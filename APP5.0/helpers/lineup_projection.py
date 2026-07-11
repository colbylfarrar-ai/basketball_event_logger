"""
lineup_projection.py — depth-chart minutes projection (B) + signature-stat
lineup optimizer (C), stacked on the career-player base layer.

Given a minutes allocation across a roster in a 32-minute game, B projects the
team's per-game stat line — the SAME 12 keys the Insights win/loss miner ranks
(helpers.insights_team) — so the projection can be scored directly against the
team's own signature-stat goals. C then searches minute allocations to MAXIMIZE
how many of those signature goals the lineup projects to hit (effect-size
weighted), under real coaching constraints (foul trouble, star stagger, min/max
minutes). When a team lacks the win/loss split to mine signatures, the objective
degrades to projected Net vs the average tracked team.

WHY this is honest on thin data: rates travel (projected by the base layer),
minutes are the environment weight; the offensive line is a volume-weighted mix
of projected player rates, the defensive line is the team's OBSERVED defensive
line nudged by the on-court defenders' quality. Everything is flagged directional
and team-gated behind `MIN_TEAM_GAMES` — a one-game opponent has no rotation to
project.

Pure data layer: db + stats + projection + lineups + rotation_plan +
insights_team + gameflow. No streamlit.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.projection as PJ


GAME_MIN     = 32.0     # HS regulation
TEAM_MIN     = GAME_MIN * 5       # 160 player-minutes to allocate
BLOCK        = 2.0      # minutes are placed in 2-minute blocks
MIN_TEAM_GAMES = 8      # below this a team has no rotation to project
MAX_ROTATION = 9        # players in the optimized rotation
MIN_PP       = 8.0      # per-player minute bounds: a rotation player actually rotates
MAX_PP       = 30.0     # nobody plays a full 32 wire-to-wire (rest/fatigue)
MAX_PP_FOUL  = 24.0     # cap on a chronically foul-prone player
STAGGER_COVER = 32.0    # top stars must be able to cover the whole game (stagger)

# Defense is anchored in the team's OBSERVED line and only NUDGED by the on-court
# defenders' quality — a full 1:1 swing would hallucinate elite/awful defenses on a
# thin sample. Damp the nudge and clamp it to a believable band around observed.
DEF_ADJ      = 0.35     # damping on the defender-quality nudge
DEF_CLAMP    = 0.06     # max shift of oeFG from observed (0-1 rate)
OPPP_CLAMP   = 0.10     # max shift of oPPP from observed
NET_CLAMP    = 20.0     # sanity band on projected Net (points/100) — flagged directional

# Diminishing returns: a convex penalty on minutes so the optimizer doesn't pin
# every player to a bound (the "4×30 + 5×8" vertex a LINEAR objective always
# produces). penalty = W · Σ(minutes/32)² makes concentrated minutes cost more
# than spread ones → natural rotations (24/22/18/16/…). Two weights because the
# signature score (~O(1-3)) and Net (~O(20)) live on different scales.
FATIGUE_W_SIG = 0.30
FATIGUE_W_NET = 6.0
FATIGUE_W_VAL = 2.5     # scale for the player-impact objective (Impact ~0-100)
REPLACEMENT   = 40.0    # a 0-100 Impact/OVERALL below this adds ~no value


# ══════════════════════════════════════════════════════════════════════════════
#  CONTEXT  (one DB pass; injectable for tests)
# ══════════════════════════════════════════════════════════════════════════════

def _observed_line(team_id, gids, events=None):
    """The team's OBSERVED 12-key stat line over its tracked games, in
    insights_team.team_stat_line units (rates 0-1, PPP/oPPP raw, pace = poss)."""
    import helpers.team_analytics as TA
    if events is None:
        events = S.fetch_events(gids)
    tb, ob = TA.team_and_opp_box(team_id, gids, events=events)
    poss = (tb.get("FGA", 0) or 0) + (tb.get("TOV", 0) or 0)
    opos = (ob.get("FGA", 0) or 0) + (ob.get("TOV", 0) or 0)
    sf = lambda a, b_: (a / b_) if b_ else None
    n_games = len({e["game_id"] for e in events}) or 1
    return {
        "PPP":  sf(tb.get("PTS", 0), poss),
        "eFG":  S.efg(tb) if tb.get("FGA") else None,
        "3P%":  sf(tb.get("3PM", 0), tb.get("3PA", 0)),
        "3PAr": sf(tb.get("3PA", 0), tb.get("FGA", 0)),
        "TOVr": sf(tb.get("TOV", 0), poss),
        "FTr":  sf(tb.get("FTA", 0), tb.get("FGA", 0)),
        "ORBpct": sf(tb.get("ORB", 0),
                     (tb.get("ORB", 0) or 0) + (ob.get("DRB", 0) or 0)),
        "AST%": sf(tb.get("AST", 0), tb.get("FGM", 0)),
        "oPPP": sf(ob.get("PTS", 0), opos) if opos else None,
        "oeFG": S.efg(ob) if ob.get("FGA") else None,
        "forced": sf(ob.get("TOV", 0), opos) if opos else None,
        "pace": poss / n_games,
    }


def build_context(team_id, gender=None, game_ids=None, season="Current"):
    """Assemble everything project_minutes / optimize_minutes need, in one pass.

    Returns a ctx dict, or {"gated": reason} when the team has too few tracked
    games to project a rotation. `season` scopes the stat table + signature miner
    to the season the `game_ids` belong to (a rolled-over prod is not 'Current').
    """
    # When no explicit game_ids (own team / open archive → entitlement returns
    # None = unrestricted), resolve the team's tracked games FOR `season` — NOT
    # via the 'Current'-hardcoded _team_game_ids, which reads zero on any archive
    # season (the founder's "no tracked games for 2025-2026" bug).
    if game_ids is not None:
        gids = list(game_ids)
    else:
        gids = [r["id"] for r in query(
            "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) "
            "AND tracked=1 AND season=?", (team_id, team_id, season))]
    n_games = len(gids)
    if n_games < MIN_TEAM_GAMES:
        return {"gated": f"only {n_games} tracked games (need {MIN_TEAM_GAMES})",
                "team_games": n_games}

    events = S.fetch_events(gids)
    observed = _observed_line(team_id, gids, events)

    proj = PJ.project_roster(team_id, gender=gender, game_ids=gids, season=season)
    mins = S.minutes_played(gids)
    table = __import__("helpers.player_ratings", fromlist=["x"]).player_stat_table(
        game_ids=gids, gender=gender, min_games=1, season=season)

    import helpers.rotation_plan as RP
    prone = {r["pid"] for r in RP.foul_prone(team_id, game_ids=gids) if r["prone"]}

    players = {}
    dshot_num = dshot_den = stl_num = 0.0
    for pid, pr in proj.items():
        row = table.get(pid, {})
        m = mins.get(pid, 0.0)
        if m <= 0:
            continue
        pm = lambda k: (row.get(k) or 0) / m       # per-minute observed volume
        vol = {
            "fga_pm": pm("FGA"), "fta_pm": pm("FTA"), "tpa_pm": pm("3PA"),
            "tov_pm": pm("TOV"), "pts_pm": pm("PTS"), "fgm_pm": pm("FGM"),
            "ast_pm": pm("AST"), "poss_pm": (pm("FGA") + 0.44 * pm("FTA") + pm("TOV")),
        }
        dshot = row.get("DSHOT%")
        stl_pm = pm("STL")
        # per-player VALUE for the impact objective: the 0-100 OVERALL rating
        # (the box+event composite that folds in the RAPM impact pillar; the raw
        # Impact column is often 0 until RAPM fits). Above-replacement so bench
        # value tapers to ~0 — the gradient the flat clamped team-net lacks.
        _imp = row.get("Impact") or 0.0
        _val = _imp if _imp > REPLACEMENT else (row.get("OVERALL") or 50.0)
        value = max(0.0, _val - REPLACEMENT)
        players[pid] = {
            "name": pr["name"], "proj": pr["stats"], "vol": vol,
            "dshot": dshot, "stl_pm": stl_pm, "obs_min": m,
            "foul_prone": pid in prone, "value": value,
        }
        if dshot is not None:
            dshot_num += dshot * m
            dshot_den += m
        stl_num += stl_pm * m
    team_dshot_avg = (dshot_num / dshot_den) if dshot_den else None
    team_stl_pm_avg = (stl_num / dshot_den) if dshot_den else 0.0

    # signature goals (the OBJECTIVE) — the team's own win/loss stats
    import helpers.insights_team as IT
    wl = IT.winloss_alignment(team_id, gender=gender, game_ids=gids)
    sig_available = bool(wl.get("available"))
    goals = wl.get("goals", []) if sig_available else []
    d_by_key = {r["key"]: r["d"] for r in wl.get("rows", [])} if sig_available else {}

    # stars = top-2 by observed minutes (for the stagger constraint)
    stars = sorted(players, key=lambda p: -players[p]["obs_min"])[:2]

    return {
        "team_id": team_id, "team_games": n_games, "game_ids": gids,
        "players": players, "observed_line": observed,
        "team_dshot_avg": team_dshot_avg, "team_stl_pm_avg": team_stl_pm_avg,
        "goals": goals, "d_by_key": d_by_key, "sig_available": sig_available,
        "stars": stars,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  B — project a minutes allocation to a team stat line
# ══════════════════════════════════════════════════════════════════════════════

def _pr(pl, stat, default):
    """A player's projected rate (0-100 native) or a default when unprojected."""
    s = pl["proj"].get(stat)
    if not s or s.get("proj") is None:
        return default
    return s["proj"]


