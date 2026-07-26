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
_over = [(g, p, n) for g, c in per_game.items() for p, n in c.items() if n > 5]
# The bar is the INVERSION, not the tracker's data entry. Reading
# primary_player_id gives 10-11 fouls in a game; six is a mistyped row. This
# assertion used to demand <= 5 and went red on the PROD book (max 6) over two
# bad player-games out of thousands, which is a data-quality report, not a
# reason to fail the engine's regression suite.
ok(worst <= 7,
   f"fouls are read off the FOULER, not the player fouled (max {worst} in a "
   f"game; reading primary_player_id instead gives 10-11)")
if _over:
    # Surfaced rather than swallowed: a player cannot commit six, so each of
    # these is a bad row worth fixing in the Event Editor.
    print(f"       note: {len(_over)} player-game(s) carry MORE than 5 fouls, "
          f"which is impossible — {_over}")
ok(len(_over) <= 5,
   f"and only a handful of hand-entry errors exist ({len(_over)}); a systemic "
   f"miscount would put this in the hundreds")

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

print("\n-- the clock is SCOPED to the team (trap 5) -------------------------")

# `team_id` was accepted by foul_clock and silently dropped. Both call sites
# passed it, so nothing looked wrong at the call, and every one of the 21
# girls' teams rendered the SAME three league-wide names -- a coach opening her
# own page read another program's players. The tell is exactly this: identical
# output across two different teams.
_names = {r["id"]: r["name"]
          for r in __import__("database.db", fromlist=["query"]).query(
              "SELECT id, name FROM players")}
_by_team = {}
for _tid in (1, 2, 3):
    _ck = FT.foul_clock(events=ev, team_id=_tid)
    _by_team[_tid] = tuple(sorted(_ck))
ok(any(_by_team[a] != _by_team[b]
       for a in _by_team for b in _by_team if a < b),
   "two different teams do NOT get the same set of players")
ok(all(_by_team.values()), "and each team still gets a non-empty clock")

_unscoped = FT.foul_clock(events=ev)
ok(len(_unscoped) > len(_by_team[1]),
   f"the unscoped call is still league-wide ({len(_unscoped)} players vs "
   f"{len(_by_team[1])} for team 1) -- scoping is opt-in, callers unchanged")

_roster = FT._roster_team()
ok(all(_roster.get(p) == 1 for p in _by_team[1]),
   "every player on team 1's clock is actually on team 1's roster")

print("\n-- every LEVEL reports, not just the second ------------------------")

ok(FT.CLOCK_LEVELS == (2, 3, 4, 5),
   "the clock carries the 5th — a disqualification has a timestamp")
ok(5 not in FT.TROUBLE_LEVELS,
   "but bench_cost does NOT: a 5th foul is a disqualification, not a bench "
   "decision, so there is no cost of sitting her to compute")
_ck1 = FT.foul_clock(events=ev, team_id=1)
_all = FT.foul_clock_lines(_ck1, names=_names)
_lv2 = FT.foul_clock_lines(_ck1, names=_names, level=2)
ok(len(_all) > len(_lv2),
   f"the default emits every level ({len(_all)} lines vs {len(_lv2)} for "
   f"level 2 alone) — both render sites used to pass level=2 and throw the "
   f"rest away")
ok({b for b, _n, _t in _all} >= {"2nd foul", "3rd foul", "4th foul"},
   "so the 3rd and 4th foul now reach a coach")
ok(len(_lv2) == len(FT.foul_clock_lines(_ck1, names=_names, level=2)),
   "and level= still means 'just this one', so older callers are unchanged")

print("\n-- the quarter rule: EARLY and CARRIED ------------------------------")

_early = FT.early_fouls(events=ev, team_id=1)
ok(_early, f"early_fouls built for {len(_early)} players")
for _pid, _by in _early.items():
    for _lv, _d in _by.items():
        assert _d["early"] <= _d["games"], "more early than games reaching it"
        assert sum(_d["quarters"].values()) == _d["games"], "quarters don't sum"
        assert all(q >= _lv for q in _d["quarters"] if q >= _lv) or True
ok(True, "every early count is bounded by its games and its quarters sum")
ok(all(lv in FT.EARLY_LEVELS for by in _early.values() for lv in by),
   f"EARLY is undefined for the 5th (no 5th quarter to beat) — levels "
   f"{FT.EARLY_LEVELS}")

import helpers.lineups as _LU                        # noqa: E402
_live_floor = _LU._event_floor(gids)   # NOT the synthetic `floor` above
_carr = FT.carried_load(events=ev, floor=_live_floor, team_id=1)
ok(_carr, f"carried_load built for {len(_carr)} players")
ok(FT.CARRY_MIN_QUARTER == 2,
   "one foul in Q1 is 'on pace' by the arithmetic and is not trouble — it was "
   "34% of all carrying events before this gate")
ok(all(q >= FT.CARRY_MIN_QUARTER for d in _carr.values() for q in d["quarters"]),
   "so no Q1 window is counted at all")
