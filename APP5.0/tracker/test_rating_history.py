"""
Unit test for helpers/rating_history.py (daily rating snapshots → trajectory).
Runs on a THROWAWAY DB (temp APP5_DATA_DIR) with synthetic boards so the
write-idempotency, window pick, movement sign and riser ordering are pinned:
  * INSERT OR IGNORE — a second snapshot the same day writes nothing,
  * rows are stamped with the season's REAL label (never 'Current'),
  * movement = latest day vs the newest day at least `days` old (fallback
    earliest), d_rank POSITIVE = climbed,
  * risers returns climbers only, biggest first.
Run: python tracker/test_rating_history.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_rsnap_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import query, initialize_database   # noqa: E402
import helpers.rating_history as RH                  # noqa: E402
import helpers.seasons as SEAS                       # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def board(*rows):
    """rows = (tid, rating, rank)"""
    return {tid: {"Rating": rt, "Rank": rk} for tid, rt, rk in rows}


D1, D2, D3 = "2026-07-01", "2026-07-08", "2026-07-09"

print("write path")
n = RH.snapshot_board("F", {"score": board((1, 5.0, 1), (2, 3.0, 2), (3, 1.0, 3)),
                            "tracked": board((1, 8.0, 1))}, day=D1)
ok(n == 4, f"day-1 write = 4 rows (3 score + 1 tracked, got {n})")
n = RH.snapshot_board("F", {"score": board((1, 9.9, 1))}, day=D1)
ok(n == 0, "same-day re-snapshot is a no-op (INSERT OR IGNORE)")
lbl = SEAS.active_label()
r = query("SELECT DISTINCT season FROM rating_snapshots")
ok(len(r) == 1 and r[0]["season"] == lbl,
   f"rows stamped with the real season label ({lbl}, never 'Current')")
ok(RH.snapshot_board("F", {"score": {}}) == 0, "empty board writes nothing")

print("movement")
ok(RH.movement("F") == {}, "one day of history -> no movement yet")
# day 2 (a week later): team 2 climbs past team 1; team 3 holds; team 4 is new
RH.snapshot_board("F", {"score": board((2, 6.0, 1), (1, 4.0, 2),
                                       (3, 1.5, 3), (4, 0.5, 4))}, day=D2)
mv = RH.movement("F", days=7)
ok(mv[2]["d_rank"] == 1 and mv[1]["d_rank"] == -1,
   "d_rank sign: climbed = positive, fell = negative")
ok(abs(mv[2]["d_rating"] - 3.0) < 1e-9, "d_rating = rating delta over the window")
ok(mv[3]["d_rank"] == 0, "held rank -> 0")
ok(4 not in mv, "team new to the board has no trajectory")
ok(mv[2]["from_day"] == D1 and mv[2]["to_day"] == D2, "window endpoints reported")

# day 3 (one day after day 2): the 7-day window must still baseline at day 1,
# not the fresher day 2.
RH.snapshot_board("F", {"score": board((2, 6.5, 1), (1, 4.0, 2), (3, 1.5, 3))},
                  day=D3)
mv = RH.movement("F", days=7)
ok(mv[2]["from_day"] == D1 and mv[2]["to_day"] == D3,
   "window picks the newest day >= 7 days back (day 1)")

print("series + risers + arrows")
ser = RH.team_series(2, "F")
ok([s["day"] for s in ser] == [D1, D2, D3], "team_series is oldest-first")
ok(ser[0]["rank"] == 2 and ser[-1]["rank"] == 1, "series carries rank by day")
rs = RH.risers("F", days=7, top=3)
ok([t for t, _ in rs] == [2], "risers = climbers only, holds/fallers excluded")
ok(RH.risers("F", days=7, min_move=2) == [], "min_move filters small climbs")
ok(RH.arrow(3) == "▲3" and RH.arrow(-2) == "▼2" and RH.arrow(0) == "—"
   and RH.arrow(None) == "", "arrow chips")

print("isolation")
ok(RH.movement("M") == {}, "genders don't blend")
ok(RH.team_series(2, "F", system="tracked") == [],
   "systems don't blend (team 2 was never on the tracked board)")

print(f"\nALL {PASS} CHECKS PASSED")
