"""
Connection matrix (spec Part 4c) — who feeds whom, weighted by look quality.

DEDUPE NOTE, because this nearly did not need building: a passer->finisher edge
list ALREADY exists as team_analytics.assist_network, drawn as the Playmaking
node-link diagram. It counts MADE shots only (team_analytics.py:1540), so it is
structurally blind to a pair that creates good looks the shooter misses. That
blind spot is the whole reason this exists, and the boundary is load-bearing:

    assist_network      what DROPPED     made assists, node-link picture
    connection_matrix   what was CREATED every feed, xA-weighted, plus the gap

If a future change makes connection_matrix make-conditioned, these two surfaces
become the same surface and one of them should be deleted. Several checks below
exist purely to make that impossible to do by accident.

Run: python tracker/test_connection_matrix.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.passing_chains as PC                 # noqa: E402
import helpers.stats as S                           # noqa: E402
import helpers.seasons as SEAS                      # noqa: E402
import helpers.team_analytics as TA                 # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


_EID = [0]


def shot(passer, shooter, made, team=1, zone="center", stype=2, screen=False,
         guarded=False, x=0.0, y=4.0):
    """A located shot. COORDINATES matter, `zone` does not: the shot-quality key
    reads stats._sq_loc, which is a shot KIND derived from shot_x/shot_y (see
    the depth-beats-angle table in stats._sq_loc), not the zone column. This
    fixture used to leave x/y None while setting zone='center', so every lookup
    keyed ('unknown', ...), missed the seeded rates, and scored xa = 0.0 — which
    silently turned the finish_delta assertion below into `10 > 0 > 0`."""
    _EID[0] += 1
    return {"id": _EID[0], "game_id": 900, "event_type": "shot",
            "quarter": 1, "time": "8:00", "possession_secs": 12,
            "primary_player_id": shooter, "shot_result": ("make" if made
                                                          else "miss"),
            "rebound_by_id": None, "shot_type": stype,
            "pass_from_id": passer,
            "shot_created_by_id": (99 if screen else None),
            "blocked_by_id": None,
            "guarded_by_id": (77 if guarded else None), "zone": zone,
            "secondary_player_id": None, "official_id": None,
            "stolen_by_id": None, "shot_x": x, "shot_y": y,
            "play_type": None, "defense": None, "turnover_type": None,
            "hockey_from_id": None, "shooter_team_id": team}


print("\n-- make-independence: the property that justifies this module ------")

TEAM_OF = {1: 1, 2: 1, 3: 1, 99: 1, 77: 2}
# Keyed on the real (kind, creation, contested) triple the engine builds — the
# default fixture coordinates (0, 4) classify as 'rim'. Asserted below rather
# than hardcoded blind, so a change to the kind boundaries fails loudly here
# instead of silently zeroing every xa again.
assert S._sq_loc(shot(1, 2, True)) == "rim", "fixture coords must be a real kind"
rates = {("rim", "pass", False): {"FGA": 100, "FGM": 50, "pct": 0.5}}

all_made = [shot(1, 2, True) for _ in range(10)]
all_miss = [shot(1, 2, False) for _ in range(10)]

a = PC.connection_matrix(events=all_made, team_of=TEAM_OF, rates=rates)
b = PC.connection_matrix(events=all_miss, team_of=TEAM_OF, rates=rates)
ok(len(a) == 1 and len(b) == 1, "an all-missed pair still produces an edge")
ok(a[0]["feeds"] == b[0]["feeds"] == 10, "feeds count make AND miss alike")
ok(a[0]["xa"] == b[0]["xa"],
   "xA is IDENTICAL for ten made and ten missed looks (make-independent)")
ok(a[0]["made"] == 10 and b[0]["made"] == 0, "made still tracks the finish")
ok(a[0]["finish_delta"] > 0 > b[0]["finish_delta"],
   "finish_delta separates over- from under-conversion")

# the dedupe guard: assist_network must NOT see the missed pair at all
an = TA.assist_network(1, events=all_miss)
ok(not an["edges"],
   "assist_network sees NO edge for the all-missed pair — the blind spot")
ok(len(b) == 1,
   "connection_matrix does see it — the two surfaces stay different")

print("\n-- edges are directed and self-passes excluded ---------------------")

mix = ([shot(1, 2, True) for _ in range(6)]
       + [shot(2, 1, True) for _ in range(5)]
       + [shot(3, 3, True) for _ in range(9)])
rows = PC.connection_matrix(events=mix, team_of=TEAM_OF, rates=rates)
pairs = {(r["passer"], r["shooter"]): r for r in rows}
ok((1, 2) in pairs and (2, 1) in pairs, "A->B and B->A are separate edges")
ok(pairs[(1, 2)]["feeds"] == 6 and pairs[(2, 1)]["feeds"] == 5,
   "each direction keeps its own count")
ok((3, 3) not in pairs, "a player 'feeding' themselves is not an edge")

print("\n-- min_feeds and team scoping --------------------------------------")

thin = [shot(1, 2, True) for _ in range(3)]
ok(PC.connection_matrix(events=thin, team_of=TEAM_OF, rates=rates) == [],
   f"a {len(thin)}-feed pair is below MIN_EDGE_FEEDS ({PC.MIN_EDGE_FEEDS})")
ok(len(PC.connection_matrix(events=thin, team_of=TEAM_OF, rates=rates,
                            min_feeds=1)) == 1,
   "callers can lower the floor explicitly")

cross = [shot(1, 2, True, team=1) for _ in range(6)]
ok(len(PC.connection_matrix(events=cross, team_of=TEAM_OF, rates=rates,
                            team_id=1)) == 1, "team scoping keeps own edges")
ok(PC.connection_matrix(events=cross, team_of=TEAM_OF, rates=rates,
                        team_id=2) == [],
   "team scoping drops edges whose ends are not both on that roster")
ok(PC.connection_matrix(events=[], team_of=TEAM_OF, rates=rates) == [],
   "no events -> no edges, not a zero-filled grid")

print("\n-- hubs separate a distributor from a two-man game -----------------")

hub = ([shot(1, 2, True) for _ in range(5)]
       + [shot(1, 3, True) for _ in range(5)]
       + [shot(1, 99, True) for _ in range(5)]
       + [shot(2, 3, True) for _ in range(20)])
hrows = PC.connection_matrix(events=hub, team_of=TEAM_OF, rates=rates)
hubs = PC.connection_hubs(hrows)
ok(hubs[1]["partners_out"] == 3, "the distributor feeds three teammates")
ok(hubs[2]["partners_out"] == 1, "the two-man-game passer feeds one")
ok(hubs[2]["feeds_out"] > hubs[1]["feeds_out"],
   "and does it MORE often — so raw volume alone would rank them wrongly")
ok(hubs[3]["feeds_in"] == 25 and hubs[3]["partners_in"] == 2,
   "the receiving side is tracked too")
ok(PC.connection_hubs([]) == {}, "empty edge list -> empty hubs")

print("\n-- against the live book -------------------------------------------")

gids = sorted(SEAS.game_pool("2025-2026", gender="F", tracked_only=True))
ev = S.fetch_events(gids)
live = PC.connection_matrix(events=ev)
ok(len(live) > 0, f"league graph built ({len(live)} edges)")
t1 = PC.connection_matrix(events=ev, team_id=1)
ok(0 < len(t1) < len(live), f"team 1 is a subset ({len(t1)} edges)")
ok(all(r["feeds"] >= PC.MIN_EDGE_FEEDS for r in live), "floor respected")
ok(all(r["made"] <= r["feeds"] for r in live), "made never exceeds feeds")
ok(all(r["xa"] <= r["feeds"] for r in live),
   "xA never exceeds feeds (it is a sum of probabilities)")
ok(all(r["xa"] >= 0 for r in live), "no negative expected assists")
ok(live == sorted(live, key=lambda r: (-r["feeds"], -r["xa"])),
   "edges come back sorted by volume")

_missed_edges = [r for r in live if r["made"] < r["feeds"]]
ok(len(_missed_edges) > 0,
   f"{len(_missed_edges)} edges carry missed looks the made-only graph "
   f"cannot see")

top = t1[0]
print(f"    busiest team-1 line: {top['feeds']} feeds, {top['made']} made, "
      f"xA {top['xa']}")

hubs = PC.connection_hubs(t1)
ok(len(hubs) > 0, f"hubs roll up ({len(hubs)} players)")
ok(sum(h["feeds_out"] for h in hubs.values())
   == sum(h["feeds_in"] for h in hubs.values()),
   "every feed out is a feed in — the roll-up balances")

v = PC.connection_verdict(t1, names={})
ok(len(v) > 0, f"verdict produces {len(v)} line(s)")
ok(all(len(x) == 3 for x in v), "verdict lines are (badge, n, html) triples")
ok(PC.connection_verdict([]) == [],
   "an empty graph says nothing rather than narrating zero")

print(f"\n{PASS} checks passed.")
