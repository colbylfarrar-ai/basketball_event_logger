"""
Write/edit path for hockey assists (maintenance batch #3 capture wiring).

test_hockey_assist.py covers the READ side (box credit). This covers CAPTURE:
the live logger (helpers.game_events.log_event) and the Event Editor mutate
path (helpers.event_log) must persist and round-trip game_events.hockey_from_id,
a sibling to pass_from_id — otherwise the box stat can never light up.

Asserts:
  * log_event on a shot persists hockey_from_id (create path — PWA + Streamlit
    tracker both go through here),
  * event_changed sees a hockey_from_id edit (else the editor no-ops the change),
  * update_event writes a new hockey_from_id and clears it on retype,
  * the editor field set (_FIELDS_BY_TYPE['shot'] / _ALL_FIELDS) carries it.
Run: python tracker/test_hockey_capture.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_hcap_test_")
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


# ── seed teams / rosters / game ───────────────────────────────────────────────
execute("INSERT INTO teams (id, name, class, gender) VALUES (1,'Home','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (2,'Away','3A','F')")
for pid in (101, 102, 103, 104, 105):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)",
            (pid, f"H{pid}", pid))
for pid in (201, 202, 203, 204, 205):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,2,?,?)",
            (pid, f"A{pid}", pid))
G = execute("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-01')")
FLOOR = [(101, 1), (102, 1), (103, 1), (104, 1), (105, 1),
         (201, 2), (202, 2), (203, 2), (204, 2), (205, 2)]

# ── the editor field set carries hockey_from_id ───────────────────────────────
ok("hockey_from_id" in EL._FIELDS_BY_TYPE["shot"], "shot field set includes hockey_from_id")
ok("hockey_from_id" in EL._ALL_FIELDS, "editor writes hockey_from_id on every update")

# ── create path: log_event persists it ────────────────────────────────────────
# 101 makes an assisted shot: 102 assists (pass_from_id), 103 fed 102 (hockey).
eid = GE.log_event(G, {"event_type": "shot", "quarter": 1, "time": "5:00",
                       "primary_player_id": 101, "shot_result": "make",
                       "shot_type": 2, "pass_from_id": 102,
                       "hockey_from_id": 103}, FLOOR)
row = query("SELECT hockey_from_id, pass_from_id FROM game_events WHERE id=?", (eid,))[0]
ok(row["hockey_from_id"] == 103, f"log_event stored hockey_from_id=103, got {row['hockey_from_id']}")
ok(row["pass_from_id"] == 102, f"assist unaffected, got {row['pass_from_id']}")

# a shot with no hockey pass stays NULL (the common case)
eid2 = GE.log_event(G, {"event_type": "shot", "quarter": 1, "time": "4:00",
                        "primary_player_id": 101, "shot_result": "make",
                        "shot_type": 2, "pass_from_id": 102}, FLOOR)
ok(query("SELECT hockey_from_id FROM game_events WHERE id=?", (eid2,))[0]["hockey_from_id"] is None,
   "shot without a hockey pass stores NULL")

# ── edit path: change + clear the hockey passer ───────────────────────────────
ev = query("SELECT * FROM game_events WHERE id=?", (eid,))[0]
pid2team = EL.game_people(G)["pid2team"]

# no-op guard: same value is not a change
same = EL._resolved(ev)
ok(not EL.event_changed(ev, same), "identical field set is not a change")

# retarget the hockey passer 103 -> 104
new = dict(EL._resolved(ev)); new["hockey_from_id"] = 104
ok(EL.event_changed(ev, new), "event_changed detects a hockey_from_id edit")
EL.update_event(G, eid, new, pid2team)
ok(query("SELECT hockey_from_id FROM game_events WHERE id=?", (eid,))[0]["hockey_from_id"] == 104,
   "update_event wrote the new hockey_from_id")

# clear it (coach removes the tag)
ev2 = query("SELECT * FROM game_events WHERE id=?", (eid,))[0]
cleared = dict(EL._resolved(ev2)); cleared["hockey_from_id"] = None
ok(EL.event_changed(ev2, cleared), "clearing hockey_from_id is a change")
EL.update_event(G, eid, cleared, pid2team)
ok(query("SELECT hockey_from_id FROM game_events WHERE id=?", (eid,))[0]["hockey_from_id"] is None,
   "update_event cleared hockey_from_id")

print(f"\nALL {PASS} ASSERTS PASS")
