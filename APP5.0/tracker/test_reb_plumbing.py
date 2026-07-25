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

print("rebounding_verdict (player-card do-it-all read)")

# Nothing tagged -> honest silence, not a hedged sentence.
ok(RB.rebounding_verdict({}) == [],
   "untagged player gets NO verdict lines (silence beats hedging)")

# Above the table gate but below the VERDICT gate: the table may print the
# number, but a verdict must not assert on it.
ok(RB.rebounding_verdict({"def_secure_team_stab": 80.0,
                          "onball_misses": RB.VERDICT_MIN_ONBALL - 1}) == [],
   f"{RB.VERDICT_MIN_ONBALL - 1} contests: table can show it, verdict stays quiet")

solo = RB.rebounding_verdict({"def_secure_team_stab": 72.0,
                              "onball_misses": 20})
ok(len(solo) == 1 and solo[0][0] == "Box-out" and solo[0][1] == 20,
   "box-out line carries its own n")
ok("72%" in solo[0][2], f"box-out line states the rate (got {solo[0][2]!r})")
ok("best on the team" not in solo[0][2],
   "no ranking clause without a pool to rank against")

# Ranking comes from the pool the caller passes.
me = {"def_secure_team_stab": 72.0, "onball_misses": 20}
peers = [{"def_secure_team_stab": 55.0, "onball_misses": 20},
         {"def_secure_team_stab": 40.0, "onball_misses": 20}]
ok("best on the team" in RB.rebounding_verdict(me, pool=peers)[0][2],
   "tops the pool -> 'best on the team'")
ok("2nd on the team" in RB.rebounding_verdict(
    me, pool=peers + [{"def_secure_team_stab": 90.0, "onball_misses": 20}])[0][2],
   "one player better -> '2nd on the team'")
# A thin peer must not enter the ranking pool: a 99% rate on 2 contests cannot
# demote a real sample to "2nd on the team".
_thin_peer = {"def_secure_team_stab": 99.0, "onball_misses": 2}
ok("best on the team" in RB.rebounding_verdict(
    me, pool=peers + [_thin_peer])[0][2],
   "a peer below the verdict gate cannot demote a real sample")
# And a pool of ONLY thin peers leaves no ranking clause at all, rather than
# inventing one against nobody.
_only_thin = RB.rebounding_verdict(me, pool=[_thin_peer])[0][2]
ok("on the team" not in _only_thin,
   f"all-thin pool -> no ranking clause (got {_only_thin!r})")

# Board mix is a STYLE read: both extremes speak, neither is graded.
lo = RB.rebounding_verdict({"onball_share": 12.0, "tagged_dreb": 20})
hi = RB.rebounding_verdict({"onball_share": 75.0, "tagged_dreb": 20})
ok("weak-side crasher" in lo[0][2], "low on-ball share reads as weak-side crashing")
ok("own assignment" in hi[0][2].lower(),
   "high on-ball share reads as cleaning up their own")
for v in (lo, hi):
    txt = v[0][2].lower()
    ok("poor" not in txt and "bad" not in txt and "worse" not in txt,
       f"board-mix line grades nobody (got {v[0][2][:44]!r}...)")

# The combined read — the whole reason these three ship together. It is
# POOL-RELATIVE (top-third payoff, bottom-third on-ball share), because the
# live distributions are compressed enough that absolute cutoffs fired for
# nearly everyone: `stab >= 60 and share <= 30` tagged 25 of 57 players.
def _peer(stab, share):
    return {"def_secure_team_stab": stab, "onball_misses": 20,
            "onball_share": share, "tagged_dreb": 20}


# A pool spanning the real range: payoff 55-70, share 0-45.
_cal = [_peer(s, sh) for s, sh in
        ((55, 40), (58, 35), (60, 30), (62, 25), (64, 20), (66, 10), (70, 45))]

_hi_lo = _peer(69.0, 5.0)      # top-third payoff, bottom-third share
labels = [c[0] for c in RB.rebounding_verdict(_hi_lo, pool=_cal)]
ok("Does it all" in labels,
   f"top-third payoff + bottom-third share -> do-it-all line (got {labels})")

_hi_hi = _peer(69.0, 44.0)     # same payoff, but cleans up his own assignment
ok("Does it all" not in [c[0] for c in RB.rebounding_verdict(_hi_hi, pool=_cal)],
   "a HIGH on-ball share is not the do-it-all pattern, however good the payoff")

_mid_lo = _peer(56.0, 5.0)     # crashes weak-side but the payoff is bottom-third
ok("Does it all" not in [c[0] for c in RB.rebounding_verdict(_mid_lo, pool=_cal)],
   "crashing weak-side alone is not do-it-all without the box-out payoff")

# Absolute numbers that used to trip the old rule now depend on the company
# they keep — the same player is distinctive in one pool and ordinary in another.
_strong_pool = [_peer(s, sh) for s, sh in
                ((68, 4), (69, 3), (70, 2), (67, 6), (66, 8))]
ok("Does it all" not in [c[0] for c in
                         RB.rebounding_verdict(_peer(64.0, 12.0), pool=_strong_pool)],
   "pool-relative: an ordinary player in a strong pool gets no do-it-all line")

ok(RB.rebounding_verdict(_hi_lo) and "Does it all" not in
   [c[0] for c in RB.rebounding_verdict(_hi_lo)],
   "with NO pool there is nothing to calibrate against -> combo stays silent")

# Own-miss recovery is a rare event: speak only when notable.
ok(RB.rebounding_verdict({"own_miss_rec_pct": 30.0, "own_misses": 10})[0][0]
   == "Second chance", "notable own-miss recovery surfaces")
ok(RB.rebounding_verdict({"own_miss_rec_pct": 5.0, "own_misses": 10}) == [],
   "ordinary own-miss recovery stays quiet (no filler line)")

print("verdict ranks against the player's OWN team")

# "best on the team" must be literally true: a stronger player on ANOTHER team
# cannot demote this one, or the claim lies to the coach.
_me_t = {"team": "Adair", "def_secure_team_stab": 60.0, "onball_misses": 20}
_other = {"team": "Westville", "def_secure_team_stab": 95.0, "onball_misses": 20}
# Only opponents in the pool -> no teammates to rank against, so the line says
# nothing about rank: a better player on another team must not demote them, and
# "best on the team" with zero teammates would be a vacuous claim.
_cross = RB.rebounding_verdict(_me_t, pool=[_other])[0][2]
ok("on the team" not in _cross,
   f"no teammates in pool -> no ranking clause either way (got {_cross!r})")
_mate = {"team": "Adair", "def_secure_team_stab": 95.0, "onball_misses": 20}
ok("2nd on the team" in RB.rebounding_verdict(_me_t, pool=[_mate, _other])[0][2],
   "a better TEAMMATE does demote it")

print("player_stat_table exposes the engine key names the verdict reads")

_needed = ("def_secure_team_stab", "def_secure_team_pct", "onball_share",
           "own_miss_rec_pct", "onball_misses", "own_misses", "tagged_dreb")
import re as _re
_src = open(Path(__file__).resolve().parent.parent / "helpers"
            / "player_ratings.py", encoding="utf-8").read()
_tbl = _src[_src.index("def player_stat_table"):]
_missing = [k for k in _needed if f'"{k}":' not in _tbl]
ok(not _missing,
   f"player_stat_table carries every key rebounding_verdict reads "
   f"(missing: {_missing or 'none'})")

print(f"\nALL {PASS} CHECKS PASSED")
