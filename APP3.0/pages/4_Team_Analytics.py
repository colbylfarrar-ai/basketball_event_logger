import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from Database.db import query, initialize_database
from helpers.constants import ZONES, SHOT_RATING, EST_FGP
from helpers.game_utils import games_for_team, win_loss, opponent_name, home_away, record_from_games
from helpers.charts import (zone_color, render_hot_zones, show_shot_chart, show_scoring_pie,
                            show_four_factors_bars, show_trend_chart, show_player_radar,
                            show_score_flow_chart, show_matchup_bars)
from helpers.stats_team import (compute_player_game_log, compute_player_career,
                                compute_team_tracked, compute_on_off,
                                compute_league_drtg, compute_league_four_factors,
                                compute_matchup)
from helpers.stats_players import (compute_player_ratings,
                                   compute_player_rankings,
                                   compute_game_box_score,
                                   compute_game_quarter_scores)
from helpers.settings_utils import get_all_settings, apply_page_config, apply_theme_css
from helpers.box_score_render import show_game_box_score
from helpers.ui_utils import PLOT_LAYOUT, patch_dataframe

initialize_database()
_cfg = get_all_settings()
apply_page_config(_cfg)
apply_theme_css(_cfg)
patch_dataframe()

st.title("Team Analytics")

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── KPI tile ── */
.kpi-tile {
    background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:16px 20px; text-align:center; margin-bottom:10px;
}
.kpi-label { font-size:10px; color:#8b949e; text-transform:uppercase;
             letter-spacing:1.2px; font-weight:600; margin-bottom:6px; }