def project_minutes(team_id, minutes, ctx):
    """Project the 12-key team stat line for a `minutes` = {pid: minutes} plan.

    Offensive keys = volume-weighted mix of the players' PROJECTED rates (minutes ×
    observed per-minute volume as the weight). Defensive keys = the team's OBSERVED
    defensive line nudged by the on-court defenders' quality vs the team average.
    Returns {minutes, line:{12 keys}, ortg, drtg, net, net_vs_baseline, flags}.
    """
    players = ctx["players"]
    obs = ctx["observed_line"]
    # ── offensive aggregation from projected rates × minute-scaled volumes ──
    FGA = FTA = TPA = TOV = POSS = PTS = FGM = AST = 0.0
    efg_num = tp_num = oreb_num = oreb_den = 0.0
    for pid, m in minutes.items():
        pl = players.get(pid)
        if not pl or m <= 0:
            continue
        v = pl["vol"]
        fga = v["fga_pm"] * m
        tpa = v["tpa_pm"] * m
        poss = v["poss_pm"] * m
        FGA += fga; TPA += tpa; POSS += poss
        FTA += _pr(pl, "FTR", obs["FTr"] or 0.0) * fga        # FTA = FTR·FGA (proj)
        TOV += (_pr(pl, "TOV%", (obs["TOVr"] or 0) * 100) / 100.0) * poss
        PTS += v["pts_pm"] * m
        FGM += v["fgm_pm"] * m
        AST += v["ast_pm"] * m
        efg_num += (_pr(pl, "eFG%", (obs["eFG"] or 0) * 100) / 100.0) * fga
        tp_num  += (_pr(pl, "3P%",  (obs["3P%"] or 0) * 100) / 100.0) * tpa
        w = m
        oreb_num += (_pr(pl, "OREB%", (obs["ORBpct"] or 0) * 100) / 100.0) * w
        oreb_den += w

    sf = lambda a, b_: (a / b_) if b_ else None
    line = {
        "eFG":  sf(efg_num, FGA),
        "3P%":  sf(tp_num, TPA),
        "3PAr": sf(TPA, FGA),
        "TOVr": sf(TOV, POSS),
        "FTr":  sf(FTA, FGA),
        "ORBpct": sf(oreb_num, oreb_den),
        "AST%": sf(AST, FGM),
        "PPP":  sf(PTS, POSS),
        "pace": obs["pace"],                    # style property — held
    }

    # ── defensive line: observed nudged by on-court defender quality ──
    tot_min = sum(m for m in minutes.values() if m > 0) or 1.0
    on_dshot = sum((players[p]["dshot"] or ctx.get("team_dshot_avg") or 0) * m
                   for p, m in minutes.items() if m > 0 and players.get(p)) / tot_min
    on_stl = sum((players[p]["stl_pm"] or 0) * m
                 for p, m in minutes.items() if m > 0 and players.get(p)) / tot_min
    d_avg = ctx.get("team_dshot_avg")
    s_avg = ctx.get("team_stl_pm_avg") or 0.0
    def _clamp(x, lo, hi):
        return max(lo, min(hi, x))

    d_delta = ((on_dshot - d_avg) / 100.0) if d_avg is not None else 0.0   # better D < 0
    s_delta = on_stl - s_avg                                              # more STL > 0
    # damp the nudge, then clamp each defensive stat to a believable band around observed
    oeFG0, oPPP0, forced0 = obs["oeFG"] or 0, obs["oPPP"] or 0, obs["forced"] or 0
    d_nudge = _clamp(DEF_ADJ * d_delta, -DEF_CLAMP, DEF_CLAMP)
    p_nudge = _clamp(DEF_ADJ * d_delta - 0.9 * DEF_ADJ * s_delta, -OPPP_CLAMP, OPPP_CLAMP)
    line["oeFG"]   = max(0.0, oeFG0 + d_nudge)
    line["forced"] = max(0.0, forced0 + _clamp(DEF_ADJ * s_delta, -DEF_CLAMP, DEF_CLAMP))
    line["oPPP"]   = max(0.0, oPPP0 + p_nudge)

    ortg = (line["PPP"] or 0) * 100
    drtg = (line["oPPP"] or 0) * 100
    net = _clamp(ortg - drtg, -NET_CLAMP, NET_CLAMP)
    flags = _line_flags(minutes, players)
    return {"minutes": dict(minutes), "line": line,
            "ortg": round(ortg, 1), "drtg": round(drtg, 1),
            "net": round(net, 1), "net_vs_baseline": round(net, 1),
            "flags": flags}


