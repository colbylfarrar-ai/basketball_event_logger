"""
Spec 3 regression — flow-logged turnovers must keep their kind.

Two guards:
  1. API round-trip: a batch POST shaped like the PWA flow (LOG TURNOVER)
     carries turnover_type and it persists to game_events.
  2. Static client check: every event field the PWA's log* builders write is
     present in app.js SERVER_FIELDS — the whitelist toServer() strips
     payloads against. The 2026-07-18 bug was exactly this: logTov set
     turnover_type but SERVER_FIELDS didn't list it, so every flow-logged
     kind was silently dropped (founder's games 95% untyped).

Run: python tracker/test_tov_capture.py (throwaway DB; live DB untouched)
"""
import os
import re
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_tov_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient          # noqa: E402

from database.db import execute, query             # noqa: E402
from tracker.api import app                        # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── seed ────────────────────────────────────────────────────────────────────────
t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('Home HS','3A','F')")
t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('Away HS','3A','F')")
home, away = [], []
for i in range(5):
    home.append(execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
                        (t1, f"H{i+1}", i + 1)))
    away.append(execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
                        (t2, f"A{i+1}", i + 10)))
gid = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?, date('now'))",
              (t1, t2))
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('coach@test','coach','Test Coach','paid','tok')")
client = TestClient(app)
client.headers.update({"Authorization": "Bearer tok"})
floor = home + away

print("flow-shaped turnover batch keeps its kind")
r = client.post(f"/api/games/{gid}/events", json={"events": [{
    "uuid": "u-tov-kind", "event_type": "turnover", "quarter": 1,
    "time": "5:00", "primary_player_id": home[0], "stolen_by_id": away[1],
    "turnover_type": "pass", "on_court": floor, "officials_on": []}]})
ok(r.status_code == 200, "batch POST accepted")
rows = query("SELECT turnover_type, stolen_by_id FROM game_events "
             "WHERE game_id=? AND event_type='turnover'", (gid,))
ok(len(rows) == 1, "turnover row written")
ok(rows[0]["turnover_type"] == "pass",
   f"turnover_type persisted (got {rows[0]['turnover_type']!r})")
ok(rows[0]["stolen_by_id"] == away[1], "stolen_by persisted")

print("client whitelist covers every flow-written field")
src = (Path(__file__).resolve().parent / "static" / "app.js").read_text(
    encoding="utf-8")
m = re.search(r"const SERVER_FIELDS = \[(.*?)\];", src, re.S)
ok(m is not None, "SERVER_FIELDS found in app.js")
fields = set(re.findall(r"'([a-z_]+)'", m.group(1)))
# every `ev.<field> = ...` assignment in the log* builders + baseEvent keys
assigned = set(re.findall(r"\bev\.([a-z_]+)\s*=", src))
base = re.search(r"function baseEvent\(type\) \{.*?return \{(.*?)\n  \};", src, re.S)
ok(base is not None, "baseEvent found in app.js")
assigned |= set(re.findall(r"^\s*([a-z_]+):", base.group(1), re.M))
missing = sorted(assigned - fields)
ok(not missing, f"SERVER_FIELDS covers all written fields (missing: {missing})")

print(f"\nALL {PASS} CHECKS PASSED")
