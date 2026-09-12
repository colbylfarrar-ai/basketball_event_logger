"""
dashboard/scout_deep.py — the engines that were already paid for, aimed at the
opponent.

Every read here is computed and shipped somewhere else in the app. The Insights
tab runs thirteen ported engines as a SELF-scout; the Scout tab rebinds its
whole ctx onto the opponent (`ctx.opp_ctx(tid)`), so the identical engine call
answers the opposite question — and the Scout tab was not making it. Aimed at
them, "our 10-0 runs start off live-ball turnovers" becomes "don't let the game
get away from you, and here is the mechanism". `helpers/exploit` is the most
scout-shaped engine in the codebase and lived only in the War Room.

Nothing in this module computes a new number. It calls existing engines with the
opponent's id and the opponent's read-filtered game ids, and writes the coach-
facing sentence for the other direction. The entitlement filter rides in on
`ctx.tracked_ids` / `ctx.season_gp`, which `_opp_scout_ctx` already scoped — an
EMPTY pool stays empty here and is reported as "nothing you can see", never
widened.

Print parity: `print_blocks()` returns the same reads as plain (badge, n, html)
lines so `helpers.scout.printable_html` can put the identical sentences on paper.
"""
from __future__ import annotations

import html as _html

import streamlit as st

import helpers.ui as _UI
import helpers.cards as CARDS
import helpers.pronouns as PRON

e = _html.escape


# ── which ported engines mean something aimed at an OPPONENT ─────────────────
#: key -> (header, what it becomes when the subject is the other team)
#:
#: Not every self-scout read inverts. Monday is the coach's own to-do list,
#: Receipts audits our own engines and `deserved` is a statement about our
#: results — those are self-scout by construction and are deliberately absent.
OPP_SECTIONS = (
    ("clock", "⏱️ Their foul clock — when their bench decision arrives",
     "The median game-clock stamp of each of their players' fouls. Attack the "
     "name at the top of this list early: the decision keeps arriving for "
     "{obj}, and their coach has to make it."),
    ("fouls", "⚖️ What foul trouble costs them",
     "Floor time they lose after the Nth foul, and their net in each foul "
     "state — what you actually buy by drawing one."),
    ("anatomy", "🔬 Run anatomy — how their swings start",
     "What each 10-0 stretch of theirs was made of: the event that handed them "
     "the ball, the defense on the floor and who was out there. This is "
     "\"don't let the game get away from you\" with the mechanism attached."),
    ("scheme", "🛡️ What slows their offense",
     "Their offense grouped by the coverage it faced, normalized against the "
     "league's own use of that scheme — the verdict behind the raw "
     "defenses-faced table."),
    ("tovs", "🔄 Their giveaway mix — what to sit on",
     "Their dominant tagged turnover kind. The engine's own description calls "
     "this \"what an opposing defence sits on\"; it had only ever shipped on "
     "the self-scout."),
    ("hero", "🎯 Their ball share — how star-dependent they are",
     "How concentrated their scoring is across the rotation. Never a "
     "judgement: a team with one elite scorer should funnel."),
    ("involve", "🔗 Their glue — who makes it go without scoring",
     "Share of their scoring plays a player touches in ANY role — scorer, "
     "passer, screener, rebounder. Answers \"who do we actually have to take "
     "away\" when it is not the leading scorer."),
    ("stops", "🛑 Do they answer back?",
     "How often they string defensive stops together, and whether they respond "
     "straight after conceding — whether a 6-0 run of yours actually buys "
     "anything."),
    ("reb", "🏀 Their glass identity",
     "Plain-word rebounding read for their biggest rebounders, ranked within "
     "their own team — who to put a body on."),
    ("runs", "📈 Their runs — the swing count behind close results",
     "Runs they put together against runs they conceded, and their record "
     "split by how many they managed."),
    ("ledger", "📒 How their possessions end",
     "Every possession classified by how it finished, on both ends, with the "
     "scoring sources behind it."),
)

#: The subset worth printing by default — the ones that change a game plan
#: rather than describe a season.
PRINT_KEYS = ("clock", "scheme", "tovs", "anatomy", "involve")


def opp_sections(pron):
    """OPP_SECTIONS with this league's pronouns filled into the captions.

    The captions are stored with `{obj}`-style placeholders rather than a
    hard-coded "her": one of them names an opposing player, and the scout is
    read by boys' coaches as often as girls'. `str.format` is safe here because
    the only braces in these strings are the placeholders themselves.
    """
    return tuple(
        (k, h, c.format(subj=pron.subj, obj=pron.obj, poss=pron.poss))
        for k, h, c in OPP_SECTIONS)


def _lines(ctx, fp=None):
    """`{key: [(badge, n, html)]}` for the opponent, or {} when nothing is
    visible. One cached pass; each engine is isolated inside `_ported`, so a
    raising engine contributes nothing and the rest still render."""
    tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    tid = getattr(ctx, "team_id", None)
    if not (tid and tids):
        return {}
    from helpers.dashboard import insights_deep as _DEEP
    out, _diag = _DEEP._ported(tid, ctx.gender, tids, fp=fp)
    return out or {}


