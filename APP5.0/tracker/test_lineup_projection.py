"""
test_lineup_projection.py — unit tests for the depth-chart minutes projection (B)
and the signature-stat optimizer (C), helpers/lineup_projection.py. The core
(project_minutes, scoring, the constrained hill-climb) is tested on a fully
synthetic ctx; the DB-coupled reads (build_context, optimize_minutes on a real
team) get a structure smoke against the local DB.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.lineup_projection as LP


# ── synthetic ctx builders ──────────────────────────────────────────────────────
def _pl(name, efg=50.0, flag="solid", fga_pm=0.20, obs_min=20.0,
        dshot=45.0, stl_pm=0.05, foul=False):
    proj = {"eFG%": {"proj": efg, "flag": flag}}
    vol = {"fga_pm": fga_pm, "fta_pm": 0.05, "tpa_pm": 0.06, "tov_pm": 0.04,
           "pts_pm": 0.42, "fgm_pm": 0.09, "ast_pm": 0.05,
           "poss_pm": fga_pm + 0.44 * 0.05 + 0.04}
    return {"name": name, "proj": proj, "vol": vol, "dshot": dshot,
            "stl_pm": stl_pm, "obs_min": obs_min, "foul_prone": foul,
            "value": max(0.0, efg - 40.0)}   # stand-in Impact for the value objective


_OBS = {"PPP": 0.90, "eFG": 0.47, "3P%": 0.30, "3PAr": 0.30, "TOVr": 0.20,
        "FTr": 0.25, "ORBpct": 0.33, "AST%": 0.55, "oPPP": 0.92, "oeFG": 0.48,
        "forced": 0.20, "pace": 60.0}


def _ctx(players, sig=True):
    goals = [{"key": "eFG", "target": 0.50, "win_high": True, "fmt": "pct"},
             {"key": "TOVr", "target": 0.18, "win_high": False, "fmt": "pct"}]
    return {"team_id": 0, "team_games": 12, "players": players,
            "observed_line": dict(_OBS), "team_dshot_avg": 45.0,
            "team_stl_pm_avg": 0.05,
            "goals": goals if sig else [],
            "d_by_key": {"eFG": 1.5, "TOVr": 1.0} if sig else {},
            "sig_available": sig,
            "stars": sorted(players, key=lambda p: -players[p]["obs_min"])[:2]}


# ── B: minute-weighting is monotone + full 12-key line ─────────────────────────
def test_minute_weighting_monotone():
    players = {1: _pl("hi", efg=60.0), 2: _pl("lo", efg=40.0)}
    ctx = _ctx(players)
    more_hi = LP.project_minutes(0, {1: 100, 2: 60}, ctx)["line"]["eFG"]
    less_hi = LP.project_minutes(0, {1: 60, 2: 100}, ctx)["line"]["eFG"]
    assert more_hi > less_hi                      # more of the good shooter → higher eFG


def test_line_has_all_keys():
    players = {1: _pl("a"), 2: _pl("b")}
    line = LP.project_minutes(0, {1: 80, 2: 80}, _ctx(players))["line"]
    for k in ("PPP", "eFG", "3P%", "3PAr", "TOVr", "FTr", "ORBpct", "AST%",
              "oPPP", "oeFG", "forced", "pace"):
        assert k in line


# ── observed-unit Net folds in by credibility ──────────────────────────────────
def test_blend_unit_net():
    assert LP.blend_unit_net(0.0, None, 0) == 0.0          # no observed → model
    assert LP.blend_unit_net(0.0, 10.0, 0) == 0.0          # zero poss → model
    thin = LP.blend_unit_net(0.0, 10.0, 5)                 # thin unit ≈ ignored
    deep = LP.blend_unit_net(0.0, 10.0, 400)               # deep unit pulls hard
    assert 0.0 < thin < deep < 10.0
    assert deep > 8.0


# ── C: objective scoring + fallback ────────────────────────────────────────────
def test_signature_scoring_direction():
    goals = [{"key": "eFG", "target": 0.50, "win_high": True}]
    d = {"eFG": 2.0}
    hit = LP.score_signature({"eFG": 0.60}, goals, d)
    miss = LP.score_signature({"eFG": 0.40}, goals, d)
    assert hit > 0 > miss
    # effect-size weight scales the credit
    assert LP.score_signature({"eFG": 0.60}, goals, {"eFG": 4.0}) > hit


def test_force_net_overrides_signature():
    players = {1: _pl("a"), 2: _pl("b")}
    ctx = _ctx(players, sig=True)          # signatures ARE available
    proj = LP.project_minutes(0, {1: 80, 2: 80}, ctx)
    _, kind_auto = LP.objective_value(proj, ctx)               # auto → signature
    _, kind_net = LP.objective_value(proj, ctx, force="net")   # forced → net
    assert kind_auto == "signature"
    assert kind_net == "net"
    # end-to-end: the optimizer honors the override in its returned kind
    out = LP.optimize_minutes(0, ctx=ctx, objective="net")
    assert out["objective_kind"] == "net"


def test_value_objective_favors_high_impact():
    # player impact objective must give the higher-value players more minutes.
    # (efg drives the _pl stand-in value = max(0, efg-40); 6 players fill 160 min.)
    efgs = [72.0, 66.0, 58.0, 50.0, 46.0, 42.0]
    players = {i + 1: _pl(f"p{i+1}", efg=efgs[i], obs_min=18.0) for i in range(6)}
    ctx = _ctx(players, sig=False)
    out = LP.optimize_minutes(0, ctx=ctx, objective="value")
    assert out["objective_kind"] == "value"
    assert out["minutes"][1] > out["minutes"][6]     # highest value > lowest value


def test_objective_fallback_to_net():
    players = {1: _pl("a"), 2: _pl("b")}
    proj = LP.project_minutes(0, {1: 80, 2: 80}, _ctx(players, sig=False))
    val, kind = LP.objective_value(proj, _ctx(players, sig=False))
    assert kind == "net"
    val2, kind2 = LP.objective_value(proj, _ctx(players, sig=True))
    assert kind2 == "signature"


# ── C: constrained hill-climb (synthetic, no DB) ───────────────────────────────
def _roster_ctx(sig=True):
    mins = [24.0, 22.0, 18.0, 14.0, 10.0, 8.0]
    efgs = [58.0, 44.0, 52.0, 46.0, 50.0, 41.0]
    players = {i + 1: _pl(f"p{i+1}", efg=efgs[i], obs_min=mins[i],
                          foul=(i == 5)) for i in range(6)}
    return _ctx(players, sig)


def test_optimizer_respects_constraints_and_improves():
    ctx = _roster_ctx()
    out = LP.optimize_minutes(0, ctx=ctx)
    assert "minutes" not in out or abs(sum(out["minutes"].values()) - LP.TEAM_MIN) < 3
    # constraints: no player over their cap; foul-prone (#6) never above MAX_PP_FOUL
    for pid, m in out["minutes"].items():
        cap = LP.MAX_PP_FOUL if ctx["players"][pid]["foul_prone"] else LP.MAX_PP
        assert m <= cap + 1e-6
    # star stagger: the two stars can cover a full game
    stars = ctx["stars"]
    assert sum(out["minutes"][p] for p in stars) >= LP.STAGGER_COVER - 1e-6
    # objective is at least as good as the seed (hill-climb never regresses)
    seed = LP._seed(ctx, LP._rotation(ctx))
    seed_val, _ = LP.objective_value(LP.project_minutes(0, seed, ctx), ctx)
    assert out["objective"] >= round(seed_val, 4) - 1e-6
    assert out["objective_kind"] == "signature"


# ── DB smoke: build_context + optimize on a real team; gating on a thin team ────
def test_build_context_and_optimize_smoke():
    from database.db import query
    row = query(
        "SELECT gel.team_id tid, COUNT(DISTINCT ge.game_id) g "
        "FROM game_event_lineup gel JOIN game_events ge ON ge.id=gel.event_id "
        "GROUP BY gel.team_id ORDER BY g DESC LIMIT 1")
    if not row:
        return
    tid, g = row[0]["tid"], row[0]["g"]
    out = LP.optimize_minutes(tid)
    if g >= LP.MIN_TEAM_GAMES:
        assert "minutes" in out and out["objective_kind"] in ("signature", "net")
        assert abs(sum(out["minutes"].values()) - LP.TEAM_MIN) < 4
        tc = LP.project_team_current(tid)
        assert "net" in tc and 0.0 <= tc["win_prob_vs_avg"] <= 1.0
    else:
        assert out.get("gated")


def test_fatigue_spreads_minutes():
    # Diminishing returns must pull the optimizer off the all-at-bounds vertex:
    # at least one rotation player lands strictly between the min and max cap.
    ctx = _roster_ctx()
    out = LP.optimize_minutes(0, ctx=ctx)
    interior = [m for m in out["minutes"].values()
                if LP.MIN_PP + 1e-6 < m < LP.MAX_PP - 1e-6]
    assert interior, f"no interior minutes (all pinned to bounds): {out['minutes']}"


def test_max_rotation_limits_players():
    # 8-player roster, ask for a 6-man rotation → exactly 6 get minutes.
    mins = [24.0, 22.0, 18.0, 14.0, 12.0, 10.0, 9.0, 8.0]
    players = {i + 1: _pl(f"p{i+1}", efg=50.0 + i, obs_min=mins[i])
               for i in range(8)}
    ctx = _ctx(players)
    out = LP.optimize_minutes(0, ctx=ctx, max_rotation=6)
    assert len(out["minutes"]) == 6
    assert abs(sum(out["minutes"].values()) - LP.TEAM_MIN) < 3


def test_build_context_fallback_is_season_scoped():
    # game_ids=None must resolve the team's games FOR THE PASSED SEASON, not via
    # the 'Current'-hardcoded _team_game_ids (the archive "no tracked games" bug).
    from database.db import query
    row = query(
        "SELECT g.season s, gel.team_id tid, COUNT(DISTINCT ge.game_id) g "
        "FROM game_event_lineup gel JOIN game_events ge ON ge.id=gel.event_id "
        "JOIN games g ON g.id=ge.game_id "
        "GROUP BY gel.team_id ORDER BY g DESC LIMIT 1")
    if not row or row[0]["g"] < LP.MIN_TEAM_GAMES:
        return
    tid, season = row[0]["tid"], row[0]["s"]
    # correct season → resolves the games (not gated), and stamps ctx.game_ids
    ok = LP.build_context(tid, game_ids=None, season=season)
    assert not ok.get("gated")
    assert ok["game_ids"] and len(ok["game_ids"]) >= LP.MIN_TEAM_GAMES
    # a non-existent season → no games → gated (proves it's season-scoped)
    bad = LP.build_context(tid, game_ids=None, season="1900-1901")
    assert bad.get("gated")


def test_thin_team_is_gated():
    from database.db import query
    # a team with 1 tracked game (there are many) must gate
    row = query(
        "SELECT gel.team_id tid, COUNT(DISTINCT ge.game_id) g "
        "FROM game_event_lineup gel JOIN game_events ge ON ge.id=gel.event_id "
        "GROUP BY gel.team_id HAVING g < ? ORDER BY g ASC LIMIT 1", (LP.MIN_TEAM_GAMES,))
    if not row:
        return
    out = LP.optimize_minutes(row[0]["tid"])
    assert out.get("gated")


# ── line reads: goals_hit + compare_lines (the Compare-view engine) ─────────────
def test_goals_hit_counts_every_goal():
    goals = [{"key": "eFG", "target": 0.50, "win_high": True, "fmt": "pct"},
             {"key": "TOVr", "target": 0.18, "win_high": False, "fmt": "pct"},
             {"key": "forced", "target": 0.22, "win_high": True, "fmt": "pct"}]
    line = {"eFG": 0.52, "TOVr": 0.20}            # hit, miss, unprojectable
    hit, tot = LP.goals_hit(line, goals)
    assert (hit, tot) == (1, 3)                   # missing key counts as a miss
    assert LP.goals_hit({}, []) == (0, 0)


def test_compare_lines_direction_and_order():
    base = dict(_OBS)
    line = dict(_OBS, **{"3P%": 0.36, "ORBpct": 0.28, "oeFG": 0.46})
    edges = LP.compare_lines(line, base)
    by_key = {e["key"]: e for e in edges}
    assert by_key["3P%"]["good"] and by_key["3P%"]["diff"] > 0      # shoots better
    assert not by_key["ORBpct"]["good"]                             # rebounds worse
    assert by_key["oeFG"]["good"] and by_key["oeFG"]["diff"] < 0    # defends better
    assert "3PAr" not in by_key and "pace" not in by_key            # style ≠ trade-off
    diffs = [abs(e["diff"]) for e in edges]
    assert diffs == sorted(diffs, reverse=True)                     # biggest first
