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
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from PIL import Image

from helpers.ui import page_chrome, page_header, empty_state
import helpers.court_geom as CG
import helpers.event_log as EL
import helpers.playtypes as PT

try:
    from streamlit_image_coordinates import streamlit_image_coordinates
    _HAVE_IMG_COORDS = True
except Exception:
    _HAVE_IMG_COORDS = False

_cfg, ACCENT = page_chrome("Event Editor")

# Clock times must be M:SS / MM:SS with seconds 00–59 (e.g. "8:04", "10:32").
_TIME_RE = re.compile(r"^\d{1,2}:[0-5]\d$")

page_header("Event Editor",
            sub="Correct or delete any logged play-by-play event. Edits re-derive +/- "
                "for changed baskets and keep lineup stats valid; deletes cascade their "
                "on-court snapshot. Adding brand-new events is still done in the Game "
                "Tracker (a new event needs its on-floor lineup).")

# Flash messages stashed by the save handlers before their st.rerun()
for _k, _m in st.session_state.pop("ee_flash", []):
    getattr(st, _k)(_m)

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

# Play-call (play_type) labels for the optional one-tap set-call tag on a shot —
# same set as the PWA tracker (helpers/playtypes.NAMED_PLAY_TYPES).
play_opts = ["—"] + [lbl for _k, lbl in PT.NAMED_PLAY_TYPES]
key2play = {k: lbl for k, lbl in PT.NAMED_PLAY_TYPES}
play2key = {lbl: k for k, lbl in PT.NAMED_PLAY_TYPES}

# Defense labels for the sticky one-tap defense tag on a shot/turnover — same set
# as the tracker (helpers/defenses.DEFENSES). Back-fill / correct it on old events
# here just like the play call.
import helpers.defenses as DEF
def_opts = ["—"] + [lbl for _k, lbl, _f in DEF.DEFENSES]
key2def = {k: lbl for k, lbl, _f in DEF.DEFENSES}
def2key = {lbl: k for k, lbl, _f in DEF.DEFENSES}

# Turnover-kind labels (pass / drive / held / shot clock / travel) — same set
# as the trackers (helpers/turnovers.TURNOVER_TYPES). Back-fill old TOs here.
import helpers.turnovers as TOV
tov_opts = ["—"] + [lbl for _k, lbl in TOV.TURNOVER_TYPES]
key2tov = {k: lbl for k, lbl in TOV.TURNOVER_TYPES}
tov2key = {lbl: k for k, lbl in TOV.TURNOVER_TYPES}

# Foul-kind labels (offensive / rebounding) — same set as the trackers
# (helpers/fouls.FOUL_TYPES). Back-fill old fouls here; — = regular defensive.
import helpers.fouls as FLS
fk_opts = ["—"] + [lbl for _k, lbl in FLS.FOUL_TYPES]
key2fk = {k: lbl for k, lbl in FLS.FOUL_TYPES}
fk2key = {lbl: k for k, lbl in FLS.FOUL_TYPES}

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

# ── event-type filter — view just shots, just fouls, etc. ───────────────────────
_etypes = sorted({e["event_type"] for e in events})
tpick = st.radio("Event type", ["All"] + _etypes, horizontal=True, key="ee_type",
                 format_func=lambda t: "All" if t == "All" else t.replace("_", " "),
                 help="Filter the grid (and the shot fixer) to one event type — "
                      "e.g. only shots in this game.")
if tpick != "All":
    events = [e for e in events if e["event_type"] == tpick]
if not events:
    st.info(f"No {tpick.replace('_', ' ')} events in this view.")
    st.stop()

