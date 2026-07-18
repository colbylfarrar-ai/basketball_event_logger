"""
Test for the Insights-tab per-coach NEW-badge tracker
(helpers/dashboard/insights_tab._seen_tracker) on a THROWAWAY DB. Pins:
  * an unseen line is NEW and stays NEW for the rest of that day (day-sticky),
  * a line first seen on a PRIOR day is not NEW,
  * persist() writes one JSON blob under the `insights_seen` settings key,
    keyed by team id, and never mixes teams,
  * the hash keys on metric + first 40 chars of text.
Run: python tracker/test_insights_seen.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_seen_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database          # noqa: E402
import helpers.settings_utils as SU                  # noqa: E402
from helpers.dashboard.insights_tab import (         # noqa: E402
    _ins_hash, _seen_tracker)

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


L1 = {"metric": "Rim finishing",
      "text": "**Elite** at the rim — 68% inside vs a 52% league make rate",
      "n": 40}
L2 = {"metric": "Turnovers", "text": "**Loose** with the ball late", "n": 22}
TODAY = dt.date.today().isoformat()

print("hash")
ok(_ins_hash(L1) != _ins_hash(L2), "different lines hash apart")
ok(_ins_hash(L1) == _ins_hash({"metric": "Rim finishing",
                               "text": L1["text"][:40] + " EXTRA TAIL"}),
   "hash keys on metric + first 40 chars only")

print("first sight")
is_new, persist = _seen_tracker(7)
ok(is_new(L1) and is_new(L2), "unseen lines are NEW")
persist()
blob = json.loads(SU.get_setting("insights_seen", "{}"))
ok(blob.get("7", {}).get(_ins_hash(L1)) == TODAY,
   "persist stamps today's date under the team key")

print("day-sticky")
is_new, persist = _seen_tracker(7)
ok(is_new(L1), "a line first seen TODAY keeps its chip all day")

print("prior day -> not new")
blob["7"][_ins_hash(L1)] = "2026-01-01"
SU.set_setting("insights_seen", json.dumps(blob))
is_new, persist = _seen_tracker(7)
ok(not is_new(L1), "a line seen on a prior day is not NEW")
ok(is_new(L2), "the other line stays day-sticky NEW")

print("team isolation")
is_new_b, persist_b = _seen_tracker(8)
ok(is_new_b(L1), "same line is NEW again on another team's card")
persist_b()
blob = json.loads(SU.get_setting("insights_seen", "{}"))
ok(set(blob) == {"7", "8"}, "blob keeps per-team buckets side by side")

print(f"\nALL {PASS} CHECKS PASSED")
