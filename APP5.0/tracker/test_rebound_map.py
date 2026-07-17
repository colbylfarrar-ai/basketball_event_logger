"""Tests for the rebound fields on stats.located_shots + the rebound-map filter.

The ORB/DRB side is inferred by comparing the rebounder's team to the shooter's.
Getting that backwards silently swaps "second chances we created" with "boards we
gave up" — the map still renders, still looks plausible, and says the opposite of
the truth. Hence the explicit both-directions test.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _ev(shooter_team, reb_team, make=False, reb_by=7, play_type="pnr"):
    return {"event_type": "shot", "shot_result": "make" if make else "miss",
            "shot_type": 2, "shooter_team_id": shooter_team,
            "rebounder_team_id": reb_team, "rebound_by_id": reb_by,
            "game_id": 1, "quarter": 1, "time": "7:00",
            "shot_x": 10.0, "shot_y": 12.0, "zone": "C",
            "primary_player_id": 3, "guarded_by_id": None, "blocked_by_id": None,
            "play_type": play_type, "defense": "man", "possession_secs": 10}


def test_reb_off_direction():
    """reb_off True == the SHOOTER's team got its own miss back."""
    import helpers.stats as S
    shots = S.located_shots(events=[
        _ev(1, 1),        # team 1 shot, team 1 rebounded -> offensive board
        _ev(1, 2),        # team 1 shot, team 2 rebounded -> defensive board
    ])
    ok(shots[0]["reb_off"] is True,
       "rebounder on the shooter's team -> offensive board")
    ok(shots[1]["reb_off"] is False,
       "rebounder on the other team -> defensive board")


def test_reb_off_none_never_guessed():
    """Unknown stays None — never silently bucketed onto one side."""
    import helpers.stats as S
    shots = S.located_shots(events=[
        _ev(1, None, reb_by=None),     # nobody logged the board
        _ev(1, None, reb_by=7),        # rebounder logged but their team unknown
    ])
    ok(shots[0]["reb_off"] is None, "no rebounder -> None, not False")
    ok(shots[1]["reb_off"] is None, "unknown rebounder team -> None, not False")
    ok(shots[0]["reb_by"] is None and shots[1]["reb_by"] == 7,
       "reb_by passes through untouched")


def test_map_filter_excludes_makes():
    """A make has no board, so it can never appear on a rebound map."""
    import helpers.stats as S
    import helpers.dashboard.rebound_map as RM
    shots = S.located_shots(events=[
        _ev(1, 1, make=True),      # made — no board exists
        _ev(1, 1),                 # missed, own board
        _ev(1, 2),                 # missed, their board
        _ev(1, None, reb_by=None),  # missed, no rebounder logged
    ])
    off = RM._reb_shots(shots, True)
    dfn = RM._reb_shots(shots, False)
    ok(len(off) == 1, "one offensive board (the make is excluded)")
    ok(len(dfn) == 1, "one defensive board")
    ok(all(not s["make"] for s in off + dfn), "no made shot reaches the map")
    ok(len(off) + len(dfn) == 2,
       "the unlogged-rebounder miss appears on neither side")


if __name__ == "__main__":
    test_reb_off_direction()
    test_reb_off_none_never_guessed()
    test_map_filter_excludes_makes()
    print(f"\nALL {PASSED} CHECKS PASSED")
