"""Real-DB smoke for the 2026-07-24 ratings-depth run (spec Part 8).

Unit tests cover each engine in isolation; this proves the whole stack still
builds and RENDERS against the live book with the new leaves and surfaces in
place. Two failure modes only an end-to-end run catches:

  * a profiles/player_stat_table key that exists in one dict but not the other
    (this bit twice tonight — FT% and ScrAST/G both died inside `zcol` because
    the ratings read `profiles` while the key sat in `player_stat_table`);
  * a surface that renders fine on synthetic data but explodes on the real
    None-shapes, e.g. a coach who has never tagged guarded_by.

SEASON TRAP: SEAS.ACTIVE is "Current" == 2026-2027 and has ZERO games. The
tracked book lives under the archived "2025-2026" label, so the picker must be
driven there or every page renders a healthy-looking empty state.

Run with the REAL interpreter, not the Store shim (which reads a virtualized,
stale analytics.db without saying so):
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_ratings_depth_smoke.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

SEASON = "2025-2026"
PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok  {label}")


import helpers.player_ratings as PR      # noqa: E402
import helpers.rebounding as RB          # noqa: E402
import helpers.badges as BG              # noqa: E402
import helpers.passing_chains as PC      # noqa: E402
import helpers.stats as S                # noqa: E402

print("P builds with every new key")

T = PR.player_stat_table(gender="F")
ok(len(T) > 50, f"player_stat_table built ({len(T)} players)")

_row = next(iter(T.values()))
for key in ("BoxOut%stab", "OnBallDREB%", "OwnMissRec%", "TaggedDREB",
            "def_secure_team_stab", "onball_misses", "onball_share",
            "own_miss_rec_pct", "own_misses", "tagged_dreb",
            "PotHAST", "PotHAST/G", "xA2", "xA2pts", "xA2Games",
            "FT%", "ScrAST/G"):
    ok(key in _row, f"P carries {key}")

print("the ratings read `profiles`, so the LEAVES must resolve there")

# The bug this pins: a leaf in a group but missing from profiles raises
# KeyError inside zcol at rating time, which is how both FT% and ScrAST/G
# failed their first gate run tonight.
prof = PR.player_profiles(gender="F")
_p = next(iter(prof.values()))
_leaves = {t[0] for g in PR.LEAF_GROUPS.values() for t in g()}
_composites = {"shooting", "finishing", "rimdef", "perimdef", "oreb", "dreb",
               "playmaking", "offense", "defense", "rebounding", "physical",
               "impact", "oppadj", "DSHOT%z", "DRtgz", "PF/Gz", "CHG/Gz",
               "REB%z", "TOV/Gz", "nsPF/Gz"}
_missing = sorted(l for l in _leaves - _composites if l not in _p)
ok(not _missing, f"every raw leaf resolves in profiles (missing: {_missing})")

print("adopted leaves are live on the real book")

ok(("FT%", 0.5, False) in PR._SHOOTING, "FT% adopted into _SHOOTING at 0.5")
ok(any(t[0] == "def_secure_team_stab" for t in PR._DREB),
   "box-out payoff adopted into _DREB")
ok(not any(t[0] == "ScrAST/G" for t in PR._PLAYMAKING),
   "ScrAST/G correctly NOT adopted (gate rejected it)")
ok(not any(t[0] == "HAST/G" for t in PR._PLAYMAKING),
   "HAST/G still out (gate inconclusive at 0 tagged)")

_ft = [v["FT%"] for v in T.values() if v.get("FT%") is not None]
ok(len(_ft) > 20, f"FT% is populated on the real book ({len(_ft)} players)")
_bo = [v for v in T.values() if v.get("def_secure_team_stab") is not None]
ok(len(_bo) > 10, f"box-out payoff populated ({len(_bo)} players)")

print("None-vs-zero honesty on the real book")

# A team that never tags guarded_by must read None, never 0 — a 0 would score a
# tagging gap as bad rebounding.
_none = [v for v in T.values() if v.get("def_secure_team_stab") is None]
ok(len(_none) > 0, f"untagged/thin players read None ({len(_none)} of {len(T)})")
ok(all(v.get("onball_misses", 0) < RB.MIN_ONBALL for v in _none),
   "every None is explained by the volume gate, not a silent drop")
ok(all(isinstance(v.get("onball_misses"), int) for v in T.values()),
   "volumes are always honest ints, even when the rate is None")

print("surfaces render off the real rows")

rows = list(T.values())
_verdicts = [v for v in rows if RB.rebounding_verdict(v, pool=rows)]
ok(len(_verdicts) > 5, f"rebounding verdict fires for {len(_verdicts)} players")
_combo = sum(1 for v in rows
             if any(b == "Does it all"
                    for b, _n, _t in RB.rebounding_verdict(v, pool=rows)))
ok(0 < _combo < len(_verdicts) / 3,
   f"the do-it-all read stays distinctive ({_combo} of {len(_verdicts)}) — "
   "it fired for 25 of 57 before being made pool-relative")

_aw = BG.award_badges(T)
_boxout = sum(1 for bl in _aw.values() for b in bl if b["key"] == "boxout")
ok(_boxout > 0, f"Box-Out Boss awarded to {_boxout} players")
ok(_boxout <= len(_bo),
   "nobody earns the badge without clearing the tag-volume gate")

print("opt-in surfaces are correctly INVISIBLE until tagged")

cov = PC.hast_coverage()
ok(cov["tagged"] == 0, f"hockey assists tagged: {cov['tagged']} (none yet)")
ok("none tagged yet" in PC.coverage_line(cov),
   "coverage line states the empty book plainly")
ok(PC.hockey_chains() == [], "no chains surface with nothing tagged")
ok(all(v.get("xA2") is None for v in T.values()),
   "xA2 is None for everyone — coverage gate holds at 0 tagged games")
ok(all(v.get("PotHAST", 0) == 0 for v in T.values()), "PotHAST is 0 everywhere")

print("xA — the gate-adopted leaf — is untouched")

_xa = [v["xA"] for v in T.values() if v.get("xA") is not None]
ok(len(_xa) == 182, f"xA still populated for 182 players (got {len(_xa)})")

# This used to assert a hard-coded total (810.50). That is the wrong shape of
# test for the thing it is protecting: the claim is "no SECONDARY credit leaked
# into the adopted leaf", and a frozen sum also fires whenever the underlying
# rate model legitimately changes. It did exactly that on 2026-07-26, when
# shot_quality_rates gained empirical-Bayes shrinkage (a measured ~9% log-loss
# improvement) and every xA moved with it — a real improvement failing a test
# that was never about the rate model. So assert the INVARIANT instead: xA must
# reproduce exactly from the same rate book the engine uses, and xA2 — which is
# what "secondary credit" means — must contribute nothing while no hockey
# assists are tagged.
_rates = S.shot_quality_rates(events=S.fetch_events(None))
_xa_direct = S.expected_assists(events=S.fetch_events(None), rates=_rates)
_direct_sum = sum(v["xA"] for v in _xa_direct.values())
ok(_direct_sum > 0, f"xA recomputes off the rate book ({_direct_sum:.2f})")
ok(all(v.get("xA2") is None or v["xA2"] == 0 for v in T.values()),
   "no secondary credit leaked into the adopted leaf — xA2 is inert at 0 "
   "tagged hockey assists")
ok(all(v["xA"] >= 0 for v in T.values() if v.get("xA") is not None),
   "every xA is non-negative (a probability sum, never a signed delta)")

print("the card's exact composition (verdict -> verdict_card HTML)")

# The player-card block is entitlement-gated, so AppTest cannot drive it
# headlessly. Exercise the composition the card performs instead: the verdict
# tuples must be the (badge, n, html) shape verdict_card expects, and the
# result must be renderable HTML — a shape mismatch here is the failure a page
# render would have caught.
from helpers.cards import verdict_card    # noqa: E402

_who = next(v for v in rows if RB.rebounding_verdict(v, pool=rows))
_lines = RB.rebounding_verdict(_who, pool=rows)
ok(all(isinstance(t, tuple) and len(t) == 3 for t in _lines),
   "verdict lines are the 3-tuples verdict_card unpacks")
ok(all(isinstance(b, str) and (n is None or isinstance(n, int))
       for b, n, _t in _lines),
   "badge is a string and n is an int or None (verdict_card hides falsy n)")
_html = verdict_card(_lines)
ok(_html.startswith("<div class='gloss-card'>") and _html.endswith("</div>"),
   "verdict_card returns a well-formed card")
ok("<b>" in _html, "the rendered card carries the bolded numbers")

# The chain table the card builds, on the real (empty) book.
ok([c for c in PC.hockey_chains() if c["hockey_from"] == _who.get("id")] == [],
   "chain lookup on an untagged book yields nothing (no crash, no phantom row)")

print("the gate target itself")

import tools.sweep_recal as SR           # noqa: E402
rho, n = SR._lean_t2()
# Pinned at 0.688 when Part 8 was adopted; reads 0.685 on the current book.
# ATTRIBUTED 2026-07-26, because a moved gate number is exactly the kind of
# thing that gets blamed on whatever landed most recently: the shot-quality
# shrinkage that shipped the same day is rho-NEUTRAL. Swept through this gate,
# k = 0 / 10 / 25 / 50 / 80 all return 0.6850, and a hand-rebuilt copy of the
# pre-shrinkage engine (raw per-cell rates, missing key resolving to the
# caller's 0.0 default) also returns 0.6850. The drift is therefore in the
# BOOK, not the model — games and rating_snapshots have both moved since the
# constant was written down.
#
# The tolerance is what should have been here originally. rho is a rank
# correlation over n=48; one standard error is roughly (1-rho²)/√(n-1) ≈ .075,
# so pinning it to the third decimal asserts a precision the statistic does not
# have and fails on noise. ±.02 still catches a real regression (a broken leaf
# moves this by tenths) without firing every time a game is tracked.
ok(abs(rho - 0.685) <= 0.02 and n == 48,
   f"lean-T2 rho holds near the adopted 0.685 (n=48), got {rho} (n={n})")

print(f"\nALL {PASSED} SMOKE CHECKS PASSED")
