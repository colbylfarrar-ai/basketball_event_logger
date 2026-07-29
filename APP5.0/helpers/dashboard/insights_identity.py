"""insights_identity.py — Insights section 1, "Who we are".

The question this section answers is the one a coach asks before any other:
what kind of team is this, against the field it actually plays in? Everything
here already existed somewhere — the DNA percentiles and the efficiency
quadrant on Lab → Advanced, the four-factor fit on Charts → Winning Formula,
opponent-adjusted shooting and the floor-spacing index on Charts → Offense.
None of it is retired from those tabs. This is a copy, gathered around one
question instead of scattered across three.

The ordering inside the section is deliberate: the plain-word identity read
first, the league placement second, and the fitted machinery last. A coach who
stops reading after two blocks should still have the answer.
"""
from __future__ import annotations

import streamlit as st

import helpers.stats as S
from helpers.cards import dense_table, pctile_bar, verdict_card
from helpers.dashboard import insights_brief as BR
from helpers.dashboard import insights_deck as DECK


def _ord(p):
    return S.ordinal(int(p)) if p is not None else "—"


def _pct(v):
    return f"{v * 100:.0f}%" if v is not None else "—"


@st.cache_data(ttl=600, show_spinner=False)
def _adj_shooting(gender, season, tids, fp=None):
    """Opponent-adjusted eFG% for the tracked field."""
    import helpers.adj_efficiency as AE
    return AE.adjusted_shooting(gender=gender, season=season,
                                game_ids=(list(tids) if tids else None))


@st.cache_data(ttl=600, show_spinner=False)
def _spacing(gender, team_id, tids, fp=None):
    import helpers.spacing as SP
    return SP.spacing_index(team_id, gender=gender,
                            team_game_ids=(list(tids) if tids else None))


@st.cache_data(ttl=600, show_spinner=False)
def _landscape(gender, season, fp=None):
    """[(team_id, name, ORtg, DRtg)] for every tracked team — the quadrant."""
    import helpers.team_ratings as TR
    from database.db import query
    trk = TR.tracked_ratings(gender=gender, season=season) or {}
    names = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}
    return [(t, names.get(t, f"#{t}"), r.get("ORtg"), r.get("DRtg"))
            for t, r in trk.items()
            if r.get("ORtg") is not None and r.get("DRtg") is not None]


def _dna_verdict(axes):
    """The plain-word read the percentiles support, before the charts."""
    if not axes:
        return
    by = {label: p for label, p, _v in axes}
    o, d = by.get("Offense"), by.get("Defense")
    lines = []
    if o is not None and d is not None:
        bal = ("a real two-way team" if o >= 65 and d >= 65 else
               "the offense carries it" if o - d >= 25 else
               "the defense carries it" if d - o >= 25 else
               "below the league bar on both ends" if o <= 35 and d <= 35 else
               "a balanced profile")
        lines.append((
            "Identity", None,
            f"Offense sits at the <b>{_ord(o)}</b> league percentile, defense "
            f"at the <b>{_ord(d)}</b> — {bal}."))
    skills = [(lbl, p) for lbl, p, _v in axes
              if lbl not in ("Offense", "Defense") and p is not None]
    if skills:
        skills.sort(key=lambda a: a[1])
        lines.append((
            "Sharpest / softest", None,
            f"Sharpest tool: <b>{skills[-1][0]}</b> ({_ord(skills[-1][1])} "
            f"percentile). Biggest gap: <b>{skills[0][0]}</b> "
            f"({_ord(skills[0][1])}) — the axis a scout will aim at."))
    if lines:
        st.markdown(verdict_card(lines), unsafe_allow_html=True)


def _quadrant(ctx, fp):
    """KenPom-style efficiency landscape. Copied from Lab → Advanced; that tab
    keeps its own, and the two read the same `tracked_ratings` so they cannot
    disagree about where this team sits."""
    try:
        import plotly.graph_objects as go
    except Exception:
        return
    try:
        rows = _landscape(ctx.gender, getattr(ctx, "season", "Current"), fp=fp)
    except Exception as exc:
        st.caption(f"Efficiency landscape unavailable — "
                   f"{type(exc).__name__}: {exc}")
        return
    tid = getattr(ctx, "team_id", None)
    me = [r for r in rows if r[0] == tid]
    if not rows or not me:
        return
    BR._hdr("Efficiency landscape",
            "Every tracked team by offense (right = better) and defense "
            "(up = better). Crosshairs = league average.")
    others = [r for r in rows if r[0] != tid]
    o_pool = [r[2] for r in rows]
    d_pool = [r[3] for r in rows]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[r[2] for r in others], y=[r[3] for r in others], mode="markers",
        marker=dict(size=9, color="#475569"),
        hovertext=[r[1] for r in others],
        hovertemplate="%{hovertext}<br>ORtg %{x:.1f} · DRtg %{y:.1f}"
                      "<extra></extra>", name="League"))
    fig.add_trace(go.Scatter(
        x=[me[0][2]], y=[me[0][3]], mode="markers+text",
        marker=dict(size=20, color="#f0a500", symbol="star"),
        text=[me[0][1]], textposition="top center",
        textfont=dict(size=12), hovertemplate="ORtg %{x:.1f} · DRtg %{y:.1f}"
                                              "<extra></extra>",
        name=me[0][1]))
    fig.add_vline(x=sum(o_pool) / len(o_pool),
                  line=dict(color="#30363d", dash="dot"))
    fig.add_hline(y=sum(d_pool) / len(d_pool),
                  line=dict(color="#30363d", dash="dot"))
    fig.update_xaxes(title="Offensive Rating →")
    fig.update_yaxes(title="← Defensive Rating (lower better)",
                     autorange="reversed")
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color="#c9d1d9", size=11),
                      showlegend=False)
    st.plotly_chart(fig, width="stretch", key="ins_id_kenpom")


