"""
shot_diet.py — the depth axis of the shot chart, rendered.

The five zones are an ANGLE system. helpers/shot_kinds.py adds the DEPTH axis
the app never had, and this module draws it: how much of a team's diet comes
from each kind, how that compares to the league, and what the gap is worth in
points. Read shot_kinds' docstring before touching this — the display rules
here are not stylistic, they are the split-half measurement made visible.

BOTH CUTS RENDER. The depth bands (0-4 / 4 ft-to-arc / 3 at the arc / 3 from
23+) lead, because they own every player-level read and carry the verdict. The
5 kinds sit under them in an expander, because the corner/above-break split is
angular information the depth cut cannot express and the corner 3 is the most
valuable 3 on the floor. Neither is a rounding of the other and neither is
being phased out — see shot_kinds' docstring for what each one measured.

The short version of what may and may not be shown:
  * SHARES are the robust half (player band share SB .87, team .88) and are
    always rendered, with the league share beside them.
  * RATES clear TWO bars, and the second is the one that bites. A cell needs
    enough attempts (shot_kinds returns None below MIN_KIND_RATE_ATT — an em
    dash here), AND the metric has to predict itself. Rim FG% has the largest
    per-player sample in the book and predicts itself at SB .11, so it is
    "held": plenty of attempts, no stability. That distinction is drawn on
    screen rather than collapsed, because a dash and a held cell mean opposite
    things and a coach who cannot tell them apart learns to distrust both.
  * A DOT on a percentage carries its measured reliability (● reliable,
    ◐ directional, ○ early), hovering to the r itself. Nothing is decorated
    that was not measured.
  * The VERDICT needs materiality as well as sample, so most teams get the
    table and no sentence. That is correct: only one team on the live book
    has a diet problem worth a coach's practice time.

Zone content is not replaced by any of this. Angle and depth are complementary
axes — the point of the module is that reading either one alone is what hid
the 0.55 PPS spread inside zone C in the first place.

Pure renderer — the shot list arrives from a page-cached callable.
"""
from __future__ import annotations

import html

import streamlit as st

import helpers.cards as CARDS
import helpers.shot_kinds as SK
from helpers.cards import verdict_card

#: Bar colour per cell — value-coded, not decorative. Rim and corner 3s are the
#: shots worth taking; the 4ft-to-arc band is the one a coach is trying to
#: shrink. Both taxonomies key into the same map so the same shot never changes
#: colour when a coach's eye moves between the two tables.
_KIND_COLOR = {
    "rim": "#2ecc71",
    "floater": "#f85149",
    "mid": "#d29922",
    "corner3": "#58a6ff",
    "abovebreak3": "#8b949e",
    "rim04": "#2ecc71",
    "two419": "#f85149",
    "arc3": "#58a6ff",
    "deep3": "#8b949e",
}

