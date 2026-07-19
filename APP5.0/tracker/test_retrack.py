"""
Item 9 — retrack detection on game creation (throwaway DB).

POSTing a new game whose (date, team pair) matches an already-TRACKED game by
another coach returns a duplicate_of hint; same coach, untracked matches, or
different dates return none. Creation is never blocked.

Run: python tracker/test_retrack.py
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_retrack_test_")
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


t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('A HS','3A','F')")
t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('B HS','3A','F')")
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('a@test','coach','A','paid','tok-a')")
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('b@test','coach','B','paid','tok-b')")
# coach A's finished track of the Jan 10 game (home/away as A entered it)
execute("INSERT INTO games (team1_id,team2_id,date,tracked,tracked_by,season) "
        "VALUES (?,?,?,1,'a@test','2025-2026')", (t1, t2, "2026-01-10"))

client = TestClient(app)

print("another coach retracks the same matchup")
client.headers.update({"Authorization": "Bearer tok-b"})
r = client.post("/api/games", json={
    "team1_id": t2, "team2_id": t1, "date": "2026-01-10",
    "season": "2025-2026"}).json()
ok(r["created"], "creation never blocked")
ok(r["duplicate_of"] and r["duplicate_of"]["tracked_by"] == "a@test",
   f"duplicate hint names the other coach ({r['duplicate_of']})")

print("no hint cases")
r = client.post("/api/games", json={
    "team1_id": t2, "team2_id": t1, "date": "2026-01-12",
    "season": "2025-2026"}).json()
ok(r["duplicate_of"] is None, "different date -> no hint")
client.headers.update({"Authorization": "Bearer tok-a"})
r = client.post("/api/games", json={
    "team1_id": t1, "team2_id": t2, "date": "2026-01-10",
    "season": "2025-2026"}).json()
ok(r["duplicate_of"] is None, "same coach re-creating their own game -> no hint")

print(f"\nALL {PASS} CHECKS PASSED")
