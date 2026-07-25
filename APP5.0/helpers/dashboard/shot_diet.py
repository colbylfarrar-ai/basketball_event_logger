"""
shot_diet.py — the depth axis of the shot chart, rendered.

The five zones are an ANGLE system. helpers/shot_kinds.py adds the DEPTH axis
the app never had, and this module draws it: how much of a team's diet comes
from each kind, how that compares to the league, and what the gap is worth in
points. Read shot_kinds' docstring before touching this — the display rules
here are not stylistic, they are the split-half measurement made visible.

The short version of what may and may not be shown:
  * SHARES are the robust half (player floater share r=.636 against itself,
    team .582) and are always rendered, with the league share beside them.
  * RATES are the fragile half. A per-player kind FG% has r=.078 against
    itself, which is nothing, so shot_kinds returns None for any cell under
    MIN_KIND_RATE_ATT and this module prints an em dash rather than inventing
    a number to fill the column.
  * The VERDICT needs materiality as well as sample, so most teams get the
    table and no sentence. That is correct: only one team on the live book
    has a floater problem worth a coach's practice time.

Zone content is not replaced by any of this. Angle and depth are complementary
axes — the point of the module is that reading either one alone is what hid
the 0.55 PPS spread inside zone C in the first place.

Pure renderer — the shot list arrives from a page-cached callable.
"""
from __future__ import annotations

import html

import streamlit as st

import helpers.shot_kinds as SK
from helpers.cards import verdict_card

#: Bar colour per kind — value-coded, not decorative. Rim and corner 3s are the
#: shots worth taking; the floater band is the one a coach is trying to shrink.
_KIND_COLOR = {
    "rim": "#2ecc71",
    "floater": "#f85149",
    "mid": "#d29922",
    "corner3": "#58a6ff",
    "abovebreak3": "#8b949e",
}


def _pct(v, dec=1):
    return "—" if v is None else f"{v * 100:.{dec}f}%"


def _num(v, dec=2):
    return "—" if v is None else f"{v:.{dec}f}"


def _diet_row(kind, cell, lg_cell, delta):
    """One kind's row: label, share bar against the league tick, n, FG%, PPS.

    The league share is drawn as a tick ON the bar rather than as a second bar,
    so the comparison reads at a glance without doubling the row height — the
    coach's question is "more or less than everyone else", not "what are the
    two numbers".
    """
    share = cell["share"] or 0.0
    lg = lg_cell["share"] or 0.0
    col = _KIND_COLOR.get(kind, "#8b949e")
    # Bars are scaled to 60% share = full width; nothing in this league gets
    # near that, so the bars stay readable instead of all sitting at ~25%.
    w = max(1.0, min(100.0, share / 0.60 * 100))
    tick = max(0.0, min(100.0, lg / 0.60 * 100))
    dtxt = ("" if delta is None else
            f"<span style='color:{'#f85149' if (delta > 0) == (kind in ('floater', 'mid')) and abs(delta) >= 0.03 else '#8b949e'}'>"
            f"{delta * 100:+.1f}pp</span>")
    return (
        "<div class='pl-pct'><div class='pl-pct-top'>"
        f"<span class='pl-pct-lbl'>{html.escape(cell['label'])}</span>"
        f"<span class='pl-pct-val'>{_pct(cell['share'], 1)} "
        f"<span style='color:var(--subtext);font-size:10px'>"
        f"(lg {_pct(lg_cell['share'], 0)})</span> {dtxt}</span></div>"
        f"<div class='pl-pct-track' style='position:relative'>"
        f"<div class='pl-pct-fill' style='width:{w}%;background:{col}'></div>"
        f"<div style='position:absolute;left:{tick}%;top:-2px;bottom:-2px;"
        f"width:2px;background:var(--text);opacity:.55'></div></div></div>")