#: Cells where taking MORE than the league is the bad direction. Used to colour
#: the delta, so "+4pp of your shots come from the worst band" reads red and
#: "+4pp from the rim" does not.
_WORSE_IF_MORE = {"floater", "mid", "two419"}


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
    bad = (delta is not None and abs(delta) >= 0.03
           and (delta > 0) == (kind in _WORSE_IF_MORE))
    dtxt = ("" if delta is None else
            f"<span style='color:{'#f85149' if bad else '#8b949e'}'>"
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
    st.markdown(f"<div class='lab-hdr'>{html.escape(heading)}</div>",
                unsafe_allow_html=True)

    d = SK.diet(team_id=team_id, shots=shots, offense=offense,
                taxonomy=SK.DISPLAY_TAXONOMY)
    if not d["gated"]:
        st.info(
            f"Too few located shots to read a diet — {d['n_located']} of the "
            f"{d['min_att']} needed. Shot bands are geometry, so this fills in "
            f"as games are tracked; nothing needs to be logged differently.")
        return

    if offense:
        for line in SK.verdict(team_id=team_id, shots=shots, games=games):
            st.markdown(
                verdict_card([("shot diet", line["n"], html.escape(line["text"]))]),
                unsafe_allow_html=True)

    # Both cuts, stacked: DEPTH first because it owns the reads and carries the
    # verdict, ANGLE under it because the corner/above-break split is real
    # information the depth cut cannot express. Neither replaces the other —
    # the whole finding behind this block is that reading one axis alone is what
    # hid the 0.55 PPS spread inside zone C to begin with.
    _cut(d, "team", "Depth — how far out are your shots?")

    dk = SK.diet(team_id=team_id, shots=shots, offense=offense,
                 taxonomy="kind")
    with st.expander("The same shots cut by ANGLE (rim · floater · midrange · "
                     "corner 3 · above-break 3)", expanded=False):
        _cut(dk, "team", None)
        st.caption(
            "Same shots, different question. The depth cut merges the floater "
            "and the midrange because they measured as the same shot (0.57 and "
            "0.50 points a trip); this cut keeps them apart and splits the 3s "
            "by ANGLE instead of by distance, which is the only place the "
            "corner 3 — the most valuable 3 on the floor — is visible as its "
            "own thing. The model prices shots on this cut; the reads above "
            "use the other. Both are measured, neither is a rounding of the "
            "other.")


def _cut(d, unit, heading):
    """One taxonomy's half of the block: share bars left, rate table right.

    Split out so the depth and angle cuts cannot drift apart in formatting —
    the point of showing both is that a coach can compare them, which only
    works if they are drawn by the same code.
    """
    tbl, lg, meta = d["table"], d["league"], d["table"]["_meta"]
    cells = SK.TAXONOMIES[d["taxonomy"]][0]
    rr = SK.rate_reads(tbl, unit=unit)

    if heading:
        st.markdown(f"<div class='hdr-sub'>{html.escape(heading)}</div>",
                    unsafe_allow_html=True)

    left, right = st.columns([3, 2])
    with left:
        st.markdown("".join(_diet_row(k, tbl[k], lg[k], d["delta"][k])
                            for k in cells), unsafe_allow_html=True)
        st.caption(
            "Bar = your share of located shots; the tick is the league's share "
            "of the same. Shares are the reliable half of this block — they "
            "predict themselves across a split season at r≈.87, which is why "
            "they carry the verdict and the percentages beside them do not.")

    with right:
        head = ("<table class='mini'><tr><th>Band</th><th>FGA</th>"
                "<th>FG%</th><th>PPS</th></tr>")
        body = ""
        withheld = []
        for k in cells:
            c, r = tbl[k], rr[k]
            if c["fg"] is not None and not r["show"]:
                # Enough attempts, but the metric does not predict itself.
                # Withheld with a reason rather than printed with a caveat.
                withheld.append(c["label"])
                fg_txt = ("<span style='color:var(--subtext)' "
                          f"title='{html.escape(r['caption'])}'>held</span>")
                pps_txt = fg_txt
            else:
                dot = CARDS.conf_dot_r(r["sb"], metric=f"{c['label']} FG%") \
                    if r["show"] else ""
                fg_txt = f"{_pct(c['fg'], 1)}{dot}"
                pps_txt = _num(c["pps"])
            body += (f"<tr><td>{html.escape(c['label'])}</td>"
                     f"<td>{c['n']}</td><td>{fg_txt}</td>"
                     f"<td>{pps_txt}</td></tr>")
        u = tbl[SK.UNKNOWN]
        if u["n"]:
            body += (f"<tr><td style='color:var(--subtext)'>Unlocated</td>"
                     f"<td style='color:var(--subtext)'>{u['n']}</td>"
                     f"<td colspan='2' style='color:var(--subtext)'>"
                     f"no coordinate</td></tr>")
        st.markdown(head + body + "</table>", unsafe_allow_html=True)

        cap = (f"{meta['located']} of {meta['total']} shots located "
               f"({_pct(meta['located_share'], 0)}). A dash means under "
               f"{SK.MIN_KIND_RATE_ATT} attempts in that band.")
        if withheld:
            cap += (f" “Held” means the opposite problem: {', '.join(withheld)} "
                    f"has plenty of attempts, but that percentage does not "
                    f"predict itself across a split season, so a number there "
                    f"would move on noise. Hover it for the measurement.")
        cap += (" A dot on a percentage says how firmly it repeats: "
                "● reliable, ◐ directional, ○ early.")
        st.caption(cap)


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
        "Depth cut: 0–4 ft · 4 ft–arc · a 3 at the arc · a 3 from 23+. The 4 ft "
        "line is where this league's efficiency actually falls off (2–4 ft "
        "shoots 56%, 4–6 ft shoots 32%), and past it a 2 does not recover — "
        "which is why everything from 4 ft to the arc is one band. It is 37% of "
        "every shot taken in this league at 0.55 points a trip, against 1.09 at "
        "the rim. The angle cut underneath splits that band back into floater "
        "and midrange, and splits the 3s into corner and above-break.")
