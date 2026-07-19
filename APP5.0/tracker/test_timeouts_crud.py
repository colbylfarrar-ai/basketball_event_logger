"""
Timeout visibility + undo/delete (task 17, founder ask). Throwaway DB.

Run: python tracker/test_timeouts_crud.py
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_to_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient          # noqa: E402

from database.db import execute                    # noqa: E402
from tracker.api import app                        # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('H','3A','F')")
t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('A','3A','F')")
gid = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?, date('now'))",
              (t1, t2))
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('c@test','coach','C','paid','tok')")
client = TestClient(app)
client.headers.update({"Authorization": "Bearer tok"})


def log(team, q="1", tm="5:00"):
    return client.post(f"/api/games/{gid}/timeouts", json={
        "team_id": team, "quarter": int(q), "time": tm}).json()


print("log + list + counts")
log(t1); log(t1); log(t2)
d = client.get(f"/api/games/{gid}/timeouts").json()
ok(len(d["timeouts"]) == 3, "all three listed")
ok(d["counts"][str(t1)] == 2 and d["counts"][str(t2)] == 1,
   f"per-team counts ({d['counts']})")

print("delete a specific one")
_tid = d["timeouts"][0]["id"]
r = client.delete(f"/api/games/{gid}/timeouts/{_tid}")
ok(r.status_code == 200, "delete ok")
d2 = client.get(f"/api/games/{gid}/timeouts").json()
ok(len(d2["timeouts"]) == 2 and all(t["id"] != _tid for t in d2["timeouts"]),
   "the deleted one is gone")
ok(client.delete(f"/api/games/{gid}/timeouts/99999").status_code == 404,
   "deleting a missing id -> 404")

print("undo removes the newest")
before = client.get(f"/api/games/{gid}/timeouts").json()["timeouts"]
newest = max(t["id"] for t in before)
r = client.post(f"/api/games/{gid}/timeouts/undo").json()
ok(r["deleted_timeout_id"] == newest, "undo drops the most recent")

print(f"\nALL {PASS} CHECKS PASSED")
