"""
5_Team_Dashboard.py — the single-team deep dive.

Pick one team and read everything about it across these tabs:

  • Overview   — a coach's one-glance card: record, power ratings, best players,
                 four-factor snapshot, scoring mix and the margin trend.
  • Players    — the roster localized: ratings compared, leader bars, a scatter
                 map and shot-selection breakdown. (The lineup simulator now lives
                 under Helper → Lineup.)
  • Schedule   — the full schedule, record vs each class, and any tracked game's
                 complete box score on demand.
  • Charts     — the analytics wall (Scoring · Shooting · Rebounding · Defense ·
                 Trends), plus three deeper sub-tabs folded in here: Quarters
                 (every stat split by quarter), Advanced (the efficiency / DNA /
                 résumé / playmaking / flow lab) and Build (a free-form chart lab).
  • Scout      — game-day scouting report: keys to guard / attack, four-factor
                 tendencies, the 2s-vs-3s breakeven, personnel cards, hot zones
                 and a printable sheet (folds in the old Scout Report page).

All math lives in helpers/team_analytics.py (+ stats / team_ratings /
player_ratings / scout); this page is display + controls only.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import html
import math
from collections import defaultdict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from database.db import query, execute
from helpers.settings_utils import get_setting
from helpers.box_score import render_box_score
from helpers.ui import (page_chrome, rgb as _rgb, style_fig as _style,
                        q_label as _q_label, empty_state, gender_radio,
                        gender_label, grid as _grid, AWAY, CARD_BG, GRID)
from helpers.cards import (fmt as _fmt, pctile as _pctile,
                           pctile_bar as _pctile_bar,
                           tier as _tier, glass as _glass, onoff_html as _onoff_html,
                           gauge_dial as _pp_gauge, gauge_range, bar_h)
from helpers.court import shot_chart as _shot_chart, hot_zones as _hot_zones
from helpers.glossary import glossary_tab
import helpers.team_analytics as TA
import helpers.team_ratings as TR
import helpers.stats as S
import helpers.player_ratings as PR
import helpers.league_analytics as LA
import helpers.scout as SC
import helpers.archetypes as AR
import helpers.badges as BG
import helpers.predictor as PRED
import helpers.rapm as RA
import helpers.wpa as WP
import helpers.networks as NW
import helpers.lineups as LU
import helpers.playtypes as PT
import helpers.matchups as MU
import helpers.gameflow as GF
import helpers.fouls as FL
import helpers.manual_box as MB
import helpers.scoutboard as SB

_cfg, ACCENT = page_chrome()
GOOD = "#3fb950"
BAD = "#e74c3c"
BLUE = "#58a6ff"
PURPLE = "#bc8cff"
GREY = "#8b949e"
CYBER = "#00e5ff"
PINK = "#ff5db1"
# Distinct, repeatable colour cycle for the multi-series Build-your-own charts.
PALETTE = [ACCENT, BLUE, PURPLE, GOOD, "#d29922", PINK, CYBER, "#56d4dd",
           AWAY, GREY]
RATING_COLS = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]
# every glossary rating that exists per-player (numeric, 0-100) — the roster table
RATING_COLS_ALL = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING",
                   "Shooting", "Finishing", "2WAY", "VERSATILITY"]

# Player leaderboard catalogue, grouped by glossary category. Each entry is
# (display label, player-row key, format kind: f0/f1/f2/pct). One leaderboard is
# drawn per entry. Covers every per-player stat the app computes.
PLAYER_LEADER_GROUPS = [
    ("Scoring & shooting", [
        ("Points / game", "PPG", "f1"), ("Total points", "PTS", "f0"),
        ("FG%", "FG%", "pct"), ("2P%", "2P%", "pct"), ("3P%", "3P%", "pct"),
        ("FT%", "FT%", "pct"), ("eFG%", "eFG%", "pct"), ("TS%", "TS%", "pct"),
        ("Paint FG%", "Paint%", "pct"), ("3-pt rate", "3PR", "pct"),
        ("Points / shot", "PPS", "f2"), ("Pts / scoring att", "PPSA", "f2"),
        ("FT rate", "FTR", "f2"), ("Paint points", "PaintPTS", "f0"),
    ]),
    ("Playmaking & creation", [
        ("Assists / game", "APG", "f1"), ("Assists", "AST", "f0"),
        ("Assist-to-TO", "AST/TOV", "f2"), ("Usage %", "USG%", "pct"),
        ("Turnover %", "TOV%", "pct"), ("Shot creation (SC)", "SC", "f0"),
        ("Pts responsible for /g", "PRF/G", "f1"),
        ("SC Shot %", "SCShot%", "pct"), ("SC Pass %", "SCPass%", "pct"),
        ("SC Created %", "SCCreated%", "pct"),
        ("Self-created %", "SelfCr%", "pct"), ("Assisted %", "Astd%", "pct"),
    ]),
    ("Rebounding", [
        ("Rebounds / game", "RPG", "f1"), ("OREB / game", "OREB/G", "f1"),
        ("DREB / game", "DREB/G", "f1"), ("REB %", "REB%", "pct"),
        ("OREB %", "OREB%", "pct"), ("DREB %", "DREB%", "pct"),
    ]),
    ("Defense", [
        ("Steals / game", "SPG", "f1"), ("Blocks / game", "BPG", "f1"),
        ("Stocks / game", "STOCKS/G", "f1"), ("Stocks / 32", "STOCKS/32", "f1"),
        ("Contest rate", "Guarded%", "pct"), ("Defended FG%", "DSHOT%", "pct"),
    ]),
    ("Ratings", [
        ("Overall", "OVERALL", "f0"), ("Offense", "OFFENSE", "f0"),
        ("Defense", "DEFENSE", "f0"), ("Playmaking", "PLAYMAKING", "f0"),
        ("Rebounding", "REBOUNDING", "f0"), ("Shooting", "Shooting", "f0"),
        ("Finishing", "Finishing", "f0"), ("Two-way", "2WAY", "f1"),
        ("Versatility", "VERSATILITY", "f1"),
    ]),
    ("Advanced & impact", [
        ("Game Score /g", "GS/G", "f1"), ("Efficiency (EFF)", "EFF", "f0"),
        ("Floor Impact (FIC)", "FIC", "f0"), ("Minutes / game", "MPG", "f1"),
        ("Plus / minus", "+/-", "f0"), ("Pts / poss", "PPP", "f2"),
        ("Shot Rating", "ShotRating", "f1"), ("Expected FG%", "xFG%", "pct"),
        ("Expected PPS", "xPPS", "f2"), ("Shot-making over exp", "SMOE", "f1"),
        ("Q4 points / game", "Q4PPG", "f1"), ("Double-doubles", "DD", "f0"),
    ]),
]


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


def _is_num(v):
    """True for plottable numbers (ints/floats) — bools and None are excluded."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _norm01(s):
    """Scale a pandas Series onto 0–100 across its own min/max (flat → 50)."""
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return s.apply(lambda _: 50.0)
    return (s - lo) / (hi - lo) * 100


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
    return bar_h(names, vals, texts, color, height)


def _per_game_line(per_game, key, title, color=ACCENT, height=240):
    """One per-game line chart for a single stat, with a straight-average line."""
    x = [r["label"] for r in per_game]
    y = [r["stats"].get(key) for r in per_game]
    present = [v for v in y if v is not None]
    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="lines+markers", line=dict(color=color, width=2.5),
        marker=dict(size=6), connectgaps=True,
        hovertemplate="%{x}<br>%{y:.1f}<extra></extra>"))
    if present:
        avg = sum(present) / len(present)
        fig.add_hline(y=avg, line=dict(color=GREY, dash="dot"),
                      annotation_text=f"avg {avg:.1f}")
    fig.update_yaxes(title=title)
    fig.update_xaxes(tickangle=-40)
    _style(fig, height)
    return fig


def _per_game_stat_grid(per_game, spec, key_prefix, ncols=2):
    """Render an individual per-game line chart for every stat in `spec`
    (list of (label, key, higher_better)), 2 per row. Straight averages only."""
    cols = st.columns(ncols)
    ci = 0
    for label, key, hib in spec:
        if not any(r["stats"].get(key) is not None for r in per_game):
            continue
        with cols[ci % ncols]:
            st.markdown(f"**{label}**")
            st.plotly_chart(
                _per_game_line(per_game, key, label,
                               color=ACCENT if hib else AWAY),
                width="stretch", key=f"{key_prefix}_{key}")
        ci += 1


def _fmt_for(kind):
    """Value formatter for leaderboard labels by kind tag."""
    if kind == "pct":
        return lambda v: _pctf(v / 100)
    if kind == "f2":
        return lambda v: f"{v:.2f}"
    if kind == "f0":
        return lambda v: f"{v:.0f}"
    return lambda v: f"{v:.1f}"   # f1 default


def _player_leaderboards(players, spec, key_prefix, ncols=2):
    """For each (label, key, kind) in spec, a sorted horizontal leaderboard of
    the roster on that stat. Skips stats no player has."""
    cols = st.columns(ncols)
    ci = 0
    for label, key, kind in spec:
        pool = [p for p in players if _is_num(p.get(key))]
        if not pool:
            continue
        pool = sorted(pool, key=lambda p: p[key], reverse=True)
        fmt_fn = _fmt_for(kind)
        with cols[ci % ncols]:
            st.markdown(f"**{label}**")
            st.plotly_chart(
                _leader_bar(pool, key,
                            lambda r: f"#{r['number']} {r['name']}",
                            lambda r, k=key: r[k], fmt_fn,
                            height=max(170, 24 * len(pool) + 40)),
                width="stretch", key=f"{key_prefix}_{key}")
        ci += 1


def _zone_pair_bars(zmap_a, zmap_b, name_a, name_b, value_fn, yaxis,
                    color_a=ACCENT, color_b=BLUE, height=300, text_fn=None):
    """Grouped bar over the 5 zones comparing two per-zone agg maps (e.g. 2s vs
    3s, or actual vs expected). value_fn(agg) -> number; text_fn optional."""
    zl = [TA.ZONE_LABELS[z].split("/")[0].strip() for z in TA.ZONES]
    fig = go.Figure()
    for nm, zmap, clr in ((name_a, zmap_a, color_a), (name_b, zmap_b, color_b)):
        ys = [value_fn(zmap[z]) for z in TA.ZONES]
        kw = dict(name=nm, x=zl, y=ys, marker_color=clr, marker_line_width=0)
        if text_fn:
            kw["text"] = [text_fn(zmap[z]) for z in TA.ZONES]
            kw["textposition"] = "auto"
        fig.add_trace(go.Bar(**kw))
    fig.update_layout(barmode="group")
    fig.update_yaxes(title=yaxis)
    fig.update_xaxes(tickangle=-25)
    _style(fig, height)
    return fig


def _gauge(value, vmin, vmax, label, suffix="", good_high=True, ref=None,
           height=210):
    """League-range gauge (helpers.cards.gauge_range) with the page accent bar."""
    return gauge_range(value, vmin, vmax, label, suffix=suffix, good_high=good_high,
                       ref=ref, height=height, accent=ACCENT)


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

st.title("Team Dashboard")

# Default team comes from Settings. Look up its league so the gender radio
# opens on the right side — otherwise a Boys default is filtered out of the
# (Girls-first) list and the default silently never applies.
default_team = get_setting("default_team", "")
_dt_rows = query("SELECT gender FROM teams WHERE name=?", (default_team,)) \
    if default_team else []
default_gender = _dt_rows[0]["gender"] if _dt_rows else "F"

c1, c2 = st.columns([1, 3])
gender = gender_radio(c1, default=default_gender)

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


@st.cache_data(ttl=600, show_spinner=False)
def _league_stat_pools(g):
    """{team_id: {stat_key: value}} over tracked games for every team in the
    league — the pool that lets the Overview say where THIS team ranks and how
    it compares to the league average (the APP3-style league-aligned detail).
    One box pass per tracked game (shared with the four-factors helper)."""
    games = TR._finished_games(gender=g, tracked_only=True)
    if not games:
        return {}
    boxes = TR._tracked_team_game_boxes(games)        # {(gid, tid): box}
    sides = defaultdict(set)
    for (gid, tid) in boxes:
        sides[gid].add(tid)
    tbx = defaultdict(lambda: S.finalize_box(S._blank_box()))
    obx = defaultdict(lambda: S.finalize_box(S._blank_box()))
    gpc = defaultdict(int)
    for (gid, tid), b in boxes.items():
        for k in tbx[tid]:
            tbx[tid][k] += b.get(k, 0)
        gpc[tid] += 1
        for other in sides[gid]:
            if other != tid:
                ob = boxes.get((gid, other))
                if ob:
                    for k in obx[tid]:
                        obx[tid][k] += ob.get(k, 0)
    out = {}
    for tid in tbx:
        tb_, ob_ = tbx[tid], obx[tid]
        op = S.estimate_possessions(tb_)
        dp = S.estimate_possessions(ob_)
        gp_ = gpc[tid] or 1
        ff_ = TA.four_factors(tb_, ob_)
        ortg = 100 * tb_["PTS"] / op if op else 0.0
        drtg = 100 * ob_["PTS"] / dp if dp else 0.0
        out[tid] = {
            "ortg": ortg, "drtg": drtg, "net": ortg - drtg,
            "pace": (op + dp) / 2 / gp_,
            "ppp": tb_["PTS"] / op if op else 0.0,
            "oppp": ob_["PTS"] / dp if dp else 0.0,
            "efg": S.efg(tb_), "oefg": S.efg(ob_),
            "ts": S.ts(tb_), "ots": S.ts(ob_),
            "fg": S.fg_pct(tb_), "tp": S.fg3_pct(tb_), "ft": S.ft_pct(tb_),
            "paint": S.paint_fg_pct(tb_),
            "ast_tov": tb_["AST"] / tb_["TOV"] if tb_["TOV"] else 0.0,
            "stl_rate": 100 * tb_["STL"] / dp if dp else 0.0,
            # four factors — offense + what they allow
            "tov": ff_["off"]["TOV"], "orb": ff_["off"]["ORB"],
            "ftr": ff_["off"]["FTR"],
            "opp_tov": ff_["def"]["TOV"], "opp_orb": ff_["def"]["ORB"],
            "opp_ftr": ff_["def"]["FTR"],
            "dreb": (tb_["DRB"] / (tb_["DRB"] + ob_["ORB"])
                     if (tb_["DRB"] + ob_["ORB"]) else 0.0),
            "gp": gpc[tid],
        }
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _zone_player_shooting(tid, _ids):
    """Per-zone, per-player located shooting over the team's tracked games,
    split by shot value (2-pointers vs 3-pointers).

    Returns {'2': view, '3': view, 'all': view} where each view is
        {'zones': {zone: [rows sorted by FGA desc]},
         'players': [ {pid,name,number,total_FGA, by_zone:{zone:{FGA,FGM,pct}}} ]}
    so the Players tab can show who shoots WHERE the most (volume) and who
    shoots BEST there (FG%), separately for 2s and 3s. None with no tracked games."""
    if not _ids:
        return None
    zs = S.player_zone_splits(game_ids=list(_ids))
    meta = {r["id"]: r for r in query(
        "SELECT id, name, number FROM players WHERE team_id=?", (tid,))}

    def _build(stypes):
        per_zone = {z: [] for z in TA.ZONES}
        players_out = []
        for pid, m in meta.items():
            cells = zs.get(pid, {})
            by_zone = {}
            tot = 0
            for z in TA.ZONES:
                fga = sum(c["FGA"] for (zz, st_), c in cells.items()
                          if zz == z and st_ in stypes)
                fgm = sum(c["FGM"] for (zz, st_), c in cells.items()
                          if zz == z and st_ in stypes)
                pct = fgm / fga if fga else 0.0
                by_zone[z] = {"FGA": fga, "FGM": fgm, "pct": pct}
                tot += fga
                if fga > 0:
                    per_zone[z].append({"pid": pid, "name": m["name"],
                                        "number": m["number"], "FGA": fga,
                                        "FGM": fgm, "pct": pct})
            if tot > 0:
                players_out.append({"pid": pid, "name": m["name"],
                                    "number": m["number"], "total_FGA": tot,
                                    "by_zone": by_zone})
        for z in TA.ZONES:
            per_zone[z].sort(key=lambda r: r["FGA"], reverse=True)
        players_out.sort(key=lambda r: r["total_FGA"], reverse=True)
        return {"zones": per_zone, "players": players_out}

    return {"2": _build((2,)), "3": _build((3,)), "all": _build((2, 3))}


@st.cache_data(ttl=600, show_spinner=False)
def _pack(g, _trk):
    # _trk (dict) is underscore-prefixed so Streamlit skips hashing it; keyed on g.
    return LA.team_tracked_pack(gender=g, tracked=_trk)


@st.cache_data(ttl=600, show_spinner=False)
def _ptable_full(g):
    return PR.player_stat_table(gender=g, min_games=1)


@st.cache_data(ttl=600, show_spinner=False)
def _archetypes(g):
    """{player_id: archetype label} across the league pool (for the roster table)."""
    res = AR.cluster_players(_ptable_full(g))
    return {pid: v["archetype"] for pid, v in res["players"].items()}


@st.cache_data(ttl=600, show_spinner=False)
def _badges(g):
    """{player_id: [badge, ...]} (NBA-2K-style) across the league pool."""
    return BG.award_badges(_ptable_full(g))


@st.cache_data(ttl=600, show_spinner=False)
def _gender_tracked_ids(g):
    """All tracked, completed game ids for a gender (the RAPM/WPA possession pool)."""
    rows = query(
        """SELECT g.id FROM games g JOIN teams t ON t.id = g.team1_id
           WHERE g.tracked = 1 AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL AND t.gender = ?""", (g,))
    return [r["id"] for r in rows]


@st.cache_data(ttl=600, show_spinner=False)
def _rapm(g):
    """League-wide two-way RAPM over the gender's tracked games (holds teammates
    AND opponents constant — needs the whole pool, not one team). inference=True
    attaches the statsmodels 95% CI / significance companion."""
    return RA.compute_rapm(_gender_tracked_ids(g), inference=True)


@st.cache_data(ttl=600, show_spinner=False)
def _season_wpa(g, mode):
    return WP.season_wpa(gender=g, mode=mode)


@st.cache_data(ttl=600, show_spinner=False)
def _chemistry(tid, _tids):
    return NW.chemistry_network(tid, list(_tids))


@st.cache_data(ttl=600, show_spinner=False)
def _units(tid, _tids):
    return LU.unit_ratings(tid, list(_tids))