# ── bulk-tag the defense scheme, PER TEAM (set each side, then tweak) ───────────
# Most teams play one or two defenses, so per-possession entry is a slog. The
# defense tag is the DEFENDING (other) team's scheme, so splitting by the team
# WITH THE BALL lets each side take its own fill: pick the defense each team
# FACED on its possessions (= the scheme the other team ran). Tag the whole game
# in one click, then change the exceptions in the grid. Whole game, not the filter.
with st.expander("🛡️ Bulk-tag defense by team — set each side, then tweak"):
    st.caption("Pick the defense each team **faced** on its possessions (the "
               "scheme the OTHER team was running), then change the few exceptions "
               "in the grid below. Tag one side or both. Free throws don't carry a "
               "defense. Applies to the whole game, not just the filtered view.")
    # Pull the two teams straight from gid (always valid) rather than gsel's keys
    # — st.selectbox can hand back a STALE option dict from a pre-deploy session
    # that predates these fields, which would KeyError.
    _grow = _q("SELECT t1.id i1, t1.name n1, t2.id i2, t2.name n2 "
               "FROM games g JOIN teams t1 ON t1.id=g.team1_id "
               "JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?", (gid,))[0]
    _t1n, _t2n = _grow["n1"], _grow["n2"]
    _t1id, _t2id = _grow["i1"], _grow["i2"]
    bc1, bc2 = st.columns(2)
    _d_t1 = bc1.selectbox(f"{_t1n} possessions — defense faced", def_opts,
                          key="ee_bulk_t1",
                          help=f"The scheme {_t2n} ran against {_t1n}.")
    _d_t2 = bc2.selectbox(f"{_t2n} possessions — defense faced", def_opts,
                          key="ee_bulk_t2",
                          help=f"The scheme {_t1n} ran against {_t2n}.")
    _only_blank = st.checkbox(
        "Only untagged events", value=True, key="ee_bulk_blank",
        help="On = fill only events with no defense yet (keeps your tweaks). "
             "Off = overwrite every eligible event for the chosen team(s).")
    if st.button("Apply", key="ee_bulk_go", type="primary"):
        _total = 0
        for _lbl, _tid in [(_d_t1, _t1id), (_d_t2, _t2id)]:
            if _lbl and _lbl != "—":
                _total += EL.bulk_set_defense(gid, def2key.get(_lbl),
                                              only_blank=_only_blank,
                                              primary_team_id=_tid)
        if _total:
            st.cache_data.clear()
            st.success(f"Tagged {_total} event{'s' if _total != 1 else ''}. "
                       "Tweak the exceptions in the grid below.")
            st.rerun()
        else:
            st.info("Nothing to tag — pick a defense for at least one team "
                    "(uncheck **Only untagged** to overwrite existing tags).")


def _disp(ev):
    return {
        "id": ev["id"],
        "Q": ev["quarter"], "Time": ev["time"], "Type": ev["event_type"],
        "Primary": pid2label.get(ev["primary_player_id"], "—"),
        "Result": ev["shot_result"] or "—",
        "ShotType": str(ev["shot_type"]) if ev["shot_type"] else "—",
        "Zone": ev["zone"] or "—",
        "Play": key2play.get(ev["play_type"], "—"),
        "Defense": key2def.get(ev["defense"], "—"),
        "Pass": pid2label.get(ev["pass_from_id"], "—"),
        "Created": pid2label.get(ev["shot_created_by_id"], "—"),
        "Guarded": pid2label.get(ev["guarded_by_id"], "—"),
        "Rebound": pid2label.get(ev["rebound_by_id"], "—"),
        "Blocked": pid2label.get(ev["blocked_by_id"], "—"),
        "Fouler": pid2label.get(ev["secondary_player_id"], "—"),
        "Stolen": pid2label.get(ev["stolen_by_id"], "—"),
        "TOkind": key2tov.get(ev["turnover_type"], "—"),
        "FoulKind": key2fk.get(ev["foul_type"], "—"),
        "Official": oid2name.get(ev["official_id"], "—"),
        "Delete?": False,
    }


grid = pd.DataFrame([_disp(e) for e in events])
orig_by_id = {e["id"]: e for e in events}

st.caption("**Primary** = shooter (shot/FT) · player fouled (foul) · player who "
           "lost it (turnover). **Fouler** = who committed the foul. **Play** = the "
           "one-tap set call (PnR, ISO, SLOB, BLOB …) on a shot, turnover or foul — "
           "back-fill old events here. **Defense** = the scheme in effect (man, 2-3, "
           "press …) on a shot, turnover or foul. Tick **Delete?** to remove a row. Player picks are "
           "limited to both rosters. For tap-captured shots, Zone and 2/3 follow the "
           "stored location — move the shot in **Fix a shot location** below instead.")

