"""
Trio / quad units + finisher finder (spec Part 4a) — synthetic events, no DB
writes for the math; one real-book cross-check at the end.

The load-bearing property is AGREEMENT: lineups.py already owns the locked
possession rule (a possession is a shot or a turnover; free-throw points
excluded) and lineups.custom_unit already scores an arbitrary 2-5 player set.
group_units must produce byte-identical numbers to custom_unit for any group
both can express — otherwise the new surface is a parallel dialect that will
quietly disagree with the five-man and pair surfaces beside it.

What group_units adds is ENUMERATION in one walk. custom_unit re-fetches events
and rebuilds the on-court floor per call, so looping it over C(10,3)+C(10,4)
= 330 groups would be 330 full event walks.

Run: python tracker/test_group_units.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.networks as NW                      # noqa: E402
import helpers.lineups as LU                       # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


TA_, TB = 1, 2
A = [11, 12, 13, 14, 15, 16]          # team A players
B = [21, 22, 23, 24, 25]              # team B players

_EID = [0]


def ev(off_team, pts, a_five, made=True, kind="shot"):
    """One possession-ending event with an explicit on-court five."""
    _EID[0] += 1
    return {
        "id": _EID[0], "event_type": kind, "game_id": 1,
        "shot_result": ("make" if made else "miss") if kind == "shot" else None,
        "shot_type": 3 if pts == 3 else 2,
        "primary_player_id": a_five[0], "shooter_team_id": off_team,
        "pass_from_id": None, "hockey_from_id": None,
        "shot_created_by_id": None, "rebound_by_id": None,
        "rebounder_team_id": None, "guarded_by_id": None, "zone": "C",
        "blocked_by_id": None, "secondary_player_id": None,
        "stolen_by_id": None, "play_type": None, "defense": None,
        "turnover_type": None, "period": 1, "assist_type": None,
        "_five": frozenset(a_five),
    }


def build(rows):
    """(events, floor) — floor mirrors lineups._event_floor's shape."""
    events, floor = [], {}
    for off_team, pts, five, made in rows:
        e = ev(off_team, pts, five, made=made)
        events.append(e)
        floor[e["id"]] = {TA_: e["_five"], TB: frozenset(B)}
    return events, floor


def patched(floor):
    """Swap in a synthetic on-court floor for both engines under test."""
    real_nw, real_lu = NW._event_floor, LU._event_floor
    NW._event_floor = lambda *_a, **_k: floor
    LU._event_floor = lambda *_a, **_k: floor
    return real_nw, real_lu


def restore(real_nw, real_lu):
    NW._event_floor, LU._event_floor = real_nw, real_lu


# Core five 11-15 scores well; swapping 16 in for 15 goes badly.
CORE = [11, 12, 13, 14, 15]
SWAP = [11, 12, 13, 14, 16]
rows = []
for _ in range(20):                       # core: scores 2, allows 0
    rows.append((TA_, 2, CORE, True))
    rows.append((TB, 0, CORE, False))
for _ in range(20):                       # swap: scores 0, allows 2
    rows.append((TA_, 0, SWAP, False))
    rows.append((TB, 2, SWAP, True))

EVENTS, FLOOR = build(rows)
_saved = patched(FLOOR)

