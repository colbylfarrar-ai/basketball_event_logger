"""
projection_tab.py — the Projection surface, in two depths (B + C).

`render(ctx)`   — the LIGHT read on the Team Dashboard: headline projection,
                  the recommended rotation, the best five with its trade-off
                  line, and a hand-off to the War Room for the deep dive.
`render_deep(ctx)` — the FULL rotation lab on the War Room → Lineups view:
                  rotation-depth slider, objective picker, signature-goal
                  table, and the what-if minutes editor.

Both depths run helpers.lineup_projection — the ONE lineup engine — so the
number a coach sees on the dashboard is the number the War Room shows. Pure
renderers (the situational_tab.py / defense_tab.py pattern); all data arrives
via ctx values + the engines, so each is AppTest-able in isolation.

Everything is flagged directional and TEAM-GATED — a team without enough tracked
games has no rotation to project, and the objective states whether it optimized
the team's mined signatures or fell back to Net.
"""
from __future__ import annotations

import streamlit as st

from helpers.cards import dense_table
from helpers.ui import empty_state
import helpers.lineup_projection as LP


def _pct(v):
    return f"{v * 100:.1f}%" if v is not None else "—"


def _fmt_edge(e):
    """One give-or-take as coach text: percentage points for rate stats, raw
    for PPP-scale stats."""
    d = e["diff"]
    if e["key"] in ("PPP", "oPPP"):
        return f"{d:+.2f} {e['label']}"
    return f"{d * 100:+.1f} {e['label']}"


def _build(ctx):
    """Shared gates + engine context for both depths. Renders the empty state
    and returns None when gated; returns the LP ctx dict when it can run."""
    if not getattr(ctx, "is_paid", False):
        empty_state("Projection is a paid feature",
                    "Upgrade to project your roster's rates and optimize the rotation "
                    "against your win formula.", icon="🔒")
        return None
    # NOTE: no early has_tracked gate — a rolled-over season with 0 tracked
    # games can still project from the newest archived season (build_context's
    # career fallback). Only a team with no usable sample ANY season is gated.
    gids = list(ctx.game_ids) if getattr(ctx, "game_ids", None) is not None else None
    season = getattr(ctx, "season", "Current")
    ctxp = LP.build_context(ctx.team_id, gender=ctx.gender, game_ids=gids,
                            season=season)
    if ctxp.get("gated"):
        if not getattr(ctx, "has_tracked", False):
            empty_state("No tracked games yet",
                        "Track games to build the rotation history a projection "
                        "needs.", icon="🎬")
        else:
            empty_state("Not enough tracked games to project a rotation",
                        f"{ctxp['gated']}. The depth-chart projection needs a real "
                        f"rotation sample — keep tracking.", icon="📉")
        return None
    if ctxp.get("career_note"):
        st.info("📅 " + ctxp["career_note"])
    return ctxp


def _headline(tid, ctxp, opt, force=None):
    """The three headline metrics + the thin-sample caption (both depths)."""
    proj = opt["projection"]
    tc = LP.project_team_current(tid, ctx=ctxp)
    c1, c2, c3 = st.columns(3)
    c1.metric("Projected Net /100", f"{tc['net']:+.1f}",
              help="vs the average tracked team (clamped, directional)")
    c2.metric("Win prob vs avg team", f"{tc['win_prob_vs_avg'] * 100:.0f}%")
    if opt["objective_kind"] == "signature":
        _obj_lbl, _obj_help = "Signature stats", ("Optimizing the team's own win/loss "
                                                  "signature stats — who fits how you play.")
    elif opt["objective_kind"] == "value":
        _obj_lbl, _obj_help = "Best 5", ("The five who give the best chance to win in "
                                         "general — minutes to your highest-impact players.")
    elif force == "net":
        _obj_lbl, _obj_help = "Best net (chosen)", "Maximizing projected point differential /100 (clamped, blunt)."
    else:
        _obj_lbl, _obj_help = "Net (fallback)", "Not enough wins AND losses to mine signatures — optimizing Net."
    c3.metric("Objective", _obj_lbl, help=_obj_help)
    if proj["flags"]["tier"] != "solid":
        st.caption(f"⚠️ {int(proj['flags']['thin_minute_share'] * 100)}% of these minutes "
                   "go to thin-sample players — read as directional.")


def _rotation_table(opt, ctxp, names):
    """Recommended-vs-observed minutes — the prescription (both depths)."""
    st.markdown("<div class='pl-hdr'>Recommended rotation — vs your observed minutes</div>",
                unsafe_allow_html=True)
    st.caption("Minutes normalized to a 32-minute game (160 player-minutes). "
               "The diff is the shift the optimizer wants toward your win formula.")
    mrows = []
    for p in sorted(opt["minutes"], key=lambda x: -opt["minutes"][x]):
        d = opt["diff"][p]
        mrows.append({
            "Player": names[p],
            "Recommend": f"{opt['minutes'][p]:.0f}",
            "Observed": f"{opt['observed'][p]:.0f}",
            "Shift": f"{d:+.0f}" + ("  ▲" if d > 1 else ("  ▼" if d < -1 else "")),
            "Foul-prone": "⚠️" if ctxp["players"][p]["foul_prone"] else "",
        })
    st.markdown(dense_table(mrows), unsafe_allow_html=True)


