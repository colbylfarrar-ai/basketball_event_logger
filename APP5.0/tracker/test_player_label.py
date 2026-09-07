"""A jersey number is not a person's name.

The Players page's superlative row prints `ld[0]['name']` raw, and production
carries scouted players whose `name` IS their jersey number — nobody typed a
name because nobody knew it. So the league leaderboard reads

    REBOUNDING   80.7
    12 · rebounding rate

and a coach is asked to believe that a player called "12" leads the league. The
sweep filed this under honesty, and it is the one class that does NOT fix
itself: scouting will keep producing players nobody has a book for.

The mirror failure is the label built the other way. Thirty-odd sites write
`f"#{number} {name}"`, which on the same row renders **`#12 12`**.

One helper answers both, and the shape the book specified is:

    a real name          ->  "#12 Harper Willis"   (or "Harper Willis")
    a placeholder name   ->  "#12 · Kansas Girls"  (number + team, never bare)

It lives in helpers/stats.py because it is a pure formatter with no Streamlit
in it — the engine renders labels too (scout sheets, printable reports), and a
helper the engine cannot import is a helper that gets copy-pasted.

Run: python -m pytest tracker/test_player_label.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.stats as S                              # noqa: E402


# ── the real-name path, which must not get worse ─────────────────────────────

def test_a_real_name_keeps_its_number():
    assert S.player_label({"name": "Harper Willis", "number": 12}) \
        == "#12 Harper Willis"


def test_b_number_can_be_suppressed():
    """Chart tick labels and prose lines want the name alone."""
    assert S.player_label({"name": "Harper Willis", "number": 12},
                          number=False) == "Harper Willis"


def test_c_a_real_name_without_a_number_is_just_the_name():
    assert S.player_label({"name": "Harper Willis", "number": None}) \
        == "Harper Willis"


# ── the finding ──────────────────────────────────────────────────────────────

def test_d_a_naked_jersey_number_never_renders_as_a_name():
    """The superlative bug. The label must not be the bare integer."""
    out = S.player_label({"name": "12", "number": 12}, team="Kansas Girls")
    assert out == "#12 · Kansas Girls", out
    assert out != "12"


def test_e_no_number_doubled_onto_itself():
    """The `f"#{number} {name}"` mirror: never `#12 12`."""
    out = S.player_label({"name": "12", "number": 12})
    assert "12 12" not in out, out
    assert out == "#12"


def test_f_the_number_field_wins_when_the_two_disagree():
    """A name of "12" on a row whose jersey is 5 is a stale scrape, and the
    jersey column is the one a coach can check against a roster."""
    assert S.player_label({"name": "12", "number": 5}, team="Kansas Girls") \
        == "#5 · Kansas Girls"


def test_g_an_empty_name_is_a_placeholder_too():
    assert S.player_label({"name": "", "number": 7}, team="Adair Girls") \
        == "#7 · Adair Girls"
    assert S.player_label({"name": None, "number": 7}) == "#7"


def test_h_unknown_n_is_the_same_class():
    """Production already emits `Unknown 7`; it is a placeholder wearing a
    different coat and belongs on the same path."""
    assert S.player_label({"name": "Unknown 7", "number": 7},
                          team="Adair Girls") == "#7 · Adair Girls"


def test_i_a_row_carrying_its_own_team_needs_no_argument():
    for key in ("team", "team_name"):
        assert S.player_label({"name": "12", "number": 12, key: "Kansas Girls"}) \
            == "#12 · Kansas Girls"


def test_i2_a_caller_that_prints_the_team_itself_can_suppress_it():
    """Several leaderboards render `#3  <player>  ·  Kansas Girls`. Left to
    itself the label would put Kansas Girls in there twice."""
    row = {"name": "12", "number": 12, "team": "Kansas Girls"}
    assert S.player_label(row, team="") == "#12"


def test_j_nothing_at_all_still_returns_something_renderable():
    """No name, no number, no team. The label is still not blank and still not
    a lie — a blank cell in a leaderboard reads as a bug."""
    out = S.player_label({})
    assert out and out.strip(), "returned an empty label"
    assert not out.strip().isdigit()
