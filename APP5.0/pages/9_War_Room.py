"""
9_War_Room.py — the decision lab: lineups, matchups, season sims and brackets.

The spine follows the coach's decisions in order:
  • Lineups    — build a five (Creator), optimize the rotation's minutes
                 (the full lab from the Team Dashboard's light Projection tab),
                 and COMPARE candidate fives side by side — the give and take
                 each one offers. One engine (helpers.lineup_projection) under
                 every lineup number here AND on the Team Dashboard.
  • Matchup    — predict any two teams (score, win prob, line-by-line margin)
                 plus the full simulated margin distribution.
  • Season sim — replay every finished game N times → expected wins + luck.
  • Bracket    — seed a single-elim field by rating → championship odds.
  • Defensive assignments / Analyze / Glossary — prep + playground.

Display + controls only; simulation and projection live in Streamlit-free
engines (helpers/simulation.py, helpers/lineup_projection.py).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import helpers.ui as _uimod  # theme tokens read at call time
from helpers.ui import (page_chrome, style_fig as _style, empty_state, team_color,
                        chart as _chart, seg as _seg, engine_status as _eng,
                        AWAY, GOOD, BAD, HEAT, gender_radio, gender_label)
from helpers.cards import bar_h, team_short, style_df as _style_df, \
    round_df as _round_df
from helpers.glossary import glossary_tab
import helpers.team_ratings as TR
import helpers.matchup_sheet as MS
import helpers.predictor as PRED
import helpers.backtest as BT
import helpers.simulation as SIM
import helpers.player_ratings as PR
import helpers.lineups as LU
import helpers.lineup_projection as LP
import helpers.dashboard.projection_tab as DPROJ
import helpers.team_analytics as TA
import helpers.spacing as SPACE
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.seasons as SEAS
from database.db import query

_cfg, ACCENT = page_chrome("War Room")


# ── per-coach save/load blobs (Tier 3 item 23) ────────────────────────────────
# ONE compact USER_SCOPED JSON blob per concern (the insights_seen pattern):
# wr_saved_lineups = {name: {team_id, gender, season, pids, saved}}
# wr_bracket_seeds = {name: {gender, size, mode, field|seeds, saved}}
# Caps keep the app_settings row small (DB = living archive, founder rule).
_WR_MAX_SAVED = 20


def _wr_blob(key):
    import json
    from helpers.settings_utils import get_setting
    try:
        b = json.loads(get_setting(key, "") or "{}")
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def _wr_blob_save(key, blob):
    import json
    from helpers.settings_utils import set_setting
    set_setting(key, json.dumps(blob, separators=(",", ":")))


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER + LEAGUE + PRECISION
# ══════════════════════════════════════════════════════════════════════════════
from helpers.ui import lab_hero as _lab_hero
from helpers.stats import player_label as _PLBL
# The deck states the MECHANIC, not the feature list, and that is deliberate.
# The old sub named the five surfaces ("build fives, optimize the rotation,
# project any matchup…"), which is what the page contains. What makes this page
# different from every other one in the app is that nothing on it is a report:
# every number here answers an input the coach chose, and changing the input
# re-runs it. An analyst arriving with KenPom and CTG in their head already
# knows what a matchup projection is; what they do not know, from a page named
# after a room, is that they are allowed to drive it.
_lab_hero("War Room — Lineups, Matchups & Sims",
          sub="Everything on this page is something you change and re-run: "
              "build a five, swap a defender, replay the season, project any "
              "matchup, or take the whole stat table apart yourself.")

cc = st.columns([2, 3])
gender = gender_radio(cc[0])
n = cc[1].select_slider(
    "Simulations per scenario", options=[5000, 20000, 50000], value=SIM.DEFAULT_N,
    key="wr_sims", format_func=lambda v: f"{v // 1000}k sims",
    help="More sims = smoother odds, slightly slower. 20k is plenty for HS fields.")

# Form weight — how much every prediction/sim/bracket-seed leans on recency-
# weighted CURRENT FORM vs the full-season résumé. 0% = season only (the classic
# ranking); higher chases who's hot right now. Blends the ratings dict once, up
# front, so the predictor + all sims inherit it for free.
_form_pct = cc[1].slider(
    "Form weight", 0, 100, 35, step=5, format="%d%%", key="wr_form",
    help="How much predictions & sims lean on recent form (recency-weighted) vs "
         "the full-season rating. 0% = season only. 35% = résumé leads, form is a "
         "real thumb on the scale — the recommended balance for short HS records.")
form_w = _form_pct / 100.0

# Season picker — run the War Room on a past/archived season (its ratings, its
# schedule, its players). Only appears once a season has been rolled over; the
# active season is the default so the page is byte-identical with no archive.
# A PAST season is an OPEN archive: the Paid / Co-op gates below open (founder
# rule — anyone may read past data at full depth), and every sim/projection is
# computed from that season's pool only.
_season_opts = SEAS.season_options()
if len(_season_opts) > 1:
    _slbl = cc[0].selectbox(
        "Season", [l for _v, l in _season_opts], key="wr_season",
        # War Room is a READ page, so it opens on the last season that actually
        # has finished games. Without this it defaulted to index 0 = the active
        # season, which right after a rollover is empty — every sim, projection
        # and lineup read rendered blank over a full database, which is exactly
        # the failure SEAS.default_read_season exists to prevent and which the
        # Team Dashboard already avoided.
        index=SEAS.default_read_season_index(_season_opts),
        help="Simulate with a past season's ratings and rosters — 'what were our "
             "title odds last year'. Past seasons are open to everyone.")
    season_pick = next(v for v, l in _season_opts if l == _slbl)
else:
    season_pick = SEAS.ACTIVE
_is_cur_season = SEAS.is_current(season_pick)
_uimod.declare_scope(gender, season_pick)   # scope cache to this pool (batch #6a)

# Entitlement wrappers: identical to ENT on the current season; a PAST season is
# an open archive, so the per-team / per-game tracked checks answer True.
if _is_cur_season:
    _can_team = ENT.can_see_team_tracked
    _can_game = ENT.can_see_game_tracked
else:
    _can_team = lambda *_a, **_k: True
    _can_game = lambda *_a, **_k: True


# ── cached ratings + sims (keyed by hashable args only — never the dict) ────────
# `season` on each fetcher scopes to the page's selected season ('Current' =
# live default, byte-identical when no archive is picked).
@st.cache_data(ttl=600, show_spinner=False)
def _scored(g, season="Current", form_w=0.0):
    # form_w in [0,1] blends the season ratings toward recency-weighted form; 0.0
    # returns the pure season ratings unchanged (byte-identical to the old path).
    # THE single ratings dict the predictor + every sim below consume, so this one
    # blend factors current form into matchups, win-prob, season sims and brackets.
    return TR.blended_ratings(gender=g, season=season, form_weight=form_w)


@st.cache_data(ttl=600, show_spinner=False)
def _tracked(g, season="Current"):
    return TR.tracked_ratings(gender=g, season=season)


# ── back in time (helpers/backtest) ───────────────────────────────────────────
# Rankings' week picker is a pure table read — `rating_snapshots` stores a rank
# and a rating, which is everything a BOARD needs. A MATCHUP needs AdjNet,
# ClassAdj, xPPG, xoPPG and GP, none of which are in that table, so the
# predictor's version of the same idea has to RE-SOLVE the board over the games
# that existed on the date. That costs one solve (~0.2 s on the production
# book), which is why it is cached here rather than avoided.
@st.cache_data(ttl=600, show_spinner=False)
def _asof_days(g, season="Current"):
    """Every date this league actually played on, newest first.

    Game days, not the weekly `rating_snapshots` stride: the re-solve can stand
    on any date, and "the board the morning of the district final" is a date a
    coach can name, while "the Sunday before it" is not.
    """
    return sorted({x["day"] for x in BT.finished_games(g, season)}, reverse=True)


@st.cache_data(ttl=600, show_spinner=False)
def _asof_scored(g, day, season="Current", form_w=0.0):
    return BT.ratings_as_of(day, g, season, form_weight=form_w)


@st.cache_data(ttl=600, show_spinner=False)
def _asof_tracked(g, day, season="Current"):
    return BT.tracked_as_of(day, g, season)


@st.cache_data(ttl=1800, show_spinner=False)
def _backtest(g, season="Current", form_w=0.0):
    """One solve per game DATE across the season — ~20 s cold, cached for 30 min.
    Behind a button on purpose; nothing else on this page costs that much."""
    return BT.walk_forward(g, season, form_weight=form_w)


@st.cache_data(ttl=600, show_spinner=False)
def _war_map(g, season="Current"):
    """HoopWAR per player (wins vs replacement) — the lineup creator's value
    column. {} when RAPM/scores can't support it."""
    import helpers.hoopwar as HW
    try:
        _gids = (None if season in (None, "Current")
                 else SEAS.game_pool(season, gender=g, tracked_only=True))
        return HW.war_table(g, game_ids=_gids, season=season)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _sim_game(g, a, b, home, n, season="Current", form_w=0.0, asof=None):
    # `asof` runs the Monte-Carlo on the board as it stood that day. Without it
    # the sim would quietly keep using today's ratings while the verdict above it
    # showed January's — two different matchups on one screen, agreeing on
    # nothing, with no way for a coach to tell which number to believe.
    board = (_asof_scored(g, asof, season, form_w) if asof
             else _scored(g, season, form_w))
    return SIM.simulate_game(board, a, b, home=home, n=n)


@st.cache_data(ttl=600, show_spinner=False)
def _sim_season(g, n, season="Current", form_w=0.0):
    return SIM.simulate_season(_scored(g, season, form_w),
                               SIM.schedule_from_results(g, season=season), n=n)


@st.cache_data(ttl=600, show_spinner=False)
def _sim_bracket(g, field, n, reseed=True, size=None, season="Current", form_w=0.0):
    # bracket_tree returns BOTH the per-team odds (same shape simulate_tournament
    # gave) AND the render-ready probabilistic tree — one sim pass for both.
    # reseed=False → `field` is an explicit seed order (None = a bye slot).
    # form_w blends the seeding ratings toward current form (see _scored).
    return SIM.bracket_tree(_scored(g, season, form_w), list(field), n=n,
                            reseed=reseed, size=size)


@st.cache_data(ttl=600, show_spinner=False)
def _game_plan(g, a, b, avis=None, bvis=None):
    """Cross-team exploit matrix + defensive plan (Tier 2, ML_LAYER_ROADMAP):
    team `a`'s set-call efficiency × team `b`'s defensive vulnerability, plus the
    scheme to play on D against `b`. `avis`/`bvis` are each team's AXIS-2 visible
    game-id tuple (None = own/admin = full) so a non-pooled team's tendencies never
    leak. Cached on (gender, a, b, avis, bvis)."""
    import helpers.exploit as EX
    return EX.game_plan(a, b, gender=g, my_game_ids=avis, opp_game_ids=bvis)


@st.cache_data(ttl=600, show_spinner=False)
def _scheme_proj(g, a, b, avis=None, bvis=None, season="Current"):
    """Scheme-based (play_type-share) matchup projection — VERY experimental,
    gated to 150 tagged set calls per team. Possessions from the two teams'
    tracked pace when available. `avis`/`bvis` read-filter each team's leg. Cached
    on (gender, a, b, avis, bvis, season)."""
    import helpers.exploit as EX
    tr = _tracked(g, season)
    pa, pb = tr.get(a, {}).get("Pace"), tr.get(b, {}).get("Pace")
    poss = (pa + pb) / 2.0 if pa and pb else 68.0
    return EX.scheme_projection(a, b, gender=g, poss=poss,
                                a_game_ids=avis, b_game_ids=bvis)


def _vis_tuple(ident, team_id):
    """AXIS-2 read-filter for one team as a hashable cache key: None = own/admin
    (unrestricted), else the sorted tuple of that team's pooled (visible) games.
    A PAST season returns that team's tracked games of the season instead — the
    open archive's exact pool, so a projection never mixes in current games."""
    if not _is_cur_season:
        return tuple(sorted(r["id"] for r in query(
            "SELECT id FROM games WHERE tracked=1 AND season=? "
            "AND (team1_id=? OR team2_id=?)", (season_pick, team_id, team_id))))
    _v = ENT.team_visible_tracked_ids(ident, team_id)
    return None if _v is None else tuple(sorted(_v))


scored = _scored(gender, season_pick, form_w)
tracked = _tracked(gender, season_pick)


@st.cache_data(ttl=600, show_spinner=False)
def _wr_insight_feed(g, season="Current"):
    """League-wide auto-scout feed (helpers/team_insights) for the Matchup
    tells — cached once per (gender, season); the view looks both teams up.
    3-line surface cap (the TD Insights tab is the deep-dive home)."""
    import helpers.team_insights as TIN
    try:
        return TIN.team_insight_feed(gender=g, season=season, top=3)
    except Exception:
        return {}

if not scored:
    empty_state(
        "No rated teams yet" if _is_cur_season
        else f"No finished games in {season_pick} for this league",
        "Enter game results in the Input Hub and track a few games — the War Room "
        "simulates straight from the league ratings.",
        cta="Start in the Input Hub")
    st.stop()

# Tier gate: the War Room is a premium planning tool — Monte-Carlo matchups,
# season/bracket sims and the lineup creator. Plan-level entry (has_paid_plan);
# inside, the tracked-possession projection and lineup chemistry add per-team /
# pool checks (see below). A PAST season bypasses it — open archive, so anyone
# can replay history ("what were our title odds last year").
if not ENT.paid_or_open_archive(AUTH.current_user(), season_pick):
    empty_state(
        "The War Room is a Paid feature",
        "Monte-Carlo matchups, season and bracket simulations, and the lineup "
        "creator all unlock with a Paid plan. Upgrade to game-plan like the pros.",
        icon="🔒")
    st.stop()

name_of = {t: r["name"] for t, r in scored.items()}
class_of = {t: r.get("class_lbl", r["class"]) for t, r in scored.items()}
order = sorted(scored, key=lambda t: scored[t]["Rank"])


def _team_pair_colors(a, b):
    """Identity colours for two teams; fall back to accent/away if they collide."""
    ca, cb = team_color(name_of[a], a), team_color(name_of[b], b)
    return (ca, cb) if ca != cb else (ACCENT, AWAY)