def _star_note(tid, ctxp):
    # use the ctx-resolved, season-scoped game ids (gids may be None for an open
    # archive / own team — star_coverage would otherwise read the 'Current' season)
    if ctxp.get("career_note"):
        return   # last season's stagger read may name departed players — skip
    try:
        import helpers.rotation_plan as RP
        sc = RP.star_coverage(tid, game_ids=ctxp.get("game_ids"))
        if sc.get("note"):
            st.info("🔄 " + sc["note"])
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  LIGHT — Team Dashboard: the read, then hand off to the War Room
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def render(ctx):
    """Render the light Projection tab. ``ctx`` carries team_id, gender, is_paid,
    has_tracked, game_ids (visible tracked ids, or None), and season."""
    tid = ctx.team_id
    st.markdown("<div class='pl-hdr'>Projection — the minutes that hit your win formula</div>",
                unsafe_allow_html=True)
    st.caption(
        "Every player's skill rates are stabilized over their tracked games, then "
        "the optimizer searches minute splits for the objective below. Directional: "
        "it reads the levers, it doesn't promise a scoreline.")

    ctxp = _build(ctx)
    if ctxp is None:
        return

    # Two lenses (founder ask): **Best 5** = who gives the best chance to win in
    # GENERAL (a coach walking into a new team), **Signature stats** = who fits
    # HOW THIS TEAM plays (a staying coach). Signature needs a mined win/loss
    # split; without it, only Best 5 shows.
    from helpers.ui import seg as _seg
    _force = "value"
    if ctxp.get("sig_available"):
        _pick = _seg("Show me", ["Signature stats", "Best 5"],
                     default="Signature stats", key=f"proj_lens_{tid}",
                     help="Signature stats = the five that fits how you play "
                          "(your win/loss signature). Best 5 = the five with the "
                          "best chance to win in general (highest-impact players).")
        _force = {"Signature stats": None, "Best 5": "value"}.get(_pick)
    opt = LP.optimize_minutes(tid, ctx=ctxp, objective=_force)
    names = {p: ctxp["players"][p]["name"] for p in opt["minutes"]}

    _headline(tid, ctxp, opt, force=_force)
    _rotation_table(opt, ctxp, names)

    # ── the best five + its give-and-take vs the season line ─────────────────
    top5 = sorted(opt["minutes"], key=lambda p: -opt["minutes"][p])[:5]
    if len(top5) == 5:
        lp = LP.project_lineup(tid, top5, ctxp, game_ids=ctxp.get("game_ids"))
        hit, tot = LP.goals_hit(lp["line"], ctxp.get("goals", []))
        edges = LP.compare_lines(lp["line"], ctxp["observed_line"])
        gains = [e for e in edges if e["good"]][:2]
        costs = [e for e in edges if not e["good"]][:2]
        bits = [f"projected Net {lp['net_blended']:+.1f}"]
        if tot:
            bits.append(f"hits {hit}/{tot} of your signature stats")
        trade = ""
        if gains or costs:
            trade = (" Vs your season line: "
                     + " · ".join(_fmt_edge(e) for e in gains)
                     + (" / " if gains and costs else "")
                     + " · ".join(_fmt_edge(e) for e in costs) + ".")
        st.markdown("**Best five** — " + " · ".join(names[p] for p in top5)
                    + f" — {' · '.join(bits)}.{trade}")
        if lp.get("obs_unit_poss"):
            st.caption(f"Blended with {lp['obs_unit_poss']:.0f} observed possessions "
                       "together — chemistry the sum-of-parts misses.")

    _star_note(tid, ctxp)

    # ── the hand-off: the deep controls live in the War Room ─────────────────
    try:
        st.page_link("pages/9_War_Room.py",
                     label="Go deeper — War Room → Lineups: what-if minutes, "
                           "objective & depth controls, and side-by-side lineup "
                           "comparison", icon="🎯")
    except Exception:
        st.caption("Go deeper on the **War Room → Lineups** view: what-if minutes, "
                   "objective & depth controls, and side-by-side lineup comparison.")


# ══════════════════════════════════════════════════════════════════════════════
#  DEEP — War Room → Lineups: the full rotation lab
# ══════════════════════════════════════════════════════════════════════════════

