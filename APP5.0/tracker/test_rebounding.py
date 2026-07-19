"""
Item 6 — rebounding enrichment engine (pure synthetic events, no DB).

Run: python tracker/test_rebounding.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.rebounding as RB                    # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


TA_, TB = 1, 2          # team ids
A1, A2, A3 = 11, 12, 13  # team A players
B1, B2 = 21, 22          # team B players


def miss(shooter, s_team, reb, r_team, guard=None, stype=2, play=None,
         creator=None, zone="C"):
    return {"event_type": "shot", "shot_result": "miss", "game_id": 1,
            "primary_player_id": shooter, "shooter_team_id": s_team,
            "rebound_by_id": reb, "rebounder_team_id": r_team,
            "guarded_by_id": guard, "shot_type": stype, "play_type": play,
            "shot_created_by_id": creator, "zone": zone}


EVENTS = [
    # B1 shoots guarded by A1; A1 secures own contest (self + team secure)
    miss(B1, TB, A1, TA_, guard=A1),
    # B1 shoots guarded by A1; teammate A2 secures (team secure, not self;
    # A2's board is OFF-ball)
    miss(B1, TB, A2, TA_, guard=A1),
    # B2 shoots guarded by A1; B1 gets the OREB (contest lost)
    miss(B2, TB, B1, TB, guard=A1),
    # A3 misses a three, recovers own miss (OREB, own-miss recovery)
    miss(A3, TA_, A3, TA_, stype=3, zone="RW"),
    # A3 misses a two, B2 boards it (defense)
    miss(A3, TA_, B2, TB),
    # PnR miss: handler A1 shoots (creator A2 = screener), A2 secures -> screener
    miss(A1, TA_, A2, TA_, play="pnr", creator=A2),
    # PnR miss: handler A1 shoots, defense rebounds
    miss(A1, TA_, B1, TB, play="pnr", creator=A2),
    # untagged rebound -> excluded everywhere
    {"event_type": "shot", "shot_result": "miss", "game_id": 1,
     "primary_player_id": A1, "shooter_team_id": TA_, "rebound_by_id": None,
     "rebounder_team_id": None, "guarded_by_id": B1, "shot_type": 2,
     "play_type": None, "shot_created_by_id": None, "zone": "C"},
]

print("player metrics")
P = RB.player_rebounding(events=EVENTS)
a1 = P[A1]
ok(a1["onball_misses"] == 3, f"A1 contested 3 tagged misses ({a1['onball_misses']})")
ok(a1["def_secure_team"] == 2 and round(a1["def_secure_team_pct"], 1) == 66.7,
   "team secures 2/3 of A1's contests")
ok(a1["def_secure_self"] == 1, "A1 personally secured 1")
ok(a1["def_secure_team_stab"] is not None, "stabilized twin present")
a2 = P[A2]
ok(a2["dreb_offball"] == 1 and a2["dreb_onball"] == 0,
   "A2's board counted off-ball (wasn't guarding the shooter)")
ok(P[A1]["dreb_onball"] == 1, "A1's own-contest board counted on-ball")
a3 = P[A3]
ok(a3["own_misses"] == 2 and a3["own_miss_rec"] == 1
   and a3["own_miss_rec_pct"] == 50.0, "own-miss recovery 1/2")
ok(a3["oreb3"] == 1 and P[B1]["oreb2"] == 1, "OREBs split by shot type")

print("team long-rebound profile")
prof = RB.team_long_rebound_profile(TA_, events=EVENTS)
ok(prof["three"]["misses"] == 1 and prof["three"]["oreb_pct"] == 100.0,
   "own 3-miss OREB% (1/1)")
ok(prof["two"]["misses"] == 3 and prof["two"]["oreb"] == 1,
   f"own 2-miss profile (3 tagged, 1 oreb): {prof['two']['misses']}")
ok(prof["three"]["by_zone"].get("RW") == (1, 1), "zone split carried")

print("pnr roles")
roles = RB.pnr_rebound_roles(events=EVENTS)
ok(roles == {"misses": 2, "handler": 0, "screener": 1, "other_off": 0,
             "defense": 1}, f"screener + defense split ({roles})")

print(f"\nALL {PASS} CHECKS PASSED")
