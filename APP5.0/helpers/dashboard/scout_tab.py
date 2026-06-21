"""
dashboard/scout_tab.py — the Team Dashboard "Scout" tab.

Game-day scouting report: keys to guard / attack, four-factor tendencies,
the 2s-vs-3s breakeven, personnel cards, shot chart / zones and a printable
sheet. Extracted from pages/6_Team_Dashboard.py (see
helpers/dashboard/__init__.py for the ctx convention).

Coaches pick what shows via the "Customize sheet" panel — choices persist
per-coach and gate both this tab and the printable hand-out (see SCOUT_SECTIONS).
"""
from __future__ import annotations

import html

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from database.db import query
from helpers.court import shot_map as _shot_map
import helpers.scout as SC
import helpers.stats as S
import helpers.scoutboard as SB
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.settings_utils as SU


# Sections a coach can include / exclude on their scout sheet. Applies to BOTH
# this interactive tab and the printable hand-out. Stored per-coach as a CSV of
# HIDDEN keys in app_settings ("scout_hidden_sections", namespaced u:<email>:);
# default = everything on. Keep keys in sync with the _show() guards below and
# the same keys honoured in helpers/scout.py:printable_html().
SCOUT_SECTIONS = [
    ("keys", "Keys to the game (guard / attack)"),
    ("four_factors", "Four factors & tendencies"),
    ("breakeven", "Should they shoot 2s or 3s?"),
    ("three_profile", "Per-player 3-point profile"),
    ("auto_report", "Auto scouting report"),
    ("efficiency", "Efficiency summary"),
    ("personnel", "Personnel (player breakdown)"),
    ("shot_source", "Shot source — SC / Pass / Screen / Both"),
    ("play_calls", "Play calls — how they get their shots"),
    ("shot_chart", "Shot chart"),
    ("zones", "Shooting by zone"),
    ("poss_length", "Scoring by possession length"),
    ("notes", "Game-plan notes"),
    ("play_diagrams", "Blank play diagrams (draw by hand)"),
]


def _auto_report_tips(ctx):
    """The rule-based auto scouting tips (markdown **bold**). Shared by the
    on-screen 'Scouting report' block and the printable sheet so they never drift."""
    tips = []
    if ctx.ff["off"]["eFG"] >= 0.50:
        tips.append("**Efficient shooting team** — eFG% "
                    f"{ctx.pctf(ctx.ff['off']['eFG'])}; contest everything and keep "
                    "them off the offensive glass.")
    elif ctx.ff["off"]["eFG"] <= 0.42:
        tips.append("**Below-average shooting** — eFG% "
                    f"{ctx.pctf(ctx.ff['off']['eFG'])}; pack the paint and live with "
                    "contested jumpers.")
    if ctx.ff["off"]["TOV"] >= 0.18:
        tips.append("**Turnover-prone** — gives it away on "
                    f"{ctx.pctf(ctx.ff['off']['TOV'])} of trips; pressure the ball "
                    "to force live-ball turnovers.")
    if ctx.ff["off"]["ORB"] >= 0.33:
        tips.append("**Crashes the offensive glass** — OREB% "
                    f"{ctx.pctf(ctx.ff['off']['ORB'])}; box out and secure the "
                    "first rebound.")
    if ctx.soff["pct_paint"] >= 0.50:
        tips.append("**Paint-heavy offense** — "
                    f"{ctx.pctf(ctx.soff['pct_paint'])} of points in the paint; wall "
                    "up the rim and make them prove the jumper.")
    elif ctx.brk["3PAr"] >= 0.40:
        tips.append("**Lives behind the arc** — "
                    f"{ctx.pctf(ctx.brk['3PAr'])} of shots are threes; run them off "
                    "the line.")
    if ctx.ff["def"]["TOV"] >= 0.18:
        tips.append("**Forces turnovers** — takes it away on "
                    f"{ctx.pctf(ctx.ff['def']['TOV'])} of opponent trips; value "
                    "every possession and limit careless passes.")
    if ctx.ff["def"]["eFG"] <= 0.44:
        tips.append("**Locks down shots** — holds opponents to "
                    f"{ctx.pctf(ctx.ff['def']['eFG'])} eFG; attack early before the "
                    "defense sets.")
    pace = ctx.summ.get("POSS_pg", 0)
    if pace >= 70:
        tips.append("**Plays fast** — "
                    f"{pace:.0f} possessions/game; control tempo to shorten "
                    "the game if you're the underdog.")
    elif pace and pace < 60:
        tips.append("**Slow, deliberate pace** — "
                    f"{pace:.0f} possessions/game; speed them up to drag them "
                    "out of their comfort zone.")
    rated_pl = [p for p in ctx.players if p["PPG"] is not None]
    if rated_pl:
        top = max(rated_pl, key=lambda p: p["PPG"])
        share = top["PTS"] / max(ctx.tb["PTS"], 1)
        if share >= 0.28:
            tips.append(f"**Star-dependent** — #{top['number']} "
                        f"{top['name']} scores {share*100:.0f}% of the team's "
                        "points; key on them and force someone else to beat you.")
    return tips