@st.cache_data(ttl=600, show_spinner=False)
def _scout(tid, g, limit=7, excl=()):
    trk = _tracked_ratings(g)
    return SC.build_scout(tid, g, _score_ratings(g), trk,
                          _pack(g, trk), _ptable_full(g),
                          personnel_limit=limit, exclude_pids=set(excl))


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
    f"{gender_label(gender)} · {rec['games']} games"
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


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYER PROFILE — helpers + CSS ported from 6_Players.py (Player Profile tab)
# ══════════════════════════════════════════════════════════════════════════════
# Accent-tinted header (dynamic accent → page-local). The static .pl-pct*/
# .pl-glass*/.pl-scout rules used by the shared card helpers live in
# assets/style.css.
_par, _pag, _pab = _rgb(ACCENT)
st.markdown(f"""
<style>
.pl-hdr {{ font-size:16px; font-weight:800; color:#f0f6fc; text-transform:uppercase;
          letter-spacing:1.5px; border-left:3px solid {ACCENT}; padding-left:11px;
          margin:18px 0 10px; text-shadow:0 0 18px rgba({_par},{_pag},{_pab},0.35); }}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=600, show_spinner=False)
def _pp_zone_tables():
    """Per-player zone splits + guarded/open splits over the whole tracked sample."""
    ev = S.fetch_events()
    return S.player_zone_splits(events=ev), S.player_zone_guarded(events=ev)


@st.cache_data(ttl=600, show_spinner=False)
def _playtype_view(g, tid, offense):
    """Synergy-style play-type table for one team, ranked vs the league pool."""
    return PT.team_playtype_percentiles(tid, gender=g, offense=offense)


@st.cache_data(ttl=600, show_spinner=False)
def _scoring_buckets(_ids):
    """Scoring buckets (paint/2nd-chance/off-TO/fast-break/bench) over the games."""
    return GF.scoring_buckets(list(_ids))


@st.cache_data(ttl=600, show_spinner=False)
def _team_fouls(_ids):
    """Team fouls by quarter + opponent FTA drawn, over the games."""
    return FL.team_foul_by_quarter(list(_ids))


@st.cache_data(ttl=600, show_spinner=False)
def _matchup_grid(g, tid, _ids):
    """Who-guarded-whom rows + assignment difficulty for a team's defenders."""
    names = MU.player_names(g)
    rows = MU.team_matchup_rows(tid, game_ids=list(_ids), names=names)
    diff = MU.matchup_difficulty(game_ids=list(_ids), table=_ptable_full(g))
    return rows, diff


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER MAP — this file renders OUT OF DECLARATION ORDER. Read before editing.
# ──────────────────────────────────────────────────────────────────────────────
#  Each section is an @st.fragment (def _fx_*), so a widget click inside it only
#  reruns that section, not the whole page. Render order in the file:
#    _fx_over    → tab_over     Overview
#    _fx_players → tab_players   Players (nested 2PT/3PT sub-tabs inside)
#    _fx_sched   → tab_sched     Schedule + box-score picker
#    with tab_charts:  creates 10 sub-tabs (ch_sc sh rb df tr qt adv bld play
#       impact). Scoring/Shooting/Rebounding/Defense/Trends + Play Types render
#       INSIDE this block — they SHARE one computed-once data batch (quarter, qs,
#       cbg, poss, tb, ob…), which is why they are NOT individually fragmented.
#    _fx_chqt/_fx_chadv/_fx_chbld → ch_qt/ch_adv/ch_bld  (Quarters/Advanced/Build,
#       rendered BELOW at module level — the sub-tab objects are module globals)
#    _fx_scout   → tab_scout     Scout (rendered between Advanced and Build)
#    tab_gloss   → Glossary
#    _fx_prof5   → tab_prof      Player Profile — rendered LAST (~L5500)
# ══════════════════════════════════════════════════════════════════════════════
(tab_over, tab_players, tab_prof, tab_sched, tab_charts,
 tab_scout, tab_gloss) = st.tabs(
    ["Overview", "Players", "Player Profile", "Schedule", "Charts",
     "Scout", "Glossary"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _fx_over():
    st.caption("Everything about this team at a glance — power ratings, record, "
               "who carries them, the four factors and how they score.")

    # ── coach notes (teams.notes) ───────────────────────────────────────────
    _curnotes = (query("SELECT notes FROM teams WHERE id=?", (team_id,))
                 or [{"notes": ""}])[0].get("notes") or ""
    with st.expander("📝 Team notes" + (" — saved" if _curnotes else ""),
                     expanded=bool(_curnotes)):
        _newnotes = st.text_area(
            "Notes", value=_curnotes, key=f"tn_{team_id}",
            label_visibility="collapsed",
            placeholder="Scouting notes, reminders, season context… saved to this "
                        "team and shown here next time.")
        if st.button("Save notes", key=f"tn_save_{team_id}"):
            execute("UPDATE teams SET notes=? WHERE id=?", (_newnotes, team_id))
            st.success("Saved.")

    _mprof = MB.manual_team_profile(team_id)
    if _mprof:
        st.markdown("<div class='pl-hdr'>Entered (untracked) games</div>",
                    unsafe_allow_html=True)
        _mc = st.columns(4)
        _mc[0].metric("Games entered", _mprof["games"])
        _mc[1].metric("PPP", f"{_mprof['PPP']:.2f}")
        _mc[2].metric("ORtg", f"{_mprof['ORtg']:.0f}")
        _mc[3].metric("eFG%", f"{_mprof['off_ff']['eFG']:.0f}%")
        st.caption("From hand-entered box scores (not play-by-play tracked) · "
                   "possessions = FGA + TOV. Enter boxes on the Setup page.")

    _bytype = {}
    for r in query("""SELECT game_type, team1_id, home_score, away_score FROM games
                      WHERE (team1_id=? OR team2_id=?) AND home_score IS NOT NULL
                        AND away_score IS NOT NULL""", (team_id, team_id)):
        won = ((r["home_score"] > r["away_score"]) if r["team1_id"] == team_id
               else (r["away_score"] > r["home_score"]))
        d = _bytype.setdefault(r["game_type"] or "Regular", [0, 0])
        d[0 if won else 1] += 1
    if _bytype and (len(_bytype) > 1 or "Regular" not in _bytype):
        _seg = " · ".join(f"**{k}** {v[0]}-{v[1]}"
                          for k, v in sorted(_bytype.items()))
        st.caption(f"Record by game type — {_seg}  "
                   f"<span style='color:#8b949e'>(set types on Setup)</span>")

    m = st.columns(5)
    m[0].metric("Power", sc_score.get("Power", "—"),
                help="Results-only 0-100 power rating (50 = league avg).")
    m[1].metric("Everything rank", f"#{sc_score.get('Rank', '—')} of {len(scored)}",
                help="Results-only Score ranking across every team in the league.")
    m[2].metric("Record", f"{rec['wins']}-{rec['losses']}")
    m[3].metric("Margin / game", f"{rec['MOV']:+.1f}")
    m[4].metric("Points for / against", f"{rec['PF_pg']:.0f} / {rec['PA_pg']:.0f}")

    # ── record vs ranked teams (results-based — every completed game counts) ─
    _ranks = sorted(scored.items(), key=lambda kv: kv[1].get("Rank", 1e9))
    _top10 = {tid for tid, _ in _ranks[:10]}
    _top25 = {tid for tid, _ in _ranks[:25]}

    def _rec_vs(idset):
        wv = lv = 0
        for gg in log:
            if gg["opp_id"] in idset and gg["opp_id"] != team_id:
                if gg["won"]:
                    wv += 1
                else:
                    lv += 1
        return wv, lv

    _w10, _l10 = _rec_vs(_top10)
    _w25, _l25 = _rec_vs(_top25)
    vr = st.columns(3)
    vr[0].metric("Overall rank", f"#{sc_score.get('Rank', '—')} of {len(scored)}",
                 help="Results-only Score ranking across the league.")
    vr[1].metric("vs Top 10", f"{_w10}-{_l10}",
                 help="Record vs the top-10 teams by Score ranking.")
    vr[2].metric("vs Top 25", f"{_w25}-{_l25}",
                 help="Record vs the top-25 teams by Score ranking.")

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

    # ── four factors & scoring mix — every stat aligned to the league ───────────
    if has_tracked:
        st.markdown("<div class='lab-hdr'>Four factors &amp; scoring mix — vs "
                    "league</div>", unsafe_allow_html=True)
        _AMBER = "#d29922"
        lpools = _league_stat_pools(gender)
        me = lpools.get(team_id, {})

        def _vals(key):
            return [s[key] for s in lpools.values() if s.get(key) is not None]

        def _lg_avg(key):
            v = _vals(key)
            return sum(v) / len(v) if v else 0.0

        def _lg_rank(key, hib):
            v = _vals(key)
            mv = me.get(key)
            if mv is None or not v:
                return None, len(v)
            return sum(1 for x in v if (x > mv if hib else x < mv)) + 1, len(v)

        def _rcolor(rk, tot):
            if not rk or tot <= 1:
                return GREY
            p = rk / tot
            return GOOD if p <= 0.25 else (_AMBER if p <= 0.50 else BAD)

        def _pbar(rk, tot):
            if not rk or tot <= 1:
                return ""
            pct = (1 - (rk - 1) / (tot - 1)) * 100
            c = GOOD if pct >= 75 else (_AMBER if pct >= 50 else BAD)
            return (f"<div style='background:#21262d;border-radius:3px;height:4px;"
                    f"overflow:hidden;margin-top:5px'><div style='background:{c};"
                    f"width:{pct:.0f}%;height:100%;border-radius:3px'></div></div>")

        def _ff_card(col, label, key, opp_key, hib, fmt, scale=100.0):
            tv = me.get(key, 0.0) * scale
            ov = me.get(opp_key, 0.0) * scale
            lg = _lg_avg(key) * scale
            rk, tot = _lg_rank(key, hib)
            rc = _rcolor(rk, tot)
            tcol = GOOD if ((tv >= ov) if hib else (tv <= ov)) else BAD
            rstr = (f"<div style='font-size:10px;font-weight:700;color:{rc};"
                    f"margin-top:3px'>#{rk}/{tot}</div>") if rk else ""
            col.markdown(
                f"<div style='background:{CARD_BG};border:1px solid {GRID};"
                f"border-radius:10px;padding:12px 10px;text-align:center;"
                f"margin-bottom:6px'>"
                f"<div style='font-size:9px;color:{GREY};text-transform:uppercase;"
                f"letter-spacing:1px'>{label}</div>"
                f"<div style='font-size:24px;font-weight:900;color:{tcol};"
                f"line-height:1.1'>{fmt.format(tv)}</div>"
                f"<div style='font-size:11px;color:{AWAY};margin-top:1px'>"
                f"opp {fmt.format(ov)}</div>"
                f"<div style='font-size:10px;color:#6e7681'>lg {fmt.format(lg)}</div>"
                f"{rstr}{_pbar(rk, tot)}</div>", unsafe_allow_html=True)

        def _stat_card(col, label, key, hib, fmt, scale=1.0, sub=""):
            v = me.get(key)
            rk, tot = _lg_rank(key, hib)
            rc = _rcolor(rk, tot)
            vtxt = "—" if v is None else fmt.format(v * scale)
            rstr = (f"<div style='font-size:9px;font-weight:700;color:{rc};"
                    f"margin-top:2px'>#{rk}/{tot}</div>") if rk else ""
            col.markdown(
                f"<div style='background:{CARD_BG};border:1px solid {GRID};"
                f"border-radius:8px;padding:10px 8px;text-align:center'>"
                f"<div style='font-size:9px;color:{GREY};text-transform:uppercase;"
                f"letter-spacing:1px'>{label}</div>"
                f"<div style='font-size:18px;font-weight:800;color:{BLUE}'>{vtxt}"
                f"</div><div style='font-size:9px;color:#6e7681;margin-top:1px'>"
                f"{sub}</div>{rstr}{_pbar(rk, tot)}</div>", unsafe_allow_html=True)

        st.markdown("<div style='font-size:11px;color:#f0a500;font-weight:700;"
                    "text-transform:uppercase;letter-spacing:1px;margin:2px 0 4px'>"
                    "Offense</div>", unsafe_allow_html=True)
        _o = st.columns(4)
        _ff_card(_o[0], "eFG%", "efg", "oefg", True, "{:.1f}%")
        _ff_card(_o[1], "TOV%", "tov", "opp_tov", False, "{:.1f}%")
        _ff_card(_o[2], "OREB%", "orb", "opp_orb", True, "{:.1f}%")
        _ff_card(_o[3], "FT rate", "ftr", "opp_ftr", True, "{:.3f}", scale=1.0)

        st.markdown("<div style='font-size:11px;color:#58a6ff;font-weight:700;"
                    "text-transform:uppercase;letter-spacing:1px;margin:8px 0 4px'>"
                    "Defense</div>", unsafe_allow_html=True)
        _d = st.columns(4)
        _ff_card(_d[0], "Opp eFG%", "oefg", "efg", False, "{:.1f}%")
        _ff_card(_d[1], "Opp TOV%", "opp_tov", "tov", True, "{:.1f}%")
        _ff_card(_d[2], "DREB%", "dreb", "opp_orb", True, "{:.1f}%")
        _ff_card(_d[3], "Opp FT rate", "opp_ftr", "ftr", False, "{:.3f}", scale=1.0)

        st.markdown("<div class='lab-hdr' style='margin-top:12px'>Key stats — vs "
                    "league</div>", unsafe_allow_html=True)
        _k1 = st.columns(4)
        _stat_card(_k1[0], "TS%", "ts", True, "{:.1f}%", 100.0, "true shooting")
        _stat_card(_k1[1], "FG%", "fg", True, "{:.1f}%", 100.0, "field goal")
        _stat_card(_k1[2], "3P%", "tp", True, "{:.1f}%", 100.0, "three-point")
        _stat_card(_k1[3], "Paint FG%", "paint", True, "{:.1f}%", 100.0, "at the rim")
        _k2 = st.columns(4)
        _stat_card(_k2[0], "AST/TO", "ast_tov", True, "{:.2f}", 1.0, "ball security")
        _stat_card(_k2[1], "STL%", "stl_rate", True, "{:.1f}%", 1.0, "steals / 100")
        _stat_card(_k2[2], "ORtg", "ortg", True, "{:.1f}", 1.0, "pts / 100")
        _stat_card(_k2[3], "DRtg", "drtg", False, "{:.1f}", 1.0, "allowed / 100")
        st.caption("Each card: this team's value (green = beats what they allow / "
                   f"red = worse), opponent value, league average over the "
                   f"{len(lpools)} tracked teams, and league rank + percentile bar.")

        st.markdown("**Where the points come from**")
        dn = go.Figure(go.Pie(
            labels=["2-pt", "3-pt", "Free throw"],
            values=[soff["pts2"], soff["pts3"], soff["ptsft"]],
            hole=0.55, sort=False,
            marker=dict(colors=[ACCENT, BLUE, GREY]),
            textinfo="label+percent"))
        dn.update_layout(
            template="plotly_dark", height=300,
            paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
            margin=dict(l=10, r=10, t=30, b=10),
            annotations=[dict(text=f"{soff['pct_paint']*100:.0f}%<br>"
                                   "<span style='font-size:10px'>in paint</span>",
                              x=0.5, y=0.5, font=dict(size=15),
                              showarrow=False)])
        st.plotly_chart(dn, width="stretch", key="ov_src")

    # ── game-by-game: margin paired with offense/defense (APP3 trend charts) ────
    def _dual_axis(fig, y2_title, height=360):
        """MOV-bars-on-y1 + lines-on-y2 layout shared by the trend charts."""
        _style(fig, height)
        fig.update_layout(
            barmode="relative", bargap=0.25,
            xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
            yaxis=dict(title="MOV", showgrid=False, zerolinecolor="#30363d"),
            yaxis2=dict(title=y2_title, overlaying="y", side="right",
                        showgrid=False),
            legend=dict(orientation="h", y=-0.28))
        return fig

    st.markdown("<div class='lab-hdr'>Points scored &amp; allowed — all games"
                "</div>", unsafe_allow_html=True)
    _gx = [f"{g['date'][5:]} {g['site']} {g['opp'][:10]}" for g in log]
    _mv = [g["margin"] for g in log]
    _cm = [GOOD if m >= 0 else BAD for m in _mv]
    fA = go.Figure()
    fA.add_trace(go.Bar(
        x=_gx, y=_mv, name="MOV", marker_color=_cm, opacity=0.55,
        marker_line_width=0, hovertemplate="%{x}<br>MOV %{y:+d}<extra></extra>"))
    fA.add_trace(go.Scatter(
        x=_gx, y=[g["pf"] for g in log], name="Scored", yaxis="y2",
        mode="lines+markers", line=dict(color=ACCENT, width=2),
        marker=dict(size=6), hovertemplate="%{x}<br>Scored %{y}<extra></extra>"))
    fA.add_trace(go.Scatter(
        x=_gx, y=[g["pa"] for g in log], name="Allowed", yaxis="y2",
        mode="lines+markers", line=dict(color=AWAY, width=2, dash="dot"),
        marker=dict(size=6), hovertemplate="%{x}<br>Allowed %{y}<extra></extra>"))
    _dual_axis(fA, "Points")
    st.plotly_chart(fA, width="stretch", key="ov_ptsmov")
    st.caption("MOV bars (green win / red loss) on the left axis; points scored "
               "and allowed on the right — every completed game.")

    _trend = bundle["trend"] if has_tracked else []
    if _trend:
        _tx = [f"{e['date'][5:]} vs {e['opp'][:10]}" for e in _trend]
        _tm = [e["margin"] for e in _trend]
        _tc = [GOOD if m >= 0 else BAD for m in _tm]

        st.markdown("<div class='lab-hdr'>Off &amp; Def rating — tracked games"
                    "</div>", unsafe_allow_html=True)
        fB = go.Figure()
        fB.add_trace(go.Bar(
            x=_tx, y=_tm, name="MOV", marker_color=_tc, opacity=0.55,
            marker_line_width=0,
            hovertemplate="%{x}<br>MOV %{y:+.0f}<extra></extra>"))
        fB.add_trace(go.Scatter(
            x=_tx, y=[e["ORtg"] for e in _trend], name="ORtg", yaxis="y2",
            mode="lines+markers", line=dict(color=ACCENT, width=2),
            marker=dict(size=6), hovertemplate="%{x}<br>ORtg %{y:.1f}<extra></extra>"))
        fB.add_trace(go.Scatter(
            x=_tx, y=[e["DRtg"] for e in _trend], name="DRtg", yaxis="y2",
            mode="lines+markers", line=dict(color=BLUE, width=2, dash="dot"),
            marker=dict(size=6), hovertemplate="%{x}<br>DRtg %{y:.1f}<extra></extra>"))
        _dual_axis(fB, "Rating")
        st.plotly_chart(fB, width="stretch", key="ov_ortgmov")

        st.markdown("<div class='lab-hdr'>Points per possession — tracked games"
                    "</div>", unsafe_allow_html=True)
        fC = go.Figure()
        fC.add_trace(go.Bar(
            x=_tx, y=_tm, name="MOV", marker_color=_tc, opacity=0.45,
            marker_line_width=0,
            hovertemplate="%{x}<br>MOV %{y:+.0f}<extra></extra>"))
        fC.add_trace(go.Scatter(
            x=_tx, y=[e["PPP"] for e in _trend], name="PPP", yaxis="y2",
            mode="lines+markers", line=dict(color=ACCENT, width=2),
            marker=dict(size=6), hovertemplate="%{x}<br>PPP %{y:.3f}<extra></extra>"))
        fC.add_trace(go.Scatter(
            x=_tx, y=[e["oPPP"] for e in _trend], name="oPPP", yaxis="y2",
            mode="lines+markers", line=dict(color=AWAY, width=2, dash="dot"),
            marker=dict(size=6), hovertemplate="%{x}<br>oPPP %{y:.3f}<extra></extra>"))
        _dual_axis(fC, "PPP")
        st.plotly_chart(fC, width="stretch", key="ov_pppmov")

    # ── margin trend (+ shot-creation mix lines) ───────────────────────────────
    st.markdown("<div class='lab-hdr'>Margin trend</div>",
                unsafe_allow_html=True)
    gx = [f"{g['date'][5:]} {g['site']} {g['opp'][:10]}" for g in log]
    mv = [g["margin"] for g in log]
    colors = [GOOD if g["won"] else BAD for g in log]
    mfig = go.Figure(go.Bar(
        x=gx, y=mv, name="Margin", marker_color=colors, marker_line_width=0,
        text=[f"{g['pf']}-{g['pa']}" for g in log], textposition="outside",
        textfont=dict(size=9),
        hovertemplate="%{x}<br>Margin %{y:+d}<extra></extra>"))
    mfig.add_hline(y=0, line=dict(color="#30363d"))
    # overlay % of FG self-created vs % created (off a pass) per tracked game
    cbg_ov = bd.get("creation_by_game", {}) if has_tracked else {}
    if cbg_ov:
        self_sh, crt_sh = [], []
        for g in log:
            c = cbg_ov.get(g["game_id"])
            if c and (c["self_FGA"] + c["asst_FGA"]):
                tot = c["self_FGA"] + c["asst_FGA"]
                self_sh.append(100 * c["self_FGA"] / tot)
                crt_sh.append(100 * c["asst_FGA"] / tot)
            else:
                self_sh.append(None)
                crt_sh.append(None)
        mfig.add_trace(go.Scatter(
            x=gx, y=self_sh, name="% FG self-created", yaxis="y2",
            mode="lines+markers", connectgaps=True,
            line=dict(color=ACCENT, width=2.5), marker=dict(size=6),
            hovertemplate="%{x}<br>Self-created %{y:.0f}%<extra></extra>"))
        mfig.add_trace(go.Scatter(
            x=gx, y=crt_sh, name="% FG created (off pass)", yaxis="y2",
            mode="lines+markers", connectgaps=True,
            line=dict(color=BLUE, width=2.5), marker=dict(size=6),
            hovertemplate="%{x}<br>Created %{y:.0f}%<extra></extra>"))
        mfig.update_layout(
            yaxis=dict(title="Margin"),
            yaxis2=dict(title="Share of FG %", overlaying="y", side="right",
                        range=[0, 100], showgrid=False, zerolinecolor="#30363d"))
    else:
        mfig.update_yaxes(title="Margin")
    mfig.update_xaxes(tickangle=-45)
    _style(mfig, 380)
    st.plotly_chart(mfig, width="stretch", key="ov_margin")
    st.caption("Bars: green = win, red = loss (final score labelled). Lines (right "
               "axis): the share of made/attempted FGs that were self-created (no "
               "pass) vs created off a pass, each tracked game.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — PLAYERS
# ══════════════════════════════════════════════════════════════════════════════
with tab_over:
    _fx_over()


@st.fragment
def _fx_players():
    if not players:
        st.info("No eligible players for this team yet — track a game in the "
                "Game Tracker.")
    else:
        st.caption("The roster localized: ratings side-by-side, per-game "
                   "production, an offense/defense map, and a lineup builder "
                   "that projects a five from the player ratings.")

        # ── depth chart (position · availability · measurables) ─────────────
        _depth = query(
            """SELECT number, name, position, availability, height, wingspan, weight
               FROM players WHERE team_id=? AND archived=0 ORDER BY number""",
            (team_id,))
        if any((p["position"] or "").strip() for p in _depth):
            st.markdown("<div class='pl-hdr'>Depth chart</div>",
                        unsafe_allow_html=True)
            _dotc = {"Active": "#2ea043", "Questionable": "#f0a500", "Out": "#da3633"}
            _dc = st.columns(5)
            for _col, _pos in zip(_dc, ["PG", "SG", "SF", "PF", "C"]):
                _h = f"<div class='mini-lbl' style='margin-bottom:6px'>{_pos}</div>"
                for p in [q for q in _depth if (q["position"] or "") == _pos]:
                    _dot = _dotc.get(p["availability"] or "Active", "#8b949e")
                    _meas = " · ".join(
                        ([f"{p['height']:g}\"" ] if p["height"] else [])
                        + ([f"{p['weight']:g}lb"] if p["weight"] else []))
                    _h += (f"<div style='background:#161b22;border:1px solid #30363d;"
                           f"border-radius:8px;padding:6px 9px;margin-bottom:6px'>"
                           f"<span style='color:{_dot}'>●</span> <b>#{p['number']}</b> "
                           f"{p['name']}<div style='font-size:10px;color:#8b949e'>"
                           f"{_meas}</div></div>")
                _col.markdown(_h, unsafe_allow_html=True)
            st.caption("● green = available · amber = questionable · red = out. "
                       "Set positions & status on the **Setup** page.")
        else:
            st.caption("➕ Set player positions on the **Setup** page to unlock the "
                       "depth chart (with height / wingspan / weight).")

        arch = _archetypes(gender)
        rdf_rows = []
        for p in players:
            row = {"#": p["number"], "Player": p["name"], "GP": p["GP"]}
            for c in RATING_COLS_ALL:
                row[c] = p.get(c)
            row["Archetype"] = arch.get(p["_pid"], "—")
            row.update({
                "PPG": p["PPG"], "RPG": p["RPG"], "APG": p["APG"],
                "TS%": p["TS%"], "USG%": p["USG%"], "+/-": p["+/-"],
                "SC Shot%": p.get("SCShot%"), "SC Pass%": p.get("SCPass%"),
                "SC Created%": p.get("SCCreated%"),
            })
            rdf_rows.append(row)
        rdf = pd.DataFrame(rdf_rows)
        st.dataframe(
            rdf, hide_index=True, width="stretch",
            height=min(620, 60 + 35 * len(rdf)),
            column_config={c: st.column_config.ProgressColumn(
                c, format="%.0f", min_value=0, max_value=100)
                for c in RATING_COLS_ALL})
        st.caption("Every per-player rating in the glossary (0–100, 50 = league "
                   "average) plus the data-driven Archetype, and shot-creation mix: "
                   "SC Shot% (own shots), SC Pass% (passes into shots) and "
                   "SC Created% (screens that freed a shooter) — shares of the "
                   "player's total shot creation.")

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

        # ── shot selection: who shoots where (most) & best where, by 2s/3s ──
        st.markdown("<div class='lab-hdr'>Shot selection — who shoots where</div>",
                    unsafe_allow_html=True)
        _zsh = (_zone_player_shooting(team_id, tuple(bundle["tracked_ids"]))
                if has_tracked else None)
        if not _zsh or not _zsh["all"]["players"]:
            st.caption("No located shot data yet — track games to see who shoots "
                       "where, and who shoots best from each spot.")
        else:
            _ZC = {"LC": GOOD, "LW": BLUE, "C": ACCENT, "RW": PURPLE, "RC": PINK}
            _MIN_BEST = 3

            def _zlab(z):
                return TA.ZONE_LABELS[z].split("/")[0].strip()

            def _shotsel(data, pfx, tlbl):
                if not data["players"]:
                    st.caption(f"No located {tlbl} attempts in tracked games yet.")
                    return
                _lead = []
                for z in TA.ZONES:
                    rows = data["zones"][z]
                    if not rows:
                        continue
                    vol = rows[0]
                    elig = [r for r in rows if r["FGA"] >= _MIN_BEST]
                    best = (max(elig, key=lambda r: (r["pct"], r["FGA"]))
                            if elig else None)
                    _lead.append({
                        "Zone": TA.ZONE_LABELS[z],
                        "Shoots here most": f"#{vol['number']} {vol['name']} "
                                            f"({vol['FGA']} FGA)",
                        "Best FG% here": (f"#{best['number']} {best['name']} "
                                          f"({best['FGM']}/{best['FGA']} · "
                                          f"{best['pct']*100:.0f}%)"
                                          if best else "—"),
                    })
                if _lead:
                    st.markdown(f"**Zone leaders ({tlbl})** — most attempts & best "
                                f"make-rate (min {_MIN_BEST} att) per spot")
                    st.dataframe(pd.DataFrame(_lead), hide_index=True,
                                 width="stretch")

                top = data["players"][:8]
                if top:
                    xn = [f"#{p['number']}" for p in top]
                    sb = go.Figure()
                    for z in TA.ZONES:
                        sb.add_trace(go.Bar(
                            name=_zlab(z), x=xn,
                            y=[p["by_zone"][z]["FGA"] for p in top],
                            marker_color=_ZC[z], marker_line_width=0,
                            hovertemplate="%{x}<br>" + _zlab(z)
                                          + " %{y} FGA<extra></extra>"))
                    sb.update_layout(barmode="stack",
                                     legend=dict(orientation="h", y=-0.2))
                    sb.update_yaxes(title=f"{tlbl} FGA (tracked)")
                    _style(sb, 320)
                    st.plotly_chart(sb, width="stretch", key=f"pl_zvol_{pfx}")
                    st.caption(f"Where each player's {tlbl} attempts come from — "
                               "taller segment = more shots from that zone.")

                grid = []
                for p in data["players"]:
                    row = {"Player": f"#{p['number']} {p['name']}",
                           "FGA": p["total_FGA"]}
                    for z in TA.ZONES:
                        bz = p["by_zone"][z]
                        row[_zlab(z)] = (f"{bz['FGM']}/{bz['FGA']} · "
                                         f"{bz['pct']*100:.0f}%"
                                         if bz["FGA"] else "—")
                    grid.append(row)
                if grid:
                    st.markdown(f"**Per-player {tlbl} FG% by zone** — FGM/FGA · "
                                "make-rate")
                    st.dataframe(pd.DataFrame(grid), hide_index=True,
                                 width="stretch",
                                 height=min(440, 60 + 35 * len(grid)))

            _t2, _t3 = st.tabs(["2-pointers", "3-pointers"])
            with _t2:
                _shotsel(_zsh["2"], "2", "2-pt")
            with _t3:
                _shotsel(_zsh["3"], "3", "3-pt")

            # shot-selection profile — perimeter (3PA rate) vs paint volume
            _sel = [p for p in players if p.get("3PR") is not None
                    and p.get("PaintA") is not None and p.get("GP")]
            if _sel:
                st.markdown("**Shot-selection profile** — perimeter vs paint")
                _selfig = go.Figure(go.Scatter(
                    x=[p["3PR"] for p in _sel],
                    y=[p["PaintA"] / p["GP"] for p in _sel],
                    mode="markers+text",
                    text=[f"#{p['number']}" for p in _sel],
                    textposition="top center", textfont=dict(size=9),
                    marker=dict(
                        size=[max(9, (p["PPG"] or 0) * 1.4) for p in _sel],
                        color=[p["PPG"] or 0 for p in _sel],
                        colorscale="Greens", showscale=True,
                        colorbar=dict(title="PPG"),
                        line=dict(width=1, color="#30363d")),
                    hovertext=[p["name"] for p in _sel],
                    hovertemplate="%{hovertext}<br>3PA rate %{x:.0f}%"
                                  "<br>Paint FGA/g %{y:.1f}<extra></extra>"))
                _selfig.update_xaxes(title="3-point attempt rate (% of FGA) →")
                _selfig.update_yaxes(title="Paint attempts / game →")
                _style(_selfig, 380)
                st.plotly_chart(_selfig, width="stretch", key="pl_shotsel")
                st.caption("Bottom-right = perimeter-heavy; top-left = paint-"
                           "focused. Bubble size & color = points/game.")

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

        # ── best shooter by zone (court heatmap) ────────────────────────────
        st.markdown("<div class='lab-hdr'>Best shooter by zone</div>",
                    unsafe_allow_html=True)
        pzl = bundle.get("player_zone_leaders")
        if pzl and any(pzl.values()):
            ZPOS = {"LC": (-21, 4), "LW": (-15, 21), "C": (0, 8),
                    "RW": (15, 21), "RC": (21, 4)}
            hz = go.Figure()
            hz.add_shape(type="rect", x0=-25, y0=0, x1=25, y1=31,
                         line=dict(color="#30363d", width=1))
            hz.add_shape(type="rect", x0=-8, y0=0, x1=8, y1=19,
                         line=dict(color="#30363d", width=1))
            hz.add_shape(type="circle", x0=-6, y0=13, x1=6, y1=25,
                         line=dict(color="#30363d", width=1))
            qz = [z for z in TA.ZONES if pzl.get(z)]
            nz = [z for z in TA.ZONES if not pzl.get(z)]
            if qz:
                hz.add_trace(go.Scatter(
                    x=[ZPOS[z][0] for z in qz], y=[ZPOS[z][1] for z in qz],
                    mode="markers+text",
                    marker=dict(size=66, color=[pzl[z]["pct"] * 100 for z in qz],
                                colorscale="RdYlGn", cmin=25, cmax=65,
                                showscale=True, colorbar=dict(title="FG%"),
                                line=dict(color="#0d1117", width=2)),
                    text=[f"#{pzl[z]['number']} "
                          f"{pzl[z]['name'].split()[-1]}<br>"
                          f"{pzl[z]['pct']*100:.0f}% "
                          f"({pzl[z]['FGM']}/{pzl[z]['FGA']})" for z in qz],
                    textfont=dict(size=10, color="#0d1117"),
                    textposition="middle center",
                    hovertext=[f"{TA.ZONE_LABELS[z]}<br>#{pzl[z]['number']} "
                               f"{pzl[z]['name']}<br>{pzl[z]['FGM']}/"
                               f"{pzl[z]['FGA']} · {pzl[z]['pct']*100:.0f}%"
                               for z in qz],
                    hovertemplate="%{hovertext}<extra></extra>"))
            if nz:
                hz.add_trace(go.Scatter(
                    x=[ZPOS[z][0] for z in nz], y=[ZPOS[z][1] for z in nz],
                    mode="markers+text",
                    marker=dict(size=66, color="#30363d",
                                line=dict(color="#0d1117", width=2)),
                    text=["—"] * len(nz), textposition="middle center",
                    textfont=dict(size=11, color="#8b949e"),
                    hovertext=[f"{TA.ZONE_LABELS[z]}<br>no qualifier (<3 att)"
                               for z in nz],
                    hovertemplate="%{hovertext}<extra></extra>"))
            hz.update_xaxes(visible=False, range=[-27, 27])
            hz.update_yaxes(visible=False, range=[-2, 33])
            _style(hz, 420)
            hz.update_layout(showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
                             margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(hz, width="stretch", key="pl_zone_best")
            st.caption("Each zone shows the teammate with the best FG% there "
                       "(≥3 located attempts), colored by make rate — the go-to "
                       "shooter for every spot on the floor.")
        else:
            st.caption("Not enough located attempts to rank shooters by zone yet.")

        # ── every-stat leaderboards (relative within the roster) ────────────
        st.markdown("<div class='lab-hdr'>Stat leaderboards — every stat</div>",
                    unsafe_allow_html=True)
        st.caption("Every player stat the app tracks, as a roster leaderboard — "
                   "players ranked against each other on that stat. Expand a "
                   "category to see all its stats.")
        for gi, (cat_name, spec) in enumerate(PLAYER_LEADER_GROUPS):
            with st.expander(cat_name,
                             expanded=(cat_name == "Scoring & shooting")):
                _player_leaderboards(players, spec, key_prefix=f"pllb{gi}")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════
with tab_players:
    _fx_players()


@st.fragment
def _fx_sched():
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
    st.caption("Opponent ranking (everything / tracked when possible), opponent "
               "record & class, the model's projected score, and the result. "
               "Projected score uses opponent-adjusted ratings with home court "
               "applied to the actual venue.")
    any_film = any((g.get("video_url") or "").strip() for g in log)
    sched_rows = []
    for g in log:
        oid = g["opp_id"]
        o_sc = scored.get(oid, {})
        o_tr = tracked.get(oid)
        ovr = o_sc.get("Rank")
        trk_rk = o_tr.get("Rank") if o_tr else None
        pred = PRED.predict_game(team_id, oid, scored=scored, tracked=tracked,
                                 home=(team_id if g["site"] == "vs" else oid))
        row = {
            "Date": g["date"], "": g["site"], "Opponent": g["opp"],
            "Cls": g["opp_class"],
            "Opp Rk": f"#{ovr}" if ovr else "—",
            "Trk Rk": f"#{trk_rk}" if trk_rk else "—",
            "Opp Rec": (f"{o_sc.get('W', 0)}-{o_sc.get('L', 0)}"
                        if o_sc else "—"),
            "Proj": (f"{pred['pf_a']:.0f}-{pred['pf_b']:.0f}" if pred else "—"),
            "Result": ("W" if g["won"] else "L") + f" {g['pf']}-{g['pa']}",
            "Margin": f"{g['margin']:+d}",
            "Tracked": "✓" if g["tracked"] else "",
        }
        if any_film:
            row["Film"] = (g.get("video_url") or "").strip() or None
        sched_rows.append(row)
    sched_cfg = {}
    if any_film:
        sched_cfg["Film"] = st.column_config.LinkColumn(
            "Film", display_text="▶ Watch", width="small",
            help="Opens the game's film (Hudl / YouTube / NFHS) in a new tab.")
    st.dataframe(pd.DataFrame(sched_rows), hide_index=True, width="stretch",
                 height=min(680, 60 + 35 * len(sched_rows)),
                 column_config=sched_cfg)

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
    # (Team stats over tracked games moved to Charts → Trends to avoid duplication.)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — CHARTS  (5 sub-tabs: Scoring · Shooting · Rebounding · Defense · Trends)
# ══════════════════════════════════════════════════════════════════════════════
with tab_sched:
    _fx_sched()


with tab_charts:
    (ch_sc, ch_sh, ch_rb, ch_df, ch_tr, ch_qt, ch_adv, ch_bld,
     ch_play, ch_impact) = st.tabs(
        ["Scoring", "Shooting", "Rebounding", "Defense", "Trends",
         "Quarters", "Advanced", "Build", "Play Types", "Impact Lab"])

    # ───────────────────────────────────────────── PLAY TYPES ──────────────
    with ch_play:
        st.subheader("Play types — possession efficiency vs the league")
        st.caption(
            "Points per possession by **how each shot was generated**, with a "
            "league percentile rank — the Synergy view, built from this app's "
            "data. Two lenses: tempo (transition / early / half-court from the "
            "possession clock) and shot creation (self / off a pass / off a "
            "screen / both). **Inferred from logged tempo + shot creation, not "
            "video-tagged play calls** — no pick-and-roll/iso film tagging is "
            "possible here. A shot ends a possession, so PPP = points per shot.")
        if not has_tracked:
            empty_state(
                "No tracked games yet",
                "Track a game in the Game Tracker to unlock play-type efficiency "
                "and league percentiles.", icon="🎬")
        else:
            _ptside = st.radio("Side of the ball", ["Offense", "Defense"],
                               horizontal=True, key="pt_side")
            _ptoff = _ptside == "Offense"
            _ptv = _playtype_view(gender, team_id, _ptoff)
            _ptrows = _ptv["rows"]
            _pttot = _ptv["total"]
            st.caption(
                f"{'Own' if _ptoff else 'Opponent'} shots in sample: "
                f"{_pttot['FGA']} · overall {_pttot['PPS']:.2f} PPP · percentile "
                f"is always good-oriented ("
                f"{'higher PPP' if _ptoff else 'fewer points allowed'} = higher rank).")
            for _ax in ("tempo", "creation"):
                _axr = [r for r in _ptrows if r["axis"] == _ax]
                if not _axr:
                    continue
                st.markdown(f"<div class='pl-hdr'>{_axr[0]['axis_label']}</div>",
                            unsafe_allow_html=True)
                for r in _axr:
                    _val = (f"{r['PPP']:.2f} PPP · {r['FG%'] * 100:.0f}% FG · "
                            f"{r['poss']} poss")
                    if r["pct"] is None:
                        st.markdown(
                            f"<div class='pl-pct'><div class='pl-pct-top'>"
                            f"<span class='pl-pct-lbl'>{r['label']}</span>"
                            f"<span class='pl-pct-val'>{_val} · "
                            f"<span style='color:#8b949e'>thin sample</span>"
                            f"</span></div></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(_pctile_bar(r["label"], _val, r["pct"]),
                                    unsafe_allow_html=True)
            _ranked = [r for r in _ptrows if r["pct"] is not None]
            if _ranked:
                _ranked = sorted(_ranked, key=lambda r: r["PPP"])
                _bn = [r["label"] for r in _ranked]
                _bv = [round(r["PPP"], 2) for r in _ranked]
                _bt = [f"{r['PPP']:.2f} · {r['tier']}" for r in _ranked]
                _bc = [r["color"] for r in _ranked]
                _pf = go.Figure(go.Bar(
                    x=_bv, y=_bn, orientation="h", marker_color=_bc,
                    marker_line_width=0, text=_bt, textposition="auto",
                    textfont=dict(size=11), cliponaxis=False,
                    hovertemplate="%{y}: %{text}<extra></extra>"))
                _style(_pf, 80 + 30 * len(_bn), margin=dict(l=4, r=14, t=8, b=30))
                _pf.update_xaxes(
                    title=f"Points per possession ({'scored' if _ptoff else 'allowed'})")
                _pf.update_yaxes(showgrid=False, automargin=True)
                st.plotly_chart(_pf, width="stretch", key="pt_bar")
            else:
                st.caption("Not enough possessions in any single play type yet to "
                           "rank against the league — check back after more "
                           "tracked games.")

    if not has_tracked:
        with ch_sc:
            empty_state("No tracked games yet",
                        "The analytics wall is built from play-by-play. Track a game "
                        "in the Game Tracker to light up scoring, shooting, defense, "
                        "play types and the rest.", icon="📊")
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

            # ── season scoring breakdown (us vs opponents) ──────────────────
            st.markdown("<div class='pl-hdr'>Scoring breakdown — us vs opponents"
                        "</div>", unsafe_allow_html=True)
            _scb = _scoring_buckets(tuple(bundle["tracked_ids"]))
            _own = _scb.get(team_id, {})
            _opp = {}
            for _k, _v in _scb.items():
                if _k == team_id:
                    continue
                for _bk, _val in _v.items():
                    _opp[_bk] = _opp.get(_bk, 0) + _val
            _bcats = [("Paint", "paint"), ("2nd chance", "second_chance"),
                      ("Off TO", "off_turnover"), ("Fast break", "fast_break"),
                      ("Bench", "bench")]
            _bfig = go.Figure()
            _bfig.add_trace(go.Bar(
                name="Us", x=[c[0] for c in _bcats],
                y=[_own.get(c[1], 0) for c in _bcats], marker_color=ACCENT,
                marker_line_width=0, text=[_own.get(c[1], 0) for c in _bcats],
                textposition="outside"))
            _bfig.add_trace(go.Bar(
                name="Opponents", x=[c[0] for c in _bcats],
                y=[_opp.get(c[1], 0) for c in _bcats], marker_color=GREY,
                marker_line_width=0, text=[_opp.get(c[1], 0) for c in _bcats],
                textposition="outside"))
            _bfig.update_layout(barmode="group")
            _bfig.update_yaxes(title="Points (tracked games)")
            _style(_bfig, 320)
            st.plotly_chart(_bfig, width="stretch", key="sc_buckets_season")
            st.caption("Field-goal points by type over tracked games · bench = all "
                       "points by inferred non-starters (the opening five). Points "
                       "off turnovers / 2nd chance / fast break are scoring you "
                       "create; opponent bars are what you allow.")

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

            # zone analysis — separated into 2s and 3s
            st.markdown("<div class='lab-hdr'>Zone analysis — where they shoot "
                        "(2s vs 3s)</div>", unsafe_allow_html=True)
            zo = zones["off"]
            zbt = bundle["zones_by_type"]["off"]   # {'all','2','3': {zone: agg}}
            zc1, zc2 = st.columns(2)
            with zc1:
                st.markdown("**Attempts by zone**")
                st.plotly_chart(_zone_pair_bars(
                    zbt["2"], zbt["3"], "2-pt", "3-pt",
                    lambda a: a["FGA"], "Attempts",
                    text_fn=lambda a: a["FGA"] or ""),
                    width="stretch", key="sh_zfa_t")
            with zc2:
                st.markdown("**FG% by zone**")
                st.plotly_chart(_zone_pair_bars(
                    zbt["2"], zbt["3"], "2P%", "3P%",
                    lambda a: a["FG%"] * 100, "FG%",
                    text_fn=lambda a: f"{a['FG%']*100:.0f}%" if a["FGA"] else "—"),
                    width="stretch", key="sh_zfg_t")

            # ── hot zone maps (court layout, colored by FG%) — 2s and 3s ─────
            ZPOS = {"LC": (-21, 4), "LW": (-15, 21), "C": (0, 8),
                    "RW": (15, 21), "RC": (21, 4)}
            short = {"LC": "LCnr", "LW": "LWing", "C": "Paint",
                     "RW": "RWing", "RC": "RCnr"}
            # 3s have no paint shot — the centre look is a top-of-the-key 3, so
            # for the 3-pt map relabel "C" as "Center" and lift it to the top of
            # the free-throw arc (drawn at y≈25).
            ZPOS3 = {**ZPOS, "C": (0, 27)}
            short3 = {**short, "C": "Center"}

            def _hotcourt(zmap, key, zpos=ZPOS, lbl=short):
                maxfga = max((zmap[z]["FGA"] for z in TA.ZONES), default=0) or 1
                hz = go.Figure()
                hz.add_shape(type="rect", x0=-25, y0=0, x1=25, y1=31,
                             line=dict(color="#30363d", width=1))
                hz.add_shape(type="rect", x0=-8, y0=0, x1=8, y1=19,
                             line=dict(color="#30363d", width=1))
                hz.add_shape(type="circle", x0=-6, y0=13, x1=6, y1=25,
                             line=dict(color="#30363d", width=1))
                hz.add_trace(go.Scatter(
                    x=[zpos[z][0] for z in TA.ZONES],
                    y=[zpos[z][1] for z in TA.ZONES], mode="markers+text",
                    marker=dict(
                        size=[20 + (zmap[z]["FGA"] / maxfga) * 60
                              for z in TA.ZONES],
                        color=[zmap[z]["FG%"] * 100 for z in TA.ZONES],
                        colorscale="RdYlGn", cmin=20, cmax=65, showscale=True,
                        colorbar=dict(title="FG%"),
                        line=dict(color="#0d1117", width=2)),
                    text=[f"{lbl[z]}<br>{zmap[z]['FG%']*100:.0f}%"
                          if zmap[z]["FGA"] else f"{lbl[z]}<br>—"
                          for z in TA.ZONES],
                    textfont=dict(size=10, color="#0d1117"),
                    textposition="middle center",
                    hovertext=[f"{TA.ZONE_LABELS[z]}<br>{zmap[z]['FGM']}/"
                               f"{zmap[z]['FGA']}" for z in TA.ZONES],
                    hovertemplate="%{hovertext}<br>FG%: %{marker.color:.0f}%"
                                  "<extra></extra>"))
                hz.update_xaxes(visible=False, range=[-27, 27])
                hz.update_yaxes(visible=False, range=[-2, 33])
                _style(hz, 380)
                hz.update_layout(plot_bgcolor="rgba(0,0,0,0)",
                                 margin=dict(l=10, r=10, t=10, b=10))
                return hz

            st.markdown("**Hot zone maps** — size = volume, color = FG%")
            hz1, hz2 = st.columns(2)
            with hz1:
                st.caption("2-pointers")
                st.plotly_chart(_hotcourt(zbt["2"], "2"), width="stretch",
                                key="sh_hot2")
            with hz2:
                st.caption("3-pointers")
                st.plotly_chart(_hotcourt(zbt["3"], "3", zpos=ZPOS3, lbl=short3),
                                width="stretch", key="sh_hot3")

            # ── actual vs expected FG% by zone — 2s and 3s ──────────────────
            st.markdown("**Actual vs expected FG% by zone**")
            zxbt = bundle["zone_xfg_by_type"]

            def _avefig(zt):
                zl = [TA.ZONE_LABELS[z].split("/")[0].strip() for z in TA.ZONES]
                fig = go.Figure()
                fig.add_trace(go.Bar(name="Actual", x=zl,
                                     y=[zt[z]["FG%"] * 100 for z in TA.ZONES],
                                     marker_color=ACCENT, marker_line_width=0))
                fig.add_trace(go.Bar(name="xFG%", x=zl,
                                     y=[zt[z]["xFG%"] * 100 for z in TA.ZONES],
                                     marker_color=BLUE, opacity=0.7,
                                     marker_line_width=0))
                fig.update_layout(barmode="group")
                fig.update_yaxes(title="%")
                fig.update_xaxes(tickangle=-25)
                _style(fig, 320)
                return fig

            av1, av2 = st.columns(2)
            with av1:
                st.caption("2-pointers — actual vs expected")
                st.plotly_chart(_avefig(zxbt["2"]), width="stretch",
                                key="sh_ave2")
            with av2:
                st.caption("3-pointers — actual vs expected")
                st.plotly_chart(_avefig(zxbt["3"]), width="stretch",
                                key="sh_ave3")
            st.caption("xFG% = expected FG% from the league-wide make-rate of each "
                       "shot's (zone · creation · contest) type. Actual above xFG% "
                       "= the team finishes that zone better than the looks imply. "
                       "Full per-zone detail (2PA/3PA split) is in the table below.")

            zxfg = bundle["zone_xfg"]
            ztbl = []
            for z in TA.ZONES:
                row = _shot_row(TA.ZONE_LABELS[z], zo[z], ppf, ftpf)
                row["xFG%"] = _pctf(zxfg[z]["xFG%"]) if zo[z]["FGA"] else "—"
                ztbl.append(row)
            st.dataframe(pd.DataFrame(ztbl), hide_index=True,
                         width="stretch")

            # guarded vs unguarded — overall, then split by 2/3, zone & creation
            st.markdown("<div class='lab-hdr'>Guarded vs unguarded</div>",
                        unsafe_allow_html=True)
            gd = bundle["guarded_detail"]
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

            # contested eFG% broken down: by 2/3, by zone, by creation type
            st.markdown("**Contested vs open eFG% — every which way**")

            def _gu_efg_fig(items, label_fn, key):
                """Grouped guarded/unguarded eFG% bar over a list of (lbl, split)."""
                xs = [label_fn(it) for it in items]
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    name="Guarded", x=xs,
                    y=[it[1]["guarded"]["eFG"] * 100 for it in items],
                    marker_color=AWAY, marker_line_width=0))
                fig.add_trace(go.Bar(
                    name="Unguarded", x=xs,
                    y=[it[1]["unguarded"]["eFG"] * 100 for it in items],
                    marker_color=ACCENT, marker_line_width=0))
                fig.update_layout(barmode="group")
                fig.update_yaxes(title="eFG%")
                fig.update_xaxes(tickangle=-20)
                _style(fig, 300)
                return fig

            gu1, gu2 = st.columns(2)
            with gu1:
                st.caption("By shot value")
                st.plotly_chart(_gu_efg_fig(
                    [("2-pt", gd["by_type"]["2"]), ("3-pt", gd["by_type"]["3"])],
                    lambda it: it[0], "t"), width="stretch", key="sh_gu_type")
            with gu2:
                st.caption("By zone")
                st.plotly_chart(_gu_efg_fig(
                    [(TA.ZONE_LABELS[z].split("/")[0].strip(), gd["by_zone"][z])
                     for z in TA.ZONES], lambda it: it[0], "z"),
                    width="stretch", key="sh_gu_zone")
            cmap_g = {"self": "Self", "pass": "Off pass",
                      "created": "Off screen", "both": "Pass+screen"}
            st.caption("By shot-creation type")
            st.plotly_chart(_gu_efg_fig(
                [(cmap_g[k], gd["by_creation"][k])
                 for k in ("self", "pass", "created", "both")],
                lambda it: it[0], "c"), width="stretch", key="sh_gu_crt")
            st.caption("Guarded (orange) vs open (accent) eFG%, split by shot "
                       "value, floor zone and how the shot was created — where "
                       "contesting hurts them most and where they punish open looks.")

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
            # creation graphs, each separated into 2s vs 3s
            cbt = bundle["creation_by_type"]

            def _crt_fig(metric_fn, yaxis, text_fn=None):
                fig = go.Figure()
                for tlab, tk, clr in (("2-pt", "2", ACCENT), ("3-pt", "3", BLUE)):
                    ys = [metric_fn(cbt[k][tk]) for k in order]
                    kw = dict(name=tlab, x=[cmap[k] for k in order], y=ys,
                              marker_color=clr, marker_line_width=0)
                    if text_fn:
                        kw["text"] = [text_fn(cbt[k][tk]) for k in order]
                        kw["textposition"] = "auto"
                    fig.add_trace(go.Bar(**kw))
                fig.update_layout(barmode="group")
                fig.update_yaxes(title=yaxis)
                fig.update_xaxes(tickangle=-20)
                _style(fig, 300)
                return fig

            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown("**Volume by creation type** (2s vs 3s)")
                st.plotly_chart(_crt_fig(lambda a: a["FGA"], "Attempts",
                                         text_fn=lambda a: a["FGA"] or ""),
                                width="stretch", key="sh_crb_v")
            with cc2:
                st.markdown("**eFG% by creation type** (2s vs 3s)")
                st.plotly_chart(_crt_fig(
                    lambda a: a["eFG"] * 100, "eFG%",
                    text_fn=lambda a: f"{a['eFG']*100:.0f}%" if a["FGA"] else "—"),
                    width="stretch", key="sh_crb_e")

            cc3, cc4 = st.columns(2)
            with cc3:
                st.markdown("**SCE by creation type** (2s vs 3s)")
                st.plotly_chart(_crt_fig(
                    lambda a: a["SCE"], "SCE",
                    text_fn=lambda a: f"{a['SCE']:.2f}" if a["FGA"] else "—"),
                    width="stretch", key="sh_crb_sce")
            with cc4:
                st.markdown("**Points / shot by creation type** (2s vs 3s)")
                st.plotly_chart(_crt_fig(
                    lambda a: a["PPS"], "Pts / shot",
                    text_fn=lambda a: f"{a['PPS']:.2f}" if a["FGA"] else "—"),
                    width="stretch", key="sh_crb_pps")
            st.caption("Each creation graph split by shot value. SCE = (FG points) "
                       "/ max FG points possible; PPS = points per attempt. Higher "
                       "= more efficient looks from that creation type.")

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

            # shooting by quarter — FG%/2P%/3P%/eFG%/TS% + FT%
            qbx_sh = bundle["quarter_boxes"]
            qsb = sorted(qbx_sh)
            if qsb:
                st.markdown("<div class='lab-hdr'>Shooting by quarter</div>",
                            unsafe_allow_html=True)
                xq = [_q_label(q) for q in qsb]

                def _qrate(fn):
                    return [fn(qbx_sh[q]["team"]) * 100 for q in qsb]

                sq1, sq2 = st.columns([2, 1])
                with sq1:
                    qf = go.Figure()
                    for nm, fn, clr in (("FG%", S.fg_pct, ACCENT),
                                        ("2P%", S.fg2_pct, GOOD),
                                        ("3P%", S.fg3_pct, BLUE),
                                        ("eFG%", S.efg, PURPLE),
                                        ("TS%", S.ts, "#d29922")):
                        qf.add_trace(go.Scatter(
                            x=xq, y=_qrate(fn), name=nm, mode="lines+markers",
                            line=dict(color=clr, width=3), marker=dict(size=7)))
                    qf.update_yaxes(title="%")
                    _style(qf, 320)
                    st.plotly_chart(qf, width="stretch", key="sh_qfg")
                with sq2:
                    ftq = go.Figure(go.Bar(
                        x=xq, y=_qrate(S.ft_pct), marker_color="#d29922",
                        marker_line_width=0,
                        text=[f"{v:.0f}" for v in _qrate(S.ft_pct)],
                        textposition="auto"))
                    ftq.update_yaxes(title="FT%")
                    _style(ftq, 320)
                    ftq.update_layout(title=dict(text="FT% by quarter",
                                                 font=dict(size=13)))
                    st.plotly_chart(ftq, width="stretch", key="sh_qft")

            # ── Shot Lab (moved here from Advanced): shot-making vs expectation ──
            st.markdown("<div class='lab-hdr'>Shot Lab — shot-making vs "
                        "expectation</div>", unsafe_allow_html=True)
            st.caption("SMOE — Shot-Making Over Expected, split by shot value. "
                       "Expected makes come from the make-rate of each shot's "
                       "(zone · creation · contest) type. Positive = they finish "
                       "better than the looks they generate.")
            zsl_bt = bundle["zones_by_type"]["off"]   # {'all','2','3': {zone: agg}}
            zxsl_bt = bundle["zone_xfg_by_type"]      # {'2','3': {zone: agg}}

            def _shotlab(zmap, zxmap, title, keypfx):
                exp = sum(zmap[z]["FGA"] * zxmap[z]["xFG%"] for z in TA.ZONES)
                act = sum(zmap[z]["FGM"] for z in TA.ZONES)
                fga = sum(zmap[z]["FGA"] for z in TA.ZONES)
                moe = (act - exp) / fga * 100 if fga else 0
                st.markdown(f"**{title}**")
                c1, c2 = st.columns([1, 2])
                with c1:
                    clr = GOOD if moe >= 0 else BAD
                    st.markdown(
                        f"<div class='spotlight'>"
                        f"<div class='spotlight-num' style='color:{clr}'>"
                        f"{moe:+.1f}%</div>"
                        f"<div class='spotlight-lbl'>FG% over expected</div>"
                        f"<div class='spotlight-sub'>made {act:.0f} vs "
                        f"{exp:.0f} expected on {fga:.0f} shots</div></div>",
                        unsafe_allow_html=True)
                with c2:
                    diffs = [(TA.ZONE_LABELS[z].split("/")[0].strip(),
                              (zmap[z]["FG%"] - zxmap[z]["xFG%"]) * 100,
                              zmap[z]["FGA"]) for z in TA.ZONES]
                    smf = go.Figure(go.Bar(
                        x=[d[0] for d in diffs], y=[d[1] for d in diffs],
                        marker_color=[GOOD if d[1] >= 0 else BAD for d in diffs],
                        marker_line_width=0,
                        text=[f"{d[1]:+.0f}pp" for d in diffs], textposition="auto",
                        hovertext=[f"{d[2]} FGA" for d in diffs],
                        hovertemplate="%{x}<br>%{y:+.1f}pp vs expected<br>"
                                      "%{hovertext}<extra></extra>"))
                    smf.add_hline(y=0, line=dict(color="#30363d"))
                    smf.update_yaxes(title="Actual − expected FG% (pp)")
                    smf.update_xaxes(tickangle=-25)
                    _style(smf, 300)
                    st.plotly_chart(smf, width="stretch", key=f"sh_smoe_{keypfx}")

            _shotlab(zsl_bt["2"], zxsl_bt["2"], "2-pointers", "2")
            _shotlab(zsl_bt["3"], zxsl_bt["3"], "3-pointers", "3")

            # overall look-quality + efficiency metrics (all shots, both values)
            zo_sl = zones["off"]
            zxfg_sl = bundle["zone_xfg"]
            exp_fgm = sum(zo_sl[z]["FGA"] * zxfg_sl[z]["xFG%"] for z in TA.ZONES)
            z_fga = sum(zo_sl[z]["FGA"] for z in TA.ZONES)
            xfg_avg = exp_fgm / z_fga if z_fga else 0
            slm = st.columns(4)
            slm[0].metric("Avg look quality (xFG%)", _pctf(xfg_avg),
                          help="Expected FG% of the shots they generate — higher "
                               "means easier looks on average.")
            slm[1].metric("Points / shot", f"{S.pps(tb):.2f}",
                          help="Field-goal points per FGA (free throws excluded).")
            slm[2].metric("Scoring efficiency (SCE)",
                          f"{S.shot_efficiency(tb):.3f}")
            slm[3].metric("Contested rate",
                          _pctf(bundle["guarded"]["guard_share"]))
            st.caption("Look quality measures the difficulty of shots created; "
                       "shot-making over expected measures whether they convert "
                       "them. A great offense does both.")

        # ───────────────────────────────────────────── REBOUNDING ───────────
        with ch_rb:
            rm = st.columns(5)
            rm[0].metric("OREB%", _pctf(ff["off"]["ORB"]),
                         help="Share of own misses rebounded.")
            rm[1].metric("DREB%",
                         _pctf(S._safe(tb["DRB"], tb["DRB"] + ob["ORB"])),
                         help="Share of opponent misses rebounded.")
            rm[2].metric("REB / game", f"{tb['TRB'] / ng:.1f}")
            rm[3].metric("OREB / game", f"{tb['ORB'] / ng:.1f}")
            rm[4].metric("DREB / game", f"{tb['DRB'] / ng:.1f}")

            rc2 = st.columns(4)
            rc2[0].metric("Opp OREB%", _pctf(ff["def"]["ORB"]),
                          help="Opponent's offensive-rebound rate — lower is "
                               "better work on the defensive glass.")
            rc2[1].metric("BLK rate", _pctf(S._safe(tb["BLK"], ob["2PA"])),
                          help="Share of opponent 2-pt attempts blocked.")
            rc2[2].metric("Forced TOV%", _pctf(ff["def"]["TOV"]),
                          help="Turnover rate forced on the opponent.")
            rc2[3].metric("STL / game", f"{tb['STL'] / ng:.1f}")

            st.markdown("<div class='lab-hdr'>Rebounding by quarter — team vs "
                        "opponent</div>", unsafe_allow_html=True)
            qbr = bundle["quarter_boxes"]
            qsr = sorted(qbr)
            if qsr:
                xq = [_q_label(q) for q in qsr]

                def _rpg(q, side, k):
                    n = qbr[q]["n_games"] or 1
                    return qbr[q][side][k] / n

                t_or = [_rpg(q, "team", "ORB") for q in qsr]
                o_or = [_rpg(q, "opp", "ORB") for q in qsr]
                t_dr = [_rpg(q, "team", "DRB") for q in qsr]
                o_dr = [_rpg(q, "opp", "DRB") for q in qsr]
                rqc1, rqc2 = st.columns(2)
                with rqc1:
                    f_or = go.Figure()
                    f_or.add_trace(go.Bar(x=xq, y=t_or, name="Team OREB",
                                          marker_color=ACCENT))
                    f_or.add_trace(go.Bar(x=xq, y=o_or, name="Opp OREB",
                                          marker_color=AWAY))
                    f_or.update_layout(barmode="group")
                    f_or.update_yaxes(title="OREB / game")
                    _style(f_or, 300)
                    st.plotly_chart(f_or, width="stretch", key="rb_oreb_q")
                with rqc2:
                    f_dr = go.Figure()
                    f_dr.add_trace(go.Bar(x=xq, y=t_dr, name="Team DREB",
                                          marker_color=BLUE))
                    f_dr.add_trace(go.Bar(x=xq, y=o_dr, name="Opp DREB",
                                          marker_color=AWAY))
                    f_dr.update_layout(barmode="group")
                    f_dr.update_yaxes(title="DREB / game")
                    _style(f_dr, 300)
                    st.plotly_chart(f_dr, width="stretch", key="rb_dreb_q")

                t_tot = [o + d for o, d in zip(t_or, t_dr)]
                o_tot = [o + d for o, d in zip(o_or, o_dr)]
                marg = [t - o for t, o in zip(t_tot, o_tot)]
                mc = [GOOD if v >= 0 else BAD for v in marg]
                fmg = go.Figure(go.Bar(
                    x=xq, y=marg, marker_color=mc, marker_line_width=0,
                    text=[f"{v:+.1f}" for v in marg], textposition="outside"))
                fmg.add_hline(y=0, line=dict(color="#30363d"))
                fmg.update_yaxes(title="REB margin / game (team − opp)")
                _style(fmg, 260)
                st.plotly_chart(fmg, width="stretch", key="rb_margin_q")
                st.caption("Who wins the glass each quarter — green = team out-"
                           "rebounds the opponent, red = gets out-rebounded.")

            # ── game-by-game rebounding trend ───────────────────────────────
            pgf = bundle["per_game_full"]
            if len(pgf) >= 2:
                st.markdown("<div class='lab-hdr'>Rebounding trend — game by game"
                            "</div>", unsafe_allow_html=True)
                gxr = [g["label"] for g in pgf]
                tot_v = [g["stats"]["REB"] for g in pgf]
                or_v = [g["stats"]["OREB"] for g in pgf]
                dr_v = [g["stats"]["DREB"] for g in pgf]
                ftr = go.Figure()
                ftr.add_trace(go.Bar(x=gxr, y=tot_v, name="Total REB",
                                     marker_color=GREY, opacity=0.4,
                                     marker_line_width=0))
                ftr.add_trace(go.Scatter(x=gxr, y=TA.rolling(tot_v, 3),
                                         name="Total (3G avg)", mode="lines+markers",
                                         line=dict(color=GOOD, width=2.5),
                                         marker=dict(size=6)))
                ftr.add_trace(go.Scatter(x=gxr, y=TA.rolling(or_v, 3),
                                         name="OREB (3G avg)", mode="lines+markers",
                                         line=dict(color=ACCENT, width=2),
                                         marker=dict(size=5)))
                ftr.add_trace(go.Scatter(x=gxr, y=TA.rolling(dr_v, 3),
                                         name="DREB (3G avg)", mode="lines+markers",
                                         line=dict(color=BLUE, width=2),
                                         marker=dict(size=5)))
                ftr.update_xaxes(tickangle=-45)
                ftr.update_yaxes(title="Rebounds")
                _style(ftr, 340)
                st.plotly_chart(ftr, width="stretch", key="rb_trend")
                st.caption("Bars = total rebounds each game; lines = 3-game "
                           "rolling averages for total, offensive and defensive.")

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

            dm2 = st.columns(5)
            dm2[0].metric("DREB%",
                          _pctf(S._safe(tb["DRB"], tb["DRB"] + ob["ORB"])),
                          help="Defensive-rebound rate — closing out opponent "
                               "possessions on the glass.")
            dm2[1].metric("BLK rate", _pctf(S._safe(tb["BLK"], ob["2PA"])),
                          help="Share of opponent 2-pt attempts blocked.")
            dm2[2].metric("STL / game", f"{tb['STL'] / ng:.1f}")
            dm2[3].metric("Opp OREB%", _pctf(ff["def"]["ORB"]),
                          help="Opponent offensive-rebound rate allowed — lower "
                               "is better.")
            dm2[4].metric("Net Rtg", f"{summ.get('NetRtg', 0):+.1f}")

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

            # opponent zone profile — separated into 2s and 3s
            st.markdown("<div class='lab-hdr'>Opponent shot profile — where "
                        "they attack us (2s vs 3s)</div>", unsafe_allow_html=True)
            zdt = bundle["zones_by_type"]["def"]   # {'all','2','3': {zone: agg}}
            zc1, zc2 = st.columns(2)
            with zc1:
                st.markdown("**Attempts allowed by zone**")
                st.plotly_chart(_zone_pair_bars(
                    zdt["2"], zdt["3"], "2-pt", "3-pt",
                    lambda a: a["FGA"], "Attempts allowed",
                    color_a=AWAY, color_b="#f0a500",
                    text_fn=lambda a: a["FGA"] or ""),
                    width="stretch", key="df_zfa_t")
            with zc2:
                st.markdown("**FG% allowed by zone**")
                st.plotly_chart(_zone_pair_bars(
                    zdt["2"], zdt["3"], "2P% allowed", "3P% allowed",
                    lambda a: a["FG%"] * 100, "FG% allowed",
                    color_a=AWAY, color_b="#f0a500",
                    text_fn=lambda a: f"{a['FG%']*100:.0f}%" if a["FGA"] else "—"),
                    width="stretch", key="df_zfg_t")

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

            # ── defense by quarter & half (opponent scoring by period) ───────
            st.markdown("<div class='lab-hdr'>Defense by quarter &amp; half</div>",
                        unsafe_allow_html=True)
            qbd = bundle["quarter_boxes"]
            if qbd:
                d_avg = summ.get("DRtg", 0) / 100

                def _opp(qsel):
                    pts = sum(qbd[q]["opp"]["PTS"] for q in qsel if q in qbd)
                    op = sum(qbd[q]["opp_poss"] for q in qsel if q in qbd)
                    ng_ = max((qbd[q]["n_games"] for q in qsel if q in qbd),
                              default=0) or ng
                    return pts / ng_, (pts / op if op else 0.0)

                dqrows = []
                for lbl, qsel in [("Q1", [1]), ("Q2", [2]), ("H1", [1, 2]),
                                  ("Q3", [3]), ("Q4", [4]), ("H2", [3, 4])]:
                    oppg, oppp = _opp(qsel)
                    dqrows.append({
                        "Period": lbl, "Opp PPG": round(oppg, 1),
                        "Opp PPP": round(oppp, 3),
                        "vs avg": f"{oppp - d_avg:+.3f}",
                        "Grade": "✓" if oppp <= d_avg else "✗"})
                st.dataframe(pd.DataFrame(dqrows), hide_index=True, width="stretch")
                st.caption(f"'vs avg' compares each period's opponent PPP to the "
                           f"team's season defensive rate ({d_avg:.3f}); ✓ = "
                           "better than average, ✗ = worse.")

                ql = ["Q1", "Q2", "Q3", "Q4"]
                opg = [_opp([q])[0] for q in range(1, 5)]
                oppp_q = [_opp([q])[1] for q in range(1, 5)]
                dq1, dq2 = st.columns(2)
                with dq1:
                    fpg = go.Figure(go.Bar(
                        x=ql, y=opg, marker_color=AWAY, marker_line_width=0,
                        text=[f"{v:.1f}" for v in opg], textposition="outside"))
                    fpg.update_yaxes(title="Opp PPG")
                    _style(fpg, 280)
                    fpg.update_layout(title="Opponent points by quarter")
                    st.plotly_chart(fpg, width="stretch", key="df_oppg_q")
                with dq2:
                    cpp = [BAD if v > d_avg else GOOD for v in oppp_q]
                    fpp = go.Figure(go.Bar(
                        x=ql, y=oppp_q, marker_color=cpp, marker_line_width=0,
                        text=[f"{v:.3f}" for v in oppp_q], textposition="outside"))
                    fpp.add_hline(y=d_avg, line=dict(color="#f0a500", dash="dot"),
                                  annotation_text=f"season {d_avg:.3f}",
                                  annotation_position="top left")
                    fpp.update_yaxes(title="Opp PPP")
                    _style(fpp, 280)
                    fpp.update_layout(title="Opponent PPP by quarter")
                    st.plotly_chart(fpp, width="stretch", key="df_oppp_q")

                qmap = {q: _opp([q])[1] for q in range(1, 5)}
                if any(qmap.values()):
                    worst = max(qmap, key=qmap.get)
                    best = min(qmap, key=qmap.get)
                    st.info(f"Toughest defensive quarter: **Q{worst}** "
                            f"({qmap[worst]:.3f} opp PPP)  ·  Best: **Q{best}** "
                            f"({qmap[best]:.3f} opp PPP).")

            # ── who guarded whom — defensive matchup grid ────────────────────
            st.markdown("<div class='lab-hdr'>Matchup grid — who guarded whom</div>",
                        unsafe_allow_html=True)
            st.caption("Reconstructed from the defender tagged on every contested "
                       "shot — the FG% each defender allowed the shooters they "
                       "covered, and how tough their assignments were (50 = average).")
            _mrows, _mdiff = _matchup_grid(gender, team_id, tuple(bundle["tracked_ids"]))
            if not _mrows:
                empty_state("No contested-shot data yet",
                            "Tag the defender on shots in the Game Tracker to build "
                            "the who-guarded-whom grid.", icon="🛡️")
            else:
                _md = pd.DataFrame(_mrows)
                _md["Defender"] = ("#" + _md["def_#"].astype(str) + " "
                                   + _md["defender"])
                _top = (_md.groupby("shooter")["FGA"].sum()
                        .sort_values(ascending=False).head(10).index.tolist())
                _sub = _md[_md["shooter"].isin(_top)]
                _pm = _sub.pivot_table(index="Defender", columns="shooter",
                                       values="FGM", aggfunc="sum")
                _pa = _sub.pivot_table(index="Defender", columns="shooter",
                                       values="FGA", aggfunc="sum")
                _grid = (_pm / _pa.replace(0, np.nan) * 100).round(0)
                st.caption("FG% allowed · defender (row) × shooter (column), top "
                           "shooters by volume. Blank = never matched up.")
                st.dataframe(_grid, width="stretch", key="mu_grid")

                _drows = []
                for p in players:
                    d = _mdiff.get(p["_pid"])
                    if d and d.get("shots_faced"):
                        _drows.append({
                            "Defender": f"#{p['number']} {p['name']}",
                            "Shots faced": int(d["shots_faced"]),
                            "Assignment difficulty": round(d.get("Difficulty100", 50)),
                        })
                if _drows:
                    _drows.sort(key=lambda r: -r["Assignment difficulty"])
                    st.markdown("**Toughest assignments** — attempt-weighted scorer "
                                "quality each defender faced")
                    st.dataframe(
                        pd.DataFrame(_drows), hide_index=True, width="stretch",
                        key="mu_diff",
                        column_config={"Assignment difficulty":
                                       st.column_config.ProgressColumn(
                                           "Assignment difficulty", format="%.0f",
                                           min_value=0, max_value=100)})

            # ── team foul timing ────────────────────────────────────────────
            st.markdown("<div class='pl-hdr'>Foul timing</div>",
                        unsafe_allow_html=True)
            _tf = _team_fouls(tuple(bundle["tracked_ids"])).get(team_id)
            if not _tf:
                empty_state("No fouls logged yet",
                            "Foul timing needs tracked games.", icon="⚠️")
            else:
                _fqv = [_tf["by_q"].get(q, 0) for q in range(1, 5)]
                _fm = st.columns(3)
                _fm[0].metric("Fouls / game",
                              f"{_tf['total'] / max(_tf['games'], 1):.1f}")
                _fm[1].metric("Opp FTA drawn", _tf["opp_fta"])
                _fm[2].metric("Total fouls", _tf["total"])
                _fqf = go.Figure(go.Bar(
                    x=["Q1", "Q2", "Q3", "Q4"], y=_fqv, marker_color=BAD,
                    marker_line_width=0, text=_fqv, textposition="outside"))
                _fqf.update_yaxes(title="Fouls committed")
                _style(_fqf, 260)
                st.plotly_chart(_fqf, width="stretch", key="df_foul_timing")
                st.caption("When the team fouls (Q4 spikes = late-game trouble / "
                           "putting opponents in the bonus). Opp FTA = free throws "
                           "your fouls gave up.")

        # ───────────────────────────────────────────── TRENDS ───────────────
        with ch_tr:
            if len(trend) < 2:
                st.info("Need at least two tracked games for trend charts.")
            else:
                # ── wins vs losses — moved up & expanded ────────────────────
                wl = bundle["wl_splits"]
                if wl["W"] and wl["L"]:
                    st.markdown("<div class='lab-hdr'>Wins vs losses — what "
                                "changes</div>", unsafe_allow_html=True)
                    wm = st.columns(4)
                    wm[0].metric("Record split",
                                 f"{wl['W']['n']}W · {wl['L']['n']}L")
                    wm[1].metric("Net rating swing",
                                 f"{wl['W']['NetRtg'] - wl['L']['NetRtg']:+.1f}",
                                 help=f"Wins {wl['W']['NetRtg']:+.1f} vs losses "
                                      f"{wl['L']['NetRtg']:+.1f} pts/100.")
                    wm[2].metric("eFG% swing",
                                 f"{(wl['W']['eFG'] - wl['L']['eFG'])*100:+.1f}pp")
                    wm[3].metric("Avg margin W / L",
                                 f"+{strk['avg_win_margin']:.0f} / "
                                 f"{strk['avg_loss_margin']:.0f}")
                    WL_CATS = [("Pts for", "PF", False), ("Pts against", "PA", False),
                               ("Margin", "MOV", False), ("Off Rtg", "ORtg", False),
                               ("Def Rtg", "DRtg", False), ("Net Rtg", "NetRtg", False),
                               ("Pace", "Pace", False), ("eFG%", "eFG", True),
                               ("Opp eFG%", "oeFG", True), ("FG%", "FG", True),
                               ("3P%", "TP", True), ("TS%", "TS", True),
                               ("Turnovers", "TOV", False), ("OREB", "ORB", False),
                               ("DREB", "DRB", False), ("Assists", "AST", False),
                               ("Steals", "STL", False), ("Blocks", "BLK", False)]
                    labels = [c[0] for c in WL_CATS]

                    def _wlv(side, key, ispct):
                        v = wl[side][key]
                        return v * 100 if ispct else v
                    wlf = go.Figure()
                    wlf.add_trace(go.Bar(
                        name="Wins", x=labels,
                        y=[_wlv("W", k, p) for _, k, p in WL_CATS],
                        marker_color=GOOD, marker_line_width=0))
                    wlf.add_trace(go.Bar(
                        name="Losses", x=labels,
                        y=[_wlv("L", k, p) for _, k, p in WL_CATS],
                        marker_color=BAD, marker_line_width=0))
                    wlf.update_layout(barmode="group")
                    wlf.update_yaxes(title="Per game (rates as %)")
                    wlf.update_xaxes(tickangle=-35)
                    _style(wlf, 380)
                    st.plotly_chart(wlf, width="stretch", key="tr_wl")
                    st.caption(f"Per-game averages in {wl['W']['n']} wins vs "
                               f"{wl['L']['n']} losses — the statistical fingerprint "
                               "of a win. Rate stats (eFG%, FG%, 3P%, TS%) shown as "
                               "percentages.")

                # ── every team stat over the tracked games (straight, individual)
                st.markdown("<div class='lab-hdr'>Every team stat over tracked "
                            "games</div>", unsafe_allow_html=True)
                st.caption("Each tracked stat as its own per-game line (oldest → "
                           "newest), with its straight average over the tracked "
                           "games (dotted).")
                _per_game_stat_grid(bundle["per_game_full"], TA.PER_GAME_STAT_SPEC,
                                    key_prefix="tr_pg")

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

                st.markdown("<div class='lab-hdr'>Efficiency — per game"
                            "</div>", unsafe_allow_html=True)
                ortg = [e["ORtg"] for e in trend]
                drtg = [e["DRtg"] for e in trend]
                eff = _trend_line(
                    tx, [("ORtg", ortg, ACCENT), ("DRtg", drtg, AWAY)],
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
#  CHARTS ▸ QUARTERS  (every tracked stat, split by quarter)
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _fx_chqt():
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

        # ── Shooting by Quarter (ported from APP3.0): the full shooting line
        #    for each quarter PLUS half (H1/H2) and Full-game summary rows, and a
        #    grouped FG%/3P%/eFG% bar over the quarters ─────────────────────────
        st.markdown("<div class='lab-hdr'>Shooting — full table by quarter"
                    "</div>", unsafe_allow_html=True)

        def _merge_qbox(qs_subset):
            """Sum the team boxes (+ poss) over a set of quarters into one box.
            Box dicts are pure additive counts, so S.* rate fns apply to the sum.
            Returns (merged_box, poss_sum, games) or (None, 0, 0) if none present."""
            qs_use = [q for q in qs_subset if q in qbx]
            if not qs_use:
                return None, 0, 0
            merged = {}
            for k, v0 in qbx[qs_use[0]]["team"].items():
                vals = [qbx[q]["team"][k] for q in qs_use]
                merged[k] = (sum(vals) if all(_is_num(v) for v in vals) else v0)
            poss_sum = sum(qbx[q]["poss"] for q in qs_use)
            games = max(qbx[q]["n_games"] for q in qs_use)
            return merged, poss_sum, games

        def _shot_row(label, b, poss_q, gp):
            return {
                "Period": label, "GP": gp,
                "FGA": b["FGA"], "FGM": b["FGM"], "FG%": _pctf(S.fg_pct(b)),
                "2PA": b["2PA"], "2P%": _pctf(S.fg2_pct(b)) if b["2PA"] else "—",
                "3PA": b["3PA"], "3P%": _pctf(S.fg3_pct(b)) if b["3PA"] else "—",
                "FTA": b["FTA"], "FT%": _pctf(S.ft_pct(b)) if b["FTA"] else "—",
                "eFG%": _pctf(S.efg(b)), "TS%": _pctf(S.ts(b)),
                "Paint%": (_pctf(S.paint_fg_pct(b)) if b["paint_FGA"] else "—"),
                "PPS": f"{S.pps(b):.2f}", "PPP": f"{S._safe(b['PTS'], poss_q):.2f}",
                "SCE": f"{S.shot_efficiency(b):.3f}", "PTS": b["PTS"],
            }

        reg = [q for q in qsq if q <= 4]
        ot = [q for q in qsq if q > 4]
        shot_rows = []
        for q in [x for x in reg if x in (1, 2)]:
            shot_rows.append(_shot_row(_q_label(q), qbx[q]["team"],
                                       qbx[q]["poss"], qbx[q]["n_games"]))
        h1b, h1p, h1g = _merge_qbox([1, 2])
        if h1b:
            shot_rows.append(_shot_row("H1", h1b, h1p, h1g))
        for q in [x for x in reg if x in (3, 4)]:
            shot_rows.append(_shot_row(_q_label(q), qbx[q]["team"],
                                       qbx[q]["poss"], qbx[q]["n_games"]))
        h2b, h2p, h2g = _merge_qbox([3, 4])
        if h2b:
            shot_rows.append(_shot_row("H2", h2b, h2p, h2g))
        for q in ot:   # overtime periods, each on its own line
            shot_rows.append(_shot_row(_q_label(q), qbx[q]["team"],
                                       qbx[q]["poss"], qbx[q]["n_games"]))
        fb, fp, fg = _merge_qbox(qsq)
        if fb:
            shot_rows.append(_shot_row("Full", fb, fp, fg))
        st.dataframe(pd.DataFrame(shot_rows), hide_index=True, width="stretch")
        st.caption("Full shooting line for every quarter, half (H1/H2) and the "
                   "whole game (pooled over tracked games). PPP = points per "
                   "possession that period.")

        # ── Shooting % by Quarter — grouped FG% / 3P% / eFG% bar ─────────────
        if reg:
            st.markdown("**Shooting % by Quarter**")
            fg_v = [S.fg_pct(qbx[q]["team"]) * 100 for q in reg]
            tp_v = [S.fg3_pct(qbx[q]["team"]) * 100 for q in reg]
            efg_v = [S.efg(qbx[q]["team"]) * 100 for q in reg]
            st.plotly_chart(
                _q_bars(reg,
                        [("FG%", fg_v, ACCENT), ("3P%", tp_v, BLUE),
                         ("eFG%", efg_v, GOOD)],
                        "%", height=320,
                        text_fmt=lambda v: f"{v:.0f}"),
                width="stretch", key="q_sh_pct")

        # ── Off-Pass vs Self-Created by Quarter (ported from APP3.0) ─────────
        cq = bundle.get("creation_quarter") or {}
        cr_total = sum(cq[q]["ast"]["FGA"] + cq[q]["sc"]["FGA"] for q in cq)
        if cq and cr_total:
            st.markdown("<div class='lab-hdr'>Off-Pass vs Self-Created by quarter"
                        "</div>", unsafe_allow_html=True)
            st.caption("Every team FG attempt split by how it was created — off a "
                       "teammate's pass (Off-Pass / assisted) vs taken with no pass "
                       "into the shot (Self-Created) — broken out by quarter.")
            creg = [q for q in qsq if q <= 4]

            def _cr_merge(lines):
                """Sum agg_shots lines (FGA/FGM/3PA/3PM) → totals + recomputed rates."""
                fga = sum(l["FGA"] for l in lines)
                fgm = sum(l["FGM"] for l in lines)
                tpa = sum(l["3PA"] for l in lines)
                tpm = sum(l["3PM"] for l in lines)
                return {"FGA": fga, "FGM": fgm, "3PA": tpa, "3PM": tpm,
                        "FG%": S._safe(fgm, fga), "3P%": S._safe(tpm, tpa),
                        "eFG%": S._safe(fgm + 0.5 * tpm, fga)}

            def _cr_row(label, qs):
                a = _cr_merge([cq[q]["ast"] for q in qs if q in cq])
                s = _cr_merge([cq[q]["sc"] for q in qs if q in cq])
                tot = a["FGA"] + s["FGA"]
                return {
                    "Period": label,
                    "Ast FGA": a["FGA"], "Ast FGM": a["FGM"],
                    "Ast FG%": _pctf(a["FG%"]) if a["FGA"] else "—",
                    "Ast 3PA": a["3PA"],
                    "Ast 3P%": _pctf(a["3P%"]) if a["3PA"] else "—",
                    "Ast eFG%": _pctf(a["eFG%"]) if a["FGA"] else "—",
                    "Ast%": _pctf(S._safe(a["FGA"], tot)) if tot else "—",
                    "SC FGA": s["FGA"], "SC FGM": s["FGM"],
                    "SC FG%": _pctf(s["FG%"]) if s["FGA"] else "—",
                    "SC 3PA": s["3PA"],
                    "SC 3P%": _pctf(s["3P%"]) if s["3PA"] else "—",
                    "SC eFG%": _pctf(s["eFG%"]) if s["FGA"] else "—",
                    "SC%": _pctf(S._safe(s["FGA"], tot)) if tot else "—",
                }

            cr_rows = [_cr_row(_q_label(q), [q]) for q in creg]
            if any(q in cq for q in (1, 2)):
                cr_rows.append(_cr_row("H1", [1, 2]))
            if any(q in cq for q in (3, 4)):
                cr_rows.append(_cr_row("H2", [3, 4]))
            cr_rows.append(_cr_row("Full", qsq))
            st.dataframe(pd.DataFrame(cr_rows), hide_index=True, width="stretch")

            # per-quarter series (Off-Pass = BLUE, Self-Created = BAD/red)
            af = [cq[q]["ast"]["FGA"] for q in creg]
            sf = [cq[q]["sc"]["FGA"] for q in creg]

            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown("**FGA volume by quarter**")
                st.plotly_chart(
                    _q_bars(creg, [("Off Pass", af, BLUE),
                                   ("Self-Created", sf, BAD)],
                            "FGA", height=300, mode="stack",
                            text_fmt=lambda v: f"{v:.0f}"),
                    width="stretch", key="cr_vol")
            with cc2:
                ap = [af[i] / (af[i] + sf[i]) * 100 if (af[i] + sf[i]) else 0
                      for i in range(len(creg))]
                spct = [100 - v for v in ap]
                st.markdown("**Shot creation mix %**")
                st.plotly_chart(
                    _q_bars(creg, [("Off Pass %", ap, BLUE), ("SC %", spct, BAD)],
                            "%", height=300, mode="stack",
                            text_fmt=lambda v: f"{v:.0f}%"),
                    width="stretch", key="cr_mix")

            cc3, cc4 = st.columns(2)
            with cc3:
                aefg = [cq[q]["ast"]["eFG"] * 100 for q in creg]
                sefg = [cq[q]["sc"]["eFG"] * 100 for q in creg]
                st.markdown("**eFG% by quarter**")
                st.plotly_chart(
                    _q_bars(creg, [("Off Pass eFG%", aefg, BLUE),
                                   ("SC eFG%", sefg, BAD)],
                            "%", height=300, text_fmt=lambda v: f"{v:.0f}"),
                    width="stretch", key="cr_efg")
            with cc4:
                afg = [cq[q]["ast"]["FG%"] * 100 for q in creg]
                sfg = [cq[q]["sc"]["FG%"] * 100 for q in creg]
                st.markdown("**FG% by quarter**")
                st.plotly_chart(
                    _q_bars(creg, [("Off Pass FG%", afg, BLUE),
                                   ("SC FG%", sfg, BAD)],
                            "%", height=300, text_fmt=lambda v: f"{v:.0f}"),
                    width="stretch", key="cr_fg")

            a3 = [cq[q]["ast"]["3P%"] * 100 for q in creg]
            s3 = [cq[q]["sc"]["3P%"] * 100 for q in creg]
            st.markdown("**3P% by quarter**")
            st.plotly_chart(
                _q_bars(creg, [("Off Pass 3P%", a3, BLUE), ("SC 3P%", s3, BAD)],
                        "%", height=300, text_fmt=lambda v: f"{v:.0f}"),
                width="stretch", key="cr_3p")

            fa = _cr_merge([cq[q]["ast"] for q in qsq])
            fs = _cr_merge([cq[q]["sc"] for q in qsq])
            ftot = fa["FGA"] + fs["FGA"]
            if ftot:
                st.info(
                    f"**Season split:** {fa['FGA'] / ftot * 100:.1f}% off-pass "
                    f"({fa['FGA']} FGA · {fa['eFG%'] * 100:.1f}% eFG%) · "
                    f"{fs['FGA'] / ftot * 100:.1f}% self-created "
                    f"({fs['FGA']} FGA · {fs['eFG%'] * 100:.1f}% eFG%)")

        # ── every glossary team stat, by quarter (full grid) ────────────────
        st.markdown("<div class='lab-hdr'>Every stat by quarter — full grid"
                    "</div>", unsafe_allow_html=True)
        QSPEC = [
            ("Points for / g", lambda d: d["team"]["PTS"] / max(d["n_games"], 1), "f1"),
            ("Points against / g", lambda d: d["opp"]["PTS"] / max(d["n_games"], 1), "f1"),
            ("Net / g", lambda d: (d["team"]["PTS"] - d["opp"]["PTS"]) / max(d["n_games"], 1), "f1"),
            ("Off Rating", lambda d: 100 * S._safe(d["team"]["PTS"], d["poss"]), "f1"),
            ("Def Rating", lambda d: 100 * S._safe(d["opp"]["PTS"], d["opp_poss"]), "f1"),
            ("Net Rating", lambda d: 100 * (S._safe(d["team"]["PTS"], d["poss"]) - S._safe(d["opp"]["PTS"], d["opp_poss"])), "f1"),
            ("Pace / g", lambda d: (d["poss"] + d["opp_poss"]) / 2 / max(d["n_games"], 1), "f1"),
            ("Points / poss", lambda d: S._safe(d["team"]["PTS"], d["poss"]), "f2"),
            ("FG%", lambda d: S.fg_pct(d["team"]) * 100, "pct"),
            ("2P%", lambda d: S.fg2_pct(d["team"]) * 100, "pct"),
            ("3P%", lambda d: S.fg3_pct(d["team"]) * 100, "pct"),
            ("FT%", lambda d: S.ft_pct(d["team"]) * 100, "pct"),
            ("eFG%", lambda d: S.efg(d["team"]) * 100, "pct"),
            ("TS%", lambda d: S.ts(d["team"]) * 100, "pct"),
            ("Paint FG%", lambda d: S.paint_fg_pct(d["team"]) * 100, "pct"),
            ("3PA rate", lambda d: S.three_par(d["team"]) * 100, "pct"),
            ("FT rate", lambda d: S.ftr(d["team"]) * 100, "pct"),
            ("FGA / g", lambda d: d["team"]["FGA"] / max(d["n_games"], 1), "f1"),
            ("3PA / g", lambda d: d["team"]["3PA"] / max(d["n_games"], 1), "f1"),
            ("FTA / g", lambda d: d["team"]["FTA"] / max(d["n_games"], 1), "f1"),
            ("OREB / g", lambda d: d["team"]["ORB"] / max(d["n_games"], 1), "f1"),
            ("DREB / g", lambda d: d["team"]["DRB"] / max(d["n_games"], 1), "f1"),
            ("REB / g", lambda d: d["team"]["TRB"] / max(d["n_games"], 1), "f1"),
            ("OREB%", lambda d: d["four_factors"]["off"]["ORB"] * 100, "pct"),
            ("TOV%", lambda d: d["four_factors"]["off"]["TOV"] * 100, "pct"),
            ("Assists / g", lambda d: d["team"]["AST"] / max(d["n_games"], 1), "f1"),
            ("Turnovers / g", lambda d: d["team"]["TOV"] / max(d["n_games"], 1), "f1"),
            ("AST / TO", lambda d: S._safe(d["team"]["AST"], d["team"]["TOV"]), "f2"),
            ("Steals / g", lambda d: d["team"]["STL"] / max(d["n_games"], 1), "f1"),
            ("Blocks / g", lambda d: d["team"]["BLK"] / max(d["n_games"], 1), "f1"),
            ("Stocks / g", lambda d: d["team"]["stocks"] / max(d["n_games"], 1), "f1"),
            ("Fouls / g", lambda d: d["team"]["PF"] / max(d["n_games"], 1), "f1"),
            ("Opp FG%", lambda d: S.fg_pct(d["opp"]) * 100, "pct"),
            ("Opp 3P%", lambda d: S.fg3_pct(d["opp"]) * 100, "pct"),
            ("Opp eFG%", lambda d: S.efg(d["opp"]) * 100, "pct"),
            ("Opp TS%", lambda d: S.ts(d["opp"]) * 100, "pct"),
            ("Forced TOV%", lambda d: d["four_factors"]["def"]["TOV"] * 100, "pct"),
        ]
        with st.expander("Show every stat by quarter (full grid)",
                         expanded=False):
            st.caption("Every team stat the app tracks, each as its own per-quarter "
                       "bar (pooled / averaged over tracked games).")
            qcols = st.columns(2)
            for i, (lbl, fn, kind) in enumerate(QSPEC):
                vals = [fn(qbx[q]) for q in qsq]
                tf = ((lambda v: f"{v:.0f}") if kind == "pct"
                      else (lambda v: f"{v:.2f}") if kind == "f2"
                      else (lambda v: f"{v:.1f}"))
                with qcols[i % 2]:
                    st.markdown(f"**{lbl}**")
                    st.plotly_chart(
                        _q_bars(qsq, [(lbl, vals, ACCENT)], lbl, height=260,
                                text_fmt=tf),
                        width="stretch", key=f"qgrid_{i}")

        # ── by tracked game: a stat across each game's quarters ─────────────
        st.markdown("<div class='lab-hdr'>By tracked game — quarter by quarter"
                    "</div>", unsafe_allow_html=True)
        qbg = bundle.get("quarter_by_game") or {}
        if qbg:
            QBG_STATS = [
                ("Points for", lambda d: d["team"]["PTS"]),
                ("Points against", lambda d: d["opp"]["PTS"]),
                ("Net points", lambda d: d["team"]["PTS"] - d["opp"]["PTS"]),
                ("Off Rating", lambda d: 100 * S._safe(d["team"]["PTS"], d["poss"])),
                ("Def Rating", lambda d: 100 * S._safe(d["opp"]["PTS"], d["opp_poss"])),
                ("FG%", lambda d: S.fg_pct(d["team"]) * 100),
                ("3P%", lambda d: S.fg3_pct(d["team"]) * 100),
                ("eFG%", lambda d: S.efg(d["team"]) * 100),
                ("TS%", lambda d: S.ts(d["team"]) * 100),
                ("Assists", lambda d: d["team"]["AST"]),
                ("Turnovers", lambda d: d["team"]["TOV"]),
                ("Rebounds", lambda d: d["team"]["TRB"]),
                ("OREB", lambda d: d["team"]["ORB"]),
                ("Stocks", lambda d: d["team"]["stocks"]),
            ]
            glabel = {g["game_id"]: f"{g['date'][5:]} {g['site']} {g['opp'][:8]}"
                      for g in log}
            stat_name = st.selectbox("Stat", [s[0] for s in QBG_STATS],
                                     key="q_bg_stat")
            fn = dict(QBG_STATS)[stat_name]
            bgf = go.Figure()
            for j, (gid, qd) in enumerate(sorted(
                    qbg.items(), key=lambda kv: glabel.get(kv[0], ""))):
                qs_g = sorted(qd)
                bgf.add_trace(go.Scatter(
                    x=[_q_label(q) for q in qs_g], y=[fn(qd[q]) for q in qs_g],
                    name=glabel.get(gid, str(gid)), mode="lines+markers",
                    line=dict(color=PALETTE[j % len(PALETTE)], width=2),
                    marker=dict(size=6)))
            bgf.update_yaxes(title=stat_name)
            _style(bgf, 420)
            st.plotly_chart(bgf, width="stretch", key="q_bg_chart")
            st.caption(f"{stat_name} by quarter, one line per tracked game — the "
                       "'by tracked-game quarter' view. Use it to spot games where "
                       "a quarter went sideways.")


# ══════════════════════════════════════════════════════════════════════════════
#  CHARTS ▸ ADVANCED  (the futuristic analytics lab: 5 sub-tabs)
# ══════════════════════════════════════════════════════════════════════════════
with ch_qt:
    _fx_chqt()


@st.fragment
def _fx_chadv():
    st.caption("The analytics lab — league-relative efficiency, team DNA, "
               "schedule résumé, the passing network and possession flow. (Shot "
               "Lab now lives under Charts → Shooting.) Most panels need tracked "
               "games; the résumé works from results alone.")

    adv_eff, adv_res, adv_play, adv_flow = st.tabs(
        ["Efficiency & DNA", "Résumé & Form", "Playmaking",
         "Game Flow"])

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


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7 — INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════
with ch_adv:
    _fx_chadv()


@st.fragment
def _fx_scout():
    st.caption("Game-day scouting report — keys to the game, four factors & "
               "tendencies, the 2s-vs-3s question, personnel and a printable "
               "sheet. Built from the same tracked-game engine as the rest of "
               "the page.")
    frame = st.radio("Framing", ["Scout opponent", "Self-scout (own team)"],
                     horizontal=True, key="scout_frame")
    _self = frame.startswith("Self")
    opp_label = "Self-scout" if _self else "Opponent scout"

    if _self:
        # self-scout: the WHOLE roster, nobody hidden
        sc = _scout(team_id, gender, None, ())
    else:
        # opponent scout: hide players who won't play (default = injured / out /
        # suspended from their availability), still picking from the full roster
        _avail = {r["id"]: (r["availability"] or "Active") for r in query(
            "SELECT id, availability FROM players WHERE team_id=? AND archived=0",
            (team_id,))}
        _names = {p["_pid"]: f"#{p['number']} {p['name']}" for p in players}
        _def_hide = sorted(pid for pid in _names
                           if _avail.get(pid, "Active")
                           in ("Out", "Injured", "Suspended"))
        _hide = st.multiselect(
            "Hide players (injured / suspended / won't play)", list(_names),
            default=_def_hide, format_func=lambda pid: _names.get(pid, str(pid)),
            key="scout_hide")
        sc = _scout(team_id, gender, None, tuple(sorted(_hide)))
        if _hide:
            st.caption("Off the scouting list: "
                       + ", ".join(_names[p] for p in _hide if p in _names) + ".")

    trk = sc["trk"]
    hcols = st.columns(5)
    hcols[0].metric("Record", sc["record"])
    hcols[1].metric("Power rank", f"#{sc['rank']}/{sc['of']}")
    hcols[2].metric("Off. rating", f"{trk['ORtg']:.0f}" if trk else "—")
    hcols[3].metric("Def. rating", f"{trk['DRtg']:.0f}" if trk else "—")
    hcols[4].metric("Pace", f"{trk['Pace']:.0f}" if trk else "—")

    if not sc["has_tracked"]:
        st.warning("No tracked-game data for this team — showing record & ratings "
                   "only. Track a game to unlock four factors, tendencies & "
                   "personnel.")

    # ── keys to the game ─────────────────────────────────────────────────────
    k1, k2 = st.columns(2)
    with k1:
        st.markdown("<div class='lab-hdr'>How to guard them</div>",
                    unsafe_allow_html=True)
        for gtip in sc["guard"]:
            st.markdown(f"- {gtip}")
    with k2:
        st.markdown("<div class='lab-hdr'>How to attack them</div>",
                    unsafe_allow_html=True)
        for atip in sc["attack"]:
            st.markdown(f"- {atip}")

    # ── four factors & tendencies (the single four-factors block) ────────────
    if sc["factors"]:
        st.markdown("<div class='lab-hdr'>Team profile — four factors & "
                    "tendencies</div>", unsafe_allow_html=True)
        ffx = [f for f in sc["factors"] if f["value"] is not None]
        ffig = go.Figure(go.Bar(
            x=[f["pct"] or 0 for f in ffx], y=[f["label"] for f in ffx],
            orientation="h",
            marker_color=[GOOD if (f["pct"] or 0) >= 60 else
                          (BAD if (f["pct"] or 0) <= 40 else "#8b949e")
                          for f in ffx],
            text=[f"{f['value']:.1f} · "
                  f"{('%.0f'%f['pct']) if f['pct'] is not None else '—'} pctl"
                  for f in ffx], textposition="auto", marker_line_width=0))
        ffig.add_vline(x=50, line=dict(color="#8b949e", width=1, dash="dot"))
        ffig.update_xaxes(title="League percentile", range=[0, 100])
        _style(ffig, max(300, 40*len(ffx)))
        st.plotly_chart(ffig, width="stretch", key="scout_factors")

        scs1, scs2 = st.columns(2)
        with scs1:
            if sc["strengths"]:
                st.markdown("**Strengths (≥70th pctl)**")
                for f in sc["strengths"]:
                    st.markdown(f"- {f['label']} — {f['value']:.1f} "
                                f"({f['pct']:.0f}th)")
        with scs2:
            if sc["weaknesses"]:
                st.markdown("**Exploit (≤30th pctl)**")
                for f in sc["weaknesses"]:
                    st.markdown(f"- {f['label']} — {f['value']:.1f} "
                                f"({f['pct']:.0f}th)")

        # ── identity & tendencies (a couple meaningful extra reads) ─────────
        if has_tracked:
            crb_sc = bundle["creation_breakdown"]
            tot_fga = crb_sc["total"]["FGA"] or 1
            self_sh = 100 * (crb_sc["self"]["FGA"]
                             + crb_sc["created"]["FGA"]) / tot_fga
            pass_sh = 100 * (crb_sc["pass"]["FGA"]
                             + crb_sc["both"]["FGA"]) / tot_fga
            pace_v = summ.get("POSS_pg", 0)
            tm = st.columns(4)
            tm[0].metric("Pace", f"{pace_v:.0f}", help="Possessions / game.")
            tm[1].metric("Paint scoring", _pctf(soff["pct_paint"]),
                         help="Share of points scored in the paint.")
            tm[2].metric("Self-created FG", f"{self_sh:.0f}%",
                         help="Share of FGA the shooter made/took without a pass "
                              "into the shot.")
            tm[3].metric("Contested rate",
                         _pctf(bundle["guarded"]["guard_share"]),
                         help="Share of their shots that were contested.")
            tempo = ("up-tempo" if pace_v >= 70 else
                     "controlled" if pace_v >= 60 else "slow, grind-it-out")
            style = ("isolation / shot-maker heavy" if self_sh >= 55 else
                     "ball-movement / motion" if pass_sh >= 60 else
                     "balanced shot creation")
            inside = ("paint-oriented" if soff["pct_paint"] >= 0.5 else
                      "perimeter / 3-happy" if brk["3PAr"] >= 0.40 else "two-level")
            st.markdown(f"**Style read:** {tempo} pace · {style} · {inside} attack "
                        f"— {self_sh:.0f}% of shots self-created, {pass_sh:.0f}% "
                        "off a pass. Speeding them up or walling the paint attacks "
                        "the profile above.")

    if has_tracked:

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
            tips.append("**Efficient shooting team** — eFG% "
                        f"{_pctf(ff['off']['eFG'])}; contest everything and keep "
                        "them off the offensive glass.")
        elif ff["off"]["eFG"] <= 0.42:
            tips.append("**Below-average shooting** — eFG% "
                        f"{_pctf(ff['off']['eFG'])}; pack the paint and live with "
                        "contested jumpers.")
        if ff["off"]["TOV"] >= 0.18:
            tips.append("**Turnover-prone** — gives it away on "
                        f"{_pctf(ff['off']['TOV'])} of trips; pressure the ball "
                        "to force live-ball turnovers.")
        if ff["off"]["ORB"] >= 0.33:
            tips.append("**Crashes the offensive glass** — OREB% "
                        f"{_pctf(ff['off']['ORB'])}; box out and secure the "
                        "first rebound.")
        if soff["pct_paint"] >= 0.50:
            tips.append("**Paint-heavy offense** — "
                        f"{_pctf(soff['pct_paint'])} of points in the paint; wall "
                        "up the rim and make them prove the jumper.")
        elif brk["3PAr"] >= 0.40:
            tips.append("**Lives behind the arc** — "
                        f"{_pctf(brk['3PAr'])} of shots are threes; run them off "
                        "the line.")
        # defense
        if ff["def"]["TOV"] >= 0.18:
            tips.append("**Forces turnovers** — takes it away on "
                        f"{_pctf(ff['def']['TOV'])} of opponent trips; value "
                        "every possession and limit careless passes.")
        if ff["def"]["eFG"] <= 0.44:
            tips.append("**Locks down shots** — holds opponents to "
                        f"{_pctf(ff['def']['eFG'])} eFG; attack early before the "
                        "defense sets.")
        # tempo
        pace = summ.get("POSS_pg", 0)
        if pace >= 70:
            tips.append("**Plays fast** — "
                        f"{pace:.0f} possessions/game; control tempo to shorten "
                        "the game if you're the underdog.")
        elif pace and pace < 60:
            tips.append("**Slow, deliberate pace** — "
                        f"{pace:.0f} possessions/game; speed them up to drag them "
                        "out of their comfort zone.")
        # leaning on a star
        rated_pl = [p for p in players if p["PPG"] is not None]
        if rated_pl:
            top = max(rated_pl, key=lambda p: p["PPG"])
            share = top["PTS"] / max(tb["PTS"], 1)
            if share >= 0.28:
                tips.append(f"**Star-dependent** — #{top['number']} "
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

    # ── personnel ────────────────────────────────────────────────────────────
    if sc["personnel"]:
        st.markdown("<div class='lab-hdr'>Personnel</div>", unsafe_allow_html=True)
        sc_arch = _archetypes(gender)
        prow_by_name = {p["name"]: p for p in players}
        for p in sc["personnel"]:
            bdg = "  ".join(p["badges"])
            row = prow_by_name.get(p["name"])
            archlbl = sc_arch.get(row["_pid"]) if row else None
            usg = row.get("USG%") if row else None
            selfcr = row.get("SelfCr%") if row else None
            q4 = row.get("Q4PPG") if row else None
            extra = []
            if usg is not None:
                extra.append(f"USG {usg:.0f}%")
            if selfcr is not None:
                extra.append(f"self-cr {selfcr:.0f}%")
            if q4 is not None:
                extra.append(f"Q4 {q4:.1f} ppg")
            extra_html = (f"<br><span style='font-size:12px;color:#8b949e'>"
                          f"{' · '.join(extra)}</span>" if extra else "")
            arch_html = (f" <span class='stat-chip' style='font-size:11px'>"
                         f"{html.escape(archlbl)}</span>" if archlbl else "")
            st.markdown(
                f"<div class='glass-tile' style='margin-bottom:8px'>"
                f"<b>#{p['num']} {html.escape(p['name'])}</b> "
                f"<span style='color:#8b949e'>OVR "
                f"{p['ovr'] if p['ovr'] is not None else '—'}</span>{arch_html}<br>"
                f"<span style='font-size:13px'>{(p['ppg'] or 0):.1f} ppg · "
                f"{(p['rpg'] or 0):.1f} reb · {(p['apg'] or 0):.1f} ast · "
                f"3P {('%.0f%%'%p['tp']) if p['tp'] is not None else '—'} · "
                f"TS {('%.0f%%'%p['ts']) if p['ts'] is not None else '—'}</span>"
                f"{extra_html}<br>"
                f"<span style='color:{ACCENT};font-size:13px'>▶ "
                f"{html.escape(p['note'])}</span>"
                + (f"<br><span style='font-size:12px;color:#8b949e'>"
                   f"{html.escape(bdg)}</span>" if bdg else "")
                + "</div>", unsafe_allow_html=True)

    # ── shooting by zone (2s vs 3s) ─────────────────────────────────────────
    if has_tracked and bundle.get("zones_by_type"):
        st.markdown("<div class='lab-hdr'>Shooting by zone — 2s vs 3s</div>",
                    unsafe_allow_html=True)
        zbt_sc = bundle["zones_by_type"]["off"]
        sz1, sz2 = st.columns(2)
        with sz1:
            st.markdown("**Attempts by zone**")
            st.plotly_chart(_zone_pair_bars(
                zbt_sc["2"], zbt_sc["3"], "2-pt", "3-pt",
                lambda a: a["FGA"], "Attempts",
                text_fn=lambda a: a["FGA"] or ""),
                width="stretch", key="scout_zones_a")
        with sz2:
            st.markdown("**FG% by zone**")
            st.plotly_chart(_zone_pair_bars(
                zbt_sc["2"], zbt_sc["3"], "2P%", "3P%",
                lambda a: a["FG%"] * 100, "FG%",
                text_fn=lambda a: f"{a['FG%']*100:.0f}%" if a["FGA"] else "—"),
                width="stretch", key="scout_zones_fg")
        st.caption("Where they shoot and how they finish, split by shot value.")
    elif sc["zones"] and any(z["FGA"] for z in sc["zones"].values()):
        st.markdown("<div class='lab-hdr'>Shooting by zone</div>",
                    unsafe_allow_html=True)
        zfig = go.Figure(go.Bar(
            x=[SC.ZONE_LABELS[z] for z in S.ZONES],
            y=[sc["zones"][z]["FGA"] for z in S.ZONES],
            marker_color=ACCENT, marker_line_width=0,
            text=[f"{sc['zones'][z]['FGM']}/{sc['zones'][z]['FGA']} · "
                  f"{sc['zones'][z]['pct']:.0f}%" for z in S.ZONES],
            textposition="auto"))
        zfig.update_yaxes(title="Attempts")
        _style(zfig, 320)
        st.plotly_chart(zfig, width="stretch", key="scout_zones")

    # ── scoring by possession length (when tracked) ──────────────────────────
    if has_tracked and bundle.get("poss_length"):
        _plen = [r for r in bundle["poss_length"]
                 if r["label"] != "Untimed" and r["FGA"]]
        if _plen:
            st.markdown("<div class='lab-hdr'>Scoring by possession length</div>",
                        unsafe_allow_html=True)
            _plf = go.Figure(go.Bar(
                x=[r["label"] for r in _plen], y=[r["PPP"] for r in _plen],
                marker_color=ACCENT, marker_line_width=0,
                text=[f"{r['PPP']:.2f} · {r['FGA']} FGA · {r['FG%'] * 100:.0f}%"
                      for r in _plen], textposition="auto"))
            _plf.update_yaxes(title="Points per shot")
            _style(_plf, 300)
            st.plotly_chart(_plf, width="stretch", key="scout_plen")
            st.caption("How they score by tempo — transition (≤6s) vs early vs "
                       "half-court. If they spike in transition, get back on "
                       "defense; if half-court is weak, make them play in a crowd.")

    # ── game-plan notes (opponent scout) ─────────────────────────────────────
    if not _self:
        st.markdown("<div class='lab-hdr'>Game-plan notes</div>",
                    unsafe_allow_html=True)
        SB.render_notes(team_id)

    # ── printable export ─────────────────────────────────────────────────────
    st.markdown("<div class='lab-hdr'>Printable scout sheet</div>",
                unsafe_allow_html=True)
    html_doc = SC.printable_html(sc, opp_label)
    st.download_button(
        "Download printable scout (HTML — open & print to PDF)",
        data=html_doc, file_name=f"scout_{sc['name'].replace(' ', '_')}.html",
        mime="text/html", key="scout_dl")
    with st.expander("Preview printable sheet"):
        components.html(html_doc, height=620, scrolling=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 8 — HELPER  (the orphaned helper engines: Predictor + Impact Lab + Lineup)
# ══════════════════════════════════════════════════════════════════════════════
# Helper tab dissolved: matchup Predictor removed, Lineup creator moved to the War
# Room page, Impact Lab moved here under Charts. `if True:` preserves the moved
# Impact-Lab block's original indentation (no wholesale re-indent).
if True:
    h_impact = ch_impact

    with h_impact:
        if not has_tracked:
            st.info("Tracked games needed for the impact lab (RAPM, WPA, chemistry "
                    "and lineups all run on possession data).")
        else:
            tids = bundle["tracked_ids"]
            my_pids = {p["_pid"] for p in players}
            name_by = {p["_pid"]: f"#{p['number']} {p['name']}" for p in players}

            # ── RAPM ────────────────────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>RAPM — regularized adjusted +/−"
                        "</div>", unsafe_allow_html=True)
            st.caption("Points added per 100 possessions vs a league-average "
                       "player, holding teammates AND opponents constant (one ridge "
                       "regression over every tracked possession in the league). "
                       "Directional on a small book.")
            rap = _rapm(gender)
            rows_r = sorted([v for pid, v in rap.items() if pid in my_pids],
                            key=lambda v: v["RAPM"], reverse=True)
            if rows_r:
                rc1, rc2 = st.columns([3, 2])
                with rc1:
                    seq = list(reversed(rows_r))
                    rf = go.Figure()
                    rf.add_trace(go.Bar(
                        x=[v["ORAPM"] for v in seq], y=[v["name"] for v in seq],
                        name="O-RAPM", orientation="h", marker_color=ACCENT))
                    rf.add_trace(go.Bar(
                        x=[v["DRAPM"] for v in seq], y=[v["name"] for v in seq],
                        name="D-RAPM", orientation="h", marker_color=BLUE))
                    rf.update_layout(barmode="relative")
                    rf.update_xaxes(title="Pts / 100 vs average")
                    _style(rf, max(220, 32 * len(seq) + 60))
                    rf.update_layout(margin=dict(l=4, r=14, t=6, b=30))
                    st.plotly_chart(rf, width="stretch", key="il_rapm")
                with rc2:
                    st.dataframe(pd.DataFrame([{
                        "Player": v["name"], "RAPM": v["RAPM"],
                        "O": v["ORAPM"], "D": v["DRAPM"], "Poss": v["poss"],
                    } for v in rows_r]), hide_index=True, width="stretch")

                # ── RAPM with uncertainty (95% CI from the unregularized fit) ──
                inf_rows = [v for v in rows_r if v.get("RAPM_se") is not None]
                if inf_rows:
                    st.markdown("<div class='lab-hdr'>RAPM uncertainty — how firm "
                                "is each estimate?</div>", unsafe_allow_html=True)
                    sequ = list(reversed(inf_rows))
                    xs = [v["RAPM"] for v in sequ]
                    half = [1.96 * v["RAPM_se"] for v in sequ]
                    nm = [v["name"] for v in sequ]
                    sig = [abs(v["RAPM"]) > h for v, h in zip(sequ, half)]
                    dot = [("#3fb950" if x > 0 else "#e74c3c") if s else "#6b7280"
                           for s, x in zip(sig, xs)]
                    ef = go.Figure(go.Scatter(
                        x=xs, y=nm, mode="markers", customdata=half,
                        error_x=dict(type="data", array=half, color="#8b949e",
                                     thickness=1.1, width=4),
                        marker=dict(size=10, color=dot, line=dict(width=0)),
                        hovertemplate="%{y}: RAPM %{x:.1f} ± %{customdata:.1f}"
                                      "<extra></extra>"))
                    ef.add_vline(x=0, line=dict(color="#8b949e", width=1, dash="dot"))
                    ef.update_xaxes(title="RAPM (pts / 100) · whisker = 95% CI")
                    _style(ef, max(220, 30 * len(sequ) + 60))
                    ef.update_layout(margin=dict(l=4, r=14, t=6, b=30),
                                     showlegend=False)
                    st.plotly_chart(ef, width="stretch", key="il_rapm_ci")
                    st.caption(
                        f"Dot = regularized RAPM (the ranking number). Whisker = 95% "
                        f"CI from the unregularized fit — how tightly the ~15-game "
                        f"sample pins each player down. {sum(sig)} of {len(sequ)} "
                        "clear zero (green/red = distinguishable from average; grey = "
                        "not yet). Wide bands are the honest signal that small samples "
                        "can't separate most players.")
            else:
                st.caption("Not enough possessions to solve RAPM for this team yet.")

            # ── win probability added ────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>Win Probability Added (WPA)</div>",
                        unsafe_allow_html=True)
            wmode = st.radio(
                "Model", ["Scoring", "Possession"], horizontal=True,
                key="il_wpa_mode",
                help="Scoring = win-prob swing on made baskets. Possession = value "
                     "over an average possession on every shot AND turnover, split "
                     "into offense and defense (credits stops, steals, blocks).")
            sw = _season_wpa(gender, "scoring" if wmode == "Scoring" else "possession")
            wrows = sorted([dict(v, _pid=pid) for pid, v in sw.items()
                            if pid in my_pids],
                           key=lambda v: v.get("wpa", 0), reverse=True)
            if wrows:
                if wmode == "Scoring":
                    wdf = pd.DataFrame([{
                        "Player": v["name"], "WPA": round(v["wpa"], 3),
                        "Clutch WPA": round(v["clutch_wpa"], 3),
                        "WPA / game": round(v["wpa_per_game"], 3),
                        "Plays": v["plays"], "Games": v["games"],
                    } for v in wrows])
                else:
                    wdf = pd.DataFrame([{
                        "Player": v["name"], "WPA": round(v["wpa"], 3),
                        "Off WPA": round(v.get("off_wpa", 0), 3),
                        "Def WPA": round(v.get("def_wpa", 0), 3),
                        "Clutch WPA": round(v.get("clutch_wpa", 0), 3),
                        "Plays": v["plays"],
                    } for v in wrows])
                wc1, wc2 = st.columns([3, 2])
                with wc1:
                    seq = list(reversed(wrows))
                    st.plotly_chart(_leader_bar(
                        wrows, "wpa", lambda v: v["name"],
                        lambda v: v["wpa"], lambda x: f"{x:.2f}",
                        height=max(220, 30 * len(wrows) + 50)),
                        width="stretch", key="il_wpa_bar")
                with wc2:
                    st.dataframe(wdf, hide_index=True, width="stretch")
            else:
                st.caption("No win-probability plays recorded for this team yet.")

            # ── chemistry (pair net) ─────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>Chemistry — pair net rating</div>",
                        unsafe_allow_html=True)
            st.caption("Team net points / 100 while a pair of players share the "
                       "floor. Positive = the duo outscores opponents together.")
            chem = _chemistry(team_id, tuple(tids))
            edges = chem.get("edges", [])
            if len(edges) >= 1:
                cn1, cn2 = st.columns([3, 2])
                with cn1:
                    nodes = {n["pid"]: n for n in chem["nodes"]}
                    node_ids = [pid for pid in (
                        sorted(nodes, key=lambda i: nodes[i]["poss"], reverse=True))
                        if pid in name_by][:8]
                    if len(node_ids) >= 2:
                        nn = len(node_ids)
                        pos = {pid: (math.cos(2*math.pi*k/nn - math.pi/2),
                                     math.sin(2*math.pi*k/nn - math.pi/2))
                               for k, pid in enumerate(node_ids)}
                        net = go.Figure()
                        emax = max((abs(e["net"]) for e in edges), default=1) or 1
                        for e in edges:
                            a, b = e["a"], e["b"]
                            if a not in pos or b not in pos:
                                continue
                            x0, y0 = pos[a]
                            x1, y1 = pos[b]
                            clr = GOOD if e["net"] >= 0 else BAD
                            net.add_trace(go.Scatter(
                                x=[x0, x1], y=[y0, y1], mode="lines",
                                line=dict(width=1 + 4 * abs(e["net"]) / emax,
                                          color=clr),
                                hoverinfo="text",
                                hovertext=f"{e['names'][0]} + {e['names'][1]}: "
                                          f"net {e['net']:+.1f} ({e['poss']} poss)",
                                opacity=0.55, showlegend=False))
                        net.add_trace(go.Scatter(
                            x=[pos[i][0] for i in node_ids],
                            y=[pos[i][1] for i in node_ids], mode="markers+text",
                            marker=dict(
                                size=[18 + 26 * (nodes[i]["poss"]
                                      / max(nodes[n]["poss"] for n in node_ids))
                                      for i in node_ids],
                                color=[nodes[i]["net"] for i in node_ids],
                                colorscale="RdYlGn", cmid=0, showscale=True,
                                colorbar=dict(title="Solo net"),
                                line=dict(width=2, color="#0d1117")),
                            text=[name_by.get(i, "?").split()[0] for i in node_ids],
                            textposition="middle center",
                            textfont=dict(size=9, color="#0d1117"),
                            hovertext=[f"{name_by.get(i,'?')}<br>"
                                       f"net {nodes[i]['net']:+.1f} · "
                                       f"{nodes[i]['poss']} poss" for i in node_ids],
                            hovertemplate="%{hovertext}<extra></extra>",
                            showlegend=False))
                        net.update_xaxes(visible=False, range=[-1.45, 1.45])
                        net.update_yaxes(visible=False, range=[-1.45, 1.45],
                                         scaleanchor="x", scaleratio=1)
                        _style(net, 420)
                        net.update_layout(plot_bgcolor="rgba(0,0,0,0)",
                                          margin=dict(l=10, r=10, t=10, b=10))
                        st.plotly_chart(net, width="stretch", key="il_chem_net")
                        st.caption("Green lines = pairs that outscore opponents "
                                   "together; red = get outscored. Line thickness = "
                                   "size of the effect.")
                with cn2:
                    top_pairs = sorted(edges, key=lambda e: e["net"],
                                       reverse=True)
                    st.dataframe(pd.DataFrame([{
                        "Pair": f"{e['names'][0]} + {e['names'][1]}",
                        "Net": e["net"], "Poss": e["poss"],
                    } for e in top_pairs]), hide_index=True, width="stretch",
                        height=min(420, 60 + 32 * len(top_pairs)))
            else:
                st.caption("Not enough shared-floor possessions to draw chemistry "
                           "pairs yet.")

            # ── observed lineup units ────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>Lineups — observed 5-man units"
                        "</div>", unsafe_allow_html=True)
            st.caption("Net rating for each exact five that shared the floor for "
                       "enough possessions (observed, not simulated).")
            units = _units(team_id, tuple(tids))
            if units:
                st.dataframe(pd.DataFrame([{
                    "Lineup": " · ".join(u["names"]),
                    "ORtg": u["ORtg"], "DRtg": u["DRtg"], "Net": u["Net"],
                    "Off poss": u["off_poss"], "Def poss": u["def_poss"],
                } for u in units]), hide_index=True, width="stretch",
                    height=min(460, 60 + 32 * len(units)))
            else:
                st.caption("No 5-man unit cleared the minimum possessions yet.")


# ══════════════════════════════════════════════════════════════════════════════
#  CHARTS ▸ BUILD YOUR OWN CHART  (a free-form chart lab over the team's data)
# ══════════════════════════════════════════════════════════════════════════════
with tab_scout:
    _fx_scout()


@st.fragment
def _fx_chbld():
    st.caption("Build-your-own chart lab — pick a dataset, a chart type and the "
               "stat(s) you want on it (one or many). Everything updates live; "
               "hover the chart and use its toolbar to zoom or download a PNG.")

    # ── assemble the plottable datasets (one tidy table per entity type) ────
    def _player_df(rows):
        """Players → one row each, Label + every numeric stat (None-safe)."""
        cols = []
        for p in rows:
            for kk, vv in p.items():
                if str(kk).startswith("_") or kk in ("name", "number", "team_id"):
                    continue
                if _is_num(vv) and kk not in cols:
                    cols.append(kk)
        out = []
        for p in rows:
            d = {"Label": f"#{p['number']} {p['name']}"}
            for kk in cols:
                vv = p.get(kk)
                d[kk] = vv if _is_num(vv) else None
            out.append(d)
        return pd.DataFrame(out)

    datasets = {}
    if players:
        datasets["Players"] = _player_df(players)
    if log:
        _tmap = {e["game_id"]: e for e in (bundle["trend"] or [])}
        _grows = []
        for g in log:
            d = {"Label": f"{g['date'][5:]} {g['site']} {g['opp'][:12]}",
                 "Date": g["date"], "Pts For": g["pf"], "Pts Agn": g["pa"],
                 "Margin": g["margin"], "Win": 1 if g["won"] else 0}
            e = _tmap.get(g["game_id"])
            if e:
                for kk in ("ORtg", "DRtg", "NetRtg", "PPP", "oPPP", "Pace",
                           "eFG", "oeFG", "TOV", "STL", "AST", "FGA"):
                    vv = e.get(kk)
                    if _is_num(vv):
                        d[kk] = vv * 100 if kk in ("eFG", "oeFG") else vv
            _grows.append(d)
        datasets["Games"] = pd.DataFrame(_grows)
    _qbx_b = bundle["quarter_boxes"]
    if _qbx_b:
        _qrows = []
        for q in sorted(_qbx_b):
            dd = _qbx_b[q]
            tbq, obq, n = dd["team"], dd["opp"], max(dd["n_games"], 1)
            _qrows.append({
                "Label": _q_label(q),
                "Pts For/G": tbq["PTS"] / n, "Pts Agn/G": obq["PTS"] / n,
                "Net/G": (tbq["PTS"] - obq["PTS"]) / n,
                "ORtg": 100 * S._safe(tbq["PTS"], dd["poss"]),
                "DRtg": 100 * S._safe(obq["PTS"], dd["opp_poss"]),
                "PPP": S._safe(tbq["PTS"], dd["poss"]),
                "FG%": S.fg_pct(tbq) * 100, "3P%": S.fg3_pct(tbq) * 100,
                "eFG%": S.efg(tbq) * 100, "Opp FG%": S.fg_pct(obq) * 100,
                "FGA/G": tbq["FGA"] / n, "3PA/G": tbq["3PA"] / n,
                "FTA/G": tbq["FTA"] / n, "OREB/G": tbq["ORB"] / n,
                "DREB/G": tbq["DRB"] / n, "AST/G": tbq["AST"] / n,
                "TOV/G": tbq["TOV"] / n, "STL/G": tbq["STL"] / n,
                "BLK/G": tbq["BLK"] / n, "Stocks/G": tbq["stocks"] / n,
                "Fouls/G": tbq["PF"] / n,
            })
        datasets["Quarters"] = pd.DataFrame(_qrows)

    if not datasets:
        st.info("No data to chart yet — enter games (and track a few in the Game "
                "Tracker) to unlock the chart builder.")
    else:
        top = st.columns([1, 1])
        ds_name = top[0].selectbox(
            "Dataset", list(datasets), key="bld_ds",
            help="Players = one row per player · Games = one row per game "
                 "(efficiency stats fill in for tracked games) · Quarters = one "
                 "row per quarter, averaged over tracked games.")
        CHART_TYPES = ["Bar", "Horizontal bar", "Line", "Area", "Scatter",
                       "Bubble", "Pie", "Donut", "Radar", "Histogram",
                       "Box plot", "Correlation heatmap", "Data table"]
        ctype = top[1].selectbox("Chart type", CHART_TYPES, key="bld_type")

        df = datasets[ds_name]
        num_cols = [c for c in df.columns if c not in ("Label", "Date")
                    and pd.api.types.is_numeric_dtype(df[c])]
        cat_cols = ["Label"] + [c for c in df.columns if c == "Date"]
        k = ds_name   # scope widget keys per-dataset so options never go stale

        if not num_cols:
            st.info("This dataset has no numeric stats to plot yet.")

        # ── category-vs-value charts: one X, many Y ─────────────────────────
        elif ctype in ("Bar", "Horizontal bar", "Line", "Area"):
            r1 = st.columns([1, 2])
            xcol = r1[0].selectbox("X axis (labels)", cat_cols + num_cols,
                                   index=0, key=f"bld_x_{k}")
            default_y = num_cols[:2] if len(num_cols) >= 2 else num_cols[:1]
            ys = r1[1].multiselect("Stat(s) to plot — pick one or many", num_cols,
                                   default=default_y, key=f"bld_y_{k}")
            with st.expander("Options"):
                o = st.columns(4)
                sort_by = o[0].selectbox("Sort by", ["(dataset order)"] + ys) \
                    if ys else "(dataset order)"
                descending = o[1].checkbox("Descending", value=True,
                                           key=f"bld_desc_{k}")
                topn = o[2].number_input("Top N (0 = all)", 0, len(df), 0, 1,
                                         key=f"bld_top_{k}")
                show_vals = o[3].checkbox("Show values", value=False,
                                          key=f"bld_val_{k}")
                stacked = (o[3].checkbox("Stacked", value=False,
                                         key=f"bld_stack_{k}")
                           if ctype in ("Bar", "Horizontal bar", "Area")
                           else False)
            if not ys:
                st.info("Pick at least one stat to plot.")
            else:
                d = df.copy()
                if sort_by in ys:
                    d = d.sort_values(sort_by, ascending=not descending,
                                      na_position="last")
                if topn:
                    d = d.head(int(topn))
                if ctype == "Horizontal bar" and sort_by in ys:
                    d = d.iloc[::-1]   # largest ends up on top
                xv = d[xcol].tolist()
                fig = go.Figure()
                for i, ycol in enumerate(ys):
                    clr = PALETTE[i % len(PALETTE)]
                    yv = d[ycol].tolist()
                    txt = ([("" if v is None or pd.isna(v) else f"{v:g}")
                            for v in yv] if show_vals else None)
                    if ctype == "Line":
                        fig.add_trace(go.Scatter(
                            x=xv, y=yv, name=ycol,
                            mode="lines+markers+text" if show_vals
                            else "lines+markers",
                            line=dict(color=clr, width=3), marker=dict(size=7),
                            text=txt, textposition="top center"))
                    elif ctype == "Area":
                        if stacked:
                            fig.add_trace(go.Scatter(
                                x=xv, y=yv, name=ycol, mode="lines",
                                line=dict(color=clr, width=1.5),
                                stackgroup="one"))
                        else:
                            rr, gg, bb = _rgb(clr)
                            fig.add_trace(go.Scatter(
                                x=xv, y=yv, name=ycol, mode="lines",
                                line=dict(color=clr, width=2.5), fill="tozeroy",
                                fillcolor=f"rgba({rr},{gg},{bb},0.22)"))
                    elif ctype == "Horizontal bar":
                        fig.add_trace(go.Bar(
                            y=xv, x=yv, name=ycol, orientation="h",
                            marker_color=clr, marker_line_width=0,
                            text=txt, textposition="auto"))
                    else:   # Bar
                        fig.add_trace(go.Bar(
                            x=xv, y=yv, name=ycol, marker_color=clr,
                            marker_line_width=0, text=txt, textposition="auto"))
                if ctype in ("Bar", "Horizontal bar"):
                    fig.update_layout(barmode="stack" if stacked else "group")
                if ctype == "Horizontal bar":
                    fig.update_xaxes(title="Value")
                    fig.update_yaxes(title=xcol, automargin=True)
                else:
                    fig.update_yaxes(title="Value")
                    fig.update_xaxes(title=xcol, tickangle=-35)
                _style(fig, 460)
                st.plotly_chart(fig, width="stretch", key="bld_main")

        # ── scatter / bubble: X vs Y (+ optional colour, size) ──────────────
        elif ctype in ("Scatter", "Bubble"):
            ncol = 4 if ctype == "Bubble" else 3
            r1 = st.columns(ncol)
            xcol = r1[0].selectbox("X stat", num_cols, index=0, key=f"bld_sx_{k}")
            ycol = r1[1].selectbox("Y stat", num_cols,
                                   index=min(1, len(num_cols) - 1),
                                   key=f"bld_sy_{k}")
            color_by = r1[2].selectbox("Colour by", ["(none)"] + num_cols,
                                       key=f"bld_sc_{k}")
            size_by = (r1[3].selectbox("Size by", num_cols,
                                       index=min(2, len(num_cols) - 1),
                                       key=f"bld_ss_{k}")
                       if ctype == "Bubble" else None)
            r2 = st.columns(2)
            show_labels = r2[0].checkbox("Label points", value=True,
                                         key=f"bld_slab_{k}")
            trend_ln = r2[1].checkbox("Trend line", value=False,
                                      key=f"bld_str_{k}")
            d = df.dropna(subset=[xcol, ycol]).copy()
            if d.empty:
                st.info("No rows have both of those stats.")
            else:
                marker = dict(line=dict(width=1, color="#30363d"))
                if size_by:
                    sv = d[size_by].fillna(d[size_by].min())
                    lo, hi = sv.min(), sv.max()
                    marker["size"] = (list(8 + (sv - lo) / (hi - lo) * 42)
                                      if hi > lo else [18] * len(sv))
                else:
                    marker["size"] = 13
                if color_by != "(none)":
                    marker.update(color=d[color_by].tolist(),
                                  colorscale="Viridis", showscale=True,
                                  colorbar=dict(title=color_by))
                else:
                    marker["color"] = ACCENT
                fig = go.Figure(go.Scatter(
                    x=d[xcol], y=d[ycol],
                    mode="markers+text" if show_labels else "markers",
                    text=d["Label"] if show_labels else None,
                    textposition="top center", textfont=dict(size=9),
                    marker=marker, hovertext=d["Label"],
                    hovertemplate="%{hovertext}<br>" + xcol + " %{x:.2f} · "
                                  + ycol + " %{y:.2f}<extra></extra>"))
                if trend_ln and len(d) >= 2:
                    xs = d[xcol].to_numpy(dtype=float)
                    yy = d[ycol].to_numpy(dtype=float)
                    m, b = np.polyfit(xs, yy, 1)
                    xr = [float(xs.min()), float(xs.max())]
                    fig.add_trace(go.Scatter(
                        x=xr, y=[m * xr[0] + b, m * xr[1] + b], mode="lines",
                        line=dict(color=GREY, dash="dash"), name="trend",
                        hovertemplate=f"slope {m:+.2f}<extra></extra>"))
                fig.update_xaxes(title=xcol)
                fig.update_yaxes(title=ycol)
                _style(fig, 480)
                st.plotly_chart(fig, width="stretch", key="bld_main")
                if size_by:
                    st.caption(f"Bubble size = {size_by}.")

        # ── pie / donut: each row's share of one stat ───────────────────────
        elif ctype in ("Pie", "Donut"):
            r1 = st.columns(2)
            val = r1[0].selectbox("Value (slice size)", num_cols,
                                  key=f"bld_pv_{k}")
            lblcol = r1[1].selectbox("Slice labels", cat_cols, key=f"bld_pl_{k}")
            topn = st.number_input("Top N (0 = all)", 0, len(df), 0, 1,
                                   key=f"bld_pn_{k}")
            d = df.dropna(subset=[val]).copy()
            d = d[d[val] > 0]
            if d.empty:
                st.info("Pie / donut needs positive values — this stat has none.")
            else:
                d = d.sort_values(val, ascending=False)
                if topn:
                    d = d.head(int(topn))
                fig = go.Figure(go.Pie(
                    labels=d[lblcol], values=d[val],
                    hole=0.55 if ctype == "Donut" else 0,
                    textinfo="label+percent", sort=False,
                    marker=dict(colors=[PALETTE[i % len(PALETTE)]
                                        for i in range(len(d))],
                                line=dict(color="#0d1117", width=1))))
                fig.update_layout(template="plotly_dark", height=480,
                                  paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                                  margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig, width="stretch", key="bld_main")
                st.caption("Each slice is a row's share of the selected stat; "
                           "non-positive values are dropped.")

        # ── radar: many stats, compare a few rows ───────────────────────────
        elif ctype == "Radar":
            r1 = st.columns(2)
            stats = r1[0].multiselect(
                "Stats (3+ make a shape)", num_cols,
                default=num_cols[:min(6, len(num_cols))], key=f"bld_rs_{k}")
            labels = df["Label"].tolist()
            ent = r1[1].multiselect(
                f"Compare these {ds_name.lower()}", labels,
                default=labels[:min(3, len(labels))], key=f"bld_re_{k}")
            normalize = st.checkbox(
                "Scale each stat 0–100 across the dataset (recommended — stats "
                "have different units)", value=True, key=f"bld_rn_{k}")
            if len(stats) < 3 or not ent:
                st.info("Pick at least 3 stats and 1 row to compare.")
            else:
                indexed = df.drop_duplicates("Label").set_index("Label")
                series = {s: (_norm01(indexed[s]) if normalize else indexed[s])
                          for s in stats}
                theta = stats + [stats[0]]
                fig = go.Figure()
                if normalize:
                    fig.add_trace(go.Scatterpolar(
                        r=[50] * len(theta), theta=theta, mode="lines",
                        line=dict(color=GREY, width=1, dash="dot"),
                        name="mid (50)", hoverinfo="skip"))
                for i, e in enumerate(ent):
                    rv = [series[s].get(e, 0) for s in stats]
                    rv = [0 if pd.isna(x) else x for x in rv]
                    rv = rv + [rv[0]]
                    clr = PALETTE[i % len(PALETTE)]
                    rr, gg, bb = _rgb(clr)
                    fig.add_trace(go.Scatterpolar(
                        r=rv, theta=theta, fill="toself", name=e,
                        line=dict(color=clr, width=2),
                        fillcolor=f"rgba({rr},{gg},{bb},0.16)"))
                fig.update_layout(
                    template="plotly_dark", height=540,
                    paper_bgcolor="rgba(0,0,0,0)", showlegend=True,
                    legend=dict(orientation="h", y=1.12, x=0),
                    polar=dict(bgcolor=CARD_BG,
                               radialaxis=dict(range=[0, 100] if normalize
                                               else None, gridcolor=GRID,
                                               tickfont=dict(size=9)),
                               angularaxis=dict(gridcolor=GRID,
                                                tickfont=dict(size=10))),
                    margin=dict(l=60, r=60, t=60, b=30))
                st.plotly_chart(fig, width="stretch", key="bld_main")
                if normalize:
                    st.caption("Each spoke is scaled to the dataset's own min→max "
                               "(0–100), so shapes are comparable across stats.")

        # ── histogram: distribution of one or more stats ────────────────────
        elif ctype == "Histogram":
            stats = st.multiselect("Stat(s) to bin", num_cols,
                                   default=num_cols[:1], key=f"bld_hs_{k}")
            bins = st.slider("Bins", 5, 50, 15, key=f"bld_hb_{k}")
            if not stats:
                st.info("Pick at least one stat.")
            else:
                fig = go.Figure()
                for i, s in enumerate(stats):
                    fig.add_trace(go.Histogram(
                        x=df[s].dropna(), name=s, nbinsx=bins,
                        marker_color=PALETTE[i % len(PALETTE)],
                        marker_line_width=0,
                        opacity=0.65 if len(stats) > 1 else 1))
                if len(stats) > 1:
                    fig.update_layout(barmode="overlay")
                fig.update_xaxes(title="Value")
                fig.update_yaxes(title="Count")
                _style(fig, 440)
                st.plotly_chart(fig, width="stretch", key="bld_main")

        # ── box plot: spread of one or more stats ───────────────────────────
        elif ctype == "Box plot":
            stats = st.multiselect("Stat(s)", num_cols,
                                   default=num_cols[:min(4, len(num_cols))],
                                   key=f"bld_bs_{k}")
            show_pts = st.checkbox("Show individual points", value=True,
                                   key=f"bld_bp_{k}")
            if not stats:
                st.info("Pick at least one stat.")
            else:
                fig = go.Figure()
                for i, s in enumerate(stats):
                    fig.add_trace(go.Box(
                        y=df[s].dropna(), name=s,
                        marker_color=PALETTE[i % len(PALETTE)],
                        boxpoints="all" if show_pts else "outliers",
                        jitter=0.4, pointpos=0))
                fig.update_yaxes(title="Value")
                _style(fig, 460)
                st.plotly_chart(fig, width="stretch", key="bld_main")
                st.caption("Box spans the inter-quartile range; line = median, "
                           "whiskers reach 1.5×IQR.")

        # ── correlation heatmap across selected stats ───────────────────────
        elif ctype == "Correlation heatmap":
            stats = st.multiselect("Stats to correlate (2+)", num_cols,
                                   default=num_cols[:min(8, len(num_cols))],
                                   key=f"bld_cs_{k}")
            if len(stats) < 2:
                st.info("Pick at least two stats.")
            else:
                corr = df[stats].corr()
                z = corr.values
                fig = go.Figure(go.Heatmap(
                    z=z, x=stats, y=stats, zmin=-1, zmax=1, colorscale="RdBu",
                    text=[[f"{v:.2f}" for v in row] for row in z],
                    texttemplate="%{text}", textfont=dict(size=9),
                    colorbar=dict(title="r")))
                fig.update_layout(template="plotly_dark", height=520,
                                  paper_bgcolor="rgba(0,0,0,0)",
                                  margin=dict(l=10, r=10, t=10, b=10))
                fig.update_xaxes(tickangle=-40)
                st.plotly_chart(fig, width="stretch", key="bld_main")
                st.caption(f"Pearson correlation between each pair of stats over "
                           f"the {len(df)} rows. +1 (blue) = move together, "
                           "−1 (red) = move opposite. Small samples are noisy.")

        # ── raw data table ──────────────────────────────────────────────────
        elif ctype == "Data table":
            cols = st.multiselect(
                "Columns", list(df.columns),
                default=["Label"] + num_cols[:min(8, len(num_cols))],
                key=f"bld_tc_{k}")
            if cols:
                _grid(df[cols], f"bld_dt_{k}", height=min(640, 60 + 35 * len(df)))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 9 — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
with ch_bld:
    _fx_chbld()


with tab_gloss:
    glossary_tab("ta_gloss")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB — PLAYER PROFILE  (ported from 6_Players.py; scoped to this team's roster)
# ══════════════════════════════════════════════════════════════════════════════
def _render_profile(P, pid, rows, zsplits, zguard):
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
    _arch = _archetypes(gender).get(pid)
    _pg_chips = "".join(
        f"<span class='stat-chip'>{lbl} <b>{P[k]:.1f}</b></span>"
        for k, lbl in [("PPG", "PPG"), ("RPG", "RPG"), ("APG", "APG"),
                       ("SPG", "SPG"), ("BPG", "BPG"), ("MPG", "MIN")]
        if P.get(k) is not None)
    _arch_chip = (f"<span class='stat-chip' style='border-color:{ACCENT}'>"
                  f"<b>{_arch}</b></span>" if _arch else "")
    st.markdown(f"<div class='form-strip' style='margin:-8px 0 10px'>"
                f"{_arch_chip}{_pg_chips}</div>", unsafe_allow_html=True)
    _pbadges = _badges(gender).get(pid, [])
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
            st.plotly_chart(_pp_gauge(P[key], key, GAUGE_CLR.get(key, ACCENT)),
                            width="stretch", key=f"tdprof_gauge_{key}")
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
            st.plotly_chart(fig, width="stretch", key="tdprof_court")
            st.caption("≥45% · 30–44% · <30% · bubble size = attempts · "
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
        st.plotly_chart(rad, width="stretch", key="tdprof_radar")

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
            st.plotly_chart(dn, width="stretch", key="tdprof_src")

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
        st.plotly_chart(df_, width="stretch", key="tdprof_diet")
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
            st.plotly_chart(cd, width="stretch", key="tdprof_sccomp")
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
            st.plotly_chart(qfig, width="stretch", key="tdprof_qtr")
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
    plog = []
    for g in sorted(games, key=lambda x: x["date"]):
        b = S.aggregate_player_boxes(game_ids=[g["id"]]).get(pid)
        if not b:
            continue
        opp = g["team2_id"] if g["team1_id"] == P["team_id"] else g["team1_id"]
        plog.append({
            "Date": g["date"], "Opp": name_of.get(opp, "?"),
            "PTS": b["PTS"], "REB": b["TRB"], "AST": b["AST"],
            "STL": b["STL"], "BLK": b["BLK"], "TOV": b["TOV"],
            "FG": f"{b['FGM']}/{b['FGA']}", "3P": f"{b['3PM']}/{b['3PA']}",
            "FT": f"{b['FTM']}/{b['FTA']}",
            "GS": round(S.game_score(b), 1),
        })
    if plog:
        gx = [f"{g['Date'][5:]} {g['Opp'][:8]}" for g in plog]
        tr = go.Figure()
        tr.add_trace(go.Bar(x=gx, y=[g["PTS"] for g in plog], name="PTS",
                            marker_color=ACCENT, marker_line_width=0))
        tr.add_trace(go.Scatter(x=gx, y=[g["GS"] for g in plog], name="Game Score",
                                mode="lines+markers", line=dict(color="#56d4dd",
                                                                width=2)))
        tr.update_yaxes(title="Points / Game Score")
        tr.update_xaxes(tickangle=-40)
        _style(tr, 320)
        st.plotly_chart(tr, width="stretch", key="tdprof_log")

        st.dataframe(pd.DataFrame(plog), hide_index=True,
                     width="stretch",
                     height=min(560, 60 + 35 * len(plog)))
        st.caption(f"{len(plog)} tracked games. Box scores are per game from "
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
        st.plotly_chart(bar, width="stretch", key="tdprof_leaguebar")

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
        st.plotly_chart(p32, width="stretch", key="tdprof_per32")
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
        arch = ("", "Two-Way Force",
                "Produces on offense and disrupts on defense — a rare both-ends impact.")
    elif OFF >= 62 and pc("PPG") >= 80:
        arch = ("", "Scoring Machine",
                "A primary offensive weapon who creates and converts at volume.")
    elif PLY >= 62 and pc("APG") >= 80:
        arch = ("", "Floor General",
                "Runs the offense through vision and distribution.")
    elif REB_R >= 62 or pc("REB") >= 85:
        arch = ("", "Glass Cleaner",
                "Owns the boards and generates extra possessions.")
    elif DEF >= 62 or pc("STOCKS") >= 85:
        arch = ("", "Defensive Anchor",
                "Disrupts opponents with steals, blocks, and contests.")
    elif pc("3P%") >= 70 and P["3PA"] >= 15 and pc("DSHOT%", True) >= 55:
        arch = ("", "3-and-D Wing",
                "Spaces the floor and holds up defensively — a valuable role.")
    elif pc("3P%") >= 70 and P["3PA"] >= 20:
        arch = ("", "Spot-Up Shooter",
                "An off-ball threat who punishes help defense from deep.")
    elif pc("Paint%") >= 70 and pc("REB") >= 60:
        arch = ("", "Interior Presence",
                "Finishes inside efficiently and commands the paint.")
    elif OVR >= 56:
        arch = ("", "Versatile Contributor",
                "Well-rounded across the board without one dominant trait.")
    elif pc("+/-") >= 75:
        arch = ("", "High-Impact Role Player",
                "The team plays better with them on the floor.")
    else:
        arch = ("", "Developing Player",
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

    if pc("TS%") <= 25 and P["FGA"] >= 20:
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
        f"color:#2ea043;margin-bottom:10px'>Strengths</div>"
        f"{_bullets(strengths, 'No standout strengths in this sample yet.')}</div>",
        unsafe_allow_html=True)
    sc2.markdown(
        f"<div class='pl-scout'><div style='font-size:13px;font-weight:700;"
        f"color:#f0a500;margin-bottom:10px'>Areas to watch</div>"
        f"{_bullets(weaknesses, 'No clear weaknesses in this sample yet.')}</div>",
        unsafe_allow_html=True)


@st.fragment
def _fx_prof5():
    st.caption("One player's full card — ratings, signature metrics, shot chart, "
               "game log, league percentiles and a scouting report. Ranks and "
               "percentiles are vs the whole league player pool.")
    _ppool = _ptable_full(gender)
    _prows = sorted(_ppool.values(), key=lambda r: (r["Rank"] or 1e9))
    _tpids = [k for k in _ppool if _ppool[k]["team_id"] == team_id]
    if not _tpids:
        st.info(f"No rated players for **{team['name']}** yet — track a game in "
                "the Game Tracker.")
    else:
        _porder = sorted(_tpids, key=lambda k: (_ppool[k]["Rank"] or 1e9))
        _plabels = [f"#{_ppool[k]['Rank']}  {_ppool[k]['name']}"
                    f"  ·  {_ppool[k]['class']}" for k in _porder]
        _ppick = st.selectbox("Player", range(len(_porder)),
                              format_func=lambda i: _plabels[i], key="td_prof_pick")
        _ppid = _porder[_ppick]
        _zs, _zg = _pp_zone_tables()
        _render_profile(_ppool[_ppid], _ppid, _prows, _zs, _zg)


with tab_prof:
    _fx_prof5()
