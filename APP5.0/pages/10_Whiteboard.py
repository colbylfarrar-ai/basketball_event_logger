"""
10_Whiteboard.py — draw plays on a half or full court, save them to a playbook.

The canvas whiteboard is a no-build bidirectional component
(assets/whiteboard/index.html): the court is drawn in JavaScript (vector,
crisp at any size) from the same geometry constants the shot-chart model uses
(helpers/court_geom.py) and every stroke stays client-side at 60fps. Two
round-trips exist, both explicit (never per-stroke):
  * "⬆ Send to app" pushes the current board to Python so the coach can NAME
    and SAVE it (helpers/playbook.py → coach_plays, compact rounded ops JSON
    only — no PNGs or renders in the DB; the founder's living-archive rule).
  * Loading a saved play hands the ops back to the component via a nonce'd
    arg, replacing the board.
Saved plays render to print-ready SVG on demand (playbook.play_svg) — download
here, and they embed on the printable scout sheet.

Why not streamlit-drawable-canvas: it round-trips every stroke through Python
(laggy freehand) and the project is stale against current Streamlit. A ~300-line
inline component needs no new dependency and keeps drawing at 60fps.

Coaching notation implemented (standard playbook symbols):
  pen        freehand
  cut        solid arrow            — player movement
  pass       dashed arrow           — the ball moving
  dribble    zigzag arrow           — player moving with the ball
  screen     line with a T-bar end  — pick/screen
  O / X      numbered offense circles / defense X's (auto-number 1-5) — DRAGGABLE
             with any tool (numbered pieces a player can follow around the court)
  ball       one gold ball per court, draggable; re-placing moves it
  erase      tap/drag removes whole marks (op hit-test, mirrors undo)

Drawing coordinates are stored in FEET (canvas px / scale), so strokes survive
window resizes; each court mode (half/full) keeps its own op list, so toggling
courts doesn't destroy work in the other mode.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import streamlit.components.v1 as components

import helpers.court_geom as CG
from helpers.ui import page_chrome, page_header

_cfg, ACCENT = page_chrome("Whiteboard")

page_header(
    "Whiteboard",
    sub="Sketch plays on a half or full court — solid arrow = cut, dashed = pass, "
        "zigzag = dribble, T-bar = screen, numbered O/X = players, gold dot = ball. "
        "**Drag any O, X or the ball to move it** — walk a player through the "
        "action piece by piece. Hit **⬆ Send to app**, then name it in the "
        "Playbook below to save; PNG keeps a copy on your device.")

# Court geometry, single-sourced from the shot-location model. The whiteboard
# adds the one real-world constant court_geom doesn't need: a high-school court
# is 84 ft long, so a true half court is 42 ft baseline-to-midcourt (court_geom's
# Y_MAX=38 is the shot-extent window, not the physical half court).
_GEOM = json.dumps({
    "courtW": CG.X_MAX - CG.X_MIN,        # 50 ft sideline to sideline
    "halfLen": 42.0,                      # baseline → midcourt (84 ft court)
    "laneHW": CG.LANE_HW, "laneD": CG.LANE_D,
    "ftR": CG.FT_R, "raR": CG.RA_R,
    "hoopY": CG.HOOP_Y, "rimR": 0.75, "boardY": CG.HOOP_Y - 1.25,
    "threeR": CG.THREE_R, "cornerX": CG.CORNER_X, "cbreak": CG.CBREAK,
    "centerR": CG.FT_R,                   # center circle, 6 ft radius
})

# ── the board (bidirectional component; see assets/whiteboard/index.html).
# The declare_component call lives in helpers/whiteboard_component.py — pages
# exec'd by st.navigation have no module, and declare_component requires one.
from helpers.whiteboard_component import whiteboard as _wb_component

# a Load stages {nonce, mode, ops_half, ops_full}; the component swaps its
# board only when the nonce moves, so ordinary reruns never wipe a drawing.
_load = st.session_state.get("_wb_load") or {}

_board = _wb_component(geom=_GEOM, accent=ACCENT, load=_load,
                       key="wb_board", default=None)

# ── 📓 Playbook — save / load / delete / export (per coach) ──────────────────
import helpers.auth as AUTH
import helpers.playbook as PB

_me_email = (AUTH.current_user() or {}).get("email", "")

with st.expander("📓 Playbook — save & load plays", expanded=True):
    _has_board = bool(_board and (_board.get("ops_half") or _board.get("ops_full")))
    c1, c2 = st.columns([3, 1])
    _pname = c1.text_input("Play name", key="wb_play_name",
                           placeholder="e.g. Horns flare — ATO")
    c2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if c2.button("Save play", key="wb_save_btn", type="primary",
                 disabled=not ((_pname or "").strip() and _has_board)):
        _mode = _board.get("mode", "half")
        _ops = _board.get("ops_full" if _mode == "full" else "ops_half") or []
        _err = PB.save_play(_me_email, _pname, _mode, _ops)
        if _err:
            st.warning(_err)
        else:
            st.toast(f"Saved '{_pname.strip()}' to your playbook", icon="📓")
            st.rerun()
    # ── frame sequences (spec 2.4): save 1, save 2, save 3 … then slideshow.
    # Each frame is a normal play row named '<seq> · <n>' — counts against the
    # per-coach cap like any save.
    f1, f2 = st.columns([3, 1])
    _sqname = f1.text_input("Sequence name", key="wb_seq_name",
                            placeholder="e.g. Horns flare — full action")
    f2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if f2.button("Save frame", key="wb_frame_btn",
                 disabled=not ((_sqname or "").strip() and _has_board),
                 help="Appends the current board as the next frame of this "
                      "sequence — draw the next action and hit it again."):
        _mode = _board.get("mode", "half")
        _ops = _board.get("ops_full" if _mode == "full" else "ops_half") or []
        _err, _fidx = PB.save_frame(_me_email, _sqname, _mode, _ops)
        if _err:
            st.warning(_err)
        else:
            st.toast(f"Frame {_fidx} of '{_sqname.strip()}' saved", icon="🎞")
            st.rerun()

    if not _has_board:
        st.caption("Draw a play, hit **⬆ Send to app** on the board's toolbar, "
                   "then name and save it here. Saved plays are private to you. "
                   "Use **Save frame** repeatedly to build a step-by-step "
                   "sequence you can play back below.")

    _plays = PB.list_plays(_me_email)
    if _plays:
        _by_id = {p["id"]: p for p in _plays}
        l1, l2, l3 = st.columns([3, 1, 1])
        _pid = l1.selectbox(
            "Saved plays", list(_by_id), key="wb_play_pick",
            format_func=lambda i: (f"{_by_id[i]['name']} — "
                                   f"{_by_id[i]['mode']} court · "
                                   f"{_by_id[i]['n_ops']} marks"),
            label_visibility="collapsed")
        if l2.button("Load onto board", key="wb_load_btn"):
            _pl = PB.get_play(_me_email, _pid)
            if _pl:
                st.session_state["_wb_load"] = {
                    "nonce": st.session_state.get("_wb_load", {}).get("nonce", 0) + 1,
                    "mode": _pl["mode"],
                    "ops_half": _pl["ops"] if _pl["mode"] == "half" else [],
                    "ops_full": _pl["ops"] if _pl["mode"] == "full" else []}
                st.rerun()
        if l3.button("Delete", key="wb_del_btn"):
            PB.delete_play(_me_email, _pid)
            st.toast("Play deleted")
            st.rerun()
        _sel = PB.get_play(_me_email, _pid)
        if _sel:
            st.download_button(
                "⬇ Print image (SVG)",
                PB.play_svg(_sel["ops"], _sel["mode"]),
                file_name=f"{_sel['name'].replace(' ', '_')}.svg",
                mime="image/svg+xml", key="wb_svg_dl",
                help="A crisp vector image of the play on a white court — "
                     "prints clean and drops into any doc. Saved plays also "
                     "print on the scout sheet.")

# ── 🎞 Sequence playback — step through a saved frame sequence in order ───────
_seqs = PB.list_sequences(_me_email)
if _seqs:
    with st.expander("🎞 Sequences — step through a play frame by frame",
                     expanded=False):
        s1, s2 = st.columns([3, 1])
        _sq = s1.selectbox(
            "Sequence", sorted(_seqs), key="wb_seq_pick",
            format_func=lambda s: f"{s} — {len(_seqs[s])} frame(s)",
            label_visibility="collapsed")
        _frames = _seqs[_sq]
        _fi = 0
        if len(_frames) > 1:
            _fi = st.slider("Frame", 1, len(_frames),
                            key="wb_seq_frame") - 1
        _fr = PB.get_play(_me_email, _frames[_fi]["id"])
        if _fr:
            st.caption(f"**{_fr['name']}** · {_fr['mode']} court")
            st.image(PB.play_svg(_fr["ops"], _fr["mode"]).encode("utf-8"),
                     width="stretch")
            if s2.button("Load frame onto board", key="wb_seq_load"):
                st.session_state["_wb_load"] = {
                    "nonce": st.session_state.get("_wb_load", {}).get("nonce", 0) + 1,
                    "mode": _fr["mode"],
                    "ops_half": _fr["ops"] if _fr["mode"] == "half" else [],
                    "ops_full": _fr["ops"] if _fr["mode"] == "full" else []}
                st.rerun()
