"""
scoutboard.py — opponent game-plan notes, saved per team (scout_notes table).

(A play-drawing canvas was tried but streamlit-drawable-canvas is incompatible
with the installed Streamlit — left out; notes only.) UI helper.
"""
from __future__ import annotations

import streamlit as st

from database.db import query, execute


def render_notes(team_id, key_prefix="sn"):
    """Per-team game-plan notes (scout_notes), saved in place."""
    cur = query("SELECT notes FROM scout_notes WHERE team_id=?", (team_id,))
    val = cur[0]["notes"] if cur else ""
    new = st.text_area(
        "Game-plan notes", value=val, height=200, key=f"{key_prefix}_{team_id}",
        placeholder="Coverages, ATO / BLOB / SLOB calls, who to deny, press break, "
                    "special situations, late-game fouling…")
    if st.button("Save notes", key=f"{key_prefix}_save_{team_id}"):
        execute(
            "INSERT INTO scout_notes (team_id, notes) VALUES (?,?) "
            "ON CONFLICT(team_id) DO UPDATE SET notes=excluded.notes",
            (team_id, new))
        st.success("Notes saved.")
