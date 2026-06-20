"""
2_Game_Tracker.py — the live command center (bench / scorer's-table screen).

The mobile PWA (tracker/) owns courtside logging; this page is the second
screen that WATCHES the game: auto-refreshing scoreboard, quarter scores, team
fouls + bonus, a live box score with foul-trouble highlighting, the live shot
chart, and the running play-by-play. Manual logging stays available — demoted
to a corrections expander for film review or as a backup when no phone is
logging. Both writers go through helpers/game_events.py, so they stay in
lockstep.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from database.db import query, execute
from helpers.ui import page_chrome, page_header, q_label
import helpers.court as COURT
import helpers.court_geom as CG
import helpers.fouls as FOULS
import helpers.game_events as GE
from PIL import Image

try:
    from streamlit_image_coordinates import streamlit_image_coordinates
    _HAVE_IMG_COORDS = True
except Exception:
    _HAVE_IMG_COORDS = False

ZONES = ["LC", "LW", "C", "RW", "RC"]
COURT_W = 340   # tap-court image px (pre-transpose width → displayed height)
REFRESH_SECS = 3

_cfg, ACCENT = page_chrome("Game Tracker")

page_header("Game Tracker",
            sub="Live command center — the phone logs courtside, this screen "
                "watches the game.")

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner=False)
def _court_base(width):
    """Cached base half-court image for tap capture (rendered once via matplotlib)."""
    return CG.court_image(width)

def load_lineup(game_id: int) -> dict:
    game = query("""
        SELECT g.id, g.team1_id, g.team2_id, g.tracked, g.date,
               t1.name AS t1_name, t2.name AS t2_name
        FROM games g JOIN teams t1 ON t1.id=g.team1_id JOIN teams t2 ON t2.id=g.team2_id
        WHERE g.id=?
    """, (game_id,))[0]
    players = query("""
        SELECT glp.team_id, p.id AS pid, p.name AS pname, t.name AS tname
        FROM game_lineup_players glp
        JOIN players p ON p.id=glp.player_id JOIN teams t ON t.id=glp.team_id
        WHERE glp.game_id=? ORDER BY glp.team_id, p.name
    """, (game_id,))
    officials = query("""
        SELECT o.id AS oid, o.name AS oname
        FROM game_lineup_officials glo JOIN officials o ON o.id=glo.official_id
        WHERE glo.game_id=?
    """, (game_id,))
    return {"game": game, "players": players, "officials": officials}

def plookup(label: str, id_map: dict):
    return id_map.get(label) if label and label != "—" else None

def _abbr(name: str) -> str:
    """'Adair Girls' → 'AG', 'North Valley' → 'NV'"""
    return "".join(w[0].upper() for w in name.split() if w)

# The on-court five live in widget state, which a browser refresh wipes —
# zeroing everyone's minutes silently. Persist the picked labels per game in
# app_settings (same key/value table data_version uses) and re-seed the
# widgets when a fresh session opens the game.
def _load_floor(game_id: int):
    row = query("SELECT value FROM app_settings WHERE key=?",
                (f"gt_floor_{game_id}",))
    if not row:
        return None
    try:
        return json.loads(row[0]["value"])
    except Exception:
        return None

def _save_floor(game_id: int, payload: dict):
    execute("INSERT INTO app_settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"gt_floor_{game_id}", json.dumps(payload)))

# ══════════════════════════════════════════════════════════════════════════════
#  LIVE BOX SCORE  (per-player stats straight from the event stream)
# ══════════════════════════════════════════════════════════════════════════════

def compute_box(game_id: int, t1id: int, t2id: int):
    """Per-player live box rows for both rosters, plus team points."""
    events = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (game_id,))

    def blank():
        return {"pts":0,"ast":0,"oreb":0,"dreb":0,"stl":0,"blk":0,"tov":0,
                "fgm":0,"fga":0,"tpm":0,"tpa":0,"ftm":0,"fta":0,"sc":0,"pf":0}

    # All players on both rosters always appear
    all_players = query(
        "SELECT id AS pid, name AS pname, team_id FROM players "
        "WHERE team_id IN (?,?) AND archived=0 ORDER BY name",
        (t1id, t2id)
    )
    stats = {p["pid"]: {**blank(), "name": p["pname"], "team_id": p["team_id"]}
             for p in all_players}
    player_team = {pid: s["team_id"] for pid, s in stats.items()}

    # Minutes: sum possession_secs for events where each player was in the lineup snapshot
    # Exclude 0-sec events (first event of a quarter at full clock has no elapsed time)
    mins_rows = query("""
        SELECT gel.player_id, SUM(ge.possession_secs) AS secs
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id = gel.event_id
        WHERE ge.game_id = ? AND ge.possession_secs > 0
        GROUP BY gel.player_id
    """, (game_id,))
    player_mins = {r["player_id"]: r["secs"] or 0.0 for r in mins_rows}

    # +/- stored directly per player from event-time snapshots
    pm_rows = query("SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?", (game_id,))
    stored_pm = {r["player_id"]: r["plus_minus"] for r in pm_rows}

    t1_pts = t2_pts = 0

    for ev in events:
        etype = ev["event_type"]
        prim  = ev["primary_player_id"]

        if etype == "shot":
            sh = prim
            if sh and sh in stats:
                stats[sh]["fga"] += 1
                stats[sh]["sc"]  += 1
                if ev["shot_type"] == 3: stats[sh]["tpa"] += 1
                if ev["shot_result"] == "make":
                    pts = ev["shot_type"]
                    stats[sh]["fgm"] += 1
                    stats[sh]["pts"] += pts
                    if ev["shot_type"] == 3: stats[sh]["tpm"] += 1
                    if stats[sh]["team_id"] == t1id: t1_pts += pts
                    else: t2_pts += pts
                    if ev["pass_from_id"] and ev["pass_from_id"] in stats:
                        stats[ev["pass_from_id"]]["ast"] += 1
            for col, key in [("pass_from_id","sc"),("shot_created_by_id","sc"),("blocked_by_id","blk")]:
                pid = ev[col]
                if pid and pid in stats: stats[pid][key] += 1
            reb = ev["rebound_by_id"]
            if reb and reb in stats and sh and sh in stats:
                stats[reb]["oreb" if player_team.get(sh)==player_team.get(reb) else "dreb"] += 1

        elif etype == "free_throw":
            sh = prim
            if sh and sh in stats:
                stats[sh]["fta"] += 1
                if ev["shot_result"] == "make":
                    stats[sh]["ftm"] += 1; stats[sh]["pts"] += 1
                    if stats[sh]["team_id"] == t1id: t1_pts += 1
                    else: t2_pts += 1
            reb = ev["rebound_by_id"]
            if reb and reb in stats and sh and sh in stats:
                stats[reb]["oreb" if player_team.get(sh)==player_team.get(reb) else "dreb"] += 1

        elif etype == "foul":
            f = ev["secondary_player_id"]
            if f and f in stats: stats[f]["pf"] += 1

        elif etype == "turnover":
            if prim and prim in stats: stats[prim]["tov"] += 1
            s = ev["stolen_by_id"]
            if s and s in stats: stats[s]["stl"] += 1

    rows = []
    for pid, s in stats.items():
        reb  = s["oreb"] + s["dreb"]
        mins = round(player_mins.get(pid, 0.0) / 60, 1)
        plus = stored_pm.get(pid, 0)
        gs   = round(s["pts"]+0.4*s["fgm"]-0.7*s["fga"]-0.4*(s["fta"]-s["ftm"])
                     +0.7*s["oreb"]+0.3*s["dreb"]+s["stl"]+0.7*s["ast"]+0.7*s["blk"]
                     -0.4*s["pf"]-s["tov"], 1)
        rows.append({"_tid": s["team_id"], "Player": s["name"], "MIN": mins,
                     "PTS": s["pts"],
                     "FG": f"{s['fgm']}-{s['fga']}", "3P": f"{s['tpm']}-{s['tpa']}",
                     "FT": f"{s['ftm']}-{s['fta']}",
                     "REB": reb, "AST": s["ast"], "STL": s["stl"], "BLK": s["blk"],
                     "TOV": s["tov"], "PF": s["pf"], "+/-": plus, "GS": gs})
    return rows, t1_pts, t2_pts

# ══════════════════════════════════════════════════════════════════════════════
#  GAME SELECTOR  — one list, newest first, live games on top of mind
# ══════════════════════════════════════════════════════════════════════════════

all_games = query("""
    SELECT g.id, g.date, g.tracked, t1.name AS t1, t2.name AS t2,
           (SELECT COUNT(*) FROM game_events ge WHERE ge.game_id = g.id) AS n_ev
    FROM games g JOIN teams t1 ON t1.id=g.team1_id JOIN teams t2 ON t2.id=g.team2_id
