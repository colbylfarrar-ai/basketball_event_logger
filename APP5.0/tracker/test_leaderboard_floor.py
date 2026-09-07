"""A leaderboard has to say what its floor is, and the floor cannot be one game.

On production **168 of 703 rated girls teams and 210 of 748 boys teams have
played exactly one game**; 223 and 266 respectively have fewer than five. The
Rankings page's `_MIN_GP` slider defaults to **1**, so four of the five
Team-leader cards and the top Signature card belonged to 1-0 teams — including
"Best defense (PA/G) 0.0", which is a forfeit.

The slider exists and is applied correctly everywhere. The DEFAULT is the bug.

Hall of Fame already does this right and does the other half too: it states the
floor in the heading — `min 10 games`, `min 25 games` — so a coach reading a
board knows what it is a board OF. That is the pattern §8.2 asks to be copied
onto Rankings and Players, and it is the same honesty rule as the percentile
pool: publish the sample beside the claim.

This asserts the shared default and the helper that renders the note, not the
Streamlit widgets — the pages are scripts, and a constant plus a formatter is
the part that can be wrong in a way a reader would not notice.

Run: python -m pytest tracker/test_leaderboard_floor.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.stats as S                              # noqa: E402


def test_a_the_default_floor_is_not_one_game():
    """Q5's ruling. One game is not a season, and a 1-0 team is not a leader."""
    assert S.LEADERBOARD_MIN_GP >= 5, S.LEADERBOARD_MIN_GP


def test_b_a_board_states_its_floor():
    note = S.floor_note(5)
    assert "5" in note, note
    assert "game" in note.lower(), note


def test_c_the_note_names_tracked_games_when_that_is_the_pool():
    """A tracked floor and a played floor are different claims — "min 5 games"
    over a tracked-only board would overstate what was measured."""
    note = S.floor_note(5, tracked=True)
    assert "tracked" in note.lower(), note


def test_d_a_floor_of_one_says_so_rather_than_pretending_to_be_a_gate():
    """A coach who drags the slider back to 1 is entitled to do that. The board
    must still disclose it, because "min 1 game" is the sentence that explains
    a 0.0 points-allowed leader."""
    note = S.floor_note(1)
    assert "1" in note, note


def test_e_the_note_is_a_fragment_a_heading_can_hold():
    """Rendered as `### Team leaders (min 5 games)` — so no leading capital, no
    trailing period, and it brings its own parentheses."""
    note = S.floor_note(5)
    assert note.startswith("(") and note.endswith(")"), note
    assert not note.endswith(".)"), note
