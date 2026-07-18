"""
Test for helpers/event_log.bulk_retag against a THROWAWAY DB. Pins:
  * validation — unknown field / non-canonical value raise, None clears,
  * one batched UPDATE re-tags exactly the given ids,
  * type eligibility — a free throw never takes a tag; turnover_type only
    lands on turnovers; ineligible ids are skipped, not corrupted,
  * the write lands in the audit log (moderation trail).
Run: python tracker/test_bulk_retag.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_retag_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query   # noqa: E402
import helpers.event_log as EL           # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


A = execute("INSERT INTO teams (name,class,gender) VALUES ('RtA','3A','F')")
B = execute("INSERT INTO teams (name,class,gender) VALUES ('RtB','3A','F')")
p1 = execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)", (A, "P1", 1))
g = execute("INSERT INTO games (team1_id,team2_id,date,tracked,season) "
            "VALUES (?,?, '2099-12-27', 0, 'Current')", (A, B))


def ev(et, **kw):
    cols = ["game_id", "event_type", "quarter", "time", "primary_player_id"]
    vals = [g, et, 1, "6:00", p1]
    for k, v in kw.items():
        cols.append(k)
        vals.append(v)
    return execute(f"INSERT INTO game_events ({','.join(cols)}) "
                   f"VALUES ({','.join('?' * len(cols))})", tuple(vals))


s1 = ev("shot", shot_result="make", shot_type=2, play_type="iso")
s2 = ev("shot", shot_result="miss", shot_type=3)
t1 = ev("turnover")
f1 = ev("foul")
ft = ev("free_throw", shot_result="make")


def col(eid, field):
    return query(f"SELECT {field} AS v FROM game_events WHERE id=?", (eid,))[0]["v"]


print("validation")
for bad in (lambda: EL.bulk_retag([s1], "zone", "C"),
            lambda: EL.bulk_retag([s1], "play_type", "not_a_set"),
            lambda: EL.bulk_retag([t1], "turnover_type", "man")):
    try:
        bad()
        ok(False, "invalid field/value must raise")
    except ValueError:
        ok(True, "invalid field/value raises ValueError")

print("re-tag")
n = EL.bulk_retag([s1, s2], "play_type", "pnr")
ok(n == 2, f"2 shots re-tagged in one write (got {n})")
ok(col(s1, "play_type") == "pnr" and col(s2, "play_type") == "pnr",
   "both rows now carry the new set call")
ok(col(t1, "play_type") is None, "unselected rows untouched")
n = EL.bulk_retag([s1], "play_type", None)
ok(n == 1 and col(s1, "play_type") is None, "None clears the tag")

print("eligibility")
n = EL.bulk_retag([s1, t1, f1, ft], "defense", "zone_23")
ok(n == 3, f"defense lands on shot+turnover+foul, never the FT (got {n})")
ok(col(ft, "defense") is None, "free throw stays untagged")
n = EL.bulk_retag([s2, t1, f1], "turnover_type", "pass")
ok(n == 1, f"turnover_type lands only on the turnover (got {n})")
ok(col(t1, "turnover_type") == "pass" and col(s2, "turnover_type") is None,
   "shot/foul rows skipped, not corrupted")
ok(EL.bulk_retag([], "defense", "man") == 0, "empty selection -> 0")

print("audit")
ok(any(r["table_name"] == "game_events" and r["op"] == "UPDATE"
       for r in query("SELECT table_name, op FROM audit_log")),
   "batched re-tag hits the audit log")

print(f"\nALL {PASS} CHECKS PASSED")
