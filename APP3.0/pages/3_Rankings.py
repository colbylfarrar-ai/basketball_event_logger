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
from helpers.constants import CLASS_ORDER, _RYG, _RYG_R
from helpers.game_utils import streak, record_str, normalize
from helpers.stats_rankings import game_team_stats, compute_all_rankings, compute_tracked_rankings
from helpers.stats_team import compute_matchup
from helpers.stats_players import (compute_game_box_score,
                                    compute_game_quarter_scores)
from helpers.settings_utils import get_all_settings, apply_theme_css
from helpers.box_score_render import show_game_box_score, _show_linescore
from helpers.charts import (show_shot_chart, show_scoring_pie,
                             show_four_factors_bars, show_efficiency_scatter,
                             show_matchup_bars, show_player_leaderboard_chart,
                             show_trend_chart, show_score_flow_chart)
from helpers.ui_utils import patch_dataframe

initialize_database()
_cfg = get_all_settings()
apply_theme_css(_cfg)
patch_dataframe()

# ── Card / badge CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
.dash-card {
    background: linear-gradient(135deg,#0d1117 0%,#161b22 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:20px 22px; margin-bottom:14px;
}
.dash-card-title {
    font-size:10px; color:#8b949e; text-transform:uppercase;
    letter-spacing:1.2px; margin-bottom:6px;
}
.dash-card-value {
    font-size:34px; font-weight:800; color:#f0a500; line-height:1.1;
}
.dash-card-sub { font-size:13px; color:#c9d1d9; margin-top:6px; }
.dash-card-meta { font-size:11px; color:#8b949e; margin-top:2px; }
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
    padding:11px 14px; margin-bottom:6px; display:flex;
    align-items:center; gap:12px;
}
.rank-badge {
    width:30px; height:30px; border-radius:50%; display:flex;
    align-items:center; justify-content:center;
    font-weight:800; font-size:13px; flex-shrink:0;
}
.rank-1 { background:#f0a500; color:#000; }
.rank-2 { background:#adb5bd; color:#000; }
.rank-3 { background:#cd7f32; color:#fff; }
.rank-n { background:#2d333b; color:#c9d1d9; }
.rank-team { font-size:14px; font-weight:700; color:#f0f6fc; }
.rank-rec  { font-size:12px; color:#8b949e; }
.rank-ps   { font-size:13px; font-weight:700; color:#58a6ff; margin-left:auto; }
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
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL FILTERS  (sidebar-style row at the top)
# ══════════════════════════════════════════════════════════════════════════════

st.title("📊 League Analytics")

f1, f2, f3 = st.columns(3)
sel_class  = f1.multiselect("Class", CLASS_ORDER, default=CLASS_ORDER)
sel_gender = f2.selectbox("Gender", ["All","M","F"])
min_gp     = f3.number_input("Min Games", min_value=0, value=0, step=1)


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    df = df[df["Class"].isin(sel_class)]
    if sel_gender != "All":
        df = df[df["Gender"] == sel_gender]
    return df[df["GP"] >= min_gp]

def _f(df): return apply_filters(df) if not df.empty else df


# ── Load data once ────────────────────────────────────────────────────────────
with st.spinner("Loading data…"):
    df_all = compute_all_rankings()
    df_tr  = compute_tracked_rankings()


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED VISUAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_GOOD_LOW = {
    "DRtg","Opp eFG%","Opp TS%","TOV%","TOV/G","PA/G",
    "Worst Loss","L","Opp PPP","TOV/Poss","Avg Poss (s)",
    "Opp FT Rate","Q4 PA/G","Unast%",
}
_GRADIENT_COLS = {
    "W%","PPG","PA/G","Diff","SOS","SOR","Power Score",
    "ORtg","DRtg","Net Rtg","eFG%","Opp eFG%","TS%","Opp TS%",
    "TOV%","OREB%","DREB%","FG%","2P%","3P%","FT%","FT Rate","Opp FT Rate",
    "AST/G","STL/G","BLK/G","TOV/G","BLK Rate","STL Rate",
    "AST/TOV","Opp TOV%","Ast%","Unast%",
    "Paint FG%","Paint Pts/G","Pts from 2%","Pts from 3%","Pts from FT%",
    "Q4 Pts/G","Q4 PA/G","Q4 Diff",
    "PPP","Opp PPP","TOV/Poss",
}

def _apply_grads(styler, cols):
    for c in cols:
        if c not in styler.data.columns: continue
        if not pd.api.types.is_numeric_dtype(styler.data[c]): continue
        if c in ("Rank","GP","W","L","Best Win","Worst Loss"): continue
        try:
            styler = styler.background_gradient(
                subset=[c], cmap="RdYlGn_r" if c in _GOOD_LOW else "RdYlGn", axis=0)
        except Exception:
            pass
    return styler

def show_table(df, display_cols, sort_default, use_gradients=True):
    # Use a session-state counter so widget keys are stable across reruns
    _k = "_tbl_counter"
    st.session_state[_k] = st.session_state.get(_k, 0) + 1
    uid = st.session_state[_k]
    if df.empty: st.info("No data available."); return
    filtered = apply_filters(df)
    if filtered.empty: st.info("No teams match the filters."); return
    sort_col = st.selectbox("Sort by", display_cols,
                             index=display_cols.index(sort_default)
                             if sort_default in display_cols else 0,
                             key=f"sort_{uid}_{sort_default}")
    asc = sort_col in _GOOD_LOW or sort_col == "Rank"
    out = filtered[display_cols].sort_values(sort_col, ascending=asc).reset_index(drop=True)
    out.index += 1
    if use_gradients:
        grad_targets = [c for c in display_cols if c in _GRADIENT_COLS]
        styler = out.style.set_properties(**{"font-size":"13px"})
        styler = _apply_grads(styler, grad_targets)
        st.dataframe(styler, use_container_width=True)
    else:
        st.dataframe(out, use_container_width=True)

def show_class_breakdown(df, display_cols):
    if df.empty: return
    filtered = apply_filters(df)
    for cls in CLASS_ORDER:
        cls_df = filtered[filtered["Class"]==cls]
        if cls_df.empty: continue
        with st.expander(f"Class {cls}  ({len(cls_df)} teams)"):
            out = cls_df[display_cols].sort_values("Power Score",ascending=False).reset_index(drop=True)
            out.index += 1
            grad_targets = [c for c in display_cols if c in _GRADIENT_COLS]
            styler = out.style.set_properties(**{"font-size":"13px"})
            styler = _apply_grads(styler, grad_targets)
            st.dataframe(styler, use_container_width=True)

def show_power_chart(df, title, n=20):
    fdf = _f(df)
    if fdf.empty: return
    top = fdf.nsmallest(min(n,len(fdf)),"Rank").sort_values("Rank",ascending=False)
    hover = {"Net Rtg":":.1f"} if "Net Rtg" in top.columns else {}
    fig = px.bar(top, x="Power Score", y="Team", orientation="h",
                 color="Power Score", color_continuous_scale=_RYG, text="Power Score",
                 hover_data={"Class":True,"W":True,"L":True,"W%":":.1f",
                             "Diff":":.1f","Power Score":":.1f",**hover},
                 title=title)
    fig.update_traces(textposition="outside", texttemplate="%{text:.1f}", textfont_size=11)
    fig.update_layout(height=max(380,len(top)*30+80), coloraxis_showscale=False,
                      yaxis_title="", xaxis_title="Power Score (0–100)",
                      xaxis=dict(range=[0,112],gridcolor="rgba(128,128,128,0.15)"),
                      margin=dict(l=10,r=70,t=50,b=20),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(size=12))
    st.plotly_chart(fig, use_container_width=True)

def show_net_rtg_chart(df):
    fdf = _f(df)
    if fdf.empty or "Net Rtg" not in fdf.columns: return
    sdf = fdf.sort_values("Net Rtg",ascending=True)
    colors = ["#1a9850" if v>=0 else "#d73027" for v in sdf["Net Rtg"]]
    fig = go.Figure(go.Bar(x=sdf["Net Rtg"], y=sdf["Team"], orientation="h",
                            marker_color=colors,
                            text=sdf["Net Rtg"].apply(lambda v:f"{v:+.1f}"),
                            textposition="outside",
                            hovertemplate="%{y}<br>Net Rtg: %{x:+.1f}<extra></extra>"))
    fig.add_vline(x=0, line_color="rgba(180,180,180,0.8)", line_width=1.5)
    fig.update_layout(title="Net Rating (ORtg − DRtg)",
                      height=max(380,len(sdf)*26+80),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10,r=70,t=50,b=20),
                      xaxis=dict(gridcolor="rgba(128,128,128,0.15)"), font=dict(size=11))
    st.plotly_chart(fig, use_container_width=True)

def show_stat_leaders(df, stats):
    fdf = _f(df)
    if fdf.empty: return
    medals = ["🥇","🥈","🥉"," 4."," 5."]
    cols = st.columns(len(stats))
    for col,(stat,label,hib) in zip(cols,stats):
        if stat not in fdf.columns: continue
        sub = fdf[["Team","Class","GP",stat]].dropna()
        if sub.empty: continue
        top5 = sub.nlargest(5,stat) if hib else sub.nsmallest(5,stat)
        with col:
            st.markdown(f"**{label}**")
            for i,(_,row) in enumerate(top5.iterrows()):
                val = row[stat]
                fmt = (f"{val:+.1f}" if stat in ("Diff","Net Rtg","Q4 Diff")
                       else f"{val:.1f}" if isinstance(val,float) else str(val))
                st.markdown(f"{medals[i]} **{row['Team']}** `{row['Class']}`  {fmt}")

def show_scoring_dist_chart(df):
    fdf = _f(df)
    if fdf.empty or "Pts from 2%" not in fdf.columns: return
    sdf = fdf.sort_values("Power Score",ascending=False).head(20)
    fig = go.Figure()
    for col,color,lbl in [("Pts from 2%","#2166ac","2PT %"),
                           ("Pts from 3%","#1a9850","3PT %"),
                           ("Pts from FT%","#d73027","FT %")]:
        fig.add_trace(go.Bar(name=lbl, x=sdf["Team"], y=sdf[col],
                             marker_color=color,
                             hovertemplate="%{x}<br>"+lbl+": %{y:.1f}%<extra></extra>"))
    fig.update_layout(barmode="stack", title="Scoring Sources — Top 20",
                      yaxis_title="% of Points", height=380,
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=20,r=20,t=50,b=80),
                      legend=dict(orientation="h",y=1.08),
                      xaxis=dict(tickangle=-40), font=dict(size=11))
    st.plotly_chart(fig, use_container_width=True)

def show_team_radar(df, radar_stats, key="radar"):
    fdf = _f(df)
    if fdf.empty: return
    team_names = sorted(fdf["Team"].tolist())
    selected = st.multiselect("Compare teams on radar (2–5)",team_names,max_selections=5,key=key)
    if not selected:
        st.caption("Select teams above to compare stats visually."); return
    cats = [l for _,l,_ in radar_stats]
    cols = [c for c,_,_ in radar_stats]
    hibs = [h for _,_,h in radar_stats]
    normed = {}
    for c,hib in zip(cols,hibs):
        s = fdf[c]; lo,hi = s.min(),s.max()
        normed[c] = (((s-lo)/(hi-lo) if hi!=lo else pd.Series(0.5,index=fdf.index))
                     .apply(lambda v: v if hib else 1-v)*100)
    palette = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd"]
    fig = go.Figure()
    for i,team in enumerate(selected):
        row = fdf[fdf["Team"]==team]
        if row.empty: continue
        idx = row.index[0]
        nv  = [normed[c][idx] for c in cols]
        rv  = [row[c].values[0] for c in cols]
        hl  = "<br>".join(f"{cat}: {rv_:.1f}" for cat,rv_ in zip(cats,rv))
        color = palette[i%len(palette)]
        fig.add_trace(go.Scatterpolar(r=nv+[nv[0]],theta=cats+[cats[0]],
            fill="toself",fillcolor=color,line=dict(color=color,width=2),
            opacity=0.25,name=team,
            hovertemplate=f"<b>{team}</b><br>{hl}<extra></extra>"))
        fig.add_trace(go.Scatterpolar(r=nv+[nv[0]],theta=cats+[cats[0]],
            mode="lines+markers",line=dict(color=color,width=2),
            marker=dict(size=6,color=color),showlegend=False,hoverinfo="skip"))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True,range=[0,100],showticklabels=False,
                                   gridcolor="rgba(150,150,150,0.25)"),
                   angularaxis=dict(tickfont=dict(size=11)),bgcolor="rgba(0,0,0,0)"),
        showlegend=True, height=460,
        margin=dict(l=50,r=50,t=60,b=50), paper_bgcolor="rgba(0,0,0,0)",
        title="Team Comparison — normalized vs filter set (100 = best)",
        font=dict(size=11), legend=dict(orientation="h",y=-0.08))
    st.plotly_chart(fig, use_container_width=True)

def show_four_factors_chart(df):
    fdf = _f(df)
    if fdf.empty or "eFG%" not in fdf.columns: return
    ranked_teams  = fdf.sort_values("Power Score",ascending=False)["Team"].tolist()
    default_teams = ranked_teams[:15]
    selected = st.multiselect("Teams to include",options=ranked_teams,
                               default=default_teams, key="ff_team_picker",
                               help="Leave blank to reset to top 15 by Power Score.")
    teams_to_show = selected if selected else default_teams
    sdf = fdf[fdf["Team"].isin(teams_to_show)].sort_values("Power Score",ascending=False)
    if sdf.empty: st.info("No data for selected teams."); return
    cats = ["eFG%","TOV% (inv)","OREB%","FT Rate",
            "Opp eFG% (inv)","Opp TOV%","DREB%","Opp FT Rate (inv)"]
    factor_cfg = [("eFG%",True),("TOV%",False),("OREB%",True),("FT Rate",True),
                  ("Opp eFG%",False),("Opp TOV%",True),("DREB%",True),("Opp FT Rate",False)]
    def pct(col, hib):
        lo,hi = sdf[col].min(),sdf[col].max()
        if hi==lo: return 50.0
        try:
            v = sdf.loc[sdf["Team"]==team_name, col].values[0]
        except Exception: return 0.0
        return ((v-lo)/(hi-lo) if hib else 1-(v-lo)/(hi-lo))*100
    palette = px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
    n_teams = len(sdf)
    fig = go.Figure()
    for i, row in enumerate(sdf.itertuples()):
        team_name = row.Team
        vals  = [pct(col,hib) for col,hib in factor_cfg]
        color = palette[i%len(palette)]
        opa   = max(0.12, 0.45 - n_teams*0.015)
        hl    = "<br>".join(
            f"{cats[j]}: {sdf.loc[sdf['Team']==team_name, col].values[0]:.1f}"
            for j,(col,_) in enumerate(factor_cfg) if col in sdf.columns)
        fig.add_trace(go.Scatterpolar(r=vals+[vals[0]],theta=cats+[cats[0]],
            name=team_name, fill="toself", line=dict(color=color,width=2),
            opacity=opa, hovertemplate=f"<b>{team_name}</b><br>{hl}<extra></extra>"))
        fig.add_trace(go.Scatterpolar(r=vals+[vals[0]],theta=cats+[cats[0]],
            mode="lines",line=dict(color=color,width=2),showlegend=False,hoverinfo="skip"))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0,100],showticklabels=False,
                                   gridcolor="rgba(150,150,150,0.2)"),
                   angularaxis=dict(tickfont=dict(size=11)),bgcolor="rgba(0,0,0,0)"),
        showlegend=True, height=520, paper_bgcolor="rgba(0,0,0,0)",
        title=f"Four Factors Radar — {n_teams} team{'s' if n_teams!=1 else ''} (normalized within selection)",
        legend=dict(orientation="h",y=-0.15,font=dict(size=9)),
        margin=dict(l=50,r=50,t=70,b=100))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("100 = best among shown teams · inverted axes: lower raw = higher score for TOV, Opp eFG%, Opp FT Rate")