def _line_flags(minutes, players):
    """Directional-honesty flags: how much of the allocation is thin projection."""
    thin = 0.0
    for pid, m in minutes.items():
        pl = players.get(pid)
        if pl and m > 0:
            efg = pl["proj"].get("eFG%")
            if not efg or efg.get("flag") == "thin":
                thin += m
    tot = sum(m for m in minutes.values() if m > 0) or 1.0
    share = thin / tot
    tier = "solid" if share < 0.2 else ("directional" if share < 0.5 else "thin")
    return {"thin_minute_share": round(share, 2), "tier": tier}


_UNIT_PRIOR_POSS = 40    # possessions of the model line mixed against an observed unit


def blend_unit_net(model_net, obs_net, obs_poss):
    """Blend a projected (model) Net with an OBSERVED 5-man unit Net by the unit's
    possession credibility: a thin unit is ignored, a deep unit pulls the number.
    `model_net` is returned unchanged when there's no observed sample."""
    if obs_net is None or not obs_poss or obs_poss <= 0:
        return model_net
    c = obs_poss / (obs_poss + _UNIT_PRIOR_POSS)
    return model_net * (1 - c) + obs_net * c


def project_lineup(team_id, five, ctx, game_ids=None):
    """Project one 5-man unit (all five on the full game) and fold in that unit's
    OBSERVED Net where it has possessions — the chemistry the sum-of-parts misses.
    Returns the project_minutes payload with a `net_blended` field added."""
    minutes = {p: GAME_MIN for p in five}
    proj = project_minutes(team_id, minutes, ctx)
    obs_net = obs_poss = None
    try:
        import helpers.lineups as LU
        cu = LU.custom_unit(team_id, list(five), game_ids=game_ids)
        if cu and cu.get("poss"):
            obs_net, obs_poss = cu["Net"], cu["poss"]
    except Exception:
        pass
    proj["net_blended"] = round(blend_unit_net(proj["net"], obs_net, obs_poss), 1)
    proj["obs_unit_poss"] = obs_poss or 0
    return proj


