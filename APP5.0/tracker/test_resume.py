"""
The point-in-time résumé must resolve against the board of the DAY, not today.

`helpers/resume.py` reads `rating_snapshots` to answer three questions the app
could not answer before: what did the board look like on a past week, what rank
did an opponent carry GOING INTO a game, and how many quality wins does a team
have when they are counted at the time rather than against today's rankings.

The measurement that makes it worth building, from the live book: rank movement
between 2025-12-14 and 2026-03-14 has a median of 68 places, only 11 of
December's top 25 were still top 25 in March, and 71 of the 102 teams with any
quality win get a DIFFERENT count depending on which board you ask. CANUTE has
three quality wins at the time and none today; Grind Prep has none then and
three today. A feature that gets this wrong is not slightly off, it is
describing a different team.

Four things are guarded here, and each one is a way the feature could be wrong
while still looking healthy on screen:

  1. the day-before resolution picks the right board — STRICTLY before, because
     `backfill_weekly` solves each day over the games finished ON OR BEFORE it,
     so a board stamped with the game's own date already contains the result of
     the game being described;
  2. a game played before the first snapshot yields NO rank rather than an
     exception or a borrowed number;
  3. counted-at-the-time really does differ from counted-today — the whole
     premise, asserted on a seeded fixture rather than trusted;
  4. an empty snapshot table degrades to "no history yet" instead of raising,
     because a fresh book genuinely has none and a coach who has never pressed
     Rebuild must not meet a stack trace.

Throwaway DB. Run: python -m pytest tracker/test_resume.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_resume_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                   # noqa: E402
import database.db as DB                        # noqa: E402
from database.db import execute, query          # noqa: E402
import helpers.resume as RES                    # noqa: E402
import helpers.seasons as SEAS                  # noqa: E402
import helpers.team_analytics as TA             # noqa: E402

DB.initialize_database()

_SEASON = "2025-2026"
_ALPHA, _BRAVO, _CHARLIE, _DELTA, _ECHO = 8001, 8002, 8003, 8004, 8005

#: Two saved boards a month apart, with Bravo and Charlie deliberately trading
#: places. That swap is the whole fixture: it makes "at the time" and "today"
#: give different answers about the SAME win, which is the claim the feature
#: makes about the live book.
_D1, _D2 = "2026-01-01", "2026-02-01"
_BOARDS = {
    _D1: {_BRAVO: 3, _CHARLIE: 40, _DELTA: 40},
    _D2: {_BRAVO: 40, _CHARLIE: 3, _DELTA: 40},
}
#: Where the same four teams sit on the CURRENT board — the naive comparison.
#: Echo is absent from every saved board on purpose (a team under the 5-game
#: snapshot floor), so the "no row on that day" gap is exercised alongside the
#: "no board at all" one.
_RANK_NOW = {_BRAVO: 40, _CHARLIE: 30, _DELTA: 5, _ECHO: 12}

#: (id, opponent, date, alpha won) — Alpha's whole season.
_GAMES = [
    # before the first board exists: unresolvable, and must stay that way
    (8101, _BRAVO,   "2025-12-01", True),
    # resolve to _D1, where Bravo is #3 — a quality win then, not now
    (8102, _BRAVO,   "2026-01-15", True),
    (8103, _BRAVO,   "2026-01-20", True),
    # a LOSS to a then-#3 side: must never be counted as a quality win
    (8104, _BRAVO,   "2026-01-25", False),
    # played ON a snapshot day: must resolve to the PREVIOUS board (_D1, where
    # Charlie is #40), not to _D2's board, which already contains this game
    (8105, _CHARLIE, _D2,          True),
    # resolve to _D2, where Charlie is #3 — a quality win both then and… no:
    # #30 today, so then-only again
    (8106, _CHARLIE, "2026-02-15", True),
    # Delta is #40 on both boards but #5 today — today's board credits a win
    # that was not a quality win at the time
    (8107, _DELTA,   "2026-02-15", True),
    # Echo never appears on a board: an honest gap, not a zero
    (8108, _ECHO,    "2026-02-10", True),
]


def _seed():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(8001,'Resume Alpha','4A','M'),"
            "(8002,'Resume Bravo','4A','M'),"
            "(8003,'Resume Charlie','4A','M'),"
            "(8004,'Resume Delta','4A','M'),"
            "(8005,'Resume Echo','4A','M')")
    for gid, opp, date, won in _GAMES:
        hs, as_ = (70, 50) if won else (50, 70)
        execute("INSERT INTO games (id, team1_id, team2_id, date, home_score,"
                " away_score, tracked, season) VALUES (?,?,?,?,?,?,0,?)",
                (gid, _ALPHA, opp, date, hs, as_, _SEASON))
    for day, board in _BOARDS.items():
        for tid, rank in board.items():
            execute("INSERT INTO rating_snapshots (day, gender, system, "
                    "team_id, season, rating, rank) VALUES (?,?,?,?,?,?,?)",
                    (day, "M", "score", tid, _SEASON,
                     100.0 - rank, rank))


@pytest.fixture(autouse=True)
def _this_modules_db():
    # The collection hazard test_results_season_rollover.py documents: the LAST
    # module to set APP5_DATA_DIR at import time wins for the whole run, so a
    # sibling test module's temp dir would otherwise be live by the time these
    # tests execute. Re-pin per test.
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


if not query("SELECT id FROM teams WHERE id=8001"):
    _seed()


def _log():
    return TA.team_game_log(_ALPHA, season=_SEASON)


class DayResolution(unittest.TestCase):
    """1 — the board a game was played INTO."""

    def test_snapshot_days_are_the_two_seeded_boards(self):
        self.assertEqual(RES.snapshot_days("M", _SEASON), [_D1, _D2])

    def test_day_before_picks_the_latest_board_that_predates_the_game(self):
        days = [_D1, _D2]
        self.assertEqual(RES.day_before(days, "2026-01-15"), _D1)
        self.assertEqual(RES.day_before(days, "2026-02-15"), _D2)

    def test_a_game_on_a_snapshot_day_reads_the_PREVIOUS_board(self):
        """Strictly before, not on-or-before. `backfill_weekly` solves each day
        over the games finished ON OR BEFORE it, so the board stamped with the
        game's own date already contains that game — resolving to it would let
        the result of the game set the opponent's 'going in' rank."""
        self.assertEqual(RES.day_before([_D1, _D2], _D2), _D1)
        ranks = RES.opponent_ranks(_log(), "M", season=_SEASON)
        self.assertEqual(ranks[8105], 40,
                         "a game played on a snapshot day read that day's own "
                         "board instead of the one before it")

    def test_the_resolved_rank_is_the_one_from_that_board(self):
        ranks = RES.opponent_ranks(_log(), "M", season=_SEASON)
        self.assertEqual(ranks[8102], 3)      # Bravo on _D1
        self.assertEqual(ranks[8103], 3)
        self.assertEqual(ranks[8106], 3)      # Charlie on _D2
        self.assertEqual(ranks[8107], 40)     # Delta on _D2

    def test_board_as_of_is_the_saved_board_and_nothing_else(self):
        b = RES.board_as_of("M", _D1, _SEASON)
        self.assertEqual({t: r["Rank"] for t, r in b.items()}, _BOARDS[_D1])
        self.assertEqual(b[_BRAVO]["name"], "Resume Bravo")
        self.assertEqual(list(b), sorted(b, key=lambda t: b[t]["Rank"]),
                         "board_as_of must come back rank-ordered")

    def test_the_default_season_sentinel_resolves(self):
        """`SEAS.DEFAULT` has to reach `default_read_season()` before the label
        lookup. Without that it would query for the literal '__default__' and
        return a clean, silent, completely empty board — the exact shape of the
        rollover trap this codebase has already been bitten by three times."""
        self.assertEqual(RES.snapshot_days("M", SEAS.DEFAULT), [_D1, _D2])
        self.assertEqual(RES.snapshot_days("M"), [_D1, _D2])


