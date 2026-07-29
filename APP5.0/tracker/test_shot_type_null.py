"""
Unit test for a made shot carrying a NULL shot_type.

The defect this pins: retyping an event INTO a shot through the editor left
shot_type NULL, because update_event only ever nulled it (for non-shots) and
never defaulted it. NULL was then read two incompatible ways:

  * the scoring helpers use `3 if shot_type == 3 else 2`, so they scored it 2 —
    which is what event_points feeds the +/- ledger;
  * a handful of readers took the raw value (`pts = e["shot_type"]`), which is
    None — TypeError on `stats[sh]["pts"] += pts` in the tracker's box score,
    and a silently-dropped basket elsewhere.

So the same event was worth 2 to +/- and 0-or-a-crash to the scoreboard, and
the two disagreed for the life of the game.

Covers:
  * update_event defaults a shot's shot_type to 2, matching log_event's live
    rule, so the NULL can't be created in the first place,
  * a 3 given explicitly still survives the edit,
  * a non-shot still has its shot_type cleared,
  * a row that ALREADY holds NULL (written before the fix) scores 2 everywhere
    instead of crashing — compute_box, box_score, event_points and the quarter
    scores all agree,
  * +/- and the scoreboard agree on such a row.
Run: python tracker/test_shot_type_null.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_stype_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, query, execute      # noqa: E402
import helpers.game_events as GE                                  # noqa: E402
import helpers.event_log as EL                                    # noqa: E402
import helpers.box_score as BX                                    # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


execute("INSERT INTO teams (id, name, class, gender) VALUES (1,'Home','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (2,'Away','3A','F')")
for pid in (101, 102, 103, 104, 105):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)",
            (pid, f"H{pid}", pid))
for pid in (201, 202, 203, 204, 205):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,2,?,?)",
            (pid, f"A{pid}", pid))
G = execute("INSERT INTO games (team1_id, team2_id, date, tracked) "
            "VALUES (1,2,'2026-01-01',1)")
FLOOR = [(p, 1) for p in (101, 102, 103, 104, 105)] + \
        [(p, 2) for p in (201, 202, 203, 204, 205)]
PID2TEAM = dict(FLOOR)


def stype(eid):
    return query("SELECT shot_type FROM game_events WHERE id=?", (eid,))[0]["shot_type"]


# ── the write path can no longer produce the NULL ────────────────────────────
print("retyping a turnover into a shot fills shot_type in")
tov = GE.log_event(G, {"event_type": "turnover", "quarter": 1, "time": "7:00",
                       "primary_player_id": 101}, FLOOR)
EL.update_event(G, tov, {"event_type": "shot", "quarter": 1, "time": "7:00",
                         "primary_player_id": 101, "shot_result": "make",
                         "shot_type": None}, PID2TEAM)
ok(stype(tov) == 2, f"NULL shot_type defaulted to 2, got {stype(tov)!r}")

print("an explicit 3 is not clobbered by that default")
EL.update_event(G, tov, {"event_type": "shot", "quarter": 1, "time": "7:00",
                         "primary_player_id": 101, "shot_result": "make",
                         "shot_type": 3}, PID2TEAM)
ok(stype(tov) == 3, f"an explicit 3 survives, got {stype(tov)!r}")

print("a non-shot still has shot_type cleared")
EL.update_event(G, tov, {"event_type": "turnover", "quarter": 1, "time": "7:00",
                         "primary_player_id": 101}, PID2TEAM)
ok(stype(tov) is None, f"non-shot keeps NULL, got {stype(tov)!r}")

# ── an EXISTING NULL row (written before the fix) must not crash ─────────────
print("a legacy NULL row scores 2 everywhere instead of crashing")
made = GE.log_event(G, {"event_type": "shot", "quarter": 1, "time": "6:00",
                        "primary_player_id": 102, "shot_result": "make",
                        "shot_type": 2}, FLOOR)
# forge the pre-fix state: a MADE shot with no shot_type at all
execute("UPDATE game_events SET shot_type=NULL WHERE id=?", (made,))
ok(stype(made) is None, "the row is genuinely NULL now")

ok(EL.event_points(query("SELECT * FROM game_events WHERE id=?",
                         (made,))[0]) == 2,
   "event_points scores it 2")

ok(EL.score_from_events(G) == (2, 0),
   f"score_from_events agrees: {EL.score_from_events(G)}")

qs = GE.quarter_scores(G, 1, 2)
ok(qs[1][1] == 2, f"quarter scores count it as 2, got {qs[1]}")

# _build_boxes' quarter SQL summed ge.shot_type raw; SUM skips NULLs, so the
# basket vanished from the quarter line while the player box still had it.
boxes, team_pts, quarters = BX._build_boxes(G, 1, 2)
ok(team_pts[1] == 2, f"team points count it as 2, got {team_pts[1]}")
ok(quarters[1][1] == 2,
   f"the quarter line counts it too (SUM no longer skips it), got {quarters[1]}")
ok(boxes[102]["PTS"] == 2, f"the player box has it, got {boxes[102]['PTS']}")

print("+/- and the scoreboard agree on it")
EL.recompute_game_plus_minus(G)
pm = {r["player_id"]: r["plus_minus"] for r in query(
    "SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?", (G,))}
ok(pm[102] == 2, f"the scorer's floor is +2, got {pm[102]}")
ok(pm[201] == -2, f"the opposing floor is -2, got {pm[201]}")

print(f"\nALL {PASS} ASSERTS PASS")