def print_blocks(ctx, fp=None, keys=PRINT_KEYS):
    """`[(header, [(badge, n, html)])]` for the printable sheet — the same
    sentences the tab renders, so the hand-out cannot say something the screen
    does not."""
    got = _lines(ctx, fp=fp)
    hdrs = {k: h for k, h, _c in OPP_SECTIONS}
    return [(hdrs[k], got[k]) for k in keys if got.get(k)]


def render_ported(ctx, fp=None):
    """The ported engines, aimed at the opponent, verdict-first."""
    got = _lines(ctx, fp=fp)
    if not got:
        st.caption("No tracked games of this opponent are visible to you, so "
                   "the engine reads below have nothing to run on. The "
                   "hand-entered scouting and the matchup planner still work.")
        return
    _secs = opp_sections(PRON.for_gender(getattr(ctx, "gender", None)))
    shown = [(k, h, c) for k, h, c in _secs if got.get(k)]
    for key, header, cap in shown:
        st.markdown(f"<div class='lab-hdr'>{header}</div>",
                    unsafe_allow_html=True)
        st.markdown(CARDS.verdict_card(got[key]), unsafe_allow_html=True)
        st.caption(cap)
    _missing = [h for k, h, _c in OPP_SECTIONS if not got.get(k)]
    if _missing:
        st.caption(f"{len(_missing)} more engine reads had nothing to say about "
                   "this opponent on the games you can see — they fill in as "
                   "the book grows, and as play types and defenses get tagged.")


# ── the game plan: our sets × their vulnerability, and what to play on D ──────
def game_plan(ctx, my_team_id, my_game_ids=None):
    """`exploit.game_plan` for this matchup, or None.

    Data only, deliberately: the printable needs the same plan the tab draws,
    and a builder that renders as a side effect cannot be called from a lazy
    download without painting a second copy of the section onto the page.
    """
    opp_tid = getattr(ctx, "team_id", None)
    if not (my_team_id and opp_tid and my_team_id != opp_tid):
        return None
    try:
        import helpers.exploit as EX
        return EX.game_plan(my_team_id, opp_tid, gender=ctx.gender,
                            my_game_ids=my_game_ids,
                            opp_game_ids=getattr(ctx, "season_gp", None))
    except Exception:
        return None


def render_game_plan(ctx, my_team_id, my_game_ids=None, fp=None, plan=None):
    """`exploit.game_plan` — the most scout-shaped engine in the codebase, and
    until now the Scout tab did not import it.

    It is correctly absent from Insights (self-scout by charter) and it lived
    only behind the War Room's own view, two pages from the sheet a coach
    actually carries. `offensive_exploits` is our set-call efficiency × their
    vulnerability to the same set; `defensive_plan` is what to play on D.
    """
    if plan is None:
        plan = game_plan(ctx, my_team_id, my_game_ids=my_game_ids)
    if not plan:
        st.caption("No game plan yet — it needs tagged play types or defenses "
                   "on both sides of this matchup.")
        return None

    off, dfn = plan["offense"], plan["defense"]
    st.markdown("<div class='lab-hdr'>Call sheet — what to run, what to play"
                "</div>", unsafe_allow_html=True)

    _v = []
    _stable = [r for r in off["rows"] if r["stable"]]
    _best = (_stable or off["rows"] or [None])[0]
    if _best:
        _v.append((
            "Lean on it", _best["our_poss"] + _best["opp_poss"],
            f"Run <b>{e(_best['label'])}</b>: you get "
            f"{_best['our_ppp']:.2f} PPP from it and they give up "
            f"{_best['opp_ppp']:.2f} to it"
            + ("" if _best["stable"] else
               " — <i>below the volume bar on one side, so a lean, not a rule</i>")
            + "."))
    if dfn["throw"]:
        _t = dfn["throw"][0]
        _v.append((
            "Play this D", _t["poss"],
            f"Throw <b>{e(_t['label'])}</b> at them — they score only "
            f"{_t['ppp']:.2f} PPP against it."))
    if dfn["avoid"]:
        _a = dfn["avoid"][0]
        _v.append((
            "Don't sit in", _a["poss"],
            f"<b>{e(_a['label'])}</b> is what they shred "
            f"({_a['ppp']:.2f} PPP) — don't live in it."))
    if _v:
        st.markdown(CARDS.verdict_card(_v), unsafe_allow_html=True)

    import pandas as pd
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Your sets vs their coverage**")
        if off["rows"]:
            st.dataframe(pd.DataFrame([{
                "Set": r["label"], "Your PPP": r["our_ppp"],
                "PPP on them": r["opp_ppp"],
                "Their weakness": r["opp_vuln_pct"],
                "Poss (you / them)": f"{r['our_poss']} / {r['opp_poss']}",
                "Solid": "✓" if r["stable"] else "",
            } for r in off["rows"][:8]]), hide_index=True, width="stretch",
                column_config={
                    "Your PPP": st.column_config.NumberColumn(format="%.2f"),
                    "PPP on them": st.column_config.NumberColumn(format="%.2f"),
                    "Their weakness": st.column_config.NumberColumn(
                        format="%.0f", help="Their defensive percentile on this "
                                            "set, inverted — higher = softer."),
                })
        st.caption(off["note"])
    with c2:
        st.markdown("**What to play on defense**")
        _rows = ([{"Scheme": r["label"], "Their PPP": r["ppp"],
                   "Poss": r["poss"], "Call": "Throw it"} for r in dfn["throw"]]
                 + [{"Scheme": r["label"], "Their PPP": r["ppp"],
                     "Poss": r["poss"], "Call": "Avoid"} for r in dfn["avoid"]])
        if _rows:
            st.dataframe(pd.DataFrame(_rows), hide_index=True, width="stretch",
                         column_config={"Their PPP":
                                        st.column_config.NumberColumn(
                                            format="%.2f")})
        if dfn["their_leaks"]:
            st.markdown("**Their own schemes, by what they give up**")
            st.dataframe(pd.DataFrame([{
                "Scheme": r["label"], "PPP allowed": r["ppp_allowed"],
                "Poss": r["poss"]} for r in dfn["their_leaks"]]),
                hide_index=True, width="stretch",
                column_config={"PPP allowed":
                               st.column_config.NumberColumn(format="%.2f")})
        st.caption(dfn["note"])
    return plan