class PreHistoryGames(unittest.TestCase):
    """2 — no board yet is a blank, not a guess and not a crash."""

    def test_a_game_before_the_first_board_has_no_rank(self):
        ranks = RES.opponent_ranks(_log(), "M", season=_SEASON)
        self.assertIsNone(ranks[8101],
                          "a pre-first-snapshot game was given a rank it "
                          "cannot have")

    def test_an_opponent_with_no_row_on_that_board_has_no_rank(self):
        """Distinct from the above and much more common on the live book: the
        board EXISTS, the opponent is simply not on it (under the 5-game
        snapshot floor). 5,436 of this book's 25,296 team-games fail this way
        against 780 that predate the first board."""
        ranks = RES.opponent_ranks(_log(), "M", season=_SEASON)
        self.assertIsNone(ranks[8108])

    def test_day_before_the_first_board_is_None_not_the_first_board(self):
        self.assertIsNone(RES.day_before([_D1, _D2], "2025-11-01"))

    def test_rank_chip_renders_nothing_for_a_missing_rank(self):
        self.assertEqual(RES.rank_chip(None), "")
        self.assertEqual(RES.rank_chip(6), "#6")


class QualityWinsAtTheTime(unittest.TestCase):
    """3 — the premise: the two counts really do disagree."""

    def _qw(self, top_n=25):
        return RES.quality_wins(_log(), "M", season=_SEASON, top_n=top_n,
                                rank_now=_RANK_NOW)

    def test_the_two_counts_differ(self):
        q = self._qw()
        self.assertEqual(q["n_then"], 3,
                         "wins over Bravo(#3) twice and Charlie(#3) once")
        self.assertEqual(q["n_now"], 2,
                         "on today's board only Delta (#5) and Echo (#12) "
                         "are inside the cutoff")
        self.assertNotEqual(q["n_then"], q["n_now"])

    def test_the_wins_that_only_count_at_the_time(self):
        q = self._qw()
        self.assertEqual(sorted(w["game_id"] for w in q["then_only"]),
                         [8102, 8103, 8106])

    def test_the_wins_that_only_count_today(self):
        """Two different ways today's board manufactures a résumé line. Delta
        was #40 on both saved boards and is #5 now. Echo was never ON a board
        and is #12 now — so counting against today does not merely re-rank the
        opponent, it invents a ranking for a game where none existed."""
        q = self._qw()
        self.assertEqual(sorted(w["game_id"] for w in q["now_only"]),
                         [8107, 8108])

    def test_a_loss_to_a_ranked_team_is_not_a_quality_win(self):
        q = self._qw()
        self.assertNotIn(8104, [w["game_id"] for w in q["wins"]])

    def test_unresolved_wins_are_counted_not_guessed(self):
        """Two wins cannot be scored at the time — one predates every board,
        one is against a team that never made a board. Neither may be silently
        treated as 'not a quality win' without saying so."""
        q = self._qw()
        self.assertEqual(q["unresolved"], 2)

    def test_each_win_carries_both_ranks_and_its_board(self):
        q = self._qw()
        w = next(w for w in q["wins"] if w["game_id"] == 8102)
        self.assertEqual((w["rank_then"], w["rank_now"], w["as_of"]),
                         (3, 40, _D1))

    def test_the_cutoff_moves_the_answer(self):
        """top_n is a real parameter, not decoration: at 50 the Delta win and
        both Charlie-at-#40 reads come inside the cutoff too."""
        self.assertEqual(self._qw(top_n=50)["n_then"], 5)
        self.assertEqual(self._qw(top_n=10)["n_then"], 3)

    def test_rank_now_is_optional_and_suppresses_the_comparison(self):
        q = RES.quality_wins(_log(), "M", season=_SEASON)
        self.assertEqual(q["n_then"], 3)
        self.assertIsNone(q["n_now"],
                          "without a live board there is no honest 'today' "
                          "number to draw")


