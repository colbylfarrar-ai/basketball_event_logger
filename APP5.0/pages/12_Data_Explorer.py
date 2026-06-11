"""
12_Data_Explorer.py — a self-serve analytics playground over every stat the app
computes. Built for the data-hungry: filter the full ~60-column player table,
plot any stat against any other (with an OLS trendline), see the league mapped
into 2D style-space (PCA) coloured by learned archetype, and read a correlation
matrix across whatever stats you pick.

Nothing here is dumbed down — it surfaces the raw richness and lets the user
decide what's meaningful. New, isolated page: it can't slow or break the existing
ones. Charts are Plotly (consistent dark theme); the grid uses streamlit-aggrid
when available and falls back to a native dataframe otherwise.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from helpers.ui import (page_chrome, gender_radio, style_fig as _style,
                        empty_state, grid as _grid, chart as _chart)
import helpers.player_ratings as PR
import helpers.archetypes as AR
import helpers.stats as S
import helpers.court as court

_cfg, ACCENT = page_chrome()

st.title("Data Explorer")
st.caption("Every stat, your way — filter the full table, build any scatter, map "
           "the league's playing styles, and correlate anything. Raw and dense by "
           "design; trust your own read on what matters.")

# ── cached engine wrappers (compute once per gender/min-games, reuse on rerun) ──
@st.cache_data(ttl=600, show_spinner=False)
def _table(g, mg):
    return PR.player_stat_table(gender=g, min_games=mg)

@st.cache_data(ttl=600, show_spinner=False)
def _clusters(g, mg):
    return AR.cluster_players(_table(g, mg))["players"]

@st.cache_data(ttl=600, show_spinner=False)
def _stylemap(g, mg):
    return AR.style_map(_table(g, mg))

@st.cache_data(ttl=600, show_spinner=False)
def _mapped(approx, team_id=None, player_id=None):
    return S.mapped_shots(include_approx=approx, team_id=team_id, player_id=player_id)

@st.cache_data(ttl=600, show_spinner=False)
def _shot_model(approx):
    return S.distance_make_model(shots=_mapped(approx))


# ── scope ────────────────────────────────────────────────────────────────────
sc = st.columns([1, 2, 3])
gender = gender_radio(sc[0], key="dx_gender")
min_g = sc[1].slider("Min games", 1, 15, 1, key="dx_ming",
                     help="Drop thin samples from the pool.")
table = _table(gender, min_g)
if not table:
    empty_state("No players in this pool", "Lower the minimum games, or track "
                "more games in the Game Tracker.", icon="📊")
    st.stop()

# attach archetype label, build the master frame
_arche = _clusters(gender, min_g)
df = pd.DataFrame([{**r, "Archetype": _arche.get(pid, {}).get("archetype", "—")}
                   for pid, r in table.items()])

_EXCLUDE = {"team_id", "number"}
num_cols = [c for c in df.columns
            if pd.api.types.is_numeric_dtype(df[c]) and c not in _EXCLUDE]
cat_cols = [c for c in ("Archetype", "team", "class", "Confidence") if c in df.columns]


def _ix(col, default):
    return num_cols.index(col) if col in num_cols else default


t_grid, t_scatter, t_map, t_corr, t_shots = st.tabs(
    ["📋 Stat grid", "✦ Scatter explorer", "🗺 Style map", "▦ Correlations",
     "🏀 Shot maps"])

# ── tab 1: filterable stat grid ────────────────────────────────────────────────
with t_grid:
    default_cols = [c for c in (
        "name", "team", "class", "GP", "Confidence", "OVERALL", "OFFENSE",
        "DEFENSE", "PLAYMAKING", "REBOUNDING", "Archetype", "PPG", "RPG", "APG",
        "SPG", "BPG", "TS%", "eFG%", "3P%", "USG%", "ShotRating", "xPPS", "SMOE",
    ) if c in df.columns]
    cols = st.multiselect("Columns to show", list(df.columns), default=default_cols,
                          key="dx_cols")
    gdf = df[cols] if cols else df
    st.caption(f"{len(gdf)} players · {len(gdf.columns)} columns. "
               "Click a column header to sort; AgGrid adds per-column filters.")
    _grid(gdf, "dx_grid")
    st.download_button("⬇ Download CSV", gdf.to_csv(index=False),
                       file_name=f"players_{gender}.csv", mime="text/csv",
                       key="dx_csv")

# ── tab 2: scatter explorer ────────────────────────────────────────────────────
with t_scatter:
    cc = st.columns(4)
    x = cc[0].selectbox("X axis", num_cols, index=_ix("USG%", 0), key="dx_x")
    y = cc[1].selectbox("Y axis", num_cols, index=_ix("TS%", min(1, len(num_cols) - 1)),
                        key="dx_y")
    size = cc[2].selectbox("Size", ["(none)"] + num_cols, key="dx_size")
    color = cc[3].selectbox("Color", ["(none)"] + cat_cols + num_cols, key="dx_color")
    trend = st.checkbox("OLS trendline", value=True, key="dx_trend")

    keep = [c for c in {x, y, "name", "team",
                        *( [size] if size != "(none)" else []),
                        *( [color] if color != "(none)" else [])} if c in df.columns]
    sub = df[keep].dropna(subset=[x, y]).copy()
    if size != "(none)":
        sub = sub[sub[size].notna()]
        sub[size] = sub[size].clip(lower=0)   # px sizes must be non-negative

    kw = dict(x=x, y=y, hover_name="name" if "name" in sub else None)
    if size != "(none)":
        kw["size"] = size
    if color != "(none)":
        kw["color"] = color
    if trend:
        kw["trendline"] = "ols"
        kw["trendline_scope"] = "overall"
        kw["trendline_color_override"] = "#8b949e"
    try:
        fig = px.scatter(sub, **kw)
    except Exception:
        kw.pop("size", None)
        fig = px.scatter(sub, **kw)
    fig.update_traces(marker=dict(line=dict(width=0)),
                      selector=dict(mode="markers"))
    _style(fig, 540)
    _chart(fig, data=sub, key="dx_scatter")
    if len(sub) >= 3:
        r = sub[x].corr(sub[y])
        st.caption(f"Pearson r = **{r:+.2f}** across {len(sub)} players "
                   f"(r² = {r * r:.2f}). Correlation, not causation.")

# ── tab 3: PCA style map ───────────────────────────────────────────────────────
with t_map:
    sm = _stylemap(gender, min_g)
    pts = sm.get("points", {})
    if not pts:
        st.info("Style map needs scikit-learn and at least 3 players.")
    else:
        mdf = pd.DataFrame(list(pts.values()))
        mdf["overall"] = mdf["overall"].fillna(50)
        evr = sm.get("evr") or [0, 0]
        fig = px.scatter(mdf, x="x", y="y", color="archetype", size="overall",
                         hover_name="name", hover_data={"team": True, "x": False,
                                                         "y": False, "overall": True})
        fig.update_layout(
            xaxis_title=f"Style PC1 · {evr[0] * 100:.0f}% of variance",
            yaxis_title=f"Style PC2 · {evr[1] * 100:.0f}% of variance")
        fig.update_traces(marker=dict(line=dict(width=0.5, color="#0d1117")))
        _style(fig, 560)
        _chart(fig, data=mdf, key="dx_map")
        st.caption("Each dot is a player placed by *how* they play (16 style "
                   "features, reduced to 2 axes via PCA). Neighbours play alike; "
                   "colour = the archetype k-means grouped them into; size = OVERALL.")

# ── tab 4: correlation heatmap ─────────────────────────────────────────────────
with t_corr:
    default_stats = [c for c in (
        "PPG", "USG%", "TS%", "eFG%", "3P%", "AST/TOV", "RPG", "SPG", "BPG",
        "ShotRating", "xPPS", "SMOE", "OVERALL",
    ) if c in num_cols]
    pick = st.multiselect("Stats to correlate", num_cols, default=default_stats,
                          key="dx_corrpick")
    if len(pick) < 2:
        st.info("Pick at least two stats.")
    else:
        corr = df[pick].corr()
        fig = px.imshow(corr, text_auto=".2f", color_continuous_scale="RdBu_r",
                        zmin=-1, zmax=1, aspect="auto")
        fig.update_layout(height=max(360, 34 * len(pick)),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        _chart(fig, data=corr.reset_index(), key="dx_corr")
        st.caption("Pearson correlation across the player pool. Deep red = strong "
                   "positive, deep blue = strong negative. Use it to spot which "
                   "stats move together (and which are redundant).")

# ── tab 5: shot maps (hexbin / expected points / scatter) ─────────────────────
with t_shots:
    st.caption("Shot locations from the court tap (x, y). Legacy zone-only shots "
               "sit at their zone centroid (approx) so the maps work today — they "
               "sharpen as you track games with the new tap capture.")
    cc = st.columns([1.1, 2.2, 2.2, 1.4])
    scope = cc[0].radio("Scope", ["League", "Team", "Player"], key="sm_scope")

    teams = {}
    for _pid, r in table.items():
        if r.get("team_id") is not None:
            teams.setdefault(r["team_id"], r.get("team", str(r["team_id"])))
    team_items = sorted(teams.items(), key=lambda kv: kv[1])

    kw = {}
    if scope == "Team" and team_items:
        tsel = cc[1].selectbox("Team", team_items, format_func=lambda kv: kv[1],
                               key="sm_team")
        kw["team_id"] = tsel[0]
    elif scope == "Player":
        pl_items = sorted(table.items(), key=lambda kv: -(kv[1].get("OVERALL") or 0))
        psel = cc[1].selectbox(
            "Player", pl_items, key="sm_player",
            format_func=lambda kv: f"{kv[1]['name']} · {kv[1].get('team', '')}")
        kw["player_id"] = psel[0]
    ctype = cc[2].radio("Chart", ["Hexbin (volume + PPS)",
                                  "Expected points surface", "Scatter"],
                        key="sm_ctype")
    approx = cc[3].checkbox("Zone-approx", value=True, key="sm_approx",
                            help="Include legacy zone-only shots at their centroid.")

    shots = _mapped(approx, **kw)
    if not shots:
        empty_state("No shots in this view",
                    "Track a game with the court tap, or keep zone-approx on.",
                    icon="🏀")
    else:
        n_real = sum(1 for s in shots if not s["approx"])
        st.caption(f"**{len(shots)}** shots · {n_real} located, "
                   f"{len(shots) - n_real} zone-approx.")
        league = _mapped(approx)                              # pooled color/model
        lpps = (sum(s["value"] for s in league if s["make"]) / len(league)
                if league else 1.0)
        if ctype.startswith("Hexbin"):
            fig, _n = court.shot_hexbin(shots, title="Volume + points-per-shot",
                                        league_pps=lpps)
            st.plotly_chart(fig, width="stretch", key="sm_hex")
            st.caption("Hexagon size = shots from that spot; colour = points per "
                       f"shot (green above league {lpps:.2f}, red below).")
        elif ctype.startswith("Expected"):
            model = _shot_model(approx)
            fig = court.expected_points_surface(model, shots=shots, overlay=True,
                                                title="Expected points per shot")
            st.plotly_chart(fig, width="stretch", key="sm_xpts")
            st.caption("Colour = expected points from that spot (league make-rate by "
                       "distance × the 2/3 value). The step at the arc is the 3-pt "
                       "bump. Dots = the shots in this view.")
        else:
            fig, _n = court.shot_map(shots, title="Shot map")
            st.plotly_chart(fig, width="stretch", key="sm_scatter")

        _ls = S.shot_location_summary(shots)
        if _ls:
            st.caption(f"Avg distance **{_ls['avg_dist']:.1f} ft** · FG "
                       f"{_ls['fg'] * 100:.0f}% · rim {_ls['rim_n']} · "
                       f"mid {_ls['mid_n']} · three {_ls['three_n']}")
