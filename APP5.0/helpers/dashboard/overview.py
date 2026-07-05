"""
dashboard/overview.py — the Team Dashboard "Overview" tab.

A coach's one-glance card: coach notes, record (incl. vs ranked teams and by
game type), power ratings, who carries them, the four factors & scoring mix
aligned to the league, and the game-by-game margin / rating / PPP trends.
Extracted from pages/6_Team_Dashboard.py (see helpers/dashboard/__init__.py
for the ctx convention).
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from database.db import query, execute
from helpers.ui import AWAY, CARD_BG, GRID, seg as _segc
import helpers.cards as CARDS
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.manual_box as MB
import helpers.team_analytics as TA


@st.fragment
def render(ctx):
    st.caption("Everything about this team at a glance — power ratings, record, "
               "who carries them, the four factors and how they score.")

    # ── coach notes (PER-COACH + private — was the global teams.notes) ────────
    import helpers.scoutboard as SB
    _curnotes = SB.get_note(ctx.team_id, "team")
    with st.expander("📝 Team notes" + (" — saved" if _curnotes else ""),
                     expanded=bool(_curnotes)):
        SB.render_notes(ctx.team_id, kind="team", key_prefix="tn", label="Notes",
                        placeholder="Scouting notes, reminders, season context… "
                                    "private to you, shown here next time.")

    _mprof = MB.manual_team_profile(ctx.team_id)
    if _mprof:
        # PPP/ORtg are possession-derived (POSS = FGA+TOV) → Paid per the carve-out,
        # even off a hand-entered box. Games-entered + eFG% (pure shooting) are box-
        # derivable and stay Free. Gate on can_see_team_tracked (Paid AND own-team
        # or league-wide) — NOT has_tracked, which is False for manual-only teams.
        _see_depth = ENT.can_see_team_tracked(AUTH.current_user(), ctx.team_id)
        st.markdown("<div class='pl-hdr'>Entered (untracked) games</div>",
                    unsafe_allow_html=True)
        if _see_depth:
            _mc = st.columns(4)
            _mc[0].metric("Games entered", _mprof["games"])
            _mc[1].metric("PPP", f"{_mprof['PPP']:.2f}")
            _mc[2].metric("ORtg", f"{_mprof['ORtg']:.0f}")
            _mc[3].metric("eFG%", f"{_mprof['off_ff']['eFG']:.0f}%")
            st.caption("From hand-entered box scores (not play-by-play tracked) · "
                       "possessions = FGA + TOV. Enter boxes on the Setup page.")
        else:
            _mc = st.columns(2)
            _mc[0].metric("Games entered", _mprof["games"])
            _mc[1].metric("eFG%", f"{_mprof['off_ff']['eFG']:.0f}%")
            st.caption("From hand-entered box scores. Possession rates (PPP, ORtg) "
                       "are a Paid feature.")

    # ── the dense team header card (banner · glance · identity/engine/verdict)
    #    — UI_DENSITY_PLAN phase C; shared with the Rankings deep dive (phase D).
    #    Absorbs the old metric rows (Power/rank/record, vs-ranked, tracked row,
    #    game-type caption) and the glance strip into one OOTP-style read.
    import helpers.dashboard.team_card as TC
    TC.render_header(ctx)

    if ctx.has_tracked:
        # ── efficiency rankings vs league (DEMOTED into an expander) ────────
        # Restates the header card's engine zone + the per-stat four-factor
        # percentile bars below — collapsed so the top of the card paints fast.
        if ctx.sc_track:
            with st.expander("Efficiency rankings — vs league"):
                pool_o = [r["ORtg"] for r in ctx.tracked.values()]
                pool_d = [r["DRtg"] for r in ctx.tracked.values()]
                pool_n = [r["NetRtg"] for r in ctx.tracked.values()]
                pool_p = [r["Pace"] for r in ctx.tracked.values()]
                metrics = [
                    ("Offense", ctx.sc_track["ORtg"], pool_o, True),
                    ("Defense", ctx.sc_track["DRtg"], pool_d, False),
                    ("Net rating", ctx.sc_track["NetRtg"], pool_n, True),
                    ("Pace", ctx.sc_track["Pace"], pool_p, True),
                ]
                bars = []
                for lbl, val, pool, hb in metrics:
                    pct = TA.percentile(val, pool, higher_better=hb) or 0
                    bars.append((lbl, pct, val))
                ef = go.Figure(go.Bar(
                    x=[b[1] for b in bars], y=[b[0] for b in bars], orientation="h",
                    marker_color=[ctx.GOOD if b[1] >= 50 else ctx.BAD for b in bars],
                    marker_line_width=0,
                    text=[f"{b[1]:.0f}th pct ({b[2]:.1f})" for b in bars],
                    textposition="auto"))
                ef.update_xaxes(title="League percentile", range=[0, 100])
                ctx.style(ef, 240)
                ef.update_layout(margin=dict(l=4, r=14, t=6, b=30))
                st.plotly_chart(ef, width="stretch", key="ov_effrank")
                st.caption(f"Where this team ranks among the {len(ctx.tracked)} "
                           "tracked teams in the league (100 = best).")

    # ── best players ──────────────────────────────────────────────────────────
    st.markdown("<div class='lab-hdr'>Who carries them</div>",
                unsafe_allow_html=True)
    if ctx.players:
        rated = [p for p in ctx.players if p["OVERALL"] is not None]
        # OVERALL is an event-derived rating — gate the hero cards behind the
        # entitlement-folded has_tracked flag (Free keeps the box PPG leaders).
        if ctx.has_tracked and rated:
            top = sorted(rated, key=lambda p: p["OVERALL"], reverse=True)[:3]
            cards = st.columns(max(len(top), 1))
            _medal = ["#f0a500", "#adb5bd", "#cd7f32"]
            for i, (col, p) in enumerate(zip(cards, top)):
                col.markdown(
                    f"<div class='glass-tile'>"
                    f"<div class='spotlight-num' style='color:{ctx.ACCENT};font-size:42px'>"
                    f"{p['OVERALL']:.0f}</div>"
                    f"<div class='glass-label' style='color:{_medal[i]}'>OVERALL</div>"
                    f"<div class='glass-sub' style='color:#f0f6fc;font-weight:700;"
                    f"font-size:13px;margin-top:6px'>#{p['number']} {p['name']}</div>"
                    f"<div class='glass-sub'>{p['PPG']:.1f} pts · {p['RPG']:.1f} reb · "
                    f"{p['APG']:.1f} ast</div>"
                    f"</div>", unsafe_allow_html=True)

        # Scoring leaders full-width. The top-3 OVERALL hero cards above ARE the
        # OVERALL leaderboard now — the old "Top rated" bar duplicated them.
        st.markdown("**Scoring leaders** — points / game")
        sl = sorted([p for p in ctx.players if p["PPG"] is not None],
                    key=lambda p: p["PPG"], reverse=True)[:7]
        st.plotly_chart(
            ctx.leader_bar(sl, "PPG", lambda r: f"#{r['number']} {r['name']}",
                        lambda r: r["PPG"], lambda v: f"{v:.1f}",
                        color=ctx.ACCENT, height=260),
            width="stretch", key="ov_ppg")

    # ── four factors & scoring mix — every stat aligned to the league ───────────
    if ctx.has_tracked:
        st.markdown("<div class='lab-hdr'>Four factors &amp; scoring mix — vs "
                    "league</div>", unsafe_allow_html=True)
        _AMBER = "#d29922"
        lpools = ctx.league_stat_pools(ctx.gender, getattr(ctx, "season", "Current"))
        me = lpools.get(ctx.team_id, {})

        def _vals(key):
            return [s[key] for s in lpools.values() if s.get(key) is not None]

        def _lg_avg(key):
            v = _vals(key)
            return sum(v) / len(v) if v else 0.0

        def _lg_rank(key, hib):
            v = _vals(key)
            mv = me.get(key)
            if mv is None or not v:
                return None, len(v)
            return sum(1 for x in v if (x > mv if hib else x < mv)) + 1, len(v)

        def _rcolor(rk, tot):
            if not rk or tot <= 1:
                return ctx.GREY
            p = rk / tot
            return ctx.GOOD if p <= 0.25 else (_AMBER if p <= 0.50 else ctx.BAD)

        def _pbar(rk, tot):
            if not rk or tot <= 1:
                return ""
            pct = (1 - (rk - 1) / (tot - 1)) * 100
            c = ctx.GOOD if pct >= 75 else (_AMBER if pct >= 50 else ctx.BAD)
            return (f"<div style='background:#21262d;border-radius:3px;height:4px;"
                    f"overflow:hidden;margin-top:5px'><div style='background:{c};"
                    f"width:{pct:.0f}%;height:100%;border-radius:3px'></div></div>")

        def _ff_card(col, label, key, opp_key, hib, fmt, scale=100.0):
            # Renders via the shared cards.factor_tile so the signature four-factor
            # grid uses the same tile grammar as any other team surface. Engine
            # logic (percentile / rank) stays here; only the markup is centralized.
            tv = me.get(key, 0.0) * scale
            ov = me.get(opp_key, 0.0) * scale
            lg = _lg_avg(key) * scale
            rk, tot = _lg_rank(key, hib)
            good = (tv >= ov) if hib else (tv <= ov)
            col.markdown(
                CARDS.factor_tile(label, fmt.format(tv), fmt.format(ov),
                                  fmt.format(lg), rk, tot, value_good=good),
                unsafe_allow_html=True)

        def _stat_card(col, label, key, hib, fmt, scale=1.0, sub=""):
            v = me.get(key)
            rk, tot = _lg_rank(key, hib)
            rc = _rcolor(rk, tot)
            vtxt = "—" if v is None else fmt.format(v * scale)
            rstr = (f"<div style='font-size:9px;font-weight:700;color:{rc};"
                    f"margin-top:2px'>#{rk}/{tot}</div>") if rk else ""
            col.markdown(
                f"<div style='background:{CARD_BG};border:1px solid {GRID};"
                f"border-radius:8px;padding:10px 8px;text-align:center'>"
                f"<div style='font-size:9px;color:{ctx.GREY};text-transform:uppercase;"
                f"letter-spacing:1px'>{label}</div>"
                f"<div style='font-size:18px;font-weight:800;color:{ctx.BLUE}'>{vtxt}"
                f"</div><div style='font-size:9px;color:#6e7681;margin-top:1px'>"
                f"{sub}</div>{rstr}{_pbar(rk, tot)}</div>", unsafe_allow_html=True)

        st.markdown("<div style='font-size:11px;color:#f0a500;font-weight:700;"
                    "text-transform:uppercase;letter-spacing:1px;margin:2px 0 4px'>"
                    "Offense</div>", unsafe_allow_html=True)
        _o = st.columns(4)
        _ff_card(_o[0], "eFG%", "efg", "oefg", True, "{:.1f}%")
        _ff_card(_o[1], "TOV%", "tov", "opp_tov", False, "{:.1f}%")
        _ff_card(_o[2], "OREB%", "orb", "opp_orb", True, "{:.1f}%")
        _ff_card(_o[3], "FT rate", "ftr", "opp_ftr", True, "{:.3f}", scale=1.0)

        st.markdown("<div style='font-size:11px;color:#58a6ff;font-weight:700;"
                    "text-transform:uppercase;letter-spacing:1px;margin:8px 0 4px'>"
                    "Defense</div>", unsafe_allow_html=True)
        _d = st.columns(4)
        _ff_card(_d[0], "Opp eFG%", "oefg", "efg", False, "{:.1f}%")
        _ff_card(_d[1], "Opp TOV%", "opp_tov", "tov", True, "{:.1f}%")
        _ff_card(_d[2], "DREB%", "dreb", "opp_orb", True, "{:.1f}%")
        _ff_card(_d[3], "Opp FT rate", "opp_ftr", "ftr", False, "{:.3f}", scale=1.0)

        # 4F-PPP — what the factor profile alone predicts per possession, vs the
        # actual rating. Gap = shot-making the factor averages can't see.
        if all(me.get(k) is not None for k in ("efg", "tov", "orb", "ftr")):
            import helpers.stats as _S
            _xo = _S.four_factor_ppp(me["efg"], me["tov"], me["orb"], me["ftr"])
            _parts = [f"off expected <b>{_xo:.2f}</b>"]
            if me.get("ortg") is not None:
                _parts.append(f"actual {me['ortg']/100:.2f} "
                              f"({me['ortg']/100 - _xo:+.2f} shot-making)")
            if all(me.get(k) is not None
                   for k in ("oefg", "opp_tov", "opp_orb", "opp_ftr")):
                _xd = _S.four_factor_ppp(me["oefg"], me["opp_tov"],
                                         me["opp_orb"], me["opp_ftr"])
                _parts.append(f"· def expected <b>{_xd:.2f}</b>")
                if me.get("drtg") is not None:
                    _parts.append(f"actual {me['drtg']/100:.2f}")
            st.markdown(
                "<div style='font-size:12px;color:#8b949e;margin:6px 0 2px'>"
                "<b style='color:#f0a500'>4F-PPP</b> — points/possession the four "
                "factors alone predict: " + " ".join(_parts) + "</div>",
                unsafe_allow_html=True)

        # Key stats DEMOTED into an expander — ORtg/DRtg restate the metric row,
        # the shooting splits restate the four-factor eFG card. Collapsed by default.
        with st.expander("Key stats — vs league"):
            _k1 = st.columns(4)
            _stat_card(_k1[0], "TS%", "ts", True, "{:.1f}%", 100.0, "true shooting")
            _stat_card(_k1[1], "FG%", "fg", True, "{:.1f}%", 100.0, "field goal")
            _stat_card(_k1[2], "3P%", "tp", True, "{:.1f}%", 100.0, "three-point")
            _stat_card(_k1[3], "Paint FG%", "paint", True, "{:.1f}%", 100.0, "at the rim")
            _k2 = st.columns(4)
            _stat_card(_k2[0], "AST/TO", "ast_tov", True, "{:.2f}", 1.0, "ball security")
            _stat_card(_k2[1], "STL%", "stl_rate", True, "{:.1f}%", 1.0, "steals / 100")
            _stat_card(_k2[2], "ORtg", "ortg", True, "{:.1f}", 1.0, "pts / 100")
            _stat_card(_k2[3], "DRtg", "drtg", False, "{:.1f}", 1.0, "allowed / 100")
            st.caption("Each card: this team's value (green = beats what they allow / "
                       f"red = worse), opponent value, league average over the "
                       f"{len(lpools)} tracked teams, and league rank + percentile bar.")

        st.markdown("**Where the points come from**")
        dn = CARDS.scoring_donut(
            ctx.soff["pts2"], ctx.soff["pts3"], ctx.soff["ptsft"],
            colors=(ctx.ACCENT, ctx.BLUE, ctx.GREY), height=300, margin_top=30,
            center=f"{ctx.soff['pct_paint']*100:.0f}%<br>"
                   "<span style='font-size:10px'>in paint</span>")
        st.plotly_chart(dn, width="stretch", key="ov_src")

    # ── game-by-game: margin paired with offense/defense (APP3 trend charts) ────
    def _dual_axis(fig, y2_title, height=360):
        """MOV-bars-on-y1 + lines-on-y2 layout shared by the trend charts."""
        ctx.style(fig, height)
        fig.update_layout(
            barmode="relative", bargap=0.25,
            xaxis=dict(tickangle=-45, tickfont=dict(size=9)),
            yaxis=dict(title="MOV", showgrid=False, zerolinecolor="#30363d"),
            yaxis2=dict(title=y2_title, overlaying="y", side="right",
                        showgrid=False),
            legend=dict(orientation="h", y=-0.28))
        return fig

    # All four trend charts share MOV/margin bars on y1 + a line set on y2, so
    # they fold into one chart with a "View" switcher (less scroll, same data).
    _trend = ctx.bundle["trend"] if ctx.has_tracked else []

    # shot-creation mix shares per logged game (None where the game isn't tracked)
    cbg_ov = ctx.bd.get("creation_by_game", {}) if ctx.has_tracked else {}
    _self_sh, _crt_sh = [], []
    for g in ctx.log:
        c = cbg_ov.get(g["game_id"])
        if c and (c["self_FGA"] + c["asst_FGA"]):
            _tot = c["self_FGA"] + c["asst_FGA"]
            _self_sh.append(100 * c["self_FGA"] / _tot)
            _crt_sh.append(100 * c["asst_FGA"] / _tot)
        else:
            _self_sh.append(None)
            _crt_sh.append(None)
    _has_creation = any(v is not None for v in _self_sh)

    _opts = ["Scoring"]
    if _trend:
        _opts += ["Rating", "Per poss"]
    if _has_creation:
        _opts += ["Creation mix"]

    st.markdown("<div class='lab-hdr'>Game-by-game trend</div>",
                unsafe_allow_html=True)
    _view = (_segc("Overlay", _opts, default="Scoring", key="ov_trend_view")
             if len(_opts) > 1 else "Scoring") or "Scoring"

    _gx = [f"{g['date'][5:]} {g['site']} {g['opp'][:10]}" for g in ctx.log]
    _gmv = [g["margin"] for g in ctx.log]
    _gc = [ctx.GOOD if m >= 0 else ctx.BAD for m in _gmv]
    _tx = [f"{e['date'][5:]} vs {e['opp'][:10]}" for e in _trend]
    _tm = [e["margin"] for e in _trend]
    _tc = [ctx.GOOD if m >= 0 else ctx.BAD for m in _tm]

    fig = go.Figure()
    if _view == "Rating":
        fig.add_trace(go.Bar(
            x=_tx, y=_tm, name="MOV", marker_color=_tc, opacity=0.55,
            marker_line_width=0,
            hovertemplate="%{x}<br>MOV %{y:+.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=_tx, y=[e["ORtg"] for e in _trend], name="ORtg", yaxis="y2",
            mode="lines+markers", line=dict(color=ctx.ACCENT, width=2),
            marker=dict(size=6),
            hovertemplate="%{x}<br>ORtg %{y:.1f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=_tx, y=[e["DRtg"] for e in _trend], name="DRtg", yaxis="y2",
            mode="lines+markers", line=dict(color=ctx.BLUE, width=2, dash="dot"),
            marker=dict(size=6),
            hovertemplate="%{x}<br>DRtg %{y:.1f}<extra></extra>"))
        _dual_axis(fig, "Rating")
        _cap = ("MOV bars (green win / red loss); offensive and defensive rating "
                "(points per 100 possessions) on the right axis — tracked games.")
    elif _view == "Per poss":
        fig.add_trace(go.Bar(
            x=_tx, y=_tm, name="MOV", marker_color=_tc, opacity=0.45,
            marker_line_width=0,
            hovertemplate="%{x}<br>MOV %{y:+.0f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=_tx, y=[e["PPP"] for e in _trend], name="PPP", yaxis="y2",
            mode="lines+markers", line=dict(color=ctx.ACCENT, width=2),
            marker=dict(size=6),
            hovertemplate="%{x}<br>PPP %{y:.3f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=_tx, y=[e["oPPP"] for e in _trend], name="oPPP", yaxis="y2",
            mode="lines+markers", line=dict(color=AWAY, width=2, dash="dot"),
            marker=dict(size=6),
            hovertemplate="%{x}<br>oPPP %{y:.3f}<extra></extra>"))
        _dual_axis(fig, "PPP")
        _cap = ("MOV bars; points per possession scored (PPP) vs allowed (oPPP) "
                "on the right axis — tracked games.")
    elif _view == "Creation mix":
        fig.add_trace(go.Bar(
            x=_gx, y=_gmv, name="Margin", marker_color=_gc, marker_line_width=0,
            text=[f"{g['pf']}-{g['pa']}" for g in ctx.log], textposition="outside",
            textfont=dict(size=9),
            hovertemplate="%{x}<br>Margin %{y:+d}<extra></extra>"))
        fig.add_hline(y=0, line=dict(color="#30363d"))
        fig.add_trace(go.Scatter(
            x=_gx, y=_self_sh, name="% FG self-created", yaxis="y2",
            mode="lines+markers", connectgaps=True,
            line=dict(color=ctx.ACCENT, width=2.5), marker=dict(size=6),
            hovertemplate="%{x}<br>Self-created %{y:.0f}%<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=_gx, y=_crt_sh, name="% FG created (off pass)", yaxis="y2",
            mode="lines+markers", connectgaps=True,
            line=dict(color=ctx.BLUE, width=2.5), marker=dict(size=6),
            hovertemplate="%{x}<br>Created %{y:.0f}%<extra></extra>"))
        ctx.style(fig, 380)
        fig.update_layout(
            yaxis=dict(title="Margin"),
            yaxis2=dict(title="Share of FG %", overlaying="y", side="right",
                        range=[0, 100], showgrid=False, zerolinecolor="#30363d"))
        fig.update_xaxes(tickangle=-45)
        _cap = ("Bars: green = win, red = loss (final score labelled). Lines (right "
                "axis): the share of made/attempted FGs that were self-created (no "
                "pass) vs created off a pass, each tracked game.")
    else:  # Scoring — every completed game
        fig.add_trace(go.Bar(
            x=_gx, y=_gmv, name="MOV", marker_color=_gc, opacity=0.55,
            marker_line_width=0,
            hovertemplate="%{x}<br>MOV %{y:+d}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=_gx, y=[g["pf"] for g in ctx.log], name="Scored", yaxis="y2",
            mode="lines+markers", line=dict(color=ctx.ACCENT, width=2),
            marker=dict(size=6),
            hovertemplate="%{x}<br>Scored %{y}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=_gx, y=[g["pa"] for g in ctx.log], name="Allowed", yaxis="y2",
            mode="lines+markers", line=dict(color=AWAY, width=2, dash="dot"),
            marker=dict(size=6),
            hovertemplate="%{x}<br>Allowed %{y}<extra></extra>"))
        _dual_axis(fig, "Points")
        _cap = ("MOV bars (green win / red loss) on the left axis; points scored "
                "and allowed on the right — every completed game.")
    st.plotly_chart(fig, width="stretch", key="ov_trend")
    st.caption(_cap)
