"""
fatigue.py — rest-days / schedule-density splits (score-based, engine-safe).

The game DATES were the last untouched capture: every game carries an ISO date,
so days-of-rest and week-density are free signals. Everything here is
score-based (works on the full schedule, no tracked events needed):

  rest_splits(rows)        one team's record + MOV bucketed by days since the
                           previous game (B2B / 2 / 3-4 / 5+), plus a
                           heavy-week split (3+ games in any trailing 7 days).
                           Deltas are vs the team's own overall MOV, so a bad
                           team isn't "fatigued" just for losing as usual.
  team_rest_splits(tid)    the same from the games table for one team.
  league_rest_edge(gender) the league-wide fatigue curve: game margin as a
                           function of the REST DIFFERENTIAL (my rest − their
                           rest, capped ±3). Pooled own-rest MOV means nothing
                           (both sides of every game cancel); the differential
                           is the real "who had the fresher legs" read.

Pure data layer (dates + arithmetic), no streamlit. First game of a season has
no previous game — it is excluded from rest buckets, not guessed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from database.db import query

# (bucket key, label, lo, hi) on days since the previous game (1 = played
# yesterday). HS weeks run Tue/Fri, so 3-4 days is the "normal" bucket.
REST_BUCKETS = (
    ("b2b", "Back-to-back (1 day)", 1, 1),
    ("short", "2 days", 2, 2),
    ("normal", "3-4 days", 3, 4),
    ("long", "5+ days", 5, 10 ** 6),
)
HEAVY_WINDOW, HEAVY_GAMES = 7, 3          # 3+ games inside any 7-day window


def _d(iso):
    """ISO date string -> date, or None if unparseable."""
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _bucket(rest):
    for key, label, lo, hi in REST_BUCKETS:
        if lo <= rest <= hi:
            return key
    return None


def rest_splits(rows):
    """Bucket one team's played games by rest.

    `rows` — [{date, margin, won}] in any order (extra keys ignored); margin is
    from the team's perspective. Returns None with < 3 dated games, else:
      {"overall_mov", "gp",
       "buckets": [{key,label,gp,w,l,mov,delta}],       (only non-empty)
       "heavy": {"gp","w","l","mov","delta"} | None,    (3+ in 7 days)
       "rest_of": {date_iso: rest_days}}                (for the edge join)
    """
    dated = sorted((r for r in rows if _d(r["date"])), key=lambda r: r["date"])
    if len(dated) < 3:
        return None
    overall = sum(r["margin"] for r in dated) / len(dated)

    agg = defaultdict(lambda: {"gp": 0, "w": 0, "l": 0, "mov": 0.0})
    heavy = {"gp": 0, "w": 0, "l": 0, "mov": 0.0}
    rest_of = {}
    days = [_d(r["date"]) for r in dated]
    for i, r in enumerate(dated):
        if i:
            rest = (days[i] - days[i - 1]).days
            rest_of[r["date"]] = rest
            key = _bucket(rest)
            if key:
                a = agg[key]
                a["gp"] += 1
                a["w"] += 1 if r["won"] else 0
                a["l"] += 0 if r["won"] else 1
                a["mov"] += r["margin"]
        # density: this game + the games in the 7 days before it
        in_window = sum(1 for dd in days if 0 <= (days[i] - dd).days
                        < HEAVY_WINDOW)
        if in_window >= HEAVY_GAMES:
            heavy["gp"] += 1
            heavy["w"] += 1 if r["won"] else 0
            heavy["l"] += 0 if r["won"] else 1
            heavy["mov"] += r["margin"]

    buckets = []
    for key, label, _lo, _hi in REST_BUCKETS:
        a = agg.get(key)
        if not a or not a["gp"]:
            continue
        mov = a["mov"] / a["gp"]
        buckets.append({"key": key, "label": label, "gp": a["gp"],
                        "w": a["w"], "l": a["l"],
                        "mov": round(mov, 1), "delta": round(mov - overall, 1)})
    hv = None
    if heavy["gp"]:
        hmov = heavy["mov"] / heavy["gp"]
        hv = {"gp": heavy["gp"], "w": heavy["w"], "l": heavy["l"],
              "mov": round(hmov, 1), "delta": round(hmov - overall, 1)}
    return {"overall_mov": round(overall, 1), "gp": len(dated),
            "buckets": buckets, "heavy": hv, "rest_of": rest_of}


def _team_games(gender=None):
    """{team_id: [{date, margin, won}]} for finished Current-season games."""
    sql = """SELECT g.date, g.team1_id t1, g.team2_id t2,
                    g.home_score hs, g.away_score aws
             FROM games g JOIN teams t ON t.id = g.team1_id
             WHERE g.season = 'Current'
               AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL"""
    params: tuple = ()
    if gender:
        sql += " AND t.gender = ?"
        params = (gender,)
    per = defaultdict(list)
    for g in query(sql, params):
        m = g["hs"] - g["aws"]
        per[g["t1"]].append({"date": g["date"], "margin": m, "won": m > 0})
        per[g["t2"]].append({"date": g["date"], "margin": -m, "won": m < 0})
    return per


def team_rest_splits(team_id):
    """rest_splits() for one team straight from the games table."""
    rows = _team_games().get(team_id, [])
    return rest_splits(rows)


def league_rest_edge(gender=None, min_gp=5):
    """League fatigue curve: average game margin by REST DIFFERENTIAL.

    For every game where both teams have a known previous game, diff =
    team1_rest − team2_rest capped to ±3; margin is team1's. Symmetric by
    construction (each game enters once; a +2 win for the rested side IS the
    −2 loss for the tired side). Returns {diff: {"gp","mov"}} for diffs with
    `min_gp`+ games, or {} when the schedule is too thin.
    """
    per = _team_games(gender)
    rest_maps = {}
    for tid, rows in per.items():
        rs = rest_splits(rows)
        rest_maps[tid] = rs["rest_of"] if rs else {}

    sql = """SELECT g.date, g.team1_id t1, g.team2_id t2,
                    g.home_score hs, g.away_score aws
             FROM games g JOIN teams t ON t.id = g.team1_id
             WHERE g.season = 'Current'
               AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL"""
    params: tuple = ()
    if gender:
        sql += " AND t.gender = ?"
        params = (gender,)
    agg = defaultdict(lambda: {"gp": 0, "mov": 0.0})
    for g in query(sql, params):
        r1 = rest_maps.get(g["t1"], {}).get(g["date"])
        r2 = rest_maps.get(g["t2"], {}).get(g["date"])
        if r1 is None or r2 is None:
            continue
        diff = max(-3, min(3, r1 - r2))
        a = agg[diff]
        a["gp"] += 1
        a["mov"] += g["hs"] - g["aws"]
    return {d: {"gp": a["gp"], "mov": round(a["mov"] / a["gp"], 1)}
            for d, a in sorted(agg.items()) if a["gp"] >= min_gp}
