"""
test_concession.py — unit tests for the Tier-2 concession / shot-selection maps
(helpers/concession.py). Builds an xPP-Q model from synthetic shots, then feeds
crafted zone shots (all-make / all-miss → deterministic residual signs) to assert the
per-zone aggregation and the over/under-use flags. No DB (shots passed directly).
"""
import math

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.concession as CO
import helpers.shotquality as SQ

HOOP_Y = SQ.HOOP_Y


def _model():
    shots = []
    for d in range(1, 26):
        for k in range(20):
            x, y = 0.0, HOOP_Y + d
            value = 3 if d >= 20 else 2
            guarded = (k % 2 == 0)
            rate = max(0.20, 0.72 - 0.02 * d) - (0.10 if guarded else 0.0)
            shots.append({"x": x, "y": y, "value": value, "guarded": guarded,
                          "make": (k / 20.0) < rate, "dist": math.hypot(x, y - HOOP_Y)})
    return SQ.fit_league_model(shots=shots)


def _zone_shots():
    """C: 30 rim makes · LW: 30 mid misses · RC: 6 corner-3 makes (total 66)."""
    out = []
    for _ in range(30):
        out.append({"x": 0.0, "y": HOOP_Y + 2, "value": 2, "guarded": False,
                    "make": True, "zone": "C"})
        out.append({"x": -12.0, "y": HOOP_Y + 12, "value": 2, "guarded": False,
                    "make": False, "zone": "LW"})
    for _ in range(6):
        out.append({"x": 19.0, "y": HOOP_Y + 1.5, "value": 3, "guarded": False,
                    "make": True, "zone": "RC"})
    return out


def test_zone_breakdown_totals_and_residual_signs():
    m = _model()
    rows, total, avg_x = CO.zone_breakdown(_zone_shots(), m)
    assert total == 66
    by = {r["zone"]: r for r in rows}
    assert len(rows) == 5                                   # all five zones present
    assert by["C"]["n"] == 30 and abs(by["C"]["share"] - 30 / 66) < 1e-6
    assert by["C"]["residual"] > 0                          # all makes -> over expected
    assert by["LW"]["residual"] < 0                         # all misses -> under
    assert by["RC"]["residual"] > 0
    assert by["LC"]["pps"] is None and by["LC"]["n"] == 0    # empty zone -> None rate
    assert 0.0 < avg_x < 3.0


def test_defense_concession_structure():
    m = _model()
    out = CO.defense_concession(model=m, shots=_zone_shots())
    assert out["leaks"], "expected at least one leak zone"
    xs = [r["xpps"] for r in out["leaks"]]
    assert xs == sorted(xs, reverse=True)                   # leaks sorted by xPPS desc
    assert all(r["n"] >= CO.MIN_ZONE for r in out["leaks"])
    # leaks above the defense average, locked at/below it (disjoint)
    leak_z = {r["zone"] for r in out["leaks"]}
    lock_z = {r["zone"] for r in out["locked"]}
    assert not (leak_z & lock_z)


def test_shot_selection_overshoot_and_underused():
    m = _model()
    out = CO.shot_selection(model=m, shots=_zone_shots())
    over = {r["zone"] for r in out["overshoot"]}
    under = {r["zone"] for r in out["underused"]}
    assert "LW" in over          # 45% share, all misses -> residual<0
    assert "RC" in under         # ~9% share, all makes -> residual>0, n=6>=MIN_ZONE
    assert "C" not in over       # high share but residual>0, not a leak


def test_handles_empty_shots():
    m = _model()
    out = CO.defense_concession(model=m, shots=[])
    assert out["leaks"] == [] and "yet" in out["note"]
    sel = CO.shot_selection(model=m, shots=[])
    assert sel["overshoot"] == [] and sel["underused"] == []
