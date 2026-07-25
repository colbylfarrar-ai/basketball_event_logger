"""
The stint-length verdict must not be one made basket wide.

MEASURED 2026-07-25 on the live book (35 tracked games, 105 players with time
in both bands), split-half over the same players' odd vs even games:

    loosest tier gate (2 stints /  6 min per band)   r =  0.018  -> SB  0.035
    full gate         (3 stints / 12 min per band)   r = -0.130  -> SB -0.300

Median smaller-band sample ~1,700 s, so the implied EB prior is ~45,000 s of
band time. Corroborating reads: 53 of 105 players scored ZERO short-stint
points (p25/median/p75 of short_p32 = 0.0 / 0.0 / 9.1), and at 30 minutes of
band time -- already above the median -- one made three moves short_p32 by
3.2 pts/32 against a 4.0 pts/32 verdict threshold. At the loosest shipped gate
it moves it by 16.0.

It fired for 24 of 242 players with rotation prescriptions on that basis.

Run: python tracker/test_stint_credibility.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.insights as IN                      # noqa: E402
import helpers.seasons as SEAS                     # noqa: E402
import helpers.stats as S                          # noqa: E402
import helpers.gameflow as GF                      # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def stint(short_p32, long_p32, secs=1800, n=6):
    return {"stints": {"short_p32": short_p32, "long_p32": long_p32,
                       "n_short": n, "n_long": n,
                       "short_secs": secs, "long_secs": secs,
                       "short_pts": 0, "long_pts": 0,
                       "diff_p32": short_p32 - long_p32}}


print("\n-- credibility shrink -------------------------------------------")

ok(IN.STINT_PRIOR_SECS == 45000,
   "prior is the ~45,000 s implied by split-half reliability, not a guess")

# a realistic, well-sampled player: 30 min in each band, a 10 pts/32 raw gap
r = IN._g_stints({"GP": 20}, {}, stint(18.0, 8.0, secs=1800))
ok(r is None,
   "a 10 pts/32 gap on 30 min per band no longer mints a verdict")

# the loosest shipped gate, where one made three was worth 16 pts/32
r = IN._g_stints({"GP": 2}, {}, stint(20.0, 6.0, secs=360, n=2))
ok(r is None, "the 6-minute loosest-gate case can no longer fire")

# an effect so large and so well-sampled that it would be real
huge = IN._g_stints({"GP": 30}, {}, stint(300.0, 20.0, secs=60000, n=40))
ok(huge is not None,
   "a genuinely huge, hugely-sampled effect still fires (the read reactivates)")
ok("Microwave" in huge["text"], "and it is the right verdict")
ok("min in the thinner band" in huge["text"],
   "the firing text discloses the sample it rests on")

low = IN._g_stints({"GP": 30}, {}, stint(20.0, 300.0, secs=60000, n=40))
ok(low is not None and "Rhythm" in low["text"], "the mirror verdict still works")
ok(low["z"] < 0 < huge["z"], "z keeps its orientation across the two verdicts")

print("\n-- shrink is monotone in sample ---------------------------------")

def shrunk(secs):
    return (18.0 - 8.0) * secs / (secs + IN.STINT_PRIOR_SECS)

ok(shrunk(600) < shrunk(1800) < shrunk(60000),
   "more band time keeps more of the raw difference")
ok(shrunk(60000) < 10.0, "even a huge sample never exceeds the raw gap")

print("\n-- existing gates are untouched ---------------------------------")

ok(IN._g_stints({"GP": 20}, {}, stint(2.0, 1.0, secs=60000, n=40)) is None,
   "the low-usage floor (max band rate < 6) still short-circuits")
ok(IN._g_stints({"GP": 20}, {}, {"stints": None}) is None, "no stint feed -> no card")
ok(IN._g_stints({"GP": 20}, {}, {}) is None, "missing key -> no card")
ok(IN._g_stints({"GP": 20}, {}, stint(300.0, 20.0, secs=60000, n=1)) is None,
   "the stint-COUNT gate still applies independently of time")

print("\n-- against the live book ----------------------------------------")

gids = sorted(SEAS.game_pool("2025-2026", gender="F", tracked_only=True))
ev = S.fetch_events(gids)
sp = GF.stint_scoring_splits(ev)
ok(len(sp) > 0, f"engine still produces its descriptive split ({len(sp)} players)")

zero = sum(1 for v in sp.values() if v["short_pts"] == 0)
ok(zero > 0.4 * len(sp),
   f"the distribution this guards against is still there ({zero}/{len(sp)} "
   f"players score zero in short stints)")

fires = 0
for pid, v in sp.items():
    if IN._g_stints({"GP": 20}, {}, {"stints": v}):
        fires += 1
print(f"  live fire count: {fires} of {len(sp)} (was 24 of 242 before the shrink)")
ok(fires <= 2,
   f"at most a couple of live players clear the credibility bar (got {fires})")

print(f"\n{PASS} checks passed.")
