"""
scoutboard.py — PER-COACH notes (coach_notes table), private to each coach.

Two kinds share the table: 'team' (general team notes) and 'scout' (opponent
game-plan). Every coach sees ONLY their own notes for a team — no cross-coach
read or last-write-wins overwrite (the old global teams.notes / scout_notes leak).
The coach is resolved from the login identity (helpers.auth.current_user); with
auth off it's the single local owner ('' bucket). UI helper.
"""
from __future__ import annotations

import json

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


# ── structured key-player intel (hand-entered; works for COLD opponents) ─────────
# Stored per-coach in the SAME coach_notes table under kind='intel' as a JSON list
# [{num, name, note}, ...] — no schema change. This is the coaching-intel layer
# (who to guard, force-hand, threats) that no scraper produces, so a coach can
# build a real scout sheet for an opponent they've never tracked.
def get_intel(team_id, email=None) -> list:
    raw = get_note(team_id, kind="intel", email=email)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def save_intel(team_id, rows, email=None) -> None:
    clean = []
    for r in (rows or []):
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        rec = {"num": str(r.get("num") or "").strip(), "name": name,
               "note": str(r.get("note") or "").strip()}
        if r.get("pid") is not None:        # roster-picked → keep the player id so
            try:                            # the note can land in that player's box
                rec["pid"] = int(r["pid"])
            except (TypeError, ValueError):
                pass
        clean.append(rec)
    save_note(team_id, json.dumps(clean), kind="intel", email=email)


def render_intel(team_id, *, key_prefix="si") -> list:
    """Per-coach key-player intel. When the opponent's roster is on file, the coach
    PICKS the player from a dropdown (number + name auto-filled) and adds a note —
    the note then prints in that player's box on the scout sheet. Falls back to
    free-text entry for a team with no roster yet. Returns the current rows."""
    import pandas as pd
    roster = query(
        "SELECT id, number, name FROM players WHERE team_id=? AND archived=0 "
        "ORDER BY CAST(COALESCE(NULLIF(number,''),'0') AS INTEGER), name", (team_id,))
    cur = get_intel(team_id)

    if not roster:
        # no roster on file (truly cold opponent) — free-text entry
        df = pd.DataFrame(
            [{"num": r.get("num", ""), "name": r.get("name", ""),
              "note": r.get("note", "")} for r in cur], columns=["num", "name", "note"])
        edited = st.data_editor(
            df, key=f"{key_prefix}_intel_{team_id}", num_rows="dynamic",
            width="stretch", hide_index=True,
            column_config={
                "num": st.column_config.TextColumn("#", width="small"),
                "name": st.column_config.TextColumn("Player", required=True),
                "note": st.column_config.TextColumn(
                    "Scouting note (how to guard / force-hand / threat)",
                    width="large"),
            })
        if st.button("Save key players", key=f"{key_prefix}_intel_save_{team_id}"):
            save_intel(team_id, edited.to_dict("records"))
            st.success("Key players saved.")
            return get_intel(team_id)
        return cur

    # roster on file — pick the player from a dropdown (we already have the data)
    meta_by_label, options = {}, []
    for r in roster:
        lbl = f"#{r['number'] or ''} {r['name']}".strip()
        if lbl in meta_by_label:                    # disambiguate rare collisions
            lbl = f"{lbl} (id {r['id']})"
        meta_by_label[lbl] = {"pid": r["id"], "num": str(r["number"] or ""),
                              "name": r["name"]}
        options.append(lbl)
    label_by_pid = {m["pid"]: lbl for lbl, m in meta_by_label.items()}
    name_to_label = {m["name"].lower(): lbl for lbl, m in meta_by_label.items()}
    seed = [{"Player": (label_by_pid.get(r.get("pid"))
                        or name_to_label.get(str(r.get("name", "")).lower())),
             "note": r.get("note", "")} for r in cur]
    df = pd.DataFrame(seed, columns=["Player", "note"])
    edited = st.data_editor(
        df, key=f"{key_prefix}_intel_{team_id}", num_rows="dynamic",
        width="stretch", hide_index=True,
        column_config={
            "Player": st.column_config.SelectboxColumn(
                "Player", options=options, required=True, width="medium"),
            "note": st.column_config.TextColumn(
                "Scouting note (how to guard / force-hand / threat)", width="large"),
        })
    if st.button("Save key players", key=f"{key_prefix}_intel_save_{team_id}"):
        recs = []
        for row in edited.to_dict("records"):
            m = meta_by_label.get((row.get("Player") or "").strip())
            if not m:
                continue
            recs.append({"num": m["num"], "name": m["name"], "pid": m["pid"],
                         "note": str(row.get("note") or "").strip()})
        save_intel(team_id, recs)
        st.success("Key players saved.")
        return get_intel(team_id)
    return cur


# ── matchup plan (per-coach): {their_scorer_key: my_defender_pid} per opponent ──
# Stored in coach_notes under kind='matchup' as JSON, keyed by the OPPONENT team_id
# (the team_id arg). Lets a coach save "put my #4 on their #11" assignments. No
# schema change.
def get_plan(team_id, email=None) -> dict:
    raw = get_note(team_id, kind="matchup", email=email)
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_plan(team_id, plan, email=None) -> None:
    save_note(team_id, json.dumps(plan or {}), kind="matchup", email=email)
