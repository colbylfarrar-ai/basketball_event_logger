"""news_feed.py — the season as a reverse-chronological story.

The most OOTP thing the app can show, and every input already existed: games
carry dates and scores, `rating_snapshots` carries the Power trajectory,
`postgame` generates a game report, `awards` names the standouts. What was
missing was a spine to hang them on and, more importantly, any HISTORY to
compute movement from -- the snapshot table was designed to accrue forward from
first deploy and had 0 rows, so on a season already played the entire feature
was empty. `rating_history.backfill_weekly` reconstructs it; this module reads
the result.

HOW THE POWER DELTA IS ATTACHED, AND WHY NOT TO A GAME
-----------------------------------------------------
The obvious feed line is "W 58-51 vs Kansas -- Power 66.9 -> 68.2 (+1.3)",
crediting one game with one rating move. Reconstructed history cannot honestly
support that: snapshots are WEEKLY, because a HS team plays once or twice a
week and a daily grid would be duplicate rows at two full rating solves each.
A week containing two games has one delta between them, and splitting it
across the games would be inventing precision the cadence does not have.

So movement is its own item, attached to the WEEK, sitting in the timeline
beside the games that caused it. A coach reads "these two results, and the
board moved this much" -- which is the true statement -- instead of a
per-game attribution that would be a guess wearing a decimal point.

When history accrues live at daily cadence this same code produces per-day
items automatically, and the delta narrows to the games it actually covers.
Nothing here needs changing when that happens; the items just get finer.

Everything degrades to "fewer item types", never to a wrong number: with no
snapshots there are no movement items and the game log still reads.

Streamlit-free.
"""
from __future__ import annotations

import datetime as _dt

from database.db import query
import helpers.rating_history as RH
import helpers.seasons as SEAS

#: Item kinds, in the order they sort within one day (a result outranks the
#: board move it caused).
KINDS = ("result", "movement", "award", "note")


def _season_label(season):
    return SEAS.active_label() if SEAS.is_current(season) else str(season)


def team_games(team_id, season=SEAS.ACTIVE, limit=None):
    """This team's finished games, newest first, with the opponent resolved."""
    rows = query(
        """SELECT g.id, g.date, g.team1_id, g.team2_id, g.home_score,
                  g.away_score, g.tracked, g.neutral, g.location,
                  t1.name AS n1, t2.name AS n2
           FROM games g
           JOIN teams t1 ON t1.id = g.team1_id
           JOIN teams t2 ON t2.id = g.team2_id
           WHERE g.season = ? AND (g.team1_id = ? OR g.team2_id = ?)
             AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
           ORDER BY g.date DESC, g.id DESC""",
        (_season_label(season), int(team_id), int(team_id)))
    out = []
    for r in rows:
        home = r["team1_id"] == int(team_id)
        us = r["home_score"] if home else r["away_score"]
        them = r["away_score"] if home else r["home_score"]
        out.append({
            "game_id": r["id"], "date": str(r["date"])[:10],
            "opp_id": r["team2_id"] if home else r["team1_id"],
            "opp": r["n2"] if home else r["n1"],
            "us": us, "them": them,
            "win": us > them, "margin": us - them,
            "home": home, "neutral": bool(r["neutral"]),
            "tracked": bool(r["tracked"]),
        })
    return out[:limit] if limit else out


def _movement_items(team_id, gender, season, system="score"):
    """One item per snapshot interval in which this team's board actually moved.

    Reads the reconstructed (or accrued) series and diffs consecutive days.
    Emits nothing at all when there are fewer than two days, which is the
    honest state before a backfill has been run.
    """
    series = RH.team_series(team_id, gender, system=system, season=season)
    items = []
    for prev, cur in zip(series, series[1:]):
        d_rating = (cur["rating"] or 0) - (prev["rating"] or 0)
        d_rank = (prev["rank"] or 0) - (cur["rank"] or 0)
        if abs(d_rating) < 0.005 and d_rank == 0:
            continue        # the board did not move; not news
        items.append({
            "kind": "movement", "date": cur["day"], "from_day": prev["day"],
            "rating": cur["rating"], "prev_rating": prev["rating"],
            "d_rating": d_rating, "rank": cur["rank"], "prev_rank": prev["rank"],
            "d_rank": d_rank, "system": system,
        })
    return items