def game_plan_print(plan):
    """`[(badge, n, html)]` — the three game-plan verdicts for the sheet."""
    if not plan:
        return []
    off, dfn = plan["offense"], plan["defense"]
    out = []
    _stable = [r for r in off["rows"] if r["stable"]]
    _best = (_stable or off["rows"] or [None])[0]
    if _best:
        out.append(("Lean on it", _best["our_poss"] + _best["opp_poss"],
                    f"Run <b>{e(_best['label'])}</b> — you get "
                    f"{_best['our_ppp']:.2f} PPP from it, they give up "
                    f"{_best['opp_ppp']:.2f} to it."))
    if dfn["throw"]:
        _t = dfn["throw"][0]
        out.append(("Play this D", _t["poss"],
                    f"Throw <b>{e(_t['label'])}</b> — they score "
                    f"{_t['ppp']:.2f} PPP against it."))
    if dfn["avoid"]:
        _a = dfn["avoid"][0]
        out.append(("Don't sit in", _a["poss"],
                    f"<b>{e(_a['label'])}</b> is what they shred "
                    f"({_a['ppp']:.2f} PPP)."))
    return out


# ── per-defender on-ball D: the real measurement behind the matchup planner ───
def render_defender_profiles(my_team_id, gender, my_game_ids=None):
    """`exploit.defender_profiles` — measured per-defender on-ball defense from
    the `guarded_by_id` tag.

    The matchup planner prices its edges off generic 0-100 OFF vs DEF ratings.
    This is what your defenders have actually allowed on shots they contested,
    and it is the honest second opinion on the assignment. Self-hides with a
    note until `guarded by` coverage exists — the tag is opt-in per shot.
    """
    try:
        import helpers.exploit as EX
        prof = EX.defender_profiles(my_team_id, gender=gender,
                                    game_ids=my_game_ids)
    except Exception:
        return
    if not prof["rows"]:
        st.caption(prof["note"])
        return
    import pandas as pd
    st.markdown("**Your defenders — what they actually allow**")
    st.dataframe(pd.DataFrame([{
        "Defender": r["name"], "Contested": r["contested"],
        "FG% allowed": (r["FGpct"] or 0) * 100,
        "Pts/shot allowed": r["PPS"],
        "2s": r["twos"], "2P% allowed": (r["twos_pct"] or 0) * 100,
        "3s": r["threes"], "3P% allowed": (r["threes_pct"] or 0) * 100,
    } for r in prof["rows"]]), hide_index=True, width="stretch",
        column_config={
            "FG% allowed": st.column_config.NumberColumn(format="%.0f%%"),
            "2P% allowed": st.column_config.NumberColumn(format="%.0f%%"),
            "3P% allowed": st.column_config.NumberColumn(format="%.0f%%"),
            "Pts/shot allowed": st.column_config.NumberColumn(format="%.2f"),
        })
    st.caption(prof["note"])


# ── the opponent masthead: rest, record, and the style identity ──────────────
def render_deck(ctx, sc):
    """The header strip. Scout's was five bare `st.metric`s; Insights leads with
    a masthead that carries rest days and the scope note, and the Charts Lab has
    a team-DNA rail. Both are already computed — this spends them."""
    bits = []
    try:
        import helpers.fatigue as FT
        from database.db import query
        _nxt = query(
            "SELECT date FROM games WHERE (team1_id=? OR team2_id=?) "
            "AND date >= date('now') ORDER BY date LIMIT 1",
            (ctx.team_id, ctx.team_id))
        if _nxt:
            _rest = FT.rest_on_date(ctx.team_id, _nxt[0]["date"])
            if _rest is not None:
                bits.append(
                    ("Rest", None,
                     f"They come into {e(str(_nxt[0]['date']))} on "
                     f"<b>{_rest} day{'s' if _rest != 1 else ''}</b> of rest"
                     + (" — a back-to-back." if _rest <= 1 else ".")))
    except Exception:
        pass
    # Identity off the four-factor profile that is already on the sheet: their
    # single best and single worst percentile, named. Cheaper than a second
    # clustering pass and it says the same thing a DNA rail would.
    _rated = [f for f in (sc.get("factors") or [])
              if f.get("pct") is not None and f.get("value") is not None]
    if _rated:
        _hi = max(_rated, key=lambda f: f["pct"])
        _lo = min(_rated, key=lambda f: f["pct"])
        _n_pool = _hi.get("n")
        if _hi["label"] != _lo["label"]:
            _hb, _, _ = CARDS._pctile_badge(_hi["pct"], _n_pool)
            _lb, _, _ = CARDS._pctile_badge(_lo["pct"], _n_pool)
            bits.append((
                "Identity", _n_pool,
                f"Strongest: <b>{e(_hi['label'])}</b> ({_hb}). Softest: "
                f"<b>{e(_lo['label'])}</b> ({_lb}) — start the game plan there."))
    _n = len(getattr(ctx, "tracked_ids", None) or ())
    bits.append(("Book", _n,
                 f"<b>{sc['record']}</b> · power #{sc['rank']} of {sc['of']} · "
                 f"{_n} tracked game{'s' if _n != 1 else ''} visible to you"))
    if bits:
        st.markdown(CARDS.verdict_card(bits), unsafe_allow_html=True)


