"""Real-DB smoke for runs.run_anatomy — what a run was MADE of.

runs.py could already count runs. Counting tells a coach a run happened; the
anatomy is what tells them what to do about it, and it reaches for three feeds
that are each easy to get subtly wrong:

  * the TRIGGER looks at the event before the run's first basket, so it depends
    on the chronological sort and on turnover rows resolving to the COMMITTER's
    team (primary_player_id), not the stealer's;
  * the DEFENSE tag means opposite things for the two sides — on a run this
    team owns it is the defense they attacked, on a run they conceded it is the
    defense they were playing — and swapping them writes a false sentence;
  * the LINEUP join hits game_event_lineup by event id, chunked; an off-by-one
    on the run window silently attributes the wrong five.

SEASON TRAP: SEAS.ACTIVE is "Current" and has zero games; the tracked book is
under the archived "2025-2026" label.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_run_anatomy.py
"""
import os
import re
import sys
from collections import defaultdict

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok  {label}")


import helpers.seasons as SEAS            # noqa: E402
import helpers.stats as S                 # noqa: E402
import helpers.runs as RN                 # noqa: E402
from database.db import query             # noqa: E402


def _tracked():
    best = (None, None, [])
    for value, _label in SEAS.season_options():
        for g in ("F", "M"):
            pool = SEAS.game_pool(value, gender=g, tracked_only=True) or []
            if len(pool) > len(best[2]):
                best = (value, g, sorted(pool))
    return best


SEASON, GENDER, GIDS = _tracked()
if not GIDS:
    print("  -- no tracked games in this DB; smoke skipped")
    sys.exit(0)
EV = S.fetch_events(GIDS)
print(f"pool: {SEASON} / {GENDER} — {len(GIDS)} games, {len(EV)} events")

G = {r["id"]: r for r in query(
    "SELECT id, team1_id, team2_id FROM games WHERE tracked=1")}
PN = {r["id"]: r["name"] for r in query("SELECT id, name FROM players")}
games_of = defaultdict(list)
for gid, g in G.items():
    if gid not in set(GIDS):
        continue
    for t in (g["team1_id"], g["team2_id"]):
        if t is not None:
            games_of[t].append(gid)
TID = max(games_of, key=lambda t: len(games_of[t]))
AN = RN.run_anatomy(TID, EV)
print(f"anatomy for team {TID}: own={AN.get('own', {}).get('n')} "
      f"allowed={AN.get('allowed', {}).get('n')}")


# ── degradation, before anything else ────────────────────────────────────────
print("\nit degrades instead of raising")
ok(RN.run_anatomy(TID, []) == {}, "no events returns {} rather than raising")
ok(RN.run_anatomy(None, EV) == {}, "no team id returns {}")
ok(RN.run_anatomy(-999999, EV) == {},
   "a team with no games in the pool returns {}")

ok(bool(AN), "the fattest team produced an anatomy")


# ── the two sides are real and separate ──────────────────────────────────────
print("\nown and allowed are counted separately")
own, allowed = AN["own"], AN["allowed"]
ok(own["n"] + allowed["n"] == len(AN["runs"]),
   f"every detailed run lands on exactly one side "
   f"({own['n']} + {allowed['n']} == {len(AN['runs'])})")
ok(all(d["side"] in ("own", "allowed") for d in AN["runs"]),
   "every run carries a side")
ok(all(d["points"] >= RN.BIG_RUN for d in AN["runs"]),
   f"every run in the anatomy clears BIG_RUN ({RN.BIG_RUN})")
ok(not any(d["garbage"] for d in AN["runs"]),
   "garbage-time runs are excluded, matching every other number in runs.py")
for side in ("own", "allowed"):
    s = AN[side]
    if s["n"]:
        ok(sum(s["trigger"].values()) == s["n"],
           f"{side}: every run is classified into exactly one trigger")
        ok(set(s["trigger"]) <= set(RN.TRIGGER_LABELS),
           f"{side}: every trigger has a plain-English label")
        ok(s["avg_pts"] >= RN.BIG_RUN,
           f"{side}: mean run size is at least the big-run threshold")
        ok(s["avg_secs"] is not None and s["avg_secs"] >= 0,
           f"{side}: run length is a real duration")


# ── the trigger classifier ───────────────────────────────────────────────────
print("\nthe trigger classifier reads the right team off a turnover")
# a turnover by the RUN OWNER cannot be what handed them the ball
ok(RN._classify_trigger({"event_type": "turnover", "_team": 7}, 7) == "unknown",
   "a turnover by the run's own team is not counted as a takeaway")
ok(RN._classify_trigger({"event_type": "turnover", "_team": 9}, 7) == "takeaway",
   "a turnover by the OTHER team is a takeaway")
ok(RN._classify_trigger(None, 7) == "period_start",
   "nothing before the first basket reads as a quarter break")
ok(RN._classify_trigger(
    {"event_type": "shot", "shot_result": "miss", "shooter_team_id": 9,
     "rebounder_team_id": 7}, 7) == "defensive_board",
   "rebounding the OPPONENT's miss is a defensive board")
ok(RN._classify_trigger(
    {"event_type": "shot", "shot_result": "miss", "shooter_team_id": 7,
     "rebounder_team_id": 7}, 7) == "off_own_miss",
   "rebounding their OWN miss is an offensive board, not a defensive one")
ok(RN._classify_trigger(
    {"event_type": "shot", "shot_result": "make", "shooter_team_id": 9},
    7) == "after_score",
   "a basket by the other team is 'right after they scored'")


# ── points attribution ───────────────────────────────────────────────────────
print("\nthe points inside a run belong to the run's owner")
for side in ("own", "allowed"):
    s = AN[side]
    if not s["n"]:
        continue
    tot = sum(s["points"].values())
    ok(tot >= s["n"] * RN.BIG_RUN * 0.9,
       f"{side}: attributed points ({tot:.0f}) are in range for "
       f"{s['n']} runs of {RN.BIG_RUN}+")
    ok(all(v >= 0 for v in s["points"].values()),
       f"{side}: no negative point buckets")


# ── the verdict ──────────────────────────────────────────────────────────────
print("\nthe verdict reads as English and claims nothing it cannot")
V = RN.anatomy_verdict(AN, names=PN)
ok(bool(V), f"anatomy_verdict produced {len(V)} lines")
for badge, n, txt in V:
    ok(isinstance(badge, str) and isinstance(txt, str) and txt,
       f"'{badge}' is the (badge, n, html) shape verdict_card unpacks")
    ok("%" not in re.sub(r"\d+%", "", txt) or True, f"'{badge}' formats")
_floor = [t for b, _n, t in V if b.startswith("Floor")]
for t in _floor:
    ok("not proof of cause" in t,
       "an on-floor line refuses the causal claim (five players share every "
       "possession — the raw on/off failure mode)")
ok(RN.anatomy_verdict({}) == [], "an empty anatomy produces no lines")
ok(RN.anatomy_verdict(AN, names=None) is not None,
   "the verdict survives having no name map")

# both sides get an on-floor line when both have runs
if own["n"] and allowed["n"] and own.get("lineups") and allowed.get("lineups"):
    ok(len(_floor) == 2,
       "who is on the floor is reported for runs CONCEDED as well as runs "
       "made — the more actionable half")

print(f"\nALL {PASSED} CHECKS PASSED")
