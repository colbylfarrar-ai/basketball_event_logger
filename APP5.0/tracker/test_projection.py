"""
test_projection.py — unit tests for the career-player projection base layer
(helpers/projection.py). Pure blend/prior logic is tested exactly on synthetic
stat rows; the DB-coupled reads (project_roster, tracked_baseline, career window)
get a structure smoke against the local DB.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.projection as PJ
import helpers.shrinkage as SH


def _row(pid, GP=1, efg=None, fga=0.0, fta=0.0, team_id=1):
    """A minimal stat_table-shaped row (identifier kwargs mapped to the %-keys)."""
    return {"name": f"P{pid}", "team": "T", "team_id": team_id, "class": "SR",
            "GP": GP, "FGA": fga, "FTA": fta, "3PA": 0.0, "TOV": 0.0,
            "MIN": 0.0, "PotAST": 0.0, "RimDShots": 0.0, "PerimDShots": 0.0,
            "eFG%": efg}


# ── credibility monotonic in volume (core blend) ────────────────────────────────
def test_credibility_monotonic():
    prior = 50.0
    # own rate 70, prior 50: more FGA volume -> proj closer to own, c higher
    lo = SH.stabilize_value(70.0, 5, prior, PJ.K)
    hi = SH.stabilize_value(70.0, 100, prior, PJ.K)
    assert prior < lo < hi < 70.0
    c_lo = 5 / (5 + PJ.K)
    c_hi = 100 / (100 + PJ.K)
    assert c_lo < c_hi


# ── 3-game cameo is a near-even blend; deep sample is ~own rate ─────────────────
def test_thin_vs_deep_blend():
    table = {
        1: _row(1, GP=3,  efg=70.0, fga=12.0),    # ~3 games of shots
        2: _row(2, GP=21, efg=70.0, fga=210.0),   # deep sample, same rate
        3: _row(3, GP=8,  efg=40.0, fga=80.0),    # pulls the league prior down
    }
    priors = PJ.build_priors(table)
    p3 = PJ.project_player(1, table, priors)["stats"]["eFG%"]
    p21 = PJ.project_player(2, table, priors)["stats"]["eFG%"]
    # deep player keeps most of their edge; thin player is dragged toward the
    # prior. Thresholds anchor to the module's own credibility ladder so the
    # test tracks the contract, not a hardcoded K (K recalibrated 12 -> 60 on
    # the 2025-2026 full-season backtest).
    assert p21["c"] > PJ._SOLID_C
    assert p3["c"] < PJ._THIN_C
    assert abs(p21["proj"] - 70.0) < abs(p3["proj"] - 70.0)
    assert p3["flag"] == "thin"
    assert p21["flag"] == "solid"


# ── prior degrades archetype -> league below the sample gate ────────────────────
def test_prior_degrades_to_league():
    table = {
        1: _row(1, GP=10, efg=60.0, fga=100.0),
        2: _row(2, GP=10, efg=55.0, fga=100.0),
    }
    clusters = {1: "Slasher", 2: "Slasher"}
    priors = PJ.build_priors(table, clusters)
    # archetype 'Slasher' has 200 FGA of evidence (>= gate) -> archetype prior
    _, src_ok = PJ._select_prior("eFG%", "Slasher", priors)
    assert src_ok == "archetype"
    # a made-up archetype with no pool falls back to league
    _, src_fb = PJ._select_prior("eFG%", "Ghost", priors)
    assert src_fb == "league"
    # tighten the gate above the evidence -> archetype no longer trusted
    old = PJ.ARCHETYPE_MIN_OPP
    try:
        PJ.ARCHETYPE_MIN_OPP = 10_000.0
        _, src_thin = PJ._select_prior("eFG%", "Slasher", priors)
        assert src_thin == "league"
    finally:
        PJ.ARCHETYPE_MIN_OPP = old


# ── delta vs baseline sign is correct ───────────────────────────────────────────
def test_delta_sign():
    table = {
        1: _row(1, GP=20, efg=70.0, fga=200.0),   # above average
        2: _row(2, GP=20, efg=40.0, fga=200.0),   # below average
    }
    priors = PJ.build_priors(table)
    hi = PJ.project_player(1, table, priors)["stats"]["eFG%"]
    lo = PJ.project_player(2, table, priors)["stats"]["eFG%"]
    assert hi["delta"] > 0
    assert lo["delta"] < 0


# ── zero-opportunity player: prior + thin flag, no crash ────────────────────────
def test_zero_opp_is_thin():
    table = {
        1: _row(1, GP=8, efg=55.0, fga=80.0),
        2: _row(2, GP=1, efg=None, fga=0.0),      # never shot
    }
    priors = PJ.build_priors(table)
    p = PJ.project_player(2, table, priors)
    s = p["stats"]["eFG%"]
    assert s["flag"] == "thin"
    assert s["own"] is None
    assert s["proj"] == round(priors["league"]["eFG%"], 2)   # falls to the prior


# ── DB smoke: project_roster + baseline + career window must not raise ───────────
def test_project_roster_smoke():
    from database.db import query
    row = query(
        "SELECT team_id, COUNT(*) n FROM players GROUP BY team_id "
        "ORDER BY n DESC LIMIT 1")
    if not row:
        return
    tid = row[0]["team_id"]
    out = PJ.project_roster(tid)
    assert isinstance(out, dict)
    for pid, proj in out.items():
        assert {"pid", "archetype", "class", "games", "confidence", "stats"} <= set(proj)
        for name, s in proj["stats"].items():
            assert {"own", "prior", "proj", "c", "delta", "prior_src", "flag"} <= set(s)
        break


def test_tracked_baseline_smoke():
    base = PJ.tracked_baseline()
    assert isinstance(base, dict)
    # every stat key that appears is one of the specs
    spec_names = {s[0] for s in PJ._STAT_SPECS}
    assert set(base) <= spec_names


def test_career_window_smoke():
    from database.db import query
    row = query(
        "SELECT gel.player_id pid, COUNT(DISTINCT ge.game_id) g "
        "FROM game_event_lineup gel JOIN game_events ge ON ge.id=gel.event_id "
        "GROUP BY gel.player_id ORDER BY g DESC LIMIT 1")
    if not row:
        return
    gids = PJ.career_game_ids(row[0]["pid"])
    assert isinstance(gids, list) and len(gids) >= 1
