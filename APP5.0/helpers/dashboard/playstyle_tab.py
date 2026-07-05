"""
playstyle_tab.py — the Team Dashboard "Play Style" super-tab (Charts → Play Style).

The deep, advanced-analytics home for the explicit one-tap ``play_type`` set-call
tag. A pure renderer (the scout_tab.py / player_card.py pattern): all heavy data
arrives via pre-bound, page-cached callables on ``ctx`` so caching stays on the
page and this module is testable in isolation (AppTest.from_function — full pages
can't be tested past the native st.login gate, a module render(ctx) can).

Sections, in order:
  A header + offense/defense toggle + coverage
  B SHOT CHART BY PLAY STYLE (filter / facet color-by-set / small-multiples)
  C tagged set-call PPP percentile bars + tier + detail table
  D frequency × efficiency quadrant
  E set fingerprint (3PA/rim/zone/assisted/open/tempo) + go-to / take-away chips
  F per-set shot diet + zone heat + distance buckets
  G handler-vs-roller / roll-vs-pop role splits
  H hand-off & inbounds feeder hubs
  I inferred tempo/creation cross-read (the Synergy cross-check)
  J league rank context (you vs league best / avg)
  K offense vs defense compare
  L per-player play-style drill-down
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.playtypes as PT
import helpers.stats as S
import helpers.team_analytics as TA
import helpers.court as court
from helpers.cards import pctile_bar, glass, dense_table
from helpers.ui import empty_state, seg, style_fig

_PTL = dict(PT.NAMED_PLAY_TYPES)
_ZL = TA.ZONE_LABELS
_ZONES = ("LC", "LW", "C", "RW", "RC")
# Categorical palette for the distribution pie (identity colour per set — kept
# separate from the tier colours, which encode performance not which set it is).
_PALETTE = ["#58a6ff", "#3fb950", "#bc8cff", "#ff5db1", "#f0a500", "#e74c3c",
            "#2dd4bf", "#f97583", "#a3e635", "#fbbf24", "#22d3ee", "#c084fc",
            "#7ee787"]


# ── small shared helpers ─────────────────────────────────────────────────────
def _zone_grid(shots):
    """Located shots → {(zone, 2|3): {FGA, FGM, pct}} for court.shot_chart."""
    g = {(z, t): {"FGA": 0, "FGM": 0} for z in _ZONES for t in (2, 3)}
    for s in shots:
        z = s.get("zone")
        t = 3 if (s.get("value") == 3) else 2
        if z in _ZONES:
            c = g[(z, t)]
            c["FGA"] += 1
            if s.get("make"):
                c["FGM"] += 1
    return {k: {**v, "pct": (v["FGM"] / v["FGA"] if v["FGA"] else 0.0)}
            for k, v in g.items()}


def _present_sets(shots):
    """Ordered {label: key} for the set calls actually present in ``shots``."""
    present = {s.get("play_type") for s in shots if s.get("play_type")}
    return {_PTL[k]: k for k, _ in PT.NAMED_PLAY_TYPES if k in present}


def _pctile_or_thin(label, value_str, pct):
    """Percentile bar, or the 'thin sample' row when pct is None."""
    if pct is None:
        return (f"<div class='pl-pct'><div class='pl-pct-top'>"
                f"<span class='pl-pct-lbl'>{label}</span>"
                f"<span class='pl-pct-val'>{value_str} · "
                f"<span style='color:#8b949e'>thin sample</span>"
                f"</span></div></div>")
    return pctile_bar(label, value_str, round(pct))


def _profile_howline(pr):
    """Gender-neutral 'how they score this set' line from a shot profile, with
    the inherent-attribute suppression (a spot-up IS a 3, an iso IS a rim
    attack — don't restate the tag)."""
    if not pr:
        return ""
    bits = []
    key = pr.get("key")
    if pr.get("3PA_rate") is not None and not PT.is_inherent(key, "three"):
        bits.append(f"{pr['3PA_rate'] * 100:.0f}% 3PA")
    if pr.get("rim_rate") is not None and not PT.is_inherent(key, "rim"):
        bits.append(f"{pr['rim_rate'] * 100:.0f}% rim")
    if pr.get("ast_rate") is not None:
        bits.append(f"{pr['ast_rate'] * 100:.0f}% assisted")
    if pr.get("open_rate") is not None:
        bits.append(f"{pr['open_rate'] * 100:.0f}% open")
    tz = pr.get("top_zone")
    if tz:
        bits.append(f"mostly {_ZL.get(tz, tz).lower()}")
    return " · ".join(bits)


# ══════════════════════════════════════════════════════════════════════════════
def _render_turnovers(tv, off):
    """Giveaway-kind breakdown from the explicit ``turnover_type`` tag
    (helpers/turnovers). ``off`` mirrors the tab's side toggle: True = the
    team's own giveaways, False = the takeaways it forces."""
    import helpers.turnovers as TOV
    st.markdown("<div class='pl-hdr'>Turnover profile — "
                f"{'giveaways' if off else 'takeaways forced'}</div>",
                unsafe_allow_html=True)
    tv = tv or {}
    rows = tv.get("rows", [])
    if not rows:
        st.caption(
            "No turnover-kind tags yet — tag the **Type** on turnovers (bad "
            "pass, drive, held ball, shot clock, travel) in the Game Tracker "
            "or the phone tracker's detailed mode and this breakdown fills in. "
            f"({tv.get('total', 0)} untagged turnover(s) so far.)")
        return
    st.markdown(dense_table([{
        "Kind": r["label"], "TOs": r["n"],
        "Share": f"{r['share'] * 100:.0f}%", "Stolen": r["stolen"],
        "Top set calls": " · ".join(
            f"{_PTL.get(k, k)} ×{n}" for k, n in list(r["sets"].items())[:3])
        or "—",
    } for r in rows], num_cols=("TOs", "Share", "Stolen")),
        unsafe_allow_html=True)
    st.caption(
        f"{tv.get('total_tagged', 0)} tagged · {tv.get('untagged', 0)} untagged "
        f"{'giveaways' if off else 'forced turnovers'}. **Stolen** = live-ball "
        "takeaway credited to a defender. **Top set calls** = the play_type "
        "extra layer — which sets the ball was lost in (a cut-TO is tagged as "
        "the set, the kind says how it was lost).")


# ══════════════════════════════════════════════════════════════════════════════
def _render_factors(ff, unit):
    """Gated four-factors table (eFG% · OREB% · TOV% · FT-rate) per set/scheme.
    `ff` = helpers.breakdown.play_type_factors / defense_factors output."""
    from helpers.breakdown import MIN_POSS_DETAIL
    st.markdown(f"<div class='pl-hdr'>Four factors by {unit}</div>",
                unsafe_allow_html=True)
    st.caption(
        f"*Why* each {unit} works, not just PPP — eFG% (shooting), OREB% (second "
        f"chances), TOV% (ball security). FT-rate is dropped here — free-throw "
        f"trips aren't tied to a set call in the tracking. Each {unit} unlocks "
        f"at {MIN_POSS_DETAIL} possessions; these splits are noisy below that, "
        "and OREB% needs enough missed-shot boards.")
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
        "TOV%": _pct(r["TOV%"]),
    } for r in stable]), unsafe_allow_html=True)
    thin = sorted((r for r in rows if not r.get("stable")),
                  key=lambda r: r["poss"], reverse=True)
    if thin:
        st.caption(f"Building toward {MIN_POSS_DETAIL}: " + " · ".join(
            f"{r['label']} {r['poss']}" for r in thin[:6]))


