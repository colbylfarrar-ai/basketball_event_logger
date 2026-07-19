"""
Spec 2.1 — possession-model WP display curve.

`wpa.possession_timeline` steps at EVERY possession-ending event (shot make or
miss, turnover) plus made FTs — so stops and giveaways visibly move the curve
(via time decay), unlike the makes-only scoring walk. Margin only moves on
scores; GEI/summarize keep reading the scoring curve (award-history stability),
so `wp_curve`/`game_wpa` timelines are deliberately NOT this function.

Run: python tracker/test_possession_timeline.py (pure; no DB writes)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.wpa as W                            # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


T1, T2 = 10, 20


def ev(etype, q, time, team, result=None, stype=2):
    return {"event_type": etype, "quarter": q, "time": time,
            "shooter_team_id": team, "shot_result": result,
            "shot_type": stype}


events = [
    ev("shot", 1, "7:00", T1, "make", 2),      # home +2
    ev("shot", 1, "6:00", T2, "miss"),         # step, no margin move
    ev("turnover", 1, "5:00", T1),             # step, no margin move
    ev("free_throw", 1, "4:00", T2, "make"),   # away +1
    ev("foul", 1, "3:30", T2),                 # ignored (not a possession)
    ev("shot", 4, "0:30", T2, "make", 3),      # away +3 late
]

curve = W.possession_timeline(events, T1, T2)

print("shape + stepping")
ok(len(curve) == 5, f"5 steps (shots+turnover+FT make, foul skipped): {len(curve)}")
ts = [c[0] for c in curve]
ok(ts == sorted(ts), "elapsed monotone")
margins = [c[1] for c in curve]
ok(margins == [2, 2, 2, 1, -2], f"margin only moves on scores: {margins}")
ok(all(0.0 <= c[2] <= 1.0 for c in curve)
   and all(0.0 < c[2] < 1.0 for c in curve[:-1]),
   "wp in [0,1], strictly interior before the final step")

print("stops move the curve through time")
ok(curve[1][2] != curve[0][2],
   "a miss changes wp (time decay at same margin)")

print("perspective + edge")
ok(curve[-1][2] < 0.5, "home trailing late -> wp < 0.5")
edge = W.possession_timeline(events, T1, T2, pregame_edge=20.0)
ok(edge[0][2] > curve[0][2], "positive pregame edge lifts home wp")

print("empty input")
ok(W.possession_timeline([], T1, T2) == [], "no events -> empty curve")

print(f"\nALL {PASS} CHECKS PASSED")
