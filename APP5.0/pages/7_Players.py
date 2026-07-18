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

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.ui import (page_chrome, page_header, lab_hero as _lab_hero,
                        empty_state, rgb as _rgb, shot_panel as _shot_panel,
                        style_fig as _style, CARD_BG, GRID, HEAT, PALETTE,
                        gender_radio, grid as _grid, glossary_key as _glossary_key)
from helpers.cards import (fmt as _fmt, pctile as _pctile,
                           pctile_bar as _pctile_bar,
                           tier as _tier, glass as _glass, onoff_html as _onoff_html,
                           gauge_dial as _gauge, team_short as _team_short, bar_h)
from helpers.court import (shot_chart as _shot_chart, shot_map as _shot_map,
                           hot_zones as _hot_zones,
                           ZONE_FULLNAME as _ZONE_FULLNAME)
from helpers.glossary import glossary_tab
import helpers.player_ratings as PR
import helpers.playtypes as PT
import helpers.team_ratings as TR
import helpers.stats as S
import helpers.badges as BG
import helpers.archetypes as ARC
import helpers.shrinkage as SH
import helpers.matchups as MX
import helpers.player_edge as PE
from helpers.dashboard.player_edge import render as _render_edge
import helpers.trends as TRD
import helpers.fouls as FL
import helpers.reports as RP
import helpers.manual_box as MB
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.seasons as SEAS

_cfg, ACCENT = page_chrome("Players")
# The Players page is a whole-league (multi-team) pool, so every tracked surface
# here is a CROSS-TEAM aggregate → per the MULTI-TEAM rule it needs the Coaches'
# Co-op (league-wide), not just Paid. Own-team tracked depth lives on the Team
# Dashboard; on this league-wide page a solo-paid coach is box-only until they opt
# into the pool. (`_PAID` = the effective "show tracked depth" gate for this page.)
_ident = AUTH.current_user()
_HAS_PAID = ENT.has_paid_plan(_ident)
_PAID = _HAS_PAID and ENT.viewer_is_league_wide(_ident)
# Lock copy keyed to WHY: not paid → upgrade; paid-but-solo → co-op invite.
_LOCK = (ENT.MSG_PAID if not _HAS_PAID
         else ENT.MSG_POOL_BANNED if ENT.is_pool_banned(_ident)
         else ENT.MSG_COOP_INVITE)
RATING_COLS = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]