def _formula_block(ctx, fp):
    """The full four-factor fit — the machinery behind the deck's one line."""
    try:
        import helpers.winning_formula as WF
        tm, lg, supp = DECK._formula(
            ctx.gender, getattr(ctx, "season", "Current"),
            getattr(ctx, "team_id", None), fp=fp)
    except Exception as exc:
        st.caption(f"Winning formula unavailable — {type(exc).__name__}: {exc}")
        return
    fit = tm if (tm or {}).get("enough") else lg
    if not (fit or {}).get("factors"):
        return
    scope = "your games" if fit is tm else "this league"
    BR._hdr(f"Winning formula — fitted on {scope}",
            "What one standard deviation of each four-factor edge is worth in "
            "points of margin, against Dean Oliver's textbook weights.")
    st.markdown(dense_table([{
        "Factor": f["label"],
        "Points per SD": f"{f['beta']:+.1f}" if f.get("beta") is not None
                         else "—",
        "Share of pull": _pct(f.get("share")),
        "Oliver": _pct(f.get("oliver")),
        "Δ vs Oliver": (f"{f['gap'] * 100:+.0f} pts"
                        if f.get("gap") is not None else "—"),
        "Raw r": (f"{f['r']:+.2f}" if f.get("r") is not None else "—"),
    } for f in fit["factors"]]), unsafe_allow_html=True)
    st.caption(
        f"Reconstruction R² **{fit.get('recon_r2')}** over "
        f"**{fit.get('n_games')}** games. The claim is an EXCHANGE RATE "
        "between edges, never a forecast.")
    if supp:
        st.caption(
            "⚠ Suppressor: " + ", ".join(f"**{f['noun']}**" for f in supp)
            + " — the fitted coefficient and the raw correlation disagree in "
              "sign. That is game state leaking into the raw column (trailing "
              "teams get fouled late), and the fit is what removes it. Read "
              "the fitted column.")


def _adj_block(ctx, tids, fp):
    """Opponent-adjusted shooting — how much of the eFG% is the schedule."""
    try:
        adj = _adj_shooting(ctx.gender, getattr(ctx, "season", "Current"),
                            tuple(tids or ()), fp=fp)
    except Exception as exc:
        st.caption(f"Adjusted shooting unavailable — "
                   f"{type(exc).__name__}: {exc}")
        return
    tid = getattr(ctx, "team_id", None)
    mine = (adj or {}).get(tid)
    if not mine:
        return
    BR._hdr("Opponent-adjusted shooting",
            "Ridge-adjusted eFG% on both ends. The delta is the part of the "
            "raw number that was the schedule, not the shooting.")
    st.markdown(verdict_card([
        ("Offense", mine.get("games"),
         f"<b>{mine['AdjeFG'] * 100:.1f}%</b> adjusted eFG against "
         f"{mine['RawEFG'] * 100:.1f}% raw "
         f"(<b>{mine['dEFG'] * 100:+.1f}</b> pts of schedule)."),
        ("Defense", mine.get("games"),
         f"<b>{mine['AdjoeFG'] * 100:.1f}%</b> adjusted eFG allowed against "
         f"{mine['RawOeFG'] * 100:.1f}% raw "
         f"(<b>{mine['dOeFG'] * 100:+.1f}</b> pts)."),
    ]), unsafe_allow_html=True)


def _spacing_block(ctx, tids, fp):
    try:
        sp = _spacing(ctx.gender, getattr(ctx, "team_id", None),
                      tuple(tids or ()), fp=fp)
    except Exception as exc:
        st.caption(f"Spacing index unavailable — {type(exc).__name__}: {exc}")
        return
    if not sp:
        return
    BR._hdr("Floor spacing", sp.get("note"))
    if sp.get("index") is None:
        return
    cols = st.columns(max(2, len(sp["components"]) + 1))
    cols[0].markdown(BR._tile("Spacing index", f"{sp['index']:.0f}",
                              f"{sp['n']} located shots"),
                     unsafe_allow_html=True)
    import helpers.spacing as SP
    for i, c in enumerate(sp["components"], start=1):
        # SP.fmt_component, not a blanket *100 — Floor width is a stdev in FEET
        cols[i].markdown(pctile_bar(c["label"], SP.fmt_component(c),
                                    c.get("pct")), unsafe_allow_html=True)


def render(ctx, *, axes, shot_diet_lines=None, ported=None, tids=(), fp=None):
    """Section 1 — Who we are."""
    _dna_verdict(axes)
    if axes:
        BR._hdr("Team DNA — every axis against the field")
        cols = st.columns(4)
        for i, (label, pct, val) in enumerate(axes):
            cols[i % 4].markdown(pctile_bar(label, val, pct),
                                 unsafe_allow_html=True)

    _quadrant(ctx, fp)
    _formula_block(ctx, fp)
    _adj_block(ctx, tids, fp)
    _spacing_block(ctx, tids, fp)

    if shot_diet_lines:
        BR._hdr("Shot depth — where this offense actually lives",
                "The 4-to-arc band is over a third of every shot in this "
                "league at 0.60 points per shot against 1.14 at the rim.")
        st.markdown(verdict_card(shot_diet_lines), unsafe_allow_html=True)

    scout = (ported or {}).get("selfscout")
    if scout:
        BR._hdr("How quickly a scout keys on this offense",
                "The full self-scout — tendency drift, over-run sets, hand and "
                "space gaps — is in “What they'll take away”.")
        st.markdown(verdict_card(scout), unsafe_allow_html=True)
