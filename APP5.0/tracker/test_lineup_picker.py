"""The War Room's headline paid tool must not open on an empty team.

Lineup Creator's team picker is ranked and defaults to index 0. On production
the #1 team has no tracked data at all — 21 of 704 options produce anything, and
the first that works is #22. It is Paid-gated, so the coach paying for it is the
one who meets the empty state.

Worse, the message they meet is the wrong message. The engine has a proper gate
(`lineup_projection.MIN_TEAM_GAMES = 8`) that returns `"only 3 tracked games
(need 8)"`, and it is never seen: the page's own "no rated players at all" check
fires first, and its copy reads

    "No rated players on this team yet. Track a game for them first."

which is advice a coach cannot follow — nobody can track another program's
games.

`pickable_teams` is the option list, lifted out of the page so it can be
asserted on. Three rules:

    1. the viewer's own team comes first, so the picker opens on it
    2. every other option has tracked data behind it
    3. the viewer's own team is offered even when it has none — a coach is
       entitled to their own program, and to the honest reason it is empty

Run: python -m pytest tracker/test_lineup_picker.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.lineup_projection as LP                 # noqa: E402


# Rank order as the page builds it: 1..5, and only teams 3 and 5 have any
# rated players — the production shape in miniature.
ORDER = [1, 2, 3, 4, 5]
TABLE = {
    101: {"team_id": 3, "OVERALL": 60.0},
    102: {"team_id": 3, "OVERALL": 55.0},
    103: {"team_id": 5, "OVERALL": 51.0},
}


def test_a_a_league_wide_viewer_never_lands_on_an_empty_team():
    """The finding. Team 1 is ranked first and has nothing behind it."""
    opts = LP.pickable_teams(ORDER, TABLE, my_team=None, league_wide=True)
    assert opts, "offered no teams at all"
    assert opts[0] != 1, "still opens on the ranked #1 with no tracked data"
    assert set(opts) == {3, 5}, opts


def test_b_the_viewers_own_team_comes_first():
    opts = LP.pickable_teams(ORDER, TABLE, my_team=5, league_wide=True)
    assert opts[0] == 5, opts


def test_c_own_team_is_offered_even_with_nothing_tracked():
    """A coach gets their own program on the picker whatever its state — the
    point is that they then read the real reason instead of a filtered-out
    silence."""
    opts = LP.pickable_teams(ORDER, TABLE, my_team=2, league_wide=True)
    assert opts[0] == 2, opts
    assert set(opts) == {2, 3, 5}, opts


def test_d_a_solo_coach_gets_only_their_own_team():
    """Unchanged behaviour, asserted so the filter above cannot quietly widen
    what a Solo coach sees."""
    assert LP.pickable_teams(ORDER, TABLE, my_team=2, league_wide=False) == [2]


def test_e_a_solo_coach_with_no_team_gets_nothing():
    assert LP.pickable_teams(ORDER, TABLE, my_team=None,
                             league_wide=False) == []


def test_f_a_team_outside_the_rank_order_is_not_invented():
    """`order` is the rated pool. A team_id that is not in it has no rank and
    no row, so it cannot be offered."""
    opts = LP.pickable_teams(ORDER, TABLE, my_team=99, league_wide=True)
    assert 99 not in opts, opts


def test_g_the_ranked_order_survives_the_filter():
    table = {i: {"team_id": t} for i, t in enumerate([5, 3, 4])}
    opts = LP.pickable_teams(ORDER, table, my_team=None, league_wide=True)
    assert opts == [3, 4, 5], f"lost the rank ordering: {opts}"


# ── the copy the coach reads when their own team is the empty one ────────────

def test_h_the_zero_game_message_states_the_requirement():
    """Not "track a game for them first" — a coach cannot track another
    program, and for their own team the number is the useful part."""
    msg = LP.no_rotation_reason(0)
    assert str(LP.MIN_TEAM_GAMES) in msg, msg
    assert "none tracked" in msg.lower(), msg


def test_i_the_partial_book_message_still_carries_the_count():
    msg = LP.no_rotation_reason(3)
    assert "3" in msg and str(LP.MIN_TEAM_GAMES) in msg, msg
