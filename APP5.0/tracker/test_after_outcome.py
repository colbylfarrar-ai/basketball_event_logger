"""
Unit test for helpers/situational.py after-outcome response splits
(annotate_after / team_after_outcome) + the team_insights after_extra feed and
its generators. Runs on SYNTHETIC events — no DB — so the possession-sequence
replay (make → flip, offensive rebound → continue, turnover → break, per-game
reset) and the bucket tagging are pinned.
Run: python tracker/test_after_outcome.py
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


A, B = 1, 2
_clock = [480]


def _t():
    _clock[0] -= 7
    return f"{_clock[0] // 60}:{_clock[0] % 60:02d}"


def ev(et, team, res=None, stp=2, pt=None, dfn=None, reb=None, secs=None, gid=1):
    return {"event_type": et, "quarter": 1, "time": _t(), "game_id": gid,
            "shooter_team_id": team, "primary_player_id": 100 + team,
            "shot_result": res, "shot_type": stp, "play_type": pt,
            "defense": dfn, "rebounder_team_id": reb, "possession_secs": secs}


# ── a scripted possession sequence (perspective = team A) ────────────────────
e1 = ev("shot", A, "make", pt="iso", secs=10)          # A scores
e2 = ev("shot", B, "make", dfn="man")                   # B scores (our D)
e3 = ev("shot", A, "miss", reb=B, pt="pnr")             # A misses, B rebounds
e4 = ev("shot", B, "miss", reb=A, dfn="zone_23")        # B misses, A rebounds
e5 = ev("turnover", A)                                   # A turns it over
e6 = ev("turnover", B)                                   # B turns it over (our steal)
e7 = ev("shot", A, "make", pt="transition")             # A scores
e8 = ev("shot", B, "make", dfn="man")                   # B scores (our D)
e9 = ev("shot", A, "miss", reb=A, pt="putback")         # A misses, A OREB (continues)
e10 = ev("shot", A, "make", pt="putback")               # A scores (same possession)
evs = [e1, e2, e3, e4, e5, e6, e7, e8, e9, e10]

SIT.annotate_after(evs, A)

# transition (our offense, keyed on opponent's last possession)
ok(e3["_after"]["trans"] == "score", "A offense after opp SCORE tagged")
ok(e5["_after"]["trans"] == "miss", "A offense after defensive REBOUND tagged")
ok(e7["_after"]["trans"] == "tov", "A offense after TAKEAWAY tagged")
# hot-hand (our offense, keyed on our own last offensive possession)
ok(e3["_after"]["hot"] == "score", "hot-hand: after we score tagged")
ok(e5["_after"]["hot"] == "miss", "hot-hand: after we miss tagged")
ok(e7["_after"]["hot"] == "tov", "hot-hand: after we turn it over tagged")
# defense (our defense, keyed on what we just did)
ok(e2["_after"]["def"] == "score", "D after we score tagged")
ok(e4["_after"]["def"] == "miss", "D after we miss tagged")
ok(e6["_after"]["def"] == "tov", "D after our turnover tagged")
# first possession of the game has no prior -> no bucket
ok(e1["_after"]["trans"] is None and e1["_after"]["hot"] is None,
   "first possession has no prior-outcome bucket")

# OFFENSIVE REBOUND does NOT start a new possession: the OREB miss and the make
# that follows it share ONE possession tag, drawn from the possession BEFORE the
# trip (opp's make at e8 -> 'score'), NOT from the miss itself.
ok(e9["_after"] is e10["_after"], "OREB miss + make share one possession tag")
ok(e9["_after"]["trans"] == "score" and e9["_after"]["hot"] == "score",
   "OREB trip keeps the prior possession's bucket (not 'miss' from its own miss)")

# ── team_after_outcome aggregate ─────────────────────────────────────────────
res = SIT.team_after_outcome(A, evs)
ok(res is not None, "team_after_outcome returns a result")
for fam in ("transition", "hot_hand", "defense"):
    keys = {r["key"] for r in res[fam]}
    ok(keys == {"score", "miss", "tov"}, f"{fam} has all 3 buckets")
# defense bucket carries PPP-ALLOWED (dPPP), offense buckets carry PPP
ok(all("dPPP" in r for r in res["defense"]), "defense buckets expose dPPP (allowed)")
ok(all("PPP" in r for r in res["transition"]), "transition buckets expose PPP")
# transition 'tov' bucket = the takeaway trip (e7 make) -> perfect PPP on 1 poss
_tk = next(r for r in res["transition"] if r["key"] == "tov")
ok(_tk["poss"] == 1 and abs(_tk["PPP"] - 2.0) < 1e-9,
   "takeaway bucket: 1 poss, 2 PPP (the e7 make)")

# ── per-game reset: game 2's first A possession must not inherit game 1 ───────
_clock[0] = 480
g2 = [ev("shot", A, "make", pt="iso", gid=2),          # A scores (first poss g2)
      ev("shot", B, "make", dfn="man", gid=2),          # B scores
      ev("shot", A, "make", pt="iso", gid=2)]           # A scores again
multi = evs + g2
SIT.annotate_after(multi, A)
ok(g2[0]["_after"]["trans"] is None,
   "game 2's first possession has no carryover bucket from game 1")
ok(g2[2]["_after"]["trans"] == "score",
   "game 2 second A possession tags 'after opp scores' within its own game")

# ── team_insights after_extra + generators ───────────────────────────────────
import helpers.team_insights as TIN  # noqa: E402

# a bigger sample so a bucket clears the generator gate: A pushes fast after a
# defensive rebound (many quick makes) but grinds after opponent scores.
_clock[0] = 480
bulk = []
for i in range(30):
    # opp scores, then A grinds (2-pt make, slow)
    bulk.append(ev("shot", B, "make", gid=5))
    bulk.append(ev("shot", A, "make", stp=2, secs=18, pt="iso", gid=5))
    # A forces a miss (opp miss, A rebounds), then A pushes (3-pt make, fast)
    bulk.append(ev("shot", B, "miss", reb=A, gid=5))
    bulk.append(ev("shot", A, "make", stp=3, secs=5, pt="transition", gid=5))
ext = TIN.after_extra(A, events=bulk)
ok("after" in ext and ext["after"] is not None, "after_extra builds the feed")

d = {"after": ext["after"]}
fired = []
for gen in (TIN._t_after_push, TIN._t_after_cold, TIN._t_after_scramble):
    c = gen(A, {}, {}, {}, d)
    ok(c is None or ("text" in c and "score" in c),
       f"{gen.__name__} returns None or a valid candidate")
    if c:
        fired.append(gen.__name__)
ok("_t_after_push" in fired,
   "_t_after_push fires on the push-after-rebound sample")

# thin data -> generators gate cleanly (no false headline)
thin = {"after": TIN.after_extra(A, events=evs)["after"]}
for gen in (TIN._t_after_push, TIN._t_after_cold, TIN._t_after_scramble):
    gen(A, {}, {}, {}, thin)  # must not raise

print(f"\nALL {PASS} CHECKS PASSED")
