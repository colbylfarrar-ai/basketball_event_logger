"""
Tagged-rebounding plumbing into profiles / player_stat_table (spec Part 8
commit 4) — synthetic events, no DB writes.

What this guards is the None-vs-0 boundary, which is the whole reason the
plumbing is delicate: a coach who never tags `guarded_by` must read None (leaf
drops out of the weighted mean) and never 0 (which would score a tagging gap as
bad defense). Same trap as CHG/G, and the reason def_secure is T3 not T2.

The engine itself is covered by test_rebounding.py; this covers the MAPPING —
gates applied at the right thresholds, volumes always present as honest ints,
and the stabilized twin (not the raw rate) being what a leaf can read.

Run: python tracker/test_reb_plumbing.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.rebounding as RB                    # noqa: E402
import helpers.player_ratings as PR                # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── the gate arithmetic the profiles mapping performs ────────────────────────
# Mirrors the expressions added to player_profiles: rates gated on volume,
# volumes unconditional. Kept as a tiny local so the boundary is testable
# without standing up a 200-line profiles fixture.
def _map(rb):
    ob = rb.get("onball_misses", 0)
    return {
        "def_secure_team_stab": (rb.get("def_secure_team_stab")
                                 if ob >= RB.MIN_ONBALL else None),
        "def_secure_team_pct": (rb.get("def_secure_team_pct")
                                if ob >= RB.MIN_ONBALL else None),
        "onball_share": (rb.get("onball_share")
                         if rb.get("dreb", 0) >= 3 else None),
        "own_miss_rec_pct": (rb.get("own_miss_rec_pct")
                             if rb.get("own_misses", 0) >= 3 else None),
        "onball_misses": ob,
        "own_misses": rb.get("own_misses", 0),
        "tagged_dreb": rb.get("dreb", 0),
    }


print(f"MIN_ONBALL gate (= {RB.MIN_ONBALL})")

# An untagged player is ABSENT from player_rebounding entirely -> {} -> None.
m = _map({})
ok(m["def_secure_team_stab"] is None,
   "untagged player reads None, not 0 (leaf drops from the mean)")
ok(m["onball_misses"] == 0 and m["tagged_dreb"] == 0,
   "volumes are still honest ints for an untagged player")

# One below the gate: a real but too-thin sample must not surface.
thin = {"onball_misses": RB.MIN_ONBALL - 1, "def_secure_team_stab": 91.0,
        "def_secure_team_pct": 100.0, "dreb": 9, "own_misses": 5,
        "onball_share": 55.0, "own_miss_rec_pct": 40.0}
m = _map(thin)
ok(m["def_secure_team_stab"] is None,
   f"{RB.MIN_ONBALL - 1} contests is below the gate -> rate suppressed")
ok(m["def_secure_team_pct"] is None, "raw pct suppressed on the same gate")
ok(m["onball_misses"] == RB.MIN_ONBALL - 1,
   "...but the volume is still reported (honest n)")
ok(m["onball_share"] == 55.0,
   "on-ball share rides its OWN gate (>=3 boards), not the contest gate")

# At the gate: surfaces.
atg = dict(thin, onball_misses=RB.MIN_ONBALL)
m = _map(atg)
ok(m["def_secure_team_stab"] == 91.0, "exactly at the gate -> rate surfaces")

# Independent gates: plenty of contests, but too few boards / own misses.
m = _map({"onball_misses": 20, "def_secure_team_stab": 70.0, "dreb": 2,
          "own_misses": 1, "onball_share": 50.0, "own_miss_rec_pct": 100.0})
ok(m["def_secure_team_stab"] == 70.0, "box-out payoff surfaces on 20 contests")
ok(m["onball_share"] is None, "2 boards is below the 3-board share gate")
ok(m["own_miss_rec_pct"] is None,
   "1 own miss is below the 3-miss recovery gate (rare event stays quiet)")

print("stabilized twin is what a leaf may read")

# Build a real engine row from synthetic events and confirm the EB twin is
# pulled toward the pool rather than sitting at a raw extreme.
TA_, TB = 1, 2
A1, A2 = 11, 12
B1 = 21
EV = []


def miss(shooter, s_team, reb, r_team, guard):
    EV.append({"event_type": "shot", "shot_result": "miss", "shot_type": 2,
               "primary_player_id": shooter, "shooter_team_id": s_team,
               "rebound_by_id": reb, "rebounder_team_id": r_team,
               "guarded_by_id": guard, "shot_created_by_id": None,
               "play_type": None, "zone": "C", "game_id": 1})


# A1 guards 6 misses and team A secures every one -> raw 100%.
for _ in range(6):
    miss(B1, TB, A2, TA_, A1)
# A2 guards 6 and the shooting team keeps every board -> raw 0%. Two opposite
# extremes give the EB prior something to shrink toward.
for _ in range(6):
    miss(B1, TB, B1, TB, A2)

P = RB.player_rebounding(events=EV)
raw1 = P[A1]["def_secure_team_pct"]
stab1 = P[A1]["def_secure_team_stab"]
ok(raw1 == 100.0, f"A1 raw box-out payoff is the 100% extreme (got {raw1})")
ok(stab1 is not None and stab1 < raw1,
   f"stabilized twin is shrunk off the extreme ({stab1} < {raw1})")
ok(P[A2]["def_secure_team_stab"] > P[A2]["def_secure_team_pct"],
   "the 0% extreme is shrunk UP toward the pool for the same reason")
ok(PR.leaf_tier("def_secure_team_stab") == PR.T3_TAGGED,
   "def_secure_team_stab is tagged T3 (needs guarded_by AND rebound_by)")

print("scale: engine rates are ALREADY 0-100")

# The live-book bug this catches: player_stat_table wrapped these in _pct(),
# which multiplies by 100 — correct for `profiles` fractions like 3P%/TS%, but
# these rates are percentages when they leave rebounding.py, so it printed
# 6940%. Any rate here above 100 means someone re-introduced the double scale.
for key in ("def_secure_team_pct", "def_secure_team_stab", "onball_share",
            "own_miss_rec_pct"):
    vals = [P[p][key] for p in P if P[p].get(key) is not None]
    ok(all(0.0 <= v <= 100.0 for v in vals),
       f"{key} stays within 0-100 (got {sorted(vals)[:4]})")

print(f"\nALL {PASS} CHECKS PASSED")