# ══════════════════════════════════════════════════════════════════════════════
#  COLUMN PRESETS
# ══════════════════════════════════════════════════════════════════════════════

ALL_COLS          = ["Rank","Team","Class","Gender","GP","W","L","W%",
                     "PPG","PA/G","Diff","SOS","SOR",
                     "Home","Away","Best Win","Worst Loss","Streak","Power Score"]
CORE_COLS         = ["Rank","Team","Class","Gender","GP","W","L","W%",
                     "PPG","PA/G","Diff","SOS","SOR","Home","Away","Streak","Power Score"]
EFF_COLS          = ["Rank","Team","Class","Gender","GP",
                     "ORtg","DRtg","Net Rtg","Pace",
                     "eFG%","Opp eFG%","TS%","Opp TS%",
                     "TOV%","OREB%","DREB%","AST/TOV","Power Score"]
SHOOT_COLS        = ["Rank","Team","Class","Gender","GP",
                     "FG%","2P%","eFG%","TS%","3P%","FT%",
                     "3PAr","FT Rate","Ast%","Unast%",
                     "Paint FG%","Paint Pts/G",
                     "Pts from 2%","Pts from 3%","Pts from FT%","Power Score"]
MISC_COLS         = ["Rank","Team","Class","Gender","GP",
                     "AST/G","STL/G","BLK/G","TOV/G","OREB/G","DREB/G",
                     "BLK Rate","STL Rate","AST/TOV",
                     "Q4 Pts/G","Q4 PA/G","Q4 Diff",
                     "Best Win","Worst Loss","Streak","Power Score"]
