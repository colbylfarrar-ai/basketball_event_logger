"""
8_Officials.py — the officials hub.

Three tabs, all reading from one engine call (helpers/officials.official_overview):

  • Overview    — the league of refs at a glance: leaders + the full sortable table.
  • Charts      — who calls the most fouls, fouls-by-team, home/away lean, and the
                  scoring environment (PPP) of each ref's games.
  • Individual  — one official's deep dive: foul rate, team breakdown, quarter
                  splits, home/away lean, and a game-by-game log.

All math lives in helpers/officials.py (Streamlit-free); this page is display +
controls only.

Data notes the reader should keep in mind:
  - A foul is charged to the player who committed it (secondary_player_id), so
    "fouls against a team" = calls made on that team's players.
  - Only foul events carry an official, and the ref is optional in the tracker —
    so unassigned fouls count toward a game's total but toward no ref.
  - PPP / pace are GAME-level (shared by every ref of a game), not a per-ref skill.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import defaultdict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import helpers.ui as _uimod  # theme tokens read at call time
from helpers.ui import (page_chrome, style_fig as _style, AWAY, CARD_BG, GRID,
                        rgb as _rgb, grid as _grid, page_header, gender_radio,
                        gender_label, empty_state, HEAT)
from helpers.cards import team_short as _team_short, fmt as _fmt, bar_h
from helpers.glossary import glossary_tab
import helpers.officials as OFF
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.seasons as SEAS
from database.db import query

_cfg, ACCENT = page_chrome("Officials")
HOME = ACCENT
_AR, _AG, _AB = _rgb(ACCENT)
_ARGB = f"{_AR},{_AG},{_AB}"


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _scatter(rows, xk, yk, xlab, ylab, xfmt, yfmt, color=ACCENT, qkey="games", qmin=1):
    """Bubble scatter of officials over two metrics, labelled by name."""
    pool = [r for r in rows
            if r.get(xk) is not None and r.get(yk) is not None
            and (r.get(qkey) or 0) >= qmin]
    fig = go.Figure(go.Scatter(
        x=[r[xk] for r in pool], y=[r[yk] for r in pool],
        mode="markers+text", text=[r["name"] for r in pool],
        textposition="top center", textfont=dict(size=9, color="#8b949e"),
        marker=dict(size=[max(9, 5 + r["games"] * 2) for r in pool],
                    color=color, line=dict(width=1, color="#0d1117"),
                    opacity=0.85),
        customdata=[[_fmt(r[xk], xfmt), _fmt(r[yk], yfmt), r["games"]] for r in pool],
        hovertemplate=("%{text}<br>" + xlab + ": %{customdata[0]}<br>"
                       + ylab + ": %{customdata[1]}<br>games: %{customdata[2]}"
                       "<extra></extra>")))
    _style(fig, height=380)
    fig.update_xaxes(title_text=xlab)
    fig.update_yaxes(title_text=ylab)
    return fig


def _leader_bar(rows, key, fmt, color=ACCENT, n=12, height=None, qkey=None, qmin=0):
    """Horizontal bar of the top-n officials by `key` (#1 on top)."""
    pool = [r for r in rows if r.get(key) is not None]
    if qkey:
        pool = [r for r in pool if (r.get(qkey) or 0) >= qmin]
    pool = sorted(pool, key=lambda r: r[key], reverse=True)[:n]
    seq = list(reversed(pool))
    names = [r["name"] for r in seq]
    vals = [r[key] for r in seq]
    texts = [_fmt(v, fmt) for v in vals]
    return bar_h(names, vals, texts, color, height)


# ══════════════════════════════════════════════════════════════════════════════
#  MODERN HEADER HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _glass(col, label, value, sub="", color=None):
    col.markdown(
        f"<div class='glass-tile'><div class='glass-label'>{label}</div>"
        f"<div class='glass-value' style='color:{color or ACCENT}'>{value}</div>"
        f"<div class='glass-sub'>{sub}</div></div>", unsafe_allow_html=True)


def _quadrant(rows, xk, yk, xlab, ylab, xfmt, yfmt, color="#bc8cff", qmin=1):
    """KenPom-style whistle-archetype quadrant with league-avg crosshairs."""
    pool = [r for r in rows if r.get(xk) is not None and r.get(yk) is not None
            and r["games"] >= qmin]
    if not pool:
        return None
    xs = [r[xk] for r in pool]
    ys = [r[yk] for r in pool]
    mx, my = float(np.mean(xs)), float(np.mean(ys))
    fig = go.Figure(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=[r["name"] for r in pool],
        textposition="top center", textfont=dict(size=9, color="#8b949e"),
        marker=dict(size=[max(11, 6 + r["games"] * 2.2) for r in pool],
                    color=color, line=dict(width=1, color="#0d1117"), opacity=0.85),
        customdata=[[_fmt(r[xk], xfmt), _fmt(r[yk], yfmt), r["games"]] for r in pool],
        hovertemplate=("%{text}<br>" + xlab + ": %{customdata[0]}<br>"
                       + ylab + ": %{customdata[1]}<br>games: %{customdata[2]}"
                       "<extra></extra>")))
    fig.add_vline(x=mx, line_dash="dot", line_color="#8b949e", opacity=0.6)
    fig.add_hline(y=my, line_dash="dot", line_color="#8b949e", opacity=0.6)
    _style(fig, height=420)
    fig.update_xaxes(title_text=xlab)
    fig.update_yaxes(title_text=ylab)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER + CONTROLS
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner=False)
def _official_overview(g, gids=None, season=None):
    # gids = read-filter (hashable tuple of game ids) or None = unrestricted.
    # season None = ALL seasons (career view — refs keep the same official_id
    # for ~15-year careers and are never archived at rollover).
    return OFF.official_overview(gender=g, game_ids=(set(gids) if gids else None),
                                 season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _official_environment(g, gids=None, untr=None, season=None):
    # Projection-facing coverage (tracked ∪ untracked boxed). gids/untr = the
    # tracked / untracked read-filters (hashable tuples) or None = unrestricted.
    return OFF.official_environment(
        gender=g, game_ids=(set(gids) if gids else None),
        untracked_ids=(set(untr) if untr else None), season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _official_game_log(off_pk, g, gids=None, season=None):
    return OFF.official_game_log(off_pk, gender=g,
                                 game_ids=(set(gids) if gids else None),
                                 season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _official_ratings(g, gids=None, season=None):
    """The Officials Rating composite (leverage / clutch / play-type bias +
    the 0-100 index). Threads team ranks (all-season pool so a career view
    still gets quality) for the game-leverage term."""
    import helpers.team_ratings as _TR
    scored = {}
    for _szn in ({r["season"] for r in query(
            "SELECT DISTINCT season FROM games WHERE tracked=1")} or {"Current"}):
        try:
            scored.update(_TR.score_ratings(gender=g, season=_szn))
        except Exception:
            pass
    return OFF.official_ratings(gender=g, game_ids=(set(gids) if gids else None),
                                season=season, scored=scored)


hc1, hc2 = st.columns([3, 1])
gender = gender_radio(hc2, default=None, key="off_league", include_all=True)
gender_lbl = "All" if gender is None else gender_label(gender)

# Season scope — officials are CAREER-long (same person, same ID, season after
# season), so the default view aggregates every season they've worked; the picker
# narrows to one season when you want "how did they call it last year". Shown
# only once an archive exists; with a single season the career view IS that season.
_szn_opts = [("__all__", "All seasons (career)")] + SEAS.season_options()
if len(_szn_opts) > 2:
    _slbl = hc2.selectbox("Season", [l for _v, l in _szn_opts], key="off_season")
    _off_season = next(v for v, l in _szn_opts if l == _slbl)
else:
    _off_season = "__all__"
# engine contract: None = all seasons, else the label / 'Current'
_off_season = None if _off_season == "__all__" else _off_season
_is_cur_off = _off_season is not None and SEAS.is_current(_off_season)

# Tier gate: the entire officials hub is built from foul EVENTS attributed to a
# named ref (who called what, when, vs which team) — event-derived analytics, no
# box-only view exists here. Plan-level gate (individual/official data is
# pool-agnostic, per the gating taxonomy), so lock the whole page for Free.
if not ENT.has_paid_plan(AUTH.current_user()):
    with hc1:
        page_header("Officiating Lab",
                    sub=f"{gender_lbl} league · whistle rates, home/away lean, "
                        "foul timing and per-ref breakdowns.")
    st.info("🔒 **Officiating analytics are a Paid feature.** Whistle tightness, "
            "home/away foul lean, foul-timing fingerprints and the per-official "
            "deep dive all come from tracked foul events. Upgrade to unlock the "
            "officials hub.")
    st.stop()

# Read-filter: officials analytics span many teams' games, so scope them to the
# games this viewer may aggregate — a Solo-paid coach sees refs/foul depth over
# their OWN tracked games only; a league-wide coach sees the pooled set; admin sees
# all. (Free is already blocked above — no box-only officials view exists.)
# Season composition: PAST seasons are an open archive, so the career (all-seasons)
# view = the viewer's CURRENT visible set ∪ every past season's tracked games; a
# single past season is fully open (no filter); the current season keeps the
# per-viewer set.
_off_vis = ENT.visible_tracked_game_ids(AUTH.current_user())
if _off_vis is None:                       # admin — unrestricted at every scope
    _off_gids = None
elif _off_season is None:                  # career: own current ∪ open past
    _past = {r["id"] for r in query(
        "SELECT id FROM games WHERE tracked=1 AND season != 'Current'")}
    _off_gids = tuple(sorted(set(_off_vis) | _past))
elif _is_cur_off:                          # current season: per-viewer set
    _off_gids = tuple(sorted(_off_vis))
else:                                      # one past season: open archive
    _off_gids = None
data = _official_overview(gender, _off_gids, _off_season)
rows = data["officials"]
team_names = data["teams"]

# Untracked BOXED games (setup-assigned crews) feed the projection layer only —
# scoped conservatively: unrestricted for admin, else the viewer's own boxed
# games (never another org's entered box). The Officials Rating + tracked tables
# above are untouched; env is used only by the crew-outlook projection tool.
_off_untr = (None if _off_vis is None
             else tuple(sorted(ENT.visible_untracked_boxed_game_ids(
                 AUTH.current_user()))))
_off_env = _official_environment(gender, _off_gids, _off_untr, _off_season)

if not rows:
    empty_state("No officials yet for this league",
                "Assign officials in the Game Tracker and call some fouls — "
                "they'll show up here.",
                cta="Open the Game Tracker", page="pages/2_Game_Tracker.py")
    st.stop()

# Derived per-ref stats: pace-adjusted whistle rate + lean/clutch shares
for r in rows:
    r["FP100"] = (r["fouls"] / r["game_poss"] * 100.0) if r["game_poss"] else 0.0
    _tot_ha = r["home_fouls"] + r["away_fouls"]
    r["home_lean"] = (r["ha_diff"] / _tot_ha * 100.0) if _tot_ha else 0.0
    r["q4_share"] = (r["q4"] / r["fouls"] * 100.0) if r["fouls"] else 0.0

total_fouls = sum(r["fouls"] for r in rows)


def _avg(key, qmin=1):
    pool = [r[key] for r in rows if r["games"] >= qmin and r.get(key) is not None]
    return sum(pool) / len(pool) if pool else 0.0


with hc1:
    page_header(
        "Officiating Lab",
        sub=f"{gender_lbl} league · who blows the whistle, how tight, and the "
            "scoring environment of the games they work.",
        chips=[f"Officials {len(rows)}",
               f"Assigned fouls {total_fouls}",
               f"Avg FPG {_avg('FPG'):.1f}",
               f"Avg FP100 {_avg('FP100'):.1f}",
               f"Avg PPP {_avg('PPP'):.3f}"])

# ── Signature whistle leaders (glass tiles) ─────────────────────────────────────
_elig = [r for r in rows if r["games"] >= 2] or rows
_tightest = max(_elig, key=lambda r: r["FP100"])
_lenient = min(_elig, key=lambda r: r["FP100"])
_homer = max(rows, key=lambda r: abs(r["home_lean"])
             if (r["home_fouls"] + r["away_fouls"]) >= 4 else -1)
_steady = min(_elig, key=lambda r: r["FPG_std"])
_hottest = max([r for r in rows if r["game_poss"] > 0],
               key=lambda r: r["PPP"], default=rows[0])

st.markdown("<div class='lab-hdr'>League whistle leaders</div>",
            unsafe_allow_html=True)
_g = st.columns(5)
_glass(_g[0], "TIGHTEST WHISTLE", f"{_tightest['FP100']:.1f}",
       f"{_tightest['name']} · FP100", ACCENT)
_glass(_g[1], "MOST LENIENT", f"{_lenient['FP100']:.1f}",
       f"{_lenient['name']} · FP100", _uimod.GOOD)
_glass(_g[2], "BIGGEST H/A LEAN", f"{_homer['ha_diff']:+d}",
       f"{_homer['name']}", "#bc8cff")
_glass(_g[3], "MOST CONSISTENT", f"±{_steady['FPG_std']:.1f}",
       f"{_steady['name']} · FPG", "#58a6ff")
_glass(_g[4], "HOTTEST ENV.", f"{_hottest['PPP']:.2f}",
       f"{_hottest['name']} · PPP", "#e3b341")

tab_rate, tab_over, tab_charts, tab_ind, tab_gloss = st.tabs(
    ["Ratings", "Overview", "Charts", "Individual", "Glossary"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 0 — OFFICIALS RATING  (the ref a coach wants)
# ══════════════════════════════════════════════════════════════════════════════
with tab_rate:
    st.caption(
        "The **Officials Rating** — the ref coaches want: works the big games, "
        "lets them play, and still makes the gutsy call late. A 0-100 index "
        "(50 = average) weighting, in order: **fewer fouls/game** · **higher-"
        "leverage games worked** · **higher scoring** · **higher pace** · "
        "**clutch calls** (Q4/OT with the game within a possession or two).")
    _rat = _official_ratings(gender, _off_gids, _off_season)
    _rrows = _rat.get("officials", [])
    _rated = [r for r in _rrows if r.get("rating") is not None]
    if not _rated:
        st.info(f"Need at least {OFF.RATING_MIN_GAMES} games worked to rate an "
                "official — the board fills in as refs build a tracked-game "
                "history.")
    else:
        # headline tiles
        _top = _rated[0]
        _bigstage = max(_rrows, key=lambda r: r.get("leverage", 0))
        _letplay = min([r for r in _rrows if r["games"] >= 2],
                       key=lambda r: r["FPG"], default=_rated[0])
        _clutchref = max(_rrows, key=lambda r: r.get("clutch_pg", 0))
        gg = st.columns(4)
        _glass(gg[0], "TOP-RATED", f"{_top['rating']:.0f}",
               f"{_top['name']}", ACCENT)
        _glass(gg[1], "BIG-STAGE REF", f"{_bigstage['leverage']:.2f}",
               f"{_bigstage['name']} · leverage", "#e3b341")
        _glass(gg[2], "LETS THEM PLAY", f"{_letplay['FPG']:.1f}",
               f"{_letplay['name']} · FPG", _uimod.GOOD)
        _glass(gg[3], "MAKES THE CALL", f"{_clutchref['clutch']}",
               f"{_clutchref['name']} · clutch", "#bc8cff")

        import pandas as _pd
        from helpers.ui import glossary_key as _glossary_key
        _glossary_key("FPG", "Leverage", "PPP", "Clutch")
        _rdf = _pd.DataFrame([{
            "Official": r["name"], "Rating": round(r["rating"], 0),
            "GP": r["games"], "FPG": round(r["FPG"], 1),
            "Leverage": round(r["leverage"], 2),
            "PPP": round(r["PPP"], 2), "Pace": round(r["POSSPG"], 0),
            "Clutch": r["clutch"],
        } for r in _rated])
        st.dataframe(
            _rdf, hide_index=True, width="stretch", key="off_rating_df",
            column_config={"Rating": st.column_config.ProgressColumn(
                "Rating", format="%.0f", min_value=0, max_value=100)})
        st.caption(
            "Leverage = mean stakes of the games worked (team quality + "
            "closeness). Clutch = fouls called in Q4/OT within a possession or "
            "two. FPG lower is better; everything else higher is better.")

        # ── play-type foul bias ────────────────────────────────────────────
        import helpers.playtypes as _PTP
        _ptl = dict(_PTP.NAMED_PLAY_TYPES)
        _bias_rows = [r for r in _rrows if r.get("pt_bias")]
        if _bias_rows:
            st.markdown("<div class='lab-hdr'>Play-type foul bias — which sets a "
                        "ref whistles more</div>", unsafe_allow_html=True)
            st.caption("How much more (or less) of a ref's fouls come on a given "
                       "set call vs the league — a positive gap means they call "
                       "that action tight. Needs play-type-tagged fouls.")
            def _bias_cell(bias, i):
                if i >= len(bias):
                    return "—"
                k, d, n, s = bias[i]
                return f"{_ptl.get(k, k)} {d * 100:+.0f}%"
            st.dataframe(_pd.DataFrame([{
                "Official": r["name"], "GP": r["games"],
                "Calls tight #1": _bias_cell(r["pt_bias"], 0),
                "#2": _bias_cell(r["pt_bias"], 1),
                "#3": _bias_cell(r["pt_bias"], 2),
            } for r in _bias_rows[:15]]), hide_index=True, width="stretch",
                key="off_bias_df")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_over:
    st.caption("Every official who has worked a tracked game. Fouls are the calls "
               "credited to that ref; FPG is fouls per game worked. PPP is the "
               "scoring environment of their games (a property of the game, not "
               "the ref).")

    # ── pre-game crew outlook (Tier 2, ML_LAYER_ROADMAP) — pick tonight's refs
    #    → a league-relative whistle / lean / scoring expectation. ──────────────
    with st.expander("🔮 Crew outlook — what to expect from tonight's refs"):
        import helpers.ref_tendencies as RT
        _by_name = {r["name"]: r["off_pk"] for r in rows}
        _pick = st.multiselect("Officials assigned to your next game",
                               list(_by_name), key="crew_pick")
        if _pick:
            _out = RT.crew_outlook([_by_name[n] for n in _pick], overview=data,
                                   env=_off_env)
            if _out:
                st.markdown(" · ".join(f"`{t}`" for t in _out["tags"]))
                st.info(_out["summary"])
                if _out.get("env_games"):
                    st.caption(
                        f"Scoring / pace / total-foul read spans "
                        f"{_out['env_games']} game(s) worked, including "
                        "setup-entered untracked boxes; whistle & home/away lean "
                        "are tracked-only.")
        else:
            st.caption("Pick the officials assigned to your next game for a "
                       "league-relative whistle / lean / scoring-environment "
                       "outlook — value-the-ball vs attack-the-rim, before tip.")

    total_fouls = sum(r["fouls"] for r in rows)
    most = max(rows, key=lambda r: r["fouls"])
    busiest = max(rows, key=lambda r: r["FPG"])
    most_active = max(rows, key=lambda r: r["games"])

    def _avg(key, qmin=1):
        pool = [r[key] for r in rows if r["games"] >= qmin and r[key] is not None]
        return sum(pool) / len(pool) if pool else 0.0

    m = st.columns(4)
    m[0].metric("Officials", len(rows))
    m[1].metric("Assigned fouls", total_fouls)
    m[2].metric("Most fouls", most["fouls"])
    m[2].caption(most["name"])
    m[3].metric("Highest FPG", f"{busiest['FPG']:.1f}")
    m[3].caption(busiest["name"])

    m2 = st.columns(4)
    m2[0].metric("Most active", f"{most_active['games']} games")
    m2[0].caption(most_active["name"])
    m2[1].metric("Avg PPP", f"{_avg('PPP'):.3f}",
                 help="Mean points-per-possession of officiated games")
    m2[2].metric("Avg pace", f"{_avg('POSSPG'):.1f}",
                 help="Mean possessions per officiated game")
    m2[3].metric("Avg total score", f"{_avg('PTSPG'):.1f}",
                 help="Mean combined points per officiated game")

    lc, rc = st.columns(2)
    with lc:
        st.markdown("**Most fouls called** — total")
        st.plotly_chart(_leader_bar(rows, "fouls", "int", color=ACCENT, n=10),
                        width="stretch", key="ov_fouls")
    with rc:
        st.markdown("**Fouls per game** — min. 2 games")
        st.plotly_chart(_leader_bar(rows, "FPG", "f1", color="#58a6ff", n=10,
                                    qkey="games", qmin=2),
                        width="stretch", key="ov_fpg")

    lc2, rc2 = st.columns(2)
    with lc2:
        st.markdown("**Home / away foul lean** — (+ = more on home team)")
        lean = sorted([r for r in rows if r["home_fouls"] + r["away_fouls"] > 0],
                      key=lambda r: r["ha_diff"])
        seq = lean[:6] + lean[-6:] if len(lean) > 12 else lean
        fig = go.Figure(go.Bar(
            x=[r["ha_diff"] for r in seq], y=[r["name"] for r in seq],
            orientation="h", text=[f"{r['ha_diff']:+d}" for r in seq],
            textposition="auto",
            marker_color=[_uimod.GOOD if r["ha_diff"] >= 0 else AWAY for r in seq]))
        fig.update_layout(
            template="plotly_dark", height=max(220, 50 + 26 * len(seq)),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=4, r=14, t=6, b=6), showlegend=False,
            font=dict(size=11, color="#c9d1d9"))
        fig.update_xaxes(zeroline=True, zerolinecolor="#8b949e", gridcolor=GRID)
        fig.update_yaxes(showgrid=False, automargin=True)
        st.plotly_chart(fig, width="stretch", key="ov_hadiff")
    with rc2:
        st.markdown("**Whistle archetype** — FPG × scoring environment")
        st.caption("Crosshairs = league average. Upper-right = tight whistle in "
                   "high-scoring games; lower-left = let-them-play, grind-it-out.")
        _qf = _quadrant(rows, "FPG", "PPP", "Fouls / game", "PPP (scoring env.)",
                        "f1", "f3", color="#bc8cff", qmin=1)
        if _qf:
            st.plotly_chart(_qf, width="stretch", key="ov_quad")
        else:
            st.info("Not enough data for the archetype map.")

    st.markdown("<div class='lab-hdr'>Full official table</div>",
                unsafe_allow_html=True)
    full = pd.DataFrame([{
        "Official": r["name"], "ID": r["ext_id"], "GW": r["games"],
        "Fouls": r["fouls"], "FPG": round(r["FPG"], 1),
        "FP100": round(r["FP100"], 1),
        "Call share": round(r["foul_share"] * 100, 0),
        "Home F": r["home_fouls"], "Away F": r["away_fouls"],
        "H/A": r["ha_diff"], "Lean%": round(r["home_lean"], 0),
        "±FPG": round(r["FPG_std"], 1),
        "PPP": round(r["PPP"], 3), "PTS/G": round(r["PTSPG"], 1),
        "POSS/G": round(r["POSSPG"], 1),
    } for r in rows])
    _grid(full, "off_full", height=560)
    st.caption("Sort or filter any column in-grid (click a header for filters) — "
               "surface the tightest whistles (FP100), the biggest home leans "
               "(Lean%), or the most consistent refs (±FPG). Every metric is "
               "defined in the Glossary tab.")
    st.download_button("Officials (CSV)", full.to_csv(index=False),
                       file_name=f"officials_{gender_lbl}.csv", mime="text/csv",
                       key="dl_off")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — CHARTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_charts:
    st.caption("The officiating breakdown: who blows the whistle most, who they "
               "call it on, whether they lean home or away, and the scoring "
               "environment of the games they work.")

    # ── Most fouls & PPP side by side ─────────────────────────────────────────
    lc, rc = st.columns(2)
    with lc:
        st.markdown("**Who calls the most fouls** (total)")
        st.plotly_chart(_leader_bar(rows, "fouls", "int", color=ACCENT, n=14),
                        width="stretch", key="ch_fouls")
    with rc:
        st.markdown("**PPP of games worked** — points per possession")
        st.plotly_chart(_leader_bar(rows, "PPP", "f3", color=_uimod.GOOD, n=14,
                                    qkey="games", qmin=1),
                        width="stretch", key="ch_ppp")

    # ── Pace & scoring environment ────────────────────────────────────────────
    lc, rc = st.columns(2)
    with lc:
        st.markdown("**Pace of games worked** — possessions / game")
        st.plotly_chart(_leader_bar(rows, "POSSPG", "f1", color="#d29922", n=14,
                                    qkey="games", qmin=1),
                        width="stretch", key="ch_pace")
    with rc:
        st.markdown("**Avg total score** — combined points / game")
        st.plotly_chart(_leader_bar(rows, "PTSPG", "f1", color="#e67e22", n=14,
                                    qkey="games", qmin=1),
                        width="stretch", key="ch_score")

    # ── Tightness vs pace + most consistent ───────────────────────────────────
    lc, rc = st.columns(2)
    with lc:
        st.markdown("**Whistle tightness vs pace** — FPG × possessions")
        st.plotly_chart(
            _scatter(rows, "POSSPG", "FPG", "Possessions / game", "Fouls / game",
                     "f1", "f1", color="#58a6ff", qmin=1),
            width="stretch", key="ch_scatter")
    with rc:
        st.markdown("**Most consistent** — lowest game-to-game foul swing")
        st.caption("Std dev of fouls/game (min. 2 games). Low = predictable "
                   "whistle; high = varies a lot by game.")
        cons = sorted([r for r in rows if r["games"] >= 2],
                      key=lambda r: r["FPG_std"])[:12]
        seq = list(reversed(cons))
        cfig = go.Figure(go.Bar(
            x=[r["FPG_std"] for r in seq], y=[r["name"] for r in seq],
            orientation="h", marker_color="#56d4dd",
            text=[f"{r['FPG_std']:.1f}" for r in seq], textposition="auto",
            hovertemplate="%{y}: ±%{x:.1f} fouls/g<extra></extra>"))
        cfig.update_layout(
            template="plotly_dark", height=max(220, 50 + 26 * len(seq)),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=4, r=14, t=6, b=6), showlegend=False,
            font=dict(size=11, color="#c9d1d9"))
        cfig.update_xaxes(visible=False)
        cfig.update_yaxes(showgrid=False, automargin=True)
        st.plotly_chart(cfig, width="stretch", key="ch_cons")

    # ── League-wide foul timing ───────────────────────────────────────────────
    st.markdown("<div class='lab-hdr'>When fouls get called — league total by quarter</div>",
                unsafe_allow_html=True)
    qtot = [sum(r[q] for r in rows) for q in ("q1", "q2", "q3", "q4")]
    qfig = go.Figure(go.Bar(
        x=["Q1", "Q2", "Q3", "Q4"], y=qtot, marker_color=ACCENT,
        text=qtot, textposition="auto"))
    _style(qfig, height=280, margin=dict(l=44, r=20, t=20, b=36))
    st.plotly_chart(qfig, width="stretch", key="ch_qtr")

    # ── Home vs away lean ─────────────────────────────────────────────────────
    st.markdown("<div class='lab-hdr'>Home vs away — who gets the calls</div>",
                unsafe_allow_html=True)
    st.caption("Fouls each ref called against the home team (team 1) vs the away "
               "team (team 2). A strong tilt can flag a home/away whistle lean — "
               "but small samples swing hard.")
    lean = [r for r in rows if (r["home_fouls"] + r["away_fouls"]) > 0]
    lean = sorted(lean, key=lambda r: -(r["home_fouls"] + r["away_fouls"]))[:14]
    seq = list(reversed(lean))
    fig = go.Figure()
    fig.add_bar(y=[r["name"] for r in seq], x=[r["home_fouls"] for r in seq],
                orientation="h", name="vs Home", marker_color=HOME)
    fig.add_bar(y=[r["name"] for r in seq], x=[r["away_fouls"] for r in seq],
                orientation="h", name="vs Away", marker_color=AWAY)
    fig.update_layout(barmode="stack")
    _style(fig, height=max(280, 60 + 28 * len(seq)))
    st.plotly_chart(fig, width="stretch", key="ch_lean")

    # ── Fouls-against-team heatmap ────────────────────────────────────────────
    st.markdown("<div class='lab-hdr'>Fouls called against each team</div>",
                unsafe_allow_html=True)
    st.caption("Rows are officials, columns are teams; the cell is how many fouls "
               "that ref called against that team. Reads as a who-calls-what map.")

    # teams that actually drew a foul from someone, ranked by total volume
    team_tot = defaultdict(int)
    for r in rows:
        for tid, c in r["team_fouls"].items():
            team_tot[tid] += c
    top_teams = [t for t, _ in sorted(team_tot.items(), key=lambda kv: -kv[1])][:14]
    # officials with the most calls, so the grid stays legible
    grid_offs = sorted([r for r in rows if r["fouls"] > 0],
                       key=lambda r: -r["fouls"])[:16]

    if top_teams and grid_offs:
        z = [[r["team_fouls"].get(tid, 0) for tid in top_teams] for r in grid_offs]
        hm = go.Figure(go.Heatmap(
            z=z,
            x=[_team_short(team_names.get(t, "?")) for t in top_teams],
            y=[r["name"] for r in grid_offs],
            colorscale=HEAT, showscale=True,
            hovertemplate="%{y} → %{x}: %{z} fouls<extra></extra>",
            text=z, texttemplate="%{text}", textfont=dict(size=10)))
        _style(hm, height=max(320, 40 + 30 * len(grid_offs)),
               margin=dict(l=120, r=20, t=20, b=90))
        hm.update_xaxes(tickangle=-40)
        st.plotly_chart(hm, width="stretch", key="ch_heat")
    else:
        st.info("Not enough assigned fouls yet to build the team map.")

    # ── Pace-adjusted whistle rate + distribution ─────────────────────────────
    st.markdown("<div class='lab-hdr'>Pace-adjusted whistle rate (FP100)</div>",
                unsafe_allow_html=True)
    st.caption("Fouls per 100 possessions — strips out pace so a ref of fast "
               "games isn't unfairly flagged as whistle-happy. Fairer than raw FPG.")
    lc, rc = st.columns(2)
    with lc:
        st.markdown("**FP100 leaders** — min. 1 game")
        st.plotly_chart(_leader_bar(rows, "FP100", "f1", color="#56d4dd", n=14,
                                    qkey="games", qmin=1),
                        width="stretch", key="ch_fp100")
    with rc:
        st.markdown("**Distribution of FP100 across the league**")
        vals = [r["FP100"] for r in rows if r["game_poss"] > 0]
        hfig = go.Figure(go.Histogram(
            x=vals, nbinsx=12, marker_color=ACCENT, marker_line_width=0,
            opacity=0.9, hovertemplate="FP100 %{x}<br>%{y} refs<extra></extra>"))
        if vals:
            hfig.add_vline(x=float(np.mean(vals)), line_dash="dot",
                           line_color="#f0f6fc",
                           annotation_text=f"avg {np.mean(vals):.1f}",
                           annotation_position="top")
        _style(hfig, height=max(220, 60 + 26 * 14),
               margin=dict(l=44, r=20, t=30, b=40))
        hfig.update_xaxes(title_text="Fouls / 100 poss.")
        hfig.update_yaxes(title_text="Officials")
        st.plotly_chart(hfig, width="stretch", key="ch_fp100_hist")

    # ── When in the game each ref blows the whistle (quarter share) ───────────
    st.markdown("<div class='lab-hdr'>Foul-timing fingerprint — share of calls by quarter</div>",
                unsafe_allow_html=True)
    st.caption("Each row is a ref; cells are the % of THEIR calls in each quarter "
               "(rows sum to 100%). Spot refs who front-load early or tighten up late.")
    timing = sorted([r for r in rows if r["fouls"] >= 4],
                    key=lambda r: -r["fouls"])[:16]
    if timing:
        z = [[round(r[q] / r["fouls"] * 100, 0) for q in ("q1", "q2", "q3", "q4")]
             for r in timing]
        tm = go.Figure(go.Heatmap(
            z=z, x=["Q1", "Q2", "Q3", "Q4"], y=[r["name"] for r in timing],
            colorscale=HEAT, showscale=True, zmin=0,
            hovertemplate="%{y} — %{x}: %{z}% of calls<extra></extra>",
            text=[[f"{v:.0f}%" for v in row] for row in z],
            texttemplate="%{text}", textfont=dict(size=10)))
        _style(tm, height=max(300, 40 + 30 * len(timing)),
               margin=dict(l=120, r=20, t=20, b=40))
        st.plotly_chart(tm, width="stretch", key="ch_timing")
    else:
        st.info("Not enough calls yet to build the timing fingerprint.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — INDIVIDUAL
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _fx_individual():
    by_name = {r["name"]: r for r in rows}
    pick = st.selectbox("Official", list(by_name.keys()), key="ind_pick")
    r = by_name[pick]

    st.markdown(f"### {r['name']}  ·  ID {r['ext_id']}")

    # league FPG (min 1 game) for a vs-league delta
    fpg_pool = [x["FPG"] for x in rows if x["games"] >= 1]
    league_fpg = sum(fpg_pool) / len(fpg_pool) if fpg_pool else 0.0

    m = st.columns(5)
    m[0].metric("Games worked", r["games"])
    m[1].metric("Fouls called", r["fouls"])
    m[2].metric("Fouls / game", f"{r['FPG']:.1f}",
                delta=f"{r['FPG'] - league_fpg:+.1f} vs league")
    m[3].metric("Consistency ±FPG", f"{r['FPG_std']:.1f}",
                help="Game-to-game swing in fouls called; lower = steadier")
    m[4].metric("Games PPP", f"{r['PPP']:.3f}")

    m2 = st.columns(5)
    m2[0].metric("Call share", f"{r['foul_share'] * 100:.0f}%")
    m2[1].metric("Home fouls", r["home_fouls"])
    m2[2].metric("Away fouls", r["away_fouls"])
    m2[3].metric("H/A diff", f"{r['ha_diff']:+d}")
    m2[4].metric("Pace", f"{r['POSSPG']:.1f}")

    lc, rc = st.columns(2)

    # ── Foul-by-team ──────────────────────────────────────────────────────────
    with lc:
        st.markdown("**Fouls called against each team**")
        tf = sorted(r["team_fouls"].items(), key=lambda kv: -kv[1])
        if tf:
            seq = list(reversed(tf))
            fig = go.Figure(go.Bar(
                x=[c for _, c in seq],
                y=[_team_short(team_names.get(t, "?")) for t, _ in seq],
                orientation="h", marker_color=ACCENT,
                text=[c for _, c in seq], textposition="auto",
                hovertemplate="%{y}: %{x} fouls<extra></extra>"))
            fig.update_layout(
                template="plotly_dark", height=max(200, 50 + 28 * len(seq)),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=4, r=14, t=6, b=6), showlegend=False,
                font=dict(size=11, color="#c9d1d9"))
            fig.update_xaxes(visible=False)
            fig.update_yaxes(showgrid=False, automargin=True)
            st.plotly_chart(fig, width="stretch", key="ind_team")
        else:
            st.info("No team-attributable fouls recorded for this official.")

    # ── Quarter splits + home/away ────────────────────────────────────────────
    with rc:
        st.markdown("**Fouls by quarter**")
        qs = [r["q1"], r["q2"], r["q3"], r["q4"]]
        qfig = go.Figure(go.Bar(
            x=["Q1", "Q2", "Q3", "Q4"], y=qs, marker_color="#58a6ff",
            text=qs, textposition="auto"))
        _style(qfig, height=240, margin=dict(l=40, r=20, t=20, b=36))
        st.plotly_chart(qfig, width="stretch", key="ind_qtr")

        st.markdown("**Home vs away calls**")
        if r["home_fouls"] + r["away_fouls"] > 0:
            dn = go.Figure(go.Pie(
                labels=["vs Home", "vs Away"],
                values=[r["home_fouls"], r["away_fouls"]], hole=0.5,
                marker_colors=[HOME, AWAY], textinfo="label+value"))
            dn.update_layout(
                template="plotly_dark", height=240,
                paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(size=12, color="#c9d1d9"))
            st.plotly_chart(dn, width="stretch", key="ind_ha")
        else:
            st.caption("No home/away-attributable fouls.")

    log = _official_game_log(r["off_pk"], gender, _off_gids, _off_season)

    # ── Foul-rate trend over time ─────────────────────────────────────────────
    if len(log) >= 2:
        st.markdown("<div class='lab-hdr'>Foul-rate trend</div>",
                    unsafe_allow_html=True)
        chrono = sorted(log, key=lambda g: (g["date"] or ""))
        tr = go.Figure()
        tr.add_trace(go.Scatter(
            x=[g["date"] for g in chrono], y=[g["fouls"] for g in chrono],
            mode="lines+markers", name="Fouls called",
            line=dict(color="#58a6ff", width=2),
            marker=dict(size=8, color=ACCENT), fill="tozeroy",
            fillcolor="rgba(88,166,255,0.12)",
            customdata=[g["matchup"] for g in chrono],
            hovertemplate="%{x}<br>%{customdata}<br>%{y} fouls<extra></extra>"))
        tr.add_hline(y=r["FPG"], line_dash="dot", line_color=ACCENT,
                     annotation_text=f"avg {r['FPG']:.1f}",
                     annotation_position="top left")
        _style(tr, height=300, margin=dict(l=44, r=20, t=30, b=40))
        tr.update_yaxes(title_text="Fouls called")
        st.plotly_chart(tr, width="stretch", key="ind_trend")

    # ── Game log ──────────────────────────────────────────────────────────────
    st.markdown("<div class='lab-hdr'>Game log</div>", unsafe_allow_html=True)
    if log:
        log_df = pd.DataFrame([{
            "Date": g["date"], "Matchup": g["matchup"],
            "Score": (f"{g['home_score']}-{g['away_score']}"
                      if g["home_score"] is not None else "—"),
            "Ref fouls": g["fouls"], "Game fouls": g["game_fouls"],
            "POSS": round(g["poss"], 1), "PPP": round(g["ppp"], 3),
        } for g in log])
        _grid(log_df, "off_log_grid", pin_first=False,
              height=min(520, 60 + 35 * len(log_df)))
    else:
        st.info("No game log available.")


@st.fragment
def _fx_crews():
    """Crew pairs — how refs call games TOGETHER (Tier 3 item 22). League-wide
    table (n≥5 games together), verdict line first (founder taste)."""
    import helpers.ref_tendencies as RT
    from helpers.cards import conf_dot as _conf_dot
    st.markdown("<div class='lab-hdr'>Crew pairs — how they call it together</div>",
                unsafe_allow_html=True)
    cp = RT.crew_pairs(gender=gender, game_ids=_off_gids, season=_off_season,
                       min_games=5)
    _cp_rows = cp["rows"]
    if not _cp_rows:
        st.info("No pair of officials has 5+ tracked games together yet — the "
                "crew table fills in as the tracked book grows.")
        return
    # verdict first: tightest + most home-leaning crews
    _tight = max(_cp_rows, key=lambda r: r["fpg"])
    _leany = [r for r in _cp_rows if r["ha_fouls"] >= 10]
    _lean = max(_leany, key=lambda r: abs(r["lean_pct"])) if _leany else None
    _v = (f"Tightest crew: <b>{_tight['label']}</b> — "
          f"{_tight['fpg']:.1f} fouls/game across {_tight['games']} games "
          f"together (league {cp['league_fpg']:.1f}) "
          f"{_conf_dot(_tight['games'], k=8)}")
    if _lean is not None and abs(_lean["lean_pct"]) >= 10:
        _dir = "home" if _lean["lean_pct"] > 0 else "away"
        _v += (f". Most {_dir}-leaning: <b>{_lean['label']}</b> "
               f"({_lean['lean_pct']:+.0f}% of attributed fouls on the "
               f"{'home' if _dir == 'home' else 'road'} team) "
               f"{_conf_dot(_lean['games'], k=8)}")
    st.markdown(_v + ".", unsafe_allow_html=True)
    st.caption("Every pair (and full three-man crew) with 5+ games together. "
               "Fouls/game counts every whistle in their shared games — the "
               "game feel a crew produces, not individual attribution. "
               "Lean +% = more fouls on the home team.")
    _cp_df = pd.DataFrame([{
        "Crew": r["label"],
        "Type": "3-man crew" if r["kind"] == "crew" else "pair",
        "GP together": r["games"],
        "Fouls/gm": r["fpg"],
        "Lean %": r["lean_pct"],
        "PPP": r["ppp"],
        "Q4 call %": r["q4_share"],
    } for r in _cp_rows])
    _grid(_cp_df, "off_crew_grid", height=min(520, 92 + 35 * len(_cp_df)))


with tab_ind:
    _fx_individual()
    st.divider()
    _fx_crews()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_gloss:
    glossary_tab("off_gloss")