# ── per-player depth on the personnel card ───────────────────────────────────
def player_depth(ctx, fp=None):
    """`{pid: [(badge, n, html)]}` — the reads that make ONE opponent player
    different from the next, for the personnel cards.

    The card prints the same eight fields for every player whether or not those
    fields are what makes that player dangerous. Two things fix most of it:

      * **recent form.** The scout is season-flat today — a player who has been
        cold for three weeks reads identically to one who is on fire. One delta
        per player.
      * **the foul clock.** The median game-clock stamp of her second foul is a
        weapon no other high-school product has, and it was already computed for
        the Insights tab. Trouble is measured against the QUARTER, and a carried
        foul compares her to her own clean quarters — the semantics come from
        the engine, they are not re-derived here.
    """
    tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    if not tids:
        return {}
    out = {}
    pr = PRON.for_gender(getattr(ctx, "gender", None))

    # foul clock, per player
    try:
        import helpers.foul_trouble as FT
        import helpers.stats as S
        from database.db import query
        names = {r["id"]: r["name"] for r in query(
            "SELECT id, name FROM players WHERE team_id=?", (ctx.team_id,))}
        ev = S.fetch_events(list(tids))
        clock = FT.foul_clock(game_ids=list(tids), events=ev,
                              team_id=ctx.team_id)
        for pid, per_level in (clock or {}).items():
            d = per_level.get(2)
            if not d or d["n"] < FT.MIN_GAMES_AT_LEVEL:
                continue
            share = d["pre_half"] / d["n"]
            out.setdefault(pid, []).append((
                "2nd foul", d["n"],
                f"{pr.v('picks')} up {pr.poss} second at "
                f"<b>{FT.clock_label(d['median'])}</b> "
                f"on a typical night"
                + (f" — <b>{d['pre_half']} of {d['n']}</b> land before the half."
                   if share >= 0.5 else ".")))
        del names
    except Exception:
        pass

    # last-5 vs season scoring form
    try:
        import helpers.stats as S
        boxes = S.player_game_boxes(game_ids=list(tids))
        for pid, by_gid in (boxes or {}).items():
            pts = [b.get("PTS", 0) for _g, b in sorted(by_gid.items())]
            if len(pts) < 5:
                continue
            season = sum(pts) / len(pts)
            last5 = sum(pts[-5:]) / 5.0
            d = last5 - season
            if abs(d) < 2.0:            # a point either way is not news
                continue
            out.setdefault(pid, []).append((
                "Form", len(pts),
                f"{'up' if d > 0 else 'down'} <b>{abs(d):.1f} ppg</b> over "
                f"{pr.poss} last five "
                f"({last5:.1f} vs {season:.1f} on the season)"))
    except Exception:
        pass
    return out


def render_player_depth(lines, pid):
    """The depth lines for one player, under their personnel tile."""
    got = (lines or {}).get(pid)
    if got:
        st.markdown(CARDS.verdict_card(got), unsafe_allow_html=True)


# ── section chooser, shared with the tab ─────────────────────────────────────
def section_picker(labels, key="scout_section"):
    """`_UI.seg`, not `st.tabs`: st.tabs executes EVERY tab body on every rerun,
    which is what made the Scout tab render all ~35 of its sections eagerly on
    every interaction. One open section instead."""
    return _UI.seg("Section", labels, default=labels[0], key=key,
                   label_visibility="collapsed") or labels[0]


# ══════════════════════════════════════════════════════════════════════════════
#  CHARTS → SCOUT, TIER A  (SCOUT_TAB_ROADMAP Part 10)
# ══════════════════════════════════════════════════════════════════════════════
# Four blocks the Charts tab already draws about YOUR team, aimed at the
# opponent. Same rule as everything above: nothing here computes a new number.
# Each one is an existing engine result that already rides on `_opp_scout_ctx` —
# the zone tables, the xFG baseline, the team box, the guarded split — plus the
# sentence for the other direction.
#
# Screen-first by founder rule: all four default to SCREEN ON / PAPER OFF, which
# is the whole point of splitting `scout_hidden_screen` from
# `scout_hidden_print`. Each still HAS a paper form, because a print toggle that
# renders nothing is its own bug.

