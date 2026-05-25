import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from pandas.io.formats.style import Styler as _PdStyler
from Database.db import query, initialize_database
from helpers.settings_utils import get_all_settings, apply_theme_css
from helpers.stats_players import compute_player_rankings, compute_player_ratings, compute_official_stats
from helpers.stats_team import compute_player_game_log

initialize_database()
_cfg = get_all_settings()
apply_theme_css(_cfg)

# ── Arrow-safe wrapper ────────────────────────────────────────────────────────
_st_df_orig = st.dataframe
def _safe_df(data=None, *args, **kwargs):
    if data is not None and not isinstance(data, _PdStyler):
        data = data.copy()
        for _c in data.select_dtypes(include=["object","str"]).columns:
            data[_c] = data[_c].astype(str)
    return _st_df_orig(data, *args, **kwargs)
st.dataframe = _safe_df

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
PLOT_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font_color="#c9d1d9",
    margin=dict(l=10, r=10, t=30, b=10),
)

def _bar_h(df, x_col, y_col, color="#f0a500", title=""):
    fig = go.Figure(go.Bar(
        x=df[x_col], y=df[y_col], orientation="h",
        marker_color=color,
        text=[f"{v:.1f}" if isinstance(v, float) else str(v) for v in df[x_col]],
        textposition="outside",
    ))
    fig.update_layout(**PLOT_LAYOUT, title=title,
                      yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                      xaxis=dict(showgrid=False),
                      height=max(300, len(df) * 40))
    return fig

def _normalize_col(series: pd.Series) -> pd.Series:
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([50.0] * len(series), index=series.index)
    return (series - mn) / (mx - mn) * 100

def _percentile_of(val, series: pd.Series) -> float:
    """What percentile is val within series (0–100)."""
    vals = series.dropna().values
    if len(vals) == 0:
        return 50.0
    return float((vals < val).sum() / len(vals) * 100)

def _pctile_bar_html(label: str, val, pct: float, higher_better: bool = True) -> str:
    """Returns HTML for one percentile bar row."""
    effective_pct = pct if higher_better else (100 - pct)
    color = ("#2ecc71" if effective_pct >= 75
             else "#f0a500" if effective_pct >= 50
             else "#e74c3c")
    val_str = f"{val:.1f}" if isinstance(val, float) else str(val)
    pct_str = f"{effective_pct:.0f}th"
    return f"""
<div class="pctile-row">
  <div class="pctile-label-row">
    <span class="pctile-stat">{label}</span>
    <div style="display:flex;gap:10px;align-items:center">
      <span class="pctile-val">{val_str}</span>
      <span class="pctile-rank" style="color:{color}">{pct_str}</span>
    </div>
  </div>
  <div class="pctile-track">
    <div class="pctile-fill" style="width:{min(100,effective_pct):.1f}%;background:{color}"></div>
  </div>
</div>"""

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
            "eFG%","TS%","+/-","GS","SC","ShotRat","Stocks","Q4 PPG",
            "3PAr","PaintFG%","PaintFGA","PaintFGM","DSh%",
            "FTr","PPS","PPSA","TOV%","USG","EFF","FIC","PRF","AST/TOV",
            "PTS32","REB32","AST32","STL32","BLK32","TOV32","SC32","GP","MIN"]
for c in NUM_COLS:
    if c in rnk.columns:
        rnk[c] = pd.to_numeric(rnk[c], errors="coerce").fillna(0)

if not rat.empty:
    for c in ["OFF","DEF","PLY","REB_R","OVRL","GP"]:
        if c in rat.columns:
            rat[c] = pd.to_numeric(rat[c], errors="coerce").fillna(0)