.kpi-value { font-size:32px; font-weight:900; color:#f0a500; line-height:1.1; }
.kpi-sub   { font-size:12px; color:#c9d1d9; margin-top:5px; }
/* ── Adv metric tile ── */
.adv-tile {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:12px 16px; text-align:center;
}
.adv-label { font-size:10px; color:#8b949e; text-transform:uppercase;
             letter-spacing:1px; margin-bottom:4px; }
.adv-value { font-size:22px; font-weight:800; color:#58a6ff; }
/* ── Four Factors row ── */
.ff-label  { font-size:11px; color:#8b949e; text-transform:uppercase;
             letter-spacing:1px; margin-bottom:3px; }
.ff-team   { font-size:20px; font-weight:800; color:#f0a500; }
.ff-opp    { font-size:20px; font-weight:800; color:#e74c3c; }
.ff-bar-wrap{ background:#21262d; border-radius:4px; height:8px; overflow:hidden; margin:4px 0; }
.ff-bar-t  { background:#f0a500; height:100%; border-radius:4px; }
.ff-bar-o  { background:#e74c3c; height:100%; border-radius:4px; }
/* ── Rating cards ── */
.rat-card {
    background:linear-gradient(135deg,#0d1117,#161b22);
    border:1px solid #30363d; border-radius:12px;
    padding:16px; margin-bottom:10px;
}
.rat-title { font-size:13px; font-weight:700; color:#58a6ff; margin-bottom:6px; }
.rat-desc  { font-size:11px; color:#8b949e; line-height:1.5; margin-bottom:6px; }
.rat-comp  { font-size:10px; color:#6e7681; font-style:italic; }
/* ── Player rating card ── */
.rpl-card {
    background:linear-gradient(160deg,#0d1117,#161b22);
    border:1px solid #30363d; border-radius:12px;
    padding:14px 12px; margin-bottom:10px;
}
.rpl-name { font-size:13px; font-weight:800; color:#f0f6fc; }
.rpl-meta { font-size:10px; color:#8b949e; margin-bottom:8px; }
.rpl-bar-wrap { background:#21262d; border-radius:3px; height:5px;
                overflow:hidden; margin-top:2px; }
.rpl-bar-fill { height:100%; border-radius:3px; }
/* ── Section header ── */
.section-hdr {
    font-size:17px; font-weight:700; color:#f0f6fc;
    border-left:4px solid #f0a500; padding-left:10px; margin:16px 0 10px;
}
/* ── Lineup card ── */
.lu-card {
    background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:18px 12px; text-align:center;
    height:230px; box-sizing:border-box;
    display:flex; flex-direction:column; justify-content:space-between;
    overflow:hidden;
}
.lu-slot  { font-size:9px; text-transform:uppercase; letter-spacing:1.5px;
            font-weight:700; margin-bottom:4px; flex-shrink:0; }
.lu-num   { font-size:12px; color:#8b949e; margin-bottom:1px; flex-shrink:0; }
.lu-name  { font-size:14px; font-weight:800; color:#f0f6fc; margin-bottom:2px;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
            flex-shrink:0; }
.lu-tm    { font-size:10px; color:#8b949e; margin-bottom:6px; flex-shrink:0; }
.lu-val   { font-size:28px; font-weight:900; line-height:1; flex-shrink:0; }
.lu-lbl   { font-size:9px; color:#8b949e; text-transform:uppercase;
            letter-spacing:1px; margin-bottom:4px; flex-shrink:0; }
.lu-ovrl  { font-size:10px; color:#8b949e; margin-bottom:3px; flex-shrink:0; }
.lu-line  { font-size:10px; color:#8b949e; border-top:1px solid #30363d;
            padding-top:6px; margin-top:auto; flex-shrink:0;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* ── Top-5 rating row cards ── */
.lu-row-card {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:10px 14px; margin-bottom:6px;
    display:flex; align-items:center; gap:12px;
}
.lu-rank  { font-size:16px; font-weight:800; color:#8b949e; min-width:22px; }
.lu-body  { flex:1; min-width:0; }
.lu-name  { font-size:13px; font-weight:700; color:#f0f6fc;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lu-meta  { font-size:10px; color:#8b949e; margin-top:2px; }
.lu-score { font-size:22px; font-weight:900; min-width:44px; text-align:right; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  TEAM SELECTOR
# ══════════════════════════════════════════════════════════════════════════════

all_teams = query("SELECT id, name, class, gender FROM teams ORDER BY name")
if not all_teams:
    st.warning("No teams found. Add teams in the Input Hub first.")
    st.stop()

team_map   = {t["name"]: t["id"] for t in all_teams}
team_meta  = {t["id"]: t for t in all_teams}
_team_names    = list(team_map.keys())
_default_team  = _cfg.get("default_team", "")
_default_idx   = (_team_names.index(_default_team)
                  if _default_team in _team_names else 0)
# Persist selection across page navigations via session_state
if "ta_team_sel" not in st.session_state:
    st.session_state["ta_team_sel"] = _team_names[_default_idx]
elif st.session_state["ta_team_sel"] not in _team_names:
    st.session_state["ta_team_sel"] = _team_names[_default_idx]
sel_name   = st.selectbox("Select Team", _team_names, key="ta_team_sel")
team_id    = team_map[sel_name]
team_info  = team_meta[team_id]

st.caption(f"Class {team_info['class']} · {'Men' if team_info['gender']=='M' else 'Women'}")
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_ov, tab_ts, tab_pl, tab_rat, tab_lu, tab_gm, tab_mu, tab_notes, tab_ai = st.tabs([
    "Overview", "Team Stats", "Players", "🏅 Ratings",
    "🏀 Lineups", "Games", "Matchup Simulator", "Notes", "AI Insights",
])

# ══════════════════════════════════════════════════════════════════════════════
#  OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_ov:
    all_gs  = games_for_team(team_id)
    tr_gs   = games_for_team(team_id, tracked_only=True)
    adv     = compute_team_tracked(team_id)
    w,l,pf,pa = record_from_games(all_gs, team_id)
    gp=len(all_gs)

    # ── KPI hero tiles ────────────────────────────────────────────────────────
    _win_pct = f"{w/gp*100:.1f}%" if gp else "—"
    _ppg     = f"{pf/gp:.1f}" if gp else "—"
    _papg    = f"{pa/gp:.1f}" if gp else "—"
    _diff    = f"{(pf-pa)/gp:+.1f}" if gp else "—"
    _diff_clr= "#2ecc71" if gp and pf>pa else "#e74c3c" if gp and pf<pa else "#8b949e"

    _kpi_cols = st.columns(6)
    _kpi_data = [
        ("Record",    f"{w}-{l}",     f"{_win_pct} win rate"),
        ("PPG",       _ppg,           "Points per game"),
        ("PA/G",      _papg,          "Points allowed per game"),
        ("Diff",      _diff,          "Point differential"),
        ("GP",        str(gp),        f"{len(tr_gs)} tracked"),
        ("W%",        _win_pct,       f"{w}W – {l}L"),
    ]
    for col_obj, (label, val, sub) in zip(_kpi_cols, _kpi_data):
        _vc = _diff_clr if label == "Diff" else "#f0a500"
        col_obj.markdown(f"""
        <div class="kpi-tile">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value" style="color:{_vc}">{val}</div>
            <div class="kpi-sub">{sub}</div>
        </div>""", unsafe_allow_html=True)

    st.divider()

    if adv:
        # ── Advanced tiles ─────────────────────────────────────────────────────
        st.markdown('<div class="section-hdr">Advanced Stats (Tracked Games)</div>',
                    unsafe_allow_html=True)
        _adv_tiles = [
            ("ORtg",    f"{adv['ortg']:.1f}",  "Points per 100 poss (off)"),
            ("DRtg",    f"{adv['drtg']:.1f}",  "Points per 100 poss (def)"),
            ("Net Rtg", f"{adv['net']:+.1f}",  "ORtg minus DRtg"),
            ("Pace",    f"{adv['pace']:.1f}",  "Possessions per game"),
            ("eFG%",    f"{adv['efg']*100:.1f}%","Effective FG% (off)"),
            ("Opp eFG%",f"{adv['oefg']*100:.1f}%","Opponent eFG%"),
            ("TS%",     f"{adv['ts']*100:.1f}%","True Shooting %"),
            ("TOV%",    f"{adv['tov_r']*100:.1f}%","Turnover rate"),
            ("OREB%",   f"{adv['oreb_p']*100:.1f}%","Offensive REB rate"),
            ("FT Rate", f"{adv['ft_r']:.2f}",  "FTA per FGA"),
        ]
        _at_cols = st.columns(5)
        for i, (lbl, val, tip) in enumerate(_adv_tiles):
            _at_cols[i % 5].markdown(
                f'<div class="adv-tile" title="{tip}">'
                f'<div class="adv-label">{lbl}</div>'
                f'<div class="adv-value">{val}</div>'
                f'</div>', unsafe_allow_html=True)

        st.divider()

        # ── Four Factors visual ─────────────────────────────────────────────────
        st.markdown('<div class="section-hdr">📊 Four Factors (Dean Oliver)</div>',
                    unsafe_allow_html=True)
        st.caption("The four factors that most determine winning: shooting efficiency, "
                   "turnovers, rebounding, and free throws. Green = team leading, Red = opponent leading.")

        _ff = [
            ("eFG%",   adv['efg']*100,      adv['oefg']*100,     True,
             "Effective FG% — best predictor of offensive efficiency (weight ~40%)"),
            ("TOV%",   adv['tov_r']*100,    adv.get('opp_tov_r',0)*100, False,
             "Turnover Rate — lower is better for offense (weight ~25%)"),
            ("OREB%",  adv['oreb_p']*100,   adv.get('opp_oreb_p',0)*100, True,
             "Offensive Rebound Rate — second-chance opportunities (weight ~20%)"),
            ("FT Rate",adv['ft_r'],          adv.get('opp_ft_r',0),       True,
             "FT Rate (FTA/FGA) — getting to the line (weight ~15%)"),
        ]

        ff_cols = st.columns(4)
        for (col_obj, (label, team_v, opp_v, higher_team_better, tip)) in zip(ff_cols, _ff):
            t_win = (team_v > opp_v) if higher_team_better else (team_v < opp_v)
            o_win = not t_win
            t_clr = "#2ecc71" if t_win else "#e74c3c"
            o_clr = "#e74c3c" if t_win else "#2ecc71"
            t_bar = min(100, team_v) if higher_team_better else max(0, 100 - team_v)
            o_bar = min(100, opp_v)  if higher_team_better else max(0, 100 - opp_v)
            col_obj.markdown(f"""
            <div title="{tip}" style="background:#161b22;border:1px solid #30363d;
                 border-radius:12px;padding:14px;text-align:center;height:160px">
                <div style="font-size:10px;color:#8b949e;text-transform:uppercase;
                     letter-spacing:1px;margin-bottom:8px">{label}</div>
                <div style="display:flex;justify-content:space-around;margin-bottom:8px">
                    <div>
                        <div style="font-size:9px;color:#8b949e">Team</div>
                        <div style="font-size:20px;font-weight:800;color:{t_clr}">
                            {team_v:.1f}{"%" if "%" in label or label=="eFG%" else ""}</div>
                    </div>
                    <div style="font-size:18px;color:#30363d;align-self:center">vs</div>
                    <div>
                        <div style="font-size:9px;color:#8b949e">Opp</div>
                        <div style="font-size:20px;font-weight:800;color:{o_clr}">
                            {opp_v:.1f}{"%" if "%" in label or label=="eFG%" else ""}</div>
                    </div>
                </div>
                <div style="background:#21262d;border-radius:4px;height:6px;overflow:hidden;margin-bottom:4px">
                    <div style="width:{t_bar:.0f}%;background:{t_clr};height:100%;border-radius:4px"></div>
                </div>
                <div style="background:#21262d;border-radius:4px;height:6px;overflow:hidden">
                    <div style="width:{o_bar:.0f}%;background:{o_clr};height:100%;border-radius:4px"></div>
                </div>
            </div>""", unsafe_allow_html=True)
        st.caption("Four Factors weights (approximate): eFG% 40% · TOV% 25% · OREB% 20% · FT Rate 15%")

        st.divider()

        # ── ORtg / DRtg / Margin trend ─────────────────────────────────────────
        _gl = adv.get("game_log", [])
        if _gl:
            st.markdown('<div class="section-hdr">📈 ORtg · DRtg · Margin Trend</div>',
                        unsafe_allow_html=True)
            _gl_sorted = sorted(_gl, key=lambda g: pd.to_datetime(g["date"], format="mixed", errors="coerce"))
            _trend_df  = pd.DataFrame([
                {"Game": i+1, "Date": g["date"],
                 "ORtg": g["ortg"], "DRtg": g["drtg"], "Margin": g["margin"],
                 "Opp": g.get("opp", "")}
                for i, g in enumerate(_gl_sorted)
            ])

            fig_trend = go.Figure()
            # ORtg line
            fig_trend.add_trace(go.Scatter(
                x=_trend_df["Game"], y=_trend_df["ORtg"],
                name="ORtg", mode="lines+markers",
                line=dict(color="#2ecc71", width=2.5),
                marker=dict(size=6),
                hovertemplate="Game %{x} vs %{customdata}<br>ORtg: %{y:.1f}<extra></extra>",
                customdata=_trend_df["Opp"],
            ))
            # DRtg line
            fig_trend.add_trace(go.Scatter(
                x=_trend_df["Game"], y=_trend_df["DRtg"],
                name="DRtg", mode="lines+markers",
                line=dict(color="#e74c3c", width=2.5),
                marker=dict(size=6),
                hovertemplate="Game %{x} vs %{customdata}<br>DRtg: %{y:.1f}<extra></extra>",
                customdata=_trend_df["Opp"],
            ))
            # Margin bars on secondary axis
            fig_trend.add_trace(go.Bar(
                x=_trend_df["Game"], y=_trend_df["Margin"],
                name="Margin", yaxis="y2",
                marker_color=["rgba(46,204,113,0.35)" if m > 0 else "rgba(231,76,60,0.35)"
                              for m in _trend_df["Margin"]],
                hovertemplate="Game %{x}<br>Margin: %{y:+d}<extra></extra>",
            ))
            fig_trend.update_layout(
                **PLOT_LAYOUT,
                title="Game-by-Game: Offensive & Defensive Rating with Point Margin",
                xaxis=dict(title="Game #", dtick=1, showgrid=False),
                yaxis=dict(title="Efficiency Rating", showgrid=True, gridcolor="#21262d"),
                yaxis2=dict(title="Point Margin", overlaying="y", side="right",
                            showgrid=False, zeroline=True, zerolinecolor="#30363d"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                hovermode="x unified",
                height=380,
            )
            st.plotly_chart(fig_trend, use_container_width=True, key="ov_rtg_trend")

        st.divider()

    # ── Schedule summary ──
    st.subheader("Schedule")
    sched_rows=[]
    for g in all_gs:
        res,my,opp=win_loss(g,team_id)
        sched_rows.append({
            "Date":g["date"],"Opponent":opponent_name(g,team_id),
            "H/A":home_away(g,team_id),"Result":res,
            "Score":f"{my}-{opp}","Tracked":"✓" if g["tracked"] else ""
        })
    if sched_rows:
        st.dataframe(pd.DataFrame(sched_rows), use_container_width=True, hide_index=True)

    # ── Hot zones aggregate ──
    if tr_gs:
        st.divider()
        st.subheader("Shooting Zones (All Tracked Games)")
        gids=tuple(g["id"] for g in tr_gs)
        if len(gids)==1:
            shots=query("""
                SELECT e.zone,e.shot_type,e.shot_result
                FROM game_events e
                JOIN game_lineup_players glp ON glp.game_id=e.game_id AND glp.player_id=e.primary_player_id
                WHERE e.game_id=? AND e.event_type='shot' AND e.zone IS NOT NULL AND glp.team_id=?
            """, (gids[0], team_id))
        else:
            shots=query(f"""
                SELECT e.zone,e.shot_type,e.shot_result
                FROM game_events e
                JOIN game_lineup_players glp ON glp.game_id=e.game_id AND glp.player_id=e.primary_player_id
                WHERE e.game_id IN ({','.join('?'*len(gids))}) AND e.event_type='shot'
                  AND e.zone IS NOT NULL AND glp.team_id=?
            """, (*gids, team_id))
        render_hot_zones(shots)

# ══════════════════════════════════════════════════════════════════════════════
#  TEAM STATS
# ══════════════════════════════════════════════════════════════════════════════
with tab_ts:
    ts_adv = compute_team_tracked(team_id)
    ts_all = games_for_team(team_id, tracked_only=True)
    gp_ts  = len(ts_all)

    if not ts_adv or gp_ts == 0:
        st.info("No tracked game data yet.")
    else:
        a = ts_adv  # shorthand

        # ── Per-game highlights ──────────────────────────────────────────────
        st.markdown('<div class="section-hdr">Per Game</div>', unsafe_allow_html=True)
        _pg_cols = st.columns(6)
        _pg_data = [("PPG",f"{a['pts_pg']:.1f}"),("APG",f"{a['ast_pg']:.1f}"),
                    ("RPG",f"{(a['oreb_pg']+a['dreb_pg']):.1f}"),
                    ("SPG",f"{a['stl_pg']:.1f}"),("BPG",f"{a['blk_pg']:.1f}"),
                    ("TPG",f"{a['tov_pg']:.1f}")]
        for _co, (_lbl, _val) in zip(_pg_cols, _pg_data):
            _co.markdown(f"""<div class="adv-tile">
                <div class="adv-label">{_lbl}</div>
                <div class="adv-value">{_val}</div>
            </div>""", unsafe_allow_html=True)

        # ── Shot distribution chart ──────────────────────────────────────────
        _ts_gids = tuple(g["id"] for g in ts_all)
        if _ts_gids:
            _ph_str = ",".join("?" * len(_ts_gids))
            _shot_dist = query(f"""
                SELECT e.shot_type, e.zone, e.shot_result, COUNT(*) AS cnt
                FROM game_events e
                JOIN players p ON p.id = e.primary_player_id
                WHERE e.game_id IN ({_ph_str})
                  AND e.event_type='shot' AND p.team_id=?
                GROUP BY e.shot_type, e.zone, e.shot_result
            """, (*_ts_gids, team_id))

            if _shot_dist:
                _sdf = pd.DataFrame(_shot_dist)
                _two  = _sdf[_sdf["shot_type"]==2]["cnt"].sum()
                _three= _sdf[_sdf["shot_type"]==3]["cnt"].sum()
                _tot  = _two + _three
                _ft_d = query(f"""
                    SELECT COUNT(*) AS cnt,
                           SUM(CASE WHEN shot_result='make' THEN 1 ELSE 0 END) AS makes
                    FROM game_events e
                    JOIN players p ON p.id=e.primary_player_id
                    WHERE e.game_id IN ({_ph_str})
                      AND e.event_type='free_throw' AND p.team_id=?
                """, (*_ts_gids, team_id))
                _fta_t = _ft_d[0]["cnt"] if _ft_d else 0

                _dist_l, _dist_r = st.columns([1, 1])
                with _dist_l:
                    if _tot + _fta_t > 0:
                        fig_td = go.Figure(go.Pie(
                            labels=["2PT FGA","3PT FGA","FTA"],
                            values=[int(_two), int(_three), int(_fta_t)],
                            hole=0.55,
                            marker_colors=["#f0a500","#3498db","#2ecc71"],
                            textinfo="label+percent", textfont_size=12,
                        ))
                        fig_td.update_layout(
                            **PLOT_LAYOUT, title="Shot Attempt Distribution",
                            showlegend=False, height=290)
                        st.plotly_chart(fig_td, use_container_width=True, key="ts_shot_dist")

                with _dist_r:
                    # Shooting % by type
                    _makes2 = _sdf[(_sdf["shot_type"]==2)&(_sdf["shot_result"]=="make")]["cnt"].sum()
                    _makes3 = _sdf[(_sdf["shot_type"]==3)&(_sdf["shot_result"]=="make")]["cnt"].sum()
                    _ft_makes= _ft_d[0]["makes"] if _ft_d else 0
                    _2pct  = round(_makes2/_two*100,1)  if _two   else 0
                    _3pct  = round(_makes3/_three*100,1) if _three else 0
                    _ftpct = round(_ft_makes/_fta_t*100,1) if _fta_t else 0
                    _efg   = round((_makes2 + 1.5*_makes3) / _tot * 100, 1) if _tot else 0
                    fig_pcts = go.Figure(go.Bar(
                        x=["2P%","3P%","FT%","eFG%"],
                        y=[_2pct, _3pct, _ftpct, _efg],
                        marker_color=["#f0a500","#3498db","#2ecc71","#9b59b6"],
                        text=[f"{v:.1f}%" for v in [_2pct,_3pct,_ftpct,_efg]],
                        textposition="outside",
                    ))
                    fig_pcts.update_layout(
                        **PLOT_LAYOUT, title="Shooting Percentages by Type",
                        yaxis=dict(range=[0,115], showgrid=False),
                        height=290)
                    st.plotly_chart(fig_pcts, use_container_width=True, key="ts_shoot_pcts")

        st.divider()

        # ── Possessions ──────────────────────────────────────────────────────
        st.subheader("Possessions")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Total Possessions",  a["poss_count"],
                  help="Count of non-free-throw events with a primary player (same definition as Game Tracker)")
        p2.metric("Possessions / Game", f"{a['poss_pg']:.1f}")
        p3.metric("Points Per Poss.",   f"{a['ppp']:.3f}",
                  help="Total points scored ÷ total possessions")
        p4.metric("Avg Poss. Length",   a["avg_poss_len"],
                  help="Average time (M:SS) per possession")

        poss_rows = [
            {"Stat": "Total Possessions",    "Value": a["poss_count"]},
            {"Stat": "Possessions / Game",   "Value": f"{a['poss_pg']:.1f}"},
            {"Stat": "Total Poss. Time",     "Value": a["poss_time_total"]},
            {"Stat": "Avg Poss. Length",     "Value": a["avg_poss_len"]},
            {"Stat": "Points Per Possession","Value": f"{a['ppp']:.3f}"},
        ]
        st.dataframe(pd.DataFrame(poss_rows), hide_index=True, use_container_width=True)

        # ── Possession Length Breakdown ───────────────────────────────────────
        st.markdown("#### Possession Length Breakdown")
        _pb_gids = [g["id"] for g in ts_all]
        _pb_ph   = ",".join("?" * len(_pb_gids))
        _pb_rows = query(f"""
            SELECT
                CASE
                    WHEN e.possession_secs < 12 THEN 'Quick'
                    WHEN e.possession_secs < 27 THEN 'Medium'
                    ELSE 'Long'
                END AS bucket,
                COUNT(*)                                                             AS poss,
                AVG(e.possession_secs)                                               AS avg_secs,
                SUM(CASE WHEN e.shot_result='make' AND e.shot_type=2 THEN 2
                         WHEN e.shot_result='make' AND e.shot_type=3 THEN 3
                         ELSE 0 END)                                                 AS fg_pts,
                SUM(CASE WHEN e.event_type='shot'                     THEN 1 ELSE 0 END) AS fga,
                SUM(CASE WHEN e.event_type='shot'
                          AND e.shot_result='make'                     THEN 1 ELSE 0 END) AS fgm,
                SUM(CASE WHEN e.event_type='shot' AND e.shot_type=2   THEN 1 ELSE 0 END) AS fga2,
                SUM(CASE WHEN e.event_type='shot' AND e.shot_type=2
                          AND e.shot_result='make'                     THEN 1 ELSE 0 END) AS fgm2,
                SUM(CASE WHEN e.event_type='shot' AND e.shot_type=3   THEN 1 ELSE 0 END) AS fga3,
                SUM(CASE WHEN e.event_type='shot' AND e.shot_type=3
                          AND e.shot_result='make'                     THEN 1 ELSE 0 END) AS fgm3,
                SUM(CASE WHEN e.event_type='turnover'                  THEN 1 ELSE 0 END) AS tov,
                SUM(CASE WHEN e.event_type='shot' AND e.shot_result='make'
                          AND e.pass_from_id IS NOT NULL               THEN 1 ELSE 0 END) AS ast_fgm,
                SUM(CASE WHEN e.event_type='shot' AND e.shot_result='make'
                          AND e.pass_from_id IS NULL                   THEN 1 ELSE 0 END) AS unast_fgm
            FROM game_events e
            JOIN players p ON p.id = e.primary_player_id
            WHERE e.game_id IN ({_pb_ph})
              AND e.event_type IN ('shot','turnover')
              AND p.team_id = ?
            GROUP BY bucket
        """, (*_pb_gids, team_id))

        # Free throw points can't be bucketed by possession length (FT events have
        # their own psec, unrelated to the parent possession).  Distribute them
        # proportionally across buckets so the weighted PPP matches the overall PPP.
        _ft_row = query(f"""
            SELECT SUM(CASE WHEN e.shot_result='make' THEN 1 ELSE 0 END) AS ft_pts
            FROM game_events e
            JOIN players p ON p.id = e.primary_player_id
            WHERE e.game_id IN ({_pb_ph})
              AND e.event_type = 'free_throw'
              AND p.team_id = ?
        """, (*_pb_gids, team_id))
        _total_ft_pts    = (_ft_row[0]["ft_pts"] or 0) if _ft_row else 0
        _total_bkt_poss  = sum((r["poss"] or 0) for r in _pb_rows) if _pb_rows else 1

        if _pb_rows:
            # Force canonical order and compute derived stats
            _bucket_order = {"Quick": 0, "Medium": 1, "Long": 2}
            _bucket_label = {
                "Quick":  "⚡ Quick  (<12s)",
                "Medium": "🏃 Medium  (12–27s)",
                "Long":   "🐢 Long  (27+s)",
            }
            _pb_rows = sorted(_pb_rows, key=lambda r: _bucket_order.get(r["bucket"], 9))

            _pb_table = []
            _ppp_vals, _ppp_lbls, _ppp_colors = [], [], []
            _accent = {"Quick": "#f0a500", "Medium": "#58a6ff", "Long": "#2ecc71"}

            for r in _pb_rows:
                b      = r["bucket"]
                poss   = r["poss"]   or 1
                fga    = r["fga"]    or 0
                fgm    = r["fgm"]    or 0
                fga2   = r["fga2"]   or 0
                fgm2   = r["fgm2"]   or 0
                fga3   = r["fga3"]   or 0
                fgm3   = r["fgm3"]   or 0
                tov    = r["tov"]    or 0
                fg_pts = r["fg_pts"] or 0
                ast_f  = r["ast_fgm"]   or 0
                unast  = r["unast_fgm"] or 0
                secs   = r["avg_secs"]  or 0

                # Add this bucket's proportional share of free throw points
                ft_share = _total_ft_pts * (poss / max(_total_bkt_poss, 1))
                pts      = fg_pts + ft_share

                ppp      = pts / poss
                fg_pct   = fgm / fga * 100   if fga   else 0
                p2_pct   = fgm2 / fga2 * 100 if fga2  else 0
                p3_pct   = fgm3 / fga3 * 100 if fga3  else 0
                efg_pct  = (fgm + 0.5*fgm3) / fga * 100 if fga else 0
                tov_pct  = tov / poss * 100
                shot_rt  = fga / poss * 100        # % possessions ending in shot
                w_pass   = ast_f / fgm * 100 if fgm else 0
                mins     = int(secs // 60)
                secs_rem = int(secs % 60)

                _pb_table.append({
                    "Bucket":       _bucket_label.get(b, b),
                    "Possessions":  int(poss),
                    "Avg Length":   f"{mins}:{secs_rem:02d}",
                    "PPP":          f"{ppp:.3f}",
                    "FG%":          f"{fg_pct:.1f}%",
                    "2P%":          f"{p2_pct:.1f}%",
                    "3P%":          f"{p3_pct:.1f}%",
                    "eFG%":         f"{efg_pct:.1f}%",
                    "TOV%":         f"{tov_pct:.1f}%",
                    "Shot Rate":    f"{shot_rt:.1f}%",
                    "W/Pass%":      f"{w_pass:.1f}%",
                })
                _ppp_vals.append(round(ppp, 3))
                _ppp_lbls.append(_bucket_label.get(b, b))
                _ppp_colors.append(_accent.get(b, "#888"))

            # Metric cards — one per bucket
            _pb_cols = st.columns(len(_pb_table))
            for i, (row, r) in enumerate(zip(_pb_table, _pb_rows)):
                with _pb_cols[i]:
                    st.markdown(f"""
                    <div style="background:linear-gradient(135deg,#0d1117,#161b22);
                                border:1px solid #30363d; border-radius:12px;
                                padding:14px 10px; text-align:center;">
                        <div style="font-size:9px;color:#8b949e;text-transform:uppercase;
                                    letter-spacing:1.2px;margin-bottom:6px;">
                            {row['Bucket']}
                        </div>
                        <div style="font-size:26px;font-weight:900;
                                    color:{_accent.get(r['bucket'],'#888')};">
                            {row['PPP']}
                        </div>
                        <div style="font-size:10px;color:#8b949e;margin-top:4px;">
                            PPP
                        </div>
                        <div style="font-size:12px;color:#c9d1d9;margin-top:6px;">
                            {row['Possessions']} poss · TOV {row['TOV%']}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # PPP bar chart
            _fig_pb = go.Figure(go.Bar(
                x=_ppp_lbls,
                y=_ppp_vals,
                marker_color=_ppp_colors,
                text=[f"{v:.3f}" for v in _ppp_vals],
                textposition="outside",
                hovertemplate="%{x}<br>PPP: %{y:.3f}<extra></extra>",
            ))
            _fig_pb.update_layout(
                title="Points Per Possession by Pace",
                xaxis=dict(showgrid=False),
                yaxis=dict(range=[0, max(_ppp_vals) * 1.35 if _ppp_vals else 1],
                           showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
                height=280,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#c9d1d9", size=11),
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(_fig_pb, use_container_width=True, key="pb_ppp_bar")

            # Detailed breakdown table
            st.dataframe(
                pd.DataFrame(_pb_table),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                "Quick < 12s · Medium 12–27s · Long 27+s  ·  "
                "FT points distributed proportionally across buckets (FT events have no possession length)  ·  "
                "Shot Rate = % of possessions ending in a field-goal attempt  ·  "
                "W/Pass% = assisted makes ÷ total makes"
            )

        st.divider()

        # ── Shooting ────────────────────────────────────────────────────────
        st.subheader("Shooting")
        sh1, sh2, sh3 = st.columns(3)

        with sh1:
            st.markdown("**Field Goals**")
            _2pm = a["fgm"]-a["tpm"]; _2pa = a["fga"]-a["tpa"]
            fg_rows = [
                {"Stat": "FGM",  "Total": a["fgm"],               "Per Game": round(a["fgm"]/gp_ts, 1)},
                {"Stat": "FGA",  "Total": a["fga"],               "Per Game": round(a["fga"]/gp_ts, 1)},
                {"Stat": "FG%",  "Total": f"{a['fgp']*100:.1f}%", "Per Game": "—"},
                {"Stat": "2PM",  "Total": _2pm,                   "Per Game": round(_2pm/gp_ts, 1)},
                {"Stat": "2PA",  "Total": _2pa,                   "Per Game": round(_2pa/gp_ts, 1)},
                {"Stat": "2P%",  "Total": f"{a['two_pct']*100:.1f}%","Per Game": "—"},
                {"Stat": "eFG%", "Total": f"{a['efg']*100:.1f}%", "Per Game": "—"},
                {"Stat": "TS%",  "Total": f"{a['ts']*100:.1f}%",  "Per Game": "—"},
            ]
            st.dataframe(pd.DataFrame(fg_rows), hide_index=True, use_container_width=True)

        with sh2:
            st.markdown("**3-Pointers**")
            tp_rows = [
                {"Stat": "3PM",  "Total": a["tpm"],                         "Per Game": round(a["tpm"]/gp_ts, 1)},
                {"Stat": "3PA",  "Total": a["tpa"],                         "Per Game": round(a["tpa"]/gp_ts, 1)},
                {"Stat": "3P%",  "Total": f"{a['tpp']*100:.1f}%",           "Per Game": "—"},
                {"Stat": "3PAr", "Total": f"{a['tpar']*100:.1f}%",          "Per Game": "—"},
            ]
            st.dataframe(pd.DataFrame(tp_rows), hide_index=True, use_container_width=True)

        with sh3:
            st.markdown("**Free Throws**")
            ft_rows = [
                {"Stat": "FTM",     "Total": a["ftm"],                      "Per Game": round(a["ftm"]/gp_ts, 1)},
                {"Stat": "FTA",     "Total": a["fta"],                      "Per Game": round(a["fta"]/gp_ts, 1)},
                {"Stat": "FT%",     "Total": f"{a['ftp']*100:.1f}%",        "Per Game": "—"},
                {"Stat": "FT Rate", "Total": f"{a['ft_r']:.2f}",            "Per Game": "—"},
            ]
            st.dataframe(pd.DataFrame(ft_rows), hide_index=True, use_container_width=True)

        st.divider()

        # ── Other counting stats ─────────────────────────────────────────────
        st.subheader("Other Stats")
        other_rows = [
            {"Stat": "Assists",       "Total": a["ast"],  "Per Game": round(a["ast_pg"], 1)},
            {"Stat": "Off. Rebounds", "Total": a["oreb"], "Per Game": round(a["oreb_pg"], 1)},
            {"Stat": "Def. Rebounds", "Total": a["dreb"], "Per Game": round(a["dreb_pg"], 1)},
            {"Stat": "Rebounds",      "Total": a["oreb"]+a["dreb"], "Per Game": round(a["oreb_pg"]+a["dreb_pg"], 1)},
            {"Stat": "Steals",        "Total": a["stl"],  "Per Game": round(a["stl_pg"], 1)},
            {"Stat": "Blocks",        "Total": a["blk"],  "Per Game": round(a["blk_pg"], 1)},
            {"Stat": "Turnovers",     "Total": a["tov"],  "Per Game": round(a["tov_pg"], 1)},
        ]
        st.dataframe(pd.DataFrame(other_rows), hide_index=True, use_container_width=True)

        st.divider()

        # ── Advanced ─────────────────────────────────────────────────────────
        st.subheader("Advanced")
        adv1, adv2 = st.columns(2)
        with adv1:
            adv_off = [
                {"Stat": "Off. Rating (ORtg)",   "Value": f"{a['ortg']:.1f}",          "Note": "pts/100 poss"},
                {"Stat": "Net Rating",            "Value": f"{a['net']:+.1f}",           "Note": "ORtg − DRtg"},
                {"Stat": "Pace",                  "Value": f"{a['pace']:.1f}",           "Note": "poss/game"},
                {"Stat": "eFG%",                  "Value": f"{a['efg']*100:.1f}%",       "Note": "(FGM+0.5×3PM)/FGA"},
                {"Stat": "TS%",                   "Value": f"{a['ts']*100:.1f}%",        "Note": "true shooting"},
                {"Stat": "TOV%",                  "Value": f"{a['tov_r']*100:.1f}%",     "Note": "tov per poss"},
                {"Stat": "OREB%",                 "Value": f"{a['oreb_p']*100:.1f}%",    "Note": "off-glass rate"},
                {"Stat": "FT Rate",               "Value": f"{a['ft_r']:.3f}",           "Note": "FTA/FGA"},
                {"Stat": "AST%",                  "Value": f"{a.get('ast_pct',0):.1f}%", "Note": "% FGM assisted"},
                {"Stat": "AST/TOV",               "Value": f"{a.get('ast_tov_r',0):.2f}","Note": "assist-to-tov ratio"},
                {"Stat": "Paint FG%",             "Value": f"{a.get('paint_fg_p',0)*100:.1f}%","Note": "zone-C 2PT proxy"},
                {"Stat": "Paint Pts/G",           "Value": f"{a.get('paint_pts_pg',0):.1f}",   "Note": "pts from paint/g"},
            ]
            st.markdown("**Offense**")
            st.dataframe(pd.DataFrame(adv_off), hide_index=True, use_container_width=True)
        with adv2:
            adv_def = [
                {"Stat": "Def. Rating (DRtg)",   "Value": f"{a['drtg']:.1f}",                      "Note": "pts/100 poss"},
                {"Stat": "Opp eFG%",              "Value": f"{a['oefg']*100:.1f}%",                 "Note": "opp shooting qual"},
                {"Stat": "Opp TS%",               "Value": f"{(a['opp_pts']/(2*(a['opp_fga']+0.44*a['opp_fta'])) if (a['opp_fga']+0.44*a['opp_fta']) else 0)*100:.1f}%","Note": "opp true shooting"},
                {"Stat": "Opp TOV%",              "Value": f"{a.get('opp_tov_r',0)*100:.1f}%",      "Note": "forced tov rate"},
                {"Stat": "Opp FT Rate",           "Value": f"{a.get('opp_ft_r',0):.3f}",            "Note": "FTA/FGA allowed"},
                {"Stat": "DREB%",                 "Value": f"{a.get('dreb_p',0)*100:.1f}%",         "Note": "def rebound rate"},
                {"Stat": "BLK Rate",              "Value": f"{a.get('blk_rate',0):.1f}%",           "Note": "BLK/opp 2PA"},
                {"Stat": "STL Rate",              "Value": f"{a.get('stl_rate',0):.1f}%",           "Note": "STL/opp poss"},
                {"Stat": "Opp TOV/G",             "Value": f"{a['opp_tov']/gp_ts:.1f}",             "Note": "opp turnovers/g"},
            ]
            st.markdown("**Defense**")
            st.dataframe(pd.DataFrame(adv_def), hide_index=True, use_container_width=True)

        st.divider()

        # ── Shot Creation ────────────────────────────────────────────────────
        st.subheader("Shot Creation")
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("SC/G",   f"{a['sc_pg']:.1f}",       help="Shot creations per game (shots taken + passes on shots + dribble creates)")
        sc2.metric("SCE",    f"{a['team_sce']:.3f}",    help="PTS / ((2PT_att×2) + (3PT_att×3)) — points scored per shot opportunity")
        sc3.metric("PTS/SC", f"{(a['pts']/a['sc']):.2f}" if a['sc'] else "—", help="Points scored per shot creation act")
        sc4.metric("SC/FGA", f"{(a['sc']/a['fga']):.2f}" if a['fga'] else "—", help=">1 = team creates more than it shoots, <1 = shoots more than it creates")

        st.divider()

        # ── Four Factors ─────────────────────────────────────────────────────
        st.subheader("Dean Oliver's Four Factors")
        st.caption("The four factors that drive winning: Shooting (40%), Turnovers (25%), Rebounding (20%), Free Throws (15%)")
        _lg_ff = compute_league_four_factors()
        show_four_factors_bars(a, _lg_ff if _lg_ff else None)

        ff_col1, ff_col2, ff_col3, ff_col4 = st.columns(4)
        ff_col1.metric("eFG%",      f"{a['efg']*100:.1f}%",       help="Effective FG% — weights 3s by 1.5×")
        ff_col2.metric("TOV%",      f"{a['tov_r']*100:.1f}%",     help="Turnover rate — lower is better")
        ff_col3.metric("OREB%",     f"{a['oreb_p']*100:.1f}%",    help="Offensive rebound rate")
        ff_col4.metric("FT Rate",   f"{a['ft_r']:.3f}",           help="FTA per FGA — getting to the line")
        ff_col1.metric("Opp eFG%",  f"{a['oefg']*100:.1f}%",      help="Opponent effective FG% — lower is better")
        ff_col2.metric("Opp TOV%",  f"{a.get('opp_tov_r',0)*100:.1f}%", help="Forced turnover rate — higher is better")
        ff_col3.metric("DREB%",     f"{a.get('dreb_p',0)*100:.1f}%",    help="Defensive rebound rate")
        ff_col4.metric("Opp FT Rate",f"{a.get('opp_ft_r',0):.3f}",     help="FTA/FGA allowed — lower is better")

        st.divider()

        # ── Scoring Distribution ─────────────────────────────────────────────
        st.subheader("Scoring Distribution")
        _pts2 = (a["fgm"]-a["tpm"])*2
        _pts3 = a["tpm"]*3
        _ptft = a["ftm"]
        sd_col1, sd_col2 = st.columns([1, 1])
        with sd_col1:
            show_scoring_pie(_pts2, _pts3, _ptft, f"{sel_name} — Scoring Sources")
        with sd_col2:
            pct_rows = [
                {"Source": "2PT Field Goals", "Points": _pts2, "Pct": f"{a.get('pct_from_2',0):.1f}%",
                 "Per Game": f"{_pts2/gp_ts:.1f}"},
                {"Source": "3PT Field Goals", "Points": _pts3, "Pct": f"{a.get('pct_from_3',0):.1f}%",
                 "Per Game": f"{_pts3/gp_ts:.1f}"},
                {"Source": "Free Throws",     "Points": _ptft, "Pct": f"{a.get('pct_from_ft',0):.1f}%",
                 "Per Game": f"{_ptft/gp_ts:.1f}"},
                {"Source": "TOTAL",           "Points": _pts2+_pts3+_ptft,
                 "Pct": "100%", "Per Game": f"{a['pts_pg']:.1f}"},
            ]
            st.dataframe(pd.DataFrame(pct_rows), hide_index=True, use_container_width=True)
            st.markdown(f"**Ast%**: {a.get('ast_pct',0):.1f}% of FGM were assisted")
            st.markdown(f"**Unast%**: {a.get('unast_pct',0):.1f}% of FGM were unassisted")

        st.divider()

        # ── Shot Creation Mix ─────────────────────────────────────────────────
        st.subheader("Shot Creation Mix")
        st.caption(
            "Per-player breakdown of shot attempts (FGA): "
            "🟡 W/O% = self-created makes  ·  🔵 W/Pass% = assisted makes  ·  ⬛ Miss%"
        )

        _scm_gids = tuple(g["id"] for g in ts_all)
        if _scm_gids:
            _scm_ph = ','.join('?' * len(_scm_gids))
            _scm_rows = query(f"""
                SELECT p.name, p.number,
                       COUNT(*) AS fga,
                       SUM(CASE WHEN e.shot_result='make' AND e.pass_from_id IS NOT NULL
                                THEN 1 ELSE 0 END) AS ast_fgm,
                       SUM(CASE WHEN e.shot_result='make' AND e.pass_from_id IS NULL
                                THEN 1 ELSE 0 END) AS unast_fgm
                FROM game_events e
                JOIN players p ON p.id = e.primary_player_id
                WHERE e.game_id IN ({_scm_ph})
                  AND e.event_type = 'shot'
                  AND p.team_id = ?
                GROUP BY p.id, p.name, p.number
                HAVING COUNT(*) >= 3
                ORDER BY COUNT(*) DESC
            """, (*_scm_gids, team_id))

            if _scm_rows:
                _scm_df = pd.DataFrame(_scm_rows)
                _scm_df["w_pass"]  = (_scm_df["ast_fgm"]   / _scm_df["fga"] * 100).round(1)
                _scm_df["wo_pass"] = (_scm_df["unast_fgm"] / _scm_df["fga"] * 100).round(1)
                _scm_df["miss"]    = (100 - _scm_df["w_pass"] - _scm_df["wo_pass"]).round(1).clip(lower=0)
                _scm_df["label"]   = _scm_df.apply(lambda r: f"#{r['number']} {r['name']}", axis=1)
                _scm_df = _scm_df.sort_values("wo_pass", ascending=True)  # self-creators on top

                fig_scm = go.Figure()
                fig_scm.add_trace(go.Bar(
                    name="W/O% (Self-Created)",
                    y=_scm_df["label"],
                    x=_scm_df["wo_pass"],
                    orientation="h",
                    marker_color="#f0a500",
                    text=[f"{v:.1f}%" for v in _scm_df["wo_pass"]],
                    textposition="inside",
                    insidetextanchor="middle",
                ))
                fig_scm.add_trace(go.Bar(
                    name="W/Pass% (Assisted)",
                    y=_scm_df["label"],
                    x=_scm_df["w_pass"],
                    orientation="h",
                    marker_color="#58a6ff",
                    text=[f"{v:.1f}%" for v in _scm_df["w_pass"]],
                    textposition="inside",
                    insidetextanchor="middle",
                ))
                fig_scm.add_trace(go.Bar(
                    name="Miss%",
                    y=_scm_df["label"],
                    x=_scm_df["miss"],
                    orientation="h",
                    marker_color="#30363d",
                    text=[f"{v:.1f}%" for v in _scm_df["miss"]],
                    textposition="inside",
                    insidetextanchor="middle",
                ))
                fig_scm.update_layout(
                    barmode="stack",
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font_color="#c9d1d9",
                    margin=dict(l=10, r=10, t=30, b=10),
                    height=max(320, len(_scm_df) * 42),
                    xaxis=dict(
                        title="% of FGA", range=[0, 100],
                        ticksuffix="%", gridcolor="rgba(128,128,128,0.15)",
                    ),
                    yaxis=dict(tickfont=dict(size=11)),
                    legend=dict(
                        orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1,
                    ),
                    title="Shot Outcome Mix by Player (% of FGA)",
                )
                st.plotly_chart(fig_scm, use_container_width=True, key="scm_chart_ta")
                st.caption(
                    f"Minimum 3 FGA · sorted by W/O% ascending (biggest creators on top) · "
                    f"{len(_scm_df)} player{'s' if len(_scm_df) != 1 else ''} shown"
                )
            else:
                st.info("Not enough shot data yet — players need at least 3 FGA in tracked games.")

        st.divider()

        # ── Shot Chart ───────────────────────────────────────────────────────
        st.subheader("Shot Chart (All Tracked Games)")
        _gids = tuple(g["id"] for g in ts_all)
        if _gids:
            if len(_gids) == 1:
                _shots_ts = query("""
                    SELECT e.zone, e.shot_type, e.shot_result
                    FROM game_events e
                    JOIN game_lineup_players glp ON glp.game_id=e.game_id
                                                AND glp.player_id=e.primary_player_id
                    WHERE e.game_id=? AND e.event_type='shot'
                      AND e.zone IS NOT NULL AND glp.team_id=?
                """, (_gids[0], team_id))
            else:
                _shots_ts = query(f"""
                    SELECT e.zone, e.shot_type, e.shot_result
                    FROM game_events e
                    JOIN game_lineup_players glp ON glp.game_id=e.game_id
                                                AND glp.player_id=e.primary_player_id
                    WHERE e.game_id IN ({','.join('?'*len(_gids))})
                      AND e.event_type='shot' AND e.zone IS NOT NULL AND glp.team_id=?
                """, (*_gids, team_id))
            sc_c1, sc_c2 = st.columns(2)
            with sc_c1:
                show_shot_chart(_shots_ts, f"{sel_name} — Offense")
            # Opponent shot chart
            if len(_gids) == 1:
                _opp_shots_ts = query("""
                    SELECT e.zone, e.shot_type, e.shot_result
                    FROM game_events e
                    JOIN game_lineup_players glp ON glp.game_id=e.game_id
                                                AND glp.player_id=e.primary_player_id
                    WHERE e.game_id=? AND e.event_type='shot'
                      AND e.zone IS NOT NULL AND glp.team_id!=?
                """, (_gids[0], team_id))
            else:
                _opp_shots_ts = query(f"""
                    SELECT e.zone, e.shot_type, e.shot_result
                    FROM game_events e
                    JOIN game_lineup_players glp ON glp.game_id=e.game_id
                                                AND glp.player_id=e.primary_player_id
                    WHERE e.game_id IN ({','.join('?'*len(_gids))})
                      AND e.event_type='shot' AND e.zone IS NOT NULL AND glp.team_id!=?
                """, (*_gids, team_id))
            with sc_c2:
                show_shot_chart(_opp_shots_ts, "Opponents — Offense (Defense Quality)")

        st.divider()

        # ── Quarter / Half Breakdown ──────────────────────────────────────────
        st.subheader("Quarter Breakdown")
        _qperiods = [
            ("Q1", a.get("q1_pts_pg", 0), a.get("opp_q1_pts_pg", 0),
                   a.get("q1_ppp", 0),    a.get("opp_q1_ppp", 0)),
            ("Q2", a.get("q2_pts_pg", 0), a.get("opp_q2_pts_pg", 0),
                   a.get("q2_ppp", 0),    a.get("opp_q2_ppp", 0)),
            ("H1", a.get("h1_pts_pg",  0), a.get("opp_h1_pts_pg",  0),
                   a.get("h1_ppp",  0),    a.get("opp_h1_ppp",  0)),
            ("Q3", a.get("q3_pts_pg", 0), a.get("opp_q3_pts_pg", 0),
                   a.get("q3_ppp", 0),    a.get("opp_q3_ppp", 0)),
            ("Q4", a.get("q4_pts_pg", 0), a.get("opp_q4_pts_pg", 0),
                   a.get("q4_ppp", 0),    a.get("opp_q4_ppp", 0)),
            ("H2", a.get("h2_pts_pg",  0), a.get("opp_h2_pts_pg",  0),
                   a.get("h2_ppp",  0),    a.get("opp_h2_ppp",  0)),
        ]
        _qdf_rows = [
            {
                "Period":  p,
                "Pts/G":   f"{pts:.1f}",
                "PPP":     f"{ppp:.2f}" if ppp is not None and ppp > 0 else "—",
                "PA/G":    f"{pa:.1f}",
                "Opp PPP": f"{oppp:.2f}" if oppp is not None and oppp > 0 else "—",
                "Diff":    f"{pts - pa:+.1f}",
            }
            for p, pts, pa, ppp, oppp in _qperiods
        ]
        _qdf = pd.DataFrame(_qdf_rows)

        def _quarter_row_style(row):
            if row["Period"] in ("H1", "H2"):
                return ["font-weight:700; background-color:#1c2230"] * len(row)
            return [""] * len(row)

        def _ppp_cell_style(val):
            """Green if PPP ≥ 1.0, red if < 0.85, neutral otherwise."""
            try:
                v = float(val)
                if v >= 1.0:  return "color:#2ecc71; font-weight:600"
                if v < 0.85:  return "color:#e74c3c; font-weight:600"
            except (TypeError, ValueError):
                pass
            return ""

        st.dataframe(
            _qdf.style
                .apply(_quarter_row_style, axis=1)
                .map(_ppp_cell_style, subset=["PPP", "Opp PPP"]),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            f"Per-game averages across {gp_ts} tracked game{'s' if gp_ts != 1 else ''}. "
            "H1 = Q1+Q2  ·  H2 = Q3+Q4  ·  Diff = Pts/G − PA/G  ·  "
            "PPP = points per possession (green ≥ 1.00, red < 0.85)"
        )

# ══════════════════════════════════════════════════════════════════════════════
#  PLAYERS
# ══════════════════════════════════════════════════════════════════════════════
with tab_pl:
    players = query("SELECT id, name, number, height, wingspan, weight FROM players WHERE team_id=? ORDER BY name", (team_id,))
    if not players:
        st.info("No players on roster.")
    else:
        # Aggregate stats table
        stat_rows=[]
        player_careers={}
        for p in players:
            c=compute_player_career(p["id"])
            player_careers[p["id"]]=c

        # Team SC total (for SC%)
        team_sc_total = sum(c["sc"] for c in player_careers.values() if c and c["gp"]>0)

        # On/Off data (uses game_event_lineup snapshots)
        on_off_data = compute_on_off(team_id)

        for p in players:
            c=player_careers[p["id"]]
            if c and c["gp"]>0:
                gp=c["gp"]
                fgp=c["fgm"]/c["fga"] if c["fga"] else 0
                tpp=c["tpm"]/c["tpa"] if c["tpa"] else 0
                ftp=c["ftm"]/c["fta"] if c["fta"] else 0
                efg=(c["fgm"]+0.5*c["tpm"])/c["fga"] if c["fga"] else 0
                ts =c["pts"]/(2*(c["fga"]+0.44*c["fta"])) if (c["fga"]+0.44*c["fta"]) else 0
                reb=(c["oreb"]+c["dreb"])
                gs =round((c["pts"]+0.4*c["fgm"]-0.7*c["fga"]-0.4*(c["fta"]-c["ftm"])
                           +0.7*c["oreb"]+0.3*c["dreb"]+c["stl"]+0.7*c["ast"]
                           +0.7*c["blk"]-0.4*c["pf"]-c["tov"])/gp, 1)
                sc_pct  = round(c["sc"]/team_sc_total*100, 1) if team_sc_total else 0
                sce_den = (c["fga"] - c["tpa"]) * 2 + c["tpa"] * 3
                sce     = round(c["pts"] / sce_den, 3) if sce_den else 0
                ast_tov = round(c["ast"]/c["tov"], 2) if c["tov"] else ("∞" if c["ast"] else "—")
                sc_fga  = round(c["sc"]/c["fga"], 2) if c["fga"] else 0
                pts_sc  = round(c["pts"]/c["sc"], 2) if c["sc"] else 0
                # On/Off derived metrics
                oo = on_off_data.get(p["id"], {})
                on_p  = oo.get("on_poss", 0)
                off_p = oo.get("off_poss", 0)
                on_pf = oo.get("on_pts_for", 0)
                on_pa = oo.get("on_pts_against", 0)
                off_pf= oo.get("off_pts_for", 0)
                off_pa= oo.get("off_pts_against", 0)
                pu    = oo.get("poss_used", 0)

                net_on  = (on_pf  - on_pa)  / on_p  * 100 if on_p  else None
                net_off = (off_pf - off_pa) / off_p * 100 if off_p else None
                on_off  = round(net_on - net_off, 1) if (net_on is not None and net_off is not None) else "—"
                usg_pct = round(pu / on_p * 100, 1) if on_p else 0
                poss_pg = round(pu / gp, 1) if gp else 0
                pts_poss= round(c["pts"] / pu, 3) if pu else 0

                # Shot quality
                sht_q    = round(c["shot_rating"] / c["est_fg_shots"], 2) if c["est_fg_shots"] else "—"
                efg_est  = round(c["est_fg_sum"]  / c["est_fg_shots"] * 100, 1) if c["est_fg_shots"] else "—"
                # Defensive
                dfga_pg  = round(c["def_fga"] / gp, 1)
                dsh_pct  = round(c["def_fga"] / c["on_court_opp_shots"] * 100, 1) if c["on_court_opp_shots"] else "—"

                stat_rows.append({
                    "Player":p["name"],"#":p["number"],"GP":gp,
                    "PTS":round(c["pts"]/gp,1),"AST":round(c["ast"]/gp,1),
                    "REB":round(reb/gp,1),"OREB":round(c["oreb"]/gp,1),"DREB":round(c["dreb"]/gp,1),
                    "STL":round(c["stl"]/gp,1),"BLK":round(c["blk"]/gp,1),
                    "TOV":round(c["tov"]/gp,1),
                    "FGM":round(c["fgm"]/gp,1),"FGA":round(c["fga"]/gp,1),
                    "FG%":f"{fgp*100:.1f}","3PM":round(c["tpm"]/gp,1),"3PA":round(c["tpa"]/gp,1),
                    "3P%":f"{tpp*100:.1f}","FTM":round(c["ftm"]/gp,1),"FTA":round(c["fta"]/gp,1),
                    "FT%":f"{ftp*100:.1f}",
                    "eFG%":f"{efg*100:.1f}","TS%":f"{ts*100:.1f}",
                    "SC":round(c["sc"]/gp,1),"SC%":sc_pct,"SCE":sce,
                    "AST/TOV":ast_tov,"SC/FGA":sc_fga,"PTS/SC":pts_sc,
                    "MIN":round(c["poss_secs"]/60/gp,1),"GS":gs,
                    # Shot quality
                    "ShtQ":sht_q, "eFG%E":efg_est,
                    # Possession & On/Off
                    "+/-":c["plus_minus"],
                    "Poss/G":poss_pg, "Usg%":usg_pct, "PTS/Poss":pts_poss,
                    "Net On":round(net_on, 1) if net_on is not None else "—",
                    "Net Off":round(net_off,1) if net_off is not None else "—",
                    "On/Off":on_off,
                    # Defensive
                    "DFGA/G":dfga_pg, "DSh%":dsh_pct,
                    "_pid":p["id"],
                })
            else:
                stat_rows.append({"Player":p["name"],"#":p["number"],"GP":0,
                                   **{k:"—" for k in ["PTS","AST","REB","OREB","DREB","STL","BLK","TOV",
                                                       "FGM","FGA","FG%","2PM","2PA","2P%",
                                                       "3PM","3PA","3P%","FTM","FTA","FT%",
                                                       "eFG%","TS%","FTr","PPS","PPSA","TOV%",
                                                       "EFF","FIC","PRF",
                                                       "SC","SC%","SCE","AST/TOV","SC/FGA",
                                                       "PTS/SC","MIN","GS","Q4 PPG",
                                                       "ShtQ","eFG%E",
                                                       "+/-","Poss/G","Usg%","PTS/Poss",
                                                       "Net On","Net Off","On/Off",
                                                       "DFGA/G","DSh%",
                                                       "OVRL","OFF","DEF","PLY","REB_R"]},
                                   "_pid":p["id"]})

        disp_cols=["Player","#","GP","OVRL","OFF","DEF","PLY","REB_R",
                   "PTS","AST","REB","OREB","DREB","STL","BLK","TOV",
                   "FGM","FGA","FG%","2PM","2PA","2P%","3PM","3PA","3P%","FTM","FTA","FT%",
                   "eFG%","TS%","FTr","PPS","PPSA","TOV%","EFF","FIC","PRF",
                   "SC","SC%","SCE","AST/TOV","SC/FGA","PTS/SC","MIN","GS","Q4 PPG",
                   "ShtQ","eFG%E",
                   "+/-","Poss/G","Usg%","PTS/Poss","Net On","Net Off","On/Off",
                   "DFGA/G","DSh%"]
        df_pl=pd.DataFrame(stat_rows)

        # Merge OVRL / OFF / DEF / PLY / REB_R from ratings
        _pl_rat = compute_player_ratings()
        _rating_cols = ["OVRL","OFF","DEF","PLY","REB_R"]
        if not _pl_rat.empty and "pid" in _pl_rat.columns:
            _rat_cols = [c for c in ["pid"] + _rating_cols if c in _pl_rat.columns]
            _pl_rat_slim = _pl_rat[_rat_cols].copy()
            for _rc in _rating_cols:
                if _rc in _pl_rat_slim.columns:
                    _pl_rat_slim[_rc] = pd.to_numeric(_pl_rat_slim[_rc], errors="coerce").round(1)
            df_pl = df_pl.merge(_pl_rat_slim, left_on="_pid", right_on="pid", how="left").drop(columns=["pid"], errors="ignore")
        # Fill missing ratings with "—"
        for _rc in _rating_cols:
            if _rc not in df_pl.columns:
                df_pl[_rc] = "—"
            else:
                df_pl[_rc] = df_pl[_rc].where(df_pl[_rc].notna(), "—")

        # Keep only columns that exist
        disp_cols = [c for c in disp_cols if c in df_pl.columns]

        # ── Top 5 Offense / Defense Lineup ───────────────────────────────────
        _rated = df_pl[
            df_pl["GP"].apply(lambda v: isinstance(v, (int, float)) and v > 0)
        ].copy()
        for _rc in ["OFF", "DEF"]:
            if _rc in _rated.columns:
                _rated[_rc] = pd.to_numeric(_rated[_rc], errors="coerce")

        _has_off = "OFF" in _rated.columns and _rated["OFF"].notna().any()
        _has_def = "DEF" in _rated.columns and _rated["DEF"].notna().any()

        if _has_off or _has_def:
            st.subheader("Lineup Ratings")
            _lu_col1, _lu_col2 = st.columns(2)

            _rank_labels = ["🥇", "🥈", "🥉", "4.", "5."]

            if _has_off:
                _top_off = (_rated.dropna(subset=["OFF"])
                                  .nlargest(5, "OFF")[["Player", "#", "GP", "OFF", "PTS", "TS%"]]
                                  .reset_index(drop=True))
                with _lu_col1:
                    st.markdown("**⚡ Top 5 — Offense Rating**")
                    for _i, _row in _top_off.iterrows():
                        _pts_val = f"{_row['PTS']}" if isinstance(_row['PTS'], (int, float)) else "—"
                        _ts_val  = f"{_row['TS%']}"  if isinstance(_row['TS%'],  (int, float)) else "—"
                        st.markdown(f"""
<div class="lu-row-card">
  <div class="lu-rank">{_rank_labels[_i]}</div>
  <div class="lu-body">
    <div class="lu-name">#{int(_row['#']) if isinstance(_row['#'], (int,float)) else _row['#']} &nbsp;{_row['Player']}</div>
    <div class="lu-meta">GP {int(_row['GP'])} &middot; PTS/G {_pts_val} &middot; TS% {_ts_val}</div>
  </div>
  <div class="lu-score" style="color:#f0a500">{_row['OFF']:.1f}</div>
</div>""", unsafe_allow_html=True)

            if _has_def:
                _top_def = (_rated.dropna(subset=["DEF"])
                                  .nlargest(5, "DEF")[["Player", "#", "GP", "DEF", "STL", "BLK"]]
                                  .reset_index(drop=True))
                with _lu_col2:
                    st.markdown("**🛡 Top 5 — Defense Rating**")
                    for _i, _row in _top_def.iterrows():
                        _stl_val = f"{_row['STL']}" if isinstance(_row['STL'], (int, float)) else "—"
                        _blk_val = f"{_row['BLK']}" if isinstance(_row['BLK'], (int, float)) else "—"
                        st.markdown(f"""
<div class="lu-row-card">
  <div class="lu-rank">{_rank_labels[_i]}</div>
  <div class="lu-body">
    <div class="lu-name">#{int(_row['#']) if isinstance(_row['#'], (int,float)) else _row['#']} &nbsp;{_row['Player']}</div>
    <div class="lu-meta">GP {int(_row['GP'])} &middot; STL/G {_stl_val} &middot; BLK/G {_blk_val}</div>
  </div>
  <div class="lu-score" style="color:#3498db">{_row['DEF']:.1f}</div>
</div>""", unsafe_allow_html=True)

            st.divider()

        st.subheader("Per Game Averages (Tracked Games)")
        if not df_pl.empty:
            st.dataframe(df_pl[disp_cols], use_container_width=True, hide_index=True)
            st.download_button("⬇ Export Player Stats (CSV)",
                               df_pl[disp_cols].to_csv(index=False),
                               file_name=f"{sel_name}_player_stats.csv",
                               mime="text/csv", key="dl_pl_stats")

        st.divider()
        st.subheader("Player Comparison Radar")
        show_player_radar(df_pl[df_pl["GP"] > 0].copy(), key="main_radar")

        st.divider()
        st.subheader("Individual Breakdowns")
        for p in players:
            c=player_careers.get(p["id"])
            label=f"#{p['number']}  {p['name']}"
            if p["height"]: label+=f"  ·  {p['height']}in"
            with st.expander(label):
                bio_cols=st.columns(4)
                bio_cols[0].metric("Height",  f"{p['height']}\"" if p['height'] else "—")
                bio_cols[1].metric("Wingspan", f"{p['wingspan']}\"" if p['wingspan'] else "—")
                bio_cols[2].metric("Weight",   f"{p['weight']} lbs" if p['weight'] else "—")
                bio_cols[3].metric("Number",   f"#{p['number']}")

                if not c or c["gp"]==0:
                    st.info("No tracked game data.")
                    continue

                mc=st.columns(5)
                mc[0].metric("PTS/G", f"{c['pts']/c['gp']:.1f}")
                mc[1].metric("REB/G", f"{(c['oreb']+c['dreb'])/c['gp']:.1f}")
                mc[2].metric("AST/G", f"{c['ast']/c['gp']:.1f}")
                mc[3].metric("STL/G", f"{c['stl']/c['gp']:.1f}")
                mc[4].metric("BLK/G", f"{c['blk']/c['gp']:.1f}")

                shoot_cols=st.columns(4)
                fgp_=c["fgm"]/c["fga"] if c["fga"] else 0
                tpp_=c["tpm"]/c["tpa"] if c["tpa"] else 0
                ftp_=c["ftm"]/c["fta"] if c["fta"] else 0
                ts_ =c["pts"]/(2*(c["fga"]+0.44*c["fta"])) if (c["fga"]+0.44*c["fta"]) else 0
                shoot_cols[0].metric("FG%", f"{fgp_*100:.1f}%")
                shoot_cols[1].metric("3P%", f"{tpp_*100:.1f}%")
                shoot_cols[2].metric("FT%", f"{ftp_*100:.1f}%")
                shoot_cols[3].metric("TS%", f"{ts_*100:.1f}%")

                # SC metrics
                sc_pct_  = round(c["sc"]/team_sc_total*100, 1) if team_sc_total else 0
                sce_den_ = (c["fga"] - c["tpa"]) * 2 + c["tpa"] * 3
                sce_     = round(c["pts"] / sce_den_, 3) if sce_den_ else 0
                ast_tov_ = round(c["ast"]/c["tov"], 2) if c["tov"] else ("∞" if c["ast"] else "—")
                sc_fga_  = round(c["sc"]/c["fga"], 2) if c["fga"] else 0
                pts_sc_  = round(c["pts"]/c["sc"], 2) if c["sc"] else 0

                st.markdown("**Shot Creation**")
                sc_cols = st.columns(6)
                sc_cols[0].metric("SC/G",    f"{c['sc']/c['gp']:.1f}")
                sc_cols[1].metric("SC%",     f"{sc_pct_}%",    help="% of team's total shot creation")
                sc_cols[2].metric("SCE",     f"{sce_:.3f}",    help="PTS / ((2PT_att×2) + (3PT_att×3))")
                sc_cols[3].metric("AST/TOV", f"{ast_tov_}",    help="Assist-to-turnover ratio")
                sc_cols[4].metric("SC/FGA",  f"{sc_fga_:.2f}", help="Shot creations per field goal attempt")
                sc_cols[5].metric("PTS/SC",  f"{pts_sc_:.2f}", help="Points scored per shot creation act")

                # ── Shot Quality ────────────────────────────────────────────
                _esf = c["est_fg_shots"]
                _sht_q   = round(c["shot_rating"] / _esf, 2) if _esf else None
                _efg_est = round(c["est_fg_sum"] / _esf * 100, 1) if _esf else None

                st.markdown("**Shot Quality** *(zone-logged shots only)*")
                sq_cols = st.columns(4)
                sq_cols[0].metric("Shot Rating",
                                  f"{_sht_q:+.2f}" if _sht_q is not None else "—",
                                  help="Avg shot rating per attempt. Positive = good looks (open, high-% spot), Negative = difficult shots (contested, low-% spot)")
                sq_cols[1].metric("Est FG%",
                                  f"{_efg_est:.1f}%" if _efg_est is not None else "—",
                                  help="Estimated FG% based on shot location and whether the shot was contested")
                sq_cols[2].metric("Actual FG%",
                                  f"{fgp_*100:.1f}%",
                                  help="Actual field goal percentage — compare to Est FG% to see if they over/under-perform their shot quality")
                _fg_diff = round(fgp_*100 - _efg_est, 1) if _efg_est is not None else None
                sq_cols[3].metric("FG% vs Est",
                                  f"{_fg_diff:+.1f}%" if _fg_diff is not None else "—",
                                  help="Actual FG% minus Estimated FG%. Positive = outperforming shot quality; Negative = underperforming")

                if c["shots"]:
                    # Shot quality breakdown by zone — uses uncontested baseline (guarded flag not stored per shot)
                    _zone_data = {}
                    for sh in c["shots"]:
                        _k = (sh["shot_type"], sh["zone"])
                        _e = _zone_data.setdefault(_k, {"fga":0,"fgm":0})
                        _e["fga"] += 1
                        if sh["shot_result"] == "make": _e["fgm"] += 1
                    _sq_table = []
                    for (stype, zone), d in sorted(_zone_data.items()):
                        _est_unc = EST_FGP.get((stype, zone, False))
                        _est_con = EST_FGP.get((stype, zone, True))
                        _sq_table.append({
                            "Type": f"{stype}PT", "Zone": zone,
                            "FGA": d["fga"],
                            "Actual FG%": f"{d['fgm']/d['fga']*100:.0f}%" if d["fga"] else "—",
                            "Open baseline": f"{_est_unc*100:.0f}%" if _est_unc else "—",
                            "Contested baseline": f"{_est_con*100:.0f}%" if _est_con else "—",
                            "Open rating": f"{SHOT_RATING.get((stype,zone,False),0):+.1f}",
                            "Contested rating": f"{SHOT_RATING.get((stype,zone,True),0):+.1f}",
                        })
                    if _sq_table:
                        st.dataframe(pd.DataFrame(_sq_table), hide_index=True, use_container_width=True)
                        st.caption(
                            "Baselines are zone/contest averages before creation context. "
                            "**Shot Rating** and **Est FG%** shown above already include the "
                            "creation modifier applied per shot:  "
                            "Pass + Created (designed play) **+0.30 / +7%** · "
                            "Pass only (assisted) **+0.15 / +4%** · "
                            "Created only (screen/drive) **+0.08 / +2%** · "
                            "Self-created (no context) **−0.10 / −2%**"
                        )

                # ── Per-32 Stats (HS equivalent of per-36) ──────────────────
                _mins32 = c["poss_secs"]/60
                if _mins32 > 0:
                    _m32 = 32/_mins32
                    st.markdown("**Per-32 Minutes** *(high-school game equivalent)*")
                    p32_cols = st.columns(7)
                    p32_cols[0].metric("PTS/32",  f"{c['pts']*_m32:.1f}")
                    p32_cols[1].metric("AST/32",  f"{c['ast']*_m32:.1f}")
                    p32_cols[2].metric("REB/32",  f"{(c['oreb']+c['dreb'])*_m32:.1f}")
                    p32_cols[3].metric("STL/32",  f"{c['stl']*_m32:.1f}")
                    p32_cols[4].metric("BLK/32",  f"{c['blk']*_m32:.1f}")
                    p32_cols[5].metric("TOV/32",  f"{c['tov']*_m32:.1f}")
                    p32_cols[6].metric("FGA/32",  f"{c['fga']*_m32:.1f}")

                # ── Scoring Source ───────────────────────────────────────────
                _c_pts2 = (c["fgm"]-c["tpm"])*2
                _c_pts3 = c["tpm"]*3
                _c_ptft = c["ftm"]
                _c_tot  = _c_pts2 + _c_pts3 + _c_ptft
                if _c_tot > 0:
                    st.markdown("**Scoring Distribution**")
                    show_scoring_pie(_c_pts2, _c_pts3, _c_ptft,
                                     f"{p['name']} — Scoring Sources")

                # ── Defensive Impact ────────────────────────────────────────
                st.markdown("**Defensive Impact**")
                _dfga   = c["def_fga"]
                _oc_opp = c["on_court_opp_shots"]

                di_cols = st.columns(2)
                di_cols[0].metric("DFGA/G",
                                  f"{_dfga/c['gp']:.1f}",
                                  help="Shots defended per game (guarded_by logged on shot events)")
                di_cols[1].metric("Contested Sh%",
                                  f"{_dfga/_oc_opp*100:.1f}%" if _oc_opp else "—",
                                  help="Defended shots ÷ total opponent shots while on court — how often this player contests shots")

                # ── Possession & On/Off Impact ──────────────────────────────
                oo_ = on_off_data.get(p["id"], {})
                on_p_  = oo_.get("on_poss", 0)
                off_p_ = oo_.get("off_poss", 0)
                on_pf_ = oo_.get("on_pts_for", 0)
                on_pa_ = oo_.get("on_pts_against", 0)
                off_pf_= oo_.get("off_pts_for", 0)
                off_pa_= oo_.get("off_pts_against", 0)
                pu_    = oo_.get("poss_used", 0)

                has_oo = on_p_ > 0

                st.markdown("**Possession & On/Off Impact**")
                po_cols = st.columns(4)
                po_cols[0].metric("Poss Used/G",  f"{pu_/c['gp']:.1f}" if c['gp'] else "—",
                                  help="Shots taken + turnovers per game — times they touched ball and ended a possession")
                po_cols[1].metric("Usg%",         f"{pu_/on_p_*100:.1f}%" if on_p_ else "—",
                                  help="% of team possessions used by this player while on court")
                po_cols[2].metric("PTS/Poss",     f"{c['pts']/pu_:.3f}" if pu_ else "—",
                                  help="Points scored per possession used")
                po_cols[3].metric("Career +/-",   f"{c['plus_minus']:+d}",
                                  help="Total plus/minus across all tracked games")

                if has_oo:
                    net_on_  = (on_pf_  - on_pa_)  / on_p_  * 100
                    net_off_ = (off_pf_ - off_pa_) / off_p_ * 100 if off_p_ else None
                    on_off_v = f"{net_on_ - net_off_:+.1f}" if net_off_ is not None else "—"

                    st.markdown("*On-Court vs Off-Court (per 100 team possessions)*")
                    oc_cols = st.columns(3)
                    oc_cols[0].metric("Net Rtg ON",  f"{net_on_:+.1f}",
                                      help="Team point differential per 100 possessions while this player is on court")
                    oc_cols[1].metric("Net Rtg OFF",
                                      f"{net_off_:+.1f}" if net_off_ is not None else "—",
                                      help="Team point differential per 100 possessions while this player is off court")
                    oc_cols[2].metric("On/Off Impact", on_off_v,
                                      help="Net Rating ON minus Net Rating OFF — how much better/worse the team is with this player")

                    # Detailed on/off table
                    ortg_on  = on_pf_  / on_p_  * 100
                    drtg_on  = on_pa_  / on_p_  * 100
                    ortg_off = off_pf_ / off_p_ * 100 if off_p_ else 0
                    drtg_off = off_pa_ / off_p_ * 100 if off_p_ else 0
                    oo_table = pd.DataFrame([
                        {"Split": "ON Court",  "Poss": on_p_,
                         "ORtg": round(ortg_on,1),  "DRtg": round(drtg_on,1),
                         "Net": round(net_on_,1),
                         "Pts For": on_pf_,  "Pts Against": on_pa_},
                        {"Split": "OFF Court", "Poss": off_p_,
                         "ORtg": round(ortg_off,1), "DRtg": round(drtg_off,1),
                         "Net": round(net_off_,1) if net_off_ is not None else "—",
                         "Pts For": off_pf_, "Pts Against": off_pa_},
                    ])
                    st.dataframe(oo_table, hide_index=True, use_container_width=True)
                else:
                    st.caption("On/Off data requires games with lineup snapshots logged in Game Tracker.")

                if c["shots"]:
                    render_hot_zones(c["shots"])

                # ── Game Log ────────────────────────────────────────────────
                st.markdown("**Game Log**")
                gl = compute_player_game_log(p["id"], team_id)
                if gl:
                    gl_cols = ["Date","Opp","W/L","Score",
                               "PTS","AST","REB","STL","BLK","TOV",
                               "FGM","FGA","FG%","3PM","3PA","3P%",
                               "FTM","FTA","FT%","SC","SC%","Poss","+/-","MIN","GS"]
                    gl_df = pd.DataFrame(gl)[gl_cols]

                    # Colour W/L column green/red with styling
                    def _wl_style(val):
                        return "color:#2ecc71;font-weight:bold" if val=="W" else "color:#e74c3c;font-weight:bold"

                    st.dataframe(
                        gl_df.style.map(_wl_style, subset=["W/L"]),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "MIN":  st.column_config.NumberColumn("MIN",  format="%.1f"),
                            "SC%":  st.column_config.NumberColumn("SC%",  format="%.1f"),
                            "GS":   st.column_config.NumberColumn("GS",   format="%.1f"),
                        },
                    )
                    st.download_button(
                        "⬇ Export Game Log (CSV)",
                        gl_df.to_csv(index=False),
                        file_name=f"{p['name'].replace(' ','_')}_game_log.csv",
                        mime="text/csv",
                        key=f"dl_gl_{p['id']}",
                    )
                else:
                    st.caption("No tracked game data yet.")

# ══════════════════════════════════════════════════════════════════════════════
#  RATINGS TAB
# ══════════════════════════════════════════════════════════════════════════════
with tab_rat:
    # CSS reuse (same classes as Rankings page)
    st.markdown("""
<style>
.rat-card{background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);
border:1px solid #30363d;border-radius:12px;padding:16px 18px;margin-bottom:10px;}
.rat-title{font-size:16px;font-weight:800;color:#f0a500;margin-bottom:6px;}
.rat-desc{font-size:12px;color:#c9d1d9;line-height:1.5;}
.rat-comp{font-size:11px;color:#8b949e;margin-top:6px;}
.rpl-card{background:linear-gradient(135deg,#0f3460 0%,#16213e 100%);
border:1px solid #1f4d8a;border-radius:12px;padding:16px;text-align:center;margin-bottom:8px;}
.rpl-label{font-size:10px;color:#8b949e;text-transform:uppercase;
letter-spacing:1px;margin-bottom:4px;}
.rpl-score{font-size:34px;font-weight:800;color:#f0a500;}
.rpl-name{font-size:15px;font-weight:700;color:#f0f6fc;margin-top:4px;}
.rpl-meta{font-size:11px;color:#8b949e;}
.rpl-bar-wrap{background:#2d333b;border-radius:6px;height:8px;margin-top:6px;}
.rpl-bar-fill{height:100%;border-radius:6px;}
</style>
""", unsafe_allow_html=True)

    # Load all ratings then filter to this team
    _all_ratings = compute_player_ratings()

    if _all_ratings.empty:
        st.info("No player rating data yet — track at least 2 games first.")
    else:
        _team_ratings = _all_ratings[_all_ratings["Team"] == sel_name].copy()

        # ── Rating description cards ─────────────────────────────────────────
        st.markdown("""
<div style="display:flex;gap:12px;margin-bottom:10px;align-items:stretch">
  <div class="rat-card" style="flex:1">
    <div class="rat-title">⚡ OFF — Offensive Rating</div>
    <div class="rat-desc">Overall offensive impact. Blends a Shooting sub-score
    (TS%, eFG%, 3P%, FT%, Shot Rating) with a Finishing sub-score (PPG, Paint FG%,
    Shots Created, FG%) into one 0–100 number.</div>
    <div class="rat-comp">Shooting 50%: TS% 30 · eFG% 25 · 3P% 20 · FT% 15 · ShotRat 10 | Finishing 50%: PTS 35 · PaintFG% 30 · SC 20 · FG% 15</div>
  </div>
  <div class="rat-card" style="flex:1">
    <div class="rat-title">🛡️ DEF — Defensive Rating</div>
    <div class="rat-desc">Defensive presence and disruption. Rewards contested-shot
    percentage, combined stocks (STL+BLK), defensive rebounding, and individual
    steal/block totals.</div>
    <div class="rat-comp">DSh% 30% · Stocks 25% · DREB 25% · STL 10% · BLK 10%</div>
  </div>
  <div class="rat-card" style="flex:1">
    <div class="rat-title">🎯 PLY — Playmaking Rating</div>
    <div class="rat-desc">Ball-handling and creation value. Rewards assist volume,
    assist-to-turnover efficiency, low turnovers, and shot creation for teammates.</div>
    <div class="rat-comp">AST 30% · AST/TOV 25% · TOV(inv) 20% · SC 15% · PTS 10%</div>
  </div>
  <div class="rat-card" style="flex:1">
    <div class="rat-title">📦 REB_R — Rebounding Rating</div>
    <div class="rat-desc">Glass-cleaning ability. Heavily weights offensive and
    defensive rebounding totals, total boards, and paint activity (FGA inside).</div>
    <div class="rat-comp">OREB 35% · DREB 35% · REB 20% · PaintFGA 10%</div>
  </div>
</div>""", unsafe_allow_html=True)

        st.divider()

        # ── Per-player rating cards ──────────────────────────────────────────
        if _team_ratings.empty:
            st.info("No tracked game data for this team's players yet (min 1 GP required).")
        else:
            st.markdown(f'<div class="section-hdr">{sel_name} — Player Ratings</div>',
                        unsafe_allow_html=True)
            st.caption("Scores are 0–100, league-wide relative. 100 = top performer across all teams.")

            def _rating_bar(score: float, color: str) -> str:
                pct = min(100, max(0, score))
                return (f'<div class="rpl-bar-wrap">'
                        f'<div class="rpl-bar-fill" style="width:{pct:.0f}%;background:{color}"></div>'
                        f'</div>')

            _rat_cols = st.columns(min(4, len(_team_ratings)))
            for i, (_, row) in enumerate(_team_ratings.sort_values("OVRL", ascending=False).iterrows()):
                c = _rat_cols[i % 4]
                off_bar  = _rating_bar(row["OFF"],   "#f0a500")
                def_bar  = _rating_bar(row["DEF"],   "#3498db")
                ply_bar  = _rating_bar(row["PLY"],   "#2ecc71")
                reb_bar  = _rating_bar(row["REB_R"], "#e67e22")
                c.markdown(f"""
<div class="rpl-card">
  <div class="rpl-name">#{row.get('#','')} {row['Player']}</div>
  <div class="rpl-meta">{row['GP']} GP · {row['MIN']:.1f} MPG · OVRL {row['OVRL']:.1f}</div>
  <div style="margin-top:12px">
    <div style="display:flex;justify-content:space-between;font-size:11px;color:#8b949e">
      <span>⚡ OFF</span><span style="color:#f0a500;font-weight:700">{row['OFF']:.1f}</span>
    </div>{off_bar}
  </div>
  <div style="margin-top:8px">
    <div style="display:flex;justify-content:space-between;font-size:11px;color:#8b949e">
      <span>🛡️ DEF</span><span style="color:#3498db;font-weight:700">{row['DEF']:.1f}</span>
    </div>{def_bar}
  </div>
  <div style="margin-top:8px">
    <div style="display:flex;justify-content:space-between;font-size:11px;color:#8b949e">
      <span>🎯 PLY</span><span style="color:#2ecc71;font-weight:700">{row['PLY']:.1f}</span>
    </div>{ply_bar}
  </div>
  <div style="margin-top:8px">
    <div style="display:flex;justify-content:space-between;font-size:11px;color:#8b949e">
      <span>📦 REB</span><span style="color:#e67e22;font-weight:700">{row['REB_R']:.1f}</span>
    </div>{reb_bar}
  </div>
  <div style="margin-top:10px;font-size:10px;color:#8b949e;text-align:left">
    PPG {row['PTS']} · AST {row['AST']} · REB {row['REB']}<br>
    STL {row['STL']} · BLK {row['BLK']} · 3P% {row['3P%']}
  </div>
</div>""", unsafe_allow_html=True)

            st.divider()

            # ── Role ranking within team ─────────────────────────────────────
            st.markdown("#### Team Role Rankings")
            role_tab_off, role_tab_def, role_tab_ply, role_tab_reb = st.tabs([
                "⚡ Offense (OFF)",
                "🛡️ Defense (DEF)",
                "🎯 Playmaking (PLY)",
                "📦 Rebounding (REB_R)",
            ])

            def _role_table(df, score_col, extra_cols, color):
                if df.empty:
                    st.info("No data.")
                    return
                out = df[["Player", "#", "GP", "MIN"] + extra_cols + [score_col]
                         ].sort_values(score_col, ascending=False).reset_index(drop=True)
                out.index += 1
                # League rank
                all_sorted = _all_ratings.sort_values(score_col, ascending=False).reset_index(drop=True)
                all_sorted["League Rank"] = all_sorted.index + 1
                out = out.merge(
                    all_sorted[["Player", "Team", "League Rank"]],
                    on=["Player"], how="left"
                )
                st.dataframe(out, use_container_width=True)

                # Bar chart
                fig = go.Figure(go.Bar(
                    x=out[score_col],
                    y=out["Player"],
                    orientation="h",
                    marker_color=color,
                    text=out[score_col].apply(lambda v: f"{v:.1f}"),
                    textposition="outside",
                ))
                fig.update_layout(
                    height=max(260, len(out) * 38 + 80),
                    xaxis=dict(range=[0, 110],
                               gridcolor="rgba(128,128,128,0.15)"),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=10, r=80, t=20, b=20),
                    font=dict(size=11),
                )
                st.plotly_chart(fig, use_container_width=True)

            with role_tab_off:
                st.caption("Higher OFF = better offensive player. "
                           "Combines shooting efficiency (TS%, eFG%, 3P%, FT%) with "
                           "finishing/production (PPG, PaintFG%, SC, FG%). "
                           "League Rank shows where this player stands against ALL teams.")
                _role_table(_team_ratings,
                            "OFF",
                            ["PTS", "eFG%", "TS%", "PaintFG%", "SC", "3P%"],
                            "#f0a500")
            with role_tab_def:
                st.caption("Higher DEF = better defender. "
                           "DSh% = contested-shot differential · Stocks = STL+BLK/G.")
                _role_table(_team_ratings,
                            "DEF",
                            ["STL", "BLK", "Stocks", "DREB", "+/-"],
                            "#3498db")
            with role_tab_ply:
                st.caption("Higher PLY = better playmaker/ball-handler. "
                           "SC = shots created/G · AST/TOV ratio rewards decision-making.")
                _role_table(_team_ratings,
                            "PLY",
                            ["AST", "TOV", "SC", "GS", "+/-"],
                            "#2ecc71")
            with role_tab_reb:
                st.caption("Higher REB_R = better rebounder. "
                           "PaintFGA = paint field-goal attempts per game (proxy for interior activity).")
                _role_table(_team_ratings,
                            "REB_R",
                            ["OREB", "DREB", "REB", "PaintFGA", "BLK"],
                            "#e67e22")

            st.divider()

            # ── Three-way radar overlay for all team players ─────────────────
            st.markdown("#### Player Rating Scatter")
            st.caption("Each dot = one player. Bubble size = REB_R. Best all-around players appear top-right.")
            if len(_team_ratings) >= 2:
                fig_rad = px.scatter(
                    _team_ratings,
                    x="OFF", y="DEF",
                    size="REB_R",
                    size_max=45,
                    text="Player",
                    color="PLY",
                    color_continuous_scale=[[0, "#1a3a5c"], [0.5, "#f0a500"], [1, "#2ecc71"]],
                    hover_name="Player",
                    hover_data={"OFF": ":.1f", "DEF": ":.1f", "PLY": ":.1f", "REB_R": ":.1f",
                                "PTS": ":.1f", "AST": ":.1f", "REB": ":.1f",
                                "Team": False},
                    title=f"{sel_name} — Offense vs Defense (bubble = REB_R, color = PLY)",
                )
                fig_rad.update_traces(textposition="top center", textfont_size=10)
                fig_rad.update_layout(
                    height=500,
                    xaxis=dict(title="OFF — Offensive Rating (0–100)",
                               range=[0, 110],
                               gridcolor="rgba(128,128,128,0.15)"),
                    yaxis=dict(title="DEF — Defensive Rating (0–100)",
                               range=[0, 110],
                               gridcolor="rgba(128,128,128,0.15)"),
                    coloraxis_colorbar=dict(title="PLY"),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=20, r=20, t=50, b=30),
                    font=dict(size=11),
                )
                st.plotly_chart(fig_rad, use_container_width=True)
            else:
                st.info("Need at least 2 qualified players for the scatter chart.")

            # ── League comparison — where does each player rank? ─────────────
            st.divider()
            st.markdown("#### League Percentile Comparison")
            st.caption("Where do this team's players rank compared to the entire league?")

            _league_pcts = {}
            for _rat_col in ["OVRL", "OFF", "DEF", "PLY", "REB_R"]:
                if _rat_col not in _all_ratings.columns:
                    continue
                all_vals = _all_ratings[_rat_col].dropna().sort_values().values
                for _, row in _team_ratings.iterrows():
                    val = row.get(_rat_col, 0)
                    pct = (all_vals < val).sum() / len(all_vals) * 100 if len(all_vals) else 0
                    _league_pcts.setdefault(row["Player"], {})[_rat_col] = round(pct, 1)

            if _league_pcts:
                pct_rows = [{"Player":       p,
                             "OVRL Pctile":  v.get("OVRL",  0),
                             "OFF Pctile":   v.get("OFF",   0),
                             "DEF Pctile":   v.get("DEF",   0),
                             "PLY Pctile":   v.get("PLY",   0),
                             "REB_R Pctile": v.get("REB_R", 0)}
                            for p, v in _league_pcts.items()]
                pct_df = pd.DataFrame(pct_rows)
                _pct_subset = [c for c in ["OVRL Pctile","OFF Pctile","DEF Pctile","PLY Pctile","REB_R Pctile"]
                               if c in pct_df.columns]
                styler = (pct_df.style
                          .background_gradient(subset=_pct_subset,
                                               cmap="RdYlGn", axis=None, vmin=0, vmax=100)
                          .format({c: "{:.1f}%" for c in _pct_subset}))
                st.dataframe(styler, use_container_width=True, hide_index=True)
                st.caption("Percentile = % of all tracked players with a lower score. "
                           "90th pctile = top 10% in the league.")


# ══════════════════════════════════════════════════════════════════════════════
#  LINEUPS
# ══════════════════════════════════════════════════════════════════════════════
with tab_lu:

    # compute_player_ratings / compute_player_rankings are already @st.cache_data
    def _lu_load_ratings():
        return compute_player_ratings()

    def _lu_load_rankings():
        return compute_player_rankings()

    _lu_rat_all = _lu_load_ratings()
    _lu_rnk_all = _lu_load_rankings()

    # ── Filter to selected team, merge in per-game attempt counts ────────────
    if _lu_rat_all.empty or "Team" not in _lu_rat_all.columns:
        st.info("No player rating data yet — track some games to unlock Lineups.")
    else:
        _lu_pool = _lu_rat_all[_lu_rat_all["Team"] == sel_name].copy()

        # Merge FTA / 3PA per game from rankings (needed for threshold filters)
        if not _lu_rnk_all.empty and "pid" in _lu_rnk_all.columns and "pid" in _lu_pool.columns:
            _lu_pool = _lu_pool.merge(
                _lu_rnk_all[["pid","FTA","3PA","FGA","FGM","3PM"]].rename(columns={
                    "FTA":"_fta","3PA":"_3pa","FGA":"_fga","FGM":"_fgm","3PM":"_3pm"}),
                on="pid", how="left",
            )

        # Numeric coerce
        for _c in ["OVRL","OFF","DEF","PLY","REB_R","PTS","AST","REB","OREB","DREB",
                   "STL","BLK","TOV","eFG%","TS%","FT%","3P%","2P%","FG%",
                   "Q4 PPG","Stocks","+/-","EFF","FIC","PRF","PPSA","PPS","FTr","TOV%",
                   "_fta","_3pa","_fga","_fgm","_3pm"]:
            if _c in _lu_pool.columns:
                _lu_pool[_c] = pd.to_numeric(_lu_pool[_c], errors="coerce").fillna(0)

        # Require at least 1 GP
        if "GP" in _lu_pool.columns:
            _lu_pool = _lu_pool[pd.to_numeric(_lu_pool["GP"], errors="coerce").fillna(0) >= 1]

        # OVRL fallback — if the ratings cache pre-dates OVRL, derive it from
        # Game Score (same formula family) so all lineup slots still work.
        if "OVRL" not in _lu_pool.columns or _lu_pool["OVRL"].isna().all():
            if "GS" in _lu_pool.columns:
                _gs = pd.to_numeric(_lu_pool["GS"], errors="coerce").fillna(0)
                _mn, _mx = _gs.min(), _gs.max()
                _lu_pool["OVRL"] = (
                    ((_gs - _mn) / (_mx - _mn) * 100).round(1)
                    if _mx > _mn else pd.Series(50.0, index=_lu_pool.index)
                )
            else:
                _lu_pool["OVRL"] = 50.0

        if len(_lu_pool) < 3:
            st.info("Need at least 3 players with 1+ GP on this team to build lineups.")
        else:
            # ── Core helpers ─────────────────────────────────────────────────
            def _pick_lineup(pool, slots):
                """
                Assign players to slots by largest-margin-first priority.

                For every remaining (slot, candidate pool) pair we compute the
                margin between the best and second-best eligible player for that
                slot's metric.  The slot with the biggest margin is filled first —
                this locks in dominant specialists (e.g. a clear-best rebounder) before a
                shared metric (e.g. OFF) can steal them, so each player ends up in
                the position where they have the greatest relative advantage.
                """
                used   = set()
                filled = {}          # slot_index → card dict
                pending = list(enumerate(slots))   # [(original_idx, slot_def), …]

                def _eligible(s):
                    """Return candidates for slot s, applying min threshold."""
                    metric = s["metric"]
                    if metric not in pool.columns:
                        return pd.DataFrame()
                    cands = pool[~pool.index.isin(used)].copy()
                    if cands.empty:
                        return cands
                    if "min_col" in s and "min_val" in s:
                        mc, mv = s["min_col"], s["min_val"]
                        if mc in cands.columns:
                            filtered = cands[cands[mc] >= mv]
                            if not filtered.empty:
                                cands = filtered
                    return cands

                while pending:
                    best_slot_i  = None
                    best_slot_s  = None
                    best_player  = None
                    best_margin  = -1.0

                    for slot_i, s in pending:
                        cands = _eligible(s)
                        if cands.empty:
                            continue
                        metric = s["metric"]
                        vals = pd.to_numeric(cands[metric], errors="coerce").fillna(0)
                        sorted_vals = vals.sort_values(ascending=False)
                        top_val    = float(sorted_vals.iloc[0])
                        second_val = float(sorted_vals.iloc[1]) if len(sorted_vals) > 1 else 0.0
                        margin     = top_val - second_val
                        if margin > best_margin:
                            best_margin   = margin
                            best_slot_i   = slot_i
                            best_slot_s   = s
                            best_player   = pool.loc[sorted_vals.index[0]]

                    if best_slot_i is None:
                        break   # no eligible candidates remain

                    metric = best_slot_s["metric"]
                    used.add(best_player.name)
                    filled[best_slot_i] = {
                        "role":    best_slot_s["role"],
                        "key_val": float(best_player.get(metric, 0)),
                        "key_lbl": best_slot_s.get("label", metric),
                        "player":  str(best_player.get("Player", "—")),
                        "number":  str(best_player.get("#", "") or ""),
                        "team":    str(best_player.get("Team", "—")),
                        "pts":     float(best_player.get("PTS", 0)),
                        "reb":     float(best_player.get("REB", 0)),
                        "ast":     float(best_player.get("AST", 0)),
                        "ovrl":    (float(best_player["OVRL"])
                                    if "OVRL" in best_player.index
                                    and pd.notna(best_player.get("OVRL"))
                                    else None),
                    }
                    pending = [(i, sl) for i, sl in pending if i != best_slot_i]

                # Return cards in the original slot order
                return [filled[i] for i in sorted(filled.keys())]

            def _render_lineup(lineup, accent="#f0a500"):
                if not lineup:
                    st.info("Not enough qualified players to fill this lineup.")
                    return
                cols = st.columns(len(lineup))
                for i, p in enumerate(lineup):
                    with cols[i]:
                        ovrl_line = (f'<div class="lu-ovrl">OVRL {p["ovrl"]:.1f}</div>'
                                     if p["ovrl"] is not None else "")
                        st.markdown(f"""
                        <div class="lu-card">
                            <div class="lu-slot" style="color:{accent}">{p['role']}</div>
                            <div class="lu-num">#{p['number']}</div>
                            <div class="lu-name">{p['player']}</div>
                            <div class="lu-tm">{p['team']}</div>
                            <div class="lu-val" style="color:{accent}">{p['key_val']:.1f}</div>
                            <div class="lu-lbl">{p['key_lbl']}</div>
                            {ovrl_line}
                            <div class="lu-line">
                                {p['pts']:.1f} PTS · {p['reb']:.1f} REB · {p['ast']:.1f} AST
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

            # ── Unavailable players (fouled out / injured / sitting) ──────────
            # Build label → index map before expander so the multiselect always
            # renders against the full (pre-removal) roster.
            _avail_opts = {}
            for _ai, _ar in _lu_pool.iterrows():
                _al = f"#{_ar.get('#', '?')} {_ar.get('Player', 'Unknown')}"
                _avail_opts[_al] = _ai

            with st.expander("🚫 Mark players as unavailable (foul out, injury, DNP…)", expanded=False):
                _unavail_picked = st.multiselect(
                    "Select unavailable players",
                    options=list(_avail_opts.keys()),
                    placeholder="No players removed — select to exclude from all lineups",
                    key="lu_unavail",
                )

            # Apply exclusions OUTSIDE the expander so they always take effect
            if _unavail_picked:
                _unavail_idx = [_avail_opts[lbl] for lbl in _unavail_picked]
                _lu_pool = _lu_pool[~_lu_pool.index.isin(_unavail_idx)].copy()
                st.warning(
                    f"⚠️ {len(_unavail_picked)} player(s) removed from all lineups: "
                    + ", ".join(_unavail_picked)
                )
                if len(_lu_pool) < 3:
                    st.info("Not enough available players to build lineups — unmark some players above.")
                    _lu_pool = pd.DataFrame()   # signal tabs to show empty state

            # ── Sub-tabs ──────────────────────────────────────────────────────
            lu_best, lu_off, lu_def, lu_ft, lu_3pt, lu_clutch, lu_custom = st.tabs([
                "🏆 Best Overall",
                "⚔️ Offense",
                "🛡️ Defense",
                "🎯 Free Throw",
                "🔥 3-Point",
                "⏰ Clutch",
                "🛠️ Custom",
            ])

            # ─── Best Overall ─────────────────────────────────────────────────
            with lu_best:
                st.caption(
                    "Optimal 5-man unit using composite ratings. "
                    "Fills by PLY → OFF → OFF → REB, then best remaining OVRL."
                )
                _slots_best = [
                    {"role":"🎯 Playmaker",  "metric":"PLY",   "label":"PLY"},
                    {"role":"🏀 Wing 1",     "metric":"OFF",   "label":"OFF"},
                    {"role":"🏀 Wing 2",     "metric":"OFF",   "label":"OFF"},
                    {"role":"🏋️ Interior",   "metric":"REB_R", "label":"REB"},
                    {"role":"👑 X-Factor",   "metric":"OVRL",  "label":"OVRL"},
                ]
                _render_lineup(_pick_lineup(_lu_pool, _slots_best), accent="#f0a500")

                # OVRL bar for the team
                st.markdown("---")
                st.caption(f"All qualified {sel_name} players by OVRL")
                if "OVRL" in _lu_pool.columns and not _lu_pool.empty:
                    _ov_team = _lu_pool.sort_values("OVRL", ascending=True).copy()
                    _ov_team["_lbl"] = _ov_team.apply(
                        lambda r: f"#{r['#']} {r['Player']}", axis=1)
                    fig_ov_t = go.Figure(go.Bar(
                        x=_ov_team["OVRL"], y=_ov_team["_lbl"],
                        orientation="h", marker_color="#f0a500",
                        text=[f"{v:.1f}" for v in _ov_team["OVRL"]],
                        textposition="outside",
                    ))
                    fig_ov_t.update_layout(
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        font_color="#c9d1d9", margin=dict(l=10,r=10,t=20,b=10),
                        xaxis=dict(range=[0,108], showgrid=False),
                        yaxis=dict(tickfont=dict(size=11)),
                        height=max(260, len(_ov_team)*40),
                    )
                    st.plotly_chart(fig_ov_t, use_container_width=True, key="lu_ovrl_bar")

            # ─── Offense ──────────────────────────────────────────────────────
            with lu_off:
                st.caption(
                    "Best offensive 5: primary scorer → playmaker/creator → "
                    "efficient shooter (min 2 FGA/g) → offensive rebounder → paint finisher."
                )
                _slots_off = [
                    {"role":"⚡ Primary Scorer",  "metric":"OFF",   "label":"OFF"},
                    {"role":"🎯 Creator",          "metric":"PLY",   "label":"PLY"},
                    {"role":"📈 Efficient Shooter","metric":"eFG%",  "label":"eFG%",
                     "min_col":"_fga", "min_val":2.0},
                    {"role":"🏃 Off-Glass",        "metric":"OREB",  "label":"OREB/G"},
                    {"role":"🔴 Paint Finisher",   "metric":"REB_R", "label":"REB"},
                ]
                _render_lineup(_pick_lineup(_lu_pool, _slots_off), accent="#e67e22")

                # Scoring breakdown bar
                st.markdown("---")
                st.caption("Points per game — all qualified players")
                _pts_t = _lu_pool.sort_values("PTS", ascending=True).copy()
                _pts_t["_lbl"] = _pts_t.apply(lambda r: f"#{r['#']} {r['Player']}", axis=1)
                fig_pts = go.Figure(go.Bar(
                    x=_pts_t["PTS"], y=_pts_t["_lbl"], orientation="h",
                    marker_color="#e67e22",
                    text=[f"{v:.1f}" for v in _pts_t["PTS"]], textposition="outside",
                ))
                fig_pts.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    font_color="#c9d1d9", margin=dict(l=10,r=10,t=20,b=10),
                    xaxis=dict(showgrid=False), height=max(260, len(_pts_t)*40),
                )
                st.plotly_chart(fig_pts, use_container_width=True, key="lu_pts_bar")

            # ─── Defense ──────────────────────────────────────────────────────
            with lu_def:
                st.caption(
                    "Best defensive 5: ball hawk (STL) → shot blocker (BLK) → "
                    "two glass cleaners (DREB) → best remaining disruptor (Stocks)."
                )
                _slots_def = [
                    {"role":"🦅 Ball Hawk",     "metric":"STL",    "label":"STL/G"},
                    {"role":"🧱 Shot Blocker",  "metric":"BLK",    "label":"BLK/G"},
                    {"role":"💪 Glass 1",       "metric":"DREB",   "label":"DREB/G"},
                    {"role":"💪 Glass 2",       "metric":"DREB",   "label":"DREB/G"},
                    {"role":"🔀 Disruptor",     "metric":"Stocks", "label":"Stocks/G"},
                ]
                _render_lineup(_pick_lineup(_lu_pool, _slots_def), accent="#58a6ff")

                # Defensive stats table
                st.markdown("---")
                st.caption("Defensive stats — all qualified players")
                _def_t = _lu_pool.sort_values("Stocks", ascending=False).copy()
                _def_t["_lbl"] = _def_t.apply(lambda r: f"#{r['#']} {r['Player']}", axis=1)
                _def_cols = [c for c in ["_lbl","STL","BLK","Stocks","DREB","TOV"]
                             if c in _def_t.columns]
                st.dataframe(
                    _def_t[_def_cols].rename(columns={"_lbl":"Player"}),
                    use_container_width=True, hide_index=True,
                )

            # ─── Free Throw ───────────────────────────────────────────────────
            with lu_ft:
                st.caption(
                    "Best free throw lineup — who you want on the floor when the game is on the line. "
                    "Ranked by FT% with minimum 1 FTA per game."
                )
                _slots_ft = [
                    {"role":"🎯 FT Shooter 1", "metric":"FT%", "label":"FT%",
                     "min_col":"_fta", "min_val":1.0},
                    {"role":"🎯 FT Shooter 2", "metric":"FT%", "label":"FT%",
                     "min_col":"_fta", "min_val":1.0},
                    {"role":"🎯 FT Shooter 3", "metric":"FT%", "label":"FT%",
                     "min_col":"_fta", "min_val":1.0},
                    {"role":"🎯 FT Shooter 4", "metric":"FT%", "label":"FT%",
                     "min_col":"_fta", "min_val":1.0},
                    {"role":"🎯 FT Shooter 5", "metric":"FT%", "label":"FT%",
                     "min_col":"_fta", "min_val":1.0},
                ]
                _render_lineup(_pick_lineup(_lu_pool, _slots_ft), accent="#2ecc71")

                # FT% bar
                st.markdown("---")
                _ft_t = (_lu_pool[_lu_pool.get("_fta", pd.Series(0, index=_lu_pool.index)) >= 0.5]
                         .sort_values("FT%", ascending=True).copy()
                         if "_fta" in _lu_pool.columns
                         else _lu_pool.sort_values("FT%", ascending=True).copy())
                _ft_t["_lbl"] = _ft_t.apply(lambda r: f"#{r['#']} {r['Player']}", axis=1)
                if not _ft_t.empty:
                    fig_ft = go.Figure(go.Bar(
                        x=_ft_t["FT%"], y=_ft_t["_lbl"], orientation="h",
                        marker_color="#2ecc71",
                        text=[f"{v:.1f}%" for v in _ft_t["FT%"]], textposition="outside",
                    ))
                    fig_ft.update_layout(
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        font_color="#c9d1d9", margin=dict(l=10,r=10,t=20,b=10),
                        xaxis=dict(range=[0,115], showgrid=False),
                        height=max(260, len(_ft_t)*40),
                    )
                    st.plotly_chart(fig_ft, use_container_width=True, key="lu_ft_bar")

            # ─── 3-Point ──────────────────────────────────────────────────────
            with lu_3pt:
                st.caption(
                    "Best 3-point shooting lineup — for zone busting or comeback situations. "
                    "Ranked by 3P% with minimum 1 three attempted per game."
                )
                _slots_3pt = [
                    {"role":"🔥 Shooter 1", "metric":"3P%", "label":"3P%",
                     "min_col":"_3pa", "min_val":1.0},
                    {"role":"🔥 Shooter 2", "metric":"3P%", "label":"3P%",
                     "min_col":"_3pa", "min_val":1.0},
                    {"role":"🔥 Shooter 3", "metric":"3P%", "label":"3P%",
                     "min_col":"_3pa", "min_val":1.0},
                    {"role":"🔥 Shooter 4", "metric":"3P%", "label":"3P%",
                     "min_col":"_3pa", "min_val":1.0},
                    {"role":"🔥 Shooter 5", "metric":"3P%", "label":"3P%",
                     "min_col":"_3pa", "min_val":1.0},
                ]
                _render_lineup(_pick_lineup(_lu_pool, _slots_3pt), accent="#9b59b6")

                # 3P% bar
                st.markdown("---")
                _tp_t = (_lu_pool[_lu_pool["_3pa"] >= 0.5].sort_values("3P%", ascending=True).copy()
                         if "_3pa" in _lu_pool.columns
                         else _lu_pool.sort_values("3P%", ascending=True).copy())
                _tp_t["_lbl"] = _tp_t.apply(lambda r: f"#{r['#']} {r['Player']}", axis=1)
                if not _tp_t.empty:
                    fig_3p = go.Figure(go.Bar(
                        x=_tp_t["3P%"], y=_tp_t["_lbl"], orientation="h",
                        marker_color="#9b59b6",
                        text=[f"{v:.1f}%" for v in _tp_t["3P%"]], textposition="outside",
                    ))
                    fig_3p.update_layout(
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        font_color="#c9d1d9", margin=dict(l=10,r=10,t=20,b=10),
                        xaxis=dict(range=[0,115], showgrid=False),
                        height=max(260, len(_tp_t)*40),
                    )
                    st.plotly_chart(fig_3p, use_container_width=True, key="lu_3pt_bar")

            # ─── Clutch ───────────────────────────────────────────────────────
            with lu_clutch:
                st.caption(
                    "Best 4th-quarter lineup — ranked by Q4 PPG. "
                    "These are the players you want on the floor when it matters most."
                )
                _slots_cl = [
                    {"role":"⏰ Clutch 1", "metric":"Q4 PPG", "label":"Q4 PPG"},
                    {"role":"⏰ Clutch 2", "metric":"Q4 PPG", "label":"Q4 PPG"},
                    {"role":"⏰ Clutch 3", "metric":"Q4 PPG", "label":"Q4 PPG"},
                    {"role":"⏰ Clutch 4", "metric":"Q4 PPG", "label":"Q4 PPG"},
                    {"role":"⏰ Clutch 5", "metric":"Q4 PPG", "label":"Q4 PPG"},
                ]
                _render_lineup(_pick_lineup(_lu_pool, _slots_cl), accent="#e74c3c")

                # Q4 PPG bar
                st.markdown("---")
                _q4_t = _lu_pool.sort_values("Q4 PPG", ascending=True).copy()
                _q4_t["_lbl"] = _q4_t.apply(lambda r: f"#{r['#']} {r['Player']}", axis=1)
                if "Q4 PPG" in _q4_t.columns and not _q4_t.empty:
                    fig_q4 = go.Figure(go.Bar(
                        x=_q4_t["Q4 PPG"], y=_q4_t["_lbl"], orientation="h",
                        marker_color="#e74c3c",
                        text=[f"{v:.1f}" for v in _q4_t["Q4 PPG"]], textposition="outside",
                    ))
                    fig_q4.update_layout(
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        font_color="#c9d1d9", margin=dict(l=10,r=10,t=20,b=10),
                        xaxis=dict(showgrid=False),
                        height=max(260, len(_q4_t)*40),
                    )
                    st.plotly_chart(fig_q4, use_container_width=True, key="lu_q4_bar")

            # ─── Custom Lineup ────────────────────────────────────────────────
            with lu_custom:
                st.caption(
                    "Build your own 5-man lineup and see projected pace, ORat, DRat, "
                    "and net rating based on individual player stats."
                )

                # Build display labels → df-index map (handle duplicate names)
                _clu_name_map = {}
                for _idx, _crow in _lu_pool.iterrows():
                    _lbl = f"#{_crow.get('#', '?')} {_crow.get('Player', 'Unknown')}"
                    # If duplicate label (same number+name on two rows), append OVRL
                    if _lbl in _clu_name_map:
                        _lbl = f"{_lbl} (OVRL {_crow.get('OVRL', '?')})"
                    _clu_name_map[_lbl] = _idx

                _clu_picked = st.multiselect(
                    "Choose exactly 5 players",
                    options=list(_clu_name_map.keys()),
                    max_selections=5,
                    placeholder="Search and select players…",
                    key="lu_custom_pick",
                )

                if len(_clu_picked) == 0:
                    st.info("Select 5 players above to build a custom lineup.")
                elif len(_clu_picked) < 5:
                    st.info(f"Select {5 - len(_clu_picked)} more player(s) to complete the lineup.")
                else:
                    # Sub-pool for selected 5
                    _clu_idx  = [_clu_name_map[lbl] for lbl in _clu_picked]
                    _clu_pool = _lu_pool.loc[_clu_idx].copy()

                    # Assign positional roles using same largest-margin algorithm
                    _slots_clu = [
                        {"role": "⚡ Scorer",     "metric": "OFF",   "label": "OFF"},
                        {"role": "🎯 Playmaker",  "metric": "PLY",   "label": "PLY"},
                        {"role": "🛡️ Defender",   "metric": "DEF",   "label": "DEF"},
                        {"role": "📦 Rebounder",  "metric": "REB_R", "label": "REB_R"},
                        {"role": "👑 X-Factor",   "metric": "OVRL",  "label": "OVRL"},
                    ]
                    _clu_cards = _pick_lineup(_clu_pool, _slots_clu)
                    _render_lineup(_clu_cards, accent="#1abc9c")

                    st.markdown("---")

                    # ── Pull team pace / DRat baseline ────────────────────────
                    _clu_adv = compute_team_tracked(team_id)
                    _tm_pace = _clu_adv.get("pace", 70.0)  if _clu_adv else 70.0
                    _tm_drtg = _clu_adv.get("drtg", 100.0) if _clu_adv else 100.0

                    # ── Projected offensive stats (sum of per-game avgs) ──────
                    _clu_pts  = float(_clu_pool["PTS"].sum())
                    _clu_reb  = float(_clu_pool["REB"].sum())
                    _clu_ast  = float(_clu_pool["AST"].sum())
                    _clu_stl  = float(_clu_pool["STL"].sum())
                    _clu_blk  = float(_clu_pool["BLK"].sum())
                    _clu_tov  = float(_clu_pool["TOV"].sum())
                    _clu_stk  = _clu_stl + _clu_blk

                    # Weighted eFG%: (FGM + 0.5·3PM) / FGA — use merged columns
                    _clu_fga = float(_clu_pool["_fga"].sum()) if "_fga" in _clu_pool.columns else 0.0
                    _clu_fgm = float(_clu_pool["_fgm"].sum()) if "_fgm" in _clu_pool.columns else 0.0
                    _clu_3pm = float(_clu_pool["_3pm"].sum()) if "_3pm" in _clu_pool.columns else 0.0
                    _clu_efg = round((_clu_fgm + 0.5 * _clu_3pm) / _clu_fga * 100, 1) if _clu_fga else 0.0

                    # Avg +/-
                    _clu_pm  = float(_clu_pool["+/-"].mean()) if "+/-" in _clu_pool.columns else 0.0

                    # ── ORat estimate ─────────────────────────────────────────
                    # Projected pts / pace × 100  (mirrors the team ortg formula)
                    _clu_ortg = round((_clu_pts / max(_tm_pace, 0.1)) * 100, 1)

                    # ── DRat estimate ─────────────────────────────────────────
                    # Baseline = team DRat; adjust for lineup defensive strength
                    # vs. team average: each +1 Stocks/G above team avg ≈ −1.5 DRat
                    _tm_avg_stk  = float(_lu_pool["Stocks"].mean()) if "Stocks" in _lu_pool.columns else 0.0
                    _clu_avg_stk = float(_clu_pool["Stocks"].mean()) if "Stocks" in _clu_pool.columns else 0.0
                    _tm_avg_def  = float(_lu_pool["DEF"].mean()) if "DEF" in _lu_pool.columns else 50.0
                    _clu_avg_def = float(_clu_pool["DEF"].mean()) if "DEF" in _clu_pool.columns else 50.0
                    # Stocks delta → ~1.5 DRat each; DEF rating delta → ~0.3 DRat per point
                    _def_adj = (_clu_avg_stk - _tm_avg_stk) * 1.5 + \
                               (_clu_avg_def - _tm_avg_def) * 0.3
                    _clu_drtg = round(_tm_drtg - _def_adj, 1)
                    _clu_net  = round(_clu_ortg - _clu_drtg, 1)

                    # ── Rating metrics row ────────────────────────────────────
                    st.subheader("Projected Lineup Ratings")
                    _m1, _m2, _m3, _m4, _m5 = st.columns(5)
                    _m1.metric("Pace",    f"{_tm_pace:.1f}",  help="Team's tracked possessions per game")
                    _m2.metric("ORat",    f"{_clu_ortg:.1f}", help="Projected pts / pace × 100")
                    _m3.metric("DRat",    f"{_clu_drtg:.1f}", help="Team DRat adjusted for lineup defensive profile")
                    _m4.metric("Net Rtg", f"{_clu_net:+.1f}", help="ORat − DRat")
                    _m5.metric("Avg +/-", f"{_clu_pm:+.1f}",  help="Average on/off per player")
                    st.caption(
                        "ORat = projected pts ÷ pace × 100  ·  "
                        "DRat = team baseline adjusted by lineup Stocks & Wing Rating vs. team avg  ·  "
                        "All figures are estimates based on individual per-game averages."
                    )

                    # ── Projected box ─────────────────────────────────────────
                    st.markdown("**Projected Lineup Totals (per game)**")
                    _clu_box_df = pd.DataFrame([{
                        "PTS":    round(_clu_pts,  1),
                        "REB":    round(_clu_reb,  1),
                        "AST":    round(_clu_ast,  1),
                        "STL":    round(_clu_stl,  1),
                        "BLK":    round(_clu_blk,  1),
                        "TOV":    round(_clu_tov,  1),
                        "Stocks": round(_clu_stk,  1),
                        "eFG%":   f"{_clu_efg:.1f}%",
                        "Avg OVRL": round(float(_clu_pool["OVRL"].mean()), 1),
                    }])
                    st.dataframe(_clu_box_df, hide_index=True, use_container_width=True)

                    # ── Individual breakdown table ─────────────────────────────
                    st.markdown("**Individual Player Breakdown**")
                    _show_cols = [c for c in
                        ["Player","#","OVRL","OFF","DEF","PLY","REB_R","PTS","REB","AST",
                         "STL","BLK","TOV","Stocks","eFG%","+/-"]
                        if c in _clu_pool.columns]
                    st.dataframe(
                        _clu_pool[_show_cols].reset_index(drop=True),
                        hide_index=True, use_container_width=True,
                    )


# ══════════════════════════════════════════════════════════════════════════════
#  GAMES
# ══════════════════════════════════════════════════════════════════════════════
with tab_gm:
    all_gs = games_for_team(team_id)
    if not all_gs:
        st.info("No games with scores yet.")
    else:
        # Build log (all_gs already newest→oldest)
        log=[]
        for g in all_gs:
            res,my,opp=win_loss(g,team_id)
            log.append({"Date":g["date"],"Opponent":opponent_name(g,team_id),
                        "H/A":home_away(g,team_id),"Result":res,
                        "Tm":my,"Opp":opp,"Margin":my-opp,"Tracked":"✓" if g["tracked"] else ""})

        # Table: newest first
        st.dataframe(pd.DataFrame(log), use_container_width=True, hide_index=True)

        # Scoring trend: sort ascending for chart x-axis
        st.subheader("Scoring Trend")
        _adv_gm = compute_team_tracked(team_id)
        if _adv_gm and _adv_gm.get("game_log"):
            show_trend_chart(_adv_gm["game_log"], sel_name)
        else:
            # Fallback — simple score chart for untracked games
            trend_df = pd.DataFrame(log)[["Date","Tm","Opp"]].copy()
            trend_df["Date"] = pd.to_datetime(trend_df["Date"], format="mixed", errors="coerce")
            trend_df = trend_df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")
            st.line_chart(trend_df, color=["#2ecc71","#e74c3c"])

        # ── Shot Creation Trend (tracked games only) ──────────────────────────
        tr_gs = [g for g in all_gs if g["tracked"]]
        if tr_gs:
            _sc_gids = [g["id"] for g in tr_gs]
            _sc_ph   = ",".join("?" * len(_sc_gids))
            _sc_rows = query(f"""
                SELECT g.id, g.date,
                       SUM(CASE WHEN e.pass_from_id IS NOT NULL THEN 1 ELSE 0 END) AS ast_fga,
                       SUM(CASE WHEN e.pass_from_id IS NULL     THEN 1 ELSE 0 END) AS unast_fga
                FROM game_events e
                JOIN games g   ON g.id  = e.game_id
                JOIN players p ON p.id  = e.primary_player_id
                WHERE e.game_id IN ({_sc_ph})
                  AND e.event_type = 'shot'
                  AND p.team_id = ?
                GROUP BY g.id, g.date
            """, (*_sc_gids, team_id))

            if _sc_rows:
                _sc_df = pd.DataFrame(_sc_rows)
                # Sort chronologically — date stored as text so SQL ORDER BY is wrong
                _sc_df["_dt"] = pd.to_datetime(_sc_df["date"], format="mixed", errors="coerce")
                _sc_df = _sc_df.sort_values("_dt").drop(columns=["_dt"])

                # Score margin per game (green = win, red = loss)
                _gid_to_margin = {}
                _gid_to_label  = {}
                for _g in tr_gs:
                    _, _my, _op = win_loss(_g, team_id)
                    _gid_to_margin[_g["id"]] = _my - _op
                    _gid_to_label[_g["id"]]  = f"{opponent_name(_g, team_id)}\n{_g['date']}"
                _sc_df["margin"] = _sc_df["id"].map(_gid_to_margin)
                _sc_df["label"]  = _sc_df["id"].map(_gid_to_label).fillna(_sc_df["date"])

                st.subheader("Shot Creation Trend")
                _fig_sc_trend = go.Figure()

                # Background margin bars (secondary y-axis)
                _bar_colors = ["#1a9850" if m >= 0 else "#d73027"
                               for m in _sc_df["margin"]]
                _fig_sc_trend.add_trace(go.Bar(
                    x=_sc_df["label"],
                    y=_sc_df["margin"],
                    name="Score Margin",
                    marker_color=_bar_colors,
                    opacity=0.4,
                    hovertemplate="%{x}<br>Margin: %{y:+.0f}<extra></extra>",
                    yaxis="y2",
                ))

                # Self-created shots line
                _fig_sc_trend.add_trace(go.Scatter(
                    x=_sc_df["label"],
                    y=_sc_df["unast_fga"],
                    mode="lines+markers",
                    name="Self-Created FGA",
                    line=dict(color="#f0a500", width=2),
                    marker=dict(size=7, color="#f0a500"),
                    hovertemplate="%{x}<br>Self-Created: %{y}<extra></extra>",
                ))

                # Shots off pass line
                _fig_sc_trend.add_trace(go.Scatter(
                    x=_sc_df["label"],
                    y=_sc_df["ast_fga"],
                    mode="lines+markers",
                    name="Shots Off Pass FGA",
                    line=dict(color="#58a6ff", width=2),
                    marker=dict(size=7, color="#58a6ff"),
                    hovertemplate="%{x}<br>Off Pass: %{y}<extra></extra>",
                ))

                _fig_sc_trend.update_layout(
                    title=f"{sel_name} — Shot Creation by Game",
                    xaxis=dict(tickangle=-35, tickfont=dict(size=9), showgrid=False),
                    yaxis=dict(title="Shot Attempts (FGA)",
                               range=[0, 65],
                               gridcolor="rgba(128,128,128,0.15)"),
                    yaxis2=dict(title="Score Margin", overlaying="y", side="right",
                                zeroline=True, zerolinecolor="rgba(200,200,200,0.4)",
                                showgrid=False),
                    height=400,
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=20, r=40, t=60, b=100),
                    legend=dict(orientation="h", y=1.06),
                    font=dict(size=11, color="#c9d1d9"),
                )
                st.plotly_chart(_fig_sc_trend, use_container_width=True,
                                key="sc_trend_games")
                st.caption(
                    "🟡 Self-Created = attempts with no pass credited  ·  "
                    "🔵 Off Pass = attempts assisted by a teammate  ·  "
                    "Bars = score margin (🟢 win / 🔴 loss)  ·  Tracked games only"
                )

        # Tracked game box scores (newest first — all_gs already sorted that way)
        if tr_gs:
            st.subheader("Tracked Game Box Scores")
            for g in tr_gs:
                res,my,opp_sc=win_loss(g,team_id)
                opp_nm=opponent_name(g,team_id)
                lbl=f"{g['date']}  ·  {res}  {my}-{opp_sc}  vs {opp_nm}"
                with st.expander(lbl):
                    t1id=g["team1_id"]; t2id=g["team2_id"]
                    t1nm=g["t1_name"]; t2nm=g["t2_name"]

                    # ── Load all data once ───────────────────────────────────
                    all_gp = query(
                        "SELECT id AS pid, name AS pname, team_id FROM players "
                        "WHERE team_id IN (?,?) AND archived=0 ORDER BY name",
                        (t1id, t2id))
                    if not all_gp:
                        st.info("No players on roster.")
                        continue

                    def _blank_p():
                        return dict(pts=0,ast=0,oreb=0,dreb=0,stl=0,blk=0,tov=0,
                                    fgm=0,fga=0,tpm=0,tpa=0,ftm=0,fta=0,sc=0,pf=0)
                    stats_g = {p["pid"]: {**_blank_p(), "name": p["pname"], "team_id": p["team_id"]}
                               for p in all_gp}
                    player_team_id = {p["pid"]: p["team_id"] for p in all_gp}

                    mins_rows_g = query("""
                        SELECT gel.player_id, SUM(ge.possession_secs) AS secs
                        FROM game_event_lineup gel
                        JOIN game_events ge ON ge.id = gel.event_id
                        WHERE ge.game_id = ? AND ge.possession_secs > 0
                        GROUP BY gel.player_id
                    """, (g["id"],))
                    player_mins_g = {r["player_id"]: r["secs"] or 0.0 for r in mins_rows_g}

                    pm_rows_g = query("SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?", (g["id"],))
                    stored_pm_g = {r["player_id"]: r["plus_minus"] for r in pm_rows_g}

                    events_g = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (g["id"],))
                    t1p = t2p = 0
                    for ev in events_g:
                        prim = ev["primary_player_id"]
                        et   = ev["event_type"]
                        if et == "shot":
                            sh = prim
                            if sh and sh in stats_g:
                                stats_g[sh]["fga"] += 1; stats_g[sh]["sc"] += 1
                                if ev["shot_type"] == 3: stats_g[sh]["tpa"] += 1
                                if ev["shot_result"] == "make":
                                    pts_ = ev["shot_type"]; stats_g[sh]["fgm"] += 1; stats_g[sh]["pts"] += pts_
                                    if ev["shot_type"] == 3: stats_g[sh]["tpm"] += 1
                                    if stats_g[sh]["team_id"] == t1id: t1p += pts_
                                    else: t2p += pts_
                                    if ev["pass_from_id"] and ev["pass_from_id"] in stats_g:
                                        stats_g[ev["pass_from_id"]]["ast"] += 1
                            for _col, _key in [("pass_from_id","sc"),("shot_created_by_id","sc"),("blocked_by_id","blk")]:
                                _pid2 = ev[_col]
                                if _pid2 and _pid2 in stats_g: stats_g[_pid2][_key] += 1
                            reb = ev["rebound_by_id"]
                            if reb and reb in stats_g and prim and prim in stats_g:
                                stats_g[reb]["oreb" if player_team_id.get(prim)==player_team_id.get(reb) else "dreb"] += 1
                        elif et == "free_throw":
                            sh = prim
                            if sh and sh in stats_g:
                                stats_g[sh]["fta"] += 1
                                if ev["shot_result"] == "make":
                                    stats_g[sh]["ftm"] += 1; stats_g[sh]["pts"] += 1
                                    if stats_g[sh]["team_id"] == t1id: t1p += 1
                                    else: t2p += 1
                            reb = ev["rebound_by_id"]
                            if reb and reb in stats_g and prim and prim in stats_g:
                                stats_g[reb]["oreb" if player_team_id.get(prim)==player_team_id.get(reb) else "dreb"] += 1
                        elif et == "foul":
                            f2 = ev["secondary_player_id"]
                            if f2 and f2 in stats_g: stats_g[f2]["pf"] += 1
                        elif et == "turnover":
                            if prim and prim in stats_g: stats_g[prim]["tov"] += 1
                            s2 = ev["stolen_by_id"]
                            if s2 and s2 in stats_g: stats_g[s2]["stl"] += 1

                    # ── Quarter scores (above tabs) ──────────────────────────
                    def _ql(qq): return f"Q{qq}" if qq <= 4 else f"OT{qq-4}"
                    q_sc = {}
                    for ev2 in events_g:
                        if ev2["event_type"] in ("shot","free_throw") and ev2["shot_result"] == "make":
                            qq = ev2["quarter"]
                            if qq not in q_sc: q_sc[qq] = {t1id: 0, t2id: 0}
                            pts_q = ev2["shot_type"] if ev2["event_type"] == "shot" else 1
                            s_tid = player_team_id.get(ev2["primary_player_id"])
                            if s_tid in q_sc[qq]: q_sc[qq][s_tid] += pts_q
                    if q_sc:
                        r1g = {"Team": t1nm}; r2g = {"Team": t2nm}
                        tot1g = tot2g = 0
                        for qq in sorted(q_sc.keys()):
                            r1g[_ql(qq)] = q_sc[qq].get(t1id, 0)
                            r2g[_ql(qq)] = q_sc[qq].get(t2id, 0)
                            tot1g += q_sc[qq].get(t1id, 0)
                            tot2g += q_sc[qq].get(t2id, 0)
                        r1g["Total"] = tot1g; r2g["Total"] = tot2g
                        st.dataframe(pd.DataFrame([r1g, r2g]), hide_index=True, use_container_width=True)

                    # ── Quarter PPP (above tabs) ─────────────────────────────
                    qp_g = {}
                    for ev2 in events_g:
                        pid2_ = ev2["primary_player_id"]
                        if not pid2_: continue
                        tid2_ = player_team_id.get(pid2_)
                        if tid2_ not in (t1id, t2id): continue
                        qq2 = ev2["quarter"]
                        if qq2 not in qp_g:
                            qp_g[qq2] = {t1id: {"poss":0,"pts":0}, t2id: {"poss":0,"pts":0}}
                        if ev2["event_type"] in ("shot","turnover"):
                            qp_g[qq2][tid2_]["poss"] += 1
                        if ev2["event_type"] == "shot" and ev2["shot_result"] == "make":
                            qp_g[qq2][tid2_]["pts"] += ev2["shot_type"] or 0
                        elif ev2["event_type"] == "free_throw" and ev2["shot_result"] == "make":
                            qp_g[qq2][tid2_]["pts"] += 1
                    if qp_g:
                        qp_r1 = {"Team": t1nm}; qp_r2 = {"Team": t2nm}
                        t1_tp = t2_tp = t1_tpts = t2_tpts = 0
                        for qq2 in sorted(qp_g.keys()):
                            lbl2 = _ql(qq2)
                            d1 = qp_g[qq2].get(t1id, {"poss":0,"pts":0})
                            d2 = qp_g[qq2].get(t2id, {"poss":0,"pts":0})
                            qp_r1[f"{lbl2} Poss"] = d1["poss"]
                            qp_r1[f"{lbl2} PPP"]  = round(d1["pts"]/d1["poss"],3) if d1["poss"] else "—"
                            qp_r2[f"{lbl2} Poss"] = d2["poss"]
                            qp_r2[f"{lbl2} PPP"]  = round(d2["pts"]/d2["poss"],3) if d2["poss"] else "—"
                            t1_tp += d1["poss"]; t1_tpts += d1["pts"]
                            t2_tp += d2["poss"]; t2_tpts += d2["pts"]
                        qp_r1["Total Poss"] = t1_tp
                        qp_r1["Total PPP"]  = round(t1_tpts/t1_tp,3) if t1_tp else "—"
                        qp_r2["Total Poss"] = t2_tp
                        qp_r2["Total PPP"]  = round(t2_tpts/t2_tp,3) if t2_tp else "—"
                        st.caption("Possessions per Quarter · PPP = points per possession")
                        st.dataframe(pd.DataFrame([qp_r1, qp_r2]), hide_index=True, use_container_width=True)

                    # ── Score flow chart ─────────────────────────────────────
                    show_score_flow_chart(g["id"], t1nm, t2nm, t1id, t2id,
                                         key=f"flow_ta_{g['id']}")

                    # ── Four tabs ────────────────────────────────────────────
                    gtab_box, gtab_ts, gtab_off, gtab_hz = st.tabs(
                        ["Box Score", "Team Stats", "Officials", "Hot Zones"])

                    # ── Box Score ────────────────────────────────────────────
                    with gtab_box:
                        _bx_rows_t1, _bx_rows_t2, _bx_gi = compute_game_box_score(g["id"])
                        _bx_q = compute_game_quarter_scores(g["id"])
                        show_game_box_score(_bx_rows_t1, _bx_rows_t2, _bx_q, _bx_gi, _cfg)

                        # CSV export — build flat DataFrame from the computed rows
                        _exp_cols = ["Team","Player","MIN","PTS","REB","AST","STL","BLK",
                                     "TOV","PF","FGM","FGA","3PM","3PA","FTM","FTA",
                                     "eFG%","TS%","GmSc","+/-"]
                        _exp_rows = []
                        for _r, _tnm in [(_bx_rows_t1, t1nm), (_bx_rows_t2, t2nm)]:
                            for _p in _r:
                                if _p.get("_totals"):
                                    continue
                                _min_v = _p.get("MIN", 0)
                                _exp_rows.append({
                                    "Team":   _tnm,
                                    "Player": _p["Player"],
                                    "MIN":    f"{_min_v:.1f}" if isinstance(_min_v, float) else _min_v,
                                    "PTS":    _p.get("PTS", 0),
                                    "REB":    _p.get("REB", 0),
                                    "AST":    _p.get("AST", 0),
                                    "STL":    _p.get("STL", 0),
                                    "BLK":    _p.get("BLK", 0),
                                    "TOV":    _p.get("TOV", 0),
                                    "PF":     _p.get("PF", 0),
                                    "FGM":    _p.get("FGM", 0),
                                    "FGA":    _p.get("FGA", 0),
                                    "3PM":    _p.get("3PM", 0),
                                    "3PA":    _p.get("3PA", 0),
                                    "FTM":    _p.get("FTM", 0),
                                    "FTA":    _p.get("FTA", 0),
                                    "eFG%":   f"{_p['eFG%']:.1f}%" if _p.get("eFG%") is not None else "—",
                                    "TS%":    f"{_p['TS%']:.1f}%"  if _p.get("TS%")  is not None else "—",
                                    "GmSc":   _p.get("GmSc", "—"),
                                    "+/-":    _p.get("+/-", 0),
                                })
                        if _exp_rows:
                            _exp_df = pd.DataFrame(_exp_rows)[_exp_cols]
                            st.download_button(
                                "⬇ Export Box Score (CSV)",
                                _exp_df.to_csv(index=False),
                                file_name=f"boxscore_{g['id']}_{opp_nm}.csv",
                                mime="text/csv",
                                key=f"dl_box_{g['id']}",
                            )

                    # ── Team Stats ───────────────────────────────────────────
                    with gtab_ts:
                        def _fmt_s(s):
                            _m, _sec = divmod(int(s), 60)
                            return f"{_m}:{_sec:02d}"

                        def _team_totals(tid_, pts_, poss_evs_):
                            _sr = [s for s in stats_g.values() if s["team_id"] == tid_]
                            if not _sr: return {}
                            _fgm=sum(r["fgm"] for r in _sr); _fga=sum(r["fga"] for r in _sr)
                            _tpm=sum(r["tpm"] for r in _sr); _tpa=sum(r["tpa"] for r in _sr)
                            _ftm=sum(r["ftm"] for r in _sr); _fta=sum(r["fta"] for r in _sr)
                            _oreb=sum(r["oreb"] for r in _sr); _dreb=sum(r["dreb"] for r in _sr)
                            _poss  = sum(1   for ev in poss_evs_ if player_team_id.get(ev["primary_player_id"])==tid_)
                            _psecs = sum(ev["possession_secs"] or 0 for ev in poss_evs_
                                         if player_team_id.get(ev["primary_player_id"])==tid_)
                            return {
                                "PTS":pts_, "POSS":_poss,
                                "POSS TIME":_fmt_s(_psecs),
                                "AVG POSS":_fmt_s(_psecs/_poss) if _poss else "—",
                                "PPP":round(pts_/_poss,3) if _poss else "—",
                                "FGM":_fgm,"FGA":_fga,"FG%":f"{_fgm/_fga*100:.1f}%" if _fga else "—",
                                "3PM":_tpm,"3PA":_tpa,"3P%":f"{_tpm/_tpa*100:.1f}%" if _tpa else "—",
                                "FTM":_ftm,"FTA":_fta,"FT%":f"{_ftm/_fta*100:.1f}%" if _fta else "—",
                                "AST":sum(r["ast"] for r in _sr),
                                "OREB":_oreb,"DREB":_dreb,"REB":_oreb+_dreb,
                                "STL":sum(r["stl"] for r in _sr),
                                "BLK":sum(r["blk"] for r in _sr),
                                "TOV":sum(r["tov"] for r in _sr),
                                "PF":sum(r["pf"]  for r in _sr),
                            }

                        _poss_evs = [ev for ev in events_g
                                     if ev["event_type"] != "free_throw" and ev["primary_player_id"]]
                        t1_tot_g = _team_totals(t1id, t1p, _poss_evs)
                        t2_tot_g = _team_totals(t2id, t2p, _poss_evs)

                        if t1_tot_g and t2_tot_g:
                            _stat_order = [
                                ("PTS","Points"),("POSS","Possessions"),
                                ("POSS TIME","Total Poss. Time"),("AVG POSS","Avg Poss. Length"),
                                ("PPP","Points Per Possession"),
                                ("FGM","FG Made"),("FGA","FG Attempted"),("FG%","FG%"),
                                ("3PM","3PT Made"),("3PA","3PT Attempted"),("3P%","3P%"),
                                ("FTM","FT Made"),("FTA","FT Attempted"),("FT%","FT%"),
                                ("AST","Assists"),("REB","Rebounds"),
                                ("OREB","Off. Rebounds"),("DREB","Def. Rebounds"),
                                ("STL","Steals"),("BLK","Blocks"),
                                ("TOV","Turnovers"),("PF","Personal Fouls"),
                            ]
                            _ts_rows = [{"Stat":lbl, t1nm:t1_tot_g.get(k,0), t2nm:t2_tot_g.get(k,0)}
                                        for k,lbl in _stat_order]
                            st.dataframe(pd.DataFrame(_ts_rows), use_container_width=True, hide_index=True)
                        else:
                            st.info("No events logged yet.")

                    # ── Officials ────────────────────────────────────────────
                    with gtab_off:
                        _game_offs = query("""
                            SELECT o.id AS oid, o.name AS oname
                            FROM game_lineup_officials glo
                            JOIN officials o ON o.id = glo.official_id
                            WHERE glo.game_id = ?
                        """, (g["id"],))
                        if not _game_offs:
                            st.info("No officials logged for this game.")
                        else:
                            _off_stats = {o["oid"]:{"name":o["oname"],"t1":0,"t2":0} for o in _game_offs}
                            for ev in events_g:
                                if ev["event_type"] != "foul": continue
                                _oid = ev["official_id"]; _fp = ev["secondary_player_id"]
                                if _oid in _off_stats and _fp and _fp in player_team_id:
                                    if player_team_id[_fp] == t1id: _off_stats[_oid]["t1"] += 1
                                    else: _off_stats[_oid]["t2"] += 1
                            _off_rows = [{"Official":s["name"],
                                          f"Calls vs {t1nm}":s["t1"],
                                          f"Calls vs {t2nm}":s["t2"],
                                          "Total":s["t1"]+s["t2"]}
                                         for s in _off_stats.values()]
                            st.dataframe(pd.DataFrame(_off_rows), use_container_width=True, hide_index=True)

                    # ── Hot Zones ────────────────────────────────────────────
                    with gtab_hz:
                        _zf1, _zf2 = st.columns(2)
                        _team_filt = _zf1.selectbox("Team", ["Both Teams", t1nm, t2nm],
                                                    key=f"hz_team_{g['id']}")
                        if _team_filt == t1nm:
                            _hz_pls = [{"pid":pid,"pname":s["name"]} for pid,s in stats_g.items() if s["team_id"]==t1id]
                        elif _team_filt == t2nm:
                            _hz_pls = [{"pid":pid,"pname":s["name"]} for pid,s in stats_g.items() if s["team_id"]==t2id]
                        else:
                            _hz_pls = [{"pid":pid,"pname":s["name"]} for pid,s in stats_g.items()]
                        _pl_filt = _zf2.selectbox("Player", ["All Players"]+[p["pname"] for p in _hz_pls],
                                                  key=f"hz_player_{g['id']}")

                        _shot_evs = [ev for ev in events_g
                                     if ev["event_type"]=="shot" and ev.get("zone")]
                        if _pl_filt != "All Players":
                            _mp = next((p for p in _hz_pls if p["pname"]==_pl_filt), None)
                            if _mp:
                                _shot_evs = [ev for ev in _shot_evs if ev["primary_player_id"]==_mp["pid"]]
                        elif _team_filt != "Both Teams":
                            _tf = t1id if _team_filt==t1nm else t2id
                            _shot_evs = [ev for ev in _shot_evs if player_team_id.get(ev["primary_player_id"])==_tf]

                        render_hot_zones(_shot_evs)

# ══════════════════════════════════════════════════════════════════════════════
#  MATCHUP SIMULATOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_mu:
    other_teams = [t for t in all_teams if t["id"] != team_id]
    if not other_teams:
        st.info("Need at least two teams.")
    else:
        opp_map  = {t["name"]: t["id"] for t in other_teams}
        opp_name = st.selectbox("Select Opponent", list(opp_map.keys()), key="mu_opp_sel")
        opp_id   = opp_map[opp_name]

        mu = compute_matchup(team_id, opp_id)

        adv_a2 = mu["adv_a"]
        adv_b2 = mu["adv_b"]
        prob_a = mu["prob_a"]
        prob_b = 1 - prob_a
        proj_a = mu["proj_a"]
        proj_b = mu["proj_b"]

        # ── Summary header ────────────────────────────────────────────────────
        st.divider()
        hm1, hm2, hm3, hm4, hm5, hm6 = st.columns(6)
        hm1.metric(f"{sel_name} Record",  f"{mu['wa']}-{mu['la']}")
        hm2.metric("Proj Score",          f"{proj_a:.1f} pts")
        hm3.metric(f"{sel_name} Win Prob", f"{prob_a*100:.0f}%")
        hm4.metric(f"{opp_name} Win Prob", f"{prob_b*100:.0f}%")
        hm5.metric("Proj Score",          f"{proj_b:.1f} pts")
        hm6.metric(f"{opp_name} Record",  f"{mu['wb']}-{mu['lb']}")

        # Win probability bar
        bar_html = (
            f"<div style='background:#2d333b;border-radius:6px;height:18px;overflow:hidden'>"
            f"<div style='background:#3498db;width:{prob_a*100:.0f}%;height:100%;float:left;"
            f"border-radius:6px 0 0 6px'></div>"
            f"<div style='background:#e74c3c;width:{prob_b*100:.0f}%;height:100%;float:left;"
            f"border-radius:0 6px 6px 0'></div></div>"
            f"<div style='display:flex;justify-content:space-between;font-size:11px;"
            f"color:#8b949e;margin-top:4px'>"
            f"<span style='color:#3498db;font-weight:700'>{sel_name}</span>"
            f"<span style='color:#e74c3c;font-weight:700'>{opp_name}</span></div>"
        )
        st.markdown(bar_html, unsafe_allow_html=True)
        method_lbl = "efficiency-based (ORtg · DRtg · Pace)" if mu["method"] == "efficiency" else "score-based"
        st.caption(f"Projection method: {method_lbl}")

        # ── Visual stat comparison bars ───────────────────────────────────────
        st.divider()
        if adv_a2 and adv_b2:
            _bars_a = dict(pts=adv_a2["pts_pg"], efg=adv_a2["efg"]*100,
                           ts=adv_a2["ts"]*100,  ast=adv_a2["ast_pg"],
                           tov=adv_a2["tov_pg"], oreb=adv_a2["oreb_pg"],
                           dreb=adv_a2["dreb_pg"],stl=adv_a2["stl_pg"],
                           blk=adv_a2["blk_pg"])
            _bars_b = dict(pts=adv_b2["pts_pg"], efg=adv_b2["efg"]*100,
                           ts=adv_b2["ts"]*100,  ast=adv_b2["ast_pg"],
                           tov=adv_b2["tov_pg"], oreb=adv_b2["oreb_pg"],
                           dreb=adv_b2["dreb_pg"],stl=adv_b2["stl_pg"],
                           blk=adv_b2["blk_pg"])
            show_matchup_bars(_bars_a, _bars_b, sel_name, opp_name)

        # ── Side-by-side stat table with ✅ markers ───────────────────────────
        st.divider()
        st.markdown("#### Side-by-Side Stats")

        _cmp_stats = [
            ("PPG",      mu["ppg_a"],               mu["ppg_b"],               True),
            ("PA/G",     mu["papg_a"],              mu["papg_b"],              False),
        ]
        if adv_a2 and adv_b2:
            _cmp_stats += [
                ("ORtg",     adv_a2["ortg"],            adv_b2["ortg"],            True),
                ("DRtg",     adv_a2["drtg"],            adv_b2["drtg"],            False),
                ("Net Rtg",  adv_a2["net"],             adv_b2["net"],             True),
                ("eFG%",     adv_a2["efg"]*100,         adv_b2["efg"]*100,         True),
                ("Opp eFG%", adv_a2["oefg"]*100,        adv_b2["oefg"]*100,        False),
                ("TS%",      adv_a2["ts"]*100,          adv_b2["ts"]*100,          True),
                ("TOV%",     adv_a2["tov_r"]*100,       adv_b2["tov_r"]*100,       False),
                ("OREB%",    adv_a2["oreb_p"]*100,      adv_b2["oreb_p"]*100,      True),
                ("DREB%",    adv_a2["dreb_p"]*100,      adv_b2["dreb_p"]*100,      True),
                ("FT Rate",  adv_a2["ft_r"],            adv_b2["ft_r"],            True),
                ("Pace",     adv_a2["pace"],            adv_b2["pace"],            True),
            ]

        _cmp_rows = []
        for label, va, vb, hib in _cmp_stats:
            try:
                va_f, vb_f = float(va), float(vb)
            except (TypeError, ValueError):
                continue
            better_a = va_f >= vb_f if hib else va_f <= vb_f
            _cmp_rows.append({
                sel_name: f"{'✅ ' if better_a else ''}{va_f:.1f}",
                "Stat":   label,
                opp_name: f"{'✅ ' if not better_a else ''}{vb_f:.1f}",
            })
        if _cmp_rows:
            st.dataframe(pd.DataFrame(_cmp_rows).set_index("Stat"), use_container_width=True)

        # ── Head-to-head history ──────────────────────────────────────────────
        st.divider()
        st.markdown("#### 📜 Head-to-Head History")
        if not mu["h2h"]:
            st.info("These two teams have not played each other yet.")
        else:
            h2h_games = mu["h2h"]
            # Count wins
            h2h_w_me  = sum(1 for g in h2h_games
                            if (g["team1_id"] == team_id and g["home_score"] > g["away_score"])
                            or (g["team1_id"] != team_id and g["away_score"] > g["home_score"]))
            h2h_w_opp = len(h2h_games) - h2h_w_me
            hh1, hh2 = st.columns(2)
            hh1.metric(f"{sel_name} wins",  h2h_w_me)
            hh2.metric(f"{opp_name} wins",  h2h_w_opp)

            for g in h2h_games:
                if g["team1_id"] == team_id:
                    me_sc, opp_sc = g["home_score"], g["away_score"]
                else:
                    me_sc, opp_sc = g["away_score"], g["home_score"]
                i_won = me_sc > opp_sc
                winner_name = sel_name  if i_won else opp_name
                w_sc = me_sc  if i_won else opp_sc
                l_sc = opp_sc if i_won else me_sc
                loser_name  = opp_name  if i_won else sel_name
                try:
                    dl = _dth.strptime(g["date"], "%Y-%m-%d").strftime("%B %d, %Y")
                except Exception:
                    dl = g["date"] or "—"
                st.markdown(
                    f"<div class='score-card'>"
                    f"<span style='color:#8b949e;font-size:11px'>{dl}</span><br>"
                    f"<span style='color:#2ecc71;font-weight:700'>{winner_name}</span> "
                    f"<span style='color:#f0a500;font-weight:800'>{w_sc}</span>  –  "
                    f"<span style='color:#8b949e;font-weight:700'>{loser_name}</span> "
                    f"<span style='color:#555d68;font-weight:800'>{l_sc}</span>"
                    f"</div>", unsafe_allow_html=True)

                # Check if tracked for box score
                _g_tracked = query(
                    "SELECT id, tracked FROM games WHERE team1_id IN (?,?) AND team2_id IN (?,?) "
                    "AND date=? AND tracked=1 LIMIT 1",
                    (team_id, opp_id, team_id, opp_id, g["date"]))
                if _g_tracked:
                    with st.expander("View Box Score"):
                        _bsr1, _bsr2, _gi = compute_game_box_score(_g_tracked[0]["id"])
                        if any(not r.get("_totals") for r in _bsr1 + _bsr2):
                            show_game_box_score(_bsr1, _bsr2, {}, _gi, _cfg)

# ══════════════════════════════════════════════════════════════════════════════
#  NOTES
# ══════════════════════════════════════════════════════════════════════════════
with tab_notes:
    from Database.db import execute as db_execute
    current_notes = query("SELECT notes FROM teams WHERE id=?", (team_id,))
    existing = current_notes[0]["notes"] if current_notes else ""
    new_notes = st.text_area(
        f"Notes — {sel_name}",
        value=existing,
        height=400,
        placeholder="Scouting notes, tendencies, player observations, game plans…",
        key=f"team_notes_{team_id}",
    )
    if st.button("💾 Save Notes", type="primary", key="save_notes_analytics"):
        db_execute("UPDATE teams SET notes=? WHERE id=?", (new_notes, team_id))
        st.success("Notes saved.")

# ══════════════════════════════════════════════════════════════════════════════
#  📊 SMART INSIGHTS  (rule-based — no API key required)
# ══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.markdown(
        f"<div style='margin-bottom:10px'>"
        f"<span style='font-size:20px;font-weight:800;color:#f0f6fc'>📊 Smart Insights</span>"
        f"&nbsp;&nbsp;<span style='font-size:12px;color:#8b949e'>"
        f"Auto-generated from live data — <b style='color:#f0a500'>{sel_name}</b></span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Pull all the data we need ─────────────────────────────────────────────
    _ai_games  = games_for_team(team_id)
    _ai_adv    = compute_team_tracked(team_id)
    _ai_w, _ai_l, _ai_pf, _ai_pa = (
        record_from_games(_ai_games, team_id) if _ai_games else (0, 0, 0, 0)
    )
    _ai_gp = max(len(_ai_games), 1)
    _ai_ppg  = _ai_pf / _ai_gp
    _ai_papg = _ai_pa / _ai_gp
    _ai_margin = _ai_ppg - _ai_papg
    _ai_win_pct = _ai_w / _ai_gp

    # Roster stats
    _ai_roster = query(
        "SELECT id, name, number FROM players WHERE team_id=? AND archived=0 ORDER BY name",
        (team_id,),
    )
    _ai_player_stats: list[dict] = []
    for _p in _ai_roster:
        _c = compute_player_career(_p["id"])
        if _c and _c.get("gp", 0) > 0:
            _pgp = _c["gp"]
            _ai_player_stats.append({
                "name":   _p["name"],
                "number": _p["number"],
                "gp":     _pgp,
                "ppg":    _c["pts"]  / _pgp,
                "rpg":    (_c.get("oreb", 0) + _c.get("dreb", 0)) / _pgp,
                "apg":    _c.get("ast", 0) / _pgp,
                "spg":    _c.get("stl", 0) / _pgp,
                "bpg":    _c.get("blk", 0) / _pgp,
                "topg":   _c.get("tov", 0) / _pgp,
                "fgp":    (_c["fgm"] / _c["fga"]) if _c.get("fga") else None,
                "tpp":    (_c["tpm"] / _c["tpa"]) if _c.get("tpa") else None,
                "ftp":    (_c["ftm"] / _c["fta"]) if _c.get("fta") else None,
                "pts":    _c["pts"],
            })
    _ai_player_stats.sort(key=lambda x: x["ppg"], reverse=True)

    # ── Helper: coloured badge ────────────────────────────────────────────────
    def _badge(label: str, good: bool | None = None) -> str:
        if good is None:
            colour = "#555"
        elif good:
            colour = "#2ea043"
        else:
            colour = "#da3633"
        return (
            f"<span style='background:{colour};color:#fff;"
            f"padding:2px 8px;border-radius:12px;font-size:12px;"
            f"font-weight:600;margin-left:6px'>{label}</span>"
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  SNAPSHOT ROW
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("#### Season Snapshot")
    _sc1, _sc2, _sc3, _sc4, _sc5 = st.columns(5)
    _sc1.metric("Record",   f"{_ai_w}–{_ai_l}")
    _sc2.metric("Win %",    f"{_ai_win_pct*100:.1f}%")
    _sc3.metric("PPG",      f"{_ai_ppg:.1f}")
    _sc4.metric("Opp PPG",  f"{_ai_papg:.1f}")
    _sc5.metric("Margin",   f"{_ai_margin:+.1f}")

    if _ai_adv and _ai_adv.get("gp", 0) > 0:
        _adv = _ai_adv
        _ac1, _ac2, _ac3, _ac4, _ac5 = st.columns(5)
        _ac1.metric("ORtg",   f"{_adv['ortg']:.1f}")
        _ac2.metric("DRtg",   f"{_adv['drtg']:.1f}")
        _ac3.metric("Net Rtg", f"{_adv['net']:+.1f}")
        _ac4.metric("Pace",   f"{_adv['pace']:.1f}")
        _ac5.metric("TS%",    f"{_adv['ts']*100:.1f}%")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    #  STRENGTHS & WEAKNESSES
    # ══════════════════════════════════════════════════════════════════════════
    _strengths:   list[str] = []
    _weaknesses:  list[str] = []
    _notes:       list[str] = []

    # Win/loss record
    if _ai_win_pct >= 0.65:
        _strengths.append(f"**Winning culture** — {_ai_win_pct*100:.0f}% win rate ({_ai_w}–{_ai_l}). Team is consistently closing out games.")
    elif _ai_win_pct <= 0.35:
        _weaknesses.append(f"**Win rate** — {_ai_win_pct*100:.0f}% ({_ai_w}–{_ai_l}). Execution in close games or late-game situations may need attention.")
    else:
        _notes.append(f"**Competitive** — {_ai_win_pct*100:.0f}% win rate ({_ai_w}–{_ai_l}). Games appear close; margins matter.")

    # Scoring margin
    if _ai_margin >= 8:
        _strengths.append(f"**Dominant margin** — +{_ai_margin:.1f} pts/game. Consistent pressure on opponents suggests depth or execution advantage.")
    elif _ai_margin <= -6:
        _weaknesses.append(f"**Negative margin** — {_ai_margin:.1f} pts/game. Either scoring droughts or late defensive breakdowns are costing games.")

    if _ai_adv and _ai_adv.get("gp", 0) > 0:
        _adv = _ai_adv

        # Offensive rating
        if _adv["ortg"] >= 105:
            _strengths.append(f"**Efficient offense** — ORtg {_adv['ortg']:.1f}. Attack patterns are generating quality looks consistently.")
        elif _adv["ortg"] <= 90:
            _weaknesses.append(f"**Offensive efficiency** — ORtg {_adv['ortg']:.1f}. Low rating suggests poor shot selection, turnover issues, or lack of pace.")

        # Defensive rating (lower = better)
        if _adv["drtg"] <= 95:
            _strengths.append(f"**Elite defense** — DRtg {_adv['drtg']:.1f}. Opponents struggle to score, indicating solid rotations and contest rates.")
        elif _adv["drtg"] >= 110:
            _weaknesses.append(f"**Defensive leaks** — DRtg {_adv['drtg']:.1f}. Opponents are scoring efficiently; check help-defense and transition defense.")

        # Shooting
        if _adv["efg"] >= 0.54:
            _strengths.append(f"**Shooting efficiency** — eFG% {_adv['efg']*100:.1f}%. Strong shot quality or spacing is creating open looks.")
        elif _adv["efg"] <= 0.44:
            _weaknesses.append(f"**Shooting struggles** — eFG% {_adv['efg']*100:.1f}%. Consider shot-quality drills or revisiting offensive sets.")

        # Turnovers
        if _adv["tov_r"] <= 0.14:
            _strengths.append(f"**Ball security** — TOV% {_adv['tov_r']*100:.1f}%. Team is disciplined with possessions.")
        elif _adv["tov_r"] >= 0.21:
            _weaknesses.append(f"**Ball security** — TOV% {_adv['tov_r']*100:.1f}%. Too many possessions lost to turnovers. Emphasise decision-making under pressure.")

        # Offensive rebounding
        if _adv["oreb_p"] >= 0.32:
            _strengths.append(f"**Offensive rebounding** — OREB% {_adv['oreb_p']*100:.1f}%. Second-chance points are a real weapon.")
        elif _adv["oreb_p"] <= 0.20:
            _notes.append(f"**Offensive rebounding** — OREB% {_adv['oreb_p']*100:.1f}%. Team may be prioritising transition defence over crashing the glass.")

        # Pace
        if _adv["pace"] >= 75:
            _notes.append(f"**Up-tempo** — Pace {_adv['pace']:.1f} poss/game. High pace favours athleticism; monitor fatigue depth.")
        elif _adv["pace"] <= 60:
            _notes.append(f"**Half-court focused** — Pace {_adv['pace']:.1f} poss/game. Half-court execution and set plays are critical.")

        # FT rate
        if _adv["ft_r"] >= 0.35:
            _strengths.append(f"**Getting to the line** — FT Rate {_adv['ft_r']:.2f}. Aggressive drives are drawing fouls and generating free possessions.")
        elif _adv["ft_r"] <= 0.18:
            _weaknesses.append(f"**Free-throw generation** — FT Rate {_adv['ft_r']:.2f}. Team is not attacking the paint enough or getting whistles.")

    # Fall-back if no tracked games
    if not _strengths and not _weaknesses and not (_ai_adv and _ai_adv.get("gp", 0) > 0):
        _notes.append("Track a full game via the Game Tracker to unlock advanced shooting, pace, and efficiency insights.")

    # ── Render strengths / weaknesses ─────────────────────────────────────────
    _sw_c1, _sw_c2 = st.columns(2)

    with _sw_c1:
        st.markdown("#### ✅ Strengths")
        if _strengths:
            for _s in _strengths:
                st.markdown(f"- {_s}")
        else:
            st.caption("No clear statistical strengths detected yet — keep logging games.")

    with _sw_c2:
        st.markdown("#### ⚠️ Areas to Improve")
        if _weaknesses:
            for _w in _weaknesses:
                st.markdown(f"- {_w}")
        else:
            st.caption("No glaring weaknesses detected. Keep it up!")

    if _notes:
        st.markdown("#### 📌 Context Notes")
        for _n in _notes:
            st.markdown(f"- {_n}")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    #  PLAYER SPOTLIGHT
    # ══════════════════════════════════════════════════════════════════════════
    if _ai_player_stats:
        st.markdown("#### 🌟 Player Spotlight")

        _top_scorer   = max(_ai_player_stats, key=lambda x: x["ppg"])
        _top_rebounder = max(_ai_player_stats, key=lambda x: x["rpg"])
        _top_assists  = max(_ai_player_stats, key=lambda x: x["apg"])
        _top_stocks   = max(_ai_player_stats, key=lambda x: x["spg"] + x["bpg"])

        _sp1, _sp2, _sp3, _sp4 = st.columns(4)

        def _player_card(col, emoji: str, role: str, p: dict):
            fgp_str = f"{p['fgp']*100:.1f}%" if p["fgp"] is not None else "—"
            col.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;"
                f"border-radius:10px;padding:12px;text-align:center'>"
                f"<div style='font-size:22px'>{emoji}</div>"
                f"<div style='font-size:11px;color:#8b949e;text-transform:uppercase;"
                f"letter-spacing:1px'>{role}</div>"
                f"<div style='font-size:15px;font-weight:700;color:#f0f6fc;margin:4px 0'>"
                f"#{p['number']} {p['name']}</div>"
                f"<div style='font-size:13px;color:#f0a500;font-weight:600'>"
                f"{p['ppg']:.1f} PPG · {p['rpg']:.1f} RPG · {p['apg']:.1f} APG</div>"
                f"<div style='font-size:11px;color:#8b949e;margin-top:4px'>"
                f"FG% {fgp_str} · {p['gp']}G</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        _player_card(_sp1, "🔥", "Top Scorer",    _top_scorer)
        _player_card(_sp2, "💪", "Top Rebounder", _top_rebounder)
        _player_card(_sp3, "🎯", "Playmaker",     _top_assists)
        _player_card(_sp4, "🛡️", "Defensive Ace", _top_stocks)

        st.markdown("---")

        # ── Full roster table ─────────────────────────────────────────────────
        with st.expander("📋 Full Roster Averages", expanded=False):
            import pandas as _pd_ai
            _roster_df = _pd_ai.DataFrame([
                {
                    "#":      p["number"],
                    "Player": p["name"],
                    "GP":     p["gp"],
                    "PPG":    round(p["ppg"], 1),
                    "RPG":    round(p["rpg"], 1),
                    "APG":    round(p["apg"], 1),
                    "SPG":    round(p["spg"], 1),
                    "BPG":    round(p["bpg"], 1),
                    "TO/G":   round(p["topg"], 1),
                    "FG%":    f"{p['fgp']*100:.1f}%" if p["fgp"] is not None else "—",
                    "3P%":    f"{p['tpp']*100:.1f}%" if p["tpp"] is not None else "—",
                    "FT%":    f"{p['ftp']*100:.1f}%" if p["ftp"] is not None else "—",
                }
                for p in _ai_player_stats
            ])
            st.dataframe(_roster_df, use_container_width=True, hide_index=True)

    else:
        st.info("No player data yet. Add players and log games to see individual breakdowns.")

    # ══════════════════════════════════════════════════════════════════════════
    #  COACHING PRIORITIES  (rule-based recommendations)
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🏋️ Coaching Priorities")

    _priorities: list[tuple[str, str]] = []  # (priority text, rationale)

    if _ai_adv and _ai_adv.get("gp", 0) > 0:
        _adv = _ai_adv
        if _adv["tov_r"] >= 0.20:
            _priorities.append((
                "Reduce turnovers in transition",
                f"TOV% is {_adv['tov_r']*100:.1f}% — work on catch-and-attack drills and limit dribble-hand-offs under pressure.",
            ))
        if _adv["drtg"] >= 108:
            _priorities.append((
                "Tighten defensive rotations",
                f"DRtg {_adv['drtg']:.1f} indicates opponents are finding open looks. Focus on help-side positioning and closeouts.",
            ))
        if _adv["efg"] <= 0.46:
            _priorities.append((
                "Improve shot selection",
                f"eFG% {_adv['efg']*100:.1f}% is below average. Prioritise corner 3s and lay-ups; reduce mid-range pull-ups.",
            ))
        if _adv["oreb_p"] <= 0.22:
            _priorities.append((
                "Crash the offensive glass harder",
                f"OREB% {_adv['oreb_p']*100:.1f}%. Second-chance points are being left on the table.",
            ))
        if _adv["ft_r"] <= 0.20:
            _priorities.append((
                "Attack the paint more aggressively",
                f"FT Rate {_adv['ft_r']:.2f} — driving lanes and post touches generate fouls and easy points.",
            ))
        if _adv["oefg"] >= 0.54:
            _priorities.append((
                "Contest shots harder on defence",
                f"Opponents are shooting eFG% {_adv['oefg']*100:.1f}%. Improve on-ball pressure and tag on cutters.",
            ))

    # Generic priorities from overall numbers
    if _ai_win_pct < 0.40 and _ai_margin < -5:
        _priorities.append((
            "Focus on late-game execution",
            f"Negative margin ({_ai_margin:.1f} pts) with a losing record suggests close games slip away late. Run late-game scenarios in practice.",
        ))

    if _ai_player_stats:
        _scorer = _ai_player_stats[0]
        _rest   = _ai_player_stats[1:]
        if _rest and _scorer["ppg"] > 2.5 * (_rest[0]["ppg"] if _rest else 1):
            _priorities.append((
                f"Distribute the load beyond #{_scorer['number']} {_scorer['name']}",
                f"Scoring is concentrated: {_scorer['ppg']:.1f} PPG vs next best {_rest[0]['ppg']:.1f} PPG. "
                "Develop secondary scoring options so opponents can't key in on one player.",
            ))

    if not _priorities:
        _priorities.append((
            "Keep logging games",
            "More game-tracking data will unlock targeted, specific coaching recommendations here.",
        ))

    for _idx, (_pri, _rat) in enumerate(_priorities, 1):
        st.markdown(
            f"<div style='background:#161b22;border-left:3px solid #f0a500;"
            f"border-radius:0 8px 8px 0;padding:10px 14px;margin-bottom:8px'>"
            f"<span style='font-weight:700;color:#f0f6fc'>{_idx}. {_pri}</span><br>"
            f"<span style='font-size:13px;color:#8b949e'>{_rat}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
