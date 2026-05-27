import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from collections import defaultdict as _dd
from Database.db import query, initialize_database
from helpers.constants import CLASS_ORDER, _RYG, _RYG_R
from helpers.game_utils import streak, record_str, normalize, games_for_team, win_loss, opponent_name
from helpers.stats_rankings import game_team_stats, compute_all_rankings, compute_tracked_rankings
from helpers.stats_team import compute_matchup, compute_team_tracked
from helpers.stats_players import compute_game_box_score, compute_game_quarter_scores
from helpers.settings_utils import get_all_settings, apply_page_config, apply_theme_css
from helpers.box_score_render import show_game_box_score, _show_linescore
from helpers.charts import (show_shot_chart, show_scoring_pie,
                             show_four_factors_bars, show_efficiency_scatter,
                             show_matchup_bars, show_player_leaderboard_chart,
                             show_trend_chart, show_score_flow_chart,
                             show_pace_scatter)
from helpers.ui_utils import patch_dataframe

initialize_database()
_cfg = get_all_settings()
apply_page_config(_cfg)
apply_theme_css(_cfg)
patch_dataframe()

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.dash-card {
    background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:20px 22px; margin-bottom:14px;
}
.dash-card-title { font-size:10px; color:#8b949e; text-transform:uppercase;
                   letter-spacing:1.2px; margin-bottom:6px; }