def _label(row):
    num = f"#{row['#']} " if "#" in row and row["#"] else ""
    return f"{num}{row['Player']} ({row['Team']})"

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

    # ── Sub-tabs ─────────────────────────────────────────────────────────────
    sub1, sub2, sub3, sub4, sub5, sub6, sub_adv, sub_ovrl = st.tabs([
        "Scoring", "Rebounds", "Assists", "Defense", "Shooting", "Advanced", "🔬 Deep Analytics", "👑 Overall"
    ])

    DISPLAY_COLS = ["Player","#","Team","GP","PTS","REB","AST","STL","BLK","FG%","eFG%","TS%"]

    def _leaderboard_tab(parent, col, label, top_n=12, color="#f0a500", display_cols=None):
        with parent:
            if col not in rnk.columns:
                st.info(f"No data for {label}.")
                return
            top = rnk.nlargest(top_n, col)[["_label", col]].copy()
            top["_label"] = top["_label"].astype(str)
            # Color gradient gold→blue by rank
            _clrs = [("#f0a500" if i == 0 else "#58a6ff" if i < 3 else "#30363d")
                     for i in range(len(top))]
            fig = go.Figure(go.Bar(
                x=top[col], y=top["_label"], orientation="h",
                marker_color=list(reversed(_clrs)),
                text=[f"{v:.2f}" if col in ("PPSA","PPS","FTr") else f"{v:.1f}"
                      for v in top[col]],
                textposition="outside",
            ))
            fig.update_layout(**PLOT_LAYOUT, title=f"Top {top_n} — {label}",
                              yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                              xaxis=dict(showgrid=False),
                              height=max(340, top_n * 40))
            st.plotly_chart(fig, width='stretch')
            dcols = display_cols or DISPLAY_COLS
            show_cols = [c for c in dcols if c in rnk.columns]
            st.dataframe(rnk.nlargest(len(rnk), col)[show_cols],
                         width='stretch', hide_index=True)

    _leaderboard_tab(sub1, "PTS", "Points per Game",
                     display_cols=["Player","#","Team","GP","PTS","FGM","FGA","FG%","eFG%","TS%","PPSA","Q4 PPG"])
    _leaderboard_tab(sub2, "REB", "Rebounds per Game",
                     display_cols=["Player","#","Team","GP","REB","OREB","DREB","+/-"])
    _leaderboard_tab(sub3, "AST", "Assists per Game",
                     display_cols=["Player","#","Team","GP","AST","TOV","AST/TOV","SC","PRF"])

    with sub4:
        if "Stocks" in rnk.columns:
            df4 = rnk.copy()
            top4 = df4.nlargest(12, "Stocks")[["_label","STL","BLK","Stocks"]].copy()
            top4["_label"] = top4["_label"].astype(str)
            fig4 = go.Figure()
            fig4.add_trace(go.Bar(x=top4["STL"], y=top4["_label"], orientation="h",
                                  name="STL", marker_color="#58a6ff"))
            fig4.add_trace(go.Bar(x=top4["BLK"], y=top4["_label"], orientation="h",
                                  name="BLK", marker_color="#f0a500"))
            fig4.update_layout(**PLOT_LAYOUT, barmode="stack", title="Top 12 — Stocks (STL+BLK)",
                               yaxis=dict(autorange="reversed"), height=max(340, 12*40))
            st.plotly_chart(fig4, width='stretch')
            dcols4 = ["Player","#","Team","GP","STL","BLK","Stocks","DREB","DSh%","TOV"]
            show4  = [c for c in dcols4 if c in df4.columns]
            st.dataframe(df4.nlargest(len(df4), "Stocks")[show4],
                         width='stretch', hide_index=True)

    with sub5:
        shoot_cols = ["Player","#","Team","GP","FGM","FGA","FG%",
                      "2PM","2PA","2P%","3PM","3PA","3P%",
                      "FTM","FTA","FT%","FTr","eFG%","TS%","PPS","PPSA"]
        show_s = [c for c in shoot_cols if c in rnk.columns]
        rnk_s  = rnk[rnk["FGA"] >= 1].copy() if "FGA" in rnk.columns else rnk.copy()

        # Shot distribution chart for top scorers
        if all(c in rnk_s.columns for c in ["2PA","3PA","FTA"]) and not rnk_s.empty:
            top_sc = rnk_s.nlargest(10, "PTS")
            fig_dist = go.Figure()
            fig_dist.add_trace(go.Bar(
                name="2PT FGA", x=top_sc["_label"], y=top_sc["2PA"],
                marker_color="#f0a500"))
            fig_dist.add_trace(go.Bar(
                name="3PT FGA", x=top_sc["_label"], y=top_sc["3PA"],
                marker_color="#3498db"))
            fig_dist.add_trace(go.Bar(
                name="FTA",     x=top_sc["_label"], y=top_sc["FTA"],
                marker_color="#2ecc71"))
            fig_dist.update_layout(
                **PLOT_LAYOUT, barmode="stack",
                title="Shot Attempt Distribution — Top 10 Scorers",
                xaxis=dict(tickangle=-30, tickfont=dict(size=10)),
                height=380, legend=dict(orientation="h", yanchor="bottom", y=1.02))
            st.plotly_chart(fig_dist, width='stretch')

        if "eFG%" in rnk_s.columns:
            top_s = rnk_s.nlargest(12, "eFG%")[["_label","eFG%"]].copy()
            top_s["_label"] = top_s["_label"].astype(str)
            fig_s = _bar_h(top_s, "eFG%", "_label", color="#2ecc71",
                           title="Top 12 — eFG% (min 1 FGA)")
            st.plotly_chart(fig_s, width='stretch')
        st.dataframe(rnk_s.sort_values("eFG%", ascending=False)[show_s],
                     width='stretch', hide_index=True)

    with sub6:
        adv_cols = ["Player","#","Team","GP","GS","SC","ShotRat","Stocks",
                    "Q4 PPG","3PAr","PaintFG%","AST/TOV","+/-"]
        show_a = [c for c in adv_cols if c in rnk.columns]
        if "GS" in rnk.columns:
            top_a = rnk.nlargest(12, "GS")[["_label","GS"]].copy()
            top_a["_label"] = top_a["_label"].astype(str)
            fig_a = _bar_h(top_a, "GS", "_label", color="#9b59b6",
                           title="Top 12 — Game Score (Hollinger)")
            st.plotly_chart(fig_a, width='stretch')
        st.dataframe(rnk.sort_values("GS", ascending=False)[show_a] if "GS" in rnk.columns
                     else rnk[show_a], width='stretch', hide_index=True)

    # ── Deep Analytics tab ───────────────────────────────────────────────────
    with sub_adv:
        st.markdown('<div class="section-hdr">🔬 Deep Analytics Leaderboards</div>',
                    unsafe_allow_html=True)

        adv_metrics = [
            ("EFF",   "NBA Efficiency (PTS+REB+AST+STL+BLK−missed FG−missed FT−TOV)",   "#f0a500"),
            ("FIC",   "Floor Impact Counter (weighted composite)",                          "#9b59b6"),
            ("PRF",   "Points Responsible For (PTS + AST×2)",                             "#3498db"),
            ("PPSA",  "Points Per Scoring Attempt (PTS÷(FGA+0.44×FTA))",                  "#2ecc71"),
            ("PPS",   "Points Per Shot (PTS÷FGA)",                                        "#e67e22"),
            ("FTr",   "Free Throw Rate (FTA÷FGA) — how often you draw fouls",             "#e74c3c"),
            ("TOV%",  "Turnover Rate % (TOV÷(FGA+0.44×FTA+TOV)×100)",                    "#8b949e"),
            ("USG",   "Usage Volume per Game (FGA+0.44×FTA+TOV) — ball in hands",        "#58a6ff"),
        ]

        desc_html = "".join(
            f'<div style="display:inline-block;background:#161b22;border:1px solid #30363d;'
            f'border-radius:8px;padding:8px 14px;margin:4px;font-size:11px;color:{clr}">'
            f'<b>{m}</b> <span style="color:#8b949e">— {desc}</span></div>'
            for m, desc, clr in adv_metrics
        )
        st.markdown(desc_html, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        _adv_sel = st.selectbox("Select metric to rank",
                                [m for m, _, _ in adv_metrics],
                                key="adv_metric_sel")
        _adv_color = next((c for m, _, c in adv_metrics if m == _adv_sel), "#f0a500")

        if _adv_sel in rnk.columns:
            _adv_top = rnk.nlargest(15, _adv_sel)[["_label", _adv_sel]].copy()
            _adv_top["_label"] = _adv_top["_label"].astype(str)
            _adv_clrs = [("#f0a500" if i == 0 else "#58a6ff" if i < 3 else "#30363d")
                         for i in range(len(_adv_top))]
            _adv_fig = go.Figure(go.Bar(
                x=_adv_top[_adv_sel], y=_adv_top["_label"], orientation="h",
                marker_color=list(reversed(_adv_clrs)),
                text=[f"{v:.2f}" if _adv_sel in ("PPSA","PPS","FTr") else f"{v:.1f}"
                      for v in _adv_top[_adv_sel]],
                textposition="outside",
            ))
            _adv_fig.update_layout(
                **PLOT_LAYOUT, title=f"Top 15 — {_adv_sel}",
                yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                xaxis=dict(showgrid=False),
                height=max(380, 15 * 40))
            st.plotly_chart(_adv_fig, width='stretch')

        # Full advanced stats table
        _full_adv = ["Player","#","Team","GP","EFF","FIC","PRF","PPSA","PPS",
                     "FTr","TOV%","USG","GS","SC","ShotRat","AST/TOV"]
        _full_adv_show = [c for c in _full_adv if c in rnk.columns]
        st.dataframe(rnk.sort_values("EFF", ascending=False)[_full_adv_show] if "EFF" in rnk.columns
                     else rnk[_full_adv_show], width='stretch', hide_index=True)

        # EFF vs PRF scatter (size = Stocks)
        if all(c in rnk.columns for c in ["EFF","PRF"]):
            st.markdown("---")
            st.markdown("**Efficiency vs. Impact (EFF vs PRF)**")
            _sc_df = rnk[rnk["GP"] >= 1].copy()
            _sc_df["_sz"] = (_sc_df["Stocks"] + 0.5) * 8 if "Stocks" in _sc_df.columns else 15
            fig_ev = px.scatter(
                _sc_df, x="EFF", y="PRF",
                size="_sz", color="Team", hover_name="Player",
                hover_data={"EFF":":.1f","PRF":":.1f","PTS":":.1f","AST":":.1f","_sz":False},
                size_max=35,
                color_discrete_sequence=px.colors.qualitative.Plotly,
                labels={"EFF":"Efficiency (EFF)","PRF":"Points Responsible For (PRF)"},
            )
            fig_ev.update_layout(**PLOT_LAYOUT, height=440)
            st.plotly_chart(fig_ev, width='stretch', key="adv_scatter")
            st.caption("Bubble size = Stocks (STL+BLK). Top-right = high efficiency AND high impact.")

    # ── Overall tab ──────────────────────────────────────────────────────────
    with sub_ovrl:
        if rat.empty or "OVRL" not in rat.columns:
            st.info("No players with tracked games found.")
        else:
            _ov = rat.copy()
            _ov["_label"] = _ov.apply(_label, axis=1).astype(str)
            top_ov = _ov.nlargest(min(15, len(_ov)), "OVRL")

            _colors = ["#f0a500" if i == 0 else "#58a6ff" if i < 3 else "#30363d"
                       for i in range(len(top_ov))]
            fig_ov = go.Figure(go.Bar(
                x=top_ov["OVRL"], y=top_ov["_label"], orientation="h",
                marker_color=list(reversed(_colors)),
                text=[f"{v:.1f}" for v in top_ov["OVRL"]],
                textposition="outside",
            ))
            fig_ov.update_layout(
                **PLOT_LAYOUT, title="Overall Rating (OVRL) — Top Players",
                xaxis=dict(range=[0, 108], showgrid=False),
                yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                height=max(360, len(top_ov) * 42),
            )
            st.plotly_chart(fig_ov, width='stretch', key="ovrl_leaderboard")

            # Component breakdown for top players
            if all(c in _ov.columns for c in ["OFF","DEF","PLY","REB_R"]):
                st.markdown("**Rating Component Breakdown — Top 10**")
                _top10 = _ov.nlargest(10, "OVRL")
                fig_comp = go.Figure()
                comps = [("OFF","⚡ Offense","#f0a500"),("DEF","🛡 Defense","#3498db"),
                         ("PLY","🎯 Playmaking","#2ecc71"),("REB_R","📦 Rebounding","#e67e22")]
                for col, name, clr in comps:
                    fig_comp.add_trace(go.Bar(
                        name=name, x=_top10["Player"], y=_top10[col],
                        marker_color=clr))
                fig_comp.update_layout(
                    **PLOT_LAYOUT, barmode="group",
                    xaxis=dict(tickangle=-30, tickfont=dict(size=10)),
                    yaxis=dict(range=[0,105], title="Score (0–100)"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    height=400)
                st.plotly_chart(fig_comp, width='stretch', key="ovrl_comp")

            # Full table
            _ov_cols = ["Player","#","Team","GP","OVRL","OFF","DEF","PLY","REB_R",
                        "PTS","AST","REB","STL","BLK","TOV","TS%"]
            _show_ov = [c for c in _ov_cols if c in _ov.columns]
            st.dataframe(_ov.nlargest(len(_ov), "OVRL")[_show_ov],
                         width='stretch', hide_index=True)
            st.caption("OVRL weights: OFF 30% · PLY 25% · DEF 25% · REB_R 20%. Min 1 GP.")


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
            sub_ovrl_r, sub_off, sub_def, sub_ply, sub_reb = st.tabs([
                "👑 Overall (OVRL)", "⚡ Offense (OFF)", "🛡️ Defense (DEF)",
                "🎯 Playmaking (PLY)", "📦 Rebounding (REB_R)"
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
                    dcols = ["Player","#","Team","GP","PTS","AST","REB","STL","BLK","eFG%","TS%",col]
                    show_c = [c for c in dcols if c in sorted_r.columns]
                    st.dataframe(sorted_r[show_c], width='stretch', hide_index=True)

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
                        st.plotly_chart(fig_sc, width='stretch', key=f"scatter_rating_{col}")

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
                    _ov_r_cols = ["Player","#","Team","GP","OVRL","OFF","DEF","PLY","REB_R",
                                  "PTS","AST","REB","STL","BLK","TOV","TS%"]
                    _ov_r_show = [c for c in _ov_r_cols if c in _ov_r.columns]
                    st.dataframe(_ov_r[_ov_r_show], width='stretch', hide_index=True)

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
                        st.plotly_chart(fig_ov_sc, width='stretch', key="scatter_ovrl_off")

                    st.caption("OVRL = OFF 30% + PLY 25% + DEF 25% + REB_R 20%, normalised 0–100.")

            _rating_tab(sub_off, "OFF",   "Offensive Rating",   "#f0a500")
            _rating_tab(sub_def, "DEF",   "Defensive Rating",   "#3498db")
            _rating_tab(sub_ply, "PLY",   "Playmaking Rating",  "#2ecc71")
            _rating_tab(sub_reb, "REB_R", "Rebounding Rating",  "#e67e22")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 – BEST FIVE
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    def _build_best_five(df_rat, df_rnk):
        if df_rat.empty:
            return []
        needed = ["OFF","DEF","PLY","REB_R","Player","Team"]
        if not all(c in df_rat.columns for c in needed):
            return []
        pool = df_rat.copy()
        used = set()

        def _pick(metric):
            src = pool[~pool.index.isin(used)]
            if src.empty: return None
            row = src.nlargest(1, metric).iloc[0]
            used.add(row.name)
            return row

        roles = [
            ("OFF",   "#1 Primary Scorer",  "Highest OFF"),
            ("PLY",   "#2 Playmaker",       "Highest PLY"),
            ("DEF",   "#3 Defender",        "Highest DEF"),
            ("REB_R", "#4 Rebounder",       "Highest REB_R"),
        ]
        five = []
        for metric, role, desc in roles:
            row = _pick(metric)
            if row is not None:
                five.append({"role":role,"desc":desc,"metric":metric,"row":row})

        if "OVRL" in pool.columns:
            pool["_avg"] = pool["OVRL"]; wc_desc = "Highest OVRL"
        else:
            pool["_avg"] = (pool["OFF"]+pool["DEF"]+pool["PLY"]+pool["REB_R"])/4
            wc_desc = "Best avg OFF+DEF+PLY+REB_R"
        wc = _pick("_avg")
        if wc is not None:
            five.append({"role":"#5 X-Factor","desc":wc_desc,"metric":"_avg","row":wc})
        return five

    def _render_five(five, df_rnk):
        if not five:
            st.info("Not enough rating data to build a Best Five.")
            return
        cols_5 = st.columns(len(five))
        for i, entry in enumerate(five):
            row   = entry["row"]
            pid   = row.get("pid", None)
            pts_val = reb_val = ast_val = "—"
            if pid is not None and not df_rnk.empty and "pid" in df_rnk.columns:
                pr = df_rnk[df_rnk["pid"] == pid]
                if not pr.empty:
                    pts_val = f"{pr.iloc[0].get('PTS',0):.1f}"
                    reb_val = f"{pr.iloc[0].get('REB',0):.1f}"
                    ast_val = f"{pr.iloc[0].get('AST',0):.1f}"
            mv  = row.get(entry["metric"], 0)
            mlb = entry["metric"] if entry["metric"] != "_avg" else "OVRL"
            with cols_5[i]:
                st.markdown(f"""
                <div class="best5-card">
                    <div class="best5-role">{entry['role']}</div>
                    <div class="best5-name">{row['Player']}</div>
                    <div class="best5-team">{row.get('Team','')} · {row.get('Class','')}</div>
                    <div class="best5-stat">{mv:.1f}</div>
                    <div class="best5-stat-lbl">{mlb}</div>
                    <div style="margin-top:10px;font-size:11px;color:#8b949e">
                        {pts_val} PTS · {reb_val} REB · {ast_val} AST
                    </div>
                </div>
                """, unsafe_allow_html=True)

    st.markdown('<div class="section-hdr">🌟 League Best Five</div>', unsafe_allow_html=True)
    _render_five(_build_best_five(rat, rnk), rnk)
    st.markdown("---")
    st.markdown('<div class="section-hdr">🏀 Best Five by Team</div>', unsafe_allow_html=True)
    teams_list = sorted(rnk["Team"].dropna().unique().tolist()) if "Team" in rnk.columns else []
    if teams_list:
        sel_team = st.selectbox("Select Team", teams_list, key="best5_team")
        if not rat.empty and "Team" in rat.columns:
            _render_five(_build_best_five(rat[rat["Team"]==sel_team].copy(),
                                          rnk[rnk["Team"]==sel_team].copy()), rnk)


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
        st.plotly_chart(fig_radar, width='stretch')

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
                            showlegend=False, height=300, margin=dict(l=5,r=5,t=40,b=5))
                        st.plotly_chart(fig_d, width='stretch',
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
        st.dataframe(out_df, width='stretch', hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 – PLAYER PROFILES
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    if rnk.empty:
        st.info("No player data available.")
    else:
        player_opts = rnk["_label"].tolist()
        sel_prof    = st.selectbox("Select Player", player_opts, key="prof_sel")
        prof_row    = rnk[rnk["_label"] == sel_prof].iloc[0]
        pid         = prof_row.get("pid", None)

        # ── Bio hero card ─────────────────────────────────────────────────────
        _gp_val  = int(prof_row.get("GP",0))
        _min_val = float(prof_row.get("MIN",0))
        _pm_val  = float(prof_row.get("+/-",0))
        _gs_val  = float(prof_row.get("GS",0))

        st.markdown(f"""
        <div class="pl-hero">
            <div class="pl-name">{prof_row['Player']}</div>
            <div class="pl-meta">
                #{prof_row.get('#','')} &nbsp;·&nbsp;
                {prof_row.get('Team','')} &nbsp;·&nbsp;
                {prof_row.get('Class','')} &nbsp;·&nbsp;
                {prof_row.get('Gender','')}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Bio (height / wingspan / weight)
        bio = None
        if pid is not None:
            bio_rows = query("SELECT height, wingspan, weight FROM players WHERE id=?", (int(pid),))
            bio = bio_rows[0] if bio_rows else None

        if bio:
            b1, b2, b3 = st.columns(3)
            b1.metric("Height",   bio.get("height","—")   or "—")
            b2.metric("Wingspan", bio.get("wingspan","—") or "—")
            b3.metric("Weight",   bio.get("weight","—")   or "—")

        # ── Quick stat strip ──────────────────────────────────────────────────
        _qs = {
            "PTS": f"{prof_row.get('PTS',0):.1f}",
            "REB": f"{prof_row.get('REB',0):.1f}",
            "AST": f"{prof_row.get('AST',0):.1f}",
            "STL": f"{prof_row.get('STL',0):.1f}",
            "BLK": f"{prof_row.get('BLK',0):.1f}",
            "TOV": f"{prof_row.get('TOV',0):.1f}",
            "EFF": f"{prof_row.get('EFF',0):.1f}",
            "+/-": f"{_pm_val:+.1f}",
            "MIN": f"{_min_val:.1f}",
            "GP":  str(_gp_val),
        }
        st.markdown(_stat_grid_html(_qs), unsafe_allow_html=True)

        st.markdown("---")

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
                         width='stretch', hide_index=True)

            # Shooting breakdown
            st.markdown('<div class="section-hdr">Shooting Breakdown</div>',
                        unsafe_allow_html=True)
            shoot_cols_p = ["FGM","FGA","FG%","2PM","2PA","2P%",
                            "3PM","3PA","3P%","FTM","FTA","FT%","eFG%","TS%",
                            "PaintFG%","PaintFGA","PaintFGM","3PAr","FTr","PPS","PPSA","ShotRat"]
            shoot_avail = [c for c in shoot_cols_p if c in prof_row.index]
            if shoot_avail:
                st.dataframe(pd.DataFrame([{c: prof_row[c] for c in shoot_avail}]),
                             width='stretch', hide_index=True)

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
                        showlegend=False, height=280, margin=dict(l=5,r=5,t=40,b=5))
                    st.plotly_chart(fig_donut, width='stretch', key=f"prof_donut_{pid}")

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
                    st.plotly_chart(fig_sh, width='stretch', key=f"prof_shoot_{pid}")

        # ── Advanced ──────────────────────────────────────────────────────────
        with p_tab_adv:
            st.markdown('<div class="section-hdr">Advanced Metrics</div>',
                        unsafe_allow_html=True)
            adv_stat_cols = ["EFF","FIC","PRF","PPSA","PPS","FTr","TOV%",
                             "USG","GS","SC","ShotRat","AST/TOV","DSh%","Q4 PPG"]
            adv_avail = [c for c in adv_stat_cols if c in prof_row.index]
            if adv_avail:
                st.dataframe(pd.DataFrame([{c: prof_row[c] for c in adv_avail}]),
                             width='stretch', hide_index=True)

            # Percentile bars for advanced stats
            st.markdown('<div class="section-hdr">League Percentiles — Advanced</div>',
                        unsafe_allow_html=True)
            adv_pctile_stats = [
                ("EFF",  "NBA Efficiency",       True),
                ("FIC",  "Floor Impact Ctr",     True),
                ("PRF",  "Pts Responsible For",  True),
                ("PPSA", "Pts/Scoring Att",       True),
                ("PPS",  "Pts Per Shot",           True),
                ("FTr",  "Free Throw Rate",        True),
                ("TOV%", "Turnover Rate",          False),
                ("USG",  "Usage Volume",           True),
                ("SC",   "Shots Created",          True),
                ("Q4 PPG","Q4 Scoring",           True),
                ("AST/TOV","AST/TOV Ratio",        True),
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
                st.plotly_chart(fig_adv_r, width='stretch', key=f"prof_adv_radar_{pid}")

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
                                 width='stretch', hide_index=True)
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
                        st.plotly_chart(fig_p36, width='stretch', key=f"prof_p36_{pid}")
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
                        st.plotly_chart(fig_rat, width='stretch', key=f"prof_rat_{pid}")

                        # Ratings table with descriptions
                        r_labels = {"OVRL":"Overall Rating","OFF":"Offensive Rating",
                                    "DEF":"Defensive Rating","PLY":"Playmaking Rating",
                                    "REB_R":"Rebounding Rating"}
                        r_rows = [{"Rating":r_labels.get(c,c),"Code":c,
                                   "Score":f"{float(pr[c]):.1f}"}
                                  for c in rating_cols]
                        st.dataframe(pd.DataFrame(r_rows), width='stretch', hide_index=True)

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
                                     width='stretch', hide_index=True)

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
                    st.plotly_chart(fig_rank, width='stretch',
                                    key=f"prof_ovrl_rank_{pid}")

        # ── Game Log ──────────────────────────────────────────────────────────
        with p_tab_log:
            if pid is not None:
                # Try to get full game log stats via compute_player_game_log
                _profile_team_id = None
                if "Team" in prof_row.index:
                    _team_res = query("SELECT id FROM teams WHERE name=?",
                                      (str(prof_row.get("Team","")),))
                    if _team_res:
                        _profile_team_id = _team_res[0]["id"]

                if _profile_team_id is not None:
                    from helpers.stats_team import compute_player_game_log
                    game_log_data = compute_player_game_log(int(pid), int(_profile_team_id))
                else:
                    game_log_data = []

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
                        _trend_df["_game_num"] = range(1, len(_trend_df)+1)
                        fig_trend = go.Figure()
                        _tcols = ["#f0a500","#3498db","#2ecc71","#e74c3c"]
                        for ti, ts in enumerate(_trend_sel):
                            if ts not in _trend_df.columns: continue
                            _y = pd.to_numeric(_trend_df[ts], errors="coerce").fillna(0)
                            fig_trend.add_trace(go.Scatter(
                                x=_trend_df["_game_num"], y=_y,
                                mode="lines+markers", name=ts,
                                line=dict(color=_tcols[ti % len(_tcols)], width=2),
                                marker=dict(size=7),
                                hovertemplate=f"<b>Game %{{x}}</b><br>{ts}: %{{y}}<extra></extra>",
                            ))
                        # Rolling average overlay
                        if "PTS" in _trend_sel and "PTS" in _trend_df.columns:
                            _roll = pd.to_numeric(_trend_df["PTS"], errors="coerce").rolling(3, min_periods=1).mean()
                            fig_trend.add_trace(go.Scatter(
                                x=_trend_df["_game_num"], y=_roll,
                                mode="lines", name="PTS 3-game avg",
                                line=dict(color="#f0a500", width=1, dash="dot"),
                                opacity=0.6,
                            ))
                        fig_trend.update_layout(
                            **PLOT_LAYOUT, title="Game-by-Game Performance",
                            xaxis=dict(title="Game #", dtick=1, showgrid=False),
                            yaxis=dict(title="Value", showgrid=True, gridcolor="#21262d"),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02),
                            height=360,
                        )
                        st.plotly_chart(fig_trend, width='stretch',
                                        key=f"prof_trend_{pid}")

                    # W/L coloring in log
                    show_log_cols = [c for c in
                        ["Date","Opp","W/L","Score","PTS","AST","REB","STL","BLK",
                         "TOV","FGM","FGA","FG%","3PM","3PA","3P%","FTM","FTA","FT%",
                         "SC","+/-","MIN","GS"]
                        if c in gl_df.columns]
                    st.markdown('<div class="section-hdr">Game Log</div>',
                                unsafe_allow_html=True)
                    st.dataframe(gl_df[show_log_cols], width='stretch', hide_index=True)
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
                                     width='stretch', hide_index=True)
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