""")
all_games = sorted(all_games, key=lambda g: pd.to_datetime(g["date"], format="mixed", errors="coerce"), reverse=True)
if not all_games:
    st.warning("No games found. Add games in the Input Hub first.")
    st.stop()

def _g_status(g):
    if g["tracked"]:
        return "FINAL"
    return "LIVE" if g["n_ev"] else "not started"

_g_by_id = {g["id"]: g for g in all_games}
def _g_label(gid):
    g = _g_by_id[gid]
    badge = {"LIVE": " · 🔴 LIVE", "FINAL": " · FINAL", "not started": ""}[_g_status(g)]
    return f"{g['date']} — {g['t1']} vs {g['t2']}{badge}"

_default_idx = next((i for i, g in enumerate(all_games) if _g_status(g) == "LIVE"), 0)
game_id = st.selectbox("Game", [g["id"] for g in all_games], index=_default_idx,
                       format_func=_g_label, key="gt_game")

lineup      = load_lineup(game_id)
game_info   = lineup["game"]
t1id, t2id  = game_info["team1_id"], game_info["team2_id"]
t1name, t2name = game_info["t1_name"], game_info["t2_name"]
is_tracked  = bool(game_info["tracked"])

# ── End / reopen, both behind a confirm dialog ──────────────────────────────────
@st.dialog("End game?")
def _confirm_end(game_id, t1name, t2name):
    hp, ap = GE.score_from_events(game_id) or (0, 0)
    st.write(f"Freeze the final score — **{t1name} {hp} · {t2name} {ap}** — "
             "and mark the game FINAL?")
    st.caption("Rankings and dashboards pick it up immediately. "
               "You can reopen the game later if this was a mistap.")
    c1, c2 = st.columns(2)
    if c1.button("End game", type="primary", width="stretch", key="dlg_end_yes"):
        GE.finish_game(game_id)
        GE.bump_data_version()
        st.cache_data.clear()
        st.rerun()
    if c2.button("Cancel", width="stretch", key="dlg_end_no"):
        st.rerun()

@st.dialog("Reopen game?")
def _confirm_reopen(game_id):
    st.write("Unlock this FINAL game so events can be logged again?")
    st.warning("The frozen score is cleared and will be re-frozen from the "
               "event stream on the next End Game — a hand-corrected final "
               "score does not survive this.")
    c1, c2 = st.columns(2)
    if c1.button("Reopen", type="primary", width="stretch", key="dlg_reo_yes"):
        GE.reopen_game(game_id)
        GE.bump_data_version()
        st.cache_data.clear()
        st.rerun()
    if c2.button("Cancel", width="stretch", key="dlg_reo_no"):
        st.rerun()

bc1, bc2 = st.columns([4, 1])
if is_tracked:
    bc1.success("✓ Game Final")
    if bc2.button("Reopen", width="stretch"):
        _confirm_reopen(game_id)
else:
    if bc2.button("End Game", type="primary", width="stretch"):
        _confirm_end(game_id, t1name, t2name)

# ══════════════════════════════════════════════════════════════════════════════
#  COMMAND CENTER  — auto-refreshing while the game is live
# ══════════════════════════════════════════════════════════════════════════════

def _pf_style(v):
    """Foul-trouble shading on the PF column (HS: 5 fouls = out)."""
    if v >= 5: return "background-color:#d73027;color:white;font-weight:700"
    if v == 4: return "background-color:#a04a12;color:white"
    if v == 3: return "background-color:#7a5d1e"
    return ""

def _render_command_center():
    events_asc = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id",
                       (game_id,))
    ls = GE.live_state(game_id, n_events=0)
    hp, ap = ls["home_pts"], ls["away_pts"]
    cur_q = max((ev["quarter"] for ev in events_asc), default=1)

    # Fresh name maps each tick — phone-side quick-adds appear without a reload
    proster = query("SELECT id, name, team_id FROM players WHERE team_id IN (?,?)",
                    (t1id, t2id))
    pid_name = {p["id"]: p["name"] for p in proster}
    pid_team = {p["id"]: p["team_id"] for p in proster}
    oid_name = {o["id"]: o["name"] for o in query("SELECT id, name FROM officials")}
    def pn(pid): return pid_name.get(pid, f"ID:{pid}") if pid else None
    def on_(oid): return oid_name.get(oid, f"ID:{oid}") if oid else None

    # ── scoreboard ──────────────────────────────────────────────────────────────
    sc1, sc2, sc3 = st.columns([2, 1, 2])
    sc1.metric(t1name, hp)
    sc2.markdown(
        f"<div style='text-align:center;padding-top:8px'>"
        f"<div style='font-size:1.3em'>{q_label(cur_q)}</div>"
        f"<div style='color:#888;font-size:0.85em'>poss {ls['home_poss']}–{ls['away_poss']}</div>"
        f"</div>", unsafe_allow_html=True)
    sc3.metric(t2name, ap)

    # ── team fouls + bonus (NFHS since 2023-24: fouls reset each quarter,
    #    two-shot bonus on the 5th team foul of the quarter) ────────────────────
    tf = FOULS.team_foul_by_quarter(events=events_asc)
    fc1, fc2 = st.columns(2)
    for col, tid, tname in ((fc1, t1id, t1name), (fc2, t2id, t2name)):
        by_q = tf.get(tid, {}).get("by_q", {})
        # OT extends Q4 for team fouls — no reset, the count carries over.
        n = (sum(by_q.get(q, 0) for q in range(4, cur_q + 1)) if cur_q > 4
             else by_q.get(cur_q, 0))
        bonus = (" &nbsp;<span style='background:#d73027;color:white;padding:1px 8px;"
                 "border-radius:8px;font-size:0.8em;font-weight:700'>BONUS</span>"
                 if n >= 5 else "")
        col.markdown(f"**{tname}** — {q_label(cur_q)} team fouls: {n}{bonus}",
                     unsafe_allow_html=True)

    # ── quarter scores ──────────────────────────────────────────────────────────
    qs = ls["quarters"]
    if qs:
        qlist = sorted(qs, key=int)
        r1, r2 = {"Team": t1name}, {"Team": t2name}
        for q in qlist:
            r1[q_label(int(q))] = qs[q]["home"]
            r2[q_label(int(q))] = qs[q]["away"]
        r1["T"], r2["T"] = hp, ap
        st.dataframe(pd.DataFrame([r1, r2]), hide_index=True, width="stretch")

    # ── live box score with foul-trouble shading ────────────────────────────────
    box_rows, _, _ = compute_box(game_id, t1id, t2id)
    bt1, bt2 = st.tabs([t1name, t2name])
    for tab, tid in ((bt1, t1id), (bt2, t2id)):
        rows = [{k: v for k, v in r.items() if k != "_tid"}
                for r in box_rows if r["_tid"] == tid]
        if not rows:
            tab.info("No roster for this team yet.")
            continue
        df = (pd.DataFrame(rows)
              .sort_values(["PTS", "MIN"], ascending=False)
              .reset_index(drop=True))
        tab.dataframe(df.style.map(_pf_style, subset=["PF"]),
                      hide_index=True, width="stretch",
                      height=min(420, 38 + 35 * len(df)))
    st.caption("PF shading: 3 amber · 4 orange · 5 red (fouled out). "
               "MIN from event-clock elapsed time; needs the on-court five set "
               "wherever the events are logged.")

    # ── live shot chart (tap-captured x/y from the phone or the form below) ────
    shots = query("""
        SELECT ge.shot_x AS x, ge.shot_y AS y, ge.shot_result, ge.shot_type,
               p.team_id AS tid
        FROM game_events ge JOIN players p ON p.id = ge.primary_player_id
        WHERE ge.game_id=? AND ge.event_type='shot'
          AND ge.shot_x IS NOT NULL AND ge.shot_y IS NOT NULL""", (game_id,))
    if shots:
        cc1, cc2 = st.columns(2)
        for col, tid, tname in ((cc1, t1id, t1name), (cc2, t2id, t2name)):
            tshots = [{"x": s["x"], "y": s["y"],
                       "make": s["shot_result"] == "make",
                       "value": s["shot_type"]} for s in shots if s["tid"] == tid]
            fig, n = COURT.shot_map(tshots, title=f"{tname} — {len(tshots)} shots")
            with col:
                if n:
                    st.plotly_chart(fig, width="stretch",
                                    key=f"cc_court_{game_id}_{tid}")
                else:
                    st.caption(f"{tname}: no located shots yet.")
    else:
        st.caption("No located shots yet — taps from the phone (or the court "
                   "below) land here as the game goes.")

    # ── play-by-play with running score ─────────────────────────────────────────
    st.markdown("#### Play-by-Play")
    if not events_asc:
        st.info("No events logged yet.")
        return

    # Walk in GAME order (quarter, clock), not insertion order — film-review
    # backfills and editor fixes insert rows out of chronology, which would
    # make the running score column lie.
    events_chrono = sorted(events_asc,
                           key=lambda e: (e["quarter"],
                                          -GE.time_to_secs(e["time"]), e["id"]))
    log_rows, s1, s2 = [], 0, 0
    for ev in events_chrono:
        et = ev["event_type"]
        pts = 0
        if et == "shot" and ev["shot_result"] == "make":
            pts = ev["shot_type"]
        elif et == "free_throw" and ev["shot_result"] == "make":
            pts = 1
        if pts:
            scorer_team = pid_team.get(ev["primary_player_id"])
            if scorer_team == t1id: s1 += pts
            elif scorer_team == t2id: s2 += pts

        if et == "shot":
            verb = "makes" if ev["shot_result"] == "make" else "misses"
            desc = f"{pn(ev['primary_player_id']) or '—'} {verb} {ev['shot_type']}PT"
            if ev["zone"]: desc += f" ({ev['zone']})"
            for col, word in (("pass_from_id", "assist"), ("rebound_by_id", "reb"),
                              ("blocked_by_id", "blk")):
                if ev[col]: desc += f" · {word} {pn(ev[col])}"
        elif et == "free_throw":
            verb = "makes" if ev["shot_result"] == "make" else "misses"
            desc = f"{pn(ev['primary_player_id']) or '—'} {verb} FT"
            if ev["rebound_by_id"]: desc += f" · reb {pn(ev['rebound_by_id'])}"
        elif et == "foul":
            desc = f"Foul on {pn(ev['secondary_player_id']) or '—'}"
            if ev["primary_player_id"]: desc += f" (fouled {pn(ev['primary_player_id'])})"
            if ev["official_id"]: desc += f" · ref {on_(ev['official_id'])}"
        elif et == "turnover":
            desc = f"Turnover {pn(ev['primary_player_id']) or '—'}"
            if ev["stolen_by_id"]: desc += f" · steal {pn(ev['stolen_by_id'])}"
        else:
            desc = et
        log_rows.append({"Q": q_label(ev["quarter"]), "Time": ev["time"],
                         "Play": desc, "Score": f"{s1}–{s2}"})

    log_rows.reverse()   # newest first
    pbp_df = pd.DataFrame(log_rows)
    st.dataframe(pbp_df, width="stretch", hide_index=True,
                 height=min(420, 38 + 35 * len(pbp_df)))
    dc1, dc2 = st.columns(2)
    dc1.download_button("Export play-by-play (CSV)", pbp_df.to_csv(index=False),
                        file_name=f"pbp_{game_id}.csv", mime="text/csv",
                        key="cc_csv")
    # Undo is a live-game tool only: on a FINAL game it would desync the
    # frozen score from the event stream (the Event Editor handles that case
    # drift-aware). Re-check tracked at click time — the phone may have
    # finished the game while this screen sat open.
    if not is_tracked and dc2.button("Delete last event", type="secondary",
                                     key="cc_undo"):
        if query("SELECT tracked FROM games WHERE id=?", (game_id,))[0]["tracked"]:
            st.warning("Game was finalized while this screen was open — "
                       "reopen it (top right) before deleting events.")
        elif GE.undo_last_event(game_id):
            # Shared undo path (helpers.game_events): reverses +/- over the
            # event's lineup snapshot, then deletes (cascade clears
            # game_event_lineup).
            st.cache_data.clear()
            st.rerun(scope="app")

if is_tracked:
    _render_command_center()
else:
    st.fragment(run_every=REFRESH_SECS)(_render_command_center)()
    st.caption(f"Auto-refreshes every {REFRESH_SECS} s while the game is live.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  MANUAL LOGGING & CORRECTIONS  — backup writer / film review
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("### Logging & corrections")

if is_tracked:
    st.info("Game is FINAL — logging is locked. Reopen the game (top right) to "
            "resume logging here, or use the Event Editor page for one-off fixes.")
else:
    # ── the floor: on-court five + officials (feeds minutes and +/-) ───────────
    with st.expander("Floor — on-court five & officials", expanded=False):
        t1_db  = query("SELECT id, name, number FROM players WHERE team_id=? AND archived=0 ORDER BY number, name", (t1id,))
        t2_db  = query("SELECT id, name, number FROM players WHERE team_id=? AND archived=0 ORDER BY number, name", (t2id,))
        all_offs = query("SELECT id, name FROM officials WHERE archived=0 ORDER BY name")

        t1_opts  = ["—"] + [f"#{p['number']} {p['name']}" for p in t1_db]
        t2_opts  = ["—"] + [f"#{p['number']} {p['name']}" for p in t2_db]
        off_opts_all = ["—"] + [o["name"] for o in all_offs]
        t1_pmap  = {f"#{p['number']} {p['name']}": p["id"] for p in t1_db}
        t2_pmap  = {f"#{p['number']} {p['name']}": p["id"] for p in t2_db}
        off_imap = {o["name"]: o["id"] for o in all_offs}

        # Re-seed widget state from the persisted floor on a fresh session, so a
        # browser refresh doesn't silently zero everyone's minutes. The floor is
        # stored as ids (labels change when a jersey number or name is edited
        # mid-game); a missing/archived id just leaves its slot on "—".
        t1_ilab  = {p["id"]: f"#{p['number']} {p['name']}" for p in t1_db}
        t2_ilab  = {p["id"]: f"#{p['number']} {p['name']}" for p in t2_db}
        off_ilab = {o["id"]: o["name"] for o in all_offs}

        _stored = _load_floor(game_id) or {}
        for grp, ilab in (("t1", t1_ilab), ("t2", t2_ilab), ("offs", off_ilab)):
            for i, pid in enumerate(_stored.get(grp, [])):
                k = f"{grp}_{game_id}_{i}"
                lbl = ilab.get(pid)
                if k not in st.session_state and lbl is not None:
                    st.session_state[k] = lbl

        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            st.markdown(f"**{t1name}**")
            cur_t1 = [st.selectbox(f"Slot {i+1}", t1_opts, key=f"t1_{game_id}_{i}") for i in range(5)]
        with lc2:
            st.markdown(f"**{t2name}**")
            cur_t2 = [st.selectbox(f"Slot {i+1}", t2_opts, key=f"t2_{game_id}_{i}") for i in range(5)]
        with lc3:
            st.markdown("**Officials**")
            cur_offs = [st.selectbox(f"Slot {i+1}", off_opts_all, key=f"offs_{game_id}_{i}") for i in range(3)]

        _floor_now = {"t1": [t1_pmap.get(s) for s in cur_t1],
                      "t2": [t2_pmap.get(s) for s in cur_t2],
                      "offs": [off_imap.get(s) for s in cur_offs]}
        # Persist only on a change made IN THIS SESSION (vs the previous run),
        # so a stale second screen that merely rerenders never clobbers the
        # floor another device saved.
        _prev_key = f"gt_floor_prev_{game_id}"
        _prev = st.session_state.get(_prev_key)
        if _prev is not None and _floor_now != _prev:
            _save_floor(game_id, _floor_now)
        st.session_state[_prev_key] = _floor_now

        # Current on-court players (non-"—" selections) with their team
        on_court = (
            [(t1_pmap[s], t1id) for s in cur_t1 if s != "—"] +
            [(t2_pmap[s], t2id) for s in cur_t2 if s != "—"]
        )
        # Dedupe — the same player can be picked in two slots. Warn, never block logging.
        _seen = set()
        _deduped = []
        for pid, tid in on_court:
            if pid not in _seen:
                _seen.add(pid)
                _deduped.append((pid, tid))
        if len(_deduped) < len(on_court):
            st.warning("Duplicate lineup selection dropped — the same player was picked in more than one slot.")
        on_court = _deduped
        if on_court:
            for _tname, _n in ((t1name, sum(1 for _, t in on_court if t == t1id)),
                               (t2name, sum(1 for _, t in on_court if t == t2id))):
                if _n < 5:
                    st.warning(f"{_tname}: only {_n} of 5 lineup slots selected.")
        on_court_offs = [off_imap[s] for s in cur_offs if s != "—"]

    # Build player option lists for the event form
    all_player_rows = query(
        "SELECT id AS pid, name AS pname, number, team_id FROM players "
        "WHERE team_id IN (?,?) AND archived=0 ORDER BY name", (t1id, t2id)
    )
    pid_to_row = {p["pid"]: p for p in all_player_rows}

    on_court_labels = []
    for pid, tid in on_court:
        p = pid_to_row.get(pid)
        if p:
            abbr = _abbr(t1name if tid == t1id else t2name)
            on_court_labels.append((f"{abbr} #{p['number']} {p['pname']}", pid))

    all_opts = ["—"] + [lbl for lbl, _ in on_court_labels]
    all_id   = {lbl: pid for lbl, pid in on_court_labels}
    off_opts = ["—"] + [s for s in cur_offs if s != "—"]
    off_eid  = off_imap

    # ── manual event form ───────────────────────────────────────────────────────
    with st.expander("Log an event manually (film review / backup writer)",
                     expanded=False):
        if not on_court:
            st.info("Pick the on-court five in the Floor expander above first.")
        else:
            event_type = st.selectbox("Event Type", ["Shot", "Free Throw", "Foul", "Turnover"], key="ev_type")

            cap_key = f"shot_xy_{game_id}"
            if event_type != "Shot" and cap_key in st.session_state:
                # drop the stale marker AND remount the tap component, else its
                # remembered click re-seeds the old location on return to Shot
                st.session_state.pop(cap_key)
                st.session_state[f"tapgen_{game_id}"] = \
                    st.session_state.get(f"tapgen_{game_id}", 0) + 1

            _last_time = st.session_state.get(f"last_time_{game_id}", "8:00")
            _last_q    = st.session_state.get(f"last_q_{game_id}", 1)
            try:
                _lm, _ls = _last_time.split(":")
                _last_mins = int(_lm)
                _last_secs = int(_ls)
            except Exception:
                _last_mins, _last_secs = 8, 0

            def _time_row():
                mc, sc, qc = st.columns(3)
                return (mc.number_input("Minutes", min_value=0, max_value=8, step=1,
                                        value=min(_last_mins, 8)),
                        sc.number_input("Seconds", min_value=0, max_value=59, step=1, value=_last_secs),
                        qc.number_input("Quarter", min_value=1, max_value=10, step=1, value=int(_last_q)))

            if event_type == "Shot":
                cur = st.session_state.get(cap_key)
                # The tap component keeps returning its LAST click while its key
                # is unchanged — after a submit pops cap_key, that stale click
                # would silently re-attach the previous shot's location to the
                # next one. Versioning the key (nonce bumped on submit) remounts
                # the component clean.
                _tapgen = st.session_state.get(f"tapgen_{game_id}", 0)
                court_col, form_col = (st.columns([1, 3]) if _HAVE_IMG_COORDS
                                       else (None, st.container()))

                # ── court tap, left column (outside the form so each tap reruns to
                #    redraw the marker) → x/y, auto zone + 2/3 ─────────────────────
                if _HAVE_IMG_COORDS:
                    with court_col:
                        W = COURT_W
                        H = CG.image_height(W)
                        base = _court_base(W)
                        shown = (CG.court_image_with_marker(cur[0], cur[1], base=base, width=W)
                                 if cur else base)
                        disp = shown.transpose(Image.TRANSPOSE)   # sideways: hoop right, halfcourt-POV left = top
                        st.caption("Tap where the shot was taken")
                        val = streamlit_image_coordinates(disp, width=disp.width,
                                                          key=f"court_tap_{game_id}_{_tapgen}")
                        if val is not None:
                            # invert the transpose: display (x,y) → original (y,x) → feet
                            ox, oy = val["y"], val["x"]
                            fx, fy = CG.feet_from_px(ox, oy, W, H)
                            if cur is None or abs(cur[0] - fx) > 1e-6 or abs(cur[1] - fy) > 1e-6:
                                st.session_state[cap_key] = (fx, fy)
                                st.rerun()
                        if cur:
                            st.caption(f"**{CG.shot_value(*cur)}PT · {CG.zone_from_xy(*cur)}** · "
                                       f"{CG.shot_distance(*cur):.0f} ft — tap again to move")
                        else:
                            st.caption("Zone & 2/3 auto-set from your tap "
                                       "(skip → logs 2PT, blank zone)")

                # ── shot detail form, right column (in line with the court) ───────
                with form_col:
                    with st.form("event_form", clear_on_submit=True):
                        mins_input, secs_input, quarter = _time_row()
                        st.markdown("---")
                        _cap = st.session_state.get(cap_key)
                        if _HAVE_IMG_COORDS:
                            # location, zone AND 2/3 come from the tap — no type/zone dropdowns
                            r1a, r1b = st.columns([3, 1])
                            shooter = r1a.selectbox("Shooter", all_opts[1:])
                            result  = r1b.selectbox("Result", ["make", "miss"])
                            zone = CG.zone_from_xy(*_cap) if _cap else None
                            shot_type = CG.shot_value(*_cap) if _cap else 2
                            r2a, r2b = st.columns(2)
                            pass_from = r2a.selectbox("Pass From", all_opts)
                            created   = r2b.selectbox("Shot Created By", all_opts)
                        else:
                            r1a, r1b, r1c = st.columns([3, 1, 1])
                            shooter   = r1a.selectbox("Shooter", all_opts[1:])
                            shot_type = r1b.selectbox("Type", ["2", "3"])
                            result    = r1c.selectbox("Result", ["make", "miss"])
                            r2a, r2b, r2c = st.columns([1, 2, 2])
                            zone      = r2a.selectbox("Zone", ZONES)
                            pass_from = r2b.selectbox("Pass From", all_opts)
                            created   = r2c.selectbox("Shot Created By", all_opts)
                        # player pickers
                        r3a, r3b, r3c = st.columns(3)
                        guarded   = r3a.selectbox("Guarded By", all_opts)
                        rebound   = r3b.selectbox("Rebound By", all_opts)
                        blocked   = r3c.selectbox("Blocked By", all_opts)
                        submitted = st.form_submit_button("Log Event", type="primary", width="stretch")
            else:
                with st.form("event_form", clear_on_submit=True):
                    mins_input, secs_input, quarter = _time_row()
                    st.markdown("---")
                    if event_type == "Free Throw":
                        c1, c2, c3 = st.columns([3, 1, 2])
                        shooter = c1.selectbox("Shooter", all_opts[1:])
                        result  = c2.selectbox("Result", ["make", "miss"])
                        rebound = c3.selectbox("Rebound By", all_opts)

                    elif event_type == "Foul":
                        c1, c2, c3 = st.columns([2, 2, 1])
                        fouled   = c1.selectbox("Player Fouled", all_opts[1:])
                        fouler   = c2.selectbox("Player Who Fouled", all_opts[1:])
                        official = c3.selectbox("Official", off_opts)

                    elif event_type == "Turnover":
                        c1, c2 = st.columns(2)
                        tov_p  = c1.selectbox("Turnover By", all_opts[1:])
                        stolen = c2.selectbox("Stolen By", all_opts)

                    submitted = st.form_submit_button("Log Event", type="primary", width="stretch")

            if submitted:
                q = int(quarter)
                t = f"{int(mins_input)}:{int(secs_input):02d}"
                # The clock can't show more time than the period holds
                # (8:00 quarters, 4:00 OTs) — a typo here corrupts possession
                # seconds for every later event in the quarter. And the phone
                # may have finished the game while this screen sat open —
                # logging into a FINAL game desyncs its frozen score.
                if GE.time_to_secs(t) > GE.quarter_start_secs(q):
                    st.error(f"{t} is more than a {'quarter' if q <= 4 else 'OT period'} "
                             f"holds ({int(GE.quarter_start_secs(q) // 60)}:00) — not logged.")
                    submitted = False
                elif query("SELECT tracked FROM games WHERE id=?", (game_id,))[0]["tracked"]:
                    st.error("Game was finalized while this screen was open — "
                             "not logged. Reopen the game to keep logging.")
                    submitted = False

            if submitted:
                # Persist so the form re-opens with the same time/quarter
                st.session_state[f"last_time_{game_id}"] = t
                st.session_state[f"last_q_{game_id}"]    = q

                # Build the event payload; helpers.game_events owns possession secs,
                # the lineup snapshot, +/- and x/y -> zone/2-3 (shared with the mobile
                # tracker API, so both writers stay in lockstep).
                ev = {"quarter": q, "time": t}
                if event_type == "Shot":
                    _xy = st.session_state.get(cap_key)
                    _sx, _sy = _xy if _xy else (None, None)
                    ev.update(event_type="shot",
                              primary_player_id=plookup(shooter, all_id),
                              shot_result=result, shot_x=_sx, shot_y=_sy,
                              shot_type=int(shot_type), zone=zone,
                              pass_from_id=plookup(pass_from, all_id),
                              shot_created_by_id=plookup(created, all_id),
                              rebound_by_id=plookup(rebound, all_id),
                              blocked_by_id=plookup(blocked, all_id),
                              guarded_by_id=plookup(guarded, all_id))
                    st.session_state.pop(cap_key, None)   # reset location for next shot
                    # remount the tap component so its stale click can't re-seed
                    st.session_state[f"tapgen_{game_id}"] = \
                        st.session_state.get(f"tapgen_{game_id}", 0) + 1

                elif event_type == "Free Throw":
                    ev.update(event_type="free_throw",
                              primary_player_id=plookup(shooter, all_id),
                              shot_result=result,
                              rebound_by_id=plookup(rebound, all_id))

                elif event_type == "Foul":
                    ev.update(event_type="foul",
                              primary_player_id=plookup(fouled, all_id),
                              secondary_player_id=plookup(fouler, all_id),
                              official_id=(off_eid.get(official)
                                           if official and official != "—" else None))

                elif event_type == "Turnover":
                    ev.update(event_type="turnover",
                              primary_player_id=plookup(tov_p, all_id),
                              stolen_by_id=plookup(stolen, all_id))

                GE.log_event(game_id, ev, on_court, on_court_offs)
                st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  TEAM NOTES
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("📋 Team Notes", expanded=False):
    import helpers.scoutboard as SB
    st.caption("Private to you — each coach keeps their own notes.")
    notes_col1, notes_col2 = st.columns(2)
    for col, tid, tname in [(notes_col1, t1id, t1name), (notes_col2, t2id, t2name)]:
        with col:
            st.markdown(f"**{tname}**")
            SB.render_notes(tid, kind="team", key_prefix=f"gt_{game_id}",
                            label="Notes", height=180,
                            placeholder="Scouting notes, tendencies, game plan…")

# ══════════════════════════════════════════════════════════════════════════════
#  QUICK ADD — spreadsheet style
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("＋ Quick Add Player / Official"):
    qa_l, qa_r = st.columns(2)

    with qa_l:
        st.markdown("**Add Players**")
        qa_tm_map  = {t1name: t1id, t2name: t2id}
        qa_tnames  = [t1name, t2name]

        qa_p_orig = st.session_state.get("_qa_players_orig",
                        pd.DataFrame(columns=["team","name","number","height","wingspan","weight","handedness"]))

        st.data_editor(
            qa_p_orig,
            key="qa_players_editor",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "team":     st.column_config.SelectboxColumn("Team",         options=qa_tnames, required=True),
                "name":     st.column_config.TextColumn("Player Name",        required=True),
                "number":   st.column_config.NumberColumn("Number",           min_value=0, max_value=999, step=1),
                "height":   st.column_config.NumberColumn("Height (in)",      min_value=0.0, step=0.5),
                "wingspan": st.column_config.NumberColumn("Wingspan (in)",    min_value=0.0, step=0.5),
                "weight":   st.column_config.NumberColumn("Weight (lbs)",     min_value=0.0, step=1.0),
                "handedness": st.column_config.SelectboxColumn("Hand", options=["right","left"], default="right"),
            },
        )
        if st.button("Save Players", key="qa_save_players", type="primary"):
            delta = st.session_state.get("qa_players_editor", {})
            # Merge added_rows with any edits applied to those same rows
            added = list(delta.get("added_rows", []))
            for idx_str, changes in delta.get("edited_rows", {}).items():
                idx = int(idx_str)
                if idx < len(added):
                    added[idx] = {**added[idx], **changes}
            saved = skipped = 0
            for r in added:
                name = r.get("name", "").strip()
                team = r.get("team")
                if not name or not team:
                    continue
                tid = qa_tm_map[team]
                exists = query(
                    "SELECT id FROM players WHERE team_id=? AND name=? AND archived=0",
                    (tid, name)
                )
                if exists:
                    skipped += 1
                    continue
                execute(
                    "INSERT INTO players (team_id, name, number, height, wingspan, weight, handedness) VALUES (?,?,?,?,?,?,?)",
                    (tid, name, int(r.get("number") or 0),
                     r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None,
                     "left" if r.get("handedness") == "left" else "right")
                )
                saved += 1
            if saved or skipped:
                msg = f"Added {saved} player(s)."
                if skipped:
                    msg += f" {skipped} skipped (already exist)."
                st.success(msg)
                # Invalidate Input Hub player cache so it reloads from DB
                st.session_state.pop("_players_orig", None)
                st.session_state.pop("_qa_players_orig", None)
                st.session_state.pop("qa_players_editor", None)
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("Fill in at least one player row.")

        # Flip handedness on existing players without leaving the tracker.
        st.markdown("**Edit shooting hand**")
        _hand_rows = query(
            "SELECT id, name, number, team_id, handedness FROM players "
            "WHERE team_id IN (?,?) AND archived=0 ORDER BY team_id, number, name",
            (t1id, t2id))
        if not _hand_rows:
            st.caption("No players yet.")
        else:
            _tname_by = {t1id: t1name, t2id: t2name}
            _hdf = pd.DataFrame([{"id": r["id"], "team": _tname_by.get(r["team_id"], ""),
                                  "player": f"#{r['number']} {r['name']}",
                                  "handedness": r["handedness"] or "right"} for r in _hand_rows])
            _hed = st.data_editor(
                _hdf, hide_index=True, width="stretch", key="gt_hand_editor",
                column_config={
                    "id": None,
                    "team": st.column_config.TextColumn("Team", disabled=True),
                    "player": st.column_config.TextColumn("Player", disabled=True),
                    "handedness": st.column_config.SelectboxColumn(
                        "Hand", options=["right", "left"], default="right"),
                })
            if st.button("Save hands", key="gt_save_hands"):
                for _, r in _hed.iterrows():
                    execute("UPDATE players SET handedness=? WHERE id=?",
                            ("left" if r["handedness"] == "left" else "right", int(r["id"])))
                st.session_state.pop("_players_orig", None)
                st.cache_data.clear()
                st.success("Shooting hands saved.")
                st.rerun()

    with qa_r:
        st.markdown("**Add Officials**")
        qa_o_orig = st.session_state.get("_qa_officials_orig",
                        pd.DataFrame(columns=["name","official_id"]))

        st.data_editor(
            qa_o_orig,
            key="qa_officials_editor",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "name":        st.column_config.TextColumn("Official Name", required=True),
                "official_id": st.column_config.NumberColumn("Official ID", required=True, step=1),
            },
        )
        if st.button("Save Officials", key="qa_save_officials", type="primary"):
            delta = st.session_state.get("qa_officials_editor", {})
            added = delta.get("added_rows", [])
            saved = 0
            for r in added:
                if r.get("name","").strip() and r.get("official_id") is not None:
                    execute("INSERT OR IGNORE INTO officials (name, official_id) VALUES (?,?)",
                            (r["name"].strip(), int(r["official_id"])))
                    saved += 1
            if saved:
                st.success(f"Added {saved} official(s).")
                st.session_state.pop("_qa_officials_orig", None)
                st.session_state.pop("qa_officials_editor", None)
                st.cache_data.clear()
                st.rerun()
            else:
                st.warning("Fill in at least one official row.")