def _zone_rows(z2, z3):
    """[(label, fga2, fg2, fga3, fg3)] over the five zones — the numbers behind
    the two zone charts, in the order the court reads."""
    import helpers.team_analytics as TA
    out = []
    for z in TA.ZONES:
        a, b = z2.get(z) or {}, z3.get(z) or {}
        out.append((TA.ZONE_LABELS[z].split("/")[0].strip(),
                    a.get("FGA", 0), a.get("FG%"), b.get("FGA", 0), b.get("FG%")))
    return out


def _force_verdict(rows):
    """One sentence: where their defense sends the ball, and whether going there
    actually hurts.

    Written off SHARE of attempts allowed, not raw counts — a scout needs "they
    funnel you to the corner", and a count says that only if you already know
    their pace. The efficiency half is stated ONLY where the sample can carry
    it: five attempts from a zone is not an FG%, and saying it is would be the
    kind of line that costs a coach a game.
    """
    tot2 = sum(r[1] for r in rows)
    tot3 = sum(r[3] for r in rows)
    tot = tot2 + tot3
    if not tot:
        return []
    by_zone = sorted(((r[0], r[1] + r[3]) for r in rows), key=lambda kv: -kv[1])
    top, n = by_zone[0]
    low, ln = by_zone[-1]
    lines = [("Where they send it", tot,
              f"Most of what they allow comes from <b>{e(top)}</b> "
              f"(<b>{n / tot * 100:.0f}%</b> of shots allowed); they give up "
              f"least from <b>{e(low)}</b> (<b>{ln / tot * 100:.0f}%</b>). "
              "That is where they will force us to shoot.")]
    _share3 = tot3 / tot
    lines.append(("Shot value allowed", tot,
                  f"<b>{_share3 * 100:.0f}%</b> of the shots they allow are "
                  "threes — "
                  + ("they concede the arc to protect the rim"
                     if _share3 >= 0.35 else
                     "they run shooters off the line and live with twos"
                     if _share3 <= 0.22 else
                     "a balanced shot chart allowed") + "."))
    # the zone they are genuinely bad at defending — stated only on real volume
    _punish = [r for r in rows if (r[1] + r[3]) >= 15 and r[2] is not None]
    if _punish:
        worst = max(_punish, key=lambda r: r[2])
        lines.append(("Their softest zone", worst[1] + worst[3],
                      f"The highest two-point FG% they allow from any zone with "
                      f"real volume is <b>{worst[2] * 100:.0f}%</b>, from "
                      f"<b>{e(worst[0])}</b>. Softest is relative to their own "
                      "chart — read it against the other zones above, not "
                      "against a league average."))
    return lines