def _round_labels(n_rounds):
    """Stage names for the bracket survival curve (named from the final inward)."""
    tail = ["Champion", "Final", "Semifinals", "Quarterfinals",
            "Round of 16", "Round of 32", "Round of 64"]
    out = []
    for k in range(1, n_rounds + 1):
        from_end = n_rounds - k          # 0 = champion
        out.append(tail[from_end] if from_end < len(tail) else f"Round {k}")
    return out


def _bracket_tree_html(res, short):
    """Probabilistic bracket tree — each slot shows its most-likely occupant and
    how often it reaches that slot, left→right to the champion (gold)."""
    cols, size, names = res["cols"], res["size"], res["names"]
    H = max(240, size * 34)     # column height so the rounds line up

    def _label(remaining):
        return {1: "Champion", 2: "Final", 4: "Semifinals",
                8: "Quarterfinals"}.get(remaining, f"Round of {remaining}")

    def _box(slot, champ=False):
        t = slot["team"]
        if t is None:
            return ("<div style='background:#0d1117;border:1px dashed #21262d;"
                    "border-radius:6px;padding:4px 7px;font-size:11px;"
                    "color:#484f58'>bye</div>")
        p, sd = slot["p"], slot.get("seed")
        pcol = _uimod.GOOD if p >= .6 else "#f0a500" if p >= .3 else "#8b949e"
        bd = "#f0a500" if champ else "#30363d"
        seedtag = f"<span style='color:#6e7681'>{sd}</span> " if sd else ""
        return (f"<div style='background:#0d1117;border:1px solid {bd};"
                f"border-radius:6px;padding:4px 7px;font-size:11px;display:flex;"
                f"justify-content:space-between;gap:6px'>"
                f"<span>{seedtag}<b style='color:#f0f6fc'>{short(names[t])}</b></span>"
                f"<span style='color:{pcol};font-weight:700'>{p*100:.0f}%</span></div>")

    colhtml = ""
    for col in cols:
        boxes = "".join(_box(s, champ=(len(col) == 1)) for s in col)
        colhtml += (
            f"<div style='display:flex;flex-direction:column;min-width:132px'>"
            f"<div style='font-size:10px;color:#8b949e;text-transform:uppercase;"
            f"letter-spacing:.05em;text-align:center;margin-bottom:6px'>"
            f"{_label(len(col))}</div>"
            f"<div style='display:flex;flex-direction:column;flex:1;"
            f"justify-content:space-around;height:{H}px;gap:5px'>{boxes}</div></div>")
    return (f"<div style='display:flex;gap:12px;overflow-x:auto;padding:4px 0'>"
            f"{colhtml}</div>")


@st.cache_data(ttl=600, show_spinner=False)
def _league_pool(season="Current"):
    """Every rated player league-wide for the cross-team lineup picker:
    pid, name, team(+id), class, gender, district + 0-100 ratings & per-game.
    `season` scopes each gender's pool (archive = that season's players)."""
    dist = {r["id"]: (r["district"] or "")
            for r in query("SELECT id, district FROM teams")}
    rows = []
    for _g in ("F", "M"):
        _gids = (None if season in (None, "Current")
                 else set(SEAS.game_pool(season, gender=_g, tracked_only=True)))
        for pid, r in PR.player_stat_table(gender=_g, min_games=1,
                                           game_ids=_gids).items():
            rows.append({
                "pid": pid, "name": r["name"], "team": r["team"],
                "team_id": r["team_id"], "class": r.get("class"), "gender": _g,
                "district": dist.get(r["team_id"], ""),
                "OVERALL": r.get("OVERALL"), "OFFENSE": r.get("OFFENSE"),
                "DEFENSE": r.get("DEFENSE"), "PLAYMAKING": r.get("PLAYMAKING"),
                "REBOUNDING": r.get("REBOUNDING"), "PPG": r.get("PPG"),
                "RPG": r.get("RPG"), "APG": r.get("APG")})
    return rows


@st.cache_data(ttl=600, show_spinner=False)
def _wl_table(g, season="Current"):
    _gids = (None if season in (None, "Current")
             else set(SEAS.game_pool(season, gender=g, tracked_only=True)))
    return PR.player_stat_table(gender=g, min_games=1, game_ids=_gids)


@st.cache_data(ttl=600, show_spinner=False)
def _wl_ctx(g, season="Current"):
    # current season keeps the engine's own defaults (byte-identical); an archive
    # passes the season-scoped ratings + table so the calibration is that year's.
    if season in (None, "Current"):
        return TA.lineup_engine_context(g)
    return TA.lineup_engine_context(g, tracked_ratings=_tracked(g, season),
                                    table=_wl_table(g, season))


@st.cache_data(ttl=600, show_spinner=False)
def _wl_player_spacing(g, season="Current"):
    """League per-player floor-spacing map for the 'Floor spacing' preset lens
    (empty until located-shot coverage is real)."""
    _gids = (None if season in (None, "Current")
             else SEAS.game_pool(season, gender=g, tracked_only=True))
    return SPACE.league_player_spacing(g, game_ids=_gids)


@st.cache_data(ttl=600, show_spinner=False)
def _lp_ctx(g, team_id, season="Current", vis=None):
    """lineup_projection context, cached per (team, season, visible games) — the
    ONE lineup engine every win-formula number on this page (and the Team
    Dashboard Projection tab) reads. `vis` = the viewer's visible-game tuple
    (None = own team / open archive = unrestricted)."""
    return LP.build_context(team_id, gender=g,
                            game_ids=(list(vis) if vis is not None else None),
                            season=season)


def _cmp_key(team_id):
    """Session key for the team's saved comparison fives (per season)."""
    return f"wr_cmp_{team_id}_{season_pick}"


def _add_cmp(team_id, five):
    """Save a five (pid tuple) for the Compare view; dedupes."""
    cur = st.session_state.setdefault(_cmp_key(team_id), [])
    if tuple(five) not in [tuple(x) for x in cur]:
        cur.append(tuple(five))


def _fmt_edge(e):
    """One give-or-take (LP.compare_lines row) as coach text: percentage points
    for rate stats, raw for PPP-scale stats."""
    d = e["diff"]
    if e["key"] in ("PPP", "oPPP"):
        return f"{d:+.2f} {e['label']}"
    return f"{d * 100:+.1f} {e['label']}"


@st.cache_data(ttl=600, show_spinner=False)
def _lineup_net(g, team_id, lineup, season="Current"):
    """NetRtg for one candidate five, cached on (gender, team, lineup tuple) —
    the bench-swap search tries ~50 lineups and must not recompute each rerun."""
    tbl = _wl_table(g, season)
    rows = [dict(r, _pid=pid) for pid, r in tbl.items() if r["team_id"] == team_id]
    return TA.lineup_prediction(rows, list(lineup), _wl_ctx(g, season),
                                team_id)["NetRtg"]


def _lineup_statline(pred, ctx, table):
    """Per-player PROJECTED box line for a five, sorted by projected points.

    PTS is lineup-aware — the unit's projected points-for (exp_pf, which drives the
    score line) split across the five by each player's offensive share, so the
    per-player points sum to the headline score and stacking scorers splits the
    ball (a genuine prediction, not the per-game average). REB/AST/STL/BLK/TOV are
    the player's per-game production pace-adjusted to the unit's pace (we don't
    model rebound/assist interaction, so these ride each player's baseline scaled
    for tempo). `table` = the full PR.player_stat_table for the five's gender. Also
    carries SC/G (shots created) and the defensive z as context columns."""
    pace = pred.get("pace") or 0
    exp_pf = pred.get("exp_pf")
    tracked = ctx.get("tracked", {}) or {}
    contrib = pred.get("contrib") or []
    tot_off = sum(c["off_pts100"] for c in contrib) or 0
    rows = []
    for c in contrib:
        fr = table.get(c["pid"], {})
        ppace = (tracked.get(fr.get("team_id"), {}) or {}).get("Pace") or pace
        f = (pace / ppace) if ppace else 1.0

        def _s(k, _f=f, _fr=fr):
            v = _fr.get(k)
            return round(v * _f, 1) if v is not None else None
        rows.append({
            "Player": c["name"], "Team": fr.get("team", ""),
            # calibrated points-for shared by offensive slice -> sums to exp_pf
            "PTS": (round(exp_pf * c["off_pts100"] / tot_off, 1)
                    if exp_pf is not None and tot_off else None),
            "REB": _s("RPG"), "AST": _s("APG"), "STL": _s("SPG"),
            "BLK": _s("BPG"), "TOV": _s("TPG"),
            "SC/G": _s("SC/G"), "DEF z": c["def_z"],
            # season value context (measured, not projected): wins vs
            # replacement + the measurables rating when recorded
            "WAR": (_war_map(gender, season_pick).get(c["pid"], {}) or {}).get("WAR"),
            "PHY": fr.get("PHYSICAL"),
        })
    return rows


def _render_proj_statline(pred, ctx, table, key):
    """Render the predicted stat line table + a unit-total row (shared by the One-
    team and Any-team lineup views)."""
    rows = _lineup_statline(pred, ctx, table)
    if not rows:
        return
    st.markdown("**Predicted stat line — this five**")
    _sum = lambda k: round(sum(r[k] or 0 for r in rows), 1)
    total = {"Player": "Unit total", "Team": "", "PTS": _sum("PTS"),
             "REB": _sum("REB"), "AST": _sum("AST"), "STL": _sum("STL"),
             "BLK": _sum("BLK"), "TOV": _sum("TOV"), "SC/G": _sum("SC/G"),
             "DEF z": None, "WAR": _sum("WAR"), "PHY": None}
    st.dataframe(_round_df(pd.DataFrame(rows + [total])), hide_index=True,
                 width="stretch", key=key)
    st.caption(
        "Projected per-game line for this unit. **PTS** is lineup-aware — each "
        "player's share of the five's offense at the projected pace, so stacking "
        "scorers splits the ball. REB/AST/STL/BLK/TOV are per-game production pace-"
        "adjusted to the unit (rebound/assist interaction isn't modelled). "
        "SC/G = shots created · DEF z = defensive value (0 = league average) · "
        "WAR = HoopWAR, season wins vs replacement (measured, not projected) · "
        "PHY = measurables rating when recorded.")


# Paid + Solo (not in the Coaches' Co-op) build their OWN team's lineups from
# their OWN tracked data. Scouting other teams — the matchup projection and the
# season/bracket sims, all league-wide aggregates — is Co-op only.
#
# THE GATE MAP, because the comment that stood here counted five views against a
# seven-view list and was stale rather than wrong. Audited 2026-09-13:
#
#   Lineups                 open to any Paid coach. `_wr_team_pick` narrows the
#                           team list to their own when not league-wide, so the
#                           view opens and the SCOPE is what the gate moves.
#   Glossary                open. Definitions are not data.
#   Matchup / Season sim /  hard-gated on `_wr_league_wide` below — the three the
#   Bracket                 old comment meant by "the other three".
#   Analyze                 gated INSIDE `helpers/dashboard/analyze.py:100`, and
#                           it DEGRADES rather than refusing: a solo coach gets
#                           the box-score columns and loses the tracked ones.
#                           That is why it carries no lock glyph — the door does
#                           open, onto a smaller room.
#   Defensive assignments   no VIEW-level gate, and that is the one finding the
#                           audit turned up. It gates per-opponent instead:
#                           `can_rate = _can_team(_id, opp)` inside
#                           `_render_planner`, so an un-entitled coach still
#                           opens the planner and assigns their own five, and
#                           the opponent's rated players are replaced by their
#                           own hand-entered Scout intel. Correct, and the
#                           better design — the view is a planning surface that
#                           works with no opponent data at all. Left as is.
_wr_ident = AUTH.current_user()
# a PAST season is an open archive → the co-op (league-wide) gate opens too
_wr_league_wide = True if not _is_cur_season else ENT.viewer_is_league_wide(_wr_ident)
# One ladder (entitlement.lock_reason), POOL scope. Only read when
# _wr_league_wide is False, which a past season already rules out.
_WR_LOCK = (ENT.lock_reason(_wr_ident, season=season_pick, scope="pool")
            or ENT.MSG_COOP_INVITE)


@st.cache_data(ttl=600, show_spinner=False)
def _wr_pool_size(season="Current"):
    """(teams, games) the co-op pool would open — the SIZE of what is behind the
    lock, which is the only part of the sell that is a fact rather than a claim.

    A coach deciding whether to share their season's tracking is pricing an
    exchange, and "scout every league-wide team" does not say whether that is
    two teams or twenty. Counted off `games.in_pool`, the same denormalised
    truth `entitlement.pooled_game_ids` reads, so this cannot drift from what
    the gate would actually hand over."""
    gids = ENT.pooled_game_ids(season)
    if not gids:
        return 0, 0
    marks = ",".join("?" * len(gids))
    rows = query(f"SELECT team1_id a, team2_id b FROM games WHERE id IN ({marks})",
                 tuple(sorted(gids)))
    teams = {r["a"] for r in rows} | {r["b"] for r in rows}
    return len(teams - {None}), len(gids)


# What each locked view actually is, in the two sentences a coach needs to price
# it: the read it produces, and a question they would genuinely ask it. Written
# as the thing behind the door, never as marketing — `MSG_COOP_INVITE` already
# carries the ask, and a second layer of persuasion over it reads as a pitch.
_WR_LOCK_SELL = {
    "Matchup": (
        "A projected score, a win probability and a **line-by-line margin "
        "breakdown** for any two teams in the league, plus the full simulated "
        "margin distribution — opponent-adjusted, with home court applied to "
        "the actual venue.",
        "“We are three points worse than them on paper. Where do the three "
        "points come from, and which of them can I coach?”"),
    "Season sim": (
        "Every finished game replayed thousands of times off the league "
        "ratings → expected wins, and the gap between those and the record "
        "you actually have.",
        "“Are we 14-6 because we are a 14-win team, or because we won four "
        "coin flips?”"),
    "Bracket": (
        "Seed a single-elimination field by rating and roll it out → "
        "round-by-round survival and championship odds for every team in it.",
        "“If we draw the 3-seed in the quarters, what are we actually "
        "playing for?”"),
}


