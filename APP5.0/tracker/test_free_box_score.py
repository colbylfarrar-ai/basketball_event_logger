"""The box score is Free, and there is one list that says what "box" means. (B2)

`entitlement.py`'s first sentence is "Box score + final results are Free and
visible to everyone, always." `render_box_score` did not do that: it gated at the
scoreboard and returned, so a Free coach on a current-season tracked game got a
final score and a padlock where the box score should be — the one artefact every
coach already understands, on the app you are recruiting them with.

THE BOOK §12.2 asks for three stages instead of one gate:

    hero    scoreboard, date, venue, FINAL                     always
    BOX     per-player counting lines, team totals, shooting %,
            quarter scores, the shooting four-factor terms     always (Free)
    DEPTH   everything below the old gate                      Paid

What decides the split is not taste. `player_ratings.EVENT_DERIVED_STATS`
already carries the rule at PLAYER level — a key is Paid when it cannot be
computed from a final score plus a manually kept box line, plus the owner's
possession carve-out (2026-06-15) that makes any per-possession rate Paid even
when its inputs are box stats. That set already answers the three columns this
split turns on: MIN, +/- and SC are event-derived and Paid; eFG%, TS% and GS are
named in its comment as staying Free.

The TEAM-level equivalent did not exist, which is why the team half of every
gate decision has been made by hand at each site. `TEAM_EVENT_DERIVED` is that
list, and it lives next to its sibling so the two cannot drift.

Run: python -m pytest tracker/test_free_box_score.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.player_ratings as PR                     # noqa: E402


def test_the_possession_family_is_paid_at_team_level_too():
    """The owner's possession carve-out, applied to the team keys. Anything per
    possession or per 100 is Paid even though its box inputs are Free."""
    for key in ("ORtg", "DRtg", "NetRtg", "Pace", "Poss/G", "PPP", "Opp PPP"):
        assert key in PR.TEAM_EVENT_DERIVED, key


def test_the_tap_captured_family_is_paid_at_team_level_too():
    """Shot quality and location need the court tap, and the adjusted terms need
    the tracked league behind them."""
    for key in ("SMOE", "xPPS", "ShotRating", "Adj eFG%", "Adj Opp eFG%",
                "Paint pt%", "3PT pt%"):
        assert key in PR.TEAM_EVENT_DERIVED, key


def test_the_box_family_stays_free_at_team_level():
    """A coach with a scorebook can compute every one of these, so none of them
    is a thing to sell. eFG% and TS% are the shooting four-factor terms §12.2
    puts explicitly in the Free stage."""
    for key in ("FG%", "3P%", "FT%", "eFG%", "TS%", "PPS", "AST/G", "REB/G",
                "TOV/G", "PF/G", "AST/TO", "3PAr", "FTr", "W", "L", "MOV"):
        assert key not in PR.TEAM_EVENT_DERIVED, key


def test_the_two_lists_do_not_disagree_about_a_shared_key():
    """Several keys name the same quantity at both levels. A key that is Paid
    for a player and Free for their team is a leak with extra steps."""
    shared = set(PR.EVENT_DERIVED_STATS) & {
        "PPP", "TOV%", "REB%", "OREB%", "DREB%", "SMOE", "xPPS", "ShotRating"}
    for key in shared:
        assert key in PR.TEAM_EVENT_DERIVED, (
            f"{key!r} is Paid for a player and Free for a team")


def test_the_free_box_columns_are_the_box_ones():
    """The per-player Free table drops exactly the event-derived columns and
    keeps the counting line a scorebook already holds."""
    import helpers.box_score as BS
    free, full = set(BS.FREE_BOX_COLS), set(BS.BOX_COLS)
    assert free < full
    assert full - free == {"MIN", "+/-", "SC"}, full - free
    for key in ("PTS", "FG", "FG%", "3P", "FT", "ORB", "DRB", "REB", "AST",
                "STL", "BLK", "TOV", "PF", "eFG%", "TS%", "GS"):
        assert key in free, key


def test_no_free_box_column_is_gated_at_player_level():
    """The one rule, applied rather than restated. Every column the Free table
    keeps must be absent from EVENT_DERIVED_STATS — that is what makes this a
    single source of truth instead of a second opinion."""
    import helpers.box_score as BS
    # "#", "Player" and the paired "FG"/"3P"/"FT" make-attempt strings are
    # display shapes, not stat keys, so they are not in either list.
    _DISPLAY = {"#", "Player", "FG", "3P", "FT"}
    bad = [c for c in BS.FREE_BOX_COLS
           if c not in _DISPLAY and c in PR.EVENT_DERIVED_STATS]
    assert not bad, f"Free box columns that are Paid at player level: {bad}"