@st.fragment
def render_deep(ctx):
    """Render the full rotation lab (War Room). Same ctx contract as render()."""
    tid = ctx.team_id
    st.caption(
        "Every player's skill rates are stabilized over their tracked games, then "
        "the optimizer searches minute splits to best hit **this team's own "
        "signature stats** — the ~4 stats your wins and losses actually turn on. "
        "Directional: it reads the levers, it doesn't promise a scoreline.")

    ctxp = _build(ctx)
    if ctxp is None:
        return

    cset1, cset2 = st.columns([1, 1])
    rot = cset1.slider("Rotation depth (players)", 6, 10, min(LP.MAX_ROTATION, 10),
                       key="proj_rot_depth",
                       help="How many players share the 32-minute game. Deeper = more "
                            "even minutes; shorter = more on your best.")
    # objective toggle — only meaningful when the team has mined signature stats
    # (without them the objective is always Net regardless).
    _obj_opts = (["Signature stats", "Best 5"] if ctxp.get("sig_available")
                 else ["Best 5", "Best net"])
    pick = cset2.radio(
        "Optimize for", _obj_opts, horizontal=True, key="proj_objective",
        help="Signature stats = the five that fits how you play (hit the ~4 stats "
             "your wins turn on) — for a staying coach. Best 5 = the best chance "
             "to win in general (minutes to your highest-impact players) — for a "
             "coach walking into a new team. Best net = projected point diff /100 "
             "(a blunt lever — the net projection is clamped).")
    force = {"Best 5": "value", "Best net": "net",
             "Signature stats": None}.get(pick)

    opt = LP.optimize_minutes(tid, ctx=ctxp, max_rotation=rot, objective=force)
    proj = opt["projection"]
    names = {p: ctxp["players"][p]["name"] for p in opt["minutes"]}

    _headline(tid, ctxp, opt, force=force)

    # ── signature goals: does the recommended lineup hit them? ───────────────
    if opt["objective_kind"] == "signature" and opt["signature_goals"]:
        st.markdown("<div class='pl-hdr'>Your signature stats — projected vs goal</div>",
                    unsafe_allow_html=True)
        rows = []
        for goal in opt["signature_goals"]:
            k = goal["key"]
            v = proj["line"].get(k)
            if v is None:
                continue
            hit = (v >= goal["target"]) if goal["win_high"] else (v <= goal["target"])
            rows.append({
                "Signature stat": k,
                "Target": _pct(goal["target"]) if goal["fmt"] == "pct" else f"{goal['target']:.2f}",
                "Projected": _pct(v) if goal["fmt"] == "pct" else f"{v:.2f}",
                "Want": "higher" if goal["win_high"] else "lower",
                "": "✅ hit" if hit else "❌ miss",
            })
        if rows:
            st.markdown(dense_table(rows), unsafe_allow_html=True)

    _rotation_table(opt, ctxp, names)

    # ── what-if: coach sets the minutes, sees the projected difference ────────
    with st.expander("🎛️ Try your own minutes — see the difference"):
        st.caption("Set each player's minutes; the projection updates live. Deltas "
                   "are vs the optimizer's recommendation above.")
        order = sorted(opt["minutes"], key=lambda x: -opt["minutes"][x])
        custom = {}
        cols = st.columns(3)
        for i, p in enumerate(order):
            custom[p] = cols[i % 3].number_input(
                names[p], min_value=0, max_value=32, step=2,
                value=int(round(opt["minutes"][p])), key=f"proj_wi_{tid}_{p}")
        total = sum(custom.values())
        if total != int(LP.TEAM_MIN):
            st.caption(f"⚖️ {total} of {int(LP.TEAM_MIN)} player-minutes "
                       f"({'over' if total > LP.TEAM_MIN else 'under'} a full game) "
                       "— rates still read, but fill to 160 for a fair read.")
        wp = LP.project_minutes(tid, {p: float(m) for p, m in custom.items()}, ctxp)

        # goals hit: yours vs recommended
        n_goals = len(opt.get("signature_goals", []))
        yours, _ = LP.goals_hit(wp["line"], opt.get("signature_goals", []))
        rec, _ = LP.goals_hit(proj["line"], opt.get("signature_goals", []))
        m1, m2 = st.columns(2)
        if n_goals:
            m1.metric("Signature goals hit", f"{yours} / {n_goals}",
                      delta=(yours - rec) or None, help="vs the recommendation")
        m2.metric("Projected Net /100", f"{wp['net']:+.1f}",
                  delta=round(wp["net"] - proj["net"], 1) or None,
                  help="vs the recommendation")
        if opt["objective_kind"] == "signature" and opt.get("signature_goals"):
            wrows = []
            for goal in opt["signature_goals"]:
                k = goal["key"]
                v = wp["line"].get(k)
                if v is None:
                    continue
                hit = (v >= goal["target"]) if goal["win_high"] else (v <= goal["target"])
                wrows.append({
                    "Signature stat": k,
                    "Target": _pct(goal["target"]) if goal["fmt"] == "pct" else f"{goal['target']:.2f}",
                    "Yours": _pct(v) if goal["fmt"] == "pct" else f"{v:.2f}",
                    "": "✅ hit" if hit else "❌ miss",
                })
            if wrows:
                st.markdown(dense_table(wrows), unsafe_allow_html=True)

    _star_note(tid, ctxp)