def _wr_locked(view):
    """The co-op lock, rendered as the door it is instead of the refusal it was.

    This gate is the page's commercial job and it used to be one `st.info` line.
    Three things go on the screen instead, and the order is the argument: WHAT
    is behind it, a QUESTION it answers, and HOW BIG the pool it would draw on
    actually is — then the one action that opens it. Nothing here bypasses
    anything; the view below still does not run.
    """
    what, question = _WR_LOCK_SELL.get(view, ("", ""))
    st.markdown(f"<div class='lab-hdr'>🔒 {view}</div>", unsafe_allow_html=True)
    if what:
        st.markdown(what)
        st.markdown(f"<div style='color:var(--subtext);font-style:italic;"
                    f"margin:6px 0 10px'>{question}</div>",
                    unsafe_allow_html=True)
    _teams, _games = _wr_pool_size(season_pick)
    if _teams:
        st.markdown(
            f"<span class='stat-chip'>{_teams} teams in the pool</span>"
            f"<span class='stat-chip'>{_games} tracked games</span>",
            unsafe_allow_html=True)
    else:
        # An honest zero. Telling a coach they are missing out on an empty pool
        # is the fastest way to lose the next thing you tell them.
        st.caption("Nobody has shared tracked games in this season yet — you "
                   "would be first in, and the pool grows as coaches join.")
    st.info(_WR_LOCK)

# View switcher — seg + if-dispatch (the lazy-load contract): only the chosen
# view computes, where st.tabs ran EVERY body each rerun.
#
# THE ORDER IS THE ARGUMENT. Analyze — the self-serve playground that filters
# the full ~60-column player table, plots any stat against any other and
# correlates anything — shipped SIXTH of seven, behind two simulators. It is the
# one surface on this page that lets a reader ask a question nobody composed for
# them, which is the single thing a college-level analyst is looking for, and it
# was the hardest thing here to find. Defensive assignments follows it for the
# same reason from the other direction: who guarded whom is the read no
# competitor at this level can produce at all.
#
# LINEUPS STAYS THE DEFAULT, and that is a hard constraint, not a preference:
# Analyze is co-op-gated, and landing a Paid-but-solo coach on a page that opens
# into a degraded view is a worse first impression than any ordering buys back.
# Never default-land a gated view.
#
# Reordering is free at runtime — `_seg` dispatch is lazy, so Season sim and
# Bracket stay expensive and stay unevaluated until someone clicks them.
#
# THE VALUES DO NOT CHANGE. Only the ORDER of the list and the display labels
# (via format_func) move; every option string is byte-identical, so `wr_view`
# session state and every existing deep link resolve exactly as before. Changing
# an option VALUE here is the same class of failure as the st.tabs -> _seg
# conversion that silently broke routing into a section.
_WR_VIEWS = ["Lineups", "Analyze", "Defensive assignments", "Matchup",
             "Season sim", "Bracket", "Glossary"]
# Icons make the bar read as primary navigation rather than one more toggle —
# the Team Dashboard pattern at 6_Team_Dashboard.py:1794.
_WR_VIEW_ICONS = {"Lineups": "👥", "Analyze": "🔬",
                  "Defensive assignments": "🛡", "Matchup": "⚔",
                  "Season sim": "🎲", "Bracket": "🏆", "Glossary": "📖"}

# The three views a solo coach cannot open at all. Shown in the bar WITH a lock
# glyph rather than hidden: a door you can see is a sell, a door you cannot see
# is nothing. Analyze is deliberately NOT in this set — its gate degrades to the
# box-score columns instead of refusing, so a padlock on it would be a lie.
_WR_GATED = ("Matchup", "Season sim", "Bracket")


def _wr_view_label(v):
    icon = _WR_VIEW_ICONS.get(v, "")
    lock = " 🔒" if (v in _WR_GATED and not _wr_league_wide) else ""
    return f"{icon} {v}{lock}"


_wrview = _seg("View", _WR_VIEWS, default="Lineups", key="wr_view",
               format_func=_wr_view_label) or "Lineups"

# Team-identity chrome. Anchored to the coach's OWN team from their identity,
# not to whichever team the current view happens to have selected: the banner
# answers "whose app is this", and a bar that changed meaning as you switched
# from your lineups to an opponent's would answer a different question badly.
# render_for resolves ratings + the tracked_gate itself, and draws nothing when
# the viewer has no team (admins browsing, unassigned coaches).
if _wr_ident.get("team_id"):
    import helpers.dashboard.team_card as _WR_TCARD
    _WR_TCARD.render_for(_wr_ident["team_id"], gender, season_pick,
                         ident=_wr_ident)
# one stat key for the dense tables across the views (lineups / sims / boards)
from helpers.ui import glossary_key as _glossary_key
_glossary_key("ORtg", "DRtg", "NetRtg", "Pace", "PPP", "HoopWAR", "RAPM",
              "Unit Net", "Pair Net", "Exp. Wins", "Luck", "Title Odds")