def render(shots, team_id, *, games=None, key_prefix="sd", offense=True,
           heading="Shot depth — how far out are your shots?"):
    # "Shot diet" is deliberately NOT the heading: pages/6_Team_Dashboard.py:1997
    # already renders a block by that name in this same Shooting tab (attempts
    # by type), and player_card.py has a third. Depth is the new axis and the
    # honest label for it.
    """The shot-diet block for one team.

    shots       located/mapped shots for the whole tracked pool (NOT pre-filtered
                to the team — the league baseline is computed from the same list,
                which is what keeps the comparison honest and costs one pass)
    team_id     whose diet to draw
    games       tracked game count, for the points-per-game phrasing
    offense     False draws what the team CONCEDES by kind
    """
    d = SK.diet(team_id=team_id, shots=shots, offense=offense)
    tbl, lg, meta = d["table"], d["league"], d["table"]["_meta"]

    st.markdown(f"<div class='lab-hdr'>{html.escape(heading)}</div>",
                unsafe_allow_html=True)

    if not d["gated"]:
        st.info(
            f"Too few located shots to read a diet — {d['n_located']} of the "
            f"{d['min_att']} needed. Shot kinds are geometry, so this fills in "
            f"as games are tracked; nothing needs to be logged differently.")
        return

    if offense:
        for line in SK.verdict(team_id=team_id, shots=shots, games=games):
            st.markdown(
                verdict_card([("shot diet", line["n"], html.escape(line["text"]))]),
                unsafe_allow_html=True)

    left, right = st.columns([3, 2])
    with left:
        rows = "".join(_diet_row(k, tbl[k], lg[k], d["delta"][k])
                       for k in SK.KINDS)
        st.markdown(rows, unsafe_allow_html=True)
        st.caption(
            "Bar = your share of located shots; the tick is the league's share "
            "of the same. Depth is measured from the rim, so it is a different "
            "question from the zone charts (angle) — a zone-C shot can be "
            "either the best look on the floor or the worst.")

    with right:
        head = ("<table class='mini'><tr><th>Kind</th><th>FGA</th>"
                "<th>FG%</th><th>PPS</th></tr>")
        body = ""
        for k in SK.KINDS:
            c = tbl[k]
            body += (f"<tr><td>{html.escape(c['label'])}</td>"
                     f"<td>{c['n']}</td><td>{_pct(c['fg'], 1)}</td>"
                     f"<td>{_num(c['pps'])}</td></tr>")
        u = tbl[SK.UNKNOWN]
        if u["n"]:
            body += (f"<tr><td style='color:var(--subtext)'>Unlocated</td>"
                     f"<td style='color:var(--subtext)'>{u['n']}</td>"
                     f"<td colspan='2' style='color:var(--subtext)'>"
                     f"no coordinate</td></tr>")
        st.markdown(head + body + "</table>", unsafe_allow_html=True)
        st.caption(
            f"{meta['located']} of {meta['total']} shots located "
            f"({_pct(meta['located_share'], 0)}). A dash means that band has "
            f"under {SK.MIN_KIND_RATE_ATT} attempts — its percentage would not "
            f"repeat itself, so it is not shown. Split-half on this book puts a "
            f"player's floater FG% at r=.08 against her own other games, which "
            f"is why the shares above carry the read and the rates only "
            f"describe.")


def render_concedes(shots, *, labels=None, own_side=True,
                    heading="What each scheme gives up — by depth"):
    """Shot kind × defensive scheme: what the tag actually concedes.

    The cross-tab the zones could never give, because "gives up the paint" and
    "gives up layups" are the same sentence in a five-wedge system and two very
    different things on the floor.

    `shots` is the tab's already-scoped located feed — shots ALLOWED when
    own_side is True (the `defense` tag is then the scheme this team ran), or
    the team's own attempts when False (the tag is the scheme it faced).
    """
    xt = SK.kind_by_shot_tag(shots, "defense")
    if not xt:
        st.caption(
            "No scheme has enough tagged located shots yet for a depth "
            f"cross-tab (needs {SK.MIN_KIND_RATE_ATT} per scheme). Tag the "
            "Defense in the tracker and this fills in.")
        return
    st.markdown(f"<div class='lab-hdr'>{html.escape(heading)}</div>",
                unsafe_allow_html=True)

    rows = sorted(xt.items(), key=lambda kv: -kv[1]["_meta"]["located"])
    head = ("<table class='mini'><tr><th>Scheme</th><th>Shots</th>"
            + "".join(f"<th>{html.escape(SK.KIND_LABELS[k].split(' /')[0])}</th>"
                      for k in SK.KINDS)
            + "<th>PPS</th></tr>")
    body = ""
    for key, t in rows:
        n = t["_meta"]["located"]
        if not n:
            continue
        pts = sum(t[k]["pts"] for k in SK.KINDS)
        cells = ""
        for k in SK.KINDS:
            sh = t[k]["share"]
            col = _KIND_COLOR.get(k, "#8b949e")
            cells += (f"<td style='color:{col}'>{_pct(sh, 1)}</td>")
        lbl = (labels or {}).get(key, key)
        body += (f"<tr><td>{html.escape(str(lbl))}</td><td>{n}</td>{cells}"
                 f"<td><b>{pts / n:.3f}</b></td></tr>")
    st.markdown(head + body + "</table>", unsafe_allow_html=True)
    _verb = "concedes" if own_side else "gets"
    st.caption(
        f"Share of shots from each depth band each scheme {_verb}, and the "
        "points per shot that comes with it. Rim shots are worth about 1.09 "
        "points a trip in this league and the 4–10 ft band about 0.57, so two "
        "schemes can allow the same shot COUNT and be half a point apart. "
        f"Schemes under {SK.MIN_KIND_RATE_ATT} tagged located shots are left "
        "off rather than shown at a sample that moves on one game. Located "
        "shots only — untagged and unlocated attempts are not in these rows.")


def league_reference():
    """The league kind table as a standalone caption block.

    Small, and worth showing wherever the diet is: the whole argument is that
    the 4-10 ft band is not a better shot than the midrange, and a coach only
    believes that when the two numbers sit next to each other.
    """
    return (
        "Rim ≤4 ft · floater 4–10 ft · midrange 10 ft–arc. The 4 ft line is "
        "where this league's efficiency actually falls off (2–4 ft shoots 56%, "
        "4–6 ft shoots 32%), and past it a 2 does not recover — the floater "
        "band and the midrange are the same shot by the numbers.")