def _headline(g):
    """The result line a coach would say out loud."""
    where = "vs" if g["home"] else ("@" if not g["neutral"] else "vs")
    wl = "W" if g["win"] else "L"
    return f"{wl} {g['us']}-{g['them']} {where} {g['opp']}"


def _result_notes(g, *, big_win=15, close=3):
    """Short, always-true bullets. Nothing here needs a model or a gate."""
    notes = []
    m = abs(g["margin"])
    if g["win"] and m >= big_win:
        notes.append(f"Won by {m}")
    elif not g["win"] and m >= big_win:
        notes.append(f"Lost by {m}")
    elif m <= close:
        notes.append(f"Decided by {m}")
    if not g["tracked"]:
        notes.append("Not tracked — box score only")
    return notes


def feed(team_id, gender, season=SEAS.ACTIVE, limit=40, system="score",
         with_movement=True):
    """The team's season, newest first: [{kind, date, ...}].

    Every item carries `date` and `kind`; renderers switch on `kind` rather
    than parsing text, so a new item type is additive.
    """
    items = []
    for g in team_games(team_id, season=season):
        items.append({
            "kind": "result", "date": g["date"], "game_id": g["game_id"],
            "headline": _headline(g), "win": g["win"], "tracked": g["tracked"],
            "opp_id": g["opp_id"], "opp": g["opp"], "margin": g["margin"],
            "notes": _result_notes(g),
        })
    if with_movement:
        try:
            items.extend(_movement_items(team_id, gender, season, system))
        except Exception:
            pass        # no history is a missing section, never a broken page

    order = {k: i for i, k in enumerate(KINDS)}
    items.sort(key=lambda it: (it["date"], -order.get(it["kind"], 9)),
               reverse=True)
    return items[:limit] if limit else items


def movement_sentence(it):
    """A movement item as one coach-readable line."""
    d = it["d_rating"]
    verb = "up" if d > 0 else "down"
    s = (f"Power {it['prev_rating']:.1f} → {it['rating']:.1f} "
         f"({d:+.1f}) — {verb} the board")
    if it["d_rank"]:
        s += (f", {'+' if it['d_rank'] > 0 else ''}{it['d_rank']} "
              f"{'spot' if abs(it['d_rank']) == 1 else 'spots'} "
              f"to #{it['rank']}")
    else:
        s += f", holding #{it['rank']}"
    return s


def week_label(iso):
    """'Sat 2/14' — the compact date stamp the feed reads down the left."""
    try:
        d = _dt.date.fromisoformat(iso)
    except (ValueError, TypeError):
        return str(iso)
    return f"{d.strftime('%a')} {d.month}/{d.day}"


def summary(team_id, gender, season=SEAS.ACTIVE, system="score"):
    """Season-shape header for the feed: record, and the Power arc if known."""
    gs = team_games(team_id, season=season)
    w = sum(1 for g in gs if g["win"])
    out = {"games": len(gs), "wins": w, "losses": len(gs) - w,
           "tracked": sum(1 for g in gs if g["tracked"]),
           "first": gs[-1]["date"] if gs else None,
           "last": gs[0]["date"] if gs else None,
           "power_from": None, "power_to": None, "rank_from": None,
           "rank_to": None, "days": 0}
    try:
        series = RH.team_series(team_id, gender, system=system, season=season)
    except Exception:
        series = []
    if len(series) >= 2:
        out.update(power_from=series[0]["rating"], power_to=series[-1]["rating"],
                   rank_from=series[0]["rank"], rank_to=series[-1]["rank"],
                   days=len(series))
    return out
