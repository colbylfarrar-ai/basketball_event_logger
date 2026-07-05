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

import plotly.graph_objects as go
import streamlit as st

import helpers.auth as AUTH
import helpers.defenses as DEF
import helpers.entitlement as ENT
import helpers.playtypes as PT
import helpers.stats as S
import helpers.court as court
from helpers.cards import pctile_bar, glass, dense_table
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
def _render_factors(ff, unit):
    """Gated four-factors table (eFG% · OREB% · TOV% · FT-rate) per scheme.
    `ff` = helpers.breakdown.defense_factors output."""
    from helpers.breakdown import MIN_POSS_DETAIL
    st.markdown(f"<div class='pl-hdr'>Four factors by {unit}</div>",
                unsafe_allow_html=True)
    st.caption(
        f"*Why* each {unit} works, not just PPP — eFG% (shooting), OREB% (second "
        f"chances), TOV% (ball security), FT-rate (getting to the line). Each "
        f"{unit} unlocks at {MIN_POSS_DETAIL} possessions; these splits are noisy "
        "below that, and OREB% needs enough missed-shot boards.")
    rows = (ff or {}).get("rows", [])
    stable = [r for r in rows if r.get("stable")]
    if not stable:
        best = max((r["poss"] for r in rows), default=0)
        st.info(f"Not enough data yet — the four-factors breakdown unlocks at "
                f"{MIN_POSS_DETAIL} possessions per {unit} (most so far: {best}). "
                "It fills in automatically as you tag plays.")
        return
    def _pct(v):
        return f"{v * 100:.0f}%" if v is not None else "—"
    st.markdown(dense_table([{
        unit.title(): r["label"], "Poss": r["poss"], "PPP": f"{r['PPP']:.2f}",
        "eFG%": _pct(r["eFG"]), "OREB%": _pct(r["OREB%"]),
        "TOV%": _pct(r["TOV%"]), "FT-rate": f"{r['FTr']:.2f}",
    } for r in stable]), unsafe_allow_html=True)
    thin = sorted((r for r in rows if not r.get("stable")),
                  key=lambda r: r["poss"], reverse=True)
    if thin:
        st.caption(f"Building toward {MIN_POSS_DETAIL}: " + " · ".join(
            f"{r['label']} {r['poss']}" for r in thin[:6]))


