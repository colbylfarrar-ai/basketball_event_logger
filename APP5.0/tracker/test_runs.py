"""Tests for helpers/runs.py — scoring-run detection, garbage-time exclusion,
momentum window, allowed counting and the record-by-run-count buckets."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _mk(team, q, clock, pts=2, gid=10):
    return {"event_type": "shot", "shot_result": "make",
            "shot_type": 3 if pts == 3 else 2, "shooter_team_id": team,
            "game_id": gid, "quarter": q, "time": clock}


def test_detect_and_momentum():
    import helpers.runs as RN
    ev = [
        _mk(1, 1, "7:30"), _mk(1, 1, "6:50"), _mk(1, 1, "6:10"),
        _mk(1, 1, "5:40", 3), _mk(1, 1, "5:00"),          # 11-0 run by team 1
        _mk(2, 1, "4:30"),                                  # answer inside 2m
        _mk(2, 1, "3:00"), _mk(1, 1, "2:00"),
    ]
    runs = RN.detect_runs(ev)
    big = [r for r in runs if r["points"] >= RN.BIG_RUN]
    ok(len(big) == 1 and big[0]["team_id"] == 1 and big[0]["points"] == 11,
       "11-0 run detected for team 1")
    r = big[0]
    ok(abs(r["secs"] - 150) < 1, f"run length = 150s clock (got {r['secs']:.0f})")
    # window = (5:00, 3:00] of Q1 clock: the 4:30 and 3:00 answers land in it
    # (edge inclusive), the 2:00 basket is outside.
    ok(r["momentum"] == -4, "opponent answered -4 inside the 2-minute window")
    ok(not r["garbage"], "1st-quarter run is not garbage time")


def test_garbage_time():
    import helpers.runs as RN
    ev = []
    # team 1 goes up 24-0 across Q1-Q3 (one long run, margin builds)
    clocks = ["7:00", "6:00", "5:00", "4:00", "3:00", "2:00"]
    for q in (1, 2):
        ev += [_mk(1, q, c) for c in clocks]
    # Q4: team 2 lands a 10-0 run starting down 24 — garbage
    ev += [_mk(2, 4, c) for c in ("7:00", "6:00", "5:00", "4:00", "3:30")]
    runs = RN.detect_runs(ev)
    g = [r for r in runs if r["team_id"] == 2]
    ok(len(g) == 1 and g[0]["garbage"], "Q4 run down 20+ flagged garbage")
    t1 = [r for r in runs if r["team_id"] == 1]
    ok(t1 and t1[0]["points"] == 24 and not t1[0]["garbage"],
       "the 24-0 itself started at 0-0 — live, not garbage")


def test_league_table_counts():
    import helpers.runs as RN
    ev = [
        _mk(1, 1, "7:30"), _mk(1, 1, "6:50"), _mk(1, 1, "6:10"),
        _mk(1, 1, "5:40"), _mk(1, 1, "5:00"),               # 10-0 team 1
        _mk(2, 2, "7:00"),
    ]
    orig = RN.query
    RN.query = lambda *a, **k: [{"id": 10, "team1_id": 1, "team2_id": 2,
                                 "home_score": 60, "away_score": 40}]
    try:
        tbl = RN.league_run_table(events=ev)
    finally:
        RN.query = orig
    ok(tbl[1]["made_pg"] == 1.0 and tbl[2]["allowed_pg"] == 1.0,
       "run credited to maker, charged to the other side")
    ok(tbl[1]["by_count"][1] == [1, 0], "team 1: 1 run in the game, a win")
    ok(tbl[2]["by_count"][0] == [0, 1], "team 2: 0 runs, a loss")
    ok(tbl[1]["biggest"] == 10, "biggest run recorded")


if __name__ == "__main__":
    test_detect_and_momentum()
    test_garbage_time()
    test_league_table_counts()
    print(f"\nALL {PASSED} CHECKS PASSED")
