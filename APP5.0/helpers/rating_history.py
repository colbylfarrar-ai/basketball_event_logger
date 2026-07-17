"""
rating_history.py — daily rating/rank snapshots → rank trajectory.

The rating engines (helpers/team_ratings.py) recompute the whole board from
scratch on every score change, so the app never knew where a team WAS — no
"risers this week", no rank-over-time line. This module fixes that with the
cheapest possible mechanism: whenever the Rankings page computes a board for
the ACTIVE season, it INSERT OR IGNOREs one row per (team, system) for today
into `rating_snapshots`. No timer, no backfill — history simply accrues from
the first deploy, and every surface here degrades to "nothing to show" until
two distinct days exist.

Rows are stamped with the season's REAL label (SEAS.active_label(), never the
'Current' sentinel) so a New Season rollover can't blend trajectories.
Streamlit-free + pure reads; the one write is idempotent per day.
"""
from __future__ import annotations

import datetime as _dt

from database.db import query, executemany
import helpers.seasons as SEAS

#: rating systems snapshotted per day. 'score' = results-only power board
#: (TR.score_ratings); 'tracked' = possession-based board (TR.tracked_ratings).
SYSTEMS = ("score", "tracked")


def _today() -> str:
    return _dt.date.today().isoformat()


def _season_label(season) -> str:
    """Snapshots always store the REAL label — resolve the 'Current' sentinel."""
    return SEAS.active_label() if SEAS.is_current(season) else str(season)


# ── write path ─────────────────────────────────────────────────────────────────
def snapshot_board(gender, boards, season=SEAS.ACTIVE, day=None) -> int:
    """Record today's rating boards. `boards` = {system: {team_id: row}} where
    each row carries at least Rating + Rank (the score_ratings/tracked_ratings
    shape). INSERT OR IGNORE on the (day, gender, system, team_id) PK makes a
    second call the same day a no-op, so the caller can fire on every rerun.
    Returns rows actually written."""
    day = day or _today()
    lbl = _season_label(season)
    rows = []
    for system, board in (boards or {}).items():
        for tid, r in (board or {}).items():
            if r.get("Rank") is None:
                continue
            rows.append((day, gender, system, int(tid), lbl,
                         float(r.get("Rating") or 0.0), int(r["Rank"])))
    if not rows:
        return 0
    return executemany(
        "INSERT OR IGNORE INTO rating_snapshots "
        "(day, gender, system, team_id, season, rating, rank) "
        "VALUES (?,?,?,?,?,?,?)", rows)


# ── reads ──────────────────────────────────────────────────────────────────────
def snapshot_days(gender, system="score", season=SEAS.ACTIVE) -> list[str]:
    """Distinct snapshot days for a board, oldest first."""
    return [r["day"] for r in query(
        "SELECT DISTINCT day FROM rating_snapshots "
        "WHERE gender=? AND system=? AND season=? ORDER BY day",
        (gender, system, _season_label(season)))]


def movement(gender, system="score", season=SEAS.ACTIVE, days=7) -> dict:
    """Rank/rating movement per team: latest snapshot vs the most recent
    snapshot at least `days` old (falling back to the earliest available, so
    the read works from day 2 on). Returns {} until two days exist, else
    {team_id: {d_rank, d_rating, from_day, to_day}} — d_rank POSITIVE = the
    team CLIMBED that many spots (old rank 10 → new 7 → +3)."""
    ds = snapshot_days(gender, system, season)
    if len(ds) < 2:
        return {}
    latest = ds[-1]
    cutoff = (_dt.date.fromisoformat(latest)
              - _dt.timedelta(days=days)).isoformat()
    base = ds[0]
    for d in ds[:-1]:
        if d <= cutoff:
            base = d            # last day at/behind the window edge
    lbl = _season_label(season)

    def _board(day):
        return {r["team_id"]: r for r in query(
            "SELECT team_id, rating, rank FROM rating_snapshots "
            "WHERE day=? AND gender=? AND system=? AND season=?",
            (day, gender, system, lbl))}

    cur, old = _board(latest), _board(base)
    out = {}
    for tid, r in cur.items():
        o = old.get(tid)
        if not o:
            continue            # new to the board — no trajectory yet
        out[tid] = {"d_rank": o["rank"] - r["rank"],
                    "d_rating": round(r["rating"] - o["rating"], 2),
                    "from_day": base, "to_day": latest}
    return out


def team_series(team_id, gender, system="score", season=SEAS.ACTIVE) -> list[dict]:
    """One team's full trajectory, oldest first: [{day, rating, rank}, ...]."""
    return query(
        "SELECT day, rating, rank FROM rating_snapshots "
        "WHERE team_id=? AND gender=? AND system=? AND season=? ORDER BY day",
        (int(team_id), gender, system, _season_label(season)))


def risers(gender, system="score", season=SEAS.ACTIVE, days=7, top=3,
           min_move=1) -> list[tuple[int, dict]]:
    """Biggest rank climbs over the window: [(team_id, movement-row)], best
    first, movers only (|d_rank| >= min_move as a climb)."""
    mv = movement(gender, system=system, season=season, days=days)
    ups = [(t, m) for t, m in mv.items() if m["d_rank"] >= min_move]
    ups.sort(key=lambda tm: (-tm[1]["d_rank"], -tm[1]["d_rating"]))
    return ups[:top]


def arrow(d_rank) -> str:
    """Compact movement chip for tables: ▲3 / ▼2 / — (None → '')."""
    if d_rank is None:
        return ""
    d = int(d_rank)
    if d > 0:
        return f"▲{d}"
    if d < 0:
        return f"▼{-d}"
    return "—"
