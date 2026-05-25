import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
from Database.db import query, initialize_database
from helpers.settings_utils import get_all_settings, apply_page_config, apply_theme_css
from helpers.stats_players import (compute_player_rankings, compute_player_ratings,
                                   compute_game_box_score, compute_game_quarter_scores)
from helpers.box_score_render import show_game_box_score, _show_linescore
from helpers.charts import show_score_flow_chart
from helpers.ui_utils import PLOT_LAYOUT, patch_dataframe

initialize_database()
_cfg = get_all_settings()
apply_page_config(_cfg)
apply_theme_css(_cfg)
patch_dataframe()

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.dash-card {
    background: linear-gradient(135deg,#0d1117 0%,#161b22 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:20px 22px; margin-bottom:14px;
}
.dash-card-title {
    font-size:10px; color:#8b949e; text-transform:uppercase;
    letter-spacing:1.2px; margin-bottom:6px;
}
.dash-card-value { font-size:34px; font-weight:800; color:#f0a500; line-height:1.1; }
.dash-card-sub { font-size:13px; color:#c9d1d9; margin-top:6px; }
.section-hdr {
    font-size:18px; font-weight:700; color:#f0f6fc;
    border-left:4px solid #f0a500; padding-left:10px; margin:18px 0 10px;
}
.game-hero {
    background: linear-gradient(135deg,#0f1923 0%,#1a2332 100%);
    border:1px solid #1f4d8a; border-radius:16px;
    padding:24px; margin-bottom:14px; text-align:center;
}
.game-hero-teams { font-size:22px; font-weight:800; color:#f0f6fc; }
.game-hero-score { font-size:40px; font-weight:900; color:#f0a500; margin:8px 0; }
.game-hero-badge {
    display:inline-block; background:#0d419d; color:#fff;
    font-size:10px; font-weight:700; letter-spacing:1px;
    border-radius:20px; padding:3px 10px; text-transform:uppercase;
}
.game-hero-meta { font-size:12px; color:#8b949e; margin-top:8px; }
.score-card {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:14px 16px; margin-bottom:8px;
}
.score-team-row { display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; }
.score-team-name { font-size:14px; font-weight:600; }
.score-winner-text { color:#f0a500; }
.score-loser-text  { color:#555d68; }
.score-pts-win  { font-size:22px; font-weight:900; color:#f0a500; }
.score-pts-lose { font-size:22px; font-weight:700; color:#555d68; }
.score-meta { font-size:10px; color:#8b949e; margin-top:4px; }
.tracked-badge {
    display:inline-block; background:#0d419d; color:#fff;
    font-size:9px; font-weight:700; letter-spacing:1px;
    border-radius:10px; padding:2px 8px; text-transform:uppercase;
    margin-left:6px;
}
.upset-card {
    background:linear-gradient(135deg,#1a0a0a,#2a0d0d);
    border:1px solid #e74c3c; border-radius:12px;
    padding:18px; margin-bottom:10px;
}
.upset-title { font-size:14px; font-weight:800; color:#e74c3c; margin-bottom:6px; }
.upset-body  { font-size:13px; color:#c9d1d9; }
</style>
""", unsafe_allow_html=True)

# ── Page title ────────────────────────────────────────────────────────────────
st.title("📅 Daily Breakdown")

# ── Load all dates ────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _get_dates():
    rows = query("SELECT DISTINCT date FROM games WHERE date IS NOT NULL ORDER BY date DESC")
    return [r["date"] for r in rows] if rows else []

all_dates = _get_dates()

if not all_dates:
    st.info("No game dates found. Add games with dates to unlock the Daily Breakdown.")
    st.stop()

# ── Date selector ─────────────────────────────────────────────────────────────
# Format for display
def _fmt_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%A, %B %-d, %Y")
    except Exception:
        try:
            return datetime.strptime(d, "%Y-%m-%d").strftime("%A, %B %d, %Y")
        except Exception:
            return str(d)

date_display = {d: _fmt_date(d) for d in all_dates}
sel_date = st.selectbox(
    "Select Date",
    options=all_dates,
    format_func=lambda d: date_display.get(d, d),
    key="daily_date_sel",
)

st.markdown(f"### {date_display.get(sel_date, sel_date)}")

# ── Load games for selected date ──────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _get_games_on_date(date_str):
    rows = query("""
        SELECT g.id, g.date, g.home_score, g.away_score, g.tracked,
               g.team1_id, g.team2_id,
               t1.name AS t1, t2.name AS t2
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE g.date = ?
        ORDER BY g.id
    """, (date_str,))
    return rows or []

day_games = _get_games_on_date(sel_date)

if not day_games:
    st.info(f"No games found on {date_display.get(sel_date, sel_date)}.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# SECTION: Day at a Glance
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-hdr">📊 Day at a Glance</div>', unsafe_allow_html=True)

total_games   = len(day_games)
tracked_count = sum(1 for g in day_games if g["tracked"])

# Compute scores
scores_available = [(g["home_score"], g["away_score"]) for g in day_games
                    if g["home_score"] is not None and g["away_score"] is not None]

if scores_available:
    all_pts    = [s[0] + s[1] for s in scores_available]
    margins    = [abs(s[0] - s[1]) for s in scores_available]
    avg_score  = float(np.mean([s for pair in scores_available for s in pair]))
    largest_mov = int(max(margins)) if margins else 0
else:
    avg_score  = 0.0
    largest_mov = 0

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Games",   str(total_games))
m2.metric("Avg Score",     f"{avg_score:.1f}" if avg_score else "—")
m3.metric("Largest MOV",   f"{largest_mov}" if largest_mov else "—")
m4.metric("Tracked Games", str(tracked_count))

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION: Game of the Day
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-hdr">🏆 Game of the Day</div>', unsafe_allow_html=True)

scored_games = [g for g in day_games
                if g["home_score"] is not None and g["away_score"] is not None]

if scored_games:
    gotd = max(scored_games, key=lambda g: (g["home_score"] + g["away_score"]))
    hs, as_ = gotd["home_score"], gotd["away_score"]
    tracked_badge = '<span class="game-hero-badge">📊 TRACKED</span>' if gotd["tracked"] else ""

    st.markdown(f"""
    <div class="game-hero">
        <div class="game-hero-teams">{gotd['t1']} vs {gotd['t2']}</div>
        <div class="game-hero-score">{hs} – {as_}</div>
        {tracked_badge}
    </div>
    """, unsafe_allow_html=True)

    if gotd["tracked"]:
        try:
            gotd_id   = gotd["id"]
            t1id      = gotd["team1_id"]
            t2id      = gotd["team2_id"]
            show_score_flow_chart(gotd_id, gotd["t1"], gotd["t2"], t1id, t2id,
                                  key=f"flow_daily_{gotd_id}")
        except Exception:
            pass
        try:
            linescore_rows = compute_game_quarter_scores(gotd["id"])
            if linescore_rows:
                _show_linescore(linescore_rows, gotd["t1"], gotd["t2"],
                                gotd["team1_id"], gotd["team2_id"])
        except Exception:
            pass
else:
    st.info("No scored games to determine Game of the Day.")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION: Upset Alert
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-hdr">⚠️ Upset Alert</div>', unsafe_allow_html=True)

try:
    from helpers.stats_rankings import compute_all_rankings
    rank_df = compute_all_rankings()

    if rank_df is not None and not rank_df.empty and "Team" in rank_df.columns:
        rank_map = {}
        rank_df_reset = rank_df.reset_index(drop=True)
        for i, row in rank_df_reset.iterrows():
            team_name = row.get("Team") or row.get("name","")
            rank_map[team_name] = i + 1   # 1-indexed rank

        best_upset = None
        best_diff  = 0

        for g in scored_games:
            hs, as_ = g["home_score"], g["away_score"]
            if hs is None or as_ is None:
                continue
            t1_rank = rank_map.get(g["t1"])
            t2_rank = rank_map.get(g["t2"])
            if t1_rank is None or t2_rank is None:
                continue

            winner = g["t1"] if hs > as_ else (g["t2"] if as_ > hs else None)
            loser  = g["t2"] if hs > as_ else (g["t1"] if as_ > hs else None)
            if winner is None:
                continue

            winner_rank = rank_map.get(winner)
            loser_rank  = rank_map.get(loser)
            if winner_rank is None or loser_rank is None:
                continue

            # Upset: winner was ranked lower (higher number = worse)
            if winner_rank > loser_rank:
                diff = winner_rank - loser_rank
                if diff > best_diff:
                    best_diff  = diff
                    best_upset = {"winner": winner, "loser": loser,
                                  "winner_rank": winner_rank, "loser_rank": loser_rank,
                                  "score": f"{hs}–{as_}" if hs > as_ else f"{as_}–{hs}",
                                  "diff": diff}

        if best_upset:
            st.markdown(f"""
            <div class="upset-card">
                <div class="upset-title">🚨 Biggest Upset of the Day</div>
                <div class="upset-body">
                    <b>#{best_upset['winner_rank']} {best_upset['winner']}</b>
                    defeated <b>#{best_upset['loser_rank']} {best_upset['loser']}</b>
                    &nbsp;({best_upset['score']})
                    &nbsp;— Rank difference: <b>{best_upset['diff']}</b>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("No upsets detected — higher-ranked teams won all their games today (or no ranking data for matchups).")
    else:
        st.info("No ranking data available to detect upsets.")
except Exception as e:
    st.info("Upset detection unavailable (rankings not computed).")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION: Top Performers
# ─────────────────────────────────────────────────────────────────────────────
if tracked_count > 0:
    st.markdown('<div class="section-hdr">🎯 Top Performers</div>', unsafe_allow_html=True)

    # Top scorer
    try:
        top_pts_rows = query("""
            SELECT p.name AS player, t.name AS team,
                   SUM(CASE
                       WHEN ge.event_type='shot' AND ge.shot_result='make' THEN ge.shot_type
                       WHEN ge.event_type='free_throw' AND ge.shot_result='make' THEN 1
                       ELSE 0 END) AS pts
            FROM game_events ge
            JOIN players p ON p.id = ge.primary_player_id
            JOIN teams t ON t.id = p.team_id
            JOIN games g ON g.id = ge.game_id
            WHERE g.date = ? AND g.tracked = 1
            GROUP BY ge.game_id, ge.primary_player_id
            ORDER BY pts DESC
            LIMIT 1
        """, (sel_date,))
        top_pts = top_pts_rows[0] if top_pts_rows else None
    except Exception:
        top_pts = None

    # Top rebounder
    try:
        top_reb_rows = query("""
            SELECT p.name AS player, t.name AS team, COUNT(*) AS reb
            FROM game_events ge
            JOIN players p ON p.id = ge.rebound_by_id
            JOIN teams t ON t.id = p.team_id
            JOIN games g ON g.id = ge.game_id
            WHERE g.date = ? AND g.tracked = 1
              AND ge.event_type = 'rebound'
            GROUP BY ge.game_id, ge.rebound_by_id
            ORDER BY reb DESC
            LIMIT 1
        """, (sel_date,))
        top_reb = top_reb_rows[0] if top_reb_rows else None
    except Exception:
        top_reb = None

    # Top distributor (assists via pass_from_id on assisted makes)
    try:
        top_ast_rows = query("""
            SELECT p.name AS player, t.name AS team, COUNT(*) AS ast
            FROM game_events ge
            JOIN players p ON p.id = ge.pass_from_id
            JOIN teams t ON t.id = p.team_id
            JOIN games g ON g.id = ge.game_id
            WHERE g.date = ? AND g.tracked = 1
              AND ge.event_type = 'shot'
              AND ge.shot_result = 'make'
              AND ge.pass_from_id IS NOT NULL
            GROUP BY ge.game_id, ge.pass_from_id
            ORDER BY ast DESC
            LIMIT 1
        """, (sel_date,))
        top_ast = top_ast_rows[0] if top_ast_rows else None
    except Exception:
        top_ast = None

    tp1, tp2, tp3 = st.columns(3)

    if top_pts:
        tp1.metric(
            f"🏀 Top Scorer",
            f"{int(top_pts['pts'])} PTS",
            f"{top_pts['player']} ({top_pts['team']})"
        )
    else:
        tp1.metric("🏀 Top Scorer", "—")

    if top_reb:
        tp2.metric(
            f"💪 Top Rebounder",
            f"{int(top_reb['reb'])} REB",
            f"{top_reb['player']} ({top_reb['team']})"
        )
    else:
        tp2.metric("💪 Top Rebounder", "—")

    if top_ast:
        tp3.metric(
            f"🎯 Top Distributor",
            f"{int(top_ast['ast'])} AST",
            f"{top_ast['player']} ({top_ast['team']})"
        )
    else:
        tp3.metric("🎯 Top Distributor", "—")

    st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION: All Results
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-hdr">📋 All Results</div>', unsafe_allow_html=True)

for g in day_games:
    hs  = g["home_score"]
    as_ = g["away_score"]
    t1  = g["t1"]
    t2  = g["t2"]

    has_score  = hs is not None and as_ is not None
    t1_wins    = has_score and hs > as_
    t2_wins    = has_score and as_ > hs
    is_tracked = bool(g["tracked"])

    if has_score:
        t1_cls = "score-winner-text" if t1_wins else "score-loser-text"
        t2_cls = "score-winner-text" if t2_wins else "score-loser-text"
        t1_pts_cls = "score-pts-win" if t1_wins else "score-pts-lose"
        t2_pts_cls = "score-pts-win" if t2_wins else "score-pts-lose"
        hs_str  = str(int(hs))
        as_str  = str(int(as_))
    else:
        t1_cls = t2_cls = "score-loser-text"
        t1_pts_cls = t2_pts_cls = "score-pts-lose"
        hs_str = as_str = "—"

    tracked_html = '<span class="tracked-badge">📊 TRACKED</span>' if is_tracked else ""
    margin_str   = f"MOV: {abs(int(hs)-int(as_))}" if has_score and hs != as_ else ("TIE" if has_score else "No Score")

    st.markdown(f"""
    <div class="score-card">
        <div class="score-team-row">
            <span class="score-team-name {t1_cls}">{t1}</span>
            <span class="{t1_pts_cls}">{hs_str}</span>
        </div>
        <div class="score-team-row">
            <span class="score-team-name {t2_cls}">{t2}</span>
            <span class="{t2_pts_cls}">{as_str}</span>
        </div>
        <div class="score-meta">{margin_str} {tracked_html}</div>
    </div>
    """, unsafe_allow_html=True)

    # Box score expander for tracked games
    if is_tracked:
        with st.expander(f"📊 Box Score: {t1} vs {t2}"):
            try:
                rows_t1, rows_t2, game_info = compute_game_box_score(g["id"])
                quarter_data = compute_game_quarter_scores(g["id"])

                if quarter_data:
                    _show_linescore(quarter_data, t1, t2,
                                    g["team1_id"], g["team2_id"])

                has_data = any(not r.get("_totals") for r in rows_t1 + rows_t2)
                if has_data:
                    show_game_box_score(rows_t1, rows_t2, {}, game_info, _cfg)
                else:
                    st.info("Box score data not available for this game.")
            except Exception as exc:
                st.warning(f"Could not load box score: {exc}")
