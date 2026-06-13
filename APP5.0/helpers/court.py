"""
court.py — shared half-court shot visualisation (Plotly).

Two render modes over the same hoop-at-origin coordinate frame (see
helpers/court_geom.py):
  * shot_chart() — the legacy 5-zone bubble chart (zone make/attempt), still used
    for games that only have `zone` (no tap-captured x/y).
  * shot_map()   — the real shot chart: every tap-captured shot as a dot on the
    court (green make / red miss), with distance + value on hover.

Both draw the court via the single _draw_court() helper so the geometry never
diverges. This is a UI helper (imports streamlit/plotly) — the display mirror of
the Streamlit-free engines. Do NOT import it from the engine layer; the pure
coordinate math lives in helpers/court_geom.py (engine-safe).
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

import helpers.court_geom as CG

# Zone-bubble positions (feet) for the legacy 5-zone chart (hoop at (0, HOOP_Y)).
ZONE_XY = {
    ("C", 2): (0, 16),    ("C", 3): (0, 26),
    ("LC", 2): (-13, 8),  ("LC", 3): (-19, 4),
    ("LW", 2): (-12, 17), ("LW", 3): (-17, 21),
    ("RW", 2): (12, 17),  ("RW", 3): (17, 21),
    ("RC", 2): (13, 8),   ("RC", 3): (19, 4),
}
ZONE_FULLNAME = {"LC": "Left corner", "LW": "Left wing", "C": "Center / top",
                 "RW": "Right wing", "RC": "Right corner"}


def fgp_color(p, a):
    """Red→gold→green by FG% (None/empty attempts = grey)."""
    if not a:
        return "#2d333b"
    return "#1a9850" if p >= 0.45 else "#f4a724" if p >= 0.30 else "#d73027"


# ── shared court rendering ──────────────────────────────────────────────────────
def _draw_court(fig):
    """Draw the half-court lines onto a Plotly figure (hoop at (0, HOOP_Y))."""
    LINE, DIM = "rgba(220,220,220,0.65)", "rgba(180,180,180,0.30)"
    GOLD = "rgba(230,190,100,0.95)"
    R3, HY = CG.THREE_R, CG.HOOP_Y
    LANE_W, LANE_D, FT_R, RA_R = CG.LANE_HW, CG.LANE_D, CG.FT_R, CG.RA_R

    def _ln(x0, y0, x1, y1, c=LINE, w=1.5):
        fig.add_shape(type="line", x0=x0, y0=y0, x1=x1, y1=y1,
                      line=dict(color=c, width=w))

    def _arc(cx, cy, r, t0, t1, c=LINE, w=1.5, dash="solid", n=90):
        th = np.linspace(t0, t1, n)
        fig.add_trace(go.Scatter(x=cx + r * np.cos(th), y=cy + r * np.sin(th),
                                 mode="lines", line=dict(color=c, width=w, dash=dash),
                                 showlegend=False, hoverinfo="skip"))

    _ln(-25, 0, 25, 0, LINE, 2)                                   # baseline
    yj = HY + CG.CBREAK                                           # corner/arc join
    _ln(-CG.CORNER_X, 0, -CG.CORNER_X, yj)                        # corner-3 straights
    _ln(CG.CORNER_X, 0, CG.CORNER_X, yj)
    tj = float(np.arctan2(CG.CBREAK, CG.CORNER_X))
    _arc(0, HY, R3, tj, np.pi - tj, n=140)                        # 3-pt arc
    fig.add_shape(type="rect", x0=-LANE_W, y0=0, x1=LANE_W, y1=LANE_D,
                  line=dict(color=LINE, width=1.5), fillcolor="rgba(255,255,255,0.03)")
    _ln(-LANE_W, LANE_D, LANE_W, LANE_D)
    _arc(0, LANE_D, FT_R, 0, np.pi)
    _arc(0, LANE_D, FT_R, np.pi, 2 * np.pi, DIM, 1, "dot")
    _arc(0, HY, RA_R, 0, np.pi, DIM, 1)                           # restricted area
    _ln(-3, HY - 1.25, 3, HY - 1.25, GOLD, 2.5)                   # backboard
    fig.add_shape(type="circle", x0=-0.75, y0=HY - 0.75, x1=0.75, y1=HY + 0.75,
                  line=dict(color=GOLD, width=2.5), fillcolor="rgba(0,0,0,0)")


def _court_layout(fig, title, height):
    """Apply the shared half-court axes / theme."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#c9d1d9"), x=0.02),
        xaxis=dict(range=[-26, 26], visible=False),
        yaxis=dict(range=[-2, CG.Y_MAX], visible=False, scaleanchor="x", scaleratio=1),
        height=height, margin=dict(l=5, r=5, t=42, b=5),
        plot_bgcolor="rgba(18,20,30,1)", paper_bgcolor="rgba(0,0,0,0)")


