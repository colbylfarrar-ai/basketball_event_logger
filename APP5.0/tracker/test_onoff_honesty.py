"""
On/off insight cards must not prescribe rotation changes off an unadjusted split.

WHY THIS EXISTS (measured on the live book, 2026-07-25, 35 tracked games):
  * `_g_onoff` was the single most-fired player card in the app: 37 of 242.
  * Its number averaged 15.7 pts/100 against a mean |ORAPM| of 2.61 — the same
    quantity with teammates and opponents partialled out. A 6x scale gap.
  * 6 of those 37 cards pointed the OPPOSITE way to the adjusted estimate, and
    every one carried a prescription ("protect their minutes", "hide them on
    the weakest matchup").
  * Split-half reliability of the raw offensive split: r = -0.096. Negative.
    The odd games tell you nothing about the even games. Defence was better
    but still thin: r = 0.224, Spearman-Brown 0.366, implied EB prior K = 226.

So the cards are now anchored: EB-shrunk on the harmonic-mean sample, and they
fire only when the side-matched adjusted estimate agrees in sign.

Run: python tracker/test_onoff_honesty.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.insights as IN                      # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def row(gp=20):
    return {"GP": gp}


def dd(off_diff=None, def_diff=None, on=400, off=400,
       don=400, doff=400, orapm=None, drapm=None, with_impact=True):
    oo = {"on_poss": on, "off_poss": off, "on_dposs": don, "off_dposs": doff,
          "off_diff": off_diff, "def_diff": def_diff,
          "on_ortg": 100.0, "off_ortg": 100.0 - (off_diff or 0),
          "on_drtg": 100.0, "off_drtg": 100.0 - (def_diff or 0)}
    d = {"onoff": oo}
    if with_impact:
        d["impact"] = {"orapm": orapm, "drapm": drapm, "rapm": 0.0}
    return d


print("\n-- the shrink -----------------------------------------------------")

v, n = IN._onoff_shrunk(20.0, 400, 400)
ok(abs(n - 400.0) < 1e-6, "harmonic mean of equal samples is that sample (400)")
ok(v < 20.0, "shrink pulls the raw difference toward zero")
ok(abs(v - 20.0 * 400 / (400 + IN.ONOFF_PRIOR_POSS)) < 1e-9,
   "shrink is exactly n_eff/(n_eff+K) on the raw value")

_v, n2 = IN._onoff_shrunk(20.0, 1000, 45)
ok(n2 < 100,
   f"1000-on vs 45-off is a ~{n2:.0f}-possession estimate, not a 1000 one")
ok(IN._onoff_shrunk(20.0, 1000, 45)[0] < IN._onoff_shrunk(20.0, 400, 400)[0],
   "the lopsided split shrinks harder than the balanced one")
ok(IN._onoff_shrunk(None, 400, 400) == (None, 0.0), "None diff stays None")
ok(IN._onoff_shrunk(20.0, 0, 400) == (None, 0.0), "zero on-floor sample -> None")
ok(IN._onoff_shrunk(20.0, 400, 0) == (None, 0.0), "zero off-floor sample -> None")
ok(IN._onoff_shrunk(-20.0, 400, 400)[0] < 0, "shrink preserves sign")

print("\n-- offence: adjusted estimate is required -------------------------")

big = 40.0      # survives the shrink comfortably at 400/400
ok(IN._g_onoff(row(), {}, dd(off_diff=big, orapm=3.0)) is not None,
   "fires when the raw split and ORAPM agree (both positive)")
ok(IN._g_onoff(row(), {}, dd(off_diff=-big, orapm=-3.0)) is not None,
   "fires when the raw split and ORAPM agree (both negative)")
ok(IN._g_onoff(row(), {}, dd(off_diff=big, orapm=-3.0)) is None,
   "SUPPRESSED when ORAPM points the other way (the 6-of-37 case)")
ok(IN._g_onoff(row(), {}, dd(off_diff=-big, orapm=3.0)) is None,
   "SUPPRESSED when ORAPM points the other way, negative raw")
ok(IN._g_onoff(row(), {}, dd(off_diff=big, orapm=None)) is None,
   "no card without an adjusted estimate at all")
ok(IN._g_onoff(row(), {}, dd(off_diff=big, with_impact=False)) is None,
   "no card when the impact feed is absent entirely")
ok(IN._g_onoff(row(), {}, dd(off_diff=big, on=39, orapm=3.0)) is None,
   "possession gate still applies on the on-floor side")
ok(IN._g_onoff(row(), {}, dd(off_diff=big, off=39, orapm=3.0)) is None,
   "possession gate still applies on the off-floor side")

card = IN._g_onoff(row(), {}, dd(off_diff=big, orapm=3.0))
ok("adjusted" in card["text"], "text names the adjustment")
ok("+3.0" in card["text"], "text leads with the adjusted number itself")
ok("shrinking for sample size" in card["text"], "text discloses the shrink")
ok(card["metric"] == "On/off offense", "metric label unchanged")

# a raw split that only clears the bar BEFORE shrinking must not fire
ok(IN._g_onoff(row(), {}, dd(off_diff=9.0, on=100, off=100, orapm=3.0)) is None,
   "a +9 raw split on 100/100 no longer clears the bar once shrunk")

print("\n-- defence: sign convention is the inverted one -------------------")

# def_diff is on-minus-off of points ALLOWED, so NEGATIVE is good.
# DRAPM is sign-flipped at source (rapm.py:22) so POSITIVE is good.
ok(IN._g_onoff_def(row(), {}, dd(def_diff=-big, drapm=3.0)) is not None,
   "fires when both say good (allows fewer, positive DRAPM)")
ok(IN._g_onoff_def(row(), {}, dd(def_diff=big, drapm=-3.0)) is not None,
   "fires when both say bad (allows more, negative DRAPM)")
ok(IN._g_onoff_def(row(), {}, dd(def_diff=-big, drapm=-3.0)) is None,
   "SUPPRESSED when the raw split says good and DRAPM says bad")
ok(IN._g_onoff_def(row(), {}, dd(def_diff=big, drapm=3.0)) is None,
   "SUPPRESSED when the raw split says bad and DRAPM says good")
ok(IN._g_onoff_def(row(), {}, dd(def_diff=-big, drapm=None)) is None,
   "no defensive card without DRAPM")

good = IN._g_onoff_def(row(), {}, dd(def_diff=-big, drapm=3.0))
ok(good["z"] > 0, "good defence scores positive z (generators are good-oriented)")
bad = IN._g_onoff_def(row(), {}, dd(def_diff=big, drapm=-3.0))
ok(bad["z"] < 0, "leaky defence scores negative z")
ok("tightens" in good["text"] and "leaks" in bad["text"],
   "the two defensive verdicts are the right way round")

ok(IN._g_onoff_def(row(), {}, dd(def_diff=-big, don=39, drapm=3.0)) is None,
   "defensive gate reads the DEFENSIVE possession counts")

print("\n-- impact_map carries the side-matched columns --------------------")

m = IN.impact_map(rapm={7: {"RAPM": 4.0, "ORAPM": 3.0, "DRAPM": 1.0,
                            "off_poss": 100, "def_poss": 100}})
ok(m[7]["orapm"] == 3.0, "impact_map carries ORAPM")
ok(m[7]["drapm"] == 1.0, "impact_map carries DRAPM")
ok(m[7]["rapm"] == 4.0, "impact_map still carries two-way RAPM for _g_impact")
ok(m[7]["poss"] == 200, "poss still summed across both sides")
ok(IN.impact_map() == {}, "empty inputs still yield an empty map")

print("\n-- the constants are the measured ones ----------------------------")
ok(IN.ONOFF_PRIOR_POSS == 226,
   "prior is the 226 possessions implied by split-half reliability, not a guess")
ok(IN.ONOFF_MIN_DIFF == 8.0, "the pts/100 bar is unchanged from the raw card")

print(f"\n{PASS} checks passed.")
