import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from Database.db import query, initialize_database
from helpers.constants import CLASS_ORDER, _RYG, _RYG_R
from helpers.game_utils import streak, record_str, normalize
from helpers.stats_rankings import game_team_stats, compute_all_rankings, compute_tracked_rankings
from helpers.charts import (show_shot_chart, show_scoring_pie,
                            show_four_factors_bars, show_scoring_pie)

initialize_database()

st.title("Rankings")

# ══════════════════════════════════════════════════════════════════════════════
#  FILTERS
# ══════════════════════════════════════════════════════════════════════════════

f1, f2, f3 = st.columns(3)
sel_class  = f1.multiselect("Class", CLASS_ORDER, default=CLASS_ORDER)
sel_gender = f2.selectbox("Gender", ["All","M","F"])
min_gp     = f3.number_input("Min Games Played", min_value=0, value=0, step=1)

# ══════════════════════════════════════════════════════════════════════════════
#  LOCAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df[df["Class"].isin(sel_class)]
    if sel_gender != "All":
        df = df[df["Gender"] == sel_gender]
    df = df[df["GP"] >= min_gp]
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  VISUAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _f(df): return apply_filters(df) if not df.empty else df

def show_summary_metrics(df: pd.DataFrame, tracked: bool = False):
    fdf = _f(df)
    if fdf.empty: return
    best_row = fdf.loc[fdf["Power Score"].idxmax()]
    cols = st.columns(5)
    cols[0].metric("Teams", len(fdf))
    cols[1].metric("Total Games", int(fdf["GP"].sum()//2))
    cols[2].metric("#1 Overall", best_row["Team"],
                   f"PS {best_row['Power Score']} · {best_row['Class']}")
    cols[3].metric("Avg PPG", f"{fdf['PPG'].mean():.1f}")
    if tracked and "Net Rtg" in fdf.columns:
        best_net = fdf.loc[fdf["Net Rtg"].idxmax()]
        cols[4].metric("Best Net Rtg", best_net["Team"], f"{best_net['Net Rtg']:+.1f}")
    else:
        cols[4].metric("Avg Point Diff", f"{fdf['Diff'].mean():+.1f}")


def show_power_chart(df: pd.DataFrame, title: str = "Power Rankings", n: int = 20):
    fdf = _f(df)
    if fdf.empty: return
    top = fdf.nsmallest(min(n,len(fdf)),"Rank").sort_values("Rank",ascending=False)
    hover_extra = {"Net Rtg":":.1f"} if "Net Rtg" in top.columns else {}
    fig = px.bar(
        top, x="Power Score", y="Team", orientation="h",
        color="Power Score", color_continuous_scale=_RYG,
        text="Power Score",
        hover_data={"Class":True,"W":True,"L":True,"W%":":.1f",
                    "Diff":":.1f","Power Score":":.1f",**hover_extra},
        title=title,
    )
    fig.update_traces(textposition="outside",texttemplate="%{text:.1f}",textfont_size=11)
    fig.update_layout(
        height=max(380,len(top)*30+80), coloraxis_showscale=False,
        yaxis_title="", xaxis_title="Power Score (0–100)",
        xaxis=dict(range=[0,112],gridcolor="rgba(128,128,128,0.15)"),
        margin=dict(l=10,r=70,t=50,b=20),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(size=12),
    )
    st.plotly_chart(fig, width='stretch')


def show_four_quadrant(df: pd.DataFrame):
    fdf = _f(df)
    if fdf.empty or "ORtg" not in fdf.columns: return
    avg_ortg = fdf["ORtg"].mean(); avg_drtg = fdf["DRtg"].mean()
    fig = px.scatter(
        fdf, x="DRtg", y="ORtg", text="Team",
        color="Net Rtg", color_continuous_scale=_RYG, size="GP", size_max=22,
        hover_data={"Class":True,"GP":True,"W":True,"L":True,
                    "ORtg":":.1f","DRtg":":.1f","Net Rtg":":.1f","TS%":":.1f"},
        title="Offensive vs Defensive Rating",
        labels={"DRtg":"Defensive Rating — pts allowed per 100 poss (lower = better →)",
                "ORtg":"Offensive Rating — pts scored per 100 poss (higher = better ↑)"},
    )
    fig.add_hline(y=avg_ortg,line_dash="dot",line_color="rgba(180,180,180,0.7)",
                  annotation_text=f"Avg ORtg {avg_ortg:.1f}",
                  annotation_position="bottom right",annotation_font_size=10)
    fig.add_vline(x=avg_drtg,line_dash="dot",line_color="rgba(180,180,180,0.7)",
                  annotation_text=f"Avg DRtg {avg_drtg:.1f}",
                  annotation_position="top left",annotation_font_size=10)
    x_lo=fdf["DRtg"].min(); x_hi=fdf["DRtg"].max()
    y_lo=fdf["ORtg"].min(); y_hi=fdf["ORtg"].max()
    px2=(x_hi-x_lo)*0.08; py2=(y_hi-y_lo)*0.08
    for lbl,tx,ty,col in [
        ("ELITE\n● High O  ● Low D",   x_lo+px2, y_hi-py2, "#1a9850"),
        ("OFFENSIVE\n● High O  ● High D", x_hi-px2, y_hi-py2, "#fee08b"),
        ("DEFENSIVE\n● Low O  ● Low D",  x_lo+px2, y_lo+py2, "#74add1"),
        ("STRUGGLING\n● Low O  ● High D",x_hi-px2, y_lo+py2, "#d73027"),
    ]:
        fig.add_annotation(x=tx,y=ty,text=lbl,showarrow=False,
                           font=dict(color=col,size=9),opacity=0.55,align="center")
    fig.update_traces(textposition="top center",textfont_size=9,
                      marker=dict(line=dict(width=1,color="white")))
    fig.update_layout(
        height=560, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20,r=30,t=60,b=20),
        coloraxis_colorbar=dict(title="Net Rtg",thickness=12),
        xaxis=dict(gridcolor="rgba(128,128,128,0.12)",autorange="reversed"),
        yaxis=dict(gridcolor="rgba(128,128,128,0.12)"), font=dict(size=11),
    )
    st.plotly_chart(fig, width='stretch')
    st.caption("Bubble size = games played.  Quadrant dividers = league averages.  X-axis is reversed: teams further left have better defense.")


def show_four_factors_chart(df: pd.DataFrame):
    """Radar chart — Four Factors profile for user-selected teams."""
    fdf = _f(df)
    if fdf.empty or "eFG%" not in fdf.columns:
        return

    ranked_teams = fdf.sort_values("Power Score", ascending=False)["Team"].tolist()
    default_teams = ranked_teams[:15]

    selected = st.multiselect(
        "Teams to include in chart",
        options=ranked_teams,
        default=default_teams,
        key="ff_team_picker",
        help="Leave blank to reset to top 15 by Power Score. "
             "All normalisation is recalculated relative to the teams shown.",
    )

    # Fall back to top 15 if user clears the picker
    teams_to_show = selected if selected else default_teams
    sdf = fdf[fdf["Team"].isin(teams_to_show)].sort_values("Power Score", ascending=False)

    if sdf.empty:
        st.info("No data for the selected teams.")
        return

    # Axes (inverted where lower = better so 100 always = best)
    cats = [
        "eFG%", "TOV% (inv)", "OREB%", "FT Rate",
        "Opp eFG% (inv)", "Opp TOV%", "DREB%", "Opp FT Rate (inv)",
    ]
    factor_cfg = [
        ("eFG%",         True),
        ("TOV%",         False),
        ("OREB%",        True),
        ("FT Rate",      True),
        ("Opp eFG%",     False),
        ("Opp TOV%",     True),
        ("DREB%",        True),
        ("Opp FT Rate",  False),
    ]

    # Normalise relative to the *selected* teams only
    norm_base = sdf  # so each axis spans 0-100 over the chosen set

    def pct(col, hib):
        lo, hi = norm_base[col].min(), norm_base[col].max()
        if hi == lo:
            return 50.0
        try:
            v = norm_base.loc[norm_base["Team"] == team_name, col].values[0]
        except Exception:
            return 0.0
        n = (v - lo) / (hi - lo)
        return (n if hib else 1 - n) * 100

    palette = px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
    n_teams = len(sdf)
    fig = go.Figure()

    for i, row in enumerate(sdf.itertuples()):
        team_name = row.Team
        vals = [pct(col, hib) for col, hib in factor_cfg]
        color = palette[i % len(palette)]
        opacity = max(0.15, 0.45 - n_teams * 0.015)
        hover_lines = "<br>".join(
            f"{cats[j]}: {norm_base.loc[norm_base['Team']==team_name, col].values[0]:.1f}"
            for j, (col, _) in enumerate(factor_cfg)
            if col in norm_base.columns
        )
        fig.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=cats + [cats[0]],
            name=team_name, fill="toself",
            line=dict(color=color, width=2),
            opacity=opacity,
            hovertemplate=f"<b>{team_name}</b><br>{hover_lines}<extra></extra>",
        ))
        # Solid border trace (no fill) so team outlines stay crisp
        fig.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=cats + [cats[0]],
            mode="lines", line=dict(color=color, width=2),
            showlegend=False, hoverinfo="skip",
        ))

    title_str = (
        f"Four Factors Radar — {n_teams} team{'s' if n_teams != 1 else ''}"
        " (normalized within selection)"
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(range=[0, 100], showticklabels=False,
                            gridcolor="rgba(150,150,150,0.2)"),
            angularaxis=dict(tickfont=dict(size=11)),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=True, height=520,
        paper_bgcolor="rgba(0,0,0,0)",
        title=dict(text=title_str, font=dict(size=13)),
        legend=dict(orientation="h", y=-0.15, font=dict(size=9)),
        margin=dict(l=50, r=50, t=70, b=100),
    )
    st.plotly_chart(fig, width='stretch')
    st.caption(
        "Each axis normalised 0–100 **within the selected teams** — "
        "100 = best, 0 = worst among those shown. "
        "Inverted axes (TOV%, Opp eFG%, Opp FT Rate): lower raw value = higher score."
    )