def _render_scheme_fingerprint(ctx, g, tid, off, drows, prof):
    """Scheme fingerprint — the headline 'what each scheme gives up' board: one row
    per scheme with possession-correct PPP, the four factors (eFG · OREB% · TOV%)
    + the four-factor expected PPP, rim/three finishing allowed, and the shot-mix.
    The richest, highest-quality scheme table, so it leads the tab.

    PPP is POSSESSION-CORRECT (shots + tagged turnovers) so it matches the go-to /
    take-away chips and the efficiency table — the def_profiles `PPP` is shot-only
    and used to disagree (chip vs table mismatch)."""
    if not prof:
        return
    from helpers.team_analytics import ZONE_LABELS as _ZL
    st.markdown("<div class='pl-hdr'>Scheme fingerprint — what each gives up"
                "</div>", unsafe_allow_html=True)
    _byk = {r["key"]: r for r in drows}
    # four-factors merge (OREB% allowed + FT-rate → 4F-PPP), possession-correct
    _fbyk = {}
    if getattr(ctx, "factors", None):
        _fbyk = {r["key"]: r
                 for r in (ctx.factors(g, tid, off) or {}).get("rows", [])}

    # go-to / take-away chips (best / worst by percentile, possession-correct PPP)
    ranked = [r for r in drows if r.get("pct") is not None and r["poss"] >= 8]
    if ranked:
        best = max(ranked, key=lambda r: r["pct"])
        worst = min(ranked, key=lambda r: r["pct"])
        cc = st.columns(2)
        cc[0].markdown(glass(
            "Best scheme", best["label"],
            f"{best['PPP']:.2f} PPP · {best['pct']}th pct · {best['poss']} poss",
            color=best.get("color", "var(--text)")), unsafe_allow_html=True)
        if worst["key"] != best["key"]:
            cc[1].markdown(glass(
                "Leakiest", worst["label"],
                f"{worst['PPP']:.2f} PPP · {worst['pct']}th pct · "
                f"{worst['poss']} poss", color=worst.get("color", "var(--text)")),
                unsafe_allow_html=True)

    def _pctv(v):
        return f"{v * 100:.0f}%" if v is not None else None

    def _fourf_ppp(f):
        if not f:
            return None
        v = S.four_factor_ppp(f.get("eFG"), f.get("TOV%"),
                              f.get("OREB%"), f.get("FTr"))
        return f"{v:.2f}" if v is not None else None

    rows_out = []
    for p in sorted(prof.values(),
                    key=lambda p: -(_byk.get(p["key"], {}).get("poss")
                                    or p["poss"])):
        k = p["key"]
        nb, fb = _byk.get(k, {}), _fbyk.get(k, {})
        ppp = nb.get("PPP", fb.get("PPP"))          # possession-correct
        rows_out.append({
            "Defense": p["label"],
            "Poss": nb.get("poss", p["poss"]),
            "Share": _pctv(nb.get("share")),
            "PPP": f"{ppp:.2f}" if ppp is not None else f"{p['PPP']:.2f}",
            "4FPPP": _fourf_ppp(fb),
            "TO%": _pctv(nb.get("TO%")),
            "eFG%": f"{p.get('eFG', 0) * 100:.0f}%",
            "OREB%": _pctv(fb.get("OREB%")),
            "3PA%": f"{p['3PA_rate'] * 100:.0f}%",
            "Rim%": f"{p['rim_rate'] * 100:.0f}%",
            "Rim FG%": (f"{p['rim_FG%'] * 100:.0f}%"
                        if p.get("rim_FG%") is not None else "—"),
            "3P%": (f"{p['3P%'] * 100:.0f}%"
                    if p.get("3P%") is not None else "—"),
            "Assisted%": f"{p['ast_rate'] * 100:.0f}%",
            "Open%": f"{p['open_rate'] * 100:.0f}%",
            "Where": _ZL.get(p["top_zone"], "—") if p["top_zone"] else "—",
            "Avg s": (f"{p['avg_secs']:.1f}"
                      if p["avg_secs"] is not None else None),
        })
    st.markdown(dense_table(rows_out), unsafe_allow_html=True)
    st.caption(
        "PPP / Poss / Share / TO% count possessions (shots + tagged turnovers) — "
        "the possession-correct efficiency, matching the chips. **4FPPP** = "
        "expected PPP from the four factors alone (eFG · OREB% · TOV% · FT-rate); "
        "the gap vs PPP is shot-making the averages can't see. **OREB%** = "
        + ("offensive boards the scheme allows" if not off else "our offensive "
           "boards vs it") + ". 3PA% / Rim% = shot-type share " +
        ("allowed" if not off else "you get") + " · Rim FG% / 3P% = finishing at "
        "the rim / from three vs that scheme · Assisted% = off a pass · Open% = "
        "uncontested · Where = the zone shots most come from · Avg s = poss length.")


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

    # ── §A — side toggle (drives the court below AND every table) ────────────
    _side = seg("Side of the ball", ["Our defense", "Vs defenses we face"],
                key="def_side") or "Our defense"
    _off = _side != "Our defense"     # offense=True => the defenses we FACE

    # ══ SHOT CHART — BOTH sides (shots-against on D, shots-for on offense) ════
    # Our defense -> the opponents' located shots vs each scheme WE ran (where
    # they attack our 2-3 / man — "shots against"). Vs defenses we face -> our
    # OWN located shots vs each scheme we faced ("shots for"). Same court UI as
    # Play Style; lives above the no-tags gate so it shows from day one, and the
    # by-scheme filter lights up as you tag.
    if _off:
        shots = list(ctx.located_team(tid, ctx.tracked_ids) or [])
        _what = "our shots by the defense we faced"
        _filterhelp = "Filter the court to one defense you faced."
    else:
        shots = list(ctx.located_allowed(tid, ctx.tracked_ids) or [])
        _what = "shots we allowed by the scheme we ran"
        _filterhelp = "Filter the court to one scheme you ran."
    st.markdown(f"<div class='pl-hdr'>Shot chart — {_what}</div>",
                unsafe_allow_html=True)
    if not shots:
        st.caption("No tap-located shots for this side yet — tap shot spots in the "
                   "Game Tracker to unlock the court.")
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
                title=f"Every shot, colored by scheme — {_what}")
            if n:
                st.plotly_chart(fig, width="stretch", key="def_court_facet")
                st.caption("Each colour = a scheme · filled = make, open = miss · "
                           "grey = untagged. Spot how the looks cluster vs each "
                           "scheme.")
            else:
                st.caption("No located shots to plot.")
        else:
            pick = st.selectbox("Defense", ["All defenses"] + list(lbl2key),
                                key="def_court_pick", disabled=not lbl2key,
                                help=_filterhelp)
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
        if not lbl2key:
            st.caption("Showing every located shot — tag the **Defense** on shots "
                       "in the tracker (it's sticky) to filter this court by scheme.")
        elif n_untagged:
            st.caption(f"{n_untagged}/{len(shots)} located shots are untagged — set "
                       "the defense in the tracker to sharpen the by-scheme court.")

    # ── coverage line for the analytical sections below ──────────────────────
    dv = ctx.def_view(g, tid, _off)
    drows = dv.get("rows", [])
    st.caption(
        f"{'Defenses we ran (shots we allowed)' if not _off else 'Defenses we faced (our shots)'}: "
        f"{dv.get('total_tagged', 0)} tagged · {dv.get('untagged', 0)} untagged. "
        f"Percentile is good-oriented "
        f"({'fewer points allowed' if not _off else 'more points scored'} = higher rank).")

    # ══ on-ball defenders (the `guarded_by_id` tag — independent of the scheme
    #    tag, so it sits ABOVE the no-scheme-tags early return below). Dormant
    #    until coaches tap WHO contested; fills in as coverage grows. ═══════════
    if getattr(ctx, "defender_profiles", None):
        _dp = ctx.defender_profiles(g, tid) or {}
        _drows = _dp.get("rows", [])
        if _drows:
            st.markdown("<div class='pl-hdr'>On-ball defenders — FG% allowed when "
                        "contesting</div>", unsafe_allow_html=True)
            st.markdown(dense_table([{
                "Defender": r["name"], "Contested": r["contested"],
                "FG% allowed": f"{r['FGpct'] * 100:.1f}%",
                "PPS allowed": f"{r['PPS']:.2f}",
                "2P% allowed": f"{r['twos_pct'] * 100:.1f}%",
                "3P% allowed": f"{r['threes_pct'] * 100:.1f}%",
            } for r in _drows]), unsafe_allow_html=True)
            st.caption("Lower FG%/PPS allowed = better on-ball defense. "
                       + _dp.get("note", ""))

    if not drows and dv.get("total_tagged", 0) == 0:
        st.info("No defense tags on these shots yet — set the **Defense** "
                "(man, 2-3, 1-3-1, presses, traps…) in the Game Tracker; it's "
                "sticky, so one tap covers a whole stretch. This tab fills in as "
                "you tag.")
        return

    # ══ §E (PROMOTED) — SCHEME FINGERPRINT: the richest scheme table leads the
    # tab, above the plainer family / efficiency / frequency tables that repeat a
    # subset of it. `prof` is computed once here and reused by §F below. ─────────
    prof = ctx.def_profiles(g, tid, _off) or {}
    _render_scheme_fingerprint(ctx, g, tid, _off, drows, prof)

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
        st.markdown(dense_table([{
            "Defense": r["label"], "Poss": r["poss"],
            "Share": f"{r['share'] * 100:.0f}%",
            "PPP": f"{r['PPP']:.2f}",
            "TO%": (f"{r['TO%'] * 100:.0f}%"
                    if r.get("TO%") is not None else None),
            "FG%": f"{r['FG%'] * 100:.0f}%",
            "3P%": f"{r.get('3P%', 0) * 100:.0f}%",
            "eFG%": f"{r.get('eFG', 0) * 100:.0f}%",
            "ScEff": f"{r.get('SCE', 0) * 100:.0f}%",
            "Tier": r["tier"],
        } for r in drows]), unsafe_allow_html=True)
        st.caption("Poss = shots + tagged turnovers · PPP = points/possession · "
                   "TO% = " + ("turnovers this scheme forces" if not _off else
                               "how often you cough it up vs this scheme") +
                   " · eFG% weights 3s · **ScEff** = scoring efficiency · Share "
                   "= % of tagged possessions. Rank is good-oriented for this "
                   "side.")

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

    # (§E scheme fingerprint was promoted above §B — `prof` is computed there.)

    # ── §E2 — FOUR FACTORS per scheme (gated ~100 poss) ──────────────────────
    if getattr(ctx, "factors", None):
        _render_factors(ctx.factors(g, tid, _off), "defense")

    # ══ §F — PLAY TYPE × DEFENSE cross-tab (the headline overlap) ═════════════
    cx = ctx.cross_pd(g, tid, _off) or {}
    plays, defs = cx.get("plays", []), cx.get("defenses", [])
    if plays and defs:
        matrix = cx["matrix"]
        pl_lbl, df_lbl = cx["play_label"], cx["def_label"]
        # z = PPP per (play row × defense col); text = "PPP\n(poss)". Thin cells
        # (poss < min, ~10) are HIDDEN, not greyed — single-digit-possession PPP is
        # noise dressed as a Synergy grid, and showing it costs more trust than it
        # adds. A cell renders only when its sample is stable.
        z, txt, _shown = [], [], 0
        for pk in plays:
            zr, tr = [], []
            for dk in defs:
                c = matrix.get(pk, {}).get(dk)
                if c and c["stable"]:
                    zr.append(round(c["PPP"], 2))
                    tr.append(f"{c['PPP']:.2f}<br>{c['poss']}p")
                    _shown += 1
                else:
                    zr.append(None)
                    tr.append("")
            z.append(zr)
            txt.append(tr)
        if _shown:
            st.markdown("<div class='pl-hdr'>Play type × defense — how each set fares "
                        "vs each scheme</div>", unsafe_allow_html=True)
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
                f"Each cell = PPP when a set call meets a scheme, shown only where "
                f"≥10 possessions back it (thinner cells are hidden — too noisy to "
                f"trust). {cx.get('tagged', 0)} doubly-tagged shots so far. " +
                ("Green = you defend that set well in that scheme; red = it burns you."
                 if not _off else
                 "Green = you attack that scheme well with that set; red = it stalls."))
        else:
            st.caption("Not enough doubly-tagged shots yet — a play type × defense "
                       "cell needs ≥10 possessions to show. Keep tagging both on the "
                       "same shots to unlock this grid.")
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

    # ══ §H — league rank context (cross-team → Coaches' Co-op only) ═══════════
    # Lg avg / Lg best / Pctile compare this team against every tracked team, so the
    # block is a cross-team aggregate: gated on league-wide (co-op). A solo coach
    # still sees their own per-scheme PPP in the tables above; empty leaders here
    # makes the "you vs the field" table self-skip.
    leaders = ((ctx.def_leaders(g, _off) or {})
               if ENT.viewer_is_league_wide(AUTH.current_user()) else {})
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
            "Defense": blk["label"], "Your PPP": f"{mine['PPP']:.2f}",
            "Pctile": (f"{mine['pct']:.0f}"
                       if mine.get("pct") is not None else None),
            "_p": mine.get("pct") or -1,
            "Lg avg": (f"{blk['lg_ppp']:.2f}"
                       if blk.get("lg_ppp") is not None else None),
            "Lg best": f"{best['PPP']:.2f}" if best else None,
            "Poss": mine["poss"],
        })
    if _lr:
        st.markdown("<div class='pl-hdr'>League context — you vs the field</div>",
                    unsafe_allow_html=True)
        _lr.sort(key=lambda r: -r["_p"])
        st.markdown(dense_table(
            _lr, columns=["Defense", "Your PPP", "Pctile", "Lg avg", "Lg best",
                          "Poss"]), unsafe_allow_html=True)
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