def _render_fingerprint(ctx, g, tid, off, nrows, prof):
    """Set fingerprint — the headline 'what each set produces' board: one row per
    set with possession-correct PPP, the four factors (eFG · OREB% · TOV%) + the
    four-factor expected PPP, plus the shot-mix, and go-to / take-away chips. The
    richest, highest-quality set table, so it leads the tab (above the plainer
    four-factors / efficiency / frequency tables that repeat a subset of it).

    PPP here is POSSESSION-CORRECT (shots + tagged turnovers) so it matches the
    chips and the efficiency table — the set_profiles `PPP` is shot-only and used
    to disagree (the go-to chip read 0.92 while the table row read 1.11)."""
    if not prof:
        return
    st.markdown("<div class='pl-hdr'>Set fingerprint — what each set produces"
                "</div>", unsafe_allow_html=True)
    _byk = {r["key"]: r for r in nrows}
    # four-factors merge (OREB% + FT-rate → 4F-PPP), possession-correct like chips
    _fbyk = {}
    if getattr(ctx, "factors", None):
        _fbyk = {r["key"]: r
                 for r in (ctx.factors(g, tid, off) or {}).get("rows", [])}

    # go-to (best ranked) / take-away (worst ranked) chips from the §C ranks
    ranked = [r for r in nrows if r["pct"] is not None and r["poss"] >= 8]
    if ranked:
        best = max(ranked, key=lambda r: r["pct"])
        worst = min(ranked, key=lambda r: r["pct"])
        cc = st.columns(2)
        cc[0].markdown(glass(
            "Go-to set", best["label"],
            f"{best['PPP']:.2f} PPP · {best['pct']}th pct · {best['poss']} poss",
            color=best["color"]), unsafe_allow_html=True)
        if worst["key"] != best["key"]:
            cc[1].markdown(glass(
                "Take away", worst["label"],
                f"{worst['PPP']:.2f} PPP · {worst['pct']}th pct · "
                f"{worst['poss']} poss", color=worst["color"]),
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
            "Set": p["label"],
            "Poss": nb.get("poss", p["poss"]),
            "Share": _pctv(nb.get("share")),
            "PPP": f"{ppp:.2f}" if ppp is not None else f"{p['PPP']:.2f}",
            "4FPPP": _fourf_ppp(fb),
            "TO%": _pctv(nb.get("TO%")),
            "eFG%": f"{p.get('eFG', 0) * 100:.0f}%",
            "OREB%": _pctv(fb.get("OREB%")),
            "ScEff": f"{p.get('SCE', 0) * 100:.0f}%",
            "3PA%": f"{p['3PA_rate'] * 100:.0f}%",
            "Rim%": f"{p['rim_rate'] * 100:.0f}%",
            "Assisted%": f"{p['ast_rate'] * 100:.0f}%",
            "Open%": f"{p['open_rate'] * 100:.0f}%",
            "Where": _ZL.get(p["top_zone"], "—") if p["top_zone"] else "—",
            "Avg s": (f"{p['avg_secs']:.1f}"
                      if p["avg_secs"] is not None else None),
        })
    st.markdown(dense_table(rows_out), unsafe_allow_html=True)
    st.caption(
        "PPP / Poss / Share / TO% count possessions (shots + tagged turnovers) — "
        "the possession-correct efficiency, matching the go-to/take-away chips. "
        "**4FPPP** = expected PPP from the four factors alone (eFG · OREB% · TOV% "
        "· FT-rate); the gap vs PPP is shot-making/sequencing the averages can't "
        "see. **OREB%** unlocks with enough missed-shot boards. eFG% weights 3s · "
        "ScEff = scoring efficiency · 3PA% / Rim% = shot-type share · Assisted% = "
        "off a pass · Open% = uncontested · Where = the zone the set most lives in "
        "· Avg s = poss length.")


