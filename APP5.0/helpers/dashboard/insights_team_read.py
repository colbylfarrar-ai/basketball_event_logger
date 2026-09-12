"""
insights_team_read.py — the whole team's read, in one block.

The founder's ask: *"coaches want to look in one place and get a full read of
insights on the entire team with tendencies."* That sentence hides two different
problems, and only one of them is a consolidation.

**The consolidation.** The team miner (helpers/team_insights.py, 24 generators)
already runs on every Insights render and its lines already reach the tab — but
`insights_severity.METRIC_SECTION` routes each one by metric, so the team story
is split across "Who we are", "Why we win / why we lose" and "What they'll take
away". No screen held it whole.

**The gap.** The two examples given were not consolidation problems at all.
"Plays zone against a BLOB" is `scheme_situational`, which uses the founder's own
phrasing in its docstring and rendered only on the Team Dashboard — Insights had
never seen it. "Runs man more in the 4th" was not computable anywhere until the
quarter cut was added to that engine. And quarter reads were the single largest
content gap on this view: Charts → Quarters has four sub-tabs, Insights had none.

Lives in "Who we are" rather than "Who's helping", where the ask put it, because
the sections are cut by the QUESTION a coach asks and "what kind of team is
this" is already section 1's question. "Who's helping" is the player section by
authored design.

Pure renderer. Everything heavy arrives through ctx callables so caching stays
on the page, the same contract the Team Dashboard tabs use.
"""
from __future__ import annotations


import streamlit as st

from helpers.cards import verdict_card, md_bold as _CARDS_md_bold
from helpers.dashboard import insights_brief as BR
from helpers.dashboard import scheme_section as SCHEME
from helpers.dashboard import quarter_read as QREAD
import helpers.insights_severity as SEV
import helpers.stats as _STATS


#: `**x**` -> `<b>x</b>` — one copy, beside the `verdict_card` that
#: needs it (helpers/cards.py). Do not re-add a private one.
_md_bold = _CARDS_md_bold


def _tendencies(ctx):
    """Both sides of the "when does a look spike" read.

    `scheme_section.render` is reused rather than reimplemented — it is already
    the shared renderer for this engine on two Team Dashboard tabs, it
    self-gates on a missing ctx callable, and it says "nothing spiked" in words
    instead of leaving a blank panel that reads like a bug.
    """
    if getattr(ctx, "scheme_sit", None) is None:
        return
    # The deck's game-window control is a CACHE-KEY input on every other wrapper
    # in this tab, so it is one here too. `as_scope` rather than
    # `tuple(...) or None`: an empty visible set means this viewer may see NO
    # games, and collapsing it to None hands them the unrestricted pool. The
    # sibling `_ins_quarter_read` guards the same way by returning early.
    gids = _STATS.as_scope(getattr(ctx, "tracked_ids", ()) or ())
    if not gids:
        st.caption("No visible tracked games in this window.")
        return
    SCHEME.render(
        ctx, "defense", "Tendencies — the schemes we go to",
        "Where this team's defensive scheme usage spikes off its OWN season "
        "baseline: the zone it goes to on a run, what it sits in on a BLOB, "
        "what it plays in the 4th. Measured against itself, so the read is "
        "“more than they normally do”.", game_ids=gids)
    SCHEME.render(
        ctx, "offense", "Tendencies — the sets we call",
        "The same cut on our own possessions: which sets get called when the "
        "game state changes. This is the half an opposing staff would write "
        "down about us.", game_ids=gids)


def _quarters(ctx):
    """The quarter story, as sentences rather than as the Charts panels."""
    fn = getattr(ctx, "quarter_read", None)
    if fn is None:
        return
    try:
        lines = fn(ctx.gender, ctx.team_id)
    except Exception as exc:
        st.caption(f"Quarter read unavailable — {type(exc).__name__}: {exc}")
        return

    BR._hdr("The quarters",
            "Which period actually decides these games. The full per-quarter "
            "splits — shooting, efficiency, the four factors — stay on "
            "Charts → Quarters; this is what they add up to.")
    # One renderer, shared with Charts → Quarters (which puts the same
    # sentences above the panels that are their evidence). The caption
    # carries the reliability disclosure, so it must not be able to be
    # true on one of the two screens and absent on the other.
    QREAD.render(lines)


def _rollup(findings):
    """Every other team-level read, gathered from the sections that own them.

    Deliberately NOT the team lines whose home is this section — those render in
    "Who we are"'s own feed a few blocks down, and printing the same sentence
    twice on one screen is how a coach learns to skim.

    Each line names the section holding its evidence, so this is a table of
    contents for the team story rather than a replacement for it.
    """
    rows = [f for f in (findings or [])
            if f.get("family") == "team"
            and f.get("section") != SEV.S_IDENTITY]
    if not rows:
        return
    BR._hdr(f"The rest of the team read — {len(rows)}",
            "Team-level findings that live in other sections, gathered here so "
            "the whole team story is on one screen. Each says where its "
            "evidence is.")
    BR.grid([BR.block(
        str(f.get("metric") or "Read"),
        n=SEV.SECTION_LABELS.get(f.get("section")),
        lines=[(SEV.pts_chip(f.get("pts")) if f.get("pts") is not None
                else SEV.r_chip(f),
                _md_bold(f.get("text") or ""))])
        for f in rows], cols=3)


def render(ctx, *, findings=None):
    """The team read block — tendencies, quarters, and everything else we know.

    Self-gating throughout: a ctx without the engine callables renders the parts
    it can and stays silent about the rest, so an older call site degrades
    instead of raising.
    """
    BR._hdr("The team read",
            "What this team does, in one place — the tendencies an opposing "
            "staff would chart, the quarter it wins or loses, and every other "
            "team-level finding the app has, with its evidence named.")
    _tendencies(ctx)
    _quarters(ctx)
    _rollup(findings)
