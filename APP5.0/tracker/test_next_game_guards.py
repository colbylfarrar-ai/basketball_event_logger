"""The two `_next_game` implementations must answer the same question.

`team_card._next_game` and `insights_deck._next_game` both mean "the next game
this team plays". The Overview card's version guards on two things the Insights
masthead's version does not:

  * the season has to be CURRENT — a past season is over, so it has no next game;
  * the date has to be TODAY OR LATER — an unscored row on a finished season is a
    game that was never entered, not a fixture.

Without them the Insights masthead reads "next: at Salina Girls 2025-12-05" on a
season that ended in March, six inches from an Overview card that correctly shows
nothing. Two engines, one question, two answers — and the wrong one is the one on
the masthead a coach reads first.

The fixture reproduces both halves on purpose: a past-season fixture that was
never scored (the archive case) and a current-season fixture whose date has gone
by (the stale case). Neither is a next game.

Run: python -m pytest tracker/test_next_game_guards.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_nextgame_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                          # noqa: E402
import database.db as DB                               # noqa: E402
from database.db import execute                        # noqa: E402
import helpers.dashboard.insights_deck as DECK         # noqa: E402
import helpers.dashboard.team_card as TC               # noqa: E402

DB.initialize_database()


@pytest.fixture(autouse=True)
def _this_modules_db():
    # The same collection hazard test_read_filter_empty_scope.py documents: the
    # LAST module to set APP5_DATA_DIR at import time wins for the whole run, so
    # re-pin per test. The cache clears go with it — both engines are
    # st.cache_data'd and a hit from a sibling module's DB would answer from the
    # wrong book entirely.
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    DECK._next_game.clear()
    TC._next_game.clear()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


_PAST = "2025-2026"


def _seed():
    t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('A HS','3A','F')")
    t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('B HS','3A','F')")
    t3 = execute("INSERT INTO teams (name, class, gender) VALUES ('C HS','3A','F')")
    # the archive case — a past season's fixture that never got a score
    execute("INSERT INTO games (team1_id,team2_id,date,season) VALUES (?,?,?,?)",
            (t1, t2, "2025-12-05", _PAST))
    # the stale case — this season, but the date has gone by
    execute("INSERT INTO games (team1_id,team2_id,date,season) "
            "VALUES (?,?,?,'Current')",
            (t1, t3, (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")))
    return t1


_T1 = _seed()


def test_a_past_season_has_no_next_game():
    """An archived season is over. Its unscored rows are not fixtures."""
    assert DECK._next_game(_T1, _PAST) is None, (
        "the Insights masthead offered a next game on a season that has "
        "already finished")


def test_a_date_that_has_gone_by_is_not_a_next_game():
    """'Next' means today or later, the way the Overview card already reads it."""
    assert DECK._next_game(_T1, "Current") is None, (
        "the Insights masthead offered a game whose date is in the past as the "
        "next one")


def test_the_two_implementations_agree():
    """Whatever the rule is, one question gets one answer.

    Compared on emptiness rather than on shape — the two return different
    structures on purpose (a tuple for the masthead line, a row dict for the
    card) and consolidating them is §14's job, not this test's."""
    for season in (_PAST, "Current"):
        assert (DECK._next_game(_T1, season) is None) \
            == (TC._next_game(_T1, season) is None), \
            f"the two _next_game engines disagree on season {season!r}"
