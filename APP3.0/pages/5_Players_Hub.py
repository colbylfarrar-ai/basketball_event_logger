import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from Database.db import query, initialize_database
from helpers.constants import CLASS_ORDER
from helpers.settings_utils import get_all_settings, apply_page_config, apply_theme_css
from helpers.stats_players import (compute_player_rankings, compute_player_ratings,
                                   compute_official_stats,
                                   compute_player_rebound_onoff,
                                   compute_player_assist_onoff)
from helpers.stats_team import compute_player_game_log
from helpers.ui_utils import (PLOT_LAYOUT, patch_dataframe,
                               bar_h as _bar_h,
                               normalize_col as _normalize_col,
                               percentile_of as _percentile_of,
                               pctile_bar_html as _pctile_bar_html)

initialize_database()
_cfg = get_all_settings()
apply_page_config(_cfg)
apply_theme_css(_cfg)
patch_dataframe()

# ══════════════════════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* ── Base cards ── */
.dash-card {
    background:linear-gradient(135deg,#0d1117 0%,#161b22 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:20px 22px; margin-bottom:14px;
}
/* ── Hero banner ── */
.pl-hero {
    background:linear-gradient(135deg,#0d1117 0%,#1a2332 100%);
    border:1px solid #30363d; border-radius:14px;
    padding:22px 24px; margin-bottom:14px;
}
.pl-name  { font-size:22px; font-weight:900; color:#f0f6fc; }
.pl-meta  { font-size:13px; color:#8b949e; margin-top:5px; }
/* ── Medal cards ── */
.medal-gold   { background:linear-gradient(135deg,#3a2a00,#1a1200); border:1px solid #f0a500; border-radius:12px; padding:18px; text-align:center; }
.medal-silver { background:linear-gradient(135deg,#1e2229,#13161b); border:1px solid #adb5bd; border-radius:12px; padding:18px; text-align:center; }
.medal-bronze { background:linear-gradient(135deg,#271505,#1a0e04); border:1px solid #cd7f32; border-radius:12px; padding:18px; text-align:center; }
.medal-icon  { font-size:28px; }
.medal-name  { font-size:16px; font-weight:800; color:#f0f6fc; margin-top:6px; }
.medal-value { font-size:28px; font-weight:800; color:#f0a500; }
.medal-sub   { font-size:11px; color:#8b949e; }
/* ── Best Five cards ── */
.best5-card {
    background:linear-gradient(135deg,#0f1923,#1a2332);
    border:1px solid #1f4d8a; border-radius:14px;
    padding:18px 14px; text-align:center; margin-bottom:8px;
}
.best5-role    { font-size:10px; color:#58a6ff; text-transform:uppercase; letter-spacing:1px; margin-bottom:6px; }
.best5-name    { font-size:15px; font-weight:800; color:#f0f6fc; }
.best5-team    { font-size:11px; color:#8b949e; margin-top:3px; }
.best5-stat    { font-size:24px; font-weight:800; color:#f0a500; margin-top:8px; }
.best5-stat-lbl{ font-size:10px; color:#8b949e; }
/* ── Section header ── */
.section-hdr {
    font-size:18px; font-weight:700; color:#f0f6fc;
    border-left:4px solid #f0a500; padding-left:10px; margin:18px 0 10px;
}
/* ── Rating description ── */
.rating-desc {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:14px 16px; margin-bottom:10px;
}
.rating-desc-title { font-size:13px; font-weight:700; color:#58a6ff; margin-bottom:4px; }
.rating-desc-body  { font-size:12px; color:#8b949e; line-height:1.5; }
/* ── OVRL hero ── */
.ovrl-hero {
    background:linear-gradient(135deg,#1a0d2e 0%,#0d1117 100%);
    border:2px solid #f0a500; border-radius:16px;
    padding:22px 28px; margin-bottom:18px;
    display:flex; align-items:center; gap:24px;
}
.ovrl-crown { font-size:42px; line-height:1; }
.ovrl-info  { flex:1; }
.ovrl-label { font-size:10px; color:#f0a500; text-transform:uppercase; letter-spacing:1.5px; font-weight:700; }
.ovrl-name  { font-size:24px; font-weight:900; color:#f0f6fc; margin:4px 0 2px; }
.ovrl-sub   { font-size:13px; color:#8b949e; }
.ovrl-score { text-align:right; }
.ovrl-num   { font-size:52px; font-weight:900; color:#f0a500; line-height:1; }
.ovrl-tag   { font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:1px; }
/* ── Percentile bar ── */
.pctile-row {
    margin-bottom:10px;
}
.pctile-label-row {
    display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;
}
.pctile-stat   { font-size:12px; font-weight:600; color:#c9d1d9; }
.pctile-val    { font-size:13px; font-weight:700; color:#f0f6fc; }
.pctile-rank   { font-size:10px; font-weight:600; }
.pctile-track  { background:#21262d; border-radius:4px; height:7px; overflow:hidden; }
.pctile-fill   { height:100%; border-radius:4px; }
/* ── Stat summary grid ── */
.stat-grid {
    display:grid; grid-template-columns:repeat(auto-fit,minmax(90px,1fr)); gap:10px;
    margin-bottom:16px;
}
.stat-cell {
    background:#161b22; border:1px solid #30363d; border-radius:10px;
    padding:10px 8px; text-align:center;
}
.stat-cell-val { font-size:20px; font-weight:800; color:#f0a500; }
.stat-cell-lbl { font-size:9px; color:#8b949e; text-transform:uppercase; letter-spacing:1px; margin-top:3px; }
/* ── Advanced stat badge ── */
.adv-badge {
    display:inline-block; background:#1f3a5c; border:1px solid #1f6feb;
    border-radius:6px; padding:4px 10px; font-size:11px; color:#58a6ff;
    font-weight:700; margin:2px;
}
/* ── Trend pill ── */
.trend-up   { color:#2ecc71; font-weight:700; }
.trend-down { color:#e74c3c; font-weight:700; }
.trend-flat { color:#8b949e; font-weight:600; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
# PLOT_LAYOUT, _bar_h, _normalize_col, _percentile_of, _pctile_bar_html
# are all imported from helpers.ui_utils above.

def _stat_grid_html(stats: dict) -> str:
    cells = "".join(
        f'<div class="stat-cell">'
        f'<div class="stat-cell-val">{v}</div>'
        f'<div class="stat-cell-lbl">{k}</div>'
        f'</div>'
        for k, v in stats.items()
    )
    return f'<div class="stat-grid">{cells}</div>'

# ══════════════════════════════════════════════════════════════════════════════
#  DATA LOAD
# ══════════════════════════════════════════════════════════════════════════════
def _load_rankings(): return compute_player_rankings()
def _load_ratings():  return compute_player_ratings()

rnk = _load_rankings()
rat = _load_ratings()

st.title("👤 Players Hub")

if rnk.empty:
    st.info("No tracked game data found. Track some games to unlock player analytics.")
    st.stop()

# Numeric coerce
NUM_COLS = ["PTS","REB","AST","STL","BLK","TOV","FGM","FGA","FG%",
            "2PM","2PA","2P%","3PM","3PA","3P%","FTM","FTA","FT%",
            "eFG%","TS%","+/-","GS","SC","SCS","SCP","SCO","SCS%","SCP%","SCO%",
            "ShotRat","Stocks","Q4 PPG",
            "3PAr","PaintFG%","PaintFGA","PaintFGM","DSh%",
            "FTr","PPS","PPSA","TOV%","USG","EFF","FIC","PRF","AST/TOV",
            "PTS32","REB32","AST32","STL32","BLK32","TOV32","SC32",
            "SCS32","SCP32","SCO32","GP","MIN"]
for c in NUM_COLS:
    if c in rnk.columns:
        rnk[c] = pd.to_numeric(rnk[c], errors="coerce").fillna(0)

if not rat.empty:
    for c in ["OFF","DEF","PLY","REB_R","OVRL","GP"]:
        if c in rat.columns:
            rat[c] = pd.to_numeric(rat[c], errors="coerce").fillna(0)

def _label(row):
    num = f"#{row['#']} " if "#" in row and row["#"] else ""
    cls = f" · {row['Class']}" if "Class" in row and row.get("Class") else ""
    pts = f" · {float(row.get('PTS', 0)):.1f}pts" if "PTS" in row else ""
    return f"{num}{row['Player']} ({row['Team']}{cls}{pts})"

rnk["_label"] = rnk.apply(_label, axis=1)
if "STL" in rnk.columns and "BLK" in rnk.columns:
    rnk["Stocks"] = (pd.to_numeric(rnk["STL"], errors="coerce").fillna(0)
                     + pd.to_numeric(rnk["BLK"], errors="coerce").fillna(0))

# ══════════════════════════════════════════════════════════════════════════════
#  TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏆 Leaderboards", "🏅 Ratings", "⭐ Best Five", "📊 Compare", "🔍 Player Profiles"
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 – LEADERBOARDS
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    # ── OVRL Hero Card ──────────────────────────────────────────────────────
    if not rat.empty and "OVRL" in rat.columns:
        _ovrl_leader = rat.nlargest(1, "OVRL").iloc[0]
        st.markdown(f"""
        <div class="ovrl-hero">
            <div class="ovrl-crown">👑</div>
            <div class="ovrl-info">
                <div class="ovrl-label">Overall Rating Leader</div>
                <div class="ovrl-name">{_ovrl_leader['Player']}</div>
                <div class="ovrl-sub">{_ovrl_leader.get('Team','—')} &nbsp;·&nbsp;
                    {_ovrl_leader.get('GP',0):.0f} GP &nbsp;·&nbsp;
                    {_ovrl_leader.get('PTS',0):.1f} PTS &nbsp;
                    {_ovrl_leader.get('REB',0):.1f} REB &nbsp;
                    {_ovrl_leader.get('AST',0):.1f} AST
                </div>
            </div>
            <div class="ovrl-score">
                <div class="ovrl-num">{_ovrl_leader['OVRL']:.1f}</div>
                <div class="ovrl-tag">OVRL</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Headline metrics ─────────────────────────────────────────────────────
    def _leader(col, src=None):
        src = src if src is not None else rnk
        return src.nlargest(1, col).iloc[0] if col in src.columns and not src.empty else None

    l_pts = _leader("PTS"); l_reb = _leader("REB")
    l_ast = _leader("AST"); l_stk = _leader("Stocks")
    l_eff = _leader("EFF"); l_pps = _leader("PPSA")

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    def _mc(col_obj, label, row, stat_col, fmt=".1f"):
        if row is not None:
            col_obj.metric(label, f"{row[stat_col]:{fmt}}", row["Player"])
        else:
            col_obj.metric(label, "—")

    _mc(c1, "Points Leader",   l_pts, "PTS")
    _mc(c2, "Rebound Leader",  l_reb, "REB")
    _mc(c3, "Assist Leader",   l_ast, "AST")
    _mc(c4, "Stocks Leader",   l_stk, "Stocks")
    _mc(c5, "Efficiency (EFF)",l_eff, "EFF")
    _mc(c6, "PPSA Leader",     l_pps, "PPSA", fmt=".2f")

    st.markdown("---")

    # ── Charts row ────────────────────────────────────────────────────────────
    ch1, ch2 = st.columns(2)

    with ch1:
        if "PTS" in rnk.columns:
            _tp = rnk.nlargest(10, "PTS")[["_label", "PTS"]].copy()
            _tp["_label"] = _tp["_label"].astype(str)
            _cp = ["#f0a500" if i == 0 else "#58a6ff" if i < 3 else "#30363d"
                   for i in range(len(_tp))]
            fig_lb_pts = go.Figure(go.Bar(
                x=_tp["PTS"], y=_tp["_label"], orientation="h",
                marker_color=list(reversed(_cp)),
                text=[f"{v:.1f}" for v in _tp["PTS"]],
                textposition="outside",
            ))
            fig_lb_pts.update_layout(
                **PLOT_LAYOUT, title="Top 10 — Points per Game",
                yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                xaxis=dict(showgrid=False),
                height=max(300, 10 * 38))
            st.plotly_chart(fig_lb_pts, use_container_width=True, key="lb_pts_chart")

    with ch2:
        if "EFF" in rnk.columns:
            _te = rnk.nlargest(10, "EFF")[["_label", "EFF"]].copy()
            _te["_label"] = _te["_label"].astype(str)
            _ce = ["#f0a500" if i == 0 else "#9b59b6" if i < 3 else "#30363d"
                   for i in range(len(_te))]
            fig_lb_eff = go.Figure(go.Bar(
                x=_te["EFF"], y=_te["_label"], orientation="h",
                marker_color=list(reversed(_ce)),
                text=[f"{v:.1f}" for v in _te["EFF"]],
                textposition="outside",
            ))
            fig_lb_eff.update_layout(
                **PLOT_LAYOUT, title="Top 10 — Efficiency (EFF)",
                yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                xaxis=dict(showgrid=False),
                height=max(300, 10 * 38))
            st.plotly_chart(fig_lb_eff, use_container_width=True, key="lb_eff_chart")

    st.markdown("---")

    # ── Full stats dashboard table ────────────────────────────────────────────
    st.markdown('<div class="section-hdr">📋 Full Stats Dashboard</div>',
                unsafe_allow_html=True)
    _sort_opts = [c for c in ["PTS","REB","AST","STL","BLK","EFF","eFG%","TS%","+/-","TOV"]
                  if c in rnk.columns]
    _lb_sort = st.selectbox("Sort by", _sort_opts, key="lb_sort_col")
    _lb_asc  = (_lb_sort == "TOV")
    _dash_cols = ["Player","#","Team","Class","GP","PTS","REB","AST","STL","BLK",
                  "TOV","FG%","eFG%","TS%","+/-","EFF"]
    _dash_show = [c for c in _dash_cols if c in rnk.columns]
    _lb_src = rnk.sort_values(_lb_sort, ascending=_lb_asc) if _lb_sort in rnk.columns else rnk
    st.dataframe(_lb_src[_dash_show], use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 – RATINGS
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    if rat.empty:
        st.info("No rating data available yet.")
    else:
        st.markdown("""
        <div class="rating-desc">
            <div class="rating-desc-title">👑 OVRL – Overall Rating</div>
            <div class="rating-desc-body">Position-neutral composite. Weights: OFF 30% · PLY 25% · DEF 25% · REB_R 20%. Scale 0–100, league-relative.</div>
        </div>
        <div class="rating-desc">
            <div class="rating-desc-title">⚡ OFF – Offensive Rating</div>
            <div class="rating-desc-body">Shooting sub-score (TS% 30 · eFG% 25 · 3P% 20 · FT% 15 · ShotRat 10) + Finishing sub-score (PTS 35 · PaintFG% 30 · SC 20 · FG% 15), averaged.</div>
        </div>
        <div class="rating-desc">
            <div class="rating-desc-title">🛡️ DEF – Defensive Rating</div>
            <div class="rating-desc-body">DSh% 30 · Stocks 25 · DREB 25 · STL 10 · BLK 10. Rewards contested shots, disruption, and defensive rebounding.</div>
        </div>
        <div class="rating-desc">
            <div class="rating-desc-title">🎯 PLY – Playmaking Rating</div>
            <div class="rating-desc-body">AST 30 · AST/TOV 25 · TOV(inv) 20 · SC 15 · PTS 10. Ball-handling and creation value.</div>
        </div>
        <div class="rating-desc">
            <div class="rating-desc-title">📦 REB_R – Rebounding Rating</div>
            <div class="rating-desc-body">OREB 35 · DREB 35 · REB 20 · PaintFGA 10. Glass-cleaning ability.</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        _gp_max = int(rat["GP"].max()) if "GP" in rat.columns and not rat.empty else 1
        _gp_min = st.slider("Minimum Games Played", 1, max(_gp_max, 1), 1, key="rat_min_gp")
        rat_f   = rat[rat["GP"] >= _gp_min].copy() if "GP" in rat.columns else rat.copy()

        if rat_f.empty:
            st.info(f"No players with {_gp_min}+ games played.")
        else:
            # Pre-compute within-class rank for every player (by OVRL)
            if "Class" in rat_f.columns and "OVRL" in rat_f.columns:
                rat_f = rat_f.copy()
                rat_f["Class Rank"] = (
                    rat_f.groupby("Class")["OVRL"]
                         .rank(method="min", ascending=False)
                         .astype(int)
                )

            sub_ovrl_r, sub_off, sub_def, sub_ply, sub_reb, sub_cls = st.tabs([
                "👑 Overall (OVRL)", "⚡ Offense (OFF)", "🛡️ Defense (DEF)",
                "🎯 Playmaking (PLY)", "📦 Rebounding (REB_R)", "📚 Class Rankings"
            ])

            MEDAL_STYLES = ["medal-gold","medal-silver","medal-bronze"]
            MEDAL_ICONS  = ["🥇","🥈","🥉"]

            def _rating_tab(parent, col, label, color):
                with parent:
                    if col not in rat_f.columns:
                        st.info(f"No {label} data.")
                        return
                    sorted_r = rat_f.nlargest(len(rat_f), col).reset_index(drop=True)
                    top3 = sorted_r.head(3)
                    cols_m = st.columns(min(3, len(top3)))
                    for i, (_, row) in enumerate(top3.iterrows()):
                        with cols_m[i]:
                            st.markdown(f"""
                            <div class="{MEDAL_STYLES[i]}">
                                <div class="medal-icon">{MEDAL_ICONS[i]}</div>
                                <div class="medal-name">{row['Player']}</div>
                                <div class="medal-sub">{row.get('Team','')} · {row.get('Class','')}</div>
                                <div class="medal-value">{row[col]:.1f}</div>
                                <div class="medal-sub">{label}</div>
                            </div>
                            """, unsafe_allow_html=True)

                    st.markdown("<br>", unsafe_allow_html=True)
                    dcols = ["Player","#","Team","Class","Class Rank","GP","OVRL","PTS","AST","REB","STL","BLK","eFG%","TS%",col]
                    show_c = [c for c in dcols if c in sorted_r.columns]
                    st.dataframe(sorted_r[show_c], use_container_width=True, hide_index=True)

                    # OFF vs DEF scatter, bubble = REB_R
                    if all(c in rat_f.columns for c in ["OFF","DEF","REB_R"]):
                        st.markdown('<div class="section-hdr">OFF vs DEF (bubble = REB_R)</div>',
                                    unsafe_allow_html=True)
                        fig_sc = px.scatter(
                            rat_f, x="OFF", y="DEF", size="REB_R",
                            color="Team", hover_name="Player", size_max=30,
                            color_discrete_sequence=px.colors.qualitative.Plotly,
                            labels={"OFF":"Offensive Rating","DEF":"Defensive Rating","REB_R":"Rebounding Rating"},
                        )
                        fig_sc.update_layout(**PLOT_LAYOUT, height=420)
                        st.plotly_chart(fig_sc, use_container_width=True, key=f"scatter_rating_{col}")

            # OVRL sub-tab
            with sub_ovrl_r:
                if "OVRL" not in rat_f.columns:
                    st.info("No OVRL data.")
                else:
                    _ov_r = rat_f.nlargest(len(rat_f), "OVRL").reset_index(drop=True)
                    top3_ov = _ov_r.head(3)
                    ov_cols = st.columns(min(3, len(top3_ov)))
                    for i, (_, row) in enumerate(top3_ov.iterrows()):
                        with ov_cols[i]:
                            st.markdown(f"""
                            <div class="{MEDAL_STYLES[i]}">
                                <div class="medal-icon">{MEDAL_ICONS[i]}</div>
                                <div class="medal-name">{row['Player']}</div>
                                <div class="medal-sub">{row.get('Team','')} · {row.get('Class','')}</div>
                                <div class="medal-value">{row['OVRL']:.1f}</div>
                                <div class="medal-sub">Overall Rating</div>
                            </div>
                            """, unsafe_allow_html=True)

                    st.markdown("<br>", unsafe_allow_html=True)
                    _ov_r_cols = ["Player","#","Team","Class","Class Rank","GP","OVRL",
                                  "OFF","DEF","PLY","REB_R","PTS","AST","REB","STL","BLK","TOV","TS%"]
                    _ov_r_show = [c for c in _ov_r_cols if c in _ov_r.columns]
                    st.dataframe(_ov_r[_ov_r_show], use_container_width=True, hide_index=True)

                    if all(c in rat_f.columns for c in ["OVRL","OFF","REB_R"]):
                        st.markdown("---")
                        fig_ov_sc = px.scatter(
                            rat_f, x="OFF", y="OVRL", size="REB_R",
                            color="DEF" if "DEF" in rat_f.columns else "Team",
                            hover_name="Player", size_max=30,
                            color_continuous_scale=[[0,"#1a3a5c"],[0.5,"#f0a500"],[1,"#2ecc71"]],
                            labels={"OFF":"Offensive Rating","OVRL":"Overall Rating",
                                    "REB_R":"Rebounding Rating","DEF":"Defensive Rating"},
                            title="OVRL vs OFF — size=REB_R, color=DEF",
                        )
                        fig_ov_sc.update_layout(**PLOT_LAYOUT, height=440)
                        st.plotly_chart(fig_ov_sc, use_container_width=True, key="scatter_ovrl_off")

                    st.caption("OVRL = OFF 30% + PLY 25% + DEF 25% + REB_R 20%, normalised 0–100.")

            _rating_tab(sub_off, "OFF",   "Offensive Rating",   "#f0a500")
            _rating_tab(sub_def, "DEF",   "Defensive Rating",   "#3498db")
            _rating_tab(sub_ply, "PLY",   "Playmaking Rating",  "#2ecc71")
            _rating_tab(sub_reb, "REB_R", "Rebounding Rating",  "#e67e22")

            # ── Class Rankings tab ────────────────────────────────────────────
            with sub_cls:
                if "Class" not in rat_f.columns or "OVRL" not in rat_f.columns:
                    st.info("Class or OVRL data not available.")
                else:
                    _cls_order = [c for c in CLASS_ORDER if c in rat_f["Class"].values]

                    # Rating to display picker
                    _cls_metric = st.selectbox(
                        "Rank by",
                        ["OVRL","OFF","DEF","PLY","REB_R"],
                        key="cls_rank_metric",
                    )

                    st.markdown("---")

                    for _cls in _cls_order:
                        _cls_df = (
                            rat_f[rat_f["Class"] == _cls]
                            .copy()
                            .sort_values(_cls_metric, ascending=False)
                            .reset_index(drop=True)
                        )
                        if _cls_df.empty:
                            continue

                        # Class header
                        _cls_leader = _cls_df.iloc[0]
                        st.markdown(
                            f"<div style='background:linear-gradient(135deg,#0d1117,#161b22);"
                            f"border:1px solid #30363d;border-radius:12px;"
                            f"padding:14px 18px;margin-bottom:12px'>"
                            f"<span style='font-size:18px;font-weight:800;color:#f0a500'>"
                            f"🏫 {_cls} Classification</span>"
                            f"<span style='font-size:13px;color:#8b949e;margin-left:12px'>"
                            f"{len(_cls_df)} players · ranked by {_cls_metric}</span>"
                            f"<span style='font-size:13px;color:#c9d1d9;margin-left:12px'>"
                            f"Class leader: <b>{_cls_leader['Player']}</b> "
                            f"({_cls_leader[_cls_metric]:.1f} {_cls_metric})</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                        # Top-3 podium for this class
                        _cls_top3 = _cls_df.head(3)
                        _pod_cols = st.columns(min(3, len(_cls_top3)))
                        for _pi, (_, _pr) in enumerate(_cls_top3.iterrows()):
                            with _pod_cols[_pi]:
                                st.markdown(
                                    f"<div class='{MEDAL_STYLES[_pi]}'>"
                                    f"<div class='medal-icon'>{MEDAL_ICONS[_pi]}</div>"
                                    f"<div class='medal-name'>{_pr['Player']}</div>"
                                    f"<div class='medal-sub'>{_pr.get('Team','')}</div>"
                                    f"<div class='medal-value'>{_pr[_cls_metric]:.1f}</div>"
                                    f"<div class='medal-sub'>{_cls_metric}</div>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )

                        st.markdown("<br>", unsafe_allow_html=True)

                        # Bar chart — top 10 in class
                        _cls_top10 = _cls_df.head(10).iloc[::-1]   # ascending for h-bar
                        _bar_clrs = [
                            "#f0a500" if i == len(_cls_top10) - 1
                            else "#58a6ff" if i >= len(_cls_top10) - 3
                            else "#30363d"
                            for i in range(len(_cls_top10))
                        ]
                        _cls_lbl = _cls_top10.apply(
                            lambda r: f"#{int(_cls_df.index[_cls_df['Player']==r['Player']].min())+1} {r['Player']} ({r.get('Team','')[:12]})",
                            axis=1,
                        )
                        _fig_cls = go.Figure(go.Bar(
                            x=_cls_top10[_cls_metric],
                            y=_cls_lbl,
                            orientation="h",
                            marker_color=_bar_clrs,
                            text=[f"{v:.1f}" for v in _cls_top10[_cls_metric]],
                            textposition="outside",
                        ))
                        _fig_cls.update_layout(
                            **{k: v for k, v in PLOT_LAYOUT.items() if k != "margin"},
                            height=max(280, len(_cls_top10) * 38),
                            xaxis=dict(range=[0, 108], showgrid=False),
                            yaxis=dict(tickfont=dict(size=11)),
                            margin=dict(l=0, r=60, t=10, b=10),
                        )
                        st.plotly_chart(_fig_cls, use_container_width=True,
                                        key=f"cls_bar_{_cls}_{_cls_metric}")

                        # Full class table with class-internal rank
                        _cls_df = _cls_df.copy()
                        if "Class Rank" in _cls_df.columns:
                            _cls_df.drop(columns=["Class Rank"], inplace=True)
                        _cls_df.insert(0, "Class Rank", range(1, len(_cls_df) + 1))
                        _cls_show_cols = [c for c in
                            ["Class Rank","Player","#","Team","GP",_cls_metric,
                             "OFF","DEF","PLY","REB_R","OVRL","PTS","AST","REB"]
                            if c in _cls_df.columns]
                        # Deduplicate if _cls_metric already in list
                        seen = set(); _cls_show_cols = [
                            c for c in _cls_show_cols
                            if not (c in seen or seen.add(c))
                        ]
                        with st.expander(f"Full {_cls} table ({len(_cls_df)} players)", expanded=False):
                            st.dataframe(_cls_df[_cls_show_cols],
                                         use_container_width=True, hide_index=True)

                        st.markdown("---")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 – BEST FIVE  (top 5 per individual category)
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    if rnk.empty and rat.empty:
        st.info("No player data available.")
    else:
        # ── Filters ──────────────────────────────────────────────────────────
        _b5_c1, _b5_c2, _b5_c3 = st.columns(3)
        _b5_avail_cls = CLASS_ORDER
        _b5_sel_cls = _b5_c1.multiselect(
            "Class Filter", _b5_avail_cls, default=_b5_avail_cls, key="b5_cls_sel"
        )
        _b5_gender = _b5_c2.radio("Gender", ["All", "M", "F"], horizontal=True, key="b5_gender")
        _b5_min_gp = _b5_c3.number_input("Min GP", min_value=0, value=1, step=1, key="b5_min_gp")

        # Apply filters to rnk and rat
        _b5_rnk = rnk.copy()
        _b5_rat = rat.copy()
        if _b5_sel_cls and "Class" in _b5_rnk.columns:
            _b5_rnk = _b5_rnk[_b5_rnk["Class"].isin(_b5_sel_cls)]
        if _b5_gender != "All" and "Gender" in _b5_rnk.columns:
            _b5_rnk = _b5_rnk[_b5_rnk["Gender"] == _b5_gender]
        if "GP" in _b5_rnk.columns:
            _b5_rnk = _b5_rnk[_b5_rnk["GP"] >= _b5_min_gp]
        if _b5_sel_cls and "Class" in _b5_rat.columns:
            _b5_rat = _b5_rat[_b5_rat["Class"].isin(_b5_sel_cls)]

        # Merge OVRL onto rnk pool for display
        _b5_merged = _b5_rnk.copy()
        if not _b5_rat.empty and "pid" in _b5_rat.columns and "pid" in _b5_merged.columns:
            _b5_ovrl = _b5_rat[["pid", "OVRL"]].rename(columns={"OVRL": "_ovrl_merge"})
            _b5_merged = _b5_merged.merge(_b5_ovrl, on="pid", how="left")

        medals_b5 = ["🥇", "🥈", "🥉", "  4", "  5"]
        _b5_rank_colors = ["#f0a500", "#adb5bd", "#cd7f32", "#555d68", "#555d68"]

        def _show_top5_category(df, stat_col, label, color, fmt=".1f", hib=True):
            """Render a top-5 card list for one stat category."""
            if df.empty or stat_col not in df.columns:
                st.info(f"No {label} data available.")
                return
            sorted_df = df.sort_values(stat_col, ascending=not hib).head(5).reset_index(drop=True)
            for i, (_, row) in enumerate(sorted_df.iterrows()):
                val    = row.get(stat_col, 0)
                name   = row.get("Player", "—")
                team   = row.get("Team", "—")
                cls    = row.get("Class", "")
                num    = f"#{row.get('#', '')}" if row.get("#") else ""
                ovrl   = row.get("_ovrl_merge", None)
                ovrl_s = f"  OVRL {ovrl:.0f}" if ovrl and not pd.isna(ovrl) else ""
                pts    = row.get("PTS", None)
                reb    = row.get("REB", None)
                ast    = row.get("AST", None)
                stat_line = "  ·  ".join(
                    f"{s:.1f} {l}" for s, l in
                    [(pts, "PTS"), (reb, "REB"), (ast, "AST")]
                    if s is not None and l != label
                )
                rc = _b5_rank_colors[i]
                st.markdown(
                    f"<div class='lu-row-card'>"
                    f"<div class='lu-rank' style='color:{rc}'>{medals_b5[i]}</div>"
                    f"<div class='lu-body'>"
                    f"  <div class='lu-name'>{num} {name}</div>"
                    f"  <div class='lu-meta'>{team} · {cls}{ovrl_s}</div>"
                    f"  <div class='lu-meta' style='font-size:10px'>{stat_line}</div>"
                    f"</div>"
                    f"<div class='lu-score' style='color:{color}'>{val:{fmt}}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # ── Category grid ─────────────────────────────────────────────────────
        # Row 1: OVRL · PTS · AST
        st.markdown('<div class="section-hdr">League Leaders — Top 5 Per Category</div>',
                    unsafe_allow_html=True)

        # Use merged df for OVRL display, rnk for stat categories
        _b5_ovrl_df = _b5_merged.copy()

        _cat_cfg = [
            ("_ovrl_merge", "Overall (OVRL)", "#f0a500", _b5_ovrl_df),
            ("PTS",         "Points",         "#e74c3c", _b5_merged),
            ("AST",         "Assists",        "#2ecc71", _b5_merged),
            ("REB",         "Rebounds",       "#3498db", _b5_merged),
            ("STL",         "Steals",         "#58a6ff", _b5_merged),
            ("BLK",         "Blocks",         "#e67e22", _b5_merged),
        ]

        # 3-column layout, 2 rows
        for row_idx in range(0, len(_cat_cfg), 3):
            _row_cats = _cat_cfg[row_idx:row_idx + 3]
            _row_cols = st.columns(len(_row_cats))
            for col_obj, (stat, label, color, src_df) in zip(_row_cols, _row_cats):
                with col_obj:
                    st.markdown(
                        f"<div style='font-size:13px;font-weight:700;color:{color};"
                        f"margin-bottom:8px;border-bottom:2px solid {color};"
                        f"padding-bottom:4px'>⭐ {label}</div>",
                        unsafe_allow_html=True,
                    )
                    _show_top5_category(src_df, stat, label, color)
            st.write("")

        # ── Secondary categories ───────────────────────────────────────────────
        with st.expander("📈 More Categories", expanded=False):
            _more_cfg = [
                ("EFF",    "Efficiency (EFF)",  "#9b59b6", _b5_merged),
                ("eFG%",   "eFG%",              "#1abc9c", _b5_merged),
                ("TS%",    "True Shooting %",   "#1abc9c", _b5_merged),
                ("SC",     "Shot Creation",     "#f39c12", _b5_merged),
                ("+/-",    "Plus/Minus",        "#27ae60", _b5_merged),
                ("PPSA",   "Pts Per Shot Att.", "#8e44ad", _b5_merged),
            ]
            for row_idx2 in range(0, len(_more_cfg), 3):
                _row2_cats = _more_cfg[row_idx2:row_idx2 + 3]
                _row2_cols = st.columns(len(_row2_cats))
                for col_obj2, (stat2, label2, color2, src2) in zip(_row2_cols, _row2_cats):
                    with col_obj2:
                        st.markdown(
                            f"<div style='font-size:13px;font-weight:700;color:{color2};"
                            f"margin-bottom:8px;border-bottom:2px solid {color2};"
                            f"padding-bottom:4px'>📊 {label2}</div>",
                            unsafe_allow_html=True,
                        )
                        _show_top5_category(src2, stat2, label2, color2)
                st.write("")

        # ── Class-filtered view ────────────────────────────────────────────────
        if _b5_avail_cls:
            st.markdown("---")
            st.markdown('<div class="section-hdr">🏫 Class View</div>', unsafe_allow_html=True)
            _cls_sel_b5 = st.selectbox("Select Class", _b5_avail_cls, key="b5_cls_single")
            _cls_rnk_b5 = _b5_merged[_b5_merged["Class"] == _cls_sel_b5].copy() \
                          if "Class" in _b5_merged.columns else _b5_merged.copy()
            _cls_cats = [
                ("_ovrl_merge", "Overall (OVRL)", "#f0a500"),
                ("PTS",         "Points",         "#e74c3c"),
                ("AST",         "Assists",        "#2ecc71"),
                ("REB",         "Rebounds",       "#3498db"),
                ("STL",         "Steals",         "#58a6ff"),
                ("BLK",         "Blocks",         "#e67e22"),
            ]
            for _ri3 in range(0, len(_cls_cats), 3):
                _r3 = _cls_cats[_ri3:_ri3 + 3]
                _r3c = st.columns(len(_r3))
                for _co3, (_st3, _lb3, _cl3) in zip(_r3c, _r3):
                    with _co3:
                        st.markdown(
                            f"<div style='font-size:13px;font-weight:700;color:{_cl3};"
                            f"margin-bottom:8px;border-bottom:2px solid {_cl3};"
                            f"padding-bottom:4px'>⭐ {_lb3}</div>",
                            unsafe_allow_html=True,
                        )
                        _show_top5_category(_cls_rnk_b5, _st3, _lb3, _cl3)
                st.write("")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 – COMPARE
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    eligible = rnk[rnk["GP"] >= 1].copy() if "GP" in rnk.columns else rnk.copy()
    if len(eligible) < 2:
        st.info("Need at least 2 players with game appearances to compare.")
    else:
        player_options = eligible["_label"].tolist()
        col_a, col_b = st.columns(2)
        sel_a = col_a.selectbox("Player A", player_options, index=0, key="cmp_a")
        sel_b = col_b.selectbox("Player B", player_options,
                                index=min(1, len(player_options)-1), key="cmp_b")
        row_a = eligible[eligible["_label"] == sel_a].iloc[0]
        row_b = eligible[eligible["_label"] == sel_b].iloc[0]

        # ── Radar ───────────────────────────────────────────────────────────
        RADAR_STATS = ["PTS","AST","REB","STL","BLK","eFG%","TS%","SC","Q4 PPG"]
        avail = [s for s in RADAR_STATS if s in rnk.columns]
        norm_df = eligible[avail].copy()
        for c in avail:
            norm_df[c] = _normalize_col(eligible[c])

        def _get_norm(row_label):
            idx = eligible[eligible["_label"] == row_label].index[0]
            return norm_df.loc[idx, avail].tolist()

        vals_a = _get_norm(sel_a)
        vals_b = _get_norm(sel_b)

        fig_radar = go.Figure()
        for vals, name, color in [(vals_a, sel_a, "#58a6ff"), (vals_b, sel_b, "#f0a500")]:
            fig_radar.add_trace(go.Scatterpolar(
                r=vals + [vals[0]], theta=avail + [avail[0]],
                fill="toself", name=name[:30], line_color=color,
                fillcolor=color.replace("ff","22"),  opacity=0.7,
            ))
        fig_radar.update_layout(
            **PLOT_LAYOUT,
            polar=dict(bgcolor="rgba(0,0,0,0)",
                       radialaxis=dict(visible=True, range=[0,100],
                                       tickfont=dict(size=9), gridcolor="#30363d"),
                       angularaxis=dict(tickfont=dict(size=11), gridcolor="#30363d")),
            legend=dict(font=dict(color="#c9d1d9")),
            title="Player Radar (normalized 0–100 within league)", height=460,
        )
        st.plotly_chart(fig_radar, use_container_width=True)

        # ── Shooting distribution donut ──────────────────────────────────────
        if all(c in eligible.columns for c in ["2PA","3PA","FTA"]):
            st.markdown('<div class="section-hdr">Shot Profile Comparison</div>',
                        unsafe_allow_html=True)
            dc1, dc2 = st.columns(2)
            for col_obj, sel, row in [(dc1, sel_a, row_a), (dc2, sel_b, row_b)]:
                with col_obj:
                    _2pa = float(row.get("2PA",0))
                    _3pa = float(row.get("3PA",0))
                    _fta = float(row.get("FTA",0))
                    total = _2pa + _3pa + _fta
                    if total > 0:
                        fig_d = go.Figure(go.Pie(
                            labels=["2PT FGA","3PT FGA","FTA"],
                            values=[_2pa, _3pa, _fta],
                            hole=0.55,
                            marker_colors=["#f0a500","#3498db","#2ecc71"],
                            textinfo="label+percent",
                            textfont_size=11,
                        ))
                        fig_d.update_layout(
                            **PLOT_LAYOUT,
                            title=f"{row['Player']} — Shot Profile",
                            showlegend=False, height=300)
                        st.plotly_chart(fig_d, use_container_width=True,
                                        key=f"donut_{sel[:8]}")

        # ── Percentile bars side-by-side ─────────────────────────────────────
        st.markdown('<div class="section-hdr">Percentile Comparison</div>',
                    unsafe_allow_html=True)
        PCTILE_STATS = [
            ("PTS","Points",True), ("REB","Rebounds",True),
            ("AST","Assists",True), ("STL","Steals",True),
            ("BLK","Blocks",True),  ("TOV","Turnovers",False),
            ("eFG%","eFG%",True),   ("TS%","TS%",True),
            ("FTr","FT Rate",True), ("PPSA","Pts/Scoring Att",True),
            ("EFF","Efficiency",True),("FIC","Floor Impact",True),
        ]
        pc_cols = st.columns(2)
        for i, (sel, row) in enumerate([(sel_a, row_a), (sel_b, row_b)]):
            with pc_cols[i]:
                st.markdown(f"**{row['Player']}**")
                bars_html = ""
                for col, lbl, hb in PCTILE_STATS:
                    if col not in eligible.columns: continue
                    val = row.get(col, 0)
                    pct = _percentile_of(float(val), eligible[col])
                    bars_html += _pctile_bar_html(lbl, round(float(val),1), pct, hb)
                st.markdown(bars_html, unsafe_allow_html=True)

        # ── Stat comparison table ────────────────────────────────────────────
        st.markdown('<div class="section-hdr">Stat Comparison</div>', unsafe_allow_html=True)
        CMP_STATS = ["GP","PTS","REB","AST","STL","BLK","TOV","FG%","3P%","FT%",
                     "eFG%","TS%","+/-","GS","SC","EFF","FIC","PRF","PPSA","FTr","AST/TOV"]
        cmp_avail = [s for s in CMP_STATS if s in eligible.columns]
        rows_cmp  = []
        for stat in cmp_avail:
            v_a = row_a.get(stat, 0); v_b = row_b.get(stat, 0)
            try:
                fa, fb = float(v_a), float(v_b)
                wa = fa > fb; wb = fb > fa
            except Exception:
                wa = wb = False
            rows_cmp.append({"Stat":stat, "Player A":v_a, "Player B":v_b,
                              "_wa":wa, "_wb":wb})
        cmp_df = pd.DataFrame(rows_cmp)

        def _color_row(row):
            styles = [""] * len(row)
            ci = row.index.tolist()
            if row.get("_wa"):
                if "Player A" in ci: styles[ci.index("Player A")] = "color:#2ecc71;font-weight:700"
                if "Player B" in ci: styles[ci.index("Player B")] = "color:#e74c3c"
            elif row.get("_wb"):
                if "Player B" in ci: styles[ci.index("Player B")] = "color:#2ecc71;font-weight:700"
                if "Player A" in ci: styles[ci.index("Player A")] = "color:#e74c3c"
            return styles

        out_df = cmp_df[["Stat","Player A","Player B"]].copy()
        out_df.columns = ["Stat", row_a["Player"], row_b["Player"]]
        st.dataframe(out_df, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 – PLAYER PROFILES
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    if rnk.empty:
        st.info("No player data available.")
    else:
        # ── Two-step team → player selector ──────────────────────────────────
        _prof_teams = (sorted(rnk["Team"].dropna().unique().tolist())
                       if "Team" in rnk.columns else [])
        _psel_c1, _psel_c2 = st.columns([1, 2])
        with _psel_c1:
            _sel_team_prof = st.selectbox("Team", _prof_teams, key="prof_team_sel")
        with _psel_c2:
            _team_rnk_pool = (rnk[rnk["Team"] == _sel_team_prof]
                              if "Team" in rnk.columns and _prof_teams else rnk)
            _team_player_opts = _team_rnk_pool["_label"].tolist()
            sel_prof = st.selectbox("Player", _team_player_opts, key="prof_sel")

        prof_row = rnk[rnk["_label"] == sel_prof].iloc[0]
        pid      = prof_row.get("pid", None)

        # ── Pre-compute values used in hero card ──────────────────────────────
        _gp_val  = int(prof_row.get("GP", 0))
        _min_val = float(prof_row.get("MIN", 0))
        _pm_val  = float(prof_row.get("+/-", 0))

        # Pull ratings for hero card
        _prof_rat_vals = {}
        if not rat.empty and pid is not None and "pid" in rat.columns:
            _pr_match = rat[rat["pid"] == pid]
            if not _pr_match.empty:
                for _rc in ("OVRL", "OFF", "DEF", "PLY", "REB_R"):
                    _prof_rat_vals[_rc] = float(_pr_match.iloc[0].get(_rc, 0) or 0)
        _prof_ovrl = _prof_rat_vals.get("OVRL", 0.0)

        _tier_color = ("#f0a500" if _prof_ovrl >= 80 else
                       "#2ecc71" if _prof_ovrl >= 65 else
                       "#58a6ff" if _prof_ovrl >= 50 else
                       "#c9d1d9" if _prof_ovrl >= 35 else "#8b949e")
        _tier_label = ("ELITE"      if _prof_ovrl >= 80 else
                       "GREAT"      if _prof_ovrl >= 65 else
                       "ABOVE AVG"  if _prof_ovrl >= 50 else
                       "AVERAGE"    if _prof_ovrl >= 35 else "DEVELOPING")

        _p_num  = str(prof_row.get("#", "") or "")
        _p_name = prof_row["Player"]
        _p_team = prof_row.get("Team", "")
        _p_cls  = prof_row.get("Class", "")
        _p_gnd  = prof_row.get("Gender", "")

        # Stat strip HTML
        _stat_items_hero = [
            ("PTS", float(prof_row.get("PTS", 0)), "#f0a500"),
            ("REB", float(prof_row.get("REB", 0)), "#3498db"),
            ("AST", float(prof_row.get("AST", 0)), "#2ecc71"),
            ("STL", float(prof_row.get("STL", 0)), "#58a6ff"),
            ("BLK", float(prof_row.get("BLK", 0)), "#e67e22"),
            ("TOV", float(prof_row.get("TOV", 0)), "#e74c3c"),
            ("+/-", _pm_val,                        "#c9d1d9"),
            ("EFF", float(prof_row.get("EFF", 0)), "#9b59b6"),
        ]
        _hero_stat_html = ""
        for _slbl, _sval, _sclr in _stat_items_hero:
            _sfmt = f"{_sval:+.1f}" if _slbl == "+/-" else f"{_sval:.1f}"
            _hero_stat_html += (
                f"<div style='text-align:center;padding:0 10px;"
                f"border-right:1px solid #21262d'>"
                f"<div style='font-size:24px;font-weight:900;color:{_sclr};"
                f"line-height:1.1'>{_sfmt}</div>"
                f"<div style='font-size:9px;color:#8b949e;text-transform:uppercase;"
                f"letter-spacing:1.2px;margin-top:3px'>{_slbl}</div>"
                f"</div>"
            )

        # Rating badges HTML
        _rat_badge_colors = {"OVRL": "#f0a500", "OFF": "#e74c3c", "DEF": "#3498db",
                             "PLY": "#2ecc71",  "REB_R": "#e67e22"}
        _hero_badges_html = ""
        for _rk, _rv in _prof_rat_vals.items():
            if _rv > 0:
                _rbclr = _rat_badge_colors.get(_rk, "#8b949e")
                _rvint = int(_rv)
                _hero_badges_html += (
                    f"<div style='background:#0d1117;border:1px solid {_rbclr}55;"
                    f"border-radius:8px;padding:8px 16px;text-align:center'>"
                    f"<div style='font-size:22px;font-weight:900;color:{_rbclr}'>{_rvint}</div>"
                    f"<div style='font-size:8px;color:#8b949e;text-transform:uppercase;"
                    f"letter-spacing:1.2px;margin-top:2px'>{_rk}</div>"
                    f"</div>"
                )

        _ovrl_badge = ""
        if _prof_ovrl > 0:
            _ovrl_badge = (
                f"<div style='text-align:center;flex-shrink:0'>"
                f"<div style='font-size:9px;color:{_tier_color};text-transform:uppercase;"
                f"letter-spacing:2px;font-weight:700;margin-bottom:2px'>OVERALL</div>"
                f"<div style='font-size:68px;font-weight:900;color:{_tier_color};"
                f"line-height:1'>{int(_prof_ovrl)}</div>"
                f"<div style='font-size:10px;font-weight:700;color:{_tier_color};"
                f"letter-spacing:1.5px;margin-top:2px'>{_tier_label}</div>"
                f"</div>"
            )

        _hero_num_disp = _p_num if _p_num else "—"

        _hero_card = f"""
<div style="background:linear-gradient(135deg,#080c14 0%,#0d1117 55%,#111827 100%);
            border:1px solid {_tier_color}66;border-radius:18px;
            padding:28px 32px;margin-bottom:20px;position:relative;overflow:hidden">
  <!-- Accent bar -->
  <div style="position:absolute;top:0;left:0;right:0;height:3px;
              background:linear-gradient(90deg,{_tier_color},{_tier_color}00)"></div>
  <!-- Watermark number -->
  <div style="position:absolute;right:-8px;top:50%;transform:translateY(-50%);
              font-size:180px;font-weight:900;color:rgba(255,255,255,0.02);
              line-height:1;pointer-events:none;user-select:none">#{_hero_num_disp}</div>
  <!-- Main row -->
  <div style="display:flex;align-items:flex-start;gap:24px;position:relative">
    <!-- Jersey number box -->
    <div style="background:linear-gradient(135deg,{_tier_color}18,{_tier_color}08);
                border:2px solid {_tier_color}55;border-radius:14px;
                padding:14px 18px;text-align:center;min-width:82px;flex-shrink:0">
      <div style="font-size:9px;color:#8b949e;text-transform:uppercase;
                  letter-spacing:1.2px;margin-bottom:4px">No.</div>
      <div style="font-size:52px;font-weight:900;color:{_tier_color};
                  line-height:1">{_hero_num_disp}</div>
    </div>
    <!-- Name / info / stats -->
    <div style="flex:1;min-width:0">
      <div style="font-size:40px;font-weight:900;color:#f0f6fc;line-height:1.05;
                  letter-spacing:-0.5px;overflow:hidden;text-overflow:ellipsis;
                  white-space:nowrap">{_p_name}</div>
      <div style="font-size:13px;color:#8b949e;margin-top:5px;display:flex;
                  align-items:center;gap:6px;flex-wrap:wrap">
        <span style="color:{_tier_color};font-weight:700;font-size:10px;
                     text-transform:uppercase;letter-spacing:1.2px">{_tier_label}</span>
        <span style="color:#30363d">·</span><span>{_p_team}</span>
        <span style="color:#30363d">·</span><span>{_p_cls}</span>
        <span style="color:#30363d">·</span><span>{_p_gnd}</span>
        <span style="color:#30363d">·</span><span>{_gp_val} GP</span>
      </div>
      <!-- Core stat row -->
      <div style="display:flex;margin-top:14px;background:#0a0e1a;
                  border:1px solid #21262d;border-radius:10px;
                  padding:12px 6px;overflow-x:auto;gap:0">
        {_hero_stat_html}
      </div>
    </div>
    <!-- OVRL badge -->
    {_ovrl_badge}
  </div>
  <!-- Rating component badges -->
  {f'<div style="display:flex;gap:8px;margin-top:14px;padding-top:12px;border-top:1px solid #21262d;flex-wrap:wrap">{_hero_badges_html}</div>' if _hero_badges_html else ''}
</div>
"""
        st.markdown(_hero_card, unsafe_allow_html=True)

        # Bio (height / wingspan / weight) — kept compact below the card
        if pid is not None:
            bio_rows = query("SELECT height, wingspan, weight FROM players WHERE id=?", (int(pid),))
            bio = bio_rows[0] if bio_rows else None
            if bio and any(bio.get(k) for k in ("height", "wingspan", "weight")):
                b1, b2, b3 = st.columns(3)
                b1.metric("Height",   bio.get("height",   "—") or "—")
                b2.metric("Wingspan", bio.get("wingspan", "—") or "—")
                b3.metric("Weight",   bio.get("weight",   "—") or "—")

        st.markdown("---")

        # ── Pre-fetch game log (used in Game Log tab AND Game Score graph) ────
        from helpers.stats_team import compute_player_game_log as _cpgl
        _profile_team_id = None
        if pid is not None and "Team" in prof_row.index:
            _team_res = query("SELECT id FROM teams WHERE name=?",
                              (str(prof_row.get("Team", "")),))
            if _team_res:
                _profile_team_id = _team_res[0]["id"]

        _game_log_data: list = []
        if pid is not None and _profile_team_id is not None:
            _game_log_data = _cpgl(int(pid), int(_profile_team_id))

        _gl_df = pd.DataFrame(_game_log_data) if _game_log_data else pd.DataFrame()

        # ── Profile inner tabs ────────────────────────────────────────────────
        p_tab_stats, p_tab_adv, p_tab_per36, p_tab_ratings, p_tab_rank, p_tab_log = st.tabs([
            "📊 Stats", "🔬 Advanced", "📐 Per-36", "🏅 Ratings", "👑 OVRL Ranking", "📋 Game Log"
        ])

        # ── Stats ─────────────────────────────────────────────────────────────
        with p_tab_stats:
            st.markdown('<div class="section-hdr">Career Averages</div>',
                        unsafe_allow_html=True)
            avg_cols  = ["GP","MIN","PTS","REB","AST","STL","BLK","TOV","PF","+/-","GS"]
            avg_avail = [c for c in avg_cols if c in prof_row.index]
            st.dataframe(pd.DataFrame([{c: prof_row[c] for c in avg_avail}]),
                         use_container_width=True, hide_index=True)

            # Shooting breakdown
            st.markdown('<div class="section-hdr">Shooting Breakdown</div>',
                        unsafe_allow_html=True)
            shoot_cols_p = ["FGM","FGA","FG%","2PM","2PA","2P%",
                            "3PM","3PA","3P%","FTM","FTA","FT%","eFG%","TS%",
                            "PaintFG%","PaintFGA","PaintFGM","3PAr","FTr","PPS","PPSA","ShotRat"]
            shoot_avail = [c for c in shoot_cols_p if c in prof_row.index]
            if shoot_avail:
                st.dataframe(pd.DataFrame([{c: prof_row[c] for c in shoot_avail}]),
                             use_container_width=True, hide_index=True)

            # Shot distribution donut + efficiency bars
            _col_l, _col_r = st.columns([1, 1])
            with _col_l:
                _2pa_v = float(prof_row.get("2PA",0))
                _3pa_v = float(prof_row.get("3PA",0))
                _fta_v = float(prof_row.get("FTA",0))
                if (_2pa_v + _3pa_v + _fta_v) > 0:
                    fig_donut = go.Figure(go.Pie(
                        labels=["2PT FGA","3PT FGA","FTA"],
                        values=[_2pa_v, _3pa_v, _fta_v],
                        hole=0.58,
                        marker_colors=["#f0a500","#3498db","#2ecc71"],
                        textinfo="label+percent", textfont_size=11,
                    ))
                    fig_donut.update_layout(
                        **PLOT_LAYOUT, title="Shot Attempt Distribution",
                        showlegend=False, height=280)
                    st.plotly_chart(fig_donut, use_container_width=True, key=f"prof_donut_{pid}")

            with _col_r:
                pct_cols = [c for c in ["FG%","2P%","3P%","FT%","eFG%","TS%"]
                            if c in prof_row.index]
                if pct_cols:
                    pct_vals = [float(prof_row[c]) for c in pct_cols]
                    fig_sh = go.Figure(go.Bar(
                        x=pct_cols, y=pct_vals,
                        marker_color=["#f0a500","#e67e22","#3498db","#2ecc71","#9b59b6","#e74c3c"],
                        text=[f"{v:.1f}%" for v in pct_vals],
                        textposition="outside",
                    ))
                    fig_sh.update_layout(**PLOT_LAYOUT, title="Shooting Percentages",
                                         yaxis=dict(range=[0,115]), height=280)
                    st.plotly_chart(fig_sh, use_container_width=True, key=f"prof_shoot_{pid}")

        # ── Advanced ──────────────────────────────────────────────────────────
        with p_tab_adv:
            st.markdown('<div class="section-hdr">Advanced Metrics</div>',
                        unsafe_allow_html=True)
            adv_stat_cols = ["EFF","FIC","PRF","PPSA","PPS","FTr","TOV%",
                             "USG","GS","SC","ShotRat","AST/TOV","DSh%","Q4 PPG"]
            adv_avail = [c for c in adv_stat_cols if c in prof_row.index]
            if adv_avail:
                st.dataframe(pd.DataFrame([{c: prof_row[c] for c in adv_avail}]),
                             use_container_width=True, hide_index=True)

            # Percentile bars for advanced stats
            st.markdown('<div class="section-hdr">League Percentiles — Advanced</div>',
                        unsafe_allow_html=True)
            adv_pctile_stats = [
                ("EFF",     "NBA Efficiency",       True),
                ("FIC",     "Floor Impact Ctr",     True),
                ("PRF",     "Pts Responsible For",  True),
                ("PPSA",    "Pts/Scoring Att",      True),
                ("PPS",     "Pts Per Shot",          True),
                ("FTr",     "Free Throw Rate",       True),
                ("TOV%",    "Turnover Rate",         False),
                ("USG",     "Usage Volume",          True),
                ("SC",      "Shots Created",         True),
                ("Q4 PPG",  "Q4 Scoring",            True),
                ("AST%",    "Adj Assist Rate",       True),
                ("AST/TOV", "AST/TOV Ratio",         True),
                ("OREB%",   "Adj Off Reb Rate",      True),
                ("DREB%",   "Adj Def Reb Rate",      True),
            ]
            bars_html = ""
            for col, lbl, hb in adv_pctile_stats:
                if col not in rnk.columns: continue
                val = prof_row.get(col, 0)
                try:
                    val_f = float(val)
                    pct   = _percentile_of(val_f, rnk[col])
                    bars_html += _pctile_bar_html(lbl, round(val_f, 2), pct, hb)
                except Exception:
                    pass
            if bars_html:
                st.markdown(bars_html, unsafe_allow_html=True)

            # Spider chart for advanced
            adv_radar_cols = ["EFF","FIC","PRF","PPSA","Stocks","Q4 PPG","GS","SC"]
            adv_r_avail    = [c for c in adv_radar_cols if c in rnk.columns and c in prof_row.index]
            if len(adv_r_avail) >= 4 and not rnk.empty:
                adv_norm = [_percentile_of(float(prof_row.get(c,0)), rnk[c]) for c in adv_r_avail]
                fig_adv_r = go.Figure(go.Scatterpolar(
                    r=adv_norm + [adv_norm[0]],
                    theta=adv_r_avail + [adv_r_avail[0]],
                    fill="toself", line_color="#f0a500",
                    fillcolor="rgba(240,165,0,0.15)",
                ))
                fig_adv_r.update_layout(
                    **PLOT_LAYOUT,
                    polar=dict(bgcolor="rgba(0,0,0,0)",
                               radialaxis=dict(visible=True, range=[0,100],
                                               tickfont=dict(size=9), gridcolor="#30363d"),
                               angularaxis=dict(tickfont=dict(size=10), gridcolor="#30363d")),
                    title="Advanced Metrics Radar (percentile vs. league)",
                    height=400,
                )
                st.plotly_chart(fig_adv_r, use_container_width=True, key=f"prof_adv_radar_{pid}")

            # ── Rebounding Deep Dive ───────────────────────────────────────────
            st.markdown('<div class="section-hdr">🏀 Rebounding Deep Dive</div>',
                        unsafe_allow_html=True)
            st.caption(
                "Adjusted rates measure what % of available board opportunities "
                "the player grabbed while on court — a fairer comparison than raw totals. "
                "On/Off shows how the *team's* rebounding changes with this player in/out."
            )

            # ── Individual adjusted rates ──────────────────────────────────────
            _oreb_pct_v = float(prof_row.get("OREB%", 0) or 0)
            _dreb_pct_v = float(prof_row.get("DREB%", 0) or 0)
            _trb_pct_v  = float(prof_row.get("TRB%",  0) or 0)
            _oreb_pg_v  = float(prof_row.get("OREB",  0) or 0)
            _dreb_pg_v  = float(prof_row.get("DREB",  0) or 0)

            _rdc1, _rdc2, _rdc3 = st.columns(3)

            def _reb_rate_card(col, label, rate, raw_pg, source_col, higher_label=""):
                """Render a rebound-rate card with percentile bar."""
                if "OREB%" in rnk.columns and source_col in rnk.columns:
                    pct = _percentile_of(rate, rnk[source_col])
                    pct_bar = min(max(pct, 0), 100)
                    clr = ("#2ea043" if pct >= 75 else "#3fb950" if pct >= 50
                           else "#f0a500" if pct >= 25 else "#da3633")
                else:
                    pct, pct_bar, clr = None, 0, "#8b949e"

                pct_str  = f"{pct}th pct" if pct is not None else "—"
                col.markdown(
                    f"<div style='background:#161b22;border:1px solid #30363d;"
                    f"border-radius:10px;padding:12px;text-align:center'>"
                    f"<div style='font-size:10px;color:#8b949e;text-transform:uppercase;"
                    f"letter-spacing:1px;margin-bottom:4px'>{label}</div>"
                    f"<div style='font-size:30px;font-weight:900;color:{clr};line-height:1.1'>"
                    f"{rate:.1f}%</div>"
                    f"<div style='font-size:11px;color:#8b949e;margin-top:2px'>"
                    f"{raw_pg:.1f}/G · {pct_str}</div>"
                    f"<div style='background:#21262d;border-radius:4px;height:5px;"
                    f"overflow:hidden;margin-top:6px'>"
                    f"<div style='width:{pct_bar:.0f}%;background:{clr};height:100%;"
                    f"border-radius:4px'></div></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            _reb_rate_card(_rdc1, "OREB%  (Adj)", _oreb_pct_v, _oreb_pg_v, "OREB%")
            _reb_rate_card(_rdc2, "DREB%  (Adj)", _dreb_pct_v, _dreb_pg_v, "DREB%")
            _reb_rate_card(_rdc3, "TRB%   (Adj)", _trb_pct_v,
                           _oreb_pg_v + _dreb_pg_v, "TRB%")

            st.caption(
                "OREB% = player's offensive rebounds ÷ own-team missed shots while on court.  "
                "DREB% = player's defensive rebounds ÷ opponent missed shots while on court.  "
                "TRB% = total player rebs ÷ avg available rebs per missed shot (on court)."
            )

            st.markdown("---")

            # ── On / Off team rebounding ───────────────────────────────────────
            st.markdown("**On/Off Team Rebounding Impact**")
            st.caption(
                "Does the team rebound better *with* this player on the floor? "
                "Covers all games where this player appeared."
            )

            _prof_team_id_reb = None
            if pid is not None and "Team" in prof_row.index:
                _t_res = query("SELECT id FROM teams WHERE name=?",
                               (str(prof_row.get("Team", "")),))
                if _t_res:
                    _prof_team_id_reb = _t_res[0]["id"]

            if pid is not None and _prof_team_id_reb is not None:
                _onoff = compute_player_rebound_onoff(int(pid), int(_prof_team_id_reb))
                if _onoff and _onoff.get("on_oreb_opps", 0) >= 5:

                    def _delta_clr(d):
                        if d is None: return "#8b949e"
                        return "#2ea043" if d > 1 else "#da3633" if d < -1 else "#f0a500"

                    def _delta_str(on_v, off_v):
                        if on_v is None or off_v is None:
                            return "—"
                        d = on_v - off_v
                        return f"{d:+.1f}%"

                    _oo_rows = [
                        ("Team OREB%",
                         _onoff["on_oreb_pct"], _onoff["off_oreb_pct"],
                         _onoff["on_oreb_opps"], _onoff["off_oreb_opps"]),
                        ("Team DREB%",
                         _onoff["on_dreb_pct"], _onoff["off_dreb_pct"],
                         _onoff["on_dreb_opps"], _onoff["off_dreb_opps"]),
                    ]

                    _oo_c1, _oo_c2 = st.columns(2)
                    for _oo_col, (_oo_lbl, _on_v, _off_v, _on_n, _off_n) in zip(
                            [_oo_c1, _oo_c2], _oo_rows):
                        _d = (_on_v - _off_v) if (_on_v is not None and _off_v is not None) else None
                        _dclr = _delta_clr(_d)
                        _on_str  = f"{_on_v:.1f}%"  if _on_v  is not None else "—"
                        _off_str = f"{_off_v:.1f}%" if _off_v is not None else "—"
                        _delta   = _delta_str(_on_v, _off_v)
                        _impact  = ("↑ Positive" if _d is not None and _d > 1
                                    else "↓ Negative" if _d is not None and _d < -1
                                    else "~ Neutral")
                        _oo_col.markdown(
                            f"<div style='background:#161b22;border:1px solid #30363d;"
                            f"border-radius:10px;padding:14px'>"
                            f"<div style='font-size:11px;color:#8b949e;text-transform:uppercase;"
                            f"letter-spacing:1px;margin-bottom:8px'>{_oo_lbl}</div>"
                            f"<div style='display:flex;justify-content:space-around;"
                            f"align-items:center;margin-bottom:8px'>"
                            f"<div style='text-align:center'>"
                            f"<div style='font-size:9px;color:#8b949e'>ON COURT</div>"
                            f"<div style='font-size:24px;font-weight:800;color:#f0f6fc'>{_on_str}</div>"
                            f"<div style='font-size:10px;color:#484f58'>n={_on_n}</div>"
                            f"</div>"
                            f"<div style='font-size:18px;color:#30363d'>vs</div>"
                            f"<div style='text-align:center'>"
                            f"<div style='font-size:9px;color:#8b949e'>OFF COURT</div>"
                            f"<div style='font-size:24px;font-weight:800;color:#f0f6fc'>{_off_str}</div>"
                            f"<div style='font-size:10px;color:#484f58'>n={_off_n}</div>"
                            f"</div>"
                            f"</div>"
                            f"<div style='text-align:center;padding:6px;background:#0d1117;"
                            f"border-radius:6px'>"
                            f"<span style='font-weight:700;color:{_dclr}'>{_delta}</span>"
                            f"<span style='font-size:11px;color:{_dclr};margin-left:6px'>{_impact}</span>"
                            f"</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                    # Combined TRB% on/off
                    _on_trb  = _onoff.get("on_trb_pct")
                    _off_trb = _onoff.get("off_trb_pct")
                    if _on_trb is not None and _off_trb is not None:
                        _td  = _on_trb - _off_trb
                        _tdc = _delta_clr(_td)
                        st.markdown(
                            f"<div style='margin-top:8px;padding:10px 14px;background:#161b22;"
                            f"border:1px solid #30363d;border-radius:8px;"
                            f"display:flex;align-items:center;gap:12px'>"
                            f"<span style='font-size:12px;color:#8b949e'>Team TRB% (combined):</span>"
                            f"<span style='font-weight:700;color:#f0f6fc'>{_on_trb:.1f}% ON</span>"
                            f"<span style='color:#484f58'>vs</span>"
                            f"<span style='font-weight:700;color:#f0f6fc'>{_off_trb:.1f}% OFF</span>"
                            f"<span style='font-weight:700;color:{_tdc}'>&nbsp;({_td:+.1f}%)</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                elif _onoff and _onoff.get("on_oreb_opps", 0) < 5:
                    st.info("Not enough tracked minutes yet for a reliable on/off split (need ≥5 rebound opportunities on-court).")
                else:
                    st.info("No on/off rebounding data — make sure this player is tracked in at least one game lineup.")
            else:
                st.info("On/off rebounding requires the player's team to be identified.")

            st.markdown("---")

            # ── Playmaking Deep Dive ───────────────────────────────────────────
            st.markdown('<div class="section-hdr">🎯 Playmaking Deep Dive</div>',
                        unsafe_allow_html=True)
            st.caption(
                "AST% measures what fraction of teammate made field goals this player "
                "facilitated while on court — a fairer signal than raw assists per game. "
                "On/Off shows how team assist rate and turnover rate shift with this player in/out."
            )

            # ── Individual adjusted AST% card ─────────────────────────────────
            _ast_pct_v  = float(prof_row.get("AST%",    0) or 0)
            _ast_pg_v   = float(prof_row.get("AST",     0) or 0)
            _astov_v    = float(prof_row.get("AST/TOV", 0) or 0)
            _tov_pg_v   = float(prof_row.get("TOV",     0) or 0)
            _tov_pct_v  = float(prof_row.get("TOV%",    0) or 0)

            _plc1, _plc2, _plc3 = st.columns(3)

            def _pm_rate_card(col, label, val, sub_str, pct_col):
                if pct_col in rnk.columns:
                    _p = _percentile_of(val, rnk[pct_col])
                    _pb = min(max(_p, 0), 100)
                    _clr = ("#2ea043" if _p >= 75 else "#3fb950" if _p >= 50
                            else "#f0a500" if _p >= 25 else "#da3633")
                    _ps  = f"{_p}th pct"
                else:
                    _pb, _clr, _ps = 0, "#8b949e", "—"
                col.markdown(
                    f"<div style='background:#161b22;border:1px solid #30363d;"
                    f"border-radius:10px;padding:12px;text-align:center'>"
                    f"<div style='font-size:10px;color:#8b949e;text-transform:uppercase;"
                    f"letter-spacing:1px;margin-bottom:4px'>{label}</div>"
                    f"<div style='font-size:30px;font-weight:900;color:{_clr};line-height:1.1'>"
                    f"{val:.1f}</div>"
                    f"<div style='font-size:11px;color:#8b949e;margin-top:2px'>{sub_str} · {_ps}</div>"
                    f"<div style='background:#21262d;border-radius:4px;height:5px;"
                    f"overflow:hidden;margin-top:6px'>"
                    f"<div style='width:{_pb:.0f}%;background:{_clr};height:100%;"
                    f"border-radius:4px'></div></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            _pm_rate_card(_plc1, "AST%  (Adj)", _ast_pct_v,
                          f"{_ast_pg_v:.1f} AST/G", "AST%")
            _pm_rate_card(_plc2, "AST/TOV", _astov_v,
                          f"{_ast_pg_v:.1f} AST / {_tov_pg_v:.1f} TOV", "AST/TOV")
            _pm_rate_card(_plc3, "TOV%", _tov_pct_v,
                          f"{_tov_pg_v:.1f} TOV/G", "TOV%")

            st.caption(
                "AST% = player assists ÷ teammate FGM while on court. "
                "TOV% = turnovers ÷ (FGA + 0.44×FTA + TOV). "
                "Both are league-percentile ranked."
            )

            st.markdown("---")

            # ── On / Off team playmaking ───────────────────────────────────────
            st.markdown("**On/Off Team Playmaking Impact**")
            st.caption(
                "Does the team share the ball and protect possessions better "
                "*with* this player on the floor?"
            )

            _prof_team_id_pm = None
            if pid is not None and "Team" in prof_row.index:
                _t_res_pm = query("SELECT id FROM teams WHERE name=?",
                                  (str(prof_row.get("Team", "")),))
                if _t_res_pm:
                    _prof_team_id_pm = _t_res_pm[0]["id"]

            if pid is not None and _prof_team_id_pm is not None:
                _onoff_pm = compute_player_assist_onoff(int(pid), int(_prof_team_id_pm))

                if _onoff_pm and _onoff_pm.get("on_fgm", 0) >= 5:

                    def _pm_delta_clr(d, higher_better=True):
                        if d is None: return "#8b949e"
                        pos = d > 1 if higher_better else d < -1
                        neg = d < -1 if higher_better else d > 1
                        return "#2ea043" if pos else "#da3633" if neg else "#f0a500"

                    _pm_oo_rows = [
                        ("Team AST%",
                         _onoff_pm["on_ast_pct"], _onoff_pm["off_ast_pct"],
                         _onoff_pm["on_fgm"],     _onoff_pm["off_fgm"],
                         True,  "n (FGM)"),
                        ("Team TOV%",
                         _onoff_pm["on_tov_pct"], _onoff_pm["off_tov_pct"],
                         _onoff_pm["on_tov"],     _onoff_pm["off_tov"],
                         False, "n (TOV)"),
                    ]

                    _pm_oo_c1, _pm_oo_c2 = st.columns(2)
                    for _oo_col, (_oo_lbl, _on_v, _off_v, _on_n, _off_n,
                                  _hb, _n_lbl) in zip([_pm_oo_c1, _pm_oo_c2],
                                                       _pm_oo_rows):
                        _d = ((_on_v - _off_v)
                              if _on_v is not None and _off_v is not None else None)
                        _dclr   = _pm_delta_clr(_d, _hb)
                        _on_s   = f"{_on_v:.1f}%"  if _on_v  is not None else "—"
                        _off_s  = f"{_off_v:.1f}%" if _off_v is not None else "—"
                        _impact = ("↑ Positive" if _d is not None and ((_d > 1 and _hb) or (_d < -1 and not _hb))
                                   else "↓ Negative" if _d is not None and ((_d < -1 and _hb) or (_d > 1 and not _hb))
                                   else "~ Neutral")
                        _delta_s = f"{_d:+.1f}%" if _d is not None else "—"
                        _oo_col.markdown(
                            f"<div style='background:#161b22;border:1px solid #30363d;"
                            f"border-radius:10px;padding:14px'>"
                            f"<div style='font-size:11px;color:#8b949e;text-transform:uppercase;"
                            f"letter-spacing:1px;margin-bottom:8px'>{_oo_lbl}</div>"
                            f"<div style='display:flex;justify-content:space-around;"
                            f"align-items:center;margin-bottom:8px'>"
                            f"<div style='text-align:center'>"
                            f"<div style='font-size:9px;color:#8b949e'>ON COURT</div>"
                            f"<div style='font-size:24px;font-weight:800;color:#f0f6fc'>{_on_s}</div>"
                            f"<div style='font-size:10px;color:#484f58'>{_n_lbl}={_on_n}</div>"
                            f"</div>"
                            f"<div style='font-size:18px;color:#30363d'>vs</div>"
                            f"<div style='text-align:center'>"
                            f"<div style='font-size:9px;color:#8b949e'>OFF COURT</div>"
                            f"<div style='font-size:24px;font-weight:800;color:#f0f6fc'>{_off_s}</div>"
                            f"<div style='font-size:10px;color:#484f58'>{_n_lbl}={_off_n}</div>"
                            f"</div>"
                            f"</div>"
                            f"<div style='text-align:center;padding:6px;background:#0d1117;"
                            f"border-radius:6px'>"
                            f"<span style='font-weight:700;color:{_dclr}'>{_delta_s}</span>"
                            f"<span style='font-size:11px;color:{_dclr};margin-left:6px'>{_impact}</span>"
                            f"</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

                    # AST/G on vs off — quick context line
                    _on_apg  = _onoff_pm.get("on_ast_pg",  0)
                    _off_apg = _onoff_pm.get("off_ast_pg", 0)
                    _apg_d   = _on_apg - _off_apg
                    _adc     = _pm_delta_clr(_apg_d, True)
                    st.markdown(
                        f"<div style='margin-top:8px;padding:10px 14px;background:#161b22;"
                        f"border:1px solid #30363d;border-radius:8px'>"
                        f"<span style='font-size:12px;color:#8b949e'>Team AST/G:&nbsp;</span>"
                        f"<span style='font-weight:700;color:#f0f6fc'>{_on_apg:.1f} ON</span>"
                        f"<span style='color:#484f58'>&nbsp;vs&nbsp;</span>"
                        f"<span style='font-weight:700;color:#f0f6fc'>{_off_apg:.1f} OFF</span>"
                        f"<span style='font-weight:700;color:{_adc}'>&nbsp;({_apg_d:+.1f}/G)</span>"
                        f"<span style='font-size:11px;color:#484f58'>"
                        f"&nbsp;· across {_onoff_pm['n_games']} game(s)</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                elif _onoff_pm and _onoff_pm.get("on_fgm", 0) < 5:
                    st.info("Not enough tracked possessions yet for a reliable on/off split (need ≥5 team FGM on-court).")
                else:
                    st.info("No on/off playmaking data — ensure this player is tracked in at least one game lineup.")
            else:
                st.info("On/off playmaking requires the player's team to be identified.")

        # ── Per-36 ────────────────────────────────────────────────────────────
        with p_tab_per36:
            st.markdown('<div class="section-hdr">Per-36 Minutes Stats</div>',
                        unsafe_allow_html=True)
            per36_cols = ["PTS32","REB32","AST32","STL32","BLK32","TOV32","SC32"]
            p36_avail  = [c for c in per36_cols if c in prof_row.index]
            if p36_avail:
                _min_pg = float(prof_row.get("MIN", 0))
                if _min_pg < 5:
                    st.info("Per-36 stats require ≥5 MIN/G. This player doesn't have enough tracked minutes yet.")
                else:
                    p36_data = {c.replace("32",""):prof_row[c] for c in p36_avail
                                if prof_row[c] is not None}
                    st.dataframe(pd.DataFrame([p36_data]),
                                 use_container_width=True, hide_index=True)
                    # Bar chart
                    p36_labels = list(p36_data.keys())
                    p36_vals   = [float(v) if v is not None else 0.0 for v in p36_data.values()]
                    if p36_labels:
                        fig_p36 = go.Figure(go.Bar(
                            x=p36_labels, y=p36_vals,
                            marker_color=["#f0a500","#3498db","#2ecc71","#58a6ff","#e74c3c","#e67e22","#9b59b6"][:len(p36_labels)],
                            text=[f"{v:.1f}" for v in p36_vals],
                            textposition="outside",
                        ))
                        fig_p36.update_layout(**PLOT_LAYOUT, title="Per-36 Min Projections",
                                              yaxis=dict(range=[0, max(p36_vals)*1.25+1]),
                                              height=320)
                        st.plotly_chart(fig_p36, use_container_width=True, key=f"prof_p36_{pid}")
                    st.caption("Per-36 = actual totals × 36 ÷ total tracked minutes. Requires ≥5 MIN/G.")
            else:
                st.info("Per-36 data not available for this player.")

        # ── Ratings ───────────────────────────────────────────────────────────
        with p_tab_ratings:
            if not rat.empty and pid is not None and "pid" in rat.columns:
                p_rat = rat[rat["pid"] == pid]
                if not p_rat.empty and float(p_rat.iloc[0].get("GP", 0)) >= 1:
                    pr = p_rat.iloc[0]
                    rating_cols = [c for c in ["OVRL","OFF","DEF","PLY","REB_R"] if c in pr.index]
                    if rating_cols:
                        r_colors = {"OVRL":"#f0a500","OFF":"#e74c3c","DEF":"#3498db",
                                    "PLY":"#2ecc71","REB_R":"#e67e22"}
                        fig_rat = go.Figure(go.Bar(
                            x=rating_cols,
                            y=[float(pr[c]) for c in rating_cols],
                            marker_color=[r_colors.get(c,"#8b949e") for c in rating_cols],
                            text=[f"{float(pr[c]):.1f}" for c in rating_cols],
                            textposition="outside",
                        ))
                        fig_rat.update_layout(**PLOT_LAYOUT, yaxis=dict(range=[0,115]),
                                              title="Player Ratings (0–100 scale)", height=320)
                        st.plotly_chart(fig_rat, use_container_width=True, key=f"prof_rat_{pid}")

                        # Ratings table with descriptions
                        r_labels = {"OVRL":"Overall Rating","OFF":"Offensive Rating",
                                    "DEF":"Defensive Rating","PLY":"Playmaking Rating",
                                    "REB_R":"Rebounding Rating"}
                        r_rows = [{"Rating":r_labels.get(c,c),"Code":c,
                                   "Score":f"{float(pr[c]):.1f}"}
                                  for c in rating_cols]
                        st.dataframe(pd.DataFrame(r_rows), use_container_width=True, hide_index=True)

                        # Percentile bars for ratings vs league
                        if not rat.empty:
                            st.markdown('<div class="section-hdr">Rating Percentiles vs League</div>',
                                        unsafe_allow_html=True)
                            rat_bars = ""
                            for col in rating_cols:
                                if col not in rat.columns: continue
                                val = float(pr.get(col, 0))
                                pct = _percentile_of(val, rat[col])
                                rat_bars += _pctile_bar_html(r_labels.get(col,col), round(val,1), pct)
                            st.markdown(rat_bars, unsafe_allow_html=True)
                else:
                    st.info("Player needs at least 1 GP for ratings.")
            else:
                st.info("No rating data available.")

        # ── OVRL Ranking ──────────────────────────────────────────────────────
        with p_tab_rank:
            if rat.empty or "OVRL" not in rat.columns:
                st.info("No OVRL data yet — log at least 1 game to compute rankings.")
            elif pid is None or "pid" not in rat.columns:
                st.info("Player not found in ratings pool.")
            else:
                p_rat_ov = rat[rat["pid"] == pid]
                if p_rat_ov.empty or float(p_rat_ov.iloc[0].get("GP",0)) < 1:
                    st.info("This player needs at least 1 GP for an OVRL ranking.")
                else:
                    _ov_all = rat[["pid","Player","Team","GP","OVRL",
                                   "PTS","AST","REB","STL","BLK","TOV","TS%"]].copy()
                    _ov_all = _ov_all.sort_values("OVRL", ascending=False).reset_index(drop=True)
                    _ov_all["Rank"] = _ov_all.index + 1
                    _ov_all["_label"] = _ov_all.apply(
                        lambda r: f"#{int(r['Rank'])}  {r['Player']} ({r['Team']})", axis=1)

                    total_players    = len(_ov_all)
                    player_rank_row  = _ov_all[_ov_all["pid"] == pid].iloc[0]
                    player_rank      = int(player_rank_row["Rank"])
                    player_ovrl      = float(player_rank_row["OVRL"])
                    pct_tile         = round((total_players-player_rank)/max(total_players-1,1)*100)

                    tier = ("👑 Elite"      if player_ovrl >= 80 else
                            "⭐ Great"      if player_ovrl >= 65 else
                            "✅ Above Avg"  if player_ovrl >= 50 else
                            "📊 Average"   if player_ovrl >= 35 else "📉 Below Avg")
                    tier_color = ("#f0a500" if player_ovrl >= 80 else
                                  "#2ecc71" if player_ovrl >= 65 else
                                  "#58a6ff" if player_ovrl >= 50 else
                                  "#c9d1d9" if player_ovrl >= 35 else "#8b949e")

                    rk1, rk2, rk3 = st.columns(3)
                    rk1.metric("League Rank",  f"#{player_rank} of {total_players}")
                    rk2.metric("OVRL Score",   f"{player_ovrl:.1f}")
                    rk3.metric("Percentile",   f"{pct_tile}th")
                    st.markdown(
                        f"<div style='text-align:center;font-size:22px;font-weight:800;"
                        f"color:{tier_color};margin:10px 0 18px'>{tier}</div>",
                        unsafe_allow_html=True)

                    # Stat-by-stat rank table
                    st.markdown('<div class="section-hdr">Stat Rankings</div>',
                                unsafe_allow_html=True)
                    _rank_stats = ["OVRL","OFF","DEF","PLY","REB_R",
                                   "PTS","AST","REB","STL","BLK","TOV","TS%","EFF","FIC"]
                    _rank_rows  = []
                    for stat in _rank_stats:
                        _src = rat if stat in ["OVRL","OFF","DEF","PLY","REB_R"] else rnk
                        _pid_col = "pid"
                        if stat not in _src.columns or _pid_col not in _src.columns:
                            continue
                        _sorted = _src.sort_values(stat, ascending=(stat == "TOV")).reset_index(drop=True)
                        _sorted["_rank"] = _sorted.index + 1
                        _match = _sorted[_sorted[_pid_col] == pid]
                        if _match.empty: continue
                        sr = int(_match.iloc[0]["_rank"])
                        sv = float(p_rat_ov.iloc[0].get(stat, 0) if stat in ["OVRL","OFF","DEF","PLY","REB_R"]
                                   else prof_row.get(stat, 0))
                        sp = round((total_players - sr) / max(total_players-1,1) * 100)
                        _rank_rows.append({"Stat":stat,"Value":f"{sv:.1f}",
                                           "Rank":f"#{sr} of {total_players}","Percentile":f"{sp}th"})
                    if _rank_rows:
                        st.dataframe(pd.DataFrame(_rank_rows),
                                     use_container_width=True, hide_index=True)

                    # League bar chart
                    st.markdown("---")
                    _bar_df = _ov_all.sort_values("OVRL", ascending=True)
                    _bar_colors = ["#f0a500" if int(r["pid"])==int(pid) else "#30363d"
                                   for _,r in _bar_df.iterrows()]
                    fig_rank = go.Figure(go.Bar(
                        x=_bar_df["OVRL"], y=_bar_df["_label"],
                        orientation="h", marker_color=_bar_colors,
                        text=[f"{v:.1f}" if int(r["pid"])==int(pid) else ""
                              for v, (_,r) in zip(_bar_df["OVRL"], _bar_df.iterrows())],
                        textposition="outside",
                        textfont=dict(color="#f0a500", size=13),
                    ))
                    fig_rank.update_layout(
                        **PLOT_LAYOUT,
                        title=f"OVRL League Rankings — {prof_row['Player']} highlighted",
                        xaxis=dict(range=[0,108], showgrid=False, title="OVRL"),
                        yaxis=dict(tickfont=dict(size=10)),
                        height=max(380, total_players*26),
                    )
                    st.plotly_chart(fig_rank, use_container_width=True,
                                    key=f"prof_ovrl_rank_{pid}")

        # ── Game Log ──────────────────────────────────────────────────────────
        with p_tab_log:
            if pid is not None:
                # Reuse pre-fetched game log (computed above before the tabs)
                game_log_data = _game_log_data

                if game_log_data:
                    gl_df = pd.DataFrame(game_log_data)

                    # Trend chart
                    st.markdown('<div class="section-hdr">Performance Trend</div>',
                                unsafe_allow_html=True)
                    _trend_cols = [c for c in ["PTS","AST","REB","Stocks"] if c in gl_df.columns]

                    # Compute Stocks if not present
                    if "Stocks" not in gl_df.columns and "STL" in gl_df.columns and "BLK" in gl_df.columns:
                        gl_df["Stocks"] = gl_df["STL"].fillna(0) + gl_df["BLK"].fillna(0)
                        if "Stocks" not in _trend_cols:
                            _trend_cols.append("Stocks")

                    _trend_sel = st.multiselect("Stats to trend", _trend_cols,
                                                default=["PTS"] if "PTS" in _trend_cols else _trend_cols[:1],
                                                key=f"trend_sel_{pid}")
                    if _trend_sel:
                        # Reverse so oldest is left
                        _trend_df = gl_df.iloc[::-1].reset_index(drop=True)
                        # x-axis label: "MMM DD vs OPP (W/L)"
                        def _xlbl(r):
                            try:
                                _d = pd.to_datetime(r.get("Date",""), errors="coerce")
                                _d_str = _d.strftime("%b %d") if not pd.isnull(_d) else str(r.get("Date",""))
                            except Exception:
                                _d_str = str(r.get("Date",""))
                            return f"{_d_str} vs {r.get('Opp','?')} ({r.get('W/L','')})"
                        _trend_df["_xlbl"] = _trend_df.apply(_xlbl, axis=1)
                        fig_trend = go.Figure()
                        _tcols = ["#f0a500","#3498db","#2ecc71","#e74c3c"]
                        for ti, ts in enumerate(_trend_sel):
                            if ts not in _trend_df.columns: continue
                            _y = pd.to_numeric(_trend_df[ts], errors="coerce").fillna(0)
                            fig_trend.add_trace(go.Scatter(
                                x=_trend_df["_xlbl"], y=_y,
                                mode="lines+markers", name=ts,
                                line=dict(color=_tcols[ti % len(_tcols)], width=2),
                                marker=dict(size=7),
                                hovertemplate=f"<b>%{{x}}</b><br>{ts}: %{{y}}<extra></extra>",
                            ))
                        # Rolling average overlay
                        if "PTS" in _trend_sel and "PTS" in _trend_df.columns:
                            _roll = pd.to_numeric(_trend_df["PTS"], errors="coerce").rolling(3, min_periods=1).mean()
                            fig_trend.add_trace(go.Scatter(
                                x=_trend_df["_xlbl"], y=_roll,
                                mode="lines", name="PTS 3-game avg",
                                line=dict(color="#f0a500", width=1, dash="dot"),
                                opacity=0.6,
                            ))
                        fig_trend.update_layout(
                            **PLOT_LAYOUT, title="Game-by-Game Performance",
                            xaxis=dict(title="", tickangle=-35, showgrid=False,
                                       automargin=True),
                            yaxis=dict(title="Value", showgrid=True, gridcolor="#21262d"),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02),
                            height=380,
                        )
                        st.plotly_chart(fig_trend, use_container_width=True,
                                        key=f"prof_trend_{pid}")

                    # W/L coloring in log
                    show_log_cols = [c for c in
                        ["Date","Opp","W/L","Score","PTS","AST","REB","STL","BLK",
                         "TOV","FGM","FGA","FG%","3PM","3PA","3P%","FTM","FTA","FT%",
                         "SC","SCS","SCP","SCO","+/-","MIN","GS"]
                        if c in gl_df.columns]
                    st.markdown('<div class="section-hdr">Game Log</div>',
                                unsafe_allow_html=True)
                    st.dataframe(gl_df[show_log_cols], use_container_width=True, hide_index=True)
                else:
                    # Fallback: simple log from DB
                    game_log = query("""
                        SELECT g.date, t1.name AS t1, t2.name AS t2,
                               g.home_score, g.away_score, g.tracked
                        FROM game_lineup_players glp
                        JOIN games g ON g.id = glp.game_id
                        JOIN teams t1 ON t1.id = g.team1_id
                        JOIN teams t2 ON t2.id = g.team2_id
                        WHERE glp.player_id = ?
                        ORDER BY g.date DESC
                    """, (int(pid),))
                    if game_log:
                        gl2 = pd.DataFrame(game_log)
                        gl2["Matchup"] = gl2["t1"] + " vs " + gl2["t2"]
                        gl2["Score"]   = gl2["home_score"].astype(str) + "–" + gl2["away_score"].astype(str)
                        gl2["Tracked"] = gl2["tracked"].apply(lambda x: "✓" if x else "")
                        st.dataframe(gl2[["date","Matchup","Score","Tracked"]].rename(columns={"date":"Date"}),
                                     use_container_width=True, hide_index=True)
                    else:
                        st.info("No game appearances found for this player.")

                    # Percentile bars for core stats in profile
            st.markdown("---")
            st.markdown('<div class="section-hdr">Career Stat Percentiles</div>',
                        unsafe_allow_html=True)
            PROF_PCTILE = [
                ("PTS","Points",True),("REB","Rebounds",True),("AST","Assists",True),
                ("STL","Steals",True),("BLK","Blocks",True),("TOV","Turnovers",False),
                ("eFG%","eFG%",True),("TS%","TS%",True),("FTr","FT Rate",True),
                ("PPSA","Pts/Scoring Att",True),("EFF","Efficiency",True),
                ("FIC","Floor Impact",True),("SC","Shots Created",True),
                ("Q4 PPG","Q4 PPG",True),("+/-","Plus/Minus",True),
            ]
            bars = ""
            for col, lbl, hb in PROF_PCTILE:
                if col not in rnk.columns: continue
                val = prof_row.get(col, 0)
                try:
                    val_f = float(val)
                    pct   = _percentile_of(val_f, rnk[col])
                    bars += _pctile_bar_html(lbl, round(val_f, 1), pct, hb)
                except Exception:
                    pass
            if bars:
                st.markdown(bars, unsafe_allow_html=True)

        # ══════════════════════════════════════════════════════════════════════
        #  GAME SCORE GRAPH  (Hollinger, game-by-game)
        # ══════════════════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown('<div class="section-hdr">📈 Game Score — Game by Game</div>',
                    unsafe_allow_html=True)

        if not _gl_df.empty and "GS" in _gl_df.columns:
            _gs_plot = _gl_df.iloc[::-1].reset_index(drop=True)
            _gs_plot["GS_num"] = pd.to_numeric(_gs_plot["GS"], errors="coerce").fillna(0)
            _gs_avg            = _gs_plot["GS_num"].mean()

            # x-axis label: "MMM DD vs OPP"
            def _gs_xlbl(r):
                try:
                    _d = pd.to_datetime(r.get("Date", ""), errors="coerce")
                    _d_str = _d.strftime("%b %d") if not pd.isnull(_d) else str(r.get("Date", ""))
                except Exception:
                    _d_str = str(r.get("Date", ""))
                return f"{_d_str} vs {r.get('Opp', '?')}"
            _gs_plot["_xlbl"] = _gs_plot.apply(_gs_xlbl, axis=1)

            # Colour each bar: green if >= average, red if below
            _bar_colors = [
                "#2ecc71" if v >= _gs_avg else "#e74c3c"
                for v in _gs_plot["GS_num"]
            ]

            # Hover labels
            _hover_lbl = []
            for _, _gr in _gs_plot.iterrows():
                _wl  = _gr.get("W/L", "")
                _opp = _gr.get("Opp", "")
                _sc  = _gr.get("Score", "")
                _pts = _gr.get("PTS", 0)
                _ast = _gr.get("AST", 0)
                _reb = _gr.get("REB", 0)
                _hover_lbl.append(
                    f"<b>{_gr['_xlbl']}</b> ({_wl})<br>"
                    f"Score: {_sc}<br>"
                    f"GS: <b>{_gr['GS_num']:.1f}</b><br>"
                    f"{_pts} pts · {_reb} reb · {_ast} ast"
                )

            _fig_gs = go.Figure()

            # Bar trace
            _fig_gs.add_trace(go.Bar(
                x=_gs_plot["_xlbl"],
                y=_gs_plot["GS_num"],
                marker_color=_bar_colors,
                hovertemplate="%{customdata}<extra></extra>",
                customdata=_hover_lbl,
                name="Game Score",
            ))

            # Rolling 3-game average line
            _gs_roll = _gs_plot["GS_num"].rolling(3, min_periods=1).mean()
            _fig_gs.add_trace(go.Scatter(
                x=_gs_plot["_xlbl"], y=_gs_roll,
                mode="lines", name="3-game avg",
                line=dict(color="#f0a500", width=2, dash="dot"),
                hoverinfo="skip",
            ))

            # Season average reference line
            _fig_gs.add_hline(
                y=_gs_avg, line_dash="dash", line_color="#8b949e", line_width=1,
                annotation_text=f"Avg {_gs_avg:.1f}",
                annotation_position="top right",
                annotation_font=dict(color="#8b949e", size=11),
            )

            _fig_gs.update_layout(
                **PLOT_LAYOUT,
                height=340,
                bargap=0.25,
                xaxis=dict(title="", tickangle=-35, showgrid=False, automargin=True),
                yaxis=dict(title="Game Score", showgrid=True, gridcolor="#21262d"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                showlegend=True,
            )
            st.plotly_chart(_fig_gs, use_container_width=True, key=f"gs_graph_{pid}")
        else:
            st.info("Not enough tracked game data to display a Game Score trend.")

        # ══════════════════════════════════════════════════════════════════════
        #  SCOUTING REPORT  (rule-based, always visible below the tabs)
        # ══════════════════════════════════════════════════════════════════════
        st.markdown("---")
        st.markdown('<div class="section-hdr">🔍 Scouting Report</div>',
                    unsafe_allow_html=True)

        # ── Pull numeric values with safe defaults ────────────────────────────
        def _fv(key, default=0.0):
            try: return float(prof_row.get(key, default) or default)
            except (TypeError, ValueError): return float(default)

        _s_pts     = _fv("PTS");       _s_reb    = _fv("REB")
        _s_ast     = _fv("AST");       _s_stl    = _fv("STL")
        _s_blk     = _fv("BLK");       _s_tov    = _fv("TOV")
        _s_fgp     = _fv("FG%");       _s_tpp    = _fv("3P%")
        _s_ftp     = _fv("FT%");       _s_efg    = _fv("eFG%")
        _s_ts      = _fv("TS%");       _s_oreb   = _fv("OREB")
        _s_dreb    = _fv("DREB");      _s_pf     = _fv("PF")
        _s_tpa     = _fv("3PA");       _s_fta    = _fv("FTA")
        _s_min     = _fv("MIN");       _s_gp     = _fv("GP")
        _s_pps     = _fv("PPS");       _s_ppsa   = _fv("PPSA")
        _s_tov_pct = _fv("TOV%");      _s_ftr    = _fv("FTr")
        _s_ast_tov = _fv("AST/TOV");   _s_sc     = _fv("SC")
        _s_pm      = _fv("+/-");       _s_q4     = _fv("Q4 PPG")
        _s_stocks  = _fv("Stocks");    _s_dsh    = _fv("DSh%")
        _s_ast_pct = _fv("AST%");      _s_oreb_p = _fv("OREB%")
        _s_dreb_p  = _fv("DREB%");     _s_trb_p  = _fv("TRB%")
        _s_efg_dec = _s_efg / 100      # percentage → decimal

        # Ratings row (may be absent for players with <2 GP)
        _s_rat = {}
        if not rat.empty and pid is not None and "pid" in rat.columns:
            _rat_match = rat[rat["pid"] == pid]
            if not _rat_match.empty:
                _r = _rat_match.iloc[0]
                for _rc in ("OFF","DEF","PLY","REB_R","OVRL"):
                    try: _s_rat[_rc] = float(_r.get(_rc, 0) or 0)
                    except (TypeError, ValueError): _s_rat[_rc] = 0.0

        _off  = _s_rat.get("OFF",   0)
        _def  = _s_rat.get("DEF",   0)
        _ply  = _s_rat.get("PLY",   0)
        _reb  = _s_rat.get("REB_R", 0)
        _ovrl = _s_rat.get("OVRL",  0)

        # ── Percentile helper (vs full rnk pool) ──────────────────────────────
        def _pct(col):
            if col not in rnk.columns: return 50
            try: return _percentile_of(float(prof_row.get(col, 0) or 0), rnk[col])
            except Exception: return 50

        # ── Archetype ─────────────────────────────────────────────────────────
        if _ovrl >= 80 and _def >= 68:
            _archetype = ("👑", "Elite Two-Way Player",
                          "Excels on both ends — a rare combination of offensive production and defensive impact.")
        elif _off >= 80 and _s_pts >= 14:
            _archetype = ("⚡", "Scoring Machine",
                          "A primary offensive weapon who creates points consistently and efficiently.")
        elif _ply >= 75 and _s_ast_pct >= 18:
            _archetype = ("🎯", "Floor General",
                          "Controls the offense through vision and distribution. The team runs through this player.")
        elif _reb >= 75 or (_s_trb_p >= 12 and _s_reb >= 6):
            _archetype = ("📦", "Glass Cleaner",
                          "Dominates the rebounding battle on both ends, generating extra possessions for the team.")
        elif _def >= 75 or (_s_stocks >= 3 and _s_dsh >= 12):
            _archetype = ("🛡️", "Defensive Anchor",
                          "High-impact defender whose presence disrupts opponents through steals, blocks, and contests.")
        elif _s_tpp >= 36 and _s_tpa >= 2 and _s_dsh >= 10:
            _archetype = ("🏹", "3-and-D Specialist",
                          "Punishes opponents with the three ball and holds their own defensively — a valuable role player.")
        elif _s_tpp >= 36 and _s_tpa >= 2.5 and _s_ast <= 2:
            _archetype = ("🎪", "Spot-Up Shooter",
                          "An off-ball threat who makes defenses pay for leaving them open beyond the arc.")
        elif _s_fv("PaintFG%") >= 54 and _s_reb >= 4:
            _archetype = ("🔨", "Interior Presence",
                          "Operates close to the basket with efficiency, finishing strong and commanding the paint.")
        elif _ovrl >= 55:
            _archetype = ("🧩", "Versatile Contributor",
                          "A well-rounded player who contributes across multiple areas without a single dominant trait.")
        elif _s_min >= 20 and _s_pm >= 3:
            _archetype = ("🔋", "High-Impact Role Player",
                          "Team plays better with this player on the floor. Wins through effort and smart decisions.")
        else:
            _archetype = ("📊", "Developing Player",
                          "Building their game. Stats are still developing — more tracked games will sharpen the picture.")

        # ── Render archetype banner ───────────────────────────────────────────
        st.markdown(
            f"<div style='background:linear-gradient(135deg,#1a1200,#0d1117);"
            f"border:1px solid #f0a500;border-radius:12px;padding:14px 18px;"
            f"margin-bottom:14px;display:flex;align-items:center;gap:14px'>"
            f"<span style='font-size:32px'>{_archetype[0]}</span>"
            f"<div><div style='font-size:15px;font-weight:800;color:#f0a500'>{_archetype[1]}</div>"
            f"<div style='font-size:12px;color:#8b949e;margin-top:3px'>{_archetype[2]}</div></div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Build strengths list ──────────────────────────────────────────────
        _strengths_sr: list[tuple[str, str]] = []   # (label, detail)

        # Scoring
        if _s_pts >= 18:
            _strengths_sr.append(("Elite scorer",
                f"{_s_pts:.1f} PPG — top-{100-_pct('PTS')}% of tracked players."))
        elif _s_pts >= 12:
            _strengths_sr.append(("Consistent scorer",
                f"{_s_pts:.1f} PPG with solid production game-to-game."))
        if _s_efg_dec >= 0.54:
            _strengths_sr.append(("Efficient shooter",
                f"eFG% {_s_efg:.1f}% — squeezes high value from each attempt."))
        if _s_tpp >= 36 and _s_tpa >= 2:
            _strengths_sr.append(("3-point threat",
                f"{_s_tpp:.1f}% on {_s_tpa:.1f} attempts/G — a credible stretch option."))
        if _s_ftp >= 80 and _s_fta >= 2:
            _strengths_sr.append(("Reliable at the line",
                f"{_s_ftp:.1f}% FT% converts free chances into points."))
        if _s_q4 >= _s_pts * 0.30 and _s_q4 >= 4:
            _strengths_sr.append(("Clutch performer",
                f"{_s_q4:.1f} Q4 PPG — raises the level when it matters most."))
        if _s_pps >= 1.05:
            _strengths_sr.append(("High-quality shot selection",
                f"{_s_pps:.2f} PPS — generates above-average value per attempt."))

        # Rebounding
        if _s_oreb_p >= 12:
            _strengths_sr.append(("Offensive glass presence",
                f"OREB% {_s_oreb_p:.1f}% — consistently generates second-chance opportunities."))
        elif _s_oreb >= 2.5:
            _strengths_sr.append(("Active offensive rebounder",
                f"{_s_oreb:.1f} OREB/G keeps possessions alive."))
        if _s_dreb_p >= 22:
            _strengths_sr.append(("Defensive rebounding anchor",
                f"DREB% {_s_dreb_p:.1f}% — cleans the glass and ends opponent possessions."))
        elif _s_reb >= 7:
            _strengths_sr.append(("Dominant rebounder",
                f"{_s_reb:.1f} RPG — controls the boards on both ends."))

        # Playmaking
        if _s_ast_pct >= 22:
            _strengths_sr.append(("Elite facilitator",
                f"AST% {_s_ast_pct:.1f}% — facilitates a high share of teammate field goals."))
        elif _s_ast >= 4:
            _strengths_sr.append(("Playmaking presence",
                f"{_s_ast:.1f} APG creates consistent scoring chances for teammates."))
        if _s_ast_tov >= 3.0 and _s_ast >= 2:
            _strengths_sr.append(("Excellent ball security",
                f"AST/TOV {_s_ast_tov:.1f} — makes good decisions under pressure."))

        # Defense
        if _s_stl >= 2.0:
            _strengths_sr.append(("Disruptive hands",
                f"{_s_stl:.1f} SPG — creates turnovers and ignites transition."))
        elif _s_stl >= 1.3:
            _strengths_sr.append(("Active on-ball defender",
                f"{_s_stl:.1f} SPG demonstrates consistent defensive pressure."))
        if _s_blk >= 1.5:
            _strengths_sr.append(("Shot-blocking threat",
                f"{_s_blk:.1f} BPG alters the opponent's interior game."))
        if _s_dsh >= 14 and _s_stl + _s_blk >= 1.5:
            _strengths_sr.append(("High contest rate",
                f"DSh% {_s_dsh:.1f}% — consistently challenges shots on defense."))

        # Impact
        if _s_pm >= 6:
            _strengths_sr.append(("Strong net impact",
                f"+{_s_pm:.1f} +/- per game — team consistently outscores opponents with them on court."))

        # Cap at 4 strongest
        _strengths_sr = _strengths_sr[:4]

        # ── Build weaknesses list ─────────────────────────────────────────────
        _weaknesses_sr: list[tuple[str, str]] = []

        # Shooting
        if _s_efg_dec < 0.42 and _s_fv("FGA") >= 3:
            _weaknesses_sr.append(("Below-average shooting efficiency",
                f"eFG% {_s_efg:.1f}% — shot selection or finishing needs work."))
        elif _s_efg_dec < 0.47 and _s_fv("FGA") >= 4:
            _weaknesses_sr.append(("Inconsistent shooting",
                f"eFG% {_s_efg:.1f}% leaves efficiency gains on the table."))
        if _s_tpp < 27 and _s_tpa >= 2.5:
            _weaknesses_sr.append(("Poor 3-point selection",
                f"{_s_tpp:.1f}% on {_s_tpa:.1f} attempts/G — 3-point volume isn't justified by accuracy."))
        elif _s_tpp < 32 and _s_tpa >= 3:
            _weaknesses_sr.append(("Streaky from three",
                f"{_s_tpp:.1f}% 3P% — opponents may be comfortable leaving open."))
        if _s_ftp < 62 and _s_fta >= 2.5:
            _weaknesses_sr.append(("Exploitable at the free-throw line",
                f"{_s_ftp:.1f}% FT% — opponents may intentionally foul in close games."))

        # Turnovers
        if _s_tov_pct >= 22:
            _weaknesses_sr.append(("Turnover-prone",
                f"TOV% {_s_tov_pct:.1f}% — careless with the ball; opponents benefit from extra possessions."))
        elif _s_ast_tov < 1.0 and _s_ast >= 1.5:
            _weaknesses_sr.append(("Poor AST/TOV ratio",
                f"AST/TOV {_s_ast_tov:.1f} — gives back possessions almost as often as creating them."))

        # Rebounding
        if _s_oreb_p < 4 and _s_min >= 16 and _s_reb < 3:
            _weaknesses_sr.append(("Limited glass presence",
                "Doesn't crash the offensive boards — leaves second-chance points behind."))
        if _s_dreb_p < 10 and _s_min >= 16 and _s_reb < 3:
            _weaknesses_sr.append(("Soft on the defensive boards",
                "Opponents get too many second chances with this player on court."))

        # Defense
        if _s_stl < 0.4 and _s_blk < 0.3 and _s_min >= 18 and _s_dsh < 6:
            _weaknesses_sr.append(("Low defensive impact",
                f"Minimal steals, blocks, or contests with {_s_min:.0f} MIN/G — limited defensive presence."))

        # Fouls
        if _s_pf >= 3.5 and _s_min >= 15:
            _weaknesses_sr.append(("Foul trouble risk",
                f"{_s_pf:.1f} PF/G — stays on the floor by staying out of foul trouble."))

        # Production vs minutes
        if _s_pts < 5 and _s_ast < 2 and _s_reb < 3 and _s_min >= 18:
            _weaknesses_sr.append(("Needs to contribute more",
                f"Limited output ({_s_pts:.1f} pts / {_s_reb:.1f} reb / {_s_ast:.1f} ast) for the minutes played."))

        # Cap at 3
        _weaknesses_sr = _weaknesses_sr[:3]

        # ── Render strengths / weaknesses two-column ──────────────────────────
        _sr_c1, _sr_c2 = st.columns(2)

        def _scout_bullets(col, header_emoji, header_text, header_clr, items):
            bullets_html = "".join(
                f"<div style='margin-bottom:9px'>"
                f"<div style='font-size:13px;font-weight:700;color:#f0f6fc'>{lbl}</div>"
                f"<div style='font-size:12px;color:#8b949e;margin-top:1px'>{detail}</div>"
                f"</div>"
                for lbl, detail in items
            )
            if not items:
                bullets_html = (
                    "<div style='font-size:12px;color:#484f58;font-style:italic'>"
                    "Not enough data to identify clear patterns yet.</div>"
                )
            col.markdown(
                f"<div style='background:#161b22;border:1px solid #30363d;"
                f"border-radius:10px;padding:14px'>"
                f"<div style='font-size:13px;font-weight:700;color:{header_clr};"
                f"margin-bottom:10px'>{header_emoji} {header_text}</div>"
                f"{bullets_html}"
                f"</div>",
                unsafe_allow_html=True,
            )

        _scout_bullets(_sr_c1, "✅", "Strengths", "#2ea043", _strengths_sr)
        _scout_bullets(_sr_c2, "⚠️", "Areas to Watch", "#f0a500", _weaknesses_sr)

        # ── One-line scout summary ────────────────────────────────────────────
        if _strengths_sr or _weaknesses_sr:
            _top_str = _strengths_sr[0][0].lower()  if _strengths_sr  else None
            _top_wk  = _weaknesses_sr[0][0].lower() if _weaknesses_sr else None
            _summary_parts = []
            if _top_str:
                _summary_parts.append(f"Best asset: <b style='color:#f0f6fc'>{_top_str}</b>")
            if _top_wk:
                _summary_parts.append(f"key concern: <b style='color:#f0f6fc'>{_top_wk}</b>")
            if _summary_parts:
                st.markdown(
                    f"<div style='margin-top:8px;font-size:12px;color:#8b949e;"
                    f"padding:8px 12px;background:#0d1117;border-radius:6px'>"
                    f"📋 Scout note — {' · '.join(_summary_parts)}.</div>",
                    unsafe_allow_html=True,
                )
