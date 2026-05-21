import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from helpers.constants import ZONES, _ZONE_XY


def zone_color(m, a):
    if not a: return "#2d2d2d","#555"
    p=m/a
    if p>=0.5: return "#1a5c38","#fff"
    if p>=0.35: return "#7a5200","#fff"
    return "#6b1515","#fff"


def render_hot_zones(shot_rows, title=""):
    if title: st.markdown(f"**{title}**")
    zd={z:{2:[0,0],3:[0,0]} for z in ZONES}
    for s in shot_rows:
        z,t=s.get("zone"),s.get("shot_type")
        if z and t:
            zd[z][t][1]+=1
            if s.get("shot_result")=="make": zd[z][t][0]+=1
    for stype,lbl in [(2,"2-Point"),(3,"3-Point")]:
        st.markdown(f"*{lbl}*")
        cols=st.columns(5)
        for i,zone in enumerate(ZONES):
            m,a=zd[zone][stype]
            pct=m/a*100 if a else 0
            bg,fg=zone_color(m,a)
            cols[i].markdown(
                f"""<div style="background:{bg};color:{fg};padding:12px 4px;
                border-radius:8px;text-align:center;font-size:0.85em">
                <b>{zone}</b><br>{m}/{a}<br>{pct:.0f}%</div>""",
                unsafe_allow_html=True)


