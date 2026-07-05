"""
5_Rankings.py — the league-wide view: team rankings, deep dives and charts.

League-wide views (a lazy segmented_control — only the chosen view computes):
  • Overview    — the source of truth. Results-only "Score" power ratings for
                  every team, with Class / min-games filters that drive the team
                  leaders, signature metrics and the rankings table.
  • Compare     — two teams head-to-head: side-by-side metrics, past meetings,
                  predicted score and (tracked) the four-factor edge. Promoted to
                  #2 as the one genuine opponent-prep tool here.
  • Team        — the per-team deep dive (record, vs top 10, vs class, schedule,
                  percentile profile + tracked possession deep dive).
  • Tracked     — possession-based ratings over tracked games only (the full
                  tracked stat set), with a per-team tracked schedule that opens
                  the full box score.
  • League landscape — the cross-team analytics lab. An inner Section selector
                  folds in two former views: "Team Charts" (how teams score / win,
                  quarter breakdown, who can shoot, shot volume — per-team tracked
                  charts) and "League Lab" (whole-league landscape, tiers,
                  Pythagoras, momentum, win network). Only the chosen Section runs.
                  (Matchup predictions + sims live on the War Room page.)

All rating math lives in helpers/team_ratings.py; this page is display + controls.
"""
import sys
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.settings_utils import get_setting
from helpers.box_score import render_box_score
from helpers.ui import (page_chrome, style_fig as _style, q_label as _q_label,
                        AWAY, gender_radio, score_card, rank_chip, grid as _grid,
                        page_header, lab_hero as _lab_hero, empty_state,
                        seg as _rkseg, HEAT, DIVERGE)
import helpers.cards as CD
from helpers.cards import team_short
from helpers.glossary import glossary_tab
import helpers.team_ratings as TR
import helpers.predictor as PRED
import helpers.team_analytics as TA
import helpers.stats as S
import helpers.league_analytics as LA
import helpers.player_ratings as PR
import helpers.insights as INS
import helpers.playtypes as PT
import helpers.defenses as DEF
import helpers.player_edge as PE
from helpers.dashboard.player_edge import render as _render_edge
import helpers.wpa as WPA
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.seasons as SEAS

_cfg, ACCENT = page_chrome("Rankings")


def _paid_pool_lock():
    """Lock reason for a LEAGUE-WIDE tracked surface (the whole pool's possession
    data at once), or None if the viewer may see it. Needs Paid AND League-wide
    (the per-coach Coaches' Co-op toggle) — a Solo coach gets an INVITE to share,
    not a denial. See helpers.entitlement.viewer_is_league_wide.

    A PAST season is an open archive (last year's roster turned over) — no gate,
    so the whole league's tracked history is free to everyone."""
    if not SEAS.is_current(season_pick):
        return None
    _ident = AUTH.current_user()
    if not ENT.has_paid_plan(_ident):
        return ("🔒 Tracked league analytics — possession ratings, four factors "
                "and the advanced charts — are a **Paid** feature. Upgrade to "
                "unlock.")
    if not ENT.viewer_is_league_wide(_ident):
        return (ENT.MSG_POOL_BANNED if ENT.is_pool_banned(_ident)
                else ENT.MSG_COOP_INVITE)
    return None


def _archive_note():
    """Note for a CURRENT-season-only pooled surface when a PAST season is picked,
    else None. The league-wide tag / edge engines (play type, defense, player edge,
    excitement, by-game-type) aren't partitioned per season, so an archive view
    shows this note instead of silently serving the CURRENT season's data under a
    past-season header. Mirrors the Team Dashboard rule (tag tabs are current-only).
    Used as `_archive_note() or _paid_pool_lock()` so past short-circuits the lock."""
    if _is_cur_season:
        return None
    return ("🗄️ This view is **current-season only** — the league-wide play-type, "
            "defense and player-edge tables aren't archived per season yet. Switch "
            "back to the current season to see them. (Rankings, records, tracked "
            "efficiency and the KenPom map DO show the archived season.)")

# futuristic-lab palette (mirrors the Team Analytics advanced layer)
GOOD = "#3fb950"
BAD = "#e74c3c"
BLUE = "#58a6ff"
PURPLE = "#bc8cff"
CYBER = "#00e5ff"
GREY = "#8b949e"
PINK = "#ff5db1"
GOLD = "#f0a500"
TIER_PALETTE = ["#00e5ff", "#3fb950", "#58a6ff", "#f0a500", "#8b949e"]

# tier ladder — single source for _tier() and the Power-tiers caption
TIER_CUTS = [("S · ELITE", 70, "#00e5ff"),
             ("A · CONTENDER", 62, "#3fb950"),
             ("B · SOLID", 54, "#58a6ff"),
             ("C · MIDDLING", 46, "#f0a500")]
TIER_FLOOR = ("D · REBUILDING", "#e74c3c")


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _team_results(team_id):
    """Completed games for a team, oldest first. team1 = home, team2 = away.
    Scoped to the page's selected season (`season_pick` — 'Current' or an archive
    label)."""
    rows = query(
        """SELECT g.id, g.date, g.location, g.tracked,
                  g.team1_id, g.team2_id, g.home_score, g.away_score
           FROM games g
           WHERE (g.team1_id=? OR g.team2_id=?)
             AND g.season=?
             AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
           ORDER BY g.date, g.id""",
        (team_id, team_id, season_pick))
    out = []
    for g in rows:
        if g["team1_id"] == team_id:
            pf, pa, opp, site = g["home_score"], g["away_score"], g["team2_id"], "vs"
        else:
            pf, pa, opp, site = g["away_score"], g["home_score"], g["team1_id"], "@"
        out.append({"game_id": g["id"], "date": g["date"], "opp": opp,
                    "site": site, "pf": pf, "pa": pa, "won": pf > pa,
                    "tracked": g["tracked"]})
    return out


def _team_streak(results):
    """Current W/L streak string (e.g. 'W3') from oldest-first results."""
    if not results:
        return ""
    last = results[-1]["won"]
    n = 0
    for g in reversed(results):
        if g["won"] == last:
            n += 1
        else:
            break
    return ("W" if last else "L") + str(n)


def _vs_topn(results, topn_set):
    """(wins, losses) against teams in topn_set."""
    w = sum(1 for g in results if g["won"] and g["opp"] in topn_set)
    l = sum(1 for g in results if not g["won"] and g["opp"] in topn_set)
    return w, l


def _filter_rows(rows, key=None):
    """Filter rows by the PAGE-LEVEL Class + min-games selection (set once at the
    top of the page — see _PICKED_CLASSES / _MIN_GP). No longer renders its own
    widgets; `key` is accepted for backward-compat and ignored."""
    return [r for r in rows
            if r["class"] in _PICKED_CLASSES and r["GP"] >= _MIN_GP]


# ── futuristic-lab UI helpers ─────────────────────────────────────────────────

def _lab_hdr(text):
    """Neon section header (the cyber look from Team Analytics)."""
    st.markdown(f"<div class='lab-hdr'>{text}</div>", unsafe_allow_html=True)


def _tier(power):
    """Power 0-100 → (tier name, color). 50 = league average on the z-scale.

    Band edges (TIER_CUTS) match the player OVERALL ladder (helpers.cards.tier)
    so "elite/great/above-average/average" mean the same number on both scales.
    """
    if power is None:
        return "—", GREY
    for name, cut, clr in TIER_CUTS:
        if power >= cut:
            return name, clr
    return TIER_FLOOR


def _pctile_color(pct):
    """Percentile (0-100) → quartile color."""
    if pct is None:
        return GREY
    if pct >= 75:
        return GOOD
    if pct >= 50:
        return BLUE
    if pct >= 25:
        return GOLD
    return BAD


def _pctile_bar(label, val_txt, pct):
    """One HTML percentile bar row (reuses the global .pctile-* classes)."""
    clr = _pctile_color(pct)
    width = 0 if pct is None else max(2, pct)
    rank_txt = "—" if pct is None else f"{pct:.0f}th"
    return (
        f"<div class='pctile-row'><div class='pctile-label-row'>"
        f"<span class='pctile-stat'>{label}</span>"
        f"<span><span class='pctile-val'>{val_txt}</span> "
        f"<span class='pctile-rank' style='color:{clr}'>{rank_txt}</span></span>"
        f"</div><div class='pctile-track'>"
        f"<div class='pctile-fill' style='width:{width}%;background:{clr}'></div>"
        f"</div></div>")


