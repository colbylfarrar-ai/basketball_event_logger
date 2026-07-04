"""
situational_tab.py — the Team Dashboard "Situational" super-tab (Charts → Situational).

*When* a team leans on a set or scheme: which quarter, what score-state, on a run.
A pure renderer (the playstyle_tab.py / defense_tab.py pattern) — all heavy data
arrives via the page-cached ``ctx.situational(g, tid)`` callable (helpers/situational.py
team_situational), so caching stays on the page and this module is testable in
isolation via AppTest.from_function.

Sparsity is the binding constraint: tagged play_type/defense sliced by situation gets
thin fast, so every cell shows its possession count and the broad slices (by-quarter,
leading/trailing) fill in before the narrow ones. Dormant-until-tagged, like the rest
of the play_type engine.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from helpers.cards import glass, dense_table
from helpers.ui import empty_state, style_fig

# Identity palette for the usage bars (separate from any performance colour).
_PALETTE = ["#58a6ff", "#3fb950", "#bc8cff", "#ff5db1", "#f0a500", "#e74c3c",
            "#2dd4bf", "#f97583", "#a3e635", "#fbbf24", "#22d3ee", "#c084fc",
            "#7ee787"]
# more-is-share heatmap: fade into the card, climb to gold.
_HEAT = [[0.0, "#161b22"], [1.0, "#f0a500"]]


def _fmt_top(t):
    return f"{t['label']} {t['share'] * 100:.0f}%" if t else "—"


@st.fragment
def render(ctx):
    """Render the Situational super-tab. ``ctx`` carries plain values + the page-cached
    ``ctx.situational(gender, team_id)`` callable returning helpers.situational
    .team_situational output (or None)."""
    g, tid = ctx.gender, ctx.team_id
    st.markdown("<div class='pl-hdr'>Situational tendencies — when they run it</div>",
                unsafe_allow_html=True)
    st.caption(
        "How the offense (and the defense it runs) shifts by **quarter**, **score "
        "state**, and whether the team is **on a run**. A shot ends a possession, so "
        "PPP = points per possession. Each situation is its own lens — a possession "
        "can be both *4th quarter* and *down 10+*.")

    if not getattr(ctx, "has_tracked", False):
        empty_state("No tracked games yet",
                    "Track a game and tag shots with a Play type / Defense to unlock "
                    "the situational breakdown.", icon="🎬")
        return

    # ── By game type — how they play in Regular / District / Playoff / … ──────
    _bgt = ctx.by_game_type(g, tid) if getattr(ctx, "by_game_type", None) else None
    if _bgt and len(_bgt) > 1:
        st.markdown("<div class='pl-hdr'>By game type — how they play in each</div>",
                    unsafe_allow_html=True)
        st.caption("Record + margin from every game; efficiency (points per "
                   "possession, eFG%, pace) and shot mix from the tracked ones — so "
                   "you can compare their playoff / rivalry self to the regular-season "
                   "baseline.")

        def _n(v, fmt):
            return fmt.format(v) if v is not None else None
        st.markdown(dense_table([{
            "Type": r["type"], "GP": r["GP"], "W-L": f"{r['W']}-{r['L']}",
            "MOV": _n(r["MOV"], "{:+.1f}"),
            "Off PPP": _n(r.get("oPPP"), "{:.2f}"),
            "Def PPP": _n(r.get("dPPP"), "{:.2f}"),
            "eFG%": _n(r.get("eFG"), "{:.0f}%"),
            "Opp eFG%": _n(r.get("oeFG"), "{:.0f}%"),
            "Pace": _n(r.get("pace"), "{:.1f}"),
            "Rim%": _n(r.get("rim%"), "{:.0f}%"),
            "3PA%": _n(r.get("3PA%"), "{:.0f}%"),
            "Trk GP": r.get("trk_gp"),
        } for r in _bgt]), unsafe_allow_html=True)
        st.caption("Efficiency / eFG% / pace / shot-mix come from tracked games only "
                   "(Trk GP); '—' = no tracked game of that type yet. Set a game's "
                   "type on the Roster & District page.")
        st.divider()

    data = ctx.situational(g, tid) if getattr(ctx, "situational", None) else None
    if not data or len(data.get("situations", [])) <= 1:
        st.info("Not enough tracked possessions yet — the situational breakdown fills "
                "in automatically as you log games (and sharpens once you tag **Play "
                "type** / **Defense** on shots).")
        return

    sits = data["situations"]
    baseline = sits[0]                       # the 'all' row
    by_key = {s["key"]: s for s in sits}
    if data.get("tagged_total", 0) == 0:
        st.info("These games have scoring but no **Play type** tags yet — the scoring "
                "lines by situation below already work; tag sets in the tracker to "
                "unlock the go-to-set and defense-scheme columns.")

    # ── §A — headline: go-to set & efficiency by situation ───────────────────
    st.markdown("<div class='pl-hdr'>Go-to set &amp; efficiency by situation</div>",
                unsafe_allow_html=True)
    arows = []
    for s in sits[1:]:
        arows.append({
            "Situation": s["label"] + ("" if s["stable"] else " ⚠"),
            "Group": s["group"], "Poss": s["off_poss"],
            "Poss len": (f"{s['secs']:.1f} s"
                         if s.get("secs") is not None else None),
            "PPP": f"{s['PPP']:.2f}", "eFG%": f"{s['eFG'] * 100:.0f}%",
            "FG%": f"{s['FG%'] * 100:.0f}%",
            "Go-to set": _fmt_top(s["top_play"]),
            "Defense run": _fmt_top(s["top_def"]),
        })
    st.markdown(dense_table(
        arows, num_cols=("Poss", "Poss len", "PPP", "eFG%", "FG%")),
        unsafe_allow_html=True)
    _blen = (f" · {baseline['secs']:.1f}s/poss"
             if baseline.get("secs") is not None else "")
    st.caption(
        f"Baseline (all possessions): **{baseline['PPP']:.2f} PPP** · "
        f"{baseline['eFG'] * 100:.0f}% eFG{_blen} over {baseline['off_poss']} poss. "
        "Compare each situation's PPP to that. 'Go-to set' / 'Defense run' need "
        "tagged plays; '—' = untagged. ⚠ marks situations under "
        f"{__import__('helpers.situational', fromlist=['SIT_MIN_POSS']).SIT_MIN_POSS} "
        "possessions — thin, read them lightly.")

    # ── §B — drill into one situation ────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Drill into a situation</div>",
                unsafe_allow_html=True)
    opts = [s["label"] for s in sits[1:]]
    lbl2key = {s["label"]: s["key"] for s in sits[1:]}
    pick = st.selectbox("Situation", opts, key="sit_drill_pick")
    s = by_key.get(lbl2key.get(pick), baseline)

    k1, k2, k3 = st.columns(3)
    k1.metric("Possessions", s["off_poss"])
    k2.metric("PPP", f"{s['PPP']:.2f}",
              delta=f"{s['PPP'] - baseline['PPP']:+.2f} vs all",
              delta_color="normal")
    k3.metric("eFG%", f"{s['eFG'] * 100:.0f}%",
              delta=f"{(s['eFG'] - baseline['eFG']) * 100:+.0f} vs all",
              delta_color="normal")
    if not s["stable"]:
        st.caption("⚠ Thin sample — read this situation lightly until more games.")

    plays = s.get("plays", [])
    if plays:
        st.markdown("**Offense — what they run here**")
        pfig = go.Figure(go.Bar(
            x=[p["label"] for p in plays],
            y=[round(p["share"] * 100) for p in plays],
            marker_color=[_PALETTE[i % len(_PALETTE)] for i in range(len(plays))],
            marker_line_width=0,
            text=[f"{p['share'] * 100:.0f}%" for p in plays],
            textposition="outside",
            hovertext=[f"{p['label']}: {p['poss']} poss · {p['PPP']:.2f} PPP"
                       for p in plays], hoverinfo="text"))
        pfig.update_yaxes(title="Share of tagged plays (%)")
        style_fig(pfig, 300)
        st.plotly_chart(pfig, width="stretch", key="sit_play_bar")
        st.markdown(dense_table([{
            "Set": p["label"], "Poss": p["poss"],
            "Share": f"{p['share'] * 100:.0f}%", "PPP": f"{p['PPP']:.2f}",
            "eFG%": f"{p['eFG'] * 100:.0f}%", "FG%": f"{p['FG%'] * 100:.0f}%",
        } for p in plays]), unsafe_allow_html=True)
    else:
        st.caption("No tagged offensive sets in this situation yet.")

    defs = s.get("defenses", [])
    if defs:
        st.markdown("**Defense — what they run here (schemes)**")
        dfig = go.Figure(go.Bar(
            x=[d["label"] for d in defs],
            y=[round(d["share"] * 100) for d in defs],
            marker_color=[_PALETTE[i % len(_PALETTE)] for i in range(len(defs))],
            marker_line_width=0,
            text=[f"{d['share'] * 100:.0f}%" for d in defs],
            textposition="outside",
            hovertext=[f"{d['label']}: {d['poss']} poss · {d['PPP']:.2f} PPP allowed"
                       for d in defs], hoverinfo="text"))
        dfig.update_yaxes(title="Share of tagged defensive poss (%)")
        style_fig(dfig, 300)
        st.plotly_chart(dfig, width="stretch", key="sit_def_bar")
        st.markdown(dense_table([{
            "Scheme": d["label"], "Poss": d["poss"],
            "Share": f"{d['share'] * 100:.0f}%",
            "PPP allowed": f"{d['PPP']:.2f}",
        } for d in defs]), unsafe_allow_html=True)

    # ── §C — situational sets (usage concentration) ──────────────────────────
    conc = data.get("concentration", [])
    if conc:
        st.markdown("<div class='pl-hdr'>Situational sets — called far more in one "
                    "spot</div>", unsafe_allow_html=True)
        st.caption("A set whose usage SHARE spikes in a situation vs its overall rate "
                   "— the plays they save for a moment.")
        cols = st.columns(min(3, len(conc)))
        for i, c in enumerate(conc[:6]):
            cols[i % len(cols)].markdown(glass(
                c["play_label"], f"{c['lift']:.1f}× usage",
                f"in {c['sit_label']} · {c['share_here'] * 100:.0f}% "
                f"(vs {c['share_overall'] * 100:.0f}% overall) · {c['poss']}p"),
                unsafe_allow_html=True)

    # ── §D — set-usage map (share heatmap: set × situation) ──────────────────
    base_plays = [p for p in baseline.get("plays", []) if p["poss"] > 0][:8]
    cols_s = sits[1:]
    if base_plays and cols_s:
        st.markdown("<div class='pl-hdr'>Set-usage map — share by situation</div>",
                    unsafe_allow_html=True)
        play_keys = [p["key"] for p in base_plays]
        play_lbls = [p["label"] for p in base_plays]
        z, txt = [], []
        for pk in play_keys:
            zr, tr = [], []
            for s2 in cols_s:
                share = next((pp["share"] for pp in s2["plays"] if pp["key"] == pk), 0.0)
                zr.append(round(share * 100))
                tr.append(f"{share * 100:.0f}%" if share else "")
            z.append(zr)
            txt.append(tr)
        hfig = go.Figure(go.Heatmap(
            z=z, x=[s2["label"] for s2 in cols_s], y=play_lbls,
            colorscale=_HEAT, text=txt, texttemplate="%{text}",
            textfont=dict(size=10), showscale=False,
            hovertemplate="%{y} in %{x}: %{z}% of tagged plays<extra></extra>"))
        hfig.update_xaxes(tickangle=-30)
        style_fig(hfig, 60 + 34 * len(play_lbls), margin=dict(l=8, r=8, t=10, b=70))
        st.plotly_chart(hfig, width="stretch", key="sit_heat")
        st.caption("Darker/gold = a bigger share of that situation's tagged plays. "
                   "Read across a row to see where a set lives.")

    # ── §E — defense-usage map (scheme × situation share heatmap) ─────────────
    base_defs = [d for d in baseline.get("defenses", []) if d["poss"] > 0][:8]
    if base_defs and cols_s:
        st.markdown("<div class='pl-hdr'>Defense-usage map — share by situation"
                    "</div>", unsafe_allow_html=True)
        def_keys = [d["key"] for d in base_defs]
        def_lbls = [d["label"] for d in base_defs]
        dz, dtxt = [], []
        for dk in def_keys:
            zr, tr = [], []
            for s2 in cols_s:
                share = next((dd["share"] for dd in s2["defenses"]
                              if dd["key"] == dk), 0.0)
                zr.append(round(share * 100))
                tr.append(f"{share * 100:.0f}%" if share else "")
            dz.append(zr)
            dtxt.append(tr)
        dhfig = go.Figure(go.Heatmap(
            z=dz, x=[s2["label"] for s2 in cols_s], y=def_lbls,
            colorscale=_HEAT, text=dtxt, texttemplate="%{text}",
            textfont=dict(size=10), showscale=False,
            hovertemplate="%{y} in %{x}: %{z}% of tagged def poss<extra></extra>"))
        dhfig.update_xaxes(tickangle=-30)
        style_fig(dhfig, 60 + 34 * len(def_lbls),
                  margin=dict(l=8, r=8, t=10, b=70))
        st.plotly_chart(dhfig, width="stretch", key="sit_def_heat")
        st.caption("Darker/gold = a bigger share of that situation's tagged "
                   "defensive possessions. Read across a row to see when they run "
                   "each scheme.")
