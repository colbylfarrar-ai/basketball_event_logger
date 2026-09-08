"""One IMPORTED row per real game — and not one row per real game.

THE BOOK §8.8 wanted the duplicate-game class made impossible rather than
repairable, and Q13 ("teams only play once per day") is what unblocks an index
at all. Two things decide its shape, and the second one is why this file
exists.

NORMALISED, because half the duplicates are mirrored. Production carried nine
duplicate matchups and four of them had home and away swapped, which
UNIQUE(date, team1_id, team2_id) cannot see. That mirror is what
ossaa_sync.merge_teams produces and the case game_dedup.py was written for.

PARTIAL, because Q13 answers a scheduling question and a strict index would
answer a different one. Two rows for one real game are DESIGNED here —
tracker/api.py's create_game says so itself: "the same real game already
tracked by another coach is legitimate (a second angle)". A strict index also
blocks the ORDINARY courtside create, because a coach tracking a game the
scraper has already loaded is inserting a second row for that matchup. Both
were measured against a repaired copy of the production book before this index
was narrowed, and both failed with an IntegrityError in either orientation —
a 500 on the one surface where a failure costs data permanently.

`tracked_by` separates them cleanly. Every imported row carries '' and every
coach-created row carries an email; on production all nine duplicate pairs are
''-on-both-sides, and all nine collisions among ''-rows are those same nine.

Run: python -m pytest tracker/test_games_matchup_index.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_matchup_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                          # noqa: E402
import database.db as DB                               # noqa: E402
from database.db import execute, query                 # noqa: E402

DB.initialize_database()

SEASON = "2025-2026"


@pytest.fixture(autouse=True)
def _this_modules_db():
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    yield
    if prev is not None:
        os.environ["APP5_DATA_DIR"] = prev


def _reset():
    execute("DELETE FROM games")
    execute("DELETE FROM teams")
    for tid, name in ((1, "Home Girls"), (2, "Away Girls")):
        execute("INSERT INTO teams (id, name, class, gender, state) "
                "VALUES (?,?,?,?,?)", (tid, name, "4A", "F", "OK"))


def _add(t1, t2, date="2025-12-01", tracked_by=""):
    return execute(
        "INSERT INTO games (team1_id, team2_id, date, tracked_by, season) "
        "VALUES (?,?,?,?,?)", (t1, t2, date, tracked_by, SEASON))


def test_the_index_exists_after_a_clean_boot():
    assert query("SELECT name FROM sqlite_master WHERE type='index' "
                 "AND name='ux_games_matchup'"), \
        "the matchup index never got created on a fresh book"


def test_a_second_imported_row_is_refused_in_either_orientation():
    _reset()
    _add(1, 2)
    with pytest.raises(sqlite3.IntegrityError):
        _add(1, 2)
    with pytest.raises(sqlite3.IntegrityError):
        _add(2, 1)          # the mirror — the merge_teams class, and the half
                            # a plain UNIQUE(date, team1_id, team2_id) misses
    _reset()


def test_a_different_day_is_a_different_game():
    _reset()
    _add(1, 2, "2025-12-01")
    _add(1, 2, "2025-12-02")        # a real rematch, and it must be allowed
    assert len(query("SELECT id FROM games")) == 2
    _reset()


def test_the_courtside_create_still_works_over_a_scheduled_row():
    """The path that a strict index broke. A coach tracking a game the scraper
    has already loaded is inserting a second row for that matchup, and this is
    the ordinary case, not an edge one."""
    _reset()
    _add(1, 2)                                   # the scraper's scheduled row
    _add(1, 2, tracked_by="coach@example.com")   # the PWA's create_game
    _add(2, 1, tracked_by="coach@example.com")   # …and in the mirror
    assert len(query("SELECT id FROM games")) == 3
    _reset()


def test_a_second_angle_retrack_is_still_allowed():
    """tracker/api.py: "the same real game already tracked by another coach is
    legitimate (a second angle)". game_dedup picks the fuller row at read
    time; the schema must not pre-empt that."""
    _reset()
    _add(1, 2, tracked_by="one@example.com")
    _add(1, 2, tracked_by="two@example.com")
    _add(2, 1, tracked_by="three@example.com")
    assert len(query("SELECT id FROM games")) == 3
    _reset()


def test_the_index_is_not_self_repairing():
    """A duplicate GAME can carry events, a score and a tracked flag, so which
    row dies is a judgement about someone's season — not a migration's call.
    The statement must FAIL on a dirty book and be recorded, never delete."""
    import re
    src = (_APP / "database" / "db.py").read_text(encoding="utf-8")
    m = re.search(r"CREATE UNIQUE INDEX IF NOT EXISTS ux_games_matchup.*?,\n",
                  src, re.S)
    assert m, "the index statement moved or was removed"
    stmt = m.group(0)
    assert "tracked_by = ''" in stmt, "the partial clause is gone — this index " \
        "now blocks the courtside create"
    assert "MIN(team1_id, team2_id)" in stmt and "MAX(team1_id, team2_id)" in stmt, \
        "the index stopped normalising orientation and misses every mirror"
    # and no DELETE FROM games anywhere near it
    before = src[:m.start()]
    assert "DELETE FROM games" not in before[-3000:], \
        "something now deletes duplicate games as part of a migration"
