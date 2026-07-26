"""Real-DB smoke for helpers/deserved.py — the four-term margin decomposition.

This engine's whole claim is an IDENTITY: every point of a game's final margin
lands in exactly one of volume / quality / making / free throws, and those four
add back to the scoreboard. If the identity ever breaks the surface starts
lying quietly — the numbers still render, they just stop summing — so it is
pinned here rather than trusted.

What only this catches:

  * the identity drifting (a term double-counted, or free throws leaking into
    the field-goal side);
  * the event book diverging from `games.home_score/away_score`, which would
    mean the decomposition explains a tracked approximation rather than the
    real result;
  * `team1_id` turning out not to be the home team on some future import path,
    which silently inverts every sign on the page;
  * `for_team` failing to flip a term, so the same game reads as a win for both
    sides;
  * a prose bug of the kind the build already hit twice — a margin-sized term
    quoted next to one team's own number, and a "the looks went one way and the
    ball went the other" sentence printed over a game where both pointed the
    same way.

SEASON TRAP: SEAS.ACTIVE is "Current" and has zero games; the tracked book is
under the archived "2025-2026" label.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_deserved.py
"""
import os
import re
import sys

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
import helpers.deserved as D              # noqa: E402
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

LED = D.game_ledgers(events=EV)
print(f"ledgers: {len(LED)} games decomposed")
ok(bool(LED), "game_ledgers produced rows off the real book")


# ── the guard every pooled engine in this codebase needs ─────────────────────
print("\nthe empty-pool guard")
ok(D.game_ledgers(game_ids=[]) == {},
   "an EMPTY game-id list means nothing, not the whole database")


# ── 1. the identity ──────────────────────────────────────────────────────────
print("\nthe four terms add up to the final margin")
worst = 0.0
for r in LED.values():
    s = r["volume"] + r["quality"] + r["making"] + r["ft_margin"]
    worst = max(worst, abs(s - r["margin"]))
ok(worst < 1e-6,
   f"volume + quality + making + free throws == final margin (max err {worst:.2e})")

# volume + quality is exactly the expected margin, which is what makes the
# "possession vs quality" split legible rather than a rearrangement
worst_x = max(abs(r["volume"] + r["quality"] - r["xmargin"])
              for r in LED.values())
ok(worst_x < 1e-6,
   f"volume + quality == expected margin (max err {worst_x:.2e})")


# ── 2. the event book vs the official scoreboard ─────────────────────────────
print("\nthe decomposition explains the REAL result")
G = {r["id"]: r for r in query(
    "SELECT id, home_score, away_score FROM games WHERE tracked=1")}
checked = mism = 0
for gid, r in LED.items():
    g = G.get(gid)
    if not g or g["home_score"] is None or g["away_score"] is None:
        continue
    checked += 1
    if abs((g["home_score"] - g["away_score"]) - r["margin"]) > 1e-6:
        mism += 1
ok(checked > 0, f"{checked} games carry an official score to check against")
ok(mism == 0,
   f"event-derived margin equals the official scoreboard margin "
   f"({checked - mism}/{checked}) — team1_id is the HOME team")


# ── 3. for_team flips every sign ─────────────────────────────────────────────
print("\nfor_team() re-orients without losing a term")
bad = 0
for r in LED.values():
    h = D.for_team(r, r["home_id"])
    a = D.for_team(r, r["away_id"])
    for k in ("margin", "xmargin", "volume", "quality", "making", "ft_margin"):
        if abs(h[k] + a[k]) > 1e-9:
            bad += 1
ok(bad == 0, "home and away terms are exact negatives of each other")
_any = next(iter(LED.values()))
ok(D.for_team(_any, -999999) is None,
   "a team that did not play in the game returns None, not a zeroed row")
_h = D.for_team(_any, _any["home_id"])
ok(_h["won"] == (_h["margin"] > 0), "won flag agrees with the signed margin")
ok(_h["fga_gap"] == _h["fga"] - _h["opp_fga"], "the attempt gap is self-consistent")


# ── 4. the team roll-up ──────────────────────────────────────────────────────
print("\nteam_deserved rolls a season up")
from collections import defaultdict          # noqa: E402
cnt = defaultdict(int)
for r in LED.values():
    cnt[r["home_id"]] += 1
    cnt[r["away_id"]] += 1
TID = max(cnt, key=cnt.get)
d = D.team_deserved(TID, ledgers=LED)
ok(d["available"] and d["games"] >= 3,
   f"the fattest team has {d['games']} decomposed games")
