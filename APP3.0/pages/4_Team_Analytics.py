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
                            show_score_flow_chart, show_matchup_bars, show_shooting_pct_chart)
from helpers.stats_team import (compute_player_game_log, compute_player_career,
                                compute_team_tracked, compute_on_off,
                                compute_league_drtg, compute_league_four_factors,
                                compute_matchup, compute_all_teams_standings)
from helpers.stats_players import (compute_player_ratings,
                                   compute_player_rankings,
                                   compute_game_box_score,
                                   compute_game_quarter_scores)
from helpers.settings_utils import get_all_settings, apply_page_config, apply_theme_css
from helpers.box_score_render import show_game_box_score
from helpers.ui_utils import PLOT_LAYOUT, patch_dataframe

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.kpi-tile {
    background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:16px 20px; text-align:center; margin-bottom:10px;
}
.kpi-label { font-size:10px; color:#8b949e; text-transform:uppercase;
             letter-spacing:1.2px; font-weight:600; margin-bottom:6px; }
.kpi-value { font-size:32px; font-weight:900; color:#f0a500; line-height:1.1; }
.kpi-sub   { font-size:12px; color:#c9d1d9; margin-top:5px; }
.adv-tile {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:12px 16px; text-align:center;
}
.adv-label { font-size:10px; color:#8b949e; text-transform:uppercase;
             letter-spacing:1px; margin-bottom:4px; }
.adv-value { font-size:22px; font-weight:800; color:#58a6ff; }
.section-hdr {
    font-size:17px; font-weight:700; color:#f0f6fc;
    border-left:4px solid #f0a500; padding-left:10px; margin:16px 0 10px;
}
.ff-label  { font-size:11px; color:#8b949e; text-transform:uppercase;
             letter-spacing:1px; margin-bottom:3px; }
.ff-team   { font-size:20px; font-weight:800; color:#f0a500; }
.ff-opp    { font-size:20px; font-weight:800; color:#e74c3c; }
.ff-bar-wrap{ background:#21262d; border-radius:4px; height:8px; overflow:hidden; margin:4px 0; }
.ff-bar-t  { background:#f0a500; height:100%; border-radius:4px; }
.ff-bar-o  { background:#e74c3c; height:100%; border-radius:4px; }
.big4-card {
    background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);
    border:2px solid #30363d; border-radius:16px;
    padding:22px 18px; text-align:center; margin-bottom:12px;
}
.big4-label { font-size:11px; color:#8b949e; text-transform:uppercase;
              letter-spacing:1.5px; font-weight:700; margin-bottom:8px; }
.big4-team  { font-size:38px; font-weight:900; color:#f0a500; line-height:1; }
.big4-opp   { font-size:38px; font-weight:900; color:#e74c3c; line-height:1; }
.big4-sub   { font-size:11px; color:#8b949e; margin-top:6px; }
.big4-bar-wrap { background:#21262d; border-radius:6px; height:12px;
                 overflow:hidden; margin:8px 0 4px; }
.big4-bar-t { background:linear-gradient(90deg,#f0a500,#e67e22); height:100%; border-radius:6px; }
.big4-bar-o { background:linear-gradient(90deg,#e74c3c,#c0392b); height:100%; border-radius:6px; }
.rat-card {
    background:linear-gradient(135deg,#0d1117,#161b22);
    border:1px solid #30363d; border-radius:12px;
    padding:16px; margin-bottom:10px;
}
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
.pl-hero {
    background:linear-gradient(135deg,#0d1117 0%,#1a2332 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:20px 24px; margin-bottom:14px;
}
.pl-name  { font-size:20px; font-weight:900; color:#f0f6fc; }
.pl-meta  { font-size:12px; color:#8b949e; margin-top:4px; }
.stat-grid {
    display:grid; grid-template-columns:repeat(auto-fit,minmax(90px,1fr)); gap:10px;
    margin-bottom:16px;
}
.stat-cell {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:10px 8px; text-align:center;
}
.stat-cell-val { font-size:20px; font-weight:800; color:#f0a500; }
.stat-cell-lbl { font-size:9px; color:#8b949e; text-transform:uppercase;
                 letter-spacing:1px; margin-top:3px; }
.record-badge {
    display:inline-block; background:#21262d; border:1px solid #30363d;
    border-radius:8px; padding:6px 14px; font-size:13px; font-weight:700;
    color:#c9d1d9; margin:3px;
}
.win-badge  { border-color:#2ecc71; color:#2ecc71; }
.loss-badge { border-color:#e74c3c; color:#e74c3c; }
</style>
""", unsafe_allow_html=True)

# ── Setup ─────────────────────────────────────────────────────────────────────
initialize_database()
_cfg = get_all_settings()
apply_page_config(_cfg)
apply_theme_css(_cfg)
patch_dataframe()

st.title("🏀 Team Analytics")

all_teams = query("SELECT id, name, class, gender FROM teams ORDER BY name")
if not all_teams:
    st.warning("No teams found.")
    st.stop()

team_map  = {t["name"]: t["id"] for t in all_teams}
team_meta = {t["id"]: t for t in all_teams}
_team_names = list(team_map.keys())
_default_team = _cfg.get("default_team", "")
_default_idx  = _team_names.index(_default_team) if _default_team in _team_names else 0
if "ta_team_sel" not in st.session_state:
    st.session_state["ta_team_sel"] = _team_names[_default_idx]
elif st.session_state["ta_team_sel"] not in _team_names:
    st.session_state["ta_team_sel"] = _team_names[_default_idx]

# ── Global team selector ──────────────────────────────────────────────────────
sel_name = st.selectbox("Select Team", _team_names, key="ta_team_sel")
team_id  = team_map[sel_name]
team_info = team_meta[team_id]

# Pre-load data used across multiple tabs
all_gs   = games_for_team(team_id)
tr_gs    = games_for_team(team_id, tracked_only=True)
adv      = compute_team_tracked(team_id)
w, l, pf, pa = record_from_games(all_gs, team_id)
gp   = len(all_gs)
tgp  = len(tr_gs)

# League-wide standings (for ranking/record vs top-X)
_standings = compute_all_teams_standings()
_std_df = pd.DataFrame(_standings) if _standings else pd.DataFrame()

# ── Tab layout ────────────────────────────────────────────────────────────────
tab_ov, tab_sc, tab_an, tab_pl, tab_lu, tab_mu, tab_ins = st.tabs([
    "📋 Overview", "📅 Schedule", "📊 Analytics", "👤 Players", "🔄 Lineups", "⚔️ Matchup", "💡 Insights"
])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_ov:
    # ── Team header ──────────────────────────────────────────────────────────
    gender_lbl = "Women" if team_info["gender"] == "F" else "Men"
    _ppg_ov = pf / gp if gp else 0
    _papg_ov = pa / gp if gp else 0
    _margin_ov = _ppg_ov - _papg_ov

    st.markdown(
        f"<div class='pl-hero'>"
        f"<div class='pl-name'>{sel_name}</div>"
        f"<div class='pl-meta'>Class {team_info['class']} · {gender_lbl} · "
        f"{w}–{l} record · {gp} games played · {tgp} tracked</div>"
        f"</div>", unsafe_allow_html=True)

    # ── KPI tiles ────────────────────────────────────────────────────────────
    kc = st.columns(5)
    _win_pct = w / gp * 100 if gp else 0
    for col, lbl, val, sub in [
        (kc[0], "Record",   f"{w}–{l}",          f"{_win_pct:.1f}% W%"),
        (kc[1], "PPG",      f"{_ppg_ov:.1f}",     "points per game"),
        (kc[2], "PA/G",     f"{_papg_ov:.1f}",    "points allowed"),
        (kc[3], "Margin",   f"{_margin_ov:+.1f}", "avg differential"),
        (kc[4], "Tracked",  tgp,                  f"of {gp} charted"),
    ]:
        col.markdown(
            f"<div class='kpi-tile'>"
            f"<div class='kpi-label'>{lbl}</div>"
            f"<div class='kpi-value'>{val}</div>"
            f"<div class='kpi-sub'>{sub}</div>"
            f"</div>", unsafe_allow_html=True)

    # ── Ranking & Record vs Top Teams ────────────────────────────────────────
    if not _std_df.empty:
        st.markdown("<div class='section-hdr'>League Standing & Record vs Ranked Teams</div>",
                    unsafe_allow_html=True)

        # Find this team's rank by margin among all teams
        _rk_sorted = _std_df.sort_values("margin", ascending=False).reset_index(drop=True)
        _rk_sorted["rank"] = range(1, len(_rk_sorted) + 1)
        _my_row = _rk_sorted[_rk_sorted["id"] == team_id]
        _my_rank = int(_my_row["rank"].iloc[0]) if not _my_row.empty else None
        _total_teams = len(_rk_sorted)

        # Top 10 and Top 25 team IDs
        _top10_ids  = set(_rk_sorted.head(10)["id"].tolist())
        _top25_ids  = set(_rk_sorted.head(25)["id"].tolist())

        # Compute record vs top 10 / top 25
        def _record_vs(team_ids_set):
            wins, losses = 0, 0
            for g in all_gs:
                opp_id = g["team2_id"] if g["team1_id"] == team_id else g["team1_id"]
                if opp_id not in team_ids_set:
                    continue
                res, _, _ = win_loss(g, team_id)
                if res == "W":
                    wins += 1
                else:
                    losses += 1
            return wins, losses

        _w10, _l10 = _record_vs(_top10_ids - {team_id})
        _w25, _l25 = _record_vs(_top25_ids - {team_id})

        rk_c1, rk_c2, rk_c3, rk_c4 = st.columns(4)
        if _my_rank:
            rk_c1.markdown(
                f"<div class='kpi-tile'>"
                f"<div class='kpi-label'>Overall Rank</div>"
                f"<div class='kpi-value'>#{_my_rank}</div>"
                f"<div class='kpi-sub'>of {_total_teams} teams</div>"
                f"</div>", unsafe_allow_html=True)
        rk_c2.markdown(
            f"<div class='kpi-tile'>"
            f"<div class='kpi-label'>vs Top 10</div>"
            f"<div class='kpi-value'>{_w10}–{_l10}</div>"
            f"<div class='kpi-sub'>record</div>"
            f"</div>", unsafe_allow_html=True)
        rk_c3.markdown(
            f"<div class='kpi-tile'>"
            f"<div class='kpi-label'>vs Top 25</div>"
            f"<div class='kpi-value'>{_w25}–{_l25}</div>"
            f"<div class='kpi-sub'>record</div>"
            f"</div>", unsafe_allow_html=True)
        if not _my_row.empty:
            _my_ppg = float(_my_row["ppg"].iloc[0])
            _my_opp = float(_my_row["opp_ppg"].iloc[0])
            rk_c4.markdown(
                f"<div class='kpi-tile'>"
                f"<div class='kpi-label'>Net Rating Rank</div>"
                f"<div class='kpi-value'>{_my_ppg:.1f} / {_my_opp:.1f}</div>"
                f"<div class='kpi-sub'>PPG / OPP PPG</div>"
                f"</div>", unsafe_allow_html=True)

    # ── Schedule ─────────────────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Season Schedule & Results</div>", unsafe_allow_html=True)

    if all_gs:
        _sched_rows = []
        for g in sorted(all_gs, key=lambda x: x["date"]):
            _res, _my, _opp = win_loss(g, team_id)
            try:
                _dl = datetime.strptime(g["date"], "%Y-%m-%d").strftime("%b %d")
            except Exception:
                _dl = g["date"] or "—"
            _sched_rows.append({
                "Date":     _dl,
                "Opponent": opponent_name(g, team_id),
                "H/A":      home_away(g, team_id),
                "Result":   _res,
                "Score":    f"{_my}–{_opp}",
                "MOV":      f"{_my - _opp:+d}",
                "Tracked":  "✓" if g.get("tracked") else "",
            })
        st.dataframe(pd.DataFrame(_sched_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No games found for this team.")

    # ── Chart 1: Points Scored / Allowed + MOV (all games) ───────────────────
    if all_gs:
        st.markdown("<div class='section-hdr'>Points Scored & Allowed — All Games</div>",
                    unsafe_allow_html=True)

        _chart_data = []
        for g in sorted(all_gs, key=lambda x: x["date"]):
            _res, _my, _opp_sc = win_loss(g, team_id)
            _opp_n = opponent_name(g, team_id)
            _ha = home_away(g, team_id)
            try:
                _dl2 = datetime.strptime(g["date"], "%Y-%m-%d").strftime("%b %d")
            except Exception:
                _dl2 = g["date"] or "—"
            _label = f"{_dl2} {'vs' if _ha == 'H' else '@'} {_opp_n}"
            _chart_data.append({
                "label": _label,
                "pts_scored": _my,
                "pts_allowed": _opp_sc,
                "mov": _my - _opp_sc,
                "result": _res,
            })

        _cd_df = pd.DataFrame(_chart_data)
        _colors_mov = ["#2ecc71" if m >= 0 else "#e74c3c" for m in _cd_df["mov"]]

        fig_c1 = go.Figure()
        # MOV bars (primary)
        fig_c1.add_trace(go.Bar(
            x=_cd_df["label"], y=_cd_df["mov"],
            name="MOV", marker_color=_colors_mov,
            opacity=0.55, yaxis="y1",
            hovertemplate="%{x}<br>MOV: %{y:+d}<extra></extra>",
        ))
        # Points scored line
        fig_c1.add_trace(go.Scatter(
            x=_cd_df["label"], y=_cd_df["pts_scored"],
            name="Pts Scored", mode="lines+markers",
            line=dict(color="#f0a500", width=2),
            marker=dict(size=6), yaxis="y2",
            hovertemplate="%{x}<br>Scored: %{y}<extra></extra>",
        ))
        # Points allowed line
        fig_c1.add_trace(go.Scatter(
            x=_cd_df["label"], y=_cd_df["pts_allowed"],
            name="Pts Allowed", mode="lines+markers",
            line=dict(color="#e74c3c", width=2, dash="dot"),
            marker=dict(size=6), yaxis="y2",
            hovertemplate="%{x}<br>Allowed: %{y}<extra></extra>",
        ))
        fig_c1.update_layout(
            **PLOT_LAYOUT,
            title="Points Scored & Allowed with Margin of Victory",
            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
            yaxis=dict(title="MOV", zeroline=True, zerolinecolor="#444",
                       zerolinewidth=1, showgrid=False),
            yaxis2=dict(title="Points", overlaying="y", side="right",
                        showgrid=True, gridcolor="#21262d"),
            barmode="relative",
            legend=dict(orientation="h", y=-0.2),
            height=400,
        )
        st.plotly_chart(fig_c1, use_container_width=True)

    # ── Chart 2: ORtg / DRtg + MOV (tracked games) ───────────────────────────
    if adv and adv.get("game_log"):
        st.markdown("<div class='section-hdr'>ORtg & DRtg — Tracked Games</div>",
                    unsafe_allow_html=True)

        _gl = adv["game_log"]
        _gl_labels = []
        for entry in _gl:
            try:
                _dl3 = datetime.strptime(entry["date"], "%Y-%m-%d").strftime("%b %d")
            except Exception:
                _dl3 = entry.get("date", "—")
            _gl_labels.append(f"{_dl3} vs {entry['opp']}")

        _gl_mov    = [e["margin"] for e in _gl]
        _gl_ortg   = [e["ortg"]   for e in _gl]
        _gl_drtg   = [e["drtg"]   for e in _gl]
        _colors_gl = ["#2ecc71" if m >= 0 else "#e74c3c" for m in _gl_mov]

        fig_c2 = go.Figure()
        fig_c2.add_trace(go.Bar(
            x=_gl_labels, y=_gl_mov,
            name="MOV", marker_color=_colors_gl,
            opacity=0.55, yaxis="y1",
            hovertemplate="%{x}<br>MOV: %{y:+.0f}<extra></extra>",
        ))
        fig_c2.add_trace(go.Scatter(
            x=_gl_labels, y=_gl_ortg,
            name="ORtg", mode="lines+markers",
            line=dict(color="#f0a500", width=2),
            marker=dict(size=6), yaxis="y2",
            hovertemplate="%{x}<br>ORtg: %{y:.1f}<extra></extra>",
        ))
        fig_c2.add_trace(go.Scatter(
            x=_gl_labels, y=_gl_drtg,
            name="DRtg", mode="lines+markers",
            line=dict(color="#3498db", width=2, dash="dot"),
            marker=dict(size=6), yaxis="y2",
            hovertemplate="%{x}<br>DRtg: %{y:.1f}<extra></extra>",
        ))
        fig_c2.update_layout(
            **PLOT_LAYOUT,
            title="Offensive & Defensive Rating with Margin of Victory",
            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
            yaxis=dict(title="MOV", zeroline=True, zerolinecolor="#444",
                       zerolinewidth=1, showgrid=False),
            yaxis2=dict(title="Rating", overlaying="y", side="right",
                        showgrid=True, gridcolor="#21262d"),
            legend=dict(orientation="h", y=-0.2),
            height=400,
        )
        st.plotly_chart(fig_c2, use_container_width=True)

    # ── Chart 3: PPP / oPPP + MOV (tracked games) ────────────────────────────
    if adv and adv.get("game_log"):
        st.markdown("<div class='section-hdr'>PPP & oPPP — Tracked Games</div>",
                    unsafe_allow_html=True)

        _gl3        = adv["game_log"]
        _gl3_labels = []
        for entry in _gl3:
            try:
                _dl4 = datetime.strptime(entry["date"], "%Y-%m-%d").strftime("%b %d")
            except Exception:
                _dl4 = entry.get("date", "—")
            _gl3_labels.append(f"{_dl4} vs {entry['opp']}")

        _gl3_mov    = [e["margin"] for e in _gl3]
        _gl3_ppp    = [round(e["ortg"] / 100, 3) for e in _gl3]
        _gl3_oppp   = [round(e["drtg"] / 100, 3) for e in _gl3]
        _colors_gl3 = ["#2ecc71" if m >= 0 else "#e74c3c" for m in _gl3_mov]

        fig_c3 = go.Figure()
        fig_c3.add_trace(go.Bar(
            x=_gl3_labels, y=_gl3_mov,
            name="MOV", marker_color=_colors_gl3,
            opacity=0.45, yaxis="y1",
            hovertemplate="%{x}<br>MOV: %{y:+.0f}<extra></extra>",
        ))
        fig_c3.add_trace(go.Scatter(
            x=_gl3_labels, y=_gl3_ppp,
            name="PPP", mode="lines+markers",
            line=dict(color="#f0a500", width=2),
            marker=dict(size=6), yaxis="y2",
            hovertemplate="%{x}<br>PPP: %{y:.3f}<extra></extra>",
        ))
        fig_c3.add_trace(go.Scatter(
            x=_gl3_labels, y=_gl3_oppp,
            name="oPPP", mode="lines+markers",
            line=dict(color="#e74c3c", width=2, dash="dot"),
            marker=dict(size=6), yaxis="y2",
            hovertemplate="%{x}<br>oPPP: %{y:.3f}<extra></extra>",
        ))
        fig_c3.update_layout(
            **PLOT_LAYOUT,
            title="Points Per Possession (Offense & Defense) with Margin of Victory",
            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
            yaxis=dict(title="MOV", zeroline=True, zerolinecolor="#444",
                       zerolinewidth=1, showgrid=False),
            yaxis2=dict(title="PPP", overlaying="y", side="right",
                        showgrid=True, gridcolor="#21262d"),
            legend=dict(orientation="h", y=-0.2),
            height=400,
        )
        st.plotly_chart(fig_c3, use_container_width=True)

    # ── Roster Stats Table ────────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Roster — Full Stats</div>", unsafe_allow_html=True)

    _all_rankings = compute_player_rankings()
    if not _all_rankings.empty and "pid" in _all_rankings.columns:
        # Filter to players on this team who are not archived
        _team_pids = {r["id"] for r in query(
            "SELECT id FROM players WHERE team_id=? AND archived=0", (team_id,))}
        _team_stats = _all_rankings[_all_rankings["pid"].isin(_team_pids)].copy()
    else:
        _team_stats = pd.DataFrame()

    if not _team_stats.empty:
        # Drop lookup-only / cross-team columns, keep everything stat-related
        _drop_cols = [c for c in ["pid", "Team", "Class", "Gender"] if c in _team_stats.columns]
        _team_stats = _team_stats.drop(columns=_drop_cols)

        # Sort by PTS descending so top scorers appear first
        if "PTS" in _team_stats.columns:
            _team_stats = _team_stats.sort_values("PTS", ascending=False)

        _col_order = [
            "Player", "#", "GP", "MIN",
            # per-game counting
            "PTS", "REB", "AST", "OREB", "DREB", "STL", "BLK", "TOV", "PF",
            # shooting efficiency
            "FGM", "FGA", "FG%", "2PM", "2PA", "2P%",
            "3PM", "3PA", "3P%", "FTM", "FTA", "FT%",
            "eFG%", "TS%", "FTr", "3PAr",
            # scoring composites
            "PTS32", "PPS", "PPSA", "Q4 PPG",
            # playmaking / ball-handling
            "SC", "SCS", "SCP", "SCO", "SCS%", "SCP%", "SCO%", "ShotRat",
            "AST%", "AST/TOV", "TOV%", "USG",
            # rebounding rates
            "OREB%", "DREB%", "TRB%",
            # paint
            "PaintFGA", "PaintFGM", "PaintFG%",
            # defense
            "DSh%", "Stocks",
            # per-32
            "REB32", "AST32", "STL32", "BLK32", "TOV32", "SC32",
            "SCS32", "SCP32", "SCO32",
            # composites
            "+/-", "GS", "EFF", "FIC", "PRF",
        ]
        _ordered = [c for c in _col_order if c in _team_stats.columns]
        _remaining = [c for c in _team_stats.columns if c not in _ordered]
        _team_stats = _team_stats[_ordered + _remaining]

        # Format percentage columns to show one decimal
        _pct_cols = [c for c in _team_stats.columns if "%" in c]
        for _pc in _pct_cols:
            _team_stats[_pc] = _team_stats[_pc].apply(
                lambda v: f"{v:.1f}" if pd.notna(v) else "—")

        st.dataframe(_team_stats, use_container_width=True, hide_index=True)

        with st.expander("Column legend", expanded=False):
            st.markdown("""
| Column | Description |
|--------|-------------|
| MIN | Avg minutes per game (possession-time based) |
| eFG% | Effective FG% — accounts for 3-pt value |
| TS% | True Shooting % — includes FTs |
| FTr | Free Throw Rate (FTA / FGA) |
| 3PAr | 3-Point Attempt Rate (3PA / FGA %) |
| PPS | Points Per Shot |
| PPSA | Points Per Scoring Attempt (FGA + 0.44×FTA) |
| SC | Shot Creations (shooter + passer + creator) |
| SCS/SCP/SCO | Shot Creations as Shooter / Passer / Off-ball creator |
| ShotRat | Shot quality rating (zone + creation context) |
| AST% | % of teammate made FGs assisted while on court |
| AST/TOV | Assist-to-Turnover ratio |
| TOV% | Turnover rate (TOV / possessions used) |
| USG | Usage volume per game |
| OREB%/DREB%/TRB% | Rebound rate vs available opportunities |
| PaintFGA/FGM/FG% | Zone-C 2PT paint shots |
| DSh% | % of opponent shots where player was the listed defender |
| Stocks | Steals + Blocks per game |
| Per-32 cols | Stats extrapolated to 32 minutes |
| GS | Game Score (Hollinger) |
| EFF | NBA Efficiency (PTS+REB+AST+STL+BLK − misses − TOV) |
| FIC | Floor Impact Counter (weighted composite) |
| PRF | Points Responsible For (PTS + AST×2) |
""")
    else:
        _roster = query(
            "SELECT name, number FROM players WHERE team_id=? AND archived=0 ORDER BY number",
            (team_id,))
        if _roster:
            st.info("No tracked game data yet — showing roster only.")
            _roster_df = pd.DataFrame(_roster)
            _roster_df.columns = ["Name", "#"]
            st.dataframe(_roster_df, use_container_width=True, hide_index=True)
        else:
            st.info("No roster data available.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════
with tab_sc:
    _sched_rows = query("""
        SELECT g.id, g.date, g.team1_id, g.team2_id,
               g.home_score, g.away_score, g.tracked, g.location,
               t1.name AS t1_name, t2.name AS t2_name
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE g.team1_id = ? OR g.team2_id = ?
        ORDER BY g.date DESC
    """, (team_id, team_id))

    if not _sched_rows:
        st.info("No games found for this team.")
    else:
        _completed   = [g for g in _sched_rows if g["home_score"] is not None and g["away_score"] is not None]
        _upcoming    = [g for g in _sched_rows if g["home_score"] is None or g["away_score"] is None]
        _sc_w = sum(1 for g in _completed if (
            (g["team1_id"] == team_id and g["home_score"] > g["away_score"]) or
            (g["team2_id"] == team_id and g["away_score"] > g["home_score"])
        ))
        _sc_l = len(_completed) - _sc_w

        _sc_cols = st.columns(3)
        _sc_cols[0].metric("Games Played",  len(_completed))
        _sc_cols[1].metric("Record",        f"{_sc_w}–{_sc_l}")
        _sc_cols[2].metric("Upcoming",      len(_upcoming))

        st.markdown("---")

        # ── Completed games ───────────────────────────────────────────────────
        if _completed:
            st.markdown("<div class='section-hdr'>Results</div>", unsafe_allow_html=True)
            for _sg in _completed:
                _is_home = _sg["team1_id"] == team_id
                _opp_sc  = _sg["t2_name"] if _is_home else _sg["t1_name"]
                _my_pts  = (_sg["home_score"] if _is_home else _sg["away_score"]) or 0
                _op_pts  = (_sg["away_score"] if _is_home else _sg["home_score"]) or 0
                _ha_lbl  = "vs" if _is_home else "@"
                _won     = _my_pts > _op_pts
                _wl_col  = "#2ecc71" if _won else "#e74c3c"
                _wl_txt  = "W" if _won else "L"
                _tracked = bool(_sg["tracked"])
                _trk_badge = (
                    "<span style='background:#1f3a1f;border:1px solid #2ecc71;"
                    "border-radius:4px;padding:1px 6px;font-size:10px;color:#2ecc71;"
                    "font-weight:700;margin-left:6px'>TRACKED</span>"
                    if _tracked else ""
                )
                try:
                    _dl = datetime.strptime(_sg["date"], "%Y-%m-%d").strftime("%b %d, %Y")
                except Exception:
                    _dl = _sg["date"] or "—"
                _loc_str = f" · {_sg['location']}" if _sg.get("location") else ""

                st.markdown(
                    f"<div style='background:#161b22;border:1px solid #30363d;"
                    f"border-radius:10px;padding:12px 16px;margin-bottom:6px'>"
                    f"<div style='display:flex;align-items:center;justify-content:space-between'>"
                    f"<div>"
                    f"<span style='color:#8b949e;font-size:11px'>{_dl}{_loc_str}</span>"
                    f"<div style='margin-top:4px'>"
                    f"<span style='color:#8b949e;font-size:12px'>{_ha_lbl} </span>"
                    f"<span style='color:#f0f6fc;font-weight:700;font-size:14px'>{_opp_sc}</span>"
                    f"{_trk_badge}"
                    f"</div>"
                    f"</div>"
                    f"<div style='text-align:right'>"
                    f"<span style='color:{_wl_col};font-weight:900;font-size:18px'>{_wl_txt}</span>"
                    f"<span style='color:#f0a500;font-weight:800;font-size:16px;margin-left:10px'>{_my_pts}</span>"
                    f"<span style='color:#8b949e;font-size:13px'> – </span>"
                    f"<span style='color:#555d68;font-weight:700;font-size:16px'>{_op_pts}</span>"
                    f"</div>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                if _tracked:
                    with st.expander("View Box Score", expanded=False):
                        _bsr1, _bsr2, _gi = compute_game_box_score(_sg["id"])
                        if any(not r.get("_totals") for r in _bsr1 + _bsr2):
                            show_game_box_score(_bsr1, _bsr2, {}, _gi, _cfg)
                        else:
                            st.info("Box score data not available for this game.")

        # ── Upcoming games ────────────────────────────────────────────────────
        if _upcoming:
            st.markdown("<div class='section-hdr'>Upcoming</div>", unsafe_allow_html=True)
            for _sg in sorted(_upcoming, key=lambda g: pd.to_datetime(g["date"], format="mixed", errors="coerce")):
                _is_home = _sg["team1_id"] == team_id
                _opp_sc  = _sg["t2_name"] if _is_home else _sg["t1_name"]
                _ha_lbl  = "vs" if _is_home else "@"
                try:
                    _dl = datetime.strptime(_sg["date"], "%Y-%m-%d").strftime("%b %d, %Y")
                except Exception:
                    _dl = _sg["date"] or "—"
                _loc_str = f" · {_sg['location']}" if _sg.get("location") else ""

                st.markdown(
                    f"<div style='background:#0d1117;border:1px solid #30363d;"
                    f"border-radius:10px;padding:12px 16px;margin-bottom:6px'>"
                    f"<span style='color:#8b949e;font-size:11px'>{_dl}{_loc_str}</span>"
                    f"<div style='margin-top:4px'>"
                    f"<span style='color:#8b949e;font-size:12px'>{_ha_lbl} </span>"
                    f"<span style='color:#c9d1d9;font-weight:700;font-size:14px'>{_opp_sc}</span>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — ANALYTICS  (tracked deep-dive)
# ══════════════════════════════════════════════════════════════════════════════
with tab_an:
    if not adv:
        st.info(f"No tracked game data for {sel_name} yet.")
    else:
        sub_big4, sub_scoring, sub_shooting, sub_reb, sub_defense, sub_trends = st.tabs([
            "🏆 The Big 4", "📈 Scoring", "🎯 Shooting", "🏀 Rebounding",
            "🛡️ Defense", "📉 Trends"
        ])

        # ── THE BIG 4 ────────────────────────────────────────────────────────
        with sub_big4:
            st.markdown(
                f"<div style='text-align:center;padding:8px 0 18px'>"
                f"<div style='font-size:28px;font-weight:900;color:#f0a500;letter-spacing:2px'>"
                f"THE BIG FOUR</div>"
                f"<div style='font-size:13px;color:#8b949e;margin-top:4px'>"
                f"Dean Oliver's four factors — the pillars of winning basketball</div>"
                f"</div>", unsafe_allow_html=True)

            _lg_ff = compute_league_four_factors()

            # Big 4 metrics
            _efg_t  = adv["efg"]  * 100
            _efg_o  = adv["oefg"] * 100
            _tov_t  = adv["tov_r"] * 100
            _opp_tv = adv.get("opp_tov_r", 0) * 100
            _oreb_t = adv["oreb_p"] * 100
            _oreb_o = adv.get("opp_oreb_p", 0) * 100
            _ftr_t  = adv["ft_r"]
            _ftr_o  = adv.get("opp_ft_r", 0)

            def _big4_bar(team_val, opp_val, team_higher_is_better=True):
                _max = max(team_val, opp_val, 0.001)
                _t_w = min(100, team_val / _max * 100)
                _o_w = min(100, opp_val  / _max * 100)
                _t_better = (team_val >= opp_val) == team_higher_is_better
                _t_border = "border:2px solid #2ecc71;" if _t_better else ""
                _o_border = "border:2px solid #2ecc71;" if not _t_better else ""
                return _t_w, _o_w, _t_border, _o_border

            _b4_data = [
                ("eFG%", "Effective FG%",
                 f"{_efg_t:.1f}%", f"{_efg_o:.1f}%",
                 _efg_t, _efg_o, True,
                 "Adjusts FG% for the extra value of 3-pointers. Higher = better shooting."),
                ("TOV%", "Turnover Rate",
                 f"{_tov_t:.1f}%", f"{_opp_tv:.1f}%",
                 _tov_t, _opp_tv, False,
                 "% of possessions ending in a turnover. Lower = better ball security."),
                ("OREB%", "Offensive Rebounding",
                 f"{_oreb_t:.1f}%", f"{_oreb_o:.1f}%",
                 _oreb_t, _oreb_o, True,
                 "% of missed shots recovered offensively. Higher = more second chances."),
                ("FT Rate", "Free Throw Rate",
                 f"{_ftr_t:.3f}", f"{_ftr_o:.3f}",
                 _ftr_t, _ftr_o, True,
                 "FTA per FGA — how often the team gets to the line vs. forces fouls."),
            ]

            b4cols = st.columns(4)
            for col, (abbr, name, t_val, o_val, tv, ov, hib, desc) in zip(b4cols, _b4_data):
                _tw, _ow, _tb, _ob = _big4_bar(tv, ov, hib)
                _winner = t_val if (tv >= ov) == hib else o_val
                col.markdown(
                    f"<div class='big4-card' style='{_tb}'>"
                    f"<div class='big4-label'>{name}</div>"
                    f"<div style='display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:4px'>"
                    f"<div style='text-align:left'>"
                    f"<div style='font-size:11px;color:#8b949e'>US</div>"
                    f"<div class='big4-team'>{t_val}</div>"
                    f"</div>"
                    f"<div style='font-size:22px;color:#30363d;font-weight:900'>vs</div>"
                    f"<div style='text-align:right'>"
                    f"<div style='font-size:11px;color:#8b949e'>OPP</div>"
                    f"<div class='big4-opp'>{o_val}</div>"
                    f"</div>"
                    f"</div>"
                    f"<div style='display:flex;gap:4px;margin:8px 0 4px'>"
                    f"<div style='flex:1'>"
                    f"<div class='big4-bar-wrap'><div class='big4-bar-t' style='width:{_tw:.0f}%'></div></div>"
                    f"</div>"
                    f"<div style='flex:1'>"
                    f"<div class='big4-bar-wrap'><div class='big4-bar-o' style='width:{_ow:.0f}%'></div></div>"
                    f"</div>"
                    f"</div>"
                    f"<div class='big4-sub'>{desc}</div>"
                    f"</div>", unsafe_allow_html=True)

            st.write("")
            show_four_factors_bars(adv, _lg_ff)

            # ORtg / DRtg / Net
            st.markdown("<div class='section-hdr'>Efficiency Ratings</div>", unsafe_allow_html=True)
            _r_cols = st.columns(5)
            for _rc, (lbl, val, sub) in zip(_r_cols, [
                ("ORtg",    f"{adv['ortg']:.1f}",                 "pts scored per 100 poss"),
                ("DRtg",    f"{adv['drtg']:.1f}",                 "pts allowed per 100 poss"),
                ("Net Rtg", f"{adv['ortg']-adv['drtg']:+.1f}",    "ORtg − DRtg"),
                ("PPP",     f"{adv['ppp']:.3f}",                   "pts per possession"),
                ("Pace",    f"{adv['pace']:.1f}",                  "possessions per game"),
            ]):
                _rc.markdown(
                    f"<div class='adv-tile'>"
                    f"<div class='adv-label'>{lbl}</div>"
                    f"<div class='adv-value'>{val}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                    f"</div>", unsafe_allow_html=True)

        # ── SCORING ──────────────────────────────────────────────────────────
        with sub_scoring:
            st.markdown("<div class='section-hdr'>Scoring Overview</div>", unsafe_allow_html=True)

            _sc_cols = st.columns(4)
            for _sc, (lbl, val, sub) in zip(_sc_cols, [
                ("PPG",    f"{adv['pts_pg']:.1f}",         "tracked avg"),
                ("TS%",    f"{adv['ts']*100:.1f}%",        "true shooting"),
                ("FG%",    f"{adv['fgp']*100:.1f}%",       "field goal %"),
                ("3P%",    f"{adv['tpp']*100:.1f}%",       "three-point %"),
            ]):
                _sc.markdown(
                    f"<div class='adv-tile'>"
                    f"<div class='adv-label'>{lbl}</div>"
                    f"<div class='adv-value'>{val}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                    f"</div>", unsafe_allow_html=True)

            st.write("")

            # Points distribution
            _dc1, _dc2 = st.columns(2)
            with _dc1:
                st.markdown("<div class='section-hdr'>Points Distribution</div>", unsafe_allow_html=True)
                _tot_pts_vals = [
                    adv.get("pct_from_2", 0),
                    adv.get("pct_from_3", 0),
                    adv.get("pct_from_ft", 0),
                ]
                if sum(_tot_pts_vals) > 0:
                    fig_pie = go.Figure(go.Pie(
                        labels=["2PT", "3PT", "Free Throws"],
                        values=_tot_pts_vals,
                        hole=0.52,
                        marker_colors=["#f0a500", "#3498db", "#2ecc71"],
                        textinfo="label+percent",
                        textfont_size=11,
                    ))
                    fig_pie.update_layout(**PLOT_LAYOUT, title="% of Total Points by Type", height=320)
                    st.plotly_chart(fig_pie, use_container_width=True)

            with _dc2:
                st.markdown("<div class='section-hdr'>Assisted vs Self-Created</div>",
                            unsafe_allow_html=True)
                _total_a = sum(adv.get(f"ast_q{q}_fga", 0) for q in range(1, 5))
                _total_s = sum(adv.get(f"sc_q{q}_fga", 0) for q in range(1, 5))
                if _total_a + _total_s > 0:
                    fig_asi = go.Figure(go.Pie(
                        labels=["Assisted FGA", "Self-Created FGA"],
                        values=[_total_a, _total_s],
                        hole=0.52,
                        marker_colors=["#58a6ff", "#e67e22"],
                        textinfo="label+percent",
                        textfont_size=11,
                    ))
                    fig_asi.update_layout(**PLOT_LAYOUT, title="Shot Creation Split", height=320)
                    st.plotly_chart(fig_asi, use_container_width=True)

            # Additional scoring metrics
            st.markdown("<div class='section-hdr'>Scoring Breakdown</div>", unsafe_allow_html=True)
            _sb_cols = st.columns(5)
            for _sb, (lbl, val, sub) in zip(_sb_cols, [
                ("AST%",   f"{adv.get('ast_pct', 0):.1f}%",     "assisted FGM"),
                ("Paint PPG", f"{adv.get('paint_pts_pg', 0):.1f}", "paint pts/game"),
                ("Paint FG%", f"{adv.get('paint_fg_p', 0)*100:.1f}%", "paint FG%"),
                ("SCE",    f"{adv.get('team_sce', 0):.3f}",      "shot creation eff"),
                ("AST/TOV",f"{adv.get('ast_tov_r', 0):.2f}",    "assist/turnover"),
            ]):
                _sb.markdown(
                    f"<div class='adv-tile'>"
                    f"<div class='adv-label'>{lbl}</div>"
                    f"<div class='adv-value'>{val}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                    f"</div>", unsafe_allow_html=True)

            # Game-by-game PPP trend in wins vs losses
            _gl = adv.get("game_log", [])
            if len(_gl) >= 2:
                st.markdown("<div class='section-hdr'>Game Trends</div>", unsafe_allow_html=True)
                show_trend_chart(_gl, sel_name)

            # ── Scoring by Quarter & Half ─────────────────────────────────
            st.markdown("<div class='section-hdr'>Scoring by Quarter & Half</div>",
                        unsafe_allow_html=True)
            _sc_opp_full = (adv["drtg"] / 100) * adv.get("poss_pg", adv["pace"])
            _sc_q_periods = [
                ("Q1",  adv["q1_pts_pg"],  adv["opp_q1_pts_pg"],  adv["q1_ppp"],  adv["opp_q1_ppp"]),
                ("Q2",  adv["q2_pts_pg"],  adv["opp_q2_pts_pg"],  adv["q2_ppp"],  adv["opp_q2_ppp"]),
                ("H1",  adv["h1_pts_pg"],  adv["opp_h1_pts_pg"],  adv["h1_ppp"],  adv["opp_h1_ppp"]),
                ("Q3",  adv["q3_pts_pg"],  adv["opp_q3_pts_pg"],  adv["q3_ppp"],  adv["opp_q3_ppp"]),
                ("Q4",  adv["q4_pts_pg"],  adv["opp_q4_pts_pg"],  adv["q4_ppp"],  adv["opp_q4_ppp"]),
                ("H2",  adv["h2_pts_pg"],  adv["opp_h2_pts_pg"],  adv["h2_ppp"],  adv["opp_h2_ppp"]),
                ("Full", adv["pts_pg"],    _sc_opp_full,           adv["ppp"],     adv["drtg"] / 100),
            ]
            _sc_qb_rows = []
            for _prd, _tppg, _oppg, _tppp, _oppp in _sc_q_periods:
                _sc_qb_rows.append({
                    "Period":   _prd,
                    "Team PPG": round(_tppg, 1),
                    "Opp PPG":  round(_oppg, 1),
                    "Margin":   f"{_tppg - _oppg:+.1f}",
                    "Team PPP": round(_tppp, 3),
                    "Opp PPP":  round(_oppp, 3),
                    "Edge":     "✓" if _tppp > _oppp else "✗",
                })
            st.dataframe(pd.DataFrame(_sc_qb_rows), use_container_width=True, hide_index=True)

            _ql_sc = ["Q1", "Q2", "Q3", "Q4"]
            _sc_q2cols = st.columns(2)
            with _sc_q2cols[0]:
                fig_sc_qppg = go.Figure()
                fig_sc_qppg.add_trace(go.Bar(
                    name=sel_name, x=_ql_sc,
                    y=[adv["q1_pts_pg"], adv["q2_pts_pg"],
                       adv["q3_pts_pg"], adv["q4_pts_pg"]],
                    marker_color="#f0a500"))
                fig_sc_qppg.add_trace(go.Bar(
                    name="Opponent", x=_ql_sc,
                    y=[adv["opp_q1_pts_pg"], adv["opp_q2_pts_pg"],
                       adv["opp_q3_pts_pg"], adv["opp_q4_pts_pg"]],
                    marker_color="#e74c3c"))
                fig_sc_qppg.update_layout(
                    **PLOT_LAYOUT, title="Points Per Game by Quarter", barmode="group",
                    yaxis_title="PPG", height=320)
                st.plotly_chart(fig_sc_qppg, use_container_width=True)
            with _sc_q2cols[1]:
                fig_sc_qppp = go.Figure()
                fig_sc_qppp.add_trace(go.Bar(
                    name=sel_name, x=_ql_sc,
                    y=[adv["q1_ppp"], adv["q2_ppp"], adv["q3_ppp"], adv["q4_ppp"]],
                    marker_color="#f0a500"))
                fig_sc_qppp.add_trace(go.Bar(
                    name="Opponent", x=_ql_sc,
                    y=[adv["opp_q1_ppp"], adv["opp_q2_ppp"],
                       adv["opp_q3_ppp"], adv["opp_q4_ppp"]],
                    marker_color="#e74c3c"))
                fig_sc_qppp.update_layout(
                    **PLOT_LAYOUT, title="PPP by Quarter", barmode="group",
                    yaxis_title="Points Per Possession", height=320)
                st.plotly_chart(fig_sc_qppp, use_container_width=True)

            _sc_q_map = {"Q1": adv["q1_ppp"], "Q2": adv["q2_ppp"],
                         "Q3": adv["q3_ppp"], "Q4": adv["q4_ppp"]}
            _sc_best_q  = max(_sc_q_map, key=_sc_q_map.get)
            _sc_worst_q = min(_sc_q_map, key=_sc_q_map.get)
            st.info(
                f"Strongest quarter: **{_sc_best_q}** ({_sc_q_map[_sc_best_q]:.3f} PPP) · "
                f"Weakest: **{_sc_worst_q}** ({_sc_q_map[_sc_worst_q]:.3f} PPP)")

            # ── Scoring by Possession Length ──────────────────────────────
            _tb_data = adv.get("tb_data", [])
            if _tb_data:
                st.markdown("<div class='section-hdr'>Scoring by Possession Length</div>",
                            unsafe_allow_html=True)
                _tb_rows = []
                for _tbd in _tb_data:
                    _2pa = _tbd["fga"] - _tbd["tpa"]
                    _2pm = _tbd["fgm"] - _tbd["tpm"]
                    _tb_rows.append({
                        "Poss. Length": _tbd["label"],
                        "Poss":         _tbd["poss"],
                        "PPP":          f"{_tbd['pts']/_tbd['poss']:.3f}" if _tbd["poss"] else "—",
                        "2FG%":         f"{_2pm/_2pa*100:.1f}%"           if _2pa          else "—",
                        "3FG%":         f"{_tbd['tpm']/_tbd['tpa']*100:.1f}%" if _tbd["tpa"] else "—",
                        "AST%":         f"{_tbd['ast_fgm']/_tbd['fgm']*100:.1f}%" if _tbd["fgm"] else "—",
                    })
                st.dataframe(pd.DataFrame(_tb_rows), use_container_width=True, hide_index=True)

                with st.expander("By Quarter"):
                    _bq_rows = []
                    for _qi, _ql in enumerate(["Q1", "Q2", "Q3", "Q4"]):
                        for _tbd in _tb_data:
                            _qd  = _tbd["by_quarter"][_qi]
                            _q2pa = _qd["fga"] - _qd["tpa"]
                            _q2pm = _qd["fgm"] - _qd["tpm"]
                            _bq_rows.append({
                                "Quarter":      _ql,
                                "Poss. Length": _tbd["label"],
                                "Poss":         _qd["poss"],
                                "PPP":          f"{_qd['pts']/_qd['poss']:.3f}"      if _qd["poss"]   else "—",
                                "2FG%":         f"{_q2pm/_q2pa*100:.1f}%"            if _q2pa         else "—",
                                "3FG%":         f"{_qd['tpm']/_qd['tpa']*100:.1f}%" if _qd["tpa"]    else "—",
                                "AST%":         f"{_qd['ast_fgm']/_qd['fgm']*100:.1f}%" if _qd["fgm"] else "—",
                            })
                    st.dataframe(pd.DataFrame(_bq_rows), use_container_width=True, hide_index=True)

        # ── SHOOTING ─────────────────────────────────────────────────────────
        with sub_shooting:
            from collections import defaultdict as _dd

            # ── Pull all team shots with full context ─────────────────────
            _all_shots_raw = []
            _my_pids_sh    = set()
            _game_ids_sh   = []
            if tr_gs:
                _game_ids_sh = [g["id"] for g in tr_gs]
                _ph_sh = ",".join("?" * len(_game_ids_sh))
                _lp_sh = query(
                    f"SELECT game_id, player_id, team_id FROM game_lineup_players "
                    f"WHERE game_id IN ({_ph_sh})", tuple(_game_ids_sh))
                _my_pids_sh = {r["player_id"] for r in _lp_sh if r["team_id"] == team_id}
                if _my_pids_sh:
                    _all_shots_raw = query(
                        f"SELECT primary_player_id, pass_from_id, shot_created_by_id, "
                        f"shot_type, shot_result, zone, guarded_by_id "
                        f"FROM game_events "
                        f"WHERE game_id IN ({_ph_sh}) AND event_type='shot' "
                        f"AND primary_player_id IN ({','.join('?'*len(_my_pids_sh))})",
                        tuple(_game_ids_sh) + tuple(_my_pids_sh))

            # ── Team-level shooting metrics (incl. SCE) ───────────────────
            _two_pa   = adv.get("fga", 0) - adv.get("tpa", 0)
            _pts_fg   = adv.get("pts", 0) - adv.get("ftm", 0)
            _sce_denom = 2 * _two_pa + 3 * adv.get("tpa", 0)
            _sce_val  = _pts_fg / _sce_denom if _sce_denom else 0.0

            st.markdown("<div class='section-hdr'>Shooting Metrics</div>",
                        unsafe_allow_html=True)
            _sh_cols6 = st.columns(6)
            for _shc, (lbl, val, sub) in zip(_sh_cols6, [
                ("eFG%",    f"{adv['efg']*100:.1f}%",           "effective FG%"),
                ("Opp eFG%",f"{adv['oefg']*100:.1f}%",          "opp eFG%"),
                ("SCE",     f"{_sce_val:.3f}",                   "(pts−FT)÷(2×2PA+3×3PA)"),
                ("3P Rate", f"{adv['tpar']*100:.1f}%",           "3PA / FGA"),
                ("FT%",     f"{adv['ftp']*100:.1f}%",            "free throw %"),
                ("2P%",     f"{adv.get('two_pct',0)*100:.1f}%",  "two-point %"),
            ]):
                _shc.markdown(
                    f"<div class='adv-tile'>"
                    f"<div class='adv-label'>{lbl}</div>"
                    f"<div class='adv-value'>{val}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                    f"</div>", unsafe_allow_html=True)

            # ── Shooting % Overview chart ──────────────────────────────────
            st.markdown("<div class='section-hdr'>Shooting Percentages</div>",
                        unsafe_allow_html=True)
            show_shooting_pct_chart(adv, sel_name)

            # ── Team Shot Chart ────────────────────────────────────────────
            if _all_shots_raw:
                st.markdown("<div class='section-hdr'>Team Shot Chart</div>",
                            unsafe_allow_html=True)
                render_hot_zones(_all_shots_raw, title="Shot Zones (Tracked Games)")

            # ── Shot Creation Breakdown ────────────────────────────────────
            if _all_shots_raw:
                st.markdown("<div class='section-hdr'>Shot Creation Breakdown</div>",
                            unsafe_allow_html=True)
                st.caption(
                    "**Pass** = pass_from_id set (catch-and-shoot / off pass)  ·  "
                    "**Created** = shot_created_by_id set (screen / drive created the look)")

                def _creation_cat(s):
                    hp = s["pass_from_id"]    is not None
                    hc = s["shot_created_by_id"] is not None
                    if hp and hc: return "Both (Pass + Created)"
                    if hp:        return "Pass Only"
                    if hc:        return "Created Only"
                    return "Neither (Pure Self-Created)"

                def _agg_shots(shots):
                    fga  = len(shots)
                    fgm  = sum(1 for s in shots if s["shot_result"] == "make")
                    tpa  = sum(1 for s in shots if s["shot_type"] == 3)
                    tpm  = sum(1 for s in shots if s["shot_type"] == 3 and s["shot_result"] == "make")
                    twa  = fga - tpa
                    twm  = fgm - tpm
                    pts  = twm * 2 + tpm * 3
                    efg  = (fgm + 0.5 * tpm) / fga if fga else 0
                    ppp  = pts / fga if fga else 0
                    denom = twa * 2 + tpa * 3
                    sce  = pts / denom if denom else 0
                    return dict(fga=fga, fgm=fgm, fg_pct=fgm/fga if fga else 0,
                                tpa=tpa, tpm=tpm, tp_pct=tpm/tpa if tpa else 0,
                                twa=twa, twm=twm, tw_pct=twm/twa if twa else 0,
                                efg=efg, ppp=ppp, sce=sce, pts=pts)

                _cat_order = [
                    "Both (Pass + Created)",
                    "Pass Only",
                    "Created Only",
                    "Neither (Pure Self-Created)",
                ]
                _cat_shots = {c: [] for c in _cat_order}
                for _s in _all_shots_raw:
                    _cat_shots[_creation_cat(_s)].append(_s)

                # Summary table
                _crb_rows = []
                for _cat in _cat_order:
                    _a = _agg_shots(_cat_shots[_cat])
                    _crb_rows.append({
                        "Creation Type": _cat,
                        "FGA":  _a["fga"],  "FGM": _a["fgm"],
                        "FG%":  f"{_a['fg_pct']*100:.1f}%" if _a["fga"] else "—",
                        "2PA":  _a["twa"],  "2PM": _a["twm"],
                        "2P%":  f"{_a['tw_pct']*100:.1f}%" if _a["twa"] else "—",
                        "3PA":  _a["tpa"],  "3PM": _a["tpm"],
                        "3P%":  f"{_a['tp_pct']*100:.1f}%" if _a["tpa"] else "—",
                        "eFG%": f"{_a['efg']*100:.1f}%"   if _a["fga"] else "—",
                        "PPP":  f"{_a['ppp']:.3f}"         if _a["fga"] else "—",
                        "SCE":  f"{_a['sce']:.3f}"         if _a["fga"] else "—",
                    })
                _tot_a = _agg_shots(_all_shots_raw)
                _crb_rows.append({
                    "Creation Type": "TOTAL",
                    "FGA": _tot_a["fga"], "FGM": _tot_a["fgm"],
                    "FG%":  f"{_tot_a['fg_pct']*100:.1f}%",
                    "2PA":  _tot_a["twa"], "2PM": _tot_a["twm"],
                    "2P%":  f"{_tot_a['tw_pct']*100:.1f}%",
                    "3PA":  _tot_a["tpa"], "3PM": _tot_a["tpm"],
                    "3P%":  f"{_tot_a['tp_pct']*100:.1f}%",
                    "eFG%": f"{_tot_a['efg']*100:.1f}%",
                    "PPP":  f"{_tot_a['ppp']:.3f}",
                    "SCE":  f"{_tot_a['sce']:.3f}",
                })
                st.dataframe(pd.DataFrame(_crb_rows), use_container_width=True,
                             hide_index=True)

                # ── Charts: FGA split + FG% comparison ────────────────────
                _crb_chart_c1, _crb_chart_c2 = st.columns(2)
                _crb_colors = ["#3498db", "#2ecc71", "#f0a500", "#e74c3c"]
                _short_cats = ["Both", "Pass Only", "Created Only", "Neither"]

                with _crb_chart_c1:
                    _fig_crb_fga = go.Figure()
                    for _cat, _short, _clr in zip(_cat_order, _short_cats, _crb_colors):
                        _a = _agg_shots(_cat_shots[_cat])
                        _fig_crb_fga.add_trace(go.Bar(
                            name=_short,
                            x=["2PT", "3PT", "All FGA"],
                            y=[_a["twa"], _a["tpa"], _a["fga"]],
                            marker_color=_clr,
                        ))
                    _fig_crb_fga.update_layout(
                        **PLOT_LAYOUT, barmode="group",
                        title="FGA by Creation Type", yaxis_title="Attempts",
                        height=320, legend=dict(orientation="h", y=-0.25))
                    st.plotly_chart(_fig_crb_fga, use_container_width=True)

                with _crb_chart_c2:
                    _fig_crb_pct = go.Figure()
                    for _lbl_pct, _key_pct in [("FG%","fg_pct"),("2P%","tw_pct"),("3P%","tp_pct")]:
                        _pct_vals = []
                        for _cat in _cat_order:
                            _a = _agg_shots(_cat_shots[_cat])
                            _pct_vals.append(round(_a[_key_pct] * 100, 1))
                        _fig_crb_pct.add_trace(go.Bar(
                            name=_lbl_pct, x=_short_cats, y=_pct_vals))
                    _fig_crb_pct.update_layout(
                        **PLOT_LAYOUT, barmode="group",
                        title="FG% by Creation Type", yaxis_title="%",
                        height=320, legend=dict(orientation="h", y=-0.25))
                    st.plotly_chart(_fig_crb_pct, use_container_width=True)

                # PPP + SCE comparison
                _fig_eff = go.Figure()
                _ppp_vals = [round(_agg_shots(_cat_shots[c])["ppp"], 3) for c in _cat_order]
                _sce_vals = [round(_agg_shots(_cat_shots[c])["sce"], 3) for c in _cat_order]
                _fig_eff.add_trace(go.Bar(name="PPP", x=_short_cats, y=_ppp_vals,
                                          marker_color="#f0a500"))
                _fig_eff.add_trace(go.Bar(name="SCE", x=_short_cats, y=_sce_vals,
                                          marker_color="#3498db", opacity=0.8))
                _fig_eff.update_layout(
                    **PLOT_LAYOUT, barmode="group",
                    title="PPP & SCE by Creation Type",
                    yaxis_title="Efficiency", height=300,
                    legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(_fig_eff, use_container_width=True)

            # ── Zone Analysis ──────────────────────────────────────────────
            if _all_shots_raw:
                st.markdown("<div class='section-hdr'>Zone Analysis</div>",
                            unsafe_allow_html=True)

                _zone_agg = _dd(lambda: dict(
                    fga=0, fgm=0, tpa=0, tpm=0,
                    sr_sum=0.0, sr_n=0, xfg_sum=0.0, xfg_n=0))
                _pl_zone   = _dd(lambda: _dd(lambda: dict(fga=0, fgm=0)))

                for _s in _all_shots_raw:
                    _z  = _s["zone"]
                    _st = _s["shot_type"]
                    _mk = _s["shot_result"] == "make"
                    _cn = _s["guarded_by_id"] is not None
                    if not _z:
                        continue
                    _za = _zone_agg[_z]
                    _za["fga"] += 1
                    if _mk: _za["fgm"] += 1
                    if _st == 3:
                        _za["tpa"] += 1
                        if _mk: _za["tpm"] += 1
                    _zk = (_st, _z, _cn)
                    _sr = SHOT_RATING.get(_zk)
                    if _sr is not None:
                        _za["sr_sum"] += _sr; _za["sr_n"] += 1
                    _xf = EST_FGP.get(_zk)
                    if _xf is not None:
                        _za["xfg_sum"] += _xf; _za["xfg_n"] += 1
                    _pz = _pl_zone[_z][_s["primary_player_id"]]
                    _pz["fga"] += 1
                    if _mk: _pz["fgm"] += 1

                # Player name lookup
                _pid_names = {}
                _rstr = query(
                    "SELECT id, name, number FROM players "
                    "WHERE team_id=? AND archived=0", (team_id,))
                for _rp in (_rstr or []):
                    _pid_names[_rp["id"]] = f"#{_rp['number']} {_rp['name']}"

                _zone_rows = []
                for _z in ["C", "LC", "LW", "RW", "RC"]:
                    _za = _zone_agg.get(_z)
                    if not _za or _za["fga"] == 0:
                        continue
                    _fga = _za["fga"]; _fgm = _za["fgm"]
                    _avg_sr  = _za["sr_sum"]  / _za["sr_n"]  if _za["sr_n"]  else None
                    _avg_xfg = _za["xfg_sum"] / _za["xfg_n"] if _za["xfg_n"] else None

                    # Best / worst per zone (min 2 FGA)
                    _pz_list = [
                        (pid, d["fgm"] / d["fga"], d["fga"])
                        for pid, d in _pl_zone[_z].items() if d["fga"] >= 2
                    ]
                    _best  = max(_pz_list, key=lambda x: x[1]) if _pz_list else None
                    _worst = min(_pz_list, key=lambda x: x[1]) if _pz_list else None

                    _zone_rows.append({
                        "Zone":   _z,
                        "FGA":    _fga,  "FGM":    _fgm,
                        "FG%":    f"{_fgm/_fga*100:.1f}%",
                        "3PA":    _za["tpa"],
                        "3P%":    f"{_za['tpm']/_za['tpa']*100:.1f}%" if _za["tpa"] else "—",
                        "Avg SRat":  f"{_avg_sr:.2f}"       if _avg_sr  is not None else "—",
                        "Avg XFG%":  f"{_avg_xfg*100:.1f}%" if _avg_xfg is not None else "—",
                        "Best":  (f"{_pid_names.get(_best[0],'?')} "
                                  f"({_best[1]*100:.0f}%, {_best[2]} FGA)")  if _best  else "—",
                        "Worst": (f"{_pid_names.get(_worst[0],'?')} "
                                  f"({_worst[1]*100:.0f}%, {_worst[2]} FGA)") if _worst else "—",
                    })

                if _zone_rows:
                    st.dataframe(pd.DataFrame(_zone_rows), use_container_width=True,
                                 hide_index=True)
                    # Actual vs Expected FG% per zone
                    _zdf = pd.DataFrame(_zone_rows)
                    _z_actual = [float(v.replace("%","")) for v in _zdf["FG%"]]
                    _z_xfg    = [
                        float(v.replace("%","")) if v != "—" else 0
                        for v in _zdf["Avg XFG%"]
                    ]
                    _z_srat   = [
                        float(v) if v != "—" else 0
                        for v in _zdf["Avg SRat"]
                    ]
                    fig_zone_c1, fig_zone_c2 = st.columns(2)
                    with fig_zone_c1:
                        fig_fgpz = go.Figure()
                        fig_fgpz.add_trace(go.Bar(name="Actual FG%", x=_zdf["Zone"],
                                                   y=_z_actual, marker_color="#f0a500"))
                        fig_fgpz.add_trace(go.Bar(name="Avg XFG%", x=_zdf["Zone"],
                                                   y=_z_xfg, marker_color="#3498db",
                                                   opacity=0.75))
                        fig_fgpz.update_layout(
                            **PLOT_LAYOUT, barmode="group",
                            title="Actual vs Expected FG% by Zone",
                            yaxis_title="%", height=300,
                            legend=dict(orientation="h", y=-0.2))
                        st.plotly_chart(fig_fgpz, use_container_width=True)
                    with fig_zone_c2:
                        _z_fga = [row["FGA"] for row in _zone_rows]
                        fig_sratz = go.Figure()
                        fig_sratz.add_trace(go.Bar(
                            name="Avg Shot Rating", x=_zdf["Zone"],
                            y=_z_srat,
                            marker_color=[
                                "#2ecc71" if v >= 0.5 else
                                "#f0a500" if v >= 0    else "#e74c3c"
                                for v in _z_srat],
                            text=[f"{v:.2f}" for v in _z_srat],
                            textposition="outside",
                        ))
                        fig_sratz.update_layout(
                            **PLOT_LAYOUT,
                            title="Avg Shot Rating by Zone",
                            yaxis_title="Shot Rating", height=300)
                        st.plotly_chart(fig_sratz, use_container_width=True)

            # ── Player Shooting Comparison ─────────────────────────────────
            st.markdown("<div class='section-hdr'>Player Shooting Comparison</div>",
                        unsafe_allow_html=True)
            _rnk_all = compute_player_rankings()
            _team_shooters = pd.DataFrame()
            if not _rnk_all.empty and "Team" in _rnk_all.columns:
                _team_shooters = _rnk_all[_rnk_all["Team"] == sel_name].copy()
            if not _team_shooters.empty:
                _shoot_cols = ["Player", "GP", "PTS", "FG%", "3P%", "FT%",
                               "TS%", "eFG%", "ShotRat", "SC"]
                _show_sh = [c for c in _shoot_cols if c in _team_shooters.columns]
                st.dataframe(
                    _team_shooters[_show_sh].sort_values("PTS", ascending=False)
                    .reset_index(drop=True),
                    use_container_width=True, hide_index=True)
            else:
                st.info("No tracked player stats found for this team. "
                        "Players must be added to tracked game lineups to appear here.")

            # ── Shooting by Quarter ───────────────────────────────────────
            st.markdown("<div class='section-hdr'>Shooting by Quarter</div>",
                        unsafe_allow_html=True)

            def _sh_q_agg(quarters, pfx="both"):
                """Aggregate shooting for given quarters. pfx: 'ast', 'sc', or 'both'."""
                pfxs = ["ast", "sc"] if pfx == "both" else [pfx]
                fga = sum(adv.get(f"{p}_q{q}_fga", 0) for q in quarters for p in pfxs)
                fgm = sum(adv.get(f"{p}_q{q}_fgm", 0) for q in quarters for p in pfxs)
                tpa = sum(adv.get(f"{p}_q{q}_tpa", 0) for q in quarters for p in pfxs)
                tpm = sum(adv.get(f"{p}_q{q}_tpm", 0) for q in quarters for p in pfxs)
                return fga, fgm, tpa, tpm

            def _sh_q_row(label, fga, fgm, tpa, tpm, ppp):
                efg = (fgm + 0.5 * tpm) / fga if fga else 0
                return {
                    "Period": label,
                    "FGA": fga, "FGM": fgm,
                    "FG%":  f"{fgm / fga * 100:.1f}%"  if fga else "—",
                    "3PA": tpa, "3PM": tpm,
                    "3P%":  f"{tpm / tpa * 100:.1f}%"  if tpa else "—",
                    "eFG%": f"{efg * 100:.1f}%"        if fga else "—",
                    "PPP":  f"{ppp:.3f}",
                }

            _sh_q_table = []
            for _shq in [1, 2]:
                _a, _m, _ta, _tm = _sh_q_agg([_shq])
                _sh_q_table.append(_sh_q_row(f"Q{_shq}", _a, _m, _ta, _tm, adv.get(f"q{_shq}_ppp", 0)))
            _h1a, _h1m, _h1ta, _h1tm = _sh_q_agg([1, 2])
            _sh_q_table.append(_sh_q_row("H1", _h1a, _h1m, _h1ta, _h1tm, adv.get("h1_ppp", 0)))
            for _shq in [3, 4]:
                _a, _m, _ta, _tm = _sh_q_agg([_shq])
                _sh_q_table.append(_sh_q_row(f"Q{_shq}", _a, _m, _ta, _tm, adv.get(f"q{_shq}_ppp", 0)))
            _h2a, _h2m, _h2ta, _h2tm = _sh_q_agg([3, 4])
            _sh_q_table.append(_sh_q_row("H2", _h2a, _h2m, _h2ta, _h2tm, adv.get("h2_ppp", 0)))
            _tfa, _tfm, _tta, _ttm = _sh_q_agg([1, 2, 3, 4])
            _sh_q_table.append(_sh_q_row("Full", _tfa, _tfm, _tta, _ttm, adv.get("ppp", 0)))

            if _tfa:
                st.dataframe(pd.DataFrame(_sh_q_table), use_container_width=True, hide_index=True)

                _ql_sh = ["Q1", "Q2", "Q3", "Q4"]
                _sh_fg_vals, _sh_tp_vals, _sh_efg_vals = [], [], []
                for _shq in [1, 2, 3, 4]:
                    _a, _m, _ta, _tm = _sh_q_agg([_shq])
                    _sh_fg_vals.append(round(_m / _a * 100, 1) if _a else 0)
                    _sh_tp_vals.append(round(_tm / _ta * 100, 1) if _ta else 0)
                    _sh_efg_vals.append(round((_m + 0.5 * _tm) / _a * 100, 1) if _a else 0)

                fig_sh_q = go.Figure()
                fig_sh_q.add_trace(go.Bar(name="FG%",  x=_ql_sh, y=_sh_fg_vals,
                                          marker_color="#f0a500"))
                fig_sh_q.add_trace(go.Bar(name="3P%",  x=_ql_sh, y=_sh_tp_vals,
                                          marker_color="#3498db"))
                fig_sh_q.add_trace(go.Bar(name="eFG%", x=_ql_sh, y=_sh_efg_vals,
                                          marker_color="#2ecc71"))
                fig_sh_q.update_layout(
                    **PLOT_LAYOUT, barmode="group",
                    title="Shooting % by Quarter",
                    yaxis_title="%", height=320,
                    legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig_sh_q, use_container_width=True)

            # ── Off-Pass vs Self-Created by Quarter ───────────────────────
            st.markdown("<div class='section-hdr'>Off-Pass vs Self-Created by Quarter</div>",
                        unsafe_allow_html=True)

            def _creation_row(label, qs):
                aa, am, ata, atm = _sh_q_agg(qs, "ast")
                sa, sm, sta, stm = _sh_q_agg(qs, "sc")
                total_fga = aa + sa
                a_efg = (am + 0.5 * atm) / aa if aa else 0
                s_efg = (sm + 0.5 * stm) / sa if sa else 0
                return {
                    "Period":   label,
                    "Ast FGA":  aa,
                    "Ast FGM":  am,
                    "Ast FG%":  f"{am / aa * 100:.1f}%" if aa else "—",
                    "Ast 3PA":  ata,
                    "Ast 3P%":  f"{atm / ata * 100:.1f}%" if ata else "—",
                    "Ast eFG%": f"{a_efg * 100:.1f}%" if aa else "—",
                    "Ast%":     f"{aa / total_fga * 100:.1f}%" if total_fga else "—",
                    "SC FGA":   sa,
                    "SC FGM":   sm,
                    "SC FG%":   f"{sm / sa * 100:.1f}%" if sa else "—",
                    "SC 3PA":   sta,
                    "SC 3P%":   f"{stm / sta * 100:.1f}%" if sta else "—",
                    "SC eFG%":  f"{s_efg * 100:.1f}%" if sa else "—",
                    "SC%":      f"{sa / total_fga * 100:.1f}%" if total_fga else "—",
                }

            _cr_table = []
            for _cq in [1, 2, 3, 4]:
                _cr_table.append(_creation_row(f"Q{_cq}", [_cq]))
            _cr_table.append(_creation_row("H1",   [1, 2]))
            _cr_table.append(_creation_row("H2",   [3, 4]))
            _cr_table.append(_creation_row("Full", [1, 2, 3, 4]))

            _cr_total_fga = (
                sum(adv.get(f"ast_q{q}_fga", 0) for q in range(1, 5)) +
                sum(adv.get(f"sc_q{q}_fga",  0) for q in range(1, 5))
            )

            if _cr_total_fga:
                st.dataframe(pd.DataFrame(_cr_table), use_container_width=True, hide_index=True)

                _ql_cr = ["Q1", "Q2", "Q3", "Q4"]
                _ast_fga_q, _sc_fga_q = [], []
                _ast_efg_q, _sc_efg_q = [], []
                _ast_fg_q,  _sc_fg_q  = [], []
                _ast_3p_q,  _sc_3p_q  = [], []
                for _cq in [1, 2, 3, 4]:
                    _aa, _am, _ata, _atm = _sh_q_agg([_cq], "ast")
                    _sa, _sm, _sta, _stm = _sh_q_agg([_cq], "sc")
                    _ast_fga_q.append(_aa)
                    _sc_fga_q.append(_sa)
                    _ast_efg_q.append(round((_am + 0.5*_atm)/_aa*100, 1) if _aa else 0)
                    _sc_efg_q.append(round((_sm + 0.5*_stm)/_sa*100, 1)  if _sa else 0)
                    _ast_fg_q.append(round(_am/_aa*100, 1) if _aa else 0)
                    _sc_fg_q.append(round(_sm/_sa*100, 1)  if _sa else 0)
                    _ast_3p_q.append(round(_atm/_ata*100, 1) if _ata else 0)
                    _sc_3p_q.append(round(_stm/_sta*100, 1)  if _sta else 0)

                # Row 1 — volume split
                _cr_c1, _cr_c2 = st.columns(2)
                with _cr_c1:
                    fig_cr_vol = go.Figure()
                    fig_cr_vol.add_trace(go.Bar(
                        name="Off Pass", x=_ql_cr, y=_ast_fga_q,
                        marker_color="#3498db",
                        text=_ast_fga_q, textposition="inside"))
                    fig_cr_vol.add_trace(go.Bar(
                        name="Self-Created", x=_ql_cr, y=_sc_fga_q,
                        marker_color="#e74c3c",
                        text=_sc_fga_q, textposition="inside"))
                    fig_cr_vol.update_layout(
                        **PLOT_LAYOUT, barmode="stack",
                        title="FGA Volume by Quarter (Off-Pass vs SC)",
                        yaxis_title="FGA", height=320,
                        legend=dict(orientation="h", y=-0.2))
                    st.plotly_chart(fig_cr_vol, use_container_width=True)

                with _cr_c2:
                    _ast_pct_q = [
                        round(_ast_fga_q[i] / (_ast_fga_q[i] + _sc_fga_q[i]) * 100, 1)
                        if (_ast_fga_q[i] + _sc_fga_q[i]) else 0
                        for i in range(4)
                    ]
                    _sc_pct_q = [round(100 - v, 1) for v in _ast_pct_q]
                    fig_cr_mix = go.Figure()
                    fig_cr_mix.add_trace(go.Bar(
                        name="Off Pass %", x=_ql_cr, y=_ast_pct_q,
                        marker_color="#3498db",
                        text=[f"{v:.0f}%" for v in _ast_pct_q],
                        textposition="inside"))
                    fig_cr_mix.add_trace(go.Bar(
                        name="SC %", x=_ql_cr, y=_sc_pct_q,
                        marker_color="#e74c3c",
                        text=[f"{v:.0f}%" for v in _sc_pct_q],
                        textposition="inside"))
                    fig_cr_mix.update_layout(
                        **PLOT_LAYOUT, barmode="stack",
                        title="Shot Creation Mix % by Quarter",
                        yaxis_title="%", height=320,
                        legend=dict(orientation="h", y=-0.2))
                    st.plotly_chart(fig_cr_mix, use_container_width=True)

                # Row 2 — efficiency
                _cr_c3, _cr_c4 = st.columns(2)
                with _cr_c3:
                    fig_cr_efg = go.Figure()
                    fig_cr_efg.add_trace(go.Bar(
                        name="Off Pass eFG%", x=_ql_cr, y=_ast_efg_q,
                        marker_color="#3498db",
                        text=[f"{v:.1f}%" for v in _ast_efg_q],
                        textposition="outside"))
                    fig_cr_efg.add_trace(go.Bar(
                        name="SC eFG%", x=_ql_cr, y=_sc_efg_q,
                        marker_color="#e74c3c",
                        text=[f"{v:.1f}%" for v in _sc_efg_q],
                        textposition="outside"))
                    fig_cr_efg.update_layout(
                        **PLOT_LAYOUT, barmode="group",
                        title="eFG% by Quarter — Off-Pass vs SC",
                        yaxis_title="%", height=320,
                        legend=dict(orientation="h", y=-0.2))
                    st.plotly_chart(fig_cr_efg, use_container_width=True)

                with _cr_c4:
                    fig_cr_fg = go.Figure()
                    fig_cr_fg.add_trace(go.Bar(
                        name="Off Pass FG%", x=_ql_cr, y=_ast_fg_q,
                        marker_color="#3498db",
                        text=[f"{v:.1f}%" for v in _ast_fg_q],
                        textposition="outside"))
                    fig_cr_fg.add_trace(go.Bar(
                        name="SC FG%", x=_ql_cr, y=_sc_fg_q,
                        marker_color="#e74c3c",
                        text=[f"{v:.1f}%" for v in _sc_fg_q],
                        textposition="outside"))
                    fig_cr_fg.update_layout(
                        **PLOT_LAYOUT, barmode="group",
                        title="FG% by Quarter — Off-Pass vs SC",
                        yaxis_title="%", height=320,
                        legend=dict(orientation="h", y=-0.2))
                    st.plotly_chart(fig_cr_fg, use_container_width=True)

                # Row 3 — 3P%
                fig_cr_3p = go.Figure()
                fig_cr_3p.add_trace(go.Bar(
                    name="Off Pass 3P%", x=_ql_cr, y=_ast_3p_q,
                    marker_color="#3498db",
                    text=[f"{v:.1f}%" for v in _ast_3p_q],
                    textposition="outside"))
                fig_cr_3p.add_trace(go.Bar(
                    name="SC 3P%", x=_ql_cr, y=_sc_3p_q,
                    marker_color="#e74c3c",
                    text=[f"{v:.1f}%" for v in _sc_3p_q],
                    textposition="outside"))
                fig_cr_3p.update_layout(
                    **PLOT_LAYOUT, barmode="group",
                    title="3P% by Quarter — Off-Pass vs SC",
                    yaxis_title="%", height=300,
                    legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig_cr_3p, use_container_width=True)

                # Summary insight line
                _fa_aa, _fa_am, _fa_ata, _fa_atm = _sh_q_agg([1,2,3,4], "ast")
                _fa_sa, _fa_sm, _fa_sta, _fa_stm = _sh_q_agg([1,2,3,4], "sc")
                _fa_tot = _fa_aa + _fa_sa
                if _fa_tot:
                    _fa_a_efg = (_fa_am + 0.5*_fa_atm)/_fa_aa*100 if _fa_aa else 0
                    _fa_s_efg = (_fa_sm + 0.5*_fa_stm)/_fa_sa*100 if _fa_sa else 0
                    st.info(
                        f"**Season split:** {_fa_aa/_fa_tot*100:.1f}% off-pass "
                        f"({_fa_aa} FGA · {_fa_a_efg:.1f}% eFG%) · "
                        f"{_fa_sa/_fa_tot*100:.1f}% self-created "
                        f"({_fa_sa} FGA · {_fa_s_efg:.1f}% eFG%)"
                    )

        # ── REBOUNDING ───────────────────────────────────────────────────────
        with sub_reb:
            st.markdown("<div class='section-hdr'>Rebounding</div>", unsafe_allow_html=True)

            _rb_cols = st.columns(5)
            for _rbc, (lbl, val, sub) in zip(_rb_cols, [
                ("OREB%",  f"{adv['oreb_p']*100:.1f}%",         "off reb rate"),
                ("DREB%",  f"{adv.get('dreb_p',0)*100:.1f}%",   "def reb rate"),
                ("OREB/G", f"{adv.get('oreb_pg',0):.1f}",        "off reb / game"),
                ("DREB/G", f"{adv.get('dreb_pg',0):.1f}",        "def reb / game"),
                ("STL%",   f"{adv.get('stl_rate',0):.1f}%",      "steal rate"),
            ]):
                _rbc.markdown(
                    f"<div class='adv-tile'>"
                    f"<div class='adv-label'>{lbl}</div>"
                    f"<div class='adv-value'>{val}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                    f"</div>", unsafe_allow_html=True)

            st.write("")

            # Per-game rebounding for each player
            st.markdown("<div class='section-hdr'>Player Rebounding Leaders</div>",
                        unsafe_allow_html=True)
            _rnk_all2 = compute_player_rankings()
            if not _rnk_all2.empty and "Team" in _rnk_all2.columns:
                _team_reb = _rnk_all2[_rnk_all2["Team"] == sel_name].copy()
                if not _team_reb.empty:
                    _reb_cols = ["Player", "GP", "REB", "OREB", "DREB", "BLK", "STL"]
                    _show_reb = [c for c in _reb_cols if c in _team_reb.columns]
                    st.dataframe(
                        _team_reb[_show_reb].sort_values("REB", ascending=False)
                        .reset_index(drop=True),
                        use_container_width=True, hide_index=True)

            # Opp rebounding context
            st.markdown("<div class='section-hdr'>Defensive Rebounding Context</div>",
                        unsafe_allow_html=True)
            _dr2_cols = st.columns(4)
            for _dr2c, (lbl, val, sub) in zip(_dr2_cols, [
                ("Opp OREB%",  f"{adv.get('opp_oreb_p',0)*100:.1f}%", "opp off reb rate"),
                ("BLK Rate",   f"{adv.get('blk_rate',0):.1f}%",       "% opp 2PA blocked"),
                ("Opp TOV%",   f"{adv.get('opp_tov_r',0)*100:.1f}%",  "forced turnover rate"),
                ("STL/G",      f"{adv.get('stl_pg',0):.1f}",          "steals per game"),
            ]):
                _dr2c.markdown(
                    f"<div class='adv-tile'>"
                    f"<div class='adv-label'>{lbl}</div>"
                    f"<div class='adv-value'>{val}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                    f"</div>", unsafe_allow_html=True)

            # ── Per-Quarter Rebounding ────────────────────────────────────────
            st.write("")
            st.markdown("<div class='section-hdr'>Rebounding by Quarter</div>",
                        unsafe_allow_html=True)
            st.caption("Average rebounds per game broken down by quarter — team vs opponent.")

            # KPI tiles — total reb, oreb, dreb per quarter
            _ql_reb = ["Q1", "Q2", "Q3", "Q4"]
            _qreb_tile_cols = st.columns(4)
            for _qi, (_qc, _qlbl) in enumerate(zip(_qreb_tile_cols, _ql_reb)):
                _q = _qi + 1
                _qo  = adv.get(f"q{_q}_oreb_pg", 0)
                _qd  = adv.get(f"q{_q}_dreb_pg", 0)
                _qt  = _qo + _qd
                _qc.markdown(
                    f"<div class='adv-tile'>"
                    f"<div class='adv-label'>{_qlbl} TOTAL</div>"
                    f"<div class='adv-value'>{_qt:.1f}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>"
                    f"OREB {_qo:.1f} · DREB {_qd:.1f}</div>"
                    f"</div>", unsafe_allow_html=True)

            st.write("")

            # ── Grouped bar: OREB + DREB per quarter (team vs opp) ──────────
            _rq_c1, _rq_c2 = st.columns(2)

            with _rq_c1:
                _rq_quarters = ["Q1", "Q2", "Q3", "Q4"]
                _rq_team_oreb = [adv.get(f"q{q}_oreb_pg", 0) for q in range(1,5)]
                _rq_team_dreb = [adv.get(f"q{q}_dreb_pg", 0) for q in range(1,5)]
                _rq_opp_oreb  = [adv.get(f"opp_q{q}_oreb_pg", 0) for q in range(1,5)]
                _rq_opp_dreb  = [adv.get(f"opp_q{q}_dreb_pg", 0) for q in range(1,5)]

                fig_rq_oreb = go.Figure()
                fig_rq_oreb.add_trace(go.Bar(
                    name=f"{sel_name} OREB", x=_rq_quarters, y=_rq_team_oreb,
                    marker_color="#e67e22",
                    text=[f"{v:.1f}" for v in _rq_team_oreb], textposition="outside"))
                fig_rq_oreb.add_trace(go.Bar(
                    name="Opp OREB", x=_rq_quarters, y=_rq_opp_oreb,
                    marker_color="#7f8c8d",
                    text=[f"{v:.1f}" for v in _rq_opp_oreb], textposition="outside"))
                fig_rq_oreb.update_layout(
                    **PLOT_LAYOUT, title="Offensive Rebounds per Quarter",
                    barmode="group", yaxis_title="OREB/G",
                    height=320, legend=dict(orientation="h", y=-0.22))
                st.plotly_chart(fig_rq_oreb, use_container_width=True)

            with _rq_c2:
                fig_rq_dreb = go.Figure()
                fig_rq_dreb.add_trace(go.Bar(
                    name=f"{sel_name} DREB", x=_rq_quarters, y=_rq_team_dreb,
                    marker_color="#9b59b6",
                    text=[f"{v:.1f}" for v in _rq_team_dreb], textposition="outside"))
                fig_rq_dreb.add_trace(go.Bar(
                    name="Opp DREB", x=_rq_quarters, y=_rq_opp_dreb,
                    marker_color="#7f8c8d",
                    text=[f"{v:.1f}" for v in _rq_opp_dreb], textposition="outside"))
                fig_rq_dreb.update_layout(
                    **PLOT_LAYOUT, title="Defensive Rebounds per Quarter",
                    barmode="group", yaxis_title="DREB/G",
                    height=320, legend=dict(orientation="h", y=-0.22))
                st.plotly_chart(fig_rq_dreb, use_container_width=True)

            # ── Stacked total reb comparison per quarter ─────────────────────
            _rq_team_reb = [o + d for o, d in zip(_rq_team_oreb, _rq_team_dreb)]
            _rq_opp_reb  = [o + d for o, d in zip(_rq_opp_oreb, _rq_opp_dreb)]

            fig_rq_stk = go.Figure()
            fig_rq_stk.add_trace(go.Bar(
                name=f"{sel_name} OREB", x=_rq_quarters, y=_rq_team_oreb,
                marker_color="#e67e22"))
            fig_rq_stk.add_trace(go.Bar(
                name=f"{sel_name} DREB", x=_rq_quarters, y=_rq_team_dreb,
                marker_color="#9b59b6"))
            fig_rq_stk.add_trace(go.Bar(
                name="Opp OREB", x=_rq_quarters, y=_rq_opp_oreb,
                marker_color="#c0392b", opacity=0.65))
            fig_rq_stk.add_trace(go.Bar(
                name="Opp DREB", x=_rq_quarters, y=_rq_opp_dreb,
                marker_color="#7f8c8d", opacity=0.65))
            fig_rq_stk.update_layout(
                **PLOT_LAYOUT, barmode="group",
                title="Total Rebounds per Quarter — Team vs Opponent",
                yaxis_title="REB/G", height=340,
                legend=dict(orientation="h", y=-0.22))
            st.plotly_chart(fig_rq_stk, use_container_width=True)

            # ── Quarter margin bar (who wins the glass each quarter) ─────────
            _rq_margins = [t - o for t, o in zip(_rq_team_reb, _rq_opp_reb)]
            _rq_margin_colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in _rq_margins]
            fig_rq_margin = go.Figure(go.Bar(
                x=_rq_quarters, y=_rq_margins,
                marker_color=_rq_margin_colors,
                text=[f"{v:+.1f}" for v in _rq_margins],
                textposition="outside"))
            fig_rq_margin.add_hline(y=0, line_color="#555d68", line_width=1)
            fig_rq_margin.update_layout(
                **PLOT_LAYOUT,
                title="Rebounding Margin per Quarter (Team − Opponent)",
                yaxis_title="REB Margin", height=280)
            st.plotly_chart(fig_rq_margin, use_container_width=True)

            # ── Game-by-game rebounding trend ────────────────────────────────
            _gl_reb = adv.get("game_log", [])
            if len(_gl_reb) >= 2:
                st.markdown("<div class='section-hdr'>Game-by-Game Rebounding Trends</div>",
                            unsafe_allow_html=True)
                _gl_reb_labels = []
                for _er in _gl_reb:
                    try:
                        _dl_r = datetime.strptime(_er["date"], "%Y-%m-%d").strftime("%b %d")
                    except Exception:
                        _dl_r = _er.get("date", "—")
                    _gl_reb_labels.append(f"{_dl_r} vs {_er['opp']}")

                _gl_oreb_vals = [e.get("oreb", 0) for e in _gl_reb]
                _gl_dreb_vals = [e.get("dreb", 0) for e in _gl_reb]
                _gl_reb_vals  = [e.get("reb",  0) for e in _gl_reb]

                # Rolling 3-game helper
                def _roll3_reb(vals):
                    out = []
                    for i in range(len(vals)):
                        w = vals[max(0, i-2):i+1]
                        out.append(sum(w)/len(w))
                    return out

                _gl_oreb_r3 = _roll3_reb(_gl_oreb_vals)
                _gl_dreb_r3 = _roll3_reb(_gl_dreb_vals)
                _gl_reb_r3  = _roll3_reb(_gl_reb_vals)

                # Total + OREB + DREB trend lines
                fig_reb_trend = go.Figure()
                fig_reb_trend.add_trace(go.Bar(
                    x=_gl_reb_labels, y=_gl_reb_vals,
                    name="Total REB", marker_color="#2ecc71", opacity=0.45))
                fig_reb_trend.add_trace(go.Scatter(
                    x=_gl_reb_labels, y=_gl_reb_r3, name="Total REB (3G avg)",
                    mode="lines+markers",
                    line=dict(color="#2ecc71", width=2.5), marker=dict(size=7)))
                fig_reb_trend.add_trace(go.Scatter(
                    x=_gl_reb_labels, y=_gl_oreb_vals, name="OREB (game)",
                    mode="lines+markers",
                    line=dict(color="#e67e22", width=1.5, dash="dot"),
                    marker=dict(size=5), opacity=0.7))
                fig_reb_trend.add_trace(go.Scatter(
                    x=_gl_reb_labels, y=_gl_oreb_r3, name="OREB (3G avg)",
                    mode="lines+markers",
                    line=dict(color="#e67e22", width=2.5), marker=dict(size=7)))
                fig_reb_trend.add_trace(go.Scatter(
                    x=_gl_reb_labels, y=_gl_dreb_vals, name="DREB (game)",
                    mode="lines+markers",
                    line=dict(color="#9b59b6", width=1.5, dash="dot"),
                    marker=dict(size=5), opacity=0.7))
                fig_reb_trend.add_trace(go.Scatter(
                    x=_gl_reb_labels, y=_gl_dreb_r3, name="DREB (3G avg)",
                    mode="lines+markers",
                    line=dict(color="#9b59b6", width=2.5), marker=dict(size=7)))
                fig_reb_trend.update_layout(
                    **PLOT_LAYOUT,
                    title="Total / OREB / DREB per Game + 3-Game Rolling Avg",
                    xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                    yaxis_title="Rebounds", height=380,
                    legend=dict(orientation="h", y=-0.25))
                st.plotly_chart(fig_reb_trend, use_container_width=True)

                # Per-quarter rebound trend across games
                st.markdown("<div class='section-hdr'>Per-Quarter Rebound Breakdown — Game by Game</div>",
                            unsafe_allow_html=True)
                _rq_colors = {"Q1": "#58a6ff", "Q2": "#f0a500",
                              "Q3": "#2ecc71",  "Q4": "#e74c3c"}
                fig_rq_trend = go.Figure()
                for _qi2, _qlbl2 in enumerate(["Q1", "Q2", "Q3", "Q4"], start=1):
                    _q_oreb_g = [e.get(f"q{_qi2}_oreb", 0) for e in _gl_reb]
                    _q_dreb_g = [e.get(f"q{_qi2}_dreb", 0) for e in _gl_reb]
                    _q_reb_g  = [o + d for o, d in zip(_q_oreb_g, _q_dreb_g)]
                    fig_rq_trend.add_trace(go.Scatter(
                        x=_gl_reb_labels, y=_q_reb_g, name=f"{_qlbl2} REB",
                        mode="lines+markers",
                        line=dict(color=_rq_colors[_qlbl2], width=2),
                        marker=dict(size=6)))
                fig_rq_trend.update_layout(
                    **PLOT_LAYOUT,
                    title="Total Rebounds per Quarter — Game by Game",
                    xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                    yaxis_title="Rebounds", height=340,
                    legend=dict(orientation="h", y=-0.25))
                st.plotly_chart(fig_rq_trend, use_container_width=True)

                # OREB & DREB split per quarter across games (2-col)
                _rqg_c1, _rqg_c2 = st.columns(2)
                with _rqg_c1:
                    fig_oreb_qg = go.Figure()
                    for _qi2, _qlbl2 in enumerate(["Q1", "Q2", "Q3", "Q4"], start=1):
                        _q_vals = [e.get(f"q{_qi2}_oreb", 0) for e in _gl_reb]
                        fig_oreb_qg.add_trace(go.Scatter(
                            x=_gl_reb_labels, y=_q_vals, name=f"{_qlbl2}",
                            mode="lines+markers",
                            line=dict(color=_rq_colors[_qlbl2], width=2),
                            marker=dict(size=6)))
                    fig_oreb_qg.update_layout(
                        **PLOT_LAYOUT, title="OREB per Quarter — Game by Game",
                        xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                        yaxis_title="OREB", height=300,
                        legend=dict(orientation="h", y=-0.3))
                    st.plotly_chart(fig_oreb_qg, use_container_width=True)

                with _rqg_c2:
                    fig_dreb_qg = go.Figure()
                    for _qi2, _qlbl2 in enumerate(["Q1", "Q2", "Q3", "Q4"], start=1):
                        _q_vals = [e.get(f"q{_qi2}_dreb", 0) for e in _gl_reb]
                        fig_dreb_qg.add_trace(go.Scatter(
                            x=_gl_reb_labels, y=_q_vals, name=f"{_qlbl2}",
                            mode="lines+markers",
                            line=dict(color=_rq_colors[_qlbl2], width=2),
                            marker=dict(size=6)))
                    fig_dreb_qg.update_layout(
                        **PLOT_LAYOUT, title="DREB per Quarter — Game by Game",
                        xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                        yaxis_title="DREB", height=300,
                        legend=dict(orientation="h", y=-0.3))
                    st.plotly_chart(fig_dreb_qg, use_container_width=True)

        # ── DEFENSE ──────────────────────────────────────────────────────────
        with sub_defense:
            st.markdown("<div class='section-hdr'>Team Defensive Profile</div>",
                        unsafe_allow_html=True)

            _def_kpi_cols = st.columns(4)
            for _dkc, (lbl, val, sub) in zip(_def_kpi_cols, [
                ("DRtg",       f"{adv['drtg']:.1f}",                   "pts allowed / 100 poss"),
                ("Opp eFG%",   f"{adv['oefg']*100:.1f}%",              "opponent eff FG%"),
                ("DREB%",      f"{adv.get('dreb_p',0)*100:.1f}%",      "def rebound rate"),
                ("Forced TOV", f"{adv.get('opp_tov_r',0)*100:.1f}%",   "opp turnover rate"),
            ]):
                _dkc.markdown(
                    f"<div class='adv-tile'><div class='adv-label'>{lbl}</div>"
                    f"<div class='adv-value'>{val}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>{sub}</div></div>",
                    unsafe_allow_html=True)

            st.write("")
            _def_kpi_cols2 = st.columns(4)
            for _dkc2, (lbl, val, sub) in zip(_def_kpi_cols2, [
                ("BLK Rate",  f"{adv.get('blk_rate',0):.1f}%",        "% opp 2PA blocked"),
                ("STL/G",     f"{adv.get('stl_pg',0):.1f}",           "steals per game"),
                ("Opp OREB%", f"{adv.get('opp_oreb_p',0)*100:.1f}%",  "opp off-reb rate"),
                ("Net Rtg",   f"{adv['ortg']-adv['drtg']:+.1f}",      "ORtg − DRtg"),
            ]):
                _dkc2.markdown(
                    f"<div class='adv-tile'><div class='adv-label'>{lbl}</div>"
                    f"<div class='adv-value'>{val}</div>"
                    f"<div style='font-size:10px;color:#8b949e'>{sub}</div></div>",
                    unsafe_allow_html=True)

            # Per-player defensive rankings
            st.markdown("<div class='section-hdr'>Individual Defensive Rankings</div>",
                        unsafe_allow_html=True)
            _rnk_def = compute_player_rankings()
            _rat_def = compute_player_ratings()
            _team_rnk_def = pd.DataFrame()
            _team_rat_def = pd.DataFrame()
            if not _rnk_def.empty and "Team" in _rnk_def.columns:
                _team_rnk_def = _rnk_def[_rnk_def["Team"] == sel_name].copy()
            if not _rat_def.empty and "Team" in _rat_def.columns:
                _team_rat_def = _rat_def[_rat_def["Team"] == sel_name].copy()

            if not _team_rnk_def.empty:
                _def_tbl_cols = ["Player", "GP", "STL", "BLK", "Stocks", "DREB",
                                  "OREB", "DREB%", "OREB%", "DSh%", "PF", "TOV"]
                _def_show = [c for c in _def_tbl_cols if c in _team_rnk_def.columns]
                st.dataframe(
                    _team_rnk_def[_def_show].sort_values("STL", ascending=False)
                    .reset_index(drop=True),
                    use_container_width=True, hide_index=True)

                _def_c1, _def_c2 = st.columns(2)
                with _def_c1:
                    if "STL" in _team_rnk_def.columns:
                        _stl_s = _team_rnk_def.sort_values("STL", ascending=True)
                        fig_stl = go.Figure(go.Bar(
                            x=_stl_s["STL"], y=_stl_s["Player"], orientation="h",
                            marker_color="#2ecc71",
                            text=[f"{v:.1f}" for v in _stl_s["STL"]],
                            textposition="outside"))
                        fig_stl.update_layout(
                            **PLOT_LAYOUT, title="Steals per Game",
                            xaxis_title="STL/G",
                            height=max(280, len(_stl_s)*34+60),
                            margin_l=130)
                        st.plotly_chart(fig_stl, use_container_width=True)

                with _def_c2:
                    if "BLK" in _team_rnk_def.columns:
                        _blk_s = _team_rnk_def.sort_values("BLK", ascending=True)
                        fig_blk = go.Figure(go.Bar(
                            x=_blk_s["BLK"], y=_blk_s["Player"], orientation="h",
                            marker_color="#3498db",
                            text=[f"{v:.1f}" for v in _blk_s["BLK"]],
                            textposition="outside"))
                        fig_blk.update_layout(
                            **PLOT_LAYOUT, title="Blocks per Game",
                            xaxis_title="BLK/G",
                            height=max(280, len(_blk_s)*34+60),
                            margin_l=130)
                        st.plotly_chart(fig_blk, use_container_width=True)

                _def_c3, _def_c4 = st.columns(2)
                with _def_c3:
                    if "DREB" in _team_rnk_def.columns:
                        _dreb_s = _team_rnk_def.sort_values("DREB", ascending=True)
                        fig_dreb = go.Figure(go.Bar(
                            x=_dreb_s["DREB"], y=_dreb_s["Player"], orientation="h",
                            marker_color="#9b59b6",
                            text=[f"{v:.1f}" for v in _dreb_s["DREB"]],
                            textposition="outside"))
                        fig_dreb.update_layout(
                            **PLOT_LAYOUT, title="Defensive Rebounds per Game",
                            xaxis_title="DREB/G",
                            height=max(280, len(_dreb_s)*34+60),
                            margin_l=130)
                        st.plotly_chart(fig_dreb, use_container_width=True)

                with _def_c4:
                    if "DSh%" in _team_rnk_def.columns:
                        _dsh_s = _team_rnk_def[_team_rnk_def["DSh%"] > 0].sort_values(
                            "DSh%", ascending=True)
                        if not _dsh_s.empty:
                            fig_dsh = go.Figure(go.Bar(
                                x=_dsh_s["DSh%"], y=_dsh_s["Player"], orientation="h",
                                marker_color=[
                                    "#2ecc71" if v >= 15 else
                                    "#f0a500" if v >= 8  else "#e74c3c"
                                    for v in _dsh_s["DSh%"]
                                ],
                                text=[f"{v:.1f}%" for v in _dsh_s["DSh%"]],
                                textposition="outside"))
                            fig_dsh.update_layout(
                                **PLOT_LAYOUT, title="Shot Contest Rate (DSh%)",
                                xaxis_title="DSh%",
                                height=max(280, len(_dsh_s)*34+60),
                                margin_l=130)
                            st.plotly_chart(fig_dsh, use_container_width=True)

                # Stocks (STL+BLK) bar
                if "Stocks" in _team_rnk_def.columns:
                    st.markdown("<div class='section-hdr'>Stocks (STL+BLK) per Game</div>",
                                unsafe_allow_html=True)
                    _stk_s = _team_rnk_def.sort_values("Stocks", ascending=False)
                    fig_stk = go.Figure()
                    if "STL" in _team_rnk_def.columns:
                        fig_stk.add_trace(go.Bar(
                            name="STL", x=_stk_s["Player"], y=_stk_s["STL"],
                            marker_color="#2ecc71"))
                    if "BLK" in _team_rnk_def.columns:
                        fig_stk.add_trace(go.Bar(
                            name="BLK", x=_stk_s["Player"], y=_stk_s["BLK"],
                            marker_color="#3498db"))
                    fig_stk.update_layout(
                        **PLOT_LAYOUT, barmode="stack",
                        title="Stocks per Game — STL + BLK",
                        yaxis_title="Per Game", height=320,
                        xaxis=dict(tickangle=-20),
                        legend=dict(orientation="h", y=-0.2))
                    st.plotly_chart(fig_stk, use_container_width=True)

            if not _team_rat_def.empty and "DEF" in _team_rat_def.columns:
                st.markdown(
                    "<div class='section-hdr'>Defensive Rating (0–100 vs League)</div>",
                    unsafe_allow_html=True)
                _def_rat_s = _team_rat_def.sort_values("DEF", ascending=True)
                fig_def_rat = go.Figure(go.Bar(
                    x=_def_rat_s["DEF"], y=_def_rat_s["Player"], orientation="h",
                    marker_color=[
                        "#2ecc71" if v >= 70 else "#f0a500" if v >= 45 else "#e74c3c"
                        for v in _def_rat_s["DEF"]
                    ],
                    text=[f"{v:.1f}" for v in _def_rat_s["DEF"]],
                    textposition="outside"))
                fig_def_rat.update_layout(
                    **PLOT_LAYOUT, title="Individual Defensive Rating (League-relative)",
                    xaxis_title="DEF Rating", xaxis_range=[0, 110],
                    height=max(300, len(_def_rat_s)*35+60))
                fig_def_rat.update_layout(margin_l=130)
                st.plotly_chart(fig_def_rat, use_container_width=True)

            # ── Defense by Quarter ────────────────────────────────────────
            st.markdown("<div class='section-hdr'>Defense by Quarter & Half</div>",
                        unsafe_allow_html=True)
            _dq_drtg_avg = adv["drtg"] / 100
            _dq_data = [
                ("Q1", adv["opp_q1_pts_pg"], adv["opp_q1_ppp"]),
                ("Q2", adv["opp_q2_pts_pg"], adv["opp_q2_ppp"]),
                ("H1", adv["opp_h1_pts_pg"], adv["opp_h1_ppp"]),
                ("Q3", adv["opp_q3_pts_pg"], adv["opp_q3_ppp"]),
                ("Q4", adv["opp_q4_pts_pg"], adv["opp_q4_ppp"]),
                ("H2", adv["opp_h2_pts_pg"], adv["opp_h2_ppp"]),
            ]
            _def_q_rows = [
                {
                    "Period":  lbl,
                    "Opp PPG": round(oppg, 1),
                    "Opp PPP": round(oppp, 3),
                    "vs Avg":  f"{oppp - _dq_drtg_avg:+.3f}",
                    "Grade":   "✓" if oppp <= _dq_drtg_avg else "✗",
                }
                for lbl, oppg, oppp in _dq_data
            ]
            st.dataframe(pd.DataFrame(_def_q_rows), use_container_width=True, hide_index=True)

            _dql = ["Q1", "Q2", "Q3", "Q4"]
            _def_qcols = st.columns(2)
            with _def_qcols[0]:
                fig_dq_ppg = go.Figure(go.Bar(
                    x=_dql,
                    y=[adv["opp_q1_pts_pg"], adv["opp_q2_pts_pg"],
                       adv["opp_q3_pts_pg"], adv["opp_q4_pts_pg"]],
                    marker_color="#e74c3c",
                    text=[f"{v:.1f}" for v in [
                        adv["opp_q1_pts_pg"], adv["opp_q2_pts_pg"],
                        adv["opp_q3_pts_pg"], adv["opp_q4_pts_pg"]]],
                    textposition="outside"))
                fig_dq_ppg.update_layout(
                    **PLOT_LAYOUT, title="Opponent PPG by Quarter",
                    yaxis_title="PPG", height=300)
                st.plotly_chart(fig_dq_ppg, use_container_width=True)
            with _def_qcols[1]:
                _opp_ppp_q = [adv["opp_q1_ppp"], adv["opp_q2_ppp"],
                              adv["opp_q3_ppp"], adv["opp_q4_ppp"]]
                fig_dq_ppp = go.Figure(go.Bar(
                    x=_dql, y=_opp_ppp_q,
                    marker_color=[
                        "#e74c3c" if v > _dq_drtg_avg else "#2ecc71"
                        for v in _opp_ppp_q
                    ],
                    text=[f"{v:.3f}" for v in _opp_ppp_q],
                    textposition="outside"))
                fig_dq_ppp.add_hline(
                    y=_dq_drtg_avg, line_dash="dot", line_color="#f0a500",
                    annotation_text=f"Season avg ({_dq_drtg_avg:.3f})",
                    annotation_position="top left")
                fig_dq_ppp.update_layout(
                    **PLOT_LAYOUT, title="Opponent PPP by Quarter",
                    yaxis_title="PPP", height=300)
                st.plotly_chart(fig_dq_ppp, use_container_width=True)

            _opp_q_ppp_map = {"Q1": adv["opp_q1_ppp"], "Q2": adv["opp_q2_ppp"],
                               "Q3": adv["opp_q3_ppp"], "Q4": adv["opp_q4_ppp"]}
            _worst_def_q = max(_opp_q_ppp_map, key=_opp_q_ppp_map.get)
            _best_def_q  = min(_opp_q_ppp_map, key=_opp_q_ppp_map.get)
            st.info(
                f"Toughest defensive quarter: **{_worst_def_q}** "
                f"({_opp_q_ppp_map[_worst_def_q]:.3f} opp PPP) · "
                f"Best: **{_best_def_q}** ({_opp_q_ppp_map[_best_def_q]:.3f} opp PPP)")

        # ── TRENDS ────────────────────────────────────────────────────────────
        with sub_trends:
            _gl_tr = adv.get("game_log", [])
            if len(_gl_tr) < 2:
                st.info("Need at least 2 tracked games to display trends.")
            else:
                _gl_labels_tr = []
                for _e_tr in _gl_tr:
                    try:
                        _dl_tr = datetime.strptime(_e_tr["date"], "%Y-%m-%d").strftime("%b %d")
                    except Exception:
                        _dl_tr = _e_tr.get("date", "—")
                    _gl_labels_tr.append(f"{_dl_tr} vs {_e_tr['opp']}")

                _ortg_tr = [e["ortg"]             for e in _gl_tr]
                _drtg_tr = [e["drtg"]             for e in _gl_tr]
                _net_tr  = [e["ortg"] - e["drtg"] for e in _gl_tr]
                _wins_tr = [e["margin"] >= 0       for e in _gl_tr]

                def _roll3(vals):
                    out = []
                    for i in range(len(vals)):
                        w = vals[max(0, i-2):i+1]
                        out.append(sum(w) / len(w))
                    return out

                _ortg_r3 = _roll3(_ortg_tr)
                _drtg_r3 = _roll3(_drtg_tr)
                _net_r3  = _roll3(_net_tr)

                # Rolling ORtg / DRtg
                st.markdown("<div class='section-hdr'>Rolling 3-Game Efficiency</div>",
                            unsafe_allow_html=True)
                fig_roll = go.Figure()
                fig_roll.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_ortg_tr, name="ORtg (game)",
                    mode="lines+markers",
                    line=dict(color="#f0a500", width=1.5, dash="dot"),
                    marker=dict(size=5), opacity=0.55))
                fig_roll.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_ortg_r3, name="ORtg (3G avg)",
                    mode="lines+markers",
                    line=dict(color="#f0a500", width=2.5), marker=dict(size=7)))
                fig_roll.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_drtg_tr, name="DRtg (game)",
                    mode="lines+markers",
                    line=dict(color="#e74c3c", width=1.5, dash="dot"),
                    marker=dict(size=5), opacity=0.55))
                fig_roll.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_drtg_r3, name="DRtg (3G avg)",
                    mode="lines+markers",
                    line=dict(color="#e74c3c", width=2.5), marker=dict(size=7)))
                fig_roll.update_layout(
                    **PLOT_LAYOUT,
                    title="ORtg & DRtg — Raw + 3-Game Rolling Average",
                    xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                    yaxis_title="Rating", height=360,
                    legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig_roll, use_container_width=True)

                # Net Rating trend
                st.markdown("<div class='section-hdr'>Net Rating Trend</div>",
                            unsafe_allow_html=True)
                _net_colors_tr = ["#2ecc71" if v >= 0 else "#e74c3c" for v in _net_tr]
                fig_net = go.Figure()
                fig_net.add_trace(go.Bar(
                    x=_gl_labels_tr, y=_net_tr,
                    name="Net Rtg", marker_color=_net_colors_tr, opacity=0.7))
                fig_net.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_net_r3, name="3G Rolling Net",
                    mode="lines+markers",
                    line=dict(color="#58a6ff", width=2.5), marker=dict(size=7)))
                fig_net.add_hline(y=0, line_color="#555d68", line_width=1)
                fig_net.update_layout(
                    **PLOT_LAYOUT, title="Net Rating per Game + 3-Game Trend",
                    xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                    yaxis_title="Net Rtg", height=320,
                    legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig_net, use_container_width=True)

                # Self-Created vs Assisted FGA trend with MOV background
                st.markdown("<div class='section-hdr'>Self-Created vs Assisted FGA</div>",
                            unsafe_allow_html=True)
                _sc_fga_tr  = [e.get("sc_fga",  0) for e in _gl_tr]
                _ast_fga_tr = [e.get("ast_fga", 0) for e in _gl_tr]
                _mov_tr     = [e["margin"] for e in _gl_tr]
                _mov_colors_fga = ["rgba(46,204,113,0.25)" if v >= 0 else "rgba(231,76,60,0.25)"
                                   for v in _mov_tr]
                fig_fga_creation = go.Figure()
                # MOV bars in background (secondary y-axis)
                fig_fga_creation.add_trace(go.Bar(
                    x=_gl_labels_tr, y=_mov_tr,
                    name="MOV", marker_color=_mov_colors_fga,
                    yaxis="y2", showlegend=True))
                # Self-created line
                fig_fga_creation.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_sc_fga_tr,
                    name="Self-Created FGA",
                    mode="lines+markers",
                    line=dict(color="#f0a500", width=2.5),
                    marker=dict(size=7)))
                # Assisted line
                fig_fga_creation.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_ast_fga_tr,
                    name="Assisted FGA",
                    mode="lines+markers",
                    line=dict(color="#58a6ff", width=2.5),
                    marker=dict(size=7)))
                fig_fga_creation.update_layout(
                    **PLOT_LAYOUT,
                    title="Self-Created vs Assisted FGA per Game",
                    xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                    yaxis=dict(title="FGA", side="left"),
                    yaxis2=dict(title="MOV", overlaying="y", side="right",
                                zeroline=True, zerolinecolor="#555d68",
                                showgrid=False),
                    height=360,
                    legend=dict(orientation="h", y=-0.25),
                    barmode="overlay")
                st.plotly_chart(fig_fga_creation, use_container_width=True)

                # Wins vs Losses breakdown
                st.markdown("<div class='section-hdr'>Performance in Wins vs Losses</div>",
                            unsafe_allow_html=True)
                _wl_ortg_w = [v for v, w in zip(_ortg_tr, _wins_tr) if w]
                _wl_drtg_w = [v for v, w in zip(_drtg_tr, _wins_tr) if w]
                _wl_ortg_l = [v for v, w in zip(_ortg_tr, _wins_tr) if not w]
                _wl_drtg_l = [v for v, w in zip(_drtg_tr, _wins_tr) if not w]
                _wl_rows = []
                for _split, _og, _dg in [
                    ("Wins",   _wl_ortg_w, _wl_drtg_w),
                    ("Losses", _wl_ortg_l, _wl_drtg_l),
                ]:
                    if not _og:
                        continue
                    _avg_o = round(sum(_og)/len(_og), 1)
                    _avg_d = round(sum(_dg)/len(_dg), 1)
                    _wl_rows.append({
                        "Split":    _split,
                        "GP":       len(_og),
                        "Avg ORtg": _avg_o,
                        "Avg DRtg": _avg_d,
                        "Avg Net":  round(_avg_o - _avg_d, 1),
                    })
                if _wl_rows:
                    st.dataframe(pd.DataFrame(_wl_rows),
                                 use_container_width=True, hide_index=True)
                    _wc1, _wc2 = st.columns(2)
                    with _wc1:
                        fig_wl_o = go.Figure()
                        _wl_xlabels = [r["Split"] for r in _wl_rows]
                        fig_wl_o.add_trace(go.Bar(
                            name="ORtg", x=_wl_xlabels,
                            y=[r["Avg ORtg"] for r in _wl_rows],
                            marker_color="#f0a500"))
                        fig_wl_o.add_trace(go.Bar(
                            name="DRtg", x=_wl_xlabels,
                            y=[r["Avg DRtg"] for r in _wl_rows],
                            marker_color="#e74c3c"))
                        fig_wl_o.update_layout(
                            **PLOT_LAYOUT, barmode="group",
                            title="ORtg / DRtg — Wins vs Losses",
                            yaxis_title="Rating", height=300)
                        st.plotly_chart(fig_wl_o, use_container_width=True)
                    with _wc2:
                        fig_wl_n = go.Figure(go.Bar(
                            x=_wl_xlabels,
                            y=[r["Avg Net"] for r in _wl_rows],
                            marker_color=["#2ecc71" if r["Avg Net"] >= 0 else "#e74c3c"
                                          for r in _wl_rows],
                            text=[f"{r['Avg Net']:+.1f}" for r in _wl_rows],
                            textposition="outside"))
                        fig_wl_n.update_layout(
                            **PLOT_LAYOUT, title="Net Rating — Wins vs Losses",
                            yaxis_title="Net Rtg", height=300)
                        st.plotly_chart(fig_wl_n, use_container_width=True)

                # Home / Away / Neutral splits
                st.markdown("<div class='section-hdr'>Home / Away / Neutral Splits</div>",
                            unsafe_allow_html=True)
                _ha_buckets = {"Home": [], "Away": [], "Neutral": []}
                for _g_ha in sorted(all_gs, key=lambda x: x["date"]):
                    _ha_val = home_away(_g_ha, team_id)
                    _res_ha, _my_ha, _op_ha = win_loss(_g_ha, team_id)
                    _k_ha = "Home" if _ha_val == "H" else "Away" if _ha_val == "A" else "Neutral"
                    _ha_buckets[_k_ha].append({
                        "result": _res_ha, "pts": _my_ha,
                        "opp_pts": _op_ha, "mov": _my_ha - _op_ha})
                _ha_rows_tr = []
                for _k, _games_k in _ha_buckets.items():
                    if not _games_k:
                        continue
                    _w_ha = sum(1 for g in _games_k if g["result"] == "W")
                    _n_ha = len(_games_k)
                    _ha_rows_tr.append({
                        "Split":   _k,
                        "GP":      _n_ha,
                        "W":       _w_ha,
                        "L":       _n_ha - _w_ha,
                        "W%":      f"{_w_ha/_n_ha*100:.0f}%",
                        "PPG":     round(sum(g["pts"]     for g in _games_k)/_n_ha, 1),
                        "PA/G":    round(sum(g["opp_pts"] for g in _games_k)/_n_ha, 1),
                        "Avg MOV": round(sum(g["mov"]     for g in _games_k)/_n_ha, 1),
                    })
                if _ha_rows_tr:
                    st.dataframe(pd.DataFrame(_ha_rows_tr),
                                 use_container_width=True, hide_index=True)

                # First-half vs Second-half splits
                if adv.get("h1_pts_pg") is not None:
                    st.markdown("<div class='section-hdr'>Half-by-Half Scoring</div>",
                                unsafe_allow_html=True)
                    _half_lbl = ["1st Half", "2nd Half"]
                    _t_half   = [adv["h1_pts_pg"], adv["h2_pts_pg"]]
                    _o_half   = [adv["opp_h1_pts_pg"], adv["opp_h2_pts_pg"]]
                    _tc1, _tc2 = st.columns(2)
                    with _tc1:
                        fig_half = go.Figure()
                        fig_half.add_trace(go.Bar(
                            name=sel_name, x=_half_lbl, y=_t_half,
                            marker_color="#f0a500",
                            text=[f"{v:.1f}" for v in _t_half], textposition="outside"))
                        fig_half.add_trace(go.Bar(
                            name="Opponent", x=_half_lbl, y=_o_half,
                            marker_color="#e74c3c",
                            text=[f"{v:.1f}" for v in _o_half], textposition="outside"))
                        fig_half.update_layout(
                            **PLOT_LAYOUT, barmode="group",
                            title="Avg Points per Half", yaxis_title="PPG", height=300)
                        st.plotly_chart(fig_half, use_container_width=True)
                    with _tc2:
                        _h_margins = [_t_half[i] - _o_half[i] for i in range(2)]
                        fig_hm = go.Figure(go.Bar(
                            x=_half_lbl, y=_h_margins,
                            marker_color=["#2ecc71" if v >= 0 else "#e74c3c"
                                          for v in _h_margins],
                            text=[f"{v:+.1f}" for v in _h_margins],
                            textposition="outside"))
                        fig_hm.add_hline(y=0, line_color="#555d68", line_width=1)
                        fig_hm.update_layout(
                            **PLOT_LAYOUT, title="Scoring Margin by Half",
                            yaxis_title="Margin", height=300)
                        st.plotly_chart(fig_hm, use_container_width=True)

                # PPP game-by-game with win/loss shading
                st.markdown("<div class='section-hdr'>PPP Trend — Each Tracked Game</div>",
                            unsafe_allow_html=True)
                _ppp_t = [e["ortg"] / 100 for e in _gl_tr]
                _ppp_o = [e["drtg"] / 100 for e in _gl_tr]
                fig_ppp_tr = go.Figure()
                fig_ppp_tr.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_ppp_t,
                    name="Team PPP", mode="lines+markers",
                    line=dict(color="#f0a500", width=2), marker=dict(size=7)))
                fig_ppp_tr.add_trace(go.Scatter(
                    x=_gl_labels_tr, y=_ppp_o,
                    name="Opp PPP", mode="lines+markers",
                    line=dict(color="#e74c3c", width=2, dash="dot"), marker=dict(size=7)))
                fig_ppp_tr.update_layout(
                    **PLOT_LAYOUT, title="Points Per Possession — Game by Game",
                    xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                    yaxis_title="PPP", height=320,
                    legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig_ppp_tr, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — PLAYERS
# ══════════════════════════════════════════════════════════════════════════════
with tab_pl:
    _rnk_all_pl = compute_player_rankings()
    _rat_all_pl = compute_player_ratings()

    # Filter to this team
    _team_rnk = pd.DataFrame()
    _team_rat = pd.DataFrame()
    if not _rnk_all_pl.empty and "Team" in _rnk_all_pl.columns:
        _team_rnk = _rnk_all_pl[_rnk_all_pl["Team"] == sel_name].copy()
    if not _rat_all_pl.empty and "Team" in _rat_all_pl.columns:
        _team_rat = _rat_all_pl[_rat_all_pl["Team"] == sel_name].copy()

    # ── Full team stats table ────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Team Player Stats</div>", unsafe_allow_html=True)

    if not _team_rnk.empty:
        _pl_stat_cols = ["Player", "#", "GP", "PTS", "AST", "REB", "OREB", "DREB",
                         "STL", "BLK", "TOV", "FG%", "3P%", "FT%", "TS%", "eFG%",
                         "ShotRat", "DSh%", "SC"]
        _show_pl_cols = [c for c in _pl_stat_cols if c in _team_rnk.columns]
        st.dataframe(
            _team_rnk[_show_pl_cols].sort_values("PTS", ascending=False)
            .reset_index(drop=True),
            use_container_width=True, hide_index=True)
    else:
        st.info("No tracked player stats for this team yet.")

    # ── Player Rankings & Comparisons ────────────────────────────────────────
    if not _team_rnk.empty:
        st.divider()
        st.markdown("<div class='section-hdr'>Player Rankings & Comparisons</div>",
                    unsafe_allow_html=True)
        st.caption("Every player on this roster ranked across all tracked stat categories.")

        _pr_s1, _pr_s2, _pr_s3, _pr_s4 = st.tabs([
            "📊 Stat Leaders", "🏹 Shooting Profile", "🧠 Advanced Metrics", "⚔️ Player Comparison"
        ])

        with _pr_s1:
            # Mini leaderboards
            st.markdown("<div class='section-hdr'>Category Leaders</div>",
                        unsafe_allow_html=True)
            _ldr_cats = [
                ("PTS",  "Points/G",        "#f0a500", True),
                ("AST",  "Assists/G",        "#3498db", True),
                ("REB",  "Rebounds/G",       "#2ecc71", True),
                ("STL",  "Steals/G",         "#9b59b6", True),
                ("BLK",  "Blocks/G",         "#e67e22", True),
                ("TS%",  "True Shooting%",   "#58a6ff", True),
                ("3P%",  "Three-Point%",     "#f0a500", True),
                ("+/-",  "Plus/Minus",       "#2ecc71", True),
            ]
            _ldr_cols = st.columns(4)
            for _ldr_i, (_ldr_c, _ldr_l, _ldr_clr, _ldr_hib) in enumerate(_ldr_cats):
                if _ldr_c not in _team_rnk.columns:
                    continue
                _ldr_s = _team_rnk.sort_values(
                    _ldr_c, ascending=not _ldr_hib).dropna(subset=[_ldr_c])
                if _ldr_s.empty:
                    continue
                _top3 = _ldr_s.head(3)
                _mhtml = ""
                for _mi, (__, _lr) in enumerate(_top3.iterrows()):
                    _medal = ["🥇","🥈","🥉"][_mi]
                    _lv = _lr[_ldr_c]
                    _vs = (f"{_lv:+.1f}" if _ldr_c == "+/-"
                           else f"{_lv:.1f}{'%' if '%' in _ldr_c else ''}")
                    _mhtml += (
                        f"<div style='display:flex;justify-content:space-between;"
                        f"padding:3px 0;border-bottom:1px solid #21262d'>"
                        f"<span style='font-size:12px'>{_medal} {_lr['Player']}</span>"
                        f"<span style='color:{_ldr_clr};font-weight:700;font-size:12px'>"
                        f"{_vs}</span></div>")
                _ldr_cols[_ldr_i % 4].markdown(
                    f"<div style='background:#161b22;border:1px solid #30363d;"
                    f"border-radius:10px;padding:12px;margin-bottom:10px'>"
                    f"<div style='font-size:10px;color:#8b949e;text-transform:uppercase;"
                    f"letter-spacing:1px;margin-bottom:8px'>{_ldr_l}</div>"
                    f"{_mhtml}</div>", unsafe_allow_html=True)

            # Sorted bar charts
            st.markdown("<div class='section-hdr'>Full Rankings — All Players</div>",
                        unsafe_allow_html=True)
            _rk_cfg = [
                ("PTS",  "Points per Game",        "#f0a500"),
                ("AST",  "Assists per Game",        "#3498db"),
                ("REB",  "Rebounds per Game",       "#2ecc71"),
                ("OREB", "Off Rebounds per Game",   "#e67e22"),
                ("DREB", "Def Rebounds per Game",   "#9b59b6"),
                ("STL",  "Steals per Game",         "#2ecc71"),
                ("BLK",  "Blocks per Game",         "#3498db"),
                ("TOV",  "Turnovers per Game",      "#e74c3c"),
                ("+/-",  "Plus/Minus per Game",     "#58a6ff"),
                ("SC",   "Shot Creations per Game", "#f0a500"),
                ("GS",   "Game Score",              "#2ecc71"),
                ("EFF",  "NBA Efficiency",          "#f0a500"),
            ]
            for _rki in range(0, len(_rk_cfg), 2):
                _rc1, _rc2 = st.columns(2)
                for _rci, _rcobj in enumerate([_rc1, _rc2]):
                    if _rki + _rci >= len(_rk_cfg):
                        break
                    _rk_key, _rk_lbl, _rk_clr = _rk_cfg[_rki + _rci]
                    if _rk_key not in _team_rnk.columns:
                        continue
                    _rk_s = _team_rnk.sort_values(
                        _rk_key, ascending=True).dropna(subset=[_rk_key])
                    if _rk_s.empty:
                        continue
                    _is_pm = (_rk_key == "+/-")
                    with _rcobj:
                        _fig_rk = go.Figure(go.Bar(
                            x=_rk_s[_rk_key], y=_rk_s["Player"],
                            orientation="h",
                            marker_color=(
                                ["#2ecc71" if v >= 0 else "#e74c3c"
                                 for v in _rk_s[_rk_key]] if _is_pm
                                else [_rk_clr]*len(_rk_s)),
                            text=[f"{v:+.1f}" if _is_pm else f"{v:.1f}"
                                  for v in _rk_s[_rk_key]],
                            textposition="outside"))
                        _fig_rk.update_layout(
                            **PLOT_LAYOUT, title=_rk_lbl,
                            xaxis_title=_rk_key,
                            height=max(250, len(_rk_s)*34+60))
                        _fig_rk.update_layout(margin_l=130, margin_r=60)
                        st.plotly_chart(_fig_rk, use_container_width=True)

            # MIN + USG
            if "MIN" in _team_rnk.columns and "USG" in _team_rnk.columns:
                st.markdown("<div class='section-hdr'>Minutes & Usage</div>",
                            unsafe_allow_html=True)
                _muc1, _muc2 = st.columns(2)
                with _muc1:
                    _min_s = _team_rnk.sort_values("MIN", ascending=True)
                    fig_min = go.Figure(go.Bar(
                        x=_min_s["MIN"], y=_min_s["Player"], orientation="h",
                        marker_color="#58a6ff",
                        text=[f"{v:.1f}" for v in _min_s["MIN"]],
                        textposition="outside"))
                    fig_min.update_layout(
                        **PLOT_LAYOUT, title="Minutes per Game", xaxis_title="MIN/G",
                        height=max(250, len(_min_s)*34+60))
                    fig_min.update_layout(margin_l=130)
                    st.plotly_chart(fig_min, use_container_width=True)
                with _muc2:
                    _usg_s = _team_rnk.sort_values("USG", ascending=True)
                    fig_usg = go.Figure(go.Bar(
                        x=_usg_s["USG"], y=_usg_s["Player"], orientation="h",
                        marker_color="#e67e22",
                        text=[f"{v:.1f}" for v in _usg_s["USG"]],
                        textposition="outside"))
                    fig_usg.update_layout(
                        **PLOT_LAYOUT, title="Usage Volume per Game",
                        xaxis_title="USG/G",
                        height=max(250, len(_usg_s)*34+60))
                    fig_usg.update_layout(margin_l=130)
                    st.plotly_chart(fig_usg, use_container_width=True)

        with _pr_s2:
            # Volume vs efficiency scatter
            st.markdown("<div class='section-hdr'>Volume vs Efficiency</div>",
                        unsafe_allow_html=True)
            if all(c in _team_rnk.columns for c in ["FGA", "eFG%", "PTS"]):
                _scat = _team_rnk.dropna(subset=["FGA","eFG%","PTS"]).copy()
                if not _scat.empty:
                    _scat_fig = px.scatter(
                        _scat, x="FGA", y="eFG%", size="PTS", color="PTS",
                        text="Player", color_continuous_scale="Oranges",
                        labels={"FGA":"FGA per Game","eFG%":"eFG%"},
                        title="FGA vs eFG% (bubble = PPG)")
                    _scat_fig.update_traces(textposition="top center", textfont_size=9)
                    _scat_fig.update_layout(**PLOT_LAYOUT, height=440)
                    st.plotly_chart(_scat_fig, use_container_width=True)

            if all(c in _team_rnk.columns for c in ["USG","TS%","PTS"]):
                _scat2 = _team_rnk.dropna(subset=["USG","TS%","PTS"]).copy()
                if not _scat2.empty:
                    _scat2_fig = px.scatter(
                        _scat2, x="USG", y="TS%", size="PTS", color="PTS",
                        text="Player", color_continuous_scale="Blues",
                        labels={"USG":"Usage Volume/G","TS%":"True Shooting%"},
                        title="Usage Volume vs True Shooting% (bubble = PPG)")
                    _scat2_fig.update_traces(textposition="top center", textfont_size=9)
                    _scat2_fig.update_layout(**PLOT_LAYOUT, height=420)
                    st.plotly_chart(_scat2_fig, use_container_width=True)

            # Shooting splits table
            st.markdown("<div class='section-hdr'>Shooting Splits — All Players</div>",
                        unsafe_allow_html=True)
            _sh_sp_c = ["Player","GP","FG%","2P%","3P%","FT%",
                        "eFG%","TS%","3PAr","FTr","PPS","PPSA","ShotRat"]
            _sh_sp_s = [c for c in _sh_sp_c if c in _team_rnk.columns]
            if _sh_sp_s:
                st.dataframe(
                    _team_rnk[_sh_sp_s].sort_values("TS%", ascending=False)
                    .reset_index(drop=True),
                    use_container_width=True, hide_index=True)

            # Grouped efficiency bars
            st.markdown("<div class='section-hdr'>Shooting Efficiency Comparison</div>",
                        unsafe_allow_html=True)
            _eff_v = [(c, cl) for c, cl in [
                ("eFG%","#f0a500"),("TS%","#2ecc71"),("FG%","#3498db"),("3P%","#9b59b6")
            ] if c in _team_rnk.columns]
            if _eff_v:
                _eff_s = _team_rnk.sort_values("TS%", ascending=False)
                fig_effsh = go.Figure()
                for _esc, _esclr in _eff_v:
                    fig_effsh.add_trace(go.Bar(
                        name=_esc, x=_eff_s["Player"], y=_eff_s[_esc],
                        marker_color=_esclr, width=0.2))
                fig_effsh.update_layout(
                    **PLOT_LAYOUT, barmode="group",
                    title="FG% / eFG% / TS% / 3P% — All Players",
                    yaxis_title="%", height=320,
                    xaxis=dict(tickangle=-20),
                    legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig_effsh, use_container_width=True)

            # Shot selection profile
            if "PaintFG%" in _team_rnk.columns and "3PAr" in _team_rnk.columns:
                st.markdown("<div class='section-hdr'>Shot Selection Profile</div>",
                            unsafe_allow_html=True)
                _ss_cols = ["Player","3PAr","PaintFG%","PaintFGA","2P%","FTr"]
                _ss_show = [c for c in _ss_cols if c in _team_rnk.columns]
                st.dataframe(
                    _team_rnk[_ss_show].sort_values("3PAr", ascending=False)
                    .reset_index(drop=True),
                    use_container_width=True, hide_index=True)
                if all(c in _team_rnk.columns for c in ["3PAr","PaintFGA","PTS"]):
                    _sel_sc = _team_rnk.dropna(subset=["3PAr","PaintFGA"]).copy()
                    if not _sel_sc.empty:
                        fig_sel = px.scatter(
                            _sel_sc, x="3PAr", y="PaintFGA", color="PTS",
                            text="Player", color_continuous_scale="Greens",
                            labels={"3PAr":"3PA Rate (%)","PaintFGA":"Paint FGA/G"},
                            title="Shot Selection: 3-Point Rate vs Paint Volume")
                        fig_sel.update_traces(textposition="top center", textfont_size=9)
                        fig_sel.update_layout(**PLOT_LAYOUT, height=400)
                        st.plotly_chart(fig_sel, use_container_width=True)

        with _pr_s3:
            # Advanced metrics table
            st.markdown("<div class='section-hdr'>Advanced Metrics</div>",
                        unsafe_allow_html=True)
            _adv_c = ["Player","GP","MIN","GS","EFF","FIC","PRF",
                      "AST%","AST/TOV","OREB%","DREB%","TRB%",
                      "DSh%","Stocks","TOV%","USG","PPS","PPSA","FTr","Q4 PPG"]
            _adv_s = [c for c in _adv_c if c in _team_rnk.columns]
            if _adv_s:
                _adv_sort_col = "EFF" if "EFF" in _team_rnk.columns else "GS"
                st.dataframe(
                    _team_rnk[_adv_s].sort_values(_adv_sort_col, ascending=False)
                    .reset_index(drop=True),
                    use_container_width=True, hide_index=True)
                st.caption(
                    "**GS** Game Score · **EFF** NBA Efficiency (PTS+REB+AST+STL+BLK−Misses−TOV) · "
                    "**FIC** Floor Impact Counter · **PRF** Pts Responsible For (PTS+AST×2) · "
                    "**AST%** % of teammate FGMs assisted on-court · "
                    "**PPS** Pts Per Shot · **PPSA** Pts Per Scoring Attempt · **FTr** FTA/FGA")

            # EFF / FIC / GS grouped bar
            _ab_v = [(c,cl) for c,cl in [("EFF","#f0a500"),("FIC","#2ecc71"),("GS","#3498db")]
                     if c in _team_rnk.columns]
            if _ab_v:
                st.markdown("<div class='section-hdr'>Composite Impact Scores</div>",
                            unsafe_allow_html=True)
                _ab_s = _team_rnk.sort_values(_ab_v[0][0], ascending=False)
                fig_adv = go.Figure()
                for _abc, _abclr in _ab_v:
                    fig_adv.add_trace(go.Bar(
                        name=_abc, x=_ab_s["Player"], y=_ab_s[_abc],
                        marker_color=_abclr, width=0.25))
                fig_adv.update_layout(
                    **PLOT_LAYOUT, barmode="group",
                    title="EFF / FIC / Game Score per Game",
                    yaxis_title="Score", height=320,
                    xaxis=dict(tickangle=-20),
                    legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(fig_adv, use_container_width=True)

            # Per-32 min stats
            _p32_c = ["Player","GP","MIN","PTS32","REB32","AST32",
                      "STL32","BLK32","TOV32","SC32"]
            _p32_s = [c for c in _p32_c if c in _team_rnk.columns]
            if "PTS32" in _p32_s:
                st.markdown("<div class='section-hdr'>Per-32 Minute Stats (min 5 min/G)</div>",
                            unsafe_allow_html=True)
                _p32_df = _team_rnk[_p32_s].dropna(subset=["PTS32"])
                if not _p32_df.empty:
                    st.dataframe(
                        _p32_df.sort_values("PTS32", ascending=False)
                        .reset_index(drop=True),
                        use_container_width=True, hide_index=True)

            # Ratings breakdown + radar
            if not _team_rat.empty:
                st.markdown(
                    "<div class='section-hdr'>Ratings Breakdown (OFF/DEF/PLY/REB)</div>",
                    unsafe_allow_html=True)
                _rfd_c = ["Player","OVRL","OFF","_OFF_shoot","_OFF_finish","DEF","PLY","REB_R"]
                _rfd_s = [c for c in _rfd_c if c in _team_rat.columns]
                st.dataframe(
                    _team_rat[_rfd_s].sort_values("OVRL", ascending=False)
                    .reset_index(drop=True),
                    use_container_width=True, hide_index=True)
                st.caption("All ratings 0–100 vs full player pool. "
                           "OFF = avg of Shooting + Finishing sub-scores.")

                _radar_cats_all = ["OFF","DEF","PLY","REB_R","OVRL"]
                _radar_lbls_all = ["Offense","Defense","Playmaking","Rebounding","Overall"]
                _rv_all = [(l,c) for l,c in zip(_radar_lbls_all, _radar_cats_all)
                           if c in _team_rat.columns]
                if _rv_all and len(_team_rat) > 0:
                    st.markdown("<div class='section-hdr'>Team Radar Overview</div>",
                                unsafe_allow_html=True)
                    _rl_all = [l for l,_ in _rv_all] + [[l for l,_ in _rv_all][0]]
                    fig_radar_all = go.Figure()
                    for __, _rat_row in _team_rat.sort_values("OVRL",ascending=False).iterrows():
                        _rv_row = [float(_rat_row.get(c,0)) for _,c in _rv_all]
                        fig_radar_all.add_trace(go.Scatterpolar(
                            r=_rv_row+[_rv_row[0]], theta=_rl_all,
                            fill="toself", name=_rat_row["Player"],
                            opacity=0.65, line=dict(width=1.8)))
                    fig_radar_all.update_layout(
                        **PLOT_LAYOUT,
                        polar=dict(radialaxis=dict(
                            visible=True, range=[0,100], tickfont=dict(size=8))),
                        title="All Players — Rating Radar",
                        height=520,
                        legend=dict(orientation="v", x=1.05, y=0.5))
                    st.plotly_chart(fig_radar_all, use_container_width=True)

        with _pr_s4:
            # Head-to-head comparison
            st.markdown("<div class='section-hdr'>Head-to-Head Comparison</div>",
                        unsafe_allow_html=True)
            _cmp_pl = _team_rnk["Player"].tolist() if "Player" in _team_rnk.columns else []
            if len(_cmp_pl) < 2:
                st.info("Need at least 2 players with tracked stats.")
            else:
                _cmp_ca, _cmp_cb = st.columns(2)
                _pl_a = _cmp_ca.selectbox("Player A", _cmp_pl, index=0, key="cmp_pl_a")
                _pl_b = _cmp_cb.selectbox(
                    "Player B", _cmp_pl, index=min(1,len(_cmp_pl)-1), key="cmp_pl_b")

                _rowa = (_team_rnk[_team_rnk["Player"]==_pl_a].iloc[0]
                         if _pl_a in _team_rnk["Player"].values else None)
                _rowb = (_team_rnk[_team_rnk["Player"]==_pl_b].iloc[0]
                         if _pl_b in _team_rnk["Player"].values else None)

                if _rowa is not None and _rowb is not None:
                    _cmp_def = [
                        ("PTS","Points/G",True), ("AST","Assists/G",True),
                        ("REB","Rebounds/G",True), ("OREB","Off Reb/G",True),
                        ("DREB","Def Reb/G",True), ("STL","Steals/G",True),
                        ("BLK","Blocks/G",True), ("TOV","Turnovers/G",False),
                        ("FG%","FG%",True), ("3P%","3P%",True), ("FT%","FT%",True),
                        ("TS%","True Shooting%",True), ("eFG%","eFG%",True),
                        ("GS","Game Score",True), ("EFF","NBA Efficiency",True),
                        ("FIC","Floor Impact Counter",True),
                        ("PRF","Pts Responsible For",True),
                        ("+/-","Plus/Minus",True), ("SC","Shot Creations/G",True),
                        ("AST/TOV","AST/TOV Ratio",True),
                        ("DSh%","Shot Contest Rate",True),
                        ("Stocks","Stocks/G (STL+BLK)",True),
                        ("AST%","Assist Rate (on-court)",True),
                        ("OREB%","OREB Rate",True), ("DREB%","DREB Rate",True),
                        ("Q4 PPG","4th Qtr PPG",True), ("MIN","Min per Game",True),
                    ]
                    _cmp_rows_pl = []
                    for _cc, _cl, _hib_c in _cmp_def:
                        if _cc not in _team_rnk.columns:
                            continue
                        _va = _rowa.get(_cc)
                        _vb = _rowb.get(_cc)
                        if pd.isna(_va) or pd.isna(_vb):
                            continue
                        _va, _vb = float(_va), float(_vb)
                        _aw = (_va>=_vb) if _hib_c else (_va<=_vb)
                        def _fv(v, c_):
                            return (f"{v:+.1f}" if c_=="+/-"
                                    else f"{v:.1f}{'%' if '%' in c_ else ''}")
                        _cmp_rows_pl.append({
                            _pl_a: ("✅ " if _aw  else "")+_fv(_va,_cc),
                            "Stat": _cl,
                            _pl_b: ("✅ " if not _aw else "")+_fv(_vb,_cc),
                        })
                    if _cmp_rows_pl:
                        st.dataframe(
                            pd.DataFrame(_cmp_rows_pl).set_index("Stat"),
                            use_container_width=True)

                    # Side-by-side bar
                    _bv = [(l,c) for l,c in [
                        ("PTS","PTS"),("AST","AST"),("REB","REB"),
                        ("STL","STL"),("BLK","BLK"),("TOV","TOV")]
                        if c in _team_rnk.columns]
                    if _bv:
                        st.markdown("<div class='section-hdr'>Side-by-Side Bar</div>",
                                    unsafe_allow_html=True)
                        fig_barcmp = go.Figure()
                        fig_barcmp.add_trace(go.Bar(
                            name=_pl_a,
                            x=[l for l,_ in _bv],
                            y=[float(_rowa.get(c,0)) for _,c in _bv],
                            marker_color="#f0a500",
                            text=[f"{float(_rowa.get(c,0)):.1f}" for _,c in _bv],
                            textposition="outside"))
                        fig_barcmp.add_trace(go.Bar(
                            name=_pl_b,
                            x=[l for l,_ in _bv],
                            y=[float(_rowb.get(c,0)) for _,c in _bv],
                            marker_color="#3498db",
                            text=[f"{float(_rowb.get(c,0)):.1f}" for _,c in _bv],
                            textposition="outside"))
                        fig_barcmp.update_layout(
                            **PLOT_LAYOUT, barmode="group",
                            title=f"{_pl_a} vs {_pl_b} — Per Game",
                            yaxis_title="Per Game", height=340,
                            legend=dict(orientation="h", y=-0.15))
                        st.plotly_chart(fig_barcmp, use_container_width=True)

                    # Shooting radar
                    _sh_rad_c = ["FG%","3P%","FT%","TS%","eFG%"]
                    if all(c in _team_rnk.columns for c in _sh_rad_c):
                        st.markdown("<div class='section-hdr'>Shooting Radar</div>",
                                    unsafe_allow_html=True)
                        _sha = [float(_rowa.get(c,0)) for c in _sh_rad_c]
                        _shb = [float(_rowb.get(c,0)) for c in _sh_rad_c]
                        _sh_th = _sh_rad_c + [_sh_rad_c[0]]
                        fig_shrad = go.Figure()
                        fig_shrad.add_trace(go.Scatterpolar(
                            r=_sha+[_sha[0]], theta=_sh_th,
                            fill="toself", name=_pl_a,
                            line=dict(color="#f0a500",width=2),
                            fillcolor="rgba(240,165,0,0.15)"))
                        fig_shrad.add_trace(go.Scatterpolar(
                            r=_shb+[_shb[0]], theta=_sh_th,
                            fill="toself", name=_pl_b,
                            line=dict(color="#3498db",width=2),
                            fillcolor="rgba(52,152,219,0.15)"))
                        fig_shrad.update_layout(
                            **PLOT_LAYOUT,
                            polar=dict(radialaxis=dict(
                                visible=True, range=[0,100], tickfont=dict(size=9))),
                            title="Shooting % Radar", height=400,
                            legend=dict(orientation="h", y=-0.1))
                        st.plotly_chart(fig_shrad, use_container_width=True)

                    # Overall ratings radar
                    _ratra = (_team_rat[_team_rat["Player"]==_pl_a].iloc[0]
                              if (not _team_rat.empty and
                                  _pl_a in _team_rat["Player"].values) else None)
                    _ratrb = (_team_rat[_team_rat["Player"]==_pl_b].iloc[0]
                              if (not _team_rat.empty and
                                  _pl_b in _team_rat["Player"].values) else None)
                    if _ratra is not None and _ratrb is not None:
                        st.markdown("<div class='section-hdr'>Overall Ratings Radar</div>",
                                    unsafe_allow_html=True)
                        _ovr_c = ["OFF","DEF","PLY","REB_R","OVRL"]
                        _ovr_l = ["Offense","Defense","Playmaking","Rebounding","Overall"]
                        _ovr_v = [(l,c) for l,c in zip(_ovr_l,_ovr_c)
                                  if c in _team_rat.columns]
                        if _ovr_v:
                            _ovr_th = [l for l,_ in _ovr_v]+[[l for l,_ in _ovr_v][0]]
                            _ovra = [float(_ratra.get(c,0)) for _,c in _ovr_v]
                            _ovrb = [float(_ratrb.get(c,0)) for _,c in _ovr_v]
                            fig_ovrrad = go.Figure()
                            fig_ovrrad.add_trace(go.Scatterpolar(
                                r=_ovra+[_ovra[0]], theta=_ovr_th,
                                fill="toself", name=_pl_a,
                                line=dict(color="#f0a500",width=2),
                                fillcolor="rgba(240,165,0,0.15)"))
                            fig_ovrrad.add_trace(go.Scatterpolar(
                                r=_ovrb+[_ovrb[0]], theta=_ovr_th,
                                fill="toself", name=_pl_b,
                                line=dict(color="#3498db",width=2),
                                fillcolor="rgba(52,152,219,0.15)"))
                            fig_ovrrad.update_layout(
                                **PLOT_LAYOUT,
                                polar=dict(radialaxis=dict(
                                    visible=True, range=[0,100], tickfont=dict(size=9))),
                                title=f"{_pl_a} vs {_pl_b} — Overall Ratings",
                                height=440,
                                legend=dict(orientation="h", y=-0.1))
                            st.plotly_chart(fig_ovrrad, use_container_width=True)

    st.divider()

    # ── Individual player breakdown ──────────────────────────────────────────
    _pl_list = query(
        "SELECT id, name, number FROM players "
        "WHERE team_id=? AND archived=0 ORDER BY name",
        (team_id,))

    if not _pl_list:
        st.info("No players on this roster.")
    else:
        _pl_names_map = {f"#{p['number']} {p['name']}": p["id"] for p in _pl_list}
        _sel_pl_key = st.selectbox(
            "Select Player", list(_pl_names_map.keys()), key="ta_pl_sel")
        _sel_pl_id = _pl_names_map[_sel_pl_key]
        _sel_pl_info = next(p for p in _pl_list if p["id"] == _sel_pl_id)

        career = compute_player_career(_sel_pl_id)

        if not career:
            st.info(f"No tracked data for {_sel_pl_info['name']} yet.")
        else:
            gp_pl = career["gp"]
            _pl_row = _team_rnk[_team_rnk["pid"] == _sel_pl_id] if (
                not _team_rnk.empty and "pid" in _team_rnk.columns) else pd.DataFrame()
            _pl_rat_row = _team_rat[_team_rat["pid"] == _sel_pl_id] if (
                not _team_rat.empty and "pid" in _team_rat.columns) else pd.DataFrame()

            # ── Player hero ──────────────────────────────────────────────────
            _ovrl_val = float(_pl_rat_row["OVRL"].iloc[0]) if not _pl_rat_row.empty and "OVRL" in _pl_rat_row else None
            st.markdown(
                f"<div class='pl-hero'>"
                f"<div class='pl-name'>#{_sel_pl_info['number']} {_sel_pl_info['name']}</div>"
                f"<div class='pl-meta'>#{_sel_pl_info['number']} · "
                f"{gp_pl} tracked games"
                f"{f' · OVRL {_ovrl_val:.1f}' if _ovrl_val else ''}</div>"
                f"</div>", unsafe_allow_html=True)

            pl_t1, pl_t2, pl_t3, pl_t4, pl_t5 = st.tabs([
                "📊 Stats", "🎯 Shot Quality", "🛡️ Defense", "📡 On/Off", "📈 Charts"
            ])

            # ── Stats ────────────────────────────────────────────────────────
            with pl_t1:
                _pts_pg = career["pts"] / gp_pl
                _ast_pg = career["ast"] / gp_pl
                _reb_pg = (career["oreb"] + career["dreb"]) / gp_pl
                _stl_pg = career["stl"] / gp_pl
                _blk_pg = career["blk"] / gp_pl
                _tov_pg = career["tov"] / gp_pl
                _fgp    = career["fgm"] / career["fga"] * 100 if career["fga"] else 0
                _tpp    = career["tpm"] / career["tpa"] * 100 if career["tpa"] else 0
                _ftp    = career["ftm"] / career["fta"] * 100 if career["fta"] else 0
                _ts     = career["pts"] / (2 * (career["fga"] + 0.44 * career["fta"])) * 100 if (career["fga"] + 0.44 * career["fta"]) else 0
                _efg    = (career["fgm"] + 0.5 * career["tpm"]) / career["fga"] * 100 if career["fga"] else 0
                _pm_pg  = career["plus_minus"] / gp_pl

                _stat_items = [
                    ("PTS", f"{_pts_pg:.1f}"), ("AST", f"{_ast_pg:.1f}"),
                    ("REB", f"{_reb_pg:.1f}"), ("STL", f"{_stl_pg:.1f}"),
                    ("BLK", f"{_blk_pg:.1f}"), ("TOV", f"{_tov_pg:.1f}"),
                    ("FG%", f"{_fgp:.1f}%"),   ("3P%", f"{_tpp:.1f}%"),
                    ("FT%", f"{_ftp:.1f}%"),   ("TS%", f"{_ts:.1f}%"),
                    ("eFG%", f"{_efg:.1f}%"),  ("+/-", f"{_pm_pg:+.1f}"),
                ]
                grid_html = "<div class='stat-grid'>" + "".join(
                    f"<div class='stat-cell'>"
                    f"<div class='stat-cell-val'>{v}</div>"
                    f"<div class='stat-cell-lbl'>{l}</div>"
                    f"</div>"
                    for l, v in _stat_items
                ) + "</div>"
                st.markdown(grid_html, unsafe_allow_html=True)

                # Ratings row
                if not _pl_rat_row.empty:
                    st.markdown("<div class='section-hdr'>Ratings</div>", unsafe_allow_html=True)
                    _rat_items = [("OVRL","OVRL","#f0a500"), ("OFF","OFF","#2ecc71"),
                                  ("DEF","DEF","#3498db"), ("PLY","PLY","#9b59b6"),
                                  ("REB_R","REB","#e67e22")]
                    _rat_cols = st.columns(5)
                    for _rc2, (col_key, lbl2, color2) in zip(_rat_cols, _rat_items):
                        if col_key in _pl_rat_row.columns:
                            _rv = float(_pl_rat_row[col_key].iloc[0])
                            _rc2.markdown(
                                f"<div class='adv-tile'>"
                                f"<div class='adv-label'>{lbl2}</div>"
                                f"<div class='adv-value' style='color:{color2}'>{_rv:.1f}</div>"
                                f"<div style='background:#21262d;border-radius:3px;height:5px;overflow:hidden;margin-top:6px'>"
                                f"<div style='background:{color2};width:{_rv}%;height:100%;border-radius:3px'></div>"
                                f"</div>"
                                f"</div>", unsafe_allow_html=True)

            # ── Shot Quality ─────────────────────────────────────────────────
            with pl_t2:
                _xfg = career["est_fg_sum"] / career["est_fg_shots"] * 100 if career["est_fg_shots"] else None
                _sr  = career["shot_rating"] / career["fga"] if career["fga"] else None
                _sc_pct = career["sc"] / (career["sc"] + 1) * 100 if career["sc"] else 0

                _sc_total = career["sc"] or 1
                _sq_metrics = [
                    ("XFG%", f"{_xfg:.1f}%" if _xfg else "—",    "expected FG% by zone/context"),
                    ("Shot Rating", f"{_sr:.2f}" if _sr else "—", "avg shot quality score"),
                    ("SC Actions", career["sc"],                    "shots + assists + creation"),
                    ("SC/FGA", f"{career['sc']/(career['fga']+0.01):.2f}", "SC actions per FGA (scorer+passer+creator)"),
                    ("SCS%", f"{career.get('scs',0)/_sc_total*100:.0f}%", "SC from own shot"),
                    ("SCP%", f"{career.get('scp',0)/_sc_total*100:.0f}%", "SC from pass/assist"),
                    ("SCO%", f"{career.get('sco',0)/_sc_total*100:.0f}%", "SC from shot creation"),
                ]
                _sq_c = st.columns(7)
                for _sqc, (lbl3, val3, sub3) in zip(_sq_c, _sq_metrics):
                    _sqc.markdown(
                        f"<div class='adv-tile'>"
                        f"<div class='adv-label'>{lbl3}</div>"
                        f"<div class='adv-value'>{val3}</div>"
                        f"<div style='font-size:10px;color:#8b949e'>{sub3}</div>"
                        f"</div>", unsafe_allow_html=True)

                if career["shots"]:
                    st.markdown("<div class='section-hdr'>Offensive Shot Chart</div>",
                                unsafe_allow_html=True)
                    render_hot_zones(career["shots"], title=f"{_sel_pl_info['name']} — Shot Zones")

            # ── Defense ──────────────────────────────────────────────────────
            with pl_t3:
                _dfga = career["def_fga"]
                _dfgm = career["def_fgm"]
                _d3pa = career["def_3pa"]
                _d3pm = career["def_3pm"]
                _dsh_pct  = (1 - _dfgm / _dfga) * 100 if _dfga else None
                _d3sh_pct = (1 - _d3pm / _d3pa) * 100 if _d3pa else None
                _ocs = career["on_court_opp_shots"]
                _cnt_rt   = _dfga / _ocs * 100 if _ocs else None

                _def_items = [
                    ("Shots Defended", _dfga,                                  "opponent FGA guarded"),
                    ("Def FG%",        f"{(_dfgm/_dfga*100):.1f}%" if _dfga else "—", "opp FG% when guarded"),
                    ("DSh%",           f"{_dsh_pct:.1f}%" if _dsh_pct else "—", "shots defended %"),
                    ("Def 3P%",        f"{(_d3pm/_d3pa*100):.1f}%" if _d3pa else "—", "opp 3P% when guarded"),
                    ("Contest Rate",   f"{_cnt_rt:.1f}%" if _cnt_rt else "—",  "contests / on-court opp shots"),
                ]
                _def_c = st.columns(5)
                for _dc2, (lbl4, val4, sub4) in zip(_def_c, _def_items):
                    _dc2.markdown(
                        f"<div class='adv-tile'>"
                        f"<div class='adv-label'>{lbl4}</div>"
                        f"<div class='adv-value'>{val4}</div>"
                        f"<div style='font-size:10px;color:#8b949e'>{sub4}</div>"
                        f"</div>", unsafe_allow_html=True)

                if career["def_shots"]:
                    st.markdown("<div class='section-hdr'>Defensive Shot Chart (Shots Guarded)</div>",
                                unsafe_allow_html=True)
                    render_hot_zones(career["def_shots"],
                                     title=f"{_sel_pl_info['name']} — Defended Shots")

            # ── On/Off ───────────────────────────────────────────────────────
            with pl_t4:
                _onoff = compute_on_off(team_id)
                _p_oo  = _onoff.get(_sel_pl_id)

                if not _p_oo or _p_oo["on_poss"] == 0:
                    st.info("Not enough on/off data — need lineup snapshots.")
                else:
                    _on_poss  = _p_oo["on_poss"]
                    _off_poss = _p_oo["off_poss"]
                    _ortg_on  = _p_oo["on_pts_for"]   / _on_poss  * 100 if _on_poss  else 0
                    _drtg_on  = _p_oo["on_pts_against"]/ _on_poss  * 100 if _on_poss  else 0
                    _net_on   = _ortg_on - _drtg_on
                    _ortg_off = _p_oo["off_pts_for"]  / _off_poss * 100 if _off_poss else 0
                    _drtg_off = _p_oo["off_pts_against"]/ _off_poss* 100 if _off_poss else 0
                    _net_off  = _ortg_off - _drtg_off
                    _oo_delta = _net_on - _net_off
                    _usg      = _p_oo["poss_used"] / _on_poss * 100 if _on_poss else 0

                    _oo_c = st.columns(4)
                    for _ooc, (lbl5, val5, sub5, _signed) in zip(_oo_c, [
                        ("Net ON",   f"{_net_on:+.1f}",   f"ORtg {_ortg_on:.1f} / DRtg {_drtg_on:.1f}", True),
                        ("Net OFF",  f"{_net_off:+.1f}",  f"ORtg {_ortg_off:.1f} / DRtg {_drtg_off:.1f}", True),
                        ("On/Off",   f"{_oo_delta:+.1f}", "impact on net rating", True),
                        ("USG%",     f"{_usg:.1f}%",      "possessions used", False),
                    ]):
                        if _signed:
                            try:
                                _color_oo = "#2ecc71" if float(str(val5).replace("+","").replace("%","")) > 0 else "#e74c3c"
                            except ValueError:
                                _color_oo = "#58a6ff"
                        else:
                            _color_oo = "#58a6ff"
                        _ooc.markdown(
                            f"<div class='adv-tile'>"
                            f"<div class='adv-label'>{lbl5}</div>"
                            f"<div class='adv-value' style='color:{_color_oo}'>{val5}</div>"
                            f"<div style='font-size:10px;color:#8b949e'>{sub5}</div>"
                            f"</div>", unsafe_allow_html=True)

                    st.write("")
                    st.markdown("<div class='section-hdr'>On/Off Team Stats Comparison</div>",
                                unsafe_allow_html=True)
                    _oo_tbl = pd.DataFrame([
                        {"Split": "On Court",  "Poss": _on_poss,  "ORtg": round(_ortg_on,1),
                         "DRtg": round(_drtg_on,1), "Net": round(_net_on,1)},
                        {"Split": "Off Court", "Poss": _off_poss, "ORtg": round(_ortg_off,1),
                         "DRtg": round(_drtg_off,1), "Net": round(_net_off,1)},
                        {"Split": "Δ Impact",  "Poss": "—",
                         "ORtg": round(_ortg_on - _ortg_off, 1),
                         "DRtg": round(_drtg_on - _drtg_off, 1),
                         "Net":  round(_oo_delta, 1)},
                    ])
                    st.dataframe(_oo_tbl, use_container_width=True, hide_index=True)

            # ── Charts ───────────────────────────────────────────────────────
            with pl_t5:
                _pl_log = compute_player_game_log(_sel_pl_id, team_id)
                if not _pl_log:
                    st.info("No game log data for this player.")
                else:
                    _log_df = pd.DataFrame(_pl_log)

                    # Build labels (game log uses capitalized keys: Date, Opp, W/L)
                    _log_labels = []
                    for _lr in _pl_log:
                        try:
                            _ld = datetime.strptime(_lr["Date"], "%Y-%m-%d").strftime("%b %d")
                        except Exception:
                            _ld = _lr.get("Date", "—")
                        _log_labels.append(f"{_ld} vs {_lr.get('Opp','?')}")

                    # Win/loss colors
                    _colors_res = ["#2ecc71" if r == "W" else "#e74c3c"
                                   for r in (_log_df["W/L"].tolist()
                                             if "W/L" in _log_df.columns
                                             else [""] * len(_log_df))]

                    # PTS trend
                    if "PTS" in _log_df.columns:
                        fig_pts_trend = go.Figure()
                        fig_pts_trend.add_trace(go.Bar(
                            x=_log_labels, y=_log_df["PTS"],
                            name="PTS", marker_color=_colors_res, opacity=0.85,
                        ))
                        fig_pts_trend.update_layout(
                            **PLOT_LAYOUT, title="Points per Game",
                            yaxis_title="Points", height=280,
                            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                        )
                        st.plotly_chart(fig_pts_trend, use_container_width=True)

                    # AST + REB + TOV trend
                    if all(c in _log_df.columns for c in ["AST", "REB", "TOV"]):
                        fig_multi = go.Figure()
                        fig_multi.add_trace(go.Scatter(
                            x=_log_labels, y=_log_df["AST"],
                            name="AST", mode="lines+markers",
                            line=dict(color="#3498db", width=2), marker=dict(size=5),
                        ))
                        fig_multi.add_trace(go.Scatter(
                            x=_log_labels, y=_log_df["REB"],
                            name="REB", mode="lines+markers",
                            line=dict(color="#2ecc71", width=2), marker=dict(size=5),
                        ))
                        fig_multi.add_trace(go.Scatter(
                            x=_log_labels, y=_log_df["TOV"],
                            name="TOV", mode="lines+markers",
                            line=dict(color="#e74c3c", width=2, dash="dot"), marker=dict(size=5),
                        ))
                        fig_multi.update_layout(
                            **PLOT_LAYOUT, title="AST / REB / TOV per Game",
                            yaxis_title="Count", height=280,
                            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                            legend=dict(orientation="h", y=-0.25),
                        )
                        st.plotly_chart(fig_multi, use_container_width=True)

                    # FG% trend
                    if all(c in _log_df.columns for c in ["FGM", "FGA"]):
                        _career_fgp = career["fgm"] / career["fga"] * 100 if career["fga"] else 0
                        _log_df["fgp_game"] = _log_df.apply(
                            lambda r: r["FGM"] / r["FGA"] * 100 if r["FGA"] else 0, axis=1)
                        fig_fgp = go.Figure(go.Scatter(
                            x=_log_labels, y=_log_df["fgp_game"],
                            name="FG%", mode="lines+markers",
                            line=dict(color="#f0a500", width=2), marker=dict(size=6),
                        ))
                        fig_fgp.add_hline(y=_career_fgp, line_dash="dot", line_color="#555d68",
                                          annotation_text=f"Avg {_career_fgp:.1f}%")
                        fig_fgp.update_layout(
                            **PLOT_LAYOUT, title="FG% per Game",
                            yaxis_title="FG%", height=260,
                            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                        )
                        st.plotly_chart(fig_fgp, use_container_width=True)

                    # STL + BLK trend
                    if all(c in _log_df.columns for c in ["STL", "BLK"]):
                        fig_def = go.Figure()
                        fig_def.add_trace(go.Bar(
                            x=_log_labels, y=_log_df["STL"],
                            name="STL", marker_color="#9b59b6", opacity=0.85,
                        ))
                        fig_def.add_trace(go.Bar(
                            x=_log_labels, y=_log_df["BLK"],
                            name="BLK", marker_color="#3498db", opacity=0.85,
                        ))
                        fig_def.update_layout(
                            **PLOT_LAYOUT, title="STL / BLK per Game",
                            yaxis_title="Count", height=260, barmode="group",
                            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                            legend=dict(orientation="h", y=-0.25),
                        )
                        st.plotly_chart(fig_def, use_container_width=True)

                    # +/- trend
                    if "+/-" in _log_df.columns:
                        _pm_colors = ["#2ecc71" if v >= 0 else "#e74c3c"
                                      for v in _log_df["+/-"]]
                        fig_pm = go.Figure(go.Bar(
                            x=_log_labels, y=_log_df["+/-"],
                            marker_color=_pm_colors, opacity=0.85, name="+/-",
                        ))
                        fig_pm.add_hline(y=0, line_color="#555d68", line_width=1)
                        fig_pm.update_layout(
                            **PLOT_LAYOUT, title="+/- per Game",
                            yaxis_title="+/-", height=260,
                            xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                        )
                        st.plotly_chart(fig_pm, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — LINEUPS
# ══════════════════════════════════════════════════════════════════════════════
with tab_lu:
    _rat_all_lu = compute_player_ratings()
    _rnk_all_lu = compute_player_rankings()

    _team_rat_lu = pd.DataFrame()
    _team_rnk_lu = pd.DataFrame()
    if not _rat_all_lu.empty and "Team" in _rat_all_lu.columns:
        _team_rat_lu = _rat_all_lu[_rat_all_lu["Team"] == sel_name].copy()
    if not _rnk_all_lu.empty and "Team" in _rnk_all_lu.columns:
        _team_rnk_lu = _rnk_all_lu[_rnk_all_lu["Team"] == sel_name].copy()

    # ── Player Ratings Grid ──────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Player Ratings</div>", unsafe_allow_html=True)
    st.caption("All ratings normalized 0–100 relative to the entire player pool.")

    if _team_rat_lu.empty:
        st.info("No tracked player ratings for this team yet.")
    else:
        _rat_display_cols = ["Player", "#", "GP", "OVRL", "OFF", "DEF", "PLY", "REB_R"]
        _rat_show = [c for c in _rat_display_cols if c in _team_rat_lu.columns]
        _rat_sorted = _team_rat_lu[_rat_show].sort_values("OVRL", ascending=False).reset_index(drop=True)
        st.dataframe(_rat_sorted, use_container_width=True, hide_index=True)

        # Visual rating bars per player
        _rat_bar_cols = ["OVRL", "OFF", "DEF", "PLY", "REB_R"]
        _rat_bar_colors = {
            "OVRL": "#f0a500", "OFF": "#2ecc71", "DEF": "#3498db",
            "PLY": "#9b59b6", "REB_R": "#e67e22",
        }
        _player_names_lu = _team_rat_lu["Player"].tolist() if "Player" in _team_rat_lu.columns else []

        if len(_player_names_lu) > 0:
            fig_rat_bar = go.Figure()
            for _bcol in _rat_bar_cols:
                if _bcol not in _team_rat_lu.columns:
                    continue
                _sorted_team = _team_rat_lu.sort_values("OVRL", ascending=False)
                fig_rat_bar.add_trace(go.Bar(
                    name=_bcol,
                    x=_sorted_team["Player"],
                    y=_sorted_team[_bcol],
                    marker_color=_rat_bar_colors.get(_bcol, "#888"),
                    width=0.15,
                ))
            fig_rat_bar.update_layout(
                **PLOT_LAYOUT,
                title="Player Ratings — All Categories",
                barmode="group",
                yaxis=dict(title="Rating (0–100)", range=[0, 110]),
                xaxis=dict(tickangle=-20),
                height=360,
                legend=dict(orientation="h", y=-0.15),
            )
            st.plotly_chart(fig_rat_bar, use_container_width=True)

    st.divider()

    # ── On/Off Impact Table ──────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Player On/Off Impact</div>", unsafe_allow_html=True)

    _onoff_lu = compute_on_off(team_id)
    if not _onoff_lu:
        st.info("No on/off data — need tracked games with lineup snapshots.")
    else:
        _pl_info_lu = query(
            "SELECT id, name, number FROM players WHERE team_id=? AND archived=0",
            (team_id,))
        _oo_rows = []
        for _plr in _pl_info_lu:
            _pid2 = _plr["id"]
            _oo = _onoff_lu.get(_pid2, {})
            _onp  = _oo.get("on_poss", 0)
            _offp = _oo.get("off_poss", 0)
            if _onp == 0:
                continue
            _or_on  = _oo["on_pts_for"]   / _onp  * 100
            _dr_on  = _oo["on_pts_against"]/ _onp  * 100
            _net_on2 = _or_on - _dr_on
            _or_off = _oo["off_pts_for"]  / _offp * 100 if _offp else 0
            _dr_off = _oo["off_pts_against"]/ _offp* 100 if _offp else 0
            _net_off2= _or_off - _dr_off
            _oo_rows.append({
                "Player": f"#{_plr['number']} {_plr['name']}",
                "On Poss": _onp,
                "On ORtg": round(_or_on, 1),
                "On DRtg": round(_dr_on, 1),
                "On Net":  round(_net_on2, 1),
                "Off Net": round(_net_off2, 1),
                "On/Off Δ": round(_net_on2 - _net_off2, 1),
                "USG%":    round(_oo.get("poss_used", 0) / _onp * 100, 1),
            })

        if _oo_rows:
            _oo_df = pd.DataFrame(_oo_rows).sort_values("On/Off Δ", ascending=False)
            st.dataframe(_oo_df, use_container_width=True, hide_index=True)
        else:
            st.info("No on/off splits calculated.")

    st.divider()

    # ── Lineup Builder / Injury Simulation ──────────────────────────────────
    st.markdown("<div class='section-hdr'>Lineup Builder & Injury Simulation</div>",
                unsafe_allow_html=True)
    st.caption("Select up to 5 players — mark injured/suspended players unavailable first.")

    # Use ratings (GP ≥ 2) for composite scores; fall back to rankings (GP ≥ 1)
    _has_ratings  = not _team_rat_lu.empty  and "Player" in _team_rat_lu.columns
    _has_rankings = not _team_rnk_lu.empty  and "Player" in _team_rnk_lu.columns

    if not (_has_ratings or _has_rankings):
        st.info("No tracked player stats available for this team yet. "
                "Players must appear in tracked game lineups to show here.")
    else:
        _lu_base_df     = _team_rat_lu if _has_ratings else _team_rnk_lu
        _all_lu_players = _lu_base_df["Player"].tolist()

        if not _has_ratings:
            st.caption("ℹ️ Composite ratings require ≥ 2 tracked games — showing raw stats.")

        _injured = st.multiselect(
            "Mark as Unavailable (injured / suspended)",
            _all_lu_players, key="lu_injured")
        _available = [p for p in _all_lu_players if p not in _injured]

        if len(_available) < 5:
            st.warning(f"Only {len(_available)} player(s) available — need at least 5.")
        else:
            _lineup_sel = st.multiselect(
                "Select Starting Lineup (5 players)",
                _available,
                default=_available[:5],
                max_selections=5,
                key="lu_sel5")

            if len(_lineup_sel) == 5:
                # ── Merge ratings + rankings for the 5 selected players ──────
                _rnk5 = (_team_rnk_lu[_team_rnk_lu["Player"].isin(_lineup_sel)].copy()
                         if _has_rankings else pd.DataFrame())
                _rat5 = (_team_rat_lu[_team_rat_lu["Player"].isin(_lineup_sel)].copy()
                         if _has_ratings  else pd.DataFrame())

                # Helper: safe column sum / weighted avg
                def _col_sum(df, col):
                    return float(df[col].sum()) if (not df.empty and col in df.columns) else 0.0
                def _col_mean(df, col):
                    return float(df[col].mean()) if (not df.empty and col in df.columns) else 0.0
                def _wavg_pct(df, num_col, den_col):
                    """Weighted average %: sum(num_col) / sum(den_col) * 100."""
                    if df.empty or num_col not in df.columns or den_col not in df.columns:
                        return 0.0
                    d = float(df[den_col].sum())
                    return float(df[num_col].sum()) / d * 100 if d else 0.0

                # ── Rating tiles ─────────────────────────────────────────────
                st.markdown("<div class='section-hdr'>Lineup Rating Averages</div>",
                            unsafe_allow_html=True)
                _rat_cfg = [("OVRL","Overall","#f0a500"),("OFF","Offense","#2ecc71"),
                            ("DEF","Defense","#3498db"),("PLY","Playmaking","#9b59b6"),
                            ("REB_R","Rebounding","#e67e22")]
                _rat_tile_cols = st.columns(5)
                for _rtc, (_rk, _rl, _rclr) in zip(_rat_tile_cols, _rat_cfg):
                    _rv = round(_col_mean(_rat5, _rk), 1) if _has_ratings else None
                    _rtc.markdown(
                        f"<div class='kpi-tile'>"
                        f"<div class='kpi-label'>{_rl}</div>"
                        f"<div class='kpi-value' style='color:{_rclr}'>"
                        f"{_rv if _rv is not None else '—'}</div>"
                        f"<div class='kpi-sub'>avg of 5</div>"
                        f"</div>", unsafe_allow_html=True)

                # ── Per-player breakdown table ────────────────────────────────
                st.markdown("<div class='section-hdr'>Player Breakdown</div>",
                            unsafe_allow_html=True)

                if _has_ratings and _has_rankings:
                    # Merge ratings cols onto rankings row
                    _rat_merge_cols = [c for c in
                                       ["Player","OVRL","OFF","DEF","PLY","REB_R"]
                                       if c in _rat5.columns]
                    _merged5 = _rnk5.merge(_rat5[_rat_merge_cols],
                                           on="Player", how="left")
                elif _has_rankings:
                    _merged5 = _rnk5.copy()
                else:
                    _merged5 = _rat5.copy()

                _detail_cols = ["Player","GP",
                                "OVRL","OFF","DEF","PLY","REB_R",
                                "PTS","AST","REB","OREB","DREB",
                                "FG%","3P%","FT%","TS%","eFG%",
                                "STL","BLK","TOV","SC","ShotRat","+/-"]
                _show_detail = [c for c in _detail_cols if c in _merged5.columns]
                st.dataframe(
                    _merged5[_show_detail].sort_values(
                        "OVRL" if "OVRL" in _merged5.columns else "PTS",
                        ascending=False).reset_index(drop=True),
                    use_container_width=True, hide_index=True)

                # ── Shot Share & Usage Intelligence ──────────────────────────
                st.markdown("<div class='section-hdr'>Shot Share & Usage (Context-Adjusted)</div>",
                            unsafe_allow_html=True)
                st.caption(
                    "Shot allocation redistributed by OFF rating × raw FGA; "
                    "assists by PLY × AST; rebounds by REB_R × REB. "
                    "Shooting efficiencies (FG%, 3P%, FT%) are preserved per player.")

                # Build the adjustment frame from rankings + optional ratings
                _adj5 = _rnk5.copy() if _has_rankings and not _rnk5.empty else pd.DataFrame()
                if not _adj5.empty and _has_ratings and not _rat5.empty:
                    _r5_cols = [c for c in
                        ["Player","OFF","DEF","PLY","REB_R","OVRL","USG"]
                        if c in _rat5.columns]
                    _adj5 = _adj5.merge(_rat5[_r5_cols], on="Player", how="left")

                if not _adj5.empty:
                    _total_fga = float(_adj5["FGA"].sum()) if "FGA" in _adj5.columns else 0.0
                    _total_ast = float(_adj5["AST"].sum()) if "AST" in _adj5.columns else 0.0
                    _total_reb = float(_adj5["REB"].sum()) if "REB" in _adj5.columns else 0.0

                    # ── Shot rebalancing: OFF rating × FGA drives share ────────
                    if _total_fga > 0 and "OFF" in _adj5.columns and "FGA" in _adj5.columns:
                        _adj5["_shot_wt"] = _adj5["OFF"].fillna(50) * _adj5["FGA"].fillna(0)
                        _sw = float(_adj5["_shot_wt"].sum())
                        _adj5["adj_FGA"] = (
                            _total_fga * _adj5["_shot_wt"] / _sw if _sw else _adj5["FGA"]
                        ).round(1)
                        _adj5["Sh%"] = (_adj5["adj_FGA"] / _total_fga * 100).round(1)
                    else:
                        _adj5["adj_FGA"] = _adj5.get("FGA", pd.Series([0.0]*5))
                        _adj5["Sh%"] = 20.0

                    # 3PA rate preserved; FT rate preserved
                    if "3PAr" in _adj5.columns:
                        _adj5["adj_3PA"] = (_adj5["adj_FGA"] * _adj5["3PAr"] / 100).round(1)
                    elif "3PA" in _adj5.columns and "FGA" in _adj5.columns:
                        _adj5["adj_3PA"] = (
                            _adj5["adj_FGA"] * (_adj5["3PA"] / _adj5["FGA"].replace(0, 1))
                        ).round(1)
                    else:
                        _adj5["adj_3PA"] = 0.0

                    _adj5["adj_FGM"]  = (_adj5["adj_FGA"] * _adj5["FG%"].fillna(0) / 100).round(1)
                    _adj5["adj_3PM"]  = (_adj5["adj_3PA"] * _adj5["3P%"].fillna(0) / 100).round(1)
                    if "FTA" in _adj5.columns and "FGA" in _adj5.columns:
                        _ftr5 = _adj5["FTA"] / _adj5["FGA"].replace(0, 1)
                    else:
                        _ftr5 = pd.Series([0.0]*len(_adj5), index=_adj5.index)
                    _adj5["adj_FTA"]  = (_adj5["adj_FGA"] * _ftr5).round(1)
                    _adj5["adj_FTM"]  = (_adj5["adj_FTA"] * _adj5["FT%"].fillna(0) / 100).round(1)
                    _adj5["adj_PTS"]  = (
                        2*(_adj5["adj_FGM"] - _adj5["adj_3PM"])
                        + 3*_adj5["adj_3PM"]
                        + _adj5["adj_FTM"]
                    ).round(1)

                    # ── Assist rebalancing: PLY × AST ─────────────────────────
                    if _total_ast > 0 and "PLY" in _adj5.columns and "AST" in _adj5.columns:
                        _adj5["_ast_wt"] = _adj5["PLY"].fillna(50) * _adj5["AST"].fillna(0)
                        _aw = float(_adj5["_ast_wt"].sum())
                        _adj5["adj_AST"] = (
                            _total_ast * _adj5["_ast_wt"] / _aw if _aw else _adj5["AST"]
                        ).round(1)
                    else:
                        _adj5["adj_AST"] = _adj5.get("AST", pd.Series([0.0]*5))

                    # ── Rebound rebalancing: REB_R × REB ──────────────────────
                    if _total_reb > 0 and "REB_R" in _adj5.columns and "REB" in _adj5.columns:
                        _adj5["_reb_wt"] = _adj5["REB_R"].fillna(50) * _adj5["REB"].fillna(0)
                        _rw = float(_adj5["_reb_wt"].sum())
                        _adj5["adj_REB"] = (
                            _total_reb * _adj5["_reb_wt"] / _rw if _rw else _adj5["REB"]
                        ).round(1)
                        _oreb_r5 = (
                            _adj5["OREB"] / _adj5["REB"].replace(0, 1)
                            if "OREB" in _adj5.columns else 0.33
                        )
                        _adj5["adj_OREB"] = (_adj5["adj_REB"] * _oreb_r5).round(1)
                        _adj5["adj_DREB"] = (_adj5["adj_REB"] - _adj5["adj_OREB"]).round(1)
                    else:
                        _adj5["adj_REB"]  = _adj5.get("REB",  pd.Series([0.0]*5))
                        _adj5["adj_OREB"] = _adj5.get("OREB", pd.Series([0.0]*5))
                        _adj5["adj_DREB"] = _adj5.get("DREB", pd.Series([0.0]*5))

                    # Display shot-share table
                    _usage_cols = {
                        "Player": "Player", "Sh%": "Shot Share %",
                        "adj_FGA": "Adj FGA", "adj_PTS": "Adj PTS",
                        "adj_AST": "Adj AST", "adj_REB": "Adj REB",
                        "adj_OREB": "Adj OREB",
                    }
                    _usage_disp = _adj5[[c for c in _usage_cols if c in _adj5.columns]].rename(
                        columns=_usage_cols).reset_index(drop=True)
                    st.dataframe(_usage_disp, use_container_width=True, hide_index=True)

                    # ── Lineup-level efficiency ────────────────────────────────
                    _lu_fga  = float(_adj5["adj_FGA"].sum())
                    _lu_fgm  = float(_adj5["adj_FGM"].sum())
                    _lu_3pa  = float(_adj5["adj_3PA"].sum())
                    _lu_3pm  = float(_adj5["adj_3PM"].sum())
                    _lu_fta  = float(_adj5["adj_FTA"].sum())
                    _lu_ftm  = float(_adj5["adj_FTM"].sum())
                    _lu_pts  = float(_adj5["adj_PTS"].sum())
                    _lu_ast  = float(_adj5["adj_AST"].sum())
                    _lu_reb  = float(_adj5["adj_REB"].sum())
                    _lu_oreb = float(_adj5["adj_OREB"].sum())
                    _lu_dreb = float(_adj5["adj_DREB"].sum())
                    _lu_stl  = _col_sum(_rnk5, "STL")
                    _lu_blk  = _col_sum(_rnk5, "BLK")
                    _lu_tov  = _col_sum(_rnk5, "TOV")
                    _lu_sc   = _col_sum(_rnk5, "SC")
                    _lu_pm   = _col_sum(_rnk5, "+/-")

                    _lu_efg  = (_lu_fgm + 0.5*_lu_3pm) / _lu_fga * 100 if _lu_fga else 0.0
                    _lu_ts_d = 2.0 * (_lu_fga + 0.44 * _lu_fta)
                    _lu_ts   = _lu_pts / _lu_ts_d * 100 if _lu_ts_d else 0.0
                    _lu_fgp  = _lu_fgm / _lu_fga * 100 if _lu_fga else 0.0
                    _lu_3pp  = _lu_3pm / _lu_3pa * 100 if _lu_3pa else 0.0
                    _lu_ftp  = _lu_ftm / _lu_fta * 100 if _lu_fta else 0.0
                    _lu_astov = _lu_ast / _lu_tov if _lu_tov else _lu_ast
                    _lu_srat  = _col_mean(_rnk5, "ShotRat")

                    # Lineup ORtg (pts per 100 possessions, player-side)
                    _lu_poss_est = max(0.1, _lu_fga - _lu_oreb + _lu_tov + 0.44 * _lu_fta)
                    _lu_ortg = _lu_pts / _lu_poss_est * 100

                    # Lineup DRtg — team base DRtg adjusted by avg DEF rating
                    _team_drtg_base = adv.get("drtg", 100.0) if adv else 100.0
                    _avg_def_rat = _col_mean(_rat5, "DEF") if _has_ratings else 50.0
                    _def_mod = (_avg_def_rat - 50.0) / 50.0 * 0.08  # ±8% swing
                    _lu_drtg = _team_drtg_base * (1.0 - _def_mod)
                    _lu_net  = _lu_ortg - _lu_drtg

                    # Team pace
                    _team_pace = adv.get("pace", 70.0) if adv else 70.0

                else:
                    # Fallback: raw sums from rankings when no adj frame
                    _lu_fga  = _col_sum(_rnk5, "FGA")
                    _lu_fgm  = _col_sum(_rnk5, "FGM")
                    _lu_3pa  = _col_sum(_rnk5, "3PA")
                    _lu_3pm  = _col_sum(_rnk5, "3PM")
                    _lu_fta  = _col_sum(_rnk5, "FTA")
                    _lu_ftm  = _col_sum(_rnk5, "FTM")
                    _lu_pts  = _col_sum(_rnk5, "PTS")
                    _lu_ast  = _col_sum(_rnk5, "AST")
                    _lu_reb  = _col_sum(_rnk5, "REB")
                    _lu_oreb = _col_sum(_rnk5, "OREB")
                    _lu_dreb = _col_sum(_rnk5, "DREB")
                    _lu_stl  = _col_sum(_rnk5, "STL")
                    _lu_blk  = _col_sum(_rnk5, "BLK")
                    _lu_tov  = _col_sum(_rnk5, "TOV")
                    _lu_sc   = _col_sum(_rnk5, "SC")
                    _lu_pm   = _col_sum(_rnk5, "+/-")
                    _lu_efg  = (_lu_fgm + 0.5*_lu_3pm) / _lu_fga * 100 if _lu_fga else 0.0
                    _lu_ts_d = 2.0 * (_lu_fga + 0.44 * _lu_fta)
                    _lu_ts   = _lu_pts / _lu_ts_d * 100 if _lu_ts_d else 0.0
                    _lu_fgp  = _lu_fgm / _lu_fga * 100 if _lu_fga else 0.0
                    _lu_3pp  = _lu_3pm / _lu_3pa * 100 if _lu_3pa else 0.0
                    _lu_ftp  = _lu_ftm / _lu_fta * 100 if _lu_fta else 0.0
                    _lu_astov = _lu_ast / _lu_tov if _lu_tov else _lu_ast
                    _lu_srat  = _col_mean(_rnk5, "ShotRat")
                    _lu_poss_est = max(0.1, _lu_fga - _lu_oreb + _lu_tov + 0.44 * _lu_fta)
                    _lu_ortg = _lu_pts / _lu_poss_est * 100
                    _lu_drtg = adv.get("drtg", 100.0) if adv else 100.0
                    _lu_net  = _lu_ortg - _lu_drtg
                    _team_pace = adv.get("pace", 70.0) if adv else 70.0

                # ── Projected Lineup Stats ────────────────────────────────────
                st.markdown("<div class='section-hdr'>Projected Lineup Stats</div>",
                            unsafe_allow_html=True)

                # Row 1 — Scoring efficiency
                _pr1 = st.columns(6)
                for _prc, (lbl, val, sub) in zip(_pr1, [
                    ("Adj PPG",   f"{_lu_pts:.1f}",   "context-adj sum"),
                    ("Proj FG%",  f"{_lu_fgp:.1f}%",  "weighted avg"),
                    ("Proj 3P%",  f"{_lu_3pp:.1f}%",  "weighted avg"),
                    ("Proj FT%",  f"{_lu_ftp:.1f}%",  "weighted avg"),
                    ("Proj eFG%", f"{_lu_efg:.1f}%",  "weighted avg"),
                    ("Proj TS%",  f"{_lu_ts:.1f}%",   "weighted avg"),
                ]):
                    _prc.markdown(
                        f"<div class='adv-tile'>"
                        f"<div class='adv-label'>{lbl}</div>"
                        f"<div class='adv-value'>{val}</div>"
                        f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                        f"</div>", unsafe_allow_html=True)

                st.write("")
                # Row 2 — Lineup efficiency & pace
                _net_clr = "#2ecc71" if _lu_net >= 0 else "#e74c3c"
                _pr2 = st.columns(6)
                for _prc, (lbl, val, sub, clr) in zip(_pr2, [
                    ("Lineup ORtg",  f"{_lu_ortg:.1f}",     "pts/100 poss",    "#f0a500"),
                    ("Lineup DRtg",  f"{_lu_drtg:.1f}",     "est. def (adj)",  "#3498db"),
                    ("Net Rating",   f"{_lu_net:+.1f}",     "off − def",       _net_clr),
                    ("Pace",         f"{_team_pace:.1f}",   "poss / game",     "#8b949e"),
                    ("Adj AST",      f"{_lu_ast:.1f}",      "context-adj",     "#9b59b6"),
                    ("AST/TOV",      f"{_lu_astov:.2f}",    "lineup ratio",    "#2ecc71"),
                ]):
                    _prc.markdown(
                        f"<div class='adv-tile'>"
                        f"<div class='adv-label'>{lbl}</div>"
                        f"<div class='adv-value' style='color:{clr}'>{val}</div>"
                        f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                        f"</div>", unsafe_allow_html=True)

                st.write("")
                # Row 3 — Rebounding & defense
                _pr3 = st.columns(6)
                for _prc, (lbl, val, sub) in zip(_pr3, [
                    ("Adj REB",   f"{_lu_reb:.1f}",            "context-adj"),
                    ("Adj OREB",  f"{_lu_oreb:.1f}",           "context-adj"),
                    ("Adj DREB",  f"{_lu_dreb:.1f}",           "context-adj"),
                    ("Comb STL",  f"{_lu_stl:.1f}",            "steals / game"),
                    ("Comb BLK",  f"{_lu_blk:.1f}",            "blocks / game"),
                    ("Stocks",    f"{_lu_stl+_lu_blk:.1f}",    "STL+BLK"),
                ]):
                    _prc.markdown(
                        f"<div class='adv-tile'>"
                        f"<div class='adv-label'>{lbl}</div>"
                        f"<div class='adv-value'>{val}</div>"
                        f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                        f"</div>", unsafe_allow_html=True)

                # ── Lineup Charts ─────────────────────────────────────────────
                st.markdown("<div class='section-hdr'>Lineup Charts</div>",
                            unsafe_allow_html=True)
                _ch1, _ch2 = st.columns(2)

                # Chart 1 — Rating bars
                if _has_ratings and not _rat5.empty:
                    with _ch1:
                        _fig_lu_rat = go.Figure()
                        _rat_bar_cfg2 = [("OVRL","Overall","#f0a500"),
                                         ("OFF","Offense","#2ecc71"),
                                         ("DEF","Defense","#3498db"),
                                         ("PLY","Playmaking","#9b59b6"),
                                         ("REB_R","Rebounding","#e67e22")]
                        _rat5_sorted = _rat5.sort_values("OVRL", ascending=False)
                        for _rc, _rl, _rclr2 in _rat_bar_cfg2:
                            if _rc not in _rat5_sorted.columns:
                                continue
                            _fig_lu_rat.add_trace(go.Bar(
                                name=_rl,
                                x=_rat5_sorted["Player"],
                                y=_rat5_sorted[_rc],
                                marker_color=_rclr2, width=0.15))
                        _fig_lu_rat.update_layout(
                            **PLOT_LAYOUT,
                            title="Player Ratings (0–100)",
                            barmode="group",
                            yaxis=dict(title="Rating", range=[0, 110]),
                            xaxis=dict(tickangle=-20),
                            height=320,
                            legend=dict(orientation="h", y=-0.2))
                        st.plotly_chart(_fig_lu_rat, use_container_width=True)

                # Chart 2 — Raw vs Adjusted scoring per player
                if not _adj5.empty and "adj_PTS" in _adj5.columns and "PTS" in _adj5.columns:
                    with _ch2:
                        _fig_adj_pts = go.Figure()
                        _adj5_sorted = _adj5.sort_values("adj_PTS", ascending=False)
                        _fig_adj_pts.add_trace(go.Bar(
                            name="Raw PPG",
                            x=_adj5_sorted["Player"],
                            y=_adj5_sorted["PTS"],
                            marker_color="#555d68", opacity=0.7,
                            text=[f"{v:.1f}" for v in _adj5_sorted["PTS"]],
                            textposition="outside"))
                        _fig_adj_pts.add_trace(go.Bar(
                            name="Adj PPG",
                            x=_adj5_sorted["Player"],
                            y=_adj5_sorted["adj_PTS"],
                            marker_color="#f0a500",
                            text=[f"{v:.1f}" for v in _adj5_sorted["adj_PTS"]],
                            textposition="outside"))
                        _fig_adj_pts.update_layout(
                            **PLOT_LAYOUT,
                            title="Raw vs Adjusted PPG",
                            barmode="group",
                            yaxis_title="PTS/G", height=320,
                            xaxis=dict(tickangle=-20),
                            legend=dict(orientation="h", y=-0.2))
                        st.plotly_chart(_fig_adj_pts, use_container_width=True)
                elif _has_rankings and not _rnk5.empty:
                    with _ch2:
                        _fig_lu_pts = go.Figure()
                        _rnk5_sorted = _rnk5.sort_values("PTS", ascending=False)
                        _pts_colors = ["#f0a500","#2ecc71","#3498db","#9b59b6","#e67e22"]
                        _fig_lu_pts.add_trace(go.Bar(
                            name="PTS",
                            x=_rnk5_sorted["Player"],
                            y=_rnk5_sorted["PTS"] if "PTS" in _rnk5_sorted.columns else [],
                            marker_color=_pts_colors[:len(_rnk5_sorted)],
                            text=[f"{v:.1f}" for v in _rnk5_sorted["PTS"]] if "PTS" in _rnk5_sorted.columns else [],
                            textposition="outside"))
                        _fig_lu_pts.update_layout(
                            **PLOT_LAYOUT,
                            title="Scoring Contribution (PPG)",
                            yaxis_title="PTS/G", height=320,
                            xaxis=dict(tickangle=-20))
                        st.plotly_chart(_fig_lu_pts, use_container_width=True)

                # Chart 3 — Shot share pie + shooting %
                _ch3a, _ch3b = st.columns(2)
                if not _adj5.empty and "Sh%" in _adj5.columns:
                    with _ch3a:
                        _pie_colors = ["#f0a500","#2ecc71","#3498db","#9b59b6","#e67e22"]
                        _fig_pie = go.Figure(go.Pie(
                            labels=_adj5["Player"].tolist(),
                            values=_adj5["Sh%"].tolist(),
                            marker_colors=_pie_colors[:len(_adj5)],
                            textinfo="label+percent",
                            hole=0.35))
                        _fig_pie.update_layout(
                            **PLOT_LAYOUT,
                            title="Adjusted Shot Share",
                            height=300,
                            showlegend=False)
                        st.plotly_chart(_fig_pie, use_container_width=True)
                if _has_rankings and not _rnk5.empty:
                    with _ch3b:
                        _fig_lu_sh = go.Figure()
                        _sh_cols_cfg = [("FG%","FG%","#f0a500"),("3P%","3P%","#3498db"),
                                        ("FT%","FT%","#2ecc71"),("TS%","TS%","#9b59b6")]
                        _rnk5_sorted2 = _rnk5.sort_values("PTS", ascending=False)
                        for _sc_col, _sc_lbl, _sc_clr in _sh_cols_cfg:
                            if _sc_col not in _rnk5_sorted2.columns:
                                continue
                            _fig_lu_sh.add_trace(go.Bar(
                                name=_sc_lbl, x=_rnk5_sorted2["Player"],
                                y=_rnk5_sorted2[_sc_col],
                                marker_color=_sc_clr, width=0.2))
                        _fig_lu_sh.update_layout(
                            **PLOT_LAYOUT, title="Shooting % Comparison",
                            barmode="group", yaxis_title="%", height=300,
                            xaxis=dict(tickangle=-20),
                            legend=dict(orientation="h", y=-0.2))
                        st.plotly_chart(_fig_lu_sh, use_container_width=True)

                # Chart 4 — Rebounding & defense
                if _has_rankings and not _rnk5.empty:
                    _fig_lu_def = go.Figure()
                    _rnk5_sorted3 = (_rnk5.sort_values("REB", ascending=False)
                                     if "REB" in _rnk5.columns else _rnk5)
                    for _dc_col, _dc_lbl, _dc_clr in [
                        ("REB","REB","#3498db"),("STL","STL","#2ecc71"),("BLK","BLK","#9b59b6"),
                    ]:
                        if _dc_col not in _rnk5_sorted3.columns:
                            continue
                        _fig_lu_def.add_trace(go.Bar(
                            name=_dc_lbl, x=_rnk5_sorted3["Player"],
                            y=_rnk5_sorted3[_dc_col],
                            marker_color=_dc_clr, width=0.2))
                    _fig_lu_def.update_layout(
                        **PLOT_LAYOUT, title="Rebounding & Defense",
                        barmode="group", yaxis_title="Per Game", height=300,
                        xaxis=dict(tickangle=-20),
                        legend=dict(orientation="h", y=-0.2))
                    st.plotly_chart(_fig_lu_def, use_container_width=True)

                # ── 30-Game Season Simulation ─────────────────────────────────
                st.divider()
                st.markdown("<div class='section-hdr'>30-Game Season Simulation</div>",
                            unsafe_allow_html=True)
                st.caption(
                    "Games pulled from actual schedule first. If fewer than 30, filled with "
                    "same-class teams then adjacent classes. Where opponent has tracked games, "
                    "their ORtg/DRtg is used (Tracked); otherwise PPG/OPP-PPG from box scores.")

                # ── league baseline ───────────────────────────────────────────
                _lg_drtg_sim = compute_league_drtg()
                _lg_pace_sim = _team_pace  # proxy for league avg pace

                # ── class proximity helper ────────────────────────────────────
                def _cls_num(cls: str) -> int:
                    """Numeric rank for a class string — higher = stronger."""
                    c = (cls or "").strip().upper()
                    # Leading digit: "6A"→6, "5A"→5, etc.
                    _d = ""
                    for _ch in c:
                        if _ch.isdigit():
                            _d += _ch
                        else:
                            break
                    if _d:
                        return int(_d)
                    # Count leading/all A's: AAAA→4, AAA→3, AA→2, A→1
                    _ac = sum(1 for _ch in c if _ch == "A")
                    if _ac:
                        return _ac
                    return 0

                _my_cls_num = _cls_num(team_info.get("class", "") or "")

                # ── standings lookup {team_id: standings_row} ─────────────────
                _std_lookup = {s["id"]: s for s in (_standings or [])}

                # ── 1. Build opponent list from actual schedule ────────────────
                _sim_opps: list = []
                _seen_sim: set  = {team_id}

                for _sg in sorted(all_gs, key=lambda x: x.get("date", "")):
                    _o_id = (_sg["team2_id"] if _sg["team1_id"] == team_id
                             else _sg["team1_id"])
                    _o_nm = (_sg["t2_name"] if _sg["team1_id"] == team_id
                             else _sg["t1_name"])
                    if _o_id in _seen_sim:
                        continue
                    _seen_sim.add(_o_id)

                    # Try tracked stats first, fall back to box-score standings
                    _o_adv = compute_team_tracked(_o_id)
                    _o_std = _std_lookup.get(_o_id, {})
                    if _o_adv and _o_adv.get("gp", 0) > 0:
                        _o_ortg  = float(_o_adv["ortg"])
                        _o_drtg  = float(_o_adv["drtg"])
                        _o_pace  = float(_o_adv.get("pace", _lg_pace_sim))
                        _o_meth  = "Tracked"
                    elif _o_std:
                        _ppg_s   = float(_o_std.get("ppg", 0) or 0)
                        _opg_s   = float(_o_std.get("opp_ppg", 0) or 0)
                        _o_ortg  = _ppg_s / _lg_pace_sim * 100 if _lg_pace_sim else 100.0
                        _o_drtg  = _opg_s / _lg_pace_sim * 100 if _lg_pace_sim else 100.0
                        _o_pace  = _lg_pace_sim
                        _o_meth  = "Box Score"
                    else:
                        continue  # no data — skip

                    _sim_opps.append({
                        "id":    _o_id,
                        "name":  _o_nm,
                        "class": (team_meta.get(_o_id, {}) or {}).get("class", "")
                                 or _o_std.get("class", ""),
                        "ortg":  _o_ortg,
                        "drtg":  _o_drtg,
                        "pace":  _o_pace,
                        "meth":  _o_meth,
                        "src":   "Schedule",
                    })

                # ── 2. Fill to 30 with same / adjacent class teams ────────────
                if len(_sim_opps) < 30:
                    _fill_pool = sorted(
                        [t for t in all_teams
                         if t["id"] not in _seen_sim
                         and _std_lookup.get(t["id"])],
                        key=lambda t: (
                            abs(_cls_num(t.get("class", "") or "") - _my_cls_num),
                            t["name"],
                        ),
                    )
                    for _ft in _fill_pool:
                        if len(_sim_opps) >= 30:
                            break
                        _o_adv2 = compute_team_tracked(_ft["id"])
                        _o_std2 = _std_lookup[_ft["id"]]
                        if _o_adv2 and _o_adv2.get("gp", 0) > 0:
                            _fo  = float(_o_adv2["ortg"])
                            _fd  = float(_o_adv2["drtg"])
                            _fp  = float(_o_adv2.get("pace", _lg_pace_sim))
                            _fm  = "Tracked"
                        else:
                            _ppg_f = float(_o_std2.get("ppg", 0) or 0)
                            _opg_f = float(_o_std2.get("opp_ppg", 0) or 0)
                            _fo    = _ppg_f / _lg_pace_sim * 100 if _lg_pace_sim else 100.0
                            _fd    = _opg_f / _lg_pace_sim * 100 if _lg_pace_sim else 100.0
                            _fp    = _lg_pace_sim
                            _fm    = "Box Score"
                        _seen_sim.add(_ft["id"])
                        _sim_opps.append({
                            "id":    _ft["id"],
                            "name":  _ft["name"],
                            "class": _ft.get("class", ""),
                            "ortg":  _fo,
                            "drtg":  _fd,
                            "pace":  _fp,
                            "meth":  _fm,
                            "src":   f"Fill ({_ft.get('class','')})",
                        })

                # ── 3. Per-game simulation ────────────────────────────────────
                _sim_rows   = []
                _exp_wins   = 0.0
                _cum_w_list = []
                _cum_l_list = []
                _running_w  = 0.0

                for _gn, _opp in enumerate(_sim_opps[:30], 1):
                    # Projected score per matchup using the matchup-simulator formula:
                    # our_score  = (our ORtg / 100) × avg_pace × (opp DRtg / lg DRtg)
                    # opp_score  = (opp ORtg / 100) × avg_pace × (our DRtg / lg DRtg)
                    _avg_pace_g = (_team_pace + _opp["pace"]) / 2.0
                    _lg_d       = max(_lg_drtg_sim, 1.0)
                    _my_sc_g = (_lu_ortg / 100.0) * _avg_pace_g * (_opp["drtg"] / _lg_d)
                    _op_sc_g = (_opp["ortg"] / 100.0) * _avg_pace_g * (_lu_drtg  / _lg_d)
                    _margin_g = _my_sc_g - _op_sc_g

                    _gm_wp = 1.0 / (1.0 + np.exp(-_margin_g / 8.0))
                    _exp_wins   += _gm_wp
                    _running_w  += _gm_wp
                    _result_g   = "W" if _gm_wp >= 0.5 else "L"

                    _cum_w_list.append(round(_running_w))
                    _cum_l_list.append(_gn - round(_running_w))

                    _sim_rows.append({
                        "G#":       _gn,
                        "Opponent": _opp["name"],
                        "Class":    _opp["class"],
                        "Source":   _opp["src"],
                        "Method":   _opp["meth"],
                        "Our Proj": round(_my_sc_g, 1),
                        "Opp Proj": round(_op_sc_g, 1),
                        "Margin":   f"{_margin_g:+.1f}",
                        "Win %":    f"{_gm_wp*100:.0f}%",
                        "Result":   _result_g,
                    })

                _exp_w   = round(_exp_wins)
                _exp_l   = 30 - _exp_w
                _avg_wp  = _exp_wins / max(len(_sim_rows), 1)
                _proj_pts_pg      = (_lu_ortg / 100.0) * _team_pace
                _proj_pts_alwd_pg = (_lu_drtg  / 100.0) * _team_pace
                _proj_margin_pg   = _proj_pts_pg - _proj_pts_alwd_pg

                # ── 4. Header KPI tiles ───────────────────────────────────────
                _wl_clr  = "#2ecc71" if _exp_w >= 15 else "#e74c3c"
                _mg_clr  = "#2ecc71" if _proj_margin_pg >= 0 else "#e74c3c"
                _sched_ct = sum(1 for r in _sim_rows if r["Source"] == "Schedule")
                _fill_ct  = len(_sim_rows) - _sched_ct

                _wl_cols = st.columns(5)
                for _wc, (lbl, val, sub, clr) in zip(_wl_cols, [
                    ("Proj Record",     f"{_exp_w}–{_exp_l}",
                     f"{_avg_wp*100:.0f}% avg win prob", _wl_clr),
                    ("Pts Scored / G",  f"{_proj_pts_pg:.1f}",
                     f"{_proj_pts_pg*30:.0f} over 30 G", "#f0a500"),
                    ("Pts Allowed / G", f"{_proj_pts_alwd_pg:.1f}",
                     f"{_proj_pts_alwd_pg*30:.0f} over 30 G", "#e74c3c"),
                    ("Point Margin",    f"{_proj_margin_pg:+.1f}",
                     "per game avg", _mg_clr),
                    ("Schedule",        f"{_sched_ct} + {_fill_ct}",
                     "real games + fill", "#8b949e"),
                ]):
                    _wc.markdown(
                        f"<div class='kpi-tile'>"
                        f"<div class='kpi-label'>{lbl}</div>"
                        f"<div class='kpi-value' style='color:{clr}'>{val}</div>"
                        f"<div class='kpi-sub'>{sub}</div>"
                        f"</div>", unsafe_allow_html=True)

                # Win-probability bar
                st.write("")
                _wbar_html = (
                    f"<div style='background:#2d333b;border-radius:6px;"
                    f"height:20px;overflow:hidden'>"
                    f"<div style='background:linear-gradient(90deg,#2ecc71,#27ae60);"
                    f"width:{_avg_wp*100:.0f}%;height:100%;float:left;"
                    f"border-radius:6px 0 0 6px'></div>"
                    f"<div style='background:linear-gradient(90deg,#e74c3c,#c0392b);"
                    f"width:{(1-_avg_wp)*100:.0f}%;height:100%;float:left;"
                    f"border-radius:0 6px 6px 0'></div></div>"
                    f"<div style='display:flex;justify-content:space-between;"
                    f"font-size:11px;color:#8b949e;margin-top:4px'>"
                    f"<span style='color:#2ecc71;font-weight:700'>"
                    f"W {_exp_w} ({_avg_wp*100:.0f}%)</span>"
                    f"<span style='color:#e74c3c;font-weight:700'>"
                    f"L {_exp_l} ({(1-_avg_wp)*100:.0f}%)</span></div>"
                )
                st.markdown(_wbar_html, unsafe_allow_html=True)
                st.write("")

                # ── 5. Team season totals ─────────────────────────────────────
                st.markdown("**Projected 30-Game Team Totals**")
                _ssn_team_cols = st.columns(6)
                for _sc2, (lbl, val) in zip(_ssn_team_cols, [
                    ("PTS", f"{_proj_pts_pg*30:.0f}"),
                    ("AST", f"{_lu_ast*30:.0f}"),
                    ("REB", f"{_lu_reb*30:.0f}"),
                    ("STL", f"{_lu_stl*30:.0f}"),
                    ("BLK", f"{_lu_blk*30:.0f}"),
                    ("TOV", f"{_lu_tov*30:.0f}"),
                ]):
                    _sc2.markdown(
                        f"<div class='adv-tile'>"
                        f"<div class='adv-label'>{lbl} (30 G)</div>"
                        f"<div class='adv-value'>{val}</div>"
                        f"</div>", unsafe_allow_html=True)

                # ── 6. Per-player season totals table ─────────────────────────
                st.write("")
                st.markdown("**Projected Per-Player Season Totals (30 Games)**")
                _src_df  = _adj5 if not _adj5.empty else _rnk5
                _ssn_rows = []
                for _, _plr_row in _src_df.iterrows():
                    _s_pts  = float(_plr_row.get("adj_PTS",  _plr_row.get("PTS",  0)))
                    _s_ast  = float(_plr_row.get("adj_AST",  _plr_row.get("AST",  0)))
                    _s_reb  = float(_plr_row.get("adj_REB",  _plr_row.get("REB",  0)))
                    _s_oreb = float(_plr_row.get("adj_OREB", _plr_row.get("OREB", 0)))
                    _s_dreb = float(_plr_row.get("adj_DREB", _plr_row.get("DREB", 0)))
                    _s_stl  = float(_plr_row.get("STL", 0))
                    _s_blk  = float(_plr_row.get("BLK", 0))
                    _s_tov  = float(_plr_row.get("TOV", 0))
                    _ssn_rows.append({
                        "Player":   _plr_row.get("Player", ""),
                        "Adj PPG":  round(_s_pts,  1),
                        "Adj APG":  round(_s_ast,  1),
                        "Adj RPG":  round(_s_reb,  1),
                        "Adj ORPG": round(_s_oreb, 1),
                        "Adj DRPG": round(_s_dreb, 1),
                        "SPG":      round(_s_stl,  1),
                        "BPG":      round(_s_blk,  1),
                        "TOPG":     round(_s_tov,  1),
                        "FG%":      round(float(_plr_row.get("FG%", 0)), 1),
                        "3P%":      round(float(_plr_row.get("3P%", 0)), 1),
                        "FT%":      round(float(_plr_row.get("FT%", 0)), 1),
                        "Seas PTS": round(_s_pts  * 30),
                        "Seas AST": round(_s_ast  * 30),
                        "Seas REB": round(_s_reb  * 30),
                        "Seas STL": round(_s_stl  * 30),
                        "Seas BLK": round(_s_blk  * 30),
                    })
                if _ssn_rows:
                    _ssn_df = (pd.DataFrame(_ssn_rows)
                               .sort_values("Adj PPG", ascending=False)
                               .reset_index(drop=True))
                    st.dataframe(_ssn_df, use_container_width=True, hide_index=True)

                # ── 7. Cumulative W-L chart + game-by-game schedule ───────────
                st.write("")
                if _sim_rows:
                    _ch_sim1, _ch_sim2 = st.columns([1, 1])

                    with _ch_sim1:
                        _gs_ax   = [r["G#"] for r in _sim_rows]
                        _fig_ssn = go.Figure()
                        _fig_ssn.add_trace(go.Scatter(
                            x=_gs_ax, y=_cum_w_list,
                            mode="lines+markers", name="Proj Wins",
                            line=dict(color="#2ecc71", width=2),
                            marker=dict(size=5)))
                        _fig_ssn.add_trace(go.Scatter(
                            x=_gs_ax, y=_cum_l_list,
                            mode="lines+markers", name="Proj Losses",
                            line=dict(color="#e74c3c", width=2),
                            marker=dict(size=5)))
                        _fig_ssn.add_hline(
                            y=15, line_dash="dot", line_color="#888",
                            annotation_text=".500")
                        _fig_ssn.update_layout(
                            **PLOT_LAYOUT,
                            title="Cumulative Projected Record",
                            xaxis_title="Game #",
                            yaxis_title="Cumulative W / L",
                            height=340,
                            legend=dict(orientation="h", y=-0.25))
                        st.plotly_chart(_fig_ssn, use_container_width=True)

                    with _ch_sim2:
                        # Margin bar chart: green=W, red=L
                        _mar_vals = [float(r["Margin"]) for r in _sim_rows]
                        _mar_clrs = ["#2ecc71" if v >= 0 else "#e74c3c" for v in _mar_vals]
                        _fig_mar = go.Figure(go.Bar(
                            x=_gs_ax,
                            y=_mar_vals,
                            marker_color=_mar_clrs,
                            text=[r["Opponent"].split()[-1] for r in _sim_rows],
                            textposition="outside",
                            textfont=dict(size=8)))
                        _fig_mar.add_hline(y=0, line_color="#555d68", line_width=1)
                        _fig_mar.update_layout(
                            **PLOT_LAYOUT,
                            title="Projected Score Margin per Game",
                            xaxis_title="Game #",
                            yaxis_title="Margin",
                            height=340)
                        st.plotly_chart(_fig_mar, use_container_width=True)

                    # ── Game-by-game schedule table ───────────────────────────
                    st.markdown("**Game-by-Game Projection**")
                    _sched_display = pd.DataFrame(_sim_rows)
                    st.dataframe(
                        _sched_display, use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Result": st.column_config.TextColumn("Result"),
                            "Win %":  st.column_config.TextColumn("Win %"),
                            "Margin": st.column_config.TextColumn("Margin"),
                        })


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — MATCHUP SIMULATOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_mu:
    other_teams = [t for t in all_teams if t["id"] != team_id]

    if not other_teams:
        st.info("Need at least two teams.")
    else:
        opp_map_mu  = {t["name"]: t["id"] for t in other_teams}
        opp_name_mu = st.selectbox("Select Opponent", list(opp_map_mu.keys()), key="mu_opp_sel")
        opp_id_mu   = opp_map_mu[opp_name_mu]

        mu = compute_matchup(team_id, opp_id_mu)

        adv_a2 = mu["adv_a"]
        adv_b2 = mu["adv_b"]
        prob_a = mu["prob_a"]
        prob_b = 1 - prob_a
        proj_a = mu["proj_a"]
        proj_b = mu["proj_b"]

        # ── Summary header ─────────────────────────────────────────────────
        st.divider()
        hm1, hm2, hm3, hm4, hm5, hm6 = st.columns(6)
        hm1.metric(f"{sel_name} Record",   f"{mu['wa']}-{mu['la']}")
        hm2.metric("Proj Score",           f"{proj_a:.1f} pts")
        hm3.metric(f"{sel_name} Win Prob", f"{prob_a*100:.0f}%")
        hm4.metric(f"{opp_name_mu} Win Prob", f"{prob_b*100:.0f}%")
        hm5.metric("Proj Score",           f"{proj_b:.1f} pts")
        hm6.metric(f"{opp_name_mu} Record", f"{mu['wb']}-{mu['lb']}")

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
            f"<span style='color:#e74c3c;font-weight:700'>{opp_name_mu}</span></div>"
        )
        st.markdown(bar_html, unsafe_allow_html=True)
        _n_h2h = mu.get("n_h2h", 0)
        _base  = ("efficiency (ORtg · DRtg · Pace, additive)"
                  if "efficiency" in mu.get("method", "") else "score-based (PPG avg)")
        method_lbl = f"{_base} + {_n_h2h} H2H game{'s' if _n_h2h != 1 else ''} blended" if _n_h2h else _base
        st.caption(f"Projection method: {method_lbl}")

        # ── Component breakdown when H2H blending is active ─────────────────
        if _n_h2h and mu.get("h2h_proj_a") is not None:
            with st.expander("📐 Projection breakdown", expanded=False):
                bc1, bc2, bc3 = st.columns(3)
                bc1.metric("Efficiency-only projection",
                           f"{mu['eff_proj_a']:.1f} – {mu['eff_proj_b']:.1f}",
                           f"Margin: {mu['eff_proj_a']-mu['eff_proj_b']:+.1f}")
                bc2.metric(f"H2H avg ({_n_h2h} game{'s' if _n_h2h!=1 else ''})",
                           f"{mu['h2h_proj_a']:.1f} – {mu['h2h_proj_b']:.1f}",
                           f"Margin: {mu['h2h_proj_a']-mu['h2h_proj_b']:+.1f}")
                bc3.metric("Blended projection",
                           f"{proj_a:.1f} – {proj_b:.1f}",
                           f"Margin: {proj_a-proj_b:+.1f}")

        # ── Visual stat comparison bars ─────────────────────────────────────
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
            show_matchup_bars(_bars_a, _bars_b, sel_name, opp_name_mu)

        # ── Side-by-side stat table ─────────────────────────────────────────
        st.divider()
        st.markdown("#### Side-by-Side Stats")

        _cmp_stats = [
            ("PPG",  mu["ppg_a"],  mu["ppg_b"],  True),
            ("PA/G", mu["papg_a"], mu["papg_b"], False),
        ]
        if adv_a2 and adv_b2:
            _cmp_stats += [
                ("ORtg",     adv_a2["ortg"],       adv_b2["ortg"],       True),
                ("DRtg",     adv_a2["drtg"],       adv_b2["drtg"],       False),
                ("Net Rtg",  adv_a2["net"],        adv_b2["net"],        True),
                ("eFG%",     adv_a2["efg"]*100,    adv_b2["efg"]*100,    True),
                ("Opp eFG%", adv_a2["oefg"]*100,   adv_b2["oefg"]*100,  False),
                ("TS%",      adv_a2["ts"]*100,     adv_b2["ts"]*100,     True),
                ("TOV%",     adv_a2["tov_r"]*100,  adv_b2["tov_r"]*100, False),
                ("OREB%",    adv_a2["oreb_p"]*100, adv_b2["oreb_p"]*100, True),
                ("DREB%",    adv_a2["dreb_p"]*100, adv_b2["dreb_p"]*100, True),
                ("FT Rate",  adv_a2["ft_r"],        adv_b2["ft_r"],       True),
                ("Pace",     adv_a2["pace"],         adv_b2["pace"],       True),
                ("Paint PPG",adv_a2.get("paint_pts_pg",0), adv_b2.get("paint_pts_pg",0), True),
                ("AST/TOV",  adv_a2.get("ast_tov_r",0),  adv_b2.get("ast_tov_r",0),  True),
            ]

        _cmp_rows = []
        for label, va, vb, hib in _cmp_stats:
            try:
                va_f, vb_f = float(va), float(vb)
            except (TypeError, ValueError):
                continue
            better_a = va_f >= vb_f if hib else va_f <= vb_f
            _cmp_rows.append({
                sel_name:    f"{'✅ ' if better_a else ''}{va_f:.1f}",
                "Stat":      label,
                opp_name_mu: f"{'✅ ' if not better_a else ''}{vb_f:.1f}",
            })
        if _cmp_rows:
            st.dataframe(pd.DataFrame(_cmp_rows).set_index("Stat"), use_container_width=True)

        # ── Head-to-head history ────────────────────────────────────────────
        st.divider()
        st.markdown("#### Head-to-Head History")
        if not mu["h2h"]:
            st.info("These two teams have not played each other yet.")
        else:
            h2h_games = mu["h2h"]
            h2h_w_me  = sum(1 for g in h2h_games
                            if (g["team1_id"] == team_id and g["home_score"] > g["away_score"])
                            or (g["team1_id"] != team_id and g["away_score"] > g["home_score"]))
            h2h_w_opp = len(h2h_games) - h2h_w_me
            hh1, hh2 = st.columns(2)
            hh1.metric(f"{sel_name} wins",    h2h_w_me)
            hh2.metric(f"{opp_name_mu} wins", h2h_w_opp)

            for g in h2h_games:
                if g["team1_id"] == team_id:
                    me_sc, opp_sc = g["home_score"], g["away_score"]
                else:
                    me_sc, opp_sc = g["away_score"], g["home_score"]
                i_won = me_sc > opp_sc
                winner_name = sel_name if i_won else opp_name_mu
                w_sc = me_sc  if i_won else opp_sc
                l_sc = opp_sc if i_won else me_sc
                loser_name  = opp_name_mu if i_won else sel_name
                try:
                    dl = datetime.strptime(g["date"], "%Y-%m-%d").strftime("%B %d, %Y")
                except Exception:
                    dl = g["date"] or "—"
                st.markdown(
                    f"<div style='background:#161b22;border:1px solid #30363d;border-radius:10px;"
                    f"padding:12px 16px;margin-bottom:8px'>"
                    f"<span style='color:#8b949e;font-size:11px'>{dl}</span><br>"
                    f"<span style='color:#2ecc71;font-weight:700'>{winner_name}</span> "
                    f"<span style='color:#f0a500;font-weight:800'>{w_sc}</span>  –  "
                    f"<span style='color:#8b949e;font-weight:700'>{loser_name}</span> "
                    f"<span style='color:#555d68;font-weight:800'>{l_sc}</span>"
                    f"</div>", unsafe_allow_html=True)

                _g_tracked = query(
                    "SELECT id, tracked FROM games WHERE team1_id IN (?,?) "
                    "AND team2_id IN (?,?) AND date=? AND tracked=1 LIMIT 1",
                    (team_id, opp_id_mu, team_id, opp_id_mu, g["date"]))
                if _g_tracked:
                    with st.expander("View Box Score"):
                        _bsr1, _bsr2, _gi = compute_game_box_score(_g_tracked[0]["id"])
                        if any(not r.get("_totals") for r in _bsr1 + _bsr2):
                            show_game_box_score(_bsr1, _bsr2, {}, _gi, _cfg)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_ins:
    if not adv:
        st.info("No tracked game data yet — track some games to unlock insights.")
        st.stop()

    _ins_rnk = compute_player_rankings()
    _ins_rat = compute_player_ratings()
    _ins_oo  = compute_on_off(team_id)
    _ins_lg  = compute_league_four_factors()

    _i_rnk = pd.DataFrame()
    _i_rat = pd.DataFrame()
    if not _ins_rnk.empty and "Team" in _ins_rnk.columns:
        _i_rnk = _ins_rnk[_ins_rnk["Team"] == sel_name].copy()
    if not _ins_rat.empty and "Team" in _ins_rat.columns:
        _i_rat = _ins_rat[_ins_rat["Team"] == sel_name].copy()

    # ── SECTION 1: FOUR FACTORS DEEP DIVE ────────────────────────────────────
    st.markdown("<div class='section-hdr'>The Four Factors — Offense & Defense vs League Avg</div>",
                unsafe_allow_html=True)
    st.caption("Dean Oliver's Four Factors that determine offensive and defensive efficiency, "
               "benchmarked against the league average.")

    _i_ff_rows = [
        # (label, our_off, lg_off, off_hib, our_def, lg_def, def_hib, description)
        ("eFG%",
         adv["efg"] * 100,          _ins_lg["efg"] * 100,        True,
         adv["oefg"] * 100,         _ins_lg["oefg"] * 100,       False,
         "Effective FG% weights 3s at 1.5× — best single measure of shot quality."),
        ("TOV Rate",
         adv["tov_r"] * 100,        _ins_lg["tov_r"] * 100,      False,
         adv.get("opp_tov_r",0)*100,_ins_lg.get("opp_tov_r",0)*100, True,
         "Turnovers per scoring attempt. Lower ours / higher forced = better."),
        ("OREB / DREB%",
         adv["oreb_p"] * 100,       _ins_lg["oreb_p"] * 100,     True,
         adv.get("dreb_p",0) * 100, _ins_lg.get("dreb_p",0)*100, True,
         "Off-reb gives second chances; def-reb denies them."),
        ("FT Rate",
         adv["ft_r"] * 100,         _ins_lg["ft_r"] * 100,       True,
         adv.get("opp_ft_r",0)*100, _ins_lg.get("opp_ft_r",0)*100, False,
         "FTA / FGA × 100. Getting to the line (off) vs surrendering it (def)."),
    ]

    _i_ff_cols = st.columns(4)
    for _ifc, (_ifl, _io, _ilo, _ioh, _id, _ild, _idh, _ifd) in zip(_i_ff_cols, _i_ff_rows):
        _od = _io - _ilo
        _dd = _id - _ild
        _oc = "#2ecc71" if ((_od > 0) == _ioh) else "#e74c3c"
        _dc = "#2ecc71" if ((_dd > 0) == _idh) else "#e74c3c"
        _ifc.markdown(
            f"<div class='big4-card'>"
            f"<div class='big4-label'>{_ifl}</div>"
            f"<div style='display:flex;justify-content:space-between;margin-bottom:2px'>"
            f"<span style='font-size:9px;color:#8b949e;text-transform:uppercase'>OFFENSE</span>"
            f"<span style='font-size:9px;color:#8b949e;text-transform:uppercase'>DEFENSE</span></div>"
            f"<div style='display:flex;justify-content:space-between'>"
            f"<span style='font-size:26px;font-weight:900;color:{_oc}'>{_io:.1f}</span>"
            f"<span style='font-size:26px;font-weight:900;color:{_dc}'>{_id:.1f}</span>"
            f"</div>"
            f"<div style='display:flex;justify-content:space-between;margin-top:4px'>"
            f"<span style='font-size:9px;color:#555d68'>lg {_ilo:.1f} ({_od:+.1f})</span>"
            f"<span style='font-size:9px;color:#555d68'>lg {_ild:.1f} ({_dd:+.1f})</span>"
            f"</div>"
            f"<div style='font-size:9px;color:#555d68;margin-top:6px;line-height:1.3'>{_ifd}</div>"
            f"</div>", unsafe_allow_html=True)

    # Comparison bar chart — team vs league avg, 8 metrics
    st.write("")
    _i_bar_labels = [
        "eFG% OFF", "TOV% OFF\n(lower=better)", "OREB%", "FT Rate OFF",
        "eFG% DEF\n(lower=better)", "Forced TOV%", "DREB%", "Opp FT Rate\n(lower=better)",
    ]
    _i_team_vals = [
        adv["efg"]*100, adv["tov_r"]*100, adv["oreb_p"]*100, adv["ft_r"]*100,
        adv["oefg"]*100, adv.get("opp_tov_r",0)*100,
        adv.get("dreb_p",0)*100, adv.get("opp_ft_r",0)*100,
    ]
    _i_lg_vals = [
        _ins_lg["efg"]*100, _ins_lg["tov_r"]*100, _ins_lg["oreb_p"]*100, _ins_lg["ft_r"]*100,
        _ins_lg["oefg"]*100, _ins_lg.get("opp_tov_r",0)*100,
        _ins_lg.get("dreb_p",0)*100, _ins_lg.get("opp_ft_r",0)*100,
    ]
    _i_hib = [True, False, True, True, False, True, True, False]
    _i_bar_colors = [
        "#2ecc71" if ((tv > lv) == hb) else "#e74c3c"
        for tv, lv, hb in zip(_i_team_vals, _i_lg_vals, _i_hib)
    ]
    fig_ff_bar = go.Figure()
    fig_ff_bar.add_trace(go.Bar(
        name=sel_name, x=_i_bar_labels, y=_i_team_vals,
        marker_color=_i_bar_colors, opacity=0.9,
        text=[f"{v:.1f}" for v in _i_team_vals], textposition="outside",
    ))
    fig_ff_bar.add_trace(go.Bar(
        name="League Avg", x=_i_bar_labels, y=_i_lg_vals,
        marker_color="rgba(150,150,150,0.4)",
        text=[f"{v:.1f}" for v in _i_lg_vals], textposition="outside",
    ))
    fig_ff_bar.update_layout(
        **PLOT_LAYOUT, barmode="group",
        title="Four Factors — Team vs League Average (green = better than avg)",
        yaxis_title="Value", height=380,
        xaxis=dict(tickangle=-20, tickfont=dict(size=9)),
        legend=dict(orientation="h", y=-0.15),
    )
    st.plotly_chart(fig_ff_bar, use_container_width=True)

    # Four factors diagnosis bullets
    st.markdown("<div class='section-hdr'>Diagnosis</div>", unsafe_allow_html=True)
    _i_diag = []
    if adv["efg"] > _ins_lg["efg"]:
        _i_diag.append(("✅", "Shooting Efficiency",
                         f"eFG% {adv['efg']*100:.1f}% is above league avg ({_ins_lg['efg']*100:.1f}%) — keep taking good shots."))
    else:
        _i_diag.append(("⚠️", "Shooting Efficiency",
                         f"eFG% {adv['efg']*100:.1f}% trails league avg ({_ins_lg['efg']*100:.1f}%) — improve shot selection or 3P%."))
    if adv["tov_r"] < _ins_lg["tov_r"]:
        _i_diag.append(("✅", "Ball Security",
                         f"TOV rate {adv['tov_r']*100:.1f}% is below avg ({_ins_lg['tov_r']*100:.1f}%) — good decision-making."))
    else:
        _i_diag.append(("⚠️", "Ball Security",
                         f"TOV rate {adv['tov_r']*100:.1f}% exceeds avg ({_ins_lg['tov_r']*100:.1f}%) — turnovers are costing possessions."))
    if adv["oreb_p"] > _ins_lg["oreb_p"]:
        _i_diag.append(("✅", "Offensive Rebounding",
                         f"OREB% {adv['oreb_p']*100:.1f}% above avg ({_ins_lg['oreb_p']*100:.1f}%) — good at second chances."))
    else:
        _i_diag.append(("⚠️", "Offensive Rebounding",
                         f"OREB% {adv['oreb_p']*100:.1f}% below avg ({_ins_lg['oreb_p']*100:.1f}%) — missing second-chance opportunities."))
    if adv["oefg"] < _ins_lg["oefg"]:
        _i_diag.append(("✅", "Defensive eFG% Allowed",
                         f"Holding opponents to {adv['oefg']*100:.1f}% eFG% vs avg {_ins_lg['oefg']*100:.1f}% — solid shot defense."))
    else:
        _i_diag.append(("⚠️", "Defensive eFG% Allowed",
                         f"Opponents shooting {adv['oefg']*100:.1f}% eFG% vs avg {_ins_lg['oefg']*100:.1f}% — contests need to improve."))
    _forced_tov = adv.get("opp_tov_r", 0)
    _lg_forced  = _ins_lg.get("opp_tov_r", 0)
    if _forced_tov > _lg_forced:
        _i_diag.append(("✅", "Defensive Pressure",
                         f"Forcing {_forced_tov*100:.1f}% TOV rate vs avg {_lg_forced*100:.1f}% — active, disruptive defense."))
    else:
        _i_diag.append(("⚠️", "Defensive Pressure",
                         f"Only forcing {_forced_tov*100:.1f}% TOV rate (avg {_lg_forced*100:.1f}%) — need more active hands."))

    for _ico, _icat, _imsg in _i_diag:
        _iclr = "#2ecc71" if _ico == "✅" else "#f0a500"
        st.markdown(
            f"<div style='background:#161b22;border:1px solid #30363d;border-radius:8px;"
            f"padding:10px 14px;margin-bottom:6px;display:flex;gap:10px;align-items:flex-start'>"
            f"<span style='font-size:16px;margin-top:1px'>{_ico}</span>"
            f"<div><span style='color:{_iclr};font-weight:700;font-size:12px'>{_icat}</span>"
            f"<div style='font-size:12px;color:#c9d1d9;margin-top:2px'>{_imsg}</div></div>"
            f"</div>", unsafe_allow_html=True)

    # ── SECTION 2: SHOT SELECTION — 2s vs 3s ─────────────────────────────────
    st.markdown("<div class='section-hdr'>Shot Selection — Should We Take More 2s or 3s?</div>",
                unsafe_allow_html=True)

    _i_2pct  = adv.get("two_pct", 0)       # fraction
    _i_3pct  = adv.get("tpp", 0)           # fraction
    _i_tpar  = adv.get("tpar", 0)          # fraction of FGA that are 3PA
    _i_ev2   = _i_2pct * 2                 # expected pts per 2PA
    _i_ev3   = _i_3pct * 3                 # expected pts per 3PA
    _i_be3   = (2 / 3) * _i_2pct          # break-even 3P% (fraction)
    _i_be2   = (3 / 2) * _i_3pct          # break-even 2P% (fraction)
    _i_3ahead = _i_3pct > _i_be3          # True if 3s are currently better value

    _i_ss_c1, _i_ss_c2 = st.columns([1, 1])
    with _i_ss_c1:
        _ss_kpis = [
            ("2P%",            f"{_i_2pct*100:.1f}%",  "current 2-point FG%",       "#58a6ff"),
            ("3P%",            f"{_i_3pct*100:.1f}%",  "current 3-point FG%",
             "#2ecc71" if _i_3ahead else "#e74c3c"),
            ("Break-even 3P%", f"{_i_be3*100:.1f}%",   "3P% needed to match 2P value",
             "#2ecc71" if _i_3ahead else "#f0a500"),
            ("Break-even 2P%", f"{_i_be2*100:.1f}%",   "2P% needed to match 3P value", "#f0a500"),
            ("EV / 2PA",       f"{_i_ev2:.3f}",        "expected pts per 2-point attempt",
             "#2ecc71" if _i_ev2 >= _i_ev3 else "#8b949e"),
            ("EV / 3PA",       f"{_i_ev3:.3f}",        "expected pts per 3-point attempt",
             "#2ecc71" if _i_ev3 > _i_ev2 else "#8b949e"),
            ("3PA Rate",       f"{_i_tpar*100:.0f}%",  "% of field goal attempts from 3", "#f0a500"),
        ]
        for _ssk, _ssv, _sss, _ssclr in _ss_kpis:
            st.markdown(
                f"<div class='adv-tile' style='margin-bottom:6px'>"
                f"<div class='adv-label'>{_ssk}</div>"
                f"<div class='adv-value' style='color:{_ssclr}'>{_ssv}</div>"
                f"<div style='font-size:10px;color:#8b949e'>{_sss}</div>"
                f"</div>", unsafe_allow_html=True)

    with _i_ss_c2:
        fig_ev = go.Figure()
        _i_ev_clr = ["#58a6ff", "#2ecc71" if _i_3ahead else "#e74c3c"]
        fig_ev.add_trace(go.Bar(
            x=["2-Point", "3-Point"], y=[_i_ev2, _i_ev3],
            marker_color=_i_ev_clr,
            text=[f"{v:.3f} pts/attempt" for v in [_i_ev2, _i_ev3]],
            textposition="outside"))
        fig_ev.update_layout(
            **PLOT_LAYOUT, title="Expected Value per Shot Attempt",
            yaxis_title="Pts / Attempt", height=240,
            yaxis=dict(range=[0, max(_i_ev2, _i_ev3) * 1.25]))
        st.plotly_chart(fig_ev, use_container_width=True)

        # Shot mix donut
        _i_2pa_tot = adv.get("fga", 0) - adv.get("tpa", 0)
        _i_3pa_tot = adv.get("tpa", 0)
        fig_mix = go.Figure(go.Pie(
            labels=["2-Point Attempts", "3-Point Attempts"],
            values=[_i_2pa_tot, _i_3pa_tot],
            hole=0.55,
            marker=dict(colors=["#58a6ff", "#f0a500"]),
            textinfo="label+percent"))
        fig_mix.update_layout(
            **PLOT_LAYOUT, title="Shot Mix", height=220, showlegend=False)
        st.plotly_chart(fig_mix, use_container_width=True)

    # Recommendation banner
    if _i_3ahead:
        _i_rec = f"Take MORE 3s"
        _i_rec_detail = (
            f"Your 3P% ({_i_3pct*100:.1f}%) beats the break-even threshold "
            f"({_i_be3*100:.1f}%). Each 3PA generates {_i_ev3:.3f} pts vs {_i_ev2:.3f} "
            f"for a 2PA. Current 3PA rate is {_i_tpar*100:.0f}% of FGA — "
            f"there's room to push more looks from range.")
        _i_rec_color = "#2ecc71"
    else:
        _i_rec = f"Prioritize 2s (or get better 3P shooters)"
        _i_rec_detail = (
            f"Your 3P% ({_i_3pct*100:.1f}%) falls below the break-even of "
            f"{_i_be3*100:.1f}%. A 2PA is worth {_i_ev2:.3f} pts vs {_i_ev3:.3f} "
            f"for a 3PA right now. Drive to the paint, attack the rim, and only "
            f"launch 3s from your best shooters above that threshold.")
        _i_rec_color = "#f0a500"

    st.markdown(
        f"<div style='background:#161b22;border:2px solid {_i_rec_color};"
        f"border-radius:12px;padding:16px 20px;margin:10px 0'>"
        f"<div style='font-size:10px;color:#8b949e;text-transform:uppercase;"
        f"letter-spacing:1.2px;margin-bottom:6px'>Shot Selection Recommendation</div>"
        f"<div style='font-size:20px;font-weight:900;color:{_i_rec_color};margin-bottom:6px'>"
        f"{_i_rec}</div>"
        f"<div style='font-size:12px;color:#c9d1d9;line-height:1.5'>{_i_rec_detail}</div>"
        f"</div>", unsafe_allow_html=True)

    # Per-player 3P profile: volume vs efficiency vs break-even
    if not _i_rnk.empty and "3PA" in _i_rnk.columns and "3P%" in _i_rnk.columns:
        _i_3p_df = _i_rnk[["Player", "3PA", "3P%", "FGA", "PTS"]].copy()
        _i_3p_df = _i_3p_df[(_i_3p_df["3PA"] > 0)].dropna(subset=["3P%"]).copy()
        if not _i_3p_df.empty:
            st.markdown("<div class='section-hdr'>Per-Player 3-Point Profile</div>",
                        unsafe_allow_html=True)
            _i_3p_df["vs BE"] = _i_3p_df["3P%"] - _i_be3 * 100
            _i_3p_df["EV3"]   = _i_3p_df["3P%"] * 3 / 100
            fig_3p_scat = px.scatter(
                _i_3p_df, x="3PA", y="3P%", size="PTS", color="vs BE",
                text="Player", color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0,
                labels={"3PA": "3PA per Game", "3P%": "3P%",
                        "vs BE": "vs Break-even %"},
                title=f"3PA Volume vs 3P% — break-even line at {_i_be3*100:.1f}%")
            fig_3p_scat.add_hline(
                y=_i_be3 * 100, line_dash="dash", line_color="#f0a500",
                annotation_text=f"Break-even {_i_be3*100:.1f}%",
                annotation_position="top left")
            fig_3p_scat.update_traces(textposition="top center", textfont_size=9)
            fig_3p_scat.update_layout(**PLOT_LAYOUT, height=380)
            st.plotly_chart(fig_3p_scat, use_container_width=True)
            st.caption(
                "Green = shooting above break-even (should take more 3s) · "
                "Red = below break-even (reduce volume or improve selection) · "
                "Bubble size = PPG")

    # ── SECTION 3: MINUTES ALLOCATION ────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Minutes Allocation — Who Deserves More?</div>",
                unsafe_allow_html=True)
    st.caption(
        "MVS (Minutes Value Score) blends Game Score, Efficiency, and team-adjusted "
        "OFF / DEF / PLY / REB ratings to determine who earns more minutes. "
        "On/Off Δ is shown for reference.")

    # ── Pre-compute MVS (does not require lineup data) ─────────────────────
    _mvs_lookup: dict     = {}
    _team_avg_min_mvs     = 0.0
    _team_w: dict         = {"OFF": 0.25, "DEF": 0.25, "PLY": 0.25, "REB_R": 0.25}
    _team_avgs: dict      = {}

    if (not _i_rnk.empty and not _i_rat.empty
            and "pid" in _i_rnk.columns and "pid" in _i_rat.columns):
        _rnk_need = [c for c in ["pid", "MIN", "GS", "EFF"] if c in _i_rnk.columns]
        _rat_need = [c for c in ["pid", "OFF", "DEF", "PLY", "REB_R"] if c in _i_rat.columns]
        if len(_rnk_need) >= 2 and "pid" in _rnk_need:
            _i_mvs_df = (
                _i_rnk[_rnk_need].merge(_i_rat[_rat_need], on="pid", how="inner")
                .dropna(subset=["MIN"]).copy()
            )
            if len(_i_mvs_df) >= 2:
                _team_avgs = {
                    "OFF":   float(_i_mvs_df["OFF"].mean())   if "OFF"   in _i_mvs_df.columns else 50.0,
                    "DEF":   float(_i_mvs_df["DEF"].mean())   if "DEF"   in _i_mvs_df.columns else 50.0,
                    "PLY":   float(_i_mvs_df["PLY"].mean())   if "PLY"   in _i_mvs_df.columns else 50.0,
                    "REB_R": float(_i_mvs_df["REB_R"].mean()) if "REB_R" in _i_mvs_df.columns else 50.0,
                }
                _avg_of_avgs = sum(_team_avgs.values()) / 4
                # lower team avg → higher weight (team needs that dimension most)
                # each 10-pt gap from the mean shifts weight by ~0.05
                _raw_w = {k: max(0.10, 0.25 + (_avg_of_avgs - v) * 0.005)
                          for k, v in _team_avgs.items()}
                _total_rw = sum(_raw_w.values())
                _team_w = {k: v / _total_rw for k, v in _raw_w.items()}

                def _mvs_norm(s: pd.Series) -> pd.Series:
                    lo, hi = s.min(), s.max()
                    if hi == lo:
                        return pd.Series(50.0, index=s.index)
                    return (s - lo) / (hi - lo) * 100.0

                for _rc in ["OFF", "DEF", "PLY", "REB_R"]:
                    if _rc not in _i_mvs_df.columns:
                        _i_mvs_df[_rc] = 50.0

                # Ratings component: team-adjusted blend of the four pillars
                _i_mvs_df["_rat"] = (
                    _team_w["OFF"]   * _i_mvs_df["OFF"]
                    + _team_w["DEF"]   * _i_mvs_df["DEF"]
                    + _team_w["PLY"]   * _i_mvs_df["PLY"]
                    + _team_w["REB_R"] * _i_mvs_df["REB_R"]
                )

                # Production: GS + EFF, normalized within this team's pool
                _i_mvs_df["_gs_n"]  = (_mvs_norm(_i_mvs_df["GS"].fillna(0))
                                        if "GS"  in _i_mvs_df.columns else 50.0)
                _i_mvs_df["_eff_n"] = (_mvs_norm(_i_mvs_df["EFF"].fillna(0))
                                        if "EFF" in _i_mvs_df.columns else 50.0)
                _i_mvs_df["_prod"]  = 0.55 * _i_mvs_df["_gs_n"] + 0.45 * _i_mvs_df["_eff_n"]

                # Per-minute efficiency: GS per minute (rewards impact density)
                _gs_col = _i_mvs_df["GS"] if "GS" in _i_mvs_df.columns else pd.Series(0, index=_i_mvs_df.index)
                _i_mvs_df["_pm_n"] = _mvs_norm(_gs_col / _i_mvs_df["MIN"].clip(lower=1.0))

                # MVS: 45% ratings · 40% production · 15% per-minute efficiency
                _i_mvs_df["_mvs_raw"] = (
                    0.45 * _i_mvs_df["_rat"]
                    + 0.40 * _i_mvs_df["_prod"]
                    + 0.15 * _i_mvs_df["_pm_n"]
                )
                _i_mvs_df["MVS"] = _mvs_norm(_i_mvs_df["_mvs_raw"]).round(1)

                _mvs_lookup       = dict(zip(_i_mvs_df["pid"], _i_mvs_df["MVS"]))
                _team_avg_min_mvs = float(_i_mvs_df["MIN"].mean())

    if not _ins_oo:
        st.info("Need tracked games with lineup snapshots for minutes analysis.")
    else:
        _i_pl_info = query(
            "SELECT id, name, number FROM players WHERE team_id=? AND archived=0",
            (team_id,))
        _i_min_rows = []
        for _iplr in _i_pl_info:
            _ipid = _iplr["id"]
            _ioo  = _ins_oo.get(_ipid, {})
            _ionp = _ioo.get("on_poss", 0)
            _iofp = _ioo.get("off_poss", 0)
            if _ionp == 0:
                continue
            _ior_on  = _ioo["on_pts_for"]    / _ionp  * 100
            _idr_on  = _ioo["on_pts_against"] / _ionp  * 100
            _inet_on = _ior_on - _idr_on
            _ior_off = _ioo["off_pts_for"]   / _iofp  * 100 if _iofp else 0
            _idr_off = _ioo["off_pts_against"]/ _iofp  * 100 if _iofp else 0
            _inet_off = _ior_off - _idr_off
            _idelta  = _inet_on - _inet_off

            _ipl_rnk_row = (_i_rnk[_i_rnk["pid"] == _ipid]
                            if (not _i_rnk.empty and "pid" in _i_rnk.columns)
                            else pd.DataFrame())
            _imin_pg = (float(_ipl_rnk_row["MIN"].iloc[0])
                        if not _ipl_rnk_row.empty and "MIN" in _ipl_rnk_row.columns
                        else None)
            _igs_pg  = (float(_ipl_rnk_row["GS"].iloc[0])
                        if not _ipl_rnk_row.empty and "GS"  in _ipl_rnk_row.columns
                        else None)
            _ieff    = (float(_ipl_rnk_row["EFF"].iloc[0])
                        if not _ipl_rnk_row.empty and "EFF" in _ipl_rnk_row.columns
                        else None)
            _iovrl = None
            if not _i_rat.empty and "pid" in _i_rat.columns:
                _irat_row = _i_rat[_i_rat["pid"] == _ipid]
                if not _irat_row.empty and "OVRL" in _irat_row.columns:
                    _iovrl = float(_irat_row["OVRL"].iloc[0])

            _imvs     = _mvs_lookup.get(_ipid)
            _imin_val = _imin_pg or 0

            # Verdict driven by MVS vs current minutes allocation
            if _imvs is not None:
                if _imvs >= 60 and _imin_val <= _team_avg_min_mvs:
                    _imin_verdict = "▲ More"
                elif _imvs <= 35 and _imin_val >= _team_avg_min_mvs:
                    _imin_verdict = "▼ Less"
                else:
                    _imin_verdict = "— OK"
            else:
                _imin_verdict = ("▲ More" if _idelta > 3 else
                                 "▼ Less"  if _idelta < -3 else "— OK")

            _i_min_rows.append({
                "Player":   f"#{_iplr['number']} {_iplr['name']}",
                "MIN/G":    round(_imin_pg, 1) if _imin_pg is not None else "—",
                "GS/G":     round(_igs_pg,  1) if _igs_pg  is not None else "—",
                "EFF":      round(_ieff,    1) if _ieff    is not None else "—",
                "On/Off Δ": round(_idelta,  1),
                "OVRL":     round(_iovrl,   1) if _iovrl   is not None else "—",
                "MVS":      round(_imvs,    1) if _imvs    is not None else "—",
                "Verdict":  _imin_verdict,
                "_mvs":     _imvs if _imvs is not None else 0,
                "_delta":   _idelta,
                "_min":     _imin_pg or 0,
            })

        if _i_min_rows:
            _i_min_df = pd.DataFrame(_i_min_rows).sort_values("_mvs", ascending=False)

            # Team weight explainer
            if _team_avgs:
                _wlbl = {"OFF": "Offense", "DEF": "Defense",
                         "PLY": "Playmaking", "REB_R": "Rebounding"}
                _weakest_dim = min(_team_avgs, key=_team_avgs.get)
                _w_parts = [
                    f"**{_wlbl[k]}** {_team_w[k]*100:.0f}%"
                    + (" ← team need" if k == _weakest_dim else "")
                    for k in ["OFF", "DEF", "PLY", "REB_R"]
                ]
                st.caption("MVS weights (adjusted to team strengths): " + " · ".join(_w_parts))

            st.dataframe(
                _i_min_df.drop(columns=["_mvs", "_delta", "_min"]),
                use_container_width=True, hide_index=True)

            # MVS bar — horizontal, color-coded
            _i_ms = _i_min_df[_i_min_df["_mvs"] > 0].sort_values("_mvs", ascending=True)
            if not _i_ms.empty:
                _i_bar_clrs = [
                    "#2ecc71" if v >= 60 else "#e74c3c" if v <= 35 else "#f0a500"
                    for v in _i_ms["_mvs"]
                ]
                fig_oo_bar = go.Figure(go.Bar(
                    x=_i_ms["_mvs"], y=_i_ms["Player"],
                    orientation="h", marker_color=_i_bar_clrs,
                    text=[f"{v:.0f}" for v in _i_ms["_mvs"]],
                    textposition="outside"))
                fig_oo_bar.add_vline(x=50, line_color="#555d68", line_width=1)
                fig_oo_bar.add_vline(x=60, line_dash="dot", line_color="#2ecc71",
                                      annotation_text="▲ Give more mins",
                                      annotation_position="top right")
                fig_oo_bar.add_vline(x=35, line_dash="dot", line_color="#e74c3c",
                                      annotation_text="▼ Reduce mins",
                                      annotation_position="top left")
                fig_oo_bar.update_layout(
                    **PLOT_LAYOUT,
                    title="MVS — Minutes Value Score",
                    xaxis_title="MVS (0–100)",
                    xaxis_range=[0, 110],
                    height=max(300, len(_i_ms) * 36 + 80),
                    margin_l=150)
                st.plotly_chart(fig_oo_bar, use_container_width=True)

            # Scatter: minutes vs MVS
            _i_scat_df = _i_min_df[(_i_min_df["_min"] > 0) & (_i_min_df["_mvs"] > 0)].copy()
            if len(_i_scat_df) >= 3:
                st.markdown("<div class='section-hdr'>Minutes Played vs MVS</div>",
                            unsafe_allow_html=True)
                st.caption(
                    "Top-right = earning their minutes. "
                    "Top-left = high MVS, underused — give more. "
                    "Bottom-right = heavy usage, low MVS — consider reducing.")
                fig_min_scat = px.scatter(
                    _i_scat_df, x="_min", y="_mvs",
                    text="Player", color="_mvs",
                    color_continuous_scale="RdYlGn",
                    color_continuous_midpoint=50,
                    range_color=[0, 100],
                    labels={"_min": "Minutes per Game", "_mvs": "MVS"},
                    title="Minutes per Game vs MVS")
                fig_min_scat.add_hline(
                    y=_i_scat_df["_mvs"].mean(), line_dash="dot", line_color="#8b949e",
                    annotation_text="Team avg MVS", annotation_position="top left")
                fig_min_scat.add_vline(
                    x=_i_scat_df["_min"].mean(), line_dash="dot", line_color="#8b949e",
                    annotation_text="Team avg MIN", annotation_position="top right")
                fig_min_scat.update_traces(textposition="top center", textfont_size=9)
                fig_min_scat.update_layout(**PLOT_LAYOUT, height=380,
                                            coloraxis_showscale=False)
                st.plotly_chart(fig_min_scat, use_container_width=True)
        else:
            st.info("Not enough lineup data to compute on/off splits.")

    # ── SECTION 4: PLAYER RATINGS SPOTLIGHT ──────────────────────────────────
    st.markdown("<div class='section-hdr'>Player Ratings Spotlight</div>",
                unsafe_allow_html=True)

    if _i_rat.empty:
        st.info("No player ratings yet — need at least 2 tracked games per player.")
    else:
        _i_rat_cats = [
            ("OVRL",  "Overall",     "#f0a500"),
            ("OFF",   "Offense",     "#2ecc71"),
            ("DEF",   "Defense",     "#3498db"),
            ("PLY",   "Playmaking",  "#9b59b6"),
            ("REB_R", "Rebounding",  "#e67e22"),
        ]

        st.markdown(
            "<div style='font-size:10px;color:#2ecc71;text-transform:uppercase;"
            "letter-spacing:1.2px;font-weight:700;margin-bottom:6px'>BEST IN CATEGORY</div>",
            unsafe_allow_html=True)
        _i_best_cols = st.columns(5)
        for _ibc, (_irk, _irl, _irclr) in zip(_i_best_cols, _i_rat_cats):
            if _irk not in _i_rat.columns:
                continue
            _ibr = _i_rat.loc[_i_rat[_irk].idxmax()]
            _ibv = float(_ibr[_irk])
            _ibc.markdown(
                f"<div class='rat-card'>"
                f"<div style='font-size:9px;color:#8b949e;text-transform:uppercase;"
                f"letter-spacing:1px;margin-bottom:6px'>{_irl}</div>"
                f"<div style='font-size:22px;font-weight:900;color:{_irclr}'>{_ibv:.1f}</div>"
                f"<div style='font-size:12px;color:#f0f6fc;font-weight:700;margin-top:4px'>"
                f"{_ibr['Player']}</div>"
                f"<div style='background:#21262d;border-radius:3px;height:4px;"
                f"overflow:hidden;margin-top:8px'>"
                f"<div style='background:{_irclr};width:{_ibv:.0f}%;height:100%'></div></div>"
                f"</div>", unsafe_allow_html=True)

        st.markdown(
            "<div style='font-size:10px;color:#e74c3c;text-transform:uppercase;"
            "letter-spacing:1.2px;font-weight:700;margin-top:12px;margin-bottom:6px'>"
            "MOST ROOM TO GROW</div>",
            unsafe_allow_html=True)
        _i_worst_cols = st.columns(5)
        for _iwc, (_irk, _irl, _irclr) in zip(_i_worst_cols, _i_rat_cats):
            if _irk not in _i_rat.columns:
                continue
            _iwr = _i_rat.loc[_i_rat[_irk].idxmin()]
            _iwv = float(_iwr[_irk])
            _iwc.markdown(
                f"<div class='rat-card'>"
                f"<div style='font-size:9px;color:#8b949e;text-transform:uppercase;"
                f"letter-spacing:1px;margin-bottom:6px'>{_irl}</div>"
                f"<div style='font-size:22px;font-weight:900;color:#e74c3c'>{_iwv:.1f}</div>"
                f"<div style='font-size:12px;color:#f0f6fc;font-weight:700;margin-top:4px'>"
                f"{_iwr['Player']}</div>"
                f"<div style='background:#21262d;border-radius:3px;height:4px;"
                f"overflow:hidden;margin-top:8px'>"
                f"<div style='background:#e74c3c;width:{_iwv:.0f}%;height:100%'></div></div>"
                f"</div>", unsafe_allow_html=True)

        # Full ratings table for quick reference
        st.write("")
        _i_rat_show_cols = [c for c in ["Player","#","GP","OVRL","OFF","DEF","PLY","REB_R"]
                            if c in _i_rat.columns]
        if _i_rat_show_cols:
            st.dataframe(
                _i_rat[_i_rat_show_cols].sort_values("OVRL", ascending=False)
                .reset_index(drop=True),
                use_container_width=True, hide_index=True)
            st.caption("All ratings 0–100 vs full player pool across all teams.")

    # ── SECTION 5: SCOUTING REPORT ───────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Scouting Report & Strategy Tips</div>",
                unsafe_allow_html=True)

    _i_tips: list = []  # (icon, title, category, message)

    # Offensive identity
    if _i_tpar > 0.38:
        _i_tips.append(("🏹", "Perimeter-Oriented Offense",    "offense",
                         f"Taking {_i_tpar*100:.0f}% of shots from 3 — a true perimeter team. "
                         f"Opposing defenses should extend and close out hard on the 3-point line."))
    elif _i_tpar < 0.22:
        _i_tips.append(("🦏", "Interior-Heavy Offense",        "offense",
                         f"Only {_i_tpar*100:.0f}% of shots from 3 — attacks the paint relentlessly. "
                         f"Watch for post-ups, drives, and draw-and-kick opportunities."))
    else:
        _i_tips.append(("⚖️", "Balanced Shot Diet",             "offense",
                         f"{_i_tpar*100:.0f}% 3PA rate — mix of inside and outside. "
                         f"No obvious shot-selection bias to exploit or defend."))

    _i_ast_pct = adv.get("ast_pct", 0)
    if _i_ast_pct > 60:
        _i_tips.append(("🔗", "Ball-Movement Team",             "offense",
                         f"{_i_ast_pct:.0f}% of made FGs are assisted — heavy ball movement. "
                         f"Break down passing lanes; deny the secondary ball-handlers."))
    elif _i_ast_pct < 35:
        _i_tips.append(("⚡", "Isolation-Heavy Offense",        "offense",
                         f"Only {_i_ast_pct:.0f}% of FGs assisted — self-creation dominant. "
                         f"Key: who are the primary creators? Limit their touches and force others to beat you."))

    _i_paint_ppg = adv.get("paint_pts_pg", 0)
    if _i_paint_ppg > 14:
        _i_tips.append(("🎯", "Strong Paint Presence",           "offense",
                         f"{_i_paint_ppg:.1f} paint points per game — dominant inside. "
                         f"Must defend the rim; pack the paint and force kick-outs."))

    if adv["ft_r"] > _ins_lg["ft_r"] * 1.2:
        _i_tips.append(("🎁", "Gets to the Line Often",          "offense",
                         f"FT rate {adv['ft_r']*100:.0f}% — significantly above league avg. "
                         f"Attacks the basket and draws fouls. Stay disciplined; avoid reach-in fouls."))

    # Defensive identity
    _i_blk_rate = adv.get("blk_rate", 0)
    if _i_blk_rate > 8:
        _i_tips.append(("🏰", "Shot-Blocking Defense",           "defense",
                         f"Blocking {_i_blk_rate:.1f}% of opponent 2PAs — strong rim protection. "
                         f"Drive straight at the rim with caution; look for pump-fakes to draw fouls."))

    if _forced_tov > _ins_lg.get("opp_tov_r", 0) * 1.15:
        _i_tips.append(("💨", "High-Pressure Defense",           "defense",
                         f"Forcing {_forced_tov*100:.1f}% TOV rate — active, aggressive defenders. "
                         f"Protect the ball; limit risky passes and crosscourt throws."))

    if adv.get("opp_oreb_p", 0) > 0.30:
        _i_tips.append(("⚠️", "Defensive Rebounding Concern",    "defense",
                         f"Opponents grabbing {adv.get('opp_oreb_p',0)*100:.1f}% of their own misses. "
                         f"Box-out discipline is an issue — target second-chance points offensively."))

    if adv.get("dreb_p", 0) > _ins_lg.get("dreb_p", 0) * 1.1:
        _i_tips.append(("🧱", "Elite Defensive Rebounding",      "defense",
                         f"DREB% {adv.get('dreb_p',0)*100:.1f}% — shuts down second chances. "
                         f"Offense needs to follow misses hard; crash the glass aggressively."))

    # Efficiency summary
    _i_net = adv["ortg"] - adv["drtg"]
    if _i_net > 8:
        _i_tips.append(("🏆", f"Elite Team (Net +{_i_net:.1f})",  "strength",
                         f"ORtg {adv['ortg']:.1f} — DRtg {adv['drtg']:.1f} = "
                         f"net +{_i_net:.1f}. Dominant on both ends of the floor."))
    elif _i_net > 0:
        _i_tips.append(("📈", f"Positive Net Rating (+{_i_net:.1f})", "strength",
                         f"ORtg {adv['ortg']:.1f} — DRtg {adv['drtg']:.1f}. "
                         f"Winning team, edge comes from {'offense' if adv['ortg'] > adv['drtg']+5 else 'defense'}."))
    else:
        _i_tips.append(("📉", f"Negative Net Rating ({_i_net:+.1f})", "strength",
                         f"ORtg {adv['ortg']:.1f} — DRtg {adv['drtg']:.1f}. "
                         f"Improvement needed; {'offense' if adv['ortg'] < adv['drtg']-5 else 'defense'} is the bigger drag."))

    for _i_cat, _i_cat_lbl, _i_cat_clr in [
        ("offense",  "Offensive Tendencies",  "#f0a500"),
        ("defense",  "Defensive Tendencies",  "#3498db"),
        ("strength", "Overall Assessment",    "#2ecc71"),
    ]:
        _cat_tips = [t for t in _i_tips if t[2] == _i_cat]
        if not _cat_tips:
            continue
        st.markdown(
            f"<div style='font-size:10px;color:{_i_cat_clr};text-transform:uppercase;"
            f"letter-spacing:1.2px;font-weight:700;margin:12px 0 6px'>"
            f"{_i_cat_lbl}</div>", unsafe_allow_html=True)
        for _ti, _tttl, _tcf, _tmsg in _cat_tips:
            st.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;"
                f"border-radius:8px;padding:10px 14px;margin-bottom:6px'>"
                f"<span style='font-size:14px;margin-right:8px'>{_ti}</span>"
                f"<span style='color:{_i_cat_clr};font-weight:700;font-size:12px'>{_tttl}</span>"
                f"<div style='font-size:12px;color:#c9d1d9;margin-top:4px;line-height:1.4'>"
                f"{_tmsg}</div>"
                f"</div>", unsafe_allow_html=True)

    # ── SECTION 6: TEAM NEEDS / WHO TO TARGET ────────────────────────────────
    st.markdown("<div class='section-hdr'>Team Needs — What Profile to Target</div>",
                unsafe_allow_html=True)
    st.caption("Based on where this team falls below league average across the Four Factors.")

    _i_needs: list = []  # (icon, role, why, target_description)

    if adv["efg"] < _ins_lg["efg"]:
        _i_needs.append(("🎯", "Efficient Scorer / Shooter",
                          f"eFG% ({adv['efg']*100:.1f}%) is below avg ({_ins_lg['efg']*100:.1f}%)",
                          "Target: high eFG%, good 3P% above break-even, smart shot selection. "
                          "Even a moderate scorer with great efficiency raises the team floor."))

    if adv["tov_r"] > _ins_lg["tov_r"]:
        _i_needs.append(("🎮", "Ball-Security Guard / Handler",
                          f"TOV rate ({adv['tov_r']*100:.1f}%) above avg ({_ins_lg['tov_r']*100:.1f}%)",
                          "Target: high AST/TOV ratio, low usage with high efficiency, "
                          "calm decision-maker under pressure."))

    if adv["oreb_p"] < _ins_lg["oreb_p"]:
        _i_needs.append(("🏀", "Active Rebounder / Big",
                          f"OREB% ({adv['oreb_p']*100:.1f}%) below avg ({_ins_lg['oreb_p']*100:.1f}%)",
                          "Target: high OREB rating, physical presence, crashes the glass relentlessly. "
                          "Second-chance points are free points — don't leave them."))

    if adv["ft_r"] < _ins_lg["ft_r"]:
        _i_needs.append(("⚡", "Downhill Driver / Slasher",
                          f"FT rate ({adv['ft_r']*100:.0f}%) below avg ({_ins_lg['ft_r']*100:.0f}%)",
                          "Target: attacks the basket, draws contact, high FTr. "
                          "Getting to the line is repeatable, high-value offense."))

    if adv["oefg"] > _ins_lg["oefg"]:
        _i_needs.append(("🛡️", "Perimeter / Interior Defender",
                          f"Allowing eFG% ({adv['oefg']*100:.1f}%) above avg ({_ins_lg['oefg']*100:.1f}%)",
                          "Target: high DEF rating, active shot-contester, "
                          "ability to guard multiple positions and contest without fouling."))

    if _forced_tov < _ins_lg.get("opp_tov_r", 0):
        _i_needs.append(("🤲", "Defensive Disruptor / Pressure Guard",
                          f"Forcing only {_forced_tov*100:.1f}% TOV rate "
                          f"vs avg {_ins_lg.get('opp_tov_r',0)*100:.1f}%",
                          "Target: high STL rate, quick hands, pressure defender. "
                          "Turnovers convert directly to fast-break points."))

    if adv.get("dreb_p", 0) < _ins_lg.get("dreb_p", 0):
        _i_needs.append(("🧱", "Defensive Rebounder",
                          f"DREB% ({adv.get('dreb_p',0)*100:.1f}%) below avg "
                          f"({_ins_lg.get('dreb_p',0)*100:.1f}%)",
                          "Target: high REB_R rating, strong box-out instincts, "
                          "denies second-chance opportunities."))

    if not _i_needs:
        st.success(
            f"No glaring roster weaknesses detected across the Four Factors. "
            f"This team is performing at or above league average in all key areas. "
            f"Focus on depth and health rather than specific skill additions.")
    else:
        for _ini, _inr, _inw, _int in _i_needs:
            st.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;"
                f"border-radius:10px;padding:14px 16px;margin-bottom:8px'>"
                f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:6px'>"
                f"<span style='font-size:18px'>{_ini}</span>"
                f"<span style='font-weight:700;color:#f0a500;font-size:13px'>{_inr}</span>"
                f"</div>"
                f"<div style='font-size:11px;color:#e74c3c;margin-bottom:4px'>Why: {_inw}</div>"
                f"<div style='font-size:12px;color:#c9d1d9;line-height:1.4'>{_int}</div>"
                f"</div>", unsafe_allow_html=True)