@st.cache_data(ttl=600, show_spinner=False)
def _team_tracked_deep(team_id, vis=None, season="Current"):
    """Possession-based tracked deep dive for one team — None if no tracked games.

    Mirrors (and extends) APP3's 'Team Deep Dive': pace-adjusted ratings, the
    four factors on both ends, a per-period PPG/PPP table and a per-game
    efficiency log that drives the win/loss pattern charts. Everything is built
    from tracked play-by-play, so it is a small, directional sample.

    `vis` (tuple of game ids, or None) is the AXIS-2 read-filter: None for own
    team / admin (full depth); a League-wide scout passes the team's POOLED games.
    """
    game_log = TA.team_game_log(team_id, season=season)
    tracked_ids = [g["game_id"] for g in game_log if g["tracked"]]
    if vis is not None:
        _vis = set(vis)
        tracked_ids = [gid for gid in tracked_ids if gid in _vis]
    if not tracked_ids:
        return None
    events = S.fetch_events(tracked_ids)
    tb, ob = TA.team_and_opp_box(team_id, tracked_ids, events=events)
    gp = len(tracked_ids)
    rt = S.team_ratings(team_id, None, tracked_ids)
    off_poss = rt.get("off_poss") or 0.0
    def_poss = rt.get("def_poss") or 0.0
    ff = TA.four_factors(tb, ob)

    qb = TA.quarter_boxes(team_id, tracked_ids, events=events)

    def _pack(qs):
        tp = sum(qb[q]["team"]["PTS"] for q in qs if q in qb)
        op = sum(qb[q]["opp"]["PTS"] for q in qs if q in qb)
        tposs = sum(qb[q]["poss"] for q in qs if q in qb)
        oposs = sum(qb[q]["opp_poss"] for q in qs if q in qb)
        ng = max((qb[q]["n_games"] for q in qs if q in qb), default=0) or gp
        return {"tppg": tp / ng if ng else 0.0, "oppg": op / ng if ng else 0.0,
                "tppp": tp / tposs if tposs else 0.0,
                "oppp": op / oposs if oposs else 0.0}

    periods = [{"Period": lbl, **_pack(qs)} for lbl, qs in
               [("Q1", [1]), ("Q2", [2]), ("H1", [1, 2]),
                ("Q3", [3]), ("Q4", [4]), ("H2", [3, 4])]]
    periods.append({
        "Period": "Full Game",
        "tppg": tb["PTS"] / gp if gp else 0.0,
        "oppg": ob["PTS"] / gp if gp else 0.0,
        "tppp": tb["PTS"] / off_poss if off_poss else 0.0,
        "oppp": ob["PTS"] / def_poss if def_poss else 0.0})

    return {
        "gp": gp,
        "ortg": rt["ORtg"], "drtg": rt["DRtg"], "net": rt["NetRtg"],
        "ppp": tb["PTS"] / off_poss if off_poss else 0.0,
        "oppp": ob["PTS"] / def_poss if def_poss else 0.0,
        "pace": (off_poss + def_poss) / 2 / gp if gp else 0.0,
        "efg": S.efg(tb), "oefg": S.efg(ob), "ts": S.ts(tb), "ots": S.ts(ob),
        "paint": S.paint_fg_pct(tb),
        "tov": ff["off"]["TOV"], "ftov": ff["def"]["TOV"], "oreb": ff["off"]["ORB"],
        "dreb": (tb["DRB"] / (tb["DRB"] + ob["ORB"])
                 if (tb["DRB"] + ob["ORB"]) else 0.0),
        "ftr": tb["FTA"] / tb["FGA"] if tb["FGA"] else 0.0,
        "periods": periods,
        "trend": TA.per_game_metrics(team_id, game_log, events=events),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE HEADER + GENDER
# ══════════════════════════════════════════════════════════════════════════════

_lab_hero("Rankings", phase="ANALYZE",
          sub="Opponent-adjusted power, résumé and possession analytics "
              "across the whole league — results power every team, tracked "
              "games add the deep layer.")

gender = gender_radio()

# Season picker — view a past/archived season's rankings. Only appears once a
# season has been rolled over (archived labels exist); the active season is the
# default, so the page is byte-identical when no archive exists. A PAST season is
# an OPEN ARCHIVE (no entitlement gate — see _paid_pool_lock + _VIS below), the
# same rule the Team Dashboard follows. season_pick is a module global the page
# helpers read.
_season_opts = SEAS.season_options()
if len(_season_opts) > 1:
    _slbl = st.selectbox(
        "Season", [l for _v, l in _season_opts], key="rk_season",
        help="View a past season's rankings. Past seasons are an open archive — "
             "free, full depth, to everyone.")
    season_pick = next(v for v, l in _season_opts if l == _slbl)
else:
    season_pick = SEAS.ACTIVE
_is_cur_season = SEAS.is_current(season_pick)

@st.cache_resource(show_spinner=False)
def _score_ratings_fp(g, season, _fp):
    # cache_resource survives the app-wide st.cache_data.clear() on every write;
    # keyed on the results fingerprint so the ~0.5s league rating recomputes only
    # when a score moves. Read-only output → safe to share. `season` partitions
    # the cache so an archive view never serves the active season's ratings.
    return TR.score_ratings(gender=g, season=season)


def _score_ratings(g, season="Current"):
    return _score_ratings_fp(g, season, TR.results_fingerprint())


@st.cache_data(ttl=600, show_spinner=False)
def _tracked_ratings(g, vis=None, season="Current"):
    # `vis` (tuple of game ids, or None) is the AXIS-2 read-filter: the whole
    # tracked surface here is league-wide, so it aggregates only games the viewer
    # may see (None = admin/local = all; a League-wide coach = the pooled set).
    # `season` scopes to the active season (default) or an archive label.
    return TR.tracked_ratings(gender=g,
                              game_ids=(set(vis) if vis is not None else None),
                              season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _adj_shoot(g, vis=None, season="Current"):
    """Opponent-adjusted eFG per team (helpers/adj_efficiency) — closes the
    KenPom gap for SHOOTING (ORtg/DRtg/PPP were already schedule-adjusted by
    tracked_ratings). Same AXIS-2 pool scope as the tracked ratings."""
    import helpers.adj_efficiency as AE
    try:
        return AE.adjusted_shooting(
            g, game_ids=(set(vis) if vis is not None else None), season=season)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _form_stats(g, season="Current"):
    return LA.team_form_stats(gender=g, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _tracked_pack(g, _tracked, vis=None, season="Current"):
    return LA.team_tracked_pack(gender=g, tracked=_tracked,
                                game_ids=(set(vis) if vis is not None else None),
                                season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _win_net(g, _scored, season="Current"):
    return LA.win_network(gender=g, scored=_scored, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _runs_table(g, vis=None, season="Current"):
    """League scoring-run profiles (helpers/runs.py) over the viewer's tracked
    pool — 10-0 runs made / allowed per game, records by run count."""
    import helpers.runs as RN
    gids = (list(vis) if vis is not None
            else SEAS.game_pool(season=season, gender=g, tracked_only=True,
                                finished_only=False))
    if not gids:
        return {}
    return RN.league_run_table(events=S.fetch_events(gids))


@st.cache_data(ttl=600, show_spinner=False)
def _team_stat_rows(g, _tracked, _pack, _form, vis=None, season="Current"):
    # Every-team-stat table (the Tracked tab's full stat grid). `_tracked/_pack/
    # _form` are passed-in caches (underscore = not hashed); the key is
    # (g, vis, season), and `vis` keeps the tracked columns pool-scoped to viewer.
    return LA.team_stat_table(gender=g, tracked=_tracked, pack=_pack, form=_form,
                              game_ids=(set(vis) if vis is not None else None),
                              season=season)


# AXIS-2 read-filter for every LEAGUE-WIDE tracked aggregation on this page: the
# pooled set this viewer may aggregate (None = admin/local = all tracked games;
# a League-wide coach = own ∪ pooled = pooled). Solo / Free coaches don't reach
# the tracked tabs (the lock stops them); their visible set just yields a sparse
# `tracked` used only for graceful "tracked rank" fallbacks.
_VIS = ENT.visible_tracked_game_ids(AUTH.current_user(), season=season_pick)
_VISK = None if _VIS is None else tuple(sorted(_VIS))

scored = _score_ratings(gender, season_pick)
tracked = _tracked_ratings(gender, _VISK, season_pick)
form_stats = _form_stats(gender, season_pick)

if not scored:
    empty_state("No finished games for this league yet",
                "Enter results in the Input Hub and they'll rank here.",
                cta="Open the Input Hub", page="pages/1_Input_Hub.py")
    st.stop()

name_of = {tid: r["name"] for tid, r in scored.items()}
class_of = {tid: r["class"] for tid, r in scored.items()}
rank_of = {tid: r["Rank"] for tid, r in scored.items()}
TOP5 = {tid for tid, r in scored.items() if r["Rank"] <= 5}
TOP10 = {tid for tid, r in scored.items() if r["Rank"] <= 10}
TOP25 = {tid for tid, r in scored.items() if r["Rank"] <= 25}

# tracked advanced bundle (one cached box pass) — shared by League Lab tab.
# Pool-scoped to the viewer (_VISK) so the league-wide charts never surface a
# Solo coach's tracked depth.
pack = _tracked_pack(gender, tracked, _VISK, season_pick)

# Page-level Class + Min-games filter — set the scope ONCE here (instead of each
# tab rendering its own copy) so a coach picks classes + a games threshold and
# every ranking view (Overview leaders / signature metrics / standings / table,
# and the Tracked table) follows the same scope. The league pulse + recent results
# stay league-wide by design.
_rk_classes = sorted({r["class"] for r in scored.values()},
                     key=lambda c: TR._CLASS_RANK.get(c, 99))
_rk_maxgp = max((r["GP"] for r in scored.values()), default=1)
st.markdown("<div class='section-hdr'>Filters</div>", unsafe_allow_html=True)
_rkf1, _rkf2 = st.columns([2, 1])
_PICKED_CLASSES = _rkf1.multiselect("Class", _rk_classes, default=_rk_classes,
                                    key="rk_class_page")
_MIN_GP = (_rkf2.slider("Min games played", 1, int(_rk_maxgp), 1, key="rk_mingp_page")
           if _rk_maxgp > 1 else 1)
st.caption("Class / min-games scope every ranking view below.")

# Lazy-load: a "View" segmented_control instead of st.tabs, so only the chosen
# view's heavy queries run each rerun (st.tabs computes every tab body). The
# page-level Class / min-games filter above scopes them all. The @st.fragment
# view bodies keep their own fast reruns; switching View reruns the page once.
# Compare promoted to #2 (the real opponent-prep tool); Team Charts + League
# folded into one "League landscape" view (both render the same possession pack)
# with an inner lazy Section selector so only the chosen sub-view computes.
_RK_VIEWS = ["Overview", "Compare", "Team", "Tracked", "League landscape",
             "Glossary"]
_view = _rkseg("View", _RK_VIEWS, default="Overview", key="rk_view") or "Overview"


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — OVERVIEW  (source of truth: scored ratings)
# ══════════════════════════════════════════════════════════════════════════════
if _view == "Overview":
    all_rows = list(scored.values())

    def _form_leader(metric, hi=True, need=None, pool=None):
        cand = [(t, form_stats[t]) for t in form_stats
                if form_stats[t].get(metric) is not None
                and (pool is None or t in pool)
                and (need is None or need(form_stats[t]))]
        if not cand:
            return None, None
        return (max if hi else min)(cand, key=lambda c: c[1][metric])

    st.caption(
        "**Source of truth.** Results-only power ratings for every team — built "
        "from final scores and who-beat-who, opponent-adjusted with a class "
        "bridge. **Power** is 0-100 (50 = league average, +10 per std dev); "
        "**Rating** is points vs an average team on a neutral floor.")

    # ── League pulse (DEMOTED to a one-line caption) ─────────────────────────
    # League-wide counts are context, not decisions — a thin caption instead of a
    # 5-metric row so the leaderboards and rankings table rise to the top.
    tracked_ct = sum(1 for g in TR._finished_games(gender=gender,
                                                   tracked_only=True,
                                                   season=season_pick))
    st.caption(
        f"**League pulse** — {len(all_rows)} teams · "
        f"{int(sum(r['GP'] for r in all_rows) // 2)} games · "
        f"avg {sum(r['PPG'] for r in all_rows)/len(all_rows):.1f}–"
        f"{sum(r['oPPG'] for r in all_rows)/len(all_rows):.1f} PPG · "
        f"{tracked_ct} tracked")

    # ── Recent results ───────────────────────────────────────────────────────
    recent = query(
        """SELECT g.date, g.home_score, g.away_score, g.tracked,
                  t1.id AS t1_id, t2.id AS t2_id,
                  t1.name AS t1, t2.name AS t2
           FROM games g
           JOIN teams t1 ON t1.id = g.team1_id
           JOIN teams t2 ON t2.id = g.team2_id
           WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL
             AND g.season=?
             AND t1.gender = ?
           ORDER BY g.date DESC, g.id DESC LIMIT 8""", (season_pick, gender))
    if recent:
        st.markdown("<div class='section-hdr'>Recent results</div>",
                    unsafe_allow_html=True)
        # Scored class-rank chip per team (results-only ranking → ungated).
        def _rchip(tid):
            r = scored.get(tid)
            return rank_chip(r["class"], r["ClassRank"]) if r else ""
        rc = st.columns(4)
        for i, g in enumerate(recent):
            t1w = g["home_score"] > g["away_score"]
            rc[i % 4].markdown(score_card(
                [(g['t1'], g['home_score'], t1w, _rchip(g['t1_id'])),
                 (g['t2'], g['away_score'], not t1w, _rchip(g['t2_id']))],
                footer=f"{g['date']}{' · ●' if g['tracked'] else ''}",
                footer_top=True), unsafe_allow_html=True)

    # Scope from the PAGE-LEVEL Class / Min-games filter (set once at the top) —
    # drives the team leaders, signature metrics, advanced standings and the
    # rankings table below. The league pulse + recent results stay league-wide.
    ov_tids = [t for t in sorted(scored, key=lambda t: scored[t]["Rank"])
               if scored[t]["class"] in _PICKED_CLASSES and scored[t]["GP"] >= _MIN_GP]
    ov_rows = [scored[t] for t in ov_tids]
    ov_set = set(ov_tids)

    if not ov_rows:
        st.info("No teams match the current Class / games filter.")
    else:
        # ── Team leaders ─────────────────────────────────────────────────────
        st.markdown("<div class='section-hdr'>Team leaders</div>",
                    unsafe_allow_html=True)

        def _leader_card(col, label, key, hi=True, fmt="{:.1f}"):
            best = max(ov_rows, key=lambda r: r[key]) if hi else \
                min(ov_rows, key=lambda r: r[key])
            col.markdown(
                f"<div class='dash-card'><div class='dash-card-title'>{label}</div>"
                f"<div class='dash-card-value'>{fmt.format(best[key])}</div>"
                f"<div class='dash-card-sub'>{best['name']}</div>"
                f"<div class='dash-card-meta'>{best['class']} · "
                f"{best['W']}-{best['L']}</div></div>", unsafe_allow_html=True)

        tl = st.columns(5)
        _leader_card(tl[0], "Top rating", "Rating")
        _leader_card(tl[1], "Best offense (PPG)", "PPG")
        _leader_card(tl[2], "Best defense (PA/G)", "oPPG", hi=False)
        _leader_card(tl[3], "Point margin", "MOV", fmt="{:+.1f}")
        _leader_card(tl[4], "Strength of record", "SOR", fmt="{:.2f}")

        # ── signature (made-up, league-relative) metric leaders ──────────────
        _lab_hdr("Signature metrics")
        st.caption(
            "New composite indices, all 0-100 with 50 = league average (+10 per std "
            "dev). **Dominance** blends margin, win% and blowout rate. "
            "**Consistency** rewards low game-to-game margin volatility. **Clutch** "
            "blends record and margin in games decided by ≤5. **Momentum** is recent "
            "(last-5) vs season form. **Luck** is wins above Pythagorean expectation.")

        def _sig_tile(col, title, metric, fmt="{:.0f}", hi=True, need=None,
                      color=CYBER, suffix=""):
            t, r = _form_leader(metric, hi=hi, need=need, pool=ov_set)
            if t is None:
                col.markdown(
                    f"<div class='glass-tile'><div class='glass-label'>{title}</div>"
                    f"<div class='glass-value' style='color:{GREY}'>—</div>"
                    f"<div class='glass-sub'>no qualifier</div></div>",
                    unsafe_allow_html=True)
                return
            col.markdown(
                f"<div class='glass-tile'><div class='glass-label'>{title}</div>"
                f"<div class='glass-value' style='color:{color}'>"
                f"{fmt.format(r[metric])}{suffix}</div>"
                f"<div class='glass-sub'>{name_of[t]} · {class_of[t]}</div></div>",
                unsafe_allow_html=True)

        sg = st.columns(5)
        _sig_tile(sg[0], "Most dominant", "Dominance", color=CYBER)
        _sig_tile(sg[1], "Most consistent", "Consistency", color=GOOD)
        _sig_tile(sg[2], "Clutch king", "Clutch", color=PURPLE)
        _sig_tile(sg[3], "Hottest", "streak_len", fmt="W{:.0f}",
                  need=lambda r: r["streak_type"] == "W", color=GOLD)
        _sig_tile(sg[4], "Luckiest", "Luck_wins", fmt="{:+.1f}", suffix=" W",
                  color=BLUE)

        with st.expander("Standings — by district"):
            _distmap = {row["id"]: (row["district"] or "")
                        for row in query("SELECT id, district FROM teams")}
            _grp = {}
            for t in ov_tids:
                r = scored[t]
                key = _distmap.get(t) or f"Class {r['class']}"
                _grp.setdefault(key, []).append(r)
            for _dname in sorted(_grp):
                _gts = sorted(_grp[_dname],
                              key=lambda r: -(r["W"] / max(r["W"] + r["L"], 1)))
                _lead = _gts[0]
                _srows = []
                for r in _gts:
                    gb = ((_lead["W"] - r["W"]) + (r["L"] - _lead["L"])) / 2
                    _srows.append({
                        "Team": r["name"], "W": r["W"], "L": r["L"],
                        "Win%": round(r["W"] / max(r["W"] + r["L"], 1) * 100, 1),
                        "GB": "—" if gb <= 0 else f"{gb:.1f}", "Power": r["Power"]})
                st.markdown(f"**{_dname}**")
                st.dataframe(pd.DataFrame(_srows), hide_index=True, width="stretch")
            st.caption("Grouped by district (set on the Setup page); teams with no "
                       "district fall back to their class. GB = games behind leader.")

        st.markdown("<div class='section-hdr'>Rankings table</div>",
                    unsafe_allow_html=True)
        df = pd.DataFrame(ov_rows)[[
            "Rank", "name", "class", "W", "L", "Power", "Rating",
            "PPG", "oPPG", "MOV", "xPPG", "xoPPG", "SOS", "SOR"]].rename(
            columns={"name": "Team", "class": "Class"})
        # Inline margin-trend sparkline per team (last 7 games, oldest→newest) —
        # reads the engine's per_team_results; aligned to ov_tids row order.
        try:
            _ptr = LA.per_team_results(gender, season=season_pick)
            df["Form"] = [[r["margin"] for r in _ptr.get(t, [])[-7:]]
                          for t in ov_tids]
        except Exception:
            pass
        # Advanced composites (was a separate "Advanced standings" table) folded
        # in as a column set — one team table, you pick which stats to see.
        for _ck, _src, _rnd in [("Dominance", "Dominance", None),
                                ("Consistency", "Consistency", None),
                                ("Clutch", "Clutch", None),
                                ("Momentum", "Momentum", None),
                                ("Volatility", "Volatility", 1),
                                ("Pyth W", "Pyth_W", 1),
                                ("Luck (W)", "Luck_wins", 2)]:
            df[_ck] = [(round(form_stats.get(t, {}).get(_src, 0), _rnd)
                        if _rnd is not None else form_stats.get(t, {}).get(_src))
                       for t in ov_tids]

        _core_cols = ["Rank", "Team", "Class", "W", "L", "Power", "Rating",
                      "PPG", "oPPG", "MOV", "xPPG", "xoPPG", "SOS", "SOR"]
        if "Form" in df.columns:
            _core_cols.append("Form")
        _comp_cols = ["Rank", "Team", "Class", "Power", "MOV", "Dominance",
                      "Consistency", "Clutch", "Momentum", "Volatility",
                      "Pyth W", "Luck (W)"]
        _colset = _rkseg("Columns", ["Core", "Composites", "All"],
                         default="Core", key="rk_ov_cols") or "Core"
        _show = (_core_cols if _colset == "Core"
                 else _comp_cols if _colset == "Composites"
                 else list(df.columns))
        st.dataframe(
            df[_show], hide_index=True, width="stretch",
            height=min(720, 60 + 35 * len(df)),
            column_config={
                "Power": st.column_config.ProgressColumn(
                    "Power", format="%.1f", min_value=0, max_value=100,
                    help="Opponent-adjusted power rating on a 0–100 scale — the "
                         "headline strength number (50 ≈ league average)."),
                "Rating": st.column_config.NumberColumn(
                    "Rating", format="%.2f",
                    help="SRS-style net rating: average scoring margin adjusted "
                         "for strength of schedule. 0 = average."),
                "PPG": st.column_config.NumberColumn(
                    "PPG", help="Points scored per game."),
                "oPPG": st.column_config.NumberColumn(
                    "oPPG", help="Opponent points per game (points allowed)."),
                "MOV": st.column_config.NumberColumn(
                    "MOV", help="Average margin of victory (PPG − oPPG)."),
                "xPPG": st.column_config.NumberColumn(
                    "xPPG", help="Schedule-adjusted points scored — what they'd "
                                 "score against an average team."),
                "xoPPG": st.column_config.NumberColumn(
                    "xoPPG", help="Schedule-adjusted points allowed."),
                "SOS": st.column_config.NumberColumn(
                    "SOS", format="%.2f",
                    help="Strength of schedule — the average rating of opponents "
                         "faced."),
                "SOR": st.column_config.NumberColumn(
                    "SOR", format="%.2f",
                    help="Strength of record — how impressive the W–L is given "
                         "the schedule played."),
                "Form": st.column_config.LineChartColumn(
                    "Margin trend", y_min=-30, y_max=30,
                    help="Scoring margin over the last 7 games (oldest → newest)."),
                "Dominance": st.column_config.ProgressColumn(
                    "Dominance", format="%.0f", min_value=0, max_value=100,
                    help="How decisively they beat the teams they should."),
                "Consistency": st.column_config.ProgressColumn(
                    "Consistency", format="%.0f", min_value=0, max_value=100,
                    help="How repeatable their game-to-game performance is."),
                "Clutch": st.column_config.ProgressColumn(
                    "Clutch", format="%.0f", min_value=0, max_value=100,
                    help="Performance in close, late-game situations."),
                "Momentum": st.column_config.ProgressColumn(
                    "Momentum", format="%.0f", min_value=0, max_value=100,
                    help="Recent form trend — rising or fading."),
                "Volatility": st.column_config.NumberColumn(
                    "Volatility",
                    help="Swing in game-to-game margin (lower = steadier)."),
                "Pyth W": st.column_config.NumberColumn(
                    "Pyth W",
                    help="Pythagorean expected wins from points scored/allowed."),
                "Luck (W)": st.column_config.NumberColumn(
                    "Luck (W)", format="%.2f",
                    help="Actual wins minus Pythagorean expected wins."),
            })
        st.caption("Columns: **Core** = ratings & scoring · **Composites** = "
                   "Dominance / Consistency / Clutch / Momentum & luck · **All** "
                   "= everything. Scope set by the Class / min-games filter above.")
        st.download_button("Rankings (CSV)",
                           df.drop(columns=["Form"], errors="ignore").to_csv(index=False),
                           file_name=f"rankings_{gender}.csv", mime="text/csv",
                           key="dl_scored")

# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — TEAM  (per-team deep dive, moved out of Overview)
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _fx_team():
    st.caption("One team, every angle — pick a team for its record, résumé "
               "splits, composites, league percentile profile and full schedule. "
               "Both the league ranking and (where tracked) the possession "
               "ranking are shown together.")

    # ── Team deep dive ───────────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Team deep dive</div>",
                unsafe_allow_html=True)

    order = sorted(scored.keys(), key=lambda t: scored[t]["Rank"])
    default_team = get_setting("default_team", "")
    default_idx = next((i for i, t in enumerate(order)
                        if name_of[t] == default_team), 0)
    pick = st.selectbox(
        "Team", order, index=default_idx,
        format_func=lambda t: f"#{scored[t]['Rank']}  {name_of[t]}  ({class_of[t]})",
        key="ov_team")
    r = scored[pick]

    results = _team_results(pick)
    # record splits
    t5_w, t5_l = _vs_topn(results, TOP5)
    t10_w, t10_l = _vs_topn(results, TOP10)
    t25_w, t25_l = _vs_topn(results, TOP25)
    streak = _team_streak(results)
    by_class = defaultdict(lambda: [0, 0])
    for g in results:
        oc = class_of.get(g["opp"], "N/A")
        by_class[oc][0 if g["won"] else 1] += 1

    # ── the shared team header card (UI_DENSITY_PLAN phase D) — the SAME
    # render the Team Dashboard Overview uses, so the two team surfaces can't
    # drift. Tracked depth (glance / engine zone / tracked rank) rides on the
    # viewer's entitlement for THIS team, exactly like the old tracked clause.
    rk = TR.team_rank(pick, scored=scored, tracked=tracked)
    _see_trk = ENT.can_see_team_tracked(AUTH.current_user(), pick)
    _tr = tracked.get(pick) if _see_trk else None
    from types import SimpleNamespace as _NS
    import helpers.dashboard.team_card as TC
    TC.render_header(_NS(
        team_id=pick, gender=gender, sc_score=r, scored=scored,
        rec={"wins": r["W"], "losses": r["L"], "MOV": r["MOV"],
             "PF_pg": r["PPG"], "PA_pg": r["oPPG"]},
        log=[{"opp_id": g["opp"], "won": g["won"]} for g in results],
        has_tracked=bool(_tr),
        summ=({"ORtg": _tr["ORtg"], "DRtg": _tr["DRtg"],
               "NetRtg": _tr["NetRtg"], "POSS_pg": _tr["Pace"]} if _tr else {}),
        rank_info={"tracked": (rk["tracked"] if _see_trk else None)},
        tracked=tracked,
    ))

    # Rankings-only extras the card doesn't carry (schedule strength + the
    # opponent-adjusted score-based O/D) + the earliest vs-Top split.
    mx = st.columns(5)
    for col, (lbl, val, sub) in zip(mx, [
            ("Rating", r["Rating"], "opponent-adjusted"),
            ("SOS / SOR", f"{r['SOS']:.1f} / {r['SOR']:.1f}", "schedule · record"),
            ("Adj O (xPPG)", r["xPPG"], "score-based offense"),
            ("Adj D (xoPPG)", r["xoPPG"], "score-based defense"),
            ("vs Top 5", f"{t5_w}-{t5_l}", "Top 10/25 on the card")]):
        col.markdown(CD.glass(lbl, val, sub), unsafe_allow_html=True)

    # ── advanced profile (results-only composites + form) ────────────────────
    f = form_stats.get(pick, {})

    def _mv(x, fmt="{:.0f}"):
        return "—" if x is None else fmt.format(x)

    _lab_hdr("Advanced profile")
    if f.get("form"):
        pills = "".join(
            f"<span class='form-pill {'w' if x == 'W' else 'l'}"
            f"{' now' if i == len(f['form']) - 1 else ''}'>{x}</span>"
            for i, x in enumerate(f["form"]))
        st.markdown(f"<div class='form-strip'>{pills}</div>"
                    f"<div style='font-size:11px;color:#8b949e;margin:4px 0 10px'>"
                    f"last {len(f['form'])} · most recent outlined</div>",
                    unsafe_allow_html=True)

    am = st.columns(5)
    for col, (lbl, val, sub) in zip(am, [
            ("Dominance", _mv(f.get("Dominance")), "MOV · win% · blowouts"),
            ("Consistency", _mv(f.get("Consistency")), "steady margins"),
            ("Clutch", _mv(f.get("Clutch")), "close-game execution"),
            ("Momentum", _mv(f.get("Momentum")), "last 5 vs season"),
            ("Volatility", _mv(f.get("Volatility"), "{:.1f}"), "margin swing")]):
        col.markdown(CD.glass(lbl, val, sub), unsafe_allow_html=True)

    # (Pythagorean / luck / close-game rows moved onto the header card's
    #  Verdict zone — only the ceiling/floor extremes stay here.)
    pm = st.columns(2)
    pm[0].markdown(CD.glass("Ceiling", _mv(f.get("ceiling"), "{:+d}"),
                            "best win margin", "#3fb950"),
                   unsafe_allow_html=True)
    pm[1].markdown(CD.glass("Floor", _mv(f.get("floor"), "{:+d}"),
                            "worst loss margin", "#e74c3c"),
                   unsafe_allow_html=True)

    # league percentile profile (results-only, vs the whole field)
    st.markdown("**League percentile profile**")
    pow_pool = [s["Power"] for s in scored.values()]
    mov_pool = [s["MOV"] for s in scored.values()]
    off_pool = [s["PPG"] for s in scored.values()]
    def_pool = [s["oPPG"] for s in scored.values()]
    sos_pool = [s["SOS"] for s in scored.values()]
    sor_pool = [s["SOR"] for s in scored.values()]
    dom_pool = [fm.get("Dominance") for fm in form_stats.values()]
    con_pool = [fm.get("Consistency") for fm in form_stats.values()]
    prof = [
        ("Power", r["Power"], pow_pool, True, "{:.1f}"),
        ("Margin / game", r["MOV"], mov_pool, True, "{:+.1f}"),
        ("Offense (PPG)", r["PPG"], off_pool, True, "{:.1f}"),
        ("Defense (PA/G)", r["oPPG"], def_pool, False, "{:.1f}"),
        ("Strength of schedule", r["SOS"], sos_pool, True, "{:.2f}"),
        ("Strength of record", r["SOR"], sor_pool, True, "{:.2f}"),
        ("Dominance", f.get("Dominance"), dom_pool, True, "{:.0f}"),
        ("Consistency", f.get("Consistency"), con_pool, True, "{:.0f}"),
    ]
    pc1, pc2 = st.columns(2)
    for i, (lbl, val, pool, hib, fmt) in enumerate(prof):
        pct = LA.percentile(val, pool, higher_better=hib)
        txt = "—" if val is None else fmt.format(val)
        (pc1 if i % 2 == 0 else pc2).markdown(
            _pctile_bar(lbl, txt, pct), unsafe_allow_html=True)

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Schedule & results**")
        sched = []
        for g in reversed(results):  # most recent first
            opp = g["opp"]
            sched.append({
                "Date": g["date"],
                "": g["site"],
                "Opponent": f"#{rank_of.get(opp, '—')} {name_of.get(opp, '?')}",
                "Class": class_of.get(opp, "N/A"),
                "Result": f"{'W' if g['won'] else 'L'} {g['pf']}-{g['pa']}",
                "Tracked": "●" if g["tracked"] else "",
            })
        if sched:
            st.dataframe(pd.DataFrame(sched), hide_index=True,
                         width="stretch",
                         height=min(520, 60 + 35 * len(sched)))
        else:
            st.info("No completed games.")

        # upcoming (from the games table, unplayed) — the `schedule` table is dead
        # for the active season; games (manual or OSSAA-imported) live in `games`.
        upcoming = query(
            """SELECT date,
                      CASE WHEN team1_id=? THEN team2_id ELSE team1_id END AS opponent_id,
                      CASE WHEN team1_id=? THEN 'Home'   ELSE 'Away'    END AS home_away,
                      location
               FROM games
               WHERE (team1_id=? OR team2_id=?) AND season=?
                 AND (home_score IS NULL OR away_score IS NULL)
                 AND date >= date('now', 'localtime')
               ORDER BY date""", (pick, pick, pick, pick, season_pick))
        if upcoming:
            st.markdown("**Upcoming**")
            up = [{"Date": u["date"],
                   "": "vs" if u["home_away"] == "Home" else "@",
                   "Opponent": name_of.get(u["opponent_id"],
                                           f"#{u['opponent_id']}"),
                   "Class": class_of.get(u["opponent_id"], "N/A")}
                  for u in upcoming]
            st.dataframe(pd.DataFrame(up), hide_index=True,
                         width="stretch")
    with c2:
        st.markdown("**Record by opponent class**")
        if by_class:
            cls_rows = [{"Class": c, "W": wl[0], "L": wl[1]}
                        for c, wl in sorted(
                            by_class.items(),
                            key=lambda kv: TR._CLASS_RANK.get(kv[0], 99))]
            st.dataframe(pd.DataFrame(cls_rows), hide_index=True,
                         width="stretch")
        # The Adj-O/Adj-D bar just re-plots the xPPG/xoPPG metrics shown above —
        # demoted to an expander so the column reads cleaner.
        with st.expander("Offense vs defense — chart"):
            bar = go.Figure()
            bar.add_trace(go.Bar(
                x=["Adj O", "Adj D"], y=[r["xPPG"], r["xoPPG"]],
                marker_color=[ACCENT, AWAY],
                text=[r["xPPG"], r["xoPPG"]], textposition="outside",
                marker_line_width=0))
            bar.update_yaxes(title="Points / game (opp-adjusted)")
            _style(bar, 240)
            st.plotly_chart(bar, width="stretch")

        # scoring profile in wins vs losses (from final scores)
        wins = [g for g in results if g["won"]]
        losses = [g for g in results if not g["won"]]
        if wins and losses:
            st.markdown("**Wins vs losses** — points for / against")
            def _avg(games, key):
                return sum(g[key] for g in games) / len(games)
            wl = go.Figure()
            wl.add_trace(go.Bar(
                x=["In wins", "In losses"], name="Scored",
                y=[_avg(wins, "pf"), _avg(losses, "pf")], marker_color=ACCENT))
            wl.add_trace(go.Bar(
                x=["In wins", "In losses"], name="Allowed",
                y=[_avg(wins, "pa"), _avg(losses, "pa")], marker_color=AWAY))
            wl.update_layout(barmode="group")
            wl.update_yaxes(title="Points / game")
            _style(wl, 260)
            st.plotly_chart(wl, width="stretch")

    # ── Tracked deep dive (possession-based, tracked games only) ─────────────
    _lab_hdr("Tracked deep dive")
    st.caption("“Tracked” = games logged play-by-play (the phone tracker or Game "
               "Tracker). These possession stats need that depth — box-score-only "
               "games don't feed them.")
    # Single-team tracked depth (AXIS 1 + AXIS 2): own team (Paid) always; another
    # team only when you're League-wide AND it has shared (pooled) tracked games —
    # a Solo coach gets the co-op invite, a non-shared team a neutral note. This is
    # the last section of _fx_team, so a locked viewer just gets the message + return.
    _ident = AUTH.current_user()
    _raw_trk = bool(query("SELECT 1 FROM games WHERE (team1_id=? OR team2_id=?) "
                          "AND tracked=1 AND season=? LIMIT 1",
                          (pick, pick, season_pick)))
    _ok, _lock = ENT.tracked_gate(_ident, pick, _raw_trk, season=season_pick)
    if not _ok:
        if _lock:
            st.info(_lock)
        else:
            empty_state("No tracked games for this team yet",
                        "Track a game in the Game Tracker to unlock the deep dive.")
        return
    _dv = ENT.team_visible_tracked_ids(_ident, pick, season=season_pick)
    _deep = _team_tracked_deep(pick, None if _dv is None else tuple(sorted(_dv)),
                               season=season_pick)
    if not _deep:
        empty_state("No tracked games for this team yet",
                    "Track a game in the Game Tracker to unlock possession "
                    "ratings, the four factors, quarter-by-quarter PPP and "
                    "win/loss patterns.",
                    cta="Open the Game Tracker", page="pages/2_Game_Tracker.py")
    else:
        st.caption(
            f"Possession-based over **{_deep['gp']} tracked game"
            f"{'' if _deep['gp'] == 1 else 's'}** — a small sample, so treat as "
            "directional. PPP = points per possession; PPG = points per game.")

        kc = st.columns(6)
        kc[0].metric("Net Rtg", f"{_deep['net']:+.1f}", help="ORtg − DRtg")
        kc[1].metric("ORtg", f"{_deep['ortg']:.1f}", help="pts / 100 poss")
        kc[2].metric("DRtg", f"{_deep['drtg']:.1f}", help="pts allowed / 100 poss")
        kc[3].metric("PPP", f"{_deep['ppp']:.3f}")
        kc[4].metric("Opp PPP", f"{_deep['oppp']:.3f}")
        kc[5].metric("Pace", f"{_deep['pace']:.1f}", help="poss / game")

        a1 = st.columns(5)
        a1[0].metric("eFG%", f"{_deep['efg'] * 100:.1f}%")
        a1[1].metric("Opp eFG%", f"{_deep['oefg'] * 100:.1f}%")
        a1[2].metric("TS%", f"{_deep['ts'] * 100:.1f}%")
        a1[3].metric("Opp TS%", f"{_deep['ots'] * 100:.1f}%")
        a1[4].metric("Paint FG%", f"{_deep['paint'] * 100:.1f}%")

        a2 = st.columns(5)
        a2[0].metric("TOV%", f"{_deep['tov'] * 100:.1f}%")
        a2[1].metric("Forced TOV%", f"{_deep['ftov'] * 100:.1f}%")
        a2[2].metric("OREB%", f"{_deep['oreb'] * 100:.1f}%")
        a2[3].metric("DREB%", f"{_deep['dreb'] * 100:.1f}%")
        a2[4].metric("FT rate", f"{_deep['ftr']:.3f}", help="FTA / FGA")

        _dt_q, _dt_wl = st.tabs(["Quarters & PPP", "Win/Loss patterns"])

        with _dt_q:
            _pr = _deep["periods"]
            _qtbl = pd.DataFrame([{
                "Period": p["Period"],
                "Team PPG": f"{p['tppg']:.1f}",
                "Opp PPG": f"{p['oppg']:.1f}",
                "Margin": f"{p['tppg'] - p['oppg']:+.1f}",
                "Team PPP": f"{p['tppp']:.3f}",
                "Opp PPP": f"{p['oppp']:.3f}",
            } for p in _pr])
            st.dataframe(_qtbl, hide_index=True, width="stretch")

            _bars = [p for p in _pr if p["Period"] != "Full Game"]
            _lbl = [p["Period"] for p in _bars]
            _tname = name_of.get(pick, "Team")
            qc1, qc2 = st.columns(2)
            with qc1:
                f1 = go.Figure()
                f1.add_trace(go.Bar(name=_tname, x=_lbl,
                                    y=[p["tppp"] for p in _bars],
                                    marker_color=ACCENT))
                f1.add_trace(go.Bar(name="Opponent", x=_lbl,
                                    y=[p["oppp"] for p in _bars],
                                    marker_color=AWAY))
                f1.update_layout(barmode="group", title="PPP by period")
                f1.update_yaxes(title="Points / possession")
                _style(f1, 300)
                st.plotly_chart(f1, width="stretch")
            with qc2:
                f2 = go.Figure()
                f2.add_trace(go.Bar(name=_tname, x=_lbl,
                                    y=[p["tppg"] for p in _bars],
                                    marker_color=ACCENT))
                f2.add_trace(go.Bar(name="Opponent", x=_lbl,
                                    y=[p["oppg"] for p in _bars],
                                    marker_color=AWAY))
                f2.update_layout(barmode="group", title="PPG by period")
                f2.update_yaxes(title="Points / game")
                _style(f2, 300)
                st.plotly_chart(f2, width="stretch")

            _qp = {p["Period"]: p["tppp"] for p in _pr
                   if p["Period"] in ("Q1", "Q2", "Q3", "Q4")}
            if _qp and max(_qp.values()) > 0:
                _bq = max(_qp, key=_qp.get)
                _wq = min(_qp, key=_qp.get)
                st.info(f"Strongest quarter: **{_bq}** ({_qp[_bq]:.3f} PPP)  ·  "
                        f"Weakest: **{_wq}** ({_qp[_wq]:.3f} PPP)")

        with _dt_wl:
            _tr = _deep["trend"]
            if len(_tr) < 2:
                st.info("Need at least 2 tracked games for win/loss patterns.")
            else:
                _w = [g for g in _tr if g["won"]]
                _l = [g for g in _tr if not g["won"]]
                _close = [g for g in _tr if abs(g["margin"]) <= 10]
                _cw = sum(1 for g in _close if g["won"])

                def _avg(rows, k):
                    return sum(r[k] for r in rows) / len(rows) if rows else 0.0

                _bul = []
                if _w:
                    _bul.append(f"In **wins** ({len(_w)}): ORtg "
                                f"{_avg(_w, 'ORtg'):.1f}, DRtg {_avg(_w, 'DRtg'):.1f}"
                                f", margin {_avg(_w, 'margin'):+.1f}")
                if _l:
                    _bul.append(f"In **losses** ({len(_l)}): ORtg "
                                f"{_avg(_l, 'ORtg'):.1f}, DRtg {_avg(_l, 'DRtg'):.1f}"
                                f", margin {_avg(_l, 'margin'):+.1f}")
                if _close:
                    _bul.append(f"Close games (≤10): **{_cw}-{len(_close) - _cw}**")
                for b in _bul:
                    st.markdown(f"- {b}")

                wc1, wc2 = st.columns(2)
                with wc1:
                    _rows, _oo, _dd = [], [], []
                    for tag, grp in [("Wins", _w), ("Losses", _l)]:
                        if grp:
                            _rows.append(tag)
                            _oo.append(_avg(grp, "ORtg"))
                            _dd.append(_avg(grp, "DRtg"))
                    if _rows:
                        fwl = go.Figure()
                        fwl.add_trace(go.Bar(name="ORtg", x=_rows, y=_oo,
                                             marker_color=ACCENT))
                        fwl.add_trace(go.Bar(name="DRtg", x=_rows, y=_dd,
                                             marker_color=AWAY))
                        fwl.update_layout(barmode="group",
                                          title="Avg ratings: wins vs losses")
                        _style(fwl, 300)
                        st.plotly_chart(fwl, width="stretch")
                with wc2:
                    fom = go.Figure()
                    for tag, grp, clr in [("W", _w, GOOD), ("L", _l, BAD)]:
                        fom.add_trace(go.Scatter(
                            x=[g["ORtg"] for g in grp],
                            y=[g["margin"] for g in grp], mode="markers", name=tag,
                            marker=dict(color=clr, size=9),
                            text=[g["opp"] for g in grp],
                            hovertemplate="%{text}<br>ORtg %{x:.1f}"
                                          "<br>Margin %{y:+d}<extra></extra>"))
                    fom.update_layout(title="ORtg vs margin")
                    fom.update_xaxes(title="ORtg")
                    fom.update_yaxes(title="Margin")
                    _style(fom, 300)
                    st.plotly_chart(fom, width="stretch")

                fdm = go.Figure()
                for tag, grp, clr in [("W", _w, GOOD), ("L", _l, BAD)]:
                    fdm.add_trace(go.Scatter(
                        x=[g["DRtg"] for g in grp],
                        y=[g["margin"] for g in grp], mode="markers", name=tag,
                        marker=dict(color=clr, size=9),
                        text=[g["opp"] for g in grp],
                        hovertemplate="%{text}<br>DRtg %{x:.1f}"
                                      "<br>Margin %{y:+d}<extra></extra>"))
                fdm.update_layout(
                    title="DRtg vs margin (lower DRtg = better defense)")
                fdm.update_xaxes(title="DRtg")
                fdm.update_yaxes(title="Margin")
                _style(fdm, 300)
                st.plotly_chart(fdm, width="stretch")


if _view == "Team":
    _fx_team()


if _view == "Overview":
    # ── Hot & cold (current streaks across the league) ───────────────────────
    streaks = []
    for tid in scored:
        f = form_stats.get(tid)
        if f and f.get("streak_type") and f.get("streak_len"):
            streaks.append((tid, f["streak_type"], int(f["streak_len"])))
    if streaks:
        st.markdown("<div class='section-hdr'>Hot &amp; cold</div>",
                    unsafe_allow_html=True)
        hot = sorted((x for x in streaks if x[1] == "W"),
                     key=lambda x: -x[2])[:5]
        cold = sorted((x for x in streaks if x[1] == "L"),
                      key=lambda x: -x[2])[:5]
        hc1, hc2 = st.columns(2)
        with hc1:
            st.markdown("**Win streaks**")
            for tid, _, n in hot:
                st.markdown(
                    f"**{name_of[tid]}** `{class_of[tid]}`  "
                    f"<span style='color:{GOOD};font-weight:700'>W{n}</span>  "
                    f"({scored[tid]['W']}-{scored[tid]['L']})",
                    unsafe_allow_html=True)
        with hc2:
            st.markdown("**Losing streaks**")
            for tid, _, n in cold:
                st.markdown(
                    f"**{name_of[tid]}** `{class_of[tid]}`  "
                    f"<span style='color:var(--bad);font-weight:700'>L{n}</span>  "
                    f"({scored[tid]['W']}-{scored[tid]['L']})",
                    unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — TRACKED  (possession-based, advanced)
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _fx_track():
    if not tracked:
        empty_state("No tracked games for this league yet",
                    "Track a game in the Game Tracker and its advanced ratings "
                    "appear here.",
                    cta="Open the Game Tracker", page="pages/2_Game_Tracker.py")
    else:
        st.caption(
            "Possession-based ratings over **tracked games only** — a far smaller, "
            "sparsely-connected sample, so treat as directional. **ORtg / DRtg / "
            "NetRtg / PPP are opponent-adjusted** (KenPom-style — corrected for "
            "the schedule faced); **AdjeFG / Adj-oeFG** apply the same correction "
            "to shooting (what you'd shoot vs an average defense / what an "
            "average offense would shoot on you). **Pace** is possessions per "
            "game.")

        _adj = _adj_shoot(gender, _VISK, season_pick)
        for _at, _arow in tracked.items():     # cache returns a copy — safe to
            _a = _adj.get(_at) or {}            # annotate per rerun
            _arow["AdjeFG"] = _a.get("AdjeFG")
            _arow["AdjoeFG"] = _a.get("AdjoeFG")

        rows = _filter_rows(
            sorted(tracked.values(), key=lambda r: r["Rank"]), "trk")
        if not rows:
            st.info("No teams match the current Class / games filter.")
        else:
            df = pd.DataFrame(rows)[[
                "Rank", "name", "class", "GP", "Power", "Rating", "RatingPts",
                "NetRtg", "ORtg", "DRtg", "PPP", "oPPP", "Pace",
                "eFG", "oeFG", "AdjeFG", "AdjoeFG",
                "FGpct", "oFGpct", "TPpct", "SOS", "SOR",
                "ClassAdj"]].rename(columns={"name": "Team", "class": "Class"})
            st.dataframe(
                df, hide_index=True, width="stretch",
                height=min(640, 60 + 35 * len(df)),
                column_config={
                    "Power": st.column_config.ProgressColumn(
                        "Power", format="%.1f", min_value=0, max_value=100),
                    "Rating": st.column_config.NumberColumn("Rating", format="%.2f"),
                    "RatingPts": st.column_config.NumberColumn(
                        "Rating (pts)", format="%.2f"),
                    "NetRtg": st.column_config.NumberColumn("NetRtg", format="%.1f"),
                    "ORtg": st.column_config.NumberColumn("ORtg", format="%.1f"),
                    "DRtg": st.column_config.NumberColumn("DRtg", format="%.1f"),
                    "PPP": st.column_config.NumberColumn("PPP", format="%.3f"),
                    "oPPP": st.column_config.NumberColumn("Opp PPP", format="%.3f"),
                    "Pace": st.column_config.NumberColumn("Pace", format="%.1f"),
                    "eFG": st.column_config.NumberColumn("eFG%", format="percent"),
                    "oeFG": st.column_config.NumberColumn("Opp eFG%",
                                                          format="percent"),
                    "AdjeFG": st.column_config.NumberColumn(
                        "Adj eFG%", format="percent",
                        help="Opponent-adjusted: what this team would shoot "
                             "against an AVERAGE defense."),
                    "AdjoeFG": st.column_config.NumberColumn(
                        "Adj Opp eFG%", format="percent",
                        help="Opponent-adjusted: what an AVERAGE offense would "
                             "shoot against this defense (lower is better)."),
                    "FGpct": st.column_config.NumberColumn("FG%", format="percent"),
                    "oFGpct": st.column_config.NumberColumn("Opp FG%",
                                                            format="percent"),
                    "TPpct": st.column_config.NumberColumn("3P%", format="percent"),
                    "SOS": st.column_config.NumberColumn("SOS", format="%.2f"),
                    "SOR": st.column_config.NumberColumn("SOR", format="%.2f"),
                    "ClassAdj": st.column_config.NumberColumn(
                        "ClassAdj", format="%.2f"),
                })
            st.download_button("Tracked ratings (CSV)", df.to_csv(index=False),
                               file_name=f"tracked_ratings_{gender}.csv",
                               mime="text/csv", key="dl_tracked")

            # ── full team stat table — every tracked-team stat in one grid.
            #    LAZY: built only when the toggle is on (it recomputes the
            #    adjusted-shooting ridge + the run detection — no reason to pay
            #    that on every Tracked-view rerun).
            st.markdown("<div class='section-hdr'>Full team stat table</div>",
                        unsafe_allow_html=True)
            if not st.toggle("Load the full stat table (every team stat, "
                             "sortable + filterable)", key="trk_full_on"):
                st.caption("70+ columns: power, efficiency, shooting both ends "
                           "(incl. opponent-adjusted), rebounding, playmaking, "
                           "defense, scoring runs, composites and schedule. "
                           "Team column stays pinned while you scroll.")
            else:
                full_rows = _team_stat_rows(gender, tracked, pack, form_stats,
                                            _VISK, season_pick)
                _keep = {r["name"] for r in rows}      # same Class / min-games filter
                full = pd.DataFrame([fr for fr in full_rows if fr["Team"] in _keep])
                if full.empty:
                    st.info("No tracked teams match the current Class / games "
                            "filter.")
                else:
                    _grid(full, "trk_full", height=560)
                    st.download_button(
                        "Full team stats (CSV)", full.to_csv(index=False),
                        file_name=f"team_stats_{gender}.csv", mime="text/csv",
                        key="dl_team_full")
                    st.caption(
                        "Every team stat in one grid — sort or filter any column; "
                        "the Team column stays pinned. Efficiency, shooting and "
                        "rate columns (0-100 scale) come from **tracked games "
                        "only** (Trk GP); record, MOV and the composites "
                        "(Dominance / Clutch / Luck …) are **full-season "
                        "results**; Adj eFG% / Adj Opp eFG% are opponent-"
                        "adjusted; 10-0 runs from the run engine (garbage time "
                        "excluded). Pool-scoped to you.")

        st.markdown("<div class='section-hdr'>Tracked schedule & box scores</div>",
                    unsafe_allow_html=True)
        torder = sorted(tracked.keys(), key=lambda t: tracked[t]["Rank"])
        tpick = st.selectbox(
            "Team", torder,
            format_func=lambda t: f"#{tracked[t]['Rank']}  {name_of.get(t, t)}",
            key="trk_team")

        tracked_games = [g for g in _team_results(tpick) if g["tracked"]]
        if not tracked_games:
            st.info("This team has no tracked games yet.")
        else:
            # A game PICKER, not a list of expanders. st.expander always renders its
            # body (even collapsed), so the old loop rendered EVERY game's full box
            # score — 7 tabs + plotly each — on every rerun: the bottom of this tab
            # crawled for a team with several tracked games. Render one at a time.
            games_desc = list(reversed(tracked_games))
            _glabel = {
                g["game_id"]: (f"{g['date']}  ·  {g['site']} "
                               f"{name_of.get(g['opp'], '?')}  ·  "
                               f"{'W' if g['won'] else 'L'} {g['pf']}-{g['pa']}")
                for g in games_desc}
            gpick = st.selectbox(
                "Game", [g["game_id"] for g in games_desc],
                format_func=lambda gid: _glabel.get(gid, gid), key="trk_game")
            render_box_score(gpick)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — TEAM CHARTS  (tracked-event driven, cross-team) + STAT LAB explorer
# ══════════════════════════════════════════════════════════════════════════════
if _view == "Tracked":
    _trk_lock = _paid_pool_lock()
    if _trk_lock:
        st.info(_trk_lock)
    else:
        _fx_track()


@st.fragment
def _fx_chart():
    if not tracked:
        empty_state("No tracked-game events yet",
                    "Team charts are built from tracked-game events — none yet "
                    "for this league.",
                    cta="Open the Game Tracker", page="pages/2_Game_Tracker.py")
    else:
        st.caption("How teams score, how they win, and who can shoot — across all "
                   "tracked games in this league. Built from per-game team boxes, "
                   "so defensive splits (opp eFG%, ORB%) are included. Use the "
                   "team filter to take teams out of every graph below.")

        # per-team advanced bundle — the single shared box pass from
        # helpers/league_analytics.team_tracked_pack (computed once, cached, and
        # reused by the League tab). `ts[t]` carries the
        # derived keys this tab used inline, plus extras; 3P% is "TPpct".
        all_teams = pack["teams"]
        own, opp, gp, ts = pack["own"], pack["opp"], pack["gp"], pack["ts"]
        qfor, qagn, tqbox = pack["qfor"], pack["qagn"], pack["tqbox"]

        # ── team filter — drives every chart on this tab ─────────────────────
        _csel = st.multiselect(
            "Teams to show (empty = all)", all_teams, default=[],
            format_func=lambda t: name_of.get(t, str(t)), key="chart_team_filter")
        teams = [t for t in all_teams if t in set(_csel)] or all_teams
        labels = [name_of.get(t, str(t)) for t in teams]
        if len(teams) < len(all_teams):
            st.caption(f"Showing {len(teams)} of {len(all_teams)} tracked teams.")

        def _hbar(metric, title, axis, pct=False, asc=False, n=2, key=None):
            """Sorted horizontal bar of one team metric."""
            srt = sorted(teams, key=lambda t: ts[t][metric], reverse=not asc)
            vals = [ts[t][metric] for t in srt]
            slab = [name_of.get(t, str(t)) for t in srt]
            fmt = "%{x:.1f}%" if pct else f"%{{x:.{n}f}}"
            fig = go.Figure(go.Bar(
                y=slab, x=vals, orientation="h", marker_color=ACCENT,
                text=vals, texttemplate=fmt, textposition="auto",
                marker_line_width=0,
                hovertemplate="<b>%{y}</b><br>" + axis + ": %{x}<extra></extra>"))
            fig.update_xaxes(title=axis)
            _style(fig, max(320, 26 * len(srt)))
            st.markdown(f"**{title}**")
            st.plotly_chart(fig, width="stretch", key=key)

        # ════════════════ EVERY HEADLINE STAT — SORTED BARS ════════════════
        st.markdown("<div class='section-hdr'>Every headline team stat</div>",
                    unsafe_allow_html=True)
        st.caption("Pick a headline stat to chart as a sorted bar — one bar per "
                   "team, respecting the team filter. Four Factors, shooting, "
                   "efficiency and the core box rates; the full stat set lives "
                   "in the Stat Lab explorer further down.")
        _gallery = [
            ("eFG", "Effective FG%", "eFG%", True, False, 1),
            ("oeFG", "Opponent eFG% (lower better)", "Opp eFG%", True, True, 1),
            ("TS", "True shooting %", "TS%", True, False, 1),
            ("FGpct", "Field-goal %", "FG%", True, False, 1),
            ("TPpct", "Three-point %", "3P%", True, False, 1),
            ("FTpct", "Free-throw %", "FT%", True, False, 1),
            ("TPAr", "Three-point attempt rate", "3PA/FGA %", True, False, 1),
            ("FTr", "Free-throw rate", "FTA / FGA", False, False, 2),
            ("ORtg", "Offensive rating", "ORtg", False, False, 1),
            ("DRtg", "Defensive rating (lower better)", "DRtg", False, True, 1),
            ("NetRtg", "Net rating", "Net", False, False, 1),
            ("Pace", "Pace — possessions / game", "Poss/g", False, False, 1),
            ("PPP", "Points per possession", "PPP", False, False, 3),
            ("oPPP", "Opp points per possession (lower better)", "Opp PPP",
             False, True, 3),
            ("ORBpct", "Offensive-rebound %", "ORB%", True, False, 1),
            ("DRBpct", "Defensive-rebound %", "DRB%", True, False, 1),
            ("Astpct", "Assisted % of made FGs", "AST%", True, False, 1),
            ("TOVpct", "Turnover % (lower better)", "TOV%", True, True, 1),
            ("ast_pg", "Assists / game", "AST/g", False, False, 1),
            ("tov_pg", "Turnovers / game (lower better)", "TOV/g", False, True, 1),
            ("stl_pg", "Steals / game", "STL/g", False, False, 1),
            ("blk_pg", "Blocks / game", "BLK/g", False, False, 1),
        ]
        _avail = [g for g in _gallery if all(g[0] in ts[t] for t in teams)]
        _by_ax = {g[2]: g for g in _avail}
        _pick_ax = st.pills("Stat", list(_by_ax), default=next(iter(_by_ax), None),
                            key="gal_pick")
        if _pick_ax:
            _mk, _ti, _ax, _pc, _as, _nn = _by_ax[_pick_ax]
            _hbar(_mk, _ti, _ax, pct=_pc, asc=_as, n=_nn, key=f"gal_{_mk}")
        if st.checkbox("Show all stats as a chart wall", key="gal_all"):
            _gcols = st.columns(2)
            for _i, (_mk, _ti, _ax, _pc, _as, _nn) in enumerate(_avail):
                with _gcols[_i % 2]:
                    _hbar(_mk, _ti, _ax, pct=_pc, asc=_as, n=_nn,
                          key=f"galw_{_mk}")

        # ════════════════ SCORING ════════════════
        st.markdown("<div class='section-hdr'>Scoring</div>",
                    unsafe_allow_html=True)
        st.markdown("**How teams score** — points per game by source")
        two = [own[t]["2PM"] * 2 / max(gp[t], 1) for t in teams]
        thr = [own[t]["3PM"] * 3 / max(gp[t], 1) for t in teams]
        ftp = [own[t]["FTM"] / max(gp[t], 1) for t in teams]
        sfig = go.Figure()
        sfig.add_trace(go.Bar(x=labels, y=two, name="2-pt", marker_color=ACCENT))
        sfig.add_trace(go.Bar(x=labels, y=thr, name="3-pt", marker_color="#58a6ff"))
        sfig.add_trace(go.Bar(x=labels, y=ftp, name="FT", marker_color="#8b949e"))
        sfig.update_layout(barmode="stack")
        sfig.update_yaxes(title="Points / game")
        _style(sfig, 380)
        st.plotly_chart(sfig, width="stretch")

        c1, c2 = st.columns(2)
        with c1:
            _hbar("TS", "True shooting %", "TS%", pct=True)
        with c2:
            _hbar("paint_pg", "Paint scoring — points / game", "Paint pts/g")

        # ════════════════ HOW TEAMS WIN ════════════════
        st.markdown("<div class='section-hdr'>How teams win</div>",
                    unsafe_allow_html=True)
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("**Offense vs defense** (bubble = pace)")
            ortg = [tracked[t]["ORtg"] for t in teams]
            drtg = [tracked[t]["DRtg"] for t in teams]
            pace = [tracked[t]["Pace"] for t in teams]
            wfig = go.Figure(go.Scatter(
                x=ortg, y=drtg, mode="markers+text", text=labels,
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=[max(8, p / 2) for p in pace], color=ortg,
                            colorscale=HEAT, showscale=False,
                            line=dict(width=1, color="#30363d"))))
            if ortg:
                wfig.add_vline(x=sum(ortg) / len(ortg),
                               line=dict(color="#30363d", dash="dot"))
                wfig.add_hline(y=sum(drtg) / len(drtg),
                               line=dict(color="#30363d", dash="dot"))
            wfig.update_xaxes(title="Offensive rating →")
            wfig.update_yaxes(title="← Defensive rating (lower better)",
                              autorange="reversed")
            _style(wfig, 400)
            st.plotly_chart(wfig, width="stretch")
        with c4:
            st.markdown("**Ball movement** — assists vs turnovers per game")
            mfig = go.Figure(go.Scatter(
                x=[ts[t]["tov_pg"] for t in teams],
                y=[ts[t]["ast_pg"] for t in teams],
                mode="markers+text", text=labels, textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=12, color=[ts[t]["ast_per_fgm"] for t in teams],
                            colorscale=HEAT, showscale=True,
                            colorbar=dict(title="AST/<br>FGM", thickness=10),
                            line=dict(width=1, color="#30363d"))))
            mfig.update_xaxes(title="Turnovers / game →")
            mfig.update_yaxes(title="Assists / game →")
            _style(mfig, 400)
            st.plotly_chart(mfig, width="stretch")

        # Four Factors table (Dean Oliver — offense + defensive eFG%)
        st.markdown("**Four factors** — eFG%, turnover %, offensive-rebound %, "
                    "free-throw rate (plus opponent eFG%)")
        ff = pd.DataFrame([{
            "Team": name_of.get(t, str(t)),
            "eFG%": round(ts[t]["eFG"], 1),
            "TOV%": round(ts[t]["TOVpct"], 1),
            "ORB%": round(ts[t]["ORBpct"], 1),
            "FT Rate": round(ts[t]["FTr"], 3),
            "Opp eFG%": round(ts[t]["oeFG"], 1),
            "DRB%": round(ts[t]["DRBpct"], 1),
        } for t in teams])
        st.dataframe(
            ff, hide_index=True, width="stretch",
            height=min(560, 60 + 35 * len(ff)),
            column_config={
                "eFG%": st.column_config.ProgressColumn(
                    "eFG%", format="%.1f", min_value=0, max_value=70),
                "Opp eFG%": st.column_config.ProgressColumn(
                    "Opp eFG%", format="%.1f", min_value=0, max_value=70),
                "ORB%": st.column_config.NumberColumn("ORB%", format="%.1f"),
                "DRB%": st.column_config.NumberColumn("DRB%", format="%.1f"),
                "TOV%": st.column_config.NumberColumn("TOV%", format="%.1f"),
            })

        # ════════════════ SHOOTING & STYLE ════════════════
        st.markdown("<div class='section-hdr'>Shooting & style</div>",
                    unsafe_allow_html=True)
        c5, c6 = st.columns(2)
        with c5:
            st.markdown("**Who can shoot** — eFG% & 3P%")
            srt = sorted(teams, key=lambda t: tracked[t]["eFG"])
            efg = [tracked[t]["eFG"] * 100 for t in srt]
            tp = [tracked[t]["TPpct"] * 100 for t in srt]
            slab = [name_of.get(t, str(t)) for t in srt]
            shfig = go.Figure()
            shfig.add_trace(go.Bar(y=slab, x=efg, name="eFG%", orientation="h",
                                   marker_color=ACCENT))
            shfig.add_trace(go.Bar(y=slab, x=tp, name="3P%", orientation="h",
                                   marker_color="#58a6ff"))
            shfig.update_layout(barmode="group")
            shfig.update_xaxes(title="%")
            _style(shfig, max(360, 26 * len(srt)))
            st.plotly_chart(shfig, width="stretch")
        with c6:
            st.markdown("**Shot diet** — 3-point reliance vs 3P% (bubble = FGA/g)")
            dfig = go.Figure(go.Scatter(
                x=[ts[t]["TPAr"] for t in teams],
                y=[ts[t]["TPpct"] for t in teams],
                mode="markers+text", text=labels, textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=[max(8, ts[t]["fga_pg"] / 4) for t in teams],
                            color="#58a6ff", line=dict(width=1, color="#30363d"))))
            dfig.update_xaxes(title="3PA rate (% of FGA) →")
            dfig.update_yaxes(title="3P% →")
            _style(dfig, 400)
            st.plotly_chart(dfig, width="stretch")

        c7, c8 = st.columns(2)
        with c7:
            _hbar("fga_pg", "Shot volume — FGA / game", "FGA/g", n=1)
        with c8:
            _hbar("TOVpct", "Turnover % (lower better)", "TOV%", pct=True,
                  asc=True)

        # crosshair scatter helper (mean lines, optional reversed y)
        def _scatter(xk, yk, xt, yt, title, color="#58a6ff",
                     yreverse=False, height=400):
            xs = [ts[t][xk] for t in teams]
            ys = [ts[t][yk] for t in teams]
            fig = go.Figure(go.Scatter(
                x=xs, y=ys, mode="markers+text", text=labels,
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=12, color=color,
                            line=dict(width=1, color="#30363d"))))
            if xs:
                fig.add_vline(x=sum(xs) / len(xs),
                              line=dict(color="#30363d", dash="dot"))
                fig.add_hline(y=sum(ys) / len(ys),
                              line=dict(color="#30363d", dash="dot"))
            fig.update_xaxes(title=xt)
            fig.update_yaxes(title=yt, autorange="reversed" if yreverse else None)
            _style(fig, height)
            st.markdown(f"**{title}**")
            st.plotly_chart(fig, width="stretch")

        c11, c12 = st.columns(2)
        with c11:
            _scatter("eFG", "TS", "eFG% →", "TS% →",
                     "Shooting map — eFG% vs TS% (crosshairs = league avg)")
        with c12:
            _scatter("paint_pg", "paint3_pg", "Paint pts/g →", "3PT pts/g →",
                     "Inside vs outside — paint vs 3PT scoring", color="#f0a500")

        # assisted vs self-created (Ast% of made FGs)
        st.markdown("**Ball movement** — assisted vs self-created field goals")
        srt = sorted(teams, key=lambda t: ts[t]["Astpct"], reverse=True)
        slab = [name_of.get(t, str(t)) for t in srt]
        afig = go.Figure()
        afig.add_trace(go.Bar(x=slab, y=[ts[t]["Astpct"] for t in srt],
                              name="Assisted %", marker_color="#1a9850"))
        afig.add_trace(go.Bar(x=slab, y=[100 - ts[t]["Astpct"] for t in srt],
                              name="Self-created %", marker_color=AWAY))
        afig.update_layout(barmode="stack")
        afig.update_yaxes(title="% of made FGs")
        afig.update_xaxes(tickangle=-40)
        _style(afig, 360)
        st.plotly_chart(afig, width="stretch")
        st.caption("Assisted% = made FGs off a pass (AST/FGM). High = ball-movement "
                   "offense; low = isolation / self-creation.")

        # ════════════════ DEFENSE ════════════════
        st.markdown("<div class='section-hdr'>Defense</div>",
                    unsafe_allow_html=True)
        d1, d2 = st.columns(2)
        with d1:
            _hbar("oeFG", "Opponent eFG% (lower better)", "Opp eFG%",
                  pct=True, asc=True)
        with d2:
            _scatter("blk_r", "stl_r", "Block rate (per 100) →",
                     "Steal rate (per 100) →",
                     "Rim vs perimeter D — blocks vs steals", color="#9b59b6")

        # ════════════════ POSSESSIONS & EFFICIENCY ════════════════
        st.markdown("<div class='section-hdr'>Possessions & efficiency</div>",
                    unsafe_allow_html=True)
        st.caption("A possession ends on a shot or a turnover (FGA + TOV); "
                   "free throws and fouls don't count. Pace is possessions per "
                   "game; PPP is points per possession.")
        c9, c10 = st.columns(2)
        with c9:
            _hbar("Pace", "Pace — possessions / game", "Poss/g", n=1)
        with c10:
            st.markdown("**Efficiency** — points per possession (own vs allowed)")
            srt = sorted(teams, key=lambda t: ts[t]["PPP"] - ts[t]["oPPP"])
            slab = [name_of.get(t, str(t)) for t in srt]
            efig = go.Figure()
            efig.add_trace(go.Bar(y=slab, x=[ts[t]["PPP"] for t in srt],
                                  name="PPP (off)", orientation="h",
                                  marker_color=ACCENT))
            efig.add_trace(go.Bar(y=slab, x=[ts[t]["oPPP"] for t in srt],
                                  name="Opp PPP (def)", orientation="h",
                                  marker_color=AWAY))
            efig.update_layout(barmode="group")
            efig.update_xaxes(title="Points / possession")
            _style(efig, max(360, 26 * len(srt)))
            st.plotly_chart(efig, width="stretch")

        # net efficiency margin per possession
        _hbar2_metric = {t: ts[t]["PPP"] - ts[t]["oPPP"] for t in teams}
        st.markdown("**Net points per possession** (PPP − opponent PPP)")
        srt = sorted(teams, key=lambda t: _hbar2_metric[t], reverse=True)
        vals = [_hbar2_metric[t] for t in srt]
        nfig = go.Figure(go.Bar(
            x=[name_of.get(t, str(t)) for t in srt], y=vals,
            marker_color=[ACCENT if v >= 0 else AWAY for v in vals],
            text=[f"{v:+.3f}" for v in vals], textposition="outside",
            marker_line_width=0))
        nfig.add_hline(y=0, line=dict(color="#30363d", width=1))
        nfig.update_yaxes(title="Net PPP")
        _style(nfig, 340)
        st.plotly_chart(nfig, width="stretch")

        # ════════════════ GAME FLOW (quarter data) ════════════════
        st.markdown("<div class='section-hdr'>Game flow — quarter data</div>",
                    unsafe_allow_html=True)
        allq = sorted({q for t in teams for q in qfor[t]} |
                      {q for t in teams for q in qagn[t]})
        qlabels = [_q_label(q) for q in allq]

        f1, f2 = st.columns(2)
        with f1:
            st.markdown("**Points scored by quarter** (top 8)")
            qfig = go.Figure()
            for t in teams[:8]:
                ys = [qfor[t].get(q, 0) / max(gp[t], 1) for q in allq]
                qfig.add_trace(go.Scatter(
                    x=qlabels, y=ys, mode="lines+markers",
                    name=name_of.get(t, str(t))))
            qfig.update_yaxes(title="Points / game")
            _style(qfig, 360)
            st.plotly_chart(qfig, width="stretch")
        with f2:
            st.markdown("**Points allowed by quarter** (top 8)")
            afig = go.Figure()
            for t in teams[:8]:
                ys = [qagn[t].get(q, 0) / max(gp[t], 1) for q in allq]
                afig.add_trace(go.Scatter(
                    x=qlabels, y=ys, mode="lines+markers",
                    name=name_of.get(t, str(t))))
            afig.update_yaxes(title="Points / game")
            _style(afig, 360)
            st.plotly_chart(afig, width="stretch")
        if len(teams) > 8:
            st.caption("Quarter lines show the top 8 teams to stay readable.")

        # league-average quarter shape: scored, allowed, net
        st.markdown("**League quarter shape** — average points scored & allowed")
        lf = [sum(qfor[t].get(q, 0) for t in teams) /
              max(sum(gp[t] for t in teams), 1) for q in allq]
        la = [sum(qagn[t].get(q, 0) for t in teams) /
              max(sum(gp[t] for t in teams), 1) for q in allq]
        lfig = go.Figure()
        lfig.add_trace(go.Bar(x=qlabels, y=lf, name="Scored", marker_color=ACCENT,
                              text=[f"{v:.1f}" for v in lf], textposition="outside"))
        lfig.add_trace(go.Bar(x=qlabels, y=la, name="Allowed", marker_color=AWAY,
                              text=[f"{v:.1f}" for v in la], textposition="outside"))
        lfig.update_layout(barmode="group")
        lfig.update_yaxes(title="Points / game (per team)")
        _style(lfig, 320)
        st.plotly_chart(lfig, width="stretch")

        # points per possession by quarter (league + per team), from quarter boxes
        st.markdown("**Points per possession by quarter** (top 8)")
        ppp_fig = go.Figure()
        for t in teams[:8]:
            ys = []
            for q in allq:
                bx = tqbox[t].get(q)
                poss = S.estimate_possessions(bx) if bx else 0
                ys.append(round(bx["PTS"] / poss, 3) if poss > 0 else None)
            ppp_fig.add_trace(go.Scatter(
                x=qlabels, y=ys, mode="lines+markers", connectgaps=True,
                name=name_of.get(t, str(t))))
        ppp_fig.update_yaxes(title="Points / possession")
        _style(ppp_fig, 360)
        st.plotly_chart(ppp_fig, width="stretch")
        st.caption("Quarter PPP uses each team's per-quarter box "
                   "(FGA + TOV possessions — shots + turnovers).")


# _fx_chart() is now rendered under the merged "League landscape" view (below),
# not its own top-level view — see the League-landscape gate near the page tail.


@st.cache_data(ttl=300, show_spinner=False)
def _pt_team_leaders(g, offense):
    """League team leaderboards by set call (one-tap play_type), best PPP first
    on offense / fewest allowed first on defense."""
    return PT.league_named_playtype_leaders(gender=g, offense=offense)


@st.cache_data(ttl=300, show_spinner=False)
def _pt_player_leaders(g):
    """Per-player PPP by set call, league-percentiled — keyed by player_id."""
    return PT.player_named_playtype_percentiles(gender=g)


@st.cache_data(ttl=300, show_spinner=False)
def _pt_player_meta(g):
    """player_id → (name, team) for labelling the play-type player board."""
    return {pid: (r["name"], r.get("team", ""))
            for pid, r in PR.player_stat_table(gender=g, min_games=1).items()}


@st.cache_data(ttl=300, show_spinner=False)
def _def_team_leaders(g, offense):
    """League team leaderboards by DEFENSIVE SCHEME (one-tap defense tag): fewest
    points allowed first on defense (offense=False), most scored first on offense.
    The defensive companion to _pt_team_leaders."""
    return DEF.league_defense_leaders(gender=g, offense=offense)


@st.cache_data(ttl=300, show_spinner=False)
def _def_player_faced(g):
    """Per-player PPP by the defense FACED, league-percentiled — how each scorer
    handles each scheme thrown at them (keyed by player_id)."""
    return DEF.player_defenses_faced(gender=g)


@st.cache_data(ttl=300, show_spinner=False)
def _edge_boards(g):
    """League-wide player-edge leaderboards (shared with the Players Lab tab)."""
    return PE.edge_boards(gender=g)


_GAME_TYPES = ["Regular", "District", "Rivalry", "Tournament", "Showcase", "Playoff"]


@st.cache_data(ttl=600, show_spinner=False)
def _type_game_ids(g, game_type, season="Current"):
    """Game ids of `game_type` for gender `g` in `season` (played games only).
    'Regular' also picks up untyped games (NULL/'') — the default type."""
    if game_type == "Regular":
        rows = query(
            """SELECT g.id FROM games g JOIN teams t ON t.id=g.team1_id
               WHERE g.season=? AND t.gender=? AND g.home_score IS NOT NULL
                 AND (g.game_type='Regular' OR g.game_type IS NULL OR g.game_type='')""",
            (season, g))
    else:
        rows = query(
            """SELECT g.id FROM games g JOIN teams t ON t.id=g.team1_id
               WHERE g.season=? AND t.gender=? AND g.home_score IS NOT NULL
                 AND g.game_type=?""", (season, g, game_type))
    return tuple(r["id"] for r in rows)


@st.cache_data(ttl=600, show_spinner=False)
def _type_power(g, game_type, season="Current"):
    """Opponent-adjusted power/record over just this game type's games (every team
    with a game of that type). {} when the type has no games."""
    gids = _type_game_ids(g, game_type, season)
    return (TR.score_ratings(gender=g, game_ids=list(gids), season=season)
            if gids else {})


@st.cache_data(ttl=600, show_spinner=False)
def _type_stat_table(g, game_type, season="Current"):
    """Team tracked-stat table scoped to this game type's tracked games (efficiency
    in-type; record cols may be season-wide). [] when no tracked game of the type."""
    gids = _type_game_ids(g, game_type, season)
    return (LA.team_stat_table(gender=g, game_ids=list(gids), season=season)
            if gids else [])


# Stakes weights: how much the two teams' QUALITY and an UPSET lift a game's
# excitement. Tuned to the founder's ordering — a #1-vs-#2 back-and-forth at a
# 3.7 raw GEI should edge a #450-vs-#415 game at 4.2, and a competitive big
# upset (#250 over #20) lands between the two. Multiplicative so a blowout's
# low GEI is never rescued by stakes alone.
_GEI_QUAL_W = 0.45      # weight on the two teams' mean quality percentile
_GEI_UPSET_W = 0.60     # weight on the normalized rank gap when the underdog won


@st.cache_data(ttl=600, show_spinner=False)
def _gei_board(g, season="Current", _scored=None):
    """Game Excitement Index for every tracked game of gender `g` in `season`,
    ranked most-dramatic first with a STAKES adjustment. Rebuilds each game's
    scoring timeline → win-prob curve → GEI (same pipeline the box score uses),
    then multiplies by 1 + quality + upset stakes so a marquee thriller outranks
    an equally-frantic bottom-of-the-league game and a live upset gets its due.
    `scored` (team_ratings.score_ratings) supplies the ranks; without it the
    board falls back to raw GEI (stakes = 0). Tracked games only."""
    import helpers.win_probability as WP
    import helpers.gameflow as GF
    rows = query(
        """SELECT g.id, g.date, g.team1_id, g.team2_id, g.home_score, g.away_score,
                  t1.name AS n1, t2.name AS n2
           FROM games g JOIN teams t1 ON t1.id=g.team1_id
                        JOIN teams t2 ON t2.id=g.team2_id
           WHERE g.tracked=1 AND g.season=? AND t1.gender=?""",
        (SEAS.ACTIVE if SEAS.is_current(season) else season, g))
    if not rows:
        return []
    scored = _scored or {}
    n_teams = len(scored) or 1

    def _q(tid):
        """A team's quality percentile in [0,1] (1 = best). None if unranked."""
        rk = (scored.get(tid) or {}).get("Rank")
        if rk is None or n_teams < 2:
            return None
        return 1.0 - (rk - 1) / (n_teams - 1)

    ev_by = defaultdict(list)
    for e in S.fetch_events([r["id"] for r in rows]):
        ev_by[e["game_id"]].append(e)
    out = []
    for r in rows:
        scoring = [e for e in ev_by.get(r["id"], [])
                   if e["event_type"] in ("shot", "free_throw")
                   and e.get("shot_result") == "make"]
        if len(scoring) < 4:
            continue
        scoring.sort(key=GF.elapsed)
        times, hc, ac, h, a = [0.0], [0], [0], 0, 0
        for e in scoring:
            pts = e["shot_type"] if e["event_type"] == "shot" else 1
            if e["shooter_team_id"] == r["team1_id"]:
                h += pts
            elif e["shooter_team_id"] == r["team2_id"]:
                a += pts
            times.append(GF.elapsed(e)); hc.append(h); ac.append(a)
        end_t = times[-1] or WP.GAME_SECONDS
        times.append(end_t); hc.append(h); ac.append(a)
        curve = WP.wp_curve(list(zip(times, [x - y for x, y in zip(hc, ac)])),
                            total_secs=end_t)
        if len(curve) < 2:
            continue
        summ = WP.summarize(curve)
        gei = summ["gei"]

        # ── stakes: mean quality of the two teams + an upset kicker ──────────
        q1, q2 = _q(r["team1_id"]), _q(r["team2_id"])
        qual = ((q1 + q2) / 2) if (q1 is not None and q2 is not None) else 0.0
        upset = 0.0
        rk1 = (scored.get(r["team1_id"]) or {}).get("Rank")
        rk2 = (scored.get(r["team2_id"]) or {}).get("Rank")
        if (rk1 and rk2 and r["home_score"] is not None
                and r["away_score"] != r["home_score"] and n_teams > 1):
            win_rk = rk1 if r["home_score"] > r["away_score"] else rk2
            los_rk = rk2 if r["home_score"] > r["away_score"] else rk1
            if win_rk > los_rk:                    # worse-seeded team won
                upset = (win_rk - los_rk) / (n_teams - 1)
        stakes = _GEI_QUAL_W * qual + _GEI_UPSET_W * upset
        out.append({"date": r["date"], "matchup": f'{r["n1"]} vs {r["n2"]}',
                    "score": f'{r["home_score"]}-{r["away_score"]}',
                    "gei": gei, "adj_gei": gei * (1 + stakes),
                    "stakes": stakes, "qual": qual, "upset": upset,
                    "label": summ["label"]})
    out.sort(key=lambda d: -d["adj_gei"])
    return out


def _fx_evr():
    st.caption(
        "The whole field at a glance — the league-wide companion to the Tracked "
        "tab. **Results-only** views (landscape, tiers, Pythagoras, momentum, "
        "network) cover every team; the tracked KenPom map uses possession data. "
        "Matchup predictions and simulations now live on the War Room page.")

    ts = pack["ts"]
    pteams = pack["teams"]
    sv = list(scored.values())

    (lab_land, lab_tier, lab_pyth, lab_mo, lab_net, lab_pl, lab_pt, lab_def,
     lab_exc, lab_gt, lab_runs) = st.tabs(
        ["Landscape", "Power tiers", "Pythagoras & luck",
         "Momentum", "Win network", "Player edge", "Play types", "Defense",
         "Excitement", "By game type", "Runs"])

    # ──────────────────────────────────────────────────────────────────────
    #  RUNS — 10-0 runs made / given up, and whether run games get won
    # ──────────────────────────────────────────────────────────────────────
    with lab_runs:
        st.caption(
            "Scoring runs across the tracked field: a run = **10-0** or better "
            "(unanswered points). Garbage-time runs (started in the 4th up/down "
            "20+) are excluded. Length matters — a 4-minute run is a string of "
            "defensive stops; a 30-second flurry is answerable.")
        _rt = _runs_table(gender, _VISK, season_pick)
        if not _rt:
            st.info("No tracked games in the pool yet — runs read from "
                    "play-by-play.")
        else:
            def _bc_rec(bc, keys):
                w = sum(bc[k][0] for k in keys)
                l = sum(bc[k][1] for k in keys)
                return f"{w}-{l}"
            _rrows = _filter_rows([{
                "Team": name_of.get(t, f"#{t}"), "class": class_of.get(t),
                "GP": p["gp"],
                "10-0 / g": round(p["made_pg"], 2),
                "Given up / g": round(p["allowed_pg"], 2),
                "6-0 / g": round(p["made6_pg"], 2),
                "Biggest": p["biggest"] or None,
                "Avg len (s)": (round(p["avg_secs"]) if p["avg_secs"] is not None
                                else None),
                "After run (±2m)": (round(p["avg_momentum"], 1)
                                    if p["avg_momentum"] is not None else None),
                "W-L w/ run": _bc_rec(p["by_count"], (1, 2, "3+")),
                "W-L no run": _bc_rec(p["by_count"], (0,)),
            } for t, p in _rt.items()])
            _rrows.sort(key=lambda r: -(r["10-0 / g"] or 0))
            if _rrows:
                st.dataframe(pd.DataFrame(_rrows).drop(columns=["class"]),
                             hide_index=True, width="stretch", key="lab_runs_df")
                st.caption(f"{len(_rrows)} team(s) · 'W-L w/ run' = record in "
                           "games with at least one 10-0 run of their own · "
                           "'After run' = avg net points in the 2 minutes after "
                           "their runs end (does the surge carry?). Scoped by "
                           "the Class / min-games filter above.")
            else:
                st.info("No teams match the current Class / min-games filter.")

    # ──────────────────────────────────────────────────────────────────────
    #  BY GAME TYPE — power / record / efficiency scoped to one game_type
    # ──────────────────────────────────────────────────────────────────────
    with lab_gt:
        st.warning("🧪 **Experimental** — sparse types (playoffs, ~1-3 games/team) "
                   "make the opponent-adjusted power noisy. Read record + margin as "
                   "the firmer signal; the power/efficiency is directional.")
        st.caption("How teams rank WITHIN one game type — their playoff / district / "
                   "rivalry self, not the whole season. Set a game's type on the "
                   "Roster & District page.")
        _gt = st.selectbox("Game type", _GAME_TYPES, key="lab_gt_type")
        _gt_view = st.radio(
            "View", ["All games — power & record", "Tracked — efficiency"],
            horizontal=True, key="lab_gt_view")
        if _gt_view.startswith("All"):
            _sc = _type_power(gender, _gt, season_pick)
            if not _sc:
                st.info(f"No **{_gt}** games yet. Set game types on the Roster & "
                        "District page (bulk-set makes playoffs quick).")
            else:
                # honour the page-level Class / min-games filter (min games here =
                # games IN this type, since the rows are already type-scoped).
                _rows = _filter_rows(
                    sorted(_sc.values(), key=lambda r: (r.get("Rank") or 1e9)))
                if not _rows:
                    st.info("No teams match the current Class / min-games filter "
                            "(above). Widen it or lower the games threshold.")
                else:
                    _df = pd.DataFrame([{
                        "Rank": r.get("Rank"), "Team": r.get("name"), "GP": r.get("GP"),
                        "W-L": f"{r.get('W', 0)}-{r.get('L', 0)}",
                        "MOV": (round(r["MOV"], 1) if r.get("MOV") is not None else None),
                        "Power": (round(r["Power"], 1) if r.get("Power") is not None else None),
                        "Rating": (round(r["Rating"], 2) if r.get("Rating") is not None else None),
                        "AdjNet": (round(r["AdjNet"], 1) if r.get("AdjNet") is not None else None),
                        "SOS": (round(r["SOS"], 1) if r.get("SOS") is not None else None),
                    } for r in _rows])
                    st.dataframe(
                        _df, hide_index=True, width="stretch", key="lab_gt_power",
                        column_config={"Power": st.column_config.ProgressColumn(
                            "Power", format="%.1f", min_value=0, max_value=100)})
                    st.caption(f"{len(_rows)} team(s) · opponent-adjusted over just "
                               f"the {_gt} games · scoped by the Class / min-games "
                               "filter above.")
        else:
            _tt = [r for r in _type_stat_table(gender, _gt, season_pick)
                   if r.get("Class") in _PICKED_CLASSES
                   and (r.get("Trk GP") or 0) >= _MIN_GP]
            if not _tt:
                st.info(f"No **tracked** {_gt} games match — efficiency needs a "
                        "tracked game of this type within the Class / min-games "
                        "filter above.")
            else:
                st.dataframe(pd.DataFrame(_tt), hide_index=True, width="stretch",
                             key="lab_gt_eff")
                st.caption(f"Efficiency scoped to tracked {_gt} games (Class / "
                           "min-games filter applied). Record / results columns may "
                           "reflect the full season.")

    # ──────────────────────────────────────────────────────────────────────
    #  EXCITEMENT — Game Excitement Index leaderboard (tracked games)
    # ──────────────────────────────────────────────────────────────────────
    with lab_exc:
        # Excitement is per-game and season-scoped, so it works on archives too
        # (unlike the league-wide tag surfaces) — only the paid-pool lock gates it.
        _exc_lock = _paid_pool_lock()
        if _exc_lock:
            st.info(_exc_lock)
        else:
            st.caption(
                "The most dramatic tracked games by **Adjusted GEI** — the Game "
                "Excitement Index (total win-probability movement, length-"
                "normalized) lifted by the **stakes**: how good the two teams are "
                "and whether it was an upset. A #1-vs-#2 thriller outranks an "
                "equally-frantic bottom-of-the-league game, and a live upset gets "
                "its due — but a wire-to-wire blowout still sinks (low GEI).")
            _board = _gei_board(gender, season_pick, scored)
            if not _board:
                st.caption("No tracked games with a scoring timeline yet — track a "
                           "game in the Game Tracker and its GEI shows here.")
            else:
                _bdf = pd.DataFrame([{
                    "Game": d["matchup"], "Score": d["score"], "Date": d["date"],
                    "Adj GEI": round(d["adj_gei"], 2),
                    "GEI": round(d["gei"], 2),
                    "Stakes": (f"+{d['stakes'] * 100:.0f}%"
                               + ("  ⚡upset" if d["upset"] > 0.05 else "")),
                    "Drama": d["label"],
                } for d in _board[:25]])
                st.dataframe(
                    _bdf, hide_index=True, width="stretch",
                    column_config={"Adj GEI": st.column_config.ProgressColumn(
                        "Adj GEI", format="%.2f", min_value=0,
                        max_value=max(4.0, _board[0]["adj_gei"]))})
                st.caption("**Adj GEI** = GEI × (1 + stakes); Stakes = "
                           f"{int(_GEI_QUAL_W * 100)}% × the two teams' mean "
                           f"quality + {int(_GEI_UPSET_W * 100)}% × the upset "
                           "margin (⚡ = the worse-seeded team won). Sorted by "
                           "Adj GEI; raw GEI shown alongside.")

    # ──────────────────────────────────────────────────────────────────────
    #  PLAY TYPES — league leaders by one-tap set call (team + player)
    # ──────────────────────────────────────────────────────────────────────
    with lab_pt:
        _pt_lock = _archive_note() or _paid_pool_lock()  # current-only tag surface
        if _pt_lock:
            st.info(_pt_lock)
        else:
            st.caption(
                "League leaders by **set call** — the one-tap play type on each "
                "shot. **Offense** = who runs the action best (most points per "
                "possession); **Defense** = who defends it best (fewest points "
                "allowed). Each row is tiered vs the league on that set.")
            _pt_side = st.radio("Side", ["Offense", "Defense"], horizontal=True,
                                key="pt_lead_side")
            _pt_off = _pt_side == "Offense"
            _pt_teams = _pt_team_leaders(gender, _pt_off)
            if not _pt_teams:
                st.caption("No tagged plays yet — add a one-tap **Play type** to a "
                           "shot in the Game Tracker and these boards fill in.")
            else:
                _pt_lbl = dict(PT.NAMED_PLAY_TYPES)
                _pt_keys = [k for k, _ in PT.NAMED_PLAY_TYPES if k in _pt_teams]
                _pt_pick = st.selectbox(
                    "Set call", _pt_keys, key="pt_lead_set",
                    format_func=lambda k: _pt_lbl.get(k, k))
                _pt_blk = _pt_teams[_pt_pick]
                _pt_lg = _pt_blk.get("lg_ppp")
                _lab_hdr(f"{_pt_blk['label']} — "
                         f"{'best offense' if _pt_off else 'best defense'}")
                if _pt_lg is not None:
                    st.caption(f"League average on this set: **{_pt_lg:.2f}** PPP")
                _pt_trows = [{
                    "Team": name_of.get(L["team_id"], str(L["team_id"])),
                    "PPP": round(L["PPP"], 2),
                    "FG%": (round(L["FG%"]) if L["FG%"] is not None else None),
                    "Poss": L["poss"],
                    "Share": (round(L["share"] * 100)
                              if L["share"] is not None else None),
                    "Pct": (round(L["pct"]) if L["pct"] is not None else None),
                    "Tier": L["tier"], "_c": L["color"]}
                    for L in _pt_blk["leaders"]]
                st.dataframe(
                    pd.DataFrame(_pt_trows).style.apply(
                        lambda r: [f"color:{r['_c']}"] * len(r), axis=1),
                    hide_index=True, width="stretch",
                    column_order=["Team", "PPP", "FG%", "Poss", "Share",
                                  "Pct", "Tier"],
                    column_config={
                        "FG%": st.column_config.NumberColumn(format="%d%%"),
                        "Share": st.column_config.NumberColumn(format="%d%%"),
                        "Pct": st.column_config.NumberColumn(
                            "Lg %ile", help="League percentile on this set")})

                # ── PLAYER board for the same set: a player's own PPP finishing
                #    the action, league-percentiled (8+ tagged possessions) ──
                st.markdown("<div class='lab-hdr'>Top finishers</div>",
                            unsafe_allow_html=True)
                _pt_pl = _pt_player_leaders(gender)
                _pt_meta = _pt_player_meta(gender)
                _pt_prows = sorted(
                    ((c["PPP"], pid, c) for pid, d in _pt_pl.items()
                     if (c := d.get(_pt_pick)) and c["poss"] >= 8),
                    key=lambda t: -t[0])[:12]
                st.caption("Players finishing this set themselves — most points "
                           "per possession (8+ poss).")
                if _pt_prows:
                    st.dataframe(pd.DataFrame([{
                        "Player": _pt_meta.get(pid, ("?", ""))[0],
                        "Team": _pt_meta.get(pid, ("?", ""))[1],
                        "PPP": round(c["PPP"], 2),
                        "FG%": (round(c["FG%"]) if c["FG%"] is not None else None),
                        "Poss": c["poss"],
                        "Pct": (round(c["pct"]) if c["pct"] is not None else None),
                        "Tier": c["tier"], "_c": c["color"]}
                        for _v, pid, c in _pt_prows]).style.apply(
                            lambda r: [f"color:{r['_c']}"] * len(r), axis=1),
                        hide_index=True, width="stretch",
                        column_order=["Player", "Team", "PPP", "FG%", "Poss",
                                      "Pct", "Tier"],
                        column_config={
                            "FG%": st.column_config.NumberColumn(format="%d%%"),
                            "Pct": st.column_config.NumberColumn(
                                "Lg %ile", help="League percentile on this set")})
                else:
                    st.caption("No player has 8+ tagged possessions on this set "
                               "yet.")

    # ──────────────────────────────────────────────────────────────────────
    #  DEFENSE — league leaders by defensive SCHEME (the defensive companion
    #  to Play types: man / 2-3 / press / trap / junk, team board + scorers)
    # ──────────────────────────────────────────────────────────────────────
    with lab_def:
        _def_lock = _archive_note() or _paid_pool_lock()  # current-only tag surface
        if _def_lock:
            st.info(_def_lock)
        else:
            st.caption(
                "League leaders by **defensive scheme** — the one-tap defense tag. "
                "**Defense** = who runs the scheme best (fewest points allowed); "
                "**Offense** = who attacks it best (most points scored). Each row is "
                "tiered vs the league on that scheme.")
            _df_side = st.radio("Side", ["Defense", "Offense"], horizontal=True,
                                key="def_lead_side")
            _df_off = _df_side == "Offense"
            _df_teams = _def_team_leaders(gender, _df_off)
            if not _df_teams:
                st.caption("No tagged defenses yet — set the **Defense** in the Game "
                           "Tracker (man, 2-3, 1-3-1, presses…); it's sticky, so one "
                           "tap covers a stretch. These boards fill in as you tag.")
            else:
                _df_lbl = {k: l for k, l, _f in DEF.DEFENSES}
                _df_keys = [k for k, _l, _f in DEF.DEFENSES if k in _df_teams]
                _df_pick = st.selectbox(
                    "Scheme", _df_keys, key="def_lead_scheme",
                    format_func=lambda k: _df_lbl.get(k, k))
                _df_blk = _df_teams[_df_pick]
                _df_lg = _df_blk.get("lg_ppp")
                _lab_hdr(f"{_df_blk['label']} — "
                         f"{'best offense' if _df_off else 'best defense'}")
                if _df_lg is not None:
                    st.caption(f"League average on this scheme: **{_df_lg:.2f}** PPP")
                _df_trows = [{
                    "Team": name_of.get(L["team_id"], str(L["team_id"])),
                    "PPP": round(L["PPP"], 2),
                    "FG%": (round(L["FG%"]) if L["FG%"] is not None else None),
                    "Poss": L["poss"],
                    "Share": (round(L["share"] * 100)
                              if L["share"] is not None else None),
                    "Pct": (round(L["pct"]) if L["pct"] is not None else None),
                    "Tier": L["tier"], "_c": L["color"]}
                    for L in _df_blk["leaders"]]
                st.dataframe(
                    pd.DataFrame(_df_trows).style.apply(
                        lambda r: [f"color:{r['_c']}"] * len(r), axis=1),
                    hide_index=True, width="stretch",
                    column_order=["Team", "PPP", "FG%", "Poss", "Share",
                                  "Pct", "Tier"],
                    column_config={
                        "FG%": st.column_config.NumberColumn(format="%d%%"),
                        "Share": st.column_config.NumberColumn(format="%d%%"),
                        "Pct": st.column_config.NumberColumn(
                            "Lg %ile", help="League percentile on this scheme")})

                # ── PLAYER board: who SCORES best facing this scheme (defense is a
                #    team concept, so the player read is offense-only), 8+ poss ──
                st.markdown("<div class='lab-hdr'>Top scorers vs this scheme</div>",
                            unsafe_allow_html=True)
                _df_pl = _def_player_faced(gender)
                _df_meta = _pt_player_meta(gender)
                _df_prows = sorted(
                    ((c["PPP"], pid, c) for pid, d in _df_pl.items()
                     if (c := d.get(_df_pick)) and c["poss"] >= DEF.MIN_PLAYER_POSS),
                    key=lambda t: -t[0])[:12]
                st.caption("Players scoring best against this scheme — most points "
                           "per possession (8+ poss faced).")
                if _df_prows:
                    st.dataframe(pd.DataFrame([{
                        "Player": _df_meta.get(pid, ("?", ""))[0],
                        "Team": _df_meta.get(pid, ("?", ""))[1],
                        "PPP": round(c["PPP"], 2),
                        "FG%": (round(c["FG%"]) if c["FG%"] is not None else None),
                        "Poss": c["poss"],
                        "Pct": (round(c["pct"]) if c["pct"] is not None else None),
                        "Tier": c["tier"], "_c": c["color"]}
                        for _v, pid, c in _df_prows]).style.apply(
                            lambda r: [f"color:{r['_c']}"] * len(r), axis=1),
                        hide_index=True, width="stretch",
                        column_order=["Player", "Team", "PPP", "FG%", "Poss",
                                      "Pct", "Tier"],
                        column_config={
                            "FG%": st.column_config.NumberColumn(format="%d%%"),
                            "Pct": st.column_config.NumberColumn(
                                "Lg %ile", help="League percentile vs this scheme")})
                else:
                    st.caption("No player has 8+ tagged possessions vs this scheme "
                               "yet.")

    # ──────────────────────────────────────────────────────────────────────
    #  PLAYER EDGE — league-wide player leaders in the tracked-edge metrics
    # ──────────────────────────────────────────────────────────────────────
    with lab_pl:
        # League-wide, multi-team player tracked depth (SMOE / hand-split / Def WPA)
        # → Paid AND league-wide (Coaches' Co-op).
        _pl_lock = _archive_note() or _paid_pool_lock()  # current-only edge surface
        if _pl_lock:
            st.info(_pl_lock)
        else:
            st.caption("League-wide player leaders in the **tracked-edge** reads — "
                       "shot-making over expected, who to force off their hand, "
                       "defensive win value, clutch, self-creation, efficiency, "
                       "disruption and rim finishing. Each gated by sample.")
            _render_edge(_edge_boards(gender), key_prefix="rk_edge")

    # ──────────────────────────────────────────────────────────────────────
    #  LANDSCAPE
    # ──────────────────────────────────────────────────────────────────────
    with lab_land:
        _lab_hdr("Efficiency landscape — adjusted offense vs defense")
        st.caption("Every team by opponent-adjusted points scored (x) and allowed "
                   "(y, reversed so up = better defense). Crosshairs = league "
                   "average; top-right = elite both ends. Bubble & color = Power.")
        xs = [s["xPPG"] for s in sv]
        ys = [s["xoPPG"] for s in sv]
        powers = [s["Power"] for s in sv]
        txt = [f"#{s['Rank']} {s['name']} ({s['class']})" for s in sv]
        land = go.Figure(go.Scatter(
            x=xs, y=ys, mode="markers",
            marker=dict(size=[max(7, p / 4) for p in powers], color=powers,
                        colorscale=DIVERGE, showscale=True, cmin=0, cmax=100,
                        colorbar=dict(title="Power", thickness=12),
                        line=dict(width=0.5, color="#0d1117")),
            text=txt,
            hovertemplate="%{text}<br>Adj O %{x:.1f} · Adj D %{y:.1f}"
                          "<extra></extra>"))
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        land.add_vline(x=mx, line=dict(color="#30363d", dash="dot"))
        land.add_hline(y=my, line=dict(color="#30363d", dash="dot"))
        land.update_xaxes(title="Adjusted offense (xPPG) →")
        land.update_yaxes(title="← Adjusted defense (xoPPG) · up = better",
                          autorange="reversed")
        _style(land, 540)
        st.plotly_chart(land, width="stretch", key="lab_land")

        # KenPom map is possession-based (ORtg/DRtg/Pace/Net per-100) AND multi-team
        # → Paid + league-wide. The efficiency landscape above is box-derived (xPPG)
        # and stays public.
        _land_lock = _paid_pool_lock()
        if _land_lock:
            st.info(_land_lock)
        elif pteams:
            _lab_hdr("Tracked KenPom map — efficiency per 100 possessions")
            ortg = [ts[t]["ORtg"] for t in pteams]
            drtg = [ts[t]["DRtg"] for t in pteams]
            pace = [ts[t]["Pace"] for t in pteams]
            net = [ts[t]["NetRtg"] for t in pteams]
            lbl = [name_of[t] for t in pteams]
            kp = go.Figure(go.Scatter(
                x=ortg, y=drtg, mode="markers+text", text=lbl,
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=[max(10, p / 2) for p in pace], color=net,
                            colorscale=DIVERGE, cmid=0, showscale=True,
                            colorbar=dict(title="Net", thickness=12),
                            line=dict(width=1, color="#30363d")),
                hovertemplate="%{text}<br>ORtg %{x:.1f} · DRtg %{y:.1f}"
                              "<extra></extra>"))
            kp.add_vline(x=sum(ortg) / len(ortg),
                         line=dict(color="#30363d", dash="dot"))
            kp.add_hline(y=sum(drtg) / len(drtg),
                         line=dict(color="#30363d", dash="dot"))
            kp.update_xaxes(title="Offensive rating →")
            kp.update_yaxes(title="← Defensive rating · lower better",
                            autorange="reversed")
            _style(kp, 460)
            st.plotly_chart(kp, width="stretch", key="lab_kenpom")
            st.caption("For a single team's gauges and Team-DNA radar, open that "
                       "team in **Team Dashboard → Lab → Advanced** (Efficiency & "
                       "DNA).")
        else:
            empty_state("No tracked games yet",
                        "Track games to unlock the possession-based KenPom map.")

    # ──────────────────────────────────────────────────────────────────────
    #  POWER TIERS
    # ──────────────────────────────────────────────────────────────────────
    with lab_tier:
        _lab_hdr("Power tiers")
        st.caption("Teams bucketed by Power (0-100, 50 = league average). "
                   + " · ".join(f"{name.split(' ')[0]} ≥ {cut:g}"
                                for name, cut, _ in TIER_CUTS)
                   + f" · {TIER_FLOOR[0].split(' ')[0]} < {TIER_CUTS[-1][1]:g}.")
        tier_order = ["S · ELITE", "A · CONTENDER", "B · SOLID",
                      "C · MIDDLING", "D · REBUILDING"]
        buckets = defaultdict(list)
        for s in sorted(sv, key=lambda r: r["Rank"]):
            tname, _ = _tier(s["Power"])
            buckets[tname].append(s)
        tcols = st.columns(5)
        for i, tname in enumerate(tier_order):
            members = buckets.get(tname, [])
            _, tclr = _tier({"S · ELITE": 70, "A · CONTENDER": 62, "B · SOLID": 54,
                             "C · MIDDLING": 46, "D · REBUILDING": 40}[tname])
            chips = "".join(
                f"<div style='font-size:12px;color:#c9d1d9;margin:3px 0;"
                f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
                f"<b style='color:{tclr}'>{m['Power']:.0f}</b> "
                f"#{m['Rank']} {m['name']}</div>"
                for m in members[:8])
            more = (f"<div style='font-size:10px;color:#6e7681;margin-top:4px'>"
                    f"+{len(members) - 8} more</div>") if len(members) > 8 else ""
            tcols[i].markdown(
                f"<div class='glass-tile' style='text-align:left;height:100%'>"
                f"<div class='glass-label' style='color:{tclr}'>{tname}</div>"
                f"<div class='glass-value' style='color:{tclr};font-size:22px'>"
                f"{len(members)}</div>{chips}{more}</div>",
                unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Power distribution by class**")
            classes = sorted({s["class"] for s in sv},
                             key=lambda c: TR._CLASS_RANK.get(c, 99))
            vio = go.Figure()
            for c in classes:
                sub = [s for s in sv if s["class"] == c]
                vals = [s["Power"] for s in sub]
                nms = [s["name"] for s in sub]
                vio.add_trace(go.Violin(
                    y=vals, name=c, box_visible=True, meanline_visible=True,
                    points="all", marker=dict(size=3), line=dict(width=1),
                    fillcolor="rgba(88,166,255,0.10)", text=nms,
                    hovertemplate="<b>%{text}</b><br>" + c +
                                  " · Power %{y:.1f}<extra></extra>"))
            vio.update_yaxes(title="Power")
            vio.update_layout(showlegend=False)
            _style(vio, 420)
            st.plotly_chart(vio, width="stretch", key="lab_violin")
        with c2:
            st.markdown("**Overachievers** — Power vs strength of schedule")
            st.caption("Up & right = strong despite a hard slate. Crosshairs = "
                       "league average.")
            sx = [s["SOS"] for s in sv]
            sy = [s["Power"] for s in sv]
            scl = [TR._CLASS_RANK.get(s["class"], 0) for s in sv]
            ov = go.Figure(go.Scatter(
                x=sx, y=sy, mode="markers",
                marker=dict(size=9, color=scl, colorscale="Viridis",
                            showscale=False, line=dict(width=0.5, color="#0d1117")),
                text=[f"{s['name']} ({s['class']})" for s in sv],
                hovertemplate="%{text}<br>SOS %{x:.2f} · Power %{y:.1f}"
                              "<extra></extra>"))
            ov.add_vline(x=sum(sx) / len(sx), line=dict(color="#30363d", dash="dot"))
            ov.add_hline(y=sum(sy) / len(sy), line=dict(color="#30363d", dash="dot"))
            ov.update_xaxes(title="Strength of schedule →")
            ov.update_yaxes(title="Power →")
            _style(ov, 420)
            st.plotly_chart(ov, width="stretch", key="lab_overach")

        st.markdown("**League map** — class → team (size = wins, color = Power)")
        labels, parents, vals, colors = [], [], [], []
        classes = sorted({s["class"] for s in sv},
                         key=lambda c: TR._CLASS_RANK.get(c, 99))
        # children first so each class value == sum of its children (branch=total)
        children = [(s["name"], s["class"], max(s["W"], 0.5), s["Power"])
                    for s in sv]
        cls_val = defaultdict(float)
        cls_pow = defaultdict(list)
        for nm, c, v, p in children:
            cls_val[c] += v
            cls_pow[c].append(p)
        for c in classes:
            labels.append(c)
            parents.append("")
            vals.append(cls_val[c])
            colors.append(sum(cls_pow[c]) / len(cls_pow[c]))
        for nm, c, v, p in children:
            labels.append(nm)
            parents.append(c)
            vals.append(v)
            colors.append(p)
        tree = go.Figure(go.Treemap(
            labels=labels, parents=parents, values=vals, branchvalues="total",
            marker=dict(colors=colors, colorscale=DIVERGE, cmid=50, cmin=0,
                        cmax=100, showscale=True,
                        colorbar=dict(title="Power", thickness=12)),
            hovertemplate="<b>%{label}</b><br>%{value} wins<extra></extra>",
            textfont=dict(size=12)))
        tree.update_layout(template="plotly_dark", height=520,
                           paper_bgcolor="rgba(0,0,0,0)",
                           margin=dict(l=6, r=6, t=10, b=6))
        st.plotly_chart(tree, width="stretch", key="lab_tree")

    # ──────────────────────────────────────────────────────────────────────
    #  PYTHAGORAS & LUCK
    # ──────────────────────────────────────────────────────────────────────
    with lab_pyth:
        _lab_hdr("Pythagorean wins & luck")
        st.caption(
            "Pythagorean expectation predicts win% from points scored vs allowed "
            f"(exponent {LA.PYTHAG_EXP:g}). **Luck** = actual wins − expected "
            "wins: above the line = winning more than the scoring says (clutch or "
            "fortunate); below = underperforming the margins.")
        fids = [t for t in form_stats]
        aw = [form_stats[t]["W"] for t in fids]
        pw = [form_stats[t]["Pyth_W"] for t in fids]
        lk = [form_stats[t]["Luck_wins"] for t in fids]
        nm = [name_of.get(t, str(t)) for t in fids]
        pyfig = go.Figure(go.Scatter(
            x=pw, y=aw, mode="markers",
            marker=dict(size=9, color=lk, colorscale=DIVERGE, cmid=0,
                        showscale=True, colorbar=dict(title="Luck", thickness=12),
                        line=dict(width=0.5, color="#0d1117")),
            text=nm,
            hovertemplate="%{text}<br>Expected %{x:.1f} · Actual %{y} W"
                          "<extra></extra>"))
        hi = max(max(aw, default=1), max(pw, default=1)) + 1
        pyfig.add_trace(go.Scatter(
            x=[0, hi], y=[0, hi], mode="lines", line=dict(color=GREY, dash="dot"),
            hoverinfo="skip", showlegend=False))
        pyfig.update_xaxes(title="Pythagorean (expected) wins →")
        pyfig.update_yaxes(title="Actual wins →")
        _style(pyfig, 480)
        st.plotly_chart(pyfig, width="stretch", key="lab_pyth_scatter")

        c1, c2 = st.columns(2)
        ranked = sorted(fids, key=lambda t: form_stats[t]["Luck_wins"])
        with c1:
            st.markdown("**Luckiest** — most wins above expectation")
            top = list(reversed(ranked[-10:]))
            lf = go.Figure(go.Bar(
                y=[name_of.get(t, str(t)) for t in top][::-1],
                x=[form_stats[t]["Luck_wins"] for t in top][::-1],
                orientation="h", marker_color=GOOD, marker_line_width=0,
                text=[f"{form_stats[t]['Luck_wins']:+.1f}" for t in top][::-1],
                textposition="auto"))
            lf.update_xaxes(title="Wins vs expected")
            _style(lf, 360)
            st.plotly_chart(lf, width="stretch", key="lab_lucky")
        with c2:
            st.markdown("**Unluckiest** — most wins below expectation")
            bot = ranked[:10]
            uf = go.Figure(go.Bar(
                y=[name_of.get(t, str(t)) for t in bot][::-1],
                x=[form_stats[t]["Luck_wins"] for t in bot][::-1],
                orientation="h", marker_color=BAD, marker_line_width=0,
                text=[f"{form_stats[t]['Luck_wins']:+.1f}" for t in bot][::-1],
                textposition="auto"))
            uf.update_xaxes(title="Wins vs expected")
            _style(uf, 360)
            st.plotly_chart(uf, width="stretch", key="lab_unlucky")

    # ──────────────────────────────────────────────────────────────────────
    #  MOMENTUM
    # ──────────────────────────────────────────────────────────────────────
    with lab_mo:
        _lab_hdr("Momentum — recent form vs season")
        st.caption("**mom_delta** = last-5-game average margin minus season "
                   "average margin. Positive = heating up.")
        fids = [t for t in form_stats if form_stats[t]["games"] >= 3]
        ranked = sorted(fids, key=lambda t: form_stats[t]["mom_delta"])
        # show all teams when the field is small, else the 12 coldest + 12 hottest
        if len(fids) > 24:
            show = ranked[:12] + ranked[-12:]
        else:
            show = ranked
        vals = [form_stats[t]["mom_delta"] for t in show]
        mof = go.Figure(go.Bar(
            x=[name_of.get(t, str(t)) for t in show], y=vals,
            marker_color=[GOOD if v >= 0 else BAD for v in vals],
            marker_line_width=0,
            text=[f"{v:+.1f}" for v in vals], textposition="outside"))
        mof.add_hline(y=0, line=dict(color="#30363d"))
        mof.update_yaxes(title="Last-5 MOV − season MOV")
        mof.update_xaxes(tickangle=-45)
        _style(mof, 420)
        st.plotly_chart(mof, width="stretch", key="lab_momentum")

        st.markdown("**Trajectory** — season margin vs last-5 margin")
        st.caption("Above the line = playing better than their season; below = "
                   "cooling off.")
        sx = [form_stats[t]["MOV"] for t in fids]
        sy = [form_stats[t]["l5_mov"] for t in fids]
        traj = go.Figure(go.Scatter(
            x=sx, y=sy, mode="markers",
            marker=dict(size=9, color=[form_stats[t]["mom_delta"] for t in fids],
                        colorscale=DIVERGE, cmid=0, showscale=True,
                        colorbar=dict(title="Δ", thickness=12),
                        line=dict(width=0.5, color="#0d1117")),
            text=[name_of.get(t, str(t)) for t in fids],
            hovertemplate="%{text}<br>Season %{x:+.1f} · Last-5 %{y:+.1f}"
                          "<extra></extra>"))
        lo = min(sx + sy + [0]) - 2
        hh = max(sx + sy + [0]) + 2
        traj.add_trace(go.Scatter(x=[lo, hh], y=[lo, hh], mode="lines",
                                  line=dict(color=GREY, dash="dot"),
                                  hoverinfo="skip", showlegend=False))
        traj.update_xaxes(title="Season margin / game →")
        traj.update_yaxes(title="Last-5 margin / game →")
        _style(traj, 460)
        st.plotly_chart(traj, width="stretch", key="lab_traj")

    # ──────────────────────────────────────────────────────────────────────
    #  WIN NETWORK
    # ──────────────────────────────────────────────────────────────────────
    with lab_net:
        _lab_hdr("Win network — who beat whom")
        st.caption("Each arrow-free link is a head-to-head result; teams sit on "
                   "the ring by rank. Node size = games, color = Power. Filter to "
                   "keep it readable.")
        net = _win_net(gender, scored, season_pick)
        classes = sorted({n["class"] for n in net["nodes"]},
                         key=lambda c: TR._CLASS_RANK.get(c, 99))
        fc1, fc2 = st.columns([2, 1])
        topn = fc1.slider("Show top-N teams (by rank)", 6,
                          min(40, len(net["nodes"])),
                          min(20, len(net["nodes"])), key="lab_net_n")
        pick_cls = fc2.multiselect("Limit to classes", classes, default=[],
                                   key="lab_net_cls")
        nodes = net["nodes"]
        if pick_cls:
            nodes = [n for n in nodes if n["class"] in pick_cls]
        nodes = sorted(nodes, key=lambda n: n["rank"])[:topn]
        keep = {n["id"] for n in nodes}
        if len(nodes) >= 2:
            n_n = len(nodes)
            pos = {}
            for i, n in enumerate(nodes):
                ang = 2 * math.pi * i / n_n
                pos[n["id"]] = (math.cos(ang), math.sin(ang))
            ex, ey = [], []
            for e in net["edges"]:
                if e["winner"] in keep and e["loser"] in keep:
                    x0, y0 = pos[e["winner"]]
                    x1, y1 = pos[e["loser"]]
                    ex += [x0, x1, None]
                    ey += [y0, y1, None]
            netfig = go.Figure()
            netfig.add_trace(go.Scatter(
                x=ex, y=ey, mode="lines",
                line=dict(color="rgba(88,166,255,0.25)", width=1),
                hoverinfo="skip", showlegend=False))
            nx = [pos[n["id"]][0] for n in nodes]
            ny = [pos[n["id"]][1] for n in nodes]
            netfig.add_trace(go.Scatter(
                x=nx, y=ny, mode="markers+text",
                text=[n["name"] for n in nodes], textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=[max(10, n["degree"] * 1.6) for n in nodes],
                            color=[n["power"] for n in nodes], colorscale=DIVERGE,
                            cmin=0, cmax=100, showscale=True,
                            colorbar=dict(title="Power", thickness=12),
                            line=dict(width=1, color="#0d1117")),
                customdata=[[n["rank"], n["W"], n["L"]] for n in nodes],
                hovertemplate="<b>%{text}</b><br>#%{customdata[0]} · "
                              "%{customdata[1]}-%{customdata[2]}<extra></extra>",
                showlegend=False))
            netfig.update_layout(
                template="plotly_dark", height=560,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(visible=False), yaxis=dict(visible=False,
                                                      scaleanchor="x"))
            st.plotly_chart(netfig, width="stretch", key="lab_network")
        else:
            st.info("Not enough teams in this filter to draw a network.")

        # biggest upsets — winner Power far below loser Power. The class filter
        # above extends down here: with classes picked, show only upsets that
        # involve one of those classes ("biggest upsets in 3A").
        _cls_note = (f" · {', '.join(pick_cls)}" if pick_cls else "")
        st.markdown(f"**Biggest upsets** — winners who beat much higher-Power teams"
                    f"{_cls_note}")
        node_cls = {n["id"]: n["class"] for n in net["nodes"]}
        rows = LA._finished_rows(gender, season_pick)
        ups = []
        for g in rows:
            hp, ap = g["home_score"], g["away_score"]
            if hp == ap:
                continue
            win, lose = (g["team1_id"], g["team2_id"]) if hp > ap \
                else (g["team2_id"], g["team1_id"])
            # class filter (extended from the network): keep the game if either
            # team is in a selected class.
            if pick_cls and node_cls.get(win) not in pick_cls \
                    and node_cls.get(lose) not in pick_cls:
                continue
            pw_w = scored.get(win, {}).get("Power")
            pw_l = scored.get(lose, {}).get("Power")
            if pw_w is None or pw_l is None:
                continue
            gap = pw_l - pw_w
            if gap > 0:
                ups.append({"Date": g["date"],
                            "Winner": f"#{rank_of.get(win,'—')} {name_of.get(win,'?')}",
                            "Loser": f"#{rank_of.get(lose,'—')} {name_of.get(lose,'?')}",
                            "Score": f"{max(hp,ap)}-{min(hp,ap)}",
                            "Power gap": round(gap, 1)})
        ups.sort(key=lambda r: r["Power gap"], reverse=True)
        if ups:
            _show = fc2.slider("Upsets to show", 5, min(40, len(ups)),
                               min(12, len(ups)), key="lab_net_ups") \
                if len(ups) > 5 else len(ups)
            st.dataframe(pd.DataFrame(ups[:_show]), hide_index=True, width="stretch")
        else:
            st.info("No upsets match this filter." if pick_cls
                    else "No upsets recorded.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
# ── Merged "League landscape" view ───────────────────────────────────────────
# Team Charts (per-team tracked charts) + League (whole-league lab) were two
# top-level views over the same possession pack. They fold into one view with an
# inner segmented Section selector so only the chosen sub-view's heavy fragment
# runs (st.tabs would compute both bodies — segmented keeps it lazy). Each
# sub-view keeps its ORIGINAL gating: Team Charts behind _paid_pool_lock,
# League (_fx_evr) ungated as before.
if _view == "League landscape":
    _ll = _rkseg("Section", ["Team Charts", "League Lab"],
                 default="Team Charts", key="rk_ll_section") or "Team Charts"
    if _ll == "Team Charts":
        _chart_lock = _paid_pool_lock()
        if _chart_lock:
            st.info(_chart_lock)
        else:
            _fx_chart()
    else:
        _fx_evr()


if _view == "Glossary":
    glossary_tab("rank_gloss")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB — COMPARE  (two teams, head to head)
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _fx_cmp():
    st.caption("Two teams head to head — power and results always; four factors "
               "and efficiency when both teams are tracked.")
    _cts = pack["ts"]
    _cord = sorted(scored, key=lambda t: scored[t]["Rank"])

    def _cfmt(t):
        return f"#{scored[t]['Rank']} {name_of[t]} ({class_of[t]})"

    _cc = st.columns(2)
    cA = _cc[0].selectbox("Team A", _cord, index=0, format_func=_cfmt, key="cmp_a")
    cB = _cc[1].selectbox("Team B", _cord, index=min(1, len(_cord) - 1),
                          format_func=_cfmt, key="cmp_b")
    if cA == cB:
        st.info("Pick two different teams.")
    else:
        _sa, _sb = scored[cA], scored[cB]
        _hm = st.columns(4)
        _hm[0].metric(team_short(name_of[cA]), f"#{_sa['Rank']}",
                      f"Power {_sa['Power']:.0f}", delta_color="off")
        _hm[1].metric("Record", f"{_sa['W']}-{_sa['L']}")
        _hm[2].metric("Record", f"{_sb['W']}-{_sb['L']}")
        _hm[3].metric(team_short(name_of[cB]), f"#{_sb['Rank']}",
                      f"Power {_sb['Power']:.0f}", delta_color="off")

        def _trow(lbl, a, b, hib=True, fmt="{:.1f}", neutral=False):
            try:
                aw = (not neutral) and ((a > b) if hib else (a < b))
                bw = (not neutral) and ((b > a) if hib else (b < a))
            except TypeError:
                aw = bw = False
            ca = f"color:{GOOD};font-weight:800" if aw else "color:#c9d1d9"
            cb = f"color:{GOOD};font-weight:800" if bw else "color:#c9d1d9"
            av = fmt.format(a) if a is not None else "—"
            bv = fmt.format(b) if b is not None else "—"
            return (f"<tr><td style='text-align:right;padding:4px 10px;{ca}'>{av}</td>"
                    f"<td style='text-align:center;color:#8b949e;font-size:11px;"
                    f"text-transform:uppercase;letter-spacing:1px'>{lbl}</td>"
                    f"<td style='padding:4px 10px;{cb}'>{bv}</td></tr>")

        def _ttable(title, rows):
            return (f"<div class='lab-hdr'>{title}</div>"
                    f"<table style='width:100%;border-collapse:collapse'>"
                    f"<tr><th style='text-align:right;color:var(--accent);padding:2px 10px'>"
                    f"{team_short(name_of[cA])}</th><th></th>"
                    f"<th style='text-align:left;color:var(--accent);padding:2px 10px'>"
                    f"{team_short(name_of[cB])}</th></tr>{''.join(rows)}</table>")

        st.markdown(_ttable("Results", [
            _trow("Power", _sa["Power"], _sb["Power"], fmt="{:.0f}"),
            _trow("Adj offense", _sa["xPPG"], _sb["xPPG"]),
            _trow("Adj defense", _sa["xoPPG"], _sb["xoPPG"], hib=False),
            _trow("Adj net", _sa["AdjNet"], _sb["AdjNet"], fmt="{:+.1f}"),
            _trow("Margin / G", _sa["MOV"], _sb["MOV"], fmt="{:+.1f}"),
            _trow("Strength of sched", _sa["SOS"], _sb["SOS"], fmt="{:.0f}"),
        ]), unsafe_allow_html=True)
        st.caption("Green = the better of the two · adj defense, lower is better.")

        # ── head to head: what actually happened, then the model's call ──────
        st.markdown("<div class='lab-hdr'>Head to head</div>",
                    unsafe_allow_html=True)
        _h2h = query("""
            SELECT date, home_score, away_score, team1_id, team2_id
            FROM games
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
              AND ((team1_id=? AND team2_id=?) OR (team1_id=? AND team2_id=?))
            ORDER BY date""", (cA, cB, cB, cA))
        if _h2h:
            # Strict comparisons per side — a tied score is neither team's win.
            def _won_by(m, t):
                if m["home_score"] == m["away_score"]:
                    return False
                home_won = m["home_score"] > m["away_score"]
                return home_won == (m["team1_id"] == t)
            _wa = sum(1 for m in _h2h if _won_by(m, cA))
            _wb = sum(1 for m in _h2h if _won_by(m, cB))
            _ties = len(_h2h) - _wa - _wb
            st.markdown(f"**{team_short(name_of[cA])} {_wa} – "
                        f"{_wb} {team_short(name_of[cB])}**"
                        + (f" ({_ties} tie{'s' if _ties > 1 else ''})"
                           if _ties else "")
                        + " in actual meetings")
            for m in _h2h:
                _aw_won = m["away_score"] > m["home_score"]
                _hm_won = m["home_score"] > m["away_score"]
                st.caption(
                    f"{m['date']} · {name_of[m['team2_id']]} "
                    f"{'**' if _aw_won else ''}{m['away_score']}"
                    f"{'**' if _aw_won else ''} @ {name_of[m['team1_id']]} "
                    f"{'**' if _hm_won else ''}{m['home_score']}"
                    f"{'**' if _hm_won else ''}")
        else:
            st.caption("These two haven't played each other yet.")

        _pp = PRED.predict_game(cA, cB, scored=scored, tracked=tracked,
                                home=None)
        if _pp:
            _pm = st.columns(3)
            _pm[0].metric(team_short(name_of[cA]), f"{_pp['pf_a']:.0f}",
                          f"{_pp['win_prob_a'] * 100:.0f}% win",
                          delta_color="off")
            _pm[1].metric("Neutral-floor spread",
                          f"{team_short(name_of[_pp['favorite']])} "
                          f"−{_pp['spread']:.1f}",
                          _pp["confidence"], delta_color="off")
            _pm[2].metric(team_short(name_of[cB]), f"{_pp['pf_b']:.0f}",
                          f"{_pp['win_prob_b'] * 100:.0f}% win",
                          delta_color="off")
            st.caption("If they met on a neutral floor tonight — the full "
                       "margin breakdown and simulation live in the War Room.")

        _ma, _mb = _cts.get(cA), _cts.get(cB)
        # The tracked profile reveals BOTH teams' possession depth side by side, so
        # require entitlement to each (own team Paid; another team needs you to be
        # League-wide). The read-filter already strips non-pooled teams from `_cts`,
        # so a missing _ma/_mb falls through to the neutral "both tracked" note.
        _cmp_ident = AUTH.current_user()
        _cmp_ok = (ENT.can_see_team_tracked(_cmp_ident, cA)
                   and ENT.can_see_team_tracked(_cmp_ident, cB))
        if _ma and _mb and _cmp_ok:
            st.markdown(_ttable("Tracked profile — four factors & efficiency", [
                _trow("eFG%", _ma["eFG"], _mb["eFG"]),
                _trow("Turnover %", _ma["TOVpct"], _mb["TOVpct"], hib=False),
                _trow("Off reb %", _ma["ORBpct"], _mb["ORBpct"]),
                _trow("FT rate", _ma["FTr"], _mb["FTr"], fmt="{:.2f}"),
                _trow("Off rating", _ma["ORtg"], _mb["ORtg"]),
                _trow("Def rating", _ma["DRtg"], _mb["DRtg"], hib=False),
                _trow("Net rating", _ma["NetRtg"], _mb["NetRtg"], fmt="{:+.1f}"),
                _trow("Pace", _ma["Pace"], _mb["Pace"], fmt="{:.0f}", neutral=True),
                _trow("Points / poss", _ma["PPP"], _mb["PPP"], fmt="{:.2f}"),
            ]), unsafe_allow_html=True)
        elif _ma and _mb and not _cmp_ok:
            st.info("🔒 The tracked four-factor & efficiency compare is **Paid**. "
                    "Join the **Coaches' Co-op** (Settings) to scout any team but "
                    "your own — share to scout.")
        else:
            st.info("Four-factor & efficiency compare needs both teams tracked.")


if _view == "Compare":
    _fx_cmp()