edited = st.data_editor(
    grid, hide_index=True, width="stretch", key=f"ee_grid_{gid}_{qpick}_{tpick}",
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
        "Play": st.column_config.SelectboxColumn("Play", options=play_opts,
                                                 width="small",
                                                 help="One-tap set call (shots, "
                                                      "turnovers & fouls)"),
        "Defense": st.column_config.SelectboxColumn("Defense", options=def_opts,
                                                    width="small",
                                                    help="Defense in effect (shots & "
                                                         "turnovers) — man, 2-3, press …"),
        "Pass": st.column_config.SelectboxColumn("Pass from", options=player_opts),
        "Created": st.column_config.SelectboxColumn("Created by", options=player_opts),
        "Guarded": st.column_config.SelectboxColumn("Guarded by", options=player_opts),
        "Rebound": st.column_config.SelectboxColumn("Rebound by", options=player_opts),
        "Blocked": st.column_config.SelectboxColumn("Blocked by", options=player_opts),
        "Fouler": st.column_config.SelectboxColumn("Fouler", options=player_opts),
        "Stolen": st.column_config.SelectboxColumn("Stolen by", options=player_opts),
        "TOkind": st.column_config.SelectboxColumn("TO kind", options=tov_opts,
                                                   width="small",
                                                   help="Kind of giveaway on a "
                                                        "turnover — bad pass, "
                                                        "drive, held ball …"),
        "FoulKind": st.column_config.SelectboxColumn("Foul kind", options=fk_opts,
                                                     width="small",
                                                     help="Kind of foul — offensive "
                                                          "(charge / illegal screen) "
                                                          "or rebounding. — = regular "
                                                          "defensive foul."),
        "Official": st.column_config.SelectboxColumn("Official", options=official_opts),
        "Delete?": st.column_config.CheckboxColumn("Delete?", width="small"),
    })

if st.button("💾 Save changes", type="primary", key="ee_save"):
    updated = deleted = 0
    bad_times = []
    loc_locked = 0
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
            "play_type": play2key.get(r["Play"]),
            "defense": def2key.get(r["Defense"]),
            "primary_player_id": label2pid.get(r["Primary"]),
            "pass_from_id": label2pid.get(r["Pass"]),
            "shot_created_by_id": label2pid.get(r["Created"]),
            "guarded_by_id": label2pid.get(r["Guarded"]),
            "rebound_by_id": label2pid.get(r["Rebound"]),
            "blocked_by_id": label2pid.get(r["Blocked"]),
            "secondary_player_id": label2pid.get(r["Fouler"]),
            "stolen_by_id": label2pid.get(r["Stolen"]),
            "turnover_type": tov2key.get(r["TOkind"]),
            "foul_type": fk2key.get(r["FoulKind"]),
            "official_id": name2oid.get(r["Official"]),
        }
        # Tap-captured shots: the stored x/y is the source of truth for WHERE,
        # so a manual Zone/2-3 dropdown change re-derives from the location
        # instead (move the shot in the fixer below). Only rows the user
        # actually edited are touched — older shots whose zone/2-3 were
        # legitimately hand-corrected (foot-on-the-line 3 → 2) before the
        # fixer existed are never auto-rewritten by an unrelated save.
        if (ev["event_type"] == "shot" and vals["event_type"] == "shot"
                and ev["shot_x"] is not None and ev["shot_y"] is not None):
            _zone_touched = (
                str(r["Zone"]) != (ev["zone"] or "—")
                or str(r["ShotType"]) != (str(ev["shot_type"])
                                          if ev["shot_type"] else "—"))
            if _zone_touched:
                _dz = CG.zone_from_xy(ev["shot_x"], ev["shot_y"])
                _dv = CG.shot_value(ev["shot_x"], ev["shot_y"])
                if vals["zone"] != _dz or vals["shot_type"] != _dv:
                    loc_locked += 1
                vals["zone"], vals["shot_type"] = _dz, _dv
        if EL.event_changed(ev, vals):
            # Clock sanity — "12:99" would poison elapsed-time / +/- math.
            if not _TIME_RE.match(str(r["Time"]).strip()):
                bad_times.append(f"Q{r['Q']} '{r['Time']}' ({r['Type']} · {r['Primary']})")
                continue
            EL.update_event(gid, eid, vals, pid2team)
            updated += 1
    # Messages must survive the st.rerun() that reloads the grid — stash them
    # as a flash list rendered at the top of the next run.
    _flash = []
    if loc_locked:
        _flash.append(("warning",
                       f"{loc_locked} shot(s) kept the zone/2-3 derived from "
                       "their tap location — use **Fix a shot location** below "
                       "to move a mistapped shot."))
    if bad_times:
        st.error("Skipped row(s) with an invalid clock time — use M:SS with "
                 "seconds 00–59 (e.g. 8:04): " + "; ".join(bad_times)
                 + ". Fix those rows and save again.")
    if updated or deleted:
        st.cache_data.clear()
        _flash.insert(0, ("success",
                          f"Saved — {updated} edited, {deleted} deleted. "
                          "Recompute the final score above if it drifted."))
        if bad_times:   # no rerun — keep the skipped-row error visible
            for _k, _m in _flash:
                getattr(st, _k)(_m)
        else:
            st.session_state["ee_flash"] = _flash
            st.rerun()
    else:
        for _k, _m in _flash:
            getattr(st, _k)(_m)
        if not bad_times and not loc_locked:
            st.info("No changes to save.")

