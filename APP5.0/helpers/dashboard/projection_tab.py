"""
projection_tab.py — the Team Dashboard "Projection" super-tab (B + C surface).

Turns helpers.lineup_projection into a coach-facing read: the minutes the
signature-stat optimizer recommends vs the team's observed rotation (the "extra
wins" diff), the projected line against the team's OWN win/loss signature goals
(hit/miss + margin), the current-roster team projection, and the star-stagger
note. A pure renderer (the situational_tab.py / defense_tab.py pattern); all data
arrives via ctx values + the engines, so it's AppTest-able in isolation.

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


@st.fragment
def render(ctx):
    """Render the Projection super-tab. ``ctx`` carries team_id, gender, is_paid,
    has_tracked, game_ids (visible tracked ids, or None), and players (roster)."""
    tid, g = ctx.team_id, ctx.gender
    st.markdown("<div class='pl-hdr'>Projection — the minutes that hit your win formula</div>",
                unsafe_allow_html=True)
    st.caption(
        "Every player's skill rates are stabilized over their tracked games, then "
        "the optimizer searches minute splits to best hit **this team's own "
        "signature stats** — the ~4 stats your wins and losses actually turn on. "
        "Directional: it reads the levers, it doesn't promise a scoreline.")

    if not getattr(ctx, "is_paid", False):
        empty_state("Projection is a paid feature",
                    "Upgrade to project your roster's rates and optimize the rotation "
                    "against your win formula.", icon="🔒")
        return
    if not getattr(ctx, "has_tracked", False):
        empty_state("No tracked games yet",
                    "Track games to build the rotation history a projection needs.",
                    icon="🎬")
        return

    gids = list(ctx.game_ids) if getattr(ctx, "game_ids", None) is not None else None
    season = getattr(ctx, "season", "Current")
    ctxp = LP.build_context(tid, gender=g, game_ids=gids, season=season)
    if ctxp.get("gated"):
        empty_state("Not enough tracked games to project a rotation",
                    f"{ctxp['gated']}. The depth-chart projection needs a real "
                    f"rotation sample — keep tracking.", icon="📉")
        return

    cset1, cset2 = st.columns([1, 1])
    rot = cset1.slider("Rotation depth (players)", 6, 10, min(LP.MAX_ROTATION, 10),
                       key="proj_rot_depth",
                       help="How many players share the 32-minute game. Deeper = more "
                            "even minutes; shorter = more on your best.")
    # objective toggle — only meaningful when the team has mined signature stats
    # (without them the objective is always Net regardless).
    force = None
    if ctxp.get("sig_available"):
        pick = cset2.radio(
            "Optimize for", ["Signature stats", "Best net"], horizontal=True,
            key="proj_objective",
            help="Signature stats = hit the ~4 stats your wins turn on. "
                 "Best net = maximize projected point differential /100.")
        force = "net" if pick == "Best net" else None

    opt = LP.optimize_minutes(tid, ctx=ctxp, max_rotation=rot, objective=force)
    proj = opt["projection"]
    names = {p: ctxp["players"][p]["name"] for p in opt["minutes"]}

    # ── headline: current-roster projection ──────────────────────────────────
    tc = LP.project_team_current(tid, ctx=ctxp)
    c1, c2, c3 = st.columns(3)
    c1.metric("Projected Net /100", f"{tc['net']:+.1f}", help="vs the average tracked team (clamped, directional)")
    c2.metric("Win prob vs avg team", f"{tc['win_prob_vs_avg'] * 100:.0f}%")
    if opt["objective_kind"] == "signature":
        _obj_lbl, _obj_help = "Signature stats", "Optimizing the team's own win/loss signature stats."
    elif force == "net":
        _obj_lbl, _obj_help = "Best net (chosen)", "Maximizing projected point differential /100."
    else:
        _obj_lbl, _obj_help = "Net (fallback)", "Not enough wins AND losses to mine signatures — optimizing Net."
    c3.metric("Objective", _obj_lbl, help=_obj_help)
    if proj["flags"]["tier"] != "solid":
        st.caption(f"⚠️ {int(proj['flags']['thin_minute_share'] * 100)}% of these minutes "
                   "go to thin-sample players — read as directional.")

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

    # ── recommended minutes vs observed (the prescription) ───────────────────
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
        def _hits(line):
            n = 0
            for goal in opt.get("signature_goals", []):
                v = line.get(goal["key"])
                if v is None:
                    continue
                if (v >= goal["target"]) if goal["win_high"] else (v <= goal["target"]):
                    n += 1
            return n
        n_goals = len(opt.get("signature_goals", []))
        yours, rec = _hits(wp["line"]), _hits(proj["line"])
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

    # ── star stagger note ────────────────────────────────────────────────────
    # use the ctx-resolved, season-scoped game ids (gids may be None for an open
    # archive / own team — star_coverage would otherwise read the 'Current' season)
    try:
        import helpers.rotation_plan as RP
        sc = RP.star_coverage(tid, game_ids=ctxp.get("game_ids"))
        if sc.get("note"):
            st.info("🔄 " + sc["note"])
    except Exception:
        pass