# ══════════════════════════════════════════════════════════════════════════════
#  LINE READS — shared by every surface that shows a projected line
# ══════════════════════════════════════════════════════════════════════════════

# Winning direction per 12-key stat (+1 = higher is better). Style properties
# (3PAr, pace) are deliberately absent — a 3-point-heavy mix is a choice, not a
# win/loss lever, so it never shows up as a "give" or a "take".
KEY_DIRECTION = {"eFG": 1, "3P%": 1, "TOVr": -1, "FTr": 1, "ORBpct": 1,
                 "AST%": 1, "PPP": 1, "oeFG": -1, "oPPP": -1, "forced": 1}

KEY_LABELS = {"eFG": "eFG%", "3P%": "3P%", "3PAr": "3PA rate", "TOVr": "TOV%",
              "FTr": "FT rate", "ORBpct": "ORB%", "AST%": "AST%", "PPP": "PPP",
              "oeFG": "opp eFG%", "oPPP": "opp PPP", "forced": "forced TO%",
              "pace": "pace"}


def goals_hit(line, goals):
    """(hit, total) — how many of the team's mined signature goals a projected
    line reaches. `total` counts every goal, so an unprojectable key reads as a
    miss rather than silently shrinking the denominator."""
    n = 0
    for g in goals:
        v = line.get(g["key"])
        if v is None:
            continue
        if (v >= g["target"]) if g["win_high"] else (v <= g["target"]):
            n += 1
    return n, len(goals)


