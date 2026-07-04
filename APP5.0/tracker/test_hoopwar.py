"""Tests for helpers/hoopwar.py — the WAR chain math + guards."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_wins_per_point_nba_sanity():
    """k=14 at NBA scoring (~112/g) must land on the classic ~32 pts/win."""
    from helpers import hoopwar as HW
    wpp = HW.wins_per_point(112.0)
    assert abs(1.0 / wpp - 32.0) < 0.5


def test_wins_per_point_guard():
    from helpers import hoopwar as HW
    assert HW.wins_per_point(None) is None
    assert HW.wins_per_point(0) is None


def test_war_table_math():
    """Hand-checked chain at HS scoring (P=50 → 0.07 wins/pt)."""
    from helpers import hoopwar as HW
    rapm = {
        1: {"ORAPM": 4.0, "DRAPM": 2.0, "RAPM": 6.0,
            "off_poss": 300, "def_poss": 300, "name": "Star", "team": "T"},
        2: {"ORAPM": -1.0, "DRAPM": -1.0, "RAPM": -2.0,
            "off_poss": 100, "def_poss": 100, "name": "Bench", "team": "T"},
        3: {"ORAPM": 0.0, "DRAPM": 0.0, "RAPM": 0.0,
            "off_poss": 200, "def_poss": 200, "name": "Avg", "team": "T"},
    }
    orig = HW.league_ppg
    HW.league_ppg = lambda gender=None, season="Current": 50.0
    try:
        out = HW.war_table("F", rapm=rapm)
    finally:
        HW.league_ppg = orig

    # Star: net = (4·300 + 2·300)/100 = 18; repl debit = −3·300/100 = −9
    #       → 27 pts added → 27 × 0.07 = 1.89 WAR
    assert abs(out[1]["WAR"] - 1.89) < 0.01
    # Bench: net −2, debit −3 → +1 pt → 0.07 WAR (below-average can still clear
    # replacement)
    assert abs(out[2]["WAR"] - 0.07) < 0.01
    # The defining WAR property: an exactly-AVERAGE player earns positive WAR
    # over floor time (0 is replacement, not average).
    assert out[3]["WAR"] > 0
    # More floor time at the same rate = more WAR (Avg 400 poss vs Bench 200).
    assert out[3]["WAR"] > out[2]["WAR"]
    assert out["_meta"]["pts_per_win"] == round(1 / 0.07, 1)


def test_war_table_guards():
    from helpers import hoopwar as HW
    assert HW.war_table("F", rapm={}) == {}
    orig = HW.league_ppg
    HW.league_ppg = lambda gender=None, season="Current": None   # no finished scores
    try:
        assert HW.war_table("F", rapm={1: {"ORAPM": 1, "DRAPM": 1,
                                           "off_poss": 10, "def_poss": 10}}) == {}
    finally:
        HW.league_ppg = orig


def test_war_table_real_db_smoke():
    """Whatever the local DB holds, war_table must return a dict and never raise."""
    from helpers import hoopwar as HW
    out = HW.war_table("F")
    assert isinstance(out, dict)
    for pid, row in out.items():
        if pid == "_meta":
            continue
        assert "WAR" in row and isinstance(row["WAR"], float)


if __name__ == "__main__":
    for fn in [test_wins_per_point_nba_sanity, test_wins_per_point_guard,
               test_war_table_math, test_war_table_guards,
               test_war_table_real_db_smoke]:
        fn()
        print(f"PASS {fn.__name__}")
