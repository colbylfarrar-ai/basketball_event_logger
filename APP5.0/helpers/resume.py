"""
resume.py — the point-in-time résumé: what the board said WHEN it mattered.

`rating_snapshots` has held a full weekly reconstruction of the season since
`rating_history.backfill_weekly` shipped, and until now nothing read it except
the three trajectory surfaces (risers, movement, the Overview rank line). This
module is the other half: not "where is this team trending", but "what was true
on the day this game was played".

Three surfaces sit on top of it, and all three are the same read:

  * the board AS OF any snapshot day (Rankings → the week picker)
  * the opponent's rank GOING INTO a game ("beat #6 Broken Bow")
  * quality wins counted AT THE TIME rather than against today's board

That last one is the reason the module exists. Every product that ships "wins
vs top-25" computes it against the CURRENT board, which is a different claim
from the one a coach is making. Measured on this book, rank movement from
2025-12-14 to 2026-03-14 has a median of 68 places, and only 11 of December's
top 25 were still top 25 in March — so 38 of 51 teams get a different quality-win
count depending on which board you ask. Beating Lincoln Christian on 2025-12-31
when they were #1 is a résumé line; beating them in March after they slid is a
different game, and today's board cannot tell the two apart.

Streamlit-free and pure reads (the house convention — the pages own the render).
Every read degrades to "no history yet" on an empty snapshot table rather than
raising, because a fresh book genuinely has no history and a coach who has never
pressed Rebuild must not meet a stack trace.

THE CAVEAT that has to reach the screen (see `CAVEAT`): backfilled boards are
solved with TODAY's model constants, not whatever was adopted at the time. That
is a deliberate, documented property of the reconstruction, not a bug — but it
means reconstructed history can disagree with history that accrued live, and
backfilled days are worth regenerating after a recal.

Scoped to the 'score' system on purpose. The 'tracked' board has 1-5 rows on a
given day on this book (few tracked games), which is not a ranking, and a
résumé built on a five-team board would be a worse lie than no résumé at all.
"""
from __future__ import annotations

from bisect import bisect_left

from database.db import query
import helpers.seasons as SEAS

#: The only system these surfaces run on. See the module docstring — 'tracked'
#: is too sparse per day to rank against.
SYSTEM = "score"

#: Default cutoff for "quality win". 25 is the number every coach and every
#: poll already speaks in, so it is the default rather than the top-25% cut the
#: existing `strength_of_schedule` uses; that one moves with the size of the
#: pool and is therefore not comparable across genders or seasons.
DEFAULT_TOP_N = 25

#: One string, rendered by every surface that shows reconstructed history, so
#: the caveat cannot drift between two pages that both make the same claim.
CAVEAT = (
    "Reconstructed boards are solved with **today's** model constants, not "
    "whatever was adopted at the time — so history rebuilt after a recal can "
    "disagree with history that accrued live. Backfilled days are worth "
    "regenerating after a recal (Rankings → 🕘 Rating history → Rebuild); the "
    "write never duplicates a day."
)


def _label(season) -> str:
    """The season label snapshots are actually STORED under.

    Two resolutions, in order, and both are load-bearing. `resolve_read_season`
    turns the DEFAULT sentinel into the season a read should scope to — without
    it a no-season caller would look up '__default__' and get a clean, silent,
    completely empty board. Then the 'Current' sentinel resolves to the real
    label, because `rating_history.snapshot_board` stamps rows with
    `SEAS.active_label()` so a rollover cannot blend two seasons' trajectories.
    """
    s = SEAS.resolve_read_season(season)
    return SEAS.active_label() if SEAS.is_current(s) else str(s)


# ── the boards ────────────────────────────────────────────────────────────────
def snapshot_days(gender, season=SEAS.DEFAULT, system=SYSTEM) -> list[str]:
    """Distinct snapshot days available for this board, oldest first.

    The week picker offers exactly this list and nothing else: a day that has no
    rows would render an empty board that looks like a league with no teams in
    it, which is indistinguishable on screen from a broken page.
    """
    return [r["day"] for r in query(
        "SELECT DISTINCT day FROM rating_snapshots "
        "WHERE gender=? AND system=? AND season=? ORDER BY day",
        (gender, system, _label(season)))]


def board_as_of(gender, day, season=SEAS.DEFAULT, system=SYSTEM) -> dict:
    """The board exactly as it stood on `day`: {team_id: {rank, rating, name,
    class, day}}, or {} if that day was never snapshotted.

    A PURE TABLE READ — no engine call, no rating solve. That is the whole
    point of the week picker: the live board costs a full opponent-adjusted
    solve over every finished game, and this costs one indexed SELECT plus a
    join for the names, so looking at history is FASTER than looking at today.
    """
    rows = query(
        """SELECT s.team_id, s.rank, s.rating, t.name, t.class, t.state
           FROM rating_snapshots s JOIN teams t ON t.id = s.team_id
           WHERE s.day=? AND s.gender=? AND s.system=? AND s.season=?
           ORDER BY s.rank""",
        (str(day), gender, system, _label(season)))
    return {r["team_id"]: {"Rank": r["rank"], "Rating": r["rating"],
                           "name": r["name"], "class": r["class"],
                           "state": r["state"], "day": str(day)}
            for r in rows}


