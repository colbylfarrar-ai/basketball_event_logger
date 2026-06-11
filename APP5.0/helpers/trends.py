"""
trends.py — per-player game logs, rolling form, streaks and season highs.

Pure assembly over the existing per-game boxes (stats.player_game_boxes) joined to
the schedule — the game-by-game view the app computes but never surfaced. No new
tracking. Streamlit-free.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S

# Stats we track season highs / streaks on.
HIGH_KEYS = [("PTS", "Points"), ("TRB", "Rebounds"), ("AST", "Assists"),
             ("STL", "Steals"), ("BLK", "Blocks"), ("3PM", "Threes")]


def player_game_log(player_id, boxes=None):
    """
    Ordered game log for one player: [{game_id, date, opp, home, box}], oldest
    first, over every tracked game the player has a box for.

    `boxes` = a cached stats.player_game_boxes() result ({pid:{gid:box}}); fetched
    if omitted.
    """
    if boxes is None:
        boxes = S.player_game_boxes()
    games = boxes.get(player_id, {})
    if not games:
        return []
    prow = query("SELECT team_id FROM players WHERE id = ?", (player_id,))
    if not prow:
        return []
    pteam = prow[0]["team_id"]
    meta = {r["id"]: r for r in query(
        """SELECT g.id, g.date, g.team1_id, g.team2_id,
                  t1.name n1, t2.name n2
           FROM games g JOIN teams t1 ON t1.id = g.team1_id
                        JOIN teams t2 ON t2.id = g.team2_id""")}
    out = []
    for gid, box in games.items():
        m = meta.get(gid)
        if not m:
            continue
        is_home = m["team1_id"] == pteam
        out.append({"game_id": gid, "date": m["date"],
                    "opp": m["n2"] if is_home else m["n1"],
                    "home": is_home, "box": box})
    out.sort(key=lambda r: (r["date"] or "", r["game_id"]))
    return out


def rolling(values, window=3):
    """Trailing moving average (same length as input; ramps over the first rows)."""
    out = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        seg = values[lo:i + 1]
        out.append(sum(seg) / len(seg) if seg else 0.0)
    return out


def season_highs(log):
    """{key: {'value','date','opp'}} — the best single game for each HIGH_KEYS stat."""
    highs = {}
    for key, _label in HIGH_KEYS:
        best = None
        for g in log:
            v = g["box"].get(key, 0) or 0
            if best is None or v > best["value"]:
                best = {"value": v, "date": g["date"], "opp": g["opp"]}
        if best:
            highs[key] = best
    return highs


def streaks(log, threshold=10, key="PTS"):
    """
    Scoring (or any-stat) consistency streak: {'current','longest'} games in a row
    at/above `threshold` for `key` (default double-figure scoring).
    """
    cur = longest = 0
    for g in log:
        if (g["box"].get(key, 0) or 0) >= threshold:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return {"current": cur, "longest": longest}


def league_notables(boxes=None, table=None):
    """
    League-wide notable feats for the landing page, in one cheap in-memory pass
    over the per-game boxes: top active double-figure scoring streaks, most
    double-doubles, and the biggest single-game scoring lines.

    `table` (a player_stat_table) restricts to one gender's players when given.
    Returns {'streaks': [(current, longest, label)], 'double_doubles':
    [(count, label)], 'highs': [(pts, label, date, opp)]}, each top-5.
    """
    if boxes is None:
        boxes = S.player_game_boxes()
    gmeta = {r["id"]: r for r in query(
        """SELECT g.id, g.date, g.team1_id, g.team2_id, t1.name n1, t2.name n2
           FROM games g JOIN teams t1 ON t1.id=g.team1_id
                        JOIN teams t2 ON t2.id=g.team2_id""")}
    pmeta = {r["id"]: r for r in query("SELECT id, name, team_id FROM players")}
    tname = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}
    allow = set(table.keys()) if table else None

    streaks_r, dd_r, high_r = [], [], []
    for pid, gmap in boxes.items():
        if allow is not None and pid not in allow:
            continue
        meta = pmeta.get(pid, {})
        team = meta.get("team_id")
        log = sorted(((gmeta.get(gid, {}).get("date", ""), gid, b)
                      for gid, b in gmap.items()))
        if not log:
            continue
        cur = longest = dd = hi = 0
        hi_date = hi_opp = ""
        for date, gid, b in log:
            pts = b.get("PTS", 0) or 0
            if pts >= 10:
                cur += 1
                longest = max(longest, cur)
            else:
                cur = 0
            if sum(1 for k in ("PTS", "TRB", "AST", "STL", "BLK")
                   if (b.get(k, 0) or 0) >= 10) >= 2:
                dd += 1
            if pts > hi:
                hi = pts
                gm = gmeta.get(gid, {})
                hi_opp = gm.get("n2") if gm.get("team1_id") == team else gm.get("n1")
                hi_date = date
        label = f"{meta.get('name', '?')} ({tname.get(team, '?')})"
        streaks_r.append((cur, longest, label))
        dd_r.append((dd, label))
        high_r.append((hi, label, hi_date, hi_opp or "?"))
    streaks_r.sort(key=lambda x: (-x[0], -x[1]))
    dd_r.sort(key=lambda x: -x[0])
    high_r.sort(key=lambda x: -x[0])
    return {"streaks": streaks_r[:5], "double_doubles": dd_r[:5], "highs": high_r[:5]}


def last_n_split(log, n=5, keys=("PTS", "TRB", "AST")):
    """{key: (last_n_avg, season_avg)} — recent form vs the whole season."""
    if not log:
        return {}
    recent = log[-n:]
    out = {}
    for k in keys:
        s_all = [g["box"].get(k, 0) or 0 for g in log]
        s_rec = [g["box"].get(k, 0) or 0 for g in recent]
        out[k] = (sum(s_rec) / len(s_rec) if s_rec else 0.0,
                  sum(s_all) / len(s_all) if s_all else 0.0)
    return out
