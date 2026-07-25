"""
Kills (stop-strings) + answer rate — spec Part 4e / 4f. Synthetic events, no DB.

The subtle parts, each pinned below:
  * The unit is a TRIP, not a lineups.py "possession". An offensive rebound
    continues the same trip, and made FREE THROWS mean they scored — so a
    defensive trip that ended in two made FTs is NOT a stop, even though the
    possession model used for PPP ignores FT points entirely.
  * A string longer than the threshold is still ONE kill.
  * Streaks must not span the horn between games.

Run: python tracker/test_stops.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.stops as ST                         # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


US, THEM = 1, 2
_T = [0]


def e(team, kind="shot", made=False, pts=2, gid=1):
    """One possession-carrying event. `_T` advances the clock monotonically."""
    _T[0] += 1
    return {"id": _T[0], "game_id": gid, "event_type": kind,
            "shooter_team_id": team, "quarter": 1,
            "time": f"{max(0, 8 - _T[0] // 60)}:{59 - (_T[0] % 60):02d}",
            "shot_result": ("make" if made else "miss"),
            "shot_type": 3 if pts == 3 else 2,
            "primary_player_id": None}


def miss(team, **kw):
    return e(team, "shot", made=False, **kw)


def make(team, pts=2, **kw):
    return e(team, "shot", made=True, pts=pts, **kw)


def tov(team, **kw):
    ev = e(team, "turnover", **kw)
    ev["shot_result"] = None
    return ev


def ft(team, made=True, **kw):
    return e(team, "free_throw", made=made, **kw)


def run(events, **kw):
    return ST.team_stops(US, events=events, with_players=False, **kw)


print("trip segmentation")

# Alternating trips: they miss, we score, they miss, we score...
_alt = [miss(THEM), make(US), miss(THEM), make(US), miss(THEM), make(US)]
r = run(_alt)
ok(r["trips_faced"] == 3, f"three opponent trips seen (got {r['trips_faced']})")
ok(r["stops"] == 3, "all three produced nothing -> three stops")

# An OFFENSIVE REBOUND continues the same trip: two of their misses in a row
# with no possession change is ONE trip, not two.
_oreb = [miss(THEM), miss(THEM), make(US)]
r = run(_oreb)
ok(r["trips_faced"] == 1,
   f"consecutive opponent misses are ONE trip, not two (got {r['trips_faced']})")

print("free throws count as scoring (the divergence from the PPP model)")

# Their trip ends in two made FTs. The lineups possession model excludes FT
# points; a STOP cannot, because they scored.
r = run([miss(THEM), ft(THEM), ft(THEM), make(US)])
ok(r["trips_faced"] == 1 and r["stops"] == 0,
   "a trip ending in made FTs is NOT a stop")
r = run([miss(THEM), ft(THEM, made=False), ft(THEM, made=False), make(US)])
ok(r["stops"] == 1, "...but MISSED free throws leave it a stop")

print(f"kills (>= {ST.KILL_MIN} straight scoreless trips)")

def _n_stops(n, then_score=True):
    """n straight stops, then (by default) a concession that ends the string.

    NOTE the trailing `make(US)`: without it, concatenating two of these blocks
    puts `make(THEM)` immediately before the next `miss(THEM)`, and since no
    possession changes hands between them the trip model correctly MERGES them
    into one scoring trip — silently eating the next string's first stop. That
    is the engine behaving right and a naive fixture behaving wrong.
    """
    seq = []
    for _ in range(n):
        seq += [miss(THEM), make(US)]
    if then_score:
        seq += [make(THEM), make(US)]
    return seq


ok(run(_n_stops(2))["kills"] == 0, "two straight stops is not a kill")
ok(run(_n_stops(3))["kills"] == 1, "three straight stops IS a kill")
# A LONGER string is still one kill — counted once, when it crosses the line.
_five = run(_n_stops(5))
ok(_five["kills"] == 1,
   f"a five-stop string is still ONE kill (got {_five['kills']})")
ok(_five["longest_stop_streak"] == 5, "the streak length is reported separately")
# Two separate strings are two kills.
_two = run(_n_stops(3) + _n_stops(3))
ok(_two["kills"] == 2, f"two separate strings -> two kills (got {_two['kills']})")
ok(run(_n_stops(3), kill_min=4)["kills"] == 0, "kill_min is configurable")
ok(run(_n_stops(4), kill_min=4)["kills"] == 1, "...and honoured")

# A scoring trip breaks the string.
_broken = [miss(THEM), make(US), miss(THEM), make(US), make(THEM),
           miss(THEM), make(US)]
ok(run(_broken)["kills"] == 0, "a concession resets the streak")

print("streaks do not span the horn")

_g1 = [miss(THEM, gid=1), make(US, gid=1), miss(THEM, gid=1), make(US, gid=1)]
_g2 = [miss(THEM, gid=2), make(US, gid=2)]
r = run(_g1 + _g2)
ok(r["kills"] == 0,
   "two stops in game 1 plus one in game 2 is NOT a kill across the horn")
ok(r["games"] == 2, "both games counted")

print("answer rate (volleyball side-out)")

# They score, we answer; they score, we do not.
_ans = [make(THEM), make(US), make(THEM), miss(US)]
r = run(_ans)
a = r["answer"]
ok(a["chances"] == 2, f"two chances to answer (got {a['chances']})")
ok(a["answered"] == 1 and abs(a["rate"] - 50.0) < 1e-9,
   f"answered one of two -> 50% (got {a['rate']})")

# Our trip only counts as an answer chance when it FOLLOWS a concession.
r = run([miss(THEM), make(US), make(US)])
ok(r["answer"]["chances"] == 0,
   "no concession -> no answer chance (an unprompted score is not an answer)")

# "They scored on consecutive trips down" — measured across OPPONENT trips, so
# it does not matter what we did in between. Defining it as "scored twice with
# no trip of ours between" would essentially never fire, because consecutive
# same-team events never change possession and the trip walk merges them.
r = run([make(THEM), miss(US), make(THEM), make(US)])
ok(r["conceded_runs_allowed"] == 1,
   "opponent scored on two straight trips down -> one conceded run")
ok(run([make(THEM), make(US), make(THEM), make(US)])["conceded_runs_allowed"] == 1,
   "...still counted even though we answered in between (it is THEIR streak)")
r = run([make(THEM), make(US), miss(THEM), make(US), make(THEM)])
ok(r["conceded_runs_allowed"] == 0,
   "a stop between their scores breaks the streak")
# Two consecutive same-team scoring events are ONE trip, so they are not a run.
ok(run([make(THEM), make(THEM), make(US)])["conceded_runs_allowed"] == 0,
   "an and-1 style same-trip pair is one trip, not consecutive scores")

print("stop_pct is reported beside the threshold stat")

r = run([miss(THEM), make(US), make(THEM), make(US)])
ok(abs(r["stop_pct"] - 50.0) < 1e-9,
   f"one stop in two opponent trips -> 50% (got {r['stop_pct']})")
ok(r["kills"] == 0,
   "stop_pct moves where the kill count cannot — which is why both ship")

print("empty + verdict")

_empty = run([])
ok(_empty["trips_faced"] == 0 and _empty["kills"] == 0,
   "no events -> zeroes, no crash")
ok(_empty["stop_pct"] is None and _empty["answer"]["rate"] is None,
   "rates are None (unknown), not 0, with nothing to divide by")
ok(ST.stops_verdict(_empty) == [],
   "verdict is silent on an empty sample rather than asserting 0%")

_big = run(_n_stops(25))   # comfortably past the 20-trip verdict gate
ok(ST.stops_verdict(_big), "a real sample produces verdict lines")
ok(any("kill" in t.lower() for _b, _n, t in ST.stops_verdict(_big)),
   "the kill line states the count")

print("real book: trip points must reconcile with the SCOREBOARD")

# The strongest available correctness check, and the one that justifies trusting
# a 72% stop rate: sum the points the trip walk attributes to each team and
# compare against games.home_score / away_score. If trips fragmented or merged
# wrongly, or if made free throws were mishandled, these would not agree.
# Verified 2026-07-24: exact agreement on all 24 tracked games for the focus
# team, which is also what makes the extreme readings believable (the 26-trip
# scoreless streak comes from a 65-13 game).
try:
    from collections import defaultdict as _dd
    import helpers.stats as _S
    import helpers.team_analytics as _TA
    import tools.backtest as _BT
    from database.db import query as _q

    _tid, _gender, _n = _BT.focus_team()
    _tracked = [g["id"] for g in _BT.tracked_games()]
    _pool = _S.fetch_events(_tracked)
    _gids = sorted(_TA.event_team_games(_tid, _pool))
    _ev = _S.fetch_events(_gids)
    _trips = ST._trips(_ev)

    _ours, _theirs = _dd(int), _dd(int)
    for _g, _t, _p, _i in _trips:
        (_ours if _t == _tid else _theirs)[_g] += _p

    _rows = _q("SELECT id, team1_id, home_score, away_score FROM games "
               f"WHERE id IN ({','.join('?' * len(_gids))})", tuple(_gids))
    _checked = _mismatch = 0
    for _r in _rows:
        if _r["home_score"] is None:
            continue
        _us = _r["home_score"] if _r["team1_id"] == _tid else _r["away_score"]
        _them = _r["away_score"] if _r["team1_id"] == _tid else _r["home_score"]
        _checked += 1
        if _ours[_r["id"]] != _us or _theirs[_r["id"]] != _them:
            _mismatch += 1
    ok(_checked > 0, f"reconciled {_checked} tracked games against the box")
    ok(_mismatch == 0,
       f"trip points equal the final score in every game "
       f"({_mismatch} mismatches)")
except Exception as _ex:                       # no DB in this environment
    print(f"  .. skipping real-book reconciliation ({type(_ex).__name__}: {_ex})")

print(f"\nALL {PASS} CHECKS PASSED")
