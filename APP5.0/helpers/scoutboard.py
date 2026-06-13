"""
scoutboard.py — PER-COACH notes (coach_notes table), private to each coach.

Two kinds share the table: 'team' (general team notes) and 'scout' (opponent
game-plan). Every coach sees ONLY their own notes for a team — no cross-coach
read or last-write-wins overwrite (the old global teams.notes / scout_notes leak).
The coach is resolved from the login identity (helpers.auth.current_user); with
auth off it's the single local owner ('' bucket). UI helper.
"""
from __future__ import annotations

import streamlit as st

from database.db import query, execute
import helpers.auth as AUTH


def _coach_email(email=None) -> str:
    if email is not None:
        return (email or "").strip().lower()
    try:
        return (AUTH.current_user().get("email") or "").strip().lower()
    except Exception:
        return ""


def get_note(team_id, kind="scout", email=None) -> str:
    rows = query(
        "SELECT notes FROM coach_notes WHERE coach_email=? AND team_id=? AND kind=?",
        (_coach_email(email), team_id, kind))
    return rows[0]["notes"] if rows else ""


def save_note(team_id, text, kind="scout", email=None) -> None:
    execute(
        "INSERT INTO coach_notes (coach_email, team_id, kind, notes) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(coach_email, team_id, kind) DO UPDATE SET notes=excluded.notes",
        (_coach_email(email), team_id, kind, text))


def render_notes(team_id, *, kind="scout", key_prefix="sn", label="Game-plan notes",
                 placeholder=None, height=200):
    """Per-COACH notes for a team, saved in place — private to the current coach."""
    val = get_note(team_id, kind)
    ph = placeholder or ("Coverages, ATO / BLOB / SLOB calls, who to deny, press "
                         "break, special situations, late-game fouling…")
    new = st.text_area(
        label, value=val, height=height, key=f"{key_prefix}_{kind}_{team_id}",
        placeholder=ph, label_visibility="collapsed")
    if st.button("Save notes", key=f"{key_prefix}_{kind}_save_{team_id}"):
        save_note(team_id, new, kind)
        st.success("Notes saved.")