def compare_lines(line, base):
    """The give-and-take of one projected line vs another: directional diffs
    [{key,label,diff,good}] sorted by |diff| desc. Only KEY_DIRECTION stats
    participate (all live on a comparable 0-1-ish scale), so the top entries are
    the honest trade-offs — what this lineup buys and what it pays."""
    out = []
    for k, d in KEY_DIRECTION.items():
        a, b = line.get(k), base.get(k)
        if a is None or b is None:
            continue
        diff = a - b
        if abs(diff) < 1e-9:
            continue
        out.append({"key": k, "label": KEY_LABELS.get(k, k),
                    "diff": diff, "good": (diff * d) > 0})
    out.sort(key=lambda r: -abs(r["diff"]))
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  OBJECTIVES
# ══════════════════════════════════════════════════════════════════════════════

def _reward(value, target, win_high):
    """Signed, saturating credit for a projected stat vs its goal threshold.
    Positive when on the winning side; scales with the margin past the target."""
    if value is None or target is None:
        return 0.0
    denom = abs(target) if abs(target) > 1e-9 else 1.0
    frac = (value - target) / denom
    frac = max(-1.0, min(1.0, frac))
    return frac if win_high else -frac


def score_signature(line, goals, d_by_key):
    """Effect-size-weighted attainment of the team's signature goals."""
    total = 0.0
    for g in goals:
        w = abs(d_by_key.get(g["key"], 1.0))
        total += w * _reward(line.get(g["key"]), g["target"], g["win_high"])
    return total


def _fatigue_penalty(minutes):
    """Convex cost of concentrating minutes (Σ(m/32)²). Minimized by a spread
    allocation, maximized by pinning players to the max — so subtracting it pulls
    the optimizer off the all-or-nothing vertex into a realistic rotation."""
    return sum((m / GAME_MIN) ** 2 for m in minutes.values() if m > 0)


def score_value(minutes, players):
    """Minute-weighted per-player value (above-replacement Impact) — the gradient
    the flat clamped team-net lacks, so 'play your best players' actually varies."""
    return sum((players.get(p, {}).get("value", 0.0)) * m
               for p, m in minutes.items() if m > 0) / TEAM_MIN


