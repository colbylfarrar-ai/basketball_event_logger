"""
6_Players.py — the player hub (everything about players, one destination).

Reads from one comprehensive per-player stat table
(helpers/player_ratings.player_stat_table):

  • Leaders         — dashboard leaders + offense/defense map + the full table,
                      then the Best Five top-5 leaders for every stat we track.
  • Ratings         — every 0-100 rating, who leads each, and the best per class.
  • Shot Lab        — court charts, zone efficiency and shot-making.
  • Compare         — two players head-to-head (radar + stat deltas).
  • Player Profile  — one player's card: ratings, full stat line, game log.
  • Lab             — the next-gen layer (folds in the old Player Lab page):
                      badges, data-driven archetypes + similarity, empirical-Bayes
                      stabilized stats, and who-guarded-whom matchup intelligence.

All math lives in helpers/player_ratings.py, helpers/stats.py and the Lab engines
(badges / archetypes / shrinkage / matchups); this page is display + controls only.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import defaultdict

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.ui import (page_chrome, rgb as _rgb, style_fig as _style,
                        CARD_BG, GRID, PALETTE)
from helpers.glossary import glossary_tab
import helpers.player_ratings as PR
import helpers.team_ratings as TR
import helpers.stats as S
import helpers.badges as BG
import helpers.archetypes as ARC
import helpers.shrinkage as SH
import helpers.matchups as MX

_cfg, ACCENT = page_chrome()
RATING_COLS = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]

# percentile-bar + card styling (used in Compare / Profile). The structural
# "lab" classes (.lab-hero/.glass-tile/.lab-hdr/.spotlight/.stat-chip) live in
# assets/styles.css; here we add the accent-tinted glows (accent is dynamic) and
# the page-local percentile / scout / shot-lab pieces.
ar0, ag0, ab0 = _rgb(ACCENT)
st.markdown(f"""
<style>
.pl-pct {{ margin-bottom:9px; }}
.pl-pct-top {{ display:flex; justify-content:space-between; align-items:center;
              margin-bottom:3px; }}
