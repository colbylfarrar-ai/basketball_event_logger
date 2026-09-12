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
     "name at the top of this list early: the decision keeps arriving for her, "
     "and their coach has to make it."),
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
    shown = [(k, h, c) for k, h, c in OPP_SECTIONS if got.get(k)]
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
                f"picks up her second at <b>{FT.clock_label(d['median'])}</b> "
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
                f"{'up' if d > 0 else 'down'} <b>{abs(d):.1f} ppg</b> over her "
                f"last five ({last5:.1f} vs {season:.1f} on the season)"))
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
