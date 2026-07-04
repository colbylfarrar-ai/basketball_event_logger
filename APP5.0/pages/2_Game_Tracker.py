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
import helpers.auth as AUTH
import helpers.court as COURT
import helpers.entitlement as ENT
import helpers.court_geom as CG
import helpers.defenses as DEF
import helpers.playtypes as PT
import helpers.fouls as FOULS
import helpers.game_events as GE
import helpers.seasons as SEAS
import helpers.turnovers as TOV
from PIL import Image

try:
    from streamlit_image_coordinates import streamlit_image_coordinates
    _HAVE_IMG_COORDS = True
except Exception:
    _HAVE_IMG_COORDS = False

ZONES = ["LC", "LW", "C", "RW", "RC"]
COURT_W = 265   # tap-court image px (rim at top, half-court at bottom — matches PWA)
REFRESH_SECS = 3


@st.cache_data(ttl=600, show_spinner=False)
def _scout_cues(team_id):
    """A team's PREGAME scouting read from its PRIOR tracked games (not this game's
    live events — coaches fast-track live, so live depth is thin). Shot diet +
    side-lean (force them the other way) + hot zone + top scorers. Cached per team;
    returns empty/graceful when the team has no tracked history."""
    import helpers.insights_team as IT
    ten = IT.shot_tendencies(team_id)
    scorers = []
    grow = query("SELECT gender FROM teams WHERE id=?", (team_id,))
    gender = grow[0]["gender"] if grow else None
    if gender:
        try:
            import helpers.player_ratings as PR
            tbl = PR.player_stat_table(gender=gender, min_games=1)
            mine = [r for r in tbl.values()
                    if r.get("team_id") == team_id and r.get("PPG")]
            mine.sort(key=lambda r: -(r.get("PPG") or 0))
            scorers = [(r["name"], r["PPG"]) for r in mine[:3]]
        except Exception:
            scorers = []
    return {"ten": ten, "scorers": scorers}


