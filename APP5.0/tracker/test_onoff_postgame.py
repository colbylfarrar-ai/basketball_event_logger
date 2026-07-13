"""
On/off insight + post-game report test.

Throwaway DB via APP5_DATA_DIR set BEFORE imports (same pattern as
test_public_feed.py). Run: python tracker/test_onoff_postgame.py
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_onoff_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query             # noqa: E402
import helpers.game_events as GE                    # noqa: E402
import helpers.stats as S                           # noqa: E402
import helpers.lineups as LU                        # noqa: E402
import helpers.insights as INS                      # noqa: E402
import helpers.postgame as PG                       # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── seed: 2 teams, starters + a bench swap so a target has ON and OFF poss ──────
tA = execute("INSERT INTO teams (name, class, gender) VALUES ('Alpha','5A','M')")
tB = execute("INSERT INTO teams (name, class, gender) VALUES ('Bravo','5A','M')")
A = [execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
             (tA, f"A{i}", i)) for i in range(6)]     # A0..A5 (A5 = bench)
B = [execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
             (tB, f"B{i}", 10 + i)) for i in range(5)]
gid = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?, date('now'))",
              (tA, tB))

starters = [(A[0], tA), (A[1], tA), (A[2], tA), (A[3], tA), (A[4], tA)] \
    + [(b, tB) for b in B]
bench = [(A[5], tA), (A[1], tA), (A[2], tA), (A[3], tA), (A[4], tA)] \
    + [(b, tB) for b in B]

# 12 MAKES with A0 on the floor, 12 MISSES with A0 subbed out (A5 in). 12 clears
# lineups.DEFAULT_MIN_POSS on BOTH sides so onoff_edges (default gate) surfaces it.
for i in range(12):
    GE.log_event(gid, {"event_type": "shot", "quarter": 1, "time": f"7:{i:02d}",
                       "primary_player_id": A[0], "shot_result": "make",
                       "shot_x": 0.0, "shot_y": 8.0}, starters, [],
                 client_uuid=f"on-{i}")
for i in range(12):
    GE.log_event(gid, {"event_type": "shot", "quarter": 2, "time": f"6:{i:02d}",
                       "primary_player_id": A[5], "shot_result": "miss",
                       "shot_x": 0.0, "shot_y": 8.0}, bench, [],
                 client_uuid=f"off-{i}")

events = S.fetch_events([gid])

print("player_on_off engine")
oo = LU.player_on_off(tA, game_ids=[gid], events=events, min_poss=2)
ok(A[0] in oo, "target player has an on/off split")
a0 = oo[A[0]]
ok(a0["on_poss"] == 12 and a0["off_poss"] == 12,
   "12 on + 12 off offensive possessions")
ok(a0["on_ortg"] == 200.0 and a0["off_ortg"] == 0.0,
   "on = 200/100 (all makes), off = 0 (all misses)")
ok(a0["off_diff"] == 200.0, "off_diff = on - off")
# the bench swap-in is the mirror image (on for the misses, off for the makes)
ok(A[5] in oo and oo[A[5]]["off_diff"] == -200.0, "bench player mirrors negative")
# an always-on starter is excluded (no off-floor sample)
ok(A[1] not in oo, "always-on player excluded (no off possessions)")

print("onoff_edges merge across teams")
edges = INS.onoff_edges(events)
ok(A[0] in edges and edges[A[0]]["off_diff"] == 200.0,
   "onoff_edges surfaces the split from events alone")

print("_g_onoff generator gating + text")
# below the 40-poss gate -> silent
ok(INS._g_onoff({}, {}, {"onoff": edges[A[0]]}) is None, "thin sample: no card")
# synthetic season-scale split, positive -> "offense hums"
hot = {"onoff": {"on_poss": 120, "off_poss": 60, "on_ortg": 112.0,
                 "off_ortg": 96.0, "off_diff": 16.0}}
c = INS._g_onoff({}, {}, hot)
ok(c and "hums" in c["text"] and c["metric"] == "On/off offense",
   "positive split -> offense-hums card")
cold = {"onoff": {"on_poss": 120, "off_poss": 60, "on_ortg": 90.0,
                  "off_ortg": 108.0, "off_diff": -18.0}}
c2 = INS._g_onoff({}, {}, cold)
ok(c2 and "stalls" in c2["text"], "negative split -> offense-stalls card")

print("postgame report")
execute("UPDATE games SET tracked=1, home_score=24, away_score=0 WHERE id=?", (gid,))
bullets = PG.game_report(gid, events=events, gei=(5.4, "Instant classic"))
ok(isinstance(bullets, list) and bullets, "report returns bullets")
ok(any("Alpha" in b and "24" in b for b in bullets),
   "headline names the winner + score")
ok(any("5.4" in b for b in bullets), "excitement line included when gei passed")
ok(PG.game_report(999999) == [], "unknown game -> empty list")

print(f"\nALL {PASS} CHECKS PASSED")
