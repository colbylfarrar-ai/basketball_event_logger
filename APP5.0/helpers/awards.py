"""
awards.py — the Hub's weekly awards digest (Tier 3 item 26b).

Composes three "of the week" honours from feeds that already exist — no new
stat math:
  * Player of the week — best week of Game Score (stats.game_score) across
    the anchor week's tracked games.
  * Game of the week   — highest raw GEI (win-probability excitement) among
    the week's tracked games; the Hub's game-of-the-SEASON pipeline, scoped
    to one week.
  * Riser of the week  — rating_history.risers top climb (daily snapshots;
    silently absent until two snapshot days exist).

"The week" anchors on the LATEST finished game date in the pool (not the
wall clock), so the strip stays meaningful in the offseason and on archives.

compose_awards() is pure (injectable rows) for the script test;
weekly_awards() is the thin DB assembly the page calls.
"""
from __future__ import annotations

import datetime
from collections import defaultdict

WEEK_DAYS = 7


def _week_window(dates):
    """(lo, hi) ISO dates — the 7-day window ending on the newest date."""
    good = sorted(d for d in dates if d)
    if not good:
        return None
    hi = good[-1]
    try:
        hid = datetime.date.fromisoformat(hi[:10])
    except ValueError:
        return None
    lo = (hid - datetime.timedelta(days=WEEK_DAYS - 1)).isoformat()
    return lo, hi[:10]


def compose_awards(games, boxes, meta, *, gei_fn=None, riser=None):
    """Pure composition.

    games: [{id, date, tracked, n1, n2, home_score, away_score}] finished pool
    boxes: {pid: {gid: box}} per-game boxes for TRACKED games (visibility
           pre-filtered by the caller)
    meta:  {pid: {name, number, team}}
    gei_fn: optional fn(game_row) -> float | None (game excitement)
    riser: optional (team_name, d_rank, d_rating) tuple from rating_history

    → {"window": (lo, hi), "player": {...}|None, "game": {...}|None,
       "riser": {...}|None} or None when there are no dated games at all."""
    win = _week_window([g.get("date") for g in games])
    if not win:
        return None
    lo, hi = win
    week = [g for g in games if g.get("date") and lo <= g["date"][:10] <= hi]
    week_ids = {g["id"] for g in week}

    # player of the week — best WEEK of Game Score (sum over window games)
    player = None
    from helpers.stats import game_score
    tally = defaultdict(lambda: {"gs": 0.0, "gp": 0, "pts": 0})
    for pid, per in boxes.items():
        if pid not in meta:
            continue
        for gid, b in per.items():
            if gid in week_ids:
                t = tally[pid]
                t["gs"] += game_score(b)
                t["gp"] += 1
                t["pts"] += b.get("PTS", 0) or 0
    if tally:
        pid, t = max(tally.items(), key=lambda kv: kv[1]["gs"])
        if t["gs"] > 0:
            m = meta[pid]
            player = {"pid": pid, "name": m.get("name", pid),
                      "number": m.get("number"), "team": m.get("team", ""),
                      "gs": round(t["gs"], 1), "gp": t["gp"], "pts": t["pts"]}

    # game of the week — most exciting tracked game in the window
    game = None
    if gei_fn is not None:
        best, best_gei = None, 0.0
        for g in week:
            if not g.get("tracked"):
                continue
            try:
                gei = gei_fn(g)
            except Exception:
                gei = None
            if gei is not None and gei > best_gei:
                best, best_gei = g, gei
        if best is not None:
            game = {"gid": best["id"], "date": best["date"],
                    "matchup": f'{best["n1"]} vs {best["n2"]}',
                    "score": f'{best["home_score"]}-{best["away_score"]}',
                    "gei": round(best_gei, 1)}

    riser_out = None
    if riser:
        riser_out = {"team": riser[0], "d_rank": riser[1],
                     "d_rating": riser[2]}

    return {"window": (lo, hi), "player": player, "game": game,
            "riser": riser_out}


def weekly_awards(gender, season="Current", game_ids=None):
    """DB assembly for the Hub. `game_ids` = tracked-visibility filter
    (None = unrestricted). Every piece degrades to None on its own."""
    from database.db import query
    import helpers.stats as S
    import helpers.seasons as SEAS

    rows = query(
        """SELECT g.id, g.date, g.tracked, g.home_score, g.away_score,
                  g.team1_id, g.team2_id, t1.name AS n1, t2.name AS n2
           FROM games g JOIN teams t1 ON t1.id=g.team1_id
                        JOIN teams t2 ON t2.id=g.team2_id
           WHERE t1.gender=? AND g.season=? AND g.home_score IS NOT NULL""",
        (gender, SEAS.ACTIVE if season in (None, "Current") else season))
    games = [dict(r) for r in rows]
    if not games:
        return None

    win = _week_window([g["date"] for g in games])
    lo, hi = win if win else ("", "")
    week_tracked = [g["id"] for g in games
                    if g["tracked"] and g["date"] and lo <= g["date"][:10] <= hi
                    and (game_ids is None or g["id"] in set(game_ids))]

    boxes = S.player_game_boxes(game_ids=week_tracked) if week_tracked else {}
    meta = {r["id"]: dict(r) for r in query(
        """SELECT p.id, p.name, p.number, t.name AS team
           FROM players p JOIN teams t ON t.id=p.team_id WHERE t.gender=?""",
        (gender,))}

    ev_by = defaultdict(list)
    if week_tracked:
        for e in S.fetch_events(week_tracked):
            ev_by[e["game_id"]].append(e)

    def _gei(g):
        """Raw GEI from the scoring timeline — the box-score/Hub pipeline."""
        import helpers.win_probability as WP
        import helpers.gameflow as GF
        scoring = [e for e in ev_by.get(g["id"], [])
                   if e["event_type"] in ("shot", "free_throw")
                   and e.get("shot_result") == "make"]
        if len(scoring) < 4:
            return None
        scoring.sort(key=GF.elapsed)
        times, margins, h, a = [0.0], [0], 0, 0
        for e in scoring:
            pts = e["shot_type"] if e["event_type"] == "shot" else 1
            if e["shooter_team_id"] == g["team1_id"]:
                h += pts
            elif e["shooter_team_id"] == g["team2_id"]:
                a += pts
            times.append(GF.elapsed(e))
            margins.append(h - a)
        end_t = times[-1] or WP.GAME_SECONDS
        curve = WP.wp_curve(list(zip(times, margins)), total_secs=end_t)
        if len(curve) < 2:
            return None
        return WP.summarize(curve)["gei"]

    riser = None
    try:
        import helpers.rating_history as RH
        ups = RH.risers(gender, system="score",
                        season=(season if season not in (None, "Current")
                                else SEAS.ACTIVE), days=7, top=1)
        if ups:
            tid, m = ups[0]
            nm = {r["id"]: r["name"]
                  for r in query("SELECT id, name FROM teams")}.get(tid, f"#{tid}")
            riser = (nm, m["d_rank"], m["d_rating"])
    except Exception:
        riser = None

    return compose_awards(games, boxes, meta, gei_fn=_gei, riser=riser)
