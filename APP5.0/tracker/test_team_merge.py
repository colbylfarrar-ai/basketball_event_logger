"""
Unit test for helpers/ossaa_sync.merge_teams (admin fold-duplicate-team).
Runs on a TEMP DB so the live league DB is never touched.
Run: python tracker/test_team_merge.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_merge_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import db                       # noqa: E402
import helpers.ossaa_sync as SYNC             # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


db.initialize_database()
SYNC.ensure_schema()

keep = db.execute("INSERT INTO teams(name,class,gender,state) VALUES('Springdale','6A','M','AR')")
dupe = db.execute("INSERT INTO teams(name,class,gender,state) VALUES('Springdale AR','6A','M','AR')")
other = db.execute("INSERT INTO teams(name,class,gender,state) VALUES('Local','6A','M','OK')")
girl = db.execute("INSERT INTO teams(name,class,gender,state) VALUES('Springdale Girls','6A','F','AR')")

db.execute("INSERT INTO games(team1_id,team2_id,date) VALUES(?,?,?)", (other, dupe, '2026-01-01'))
db.execute("INSERT INTO games(team1_id,team2_id,date) VALUES(?,?,?)", (dupe, other, '2026-01-02'))
pl = db.execute("INSERT INTO players(team_id,name,number) VALUES(?,?,?)", (dupe, 'X', 5))
db.execute("INSERT INTO schedule(team_id,opponent_id,date,home_away) VALUES(?,?,?,?)",
           (dupe, other, '2026-01-03', 'Home'))
db.execute("INSERT INTO app_settings(key,value) VALUES(?,?)", (f"team_color::{dupe}", "#fff"))

usage = SYNC.team_usage(dupe)
ok(sum(usage.values()) >= 4, "preview counts the dupe's games/player/schedule")

# guards
try:
    SYNC.merge_teams(keep, keep)
    ok(False, "self-merge should raise")
except ValueError:
    ok(True, "self-merge refused")
try:
    SYNC.merge_teams(keep, girl)
    ok(False, "cross-gender should raise")
except ValueError:
    ok(True, "cross-gender merge refused")

res = SYNC.merge_teams(keep, dupe)
ok(res["keep"] == "Springdale" and res["dupe"] == "Springdale AR", "result names")
ok(not db.query("SELECT 1 FROM teams WHERE id=?", (dupe,)), "dupe team deleted")
ok(db.query("SELECT COUNT(*) AS c FROM games WHERE team1_id=? OR team2_id=?",
            (keep, keep))[0]["c"] == 2, "both games now on keeper")
ok(db.query("SELECT team_id FROM players WHERE id=?", (pl,))[0]["team_id"] == keep,
   "player moved to keeper")
ok(db.query("SELECT COUNT(*) AS c FROM schedule WHERE team_id=?", (keep,))[0]["c"] == 1,
   "schedule row moved to keeper")
ok(bool(db.query("SELECT 1 FROM app_settings WHERE key=?", (f"team_color::{keep}",))),
   "team_color setting rehomed onto keeper")
ok(not db.query("SELECT 1 FROM games WHERE team1_id=? OR team2_id=?", (dupe, dupe)),
   "no game still references the dupe")

print(f"\nALL {PASS} CHECKS PASSED")
