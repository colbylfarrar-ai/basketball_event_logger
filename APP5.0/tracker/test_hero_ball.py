"""
Hero-ball Gini (spec Part 5j) — system offence or one player?

THE CONFOUND THIS IS BUILT AROUND: Gini over raw point TOTALS is mostly a
rotation-depth stat. A starter plays 30 minutes and a reserve plays 4, so the
points concentrate whatever the team's ball-sharing looks like. On the live
book team 1 reads raw 0.449 while its MINUTES alone are 0.295 concentrated --
most of the raw number is the rotation.

So the headline is a weighted Gini over per-floor-time scoring RATES. Several
checks below construct the exact case a naive implementation gets backwards:
a short rotation of equal scorers (a system) versus a deep rotation where one
player takes everything (hero ball).

Run: python tracker/test_hero_ball.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.hero_ball as HB                      # noqa: E402
import helpers.stats as S                           # noqa: E402
import helpers.seasons as SEAS                      # noqa: E402
from helpers.lineups import _event_floor            # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("\n-- the coefficient -------------------------------------------------")

ok(HB.gini([1, 1, 1, 1]) == 0.0, "perfectly even is 0")
ok(HB.gini([5, 5]) == 0.0, "two equal contributors is 0")
ok(HB.gini([0, 0, 0, 10]) > 0.7, "one-takes-all approaches 1")
ok(0 < HB.gini([1, 3]) < 1, "an uneven pair lands strictly inside (0, 1)")
ok(HB.gini([2, 6]) == HB.gini([1, 3]),
   "scale-invariant — doubling everyone changes nothing")
ok(HB.gini([5]) is None, "a single contributor is not a distribution")
ok(HB.gini([]) is None, "no contributors -> None")
ok(HB.gini([0, 0, 0]) is None, "an all-zero distribution -> None, not 0")
ok(HB.gini([1, 2, 3]) == HB.gini([3, 1, 2]), "order does not matter")

# weighting
ok(HB.gini([1, 1], [10, 1]) == 0.0, "equal rates stay 0 whatever the weights")
w_heavy = HB.gini([0.0, 1.0], [100, 1])
w_light = HB.gini([0.0, 1.0], [1, 100])
ok(w_heavy != w_light, "weights genuinely change the coefficient")

print("\n-- the confound: rates, not totals ---------------------------------")

# SYSTEM: five players, equal rates, but wildly unequal minutes.
# Raw totals look concentrated; the weighted rate Gini must not.
sys_rates = [0.1, 0.1, 0.1, 0.1, 0.1]
sys_mins = [300, 250, 200, 60, 40]
sys_totals = [r * m for r, m in zip(sys_rates, sys_mins)]
ok(HB.gini(sys_rates, sys_mins) == 0.0,
   "an equal-rate team reads 0 however lopsided the minutes")
ok(HB.gini(sys_totals) > 0.2,
   f"...while raw totals call the same team concentrated "
   f"({HB.gini(sys_totals):.2f}) — the confound, demonstrated")

# HERO: five players, equal minutes, one takes everything.
hero_rates = [0.02, 0.02, 0.02, 0.02, 0.40]
hero_mins = [200, 200, 200, 200, 200]
ok(HB.gini(hero_rates, hero_mins) > 0.5,
   "a one-player offence reads high even with even minutes")
ok(HB.gini(hero_rates, hero_mins) > HB.gini(sys_rates, sys_mins),
   "and the hero team out-reads the system team, which is the whole point")

print("\n-- gates -----------------------------------------------------------")

ok(HB.MIN_PLAYERS >= 5, "a Gini needs a real rotation behind it")
ok(HB.MIN_POOL_GAMES >= 3,
   "league percentiles exclude one-game teams (12 of 21 on the live book)")
ok(HB.MIN_POOL_TEAMS >= 5, "and are suppressed entirely on a tiny pool")

thin = HB.team_concentration(shares={1: {"pts": 5, "ast": 1, "floor_events": 500,
                                         "pts_rate": 0.01, "ast_rate": 0.002,
                                         "games": 3}})
ok(thin["scoring_gini"] is None,
   "one eligible player yields no coefficient rather than 0")
ok(thin["players"] == 1, "but the count is still reported")

print("\n-- against the live book -------------------------------------------")

gids = sorted(SEAS.game_pool("2025-2026", gender="F", tracked_only=True))
ev = S.fetch_events(gids)
floor = _event_floor(gids)

c = HB.team_concentration(events=ev, floor=floor, team_id=1)
print(f"    team 1: scoring {c['scoring_gini']:.3f}  raw {c['raw_gini']:.3f}  "
      f"minutes {c['minutes_gini']:.3f}  ({c['players']} players, "
      f"{c['games']} games)")
ok(c["scoring_gini"] is not None, "team 1 produces a coefficient")
ok(0 <= c["scoring_gini"] <= 1, "which is inside [0, 1]")
ok(c["raw_gini"] > c["scoring_gini"],
   "the raw number is higher than the rate number, as the confound predicts")
ok(c["minutes_gini"] is not None and c["minutes_gini"] > 0.2,
   f"and the team's minutes really are unevenly spread "
   f"({c['minutes_gini']:.2f}), which is what inflates it")

lg = HB.league_context(events=ev, floor=floor, game_ids=gids)
deep = {t: x for t, x in lg.items() if x["pct"] is not None}
shallow = {t: x for t, x in lg.items() if x["pct"] is None}
print(f"    pool: {len(deep)} deep teams of {len(lg)} with a coefficient")
ok(len(deep) >= HB.MIN_POOL_TEAMS, f"the pool clears its own floor ({len(deep)})")
ok(len(shallow) > 0,
   f"{len(shallow)} shallow teams are excluded from the percentile scale")
ok(all(x["games"] >= HB.MIN_POOL_GAMES for x in deep.values()),
   "every team setting the scale has real depth behind it")
ok(all(x["games"] < HB.MIN_POOL_GAMES for x in shallow.values()),
   "and every excluded team is excluded for depth, not for its value")
pcts = sorted(x["pct"] for x in deep.values())
ok(pcts[0] < 50 < pcts[-1], "percentiles span the pool")
ok(1 in lg, "the focus team is in the league context")

print("\n-- the verdict ------------------------------------------------------")

v = HB.hero_ball_verdict(lg[1], pool_pct=lg[1]["pct"])
ok(len(v) > 0, f"verdict produces {len(v)} line(s)")
ok(all(len(x) == 3 for x in v), "lines are (badge, n, html) triples")
joined = " ".join(x[2] for x in v)
ok("%" in joined, "the verdict speaks in pool terms, not bare Gini alone")
ok("rotation depth" in joined,
   "and explains why the raw number differs when it does")
for x in v:
    assert "should" not in x[2].lower() and "stop" not in x[2].lower(), \
        "verdict must not tell a coach the concentration is wrong"
ok(True, "no prescriptive judgement — a team with one elite scorer should funnel")

sh = next(iter(shallow.values())) if shallow else None
if sh:
    sv = HB.hero_ball_verdict(sh, pool_pct=sh["pct"])
    txt = " ".join(x[2] for x in sv)
    ok("tracked teams" not in txt,
       "a shallow team gets no percentile claim it has not earned")

ok(HB.hero_ball_verdict(None) == [], "no data -> no verdict")
ok(HB.hero_ball_verdict({"scoring_gini": None}) == [],
   "a null coefficient -> no verdict")

print(f"\n{PASS} checks passed.")