# ══════════════════════════════════════════════════════════════════════════════
#  FIX A SHOT LOCATION — move a mistapped shot, or add a location to a legacy
#  zone-only shot. The x/y is the source of truth: zone + 2/3 re-derive from it
#  (helpers/event_log.set_shot_location), +/- shifts if a made 2<->3 flips, and
#  the drift banner above offers the score recompute when needed.
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.markdown("### Fix a shot location")

_shot_evs = [e for e in events if e["event_type"] == "shot"]
if not _shot_evs:
    st.caption("No shots in this view — pick another quarter or game above.")
elif not _HAVE_IMG_COORDS:
    st.caption("Tap-to-fix needs the `streamlit-image-coordinates` package "
               "(the Game Tracker court uses the same one).")
else:
    @st.cache_resource(show_spinner=False)
    def _ee_court_base(width):
        return CG.court_image(width)

    def _fx_label(e):
        who = pid2label.get(e["primary_player_id"], "—")
        res = "✓ make" if e["shot_result"] == "make" else "✕ miss"
        loc = (f"{e['zone'] or '?'} · located" if e["shot_x"] is not None
               else f"{e['zone'] or '?'} · NO location")
        return (f"Q{e['quarter']} {e['time']} · {who} · {res} · "
                f"{e['shot_type'] or '?'}PT · {loc}")

    # Saving changes the option labels, which resets the widget — re-land on
    # the same shot via the remembered event id instead of jumping to row 0.
    _last_id = st.session_state.get("ee_fix_last")
    _idx = next((i for i, e in enumerate(_shot_evs) if e["id"] == _last_id), 0)
    fx = st.selectbox("Shot to move", _shot_evs, index=_idx,
                      format_func=_fx_label, key=f"ee_fix_pick_{gid}_{qpick}")
    st.session_state["ee_fix_last"] = fx["id"]
    # Switching shots drops any uncommitted tap from the previous one — a
    # stale pending coordinate must never sit armed behind Save.
    if st.session_state.get("ee_fix_prev") != fx["id"]:
        for _sk in [k for k in st.session_state
                    if str(k).startswith(f"ee_fix_xy_{gid}_")]:
            st.session_state.pop(_sk)
        st.session_state["ee_fix_prev"] = fx["id"]
    _fx_key = f"ee_fix_xy_{gid}_{fx['id']}"
    _fx_gen = st.session_state.get(f"ee_tapgen_{gid}", 0)
    _pending = st.session_state.get(_fx_key)

    fc_l, fc_r = st.columns([1, 2])
    with fc_l:
        W = 265
        H = CG.image_height(W)
        base = _ee_court_base(W)
        mark = _pending or ((fx["shot_x"], fx["shot_y"])
                            if fx["shot_x"] is not None else None)
        if mark:
            shown = CG.court_image_with_marker(mark[0], mark[1], base=base, width=W)
            _hint = False
        else:
            # No location yet — draw a faint placeholder dot (top of the key)
            # instead of the BARE court. The bare base image is byte-identical
            # every render and the coordinates component intermittently failed to
            # repaint it; routing through the same marked-image path as located
            # shots makes the court render reliably + gives a clear tap target.
            shown = CG.court_image_with_marker(0.0, 19.0, base=base, width=W,
                                               color="#5b636e")
            _hint = True
        # rim at TOP, half-court at bottom — same view as the PWA tracker court
        # (court_geom draws rim-bottom; flip vertically to match).
        disp = shown.transpose(Image.FLIP_TOP_BOTTOM)
        st.caption("Tap where the shot was actually taken"
                   + (" — the grey dot is a placeholder, not the shot"
                      if _hint else ""))
        val = streamlit_image_coordinates(disp, width=disp.width,
                                          key=f"ee_court_{fx['id']}_{_fx_gen}")
        if val is not None:
            ox, oy = val["x"], H - val["y"]   # undo the vertical flip
            fxy = CG.feet_from_px(ox, oy, W, H)
            if (_pending is None or abs(_pending[0] - fxy[0]) > 1e-6
                    or abs(_pending[1] - fxy[1]) > 1e-6):
                st.session_state[_fx_key] = fxy
                st.rerun()

    with fc_r:
        if fx["shot_x"] is not None:
            st.markdown(f"Stored: **{fx['shot_type']}PT · {fx['zone']}** · "
                        f"{CG.shot_distance(fx['shot_x'], fx['shot_y']):.0f} ft")
        else:
            st.markdown(f"Stored: **{fx['shot_type'] or '?'}PT · "
                        f"{fx['zone'] or 'no zone'}** — no tap location yet")
        if _pending:
            st.markdown(f"New spot: **{CG.shot_value(*_pending)}PT · "
                        f"{CG.zone_from_xy(*_pending)}** · "
                        f"{CG.shot_distance(*_pending):.0f} ft")
            sv1, sv2 = st.columns(2)
            if sv1.button("Save location", type="primary", key="ee_fix_save"):
                EL.set_shot_location(gid, fx["id"], _pending[0], _pending[1],
                                     pid2team)
                st.session_state.pop(_fx_key, None)
                st.session_state[f"ee_tapgen_{gid}"] = _fx_gen + 1
                st.session_state["ee_flash"] = [
                    ("success", "Shot location updated — zone and 2/3 "
                                "re-derived. Recompute the final score above "
                                "if the drift banner appears.")]
                st.cache_data.clear()
                st.rerun()
            if sv2.button("Discard tap", key="ee_fix_discard"):
                st.session_state.pop(_fx_key, None)
                st.session_state[f"ee_tapgen_{gid}"] = _fx_gen + 1
                st.rerun()
        else:
            st.caption("Tap the court to pick the corrected spot — zone and "
                       "2/3 re-derive automatically, and a 2↔3 flip on a made "
                       "shot updates +/- (recompute the score above if the "
                       "drift banner appears).")