def _has_cues(c):
    return bool(c["ten"].get("available") or c["scorers"])

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

    # All players on both rosters always appear — the roster is the GAME's
    # season (retro-tracking: a past game lists who actually played that year).
    _rc, _rp = SEAS.roster_clause(SEAS.game_season(game_id))
    all_players = query(
        f"SELECT id AS pid, name AS pname, team_id FROM players "
        f"WHERE team_id IN (?,?) AND {_rc} ORDER BY name",
        (t1id, t2id, *_rp)
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

# Retro-tracking: rosters below are scoped to the GAME's season, so a past
# game surfaces the players who actually played it (rollover-archived rows).
_gszn = SEAS.game_season(game_id)
_roster_c, _roster_p = SEAS.roster_clause(_gszn)
if not SEAS.is_current(_gszn):
    st.caption(f"📅 **{_gszn} season game** — rosters and quick-adds use that "
               "season's players; nothing here touches current-season stats.")

# Tier gate: event-logging AND the live tracked depth this screen renders (live box,
# shot chart, win-probability, possession line, foul/bonus) are a Paid feature.
# Tracking ANY team is allowed (track-to-scout) — the only gate is Paid; no own-team
# or co-op restriction, so a paid coach can scout any opponent by tracking them.
# EXCEPTION: a Free coach gets ONE game free (their own team's earliest) so they can
# log it on the court tap below and watch the command center light up — the demo hook.
_ident = AUTH.current_user()
if not ENT.can_see_tracked_game_view(_ident, game_id):
    st.info(ENT.MSG_PAID)
    _demo = ENT.free_demo_game_id(_ident)
    if _demo is not None and _demo != game_id and _demo in _g_by_id:
        st.success(ENT.MSG_FREE_DEMO)
        st.caption(f"Your free game: **{_g_label(_demo)}** — pick it in the "
                   "Game selector above.")
    st.stop()
# Possession + efficiency depth (the poss line, win-probability, courtside
# leverage / run-alert / late-game, foul-out projection) is Paid even on the free
# demo game — a Free coach gets the SCORE, live box score and shot chart as the
# hook, never possession/efficiency analytics. Guarded by _paid_view below.
_paid_view = ENT.has_paid_plan(_ident)

# ── Pregame scouting cues — each team's tendencies from its PRIOR tracked games
#    (a scout read to glance at pregame / during fast-mode logging), NOT computed
#    from this game's live events. Paid depth; hidden when neither team has a
#    tracked history (untracked opponent → no panel). ──────────────────────────
if _paid_view:
    _cue1, _cue2 = _scout_cues(t1id), _scout_cues(t2id)
    if _has_cues(_cue1) or _has_cues(_cue2):
        with st.expander("📋 Pregame scouting cues — team tendencies from tracked "
                         "history", expanded=False):
            st.caption("Built from each team's PRIOR tracked games — a pregame "
                       "read, not this game's live stats. Scout the opponent's "
                       "column; force them off their strong side.")
            _sccols = st.columns(2)
            for _col, _tnm, _cue in ((_sccols[0], t1name, _cue1),
                                     (_sccols[1], t2name, _cue2)):
                with _col:
                    st.markdown(f"**{_tnm}**")
                    if not _has_cues(_cue):
                        st.caption("No tracked history yet.")
                        continue
                    _t = _cue["ten"]
                    if _t.get("available"):
                        _sd = _t["side"]
                        _lean = max(_sd, key=_sd.get)
                        _force = min(_sd, key=_sd.get)
                        st.markdown(
                            f"- Shot diet: **{_t['rim_rate']*100:.0f}%** rim · "
                            f"{_t['mid_rate']*100:.0f}% mid · "
                            f"**{_t['three_rate']*100:.0f}%** three")
                        st.markdown(
                            f"- Leans **{_lean}** ({_sd[_lean]*100:.0f}% of shots) "
                            f"— force them **{_force}**")
                        _zz = [z for z in _t["zones"]
                               if z["poss"] >= 3 and z["PPP"] is not None]
                        _zz.sort(key=lambda z: -z["PPP"])
                        if _zz:
                            st.markdown(
                                f"- Hot zone: **{_zz[0]['label']}** "
                                f"({_zz[0]['PPP']:.2f} PPP on {_zz[0]['poss']} shots)")
                    if _cue["scorers"]:
                        _who = " · ".join(f"{n} {p:.1f}p" for n, p in _cue["scorers"])
                        st.markdown(f"- Key scorers: {_who}")
if not _paid_view:
    # On the free-demo game: make it obvious this is the one free game.
    st.success("🎁 This is your **free** game — log it below and watch the live "
               "box score and shot chart fill in. Upgrade to unlock possession "
               "& efficiency analytics and track every game.")

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
    # Possession count is Paid-only — a Free demo viewer sees the period, not poss.
    _poss_line = (f"<div style='color:var(--subtext);font-size:0.85em'>"
                  f"poss {ls['home_poss']}–{ls['away_poss']}</div>"
                  if _paid_view else "")
    sc2.markdown(
        f"<div style='text-align:center;padding-top:8px'>"
        f"<div style='font-size:1.3em'>{q_label(cur_q)}</div>"
        f"{_poss_line}"
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
        bonus = (" &nbsp;<span style='background:var(--bad);color:white;"
                 "padding:1px 8px;border-radius:8px;font-size:0.8em;"
                 "font-weight:700'>BONUS</span>" if n >= 5 else "")
        col.markdown(f"**{tname}** — {q_label(cur_q)} team fouls: {n}{bonus}",
                     unsafe_allow_html=True)

    # ── live win-probability strip — the cutting-edge moment the live command
    #    center was missing. Builds an (elapsed, margin) walk from the scoring
    #    events and renders the shared wp_ribbon. Fully guarded: any failure
    #    silently skips so live tracking is never put at risk. ──────────────────
    try:
        if not _paid_view:
            raise RuntimeError("paid")   # win-prob/GEI is Paid depth — skip for Free demo
        import helpers.win_probability as _WP
        from helpers.ui import wp_ribbon as _wp_ribbon, mini_tile as _mini
        from helpers.settings_utils import get_setting as _get_setting
        _acc = _get_setting("accent_color", "#f0a500")
        _QSEC = 480   # 8-min HS quarters (win_probability.GAME_SECONDS / 4)
        _mc, _s1, _s2 = [(0.0, 0)], 0, 0
        for _ev in sorted(events_asc,
                          key=lambda e: (e["quarter"],
                                         -GE.time_to_secs(e["time"]), e["id"])):
            _p = 0
            if _ev["event_type"] == "shot" and _ev["shot_result"] == "make":
                _p = _ev["shot_type"]
            elif (_ev["event_type"] == "free_throw"
                  and _ev["shot_result"] == "make"):
                _p = 1
            if not _p:
                continue
            _tm = pid_team.get(_ev["primary_player_id"])
            if _tm == t1id:
                _s1 += _p
            elif _tm == t2id:
                _s2 += _p
            _q = _ev["quarter"]
            _rem = GE.time_to_secs(_ev["time"])
            _el = ((_q - 1) * _QSEC + (_QSEC - _rem) if _q <= 4
                   else 4 * _QSEC + (_q - 5) * 240 + (240 - _rem))
            _mc.append((float(_el), _s1 - _s2))
        if len(_mc) >= 2:
            _curve = _WP.wp_curve(_mc)
            _summ = _WP.summarize(_curve)
            _wpfig = _wp_ribbon(_curve, home_name=t1name, accent=_acc,
                                height=160)
            if _wpfig is not None:
                st.markdown("<div class='lab-hdr' style='margin-top:4px'>"
                            "Live win probability</div>", unsafe_allow_html=True)
                st.plotly_chart(_wpfig, width="stretch",
                                key=f"live_wp_{game_id}")
                _cwp = _curve[-1][2] * 100
                _lnm = t1name if _cwp >= 50 else t2name
                _lwp = _cwp if _cwp >= 50 else 100 - _cwp
                _wcl = st.columns(3)
                _wcl[0].markdown(_mini("Excitement (GEI)",
                                       f"{_summ['gei']:.1f}"),
                                 unsafe_allow_html=True)
                _wcl[1].markdown(_mini("Lead changes", _summ["lead_changes"]),
                                 unsafe_allow_html=True)
                _wcl[2].markdown(_mini(f"{_lnm} win odds", f"{_lwp:.0f}%"),
                                 unsafe_allow_html=True)
    except Exception:
        pass

    # ── courtside decision strip (Tier 1, ML_LAYER_ROADMAP): live Leverage Index +
    #    run alert + a late-game decision card. Reuses the SAME _QSEC=480 / 240-OT
    #    clock the win-prob walk above uses, so there is no second clock model (the
    #    one real correctness risk). Engine math lives in helpers/courtside.py; this
    #    is display only. Live games only, fully guarded — any failure skips. ───────
    if not is_tracked and _paid_view:
        try:
            import helpers.courtside as _CS
            from helpers.ui import mini_tile as _mini2
            _QSEC = 480
            _tot = 4 * _QSEC + max(cur_q - 4, 0) * 240          # full game length
            # current clock = the most recent event (latest quarter, least time left)
            _rec = max(events_asc, key=lambda e: (e["quarter"],
                                                  -GE.time_to_secs(e["time"]), e["id"]))
            _rq, _rrem = _rec["quarter"], GE.time_to_secs(_rec["time"])
            _elapsed = ((_rq - 1) * _QSEC + (_QSEC - _rrem) if _rq <= 4
                        else 4 * _QSEC + (_rq - 5) * 240 + (240 - _rrem))
            _sl = max(_tot - _elapsed, 0)
            _mh = hp - ap                                       # home (t1) margin
            _lev = _CS.leverage_now(_mh, _sl, _tot)
            # pace for the comeback gauge: seconds per possession so far
            _np = sum(1 for e in events_asc
                      if e["event_type"] in ("shot", "turnover"))
            _spp = (_elapsed / _np) if _np else 15.0

            _lc = st.columns(3)
            _lc[0].markdown(_mini2("Leverage now", _lev["tier"]), unsafe_allow_html=True)
            _lc[1].markdown(_mini2("WP swing / basket", f"{_lev['li'] * 100:.0f}%"),
                            unsafe_allow_html=True)
            _lc[2].markdown(_mini2("Sec / poss", f"{_spp:.0f}"), unsafe_allow_html=True)

            # run alert (t1 perspective): who is on a run + the WP it has cost
            _run = _CS.run_alert(events_asc, t1id, total_secs=_tot)
            if _run and _run["points"] >= 6 and abs(_run["wp_cost"]) >= 0.08:
                _rt_name = t1name if _run["team_id"] == t1id else t2name
                _hurt = t2name if _run["team_id"] == t1id else t1name
                st.warning(f"🔴 {_rt_name} on a {_run['points']}-0 run — {_hurt} win "
                           f"odds down {abs(_run['wp_cost']) * 100:.0f}%. "
                           "Consider a timeout.")

            # late-game decision card (final 3 min, league-rate v1)
            _lead = abs(_mh)
            if _sl <= 180 and _lead > 0:
                _lead_team = t1name if _mh > 0 else t2name
                _trail_team = t2name if _mh > 0 else t1name
                with st.container(border=True):
                    st.markdown("**Late-game decision**")
                    if _lead == 3 and _sl <= 35:
                        _f = _CS.foul_up_3(_sl, total_secs=_tot)
                        st.markdown(
                            f"⏱️ **{_lead_team} up 3, {int(_sl)}s left** — foul "
                            f"{_f['foul_wp'] * 100:.0f}% vs guard "
                            f"{_f['guard_wp'] * 100:.0f}% win odds · "
                            f"**{_f['recommend'].upper()}** — {_f['note']}")
                    _cg = _CS.comeback_gauge(-_lead, _sl, sec_per_poss=_spp)
                    if _cg:
                        st.markdown(
                            f"📉 **{_trail_team} down {_cg['deficit']}** — "
                            f"~{_cg['your_poss']:.0f} possessions left, need "
                            f"{_cg['req_ppp_margin']:.2f} net/poss · _{_cg['label']}_")
        except Exception:
            pass

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

    # ── foul watch: live foul-out projection for players in trouble (Tier 2,
    #    ML_LAYER_ROADMAP). At each player's current foul pace, when do they foul
    #    out? Same 480/240 clock as the courtside strip. Guarded — never blocks. ──
    if not is_tracked and _paid_view:
        try:
            import helpers.rotation_plan as _RP
            _QSEC = 480
            _tot = 4 * _QSEC + max(cur_q - 4, 0) * 240
            _rec = max(events_asc, key=lambda e: (e["quarter"],
                                                  -GE.time_to_secs(e["time"]), e["id"]))
            _rq, _rr = _rec["quarter"], GE.time_to_secs(_rec["time"])
            _el = ((_rq - 1) * _QSEC + (_QSEC - _rr) if _rq <= 4
                   else 4 * _QSEC + (_rq - 5) * 240 + (240 - _rr))
            _sl = max(_tot - _el, 0)
            _tname = {t1id: t1name, t2id: t2name}
            _watch = []
            for r in box_rows:
                if r["PF"] >= 3 and r["MIN"] > 0:
                    fp = _RP.foul_out_projection(r["PF"], r["MIN"], _sl)
                    if fp["risk"] in ("out", "high", "med"):
                        _watch.append((r, fp))
            if _watch:
                _ord = {"out": 0, "high": 1, "med": 2}
                _watch.sort(key=lambda rf: _ord.get(rf[1]["risk"], 3))
                st.markdown("**⚠ Foul watch**")
                for r, fp in _watch:
                    _emo = {"out": "🛑", "high": "🔴", "med": "🟠"}.get(fp["risk"], "")
                    st.caption(f"{_emo} {r['Player']} "
                               f"({_tname.get(r['_tid'], '')}) — {fp['note']}")
        except Exception:
            pass

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
            if ev.get("turnover_type"):
                desc += f" ({TOV.label(ev['turnover_type']).lower()})"
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
        t1_db  = query(f"SELECT id, name, number FROM players WHERE team_id=? AND {_roster_c} ORDER BY number, name", (t1id, *_roster_p))
        t2_db  = query(f"SELECT id, name, number FROM players WHERE team_id=? AND {_roster_c} ORDER BY number, name", (t2id, *_roster_p))
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

    # Build player option lists for the event form (game-season roster)
    all_player_rows = query(
        f"SELECT id AS pid, name AS pname, number, team_id FROM players "
        f"WHERE team_id IN (?,?) AND {_roster_c} ORDER BY name",
        (t1id, t2id, *_roster_p)
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

            # Sticky "current defense" — the scheme the OPPONENT is in. Set once and
            # every shot/turnover logged inherits it until changed (a team stays in
            # a defense for stretches). Lives OUTSIDE the form so flipping it doesn't
            # need a submit; its own session key keeps it across reruns. Mirrors the
            # PWA tracker's defense bar and powers the Defense tab / scout sheet.
            _def_lbls = ["—"] + [lbl for _k, lbl, _f in DEF.DEFENSES]
            _def_lbl2key = {lbl: k for k, lbl, _f in DEF.DEFENSES}
            _stick1, _stick2 = st.columns(2)
            _cur_def_lbl = _stick1.selectbox(
                "Current defense", _def_lbls, key=f"cur_def_{game_id}",
                help="The defense in effect right now — stamped on every shot and "
                     "turnover you log until you change it. Powers the Defense "
                     "breakdown on the Team Dashboard and the scout sheet.")
            cur_def_key = _def_lbl2key.get(_cur_def_lbl)

            # Sticky "current set call" — the play_type twin of the defense tag,
            # stamped on shots, TURNOVERS and FOULS so per-set outcomes cover
            # score / give-it-away / foul-drawn (mirrors the PWA set-call bar).
            _pt_lbls = ["—"] + [lbl for _k, lbl in PT.NAMED_PLAY_TYPES]
            _pt_lbl2key = {lbl: k for k, lbl in PT.NAMED_PLAY_TYPES}
            _cur_pt_lbl = _stick2.selectbox(
                "Current set call", _pt_lbls, key=f"cur_pt_{game_id}",
                help="The set the OFFENSE is running — stamped on every shot, "
                     "turnover and foul you log until you change it. Powers the "
                     "play-type breakdowns (PPP, TO%, fouls drawn per set).")
            cur_pt_key = _pt_lbl2key.get(_cur_pt_lbl)

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
                        # rim at TOP, half-court at bottom — same view as the PWA
                        # tracker court (court_geom draws rim-bottom; flip vertically).
                        disp = shown.transpose(Image.FLIP_TOP_BOTTOM)
                        st.caption("Tap where the shot was taken")
                        val = streamlit_image_coordinates(disp, width=disp.width,
                                                          key=f"court_tap_{game_id}_{_tapgen}")
                        if val is not None:
                            # undo the vertical flip: display y → original (H − y)
                            ox, oy = val["x"], H - val["y"]
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
                        c1, c2, c3 = st.columns([2, 2, 1])
                        tov_p  = c1.selectbox("Turnover By", all_opts[1:])
                        stolen = c2.selectbox("Stolen By", all_opts)
                        tov_kind = c3.selectbox(
                            "Type", ["—"] + [lbl for k, lbl in TOV.TURNOVER_TYPES
                                             if k != "other"],
                            help="Kind of giveaway — optional; feeds the "
                                 "turnover-profile breakdowns.")

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
                # Stamp the sticky current defense + set call onto the event;
                # log_event persists them per type (FT ignores both).
                ev = {"quarter": q, "time": t, "defense": cur_def_key,
                      "play_type": cur_pt_key}
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
                    _tov_key = {lbl: k for k, lbl in TOV.TURNOVER_TYPES}
                    ev.update(event_type="turnover",
                              primary_player_id=plookup(tov_p, all_id),
                              stolen_by_id=plookup(stolen, all_id),
                              turnover_type=_tov_key.get(tov_kind))

                # Every event type needs its primary actor; without it the row
                # logs a NULL primary_player_id and is silently dropped from the
                # box score (a lineup change mid-form can corrupt the selectbox).
                if ev.get("primary_player_id") is None:
                    _who = {"shot": "shooter", "free_throw": "shooter",
                            "foul": "fouled player",
                            "turnover": "player"}.get(ev["event_type"], "player")
                    st.error(f"Pick a {_who} — event not logged.")
                else:
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
                    f"SELECT id FROM players WHERE team_id=? AND name=? AND {_roster_c}",
                    (tid, name, *_roster_p)
                )
                if exists:
                    skipped += 1
                    continue
                # retro game -> the new player joins THAT season's roster
                # (archived so they never surface in current-season pickers)
                execute(
                    "INSERT INTO players (team_id, name, number, height, wingspan, weight, handedness, season, archived) VALUES (?,?,?,?,?,?,?,?,?)",
                    (tid, name, int(r.get("number") or 0),
                     r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None,
                     "left" if r.get("handedness") == "left" else "right",
                     _gszn, 0 if SEAS.is_current(_gszn) else 1)
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
            f"SELECT id, name, number, team_id, handedness FROM players "
            f"WHERE team_id IN (?,?) AND {_roster_c} ORDER BY team_id, number, name",
            (t1id, t2id, *_roster_p))
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