POSS_COLS         = ["Rank","Team","Class","Gender","GP",
                     "Poss/G","PPP","Opp PPP","Avg Poss (s)",
                     "TOV/Poss","AST/Poss","OREB%","DREB%","FT Rate","Power Score"]
FOUR_FACTORS_COLS = ["Rank","Team","Class","Gender","GP",
                     "eFG%","TOV%","OREB%","FT Rate",
                     "Opp eFG%","Opp TOV%","DREB%","Opp FT Rate","Power Score"]
DEFENSE_COLS      = ["Rank","Team","Class","Gender","GP",
                     "DRtg","Opp eFG%","Opp TS%","Opp TOV%","Opp FT Rate",
                     "DREB%","BLK Rate","STL Rate","Power Score"]


# ══════════════════════════════════════════════════════════════════════════════
#  TOP-LEVEL TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_dash, tab_rank, tab_teams, tab_matchup, tab_games = st.tabs([
    "🏠 League Overview",
    "🏆 Power Rankings",
    "📋 Teams & Schedules",
    "⚔️ Matchup",
    "🎮 Games",
])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

with tab_dash:
    fdf_all = _f(df_all)
    fdf_tr  = _f(df_tr)

    # ── League Pulse ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">League Pulse</div>', unsafe_allow_html=True)
    m1,m2,m3,m4,m5 = st.columns(5)
    total_teams  = len(fdf_all) if not fdf_all.empty else 0
    total_games  = int(fdf_all["GP"].sum()//2) if not fdf_all.empty else 0
    tracked_g    = int(fdf_tr["GP"].sum()//2) if not fdf_tr.empty else 0
    avg_ppg      = f"{fdf_all['PPG'].mean():.1f}" if not fdf_all.empty else "—"
    avg_diff_tr  = (f"{fdf_tr['Net Rtg'].mean():+.1f}"
                    if not fdf_tr.empty and "Net Rtg" in fdf_tr.columns else "—")

    m1.metric("Teams", total_teams)
    m2.metric("Total Games", total_games)
    m3.metric("Tracked", tracked_g)
    m4.metric("Avg Scoring", avg_ppg + " PPG")
    m5.metric("Avg Net Rtg", avg_diff_tr)

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
            t1_win = g["home_score"] > g["away_score"]
            s1_cls = "score-winner" if t1_win else "score-loser"
            s2_cls = "score-winner" if not t1_win else "score-loser"
            tracked_lbl = "📊 TRACKED" if g["tracked"] else "FINAL"
            try:
                d = datetime.strptime(g["date"],"%Y-%m-%d").strftime("%b %d")
            except Exception:
                d = g["date"] or "—"
            card_html = f"""
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
            </div>"""
            cols_rc[i % 4].markdown(card_html, unsafe_allow_html=True)

    st.divider()

    # ── Top Teams + Efficiency Scatter ────────────────────────────────────────
    left_col, right_col = st.columns([1, 2])

    with left_col:
        st.markdown('<div class="section-hdr">Power Rankings</div>', unsafe_allow_html=True)
        if not fdf_all.empty:
            top_n = fdf_all.sort_values("Power Score",ascending=False).head(10)
            for i, (_, row) in enumerate(top_n.iterrows()):
                rk = i + 1
                badge_cls = {1:"rank-1", 2:"rank-2", 3:"rank-3"}.get(rk, "rank-n")
                rec  = f"{int(row['W'])}-{int(row['L'])}"
                ps   = f"{row['Power Score']:.1f}"
                streak_txt = row.get("Streak","")
                st.markdown(f"""
                <div class="rank-card">
                  <div class="rank-badge {badge_cls}">{rk}</div>
                  <div>
                    <div class="rank-team">{row['Team']}</div>
                    <div class="rank-rec">{row['Class']} · {rec}
                      {"· <b style='color:#2ecc71'>"+streak_txt+"</b>"
                       if str(streak_txt).startswith("W") else
                       "· <b style='color:#e74c3c'>"+str(streak_txt)+"</b>"
                       if str(streak_txt).startswith("L") else ""}</div>
                  </div>
                  <div class="rank-ps">{ps}</div>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No ranking data yet.")

    with right_col:
        if not fdf_tr.empty and "ORtg" in fdf_tr.columns and len(fdf_tr) >= 2:
            st.markdown('<div class="section-hdr">Offensive vs Defensive Rating</div>',
                        unsafe_allow_html=True)
            show_efficiency_scatter(fdf_tr, title="")
        elif not fdf_all.empty:
            st.markdown('<div class="section-hdr">Scoring Distribution</div>',
                        unsafe_allow_html=True)
            show_power_chart(fdf_all, "Power Rankings", n=15)

    st.divider()

    # ── Team Stat Leaders ────────────────────────────────────────────────────
    st.markdown('<div class="section-hdr">Team Leaders</div>', unsafe_allow_html=True)
    src_df = fdf_tr if (not fdf_tr.empty and "Net Rtg" in fdf_tr.columns) else fdf_all

    def _team_leader_card(df, stat, label, hib=True, fmt=".1f"):
        if df.empty or stat not in df.columns: return ""
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
        (src_df, "PPG",      "Points Per Game",   True,  ".1f"),
        (src_df, "PA/G",     "Best Defense",      False, ".1f"),
        (src_df, "Diff",     "Point Differential",True,  "+.1f"),
        (fdf_tr, "eFG%",     "eFG%",              True,  ".1f"),
        (fdf_tr, "Net Rtg",  "Net Rating",        True,  "+.1f"),
    ]
    for c, (df_c, stat, lbl, hib, fmt_) in zip(tl_cols, cards):
        card = _team_leader_card(df_c, stat, lbl, hib, fmt_)
        c.markdown(card, unsafe_allow_html=True)

    # ── Hot / Cold Teams ─────────────────────────────────────────────────────
    if not fdf_all.empty and "Streak" in fdf_all.columns:
        st.divider()
        st.markdown('<div class="section-hdr">Hot & Cold</div>', unsafe_allow_html=True)
        hc1, hc2 = st.columns(2)
        # Hot: W streak
        hot_df = fdf_all[fdf_all["Streak"].str.startswith("W", na=False)].copy()
        hot_df["StreakN"] = hot_df["Streak"].str[1:].apply(
            lambda x: int(x) if x.isdigit() else 0)
        hot_df = hot_df.nlargest(5, "StreakN")
        with hc1:
            st.markdown("🔥 **Win Streaks**")
            for _, row in hot_df.iterrows():
                st.markdown(f"**{row['Team']}** `{row['Class']}`  "
                            f"<span style='color:#2ecc71;font-weight:700'>{row['Streak']}</span>  "
                            f"({int(row['W'])}-{int(row['L'])})",
                            unsafe_allow_html=True)
        # Cold: L streak
        cold_df = fdf_all[fdf_all["Streak"].str.startswith("L", na=False)].copy()
        cold_df["StreakN"] = cold_df["Streak"].str[1:].apply(
            lambda x: int(x) if x.isdigit() else 0)
        cold_df = cold_df.nlargest(5, "StreakN")
        with hc2:
            st.markdown("🧊 **Losing Streaks**")
            for _, row in cold_df.iterrows():
                st.markdown(f"**{row['Team']}** `{row['Class']}`  "
                            f"<span style='color:#e74c3c;font-weight:700'>{row['Streak']}</span>  "
                            f"({int(row['W'])}-{int(row['L'])})",
                            unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — POWER RANKINGS
# ══════════════════════════════════════════════════════════════════════════════

with tab_rank:
    sub_core, sub_eff, sub_shoot, sub_misc, sub_poss, sub_ff, sub_def = st.tabs([
        "📋 Core", "⚡ Efficiency", "🎯 Shooting",
        "📈 Per Game", "🔄 Possession", "♣ Four Factors", "🛡 Defense",
    ])

    # ── Core ─────────────────────────────────────────────────────────────────
    with sub_core:
        fdf_all2 = _f(df_all)
        if not fdf_all2.empty:
            best = fdf_all2.loc[fdf_all2["Power Score"].idxmax()]
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Teams",      len(fdf_all2))
            c2.metric("Games",      int(fdf_all2["GP"].sum()//2))
            c3.metric("#1 Overall", best["Team"],
                      f"PS {best['Power Score']:.1f} · {best['Class']}")
            c4.metric("Avg PPG",    f"{fdf_all2['PPG'].mean():.1f}")
            c5.metric("Avg Margin", f"{fdf_all2['Diff'].mean():+.1f}")
        st.divider()
        ch_col, ld_col = st.columns([3,2])
        with ch_col:
            show_power_chart(df_all, "Power Rankings — All Games", n=20)
        with ld_col:
            st.markdown("#### Stat Leaders")
            show_stat_leaders(df_all,[
                ("Power Score","Power Score",True),
                ("W%","Win %",True),
                ("PPG","Scoring",True),
                ("SOR","Str. of Record",True),
                ("Diff","Point Diff",True),
            ])
        st.divider()
        st.subheader("All Games Rankings")
        show_table(df_all, ALL_COLS, "Rank")
        st.subheader("By Class")
        show_class_breakdown(df_all, ALL_COLS)
        with st.expander("Team Comparison Radar"):
            show_team_radar(df_all,[
                ("_wp","Win %",True),("_sor","Str. of Record",True),
                ("PPG","PPG",True),("PA/G","PA/G",False),
                ("_diff","Margin",True),("_sos","Sched. Strength",True),
            ], key="radar_core_all")
        with st.expander("📖 Glossary"):
            st.markdown("""
| Stat | Meaning |
|------|---------|
| **W%** | Win percentage |
| **PPG / PA/G** | Points per game scored / allowed |
| **Diff** | Average scoring margin |
| **SOS** | Strength of Schedule — avg win% of opponents |
| **SOR** | Strength of Record — weighted win%, weighting quality of wins |
| **Power Score** | Composite: 35% SOR · 30% W% · 20% Diff · 15% SOS |
""")

    # ── Efficiency ───────────────────────────────────────────────────────────
    with sub_eff:
        fdf_tr2 = _f(df_tr)
        if not fdf_tr2.empty and "ORtg" in fdf_tr2.columns:
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Tracked Games", int(fdf_tr2["GP"].sum()//2))
            best_n = fdf_tr2.loc[fdf_tr2["Net Rtg"].idxmax()]
            m2.metric("Best Net Rtg", best_n["Team"], f"{best_n['Net Rtg']:+.1f}")
            best_o = fdf_tr2.loc[fdf_tr2["ORtg"].idxmax()]
            m3.metric("Best ORtg", best_o["Team"], f"{best_o['ORtg']:.1f}")
            best_d = fdf_tr2.loc[fdf_tr2["DRtg"].idxmin()]
            m4.metric("Best DRtg", best_d["Team"], f"{best_d['DRtg']:.1f}")
            st.divider()

        st.subheader("Offensive vs Defensive Rating")
        st.caption("Top-right = elite: high offense + lower defensive rating (shown at top due to Y-axis flip)")
        show_efficiency_scatter(_f(df_tr))
        st.divider()

        nc_col, ld2_col = st.columns([3,2])
        with nc_col:
            show_net_rtg_chart(df_tr)
        with ld2_col:
            st.markdown("#### Efficiency Leaders")
            show_stat_leaders(df_tr,[
                ("Net Rtg","Net Rating",True),
                ("ORtg","Best ORtg",True),
                ("DRtg","Best DRtg",False),
                ("TS%","True Shoot%",True),
                ("AST/TOV","AST/TOV",True),
            ])
        st.divider()
        st.subheader("Efficiency Table")
        show_table(df_tr, EFF_COLS, "Net Rtg")
        st.subheader("By Class")
        show_class_breakdown(df_tr, EFF_COLS)
        with st.expander("Team Comparison Radar"):
            show_team_radar(df_tr,[
                ("ORtg","Off Rtg",True),("DRtg","Def Rtg",False),
                ("TS%","TS%",True),("OREB%","OREB%",True),
                ("TOV%","TOV%",False),("AST/TOV","AST/TOV",True),
            ], key="radar_eff")
        with st.expander("📖 Glossary"):
            st.markdown("""
| Stat | Meaning |
|------|---------|
| **ORtg** | Offensive Rating — points scored per 100 possessions |
| **DRtg** | Defensive Rating — points allowed per 100 possessions (lower = better) |
| **Net Rtg** | ORtg − DRtg |
| **Pace** | Estimated possessions per game |
| **eFG%** | (FGM + 0.5×3PM) / FGA |
| **TS%** | PTS / (2×(FGA + 0.44×FTA)) |
| **TOV%** | Turnovers per possession |
| **AST/TOV** | Assist-to-turnover ratio |
""")

    # ── Shooting ─────────────────────────────────────────────────────────────
    with sub_shoot:
        show_scoring_dist_chart(df_tr)
        st.divider()
        show_stat_leaders(df_tr,[
            ("TS%","True Shoot%",True),("eFG%","eFG%",True),
            ("2P%","2PT%",True),("3P%","3PT%",True),("Paint Pts/G","Paint Pts/G",True),
        ])
        st.divider()
        st.subheader("Shooting Table")
        show_table(df_tr, SHOOT_COLS, "TS%")
        st.subheader("By Class")
        show_class_breakdown(df_tr, SHOOT_COLS)
        with st.expander("Team Comparison Radar"):
            show_team_radar(df_tr,[
                ("TS%","TS%",True),("eFG%","eFG%",True),
                ("FG%","FG%",True),("2P%","2P%",True),
                ("3P%","3P%",True),("FT%","FT%",True),
            ], key="radar_shoot")

    # ── Per Game / Misc ───────────────────────────────────────────────────────
    with sub_misc:
        show_stat_leaders(df_tr,[
            ("Q4 Diff","Q4 Net Diff",True),("Q4 Pts/G","Q4 Scoring",True),
            ("Q4 PA/G","Q4 Defense",False),("BLK Rate","BLK Rate",True),
            ("STL Rate","STL Rate",True),
        ])
        st.divider()
        st.subheader("Per Game / Misc Table")
        show_table(df_tr, MISC_COLS, "STL/G")
        st.subheader("By Class")
        show_class_breakdown(df_tr, MISC_COLS)
        with st.expander("Team Comparison Radar"):
            show_team_radar(df_tr,[
                ("AST/G","AST/G",True),("STL/G","STL/G",True),
                ("BLK/G","BLK/G",True),("TOV/G","TOV/G",False),
                ("BLK Rate","BLK Rate",True),("STL Rate","STL Rate",True),
            ], key="radar_misc")

    # ── Possession ────────────────────────────────────────────────────────────
    with sub_poss:
        show_stat_leaders(df_tr,[
            ("PPP","Pts/Poss",True),("Opp PPP","Opp Pts/Poss",False),
            ("Poss/G","Poss/G",True),("TOV/Poss","TOV/Poss",False),
            ("AST/Poss","AST/Poss",True),
        ])
        st.divider()
        st.subheader("Possession Table")
        show_table(df_tr, POSS_COLS, "PPP")
        st.subheader("By Class")
        show_class_breakdown(df_tr, POSS_COLS)

    # ── Four Factors ──────────────────────────────────────────────────────────
    with sub_ff:
        st.subheader("Dean Oliver's Four Factors")
        st.caption("Shooting (40%) · Ball Security (25%) · Off. Rebounding (20%) · FT Rate (15%)")
        show_four_factors_chart(df_tr)
        st.divider()
        ff1,ff2,ff3,ff4 = st.columns(4)
        with ff1:
            st.markdown("**Shooting (eFG%)**")
            show_stat_leaders(df_tr,[("eFG%","eFG%",True)])
        with ff2:
            st.markdown("**Ball Security (TOV%)**")
            show_stat_leaders(df_tr,[("TOV%","TOV%",False)])
        with ff3:
            st.markdown("**Off. Rebounding**")
            show_stat_leaders(df_tr,[("OREB%","OREB%",True)])
        with ff4:
            st.markdown("**FT Rate**")
            show_stat_leaders(df_tr,[("FT Rate","FT Rate",True)])
        st.divider()
        st.markdown("#### Defensive Four Factors")
        dff1,dff2,dff3,dff4 = st.columns(4)
        with dff1:
            st.markdown("**Opp eFG%**")
            show_stat_leaders(df_tr,[("Opp eFG%","Opp eFG%",False)])
        with dff2:
            st.markdown("**Force TOs**")
            show_stat_leaders(df_tr,[("Opp TOV%","Opp TOV%",True)])
        with dff3:
            st.markdown("**Def. Rebounding**")
            show_stat_leaders(df_tr,[("DREB%","DREB%",True)])
        with dff4:
            st.markdown("**Foul Discipline**")
            show_stat_leaders(df_tr,[("Opp FT Rate","Opp FT Rate",False)])
        st.divider()
        st.subheader("Four Factors Table")
        show_table(df_tr, FOUR_FACTORS_COLS, "eFG%")
        st.subheader("By Class")
        show_class_breakdown(df_tr, FOUR_FACTORS_COLS)

    # ── Defense ───────────────────────────────────────────────────────────────
    with sub_def:
        fdf_def = _f(df_tr)
        d_chart, d_ld = st.columns([3,2])
        with d_chart:
            if not fdf_def.empty and "DRtg" in fdf_def.columns:
                sdf_d = fdf_def.sort_values("DRtg",ascending=True).head(20)
                fig_d = px.bar(sdf_d, x="DRtg", y="Team", orientation="h",
                               color="DRtg", color_continuous_scale=_RYG_R,
                               text="DRtg",
                               hover_data={"Opp eFG%":":.1f","Opp TOV%":":.1f",
                                           "DREB%":":.1f","BLK Rate":":.1f"},
                               title="Best Defenses (lower DRtg = better)")
                fig_d.update_traces(textposition="outside",texttemplate="%{text:.1f}",
                                    textfont_size=11)
                fig_d.update_layout(height=max(380,len(sdf_d)*30+80),
                                    coloraxis_showscale=False,
                                    plot_bgcolor="rgba(0,0,0,0)",
                                    paper_bgcolor="rgba(0,0,0,0)",
                                    margin=dict(l=10,r=70,t=50,b=20), font=dict(size=12))
                st.plotly_chart(fig_d, use_container_width=True)
        with d_ld:
            st.markdown("#### Defensive Leaders")
            show_stat_leaders(df_tr,[
                ("DRtg","Best DRtg",False),("Opp eFG%","Opp eFG%",False),
                ("Opp TOV%","Force TOs",True),("BLK Rate","BLK Rate",True),
                ("STL Rate","STL Rate",True),
            ])
        st.divider()
        st.subheader("Defense Table")
        show_table(df_tr, DEFENSE_COLS, "DRtg")
        st.subheader("By Class")
        show_class_breakdown(df_tr, DEFENSE_COLS)
        with st.expander("Team Comparison Radar"):
            show_team_radar(df_tr,[
                ("DRtg","Def Rtg",False),("Opp eFG%","Opp eFG%",False),
                ("Opp TOV%","Force TOs",True),("DREB%","DREB%",True),
                ("BLK Rate","BLK Rate",True),("STL Rate","STL Rate",True),
            ], key="radar_def")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — TEAMS & SCHEDULES
# ══════════════════════════════════════════════════════════════════════════════

# Wrap in a fragment so the team selectbox reruns only this section,
# leaving the parent tab bar untouched.
@st.fragment
def _render_teams_tab():
    # Extra CSS for the OSSAA-style table
    st.markdown("""
<style>
.ts-table { width:100%; border-collapse:collapse; font-size:13px; }
.ts-table th {
    background:#1c2128; color:#8b949e; font-size:10px; text-transform:uppercase;
    letter-spacing:1px; padding:7px 10px; border-bottom:1px solid #30363d;
    text-align:left;
}
.ts-table td { padding:7px 10px; border-bottom:1px solid #21262d; color:#c9d1d9; }
.ts-table tr:hover td { background:rgba(255,255,255,0.04); }
.ts-rank   { font-weight:800; color:#f0a500; width:36px; text-align:center; }
.ts-team   { font-weight:700; color:#f0f6fc; }
.ts-sub    { font-size:11px; color:#8b949e; }
.ts-ps     { font-weight:700; color:#58a6ff; text-align:right; }
.ts-w      { color:#2ecc71; font-weight:700; }
.ts-l      { color:#e74c3c; font-weight:700; }
.sched-row { display:flex; align-items:center; gap:10px; padding:8px 4px;
             border-bottom:1px solid #21262d; font-size:13px; }
.sched-date { color:#8b949e; font-size:11px; min-width:70px; }
.sched-opp  { flex:1; color:#c9d1d9; font-weight:600; }
.sched-loc  { font-size:11px; color:#8b949e; min-width:36px; }
.sched-res-W{ font-weight:800; color:#2ecc71; min-width:14px; }
.sched-res-L{ font-weight:800; color:#e74c3c; min-width:14px; }
.sched-score{ font-weight:700; min-width:65px; }
.sched-rec  { font-size:11px; color:#8b949e; min-width:50px; }
.sched-trk  { font-size:10px; color:#f0a500; }
.rec-pill {
    display:inline-block; background:#161b22; border:1px solid #30363d;
    border-radius:6px; padding:3px 10px; margin:3px 4px 3px 0;
    font-size:12px; color:#c9d1d9;
}
.rec-pill b { color:#f0f6fc; }
.rec-pill span { color:#8b949e; }
</style>
""", unsafe_allow_html=True)

    from collections import defaultdict as _dd_ts

    # ── Load all games once ───────────────────────────────────────────────────
    sched_all = query("""
        SELECT g.id, g.date, g.home_score, g.away_score, g.tracked,
               t1.id AS t1id, t1.name AS t1, t1.class AS c1,
               t2.id AS t2id, t2.name AS t2, t2.class AS c2
        FROM games g
        JOIN teams t1 ON t1.id=g.team1_id
        JOIN teams t2 ON t2.id=g.team2_id
        ORDER BY g.date ASC, g.id ASC
    """)

    fdf_ts = _f(df_all)
    if fdf_ts.empty and not sched_all:
        st.info("No data yet.")
    else:
        # ── Two-pane layout: Rankings left | Schedule right ────────────────────
        left_col, right_col = st.columns([2, 3], gap="large")

        # ══ LEFT — Rankings table ═════════════════════════════════════════════
        with left_col:
            st.markdown("#### 🏆 Rankings")

            ranked = fdf_ts.sort_values("Power Score", ascending=False) if not fdf_ts.empty else pd.DataFrame()

            if ranked.empty:
                st.info("No ranking data.")
            else:
                # Build HTML table rows
                rows_html = ""
                for i, (_, row) in enumerate(ranked.iterrows()):
                    rk  = int(row["Rank"]) if "Rank" in row else i + 1
                    rec = f"{int(row['W'])}-{int(row['L'])}"
                    ps  = f"{row['Power Score']:.1f}"
                    cls = row.get("Class", "—")
                    gdr = row.get("Gender", "")
                    nm  = row["Team"]
                    rows_html += (
                        f"<tr>"
                        f"<td class='ts-rank'>{rk}</td>"
                        f"<td><span class='ts-team'>{nm}</span>"
                        f"<br><span class='ts-sub'>{cls}"
                        f"{' · ' + gdr if gdr else ''}</span></td>"
                        f"<td><span class='ts-w'>{int(row['W'])}</span>"
                        f"-<span class='ts-l'>{int(row['L'])}</span></td>"
                        f"<td class='ts-ps'>{ps}</td>"
                        f"</tr>"
                    )

                st.markdown(
                    f"<table class='ts-table'>"
                    f"<thead><tr>"
                    f"<th>#</th><th>Team</th><th>W-L</th><th style='text-align:right'>PS</th>"
                    f"</tr></thead>"
                    f"<tbody>{rows_html}</tbody>"
                    f"</table>",
                    unsafe_allow_html=True,
                )

        # ══ RIGHT — Team schedule ═════════════════════════════════════════════
        with right_col:
            # Team selector — ordered by rank so #1 is default
            if not ranked.empty:
                rank_order = ranked["Team"].tolist()
            elif sched_all:
                rank_order = sorted({g["t1"] for g in sched_all} |
                                    {g["t2"] for g in sched_all})
            else:
                rank_order = []

            if not rank_order:
                st.info("No teams found.")
            else:
                team_sel = st.selectbox(
                    "Select a team to view schedule",
                    rank_order,
                    key="ts_team_sel",
                    label_visibility="collapsed",
                )

                # Filter games for this team (chronological order)
                team_games = [g for g in sched_all
                              if g["t1"] == team_sel or g["t2"] == team_sel]

                if not team_games:
                    st.info(f"No games found for {team_sel}.")
                else:
                    # ── Compute records ────────────────────────────────────────
                    finished  = [g for g in team_games if g["home_score"] is not None]
                    remaining = [g for g in team_games if g["home_score"] is None]

                    def _won(g):
                        is_h = g["t1"] == team_sel
                        ts   = g["home_score"] if is_h else g["away_score"]
                        os_  = g["away_score"] if is_h else g["home_score"]
                        return ts > os_

                    wins   = sum(1 for g in finished if _won(g))
                    losses = len(finished) - wins

                    home_g   = [g for g in finished if g["t1"] == team_sel]
                    away_g   = [g for g in finished if g["t2"] == team_sel]
                    home_w   = sum(1 for g in home_g if _won(g))
                    away_w   = sum(1 for g in away_g if _won(g))

                    # vs each class
                    class_rec = _dd_ts(lambda: [0, 0])
                    for g in finished:
                        is_h = g["t1"] == team_sel
                        opp_cls = g["c2"] if is_h else g["c1"]
                        if _won(g):
                            class_rec[opp_cls][0] += 1
                        else:
                            class_rec[opp_cls][1] += 1

                    # ── Team header ────────────────────────────────────────────
                    team_row = (ranked[ranked["Team"] == team_sel].iloc[0]
                                if not ranked.empty and team_sel in ranked["Team"].values
                                else None)
                    rk_lbl = f"#{int(team_row['Rank'])}" if team_row is not None else ""
                    ps_lbl = f"PS {team_row['Power Score']:.1f}" if team_row is not None else ""
                    st.markdown(
                        f"<div style='margin-bottom:10px'>"
                        f"<span style='font-size:22px;font-weight:800;color:#f0f6fc'>"
                        f"{team_sel}</span>"
                        f"{'&nbsp;&nbsp;<span style=\"font-size:14px;color:#f0a500;font-weight:700\">' + rk_lbl + '</span>' if rk_lbl else ''}"
                        f"{'&nbsp;&nbsp;<span style=\"font-size:12px;color:#8b949e\">' + ps_lbl + '</span>' if ps_lbl else ''}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    # ── Record pills ───────────────────────────────────────────
                    pills_html = (
                        f"<div style='margin-bottom:12px'>"
                        f"<span class='rec-pill'><b>Overall</b> <span>{wins}-{losses}</span></span>"
                        f"<span class='rec-pill'><b>Home</b> <span>{home_w}-{len(home_g)-home_w}</span></span>"
                        f"<span class='rec-pill'><b>Away</b> <span>{away_w}-{len(away_g)-away_w}</span></span>"
                    )
                    for cls in sorted(class_rec.keys()):
                        cw, cl = class_rec[cls]
                        pills_html += (
                            f"<span class='rec-pill'>"
                            f"<b>vs {cls}</b> <span>{cw}-{cl}</span></span>"
                        )
                    if remaining:
                        pills_html += (
                            f"<span class='rec-pill'>"
                            f"<b>Remaining</b> <span>{len(remaining)}</span></span>"
                        )
                    pills_html += "</div>"
                    st.markdown(pills_html, unsafe_allow_html=True)

                    # ── Schedule table header ──────────────────────────────────
                    st.markdown(
                        "<div style='display:flex;gap:10px;padding:6px 4px;"
                        "border-bottom:2px solid #30363d;font-size:10px;"
                        "color:#8b949e;text-transform:uppercase;letter-spacing:1px;'>"
                        "<span style='min-width:70px'>Date</span>"
                        "<span style='flex:1'>Opponent</span>"
                        "<span style='min-width:36px'>Loc</span>"
                        "<span style='min-width:14px'>Res</span>"
                        "<span style='min-width:65px'>Score</span>"
                        "<span style='min-width:50px'>Record</span>"
                        "</div>",
                        unsafe_allow_html=True,
                    )

                    # ── Schedule rows (chronological) ──────────────────────────
                    running_w, running_l = 0, 0
                    for g in team_games:
                        is_home  = g["t1"] == team_sel
                        opp_name = g["t2"] if is_home else g["t1"]
                        opp_cls  = g["c2"] if is_home else g["c1"]
                        ha_lbl   = "H" if is_home else "A"

                        try:
                            d_fmt = _dt_ts.strptime(g["date"], "%Y-%m-%d").strftime("%m/%d/%y")
                        except Exception:
                            d_fmt = g["date"] or "—"

                        has_score = g["home_score"] is not None

                        if has_score:
                            t_pts = g["home_score"] if is_home else g["away_score"]
                            o_pts = g["away_score"] if is_home else g["home_score"]
                            won   = t_pts > o_pts
                            if won:
                                running_w += 1
                            else:
                                running_l += 1
                            res_cls   = "sched-res-W" if won else "sched-res-L"
                            res_lbl   = "W" if won else "L"
                            score_txt = f"{t_pts}–{o_pts}"
                            rec_txt   = f"{running_w}-{running_l}"
                            trk_badge = "📊" if g["tracked"] else ""

                            row_html = (
                                f"<div class='sched-row'>"
                                f"<span class='sched-date'>{d_fmt}</span>"
                                f"<span class='sched-opp'>{opp_name}"
                                f" <span style='font-size:11px;color:#8b949e'>({opp_cls})</span></span>"
                                f"<span class='sched-loc'>{ha_lbl}</span>"
                                f"<span class='{res_cls}'>{res_lbl}</span>"
                                f"<span class='sched-score'>{score_txt}</span>"
                                f"<span class='sched-rec'>{rec_txt}</span>"
                                f"<span class='sched-trk'>{trk_badge}</span>"
                                f"</div>"
                            )
                            st.markdown(row_html, unsafe_allow_html=True)

                            # Tracked game → inline expander for box score
                            if g["tracked"]:
                                exp_lbl = (
                                    f"{'✅' if won else '❌'} {opp_name} — "
                                    f"{t_pts}–{o_pts}  |  View Box Score"
                                )
                                with st.expander(exp_lbl, expanded=False):
                                    _t1id_s = g["t1id"]
                                    _t2id_s = g["t2id"]
                                    _t1n_s  = g["t1"]
                                    _t2n_s  = g["t2"]
                                    q_data_s = compute_game_quarter_scores(g["id"])
                                    if q_data_s:
                                        _ls_c, _sf_c = st.columns([2, 3])
                                        with _ls_c:
                                            st.markdown("**Linescore**")
                                            _show_linescore(q_data_s, _t1n_s, _t2n_s,
                                                            _t1id_s, _t2id_s)
                                        with _sf_c:
                                            show_score_flow_chart(
                                                g["id"], _t1n_s, _t2n_s,
                                                _t1id_s, _t2id_s,
                                                key=f"flow_ts_{g['id']}")
                                    rows_t1_s, rows_t2_s, gi_s = compute_game_box_score(g["id"])
                                    if any(not r.get("_totals") for r in rows_t1_s + rows_t2_s):
                                        st.divider()
                                        show_game_box_score(rows_t1_s, rows_t2_s, {},
                                                            gi_s, _cfg)
                        else:
                            # Scheduled but not yet played
                            row_html = (
                                f"<div class='sched-row' style='opacity:0.55'>"
                                f"<span class='sched-date'>{d_fmt}</span>"
                                f"<span class='sched-opp'>{opp_name}"
                                f" <span style='font-size:11px;color:#8b949e'>({opp_cls})</span></span>"
                                f"<span class='sched-loc'>{ha_lbl}</span>"
                                f"<span style='font-size:11px;color:#8b949e;flex:1'>Scheduled</span>"
                                f"</div>"
                            )
                            st.markdown(row_html, unsafe_allow_html=True)

    # ── end of Teams & Schedules tab ─────────────────────────────────────────


with tab_teams:
    _render_teams_tab()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — MATCHUP SIMULATOR
# ══════════════════════════════════════════════════════════════════════════════

with tab_matchup:
    st.markdown('<div class="section-hdr">Matchup Simulator</div>', unsafe_allow_html=True)
    st.caption("Pick any two teams to compare their stats head-to-head and see a projected outcome.")

    match_fdf = _f(df_tr) if not df_tr.empty else _f(df_all)
    if match_fdf.empty:
        st.info("No team data available yet.")
    else:
        team_opts = sorted(match_fdf["Team"].tolist())
        mc1, mc2 = st.columns(2)
        match_t1 = mc1.selectbox("Team 1", team_opts, index=0, key="matchup_t1")
        match_t2 = mc2.selectbox("Team 2", team_opts,
                                  index=min(1, len(team_opts)-1), key="matchup_t2")

        if match_t1 == match_t2:
            st.warning("Pick two different teams.")
        else:
            r1 = match_fdf[match_fdf["Team"] == match_t1].iloc[0]
            r2 = match_fdf[match_fdf["Team"] == match_t2].iloc[0]

            # ── Summary metrics ────────────────────────────────────────────────
            st.divider()
            hm1, hm2, hm3, hm4, hm5, hm6 = st.columns(6)
            def _delta(v1, v2, fmt=".1f", hib=True):
                d = v1 - v2
                return f"{d:+{fmt}}" if hib else f"{-d:+{fmt}}"

            hm1.metric(f"{match_t1} Record",
                       f"{int(r1['W'])}-{int(r1['L'])}" if "W" in r1 else "—")
            hm2.metric("Power Score", f"{r1['Power Score']:.1f}",
                       _delta(r1["Power Score"], r2["Power Score"]))
            hm3.metric("PPG", f"{r1['PPG']:.1f}",
                       _delta(r1["PPG"], r2["PPG"]))
            hm4.metric("PA/G", f"{r1['PA/G']:.1f}",
                       _delta(r1["PA/G"], r2["PA/G"], hib=False))
            hm5.metric("Power Score", f"{r2['Power Score']:.1f}",
                       _delta(r2["Power Score"], r1["Power Score"]))
            hm6.metric(f"{match_t2} Record",
                       f"{int(r2['W'])}-{int(r2['L'])}" if "W" in r2 else "—")

            # ── Visual matchup bars ────────────────────────────────────────────
            st.divider()
            show_matchup_bars(r1, r2, match_t1, match_t2)

            # ── Stat comparison table ──────────────────────────────────────────
            st.divider()
            st.markdown("#### Side-by-Side Stats")
            cmp_stats = [
                ("PPG",     "Points/Game",        True),
                ("PA/G",    "Points Allowed/Game", False),
                ("Diff",    "Point Diff",          True),
                ("W%",      "Win %",               True),
                ("SOS",     "Strength of Schedule",True),
            ]
            if "ORtg" in r1:
                cmp_stats += [
                    ("ORtg",    "Off. Rating",     True),
                    ("DRtg",    "Def. Rating",     False),
                    ("Net Rtg", "Net Rating",      True),
                    ("eFG%",    "eFG%",            True),
                    ("TOV%",    "TOV%",            False),
                    ("OREB%",   "Off. Reb %",      True),
                    ("DREB%",   "Def. Reb %",      True),
                    ("FT Rate", "FT Rate",         True),
                ]

            cmp_rows = []
            for col, label, hib in cmp_stats:
                if col not in r1 or col not in r2: continue
                v1, v2 = r1[col], r2[col]
                better1 = v1 >= v2 if hib else v1 <= v2
                cmp_rows.append({
                    match_t1: f"{'✅ ' if better1 else ''}{v1:.1f}",
                    "Stat": label,
                    match_t2: f"{'✅ ' if not better1 else ''}{v2:.1f}",
                })
            if cmp_rows:
                st.dataframe(pd.DataFrame(cmp_rows).set_index("Stat"),
                             use_container_width=True)

            # ── Projected outcome ──────────────────────────────────────────────
            st.divider()
            st.markdown("#### 🔮 Projected Outcome")

            # Try efficiency-based projection first; fall back to Power Score
            _tid_map = {t["name"]: t["id"]
                        for t in query("SELECT id, name FROM teams")}
            _t1_id = _tid_map.get(match_t1)
            _t2_id = _tid_map.get(match_t2)
            _mu = compute_matchup(_t1_id, _t2_id) if (_t1_id and _t2_id) else None

            if _mu and _mu["method"] == "efficiency":
                win_pct1  = _mu["prob_a"] * 100
                win_pct2  = 100 - win_pct1
                proj_sc1  = _mu["proj_a"]
                proj_sc2  = _mu["proj_b"]
                proj_margin = abs(proj_sc1 - proj_sc2)
                fav = match_t1 if proj_sc1 >= proj_sc2 else match_t2
                method_note = "ORtg · DRtg · Pace (tracked data)"
                pr1, pr2, pr3, pr4, pr5 = st.columns(5)
                pr1.metric(f"{match_t1} Win Prob", f"{win_pct1:.0f}%")
                pr2.metric(f"{match_t1} Proj Score", f"{proj_sc1:.1f}")
                pr3.metric("Margin",  f"{proj_margin:.1f} pts", f"Favor: {fav}")
                pr4.metric(f"{match_t2} Proj Score", f"{proj_sc2:.1f}")
                pr5.metric(f"{match_t2} Win Prob", f"{win_pct2:.0f}%")
            else:
                ps1 = r1["Power Score"]
                ps2 = r2["Power Score"]
                total = ps1 + ps2
                win_pct1 = ps1 / total * 100 if total else 50.0
                win_pct2 = 100 - win_pct1
                fav = match_t1 if ps1 >= ps2 else match_t2
                proj_margin = abs(r1["PPG"] - r1["PA/G"]) * abs(ps1 - ps2) / 100
                method_note = "Power Score ratio"
                pr1, pr2, pr3 = st.columns(3)
                pr1.metric(f"{match_t1} Win Prob", f"{win_pct1:.0f}%")
                pr2.metric("Projected Margin", f"{proj_margin:.1f} pts", f"Favor: {fav}")
                pr3.metric(f"{match_t2} Win Prob", f"{win_pct2:.0f}%")

            # Win prob bar
            bar_html = (
                f"<div style='background:#2d333b;border-radius:6px;height:18px;overflow:hidden'>"
                f"<div style='background:#3498db;width:{win_pct1:.0f}%;height:100%;float:left;"
                f"border-radius:6px 0 0 6px'></div>"
                f"<div style='background:#e74c3c;width:{win_pct2:.0f}%;height:100%;float:left;"
                f"border-radius:0 6px 6px 0'></div></div>"
                f"<div style='display:flex;justify-content:space-between;font-size:11px;"
                f"color:#8b949e;margin-top:4px'>"
                f"<span style='color:#3498db;font-weight:700'>{match_t1}</span>"
                f"<span style='color:#e74c3c;font-weight:700'>{match_t2}</span></div>"
            )
            st.markdown(bar_html, unsafe_allow_html=True)
            st.caption(f"Projection method: {method_note}.")

            # ── History vs each other ──────────────────────────────────────────
            st.divider()
            st.markdown("#### 📜 Head-to-Head History")
            h2h_games = query("""
                SELECT g.id, g.date, g.home_score, g.away_score, g.tracked,
                       t1.id AS t1id, t1.name AS t1, t2.id AS t2id, t2.name AS t2
                FROM games g
                JOIN teams t1 ON t1.id=g.team1_id
                JOIN teams t2 ON t2.id=g.team2_id
                WHERE (t1.name=? AND t2.name=?)
                   OR (t1.name=? AND t2.name=?)
                ORDER BY g.date DESC
            """, (match_t1, match_t2, match_t2, match_t1))

            if not h2h_games:
                st.info("These two teams have not played each other yet.")
            else:
                h2h_w1 = sum(1 for g in h2h_games
                             if g["home_score"] is not None
                             and ((g["t1"]==match_t1 and g["home_score"]>g["away_score"])
                                  or (g["t2"]==match_t1 and g["away_score"]>g["home_score"])))
                h2h_w2 = len([g for g in h2h_games if g["home_score"] is not None]) - h2h_w1
                hh1, hh2 = st.columns(2)
                hh1.metric(f"{match_t1} wins", h2h_w1)
                hh2.metric(f"{match_t2} wins", h2h_w2)
                for g in h2h_games:
                    if g["home_score"] is None: continue
                    t1_win = g["home_score"] > g["away_score"]
                    winner = g["t1"] if t1_win else g["t2"]
                    w_sc   = g["home_score"] if t1_win else g["away_score"]
                    l_sc   = g["away_score"] if t1_win else g["home_score"]
                    loser  = g["t2"] if t1_win else g["t1"]
                    tracked_lbl = " 📊" if g["tracked"] else ""
                    try:
                        dl = _dth.strptime(g["date"], "%Y-%m-%d").strftime("%B %d, %Y")
                    except Exception:
                        dl = g["date"] or "—"
                    st.markdown(
                        f"<div class='score-card'>"
                        f"<span style='color:#8b949e;font-size:11px'>{dl}{tracked_lbl}</span><br>"
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




# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — GAMES
# ══════════════════════════════════════════════════════════════════════════════

with tab_games:
    all_games = query("""
        SELECT g.id, g.date, g.home_score, g.away_score, g.tracked,
               t1.name AS t1, t2.name AS t2,
               t1.class AS c1, t2.class AS c2
        FROM games g
        JOIN teams t1 ON t1.id=g.team1_id
        JOIN teams t2 ON t2.id=g.team2_id
        ORDER BY g.date DESC, g.id DESC
    """)

    if not all_games:
        st.info("No games in the database yet.")
    else:
        # Game selector
        def _glabel(g):
            score = (f"  {g['home_score']}-{g['away_score']}"
                     if g["home_score"] is not None else "")
            tracked = " 📊" if g["tracked"] else ""
            return f"{g['date']}  |  {g['t1']} vs {g['t2']}{score}{tracked}"

        game_map = {_glabel(g): g["id"] for g in all_games}
        sel_game_lbl = st.selectbox("Select Game", list(game_map.keys()), key="games_picker")
        sel_game_id  = game_map[sel_game_lbl]

        sel_game     = next(g for g in all_games if g["id"]==sel_game_id)
        t1name       = sel_game["t1"]
        t2name       = sel_game["t2"]
        is_tracked   = bool(sel_game["tracked"])

        # ── Match Header ────────────────────────────────────────────────────
        try:
            date_fmt = _dt.strptime(sel_game["date"],"%Y-%m-%d").strftime("%B %d, %Y")
        except Exception:
            date_fmt = sel_game["date"] or "—"

        _accent = _cfg.get("accent_color", "#f0a500")
        h1, h2, h3 = st.columns([3, 2, 3])
        with h1:
            st.markdown(
                f"<div style='font-size:22px;font-weight:800;color:#f0f6fc'>{t1name}</div>"
                f"<div style='font-size:11px;color:#8b949e;margin-top:2px'>"
                f"Class {sel_game['c1']} · Home</div>",
                unsafe_allow_html=True)
        with h2:
            if sel_game["home_score"] is not None:
                hs, as_ = sel_game["home_score"], sel_game["away_score"]
                h_col = _accent if hs >= as_ else "#8b949e"
                a_col = _accent if as_ > hs  else "#8b949e"
                st.markdown(
                    f"<div style='text-align:center;line-height:1'>"
                    f"<span style='font-size:46px;font-weight:900;color:{h_col}'>{hs}</span>"
                    f"<span style='font-size:28px;font-weight:400;color:#8b949e;margin:0 8px'>–</span>"
                    f"<span style='font-size:46px;font-weight:900;color:{a_col}'>{as_}</span>"
                    f"</div>"
                    f"<div style='text-align:center;font-size:11px;color:#8b949e;margin-top:4px'>"
                    f"{date_fmt}</div>"
                    + (f"<div style='text-align:center;font-size:11px;color:#2ecc71;margin-top:2px'>"
                       f"📊 FINAL</div>" if is_tracked else ""),
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<div style='text-align:center;font-size:20px;color:#8b949e'>"
                    f"vs<br><span style='font-size:11px'>{date_fmt}</span></div>",
                    unsafe_allow_html=True)
        with h3:
            st.markdown(
                f"<div style='font-size:22px;font-weight:800;color:#f0f6fc;text-align:right'>"
                f"{t2name}</div>"
                f"<div style='font-size:11px;color:#8b949e;margin-top:2px;text-align:right'>"
                f"Class {sel_game['c2']} · Away</div>",
                unsafe_allow_html=True)

        st.divider()

        # ── Box Score ────────────────────────────────────────────────────────
        rows_t1, rows_t2, game_info = compute_game_box_score(sel_game_id)
        _has_data = any(not r.get("_totals") for r in rows_t1 + rows_t2)

        if not _has_data:
            st.info("No event data for this game — log events in the Game Tracker first.")
        else:
            q_data = compute_game_quarter_scores(sel_game_id)
            _t1id  = game_info.get("t1id")
            _t2id  = game_info.get("t2id")

            # ── Linescore + score flow chart ──────────────────────────────
            if q_data:
                ls_col, qc_col = st.columns([2, 3])
                with ls_col:
                    st.markdown("##### Linescore")
                    _show_linescore(q_data, t1name, t2name, _t1id, _t2id)
                with qc_col:
                    show_score_flow_chart(sel_game_id, t1name, t2name, _t1id, _t2id,
                                      key=f"flow_games_{sel_game_id}")
                st.divider()

            # ── Player box score (linescore already shown above) ──────────
            st.markdown("##### Player Box Score")
            show_game_box_score(rows_t1, rows_t2, {}, game_info, _cfg)

            st.divider()

            # ── Shot Charts ──────────────────────────────────────────────────
            shot_events = query(
                "SELECT * FROM game_events WHERE game_id=? AND event_type='shot'",
                (sel_game_id,))
            if shot_events:
                # Classify by team
                all_ps = query(
                    "SELECT id, team_id FROM players WHERE team_id IN (?,?)",
                    (game_info.get("t1id"), game_info.get("t2id")))
                pid_tid = {p["id"]: p["team_id"] for p in all_ps}
                t1_shots = [e for e in shot_events
                            if pid_tid.get(e["primary_player_id"]) == game_info.get("t1id")]
                t2_shots = [e for e in shot_events
                            if pid_tid.get(e["primary_player_id"]) == game_info.get("t2id")]
                sc1, sc2 = st.columns(2)
                with sc1:
                    if t1_shots:
                        show_shot_chart(t1_shots, f"{t1name} — Shots")
                with sc2:
                    if t2_shots:
                        show_shot_chart(t2_shots, f"{t2name} — Shots")

            # ── Team stat comparison (if tracked) ────────────────────────────
            if is_tracked:
                ts1, ts2 = game_team_stats(sel_game_id,
                                            game_info.get("t1id"),
                                            game_info.get("t2id"))
                if ts1 and ts2:
                    st.divider()
                    st.markdown("#### Team Stat Comparison")

                    def _bar_stat(label, v1, v2, fmt=".1f", hib=True):
                        if v1 is None or v2 is None: return
                        better1 = (v1 >= v2) if hib else (v1 <= v2)
                        c1,c2,c3 = st.columns([2,6,2])
                        c1.markdown(f"<div style='text-align:right;color:{'#2ecc71' if better1 else '#e74c3c'};font-weight:700'>{v1:{fmt}}</div>",
                                    unsafe_allow_html=True)
                        pct1 = v1/(v1+v2+1e-9)*100
                        bar = (f"<div style='background:#2d333b;border-radius:4px;height:12px'>"
                               f"<div style='background:#3498db;width:{pct1:.0f}%;height:100%;border-radius:4px 0 0 4px'></div></div>")
                        c2.markdown(f"<div style='font-size:11px;color:#8b949e;text-align:center'>{label}</div>"
                                    + bar, unsafe_allow_html=True)
                        c3.markdown(f"<div style='color:{'#2ecc71' if not better1 else '#e74c3c'};font-weight:700'>{v2:{fmt}}</div>",
                                    unsafe_allow_html=True)

                    head_c1, head_c2 = st.columns([1,1])
                    head_c1.markdown(f"**{t1name}**")
                    head_c2.markdown(f"**{t2name}**")

                    comparisons = [
                        ("Points",           ts1.get("pts"),   ts2.get("pts"),  ".0f", True),
                        ("eFG%",             ts1.get("efg"),   ts2.get("efg"),  ".3f", True),
                        ("Assists",          ts1.get("ast"),   ts2.get("ast"),  ".0f", True),
                        ("Turnovers",        ts1.get("tov"),   ts2.get("tov"),  ".0f", False),
                        ("Off. Rebounds",    ts1.get("oreb"),  ts2.get("oreb"), ".0f", True),
                        ("Def. Rebounds",    ts1.get("dreb"),  ts2.get("dreb"), ".0f", True),
                        ("Steals",           ts1.get("stl"),   ts2.get("stl"),  ".0f", True),
                        ("Blocks",           ts1.get("blk"),   ts2.get("blk"),  ".0f", True),
                    ]
                    for lbl, v1, v2, fmt_, hib in comparisons:
                        if v1 is not None and v2 is not None:
                            _bar_stat(lbl, v1, v2, fmt_, hib)


# ══════════════════════════════════════════════════════════════════════════════