# ══════════════════════════════════════════════════════════════════════════════
#  INSERT A MISSED EVENT — the basket the scorekeeper missed is no longer
#  unrecoverable: the floor is cloned from the nearest logged event and the
#  insert runs the normal live write path (snapshot, +/-, possession secs
#  re-split around the new row).
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
st.markdown("### Insert a missed event")
st.caption("The on-floor five are cloned from the nearest logged event, "
           "possession seconds are re-split around the insert, and +/- is "
           "applied — the same write path as live logging. For a shot, add "
           "its court location afterwards in **Fix a shot location**; "
           "recompute the score above if the drift banner appears.")

ins_type = st.selectbox("Event type", list(EL.EVENT_TYPES),
                        key=f"ins_type_{gid}")
with st.form(f"ins_form_{gid}", clear_on_submit=True):
    ic1, ic2 = st.columns(2)
    ins_q = ic1.number_input("Quarter", min_value=1, max_value=10, step=1,
                             value=1)
    ins_t = ic2.text_input("Clock (M:SS)", value="4:00",
                           help="Time remaining in the period")

    if ins_type == "shot":
        s1, s2, s3 = st.columns([3, 1, 1])
        ins_primary = s1.selectbox("Shooter", player_opts[1:])
        ins_result = s2.selectbox("Result", ["make", "miss"])
        ins_stype = s3.selectbox("2/3", ["2", "3"])
        s4, s5, s6 = st.columns(3)
        ins_zone = s4.selectbox("Zone", ["—"] + list(EL.ZONES))
        ins_pass = s5.selectbox("Pass from", player_opts)
        ins_created = s6.selectbox("Created by", player_opts)
        s7, s8, s9 = st.columns(3)
        ins_guarded = s7.selectbox("Guarded by", player_opts)
        ins_rebound = s8.selectbox("Rebound by", player_opts)
        ins_blocked = s9.selectbox("Blocked by", player_opts)
        i_pd1, i_pd2 = st.columns(2)
        ins_play = i_pd1.selectbox("Play type", play_opts,
                                   help="One-tap set call (optional)")
        ins_def = i_pd2.selectbox("Defense", def_opts,
                                  help="Defense in effect (optional)")
    elif ins_type == "free_throw":
        f1, f2, f3 = st.columns([3, 1, 2])
        ins_primary = f1.selectbox("Shooter", player_opts[1:])
        ins_result = f2.selectbox("Result", ["make", "miss"])
        ins_rebound = f3.selectbox("Rebound by", player_opts)
    elif ins_type == "foul":
        f1, f2, f3, f4 = st.columns([2, 2, 1, 2])
        ins_primary = f1.selectbox("Player fouled", player_opts[1:])
        ins_fouler = f2.selectbox("Player who fouled", player_opts[1:])
        ins_off = f3.selectbox("Official", official_opts)
        ins_def = f4.selectbox("Defense", def_opts,
                               help="Defense in effect (optional)")
    else:  # turnover
        f1, f2, f3 = st.columns(3)
        ins_primary = f1.selectbox("Turnover by", player_opts[1:])
        ins_stolen = f2.selectbox("Stolen by", player_opts)
        ins_def = f3.selectbox("Defense", def_opts,
                               help="Defense in effect (optional)")

    ins_go = st.form_submit_button("Insert event", type="primary")