# Accent-tinted card glows (accent is dynamic, so these stay page-local). The
# static .pl-pct*/.pl-glass*/.pl-scout rules these build on live in
# assets/style.css; structural "lab" classes live there too.
ar0, ag0, ab0 = _rgb(ACCENT)
st.markdown(f"""
<style>
/* accent-tinted neon header (dynamic accent overrides the cyan default) */
.pl-hdr {{ font-size:16px; font-weight:800; color:#f0f6fc; text-transform:uppercase;
          letter-spacing:1.5px; border-left:3px solid {ACCENT}; padding-left:11px;
          margin:18px 0 10px; text-shadow:0 0 18px rgba({ar0},{ag0},{ab0},0.35); }}
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
        ("VPS", "Value Point System (VPS)", "f2", True, None, 0),
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


def _visible_groups():
    """STAT_GROUPS for the viewer — free users lose the event-derived stats so
    box-only leaderboards/pickers stay clean (no Paid leaks)."""
    if _PAID:
        return STAT_GROUPS
    out = []
    for _title, _leaves in STAT_GROUPS:
        _keep = [lf for lf in _leaves if lf[0] not in PR.EVENT_DERIVED_STATS]
        if _keep:
            out.append((_title, _keep))
    return out


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


def _leader_bar(top, key, fmt, color=ACCENT, height=200):
    """Horizontal bar chart of a top-N leader list (#1 on top)."""
    seq = list(reversed(top))                      # plotly draws first at bottom
    names = [f"{r['name']}<br><span style='font-size:9px;color:#8b949e'>"
             f"{_team_short(r['team'])}</span>" for r in seq]
    vals = [r[key] for r in seq]
    texts = [_fmt(v, fmt) for v in vals]
    return bar_h(names, vals, texts, color, height)


# ── podium (gold/silver/bronze top-3 cards) ──────────────────────────────────

def _podium(top3, key, fmt):
    """Gold/silver/bronze top-3 cards for a stat."""
    styles = [("#f0a500", "#3a2a00"), ("#adb5bd", "#1e2229"),
              ("#cd7f32", "#271505")]
    cols = st.columns(min(3, len(top3)) or 1)
    for i, (col, r) in enumerate(zip(cols, top3)):
        c, bg = styles[i]
        col.markdown(
            f"<div style='background:linear-gradient(135deg,{bg},#0d1117);"
            f"border:1px solid {c};border-radius:12px;padding:14px;"
            f"text-align:center'>"
            f"<div style='font-size:15px;font-weight:800;color:#f0f6fc;"
            f"margin-top:4px'>{r['name']}</div>"
            f"<div style='font-size:11px;color:#8b949e'>"
            f"{_team_short(r['team'])} · {r['class']}</div>"
            f"<div style='font-size:26px;font-weight:800;color:{c};"
            f"margin-top:6px'>{_fmt(r[key], fmt)}</div></div>",
            unsafe_allow_html=True)


# ── spotlight (neon headline KPI tile) ───────────────────────────────────────

def _spotlight(num, label, sub=""):
    """Neon spotlight tile for a 'made-up'/headline metric (HTML string)."""
    return (f"<div class='pl-spot'><div class='pl-spot-n'>{num}</div>"
            f"<div class='pl-spot-l'>{label}</div>"
            f"<div class='pl-spot-s'>{sub}</div></div>")


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER + CONTROLS
# ══════════════════════════════════════════════════════════════════════════════

_lab_hero("Player Analytics Lab", phase="ANALYZE",
          sub="Every tracked stat · shot charts · 0-100 ratings · "
              "invented metrics — all built from play-by-play events.")
_glossary_key("eFG%", "TS%", "USG%", "ORtg", "DRtg", "NetRtg", "AST/TO", "TOV%",
              "DSHOT%", "PPS", "SCE", "3PAr", "FTr", "per-32", "xFG%", "SMOE",
              label="📖 Stat key — what the advanced columns mean")

c1, c2 = st.columns([1, 2])
# keyed so the command palette (helpers/ui) can land a jump on the right league
gender = gender_radio(c1, key="pl_gender")
min_games = c2.slider("Minimum games played", 1, 16, 2, 1,
                      help="Players below this drop out of the pool. Higher "
                           "values cut small-sample noise but shrink the field. "
                           "Ratings are recomputed against whoever qualifies.")

# Season picker — view a past/archived season's player pool. Only appears once a
# season has been rolled over; the active season is the default so the page is
# byte-identical with no archive. A PAST season is an OPEN archive (full tracked
# depth to everyone, no Paid/Co-op gate) scoped to that season's game pool.
_season_opts = SEAS.season_options()
if len(_season_opts) > 1:
    _slbl = c1.selectbox(
        "Season", [l for _v, l in _season_opts], key="pl_season",
        help="View a past season's players. Past seasons are an open archive — "
             "free, full depth, to everyone; every stat and rating is computed "
             "vs that season's pool only.")
    season_pick = next(v for v, l in _season_opts if l == _slbl)
else:
    season_pick = SEAS.ACTIVE
_is_cur_season = SEAS.is_current(season_pick)

@st.cache_data(ttl=600, show_spinner=False)
def _stat_table(g, mg, vis=None):
    # vis = tuple of visible tracked game ids (the AXIS-2 read-filter); None =
    # unrestricted (admin). NOTE _game_filter treats an empty/falsy game_ids as
    # "whole tracked sample", so an empty visible set must NEVER reach here — the
    # caller downgrades to box-only instead (see the table-build block below).
    return PR.player_stat_table(gender=g, min_games=mg,
                                game_ids=(list(vis) if vis else None))


@st.cache_data(ttl=600, show_spinner=False)
def _zone_tables(vis=None):
    """Per-player zone + guarded/open + hand-side splits, read-filtered to the
    viewer's visible games (vis None = whole tracked sample, for admin)."""
    ev = S.fetch_events(list(vis) if vis else None)
    return (S.player_zone_splits(events=ev), S.player_zone_guarded(events=ev),
            S.player_hand_splits(events=ev))


@st.cache_data(ttl=600, show_spinner=False)
def _shot_model(vis=None):
    """League distance×value make-rate model for the points-over-expected heat,
    read-filtered to the viewer's visible games (vis None = whole sample)."""
    return S.distance_make_model(events=S.fetch_events(list(vis) if vis else None))


@st.cache_data(ttl=600, show_spinner=False)
def _named_sets(g, vis=None):
    """Per-player play-type PPP, league-percentiled vs the visible pool
    (vis None = whole gender pool, for admin)."""
    return PT.player_named_playtype_percentiles(
        gender=g, game_ids=(list(vis) if vis else None))


@st.cache_data(ttl=600, show_spinner=False)
def _role_splits(g, vis=None):
    """Per-player screen-action handler/roller splits, read-filtered to the
    viewer's visible games (vis None = whole gender pool, for admin)."""
    gids = list(vis) if vis else PT._tracked_game_ids(g)
    return PT.player_role_splits(game_ids=gids) if gids else {}


@st.cache_data(ttl=600, show_spinner=False)
def _set_profiles(g, vis=None):
    """Per-player set-call shot profiles, read-filtered to the viewer's visible
    games (vis None = whole gender pool, for admin)."""
    gids = list(vis) if vis else PT._tracked_game_ids(g)
    return PT.player_playtype_shot_profiles(game_ids=gids) if gids else {}


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


# ── PAST season = self-contained OPEN archive ────────────────────────────────
# The whole page reuses the existing `vis` (visible-game-ids) plumbing: the
# archive's game pool (seasons.game_pool) becomes the read-filter, so every
# stat / rating / chart is computed over exactly that season, ranked vs that
# season's field — and the Paid/Co-op gate opens (founder rule: anyone may read
# a past season at full depth; only the CURRENT season is the paid edge).
if not _is_cur_season:
    _arch_pool = SEAS.game_pool(season_pick, gender=gender, tracked_only=True)
    if not _arch_pool:
        empty_state(f"No tracked games in {season_pick} for this league",
                    "This archived season has no play-by-play games — retro-track "
                    "one in the Game Tracker (pick the season in its picker) and "
                    "its players will show up here.")
        st.stop()
    _PAID = True                                   # open archive, full depth
    _vis_key = tuple(sorted(_arch_pool))
    table = _stat_table(gender, min_games, _vis_key)
    if not table:
        empty_state(f"No players clear the games filter in {season_pick}",
                    "Lower the minimum-games slider — the archive pool is small.")
        st.stop()
else:
    table = _stat_table(gender, min_games)
    if not table:
        empty_state("No eligible players yet",
                    "No players clear this league / games filter yet. Track some "
                    "games in the Game Tracker and they'll show up here.",
                    cta="Open the Game Tracker", page="pages/2_Game_Tracker.py")
        st.stop()

    # AXIS-2 read-filter: a Paid + League-wide (Co-op) viewer may aggregate ONLY the
    # tracked games they're entitled to (own ∪ pooled). A non-pooled Solo team's
    # tracked depth must never surface on this whole-league page. Mirrors
    # pages/10_Data_Explorer.py. `_vis_key` (None = admin/unrestricted, else a tuple)
    # is threaded into every cross-team builder below.
    _vis_key = None
    if _PAID:
        _vis = ENT.visible_tracked_game_ids(_ident)    # None = admin (unrestricted)
        if _vis is not None:
            if _vis:                                   # non-empty visible set → scope
                _vis_key = tuple(sorted(_vis))
                _ftab = _stat_table(gender, min_games, _vis_key)
                if _ftab:
                    table = _ftab                      # tracked depth → visible set only
                else:
                    _PAID = False                      # league-wide but nothing matched →
                    _vis_key = None                    # box-only display
            else:
                # league-wide but ZERO visible tracked games → box-only. CRITICAL: never
                # pass an empty filter to _stat_table — _game_filter treats empty as the
                # whole sample, which would re-leak the full corpus.
                _PAID = False
                _vis_key = None
    # Free / Solo-paid keep the unfiltered table — box columns are public league-wide;
    # their tracked columns are gated off at display by _PAID, so _vis_key stays None.

# Archive key for the fetchers that were historically UNSCOPED (full-sample) on
# the current season — game logs, located shots, fouls, edge boards. None on the
# current season keeps them byte-identical; a past season passes its pool.
_arch_key = None if _is_cur_season else _vis_key

rows = sorted(table.values(), key=lambda r: (r["Rank"] or 1e9))
by_pid = table

# live league chips (futuristic stat-chip strip under the hero) — the OVR chip
# is event-derived, so it only shows for Paid viewers.
_ppg_lead = _leaders(rows, "PPG")[0]
_ovr_lead = _leaders(rows, "OVERALL")[0]
_teams_n = len({r["team_id"] for r in rows})
_ovr_chip = (f"<span class='stat-chip'>OVR <b>{_ovr_lead['OVERALL']:.1f}</b> · "
             f"{_ovr_lead['name']}</span>"
             if _PAID and _ovr_lead["OVERALL"] is not None else "")
st.markdown(
    "<div class='form-strip' style='margin:-6px 0 12px'>"
    f"<span class='stat-chip'><b>{len(rows)}</b> players</span>"
    f"<span class='stat-chip'><b>{_teams_n}</b> teams</span>"
    f"<span class='stat-chip'>PPG <b>{_ppg_lead['PPG']:.1f}</b> · {_ppg_lead['name']}</span>"
    f"{_ovr_chip}"
    "</div>", unsafe_allow_html=True)

# per-player zone splits + guarded/open (shared by Shot Lab, Compare, Profile),
# read-filtered to the viewer's visible games.
zsplits, zguard, hsplits = _zone_tables(_vis_key)


# ── full-pool data for the Lab tab (badges/archetypes/stabilized/matchups all
#    run on every qualified player, not the slider-filtered set; cached so they
#    don't recompute on the main page's interactions) ──────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def _table_full(g, vis=None):
    return PR.player_stat_table(gender=g, min_games=1,
                                game_ids=(list(vis) if vis else None))


@st.cache_data(ttl=600, show_spinner=False)
def _pgb(vis=None):
    """Every player's per-game boxes over tracked games (keyed by pid → gid).
    `vis` scopes to a season's pool (archive views); None = current default."""
    return S.player_game_boxes(game_ids=(list(vis) if vis else None))


@st.cache_data(ttl=600, show_spinner=False)
def _player_located(pid, vis=None):
    """Tap-captured shot locations for one player (cached so re-selecting / other
    widgets don't recompute). `vis` scopes to a season's pool (archive views)."""
    return S.located_shots(player_id=pid,
                           game_ids=(list(vis) if vis else None))


@st.cache_data(ttl=600, show_spinner=False)
def _foulft(vis=None):
    """Foul & free-throw detail per player. `vis` scopes to a season's pool."""
    return FL.player_foul_ft(game_ids=(list(vis) if vis else None))


@st.cache_data(ttl=600, show_spinner=False)
def _player_card(pid, g, vis=None):
    """Printable HTML player report card (cached per player/gender/visible-set)."""
    return RP.player_card_html(pid, gender=g, table=_table_full(g, vis))


@st.cache_data(ttl=600, show_spinner=False)
def _combined(pid):
    """Combined counting line over tracked + entered games (None if no entered).
    Current-season only — hand-entered boxes aren't season-stamped, so an archive
    view skips this merge (the caller gates on _is_cur_season)."""
    return MB.combined_player_line(pid, tracked_boxes=_pgb())


@st.cache_data(ttl=600, show_spinner=False)
def _lab_badges(g, vis=None):
    return BG.award_badges(_table_full(g, vis))


@st.cache_data(ttl=600, show_spinner=False)
def _lab_clusters(g, vis=None):
    return ARC.cluster_players(_table_full(g, vis))


@st.cache_data(ttl=600, show_spinner=False)
def _lab_edge(g, vis=None, season="Current"):
    """League-wide player-edge leaderboards (shared with the Rankings League Lab).
    `vis`/`season` scope the boards to an archived season's pool."""
    return PE.edge_boards(gender=g, game_ids=(list(vis) if vis else None),
                          season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _lab_stab(g, vis=None):
    return SH.stabilize_table(_table_full(g, vis))


@st.cache_data(ttl=600, show_spinner=False)
def _lab_names(g):
    return MX.player_names(gender=g)


(tab_lead, tab_rate, tab_impact, tab_shot, tab_cmp, tab_prof, tab_plab,
 tab_gloss) = st.tabs(
    ["Leaders", "Ratings", "Impact & Splits", "Shot Lab",
     "Compare", "Player Profile", "Lab", "Glossary"])


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

    # ── Overall leader hero banner (event-derived → Paid) ─────────────────────
    if _PAID:
        hue, tier = _tier(ovr_lead["OVERALL"])
        st.markdown(
            f"<div style='background:linear-gradient(135deg,#1a0d2e 0%,#0d1117 100%);"
            f"border:2px solid {hue};border-radius:16px;padding:20px 26px;"
            f"margin-bottom:16px;display:flex;align-items:center;gap:22px'>"
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
    if _PAID:
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
    if _PAID:
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
        if _PAID:
            st.markdown("**Top rated** — OVERALL")
            ol = _leaders(rows, "OVERALL", n=10)
            st.plotly_chart(_leader_bar(ol, "OVERALL", "f1", color="#56d4dd",
                                        height=360),
                            width="stretch", key="ov_ovr")

    # ── Offense vs defense map (OFFENSE/DEFENSE ratings → Paid) ────────────────
    if _PAID:
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
                marker=dict(size=10, color=ovr, colorscale=HEAT,
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
        # ── how the top scorers get their points (per game) — box, Free ──────
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
        # ── distribution of OVERALL ratings (event-derived → Paid) ───────────
        if _PAID:
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

    # ── Usage vs efficiency (USG% → Paid) ─────────────────────────────────────
    if _PAID:
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
                            colorscale=HEAT, showscale=True,
                            colorbar=dict(title="OVR"),
                            line=dict(width=1, color="#30363d"))))
            ufig.update_xaxes(title="Usage % (share of team possessions) →")
            ufig.update_yaxes(title="True shooting % →")
            _style(ufig, 420)
            st.plotly_chart(ufig, width="stretch", key="ov_usage")
            st.caption("Bubble size = points/game. Top-right = high-volume *and* "
                       "efficient — the offensive engines.")

    # ── League fingerprints: percentile heatmap + parallel coordinates ────────
    #    Includes event stats (USG%/VERSATILITY) + parallel coords ride the
    #    category ratings → Paid.
    if _PAID:
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
                textfont=dict(size=9), colorscale=HEAT, zmin=0, zmax=100,
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
                color="OVERALL", color_continuous_scale=HEAT,
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
        "GS/G": r["GS/G"], "VPS": r["VPS"],
    } for r in rows]).sort_values("Rank")
    if not _PAID:
        # Free tier: drop event-derived columns (display label → canonical key)
        # before showing/exporting; "Rank" rides on OVERALL so it goes too.
        _disp2canon = {"OVR": "OVERALL", "VERS": "VERSATILITY"}
        _drop = [c for c in full.columns
                 if _disp2canon.get(c, c) in PR.EVENT_DERIVED_STATS]
        full = full.drop(columns=_drop)
    _grid(full, "pl_full", height=560)
    # ── player quick view (Tier 2 item 13): the full profile card in a modal,
    #    no tab switch — pick a player, hit the button. Shares the Profile
    #    tab's ctx builder (helpers/dashboard/player_card.build_card_ctx).
    _qv_order = sorted(by_pid, key=lambda p: (by_pid[p]["Rank"] or 1e9))
    if st.session_state.get("pl_qv_pick") not in [None] + _qv_order:
        st.session_state.pop("pl_qv_pick", None)   # pool changed (league/season)
    _qv1, _qv2 = st.columns([3, 1])
    _qv_pid = _qv1.selectbox(
        "Quick view", [None] + _qv_order,
        format_func=lambda p: "Pick a player…" if p is None else (
            f"#{by_pid[p]['Rank']}  {by_pid[p]['name']}  ·  {by_pid[p]['team']}"),
        key="pl_qv_pick", label_visibility="collapsed")
    if _qv2.button("Quick view", key="pl_qv_btn", width="stretch",
                   disabled=_qv_pid is None):
        from helpers.dashboard.player_card import quick_view
        quick_view(_qv_pid, gender, season=season_pick, season_gp=_arch_key,
                   P=by_pid[_qv_pid], rows=rows, paid=_PAID, accent=ACCENT,
                   zsplits=zsplits, zguard=zguard, hsplits=hsplits,
                   vis=_vis_key)
    st.download_button("Full stats (CSV)", full.to_csv(index=False),
                       file_name=f"players_{gender}.csv", mime="text/csv",
                       key="dl_full")
    st.caption("Sort or filter any column in-grid (click a header for filters). "
               "Every column defined in the Glossary tab. The OVERALL bar view "
               "lives in the Ratings tab.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — RATINGS
# ══════════════════════════════════════════════════════════════════════════════
with tab_rate:
    if not _PAID:
        st.info(_LOCK)
    else:
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

        # ── Who leads each rating ─────────────────────────────────────────────
        st.markdown("<div class='pl-hdr'>Who leads each rating</div>",
                    unsafe_allow_html=True)
        lead_cols = st.columns(len(rcols))
        for col, key in zip(lead_cols, rcols):
            ld = _leaders(rows, key, n=1)
            if ld:
                col.markdown(_glass(key, f"{ld[0][key]:.1f}", ld[0]["name"]),
                             unsafe_allow_html=True)

        # ── Best per class (fragment — the rating picker reruns only this) ────
        @st.fragment
        def _fx_rate_best():
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
                # mini banner rows — the player-card grammar in one line each:
                # rank chip · name · team/class · rating track + value
                _rows_html = ""
                for i, r in enumerate(top, 1):
                    hue, _t = _tier(r[pick_rate])
                    v = max(0.0, min(100.0, float(r[pick_rate])))
                    _rows_html += (
                        f"<div style='display:flex;align-items:center;gap:10px;"
                        f"background:#0d1117;border:1px solid #21262d;"
                        f"border-radius:10px;padding:6px 10px;margin-bottom:5px'>"
                        f"<div style='background:{hue}18;border:1px solid {hue}55;"
                        f"border-radius:8px;min-width:30px;text-align:center;"
                        f"font-size:13px;font-weight:800;color:{hue};"
                        f"padding:2px 0'>{i}</div>"
                        f"<div style='flex:1;min-width:0'>"
                        f"<div style='font-size:13px;font-weight:700;color:#f0f6fc;"
                        f"white-space:nowrap;overflow:hidden;"
                        f"text-overflow:ellipsis'>{r['name']}</div>"
                        f"<div style='font-size:10px;color:#8b949e'>"
                        f"{_team_short(r['team'])} · {r['class']}</div></div>"
                        f"<div style='flex:1;position:relative;height:7px;"
                        f"border-radius:4px;background:#161b22'>"
                        f"<div style='position:absolute;height:7px;"
                        f"border-radius:4px;width:{v}%;background:{hue}'></div></div>"
                        f"<div style='width:38px;text-align:right;font-size:14px;"
                        f"font-weight:800;color:{hue}'>{r[pick_rate]:.1f}</div>"
                        f"</div>")
                st.markdown(_rows_html, unsafe_allow_html=True)
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

        _fx_rate_best()


# ══════════════════════════════════════════════════════════════════════════════
#  BEST FIVE — category leaders (appends into the Leaders tab)
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _fx_best_five():
    st.markdown("<div class='pl-hdr'>Best Five — category leaders</div>",
                unsafe_allow_html=True)
    st.caption("League leaders — the top five players in **every** stat we track, "
               "regardless of team or class. Rate stats require a minimum volume "
               "so a single lucky make can't top the list. Pick a category to "
               "see its leaderboards.")

    _groups = _visible_groups()
    group_names = [g for g, _ in _groups]
    group_name = st.pills("Stat group", group_names, default=group_names[0],
                          key="best_group")
    if not group_name:                       # pills can be deselected
        st.caption("Pick a stat group to see its leaders.")
        return
    stats = dict(_groups)[group_name]
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


with tab_lead:
    _fx_best_five()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — SHOT LAB  (court charts, zone efficiency, shot-making)
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _fx_shot():
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
        st.caption("Bubble size = attempts · ≥45% · 30–44% · <30% · "
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

    pl_shots = _player_located(pl_pid, _arch_key)
    ec1, ec2 = st.columns([3, 2])
    with ec1:
        # Unified shot surface: dots / points-over-expected heat / zone fallback.
        if not _shot_panel(pl_shots, zone_data=pl_zone, model=_shot_model(_vis_key),
                           key="lab_player", title=PL["name"]):
            empty_state("No located shots yet",
                        "Tap shots in the Game Tracker to build this player's "
                        "shot map.")
        if pl_shots:
            _ls = S.shot_location_summary(pl_shots)
            if _ls:
                def _segc(lbl, n, fg):
                    return f"{lbl} {n}" + (f" ({fg*100:.0f}%)" if fg is not None else "")
                st.caption(
                    f"Avg distance **{_ls['avg_dist']:.1f} ft** · "
                    + _segc("Rim", _ls["rim_n"], _ls["rim_fg"]) + " · "
                    + _segc("Mid", _ls["mid_n"], _ls["mid_fg"]) + " · "
                    + _segc("Three", _ls["three_n"], _ls["three_fg"]))
            _dbl = S.distance_buckets(pl_shots)
            if _dbl:
                st.caption("By length — " + S.distance_buckets_caption(_dbl))
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
        hb = hsplits.get(pl_pid, {})
        if hb and (hb["dominant"]["all"]["FGA"] or hb["weak"]["all"]["FGA"]):
            st.caption("**Hand side** — dominant vs weak half (dead-center ignored)")
            dom, wk = hb["dominant"]["all"], hb["weak"]["all"]
            hh = st.columns(2)
            for col, lbl, c in ((hh[0], "Dominant FG%", dom), (hh[1], "Weak FG%", wk)):
                col.metric(lbl, f"{c['pct']*100:.0f}%" if c["FGA"] else "—",
                           help=f"{c['FGM']}/{c['FGA']} FGA")
        # ── scout cues: the new reads (shot making, space dependence, off-hand) ──
        _cues = []
        _pps, _xpps = PL.get("PPS"), PL.get("xPPS")
        if _pps is not None and _xpps is not None and (PL.get("FGA") or 0) >= 12:
            _poe = _pps - _xpps
            _cues.append(("Over expected", f"{_poe:+.2f}", "pts/shot vs look quality",
                          "#3fb950" if _poe >= 0 else "#e74c3c"))
        if gd:
            _g, _o = gd["guarded"], gd["open"]
            if _g["FGA"] >= 5 and _o["FGA"] >= 5:
                _cliff = (_o["pct"] - _g["pct"]) * 100
                _cues.append(("Space dependence", f"{_cliff:+.0f}",
                              "needs space" if _cliff > 8 else
                              "contest-proof" if _cliff < -2 else "even",
                              "#e74c3c" if _cliff > 8 else
                              "#3fb950" if _cliff < -2 else "#8b949e"))
        if hb:
            _d, _w = hb["dominant"]["all"], hb["weak"]["all"]
            if _d["FGA"] >= 6 and _w["FGA"] >= 6:
                _gap = (_d["pct"] - _w["pct"]) * 100
                if _gap > 0:
                    _cues.append(("Force off-hand", f"+{_gap:.0f}",
                                  "gap to weak side", "#f0a500"))
        if _cues:
            st.caption("**Scout cues** — what the tracked splits say")
            _cc = st.columns(len(_cues))
            for _col, (_lbl, _val, _sub, _c) in zip(_cc, _cues):
                _col.markdown(
                    f"<div class='mini-tile'><div class='mini-lbl'>{_lbl}</div>"
                    f"<div class='mini-val' style='color:{_c}'>{_val}</div>"
                    f"<div class='mini-sub'>{_sub}</div></div>",
                    unsafe_allow_html=True)
    st.markdown("**Hot zones**")
    if pl_zone:
        _hot_zones(pl_zone)
    else:
        st.caption("No zone data for this player.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — IMPACT & SPLITS  (rebuilt-engine dimensions: RAPM impact, defense /
#  rebounding sub-ratings, playmaking depth, tracked-vs-box confidence)
# ══════════════════════════════════════════════════════════════════════════════
with tab_impact:
    import helpers.advanced_ratings as ADV
    ADV.leaderboard(rows, _PAID, key="pl")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — COMPARE
# ══════════════════════════════════════════════════════════════════════════════
with tab_shot:
    if not _PAID:
        st.info(_LOCK)
    else:
        _fx_shot()


@st.fragment
def _fx_cmp():
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
            # OVERALL / Rank are event-derived → Paid only.
            _ovr_html = (
                f"<div style='font-size:42px;font-weight:900;color:{clr};"
                f"line-height:1.2'>{P['OVERALL']:.0f}</div>"
                f"<div style='font-size:11px;color:#8b949e'>OVERALL</div>"
                if _PAID and P["OVERALL"] is not None else "")
            _rank_html = (f" · #{P['Rank']}"
                          if _PAID and P["Rank"] is not None else "")
            col.markdown(
                f"<div style='text-align:center'>"
                f"<div style='font-size:17px;font-weight:700;color:#c9d1d9'>"
                f"{P['name']}</div>"
                f"<div style='font-size:12px;color:#8b949e'>{P['team']} · "
                f"{P['class']}{_rank_html}</div>"
                f"{_ovr_html}</div>",
                unsafe_allow_html=True)

        # radar (RATING_COLS → Paid)
        if _PAID:
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
        else:
            st.caption("Ratings radar is a Paid feature.")

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

        # shot-attempt profile donuts (shot location/charts → Paid)
        if _PAID:
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
                p_shots = _player_located(p_pid, _arch_key)
                with col:
                    # Shared shot surface: dots / points-over-expected heat /
                    # zone fallback — same POE "Heat vs xPts" toggle the single-
                    # player shot explorer has, now on the head-to-head view.
                    if not _shot_panel(
                            p_shots, zone_data=zsplits.get(p_pid, {}),
                            model=_shot_model(_vis_key), key=f"cmp_court_{sfx}",
                            title=P["name"], height=380):
                        st.caption(f"{P['name']}: no shot locations or zones "
                                   "logged yet.")

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
        # Free tier: keep box percentiles only (drop event-derived rows).
        if not _PAID:
            PCT_STATS = [s for s in PCT_STATS
                         if s[0] not in PR.EVENT_DERIVED_STATS]
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
        # Free tier: keep the box stat-delta comparison only.
        if not _PAID:
            CMP_STATS = [s for s in CMP_STATS
                         if s[0] not in PR.EVENT_DERIVED_STATS]
        # display labels from STAT_GROUPS so raw keys like "PTSsd" read nicely
        _stat_lbl = {k: lbl for _, _grp in STAT_GROUPS for k, lbl, *_rest in _grp}
        cmp_rows = []
        for key, fmt, higher in CMP_STATS:
            va, vb = A.get(key), B.get(key)
            edge = ""
            if va is not None and vb is not None and va != vb:
                a_better = (va > vb) if higher else (va < vb)
                edge = "◀ A" if a_better else "B ▶"
            cmp_rows.append({"Stat": _stat_lbl.get(key, key),
                             A["name"]: _fmt(va, fmt),
                             "Edge": edge, B["name"]: _fmt(vb, fmt)})
        st.dataframe(pd.DataFrame(cmp_rows), hide_index=True,
                     width="stretch",
                     height=min(800, 60 + 35 * len(cmp_rows)))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — PLAYER PROFILE
# ══════════════════════════════════════════════════════════════════════════════
with tab_cmp:
    _fx_cmp()


@st.fragment
def _fx_prof():
    order = sorted(rows, key=lambda r: (r["Rank"] or 1e9))
    labels = [f"#{r['Rank']}  {r['name']}  ·  {r['team']}" for r in order]
    # Deep-link preselect: a ?player=<id> link (from a landing/search leaderboard)
    # opens this profile already scoped to that player. Applied once per distinct
    # id so the user can still change the picker afterward; ids not in the current
    # gender pool fall through to the default.
    _qp = st.query_params.get("player")
    if _qp and st.session_state.get("_prof_deeplink") != _qp:
        _idx = next(
            (i for i, r in enumerate(order)
             if str(next((k for k, v in by_pid.items() if v is r), "")) == str(_qp)),
            None)
        if _idx is not None:
            st.session_state["prof_pick"] = _idx
        st.session_state["_prof_deeplink"] = _qp
    # Command-palette handoff (helpers/ui._palette_dialog): a player id seeded
    # from anywhere in the app — same mapping as the ?player= deep-link, popped
    # so it fires once and the picker stays free afterward.
    _pp = st.session_state.pop("_palette_player", None)
    if _pp is not None:
        _idx = next((i for i, r in enumerate(order)
                     if by_pid.get(_pp) is r), None)
        if _idx is not None:
            st.session_state["prof_pick"] = _idx
    # a stale/seeded pick outside the current pool would crash the selectbox
    if not (0 <= st.session_state.get("prof_pick", 0) < len(order)):
        st.session_state.pop("prof_pick", None)
    pick = st.selectbox("Player", range(len(order)),
                        format_func=lambda i: labels[i], key="prof_pick")
    P = order[pick]
    pid = next(k for k, v in by_pid.items() if v is P)
    # The downloadable card bakes in paid tracked depth (ratings, USG%, percentile
    # ranks, shot chart) — gate the export like the on-screen card. Free viewers get
    # an upsell instead of a card that bypasses the tier via a file.
    from helpers.ui import pdf_or_html_download
    if _PAID:
        pdf_or_html_download(
            "Player card", _player_card(pid, gender, _vis_key),
            f"card_{P['name']}".replace(" ", "_"),
            key="prof_card_dl")
    else:
        st.caption("🔒 Download the full player card (ratings, usage, shot chart) — "
                   "a **Paid** feature. Upgrade to unlock.")

    # combined (tracked + hand-entered) is current-season only — entered boxes
    # aren't season-stamped, so an archive view skips the merge.
    _comb = _combined(pid) if _is_cur_season else None
    if _comb and _comb["manual_gp"]:
        st.markdown("<div class='pl-hdr'>Combined — incl. entered games</div>",
                    unsafe_allow_html=True)
        _cm = st.columns(6)
        _cm[0].metric("Games", _comb["gp"],
                      f"{_comb['tracked_gp']} tracked + {_comb['manual_gp']} entered",
                      delta_color="off")
        _cm[1].metric("PPG", f"{_comb['PPG']:.1f}")
        _cm[2].metric("RPG", f"{_comb['RPG']:.1f}")
        _cm[3].metric("APG", f"{_comb['APG']:.1f}")
        _cm[4].metric("FG%", f"{_comb['FG%']:.0f}%")
        _cm[5].metric("3P%", f"{_comb['3P%']:.0f}%")
        st.caption("Counting averages over tracked **and** hand-entered box scores. "
                   "The ratings and advanced stats below use tracked games only "
                   "(entered games have no event detail).")

    from helpers.dashboard.player_card import render_card, build_card_ctx
    render_card(build_card_ctx(
        pid, gender, season=season_pick, season_gp=_arch_key,
        P=P, rows=rows, paid=_PAID, accent=ACCENT,
        zsplits=zsplits, zguard=zguard, hsplits=hsplits, vis=_vis_key))


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — LAB  (badges · archetypes · stabilized stats · defensive matchups)
# ══════════════════════════════════════════════════════════════════════════════
with tab_prof:
    _fx_prof()


@st.fragment
def _fx_plab():
    st.caption("The next-gen player layer — NBA-2K-style badges, data-driven "
               "archetypes + a 'plays-like' similarity engine, empirical-Bayes "
               "stabilized stats for the small sample, and who-guarded-whom "
               "matchup intelligence. Computed over the full pool (min 1 game).")
    _TIER_COLOR = {"Gold": "#f0c000", "Silver": "#c0c8d0", "Bronze": "#cd7f32"}
    ltab = _table_full(gender, _vis_key)
    if not ltab:
        empty_state("No player data yet",
                    "No tracked-game player data for this league yet — track a "
                    "game and the Lab lights up.")
    else:
        lbadges = _lab_badges(gender, _vis_key)
        lclusters = _lab_clusters(gender, _vis_key)
        lstab = _lab_stab(gender, _vis_key)
        lnames = _lab_names(gender)
        lab_pid_label = {pid: f"#{r['number']} {r['name']} · {r['team']}"
                         for pid, r in ltab.items()}
        lab_order = sorted(ltab, key=lambda p: -(ltab[p].get("OVERALL") or 0))

        sub_badge, sub_arch, sub_stab, sub_match, sub_edge = st.tabs(
            ["Badges", "Archetypes", "Stabilized", "Matchups", "Player edge"])

        # ── Badges ───────────────────────────────────────────────────────────
        with sub_badge:
            st.markdown("<div class='pl-hdr'>Badge leaders</div>",
                        unsafe_allow_html=True)
            bpts = {p: BG.badge_points(lbadges[p]) for p in ltab}
            lead = sorted([p for p in ltab if bpts[p] > 0],
                          key=lambda p: -bpts[p])[:15]
            if lead:
                # y label carries the team — adds the team name AND makes each row
                # unique, so players who share a name (common here) no longer land on
                # the same y category and stack into one bar.
                lfig = go.Figure(go.Bar(
                    x=[bpts[p] for p in lead][::-1],
                    y=[f"{ltab[p]['name']} · {_team_short(ltab[p]['team'])}"
                       for p in lead][::-1], orientation="h",
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
            # ── Badge archetypes — a transparent role straight from the badges ──
            st.markdown("<div class='pl-hdr'>Badge archetypes</div>",
                        unsafe_allow_html=True)
            st.caption("A role read straight from each player's **badges** — badge "
                       "points per category (Gold 5 · Silver 3 · Bronze 1) decide "
                       "the offense/defense tilt and the calling card. Every label "
                       "traces back to the badges earned, so it's fully explainable.")
            barch = {p: BG.badge_archetype(lbadges.get(p, [])) for p in ltab}
            from collections import Counter as _Counter
            bcnt = _Counter(v["archetype"] for v in barch.values())
            bord = [a for a, _ in bcnt.most_common()]
            bafig = go.Figure(go.Bar(
                x=[bcnt[a] for a in bord][::-1], y=bord[::-1], orientation="h",
                marker_color=ACCENT, marker_line_width=0,
                text=[bcnt[a] for a in bord][::-1], textposition="auto"))
            bafig.update_xaxes(title="Players")
            _style(bafig, max(240, 30 * len(bord)))
            st.plotly_chart(bafig, width="stretch", key="plab_badge_arch_dist")

            bap = st.selectbox("Player", lab_order,
                               format_func=lambda p: lab_pid_label[p],
                               key="plab_badge_arch_player")
            bav = barch[bap]
            drv = " · ".join(bav["drivers"]) if bav["drivers"] else "no badges yet"
            st.markdown(
                f"<div class='glass-tile'><b style='font-size:17px'>"
                f"{ltab[bap]['name']}</b> → <b style='color:{ACCENT};"
                f"font-size:17px'>{bav['archetype']}</b><br>"
                f"<span style='color:#8b949e;font-size:13px'>{bav['blurb']}</span>"
                f"<br><span style='font-size:12px'>Offense <b>{bav['off']}</b> · "
                f"Defense <b>{bav['def']}</b> · Two-way <b>{bav['two']}</b> badge "
                f"pts · drivers: {drv}</span></div>", unsafe_allow_html=True)
            st.divider()

            st.markdown("<div class='pl-hdr'>Data-driven archetypes (style clusters)"
                        "</div>", unsafe_allow_html=True)
            st.caption(f"The other lens — players grouped into {lclusters['k']} "
                       "style clusters by k-means on z-scored stats, each named from "
                       "its statistical signature. Style, not just badges.")
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
                    # name · team — bare names collide (jersey-number-as-name),
                    # and the coach wants to know WHOSE dot it is (STATUS 58)
                    text=[f"{ltab[p]['name']} · {_team_short(ltab[p]['team'])}"
                          for p in mem],
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
                roster = ", ".join(
                    f"{ltab[p]['name']} ({_team_short(ltab[p]['team'])})" for p in
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
                empty_state("No contested-shot data yet",
                            "Tag defenders on shots in the Game Tracker to "
                            "unlock matchup intelligence for this league.")
            else:
                # Sample filter — most defenders have contested only a shot or two,
                # which buries the real matchup signal (and reads as "1 shot faced
                # every time"). Gate every board below on a minimum, defaulting past
                # the one-shot noise. Reassigning gen_def flows the filter to the
                # difficulty chart, the on-ball table AND the who-guarded picker.
                _mx_max = int(max(v["FGA"] for v in gen_def.values()))
                _mx_min = (st.slider(
                    "Min contested shots", 1, _mx_max, min(3, _mx_max),
                    key="plab_match_min",
                    help="Hide defenders who contested fewer shots than this — "
                         "one- or two-shot samples are noise, not defense.")
                    if _mx_max >= 2 else 1)
                gen_def = {d: v for d, v in gen_def.items() if v["FGA"] >= _mx_min}
                if not gen_def:
                    st.caption(f"No defender has contested {_mx_min}+ shots yet — "
                               "lower the filter or tag more shots.")
                st.markdown("<div class='pl-hdr'>Matchup difficulty</div>",
                            unsafe_allow_html=True)
                st.caption("How good were the scorers each defender was assigned to "
                           "(attempt-weighted opponent OFFENSE rating). High = "
                           "guarded the other team's best.")
                drows = sorted([(d, diff[d]) for d in gen_def if d in diff],
                               key=lambda x: -x[1]["Difficulty100"])[:15]
                if drows:
                    # y label carries the team — adds the team name AND de-dupes
                    # shared player names so they don't stack onto one y row.
                    dfig = go.Figure(go.Bar(
                        x=[v["Difficulty100"] for _, v in drows][::-1],
                        y=[f"{lnames[d]['name']} · {_team_short(lnames[d]['team'])}"
                           for d, _ in drows][::-1],
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

                if defrows:
                    st.markdown("<div class='pl-hdr'>Who did they guard?</div>",
                                unsafe_allow_html=True)
                    dsel = st.selectbox(
                        "Defender", [d for d, _ in defrows],
                        format_func=lambda d: f"{lnames[d]['name']} · "
                                              f"{lnames[d]['team']}",
                        key="plab_match_defender")
                    rec = gen_def[dsel]
                    sh_rows = []
                    for sht, sv in sorted(rec["by_shooter"].items(),
                                          key=lambda x: -x[1]["FGA"]):
                        sh_rows.append(
                            {"Shooter": lnames.get(sht, {}).get("name", str(sht)),
                             "Team": lnames.get(sht, {}).get("team", ""),
                             "Shots": sv["FGA"], "Made": sv["FGM"],
                             "FG%": sv["FG%"], "Pts": sv["pts"]})
                    if sh_rows:
                        st.dataframe(pd.DataFrame(sh_rows), hide_index=True,
                                     width="stretch", key="plab_match_assignments")

        # ── Player edge — league-wide leaders in the tracked-edge reads ────────
        with sub_edge:
            st.markdown("<div class='pl-hdr'>Player edge — league leaders</div>",
                        unsafe_allow_html=True)
            st.caption("League-wide player leaders in the tracked-edge reads: shot-"
                       "making over expected, who to force off their hand, defensive "
                       "win value, clutch, self-creation, efficiency, disruption and "
                       "rim finishing. Same boards as Rankings → League Lab; each "
                       "gated by sample.")
            _render_edge(_lab_edge(gender, _arch_key, season_pick),
                         key_prefix="plab_edge")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7 — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_plab:
    if not _PAID:
        st.info("🔒 The Lab — badges, archetypes, stabilized stats and matchup "
                "intelligence — is a **Paid** feature. Upgrade to unlock.")
    else:
        _fx_plab()


with tab_gloss:
    glossary_tab("pl_gloss")
