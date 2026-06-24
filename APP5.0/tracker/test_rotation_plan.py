"""
test_rotation_plan.py — unit tests for the Tier-2 stagger / foul-trouble engine
(helpers/rotation_plan.py). Pure functions (foul_out_projection, _union_len) are
tested exactly; the DB-coupled reads (star_coverage, foul_prone) get a structure
smoke against the local DB.
"""
import helpers.rotation_plan as RP


# ── interval union ───────────────────────────────────────────────────────────
def test_union_len():
    assert RP._union_len([]) == 0.0
    assert RP._union_len([(0, 10), (5, 15)]) == 15.0      # overlap merged
    assert RP._union_len([(0, 5), (10, 15)]) == 10.0      # disjoint summed
    assert RP._union_len([(0, 10), (2, 4)]) == 10.0       # contained


# ── live foul-out projection ─────────────────────────────────────────────────
def test_foul_out_already_out():
    r = RP.foul_out_projection(5, 24, 300)
    assert r["risk"] == "out" and r["will_foul_out"] is True


def test_foul_out_no_fouls():
    r = RP.foul_out_projection(0, 20, 300)
    assert r["risk"] == "low" and r["to_foulout_min"] is None


def test_foul_out_high_one_away():
    # 4 fouls in 16 min -> 0.25/min; 1 to go -> 4 floor-min, 8 left -> fouls out
    r = RP.foul_out_projection(4, 16, 8 * 60)
    assert r["will_foul_out"] is True and r["risk"] == "high"
    assert abs(r["to_foulout_min"] - 4.0) < 1e-6
    assert abs(r["pf32"] - 8.0) < 1e-6


def test_foul_out_low_when_slow():
    # 2 fouls in 20 min -> 0.1/min; 3 to go -> 30 floor-min, 10 left -> safe
    r = RP.foul_out_projection(2, 20, 10 * 60)
    assert r["will_foul_out"] is False and r["risk"] == "low"


def test_foul_out_med_tier():
    # 3 fouls in 10 min -> 0.3/min; 2 to go -> ~6.7 min, 10 left -> fouls out but
    # not in the first 60% of remaining time, and not one-away -> med
    r = RP.foul_out_projection(3, 10, 10 * 60)
    assert r["will_foul_out"] is True and r["risk"] == "med"


# ── DB-coupled reads: structure smoke (must not raise on the local DB) ───────
def test_star_coverage_smoke():
    from database.db import query
    t = query("SELECT id FROM teams LIMIT 1")
    if not t:
        return
    out = RP.star_coverage(t[0]["id"])
    for k in ("stars", "uncovered_min_share", "bleed", "uncovered_poss", "note"):
        assert k in out


def test_foul_prone_smoke():
    from database.db import query
    t = query("SELECT id FROM teams LIMIT 1")
    if not t:
        return
    rows = RP.foul_prone(t[0]["id"])
    assert isinstance(rows, list)
    for r in rows:
        assert {"pid", "name", "fouls", "min", "pf32", "prone"} <= set(r)
