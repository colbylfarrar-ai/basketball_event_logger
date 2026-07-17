"""
scheme_section.py — the shared "when does a look spike" section.

Rendered by BOTH Team Dashboard super-tabs off one engine
(helpers/scheme_situational):
  • defense_tab   side='defense'  → the schemes they GO TO
  • playstyle_tab side='offense'  → the sets they CALL

It lives in its own module rather than in either tab because both need it and a
sibling tab importing the other for a renderer is the wrong shape.

Pure renderer, same contract as the tabs: everything heavy arrives via the
page-cached ``ctx.scheme_sit`` callable, so caching stays on the page.
"""
from __future__ import annotations

import re as _re

import streamlit as st

from helpers.cards import verdict_card


def _md_bold(text):
    """`**x**` -> `<b>x</b>`. The engines speak markdown; verdict_card takes HTML."""
    return _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def render(ctx, side, header, blurb):
    """The verdict-first spike section for one side of the ball.

    Self-gating: a ctx with no ``scheme_sit`` (an older call site) renders
    nothing rather than raising, and a team without a real tagged baseline gets
    the honest "not enough yet" line instead of invented tendencies.
    """
    fn = getattr(ctx, "scheme_sit", None)
    if fn is None:
        return
    try:
        res = fn(ctx.gender, ctx.team_id, side)
    except Exception:
        return

    st.markdown(f"<div class='pl-hdr'>{header}</div>", unsafe_allow_html=True)
    st.caption(blurb)

    if not res.get("available"):
        st.caption("Needs a real tagged baseline before a spike means anything — "
                   "fills in as games get tagged.")
        return

    import helpers.scheme_situational as SS
    lines = SS.verdict_lines(res)
    if not lines:
        # "Nothing spiked" is a real finding, not an empty state — say so rather
        # than leaving a blank panel that reads like a bug.
        st.caption(
            f"Nothing unusual: across {res['base_poss']} tagged possessions the "
            "mix holds steady in every situation — no look moves far enough off "
            "the season baseline to call it a tendency. That's an answer, not a "
            "gap.")
        return

    st.markdown(
        verdict_card([("Tendency", l["cut_poss"], _md_bold(l["text"]))
                      for l in lines]),
        unsafe_allow_html=True)
    st.caption(
        f"Measured against this team's OWN {res['base_poss']}-possession season "
        "baseline, not the league's — the read is “more than they normally do”. "
        f"A situation needs {SS.MIN_CUT_POSS}+ possessions and a "
        f"{SS.MIN_DELTA * 100:.0f}-point gap off that baseline to show up here, "
        "so a one-night quirk stays out.")
