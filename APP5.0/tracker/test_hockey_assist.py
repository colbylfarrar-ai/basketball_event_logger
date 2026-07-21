"""
Unit test for hockey assists / secondary assists (maintenance batch #3).

My additive part is the READ path: a new nullable column
`game_events.hockey_from_id` (the founder wires live capture on the three
trackers Wed) plus a HAST slot in the stats box builder, surfaced next to
AST / PotAST / ScrAST. Opt-in, purely additive: every existing row reads NULL,
so HAST is 0 until a coach starts tagging the "pass before the pass".

A hockey assist is the pass that led to the assist on a MADE, assisted shot
(mirrors AST: credit only when the shot drops). This test drives events
straight into game_events (no live-capture path yet) and asserts:
  * the migration added the column (existing DBs get it, NULL everywhere),
  * _blank_box / finalize_box carry HAST,
  * aggregate_player_boxes credits HAST to hockey_from_id on a MADE shot,
  * a MISS or a NULL hockey_from_id credits nobody,
  * the primary assist (pass_from_id -> AST) is unchanged (no regression).
Run: python tracker/test_hockey_assist.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_hast_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, query, execute      # noqa: E402
import helpers.stats as ST                                        # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── the migration ran: existing DBs gain the column, NULL everywhere ──────────
cols = {r["name"] for r in query("PRAGMA table_info(game_events)")}
ok("hockey_from_id" in cols, "game_events.hockey_from_id column exists (migration)")

# ── the box carries HAST (default 0, passes through finalize) ─────────────────
ok(ST._blank_box().get("HAST") == 0, "_blank_box seeds HAST = 0")
ok("HAST" in ST.finalize_box(ST._blank_box()), "finalize_box carries HAST")

# ── seed two teams, rosters, a game ───────────────────────────────────────────
execute("INSERT INTO teams (id, name, class, gender) VALUES (1,'Home','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (2,'Away','3A','F')")
for pid in (101, 102, 103, 104, 105):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)",
            (pid, f"H{pid}", pid))
G = execute("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-01')")


def shot(shooter, made, pass_from=None, hockey_from=None, three=False):
    return execute(
        "INSERT INTO game_events "
        "(game_id, event_type, quarter, time, primary_player_id, shot_result, "
        " shot_type, pass_from_id, hockey_from_id) "
        "VALUES (?, 'shot', 1, '5:00', ?, ?, ?, ?, ?)",
        (G, shooter, "make" if made else "miss", 3 if three else 2,
         pass_from, hockey_from))


# 101 makes an assisted 2: 102 gets the AST, 103 gets the HAST (pass-before-pass).
shot(101, True, pass_from=102, hockey_from=103)
# 101 makes another: 102 AST again, 103 HAST again -> HAST accumulates.
shot(101, True, pass_from=102, hockey_from=103)
# a MISS carrying hockey_from_id=104: no basket, so no hockey assist.
shot(101, False, pass_from=102, hockey_from=104)
# a MAKE with NO hockey_from_id (the common case today, NULL column): nobody HAST.
shot(101, True, pass_from=102, hockey_from=None)

boxes = ST.aggregate_player_boxes([G])

print("HAST credited to the hockey passer on made shots only")
ok(boxes[103]["HAST"] == 2, f"103 credited 2 HAST (two made feeds), got {boxes[103]['HAST']}")
# a miss credits nobody -> 104 never earns a box row at all
ok(104 not in boxes, f"104's hockey pass was a MISS -> no HAST, got {boxes.get(104, {}).get('HAST')}")

print("the NULL / common case credits nobody")
ok(boxes[101]["HAST"] == 0, f"shooter is never the hockey passer, got {boxes[101]['HAST']}")
ok(boxes[102]["HAST"] == 0,
   f"the primary-assist passer is not the hockey passer, got {boxes[102]['HAST']}")

print("no regression: the primary assist still lands on pass_from_id")
ok(boxes[102]["AST"] == 3, f"102 AST on the 3 made assisted shots, got {boxes[102]['AST']}")
ok(boxes[103]["AST"] == 0, f"the hockey passer earns no primary AST, got {boxes[103]['AST']}")

print(f"\nALL {PASS} ASSERTS PASS")