def _wr_team_pick(key):
    """Team selector for the Lineups views: Solo coaches get their own team,
    League-wide / admin / open-archive viewers get every team with tracked data.

    Not every RATED team — a rated team with no tracked player behind it has
    nothing for these views to build, and ranking the list put every league-wide
    coach on the #1 team, which is one of them. Own team leads the list so the
    picker opens on it. See lineup_projection.pickable_teams.
    """
    _mine = _wr_ident.get("team_id")
    opts = LP.pickable_teams(order, _wl_table(gender, season_pick),
                             my_team=_mine, league_wide=_wr_league_wide)
    if not opts:
        empty_state("No team to build for",
                    "Ask the admin to assign you a team with tracked games, "
                    "then build its lineups here. Go League-wide in Settings to "
                    "build any team's lineups.")
        return None
    return st.selectbox("Team", opts,
                        format_func=lambda t: f"#{scored[t]['Rank']} {name_of[t]}",
                        key=key)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — MATCHUP
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _render_matchup():
    # These three shadow the page-level board on purpose, and they are bound
    # FIRST so nothing in this fragment can read the live board by accident once
    # a past date is picked. Both fetchers are cached, so re-asking for the live
    # board here is a dict lookup, not a second solve.
    scored = _scored(gender, season_pick, form_w)
    tracked = _tracked(gender, season_pick)
    order = sorted(scored, key=lambda t: scored[t]["Rank"])

    st.subheader("Matchup predictor")
    st.caption(
        f"Projected score, win probability, a line-by-line margin breakdown, and "
        f"the full margin distribution across {n:,} simulated games.")

    # ── back in time ─────────────────────────────────────────────────────────
    # The same question the Rankings week picker answers, asked of a matchup:
    # what would this game have looked like BEFORE the teams played the rest of
    # their seasons? Rankings can answer it with a table read; this cannot (see
    # _asof_scored), so it re-solves.
    _LIVE = "Today (live board)"
    _days = _asof_days(gender, season_pick)
    asof = None
    if _days:
        _pick = st.selectbox(
            "🕘 As of", [_LIVE] + _days, key="wr_asof",
            help="Project this matchup off the board as it stood on a past "
                 "date — only the games finished on or before that day count. "
                 "The whole view follows the date: verdict, simulation, "
                 "one-pager.")
        asof = None if _pick == _LIVE else _pick

    if asof:
        _b = _asof_scored(gender, asof, season_pick, form_w)
        if not _b:
            st.warning(f"Too few games had been played by **{asof}** to solve a "
                       f"board worth showing — showing the live board instead.")
            asof = None
        else:
            scored, tracked = _b, _asof_tracked(gender, asof, season_pick)
            order = sorted(scored, key=lambda t: scored[t]["Rank"])
            # A team with no game yet on that date is not on that board. Its id
            # can still be sitting in the picker's session state from the live
            # list, and a selectbox handed a value outside its options is a
            # crash, not a reset.
            for _k in ("wr_a", "wr_b"):
                if st.session_state.get(_k) not in order:
                    st.session_state.pop(_k, None)
            st.info(f"**Back in time — {asof}.** Every number below is solved "
                    f"over the {len(BT.game_ids_through(asof, gender, season_pick)):,} "
                    f"games finished on or before that day; {len(order)} teams "
                    f"were rated. {BT.CAVEAT}")

    def _pfmt(t):
        return f"#{scored[t]['Rank']} {name_of[t]} ({class_of[t]})"

    pc = st.columns([3, 3, 2])
    ta = pc[0].selectbox("Team A", order, index=0, format_func=_pfmt, key="wr_a")
    tb = pc[1].selectbox("Team B", order, index=min(1, len(order) - 1),
                         format_func=_pfmt, key="wr_b")
    homep = _seg("Home court", ["Neutral", name_of[ta], name_of[tb]],
                 key="wr_home", container=pc[2]) or "Neutral"

    if ta == tb:
        empty_state("Pick two different teams",
                    "Team A and Team B are the same — choose an opponent to "
                    "project the matchup.")
    else:
        home_arg = ta if homep == name_of[ta] else (tb if homep == name_of[tb] else None)
        pred = PRED.predict_game(ta, tb, scored=scored, tracked=tracked,
                                 gender=gender, home=home_arg)
        if not pred:
            empty_state("One of these teams is unrated",
                        "Both teams need a rating — enter game results for them "
                        "in the Input Hub first.")
        else:
            wa, wb = pred["win_prob_a"] * 100, pred["win_prob_b"] * 100
            ca, cb = _team_pair_colors(ta, tb)

            # verdict banner — the team-card banner grammar, matchup-sized:
            # projected score + win% per side, the spread verdict in the middle
            _fav_a = pred["favorite"] == ta
            st.markdown(
                f"<div style='background:linear-gradient(135deg,#080c14,"
                f"#0d1117 55%,#111827);border:1px solid {ca}55;"
                f"border-radius:18px;padding:18px 26px;margin:4px 0 12px;"
                f"display:flex;align-items:center;gap:18px'>"
                f"<div style='flex:1'>"
                f"<div style='font-size:20px;font-weight:900;color:#f0f6fc'>"
                f"{pred['a_name']}</div>"
                f"<div style='font-size:40px;font-weight:900;color:{ca};"
                f"line-height:1.1'>{pred['pf_a']:.0f}</div>"
                f"<div style='font-size:12px;color:{ca};font-weight:700'>"
                f"{wa:.0f}% win</div></div>"
                f"<div style='text-align:center;min-width:170px'>"
                f"<div style='font-size:9px;color:#8b949e;letter-spacing:2px'>"
                f"MODEL VERDICT</div>"
                f"<div style='font-size:17px;font-weight:800;color:#f0f6fc;"
                f"margin:3px 0'>{team_short(name_of[pred['favorite']])} "
                f"−{pred['spread']:.1f}</div>"
                f"<div style='font-size:11px;color:{(ca if _fav_a else cb)};"
                f"font-weight:700'>{pred['confidence']}</div></div>"
                f"<div style='flex:1;text-align:right'>"
                f"<div style='font-size:20px;font-weight:900;color:#f0f6fc'>"
                f"{pred['b_name']}</div>"
                f"<div style='font-size:40px;font-weight:900;color:{cb};"
                f"line-height:1.1'>{pred['pf_b']:.0f}</div>"
                f"<div style='font-size:12px;color:{cb};font-weight:700'>"
                f"{wb:.0f}% win</div></div></div>",
                unsafe_allow_html=True)

            # form-tilt read — WHY the blended number leans the way it does. Only
            # when the Form-weight knob is engaged and both rows carry form power.
            _A, _B = scored.get(ta, {}), scored.get(tb, {})
            if form_w > 0 and "FormPower" in _A and "FormPower" in _B:
                def _fchip(row, clr):
                    d = row["FormPower"] - row["SeasonPower"]
                    arrow = "▲" if d > 1 else "▼" if d < -1 else "▬"
                    tone = _uimod.GOOD if d > 1 else _uimod.BAD if d < -1 else "#8b949e"
                    return (f"<span style='color:{clr};font-weight:700'>"
                            f"{team_short(row['name'])}</span> "
                            f"<span style='color:{tone};font-weight:700'>{arrow} "
                            f"{d:+.1f}</span>")
                st.markdown(
                    f"<div style='font-size:12px;color:#8b949e;margin:-6px 0 12px'>"
                    f"⚖️ <b>Form-weighted {_form_pct}%</b> — ratings leaned toward "
                    f"current form · {_fchip(_A, ca)} &nbsp; {_fchip(_B, cb)} "
                    f"<span style='color:#6e7681'>(form power vs season)</span></div>",
                    unsafe_allow_html=True)

            # win-probability split bar (team-coloured)
            wp = go.Figure()
            wp.add_trace(go.Bar(
                x=[wa], y=["Win prob"], orientation="h", marker_color=ca,
                text=[f"{team_short(pred['a_name'])} {wa:.0f}%"],
                textposition="inside", insidetextanchor="middle",
                hovertemplate=f"{pred['a_name']}: {wa:.0f}%<extra></extra>"))
            wp.add_trace(go.Bar(
                x=[wb], y=["Win prob"], orientation="h", marker_color=cb,
                text=[f"{team_short(pred['b_name'])} {wb:.0f}%"],
                textposition="inside", insidetextanchor="middle",
                hovertemplate=f"{pred['b_name']}: {wb:.0f}%<extra></extra>"))
            wp.update_layout(barmode="stack", showlegend=False)
            wp.update_xaxes(range=[0, 100], visible=False)
            wp.update_yaxes(visible=False)
            _style(wp, 110, margin=dict(l=4, r=4, t=10, b=4))
            st.plotly_chart(wp, width="stretch", key="wr_wp")

            # ── the tells — each side's auto-scout lines (Tier 2 item 11).
            # The same league-relative feed the TD Insights tab deep-dives,
            # capped at 3 lines per team; rendered in the Tier-1 line grammar
            # (metric badge + confidence dot + n + sentence). Tracked depth →
            # each column rides the viewer's entitlement for THAT team, like
            # the Rankings deep dive (_see_trk).
            # Skipped on a past date, and this is not a nicety: the tells feed
            # and the exploit matrix are SEASON-WIDE tracked reads with no date
            # filter, so on a back-in-time board they would quietly describe
            # games that had not been played yet, sitting directly under a
            # verdict that was careful not to. The tale of the tape below is
            # HANDED the board (`scored`, `tracked`), so it rewinds on its own
            # and stays.
            _feed = {} if asof else _wr_insight_feed(gender, season_pick)
            if asof:
                st.caption("🕘 The auto-scout tells and the game plan are "
                           "season-wide tracked reads and cannot be rewound — "
                           "hidden while a past date is selected. The cards "
                           "below follow the date.")
            _wr_uid = AUTH.current_user()
            if _feed.get(ta) or _feed.get(tb):
                import re as _re_wri
                from helpers.cards import conf_dot as _conf_dot

                def _tell_lines(tid):
                    if not ENT.can_see_team_tracked(_wr_uid, tid):
                        return None                      # locked for viewer
                    return _feed.get(tid, [])

                def _tell_html(lines):
                    return "".join(
                        f"<div style='margin-top:4px;font-size:12px'>"
                        f"<span class='badge accent'>{ln['metric']}</span> "
                        f"{_conf_dot(ln.get('n'), k=8) if isinstance(ln.get('n'), (int, float)) else ''}"
                        f"<span style='color:var(--subtext);font-size:10px'>"
                        f"n={ln.get('n')}</span> "
                        + _re_wri.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", ln["text"])
                        + "</div>" for ln in lines)

                st.markdown("<div class='section-hdr'>The tells — what the "
                            "data says about each side</div>",
                            unsafe_allow_html=True)
                _tcols = st.columns(2)
                for _col, _tid, _clr in ((_tcols[0], ta, ca), (_tcols[1], tb, cb)):
                    with _col:
                        st.markdown(
                            f"<div style='font-weight:800;color:{_clr};"
                            f"font-size:13px'>{name_of[_tid]}</div>",
                            unsafe_allow_html=True)
                        _tl = _tell_lines(_tid)
                        if _tl is None:
                            st.caption("🔒 Tracked-depth tells ride your access "
                                       "to this team (own team / Co-op).")
                        elif not _tl:
                            st.caption("No tracked signal yet — the feed lights "
                                       "up as this team's games are tracked.")
                        else:
                            st.markdown(
                                f"<div class='gloss-card'>{_tell_html(_tl)}</div>",
                                unsafe_allow_html=True)
                st.caption("League-relative reads (|z| vs the tracked field), "
                           "same engine as the Team Dashboard → Insights tab — "
                           "attack the listed weakness, respect the strength.")

            # ── tale of the tape — the shared mini team cards (WAR_ROOM_PLAN
            # W-B). Tracked-depth rows gate per team on the viewer's
            # entitlement, exactly like the deep-dive card.
            import helpers.dashboard.team_card as TC
            _tt_user = AUTH.current_user()
            tt1, tt2 = st.columns(2)
            tt1.markdown(
                TC.render_mini(ta, gender, scored, tracked,
                               show_tracked=_can_team(_tt_user, ta)),
                unsafe_allow_html=True)
            tt2.markdown(
                TC.render_mini(tb, gender, scored, tracked,
                               show_tracked=_can_team(_tt_user, tb)),
                unsafe_allow_html=True)

            # ── scheduled-game extras: rest edge + crew outlook — only when
            # this matchup is ACTUALLY on the calendar. Display-only reads;
            # deliberately NOT folded into the spread (real-numbers rule).
            _sched = query("""
                SELECT g.id, g.date FROM games g
                WHERE ((g.team1_id=? AND g.team2_id=?)
                    OR (g.team1_id=? AND g.team2_id=?))
                  AND (g.home_score IS NULL OR g.away_score IS NULL)
                  AND g.date >= date('now') ORDER BY g.date LIMIT 1""",
                (ta, tb, tb, ta))
            if _sched:
                import helpers.fatigue as FT
                _sd = _sched[0]["date"]
                _ra = FT.rest_on_date(ta, _sd)
                _rb = FT.rest_on_date(tb, _sd)
                if _ra is not None and _rb is not None:
                    _fresh = (name_of[ta] if _ra > _rb
                              else (name_of[tb] if _rb > _ra else None))
                    st.caption(
                        f"**Rest on {_sd}:** {team_short(name_of[ta])} "
                        f"{_ra} day{'s' if _ra != 1 else ''} · "
                        f"{team_short(name_of[tb])} {_rb} "
                        f"day{'s' if _rb != 1 else ''}"
                        + (f" — {_fresh} comes in fresher (context only; "
                           "not in the spread)." if _fresh else " — even rest."))
                _refs = [r["official_id"] for r in query(
                    "SELECT official_id FROM game_lineup_officials WHERE game_id=?",
                    (_sched[0]["id"],))]
                if _refs:
                    try:
                        import helpers.ref_tendencies as RTD
                        import helpers.officials as _OFFW
                        # env folds setup-assigned untracked BOXED games into the
                        # scoring / pace / total-foul read (projection coverage);
                        # whistle & lean stay tracked-only.
                        _uid = AUTH.current_user()
                        _vt = ENT.visible_tracked_game_ids(_uid, season=season_pick)
                        _vu = (None if _vt is None
                               else ENT.visible_untracked_boxed_game_ids(
                                   _uid, season=season_pick))
                        _env = _OFFW.official_environment(
                            gender=gender, game_ids=_vt, untracked_ids=_vu,
                            season=season_pick)
                        _co = RTD.crew_outlook(_refs, gender=gender, env=_env)
                        if _co:
                            st.caption(f"**Crew outlook:** {_co['summary']}")
                            if _co.get("tags"):
                                st.caption(" · ".join(f"`{t}`"
                                                      for t in _co["tags"]))
                    except Exception:
                        pass

            # manual crew "projection dropdown" — project ANY officiating crew
            # for this matchup (scheduled or not). Context only: the crew read is
            # never folded into the projected spread (real-numbers rule).
            with st.expander("🔮 Crew impact — project a specific officiating crew"):
                _allo = {o["name"]: o["id"] for o in query(
                    "SELECT id, name FROM officials WHERE archived=0 ORDER BY name")}
                if not _allo:
                    st.caption("No officials on file yet — add them in the Game "
                               "Tracker or on the Box Score Entry page (untracked games).")
                else:
                    _cp = st.multiselect("Officiating crew", list(_allo),
                                         key=f"wr_crew_{ta}_{tb}")
                    if _cp:
                        try:
                            import helpers.ref_tendencies as _RTM
                            import helpers.officials as _OFFM
                            _uidm = AUTH.current_user()
                            _vtm = ENT.visible_tracked_game_ids(
                                _uidm, season=season_pick)
                            _vum = (None if _vtm is None
                                    else ENT.visible_untracked_boxed_game_ids(
                                        _uidm, season=season_pick))
                            _ovm = _OFFM.official_overview(
                                gender=gender,
                                game_ids=(set(_vtm) if _vtm is not None else None),
                                season=season_pick)
                            _envm = _OFFM.official_environment(
                                gender=gender, game_ids=_vtm, untracked_ids=_vum,
                                season=season_pick)
                            _com = _RTM.crew_outlook([_allo[n] for n in _cp],
                                                     overview=_ovm, env=_envm)
                            if _com:
                                st.markdown(" · ".join(f"`{t}`"
                                                       for t in _com["tags"]))
                                st.info(_com["summary"]
                                        + "  _(context only — not in the spread.)_")
                            else:
                                st.caption("No history for that crew yet.")
                        except Exception:
                            st.caption("Crew projection unavailable.")
                    else:
                        st.caption("Pick the crew to see expected whistle / lean / "
                                   "scoring / pace / total-foul environment for "
                                   "this matchup — including setup-entered "
                                   "untracked boxes. Context only.")

            # simulated margin distribution
            with _eng("Simulating matchup…",
                      [f"{n:,} Monte-Carlo games", "Sampling possession outcomes",
                       "Aggregating margins & win share"]):
                sim = _sim_game(gender, ta, tb, home_arg, n, season_pick, form_w,
                                asof=asof)
            margins = np.asarray(sim["margins"])
            edges = np.linspace(float(margins.min()), float(margins.max()), 41)
            centers = (edges[:-1] + edges[1:]) / 2
            counts, _ = np.histogram(margins, bins=edges)
            share = counts / max(counts.sum(), 1) * 100
            bar_colors = [ca if c >= 0 else cb for c in centers]
            dist = go.Figure(go.Bar(
                x=centers, y=share, marker_color=bar_colors, marker_line_width=0,
                hovertemplate="margin %{x:+.0f} · %{y:.1f}% of sims<extra></extra>"))
            dist.add_vline(x=0, line=dict(color="#8b949e", dash="dot"))
            dist.add_vline(x=sim["mean_margin"], line=dict(color=ACCENT, width=2))
            dist.add_vrect(x0=sim["p05"], x1=sim["p95"], line_width=0,
                           fillcolor="rgba(240,165,0,0.07)")
            dist.update_xaxes(title=f"Projected margin  ({team_short(pred['a_name'])} "
                                    f"− {team_short(pred['b_name'])})")
            dist.update_yaxes(title="% of sims")
            _style(dist, 300)
            _chart(dist, key="wr_margin",
                   data=pd.DataFrame({"Margin": centers, "% of sims": share}))
            st.caption(
                f"**{pred['a_name']} {pred['pf_a']:.0f} – {pred['pf_b']:.0f} "
                f"{pred['b_name']}** · total {pred['total']:.0f} · "
                f"{pred['a_name']} wins **{sim['win_a'] * 100:.0f}%** of {n:,} sims · "
                f"90% of outcomes land between {sim['p05']:+.0f} and "
                f"{sim['p95']:+.0f} · {pred['confidence']}.")

            st.markdown("**Where the margin comes from**")
            st.dataframe(
                _round_df(pd.DataFrame(
                    [{"Component": c["label"], "Points": c["value"],
                      "Detail": c["note"]} for c in pred["components"]])),
                hide_index=True, width="stretch")

            if pred["tracked"] and _can_game(
                    AUTH.current_user(), ta, tb):
                tk = pred["tracked"]
                st.markdown("**Tracked possession projection** — both teams have "
                            "tracked games")
                tcl = st.columns(4)
                tcl[0].metric("Pace", f"{tk['pace']:.0f}")
                tcl[1].metric(f"{team_short(pred['a_name'])} pts", f"{tk['pf_a']:.0f}")
                tcl[2].metric(f"{team_short(pred['b_name'])} pts", f"{tk['pf_b']:.0f}")
                tcl[3].metric("ORtg A / B", f"{tk['ortg_a']:.0f} / {tk['ortg_b']:.0f}")

            # ── the takeaway artifact: a print-ready matchup one-pager ───────
            from datetime import datetime as _dt
            import re as _re
            _slug = _re.sub(r"[^A-Za-z0-9]+", "_",
                            f"{pred['a_name']}_vs_{pred['b_name']}").strip("_")
            from helpers.ui import pdf_or_html_download
            pdf_or_html_download(
                "Matchup one-pager",
                lambda: MS.matchup_html(
                    pred, sim=sim, n_sims=n,
                    home_label=("Neutral floor" if home_arg is None
                                else f"Home court: {name_of[home_arg]}"),
                    generated=_dt.now().strftime("%B %d, %Y")),
                f"matchup_{_slug}", key="wr_sheet_dl",
                fp=(_slug, n, home_arg))
            st.caption("Print-ready scouting sheet — text it straight to the "
                       "staff. Next steps: **Defensive assignments** (who guards "
                       "whom) and **Lineups** (pick the five) in the views above.")

            # ── game plan vs this opponent: exploit matrix + defensive plan ──
            # (Tier 2, ML_LAYER_ROADMAP — the cross-team bridge). A = you, B = the
            # opponent. Tag-driven, so it lights up as play_type / defense get
            # tagged; gated by the same co-op read rule as the tracked projection.
            _gp_user = AUTH.current_user()
            if _can_game(_gp_user, ta, tb) and not asof:
                gp = _game_plan(gender, ta, tb,
                                _vis_tuple(_gp_user, ta), _vis_tuple(_gp_user, tb))
                off, dfn = gp["offense"], gp["defense"]
                st.markdown(f"<div class='lab-hdr'>Game plan — {pred['a_name']} vs "
                            f"{pred['b_name']}</div>", unsafe_allow_html=True)
                st.caption(f"{pred['a_name']}'s set calls × {pred['b_name']}'s "
                           "defense, joined on the tagged play-type / defense data. "
                           "A set you run well that they give up points on = a call "
                           "to lean on.")
                if off["rows"]:
                    st.markdown("**Exploit matrix — calls to lean on**")
                    st.dataframe(_round_df(pd.DataFrame([{
                        "Set": r["label"], "Our PPP": r["our_ppp"],
                        "Our %ile": r["our_pct"],
                        "They allow (PPP)": r["opp_ppp"], "Edge": r["edge"],
                        "Trust": "✓" if r["stable"] else "thin",
                    } for r in off["rows"]])), hide_index=True, width="stretch",
                        column_config={
                            "Our PPP": st.column_config.NumberColumn(format="%.2f"),
                            "They allow (PPP)": st.column_config.NumberColumn(
                                format="%.2f"),
                            "Edge": st.column_config.NumberColumn(format="%.2f"),
                        })
                st.caption(off["note"])
                # Every row prints its possession count. These three lists are
                # ordered by PPP with no volume floor above `min_poss`, so a
                # scheme faced four times can head the "play on D" list at
                # 0.00 — the same one-game-leaderboard shape THE BOOK §8.2
                # found on Rankings, in a place a coach acts on.
                if dfn["throw"]:
                    st.markdown("**Play on D:** " + " · ".join(
                        f"{r['label']} ({r['ppp']:.2f} PPP, {r['poss']} poss)"
                        for r in dfn["throw"]))
                if dfn["avoid"]:
                    st.markdown("**Don't sit in:** " + " · ".join(
                        f"{r['label']} ({r['ppp']:.2f}, {r['poss']} poss)"
                        for r in dfn["avoid"]))
                # The other half of the plan, and the half with the sample:
                # the schemes the opponent RUNS, ranked by what they give up.
                # `throw`/`avoid` are the D call; this is the O call, and it is
                # computed on every render of this block (THE BOOK §12.4).
                if dfn.get("their_leaks"):
                    st.markdown("**Attack on O:** " + " · ".join(
                        f"{r['label']} ({r['ppp_allowed']:.2f} PPP allowed, "
                        f"{r['poss']} poss)" for r in dfn["their_leaks"]))
                _thin_def = bool(dfn["throw"] or dfn["avoid"]) and not any(
                    r["stable"] for r in dfn["throw"] + dfn["avoid"])
                st.caption(("⚠ Thin sample — lean on scouting, not these splits. "
                            if _thin_def else "") + dfn["note"])

                # ── EXPERIMENTAL: scheme-based projection (gated 150 set calls) ──
                sp = _scheme_proj(gender, ta, tb,
                                  _vis_tuple(_gp_user, ta),
                                  _vis_tuple(_gp_user, tb), season=season_pick)
                with st.expander("🧪 Experimental — scheme-based projection",
                                 expanded=False):
                    if sp is None:
                        st.caption("No overlapping tagged play types between these "
                                   "two teams yet — tag set calls + the defense "
                                   "scheme in the Game Tracker to unlock this.")
                    else:
                        st.caption(
                            "A different lens than the rating-based line above: it "
                            "weights each team's actual **play-type share** by the "
                            "matchup-expected points per type (your offense + their "
                            "per-type defense − the league baseline). **Very "
                            "experimental** on this little tagged data — a research "
                            "cross-check, not the official odds. The Monte-Carlo "
                            "line above stays authoritative.")
                        if not sp["stable"]:
                            st.warning("⚠ " + sp["note"])
                        _m = st.columns(3)
                        _m[0].metric(f"{team_short(pred['a_name'])} pts", sp["a_pts"])
                        _m[1].metric(f"{team_short(pred['b_name'])} pts", sp["b_pts"])
                        _m[2].metric("Scheme margin", f"{sp['margin']:+d}",
                                     help="From the play-type mix, not the ratings.")
                        if sp["rows_a"]:
                            st.markdown(f"**{pred['a_name']} — projected points by "
                                        "set call**")
                            st.dataframe(_round_df(pd.DataFrame([{
                                "Set": r["label"], "Share": f"{r['share'] * 100:.0f}%",
                                "Our PPP": r["off_ppp"], "They allow": r["opp_allowed"],
                                "Lg avg": r["lg_ppp"], "Exp PPP": r["exp_ppp"],
                            } for r in sp["rows_a"]])), hide_index=True,
                                width="stretch")
                        st.caption(f"Based on {sp['tagged_min']} tagged set calls "
                                   f"(smallest leg) · ~{sp['poss']} possessions/game.")


    # ── how accurate is this? (walk-forward backtest) ────────────────────────
    # The predictor has shown a number for every game in this book, and every
    # one of those games has now been played. Nothing in the app said how often
    # it was right, which is the first question a coach asks of a projection and
    # the one that decides whether he believes the next one.
    st.divider()
    with st.expander("🎯 How accurate is this predictor?", expanded=False):
        st.caption(
            "Walk-forward: every finished game in this season is re-predicted "
            "from the board solved over the games finished **strictly before "
            "that day** — the whole day is held out, not just the one game, so "
            "a Tuesday result cannot leak into a Tuesday prediction. Forfeits "
            "are excluded. Thin-sample games (a team under "
            f"{BT.MIN_TEAM_GP} prior games) are measured but kept out of the "
            "headline.")
        _bt_key = f"wr_bt_{gender}_{season_pick}_{int(form_w * 100)}"
        if st.button("Measure it", key="wr_bt_run",
                     help="~20 seconds the first time; cached for 30 minutes."):
            st.session_state[_bt_key] = True
        if st.session_state.get(_bt_key):
            with _eng("Re-playing the season…",
                      ["Solving one board per game day",
                       "Predicting every game from the day before",
                       "Scoring margins, win probabilities and calibration"]):
                _bt = _backtest(gender, season_pick, form_w)
            _s = _bt["summary"]
            if not _s["n"]:
                st.info("Not enough finished games in this season to backtest.")
            else:
                _m = st.columns(4)
                _m[0].metric("Games scored", f"{_s['n']:,}",
                             help=f"{_s['n_all']:,} predicted, "
                                  f"{_s['n_all'] - _s['n']:,} held out as thin.")
                _m[1].metric("Picked the winner", f"{_s['hit'] * 100:.1f}%")
                _m[2].metric("Typical miss", f"{_s['mae']:.1f} pts",
                             help="Mean absolute error on the final margin.")
                _m[3].metric("Brier skill", f"{_s['skill']:.3f}",
                             help=f"Brier {_s['brier']:.4f} vs {_s['brier_baseline']} "
                                  "for a coin flip on every game. 1.0 is perfect, "
                                  "0 is no better than a coin.")

                # The two constants this test can price. Reported, never
                # applied: a model constant does not move on one season's
                # measurement without its own gate.
                _c = st.columns(2)
                _c[0].metric("Pre-game SD — measured",
                             f"{_s['rmse']:.1f} pts",
                             delta=f"{_s['rmse'] - _s['sd_current']:+.1f} vs the "
                                   f"{_s['sd_current']:.0f} in use",
                             delta_color="off",
                             help="The RMSE of the margin error IS the pre-game "
                                  "SD the win-probability model assumes. If the "
                                  "measured value is higher, stated win "
                                  "probabilities are too confident.")
                # bias_home, not the mixed bias: the overall number is diluted
                # by however many neutral-floor games the book has, and the
                # reader of a HOME-COURT number wants the home floors.
                _bh = _s["bias_home"]
                _c[1].metric("Home lean — measured",
                             "—" if _bh is None else f"{_bh:+.2f} pts",
                             delta=f"home court set to {_s['hca_current']:.1f}"
                                   + (f" · neutral control {_s['bias_neutral']:+.2f}"
                                      if _s["bias_neutral"] is not None else ""),
                             delta_color="off",
                             help="Mean signed error (predicted − actual) on "
                                  "home floors. A positive number means the "
                                  "model favours the home team by that much too "
                                  "much — so the home-court constant is that "
                                  "much too big.")

                if _bt["calibration"]:
                    st.markdown("**Does a stated win probability mean what it "
                                "says?**")
                    st.dataframe(_round_df(pd.DataFrame([{
                        "Favourite's win prob": r["bin"], "Games": r["n"],
                        "Model said": f"{r['said'] * 100:.1f}%",
                        "Actually won": f"{r['actual'] * 100:.1f}%",
                        "Off by": f"{(r['said'] - r['actual']) * 100:+.1f} pts",
                    } for r in _bt["calibration"]])), hide_index=True,
                        width="stretch")
                    st.caption("A model can pick winners well and still be badly "
                               "calibrated — saying 90% when it means 70% is a "
                               "different failure from picking the wrong team.")

                if _bt["by_confidence"]:
                    st.markdown("**What each confidence word was worth**")
                    st.dataframe(_round_df(pd.DataFrame([{
                        "Confidence": r["confidence"], "Games": r["n"],
                        "Picked the winner": (f"{r['hit'] * 100:.1f}%"
                                              if r["hit"] is not None else "—"),
                        "Typical miss": f"{r['mae']:.1f}",
                    } for r in _bt["by_confidence"]])), hide_index=True,
                        width="stretch")

                if _bt["by_game_type"]:
                    st.markdown("**By game type**")
                    st.dataframe(_round_df(pd.DataFrame([{
                        "Type": r["game_type"], "Games": r["n"],
                        "Home lean": f"{r['bias']:+.2f}",
                        "Typical miss": f"{r['mae']:.1f}",
                        "Flagged neutral": r["flagged_neutral"],
                    } for r in _bt["by_game_type"]])), hide_index=True,
                        width="stretch")
                    st.caption("Home court is granted on every game that is not "
                               "flagged neutral. A playoff row with a worse home "
                               "lean than the regular-season row and no neutral "
                               "flags is the flag missing, not the model.")

                _worst = BT.worst_misses(_bt["rows"], top=10)
                if _worst:
                    st.markdown("**The ten it got most wrong**")
                    st.dataframe(_round_df(pd.DataFrame([{
                        "Date": r["day"],
                        "Matchup": f"{team_short(r['a_name'])} vs "
                                   f"{team_short(r['b_name'])}",
                        "Predicted": f"{r['pred']:+.1f}",
                        "Actual": f"{r['actual']:+.0f}",
                        "Off by": f"{r['abs_err']:.0f}",
                    } for r in _worst])), hide_index=True, width="stretch")

                st.caption(BT.CAVEAT)


