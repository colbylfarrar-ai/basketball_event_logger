"""Tests for helpers/adj_efficiency.py — opponent-adjusted eFG."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(pairs, box, monkey_teams=None):
    """Run adjusted_shooting against synthetic pairs/boxes by monkeypatching
    the two data readers."""
    from helpers import adj_efficiency as AE
    op, ob = AE._tracked_pairs, AE._game_shooting
    AE._tracked_pairs = lambda gender=None, game_ids=None, season="Current": pairs
    AE._game_shooting = lambda p: box
    try:
        return AE.adjusted_shooting("F")
    finally:
        AE._tracked_pairs, AE._game_shooting = op, ob


def _mk(fgm, tpm, fga):
    return {"FGM": float(fgm), "3PM": float(tpm), "FGA": float(fga)}


def test_schedule_correction_direction():
    """Two teams shoot an identical raw 50% eFG — but team 1 did it against the
    league's lockdown defense (everyone else shoots 30% on team 3) while team 2
    fattened up on the sieve (team 4 allows 70%). Adjusted must rank 1 > 2."""
    # teams: 1,2 = offenses under test; 3 = lockdown D; 4 = sieve D.
    # cross games let the model learn the defenses.
    pairs = [(1, 1, 3), (2, 2, 4), (3, 5, 3), (4, 5, 4), (5, 1, 3), (6, 2, 4),
             (7, 6, 3), (8, 6, 4)]
    box = {
        (1, 1): _mk(25, 0, 50), (1, 3): _mk(20, 0, 50),
        (5, 1): _mk(25, 0, 50), (5, 3): _mk(20, 0, 50),
        (2, 2): _mk(25, 0, 50), (2, 4): _mk(20, 0, 50),
        (6, 2): _mk(25, 0, 50), (6, 4): _mk(20, 0, 50),
        (3, 5): _mk(15, 0, 50), (3, 3): _mk(20, 0, 50),   # 30% on lockdown
        (4, 5): _mk(35, 0, 50), (4, 4): _mk(20, 0, 50),   # 70% on sieve
        (7, 6): _mk(15, 0, 50), (7, 3): _mk(20, 0, 50),
        (8, 6): _mk(35, 0, 50), (8, 4): _mk(20, 0, 50),
    }
    out = _run(pairs, box)
    assert out, "solver returned empty"
    assert out[1]["RawEFG"] == out[2]["RawEFG"] == 0.5
    assert out[1]["AdjeFG"] > out[2]["AdjeFG"], \
        "same raw eFG vs tougher defense must adjust higher"
    # and the defenses separate the right way (lower AdjoeFG = better D)
    assert out[3]["AdjoeFG"] < out[4]["AdjoeFG"]


def test_guards():
    from helpers import adj_efficiency as AE
    assert _run([], {}) == {}
    # single game → under row/team minimums → {}
    assert _run([(1, 1, 2)], {(1, 1): _mk(5, 0, 10), (1, 2): _mk(5, 0, 10)}) == {}


def test_real_db_smoke():
    from helpers import adj_efficiency as AE
    out = AE.adjusted_shooting("F")
    assert isinstance(out, dict)
    for tid, row in out.items():
        if tid == "_meta":
            continue
        assert 0.0 <= row["AdjeFG"] <= 1.0
        assert row["games"] >= 2


if __name__ == "__main__":
    for fn in [test_schedule_correction_direction, test_guards,
               test_real_db_smoke]:
        fn()
        print(f"PASS {fn.__name__}")
