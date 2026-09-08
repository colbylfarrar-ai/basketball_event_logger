"""SQLite has never been told what is in this book.

`ANALYZE` has never run on the production database, so `sqlite_stat1` does not
exist and the query planner is guessing from index shape alone. On the hottest
predicate in the app — `WHERE tracked=1 AND season=?`, which appears at 74 sites
— it picks `idx_games_season` (13,362 rows) over `idx_games_tracked` (63). On the
production snapshot that is 2.83 ms a call against 0.13 ms, and ANALYZE itself
costs 0.09 s on the whole 17 MB book.

That ratio is why this is a tool and not a startup step: it is far too cheap to
be worth thinking about and far too valuable to leave to somebody remembering.
It is also a WRITE, so it does not belong in `initialize_database()` where every
page load and every tracker request would take a writer's lock on a Friday night
with three games being logged at once.

Run: python -m pytest tracker/test_analyze_book.py
"""
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_analyze_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                          # noqa: E402
import database.db as DB                               # noqa: E402
from database.db import execute, query                 # noqa: E402

sys.path.insert(0, str(_APP / "tools"))
import analyze_book as AB                              # noqa: E402

DB.initialize_database()


@pytest.fixture(autouse=True)
def _this_modules_db():
    # The collection hazard test_read_filter_empty_scope.py documents: the LAST
    # module to set APP5_DATA_DIR at import time wins for the whole run.
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


def _seed():
    t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('A HS','3A','F')")
    t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('B HS','3A','F')")
    # A lopsided book is the whole point — the planner only has a wrong choice
    # to make when one branch of the predicate is far more selective than the
    # other, which is what a book of 13,383 games and 63 tracked ones is.
    # DISTINCT DATES. These 200 rows are all the same matchup, so recycling 28
    # dates put seven copies of one game on each day — which `game_dedup` has
    # always collapsed at read time and `ux_games_matchup` now refuses at write
    # time. The planner test only wants a lopsided tracked/untracked split; the
    # date collision was incidental and is not what is under test here.
    from datetime import date as _date, timedelta as _td
    _d0 = _date(2025, 11, 1)
    for i in range(200):
        execute("INSERT INTO games (team1_id,team2_id,date,tracked,season,"
                "home_score,away_score) VALUES (?,?,?,?,'2025-2026',50,40)",
                (t1, t2, (_d0 + _td(days=i)).isoformat(), 1 if i < 3 else 0))
    return t1


_T1 = _seed()


def _has_stats():
    return bool(query("SELECT 1 FROM sqlite_master WHERE name='sqlite_stat1'"))


_HOT = "SELECT id FROM games WHERE tracked=1 AND season='2025-2026'"


def _plan():
    return query("EXPLAIN QUERY PLAN " + _HOT)[0]["detail"]


def test_the_planner_stops_taking_the_wrong_index_on_the_hot_predicate():
    """The actual defect, reproduced: with no statistics SQLite searches the
    197-row season index instead of the 3-row tracked one, and after ANALYZE it
    does not. Asserted on the PLAN rather than on a wall-clock time, which would
    be a flaky test of this machine."""
    assert "idx_games_season" in _plan(), (
        "the fixture no longer reproduces the production planner choice, so "
        f"the assertion below proves nothing: {_plan()}")
    assert AB.main() == 0
    assert "idx_games_tracked" in _plan(), _plan()


def test_running_it_gives_the_planner_something_to_read():
    assert AB.main() == 0
    assert _has_stats(), "ANALYZE ran and left no sqlite_stat1 behind"
    assert query("SELECT 1 FROM sqlite_stat1 WHERE tbl='games'"), \
        "the games table — the one carrying the hot predicate — has no stats"


def test_it_is_safe_to_run_every_night_forever():
    """It goes on a timer next to the rollover, so a second run has to be a
    no-op rather than an error or a duplicate row."""
    assert AB.main() == 0
    assert AB.main() == 0
    assert _has_stats()