.pl-pct-lbl {{ font-size:12px; color:#c9d1d9; }}
.pl-pct-val {{ font-size:12px; font-weight:700; color:#f0f6fc; }}
.pl-pct-track {{ background:#21262d; border-radius:4px; height:7px; overflow:hidden; }}
.pl-pct-fill  {{ height:100%; border-radius:4px; }}
.pl-scout {{ background:#161b22; border:1px solid #30363d; border-radius:10px;
            padding:14px; height:100%; }}
/* accent-tinted neon header (dynamic accent overrides the cyan default) */
.pl-hdr {{ font-size:16px; font-weight:800; color:#f0f6fc; text-transform:uppercase;
          letter-spacing:1.5px; border-left:3px solid {ACCENT}; padding-left:11px;
          margin:18px 0 10px; text-shadow:0 0 18px rgba({ar0},{ag0},{ab0},0.35); }}
/* glass tile (futuristic KPI) */
.pl-glass {{ background:rgba(22,27,34,0.55); -webkit-backdrop-filter:blur(8px);
            backdrop-filter:blur(8px); border:1px solid rgba(48,54,61,0.9);
            border-radius:14px; padding:13px 15px; text-align:center; height:100%;
            box-sizing:border-box; }}
.pl-glass-l {{ font-size:9px; color:#8b949e; text-transform:uppercase;
              letter-spacing:1.3px; font-weight:700; }}
.pl-glass-v {{ font-size:25px; font-weight:900; line-height:1.15; margin-top:4px; }}
.pl-glass-s {{ font-size:10px; color:#8b949e; margin-top:2px; }}
/* "made-up metric" spotlight */
.pl-spot {{ background:radial-gradient(600px 80px at 50% -30%, rgba({ar0},{ag0},{ab0},0.14),
            transparent 70%), linear-gradient(135deg,#0d1117,#161b22);
            border:1px solid rgba({ar0},{ag0},{ab0},0.35); border-radius:16px;
            padding:16px 14px; text-align:center; height:100%; box-sizing:border-box; }}
.pl-spot-n {{ font-size:34px; font-weight:900; line-height:1; color:{ACCENT};
             text-shadow:0 0 22px rgba({ar0},{ag0},{ab0},0.45); }}
.pl-spot-l {{ font-size:10px; color:#c9d1d9; text-transform:uppercase;
             letter-spacing:1.3px; margin-top:7px; font-weight:700; }}
.pl-spot-s {{ font-size:10px; color:#6e7681; margin-top:4px; }}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Every tracked stat: (key, label, fmt, higher_better, qualify_key, qualify_min)
#   fmt      "int" | "f1" | "f2" | "pct"
#   qualify  drop players whose [qualify_key] total is below qualify_min (keeps a
#            1-for-1 three-point night off the 3P% leaderboard). None = no gate.
STAT_GROUPS = [
    ("Scoring", [
        ("PTS", "Points", "int", True, None, 0),
        ("PPG", "Points / game", "f1", True, None, 0),
        ("PRF", "Points responsible for", "int", True, None, 0),
        ("PaintPTS", "Paint points", "int", True, None, 0),
        ("FGM", "Field goals made", "int", True, None, 0),
        ("3PM", "Threes made", "int", True, None, 0),
        ("FTM", "Free throws made", "int", True, None, 0),
    ]),
    ("Shooting efficiency", [
        ("FG%", "Field goal %", "pct", True, "FGA", 10),
        ("2P%", "Two-point %", "pct", True, "2PA", 8),
        ("3P%", "Three-point %", "pct", True, "3PA", 8),
        ("FT%", "Free throw %", "pct", True, "FTA", 6),
        ("eFG%", "Effective FG %", "pct", True, "FGA", 10),
        ("TS%", "True shooting %", "pct", True, "FGA", 10),
        ("PPS", "Points / shot (FG)", "f2", True, "FGA", 10),
        ("Paint%", "Paint FG %", "pct", True, "PaintA", 6),
        ("3PR", "Three-point rate", "pct", True, "FGA", 10),
        ("FTR", "Free throw rate", "f2", True, "FGA", 10),
        ("xFG%", "Expected FG %", "pct", True, "FGA", 10),
        ("SMOE", "Shot-making over expected", "spp", True, "FGA", 10),
    ]),
    ("Rebounding", [
        ("REB", "Rebounds", "int", True, None, 0),
        ("RPG", "Rebounds / game", "f1", True, None, 0),
        ("OREB", "Offensive rebounds", "int", True, None, 0),
        ("DREB", "Defensive rebounds", "int", True, None, 0),
        ("REB%", "Rebound % (on court)", "pct", True, None, 0),
        ("OREB%", "Off. rebound %", "pct", True, None, 0),
        ("DREB%", "Def. rebound %", "pct", True, None, 0),
    ]),
    ("Playmaking", [
        ("AST", "Assists", "int", True, None, 0),
        ("APG", "Assists / game", "f1", True, None, 0),
        ("AST/TOV", "Assist / turnover", "f2", True, None, 0),
        ("AST3", "Three-point assists", "int", True, None, 0),
        ("SC", "Shots created", "int", True, None, 0),
        ("SC/G", "Shots created / game", "f1", True, None, 0),
        ("TOV", "Fewest turnovers", "int", False, None, 0),
    ]),
    ("Defense", [
        ("STOCKS", "Stocks (STL+BLK)", "int", True, None, 0),
        ("STL", "Steals", "int", True, None, 0),
        ("BLK", "Blocks", "int", True, None, 0),
        ("SPG", "Steals / game", "f1", True, None, 0),
        ("BPG", "Blocks / game", "f1", True, None, 0),
        ("Guarded%", "Guarded % (on court)", "pct", True, None, 0),
        ("DSHOT%", "Defended FG % (lowest)", "pct", False, "defFGA", 10),
        ("PF", "Fewest fouls", "int", False, None, 0),
    ]),
    ("Impact & usage", [
        ("MIN", "Minutes", "f1", True, None, 0),
        ("MPG", "Minutes / game", "f1", True, None, 0),
        ("+/-", "Plus / minus", "int", True, None, 0),
        ("+/-/G", "Plus / minus per game", "f1", True, None, 0),
        ("USG%", "Usage %", "pct", True, "MIN", 20),
        ("TOV%", "Turnover % (lowest)", "pct", False, "FGA", 10),
    ]),
    ("Advanced", [
        ("GS", "Game Score (total)", "f1", True, None, 0),
        ("GS/G", "Game Score / game", "f1", True, None, 0),
        ("EFF", "Efficiency (EFF)", "int", True, None, 0),
        ("FIC", "Floor Impact (FIC)", "f1", True, None, 0),
        ("PPP", "Points / possession", "f2", True, "FGA", 10),
        ("ShotRating", "Shot difficulty", "f1", True, "FGA", 10),
        ("xPPS", "Expected pts / shot", "f2", True, "FGA", 10),
    ]),
    ("Shot creation & location", [
        ("SelfCr%", "Self-created shot %", "pct", True, "FGA", 12),
        ("Astd%", "Assisted shot %", "pct", True, "FGA", 12),
        ("RimFGA%", "Rim shot share", "pct", True, "FGA", 12),
        ("MidFGA%", "Mid-range share", "pct", True, "FGA", 12),
    ]),
    ("Clutch, versatility & disruption", [
        ("VERSATILITY", "Versatility index", "f1", True, None, 0),
        ("2WAY", "Two-way index", "f1", True, None, 0),
        ("Q4PPG", "4th-quarter PPG", "f1", True, None, 0),
        ("Q4%", "Clutch scoring share", "pct", True, "PTS", 20),
        ("STOCKS/32", "Disruption / 32 min", "f1", True, "MIN", 20),
    ]),
    ("Milestones & consistency", [
        ("DD", "Double-doubles", "int", True, None, 0),
        ("bestPTS", "Career-high points", "int", True, None, 0),
        ("bestREB", "Career-high rebounds", "int", True, None, 0),
        ("bestAST", "Career-high assists", "int", True, None, 0),
        ("PTSsd", "Scoring volatility (σ, low=steady)", "f1", False, None, 0),
    ]),
    ("Ratings", [
        ("OVERALL", "Overall", "f1", True, None, 0),
        ("OFFENSE", "Offense", "f1", True, None, 0),
        ("DEFENSE", "Defense", "f1", True, None, 0),
        ("PLAYMAKING", "Playmaking", "f1", True, None, 0),
        ("REBOUNDING", "Rebounding", "f1", True, None, 0),
        ("Shooting", "Shooting", "f1", True, None, 0),
        ("Finishing", "Finishing", "f1", True, None, 0),
    ]),
]


def _fmt(v, fmt):
    if v is None:
        return "—"
    if fmt == "int":
        return f"{int(v)}"
    if fmt == "f1":
        return f"{v:.1f}"
    if fmt == "f2":
        return f"{v:.2f}"
    if fmt == "pct":
        return f"{v:.1f}%"
    if fmt == "spp":              # signed percentage points (e.g. SMOE)
        return f"{v:+.1f}"
    return str(v)


def _leaders(rows, key, higher=True, n=5, qkey=None, qmin=0):
    """Top-n rows by `key`, dropping None and players under the qualify gate."""
    pool = [r for r in rows if r.get(key) is not None]
    if qkey:
        pool = [r for r in pool if (r.get(qkey) or 0) >= qmin]
    pool.sort(key=lambda r: r[key], reverse=higher)
    return pool[:n]


# one accent per Best-Five group so the wall of charts stays legible
GROUP_COLORS = {
    "Scoring": "#f0a500", "Shooting efficiency": "#58a6ff",
    "Rebounding": "#3fb950", "Playmaking": "#bc8cff",
    "Defense": "#e74c3c", "Impact & usage": "#d29922",
    "Advanced": "#f778ba", "Ratings": "#56d4dd",
    "Shot creation & location": "#00e5ff",
    "Clutch, versatility & disruption": "#ff7b72",
    "Milestones & consistency": "#d2a8ff",
}


def _team_short(team):
    """Trim the redundant gender suffix so team labels stay compact."""
    for suf in (" Girls", " Boys"):
        if team.endswith(suf):
            return team[:-len(suf)]
    return team


def _leader_bar(top, key, fmt, color=ACCENT, height=200):
    """Horizontal bar chart of a top-N leader list (#1 on top)."""
    seq = list(reversed(top))                      # plotly draws first at bottom
    names = [f"{r['name']}<br><span style='font-size:9px;color:#8b949e'>"
             f"{_team_short(r['team'])}</span>" for r in seq]
    vals = [r[key] for r in seq]
    texts = [_fmt(v, fmt) for v in vals]
    fig = go.Figure(go.Bar(
        x=vals, y=names, orientation="h", marker_color=color,
        marker_line_width=0, text=texts, textposition="auto",
        textfont=dict(size=11), cliponaxis=False,
        hovertemplate="%{y}: %{text}<extra></extra>"))
    fig.update_layout(
        template="plotly_dark", height=height, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=4, r=14, t=6, b=6),
        showlegend=False, font=dict(size=11, color="#c9d1d9"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=11), automargin=True)
    return fig


# ── percentile + tier + podium (ported from APP3.0 ideas) ─────────────────────

def _pctile(val, key, pool, lower_better=False):
    """Percentile rank of `val` for stat `key` within `pool` (0-100)."""
    vals = [r[key] for r in pool if r.get(key) is not None]
    if val is None or not vals:
        return None
    below = sum(1 for v in vals if v < val)
    eq = sum(1 for v in vals if v == val)
    p = (below + 0.5 * eq) / len(vals) * 100
    return round(100 - p) if lower_better else round(p)


def _pctile_color(p):
    if p is None:
        return "#8b949e"
    return ("#2ea043" if p >= 75 else "#3fb950" if p >= 50
            else "#f0a500" if p >= 25 else "#da3633")


def _pctile_bar(label, value_str, p):
    """One percentile-bar row of HTML."""
    c = _pctile_color(p)
    w = 0 if p is None else max(2, min(100, p))
    rank = f"{p}th" if p is not None else "—"
    return (f"<div class='pl-pct'><div class='pl-pct-top'>"
            f"<span class='pl-pct-lbl'>{label}</span>"
            f"<span class='pl-pct-val'>{value_str} · "
            f"<span style='color:{c}'>{rank}</span></span></div>"
            f"<div class='pl-pct-track'><div class='pl-pct-fill' "
            f"style='width:{w}%;background:{c}'></div></div></div>")


def _tier(ovrl):
    """(color, label) tier off the OVERALL rating (50 = pool average)."""
    if ovrl is None:
        return ("#8b949e", "UNRATED")
    if ovrl >= 70:
        return ("#f0a500", "ELITE")
    if ovrl >= 62:
        return ("#2ecc71", "GREAT")
    if ovrl >= 54:
        return ("#58a6ff", "ABOVE AVG")
    if ovrl >= 46:
        return ("#c9d1d9", "AVERAGE")
    return ("#8b949e", "DEVELOPING")


def _podium(top3, key, fmt):
    """Gold/silver/bronze top-3 cards for a stat."""
    icons = ["🥇", "🥈", "🥉"]
    styles = [("#f0a500", "#3a2a00"), ("#adb5bd", "#1e2229"),
              ("#cd7f32", "#271505")]
    cols = st.columns(min(3, len(top3)) or 1)
    for i, (col, r) in enumerate(zip(cols, top3)):
        c, bg = styles[i]
        col.markdown(
            f"<div style='background:linear-gradient(135deg,{bg},#0d1117);"
            f"border:1px solid {c};border-radius:12px;padding:14px;"
            f"text-align:center'>"
            f"<div style='font-size:26px'>{icons[i]}</div>"
            f"<div style='font-size:15px;font-weight:800;color:#f0f6fc;"
            f"margin-top:4px'>{r['name']}</div>"
            f"<div style='font-size:11px;color:#8b949e'>"
            f"{_team_short(r['team'])} · {r['class']}</div>"
            f"<div style='font-size:26px;font-weight:800;color:{c};"
            f"margin-top:6px'>{_fmt(r[key], fmt)}</div></div>",
            unsafe_allow_html=True)


def _onoff_html(label, on_v, off_v, on_n, off_n, n_lbl="opps",
                higher_better=True):
    """On-court vs off-court comparison card with a coloured delta."""
    on_s = f"{on_v:.1f}%" if on_v is not None else "—"
    off_s = f"{off_v:.1f}%" if off_v is not None else "—"
    if on_v is None or off_v is None:
        d, dclr, dstr, impact = None, "#8b949e", "—", "~ Neutral"
    else:
        d = on_v - off_v
        good = (d > 1) if higher_better else (d < -1)
        bad = (d < -1) if higher_better else (d > 1)
        dclr = "#2ea043" if good else "#da3633" if bad else "#f0a500"
        dstr = f"{d:+.1f}%"
        impact = "↑ Positive" if good else "↓ Negative" if bad else "~ Neutral"
    return (
        f"<div style='background:#161b22;border:1px solid #30363d;"
        f"border-radius:10px;padding:14px'>"
        f"<div style='font-size:11px;color:#8b949e;text-transform:uppercase;"
        f"letter-spacing:1px;margin-bottom:8px'>{label}</div>"
        f"<div style='display:flex;justify-content:space-around;"
        f"align-items:center;margin-bottom:8px'>"
        f"<div style='text-align:center'>"
        f"<div style='font-size:9px;color:#8b949e'>ON COURT</div>"
        f"<div style='font-size:24px;font-weight:800;color:#f0f6fc'>{on_s}</div>"
        f"<div style='font-size:10px;color:#484f58'>{n_lbl}={on_n}</div></div>"
        f"<div style='font-size:18px;color:#30363d'>vs</div>"
        f"<div style='text-align:center'>"
        f"<div style='font-size:9px;color:#8b949e'>OFF COURT</div>"
        f"<div style='font-size:24px;font-weight:800;color:#f0f6fc'>{off_s}</div>"
        f"<div style='font-size:10px;color:#484f58'>{n_lbl}={off_n}</div></div>"
        f"</div>"
        f"<div style='text-align:center;padding:6px;background:#0d1117;"
        f"border-radius:6px'><span style='font-weight:700;color:{dclr}'>{dstr}</span>"
        f"<span style='font-size:11px;color:{dclr};margin-left:6px'>{impact}</span>"
        f"</div></div>")


# ── glass tile + spotlight (futuristic KPI cards) ─────────────────────────────

def _glass(label, value, sub="", color="#f0f6fc"):
    """Glassmorphism KPI tile (HTML string)."""
    return (f"<div class='pl-glass'><div class='pl-glass-l'>{label}</div>"
            f"<div class='pl-glass-v' style='color:{color}'>{value}</div>"
            f"<div class='pl-glass-s'>{sub}</div></div>")


def _spotlight(num, label, sub=""):
    """Neon spotlight tile for a 'made-up'/headline metric (HTML string)."""
    return (f"<div class='pl-spot'><div class='pl-spot-n'>{num}</div>"
            f"<div class='pl-spot-l'>{label}</div>"
            f"<div class='pl-spot-s'>{sub}</div></div>")


def _gauge(value, title, color, ref=50, vmax=100, vmin=0):
    """Plotly Indicator gauge (futuristic dial). value/ref on a 0-vmax scale."""
    if value is None:
        value = 0
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta", value=value,
        delta={"reference": ref, "increasing": {"color": "#2ea043"},
               "decreasing": {"color": "#da3633"}},
        number={"font": {"size": 26, "color": "#f0f6fc"}},
        title={"text": title, "font": {"size": 12, "color": "#8b949e"}},
        gauge={
            "axis": {"range": [vmin, vmax], "tickwidth": 1,
                     "tickcolor": "#30363d", "tickfont": {"size": 8}},
            "bar": {"color": color, "thickness": 0.28},
            "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "steps": [
                {"range": [vmin, ref], "color": "rgba(48,54,61,0.35)"},
                {"range": [ref, vmax], "color": "rgba(48,54,61,0.15)"}],
            "threshold": {"line": {"color": "#8b949e", "width": 2},
                          "thickness": 0.75, "value": ref}}))
    fig.update_layout(height=190, paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=18, r=18, t=40, b=8),
                      font=dict(color="#c9d1d9"))
    return fig


# ── shot chart + hot zones (every shot in this DB carries a zone) ─────────────
#  Court coords in feet (basket at origin, +y toward half-court). Zone-bubble
#  positions mirror the APP3.0 half-court layout.
_ZONE_XY = {
    ("C", 2): (0, 7),    ("C", 3): (0, 23),
    ("LC", 2): (-14, 5),  ("LC", 3): (-21, 9),
    ("LW", 2): (-13, 11), ("LW", 3): (-18, 15),
    ("RW", 2): (13, 11),  ("RW", 3): (18, 15),
    ("RC", 2): (14, 5),   ("RC", 3): (21, 9),
}
_ZONE_FULLNAME = {"LC": "Left corner", "LW": "Left wing", "C": "Center / top",
                  "RW": "Right wing", "RC": "Right corner"}


def _fgp_color(p, a):
    """Red→gold→green by FG% (None/empty = grey)."""
    if not a:
        return "#2d333b"
    return "#1a9850" if p >= 0.45 else "#f4a724" if p >= 0.30 else "#d73027"


def _shot_chart(zone_data, title="Shot chart", height=430):
    """Plotly zone-bubble half-court. zone_data = {(zone,stype):{FGA,FGM,pct}}."""
    fig = go.Figure()
    LINE, DIM = "rgba(220,220,220,0.65)", "rgba(180,180,180,0.30)"
    GOLD = "rgba(230,190,100,0.95)"
    R3, CORNER_X = 23.0, 21.5
    cbreak = float(np.sqrt(max(0, R3 ** 2 - CORNER_X ** 2)))
    LANE_W, LANE_D, FT_R, RA_R = 6.0, 15.0, 6.0, 3.0

    def _ln(x0, y0, x1, y1, c=LINE, w=1.5):
        fig.add_shape(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color=c, width=w))

    def _arc(cx, cy, r, t0, t1, c=LINE, w=1.5, dash="solid", n=90):
        th = np.linspace(t0, t1, n)
        fig.add_trace(go.Scatter(x=cx + r * np.cos(th), y=cy + r * np.sin(th),
                                 mode="lines", line=dict(color=c, width=w, dash=dash),
                                 showlegend=False, hoverinfo="skip"))

    _ln(-25, 0, 25, 0, LINE, 2)                                   # baseline
    t_c = float(np.arcsin(cbreak / R3))
    _arc(0, 0, R3, np.pi - t_c, t_c, n=120)                       # 3pt arc
    _ln(-CORNER_X, 0, -CORNER_X, cbreak)
    _ln(CORNER_X, 0, CORNER_X, cbreak)
    fig.add_shape(type="rect", x0=-LANE_W, y0=0, x1=LANE_W, y1=LANE_D,
                  line=dict(color=LINE, width=1.5), fillcolor="rgba(255,255,255,0.03)")
    _ln(-LANE_W, LANE_D, LANE_W, LANE_D)
    _arc(0, LANE_D, FT_R, 0, np.pi)
    _arc(0, LANE_D, FT_R, np.pi, 2 * np.pi, DIM, 1, "dot")
    _arc(0, 0, RA_R, 0, np.pi, DIM, 1)
    _ln(-3, -0.5, 3, -0.5, GOLD, 2.5)                             # backboard
    fig.add_shape(type="circle", x0=-0.75, y0=-0.75, x1=0.75, y1=0.75,
                  line=dict(color=GOLD, width=2.5), fillcolor="rgba(0,0,0,0)")

    items = sorted(zone_data.items(), key=lambda x: x[1]["FGA"], reverse=True)
    any_bubble = False
    for (zone, stype), d in items:
        pos = _ZONE_XY.get((zone, stype))
        if not pos or d["FGA"] == 0:
            continue
        any_bubble = True
        fga, fgm, fgp = d["FGA"], d["FGM"], d["pct"]
        size = max(18, min(54, 12 + fga * 4))
        fig.add_trace(go.Scatter(
            x=[pos[0]], y=[pos[1]], mode="markers+text",
            marker=dict(size=size, color=_fgp_color(fgp, fga), sizemode="diameter",
                        line=dict(color="rgba(255,255,255,0.9)", width=1.5), opacity=0.92),
            text=[f"<b>{fgp*100:.0f}%</b>"], textposition="middle center",
            textfont=dict(size=max(9, min(13, int(size // 4))), color="white",
                          family="Arial Black"),
            hovertext=[f"<b>{stype}PT — {_ZONE_FULLNAME.get(zone, zone)}</b><br>"
                       f"{fgm}/{fga} · {fgp*100:.1f}%"],
            hoverinfo="text", showlegend=False))
        fig.add_annotation(x=pos[0], y=pos[1] - size / 46 - 1.6, text=f"{fgm}/{fga}",
                           showarrow=False, font=dict(size=8, color="rgba(255,255,255,0.7)"))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#c9d1d9"), x=0.02),
        xaxis=dict(range=[-26, 26], visible=False),
        yaxis=dict(range=[-5, 32], visible=False, scaleanchor="x", scaleratio=1),
        height=height, margin=dict(l=5, r=5, t=42, b=5),
        plot_bgcolor="rgba(18,20,30,1)", paper_bgcolor="rgba(0,0,0,0)")
    return fig, any_bubble


def _hot_zones(zone_data):
    """5-zone (LC/LW/C/RW/RC) make/attempt grid for 2PT and 3PT, rendered inline."""
    for stype, lbl in [(2, "2-Point"), (3, "3-Point")]:
        st.markdown(f"<span style='font-size:12px;color:#8b949e'>{lbl}</span>",
                    unsafe_allow_html=True)
        cols = st.columns(5)
        for col, zone in zip(cols, ("LC", "LW", "C", "RW", "RC")):
            d = zone_data.get((zone, stype), {"FGA": 0, "FGM": 0, "pct": 0.0})
            m, a = d["FGM"], d["FGA"]
            pct = d["pct"] * 100 if a else 0
            bg = _fgp_color(d["pct"], a)
            fg = "#fff" if a else "#6e7681"
            col.markdown(
                f"<div style='background:{bg};color:{fg};padding:11px 4px;"
                f"border-radius:8px;text-align:center;font-size:12px'>"
                f"<b>{zone}</b><br>{m}/{a}<br>{pct:.0f}%</div>",
                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER + CONTROLS
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    f"<div class='lab-hero'>"
    f"<div class='lab-hero-name' style='color:{ACCENT}'>PLAYER ANALYTICS LAB</div>"
    f"<div class='lab-hero-sub'>Every tracked stat · shot charts · 0-100 ratings · "
    f"invented metrics — all built from play-by-play events.</div></div>",
    unsafe_allow_html=True)

c1, c2 = st.columns([1, 2])
gender = c1.radio("League", ["F", "M"],
                  format_func=lambda g: "Girls" if g == "F" else "Boys",
                  horizontal=True)
min_games = c2.slider("Minimum games played", 1, 16, 2, 1,
                      help="Players below this drop out of the pool. Higher "
                           "values cut small-sample noise but shrink the field. "
                           "Ratings are recomputed against whoever qualifies.")

@st.cache_data(ttl=600, show_spinner=False)
def _stat_table(g, mg):
    return PR.player_stat_table(gender=g, min_games=mg)


@st.cache_data(ttl=600, show_spinner=False)
def _zone_tables():
    """Per-player zone splits + guarded/open splits (whole tracked sample)."""
    ev = S.fetch_events()
    return S.player_zone_splits(events=ev), S.player_zone_guarded(events=ev)


def _agg_zone(pids, zsplits):
    """Sum many players' zone splits into one league/team {(zone,stype):cell}."""
    agg = defaultdict(lambda: {"FGA": 0, "FGM": 0})
    for pid in pids:
        for k, v in zsplits.get(pid, {}).items():
            agg[k]["FGA"] += v["FGA"]
            agg[k]["FGM"] += v["FGM"]
    return {k: {"FGA": v["FGA"], "FGM": v["FGM"],
                "pct": (v["FGM"] / v["FGA"] if v["FGA"] else 0.0)}
            for k, v in agg.items()}


table = _stat_table(gender, min_games)
if not table:
    st.info("No eligible players for this league / games filter yet. Track some "
            "games in the Game Tracker and they'll show up here.")
    st.stop()

rows = sorted(table.values(), key=lambda r: (r["Rank"] or 1e9))
by_pid = table

# live league chips (futuristic stat-chip strip under the hero)
_ppg_lead = _leaders(rows, "PPG")[0]
_ovr_lead = _leaders(rows, "OVERALL")[0]
_teams_n = len({r["team_id"] for r in rows})
st.markdown(
    "<div class='form-strip' style='margin:-6px 0 12px'>"
    f"<span class='stat-chip'>🏀 <b>{len(rows)}</b> players</span>"
    f"<span class='stat-chip'>🏫 <b>{_teams_n}</b> teams</span>"
    f"<span class='stat-chip'>🔥 PPG <b>{_ppg_lead['PPG']:.1f}</b> · {_ppg_lead['name']}</span>"
    f"<span class='stat-chip'>👑 OVR <b>{_ovr_lead['OVERALL']:.1f}</b> · {_ovr_lead['name']}</span>"
    "</div>", unsafe_allow_html=True)

# per-player zone splits + guarded/open (shared by Shot Lab, Compare, Profile)
zsplits, zguard = _zone_tables()


# ── full-pool data for the 🧪 Lab tab (badges/archetypes/stabilized/matchups all
#    run on every qualified player, not the slider-filtered set; cached so they
#    don't recompute on the main page's interactions) ──────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _table_full(g):
    return PR.player_stat_table(gender=g, min_games=1)


@st.cache_data(ttl=600, show_spinner=False)
def _lab_badges(g):
    return BG.award_badges(_table_full(g))


@st.cache_data(ttl=600, show_spinner=False)
def _lab_clusters(g):
    return ARC.cluster_players(_table_full(g))


@st.cache_data(ttl=600, show_spinner=False)
def _lab_stab(g):
    return SH.stabilize_table(_table_full(g))


@st.cache_data(ttl=600, show_spinner=False)
def _lab_names(g):
    return MX.player_names(gender=g)


(tab_lead, tab_rate, tab_shot, tab_cmp, tab_prof, tab_plab, tab_gloss) = st.tabs(
    ["📊 Leaders", "⭐ Ratings", "🔬 Shot Lab",
     "🆚 Compare", "🪪 Player Profile", "🧪 Lab", "📖 Glossary"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — LEADERS  (overview superlatives + Best Five category leaders)
# ══════════════════════════════════════════════════════════════════════════════
with tab_lead:
    st.caption("The league at a glance — who scores, who rates out on top, and "
               "the full sortable stat table. Built from tracked-game events; "
               "small samples are directional.")

    ppg_lead = _leaders(rows, "PPG")[0]
    ovr_lead = _leaders(rows, "OVERALL")[0]
    teams_n = len({r["team_id"] for r in rows})

    # ── Overall leader hero banner ────────────────────────────────────────────
    hue, tier = _tier(ovr_lead["OVERALL"])
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#1a0d2e 0%,#0d1117 100%);"
        f"border:2px solid {hue};border-radius:16px;padding:20px 26px;"
        f"margin-bottom:16px;display:flex;align-items:center;gap:22px'>"
        f"<div style='font-size:40px'>👑</div>"
        f"<div style='flex:1'>"
        f"<div style='font-size:10px;color:{hue};text-transform:uppercase;"
        f"letter-spacing:1.5px;font-weight:700'>Overall rating leader · {tier}</div>"
        f"<div style='font-size:24px;font-weight:900;color:#f0f6fc;margin:3px 0'>"
        f"{ovr_lead['name']}</div>"
        f"<div style='font-size:13px;color:#8b949e'>{ovr_lead['team']} · "
        f"{ovr_lead['class']} · {ovr_lead['GP']} GP · {ovr_lead['PPG']:.1f} PTS · "
        f"{ovr_lead['RPG']:.1f} REB · {ovr_lead['APG']:.1f} AST</div></div>"
        f"<div style='text-align:right'><div style='font-size:52px;font-weight:900;"
        f"color:{hue};line-height:1'>{ovr_lead['OVERALL']:.1f}</div>"
        f"<div style='font-size:11px;color:#8b949e;letter-spacing:1px'>OVERALL</div>"
        f"</div></div>", unsafe_allow_html=True)

    # ── new "invented metric" league superlatives (spotlight row) ────────────
    st.markdown("<div class='pl-hdr'>League superlatives — the new metrics</div>",
                unsafe_allow_html=True)
    vers_l = _leaders(rows, "VERSATILITY", n=1)
    smoe_l = _leaders(rows, "SMOE", n=1, qkey="FGA", qmin=15)
    tw_l   = _leaders(rows, "2WAY", n=1)
    clutch_l = _leaders(rows, "Q4PPG", n=1)
    diff_l = _leaders(rows, "ShotRating", n=1, qkey="FGA", qmin=15)
    sp = st.columns(5)
    spots = [
        (vers_l, "VERSATILITY", "Versatility index", "f1",
         "even box-score impact"),
        (tw_l, "2WAY", "Two-way index", "f1", "offense + defense"),
        (smoe_l, "SMOE", "Shot-making (SMOE)", "spp", "FG% over expected"),
        (diff_l, "ShotRating", "Toughest diet", "f1", "shot difficulty"),
        (clutch_l, "Q4PPG", "Clutch (Q4 PPG)", "f1", "4th-quarter scoring"),
    ]
    for col, (ld, key, lbl, fmt, sub) in zip(sp, spots):
        if ld:
            col.markdown(_spotlight(_fmt(ld[0][key], fmt), lbl,
                                    f"{ld[0]['name']} · {sub}"),
                         unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    m = st.columns(4)
    m[0].markdown(_glass("Players", len(rows), "in the qualified pool"),
                  unsafe_allow_html=True)
    m[1].markdown(_glass("Teams", teams_n, "represented"), unsafe_allow_html=True)
    m[2].markdown(_glass("PPG leader", f"{ppg_lead['PPG']:.1f}", ppg_lead["name"],
                         ACCENT), unsafe_allow_html=True)
    m[3].markdown(_glass("OVERALL leader", f"{ovr_lead['OVERALL']:.1f}",
                         ovr_lead["name"], "#56d4dd"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    lc, rc = st.columns(2)
    with lc:
        st.markdown("**Scoring leaders** — points / game")
        pl = _leaders(rows, "PPG", n=10)
        st.plotly_chart(_leader_bar(pl, "PPG", "f1", color=ACCENT, height=360),
                        width="stretch", key="ov_ppg")
    with rc:
        st.markdown("**Top rated** — OVERALL")
        ol = _leaders(rows, "OVERALL", n=10)
        st.plotly_chart(_leader_bar(ol, "OVERALL", "f1", color="#56d4dd",
                                    height=360),
                        width="stretch", key="ov_ovr")

    # ── Offense vs defense map ────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Offense vs defense</div>",
                unsafe_allow_html=True)
    off = [r["OFFENSE"] for r in rows if r["OFFENSE"] is not None
           and r["DEFENSE"] is not None]
    deff = [r["DEFENSE"] for r in rows if r["OFFENSE"] is not None
            and r["DEFENSE"] is not None]
    names = [f"{r['name']} · {_team_short(r['team'])}" for r in rows
             if r["OFFENSE"] is not None and r["DEFENSE"] is not None]
    ovr = [r["OVERALL"] for r in rows if r["OFFENSE"] is not None
           and r["DEFENSE"] is not None]
    if off:
        sc = go.Figure(go.Scatter(
            x=off, y=deff, mode="markers", text=names,
            hovertemplate="%{text}<br>OFF %{x:.1f} · DEF %{y:.1f}<extra></extra>",
            marker=dict(size=10, color=ovr, colorscale="Viridis",
                        showscale=True, colorbar=dict(title="OVR"),
                        line=dict(width=1, color="#30363d"))))
        sc.add_vline(x=50, line=dict(color="#30363d", dash="dot"))
        sc.add_hline(y=50, line=dict(color="#30363d", dash="dot"))
        sc.update_xaxes(title="Offense rating →")
        sc.update_yaxes(title="Defense rating →")
        _style(sc, 440)
        st.plotly_chart(sc, width="stretch")
        st.caption("Each dot is a player; 50 = pool average on both axes. "
                   "Top-right = two-way standouts.")

    cc1, cc2 = st.columns(2)
    with cc1:
        # ── how the top scorers get their points (per game) ──────────────────
        st.markdown("**How the top scorers score** — points / game by source")
        sc12 = _leaders(rows, "PPG", n=12)
        slab = [f"{r['name']}<br><span style='font-size:9px;color:#8b949e'>"
                f"{_team_short(r['team'])}</span>" for r in sc12]
        two = [(r["2PM"] * 2) / max(r["GP"], 1) for r in sc12]
        thr = [(r["3PM"] * 3) / max(r["GP"], 1) for r in sc12]
        ftp = [r["FTM"] / max(r["GP"], 1) for r in sc12]
        src = go.Figure()
        src.add_trace(go.Bar(x=slab, y=two, name="2-pt", marker_color=ACCENT))
        src.add_trace(go.Bar(x=slab, y=thr, name="3-pt", marker_color="#58a6ff"))
        src.add_trace(go.Bar(x=slab, y=ftp, name="FT", marker_color="#8b949e"))
        src.update_layout(barmode="stack")
        src.update_yaxes(title="Points / game")
        src.update_xaxes(tickangle=-40)
        _style(src, 380)
        st.plotly_chart(src, width="stretch", key="ov_src")
    with cc2:
        # ── distribution of OVERALL ratings ──────────────────────────────────
        st.markdown("**Rating distribution** — OVERALL across the pool")
        ovals = [r["OVERALL"] for r in rows if r["OVERALL"] is not None]
        hist = go.Figure(go.Histogram(
            x=ovals, nbinsx=20, marker_color=ACCENT, marker_line_width=0))
        hist.add_vline(x=50, line=dict(color="#8b949e", dash="dot"),
                       annotation_text="avg")
        hist.update_xaxes(title="OVERALL rating")
        hist.update_yaxes(title="Players")
        _style(hist, 380)
        st.plotly_chart(hist, width="stretch", key="ov_hist")

    # ── Usage vs efficiency ───────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Usage vs efficiency</div>",
                unsafe_allow_html=True)
    ue = [r for r in rows if r["USG%"] is not None and r["TS%"] is not None]
    if ue:
        ufig = go.Figure(go.Scatter(
            x=[r["USG%"] for r in ue], y=[r["TS%"] for r in ue], mode="markers",
            text=[f"{r['name']} · {_team_short(r['team'])}" for r in ue],
            hovertemplate="%{text}<br>USG %{x:.1f}% · TS %{y:.1f}%<extra></extra>",
            marker=dict(size=[max(7, r["PPG"] * 1.4) for r in ue],
                        color=[r["OVERALL"] or 50 for r in ue],
                        colorscale="Viridis", showscale=True,
                        colorbar=dict(title="OVR"),
                        line=dict(width=1, color="#30363d"))))
        ufig.update_xaxes(title="Usage % (share of team possessions) →")
        ufig.update_yaxes(title="True shooting % →")
        _style(ufig, 420)
        st.plotly_chart(ufig, width="stretch", key="ov_usage")
        st.caption("Bubble size = points/game. Top-right = high-volume *and* "
                   "efficient — the offensive engines.")

    # ── League fingerprints: percentile heatmap + parallel coordinates ────────
    st.markdown("<div class='pl-hdr'>League fingerprints</div>",
                unsafe_allow_html=True)
    top_n = _leaders(rows, "OVERALL", n=15)
    HM_COLS = [("PPG", "PPG"), ("RPG", "REB"), ("APG", "AST"), ("SPG", "STL"),
               ("BPG", "BLK"), ("TS%", "TS%"), ("USG%", "USG"),
               ("VERSATILITY", "VERS"), ("GS/G", "GS")]
    if top_n:
        z = [[_pctile(r.get(k), k, rows) or 0 for k, _ in HM_COLS] for r in top_n]
        txt = [[_fmt(r.get(k), "f1" if k not in ("TS%", "USG%") else "pct")
                for k, _ in HM_COLS] for r in top_n]
        hm = go.Figure(go.Heatmap(
            z=z, x=[lbl for _, lbl in HM_COLS],
            y=[r["name"] for r in top_n], text=txt, texttemplate="%{text}",
            textfont=dict(size=9), colorscale="Viridis", zmin=0, zmax=100,
            colorbar=dict(title="pctile"),
            hovertemplate="%{y} · %{x}<br>%{z}th pctile (%{text})<extra></extra>"))
        hm.update_layout(template="plotly_dark", height=max(360, 26 * len(top_n)),
                         paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                         margin=dict(l=4, r=4, t=10, b=30),
                         font=dict(size=10, color="#c9d1d9"))
        hm.update_yaxes(autorange="reversed", tickfont=dict(size=10))
        st.plotly_chart(hm, width="stretch", key="ov_heatmap")
        st.caption("Top 15 by OVERALL. Cell colour = league percentile for that "
                   "stat; numbers are the raw values. Bright row = elite across "
                   "the board.")

    # parallel coordinates — multivariate rating lines for the top players
    pc_rows = [r for r in top_n if all(r.get(k) is not None
               for k in ("OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"))]
    if len(pc_rows) >= 3:
        pdf = pd.DataFrame([{
            "Player": r["name"], "OFF": r["OFFENSE"], "DEF": r["DEFENSE"],
            "PLY": r["PLAYMAKING"], "REB": r["REBOUNDING"],
            "VERS": r["VERSATILITY"] or 0, "OVERALL": r["OVERALL"],
        } for r in pc_rows])
        pcf = px.parallel_coordinates(
            pdf, dimensions=["OFF", "DEF", "PLY", "REB", "VERS"],
            color="OVERALL", color_continuous_scale=px.colors.sequential.Viridis,
            range_color=[40, max(70, pdf["OVERALL"].max())])
        pcf.update_layout(template="plotly_dark", height=400,
                          paper_bgcolor="rgba(0,0,0,0)",
                          margin=dict(l=60, r=40, t=40, b=30),
                          font=dict(size=11, color="#c9d1d9"))
        st.plotly_chart(pcf, width="stretch", key="ov_parcoords")
        st.caption("Each line is a top player traced across the four category "
                   "ratings + versatility. Brighter = higher OVERALL. Crossing "
                   "lines reveal different archetypes reaching the same level.")

    # ── Full stat table ───────────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Full stat table</div>",
                unsafe_allow_html=True)
    full = pd.DataFrame([{
        "Rank": r["Rank"], "Player": r["name"], "Team": r["team"],
        "Cls": r["class"], "GP": r["GP"], "MIN": r["MIN"],
        "OVR": r["OVERALL"], "PPG": r["PPG"], "RPG": r["RPG"], "APG": r["APG"],
        "SPG": r["SPG"], "BPG": r["BPG"], "TPG": r["TPG"],
        "FG%": r["FG%"], "3P%": r["3P%"], "TS%": r["TS%"],
        "USG%": r["USG%"], "+/-": r["+/-"], "EFF": r["EFF"],
        "VERS": r["VERSATILITY"], "2WAY": r["2WAY"], "DD": r["DD"],
        "PTS": r["PTS"], "REB": r["REB"], "AST": r["AST"],
        "STL": r["STL"], "BLK": r["BLK"], "TOV": r["TOV"],
        "GS/G": r["GS/G"],
    } for r in rows]).sort_values("Rank")
    st.dataframe(
        full, hide_index=True, width="stretch",
        height=min(720, 60 + 35 * len(full)),
        column_config={
            "OVR": st.column_config.ProgressColumn(
                "OVR", format="%.1f", min_value=0, max_value=100)})
    st.download_button("⬇ Full stats (CSV)", full.to_csv(index=False),
                       file_name=f"players_{gender}.csv", mime="text/csv",
                       key="dl_full")
    st.caption("Every column defined in the 📖 Glossary tab.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — RATINGS
# ══════════════════════════════════════════════════════════════════════════════
with tab_rate:
    st.caption("Seven 0-100 ratings per player, each scaled so **50 = pool "
               "average** and **+10 = one standard deviation** better. OVERALL "
               "blends the four categories with PER and Game Score.")

    rate_df = pd.DataFrame([{
        "Rank": r["Rank"], "Player": r["name"], "Team": r["team"],
        "Cls": r["class"], "GP": r["GP"],
        "OVERALL": r["OVERALL"], "OFFENSE": r["OFFENSE"], "DEFENSE": r["DEFENSE"],
        "PLAYMAKING": r["PLAYMAKING"], "REBOUNDING": r["REBOUNDING"],
        "2WAY": r["2WAY"], "VERSATILITY": r["VERSATILITY"],
        "Shooting": r["Shooting"], "Finishing": r["Finishing"],
    } for r in rows]).sort_values("Rank")
    rcols = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING",
             "2WAY", "VERSATILITY", "Shooting", "Finishing"]
    st.dataframe(
        rate_df, hide_index=True, width="stretch",
        height=min(720, 60 + 35 * len(rate_df)),
        column_config={c: st.column_config.ProgressColumn(
            c, format="%.1f", min_value=0, max_value=100) for c in rcols})

    # ── Who leads each rating ─────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Who leads each rating</div>",
                unsafe_allow_html=True)
    lead_cols = st.columns(len(rcols))
    for col, key in zip(lead_cols, rcols):
        ld = _leaders(rows, key, n=1)
        if ld:
            col.metric(key, f"{ld[0][key]:.1f}")
            col.caption(ld[0]["name"])

    # ── Best per class ────────────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Best in each class</div>",
                unsafe_allow_html=True)
    pick_rate = st.selectbox("Rating", rcols, key="rate_pick")

    podium = _leaders(rows, pick_rate, n=3)
    if podium:
        _podium(podium, pick_rate, "f1")
        st.markdown("<br>", unsafe_allow_html=True)

    lc, rc = st.columns(2)
    with lc:
        st.markdown(f"**Top 10 — {pick_rate}**")
        top = _leaders(rows, pick_rate, n=10)
        st.dataframe(
            pd.DataFrame([{"#": i, "Player": r["name"], "Team": r["team"],
                           "Cls": r["class"], pick_rate: r[pick_rate]}
                          for i, r in enumerate(top, 1)]),
            hide_index=True, width="stretch")
    with rc:
        st.markdown(f"**Class champions — {pick_rate}**")
        by_class = defaultdict(list)
        for r in rows:
            if r[pick_rate] is not None:
                by_class[r["class"]].append(r)
        champ_rows = []
        for cls in sorted(by_class, key=lambda c: TR._CLASS_RANK.get(c, 99)):
            best = max(by_class[cls], key=lambda r: r[pick_rate])
            champ_rows.append({"Class": cls, "Player": best["name"],
                               "Team": best["team"], pick_rate: best[pick_rate]})
        if champ_rows:
            ch = go.Figure(go.Bar(
                x=[c["Class"] for c in champ_rows],
                y=[c[pick_rate] for c in champ_rows],
                marker_color=ACCENT, marker_line_width=0,
                text=[f"{c['Player']}<br>{c[pick_rate]:.1f}" for c in champ_rows],
                textposition="auto", textfont=dict(size=10),
                hovertemplate="%{x}: %{text}<extra></extra>"))
            ch.add_hline(y=50, line=dict(color="#8b949e", dash="dot"))
            ch.update_yaxes(title=pick_rate, range=[0, 100])
            ch.update_xaxes(title="Class")
            _style(ch, 320)
            st.plotly_chart(ch, width="stretch", key="rate_class")


# ══════════════════════════════════════════════════════════════════════════════
#  BEST FIVE — category leaders (appends into the 📊 Leaders tab)
# ══════════════════════════════════════════════════════════════════════════════
with tab_lead:
    st.markdown("<div class='pl-hdr'>Best Five — category leaders</div>",
                unsafe_allow_html=True)
    st.caption("League leaders — the top five players in **every** stat we track, "
               "regardless of team or class. Rate stats require a minimum volume "
               "so a single lucky make can't top the list.")

    for group_name, stats in STAT_GROUPS:
        st.markdown(f"<div class='pl-hdr'>{group_name}</div>",
                    unsafe_allow_html=True)
        color = GROUP_COLORS.get(group_name, ACCENT)
        # three leader-bar charts per row
        for i in range(0, len(stats), 3):
            chunk = stats[i:i + 3]
            cols = st.columns(3)
            for col, (key, label, fmt, higher, qkey, qmin) in zip(cols, chunk):
                top = _leaders(rows, key, higher=higher, n=5,
                               qkey=qkey, qmin=qmin)
                with col:
                    st.markdown(f"**{label}**")
                    if not top:
                        st.caption("Not enough data.")
                        continue
                    st.plotly_chart(
                        _leader_bar(top, key, fmt, color=color),
                        width="stretch",
                        key=f"best_{group_name}_{key}")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — SHOT LAB  (court charts, zone efficiency, shot-making)
# ══════════════════════════════════════════════════════════════════════════════
with tab_shot:
    st.caption("Where the shots come from. Every tracked shot carries a court "
               "zone (left/right corner, wing, center) and a value (2 or 3), so "
               "we can map the whole league's shot diet and each player's hot "
               "spots, then layer shot-making over shot-quality on top.")

    elig_pids = list(by_pid.keys())
    league_zone = _agg_zone(elig_pids, zsplits)

    # ── League shot map + hot zones ───────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>League shot map</div>", unsafe_allow_html=True)
    lc, rc = st.columns([3, 2])
    with lc:
        fig, ok = _shot_chart(league_zone, "All qualified players — FG% by zone")
        st.plotly_chart(fig, width="stretch", key="lab_league_court")
        st.caption("Bubble size = attempts · 🟢 ≥45% · 🟡 30–44% · 🔴 <30% · "
                   "HS 3-pt line 19′9″ · center 2PT = paint proxy.")
    with rc:
        st.markdown("**Hot zones** — make / attempt by area")
        _hot_zones(league_zone)

    # zone efficiency table (2PT & 3PT side by side)
    zrows = []
    for z in ("LC", "LW", "C", "RW", "RC"):
        d2 = league_zone.get((z, 2), {"FGM": 0, "FGA": 0, "pct": 0})
        d3 = league_zone.get((z, 3), {"FGM": 0, "FGA": 0, "pct": 0})
        zrows.append({
            "Zone": _ZONE_FULLNAME[z],
            "2PT": f"{d2['FGM']}/{d2['FGA']}",
            "2P%": f"{d2['pct']*100:.1f}%" if d2["FGA"] else "—",
            "3PT": f"{d3['FGM']}/{d3['FGA']}",
            "3P%": f"{d3['pct']*100:.1f}%" if d3["FGA"] else "—",
        })
    st.dataframe(pd.DataFrame(zrows), hide_index=True, width="stretch")

    # ── Shot-making & shot-quality leaders ────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Shot-making & shot quality</div>",
                unsafe_allow_html=True)
    st.caption("**SMOE** = shot-making over expected (real FG% minus the FG% the "
               "league hits on the *same kind of looks*). **Shot difficulty** = "
               "how hard the shots they take are (50 avg, 100 contested self-3). "
               "**xPPS** = expected points per shot from shot quality alone.")
    g1, g2, g3 = st.columns(3)
    with g1:
        st.markdown("**Best shot-makers (SMOE)**")
        top = _leaders(rows, "SMOE", n=8, qkey="FGA", qmin=15)
        st.plotly_chart(_leader_bar(top, "SMOE", "spp", color="#00e5ff", height=300),
                        width="stretch", key="lab_smoe")
    with g2:
        st.markdown("**Toughest shot diet (difficulty)**")
        top = _leaders(rows, "ShotRating", n=8, qkey="FGA", qmin=15)
        st.plotly_chart(_leader_bar(top, "ShotRating", "f1", color="#ff7b72", height=300),
                        width="stretch", key="lab_diff")
    with g3:
        st.markdown("**Best shot quality (xPPS)**")
        top = _leaders(rows, "xPPS", n=8, qkey="FGA", qmin=15)
        st.plotly_chart(_leader_bar(top, "xPPS", "f2", color="#3fb950", height=300),
                        width="stretch", key="lab_xpps")

    # ── Guarded vs open: who holds up when contested ──────────────────────────
    st.markdown("<div class='pl-hdr'>Contested vs open</div>",
                unsafe_allow_html=True)
    go_pts = []
    for pid in elig_pids:
        gd = zguard.get(pid)
        if not gd:
            continue
        gu, op = gd["guarded"], gd["open"]
        if gu["FGA"] >= 6 and op["FGA"] >= 6:
            go_pts.append((by_pid[pid]["name"], op["pct"] * 100, gu["pct"] * 100,
                           gu["FGA"] + op["FGA"]))
    if go_pts:
        sc = go.Figure(go.Scatter(
            x=[p[1] for p in go_pts], y=[p[2] for p in go_pts], mode="markers",
            text=[p[0] for p in go_pts],
            hovertemplate="%{text}<br>Open %{x:.1f}% · Guarded %{y:.1f}%<extra></extra>",
            marker=dict(size=[max(8, p[3] * 0.5) for p in go_pts], color="#00e5ff",
                        opacity=0.75, line=dict(width=1, color="#30363d"))))
        lo = min(min(p[1] for p in go_pts), min(p[2] for p in go_pts)) - 4
        hi = max(max(p[1] for p in go_pts), max(p[2] for p in go_pts)) + 4
        sc.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines",
                                line=dict(color="#8b949e", dash="dot"),
                                hoverinfo="skip", showlegend=False))
        sc.update_xaxes(title="Open FG% →")
        sc.update_yaxes(title="Guarded FG% →")
        _style(sc, 420)
        st.plotly_chart(sc, width="stretch", key="lab_guarded")
        st.caption("Dots above the dotted line shoot *better* when contested — the "
                   "shot-makers who don't need space. Bubble size = total attempts.")
    else:
        st.caption("Not enough guarded + open attempts to compare yet.")

    # ── Per-player shot explorer ──────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Player shot explorer</div>",
                unsafe_allow_html=True)
    order_l = sorted(rows, key=lambda r: (r["Rank"] or 1e9))
    labels_l = [f"#{r['Rank']}  {r['name']}  ·  {r['team']}" for r in order_l]
    pick_l = st.selectbox("Player", range(len(order_l)),
                          format_func=lambda i: labels_l[i], key="lab_pick")
    PL = order_l[pick_l]
    pl_pid = next(k for k, v in by_pid.items() if v is PL)
    pl_zone = zsplits.get(pl_pid, {})

    ec1, ec2 = st.columns([3, 2])
    with ec1:
        fig, ok = _shot_chart(pl_zone, f"{PL['name']} — shot chart")
        if ok:
            st.plotly_chart(fig, width="stretch", key="lab_player_court")
        else:
            st.info("No located shots for this player yet.")
    with ec2:
        st.markdown("**Shot-location profile**")
        rim, mid, thr = PL.get("RimFGA%"), PL.get("MidFGA%"), PL.get("3PR")
        if rim is not None:
            dn = go.Figure(go.Pie(
                labels=["Rim / paint", "Mid-range", "Three"],
                values=[rim, mid, thr], hole=0.58, sort=False,
                marker=dict(colors=["#f0a500", "#58a6ff", "#3fb950"]),
                textinfo="label+percent"))
            dn.update_layout(template="plotly_dark", height=250,
                             paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                             margin=dict(l=8, r=8, t=10, b=8))
            st.plotly_chart(dn, width="stretch", key="lab_player_diet")
        gd = zguard.get(pl_pid, {})
        if gd:
            gu, op = gd["guarded"], gd["open"]
            mm = st.columns(2)
            mm[0].metric("Guarded FG%", f"{gu['pct']*100:.0f}%" if gu["FGA"] else "—",
                         help=f"{gu['FGM']}/{gu['FGA']}")
            mm[1].metric("Open FG%", f"{op['pct']*100:.0f}%" if op["FGA"] else "—",
                         help=f"{op['FGM']}/{op['FGA']}")
    st.markdown("**Hot zones**")
    if pl_zone:
        _hot_zones(pl_zone)
    else:
        st.caption("No zone data for this player.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — COMPARE
# ══════════════════════════════════════════════════════════════════════════════
with tab_cmp:
    st.caption("Pick two players and see them head-to-head — ratings radar and "
               "a stat-by-stat breakdown with the edge highlighted.")

    order = sorted(rows, key=lambda r: (r["Rank"] or 1e9))
    labels = [f"{r['name']}  ·  {r['team']}" for r in order]
    c1, c2 = st.columns(2)
    ia = c1.selectbox("Player A", range(len(order)),
                      format_func=lambda i: labels[i], key="cmp_a")
    ib = c2.selectbox("Player B", range(len(order)),
                      index=min(1, len(order) - 1),
                      format_func=lambda i: labels[i], key="cmp_b")
    A, B = order[ia], order[ib]

    if ia == ib:
        st.warning("Pick two different players.")
    else:
        h1, h2 = st.columns(2)
        for col, P, clr in ((h1, A, ACCENT), (h2, B, "#58a6ff")):
            col.markdown(
                f"<div style='text-align:center'>"
                f"<div style='font-size:17px;font-weight:700;color:#c9d1d9'>"
                f"{P['name']}</div>"
                f"<div style='font-size:12px;color:#8b949e'>{P['team']} · "
                f"{P['class']} · #{P['Rank']}</div>"
                f"<div style='font-size:42px;font-weight:900;color:{clr};"
                f"line-height:1.2'>{P['OVERALL']:.0f}</div>"
                f"<div style='font-size:11px;color:#8b949e'>OVERALL</div></div>",
                unsafe_allow_html=True)

        # radar
        ar, ag, ab = _rgb(ACCENT)
        rad = go.Figure()
        for P, clr, rgb in ((A, ACCENT, (ar, ag, ab)), (B, "#58a6ff", (88, 166, 255))):
            vals = [P[c] or 0 for c in RATING_COLS]
            rad.add_trace(go.Scatterpolar(
                r=vals + [vals[0]], theta=RATING_COLS + [RATING_COLS[0]],
                fill="toself", name=P["name"], line=dict(color=clr, width=2),
                fillcolor=f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.18)"))
        rad.update_layout(
            template="plotly_dark", height=400, paper_bgcolor="rgba(0,0,0,0)",
            polar=dict(bgcolor=CARD_BG,
                       radialaxis=dict(range=[0, 100], gridcolor=GRID,
                                       tickfont=dict(size=9)),
                       angularaxis=dict(gridcolor=GRID)),
            margin=dict(l=60, r=60, t=50, b=30),
            legend=dict(orientation="h", y=1.12, x=0, bgcolor="rgba(0,0,0,0)"))
        st.plotly_chart(rad, width="stretch", key="cmp_radar")

        # per-game production, side by side
        pg_keys = [("PPG", "Pts"), ("RPG", "Reb"), ("APG", "Ast"),
                   ("SPG", "Stl"), ("BPG", "Blk"), ("TPG", "TO")]
        gl = [l for _, l in pg_keys]
        gb = go.Figure()
        gb.add_trace(go.Bar(x=gl, y=[A[k] or 0 for k, _ in pg_keys],
                            name=A["name"], marker_color=ACCENT))
        gb.add_trace(go.Bar(x=gl, y=[B[k] or 0 for k, _ in pg_keys],
                            name=B["name"], marker_color="#58a6ff"))
        gb.update_layout(barmode="group")
        gb.update_yaxes(title="Per game")
        _style(gb, 340)
        st.plotly_chart(gb, width="stretch", key="cmp_pg")

        # shot-attempt profile donuts
        st.markdown("<div class='pl-hdr'>Shot profile</div>",
                    unsafe_allow_html=True)
        sp1, sp2 = st.columns(2)
        for col, P, sfx in ((sp1, A, "a"), (sp2, B, "b")):
            with col:
                a2, a3, af = P["2PA"], P["3PA"], P["FTA"]
                if a2 + a3 + af > 0:
                    pie = go.Figure(go.Pie(
                        labels=["2PT FGA", "3PT FGA", "FTA"],
                        values=[a2, a3, af], hole=0.55, sort=False,
                        marker=dict(colors=[ACCENT, "#58a6ff", "#3fb950"]),
                        textinfo="label+percent"))
                    pie.update_layout(
                        template="plotly_dark", height=270,
                        paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                        margin=dict(l=10, r=10, t=34, b=10),
                        title=dict(text=P["name"], font=dict(size=13)))
                    st.plotly_chart(pie, width="stretch",
                                    key=f"cmp_donut_{sfx}")
                else:
                    st.caption(f"{P['name']}: no shot attempts.")

        # side-by-side shot charts (where each player gets their looks)
        st.markdown("<div class='pl-hdr'>Shot charts</div>", unsafe_allow_html=True)
        shc = st.columns(2)
        for col, P, sfx in ((shc[0], A, "a"), (shc[1], B, "b")):
            p_pid = next(k for k, v in by_pid.items() if v is P)
            fig, ok = _shot_chart(zsplits.get(p_pid, {}), P["name"], height=380)
            with col:
                if ok:
                    st.plotly_chart(fig, width="stretch", key=f"cmp_court_{sfx}")
                else:
                    st.caption(f"{P['name']}: no located shots.")

        # side-by-side percentile bars vs the pool
        st.markdown("<div class='pl-hdr'>League percentiles</div>",
                    unsafe_allow_html=True)
        PCT_STATS = [
            ("PPG", "Points", "f1", False), ("RPG", "Rebounds", "f1", False),
            ("APG", "Assists", "f1", False), ("SPG", "Steals", "f1", False),
            ("BPG", "Blocks", "f1", False), ("TS%", "True shooting", "pct", False),
            ("eFG%", "Effective FG", "pct", False), ("USG%", "Usage", "pct", False),
            ("TOV%", "Turnover rate", "pct", True), ("EFF", "Efficiency", "f1", False),
            ("FIC", "Floor impact", "f1", False), ("+/-", "Plus/minus", "int", False),
        ]
        pcc = st.columns(2)
        for col, P in ((pcc[0], A), (pcc[1], B)):
            html = f"<div style='font-weight:700;color:#c9d1d9;margin-bottom:8px'>{P['name']}</div>"
            for key, lbl, fmt, lb in PCT_STATS:
                p = _pctile(P.get(key), key, rows, lower_better=lb)
                html += _pctile_bar(lbl, _fmt(P.get(key), fmt), p)
            col.markdown(html, unsafe_allow_html=True)

        # stat-by-stat table with edge marker
        CMP_STATS = [
            ("MPG", "f1", True), ("PPG", "f1", True), ("RPG", "f1", True),
            ("APG", "f1", True), ("SPG", "f1", True), ("BPG", "f1", True),
            ("TPG", "f1", False),
            ("FG%", "pct", True), ("3P%", "pct", True), ("FT%", "pct", True),
            ("TS%", "pct", True), ("eFG%", "pct", True), ("PPS", "f2", True),
            ("AST/TOV", "f2", True), ("USG%", "pct", True),
            ("TOV%", "pct", False), ("REB%", "pct", True),
            ("Guarded%", "pct", True), ("DSHOT%", "pct", False),
            ("+/-", "int", True), ("EFF", "int", True), ("FIC", "f1", True),
            ("PRF", "int", True), ("ShotRating", "f1", True),
            ("SMOE", "spp", True), ("SelfCr%", "pct", True),
            ("RimFGA%", "pct", True), ("Q4PPG", "f1", True),
            ("STOCKS/32", "f1", True), ("DD", "int", True),
            ("bestPTS", "int", True), ("PTSsd", "f1", False),
            ("GS/G", "f1", True),
            ("OVERALL", "f1", True), ("OFFENSE", "f1", True),
            ("DEFENSE", "f1", True), ("PLAYMAKING", "f1", True),
            ("REBOUNDING", "f1", True), ("2WAY", "f1", True),
            ("VERSATILITY", "f1", True),
        ]
        cmp_rows = []
        for key, fmt, higher in CMP_STATS:
            va, vb = A.get(key), B.get(key)
            edge = ""
            if va is not None and vb is not None and va != vb:
                a_better = (va > vb) if higher else (va < vb)
                edge = "◀ A" if a_better else "B ▶"
            cmp_rows.append({"Stat": key, A["name"]: _fmt(va, fmt),
                             "Edge": edge, B["name"]: _fmt(vb, fmt)})
        st.dataframe(pd.DataFrame(cmp_rows), hide_index=True,
                     width="stretch",
                     height=min(800, 60 + 35 * len(cmp_rows)))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — PLAYER PROFILE
# ══════════════════════════════════════════════════════════════════════════════
with tab_prof:
    order = sorted(rows, key=lambda r: (r["Rank"] or 1e9))
    labels = [f"#{r['Rank']}  {r['name']}  ·  {r['team']}" for r in order]
    pick = st.selectbox("Player", range(len(order)),
                        format_func=lambda i: labels[i], key="prof_pick")
    P = order[pick]
    pid = next(k for k, v in by_pid.items() if v is P)

    hue, tier = _tier(P["OVERALL"])
    badges = "".join(
        f"<div style='background:#0d1117;border:1px solid {hue}55;border-radius:8px;"
        f"padding:6px 14px;text-align:center'>"
        f"<div style='font-size:20px;font-weight:900;color:{hue}'>"
        f"{P[k]:.0f}</div><div style='font-size:8px;color:#8b949e;"
        f"text-transform:uppercase;letter-spacing:1px'>{k[:4]}</div></div>"
        for k in RATING_COLS if P[k] is not None)
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#080c14,#0d1117 55%,#111827);"
        f"border:1px solid {hue}66;border-radius:18px;padding:24px 28px;"
        f"margin-bottom:18px;position:relative;overflow:hidden'>"
        f"<div style='position:absolute;right:-6px;top:50%;"
        f"transform:translateY(-50%);font-size:150px;font-weight:900;"
        f"color:rgba(255,255,255,0.03);line-height:1'>#{P['number']}</div>"
        f"<div style='display:flex;align-items:center;gap:22px;position:relative'>"
        f"<div style='background:{hue}18;border:2px solid {hue}55;border-radius:14px;"
        f"padding:12px 16px;text-align:center;min-width:74px'>"
        f"<div style='font-size:9px;color:#8b949e;letter-spacing:1px'>NO.</div>"
        f"<div style='font-size:44px;font-weight:900;color:{hue};line-height:1'>"
        f"{P['number']}</div></div>"
        f"<div style='flex:1'>"
        f"<div style='font-size:34px;font-weight:900;color:#f0f6fc;line-height:1.05'>"
        f"{P['name']}</div>"
        f"<div style='font-size:13px;color:#8b949e;margin-top:5px'>"
        f"<span style='color:{hue};font-weight:700;letter-spacing:1px'>{tier}</span> · "
        f"{P['team']} · {P['class']} · {P['GP']} GP · rank #{P['Rank']} of {len(rows)}"
        f"</div></div>"
        f"<div style='text-align:center'>"
        f"<div style='font-size:9px;color:{hue};letter-spacing:2px'>OVERALL</div>"
        f"<div style='font-size:60px;font-weight:900;color:{hue};line-height:1'>"
        f"{P['OVERALL']:.0f}</div></div></div>"
        f"<div style='display:flex;gap:8px;margin-top:14px;padding-top:12px;"
        f"border-top:1px solid #21262d;flex-wrap:wrap'>{badges}</div></div>",
        unsafe_allow_html=True)

    # ── header extras: per-game line · archetype · badges ──────────────────────
    _tc = {"Gold": "#f0c000", "Silver": "#c0c8d0", "Bronze": "#cd7f32"}
    _arch = _lab_clusters(gender)["players"].get(pid, {}).get("archetype")
    _pg_chips = "".join(
        f"<span class='stat-chip'>{lbl} <b>{P[k]:.1f}</b></span>"
        for k, lbl in [("PPG", "PPG"), ("RPG", "RPG"), ("APG", "APG"),
                       ("SPG", "SPG"), ("BPG", "BPG"), ("MPG", "MIN")]
        if P.get(k) is not None)
    _arch_chip = (f"<span class='stat-chip' style='border-color:{ACCENT}'>"
                  f"🧬 <b>{_arch}</b></span>" if _arch else "")
    st.markdown(f"<div class='form-strip' style='margin:-8px 0 10px'>"
                f"{_arch_chip}{_pg_chips}</div>", unsafe_allow_html=True)
    _pbadges = _lab_badges(gender).get(pid, [])
    if _pbadges:
        _bchips = "".join(
            f"<span style='display:inline-block;background:#0d1117;"
            f"border:1px solid {_tc.get(b['tier'], '#888')};border-radius:20px;"
            f"padding:4px 12px;margin:0 6px 7px 0;font-size:12px'>{b['emoji']} "
            f"<b>{b['name']}</b> <span style='color:"
            f"{_tc.get(b['tier'], '#888')};font-weight:700'>{b['tier']}</span></span>"
            for b in _pbadges[:8])
        st.markdown(
            f"<div style='margin:0 0 12px'><span style='font-size:11px;"
            f"color:#8b949e;text-transform:uppercase;letter-spacing:1px;"
            f"margin-right:8px'>Badges</span>{_bchips}</div>",
            unsafe_allow_html=True)
    else:
        st.caption("No badges earned yet — needs more volume or higher percentile "
                   "ranks.")

    m = st.columns(5)
    for col, key in zip(m, RATING_COLS):
        col.metric(key, P[key] if P[key] is not None else "—")

    im = st.columns(6)
    im[0].metric("MIN/G", f"{P['MPG']:.1f}" if P["MPG"] else "—")
    im[1].metric("USG%", f"{P['USG%']:.1f}%" if P["USG%"] is not None else "—")
    im[2].metric("+/-", f"{P['+/-']:+d}")
    im[3].metric("EFF", P["EFF"] if P["EFF"] is not None else "—")
    im[4].metric("FIC", P["FIC"] if P["FIC"] is not None else "—")
    im[5].metric("PRF", P["PRF"])

    # ── rating dials (futuristic gauges) ──────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Rating dials</div>", unsafe_allow_html=True)
    GAUGE_CLR = {"OVERALL": ACCENT, "OFFENSE": "#f0a500", "DEFENSE": "#e74c3c",
                 "PLAYMAKING": "#bc8cff", "REBOUNDING": "#3fb950"}
    gcols = st.columns(5)
    for col, key in zip(gcols, RATING_COLS):
        with col:
            st.plotly_chart(_gauge(P[key], key, GAUGE_CLR.get(key, ACCENT)),
                            width="stretch", key=f"prof_gauge_{key}")
    st.caption("Each dial is a 0-100 rating; the needle mark + delta are vs the "
               "pool average (50).")

    # ── signature / invented metrics (glass tiles) ────────────────────────────
    st.markdown("<div class='pl-hdr'>Signature metrics</div>",
                unsafe_allow_html=True)
    tile_specs = [
        ("VERSATILITY", _fmt(P["VERSATILITY"], "f1"), "even box impact", ACCENT),
        ("2-WAY", _fmt(P["2WAY"], "f1"), "offense + defense", "#56d4dd"),
        ("SMOE", _fmt(P["SMOE"], "spp"), "shot-making vs exp.", "#00e5ff"),
        ("Q4 PPG", _fmt(P["Q4PPG"], "f1"),
         f"{_fmt(P['Q4%'], 'pct')} of points", "#ff7b72"),
        ("SELF-CR%", _fmt(P["SelfCr%"], "pct"), "shot independence", "#d2a8ff"),
        ("STOCKS/32", _fmt(P["STOCKS/32"], "f1"), "defensive disruption", "#3fb950"),
    ]
    tiles = st.columns(6)
    for col, (lbl, val, sub, clr) in zip(tiles, tile_specs):
        col.markdown(_glass(lbl, val, sub, clr), unsafe_allow_html=True)

    # ── shot chart + hot zones ────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Shot chart</div>", unsafe_allow_html=True)
    sc_l, sc_r = st.columns([3, 2])
    with sc_l:
        fig, ok = _shot_chart(zsplits.get(pid, {}), f"{P['name']} — FG% by zone")
        if ok:
            st.plotly_chart(fig, width="stretch", key="prof_court")
            st.caption("🟢 ≥45% · 🟡 30–44% · 🔴 <30% · bubble size = attempts · "
                       "center 2PT = paint proxy.")
        else:
            st.info("No located shots for this player yet.")
    with sc_r:
        st.markdown("**Hot zones**")
        pz = zsplits.get(pid, {})
        if pz:
            _hot_zones(pz)
        else:
            st.caption("No zone data.")
        gd = zguard.get(pid, {})
        if gd:
            gg = st.columns(2)
            gg[0].metric("Guarded FG%",
                         f"{gd['guarded']['pct']*100:.0f}%" if gd["guarded"]["FGA"] else "—",
                         help=f"{gd['guarded']['FGM']}/{gd['guarded']['FGA']}")
            gg[1].metric("Open FG%",
                         f"{gd['open']['pct']*100:.0f}%" if gd["open"]["FGA"] else "—",
                         help=f"{gd['open']['FGM']}/{gd['open']['FGA']}")

    left, right = st.columns([2, 3])
    with left:
        ar, ag, ab = _rgb(ACCENT)
        vals = [P[c] or 0 for c in RATING_COLS]
        rad = go.Figure()
        rad.add_trace(go.Scatterpolar(
            r=[50] * (len(RATING_COLS) + 1),
            theta=RATING_COLS + [RATING_COLS[0]],
            line=dict(color="#8b949e", width=1, dash="dot"),
            name="Pool avg", hoverinfo="skip"))
        rad.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=RATING_COLS + [RATING_COLS[0]],
            fill="toself", name=P["name"], line=dict(color=ACCENT, width=2),
            fillcolor=f"rgba({ar},{ag},{ab},0.25)"))
        rad.update_layout(
            template="plotly_dark", height=360, paper_bgcolor="rgba(0,0,0,0)",
            polar=dict(bgcolor=CARD_BG,
                       radialaxis=dict(range=[0, 100], gridcolor=GRID,
                                       tickfont=dict(size=9)),
                       angularaxis=dict(gridcolor=GRID)),
            margin=dict(l=50, r=50, t=40, b=30),
            legend=dict(orientation="h", y=1.12, x=0, bgcolor="rgba(0,0,0,0)"))
        st.plotly_chart(rad, width="stretch", key="prof_radar")

        # points by source
        pts2, pts3, ptsf = P["2PM"] * 2, P["3PM"] * 3, P["FTM"]
        if pts2 + pts3 + ptsf > 0:
            dn = go.Figure(go.Pie(
                labels=["2-pt", "3-pt", "FT"], values=[pts2, pts3, ptsf],
                hole=0.55, sort=False,
                marker=dict(colors=[ACCENT, "#58a6ff", "#8b949e"]),
                textinfo="label+percent"))
            dn.update_layout(
                template="plotly_dark", height=260,
                paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                margin=dict(l=10, r=10, t=30, b=10),
                title=dict(text="Points by source", font=dict(size=13)))
            st.plotly_chart(dn, width="stretch", key="prof_src")

    with right:
        def _row(stat, key, fmt):
            return {"Stat": stat, "Value": _fmt(P.get(key), fmt)}

        st.markdown("**Scoring & shooting**")
        st.dataframe(pd.DataFrame([
            _row("Points (PPG)", "PTS", "int") | {"Value":
                f"{P['PTS']} ({P['PPG']:.1f}/g)"},
            _row("FG", "FG%", "pct") | {"Value":
                f"{P['FGM']}/{P['FGA']} ({_fmt(P['FG%'],'pct')})"},
            _row("Three", "3P%", "pct") | {"Value":
                f"{P['3PM']}/{P['3PA']} ({_fmt(P['3P%'],'pct')})"},
            _row("Free throw", "FT%", "pct") | {"Value":
                f"{P['FTM']}/{P['FTA']} ({_fmt(P['FT%'],'pct')})"},
            _row("eFG% / TS%", "TS%", "pct") | {"Value":
                f"{_fmt(P['eFG%'],'pct')} / {_fmt(P['TS%'],'pct')}"},
            _row("Paint FG% (pts)", "Paint%", "pct") | {"Value":
                f"{_fmt(P['Paint%'],'pct')}  ({P['PaintPTS']} pts)"},
            _row("Pts/shot (PPS)", "PPS", "f2"),
            _row("Free throw rate", "FTR", "f2"),
            _row("Shot difficulty", "ShotRating", "f1"),
            _row("Expected pts/shot", "xPPS", "f2"),
            _row("Expected FG% (SMOE)", "xFG%", "pct") | {"Value":
                f"{_fmt(P['xFG%'],'pct')}  ({_fmt(P['SMOE'],'spp')})"},
        ]), hide_index=True, width="stretch")

        st.markdown("**Rebounding · Playmaking · Defense**")
        st.dataframe(pd.DataFrame([
            _row("Rebounds (RPG)", "REB", "int") | {"Value":
                f"{P['REB']} ({P['RPG']:.1f}/g)"},
            _row("OREB / DREB", "OREB", "int") | {"Value":
                f"{P['OREB']} / {P['DREB']}"},
            _row("REB% (on court)", "REB%", "pct"),
            _row("Assists (APG)", "AST", "int") | {"Value":
                f"{P['AST']} ({P['APG']:.1f}/g)"},
            _row("Assist/turnover", "AST/TOV", "f2"),
            _row("Shots created", "SC", "int"),
            _row("Steals / Blocks", "STL", "int") | {"Value":
                f"{P['STL']} / {P['BLK']}"},
            _row("Guarded% (on court)", "Guarded%", "pct"),
            _row("Defended FG% allowed", "DSHOT%", "pct"),
            _row("Turnovers (TOV%)", "TOV", "int") | {"Value":
                f"{P['TOV']}  ({_fmt(P['TOV%'],'pct')})"},
            _row("Fouls", "PF", "int"),
            _row("Game Score / game", "GS/G", "f1"),
        ]), hide_index=True, width="stretch")

    # ── Shot diet · shot creation · quarter scoring ───────────────────────────
    st.markdown("<div class='pl-hdr'>Shot diet & impact mix</div>",
                unsafe_allow_html=True)
    pbox = S.player_box(pid)
    d1, d2, d3 = st.columns(3)
    with d1:
        st.markdown("**Shot diet** — how their shots are created")
        diet = S.shot_breakdown_pct(pbox)
        dl = {"self": "Self", "pass": "Off pass", "sc": "Off screen",
              "both": "Pass+screen"}
        dv = [(dl[k], diet[k] * 100) for k in ("self", "pass", "sc", "both")]
        df_ = go.Figure(go.Bar(
            x=[v for _, v in dv], y=[l for l, _ in dv], orientation="h",
            marker_color="#58a6ff", marker_line_width=0,
            text=[f"{v:.0f}%" for _, v in dv], textposition="auto"))
        df_.update_xaxes(visible=False)
        _style(df_, 240)
        df_.update_layout(margin=dict(l=4, r=14, t=10, b=6))
        st.plotly_chart(df_, width="stretch", key="prof_diet")
    with d2:
        st.markdown("**Shots created** — how SC is earned")
        comp = S.sc_composition(pbox)
        if pbox["SC"] > 0:
            cd = go.Figure(go.Pie(
                labels=["Shooting", "Passing", "Screening"],
                values=[comp["shoot"], comp["pass"], comp["sc"]], hole=0.55,
                sort=False, marker=dict(colors=[ACCENT, "#bc8cff", "#3fb950"]),
                textinfo="label+percent"))
            cd.update_layout(template="plotly_dark", height=240,
                             paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                             margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(cd, width="stretch", key="prof_sccomp")
        else:
            st.caption("No shots created.")
    with d3:
        st.markdown("**Scoring by quarter**")
        qb = S.quarter_boxes().get(pid, {})
        qs = sorted(qb)
        if qs:
            qfig = go.Figure(go.Bar(
                x=[f"Q{q}" if q <= 4 else f"OT{q-4}" for q in qs],
                y=[qb[q]["PTS"] for q in qs], marker_color=ACCENT,
                marker_line_width=0,
                text=[qb[q]["PTS"] for q in qs], textposition="auto"))
            qfig.update_yaxes(title="Points")
            _style(qfig, 240)
            qfig.update_layout(margin=dict(l=30, r=10, t=10, b=24))
            st.plotly_chart(qfig, width="stretch", key="prof_qtr")
        else:
            st.caption("No quarter data.")

    # ── Career highs & milestones ─────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Career highs & milestones</div>",
                unsafe_allow_html=True)
    cap_steady = ("steady" if (P["PTSsd"] or 0) < 5 else
                  "streaky" if (P["PTSsd"] or 0) > 9 else "moderate")
    ch = st.columns(6)
    ch[0].markdown(_glass("HIGH PTS", P["bestPTS"], "single game", ACCENT),
                   unsafe_allow_html=True)
    ch[1].markdown(_glass("HIGH REB", P["bestREB"], "single game", "#3fb950"),
                   unsafe_allow_html=True)
    ch[2].markdown(_glass("HIGH AST", P["bestAST"], "single game", "#bc8cff"),
                   unsafe_allow_html=True)
    ch[3].markdown(_glass("DOUBLE-DBL", P["DD"], "games", "#58a6ff"),
                   unsafe_allow_html=True)
    ch[4].markdown(_glass("TRIPLE-DBL", P["TD"], "games", "#f0a500"),
                   unsafe_allow_html=True)
    ch[5].markdown(_glass("SCORING σ", _fmt(P["PTSsd"], "f1"),
                          f"game-to-game · {cap_steady}", "#ff7b72"),
                   unsafe_allow_html=True)

    # ── Game log ──────────────────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Game log</div>",
                unsafe_allow_html=True)
    gids = [r["gid"] for r in query(
        """SELECT DISTINCT ge.game_id AS gid
           FROM game_event_lineup gel
           JOIN game_events ge ON ge.id = gel.event_id
           WHERE gel.player_id = ?""", (pid,))]
    games = query(
        """SELECT g.id, g.date, g.team1_id, g.team2_id, g.home_score,
                  g.away_score
           FROM games g WHERE g.id IN ({})""".format(
            ",".join("?" * len(gids)) or "NULL"), tuple(gids)) if gids else []
    name_of = {t["id"]: t["name"] for t in query("SELECT id, name FROM teams")}
    log = []
    for g in sorted(games, key=lambda x: x["date"]):
        b = S.aggregate_player_boxes(game_ids=[g["id"]]).get(pid)
        if not b:
            continue
        opp = g["team2_id"] if g["team1_id"] == P["team_id"] else g["team1_id"]
        log.append({
            "Date": g["date"], "Opp": name_of.get(opp, "?"),
            "PTS": b["PTS"], "REB": b["TRB"], "AST": b["AST"],
            "STL": b["STL"], "BLK": b["BLK"], "TOV": b["TOV"],
            "FG": f"{b['FGM']}/{b['FGA']}", "3P": f"{b['3PM']}/{b['3PA']}",
            "FT": f"{b['FTM']}/{b['FTA']}",
            "GS": round(S.game_score(b), 1),
        })
    if log:
        # trend across games
        gx = [f"{g['Date'][5:]} {g['Opp'][:8]}" for g in log]
        tr = go.Figure()
        tr.add_trace(go.Bar(x=gx, y=[g["PTS"] for g in log], name="PTS",
                            marker_color=ACCENT, marker_line_width=0))
        tr.add_trace(go.Scatter(x=gx, y=[g["GS"] for g in log], name="Game Score",
                                mode="lines+markers", line=dict(color="#56d4dd",
                                                                width=2)))
        tr.update_yaxes(title="Points / Game Score")
        tr.update_xaxes(tickangle=-40)
        _style(tr, 320)
        st.plotly_chart(tr, width="stretch", key="prof_log")

        st.dataframe(pd.DataFrame(log), hide_index=True,
                     width="stretch",
                     height=min(560, 60 + 35 * len(log)))
        st.caption(f"{len(log)} tracked games. Box scores are per game from "
                   "tracked events.")
    else:
        st.info("No tracked games for this player yet.")

    # ── League percentiles ────────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>League percentiles</div>",
                unsafe_allow_html=True)
    PROF_PCT = [
        ("PPG", "Points", "f1", False), ("RPG", "Rebounds", "f1", False),
        ("APG", "Assists", "f1", False), ("SPG", "Steals", "f1", False),
        ("BPG", "Blocks", "f1", False), ("STOCKS/G", "Stocks", "f1", False),
        ("TS%", "True shooting", "pct", False), ("eFG%", "Effective FG", "pct", False),
        ("3P%", "Three-point %", "pct", False), ("PPS", "Points / shot", "f2", False),
        ("USG%", "Usage", "pct", False), ("TOV%", "Ball security", "pct", True),
        ("AST/TOV", "Assist / TO", "f2", False), ("REB%", "Rebound %", "pct", False),
        ("Guarded%", "Contest rate", "pct", False), ("DSHOT%", "Defended FG%", "pct", True),
        ("EFF", "Efficiency", "f1", False), ("FIC", "Floor impact", "f1", False),
        ("+/-", "Plus/minus", "int", False), ("GS/G", "Game Score", "f1", False),
    ]
    pcol = st.columns(2)
    half = (len(PROF_PCT) + 1) // 2
    for ci, chunk in enumerate((PROF_PCT[:half], PROF_PCT[half:])):
        html = ""
        for key, lbl, fmt, lb in chunk:
            p = _pctile(P.get(key), key, rows, lower_better=lb)
            html += _pctile_bar(lbl, _fmt(P.get(key), fmt), p)
        pcol[ci].markdown(html, unsafe_allow_html=True)

    # ── League ranking ────────────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>League ranking</div>",
                unsafe_allow_html=True)
    n = len(rows)
    pctile_ovr = round((n - P["Rank"]) / max(n - 1, 1) * 100)
    rk = st.columns(3)
    rk[0].metric("League rank", f"#{P['Rank']} of {n}")
    rk[1].metric("OVERALL", f"{P['OVERALL']:.1f}")
    rk[2].metric("Percentile", f"{pctile_ovr}th")

    rank_stats = [("OVERALL", "f1"), ("OFFENSE", "f1"), ("DEFENSE", "f1"),
                  ("PLAYMAKING", "f1"), ("REBOUNDING", "f1"), ("PPG", "f1"),
                  ("RPG", "f1"), ("APG", "f1"), ("STOCKS", "int"), ("EFF", "int"),
                  ("TS%", "pct"), ("GS/G", "f1")]
    rrows = []
    for key, fmt in rank_stats:
        pool = [r for r in rows if r.get(key) is not None]
        if P.get(key) is None or not pool:
            continue
        sr = sorted(pool, key=lambda r: r[key], reverse=True)
        pos = next(i for i, r in enumerate(sr, 1) if r is P)
        rrows.append({"Stat": key, "Value": _fmt(P[key], fmt),
                      "Rank": f"#{pos} of {len(pool)}",
                      "Pctile": f"{round((len(pool)-pos)/max(len(pool)-1,1)*100)}th"})
    st.dataframe(pd.DataFrame(rrows), hide_index=True, width="stretch")

    with st.expander("OVERALL league bar — this player highlighted"):
        order_ovr = sorted([r for r in rows if r["OVERALL"] is not None],
                           key=lambda r: r["OVERALL"])
        bar = go.Figure(go.Bar(
            x=[r["OVERALL"] for r in order_ovr],
            y=[f"{r['name']}" for r in order_ovr], orientation="h",
            marker_color=[hue if r is P else "#30363d" for r in order_ovr],
            text=[f"{r['OVERALL']:.1f}" if r is P else "" for r in order_ovr],
            textposition="outside", textfont=dict(color=hue, size=12)))
        bar.update_layout(
            template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)", height=max(380, n * 22),
            margin=dict(l=4, r=40, t=10, b=10), showlegend=False,
            font=dict(size=10, color="#c9d1d9"))
        bar.update_xaxes(visible=False)
        bar.update_yaxes(showgrid=False, automargin=True, tickfont=dict(size=9))
        st.plotly_chart(bar, width="stretch", key="prof_leaguebar")

    # ── Per-32 minutes ────────────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Per-32 minutes</div>",
                unsafe_allow_html=True)
    if (P["MPG"] or 0) >= 5 and (P["MIN"] or 0) > 0:
        scale = 32.0 / P["MIN"]
        per32 = [("PTS", P["PTS"]), ("REB", P["REB"]), ("AST", P["AST"]),
                 ("STL", P["STL"]), ("BLK", P["BLK"]), ("TOV", P["TOV"]),
                 ("SC", P["SC"])]
        p32 = go.Figure(go.Bar(
            x=[k for k, _ in per32], y=[v * scale for _, v in per32],
            marker_color=["#f0a500", "#3498db", "#2ecc71", "#58a6ff",
                          "#e74c3c", "#e67e22", "#9b59b6"],
            text=[f"{v*scale:.1f}" for _, v in per32], textposition="outside",
            marker_line_width=0))
        p32.update_yaxes(title="Per 32 min")
        _style(p32, 300)
        st.plotly_chart(p32, width="stretch", key="prof_per32")
        st.caption("Totals × 32 ÷ tracked minutes. HS games run ≈32 min here, so "
                   "per-32 ≈ a full game's production. Minutes come from tracked "
                   "possession time (a slight undercount).")
    else:
        st.caption("Per-32 needs ≥5 minutes per game of tracked floor time.")

    # ── On / Off court impact ─────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>On / Off court impact</div>",
                unsafe_allow_html=True)
    st.caption("Does the **team** rebound, share the ball, and protect possessions "
               "better with this player on the floor? Covers every game the team "
               "played; small samples are directional.")

    ro = S.player_rebound_onoff(pid, P["team_id"])
    pm = S.player_playmaking_onoff(pid, P["team_id"])

    if ro and ro.get("on_oreb_opps", 0) >= 5:
        st.markdown("**Team rebounding**")
        oc1, oc2 = st.columns(2)
        oc1.markdown(_onoff_html(
            "Team OREB%", ro["on_oreb_pct"], ro["off_oreb_pct"],
            ro["on_oreb_opps"], ro["off_oreb_opps"], "opps", True),
            unsafe_allow_html=True)
        oc2.markdown(_onoff_html(
            "Team DREB%", ro["on_dreb_pct"], ro["off_dreb_pct"],
            ro["on_dreb_opps"], ro["off_dreb_opps"], "opps", True),
            unsafe_allow_html=True)
    else:
        st.info("Not enough tracked rebound opportunities for a reliable rebounding "
                "on/off split yet (need ≥5 on-court).")

    if pm and pm.get("on_fgm", 0) >= 5:
        st.markdown("**Team playmaking & ball security**")
        pc1, pc2 = st.columns(2)
        pc1.markdown(_onoff_html(
            "Team AST%", pm["on_ast_pct"], pm["off_ast_pct"],
            pm["on_fgm"], pm["off_fgm"], "FGM", True),
            unsafe_allow_html=True)
        pc2.markdown(_onoff_html(
            "Team TOV%", pm["on_tov_pct"], pm["off_tov_pct"],
            pm["on_tov"], pm["off_tov"], "TOV", False),
            unsafe_allow_html=True)
        st.caption("AST% = assisted made FGs ÷ made FGs.  TOV% = turnovers ÷ "
                   "possessions.  Lower TOV% is better — green means the team turns "
                   "it over **less** with this player on.")
    else:
        st.info("Not enough tracked possessions for a reliable playmaking on/off "
                "split yet (need ≥5 team FGM on-court).")

    # ── Scouting report (rule-based, percentile-driven) ───────────────────────
    st.markdown("<div class='pl-hdr'>Scouting report</div>",
                unsafe_allow_html=True)

    def pc(key, lb=False):
        return _pctile(P.get(key), key, rows, lower_better=lb) or 0

    OFF, DEF, PLY, REB_R = (P["OFFENSE"] or 0, P["DEFENSE"] or 0,
                            P["PLAYMAKING"] or 0, P["REBOUNDING"] or 0)
    OVR = P["OVERALL"] or 0

    if OVR >= 65 and DEF >= 60:
        arch = ("👑", "Two-Way Force",
                "Produces on offense and disrupts on defense — a rare both-ends impact.")
    elif OFF >= 62 and pc("PPG") >= 80:
        arch = ("⚡", "Scoring Machine",
                "A primary offensive weapon who creates and converts at volume.")
    elif PLY >= 62 and pc("APG") >= 80:
        arch = ("🎯", "Floor General",
                "Runs the offense through vision and distribution.")
    elif REB_R >= 62 or pc("REB") >= 85:
        arch = ("📦", "Glass Cleaner",
                "Owns the boards and generates extra possessions.")
    elif DEF >= 62 or pc("STOCKS") >= 85:
        arch = ("🛡️", "Defensive Anchor",
                "Disrupts opponents with steals, blocks, and contests.")
    elif pc("3P%") >= 70 and P["3PA"] >= 15 and pc("DSHOT%", True) >= 55:
        arch = ("🏹", "3-and-D Wing",
                "Spaces the floor and holds up defensively — a valuable role.")
    elif pc("3P%") >= 70 and P["3PA"] >= 20:
        arch = ("🎪", "Spot-Up Shooter",
                "An off-ball threat who punishes help defense from deep.")
    elif pc("Paint%") >= 70 and pc("REB") >= 60:
        arch = ("🔨", "Interior Presence",
                "Finishes inside efficiently and commands the paint.")
    elif OVR >= 56:
        arch = ("🧩", "Versatile Contributor",
                "Well-rounded across the board without one dominant trait.")
    elif pc("+/-") >= 75:
        arch = ("🔋", "High-Impact Role Player",
                "The team plays better with them on the floor.")
    else:
        arch = ("📊", "Developing Player",
                "Still building their game — more tracked games will sharpen it.")

    st.markdown(
        f"<div style='background:linear-gradient(135deg,#1a1200,#0d1117);"
        f"border:1px solid {ACCENT};border-radius:12px;padding:14px 18px;"
        f"margin-bottom:14px;display:flex;align-items:center;gap:14px'>"
        f"<span style='font-size:32px'>{arch[0]}</span><div>"
        f"<div style='font-size:15px;font-weight:800;color:{ACCENT}'>{arch[1]}</div>"
        f"<div style='font-size:12px;color:#8b949e;margin-top:3px'>{arch[2]}</div>"
        f"</div></div>", unsafe_allow_html=True)

    strengths, weaknesses = [], []
    if pc("PPG") >= 85:
        strengths.append(("Elite scorer", f"{P['PPG']:.1f} PPG — top of the league."))
    elif pc("PPG") >= 65:
        strengths.append(("Consistent scorer", f"{P['PPG']:.1f} PPG."))
    if pc("TS%") >= 80:
        strengths.append(("Efficient shooter", f"{_fmt(P['TS%'],'pct')} TS% — high value per shot."))
    if pc("3P%") >= 80 and P["3PA"] >= 12:
        strengths.append(("3-point threat", f"{_fmt(P['3P%'],'pct')} on {P['3PA']} attempts."))
    if pc("REB") >= 85:
        strengths.append(("Dominant rebounder", f"{P['RPG']:.1f} RPG."))
    if pc("APG") >= 85:
        strengths.append(("Elite facilitator", f"{P['APG']:.1f} APG."))
    if pc("AST/TOV") >= 80 and (P["AST/TOV"] or 0) >= 1.5:
        strengths.append(("Great ball security", f"{P['AST/TOV']:.2f} AST/TOV."))
    if pc("STOCKS") >= 85:
        strengths.append(("Disruptive defender", f"{P['STL']} STL / {P['BLK']} BLK."))
    if pc("+/-") >= 85:
        strengths.append(("Strong net impact", f"{P['+/-']:+d} plus/minus."))
    strengths = strengths[:4]

    if pc("TS%", ) <= 25 and P["FGA"] >= 20:
        weaknesses.append(("Below-average efficiency", f"{_fmt(P['TS%'],'pct')} TS%."))
    if pc("TOV%", True) <= 25 and P["TOV%"] is not None:
        weaknesses.append(("Turnover-prone", f"{_fmt(P['TOV%'],'pct')} turnover rate."))
    if pc("3P%") <= 25 and P["3PA"] >= 15:
        weaknesses.append(("Streaky from three", f"{_fmt(P['3P%'],'pct')} on {P['3PA']} attempts."))
    if P["FT%"] is not None and pc("FT%") <= 25 and P["FTA"] >= 10:
        weaknesses.append(("Shaky at the line", f"{_fmt(P['FT%'],'pct')} FT%."))
    if pc("REB%") <= 20 and (P["MPG"] or 0) >= 12:
        weaknesses.append(("Limited on the glass", "Low rebound rate for the minutes."))
    if pc("STOCKS") <= 15 and (P["MPG"] or 0) >= 14:
        weaknesses.append(("Low defensive activity", "Few steals or blocks for the minutes."))
    weaknesses = weaknesses[:3]

    def _bullets(items, empty):
        if not items:
            return f"<div style='font-size:12px;color:#484f58;font-style:italic'>{empty}</div>"
        return "".join(
            f"<div style='margin-bottom:9px'>"
            f"<div style='font-size:13px;font-weight:700;color:#f0f6fc'>{l}</div>"
            f"<div style='font-size:12px;color:#8b949e'>{d}</div></div>"
            for l, d in items)

    sc1, sc2 = st.columns(2)
    sc1.markdown(
        f"<div class='pl-scout'><div style='font-size:13px;font-weight:700;"
        f"color:#2ea043;margin-bottom:10px'>✅ Strengths</div>"
        f"{_bullets(strengths, 'No standout strengths in this sample yet.')}</div>",
        unsafe_allow_html=True)
    sc2.markdown(
        f"<div class='pl-scout'><div style='font-size:13px;font-weight:700;"
        f"color:#f0a500;margin-bottom:10px'>⚠️ Areas to watch</div>"
        f"{_bullets(weaknesses, 'No clear weaknesses in this sample yet.')}</div>",
        unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — LAB  (badges · archetypes · stabilized stats · defensive matchups)
# ══════════════════════════════════════════════════════════════════════════════
with tab_plab:
    st.caption("The next-gen player layer — NBA-2K-style badges, data-driven "
               "archetypes + a 'plays-like' similarity engine, empirical-Bayes "
               "stabilized stats for the small sample, and who-guarded-whom "
               "matchup intelligence. Computed over the full pool (min 1 game).")
    _TIER_COLOR = {"Gold": "#f0c000", "Silver": "#c0c8d0", "Bronze": "#cd7f32"}
    ltab = _table_full(gender)
    if not ltab:
        st.info("No tracked-game player data for this league yet.")
    else:
        lbadges = _lab_badges(gender)
        lclusters = _lab_clusters(gender)
        lstab = _lab_stab(gender)
        lnames = _lab_names(gender)
        lab_pid_label = {pid: f"#{r['number']} {r['name']} · {r['team']}"
                         for pid, r in ltab.items()}
        lab_order = sorted(ltab, key=lambda p: -(ltab[p].get("OVERALL") or 0))

        sub_badge, sub_arch, sub_stab, sub_match = st.tabs(
            ["🏅 Badges", "🧬 Archetypes", "📊 Stabilized", "🛡️ Matchups"])

        # ── Badges ───────────────────────────────────────────────────────────
        with sub_badge:
            st.markdown("<div class='pl-hdr'>Badge leaders</div>",
                        unsafe_allow_html=True)
            bpts = {p: BG.badge_points(lbadges[p]) for p in ltab}
            lead = sorted([p for p in ltab if bpts[p] > 0],
                          key=lambda p: -bpts[p])[:15]
            if lead:
                lfig = go.Figure(go.Bar(
                    x=[bpts[p] for p in lead][::-1],
                    y=[ltab[p]["name"] for p in lead][::-1], orientation="h",
                    marker_color=ACCENT, marker_line_width=0,
                    text=[bpts[p] for p in lead][::-1], textposition="auto"))
                lfig.update_xaxes(title="Badge points (Gold 5 · Silver 3 · Bronze 1)")
                _style(lfig, max(320, 26*len(lead)))
                st.plotly_chart(lfig, width="stretch", key="plab_badge_lead")

            st.markdown("<div class='pl-hdr'>Badge wall</div>",
                        unsafe_allow_html=True)
            psel = st.selectbox("Player", lab_order,
                                format_func=lambda p: lab_pid_label[p],
                                key="plab_badge_player")
            pb = lbadges.get(psel, [])
            r = ltab[psel]
            st.markdown(
                f"<div class='glass-tile'><b style='font-size:18px'>{r['name']}</b> "
                f"<span style='color:#8b949e'>#{r['number']} · {r['team']} · OVR "
                f"{r.get('OVERALL','—')} · {BG.badge_points(pb)} badge pts</span></div>",
                unsafe_allow_html=True)
            if pb:
                cols = st.columns(4)
                for i, b in enumerate(pb):
                    clr = _TIER_COLOR.get(b["tier"], "#888")
                    cols[i % 4].markdown(
                        f"<div class='glass-tile' style='border-left:4px solid {clr};"
                        f"margin-bottom:8px'>"
                        f"<div style='font-size:22px'>{b['emoji']}</div>"
                        f"<b>{b['name']}</b><br>"
                        f"<span style='color:{clr};font-weight:700;font-size:12px'>"
                        f"{b['tier'].upper()}</span>"
                        f" <span style='color:#8b949e;font-size:11px'>{b['pct']}th "
                        f"pctl</span><br>"
                        f"<span style='font-size:11px;color:#8b949e'>{b['desc']}</span>"
                        f"</div>", unsafe_allow_html=True)
            else:
                st.caption("No badges yet — needs more volume or higher percentile "
                           "ranks.")

            st.markdown("<div class='pl-hdr'>Badge explorer</div>",
                        unsafe_allow_html=True)
            all_badge_names = [b["name"] for b in BG.BADGES]
            pick = st.selectbox("Find everyone who earned…", all_badge_names,
                                key="plab_badge_pick")
            holders = []
            for p in ltab:
                for b in lbadges.get(p, []):
                    if b["name"] == pick:
                        holders.append((ltab[p]["name"], ltab[p]["team"],
                                        b["tier"], b["pct"]))
            holders.sort(key=lambda x: (-BG._TIER_RANK[x[2]], -(x[3] or 0)))
            if holders:
                st.dataframe(
                    pd.DataFrame(holders, columns=["Player", "Team", "Tier", "Pctl"]),
                    hide_index=True, width="stretch", key="plab_badge_holders")
            else:
                st.caption("No one has earned this badge in the current sample.")

        # ── Archetypes ───────────────────────────────────────────────────────
        with sub_arch:
            st.markdown("<div class='pl-hdr'>Data-driven archetypes</div>",
                        unsafe_allow_html=True)
            st.caption(f"Players grouped into {lclusters['k']} style clusters by "
                       "k-means on z-scored stats; each cluster is named from its "
                       "statistical signature.")
            afig = go.Figure()
            for ci, c in enumerate(lclusters["clusters"]):
                mem = c["members"]
                afig.add_trace(go.Scatter(
                    x=[ltab[p].get("OFFENSE") for p in mem],
                    y=[ltab[p].get("DEFENSE") for p in mem],
                    mode="markers", name=c["archetype"],
                    marker=dict(size=[8 + 0.18*(ltab[p].get("OVERALL") or 50)
                                      for p in mem],
                                color=PALETTE[ci % len(PALETTE)], opacity=0.8,
                                line=dict(color="#0d1117", width=1)),
                    text=[ltab[p]["name"] for p in mem],
                    hovertemplate="%{text}<br>OFF %{x:.0f} · DEF %{y:.0f}<extra>"
                                  + c["archetype"] + "</extra>"))
            afig.add_hline(y=50, line=dict(color="#30363d", width=1, dash="dot"))
            afig.add_vline(x=50, line=dict(color="#30363d", width=1, dash="dot"))
            afig.update_xaxes(title="OFFENSE rating")
            afig.update_yaxes(title="DEFENSE rating")
            _style(afig, 460)
            afig.update_layout(hovermode="closest")
            st.plotly_chart(afig, width="stretch", key="plab_arch_scatter")

            for c in lclusters["clusters"]:
                sig = " · ".join(f"{a}+{v:.1f}" for a, v in c["signature"] if v > 0.1)
                roster = ", ".join(ltab[p]["name"] for p in
                                   sorted(c["members"],
                                          key=lambda p: -(ltab[p].get("OVERALL") or 0))[:6])
                st.markdown(
                    f"<div class='glass-tile' style='margin-bottom:8px'>"
                    f"<b>{c['archetype']}</b> "
                    f"<span style='color:#8b949e'>· {c['size']} players · avg OVR "
                    f"{c['avg_overall']}</span><br>"
                    f"<span style='font-size:12px;color:{ACCENT}'>signature: "
                    f"{sig or 'balanced'}</span><br>"
                    f"<span style='font-size:13px'>{roster}"
                    f"{' …' if c['size']>6 else ''}</span></div>",
                    unsafe_allow_html=True)

            st.markdown("<div class='pl-hdr'>Who plays like…?</div>",
                        unsafe_allow_html=True)
            simp = st.selectbox("Player", lab_order,
                                format_func=lambda p: lab_pid_label[p],
                                key="plab_sim_player")
            sims = ARC.similar_players(ltab, simp, n=8)
            if sims:
                sfig = go.Figure(go.Bar(
                    x=[s["similarity"]*100 for s in sims][::-1],
                    y=[f"{s['name']} ({s['team']})" for s in sims][::-1],
                    orientation="h", marker_color=ACCENT, marker_line_width=0,
                    text=[f"{s['similarity']*100:.0f}%" for s in sims][::-1],
                    textposition="auto"))
                sfig.update_xaxes(title="Style similarity", range=[0, 100],
                                  ticksuffix="%")
                a = lclusters["players"].get(simp, {})
                _style(sfig, max(300, 30*len(sims)))
                st.plotly_chart(sfig, width="stretch", key="plab_sim_bar")
                st.caption(f"{ltab[simp]['name']} archetype: "
                           f"**{a.get('archetype','—')}** · cosine similarity in "
                           "the z-scored stat space.")

        # ── Stabilized ───────────────────────────────────────────────────────
        with sub_stab:
            st.markdown("<div class='pl-hdr'>Stabilized stats (small-sample "
                        "correction)</div>", unsafe_allow_html=True)
            pri = next(iter(lstab.values()))["priors"] if lstab else {}
            st.caption("Empirical-Bayes regression to the mean: each rate is pulled "
                       "toward the league average by how few attempts back it, so a "
                       "2-for-3 night no longer reads as 67%. Prior strength is "
                       "estimated from the data (FG% prior "
                       f"{pri.get('FG%',('?','?'))[0]}% on "
                       f"{pri.get('FG%',('?','?'))[1]} phantom attempts).")
            rows_s = []
            for pid, r in ltab.items():
                s = lstab.get(pid, {})
                rows_s.append({
                    "Player": r["name"], "Team": r["team"], "GP": r["GP"],
                    "FGA": r["FGA"], "FG%": r.get("FG%"), "sFG%": s.get("sFG%"),
                    "3PA": r["3PA"], "3P%": r.get("3P%"), "s3P%": s.get("s3P%"),
                    "TS%": r.get("TS%"), "sTS%": s.get("sTS%"),
                    "OVERALL": r.get("OVERALL"), "sOVERALL": s.get("sOVERALL"),
                })
            dfs = pd.DataFrame(rows_s).sort_values("sOVERALL", ascending=False,
                                                   na_position="last")
            st.dataframe(dfs, hide_index=True, width="stretch",
                         key="plab_stab_table",
                         column_config={
                             "sOVERALL": st.column_config.ProgressColumn(
                                 "sOVERALL", format="%.1f", min_value=0, max_value=100),
                         })

            st.markdown("<div class='pl-hdr'>Raw vs stabilized 3P%</div>",
                        unsafe_allow_html=True)
            spts = [(ltab[p]["name"], ltab[p].get("3P%"), lstab[p].get("s3P%"),
                     ltab[p]["3PA"]) for p in ltab
                    if ltab[p].get("3P%") is not None and ltab[p]["3PA"] > 0]
            if spts:
                scfig = go.Figure()
                scfig.add_trace(go.Scatter(
                    x=[p[1] for p in spts], y=[p[2] for p in spts], mode="markers",
                    marker=dict(size=[6 + 0.5*p[3] for p in spts], color=ACCENT,
                                opacity=0.75, line=dict(color="#0d1117", width=1)),
                    text=[f"{p[0]} ({p[3]} 3PA)" for p in spts],
                    hovertemplate="%{text}<br>raw %{x:.0f}% → stab %{y:.0f}%<extra></extra>"))
                lim = [0, max(80, max(p[1] for p in spts) + 5)]
                scfig.add_trace(go.Scatter(x=lim, y=lim, mode="lines",
                                           showlegend=False,
                                           line=dict(color="#8b949e", width=1, dash="dot")))
                scfig.update_xaxes(title="Raw 3P%", ticksuffix="%")
                scfig.update_yaxes(title="Stabilized 3P%", ticksuffix="%")
                _style(scfig, 420)
                scfig.update_layout(hovermode="closest")
                st.plotly_chart(scfig, width="stretch", key="plab_stab_scatter")
                st.caption("Bubble size = 3PA. Points are pulled toward the league "
                           "mean — low-volume shooters move most (off the y=x line).")

        # ── Matchups ─────────────────────────────────────────────────────────
        with sub_match:
            mt = MX.matchup_table()
            diff = MX.matchup_difficulty(table=ltab)
            gen_def = {d: v for d, v in mt.items() if d in lnames}
            if not gen_def:
                st.info("No contested-shot data yet for this league.")
            else:
                st.markdown("<div class='pl-hdr'>Matchup difficulty</div>",
                            unsafe_allow_html=True)
                st.caption("How good were the scorers each defender was assigned to "
                           "(attempt-weighted opponent OFFENSE rating). High = "
                           "guarded the other team's best.")
                drows = sorted([(d, diff[d]) for d in gen_def if d in diff],
                               key=lambda x: -x[1]["Difficulty100"])[:15]
                if drows:
                    dfig = go.Figure(go.Bar(
                        x=[v["Difficulty100"] for _, v in drows][::-1],
                        y=[lnames[d]["name"] for d, _ in drows][::-1],
                        orientation="h", marker_color=ACCENT, marker_line_width=0,
                        text=[f"{v['Difficulty100']:.0f}" for _, v in drows][::-1],
                        textposition="auto",
                        customdata=[v["shots_faced"] for _, v in drows][::-1],
                        hovertemplate="%{y}: difficulty %{x:.0f} · %{customdata} "
                                      "shots faced<extra></extra>"))
                    dfig.add_vline(x=50, line=dict(color="#8b949e", width=1, dash="dot"))
                    dfig.update_xaxes(title="Matchup difficulty (50 = average "
                                            "assignment)")
                    _style(dfig, max(320, 26*len(drows)))
                    st.plotly_chart(dfig, width="stretch", key="plab_match_diff")

                st.markdown("<div class='pl-hdr'>On-ball defense — shots contested"
                            "</div>", unsafe_allow_html=True)
                defrows = sorted([(d, gen_def[d]) for d in gen_def],
                                 key=lambda x: -x[1]["FGA"])
                ddf = pd.DataFrame([
                    {"Defender": lnames[d]["name"], "Team": lnames[d]["team"],
                     "Contested": v["FGA"], "Allowed": v["FGM"],
                     "FG% allowed": v["FG%"], "Pts allowed": v["pts_allowed"],
                     "Assignments": v["assignments"]}
                    for d, v in defrows])
                st.dataframe(ddf, hide_index=True, width="stretch",
                             key="plab_match_table",
                             column_config={"FG% allowed": st.column_config.NumberColumn(
                                 "FG% allowed", format="%.1f")})

                st.markdown("<div class='pl-hdr'>Who did they guard?</div>",
                            unsafe_allow_html=True)
                dsel = st.selectbox(
                    "Defender", [d for d, _ in defrows],
                    format_func=lambda d: f"{lnames[d]['name']} · {lnames[d]['team']}",
                    key="plab_match_defender")
                rec = gen_def[dsel]
                sh_rows = []
                for sht, sv in sorted(rec["by_shooter"].items(),
                                      key=lambda x: -x[1]["FGA"]):
                    sh_rows.append({"Shooter": lnames.get(sht, {}).get("name", str(sht)),
                                    "Team": lnames.get(sht, {}).get("team", ""),
                                    "Shots": sv["FGA"], "Made": sv["FGM"],
                                    "FG%": sv["FG%"], "Pts": sv["pts"]})
                if sh_rows:
                    st.dataframe(pd.DataFrame(sh_rows), hide_index=True,
                                 width="stretch", key="plab_match_assignments")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7 — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_gloss:
    glossary_tab("pl_gloss")
