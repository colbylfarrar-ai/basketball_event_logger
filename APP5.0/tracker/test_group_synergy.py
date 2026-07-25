"""
Group synergy (spec Part 4b, extended past pairs).

WHAT WAS ALREADY BUILT: pair synergy. chemistry_network's edges carry an
opponent- and teammate-adjusted net, and team_insights.chemistry_extra already
reports "pair net minus the mean of the two solo nets". What was missing is the
same read for the TRIOS and QUADS group_units enumerates.

TWO BUGS THIS FILE PINS, both found on live data:

1. MIXING ADJUSTED AND RAW. The first draft took solo nets from
   chemistry_network's `adj_net`, which is opponent- AND teammate-corrected,
   and subtracted it from group_units' RAW `Net`. On a good team the teammate
   correction pulls every solo net toward or below zero, so `expected` came out
   at about -7 against group nets of +46 and essentially every trio was
   reported at +57 "synergy". Solo nets now come from group_units(sizes=(1,)),
   which makes the two sides like-for-like BY CONSTRUCTION rather than by
   remembering to match them.

2. COST. Routing through chemistry_network cost 12.83s because of its
   opponent-slope ridge fit. group_units already walks every group size at
   once; adding k=1 is free, and the whole thing is 0.24s.

Run: python tracker/test_group_synergy.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.networks as NW                       # noqa: E402
import helpers.stats as S                           # noqa: E402
import helpers.seasons as SEAS                      # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("\n-- synergy arithmetic ----------------------------------------------")

groups = {
    1: [{"players": (1,), "poss": 200, "Net": 10.0, "cred": 0.8},
        {"players": (2,), "poss": 200, "Net": 20.0, "cred": 0.8},
        {"players": (3,), "poss": 200, "Net": 0.0, "cred": 0.8}],
    2: [{"players": (1, 2), "poss": 160, "Net": 30.0, "cred": 0.8},
        {"players": (1, 3), "poss": 160, "Net": 5.0, "cred": 0.8}],
    3: [{"players": (1, 2, 3), "poss": 160, "Net": 20.0, "cred": 0.8}],
}
syn = NW.group_synergy(1, sizes=(2, 3), groups=groups)

pair = {r["players"]: r for r in syn[2]}
ok(pair[(1, 2)]["expected"] == 15.0, "expected is the mean of the solo nets")
ok(pair[(1, 2)]["synergy"] == 15.0, "synergy is group net minus expected")
_c = 160 / (160 + NW._SYNERGY_PRIOR_POSS)
ok(abs(pair[(1, 2)]["syn_adj"] - 15.0 * _c) < 0.05,
   f"syn_adj uses SYNERGY's own prior ({NW._SYNERGY_PRIOR_POSS}), not "
   f"group_units' net prior (40)")
ok(pair[(1, 2)]["syn_adj"] < pair[(1, 2)]["synergy"] * 0.5,
   "which shrinks a 160-possession group by more than half")
ok(pair[(1, 3)]["synergy"] == 0.0,
   "a pair exactly matching its members' average reads zero synergy")
ok(syn[2] == sorted(syn[2], key=lambda r: -r["syn_adj"]),
   "rows come back ranked by the shrunk value, not the raw one")

trio = syn[3][0]
ok(trio["expected"] == 10.0, "trio expectation averages all three solos")
ok(trio["synergy"] == 10.0, "and its synergy follows")
ok(1 not in syn, "size 1 is used as input but never reported as a group")

print("\n-- credibility ordering (the whole reason syn_adj exists) ----------")

thin_vs_thick = {
    1: [{"players": (i,), "poss": 300, "Net": 0.0, "cred": 0.9} for i in (1, 2, 3, 4)],
    3: [{"players": (1, 2, 3), "poss": 26, "Net": 40.0, "cred": 0.4},
        {"players": (1, 2, 4), "poss": 900, "Net": 12.0, "cred": 0.9}],
}
r = NW.group_synergy(1, sizes=(3,), groups=thin_vs_thick)[3]
ok(r[0]["players"] == (1, 2, 4),
   "a 900-possession trio at +12 outranks a 26-possession trio at +40")
ok(r[1]["synergy"] > r[0]["synergy"],
   "...even though the thin group's RAW synergy is more than three times bigger")
ok(r[1]["syn_adj"] < 3.0,
   f"the 26-possession group keeps almost none of its raw value "
   f"({r[1]['syn_adj']:+.1f} of {r[1]['synergy']:+.1f})")

print("\n-- missing solos are skipped, not guessed --------------------------")

partial = {
    1: [{"players": (1,), "poss": 200, "Net": 10.0, "cred": 0.8}],
    2: [{"players": (1, 9), "poss": 100, "Net": 30.0, "cred": 0.7}],
}
ok(NW.group_synergy(1, sizes=(2,), groups=partial)[2] == [],
   "a group whose member never cleared the solo gate is dropped")
ok(NW.group_synergy(1, sizes=(2, 3), groups={1: [], 2: [], 3: []})[3] == [],
   "empty input -> empty output")

print("\n-- against the live book -------------------------------------------")

gids = sorted(SEAS.game_pool("2025-2026", gender="F", tracked_only=True))
ev = S.fetch_events(gids)

t0 = time.time()
live = NW.group_synergy(1, sizes=(2, 3, 4), game_ids=gids, events=ev)
elapsed = time.time() - t0
print(f"    built in {elapsed:.2f}s "
      f"(the chemistry_network route cost 12.83s)")
ok(elapsed < 4.0,
   f"synergy does not pay for the opponent-slope ridge fit ({elapsed:.2f}s)")

for k in (2, 3, 4):
    ok(len(live[k]) > 0, f"size {k}: {len(live[k])} groups")

# THE REGRESSION GUARD for bug 1: expected must sit on the same scale as Net.
# When the two were mixed, expected was ~-7 against group nets of ~+46.
allrows = [r for k in (2, 3, 4) for r in live[k]]
exps = [r["expected"] for r in allrows]
nets = [r["Net"] for r in allrows]
mean_exp = sum(exps) / len(exps)
mean_net = sum(nets) / len(nets)
print(f"    mean expected {mean_exp:+.1f} vs mean group Net {mean_net:+.1f}")
ok(abs(mean_exp - mean_net) < abs(mean_net) * 0.9 + 15,
   "expected sits on the SAME SCALE as group Net (raw vs raw), not 50 points "
   "below it")
ok(mean_exp > 0,
   f"solo nets for a winning team are positive ({mean_exp:+.1f}) — the "
   f"teammate-adjusted values that broke this were negative")

ok(all(abs(r["synergy"] - (r["Net"] - r["expected"])) < 0.11 for r in allrows),
   "every live row's synergy is its own Net minus its own expected")
ok(all(abs(r["syn_adj"]) <= abs(r["synergy"]) + 0.11 for r in allrows),
   "shrinking never increases the magnitude")
_thin = [r for r in allrows if r["poss"] < 100]
ok(_thin and all(r["syn_cred"] < 0.25 for r in _thin),
   f"the {len(_thin)} groups under 100 possessions keep under a quarter of "
   f"their raw synergy")
_creds = sorted(r["syn_cred"] for r in allrows)
print(f"    syn_cred min/median/max: {_creds[0]:.2f} / "
      f"{_creds[len(_creds) // 2]:.2f} / {_creds[-1]:.2f}")
ok(_creds[len(_creds) // 2] < 0.5,
   "the median group keeps under half — this book cannot support confident "
   "synergy claims and the shrink reflects that")
ok(all(r["poss"] > 0 for r in allrows), "every group has possessions")

# a prebuilt groups dict must give identical answers to the internal build
gu = NW.group_units(1, sizes=(1, 3), game_ids=gids, events=ev)
ok(NW.group_synergy(1, sizes=(3,), groups=gu)[3] == live[3],
   "passing prebuilt group_units changes nothing (the surface reuses one walk)")

print("\n-- the verdict ------------------------------------------------------")

names = {}
v = NW.synergy_verdict(live, names=names)
ok(len(v) > 0, f"verdict produces {len(v)} line(s)")
ok(all(len(x) == 3 for x in v), "lines are (badge, n, html) triples")
joined = " ".join(x[2] for x in v)
ok("better together than its members usually are" in joined,
   "the sentence says what synergy MEANS rather than quoting a bare number")
ok(any("reliability" in x[2].lower() for x in v),
   "the verdict carries its standing reliability caveat")
ok(v[-1][0] == "How firm is this",
   "and the caveat is the LAST line, so it qualifies everything above it")
ok(NW.synergy_verdict({}) == [], "no groups -> no verdict")
ok(NW.synergy_verdict({3: live[3][:2]}) == [],
   "fewer than three groups is too few to name a best and worst")

print(f"\n{PASS} checks passed.")
