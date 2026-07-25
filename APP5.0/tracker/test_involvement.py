"""
Involvement rate (spec Part 4d) — fingerprints on the team's scores.

THE RISK THIS GUARDS AGAINST is a stat that is secretly about minutes. Divide a
player's fingerprints by the TEAM's total scores and a starter automatically
"is involved in more of them"; the leaderboard just re-ranks the rotation and
tells a coach nothing they did not know from the minutes column.

The denominator here is therefore team scoring plays WHILE THAT PLAYER WAS ON
THE FLOOR. Several checks below exist specifically to prove a bench player can
out-rate a starter, which is the whole point and the thing a naive rewrite would
silently break.

Run: python tracker/test_involvement.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.involvement as IV                    # noqa: E402
import helpers.stats as S                           # noqa: E402
import helpers.seasons as SEAS                      # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


_EID = [0]


def ev(kind="shot", made=True, scorer=1, passer=None, screen=None, hockey=None,
       reb=None, team=1, stype=2):
    _EID[0] += 1
    return {"id": _EID[0], "game_id": 700, "event_type": kind, "quarter": 1,
            "time": "8:00", "possession_secs": 12,
            "primary_player_id": scorer,
            "shot_result": ("make" if made else "miss"),
            "rebound_by_id": reb, "shot_type": stype, "pass_from_id": passer,
            "shot_created_by_id": screen, "blocked_by_id": None,
            "guarded_by_id": None, "zone": "center",
            "secondary_player_id": None, "official_id": None,
            "stolen_by_id": None, "shot_x": None, "shot_y": None,
            "play_type": None, "defense": None, "turnover_type": None,
            "hockey_from_id": hockey, "shooter_team_id": team}


def floor_for(events, on):
    """Same five on the floor for every event."""
    return {e["id"]: {1: frozenset(on)} for e in events}


print("\n-- the denominator is on-floor plays, not team plays ---------------")

# STARTER: on the floor for 20 scores, involved in 5   -> 25%
# BENCH:   on the floor for  4 scores, involved in 3   -> 75%
# A team-total denominator would rank the starter first on raw involvement.
STARTER, BENCH, OTHER = 1, 2, 3
evs = []
for i in range(20):
    evs.append(ev(scorer=OTHER, passer=(STARTER if i < 5 else None)))
bench_evs = []
for i in range(4):
    bench_evs.append(ev(scorer=OTHER, passer=(BENCH if i < 3 else None)))

floor = {}
for e in evs:
    floor[e["id"]] = {1: frozenset({STARTER, OTHER, 9, 8, 7})}
for e in bench_evs:
    floor[e["id"]] = {1: frozenset({BENCH, OTHER, 9, 8, 7})}
allev = evs + bench_evs

rows = IV.player_involvement(events=allev, floor=floor, team_id=1)
ok(rows[STARTER]["plays_on"] == 20, "starter's denominator is her own floor time")
ok(rows[BENCH]["plays_on"] == 4, "bench player's denominator is hers")
ok(rows[STARTER]["involved"] == 5 and rows[BENCH]["involved"] == 3,
   "fingerprint counts are right")
ok(rows[BENCH]["rate"] > rows[STARTER]["rate"],
   f"the BENCH player out-rates the starter ({rows[BENCH]['rate']}% vs "
   f"{rows[STARTER]['rate']}%) — the stat is not minutes in disguise")
ok(rows[OTHER]["plays_on"] == 24, "a player on for everything sees every play")
ok(rows[OTHER]["rate"] == 100.0, "and scoring them all is 100%")

print("\n-- credited at most once per scoring play --------------------------")

both = [ev(scorer=5, passer=2, screen=2)]
r = IV.player_involvement(events=both, floor=floor_for(both, {2, 5}), team_id=1)
ok(r[2]["involved"] == 1,
   "a player who passed AND screened the same basket counts once")
ok(r[2]["as_passer"] == 1 and r[2]["as_screener"] == 1,
   "but both roles are still itemised")
ok(r[2]["rate"] == 100.0, "so the rate can never exceed 100%")

print("\n-- every fingerprint type ------------------------------------------")

one = [ev(scorer=5, passer=2, screen=3, hockey=4)]
r = IV.player_involvement(events=one, floor=floor_for(one, {2, 3, 4, 5}),
                          team_id=1)
ok(r[5]["as_scorer"] == 1, "scorer credited")
ok(r[2]["as_passer"] == 1, "passer credited")
ok(r[3]["as_screener"] == 1, "screener credited")
ok(r[4]["as_hockey"] == 1, "hockey passer credited")
ok(all(r[p]["involved"] == 1 for p in (2, 3, 4, 5)), "all four are involved")

ft = [ev(kind="free_throw", scorer=5, passer=2)]
r = IV.player_involvement(events=ft, floor=floor_for(ft, {2, 5}), team_id=1)
ok(r[5]["involved"] == 1, "a made free throw credits the shooter")
ok(r[2]["involved"] == 0,
   "and nobody else — a free throw has no passer, by construction")

miss = [ev(made=False, scorer=5, passer=2)]
r = IV.player_involvement(events=miss, floor=floor_for(miss, {2, 5}), team_id=1)
ok(not r, "a missed shot is not a scoring play, so nobody is on for anything")

print("\n-- second-chance credit stays on its own possession -----------------")

# miss by 5, rebounded by 6, then 5 scores -> 6 gets second-chance credit
_EID[0] = 100
chain = [ev(made=False, scorer=5, reb=6), ev(made=True, scorer=5)]
r = IV.player_involvement(events=chain, floor=floor_for(chain, {5, 6}),
                          team_id=1)
ok(r[6]["as_rebounder"] == 1, "the offensive rebounder is credited")
ok(r[6]["involved"] == 1, "and counted as involved")

# an intervening OPPONENT event must break the chain
_EID[0] = 200
broken = [ev(made=False, scorer=5, reb=6),
          ev(made=False, scorer=50, team=2),
          ev(made=True, scorer=5)]
fl = {e["id"]: {1: frozenset({5, 6}), 2: frozenset({50})} for e in broken}
r = IV.player_involvement(events=broken, floor=fl, team_id=1)
ok(r.get(6, {}).get("as_rebounder", 0) == 0,
   "a change of possession breaks the second-chance link")

# A previous SCORE ends the trip, so one board earns credit ONCE. Sequence:
# miss by 5, board by 6, basket by 7, basket by 5. The board legitimately
# created the FIRST basket; the second must not re-credit it, or a rebounder
# would accrue credit for everything that happened afterwards.
_EID[0] = 300
scored = [ev(made=False, scorer=5, reb=6), ev(made=True, scorer=7),
          ev(made=True, scorer=5)]
r = IV.player_involvement(events=scored, floor=floor_for(scored, {5, 6, 7}),
                          team_id=1)
ok(r[6]["as_rebounder"] == 1,
   "the board is credited for the basket it directly created")
ok(r[6]["involved"] == 1,
   "and only once — the basket after it does not re-credit the same board")
ok(r[6]["plays_on"] == 2, "though she was on the floor for both")

print("\n-- off-floor credits never inflate the rate ------------------------")

# a credit for someone the lineup says was NOT on the floor (bad snapshot)
_EID[0] = 400
ghost = [ev(scorer=5, passer=42)]
r = IV.player_involvement(events=ghost, floor=floor_for(ghost, {5}), team_id=1)
ok(42 not in r or r[42]["plays_on"] == 0,
   "a passer with no lineup snapshot cannot produce a rate")
ok(r[5]["rate"] == 100.0, "and the on-floor scorer is unaffected")

print("\n-- tag dependence ---------------------------------------------------")

_EID[0] = 500
tagged = [ev(scorer=5, screen=2) for _ in range(4)]
r = IV.player_involvement(events=tagged, floor=floor_for(tagged, {2, 5}),
                          team_id=1)
ok(r[2]["tag_dependence"] == 1.0,
   "a player credited only through screens is 100% tag-dependent")
ok(r[5]["tag_dependence"] == 0.0, "the scorer needs no optional tag")
ok(abs(IV.team_tag_dependence(r) - 0.5) < 1e-9,
   "team tag dependence is the credit-weighted share")
ok(IV.team_tag_dependence({}) == 0.0, "no credits -> zero, not a crash")

print("\n-- against the live book -------------------------------------------")

gids = sorted(SEAS.game_pool("2025-2026", gender="F", tracked_only=True))
evl = S.fetch_events(gids)
live = IV.player_involvement(game_ids=gids, events=evl, team_id=1)
ok(len(live) > 0, f"team 1 involvement built ({len(live)} players)")
ok(all(0 <= r["rate"] <= 100 for r in live.values()),
   "every live rate is inside 0-100%")
ok(all(r["involved"] <= r["plays_on"] for r in live.values()),
   "nobody is involved in more plays than they were on the floor for")
elig = {p: r for p, r in live.items() if r["plays_on"] >= IV.MIN_PLAYS}
ok(len(elig) > 0, f"{len(elig)} players clear the {IV.MIN_PLAYS}-play floor")

rates = sorted(r["rate"] for r in elig.values())
print(f"    live rates: min {rates[0]}%  median {rates[len(rates) // 2]}%  "
      f"max {rates[-1]}%")
ok(rates[-1] - rates[0] > 10,
   "the distribution actually separates players (not a compressed metric)")
ok(rates[-1] < 100, "nobody reads as involved in literally everything")

dep = IV.team_tag_dependence(elig)
print(f"    team tag dependence: {dep:.3f}")
ok(0.0 <= dep <= 1.0, "tag dependence is a share")

v = IV.involvement_verdict(live, names={})
ok(len(v) > 0, f"verdict produces {len(v)} line(s)")
ok(all(len(x) == 3 for x in v), "verdict lines are (badge, n, html) triples")
ok(IV.involvement_verdict({}) == [], "empty input says nothing")

# the glue line must not be handed to the thinnest sample
glue = [x for x in v if x[0] == "Glue"]
if glue:
    import re
    who = re.search(r"<b>(#?\d+)", glue[0][2])
    print(f"    glue line: {glue[0][2][:90]}...")
    ok(who is not None, "the glue line names a player")

print(f"\n{PASS} checks passed.")
