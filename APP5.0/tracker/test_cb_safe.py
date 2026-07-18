"""
Unit test for the colorblind-safe semantic pair (cb_safe setting).
Throwaway DB. Pins:
  * semantic_pair: default green/red; cb_safe=1 -> blue/orange (settings-dict
    and DB-read paths agree),
  * refresh_theme_tokens flips ui.GOOD/ui.BAD and rebuilds HEAT/DIVERGE
    endpoints from the pair,
  * cards.pctile_color follows the pair at call time (>=50 band + <25 band),
  * toggling back restores the classic pair everywhere.
Run: python tracker/test_cb_safe.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_cb_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database      # noqa: E402
import helpers.settings_utils as SU              # noqa: E402
import helpers.ui as ui                          # noqa: E402
import helpers.cards as cards                    # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("semantic_pair")
ok(SU.semantic_pair({}) == ("#3fb950", "#e74c3c"), "default pair green/red")
ok(SU.semantic_pair({"cb_safe": "1"}) == (SU.CB_GOOD, SU.CB_BAD),
   "dict path: cb pair blue/orange")
SU.set_setting("cb_safe", "1")
ok(SU.semantic_pair() == (SU.CB_GOOD, SU.CB_BAD), "DB path: cb pair")

print("refresh_theme_tokens")
ui.refresh_theme_tokens()
ok(ui.GOOD == SU.CB_GOOD and ui.BAD == SU.CB_BAD, "ui.GOOD/BAD flip")
ok(ui.HEAT[1][1] == SU.CB_GOOD, "HEAT top anchors to GOOD")
ok(ui.DIVERGE[0][1] == SU.CB_BAD and ui.DIVERGE[2][1] == SU.CB_GOOD,
   "DIVERGE endpoints follow the pair")

print("cards call-time reads")
ok(cards.pctile_color(60) == SU.CB_GOOD, "pctile >=50 uses GOOD")
ok(cards.pctile_color(10) == SU.CB_BAD, "pctile <25 uses BAD")
ok(cards.pctile_color(80) == "#388bfd", "top quartile uses deep CB variant")

print("toggle back")
SU.set_setting("cb_safe", "0")
ui.refresh_theme_tokens()
ok(ui.GOOD == "#3fb950" and ui.BAD == "#e74c3c", "classic pair restored")
ok(cards.pctile_color(80) == "#2ea043", "classic deep green restored")

print(f"\nALL {PASS} ASSERTS PASS")