.dash-card-value { font-size:34px; font-weight:800; color:#f0a500; line-height:1.1; }
.dash-card-sub   { font-size:13px; color:#c9d1d9; margin-top:6px; }
.dash-card-meta  { font-size:11px; color:#8b949e; margin-top:2px; }
.score-card {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:10px 14px; margin-bottom:6px;
}
.score-card-date { font-size:10px; color:#8b949e; margin-bottom:5px; }
.score-card-team { font-size:13px; font-weight:600; color:#c9d1d9; }
.score-card-pts  { font-size:20px; font-weight:800; }
.score-winner    { color:#f0a500; }
.score-loser     { color:#555d68; }
.score-final     { font-size:10px; color:#2ecc71; margin-top:4px; }
.rank-card {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:12px 16px; margin-bottom:6px; display:flex;
    align-items:center; gap:12px;
}
.rank-badge {
    width:34px; height:34px; border-radius:50%; display:flex;
    align-items:center; justify-content:center;
    font-weight:800; font-size:13px; flex-shrink:0;
}
.rank-1  { background:#f0a500; color:#000; }
.rank-2  { background:#adb5bd; color:#000; }
.rank-3  { background:#cd7f32; color:#fff; }
.rank-n  { background:#2d333b; color:#c9d1d9; }
.rank-team { font-size:14px; font-weight:700; color:#f0f6fc; }
.rank-rec  { font-size:12px; color:#8b949e; }
.rank-ps   { font-size:13px; font-weight:700; color:#58a6ff; margin-left:auto; text-align:right; }
.rank-vs   { font-size:10px; color:#8b949e; margin-top:3px; }
.tracked-badge {
    display:inline-block; background:#1f3d2a; border:1px solid #2ecc71;
    color:#2ecc71; font-size:9px; font-weight:700; text-transform:uppercase;
    letter-spacing:1px; border-radius:4px; padding:2px 6px; margin-left:6px;
}
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
.pl-card {
    background:linear-gradient(135deg,#0f3460 0%,#16213e 100%);
    border:1px solid #1f4d8a; border-radius:12px;
    padding:18px; text-align:center; margin-bottom:8px;
}
.pl-label { font-size:10px; color:#8b949e; text-transform:uppercase;
            letter-spacing:1px; margin-bottom:6px; }
.pl-value { font-size:30px; font-weight:800; color:#f0a500; }
.pl-name  { font-size:14px; font-weight:700; color:#f0f6fc; margin-top:4px; }
.pl-meta  { font-size:11px; color:#8b949e; }
.section-hdr {
    font-size:18px; font-weight:700; color:#f0f6fc;
    border-left:4px solid #f0a500; padding-left:10px; margin:18px 0 10px;
}
.ts-table { width:100%; border-collapse:collapse; font-size:13px; }
.ts-table th {
    background:#1c2128; color:#8b949e; font-size:10px; text-transform:uppercase;
    letter-spacing:1px; padding:7px 10px; border-bottom:1px solid #30363d; text-align:left;
}
.ts-table td { padding:7px 10px; border-bottom:1px solid #21262d; color:#c9d1d9; }
.ts-table tr:hover td { background:rgba(255,255,255,0.04); }
.ts-rank { font-weight:800; color:#f0a500; width:36px; text-align:center; }
.ts-team { font-weight:700; color:#f0f6fc; }
.ts-sub  { font-size:11px; color:#8b949e; }
.ts-ps   { font-weight:700; color:#58a6ff; text-align:right; }
.ts-w    { color:#2ecc71; font-weight:700; }
.ts-l    { color:#e74c3c; font-weight:700; }
.ts-vs   { font-size:11px; color:#8b949e; }
.rec-pill {
    display:inline-block; background:#161b22; border:1px solid #30363d;
    border-radius:6px; padding:3px 10px; margin:3px 4px 3px 0;
    font-size:12px; color:#c9d1d9;
}
.rec-pill b   { color:#f0f6fc; }
.rec-pill span{ color:#8b949e; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE TITLE + GLOBAL FILTERS
# ══════════════════════════════════════════════════════════════════════════════

st.title("📊 League Analytics")

f1, f2, f3 = st.columns(3)
sel_class  = f1.multiselect("Class", CLASS_ORDER, default=CLASS_ORDER)
sel_gender = f2.selectbox("Gender", ["All", "M", "F"])
min_gp     = f3.number_input("Min Games", min_value=0, value=0, step=1)


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "Class" in df.columns:
        df = df[df["Class"].isin(sel_class)]
    if sel_gender != "All" and "Gender" in df.columns:
        df = df[df["Gender"] == sel_gender]
    if "GP" in df.columns:
        df = df[df["GP"] >= min_gp]
    return df

def _f(df):
    return apply_filters(df) if not df.empty else df


# ── Load data ─────────────────────────────────────────────────────────────────
with st.spinner("Loading data…"):
    df_all = compute_all_rankings()
    df_tr  = compute_tracked_rankings()

# ── Team ID map for tracked deep-dive ─────────────────────────────────────────
_all_teams_q  = query("SELECT id, name FROM teams")
_name_to_id   = {t["name"]: t["id"] for t in _all_teams_q}
_id_to_name   = {t["id"]: t["name"] for t in _all_teams_q}

# ── Everything Rank (Power Score rank, unfiltered) ─────────────────────────────
_ev_rank_df  = df_all.sort_values("Power Score", ascending=False).reset_index(drop=True) \
               if not df_all.empty else pd.DataFrame()
_ev_rank_map: dict = {}          # team_name → 1-based rank
if not _ev_rank_df.empty:
    for _i, _row in _ev_rank_df.iterrows():
        _ev_rank_map[_row["Team"]] = _i + 1

# ── vs Top-N Records ──────────────────────────────────────────────────────────
_vs_rec: dict = _dd(lambda: {5: [0, 0], 10: [0, 0], 20: [0, 0]})
_finished_games = query(
    "SELECT team1_id, team2_id, home_score, away_score "
    "FROM games WHERE home_score IS NOT NULL AND away_score IS NOT NULL"
)
for _g in _finished_games:
    _t1n = _id_to_name.get(_g["team1_id"], "")
    _t2n = _id_to_name.get(_g["team2_id"], "")
    _t1w = (_g["home_score"] or 0) > (_g["away_score"] or 0)
    _r1  = _ev_rank_map.get(_t1n, 9999)
    _r2  = _ev_rank_map.get(_t2n, 9999)
    for _n in [5, 10, 20]:
        if _r2 <= _n:          # t1 played a top-N team
            _vs_rec[_t1n][_n][0 if _t1w else 1] += 1
        if _r1 <= _n:          # t2 played a top-N team
            _vs_rec[_t2n][_n][0 if not _t1w else 1] += 1

def _vs_str(team: str, n: int) -> str:
    w, l = _vs_rec[team][n]
    return f"{w}-{l}"

def _ev_rank(team: str) -> int:
    return _ev_rank_map.get(team, 9999)

def _rank_badge_cls(r: int) -> str:
    return {1: "rank-1", 2: "rank-2", 3: "rank-3"}.get(r, "rank-n")


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED VISUAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_GOOD_LOW = {
    "DRtg", "Opp eFG%", "Opp TS%", "TOV%", "TOV/G", "PA/G",
    "Worst Loss", "L", "Opp PPP", "TOV/Poss", "Avg Poss (s)",
    "Opp FT Rate", "Q4 PA/G", "Unast%",
}
_GRADIENT_COLS = {
    "W%", "PPG", "PA/G", "Diff", "SOS", "SOR", "Power Score",
    "ORtg", "DRtg", "Net Rtg", "eFG%", "Opp eFG%", "TS%", "Opp TS%",
    "TOV%", "OREB%", "DREB%", "FG%", "2P%", "3P%", "FT%", "FT Rate", "Opp FT Rate",
    "AST/G", "STL/G", "BLK/G", "TOV/G", "BLK Rate", "STL Rate",
    "AST/TOV", "Opp TOV%", "Ast%", "Unast%",
    "Paint FG%", "Paint Pts/G", "Pts from 2%", "Pts from 3%", "Pts from FT%",
    "Q4 Pts/G", "Q4 PA/G", "Q4 Diff",
    "PPP", "Opp PPP", "TOV/Poss",
}

def _apply_grads(styler, cols):
    for c in cols:
        if c not in styler.data.columns:
            continue
        if not pd.api.types.is_numeric_dtype(styler.data[c]):
            continue
        if c in ("Rank", "GP", "W", "L", "Best Win", "Worst Loss"):
            continue
        try:
            styler = styler.background_gradient(
                subset=[c], cmap="RdYlGn_r" if c in _GOOD_LOW else "RdYlGn", axis=0)
        except Exception:
            pass
    return styler

def show_table(df, display_cols, sort_default, use_gradients=True):
    _k = "_tbl_counter"
    st.session_state[_k] = st.session_state.get(_k, 0) + 1
    uid = st.session_state[_k]
    if df.empty:
        st.info("No data available.")
        return
    filtered = apply_filters(df)
    if filtered.empty:
        st.info("No teams match the filters.")
        return
    avail = [c for c in display_cols if c in filtered.columns]
    sort_col = st.selectbox("Sort by", avail,
                             index=avail.index(sort_default) if sort_default in avail else 0,
                             key=f"sort_{uid}_{sort_default}")
    asc = sort_col in _GOOD_LOW or sort_col == "Rank"
    out = filtered[avail].sort_values(sort_col, ascending=asc).reset_index(drop=True)
    out.index += 1
    if use_gradients:
        grad_targets = [c for c in avail if c in _GRADIENT_COLS]
        styler = out.style.set_properties(**{"font-size": "13px"})
        styler = _apply_grads(styler, grad_targets)
        st.dataframe(styler, use_container_width=True)
    else:
        st.dataframe(out, use_container_width=True)

def show_class_breakdown(df, display_cols):
    if df.empty:
        return
    filtered = apply_filters(df)
    for cls in CLASS_ORDER:
        cls_df = filtered[filtered["Class"] == cls] if "Class" in filtered.columns else pd.DataFrame()
        if cls_df.empty:
            continue
        with st.expander(f"Class {cls}  ({len(cls_df)} teams)"):
            avail = [c for c in display_cols if c in cls_df.columns]
            if "Power Score" not in avail:
                avail_sort = avail[0] if avail else None
            else:
                avail_sort = "Power Score"
            if avail_sort:
                out = cls_df[avail].sort_values(avail_sort, ascending=False).reset_index(drop=True)
            else:
                out = cls_df[avail].reset_index(drop=True)
            out.index += 1
            grad_targets = [c for c in avail if c in _GRADIENT_COLS]
            styler = out.style.set_properties(**{"font-size": "13px"})
            styler = _apply_grads(styler, grad_targets)
            st.dataframe(styler, use_container_width=True)

def show_power_chart(df, title, n=20, key="power_chart"):
    fdf = _f(df)
    if fdf.empty:
        return
    top = fdf.nsmallest(min(n, len(fdf)), "Rank").sort_values("Rank", ascending=False)
    fig = px.bar(top, x="Power Score", y="Team", orientation="h",
                 color="Power Score", color_continuous_scale=_RYG, text="Power Score",
                 hover_data={"Class": True, "W": True, "L": True, "W%": ":.1f",
                             "Diff": ":.1f", "Power Score": ":.1f"},
                 title=title)
    fig.update_traces(textposition="outside", texttemplate="%{text:.1f}", textfont_size=11)
    fig.update_layout(height=max(380, len(top) * 30 + 80), coloraxis_showscale=False,
                      yaxis_title="", xaxis_title="Power Score (0–100)",
                      xaxis=dict(range=[0, 112], gridcolor="rgba(128,128,128,0.15)"),
                      margin=dict(l=10, r=70, t=50, b=20),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(size=12))
    st.plotly_chart(fig, use_container_width=True, key=key)

def show_net_rtg_chart(df, key="net_rtg_chart"):
    fdf = _f(df)
    if fdf.empty or "Net Rtg" not in fdf.columns:
        return
    sdf = fdf.sort_values("Net Rtg", ascending=True)
    colors = ["#1a9850" if v >= 0 else "#d73027" for v in sdf["Net Rtg"]]
    fig = go.Figure(go.Bar(x=sdf["Net Rtg"], y=sdf["Team"], orientation="h",
                            marker_color=colors,
                            text=sdf["Net Rtg"].apply(lambda v: f"{v:+.1f}"),
                            textposition="outside",
                            hovertemplate="%{y}<br>Net Rtg: %{x:+.1f}<extra></extra>"))
    fig.add_vline(x=0, line_color="rgba(180,180,180,0.8)", line_width=1.5)
    fig.update_layout(title="Net Rating (ORtg − DRtg)",
                      height=max(380, len(sdf) * 26 + 80),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=70, t=50, b=20),
                      xaxis=dict(gridcolor="rgba(128,128,128,0.15)"), font=dict(size=11))
    st.plotly_chart(fig, use_container_width=True, key=key)

def show_stat_leaders(df, stats):
    fdf = _f(df)
    if fdf.empty:
        return
    medals = ["🥇", "🥈", "🥉", " 4.", " 5."]
    cols = st.columns(len(stats))
    for col, (stat, label, hib) in zip(cols, stats):
        if stat not in fdf.columns:
            continue
        sub = fdf[["Team", "Class", "GP", stat]].dropna()
        if sub.empty:
            continue
        top5 = sub.nlargest(5, stat) if hib else sub.nsmallest(5, stat)
        with col:
            st.markdown(f"**{label}**")
            for i, (_, row) in enumerate(top5.iterrows()):
                val = row[stat]
                fmt = (f"{val:+.1f}" if stat in ("Diff", "Net Rtg", "Q4 Diff")
                       else f"{val:.1f}" if isinstance(val, float) else str(val))
                st.markdown(f"{medals[i]} **{row['Team']}** `{row['Class']}`  {fmt}")

def show_scoring_dist_chart(df, key="scoring_dist_chart"):
    fdf = _f(df)
    if fdf.empty or "Pts from 2%" not in fdf.columns:
        return
    sdf = fdf.sort_values("Power Score", ascending=False).head(20)
    fig = go.Figure()
    for col, color, lbl in [("Pts from 2%", "#2166ac", "2PT %"),
                              ("Pts from 3%", "#1a9850", "3PT %"),
                              ("Pts from FT%", "#d73027", "FT %")]:
        fig.add_trace(go.Bar(name=lbl, x=sdf["Team"], y=sdf[col],
                             marker_color=color,
                             hovertemplate="%{x}<br>" + lbl + ": %{y:.1f}%<extra></extra>"))
    fig.update_layout(barmode="stack", title="Scoring Sources — Top 20",
                      yaxis_title="% of Points", height=380,
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=20, r=20, t=50, b=80),
                      legend=dict(orientation="h", y=1.08),
                      xaxis=dict(tickangle=-40), font=dict(size=11))
    st.plotly_chart(fig, use_container_width=True, key=key)

def show_team_radar(df, radar_stats, key="radar"):
    fdf = _f(df)
    if fdf.empty:
        return
    team_names = sorted(fdf["Team"].tolist())
    selected = st.multiselect("Compare teams on radar (2–5)", team_names, max_selections=5, key=key)
    if not selected:
        st.caption("Select teams above to compare stats visually.")
        return
    cats = [l for _, l, _ in radar_stats]
    cols = [c for c, _, _ in radar_stats]
    hibs = [h for _, _, h in radar_stats]
    normed = {}
    for c, hib in zip(cols, hibs):
        if c not in fdf.columns:
            continue
        s = fdf[c]
        lo, hi = s.min(), s.max()
        normed[c] = (((s - lo) / (hi - lo) if hi != lo else pd.Series(0.5, index=fdf.index))
                     .apply(lambda v: v if hib else 1 - v) * 100)
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    fig = go.Figure()
    for i, team in enumerate(selected):
        row = fdf[fdf["Team"] == team]
        if row.empty:
            continue
        idx   = row.index[0]
        nv    = [normed[c][idx] if c in normed else 50 for c in cols]
        rv    = [row[c].values[0] if c in row.columns else 0 for c in cols]
        hl    = "<br>".join(f"{cat}: {rv_:.1f}" for cat, rv_ in zip(cats, rv))
        color = palette[i % len(palette)]
        fig.add_trace(go.Scatterpolar(r=nv + [nv[0]], theta=cats + [cats[0]],
            fill="toself", fillcolor=color, line=dict(color=color, width=2),
            opacity=0.25, name=team,
            hovertemplate=f"<b>{team}</b><br>{hl}<extra></extra>"))
        fig.add_trace(go.Scatterpolar(r=nv + [nv[0]], theta=cats + [cats[0]],
            mode="lines+markers", line=dict(color=color, width=2),
            marker=dict(size=6, color=color), showlegend=False, hoverinfo="skip"))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100], showticklabels=False,
                                   gridcolor="rgba(150,150,150,0.25)"),
                   angularaxis=dict(tickfont=dict(size=11)), bgcolor="rgba(0,0,0,0)"),
        showlegend=True, height=460,
        margin=dict(l=50, r=50, t=60, b=50), paper_bgcolor="rgba(0,0,0,0)",
        title="Team Comparison — normalized vs filter set (100 = best)",
        font=dict(size=11), legend=dict(orientation="h", y=-0.08))
    st.plotly_chart(fig, use_container_width=True)

def show_four_factors_chart(df):
    fdf = _f(df)
    if fdf.empty or "eFG%" not in fdf.columns:
        return
    ranked_teams  = fdf.sort_values("Power Score", ascending=False)["Team"].tolist()
    default_teams = ranked_teams[:15]
    selected = st.multiselect("Teams to include", options=ranked_teams,
                               default=default_teams, key="ff_team_picker",
                               help="Leave blank to reset to top 15.")
    teams_to_show = selected if selected else default_teams
    sdf = fdf[fdf["Team"].isin(teams_to_show)].sort_values("Power Score", ascending=False)
    if sdf.empty:
        st.info("No data for selected teams.")
        return
    cats = ["eFG%", "TOV% (inv)", "OREB%", "FT Rate",
            "Opp eFG% (inv)", "Opp TOV%", "DREB%", "Opp FT Rate (inv)"]
    factor_cfg = [("eFG%", True), ("TOV%", False), ("OREB%", True), ("FT Rate", True),
                  ("Opp eFG%", False), ("Opp TOV%", True), ("DREB%", True), ("Opp FT Rate", False)]
    def pct(col, hib):
        lo, hi = sdf[col].min(), sdf[col].max()
        if hi == lo:
            return 50.0
        try:
            v = sdf.loc[sdf["Team"] == team_name, col].values[0]
        except Exception:
            return 0.0
        return ((v - lo) / (hi - lo) if hib else 1 - (v - lo) / (hi - lo)) * 100
    palette = px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
    n_teams = len(sdf)
    fig = go.Figure()
    for i, row in enumerate(sdf.itertuples()):
        team_name = row.Team
        vals  = [pct(col, hib) for col, hib in factor_cfg if col in sdf.columns]
        color = palette[i % len(palette)]
        opa   = max(0.12, 0.45 - n_teams * 0.015)
        hl    = "<br>".join(
            f"{cats[j]}: {sdf.loc[sdf['Team'] == team_name, col].values[0]:.1f}"
            for j, (col, _) in enumerate(factor_cfg) if col in sdf.columns)
        fig.add_trace(go.Scatterpolar(r=vals + [vals[0]], theta=cats + [cats[0]],
            name=team_name, fill="toself", line=dict(color=color, width=2),
            opacity=opa, hovertemplate=f"<b>{team_name}</b><br>{hl}<extra></extra>"))
        fig.add_trace(go.Scatterpolar(r=vals + [vals[0]], theta=cats + [cats[0]],
            mode="lines", line=dict(color=color, width=2), showlegend=False, hoverinfo="skip"))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100], showticklabels=False,
                                   gridcolor="rgba(150,150,150,0.2)"),
                   angularaxis=dict(tickfont=dict(size=11)), bgcolor="rgba(0,0,0,0)"),
        showlegend=True, height=520, paper_bgcolor="rgba(0,0,0,0)",
        title=f"Four Factors Radar — {n_teams} team{'s' if n_teams != 1 else ''} (normalized)",
        legend=dict(orientation="h", y=-0.15, font=dict(size=9)),
        margin=dict(l=50, r=50, t=70, b=100))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("100 = best among shown teams · inverted axes for TOV, Opp eFG%, Opp FT Rate")


# ── Column presets ────────────────────────────────────────────────────────────
ALL_COLS          = ["Rank", "Team", "Class", "Gender", "GP", "W", "L", "W%",
                     "PPG", "PA/G", "Diff", "SOS", "SOR",
                     "Home", "Away", "Best Win", "Worst Loss", "Streak", "Power Score"]
CORE_COLS         = ["Rank", "Team", "Class", "Gender", "GP", "W", "L", "W%",
                     "PPG", "PA/G", "Diff", "SOS", "SOR", "Home", "Away", "Streak", "Power Score"]
EFF_COLS          = ["Rank", "Team", "Class", "Gender", "GP",
                     "ORtg", "DRtg", "Net Rtg", "Pace",
                     "eFG%", "Opp eFG%", "TS%", "Opp TS%",
                     "TOV%", "OREB%", "DREB%", "AST/TOV", "Power Score"]
SHOOT_COLS        = ["Rank", "Team", "Class", "Gender", "GP",
                     "FG%", "2P%", "eFG%", "TS%", "3P%", "FT%",
                     "3PAr", "FT Rate", "Ast%", "Unast%",
                     "Paint FG%", "Paint Pts/G",
                     "Pts from 2%", "Pts from 3%", "Pts from FT%", "Power Score"]
MISC_COLS         = ["Rank", "Team", "Class", "Gender", "GP",
                     "AST/G", "STL/G", "BLK/G", "TOV/G", "OREB/G", "DREB/G",
                     "BLK Rate", "STL Rate", "AST/TOV",
                     "Q4 Pts/G", "Q4 PA/G", "Q4 Diff",
                     "Best Win", "Worst Loss", "Streak", "Power Score"]
POSS_COLS         = ["Rank", "Team", "Class", "Gender", "GP",
                     "Poss/G", "PPP", "Opp PPP", "Avg Poss (s)",
                     "TOV/Poss", "AST/Poss", "OREB%", "DREB%", "FT Rate", "Power Score"]
FOUR_FACTORS_COLS = ["Rank", "Team", "Class", "Gender", "GP",
                     "eFG%", "TOV%", "OREB%", "FT Rate",
                     "Opp eFG%", "Opp TOV%", "DREB%", "Opp FT Rate", "Power Score"]
DEFENSE_COLS      = ["Rank", "Team", "Class", "Gender", "GP",
                     "DRtg", "Opp eFG%", "Opp TS%", "Opp TOV%", "Opp FT Rate",
                     "DREB%", "BLK Rate", "STL Rate", "Power Score"]


QUARTER_COLS = ["Rank", "Team", "Class", "GP",
                "Q1 Pts/G", "Q1 PA/G", "Q1 Diff",
                "Q2 Pts/G", "Q2 PA/G", "Q2 Diff",
                "H1 Pts/G", "H1 PA/G", "H1 Diff",
                "Q3 Pts/G", "Q3 PA/G", "Q3 Diff",
                "Q4 Pts/G", "Q4 PA/G", "Q4 Diff",
                "H2 Pts/G", "H2 PA/G", "H2 Diff"]
_GOOD_LOW.update({"Q1 PA/G","Q2 PA/G","Q3 PA/G","Q4 PA/G",
                  "H1 PA/G","H2 PA/G"})
_GRADIENT_COLS.update({"Q1 Pts/G","Q1 PA/G","Q1 Diff",
                        "Q2 Pts/G","Q2 PA/G","Q2 Diff",
                        "Q3 Pts/G","Q3 PA/G","Q3 Diff",
                        "Q4 Pts/G","Q4 PA/G","Q4 Diff",
                        "H1 Pts/G","H1 PA/G","H1 Diff",
                        "H2 Pts/G","H2 PA/G","H2 Diff"})


# ══════════════════════════════════════════════════════════════════════════════
#  TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_ov, tab_tracks, tab_tr_rk, tab_mu = st.tabs([
    "🏠 Overview",
    "🔬 Tracks",
    "🏆 Tracked Rankings",
    "⚔️ Matchup",
])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — OVERVIEW  (box-score quick rankings + charts)
# ══════════════════════════════════════════════════════════════════════════════

with tab_ov:
    fdf_all = _f(df_all)
    fdf_tr  = _f(df_tr)

    # ── League Pulse ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">League Pulse</div>', unsafe_allow_html=True)
    m1, m2, m3, m4, m5 = st.columns(5)
    total_teams = len(fdf_all) if not fdf_all.empty else 0
    total_games = int(fdf_all["GP"].sum() // 2) if not fdf_all.empty else 0
    avg_ppg     = f"{fdf_all['PPG'].mean():.1f}" if not fdf_all.empty else "—"
    avg_pa      = f"{fdf_all['PA/G'].mean():.1f}" if not fdf_all.empty else "—"
    avg_diff    = (f"{fdf_all['Diff'].mean():+.1f}"
                  if not fdf_all.empty else "—")

    m1.metric("Teams",        total_teams)
    m2.metric("Total Games",  total_games)
    m3.metric("Avg Scoring",  avg_ppg + " PPG")
    m4.metric("Avg Allowed",  avg_pa + " PA/G")
    m5.metric("Avg Margin",   avg_diff)

    st.divider()

    # ── Recent Results ────────────────────────────────────────────────────────
    recent_games = query("""
        SELECT g.id, g.date, g.home_score, g.away_score, g.tracked,
               t1.name AS t1, t2.name AS t2
        FROM games g
        JOIN teams t1 ON t1.id=g.team1_id
        JOIN teams t2 ON t2.id=g.team2_id
        WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL
        ORDER BY g.date DESC, g.id DESC
        LIMIT 8
    """)
    if recent_games:
        st.markdown('<div class="section-hdr">Recent Results</div>', unsafe_allow_html=True)
        cols_rc = st.columns(min(4, len(recent_games)))
        for i, g in enumerate(recent_games):
            t1_win  = g["home_score"] > g["away_score"]
            s1_cls  = "score-winner" if t1_win else "score-loser"
            s2_cls  = "score-winner" if not t1_win else "score-loser"
            tracked_lbl = "FINAL"
            try:
                d = datetime.strptime(g["date"], "%Y-%m-%d").strftime("%b %d")
            except Exception:
                d = g["date"] or "—"
            cols_rc[i % 4].markdown(f"""
            <div class="score-card">
              <div class="score-card-date">{d}</div>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                  <div class="score-card-team">{g['t1']}</div>
                  <div class="score-card-team">{g['t2']}</div>
                </div>
                <div style="text-align:right">
                  <div class="score-card-pts {s1_cls}">{g['home_score']}</div>
                  <div class="score-card-pts {s2_cls}">{g['away_score']}</div>
                </div>
              </div>
              <div class="score-final">{tracked_lbl}</div>
            </div>""", unsafe_allow_html=True)

    st.divider()

    # ── Power Rankings + Efficiency scatter ───────────────────────────────────
    left_col, right_col = st.columns([1, 2])

    with left_col:
        st.markdown('<div class="section-hdr">Power Rankings</div>', unsafe_allow_html=True)
        if not fdf_all.empty:
            top_n = fdf_all.sort_values("Power Score", ascending=False).head(10)
            for i, (_, row) in enumerate(top_n.iterrows()):
                rk        = i + 1
                badge_cls = {1: "rank-1", 2: "rank-2", 3: "rank-3"}.get(rk, "rank-n")
                rec       = f"{int(row['W'])}-{int(row['L'])}"
                ps        = f"{row['Power Score']:.1f}"
                sor_v     = f"{row.get('SOR', 0):.1f}"
                sos_v     = f"{row.get('SOS', 0):.1f}"
                streak_txt = row.get("Streak", "")
                team_name  = row["Team"]
                is_tracked = not fdf_tr.empty and team_name in fdf_tr["Team"].values
                tr_badge   = "<span class='tracked-badge'>TRACKED</span>" if is_tracked else ""
                st.markdown(f"""
                <div class="rank-card">
                  <div class="rank-badge {badge_cls}">{rk}</div>
                  <div style="flex:1;min-width:0">
                    <div class="rank-team">{team_name}{tr_badge}</div>
                    <div class="rank-rec">{row['Class']} · {rec}
                      {"· <b style='color:#2ecc71'>" + str(streak_txt) + "</b>"
                       if str(streak_txt).startswith("W") else
                       "· <b style='color:#e74c3c'>" + str(streak_txt) + "</b>"
                       if str(streak_txt).startswith("L") else ""}
                    </div>
                    <div class="rank-vs">SOR {sor_v} &nbsp;|&nbsp; SOS {sos_v}</div>
                  </div>
                  <div class="rank-ps">{ps}</div>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No ranking data yet.")

    with right_col:
        st.markdown('<div class="section-hdr">Power Scores</div>', unsafe_allow_html=True)
        show_power_chart(fdf_all, "Power Rankings", n=15, key="power_ov")

    st.divider()

    # ── Stat Leader Cards ─────────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">Team Leaders</div>', unsafe_allow_html=True)

    def _team_leader_card(df, stat, label, hib=True, fmt=".1f"):
        if df.empty or stat not in df.columns:
            return ""
        row = df.loc[df[stat].idxmax() if hib else df[stat].idxmin()]
        val = row[stat]
        rec = f"{int(row['W'])}-{int(row['L'])}" if "W" in row and "L" in row else ""
        return f"""
        <div class="dash-card">
          <div class="dash-card-title">{label}</div>
          <div class="dash-card-value">{val:{fmt}}</div>
          <div class="dash-card-sub">{row['Team']}</div>
          <div class="dash-card-meta">{row['Class']} · {rec}</div>
        </div>"""

    tl_cols = st.columns(5)
    cards = [
        (fdf_all, "PPG",   "Points Per Game",    True,  ".1f"),
        (fdf_all, "PA/G",  "Best Defense",       False, ".1f"),
        (fdf_all, "Diff",  "Point Differential", True,  "+.1f"),
        (fdf_all, "SOR",   "Strength of Record", True,  ".1f"),
        (fdf_all, "SOS",   "Strength of Schedule", True, ".1f"),
    ]
    for c, (df_c, stat, lbl, hib, fmt_) in zip(tl_cols, cards):
        c.markdown(_team_leader_card(df_c, stat, lbl, hib, fmt_), unsafe_allow_html=True)

    st.divider()

    # ── Quick Rankings Table ──────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">Quick Rankings</div>', unsafe_allow_html=True)
    st.caption("Power Score = 35% SOR · 30% W% · 20% Margin · 15% SOS · "
               "vs T5/T10/T20 = record vs top-5/10/20 teams")

    if not fdf_all.empty:
        _qr_df = fdf_all.sort_values("Power Score", ascending=False).reset_index(drop=True).copy()
        _qr_cols = [c for c in ["Team", "Class", "GP", "W", "L", "W%",
                                 "PPG", "PA/G", "Diff", "SOR", "SOS", "Power Score"]
                    if c in _qr_df.columns]
        _qr_tbl = _qr_df[_qr_cols].copy()
        _qr_tbl.insert(0, "Rank", range(1, len(_qr_tbl) + 1))
        _qr_tbl["vs T5"]  = [_vs_str(t, 5)  for t in _qr_df["Team"]]
        _qr_tbl["vs T10"] = [_vs_str(t, 10) for t in _qr_df["Team"]]
        _qr_tbl["vs T20"] = [_vs_str(t, 20) for t in _qr_df["Team"]]
        _qr_tbl = apply_filters(_qr_tbl)
        styler = _qr_tbl.style.set_properties(**{"font-size": "13px"})
        for _c in ["W%", "PPG", "PA/G", "Diff", "SOR", "SOS", "Power Score"]:
            if _c in _qr_tbl.columns:
                try:
                    styler = styler.background_gradient(
                        subset=[_c],
                        cmap="RdYlGn_r" if _c in _GOOD_LOW else "RdYlGn", axis=0)
                except Exception:
                    pass
        st.dataframe(styler, use_container_width=True, hide_index=True)

    st.divider()

    # ── Hot & Cold ────────────────────────────────────────────────────────────
    if not fdf_all.empty and "Streak" in fdf_all.columns:
        st.markdown('<div class="section-hdr">Hot & Cold</div>', unsafe_allow_html=True)
        hc1, hc2 = st.columns(2)
        hot_df = fdf_all[fdf_all["Streak"].str.startswith("W", na=False)].copy()
        hot_df["StreakN"] = hot_df["Streak"].str[1:].apply(
            lambda x: int(x) if str(x).isdigit() else 0)
        hot_df = hot_df.nlargest(5, "StreakN")
        with hc1:
            st.markdown("🔥 **Win Streaks**")
            for _, row in hot_df.iterrows():
                st.markdown(
                    f"**{row['Team']}** `{row['Class']}`  "
                    f"<span style='color:#2ecc71;font-weight:700'>{row['Streak']}</span>  "
                    f"({int(row['W'])}-{int(row['L'])})", unsafe_allow_html=True)
        cold_df = fdf_all[fdf_all["Streak"].str.startswith("L", na=False)].copy()
        cold_df["StreakN"] = cold_df["Streak"].str[1:].apply(
            lambda x: int(x) if str(x).isdigit() else 0)
        cold_df = cold_df.nlargest(5, "StreakN")
        with hc2:
            st.markdown("🧊 **Losing Streaks**")
            for _, row in cold_df.iterrows():
                st.markdown(
                    f"**{row['Team']}** `{row['Class']}`  "
                    f"<span style='color:#e74c3c;font-weight:700'>{row['Streak']}</span>  "
                    f"({int(row['W'])}-{int(row['L'])})", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — TRACKS  (deep dive on tracked stats)
# ══════════════════════════════════════════════════════════════════════════════

with tab_tracks:
    if df_tr.empty:
        st.info("No tracked games yet. Enter play-by-play data in the Game Tracker to unlock this section.")
    else:
        sub_eff, sub_shoot, sub_qtr, sub_poss, sub_def, sub_deep = st.tabs([
            "⚡ Efficiency",
            "🎯 Shooting",
            "⏱ Quarters",
            "🔄 Possession",
            "🛡 Defense",
            "🔍 Team Deep Dive",
        ])

        # ══ Efficiency ════════════════════════════════════════════════════════
        with sub_eff:
            fdf_eff = _f(df_tr)
            if not fdf_eff.empty:
                # KPI row
                if "Net Rtg" in fdf_eff.columns:
                    best_n  = fdf_eff.loc[fdf_eff["Net Rtg"].idxmax()]
                    best_o  = fdf_eff.loc[fdf_eff["ORtg"].idxmax()]
                    best_d  = fdf_eff.loc[fdf_eff["DRtg"].idxmin()]
                    best_ts = fdf_eff.loc[fdf_eff["TS%"].idxmax()]
                    e1, e2, e3, e4 = st.columns(4)
                    e1.metric("Best Net Rtg",  best_n["Team"], f"{best_n['Net Rtg']:+.1f}")
                    e2.metric("Best ORtg",     best_o["Team"], f"{best_o['ORtg']:.1f}")
                    e3.metric("Best DRtg",     best_d["Team"], f"{best_d['DRtg']:.1f}")
                    e4.metric("Best TS%",      best_ts["Team"], f"{best_ts['TS%']:.1f}%")
                    st.divider()

                # ORtg vs DRtg scatter (KenPom-style)
                show_efficiency_scatter(fdf_eff, title="ORtg vs DRtg — KenPom Quadrant",
                                        key="eff_scatter_tr")
                st.divider()

                # Net Rating bar + leaders side-by-side
                nc2, ld3 = st.columns([3, 2])
                with nc2:
                    show_net_rtg_chart(df_tr, key="net_rtg_tr")
                with ld3:
                    st.markdown("#### Efficiency Leaders")
                    show_stat_leaders(df_tr, [
                        ("Net Rtg", "Net Rating",  True),
                        ("ORtg",    "Best ORtg",   True),
                        ("DRtg",    "Best DRtg",   False),
                        ("TS%",     "True Shoot%", True),
                        ("AST/TOV", "AST/TOV",     True),
                    ])
                st.divider()

                # TS% vs eFG% scatter — two efficiency metrics
                if "TS%" in fdf_eff.columns and "eFG%" in fdf_eff.columns:
                    st.markdown("#### TS% vs eFG% — Shooting Efficiency Map")
                    _avg_ts  = fdf_eff["TS%"].mean()
                    _avg_efg = fdf_eff["eFG%"].mean()
                    fig_te = go.Figure()
                    fig_te.add_hline(y=_avg_ts, line_dash="dot",
                                     line_color="rgba(200,200,200,0.2)", line_width=1)
                    fig_te.add_vline(x=_avg_efg, line_dash="dot",
                                     line_color="rgba(200,200,200,0.2)", line_width=1)
                    net_vals = fdf_eff["Net Rtg"].values if "Net Rtg" in fdf_eff.columns else \
                               np.zeros(len(fdf_eff))
                    n_lo, n_hi = net_vals.min(), net_vals.max()
                    for _, row in fdf_eff.iterrows():
                        nv   = row.get("Net Rtg", 0)
                        norm = (nv - n_lo) / (n_hi - n_lo + 1e-9)
                        col  = f"rgb({int(220*(1-norm))},{int(200*norm)},60)"
                        fig_te.add_trace(go.Scatter(
                            x=[row["eFG%"]], y=[row["TS%"]],
                            mode="markers+text",
                            text=[row["Team"]],
                            textposition="top center",
                            textfont=dict(size=9, color="rgba(220,220,220,0.85)"),
                            marker=dict(size=11, color=col,
                                        line=dict(color="rgba(255,255,255,0.5)", width=1)),
                            showlegend=False,
                            hovertemplate=(f"<b>{row['Team']}</b><br>eFG%: {row['eFG%']:.1f}"
                                           f"<br>TS%: {row['TS%']:.1f}<br>"
                                           f"Net Rtg: {nv:+.1f}<extra></extra>"),
                        ))
                    fig_te.update_layout(
                        xaxis=dict(title="eFG%", gridcolor="rgba(255,255,255,0.05)"),
                        yaxis=dict(title="TS%", gridcolor="rgba(255,255,255,0.05)"),
                        height=420, plot_bgcolor="rgba(14,17,23,1)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=40, r=20, t=30, b=40), font=dict(size=11),
                        annotations=[dict(text="League avg", x=_avg_efg, y=fdf_eff["TS%"].min(),
                                         showarrow=False, font=dict(size=9, color="rgba(180,180,180,0.4)"),
                                         xanchor="left")]
                    )
                    st.plotly_chart(fig_te, use_container_width=True)
                    st.caption("Color: green = positive net rating · Crosshairs = league averages")
                    st.divider()

                # Efficiency table + radar
                st.subheader("Efficiency Table")
                show_table(df_tr, EFF_COLS, "Net Rtg")
                st.subheader("By Class")
                show_class_breakdown(df_tr, EFF_COLS)
                with st.expander("Team Comparison Radar"):
                    show_team_radar(df_tr, [
                        ("ORtg",    "Off Rtg",  True),
                        ("DRtg",    "Def Rtg",  False),
                        ("TS%",     "TS%",      True),
                        ("OREB%",   "OREB%",    True),
                        ("TOV%",    "TOV%",     False),
                        ("AST/TOV", "AST/TOV",  True),
                    ], key="radar_eff_tr")

        # ══ Shooting ══════════════════════════════════════════════════════════
        with sub_shoot:
            fdf_sh = _f(df_tr)
            if not fdf_sh.empty:
                # KPI row
                sh1, sh2, sh3, sh4, sh5 = st.columns(5)
                def _best(df, col, hib=True):
                    if col not in df.columns: return "—", "—"
                    row = df.loc[df[col].idxmax() if hib else df[col].idxmin()]
                    return row["Team"], f"{row[col]:.1f}"
                for _mc, _stat, _lbl, _hib in [
                    (sh1, "eFG%",      "Best eFG%",      True),
                    (sh2, "TS%",       "Best TS%",       True),
                    (sh3, "3P%",       "Best 3PT%",      True),
                    (sh4, "Paint FG%", "Best Paint FG%", True),
                    (sh5, "Ast%",      "Most Off-Pass",  True),
                ]:
                    _t, _v = _best(fdf_sh, _stat, _hib)
                    _mc.metric(_lbl, _t, _v + "%" if _v != "—" else "—")
                st.divider()

                # Scoring distribution stacked bar
                st.markdown("#### Scoring Source Distribution — % of Points by Type")
                if all(c in fdf_sh.columns for c in ["Pts from 2%", "Pts from 3%", "Pts from FT%"]):
                    sdf_sd = fdf_sh.sort_values("Power Score", ascending=False)
                    fig_sd = go.Figure()
                    for col, color, lbl in [
                        ("Pts from 2%",  "#2166ac", "2PT %"),
                        ("Pts from 3%",  "#1a9850", "3PT %"),
                        ("Pts from FT%", "#d73027", "FT %"),
                    ]:
                        fig_sd.add_trace(go.Bar(
                            name=lbl, x=sdf_sd["Team"], y=sdf_sd[col],
                            marker_color=color,
                            hovertemplate="%{x}<br>" + lbl + ": %{y:.1f}%<extra></extra>"))
                    fig_sd.update_layout(
                        barmode="stack", yaxis_title="% of Points", height=360,
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=20, r=20, t=30, b=80),
                        legend=dict(orientation="h", y=1.05),
                        xaxis=dict(tickangle=-40), font=dict(size=11))
                    st.plotly_chart(fig_sd, use_container_width=True)

                st.divider()
                lc, rc = st.columns(2)

                # eFG% leaderboard
                with lc:
                    st.markdown("#### Shooting Efficiency Leaderboard")
                    show_stat_leaders(df_tr, [
                        ("eFG%",       "eFG%",        True),
                        ("TS%",        "TS%",         True),
                        ("FG%",        "FG%",         True),
                        ("3P%",        "3PT%",        True),
                        ("Paint FG%",  "Paint FG%",   True),
                    ])

                # Assisted (off-pass) vs unassisted breakdown
                with rc:
                    st.markdown("#### Shots Off Pass vs Self-Created")
                    if "Ast%" in fdf_sh.columns:
                        _sdf_ast = fdf_sh.sort_values("Ast%", ascending=False)
                        fig_ast = go.Figure()
                        fig_ast.add_trace(go.Bar(
                            name="Off Pass (Ast%)", x=_sdf_ast["Team"],
                            y=_sdf_ast["Ast%"], marker_color="#1a9850",
                            hovertemplate="%{x}<br>Assisted: %{y:.1f}%<extra></extra>"))
                        fig_ast.add_trace(go.Bar(
                            name="Self-Created (Unast%)", x=_sdf_ast["Team"],
                            y=_sdf_ast["Unast%"], marker_color="#d73027",
                            hovertemplate="%{x}<br>Unassisted: %{y:.1f}%<extra></extra>"))
                        fig_ast.update_layout(
                            barmode="stack", yaxis_title="% of FGM", height=320,
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=20, r=20, t=30, b=80),
                            legend=dict(orientation="h", y=1.05),
                            xaxis=dict(tickangle=-40), font=dict(size=11))
                        st.plotly_chart(fig_ast, use_container_width=True)
                        st.caption("High Ast% = team scores mostly off passes · Low Ast% = high isolation/self-creation")

                st.divider()

                # FG% breakdown chart: FG / 2P / 3P / FT side-by-side bars
                st.markdown("#### FG% Breakdown by Shot Type")
                if all(c in fdf_sh.columns for c in ["FG%", "2P%", "3P%", "FT%"]):
                    _sdf_fg = fdf_sh.sort_values("eFG%", ascending=False)
                    fig_fg = go.Figure()
                    for col, color, lbl in [
                        ("FG%",  "#f0a500", "FG%"),
                        ("2P%",  "#2166ac", "2P%"),
                        ("3P%",  "#1a9850", "3P%"),
                        ("FT%",  "#9b59b6", "FT%"),
                    ]:
                        fig_fg.add_trace(go.Bar(
                            name=lbl, x=_sdf_fg["Team"], y=_sdf_fg[col],
                            marker_color=color, opacity=0.85,
                            hovertemplate="%{x}<br>" + lbl + ": %{y:.1f}%<extra></extra>"))
                    fig_fg.update_layout(
                        barmode="group", yaxis_title="FG%", height=380,
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=20, r=20, t=30, b=80),
                        legend=dict(orientation="h", y=1.05),
                        xaxis=dict(tickangle=-40), font=dict(size=11))
                    st.plotly_chart(fig_fg, use_container_width=True)

                st.divider()

                # Paint pts/g vs 3PT pts/g scatter
                if "Paint Pts/G" in fdf_sh.columns and "Pts from 3%" in fdf_sh.columns:
                    st.markdown("#### Inside vs Outside: Paint Pts vs 3PT Scoring")
                    _pct3_pts = fdf_sh["PPG"] * fdf_sh["Pts from 3%"] / 100
                    fig_io = go.Figure()
                    for _, row in fdf_sh.iterrows():
                        _3pts = row["PPG"] * row["Pts from 3%"] / 100
                        fig_io.add_trace(go.Scatter(
                            x=[row["Paint Pts/G"]], y=[_3pts],
                            mode="markers+text",
                            text=[row["Team"]],
                            textposition="top center",
                            textfont=dict(size=9, color="rgba(220,220,220,0.85)"),
                            marker=dict(size=10, color="#f0a500",
                                        line=dict(color="rgba(255,255,255,0.4)", width=1)),
                            showlegend=False,
                            hovertemplate=(f"<b>{row['Team']}</b><br>"
                                           f"Paint Pts/G: {row['Paint Pts/G']:.1f}<br>"
                                           f"3PT Pts/G: {_3pts:.1f}<extra></extra>"),
                        ))
                    fig_io.update_layout(
                        xaxis=dict(title="Paint Pts/G", gridcolor="rgba(255,255,255,0.05)"),
                        yaxis=dict(title="3PT Pts/G", gridcolor="rgba(255,255,255,0.05)"),
                        height=400, plot_bgcolor="rgba(14,17,23,1)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=40, r=20, t=30, b=40), font=dict(size=11),
                    )
                    st.plotly_chart(fig_io, use_container_width=True)
                    st.caption("Top-right = high paint AND perimeter scoring · Bottom-left = struggle to score in both zones")
                    st.divider()

                st.subheader("Shooting Table")
                show_table(df_tr, SHOOT_COLS, "TS%")
                with st.expander("Team Comparison Radar"):
                    show_team_radar(df_tr, [
                        ("TS%",  "TS%",  True), ("eFG%", "eFG%", True),
                        ("FG%",  "FG%",  True), ("2P%",  "2P%",  True),
                        ("3P%",  "3P%",  True), ("FT%",  "FT%",  True),
                    ], key="radar_shoot_tr")

        # ══ Quarters ══════════════════════════════════════════════════════════
        with sub_qtr:
            fdf_qtr = _f(df_tr)
            if not fdf_qtr.empty:
                # Q1/Q2/Q3/Q4 leaders row
                _q_cols = [
                    ("Q1 Diff", "Q1 Net", True),
                    ("Q2 Diff", "Q2 Net", True),
                    ("Q3 Diff", "Q3 Net", True),
                    ("Q4 Diff", "Q4 Net (Clutch)", True),
                ]
                q_avail = [x for x in _q_cols if x[0] in fdf_qtr.columns]
                if q_avail:
                    q_metric_cols = st.columns(len(q_avail))
                    for _mc, (_stat, _lbl, _hib) in zip(q_metric_cols, q_avail):
                        if _stat in fdf_qtr.columns:
                            _brow = fdf_qtr.loc[fdf_qtr[_stat].idxmax() if _hib else fdf_qtr[_stat].idxmin()]
                            _mc.metric(_lbl + " Leader", _brow["Team"],
                                       f"{_brow[_stat]:+.1f}")
                    st.divider()

                # Quarter scoring bars — who is best in each quarter?
                if all(c in fdf_qtr.columns for c in ["Q1 Pts/G","Q2 Pts/G","Q3 Pts/G","Q4 Pts/G"]):
                    st.markdown("#### Quarter-by-Quarter Scoring — Pts/G Per Team")
                    _qs_df = fdf_qtr.sort_values("PPG", ascending=False)
                    fig_qs = go.Figure()
                    _qcolors = {"Q1":"#3498db","Q2":"#1a9850","Q3":"#f0a500","Q4":"#e74c3c"}
                    for q_col, q_color in [
                        ("Q1 Pts/G","#3498db"),("Q2 Pts/G","#1a9850"),
                        ("Q3 Pts/G","#f0a500"),("Q4 Pts/G","#e74c3c"),
                    ]:
                        fig_qs.add_trace(go.Bar(
                            name=q_col.replace(" Pts/G",""),
                            x=_qs_df["Team"], y=_qs_df[q_col],
                            marker_color=q_color, opacity=0.88,
                            hovertemplate="%{x}<br>" + q_col + ": %{y:.1f}<extra></extra>"))
                    fig_qs.update_layout(
                        barmode="group", yaxis_title="Pts/G", height=400,
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=20, r=20, t=30, b=80),
                        legend=dict(orientation="h", y=1.05),
                        xaxis=dict(tickangle=-40), font=dict(size=11))
                    st.plotly_chart(fig_qs, use_container_width=True)
                    st.divider()

                # Quarter net differential heatmap-style bars
                if all(c in fdf_qtr.columns for c in ["Q1 Diff","Q2 Diff","Q3 Diff","Q4 Diff"]):
                    st.markdown("#### Quarter Net Differential — Who Wins Each Quarter?")
                    _qd_df = fdf_qtr[["Team","Q1 Diff","Q2 Diff","Q3 Diff","Q4 Diff"]].copy()
                    _qd_df = _qd_df.sort_values("Q1 Diff", ascending=False)

                    qd_c1, qd_c2 = st.columns(2)
                    for qcol, qname, _col_w in [
                        ("Q1 Diff","Q1",qd_c1), ("Q2 Diff","Q2",qd_c2),
                    ]:
                        _sdf = _qd_df.sort_values(qcol, ascending=True)
                        _colors = ["#1a9850" if v >= 0 else "#d73027" for v in _sdf[qcol]]
                        _fig = go.Figure(go.Bar(
                            x=_sdf[qcol], y=_sdf["Team"], orientation="h",
                            marker_color=_colors,
                            text=_sdf[qcol].apply(lambda v: f"{v:+.1f}"),
                            textposition="outside",
                            hovertemplate=f"%{{y}}<br>{qname} Diff: %{{x:+.1f}}<extra></extra>"))
                        _fig.add_vline(x=0, line_color="rgba(180,180,180,0.6)", line_width=1.5)
                        _fig.update_layout(
                            title=f"{qname} Net Diff",
                            height=max(300, len(_sdf)*26+80),
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=10, r=60, t=40, b=20), font=dict(size=10))
                        _col_w.plotly_chart(_fig, use_container_width=True)

                    qd_c3, qd_c4 = st.columns(2)
                    for qcol, qname, _col_w in [
                        ("Q3 Diff","Q3",qd_c3), ("Q4 Diff","Q4 (Clutch)",qd_c4),
                    ]:
                        _sdf = _qd_df.sort_values(qcol, ascending=True)
                        _colors = ["#1a9850" if v >= 0 else "#d73027" for v in _sdf[qcol]]
                        _fig = go.Figure(go.Bar(
                            x=_sdf[qcol], y=_sdf["Team"], orientation="h",
                            marker_color=_colors,
                            text=_sdf[qcol].apply(lambda v: f"{v:+.1f}"),
                            textposition="outside",
                            hovertemplate=f"%{{y}}<br>{qname} Diff: %{{x:+.1f}}<extra></extra>"))
                        _fig.add_vline(x=0, line_color="rgba(180,180,180,0.6)", line_width=1.5)
                        _fig.update_layout(
                            title=f"{qname} Net Diff",
                            height=max(300, len(_sdf)*26+80),
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=10, r=60, t=40, b=20), font=dict(size=10))
                        _col_w.plotly_chart(_fig, use_container_width=True)

                    st.divider()

                # Q4 Clutch stats row
                st.markdown("#### Clutch Quarter Leaders")
                show_stat_leaders(df_tr, [
                    ("Q4 Diff",  "Q4 Net Diff",  True),
                    ("Q4 Pts/G", "Q4 Scoring",   True),
                    ("Q4 PA/G",  "Q4 Defense",   False),
                    ("BLK Rate", "BLK Rate",     True),
                    ("STL Rate", "STL Rate",     True),
                ])
                st.divider()

                # Half-time comparison bars
                if all(c in fdf_qtr.columns for c in ["H1 Diff","H2 Diff"]):
                    st.markdown("#### First Half vs Second Half — Who Finishes Strong?")
                    _hc1, _hc2 = st.columns(2)
                    for hcol, hname, _hcw in [("H1 Diff","1st Half",_hc1),("H2 Diff","2nd Half",_hc2)]:
                        _hsdf = fdf_qtr[["Team",hcol]].sort_values(hcol, ascending=True)
                        _hcolors = ["#1a9850" if v >= 0 else "#d73027" for v in _hsdf[hcol]]
                        _hfig = go.Figure(go.Bar(
                            x=_hsdf[hcol], y=_hsdf["Team"], orientation="h",
                            marker_color=_hcolors,
                            text=_hsdf[hcol].apply(lambda v: f"{v:+.1f}"),
                            textposition="outside",
                            hovertemplate=f"%{{y}}<br>{hname} Diff: %{{x:+.1f}}<extra></extra>"))
                        _hfig.add_vline(x=0, line_color="rgba(180,180,180,0.6)", line_width=1.5)
                        _hfig.update_layout(
                            title=f"{hname} Net Diff",
                            height=max(300, len(_hsdf)*26+80),
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=10, r=60, t=40, b=20), font=dict(size=10))
                        _hcw.plotly_chart(_hfig, use_container_width=True)

                    if all(c in fdf_qtr.columns for c in ["H1 Pts/G","H2 Pts/G","H1 PA/G","H2 PA/G"]):
                        st.markdown("#### First Half vs Second Half Scoring")
                        _hscore_df = fdf_qtr.sort_values("H1 Pts/G", ascending=False)
                        fig_halves = go.Figure()
                        for _hstat, _hcolor, _hname in [
                            ("H1 Pts/G","#3498db","H1 Scored"),
                            ("H2 Pts/G","#f0a500","H2 Scored"),
                            ("H1 PA/G","#e74c3c","H1 Allowed"),
                            ("H2 PA/G","#9b59b6","H2 Allowed"),
                        ]:
                            fig_halves.add_trace(go.Bar(
                                name=_hname, x=_hscore_df["Team"],
                                y=_hscore_df[_hstat],
                                marker_color=_hcolor, opacity=0.85,
                                hovertemplate="%{x}<br>" + _hstat + ": %{y:.1f}<extra></extra>"))
                        fig_halves.update_layout(
                            barmode="group", yaxis_title="Pts/G", height=380,
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=20, r=20, t=30, b=80),
                            legend=dict(orientation="h", y=1.05),
                            xaxis=dict(tickangle=-40), font=dict(size=11))
                        st.plotly_chart(fig_halves, use_container_width=True)
                    st.divider()

                # Quarter table
                st.subheader("Quarter Breakdown Table")
                show_table(df_tr, QUARTER_COLS, "Q4 Diff")
                st.subheader("By Class")
                show_class_breakdown(df_tr, QUARTER_COLS)

        # ══ Possession ════════════════════════════════════════════════════════
        with sub_poss:
            fdf_poss = _f(df_tr)
            if not fdf_poss.empty:
                # KPI
                show_stat_leaders(df_tr, [
                    ("PPP",      "Pts/Poss",     True),
                    ("Opp PPP",  "Opp Pts/Poss", False),
                    ("Poss/G",   "Poss/G",       True),
                    ("TOV/Poss", "TOV/Poss",     False),
                    ("AST/Poss", "AST/Poss",     True),
                ])
                st.divider()

                # PPP vs Opp PPP scatter
                if "PPP" in fdf_poss.columns and "Opp PPP" in fdf_poss.columns:
                    st.markdown("#### PPP vs Opp PPP — Offensive vs Defensive Efficiency")
                    avg_ppp = fdf_poss["PPP"].mean()
                    avg_op  = fdf_poss["Opp PPP"].mean()
                    fig_ppp = go.Figure()
                    fig_ppp.add_hline(y=avg_op,  line_dash="dot",
                                      line_color="rgba(200,200,200,0.2)", line_width=1)
                    fig_ppp.add_vline(x=avg_ppp, line_dash="dot",
                                      line_color="rgba(200,200,200,0.2)", line_width=1)
                    for _, row in fdf_poss.iterrows():
                        is_elite = row["PPP"] > avg_ppp and row["Opp PPP"] < avg_op
                        col = "#1a9850" if is_elite else "#3498db"
                        fig_ppp.add_trace(go.Scatter(
                            x=[row["PPP"]], y=[row["Opp PPP"]],
                            mode="markers+text",
                            text=[row["Team"]],
                            textposition="top center",
                            textfont=dict(size=9, color="rgba(220,220,220,0.85)"),
                            marker=dict(size=11, color=col,
                                        line=dict(color="rgba(255,255,255,0.4)", width=1)),
                            showlegend=False,
                            hovertemplate=(f"<b>{row['Team']}</b><br>"
                                           f"PPP: {row['PPP']:.3f}<br>"
                                           f"Opp PPP: {row['Opp PPP']:.3f}<extra></extra>"),
                        ))
                    fig_ppp.update_layout(
                        xaxis=dict(title="PPP (offense →)", gridcolor="rgba(255,255,255,0.05)"),
                        yaxis=dict(title="Opp PPP (lower = better D)",
                                   autorange="reversed",
                                   gridcolor="rgba(255,255,255,0.05)"),
                        height=450, plot_bgcolor="rgba(14,17,23,1)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=50, r=20, t=30, b=40), font=dict(size=11),
                    )
                    st.plotly_chart(fig_ppp, use_container_width=True)
                    st.caption("Top-right = elite (high PPP + low Opp PPP) · Axes reversed so top-right = best")
                    st.divider()

                # OREB% vs DREB% + Pace side-by-side
                rb_c, pace_c = st.columns(2)
                with rb_c:
                    if "OREB%" in fdf_poss.columns and "DREB%" in fdf_poss.columns:
                        st.markdown("#### Rebounding Battle")
                        _sdf_rb = fdf_poss.sort_values("OREB%", ascending=False)
                        fig_rb = go.Figure()
                        fig_rb.add_trace(go.Bar(
                            name="OREB%", x=_sdf_rb["Team"], y=_sdf_rb["OREB%"],
                            marker_color="#f0a500",
                            hovertemplate="%{x}<br>OREB%: %{y:.1f}%<extra></extra>"))
                        fig_rb.add_trace(go.Bar(
                            name="DREB%", x=_sdf_rb["Team"], y=_sdf_rb["DREB%"],
                            marker_color="#3498db",
                            hovertemplate="%{x}<br>DREB%: %{y:.1f}%<extra></extra>"))
                        fig_rb.update_layout(
                            barmode="group", yaxis_title="%", height=340,
                            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=20, r=20, t=30, b=80),
                            legend=dict(orientation="h", y=1.05),
                            xaxis=dict(tickangle=-40), font=dict(size=11))
                        st.plotly_chart(fig_rb, use_container_width=True)

                with pace_c:
                    if "Pace" in fdf_poss.columns:
                        st.markdown("#### Pace (Possessions Per Game)")
                        _sdf_pa = fdf_poss.sort_values("Pace", ascending=False)
                        fig_pa = go.Figure(go.Bar(
                            x=_sdf_pa["Pace"], y=_sdf_pa["Team"], orientation="h",
                            marker_color=[
                                f"rgba(52,152,219,{0.5 + 0.5*i/(max(len(_sdf_pa)-1,1))})"
                                for i in range(len(_sdf_pa))
                            ],
                            text=_sdf_pa["Pace"].apply(lambda v: f"{v:.1f}"),
                            textposition="outside",
                            hovertemplate="%{y}<br>Pace: %{x:.1f}<extra></extra>"))
                        fig_pa.update_layout(
                            height=340, plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                            margin=dict(l=10, r=60, t=30, b=20), font=dict(size=10))
                        st.plotly_chart(fig_pa, use_container_width=True)

                # Pace vs ORtg scatter — style/efficiency quadrant
                if "Pace" in fdf_poss.columns and "ORtg" in fdf_poss.columns:
                    st.markdown("#### Pace vs Offensive Rating — Style & Efficiency Quadrant")
                    show_pace_scatter(fdf_poss, key="pace_scatter_poss")
                st.divider()

                # TOV/Poss bar
                if "TOV/Poss" in fdf_poss.columns:
                    st.markdown("#### Turnovers Per Possession — Ball Security")
                    _sdf_tov = fdf_poss.sort_values("TOV/Poss", ascending=True)
                    fig_tov = go.Figure(go.Bar(
                        x=_sdf_tov["TOV/Poss"], y=_sdf_tov["Team"], orientation="h",
                        marker_color=["#1a9850" if v < _sdf_tov["TOV/Poss"].median()
                                      else "#d73027" for v in _sdf_tov["TOV/Poss"]],
                        text=_sdf_tov["TOV/Poss"].apply(lambda v: f"{v:.3f}"),
                        textposition="outside",
                        hovertemplate="%{y}<br>TOV/Poss: %{x:.3f}<extra></extra>"))
                    fig_tov.update_layout(
                        height=max(300, len(_sdf_tov)*26+80),
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=10, r=80, t=20, b=20), font=dict(size=10),
                        xaxis=dict(gridcolor="rgba(128,128,128,0.12)"))
                    st.plotly_chart(fig_tov, use_container_width=True)
                    st.caption("Lower = better ball security · Green = better than median")
                    st.divider()

                st.subheader("Possession Table")
                show_table(df_tr, POSS_COLS, "PPP")
                st.subheader("By Class")
                show_class_breakdown(df_tr, POSS_COLS)

        # ══ Defense ═══════════════════════════════════════════════════════════
        with sub_def:
            fdf_def = _f(df_tr)
            if not fdf_def.empty:
                # KPI
                d1, d2, d3, d4, d5 = st.columns(5)
                for _mc, _stat, _lbl, _hib in [
                    (d1, "DRtg",     "Best DRtg",  False),
                    (d2, "Opp eFG%", "Opp eFG%",   False),
                    (d3, "Opp TOV%", "Force TOs",  True),
                    (d4, "BLK Rate", "BLK Rate",   True),
                    (d5, "STL Rate", "STL Rate",   True),
                ]:
                    if _stat in fdf_def.columns:
                        row = fdf_def.loc[fdf_def[_stat].idxmax() if _hib else fdf_def[_stat].idxmin()]
                        _mc.metric(_lbl, row["Team"], f"{row[_stat]:.1f}")
                st.divider()

                # DRtg bar + defensive leaders
                d_chart, d_ld = st.columns([3, 2])
                with d_chart:
                    if "DRtg" in fdf_def.columns:
                        sdf_d = fdf_def.sort_values("DRtg", ascending=True).head(20)
                        fig_d = px.bar(sdf_d, x="DRtg", y="Team", orientation="h",
                                       color="DRtg", color_continuous_scale=_RYG_R, text="DRtg",
                                       hover_data={"Opp eFG%": ":.1f", "Opp TOV%": ":.1f",
                                                   "DREB%": ":.1f", "BLK Rate": ":.1f"},
                                       title="Best Defenses (lower DRtg = better)")
                        fig_d.update_traces(textposition="outside",
                                            texttemplate="%{text:.1f}", textfont_size=11)
                        fig_d.update_layout(height=max(380, len(sdf_d)*30+80),
                                            coloraxis_showscale=False,
                                            plot_bgcolor="rgba(0,0,0,0)",
                                            paper_bgcolor="rgba(0,0,0,0)",
                                            margin=dict(l=10, r=70, t=50, b=20),
                                            font=dict(size=12))
                        st.plotly_chart(fig_d, use_container_width=True)
                with d_ld:
                    st.markdown("#### Defensive Leaders")
                    show_stat_leaders(df_tr, [
                        ("DRtg",      "Best DRtg",  False),
                        ("Opp eFG%",  "Opp eFG%",   False),
                        ("Opp TOV%",  "Force TOs",  True),
                        ("BLK Rate",  "BLK Rate",   True),
                        ("STL Rate",  "STL Rate",   True),
                    ])
                st.divider()

                # Defensive Four Factors grouped bars
                st.markdown("#### Defensive Four Factors")
                if all(c in fdf_def.columns for c in
                       ["Opp eFG%", "Opp TOV%", "DREB%", "Opp FT Rate"]):
                    _sdf_dff = fdf_def.sort_values("DRtg", ascending=True)
                    fig_dff = go.Figure()
                    _dff_items = [
                        ("Opp eFG%",   "#d73027", "Opp eFG% (lower=better)"),
                        ("Opp TOV%",   "#1a9850", "Force TO% (higher=better)"),
                        ("DREB%",      "#3498db", "DREB% (higher=better)"),
                        ("Opp FT Rate","#9b59b6", "Opp FT Rate (lower=better)"),
                    ]
                    for col, color, lbl in _dff_items:
                        fig_dff.add_trace(go.Bar(
                            name=lbl, x=_sdf_dff["Team"], y=_sdf_dff[col],
                            marker_color=color, opacity=0.85,
                            hovertemplate="%{x}<br>" + lbl + ": %{y:.1f}<extra></extra>"))
                    fig_dff.update_layout(
                        barmode="group", yaxis_title="Value", height=380,
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=20, r=20, t=30, b=80),
                        legend=dict(orientation="h", y=1.05),
                        xaxis=dict(tickangle=-40), font=dict(size=11))
                    st.plotly_chart(fig_dff, use_container_width=True)
                st.divider()

                # BLK Rate vs STL Rate scatter
                if "BLK Rate" in fdf_def.columns and "STL Rate" in fdf_def.columns:
                    st.markdown("#### BLK Rate vs STL Rate — Rim vs Perimeter Defense")
                    fig_bs = go.Figure()
                    avg_blk = fdf_def["BLK Rate"].mean()
                    avg_stl = fdf_def["STL Rate"].mean()
                    fig_bs.add_hline(y=avg_stl, line_dash="dot",
                                     line_color="rgba(200,200,200,0.2)")
                    fig_bs.add_vline(x=avg_blk, line_dash="dot",
                                     line_color="rgba(200,200,200,0.2)")
                    for _, row in fdf_def.iterrows():
                        fig_bs.add_trace(go.Scatter(
                            x=[row["BLK Rate"]], y=[row["STL Rate"]],
                            mode="markers+text",
                            text=[row["Team"]],
                            textposition="top center",
                            textfont=dict(size=9, color="rgba(220,220,220,0.85)"),
                            marker=dict(size=11, color="#3498db",
                                        line=dict(color="rgba(255,255,255,0.4)", width=1)),
                            showlegend=False,
                            hovertemplate=(f"<b>{row['Team']}</b><br>"
                                           f"BLK Rate: {row['BLK Rate']:.1f}%<br>"
                                           f"STL Rate: {row['STL Rate']:.1f}%<extra></extra>"),
                        ))
                    fig_bs.update_layout(
                        xaxis=dict(title="BLK Rate % (rim protection)",
                                   gridcolor="rgba(255,255,255,0.05)"),
                        yaxis=dict(title="STL Rate % (perimeter pressure)",
                                   gridcolor="rgba(255,255,255,0.05)"),
                        height=420, plot_bgcolor="rgba(14,17,23,1)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=50, r=20, t=30, b=40), font=dict(size=11),
                    )
                    st.plotly_chart(fig_bs, use_container_width=True)
                    st.caption("Top-right = elite defenders (rim + perimeter) · Crosshairs = league average")
                    st.divider()

                st.subheader("Defense Table")
                show_table(df_tr, DEFENSE_COLS, "DRtg")
                st.subheader("By Class")
                show_class_breakdown(df_tr, DEFENSE_COLS)
                with st.expander("Team Comparison Radar"):
                    show_team_radar(df_tr, [
                        ("DRtg",     "Def Rtg",  False),
                        ("Opp eFG%", "Opp eFG%", False),
                        ("Opp TOV%", "Force TOs",True),
                        ("DREB%",    "DREB%",    True),
                        ("BLK Rate", "BLK Rate", True),
                        ("STL Rate", "STL Rate", True),
                    ], key="radar_def_tr")

        # ══ Team Deep Dive ════════════════════════════════════════════════════
        with sub_deep:
            @st.fragment
            def _render_deep_dive():
                _tr_names = sorted(df_tr["Team"].tolist()) if not df_tr.empty else []
                if not _tr_names:
                    st.info("No tracked teams yet.")
                    return

                sel_tr = st.selectbox("Select team for deep dive", _tr_names, key="tr_deep_sel")
                _tr_id = _name_to_id.get(sel_tr)
                if not _tr_id:
                    st.warning("Team ID not found.")
                    return

                adv = compute_team_tracked(_tr_id)
                if not adv:
                    st.info(f"No tracked data for {sel_tr}.")
                    return

                tgp = adv.get("gp", 0)
                _opp_pa_g = (adv["drtg"] / 100) * (adv.get("poss", 0) / tgp) if tgp else 0

                tr_info = df_tr[df_tr["Team"] == sel_tr].iloc[0] if sel_tr in df_tr["Team"].values else None
                _w = int(tr_info["W"]) if tr_info is not None and "W" in tr_info else "—"
                _l = int(tr_info["L"]) if tr_info is not None and "L" in tr_info else "—"

                kc = st.columns(6)
                for col_k, lbl, val, sub in [
                    (kc[0], "Record",       f"{_w}–{_l}",            "all games"),
                    (kc[1], "PPG",          f"{adv['pts_pg']:.1f}",   "tracked games"),
                    (kc[2], "PA/G",         f"{_opp_pa_g:.1f}",       "tracked games"),
                    (kc[3], "Net Rating",   f"{adv['ortg']-adv['drtg']:+.1f}", "ORtg − DRtg"),
                    (kc[4], "PPP",          f"{adv['ppp']:.3f}",      "pts per possession"),
                    (kc[5], "Pace",         f"{adv['pace']:.1f}",     "poss per game"),
                ]:
                    col_k.markdown(
                        f"<div class='kpi-tile'>"
                        f"<div class='kpi-label'>{lbl}</div>"
                        f"<div class='kpi-value'>{val}</div>"
                        f"<div class='kpi-sub'>{sub}</div>"
                        f"</div>", unsafe_allow_html=True)

                st.write("")
                st.markdown("<div class='section-hdr'>Advanced Metrics</div>", unsafe_allow_html=True)
                _adv_row1 = [
                    ("ORtg",     f"{adv['ortg']:.1f}",          "pts per 100 poss"),
                    ("DRtg",     f"{adv['drtg']:.1f}",          "pts allowed/100"),
                    ("Net Rtg",  f"{adv['ortg']-adv['drtg']:+.1f}", "ortg − drtg"),
                    ("eFG%",     f"{adv['efg']*100:.1f}%",       "effective FG%"),
                    ("Opp eFG%", f"{adv['oefg']*100:.1f}%",      "opp effective FG%"),
                ]
                _adv_row2 = [
                    ("TS%",      f"{adv['ts']*100:.1f}%",        "true shooting %"),
                    ("TOV%",     f"{adv['tov_r']*100:.1f}%",     "turnover rate"),
                    ("OREB%",    f"{adv['oreb_p']*100:.1f}%",    "off reb rate"),
                    ("DREB%",    f"{adv.get('dreb_p', 0)*100:.1f}%", "def reb rate"),
                    ("FT Rate",  f"{adv.get('ft_r', 0):.3f}",   "FTA / FGA"),
                ]
                for _row in [_adv_row1, _adv_row2]:
                    _cols_adv = st.columns(5)
                    for _c, (lbl, val, sub) in zip(_cols_adv, _row):
                        _c.markdown(
                            f"<div class='adv-tile'>"
                            f"<div class='adv-label'>{lbl}</div>"
                            f"<div class='adv-value'>{val}</div>"
                            f"<div style='font-size:10px;color:#8b949e'>{sub}</div>"
                            f"</div>", unsafe_allow_html=True)
                    st.write("")

                deep_tabs = st.tabs(["📊 Quarters & PPP", "💡 Win/Loss Patterns", "📋 Schedule"])

                with deep_tabs[0]:
                    st.markdown("<div class='section-hdr'>Quarter-by-Quarter Breakdown</div>",
                                unsafe_allow_html=True)
                    _periods = [
                        ("Q1", adv["q1_pts_pg"], adv["opp_q1_pts_pg"], adv["q1_ppp"], adv["opp_q1_ppp"]),
                        ("Q2", adv["q2_pts_pg"], adv["opp_q2_pts_pg"], adv["q2_ppp"], adv["opp_q2_ppp"]),
                        ("H1", adv["h1_pts_pg"], adv["opp_h1_pts_pg"], adv["h1_ppp"], adv["opp_h1_ppp"]),
                        ("Q3", adv["q3_pts_pg"], adv["opp_q3_pts_pg"], adv["q3_ppp"], adv["opp_q3_ppp"]),
                        ("Q4", adv["q4_pts_pg"], adv["opp_q4_pts_pg"], adv["q4_ppp"], adv["opp_q4_ppp"]),
                        ("H2", adv["h2_pts_pg"], adv["opp_h2_pts_pg"], adv["h2_ppp"], adv["opp_h2_ppp"]),
                        ("Full Game", adv["pts_pg"], _opp_pa_g, adv["ppp"], adv["drtg"] / 100),
                    ]
                    _qb_rows = []
                    for period, tppg, oppg, tppp, oppp in _periods:
                        _qb_rows.append({
                            "Period":   period,
                            "Team PPG": f"{tppg:.1f}",
                            "Opp PPG":  f"{oppg:.1f}",
                            "Margin":   f"{tppg - oppg:+.1f}",
                            "Team PPP": f"{tppp:.3f}",
                            "Opp PPP":  f"{oppp:.3f}",
                        })
                    st.dataframe(pd.DataFrame(_qb_rows), use_container_width=True, hide_index=True)

                    _q_labels = ["Q1", "Q2", "Q3", "Q4", "H1", "H2"]
                    _t_ppp = [adv["q1_ppp"], adv["q2_ppp"], adv["q3_ppp"], adv["q4_ppp"],
                              adv["h1_ppp"], adv["h2_ppp"]]
                    _o_ppp = [adv["opp_q1_ppp"], adv["opp_q2_ppp"], adv["opp_q3_ppp"],
                              adv["opp_q4_ppp"], adv["opp_h1_ppp"], adv["opp_h2_ppp"]]
                    _t_ppg = [adv["q1_pts_pg"], adv["q2_pts_pg"], adv["q3_pts_pg"], adv["q4_pts_pg"],
                              adv["h1_pts_pg"], adv["h2_pts_pg"]]
                    _o_ppg = [adv["opp_q1_pts_pg"], adv["opp_q2_pts_pg"], adv["opp_q3_pts_pg"],
                              adv["opp_q4_pts_pg"], adv["opp_h1_pts_pg"], adv["opp_h2_pts_pg"]]

                    qch1, qch2 = st.columns(2)
                    with qch1:
                        fig_ppp = go.Figure()
                        fig_ppp.add_trace(go.Bar(name=sel_tr, x=_q_labels, y=_t_ppp,
                                                  marker_color="#f0a500"))
                        fig_ppp.add_trace(go.Bar(name="Opponent", x=_q_labels, y=_o_ppp,
                                                  marker_color="#e74c3c"))
                        fig_ppp.update_layout(title="PPP by Period", barmode="group",
                                              yaxis_title="Points Per Possession", height=320,
                                              plot_bgcolor="rgba(0,0,0,0)",
                                              paper_bgcolor="rgba(0,0,0,0)",
                                              legend=dict(orientation="h", y=1.02),
                                              margin=dict(l=10, r=10, t=50, b=10))
                        st.plotly_chart(fig_ppp, use_container_width=True)
                    with qch2:
                        fig_ppg = go.Figure()
                        fig_ppg.add_trace(go.Bar(name=sel_tr, x=_q_labels, y=_t_ppg,
                                                  marker_color="#f0a500"))
                        fig_ppg.add_trace(go.Bar(name="Opponent", x=_q_labels, y=_o_ppg,
                                                  marker_color="#e74c3c"))
                        fig_ppg.update_layout(title="PPG by Period", barmode="group",
                                              yaxis_title="Points Per Game", height=320,
                                              plot_bgcolor="rgba(0,0,0,0)",
                                              paper_bgcolor="rgba(0,0,0,0)",
                                              legend=dict(orientation="h", y=1.02),
                                              margin=dict(l=10, r=10, t=50, b=10))
                        st.plotly_chart(fig_ppg, use_container_width=True)

                    _q_ppp_map = {"Q1": adv["q1_ppp"], "Q2": adv["q2_ppp"],
                                  "Q3": adv["q3_ppp"], "Q4": adv["q4_ppp"]}
                    _best_q  = max(_q_ppp_map, key=_q_ppp_map.get)
                    _worst_q = min(_q_ppp_map, key=_q_ppp_map.get)
                    st.info(
                        f"Strongest quarter: **{_best_q}** ({_q_ppp_map[_best_q]:.3f} PPP) — "
                        f"Weakest: **{_worst_q}** ({_q_ppp_map[_worst_q]:.3f} PPP)")

                with deep_tabs[1]:
                    _gl = adv.get("game_log", [])
                    if len(_gl) < 2:
                        st.info("Need at least 2 tracked games for insights.")
                    else:
                        _gl_df = pd.DataFrame(_gl)
                        _gl_df["result"] = _gl_df["margin"].apply(lambda m: "W" if m > 0 else "L")
                        _wins   = _gl_df[_gl_df["result"] == "W"]
                        _losses = _gl_df[_gl_df["result"] == "L"]
                        _close  = _gl_df[_gl_df["margin"].abs() <= 10]
                        _cg_w   = len(_close[_close["result"] == "W"])

                        _bullets = [
                            f"Strongest quarter: **{_best_q}** ({_q_ppp_map[_best_q]:.3f} PPP)",
                        ]
                        if len(_wins) > 0:
                            _bullets.append(
                                f"In wins: avg ORtg {_wins['ortg'].mean():.1f}, "
                                f"avg DRtg {_wins['drtg'].mean():.1f}")
                        if len(_losses) > 0:
                            _bullets.append(
                                f"In losses: avg ORtg {_losses['ortg'].mean():.1f}, "
                                f"avg DRtg {_losses['drtg'].mean():.1f}")
                        if len(_close) > 0:
                            _bullets.append(
                                f"Close game record (≤10 pt margin): "
                                f"{_cg_w}–{len(_close) - _cg_w}")
                        for b in _bullets:
                            st.markdown(f"- {b}")
                        st.write("")

                        wl_c1, wl_c2 = st.columns(2)
                        with wl_c1:
                            _wl_data = []
                            for res, grp in [("Wins", _wins), ("Losses", _losses)]:
                                if len(grp):
                                    _wl_data.append({"Result": res,
                                                     "ORtg": grp["ortg"].mean(),
                                                     "DRtg": grp["drtg"].mean()})
                            if _wl_data:
                                _wl_df2 = pd.DataFrame(_wl_data)
                                fig_wl = go.Figure()
                                fig_wl.add_trace(go.Bar(name="ORtg", x=_wl_df2["Result"],
                                                        y=_wl_df2["ORtg"], marker_color="#f0a500"))
                                fig_wl.add_trace(go.Bar(name="DRtg", x=_wl_df2["Result"],
                                                        y=_wl_df2["DRtg"], marker_color="#e74c3c"))
                                fig_wl.update_layout(title="Avg Ratings: W vs L",
                                                     barmode="group", height=300,
                                                     plot_bgcolor="rgba(0,0,0,0)",
                                                     paper_bgcolor="rgba(0,0,0,0)",
                                                     margin=dict(l=10, r=10, t=40, b=10))
                                st.plotly_chart(fig_wl, use_container_width=True)
                        with wl_c2:
                            fig_om = px.scatter(
                                _gl_df, x="ortg", y="margin", color="result",
                                color_discrete_map={"W": "#2ecc71", "L": "#e74c3c"},
                                hover_data=["opp", "drtg"],
                                title="ORtg vs Margin",
                                labels={"ortg": "ORtg", "margin": "Margin"},
                                height=300,
                            )
                            fig_om.update_layout(plot_bgcolor="rgba(0,0,0,0)",
                                                 paper_bgcolor="rgba(0,0,0,0)",
                                                 margin=dict(l=10, r=10, t=40, b=10))
                            st.plotly_chart(fig_om, use_container_width=True)

                        fig_dm = px.scatter(
                            _gl_df, x="drtg", y="margin", color="result",
                            color_discrete_map={"W": "#2ecc71", "L": "#e74c3c"},
                            hover_data=["opp", "ortg"],
                            title="DRtg vs Margin (lower DRtg = better defense)",
                            labels={"drtg": "DRtg", "margin": "Margin"},
                            height=300,
                        )
                        fig_dm.update_layout(plot_bgcolor="rgba(0,0,0,0)",
                                             paper_bgcolor="rgba(0,0,0,0)",
                                             margin=dict(l=10, r=10, t=40, b=10))
                        st.plotly_chart(fig_dm, use_container_width=True)

                with deep_tabs[2]:
                    all_gs = games_for_team(_tr_id)
                    tr_gs  = games_for_team(_tr_id, tracked_only=True)
                    _srows = []
                    for g in sorted(all_gs, key=lambda x: x["date"]):
                        _res2, _my2, _opp2 = win_loss(g, _tr_id)
                        _srows.append({
                            "Date":     g["date"],
                            "Opponent": opponent_name(g, _tr_id),
                            "Result":   _res2,
                            "Score":    f"{_my2}–{_opp2}",
                            "Tracked":  "✓" if g.get("tracked") else "",
                        })
                    st.dataframe(pd.DataFrame(_srows), use_container_width=True, hide_index=True)

                    if tr_gs:
                        st.markdown("<div class='section-hdr'>Tracked Game Box Scores</div>",
                                    unsafe_allow_html=True)
                        for g in sorted(tr_gs, key=lambda x: x["date"], reverse=True):
                            try:
                                _dl2 = datetime.strptime(g["date"], "%Y-%m-%d").strftime("%b %d, %Y")
                            except Exception:
                                _dl2 = g["date"] or "—"
                            _opp_lbl = opponent_name(g, _tr_id)
                            _res3, _my3, _opp3 = win_loss(g, _tr_id)
                            with st.expander(f"📋 {_dl2} vs {_opp_lbl}  ({_res3} {_my3}–{_opp3})"):
                                _bsr1, _bsr2, _gi = compute_game_box_score(g["id"])
                                if any(not r.get("_totals") for r in _bsr1 + _bsr2):
                                    show_game_box_score(_bsr1, _bsr2, {}, _gi, _cfg)
                                else:
                                    st.info("Box score unavailable.")

            _render_deep_dive()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — TRACKED RANKINGS  (advanced analytical deep dive rankings)
# ══════════════════════════════════════════════════════════════════════════════

with tab_tr_rk:
    if df_tr.empty:
        st.info("No tracked teams yet. Enter play-by-play data in the Game Tracker to unlock this section.")
    else:
        fdf_rk_tr = _f(df_tr)
        if fdf_rk_tr.empty:
            st.info("No teams match the current filters.")
        else:
            # ── Rank selector + sort ──────────────────────────────────────────
            _rsel_c1, _rsel_c2 = st.columns([2, 1])
            with _rsel_c1:
                _tr_metric = st.selectbox(
                    "Rank Tracked Teams By",
                    ["Net Rating", "ORtg", "DRtg", "PPP", "eFG%", "TS%",
                     "OREB%", "TOV%", "Pace", "AST/TOV"],
                    key="rk_tr_metric"
                )
            with _rsel_c2:
                _tr_good_low = {"DRtg", "TOV%", "Opp eFG%"}
                _tr_col_map = {
                    "Net Rating": "Net Rtg", "ORtg": "ORtg", "DRtg": "DRtg",
                    "PPP": "PPP", "eFG%": "eFG%", "TS%": "TS%",
                    "OREB%": "OREB%", "TOV%": "TOV%",
                    "Pace": "Pace", "AST/TOV": "AST/TOV",
                }
                _tr_col = _tr_col_map[_tr_metric]
                _tr_asc = (_tr_metric in _tr_good_low)

            _tr_df_s = fdf_rk_tr.sort_values(_tr_col, ascending=_tr_asc).reset_index(drop=True) \
                       if _tr_col in fdf_rk_tr.columns else fdf_rk_tr.reset_index(drop=True)

            # ── KPI row ───────────────────────────────────────────────────────
            rk_k1, rk_k2, rk_k3, rk_k4, rk_k5 = st.columns(5)
            for _mc, _stat, _lbl, _hib in [
                (rk_k1, "Net Rtg", "Best Net Rtg",  True),
                (rk_k2, "ORtg",    "Best Offense",  True),
                (rk_k3, "DRtg",    "Best Defense",  False),
                (rk_k4, "PPP",     "Best PPP",      True),
                (rk_k5, "eFG%",    "Best eFG%",     True),
            ]:
                if _stat in fdf_rk_tr.columns:
                    _row = fdf_rk_tr.loc[fdf_rk_tr[_stat].idxmax() if _hib
                                         else fdf_rk_tr[_stat].idxmin()]
                    _mc.metric(_lbl, _row["Team"], f"{_row[_stat]:.1f}")
            st.divider()

            # ── Efficiency scatter ────────────────────────────────────────────
            show_efficiency_scatter(fdf_rk_tr, title="ORtg vs DRtg — KenPom Quadrant",
                                    key="eff_scatter_rk")
            st.divider()

            # ── Rank bar chart ────────────────────────────────────────────────
            if _tr_col in _tr_df_s.columns:
                _tr_colors = (
                    ["#f0a500"] * min(3, len(_tr_df_s)) +
                    ["#3498db"] * max(0, min(7, len(_tr_df_s) - 3)) +
                    ["#555d68"] * max(0, len(_tr_df_s) - 10)
                )
                if _tr_asc:
                    _tr_colors = list(reversed(_tr_colors))
                fig_tr_rk = go.Figure(go.Bar(
                    x=[t.replace(" Girls", "").replace(" Boys", "")
                       for t in _tr_df_s["Team"]],
                    y=_tr_df_s[_tr_col],
                    marker_color=_tr_colors,
                    text=_tr_df_s[_tr_col].apply(lambda v: f"{v:.1f}"),
                    textposition="outside",
                ))
                fig_tr_rk.update_layout(
                    title=f"Tracked Teams — Ranked by {_tr_metric}",
                    yaxis_title=_tr_metric,
                    height=max(350, len(_tr_df_s) * 25),
                    xaxis=dict(tickangle=-45),
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=10, r=20, t=50, b=80), font=dict(size=11))
                st.plotly_chart(fig_tr_rk, use_container_width=True)
            st.divider()

            # ── Net Rtg bar ───────────────────────────────────────────────────
            show_net_rtg_chart(fdf_rk_tr, key="net_rtg_rk")
            st.divider()

            # ── Rank cards ────────────────────────────────────────────────────
            st.markdown("<div class='section-hdr'>Rankings</div>", unsafe_allow_html=True)
            st.caption("EV # = Everything (box-score) rank · Tracked rank based on selected metric")
            for i, (_, row) in enumerate(_tr_df_s.iterrows()):
                tr_rank = i + 1
                team    = row["Team"]
                ev_rk   = _ev_rank_map.get(team, "—")
                bc      = _rank_badge_cls(tr_rank)
                ortg    = f"{row.get('ORtg', 0):.1f}" if "ORtg" in row else "—"
                drtg    = f"{row.get('DRtg', 0):.1f}" if "DRtg" in row else "—"
                net_r   = f"{row.get('Net Rtg', 0):+.1f}" if "Net Rtg" in row else "—"
                ppp_v   = f"{row.get('PPP', 0):.3f}"  if "PPP" in row else "—"
                efg_v   = f"{row.get('eFG%', 0):.1f}%" if "eFG%" in row else "—"
                ts_v    = f"{row.get('TS%', 0):.1f}%"  if "TS%" in row else "—"
                tov_v   = f"{row.get('TOV%', 0):.1f}%" if "TOV%" in row else "—"
                oreb_v  = f"{row.get('OREB%', 0):.1f}%" if "OREB%" in row else "—"
                cls     = row.get("Class", "")
                w_l     = f"{int(row.get('W',0))}-{int(row.get('L',0))}" if "W" in row else "—"
                vs5     = _vs_str(team, 5)
                vs10    = _vs_str(team, 10)
                vs20    = _vs_str(team, 20)
                ev_badge = (
                    f"&nbsp;<span style='background:#1a2d1a;border:1px solid #f0a500;"
                    f"border-radius:4px;padding:2px 5px;font-size:9px;"
                    f"color:#f0a500;font-weight:700'>EV #{ev_rk}</span>"
                ) if ev_rk != "—" else ""

                st.markdown(
                    f"<div class='rank-card'>"
                    f"<div class='rank-badge {bc}'>{tr_rank}</div>"
                    f"<div style='flex:1;min-width:0'>"
                    f"  <div class='rank-team'>{team}{ev_badge}</div>"
                    f"  <div class='rank-rec'>{cls} · {w_l} · "
                    f"ORtg {ortg} / DRtg {drtg} / Net {net_r}</div>"
                    f"  <div class='rank-rec'>PPP {ppp_v} · eFG% {efg_v} · "
                    f"TS% {ts_v} · TOV% {tov_v} · OREB% {oreb_v}</div>"
                    f"  <div class='rank-vs'>vs T5: <b>{vs5}</b> &nbsp;|&nbsp; "
                    f"vs T10: <b>{vs10}</b> &nbsp;|&nbsp; vs T20: <b>{vs20}</b></div>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            st.divider()

            # ── Four Factors radar ────────────────────────────────────────────
            st.markdown("<div class='section-hdr'>Four Factors Comparison</div>",
                        unsafe_allow_html=True)
            st.caption("Dean Oliver's Four Factors — Shooting (40%) · Ball Security (25%) · "
                       "Off. Rebounding (20%) · FT Rate (15%)")
            show_four_factors_chart(fdf_rk_tr)
            st.divider()

            # ── Full tracked table ────────────────────────────────────────────
            st.markdown("<div class='section-hdr'>Full Advanced Stats Table</div>",
                        unsafe_allow_html=True)
            _tr_tbl_cols = [c for c in [
                "Team", "Class", "GP", "W", "L", "W%",
                "ORtg", "DRtg", "Net Rtg", "Pace",
                "eFG%", "Opp eFG%", "TS%", "Opp TS%",
                "TOV%", "OREB%", "DREB%",
                "PPP", "Opp PPP",
                "FT Rate", "Opp FT Rate",
                "AST/TOV", "Opp TOV%",
                "Paint FG%", "Paint Pts/G",
                "Ast%", "Unast%",
                "Q1 Diff", "Q2 Diff", "Q3 Diff", "Q4 Diff",
                "Power Score",
            ] if c in _tr_df_s.columns]
            _tr_tbl = _tr_df_s[_tr_tbl_cols].copy()
            _tr_tbl.insert(0, "Tracked Rank", range(1, len(_tr_tbl) + 1))
            _tr_tbl.insert(1, "Ev Rank", [_ev_rank_map.get(t, "—") for t in _tr_df_s["Team"]])
            _tr_tbl["vs T5"]  = [_vs_str(t, 5)  for t in _tr_df_s["Team"]]
            _tr_tbl["vs T10"] = [_vs_str(t, 10) for t in _tr_df_s["Team"]]
            _tr_tbl["vs T20"] = [_vs_str(t, 20) for t in _tr_df_s["Team"]]

            _grad_tr_cols = [c for c in _tr_tbl_cols if c in _GRADIENT_COLS]
            styler_tr = _tr_tbl.reset_index(drop=True).style.set_properties(**{"font-size": "12px"})
            styler_tr = _apply_grads(styler_tr, _grad_tr_cols)
            st.dataframe(styler_tr, use_container_width=True, hide_index=True)

            # ── Box scores for tracked team ───────────────────────────────────
            st.markdown("<div class='section-hdr'>View Tracked Box Scores</div>",
                        unsafe_allow_html=True)
            _tr_names_rk = _tr_df_s["Team"].tolist()
            _tr_sel_rk   = st.selectbox("Select Team", _tr_names_rk, key="rk_tr_team_sel_rk")
            _tr_id_rk    = _name_to_id.get(_tr_sel_rk)
            if _tr_id_rk:
                _tr_games_rk = games_for_team(_tr_id_rk, tracked_only=True)
                if not _tr_games_rk:
                    st.info("No tracked games found.")
                else:
                    for g in sorted(_tr_games_rk, key=lambda x: x["date"], reverse=True):
                        try:
                            _dl_rk = datetime.strptime(g["date"], "%Y-%m-%d").strftime("%b %d, %Y")
                        except Exception:
                            _dl_rk = g["date"] or "—"
                        _opp_rk = opponent_name(g, _tr_id_rk)
                        _r_rk, _m_rk, _o_rk = win_loss(g, _tr_id_rk)
                        with st.expander(f"📋 {_dl_rk} vs {_opp_rk}  ({_r_rk} {_m_rk}–{_o_rk})"):
                            _bsr1_rk, _bsr2_rk, _gi_rk = compute_game_box_score(g["id"])
                            if any(not r.get("_totals") for r in _bsr1_rk + _bsr2_rk):
                                show_game_box_score(_bsr1_rk, _bsr2_rk, {}, _gi_rk, _cfg)
                            else:
                                st.info("Box score data unavailable.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — MATCHUP SIMULATOR
# ══════════════════════════════════════════════════════════════════════════════

with tab_mu:
    st.markdown('<div class="section-hdr">Matchup Simulator</div>', unsafe_allow_html=True)
    st.caption("Pick any two teams to compare stats and see a projected outcome.")

    _all_team_names_mu = sorted(df_all["Team"].tolist()) if not df_all.empty else []
    if len(_all_team_names_mu) < 2:
        st.info("Need at least two teams.")
    else:
        mc1, mc2 = st.columns(2)
        match_t1 = mc1.selectbox("Team 1", _all_team_names_mu, index=0, key="mu_t1")
        match_t2 = mc2.selectbox("Team 2", _all_team_names_mu,
                                  index=min(1, len(_all_team_names_mu) - 1), key="mu_t2")

        if match_t1 == match_t2:
            st.warning("Pick two different teams.")
        else:
            _t1_id_mu = _name_to_id.get(match_t1)
            _t2_id_mu = _name_to_id.get(match_t2)
            _mu = compute_matchup(_t1_id_mu, _t2_id_mu) if (_t1_id_mu and _t2_id_mu) else None

            r1_mu = df_all[df_all["Team"] == match_t1].iloc[0] if match_t1 in df_all["Team"].values else None
            r2_mu = df_all[df_all["Team"] == match_t2].iloc[0] if match_t2 in df_all["Team"].values else None
            r1_tr = df_tr[df_tr["Team"] == match_t1].iloc[0] if (not df_tr.empty and match_t1 in df_tr["Team"].values) else None
            r2_tr = df_tr[df_tr["Team"] == match_t2].iloc[0] if (not df_tr.empty and match_t2 in df_tr["Team"].values) else None

            _ev_r1 = _ev_rank_map.get(match_t1, "—")
            _ev_r2 = _ev_rank_map.get(match_t2, "—")
            _is_tr1 = r1_tr is not None
            _is_tr2 = r2_tr is not None

            st.divider()
            h1c, hmc, h2c = st.columns([2, 1, 2])
            with h1c:
                _rec1   = f"{int(r1_mu['W'])}-{int(r1_mu['L'])}" if r1_mu is not None else "—"
                _vs5_1  = _vs_str(match_t1, 5)
                _vs10_1 = _vs_str(match_t1, 10)
                _tr1_b  = "<span class='tracked-badge'>TRACKED</span>" if _is_tr1 else ""
                st.markdown(
                    f"<div style='background:#161b22;border:1px solid #30363d;border-radius:12px;"
                    f"padding:16px;text-align:center'>"
                    f"<div style='font-size:11px;color:#8b949e'>#{_ev_r1} Everything Rank</div>"
                    f"<div style='font-size:22px;font-weight:800;color:#f0f6fc'>"
                    f"{match_t1}{_tr1_b}</div>"
                    f"<div style='font-size:14px;color:#f0a500;font-weight:700'>{_rec1}</div>"
                    f"<div style='font-size:11px;color:#8b949e;margin-top:4px'>"
                    f"vs T5: {_vs5_1} &nbsp;|&nbsp; vs T10: {_vs10_1}</div>"
                    f"</div>", unsafe_allow_html=True)
            with hmc:
                st.markdown(
                    "<div style='text-align:center;padding-top:20px;"
                    "font-size:28px;font-weight:800;color:#8b949e'>vs</div>",
                    unsafe_allow_html=True)
            with h2c:
                _rec2   = f"{int(r2_mu['W'])}-{int(r2_mu['L'])}" if r2_mu is not None else "—"
                _vs5_2  = _vs_str(match_t2, 5)
                _vs10_2 = _vs_str(match_t2, 10)
                _tr2_b  = "<span class='tracked-badge'>TRACKED</span>" if _is_tr2 else ""
                st.markdown(
                    f"<div style='background:#161b22;border:1px solid #30363d;border-radius:12px;"
                    f"padding:16px;text-align:center'>"
                    f"<div style='font-size:11px;color:#8b949e'>#{_ev_r2} Everything Rank</div>"
                    f"<div style='font-size:22px;font-weight:800;color:#f0f6fc'>"
                    f"{match_t2}{_tr2_b}</div>"
                    f"<div style='font-size:14px;color:#f0a500;font-weight:700'>{_rec2}</div>"
                    f"<div style='font-size:11px;color:#8b949e;margin-top:4px'>"
                    f"vs T5: {_vs5_2} &nbsp;|&nbsp; vs T10: {_vs10_2}</div>"
                    f"</div>", unsafe_allow_html=True)

            st.divider()
            badge_color = "#2ecc71"
            if _mu and "efficiency" in _mu.get("method", ""):
                wpc1  = _mu["prob_a"] * 100
                wpc2  = 100 - wpc1
                psc1  = _mu["proj_a"]
                psc2  = _mu["proj_b"]
                fav   = match_t1 if psc1 >= psc2 else match_t2
                _n_h2h = _mu.get("n_h2h", 0)
                if _n_h2h:
                    method_note  = f"ORtg · DRtg · Pace + {_n_h2h} H2H game{'s' if _n_h2h != 1 else ''}"
                    method_badge = "📊 TRACKED + H2H"
                else:
                    method_note  = "ORtg · DRtg · Pace (additive)"
                    method_badge = "📊 TRACKED DATA"
                pr1, pr2, pr3, pr4, pr5 = st.columns(5)
                pr1.metric(f"{match_t1} Win Prob", f"{wpc1:.0f}%")
                pr2.metric(f"{match_t1} Proj Score", f"{psc1:.1f}")
                pr3.metric("Margin", f"{abs(psc1 - psc2):.1f} pts", f"Favor: {fav}")
                pr4.metric(f"{match_t2} Proj Score", f"{psc2:.1f}")
                pr5.metric(f"{match_t2} Win Prob", f"{wpc2:.0f}%")
            elif _mu and _mu.get("method") in ("score", "score+h2h"):
                wpc1  = _mu["prob_a"] * 100
                wpc2  = 100 - wpc1
                psc1  = _mu["proj_a"]
                psc2  = _mu["proj_b"]
                fav   = match_t1 if psc1 >= psc2 else match_t2
                _n_h2h = _mu.get("n_h2h", 0)
                if _n_h2h:
                    method_note  = f"PPG avg + {_n_h2h} H2H game{'s' if _n_h2h != 1 else ''}"
                    method_badge = "📋 SCORE + H2H"
                else:
                    method_note  = "PPG average"
                    method_badge = "📋 SCORE-BASED"
                badge_color = "#8b949e"
                pr1, pr2, pr3, pr4, pr5 = st.columns(5)
                pr1.metric(f"{match_t1} Win Prob", f"{wpc1:.0f}%")
                pr2.metric(f"{match_t1} Proj Score", f"{psc1:.1f}")
                pr3.metric("Margin", f"{abs(psc1 - psc2):.1f} pts", f"Favor: {fav}")
                pr4.metric(f"{match_t2} Proj Score", f"{psc2:.1f}")
                pr5.metric(f"{match_t2} Win Prob", f"{wpc2:.0f}%")
            else:
                ps1_mu = r1_mu["Power Score"] if r1_mu is not None else 50
                ps2_mu = r2_mu["Power Score"] if r2_mu is not None else 50
                total  = ps1_mu + ps2_mu
                wpc1   = ps1_mu / total * 100 if total else 50.0
                wpc2   = 100 - wpc1
                fav    = match_t1 if ps1_mu >= ps2_mu else match_t2
                ppg1   = r1_mu["PPG"] if r1_mu is not None else 0
                ppg2   = r2_mu["PPG"] if r2_mu is not None else 0
                proj_margin = abs(ppg1 - ppg2) * abs(ps1_mu - ps2_mu) / 100
                method_note  = "Power Score ratio"
                method_badge = "📋 SCORE-BASED"
                badge_color  = "#8b949e"
                pr1, pr2, pr3 = st.columns(3)
                pr1.metric(f"{match_t1} Win Prob", f"{wpc1:.0f}%")
                pr2.metric("Projected Margin", f"{proj_margin:.1f} pts", f"Favor: {fav}")
                pr3.metric(f"{match_t2} Win Prob", f"{wpc2:.0f}%")

            st.markdown(
                f"<div style='text-align:center;margin-bottom:6px'>"
                f"<span style='background:#161b22;border:1px solid {badge_color};"
                f"color:{badge_color};font-size:10px;font-weight:700;text-transform:uppercase;"
                f"letter-spacing:1px;border-radius:4px;padding:3px 10px'>{method_badge}</span>"
                f"</div>", unsafe_allow_html=True)

            bar_html = (
                f"<div style='background:#2d333b;border-radius:6px;height:24px;overflow:hidden;"
                f"position:relative'>"
                f"<div style='background:#3498db;width:{wpc1:.0f}%;height:100%;float:left;"
                f"display:flex;align-items:center;justify-content:center;"
                f"font-size:11px;font-weight:700;color:#fff'>"
                f"{'&nbsp;' + str(round(wpc1)) + '%' if wpc1 > 12 else ''}</div>"
                f"<div style='background:#e74c3c;width:{wpc2:.0f}%;height:100%;float:left;"
                f"display:flex;align-items:center;justify-content:center;"
                f"font-size:11px;font-weight:700;color:#fff'>"
                f"{'&nbsp;' + str(round(wpc2)) + '%' if wpc2 > 12 else ''}</div>"
                f"</div>"
                f"<div style='display:flex;justify-content:space-between;font-size:11px;"
                f"color:#8b949e;margin-top:4px'>"
                f"<span style='color:#3498db;font-weight:700'>{match_t1}</span>"
                f"<span style='font-size:10px;color:#6e7681'>Projection: {method_note}</span>"
                f"<span style='color:#e74c3c;font-weight:700'>{match_t2}</span></div>"
            )
            st.markdown(bar_html, unsafe_allow_html=True)

            # Projection breakdown when H2H blending is active
            if _mu and _mu.get("n_h2h", 0) and _mu.get("h2h_proj_a") is not None:
                _nh = _mu["n_h2h"]
                with st.expander("📐 Projection breakdown", expanded=False):
                    bc1, bc2, bc3 = st.columns(3)
                    bc1.metric("Efficiency-only",
                               f"{_mu['eff_proj_a']:.1f} – {_mu['eff_proj_b']:.1f}",
                               f"Margin: {_mu['eff_proj_a']-_mu['eff_proj_b']:+.1f}")
                    bc2.metric(f"H2H avg ({_nh} game{'s' if _nh!=1 else ''})",
                               f"{_mu['h2h_proj_a']:.1f} – {_mu['h2h_proj_b']:.1f}",
                               f"Margin: {_mu['h2h_proj_a']-_mu['h2h_proj_b']:+.1f}")
                    bc3.metric("Blended",
                               f"{_mu['proj_a']:.1f} – {_mu['proj_b']:.1f}",
                               f"Margin: {_mu['proj_a']-_mu['proj_b']:+.1f}")

            st.divider()
            show_matchup_bars(r1_tr if r1_tr is not None else r1_mu,
                              r2_tr if r2_tr is not None else r2_mu,
                              match_t1, match_t2)

            st.divider()
            st.markdown("#### Side-by-Side Stats")
            r1_src = r1_tr if r1_tr is not None else r1_mu
            r2_src = r2_tr if r2_tr is not None else r2_mu
            cmp_stats = [
                ("PPG",   "Points/Game",         True),
                ("PA/G",  "Points Allowed/Game",  False),
                ("Diff",  "Point Differential",   True),
                ("W%",    "Win %",                True),
                ("SOS",   "Strength of Schedule", True),
            ]
            if r1_tr is not None and r2_tr is not None:
                cmp_stats += [
                    ("ORtg",    "Off. Rating",  True),
                    ("DRtg",    "Def. Rating",  False),
                    ("Net Rtg", "Net Rating",   True),
                    ("eFG%",    "eFG%",         True),
                    ("TOV%",    "TOV%",         False),
                    ("OREB%",   "Off. Reb %",   True),
                    ("DREB%",   "Def. Reb %",   True),
                    ("FT Rate", "FT Rate",      True),
                    ("PPP",     "PPP",          True),
                    ("Pace",    "Pace",         True),
                ]
            cmp_rows = []
            for col, label, hib in cmp_stats:
                v1 = (r1_src.get(col) if hasattr(r1_src, "get") else
                      r1_src[col] if r1_src is not None and col in r1_src else None)
                v2 = (r2_src.get(col) if hasattr(r2_src, "get") else
                      r2_src[col] if r2_src is not None and col in r2_src else None)
                if v1 is None or v2 is None:
                    continue
                try:
                    v1f, v2f = float(v1), float(v2)
                except (TypeError, ValueError):
                    continue
                better1 = v1f >= v2f if hib else v1f <= v2f
                cmp_rows.append({
                    match_t1: f"{'✅ ' if better1 else ''}{v1f:.1f}",
                    "Stat":    label,
                    match_t2: f"{'✅ ' if not better1 else ''}{v2f:.1f}",
                })
            if cmp_rows:
                st.dataframe(pd.DataFrame(cmp_rows).set_index("Stat"), use_container_width=True)

            st.divider()
            st.markdown("#### 📜 Head-to-Head History")
            h2h_games = query("""
                SELECT g.id, g.date, g.home_score, g.away_score, g.tracked,
                       t1.id AS t1id, t1.name AS t1, t2.id AS t2id, t2.name AS t2
                FROM games g
                JOIN teams t1 ON t1.id=g.team1_id
                JOIN teams t2 ON t2.id=g.team2_id
                WHERE (t1.name=? AND t2.name=?) OR (t1.name=? AND t2.name=?)
                ORDER BY g.date DESC
            """, (match_t1, match_t2, match_t2, match_t1))

            if not h2h_games:
                st.info("These two teams have not played each other yet.")
            else:
                h2h_w1 = sum(1 for g in h2h_games
                             if g["home_score"] is not None
                             and ((g["t1"] == match_t1 and g["home_score"] > g["away_score"])
                                  or (g["t2"] == match_t1 and g["away_score"] > g["home_score"])))
                h2h_w2 = len([g for g in h2h_games if g["home_score"] is not None]) - h2h_w1
                hh1, hh2 = st.columns(2)
                hh1.metric(f"{match_t1} wins", h2h_w1)
                hh2.metric(f"{match_t2} wins", h2h_w2)
                for g in h2h_games:
                    if g["home_score"] is None:
                        continue
                    t1_win  = g["home_score"] > g["away_score"]
                    winner  = g["t1"] if t1_win else g["t2"]
                    w_sc    = g["home_score"] if t1_win else g["away_score"]
                    l_sc    = g["away_score"] if t1_win else g["home_score"]
                    loser   = g["t2"] if t1_win else g["t1"]
                    tr_lbl  = " 📊" if g["tracked"] else ""
                    try:
                        dl = datetime.strptime(g["date"], "%Y-%m-%d").strftime("%B %d, %Y")
                    except Exception:
                        dl = g["date"] or "—"
                    st.markdown(
                        f"<div class='score-card'>"
                        f"<span style='color:#8b949e;font-size:11px'>{dl}{tr_lbl}</span><br>"
                        f"<span style='color:#2ecc71;font-weight:700'>{winner}</span> "
                        f"<span style='color:#f0a500;font-weight:800'>{w_sc}</span>  –  "
                        f"<span style='color:#8b949e;font-weight:700'>{loser}</span> "
                        f"<span style='color:#555d68;font-weight:800'>{l_sc}</span>"
                        f"</div>", unsafe_allow_html=True)
                    if g["tracked"]:
                        with st.expander("View Box Score"):
                            rows_h1, rows_h2, gi_h = compute_game_box_score(g["id"])
                            if any(not r.get("_totals") for r in rows_h1 + rows_h2):
                                show_game_box_score(rows_h1, rows_h2, {}, gi_h, _cfg)