def rank_history(gender, season=SEAS.DEFAULT, system=SYSTEM) -> dict:
    """Every snapshot day's ranks in one query: {day: {team_id: rank}}.

    Deliberately loaded whole rather than resolved per row. A game log is 20-30
    rows and a schedule table is more, and asking "what was the board the day
    before this game" one row at a time would be one query per row against a
    table that is 6,900 rows for a WHOLE SEASON of one gender. One read, then
    every resolution below is a dict lookup.
    """
    out: dict[str, dict[int, int]] = {}
    for r in query(
            "SELECT day, team_id, rank FROM rating_snapshots "
            "WHERE gender=? AND system=? AND season=? ORDER BY day",
            (gender, system, _label(season))):
        out.setdefault(str(r["day"]), {})[r["team_id"]] = r["rank"]
    return out


def day_before(days, date) -> str | None:
    """The latest snapshot day STRICTLY BEFORE `date` — the board a team walked
    into that game carrying. None when the game predates the first snapshot.

    Strictly before, not on-or-before, because `backfill_weekly` solves each
    day over the games finished ON OR BEFORE it: a board stamped with the game's
    own date already contains the game's result, so "the opponent's rank going
    into the game" would be contaminated by the game itself. On this book the
    boards are weekly, so the resolved day is 0-6 days stale — that is the true
    granularity of the reconstruction and no interpolation improves it.

    `days` is a sorted list (what `snapshot_days` returns). Returns None rather
    than the first day for pre-history games: 191 of this book's 9,676
    team-games are before 2025-11-16, and inventing a rank for them would put a
    November ranking on an October game, which is exactly the error the whole
    feature exists to stop making.
    """
    if not days or not date:
        return None
    d = str(date)[:10]
    i = bisect_left(days, d)
    return days[i - 1] if i > 0 else None


# ── surface 1b — the opponent's rank going into the game ──────────────────────
def opponent_ranks(game_log, gender, season=SEAS.DEFAULT, system=SYSTEM,
                   history=None) -> dict:
    """{game_id: rank-or-None} — the opponent's rank GOING INTO each game.

    `game_log` is any iterable of rows carrying `game_id`, `date` and `opp_id`
    (the `team_analytics.team_game_log` shape, and the upcoming-games rows once
    they are given the same three keys). `history` lets a caller that already
    holds `rank_history` pass it in rather than re-reading.

    None means "genuinely unknown", and the render must show nothing rather than
    a dash-as-rank or today's number: either the game predates the first
    snapshot, or the opponent was below `MIN_SNAPSHOT_GP` and has no row on that
    board at all. Both are honest gaps; a guess would not be.
    """
    hist = rank_history(gender, season, system) if history is None else history
    days = sorted(hist)
    out = {}
    for g in game_log:
        d = day_before(days, g.get("date"))
        out[g.get("game_id")] = (hist.get(d, {}).get(g.get("opp_id"))
                                 if d else None)
    return out


def rank_chip(rank) -> str:
    """'#6' for a resolved rank, '' for None. The empty string is the point —
    a game with no reconstructed board prints the opponent's name plain, the
    way the app did before this feature, rather than advertising a hole."""
    return f"#{int(rank)}" if rank else ""


# ── surface 1c — quality wins, counted at the time ────────────────────────────
def quality_wins(game_log, gender, season=SEAS.DEFAULT, top_n=DEFAULT_TOP_N,
                 rank_now=None, system=SYSTEM, history=None) -> dict:
    """Wins over a team ranked top-`top_n` AT THE TIME they were played.

    Returns::

        {"top_n": n,
         "has_history": bool,      # False -> the caller renders "no history yet"
         "n_then": int,            # counted against the board of the day
         "n_now": int | None,      # counted against TODAY's board (rank_now)
         "wins":  [row, ...],      # the qualifying wins, newest first
         "then_only": [row, ...],  # wins that count then but not today
         "now_only":  [row, ...],  # wins that count today but did not then
         "unresolved": int}        # wins with no board to resolve against

    `rank_now` is an optional {team_id: rank} (the page's live `scored` board,
    indexed out) purely so the two counts can be shown side by side. Without it
    `n_now` is None and the naive comparison is simply not drawn — the
    at-the-time number is the product, and the comparison is the argument for it.

    Each row carries both ranks so the render can say "#6 at the time, #41
    today" without a second pass.
    """
    hist = rank_history(gender, season, system) if history is None else history
    days = sorted(hist)
    rows, then_only, now_only = [], [], []
    unresolved = 0
    for g in game_log:
        if not g.get("won"):
            continue
        d = day_before(days, g.get("date"))
        r_then = hist.get(d, {}).get(g.get("opp_id")) if d else None
        r_now = (rank_now or {}).get(g.get("opp_id"))
        if r_then is None:
            unresolved += 1
        q_then = r_then is not None and r_then <= top_n
        q_now = r_now is not None and r_now <= top_n
        if not (q_then or q_now):
            continue
        row = {"game_id": g.get("game_id"), "date": g.get("date"),
               "opp": g.get("opp"), "opp_id": g.get("opp_id"),
               "site": g.get("site"), "pf": g.get("pf"), "pa": g.get("pa"),
               "margin": g.get("margin"),
               "rank_then": r_then, "rank_now": r_now,
               "as_of": d, "then": q_then, "now": q_now}
        if q_then:
            rows.append(row)
        if q_then and not q_now:
            then_only.append(row)
        if q_now and not q_then:
            now_only.append(row)
    rows.sort(key=lambda r: (r["date"] or ""), reverse=True)
    return {"top_n": top_n, "has_history": bool(days),
            "n_then": len(rows),
            "n_now": (None if rank_now is None
                      else sum(1 for g in game_log
                               if g.get("won")
                               and (rank_now.get(g.get("opp_id")) or 10 ** 9)
                               <= top_n)),
            "wins": rows, "then_only": then_only, "now_only": now_only,
            "unresolved": unresolved}