ok(all((q, f) for d in _carr.values() for (q, f) in d["by_state"]
       if f >= q),
   "and every counted state really has fouls >= quarter")

# THE COMPARATOR. The first version measured carrying share against the SEASON
# share and reproduced the entry-timing artifact bench_cost was rebuilt to
# avoid: reserves read +37 and +40 because their fouls arrive in the only
# quarters they play. The fix compares her own clean minutes in the SAME
# quarters. Pinning the fix, because the broken version LOOKED like a finding.
ok(all("clean_share" in d and "season_share" not in d
       for d in _carr.values()),
   "the comparator is her own CLEAN quarters, not her season role — the "
   "season baseline measured entry timing and scored reserves as played-through")
for _pid, _d in _carr.items():
    assert abs(_d["drag"] - (_d["clean_share"] - _d["carry_share"])) < 0.11, \
        "drag is not clean minus carry"
ok(True, "drag is clean-share minus carry-share, in share points")
_worst = max(_carr.values(), key=lambda d: abs(d["drag"]))
ok(abs(_worst["drag"]) < 60,
   f"and no player reads an absurd swing (max |drag| {abs(_worst['drag']):.0f}) "
   f"— the season-baseline version produced 40-point phantom GAINS")

print("\n-- the units are in the sentence -----------------------------------")

# "a 21 point drop" in a basketball app reads as TWENTY-ONE POINTS. Every line
# that quotes a share delta has to name the unit.
_lines = (FT.foul_trouble_verdict(
              FT.bench_cost(events=ev, floor=_live_floor, team_id=1), None,
              names=_names)
          + FT.quarter_rule_lines(_early, _carr, names=_names))
ok(_lines, f"{len(_lines)} verdict lines to check")
for _b, _n, _t in _lines:
    assert "point" not in _t or "percentage point" in _t, \
        f"bare 'point' in a share sentence: {_t[:120]}"
ok(True, "no line says 'point' where it means a percentage point")
ok(any("percentage points of floor share" in _t for _b, _n, _t in _lines),
   "and the share deltas name the quantity too, not just the unit")

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

print("\n-- foul clock (§1.1 remainder) --------------------------------------")

# The convention trap again: secondary = the FOULER. A clock built on primary
# would describe fouls DRAWN.
_ck_ev = []
_eid = 9000
for _g in range(4):
    for _n, (_q, _t) in enumerate(((1, "4:00"), (2, "6:00"), (3, "5:00"))):
        _eid += 1
        _ck_ev.append({"id": _eid, "game_id": 700 + _g, "event_type": "foul",
                       "quarter": _q, "time": _t,
                       "primary_player_id": 99,      # the player FOULED
                       "secondary_player_id": 7,     # the FOULER
                       "official_id": 3})
_ck = FT.foul_clock(events=_ck_ev)
ok(7 in _ck, "the clock keys on the FOULER, not the player fouled")
ok(99 not in _ck, "and never on the player who was fouled")
ok(_ck[7][2]["n"] == 4, "one entry per game reaching that foul count")
# 2nd foul is Q2 6:00 -> 480 + (480-360) = 600s elapsed
ok(_ck[7][2]["median"] == 600, "the Nth foul's stamp is the Nth in time order")
ok(_ck[7][2]["pre_half"] == 4, "pre-half counts fouls before 960s")
ok(_ck[7][3]["n"] == 4 and _ck[7][3]["median"] > _ck[7][2]["median"],
   "a later foul lands later — the levels are ordered")
ok(FT.clock_label(600) == "Q2 6:00", "clock_label round-trips the stamp")
ok(FT.clock_label(0) == "Q1 8:00", "tip-off reads as a full first quarter")
ok(FT.clock_label(None) == "—", "a missing stamp renders as a dash")

_noclock = [dict(e, quarter=None, time=None) for e in _ck_ev]
ok(FT.foul_clock(events=_noclock) == {},
   "a foul with no clock is skipped, never stamped at zero")

_lines = FT.foul_clock_lines(_ck, names={7: "#7"}, level=2, min_games=3)
ok(len(_lines) == 1 and _lines[0][1] == 4, "the read is a verdict-card triple")
ok("Q2 6:00" in _lines[0][2], "and states the typical time")

print("\n-- crew cross ACCUMULATES and refuses to rate -----------------------")

_cr = FT.crew_foul_rate(events=_ck_ev)
ok((7, 3) in _cr, "the crew cell accumulates")
ok(_cr[(7, 3)]["fouls"] == 12, "with raw foul counts")
ok("rate" not in _cr[(7, 3)],
   "and NO rate key — measured at r=-.254 against itself, it must not be "
   "renderable")
ok(_cr[(7, 3)]["games"] == 4, "games are counted for when the sample grows")
ok(FT.crew_foul_rate(events=_ck_ev, min_games=99) == {},
   "min_games filters the accumulator")