def show_shot_chart(shots: list, title: str = "Shot Chart"):
    """Plotly zone-bubble shot chart on a high-school half-court outline.

    Coordinate system (all in feet, same scale as _ZONE_XY):
      • Basket at (0, 0)
      • Y axis points toward half-court (away from basket)
      • High-school 3-pt line: 19 ft 9 in ≈ 19.75 ft from basket centre
        (corners at x = ±19.75, straight lines from baseline to y ≈ 5.25,
         then arc continuing to centre-top)
    """
    zone_stats: dict = {}
    for s in shots:
        z, st_ = s.get("zone"), s.get("shot_type")
        if not z or not st_: continue
        key = (z, st_)
        d = zone_stats.setdefault(key, {"fgm": 0, "fga": 0})
        d["fga"] += 1
        if s.get("shot_result") == "make": d["fgm"] += 1

    if not zone_stats:
        st.info("No shot data with zone information recorded yet.")
        return

    fig = go.Figure()

    # ── Colour palette ───────────────────────────────────────────────────────
    LINE  = "rgba(220,220,220,0.75)"
    LINE_DIM = "rgba(180,180,180,0.35)"
    PAINT_FILL = "rgba(255,255,255,0.04)"
    GOLD  = "rgba(230,190,100,0.95)"
    W = 1.5    # standard line width

    def _ln(x0, y0, x1, y1, color=LINE, width=W):
        fig.add_shape(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color=color, width=width))

    def _arc(cx, cy, r, t0, t1, n=80, color=LINE, width=W, dash="solid"):
        th = np.linspace(t0, t1, n)
        fig.add_trace(go.Scatter(
            x=cx + r*np.cos(th), y=cy + r*np.sin(th),
            mode="lines", line=dict(color=color, width=width, dash=dash),
            showlegend=False, hoverinfo="skip",
        ))

    # ── Court dimensions (display units match _ZONE_XY scale) ───────────────
    #   R3 = 23 ft gives a visually open arc with clear separation from the
    #   paint, matching the bubble positions in _ZONE_XY.
    R3       = 23.0
    CORNER_X = 21.5                                          # x of corner 3-pt line
    CORNER_BREAK_Y = np.sqrt(max(0, R3**2 - CORNER_X**2))   # ≈ 8.2 ft

    # Lane: 12 ft wide (±6), 15 ft deep to FT line
    LANE_W = 6.0   # half-width
    LANE_D = 15.0  # depth (to FT line)
    FT_R   = 6.0   # free-throw circle radius
    RA_R   = 3.0   # restricted area radius

    # ── Baseline ─────────────────────────────────────────────────────────────
    _ln(-25, 0, 25, 0, color=LINE, width=2)

    # ── 3-point arc ──────────────────────────────────────────────────────────
    # Arc from left corner break to right corner break
    t_corner = np.arcsin(CORNER_BREAK_Y / R3)   # angle where arc meets corner line
    _arc(0, 0, R3, np.pi - t_corner, t_corner, n=120)

    # Corner straight lines (baseline → arc start)
    _ln(-CORNER_X, 0, -CORNER_X, CORNER_BREAK_Y)
    _ln( CORNER_X, 0,  CORNER_X, CORNER_BREAK_Y)

    # ── Lane / Paint ─────────────────────────────────────────────────────────
    fig.add_shape(type="rect",
                  x0=-LANE_W, y0=0, x1=LANE_W, y1=LANE_D,
                  line=dict(color=LINE, width=W),
                  fillcolor=PAINT_FILL)

    # Lane hash marks (blocks) — 4 pairs on each side
    for y_hash in [7.0, 9.0, 11.0, 13.0]:
        for side in [-1, 1]:
            _ln(side*LANE_W, y_hash, side*(LANE_W+1.5), y_hash,
                color=LINE_DIM, width=1)

    # ── Free-throw line ───────────────────────────────────────────────────────
    _ln(-LANE_W, LANE_D, LANE_W, LANE_D)

    # FT circle — top half solid, bottom half dashed
    _arc(0, LANE_D, FT_R, 0,    np.pi,  color=LINE, width=W)
    _arc(0, LANE_D, FT_R, np.pi, 2*np.pi, color=LINE_DIM, width=1, dash="dot")

    # ── Restricted area ───────────────────────────────────────────────────────
    _arc(0, 0, RA_R, 0, np.pi, color=LINE_DIM, width=1)

    # ── Backboard & basket ────────────────────────────────────────────────────
    _ln(-3.0, -0.5, 3.0, -0.5, color=GOLD, width=2.5)   # backboard
    fig.add_shape(type="circle",
                  x0=-0.75, y0=-0.75, x1=0.75, y1=0.75,
                  line=dict(color=GOLD, width=2.5),
                  fillcolor="rgba(0,0,0,0)")

    # ── Shot bubbles ─────────────────────────────────────────────────────────
    # Sort so larger bubbles are drawn first (smaller on top)
    items = sorted(zone_stats.items(), key=lambda x: x[1]["fga"], reverse=True)
    for (zone, stype), d in items:
        pos = _ZONE_XY.get((zone, stype))
        if not pos:
            continue
        fga, fgm = d["fga"], d["fgm"]
        fgp = fgm / fga if fga else 0
        color = "#1a9850" if fgp >= 0.45 else ("#f4a724" if fgp >= 0.30 else "#d73027")
        border = "rgba(255,255,255,0.9)"
        size   = max(18, min(52, 10 + fga * 5))
        label  = f"{fgp*100:.0f}%"
        sub    = f"{fgm}/{fga}"
        hover  = (f"<b>{stype}PT — {zone}</b><br>"
                  f"Makes: {fgm}  Attempts: {fga}<br>"
                  f"FG%: {fgp*100:.1f}%"
                  f"{'<br><i>Paint area proxy</i>' if zone=='C' and stype==2 else ''}")
        fig.add_trace(go.Scatter(
            x=[pos[0]], y=[pos[1]],
            mode="markers+text",
            marker=dict(size=size, color=color, sizemode="diameter",
                        line=dict(color=border, width=1.5), opacity=0.90),
            text=[f"<b>{label}</b>"],
            textposition="middle center",
            textfont=dict(size=max(9, min(13, size//4)), color="white",
                          family="Arial Black"),
            hovertext=[hover], hoverinfo="text",
            showlegend=False,
        ))
        # Attempt count as small annotation below the bubble
        fig.add_annotation(
            x=pos[0], y=pos[1] - size/46 - 1.5,
            text=sub, showarrow=False,
            font=dict(size=8, color="rgba(255,255,255,0.7)"),
            bgcolor="rgba(0,0,0,0)",
        )

    # ── Zone labels (corner/wing identifiers) ─────────────────────────────────
    ZONE_LABELS = {
        "LC": (-21, -2.5), "LW": (-18, 13), "C": (0, -2.5),
        "RW": (18, 13),    "RC": (21, -2.5),
    }
    for z_name, (zx, zy) in ZONE_LABELS.items():
        fig.add_annotation(
            x=zx, y=zy, text=z_name, showarrow=False,
            font=dict(size=8, color="rgba(200,200,200,0.5)"),
        )

    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="rgba(220,220,220,0.9)"),
                   x=0.02, xanchor="left"),
        xaxis=dict(range=[-26, 26], showgrid=False, zeroline=False,
                   showticklabels=False, visible=False),
        yaxis=dict(range=[-5, 32], showgrid=False, zeroline=False,
                   showticklabels=False, visible=False,
                   scaleanchor="x", scaleratio=1),
        height=420,
        margin=dict(l=5, r=5, t=45, b=5),
        plot_bgcolor="rgba(18,20,30,1)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width='stretch')
    st.caption("Bubble size = attempts · 🟢 ≥45% · 🟡 30–44% · 🔴 <30% FG%"
               " · Zone C 2PT = paint area proxy · HS 3-pt line: 19′9″")


