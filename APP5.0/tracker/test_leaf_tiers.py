"""
Data-tier taxonomy guard (spec Part 3 / Part 8 commit 2) — pure, no DB.

The point of LEAF_TIER is that per-category evidence can later ask "what data
did this coach actually supply for DEFENSE?". That only works if EVERY leaf
carries a tier, so this test fails loudly the moment a new leaf lands untagged
rather than letting it silently degrade the tier accounting months later.

Also guards the backtest override surface: a gate that names a leaf group the
REGISTRY doesn't know KeyErrors inside BT.override() before it scores anything,
which is exactly what blocked the FT% and def_secure sweeps until 2026-07-24.

Run: python tracker/test_leaf_tiers.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.player_ratings as PR                # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("LEAF_TIER coverage")

# ── every leaf of every group is tagged ──────────────────────────────────────
untagged = []
for gname, getter in PR.LEAF_GROUPS.items():
    for leaf in getter():
        if PR.leaf_tier(leaf[0]) is None:
            untagged.append(f"{gname}:{leaf[0]}")
ok(not untagged, f"every leaf tagged (untagged: {untagged or 'none'})")

# ── tiers are only the three legal values ────────────────────────────────────
legal = {PR.T1_BOX, PR.T2_POSSESSION, PR.T3_TAGGED}
bad = {k: v for k, v in PR.LEAF_TIER.items() if v not in legal}
ok(not bad, f"all tiers in {sorted(legal)} (bad: {bad or 'none'})")

print("group_tier")

# A group is only as available as its most demanding leaf.
ok(PR.group_tier(PR._SHOOTING) == PR.T3_TAGGED,
   "_SHOOTING is T3 — SMOE needs contest tags even though TS%/eFG% are box")
ok(PR.group_tier(PR._OREB) == PR.T2_POSSESSION,
   "_OREB is T2 — OREB% needs on-court possessions, OREB/G alone is box")
ok(PR.group_tier(PR._PHYSICAL) == PR.T1_BOX,
   "_PHYSICAL is T1 — roster measurables need no game data at all")
ok(PR.group_tier([("TS%", 1.0, False), ("eFG%", 1.0, False)]) == PR.T1_BOX,
   "a purely box group reports T1")
ok(PR.group_tier([]) is None, "empty group has no tier")
ok(PR.group_tier([("NotALeaf", 1.0, False)]) is None,
   "unknown-only group has no tier (does not crash)")

# LEAF_GROUPS holds getters, not snapshots, so a BT.override swap is visible.
_saved = PR._DREB
try:
    PR._DREB = [("DREB/G", 1.0, False)]
    ok(PR.LEAF_GROUPS["_DREB"]() == [("DREB/G", 1.0, False)],
       "LEAF_GROUPS re-reads the module attr (BT.override stays visible)")
finally:
    PR._DREB = _saved

print("backtest REGISTRY covers every leaf group")

import tools.backtest as BT                        # noqa: E402

missing = [g for g in PR.LEAF_GROUPS
           if f"player_ratings.{g}" not in BT.REGISTRY]
ok(not missing, f"every leaf group is sweepable (missing: {missing or 'none'})")

# and the registered entries really point at the live attribute
for gname in PR.LEAF_GROUPS:
    mod, attr = BT.REGISTRY[f"player_ratings.{gname}"]
    assert getattr(mod, attr) is PR.LEAF_GROUPS[gname](), gname
ok(True, "REGISTRY entries resolve to the live leaf lists")

print(f"\nALL {PASS} CHECKS PASSED")