ok(d["games"] == cnt[TID], "every one of the team's games is in the roll-up")
ok(abs(sum(d["means"][k] for k in
           ("volume", "quality", "making", "ft_margin"))
       - d["means"]["margin"]) < 1e-6,
   "the identity survives the season average")
ok(d["decided"] <= d["games"], "decided games never exceed games played")
ok(0 <= d["agree"] <= d["decided"], "agreement count is inside its own range")
ok(len(d["ranked_terms"]) == 4, "all four terms are ranked, none dropped")
_absmeans = [t[2] for t in d["ranked_terms"]]
ok(_absmeans == sorted(_absmeans, reverse=True),
   "ranked_terms is ordered by mean absolute influence, largest first")
ok(D.team_deserved(-999999, ledgers=LED)["available"] is False,
   "a team with no games degrades to available=False rather than raising")


# ── 5. the prose bugs this build actually hit ────────────────────────────────
print("\nthe verdict says only what the numbers support")
V = D.deserved_verdict(d)
ok(bool(V), f"deserved_verdict produced {len(V)} lines")
for badge, n, txt in V:
    ok(isinstance(badge, str) and isinstance(txt, str) and txt,
       f"'{badge}' is the (badge, n, html) shape verdict_card unpacks")

_dr = [t for b, _n, t in V if b == "Deserved result"]
if _dr:
    _txt = _dr[0]
    # An UPSET (the play favoured the other team) and a big GAP (same team
    # ahead on both counts, by different amounts) are different claims. The
    # copy must not describe one as the other.
    _claims_flip = "Widest miss" in _txt
    _claims_none = "No result went against the play" in _txt
    ok(_claims_flip == (d["biggest_upset"] is not None),
       "'Widest miss' is claimed ONLY when a game's play genuinely pointed at "
       "the other team — a sign disagreement, not just a big gap")
    ok(_claims_none == (d["biggest_upset"] is None),
       "with no upset on the book the copy says so outright rather than "
       "dressing the widest gap up as one")
    ok("does not forecast" in _txt,
       "the descriptive-only disclaimer is present (reliability.py refuses the "
       "forecast)")
if d["biggest_upset"] is not None:
    u = d["biggest_upset"]
    ok((u["margin"] > 0) != (u["xmargin"] > 0),
       "biggest_upset really is a sign disagreement")

# a margin-sized term must never be quoted beside one side's number alone
print("\ngame_story quotes BOTH sides of every margin term")
_story = D.game_story(d["biggest_gap"])
ok(bool(_story), f"game_story produced {len(_story)} terms")
for lbl, pts, txt in _story:
    ok(abs(pts) >= 0.5, f"'{lbl}' clears the materiality floor")
_make = [t for lbl, _p, t in _story if lbl == "Shot-making"]
if _make:
    _plain = re.sub(r"<[^>]+>", "", _make[0])
    _nums = [float(x) for x in re.findall(r"\(([+-]\d+(?:\.\d+)?)\)", _plain)]
    ok(len(_nums) == 2,
       "the shot-making sentence shows this team's over/under AND the "
       "opponent's, so the reader can reconcile it with the margin")
    _mp = [p for lbl, p, _t in _story if lbl == "Shot-making"][0]
    # making = us_make MINUS them_make. Both sides push the margin the same
    # way, so a reader who ADDS them gets a wrong (often opposite) number —
    # the sentence must state the netting rather than leave it implied.
    ok(abs((_nums[0] - _nums[1]) - _mp) < 0.2,
       f"the term is this team's over-performance MINUS the opponent's "
       f"({_nums} -> {_nums[0] - _nums[1]:+.1f} vs {_mp:+.1f})")
    # the clause must MATCH the two signs, not be asserted unconditionally
    _reinforce = (_nums[0] > 0) != (_nums[1] > 0)
    ok(("rather than cancelling" in _plain) == _reinforce,
       "the 'both push the same way' clause is claimed only when the two "
       "sides actually reinforce (one above its looks, one below)")
    ok(("partly offset" in _plain) == (not _reinforce),
       "and the offsetting case says so instead")
_vol = [t for lbl, _p, t in _story if lbl == "Extra shots"]
if _vol:
    ok("ORB" in _vol[0] and "TOV" in _vol[0],
       "the volume sentence names its CAUSE — ORB and TOV, the r=0.98 "
       "reconstruction — rather than just its size")

# thin-sample behaviour: a 2-game team must not get a season verdict
_thin_team = min(cnt, key=cnt.get)
if cnt[_thin_team] < 3:
    ok(D.deserved_verdict(D.team_deserved(_thin_team, ledgers=LED)) == [],
       "a team under 3 decomposed games gets no verdict at all")

print(f"\nALL {PASSED} CHECKS PASSED")