if _wrview == "Matchup":
    if _wr_league_wide:
        _render_matchup()
    else:
        _wr_locked(_wrview)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — SEASON SIM
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _render_season():
    st.subheader("Season simulation")
    st.caption(
        f"Replays every finished game {n:,} times from the ratings to get each "
        "team's **expected wins** — and the **luck** baked into their actual "
        "record (actual minus expected).")

    with _eng("Simulating season…",
              [f"{n:,} season replays", "Re-playing every scheduled game",
               "Tallying wins, seeds & finish odds"]):
        sea = _sim_season(gender, n, season_pick, form_w)
    if not sea:
        empty_state("No finished games to simulate",
                    "Enter at least one final score in the Input Hub and the season "
                    "simulation lights up here.")
    else:
        rows = []
        for t, d in sea.items():
            actual = scored.get(t, {}).get("W")
            luck = (actual - d["exp_wins"]) if actual is not None else None
            rows.append({"Team": name_of.get(t, d["name"]), "G": d["games"],
                         "Actual W": actual, "Exp W": d["exp_wins"], "Luck": luck})
        rows.sort(key=lambda r: -r["Exp W"])
        df = pd.DataFrame(rows)

        # luck scatter — actual vs expected, y=x diagonal
        pts = [r for r in rows if r["Actual W"] is not None]
        if pts:
            xs = [r["Exp W"] for r in pts]
            ys = [r["Actual W"] for r in pts]
            lim = max(max(xs), max(ys)) + 1
            sc = go.Figure()
            sc.add_trace(go.Scatter(
                x=[0, lim], y=[0, lim], mode="lines",
                line=dict(color="#30363d", dash="dot"), hoverinfo="skip",
                showlegend=False))
            sc.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers+text",
                text=[team_short(r["Team"]) for r in pts], textposition="top center",
                textfont=dict(size=9, color="#8b949e"),
                marker=dict(size=11,
                            color=[GOOD if r["Luck"] >= 0 else BAD for r in pts],
                            line=dict(width=0.5, color="#0d1117")),
                hovertemplate="%{text}<br>expected %{x:.1f} · actual %{y} wins"
                              "<extra></extra>", showlegend=False))
            sc.update_xaxes(title="Expected wins (true talent)")
            sc.update_yaxes(title="Actual wins")
            _style(sc, 420)
            _chart(sc, data=pd.DataFrame(pts), key="wr_luck")
            st.caption("Above the line = winning more than the ratings expect "
                       "(green, lucky / clutch); below = unlucky (red).")

        st.dataframe(
            _style_df(df, grad_cols=["Exp W"], signed_cols=["Luck"]),
            hide_index=True, width="stretch", key="wr_seas_tbl")

        # per-team win distribution
        pick = st.selectbox("Win distribution for", order,
                            format_func=lambda t: name_of[t], key="wr_seas_pick")
        if pick in sea:
            d = sea[pick]
            wd = np.asarray(d["win_dist"])
            xs = list(range(len(wd)))
            fig = go.Figure(go.Bar(
                x=xs, y=wd * 100, marker_color=team_color(name_of[pick], pick),
                marker_line_width=0,
                hovertemplate="%{x} wins · %{y:.1f}% of seasons<extra></extra>"))
            actual = scored.get(pick, {}).get("W")
            if actual is not None:
                fig.add_vline(x=actual, line=dict(color=GOOD, width=2),
                              annotation_text=f"actual {actual}")
            fig.add_vline(x=d["exp_wins"], line=dict(color=ACCENT, dash="dot"),
                          annotation_text=f"exp {d['exp_wins']:.1f}")
            fig.update_xaxes(title="Wins", dtick=1)
            fig.update_yaxes(title="% of simulated seasons")
            _style(fig, 300)
            st.plotly_chart(fig, width="stretch", key="wr_seas_dist")