@st.fragment
def render(ctx):
    """Render the Play Style super-tab. ``ctx`` carries plain values + pre-bound
    page-cached callables (see module docstring / the page call site)."""
    g, tid = ctx.gender, ctx.team_id
    st.markdown("<div class='pl-hdr'>Play style — the explicit set-call deep dive"
                "</div>", unsafe_allow_html=True)
    st.caption(
        "The advanced home for the one-tap **Play type** tag: how each set call "
        "scores, where it shoots from, who runs it, and how it ranks vs the "
        "league. A shot ends a possession, so PPP = points per shot.")

    if not getattr(ctx, "has_tracked", False):
        empty_state("No tracked games yet",
                    "Track a game in the Game Tracker and tag shots with a Play "
                    "type to unlock the play-style deep dive.", icon="🎬")
        return

    # ── §A — side toggle + coverage ──────────────────────────────────────────
    _off = (seg("Side of the ball", ["Offense", "Defense"], key="ps_side")
            or "Offense") == "Offense"
    nv = ctx.named_view(g, tid, _off)
    nrows = nv.get("rows", [])
    st.caption(
        f"{'Own' if _off else 'Opponent'} tagged shots: {nv.get('total_tagged', 0)} "
        f"tagged · {nv.get('untagged', 0)} untagged. Percentile is good-oriented "
        f"({'higher PPP' if _off else 'fewer points allowed'} = higher rank).")

    if not nrows and nv.get("total_tagged", 0) == 0:
        st.info("No play-type tags on these shots yet — tap an optional **Play "
                "type** (Pick & roll, Iso, Transition…) on shots in the Game "
                "Tracker and this whole tab fills in. The inferred tempo/creation "
                "cross-read below works without tags.")

    # ══ §E (PROMOTED) — SET FINGERPRINT: the richest set table leads the tab, so
    # the coach sees it before scrolling past the plainer four-factors / efficiency
    # / frequency tables that repeat a subset of it. `prof` is computed here once
    # and reused by the per-set drill (§F) further down. ────────────────────────
    prof = ctx.set_profiles(g, tid, _off) or {}
    _render_fingerprint(ctx, g, tid, _off, nrows, prof)

    # ── §A2 — FOUR FACTORS per set (gated ~100 poss) ─────────────────────────
    if getattr(ctx, "factors", None):
        _render_factors(ctx.factors(g, tid, _off), "play type")

    # ── §A3 — TURNOVER PROFILE (explicit turnover-type tag) ─────────────────
    if getattr(ctx, "turnover_types", None):
        _render_turnovers(ctx.turnover_types(g, tid, _off), _off)

    # ══ §B — SHOT CHART BY PLAY STYLE (headline) ═════════════════════════════
    st.markdown("<div class='pl-hdr'>Shot chart by play style</div>",
                unsafe_allow_html=True)
    shots = list(ctx.located_team(tid, ctx.tracked_ids) or [])
    if _off is False:
        shots = []  # located_team is own-shots only; defense has no court here
    if not shots:
        st.caption("No tap-located shots for this view yet — tap shot spots in "
                   "the Game Tracker to unlock the court (the tables below still "
                   "work from zone data)." if _off else
                   "The shot-by-play-style court shows your OWN shots — flip to "
                   "Offense to see it.")
    else:
        lbl2key = _present_sets(shots)
        _mode = seg("Chart mode",
                    ["Filter to one set", "Facet (color by set)", "Small multiples"],
                    key="ps_chart_mode") or "Filter to one set"
        n_untagged = sum(1 for s in shots if not s.get("play_type"))

        if _mode == "Facet (color by set)":
            fig, n = court.shot_map_grouped(
                shots, group_key="play_type", labels=_PTL,
                title="Every shot, colored by set call")
            if n:
                st.plotly_chart(fig, width="stretch", key="ps_court_facet")
                st.caption("Each colour = a tagged set call · filled = make, open "
                           "= miss. Grey = untagged. Spot how a set's looks cluster "
                           "on the floor.")
            else:
                st.caption("No located shots to plot.")
        elif _mode == "Small multiples":
            keys = [k for _l, k in lbl2key.items()]
            by = {k: [s for s in shots if s.get("play_type") == k] for k in keys}
            keys = sorted(keys, key=lambda k: -len(by[k]))[:9]
            if not keys:
                st.caption("No tagged sets to break out — tag shots in the tracker.")
            for i in range(0, len(keys), 3):
                cols = st.columns(3)
                for col, k in zip(cols, keys[i:i + 3]):
                    fig, n = court.shot_map(by[k], title=_PTL.get(k, k),
                                            height=300, show_misses=True)
                    with col:
                        if n:
                            st.plotly_chart(fig, width="stretch",
                                            key=f"ps_court_sm_{k}")
                        m = sum(1 for s in by[k] if s.get("make"))
                        col.caption(f"{m}/{len(by[k])} · "
                                    f"{100 * m / max(len(by[k]), 1):.0f}%")
        else:  # Filter to one set
            pick = st.selectbox("Play style", ["All sets"] + list(lbl2key),
                                key="ps_court_pick", disabled=not lbl2key,
                                help="Filter the court to one tagged set call.")
            _pk = lbl2key.get(pick)
            fshots = [s for s in shots if s.get("play_type") == _pk] if _pk else shots
            view = seg("View", ["Shot map", "Hexbin (PPS)", "Quality (POE)"],
                       key="ps_court_view") or "Shot map"
            who = pick if _pk else "All sets"
            if view.startswith("Shot"):
                fig, n = court.shot_map(fshots, title=f"{who} · shot map")
            elif view.startswith("Hexbin"):
                fig, n = court.shot_hexbin(fshots, title=f"{who} · volume · PPS",
                                           league_pps=ctx.league_pps(g))
            else:
                fig, n = court.shot_hexbin(fshots, title=f"{who} · points over expected",
                                           model=ctx.shot_model(g), mode="poe")
            if n:
                st.plotly_chart(fig, width="stretch", key="ps_court_filter")
            else:
                st.caption("No located shots for this filter.")
            _db = S.distance_buckets(fshots)
            if _db:
                st.caption("By length — " + S.distance_buckets_caption(_db))
        if n_untagged:
            st.caption(f"{n_untagged}/{len(shots)} located shots are untagged — "
                       "tag them in the tracker to sharpen the by-set views.")

    # ══ §C — tagged set-call PPP percentile bars + table ═════════════════════
    st.markdown("<div class='pl-hdr'>Set-call efficiency — ranked vs the league"
                "</div>", unsafe_allow_html=True)
    if nrows:
        for r in nrows:
            val = (f"{r['PPP']:.2f} PPP · {r['FG%'] * 100:.0f}% FG · "
                   f"{r['poss']} poss")
            st.markdown(_pctile_or_thin(r["label"], val, r["pct"]),
                        unsafe_allow_html=True)
        st.markdown(dense_table([{
            "Play call": r["label"], "Poss": r["poss"],
            "Share": f"{r['share'] * 100:.0f}%",
            "PPP": f"{r['PPP']:.2f}",
            "TO%": (f"{r['TO%'] * 100:.0f}%"
                    if r.get("TO%") is not None else None),
            "FD": r.get("FD", 0),
            "FG%": f"{r['FG%'] * 100:.0f}%",
            "3P%": f"{r.get('3P%', 0) * 100:.0f}%",
            "eFG%": f"{r.get('eFG', 0) * 100:.0f}%",
            "ScEff": f"{r.get('SCE', 0) * 100:.0f}%",
            "Tier": r["tier"],
        } for r in nrows]), unsafe_allow_html=True)
        st.caption("PPP = points/possession (turnover possessions included once "
                   "TOs are tagged) · TO% = the set's give-it-away rate · FD = "
                   "fouls drawn in the set · eFG% weights 3s · **ScEff** = scoring "
                   "efficiency (FG points ÷ max possible) · Share = % of tagged "
                   "possessions (shots + turnovers).")

        # ── play-call distribution pie ──────────────────────────────────────
        st.markdown("<div class='pl-hdr'>Play-call distribution</div>",
                    unsafe_allow_html=True)
        _ord = sorted(nrows, key=lambda r: -r["poss"])
        pie = go.Figure(go.Pie(
            labels=[r["label"] for r in _ord],
            values=[r["poss"] for r in _ord],
            marker=dict(colors=[_PALETTE[i % len(_PALETTE)]
                                for i in range(len(_ord))],
                        line=dict(color="#0d1117", width=2)),
            textinfo="label+percent", sort=False, hole=0.55,
            hovertemplate="%{label}: %{value} poss · %{percent}<extra></extra>"))
        pie.update_layout(
            showlegend=False, height=380, paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=20, b=10),
            annotations=[dict(text=f"<b>{nv.get('total_tagged', 0)}</b><br>tagged",
                              x=0.5, y=0.5, showarrow=False,
                              font=dict(size=15, color="#c9d1d9"))])
        st.plotly_chart(pie, width="stretch", key="ps_named_pie")
        st.caption(f"How the {'offense' if _off else 'defense'} breaks down by "
                   "tagged set call (by possessions).")
    else:
        st.caption("No tagged set calls yet for this side.")

    # ══ §D — frequency × efficiency quadrant ═════════════════════════════════
    if nrows:
        st.markdown("<div class='pl-hdr'>Frequency × efficiency</div>",
                    unsafe_allow_html=True)
        qx = [r["share"] * 100 for r in nrows]
        qy = [r["PPP"] for r in nrows]
        qsz = [r["poss"] for r in nrows]
        qmax = max(qsz) or 1
        qposs = sum(qsz)
        qppp = (sum(r["PPP"] * r["poss"] for r in nrows) / qposs) if qposs else 0.0
        qsh = (sum(qx) / len(qx)) if qx else 0.0
        qfig = go.Figure(go.Scatter(
            x=qx, y=qy, mode="markers+text",
            text=[r["label"] for r in nrows], textposition="top center",
            textfont=dict(size=10),
            marker=dict(size=[12 + 30 * (p / qmax) for p in qsz],
                        sizemode="diameter", color=[r["color"] for r in nrows],
                        line=dict(width=1, color="#0d1117"), opacity=0.9),
            hovertext=[f"{r['label']}: {r['PPP']:.2f} PPP · {r['poss']} poss · "
                       f"{r['share'] * 100:.0f}% share" for r in nrows],
            hoverinfo="text"))
        qfig.add_vline(x=qsh, line=dict(color=ctx.GREY, dash="dot"))
        qfig.add_hline(y=qppp, line=dict(color=ctx.GREY, dash="dot"))
        qfig.update_xaxes(title="Share of tagged shots (%)")
        qfig.update_yaxes(title="PPP")
        style_fig(qfig, 380)
        st.plotly_chart(qfig, width="stretch", key="ps_named_quad")
        st.caption("Top-right = bread-and-butter (keep) · bottom-right = "
                   "over-reliance (a set called a lot that isn't working) · "
                   "top-left = under-used gem (call it more) · bottom-left = junk. "
                   "Lines = your average share & PPP.")

    # ══ §F — per-set shot diet + zone heat + length ══════════════════════════
    # (§E set fingerprint was promoted above §A2 — `prof` is computed there.)
    if prof and shots:
        st.markdown("<div class='pl-hdr'>Drill into one set</div>",
                    unsafe_allow_html=True)
        keys = [k for _l, k in _present_sets(shots).items()]
        if keys:
            spick = st.selectbox(
                "Set", [_PTL.get(k, k) for k in keys], key="ps_set_drill")
            skey = {_PTL.get(k, k): k for k in keys}.get(spick)
            sshots = [s for s in shots if s.get("play_type") == skey]
            pr = prof.get(skey)
            if pr:
                st.caption(_profile_howline(pr) or "—")
            d1, d2 = st.columns([1, 1])
            with d1:
                if pr:
                    cats = ["Paint 2", "Mid 2", "3-pt"]
                    vals = [round(pr["rim_rate"] * pr["poss"]),
                            round(pr["mid_rate"] * pr["poss"]),
                            round(pr["3PA_rate"] * pr["poss"])]
                    dfig = go.Figure(go.Bar(
                        x=cats, y=vals, marker_color=[ctx.ACCENT, ctx.PURPLE, ctx.BLUE],
                        marker_line_width=0, text=vals, textposition="outside"))
                    dfig.update_yaxes(title="Attempts")
                    style_fig(dfig, 300)
                    st.plotly_chart(dfig, width="stretch", key="ps_set_diet")
            with d2:
                zfig, any_b = court.shot_chart(
                    _zone_grid(sshots), title=f"{spick} · by zone", height=300)
                if any_b:
                    st.plotly_chart(zfig, width="stretch", key="ps_set_zone")
                else:
                    st.caption("No located shots in this set yet.")
            _db = S.distance_buckets(sshots)
            if _db:
                st.caption("By length — " + S.distance_buckets_caption(_db))

    # ══ §G — handler vs roller / roll-vs-pop role splits ═════════════════════
    roles = ctx.role_splits(g, tid, _off) or {}
    _role_present = [k for k in PT.ROLE_SPLIT_KEYS
                     if roles.get(k) and roles[k]["all"]["poss"] > 0]
    if _role_present:
        st.markdown("<div class='pl-hdr'>Screen actions — handler vs roller "
                    "(roll-vs-pop)</div>", unsafe_allow_html=True)
        st.caption("Handler = used the screen / received · Roller = set it & "
                   "finished. A high roller 3PA% = a popping big, not a roller.")
        for k in _role_present:
            v = roles[k]
            sub = [("Handler", "handler"), ("Roller", "roller"), ("All", "all")]
            sub = [(lbl, rk) for lbl, rk in sub if v[rk]["poss"] > 0]
            xs = [lbl for lbl, _ in sub]
            st.markdown(f"**{_PTL.get(k, k)}**")
            # PPP (~0-1.5) and the percentages (0-100) live on SEPARATE charts so
            # the PPP bars aren't crushed flat next to a 50% bar on one axis.
            rc1, rc2 = st.columns(2)
            with rc1:
                pfig = go.Figure(go.Bar(
                    x=xs, y=[round(v[rk]["PPP"], 2) for _, rk in sub],
                    marker_color=ctx.ACCENT, marker_line_width=0,
                    text=[f"{v[rk]['PPP']:.2f}" for _, rk in sub],
                    textposition="outside"))
                pfig.update_yaxes(title="PPP")
                style_fig(pfig, 260)
                st.plotly_chart(pfig, width="stretch", key=f"ps_role_ppp_{k}")
            with rc2:
                sfig = go.Figure()
                for metric, mkey, color in [("eFG%", "eFG", ctx.BLUE),
                                            ("3PA%", "3PA_rate", ctx.PURPLE)]:
                    sfig.add_trace(go.Bar(
                        name=metric, x=xs,
                        y=[round(v[rk][mkey] * 100, 0) for _, rk in sub],
                        marker_color=color, marker_line_width=0))
                sfig.update_layout(barmode="group")
                sfig.update_yaxes(title="%", range=[0, 100])
                style_fig(sfig, 260)
                st.plotly_chart(sfig, width="stretch", key=f"ps_role_pct_{k}")
            st.caption(" · ".join(
                f"{lbl} {v[rk]['poss']}p · {v[rk]['PPP']:.2f} PPP · "
                f"{v[rk]['eFG'] * 100:.0f}% eFG · {v[rk]['3PA_rate'] * 100:.0f}% 3PA"
                for lbl, rk in sub))

    # ══ §H — hand-off & inbounds feeder hubs ═════════════════════════════════
    feeders = ctx.feeders(g, tid, _off) or {}
    _name_of = {p.get("_pid"): f"#{p.get('number')} {p.get('name')}"
                for p in (ctx.players or [])}
    _fd_rows = []
    for k in ("dho", "blob", "slob"):
        blk = feeders.get(k)
        if not blk or not blk.get("feeders"):
            continue
        for f in blk["feeders"][:4]:
            _fd_rows.append({
                "Set": blk["label"],
                "Initiator": _name_of.get(f["feeder_id"], f"#{f['feeder_id']}"),
                "Feeds": f["feeds"], "FGM": f["FGM"],
                "PPP": f"{f['PPP']:.2f}", "FG%": f"{f['FG%'] * 100:.0f}%",
                "Top target": _name_of.get(f.get("top_target_id"), "—"),
            })
    if _fd_rows:
        st.markdown("<div class='pl-hdr'>Hand-off & inbounds hubs (who initiates)"
                    "</div>", unsafe_allow_html=True)
        st.markdown(dense_table(_fd_rows,
                                num_cols=("Feeds", "FGM", "PPP", "FG%")),
                    unsafe_allow_html=True)

    # ══ §I — inferred tempo/creation cross-read ══════════════════════════════
    pv = ctx.playtype_view(g, tid, _off) or {}
    prows = pv.get("rows", [])
    if prows:
        st.markdown("<div class='pl-hdr'>Inferred tempo & creation (cross-check)"
                    "</div>", unsafe_allow_html=True)
        st.caption("The Synergy-style INFERRED view from the possession clock + "
                   "shot creation (no tag needed) — a cross-check on the explicit "
                   "tags above.")
        for ax in ("tempo", "creation"):
            axr = [r for r in prows if r.get("axis") == ax]
            if not axr:
                continue
            st.markdown(f"<div class='pl-hdr' style='font-size:.9em'>"
                        f"{axr[0].get('axis_label', ax)}</div>",
                        unsafe_allow_html=True)
            for r in axr:
                val = (f"{r['PPP']:.2f} PPP · {r['FG%'] * 100:.0f}% FG · "
                       f"{r['poss']} poss")
                st.markdown(_pctile_or_thin(r["label"], val, r.get("pct")),
                            unsafe_allow_html=True)

    # ══ §J — league rank context (cross-team → Coaches' Co-op only) ═══════════
    # Lg avg / Lg best / Pctile rank this team vs every tracked team's pool — a
    # cross-team aggregate, so gated on league-wide (co-op). Solo coaches see their
    # own set-call PPP above; empty leaders makes the field-comparison table skip.
    leaders = ((ctx.league_leaders(g, _off) or {})
               if ENT.viewer_is_league_wide(AUTH.current_user()) else {})
    _lr = []
    for k, blk in leaders.items():
        lead = blk.get("leaders", [])
        mine = next((x for x in lead if x["team_id"] == tid), None)
        if not mine:
            continue
        best = max(lead, key=lambda x: x["PPP"]) if lead else None
        _lr.append({
            "Set": blk["label"], "Your PPP": f"{mine['PPP']:.2f}",
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
            _lr, columns=["Set", "Your PPP", "Pctile", "Lg avg", "Lg best",
                          "Poss"]), unsafe_allow_html=True)
        st.caption(f"Where this team's {'offense' if _off else 'defense'} ranks "
                   "on each set call vs every tracked team's pool.")

    # ══ §K — offense vs defense compare ══════════════════════════════════════
    off_rows = ctx.named_view(g, tid, True).get("rows", [])
    def_rows = ctx.named_view(g, tid, False).get("rows", [])
    if off_rows and def_rows:
        _o = {r["key"]: r for r in off_rows}
        _d = {r["key"]: r for r in def_rows}
        shared = [k for k in _o if k in _d]
        if shared:
            st.markdown("<div class='pl-hdr'>Offense vs defense by set</div>",
                        unsafe_allow_html=True)
            shared = sorted(shared, key=lambda k: -(_o[k]["poss"] + _d[k]["poss"]))
            labels = [_o[k]["label"] for k in shared]
            cfig = go.Figure()
            cfig.add_trace(go.Bar(name="We score (off)",
                                  x=labels, y=[round(_o[k]["PPP"], 2) for k in shared],
                                  marker_color=ctx.GOOD, marker_line_width=0))
            cfig.add_trace(go.Bar(name="We allow (def)",
                                  x=labels, y=[round(_d[k]["PPP"], 2) for k in shared],
                                  marker_color=ctx.BAD, marker_line_width=0))
            cfig.update_layout(barmode="group")
            cfig.update_yaxes(title="PPP")
            style_fig(cfig, 320)
            st.plotly_chart(cfig, width="stretch", key="ps_off_def_compare")
            st.caption("Per set call: PPP we SCORE running it vs PPP we ALLOW when "
                       "opponents run it. A set we allow more than we score = a "
                       "defensive hole to fix.")

    # ══ §L — per-player play-style drill-down ════════════════════════════════
    psets = ctx.named_sets_all(g) or {}
    pprofs = ctx.set_profiles_all(g) or {}
    _roster = [p for p in (ctx.players or [])
               if psets.get(p.get("_pid")) or pprofs.get(p.get("_pid"))]
    if _roster:
        st.markdown("<div class='pl-hdr'>Per-player play style</div>",
                    unsafe_allow_html=True)
        _opts = {f"#{p.get('number')} {p.get('name')}": p.get("_pid")
                 for p in _roster}
        who = st.selectbox("Player", list(_opts), key="ps_player_pick")
        pid = _opts.get(who)
        pr_sets = psets.get(pid, {})
        pr_prof = pprofs.get(pid, {})
        if pr_sets:
            for k, c in sorted(pr_sets.items(), key=lambda kv: -kv[1]["poss"]):
                val = (f"{c['PPP']:.2f} PPP · {c['FG%'] * 100:.0f}% FG · "
                       f"{c.get('SCE', 0) * 100:.0f}% ScEff · {c['poss']} poss")
                st.markdown(_pctile_or_thin(_PTL.get(k, k), val, c.get("pct")),
                            unsafe_allow_html=True)
                how = _profile_howline(pr_prof.get(k))
                if how:
                    st.caption("↳ " + how)
        else:
            st.caption("No tagged set calls for this player yet.")
