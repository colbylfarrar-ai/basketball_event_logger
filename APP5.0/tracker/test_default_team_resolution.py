"""A new coach must land on their own program, not on a stranger's.

`default_team` is USER_SCOPED, so a coach who has chosen one is stored at
`u:<email>:default_team`. But `get_setting` falls through to the BARE key when a
coach has no override, and production carries a bare `default_team` row left over
from the single-coach era — `Bishop Kelley Girls`, a program nobody signed in
here coaches. That fall-through fires before the Team Dashboard's own "land on
your own team" fallback can run, so the fallback never runs at all: it is written,
it is correct, and it is unreachable.

Nobody notices today because all six production accounts already have a per-coach
value. It bites in October, when four or five coaches sign in for the first time
and the app opens on a team none of them have heard of — on the page that is also
the app's landing page.

The order this asserts, and the reason for each step:

    1. this coach's own stored choice     an explicit decision wins, always
    2. the team on their identity         the fallback that could never run
    3. the bare global row                a single-coach install still works
    4. ""                                 the caller falls back to ranking order

Run: python -m pytest tracker/test_default_team_resolution.py
"""
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_defteam_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                          # noqa: E402
import database.db as DB                               # noqa: E402
from database.db import execute                        # noqa: E402
import helpers.settings_utils as SU                    # noqa: E402

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


_CHOSE = "chose@example.com"       # a coach who has picked a default
_NEW = "new@example.com"           # a coach who signed in this morning


def _seed():
    own = execute("INSERT INTO teams (name, class, gender) "
                  "VALUES ('Adair Girls','3A','F')")
    execute("INSERT INTO teams (name, class, gender) "
            "VALUES ('Salina Girls','3A','F')")
    # the legacy single-coach row — a real team, and not this coach's
    execute("INSERT OR REPLACE INTO app_settings (key, value) "
            "VALUES ('default_team', 'Bishop Kelley Girls')")
    execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)",
            (f"u:{_CHOSE}:default_team", "Salina Girls"))
    return own


_OWN = _seed()


def test_an_explicit_choice_wins():
    """A coach who has picked a default keeps it, over their own team and over
    the global row both."""
    assert SU.default_team_name(email=_CHOSE, team_id=_OWN) == "Salina Girls"


def test_a_coach_with_no_choice_lands_on_their_own_team():
    """The case that never ran. Their identity carries a team; that is the
    answer, and the stale global row does not get a vote."""
    assert SU.default_team_name(email=_NEW, team_id=_OWN) == "Adair Girls"


def test_the_global_row_still_serves_an_install_with_no_identity():
    """Single-coach and local-dev installs have no per-user row and no team on
    the identity. They keep today's behaviour rather than losing a default."""
    assert SU.default_team_name(email="", team_id=None) == "Bishop Kelley Girls"


def test_a_team_id_that_no_longer_exists_does_not_win():
    """A deleted or merged team must not resolve to an empty name and swallow
    the fallbacks below it — `merge_teams` retires team ids for a living."""
    assert SU.default_team_name(email=_NEW, team_id=9_999_999) \
        == "Bishop Kelley Girls"
