"""
dashboard/sched.py — the Team Dashboard "Schedule" tab.

Record vs every class, the full schedule with the model's retro projections
and film links, the upcoming-games projection table, and any tracked game's
box score on demand. Extracted from pages/6_Team_Dashboard.py (see
helpers/dashboard/__init__.py for the ctx convention).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.box_score import render_box_score
import helpers.predictor as PRED
import helpers.team_ratings as TR


@st.fragment
def render(ctx):
    st.caption("The full schedule with results, the record against every class, "
               "and any tracked game's complete box score on demand.")

    rvc = ctx.bundle["record_vs_class"]
    cls_order = sorted(rvc, key=lambda c: TR._CLASS_RANK.get(c, 99))
    mcols = st.columns(max(len(cls_order) + 1, 2))
    mcols[0].metric("Overall", f"{ctx.rec['wins']}-{ctx.rec['losses']}")
    for col, cls in zip(mcols[1:], cls_order):
        w, l = rvc[cls]
        col.metric(f"vs {cls}", f"{w}-{l}")

    if rvc:
        st.markdown("<div class='lab-hdr'>Record vs each class</div>",
                    unsafe_allow_html=True)
        rcfig = go.Figure()
        rcfig.add_trace(go.Bar(x=cls_order, y=[rvc[c][0] for c in cls_order],
                               name="Wins", marker_color=ctx.GOOD))
        rcfig.add_trace(go.Bar(x=cls_order, y=[rvc[c][1] for c in cls_order],
                               name="Losses", marker_color=ctx.BAD))
        rcfig.update_layout(barmode="stack")
        rcfig.update_yaxes(title="Games")
        rcfig.update_xaxes(title="Opponent class")
        ctx.style(rcfig, 300)
        st.plotly_chart(rcfig, width="stretch", key="sc_rvc")

    st.markdown("<div class='lab-hdr'>Schedule</div>", unsafe_allow_html=True)
    st.caption("Opponent ranking (everything / tracked when possible), opponent "
               "record & class, the model's projected score, and the result. "
               "Projected score uses opponent-adjusted ratings with home court "
               "applied to the actual venue.")
    any_film = any((g.get("video_url") or "").strip() for g in ctx.log)
    sched_rows = []
    for g in ctx.log:
        oid = g["opp_id"]
        o_sc = ctx.scored.get(oid, {})
        o_tr = ctx.tracked.get(oid)
        ovr = o_sc.get("Rank")
        trk_rk = o_tr.get("Rank") if o_tr else None
        pred = PRED.predict_game(ctx.team_id, oid, scored=ctx.scored,
                                 tracked=ctx.tracked,
                                 home=(ctx.team_id if g["site"] == "vs" else oid))
        row = {
            "Date": g["date"], "": g["site"], "Opponent": g["opp"],
            "Cls": g["opp_class"],
            "Opp Rk": f"#{ovr}" if ovr else "—",
            "Trk Rk": f"#{trk_rk}" if trk_rk else "—",
            "Opp Rec": (f"{o_sc.get('W', 0)}-{o_sc.get('L', 0)}"
                        if o_sc else "—"),
            "Proj": (f"{pred['pf_a']:.0f}-{pred['pf_b']:.0f}" if pred else "—"),
            "Result": ("W" if g["won"] else "L") + f" {g['pf']}-{g['pa']}",
            "Margin": f"{g['margin']:+d}",
            "Tracked": "✓" if g["tracked"] else "",
        }
        if any_film:
            row["Film"] = (g.get("video_url") or "").strip() or None
        sched_rows.append(row)
    sched_cfg = {}
    if any_film:
        sched_cfg["Film"] = st.column_config.LinkColumn(
            "Film", display_text="▶ Watch", width="small",
            help="Opens the game's film (Hudl / YouTube / NFHS) in a new tab.")
    st.dataframe(pd.DataFrame(sched_rows), hide_index=True, width="stretch",
                 height=min(680, 60 + 35 * len(sched_rows)),
                 column_config=sched_cfg)

    # ── upcoming games — the model's pre-game read, for weekly prep ──────────
    # Date floor: a past game whose score never got entered must not lead the
    # "Upcoming" list. (Dates are ISO-normalised in the DB.) Today's games
    # stay listed — live tracked games keep NULL scores until finish_game.
    _today = datetime.now().strftime("%Y-%m-%d")
    up_rows = query("""
        SELECT g.id, g.date, g.location, g.team1_id, g.team2_id,
               t1.name AS t1, t2.name AS t2
        FROM games g JOIN teams t1 ON t1.id = g.team1_id
                     JOIN teams t2 ON t2.id = g.team2_id
        WHERE (g.team1_id = ? OR g.team2_id = ?)
          AND (g.home_score IS NULL OR g.away_score IS NULL)
          AND g.date >= ?
        ORDER BY g.date""", (ctx.team_id, ctx.team_id, _today))
    if up_rows:
        st.markdown("<div class='lab-hdr'>Upcoming — projections</div>",
                    unsafe_allow_html=True)
        up_disp = []
        for g in up_rows:
            at_home = g["team1_id"] == ctx.team_id
            oid = g["team2_id"] if at_home else g["team1_id"]
            opp = g["t2"] if at_home else g["t1"]
            up_pred = PRED.predict_game(ctx.team_id, oid, scored=ctx.scored,
                                        tracked=ctx.tracked,
                                        home=(ctx.team_id if at_home else oid))
            o_sc = ctx.scored.get(oid, {})
            up_disp.append({
                "Date": g["date"], "": "vs" if at_home else "@",
                "Opponent": opp,
                "Opp Rk": f"#{o_sc['Rank']}" if o_sc.get("Rank") else "—",
                "Opp Rec": (f"{o_sc.get('W', 0)}-{o_sc.get('L', 0)}"
                            if o_sc else "—"),
                "Proj": (f"{up_pred['pf_a']:.0f}-{up_pred['pf_b']:.0f}"
                         if up_pred else "—"),
                "Our win %": (f"{up_pred['win_prob_a'] * 100:.0f}%"
                              if up_pred else "—"),
                "Call": up_pred["confidence"] if up_pred else "—",
            })
        st.dataframe(pd.DataFrame(up_disp), hide_index=True, width="stretch",
                     height=min(420, 60 + 35 * len(up_disp)))
        st.caption("Opponent-adjusted projection with home court at the actual "
                   "venue. Open the **Scout** tab to build the game plan "
                   "against the next opponent.")

    st.markdown("<div class='lab-hdr'>Box score</div>",
                unsafe_allow_html=True)
    tracked_games = [g for g in ctx.log if g["tracked"]]
    if not tracked_games:
        st.info("No tracked games to open a box score for yet.")
    else:
        glabels = [f"{g['date']}  {g['site']} {g['opp']}  "
                   f"({'W' if g['won'] else 'L'} {g['pf']}-{g['pa']})"
                   for g in tracked_games]
        gi = st.selectbox("Pick a tracked game", range(len(tracked_games)),
                          format_func=lambda i: glabels[i], key="sc_box")
        render_box_score(tracked_games[gi]["game_id"])
    # (Team stats over tracked games moved to Charts → Trends to avoid duplication.)
