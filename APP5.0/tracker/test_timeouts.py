"""
Unit test for helpers/situational.timeout_splits (the after-timeout read).
Runs on SYNTHETIC events + timeout markers — no DB — so the "first possession
out of the huddle" attribution is pinned:
  * our offense counts only after OUR timeout,
  * our defense counts only after THEIR timeout,
  * a cross case (their possession after our timeout) counts for neither,
  * only the FIRST possession after a marker is ATO.
Run: python tracker/test_timeouts.py
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


def ev(et, q, t, team, res=None, stp=None, reb_team=None):
    return {"event_type": et, "quarter": q, "time": t, "shooter_team_id": team,
            "primary_player_id": 1, "shot_result": res, "shot_type": stp,
            "rebounder_team_id": reb_team, "possession_secs": 10}


A, B = 1, 2
evs = [
    # A baseline: 4 possessions, 2 made 2s -> 1.00 PPP before the ATO trip
    ev("shot", 1, "7:40", A, "make", 2),
    ev("shot", 1, "7:20", A, "miss", 2, reb_team=B),
    ev("shot", 1, "7:00", A, "make", 2),
    ev("shot", 1, "6:40", A, "miss", 2, reb_team=B),
    # A calls TO at 6:30 -> A's next possession is the drawn-up play (made 3)
    ev("shot", 1, "6:20", A, "make", 3),
    # a second A possession after the same TO must NOT count (flow, not ATO)
    ev("shot", 1, "6:00", A, "miss", 2, reb_team=B),
    # B calls TO at 5:00 -> B's next possession (a miss, our D holds)
    ev("shot", 1, "4:50", B, "miss", 2, reb_team=A),
    # B baseline possessions
    ev("shot", 1, "4:00", B, "make", 2),
    ev("shot", 1, "3:40", B, "make", 2),
    # cross case: A calls TO at 3:00 but B has the ball -> neither bucket
    ev("shot", 1, "2:50", B, "make", 2),
]
tos = [
    {"game_id": None, "team_id": A, "quarter": 1, "time": "6:30"},
    {"game_id": None, "team_id": B, "quarter": 1, "time": "5:00"},
    {"game_id": None, "team_id": A, "quarter": 1, "time": "3:00"},
]

out = SIT.timeout_splits(A, evs, tos, min_poss=1)

print("timeout_splits")
ok(out is not None, "returns a read")
ok(out["timeouts"] == 3, f"3 markers seen (got {out['timeouts']})")

ours = out.get("ours")
ok(ours is not None, "our-ATO bucket exists")
ok(ours["poss"] == 1, f"only the FIRST possession after our TO counts "
                      f"(got {ours['poss']})")
ok(abs(ours["PPP"] - 3.0) < 1e-9, f"ATO possession = the made 3 (PPP "
                                  f"{ours['PPP']:.2f})")
# baseline = A's full offense: 6 poss, 2+2+3 = 7 pts
ok(abs(ours["base_PPP"] - 7 / 6) < 1e-9,
   f"baseline PPP over every A possession (got {ours['base_PPP']:.3f})")

theirs = out.get("theirs")
ok(theirs is not None, "their-ATO bucket exists")
ok(theirs["poss"] == 1, f"only B's first possession after B's TO counts "
                        f"(got {theirs['poss']})")
ok(abs(theirs["dPPP"] - 0.0) < 1e-9, "their drawn-up play was a stop (0.00 PPP)")
# baseline allowed = B's full offense: 4 poss, 6 pts
ok(abs(theirs["base_dPPP"] - 1.5) < 1e-9,
   f"baseline allowed over every B possession (got {theirs['base_dPPP']:.3f})")

# no markers / no events -> None (nothing to read)
ok(SIT.timeout_splits(A, evs, []) is None, "no timeouts -> None")
ok(SIT.timeout_splits(A, [], tos) is None, "no events -> None")

print(f"\nALL {PASS} CHECKS PASSED")