def show_net_rtg_chart(df: pd.DataFrame):
    fdf = _f(df)
    if fdf.empty or "Net Rtg" not in fdf.columns: return
    sdf = fdf.sort_values("Net Rtg",ascending=True)
    colors = ["#1a9850" if v>=0 else "#d73027" for v in sdf["Net Rtg"]]
    fig = go.Figure(go.Bar(
        x=sdf["Net Rtg"], y=sdf["Team"], orientation="h",
        marker_color=colors,
        text=sdf["Net Rtg"].apply(lambda v:f"{v:+.1f}"),
        textposition="outside",
        hovertemplate="%{y}<br>Net Rtg: %{x:+.1f}<extra></extra>",
    ))
    fig.add_vline(x=0,line_color="rgba(180,180,180,0.8)",line_width=1.5)
    fig.update_layout(
        title="Net Rating per Team (ORtg − DRtg)",
        xaxis_title="Net Rating (pts per 100 poss)",
        yaxis_title="",
        height=max(380,len(sdf)*26+80),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10,r=70,t=50,b=20),
        xaxis=dict(gridcolor="rgba(128,128,128,0.15)"), font=dict(size=11),
    )
    st.plotly_chart(fig, width='stretch')


def show_scoring_dist_chart(df: pd.DataFrame):
    """Stacked bar of scoring distribution (% from 2PT, 3PT, FT)."""
    fdf = _f(df)
    if fdf.empty or "Pts from 2%" not in fdf.columns: return
    sdf = fdf.sort_values("Power Score",ascending=False).head(20)
    fig = go.Figure()
    for col, color, label in [
        ("Pts from 2%", "#2166ac", "2PT %"),
        ("Pts from 3%", "#1a9850", "3PT %"),
        ("Pts from FT%","#d73027", "FT %"),
    ]:
        fig.add_trace(go.Bar(name=label, x=sdf["Team"], y=sdf[col],
                             marker_color=color,
                             hovertemplate="%{x}<br>"+label+": %{y:.1f}%<extra></extra>"))
    fig.update_layout(
        barmode="stack", title="Scoring Distribution by Source (top 20 by Power Score)",
        yaxis_title="% of Total Points", xaxis_title="",
        height=380, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20,r=20,t=50,b=80),
        legend=dict(orientation="h",y=1.08),
        xaxis=dict(tickangle=-40,gridcolor="rgba(128,128,128,0.12)"),
        yaxis=dict(gridcolor="rgba(128,128,128,0.15)"), font=dict(size=11),
    )
    st.plotly_chart(fig, width='stretch')


