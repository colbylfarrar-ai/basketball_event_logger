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

print("category -> raw-leaf resolution (spec Part 3 mechanism 2)")

# Every category flattens to raw columns with weights multiplied down the tree.
for cat in PR.CATEGORIES:
    leaves = PR.category_leaves(cat)
    ok(bool(leaves), f"{cat} resolves to {len(leaves)} raw leaves")

# Weights normalize to 1.0 per category: _wavg divides by the weight it used,
# so a component contributes its SHARE of the parent, not its raw weight sum.
# Without normalization a 10-leaf component would swamp a 2-leaf one on count.
for cat in PR.CATEGORIES:
    tot = sum(PR.category_leaves(cat).values())
    ok(abs(tot - 1.0) < 1e-9, f"{cat} leaf weights sum to 1.0 (got {tot:.6f})")

# THE GUARD: a resolved name must be a real profile key. This is the bug class
# that silently mis-measures evidence — `_DEFENSE_PARTS` names the contest leaf
# `DSHOT%z`, but it resolves to AdjDFG% (the shooter-adjusted twin). Assuming
# DSHOT% would have measured DEFENSE against a column the rating never uses.
_prof_keys = set()
try:
    _p = PR.player_profiles(gender="F")
    _prof_keys = set(next(iter(_p.values()))) if _p else set()
except Exception as ex:                                  # no DB in this env
    print(f"  .. skipping profile-key check ({type(ex).__name__})")

if _prof_keys:
    _bad = sorted({k for cat in PR.CATEGORIES for k in PR.category_leaves(cat)}
                  - _prof_keys - set(PR.DERIVED_LEAVES))
    ok(not _bad, f"every resolved leaf is a real profile key (bad: {_bad})")

ok(PR.LEAF_ALIAS["DSHOT%z"] == "AdjDFG%",
   "the contest alias points at AdjDFG%, read off zcol_signed — not guessed")
ok("AdjDFG%" in PR.category_leaves("DEFENSE"),
   "DEFENSE resolves the contest leaf to its adjusted column")

# Every RESOLVED name needs a tier too, or it drops out of box_share silently.
_untiered = sorted({k for cat in PR.CATEGORIES for k in PR.category_leaves(cat)}
                   - set(PR.LEAF_TIER))
ok(not _untiered, f"every resolved leaf carries a tier (untiered: {_untiered})")

print("fed_share / category_evidence")

_all = lambda _k: True
_none = lambda _k: False

for cat in PR.CATEGORIES:
    s, b = PR.fed_share(cat, _all)
    ok(abs(s - 1.0) < 1e-9, f"{cat}: everything fed -> share 1.0")
    # box_share is the box-reachable FRACTION OF THE CATEGORY, so it is < 1
    # even with everything fed — a box score cannot reach a tracked leaf.
    # Dividing by the box-leaf total instead would return 1.0 here and credit
    # a hand-entered game with full DEFENSE evidence.
    ok(0.0 < b <= 1.0, f"{cat}: box_share is a fraction of the whole ({b:.2f})")
    s0, b0 = PR.fed_share(cat, _none)
    ok(s0 == 0.0 and b0 == 0.0, f"{cat}: nothing fed -> both shares 0")

_share_def = PR.fed_share("DEFENSE", _all)[1]
_share_off = PR.fed_share("OFFENSE", _all)[1]
ok(_share_def < _share_off,
   f"a box score reaches less of DEFENSE than of OFFENSE "
   f"({_share_def:.2f} < {_share_off:.2f}) — DEFENSE is mostly tracked leaves")

# A fully-tracked player with NO manual games is untouched: share 1.0 means
# category evidence is exactly today's flat evidence_gp.
ok(abs(PR.category_evidence("DEFENSE", _all, 10, 0) - 10) < 1e-9,
   "full tracking, no manual games -> evidence unchanged (no regression)")
# With manual games it DOES fall, which is the intended correction: those box
# scores never fed DEFENSE's tracked leaves, and flat evidence_gp pretends they did.
ok(PR.category_evidence("DEFENSE", _all, 10, 4) < 10 + PR.MANUAL_GAME_WEIGHT * 4,
   "manual games no longer claim full DEFENSE evidence")

# A never-tags coach: T3 leaves absent -> less DEFENSE evidence -> more shrink.
_no_tags = lambda k: PR.LEAF_TIER.get(k) != PR.T3_TAGGED
_ev_tagged = PR.category_evidence("DEFENSE", _all, 10, 0)
_ev_plain = PR.category_evidence("DEFENSE", _no_tags, 10, 0)
ok(_ev_plain < _ev_tagged,
   f"never-tags DEFENSE earns less evidence ({_ev_plain:.2f} < {_ev_tagged:.2f})")

