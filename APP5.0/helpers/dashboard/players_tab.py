"""
dashboard/players_tab.py — the Team Dashboard "Players" tab.

The roster localized: depth chart, the every-rating table with archetypes,
ratings compared, per-game production, the offense/defense map, shot
selection by zone (nested 2PT/3PT sub-tabs), category leaders, volume vs
efficiency, best shooter by zone and the every-stat leaderboards. Extracted
from pages/6_Team_Dashboard.py (see helpers/dashboard/__init__.py for the
ctx convention).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.court import zone_leader_map as _zone_leader_map
from helpers.ui import DIVERGE, HEAT, grid as _grid
import helpers.team_analytics as TA
import helpers.player_ratings as PR


# Format precision per leaderboard `fmt` kind (pct values already sit on a 0-100
# scale in the player_stat_table rows, so just round).
_FMT_DEC = {"f0": 0, "f1": 1, "f2": 2, "pct": 1}


def _full_stat_df(ctx):
    """Every per-player stat for the roster in ONE flat DataFrame. Columns are
    sourced from ctx.PLAYER_LEADER_GROUPS (the single every-stat catalogue the
    leaderboards use), so this table never re-curates its own column set. Event-
    derived columns are dropped for viewers without tracked access (ctx.has_tracked),
    matching the rest of the tab's gating. Data comes straight from ctx.players
    (already computed for the page) — no new query."""
    seen, spec = set(), []
    for _cat, items in ctx.PLAYER_LEADER_GROUPS:
        for label, key, fmt in items:
            if key in seen:
                continue
            seen.add(key)
            spec.append((label, key, fmt))
    if not ctx.has_tracked:
        spec = [s for s in spec if s[1] not in PR.EVENT_DERIVED_STATS]
    rows = []
    for p in ctx.players:
        row = {"Player": p["name"], "#": p["number"], "GP": p["GP"]}
        for label, key, fmt in spec:
            v = p.get(key)
            row[label] = (round(v, _FMT_DEC.get(fmt, 1))
                          if isinstance(v, (int, float)) and not isinstance(v, bool)
                          else v)
        rows.append(row)
    return pd.DataFrame(rows)


@st.fragment
def render(ctx):
    if not ctx.players:
        st.info("No eligible players for this team yet — track a game in the "
                "Game Tracker.")
    else:
        st.caption("The roster localized: ratings side-by-side, per-game "
                   "production, an offense/defense map, and a lineup builder "
                   "that projects a five from the player ratings.")

        # ── depth chart (position · availability · measurables) ─────────────
        _depth = query(
            """SELECT number, name, position, availability, height, wingspan, weight
               FROM players WHERE team_id=? AND archived=0 ORDER BY number""",
            (ctx.team_id,))
        if any((p["position"] or "").strip() for p in _depth):
            st.markdown("<div class='pl-hdr'>Depth chart</div>",
                        unsafe_allow_html=True)
            _dotc = {"Active": "#2ea043", "Questionable": "#f0a500", "Out": "#da3633"}
            _dc = st.columns(5)
            for _col, _pos in zip(_dc, ["PG", "SG", "SF", "PF", "C"]):
                _h = f"<div class='mini-lbl' style='margin-bottom:6px'>{_pos}</div>"
                for p in [q for q in _depth if (q["position"] or "") == _pos]:
                    _dot = _dotc.get(p["availability"] or "Active", "#8b949e")
                    _meas = " · ".join(
                        ([f"{p['height']:g}\"" ] if p["height"] else [])
                        + ([f"{p['weight']:g}lb"] if p["weight"] else []))
                    _h += (f"<div style='background:#161b22;border:1px solid #30363d;"
                           f"border-radius:8px;padding:6px 9px;margin-bottom:6px'>"
                           f"<span style='color:{_dot}'>●</span> <b>#{p['number']}</b> "
                           f"{p['name']}<div style='font-size:10px;color:#8b949e'>"
                           f"{_meas}</div></div>")
                _col.markdown(_h, unsafe_allow_html=True)
            st.caption("● green = available · amber = questionable · red = out. "
                       "Set positions & status on the **Setup** page.")
        else:
            st.caption("➕ Set player positions on the **Setup** page to unlock the "
                       "depth chart (with height / wingspan / weight).")

        # Top table — a quick toggle between the compact ratings view (default)
        # and ONE scrollable grid of every per-player stat. Default off so the
        # tab stays light; the full grid is wide (every glossary stat) and is
        # built/rendered only on demand.
        _show_all = st.checkbox(
            "📋 Show every stat in one table",
            value=False, key="pl_full_table_toggle",
            help="Swap the ratings table for a single sortable/filterable grid of "
                 "every per-player stat — no need to scroll to the leaderboards.")

        if _show_all:
            _full = _full_stat_df(ctx)
            if _full.empty:
                st.info("No players to show.")
            else:
                _grid(_full, "pl_full_stat_grid", height=560)
                st.download_button(
                    "Every stat (CSV)", _full.to_csv(index=False),
                    file_name=f"players_team{ctx.team_id}.csv", mime="text/csv",
                    key="pl_full_stat_csv")
                st.caption(
                    "Every per-player stat in one grid — sort or filter any column. "
                    + ("Ratings (0–100), shooting, playmaking, rebounding, defense "
                       "and advanced/impact stats." if ctx.has_tracked else
                       "Box-score stats only — tracked ratings and advanced stats "
                       "unlock with a Paid plan."))
        else:
            # Tier gate: the 0-100 ratings, archetype and shot-creation mix are
            # event-derived. ctx.has_tracked already folds in the per-team
            # entitlement (tracked_gate), so a Free viewer / non-pool scout sees only
            # the box columns (#/Player/GP/PPG/RPG/APG/TS%).
            arch = ctx.archetypes(ctx.gender) if ctx.has_tracked else {}
            rdf_rows = []
            for p in ctx.players:
                row = {"#": p["number"], "Player": p["name"], "GP": p["GP"]}
                if ctx.has_tracked:
                    for c in ctx.RATING_COLS_ALL:
                        row[c] = p.get(c)
                    row["Archetype"] = arch.get(p["_pid"], "—")
                row.update({
                    "PPG": p["PPG"], "RPG": p["RPG"], "APG": p["APG"], "TS%": p["TS%"],
                })
                if ctx.has_tracked:
                    row.update({
                        "USG%": p["USG%"], "+/-": p["+/-"],
                        "SC Shot%": p.get("SCShot%"), "SC Pass%": p.get("SCPass%"),
                        "SC Created%": p.get("SCCreated%"),
                    })
                rdf_rows.append(row)
            rdf = pd.DataFrame(rdf_rows)
            st.dataframe(
                rdf, hide_index=True, width="stretch",
                height=min(620, 60 + 35 * len(rdf)),
                column_config={c: st.column_config.ProgressColumn(
                    c, format="%.0f", min_value=0, max_value=100)
                    for c in (ctx.RATING_COLS_ALL if ctx.has_tracked else [])})
            if ctx.has_tracked:
                st.caption("Every per-player rating in the glossary (0–100, 50 = league "
                           "average) plus the data-driven Archetype, and shot-creation "
                           "mix: SC Shot% (own shots), SC Pass% (passes into shots) and "
                           "SC Created% (screens that freed a shooter) — shares of the "
                           "player's total shot creation.")
            else:
                st.caption("Box-score lines. Tracked ratings, archetypes and "
                           "shot-creation mix unlock with a Paid plan.")

        if ctx.has_tracked:
            st.markdown("<div class='lab-hdr'>Ratings compared</div>",
                        unsafe_allow_html=True)
            rated = [p for p in ctx.players if p["OVERALL"] is not None]
            cat = st.selectbox("Rating", ctx.RATING_COLS, key="pl_cat")
            srt = sorted([p for p in rated if p[cat] is not None],
                         key=lambda p: p[cat], reverse=True)
            if srt:
                cfig = go.Figure(go.Bar(
                    x=[f"#{p['number']} {p['name']}" for p in srt],
                    y=[p[cat] for p in srt], marker_color=ctx.ACCENT,
                    marker_line_width=0,
                    text=[f"{p[cat]:.0f}" for p in srt], textposition="auto"))
                cfig.add_hline(y=50, line=dict(color=ctx.GREY, dash="dot"),
                               annotation_text="pool avg")
                cfig.update_yaxes(title=cat, range=[0, 100])
                cfig.update_xaxes(tickangle=-35)
                ctx.style(cfig, 340)
                st.plotly_chart(cfig, width="stretch", key="pl_cat_bar")

        lc, rc = st.columns(2)
        with lc:
            st.markdown("**Per-game production**")
            pg = sorted(ctx.players, key=lambda p: p["PPG"] or 0, reverse=True)[:8]
            x = [f"#{p['number']}" for p in pg]
            pgf = go.Figure()
            pgf.add_trace(go.Bar(x=x, y=[p["PPG"] for p in pg], name="Pts",
                                 marker_color=ctx.ACCENT))
            pgf.add_trace(go.Bar(x=x, y=[p["RPG"] for p in pg], name="Reb",
                                 marker_color=ctx.GOOD))
            pgf.add_trace(go.Bar(x=x, y=[p["APG"] for p in pg], name="Ast",
                                 marker_color=ctx.BLUE))
            pgf.update_layout(barmode="group")
            pgf.update_yaxes(title="Per game")
            ctx.style(pgf, 340)
            st.plotly_chart(pgf, width="stretch", key="pl_pg")
        with rc:
          if ctx.has_tracked:
            st.markdown("**Offense vs defense map**")
            mp = [p for p in ctx.players if p["OFFENSE"] is not None
                  and p["DEFENSE"] is not None]
            if mp:
                sca = go.Figure(go.Scatter(
                    x=[p["OFFENSE"] for p in mp], y=[p["DEFENSE"] for p in mp],
                    mode="markers+text",
                    text=[f"#{p['number']}" for p in mp],
                    textposition="top center", textfont=dict(size=9),
                    marker=dict(size=[max(8, (p["PPG"] or 0) * 1.3) for p in mp],
                                color=[p["OVERALL"] or 50 for p in mp],
                                colorscale=HEAT, showscale=True,
                                colorbar=dict(title="OVR"),
                                line=dict(width=1, color="#30363d")),
                    hovertext=[p["name"] for p in mp],
                    hovertemplate="%{hovertext}<br>OFF %{x:.0f} · DEF %{y:.0f}"
                                  "<extra></extra>"))
                sca.add_vline(x=50, line=dict(color="#30363d", dash="dot"))
                sca.add_hline(y=50, line=dict(color="#30363d", dash="dot"))
                sca.update_xaxes(title="Offense →")
                sca.update_yaxes(title="Defense →")
                ctx.style(sca, 340)
                st.plotly_chart(sca, width="stretch", key="pl_map")
                st.caption("Bubble size = points/game. Top-right = two-way.")

        # ── shot selection: who shoots where (most) & best where, by 2s/3s ──
        st.markdown("<div class='lab-hdr'>Shot selection — who shoots where</div>",
                    unsafe_allow_html=True)
        _zsh = (ctx.zone_player_shooting(ctx.team_id, tuple(ctx.bundle["tracked_ids"]))
                if ctx.has_tracked else None)
        if not _zsh or not _zsh["all"]["players"]:
            st.caption("No located shot data yet — track games to see who shoots "
                       "where, and who shoots best from each spot.")
        else:
            _ZC = {"LC": ctx.GOOD, "LW": ctx.BLUE, "C": ctx.ACCENT,
                   "RW": ctx.PURPLE, "RC": ctx.PINK}
            _MIN_BEST = 3

            def _zlab(z):
                return TA.ZONE_LABELS[z].split("/")[0].strip()

            def _shotsel(data, pfx, tlbl):
                if not data["players"]:
                    st.caption(f"No located {tlbl} attempts in tracked games yet.")
                    return
                _lead = []
                for z in TA.ZONES:
                    rows = data["zones"][z]
                    if not rows:
                        continue
                    vol = rows[0]
                    elig = [r for r in rows if r["FGA"] >= _MIN_BEST]
                    best = (max(elig, key=lambda r: (r["pct"], r["FGA"]))
                            if elig else None)
                    _lead.append({
                        "Zone": TA.ZONE_LABELS[z],
                        "Shoots here most": f"#{vol['number']} {vol['name']} "
                                            f"({vol['FGA']} FGA)",
                        "Best FG% here": (f"#{best['number']} {best['name']} "
                                          f"({best['FGM']}/{best['FGA']} · "
                                          f"{best['pct']*100:.0f}%)"
                                          if best else "—"),
                    })
                if _lead:
                    st.markdown(f"**Zone leaders ({tlbl})** — most attempts & best "
                                f"make-rate (min {_MIN_BEST} att) per spot")
                    st.dataframe(pd.DataFrame(_lead), hide_index=True,
                                 width="stretch")

                top = data["players"][:8]
                if top:
                    xn = [f"#{p['number']}" for p in top]
                    sb = go.Figure()
                    for z in TA.ZONES:
                        sb.add_trace(go.Bar(
                            name=_zlab(z), x=xn,
                            y=[p["by_zone"][z]["FGA"] for p in top],
                            marker_color=_ZC[z], marker_line_width=0,
                            hovertemplate="%{x}<br>" + _zlab(z)
                                          + " %{y} FGA<extra></extra>"))
                    sb.update_layout(barmode="stack",
                                     legend=dict(orientation="h", y=-0.2))
                    sb.update_yaxes(title=f"{tlbl} FGA (tracked)")
                    ctx.style(sb, 320)
                    st.plotly_chart(sb, width="stretch", key=f"pl_zvol_{pfx}")
                    st.caption(f"Where each player's {tlbl} attempts come from — "
                               "taller segment = more shots from that zone.")

                grid = []
                for p in data["players"]:
                    row = {"Player": f"#{p['number']} {p['name']}",
                           "FGA": p["total_FGA"]}
                    for z in TA.ZONES:
                        bz = p["by_zone"][z]
                        row[_zlab(z)] = (f"{bz['FGM']}/{bz['FGA']} · "
                                         f"{bz['pct']*100:.0f}%"
                                         if bz["FGA"] else "—")
                    grid.append(row)
                if grid:
                    st.markdown(f"**Per-player {tlbl} FG% by zone** — FGM/FGA · "
                                "make-rate")
                    st.dataframe(pd.DataFrame(grid), hide_index=True,
                                 width="stretch",
                                 height=min(440, 60 + 35 * len(grid)))

            _t2, _t3 = st.tabs(["2-pointers", "3-pointers"])
            with _t2:
                _shotsel(_zsh["2"], "2", "2-pt")
            with _t3:
                _shotsel(_zsh["3"], "3", "3-pt")

            # shot-selection profile — perimeter (3PA rate) vs paint volume
            _sel = [p for p in ctx.players if p.get("3PR") is not None
                    and p.get("PaintA") is not None and p.get("GP")]
            if _sel:
                st.markdown("**Shot-selection profile** — perimeter vs paint")
                _selfig = go.Figure(go.Scatter(
                    x=[p["3PR"] for p in _sel],
                    y=[p["PaintA"] / p["GP"] for p in _sel],
                    mode="markers+text",
                    text=[f"#{p['number']}" for p in _sel],
                    textposition="top center", textfont=dict(size=9),
                    marker=dict(
                        size=[max(9, (p["PPG"] or 0) * 1.4) for p in _sel],
                        color=[p["PPG"] or 0 for p in _sel],
                        colorscale=HEAT, showscale=True,
                        colorbar=dict(title="PPG"),
                        line=dict(width=1, color="#30363d")),
                    hovertext=[p["name"] for p in _sel],
                    hovertemplate="%{hovertext}<br>3PA rate %{x:.0f}%"
                                  "<br>Paint FGA/g %{y:.1f}<extra></extra>"))
                _selfig.update_xaxes(title="3-point attempt rate (% of FGA) →")
                _selfig.update_yaxes(title="Paint attempts / game →")
                ctx.style(_selfig, 380)
                st.plotly_chart(_selfig, width="stretch", key="pl_shotsel")
                st.caption("Bottom-right = perimeter-heavy; top-left = paint-"
                           "focused. Bubble size & color = points/game.")

        # ── category leaders ────────────────────────────────────────────────
        st.markdown("<div class='lab-hdr'>Category leaders</div>",
                    unsafe_allow_html=True)
        LEAD = [("PPG", "Points/g", "f1"), ("RPG", "Rebounds/g", "f1"),
                ("APG", "Assists/g", "f1"), ("STOCKS/G", "Stocks/g", "f1"),
                ("TS%", "True shooting", "pct"), ("USG%", "Usage", "pct")]
        if not ctx.has_tracked:   # drop event-derived leaders (e.g. USG%) for Free
            LEAD = [x for x in LEAD if x[0] not in PR.EVENT_DERIVED_STATS]
        lcols = st.columns(3)
        for i, (key, lbl, fmt) in enumerate(LEAD):
            pool = [p for p in ctx.players if p.get(key) is not None]
            if not pool:
                continue
            best = max(pool, key=lambda p: p[key])
            val = ctx.pctf(best[key] / 100) if fmt == "pct" else f"{best[key]:.1f}"
            with lcols[i % 3]:
                st.metric(lbl, val, help=f"#{best['number']} {best['name']}")
                st.caption(f"#{best['number']} {best['name']}")

        # ── volume vs efficiency + shot selection (tracked-only) ────────────
        if ctx.has_tracked:
            st.markdown("<div class='lab-hdr'>Volume vs efficiency</div>",
                        unsafe_allow_html=True)
            ve = [p for p in ctx.players
                  if p["USG%"] is not None and p["TS%"] is not None]
            if ve:
                vfig = go.Figure(go.Scatter(
                    x=[p["USG%"] for p in ve], y=[p["TS%"] for p in ve],
                    mode="markers+text", text=[f"#{p['number']}" for p in ve],
                    textposition="top center", textfont=dict(size=9),
                    marker=dict(size=[max(9, (p["PPG"] or 0) * 1.4) for p in ve],
                                color=[p["OVERALL"] or 50 for p in ve],
                                colorscale=HEAT, showscale=True,
                                colorbar=dict(title="OVR"),
                                line=dict(width=1, color="#30363d")),
                    hovertext=[p["name"] for p in ve],
                    hovertemplate="%{hovertext}<br>USG %{x:.0f}% · TS %{y:.0f}%"
                                  "<extra></extra>"))
                vfig.update_xaxes(title="Usage % →")
                vfig.update_yaxes(title="True shooting % →")
                ctx.style(vfig, 360)
                st.plotly_chart(vfig, width="stretch", key="pl_ve")
                st.caption("Bubble size = points/game. Top-right = high-volume and "
                           "efficient — the offensive engines.")

            # ── best shooter by zone (court heatmap) ────────────────────────
            st.markdown("<div class='lab-hdr'>Best shooter by zone</div>",
                        unsafe_allow_html=True)
            pzl = ctx.bundle.get("player_zone_leaders")
            if pzl and any(pzl.values()):
                # Rendered on the real half-court (helpers/court.py) instead of
                # the old hand-drawn rectangles.
                hz, _ = _zone_leader_map(pzl, title="", colorscale=DIVERGE)
                st.plotly_chart(hz, width="stretch", key="pl_zone_best")
                st.caption("Each zone shows the teammate with the best FG% there "
                           "(≥3 located attempts), colored by make rate — the go-to "
                           "shooter for every spot on the floor.")
            else:
                st.caption("Not enough located attempts to rank shooters by zone "
                           "yet.")

        # ── every-stat leaderboards (relative within the roster) ────────────
        st.markdown("<div class='lab-hdr'>Stat leaderboards — every stat</div>",
                    unsafe_allow_html=True)
        st.caption("Every player stat the app tracks, as a roster leaderboard — "
                   "players ranked against each other on that stat. Expand a "
                   "category to see all its stats.")
        # Free / non-pool viewers get box-only leaderboards — drop the
        # event-derived stats (spec entry is (label, key, fmt); key at index 1).
        _lb_groups = ctx.PLAYER_LEADER_GROUPS
        if not ctx.has_tracked:
            _lb_groups = [(cat, [s for s in spec
                                 if s[1] not in PR.EVENT_DERIVED_STATS])
                          for cat, spec in _lb_groups]
            _lb_groups = [(cat, spec) for cat, spec in _lb_groups if spec]
        _n_lb = sum(len(spec) for _, spec in _lb_groups)
        # heavy wall (~59 charts) — render on demand only (page-load perf)
        if st.checkbox(f"Load all stat leaderboards ({_n_lb} charts)",
                       value=False, key="pl_lb_load"):
            for gi, (cat_name, spec) in enumerate(_lb_groups):
                with st.expander(cat_name,
                                 expanded=(cat_name == "Scoring & shooting")):
                    ctx.player_leaderboards(ctx.players, spec,
                                            key_prefix=f"pllb{gi}")