def render_force_profile(ctx):
    """Defense → opponent shot profile, aimed at them: WHERE THEY FORCE SHOTS.

    The roadmap calls this the single best chart on the Charts tab for a scout,
    and the reason is worth stating: read about yourself it is "what our defense
    allows"; read about them it is *where they will force US to shoot*, which is
    the offensive game plan in one image.

    `zones_by_type["def"]` and `zone_pair_bars` are both already on the ctx, so
    this is a call and not a port.
    """
    zdt = (getattr(ctx, "bundle", {}) or {}).get("zones_by_type", {}).get("def")
    if not zdt:
        st.caption("Not enough located shots against them yet — this fills in "
                   "as their games are tracked.")
        return
    lines = _force_verdict(_zone_rows(zdt.get("2") or {}, zdt.get("3") or {}))
    if lines:
        st.markdown(CARDS.verdict_card(lines), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Attempts they allow, by zone**")
        st.plotly_chart(ctx.zone_pair_bars(
            zdt["2"], zdt["3"], "2-pt", "3-pt",
            lambda a: a["FGA"], "Attempts allowed",
            text_fn=lambda a: a["FGA"] or ""),
            width="stretch", key="scout_force_fga")
    with c2:
        st.markdown("**FG% they allow, by zone**")
        st.plotly_chart(ctx.zone_pair_bars(
            zdt["2"], zdt["3"], "2P% allowed", "3P% allowed",
            lambda a: (a["FG%"] or 0) * 100, "FG% allowed",
            text_fn=lambda a: f"{a['FG%']*100:.0f}%" if a["FGA"] else "—"),
            width="stretch", key="scout_force_fg")
    st.caption("Their defensive shot chart, which is our offensive one. Tall "
               "bars are where they are content to let the ball go; the FG% "
               "chart beside it says whether being sent there actually hurts.")


def force_profile_rows(ctx):
    """The same five zones as a table for the hand-out, or []."""
    zdt = (getattr(ctx, "bundle", {}) or {}).get("zones_by_type", {}).get("def")
    if not zdt:
        return []
    return _zone_rows(zdt.get("2") or {}, zdt.get("3") or {})


def force_profile_print(ctx):
    """`[(badge, n, html)]` — the verdict half only. The zone table is large and
    the sentences are what change a game plan, so paper gets the sentences."""
    return _force_verdict(force_profile_rows(ctx))


def _scoped_ids(ctx):
    """The subject team's entitlement-filtered tracked ids as a hashable tuple,
    or None when the ctx does not carry one.

    `as_scope` rather than `tuple(...) or None`: an EMPTY pool is this viewer's
    answer, not a missing argument, and collapsing it to None is the widening
    class the September sweep closed."""
    import helpers.stats as S
    t = getattr(ctx, "tracked_ids", None)
    return S.as_scope(t)


# ── Winning Formula, inverted: what has to be true for THEM to win ────────────
@st.cache_data(ttl=600, show_spinner=False)
def _formula(gender, season, team_id, gids=None, fp=None):
    """(team fit, league fit, suppressors) for one team.

    Two pools on purpose, unlike `insights_deck._formula`, which is a SELF-scout
    and has only one:

      · the TEAM fit reads `gids` — the opponent's entitlement-filtered tracked
        ids off the ctx. Fitting it over the season would derive a read about
        this opponent from games the viewer is not entitled to see, which is the
        read filter leaking through a model instead of through a table. An empty
        pool therefore yields NO team fit rather than a season-wide one.
      · the LEAGUE fit stays league-wide. It is a property of the competition,
        not of any team — the same number Charts and Insights already print for
        everybody — so it discloses nothing about whose games are pooled.

    ONE `game_rows` walk still feeds the league half, because `league_formula`
    takes prebuilt `rows` for exactly that reason.
    """
    import helpers.winning_formula as WF
    rows = WF.game_rows(gender=gender, season=season)
    lg = WF.league_formula(rows=rows)
    if gids is None:
        tm = WF.team_formula(team_id, rows=rows)
    elif not gids:
        tm = None
    else:
        tm = WF.team_formula(team_id, gender=gender, season=season,
                             game_ids=list(gids))
    return tm, lg, WF.suppressors(tm or {})


#: `**x**` -> `<b>x</b>` — one copy, beside the `verdict_card` that
#: needs it (helpers/cards.py). Do not re-add a private one.
_md_bold = CARDS.md_bold


def formula_lines(ctx):
    """`[(badge, n, html)]` for the winning formula at the RIGHT SCOPE.

    Built from `WF.verdict(fit, scope=...)` rather than borrowed from
    `WF.verdict_lines`, which hard-codes "Your games" and "a quirk of your
    roster" because its only caller until now was the self-scout. On an opponent
    sheet that badge is not a wording nit — it labels THEIR fit as ours, on the
    one surface whose whole job is telling the two apart.
    """
    import helpers.winning_formula as WF
    try:
        tm, lg, _supp = _formula(ctx.gender, getattr(ctx, "season", "Current"),
                                 ctx.team_id, _scoped_ids(ctx))
    except Exception:
        return []
    _self = bool(getattr(ctx, "is_self", False))
    _scope = "our games" if _self else "their games"
    out = []
    tv = WF.verdict(tm, scope=_scope) if tm else None
    if tv and tv.get("kind") == "verdict":
        out.append(("Our games" if _self else "Their games",
                    tm.get("n_games", 0), _md_bold(tv["text"])))
    lv = WF.verdict(lg, scope="this league") if lg else None
    if lv and lv.get("kind") == "verdict":
        _same = (tv and tv.get("kind") == "verdict"
                 and tv["top"]["key"] == lv["top"]["key"])
        out.append(("The league", (lg or {}).get("n_games", 0),
                    "Same lever league-wide — this is how the whole competition "
                    "plays, not a quirk of one roster."
                    if _same else _md_bold(lv["text"])))
    return out


def render_winning_formula(ctx):
    """"What has to be true for them to win" — and therefore what to take away.

    The engine already writes the forward sentence, so the inversion is one line
    of prose on top of it rather than a second engine. `suppressors` ships
    verbatim: it is already written as coach-speak and is literally the scout
    answer to "why do these two columns disagree".
    """
    try:
        import helpers.winning_formula as WF
        tm, lg, supp = _formula(ctx.gender, getattr(ctx, "season", "Current"),
                                ctx.team_id, _scoped_ids(ctx))
    except Exception as exc:
        st.caption(f"Winning formula unavailable — {type(exc).__name__}: {exc}")
        return
    lines = formula_lines(ctx)
    if not lines:
        st.caption("Not enough of their games are tracked to fit a formula — "
                   "the fit needs a real sample before it means anything.")
        return
    st.markdown(CARDS.verdict_card(lines), unsafe_allow_html=True)
    _self = bool(getattr(ctx, "is_self", False))
    _v = WF.verdict(tm, scope="our games" if _self else "their games")         if tm else None
    _top = _v.get("top") if _v and _v.get("kind") == "verdict" else None
    if _top:
        st.markdown(
            ("**Our lever:** " if _self else "**Take away:** ")
            + f"{e(_top['noun'])}. One standard deviation of it is worth "
              f"**{abs(_top['beta']):.1f} points** of margin in "
            + ("our games" if _self else "their games")
            + " — more than any other factor. Everything else on this sheet is "
              "second.")
    # Only alongside a fit that actually produced a verdict. The suppressor note
    # explains a clash between a fitted column and a raw one, and BOTH columns
    # live on the Charts tab — printing the footnote here without the verdict it
    # annotates is a warning about a table this surface does not show.
    if supp and _top:
        st.caption(
            "⚠ " + ", ".join(f"**{f['noun']}**" for f in supp)
            + " fits POSITIVE but correlates NEGATIVE with margin in the raw "
              "column — game state, not a real inversion (losing teams get "
              "fouled late). The fit is what removes it.")


def winning_formula_print(ctx):
    """`[(badge, n, html)]` for the sheet — the same lines the tab renders."""
    return formula_lines(ctx)


# ── Shot Lab: do they get good looks, or do they make tough ones? ─────────────
def _smoe(zmap, zxmap):
    """(over-expected pp, made, expected, attempts) for one shot value."""
    import helpers.team_analytics as TA
    exp = sum((zmap.get(z) or {}).get("FGA", 0)
              * ((zxmap.get(z) or {}).get("xFG%") or 0) for z in TA.ZONES)
    act = sum((zmap.get(z) or {}).get("FGM", 0) for z in TA.ZONES)
    fga = sum((zmap.get(z) or {}).get("FGA", 0) for z in TA.ZONES)
    return ((act - exp) / fga * 100 if fga else 0), act, exp, fga


def shot_lab(ctx):
    """The Shot Lab numbers, data-only so the tab and the sheet cannot disagree.

    {'two','three','look','pps','sceff','contest'} or None. Every input is
    already on the ctx bundle — this adds no metric."""
    b = getattr(ctx, "bundle", {}) or {}
    zbt = (b.get("zones_by_type") or {}).get("off")
    zxbt = b.get("zone_xfg_by_type")
    if not (zbt and zxbt):
        return None
    import helpers.stats as S
    import helpers.team_analytics as TA
    zo = (b.get("zones") or {}).get("off") or {}
    zx = b.get("zone_xfg") or {}
    _fga = sum((zo.get(z) or {}).get("FGA", 0) for z in TA.ZONES)
    _exp = sum((zo.get(z) or {}).get("FGA", 0)
               * ((zx.get(z) or {}).get("xFG%") or 0) for z in TA.ZONES)
    tb = getattr(ctx, "tb", None) or b.get("team_box") or {}
    return {
        "two": _smoe(zbt.get("2") or {}, zxbt.get("2") or {}),
        "three": _smoe(zbt.get("3") or {}, zxbt.get("3") or {}),
        "look": (_exp / _fga) if _fga else None,
        "pps": S.pps(tb) if tb else None,
        "sceff": S.shot_efficiency(tb) if tb else None,
        "contest": (b.get("guarded") or {}).get("guard_share"),
    }


def _shot_lab_read(sl):
    """The contest-or-concede line, or None.

    Deliberately states the two numbers and the rule for reading them rather
    than announcing which side of a cut-off this team falls on. A first draft
    graded look quality against `>= 0.45 xFG` and shot-making against
    `>= +2.0pp`; both constants were invented here, neither is in
    `reliability.MEASURED`, and the house rule is explicit — no verdict, badge
    or threshold on an unmeasured quantity. Render the number, skip the
    sentence. Over-expected keeps its SIGN because the zero is the engine's own
    expectation, not a constant anybody chose.
    """
    _2, _3 = sl["two"], sl["three"]
    n = _2[3] + _3[3]
    if sl["look"] is None or not n:
        return None
    make = ((_2[1] + _3[1]) - (_2[2] + _3[2])) / n * 100
    return ("Look quality vs making", int(n),
            f"Average look <b>{sl['look'] * 100:.0f}% xFG</b> on {n:.0f} shots; "
            f"they finish <b>{make:+.1f}pp</b> against that expectation. "
            "Above the line is shot-making you have to contest; below it, the "
            "looks are better than the results and taking the looks away is "
            "the lever.")


def render_shot_lab(ctx):
    """Offense → Shot Lab, aimed at them: shot-MAKING vs shot QUALITY.

    This is the contest-or-concede decision and Scout could not answer it at
    all. A team getting easy looks and converting them at expectation is beaten
    by taking the looks away; a team generating ordinary looks and making them
    anyway has to be contested, and no amount of scheme fixes that.
    """
    sl = shot_lab(ctx)
    if not sl:
        st.caption("Needs located shots and a league expectation model for "
                   "their games — fills in as they are tracked.")
        return
    lines = []
    _read = _shot_lab_read(sl)
    if _read:
        lines.append(_read)
    for _lbl, _v in (("2-pointers", sl["two"]), ("3-pointers", sl["three"])):
        if _v[3] >= 15:
            lines.append((_lbl, int(_v[3]),
                          f"<b>{_v[0]:+.1f}%</b> over expected ({_v[1]:.0f} "
                          f"made vs {_v[2]:.0f} expected on {_v[3]:.0f} "
                          "shots)"))
    if lines:
        st.markdown(CARDS.verdict_card(lines), unsafe_allow_html=True)
    m = st.columns(4)
    m[0].metric("Their look quality (xFG%)",
                "—" if sl["look"] is None else f"{sl['look'] * 100:.0f}%",
                help="Expected FG% of the shots they generate. Higher = easier "
                     "looks, which is a scheme answer rather than a contest "
                     "one.")
    m[1].metric("Points / shot",
                "—" if sl["pps"] is None else f"{sl['pps']:.2f}",
                help="Field-goal points per FGA (free throws excluded).")
    m[2].metric("Scoring efficiency (ScEff)",
                "—" if sl["sceff"] is None else f"{sl['sceff']:.3f}")
    m[3].metric("Contested rate",
                "—" if sl["contest"] is None
                else f"{sl['contest'] * 100:.0f}%",
                help="Share of their shots logged with a contest. Low = they "
                     "are getting clean looks off the scheme.")
    st.caption("Look quality measures the difficulty of what they create; "
               "over-expected measures whether they convert it. The two "
               "together are the contest-or-concede call.")


def shot_lab_print(ctx):
    """`[(badge, n, html)]` — the same sentences, for paper."""
    sl = shot_lab(ctx)
    if not sl:
        return []
    out = []
    _read = _shot_lab_read(sl)
    if _read:
        out.append(_read)
    for _lbl, _v in (("2-pointers", sl["two"]), ("3-pointers", sl["three"])):
        if _v[3] >= 15:
            out.append((_lbl, int(_v[3]),
                        f"<b>{_v[0]:+.1f}%</b> over expected on "
                        f"{_v[3]:.0f} shots"))
    return out


# ── Trends → vs top-half / bottom-half: good-team beater or stat-padder ───────
def strength_lines(ctx):
    """`[(badge, n, html)]` for the top-half / bottom-half read, or [].

    Runs `insights_team.strength_splits` through `ctx.strength_split`, which the
    page binds with the opponent's gender, read-filtered ids and season — the
    engine is never called from here with a pool this module chose.
    """
    fn = getattr(ctx, "strength_split", None)
    if fn is None:
        return []
    try:
        ss = fn(ctx.team_id)
    except Exception:
        return []
    if not (ss and ss.get("available")):
        return []
    tp, bt = ss["top"], ss["bottom"]
    d = (tp.get("PPP") or 0) - (bt.get("PPP") or 0)
    n = ss["top_games"] + ss["bottom_games"]
    # The split ITSELF is a number and always prints. The directional sentence
    # is a verdict, and a verdict off two games on one side is the superlative
    # THE BOOK's B1 bans — "no superlative on a sample that cannot support it".
    # Three a side is the floor a difference of means needs before the word
    # "beater" is worth writing on a coach's sheet.
    _split = ("The split", n,
              f"<b>{tp.get('PPP') or 0:.2f} PPP</b> vs the top half "
              f"({ss['top_games']}g) · <b>{bt.get('PPP') or 0:.2f}</b> vs the "
              f"bottom half ({ss['bottom_games']}g)")
    _thin = min(ss["top_games"], ss["bottom_games"])
    if _thin < 3:
        return [_split,
                ("Not yet a read", n,
                 f"Only {_thin} tracked game{'' if _thin == 1 else 's'} on the "
                 "thinner side — the numbers are above, but which way they "
                 "lean is not something this sample can say.")]
    read = (f"their offense <b>drops {abs(d):.2f} PPP</b> against top-half "
            "teams — a stat-padder, and the tape against weak opponents is not "
            "what you will see" if d <= -0.12 else
            f"their offense <b>rises {d:+.2f} PPP</b> against top-half teams — "
            "a good-team beater; they bring their best against the better "
            "opponents" if d >= 0.12 else
            "their offense holds up about the same against strong and weak "
            "opponents — an opponent-proof profile, so the book travels")
    return [("Who they beat", n, f"By power rank, {read}."), _split]


def render_strength_split(ctx):
    """One row and one line of prose, which is all the roadmap asked for."""
    lines = strength_lines(ctx)
    if not lines:
        st.caption("Needs tracked games on both sides of the league's power "
                   "median before a split means anything.")
        return
    st.markdown(CARDS.verdict_card(lines), unsafe_allow_html=True)
    st.caption("Split at the league's own power-rank median. A team whose "
               "numbers collapse against the top half has a book that does not "
               "travel — and the film you watched may be the wrong half of "
               "their season.")


#: Tier A, for paper. Every one of these defaults to PAPER OFF; this is what a
#: coach gets when they promote one in the ⚙ panel.
TIER_A_PRINT = (
    ("force_profile", "Where they force shots", force_profile_print),
    ("winning_formula", "What has to be true for them to win",
     winning_formula_print),
    ("shot_lab", "Shot making vs shot quality", shot_lab_print),
    ("strength_split", "Top half vs bottom half", strength_lines),
)
#: The Tier A keys, in the order they are read. Shared with scout_tab so the
#: section list and the print list cannot drift.
TIER_A_KEYS = tuple(k for k, _h, _f in TIER_A_PRINT)


def print_tier_a(ctx, hidden=frozenset()):
    """`[(header, [(badge, n, html)])]` for the sheet — the promoted Tier A
    blocks only, so the hand-out cannot say something the screen does not."""
    out = []
    for key, header, fn in TIER_A_PRINT:
        if key in hidden:
            continue
        try:
            got = fn(ctx)
        except Exception:
            got = []
        if got:
            out.append((header, got))
    return out