if _wrview == "Season sim":
    if _wr_league_wide:
        _render_season()
    else:
        _wr_locked(_wrview)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — BRACKET
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _render_bracket():
    st.subheader("Bracket / tournament odds")
    st.caption(
        f"Build a single-elimination bracket and roll it {n:,} times. Auto-seed by "
        "rating, or set the size and place teams into seeds yourself. Byes to the "
        "next power of two are handled automatically.")

    _BYE = -1
    # staged bracket-config load — applied BEFORE the widgets render; teams no
    # longer in the rated pool fall back to byes / drop from the field.
    _bl = st.session_state.pop("_wr_brk_load", None)
    if _bl:
        _bsz = _bl.get("size", 8)
        st.session_state["wr_brk_size"] = _bsz if _bsz in (4, 8, 16, 32) else 8
        st.session_state["wr_brk_mode"] = ("Manual" if _bl.get("mode") == "Manual"
                                           else "Auto (by rating)")
        if _bl.get("mode") == "Manual":
            _seeds = list(_bl.get("seeds") or [])
            _dropped = False
            for i in range(st.session_state["wr_brk_size"]):
                _sv = _seeds[i] if i < len(_seeds) else _BYE
                if _sv not in order and _sv != _BYE:
                    _sv, _dropped = _BYE, True
                st.session_state[f"wr_seed_{i}"] = _sv
            if _dropped:
                st.toast("Some saved seeds aren't rated in this pool — left "
                         "as byes.", icon="⚠️")
        else:
            st.session_state["wr_field"] = [t for t in (_bl.get("field") or [])
                                            if t in order]
        st.session_state.pop("wr_brk_ran", None)

    _csz, _cmode = st.columns([1, 2])
    size = _csz.selectbox("Bracket size", [4, 8, 16, 32], index=1, key="wr_brk_size")
    mode = _cmode.radio("Seeding", ["Auto (by rating)", "Manual"],
                        horizontal=True, key="wr_brk_mode")
    if mode.startswith("Auto"):
        default_field = order[:min(size, len(order))]
        field = st.multiselect(
            "Tournament field", order, default=default_field,
            format_func=lambda t: f"#{scored[t]['Rank']} {name_of[t]}", key="wr_field")
        seed_list, reseed = list(field), True
        n_teams = len(field)
    else:
        st.caption("Place a team in each seed (1 = top seed). Leave a slot on "
                   "“— bye —” to give that region a first-round bye.")
        _opts = [_BYE] + list(order)

        def _seedfmt(t):
            return "— bye —" if t == _BYE else f"#{scored[t]['Rank']} {name_of[t]}"
        seed_list, _seen, _dupes = [], set(), False
        _grid = st.columns(4)
        for i in range(size):
            _dflt = order[i] if i < len(order) else _BYE
            pick = _grid[i % 4].selectbox(
                f"Seed {i + 1}", _opts,
                index=(_opts.index(_dflt) if _dflt in _opts else 0),
                format_func=_seedfmt, key=f"wr_seed_{i}")
            if pick == _BYE or pick in _seen:      # a team can hold only one seed
                _dupes = _dupes or (pick != _BYE)
                seed_list.append(None)
            else:
                seed_list.append(pick)
                _seen.add(pick)
        if _dupes:
            st.warning("A team was placed in more than one seed — the later "
                       "duplicate(s) were dropped to byes.")
        reseed = False
        n_teams = len(_seen)

    # ── 💾 Saved brackets — keep a seeded field (e.g. the real OSSAA draw) ────
    with st.expander("💾 Saved brackets"):
        _bb = _wr_blob("wr_bracket_seeds")
        _bs1, _bs2 = st.columns([3, 1])
        _bname = _bs1.text_input("Save this bracket as", key="wr_brk_save_name",
                                 placeholder="e.g. 3A Area I — real draw")
        _bs2.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if _bs2.button("Save", key="wr_brk_save_btn",
                       disabled=not (_bname or "").strip()):
            _nm = _bname.strip()
            if len(_bb) >= _WR_MAX_SAVED and _nm not in _bb:
                st.warning(f"{_WR_MAX_SAVED} saved brackets max — delete one "
                           "first.")
            else:
                from datetime import date as _date
                _cfg_b = {"gender": gender, "size": int(size),
                          "mode": "Manual" if mode == "Manual" else "Auto",
                          "sims": int(n), "form": int(_form_pct),
                          "saved": _date.today().isoformat()}
                if mode == "Manual":
                    _cfg_b["seeds"] = [int(t) if t is not None else _BYE
                                       for t in seed_list]
                else:
                    _cfg_b["field"] = [int(t) for t in seed_list]
                _bb[_nm] = _cfg_b
                _wr_blob_save("wr_bracket_seeds", _bb)
                st.toast(f"Saved '{_nm}'", icon="💾")
                st.rerun()
        _bnames = [nm for nm, d in sorted(_bb.items())
                   if d.get("gender") in (None, gender)]
        if not _bnames:
            st.caption("No saved brackets yet — set the size and seeds above "
                       "(Manual seeding for a real OSSAA draw), name it, Save.")
        else:
            _bc1, _bc2, _bc3 = st.columns([3, 1, 1])
            _bpick = _bc1.selectbox(
                "Saved brackets", _bnames, key="wr_brk_saved_pick",
                format_func=lambda nm: (
                    f"{nm} — {_bb[nm].get('mode', '?')} · "
                    f"{_bb[nm].get('size', '?')} teams · {_bb[nm].get('saved', '')}"),
                label_visibility="collapsed")

            def _brk_do_load(nm, _blob=_bb):
                _d = _blob.get(nm) or {}
                st.session_state["_wr_brk_load"] = _d
                # the sim sliders live at page TOP; a callback runs before any
                # widget instantiates, so this is the one safe place to
                # restore them (the fragment's staging runs too late on a
                # full rerun).
                if _d.get("sims") in (5000, 20000, 50000):
                    st.session_state["wr_sims"] = _d["sims"]
                if _d.get("form") is not None:
                    st.session_state["wr_form"] = int(min(100, max(0, _d["form"])))

            _bc2.button("Load", key="wr_brk_load_btn",
                        on_click=_brk_do_load, args=(_bpick,))
            if _bc3.button("Delete", key="wr_brk_del_btn"):
                _bb.pop(_bpick, None)
                _wr_blob_save("wr_bracket_seeds", _bb)
                st.rerun()

    if n_teams < 2:
        empty_state("Pick at least two teams",
                    "Add teams to the bracket to simulate championship odds.")
    elif (not st.session_state.get("wr_brk_ran")
          and not st.button(f"Run bracket — roll it {n:,} times",
                            key="wr_brk_go", type="primary")):
        st.caption("The bracket is the heaviest simulation on the page, so it "
                   "waits for the button. Results stay loaded once run; edit the "
                   "size or seeds and it re-rolls.")
    else:
        st.session_state["wr_brk_ran"] = True
        with _eng("Simulating bracket…",
                  [f"{n:,} tournament runs", "Advancing winners round by round",
                   "Computing each team's title odds"]):
            res = _sim_bracket(gender, tuple(seed_list), n, reseed, size,
                               season_pick, form_w)
        if not res:
            empty_state("Not enough rated teams in the field",
                        "Add more rated teams to simulate the bracket.")
        else:
            odds = res["odds"]
            # ── the probabilistic bracket TREE (headline visual) ──────────────
            st.markdown("**Bracket — most-likely path to the title**")
            st.caption(f"Each slot shows its most-likely team and how often "
                       f"({n:,} sims) they reach it — a chalk bracket; byes to the "
                       "next power of two are handled automatically. Colour = how "
                       "locked that slot is (green ≥60%, amber ≥30%).")
            st.markdown(_bracket_tree_html(res, team_short), unsafe_allow_html=True)

            top = odds[:12]
            names = [team_short(d["name"]) for d in top][::-1]
            vals = [d["champ_pct"] for d in top][::-1]
            texts = [f"{d['champ_pct']:.1f}%" for d in top][::-1]
            st.markdown("**Championship odds**")
            st.plotly_chart(bar_h(names, vals, texts, color=ACCENT),
                            width="stretch", key="wr_title")

            # round-by-round survival heatmap
            n_rounds = len(odds[0]["rounds"]) - 1
            if n_rounds >= 1:
                labels = _round_labels(n_rounds)
                z = [[d["rounds"][k] * 100 for k in range(1, n_rounds + 1)]
                     for d in odds]
                yt = [f"{d['seed']}. {team_short(d['name'])}" for d in odds]
                hm = go.Figure(go.Heatmap(
                    z=z, x=labels, y=yt, colorscale=HEAT, zmin=0, zmax=100,
                    colorbar=dict(title="%", thickness=12),
                    hovertemplate="%{y}<br>%{x}: %{z:.1f}%<extra></extra>"))
                hm.update_yaxes(autorange="reversed")
                _style(hm, max(300, 26 * len(odds) + 80))
                st.markdown("**Survival curve — odds of reaching each round**")
                st.plotly_chart(hm, width="stretch", key="wr_surv")

            df = pd.DataFrame([{
                "Seed": d["seed"], "Team": d["name"], "Champ %": d["champ_pct"],
                "Finals %": (round(d["finals_odds"] * 100, 1)
                             if d["finals_odds"] is not None else None),
            } for d in odds])
            st.dataframe(
                _round_df(df), hide_index=True, width="stretch", key="wr_brk_tbl",
                column_config={
                    "Champ %": st.column_config.ProgressColumn(
                        "Champ %", format="%.1f%%", min_value=0, max_value=100)})


if _wrview == "Bracket":
    if _wr_league_wide:
        _render_bracket()
    else:
        _wr_locked(_wrview)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — LINEUPS  (Creator · Rotation optimizer · Compare — one engine)
# ══════════════════════════════════════════════════════════════════════════════
_lu_view = None
if _wrview == "Lineups":
    st.subheader("Lineups — build, optimize, compare")
    st.caption(
        "The decision every game turns on, in three reads: **Creator** hand-builds "
        "a five · **Rotation optimizer** finds the minutes that hit your win "
        "formula · **Compare** shows the give and take between candidate fives. "
        "One engine under every win-formula number here and on the Team "
        "Dashboard's Projection tab — the numbers agree everywhere.")
    _lu_view = _seg("Lineups view", ["Creator", "Rotation optimizer", "Compare"],
                    default="Creator", key="wr_lu_view",
                    label_visibility="collapsed") or "Creator"