def show_scoring_pie(pts_2: int, pts_3: int, pts_ft: int, title: str = "Scoring Distribution"):
    total = pts_2 + pts_3 + pts_ft
    if total == 0:
        st.info("No scoring data."); return
    fig = go.Figure(go.Pie(
        labels=["2PT Field Goals", "3PT Field Goals", "Free Throws"],
        values=[pts_2, pts_3, pts_ft],
        marker_colors=["#2166ac","#1a9850","#d73027"],
        textinfo="label+percent",
        hole=0.38,
        hovertemplate="%{label}<br>%{value} pts (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        title=title, height=300,
        margin=dict(l=20,r=20,t=50,b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        font=dict(size=12),
    )
    st.plotly_chart(fig, width='stretch')


def show_four_factors_bars(adv: dict, league_avgs: dict = None):
    """Grouped bar: team vs league avg for each Four Factor."""
    if not adv: return
    factors = [
        ("eFG%",      adv["efg"]*100,           "Offensive eFG%",       True),
        ("TOV%",      adv["tov_r"]*100,          "Turnover %",           False),
        ("OREB%",     adv["oreb_p"]*100,         "Off. Rebound %",       True),
        ("FT Rate",   adv["ft_r"]*100,           "FT Rate (×100)",       True),
        ("Opp eFG%",  adv["oefg"]*100,           "Opp eFG% (D)",         False),
        ("Opp TOV%",  adv.get("opp_tov_r",0)*100,"Opp TOV% (D)",         True),
        ("DREB%",     adv.get("dreb_p",0)*100,   "Def. Rebound %",       True),
        ("Opp FT Rate",adv.get("opp_ft_r",0)*100,"Opp FT Rate (D, ×100)",False),
    ]
    labels = [f[2] for f in factors]
    team_vals = [round(f[1],1) for f in factors]
    higher_better = [f[3] for f in factors]

    team_colors = []
    for tv, hb, (_,la) in zip(team_vals, higher_better,
                               [(k, league_avgs.get(k,0)*100 if league_avgs else 0)
                                for k,_,_,_ in factors]):
        if league_avgs is None:
            team_colors.append("#4c8edd")
        else:
            better = (tv > la) if hb else (tv < la)
            team_colors.append("#1a9850" if better else "#d73027")

    fig = go.Figure()
    fig.add_trace(go.Bar(name="This Team", x=labels, y=team_vals,
                         marker_color=team_colors, opacity=0.9,
                         text=[f"{v:.1f}" for v in team_vals],
                         textposition="outside",
                         hovertemplate="%{x}<br>%{y:.1f}<extra>This Team</extra>"))
    if league_avgs:
        la_vals = []
        for k,_,_,_ in factors:
            raw = league_avgs.get(k, 0)
            la_vals.append(round(raw*100, 1) if raw <= 1.5 else round(raw, 1))
        fig.add_trace(go.Bar(name="League Avg", x=labels, y=la_vals,
                             marker_color="rgba(150,150,150,0.5)",
                             hovertemplate="%{x}<br>%{y:.1f}<extra>League Avg</extra>"))
        fig.update_layout(barmode="group")

    fig.update_layout(
        title="Dean Oliver's Four Factors  (green = better than league avg)",
        yaxis_title="Value",
        height=380, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20,r=20,t=60,b=80),
        xaxis=dict(tickangle=-30, gridcolor="rgba(128,128,128,0.1)"),
        yaxis=dict(gridcolor="rgba(128,128,128,0.15)"),
        legend=dict(orientation="h", y=1.06),
        font=dict(size=11),
    )
    st.plotly_chart(fig, width='stretch')


def show_trend_chart(game_log: list, team_name: str = "Team"):
    """Plotly line chart of per-game ORtg, DRtg, and point margin."""
    if not game_log: return
    df = pd.DataFrame(game_log)
    df["Date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")
    df["Label"] = df.apply(lambda r: f"{r['date']} vs {r['opp']}", axis=1)

    fig = go.Figure()
    for col, color, name in [
        ("ortg",   "#1a9850", "ORtg"),
        ("drtg",   "#d73027", "DRtg"),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Label"], y=df[col], mode="lines+markers",
                name=name, line=dict(color=color, width=2),
                marker=dict(size=7, color=color),
                hovertemplate=f"%{{x}}<br>{name}: %{{y:.1f}}<extra></extra>",
            ))
    if "margin" in df.columns:
        bar_colors = ["#1a9850" if m >= 0 else "#d73027" for m in df["margin"]]
        fig.add_trace(go.Bar(
            x=df["Label"], y=df["margin"], name="Margin",
            marker_color=bar_colors, opacity=0.4,
            hovertemplate="%{x}<br>Margin: %{y:+.0f}<extra></extra>",
            yaxis="y2",
        ))
    fig.update_layout(
        title=f"{team_name} — Game-by-Game Trends",
        xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
        yaxis=dict(title="Rating (pts/100 poss)", gridcolor="rgba(128,128,128,0.15)"),
        yaxis2=dict(title="Score Margin", overlaying="y", side="right",
                    zeroline=True, zerolinecolor="rgba(200,200,200,0.4)",
                    showgrid=False),
        height=400, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20,r=40,t=60,b=100), legend=dict(orientation="h",y=1.06),
        font=dict(size=11),
    )
    st.plotly_chart(fig, width='stretch')


