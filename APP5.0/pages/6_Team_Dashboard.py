"""
6_Team_Dashboard.py — the single-team deep dive.

Pick one team and read everything about it across these tabs:

  • Overview   — a coach's one-glance card: record, power ratings, best players,
                 four-factor snapshot, scoring mix and the margin trend.
  • Roster     — the roster scan (ratings compared, leader bars, scatter maps,
                 shot-selection breakdown) and a "Player" drill-down sub-view that
                 opens one player's full card. The two share this view via an inner
                 selector. (The lineup simulator now lives under Helper → Lineup.)
  • Schedule   — the full schedule, record vs each class, and any tracked game's
                 complete box score on demand.
  • Charts     — the analytics wall, six stories: Offense (Scoring · Shooting ·
                 Playmaking nested), Play Style, Defense (Team Defense · Scheme ·
                 Glass nested), Situational, Trends and Quarters (every stat
                 split by quarter, heatmap + drill).
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
from helpers.ui import (page_chrome, page_header, masthead, rgb as _rgb,
                        style_fig as _style, q_label as _q_label, empty_state,
                        gender_radio, gender_label, grid as _grid, seg as _seg,
                        AWAY, CARD_BG, GRID, HEAT, DIVERGE,
                        glossary_key as _glossary_key)
from helpers.cards import (fmt as _fmt, pctile as _pctile,
                           pctile_bar as _pctile_bar,
                           tier as _tier, glass as _glass, onoff_html as _onoff_html,
                           gauge_dial as _pp_gauge, gauge_range, bar_h,
                           scoring_donut as _donut)
from helpers.court import (shot_chart as _shot_chart, hot_zones as _hot_zones,
                           shot_map as _shot_map, shot_hexbin as _shot_hexbin,
                           zone_leader_map as _zone_leader_map,
                           # court frame primitives for the rebound-geography
                           # maps (same geometry/theme as every shot chart)
                           _draw_court as _court_draw,
                           _court_layout as _court_frame)
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
import helpers.defenses as DEF
import helpers.exploit as EXPL
import helpers.spacing as SPACE
import helpers.matchups as MU
import helpers.gameflow as GF
import helpers.fouls as FL
import helpers.manual_box as MB
import helpers.scoutboard as SB
import helpers.auth as AUTH
import helpers.entitlement as ENT
# Tab modules (Big Bet 5 split) — render(ctx) fragments; ctx packs the shared
# page-level state. See helpers/dashboard/__init__.py for the convention.
from types import SimpleNamespace
import helpers.dashboard.overview as DOVER
import helpers.dashboard.players_tab as DPLAY
import helpers.dashboard.sched as DSCHED
import helpers.dashboard.scout_tab as DSCOUT
import helpers.dashboard.insights_tab as DINS
import helpers.dashboard.profile_tab as DPROF
import helpers.dashboard.playstyle_tab as DPLAYSTYLE
import helpers.dashboard.defense_tab as DDEFENSE
import helpers.dashboard.situational_tab as DSITUATIONAL
import helpers.dashboard.projection_tab as DPROJ
import helpers.dashboard.share_tab as DSHARE
import helpers.breakdown as BR
import helpers.situational as SIT
import helpers.seasons as SEAS

_cfg, ACCENT = page_chrome("Team Dashboard")
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
        "ScEff": f"{a['SCE']:.3f}" if a["FGA"] else "—",
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


def _poss_sankey(po, accent, height=460):
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
        node=dict(label=labels, color=node_color, pad=28, thickness=18,
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

masthead("Team Dashboard", sub="Pick a team and read everything about it — "
         "ratings, record, roster, scout and the analytics wall.")
_glossary_key("eFG%", "TS%", "USG%", "ORtg", "DRtg", "NetRtg", "PPP", "TOV%",
              "OREB%", "DSHOT%", "PPS", "ScEff", "FTr", "3PAr",
              label="📖 Stat key — what the advanced columns mean")

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

@st.cache_resource(show_spinner=False)
def _score_ratings_fp(g, season, _fp):
    # cache_resource SURVIVES st.cache_data.clear() (which fires on every write),
    # keyed on the results fingerprint so the ~0.5s league rating recomputes only
    # when a score actually moves — not on event-location edits or unrelated
    # clears. Output is read-only across callers → safe to share. `season`
    # partitions the cache so an archive view never serves current ratings.
    return TR.score_ratings(gender=g, season=season)


def _score_ratings(g, season="Current"):
    return _score_ratings_fp(g, season, TR.results_fingerprint())


@st.cache_data(ttl=600, show_spinner=False)
def _tracked_ratings(g, season="Current"):
    return TR.tracked_ratings(gender=g, season=season)


# Season picker — view a past/archived season's data. Only appears once a season
# has been rolled over (archived labels exist); the current season is the default
# so the whole page is byte-identical when no archive exists. Computed BEFORE the
# ratings/team ordering so every downstream fetch is scoped to it. A PAST season is
# an open, self-contained archive: the whole dashboard (ratings, league %, play
# style, defense, situational, player profile, lab) reads only that season's games.
_season_opts = SEAS.season_options()
if len(_season_opts) > 1:
    _slbl = c2.selectbox(
        "Season", [l for _v, l in _season_opts], key="ta_season",
        help="View a past season's data. The whole dashboard scopes to it — "
             "ratings, play style, defense, situational and player profiles are "
             "that season's. (The Scout sheet and the Lab → Build tab stay "
             "current-season.)")
    season_pick = next(v for v, l in _season_opts if l == _slbl)
else:
    season_pick = SEAS.ACTIVE
_is_cur_season = SEAS.is_current(season_pick)

with st.spinner("Crunching team ratings…"):
    scored = _score_ratings(gender, season_pick)
    tracked = _tracked_ratings(gender, season_pick)


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
# Deep-link preselect: a ?team=<id> link (from a landing power-ranking row) opens
# this dashboard already scoped to that team. Applied once per distinct id so the
# user can still switch teams; ids outside the current gender pool fall through.
_qp_team = st.query_params.get("team")
if _qp_team and st.session_state.get("_ta_deeplink") != _qp_team:
    try:
        _dl_tid = int(_qp_team)
    except (TypeError, ValueError):
        _dl_tid = _qp_team
    if _dl_tid in order_ids:
        st.session_state["ta_team"] = _dl_tid
    st.session_state["_ta_deeplink"] = _qp_team
team_id = c2.selectbox("Team", order_ids, index=default_idx,
                       format_func=lambda tid: _team_label(team_by_id[tid]),
                       key="ta_team")
team = team_by_id[team_id]

@st.cache_data(ttl=600, show_spinner=False)
def _team_bundle(tid, g, vis=None, season="Current"):
    # `vis` (tuple of game ids, or None) is the entitlement read-filter: None for
    # own team / admin (full depth); a League-wide coach scouting another team
    # passes that team's POOLED game ids so its Solo-tracked games stay private.
    # `season` scopes the whole bundle to one season (default = current). It is in
    # the cache key, so switching seasons re-derives instead of serving stale data.
    return TA.team_bundle(tid, gender=g, min_games=1,
                          visible_game_ids=(set(vis) if vis is not None else None),
                          season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _league_ff(g, season="Current"):
    return TA.league_four_factors(gender=g, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _league_stat_pools(g, season="Current"):
    """{team_id: {stat_key: value}} over tracked games for every team in the
    league — the pool that lets the Overview say where THIS team ranks and how
    it compares to the league average (the APP3-style league-aligned detail).
    One box pass per tracked game (shared with the four-factors helper).
    `season` scopes the whole pool to one season (archive views)."""
    games = TR._finished_games(gender=g, tracked_only=True, season=season)
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
def _pack(g, _trk, season="Current"):
    # _trk (dict) is underscore-prefixed so Streamlit skips hashing it; keyed on
    # (g, season) so an archive view builds its own season's pack.
    return LA.team_tracked_pack(gender=g, tracked=_trk, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _ptable_full(g, game_ids=None):
    """Every player's flat stat line for the gender. `game_ids` scopes the pool to
    a season (the page passes the season's gender tracked ids for an archive view),
    so the profile/roster read that season's players; None = current."""
    return PR.player_stat_table(
        gender=g, min_games=1,
        game_ids=(set(game_ids) if game_ids is not None else None))


@st.cache_data(ttl=600, show_spinner=False)
def _archetypes(g, game_ids=None):
    """{player_id: archetype label} across the league pool (for the roster table)."""
    res = AR.cluster_players(_ptable_full(g, game_ids))
    return {pid: v["archetype"] for pid, v in res["players"].items()}


@st.cache_data(ttl=600, show_spinner=False)
def _badges(g, game_ids=None):
    """{player_id: [badge, ...]} (NBA-2K-style) across the league pool."""
    return BG.award_badges(_ptable_full(g, game_ids))


@st.cache_data(ttl=600, show_spinner=False)
def _gender_tracked_ids(g, season="Current"):
    """All tracked, completed game ids for a gender in `season` (the RAPM/WPA
    possession pool + every league-wide tracked baseline). `season` defaults to the
    active season; a label scopes the pool to that archive."""
    rows = query(
        """SELECT g.id FROM games g JOIN teams t ON t.id = g.team1_id
           WHERE g.tracked = 1 AND g.season = ? AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL AND t.gender = ?""", (season, g))
    return [r["id"] for r in rows]


@st.cache_data(ttl=600, show_spinner=False)
def _avg_player_ratings(tracked_ids):
    """{player_id: average per-game RATING (0-10)} over the given tracked GAME ids.

    Takes the bundle's already-resolved `tracked_ids` (season + entitlement correct)
    rather than re-querying by a season LABEL — the label path silently returns
    nothing when the active-season sentinel ('Current') and the season the tracked
    data is actually stored under (e.g. an archived '2025-2026' after a rollover)
    disagree, which left every RTG blank. Calibrated over these games' player-games
    (both teams) so grades read relative to this pool. Empty when nothing tracked."""
    import helpers.game_rating as GR
    gids = list(tracked_ids)
    if not gids:
        return {}
    agg = {}
    for gm in GR.season_game_ratings(game_ids=gids).values():
        for pid, info in gm.items():
            r = info.get("rating")
            if r is not None:
                agg.setdefault(pid, []).append(r)
    return {pid: sum(v) / len(v) for pid, v in agg.items() if v}


@st.cache_data(ttl=600, show_spinner=False)
def _located_team(tid, gids):
    """Tap-captured x/y shots for one team over its tracked games (shots FOR)."""
    return S.located_shots(game_ids=list(gids), team_id=tid)


@st.cache_data(ttl=600, show_spinner=False)
def _located_allowed(tid, gids):
    """Tap-captured x/y shots the team ALLOWED (opponents' shots in its games) —
    the shots-against companion to _located_team. A game has two teams, so any
    located shot in the team's games whose shooter isn't this team is an opponent
    attempt; its `defense` tag is the scheme THIS team was running."""
    return [s for s in S.located_shots(game_ids=list(gids))
            if s.get("team_id") != tid]


@st.cache_data(ttl=600, show_spinner=False)
def _reb_geography(tid, gids):
    """Located missed shots with a logged rebounder, split by which basket:
    'own' = this team's misses (second-chance creation), 'opp' = opponent
    misses (the defensive glass). Each shot carries reb='Ours'|'Theirs'."""
    out = {"own": [], "opp": []}
    for e in S.fetch_events(list(gids)):
        if e["event_type"] != "shot" or e.get("shot_result") == "make":
            continue
        x, y = e.get("shot_x"), e.get("shot_y")
        rt, stid = e.get("rebounder_team_id"), e.get("shooter_team_id")
        if x is None or y is None or rt is None or stid is None:
            continue
        rec = {"x": x, "y": y, "make": False,
               "value": 3 if e.get("shot_type") == 3 else 2,
               "reb": "Ours" if rt == tid else "Theirs"}
        out["own" if stid == tid else "opp"].append(rec)
    return out


def _reb_map(shots, title, key):
    """Half-court map of missed-shot origins, colored by who got the board."""
    fig = go.Figure()
    _court_draw(fig)
    for name, clr in (("Ours", GOOD), ("Theirs", BAD)):
        pts = [s for s in shots if s["reb"] == name]
        if not pts:
            continue
        fig.add_trace(go.Scatter(
            x=[s["x"] for s in pts], y=[s["y"] for s in pts],
            mode="markers", name=f"{name} ({len(pts)})",
            marker=dict(symbol="x", size=8, color=clr,
                        line=dict(width=1, color=clr)),
            hoverinfo="skip"))
    _court_frame(fig, title, 420)
    fig.update_layout(showlegend=True,
                      legend=dict(orientation="h", y=1.02, x=0,
                                  bgcolor="rgba(0,0,0,0)",
                                  font=dict(size=11, color="#c9d1d9")))
    st.plotly_chart(fig, width="stretch", key=key)


def _verdict_lines(lines):
    """Insights-style plain-word read box. `lines` = [(badge, n, html_text)]
    — the same badge + n=sample + sentence pattern as the Insights feed, so
    a coach gets the takeaway before the wall of evidence below it."""
    body = "".join(
        "<div style='margin-top:4px'>"
        f"<span class='badge accent'>{b}</span> "
        + (f"<span style='color:var(--subtext);font-size:10px'>n={n}</span> "
           if n else "")
        + f"{t}</div>" for b, n, t in lines)
    st.markdown(f"<div class='gloss-card'>{body}</div>",
                unsafe_allow_html=True)


def _lg_delta(v, pool, *, pct=False, dec=1, inverse=False, neutral=False):
    """st.metric delta kwargs for `v` vs the league-pool average. `inverse`
    for lower-is-better stats, `neutral` for stats with no good direction
    (pace). Empty pool (nobody else tracked) → no delta."""
    pool = [p for p in pool if p is not None]
    if not pool:
        return {}
    d = (v - sum(pool) / len(pool)) * (100 if pct else 1)
    return {"delta": f"{d:+.{dec}f}{'pp' if pct else ''} vs lg",
            "delta_color": ("off" if neutral else
                            "inverse" if inverse else "normal")}


def _jump(view, label, key):
    """Cross-link button: flips the top-level View switcher on next rerun.
    Only for VIEW-level links (st.tabs can't be selected programmatically)."""
    st.button(label, key=key,
              on_click=lambda v=view: st.session_state.update(td_view=v))


@st.cache_data(ttl=600, show_spinner=False)
def _league_pps_located(g, game_ids=None):
    """League-wide points-per-shot over located shots — the hexbin midpoint.
    `game_ids` scopes the pool to a season (None = current gender pool)."""
    gids = list(game_ids) if game_ids is not None else _gender_tracked_ids(g)
    shots = S.located_shots(game_ids=gids)
    return (sum(s["value"] for s in shots if s["make"]) / len(shots)
            if shots else None)


@st.cache_data(ttl=600, show_spinner=False)
def _shot_model(g, game_ids=None):
    """League distance×value make-rate model for points-over-expected heat.
    `game_ids` scopes the fit to a season (None = current gender pool)."""
    gids = list(game_ids) if game_ids is not None else _gender_tracked_ids(g)
    return S.distance_make_model(events=S.fetch_events(gids))


@st.cache_data(ttl=600, show_spinner=False)
def _spacing(g, tid, vis=None):
    """Floor-spacing index — located-shot (x,y) blend vs the gender league pool.
    `vis` (the team's visible tracked games; None = own team / admin = full)
    read-filters the TEAM's own components so a league-wide scout never aggregates
    its non-pooled Solo games — the percentile pool stays gender-wide.
    None until the team + pool clear the volume gates (graceful while thin)."""
    return SPACE.spacing_index(
        tid, gender=g,
        team_game_ids=(list(vis) if vis is not None else None))


@st.cache_data(ttl=600, show_spinner="Computing RAPM…")
def _rapm(g, box_prior=False, season="Current"):
    """League-wide two-way RAPM over the gender's tracked games (holds teammates
    AND opponents constant — needs the whole pool, not one team). inference=True
    attaches the statsmodels 95% CI / significance companion. `season` scopes the
    possession pool to one season (archive views).

    box_prior=True shrinks each player toward their player_ratings box impact
    instead of toward league average (0) — the small-sample fix that keeps stars
    off 'average' on a ~15-game book (ML_LAYER_ROADMAP Tier 1)."""
    prior = RA.box_prior_from_ratings(gender=g) if box_prior else None
    return RA.compute_rapm(_gender_tracked_ids(g, season), inference=True,
                           prior=prior)


@st.cache_data(ttl=600, show_spinner=False)
def _war_tbl(g, box_prior=False, season="Current"):
    """HoopWAR per player — chains the cached RAPM solve (same box-prior toggle)
    through helpers/hoopwar.py. {} when RAPM or finished scores are absent.
    `season` scopes the RAPM pool + WAR game set to one season."""
    import helpers.hoopwar as HW
    try:
        _gids = None if season in (None, "Current") else list(_gender_tracked_ids(g, season))
        return HW.war_table(g, rapm=_rapm(g, box_prior=box_prior, season=season),
                            game_ids=_gids, season=season)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _shot_quality(g, season="Current"):
    """League-pooled continuous shot-quality (xPP-Q) + per-player SMOE (points over
    expected). Returns ({pid: smoe_row}, n_shots_fit) or ({}, 0) when there aren't
    enough located shots to fit (caller shows a fallback). Tier 2, ML_LAYER_ROADMAP.
    `season` scopes the shot pool to one season (archive views)."""
    import helpers.shotquality as SQ
    sh = S.located_shots(events=S.fetch_events(_gender_tracked_ids(g, season)))
    m = SQ.fit_league_model(shots=sh)
    return (SQ.player_smoe(shots=sh, model=m), m["n"]) if m else ({}, 0)


@st.cache_data(ttl=600, show_spinner=False)
def _rotation(tid, vis=None):
    """Stagger coverage (star floor-time + bench-only net bleed) + season foul-prone
    list for one team (Tier 2, ML_LAYER_ROADMAP). `vis` read-filters to the viewer's
    visible games for this team (None = own/admin = full). Only reached when
    has_tracked, so vis is None or a non-empty pooled set — never empty."""
    import helpers.rotation_plan as RP
    gids = list(vis) if vis else None
    return RP.star_coverage(tid, game_ids=gids), RP.foul_prone(tid, game_ids=gids)


@st.cache_data(ttl=600, show_spinner=False)
def _poss_ledger(tid, vis=None):
    """Possession-value ledger (points/100 sources + outcome mix, offense & allowed)
    for one team (Tier 2, ML_LAYER_ROADMAP). `vis` read-filters to the viewer's
    visible games (None = own/admin = full); only reached when has_tracked."""
    import helpers.possession_value as PVL
    gids = list(vis) if vis else None
    return PVL.team_ledger(tid, game_ids=gids)


@st.cache_data(ttl=600, show_spinner=False)
def _season_wpa(g, mode, season="Current"):
    return WP.season_wpa(gender=g, mode=mode, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _chemistry(tid, _tids):
    return NW.chemistry_network(tid, list(_tids))


@st.cache_data(ttl=600, show_spinner=False)
def _units(tid, _tids):
    return LU.unit_ratings(tid, list(_tids))


@st.cache_data(ttl=600, show_spinner=False)
def _scout(tid, g, limit=7, excl=(), vis=None, season="Current", season_gp=None):
    # `vis` (tuple of game ids, or None) scopes the hot-zone / shot-creation views
    # to what the viewer may see (None = own team / admin = full depth). `season`
    # + `season_gp` (the gender's season tracked ids) scope every piece to one
    # season so an archive scout reads that season's games, not 'Current'.
    trk = _tracked_ratings(g, season)
    return SC.build_scout(tid, g, _score_ratings(g, season), trk,
                          _pack(g, trk, season), _ptable_full(g, season_gp),
                          personnel_limit=limit, exclude_pids=set(excl),
                          visible_game_ids=(set(vis) if vis is not None else None),
                          season=season)


# Entitlement read-filter (AXIS-2 teeth): which of this team's tracked games may
# the viewer aggregate. None = own team / admin (full depth); a League-wide coach
# scouting another team gets only that team's POOLED games, so its Solo-tracked
# games stay private. Threaded into the bundle + scout so the page's tracked depth
# is computed over exactly the visible set.
_vis = ENT.team_visible_tracked_ids(AUTH.current_user(), team_id, season=season_pick)
_vis_key = None if _vis is None else tuple(sorted(_vis))
bundle = _team_bundle(team_id, gender, _vis_key, season=season_pick)
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
# Tier gate (AXIS 1 + AXIS 2): Free → box only; Paid → own team always, another
# team only when League-wide AND that team has shared (pooled) tracked games —
# else a neutral "hasn't shared" note. This single has_tracked flag flows to
# ctx.has_tracked and ~17 downstream sites, gating the whole dashboard in one
# place. raw_has_tracked reads the UNFILTERED game_log (box level) so the gate
# can tell "no tracked data" apart from "tracked but not shared with you".
_raw_tracked = any(g["tracked"] for g in bundle["game_log"])
# season_pick threads the archive rule: a PAST season is open (full depth to
# everyone) — the gate self-bypasses on a non-current label.
has_tracked, _tracked_lock = ENT.tracked_gate(
    AUTH.current_user(), team_id, _raw_tracked, season=season_pick)
# one helper, both rankings: 'overall' (everything / results-only) + 'tracked'
rank_info = TR.team_rank(team_id, scored=scored, tracked=tracked)

# League-wide tracked pool for the selected season: the gender's tracked game ids
# for season_pick. None for the CURRENT season → every league-wide engine below
# keeps using its own current-season default (byte-identical behaviour). For a
# PAST season this set is fed as `game_ids` into the tracked engines (play type,
# defense, situational, player pool, RAPM/WPA, shot model, league stat pools) so
# the archive is self-contained — the team is ranked vs THAT season's field only,
# never the current one. `_season_arg(fn_takes_gender_only)` picks the value.
_season_gp = None if _is_cur_season else tuple(_gender_tracked_ids(gender, season_pick))

# Binders that pre-scope the tracked wrappers to the selected season. For the
# CURRENT season they are the identity (byte-identical), so nothing changes; for a
# PAST season they pre-bind the wrapper's `game_ids` to the archive pool:
#   _LGBIND — league-wide field pool (gender's season tracked ids): play type /
#             defense percentiles + leaders + profiles + shot model / league pps.
#   _TMBIND — this team's season tracked ids (from the already-season-scoped
#             bundle): the team-only situational view.
from functools import partial as _partial


def _LGBIND(fn):
    return fn if _is_cur_season else _partial(fn, game_ids=_season_gp)


def _TMBIND(fn):
    return fn if _is_cur_season else _partial(
        fn, game_ids=tuple(bundle["tracked_ids"]))

# No completed games yet (a brand-new / empty season) is NOT a dead end: a coach
# still needs the roster (returning players carried forward), the upcoming
# schedule and player profiles to scout with. Show a note and keep rendering —
# the results-, tracked- and trend-based sections self-gate below (has_tracked /
# empty log), so they fall back to their own empty states instead of the whole
# page stopping. (Was a hard st.stop() that blanked the dashboard.)
if not log:
    st.info(
        f"**{team['name']}** has no completed games "
        f"{'this season' if _is_cur_season else 'in that season'} yet — the "
        "roster, upcoming schedule and player profiles are ready below. "
        "Results-based ratings, trends and box scores fill in once games are "
        "played and entered in the Input Hub.")

# ── futuristic identity band (neon hero + recent-form strip) ────────────────
strk = bundle["streaks"]
_cur = strk["current"]
_cur_txt = (f"{_cur['len']}{_cur['type']}" if _cur["type"] else "—")
_ov = rank_info["overall"] or {}
_ovcls = (f" <span style='color:#6e7681'>· {_ov.get('class_lbl') or _ov['class']} "
          f"#{_ov['class_rank']}</span>"
          if _ov.get("class_rank") else "")
_chips = [
    f"<span class='stat-chip'>RANK <b>#{sc_score.get('Rank', '—')}</b> "
    f"<span style='color:#6e7681'>/ {len(scored)}</span>{_ovcls}</span>",
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
        _trkcls = (f" <span style='color:#6e7681'>· {_trk.get('class_lbl') or _trk['class']} "
                   f"#{_trk['class_rank']}</span>"
                   if _trk.get("class_rank") else "")
        _chips.insert(1, f"<span class='stat-chip'>TRK RANK <b>#{_trk['rank']}</b> "
                      f"<span style='color:#6e7681'>/ {_trk['of']}</span>{_trkcls}</span>")
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

if _tracked_lock:
    st.warning(_tracked_lock)
elif not has_tracked:
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


@st.cache_data(ttl=600, show_spinner="Computing league shot tables…")
def _pp_zone_tables(game_ids=None):
    """Per-player zone + guarded/open + hand-side splits over the tracked sample.
    `game_ids` scopes to a season (the profile passes the season pool); None =
    current, via fetch_events' default."""
    ev = S.fetch_events(list(game_ids)) if game_ids is not None else S.fetch_events()
    return (S.player_zone_splits(events=ev), S.player_zone_guarded(events=ev),
            S.player_hand_splits(events=ev))


@st.cache_data(ttl=600, show_spinner=False)
def _pp_located(pid, game_ids=None):
    """This player's tap-captured (x,y) shots — feeds the profile shot map.
    `game_ids` scopes to a season (None = current-season default)."""
    return S.located_shots(
        player_id=pid, game_ids=(list(game_ids) if game_ids is not None else None))


@st.cache_data(ttl=600, show_spinner=False)
def _pp_foulft(game_ids=None):
    """Foul / free-throw detail per player (cached) — feeds the profile fouls block."""
    return FL.player_foul_ft(
        game_ids=(list(game_ids) if game_ids is not None else None))


@st.cache_data(ttl=600, show_spinner=False)
def _pgb(game_ids=None):
    """Every player's per-game boxes over tracked games (keyed by pid → gid).
    `game_ids` scopes to a season (None = current)."""
    return S.player_game_boxes(
        game_ids=(list(game_ids) if game_ids is not None else None))


@st.cache_data(ttl=600, show_spinner=False)
def _playtype_view(g, tid, offense, game_ids=None):
    """Synergy-style play-type table for one team, ranked vs the league pool.
    `game_ids` scopes the whole pass (team cells + league baseline) to a season."""
    return PT.team_playtype_percentiles(tid, gender=g, offense=offense,
                                        game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _named_playtype_view(g, tid, offense, game_ids=None):
    """Explicit one-tap set calls for one team, each ranked vs the league pool."""
    return PT.team_named_playtype_percentiles(tid, gender=g, offense=offense,
                                              game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _pt_factors(g, tid, offense, game_ids=None):
    """Four-factors detail (eFG/OREB%/TOV%/FT-rate) per play_type, gated."""
    return BR.play_type_factors(tid, gender=g, offense=offense, game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _def_factors(g, tid, offense, game_ids=None):
    """Four-factors detail per defense scheme, gated."""
    return BR.defense_factors(tid, gender=g, offense=offense, game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _tov_types_view(g, tid, offense, game_ids=None):
    """Turnovers by the explicit turnover_type tag (giveaways / forced)."""
    import helpers.turnovers as TOVX
    return TOVX.team_turnover_types(tid, gender=g, offense=offense,
                                    game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _named_sets_all(g, game_ids=None):
    """Per-player explicit set-call PPP, ranked vs the league pool (card ctx)."""
    return PT.player_named_playtype_percentiles(gender=g, game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _role_splits_all(g, game_ids=None):
    """Per-player handler/roller screen-action splits (card ctx). `game_ids` scopes
    to a season's events; None keeps the full-sample events (current behaviour)."""
    if game_ids is not None:
        return PT.player_role_splits(game_ids=list(game_ids))
    return PT.player_role_splits(events=S.fetch_events())


@st.cache_data(ttl=600, show_spinner=False)
def _set_profiles_view(g, tid, offense, game_ids=None):
    """WAVE-2 cross-dimension: per set call, what it PRODUCES (PPP, 3PA/rim/mid
    rates, assisted%, open%, top zone, avg secs) — the set fingerprint."""
    return PT.team_playtype_shot_profiles(tid, gender=g, offense=offense,
                                          game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _feeders_view(g, tid, offense, game_ids=None):
    """WAVE-2: hand-off / inbounds feeder hubs (DHO hander, BLOB/SLOB inbounder)
    — who feeds the action, how often, and to what efficiency / target."""
    return PT.team_playtype_feeders(tid, gender=g, offense=offense,
                                    game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _set_profiles_all(g, game_ids=None):
    """Per-player set-call shot profiles (card ctx) — what each player's sets
    produce. Keyed by player_id; mirrors how _named_sets_all is wired."""
    if game_ids is not None:
        return PT.player_playtype_shot_profiles(game_ids=list(game_ids))
    return PT.player_playtype_shot_profiles(events=S.fetch_events())


@st.cache_data(ttl=600, show_spinner=False)
def _team_role_splits_view(g, tid, offense, game_ids=None):
    """Team handler-vs-roller / roll-vs-pop split per pnr/dho/offscreen set.
    team_role_splits has no gender= kwarg; it filters events by team_id. Current
    uses the full-sample events (a team is one gender, so that's safe); a season
    view passes that season's game_ids so it doesn't mix seasons."""
    if game_ids is not None:
        return PT.team_role_splits(tid, game_ids=list(game_ids), offense=offense)
    return PT.team_role_splits(tid, events=S.fetch_events(), offense=offense)


@st.cache_data(ttl=600, show_spinner=False)
def _named_leaders_view(g, offense, game_ids=None):
    """League leaderboard per named set call — where this team ranks vs the pool."""
    return PT.league_named_playtype_leaders(gender=g, offense=offense,
                                            game_ids=game_ids)


# ── DEFENSE-SCHEME views (helpers/defenses.py — the Defense super-tab) ────────────
@st.cache_data(ttl=600, show_spinner=False)
def _def_view(g, tid, offense, game_ids=None):
    """Per-scheme PPP for one team, each ranked vs the league pool."""
    return DEF.team_defense_percentiles(tid, gender=g, offense=offense,
                                        game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _def_families(g, tid, offense, game_ids=None):
    """Scheme rollup to families (man/zone/press) for one team."""
    return DEF.team_defense_families(tid, gender=g, offense=offense,
                                     game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _def_profiles(g, tid, offense, game_ids=None):
    """Per-scheme shot profile — what each defense gives up (3PA/rim/zone/open)."""
    return DEF.team_defense_shot_profiles(tid, gender=g, offense=offense,
                                          game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _def_cross(g, tid, offense, game_ids=None):
    """play_type × defense cross-tab — 'their PnR vs a 2-3 zone'."""
    return DEF.cross_play_defense(tid, gender=g, offense=offense,
                                  game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _def_tovs(g, tid, offense, game_ids=None):
    """Turnovers forced/committed per scheme (the press/trap disruption read)."""
    return DEF.team_defense_turnovers(tid, gender=g, offense=offense,
                                      game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _def_fouls(g, tid, offense, game_ids=None):
    """Fouls committed/drawn per scheme (the line-risk read)."""
    return DEF.team_defense_fouls(tid, gender=g, offense=offense,
                                  game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _def_leaders(g, offense, game_ids=None):
    """League leaderboard per scheme — where this team ranks vs the pool."""
    return DEF.league_defense_leaders(gender=g, offense=offense,
                                      game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _defender_profiles(g, tid, game_ids=None):
    """Per-defender on-ball FG%/PPS allowed (the `guarded_by_id` tag). Dormant
    until coaches tag who contested — fills in as coverage grows."""
    return EXPL.defender_profiles(tid, gender=g, game_ids=game_ids)


@st.cache_data(ttl=600, show_spinner=False)
def _def_players_faced(g, game_ids=None):
    """Per-player PPP vs each defense faced, ranked vs the league pool (card ctx)."""
    return DEF.player_defenses_faced(gender=g, game_ids=game_ids)


# ── SITUATIONAL views (helpers/situational.py — the Situational super-tab) ────────
@st.cache_data(ttl=600, show_spinner=False)
def _situational_view(g, tid, game_ids=None):
    """play_type / defense usage + scoring by quarter / score-state / on-a-run, for
    one team's tracked games. `game_ids` scopes to a season's tracked games (the
    page passes the team's season-scoped bundle ids); None = current via
    _team_game_ids."""
    gids = list(game_ids) if game_ids is not None else S._team_game_ids(tid)
    return SIT.team_situational(tid, S.fetch_events(gids), gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _after_outcome_view(g, tid, game_ids=None):
    """How the team plays AFTER a make / miss / turnover on both ends — the
    after-outcome response splits (helpers/situational.py team_after_outcome).
    `game_ids` scopes a season's tracked games; None = current via _team_game_ids."""
    gids = list(game_ids) if game_ids is not None else S._team_game_ids(tid)
    return SIT.team_after_outcome(tid, S.fetch_events(gids), gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _runs_view(g, tid, game_ids=None):
    """Scoring-run profile + raw run list for one team's tracked games
    (helpers/runs.py). `game_ids` scopes an archive season; None = current."""
    import helpers.runs as RN
    gids = list(game_ids) if game_ids is not None else S._team_game_ids(tid)
    if not gids:
        return None
    return RN.team_runs(tid, S.fetch_events(gids))


@st.cache_data(ttl=600, show_spinner=False)
def _by_game_type(g, tid, season="Current"):
    """How the team plays by GAME TYPE (Regular/District/Playoff/…) — record +
    margin from every game, efficiency + shot mix from the tracked ones."""
    import helpers.insights_team as INT
    return INT.team_by_game_type(tid, gender=g, season=season)


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
#  Big Bet 5 split in progress: five top tabs now live in helpers/dashboard/
#  as render(ctx) @st.fragments — the page builds a SimpleNamespace ctx of the
#  shared per-team state at each call site and hands it over (convention in
#  helpers/dashboard/__init__.py). The Charts + Lab block is still inline.
#
#  EXTRACTED (helpers/dashboard/<module>.render(ctx)):
#    overview.py     → tab_over      Overview
#    players_tab.py  → tab_players   Players (nested 2PT/3PT sub-tabs inside)
#    sched.py        → tab_sched     Schedule + box-score picker
#    scout_tab.py    → tab_scout     Scout  (tab position 2 — second-most used)
#    profile_tab.py  → tab_prof      Player Profile
#
#  STILL INLINE — the Charts + Lab block (the hard one; shared data batch):
#    with tab_lab:     creates the 4 ANALYST sub-tabs (ch_adv bld play impact)
#       — created BEFORE tab_charts so the ch_* names exist for the with-blocks
#       below; a `with ch_x:` routes output into whichever tab owns the object,
#       no matter where the block physically sits in the file.
#    with tab_charts:  creates the 6 top-level Charts tabs; Offense nests
#       (ch_sc sh play) and Defense nests (ch_df dscheme rb).
#       Scoring/Shooting/Rebounding/Defense/Trends render INSIDE this block —
#       they SHARE one computed-once data batch (quarter, qs, cbg, poss, tb,
#       ob…) and hold no widgets, which is why they are NOT fragmented. This
#       shared batch is why the block resists a clean per-tab extraction: pull
#       it apart only after decoupling the batch (refactor, then move).
#       Play Style (DPLAYSTYLE.render, helpers/dashboard/playstyle_tab.py) and
#       Impact Lab (_fx_chimpact) ARE fragments — each owns a radio, so flipping
#       it reruns only that sub-tab.
#    _fx_chqt/_fx_chadv/_fx_chbld → ch_qt/ch_adv/ch_bld  (Quarters/Advanced/Build,
#       rendered BELOW at module level — the sub-tab objects are module globals)
#    tab_gloss   → Glossary
# ══════════════════════════════════════════════════════════════════════════════
# Lazy-load: a top-level "View" segmented_control instead of st.tabs, so only
# the chosen view's heavy queries run each rerun (st.tabs computes every tab).
# Inner sub-tabs (Charts/Lab) keep their st.tabs; the @st.fragment bodies keep
# their own fast reruns. Switching View reruns the page once.
# Players (roster scan) + Player Profile (one-player drill) fold into one "Roster"
# view with an inner lazy selector — scan the roster, switch to drill into a name.
# Only the chosen sub-view's fragment runs (see the Roster gate near the file tail,
# after _prof_ctx is built).
_TD_VIEWS = ["Overview", "Scout", "Insights", "Projection", "Roster",
             "Schedule", "Charts", "Lab", "Share", "Glossary"]
# Icons make the top-level nav read as primary navigation, not just another
# toggle (only the label list drives display; the option values are unchanged so
# session state / routing below stay identical).
_TD_VIEW_ICONS = {"Overview": "📊", "Scout": "🔍", "Insights": "💡",
                  "Projection": "🔮", "Roster": "👥", "Schedule": "📅",
                  "Charts": "📈", "Lab": "🧪", "Share": "📤", "Glossary": "📖"}
_tdview = _seg("View", _TD_VIEWS, default="Overview", key="td_view",
               format_func=lambda v: f"{_TD_VIEW_ICONS.get(v, '')} {v}") \
    or "Overview"

# Persistent team-identity chrome: the slim banner (name · tier · record · Power)
# above the view switcher output on every view EXCEPT Overview, which draws the
# full header (banner + glance + zones) itself — so the team you're reading is
# never ambiguous. Results-math fields only → Free-safe; season-scoped via
# season_pick (never hardcode 'Current' — prod reads the rolled-over season).
if _tdview != "Overview":
    import helpers.dashboard.team_card as _TCARD
    _TCARD.render_banner(SimpleNamespace(
        sc_score=sc_score, rec=rec, team_id=team_id, gender=gender,
        scored=scored, has_tracked=has_tracked, season=season_pick))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
# The Overview tab lives in helpers/dashboard/overview.py (Big Bet 5 split);
# ctx carries the page-level shared state plus the page helpers it calls.
_over_ctx = SimpleNamespace(bundle=bundle, players=players, team_id=team_id,
                            gender=gender, has_tracked=has_tracked,
                            log=log, rec=rec, bd=bd, soff=soff, summ=summ,
                            scored=scored, tracked=tracked, sc_score=sc_score,
                            sc_track=sc_track, rank_info=rank_info,
                            GOOD=GOOD, BAD=BAD, BLUE=BLUE, GREY=GREY,
                            ACCENT=ACCENT, style=_style,
                            leader_bar=_leader_bar,
                            league_stat_pools=_league_stat_pools,
                            season=season_pick)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — PLAYERS
# ══════════════════════════════════════════════════════════════════════════════
if _tdview == "Overview":
    DOVER.render(_over_ctx)


# The Players tab lives in helpers/dashboard/players_tab.py (Big Bet 5 split);
# ctx carries the page-level shared state plus the page helpers it calls.
_players_ctx = SimpleNamespace(bundle=bundle, players=players, team_id=team_id,
                               gender=gender, has_tracked=has_tracked,
                               RATING_COLS=RATING_COLS,
                               RATING_COLS_ALL=RATING_COLS_ALL,
                               PLAYER_LEADER_GROUPS=PLAYER_LEADER_GROUPS,
                               GOOD=GOOD, BLUE=BLUE, GREY=GREY, ACCENT=ACCENT,
                               PURPLE=PURPLE, PINK=PINK, style=_style,
                               pctf=_pctf, archetypes=_LGBIND(_archetypes),
                               zone_player_shooting=_zone_player_shooting,
                               player_leaderboards=_player_leaderboards,
                               season=season_pick)


# _players_ctx is rendered under the merged "Roster" view (file tail), alongside
# the Player Profile drill — not its own top-level view anymore.


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════


# The Schedule tab lives in helpers/dashboard/sched.py — the first carved-out
# module of the Big Bet 5 split; ctx carries the page-level shared state.
_sched_ctx = SimpleNamespace(bundle=bundle, rec=rec, log=log, scored=scored,
                             tracked=tracked, team_id=team_id,
                             GOOD=GOOD, BAD=BAD, style=_style,
                             is_current=_is_cur_season)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — CHARTS  (6 tabs: Offense · Play Style · Defense · Situational ·
#                   Trends · Quarters; Offense + Defense carry nested sub-tabs)
# ══════════════════════════════════════════════════════════════════════════════
if _tdview == "Schedule":
    DSCHED.render(_sched_ctx)


# The analyst toys live under one Lab tab — Scout and the game-prep charts
# stop competing with the correlation heatmap for a coach's attention. Created
# before tab_charts so the ch_* objects exist for every with-block below.
if _tdview == "Lab":
    st.caption("Analyst tools — deeper dives beyond the game-prep core.")
    (ch_adv, ch_bld, ch_impact) = st.tabs(
        ["Advanced", "Build", "Impact Lab"])

if _tdview == "Charts":
    # Six top-level stories instead of ten flat tabs: Offense and Defense carry
    # nested sub-tabs. Scheme nests under Defense (it IS the defensive-identity
    # deep dive, mirroring Play Style on offense); Rebounding folds in as Glass.
    # Every ch_* object is still a module global referenced by the `with ch_*:`
    # blocks scattered below — a `with ch_x:` routes output into whichever tab
    # owns the object regardless of where the body sits in the file, so only
    # THIS block drives what the user sees.
    (tab_off, ch_ps, tab_def, ch_sit, ch_tr, ch_qt) = st.tabs(
        ["Offense", "Play Style", "Defense", "Situational", "Trends",
         "Quarters"])
    with tab_off:
        (ch_sc, ch_sh, ch_play) = st.tabs(
            ["Scoring", "Shooting", "Playmaking"])
    with tab_def:
        (ch_df, ch_dscheme, ch_rb) = st.tabs(
            ["Team Defense", "Scheme", "Glass"])

    # ── Defense Scheme super-tab (the one-tap `defense` deep dive) ──────────
    # Modular renderer in helpers/dashboard/defense_tab.py (mirrors Play Style);
    # the page passes plain values + its own cached wrappers. Self-gates on
    # has_tracked internally (own @st.fragment), so NOT in the empty-state loop.
    with ch_dscheme:
        _def_ctx = SimpleNamespace(
            team_id=team_id, gender=gender, has_tracked=has_tracked,
            players=players, tracked_ids=tuple(bundle["tracked_ids"]),
            ACCENT=ACCENT, BLUE=BLUE, GREY=GREY, GOOD=GOOD,
            BAD=BAD, PURPLE=PURPLE, PINK=PINK,
            located_team=_located_team, located_allowed=_located_allowed,
            league_pps=_LGBIND(_league_pps_located), shot_model=_LGBIND(_shot_model),
            def_view=_LGBIND(_def_view), def_families=_LGBIND(_def_families),
            def_profiles=_LGBIND(_def_profiles), cross_pd=_LGBIND(_def_cross),
            def_tovs=_LGBIND(_def_tovs), def_fouls=_LGBIND(_def_fouls),
            def_leaders=_LGBIND(_def_leaders),
            def_players_faced=_LGBIND(_def_players_faced),
            factors=_LGBIND(_def_factors),
            defender_profiles=_LGBIND(_defender_profiles),
            is_current=_is_cur_season)
        DDEFENSE.render(_def_ctx)

    # ── Play Style super-tab (the explicit set-call deep dive) ──────────────
    # Modular renderer in helpers/dashboard/playstyle_tab.py; the page passes
    # plain values + its own cached wrappers so caching stays here and the module
    # is testable in isolation. Self-gates on has_tracked internally (it is its
    # own @st.fragment), so it is NOT in the empty-state loop below.
    with ch_ps:
        _ps_ctx = SimpleNamespace(
            team_id=team_id, gender=gender, has_tracked=has_tracked,
            players=players, tracked_ids=tuple(bundle["tracked_ids"]),
            ACCENT=ACCENT, BLUE=BLUE, GREY=GREY, GOOD=GOOD, BAD=BAD,
            PURPLE=PURPLE, PINK=PINK, pctf=_pctf,
            located_team=_located_team,
            named_view=_LGBIND(_named_playtype_view),
            playtype_view=_LGBIND(_playtype_view),
            set_profiles=_LGBIND(_set_profiles_view),
            feeders=_LGBIND(_feeders_view),
            role_splits=_LGBIND(_team_role_splits_view),
            league_leaders=_LGBIND(_named_leaders_view),
            league_pps=_LGBIND(_league_pps_located),
            shot_model=_LGBIND(_shot_model),
            named_sets_all=_LGBIND(_named_sets_all),
            set_profiles_all=_LGBIND(_set_profiles_all),
            factors=_LGBIND(_pt_factors),
            turnover_types=_LGBIND(_tov_types_view),
            is_current=_is_cur_season)
        DPLAYSTYLE.render(_ps_ctx)

    # ── Situational super-tab (play_type/defense by quarter/score/run) ──────
    # Modular renderer in helpers/dashboard/situational_tab.py; self-gates on
    # has_tracked internally (own @st.fragment), so NOT in the empty-state loop.
    with ch_sit:
        _sit_ctx = SimpleNamespace(
            team_id=team_id, gender=gender, has_tracked=has_tracked,
            players=players, tracked_ids=tuple(bundle["tracked_ids"]),
            ACCENT=ACCENT, BLUE=BLUE, GREY=GREY, GOOD=GOOD, BAD=BAD,
            PURPLE=PURPLE, PINK=PINK,
            situational=_TMBIND(_situational_view),
            after_outcome=_TMBIND(_after_outcome_view),
            runs=_TMBIND(_runs_view),
            by_game_type=(_by_game_type if _is_cur_season
                          else _partial(_by_game_type, season=season_pick)),
            is_current=_is_cur_season)
        DSITUATIONAL.render(_sit_ctx)

    if not has_tracked:
        for _ch in (ch_sc, ch_sh, ch_rb, ch_df, ch_tr):
            with _ch:
                empty_state("No tracked games yet",
                            "The analytics wall is built from play-by-play. Track a "
                            "game in the Game Tracker to light up scoring, shooting, "
                            "defense, play types and the rest.", icon="📊")
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

        # League pools for tile deltas + verdict lines (own team included in
        # the average — one team out of a pool barely moves it, and it keeps
        # the math honest on tiny leagues).
        _lgff = _league_ff(gender, season_pick)
        _lg_pace = [r.get("Pace") for r in tracked.values()]
        _lg_drtg = [r.get("DRtg") for r in tracked.values()]
        _lg_ppp = [r["ORtg"] / 100 for r in tracked.values()
                   if r.get("ORtg") is not None]
        _lg_efg = [v["off"]["eFG"] for v in _lgff.values()]
        _lg_oefg = [v["def"]["eFG"] for v in _lgff.values()]
        _lg_ftov = [v["def"]["TOV"] for v in _lgff.values()]
        _lg_orb = [v["off"]["ORB"] for v in _lgff.values()]
        _lg_dreb = [1 - v["def"]["ORB"] for v in _lgff.values()]

        # ───────────────────────────────────────────── SCORING ──────────────
        with ch_sc:
            # plain-word read first (Insights pattern) — the numbers below are
            # the evidence, not the message
            _sc_lines = []
            _sc_pts = soff["pts2"] + soff["pts3"] + soff["ptsft"]
            if _sc_pts:
                _p3 = soff["pts3"] / _sc_pts
                _idw = ("an inside-first offense"
                        if soff["pct_paint"] >= 0.45 else
                        "a three-happy offense" if _p3 >= 0.35 else
                        "a balanced scoring diet")
                _sc_lines.append((
                    "identity", None,
                    f"<b>{soff['pct_paint']*100:.0f}%</b> of points come in the "
                    f"paint · <b>{_p3*100:.0f}%</b> from three — {_idw}."))
            _sc_tim = [r for r in (plen or [])
                       if r["label"] != "Untimed" and r["FGA"] >= 10]
            if _sc_tim:
                _sc_best = max(_sc_tim, key=lambda r: _ppp(r, ppf, ftpf) or 0)
                _sc_bp = _ppp(_sc_best, ppf, ftpf)
                if _sc_bp:
                    _sc_lines.append((
                        "possessions", _sc_best["FGA"],
                        "Most efficient shooting "
                        f"<b>{_sc_best['label'].lower()}</b> into the possession "
                        f"— <b>{_sc_bp:.2f} points per possession</b>."))
            if _sc_lines:
                _verdict_lines(_sc_lines)

            pmcols = st.columns(4)
            pmcols[0].metric("Pace", f"{summ.get('POSS_pg', 0):.1f}",
                             help="Possessions per game.",
                             **_lg_delta(summ.get("POSS_pg", 0), _lg_pace,
                                         neutral=True))
            pmcols[1].metric("Pts / poss", f"{S._safe(tb['PTS'], poss):.2f}",
                             **_lg_delta(S._safe(tb["PTS"], poss), _lg_ppp,
                                         dec=2))
            pmcols[2].metric("Pts / game", f"{rec['PF_pg']:.1f}")
            pmcols[3].metric("Paint pts %", _pctf(soff["pct_paint"]))

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Points by source**")
                dn = _donut(soff["pts2"], soff["pts3"], soff["ptsft"],
                            colors=(ACCENT, BLUE, GREY), height=300)
                st.plotly_chart(dn, width="stretch", key="sc_src")
            with c2:
                # season scoring breakdown (us vs opponents) — moved up beside
                # the source donut so the Scoring tab reads as a pure season
                # snapshot. Quarter/half splits now live only in the Quarters
                # tab (they were byte-identical dups here).
                st.markdown("**Scoring breakdown — us vs opponents**")
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
                _style(_bfig, 300)
                st.plotly_chart(_bfig, width="stretch", key="sc_buckets_season")
            st.caption("Left: points by shot type (2s / 3s / FTs). Right: "
                       "field-goal points by play type over tracked games · "
                       "bench = points by inferred non-starters. Points off "
                       "turnovers / 2nd chance / fast break are scoring you "
                       "create; opponent bars are what you allow. "
                       "Quarter & half splits → **Quarters** tab.")

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
                    "ScEff": f"{r['SCE']:.3f}",
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
            _shp, _shc, _shm = st.tabs(
                ["Shot Profile", "Contest", "Creation & Shot-making"])
            with _shp:
                # plain-word read first — shot-making vs the looks created
                # (the full SMOE breakdown lives in Shot Lab further down)
                _sv_zo = zones["off"]
                _sv_zx = bundle["zone_xfg"]
                _sv_fga = sum(_sv_zo[z]["FGA"] for z in TA.ZONES)
                _sv_lines = []
                if _sv_fga >= 25:
                    _sv_exp = sum(_sv_zo[z]["FGA"] * _sv_zx[z]["xFG%"]
                                  for z in TA.ZONES)
                    _sv_act = sum(_sv_zo[z]["FGM"] for z in TA.ZONES)
                    _sv_moe = (_sv_act - _sv_exp) / _sv_fga * 100
                    _sv_w = ("finishes <b>better than the looks it creates</b>"
                             if _sv_moe >= 1 else
                             "finishes about what its looks are worth"
                             if _sv_moe > -1 else
                             "<b>leaves points on good looks</b>")
                    _sv_lines.append((
                        "shot-making", _sv_fga,
                        f"This team {_sv_w} — {_sv_moe:+.1f}pp FG% vs expected "
                        f"(made {_sv_act:.0f}, looks said {_sv_exp:.0f})."))
                    _sv_zd = [(TA.ZONE_LABELS[z].split("/")[0].strip(),
                               (_sv_zo[z]["FG%"] - _sv_zx[z]["xFG%"]) * 100,
                               _sv_zo[z]["FGA"])
                              for z in TA.ZONES if _sv_zo[z]["FGA"] >= 10]
                    if len(_sv_zd) >= 2:
                        _sv_hot = max(_sv_zd, key=lambda d: d[1])
                        _sv_cold = min(_sv_zd, key=lambda d: d[1])
                        _sv_lines.append((
                            "zones", None,
                            f"Hottest vs expected: <b>{_sv_hot[0]}</b> "
                            f"({_sv_hot[1]:+.0f}pp on {_sv_hot[2]} FGA) · "
                            f"coldest: <b>{_sv_cold[0]}</b> "
                            f"({_sv_cold[1]:+.0f}pp on {_sv_cold[2]} FGA)."))
                if _sv_lines:
                    _verdict_lines(_sv_lines)

                # ── floor-spacing index (located-shot x,y blend vs league) ────
                _sp = _spacing(gender, team_id, _vis_key)
                if _sp.get("index") is not None:
                    st.markdown("<div class='lab-hdr'>Floor-spacing index</div>",
                                unsafe_allow_html=True)
                    _spa, _spb = st.columns([1, 2])
                    with _spa:
                        st.plotly_chart(
                            _pp_gauge(_sp["index"], "Spacing",
                                      ACCENT if _sp["index"] >= 50 else AWAY),
                            width="stretch", key="sp_gauge")
                    with _spb:
                        _sph = ""
                        for _c in _sp["components"]:
                            _sv = (f"{_c['value']:.1f} ft" if _c["key"] == "x_spread"
                                   else f"{_c['value'] * 100:.0f}%")
                            _sph += _pctile_bar(_c["label"], _sv, _c["pct"])
                        st.markdown(_sph, unsafe_allow_html=True)
                    st.caption(_sp["note"] + f"  ·  {_sp['n']} located shots over a "
                               f"{_sp['pool_n']}-team pool.")
                sm = st.columns(7)
                sm[0].metric("eFG%", _pctf(S.efg(tb)),
                             **_lg_delta(S.efg(tb), _lg_efg, pct=True))
                sm[1].metric("TS%", _pctf(S.ts(tb)))
                sm[2].metric("FG%", _pctf(S.fg_pct(tb)))
                sm[3].metric("3P%", _pctf(S.fg3_pct(tb)))
                sm[4].metric("Paint FG%", _pctf(S.paint_fg_pct(tb)))
                sm[5].metric("FT%", _pctf(S.ft_pct(tb)))
                sm[6].metric("ScEff", f"{S.shot_efficiency(tb):.3f}",
                             help="Scoring efficiency = (PTS − FT) / (2PA·2 + 3PA·3) "
                                  "— FG points as a share of the max possible.")

                st.markdown("**Shot diet** — attempts by type")
                paint2 = tb["paint_FGA"]
                mid2 = tb["2PA"] - paint2
                sd = go.Figure(go.Bar(
                    x=[paint2, mid2, tb["3PA"]],
                    y=["Paint 2s", "Other 2s", "3s"], orientation="h",
                    marker_color=[ACCENT, "#d29922", BLUE], marker_line_width=0,
                    text=[paint2, mid2, tb["3PA"]], textposition="auto"))
                sd.update_xaxes(title="Attempts")
                _style(sd, 240)
                sd.update_layout(margin=dict(l=4, r=14, t=10, b=30))
                st.plotly_chart(sd, width="stretch", key="sh_diet")

                # zone aggregates — feed the xFG table below and the legacy
                # zone charts in the no-tap-data fallback branch
                zo = zones["off"]
                zbt = bundle["zones_by_type"]["off"]   # {'all','2','3': {zone: agg}}

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
                            colorscale=DIVERGE, cmin=20, cmax=65, showscale=True,
                            colorbar=dict(title="FG%"),
                            line=dict(color="#0d1117", width=2)),
                        text=[f"{lbl[z]}<br>{zmap[z]['FG%']*100:.0f}%"
                              if zmap[z]["FGA"] else f"{lbl[z]}<br>—"
                              for z in TA.ZONES],
                        textfont=dict(size=10, color="#f0f6fc"),
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

                # Real x/y shot charts when tap-captured locations exist; the
                # hand-positioned zone bubbles stay as the legacy fallback for
                # seasons logged before tap capture.
                _td_shots = _located_team(team_id, tuple(bundle["tracked_ids"]))
                if _td_shots:
                    st.markdown(f"**Shot chart** — {len(_td_shots)} tap-captured "
                                "attempts")
                    hz1, hz2 = st.columns(2)
                    with hz1:
                        _hxf, _hxn = _shot_hexbin(
                            _td_shots, title="Volume & points per shot",
                            league_pps=_league_pps_located(gender))
                        st.plotly_chart(_hxf, width="stretch", key="sh_hexbin")
                    with hz2:
                        _smf, _ = _shot_map(_td_shots, title="Makes & misses")
                        st.plotly_chart(_smf, width="stretch", key="sh_dotmap")
                    st.caption("Hexagon size = attempts, color = points per shot "
                               "vs league average. Dots are individual shots — "
                               "green make, red ✕ miss.")
                    # points-over-expected heat — shot QUALITY, not just makes
                    _pxf, _pxn = _shot_hexbin(
                        _td_shots, title="Points over expected — shot quality",
                        model=_shot_model(gender), mode="poe")
                    st.plotly_chart(_pxf, width="stretch", key="sh_poe")
                    st.caption("Points over expected — **green** hexes beat the league "
                               "make-rate for that spot (good shots being made), **red** "
                               "are below. Separates shot *quality* from shot volume.")
                    _td_db = S.distance_buckets(_td_shots)
                    if _td_db:
                        st.caption("By length — " + S.distance_buckets_caption(_td_db))
                else:
                    # Legacy zone views — only when no tap-captured x/y shots
                    # exist; the hexbin/dot charts supersede them otherwise.
                    st.markdown("<div class='lab-hdr'>Zone analysis — where they "
                                "shoot (2s vs 3s)</div>", unsafe_allow_html=True)
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
                            text_fn=lambda a: f"{a['FG%']*100:.0f}%"
                            if a["FGA"] else "—"),
                            width="stretch", key="sh_zfg_t")
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

                def _avefig(zt, three=False):
                    # on a 3-pt-only chart the C zone is the top-of-key 3, not
                    # the paint — label it Center
                    zl = ["Center" if z == "C" and three
                          else TA.ZONE_LABELS[z].split("/")[0].strip()
                          for z in TA.ZONES]
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
                    st.plotly_chart(_avefig(zxbt["3"], three=True),
                                    width="stretch", key="sh_ave3")
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

            with _shc:
                # guarded vs unguarded — overall, then split by 2/3, zone & creation
                gd = bundle["guarded_detail"]
                g, u = guarded["guarded"], guarded["unguarded"]

                # plain-word read first — what contests actually cost this team
                _ct_n = g["FGA"] + u["FGA"]
                if _ct_n >= 25:
                    _ct_gap = (u["eFG"] - g["eFG"]) * 100
                    _ct_lines = [(
                        "contest", _ct_n,
                        f"Open looks are worth <b>{_ct_gap:+.1f}pp eFG%</b> to "
                        f"this team; <b>{_pctf(guarded['guard_share'])}</b> of "
                        "attempts are contested.")]
                    _ct_pz = [(TA.ZONE_LABELS[z].split("/")[0].strip(),
                               (gd["by_zone"][z]["unguarded"]["eFG"]
                                - gd["by_zone"][z]["guarded"]["eFG"]) * 100,
                               gd["by_zone"][z]["guarded"]["FGA"])
                              for z in TA.ZONES
                              if gd["by_zone"][z]["guarded"]["FGA"] >= 8
                              and gd["by_zone"][z]["unguarded"]["FGA"] >= 4]
                    if _ct_pz:
                        _ct_worst = max(_ct_pz, key=lambda d: d[1])
                        _ct_lines.append((
                            "pressure point", None,
                            f"A hand up hurts most at <b>{_ct_worst[0]}</b> — "
                            f"{_ct_worst[1]:+.0f}pp eFG% swing open vs guarded "
                            f"({_ct_worst[2]} guarded FGA)."))
                    _verdict_lines(_ct_lines)

                st.markdown("<div class='lab-hdr'>Guarded vs unguarded</div>",
                            unsafe_allow_html=True)
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

                # dominant- vs weak-hand-side shooting (each shooter's own handedness)
                hs = bundle.get("hand_splits")
                if hs:
                    st.markdown("<div class='lab-hdr'>Dominant vs weak hand side</div>",
                                unsafe_allow_html=True)
                    st.dataframe(pd.DataFrame([
                        _shot_row("Dominant side", hs["dominant"]["all"], ppf, ftpf),
                        _shot_row("Weak side", hs["weak"]["all"], ppf, ftpf)]),
                        hide_index=True, width="stretch")
                    hc1, hc2 = st.columns([2, 1])
                    with hc1:
                        hf = go.Figure()
                        for lbl, key in [("FG%", "FG%"), ("2P%", "2P%"),
                                         ("3P%", "3P%"), ("eFG%", "eFG")]:
                            hf.add_trace(go.Bar(
                                name=lbl, x=["Dominant", "Weak"],
                                y=[hs["dominant"]["all"][key] * 100,
                                   hs["weak"]["all"][key] * 100]))
                        hf.update_layout(barmode="group")
                        hf.update_yaxes(title="%")
                        _style(hf, 300)
                        st.plotly_chart(hf, width="stretch", key="sh_hand")
                    with hc2:
                        st.metric("Dominant-side share", _pctf(hs["dom_share"]))
                        _de, _we = hs["dominant"]["all"]["eFG"], hs["weak"]["all"]["eFG"]
                        st.metric("Dominant eFG% edge", f"{(_de - _we) * 100:+.1f}pp")
                        st.caption("Right-handers' right-half shots are 'dominant', "
                                   "lefties mirrored. Dead-center shots ignored.")

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

            with _shm:
                cmap = {"both": "Pass + screen", "pass": "Off a pass",
                        "created": "Off a screen", "self": "Self-created"}
                order = ["both", "pass", "created", "self"]

                # plain-word read first — which creation type actually pays
                _cr_tot = crb["total"]["FGA"]
                if _cr_tot >= 25:
                    _cr_cands = [(cmap[k], crb[k]) for k in order
                                 if crb[k]["FGA"] >= 10]
                    _cr_lines = []
                    if _cr_cands:
                        _cr_best = max(_cr_cands, key=lambda it: it[1]["PPS"])
                        _cr_lines.append((
                            "creation", _cr_best[1]["FGA"],
                            f"Best looks come <b>{_cr_best[0].lower()}</b> — "
                            f"{_cr_best[1]['PPS']:.2f} points per shot."))
                    _cr_selfsh = S._safe(crb["self"]["FGA"], _cr_tot)
                    _cr_lines.append((
                        "mix", _cr_tot,
                        f"<b>{_cr_selfsh*100:.0f}%</b> of attempts are "
                        "self-created (no pass, no screen) — "
                        + ("a lot of hero ball." if _cr_selfsh >= 0.4 else
                           "a healthy dose of ball movement." if _cr_selfsh <= 0.25
                           else "a normal mix.")))
                    _verdict_lines(_cr_lines)

                # shot-creation breakdown
                st.markdown("<div class='lab-hdr'>Shot-creation breakdown</div>",
                            unsafe_allow_html=True)
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
                    st.markdown("**ScEff by creation type** (2s vs 3s)")
                    st.plotly_chart(_crt_fig(
                        lambda a: a["SCE"], "ScEff",
                        text_fn=lambda a: f"{a['SCE']:.2f}" if a["FGA"] else "—"),
                        width="stretch", key="sh_crb_sce")
                with cc4:
                    st.markdown("**Points / shot by creation type** (2s vs 3s)")
                    st.plotly_chart(_crt_fig(
                        lambda a: a["PPS"], "Pts / shot",
                        text_fn=lambda a: f"{a['PPS']:.2f}" if a["FGA"] else "—"),
                        width="stretch", key="sh_crb_pps")
                st.caption("Each creation graph split by shot value. ScEff = (FG points) "
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

                # (Shooting by quarter lived here as a byte-identical dup of the
                # Quarters → Shooting lines — cut; Quarters owns time splits.)
                st.caption("Shooting by quarter (FG% / eFG% / TS% / FT% lines per "
                           "period) → **Quarters** tab.")

                # ── Shot Lab (moved here from Advanced): shot-making vs expectation ──
                st.markdown("<div class='lab-hdr'>Shot Lab — shot-making vs "
                            "expectation</div>", unsafe_allow_html=True)
                st.caption("SMOE — Shot-Making Over Expected, split by shot value. "
                           "Expected makes come from the make-rate of each shot's "
                           "(zone · creation · contest) type. Positive = they finish "
                           "better than the looks they generate.")
                zsl_bt = bundle["zones_by_type"]["off"]   # {'all','2','3': {zone: agg}}
                zxsl_bt = bundle["zone_xfg_by_type"]      # {'2','3': {zone: agg}}

                def _shotlab(zmap, zxmap, title, keypfx, three=False):
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
                        diffs = [("Center" if z == "C" and three
                                  else TA.ZONE_LABELS[z].split("/")[0].strip(),
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
                _shotlab(zsl_bt["3"], zxsl_bt["3"], "3-pointers", "3",
                         three=True)

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
                slm[2].metric("Scoring efficiency (ScEff)",
                              f"{S.shot_efficiency(tb):.3f}")
                slm[3].metric("Contested rate",
                              _pctf(bundle["guarded"]["guard_share"]))
                st.caption("Look quality measures the difficulty of shots created; "
                           "shot-making over expected measures whether they convert "
                           "them. A great offense does both.")

        # ───────────────────────────────────────────── REBOUNDING ───────────
        with ch_rb:
            # plain-word read first — where this team's glass actually ranks
            _rb_dreb = S._safe(tb["DRB"], tb["DRB"] + ob["ORB"])
            _rb_opct = TA.percentile(ff["off"]["ORB"], _lg_orb,
                                     higher_better=True)
            _rb_dpct = TA.percentile(_rb_dreb, _lg_dreb, higher_better=True)
            if _rb_opct is not None and _rb_dpct is not None:
                _rb_w = ("owns both ends of the glass"
                         if _rb_opct >= 60 and _rb_dpct >= 60 else
                         "crashes hard but leaks boards on defense"
                         if _rb_opct >= 60 and _rb_dpct < 45 else
                         "cleans its own glass but rarely crashes"
                         if _rb_dpct >= 60 and _rb_opct < 45 else
                         "is getting outworked on the boards"
                         if _rb_opct < 40 and _rb_dpct < 40 else
                         "holds its own on the boards")
                _verdict_lines([(
                    "glass", None,
                    f"Offensive glass sits at the <b>{_rb_opct:.0f}th "
                    f"percentile</b>, defensive glass the <b>{_rb_dpct:.0f}th"
                    f"</b> — this team {_rb_w}.")])

            rm = st.columns(6)
            rm[0].metric("OREB%", _pctf(ff["off"]["ORB"]),
                         help="Share of own misses rebounded.",
                         **_lg_delta(ff["off"]["ORB"], _lg_orb, pct=True))
            rm[1].metric("DREB%", _pctf(_rb_dreb),
                         help="Share of opponent misses rebounded.",
                         **_lg_delta(_rb_dreb, _lg_dreb, pct=True))
            rm[2].metric("Opp OREB%", _pctf(ff["def"]["ORB"]),
                         help="Opponent's offensive-rebound rate — lower is "
                              "better work on the defensive glass.",
                         **_lg_delta(ff["def"]["ORB"], _lg_orb, pct=True,
                                     inverse=True))
            rm[3].metric("REB / game", f"{tb['TRB'] / ng:.1f}")
            rm[4].metric("OREB / game", f"{tb['ORB'] / ng:.1f}")
            rm[5].metric("DREB / game", f"{tb['DRB'] / ng:.1f}")

            st.caption("Blocks, steals & forced turnovers → **Team Defense** "
                       "sub-tab. "
                       "Quarter-by-quarter glass battle (OREB / DREB / margin "
                       "per period) → **Quarters** tab.")

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

            # ── rebound geography — where the misses (and boards) live ───────
            st.markdown("<div class='lab-hdr'>Rebound geography — where the "
                        "misses land</div>", unsafe_allow_html=True)
            _rg = _reb_geography(team_id, tuple(bundle["tracked_ids"]))
            _rg_n = len(_rg["own"]) + len(_rg["opp"])
            if _rg_n < 10:
                st.caption("Needs tap-captured shot locations with a logged "
                           "rebounder — fills in as located tracked games build.")
            else:
                _rg_own_pct = (sum(1 for s in _rg["own"] if s["reb"] == "Ours")
                               / max(len(_rg["own"]), 1) * 100)
                _rg_opp_pct = (sum(1 for s in _rg["opp"] if s["reb"] == "Theirs")
                               / max(len(_rg["opp"]), 1) * 100)
                _verdict_lines([(
                    "second chances", _rg_n,
                    f"We rebound <b>{_rg_own_pct:.0f}%</b> of our own located "
                    f"misses and give back <b>{_rg_opp_pct:.0f}%</b> of theirs "
                    "— each ✕ below is the shot the board came from.")])
                rg1, rg2 = st.columns(2)
                with rg1:
                    _reb_map(_rg["own"], "Our misses — who got the board",
                             key="rb_geo_own")
                with rg2:
                    _reb_map(_rg["opp"], "Their misses — who got the board",
                             key="rb_geo_opp")
                st.caption("Missed shots at their tap-captured origin — green ✕ "
                           "= we secured the rebound, red ✕ = they did. Left "
                           "court: second chances we create. Right court: red "
                           "clusters are where we leak offensive boards.")

            # putbacks — the shot IS roughly where the offensive board happened
            _pb = [s for s in _td_shots if s.get("play_type") == "putback"]
            if len(_pb) >= 5:
                st.markdown("<div class='lab-hdr'>Putbacks — where second-chance "
                            "shots go up</div>", unsafe_allow_html=True)
                _pbf, _pbn = _shot_map(_pb, title="")
                st.plotly_chart(_pbf, width="stretch", key="rb_putback")
                _pbm = sum(1 for s in _pb if s["make"])
                st.caption(f"{_pbm}/{_pbn} putbacks made — a putback attempt "
                           "sits at the spot of the offensive board, so this "
                           "doubles as an OREB location map. Small sample: "
                           "directional.")

        # ───────────────────────────────────────────── DEFENSE ──────────────
        with ch_df:
            # plain-word read first — where the defense ranks + where it leaks
            _df_lines = []
            _df_dpct = TA.percentile(summ.get("DRtg"), _lg_drtg,
                                     higher_better=False) \
                if summ.get("DRtg") is not None else None
            _df_tpct = TA.percentile(ff["def"]["TOV"], _lg_ftov,
                                     higher_better=True)
            if _df_dpct is not None and _df_tpct is not None:
                _df_lines.append((
                    "defense", None,
                    f"Defense sits at the <b>{_df_dpct:.0f}th percentile</b> "
                    f"league-wide; it forces turnovers at the "
                    f"<b>{_df_tpct:.0f}th</b>."))
            # opponents' most valuable look vs us — points per attempt so 2s
            # and 3s compare honestly
            _df_zdt = bundle["zones_by_type"]["def"]
            _df_cands = []
            for _tk, _tv in (("2", 2), ("3", 3)):
                for _z in TA.ZONES:
                    _a = _df_zdt[_tk][_z]
                    if _a["FGA"] >= 8:
                        _df_cands.append(
                            (f"{TA.ZONE_LABELS[_z].split('/')[0].strip()} "
                             f"{_tk}s", _a["FG%"] * _tv, _a["FG%"], _a["FGA"]))
            if _df_cands:
                _df_worst = max(_df_cands, key=lambda d: d[1])
                _df_lines.append((
                    "leak", _df_worst[3],
                    f"Opponents' best look against us: <b>{_df_worst[0]}</b> — "
                    f"{_df_worst[2]*100:.0f}% for {_df_worst[1]:.2f} points "
                    "per attempt."))
            if _df_lines:
                _verdict_lines(_df_lines)

            dm = st.columns(4)
            dm[0].metric("Def Rtg", f"{summ.get('DRtg', 0):.1f}",
                         help="Points allowed / 100 poss. Lower is better.",
                         **_lg_delta(summ.get("DRtg", 0), _lg_drtg,
                                     inverse=True))
            dm[1].metric("Opp eFG%", _pctf(ff["def"]["eFG"]),
                         **_lg_delta(ff["def"]["eFG"], _lg_oefg, pct=True,
                                     inverse=True))
            dm[2].metric("Forced TOV%", _pctf(ff["def"]["TOV"]),
                         **_lg_delta(ff["def"]["TOV"], _lg_ftov, pct=True))
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
                ddn = _donut(sdef["pts2"], sdef["pts3"], sdef["ptsft"],
                             colors=(AWAY, "#f0a500", GREY), height=300,
                             center=f"{sdef['pct_paint']*100:.0f}%<br>"
                                    "<span style='font-size:10px'>in paint</span>")
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

            st.caption("Opponent scoring by quarter & half (Def Rtg, opp PPP vs "
                       "season average, per-period grades) → **Quarters** tab.")

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
                # plain-word read — the roster's best contest numbers
                _mu_agg = _md.groupby("Defender")[["FGM", "FGA"]].sum()
                _mu_agg = _mu_agg[_mu_agg["FGA"] >= 10]
                if len(_mu_agg):
                    _mu_best = (_mu_agg["FGM"] / _mu_agg["FGA"]).idxmin()
                    _mu_fga = int(_mu_agg.loc[_mu_best, "FGA"])
                    _mu_fg = (_mu_agg.loc[_mu_best, "FGM"]
                              / _mu_agg.loc[_mu_best, "FGA"] * 100)
                    _verdict_lines([(
                        "lockdown", _mu_fga,
                        f"Best contest numbers on the roster: <b>{_mu_best}</b> "
                        f"— shooters they covered hit just {_mu_fg:.0f}%.")])
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
                _fm = st.columns(3)
                _fm[0].metric("Fouls / game",
                              f"{_tf['total'] / max(_tf['games'], 1):.1f}")
                _fm[1].metric("Opp FTA given up", _tf["opp_fta"],
                              help="Free throws opponents earned from this "
                                   "team's fouls.")
                _fm[2].metric("Total fouls", _tf["total"])
                st.caption("Opp FTA = free throws your fouls gave up. When the "
                           "team fouls by quarter (Q4 spikes = late-game trouble) "
                           "→ **Quarters** tab.")

        # ───────────────────────────────────────────── TRENDS ───────────────
        with ch_tr:
            if len(trend) < 2:
                st.info("Need at least two tracked games for trend charts.")
            else:
                # plain-word read first — which way is this team pointing
                _fr_last = trend[-3:]
                _fr_l3 = sum(e["NetRtg"] for e in _fr_last) / len(_fr_last)
                _fr_all = sum(e["NetRtg"] for e in trend) / len(trend)
                _fr_w = ("<b>trending up</b>" if _fr_l3 - _fr_all >= 3 else
                         "<b>trending down</b>" if _fr_l3 - _fr_all <= -3 else
                         "holding steady")
                _verdict_lines([(
                    "form", len(trend),
                    f"Last {len(_fr_last)} tracked games: <b>{_fr_l3:+.1f}</b> "
                    f"net rating vs <b>{_fr_all:+.1f}</b> on the season — "
                    f"{_fr_w}.")])

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
                    # One diverging bar per stat — the % swing from the loss
                    # baseline, sorted by size. Margin/NetRtg excluded (their
                    # loss baselines sit near zero, so % swings explode; the
                    # metric tiles above already carry them).
                    WL_CATS = [("Pts for", "PF", False), ("Pts against", "PA", False),
                               ("Off Rtg", "ORtg", False),
                               ("Def Rtg", "DRtg", False),
                               ("Pace", "Pace", False), ("eFG%", "eFG", True),
                               ("Opp eFG%", "oeFG", True), ("FG%", "FG", True),
                               ("3P%", "TP", True), ("TS%", "TS", True),
                               ("Turnovers", "TOV", False), ("OREB", "ORB", False),
                               ("DREB", "DRB", False), ("Assists", "AST", False),
                               ("Steals", "STL", False), ("Blocks", "BLK", False)]
                    # stats where the winning direction is DOWN
                    WL_LOW_BETTER = {"PA", "DRtg", "oeFG", "TOV"}
                    swings = []
                    for lbl, k, ispct in WL_CATS:
                        wv, lv = wl["W"][k], wl["L"][k]
                        if not lv:
                            continue
                        chg = (wv - lv) / abs(lv) * 100
                        winning_dir = chg <= 0 if k in WL_LOW_BETTER else chg >= 0
                        fmt = (lambda v: f"{v * 100:.1f}%") if ispct \
                            else (lambda v: f"{v:.1f}")
                        swings.append((lbl, chg, winning_dir, fmt(wv), fmt(lv)))
                    swings.sort(key=lambda s: abs(s[1]))
                    wlf = go.Figure(go.Bar(
                        x=[s[1] for s in swings], y=[s[0] for s in swings],
                        orientation="h",
                        marker_color=[GOOD if s[2] else BAD for s in swings],
                        marker_line_width=0,
                        text=[f"{s[1]:+.0f}%" for s in swings],
                        textposition="auto",
                        hovertext=[f"wins {s[3]} · losses {s[4]}" for s in swings],
                        hovertemplate="%{y}: %{x:+.1f}% in wins<br>%{hovertext}"
                                      "<extra></extra>"))
                    wlf.add_vline(x=0, line=dict(color="#30363d"))
                    wlf.update_xaxes(title="% change in wins (vs loss average)")
                    _style(wlf, 460)
                    wlf.update_layout(margin=dict(l=4, r=14, t=8, b=30))
                    st.plotly_chart(wlf, width="stretch", key="tr_wl")
                    st.caption(f"Each stat's per-game average in {wl['W']['n']} wins "
                               f"vs {wl['L']['n']} losses, as the % swing from the "
                               "loss baseline — longest bars change most when this "
                               "team wins. Green = moved in the winning direction "
                               "(down for Pts against / Def Rtg / Opp eFG% / "
                               "turnovers). Effect-size-ranked signature stats → "
                               "**Insights** tab.")
                    _jump("Insights", "Open Insights →", "tr_jump_ins")

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

                # Headliners only — pace / turnovers / assists / steals already
                # have their own lines in the per-game stat grid above, so no
                # standalone dups.
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("<div class='lab-hdr'>Efficiency — per game"
                                "</div>", unsafe_allow_html=True)
                    ortg = [e["ORtg"] for e in trend]
                    drtg = [e["DRtg"] for e in trend]
                    eff = _trend_line(
                        tx, [("ORtg", ortg, ACCENT), ("DRtg", drtg, AWAY)],
                        None, "tr_eff", height=320, yaxis="Pts / 100 poss")
                    st.plotly_chart(eff, width="stretch", key="tr_eff")
                with c2:
                    st.markdown("<div class='lab-hdr'>Shooting — per game"
                                "</div>", unsafe_allow_html=True)
                    ef = _trend_line(
                        tx, [("eFG%", [e["eFG"] * 100 for e in trend], ACCENT),
                             ("Opp eFG%", [e["oeFG"] * 100 for e in trend], AWAY)],
                        None, "tr_efg", height=320, yaxis="eFG%")
                    st.plotly_chart(ef, width="stretch", key="tr_efg")

                # (Margin distribution + home/away splits are results-math, not
                # tracked-event trends — they live with the résumé now.)
                st.caption("Game-margin dot plot & home/away splits → **Lab → "
                           "Advanced → Résumé & Form**.")
                _jump("Lab", "Open Lab →", "tr_jump_lab")


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
        st.caption("The single home for time-split data — every tracked stat "
                   "broken out by quarter/half and averaged over tracked games "
                   "('For' / 'Allowed' = this team vs opponents; small samples "
                   "are directional). The headline below owns which quarter you "
                   "win; the four sub-tabs go deep: **Scoring & Efficiency** "
                   "(ratings, PPP, pace), **Shooting** (offense + defense shot "
                   "profile), **Control · Glass · Discipline** (rebounds, "
                   "turnovers, fouls, four factors), and **Reference Tables** "
                   "(full per-quarter grids + by-game splits).")

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

        qt1, qt2, qt3, qt4 = st.tabs(
            ["Scoring & Efficiency", "Shooting",
             "Control · Glass · Discipline", "Reference Tables"])

        with qt1:
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

        with qt2:
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
                st.markdown("**Scoring efficiency** — PPS & ScEff")
                st.plotly_chart(_q_lines(
                    qsq, [("Pts / shot", _qv(lambda d: S.ppsa(d["team"])), ACCENT),
                          ("ScEff", _qv(lambda d: S.shot_efficiency(d["team"])), GOOD)],
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

        with qt3:
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

        with qt4:
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

            # Renamed from _shot_row — it shadowed the module-level helper of the
            # same name (line ~206) inside this function.
            def _q_shot_row(label, b, poss_q, gp):
                return {
                    "Period": label, "GP": gp,
                    "FGA": b["FGA"], "FGM": b["FGM"], "FG%": _pctf(S.fg_pct(b)),
                    "2PA": b["2PA"], "2P%": _pctf(S.fg2_pct(b)) if b["2PA"] else "—",
                    "3PA": b["3PA"], "3P%": _pctf(S.fg3_pct(b)) if b["3PA"] else "—",
                    "FTA": b["FTA"], "FT%": _pctf(S.ft_pct(b)) if b["FTA"] else "—",
                    "eFG%": _pctf(S.efg(b)), "TS%": _pctf(S.ts(b)),
                    "Paint%": (_pctf(S.paint_fg_pct(b)) if b["paint_FGA"] else "—"),
                    "PPS": f"{S.pps(b):.2f}", "PPP": f"{S._safe(b['PTS'], poss_q):.2f}",
                    "ScEff": f"{S.shot_efficiency(b):.3f}", "PTS": b["PTS"],
                }

            reg = [q for q in qsq if q <= 4]
            ot = [q for q in qsq if q > 4]
            shot_rows = []
            for q in [x for x in reg if x in (1, 2)]:
                shot_rows.append(_q_shot_row(_q_label(q), qbx[q]["team"],
                                             qbx[q]["poss"], qbx[q]["n_games"]))
            h1b, h1p, h1g = _merge_qbox([1, 2])
            if h1b:
                shot_rows.append(_q_shot_row("H1", h1b, h1p, h1g))
            for q in [x for x in reg if x in (3, 4)]:
                shot_rows.append(_q_shot_row(_q_label(q), qbx[q]["team"],
                                             qbx[q]["poss"], qbx[q]["n_games"]))
            h2b, h2p, h2g = _merge_qbox([3, 4])
            if h2b:
                shot_rows.append(_q_shot_row("H2", h2b, h2p, h2g))
            for q in ot:   # overtime periods, each on its own line
                shot_rows.append(_q_shot_row(_q_label(q), qbx[q]["team"],
                                             qbx[q]["poss"], qbx[q]["n_games"]))
            fb, fp, fg = _merge_qbox(qsq)
            if fb:
                shot_rows.append(_q_shot_row("Full", fb, fp, fg))
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
                # Only quarters that actually have creation data — a sparse book (few
                # tracked games, or an archive) can miss a quarter, and the unguarded
                # cq[q] series below would KeyError on it.
                creg = [q for q in qsq if q <= 4 and q in cq]

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

                fa = _cr_merge([cq[q]["ast"] for q in qsq if q in cq])
                fs = _cr_merge([cq[q]["sc"] for q in qsq if q in cq])
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
            # One heatmap replaces the old 37-chart wall: rows = stats, cols =
            # quarters, color = % deviation from that stat's own cross-quarter
            # average. The selectbox below keeps the per-stat bar drill.
            st.caption("Every team stat the app tracks, by quarter — color = how "
                       "far that quarter sits from the stat's own average across "
                       "quarters (not good/bad; e.g. a red Turnovers cell is a "
                       "LOW-turnover quarter). Hover for the actual value; pick a "
                       "stat below to drill into its bar chart.")

            def _qfmt(kind):
                return ((lambda v: f"{v:.0f}") if kind == "pct"
                        else (lambda v: f"{v:.2f}") if kind == "f2"
                        else (lambda v: f"{v:.1f}"))

            _hm_z, _hm_txt, _hm_hov = [], [], []
            for lbl, fn, kind in reversed(QSPEC):   # reversed: plotly y bottom-up
                vals = [fn(qbx[q]) for q in qsq]
                mean = sum(vals) / len(vals)
                devs = [((v - mean) / abs(mean) * 100) if mean else 0
                        for v in vals]
                tf = _qfmt(kind)
                _hm_z.append([max(-30, min(30, d)) for d in devs])
                _hm_txt.append([tf(v) for v in vals])
                _hm_hov.append([f"{tf(v)} ({d:+.0f}% vs avg)"
                                for v, d in zip(vals, devs)])
            hmf = go.Figure(go.Heatmap(
                z=_hm_z, x=qx, y=[s[0] for s in reversed(QSPEC)],
                text=_hm_txt, texttemplate="%{text}",
                textfont=dict(size=10),
                customdata=_hm_hov,
                hovertemplate="%{y} · %{x}: %{customdata}<extra></extra>",
                colorscale=DIVERGE, zmid=0, zmin=-30, zmax=30,
                colorbar=dict(title="% vs avg"), xgap=2, ygap=2))
            hmf.update_xaxes(side="top")
            _style(hmf, 26 * len(QSPEC) + 60)
            hmf.update_layout(margin=dict(l=4, r=10, t=30, b=10))
            st.plotly_chart(hmf, width="stretch", key="qgrid_heat")

            _qpick = st.selectbox("Drill into a stat",
                                  [s[0] for s in QSPEC], key="qgrid_stat")
            _plbl, _pfn, _pkind = next(s for s in QSPEC if s[0] == _qpick)
            st.plotly_chart(
                _q_bars(qsq, [(_plbl, [_pfn(qbx[q]) for q in qsq], ACCENT)],
                        _plbl, height=280, text_fmt=_qfmt(_pkind)),
                width="stretch", key="qgrid_drill")

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
if _tdview == "Charts":
    with ch_qt:
        _fx_chqt()


@st.fragment
def _fx_playmaking():
    """Passing network + possession flow — the Playmaking view (moved from
    Lab -> Advanced to Charts)."""
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
                    colorscale=HEAT, showscale=True,
                    colorbar=dict(title="Assists"),
                    line=dict(width=2, color="#0d1117")),
                text=[name_by[i] for i in node_ids],
                textposition="middle center",
                textfont=dict(size=10, color="#f0f6fc"),
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
                _e0 = top_edges[0]
                _verdict_lines([(
                    "duo", _e0["count"],
                    f"Top connection: <b>{full_by.get(_e0['from'], '?')} → "
                    f"{full_by.get(_e0['to'], '?')}</b> — {_e0['count']} "
                    f"assists for {_e0['pts']} points.")])
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
                                colorscale=HEAT, showscale=False),
                    text=[f"{p['PTS'] / tot_pts * 100:.0f}%"
                          for p in reversed(top8)], textposition="auto"))
                bal.update_xaxes(title="Share of team points %")
                _style(bal, 300)
                bal.update_layout(margin=dict(l=4, r=14, t=8, b=30))
                st.plotly_chart(bal, width="stretch", key="adv_balance")

# ───────────────────────────────────────── GAME FLOW ────────────────────


if _tdview == "Charts":
    # Playmaking render — deferred to here so _fx_playmaking() is already defined
    # (the ch_* Charts sub-tab objects are module globals, set in the CHARTS view).
    with ch_play:
        _fx_playmaking()


@st.fragment
def _fx_chadv():
    st.caption("The analytics lab — league-relative efficiency, team DNA, "
               "schedule résumé, the passing network and possession flow. (Shot "
               "Lab now lives under Charts → Offense → Shooting.) Most panels "
               "need tracked "
               "games; the résumé works from results alone.")

    adv_eff, adv_res, adv_flow = st.tabs(
        ["Efficiency & DNA", "Résumé & Form", "Game Flow"])

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
            lff = _league_ff(gender, season_pick)
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

        # ── margins & venue (moved from Charts → Trends: results-math) ──────
        st.markdown("<div class='lab-hdr'>Margins & venue</div>",
                    unsafe_allow_html=True)
        mc1, mc2 = st.columns([3, 2])
        with mc1:
            # one dot per game — honest at HS sample sizes where a binned
            # histogram is mostly noise
            ms = go.Figure(go.Scatter(
                x=[g["margin"] for g in log],
                y=[((i % 7) - 3) / 8 for i in range(len(log))],
                mode="markers",
                marker=dict(size=11,
                            color=[GOOD if g["won"] else BAD for g in log],
                            line=dict(width=1, color="#0d1117")),
                hovertext=[f"{g['date'][5:]} {g['site']} {g['opp']}"
                           for g in log],
                hovertemplate="%{hovertext}<br>Margin %{x:+d}<extra></extra>"))
            ms.add_vline(x=0, line=dict(color=GREY, dash="dot"))
            ms.update_xaxes(title="Final margin")
            ms.update_yaxes(visible=False, range=[-1, 1])
            _style(ms, 240)
            st.plotly_chart(ms, width="stretch", key="res_margin")
            st.caption("Every game as one dot — green win, red loss. Dots "
                       "bunched near zero = living dangerously.")
        with mc2:
            venue = bundle["venue"]
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
if _tdview == "Lab":
    with ch_adv:
        _fx_chadv()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 8 — HELPER  (the orphaned helper engines: Predictor + Impact Lab + Lineup)
# ══════════════════════════════════════════════════════════════════════════════
# Helper tab dissolved: matchup Predictor removed, Lineup creator moved to the War
# Room page, Impact Lab moved here under Charts. `if True:` preserves the moved
# Impact-Lab block's original indentation (no wholesale re-indent).
if _tdview == "Lab":
    h_impact = ch_impact

    # fragment: the WPA model radio lives INSIDE, so switching models reruns
    # only the Impact Lab, not the whole page.
    @st.fragment
    def _fx_chimpact():
        if not has_tracked:
            st.info("Tracked games needed for the impact lab (RAPM, WPA, chemistry "
                    "and lineups all run on possession data).")
        else:
            tids = bundle["tracked_ids"]
            my_pids = {p["_pid"] for p in players}
            name_by = {p["_pid"]: f"#{p['number']} {p['name']}" for p in players}

            # ── RAPM ────────────────────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>RAPM — regularized adjusted +/− "
                        "<span style='color:#8b949e;font-size:12px'>· experimental"
                        "</span></div>", unsafe_allow_html=True)
            st.caption("⚗️ Experimental — a college/pro tool on a high-school-size "
                       "book. Points added per 100 possessions vs a league-average "
                       "player, holding teammates AND opponents constant (one ridge "
                       "regression over every tracked possession in the league). "
                       "Treat as directional only: even a full HS season rarely has "
                       "the possessions to separate most players (the wide error "
                       "bands below are the honest signal).")
            _bp = st.toggle(
                "Box-prior (anchor to box impact)", key="il_rapm_boxprior",
                help="Shrink each player toward their box-score impact instead of "
                     "toward league average — keeps stars off 'average' on a short "
                     "book. Off = classic shrink-to-average RAPM.")
            if _bp:
                st.caption("Box-prior on: stars are anchored to their player-rating "
                           "box impact, then moved by the possession data (gentle).")
            rap = _rapm(gender, box_prior=_bp, season=season_pick)
            _wt = _war_tbl(gender, box_prior=_bp, season=season_pick)
            for _wpid, _wrow in rap.items():        # cache_data returns a copy —
                _wv = _wt.get(_wpid)                 # safe to annotate per rerun
                if _wv:
                    _wrow["WAR"] = _wv["WAR"]
            rows_r = sorted([v for pid, v in rap.items() if pid in my_pids],
                            key=lambda v: v["RAPM"], reverse=True)
            if rows_r:
                rc1, rc2 = st.columns([3, 2])
                with rc1:
                    # Two-way quadrant: O-RAPM (x) vs D-RAPM (y), size = poss,
                    # solid = significantly clear of average (engine `sig`),
                    # hollow = directional. Upgrades the old relative bar — the
                    # one bit that says "this impact is real", not just ranked.
                    _GRN, _RED, _BLU = "#3fb950", "#e74c3c", "#58a6ff"
                    _ax = max(2.0,
                              max((abs(v["ORAPM"]) for v in rows_r), default=2),
                              max((abs(v["DRAPM"]) for v in rows_r), default=2)) * 1.1
                    _mp = max((v["poss"] for v in rows_r), default=1) or 1
                    qf = go.Figure()
                    for _sg, _sym, _leg in (
                            (True, "circle", "Clear of average"),
                            (False, "circle-open", "Directional (small sample)")):
                        _grp = [v for v in rows_r if bool(v.get("sig")) == _sg]
                        if not _grp:
                            continue
                        qf.add_trace(go.Scatter(
                            x=[v["ORAPM"] for v in _grp],
                            y=[v["DRAPM"] for v in _grp],
                            mode="markers+text" if _sg else "markers",
                            text=[v["name"] for v in _grp] if _sg else None,
                            textposition="top center",
                            textfont=dict(size=9, color="#c9d1d9"), name=_leg,
                            marker=dict(
                                size=[max(11, min(34, 11 + 25 * (v["poss"] / _mp)))
                                      for v in _grp],
                                symbol=_sym,
                                color=[_GRN if v["RAPM"] > 0 else _RED
                                       for v in _grp],
                                line=dict(width=1.6,
                                          color=[_GRN if v["RAPM"] > 0 else _RED
                                                 for v in _grp])),
                            customdata=[(v["RAPM"], v["poss"]) for v in _grp],
                            hovertemplate=("%{text}<br>" if _sg else "")
                            + "O %{x:+.1f} · D %{y:+.1f} · RAPM "
                            "%{customdata[0]:+.1f} · %{customdata[1]} poss"
                            "<extra></extra>"))
                    qf.add_vline(x=0, line=dict(color="#8b949e", width=1,
                                                dash="dot"))
                    qf.add_hline(y=0, line=dict(color="#8b949e", width=1,
                                                dash="dot"))
                    for _qx, _qy, _txt, _clr in (
                            (0.72, 0.9, "Two-Way Star", _GRN),
                            (-0.76, 0.9, "Stopper", _BLU),
                            (0.72, -0.92, "Off. Engine", ACCENT),
                            (-0.76, -0.92, "Liability", "#8b949e")):
                        qf.add_annotation(x=_qx * _ax, y=_qy * _ax, text=_txt,
                                          showarrow=False, opacity=0.65,
                                          font=dict(size=10, color=_clr))
                    qf.update_xaxes(title="Offensive RAPM →", range=[-_ax, _ax],
                                    zeroline=False)
                    qf.update_yaxes(title="Defensive RAPM →", range=[-_ax, _ax],
                                    zeroline=False)
                    _style(qf, 430)
                    qf.update_layout(margin=dict(l=10, r=14, t=10, b=40))
                    st.plotly_chart(qf, width="stretch", key="il_rapm_quad")
                    st.caption("Right = better offense, up = better defense, "
                               "size = possessions. Solid dots clear league "
                               "average; hollow are directional on the small "
                               "book.")
                with rc2:
                    st.dataframe(pd.DataFrame([{
                        "Player": v["name"], "WAR": v.get("WAR"),
                        "RAPM": v["RAPM"],
                        "O": v["ORAPM"], "D": v["DRAPM"], "Poss": v["poss"],
                    } for v in rows_r]), hide_index=True, width="stretch")
                    st.caption("WAR = HoopWAR — RAPM impact over the player's "
                               "floor time vs a replacement-level player, in "
                               "wins (≈14 pts/win at HS scoring).")

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

            # ── shot quality — SMOE (points over expected, Tier 2) ───────────
            _sq, _sqn = _shot_quality(gender, season_pick)
            if _sq:
                _rows_sq = sorted((v for pid, v in _sq.items() if pid in my_pids),
                                  key=lambda v: -v["poe_shrunk"])
                if _rows_sq:
                    st.markdown("<div class='lab-hdr'>Shot quality — points over "
                                "expected (SMOE)</div>", unsafe_allow_html=True)
                    st.caption(
                        f"Points scored vs what a league model expects from each "
                        f"player's exact shots — continuous (x,y) + contested make "
                        f"probability, league-pooled over {_sqn} located shots and "
                        f"shrunk toward 0 for small samples. + = makes tough shots; "
                        f"− = leaves points on the floor.")
                    st.dataframe(pd.DataFrame([{
                        "Player": v["name"], "Shots": v["n"],
                        "PPS": v["pps"], "xPPS": v["xpps"], "SMOE": v["poe_shrunk"],
                    } for v in _rows_sq]), hide_index=True, width="stretch",
                        column_config={
                            "PPS": st.column_config.NumberColumn("PPS", format="%.2f"),
                            "xPPS": st.column_config.NumberColumn("xPPS", format="%.2f"),
                            "SMOE": st.column_config.NumberColumn("SMOE", format="%+.2f"),
                        })

            # ── rotation: stagger coverage + foul trouble (Tier 2) ──────────
            _cov, _prone = _rotation(
                team_id, _vis_key if _is_cur_season else tuple(bundle["tracked_ids"]))
            if _cov.get("bleed") is not None or _prone:
                st.markdown("<div class='lab-hdr'>Rotation — stagger &amp; foul "
                            "trouble</div>", unsafe_allow_html=True)
                if _cov.get("stars"):
                    _sn = " & ".join(s.get("name", "") for s in _cov["stars"])
                    _rc = st.columns(3)
                    _rc[0].metric("Uncovered minutes",
                                  f"{_cov['uncovered_min_share'] * 100:.0f}%",
                                  help=f"Share of floor time with neither {_sn} on.")
                    _rc[1].metric("Net w/ star on",
                                  f"{_cov['covered_net']:+.1f}"
                                  if _cov["covered_net"] is not None else "—")
                    _rc[2].metric("Net w/ none on",
                                  f"{_cov['uncovered_net']:+.1f}"
                                  if _cov["uncovered_net"] is not None else "—",
                                  f"{-_cov['bleed']:+.1f} bleed"
                                  if _cov["bleed"] is not None else None,
                                  delta_color="inverse")
                    st.caption(_cov["note"])
                if _prone:
                    st.markdown("**Foul-prone (season PF/32):** " + " · ".join(
                        f"{r['name']} {r['pf32']:.1f}" + ("⚠" if r["prone"] else "")
                        for r in _prone[:5]))

            # ── possession-value ledger: points/100 sources vs leaks (Tier 2) ─
            _pl = _poss_ledger(
                team_id, _vis_key if _is_cur_season else tuple(bundle["tracked_ids"]))
            if _pl["offense"] or _pl["defense"]:
                st.markdown("<div class='lab-hdr'>Possession value — where points "
                            "come from vs leak</div>", unsafe_allow_html=True)
                st.caption("Every possession walked to its end. Offense = points we "
                           "score / leaks we commit; Defense = what we allow / force.")
                _plc = st.columns(2)
                for _col, (_lbl, _lg) in zip(
                        _plc, [("Offense", _pl["offense"]),
                               ("Defense (allowed)", _pl["defense"])]):
                    with _col:
                        st.markdown(f"**{_lbl}**")
                        if not _lg:
                            st.caption("No possessions yet.")
                            continue
                        st.metric("Points / 100", f"{_lg['pts_100']:.0f}",
                                  f"PPP {_lg['ppp']:.2f}", delta_color="off")
                        st.dataframe(pd.DataFrame([
                            {"Source": s["label"], "Pts/100": s["pts_100"]}
                            for s in _lg["sources"]]), hide_index=True,
                            width="stretch")
                        _o = {x["key"]: x for x in _lg["outcomes"]}
                        st.caption(
                            f"Scored {_o['scored']['pct'] * 100:.0f}% · own board "
                            f"{_o['oreb']['pct'] * 100:.0f}% · lost "
                            f"{_o['lost']['pct'] * 100:.0f}% · TOV "
                            f"{_o['turnover']['pct'] * 100:.0f}% · eFG "
                            f"{_lg['efg'] * 100:.0f}%")

            # ── win probability added ────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>Win Probability Added (WPA)</div>",
                        unsafe_allow_html=True)
            wmode = _seg(
                "Model", ["Scoring", "Possession"], key="il_wpa_mode",
                help="Scoring = win-prob swing on made baskets. Possession = value "
                     "over an average possession on every shot AND turnover, split "
                     "into offense and defense (credits stops, steals, blocks).") \
                or "Scoring"
            st.caption("Opponent-adjusted: each game's pre-game spread feeds the "
                       "win-probability model, so a stop or comeback earned as the "
                       "underdog (vs a stronger team) is worth more, and padding a "
                       "blowout is worth less.")
            sw = _season_wpa(gender, "scoring" if wmode == "Scoring" else "possession",
                             season_pick)
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

            # ── chemistry (pair net, context-adjusted) ───────────────────────
            st.markdown("<div class='lab-hdr'>Chemistry — pair net rating</div>",
                        unsafe_allow_html=True)
            chem = _chemistry(team_id, tuple(tids))
            _chem_adj = bool(chem.get("totals", {}).get("adjusted"))
            _ek = "adj_net" if _chem_adj else "net"
            st.caption("Team net points / 100 while a pair of players share the "
                       "floor. Positive = the duo outscores opponents together."
                       + (" **Adjusted** for opponent strength and for who else "
                          "was on the floor with them — a duo riding the star "
                          "gives that credit back." if _chem_adj else
                          " ⚠ Not enough rated-lineup possessions to fit the "
                          "context adjustment yet — raw nets shown."))
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
                        emax = max((abs(e[_ek]) for e in edges), default=1) or 1
                        for e in edges:
                            a, b = e["a"], e["b"]
                            if a not in pos or b not in pos:
                                continue
                            x0, y0 = pos[a]
                            x1, y1 = pos[b]
                            clr = GOOD if e[_ek] >= 0 else BAD
                            net.add_trace(go.Scatter(
                                x=[x0, x1], y=[y0, y1], mode="lines",
                                line=dict(width=1 + 4 * abs(e[_ek]) / emax,
                                          color=clr),
                                hoverinfo="text",
                                hovertext=f"{e['names'][0]} + {e['names'][1]}: "
                                          f"adj net {e[_ek]:+.1f} · raw "
                                          f"{e['net']:+.1f} ({e['poss']} poss)",
                                opacity=0.55, showlegend=False))
                        # pair-net NUMBER on each edge (not just hover) so the
                        # graph reads at a glance
                        _lx, _ly, _lt = [], [], []
                        for e in edges:
                            a, b = e["a"], e["b"]
                            if a not in pos or b not in pos:
                                continue
                            _lx.append((pos[a][0] + pos[b][0]) / 2)
                            _ly.append((pos[a][1] + pos[b][1]) / 2)
                            _lt.append(f"{e[_ek]:+.0f}")
                        net.add_trace(go.Scatter(
                            x=_lx, y=_ly, mode="text", text=_lt,
                            textfont=dict(size=10, color="#e6edf3"),
                            hoverinfo="skip", showlegend=False))
                        net.add_trace(go.Scatter(
                            x=[pos[i][0] for i in node_ids],
                            y=[pos[i][1] for i in node_ids], mode="markers+text",
                            marker=dict(
                                size=[18 + 26 * (nodes[i]["poss"]
                                      / max(nodes[n]["poss"] for n in node_ids))
                                      for i in node_ids],
                                color=[nodes[i].get(_ek, nodes[i]["net"])
                                       for i in node_ids],
                                colorscale=DIVERGE, cmid=0, showscale=True,
                                colorbar=dict(title="Solo net"),
                                line=dict(width=2, color="#0d1117")),
                            text=[name_by.get(i, "?").split()[0] for i in node_ids],
                            textposition="middle center",
                            textfont=dict(size=9, color="#f0f6fc"),
                            hovertext=[f"{name_by.get(i,'?')}<br>"
                                       f"net {nodes[i].get(_ek, nodes[i]['net']):+.1f} · "
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
                    top_pairs = sorted(edges, key=lambda e: e[_ek],
                                       reverse=True)
                    st.dataframe(pd.DataFrame([{
                        "Pair": f"{e['names'][0]} + {e['names'][1]}",
                        "Adj Net": round(e.get("adj_net", e["net"]), 1),
                        "Net (raw)": round(e["net"], 1), "Poss": e["poss"],
                    } for e in top_pairs]), hide_index=True, width="stretch",
                        height=min(420, 60 + 32 * len(top_pairs)))
            else:
                st.caption("Not enough shared-floor possessions to draw chemistry "
                           "pairs yet.")

            # ── observed lineup units ────────────────────────────────────────
            st.markdown("<div class='lab-hdr'>Lineups — observed 5-man units"
                        "</div>", unsafe_allow_html=True)
            st.caption("Each exact five that shared the floor for enough "
                       "possessions (observed, not simulated). **Adj Net** "
                       "corrects every possession for the quality of the "
                       "opposing FIVE on the floor — not just the opponent's "
                       "record — so beating up on a good team's bench unit "
                       "doesn't inflate a lineup. **±95%** is the confidence "
                       "band on that net from the per-possession scoring "
                       "variance; **≈games** is the sample in full team-games "
                       "of floor time. Small samples carry wide bands — trust "
                       "the sign before the size.")
            units = _units(team_id, tuple(tids))
            if units:
                _adj_on = any(u.get("adjusted") for u in units)
                st.dataframe(pd.DataFrame([{
                    "Lineup": " · ".join(u["names"]),
                    "Adj Net": u["AdjNet"], "±95%": u["ci95"],
                    "Net (raw)": u["Net"],
                    "ORtg": u["AdjORtg"], "DRtg": u["AdjDRtg"],
                    "Poss": u["poss"], "≈games": u["games_eq"],
                } for u in units]), hide_index=True, width="stretch",
                    height=min(460, 60 + 32 * len(units)),
                    column_config={
                        "Adj Net": st.column_config.NumberColumn(format="%+.1f"),
                        "±95%": st.column_config.NumberColumn(format="±%.0f"),
                        "Net (raw)": st.column_config.NumberColumn(format="%+.1f"),
                    })
                if not _adj_on:
                    st.caption("⚠ Not enough rated-opponent possessions to fit "
                               "the adjustment yet — Adj Net currently equals "
                               "the raw net.")
            else:
                st.caption("No 5-man unit cleared the minimum possessions yet.")

    with h_impact:
        _fx_chimpact()


# ══════════════════════════════════════════════════════════════════════════════
#  CHARTS ▸ BUILD YOUR OWN CHART  (a free-form chart lab over the team's data)
# ══════════════════════════════════════════════════════════════════════════════
# The Scout tab lives in helpers/dashboard/scout_tab.py (Big Bet 5 split);
# ctx carries the page-level shared state plus the page helpers it calls.

# Opponent scout: build a ctx scoped to ANY opponent team (same shape as the
# dashboard ctx + the same shared helpers), so the Scout tab can render the full
# report on a team you select while keeping YOUR team for the matchup planner.
# The entitlement read-filter is recomputed for the opponent (League-wide coach →
# their pooled games only; cold opponent → record/rank + your hand-entered intel).
def _opp_scout_ctx(opp_tid):
    _ov = ENT.team_visible_tracked_ids(AUTH.current_user(), opp_tid,
                                       season=season_pick)
    _ovk = None if _ov is None else tuple(sorted(_ov))
    ob = _team_bundle(opp_tid, gender, _ovk, season=season_pick)
    _oraw = any(g["tracked"] for g in ob["game_log"])
    o_has, _olock = ENT.tracked_gate(AUTH.current_user(), opp_tid, _oraw,
                                     season=season_pick)
    return SimpleNamespace(
        bundle=ob, players=ob["players"], team_id=opp_tid, gender=gender,
        has_tracked=o_has, summ=ob["summary"], soff=ob["scoring_off"],
        brk=ob["breakeven"], ff=ob["four_factors"], tb=ob["team_box"],
        GOOD=GOOD, BAD=BAD, ACCENT=ACCENT, BLUE=BLUE, style=_style, pctf=_pctf,
        scout=lambda _t, _g, _lim, _ex: _scout(_t, _g, _lim, _ex, _ovk,
                                               season_pick, _season_gp),
        archetypes=_archetypes, located_team=_located_team,
        zone_pair_bars=_zone_pair_bars)

# every rated team this gender (tid, name) for the opponent picker
_all_teams = sorted(((tid, v.get("name", f"#{tid}")) for tid, v in scored.items()),
                    key=lambda x: x[1])

_scout_ctx = SimpleNamespace(bundle=bundle, players=players, team_id=team_id,
                             gender=gender, has_tracked=has_tracked,
                             summ=summ, soff=soff, brk=brk, ff=ff, tb=tb,
                             GOOD=GOOD, BAD=BAD, ACCENT=ACCENT, BLUE=BLUE,
                             style=_style, pctf=_pctf,
                             # scout always targets the selected team → reuse its
                             # visible-game key (the AXIS-2 read-filter).
                             scout=lambda _t, _g, _lim, _ex: _scout(
                                 _t, _g, _lim, _ex, _vis_key,
                                 season_pick, _season_gp),
                             archetypes=_archetypes, located_team=_located_team,
                             zone_pair_bars=_zone_pair_bars,
                             # opponent scout: pick & scout any team, keep yours
                             opp_ctx=_opp_scout_ctx, all_teams=_all_teams,
                             my_team_id=team_id)
if _tdview == "Scout":
    DSCOUT.render(_scout_ctx)

# ══════════════════════════════════════════════════════════════════════════════
#  TAB — INSIGHTS (the scout that reads itself, scoped to this team)
# ══════════════════════════════════════════════════════════════════════════════
_insights_ctx = SimpleNamespace(players=players, team_id=team_id, gender=gender,
                                has_tracked=has_tracked,
                                tracked_ids=tuple(bundle["tracked_ids"]),
                                season=season_pick, season_gp=_season_gp)
if _tdview == "Insights":
    DINS.render(_insights_ctx)

# ══════════════════════════════════════════════════════════════════════════════
#  TAB — PROJECTION (depth-chart minutes + signature-stat optimizer; paid+team-gated)
# ══════════════════════════════════════════════════════════════════════════════
# Self-gates on is_paid + has_tracked + the engine's own MIN_TEAM_GAMES rotation
# gate. game_ids = this team's entitlement-visible tracked ids, season-scoped.
if _tdview == "Projection":
    DPROJ.render(SimpleNamespace(
        team_id=team_id, gender=gender, has_tracked=has_tracked,
        is_paid=ENT.has_paid_plan(AUTH.current_user()),
        game_ids=(list(_vis) if _vis is not None else None),
        season=season_pick, players=players))

# ══════════════════════════════════════════════════════════════════════════════
#  TAB — SHARE (premade social-media cards; own-team surface — see share_tab)
# ══════════════════════════════════════════════════════════════════════════════
if _tdview == "Share":
    DSHARE.render(SimpleNamespace(team_id=team_id, gender=gender,
                                  team_name=team["name"], vis_key=_vis_key,
                                  season=season_pick))


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
                                  colorscale=HEAT, showscale=True,
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
if _tdview == "Lab":
    with ch_bld:
        _fx_chbld()


if _tdview == "Glossary":
    glossary_tab("ta_gloss")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB — PLAYER PROFILE  (ported from 6_Players.py; scoped to this team's roster)
# ══════════════════════════════════════════════════════════════════════════════
def _render_profile(P, pid, rows, zsplits, zguard, hsplits=None):
    from types import SimpleNamespace
    from helpers.dashboard.player_card import render_card
    # _prof_gp (module global): None for a live current season → the fetchers keep
    # their current-season default (byte-identical); a PAST season's gender tracked
    # ids — either the picked archive, or the last-season FALLBACK when the current
    # season has no tracked games yet — so the whole card (shot map, game log,
    # play-type mix, spacing, on/off) reads that season's pool.
    _gp = _prof_gp
    render_card(SimpleNamespace(
        P=P, pid=pid, rows=rows, paid=True, accent=ACCENT,
        zsplits=zsplits, zguard=zguard, hsplits=hsplits,
        badges=_badges(gender, _gp).get(pid, []),
        archetype=_archetypes(gender, _gp).get(pid),
        pgb=_pgb(_gp), located=_pp_located(pid, _gp),
        foulft=_pp_foulft(_gp).get(pid),
        named_sets=_named_sets_all(gender, _gp).get(pid),
        role_splits=_role_splits_all(gender, _gp).get(pid),
        set_profiles=_set_profiles_all(gender, _gp).get(pid),
        season=_prof_season, season_gp=_gp,
    ))


# The Player Profile tab lives in helpers/dashboard/profile_tab.py; the heavy
# renderer (_render_profile) and zone tables stay here and ride in as callables.
#
# LAST-SEASON FALLBACK: a brand-new (empty) current season has no tracked games,
# so the profile would dead-end right when a coach wants to scout their RETURNING
# players. When the current season has no tracked data but an archive exists, the
# profile reads the newest archived season's pool instead — clearly labeled — and
# hands back to the live season as soon as games are tracked. (An explicitly
# picked archive season keeps its own pool; this only fires on current+empty.)
_prof_season, _prof_note = season_pick, None
if _is_cur_season and not _raw_tracked:
    _arch_lbls = SEAS.archived_labels()
    if _arch_lbls:
        _prof_season = _arch_lbls[0]                     # newest first
        _prof_note = (f"No tracked games this season yet — showing "
                      f"**{_prof_season}** (last season) so returning players "
                      "still have a card. This switches back automatically once "
                      "you track this season's games.")
_prof_gp = (None if SEAS.is_current(_prof_season)
            else tuple(_gender_tracked_ids(gender, _prof_season)))
if _prof_note and not _prof_gp:
    _prof_note = None                                    # archive is untracked too
    _prof_season, _prof_gp = season_pick, _season_gp
# profile visibility: the real gate (has_tracked), or the labeled fallback
_prof_open = has_tracked or bool(_prof_note)


def _prof_bind(fn):
    return fn if _prof_gp is None else _partial(fn, game_ids=_prof_gp)


_prof_ctx = SimpleNamespace(team_id=team_id, gender=gender, team=team,
                            has_tracked=_prof_open, tracked_lock=_tracked_lock,
                            fallback_note=_prof_note,
                            ptable_full=_prof_bind(_ptable_full),
                            pp_zone_tables=_prof_bind(_pp_zone_tables),
                            render_profile=_render_profile, season=_prof_season)
# ══════════════════════════════════════════════════════════════════════════════
#  TAB — ROSTER  (Players roster scan + Player Profile drill, merged)
# ══════════════════════════════════════════════════════════════════════════════
# One top-level view, two lazy sub-views behind a segmented selector: "Roster"
# (the whole-roster scan — DPLAY) and "Player" (drill into one name — DPROF, which
# carries its own player selectbox). Only the chosen branch's @st.fragment runs,
# so the heavy roster wall and the heavy player card never compute together.
if _tdview == "Roster":
    _rv = _seg("View", ["Roster", "Impact & Splits", "Player"], default="Roster",
               key="td_roster_view") or "Roster"
    if _rv == "Roster":
        DPLAY.render(_players_ctx)
    elif _rv == "Impact & Splits":
        import helpers.advanced_ratings as ADV
        _avg_rtg = _avg_player_ratings(tuple(bundle["tracked_ids"])) if has_tracked else {}
        ADV.leaderboard(players, has_tracked, key="td", ratings=_avg_rtg)
    else:
        DPROF.render(_prof_ctx)
