"""
Foul-trouble drag (spec Part 4i) — what the bench decision actually costs.

TWO TRAPS THIS FILE EXISTS TO PIN, both found while building it on live data.

1. THE FOUL CONVENTION IS INVERTED from the obvious guess. On a `foul` row
   primary_player_id is the player who was FOULED and secondary_player_id is
   the FOULER (fouls.py:5). Counting primary produced player-games with 10 and
   11 fouls on the live book -- impossible under a five-foul disqualification --
   and would have shipped a "foul trouble" engine measuring fouls DRAWN.

2. THE IN-GAME BEFORE/AFTER SPLIT IS BACKWARDS FOR RESERVES. A reserve enters
   late, so her Nth foul lands late, so the "before" window spans a game she
   mostly watched. Measured: #24 read before 32.5% / after 84.8%, #14 read
   27.1% / 85.5%. Neither was benched -- the split was measuring entry timing.
   The headline comparator is therefore the player's own SEASON floor share.

Run: python tracker/test_foul_trouble.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.foul_trouble as FT                   # noqa: E402
import helpers.stats as S                           # noqa: E402
import helpers.seasons as SEAS                      # noqa: E402
import helpers.fouls as FOULS                       # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


_EID = [0]


def e(kind="shot", made=False, who=1, fouler=None, team=1, gid=800):
    _EID[0] += 1
    return {"id": _EID[0], "game_id": gid, "event_type": kind, "quarter": 1,
            "time": "8:00", "possession_secs": 12, "primary_player_id": who,
            "shot_result": ("make" if made else "miss"),
            "rebound_by_id": None, "shot_type": 2, "pass_from_id": None,
            "shot_created_by_id": None, "blocked_by_id": None,
            "guarded_by_id": None, "zone": "center",
            "secondary_player_id": fouler, "official_id": None,
            "stolen_by_id": None, "shot_x": None, "shot_y": None,
            "play_type": None, "defense": None, "turnover_type": None,
            "hockey_from_id": None, "shooter_team_id": team}


print("\n-- the foul convention (trap 1) ------------------------------------")

ok("secondary_player_id = the FOULER" in FOULS.__doc__
   or "secondary_player_id = the FOULER" in FOULS.__doc__.replace("\n", " "),
   "fouls.py still documents secondary_player_id as the fouler")

# Build a game where player 1 fouls twice and player 2 is FOULED twice.
_EID[0] = 0
evs = [e("foul", who=2, fouler=1) for _ in range(2)]
counted = 0
for x in evs:
    if x["event_type"] == "foul" and x["secondary_player_id"] == 1:
        counted += 1
ok(counted == 2, "the fouler is read off secondary_player_id in the fixture")

print("\n-- the season-share comparator (trap 2) ----------------------------")

ORD = FT._ordinal
ok(ORD(1) == "1st" and ORD(2) == "2nd" and ORD(3) == "3rd" and ORD(4) == "4th",
   "ordinals read 1st/2nd/3rd/4th, not '2th'")
ok(ORD(11) == "11th" and ORD(12) == "12th", "teens are all -th")

# STARTER plays the whole game and picks up foul 2 at the midpoint, then sits.
# RESERVE only enters in the last quarter and fouls immediately -- the case the
# in-game split gets backwards.
STARTER, RESERVE, FILLER = 1, 2, 3
game = []
for i in range(120):
    game.append(e("shot", who=FILLER))
floor = {}
for i, x in enumerate(game):
    five = {FILLER, 8, 9, 10}
    if i < 60:
        five = five | {STARTER}
    elif i < 90:
        five = five | {7}
    else:
        five = five | {RESERVE}
    floor[x["id"]] = {1: frozenset(five)}
# starter's 2nd foul at index 59, reserve's 2nd foul at index 92
game.insert(59, e("foul", who=99, fouler=STARTER))
game.insert(59, e("foul", who=99, fouler=STARTER))
game.insert(94, e("foul", who=99, fouler=RESERVE))
game.insert(94, e("foul", who=99, fouler=RESERVE))
for x in game:
    floor.setdefault(x["id"], {1: frozenset({FILLER, 8, 9, 10})})

season = FT.season_floor_share(game, floor, team_id=1)
ok(season[STARTER] > season[RESERVE],
   f"the starter's season share ({season[STARTER]:.2f}) beats the reserve's "
   f"({season[RESERVE]:.2f})")
ok(abs(sum(1 for x in game if STARTER in floor[x["id"]][1]) / len(game)
       - season[STARTER]) < 1e-9, "season share is on-floor events / team events")
ok(FT.season_floor_share([], {}, team_id=1) == {}, "no events -> no shares")

print("\n-- gates -----------------------------------------------------------")

ok(FT.MIN_GAMES_AT_LEVEL >= 3, "a level needs 3+ games, not one anecdote")
ok(FT.MIN_REMAINING > 0,
   "a foul with no game left cannot be a bench decision")
ok(FT.TROUBLE_LEVELS == (2, 3, 4),
   "levels are the three real decisions: first half, second half, endgame")
ok(FT.MIN_STATE_POSS > 40,
   f"the pooled-net gate ({FT.MIN_STATE_POSS}) is well above the 40-possession "
   f"on/off gate this codebase already measured as unreliable")

empty = FT.bench_cost(events=[], floor={}, team_id=1)
ok(empty == {}, "no events -> no bench cost")
one_game = FT.bench_cost(events=game, floor=floor, team_id=1)
ok(one_game == {},
   f"a single game never reports (needs {FT.MIN_GAMES_AT_LEVEL})")

print("\n-- against the live book -------------------------------------------")

gids = sorted(SEAS.game_pool("2025-2026", gender="F", tracked_only=True))
ev = S.fetch_events(gids)

# the impossible-foul-count check that caught trap 1
import collections                                  # noqa: E402
per_game = collections.defaultdict(collections.Counter)
for x in ev:
    if x["event_type"] == "foul" and x["secondary_player_id"] is not None:
        per_game[x["game_id"]][x["secondary_player_id"]] += 1
worst = max((n for c in per_game.values() for n in c.values()), default=0)
ok(worst <= 5,
   f"no player commits more than 5 fouls in a game (max {worst}) — reading "
   f"primary_player_id instead gives 11")

bench = FT.bench_cost(game_ids=gids, events=ev, team_id=1)
ok(len(bench) > 0, f"bench cost built for {len(bench)} rotation players")
for pid, lv in bench.items():
    for level, d in lv.items():
        assert d["games"] >= FT.MIN_GAMES_AT_LEVEL, "game gate leaked"
        assert 0 <= d["season_share"] <= 100, "season share out of range"
        assert 0 <= d["after_share"] <= 100, "after share out of range"
        assert abs(d["drag"] - (d["season_share"] - d["after_share"])) < 0.11, \
            "drag is not season minus after"
ok(True, "every live row obeys its gates and its own arithmetic")

ok(all("in_game_drag" in d for lv in bench.values() for d in lv.values()),
   "the timing-sensitive in-game figure is kept, clearly named, as context")

# the reserves that broke the first version must now be absent or sane
_l2 = {p: lv[2]["drag"] for p, lv in bench.items() if 2 in lv}
print("    2nd-foul drag by player:",
      {p: round(v, 1) for p, v in sorted(_l2.items(), key=lambda kv: -kv[1])})
ok(len(_l2) > 0, "somebody reaches two fouls often enough to report")
starters = [v for v in _l2.values() if v > 0]
ok(len(starters) >= 2,
   f"{len(starters)} rotation players lose floor share on their 2nd foul")

state = FT.team_foul_state_net(game_ids=gids, events=ev, team_id=1, level=3)
ok(state["level"] == 3, "state read is scoped to the requested level")
ok(state["with_trouble"]["poss"] > 0 and state["clean"]["poss"] > 0,
   f"both states have possessions ({state['with_trouble']['poss']} / "
   f"{state['clean']['poss']})")
ok(state["clean"]["poss"] > state["with_trouble"]["poss"],
   "most possessions are played clean, as they should be")
print(f"    with 3+: {state['with_trouble']['net']:+.1f} per 100 "
      f"({state['with_trouble']['poss']} poss) · "
      f"clean {state['clean']['net']:+.1f} ({state['clean']['poss']} poss)")

v = FT.foul_trouble_verdict(bench, state, names={})
ok(len(v) > 0, f"verdict produces {len(v)} line(s)")
ok(all(len(x) == 3 for x in v), "verdict lines are (badge, n, html) triples")
ok(not any("2th" in x[2] or "3th" in x[2] for x in v),
   "no malformed ordinals in the rendered text")
ok(any("not handed out at random" in x[2] for x in v)
   or (state["with_trouble"]["poss"] < FT.MIN_STATE_POSS),
   "the net line carries its non-causal caveat whenever it appears")
ok(FT.foul_trouble_verdict({}, None) == [], "nothing to say -> says nothing")

print(f"\n{PASS} checks passed.")