if ins_go:
    _tm = _TIME_RE.match(ins_t.strip())
    _mm, _ss = (int(p) for p in ins_t.strip().split(":")) if _tm else (0, 0)
    _cap = 480 if int(ins_q) <= 4 else 240   # 8:00 quarters, 4:00 OTs
    if not _tm:
        st.error("Clock must be M:SS with seconds 00–59 (e.g. 4:05).")
    elif _mm * 60 + _ss > _cap:
        st.error(f"{ins_t.strip()} is more than the period holds "
                 f"({_cap // 60}:00).")
    elif label2pid.get(ins_primary) is None:
        st.error("Pick the primary player.")
    else:
        ev = {"event_type": ins_type, "quarter": int(ins_q),
              "time": ins_t.strip(),
              "primary_player_id": label2pid.get(ins_primary)}
        if ins_type == "shot":
            ev.update(shot_result=ins_result, shot_type=int(ins_stype),
                      zone=None if ins_zone == "—" else ins_zone,
                      pass_from_id=label2pid.get(ins_pass),
                      shot_created_by_id=label2pid.get(ins_created),
                      guarded_by_id=label2pid.get(ins_guarded),
                      rebound_by_id=label2pid.get(ins_rebound),
                      blocked_by_id=label2pid.get(ins_blocked),
                      play_type=play2key.get(ins_play),
                      defense=def2key.get(ins_def))
        elif ins_type == "free_throw":
            ev.update(shot_result=ins_result,
                      rebound_by_id=label2pid.get(ins_rebound))
        elif ins_type == "foul":
            ev.update(secondary_player_id=label2pid.get(ins_fouler),
                      official_id=name2oid.get(ins_off),
                      defense=def2key.get(ins_def))
        else:
            ev.update(stolen_by_id=label2pid.get(ins_stolen),
                      defense=def2key.get(ins_def))

        _eid, _nfloor = EL.insert_missed_event(gid, ev)
        _flash = [("success",
                   f"Inserted — event #{_eid} now in the log. Recompute the "
                   "final score above if it drifted.")]
        if not _nfloor:
            _flash.append(("warning",
                           "No adjacent event to clone a lineup from — the "
                           "insert carries no on-floor five, so it won't "
                           "count toward minutes or +/-."))
        elif _nfloor < 10:
            _flash.append(("warning",
                           f"Cloned floor has only {_nfloor} players — "
                           "minutes/+/- follow whatever the adjacent event "
                           "had."))
        st.session_state["ee_flash"] = _flash
        st.cache_data.clear()
        st.rerun()
