"""
Unit test for retro on-court-five correction (maintenance batch #2).
Builds a real missed-sub game through the LIVE write path (helpers.game_events
.log_event, which snapshots game_event_lineup + credits +/- incrementally), then
exercises the new event_log engine:
  * recompute_game_plus_minus() reproduces the live incremental +/- exactly
    (faithfulness cross-check — the from-scratch recompute must match reality),
  * correct_floor_forward() detects the contiguous stale run, replaces only the
    target team's snapshot across it, and recomputes +/- so credit moves from the
    player who wrongly stayed on to the one who was really subbed in,
  * floor_integrity() flags events whose team floor != 5.
Run: python tracker/test_retro_floor.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_retro_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, query, execute      # noqa: E402
import helpers.game_events as GE                                  # noqa: E402
import helpers.event_log as EL                                    # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── seed two teams, rosters, a game ───────────────────────────────────────────
execute("INSERT INTO teams (id, name, class, gender) VALUES (1,'Home','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (2,'Away','3A','F')")
for pid in (101, 102, 103, 104, 105, 106):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)",
            (pid, f"H{pid}", pid))
for pid in (201, 202, 203, 204, 205):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,2,?,?)",
            (pid, f"A{pid}", pid))
G = execute("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-01')")

T2 = [(201, 2), (202, 2), (203, 2), (204, 2), (205, 2)]
FIVE_START = [(101, 1), (102, 1), (103, 1), (104, 1), (105, 1)]   # 105 in
FIVE_FIXED = [(101, 1), (102, 1), (103, 1), (104, 1), (106, 1)]   # 106 in (real sub)


def shot(pid, made, three=False, floor1=FIVE_START):
    ev = {"event_type": "shot", "quarter": 1, "time": "5:00",
          "primary_player_id": pid, "shot_result": "make" if made else "miss",
          "shot_type": 3 if three else 2}
    return GE.log_event(G, ev, floor1 + T2)


# e1: 101 makes 2 (home +2). e2: 201 makes 2 (away +2).
e1 = shot(101, True)
e2 = shot(201, True)
# e3,e4: 105 SHOULD have been subbed out for 106, but the picker still shows 105.
e3 = shot(102, True, three=True)          # home +3, wrong floor (105 on)
e4 = shot(103, True)                      # home +2, wrong floor (105 on)
# e5: coach caught it — floor now has 106, not 105. 201 makes 2 (away +2).
e5 = GE.log_event(G, {"event_type": "shot", "quarter": 1, "time": "2:00",
                      "primary_player_id": 201, "shot_result": "make",
                      "shot_type": 2}, FIVE_FIXED + T2)


def pm(pid):
    r = query("SELECT plus_minus FROM game_lineup_players WHERE game_id=? AND player_id=?",
              (G, pid))
    return r[0]["plus_minus"] if r else None


# ── live incremental +/- (the ground truth the app shows today) ───────────────
live = {p: pm(p) for p in (101, 105, 106, 201)}
print("live incremental +/- (wrong-floor scenario)")
ok(live[105] == 5, f"105 wrongly credited +5 (e1+2,e2-2,e3+3,e4+2), got {live[105]}")
ok(live[106] == -2, f"106 only on floor at e5 -> -2, got {live[106]}")

print("recompute_game_plus_minus is faithful to the live path")
before = {p: pm(p) for p in (101, 102, 103, 104, 105, 106, 201, 202)}
EL.recompute_game_plus_minus(G)
after = {p: pm(p) for p in (101, 102, 103, 104, 105, 106, 201, 202)}
ok(after == before, f"from-scratch recompute == live incremental (before={before} after={after})")

print("floor_integrity flags nothing (every floor is exactly 5)")
ok(EL.floor_integrity(G) == [], "no != 5 floors in a clean 5-on-5 game")

print("correct_floor_forward fixes the missed sub from e3")
res = EL.correct_floor_forward(G, e3, 1, [101, 102, 103, 104, 106])
ok(sorted(res["events_changed"]) == [e3, e4],
   f"contiguous stale run = e3,e4 (stops at e5), got {res['events_changed']}")
# e3/e4 now carry 106 not 105; e1/e2/e5 untouched
f3 = {r["player_id"] for r in query(
    "SELECT player_id FROM game_event_lineup WHERE event_id=? AND team_id=1", (e3,))}
ok(f3 == {101, 102, 103, 104, 106}, f"e3 home floor swapped to 106, got {f3}")
f1 = {r["player_id"] for r in query(
    "SELECT player_id FROM game_event_lineup WHERE event_id=? AND team_id=1", (e1,))}
ok(f1 == {101, 102, 103, 104, 105}, f"e1 home floor untouched, got {f1}")

print("+/- moved from 105 to 106 after the fix")
ok(pm(105) == 0, f"105 now only e1,e2 (+2-2)=0, got {pm(105)}")
ok(pm(106) == 3, f"106 now e3,e4,e5 (+3+2-2)=3, got {pm(106)}")
ok(pm(101) == 3, f"101 on floor all 5 events (+2-2+3+2-2)=3 unchanged, got {pm(101)}")

print("dedupe + != 5 handling")
res2 = EL.correct_floor_forward(G, e1, 1, [101, 101, 102, 103, 104, 105])  # dup 101
f1b = {r["player_id"] for r in query(
    "SELECT player_id FROM game_event_lineup WHERE event_id=? AND team_id=1", (e1,))}
ok(f1b == {101, 102, 103, 104, 105}, f"duplicate pid deduped on write, got {f1b}")

print(f"\nALL {PASS} ASSERTS PASS")
