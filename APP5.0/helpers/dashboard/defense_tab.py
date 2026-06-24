"""
defense_tab.py — the Team Dashboard "Defense" super-tab (Charts → Defense).

The deep-dive home for the one-tap ``defense`` scheme tag — the defensive
companion to playstyle_tab.py. A pure renderer (same pattern): all heavy data
arrives via pre-bound, page-cached callables on ``ctx`` so caching stays on the
page and this module is testable in isolation (AppTest.from_function).

Two sides off one tag (the playtypes offense/allowed duality):
  • "Our defense"        → the schemes WE run (tagged on shots we ALLOWED): PPP
                           allowed per scheme — lower is better.
  • "Vs defenses we face"→ how WE attack each scheme thrown at us (tagged on our
                           OWN shots): PPP scored — higher is better.

Sections, in order:
  A header + side toggle + coverage
  B family rollup (man / zone / press …) — donut + PPP bars
  C per-scheme PPP percentile bars + tier + detail table
  D frequency × efficiency quadrant
  E scheme fingerprint (3PA / rim / assisted / open / zone / tempo)
  F PLAY TYPE × DEFENSE cross-tab heatmap  ("their PnR vs a 2-3 zone")
  G press / trap disruption — turnovers per scheme
  H league rank context (you vs league best / avg)
  I our defense vs our offense by scheme
  J per-player — how each scorer handles each defense faced
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import helpers.defenses as DEF
import helpers.playtypes as PT
import helpers.stats as S
import helpers.court as court
from helpers.cards import pctile_bar, glass
from helpers.ui import empty_state, seg, style_fig

# Identity palette per family for the distribution donut (kept separate from the
# tier colours, which encode performance, not which scheme it is).
_FAM_COLOR = {
    "man": "#58a6ff", "zone": "#3fb950", "press": "#ff5db1",
    "trap": "#f0a500", "junk": "#bc8cff", "transition": "#2dd4bf",
    "other": "#8b949e",
}
# key -> label for the by-defense shot court (color-by-defense facet).
_DEF_LABEL = {k: l for k, l, _f in DEF.DEFENSES}


def _pctile_or_thin(label, value_str, pct):
    """Percentile bar, or the 'thin sample' row when pct is None (mirrors
    playstyle_tab so the two tabs read identically)."""
    if pct is None:
        return (f"<div class='pl-pct'><div class='pl-pct-top'>"
                f"<span class='pl-pct-lbl'>{label}</span>"
                f"<span class='pl-pct-val'>{value_str} · "
                f"<span style='color:#8b949e'>thin sample</span>"
                f"</span></div></div>")
    return pctile_bar(label, value_str, round(pct))


def _howline(pr):
    """'What this scheme gives up / how we attack it' line from a shot profile."""
    if not pr:
        return ""
    bits = []
    if pr.get("3PA_rate") is not None:
        bits.append(f"{pr['3PA_rate'] * 100:.0f}% 3PA")
    if pr.get("rim_rate") is not None:
        bits.append(f"{pr['rim_rate'] * 100:.0f}% rim")
    if pr.get("ast_rate") is not None:
        bits.append(f"{pr['ast_rate'] * 100:.0f}% assisted")
    if pr.get("open_rate") is not None:
        bits.append(f"{pr['open_rate'] * 100:.0f}% open")
    tz = pr.get("top_zone")
    if tz:
        from helpers.team_analytics import ZONE_LABELS
        bits.append(f"mostly {ZONE_LABELS.get(tz, tz).lower()}")
    return " · ".join(bits)


# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def render(ctx):
    """Render the Defense super-tab. ``ctx`` carries plain values + pre-bound
    page-cached callables (see module docstring / the page call site)."""
    g, tid = ctx.gender, ctx.team_id
    st.markdown("<div class='pl-hdr'>Defense — the scheme deep dive</div>",
                unsafe_allow_html=True)
    st.caption(
        "The advanced home for the one-tap **Defense** tag: how each scheme you "
        "run holds up, how you attack the defenses thrown at you, and the cross-"
        "tab the offense view can't give — **play type × defense**. A shot ends a "
        "possession, so PPP = points per shot.")

    if not getattr(ctx, "has_tracked", False):
        empty_state("No tracked games yet",
                    "Track a game and set the **Defense** in the tracker to unlock "
                    "the defensive-scheme deep dive.", icon="🛡️")
        return

    # ── §A — side toggle + coverage ──────────────────────────────────────────
    _side = seg("Side of the ball", ["Our defense", "Vs defenses we face"],
                key="def_side") or "Our defense"
    _off = _side != "Our defense"     # offense=True => the defenses we FACE
    dv = ctx.def_view(g, tid, _off)
    drows = dv.get("rows", [])
    st.caption(
        f"{'Defenses we ran (shots we allowed)' if not _off else 'Defenses we faced (our shots)'}: "
        f"{dv.get('total_tagged', 0)} tagged · {dv.get('untagged', 0)} untagged. "
        f"Percentile is good-oriented "
        f"({'fewer points allowed' if not _off else 'more points scored'} = higher rank).")

    if not drows and dv.get("total_tagged", 0) == 0:
        st.info("No defense tags on these shots yet — set the **Defense** "
                "(man, 2-3, 1-3-1, presses, traps…) in the Game Tracker; it's "
                "sticky, so one tap covers a whole stretch. This tab fills in as "
                "you tag.")
        return

    # ══ §B0 — SHOT CHART BY DEFENSE (headline court) ═════════════════════════
    # The court plots your OWN tap-located shots, filterable by the defense you
    # FACED — "where do we get our looks vs a 2-3 zone vs man". located_team is
    # own-shots only, so it lives on the offense side ("Vs defenses we face"); the
    # "Our defense" side has no located opponent shots (same as Play Style).
    st.markdown("<div class='pl-hdr'>Shot chart by defense</div>",
                unsafe_allow_html=True)
    shots = list(ctx.located_team(tid, ctx.tracked_ids) or []) if _off else []
    if not shots:
        st.caption(
            "The court shows your OWN shots by the defense you FACED — flip to "
            "**Vs defenses we face** to see it." if not _off else
            "No tap-located shots yet — tap shot spots in the Game Tracker to "
            "unlock the court (the tables below still work from zone data).")
    else:
        _seen = {s.get("defense") for s in shots if s.get("defense")}
        lbl2key = {DEF.label(k): k for k, _l, _f in DEF.DEFENSES if k in _seen}
        n_untagged = sum(1 for s in shots if not s.get("defense"))
        _mode = seg("Chart mode",
                    ["Filter to one defense", "Facet (color by defense)"],
                    key="def_chart_mode") or "Filter to one defense"
        if _mode.startswith("Facet"):
            fig, n = court.shot_map_grouped(
                shots, group_key="defense", labels=_DEF_LABEL,
                title="Every shot, colored by the defense faced")
            if n:
                st.plotly_chart(fig, width="stretch", key="def_court_facet")
                st.caption("Each colour = a defense faced · filled = make, open = "
                           "miss · grey = untagged. Spot how your looks cluster vs "
                           "each scheme.")
            else:
                st.caption("No located shots to plot.")
        else:
            pick = st.selectbox("Defense", ["All defenses"] + list(lbl2key),
                                key="def_court_pick", disabled=not lbl2key,
                                help="Filter the court to one defense you faced.")
            _dk = lbl2key.get(pick)
            fshots = [s for s in shots if s.get("defense") == _dk] if _dk else shots
            view = seg("View", ["Shot map", "Hexbin (PPS)", "Quality (POE)"],
                       key="def_court_view") or "Shot map"
            who = pick if _dk else "All defenses"
            if view.startswith("Shot"):
                fig, n = court.shot_map(fshots, title=f"{who} · shot map")
            elif view.startswith("Hexbin"):
                fig, n = court.shot_hexbin(fshots, title=f"{who} · volume · PPS",
                                           league_pps=ctx.league_pps(g))
            else:
                fig, n = court.shot_hexbin(fshots, title=f"{who} · points over expected",
                                           model=ctx.shot_model(g), mode="poe")
            if n:
                st.plotly_chart(fig, width="stretch", key="def_court_filter")
            else:
                st.caption("No located shots for this filter.")
            _db = S.distance_buckets(fshots)
            if _db:
                st.caption("By length — " + S.distance_buckets_caption(_db))
        if n_untagged:
            st.caption(f"{n_untagged}/{len(shots)} located shots are untagged — set "
                       "the defense in the tracker to sharpen the by-scheme court.")

    # ══ §B — family rollup (man / zone / press …) ════════════════════════════
    fam = ctx.def_families(g, tid, _off) or {}
    frows = fam.get("rows", [])
    if frows:
        st.markdown("<div class='pl-hdr'>By family — man · zone · press</div>",
                    unsafe_allow_html=True)
        fc1, fc2 = st.columns([1, 1])
        with fc1:
            pie = go.Figure(go.Pie(
                labels=[r["label"] for r in frows],
                values=[r["poss"] for r in frows],
                marker=dict(colors=[_FAM_COLOR.get(r["family"], "#8b949e")
                                    for r in frows],
                            line=dict(color="#0d1117", width=2)),
                textinfo="label+percent", sort=False, hole=0.55,
                hovertemplate="%{label}: %{value} poss · %{percent}<extra></extra>"))
            pie.update_layout(
                showlegend=False, height=330, paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                annotations=[dict(text=f"<b>{fam.get('total_tagged', 0)}</b><br>poss",
                                  x=0.5, y=0.5, showarrow=False,
                                  font=dict(size=15, color="#c9d1d9"))])
            st.plotly_chart(pie, width="stretch", key="def_fam_pie")
        with fc2:
            bfig = go.Figure(go.Bar(
                x=[r["label"] for r in frows], y=[round(r["PPP"], 2) for r in frows],
                marker_color=[_FAM_COLOR.get(r["family"], "#8b949e") for r in frows],
                marker_line_width=0, text=[f"{r['PPP']:.2f}" for r in frows],
                textposition="outside"))
            bfig.update_yaxes(title="PPP " + ("allowed" if not _off else "scored"))
            style_fig(bfig, 330)
            st.plotly_chart(bfig, width="stretch", key="def_fam_ppp")
        st.caption("Share of tagged possessions by family (donut) and the PPP each "
                   "family " + ("gives up" if not _off else "yields you") + ".")

    # ══ §C — per-scheme PPP percentile bars + table ══════════════════════════
    st.markdown("<div class='pl-hdr'>Scheme efficiency — ranked vs the league"
                "</div>", unsafe_allow_html=True)
    if drows:
        for r in drows:
            val = (f"{r['PPP']:.2f} PPP · {r['FG%'] * 100:.0f}% FG · "
                   f"{r['poss']} poss")
            st.markdown(_pctile_or_thin(r["label"], val, r["pct"]),
                        unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{
            "Defense": r["label"], "Poss": r["poss"],
            "PPP": round(r["PPP"], 2), "FG%": round(r["FG%"] * 100, 0),
            "3P%": round(r.get("3P%", 0) * 100, 0),
            "eFG%": round(r.get("eFG", 0) * 100, 0),
            "SCE": round(r.get("SCE", 0) * 100, 0),
            "Share": round(r["share"] * 100, 0), "Tier": r["tier"],
        } for r in drows]), hide_index=True, width="stretch", column_config={
            "PPP": st.column_config.NumberColumn("PPP", format="%.2f"),
            "FG%": st.column_config.NumberColumn("FG%", format="%.0f%%"),
            "3P%": st.column_config.NumberColumn("3P%", format="%.0f%%"),
            "eFG%": st.column_config.NumberColumn("eFG%", format="%.0f%%"),
            "SCE": st.column_config.NumberColumn("SCE", format="%.0f%%"),
            "Share": st.column_config.NumberColumn("Share", format="%.0f%%"),
        }, key="def_scheme_tbl")
        st.caption("PPP = points/possession · eFG% weights 3s · SCE = scoring "
                   "efficiency · Share = % of tagged possessions. Rank is good-"
                   "oriented for this side.")

        # go-to / leak chips from the ranked rows
        ranked = [r for r in drows if r["pct"] is not None and r["poss"] >= DEF.MIN_POSS]
        if ranked:
            best = max(ranked, key=lambda r: r["pct"])
            worst = min(ranked, key=lambda r: r["pct"])
            cc = st.columns(2)
            cc[0].markdown(glass(
                "Best scheme" if not _off else "We torch",
                best["label"],
                f"{best['PPP']:.2f} PPP · {best['pct']}th pct · {best['poss']} poss",
                color=best["color"]), unsafe_allow_html=True)
            if worst["key"] != best["key"]:
                cc[1].markdown(glass(
                    "Leak" if not _off else "We stall vs",
                    worst["label"],
                    f"{worst['PPP']:.2f} PPP · {worst['pct']}th pct · "
                    f"{worst['poss']} poss", color=worst["color"]),
                    unsafe_allow_html=True)
    else:
        st.caption("No tagged schemes yet for this side.")

    # ══ §D — frequency × efficiency quadrant ═════════════════════════════════
    if drows:
        st.markdown("<div class='pl-hdr'>Frequency × efficiency</div>",
                    unsafe_allow_html=True)
        qx = [r["share"] * 100 for r in drows]
        qy = [r["PPP"] for r in drows]
        qsz = [r["poss"] for r in drows]
        qmax = max(qsz) or 1
        qposs = sum(qsz)
        qppp = (sum(r["PPP"] * r["poss"] for r in drows) / qposs) if qposs else 0.0
        qsh = (sum(qx) / len(qx)) if qx else 0.0
        qfig = go.Figure(go.Scatter(
            x=qx, y=qy, mode="markers+text",
            text=[r["label"] for r in drows], textposition="top center",
            textfont=dict(size=10),
            marker=dict(size=[12 + 30 * (p / qmax) for p in qsz],
                        sizemode="diameter", color=[r["color"] for r in drows],
                        line=dict(width=1, color="#0d1117"), opacity=0.9),
            hovertext=[f"{r['label']}: {r['PPP']:.2f} PPP · {r['poss']} poss · "
                       f"{r['share'] * 100:.0f}% share" for r in drows],
            hoverinfo="text"))
        qfig.add_vline(x=qsh, line=dict(color=ctx.GREY, dash="dot"))
        qfig.add_hline(y=qppp, line=dict(color=ctx.GREY, dash="dot"))
        qfig.update_xaxes(title="Share of tagged possessions (%)")
        qfig.update_yaxes(title="PPP " + ("allowed" if not _off else "scored"))
        style_fig(qfig, 360)
        st.plotly_chart(qfig, width="stretch", key="def_quad")
        st.caption(
            ("Bottom-right = your bread-and-butter D (run it a lot, gives up little). "
             "Top-right = leaned-on but leaky. Lines = your average share & PPP."
             if not _off else
             "Top-right = a scheme you face a lot AND score well on — attack it. "
             "Bottom-right = faced often but you stall. Lines = your avg share & PPP."))

    # ══ §E — scheme fingerprint ══════════════════════════════════════════════
    prof = ctx.def_profiles(g, tid, _off) or {}
    if prof:
        st.markdown("<div class='pl-hdr'>Scheme fingerprint — what each gives up"
                    "</div>", unsafe_allow_html=True)
        from helpers.team_analytics import ZONE_LABELS as _ZL
        fdf = pd.DataFrame([{
            "Defense": p["label"], "Poss": p["poss"], "PPP": round(p["PPP"], 2),
            "eFG%": round(p.get("eFG", 0) * 100, 0),
            "3PA%": round(p["3PA_rate"] * 100, 0),
            "Rim%": round(p["rim_rate"] * 100, 0),
            "Assisted%": round(p["ast_rate"] * 100, 0),
            "Open%": round(p["open_rate"] * 100, 0),
            "Where": _ZL.get(p["top_zone"], "—") if p["top_zone"] else "—",
            "Avg s": round(p["avg_secs"], 1) if p["avg_secs"] is not None else None,
        } for p in sorted(prof.values(), key=lambda p: -p["poss"])])
        st.dataframe(fdf, hide_index=True, width="stretch", column_config={
            "PPP": st.column_config.NumberColumn("PPP", format="%.2f"),
            "eFG%": st.column_config.NumberColumn("eFG%", format="%.0f%%"),
            "3PA%": st.column_config.NumberColumn("3PA%", format="%.0f%%"),
            "Rim%": st.column_config.NumberColumn("Rim%", format="%.0f%%"),
            "Assisted%": st.column_config.NumberColumn("Assisted%", format="%.0f%%"),
            "Open%": st.column_config.NumberColumn("Open%", format="%.0f%%"),
            "Avg s": st.column_config.NumberColumn("Avg s", format="%.1f"),
        }, key="def_fingerprint")
        st.caption("3PA% / Rim% = shot-type share " +
                   ("allowed" if not _off else "you get") +
                   " · Assisted% = off a pass · Open% = uncontested · Where = the "
                   "zone shots most come from · Avg s = possession length.")

    # ══ §F — PLAY TYPE × DEFENSE cross-tab (the headline overlap) ═════════════
    cx = ctx.cross_pd(g, tid, _off) or {}
    plays, defs = cx.get("plays", []), cx.get("defenses", [])
    if plays and defs:
        st.markdown("<div class='pl-hdr'>Play type × defense — how each set fares "
                    "vs each scheme</div>", unsafe_allow_html=True)
        matrix = cx["matrix"]
        pl_lbl, df_lbl = cx["play_label"], cx["def_label"]
        # z = PPP per (play row × defense col); text = "PPP\n(poss)"; thin cells
        # (poss < min) are greyed via a NaN-ish marker in the annotation, not hidden.
        z, txt = [], []
        for pk in plays:
            zr, tr = [], []
            for dk in defs:
                c = matrix.get(pk, {}).get(dk)
                if c:
                    zr.append(round(c["PPP"], 2))
                    star = "" if c["stable"] else "·"
                    tr.append(f"{c['PPP']:.2f}{star}<br>{c['poss']}p")
                else:
                    zr.append(None)
                    tr.append("")
            z.append(zr)
            tr_txt = tr
            txt.append(tr_txt)
        # good = green: on defense (offense=False) low PPP allowed is good -> reverse.
        hm = go.Figure(go.Heatmap(
            z=z, x=[df_lbl.get(d, d) for d in defs],
            y=[pl_lbl.get(p, p) for p in plays],
            text=txt, texttemplate="%{text}", textfont=dict(size=11),
            colorscale="RdYlGn", reversescale=(not _off),
            zmid=1.0, hoverongaps=False,
            colorbar=dict(title="PPP"),
            hovertemplate="%{y} vs %{x}: %{z} PPP<extra></extra>"))
        style_fig(hm, max(300, 60 + 34 * len(plays)))
        st.plotly_chart(hm, width="stretch", key="def_cross")
        st.caption(
            f"Each cell = PPP when a set call meets a scheme ({cx.get('tagged', 0)} "
            "doubly-tagged shots). A trailing **·** marks a thin cell (< "
            f"{4} poss) — read it as a hint, not a verdict. " +
            ("Green = you defend that set well in that scheme; red = it burns you."
             if not _off else
             "Green = you attack that scheme well with that set; red = it stalls."))
    elif drows:
        st.caption("Tag **both** a play type and a defense on the same shots to "
                   "unlock the play-type × defense cross-tab (the headline overlap).")

    # ══ §G — disruption: turnovers per scheme ════════════════════════════════
    tv = ctx.def_tovs(g, tid, _off) or {}
    tvrows = tv.get("rows", [])
    if tvrows:
        st.markdown("<div class='pl-hdr'>Disruption — turnovers " +
                    ("forced" if not _off else "committed") + " per scheme</div>",
                    unsafe_allow_html=True)
        tfig = go.Figure(go.Bar(
            x=[r["label"] for r in tvrows], y=[r["tovs"] for r in tvrows],
            marker_color=[_FAM_COLOR.get(r["family"], "#8b949e") for r in tvrows],
            marker_line_width=0, text=[r["tovs"] for r in tvrows],
            textposition="outside"))
        tfig.update_yaxes(title="Turnovers " + ("forced" if not _off else "committed"))
        style_fig(tfig, 300)
        st.plotly_chart(tfig, width="stretch", key="def_tovs")
        st.caption("The press/trap value PPP-on-shots can't show — "
                   + ("turnovers your defense forces" if not _off else
                      "turnovers you cough up") + " under each scheme "
                   f"({tv.get('total', 0)} tagged).")

    # ══ §G2 — fouls per scheme (the line-risk read) ══════════════════════════
    fl = ctx.def_fouls(g, tid, _off) or {}
    flrows = fl.get("rows", [])
    if flrows:
        st.markdown("<div class='pl-hdr'>Fouls — " +
                    ("committed" if not _off else "drawn") + " per scheme</div>",
                    unsafe_allow_html=True)
        ffig = go.Figure(go.Bar(
            x=[r["label"] for r in flrows], y=[r["fouls"] for r in flrows],
            marker_color=[_FAM_COLOR.get(r["family"], "#8b949e") for r in flrows],
            marker_line_width=0, text=[r["fouls"] for r in flrows],
            textposition="outside"))
        ffig.update_yaxes(title="Fouls " + ("committed" if not _off else "drawn"))
        style_fig(ffig, 300)
        st.plotly_chart(ffig, width="stretch", key="def_fouls")
        st.caption(
            ("The cost a press/trap pays at the stripe — fouls your defense commits "
             "under each scheme. A scheme that forces TOs but also fouls a lot is a "
             "wash; one that disrupts WITHOUT fouling is gold."
             if not _off else
             "Fouls you draw vs each scheme — where you get to the line. Attack the "
             "schemes that foul you.") + f" ({fl.get('total', 0)} tagged)")
        # disruption-vs-risk one-liner when a scheme both forces TOs AND fouls
        if not _off and tvrows:
            _to = {r["key"]: r["tovs"] for r in tvrows}
            _fo = {r["key"]: r["fouls"] for r in flrows}
            shared = [k for k in _to if k in _fo]
            if shared:
                _net = max(shared, key=lambda k: _to[k] - _fo.get(k, 0))
                st.caption(f"Best disruption-to-foul tradeoff: **{DEF.label(_net)}** "
                           f"({_to[_net]} TOs forced vs {_fo.get(_net, 0)} fouls).")

    # ══ §H — league rank context ═════════════════════════════════════════════
    leaders = ctx.def_leaders(g, _off) or {}
    _lr = []
    for k, blk in leaders.items():
        lead = blk.get("leaders", [])
        mine = next((x for x in lead if x["team_id"] == tid), None)
        if not mine:
            continue
        # best = lowest PPP allowed on D, highest scored on offense
        best = (min(lead, key=lambda x: x["PPP"]) if not _off
                else max(lead, key=lambda x: x["PPP"])) if lead else None
        _lr.append({
            "Defense": blk["label"], "Your PPP": round(mine["PPP"], 2),
            "Pctile": mine.get("pct"),
            "Lg avg": round(blk["lg_ppp"], 2) if blk.get("lg_ppp") is not None else None,
            "Lg best": round(best["PPP"], 2) if best else None,
            "Poss": mine["poss"],
        })
    if _lr:
        st.markdown("<div class='pl-hdr'>League context — you vs the field</div>",
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(_lr).sort_values("Pctile", ascending=False,
                                                   na_position="last"),
                     hide_index=True, width="stretch", column_config={
                         "Your PPP": st.column_config.NumberColumn("Your PPP", format="%.2f"),
                         "Lg avg": st.column_config.NumberColumn("Lg avg", format="%.2f"),
                         "Lg best": st.column_config.NumberColumn("Lg best", format="%.2f"),
                         "Pctile": st.column_config.NumberColumn("Pctile", format="%.0f"),
                     }, key="def_league_rank")
        st.caption("Where this team ranks on each scheme vs every tracked team's "
                   "pool (good-oriented for this side).")

    # ══ §I — our defense vs our offense by scheme ════════════════════════════
    def_rows = ctx.def_view(g, tid, False).get("rows", [])    # we run (allowed)
    off_rows = ctx.def_view(g, tid, True).get("rows", [])     # we face (scored)
    if def_rows and off_rows:
        _d = {r["key"]: r for r in def_rows}
        _o = {r["key"]: r for r in off_rows}
        shared = [k for k in _d if k in _o]
        if shared:
            st.markdown("<div class='pl-hdr'>Our defense vs our offense by scheme"
                        "</div>", unsafe_allow_html=True)
            shared = sorted(shared, key=lambda k: -(_d[k]["poss"] + _o[k]["poss"]))
            labels = [_d[k]["label"] for k in shared]
            cfig = go.Figure()
            cfig.add_trace(go.Bar(name="We allow (run it)",
                                  x=labels, y=[round(_d[k]["PPP"], 2) for k in shared],
                                  marker_color=ctx.BAD, marker_line_width=0))
            cfig.add_trace(go.Bar(name="We score (face it)",
                                  x=labels, y=[round(_o[k]["PPP"], 2) for k in shared],
                                  marker_color=ctx.GOOD, marker_line_width=0))
            cfig.update_layout(barmode="group")
            cfig.update_yaxes(title="PPP")
            style_fig(cfig, 320)
            st.plotly_chart(cfig, width="stretch", key="def_off_def_compare")
            st.caption("Per scheme: PPP we ALLOW running it vs PPP we SCORE facing "
                       "it. Allow more than you score = the scheme is better in "
                       "opponents' hands than yours.")

    # ══ §J — per-player vs defenses faced ════════════════════════════════════
    pdf = ctx.def_players_faced(g) or {}
    _roster = [p for p in (ctx.players or []) if pdf.get(p.get("_pid"))]
    if _roster:
        st.markdown("<div class='pl-hdr'>Per-player — how each scorer handles each "
                    "defense faced</div>", unsafe_allow_html=True)
        _opts = {f"#{p.get('number')} {p.get('name')}": p.get("_pid")
                 for p in _roster}
        who = st.selectbox("Player", list(_opts), key="def_player_pick")
        pid = _opts.get(who)
        row = pdf.get(pid, {})
        for k, c in sorted(row.items(), key=lambda kv: -kv[1]["poss"]):
            val = (f"{c['PPP']:.2f} PPP · {c['FG%'] * 100:.0f}% FG · {c['poss']} poss")
            st.markdown(_pctile_or_thin(c["label"], val, c.get("pct")),
                        unsafe_allow_html=True)
        st.caption("Each scorer's PPP vs each scheme thrown at them, ranked vs the "
                   "league pool of players on that scheme. Higher = handles it well.")