def show_stat_leaders(df: pd.DataFrame, stats: list):
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
            for i,(_, row) in enumerate(top5.iterrows()):
                val = row[stat]
                if isinstance(val,float):
                    fmt = f"{val:+.1f}" if stat in ("Diff","Net Rtg","Q4 Diff") else f"{val:.1f}"
                else:
                    fmt = str(val)
                st.markdown(f"{medals[i]} **{row['Team']}** `{row['Class']}`  {fmt}")


def show_team_radar(df: pd.DataFrame, radar_stats: list, key: str = "radar"):
    fdf = _f(df)
    if fdf.empty: return
    team_names = sorted(fdf["Team"].tolist())
    selected = st.multiselect("Compare teams on radar (pick 2–5)",team_names,max_selections=5,key=key)
    if not selected:
        st.caption("Select teams above to compare stats visually.")
        return
    cats = [label for _,label,_ in radar_stats]
    cols = [c for c,_,_ in radar_stats]
    hibs = [h for _,_,h in radar_stats]
    normed = {}
    for c,hib in zip(cols,hibs):
        s = fdf[c]; lo,hi = s.min(),s.max()
        if hi==lo: normed[c]=pd.Series(50.0,index=fdf.index)
        else:
            n = (s-lo)/(hi-lo)
            normed[c] = (n if hib else 1-n)*100
    palette = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd"]
    fig = go.Figure()
    for i,team in enumerate(selected):
        row = fdf[fdf["Team"]==team]
        if row.empty: continue
        idx = row.index[0]
        nv  = [normed[c][idx] for c in cols]
        rv  = [row[c].values[0] for c in cols]
        hover_lines = "<br>".join(f"{cat}: {rv_:.1f}" for cat,rv_ in zip(cats,rv))
        color = palette[i%len(palette)]
        fig.add_trace(go.Scatterpolar(
            r=nv+[nv[0]], theta=cats+[cats[0]],
            fill="toself", fillcolor=color, line=dict(color=color,width=2),
            opacity=0.25, name=team,
            hovertemplate=f"<b>{team}</b><br>{hover_lines}<extra></extra>",
        ))
        fig.add_trace(go.Scatterpolar(
            r=nv+[nv[0]], theta=cats+[cats[0]],
            mode="lines+markers", line=dict(color=color,width=2),
            marker=dict(size=6,color=color), showlegend=False, hoverinfo="skip",
        ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True,range=[0,100],showticklabels=False,
                            gridcolor="rgba(150,150,150,0.25)"),
            angularaxis=dict(tickfont=dict(size=11)), bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=True, height=460,
        margin=dict(l=50,r=50,t=60,b=50), paper_bgcolor="rgba(0,0,0,0)",
        title="Team Comparison — normalized vs current filter set (100 = best)",
        font=dict(size=11), legend=dict(orientation="h",y=-0.08),
    )
    st.plotly_chart(fig, width='stretch')


