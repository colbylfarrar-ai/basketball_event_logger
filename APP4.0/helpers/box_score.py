"""
box_score.py — Reusable, tabbed single-game box-score report.

UI helper (imports streamlit): call `render_box_score(game_id)` from any page
that has a game in context. Everything is recomputed from `game_events`, so it
stays consistent with the source of truth. Advanced-metric formulas come from
helpers/stats.py; PF is credited to the fouler (secondary_player_id).
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.settings_utils import get_setting
import helpers.stats as S

ZONES = ["LC", "LW", "C", "RW", "RC"]
ZONE_LABELS = {"LC": "Left Corner", "LW": "Left Wing", "C": "Paint / Center",
               "RW": "Right Wing", "RC": "Right Corner"}
CARD_BG = "#161b22"
GRID = "#21262d"


# ══════════════════════════════════════════════════════════════════════════════
#  TIME HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _clock_secs(t: str) -> float:
    try:
        m, s = t.strip().split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return 0.0


def _q_len(q: int) -> int:
    return 480 if q <= 4 else 240


def _q_base(q: int) -> int:
    return 480 * (q - 1) if q <= 4 else 480 * 4 + 240 * (q - 5)


def _elapsed(q: int, t: str) -> float:
    return _q_base(q) + (_q_len(q) - _clock_secs(t))


def _q_label(q: int) -> str:
    return f"Q{q}" if q <= 4 else f"OT{q - 4}"


# ══════════════════════════════════════════════════════════════════════════════
#  AGGREGATION  (stats.py-compatible; PF charged to the fouler)
# ══════════════════════════════════════════════════════════════════════════════

def _build_boxes(game_id, t1id, t2id):
    """
    Returns (boxes, team_pts, quarters).

    The per-player box comes straight from the stats engine
    (`S.aggregate_player_boxes`) so any box field the engine gains — AST2/AST3,
    stocks, paint_PTS, etc. — automatically appears here. We only decorate each
    box with roster meta (name/#/team) plus MIN and +/- (game-specific, not in
    the engine), and compute team points and the quarter breakdown.
    """
    boxes_raw = S.aggregate_player_boxes([game_id])
    roster = query(
        "SELECT id AS pid, name, number, team_id FROM players "
        "WHERE team_id IN (?,?) ORDER BY number, name", (t1id, t2id))
    meta = {p["pid"]: p for p in roster}
    team_of = {p["pid"]: p["team_id"] for p in roster}

    mins = {r["player_id"]: (r["secs"] or 0.0) for r in query(
        "SELECT gel.player_id, SUM(ge.possession_secs) AS secs "
        "FROM game_event_lineup gel JOIN game_events ge ON ge.id=gel.event_id "
        "WHERE ge.game_id=? AND ge.possession_secs>0 GROUP BY gel.player_id", (game_id,))}
    pm = {r["player_id"]: r["plus_minus"] for r in query(
        "SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?", (game_id,))}

    boxes = {}
    for pid, b in boxes_raw.items():
        m = meta.get(pid)
        if not m:
            continue
        b = dict(b)
        b.update(name=m["name"], number=m["number"], team_id=m["team_id"],
                 MIN=round(mins.get(pid, 0.0) / 60, 1), PM=pm.get(pid, 0))
        boxes[pid] = b

    team_pts = {t1id: 0, t2id: 0}
    for b in boxes.values():
        if b["team_id"] in team_pts:
            team_pts[b["team_id"]] += b["PTS"]

    quarters = {}
    for r in query("""
        SELECT ge.quarter AS q, p.team_id AS tid,
               SUM(CASE WHEN ge.event_type='shot' AND ge.shot_result='make' THEN ge.shot_type
                        WHEN ge.event_type='free_throw' AND ge.shot_result='make' THEN 1
                        ELSE 0 END) AS pts
        FROM game_events ge JOIN players p ON p.id=ge.primary_player_id
        WHERE ge.game_id=? AND ge.shot_result='make'
        GROUP BY ge.quarter, p.team_id""", (game_id,)):
        quarters.setdefault(r["q"], {t1id: 0, t2id: 0})
        if r["tid"] in quarters[r["q"]]:
            quarters[r["q"]][r["tid"]] += (r["pts"] or 0)

    return boxes, team_pts, quarters


def _team_total(boxes, tid):
    keys = list(S.finalize_box(S._blank_box()).keys())
    tb = {k: 0 for k in keys}
    for b in boxes.values():
        if b["team_id"] == tid:
            for k in keys:
                tb[k] += b.get(k, 0)
    return tb


def _pct(n, d):
    return f"{100*n/d:.1f}%" if d else "—"


# ══════════════════════════════════════════════════════════════════════════════
#  PLOTLY STYLING
# ══════════════════════════════════════════════════════════════════════════════

def _style(fig, height=330, **kw):
    fig.update_layout(
        template="plotly_dark", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=CARD_BG,
        margin=dict(l=46, r=22, t=46, b=42),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified", font=dict(size=12, color="#c9d1d9"),
        bargap=0.22, **kw)
    fig.update_xaxes(gridcolor=GRID, zerolinecolor="#30363d", showline=False)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor="#30363d", showline=False)
    return fig


def _quarter_bands(fig, qs, end_t):
    """Alternating shaded bands per quarter for depth on time-axis charts."""
    for i, q in enumerate(qs):
        x0 = _q_base(q)
        x1 = _q_base(q) + _q_len(q)
        if i % 2 == 1:
            fig.add_vrect(x0=x0, x1=min(x1, end_t), fillcolor="#ffffff",
                          opacity=0.025, layer="below", line_width=0)


def _bar(text):
    return dict(texttemplate=text, textposition="outside",
               textfont=dict(size=11), cliponaxis=False)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY
# ══════════════════════════════════════════════════════════════════════════════

def render_box_score(game_id: int):
    """Render the full tabbed box-score report for one game."""
    accent = get_setting("accent_color", "#f0a500")   # home / team1
    away = "#e74c3c"                                    # away / team2

    g = query("""
        SELECT g.*, t1.name AS t1_name, t2.name AS t2_name
        FROM games g JOIN teams t1 ON t1.id=g.team1_id JOIN teams t2 ON t2.id=g.team2_id
        WHERE g.id=?""", (game_id,))
    if not g:
        st.info("Game not found.")
        return
    g = g[0]
    t1id, t2id = g["team1_id"], g["team2_id"]
    t1name, t2name = g["t1_name"], g["t2_name"]        # t1 = home, t2 = away

    boxes, team_pts, quarters = _build_boxes(game_id, t1id, t2id)
    if not any(team_pts.values()) and not quarters:
        st.info("No events have been logged for this game yet.")
        return

    home_pts, away_pts = team_pts[t1id], team_pts[t2id]
    home_win = home_pts > away_pts
    htb, atb = _team_total(boxes, t1id), _team_total(boxes, t2id)
    h_poss, a_poss = S.estimate_possessions(htb), S.estimate_possessions(atb)
    qs = sorted(quarters.keys())
    end_t = _q_base(max(qs)) + _q_len(max(qs)) if qs else 0

    # ── Scoreboard hero (always on top) ─────────────────────────────────────────
    def block(name, pts, won, color):
        cls = color if won else "#555d68"
        tag = "▸ " if won else ""
        return (f"<div style='text-align:center'>"
                f"<div style='font-size:15px;font-weight:700;color:#c9d1d9'>{tag}{name}</div>"
                f"<div style='font-size:48px;font-weight:900;color:{cls};line-height:1'>{pts}</div>"
                f"</div>")

    st.markdown(
        f"<div class='game-hero'>"
        f"<div style='font-size:12px;color:#8b949e;margin-bottom:6px'>{g['date']}"
        f"{' · ' + g['location'] if g['location'] else ''}"
        f"{' · FINAL' if g['tracked'] else ' · IN PROGRESS'}</div>"
        f"<table style='width:100%;border:none'><tr>"
        f"<td style='width:42%'>{block(t2name, away_pts, not home_win, away)}</td>"
        f"<td style='width:16%;text-align:center;color:#8b949e;font-size:18px'>@</td>"
        f"<td style='width:42%'>{block(t1name, home_pts, home_win, accent)}</td>"
        f"</tr></table></div>", unsafe_allow_html=True)

    tabs = st.tabs(["📊 Overview", "📈 Scoring & Flow", "🎯 Shooting",
                    "🧮 Advanced", "📋 Box Score", "🛡️ Hustle"])

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 0 — OVERVIEW
    # ════════════════════════════════════════════════════════════════════════
    with tabs[0]:
        # headline metrics (home edge shown as delta vs opponent)
        m = st.columns(5)
        m[0].metric(f"{t1name} PTS", home_pts, home_pts - away_pts)
        m[1].metric("FG%", f"{100*S._safe(htb['FGM'],htb['FGA']):.1f}%",
                    f"{100*(S._safe(htb['FGM'],htb['FGA'])-S._safe(atb['FGM'],atb['FGA'])):+.1f} pp")
        m[2].metric("Rebounds", htb["TRB"], htb["TRB"] - atb["TRB"])
        m[3].metric("Assists", htb["AST"], htb["AST"] - atb["AST"])
        m[4].metric("Turnovers", htb["TOV"], htb["TOV"] - atb["TOV"], delta_color="inverse")
        st.caption(f"Deltas are {t1name} relative to {t2name}.")

        # line score
        line = []
        for tid, nm in [(t2id, t2name), (t1id, t1name)]:
            row, tot = {"Team": nm}, 0
            for q in qs:
                v = quarters[q].get(tid, 0); row[_q_label(q)] = v; tot += v
            row["T"] = tot
            line.append(row)
        st.dataframe(pd.DataFrame(line), hide_index=True, width="stretch",
                     key=f"bs{game_id}_linescore")

        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown("**Team comparison**")
            comp = pd.DataFrame([
                {"Stat": "Field goals", t2name: f"{atb['FGM']}-{atb['FGA']} ({_pct(atb['FGM'],atb['FGA'])})",
                 t1name: f"{htb['FGM']}-{htb['FGA']} ({_pct(htb['FGM'],htb['FGA'])})"},
                {"Stat": "3-pointers", t2name: f"{atb['3PM']}-{atb['3PA']} ({_pct(atb['3PM'],atb['3PA'])})",
                 t1name: f"{htb['3PM']}-{htb['3PA']} ({_pct(htb['3PM'],htb['3PA'])})"},
                {"Stat": "Free throws", t2name: f"{atb['FTM']}-{atb['FTA']} ({_pct(atb['FTM'],atb['FTA'])})",
                 t1name: f"{htb['FTM']}-{htb['FTA']} ({_pct(htb['FTM'],htb['FTA'])})"},
                {"Stat": "eFG% / TS%", t2name: f"{100*S.efg(atb):.1f}% / {100*S.ts(atb):.1f}%",
                 t1name: f"{100*S.efg(htb):.1f}% / {100*S.ts(htb):.1f}%"},
                {"Stat": "Rebounds (O-D)", t2name: f"{atb['TRB']} ({atb['ORB']}-{atb['DRB']})",
                 t1name: f"{htb['TRB']} ({htb['ORB']}-{htb['DRB']})"},
                {"Stat": "Assists / Steals / Blocks",
                 t2name: f"{atb['AST']} / {atb['STL']} / {atb['BLK']}",
                 t1name: f"{htb['AST']} / {htb['STL']} / {htb['BLK']}"},
                {"Stat": "Turnovers / Fouls", t2name: f"{atb['TOV']} / {atb['PF']}",
                 t1name: f"{htb['TOV']} / {htb['PF']}"},
                {"Stat": "Paint points", t2name: f"{atb['paint_PTS']}", t1name: f"{htb['paint_PTS']}"},
                {"Stat": "3PA rate / FT rate",
                 t2name: f"{100*S.three_par(atb):.0f}% / {100*S.ftr(atb):.0f}%",
                 t1name: f"{100*S.three_par(htb):.0f}% / {100*S.ftr(htb):.0f}%"},
                {"Stat": "Points per shot (PPS)",
                 t2name: f"{S.pps(atb):.2f}", t1name: f"{S.pps(htb):.2f}"},
                {"Stat": "Turnover %", t2name: f"{S.tov_pct(atb):.1f}%", t1name: f"{S.tov_pct(htb):.1f}%"},
                {"Stat": "Possessions", t2name: f"{a_poss:.0f}", t1name: f"{h_poss:.0f}"},
                {"Stat": "Off. rating (pts/100)",
                 t2name: f"{100*away_pts/a_poss:.1f}" if a_poss else "—",
                 t1name: f"{100*home_pts/h_poss:.1f}" if h_poss else "—"},
            ])
            comp[t1name] = comp[t1name].astype(str)
            comp[t2name] = comp[t2name].astype(str)
            st.dataframe(comp, hide_index=True, width="stretch",
                         key=f"bs{game_id}_comp")
        with c2:
            st.markdown("**Shooting profile**")
            cats = ["FG%", "3P%", "FT%", "eFG%", "TS%"]
            av = [100*S._safe(atb['FGM'],atb['FGA']), 100*S._safe(atb['3PM'],atb['3PA']),
                  100*S._safe(atb['FTM'],atb['FTA']), 100*S.efg(atb), 100*S.ts(atb)]
            hv = [100*S._safe(htb['FGM'],htb['FGA']), 100*S._safe(htb['3PM'],htb['3PA']),
                  100*S._safe(htb['FTM'],htb['FTA']), 100*S.efg(htb), 100*S.ts(htb)]
            rad = go.Figure()
            for nm, vals, clr in [(t2name, av, away), (t1name, hv, accent)]:
                rr, rg, rb = int(clr[1:3], 16), int(clr[3:5], 16), int(clr[5:7], 16)
                rad.add_trace(go.Scatterpolar(
                    r=vals + [vals[0]], theta=cats + [cats[0]], fill="toself",
                    name=nm, line=dict(color=clr, width=2),
                    fillcolor=f"rgba({rr},{rg},{rb},0.18)"))
            rad.update_layout(
                template="plotly_dark", height=330,
                paper_bgcolor="rgba(0,0,0,0)",
                polar=dict(bgcolor=CARD_BG,
                           radialaxis=dict(range=[0, 100], gridcolor=GRID, tickfont=dict(size=9)),
                           angularaxis=dict(gridcolor=GRID)),
                margin=dict(l=40, r=40, t=50, b=30),
                legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)"))
            st.plotly_chart(rad, width="stretch", key=f"bs{game_id}_radar")

        # game leaders
        st.markdown("**Game leaders**")

        def leader(stat):
            best = max(boxes.values(), key=lambda b: b[stat], default=None)
            return (best["name"], best[stat]) if best and best[stat] else ("—", 0)
        lc = st.columns(5)
        for col, (lbl, stat) in zip(lc, [("Points", "PTS"), ("Rebounds", "TRB"),
                                          ("Assists", "AST"), ("Steals", "STL"),
                                          ("Blocks", "BLK")]):
            nm, val = leader(stat)
            col.markdown(
                f"<div class='kpi-tile'><div class='kpi-label'>{lbl}</div>"
                f"<div class='kpi-value'>{val}</div>"
                f"<div class='kpi-sub'>{nm}</div></div>", unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 1 — SCORING & FLOW
    # ════════════════════════════════════════════════════════════════════════
    with tabs[1]:
        scoring = query("""
            SELECT ge.quarter, ge.time, ge.event_type, ge.shot_type, p.team_id AS tid
            FROM game_events ge JOIN players p ON p.id=ge.primary_player_id
            WHERE ge.game_id=? AND ge.event_type IN ('shot','free_throw')
              AND ge.shot_result='make' ORDER BY ge.quarter, ge.id""", (game_id,))
        # Plot in game-clock order, not insertion order: events back-filled out
        # of sequence would otherwise send the step line backward in time.
        scoring.sort(key=lambda ev: _elapsed(ev["quarter"], ev["time"]))
        times, hc, ac, h, a = [0.0], [0], [0], 0, 0
        for ev in scoring:
            pts = ev["shot_type"] if ev["event_type"] == "shot" else 1
            if ev["tid"] == t1id:
                h += pts
            elif ev["tid"] == t2id:
                a += pts
            times.append(_elapsed(ev["quarter"], ev["time"])); hc.append(h); ac.append(a)
        times.append(end_t); hc.append(h); ac.append(a)
        xticks = [_q_base(q) for q in qs] + [end_t]
        xlabels = [_q_label(q) for q in qs] + ["End"]

        st.markdown("**Score over time**")
        fig = go.Figure()
        for nm, cum, clr in [(t2name, ac, away), (t1name, hc, accent)]:
            r, gg, bb = int(clr[1:3], 16), int(clr[3:5], 16), int(clr[5:7], 16)
            fig.add_trace(go.Scatter(
                x=times, y=cum, name=nm, line_shape="hv",
                line=dict(color=clr, width=3), fill="tozeroy",
                fillcolor=f"rgba({r},{gg},{bb},0.12)",
                hovertemplate=nm + ": %{y}<extra></extra>"))
        _quarter_bands(fig, qs, end_t)
        for v in xticks[1:-1]:
            fig.add_vline(x=v, line=dict(color="#30363d", width=1, dash="dot"))
        fig.update_xaxes(tickvals=xticks, ticktext=xlabels, title="Game clock")
        fig.update_yaxes(title="Points")
        _style(fig, 360)
        st.plotly_chart(fig, width="stretch", key=f"bs{game_id}_score_time")

        # margin
        margin = [x - y for x, y in zip(hc, ac)]
        lead_changes, prev = 0, 0
        for mm in margin:
            s = (mm > 0) - (mm < 0)
            if s and prev and s != prev:
                lead_changes += 1
            if s:
                prev = s
        st.markdown("**Lead margin**")
        mfig = go.Figure()
        ar, ag, ab = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
        mfig.add_trace(go.Scatter(
            x=times, y=margin, line_shape="hv", name="Margin",
            line=dict(color=accent, width=2), fill="tozeroy",
            fillcolor=f"rgba({ar},{ag},{ab},0.15)",
            hovertemplate="Margin: %{y}<extra></extra>"))
        mfig.add_hline(y=0, line=dict(color="#30363d", width=1))
        _quarter_bands(mfig, qs, end_t)
        mfig.update_xaxes(tickvals=xticks, ticktext=xlabels, title="Game clock")
        mfig.update_yaxes(title=f"+{t1name}  /  −{t2name}")
        _style(mfig, 260)
        st.plotly_chart(mfig, width="stretch", key=f"bs{game_id}_margin")
        f1, f2, f3 = st.columns(3)
        f1.metric(f"Biggest lead · {t1name}", f"+{max(margin) if margin else 0}")
        f2.metric(f"Biggest lead · {t2name}", f"+{-min(margin) if margin else 0}")
        f3.metric("Lead changes", lead_changes)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Points by quarter**")
            qfig = go.Figure()
            for nm, tid, clr in [(t2name, t2id, away), (t1name, t1id, accent)]:
                ys = [quarters[q].get(tid, 0) for q in qs]
                qfig.add_trace(go.Bar(x=[_q_label(q) for q in qs], y=ys, name=nm,
                                      marker_color=clr, text=ys,
                                      marker_line_width=0, **_bar("%{text}")))
            qfig.update_layout(barmode="group")
            _style(qfig, 320)
            st.plotly_chart(qfig, width="stretch", key=f"bs{game_id}_pts_qtr")
        with c2:
            st.markdown("**Player scoring**")
            pls = sorted([b for b in boxes.values() if b["PTS"] > 0],
                         key=lambda b: b["PTS"])
            if pls:
                colors = [accent if b["team_id"] == t1id else away for b in pls]
                pfig = go.Figure(go.Bar(
                    x=[b["PTS"] for b in pls], y=[b["name"] for b in pls],
                    orientation="h", marker_color=colors, text=[b["PTS"] for b in pls],
                    textposition="auto", marker_line_width=0))
                pfig.update_xaxes(title="Points")
                _style(pfig, max(320, 30 * len(pls)))
                st.plotly_chart(pfig, width="stretch", key=f"bs{game_id}_player_scoring")
            else:
                st.info("No scoring yet.")

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 2 — SHOOTING
    # ════════════════════════════════════════════════════════════════════════
    with tabs[2]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Shooting efficiency**")
            cats = ["FG%", "2P%", "3P%", "FT%", "Paint%", "eFG%", "TS%"]
            av = [100*S.fg_pct(atb), 100*S.fg2_pct(atb), 100*S.fg3_pct(atb),
                  100*S.ft_pct(atb), 100*S.paint_fg_pct(atb), 100*S.efg(atb), 100*S.ts(atb)]
            hv = [100*S.fg_pct(htb), 100*S.fg2_pct(htb), 100*S.fg3_pct(htb),
                  100*S.ft_pct(htb), 100*S.paint_fg_pct(htb), 100*S.efg(htb), 100*S.ts(htb)]
            sfig = go.Figure()
            sfig.add_trace(go.Bar(x=cats, y=[round(v, 1) for v in av], name=t2name,
                                  marker_color=away, text=[f"{v:.0f}" for v in av],
                                  marker_line_width=0, **_bar("%{text}%")))
            sfig.add_trace(go.Bar(x=cats, y=[round(v, 1) for v in hv], name=t1name,
                                  marker_color=accent, text=[f"{v:.0f}" for v in hv],
                                  marker_line_width=0, **_bar("%{text}%")))
            sfig.update_layout(barmode="group")
            sfig.update_yaxes(title="%", range=[0, 105])
            _style(sfig, 330)
            st.plotly_chart(sfig, width="stretch", key=f"bs{game_id}_shoot_eff")
        with c2:
            st.markdown("**How shots were created**")
            cats = ["Self", "Off pass", "Off screen", "Pass+screen"]
            keys = ["shots_self", "shots_pass", "shots_sc", "shots_both"]
            cfig = go.Figure()
            for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
                ys = [tb[k] for k in keys]
                cfig.add_trace(go.Bar(x=cats, y=ys, name=nm, marker_color=clr,
                                      text=ys, marker_line_width=0, **_bar("%{text}")))
            cfig.update_layout(barmode="group")
            cfig.update_yaxes(title="Shot attempts")
            _style(cfig, 330)
            st.plotly_chart(cfig, width="stretch", key=f"bs{game_id}_shot_creation")

        # scoring composition donuts
        st.markdown("**Where the points came from**")
        d1, d2 = st.columns(2)
        for di, (col, nm, tb, clr) in enumerate([(d1, t2name, atb, away), (d2, t1name, htb, accent)]):
            vals = [tb["2PM"]*2, tb["3PM"]*3, tb["FTM"]]
            tot = sum(vals)
            don = go.Figure(go.Pie(
                labels=["2-pt", "3-pt", "Free throws"], values=vals, hole=0.62,
                marker=dict(colors=[clr, "#58a6ff", "#8b949e"],
                            line=dict(color="#0d1117", width=2)),
                textinfo="label+percent", sort=False))
            don.update_layout(
                template="plotly_dark", height=300, showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=40, b=10),
                title=dict(text=nm, x=0.5, font=dict(size=13)),
                annotations=[dict(text=f"<b>{tot}</b><br>pts", x=0.5, y=0.5,
                                  font=dict(size=18, color="#f0f6fc"), showarrow=False)])
            col.plotly_chart(don, width="stretch", key=f"bs{game_id}_donut{di}")

        # zones
        st.markdown("**Shot distribution by zone**")
        zr = query("""
            SELECT p.team_id AS tid, ge.zone, COUNT(*) AS fga,
                   SUM(CASE WHEN ge.shot_result='make' THEN 1 ELSE 0 END) AS fgm
            FROM game_events ge JOIN players p ON p.id=ge.primary_player_id
            WHERE ge.game_id=? AND ge.event_type='shot' AND ge.zone IS NOT NULL
            GROUP BY p.team_id, ge.zone""", (game_id,))
        zmap = defaultdict(lambda: {"fga": 0, "fgm": 0})
        for r in zr:
            zmap[(r["tid"], r["zone"])] = {"fga": r["fga"], "fgm": r["fgm"] or 0}
        zfig = go.Figure()
        for nm, tid, clr in [(t2name, t2id, away), (t1name, t1id, accent)]:
            ys = [zmap[(tid, z)]["fga"] for z in ZONES]
            txt = [f"{zmap[(tid,z)]['fgm']}/{zmap[(tid,z)]['fga']}"
                   + (f" · {100*zmap[(tid,z)]['fgm']/zmap[(tid,z)]['fga']:.0f}%"
                      if zmap[(tid,z)]['fga'] else "") for z in ZONES]
            zfig.add_trace(go.Bar(x=[ZONE_LABELS[z] for z in ZONES], y=ys, name=nm,
                                  marker_color=clr, text=txt, textposition="auto",
                                  marker_line_width=0))
        zfig.update_layout(barmode="group")
        zfig.update_yaxes(title="Attempts")
        _style(zfig, 340)
        st.plotly_chart(zfig, width="stretch", key=f"bs{game_id}_zones")

        z1, z2 = st.columns(2)
        with z1:
            st.markdown("**Shot diet** (3PA rate · FT rate · PPS)")
            cats = ["3PA rate", "FT rate", "PPS ×100"]
            mfig = go.Figure()
            for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
                ys = [round(100*S.three_par(tb), 1), round(100*S.ftr(tb), 1),
                      round(100*S.pps(tb), 1)]
                mfig.add_trace(go.Bar(x=cats, y=ys, name=nm, marker_color=clr,
                                      text=ys, marker_line_width=0, **_bar("%{text}")))
            mfig.update_layout(barmode="group")
            _style(mfig, 320)
            st.plotly_chart(mfig, width="stretch", key=f"bs{game_id}_shot_diet")
        with z2:
            st.markdown("**Paint vs perimeter points**")
            pfig = go.Figure()
            for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
                paint = tb["paint_PTS"]
                mid = tb["2PM"] * 2 - paint
                three = tb["3PM"] * 3
                ft = tb["FTM"]
                pfig.add_trace(go.Bar(
                    x=["Paint", "Mid-range 2", "3-pt", "Free throws"],
                    y=[paint, mid, three, ft], name=nm, marker_color=clr,
                    text=[paint, mid, three, ft], marker_line_width=0, **_bar("%{text}")))
            pfig.update_layout(barmode="group")
            pfig.update_yaxes(title="Points")
            _style(pfig, 320)
            st.plotly_chart(pfig, width="stretch", key=f"bs{game_id}_paint_perim")

        s1, s2 = st.columns(2)
        with s1:
            st.markdown("**Scoring source %** (share of points)")
            src = ["Paint", "Mid 2", "3-pt", "FT"]
            colors = [accent, "#9b59b6", "#58a6ff", "#8b949e"]
            ssfig = go.Figure()
            for nm, tb in [(t2name, atb), (t1name, htb)]:
                tot = tb["PTS"] or 1
                vals = [tb["paint_PTS"], tb["2PM"]*2 - tb["paint_PTS"],
                        tb["3PM"]*3, tb["FTM"]]
                shares = [100*v/tot for v in vals]
                for cat, sh, cl in zip(src, shares, colors):
                    ssfig.add_trace(go.Bar(
                        y=[nm], x=[sh], orientation="h", name=cat,
                        marker_color=cl, marker_line_width=0,
                        text=f"{sh:.0f}%" if sh >= 7 else "", textposition="inside",
                        legendgroup=cat, showlegend=(nm == t2name),
                        hovertemplate=f"{cat}: %{{x:.0f}}%<extra></extra>"))
            ssfig.update_layout(barmode="stack")
            ssfig.update_xaxes(title="% of points", range=[0, 100])
            _style(ssfig, 300)
            st.plotly_chart(ssfig, width="stretch", key=f"bs{game_id}_scoring_src")
        with s2:
            st.markdown("**Assisted FG % · shot creation %**")
            cats = ["Assisted FG%", "Self-created", "Off pass", "Off screen"]
            afig = go.Figure()
            for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
                bd = S.shot_breakdown_pct(tb)
                ast_pct = 100*S._safe(tb["AST"], tb["FGM"])
                ys = [round(ast_pct, 1), round(100*bd["self"], 1),
                      round(100*bd["pass"], 1), round(100*bd["sc"], 1)]
                afig.add_trace(go.Bar(x=cats, y=ys, name=nm, marker_color=clr,
                                      text=[f"{v:.0f}%" for v in ys],
                                      marker_line_width=0, **_bar("%{text}")))
            afig.update_layout(barmode="group")
            afig.update_yaxes(title="%", range=[0, 105])
            _style(afig, 300)
            st.plotly_chart(afig, width="stretch", key=f"bs{game_id}_assisted_fg")

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 3 — ADVANCED
    # ════════════════════════════════════════════════════════════════════════
    with tabs[3]:
        st.caption("All figures recomputed from this game's events. EFF = NBA "
                   "Efficiency · FIC = Floor Impact Counter · GmSc = Game Score · "
                   "PRF = points responsible for (own pts + pts off assists) · "
                   "PPP/APP/TPP = points/assists/turnovers per usage possession.")

        # team per-possession ratings
        rt = st.columns(4)
        rt[0].metric(f"{t1name} ORtg", f"{100*home_pts/h_poss:.1f}" if h_poss else "—",
                     f"{(100*home_pts/h_poss)-(100*away_pts/a_poss):+.1f}" if h_poss and a_poss else None)
        rt[1].metric(f"{t2name} ORtg", f"{100*away_pts/a_poss:.1f}" if a_poss else "—")
        rt[2].metric(f"{t1name} PPP", f"{S._safe(home_pts, h_poss):.2f}")
        rt[3].metric(f"{t2name} PPP", f"{S._safe(away_pts, a_poss):.2f}")
        st.caption("Ratings are points per 100 possessions; PPP is points per "
                   "possession (FGA + TOV — shots + turnovers).")

        st.markdown("**Per-possession output** (team)")
        ppfig = go.Figure()
        for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
            ys = [round(S.ppp(tb), 2), round(S.app(tb), 2), round(S.tpp(tb), 2)]
            ppfig.add_trace(go.Bar(x=["Pts / poss", "Ast / poss", "TOV / poss"],
                                   y=ys, name=nm, marker_color=clr, text=ys,
                                   marker_line_width=0, **_bar("%{text}")))
        ppfig.update_layout(barmode="group")
        _style(ppfig, 300)
        st.plotly_chart(ppfig, width="stretch", key=f"bs{game_id}_per_poss")

        adv_cols = ["#", "Player", "MIN", "PTS", "POSS", "PPP", "APP", "TPP",
                    "PPS", "2P%", "eFG%", "TS%", "3PAr", "FTr", "TOV%",
                    "PaintPTS", "STK", "EFF", "FIC", "GmSc", "PRF"]

        def adv_df(tid):
            rows = []
            pls = sorted([b for b in boxes.values() if b["team_id"] == tid],
                         key=lambda b: -S.game_score(b))
            for b in pls:
                if not any([b["FGA"], b["FTA"], b["MIN"], b["TRB"], b["AST"],
                            b["PF"], b["TOV"], b["STL"], b["BLK"]]):
                    continue
                rows.append({
                    "#": str(b["number"]), "Player": b["name"], "MIN": b["MIN"],
                    "PTS": b["PTS"], "POSS": round(S.player_possessions(b), 1),
                    "PPP": round(S.ppp(b), 2), "APP": round(S.app(b), 2),
                    "TPP": round(S.tpp(b), 2), "PPS": round(S.pps(b), 2),
                    "2P%": round(100*S.fg2_pct(b), 1), "eFG%": round(100*S.efg(b), 1),
                    "TS%": round(100*S.ts(b), 1), "3PAr": round(100*S.three_par(b), 0),
                    "FTr": round(100*S.ftr(b), 0), "TOV%": round(S.tov_pct(b), 1),
                    "PaintPTS": b["paint_PTS"], "STK": b["stocks"],
                    "EFF": round(S.eff(b), 1), "FIC": round(S.fic(b), 1),
                    "GmSc": round(S.game_score(b), 1), "PRF": round(S.prf(b), 1)})
            return pd.DataFrame(rows, columns=adv_cols)

        acfg = {
            "MIN": st.column_config.NumberColumn("MIN", format="%.1f"),
            "PPP": st.column_config.ProgressColumn("PPP", format="%.2f", min_value=0, max_value=2),
            "TS%": st.column_config.ProgressColumn("TS%", format="%.0f", min_value=0, max_value=100),
            "2P%": st.column_config.ProgressColumn("2P%", format="%.0f", min_value=0, max_value=100),
            "3PAr": st.column_config.NumberColumn("3PAr", format="%d%%"),
            "FTr": st.column_config.NumberColumn("FTr", format="%d%%"),
        }
        for tid, nm in [(t2id, t2name), (t1id, t1name)]:
            st.markdown(f"**{nm}**")
            st.dataframe(adv_df(tid), hide_index=True, width="stretch",
                         column_config=acfg, key=f"bs{game_id}_adv_{tid}")

        # usage vs efficiency bubble
        st.markdown("**Usage vs efficiency** (bubble = points)")
        bub = go.Figure()
        for nm, tid, clr in [(t2name, t2id, away), (t1name, t1id, accent)]:
            pls = [b for b in boxes.values()
                   if b["team_id"] == tid and S.player_possessions(b) >= 1]
            if not pls:
                continue
            bub.add_trace(go.Scatter(
                x=[S.player_possessions(b) for b in pls],
                y=[S.ppp(b) for b in pls], mode="markers+text", name=nm,
                text=[b["name"].split()[-1] for b in pls], textposition="top center",
                textfont=dict(size=9, color="#8b949e"),
                marker=dict(size=[8 + 2.4*b["PTS"] for b in pls], color=clr,
                            opacity=0.75, line=dict(color="#0d1117", width=1))))
        bub.update_xaxes(title="Usage possessions (FGA + TOV)")
        bub.update_yaxes(title="Points per possession")
        _style(bub, 380)
        bub.update_layout(hovermode="closest")
        st.plotly_chart(bub, width="stretch", key=f"bs{game_id}_usage_eff")

        # impact leaderboards
        i1, i2 = st.columns(2)
        with i1:
            st.markdown("**Game Score leaders**")
            pls = sorted([b for b in boxes.values()
                          if any([b["FGA"], b["FTA"], b["TRB"], b["AST"]])],
                         key=lambda b: S.game_score(b))[-12:]
            if pls:
                gfig = go.Figure(go.Bar(
                    x=[round(S.game_score(b), 1) for b in pls],
                    y=[b["name"] for b in pls], orientation="h",
                    marker_color=[accent if b["team_id"] == t1id else away for b in pls],
                    text=[round(S.game_score(b), 1) for b in pls], textposition="auto",
                    marker_line_width=0))
                gfig.update_xaxes(title="Game Score")
                _style(gfig, max(300, 26*len(pls)))
                st.plotly_chart(gfig, width="stretch", key=f"bs{game_id}_gmsc_leaders")
        with i2:
            st.markdown("**Points responsible for (PRF)**")
            pls = sorted([b for b in boxes.values() if S.prf(b) > 0],
                         key=lambda b: S.prf(b))[-12:]
            if pls:
                rfig = go.Figure(go.Bar(
                    x=[round(S.prf(b), 1) for b in pls],
                    y=[b["name"] for b in pls], orientation="h",
                    marker_color=[accent if b["team_id"] == t1id else away for b in pls],
                    text=[round(S.prf(b), 1) for b in pls], textposition="auto",
                    marker_line_width=0))
                rfig.update_xaxes(title="Points created (self + assisted)")
                _style(rfig, max(300, 26*len(pls)))
                st.plotly_chart(rfig, width="stretch", key=f"bs{game_id}_prf_leaders")

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 4 — BOX SCORE
    # ════════════════════════════════════════════════════════════════════════
    with tabs[4]:
        cols = ["#", "Player", "MIN", "PTS", "FG", "FG%", "3P", "3P%", "FT", "FT%",
                "ORB", "DRB", "REB", "AST", "STL", "BLK", "TOV", "PF", "+/-",
                "SC", "eFG%", "TS%", "GS"]

        def make_df(tid):
            rows = []
            pls = sorted([b for b in boxes.values() if b["team_id"] == tid],
                         key=lambda b: (-b["PTS"], -b["MIN"]))
            for b in pls:
                if not any([b["FGA"], b["FTA"], b["MIN"], b["TRB"], b["AST"],
                            b["PF"], b["TOV"], b["STL"], b["BLK"]]):
                    continue
                rows.append({
                    "#": str(b["number"]), "Player": b["name"], "MIN": b["MIN"], "PTS": b["PTS"],
                    "FG": f"{b['FGM']}-{b['FGA']}", "FG%": round(100*S._safe(b['FGM'],b['FGA']),1),
                    "3P": f"{b['3PM']}-{b['3PA']}", "3P%": round(100*S._safe(b['3PM'],b['3PA']),1),
                    "FT": f"{b['FTM']}-{b['FTA']}", "FT%": round(100*S._safe(b['FTM'],b['FTA']),1),
                    "ORB": b["ORB"], "DRB": b["DRB"], "REB": b["TRB"], "AST": b["AST"],
                    "STL": b["STL"], "BLK": b["BLK"], "TOV": b["TOV"], "PF": b["PF"],
                    "+/-": b["PM"], "SC": b["SC"], "eFG%": round(100*S.efg(b),1),
                    "TS%": round(100*S.ts(b),1), "GS": round(S.game_score(b),1)})
            tb = _team_total(boxes, tid)
            rows.append({
                "#": "", "Player": "TOTAL", "MIN": None, "PTS": tb["PTS"],
                "FG": f"{tb['FGM']}-{tb['FGA']}", "FG%": round(100*S._safe(tb['FGM'],tb['FGA']),1),
                "3P": f"{tb['3PM']}-{tb['3PA']}", "3P%": round(100*S._safe(tb['3PM'],tb['3PA']),1),
                "FT": f"{tb['FTM']}-{tb['FTA']}", "FT%": round(100*S._safe(tb['FTM'],tb['FTA']),1),
                "ORB": tb["ORB"], "DRB": tb["DRB"], "REB": tb["TRB"], "AST": tb["AST"],
                "STL": tb["STL"], "BLK": tb["BLK"], "TOV": tb["TOV"], "PF": tb["PF"],
                "+/-": None, "SC": tb["SC"], "eFG%": round(100*S.efg(tb),1),
                "TS%": round(100*S.ts(tb),1), "GS": None})
            return pd.DataFrame(rows, columns=cols)

        pcfg = {
            "MIN": st.column_config.NumberColumn("MIN", format="%.1f"),
            "PTS": st.column_config.NumberColumn("PTS", format="%d"),
            "FG%": st.column_config.ProgressColumn("FG%", format="%.0f", min_value=0, max_value=100),
            "3P%": st.column_config.ProgressColumn("3P%", format="%.0f", min_value=0, max_value=100),
            "FT%": st.column_config.ProgressColumn("FT%", format="%.0f", min_value=0, max_value=100),
            "TS%": st.column_config.ProgressColumn("TS%", format="%.0f", min_value=0, max_value=100),
            "eFG%": st.column_config.NumberColumn("eFG%", format="%.1f"),
            "+/-": st.column_config.NumberColumn("+/-", format="%d"),
            "GS": st.column_config.NumberColumn("GS", format="%.1f"),
        }
        for tid, nm in [(t2id, t2name), (t1id, t1name)]:
            st.markdown(f"**{nm}**")
            df = make_df(tid)
            st.dataframe(df, hide_index=True, width="stretch", column_config=pcfg,
                         key=f"bs{game_id}_box_{tid}")
            st.download_button(f"⬇ {nm} box (CSV)", df.to_csv(index=False),
                               file_name=f"box_{game_id}_{nm}.csv", mime="text/csv",
                               key=f"dl_box_{game_id}_{tid}")

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 5 — HUSTLE
    # ════════════════════════════════════════════════════════════════════════
    with tabs[5]:
        st.markdown("**Rebounds · assists · defense (team totals)**")
        cats = ["OREB", "DREB", "AST", "STL", "BLK", "STOCKS", "TOV"]
        hfig = go.Figure()
        for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
            ys = [tb["ORB"], tb["DRB"], tb["AST"], tb["STL"], tb["BLK"],
                  tb["stocks"], tb["TOV"]]
            hfig.add_trace(go.Bar(x=cats, y=ys, name=nm, marker_color=clr,
                                  text=ys, marker_line_width=0, **_bar("%{text}")))
        hfig.update_layout(barmode="group")
        _style(hfig, 340)
        st.plotly_chart(hfig, width="stretch", key=f"bs{game_id}_hustle")

        h1, h2 = st.columns(2)
        with h1:
            st.markdown("**Assist value** (2-pt vs 3-pt assists)")
            afig = go.Figure()
            afig.add_trace(go.Bar(x=[t2name, t1name], y=[atb["AST2"], htb["AST2"]],
                                  name="2-pt assists", marker_color="#58a6ff",
                                  marker_line_width=0))
            afig.add_trace(go.Bar(x=[t2name, t1name], y=[atb["AST3"], htb["AST3"]],
                                  name="3-pt assists", marker_color=accent,
                                  marker_line_width=0))
            afig.update_layout(barmode="stack")
            afig.update_yaxes(title="Assists")
            _style(afig, 320)
            st.plotly_chart(afig, width="stretch", key=f"bs{game_id}_assist_value")
        with h2:
            st.markdown("**Rebound share** (offensive vs defensive)")
            rb = go.Figure()
            for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
                rb.add_trace(go.Bar(x=["OREB", "DREB"], y=[tb["ORB"], tb["DRB"]],
                                    name=nm, marker_color=clr, text=[tb["ORB"], tb["DRB"]],
                                    marker_line_width=0, **_bar("%{text}")))
            rb.update_layout(barmode="group")
            _style(rb, 320)
            st.plotly_chart(rb, width="stretch", key=f"bs{game_id}_reb_share")

        st.markdown("**Shots created** (shoot + pass-to-shot + screen-to-shot)")
        sc_rows = []
        for b in sorted(boxes.values(), key=lambda b: -b["SC"]):
            if b["SC"]:
                sc_rows.append({"Player": b["name"],
                                "Team": t1name if b["team_id"] == t1id else t2name,
                                "Shooting": b["SC_shoot"], "Passing": b["SC_pass"],
                                "Screening": b["SC_screen"], "Total SC": b["SC"]})
        if sc_rows:
            st.dataframe(pd.DataFrame(sc_rows), hide_index=True, width="stretch",
                         key=f"bs{game_id}_sc",
                         column_config={"Total SC": st.column_config.ProgressColumn(
                             "Total SC", format="%d", min_value=0,
                             max_value=max(r["Total SC"] for r in sc_rows))})

    st.caption("Recomputed from game_events. Advanced formulas from helpers/stats.py; "
               "PF credited to the fouler.")
