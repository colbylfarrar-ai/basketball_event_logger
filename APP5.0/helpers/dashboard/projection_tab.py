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
    ctxp = LP.build_context(tid, gender=g, game_ids=gids)
    if ctxp.get("gated"):
        empty_state("Not enough tracked games to project a rotation",
                    f"{ctxp['gated']}. The depth-chart projection needs a real "
                    f"rotation sample — keep tracking.", icon="📉")
        return

    opt = LP.optimize_minutes(tid, ctx=ctxp)
    proj = opt["projection"]
    names = {p: ctxp["players"][p]["name"] for p in opt["minutes"]}

    # ── headline: current-roster projection ──────────────────────────────────
    tc = LP.project_team_current(tid, ctx=ctxp)
    c1, c2, c3 = st.columns(3)
    c1.metric("Projected Net /100", f"{tc['net']:+.1f}", help="vs the average tracked team (clamped, directional)")
    c2.metric("Win prob vs avg team", f"{tc['win_prob_vs_avg'] * 100:.0f}%")
    c3.metric("Objective", "Signature stats" if opt["objective_kind"] == "signature"
              else "Net (fallback)",
              help=("Optimizing the team's own win/loss signature stats."
                    if opt["objective_kind"] == "signature" else
                    "Not enough wins AND losses to mine signatures — optimizing Net."))
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

    # ── star stagger note ────────────────────────────────────────────────────
    try:
        import helpers.rotation_plan as RP
        sc = RP.star_coverage(tid, game_ids=gids)
        if sc.get("note"):
            st.info("🔄 " + sc["note"])
    except Exception:
        pass