# ══════════════════════════════════════════════════════════════════════════════
#  STYLED TABLE + CLASS BREAKDOWN
# ══════════════════════════════════════════════════════════════════════════════

_show_table_call_count = 0

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
        cmap = "RdYlGn_r" if c in _GOOD_LOW else "RdYlGn"
        try:
            styler = styler.background_gradient(subset=[c],cmap=cmap,axis=0)
        except Exception:
            pass
    return styler

def show_table(df, display_cols, sort_default, use_gradients=True):
    global _show_table_call_count
    _show_table_call_count += 1
    uid = _show_table_call_count
    if df.empty:
        st.info("No data available."); return
    filtered = apply_filters(df)
    if filtered.empty:
        st.info("No teams match the selected filters."); return
    sort_col = st.selectbox(
        "Sort by", display_cols,
        index=display_cols.index(sort_default) if sort_default in display_cols else 0,
        key=f"sort_{uid}_{sort_default}",
    )
    asc = sort_col in _GOOD_LOW or sort_col == "Rank"
    out = filtered[display_cols].sort_values(sort_col,ascending=asc).reset_index(drop=True)
    out.index += 1
    if use_gradients:
        grad_targets = [c for c in display_cols if c in _GRADIENT_COLS]
        styler = out.style.set_properties(**{"font-size":"13px"})
        styler = _apply_grads(styler, grad_targets)
        st.dataframe(styler, width='stretch')
    else:
        st.dataframe(out, width='stretch')


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
            st.dataframe(styler, width='stretch')


