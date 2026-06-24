"""
test_ref_tendencies.py — unit tests for the Tier-2 pre-game crew outlook
(helpers/ref_tendencies.py). Stubs officials.official_overview with canned rows so
the league-relative synthesis (whistle / lean / scoring / confidence) is checked
exactly, no DB.
"""
import helpers.ref_tendencies as RT
import helpers.officials as OFF


def _overview():
    def row(pk, name, games, fouls, gposs, ppp, hf, af, q4):
        return {"off_pk": pk, "name": name, "games": games, "fouls": fouls,
                "game_poss": gposs, "PPP": ppp, "home_fouls": hf, "away_fouls": af,
                "ha_diff": hf - af, "q4": q4}
    return {"officials": [
        row(1, "Tight Homer", 5, 50, 500, 1.0, 30, 10, 20),   # fp100 10, home lean
        row(2, "Average", 5, 30, 500, 1.0, 15, 15, 5),        # fp100 6
        row(3, "Lenient", 5, 20, 500, 1.0, 10, 10, 3),        # fp100 4, even
        row(4, "Thin", 2, 8, 100, 1.0, 4, 4, 2),              # fp100 8, low games
    ], "teams": {}}


def _swap(fn):
    orig = OFF.official_overview
    OFF.official_overview = fn
    return orig


def test_tight_home_crew():
    orig = _swap(lambda **k: _overview())
    try:
        out = RT.crew_outlook([1])
    finally:
        OFF.official_overview = orig
    assert out["whistle"] == "tight"          # 10 vs ~6.67 league
    assert out["lean"] == "home" and out["lean_pct"] == 50
    assert out["confident"] is True
    assert any("calls it late" in t for t in out["tags"])   # q4 40%
    assert not out["summary"].startswith("Low-confidence")


def test_lenient_even_crew():
    orig = _swap(lambda **k: _overview())
    try:
        out = RT.crew_outlook([3])
    finally:
        OFF.official_overview = orig
    assert out["whistle"] == "lenient" and out["lean"] == "even"


def test_combined_crew_weights_both():
    orig = _swap(lambda **k: _overview())
    try:
        out = RT.crew_outlook([1, 2])
    finally:
        OFF.official_overview = orig
    assert out["crew_fp100"] == 8.0          # mean(10, 6)
    assert out["games"] == 10 and out["lean"] == "home"


def test_low_confidence_flag():
    orig = _swap(lambda **k: _overview())
    try:
        out = RT.crew_outlook([4])
    finally:
        OFF.official_overview = orig
    assert out["confident"] is False
    assert out["summary"].startswith("Low-confidence")


def test_unknown_crew_none():
    orig = _swap(lambda **k: _overview())
    try:
        assert RT.crew_outlook([999]) is None
        assert RT.crew_outlook([]) is None
    finally:
        OFF.official_overview = orig
