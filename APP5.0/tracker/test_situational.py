"""
Unit test for helpers/situational.py (play_type/defense breakdown by game situation
+ per-player situational edges). Runs on SYNTHETIC events — no DB — so the
game-state tagging (quarter / margin / run) and the situation slicing are pinned.
Run: python tracker/test_situational.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.situational as SIT  # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def ev(et, q, t, team, pid, res=None, stp=None, pt=None, dfn=None):
    return {"event_type": et, "quarter": q, "time": t, "shooter_team_id": team,
            "primary_player_id": pid, "shot_result": res, "shot_type": stp,
            "play_type": pt, "defense": dfn, "rebounder_team_id": None}


A, B = 1, 2
evs = []
# Q1 — A runs PnR only (6 shots, 3 makes); B answers with iso.
for i in range(6):
    evs.append(ev("shot", 1, f"7:{40 - i:02d}", A, 10 + i % 2,
                  "make" if i < 3 else "miss", 2, "pnr", "man"))
for i in range(3):
    evs.append(ev("shot", 1, f"5:{40 - i:02d}", B, 20, "make", 2, "iso", "zone_23"))
# Q2 — B goes on a scoring run (margin swings to A trailing).
for i in range(6):
    evs.append(ev("shot", 2, f"6:{40 - i:02d}", B, 20, "make", 3, "spot", "man"))
# Q4 — A trailing big, runs BLOB / transition.
for i in range(8):
    evs.append(ev("shot", 4, f"5:{40 - i:02d}", A, 10 + i % 2,
                  "make" if i % 2 else "miss", 2, "blob" if i % 2 else "transition",
                  "trap_23"))

# ── game-state tagging ──────────────────────────────────────────────────────
SIT.annotate(evs, A)
q1_pnr = next(e for e in evs if e["quarter"] == 1 and e["play_type"] == "pnr")
ok(q1_pnr["_sit"]["q"] == 1, "annotate: quarter tag")
# By Q4, A trails (B ran a 6-shot scoring spree in Q2) -> negative margin somewhere.
q4 = [e for e in evs if e["quarter"] == 4]
ok(any(e["_sit"]["margin"] < 0 for e in q4), "annotate: A trailing in Q4 (margin<0)")
ok(any(e["_sit"]["run"] == "opp" for e in evs), "annotate: opponent run detected")

# ── team_situational ────────────────────────────────────────────────────────
res = SIT.team_situational(A, evs)
ok(res is not None, "team_situational returns a result")
ok(res["situations"][0]["key"] == "all", "baseline 'all' is first")
keys = {s["key"] for s in res["situations"]}
ok("q1" in keys and "q4" in keys, "quarter situations present")
ok("trail" in keys, "trailing situation present")
q1 = next(s for s in res["situations"] if s["key"] == "q1")
ok(q1["top_play"] and q1["top_play"]["key"] == "pnr", "Q1 go-to set = PnR")
ok(q1["top_play"]["share"] == 1.0, "Q1 PnR share = 100% (only set run)")
# PnR is 100% in Q1 but a minority overall -> a 'situational set' (usage spikes).
ok(any(c["play_label"] == "Pick & roll" for c in res["concentration"]),
   "concentration flags PnR as a Q1 situational set")
# defense scheme A ran in Q4 (offense=False over B's events in that game-state)
ok(isinstance(res["rows"], list) and res["rows"], "flat scout rows built")

# ── per-player situational edges (quarter-based clutch) ─────────────────────
clutch = []
for i in range(4):  # pid 99: cold early, then hot in Q4
    clutch.append(ev("shot", 1, f"7:{40 - i:02d}", A, 99, "miss", 2, "iso"))
for i in range(10):
    clutch.append(ev("shot", 4, f"5:{40 - i:02d}", A, 99,
                     "make" if i < 8 else "miss", 2, "blob"))
edges = SIT.player_situational_edges(clutch)
ok(99 in edges, "player edge found for the clutch player")
ok(edges[99]["label"] == "4th quarter" and edges[99]["delta"] > 0,
   "clutch player flagged with a positive 4th-quarter delta")
# below-sample players are dropped
ok(SIT.player_situational_edges(clutch[:3]) == {}, "thin sample -> no edges")

# ── regression: score-state replay RESETS per game (margin must not accumulate
#    across a team's many tracked games — the "Close only shows 3 poss" bug) ────
def _g(e, gid):
    e["game_id"] = gid
    return e

multi = []
# Game 101: A blows B out -> ends ~ +20, so the LAST events are "leading big".
for i in range(12):
    multi.append(_g(ev("shot", 1, f"7:{50 - i:02d}", A, 30, "make", 2, "pnr"), 101))
# Game 102: A vs B trade baskets -> the score stays within +/-5 (a CLOSE game).
for i in range(10):
    team = A if i % 2 == 0 else B
    multi.append(_g(ev("shot", 1, f"7:{50 - i:02d}", team, 30 if team == A else 40,
                       "make", 2, "iso"), 102))

SIT.annotate(multi, A)
# every Game-102 event must see a small (within-game) margin — NOT A's +20 from
# game 101 carried over.
g102 = [e for e in multi if e["game_id"] == 102]
ok(all(abs(e["_sit"]["margin"]) <= SIT.CLOSE for e in g102),
   "margin resets per game (Game 102 stays within +/-5, no carryover)")
res_m = SIT.team_situational(A, multi)
_close = next((s for s in res_m["situations"] if s["key"] == "close"), None)
ok(_close is not None and _close["off_poss"] >= 8,
   "Close (+/-5) captures the whole close game, not just the opening tip")
# without the per-game reset this would be ~1-3; with it, all of game 102 counts.

print(f"\nALL {PASS} CHECKS PASSED")