def _three_profile(ctx):
    """{be3_pct, players:[{label,p3,att,above}]} for the printable 3-pt profile, or
    None when there isn't enough 3-point volume (min 4 attempts)."""
    three_p = [p for p in ctx.players if p["3PA"] and p["3PA"] >= 4]
    if not three_p:
        return None
    be3_pct = ctx.brk["be3"] * 100
    three_p = sorted(three_p, key=lambda p: p["3PA"], reverse=True)
    return {"be3_pct": be3_pct, "players": [
        {"label": f"#{p['number']} {p['name']}", "p3": p["3P%"] or 0,
         "att": p["3PA"], "above": (p["3P%"] or 0) >= be3_pct} for p in three_p]}


@st.fragment
def render(ctx):
    st.caption("Game-day scouting report — keys to the game, four factors & "
               "tendencies, the 2s-vs-3s question, personnel and a printable "
               "sheet. Built from the same tracked-game engine as the rest of "
               "the page.")
    frame = st.radio("Framing", ["Scout opponent", "Self-scout (own team)"],
                     horizontal=True, key="scout_frame")
    _self = frame.startswith("Self")
    opp_label = "Self-scout" if _self else "Opponent scout"

    if _self:
        # self-scout: the WHOLE roster, nobody hidden
        sc = ctx.scout(ctx.team_id, ctx.gender, None, ())
    else:
        # opponent scout: hide players who won't play (default = injured / out /
        # suspended from their availability), still picking from the full roster
        _avail = {r["id"]: (r["availability"] or "Active") for r in query(
            "SELECT id, availability FROM players WHERE team_id=? AND archived=0",
            (ctx.team_id,))}
        _names = {p["_pid"]: f"#{p['number']} {p['name']}" for p in ctx.players}
        _def_hide = sorted(pid for pid in _names
                           if _avail.get(pid, "Active")
                           in ("Out", "Injured", "Suspended"))
        _hide = st.multiselect(
            "Hide players (injured / suspended / won't play)", list(_names),
            default=_def_hide, format_func=lambda pid: _names.get(pid, str(pid)),
            key="scout_hide")
        sc = ctx.scout(ctx.team_id, ctx.gender, None, tuple(sorted(_hide)))
        if _hide:
            st.caption("Off the scouting list: "
                       + ", ".join(_names[p] for p in _hide if p in _names) + ".")

    # ── per-coach: pick what shows (this tab + the printable sheet) ───────────
    _hidden = set(filter(None,
                  (SU.get_setting("scout_hidden_sections", "") or "").split(",")))
    with st.expander("⚙ Customize sheet — pick what shows"):
        st.caption("Your picks save automatically and apply to this tab AND the "
                   "printable hand-out. Coach it your way.")
        _cc = st.columns(2)
        _new_hidden = set()
        for _i, (_k, _lbl) in enumerate(SCOUT_SECTIONS):
            _on = _cc[_i % 2].checkbox(_lbl, value=(_k not in _hidden),
                                       key=f"scout_sec_{_k}")
            if not _on:
                _new_hidden.add(_k)
        if _new_hidden != _hidden:
            SU.set_setting("scout_hidden_sections", ",".join(sorted(_new_hidden)))
            _hidden = _new_hidden
        st.caption("The printable sheet ends with a grid of blank half-courts — "
                   "write each play's name on the line and draw it by hand.")

    def _show(key):
        return key not in _hidden

    # Tier gate: the entire scouting report below is tracked-depth. ctx.has_tracked
    # is already gated for this team (Free -> off; Paid -> own team / pooled
    # opponents only), so blank the tracked header metrics and stop early when
    # it's off — leaving record & power rank (box-score) visible.
    trk = sc["trk"] if ctx.has_tracked else None
    hcols = st.columns(5)
    hcols[0].metric("Record", sc["record"])
    hcols[1].metric("Power rank", f"#{sc['rank']}/{sc['of']}")
    hcols[2].metric("Off. rating", f"{trk['ORtg']:.0f}" if trk else "—")
    hcols[3].metric("Def. rating", f"{trk['DRtg']:.0f}" if trk else "—")
    hcols[4].metric("Pace", f"{trk['Pace']:.0f}" if trk else "—")

    if not ctx.has_tracked:
        _, _lock = ENT.tracked_gate(AUTH.current_user(), ctx.team_id,
                                    sc["has_tracked"])
        st.warning(_lock or "No tracked-game data for this team — showing record "
                   "& ratings only. Track a game to unlock four factors, "
                   "tendencies & personnel.")
        return

    # ── keys to the game ─────────────────────────────────────────────────────
    if _show("keys"):
        k1, k2 = st.columns(2)
        with k1:
            st.markdown("<div class='lab-hdr'>How to guard them</div>",
                        unsafe_allow_html=True)
            for gtip in sc["guard"]:
                st.markdown(f"- {gtip}")
        with k2:
            st.markdown("<div class='lab-hdr'>How to attack them</div>",
                        unsafe_allow_html=True)
            for atip in sc["attack"]:
                st.markdown(f"- {atip}")

    # ── four factors & tendencies (the single four-factors block) ────────────
    if _show("four_factors") and sc["factors"]:
        st.markdown("<div class='lab-hdr'>Team profile — four factors & "
                    "tendencies</div>", unsafe_allow_html=True)
        ffx = [f for f in sc["factors"] if f["value"] is not None]
        ffig = go.Figure(go.Bar(
            x=[f["pct"] or 0 for f in ffx], y=[f["label"] for f in ffx],
            orientation="h",
            marker_color=[ctx.GOOD if (f["pct"] or 0) >= 60 else
                          (ctx.BAD if (f["pct"] or 0) <= 40 else "#8b949e")
                          for f in ffx],
            text=[f"{f['value']:.1f} · "
                  f"{('%.0f'%f['pct']) if f['pct'] is not None else '—'} pctl"
                  for f in ffx], textposition="auto", marker_line_width=0))
        ffig.add_vline(x=50, line=dict(color="#8b949e", width=1, dash="dot"))
        ffig.update_xaxes(title="League percentile", range=[0, 100])
        ctx.style(ffig, max(300, 40*len(ffx)))
        st.plotly_chart(ffig, width="stretch", key="scout_factors")
        st.caption("Green bars ≥60th percentile (a strength); red ≤40th (exploit). "
                   "The percentile bar replaces the old strengths/exploit lists.")

        # ── identity & tendencies (a couple meaningful extra reads) ─────────
        if ctx.has_tracked:
            crb_sc = ctx.bundle["creation_breakdown"]
            tot_fga = crb_sc["total"]["FGA"] or 1
            self_sh = 100 * (crb_sc["self"]["FGA"]
                             + crb_sc["created"]["FGA"]) / tot_fga
            pass_sh = 100 * (crb_sc["pass"]["FGA"]
                             + crb_sc["both"]["FGA"]) / tot_fga
            pace_v = ctx.summ.get("POSS_pg", 0)
            tm = st.columns(4)
            tm[0].metric("Pace", f"{pace_v:.0f}", help="Possessions / game.")
            tm[1].metric("Paint scoring", ctx.pctf(ctx.soff["pct_paint"]),
                         help="Share of points scored in the paint.")
            tm[2].metric("Self-created FG", f"{self_sh:.0f}%",
                         help="Share of FGA the shooter made/took without a pass "
                              "into the shot.")
            tm[3].metric("Contested rate",
                         ctx.pctf(ctx.bundle["guarded"]["guard_share"]),
                         help="Share of their shots that were contested.")
            tempo = ("up-tempo" if pace_v >= 70 else
                     "controlled" if pace_v >= 60 else "slow, grind-it-out")
            style = ("isolation / shot-maker heavy" if self_sh >= 55 else
                     "ball-movement / motion" if pass_sh >= 60 else
                     "balanced shot creation")
            inside = ("paint-oriented" if ctx.soff["pct_paint"] >= 0.5 else
                      "perimeter / 3-happy" if ctx.brk["3PAr"] >= 0.40 else "two-level")
            st.markdown(f"**Style read:** {tempo} pace · {style} · {inside} attack "
                        f"— {self_sh:.0f}% of shots self-created, {pass_sh:.0f}% "
                        "off a pass. Speeding them up or walling the paint attacks "
                        "the profile above.")

    # ── should they shoot more 3s or 2s? ─────────────────────────────────────
    if _show("breakeven"):
        st.markdown("<div class='lab-hdr'>Should they shoot more 3s or 2s?"
                    "</div>", unsafe_allow_html=True)
        bm = st.columns(4)
        bm[0].metric("2P%", ctx.pctf(ctx.brk["2P%"]))
        bm[1].metric("3P%", ctx.pctf(ctx.brk["3P%"]))
        bm[2].metric("Breakeven 3P%", ctx.pctf(ctx.brk["be3"]),
                     help="The 3P% at which a three equals their current two.")
        bm[3].metric("3PA rate", ctx.pctf(ctx.brk["3PAr"]),
                     help="Share of FG attempts that are threes.")

        evfig = go.Figure(go.Bar(
            x=["Per 2-pt attempt", "Per 3-pt attempt"],
            y=[ctx.brk["ev2"], ctx.brk["ev3"]],
            marker_color=[ctx.ACCENT, ctx.BLUE], marker_line_width=0,
            text=[f"{ctx.brk['ev2']:.2f}", f"{ctx.brk['ev3']:.2f}"],
            textposition="auto"))
        evfig.update_yaxes(title="Expected points per attempt")
        ctx.style(evfig, 300)
        st.plotly_chart(evfig, width="stretch", key="in_ev")

        diff = ctx.brk["edge"]
        if abs(diff) < 0.03:
            st.info(
                f"Their 2s and 3s pay off **about equally** ({ctx.brk['ev3']:.2f} vs "
                f"{ctx.brk['ev2']:.2f} pts/shot). Shot selection is balanced — keep "
                "taking the open look.")
        elif diff > 0:
            st.success(
                f"**Shoot more 3s.** Each three returns {ctx.brk['ev3']:.2f} pts vs "
                f"{ctx.brk['ev2']:.2f} for a two — a **+{diff:.2f}** edge. They clear "
                f"the {ctx.brk['be3']*100:.0f}% breakeven ({ctx.brk['3P%']*100:.0f}% "
                f"actual) and only {ctx.brk['3PAr']*100:.0f}% of their shots are "
                "threes.")
        else:
            st.warning(
                f"**Shoot more 2s.** A two returns {ctx.brk['ev2']:.2f} pts vs "
                f"{ctx.brk['ev3']:.2f} for a three ({diff:.2f}). Their "
                f"{ctx.brk['3P%']*100:.0f}% from deep is below the "
                f"{ctx.brk['be3']*100:.0f}% breakeven — work for higher-value twos, "
                f"especially in the paint ({ctx.soff['pct_paint']*100:.0f}% of points "
                "come there).")

    # ── per-player 3-point profile ───────────────────────────────────────────
    if _show("three_profile"):
        st.markdown("<div class='lab-hdr'>Per-player 3-point profile</div>",
                    unsafe_allow_html=True)
        three_p = [p for p in ctx.players if p["3PA"] and p["3PA"] >= 4]
        if three_p:
            be3_pct = ctx.brk["be3"] * 100
            tp = go.Figure()
            tp.add_trace(go.Bar(
                x=[f"#{p['number']} {p['name']}" for p in
                   sorted(three_p, key=lambda p: p["3PA"], reverse=True)],
                y=[p["3P%"] for p in
                   sorted(three_p, key=lambda p: p["3PA"], reverse=True)],
                marker_color=[ctx.GOOD if (p["3P%"] or 0) >= be3_pct else ctx.BAD
                              for p in sorted(three_p, key=lambda p: p["3PA"],
                                              reverse=True)],
                marker_line_width=0,
                text=[f"{p['3P%']:.0f}% ({p['3PA']} att)" for p in
                      sorted(three_p, key=lambda p: p["3PA"], reverse=True)],
                textposition="auto"))
            tp.add_hline(y=be3_pct, line=dict(color=ctx.ACCENT, dash="dot"),
                         annotation_text=f"breakeven {be3_pct:.0f}%")
            tp.update_yaxes(title="3P%")
            tp.update_xaxes(tickangle=-30)
            ctx.style(tp, 320)
            st.plotly_chart(tp, width="stretch", key="in_3pt")
            st.caption("Green = above the team's breakeven 3P% (their threes beat "
                       "their twos); red = below. Min 4 attempts.")
        else:
            st.caption("Not enough 3-point volume to profile shooters yet.")

    # ── auto scouting report ──────────────────────────────────────────────────
    if _show("auto_report"):
        st.markdown("<div class='lab-hdr'>Scouting report</div>",
                    unsafe_allow_html=True)
        tips = _auto_report_tips(ctx)
        if tips:
            for t in tips:
                st.markdown(f"- {t}")
        else:
            st.caption("A balanced profile — no single factor stands out as a "
                       "scouting key.")

    # ── efficiency summary ────────────────────────────────────────────────────
    if _show("efficiency"):
        st.markdown("<div class='lab-hdr'>Efficiency summary</div>",
                    unsafe_allow_html=True)
        st.markdown(
            f"- **Offense:** {ctx.summ.get('ORtg', 0):.1f} pts / 100 poss on "
            f"{ctx.pctf(ctx.ff['off']['eFG'])} eFG; turns it over on "
            f"{ctx.pctf(ctx.ff['off']['TOV'])} of trips and rebounds "
            f"{ctx.pctf(ctx.ff['off']['ORB'])} of its own misses.")
        st.markdown(
            f"- **Defense:** {ctx.summ.get('DRtg', 0):.1f} pts / 100 poss allowed on "
            f"{ctx.pctf(ctx.ff['def']['eFG'])} eFG; forces a turnover on "
            f"{ctx.pctf(ctx.ff['def']['TOV'])} of opponent trips.")
        st.markdown(
            f"- **Tempo:** {ctx.summ.get('POSS_pg', 0):.1f} possessions/game — "
            + ("an up-tempo team." if ctx.summ.get("POSS_pg", 0) >= 70
               else "a controlled pace." if ctx.summ.get("POSS_pg", 0) >= 60
               else "a slow, grind-it-out pace."))

    # ── personnel ────────────────────────────────────────────────────────────
    if _show("personnel") and sc["personnel"]:
        st.markdown("<div class='lab-hdr'>Personnel</div>", unsafe_allow_html=True)
        sc_arch = ctx.archetypes(ctx.gender)
        prow_by_name = {p["name"]: p for p in ctx.players}
        for p in sc["personnel"]:
            bdg = "  ".join(p["badges"])
            row = prow_by_name.get(p["name"])
            archlbl = sc_arch.get(row["_pid"]) if row else None
            usg = row.get("USG%") if row else None
            selfcr = row.get("SelfCr%") if row else None
            q4 = row.get("Q4PPG") if row else None
            extra = []
            if usg is not None:
                extra.append(f"USG {usg:.0f}%")
            if selfcr is not None:
                extra.append(f"self-cr {selfcr:.0f}%")
            if q4 is not None:
                extra.append(f"Q4 {q4:.1f} ppg")
            extra_html = (f"<br><span style='font-size:12px;color:#8b949e'>"
                          f"{' · '.join(extra)}</span>" if extra else "")
            # how the player gets their shots (SC / Pass / Screen / Both)
            cm = p.get("creation")
            src_html = ""
            if _show("shot_source") and cm:
                _src = " · ".join(f"{lbl} {cm[k]:.0f}%" for k, lbl in
                                  (("self", "SC"), ("pass", "Pass"),
                                   ("screen", "Screen"), ("both", "Both"))
                                  if k in cm)
                src_html = (f"<br><span style='font-size:12px;color:#8b949e'>"
                            f"▦ Shots: {_src}</span>")
            # play-type tags per player (one-tap set calls): top 4, share of tagged
            pm = p.get("playmix")
            play_html = ""
            if _show("play_calls") and pm:
                _pl = " · ".join(f"{lbl} {pct:.0f}%" for lbl, pct in pm[:4])
                play_html = (f"<br><span style='font-size:12px;color:#8b949e'>"
                             f"▶ Plays: {html.escape(_pl)} "
                             f"(n={p['playmix_n']})</span>")
            arch_html = (f" <span class='stat-chip' style='font-size:11px'>"
                         f"{html.escape(archlbl)}</span>" if archlbl else "")
            # who normally starts + the 0-100 category breakdown behind OVERALL
            gs_txt = (f" · Starts {p['gs_pct']:.0f}%"
                      if p.get("gs_pct") is not None else "")
            _bd = " · ".join(
                f"{lbl} {p.get(k)}" for k, lbl in
                (("off", "Off"), ("def", "Def"), ("ply", "Ply"), ("reb", "Reb"))
                if p.get(k) is not None)
            bd_html = (f"<br><span style='font-size:12px;color:#8b949e'>{_bd}</span>"
                       if _bd else "")
            # measurables: height · weight · wingspan · hand
            pos_html = (f" <span style='color:#8b949e;font-size:12px'>"
                        f"{html.escape(p['pos'])}</span>" if p.get("pos") else "")
            bio_html = (f"<br><span style='font-size:12px;color:#8b949e'>"
                        f"{html.escape(p['bio'])}</span>" if p.get("bio") else "")
            # tactical cues: force-hand + space dependence (the data-rich reads)
            _cues = []
            if p.get("hand") and p["hand"].get("cue"):
                _cues.append(p["hand"]["cue"])
            if p.get("space") and p["space"].get("cue"):
                _cues.append(p["space"]["cue"])
            cues_html = ("<br><span class='badge accent' style='font-size:11px'>✋ "
                         + " · ".join(html.escape(c) for c in _cues)
                         + "</span>" if _cues else "")
            st.markdown(
                f"<div class='glass-tile' style='margin-bottom:8px'>"
                f"<b>#{p['num']} {html.escape(p['name'])}</b>{pos_html} "
                f"<span style='color:#8b949e'>OVR "
                f"{p['ovr'] if p['ovr'] is not None else '—'}{gs_txt}</span>"
                f"{arch_html}{bd_html}{bio_html}<br>"
                f"<span style='font-size:13px'>{(p['ppg'] or 0):.1f} ppg · "
                f"{(p['rpg'] or 0):.1f} reb · {(p['apg'] or 0):.1f} ast · "
                f"3P {('%.0f%%'%p['tp']) if p['tp'] is not None else '—'} · "
                f"TS {('%.0f%%'%p['ts']) if p['ts'] is not None else '—'}</span>"
                f"{extra_html}{src_html}{play_html}<br>"
                f"<span style='color:{ctx.ACCENT};font-size:13px'>▶ "
                f"{html.escape(p['note'])}</span>"
                + cues_html
                + (f"<br><span style='font-size:12px;color:#8b949e'>"
                   f"{html.escape(bdg)}</span>" if bdg else "")
                + "</div>", unsafe_allow_html=True)

    # ── how they get their shots: tagged play calls (one-tap from tracker) ───
    if _show("play_calls"):
        st.markdown("<div class='lab-hdr'>How they get their shots — play calls"
                    "</div>", unsafe_allow_html=True)
        pc = sc.get("play_calls")
        if pc and pc.get("rows"):
            import pandas as pd
            _pcrows = sorted(pc["rows"], key=lambda r: r["share"], reverse=True)
            st.dataframe(pd.DataFrame([{
                "Play call": r["label"], "Share": r["share"] * 100,
                "PPP": r["PPP"], "FG%": r["FG%"] * 100, "Poss": r["poss"],
            } for r in _pcrows]), hide_index=True, width="stretch",
                column_config={
                    "Share": st.column_config.NumberColumn("Share", format="%.0f%%"),
                    "PPP": st.column_config.NumberColumn("PPP", format="%.2f"),
                    "FG%": st.column_config.NumberColumn("FG%", format="%.0f%%"),
                })
            st.caption(
                f"Coach-tagged set calls on {pc['total_tagged']} shots "
                f"({pc['untagged']} untagged) — share = % of tagged shots, PPP = "
                "points per possession. Separate from the inferred shot-source mix "
                "on each personnel card; tag plays one-tap in the Game Tracker.")
        else:
            st.caption("No play-call tags yet — tap an optional **Play type** "
                       "(Pick & roll, Iso, Post-up…) on shots in the Game Tracker "
                       "to scout how a team generates offense.")

    # ── where they shoot from (real x/y chart when tap data exists) ──────────
    if _show("shot_chart"):
        _sc_shots = ctx.located_team(ctx.team_id, tuple(ctx.bundle["tracked_ids"]))
        if _sc_shots:
            st.markdown("<div class='lab-hdr'>Shot chart</div>",
                        unsafe_allow_html=True)
            _scf, _ = _shot_map(_sc_shots,
                                title=f"{len(_sc_shots)} located attempts")
            st.plotly_chart(_scf, width="stretch", key="scout_shotmap")
            st.caption("Every tap-captured attempt this season — the spots to "
                       "take away.")
            _sc_db = S.distance_buckets(_sc_shots)
            if _sc_db:
                st.caption("By length — " + S.distance_buckets_caption(_sc_db))

    # ── shooting by zone (2s vs 3s) ─────────────────────────────────────────
    if _show("zones") and ctx.bundle.get("zones_by_type"):
        st.markdown("<div class='lab-hdr'>Shooting by zone — 2s vs 3s</div>",
                    unsafe_allow_html=True)
        zbt_sc = ctx.bundle["zones_by_type"]["off"]
        sz1, sz2 = st.columns(2)
        with sz1:
            st.markdown("**Attempts by zone**")
            st.plotly_chart(ctx.zone_pair_bars(
                zbt_sc["2"], zbt_sc["3"], "2-pt", "3-pt",
                lambda a: a["FGA"], "Attempts",
                text_fn=lambda a: a["FGA"] or ""),
                width="stretch", key="scout_zones_a")
        with sz2:
            st.markdown("**FG% by zone**")
            st.plotly_chart(ctx.zone_pair_bars(
                zbt_sc["2"], zbt_sc["3"], "2P%", "3P%",
                lambda a: a["FG%"] * 100, "FG%",
                text_fn=lambda a: f"{a['FG%']*100:.0f}%" if a["FGA"] else "—"),
                width="stretch", key="scout_zones_fg")
        st.caption("Where they shoot and how they finish, split by shot value.")
    elif _show("zones") and sc["zones"] and any(z["FGA"] for z in sc["zones"].values()):
        st.markdown("<div class='lab-hdr'>Shooting by zone</div>",
                    unsafe_allow_html=True)
        zfig = go.Figure(go.Bar(
            x=[SC.ZONE_LABELS[z] for z in S.ZONES],
            y=[sc["zones"][z]["FGA"] for z in S.ZONES],
            marker_color=ctx.ACCENT, marker_line_width=0,
            text=[f"{sc['zones'][z]['FGM']}/{sc['zones'][z]['FGA']} · "
                  f"{sc['zones'][z]['pct']:.0f}%" for z in S.ZONES],
            textposition="auto"))
        zfig.update_yaxes(title="Attempts")
        ctx.style(zfig, 320)
        st.plotly_chart(zfig, width="stretch", key="scout_zones")

    # ── scoring by possession length (when tracked) ──────────────────────────
    if _show("poss_length") and ctx.bundle.get("poss_length"):
        _plen = [r for r in ctx.bundle["poss_length"]
                 if r["label"] != "Untimed" and r["FGA"]]
        if _plen:
            st.markdown("<div class='lab-hdr'>Scoring by possession length</div>",
                        unsafe_allow_html=True)
            _plf = go.Figure(go.Bar(
                x=[r["label"] for r in _plen], y=[r["PPP"] for r in _plen],
                marker_color=ctx.ACCENT, marker_line_width=0,
                text=[f"{r['PPP']:.2f} · {r['FGA']} FGA · {r['FG%'] * 100:.0f}%"
                      for r in _plen], textposition="auto"))
            _plf.update_yaxes(title="Points per shot")
            ctx.style(_plf, 300)
            st.plotly_chart(_plf, width="stretch", key="scout_plen")
            st.caption("How they score by tempo — transition (≤6s) vs early vs "
                       "half-court. If they spike in transition, get back on "
                       "defense; if half-court is weak, make them play in a crowd.")

    # ── game-plan notes (opponent scout) ─────────────────────────────────────
    if not _self and _show("notes"):
        st.markdown("<div class='lab-hdr'>Game-plan notes</div>",
                    unsafe_allow_html=True)
        SB.render_notes(ctx.team_id)

    # ── printable export (always available; honours the section picks above) ──
    # Page-derived blocks the build_scout engine doesn't own, fed to the printable
    # sheet so it reaches parity with this tab (breakeven, efficiency, auto-report,
    # 3-pt profile, possession length, notes) + the blank-diagram layout choice.
    _extra = {
        "breakeven": {
            "2P%": ctx.brk["2P%"], "3P%": ctx.brk["3P%"], "be3": ctx.brk["be3"],
            "3PAr": ctx.brk["3PAr"], "ev2": ctx.brk["ev2"], "ev3": ctx.brk["ev3"],
            "edge": ctx.brk["edge"], "pct_paint": ctx.soff["pct_paint"],
        },
        "efficiency": {
            "ORtg": ctx.summ.get("ORtg", 0), "DRtg": ctx.summ.get("DRtg", 0),
            "POSS_pg": ctx.summ.get("POSS_pg", 0),
            "off_eFG": ctx.ff["off"]["eFG"], "off_TOV": ctx.ff["off"]["TOV"],
            "off_ORB": ctx.ff["off"]["ORB"], "def_eFG": ctx.ff["def"]["eFG"],
            "def_TOV": ctx.ff["def"]["TOV"],
        },
        "auto_report": _auto_report_tips(ctx),
        "three_profile": _three_profile(ctx),
        "poss_length": [r for r in (ctx.bundle.get("poss_length") or [])
                        if r["label"] != "Untimed" and r["FGA"]],
        "notes": ("" if _self else SB.get_note(ctx.team_id)),
    }
    st.markdown("<div class='lab-hdr'>Printable scout sheet</div>",
                unsafe_allow_html=True)
    html_doc = SC.printable_html(sc, opp_label, hidden=_hidden, extra=_extra)
    from helpers.ui import pdf_or_html_download
    pdf_or_html_download("Scout sheet", html_doc,
                         f"scout_{sc['name'].replace(' ', '_')}",
                         key="scout_dl")
    with st.expander("Preview printable sheet"):
        components.html(html_doc, height=620, scrolling=True)