# ══════════════════════════════════════════════════════════════════════════════
#  COLUMN LISTS
# ══════════════════════════════════════════════════════════════════════════════

ALL_COLS = ["Rank","Team","Class","Gender","GP","W","L","W%",
            "PPG","PA/G","Diff","SOS","SOR",
            "Home","Away","Best Win","Worst Loss","Streak","Power Score"]

CORE_COLS = ["Rank","Team","Class","Gender","GP","W","L","W%",
             "PPG","PA/G","Diff","SOS","SOR",
             "Home","Away","Streak","Power Score"]

EFF_COLS  = ["Rank","Team","Class","Gender","GP",
             "ORtg","DRtg","Net Rtg","Pace",
             "eFG%","Opp eFG%","TS%","Opp TS%",
             "TOV%","OREB%","DREB%","AST/TOV","Power Score"]

SHOOT_COLS = ["Rank","Team","Class","Gender","GP",
              "FG%","2P%","eFG%","TS%","3P%","FT%",
              "3PAr","FT Rate","Ast%","Unast%",
              "Paint FG%","Paint Pts/G",
              "Pts from 2%","Pts from 3%","Pts from FT%","Power Score"]

MISC_COLS = ["Rank","Team","Class","Gender","GP",
             "AST/G","STL/G","BLK/G","TOV/G","OREB/G","DREB/G",
             "BLK Rate","STL Rate","AST/TOV",
             "Q4 Pts/G","Q4 PA/G","Q4 Diff",
             "Best Win","Worst Loss","Streak","Power Score"]

POSS_COLS = ["Rank","Team","Class","Gender","GP",
             "Poss/G","PPP","Opp PPP",
             "Avg Poss (s)","TOV/Poss","AST/Poss",
             "OREB%","DREB%","FT Rate","Power Score"]

FOUR_FACTORS_COLS = ["Rank","Team","Class","Gender","GP",
                     "eFG%","TOV%","OREB%","FT Rate",
                     "Opp eFG%","Opp TOV%","DREB%","Opp FT Rate",
                     "Power Score"]

DEFENSE_COLS = ["Rank","Team","Class","Gender","GP",
                "DRtg","Opp eFG%","Opp TS%","Opp TOV%","Opp FT Rate",
                "DREB%","BLK Rate","STL Rate","Power Score"]


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER — TAB 1: EVERYTHING
# ══════════════════════════════════════════════════════════════════════════════

tab_all, tab_tracked = st.tabs(["Everything", "Tracked Games"])

with tab_all:
    st.caption("Rankings built from all games with a final score — tracked and non-tracked.")
    with st.spinner("Computing…"):
        df_all = compute_all_rankings()

    show_summary_metrics(df_all, tracked=False)
    st.divider()

    chart_col, leaders_col = st.columns([3,2])
    with chart_col:
        show_power_chart(df_all, "Power Rankings — All Games", n=20)
    with leaders_col:
        st.markdown("#### Stat Leaders")
        show_stat_leaders(df_all, [
            ("Power Score","Power Score",True),
            ("W%","Win %",True),
            ("PPG","Scoring",True),
            ("SOR","Str. of Record",True),
            ("Diff","Point Diff",True),
        ])

    st.divider()
    st.subheader("Overall Rankings")
    st.caption("Color scale: **green** = best · **red** = worst.  Defensive stats scale is inverted — lower is greener.")
    show_table(df_all, ALL_COLS, "Rank")
    st.subheader("By Class")
    show_class_breakdown(df_all, ALL_COLS)

    with st.expander("Stat glossary"):
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


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER — TAB 2: TRACKED GAMES
# ══════════════════════════════════════════════════════════════════════════════