def shot_chart(zone_data, title="Shot chart", height=430):
    """Plotly zone-bubble half-court. zone_data = {(zone,stype):{FGA,FGM,pct}}.

    Returns ``(figure, any_bubble)`` — ``any_bubble`` is False when every zone
    has zero attempts (so callers can show an empty-state instead)."""
    fig = go.Figure()
    _draw_court(fig)

    items = sorted(zone_data.items(), key=lambda x: x[1]["FGA"], reverse=True)
    any_bubble = False
    for (zone, stype), d in items:
        pos = ZONE_XY.get((zone, stype))
        if not pos or d["FGA"] == 0:
            continue
        any_bubble = True
        fga, fgm, fgp = d["FGA"], d["FGM"], d["pct"]
        size = max(18, min(54, 12 + fga * 4))
        fig.add_trace(go.Scatter(
            x=[pos[0]], y=[pos[1]], mode="markers+text",
            marker=dict(size=size, color=fgp_color(fgp, fga), sizemode="diameter",
                        line=dict(color="rgba(255,255,255,0.9)", width=1.5), opacity=0.92),
            text=[f"<b>{fgp*100:.0f}%</b>"], textposition="middle center",
            textfont=dict(size=max(9, min(13, int(size // 4))), color="white",
                          family="Arial Black"),
            hovertext=[f"<b>{stype}PT — {ZONE_FULLNAME.get(zone, zone)}</b><br>"
                       f"{fgm}/{fga} · {fgp*100:.1f}%"],
            hoverinfo="text", showlegend=False))
        fig.add_annotation(x=pos[0], y=pos[1] - size / 46 - 1.6, text=f"{fgm}/{fga}",
                           showarrow=False, font=dict(size=8, color="rgba(255,255,255,0.7)"))
    _court_layout(fig, title, height)
    return fig, any_bubble


def _shot_hover(s):
    v = s.get("value") or 2
    dist = CG.shot_distance(s["x"], s["y"])
    zone = CG.zone_from_xy(s["x"], s["y"])
    return (f"<b>{v}PT {'make' if s.get('make') else 'miss'}</b><br>"
            f"{dist:.0f} ft · {zone}")


def shot_map(shots, title="Shot chart", height=470, show_misses=True):
    """Individual-shot half-court map (the real shot chart).

    `shots` = list of {x, y, make(bool), value(2|3, optional)}. Green dot = make,
    red ✕ = miss. Returns ``(figure, n_shots)``; n_shots == 0 means nothing to
    plot (caller can fall back to shot_chart on zone data)."""
    fig = go.Figure()
    _draw_court(fig)
    makes = [s for s in shots if s.get("make")]
    misses = [s for s in shots if not s.get("make")]
    if show_misses and misses:
        fig.add_trace(go.Scatter(
            x=[s["x"] for s in misses], y=[s["y"] for s in misses],
            mode="markers", name="Miss",
            marker=dict(symbol="x", size=8, color="rgba(231,76,60,0.80)",
                        line=dict(width=1, color="rgba(231,76,60,0.9)")),
            hovertext=[_shot_hover(s) for s in misses], hoverinfo="text"))
    if makes:
        fig.add_trace(go.Scatter(
            x=[s["x"] for s in makes], y=[s["y"] for s in makes],
            mode="markers", name="Make",
            marker=dict(symbol="circle", size=9, color="rgba(63,185,80,0.90)",
                        line=dict(width=1, color="rgba(255,255,255,0.75)")),
            hovertext=[_shot_hover(s) for s in makes], hoverinfo="text"))
    _court_layout(fig, title, height)
    fig.update_layout(showlegend=True,
                      legend=dict(orientation="h", y=1.02, x=0,
                                  bgcolor="rgba(0,0,0,0)",
                                  font=dict(size=11, color="#c9d1d9")))
    return fig, len(shots)


# Zone-leader bubble spots: midpoint of the zone's 2PT and 3PT bubble positions.
_LEADER_XY = {z: ((ZONE_XY[(z, 2)][0] + ZONE_XY[(z, 3)][0]) / 2,
                  (ZONE_XY[(z, 2)][1] + ZONE_XY[(z, 3)][1]) / 2)
              for z in ZONE_FULLNAME}


def zone_leader_map(leaders, title="Best shooter by zone", height=420,
                    colorscale="RdYlGn", cmin=25, cmax=65):
    """Half-court with each zone's best shooter as a labelled bubble.

    ``leaders`` = {zone: {number, name, pct, FGM, FGA}}; a missing/None zone
    renders as a grey "no qualifier" bubble. Returns ``(figure, any_leader)``."""
    fig = go.Figure()
    _draw_court(fig)
    qz = [z for z in ZONE_FULLNAME if leaders.get(z)]
    nz = [z for z in ZONE_FULLNAME if not leaders.get(z)]
    if qz:
        fig.add_trace(go.Scatter(
            x=[_LEADER_XY[z][0] for z in qz], y=[_LEADER_XY[z][1] for z in qz],
            mode="markers+text",
            marker=dict(size=64, color=[leaders[z]["pct"] * 100 for z in qz],
                        colorscale=colorscale, cmin=cmin, cmax=cmax,
                        showscale=True,
                        colorbar=dict(title="FG%", thickness=12, len=0.6, x=1.0),
                        line=dict(color="#0d1117", width=2), opacity=0.95),
            text=[f"#{leaders[z]['number']} {str(leaders[z]['name']).split()[-1]}"
                  f"<br>{leaders[z]['pct'] * 100:.0f}% "
                  f"({leaders[z]['FGM']}/{leaders[z]['FGA']})" for z in qz],
            textfont=dict(size=10, color="#f0f6fc"), textposition="middle center",
            hovertext=[f"{ZONE_FULLNAME[z]}<br>#{leaders[z]['number']} "
                       f"{leaders[z]['name']}<br>{leaders[z]['FGM']}/"
                       f"{leaders[z]['FGA']} · {leaders[z]['pct'] * 100:.0f}%"
                       for z in qz],
            hovertemplate="%{hovertext}<extra></extra>", showlegend=False))
    if nz:
        fig.add_trace(go.Scatter(
            x=[_LEADER_XY[z][0] for z in nz], y=[_LEADER_XY[z][1] for z in nz],
            mode="markers+text",
            marker=dict(size=64, color="#30363d",
                        line=dict(color="#0d1117", width=2)),
            text=["—"] * len(nz), textposition="middle center",
            textfont=dict(size=11, color="#8b949e"),
            hovertext=[f"{ZONE_FULLNAME[z]}<br>no qualifier (<3 att)" for z in nz],
            hovertemplate="%{hovertext}<extra></extra>", showlegend=False))
    _court_layout(fig, title, height)
    return fig, bool(qz)


def _hex_centers(s):
    """Staggered (pointy-top) hex-grid centres covering the court, spacing `s` ft."""
    vy = s * np.sqrt(3) / 2.0
    centers, row, y = [], 0, CG.Y_MIN
    while y <= CG.Y_MAX + vy:
        xoff = (s / 2.0) if row % 2 else 0.0
        x = CG.X_MIN + xoff
        while x <= CG.X_MAX:
            centers.append((x, y))
            x += s
        y += vy
        row += 1
    return centers


def shot_hexbin(shots, title="Shot hexbin", height=480, hex_ft=2.6, min_count=1,
                league_pps=None):
    """NBA-style hexbin: hexagon size ∝ shot volume, colour = points-per-shot.

    `league_pps` centres the diverging colour scale (red below league, green
    above). Returns ``(figure, n_hexes)``; 0 means nothing met `min_count`."""
    fig = go.Figure()
    _draw_court(fig)
    centers = _hex_centers(hex_ft)
    if not shots or not centers:
        _court_layout(fig, title, height)
        return fig, 0
    cx = np.array([c[0] for c in centers])
    cy = np.array([c[1] for c in centers])
    cnt = np.zeros(len(centers))
    pts = np.zeros(len(centers))
    for sh in shots:
        i = int(np.argmin((cx - sh["x"]) ** 2 + (cy - sh["y"]) ** 2))
        cnt[i] += 1
        pts[i] += sh["value"] if sh["make"] else 0
    sel = [i for i in range(len(centers)) if cnt[i] >= min_count]
    if not sel:
        _court_layout(fig, title, height)
        return fig, 0
    cmax = float(cnt[sel].max())
    pps = [pts[i] / cnt[i] for i in sel]
    # marker size 12→34 by sqrt(volume)
    sizes = [12 + 22 * (cnt[i] / cmax) ** 0.5 for i in sel]
    mid = league_pps if league_pps is not None else (sum(pps) / len(pps))
    fig.add_trace(go.Scatter(
        x=[cx[i] for i in sel], y=[cy[i] for i in sel], mode="markers",
        marker=dict(symbol="hexagon", size=sizes, color=pps, colorscale="RdYlGn",
                    cmid=mid, showscale=True,
                    colorbar=dict(title="PPS", thickness=12, len=0.6, x=1.0),
                    line=dict(width=0.5, color="#0d1117")),
        hovertext=[f"{int(cnt[i])} shots · {pts[i] / cnt[i]:.2f} pts/shot" for i in sel],
        hoverinfo="text", showlegend=False))
    _court_layout(fig, title, height)
    return fig, len(sel)


def expected_points_surface(model, shots=None, title="Expected points / shot",
                            height=480, grid_ft=1.0, overlay=False):
    """Filled contour of expected points per shot across the court (from the
    distance×value make-rate model). Optionally overlays the given shots.
    Returns the figure."""
    from helpers.stats import expected_points_at
    fig = go.Figure()
    xs = np.arange(CG.X_MIN, CG.X_MAX + grid_ft, grid_ft)
    ys = np.arange(0.0, CG.Y_MAX + grid_ft, grid_ft)
    Z = np.empty((len(ys), len(xs)))
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            Z[j, i] = expected_points_at(float(x), float(y), model)
    fig.add_trace(go.Contour(
        x=xs, y=ys, z=Z, colorscale="YlOrRd", zmin=0.0,
        zmax=float(max(1.5, np.nanmax(Z))), opacity=0.85,
        contours=dict(showlines=False), line=dict(width=0),
        colorbar=dict(title="xPts", thickness=12, len=0.6, x=1.0)))
    _draw_court(fig)
    if overlay and shots:
        fig.add_trace(go.Scatter(
            x=[s["x"] for s in shots], y=[s["y"] for s in shots], mode="markers",
            marker=dict(size=5, color=["#3fb950" if s["make"] else "#e74c3c"
                                       for s in shots],
                        line=dict(width=0)),
            hoverinfo="skip", showlegend=False, opacity=0.5))
    _court_layout(fig, title, height)
    return fig


def hot_zones(zone_data):
    """5-zone (LC/LW/C/RW/RC) make/attempt grid for 2PT and 3PT, rendered inline."""
    for stype, lbl in [(2, "2-Point"), (3, "3-Point")]:
        st.markdown(f"<span style='font-size:12px;color:#8b949e'>{lbl}</span>",
                    unsafe_allow_html=True)
        cols = st.columns(5)
        for col, zone in zip(cols, ("LC", "LW", "C", "RW", "RC")):
            d = zone_data.get((zone, stype), {"FGA": 0, "FGM": 0, "pct": 0.0})
            m, a = d["FGM"], d["FGA"]
            pct = d["pct"] * 100 if a else 0
            bg = fgp_color(d["pct"], a)
            fg = "#fff" if a else "#6e7681"
            col.markdown(
                f"<div style='background:{bg};color:{fg};padding:11px 4px;"
                f"border-radius:8px;text-align:center;font-size:12px'>"
                f"<b>{zone}</b><br>{m}/{a}<br>{pct:.0f}%</div>",
                unsafe_allow_html=True)
