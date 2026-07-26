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

    # HOW WELL, not just HOW OFTEN. The bar is a SHARE, and a share bar alone
    # reads as though it were a quality bar — a long red bar looks like bad
    # shooting when it means frequent shooting. Putting the FG% and the
    # league's FG% for the same band on the row is what stops the bar from
    # being read as something it is not.
    fg, lgfg = cell.get("fg"), lg_cell.get("fg")
    if fg is not None:
        d = None if lgfg is None else (fg - lgfg)
        dcol = ("#8b949e" if d is None or abs(d) < 0.02 else
                ("#2ecc71" if d > 0 else "#f85149"))
        fgtxt = (f"<span style='color:var(--text)'>{_pct(fg, 1)}</span>"
                 + (f" <span style='color:var(--subtext);font-size:10px'>"
                    f"(lg {_pct(lgfg, 1)})</span>" if lgfg is not None else "")
                 + ("" if d is None else
                    f" <span style='color:{dcol};font-size:10px'>"
                    f"{d * 100:+.1f}</span>"))
    else:
        fgtxt = "<span style='color:var(--subtext)'>—</span>"

    return (
        "<div class='pl-pct'><div class='pl-pct-top'>"
        f"<span class='pl-pct-lbl'>{html.escape(cell['label'])}"
        f"<span style='color:var(--subtext);font-size:10px'> "
        f"· {cell['n']} shots</span></span>"
        f"<span class='pl-pct-val'>{_pct(cell['share'], 1)} "
        f"<span style='color:var(--subtext);font-size:10px'>"
        f"(lg {_pct(lg_cell['share'], 0)})</span> {dtxt}</span></div>"
        f"<div class='pl-pct-track' style='position:relative'>"
        f"<div class='pl-pct-fill' style='width:{w}%;background:{col}'></div>"
        f"<div style='position:absolute;left:{tick}%;top:-2px;bottom:-2px;"
        f"width:2px;background:var(--text);opacity:.55'></div></div>"
        f"<div style='display:flex;justify-content:space-between;"
        f"font-size:11px;margin-top:2px'>"
        f"<span style='color:var(--subtext)'>shoots</span>{fgtxt}</div></div>")


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
            # NOT escaped — SK.verdict owns its own <b> labels; see the markup
            # contract in its docstring. (Escaping printed them literally.)
            st.markdown(
                verdict_card([("shot diet", line["n"], line["text"])]),
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
    # descriptive=True: these are a TEAM's season shooting percentages over
    # hundreds of attempts — the record of games that were played, not a claim
    # that they will repeat. The dot annotates repeatability; it does not get
    # to withhold a team's own box score. See helpers/reliability.py.
    rr = SK.rate_reads(tbl, unit=unit, descriptive=True)

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
        # The league column is the BASE. Without it "you shoot 27%" is a number
        # with nothing to lean on, and the delta beside it is the whole read —
        # 27% from 4ft-to-arc is dead average in this league and 27% at the rim
        # would be a catastrophe.
        head = ("<table class='mini'><tr><th>Band</th><th>FGA</th>"
                "<th>FG%</th><th>Lg FG%</th><th>Diff</th>"
                "<th>PPS</th><th>Lg PPS</th></tr>")
        body = ""
        held = []
        for k in cells:
            c, r, l = tbl[k], rr[k], lg[k]
            if c["fg"] is None:
                fg_txt = "<span style='color:var(--subtext)'>—</span>"
                diff_txt = pps_txt = fg_txt
            elif not r["show"]:
                # Reserved for a rate MEASURED as not predicting itself. A
                # team's season shooting is descriptive and never lands here;
                # this branch exists for trait-style reads that share the code.
                held.append(c["label"])
                fg_txt = ("<span style='color:var(--subtext)' "
                          f"title='{html.escape(r['caption'])}'>held</span>")
                diff_txt = pps_txt = fg_txt
            else:
                dot = CARDS.conf_dot_r(r["sb"], metric=f"{c['label']} FG%")
                fg_txt = f"{_pct(c['fg'], 1)}{dot}"
                pps_txt = _num(c["pps"])
                if l["fg"] is not None:
                    dv = c["fg"] - l["fg"]
                    dc = ("#8b949e" if abs(dv) < 0.02 else
                          ("#2ecc71" if dv > 0 else "#f85149"))
                    diff_txt = (f"<span style='color:{dc}'>"
                                f"{dv * 100:+.1f}</span>")
                else:
                    diff_txt = "—"
            body += (f"<tr><td>{html.escape(c['label'])}</td>"
                     f"<td>{c['n']}</td><td>{fg_txt}</td>"
                     f"<td style='color:var(--subtext)'>{_pct(l['fg'], 1)}</td>"
                     f"<td>{diff_txt}</td>"
                     f"<td>{pps_txt}</td>"
                     f"<td style='color:var(--subtext)'>{_num(l['pps'])}</td>"
                     f"</tr>")
        u = tbl[SK.UNKNOWN]
        if u["n"]:
            body += (f"<tr><td style='color:var(--subtext)'>Unlocated</td>"
                     f"<td style='color:var(--subtext)'>{u['n']}</td>"
                     f"<td colspan='5' style='color:var(--subtext)'>"
                     f"no coordinate</td></tr>")
        st.markdown(head + body + "</table>", unsafe_allow_html=True)

        cap = (f"{meta['located']} of {meta['total']} shots located "
               f"({_pct(meta['located_share'], 0)}). **Lg** columns are this "
               f"league's rate in the same band — the base the Diff is against. "
               f"A dash means under {SK.MIN_KIND_RATE_ATT} attempts there.")
        if held:
            cap += (f" “Held” means the opposite problem: {', '.join(held)} has "
                    f"plenty of attempts, but that percentage was measured as "
                    f"not predicting itself, so a number there would move on "
                    f"noise. Hover it for the measurement.")
        cap += (" These percentages are a **record of these games**, not a "
                "forecast — they are shown whatever their reliability. The dot "
                "says only how likely they are to repeat: ● reliable, "
                "◐ directional, ○ early, · not measurable at this many teams.")
        st.caption(cap)


def render_concedes(shots, *, labels=None, own_side=True, league_shots=None,
                    heading="What each scheme gives up — by depth"):
    """Shot band × defensive scheme: what the tag actually concedes.

    The cross-tab the zones could never give, because "gives up the paint" and
    "gives up layups" are the same sentence in a five-wedge system and two very
    different things on the floor.

    `shots` is the tab's already-scoped located feed — shots ALLOWED when
    own_side is True (the `defense` tag is then the scheme this team ran), or
    the team's own attempts when False (the tag is the scheme it faced).

    NORMALIZED AGAINST THE LEAGUE'S MIX FOR THE SAME SCHEME, which is the whole
    point of `league_shots`. The raw version of this table produced a finding
    that was not one: "scramble concedes 55.5% of its shots at the rim, at
    1.009 PPS". True, and empty — a scramble IS a broken possession, so it
    gives up rim looks by definition, everywhere, for everyone. Reading a
    scheme against the LEAGUE-WIDE mix makes every scramble row in the app look
    alarming and tells a coach nothing about their own.

    The question a coach can act on is whether THEIR scramble concedes more rim
    than everyone else's scramble. So each cell shows the delta against the
    league's mix for that same scheme, and the raw share sits beside it. When
    no league feed is supplied the table falls back to raw shares and says so,
    rather than silently comparing against nothing.
    """
    xt = SK.kind_by_shot_tag(shots, "defense", taxonomy=SK.DISPLAY_TAXONOMY)
    if not xt:
        st.caption(
            "No scheme has enough tagged located shots yet for a depth "
            f"cross-tab (needs {SK.MIN_KIND_RATE_ATT} per scheme). Tag the "
            "Defense in the tracker and this fills in.")
        return
    st.markdown(f"<div class='lab-hdr'>{html.escape(heading)}</div>",
                unsafe_allow_html=True)

    cells_ = SK.TAXONOMIES[SK.DISPLAY_TAXONOMY][0]
    # The league's OWN cross-tab, same tag, same taxonomy, no per-scheme
    # minimum — a scheme thin for one team can still be well sampled league-wide,
    # and that is exactly the row worth comparing against.
    lg_xt = (SK.kind_by_shot_tag(league_shots, "defense", min_n=1,
                                 taxonomy=SK.DISPLAY_TAXONOMY)
             if league_shots else {})

    rows = sorted(xt.items(), key=lambda kv: -kv[1]["_meta"]["located"])
    head = ("<table class='mini'><tr><th>Scheme</th><th>Shots</th>"
            + "".join(f"<th>{html.escape(SK.BAND_LABELS[k])}</th>"
                      for k in cells_)
            + "<th>PPS</th></tr>")
    body = ""
    for key, t in rows:
        n = t["_meta"]["located"]
        if not n:
            continue
        pts = sum(t[k]["pts"] for k in cells_)
        lg_t = lg_xt.get(key)
        lg_n = lg_t["_meta"]["located"] if lg_t else 0
        tds = ""
        for k in cells_:
            sh = t[k]["share"]
            col = _KIND_COLOR.get(k, "#8b949e")
            lg_sh = lg_t[k]["share"] if lg_t else None
            if sh is None or lg_sh is None:
                tds += f"<td style='color:{col}'>{_pct(sh, 1)}</td>"
                continue
            dl = sh - lg_sh
            # Colour the DELTA, not the share: the share is context, the delta
            # is the finding. Neutral under 3pp — below that it is one shot.
            #
            # The sign flips with the side, and getting this wrong inverts every
            # judgment on the table. `_WORSE_IF_MORE` is written from the
            # SHOOTER's point of view: taking more shots from 4 ft to the arc is
            # bad for you. When these are shots you ALLOWED, forcing the
            # opponent into that band is exactly what a defense is trying to do,
            # so the same delta is good news.
            bad = (dl > 0) == (k in _WORSE_IF_MORE)
            if own_side:
                bad = not bad
            dcol = ("#8b949e" if abs(dl) < 0.03 else
                    ("#f85149" if bad else "#2ecc71"))
            tds += (f"<td><span style='color:{col}'>{_pct(sh, 1)}</span> "
                    f"<span style='color:{dcol};font-size:10px'>"
                    f"{dl * 100:+.0f}</span></td>")
        lbl = (labels or {}).get(key, key)
        pps_txt = f"{pts / n:.3f}"
        if lg_t and lg_n:
            lg_pps = sum(lg_t[k]["pts"] for k in cells_) / lg_n
            dp = pts / n - lg_pps
            pcol = ("#8b949e" if abs(dp) < 0.05 else
                    ("#f85149" if (dp > 0) == own_side else "#2ecc71"))
            pps_txt += (f" <span style='color:{pcol};font-size:10px'>"
                        f"{dp:+.2f}</span>")
        body += (f"<tr><td>{html.escape(str(lbl))}</td><td>{n}</td>{tds}"
                 f"<td><b>{pps_txt}</b></td></tr>")
    st.markdown(head + body + "</table>", unsafe_allow_html=True)

    _verb = "concedes" if own_side else "gets"
    if lg_xt:
        st.caption(
            f"Big number = share of shots from each band this scheme {_verb}. "
            f"Small number = **the same scheme's league average, subtracted**, "
            f"in share points. That subtraction is the point of the table. A "
            f"scramble is a broken possession, so it gives up rim looks by "
            f"definition — every team's does. Against the league as a whole "
            f"that reads as a damning finding about your defense; against "
            f"other people's scrambles it reads as whatever it actually is. "
            f"Only the small number is about you. Neutral under 3 points, "
            f"which at these samples is a shot or two. The PPS column is "
            f"normalized the same way. Schemes under "
            f"{SK.MIN_KIND_RATE_ATT} tagged located shots for THIS team are "
            f"left off; the league baseline behind them has no such floor, "
            f"because a scheme that is thin here can be well sampled "
            f"league-wide and that is exactly the row worth comparing to. "
            f"Located shots only.")
    else:
        st.caption(
            f"Share of shots from each depth band each scheme {_verb}, and the "
            "points per shot that comes with it. **Not normalized** — no "
            "league feed was supplied, so these are raw shares and a scheme "
            "that concedes rim looks by its nature (a scramble) will look "
            "alarming here whoever is running it. "
            f"Schemes under {SK.MIN_KIND_RATE_ATT} tagged located shots are "
            "left off. Located shots only.")


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
