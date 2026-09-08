"""The player card's passing read was gated on an opt-in tag.

THE BOOK §12.5 said `passing_chains` drops every row without a hockey tag.
At the MODULE level that is wrong, and the correction matters more than the
finding: `connection_matrix` reads only `pass_from_id`, needs no hockey tag,
and has been the engine behind the team Connection Matrix on Charts → Offense
→ Playmaking for months. The 2-node graph was never missing.

It was right about the PLAYER CARD. That surface rendered "Who they ignite"
behind `P.get("PotHAST")` and had no other passing block, so a player's
passing read existed only if someone had pressed an optional tag on their
shots. Measured on the production snapshot:

    shots carrying a plain pass_from_id      3,957
    shots carrying the hockey tag              317
    players clearing the 4-feed edge bar        100
    ...of those, with no hockey chain at all     36   -> the card showed nothing
    biggest feeder: 222 feeds, 8 tagged chains        -> the card showed the 8

This file lives apart from test_passing_chains.py deliberately. That file is
script-style — its assertions run at import under a `Run: python tracker/...`
contract — and adding a module-level `def test_*` to it flips
`_test_kinds.is_script_style` and silently moves it out of run_all.py.

Run: python -m pytest tracker/test_player_card_passing.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.passing_chains as PC                    # noqa: E402


def test_the_card_leads_with_the_graph_that_needs_no_tag():
    card = (_APP / "helpers" / "dashboard" / "player_card.py").read_text(
        encoding="utf-8")
    i_feed = card.find('"**Who they feed**')
    i_ignite = card.find('"**Who they ignite**')
    assert i_feed > 0, "the card stopped showing the 2-node feed graph"
    assert i_ignite > 0, "…or dropped the hockey chains that enrich it"
    assert i_feed < i_ignite, \
        "the always-available graph has to lead; the tagged one is the extra"

    # and the feed table must not sit inside the PotHAST gate — that gate IS
    # the bug, and re-nesting the block would restore it with nothing failing
    gate = card.find('if paid and P.get("PotHAST")')
    assert gate > i_feed, "the feed table is back behind the hockey-tag gate"


def test_the_card_quotes_the_engines_own_edge_floor():
    """The caption prints a number a coach uses to read the table, so it has
    to be the number the engine applied, not a copy of it."""
    card = (_APP / "helpers" / "dashboard" / "player_card.py").read_text(
        encoding="utf-8")
    assert "MIN_EDGE_FEEDS as _PC_MIN_FEEDS" in card
    assert "{_PC_MIN_FEEDS} feeds to draw" in card


def test_connection_matrix_needs_no_hockey_tag():
    """The engine half of the correction, held directly: no row here carries
    `hockey_from_id` at all and the graph is still complete."""
    shots = [{"event_type": "shot", "pass_from_id": 1, "primary_player_id": 2,
              "shot_created_by_id": None, "guarded_by_id": None,
              "shot_type": 2, "shot_result": "make", "x": 0.0, "y": 1.0}
             for _ in range(PC.MIN_EDGE_FEEDS)]
    assert all("hockey_from_id" not in s for s in shots)
    rows = PC.connection_matrix(events=shots, team_of={1: 9, 2: 9}, rates={})
    assert len(rows) == 1
    assert rows[0]["passer"] == 1 and rows[0]["shooter"] == 2
    assert rows[0]["feeds"] == PC.MIN_EDGE_FEEDS


def test_thin_edges_are_not_drawn():
    shots = [{"event_type": "shot", "pass_from_id": 1, "primary_player_id": 2,
              "shot_created_by_id": None, "guarded_by_id": None,
              "shot_type": 2, "shot_result": "miss", "x": 0.0, "y": 1.0}
             for _ in range(PC.MIN_EDGE_FEEDS - 1)]
    assert PC.connection_matrix(events=shots, team_of={1: 9, 2: 9},
                                rates={}) == []