def objective_value(proj, ctx, force=None):
    """The objective for a projected allocation, minus the diminishing-returns
    (fatigue) penalty. `force` picks the target:
        None        auto — signature when the team has mined signatures, else net
        "signature" signature when available, else net
        "value"     minute-weighted player Impact (the 'play your best' lever)
        "net"       always Net vs the average tracked team
    """
    pen = _fatigue_penalty(proj["minutes"])
    if force == "value":
        return score_value(proj["minutes"], ctx["players"]) - FATIGUE_W_VAL * pen, "value"
    use_sig = (force != "net"
               and ctx.get("sig_available") and ctx.get("goals"))
    if use_sig:
        raw = score_signature(proj["line"], ctx["goals"], ctx["d_by_key"])
        return raw - FATIGUE_W_SIG * pen, "signature"
    return proj["net_vs_baseline"] - FATIGUE_W_NET * pen, "net"


# ══════════════════════════════════════════════════════════════════════════════
#  C — optimize the minutes allocation (constrained hill-climb)
# ══════════════════════════════════════════════════════════════════════════════

def _rotation(ctx, max_rotation=MAX_ROTATION):
    """The optimizable rotation: top-`max_rotation` players by observed minutes."""
    # floor at 6: a 5-man rotation can't fill 160 min under the 30-min cap
    # (5×30=150) — it would force everyone to a full 32 with no bench.
    n = max(6, min(int(max_rotation or MAX_ROTATION), 10))
    return sorted(ctx["players"], key=lambda p: -ctx["players"][p]["obs_min"])[:n]

def _max_pp(ctx, pid):
    return MAX_PP_FOUL if ctx["players"][pid]["foul_prone"] else MAX_PP


def _feasible(minutes, ctx):
    """Constraint check: per-player bounds + star stagger coverage."""
    for pid, m in minutes.items():
        if m < MIN_PP - 1e-9 or m > _max_pp(ctx, pid) + 1e-9:
            return False
    stars = [p for p in ctx["stars"] if p in minutes]
    if stars:
        # the stars must be able to keep ≥1 on the floor the whole game (stagger):
        # their minutes have to sum to at least a full game, none exceeding a game.
        if sum(minutes[p] for p in stars) < STAGGER_COVER - 1e-9:
            return False
    return True


def _seed(ctx, rotation):
    """Initial allocation ∝ observed minutes, in 2-minute blocks, summing to 160,
    then repaired toward feasibility (bounds, stars covered)."""
    obs = {p: max(ctx["players"][p]["obs_min"], 1.0) for p in rotation}
    tot = sum(obs.values())
    raw = {p: TEAM_MIN * obs[p] / tot for p in rotation}
    minutes = {p: min(_max_pp(ctx, p), max(MIN_PP, round(raw[p] / BLOCK) * BLOCK))
               for p in rotation}
    _rebalance(minutes, ctx, rotation)
    # ensure star coverage by topping up stars first if short
    stars = [p for p in ctx["stars"] if p in minutes]
    guard = 0
    while stars and sum(minutes[p] for p in stars) < STAGGER_COVER and guard < 200:
        s = min(stars, key=lambda p: minutes[p])
        donor = max((p for p in rotation if p not in stars),
                    key=lambda p: minutes[p], default=None)
        if donor is None or minutes[donor] < BLOCK or minutes[s] + BLOCK > _max_pp(ctx, s):
            break
        minutes[donor] -= BLOCK
        minutes[s] += BLOCK
        guard += 1
    return minutes


