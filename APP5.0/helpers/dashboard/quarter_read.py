"""
quarter_read.py — the quarter story as sentences, rendered once.

`helpers/quarters.py` writes the axis as prose (which period decides the games,
whether the halves disagree, which quarter this team plays at a different
tempo). TWO surfaces want that prose and they want it identically:

  * Insights -> Who we are -> "The quarters"
  * Charts -> Quarters, above the panels that are its evidence

Before this module the Insights copy existed and the Charts copy did not, which
is how the tab whose entire subject is the quarter axis came to render 35 plots
without a sentence over them. A second copy was the obvious fix and the wrong
one: two renderers of one engine drift, and the caption here carries a
reliability disclosure that must never be true on one screen and absent on the
other.

Pure renderer — the caller hands in the lines `quarters.quarter_reads` already
produced, so caching stays where the caller put it.
"""
from __future__ import annotations

import streamlit as st

from helpers.cards import verdict_card, md_bold

#: The badge names the CUT, because the lines do not share a unit: the scoring
#: lines are points a game and the tempo line is possessions a game.
_TAG = {"quarter": "Quarter", "half": "Halves", "pace": "Tempo"}

#: Said under every rendering of this read, on every surface. Two things are
#: load-bearing: the units differ line to line, and ONE of the three cuts is a
#: measured tendency while the ones a coach most expects to see ("they shoot
#: better in the second half") were measured and refused.
CAPTION = (
    "Scoring lines are points per game, not per possession; the tempo line is "
    "possessions per game against this team's own other quarters, measured per "
    "game so one loose night cannot become a habit. Each line carries the "
    "number of tracked games behind it. Overtime is deliberately excluded — an "
    "OT “tendency” drawn from two games is a coin flip wearing a "
    "verdict's clothes. Tempo is the one quarter read that repeats (SB .596); "
    "quarter shooting (SB −.135) and quarter ball security (SB +.082) "
    "were measured and refused — see reliability.THE QUARTER AXIS."
)

#: What to say when the engine returns nothing. "Level" is a finding, not an
#: empty state, and saying so is the difference between an answer and a panel
#: that reads like a bug.
LEVEL = (
    "Nothing moves: no quarter sits far enough off level to call it a pattern, "
    "and the halves agree. That is an answer, not a gap — this team is the "
    "same team for 32 minutes."
)


def render(lines, *, caption=True):
    """Render `quarters.quarter_reads(...)` output. Returns True if it spoke."""
    if not lines:
        st.caption(LEVEL)
        return False
    st.markdown(
        verdict_card([(_TAG.get(l.get("cut"), "Quarter"), l.get("n"),
                       md_bold(l["text"])) for l in lines]),
        unsafe_allow_html=True)
    if caption:
        st.caption(CAPTION)
    return True
