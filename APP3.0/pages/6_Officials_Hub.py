import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from Database.db import query, initialize_database
from helpers.settings_utils import get_all_settings, apply_theme_css
from helpers.stats_players import compute_official_stats
from helpers.ui_utils import PLOT_LAYOUT, patch_dataframe

initialize_database()
_cfg = get_all_settings()
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
.ref-bio-card {
    background: linear-gradient(135deg,#0d1117 0%,#1a2332 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:22px 24px; margin-bottom:14px;
}
.ref-name  { font-size:22px; font-weight:800; color:#f0f6fc; }
.ref-id    { font-size:13px; color:#8b949e; margin-top:4px; }
.ref-stat  { font-size:28px; font-weight:800; color:#f0a500; }
.ref-lbl   { font-size:10px; color:#8b949e; text-transform:uppercase; letter-spacing:1px; }
.section-hdr {
    font-size:18px; font-weight:700; color:#f0f6fc;
    border-left:4px solid #f0a500; padding-left:10px; margin:18px 0 10px;
}
.game-row {
    background:#161b22; border:1px solid #30363d; border-radius:8px;
    padding:10px 14px; margin-bottom:6px;
}
</style>
""", unsafe_allow_html=True)


# ── Load official stats ───────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def _load_official_stats():
    return compute_official_stats()

@st.cache_data(ttl=3600, show_spinner=False)
def _load_officials_list():
    rows = query("SELECT id, name, official_id FROM officials ORDER BY name")
    return rows or []

off_df = _load_official_stats()
officials_list = _load_officials_list()

# ── Page title ────────────────────────────────────────────────────────────────
st.title("👮 Officials Hub")

if off_df.empty and not officials_list:
    st.info("No officials data found. Add officials and track games to unlock this section.")
    st.stop()

# ═════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3 = st.tabs(["📋 Overview", "🔍 Official Profile", "📊 Team Tendencies"])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 – OVERVIEW
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    if off_df.empty:
        st.info("No officiating data available yet.")
    else:
        # Ensure numeric
        for col in ["Games","Total Fouls","Fouls/Game","Home Fouls","Away Fouls","H/A Diff"]:
            if col in off_df.columns:
                off_df[col] = pd.to_numeric(off_df[col], errors="coerce").fillna(0)

        total_officials  = len(off_df)
        total_games_off  = int(off_df["Games"].sum()) if "Games" in off_df.columns else 0
        avg_fouls_game   = float(off_df["Fouls/Game"].mean()) if "Fouls/Game" in off_df.columns else 0.0
        most_active_name = ""
        if "Games" in off_df.columns and not off_df.empty:
            most_active_name = off_df.nlargest(1,"Games").iloc[0].get("Official","—")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Officials",       str(total_officials))
        m2.metric("Total Games Officiated",str(total_games_off))
        m3.metric("Avg Fouls / Game",      f"{avg_fouls_game:.1f}")
        m4.metric("Most Active",           most_active_name)

        st.markdown("---")
        st.markdown('<div class="section-hdr">Officials Leaderboard</div>', unsafe_allow_html=True)
        show_cols = [c for c in ["Official","Ref ID","Games","Total Fouls","Fouls/Game",
                                  "Home Fouls","Away Fouls","H/A Diff"] if c in off_df.columns]
        st.dataframe(off_df[show_cols].sort_values("Games", ascending=False),
                     use_container_width=True, hide_index=True)

        st.markdown("---")
        ch1, ch2 = st.columns(2)

        with ch1:
            if "Fouls/Game" in off_df.columns and "Official" in off_df.columns:
                sorted_fpg = off_df.sort_values("Fouls/Game")
                fig_fpg = go.Figure(go.Bar(
                    x=sorted_fpg["Fouls/Game"],
                    y=sorted_fpg["Official"],
                    orientation="h",
                    marker_color="#58a6ff",
                    text=[f"{v:.1f}" for v in sorted_fpg["Fouls/Game"]],
                    textposition="outside",
                ))
                fig_fpg.update_layout(**PLOT_LAYOUT, title="Fouls per Game (ascending)",
                                      height=max(300, len(off_df)*40),
                                      yaxis=dict(tickfont=dict(size=11)))
                st.plotly_chart(fig_fpg, use_container_width=True)

        with ch2:
            if "H/A Diff" in off_df.columns and "Official" in off_df.columns:
                ha = off_df.sort_values("H/A Diff").copy()
                colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in ha["H/A Diff"]]
                fig_ha = go.Figure(go.Bar(
                    x=ha["H/A Diff"],
                    y=ha["Official"],
                    orientation="h",
                    marker_color=colors,
                    text=[f"{v:+.1f}" for v in ha["H/A Diff"]],
                    textposition="outside",
                ))
                fig_ha.update_layout(
                    **PLOT_LAYOUT,
                    title="Home/Away Foul Differential (+ = more home fouls)",
                    height=max(300, len(off_df)*40),
                    yaxis=dict(tickfont=dict(size=11)),
                )
                st.plotly_chart(fig_ha, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 – OFFICIAL PROFILE
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    if not officials_list:
        st.info("No officials found in the database.")
    else:
        official_names = [o["name"] for o in officials_list]
        sel_off_name   = st.selectbox("Select Official", official_names, key="off_prof")
        sel_off        = next((o for o in officials_list if o["name"] == sel_off_name), None)

        if sel_off is None:
            st.warning("Official not found.")
        else:
            official_db_id = sel_off["id"]
            off_ref_id     = sel_off.get("official_id","—") or "—"

            # Pull stats from off_df if available
            stats_row = None
            if not off_df.empty and "Official" in off_df.columns:
                match = off_df[off_df["Official"] == sel_off_name]
                if not match.empty:
                    stats_row = match.iloc[0]

            # Bio card
            games_n   = int(stats_row["Games"])       if stats_row is not None and "Games"      in stats_row.index else 0
            fouls_n   = int(stats_row["Total Fouls"])  if stats_row is not None and "Total Fouls" in stats_row.index else 0
            fpg_n     = float(stats_row["Fouls/Game"]) if stats_row is not None and "Fouls/Game"  in stats_row.index else 0.0
            ha_diff_n = float(stats_row["H/A Diff"])   if stats_row is not None and "H/A Diff"    in stats_row.index else 0.0

            st.markdown(f"""
            <div class="ref-bio-card">
                <div class="ref-name">👮 {sel_off_name}</div>
                <div class="ref-id">Ref ID: {off_ref_id}</div>
            </div>
            """, unsafe_allow_html=True)

            bc1, bc2, bc3, bc4 = st.columns(4)
            bc1.metric("Games",          str(games_n))
            bc2.metric("Total Fouls",    str(fouls_n))
            bc3.metric("Fouls/Game",     f"{fpg_n:.1f}")
            bc4.metric("H/A Differential", f"{ha_diff_n:+.1f}")

            st.markdown("---")

            # Games worked
            st.markdown('<div class="section-hdr">Games Worked</div>', unsafe_allow_html=True)
            games_worked = query("""
                SELECT DISTINCT g.id, g.date, g.home_score, g.away_score, g.tracked,
                       t1.name AS t1, t2.name AS t2
                FROM game_lineup_officials glo
                JOIN games g ON g.id = glo.game_id
                JOIN teams t1 ON t1.id = g.team1_id
                JOIN teams t2 ON t2.id = g.team2_id
                WHERE glo.official_id = ?
                ORDER BY g.date DESC
            """, (official_db_id,))

            if not games_worked:
                st.info("No games found for this official.")
            else:
                rows_out = []
                foul_series = []  # for trend

                for g in games_worked:
                    foul_row = query("""
                        SELECT COUNT(*) AS cnt FROM game_events
                        WHERE game_id=? AND official_id=? AND event_type='foul'
                    """, (g["id"], official_db_id))
                    foul_cnt = foul_row[0]["cnt"] if foul_row else 0
                    rows_out.append({
                        "Date":    g["date"],
                        "Matchup": f"{g['t1']} vs {g['t2']}",
                        "Score":   f"{g['home_score'] or '—'} – {g['away_score'] or '—'}",
                        "Fouls Called": foul_cnt,
                        "Tracked": "✓" if g["tracked"] else "",
                    })
                    foul_series.append({"date": g["date"], "fouls": foul_cnt})

                gw_df = pd.DataFrame(rows_out)
                st.dataframe(gw_df, use_container_width=True, hide_index=True)

                # Foul rate trend
                if len(foul_series) >= 2:
                    st.markdown('<div class="section-hdr">Foul Rate Trend</div>', unsafe_allow_html=True)
                    trend_df = pd.DataFrame(foul_series).sort_values("date")
                    fig_trend = go.Figure(go.Scatter(
                        x=trend_df["date"], y=trend_df["fouls"],
                        mode="lines+markers",
                        line=dict(color="#58a6ff", width=2),
                        marker=dict(size=7, color="#f0a500"),
                        fill="tozeroy",
                        fillcolor="rgba(88,166,255,0.1)",
                    ))
                    fig_trend.update_layout(**PLOT_LAYOUT, title="Fouls Called per Game (over time)",
                                            height=320,
                                            xaxis=dict(showgrid=False),
                                            yaxis=dict(title="Fouls Called"))
                    st.plotly_chart(fig_trend, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 – TEAM TENDENCIES
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    if not officials_list:
        st.info("No officials found.")
    else:
        tend_names = [o["name"] for o in officials_list]
        sel_tend   = st.selectbox("Select Official", tend_names, key="tend_off")
        tend_off   = next((o for o in officials_list if o["name"] == sel_tend), None)

        if tend_off is None:
            st.warning("Official not found.")
        else:
            tend_db_id = tend_off["id"]

            # For each team, count fouls committed by that team called by this official
            # secondary_player_id = the player who committed the foul
            team_fouls = query("""
                SELECT t.name AS team_name,
                       COUNT(*) AS fouls_against
                FROM game_events ge
                JOIN players p ON p.id = ge.secondary_player_id
                JOIN teams t ON t.id = p.team_id
                WHERE ge.event_type = 'foul'
                  AND ge.official_id = ?
                  AND ge.secondary_player_id IS NOT NULL
                GROUP BY t.id, t.name
                ORDER BY fouls_against DESC
            """, (tend_db_id,))

            if not team_fouls:
                st.info(f"No foul data found for {sel_tend}.")
            else:
                tf_df = pd.DataFrame(team_fouls)
                tf_df["fouls_against"] = pd.to_numeric(tf_df["fouls_against"], errors="coerce").fillna(0)

                st.markdown(f'<div class="section-hdr">Fouls Called Against Each Team by {sel_tend}</div>',
                            unsafe_allow_html=True)

                fig_tf = go.Figure(go.Bar(
                    x=tf_df["fouls_against"],
                    y=tf_df["team_name"],
                    orientation="h",
                    marker_color="#e74c3c",
                    text=[str(int(v)) for v in tf_df["fouls_against"]],
                    textposition="outside",
                ))
                fig_tf.update_layout(
                    **PLOT_LAYOUT,
                    title=f"Fouls Called Against Team (games officiated by {sel_tend})",
                    height=max(300, len(tf_df)*40),
                    yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                )
                st.plotly_chart(fig_tf, use_container_width=True)

                st.dataframe(tf_df.rename(columns={"team_name":"Team","fouls_against":"Fouls Against"}),
                             use_container_width=True, hide_index=True)

            # Also show which teams this official has worked games for
            st.markdown("---")
            st.markdown('<div class="section-hdr">Teams Officiated (Game Count)</div>', unsafe_allow_html=True)

            team_game_counts = query("""
                SELECT t.name AS team_name, COUNT(DISTINCT g.id) AS game_count
                FROM game_lineup_officials glo
                JOIN games g ON g.id = glo.game_id
                JOIN teams t ON t.id = g.team1_id OR t.id = g.team2_id
                WHERE glo.official_id = ?
                GROUP BY t.id, t.name
                ORDER BY game_count DESC
            """, (tend_db_id,))

            if team_game_counts:
                tgc_df = pd.DataFrame(team_game_counts)
                tgc_df["game_count"] = pd.to_numeric(tgc_df["game_count"], errors="coerce").fillna(0)
                fig_tgc = go.Figure(go.Bar(
                    x=tgc_df["game_count"],
                    y=tgc_df["team_name"],
                    orientation="h",
                    marker_color="#58a6ff",
                    text=[str(int(v)) for v in tgc_df["game_count"]],
                    textposition="outside",
                ))
                fig_tgc.update_layout(**PLOT_LAYOUT,
                                       title="Games Involving Each Team",
                                       height=max(300, len(tgc_df)*40),
                                       yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_tgc, use_container_width=True)
            else:
                st.info("No team game data available for this official.")
