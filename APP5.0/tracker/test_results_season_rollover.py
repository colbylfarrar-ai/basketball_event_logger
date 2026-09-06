"""
The RESULTS-side default season must survive a rollover too.

`test_team_game_pool_rollover.py` fixed the TRACKED default pool (N5). This is
the same trap one layer over, on the results-only side: `_finished_games` (and
therefore `score_ratings`, `team_form_stats` and the whole power board) took
`season="Current"` as a hard default with no fallback, so the morning after a
rollover every no-season caller got ZERO teams over a full database.

Measured on the live book on 2026-09-05, before the fix:

    TR.score_ratings(gender='F')                 ->   0 teams
    TR.score_ratings(gender='F', '2025-2026')    -> 704 teams

The casualties were the callers with no season picker to pass one from —
`pages/0_Analytics_Hub.py` (the whole page: `if not scored: return d`),
`pages/4_Schedule.py` (which has no season handling anywhere in it),
`helpers/predictor.py`, `helpers/wpa.py`, `helpers/box_score.py`. The entitlement
pool had the identical default, so even a fixed page would have gated its own
depth off.

The fix is `seasons.DEFAULT` — a sentinel meaning "resolve the read season at
call time" — plus `resolve_read_season()`, which routes to the
`default_read_season()` fallback that the pickers have used all along. An
EXPLICIT `season='Current'` still means Current and still reads empty: a coach
who deliberately picks the new season must see the new season, not last year's
numbers wearing this year's label.

Throwaway DB seeded under a PAST label with nothing under 'Current' — the
morning after a rollover.

Run: python -m pytest tracker/test_results_season_rollover.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_results_rollover_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                   # noqa: E402
import database.db as DB                        # noqa: E402
from database.db import execute, query          # noqa: E402
import helpers.seasons as SEAS                  # noqa: E402
import helpers.team_ratings as TR               # noqa: E402
import helpers.league_analytics as LA           # noqa: E402

DB.initialize_database()

_A, _B, _C = 7301, 7302, 7303
_PAST = "2025-2026"


def _seed():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(7301,'Results Alpha','4A','M'),"
            "(7302,'Results Bravo','4A','M'),"
            "(7303,'Results Charlie','4A','M')")
    # Six finished games under the PAST label, none under 'Current'. Every team
    # plays every other twice so the rating solver has a connected pool.
    rows = [(7401, _A, _B, '2026-01-06', 60, 50, 1),
            (7402, _B, _C, '2026-01-13', 55, 58, 1),
            (7403, _C, _A, '2026-01-20', 48, 62, 0),
            (7404, _B, _A, '2026-01-27', 51, 57, 1),
            (7405, _C, _B, '2026-02-03', 49, 53, 0),
            (7406, _A, _C, '2026-02-10', 66, 44, 1)]
    for gid, t1, t2, d, hs, as_, trk in rows:
        execute("INSERT INTO games (id, team1_id, team2_id, date, home_score,"
                " away_score, tracked, season) VALUES (?,?,?,?,?,?,?,?)",
                (gid, t1, t2, d, hs, as_, trk, _PAST))


@pytest.fixture(autouse=True)
def _this_modules_db():
    # Same collection hazard as test_team_game_pool_rollover.py: the LAST module
    # to import wins the env var, so re-pin it per test.
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


if not query("SELECT id FROM teams WHERE id=7301"):
    _seed()


class ResultsSeasonRollover(unittest.TestCase):

    def test_the_active_season_really_is_empty(self):
        """The premise: without a fallback there is nothing to find."""
        self.assertEqual(
            query("SELECT COUNT(*) AS n FROM games WHERE season=?",
                  (SEAS.ACTIVE,))[0]["n"], 0)

    def test_finished_games_falls_back_to_the_last_played_season(self):
        rows = TR._finished_games(gender="M")
        self.assertEqual(sorted(r["id"] for r in rows),
                         [7401, 7402, 7403, 7404, 7405, 7406],
                         "the default finished-game pool went empty after rollover")

    def test_score_ratings_rates_the_field(self):
        """The headline symptom: the power board over a full DB read as 0 teams."""
        scored = TR.score_ratings(gender="M")
        self.assertEqual(len(scored), 3,
                         "score_ratings returned an empty board after rollover")
        self.assertEqual(sorted(scored), [_A, _B, _C])

    def test_team_form_stats_follows(self):
        self.assertEqual(len(LA.team_form_stats(gender="M")), 3)

    def test_tracked_only_pool_falls_back_too(self):
        """The tracked variant shares the default and the Analytics Hub counts
        its length for the 'games tracked' KPI."""
        rows = TR._finished_games(gender="M", tracked_only=True)
        self.assertEqual(sorted(r["id"] for r in rows), [7401, 7402, 7404, 7406])

    def test_an_explicit_current_still_means_current(self):
        """The fallback is a DEFAULT, not a rewrite. A coach who deliberately
        picks the new season must see the new season — empty — rather than last
        year's numbers relabelled."""
        self.assertEqual(TR._finished_games(gender="M", season=SEAS.ACTIVE), [])
        self.assertEqual(TR.score_ratings(gender="M", season=SEAS.ACTIVE), {})

    def test_season_none_still_means_every_season(self):
        """`None` is a documented value on this signature (all seasons) and the
        new sentinel must not have stolen it — test_seasons.py relies on it."""
        rows = TR._finished_games(gender="M", season=None)
        self.assertEqual(len(rows), 6)

    def test_the_fallback_yields_once_the_new_season_has_results(self):
        execute("INSERT INTO games (id, team1_id, team2_id, date, home_score,"
                " away_score, tracked, season) VALUES"
                " (7501,7301,7302,'2026-11-30',70,40,1,?)", (SEAS.ACTIVE,))
        try:
            rows = TR._finished_games(gender="M")
            self.assertEqual([r["id"] for r in rows], [7501],
                             "a populated active season must win over the fallback")
        finally:
            execute("DELETE FROM games WHERE id=7501")

    def test_the_entitlement_pool_falls_back_as_well(self):
        """A fixed page still shows nothing if the co-op read-filter resolves to
        an empty season — the visible set gates every tracked surface. The GATE
        itself is untouched; only which season it looks at moves."""
        import helpers.entitlement as ENT
        execute("UPDATE games SET in_pool=1 WHERE id IN (7401,7402,7404)")
        try:
            self.assertEqual(ENT.pooled_game_ids(), {7401, 7402, 7404})
            self.assertEqual(ENT.pooled_game_ids(season=SEAS.ACTIVE), set(),
                             "an explicit season must still be honoured")
        finally:
            execute("UPDATE games SET in_pool=0 WHERE id IN (7401,7402,7404)")
