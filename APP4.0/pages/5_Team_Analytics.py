"""
5_Team_Analytics.py — the single-team deep dive.

Pick one team and read everything about it across five tabs:

  • Overview   — a coach's one-glance card: record, power ratings, best players,
                 four-factor snapshot, scoring mix and the margin trend.
  • Players    — the roster localized: ratings compared, leader bars, a scatter
                 map, and a lineup builder that projects a five from player ratings.
  • Schedule   — the full schedule, record vs each class, and any tracked game's
                 complete box score on demand.
  • Charts     — the analytics wall: self-created vs assisted FG% over MOV bars,
                 OREB by quarter, points by quarter, possession, scoring, defense.
  • Insights   — scouting tips built around the Four Factors, league-percentile
                 strengths / weaknesses, and the 2s-vs-3s breakeven question.

All math lives in helpers/team_analytics.py (+ stats / team_ratings /
player_ratings); this page is display + controls only.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import math
from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.settings_utils import get_setting
from helpers.box_score import render_box_score
from helpers.ui import (page_chrome, rgb as _rgb, style_fig as _style,
                        q_label as _q_label, AWAY, CARD_BG, GRID)
from helpers.glossary import render_glossary
import helpers.team_analytics as TA
import helpers.team_ratings as TR
import helpers.stats as S

_cfg, ACCENT = page_chrome()
GOOD = "#3fb950"
BAD = "#e74c3c"
BLUE = "#58a6ff"
PURPLE = "#bc8cff"
GREY = "#8b949e"
CYBER = "#00e5ff"
PINK = "#ff5db1"
RATING_COLS = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]
FF_LABELS = {"eFG": "eFG%", "TOV": "TOV%", "ORB": "ORB%", "FTR": "FT rate"}


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _q_bars(qs, series, yaxis, height=300, mode="group", text_fmt=None,
            zero_line=False):
    """Bar chart over quarters. `series` = [(label, values, color)]."""
    fig = go.Figure()
    for lbl, vals, clr in series:
        kw = dict(name=lbl, x=[_q_label(q) for q in qs], y=vals,
                  marker_color=clr, marker_line_width=0)
        if text_fmt:
            kw["text"] = [text_fmt(v) for v in vals]
            kw["textposition"] = "auto"
        fig.add_trace(go.Bar(**kw))
    fig.update_layout(barmode=mode)
    if zero_line:
        fig.add_hline(y=0, line=dict(color="#30363d"))
    fig.update_yaxes(title=yaxis)
    _style(fig, height)
    return fig


def _q_lines(qs, series, yaxis, height=300):
    """Line chart over quarters. `series` = [(label, values, color)]."""
    fig = go.Figure()
    for lbl, vals, clr in series:
        fig.add_trace(go.Scatter(
            x=[_q_label(q) for q in qs], y=vals, name=lbl,
            mode="lines+markers", line=dict(color=clr, width=3),
            marker=dict(size=7)))
    fig.update_yaxes(title=yaxis)
    _style(fig, height)
    return fig


def _pctf(v, nd=1):
    return "—" if v is None else f"{100 * v:.{nd}f}%"


def _ppp(a, ppf, ftpf=0.0):
    """
    Points per possession for a shot bucket. Shot events carry no free throws and
    a bucket can't be assigned turnovers, so we estimate:
      • possessions ≈ bucket FGA · `ppf`  (ppf = team possessions per FGA), and
      • the team's free-throw points are spread across buckets by shot share
        (`ftpf` = team FTM per FGA).
    PPP = (bucket PTS + ftpf·FGA) / (FGA · ppf) = (PTS/FGA + ftpf) / ppf. With these
    two factors the buckets sum exactly to the team's true PPP (= ORtg / 100).
    """
    if not a["FGA"] or not ppf:
        return None
    return (a["PTS"] / a["FGA"] + ftpf) / ppf


def _shot_row(name, a, ppf=1.0, ftpf=0.0):
    """One formatted row from an agg_shots() dict (TA.agg_shots)."""
    ppp = _ppp(a, ppf, ftpf)
    return {
        "Split": name, "FGA": a["FGA"], "FGM": a["FGM"],
        "FG%": _pctf(a["FG%"]) if a["FGA"] else "—",
        "2PA": a["2PA"], "2P%": _pctf(a["2P%"]) if a["2PA"] else "—",
        "3PA": a["3PA"], "3P%": _pctf(a["3P%"]) if a["3PA"] else "—",
        "eFG%": _pctf(a["eFG"]) if a["FGA"] else "—",
        "PPP": f"{ppp:.2f}" if ppp is not None else "—",
        "SCE": f"{a['SCE']:.3f}" if a["FGA"] else "—",
        "PTS": a["PTS"],
    }


def _trend_line(x, series, titles, key, height=320, yaxis="Value", avg=None):
    """Multi-series line chart over games. `series` = [(label, values, color)]."""
    fig = go.Figure()
    for lbl, vals, clr in series:
        fig.add_trace(go.Scatter(x=x, y=vals, name=lbl, mode="lines+markers",
                                 line=dict(color=clr, width=2.5)))
    if avg is not None:
        fig.add_hline(y=avg, line=dict(color=GREY, dash="dot"),
                      annotation_text="avg")
    fig.update_yaxes(title=yaxis)
    fig.update_xaxes(tickangle=-40)
    _style(fig, height)
    return fig


def _leader_bar(rows, key, label_fn, val_fn, fmt_fn, color=ACCENT, height=220):
    """Horizontal leader bar; rows already ordered best-first."""
    seq = list(reversed(rows))
    names = [label_fn(r) for r in seq]
    vals = [val_fn(r) for r in seq]
    texts = [fmt_fn(v) for v in vals]
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


def _gauge(value, vmin, vmax, label, suffix="", good_high=True, ref=None,
           height=210):
    """A futuristic gauge: value vs a [vmin,vmax] league range with the league
    average (`ref`) drawn as a cyan threshold. Red/amber/green zones key off
    `good_high`. Delta (vs ref) shown when ref is given."""
    span = (vmax - vmin) or 1
    lo, hi = vmin + span / 3, vmin + 2 * span / 3
    if good_high:
        zones = [(vmin, lo, "rgba(231,76,60,.20)"), (lo, hi, "rgba(240,165,0,.16)"),
                 (hi, vmax, "rgba(63,185,80,.22)")]
    else:
        zones = [(vmin, lo, "rgba(63,185,80,.22)"), (lo, hi, "rgba(240,165,0,.16)"),
                 (hi, vmax, "rgba(231,76,60,.20)")]
    mode = "gauge+number+delta" if ref is not None else "gauge+number"
    ind = dict(
        mode=mode, value=value,
        number={"suffix": suffix, "font": {"size": 28, "color": "#f0f6fc"}},
        gauge={
            "axis": {"range": [vmin, vmax], "tickwidth": 1,
                     "tickcolor": "#30363d", "tickfont": {"size": 9}},
            "bar": {"color": ACCENT, "thickness": 0.3},
            "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "steps": [{"range": [a, b], "color": c} for a, b, c in zones]},
        title={"text": label, "font": {"size": 12, "color": "#8b949e"}})
    if ref is not None:
        ind["delta"] = {"reference": ref, "increasing": {"color": GOOD},
                        "decreasing": {"color": BAD},
                        "font": {"size": 12}}
        ind["gauge"]["threshold"] = {"line": {"color": CYBER, "width": 3},
                                     "thickness": 0.85, "value": ref}
    fig = go.Figure(go.Indicator(**ind))
    fig.update_layout(template="plotly_dark", height=height,
                      paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=22, r=22, t=46, b=10),
                      font=dict(color="#c9d1d9"))
    return fig


def _poss_sankey(po, accent, height=360):
    """Possession-outcome Sankey from a TA.possession_outcomes() dict."""
    twos = po["twos"]["make"] + po["twos"]["miss"]
    threes = po["threes"]["make"] + po["threes"]["miss"]
    labels = ["Possessions", "2-pt try", "3-pt try", "Turnover", "Made", "Missed"]
    node_color = [accent, BLUE, PURPLE, BAD, GOOD, "#475569"]
    src, tgt, val, lc = [], [], [], []
    def link(s, t, v, c):
        if v:
            src.append(s); tgt.append(t); val.append(v); lc.append(c)
    link(0, 1, twos, "rgba(88,166,255,.35)")
    link(0, 2, threes, "rgba(188,140,255,.35)")
    link(0, 3, po["tov"], "rgba(231,76,60,.35)")
    link(1, 4, po["twos"]["make"], "rgba(63,185,80,.4)")
    link(1, 5, po["twos"]["miss"], "rgba(71,85,105,.4)")
    link(2, 4, po["threes"]["make"], "rgba(63,185,80,.4)")
    link(2, 5, po["threes"]["miss"], "rgba(71,85,105,.4)")
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, color=node_color, pad=18, thickness=18,
                  line=dict(color="#0d1117", width=1)),
        link=dict(source=src, target=tgt, value=val, color=lc)))
    fig.update_layout(template="plotly_dark", height=height,
                      paper_bgcolor="rgba(0,0,0,0)",
                      font=dict(size=12, color="#c9d1d9"),
                      margin=dict(l=8, r=8, t=10, b=10))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER + TEAM SELECT
# ══════════════════════════════════════════════════════════════════════════════

st.title("Team Analytics")

# Default team comes from Settings. Look up its league so the gender radio
# opens on the right side — otherwise a Boys default is filtered out of the
# (Girls-first) list and the default silently never applies.
default_team = get_setting("default_team", "")
_dt_rows = query("SELECT gender FROM teams WHERE name=?", (default_team,)) \
    if default_team else []
default_gender = _dt_rows[0]["gender"] if _dt_rows else "F"

c1, c2 = st.columns([1, 3])
gender = c1.radio("League", ["F", "M"],
                  index=["F", "M"].index(default_gender),
                  format_func=lambda g: "Girls" if g == "F" else "Boys",
                  horizontal=True)

@st.cache_data(ttl=600, show_spinner=False)
def _list_teams(g):
    return TA.list_teams(gender=g)


teams = _list_teams(gender)
if not teams:
    st.info("No teams in this league yet. Add teams in the Input Hub.")
    st.stop()

@st.cache_data(ttl=600, show_spinner=False)
def _score_ratings(g):
    return TR.score_ratings(gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _tracked_ratings(g):
    return TR.tracked_ratings(gender=g)


scored = _score_ratings(gender)
tracked = _tracked_ratings(gender)


def _rank(t):
    return scored.get(t["id"], {}).get("Rank", 1e9)


order = sorted(teams, key=lambda t: (_rank(t), t["name"]))
default_idx = next((i for i, t in enumerate(order)
                    if t["name"] == default_team), 0)


def _team_label(t):
    r = scored.get(t["id"], {}).get("Rank")
    tag = f"#{r}  " if r else ""
    return f"{tag}{t['name']}  ({t['class']})"


# options are stable team ids (not positional indices) so the selection survives
# a gender switch that changes the team list.
team_by_id = {t["id"]: t for t in order}
order_ids = [t["id"] for t in order]
team_id = c2.selectbox("Team", order_ids, index=default_idx,
                       format_func=lambda tid: _team_label(team_by_id[tid]),
                       key="ta_team")
team = team_by_id[team_id]

@st.cache_data(ttl=600, show_spinner=False)
def _team_bundle(tid, g):
    return TA.team_bundle(tid, gender=g, min_games=1)


@st.cache_data(ttl=600, show_spinner=False)
def _league_ff(g):
    return TA.league_four_factors(gender=g)


bundle = _team_bundle(team_id, gender)
log = bundle["game_log"]
rec = bundle["record"]
players = bundle["players"]
tb, ob = bundle["team_box"], bundle["opp_box"]
ff = bundle["four_factors"]
brk = bundle["breakeven"]
soff, sdef = bundle["scoring_off"], bundle["scoring_def"]
bd = bundle["breakdown"]
summ = bundle["summary"]
sc_score = scored.get(team_id, {})
sc_track = tracked.get(team_id, {})
has_tracked = bool(bundle["tracked_ids"])
# one helper, both rankings: 'overall' (everything / results-only) + 'tracked'
rank_info = TR.team_rank(team_id, scored=scored, tracked=tracked)

if not log:
    st.info(f"**{team['name']}** has no completed games yet. Enter results in "
            "the Input Hub and they'll show up here.")
    st.stop()

# ── futuristic identity band (neon hero + recent-form strip) ────────────────
strk = bundle["streaks"]
_cur = strk["current"]
_cur_txt = (f"{_cur['len']}{_cur['type']}" if _cur["type"] else "—")
_chips = [
    f"<span class='stat-chip'>RANK <b>#{sc_score.get('Rank', '—')}</b> "
    f"<span style='color:#6e7681'>/ {len(scored)}</span></span>",
    f"<span class='stat-chip'>POWER <b>{sc_score.get('Power', '—')}</b></span>",
    f"<span class='stat-chip'>RECORD <b>{rec['wins']}-{rec['losses']}</b> "
    f"({rec['win_pct']*100:.0f}%)</span>",
    f"<span class='stat-chip'>MOV <b style='color:"
    f"{GOOD if rec['MOV'] >= 0 else BAD}'>{rec['MOV']:+.1f}</b></span>",
    f"<span class='stat-chip'>STREAK <b style='color:"
    f"{GOOD if _cur['type'] == 'W' else BAD}'>{_cur_txt}</b></span>",
]
if has_tracked:
    if rank_info["tracked"]:
        _trk = rank_info["tracked"]
        _chips.insert(1, f"<span class='stat-chip'>TRK RANK <b>#{_trk['rank']}</b> "
                      f"<span style='color:#6e7681'>/ {_trk['of']}</span></span>")
    _chips.insert(3, f"<span class='stat-chip'>NET <b style='color:"
                  f"{GOOD if summ.get('NetRtg', 0) >= 0 else BAD}'>"
                  f"{summ.get('NetRtg', 0):+.1f}</b></span>")
_pills = "".join(
    f"<span class='form-pill {'w' if r == 'W' else 'l'}"
    f"{' now' if i == len(strk['form']) - 1 else ''}'>{r}</span>"
    for i, r in enumerate(strk["form"]))
st.markdown(
    f"<div class='lab-hero'>"
    f"<div class='lab-hero-name' style='color:{ACCENT}'>{team['name']}</div>"
    f"<div class='lab-hero-sub'>{team['class']} · "
    f"{'Girls' if gender == 'F' else 'Boys'} · {rec['games']} games"
    + (f" · {len(bundle['tracked_ids'])} tracked" if has_tracked else "")
    + "</div>"
    f"<div class='lab-hero-chips'>{''.join(_chips)}</div>"
    + (f"<div class='form-strip' style='margin-top:13px'>"
       f"<span style='font-size:10px;color:#8b949e;text-transform:uppercase;"
       f"letter-spacing:1.4px;margin-right:2px'>Last {len(strk['form'])}</span>"
       f"{_pills}</div>" if strk["form"] else "")
    + "</div>",
    unsafe_allow_html=True)

if not has_tracked:
    st.warning("No **tracked** games for this team yet — only results-based "
               "ratings, record and schedule are available. Track a game in the "
               "Game Tracker to unlock shooting, possession and four-factor "
               "analytics.")

(tab_over, tab_players, tab_sched, tab_charts, tab_quarters, tab_advanced,
 tab_insights, tab_gloss) = st.tabs(
    ["📊 Overview", "👥 Players", "🗓 Schedule", "📈 Charts", "🕐 Quarters",
     "🚀 Advanced", "🧠 Insights", "📖 Glossary"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_over:
    st.caption("Everything about this team at a glance — power ratings, record, "
               "who carries them, the four factors and how they score.")

    m = st.columns(5)
    m[0].metric("Power", sc_score.get("Power", "—"),
                help="Results-only 0-100 power rating (50 = league avg).")
    m[1].metric("Everything rank", f"#{sc_score.get('Rank', '—')} of {len(scored)}",
                help="Results-only Score ranking across every team in the league.")
    m[2].metric("Record", f"{rec['wins']}-{rec['losses']}")
    m[3].metric("Margin / game", f"{rec['MOV']:+.1f}")
    m[4].metric("Points for / against", f"{rec['PF_pg']:.0f} / {rec['PA_pg']:.0f}")

    if has_tracked:
        m2 = st.columns(5)
        m2[0].metric("Off Rtg", f"{summ.get('ORtg', 0):.1f}",
                     help="Points scored per 100 possessions (tracked games).")
        m2[1].metric("Def Rtg", f"{summ.get('DRtg', 0):.1f}",
                     help="Points allowed per 100 possessions. Lower is better.")
        m2[2].metric("Net Rtg", f"{summ.get('NetRtg', 0):+.1f}")
        m2[3].metric("Pace", f"{summ.get('POSS_pg', 0):.1f}",
                     help="Possessions per game.")
        if rank_info["tracked"]:
            _trk = rank_info["tracked"]
            m2[4].metric("Tracked rank", f"#{_trk['rank']} of {_trk['of']}",
                         help=f"Possession-based power rank over tracked games "
                              f"(sparse sample — directional). Tracked Power "
                              f"{_trk['power']} (50 = league avg).")
        else:
            m2[4].metric("Tracked Power", sc_track.get("Power", "—"),
                         help="Possession-based power over tracked games (sparse "
                              "sample — directional).")

        # ── efficiency rankings vs league ──────────────────────────────────
        if sc_track:
            st.markdown("<div class='lab-hdr'>Efficiency rankings — vs league"
                        "</div>", unsafe_allow_html=True)
            pool_o = [r["ORtg"] for r in tracked.values()]
            pool_d = [r["DRtg"] for r in tracked.values()]
            pool_n = [r["NetRtg"] for r in tracked.values()]
            pool_p = [r["Pace"] for r in tracked.values()]
            metrics = [
                ("Offense", sc_track["ORtg"], pool_o, True),
                ("Defense", sc_track["DRtg"], pool_d, False),
                ("Net rating", sc_track["NetRtg"], pool_n, True),
                ("Pace", sc_track["Pace"], pool_p, True),
            ]
            bars = []
            for lbl, val, pool, hb in metrics:
                pct = TA.percentile(val, pool, higher_better=hb) or 0
                bars.append((lbl, pct, val))
            ef = go.Figure(go.Bar(
                x=[b[1] for b in bars], y=[b[0] for b in bars], orientation="h",
                marker_color=[GOOD if b[1] >= 50 else BAD for b in bars],
                marker_line_width=0,
                text=[f"{b[1]:.0f}th pct ({b[2]:.1f})" for b in bars],
                textposition="auto"))
            ef.update_xaxes(title="League percentile", range=[0, 100])
            _style(ef, 240)
            ef.update_layout(margin=dict(l=4, r=14, t=6, b=30))
            st.plotly_chart(ef, width="stretch", key="ov_effrank")
            st.caption(f"Where this team ranks among the {len(tracked)} tracked "
                       "teams in the league (100 = best).")

    # ── best players ──────────────────────────────────────────────────────────
    st.markdown("<div class='lab-hdr'>Who carries them</div>",
                unsafe_allow_html=True)
    if players:
        rated = [p for p in players if p["OVERALL"] is not None]
        top = sorted(rated, key=lambda p: p["OVERALL"], reverse=True)[:3]
        cards = st.columns(max(len(top), 1))
        _medal = ["#f0a500", "#adb5bd", "#cd7f32"]
        for i, (col, p) in enumerate(zip(cards, top)):
            col.markdown(
                f"<div class='glass-tile'>"
                f"<div class='spotlight-num' style='color:{ACCENT};font-size:42px'>"
                f"{p['OVERALL']:.0f}</div>"
                f"<div class='glass-label' style='color:{_medal[i]}'>OVERALL</div>"
                f"<div class='glass-sub' style='color:#f0f6fc;font-weight:700;"
                f"font-size:13px;margin-top:6px'>#{p['number']} {p['name']}</div>"
                f"<div class='glass-sub'>{p['PPG']:.1f} pts · {p['RPG']:.1f} reb · "
                f"{p['APG']:.1f} ast</div>"
                f"</div>", unsafe_allow_html=True)

        lc, rc = st.columns(2)
        with lc:
            st.markdown("**Scoring leaders** — points / game")
            sl = sorted([p for p in players if p["PPG"] is not None],
                        key=lambda p: p["PPG"], reverse=True)[:7]
            st.plotly_chart(
                _leader_bar(sl, "PPG", lambda r: f"#{r['number']} {r['name']}",
                            lambda r: r["PPG"], lambda v: f"{v:.1f}",
                            color=ACCENT, height=260),
                width="stretch", key="ov_ppg")
        with rc:
            st.markdown("**Top rated** — OVERALL")
            ol = sorted(rated, key=lambda p: p["OVERALL"], reverse=True)[:7]
            st.plotly_chart(
                _leader_bar(ol, "OVERALL", lambda r: f"#{r['number']} {r['name']}",
                            lambda r: r["OVERALL"], lambda v: f"{v:.0f}",
                            color="#56d4dd", height=260),
                width="stretch", key="ov_ovr")

    # ── four-factor snapshot + scoring mix ─────────────────────────────────────
    if has_tracked:
        st.markdown("<div class='lab-hdr'>Four factors & scoring mix</div>",
                    unsafe_allow_html=True)
        fcol, scol = st.columns(2)
        with fcol:
            st.markdown("**Four factors** — offense vs what they allow")
            keys = ["eFG", "TOV", "ORB", "FTR"]
            labels = [FF_LABELS[k] for k in keys]
            offv = [ff["off"][k] * 100 for k in keys]
            defv = [ff["def"][k] * 100 for k in keys]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=labels, y=offv, name="Offense",
                                 marker_color=ACCENT))
            fig.add_trace(go.Bar(x=labels, y=defv, name="Allowed",
                                 marker_color=AWAY))
            fig.update_layout(barmode="group")
            fig.update_yaxes(title="%")
            _style(fig, 320)
            st.plotly_chart(fig, width="stretch", key="ov_ff")
            st.caption("eFG%, ORB% & FT rate: higher offense is better. TOV%: "
                       "lower offense / higher 'allowed' (forced) is better.")
        with scol:
            st.markdown("**Where the points come from**")
            dn = go.Figure(go.Pie(
                labels=["2-pt", "3-pt", "Free throw"],
                values=[soff["pts2"], soff["pts3"], soff["ptsft"]],
                hole=0.55, sort=False,
                marker=dict(colors=[ACCENT, BLUE, GREY]),
                textinfo="label+percent"))
            dn.update_layout(
                template="plotly_dark", height=320,
                paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                margin=dict(l=10, r=10, t=30, b=10),
                annotations=[dict(text=f"{soff['pct_paint']*100:.0f}%<br>"
                                       "<span style='font-size:10px'>in paint</span>",
                                  x=0.5, y=0.5, font=dict(size=15),
                                  showarrow=False)])
            st.plotly_chart(dn, width="stretch", key="ov_src")

    # ── margin trend ───────────────────────────────────────────────────────────
    st.markdown("<div class='lab-hdr'>Margin trend</div>",
                unsafe_allow_html=True)
    gx = [f"{g['date'][5:]} {g['site']} {g['opp'][:10]}" for g in log]
    mv = [g["margin"] for g in log]
    colors = [GOOD if g["won"] else BAD for g in log]
    mfig = go.Figure(go.Bar(
        x=gx, y=mv, marker_color=colors, marker_line_width=0,
        text=[f"{g['pf']}-{g['pa']}" for g in log], textposition="outside",
        textfont=dict(size=9),
        hovertemplate="%{x}<br>Margin %{y:+d}<extra></extra>"))
    mfig.add_hline(y=0, line=dict(color="#30363d"))
    mfig.update_yaxes(title="Margin")
    mfig.update_xaxes(tickangle=-45)
    _style(mfig, 360)
    st.plotly_chart(mfig, width="stretch", key="ov_margin")
    st.caption("Green = win, red = loss. Final score labelled on each bar.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — PLAYERS
# ══════════════════════════════════════════════════════════════════════════════
with tab_players:
    if not players:
        st.info("No eligible players for this team yet — track a game in the "
                "Game Tracker.")
    else:
        st.caption("The roster localized: ratings side-by-side, per-game "
                   "production, an offense/defense map, and a lineup builder "
                   "that projects a five from the player ratings.")

        rdf = pd.DataFrame([{
            "#": p["number"], "Player": p["name"], "GP": p["GP"],
            "OVERALL": p["OVERALL"], "OFFENSE": p["OFFENSE"],
            "DEFENSE": p["DEFENSE"], "PLAYMAKING": p["PLAYMAKING"],
            "REBOUNDING": p["REBOUNDING"],
            "PPG": p["PPG"], "RPG": p["RPG"], "APG": p["APG"],
            "TS%": p["TS%"], "USG%": p["USG%"], "+/-": p["+/-"],
        } for p in players])
        st.dataframe(
            rdf, hide_index=True, width="stretch",
            height=min(560, 60 + 35 * len(rdf)),
            column_config={c: st.column_config.ProgressColumn(
                c, format="%.0f", min_value=0, max_value=100)
                for c in RATING_COLS})

        st.markdown("<div class='lab-hdr'>Ratings compared</div>",
                    unsafe_allow_html=True)
        rated = [p for p in players if p["OVERALL"] is not None]
        cat = st.selectbox("Rating", RATING_COLS, key="pl_cat")
        srt = sorted([p for p in rated if p[cat] is not None],
                     key=lambda p: p[cat], reverse=True)
        if srt:
            cfig = go.Figure(go.Bar(
                x=[f"#{p['number']} {p['name']}" for p in srt],
                y=[p[cat] for p in srt], marker_color=ACCENT,
                marker_line_width=0,
                text=[f"{p[cat]:.0f}" for p in srt], textposition="auto"))
            cfig.add_hline(y=50, line=dict(color=GREY, dash="dot"),
                           annotation_text="pool avg")
            cfig.update_yaxes(title=cat, range=[0, 100])
            cfig.update_xaxes(tickangle=-35)
            _style(cfig, 340)
            st.plotly_chart(cfig, width="stretch", key="pl_cat_bar")

        lc, rc = st.columns(2)
        with lc:
            st.markdown("**Per-game production**")
            pg = sorted(players, key=lambda p: p["PPG"] or 0, reverse=True)[:8]
            x = [f"#{p['number']}" for p in pg]
            pgf = go.Figure()
            pgf.add_trace(go.Bar(x=x, y=[p["PPG"] for p in pg], name="Pts",
                                 marker_color=ACCENT))
            pgf.add_trace(go.Bar(x=x, y=[p["RPG"] for p in pg], name="Reb",
                                 marker_color=GOOD))
            pgf.add_trace(go.Bar(x=x, y=[p["APG"] for p in pg], name="Ast",
                                 marker_color=BLUE))
            pgf.update_layout(barmode="group")
            pgf.update_yaxes(title="Per game")
            _style(pgf, 340)
            st.plotly_chart(pgf, width="stretch", key="pl_pg")
        with rc:
            st.markdown("**Offense vs defense map**")
            mp = [p for p in players if p["OFFENSE"] is not None
                  and p["DEFENSE"] is not None]
            if mp:
                sca = go.Figure(go.Scatter(
                    x=[p["OFFENSE"] for p in mp], y=[p["DEFENSE"] for p in mp],
                    mode="markers+text",
                    text=[f"#{p['number']}" for p in mp],
                    textposition="top center", textfont=dict(size=9),
                    marker=dict(size=[max(8, (p["PPG"] or 0) * 1.3) for p in mp],
                                color=[p["OVERALL"] or 50 for p in mp],
                                colorscale="Viridis", showscale=True,
                                colorbar=dict(title="OVR"),
                                line=dict(width=1, color="#30363d")),
                    hovertext=[p["name"] for p in mp],
                    hovertemplate="%{hovertext}<br>OFF %{x:.0f} · DEF %{y:.0f}"
                                  "<extra></extra>"))
                sca.add_vline(x=50, line=dict(color="#30363d", dash="dot"))
                sca.add_hline(y=50, line=dict(color="#30363d", dash="dot"))
                sca.update_xaxes(title="Offense →")
                sca.update_yaxes(title="Defense →")
                _style(sca, 340)
                st.plotly_chart(sca, width="stretch", key="pl_map")
                st.caption("Bubble size = points/game. Top-right = two-way.")

        st.markdown("<div class='lab-hdr'>Lineup projection</div>",
                    unsafe_allow_html=True)
        st.caption("Pick five players; the projected ratings average their "
                   "individual 0-100 ratings (50 = league average). Projected "
                   "points/game sums their scoring.")
        labels = {}
        for p in players:
            base = f"#{p['number']} {p['name']}"
            labels[p["_pid"]] = (f"{base} (OVR {p['OVERALL']:.0f})"
                                 if p["OVERALL"] is not None else base)
        default5 = [p["_pid"] for p in
                    sorted(players, key=lambda p: p["MPG"] or 0, reverse=True)[:5]]
        chosen = st.multiselect(
            "Lineup", list(labels), default=default5,
            format_func=lambda pid: labels[pid], max_selections=5,
            key="pl_lineup")
        if chosen:
            proj = TA.lineup_projection(players, chosen)
            pm = st.columns(6)
            pm[0].metric("Proj OVERALL",
                         f"{proj['OVERALL']:.0f}" if proj["OVERALL"] else "—")
            for col, key in zip(pm[1:5], ["OFFENSE", "DEFENSE", "PLAYMAKING",
                                          "REBOUNDING"]):
                col.metric(key.title(),
                           f"{proj[key]:.0f}" if proj[key] is not None else "—")
            pm[5].metric("Proj PPG", f"{proj['PPG']:.1f}")
            if proj["OVERALL"] is not None:
                ar, ag, ab = _rgb(ACCENT)
                lr = go.Figure()
                lr.add_trace(go.Scatterpolar(
                    r=[50] * (len(RATING_COLS) + 1),
                    theta=RATING_COLS + [RATING_COLS[0]],
                    line=dict(color=GREY, width=1, dash="dot"),
                    name="League avg", hoverinfo="skip"))
                lr.add_trace(go.Scatterpolar(
                    r=[proj[c] or 0 for c in RATING_COLS] + [proj[RATING_COLS[0]] or 0],
                    theta=RATING_COLS + [RATING_COLS[0]], fill="toself",
                    name="Lineup", line=dict(color=ACCENT, width=2),
                    fillcolor=f"rgba({ar},{ag},{ab},0.22)"))
                lr.update_layout(
                    template="plotly_dark", height=360,
                    paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                    polar=dict(bgcolor=CARD_BG,
                               radialaxis=dict(range=[0, 100], gridcolor=GRID,
                                               tickfont=dict(size=9)),
                               angularaxis=dict(gridcolor=GRID)),
                    margin=dict(l=50, r=50, t=30, b=30))
                st.plotly_chart(lr, width="stretch",
                                key="pl_lineup_radar")

        # ── category leaders ────────────────────────────────────────────────
        st.markdown("<div class='lab-hdr'>Category leaders</div>",
                    unsafe_allow_html=True)
        LEAD = [("PPG", "Points/g", "f1"), ("RPG", "Rebounds/g", "f1"),
                ("APG", "Assists/g", "f1"), ("STOCKS/G", "Stocks/g", "f1"),
                ("TS%", "True shooting", "pct"), ("USG%", "Usage", "pct")]
        lcols = st.columns(3)
        for i, (key, lbl, fmt) in enumerate(LEAD):
            pool = [p for p in players if p.get(key) is not None]
            if not pool:
                continue
            best = max(pool, key=lambda p: p[key])
            val = _pctf(best[key] / 100) if fmt == "pct" else f"{best[key]:.1f}"
            with lcols[i % 3]:
                st.metric(lbl, val, help=f"#{best['number']} {best['name']}")
                st.caption(f"#{best['number']} {best['name']}")

        # ── volume vs efficiency + shot selection ──────────────────────────
        st.markdown("<div class='lab-hdr'>Volume vs efficiency</div>",
                    unsafe_allow_html=True)
        ve = [p for p in players if p["USG%"] is not None and p["TS%"] is not None]
        if ve:
            vfig = go.Figure(go.Scatter(
                x=[p["USG%"] for p in ve], y=[p["TS%"] for p in ve],
                mode="markers+text", text=[f"#{p['number']}" for p in ve],
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=[max(9, (p["PPG"] or 0) * 1.4) for p in ve],
                            color=[p["OVERALL"] or 50 for p in ve],
                            colorscale="Viridis", showscale=True,
                            colorbar=dict(title="OVR"),
                            line=dict(width=1, color="#30363d")),
                hovertext=[p["name"] for p in ve],
                hovertemplate="%{hovertext}<br>USG %{x:.0f}% · TS %{y:.0f}%"
                              "<extra></extra>"))
            vfig.update_xaxes(title="Usage % →")
            vfig.update_yaxes(title="True shooting % →")
            _style(vfig, 360)
            st.plotly_chart(vfig, width="stretch", key="pl_ve")
            st.caption("Bubble size = points/game. Top-right = high-volume and "
                       "efficient — the offensive engines.")

        # ── shooting splits table ───────────────────────────────────────────
        st.markdown("<div class='lab-hdr'>Shooting splits</div>",
                    unsafe_allow_html=True)
        sdf2 = pd.DataFrame([{
            "#": p["number"], "Player": p["name"],
            "FG%": p["FG%"], "2P%": p["2P%"], "3P%": p["3P%"], "FT%": p["FT%"],
            "eFG%": p["eFG%"], "TS%": p["TS%"], "3PR": p["3PR"],
            "Paint%": p["Paint%"], "PPS": p["PPS"], "ShotRtg": p["ShotRating"],
        } for p in players])
        st.dataframe(sdf2, hide_index=True, width="stretch",
                     height=min(480, 60 + 35 * len(sdf2)))

        # ── advanced metrics + Oliver ratings ───────────────────────────────
        st.markdown("<div class='lab-hdr'>Advanced & impact metrics</div>",
                    unsafe_allow_html=True)
        oliver = TA.player_oliver_ratings(team_id, bundle["tracked_ids"])
        adf = pd.DataFrame([{
            "#": p["number"], "Player": p["name"], "GS/G": p["GS/G"],
            "EFF": p["EFF"], "FIC": p["FIC"], "PRF": p["PRF"],
            "USG%": p["USG%"], "TOV%": p["TOV%"], "PPP": p["PPP"],
            "+/-": p["+/-"],
            "ORtg": round(oliver.get(p["_pid"], {}).get("ORtg") or 0) or None,
            "DRtg": round(oliver.get(p["_pid"], {}).get("DRtg") or 0) or None,
        } for p in players])
        st.dataframe(adf, hide_index=True, width="stretch",
                     height=min(480, 60 + 35 * len(adf)))
        st.caption("ORtg/DRtg = Dean Oliver individual ratings (per 100 poss; "
                   "directional on a 15-game sample). +/- and impact metrics are "
                   "totals over tracked games.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════
with tab_sched:
    st.caption("The full schedule with results, the record against every class, "
               "and any tracked game's complete box score on demand.")

    rvc = bundle["record_vs_class"]
    cls_order = sorted(rvc, key=lambda c: TR._CLASS_RANK.get(c, 99))
    mcols = st.columns(max(len(cls_order) + 1, 2))
    mcols[0].metric("Overall", f"{rec['wins']}-{rec['losses']}")
    for col, cls in zip(mcols[1:], cls_order):
        w, l = rvc[cls]
        col.metric(f"vs {cls}", f"{w}-{l}")

    if rvc:
        st.markdown("<div class='lab-hdr'>Record vs each class</div>",
                    unsafe_allow_html=True)
        rcfig = go.Figure()
        rcfig.add_trace(go.Bar(x=cls_order, y=[rvc[c][0] for c in cls_order],
                               name="Wins", marker_color=GOOD))
        rcfig.add_trace(go.Bar(x=cls_order, y=[rvc[c][1] for c in cls_order],
                               name="Losses", marker_color=BAD))
        rcfig.update_layout(barmode="stack")
        rcfig.update_yaxes(title="Games")
        rcfig.update_xaxes(title="Opponent class")
        _style(rcfig, 300)
        st.plotly_chart(rcfig, width="stretch", key="sc_rvc")

    st.markdown("<div class='lab-hdr'>Schedule</div>", unsafe_allow_html=True)
    sdf = pd.DataFrame([{
        "Date": g["date"], "": g["site"], "Opponent": g["opp"],
        "Cls": g["opp_class"],
        "Result": ("W" if g["won"] else "L") + f" {g['pf']}-{g['pa']}",
        "Margin": f"{g['margin']:+d}",
        "Tracked": "✓" if g["tracked"] else "",
    } for g in log])
    st.dataframe(sdf, hide_index=True, width="stretch",
                 height=min(640, 60 + 35 * len(sdf)))

    st.markdown("<div class='lab-hdr'>Box score</div>",
                unsafe_allow_html=True)
    tracked_games = [g for g in log if g["tracked"]]
    if not tracked_games:
        st.info("No tracked games to open a box score for yet.")
    else:
        glabels = [f"{g['date']}  {g['site']} {g['opp']}  "
                   f"({'W' if g['won'] else 'L'} {g['pf']}-{g['pa']})"
                   for g in tracked_games]
        gi = st.selectbox("Pick a tracked game", range(len(tracked_games)),
                          format_func=lambda i: glabels[i], key="sc_box")
        render_box_score(tracked_games[gi]["game_id"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — CHARTS  (5 sub-tabs: Scoring · Shooting · Rebounding · Defense · Trends)
# ══════════════════════════════════════════════════════════════════════════════
with tab_charts:
    if not has_tracked:
        st.info("No tracked games yet — charts need play-by-play data from the "
                "Game Tracker.")
    else:
        st.caption("The analytics wall — built from tracked-game events. Small "
                   "samples are directional.")
        quarter = bd["quarter"]
        qs = sorted(quarter)
        cbg = bd["creation_by_game"]
        ng = max(len(bundle["tracked_ids"]), 1)
        poss = S.estimate_possessions(tb)
        opp_poss = S.estimate_possessions(ob)
        # possessions-per-FGA and FT-points-per-FGA: turn a bucket's shot points
        # into points per possession that sum to the team's true PPP (= ORtg/100).
        ppf = poss / max(tb["FGA"], 1)
        ftpf = tb["FTM"] / max(tb["FGA"], 1)
        zones = bundle["zones"]
        guarded = bundle["guarded"]
        crb = bundle["creation_breakdown"]
        plen = bundle["poss_length"]
        trend = bundle["trend"]
        tx = [f"{e['date'][5:]} {e['opp'][:7]}" for e in trend]

        ch_sc, ch_sh, ch_rb, ch_df, ch_tr = st.tabs(
            ["🏀 Scoring", "🎯 Shooting", "🪟 Rebounding", "🛡 Defense",
             "📉 Trends"])

        # ───────────────────────────────────────────── SCORING ──────────────
        with ch_sc:
            pmcols = st.columns(4)
            pmcols[0].metric("Pace", f"{summ.get('POSS_pg', 0):.1f}",
                             help="Possessions per game.")
            pmcols[1].metric("Pts / poss", f"{S._safe(tb['PTS'], poss):.2f}")
            pmcols[2].metric("Pts / game", f"{rec['PF_pg']:.1f}")
            pmcols[3].metric("Paint pts %", _pctf(soff["pct_paint"]))

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Points by source**")
                dn = go.Figure(go.Pie(
                    labels=["2-pt", "3-pt", "Free throw"],
                    values=[soff["pts2"], soff["pts3"], soff["ptsft"]],
                    hole=0.55, sort=False,
                    marker=dict(colors=[ACCENT, BLUE, GREY]),
                    textinfo="label+percent"))
                dn.update_layout(template="plotly_dark", height=300,
                                 paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                                 margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(dn, width="stretch", key="sc_src")
            with c2:
                st.markdown("**Scoring by quarter** — points / game")
                if qs:
                    pf = [quarter[q]["pf"] / ng for q in qs]
                    pa = [quarter[q]["pa"] / ng for q in qs]
                    qf = go.Figure()
                    qf.add_trace(go.Bar(x=[_q_label(q) for q in qs], y=pf,
                                        name="Scored", marker_color=ACCENT))
                    qf.add_trace(go.Bar(x=[_q_label(q) for q in qs], y=pa,
                                        name="Allowed", marker_color=AWAY))
                    qf.update_layout(barmode="group")
                    qf.update_yaxes(title="Points / game")
                    _style(qf, 300)
                    st.plotly_chart(qf, width="stretch", key="sc_qpts")

            if qs:
                st.markdown("<div class='lab-hdr'>Net points by quarter & half"
                            "</div>", unsafe_allow_html=True)
                c3, c4 = st.columns(2)
                with c3:
                    pf = [quarter[q]["pf"] / ng for q in qs]
                    pa = [quarter[q]["pa"] / ng for q in qs]
                    net = [pf[i] - pa[i] for i in range(len(qs))]
                    nf = go.Figure(go.Bar(
                        x=[_q_label(q) for q in qs], y=net,
                        marker_color=[GOOD if n >= 0 else BAD for n in net],
                        text=[f"{n:+.1f}" for n in net], textposition="auto"))
                    nf.add_hline(y=0, line=dict(color="#30363d"))
                    nf.update_yaxes(title="Net points / game")
                    _style(nf, 300)
                    st.plotly_chart(nf, width="stretch", key="sc_qnet")
                with c4:
                    h1_for = sum(quarter[q]["pf"] for q in qs if q <= 2) / ng
                    h2_for = sum(quarter[q]["pf"] for q in qs if 3 <= q <= 4) / ng
                    h1_ag = sum(quarter[q]["pa"] for q in qs if q <= 2) / ng
                    h2_ag = sum(quarter[q]["pa"] for q in qs if 3 <= q <= 4) / ng
                    hf = go.Figure()
                    hf.add_trace(go.Bar(x=["1st half", "2nd half"],
                                        y=[h1_for, h2_for], name="Scored",
                                        marker_color=ACCENT))
                    hf.add_trace(go.Bar(x=["1st half", "2nd half"],
                                        y=[h1_ag, h2_ag], name="Allowed",
                                        marker_color=AWAY))
                    hf.update_layout(barmode="group")
                    hf.update_yaxes(title="Points / game")
                    _style(hf, 300)
                    st.plotly_chart(hf, width="stretch", key="sc_half")

                # Q4 clutch tiles
                if 4 in quarter:
                    q4 = quarter[4]
                    q4f, q4a = q4["pf"] / ng, q4["pa"] / ng
                    cm = st.columns(4)
                    cm[0].metric("Q4 PPG", f"{q4f:.1f}")
                    cm[1].metric("Q4 PA/G", f"{q4a:.1f}")
                    cm[2].metric("Q4 margin", f"{q4f - q4a:+.1f}")
                    cm[3].metric("Q4 FG%", _pctf(S._safe(q4["fgm_for"],
                                                         q4["fga_for"])))

            # possession-length splits
            st.markdown("<div class='lab-hdr'>Scoring by possession length"
                        "</div>", unsafe_allow_html=True)
            if plen:
                pl_df = pd.DataFrame([{
                    "Length": r["label"], "FGA": r["FGA"], "FG%": _pctf(r["FG%"]),
                    "2P%": _pctf(r["2P%"]) if r["2PA"] else "—",
                    "3P%": _pctf(r["3P%"]) if r["3PA"] else "—",
                    "PPP": (f"{_ppp(r, ppf, ftpf):.2f}"
                            if _ppp(r, ppf, ftpf) is not None else "—"),
                    "SCE": f"{r['SCE']:.3f}",
                    "AST%": _pctf(r["AST%"]),
                } for r in plen])
                lc, rc = st.columns([1, 1])
                with lc:
                    st.dataframe(pl_df, hide_index=True, width="stretch")
                with rc:
                    timed = [r for r in plen if r["label"] != "Untimed"]
                    ppps = [_ppp(r, ppf, ftpf) or 0 for r in timed]
                    pf = go.Figure(go.Bar(
                        x=[r["label"] for r in timed], y=ppps,
                        marker_color=ACCENT, marker_line_width=0,
                        text=[f"{v:.2f}" for v in ppps], textposition="auto"))
                    pf.update_yaxes(title="Points per possession")
                    _style(pf, 260)
                    st.plotly_chart(pf, width="stretch", key="sc_plen")
                st.caption("Possession length = seconds elapsed on the shot's "
                           "possession. ~16% of events are untimed (shown "
                           "separately). PPP estimated from the team's "
                           "possessions-per-FGA rate. Transition looks are usually "
                           "the most efficient.")

        # ───────────────────────────────────────────── SHOOTING ─────────────
        with ch_sh:
            sm = st.columns(6)
            sm[0].metric("eFG%", _pctf(S.efg(tb)))
            sm[1].metric("TS%", _pctf(S.ts(tb)))
            sm[2].metric("FG%", _pctf(S.fg_pct(tb)))
            sm[3].metric("3P%", _pctf(S.fg3_pct(tb)))
            sm[4].metric("Paint FG%", _pctf(S.paint_fg_pct(tb)))
            sm[5].metric("SCE", f"{S.shot_efficiency(tb):.3f}",
                         help="Scoring efficiency = (PTS − FT) / (2PA·2 + 3PA·3) "
                              "— FG points as a share of the max possible.")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Shot diet** — attempts by type")
                paint2 = tb["paint_FGA"]
                mid2 = tb["2PA"] - paint2
                sd = go.Figure(go.Bar(
                    x=[paint2, mid2, tb["3PA"]],
                    y=["Paint 2s", "Other 2s", "3s"], orientation="h",
                    marker_color=[ACCENT, "#d29922", BLUE], marker_line_width=0,
                    text=[paint2, mid2, tb["3PA"]], textposition="auto"))
                sd.update_xaxes(title="Attempts")
                _style(sd, 280)
                sd.update_layout(margin=dict(l=4, r=14, t=10, b=30))
                st.plotly_chart(sd, width="stretch", key="sh_diet")
            with c2:
                st.markdown("**Make rate by type**")
                splits = [("FG%", S.fg_pct(tb)), ("2P%", S.fg2_pct(tb)),
                          ("3P%", S.fg3_pct(tb)), ("Paint%", S.paint_fg_pct(tb)),
                          ("FT%", S.ft_pct(tb)), ("eFG%", S.efg(tb)),
                          ("TS%", S.ts(tb))]
                sf = go.Figure(go.Bar(
                    x=[s[0] for s in splits], y=[s[1] * 100 for s in splits],
                    marker_color=ACCENT, marker_line_width=0,
                    text=[f"{s[1]*100:.0f}" for s in splits], textposition="auto"))
                sf.update_yaxes(title="%")
                _style(sf, 280)
                st.plotly_chart(sf, width="stretch", key="sh_splits")

            # zone analysis
            st.markdown("<div class='lab-hdr'>Zone analysis — where they shoot"
                        "</div>", unsafe_allow_html=True)
            zo = zones["off"]
            zc1, zc2 = st.columns(2)
            with zc1:
                zfa = go.Figure(go.Bar(
                    x=[TA.ZONE_LABELS[z] for z in TA.ZONES],
                    y=[zo[z]["FGA"] for z in TA.ZONES],
                    marker_color=ACCENT, marker_line_width=0,
                    text=[zo[z]["FGA"] for z in TA.ZONES], textposition="auto"))
                zfa.update_yaxes(title="Attempts")
                zfa.update_xaxes(tickangle=-25)
                _style(zfa, 300)
                zfa.update_layout(title=dict(text="Attempts by zone",
                                             font=dict(size=13)))
                st.plotly_chart(zfa, width="stretch", key="sh_zfa")
            with zc2:
                zfg = go.Figure(go.Bar(
                    x=[TA.ZONE_LABELS[z] for z in TA.ZONES],
                    y=[zo[z]["FG%"] * 100 for z in TA.ZONES],
                    marker_color=BLUE, marker_line_width=0,
                    text=[_pctf(zo[z]["FG%"]) if zo[z]["FGA"] else "—"
                          for z in TA.ZONES], textposition="auto"))
                zfg.update_yaxes(title="FG%")
                zfg.update_xaxes(tickangle=-25)
                _style(zfg, 300)
                zfg.update_layout(title=dict(text="FG% by zone",
                                             font=dict(size=13)))
                st.plotly_chart(zfg, width="stretch", key="sh_zfg")

            # ── hot zone map (court layout, colored by FG%) ─────────────────
            zxfg = bundle["zone_xfg"]
            ZPOS = {"LC": (-21, 4), "LW": (-15, 21), "C": (0, 8),
                    "RW": (15, 21), "RC": (21, 4)}
            maxfga = max((zo[z]["FGA"] for z in TA.ZONES), default=0) or 1
            hz1, hz2 = st.columns([3, 2])
            with hz1:
                st.markdown("**Hot zone map** — size = volume, color = FG%")
                hz = go.Figure()
                # half-court outline + paint
                hz.add_shape(type="rect", x0=-25, y0=0, x1=25, y1=31,
                             line=dict(color="#30363d", width=1))
                hz.add_shape(type="rect", x0=-8, y0=0, x1=8, y1=19,
                             line=dict(color="#30363d", width=1))
                hz.add_shape(type="circle", x0=-6, y0=13, x1=6, y1=25,
                             line=dict(color="#30363d", width=1))
                xs = [ZPOS[z][0] for z in TA.ZONES]
                ys = [ZPOS[z][1] for z in TA.ZONES]
                fgp = [zo[z]["FG%"] * 100 for z in TA.ZONES]
                sizes = [22 + (zo[z]["FGA"] / maxfga) * 60 for z in TA.ZONES]
                short = {"LC": "LCnr", "LW": "LWing", "C": "Paint",
                         "RW": "RWing", "RC": "RCnr"}
                hz.add_trace(go.Scatter(
                    x=xs, y=ys, mode="markers+text",
                    marker=dict(size=sizes, color=fgp, colorscale="RdYlGn",
                                cmin=25, cmax=60, showscale=True,
                                colorbar=dict(title="FG%"),
                                line=dict(color="#0d1117", width=2)),
                    text=[f"{short[z]}<br>{zo[z]['FG%']*100:.0f}%"
                          for z in TA.ZONES],
                    textfont=dict(size=10, color="#0d1117"),
                    textposition="middle center",
                    hovertext=[TA.ZONE_LABELS[z] for z in TA.ZONES],
                    hovertemplate="%{hovertext}<br>FG%: %{marker.color:.0f}%"
                                  "<extra></extra>"))
                hz.update_xaxes(visible=False, range=[-27, 27])
                hz.update_yaxes(visible=False, range=[-2, 33])
                _style(hz, 420)
                hz.update_layout(plot_bgcolor="rgba(0,0,0,0)",
                                 margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(hz, width="stretch", key="sh_hotzone")
            with hz2:
                st.markdown("**Actual vs expected FG% by zone**")
                az = go.Figure()
                az.add_trace(go.Bar(
                    name="Actual FG%", x=[short_z for short_z in
                                          [TA.ZONE_LABELS[z].split("/")[0].strip()
                                           for z in TA.ZONES]],
                    y=[zo[z]["FG%"] * 100 for z in TA.ZONES],
                    marker_color=ACCENT))
                az.add_trace(go.Bar(
                    name="xFG%", x=[TA.ZONE_LABELS[z].split("/")[0].strip()
                                    for z in TA.ZONES],
                    y=[zxfg[z]["xFG%"] * 100 for z in TA.ZONES],
                    marker_color=BLUE, opacity=0.7))
                az.update_layout(barmode="group")
                az.update_yaxes(title="%")
                az.update_xaxes(tickangle=-25)
                _style(az, 420)
                st.plotly_chart(az, width="stretch", key="sh_zxfg")
            st.caption("xFG% = expected FG% from the league-wide make-rate of each "
                       "shot's (zone · creation · contest) type. Actual above xFG% "
                       "= the team finishes that zone better than the looks imply.")

            ztbl = []
            for z in TA.ZONES:
                row = _shot_row(TA.ZONE_LABELS[z], zo[z], ppf, ftpf)
                row["xFG%"] = _pctf(zxfg[z]["xFG%"]) if zo[z]["FGA"] else "—"
                ztbl.append(row)
            st.dataframe(pd.DataFrame(ztbl), hide_index=True,
                         width="stretch")

            # guarded vs unguarded
            st.markdown("<div class='lab-hdr'>Guarded vs unguarded</div>",
                        unsafe_allow_html=True)
            g, u = guarded["guarded"], guarded["unguarded"]
            st.dataframe(pd.DataFrame([
                _shot_row("Guarded", g, ppf, ftpf),
                _shot_row("Unguarded", u, ppf, ftpf),
                _shot_row("All", guarded["all"], ppf, ftpf)]),
                hide_index=True, width="stretch")
            gc1, gc2 = st.columns([2, 1])
            with gc1:
                gf = go.Figure()
                for lbl, key in [("FG%", "FG%"), ("2P%", "2P%"),
                                 ("3P%", "3P%"), ("eFG%", "eFG")]:
                    gf.add_trace(go.Bar(
                        name=lbl, x=["Guarded", "Unguarded"],
                        y=[g[key] * 100, u[key] * 100]))
                gf.update_layout(barmode="group")
                gf.update_yaxes(title="%")
                _style(gf, 300)
                st.plotly_chart(gf, width="stretch", key="sh_guard")
            with gc2:
                st.metric("Contested rate", _pctf(guarded["guard_share"]))
                st.metric("Open eFG% edge",
                          f"{(u['eFG'] - g['eFG']) * 100:+.1f}pp")
                st.caption("How much better they shoot when nobody is tagged as "
                           "contesting.")

            # shot-creation breakdown
            st.markdown("<div class='lab-hdr'>Shot-creation breakdown</div>",
                        unsafe_allow_html=True)
            cmap = {"both": "Pass + screen", "pass": "Off a pass",
                    "created": "Off a screen", "self": "Self-created"}
            order = ["both", "pass", "created", "self"]
            st.dataframe(pd.DataFrame(
                [_shot_row(cmap[k], crb[k], ppf, ftpf) for k in order]
                + [_shot_row("TOTAL", crb["total"], ppf, ftpf)]),
                hide_index=True, width="stretch")
            cc1, cc2 = st.columns(2)
            with cc1:
                cf = go.Figure(go.Bar(
                    x=[cmap[k] for k in order], y=[crb[k]["FGA"] for k in order],
                    marker_color=[BLUE, GOOD, ACCENT, AWAY], marker_line_width=0,
                    text=[crb[k]["FGA"] for k in order], textposition="auto"))
                cf.update_yaxes(title="Attempts")
                cf.update_xaxes(tickangle=-20)
                _style(cf, 300)
                cf.update_layout(title=dict(text="Volume by creation type",
                                            font=dict(size=13)))
                st.plotly_chart(cf, width="stretch", key="sh_crb_v")
            with cc2:
                ce = go.Figure(go.Bar(
                    x=[cmap[k] for k in order],
                    y=[crb[k]["eFG"] * 100 for k in order],
                    marker_color=[BLUE, GOOD, ACCENT, AWAY], marker_line_width=0,
                    text=[_pctf(crb[k]["eFG"]) if crb[k]["FGA"] else "—"
                          for k in order], textposition="auto"))
                ce.update_yaxes(title="eFG%")
                ce.update_xaxes(tickangle=-20)
                _style(ce, 300)
                ce.update_layout(title=dict(text="Efficiency by creation type",
                                            font=dict(size=13)))
                st.plotly_chart(ce, width="stretch", key="sh_crb_e")

            # PPP & SCE by shot-creation type
            ppp_by = [_ppp(crb[k], ppf, ftpf) for k in order]
            pse = go.Figure()
            pse.add_trace(go.Bar(
                name="PPP (pts/poss)", x=[cmap[k] for k in order],
                y=[v or 0 for v in ppp_by], marker_color=ACCENT,
                text=[f"{v:.2f}" if v is not None else "—" for v in ppp_by],
                textposition="auto"))
            pse.add_trace(go.Bar(
                name="SCE", x=[cmap[k] for k in order],
                y=[crb[k]["SCE"] for k in order], marker_color=BLUE, opacity=0.8,
                text=[f"{crb[k]['SCE']:.3f}" if crb[k]["FGA"] else "—"
                      for k in order], textposition="auto"))
            pse.update_layout(barmode="group")
            pse.update_yaxes(title="Efficiency")
            pse.update_xaxes(tickangle=-20)
            _style(pse, 320)
            pse.update_layout(title=dict(text="PPP & SCE by creation type",
                                         font=dict(size=13)))
            st.plotly_chart(pse, width="stretch", key="sh_crb_pse")
            st.caption("PPP = points per possession (estimated from the team's "
                       "possessions-per-FGA rate) · SCE = (PTS−FT) / max FG points "
                       "possible. Higher = more efficient looks from that creation "
                       "type.")

            # headline: self-created vs assisted FG% over MOV bars
            st.markdown("<div class='lab-hdr'>Self-created vs assisted FG% — "
                        "per game</div>", unsafe_allow_html=True)
            glog_tracked = [g for g in log if g["tracked"] and g["game_id"] in cbg]
            if glog_tracked:
                gx = [f"{g['date'][5:]} {g['opp'][:8]}" for g in glog_tracked]
                self_pct = [cbg[g["game_id"]]["self_pct"] * 100
                            for g in glog_tracked]
                asst_pct = [cbg[g["game_id"]]["asst_pct"] * 100
                            for g in glog_tracked]
                mov = [g["margin"] for g in glog_tracked]
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=gx, y=mov, name="Margin", yaxis="y2",
                    marker_color=[GOOD if m >= 0 else BAD for m in mov],
                    opacity=0.28, marker_line_width=0,
                    hovertemplate="Margin %{y:+d}<extra></extra>"))
                fig.add_trace(go.Scatter(
                    x=gx, y=self_pct, name="Self-created FG%",
                    mode="lines+markers", line=dict(color=ACCENT, width=3)))
                fig.add_trace(go.Scatter(
                    x=gx, y=asst_pct, name="Assisted FG%", mode="lines+markers",
                    line=dict(color=BLUE, width=3)))
                fig.update_layout(
                    yaxis=dict(title="FG%"),
                    yaxis2=dict(title="Margin", overlaying="y", side="right",
                                showgrid=False, zerolinecolor="#30363d"))
                fig.update_xaxes(tickangle=-40)
                _style(fig, 400)
                st.plotly_chart(fig, width="stretch", key="sh_creation")
                ov_self = bd["creation"]["self"]
                ov_asst = bd["creation"]["asst"]
                st.caption(
                    f"Self-created = no pass into the shot; assisted = a teammate "
                    f"fed it. Season: self {_pctf(ov_self['pct'])} on "
                    f"{ov_self['FGA']} · assisted {_pctf(ov_asst['pct'])} on "
                    f"{ov_asst['FGA']}. Bars = game margin (right axis).")

            # share of shots self-created vs non-self-created, MOV bars
            st.markdown("<div class='lab-hdr'>Self-created vs non-self-created "
                        "shot share — per game</div>", unsafe_allow_html=True)
            if glog_tracked:
                self_sh, non_sh = [], []
                for g in glog_tracked:
                    c = cbg[g["game_id"]]
                    tot = c["self_FGA"] + c["asst_FGA"]
                    self_sh.append(100 * S._safe(c["self_FGA"], tot))
                    non_sh.append(100 * S._safe(c["asst_FGA"], tot))
                shf = go.Figure()
                shf.add_trace(go.Bar(
                    x=gx, y=mov, name="Margin", yaxis="y2",
                    marker_color=[GOOD if m >= 0 else BAD for m in mov],
                    opacity=0.28, marker_line_width=0,
                    hovertemplate="Margin %{y:+d}<extra></extra>"))
                shf.add_trace(go.Scatter(
                    x=gx, y=self_sh, name="% self-created", mode="lines+markers",
                    line=dict(color=ACCENT, width=3)))
                shf.add_trace(go.Scatter(
                    x=gx, y=non_sh, name="% non-self-created (off pass)",
                    mode="lines+markers", line=dict(color=BLUE, width=3)))
                shf.update_layout(
                    yaxis=dict(title="Share of shots %", range=[0, 100]),
                    yaxis2=dict(title="Margin", overlaying="y", side="right",
                                showgrid=False, zerolinecolor="#30363d"))
                shf.update_xaxes(tickangle=-40)
                _style(shf, 400)
                st.plotly_chart(shf, width="stretch", key="sh_share")
                ov_self2 = bd["creation"]["self"]
                ov_asst2 = bd["creation"]["asst"]
                tot_all = ov_self2["FGA"] + ov_asst2["FGA"]
                st.caption(
                    f"Share of the team's FGA that are self-created (no pass) vs "
                    f"set up by a pass, each game. Season: "
                    f"{100*S._safe(ov_self2['FGA'], tot_all):.0f}% self-created · "
                    f"{100*S._safe(ov_asst2['FGA'], tot_all):.0f}% off a pass. "
                    f"Bars = game margin (right axis).")

            # shooting by quarter
            if qs:
                st.markdown("<div class='lab-hdr'>Shooting by quarter</div>",
                            unsafe_allow_html=True)
                qfg = [S._safe(quarter[q]["fgm_for"], quarter[q]["fga_for"]) * 100
                       for q in qs]
                q3 = [S._safe(quarter[q]["3pm_for"], quarter[q]["3pa_for"]) * 100
                      for q in qs]
                qf = go.Figure()
                qf.add_trace(go.Scatter(x=[_q_label(q) for q in qs], y=qfg,
                                        name="FG%", mode="lines+markers",
                                        line=dict(color=ACCENT, width=3)))
                qf.add_trace(go.Scatter(x=[_q_label(q) for q in qs], y=q3,
                                        name="3P%", mode="lines+markers",
                                        line=dict(color=BLUE, width=3)))
                qf.update_yaxes(title="%")
                _style(qf, 300)
                st.plotly_chart(qf, width="stretch", key="sh_qfg")

        # ───────────────────────────────────────────── REBOUNDING ───────────
        with ch_rb:
            rm = st.columns(4)
            rm[0].metric("OREB%", _pctf(ff["off"]["ORB"]),
                         help="Share of own misses rebounded.")
            rm[1].metric("DREB%",
                         _pctf(S._safe(tb["DRB"], tb["DRB"] + ob["ORB"])))
            rm[2].metric("REB / game", f"{tb['TRB'] / ng:.1f}")
            rm[3].metric("OREB / game", f"{tb['ORB'] / ng:.1f}")

            st.markdown("<div class='lab-hdr'>Offensive rebounding by quarter"
                        "</div>", unsafe_allow_html=True)
            if qs:
                of = [quarter[q]["oreb_for"] for q in qs]
                ag = [quarter[q]["oreb_against"] for q in qs]
                ofig = go.Figure()
                ofig.add_trace(go.Bar(x=[_q_label(q) for q in qs], y=of,
                                      name="OREB grabbed", marker_color=ACCENT))
                ofig.add_trace(go.Bar(x=[_q_label(q) for q in qs], y=ag,
                                      name="OREB allowed", marker_color=AWAY))
                ofig.update_layout(barmode="group")
                ofig.update_yaxes(title="Offensive rebounds (total)")
                _style(ofig, 320)
                st.plotly_chart(ofig, width="stretch", key="rb_oreb")
                st.caption("Offensive boards grabbed vs allowed, by quarter, "
                           "across tracked games.")

            st.markdown("<div class='lab-hdr'>Player rebounding leaders</div>",
                        unsafe_allow_html=True)
            rebp = sorted([p for p in players if p["RPG"] is not None],
                          key=lambda p: p["RPG"], reverse=True)[:8]
            if rebp:
                rbf = go.Figure()
                rbf.add_trace(go.Bar(x=[f"#{p['number']}" for p in rebp],
                                     y=[p["OREB/G"] for p in rebp], name="OREB/G",
                                     marker_color=ACCENT))
                rbf.add_trace(go.Bar(x=[f"#{p['number']}" for p in rebp],
                                     y=[p["DREB/G"] for p in rebp], name="DREB/G",
                                     marker_color=BLUE))
                rbf.update_layout(barmode="stack")
                rbf.update_yaxes(title="Rebounds / game")
                _style(rbf, 320)
                st.plotly_chart(rbf, width="stretch", key="rb_players")

        # ───────────────────────────────────────────── DEFENSE ──────────────
        with ch_df:
            dm = st.columns(4)
            dm[0].metric("Def Rtg", f"{summ.get('DRtg', 0):.1f}",
                         help="Points allowed / 100 poss. Lower is better.")
            dm[1].metric("Opp eFG%", _pctf(ff["def"]["eFG"]))
            dm[2].metric("Forced TOV%", _pctf(ff["def"]["TOV"]))
            dm[3].metric("Stocks / game", f"{(tb['STL'] + tb['BLK']) / ng:.1f}")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Opponent shooting allowed**")
                dsp = [("FG%", S.fg_pct(ob)), ("2P%", S.fg2_pct(ob)),
                       ("3P%", S.fg3_pct(ob)), ("Paint%", S.paint_fg_pct(ob)),
                       ("eFG%", S.efg(ob))]
                dfg = go.Figure(go.Bar(
                    x=[s[0] for s in dsp], y=[s[1] * 100 for s in dsp],
                    marker_color=AWAY, marker_line_width=0,
                    text=[f"{s[1]*100:.0f}" for s in dsp], textposition="auto"))
                dfg.update_yaxes(title="% allowed")
                _style(dfg, 300)
                st.plotly_chart(dfg, width="stretch", key="df_shoot")
            with c2:
                st.markdown("**Opponent scoring sources**")
                ddn = go.Figure(go.Pie(
                    labels=["2-pt", "3-pt", "Free throw"],
                    values=[sdef["pts2"], sdef["pts3"], sdef["ptsft"]],
                    hole=0.55, sort=False,
                    marker=dict(colors=[AWAY, "#f0a500", GREY]),
                    textinfo="label+percent"))
                ddn.update_layout(
                    template="plotly_dark", height=300,
                    paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                    margin=dict(l=10, r=10, t=10, b=10),
                    annotations=[dict(text=f"{sdef['pct_paint']*100:.0f}%<br>"
                                           "<span style='font-size:10px'>in paint"
                                           "</span>", x=0.5, y=0.5,
                                      font=dict(size=15), showarrow=False)])
                st.plotly_chart(ddn, width="stretch", key="df_src")

            # opponent zone profile
            st.markdown("<div class='lab-hdr'>Opponent shot profile — where "
                        "they attack us</div>", unsafe_allow_html=True)
            zd = zones["def"]
            zc1, zc2 = st.columns(2)
            with zc1:
                zfa = go.Figure(go.Bar(
                    x=[TA.ZONE_LABELS[z] for z in TA.ZONES],
                    y=[zd[z]["FGA"] for z in TA.ZONES],
                    marker_color=AWAY, marker_line_width=0,
                    text=[zd[z]["FGA"] for z in TA.ZONES], textposition="auto"))
                zfa.update_yaxes(title="Attempts allowed")
                zfa.update_xaxes(tickangle=-25)
                _style(zfa, 300)
                st.plotly_chart(zfa, width="stretch", key="df_zfa")
            with zc2:
                zfg = go.Figure(go.Bar(
                    x=[TA.ZONE_LABELS[z] for z in TA.ZONES],
                    y=[zd[z]["FG%"] * 100 for z in TA.ZONES],
                    marker_color="#f0a500", marker_line_width=0,
                    text=[_pctf(zd[z]["FG%"]) if zd[z]["FGA"] else "—"
                          for z in TA.ZONES], textposition="auto"))
                zfg.update_yaxes(title="FG% allowed")
                zfg.update_xaxes(tickangle=-25)
                _style(zfg, 300)
                st.plotly_chart(zfg, width="stretch", key="df_zfg")

            # individual defense (Oliver DRtg + stocks)
            st.markdown("<div class='lab-hdr'>Individual defense</div>",
                        unsafe_allow_html=True)
            oliver = TA.player_oliver_ratings(team_id, bundle["tracked_ids"])
            pid_name = {p["_pid"]: f"#{p['number']} {p['name']}" for p in players}
            stk = sorted([p for p in players if p["STOCKS/G"] is not None],
                         key=lambda p: p["STOCKS/G"], reverse=True)[:8]
            dc1, dc2 = st.columns(2)
            with dc1:
                st.markdown("**Stocks (STL+BLK) / game**")
                if stk:
                    sf = go.Figure()
                    sf.add_trace(go.Bar(x=[f"#{p['number']}" for p in stk],
                                        y=[p["SPG"] for p in stk], name="STL/G",
                                        marker_color=ACCENT))
                    sf.add_trace(go.Bar(x=[f"#{p['number']}" for p in stk],
                                        y=[p["BPG"] for p in stk], name="BLK/G",
                                        marker_color=BLUE))
                    sf.update_layout(barmode="stack")
                    sf.update_yaxes(title="Per game")
                    _style(sf, 300)
                    st.plotly_chart(sf, width="stretch", key="df_stocks")
            with dc2:
                st.markdown("**Individual Def Rtg** (lower = better)")
                drows = sorted(
                    [(pid_name.get(pid, "?"), v["DRtg"])
                     for pid, v in oliver.items() if v["DRtg"] is not None],
                    key=lambda x: x[1])[:8]
                if drows:
                    df_ = go.Figure(go.Bar(
                        x=[r[1] for r in reversed(drows)],
                        y=[r[0] for r in reversed(drows)], orientation="h",
                        marker_color=GOOD, marker_line_width=0,
                        text=[f"{r[1]:.0f}" for r in reversed(drows)],
                        textposition="auto"))
                    df_.update_xaxes(title="Def Rtg (pts/100)")
                    _style(df_, 300)
                    df_.update_layout(margin=dict(l=4, r=14, t=6, b=30))
                    st.plotly_chart(df_, width="stretch", key="df_drtg")
                    st.caption("Dean Oliver individual DRtg — directional on this "
                               "sample (inferred rebounds, no minutes).")

        # ───────────────────────────────────────────── TRENDS ───────────────
        with ch_tr:
            if len(trend) < 2:
                st.info("Need at least two tracked games for trend charts.")
            else:
                st.markdown("<div class='lab-hdr'>Net rating — per game"
                            "</div>", unsafe_allow_html=True)
                nr = go.Figure(go.Bar(
                    x=tx, y=[e["NetRtg"] for e in trend],
                    marker_color=[GOOD if e["NetRtg"] >= 0 else BAD
                                  for e in trend], marker_line_width=0,
                    text=[f"{e['NetRtg']:+.0f}" for e in trend],
                    textposition="outside", textfont=dict(size=9)))
                nr.add_hline(y=0, line=dict(color="#30363d"))
                nr.update_yaxes(title="Net rating (pts/100)")
                nr.update_xaxes(tickangle=-40)
                _style(nr, 340)
                st.plotly_chart(nr, width="stretch", key="tr_net")

                st.markdown("<div class='lab-hdr'>Efficiency — rolling 3-game"
                            "</div>", unsafe_allow_html=True)
                ortg = [e["ORtg"] for e in trend]
                drtg = [e["DRtg"] for e in trend]
                eff = _trend_line(
                    tx, [("ORtg (3g avg)", TA.rolling(ortg), ACCENT),
                         ("DRtg (3g avg)", TA.rolling(drtg), AWAY)],
                    None, "tr_eff", height=320, yaxis="Pts / 100 poss")
                st.plotly_chart(eff, width="stretch", key="tr_eff")

                c1, c2 = st.columns(2)
                with c1:
                    efgv = [e["eFG"] * 100 for e in trend]
                    avg = sum(efgv) / len(efgv)
                    ef = _trend_line(
                        tx, [("eFG%", efgv, ACCENT),
                             ("Opp eFG%", [e["oeFG"] * 100 for e in trend], AWAY)],
                        None, "tr_efg", height=300, yaxis="eFG%")
                    st.plotly_chart(ef, width="stretch", key="tr_efg")
                with c2:
                    pc = _trend_line(
                        tx, [("Pace", [e["Pace"] for e in trend], BLUE)],
                        None, "tr_pace", height=300, yaxis="Possessions",
                        avg=sum(e["Pace"] for e in trend) / len(trend))
                    st.plotly_chart(pc, width="stretch", key="tr_pace")

                c3, c4 = st.columns(2)
                with c3:
                    to = _trend_line(
                        tx, [("Turnovers", [e["TOV"] for e in trend], AWAY),
                             ("Steals", [e["STL"] for e in trend], GOOD)],
                        None, "tr_to", height=300, yaxis="Count")
                    st.plotly_chart(to, width="stretch", key="tr_to")
                with c4:
                    asf = _trend_line(
                        tx, [("Assists", [e["AST"] for e in trend], PURPLE)],
                        None, "tr_ast", height=300, yaxis="Assists",
                        avg=sum(e["AST"] for e in trend) / len(trend))
                    st.plotly_chart(asf, width="stretch", key="tr_ast")

                # margin distribution
                st.markdown("<div class='lab-hdr'>Score-margin distribution"
                            "</div>", unsafe_allow_html=True)
                margins = [g["margin"] for g in log]
                mh = go.Figure(go.Histogram(
                    x=margins, nbinsx=15, marker_color=ACCENT,
                    marker_line_width=0))
                mh.add_vline(x=0, line=dict(color=GREY, dash="dot"))
                mh.update_xaxes(title="Final margin")
                mh.update_yaxes(title="Games")
                _style(mh, 300)
                st.plotly_chart(mh, width="stretch", key="tr_margin")

                # wins vs losses + venue
                wl = bundle["wl_splits"]
                if wl["W"] and wl["L"]:
                    st.markdown("<div class='lab-hdr'>Wins vs losses</div>",
                                unsafe_allow_html=True)
                    cats = [("PF", "Pts for"), ("PA", "Pts against"),
                            ("eFG", "eFG%"), ("TOV", "Turnovers"),
                            ("ORB", "OREB"), ("AST", "Assists")]
                    wlf = go.Figure()
                    wlf.add_trace(go.Bar(
                        name="Wins", x=[c[1] for c in cats],
                        y=[wl["W"][c[0]] * (100 if c[0] == "eFG" else 1)
                           for c in cats], marker_color=GOOD))
                    wlf.add_trace(go.Bar(
                        name="Losses", x=[c[1] for c in cats],
                        y=[wl["L"][c[0]] * (100 if c[0] == "eFG" else 1)
                           for c in cats], marker_color=BAD))
                    wlf.update_layout(barmode="group")
                    wlf.update_yaxes(title="Per game (eFG% as %)")
                    _style(wlf, 320)
                    st.plotly_chart(wlf, width="stretch", key="tr_wl")
                    st.caption(f"Averages in {wl['W']['n']} wins vs "
                               f"{wl['L']['n']} losses.")

                venue = bundle["venue"]
                st.markdown("<div class='lab-hdr'>Home / away splits</div>",
                            unsafe_allow_html=True)
                vrows = []
                for tag in ("Home", "Away"):
                    v = venue[tag]
                    vrows.append({"Venue": tag, "GP": v["n"],
                                  "Record": f"{v['W']}-{v['L']}",
                                  "PF/G": f"{v['PF']:.1f}",
                                  "PA/G": f"{v['PA']:.1f}",
                                  "MOV": f"{v['MOV']:+.1f}"})
                st.dataframe(pd.DataFrame(vrows), hide_index=True,
                             width="stretch")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — QUARTERS  (every tracked stat, split by quarter)
# ══════════════════════════════════════════════════════════════════════════════
with tab_quarters:
    qbx = bundle["quarter_boxes"]
    if not has_tracked or not qbx:
        st.info("No tracked games yet — quarter splits need play-by-play data "
                "from the Game Tracker.")
    else:
        st.caption("Every tracked stat, broken out by quarter and averaged over "
                   "tracked games. 'For' / 'Allowed' = this team vs opponents. "
                   "Small samples are directional.")

        qsq = sorted(qbx)
        qx = [_q_label(q) for q in qsq]

        def _qv(fn):
            """Apply fn(quarter_dict) across the sorted quarters → list."""
            return [fn(qbx[q]) for q in qsq]

        def _pg(side, key):
            """Per-game total of `key` for 'team' or 'opp' box, by quarter."""
            return _qv(lambda d: d[side][key] / max(d["n_games"], 1))

        def _rate(side, fn):
            """A rate fn (S.*) applied to the team/opp box, ×100, by quarter."""
            return _qv(lambda d: fn(d[side]) * 100)

        ng_q = {q: qbx[q]["n_games"] for q in qsq}

        # ── headline: who owns which quarter ────────────────────────────────
        net_pg = [(_qv(lambda d: d["team"]["PTS"] / max(d["n_games"], 1))[i]
                   - _qv(lambda d: d["opp"]["PTS"] / max(d["n_games"], 1))[i])
                  for i in range(len(qsq))]
        reg = [(q, net_pg[i]) for i, q in enumerate(qsq) if q <= 4]
        hm = st.columns(4)
        if reg:
            best_q = max(reg, key=lambda t: t[1])
            worst_q = min(reg, key=lambda t: t[1])
            hm[0].metric("Best quarter", _q_label(best_q[0]),
                         f"{best_q[1]:+.1f} net/g")
            hm[1].metric("Worst quarter", _q_label(worst_q[0]),
                         f"{worst_q[1]:+.1f} net/g")
            h1 = sum(n for q, n in reg if q <= 2)
            h2 = sum(n for q, n in reg if 3 <= q <= 4)
            hm[2].metric("1st-half net/g", f"{h1:+.1f}")
            hm[3].metric("2nd-half net/g", f"{h2:+.1f}")

        # ─────────────────────────────────────────── SCORING & EFFICIENCY ───
        st.markdown("<div class='lab-hdr'>Scoring & efficiency by quarter"
                    "</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Points — scored vs allowed / game**")
            st.plotly_chart(_q_bars(
                qsq, [("Scored", _pg("team", "PTS"), ACCENT),
                      ("Allowed", _pg("opp", "PTS"), AWAY)],
                "Points / game"), width="stretch", key="q_pts")
        with c2:
            st.markdown("**Net points / game**")
            nf = go.Figure(go.Bar(
                x=qx, y=net_pg,
                marker_color=[GOOD if n >= 0 else BAD for n in net_pg],
                marker_line_width=0, text=[f"{n:+.1f}" for n in net_pg],
                textposition="auto"))
            nf.add_hline(y=0, line=dict(color="#30363d"))
            nf.update_yaxes(title="Net points / game")
            _style(nf, 300)
            st.plotly_chart(nf, width="stretch", key="q_net")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("**Offensive vs Defensive Rating** (pts / 100 poss)")
            ortg = _qv(lambda d: 100 * S._safe(d["team"]["PTS"], d["poss"]))
            drtg = _qv(lambda d: 100 * S._safe(d["opp"]["PTS"], d["opp_poss"]))
            st.plotly_chart(_q_lines(
                qsq, [("Off Rtg", ortg, ACCENT), ("Def Rtg", drtg, AWAY)],
                "Rating"), width="stretch", key="q_rtg")
        with c4:
            st.markdown("**Net Rating by quarter**")
            netr = [ortg[i] - drtg[i] for i in range(len(qsq))]
            nrf = go.Figure(go.Bar(
                x=qx, y=netr,
                marker_color=[GOOD if n >= 0 else BAD for n in netr],
                marker_line_width=0, text=[f"{n:+.0f}" for n in netr],
                textposition="auto"))
            nrf.add_hline(y=0, line=dict(color="#30363d"))
            nrf.update_yaxes(title="Net rating")
            _style(nrf, 300)
            st.plotly_chart(nrf, width="stretch", key="q_netrtg")

        c5, c6 = st.columns(2)
        with c5:
            st.markdown("**Points per possession** — for vs allowed")
            ppp = _qv(lambda d: S._safe(d["team"]["PTS"], d["poss"]))
            oppp = _qv(lambda d: S._safe(d["opp"]["PTS"], d["opp_poss"]))
            st.plotly_chart(_q_lines(
                qsq, [("PPP", ppp, ACCENT), ("Opp PPP", oppp, AWAY)],
                "Points / possession"), width="stretch", key="q_ppp")
        with c6:
            st.markdown("**Pace** — possessions / game")
            pace = _qv(lambda d: (d["poss"] + d["opp_poss"]) / 2
                       / max(d["n_games"], 1))
            st.plotly_chart(_q_bars(
                qsq, [("Pace", pace, BLUE)], "Possessions / game",
                text_fmt=lambda v: f"{v:.1f}"),
                width="stretch", key="q_pace")

        # ─────────────────────────────────────────── SHOOTING (OFFENSE) ─────
        st.markdown("<div class='lab-hdr'>Shooting — offense, by quarter"
                    "</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**FG% · 2P% · 3P%**")
            st.plotly_chart(_q_lines(
                qsq, [("FG%", _rate("team", S.fg_pct), ACCENT),
                      ("2P%", _rate("team", S.fg2_pct), GOOD),
                      ("3P%", _rate("team", S.fg3_pct), BLUE)],
                "%"), width="stretch", key="q_fg")
        with c2:
            st.markdown("**eFG% · TS% · Paint FG%**")
            st.plotly_chart(_q_lines(
                qsq, [("eFG%", _rate("team", S.efg), ACCENT),
                      ("TS%", _rate("team", S.ts), PURPLE),
                      ("Paint FG%", _rate("team", S.paint_fg_pct), GOOD)],
                "%"), width="stretch", key="q_efg")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("**FT% by quarter**")
            st.plotly_chart(_q_bars(
                qsq, [("FT%", _rate("team", S.ft_pct), "#d29922")], "%",
                text_fmt=lambda v: f"{v:.0f}"),
                width="stretch", key="q_ft")
        with c4:
            st.markdown("**Shot rates — 3PA rate & FT rate**")
            st.plotly_chart(_q_lines(
                qsq, [("3PA rate", _rate("team", S.three_par), BLUE),
                      ("FT rate", _rate("team", S.ftr), "#d29922")],
                "%"), width="stretch", key="q_rates")

        c5, c6 = st.columns(2)
        with c5:
            st.markdown("**Scoring efficiency** — PPS & SCE")
            st.plotly_chart(_q_lines(
                qsq, [("Pts / shot", _qv(lambda d: S.ppsa(d["team"])), ACCENT),
                      ("SCE", _qv(lambda d: S.shot_efficiency(d["team"])), GOOD)],
                "Value"), width="stretch", key="q_pps")
        with c6:
            st.markdown("**Shot volume / game** — FGA · 3PA · FTA")
            st.plotly_chart(_q_bars(
                qsq, [("FGA", _pg("team", "FGA"), ACCENT),
                      ("3PA", _pg("team", "3PA"), BLUE),
                      ("FTA", _pg("team", "FTA"), "#d29922")],
                "Attempts / game"), width="stretch", key="q_vol")

        # ─────────────────────────────────────────── SHOOTING (DEFENSE) ─────
        st.markdown("<div class='lab-hdr'>Shooting allowed — defense (oFG%), "
                    "by quarter</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Opp FG% · 2P% · 3P% allowed**")
            st.plotly_chart(_q_lines(
                qsq, [("Opp FG%", _rate("opp", S.fg_pct), AWAY),
                      ("Opp 2P%", _rate("opp", S.fg2_pct), "#f0a500"),
                      ("Opp 3P%", _rate("opp", S.fg3_pct), PURPLE)],
                "% allowed"), width="stretch", key="q_ofg")
        with c2:
            st.markdown("**Opp eFG% · TS% · Paint FG% allowed**")
            st.plotly_chart(_q_lines(
                qsq, [("Opp eFG%", _rate("opp", S.efg), AWAY),
                      ("Opp TS%", _rate("opp", S.ts), PURPLE),
                      ("Opp Paint%", _rate("opp", S.paint_fg_pct), "#f0a500")],
                "% allowed"), width="stretch", key="q_oefg")

        st.markdown("**Opponent shot volume allowed / game** — FGA · 3PA · FTA")
        st.plotly_chart(_q_bars(
            qsq, [("Opp FGA", _pg("opp", "FGA"), AWAY),
                  ("Opp 3PA", _pg("opp", "3PA"), PURPLE),
                  ("Opp FTA", _pg("opp", "FTA"), "#f0a500")],
            "Attempts / game"), width="stretch", key="q_ovol")

        # ─────────────────────────────────────────── REBOUNDING ─────────────
        st.markdown("<div class='lab-hdr'>Rebounding by quarter</div>",
                    unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Offensive rebounds / game** — grabbed vs allowed")
            st.plotly_chart(_q_bars(
                qsq, [("OREB grabbed", _pg("team", "ORB"), ACCENT),
                      ("OREB allowed", _pg("opp", "ORB"), AWAY)],
                "OREB / game"), width="stretch", key="q_oreb")
        with c2:
            st.markdown("**Defensive rebounds / game** — grabbed vs allowed")
            st.plotly_chart(_q_bars(
                qsq, [("DREB grabbed", _pg("team", "DRB"), ACCENT),
                      ("DREB allowed", _pg("opp", "DRB"), AWAY)],
                "DREB / game"), width="stretch", key="q_dreb")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("**Rebound rates** — OREB% & DREB%")
            orebp = _qv(lambda d: S._safe(
                d["team"]["ORB"], d["team"]["ORB"] + d["opp"]["DRB"]) * 100)
            drebp = _qv(lambda d: S._safe(
                d["team"]["DRB"], d["team"]["DRB"] + d["opp"]["ORB"]) * 100)
            st.plotly_chart(_q_lines(
                qsq, [("OREB%", orebp, ACCENT), ("DREB%", drebp, BLUE)],
                "%"), width="stretch", key="q_rebpct")
        with c4:
            st.markdown("**Total rebounds / game** — for vs against")
            st.plotly_chart(_q_bars(
                qsq, [("REB", _pg("team", "TRB"), ACCENT),
                      ("Opp REB", _pg("opp", "TRB"), AWAY)],
                "Rebounds / game"), width="stretch", key="q_reb")

        # ─────────────────────────────────────────── BALL CONTROL & D ───────
        st.markdown("<div class='lab-hdr'>Ball control & defense by quarter"
                    "</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Turnovers / game** — committed vs forced")
            st.plotly_chart(_q_bars(
                qsq, [("Committed", _pg("team", "TOV"), AWAY),
                      ("Forced", _pg("opp", "TOV"), GOOD)],
                "Turnovers / game"), width="stretch", key="q_tov")
        with c2:
            st.markdown("**Turnover rate** — own vs forced")
            st.plotly_chart(_q_lines(
                qsq, [("TOV%", _qv(lambda d: d["four_factors"]["off"]["TOV"]
                                   * 100), AWAY),
                      ("Forced TOV%", _qv(lambda d: d["four_factors"]["def"]["TOV"]
                                          * 100), GOOD)],
                "%"), width="stretch", key="q_tovpct")

        c3, c4 = st.columns(2)
        with c3:
            st.markdown("**Assists / game** — for vs against")
            st.plotly_chart(_q_bars(
                qsq, [("Assists", _pg("team", "AST"), ACCENT),
                      ("Opp assists", _pg("opp", "AST"), AWAY)],
                "Assists / game"), width="stretch", key="q_ast")
        with c4:
            st.markdown("**Assist-to-turnover ratio** — for vs against")
            atr = _qv(lambda d: S._safe(d["team"]["AST"], d["team"]["TOV"]))
            oatr = _qv(lambda d: S._safe(d["opp"]["AST"], d["opp"]["TOV"]))
            st.plotly_chart(_q_lines(
                qsq, [("AST/TO", atr, ACCENT), ("Opp AST/TO", oatr, AWAY)],
                "Ratio"), width="stretch", key="q_atr")

        c5, c6 = st.columns(2)
        with c5:
            st.markdown("**Stocks / game** — steals, blocks & total")
            st.plotly_chart(_q_bars(
                qsq, [("Steals", _pg("team", "STL"), ACCENT),
                      ("Blocks", _pg("team", "BLK"), BLUE),
                      ("Stocks", _pg("team", "stocks"), GOOD)],
                "Per game"), width="stretch", key="q_stocks")
        with c6:
            st.markdown("**Fouls / game** — committed vs drawn")
            st.plotly_chart(_q_bars(
                qsq, [("Committed", _pg("team", "PF"), AWAY),
                      ("Drawn", _pg("opp", "PF"), GOOD)],
                "Fouls / game"), width="stretch", key="q_pf")

        # ─────────────────────────────────────────── FOUR FACTORS ───────────
        st.markdown("<div class='lab-hdr'>Four factors by quarter — offense "
                    "vs defense</div>", unsafe_allow_html=True)
        st.caption("eFG%, OREB% and FT rate: higher offense is better. TOV%: "
                   "lower own / higher forced is better.")
        ff_keys = [("eFG", "eFG%"), ("TOV", "TOV%"), ("ORB", "OREB%"),
                   ("FTR", "FT rate")]
        fcols = st.columns(2)
        for i, (k, lbl) in enumerate(ff_keys):
            with fcols[i % 2]:
                st.markdown(f"**{lbl}** — offense vs defense")
                offv = _qv(lambda d, k=k: d["four_factors"]["off"][k] * 100)
                defv = _qv(lambda d, k=k: d["four_factors"]["def"][k] * 100)
                st.plotly_chart(_q_bars(
                    qsq, [("Offense", offv, ACCENT), ("Allowed", defv, AWAY)],
                    "%"), width="stretch", key=f"q_ff_{k}")

        # ─────────────────────────────────────────── FULL TABLE ─────────────
        st.markdown("<div class='lab-hdr'>Per-quarter stat table</div>",
                    unsafe_allow_html=True)
        qrows = []
        for q in qsq:
            d = qbx[q]
            tbq, obq, n = d["team"], d["opp"], max(d["n_games"], 1)
            qrows.append({
                "Q": _q_label(q), "GP": d["n_games"],
                "PF/G": round(tbq["PTS"] / n, 1),
                "PA/G": round(obq["PTS"] / n, 1),
                "ORtg": round(100 * S._safe(tbq["PTS"], d["poss"]), 1),
                "DRtg": round(100 * S._safe(obq["PTS"], d["opp_poss"]), 1),
                "PPP": round(S._safe(tbq["PTS"], d["poss"]), 2),
                "FG%": _pctf(S.fg_pct(tbq), 0),
                "3P%": _pctf(S.fg3_pct(tbq), 0),
                "eFG%": _pctf(S.efg(tbq), 0),
                "oFG%": _pctf(S.fg_pct(obq), 0),
                "OREB/G": round(tbq["ORB"] / n, 1),
                "DREB/G": round(tbq["DRB"] / n, 1),
                "AST/G": round(tbq["AST"] / n, 1),
                "TOV/G": round(tbq["TOV"] / n, 1),
                "STK/G": round(tbq["stocks"] / n, 1),
            })
        st.dataframe(pd.DataFrame(qrows), hide_index=True,
                     width="stretch")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — ADVANCED  (the futuristic analytics lab: 5 sub-tabs)
# ══════════════════════════════════════════════════════════════════════════════
with tab_advanced:
    st.caption("The analytics lab — league-relative efficiency, team DNA, "
               "schedule résumé, the passing network, possession flow and "
               "shot-quality. Most panels need tracked games; the résumé works "
               "from results alone.")

    adv_eff, adv_res, adv_play, adv_flow, adv_shot = st.tabs(
        ["⚡ Efficiency & DNA", "📋 Résumé & Form", "🕸 Playmaking",
         "📽 Game Flow", "🔬 Shot Lab"])

    # ───────────────────────────────────────── EFFICIENCY & DNA ─────────────
    with adv_eff:
        if not has_tracked or not sc_track:
            st.info("Tracked games needed for league-relative efficiency.")
        else:
            pool_o = [r["ORtg"] for r in tracked.values()]
            pool_d = [r["DRtg"] for r in tracked.values()]
            pool_n = [r["NetRtg"] for r in tracked.values()]
            pool_p = [r["Pace"] for r in tracked.values()]
            avg_o = sum(pool_o) / len(pool_o)
            avg_d = sum(pool_d) / len(pool_d)

            # ── KenPom-style efficiency quadrant ────────────────────────────
            st.markdown("<div class='lab-hdr'>Efficiency Landscape</div>",
                        unsafe_allow_html=True)
            st.caption("Every tracked team plotted by offense (right = better) "
                       "and defense (up = better). Crosshairs = league average. "
                       "Top-right is elite; bottom-left is rebuilding.")
            others = [(tid2, r) for tid2, r in tracked.items() if tid2 != team_id]
            kp = go.Figure()
            kp.add_trace(go.Scatter(
                x=[r["ORtg"] for _, r in others],
                y=[r["DRtg"] for _, r in others], mode="markers",
                marker=dict(size=9, color="#475569",
                            line=dict(width=0)),
                hovertext=[team_by_id.get(t, {}).get("name", "?")
                           for t, _ in others],
                hovertemplate="%{hovertext}<br>ORtg %{x:.1f} · DRtg %{y:.1f}"
                              "<extra></extra>", name="League"))
            kp.add_trace(go.Scatter(
                x=[sc_track["ORtg"]], y=[sc_track["DRtg"]], mode="markers+text",
                marker=dict(size=22, color=ACCENT, symbol="star",
                            line=dict(width=2, color=CYBER)),
                text=[team["name"]], textposition="top center",
                textfont=dict(size=12, color=CYBER),
                hovertemplate=f"{team['name']}<br>ORtg %{{x:.1f}} · "
                              "DRtg %{y:.1f}<extra></extra>", name=team["name"]))
            kp.add_vline(x=avg_o, line=dict(color="#30363d", dash="dot"))
            kp.add_hline(y=avg_d, line=dict(color="#30363d", dash="dot"))
            corners = [
                (max(pool_o), min(pool_d), "ELITE", GOOD),
                (min(pool_o), min(pool_d), "GOOD DEFENSE", BLUE),
                (max(pool_o), max(pool_d), "GOOD OFFENSE", ACCENT),
                (min(pool_o), max(pool_d), "REBUILDING", BAD)]
            for cx, cy, txt, clr in corners:
                kp.add_annotation(x=cx, y=cy, text=txt, showarrow=False,
                                  font=dict(size=9, color=clr),
                                  opacity=0.65)
            kp.update_xaxes(title="Offensive Rating →")
            kp.update_yaxes(title="← Defensive Rating (lower better)",
                            autorange="reversed")
            _style(kp, 460)
            st.plotly_chart(kp, width="stretch", key="adv_kenpom")

            # ── performance gauges ──────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>Performance Gauges</div>",
                        unsafe_allow_html=True)
            st.caption("Needle vs the league range; cyan line marks the league "
                       "average and the delta shows the gap to it.")
            g1, g2, g3, g4 = st.columns(4)
            with g1:
                st.plotly_chart(_gauge(
                    sc_track["ORtg"], min(pool_o), max(pool_o), "Off Rating",
                    good_high=True, ref=avg_o), width="stretch", key="adv_g_o")
            with g2:
                st.plotly_chart(_gauge(
                    sc_track["DRtg"], min(pool_d), max(pool_d), "Def Rating",
                    good_high=False, ref=avg_d), width="stretch", key="adv_g_d")
            with g3:
                st.plotly_chart(_gauge(
                    sc_track["NetRtg"], min(pool_n), max(pool_n), "Net Rating",
                    good_high=True, ref=sum(pool_n) / len(pool_n)),
                    width="stretch", key="adv_g_n")
            with g4:
                st.plotly_chart(_gauge(
                    sc_track["Pace"], min(pool_p), max(pool_p), "Pace",
                    good_high=True, ref=sum(pool_p) / len(pool_p)),
                    width="stretch", key="adv_g_p")

            # ── team DNA radar (8 percentile axes vs league) ────────────────
            st.markdown("<div class='lab-hdr'>Team DNA — league percentiles</div>",
                        unsafe_allow_html=True)
            lff = _league_ff(gender)
            offp = {k: [v["off"][k] for v in lff.values()]
                    for k in ["eFG", "TOV", "ORB", "FTR"]}
            defp = {k: [v["def"][k] for v in lff.values()]
                    for k in ["eFG", "TOV"]}

            def _pc(val, pool, hb=True):
                return TA.percentile(val, pool, higher_better=hb) or 0

            axes = [
                ("Offense", _pc(sc_track["ORtg"], pool_o, True)),
                ("Defense", _pc(sc_track["DRtg"], pool_d, False)),
                ("Shooting", _pc(ff["off"]["eFG"], offp["eFG"], True)),
                ("Ball Security", _pc(ff["off"]["TOV"], offp["TOV"], False)),
                ("Off. Rebound", _pc(ff["off"]["ORB"], offp["ORB"], True)),
                ("FT Rate", _pc(ff["off"]["FTR"], offp["FTR"], True)),
                ("Forces TOs", _pc(ff["def"]["TOV"], defp["TOV"], True)),
                ("Shot Defense", _pc(ff["def"]["eFG"], defp["eFG"], False)),
            ]
            ar, ag, ab = _rgb(ACCENT)
            theta = [a[0] for a in axes] + [axes[0][0]]
            rvals = [a[1] for a in axes] + [axes[0][1]]
            dna = go.Figure()
            dna.add_trace(go.Scatterpolar(
                r=[50] * len(theta), theta=theta, mode="lines",
                line=dict(color=GREY, width=1, dash="dot"),
                name="League avg (50)", hoverinfo="skip"))
            dna.add_trace(go.Scatterpolar(
                r=rvals, theta=theta, fill="toself", name=team["name"],
                line=dict(color=CYBER, width=2.5),
                fillcolor=f"rgba({ar},{ag},{ab},0.28)",
                hovertemplate="%{theta}: %{r:.0f}th pct<extra></extra>"))
            dna.update_layout(
                template="plotly_dark", height=440,
                paper_bgcolor="rgba(0,0,0,0)", showlegend=True,
                legend=dict(orientation="h", y=1.08, x=0),
                polar=dict(bgcolor=CARD_BG,
                           radialaxis=dict(range=[0, 100], gridcolor=GRID,
                                           tickfont=dict(size=9)),
                           angularaxis=dict(gridcolor=GRID,
                                            tickfont=dict(size=10))),
                margin=dict(l=60, r=60, t=50, b=30))
            st.plotly_chart(dna, width="stretch", key="adv_dna")
            st.caption("Each spoke is this team's league percentile on that skill "
                       "(100 = best in the league). All spokes are framed so "
                       "outward = better, defense and turnovers included.")

    # ───────────────────────────────────────── RÉSUMÉ & FORM ────────────────
    with adv_res:
        power_by = {tid2: r.get("Power") for tid2, r in scored.items()}
        rank_by = {tid2: r.get("Rank") for tid2, r in scored.items()}
        sos = TA.strength_of_schedule(log, power_by, rank_by, len(scored))

        st.markdown("<div class='lab-hdr'>Strength of Schedule</div>",
                    unsafe_allow_html=True)
        sm = st.columns(4)
        sm[0].metric("Avg opp. power", f"{sos['avg_opp_power']:.1f}",
                     help="Mean opponent power rating (50 = league average).")
        sm[1].metric(f"vs Top-{sos['top_cut']}",
                     f"{sos['vs_top']['w']}-{sos['vs_top']['l']}",
                     help="Record vs top-25% ranked opponents.")
        sm[2].metric("vs Top-10",
                     f"{sos['vs_top10']['w']}-{sos['vs_top10']['l']}")
        sm[3].metric("Quality wins", sos["quality_wins"],
                     help=f"Wins over top-{sos['top_cut']} opponents.")
        if sos["toughest"]:
            t = sos["toughest"]
            st.markdown(
                f"<div class='glass-tile' style='text-align:left'>"
                f"<span class='glass-label'>Toughest opponent faced</span><br>"
                f"<span style='font-size:18px;font-weight:800;color:#f0f6fc'>"
                f"{t['opp']}</span> "
                f"<span style='color:{GREY}'>(power {t['power']:.0f})</span> — "
                f"<span style='color:{GOOD if t['won'] else BAD};font-weight:700'>"
                f"{'WON' if t['won'] else 'LOST'} by {abs(t['margin'])}</span>"
                f"</div>", unsafe_allow_html=True)

        st.markdown("<div class='lab-hdr'>Form & Streaks</div>",
                    unsafe_allow_html=True)
        fm = st.columns(4)
        cur = strk["current"]
        fm[0].metric("Current streak",
                     f"{cur['len']}{cur['type']}" if cur["type"] else "—")
        fm[1].metric("Longest win streak", strk["longest_win"])
        fm[2].metric("Last 5", f"{strk['last5']['w']}-{strk['last5']['l']}")
        fm[3].metric("Last 10", f"{strk['last10']['w']}-{strk['last10']['l']}")

        st.markdown("<div class='lab-hdr'>Situational Record</div>",
                    unsafe_allow_html=True)
        sr = st.columns(4)
        sr[0].metric("Close (≤5)",
                     f"{strk['close']['w']}-{strk['close']['l']}",
                     help="Games decided by 5 or fewer points.")
        sr[1].metric("One-possession (≤3)",
                     f"{strk['one_poss']['w']}-{strk['one_poss']['l']}")
        sr[2].metric("Blowouts (≥15)",
                     f"{strk['blowout']['w']}-{strk['blowout']['l']}")
        sr[3].metric("Avg win / loss margin",
                     f"+{strk['avg_win_margin']:.0f} / "
                     f"{strk['avg_loss_margin']:.0f}")

        # schedule-difficulty scatter: opponent power vs result margin
        st.markdown("<div class='lab-hdr'>Did they beat who they should?</div>",
                    unsafe_allow_html=True)
        pts_x, pts_y, pts_c, pts_h = [], [], [], []
        for g in log:
            pw = power_by.get(g["opp_id"])
            if pw is None:
                continue
            pts_x.append(pw)
            pts_y.append(g["margin"])
            pts_c.append(GOOD if g["won"] else BAD)
            pts_h.append(f"{g['opp']} (pwr {pw:.0f})")
        if pts_x:
            sd = go.Figure(go.Scatter(
                x=pts_x, y=pts_y, mode="markers",
                marker=dict(size=12, color=pts_c, line=dict(width=1,
                            color="#0d1117")),
                hovertext=pts_h,
                hovertemplate="%{hovertext}<br>Margin %{y:+d}<extra></extra>"))
            sd.add_hline(y=0, line=dict(color="#30363d"))
            sd.add_vline(x=50, line=dict(color="#30363d", dash="dot"),
                         annotation_text="league-avg opp")
            sd.update_xaxes(title="Opponent power →")
            sd.update_yaxes(title="Result margin")
            _style(sd, 380)
            st.plotly_chart(sd, width="stretch", key="adv_sched_scatter")
            st.caption("Green = win, red = loss. Points to the right are tougher "
                       "opponents; high-up wins over strong teams are the marquee "
                       "results, low losses to weak teams are the red flags.")

    # ───────────────────────────────────────── PLAYMAKING ───────────────────
    with adv_play:
        if not has_tracked:
            st.info("Tracked games needed for the passing network and possession "
                    "flow.")
        else:
            an = bundle["assist_network"]
            name_by = {p["_pid"]: f"#{p['number']}" for p in players}
            full_by = {p["_pid"]: p["name"] for p in players}

            # ── assist network ──────────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>Passing Network</div>",
                        unsafe_allow_html=True)
            am = st.columns(3)
            am[0].metric("Assisted FG%", _pctf(an["totals"]["ast_rate"]),
                         help="Share of made field goals that came off a pass.")
            am[1].metric("Total assists", an["totals"]["assisted"])
            am[2].metric("Made FGs", an["totals"]["made"])

            node_ids = [i for i in sorted(
                set(an["made_fg"]) | set(an["assists"]),
                key=lambda i: an["made_fg"].get(i, 0), reverse=True)
                if i in name_by]
            if len(node_ids) >= 2:
                n = len(node_ids)
                pos = {pid: (math.cos(2 * math.pi * k / n - math.pi / 2),
                             math.sin(2 * math.pi * k / n - math.pi / 2))
                       for k, pid in enumerate(node_ids)}
                net = go.Figure()
                max_ct = max((e["count"] for e in an["edges"]), default=1)
                for e in an["edges"]:
                    a, b = e["from"], e["to"]
                    if a not in pos or b not in pos:
                        continue
                    x0, y0 = pos[a]
                    x1, y1 = pos[b]
                    net.add_trace(go.Scatter(
                        x=[x0, x1], y=[y0, y1], mode="lines",
                        line=dict(width=1 + 5 * e["count"] / max_ct,
                                  color=f"rgba(0,229,255,"
                                        f"{0.25 + 0.5 * e['count'] / max_ct:.2f})"),
                        hoverinfo="text",
                        hovertext=f"{full_by.get(a,'?')} → {full_by.get(b,'?')}: "
                                  f"{e['count']} assists",
                        showlegend=False))
                made_sizes = [an["made_fg"].get(i, 0) for i in node_ids]
                mx = max(made_sizes) or 1
                net.add_trace(go.Scatter(
                    x=[pos[i][0] for i in node_ids],
                    y=[pos[i][1] for i in node_ids],
                    mode="markers+text",
                    marker=dict(
                        size=[20 + 34 * (an["made_fg"].get(i, 0) / mx)
                              for i in node_ids],
                        color=[an["assists"].get(i, 0) for i in node_ids],
                        colorscale="Plasma", showscale=True,
                        colorbar=dict(title="Assists"),
                        line=dict(width=2, color="#0d1117")),
                    text=[name_by[i] for i in node_ids],
                    textposition="middle center",
                    textfont=dict(size=10, color="#0d1117"),
                    hovertext=[f"{full_by.get(i,'?')}<br>"
                               f"{an['made_fg'].get(i,0)} made FG · "
                               f"{an['assists'].get(i,0)} ast given · "
                               f"{an['assisted_fgm'].get(i,0)} scored off a pass"
                               for i in node_ids],
                    hovertemplate="%{hovertext}<extra></extra>",
                    showlegend=False))
                net.update_xaxes(visible=False, range=[-1.45, 1.45])
                net.update_yaxes(visible=False, range=[-1.45, 1.45],
                                 scaleanchor="x", scaleratio=1)
                _style(net, 480)
                net.update_layout(plot_bgcolor="rgba(0,0,0,0)",
                                  margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(net, width="stretch", key="adv_network")
                st.caption("Node size = made field goals · node color = assists "
                           "handed out · arrow thickness = how often that passer "
                           "found that finisher. Hover for the full line.")

                top_edges = an["edges"][:8]
                if top_edges:
                    st.markdown("**Top passing connections**")
                    st.dataframe(pd.DataFrame([{
                        "Passer": full_by.get(e["from"], "?"),
                        "Finisher": full_by.get(e["to"], "?"),
                        "Assists": e["count"], "Points created": e["pts"],
                    } for e in top_edges]), hide_index=True, width="stretch")
            else:
                st.caption("Not enough assisted baskets to draw a network yet.")

            # ── possession-outcome Sankey ───────────────────────────────────
            st.markdown("<div class='lab-hdr'>How Every Possession Ends</div>",
                        unsafe_allow_html=True)
            po = bundle["poss_outcomes"]
            st.plotly_chart(_poss_sankey(po, ACCENT), width="stretch",
                            key="adv_sankey")
            pm = st.columns(4)
            shots = po["twos"]["make"] + po["twos"]["miss"] + \
                po["threes"]["make"] + po["threes"]["miss"]
            pm[0].metric("Possessions", po["total"])
            pm[1].metric("End in a shot", _pctf(S._safe(shots, po["total"])))
            pm[2].metric("End in a turnover",
                         _pctf(S._safe(po["tov"], po["total"])))
            scored_poss = po["twos"]["make"] + po["threes"]["make"]
            pm[3].metric("Possessions that score",
                         _pctf(S._safe(scored_poss, po["total"])),
                         help="Field goals only (free-throw trips excluded).")
            st.caption("A possession is one shot or one turnover (the locked "
                       "rule). Free-throw trips aren't possessions, so they don't "
                       "appear here.")

            # ── scoring balance ─────────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>Scoring Balance</div>",
                        unsafe_allow_html=True)
            scorers = sorted([p for p in players if (p["PTS"] or 0) > 0],
                             key=lambda p: p["PTS"], reverse=True)
            tot_pts = sum(p["PTS"] for p in scorers)
            if scorers and tot_pts:
                shares = [p["PTS"] / tot_pts for p in scorers]
                hhi = sum(s * s for s in shares)
                eff_scorers = 1 / hhi
                nbal = len(shares)
                balance_idx = (round(100 * (eff_scorers - 1) / (nbal - 1))
                               if nbal > 1 else 100)
                top_share = shares[0] * 100
                bc1, bc2 = st.columns([1, 2])
                with bc1:
                    st.markdown(
                        f"<div class='spotlight'>"
                        f"<div class='spotlight-num' style='color:{CYBER}'>"
                        f"{eff_scorers:.1f}</div>"
                        f"<div class='spotlight-lbl'>Effective scorers</div>"
                        f"<div class='spotlight-sub'>Balance index "
                        f"{balance_idx}/100 · top scorer carries "
                        f"{top_share:.0f}%</div></div>",
                        unsafe_allow_html=True)
                    st.caption("Effective scorers = inverse-Herfindahl of the "
                               "point distribution: how many players the offense "
                               "*effectively* leans on. Higher = more balanced.")
                with bc2:
                    top8 = scorers[:8]
                    bal = go.Figure(go.Bar(
                        x=[p["PTS"] / tot_pts * 100 for p in reversed(top8)],
                        y=[f"#{p['number']} {p['name']}" for p in reversed(top8)],
                        orientation="h",
                        marker=dict(color=[p["PTS"] / tot_pts * 100
                                           for p in reversed(top8)],
                                    colorscale="Tealgrn", showscale=False),
                        text=[f"{p['PTS'] / tot_pts * 100:.0f}%"
                              for p in reversed(top8)], textposition="auto"))
                    bal.update_xaxes(title="Share of team points %")
                    _style(bal, 300)
                    bal.update_layout(margin=dict(l=4, r=14, t=8, b=30))
                    st.plotly_chart(bal, width="stretch", key="adv_balance")

    # ───────────────────────────────────────── GAME FLOW ────────────────────
    with adv_flow:
        if not has_tracked:
            st.info("Tracked games needed to reconstruct the score flow.")
        else:
            st.markdown("<div class='lab-hdr'>Score-Flow Explorer</div>",
                        unsafe_allow_html=True)
            tracked_games = [g for g in log if g["tracked"]]
            glabels = [f"{g['date']}  {g['site']} {g['opp']}  "
                       f"({'W' if g['won'] else 'L'} {g['pf']}-{g['pa']})"
                       for g in tracked_games]
            gi = st.selectbox("Tracked game", range(len(tracked_games)),
                              format_func=lambda i: glabels[i], key="adv_flow_game")
            gsel = tracked_games[gi]
            flow = TA.score_flow(team_id, gsel["game_id"])
            pts = flow["points"]
            xs = [p["t"] for p in pts]
            mg = [p["margin"] for p in pts]
            fl = go.Figure()
            # quarter boundary lines (8-min Q, 4-min OT)
            last_q = max((p["q"] for p in pts), default=4)
            for q in range(1, last_q):
                bx = TA._period_start(q + 1) / 60.0
                fl.add_vline(x=bx, line=dict(color="#30363d", dash="dot"))
            fl.add_trace(go.Scatter(
                x=xs, y=mg, mode="lines", line=dict(color=CYBER, width=2.5),
                fill="tozeroy", fillcolor="rgba(0,229,255,0.12)",
                hovertemplate="%{x:.1f} min · margin %{y:+d}<extra></extra>",
                name="Margin"))
            fl.add_hline(y=0, line=dict(color=GREY))
            fl.update_xaxes(title="Minutes elapsed")
            fl.update_yaxes(title=f"{team['name']} margin")
            _style(fl, 420)
            st.plotly_chart(fl, width="stretch", key="adv_flow_chart")

            fc = st.columns(5)
            fc[0].metric("Final", f"{flow['final']['team']}-"
                         f"{flow['final']['opp']}")
            fc[1].metric("Biggest lead", f"+{flow['lead']['max']}")
            fc[2].metric("Biggest deficit", f"{flow['lead']['min']}")
            fc[3].metric("Best run", f"{flow['runs']['team']}-0",
                         help="Most points scored without the opponent answering.")
            fc[4].metric("Worst run faced", f"0-{flow['runs']['opp']}")
            st.caption("Cyan area above the line = leading, below = trailing. "
                       "Dotted lines mark quarter breaks. Reconstructed from made "
                       "shots & free throws.")

    # ───────────────────────────────────────── SHOT LAB ─────────────────────
    with adv_shot:
        if not has_tracked:
            st.info("Tracked games needed for shot-quality analytics.")
        else:
            zo = bundle["zones"]["off"]
            zxfg = bundle["zone_xfg"]
            exp_fgm = sum(zo[z]["FGA"] * zxfg[z]["xFG%"] for z in TA.ZONES)
            act_fgm = sum(zo[z]["FGM"] for z in TA.ZONES)
            z_fga = sum(zo[z]["FGA"] for z in TA.ZONES)
            smoe = (act_fgm - exp_fgm) / z_fga * 100 if z_fga else 0
            xfg_avg = exp_fgm / z_fga if z_fga else 0

            st.markdown("<div class='lab-hdr'>Shot-Making vs Expectation</div>",
                        unsafe_allow_html=True)
            sc1, sc2 = st.columns([1, 2])
            with sc1:
                clr = GOOD if smoe >= 0 else BAD
                st.markdown(
                    f"<div class='spotlight'>"
                    f"<div class='spotlight-num' style='color:{clr}'>"
                    f"{smoe:+.1f}%</div>"
                    f"<div class='spotlight-lbl'>FG% over expected</div>"
                    f"<div class='spotlight-sub'>made {act_fgm:.0f} vs "
                    f"{exp_fgm:.0f} expected on {z_fga:.0f} shots</div></div>",
                    unsafe_allow_html=True)
                st.caption("SMOE — Shot-Making Over Expected. Expected makes come "
                           "from the league-wide make-rate of each shot's "
                           "(zone · creation · contest) type. Positive = they "
                           "finish better than the looks they generate.")
            with sc2:
                diffs = [(TA.ZONE_LABELS[z],
                          (zo[z]["FG%"] - zxfg[z]["xFG%"]) * 100,
                          zo[z]["FGA"]) for z in TA.ZONES]
                sm2 = go.Figure(go.Bar(
                    x=[d[0] for d in diffs], y=[d[1] for d in diffs],
                    marker_color=[GOOD if d[1] >= 0 else BAD for d in diffs],
                    marker_line_width=0,
                    text=[f"{d[1]:+.0f}pp" for d in diffs], textposition="auto",
                    hovertext=[f"{d[2]} FGA" for d in diffs],
                    hovertemplate="%{x}<br>%{y:+.1f}pp vs expected<br>"
                                  "%{hovertext}<extra></extra>"))
                sm2.add_hline(y=0, line=dict(color="#30363d"))
                sm2.update_yaxes(title="Actual − expected FG% (pp)")
                sm2.update_xaxes(tickangle=-25)
                _style(sm2, 340)
                st.plotly_chart(sm2, width="stretch", key="adv_smoe")

            st.markdown("<div class='lab-hdr'>Shot Quality Profile</div>",
                        unsafe_allow_html=True)
            qm = st.columns(4)
            qm[0].metric("Avg look quality (xFG%)", _pctf(xfg_avg),
                         help="Expected FG% of the shots they generate — higher "
                              "means easier looks on average.")
            qm[1].metric("Points / shot", f"{S.pps(tb):.2f}",
                         help="Field-goal points per FGA (free throws excluded).")
            qm[2].metric("Scoring efficiency (SCE)",
                         f"{S.shot_efficiency(tb):.3f}")
            qm[3].metric("Contested rate",
                         _pctf(bundle["guarded"]["guard_share"]))
            st.caption("Look quality measures the difficulty of shots created; "
                       "shot-making over expected measures whether they convert "
                       "them. A great offense does both.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7 — INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_insights:
    if not has_tracked:
        st.info("No tracked games yet — insights are built from play-by-play "
                "data captured in the Game Tracker.")
    else:
        st.caption("Scouting tips built around the Four Factors (the four things "
                   "that decide basketball games) plus the 2s-vs-3s question.")

        league = _league_ff(gender)
        off_pool = {k: [v["off"][k] for v in league.values()]
                    for k in ["eFG", "TOV", "ORB", "FTR"]}
        def_pool = {k: [v["def"][k] for v in league.values()]
                    for k in ["eFG", "TOV", "ORB", "FTR"]}

        OFF_HB = {"eFG": True, "TOV": False, "ORB": True, "FTR": True}
        DEF_HB = {"eFG": False, "TOV": True, "ORB": False, "FTR": False}

        st.markdown("<div class='lab-hdr'>Four factors — vs the league</div>",
                    unsafe_allow_html=True)
        ff_rows = []
        for side, pool, hb, lbl in (("off", off_pool, OFF_HB, "Offense"),
                                    ("def", def_pool, DEF_HB, "Defense")):
            for k in ["eFG", "TOV", "ORB", "FTR"]:
                val = ff[side][k]
                pct = TA.percentile(val, pool[k], higher_better=hb[k])
                ff_rows.append({
                    "Side": lbl, "Factor": FF_LABELS[k],
                    "Value": f"{val*100:.1f}%",
                    "Pctile": pct if pct is not None else 0,
                    "Read": ("Strength" if pct is not None and pct >= 70
                             else "Weakness" if pct is not None and pct <= 30
                             else "Average"),
                })
        fdf = pd.DataFrame(ff_rows)
        st.dataframe(
            fdf, hide_index=True, width="stretch",
            column_config={"Pctile": st.column_config.ProgressColumn(
                "Pctile", format="%d", min_value=0, max_value=100)})
        st.caption("Pctile = where this team ranks in the league on that factor "
                   "(100 = best). eFG% ≈ 40% of winning, TOV% ≈ 25%, "
                   "OREB% ≈ 20%, FT rate ≈ 15%.")

        strengths = [r for r in ff_rows if r["Read"] == "Strength"]
        weaks = [r for r in ff_rows if r["Read"] == "Weakness"]
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("**✅ Major strengths**")
            if strengths:
                for r in sorted(strengths, key=lambda x: -x["Pctile"]):
                    st.markdown(f"- **{r['Side']} {r['Factor']}** — {r['Value']} "
                                f"({r['Pctile']:.0f}th pct)")
            else:
                st.caption("Nothing above the 70th percentile yet.")
        with sc2:
            st.markdown("**⚠️ Address these**")
            if weaks:
                for r in sorted(weaks, key=lambda x: x["Pctile"]):
                    st.markdown(f"- **{r['Side']} {r['Factor']}** — {r['Value']} "
                                f"({r['Pctile']:.0f}th pct)")
            else:
                st.caption("No factor below the 30th percentile — well-rounded.")

        st.markdown("<div class='lab-hdr'>Should they shoot more 3s or 2s?"
                    "</div>", unsafe_allow_html=True)
        bm = st.columns(4)
        bm[0].metric("2P%", _pctf(brk["2P%"]))
        bm[1].metric("3P%", _pctf(brk["3P%"]))
        bm[2].metric("Breakeven 3P%", _pctf(brk["be3"]),
                     help="The 3P% at which a three equals their current two.")
        bm[3].metric("3PA rate", _pctf(brk["3PAr"]),
                     help="Share of FG attempts that are threes.")

        evfig = go.Figure(go.Bar(
            x=["Per 2-pt attempt", "Per 3-pt attempt"],
            y=[brk["ev2"], brk["ev3"]],
            marker_color=[ACCENT, BLUE], marker_line_width=0,
            text=[f"{brk['ev2']:.2f}", f"{brk['ev3']:.2f}"],
            textposition="auto"))
        evfig.update_yaxes(title="Expected points per attempt")
        _style(evfig, 300)
        st.plotly_chart(evfig, width="stretch", key="in_ev")

        diff = brk["edge"]
        if abs(diff) < 0.03:
            st.info(
                f"Their 2s and 3s pay off **about equally** ({brk['ev3']:.2f} vs "
                f"{brk['ev2']:.2f} pts/shot). Shot selection is balanced — keep "
                "taking the open look.")
        elif diff > 0:
            st.success(
                f"**Shoot more 3s.** Each three returns {brk['ev3']:.2f} pts vs "
                f"{brk['ev2']:.2f} for a two — a **+{diff:.2f}** edge. They clear "
                f"the {brk['be3']*100:.0f}% breakeven ({brk['3P%']*100:.0f}% "
                f"actual) and only {brk['3PAr']*100:.0f}% of their shots are "
                "threes.")
        else:
            st.warning(
                f"**Shoot more 2s.** A two returns {brk['ev2']:.2f} pts vs "
                f"{brk['ev3']:.2f} for a three ({diff:.2f}). Their "
                f"{brk['3P%']*100:.0f}% from deep is below the "
                f"{brk['be3']*100:.0f}% breakeven — work for higher-value twos, "
                f"especially in the paint ({soff['pct_paint']*100:.0f}% of points "
                "come there).")

        # ── per-player 3-point profile ───────────────────────────────────────
        st.markdown("<div class='lab-hdr'>Per-player 3-point profile</div>",
                    unsafe_allow_html=True)
        three_p = [p for p in players if p["3PA"] and p["3PA"] >= 4]
        if three_p:
            be3_pct = brk["be3"] * 100
            tp = go.Figure()
            tp.add_trace(go.Bar(
                x=[f"#{p['number']} {p['name']}" for p in
                   sorted(three_p, key=lambda p: p["3PA"], reverse=True)],
                y=[p["3P%"] for p in
                   sorted(three_p, key=lambda p: p["3PA"], reverse=True)],
                marker_color=[GOOD if (p["3P%"] or 0) >= be3_pct else BAD
                              for p in sorted(three_p, key=lambda p: p["3PA"],
                                              reverse=True)],
                marker_line_width=0,
                text=[f"{p['3P%']:.0f}% ({p['3PA']} att)" for p in
                      sorted(three_p, key=lambda p: p["3PA"], reverse=True)],
                textposition="auto"))
            tp.add_hline(y=be3_pct, line=dict(color=ACCENT, dash="dot"),
                         annotation_text=f"breakeven {be3_pct:.0f}%")
            tp.update_yaxes(title="3P%")
            tp.update_xaxes(tickangle=-30)
            _style(tp, 320)
            st.plotly_chart(tp, width="stretch", key="in_3pt")
            st.caption("Green = above the team's breakeven 3P% (their threes beat "
                       "their twos); red = below. Min 4 attempts.")
        else:
            st.caption("Not enough 3-point volume to profile shooters yet.")

        # ── auto scouting report ─────────────────────────────────────────────
        st.markdown("<div class='lab-hdr'>Scouting report</div>",
                    unsafe_allow_html=True)
        tips = []
        # offense
        if ff["off"]["eFG"] >= 0.50:
            tips.append("🟢 **Efficient shooting team** — eFG% "
                        f"{_pctf(ff['off']['eFG'])}; contest everything and keep "
                        "them off the offensive glass.")
        elif ff["off"]["eFG"] <= 0.42:
            tips.append("🔴 **Below-average shooting** — eFG% "
                        f"{_pctf(ff['off']['eFG'])}; pack the paint and live with "
                        "contested jumpers.")
        if ff["off"]["TOV"] >= 0.18:
            tips.append("🔴 **Turnover-prone** — gives it away on "
                        f"{_pctf(ff['off']['TOV'])} of trips; pressure the ball "
                        "to force live-ball turnovers.")
        if ff["off"]["ORB"] >= 0.33:
            tips.append("🟢 **Crashes the offensive glass** — OREB% "
                        f"{_pctf(ff['off']['ORB'])}; box out and secure the "
                        "first rebound.")
        if soff["pct_paint"] >= 0.50:
            tips.append("🟠 **Paint-heavy offense** — "
                        f"{_pctf(soff['pct_paint'])} of points in the paint; wall "
                        "up the rim and make them prove the jumper.")
        elif brk["3PAr"] >= 0.40:
            tips.append("🟠 **Lives behind the arc** — "
                        f"{_pctf(brk['3PAr'])} of shots are threes; run them off "
                        "the line.")
        # defense
        if ff["def"]["TOV"] >= 0.18:
            tips.append("🟢 **Forces turnovers** — takes it away on "
                        f"{_pctf(ff['def']['TOV'])} of opponent trips; value "
                        "every possession and limit careless passes.")
        if ff["def"]["eFG"] <= 0.44:
            tips.append("🟢 **Locks down shots** — holds opponents to "
                        f"{_pctf(ff['def']['eFG'])} eFG; attack early before the "
                        "defense sets.")
        # tempo
        pace = summ.get("POSS_pg", 0)
        if pace >= 70:
            tips.append("⚡ **Plays fast** — "
                        f"{pace:.0f} possessions/game; control tempo to shorten "
                        "the game if you're the underdog.")
        elif pace and pace < 60:
            tips.append("🐢 **Slow, deliberate pace** — "
                        f"{pace:.0f} possessions/game; speed them up to drag them "
                        "out of their comfort zone.")
        # leaning on a star
        rated_pl = [p for p in players if p["PPG"] is not None]
        if rated_pl:
            top = max(rated_pl, key=lambda p: p["PPG"])
            share = top["PTS"] / max(tb["PTS"], 1)
            if share >= 0.28:
                tips.append(f"🎯 **Star-dependent** — #{top['number']} "
                            f"{top['name']} scores {share*100:.0f}% of the team's "
                            "points; key on them and force someone else to beat "
                            "you.")
        if tips:
            for t in tips:
                st.markdown(f"- {t}")
        else:
            st.caption("A balanced profile — no single factor stands out as a "
                       "scouting key.")

        st.markdown("<div class='lab-hdr'>Efficiency summary</div>",
                    unsafe_allow_html=True)
        st.markdown(
            f"- **Offense:** {summ.get('ORtg', 0):.1f} pts / 100 poss on "
            f"{_pctf(ff['off']['eFG'])} eFG; turns it over on "
            f"{_pctf(ff['off']['TOV'])} of trips and rebounds "
            f"{_pctf(ff['off']['ORB'])} of its own misses.")
        st.markdown(
            f"- **Defense:** {summ.get('DRtg', 0):.1f} pts / 100 poss allowed on "
            f"{_pctf(ff['def']['eFG'])} eFG; forces a turnover on "
            f"{_pctf(ff['def']['TOV'])} of opponent trips.")
        st.markdown(
            f"- **Tempo:** {summ.get('POSS_pg', 0):.1f} possessions/game — "
            + ("an up-tempo team." if summ.get("POSS_pg", 0) >= 70
               else "a controlled pace." if summ.get("POSS_pg", 0) >= 60
               else "a slow, grind-it-out pace."))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 8 — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_gloss:
    st.markdown("<div class='lab-hdr'>Team analytics glossary</div>",
                unsafe_allow_html=True)
    render_glossary(
        key_prefix="ta_gloss",
        categories=["Team & League", "Possession & Pace", "Shooting",
                    "Rebounding", "Defense", "Advanced", "Shot Quality"],
        intro="Every team metric on this page — Four Factors, efficiency ratings, "
              "shot quality and the signature invented stats (SMOE, Scoring "
              "Balance). Search by name or filter by category.")