def _rebalance(minutes, ctx, rotation):
    """Add/remove blocks until the allocation sums to exactly TEAM_MIN."""
    guard = 0
    while abs(sum(minutes.values()) - TEAM_MIN) > 1e-6 and guard < 500:
        diff = sum(minutes.values()) - TEAM_MIN
        if diff > 0:                                    # too many minutes: trim biggest
            # trim the largest player still above the floor
            cands = [x for x in rotation if minutes[x] - BLOCK >= MIN_PP - 1e-9]
            if not cands:
                break
            p = max(cands, key=lambda x: minutes[x])
            minutes[p] -= BLOCK
        else:                                           # too few: add to the smallest
            cands = [x for x in rotation if minutes[x] + BLOCK <= _max_pp(ctx, x) + 1e-9]
            if not cands:
                break
            p = min(cands, key=lambda x: minutes[x])
            minutes[p] += BLOCK
        guard += 1


def optimize_minutes(team_id, gender=None, game_ids=None, ctx=None, max_iters=400,
                     season="Current", max_rotation=MAX_ROTATION, objective=None):
    """Search a minutes allocation that maximizes the team's objective.

    Constrained 2-minute-swap hill-climb from an observed-minutes seed. Returns
    {gated?} | {minutes, projection, objective, objective_kind, iterations,
    observed, diff}. `diff` compares the recommendation to the team's observed
    minutes — the "extra wins" prescription. `max_rotation` (6-10 typical) is how
    many players the coach wants in the rotation.
    """
    if ctx is None:
        ctx = build_context(team_id, gender=gender, game_ids=game_ids, season=season)
    if ctx.get("gated"):
        return {"gated": ctx["gated"], "team_games": ctx.get("team_games")}

    rotation = _rotation(ctx, max_rotation)
    minutes = _seed(ctx, rotation)
    proj = project_minutes(team_id, minutes, ctx)
    best_val, kind = objective_value(proj, ctx, force=objective)

    iters = 0
    improved = True
    while improved and iters < max_iters:
        improved = False
        for a in rotation:
            for b in rotation:
                if a == b or minutes[a] < BLOCK:
                    continue
                if minutes[b] + BLOCK > _max_pp(ctx, b):
                    continue
                trial = dict(minutes)
                trial[a] -= BLOCK
                trial[b] += BLOCK
                if not _feasible(trial, ctx):
                    continue
                tp = project_minutes(team_id, trial, ctx)
                val, _ = objective_value(tp, ctx, force=objective)
                if val > best_val + 1e-9:
                    minutes, proj, best_val = trial, tp, val
                    improved = True
            iters += 1
            if iters >= max_iters:
                break

    observed = {p: round(ctx["players"][p]["obs_min"], 1) for p in rotation}
    # normalize observed to a 160-min basis for a fair diff
    otot = sum(observed.values()) or 1.0
    obs_norm = {p: round(TEAM_MIN * observed[p] / otot, 1) for p in rotation}
    diff = {p: round(minutes[p] - obs_norm[p], 1) for p in rotation}
    return {
        "minutes": {p: round(minutes[p], 1) for p in rotation},
        "projection": proj, "objective": round(best_val, 4),
        "objective_kind": kind, "iterations": iters,
        "observed": obs_norm, "diff": diff,
        "signature_goals": ctx.get("goals", []),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  D-PLUMBING — current-roster team projection (honest today; YoY at season 2)
# ══════════════════════════════════════════════════════════════════════════════

def project_team_current(team_id, gender=None, game_ids=None, ctx=None,
                         season="Current"):
    """Project the CURRENT roster's team rating from its optimized allocation and
    a win probability vs the average tracked team. Not a next-season claim — it
    becomes the year-to-year engine unchanged once identity sees a 2nd season."""
    opt = optimize_minutes(team_id, gender=gender, game_ids=game_ids, ctx=ctx,
                           season=season)
    if opt.get("gated"):
        return {"gated": opt["gated"]}
    net = opt["projection"]["net_vs_baseline"]
    import helpers.predictor as PRED
    wp = PRED.win_prob_from_margin(net)          # vs a net-zero average team
    return {
        "line": opt["projection"]["line"],
        "ortg": opt["projection"]["ortg"], "drtg": opt["projection"]["drtg"],
        "net": net, "win_prob_vs_avg": round(wp, 3),
        "minutes": opt["minutes"], "objective_kind": opt["objective_kind"],
    }