class NoHistoryYet(unittest.TestCase):
    """4 — a book nobody has rebuilt renders a message, not a traceback."""

    def test_a_board_with_no_rows_degrades(self):
        """The girls' board here has never been snapshotted — the same state a
        whole book is in before Rebuild is pressed."""
        self.assertEqual(RES.snapshot_days("F", _SEASON), [])
        self.assertEqual(RES.board_as_of("F", _D1, _SEASON), {})
        self.assertEqual(RES.rank_history("F", _SEASON), {})

    def test_opponent_ranks_over_no_history_is_all_None(self):
        ranks = RES.opponent_ranks(_log(), "F", season=_SEASON)
        self.assertEqual(set(ranks.values()), {None})

    def test_quality_wins_reports_has_history_False(self):
        q = RES.quality_wins(_log(), "F", season=_SEASON, rank_now=_RANK_NOW)
        self.assertFalse(q["has_history"],
                         "the page keys its 'press Rebuild' message off this "
                         "flag — a False that reads True would render an "
                         "authoritative zero over a book with no history")
        self.assertEqual(q["n_then"], 0)

    def test_a_genuinely_empty_table_behaves_the_same(self):
        """Not merely an empty BOARD — an empty TABLE, which is what a book
        that has never run a backfill actually has. Restored in `finally` so
        the rest of the module keeps its fixture."""
        rows = query("SELECT * FROM rating_snapshots")
        try:
            execute("DELETE FROM rating_snapshots")
            self.assertEqual(RES.snapshot_days("M", _SEASON), [])
            q = RES.quality_wins(_log(), "M", season=_SEASON,
                                 rank_now=_RANK_NOW)
            self.assertFalse(q["has_history"])
            self.assertEqual(q["n_then"], 0)
            self.assertEqual(q["wins"], [])
            self.assertIsNone(
                RES.opponent_ranks(_log(), "M", season=_SEASON)[8102])
        finally:
            for r in rows:
                execute(
                    "INSERT OR IGNORE INTO rating_snapshots (day, gender, "
                    "system, team_id, season, rating, rank) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (r["day"], r["gender"], r["system"], r["team_id"],
                     r["season"], r["rating"], r["rank"]))
        self.assertEqual(RES.snapshot_days("M", _SEASON), [_D1, _D2])

    def test_an_unknown_season_label_is_empty_not_an_error(self):
        self.assertEqual(RES.snapshot_days("M", "2019-2020"), [])
        self.assertEqual(RES.board_as_of("M", _D1, "2019-2020"), {})

