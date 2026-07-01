"""
analyze.py (dashboard) — the self-serve analytics playground, as a render() so it
can live inside the War Room ("Analyze" tab) while the same code powers the
standalone page. Filter the full ~60-column player table, plot any stat vs any
other (OLS trendline), correlate anything, and map shots.

Folded out of the old Data Explorer page. The PCA "style galaxy" was dropped on
purpose — it duplicated the Players page's data-driven archetypes; the k-means
Archetype label still rides along as a grid/scatter column.

Tier gate: a WHOLE-LEAGUE (multi-team) pool, so tracked depth is a cross-team
aggregate → Coaches' Co-op (league-wide), not just Paid. Box columns stay public;
a league-wide viewer's depth is read-filtered to the games they may aggregate.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from helpers.ui import (gender_radio, style_fig as _style, empty_state,
                        grid as _grid, chart as _chart, DIVERGE)
import helpers.player_ratings as PR
import helpers.archetypes as AR
import helpers.stats as S
import helpers.court as court
import helpers.auth as AUTH
import helpers.entitlement as ENT


@st.cache_data(ttl=600, show_spinner=False)
def _table(g, mg, gids=None):
    return PR.player_stat_table(game_ids=(set(gids) if gids else None),
                                gender=g, min_games=mg)


@st.cache_data(ttl=600, show_spinner=False)
def _clusters(g, mg, vis=None):
    return AR.cluster_players(_table(g, mg, vis))["players"]


@st.cache_data(ttl=600, show_spinner=False)
def _mapped(approx, team_id=None, player_id=None, vis=None):
    return S.mapped_shots(include_approx=approx, team_id=team_id,
                          player_id=player_id,
                          game_ids=(set(vis) if vis else None))


@st.cache_data(ttl=600, show_spinner=False)
def _shot_model(approx, vis=None):
    return S.distance_make_model(shots=_mapped(approx, vis=vis))


def render():
    """Draw the analytics playground (gender/min-games scope + 4 tabs)."""
    st.caption("⚙️ Power-user tool — unfiltered access to every stat, nothing "
               "dumbed down. Filter the table, build any scatter, correlate "
               "anything, and map shots.")

    # ── scope ──────────────────────────────────────────────────────────────
    sc = st.columns([1, 2, 3])
    gender = gender_radio(sc[0], key="dx_gender")
    min_g = sc[1].slider("Min games", 1, 15, 1, key="dx_ming",
                         help="Drop thin samples from the pool.")
    table = _table(gender, min_g)
    if not table:
        empty_state("No players in this pool", "Lower the minimum games, or track "
                    "more games in the Game Tracker.", icon="📊")
        return

    _ident = AUTH.current_user()
    _paid = ENT.has_paid_plan(_ident) and ENT.viewer_is_league_wide(_ident)
    _vis = None
    if _paid:
        _vis = ENT.visible_tracked_game_ids(_ident)   # None = admin (unrestricted)
        if _vis is not None:
            table = _table(gender, min_g, tuple(sorted(_vis))) or {}
        if not table:                                  # league-wide but nothing pooled
            _paid = False
    if not _paid:
        table = PR.box_only_table(_table(gender, min_g))
        st.caption("🔒 Box-score stats only here. The whole-league tracked table "
                   "(ratings, usage, shot quality, archetypes, shot maps) is a "
                   "**Coaches' Co-op** feature — your own team's tracked depth is "
                   "on its Team Dashboard.")

    _vis_key = (None if (_paid and _vis is None)
                else tuple(sorted(_vis)) if (_paid and _vis)
                else ())

    if _paid:
        _arche = _clusters(gender, min_g, _vis_key)
        df = pd.DataFrame([{**r, "Archetype": _arche.get(pid, {}).get("archetype", "—")}
                           for pid, r in table.items()])
    else:
        df = pd.DataFrame([dict(r) for r in table.values()])

    _EXCLUDE = {"team_id", "number"}
    num_cols = [c for c in df.columns
                if pd.api.types.is_numeric_dtype(df[c]) and c not in _EXCLUDE]
    cat_cols = [c for c in ("Archetype", "team", "class", "Confidence")
                if c in df.columns]

    def _ix(col, default):
        return num_cols.index(col) if col in num_cols else default

    t_grid, t_scatter, t_corr, t_shots = st.tabs(
        ["📋 Stat grid", "✦ Scatter explorer", "▦ Correlations", "🏀 Shot maps"])

    # ── tab 1: filterable stat grid ─────────────────────────────────────────
    with t_grid:
        default_cols = [c for c in (
            "name", "team", "class", "GP", "Confidence", "OVERALL", "OFFENSE",
            "DEFENSE", "PLAYMAKING", "REBOUNDING", "Archetype", "PPG", "RPG",
            "APG", "SPG", "BPG", "TS%", "eFG%", "3P%", "USG%", "ShotRating",
            "xPPS", "SMOE") if c in df.columns]
        cols = st.multiselect("Columns to show", list(df.columns),
                              default=default_cols, key="dx_cols")
        gdf = df[cols] if cols else df
        st.caption(f"{len(gdf)} players · {len(gdf.columns)} columns. "
                   "Click a column header to sort; AgGrid adds per-column filters.")
        _grid(gdf, "dx_grid")
        st.download_button("⬇ Download CSV", gdf.to_csv(index=False),
                           file_name=f"players_{gender}.csv", mime="text/csv",
                           key="dx_csv")

    # ── tab 2: scatter explorer ─────────────────────────────────────────────
    with t_scatter:
        cc = st.columns(4)
        x = cc[0].selectbox("X axis", num_cols, index=_ix("USG%", 0), key="dx_x")
        y = cc[1].selectbox("Y axis", num_cols,
                            index=_ix("TS%", min(1, len(num_cols) - 1)), key="dx_y")
        size = cc[2].selectbox("Size", ["(none)"] + num_cols, key="dx_size")
        color = cc[3].selectbox("Color", ["(none)"] + cat_cols + num_cols,
                                key="dx_color")
        trend = st.checkbox("OLS trendline", value=True, key="dx_trend")

        keep = [c for c in {x, y, "name", "team",
                            *([size] if size != "(none)" else []),
                            *([color] if color != "(none)" else [])}
                if c in df.columns]
        sub = df[keep].dropna(subset=[x, y]).copy()
        if size != "(none)":
            sub = sub[sub[size].notna()]
            sub[size] = sub[size].clip(lower=0)

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
        except Exception as e:
            if kw.pop("size", None) is not None:
                st.caption(f"Size ignored: {e}")
            fig = px.scatter(sub, **kw)
        fig.update_traces(marker=dict(line=dict(width=0)),
                          selector=dict(mode="markers"))
        _style(fig, 540)
        _chart(fig, data=sub, key="dx_scatter")
        if len(sub) >= 3:
            r = sub[x].corr(sub[y])
            st.caption(f"Pearson r = **{r:+.2f}** across {len(sub)} players "
                       f"(r² = {r * r:.2f}). Correlation, not causation.")

    # ── tab 3: correlation heatmap ──────────────────────────────────────────
    with t_corr:
        default_stats = [c for c in (
            "PPG", "USG%", "TS%", "eFG%", "3P%", "AST/TOV", "RPG", "SPG", "BPG",
            "ShotRating", "xPPS", "SMOE", "OVERALL") if c in num_cols]
        pick = st.multiselect("Stats to correlate", num_cols, default=default_stats,
                              key="dx_corrpick")
        if len(pick) < 2:
            empty_state("Pick at least two stats",
                        "Choose two or more stats above to build the correlation "
                        "matrix.", icon="▦")
        else:
            corr = df[pick].corr()
            fig = px.imshow(corr, text_auto=".2f", color_continuous_scale=DIVERGE,
                            zmin=-1, zmax=1, aspect="auto")
            _style(fig, max(360, 34 * len(pick)))
            _chart(fig, data=corr.reset_index(), key="dx_corr")
            st.caption("Pearson correlation across the player pool. Deep green = "
                       "strong positive, deep red = strong negative. Spot which "
                       "stats move together (and which are redundant).")

    # ── tab 4: shot maps (hexbin / expected points / scatter) ───────────────
    with t_shots:
        if not _paid:
            st.info("🔒 Shot maps plot tap-captured shot locations and a distance-"
                    "make model — a **Coaches' Co-op** feature.")
            return
        st.caption("Shot locations from the court tap (x, y). Legacy zone-only "
                   "shots sit at their zone centroid (approx) so the maps work "
                   "today — they sharpen as you track games with the tap capture.")
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
            pl_items = sorted(table.items(),
                              key=lambda kv: -(kv[1].get("OVERALL") or 0))
            psel = cc[1].selectbox(
                "Player", pl_items, key="sm_player",
                format_func=lambda kv: f"{kv[1]['name']} · {kv[1].get('team', '')}")
            kw["player_id"] = psel[0]
        ctype = cc[2].radio("Chart", ["Hexbin (volume + PPS)",
                                      "Points over expected",
                                      "Expected points surface", "Scatter"],
                            key="sm_ctype")
        approx = cc[3].checkbox("Zone-approx", value=True, key="sm_approx",
                                help="Include legacy zone-only shots at their "
                                     "centroid.")

        shots = _mapped(approx, vis=_vis_key, **kw)
        if not shots:
            empty_state("No shots in this view",
                        "Track a game with the court tap, or keep zone-approx on.",
                        icon="🏀")
            return
        n_real = sum(1 for s in shots if not s["approx"])
        st.caption(f"**{len(shots)}** shots · {n_real} located, "
                   f"{len(shots) - n_real} zone-approx.")
        league = _mapped(approx, vis=_vis_key)
        lpps = (sum(s["value"] for s in league if s["make"]) / len(league)
                if league else 1.0)
        if ctype.startswith("Hexbin"):
            fig, _n = court.shot_hexbin(shots, title="Volume + points-per-shot",
                                        league_pps=lpps)
            st.plotly_chart(fig, width="stretch", key="sm_hex")
            st.caption("Hexagon size = shots from that spot; colour = points per "
                       f"shot (green above league {lpps:.2f}, red below).")
        elif ctype.startswith("Points"):
            model = _shot_model(approx, vis=_vis_key)
            fig, _n = court.shot_hexbin(shots, title="Points over expected",
                                        model=model, mode="poe")
            st.plotly_chart(fig, width="stretch", key="sm_poe")
            st.caption("Hexagon size = shot volume; colour = points per shot ABOVE "
                       "/ BELOW what the league make-rate model expects from that "
                       "spot (green = beating the shot's difficulty, red = below).")
        elif ctype.startswith("Expected"):
            model = _shot_model(approx, vis=_vis_key)
            fig = court.expected_points_surface(model, shots=shots, overlay=True,
                                                title="Expected points per shot")
            st.plotly_chart(fig, width="stretch", key="sm_xpts")
            st.caption("Colour = expected points from that spot (league make-rate "
                       "by distance × the 2/3 value). The step at the arc is the "
                       "3-pt bump. Dots = the shots in this view.")
        else:
            fig, _n = court.shot_map(shots, title="Shot map")
            st.plotly_chart(fig, width="stretch", key="sm_scatter")

        _ls = S.shot_location_summary(shots)
        if _ls:
            st.caption(f"Avg distance **{_ls['avg_dist']:.1f} ft** · FG "
                       f"{_ls['fg'] * 100:.0f}% · rim {_ls['rim_n']} · "
                       f"mid {_ls['mid_n']} · three {_ls['three_n']}")
        _dbl = S.distance_buckets([s for s in shots if not s["approx"]])
        if _dbl:
            st.caption("By length (tap-located only) — "
                       + S.distance_buckets_caption(_dbl, show_pps=True))
