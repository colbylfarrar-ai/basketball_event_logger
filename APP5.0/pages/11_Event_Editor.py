"""
11_Event_Editor.py — fix or delete logged play-by-play events after a game.

The Game Tracker only lets you delete the LAST event while logging live. This is
the corrections desk: open any game with events, fix a mis-tagged shooter / zone
/ result / event type, or delete a bad row, in one editable grid. Saving keeps
everything downstream consistent — +/- is re-derived for changed baskets, the
on-court lineup snapshot is preserved (or cascade-cleared on delete), and you can
re-freeze the final score from the corrected log. Data quality is the moat once a
shared/scouting database grows, so a mis-click is recoverable, not permanent.

Display + controls only; all mutation/validation lives in helpers/event_log.py.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from helpers.ui import page_chrome, empty_state
import helpers.event_log as EL

_cfg, ACCENT = page_chrome()

st.title("Event Editor")
st.caption("Correct or delete any logged play-by-play event. Edits re-derive +/- "
           "for changed baskets and keep lineup stats valid; deletes cascade their "
           "on-court snapshot. Adding brand-new events is still done in the Game "
           "Tracker (a new event needs its on-floor lineup).")

games = EL.games_with_events()
if not games:
    empty_state("No tracked events yet",
                "Log a game in the Game Tracker first, then come here to fix it.",
                icon="📝")
    st.stop()

gsel = st.selectbox(
    "Game", games, key="ee_game",
    format_func=lambda g: (f"{g['date']} · {g['n1']} vs {g['n2']} "
                           f"· {g['n_events']} events"
                           + ("  ✓ final" if g["tracked"] else "  · in progress")))
gid = gsel["id"]

people = EL.game_people(gid)
pid2label = people["pid2label"]
label2pid = people["label2pid"]
oid2name = people["oid2name"]
name2oid = people["name2oid"]
pid2team = people["pid2team"]

player_opts = ["—"] + [p["label"] for p in people["players"]]
official_opts = ["—"] + [o["name"] for o in people["officials"]]

# ── score drift indicator ────────────────────────────────────────────────────
from database.db import query as _q

live = EL.score_from_events(gid)
sc_cols = st.columns([2, 2, 3])
if live is not None:
    rec = _q("SELECT home_score, away_score FROM games WHERE id=?", (gid,))
    h_stored = rec[0]["home_score"] if rec else None
    a_stored = rec[0]["away_score"] if rec else None
    sc_cols[0].metric(f"{gsel['n1']} (stored)",
                      h_stored if h_stored is not None else "—",
                      f"{live[0]} from events", delta_color="off")
    sc_cols[1].metric(f"{gsel['n2']} (stored)",
                      a_stored if a_stored is not None else "—",
                      f"{live[1]} from events", delta_color="off")
    drift = (h_stored != live[0]) or (a_stored != live[1])
    with sc_cols[2]:
        if drift:
            st.warning("Stored score ≠ events. Recompute after your edits.")
        if st.button("↻ Recompute final score from events", key="ee_recompute"):
            EL.recompute_final_score(gid)
            st.cache_data.clear()
            st.success(f"Final score set to {live[0]}–{live[1]} from the log.")
            st.rerun()

st.divider()

# ── quarter filter ─────────────────────────────────────────────────────────────
qs = EL.quarters_in_game(gid)
qlabels = ["All"] + [f"Q{q}" if q <= 4 else f"OT{q - 4}" for q in qs]
qmap = {("All"): None,
        **{(f"Q{q}" if q <= 4 else f"OT{q - 4}"): q for q in qs}}
qpick = st.radio("Quarter", qlabels, horizontal=True, key="ee_q")
quarter = qmap[qpick]

events = EL.load_events(gid, quarter)
if not events:
    st.info("No events in this quarter.")
    st.stop()


def _disp(ev):
    return {
        "id": ev["id"],
        "Q": ev["quarter"], "Time": ev["time"], "Type": ev["event_type"],
        "Primary": pid2label.get(ev["primary_player_id"], "—"),
        "Result": ev["shot_result"] or "—",
        "ShotType": str(ev["shot_type"]) if ev["shot_type"] else "—",
        "Zone": ev["zone"] or "—",
        "Pass": pid2label.get(ev["pass_from_id"], "—"),
        "Created": pid2label.get(ev["shot_created_by_id"], "—"),
        "Guarded": pid2label.get(ev["guarded_by_id"], "—"),
        "Rebound": pid2label.get(ev["rebound_by_id"], "—"),
        "Blocked": pid2label.get(ev["blocked_by_id"], "—"),
        "Fouler": pid2label.get(ev["secondary_player_id"], "—"),
        "Stolen": pid2label.get(ev["stolen_by_id"], "—"),
        "Official": oid2name.get(ev["official_id"], "—"),
        "Delete?": False,
    }


grid = pd.DataFrame([_disp(e) for e in events])
orig_by_id = {e["id"]: e for e in events}

st.caption("**Primary** = shooter (shot/FT) · player fouled (foul) · player who "
           "lost it (turnover). **Fouler** = who committed the foul. Tick "
           "**Delete?** to remove a row. Player picks are limited to both rosters.")

edited = st.data_editor(
    grid, hide_index=True, width="stretch", key=f"ee_grid_{gid}_{qpick}",
    num_rows="fixed", height=560,
    column_config={
        "id": None,
        "Q": st.column_config.NumberColumn("Q", min_value=1, max_value=10, step=1,
                                           width="small"),
        "Time": st.column_config.TextColumn("Time", width="small",
                                            help="Clock time, M:SS"),
        "Type": st.column_config.SelectboxColumn("Type", options=list(EL.EVENT_TYPES)),
        "Primary": st.column_config.SelectboxColumn("Primary", options=player_opts),
        "Result": st.column_config.SelectboxColumn("Result", options=["—", "make", "miss"],
                                                   width="small"),
        "ShotType": st.column_config.SelectboxColumn("2/3", options=["—", "2", "3"],
                                                     width="small"),
        "Zone": st.column_config.SelectboxColumn("Zone", options=["—"] + list(EL.ZONES),
                                                 width="small"),
        "Pass": st.column_config.SelectboxColumn("Pass from", options=player_opts),
        "Created": st.column_config.SelectboxColumn("Created by", options=player_opts),
        "Guarded": st.column_config.SelectboxColumn("Guarded by", options=player_opts),
        "Rebound": st.column_config.SelectboxColumn("Rebound by", options=player_opts),
        "Blocked": st.column_config.SelectboxColumn("Blocked by", options=player_opts),
        "Fouler": st.column_config.SelectboxColumn("Fouler", options=player_opts),
        "Stolen": st.column_config.SelectboxColumn("Stolen by", options=player_opts),
        "Official": st.column_config.SelectboxColumn("Official", options=official_opts),
        "Delete?": st.column_config.CheckboxColumn("Delete?", width="small"),
    })

if st.button("💾 Save changes", type="primary", key="ee_save"):
    updated = deleted = 0
    for _, r in edited.iterrows():
        eid = int(r["id"])
        ev = orig_by_id.get(eid)
        if ev is None:
            continue
        if bool(r["Delete?"]):
            EL.delete_event(gid, eid, pid2team)
            deleted += 1
            continue
        vals = {
            "event_type": r["Type"],
            "quarter": r["Q"], "time": r["Time"],
            "shot_result": None if r["Result"] == "—" else r["Result"],
            "shot_type": None if r["ShotType"] == "—" else int(r["ShotType"]),
            "zone": None if r["Zone"] == "—" else r["Zone"],
            "primary_player_id": label2pid.get(r["Primary"]),
            "pass_from_id": label2pid.get(r["Pass"]),
            "shot_created_by_id": label2pid.get(r["Created"]),
            "guarded_by_id": label2pid.get(r["Guarded"]),
            "rebound_by_id": label2pid.get(r["Rebound"]),
            "blocked_by_id": label2pid.get(r["Blocked"]),
            "secondary_player_id": label2pid.get(r["Fouler"]),
            "stolen_by_id": label2pid.get(r["Stolen"]),
            "official_id": name2oid.get(r["Official"]),
        }
        if EL.event_changed(ev, vals):
            EL.update_event(gid, eid, vals, pid2team)
            updated += 1
    if updated or deleted:
        st.cache_data.clear()
        st.success(f"Saved — {updated} edited, {deleted} deleted. "
                   "Recompute the final score above if it drifted.")
        st.rerun()
    else:
        st.info("No changes to save.")