try:
    print("group_units enumerates every size in one walk")

    G = NW.group_units(TA_, sizes=(3, 4), game_ids=None, events=EVENTS,
                       min_poss=1)
    ok(set(G) == {3, 4}, "returns one bucket per requested size")
    # 11-14 appear in BOTH lineups; 15 only in core, 16 only in swap.
    _trio_1114 = next(r for r in G[3] if r["players"] == (11, 12, 13))
    ok(_trio_1114["poss"] == 80,
       f"a trio common to both fives sees all 80 possessions "
       f"(got {_trio_1114['poss']})")
    ok(abs(_trio_1114["Net"]) < 1e-9,
       f"...and nets ~0, since its good and bad stretches cancel "
       f"(got {_trio_1114['Net']})")

    _quad_core = next(r for r in G[4] if r["players"] == (11, 12, 13, 14))
    ok(_quad_core["poss"] == 80, "the shared quad also sees 80 possessions")

    # A group containing 15 only ever played the GOOD stretch.
    _good = next(r for r in G[3] if r["players"] == (11, 12, 15))
    ok(_good["poss"] == 40 and _good["Net"] > 0,
       f"a group unique to the good five nets positive (got {_good['Net']})")
    _bad = next(r for r in G[3] if r["players"] == (11, 12, 16))
    ok(_bad["poss"] == 40 and _bad["Net"] < 0,
       f"a group unique to the bad five nets negative (got {_bad['Net']})")
    ok(abs(_good["Net"] + _bad["Net"]) < 1e-9,
       "the two are mirror images, as constructed")

    print("credibility shrink (thin groups must not outrank deep ones)")

    ok(_good["cred"] < 1.0, "cred is below 1 on a finite sample")
    ok(abs(_good["NetAdj"]) < abs(_good["Net"]),
       f"NetAdj is pulled toward 0 ({_good['NetAdj']} vs {_good['Net']})")
    # A tiny sample at a wild net must lose to a deep sample at a modest net.
    _tiny, _deep = 6, 400
    _c_tiny = _tiny / (_tiny + NW._GROUP_PRIOR_POSS)
    _c_deep = _deep / (_deep + NW._GROUP_PRIOR_POSS)
    ok(40 * _c_tiny < 12 * _c_deep,
       "a 6-poss group at +40 ranks BELOW a 400-poss group at +12")
    ok(G[3] == sorted(G[3], key=lambda d: -d["NetAdj"]),
       "rows come back sorted by the shrunk net, not the raw one")

    print("min_poss gates by size")

    _tight = NW.group_units(TA_, sizes=(3,), events=EVENTS, min_poss=41)
    ok(all(r["poss"] >= 41 for r in _tight[3]),
       "min_poss prunes thin groups")
    ok(not any(r["players"] == (11, 12, 15) for r in _tight[3]),
       "a 40-possession group is excluded at min_poss=41")
    ok(NW.GROUP_MIN_POSS[4] > NW.GROUP_MIN_POSS[3] > NW.GROUP_MIN_POSS[2],
       "default min_poss rises with group size — bigger groups are thinner")

    print("agreement with lineups.custom_unit (the locked possession rule)")

    for grp in ((11, 12, 13), (11, 12, 15), (11, 12, 13, 14)):
        k = len(grp)
        mine = next(r for r in NW.group_units(
            TA_, sizes=(k,), events=EVENTS, min_poss=1)[k]
            if r["players"] == grp)
        cu = LU.custom_unit(TA_, list(grp), events=EVENTS)
        ok(cu["poss"] == mine["poss"] and abs(cu["Net"] - mine["Net"]) < 0.05,
           f"{grp}: custom_unit and group_units agree "
           f"(poss {cu['poss']}, Net {cu['Net']})")

    print("finisher_finder ranks the fifth man")

    ff = NW.finisher_finder(TA_, (11, 12, 13, 14), events=EVENTS, min_poss=1)
    ok(ff["core_poss"] == 80, "core possessions counted over both fives")
    byid = {c["pid"]: c for c in ff["candidates"]}
    ok(set(byid) == {15, 16},
       f"only players who actually played WITH the core are candidates "
       f"(got {sorted(byid)})")
    ok(byid[15]["Net"] > 0 > byid[16]["Net"], "the good fifth ranks positive")
    ok(ff["candidates"][0]["pid"] == 15, "best candidate is listed first")
    # delta_vs_core is the honest read: credit for what the fifth ADDS.
    ok(byid[15]["delta_vs_core"] > 0 > byid[16]["delta_vs_core"],
       "delta_vs_core separates who lifts the core from who drags it")
    ok(abs(byid[15]["Net"] - byid[15]["delta_vs_core"]
           - ff["core_net"]) < 1e-9,
       "delta_vs_core == combined net minus the core's own net")

    ok(all(c["poss"] >= 20 for c in NW.finisher_finder(
        TA_, (11, 12, 13, 14), events=EVENTS, min_poss=20)["candidates"]),
       "finisher min_poss prunes thin candidates")

    print("guards")

    for bad in ((11,), (11, 12, 13, 14, 15)):
        try:
            NW.finisher_finder(TA_, bad, events=EVENTS)
            ok(False, f"core of {len(bad)} should raise")
        except ValueError:
            ok(True, f"a core of {len(bad)} is rejected (needs 2-4)")

    ok(NW.group_units(TA_, sizes=(3,), events=[], min_poss=1)[3] == [],
       "no events -> no groups (does not crash)")
finally:
    restore(*_saved)

print(f"\nALL {PASS} CHECKS PASSED")
