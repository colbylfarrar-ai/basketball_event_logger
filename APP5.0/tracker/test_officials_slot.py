"""
Smoke test for official crew SLOTS (R / U1 / U2), against a THROWAWAY DB.
Run: python tracker/test_officials_slot.py

Proves: log_event(on_official_slots=...) writes game_lineup_officials.slot; a
re-assign upserts the slot (no duplicate row); and public_feed labels the crew
R/U1/U2 by slot order. Guards the PWA role-dropdown write path end-to-end.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_offslot_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query          # noqa: E402
import helpers.game_events as GE                  # noqa: E402
import helpers.public_feed as PF                  # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# Fresh teams / players / officials / game (high ids so we see only OUR rows).
TA = execute("INSERT INTO teams (name,class,gender) VALUES ('OffSlotA','3A','F')")
TB = execute("INSERT INTO teams (name,class,gender) VALUES ('OffSlotB','3A','F')")
P1 = execute("INSERT INTO players (team_id,name,number) VALUES (?, 'A1', 1)", (TA,))
P2 = execute("INSERT INTO players (team_id,name,number) VALUES (?, 'B1', 2)", (TB,))
O_R  = execute("INSERT INTO officials (name,official_id) VALUES ('Ref Ref', 9001)")
O_U1 = execute("INSERT INTO officials (name,official_id) VALUES ('Ump One', 9002)")
O_U2 = execute("INSERT INTO officials (name,official_id) VALUES ('Ump Two', 9003)")
G = execute("INSERT INTO games (team1_id,team2_id,date,tracked,season) "
            "VALUES (?,?, '2025-12-01', 1, 'Current')", (TA, TB))


def _shot(slots):
    ev = {"event_type": "shot", "quarter": 1, "time": "8:00",
          "primary_player_id": P1, "shot_result": "make",
          "shot_type": 2, "zone": "C"}
    return GE.log_event(G, ev, on_court=[(P1, TA), (P2, TB)],
                        on_officials=[o for o, _ in slots],
                        on_official_slots=slots)


print("log_event writes crew slots")
_shot([(O_R, 1), (O_U1, 2), (O_U2, 3)])
rows = {r["official_id"]: r["slot"] for r in query(
    "SELECT official_id, slot FROM game_lineup_officials WHERE game_id=?", (G,))}
ok(rows == {O_R: 1, O_U1: 2, O_U2: 3}, "R/U1/U2 slots stored on first event")

print("re-assign upserts (no duplicate rows)")
_shot([(O_R, 1), (O_U2, 2), (O_U1, 3)])   # swap U1<->U2 roles mid-game
rows2 = {r["official_id"]: r["slot"] for r in query(
    "SELECT official_id, slot FROM game_lineup_officials WHERE game_id=?", (G,))}
ok(len(rows2) == 3, "still exactly 3 crew rows (upsert, not insert)")
ok(rows2 == {O_R: 1, O_U2: 2, O_U1: 3}, "swapped slots reflected")

print("a foul's calling ref without a slot keeps NULL, doesn't clobber the crew")
_shot([])  # already-assigned crew stays; add an unslotted extra via on_officials
GE.log_event(G, {"event_type": "foul", "quarter": 1, "time": "7:30",
                 "primary_player_id": P1, "secondary_player_id": P2,
                 "official_id": O_R},
             on_court=[(P1, TA), (P2, TB)], on_officials=[O_R])
ok({r["official_id"]: r["slot"] for r in query(
    "SELECT official_id, slot FROM game_lineup_officials WHERE game_id=?", (G,))}
   == {O_R: 1, O_U2: 2, O_U1: 3}, "assigned slots survive an unslotted on_officials write")

print("public_feed labels the crew R/U1/U2 by slot")
events = query("SELECT event_type, quarter, official_id, secondary_player_id "
               "FROM game_events WHERE game_id=?", (G,))
pmap = {P1: {"team": "home"}, P2: {"team": "away"}}
detail = PF._officials_detail(G, events, pmap)
labels_by_oid = {}
crew = query("SELECT official_id FROM game_lineup_officials WHERE game_id=? "
             "ORDER BY (slot IS NULL), slot, id", (G,))
for i, r in enumerate(crew):
    labels_by_oid[r["official_id"]] = detail[i]["slot"]
ok(labels_by_oid[O_R] == "R", "slot 1 official labeled R")
ok(labels_by_oid[O_U2] == "U1", "slot 2 official labeled U1")
ok(labels_by_oid[O_U1] == "U2", "slot 3 official labeled U2")

print(f"\nALL {PASS} CHECKS PASSED")