if _wrview == "Lineups" and _lu_view == "Creator":
    # Solo (not League-wide) coaches build ONLY their own team — no "Any team"
    # mode and no cross-team selector. Admin / League-wide get every team.
    _li = AUTH.current_user()
    _li_any = ENT.viewer_is_league_wide(_li)
    _my_team = _li.get("team_id")
    _modes = ["One team", "Any team"] if _li_any else ["One team"]
    _lmode = ((_seg("Build from", _modes, key="wl_mode") or "One team")
              if len(_modes) > 1 else "One team")

    if _lmode == "One team":
        st.caption("Pick a team and a five for a possession-calibrated "
                   "projection (ORtg / DRtg / Net vs the league) plus the observed "
                   "on-court rating and the best bench swaps.")
        # The picker opens on the viewer's own team and lists only teams with
        # tracked data behind them. Ranked-and-index-0 put every league-wide
        # coach on the #1 team, which has none — see lineup_projection
        # .pickable_teams. `_wl_table` is cached, so reading it before the
        # widget costs nothing it was not going to pay anyway.
        _tbl = _wl_table(gender, season_pick)
        _team_opts = LP.pickable_teams(order, _tbl, my_team=_my_team,
                                       league_wide=_li_any)
        if not _team_opts:
            empty_state("No team to build for",
                        "Ask the admin to assign you a team with tracked games, "
                        "then build its lineup here. Go League-wide in Settings to "
                        "build any team's lineups.")
            st.stop()
        # staged lineup load (set by the Saved-lineups Load callback) — applied
        # BEFORE the widgets render; out-of-pool team/pids are dropped, like
        # the command-palette consumers.
        _ld = st.session_state.pop("_wl1_load", None)
        if _ld:
            if _ld.get("team_id") in _team_opts:
                st.session_state["wl1_team"] = _ld["team_id"]
                st.session_state["_wl1_load_pids"] = list(_ld.get("pids") or [])
            else:
                st.toast("That lineup's team isn't in your current pool.", icon="⚠️")
        _t = st.selectbox("Team", _team_opts,
                          format_func=lambda t: f"#{scored[t]['Rank']} {name_of[t]}",
                          key="wl1_team")
        _rows = [dict(r, _pid=pid) for pid, r in _tbl.items() if r["team_id"] == _t]
        if not _rows:
            # Not "track a game for them first" — nobody can track another
            # program's games, and the engine's own gate already knows the
            # number that matters.
            empty_state("Not enough tracked games yet",
                        f"Lineup projection {LP.no_rotation_reason(0)}.")
        else:
            _ctxd = _wl_ctx(gender, season_pick)
            _lab = {}
            for r in _rows:
                _b = _PLBL(r)
                _lab[r["_pid"]] = (f"{_b} (OVR {r['OVERALL']:.0f})"
                                   if r.get("OVERALL") is not None else _b)
            _def5 = [r["_pid"] for r in
                     sorted(_rows, key=lambda r: (r.get("MIN") or 0), reverse=True)[:5]]
            _lp = st.session_state.pop("_wl1_load_pids", None)
            if _lp is not None:
                _valid = [p for p in _lp if p in _lab]
                st.session_state["wl1_pick"] = _valid
                if len(_valid) < len(_lp):
                    st.toast("Some saved players aren't on this season's rated "
                             "roster anymore — loaded the rest.", icon="⚠️")
            _chosen = st.multiselect("Lineup (up to 5)", list(_lab), default=_def5,
                                     format_func=lambda pid: _lab[pid],
                                     max_selections=5, key="wl1_pick")

            # ── 💾 Saved lineups — save-as-name / load / delete (per coach) ──
            with st.expander("💾 Saved lineups"):
                _sl = _wr_blob("wr_saved_lineups")
                _sv1, _sv2 = st.columns([3, 1])
                _sname = _sv1.text_input(
                    "Save current five as", key="wl1_save_name",
                    placeholder="e.g. Crunch-time five")
                _sv2.markdown("<div style='height:28px'></div>",
                              unsafe_allow_html=True)
                if _sv2.button("Save", key="wl1_save_btn",
                               disabled=not ((_sname or "").strip() and _chosen)):
                    _nm = _sname.strip()
                    if len(_sl) >= _WR_MAX_SAVED and _nm not in _sl:
                        st.warning(f"{_WR_MAX_SAVED} saved lineups max — delete "
                                   "one first.")
                    else:
                        from datetime import date as _date
                        _sl[_nm] = {"team_id": int(_t), "gender": gender,
                                    "season": str(season_pick),
                                    "pids": [int(p) for p in _chosen],
                                    "saved": _date.today().isoformat()}
                        _wr_blob_save("wr_saved_lineups", _sl)
                        st.toast(f"Saved '{_nm}'", icon="💾")
                        st.rerun()
                _snames = [nm for nm, d in sorted(_sl.items())
                           if d.get("gender") in (None, gender)]
                if not _snames:
                    st.caption("No saved lineups yet — pick a five above, name "
                               "it, Save. They're yours (per coach) and follow "
                               "you across devices.")
                else:
                    _lc1, _lc2, _lc3 = st.columns([3, 1, 1])
                    _slpick = _lc1.selectbox(
                        "Saved", _snames, key="wl1_saved_pick",
                        format_func=lambda nm: (
                            f"{nm} — {team_short(name_of.get(_sl[nm].get('team_id'), '?'))}"
                            f" · {len(_sl[nm].get('pids') or [])} players"
                            f" · {_sl[nm].get('saved', '')}"),
                        label_visibility="collapsed")

                    def _wl1_do_load(nm, _blob=_sl):
                        st.session_state["_wl1_load"] = _blob.get(nm)

                    _lc2.button("Load", key="wl1_load_btn",
                                on_click=_wl1_do_load, args=(_slpick,))
                    if _lc3.button("Delete", key="wl1_del_btn"):
                        _sl.pop(_slpick, None)
                        _wr_blob_save("wr_saved_lineups", _sl)
                        st.rerun()
            # ⚡ engine-built preset fives — top 5 by each lens, auto-rated. Gated
            # like the projection itself (own team on any Paid plan; another team
            # is Co-op only), so it never leaks another team's depth.
            if _can_team(AUTH.current_user(), _t):
                def _use_preset(pids):
                    st.session_state["wl1_pick"] = list(pids)
                with st.expander("⚡ Preset lineups — the best five for each lens"):
                    _presets = TA.preset_lineups(
                        _rows, _wl_ctx(gender, season_pick), _t,
                        spacing_map=_wl_player_spacing(gender, season_pick))
                    if not _presets:
                        st.caption("Need at least 5 rated players to build presets.")
                    for _i, _pz in enumerate(_presets):
                        _pp = _pz.get("pred") or {}
                        _netv = (f"{_pp['NetRtg']:+.1f}"
                                 if _pp.get("NetRtg") is not None else "—")
                        _ortv = (f"{_pp['ORtg']:.0f}"
                                 if _pp.get("ORtg") is not None else "—")
                        _drtv = (f"{_pp['DRtg']:.0f}"
                                 if _pp.get("DRtg") is not None else "—")
                        _pc1, _pc2 = st.columns([5, 1])
                        with _pc1:
                            st.markdown(
                                f"<div style='margin-bottom:2px'><b>"
                                f"{' / '.join(_pz['labels'])}</b> "
                                f"<span style='color:#8b949e;font-size:12px'>proj "
                                f"Net {_netv} · ORtg {_ortv} · DRtg {_drtv}</span>"
                                f"<br><span style='font-size:13px'>"
                                + " · ".join(f"#{x['num']} {x['name']}"
                                             for x in _pz["players"])
                                + "</span></div>", unsafe_allow_html=True)
                        with _pc2:
                            st.button("Use", key=f"wl1_use_{_i}",
                                      on_click=_use_preset,
                                      args=([x["pid"] for x in _pz["players"]],))
                    if _presets:
                        st.caption("Each five = the roster's top 5 by that lens, run "
                                   "through the same projection as the manual pick. "
                                   "Sorted by projected Net; identical fives merge "
                                   "their labels. Tap **Use** to load one above.")
            if _chosen and not _can_team(AUTH.current_user(), _t):
                st.info("🔒 Lineup projections & observed-together ratings for "
                        "another team are a **Coaches' Co-op** feature — your own "
                        "team works on any Paid plan. Go **League-wide** in Settings "
                        "to build & scout any team's lineups. Share to scout.")
            elif _chosen:
                _pred = TA.lineup_prediction(_rows, _chosen, _ctxd, _t)
                _m = st.columns(5)
                _m[0].metric("Proj ORtg", f"{_pred['ORtg']:.1f}"
                             if _pred["ORtg"] is not None else "—")
                _m[1].metric("Proj DRtg", f"{_pred['DRtg']:.1f}"
                             if _pred["DRtg"] is not None else "—")
                _tn = _pred["league"].get("team_net")
                _nd = (f"{_pred['NetRtg'] - _tn:+.1f} vs team"
                       if _tn is not None and _pred["NetRtg"] is not None else None)
                _m[2].metric("Proj Net", f"{_pred['NetRtg']:+.1f}"
                             if _pred["NetRtg"] is not None else "—", _nd)
                _m[3].metric("Proj score", _pred["score_line"])
                _m[4].metric("League rank",
                             f"#{_pred['league']['rank']} / {_pred['league']['of']}")
                _gids = [gr["id"] for gr in query(
                    "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) "
                    "AND tracked=1 AND season=?", (_t, _t, season_pick))]
                # AXIS-2 read-filter: a League-wide coach scouting another team
                # sees its observed lineups only over that team's POOLED games.
                _ovis = ENT.team_visible_tracked_ids(AUTH.current_user(), _t)
                if _ovis is not None:
                    _gids = [g for g in _gids if g in _ovis]
                _obs = LU.custom_unit(_t, list(_chosen), game_ids=_gids) if _gids else None
                if _obs and _obs.get("poss", 0) >= 40:
                    st.markdown("**Observed together — tracked games**")
                    _oc = st.columns(4)
                    _oc[0].metric("Net / 100", f"{_obs['Net']:+.1f}")
                    _oc[1].metric("ORtg", f"{_obs['ORtg']:.1f}")
                    _oc[2].metric("DRtg", f"{_obs['DRtg']:.1f}")
                    _oc[3].metric("Possessions", f"{_obs['poss']:.0f}")
                elif _obs and _obs.get("poss"):
                    st.caption(f"Only {_obs['poss']:.0f} possessions together so far — "
                               "need ~40 for a reliable observed Net. Keep tracking.")
                else:
                    st.caption("This five hasn't shared the floor in tracked games "
                               "— no observed rating.")
                _cb = _pred.get("contrib") or []
                if _cb:
                    st.markdown("**Who drives the projection**")
                    _sca = go.Figure(go.Scatter(
                        x=[c["off_pts100"] for c in _cb],
                        y=[c["def_z"] for c in _cb], mode="markers+text",
                        text=[f"#{c['number']}" for c in _cb],
                        textposition="top center",
                        marker=dict(
                            size=[max(12, c["usg_share"] * 90) for c in _cb],
                            color=[c["off_pts100"] for c in _cb],
                            colorscale=HEAT, showscale=False,
                            line=dict(width=1, color="#30363d")),
                        hovertext=[c["name"] for c in _cb],
                        hovertemplate="%{hovertext}<br>Off/100 %{x:.1f} · "
                                      "Def z %{y:.2f}<extra></extra>"))
                    _sca.add_hline(y=0, line=dict(color="#30363d", dash="dot"))
                    _sca.update_xaxes(title="Offensive points / 100 contributed")
                    _sca.update_yaxes(title="Defensive z (higher = better)")
                    _style(_sca, 340)
                    st.plotly_chart(_sca, width="stretch", key="wl1_contrib")
                _render_proj_statline(_pred, _ctxd, _tbl, "wl1_proj_tbl")
                # ── win-formula read — the ONE lineup engine (lineup_projection):
                # the same numbers the Rotation optimizer, Compare view and the
                # Team Dashboard Projection tab show for this five.
                if len(_chosen) == 5:
                    _lpc = _lp_ctx(gender, _t, season_pick,
                                   _vis_tuple(AUTH.current_user(), _t))
                    if not _lpc.get("gated"):
                        _lu5 = LP.project_lineup(_t, list(_chosen), _lpc,
                                                 game_ids=_lpc.get("game_ids"))
                        _hit, _tot = LP.goals_hit(_lu5["line"],
                                                  _lpc.get("goals", []))
                        st.markdown("**Win-formula read — this five**")
                        _wf = st.columns(4)
                        _wf[0].metric(
                            "Net /100 (blended)", f"{_lu5['net_blended']:+.1f}",
                            help="Projected intrinsic rates, blended with the "
                                 "five's observed possessions together.")
                        _wf[1].metric("ORtg / DRtg",
                                      f"{_lu5['ortg']:.0f} / {_lu5['drtg']:.0f}")
                        _wf[2].metric(
                            "Signature stats hit",
                            f"{_hit} / {_tot}" if _tot else "—",
                            help="The ~4 stats this team's wins and losses "
                                 "actually turn on (Insights win/loss miner).")
                        _wf[3].metric("Obs. poss together",
                                      f"{_lu5['obs_unit_poss']:.0f}")
                        if st.button("➕ Send this five to Compare",
                                     key="wl1_addcmp"):
                            _add_cmp(_t, tuple(sorted(_chosen)))
                            st.success("Saved — open **Compare** above to see "
                                       "the give and take vs your other fives.")
                        st.caption(
                            "Same engine as the Rotation optimizer, the Compare "
                            "view and the Team Dashboard Projection tab — one "
                            "set of numbers everywhere. (The league-calibrated "
                            "metrics above rank this five vs the league; this "
                            "read scores it against your own win formula.)")
                    else:
                        st.caption("Win-formula read needs a rotation sample — "
                                   f"{_lpc['gated']}.")
                _bench = [r for r in _rows if r["_pid"] not in _chosen]
                if _bench and len(_chosen) == 5 and _pred["NetRtg"] is not None:
                    _base = _pred["NetRtg"]
                    _swaps = []
                    for _out in _chosen:
                        for _bp in _bench:
                            _nw = [_bp["_pid"] if x == _out else x for x in _chosen]
                            _nn = _lineup_net(gender, _t, tuple(_nw), season_pick)
                            if _nn is not None:
                                _swaps.append((_nn - _base, _out, _bp))
                    # +0.3 Net floor: below that a swap is inside projection noise
                    # for these small tracked samples (was 0.05 → false positives).
                    _ups = sorted([sw for sw in _swaps if sw[0] > 0.3],
                                  key=lambda sw: -sw[0])[:3]
                    _nmap = {r["_pid"]: r for r in _rows}
                    st.markdown("**Best bench swaps**")
                    if _ups:
                        for _d, _out, _bp in _ups:
                            _o = _nmap[_out]
                            st.markdown(f"- **+{_d:.1f} Net** — sub in "
                                        f"{_PLBL(_bp)} for {_PLBL(_o)}")
                    else:
                        st.caption("No bench swap improves this five — it's the "
                                   "team's best available unit.")
                for _f in _pred.get("flags", []):
                    st.caption(_f)
    else:
        st.caption(
            "Build any five — from one team or across the whole league. Filter the "
            "pool, pick up to five, and get a unit blended from each player's 0-100 "
            "ratings and per-game production. If all five are from one team, their "
            "observed on-court net from tracked games is shown too.")

        _pool = _league_pool(season_pick)
        _fc = st.columns(4)
        _gsel = _fc[0].multiselect(
            "Gender", ["F", "M"], format_func=gender_label, key="wl_g")
        _dsel = _fc[1].multiselect(
            "District", sorted({r["district"] for r in _pool if r["district"]}),
            key="wl_d")
        _csel = _fc[2].multiselect(
            "Class", sorted({r["class"] for r in _pool if r["class"]}), key="wl_c")
        _tsel = _fc[3].multiselect(
            "Team", sorted({r["team"] for r in _pool}), key="wl_t")
        _filt = [r for r in _pool
                 if (not _gsel or r["gender"] in _gsel)
                 and (not _dsel or r["district"] in _dsel)
                 and (not _csel or r["class"] in _csel)
                 and (not _tsel or r["team"] in _tsel)]
        _idx = {r["pid"]: r for r in _filt}

        def _wl_label(pid):
            r = _idx[pid]
            ov = f" · OVR {r['OVERALL']:.0f}" if r["OVERALL"] is not None else ""
            return f"{r['name']} · {r['team']}{ov}"

        _pick = st.multiselect("Players (pick up to 5)", list(_idx),
                               format_func=_wl_label, max_selections=5, key="wl_pick")
        if not _pick:
            st.caption("Choose players above to build a unit. Tip: filter Team to one "
                       "team to build that team's five; leave filters open to mix "
                       "anyone in the league.")
        else:
            _sel = [_idx[p] for p in _pick]

            def _avg(k):
                vs = [r[k] for r in _sel if r[k] is not None]
                return sum(vs) / len(vs) if vs else None

            def _tot(k):
                return sum(r[k] or 0 for r in _sel)

            _rc = st.columns(5)
            for _col, (_lbl, _k) in zip(_rc, [
                    ("Overall", "OVERALL"), ("Offense", "OFFENSE"),
                    ("Defense", "DEFENSE"), ("Playmaking", "PLAYMAKING"),
                    ("Rebounding", "REBOUNDING")]):
                _v = _avg(_k)
                _col.metric(_lbl, f"{_v:.0f}" if _v is not None else "—")
            _pcols = st.columns(4)
            _pcols[0].metric("Combined PPG", f"{_tot('PPG'):.1f}")
            _pcols[1].metric("Combined RPG", f"{_tot('RPG'):.1f}")
            _pcols[2].metric("Combined APG", f"{_tot('APG'):.1f}")
            _pcols[3].metric("Teams in unit", len({r["team"] for r in _sel}))

            _cats = ["OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]
            _rad = go.Figure(go.Scatterpolar(
                r=[_avg(k) or 0 for k in _cats] + [_avg(_cats[0]) or 0],
                theta=[c.title() for c in _cats] + [_cats[0].title()],
                fill="toself", line=dict(color=ACCENT)))
            _rad.update_layout(polar=dict(radialaxis=dict(range=[0, 100])),
                               showlegend=False)
            _style(_rad, 330)
            st.plotly_chart(_rad, width="stretch", key="wl_radar")

            st.dataframe(pd.DataFrame([{
                "Player": r["name"], "Team": r["team"], "Class": r["class"],
                "OVR": round(r["OVERALL"]) if r["OVERALL"] is not None else None,
                "PPG": round(r["PPG"], 1) if r["PPG"] is not None else None,
                "RPG": round(r["RPG"], 1) if r["RPG"] is not None else None,
                "APG": round(r["APG"], 1) if r["APG"] is not None else None,
            } for r in _sel]), hide_index=True, width="stretch", key="wl_tbl")

            # ── Projected unit — vs an average team (mirrors the One-team tab) ────
            # League-wide ratings are already visible to this (League-wide) viewer,
            # so the cross-team five earns the SAME possession-calibrated projection
            # the One-team tab gives: ORtg/DRtg/Net, an estimated score vs an average
            # team (league pace, team_id=None), and a predicted per-player stat line.
            # The five is normalised to its own SC/A operating point (it's its own
            # "team"). Needs one gender — calibration ctx is per-gender and you never
            # field a cross-gender five.
            _genders = {r["gender"] for r in _sel}
            if len(_genders) == 1:
                _g1 = next(iter(_genders))
                _ft = _wl_table(_g1, season_pick)
                _prows = [dict(_ft[p], _pid=p) for p in _pick if p in _ft]
                if _prows:
                    _pred = TA.lineup_prediction(_prows, _pick, _wl_ctx(_g1, season_pick),
                                                 team_id=None)
                    st.markdown("**Projected unit — vs an average team**")
                    _pm = st.columns(5)
                    _pm[0].metric("Proj ORtg", f"{_pred['ORtg']:.1f}"
                                  if _pred["ORtg"] is not None else "—")
                    _pm[1].metric("Proj DRtg", f"{_pred['DRtg']:.1f}"
                                  if _pred["DRtg"] is not None else "—")
                    _pm[2].metric("Proj Net", f"{_pred['NetRtg']:+.1f}"
                                  if _pred["NetRtg"] is not None else "—")
                    _pm[3].metric("Proj score", _pred["score_line"])
                    _pm[4].metric("League rank",
                                  f"#{_pred['league']['rank']} / "
                                  f"{_pred['league']['of']}")
                    _render_proj_statline(_pred, _wl_ctx(_g1, season_pick), _ft, "wl_proj_tbl")
                    for _f in _pred.get("flags", []):
                        st.caption(_f)
            else:
                st.caption("Cross-gender five — the projection needs one gender; the "
                           "ratings averages above still apply.")

            _teams = {r["team_id"] for r in _sel}
            # Observed-together = real on-court lineup chemistry for one team →
            # own team (any Paid) or another team only via the league pool.
            _one_tid = next(iter(_teams)) if len(_teams) == 1 else None
            if (_one_tid is not None and len(_sel) >= 2
                    and _can_team(AUTH.current_user(), _one_tid)):
                _tid = _one_tid
                _gids = [g["id"] for g in query(
                    "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) "
                    "AND tracked=1 AND season=?", (_tid, _tid, season_pick))]
                # AXIS-2 read-filter: scouting another team → its pooled games only.
                _ovis = ENT.team_visible_tracked_ids(AUTH.current_user(), _tid)
                if _ovis is not None:
                    _gids = [g for g in _gids if g in _ovis]
                _obs = LU.custom_unit(_tid, [r["pid"] for r in _sel],
                                      game_ids=_gids) if _gids else None
                if _obs and _obs.get("poss", 0) >= 40:
                    st.markdown("**Observed together — tracked games**")
                    _oc = st.columns(4)
                    _oc[0].metric("Net / 100", f"{_obs['Net']:+.1f}")
                    _oc[1].metric("ORtg", f"{_obs['ORtg']:.1f}")
                    _oc[2].metric("DRtg", f"{_obs['DRtg']:.1f}")
                    _oc[3].metric("Possessions", f"{_obs['poss']:.0f}")
                elif _obs and _obs.get("poss"):
                    st.caption(f"Only {_obs['poss']:.0f} possessions together so far — "
                               "need ~40 for a reliable observed Net. Keep tracking.")
                else:
                    st.caption("This five hasn't shared the floor in tracked games — no "
                               "observed rating.")
            st.caption("Unit ratings = averaged 0-100 ratings + summed per-game "
                       "production. Observed net needs the five to have actually played "
                       "together (one team, tracked games); cross-team fives are a "
                       "ratings projection only.")


# ── LINEUPS · ROTATION OPTIMIZER — the full lab (deep sibling of the Team
# Dashboard's light Projection tab; same renderer module, same engine).
if _wrview == "Lineups" and _lu_view == "Rotation optimizer":
    st.markdown("#### Rotation optimizer — the minutes that hit your win formula")
    _t_opt = _wr_team_pick("wropt_team")
    if _t_opt is not None:
        if not _can_team(AUTH.current_user(), _t_opt):
            st.info("🔒 Another team's rotation projection is a **Coaches' Co-op** "
                    "feature — your own team works on any Paid plan. Go "
                    "**League-wide** in Settings to project any team.")
        else:
            from types import SimpleNamespace as _NS
            _ovt = _vis_tuple(AUTH.current_user(), _t_opt)
            _ht = (bool(_ovt) if _ovt is not None else bool(query(
                "SELECT 1 FROM games WHERE (team1_id=? OR team2_id=?) "
                "AND tracked=1 AND season=? LIMIT 1",
                (_t_opt, _t_opt, season_pick))))
            DPROJ.render_deep(_NS(
                team_id=_t_opt, gender=gender, is_paid=True, has_tracked=_ht,
                game_ids=(list(_ovt) if _ovt is not None else None),
                season=season_pick))


# ── LINEUPS · COMPARE — the give and take between candidate fives ─────────────
@st.fragment
def _render_compare():
    st.markdown("#### Compare lineups — the give and take")
    st.caption(
        "Project candidate fives with the SAME engine as the optimizer and see "
        "what each one buys and what it pays: the three-point-heavy five might "
        "shoot +4 3P% but give up 5 ORB% — or land barely under your best five, "
        "which is exactly the read that lets you trust it.")
    _cu = AUTH.current_user()
    _t = _wr_team_pick("wrcmp_team")
    if _t is None:
        return
    if not _can_team(_cu, _t):
        st.info("🔒 Another team's lineup projections are a **Coaches' Co-op** "
                "feature — your own team works on any Paid plan.")
        return
    _lpc = _lp_ctx(gender, _t, season_pick, _vis_tuple(_cu, _t))
    if _lpc.get("gated"):
        empty_state("Not enough tracked games to project lineups",
                    f"{_lpc['gated']}. Keep tracking — the comparison needs a "
                    "real rotation sample.", icon="📉")
        return
    _tbl = _wl_table(gender, season_pick)

    def _lab(pid):
        r = _tbl.get(pid, {})
        num = r.get("number")
        nm = _lpc["players"].get(pid, {}).get("name") or r.get("name", str(pid))
        return f"#{num} {nm}" if num is not None else nm

    _pickable = sorted(_lpc["players"],
                       key=lambda p: -_lpc["players"][p]["obs_min"])
    ac1, ac2 = st.columns([5, 1], vertical_alignment="bottom")
    _new5 = ac1.multiselect("Build a five to add", _pickable, format_func=_lab,
                            max_selections=5, key=f"wrcmp_pick_{_t}")
    if ac2.button("➕ Add", key=f"wrcmp_add_{_t}", disabled=len(_new5) != 5):
        _add_cmp(_t, tuple(sorted(_new5)))
    sc1, sc2 = st.columns(2)
    if len(_pickable) >= 5 and sc1.button(
            "Add: most-used five (observed minutes)", key=f"wrcmp_top_{_t}"):
        _add_cmp(_t, tuple(sorted(_pickable[:5])))
    if sc2.button("Add: optimizer's five (top recommended minutes)",
                  key=f"wrcmp_opt_{_t}"):
        _o = LP.optimize_minutes(_t, ctx=_lpc)
        _add_cmp(_t, tuple(sorted(sorted(
            _o["minutes"], key=lambda p: -_o["minutes"][p])[:5])))

    _saved = st.session_state.get(_cmp_key(_t), [])
    if not _saved:
        st.caption("No lineups saved yet — build a five above, load a shortcut, "
                   "or send one over from the **Creator** view.")
        return

    projs = []
    for five in _saved:
        _lu = LP.project_lineup(_t, list(five), _lpc,
                                game_ids=_lpc.get("game_ids"))
        _h, _n = LP.goals_hit(_lu["line"], _lpc.get("goals", []))
        projs.append((five, _lu, _h, _n))
    best_i = max(range(len(projs)), key=lambda i: projs[i][1]["net_blended"])
    best_net = projs[best_i][1]["net_blended"]
    best_line = projs[best_i][1]["line"]

    _p1 = lambda v: round(v * 100, 1) if v is not None else None
    rows = []
    for i, (five, _lu, _h, _n) in enumerate(projs):
        ln = _lu["line"]
        rows.append({
            "": f"L{i + 1}" + (" ★" if i == best_i else ""),
            "Lineup": " · ".join(_lab(p) for p in five),
            "Net": _lu["net_blended"],
            "Δ best": round(_lu["net_blended"] - best_net, 1),
            "ORtg": _lu["ortg"], "DRtg": _lu["drtg"],
            "eFG%": _p1(ln["eFG"]), "3P%": _p1(ln["3P%"]),
            "TOV%": _p1(ln["TOVr"]), "ORB%": _p1(ln["ORBpct"]),
            "opp eFG%": _p1(ln["oeFG"]), "Forced TO%": _p1(ln["forced"]),
            "Sig": f"{_h}/{_n}" if _n else "—",
            "Obs poss": _lu["obs_unit_poss"],
        })
    st.dataframe(_style_df(pd.DataFrame(rows), grad_cols=["Net"],
                           signed_cols=["Δ best"]),
                 hide_index=True, width="stretch", key=f"wrcmp_tbl_{_t}")
    st.caption("★ = best projected Net (blended with each five's observed "
               "possessions together). **Sig** = how many of your ~4 signature "
               "win/loss stats the five projects to hit. Offensive rates are "
               "projected intrinsic rates; defensive rates are your observed "
               "line nudged by the five's defenders — directional, not a "
               "promise.")

    st.markdown("**Each five vs the best — what it buys, what it pays**")
    for i, (five, _lu, _h, _n) in enumerate(projs):
        if i == best_i:
            st.markdown(f"- **L{i + 1}** — the benchmark: best projected Net "
                        f"({best_net:+.1f}).")
            continue
        edges = LP.compare_lines(_lu["line"], best_line)
        gains = [e for e in edges if e["good"]][:2]
        costs = [e for e in edges if not e["good"]][:2]
        dnet = _lu["net_blended"] - best_net
        verdict = (f"within {abs(dnet):.1f} Net of the best — close enough to "
                   "trust when the matchup calls for it"
                   if abs(dnet) < 2.0 else f"{dnet:+.1f} Net vs the best")
        parts = []
        if gains:
            parts.append("buys " + " · ".join(_fmt_edge(e) for e in gains))
        if costs:
            parts.append("pays " + " · ".join(_fmt_edge(e) for e in costs))
        st.markdown(f"- **L{i + 1}** — {verdict}"
                    + (" — " + "; ".join(parts) if parts else "") + ".")

    with st.expander("✏️ Manage saved lineups"):
        for i, (five, _lu, _h, _n) in enumerate(projs):
            c1, c2 = st.columns([6, 1])
            c1.markdown(f"**L{i + 1}** — " + " · ".join(_lab(p) for p in five))
            if c2.button("✕", key=f"wrcmp_rm_{_t}_{i}"):
                st.session_state[_cmp_key(_t)].pop(i)
                st.rerun()
        if st.button("Clear all", key=f"wrcmp_clear_{_t}"):
            st.session_state[_cmp_key(_t)] = []
            st.rerun()


if _wrview == "Lineups" and _lu_view == "Compare":
    _render_compare()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — MATCHUP PLANNER  (who guards whom — opponent prep)
# ══════════════════════════════════════════════════════════════════════════════
# Deliberately NOT co-op-gated: it plans for YOUR team. Opponent OFFENSE ratings
# show only where you may already see that team's tracked depth; otherwise the
# planner runs off your own hand-entered Scout intel (Track A) — scouting an
# opponent you've never tracked, without surrendering film to the pool.
@st.fragment
def _render_planner():
    import helpers.scoutboard as SB
    st.subheader("Defensive assignments — who guards whom")
    st.caption("Assign each of your defenders to an opponent scorer and see the "
               "edge: your defender's DEFENSE vs their OFFENSE (0-100, 50 = league "
               "avg). Uses your tracked ratings, or hand-entered intel for a team "
               "you haven't tracked (add it on the Team Dashboard → Scout tab). "
               "Saved per opponent. The prep flow: **Matchup** projects it → the "
               "game plan picks the calls → assignments here → **Lineups** picks "
               "the five.")

    tbl = _wl_table(gender, season_pick)
    _id = AUTH.current_user()
    _my_ids = [t for t in (_id.get("team_ids")
                           or ([_id.get("team_id")] if _id.get("team_id") else []))
               if t in name_of]
    _my_default = _my_ids[0] if _my_ids else (order[0] if order else None)
    if _my_default is None:
        st.info("No rated teams yet."); return

    pc = st.columns(2)
    my_team = pc[0].selectbox(
        "Your team", order, index=order.index(_my_default),
        format_func=lambda t: name_of.get(t, str(t)), key="mp_my")
    opp_opts = [t for t in order if t != my_team]
    if not opp_opts:
        st.info("Need at least two rated teams to plan a matchup."); return
    opp = pc[1].selectbox("Opponent", opp_opts,
                          format_func=lambda t: name_of.get(t, str(t)), key="mp_opp")

    my_players = sorted(
        [dict(r, _pid=pid) for pid, r in tbl.items() if r["team_id"] == my_team],
        key=lambda r: -(r.get("DEFENSE") or 0))
    if not my_players:
        st.info("Your team has no rated players yet — track a game or enter a box "
                "score first."); return
    my_label = {p["_pid"]: f"#{p.get('number', '')} {p['name']}".strip()
                for p in my_players}
    my_def = {p["_pid"]: p.get("DEFENSE") for p in my_players}

    can_rate = _can_team(_id, opp)
    their = []
    if can_rate:
        their = sorted(
            [dict(r, _pid=pid) for pid, r in tbl.items()
             if r["team_id"] == opp
             and (r.get("OFFENSE") is not None or r.get("PPG") is not None)],
            key=lambda r: -(r.get("OFFENSE") or r.get("PPG") or 0))[:6]
    intel = SB.get_intel(opp)
    if not their and not intel:
        st.info("No rated players or hand-entered intel for this opponent yet. "
                "Add their key players on the **Team Dashboard → Scout** tab "
                "(Manual scouting), then plan here."); return

    plan = SB.get_plan(opp)
    new_plan = {}

    def _assign_row(key, label, off_rating, threat):
        cur = plan.get(key)
        opts = [None] + [p["_pid"] for p in my_players]
        idx = opts.index(cur) if cur in opts else 0
        c = st.columns([3, 3, 2])
        meta = (f" · OFF {off_rating:.0f}" if off_rating is not None else "")
        thr = (f"<br><span style='color:#b25e00;font-size:12px'>{threat}</span>"
               if threat else "")
        c[0].markdown(f"**{label}**{meta}{thr}", unsafe_allow_html=True)
        pick = c[1].selectbox(
            "Defender", opts, index=idx,
            format_func=lambda v: "—" if v is None else my_label.get(v, str(v)),
            key=f"mp_{opp}_{key}", label_visibility="collapsed")
        if pick is not None:
            new_plan[key] = pick
            d = my_def.get(pick)
            if d is not None and off_rating is not None:
                edge = d - off_rating
                tag = ("✅ Edge" if edge >= 8 else "⚠ Tough" if edge <= -8 else "Even")
                clr = (GOOD if edge >= 8 else BAD if edge <= -8 else "#8b949e")
                c[2].markdown(f"<span style='color:{clr};font-weight:700'>{tag} "
                              f"({edge:+.0f})</span>", unsafe_allow_html=True)
            else:
                c[2].markdown("<span style='color:#8b949e'>no edge rating</span>",
                              unsafe_allow_html=True)
        else:
            c[2].markdown("<span style='color:#8b949e'>unassigned</span>",
                          unsafe_allow_html=True)

    st.markdown("**Their scorers → your defender**")
    if their:
        for p in their:
            _assign_row(str(p["_pid"]),
                        f"#{p.get('number', '')} {p['name']}".strip(),
                        p.get("OFFENSE"), None)
    else:
        st.caption("No tracked ratings for this opponent — planning off your "
                   "hand-entered Scout intel.")
        for r in intel:
            nm = (r.get("name") or "").strip()
            _assign_row("name:" + nm,
                        f"#{r.get('num', '')} {nm}".strip(), None, r.get("note"))

    if st.button("Save matchup plan", key=f"mp_save_{opp}", type="primary"):
        SB.save_plan(opp, new_plan)
        st.success("Matchup plan saved.")


if _wrview == "Defensive assignments":
    _render_planner()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB — ANALYZE  (the self-serve analytics playground, folded in from the old
#  Data Explorer page: filter the full table, scatter anything, correlate, map shots)
# ══════════════════════════════════════════════════════════════════════════════
if _wrview == "Analyze":
    from helpers.dashboard.analyze import render as _render_analyze
    st.subheader("Analyze — the stat playground")
    _render_analyze(season=season_pick)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
if _wrview == "Glossary":
    glossary_tab("wr")
