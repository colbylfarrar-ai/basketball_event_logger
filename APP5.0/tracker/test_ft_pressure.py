"""Tests for clutch FT% + and-1 linking (fouls.player_foul_ft pressure walk)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ev(etype, q, time, pid=None, made=None, stype=2, team=1, eid=None,
        fouler=None):
    return {"id": eid, "game_id": 1, "event_type": etype, "quarter": q,
            "time": time, "primary_player_id": pid,
            "shot_result": ("make" if made else "miss") if made is not None else None,
            "shot_type": stype, "shooter_team_id": team,
            "secondary_player_id": fouler, "official_id": None,
            "pass_from_id": None, "shot_created_by_id": None,
            "rebound_by_id": None, "blocked_by_id": None, "guarded_by_id": None,
            "stolen_by_id": None, "rebounder_team_id": None, "zone": None,
            "play_type": None, "defense": None}


def test_and1_lone_ft_after_make():
    from helpers import fouls as FL
    evs = [
        _ev("shot", 1, "5:00", pid=10, made=True, eid=1),
        _ev("foul", 1, "5:00", pid=10, fouler=20, eid=2),
        _ev("free_throw", 1, "5:00", pid=10, made=True, eid=3),   # and-1, made
        # later: a MISSED shot then two FTs -> fouled on the miss, NOT an and-1
        _ev("shot", 1, "3:00", pid=10, made=False, eid=4),
        _ev("foul", 1, "3:00", pid=10, fouler=20, eid=5),
        _ev("free_throw", 1, "3:00", pid=10, made=True, eid=6),
        _ev("free_throw", 1, "3:00", pid=10, made=False, eid=7),
        # a make followed by a TWO-shot trip (weird data) -> not an and-1
        _ev("shot", 2, "6:00", pid=10, made=True, eid=8),
        _ev("foul", 2, "6:00", pid=10, fouler=20, eid=9),
        _ev("free_throw", 2, "6:00", pid=10, made=True, eid=10),
        _ev("free_throw", 2, "6:00", pid=10, made=True, eid=11),
    ]
    out = FL.player_foul_ft(events=evs)
    assert out[10]["and1"] == 1
    assert out[10]["and1_made"] == 1


def test_and1_other_shooter_ft_does_not_link():
    from helpers import fouls as FL
    evs = [
        _ev("shot", 1, "5:00", pid=10, made=True, eid=1),
        _ev("foul", 1, "5:00", pid=30, fouler=20, eid=2),
        _ev("free_throw", 1, "5:00", pid=30, made=True, eid=3),  # other player
    ]
    out = FL.player_foul_ft(events=evs)
    assert out.get(10, {}).get("and1", 0) == 0


def test_clutch_ft_leverage_split():
    """A late-and-close FT counts as clutch; an early one doesn't."""
    from helpers import fouls as FL
    evs = []
    eid = 1
    # a normal first half: trade baskets so the game stays close
    for i in range(10):
        evs.append(_ev("shot", 1, f"{7-i//2}:00", pid=10, made=True,
                       team=1, eid=eid)); eid += 1
        evs.append(_ev("shot", 1, f"{7-i//2}:00", pid=20, made=True,
                       team=2, eid=eid)); eid += 1
    # early FT (Q1, low leverage vs the endgame)
    evs.append(_ev("free_throw", 1, "6:00", pid=10, made=True, team=1,
                   eid=eid)); eid += 1
    # final-seconds FT in a one-possession game (max leverage)
    evs.append(_ev("free_throw", 4, "0:05", pid=10, made=False, team=1,
                   eid=eid)); eid += 1
    out = FL.player_foul_ft(events=evs)
    assert out[10]["cFTA"] >= 1, "the last-seconds FT must count as clutch"
    assert out[10]["cFTA"] < out[10]["FTA"], \
        "not every FT is clutch (the Q1 one shouldn't be)"
    assert out[10]["ClutchFT%"] is not None


def test_real_db_smoke():
    from helpers import fouls as FL
    out = FL.player_foul_ft()
    assert isinstance(out, dict)
    for d in out.values():
        assert d["cFTA"] <= d["FTA"]
        assert d["and1_made"] <= d["and1"]


if __name__ == "__main__":
    for fn in [test_and1_lone_ft_after_make, test_and1_other_shooter_ft_does_not_link,
               test_clutch_ft_leverage_split, test_real_db_smoke]:
        fn()
        print(f"PASS {fn.__name__}")