def show_player_radar(df_pl: pd.DataFrame, key: str = "player_radar"):
    """Radar chart comparing players on the current roster."""
    if df_pl.empty: return
    eligible = df_pl[df_pl["GP"] > 0]["Player"].tolist()
    if not eligible: return
    selected = st.multiselect("Compare players (2–5)", eligible, max_selections=5, key=key)
    if len(selected) < 2:
        st.caption("Select at least 2 players to compare.")
        return
    axes = [
        ("PTS",   "Scoring",  True),
        ("AST",   "Assists",  True),
        ("REB",   "Rebounds", True),
        ("STL",   "Steals",   True),
        ("BLK",   "Blocks",   True),
        ("TS%",   "TS%",      True),
        ("Usg%",  "Usage%",   True),
        ("TOV",   "TOV",      False),
    ]
    cats = [label for _,label,_ in axes]
    cols = [c for c,_,_ in axes]
    hibs = [h for _,_,h in axes]

    numeric_df = df_pl.copy()
    for c in cols:
        if c in numeric_df.columns:
            numeric_df[c] = pd.to_numeric(numeric_df[c], errors="coerce").fillna(0)

    normed = {}
    for c, hib in zip(cols, hibs):
        if c not in numeric_df.columns: continue
        s = numeric_df[c]
        lo, hi = s.min(), s.max()
        normed[c] = ((s-lo)/(hi-lo) if hi!=lo else pd.Series(0.5, index=s.index))
        if not hib: normed[c] = 1 - normed[c]
        normed[c] = (normed[c]*100).round(1)

    palette = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd"]
    fig = go.Figure()
    for i, player in enumerate(selected):
        row = numeric_df[numeric_df["Player"] == player]
        if row.empty: continue
        idx = row.index[0]
        nv = [normed.get(c, pd.Series([50]))[idx] for c in cols if c in normed]
        rv = [row[c].values[0] for c in cols if c in normed]
        cats_used = [cats[j] for j,c in enumerate(cols) if c in normed]
        hover = "<br>".join(f"{cat}: {rv_:.1f}" for cat,rv_ in zip(cats_used,rv))
        color = palette[i % len(palette)]
        fig.add_trace(go.Scatterpolar(
            r=nv+[nv[0]], theta=cats_used+[cats_used[0]],
            fill="toself", fillcolor=color, line=dict(color=color,width=2),
            opacity=0.25, name=player,
            hovertemplate=f"<b>{player}</b><br>{hover}<extra></extra>",
        ))
        fig.add_trace(go.Scatterpolar(
            r=nv+[nv[0]], theta=cats_used+[cats_used[0]],
            mode="lines+markers", line=dict(color=color,width=2),
            marker=dict(size=6,color=color), showlegend=False, hoverinfo="skip",
        ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True,range=[0,100],showticklabels=False,
                            gridcolor="rgba(150,150,150,0.2)"),
            angularaxis=dict(tickfont=dict(size=11)),bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=True, height=450,
        margin=dict(l=50,r=50,t=50,b=50), paper_bgcolor="rgba(0,0,0,0)",
        title="Player Comparison (normalized vs team, 100 = best on roster)",
        legend=dict(orientation="h",y=-0.1),font=dict(size=11),
    )
    st.plotly_chart(fig, width='stretch')
