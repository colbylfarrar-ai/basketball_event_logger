"""
The default team game pool must survive a season rollover (N5).

`stats._team_game_ids` and `_team_game_ids_all` hardcoded `season='Current'`,
which is EMPTY for the first weeks of a season — every game still sits under the
previous label. They are the DEFAULT pool for `rotation_plan.star_coverage` and
`foul_prone` and for the player card's on/off splits, so in that window a no-arg
call reported, in good faith, that a team has no key players and no on/off
signal at all.

Same post-rollover gap the DWPA EP=0.0 bug came from, so it takes the same fix:
`seasons.tracked_default_season_sql()` falls back to the most recently played
season that HAS tracked games.

Throwaway DB (the test_wpa_recal pattern) seeded with games under a PAST season
label and nothing under 'Current' — i.e. the morning after a rollover.

Run: python -m pytest tracker/test_team_game_pool_rollover.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_pool_rollover_")
os.environ["APP5_DATA_DIR"] = _TMP

from database.db import execute, query          # noqa: E402  (migrates _TMP db)
import helpers.seasons as SEAS                  # noqa: E402
import helpers.stats as S                       # noqa: E402

_HOME, _AWAY = 7001, 7002
_PAST = "2025-2026"


def _seed():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(7001,'Rollover Home','4A','M'),(7002,'Rollover Away','4A','M')")
    # Two tracked games and one untracked, all under the PAST season label —
    # the state of the book on the first morning of a new season.
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
            "VALUES (7101,7001,7002,'2026-01-10',1,?)", (_PAST,))
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
            "VALUES (7102,7002,7001,'2026-01-17',1,?)", (_PAST,))
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
            "VALUES (7103,7001,7002,'2026-01-24',0,?)", (_PAST,))


class TeamGamePoolRollover(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not query("SELECT id FROM teams WHERE id=7001"):
            _seed()

    def test_the_active_season_really_is_empty(self):
        """The premise: without the fallback there is nothing to find."""
        self.assertEqual(
            query("SELECT COUNT(*) AS n FROM games WHERE season=?",
                  (SEAS.ACTIVE,))[0]["n"], 0)

    def test_tracked_pool_falls_back_to_the_last_played_season(self):
        gids = S._team_game_ids(_HOME)
        self.assertEqual(sorted(gids), [7101, 7102],
                         "the default tracked pool went empty after rollover")

    def test_all_games_pool_falls_back_too(self):
        """Same trap on the sibling used by the player card's on/off splits."""
        gids = S._team_game_ids_all(_HOME)
        self.assertEqual(sorted(gids), [7101, 7102, 7103],
                         "the default all-games pool went empty after rollover")

    def test_the_fallback_is_only_a_default(self):
        """A current season WITH tracked games must still win, or the fallback
        would quietly blend last year into this year's reads."""
        execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
                "VALUES (7201,7001,7002,'2026-11-30',1,?)", (SEAS.ACTIVE,))
        try:
            self.assertEqual(S._team_game_ids(_HOME), [7201])
            self.assertEqual(S._team_game_ids_all(_HOME), [7201])
        finally:
            execute("DELETE FROM games WHERE id=7201")

    def test_every_default_reader_shares_the_pool(self):
        """The pool is the single source for the Tier-2 helpers, so the fix has
        to reach all of them rather than one call site."""
        import helpers.concession as CON
        import helpers.possession_value as PV
        import helpers.rotation_plan as RP
        for mod in (CON, PV, RP):
            self.assertIs(mod._team_game_ids, S._team_game_ids,
                          f"{mod.__name__} holds its own copy of the pool")


if __name__ == "__main__":
    unittest.main()
