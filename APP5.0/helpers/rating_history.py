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
#: Games played before a team's row is STORED. The rating is still solved over
#: the whole board -- so a stored team's rank is its true rank among everyone --
#: this only decides who is worth keeping a history for. A 2-game rating is not
#: a trajectory, it is the sample arriving, and on the live book 704 of the 725
#: teams in the girls' pool are in that state for most of the season. Storing
#: them all cost 1.4 MB per gender for rows no surface would ever read, against
#: a standing constraint that this database stays small.
#:
#: Applied on BOTH paths, live and backfilled, deliberately: if the two
#: disagreed about who is in the table, `movement` would report teams appearing
#: and vanishing from the board across the boundary between reconstructed and
#: accrued history.
MIN_SNAPSHOT_GP = 5


def snapshot_board(gender, boards, season=SEAS.ACTIVE, day=None,
                   min_gp=MIN_SNAPSHOT_GP) -> int:
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
            # A MISSING GP means "unknown", not "zero". Treating absence as 0
            # would make any caller whose board rows lack the key stop
            # recording history entirely and silently — the failure would look
            # like the feature was never switched on. Only a GP that is present
            # AND below the floor drops the row.
            _gp = r.get("GP")
            if min_gp and _gp is not None and _gp < min_gp:
                continue
            rows.append((day, gender, system, int(tid), lbl,
                         float(r.get("Rating") or 0.0), int(r["Rank"])))
    if not rows:
        return 0
    return executemany(
        "INSERT OR IGNORE INTO rating_snapshots "
        "(day, gender, system, team_id, season, rating, rank) "
        "VALUES (?,?,?,?,?,?,?)", rows)


# ── retroactive backfill ───────────────────────────────────────────────────────
#: Cadence of reconstructed history. Weekly, not daily: a HS team plays one or
#: two games a week, so a daily grid would be mostly duplicate rows carrying no
#: new information, and each distinct day costs two full rating solves.
BACKFILL_STRIDE_DAYS = 7

#: Below this many finished games a board is not worth a row — early-season
#: ratings over three games are noise, and writing them would put a "Power
#: 50.0 -> 71.2" jump in the feed that is an artifact of the sample filling in
#: rather than anything a team did.
BACKFILL_MIN_GAMES = 8


def backfill_weekly(gender, season=SEAS.ACTIVE, systems=SYSTEMS,
                    stride=BACKFILL_STRIDE_DAYS, min_games=BACKFILL_MIN_GAMES,
                    progress=None) -> dict:
    """Reconstruct weekly snapshots for a season that has already been played.

    `rating_snapshots` was designed to accrue forward from the first deploy, so
    on a season that is already over it holds nothing and every trajectory read
    -- the news feed's Power deltas, risers, the rank line -- is empty until
    someone accumulates a year of history. But the ratings are a pure function
    of the games that had been played at the time, and both engines already
    accept a `game_ids` filter, so the history is RECOVERABLE: solve each board
    over the games finished on or before each week's end, and stamp it with
    that date.

    This is not an estimate of what the board would have said. It is what the
    board WOULD say, from the same engine, over exactly the games that existed.
    The one honest caveat is that it uses today's model constants rather than
    whatever was adopted at the time, so a recal makes reconstructed history
    disagree with history that accrued live. Backfilled days are therefore
    worth regenerating after a recal, and are safe to: the write is
    INSERT OR IGNORE per (day, gender, system, team_id), so re-running is a
    no-op rather than a duplicate.

    Returns {"days": n, "rows": n, "skipped": n, "from": day, "to": day}.
    """
    import helpers.team_ratings as TR
    lbl = _season_label(season)
    rows = query(
        """SELECT g.id, g.date FROM games g JOIN teams t ON t.id = g.team1_id
           WHERE g.season = ? AND t.gender = ? AND g.date IS NOT NULL
             AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
           ORDER BY g.date""", (lbl, gender))
    if not rows:
        return {"days": 0, "rows": 0, "skipped": 0, "from": None, "to": None}

    dated = [(str(r["date"])[:10], r["id"]) for r in rows if r["date"]]
    dated = [(d, i) for d, i in dated if len(d) == 10]
    if not dated:
        return {"days": 0, "rows": 0, "skipped": 0, "from": None, "to": None}

    first = _dt.date.fromisoformat(dated[0][0])
    last = _dt.date.fromisoformat(dated[-1][0])

    # Week ends, walking forward from the first game. The final day is always
    # included even when it does not land on the stride, so the reconstructed
    # series ends where the season actually ended rather than up to six days
    # short of it.
    marks, d = [], first + _dt.timedelta(days=stride - 1)
    while d < last:
        marks.append(d)
        d += _dt.timedelta(days=stride)
    marks.append(last)

    written = skipped = 0
    done = []
    for i, mark in enumerate(marks):
        iso = mark.isoformat()
        gids = [gid for gd, gid in dated if gd <= iso]
        if len(gids) < min_games:
            skipped += 1
            continue
        boards = {}
        for sysname in systems:
            fn = TR.score_ratings if sysname == "score" else TR.tracked_ratings
            try:
                boards[sysname] = fn(gender=gender, game_ids=gids, season=season)
            except Exception:
                # One unsolvable board (a tracked board before any game was
                # tracked) must not abandon the rest of the backfill.
                continue
        n = snapshot_board(gender, boards, season=season, day=iso)
        written += n
        done.append(iso)
        if progress:
            progress(i + 1, len(marks), iso, n)

    return {"days": len(done), "rows": written, "skipped": skipped,
            "from": done[0] if done else None,
            "to": done[-1] if done else None}


def has_history(gender, season=SEAS.ACTIVE, system="score", min_days=2) -> bool:
    """Enough snapshot days for any trajectory read to say something."""
    return len(snapshot_days(gender, system, season)) >= min_days


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