# ...and a manual-only player earns only what a BOX SCORE can reach. Today they
# get full MANUAL_GAME_WEIGHT evidence for DEFENSE regardless; that is the
# inaccuracy this fixes.
_box_only = lambda k: PR.LEAF_TIER.get(k) == PR.T1_BOX
_ev_manual = PR.category_evidence("DEFENSE", _box_only, 0, 10)
ok(_ev_manual < PR.MANUAL_GAME_WEIGHT * 10,
   f"manual games credit only the box-reachable share of DEFENSE "
   f"({_ev_manual:.2f} < {PR.MANUAL_GAME_WEIGHT * 10:.2f})")
ok(_ev_manual > 0, "...but a box score still counts for something")

print("tier_cohort")

ok(PR.tier_cohort(_all, 0, 5) == "box", "no tracked games -> box cohort")
ok(PR.tier_cohort(_all, 0, 0) is None, "no games at all -> no cohort")
ok(PR.tier_cohort(_no_tags, 10, 0) == "possession",
   "tracked but no tag ever fed -> possession cohort")
ok(PR.tier_cohort(_all, 10, 0) == "tagged", "a fed T3 leaf -> tagged cohort")

print("coverage chip / summary / gap (spec Part 3 mechanism 3)")

ok(PR.coverage_chip(0.95) == ("full tracked", 95), "high share -> full tracked")
ok(PR.coverage_chip(0.60) == ("partial", 60), "mid share -> partial")
ok(PR.coverage_chip(0.20) == ("thin", 20), "low share -> thin")
ok(PR.coverage_chip(None) == (None, None), "no share -> no chip")
# Same thresholds as helpers/coverage.py's team tag labels, so a coach does not
# learn two scales for the same idea.
import helpers.coverage as _COV
ok(_COV._label(85) == "strong" and PR.coverage_chip(0.85)[0] == "full tracked",
   "80% is the 'good' cut in both places")
ok(_COV._label(50) == "partial" and PR.coverage_chip(0.50)[0] == "partial",
   "40-80% is 'partial' in both places")

# The "rated from" line is FACTUAL and always present when there is data.
_sum = PR.coverage_summary({"OVERALL": 0.8, "OFFENSE": 0.97, "DEFENSE": 0.73,
                            "PLAYMAKING": 0.75, "REBOUNDING": 0.92})
ok(_sum.startswith("Rated from:"), f"summary is a rated-from line ({_sum[:28]!r})")
ok("Offense full tracked (97%)" in _sum, "names each pillar with its label + pct")
ok("Overall" not in _sum, "OVERALL is omitted — it is the blend, not an input set")
ok(PR.coverage_summary({}) is None and PR.coverage_summary(None) is None,
   "no data -> no summary (never raises)")

# The NUDGE is pool-relative, because each pillar has its own natural ceiling.
# Measured on the live book: median share is 97% OFFENSE but 73% DEFENSE and a
# hard 75% PLAYMAKING, so an absolute "below 80% is thin" rule flagged 192 of
# 242 players with near-identical text — informing nobody.
_base = {"OFFENSE": (0.97, 0.95), "DEFENSE": (0.73, 0.67),
         "PLAYMAKING": (0.75, 0.75), "REBOUNDING": (0.92, 0.92)}

_typical = {"OFFENSE": 0.97, "DEFENSE": 0.73, "PLAYMAKING": 0.75,
            "REBOUNDING": 0.92}
ok(PR.coverage_gap(_typical, _base) is None,
   "a player AT the per-pillar norm gets no nudge — 73% DEFENSE is normal")

_thin = dict(_typical, DEFENSE=0.25)
_g = PR.coverage_gap(_thin, _base)
ok(_g is not None and "Defense 25% vs 73% typical" in _g,
   f"a genuine outlier is named with its own pillar's norm (got {_g!r})")
ok("add" not in (_g or "").lower(),
   "the nudge does NOT say 'add tags' — coverage also grows with minutes, and "
   "on real data this fires mostly for 1-2 game reserves")
ok("minutes" in _g, "it names both causes honestly")

# Just under p25 but not materially under the median -> still silent, so the
# nudge cannot fire on ordinary jitter.
ok(PR.coverage_gap(dict(_typical, DEFENSE=0.66), _base) is None,
   "marginally below p25 is not an outlier (needs < 0.9x median too)")
ok(PR.coverage_gap(_thin, None) is None, "no baseline -> no nudge")
ok(PR.coverage_gap(None, _base) is None, "no shares -> no nudge")

# Worst pillar first.
_multi = PR.coverage_gap(dict(_typical, DEFENSE=0.30, OFFENSE=0.50), _base)
ok(_multi.index("Defense") < _multi.index("Offense"),
   "thinnest pillar is named first")

# pool_coverage_baseline derives the yardstick from the pool itself.
_rows = [{"CatShare": {c: v for c, v in _typical.items()}} for _ in range(4)]
_rows.append({"CatShare": dict(_typical, DEFENSE=0.10)})
_b = PR.pool_coverage_baseline(_rows)
ok(abs(_b["DEFENSE"][0] - 0.73) < 1e-9, "baseline median comes from the pool")
ok(_b["DEFENSE"][1] <= _b["DEFENSE"][0], "p25 sits at or below the median")

print(f"\nALL {PASS} CHECKS PASSED")
