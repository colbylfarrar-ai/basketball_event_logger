"""A superlative has to be supported by the thing it is a superlative about. (B1)

THE BOOK §10 rule 2: "elite" must require a rate that is elite, not first in a
five-team sample. Two sites, two different ways of failing it, both measured on
the production snapshot before this file was written.

**The glass read** (`insights._g_rebound`) gates on the player's TOTAL rebounds —
`tier_gate(12, gp, 5)` over OREB + DREB — and then fires on whichever SIDE has
the larger deviation. So a player can clear the gate on defensive boards and be
called "elite on the offensive glass" on two of them. Production, girls:

    side=def  DREB=3   GP=2   ->  "Closes possessions — elite on the defensive glass"
    side=def  DREB=4   GP=2   ->  same
    side=off  OREB=3   GP=3   ->  "Second-chance machine — elite on the offensive glass"

Three rebounds is not a rebounding identity. The evidence in the sentence's own
parenthesis contradicts the sentence.

**The glance strip** (`insights_team.team_glance`) tags on `pct >= 50`, so the
MEDIAN team gets the high tag. Production, Sequoyah Boys over a ten-team pool:

    ORtg  95.9  pct 50  dist 0.0  ->  "high-powered offense"
    DRtg  92.0  pct 60  dist 10   ->  "elite defense"

A team sitting exactly on the median is being told it has a high-powered
offense, on a screen whose heading is "the stats this team is MOST distinctive
on". That is not a thin-sample problem, it is the absence of any distinctiveness
requirement at all.

Neither fix invents a constant. The glass read applies the gate that already
exists to the quantity the sentence is actually about; the glance requires real
distance from the middle before any tag fires. Where an ABSOLUTE basketball
anchor would be needed — what DRtg is elite in points per 100 rather than
against 22 tracked teams — none is set here, deliberately: that is a measured
constant and the recal gates own it.

Run: python -m pytest tracker/test_superlative_gates.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.insights as IN                          # noqa: E402
import helpers.insights_team as IT                     # noqa: E402


# ── the glass read ────────────────────────────────────────────────────────────
#: (mean, sd) in the shape `insights._pool` returns.
_POOLS = {"OREBrtg": (5.0, 2.0), "DREBrtg": (12.0, 3.0)}


def _row(**kw):
    """A player-table row with a rebounding profile that clears every gate, so
    each test only has to move the one field it is about."""
    base = {"GP": 20, "OREB": 60, "DREB": 120, "OREB/G": 3.0, "DREB/G": 6.0,
            "OREBrtg": 5.0, "DREBrtg": 12.0}
    base.update(kw)
    return base


def test_the_offensive_glass_claim_needs_offensive_rebounds():
    """A player whose TOTAL rebounds clear the gate on defensive boards must not
    be called elite on the OFFENSIVE glass off three of them."""
    row = _row(OREB=3, DREB=120, OREBrtg=11.0)   # a huge rate on no volume
    row["OREB/G"] = 0.15
    assert IN._g_rebound(row, _POOLS, {}) is None, (
        "three offensive rebounds produced an offensive-glass identity")


def test_the_defensive_glass_claim_needs_defensive_rebounds():
    """The mirror. Two games and three defensive boards is not 'closes
    possessions'."""
    row = _row(GP=2, OREB=60, DREB=3, DREBrtg=20.0)
    row["DREB/G"] = 1.5
    assert IN._g_rebound(row, _POOLS, {}) is None, (
        "three defensive rebounds produced a defensive-glass identity")


def test_a_real_rebounder_still_gets_the_read():
    """The gate must not swallow the players it exists to find — the whole read
    is worth having, and a fix that silences it is not a fix."""
    row = _row(OREB=73, DREB=108, GP=26, OREBrtg=11.0)
    row["OREB/G"] = 2.81
    out = IN._g_rebound(row, _POOLS, {})
    assert out is not None and out["side"] == "off", out
    assert "offensive glass" in out["text"]


# ── the glance strip ──────────────────────────────────────────────────────────
def test_the_median_team_is_not_distinctive_at_anything():
    """`pct == 50` is the definition of unremarkable, and the strip's own
    heading promises the opposite."""
    assert IT.MIN_GLANCE_DIST > 0
    assert not IT._glance_tag(50, "high-powered offense", "offense struggles")


def test_a_tag_needs_real_distance_from_the_middle():
    """Sequoyah's 60th-percentile defence over ten tracked teams was reading as
    'elite defense'. Over ten teams the reachable percentiles are multiples of
    ten, so 60th is fourth — a tag it cannot carry."""
    assert not IT._glance_tag(60, "elite defense", "leaky defense")
    assert not IT._glance_tag(40, "elite defense", "leaky defense")
    assert IT._glance_tag(91, "elite defense", "leaky defense") == "elite defense"
    assert IT._glance_tag(9, "elite defense", "leaky defense") == "leaky defense"


def test_the_glance_item_carries_the_pool_it_was_ranked_against():
    """Q6 — disclose. A tag over 22 tracked teams and one over 748 are different
    claims, and the renderer cannot say so unless the item says so."""
    import inspect
    src = inspect.getsource(IT.team_glance)
    assert '"pool_n"' in src, (
        "team_glance does not carry the pool size out, so no renderer can state "
        "it")
