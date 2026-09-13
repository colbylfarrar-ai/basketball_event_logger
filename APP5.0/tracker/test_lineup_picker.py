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
    assert 2 in opts, opts
    assert set(opts) == {2, 3, 5}, opts


# ── THE LANDING, which is a different question from THE LIST ─────────────────
#
# The day-one bug (measured 2026-09-13, tools/dayone_read.py) came from those
# two questions sharing one answer. "Own team first" was written so the picker
# would OPEN on the coach's own program — the comment says so — and a Streamlit
# selectbox opens on index 0, so list position WAS the landing. On day one, own
# team rated but ZERO tracked games, that meant the War Room opened the Creator
# on a team with no tracked players and rendered an empty state while every
# tracked team in the league sat one click away in the same dropdown. It is the
# headline paid page and it showed a brand-new coach nothing at all.
#
# So the list keeps its rule (own team first, always — a coach is entitled to
# their own program and it stays where they can find it) and the LANDING becomes
# its own function that the call sites pass as `index=`.


def test_c2_the_list_still_puts_an_empty_own_team_first():
    """Unchanged, and asserted here so the landing fix cannot be mistaken for
    permission to demote a coach's own program out of the list."""
    opts = LP.pickable_teams(ORDER, TABLE, my_team=2, league_wide=True)
    assert opts[0] == 2, opts
    assert set(opts) == {2, 3, 5}, opts


def test_c3_the_picker_does_not_LAND_on_an_empty_own_team():
    """THE DAY-ONE FIX. Team 2 leads the list and cannot build anything, so the
    page must open somewhere that can."""
    opts = LP.pickable_teams(ORDER, TABLE, my_team=2, league_wide=True)
    i = LP.default_pick_index(opts, TABLE, my_team=2)
    assert opts[i] != 2, (
        "still opens on an own team with no tracked data behind it — this is "
        "the day-one empty War Room")
    assert opts[i] in {3, 5}, f"landed on a team with nothing tracked: {opts[i]}"


def test_c4_the_picker_lands_on_the_own_team_when_it_HAS_data():
    """A coach with a book opens on their own team, which is the whole point of
    the original rule and must survive the fix."""
    opts = LP.pickable_teams(ORDER, TABLE, my_team=5, league_wide=True)
    i = LP.default_pick_index(opts, TABLE, my_team=5)
    assert opts[i] == 5, opts


def test_c5_the_picker_lands_on_the_own_team_when_NOBODY_has_data():
    """An empty league is not a reason to send a coach to a stranger's team.
    With nothing tracked anywhere their own program is the right landing and
    the page's own message is the honest one."""
    opts = LP.pickable_teams(ORDER, {}, my_team=2, league_wide=True)
    i = LP.default_pick_index(opts, {}, my_team=2)
    assert opts[i] == 2, opts


def test_c6_the_landing_is_the_first_tracked_team_when_there_is_no_own_team():
    """Admins and unassigned coaches. `pickable_teams` already filters to
    tracked teams for them, so index 0 is correct and must stay correct."""
    opts = LP.pickable_teams(ORDER, TABLE, my_team=None, league_wide=True)
    assert LP.default_pick_index(opts, TABLE, my_team=None) == 0, opts


def test_c7_the_landing_is_in_range_for_every_shape():
    """The index is fed straight to st.selectbox, where an out-of-range value
    raises rather than degrading. Cheap to assert, expensive to discover."""
    for my_team in (None, 1, 2, 3, 4, 5, 99):
        for table in (TABLE, {}):
            opts = LP.pickable_teams(ORDER, table, my_team=my_team,
                                     league_wide=True)
            i = LP.default_pick_index(opts, table, my_team=my_team)
            assert isinstance(i, int) and 0 <= i < max(len(opts), 1), (
                my_team, table and "TABLE" or "{}", opts, i)


def test_c8_an_empty_option_list_still_answers_zero():
    """A Solo coach with no team gets `[]` from the picker. The caller checks
    that before rendering, but the index must not raise on the way there."""
    assert LP.default_pick_index([], TABLE, my_team=None) == 0


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


# ── the page resolves "league-wide" ONCE, or it answers it twice ─────────────

def test_j_the_war_room_resolves_league_wide_exactly_once():
    """A PAST season is an open archive, and the War Room decides that at the
    top of the page:

        _wr_league_wide = True if not _is_cur_season else viewer_is_league_wide(...)

    The Lineup Creator re-resolved it with a bare `ENT.viewer_is_league_wide`
    and so never learned about the archive. The result was two pickers on one
    page answering the same question differently: Rotation optimizer and
    Compare offered every tracked team on an archived season while the Creator
    — the sub-view that opens by default — offered a solo coach only their own.
    On day one that team has nothing tracked, so the headline paid page rendered
    an empty state with the whole league one click away.

    This is the same defect `entitlement.paid_or_open_archive` was written to
    kill: three page-level stops called `has_paid_plan` bare and hard-stopped
    Free on a past season. This was a fourth site, one level down.

    Static, because the failure is invisible at runtime until somebody opens an
    archived season as a solo coach, which is nobody until October.
    """
    src = (_APP / "pages" / "9_War_Room.py").read_text(encoding="utf-8")
    calls = [ln.strip() for ln in src.splitlines()
             if "viewer_is_league_wide(" in ln and not ln.strip().startswith("#")]
    assert len(calls) == 1, (
        "the War Room resolves league-wide in more than one place; every "
        "consumer must read `_wr_league_wide`, which is the only one that "
        "knows a past season is an open archive:\n  " + "\n  ".join(calls))
    assert calls[0].startswith("_wr_league_wide ="), calls