with tab_tracked:
    with st.spinner("Computing…"):
        df_tr = compute_tracked_rankings()

    sub_core, sub_eff, sub_shoot, sub_misc, sub_poss, sub_ff, sub_def = st.tabs([
        "Core","Efficiency","Shooting","Per Game / Misc",
        "Possession","Four Factors","Defense",
    ])

    # ── Core ─────────────────────────────────────────────────────────────────
    with sub_core:
        show_summary_metrics(df_tr, tracked=True)
        st.divider()
        ch_col, ld_col = st.columns([3,2])
        with ch_col:
            show_power_chart(df_tr,"Power Rankings — Tracked Games",n=20)
        with ld_col:
            st.markdown("#### Stat Leaders")
            show_stat_leaders(df_tr,[
                ("Power Score","Power Score",True),
                ("W%","Win %",True),
                ("PPG","Scoring",True),
                ("SOR","Str. of Record",True),
                ("Diff","Point Diff",True),
            ])
        st.divider()
        st.subheader("Core Rankings")
        show_table(df_tr, CORE_COLS, "Rank")
        st.subheader("By Class")
        show_class_breakdown(df_tr, CORE_COLS)
        with st.expander("Team Comparison — Radar"):
            show_team_radar(df_tr,[
                ("_wp","Win %",True),("_sor","Str. of Record",True),
                ("PPG","PPG",True),("PA/G","PA/G",False),
                ("_diff","Margin",True),("_sos","Sched. Strength",True),
            ], key="radar_core")

    # ── Efficiency ───────────────────────────────────────────────────────────
    with sub_eff:
        st.subheader("Offensive vs Defensive Rating")
        st.caption("Elite teams sit top-left: scoring efficiently while holding opponents down.")
        show_four_quadrant(df_tr)
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
        with st.expander("Team Comparison — Radar"):
            show_team_radar(df_tr,[
                ("ORtg","Off Rtg",True),("DRtg","Def Rtg",False),
                ("TS%","TS%",True),("OREB%","OREB%",True),
                ("TOV%","TOV%",False),("AST/TOV","AST/TOV",True),
            ], key="radar_eff")
        with st.expander("Stat glossary"):
            st.markdown("""
| Stat | Meaning |
|------|---------|
| **ORtg** | Offensive Rating — points scored per 100 possessions |
| **DRtg** | Defensive Rating — points allowed per 100 possessions (lower = better) |
| **Net Rtg** | ORtg − DRtg; positive = outscoring opponents per possession |
| **Pace** | Estimated possessions per game (both teams averaged) |
| **eFG%** | Effective FG%: (FGM + 0.5×3PM) / FGA |
| **TS%** | True Shooting %: PTS / (2×(FGA + 0.44×FTA)) |
| **TOV%** | Turnovers per possession (lower = better) |
| **AST/TOV** | Assist-to-turnover ratio (higher = better ball security) |
| **OREB% / DREB%** | Offensive / Defensive rebounding rate |
""")

    # ── Shooting ─────────────────────────────────────────────────────────────
    with sub_shoot:
        st.subheader("Scoring Sources")
        show_scoring_dist_chart(df_tr)
        st.divider()
        show_stat_leaders(df_tr,[
            ("TS%","True Shoot%",True),
            ("eFG%","eFG%",True),
            ("2P%","2PT%",True),
            ("3P%","3PT%",True),
            ("Paint Pts/G","Paint Pts/G",True),
        ])
        st.divider()
        st.subheader("Shooting Table")
        show_table(df_tr, SHOOT_COLS, "TS%")
        st.subheader("By Class")
        show_class_breakdown(df_tr, SHOOT_COLS)
        with st.expander("Team Comparison — Radar"):
            show_team_radar(df_tr,[
                ("TS%","TS%",True),("eFG%","eFG%",True),
                ("FG%","FG%",True),("2P%","2P%",True),
                ("3P%","3P%",True),("FT%","FT%",True),
            ], key="radar_shoot")
        with st.expander("Stat glossary"):
            st.markdown("""
| Stat | Meaning |
|------|---------|
| **2P%** | Two-point field goal percentage |
| **eFG%** | Effective FG% — weights 3PT attempts appropriately |
| **TS%** | True Shooting % — accounts for free throws |
| **3PAr** | 3-point attempt rate (3PA / FGA) |
| **FT Rate** | Free throw rate (FTA / FGA) |
| **Ast%** | % of made field goals that were assisted (catch-and-shoot rate) |
| **Unast%** | % of made field goals that were self-created |
| **Paint FG%** | FG% on zone-C two-point shots (paint area proxy) |
| **Paint Pts/G** | Points from paint shots per game |
| **Pts from 2%** | % of total points scored via 2-point field goals |
| **Pts from 3%** | % of total points scored via 3-point field goals |
| **Pts from FT%** | % of total points scored via free throws |
""")

    # ── Per Game / Misc ───────────────────────────────────────────────────────
    with sub_misc:
        st.subheader("Clutch — 4th Quarter")
        show_stat_leaders(df_tr,[
            ("Q4 Diff","Q4 Net Diff",True),
            ("Q4 Pts/G","Q4 Scoring",True),
            ("Q4 PA/G","Q4 D (allow)",False),
            ("BLK Rate","BLK Rate",True),
            ("STL Rate","STL Rate",True),
        ])
        st.divider()
        st.subheader("Per Game / Misc Table")
        show_table(df_tr, MISC_COLS, "STL/G")
        st.subheader("By Class")
        show_class_breakdown(df_tr, MISC_COLS)
        with st.expander("Team Comparison — Radar"):
            show_team_radar(df_tr,[
                ("AST/G","AST/G",True),("STL/G","STL/G",True),
                ("BLK/G","BLK/G",True),("TOV/G","TOV/G",False),
                ("BLK Rate","BLK Rate",True),("STL Rate","STL Rate",True),
            ], key="radar_misc")
        with st.expander("Stat glossary"):
            st.markdown("""
| Stat | Meaning |
|------|---------|
| **BLK Rate** | Blocks per 100 opponent 2PT attempts (rim protection rate) |
| **STL Rate** | Steals per 100 opponent possessions (pressure/gambling rate) |
| **Q4 Pts/G** | Team's average 4th-quarter points scored |
| **Q4 PA/G** | Team's average 4th-quarter points allowed |
| **Q4 Diff** | 4th-quarter point differential per game (clutch indicator) |
""")

    # ── Possession ────────────────────────────────────────────────────────────
    with sub_poss:
        st.caption(
            "**PPP** = points per tracked possession (shots + turnovers).  "
            "**Avg Poss (s)** = average seconds held per possession.  "
            "Only available for tracked games with logged events."
        )
        show_stat_leaders(df_tr,[
            ("PPP","Pts/Poss",True),
            ("Opp PPP","Opp Pts/Poss",False),
            ("Poss/G","Poss/G",True),
            ("TOV/Poss","TOV/Poss",False),
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
        st.caption(
            "The four most predictive factors of winning, in order of importance: "
            "**Shooting (40%)** · **Ball Security (25%)** · **Offensive Rebounding (20%)** · **Free Throw Rate (15%)**  "
            "Each factor shown for offense *and* defense."
        )
        show_four_factors_chart(df_tr)
        st.divider()
        ff_ldr_cols = st.columns(4)
        with ff_ldr_cols[0]:
            st.markdown("**Shooting (OFF eFG%)**")
            show_stat_leaders(df_tr,[("eFG%","eFG%",True)], )
        with ff_ldr_cols[1]:
            st.markdown("**Ball Security (low TOV%)**")
            show_stat_leaders(df_tr,[("TOV%","TOV%",False)])
        with ff_ldr_cols[2]:
            st.markdown("**Off. Rebounding (OREB%)**")
            show_stat_leaders(df_tr,[("OREB%","OREB%",True)])
        with ff_ldr_cols[3]:
            st.markdown("**FT Rate (FTA/FGA)**")
            show_stat_leaders(df_tr,[("FT Rate","FT Rate",True)])

        # Defensive leaders row
        st.divider()
        st.markdown("#### Defensive Four Factors")
        dff_cols = st.columns(4)
        with dff_cols[0]:
            st.markdown("**Opp Shooting (Opp eFG%)**")
            show_stat_leaders(df_tr,[("Opp eFG%","Opp eFG%",False)])
        with dff_cols[1]:
            st.markdown("**Force TOs (Opp TOV%)**")
            show_stat_leaders(df_tr,[("Opp TOV%","Opp TOV%",True)])
        with dff_cols[2]:
            st.markdown("**Def. Rebounding (DREB%)**")
            show_stat_leaders(df_tr,[("DREB%","DREB%",True)])
        with dff_cols[3]:
            st.markdown("**Foul Discipline (Opp FT Rate)**")
            show_stat_leaders(df_tr,[("Opp FT Rate","Opp FT Rate",False)])

        st.divider()
        st.subheader("Four Factors Table")
        show_table(df_tr, FOUR_FACTORS_COLS, "eFG%")
        st.subheader("By Class")
        show_class_breakdown(df_tr, FOUR_FACTORS_COLS)
        with st.expander("Stat glossary"):
            st.markdown("""
| Stat | What it measures | Weight |
|------|-----------------|--------|
| **eFG%** | Shooting efficiency (offense) | 40% |
| **TOV%** | Ball security — turnovers per possession | 25% |
| **OREB%** | Second-chance creation rate | 20% |
| **FT Rate** | Getting to the free throw line | 15% |
| **Opp eFG%** | Opponent shooting efficiency (defense) | 40% |
| **Opp TOV%** | Forcing opponent turnovers | 25% |
| **DREB%** | Limiting opponent second chances | 20% |
| **Opp FT Rate** | Foul discipline — how often you put opponents at the line | 15% |

*Weights from Dean Oliver's "Basketball on Paper" (2004)*
""")

    # ── Defense ───────────────────────────────────────────────────────────────
    with sub_def:
        st.subheader("Defensive Dashboard")
        d_chart_col, d_ld_col = st.columns([3,2])
        with d_chart_col:
            # DRtg bar chart
            fdf_def = _f(df_tr)
            if not fdf_def.empty and "DRtg" in fdf_def.columns:
                sdf_def = fdf_def.sort_values("DRtg",ascending=True).head(20)
                fig_d = px.bar(
                    sdf_def, x="DRtg", y="Team", orientation="h",
                    color="DRtg",
                    color_continuous_scale=_RYG_R,  # reversed: low DRtg = green
                    text="DRtg",
                    hover_data={"Opp eFG%":":.1f","Opp TOV%":":.1f","DREB%":":.1f","BLK Rate":":.1f"},
                    title="Defensive Rating — Top 20 Defenses (lower = better)",
                )
                fig_d.update_traces(textposition="outside",texttemplate="%{text:.1f}",textfont_size=11)
                fig_d.update_layout(
                    height=max(380,len(sdf_def)*30+80), coloraxis_showscale=False,
                    yaxis_title="", xaxis_title="DRtg (pts allowed per 100 poss)",
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=10,r=70,t=50,b=20), font=dict(size=12),
                )
                st.plotly_chart(fig_d, width='stretch')
        with d_ld_col:
            st.markdown("#### Defensive Leaders")
            show_stat_leaders(df_tr,[
                ("DRtg","Best DRtg",False),
                ("Opp eFG%","Opp eFG%",False),
                ("Opp TOV%","Force TOs",True),
                ("BLK Rate","BLK Rate",True),
                ("STL Rate","STL Rate",True),
            ])
        st.divider()
        st.subheader("Defense Table")
        show_table(df_tr, DEFENSE_COLS, "DRtg")
        st.subheader("By Class")
        show_class_breakdown(df_tr, DEFENSE_COLS)
        with st.expander("Team Comparison — Radar"):
            show_team_radar(df_tr,[
                ("DRtg","Def Rtg",False),("Opp eFG%","Opp eFG%",False),
                ("Opp TOV%","Force TOs",True),("DREB%","DREB%",True),
                ("BLK Rate","BLK Rate",True),("STL Rate","STL Rate",True),
            ], key="radar_def")
        with st.expander("Stat glossary"):
            st.markdown("""
| Stat | Meaning |
|------|---------|
| **DRtg** | Defensive Rating — points allowed per 100 possessions (lower = better) |
| **Opp eFG%** | Opponent effective FG% — how well you're contesting/limiting shots |
| **Opp TS%** | Opponent True Shooting % |
| **Opp TOV%** | How often you force the opponent into a turnover (higher = better D) |
| **Opp FT Rate** | How often you send opponents to the line (lower = better discipline) |
| **DREB%** | Defensive rebounding rate — % of available def. rebounds you grab |
| **BLK Rate** | Your blocks per 100 opponent 2PT attempts (rim protection) |
| **STL Rate** | Your steals per 100 opponent possessions (active defense/gambling) |
""")
