"""
rebound_map.py — "where do the boards come from" court, split by set call / scheme.

A rebound is logged against the SHOT it came off, so a missed attempt's location
is also the board's origin. Plotting missed shots on the half court and colouring
them by who got the board answers the question neither the ORB%/DRB% rates nor
the shot chart can: *which of our sets actually get us second chances, and which
of their looks we finish the defensive possession on.*

Rendered by both Team Dashboard super-tabs off one renderer:
  • playstyle_tab → grouped by the set call (play_type)
  • defense_tab   → grouped by the scheme (defense)

Only MISSED shots appear: a make has no rebound, so including makes would plot
points that can never be boards.

Pure renderer — shots arrive from the page-cached located_* callables.
"""
from __future__ import annotations

import streamlit as st

import helpers.court as court
from helpers.ui import seg


def _reb_shots(shots, want_off):
    """Missed shots whose board went the way we're asking about.

    `reb_off` is True for an offensive board, False for a defensive one, None
    when no rebounder was logged — those drop out rather than being guessed onto
    one side.
    """
    return [s for s in shots
            if not s.get("make") and s.get("reb_off") is want_off]


def render(shots, group_key, labels, *, unit, own_side, key_prefix):
    """The rebound court for one side of the ball.

    shots      located shots for this side (own attempts, or attempts allowed)
    group_key  "play_type" or "defense" — what the colour encodes
    labels     {key: label} for that dimension
    unit       word for the dimension in prose ("set call" / "scheme")
    own_side   True when `shots` are the team's OWN attempts. Decides what an
               offensive board MEANS: on our shots it's our second chance, on
               shots we allowed it's the board we surrendered.
    """
    st.markdown(f"<div class='pl-hdr'>Where the boards come from — by {unit}</div>",
                unsafe_allow_html=True)
    st.caption(
        f"Every MISSED attempt, placed where it went up and coloured by {unit}. "
        "A rebound is logged against the shot it came off, so a miss's spot is "
        "also the board's origin — this is the read ORB%/DRB% can't give: which "
        f"{unit}s actually produce second chances, and from where. Makes are "
        "excluded (a make has no board).")

    if not shots:
        st.caption("No tap-located shots for this side yet — tap shot spots in "
                   "the Game Tracker to unlock the court.")
        return

    if own_side:
        opts = ["Our offensive boards", "Their defensive boards"]
        blurbs = ["Our misses we rebounded — the second chances this "
                  f"{unit} creates.",
                  f"Our misses THEY rebounded — the {unit}s that end our "
                  "possession for good."]
    else:
        opts = ["Their offensive boards", "Our defensive boards"]
        blurbs = [f"Their misses THEY rebounded — the {unit}s giving up second "
                  "chances.",
                  f"Their misses we rebounded — the {unit}s we close out on."]
    pick = seg("Board", opts, key=f"{key_prefix}_reb_side") or opts[0]
    want_off = pick == opts[0]

    sel = _reb_shots(shots, want_off)
    if not sel:
        n_noreb = sum(1 for s in shots
                      if not s.get("make") and s.get("reb_off") is None)
        st.caption(
            "No boards of this kind logged on located shots yet."
            + (f" ({n_noreb} located miss(es) carry no rebounder — log the "
               "rebounder in the tracker and they'll appear.)" if n_noreb else ""))
        return

    st.caption(blurbs[0] if want_off else blurbs[1])
    # Every point here is a miss, so shot_map_grouped's make/miss encoding
    # (filled vs open) carries no information — they all render open, one colour
    # per group, which is the encoding that matters on this court.
    fig, _n = court.shot_map_grouped(
        sel, group_key=group_key, labels=labels,
        title=f"{pick} — {len(sel)} boards, by {unit}")
    st.plotly_chart(fig, width="stretch", key=f"{key_prefix}_reb_court")

    # which unit produced the most boards — the takeaway under the picture
    tally = {}
    for s in sel:
        tally[s.get(group_key)] = tally.get(s.get(group_key), 0) + 1
    ranked = sorted(tally.items(), key=lambda kv: -kv[1])
    named = [(k, v) for k, v in ranked if k]
    if named:
        bits = " · ".join(f"{labels.get(k, k)} {v}" for k, v in named[:5])
        st.caption(f"Most boards by {unit}: {bits}."
                   + (f" {tally.get(None, 0)} came off untagged possessions."
                      if tally.get(None) else ""))
