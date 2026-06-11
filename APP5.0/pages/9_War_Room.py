"""
9_War_Room.py — Monte-Carlo matchups, season sims and bracket odds.

The ratings give a single expected margin; this page turns that into the
distributions coaches actually ask for: "what are our odds Friday?", "how many
wins should we really have?", "what are our title odds?". Everything rolls the
opponent-adjusted ratings thousands of times via the (previously dormant)
helpers/simulation.py engine — no new math, pure surfacing.

Three tabs:
  • Matchup    — predict any two teams (score, win prob, line-by-line margin)
                 plus the full simulated margin distribution.
  • Season sim — replay every finished game N times → expected wins + luck.
  • Bracket    — seed a single-elim field by rating → championship odds.

Display + controls only; all simulation lives in the Streamlit-free engine.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from helpers.ui import (page_chrome, style_fig as _style, empty_state, team_color,
                        chart as _chart, AWAY, GOOD, BAD, gender_radio, gender_label)
from helpers.cards import bar_h, team_short, style_df as _style_df
from helpers.glossary import glossary_tab
import helpers.team_ratings as TR
import helpers.predictor as PRED
import helpers.simulation as SIM
import helpers.player_ratings as PR
import helpers.lineups as LU
import helpers.team_analytics as TA
from database.db import query

_cfg, ACCENT = page_chrome()


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER + LEAGUE + PRECISION
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    "<div class='lab-hero'><h1>War Room — Simulations &amp; Matchups</h1>"
    "<p>Project any matchup, roll the season thousands of times, and bracket the "
    "title. Monte-Carlo odds straight from the opponent-adjusted ratings.</p>"
    "</div>", unsafe_allow_html=True)

cc = st.columns([2, 3])
gender = gender_radio(cc[0])
n = cc[1].select_slider(
    "Simulations per scenario", options=[5000, 20000, 50000], value=SIM.DEFAULT_N,
    format_func=lambda v: f"{v // 1000}k sims",
    help="More sims = smoother odds, slightly slower. 20k is plenty for HS fields.")


# ── cached ratings + sims (keyed by hashable args only — never the dict) ────────
@st.cache_data(ttl=600, show_spinner=False)
def _scored(g):
    return TR.score_ratings(gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _tracked(g):
    return TR.tracked_ratings(gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _sim_game(g, a, b, home, n):
    return SIM.simulate_game(_scored(g), a, b, home=home, n=n)


@st.cache_data(ttl=600, show_spinner=False)
def _sim_season(g, n):
    return SIM.simulate_season(_scored(g), SIM.schedule_from_results(g), n=n)


@st.cache_data(ttl=600, show_spinner=False)
def _sim_bracket(g, field, n):
    return SIM.simulate_tournament(_scored(g), list(field), n=n)


scored = _scored(gender)
tracked = _tracked(gender)

if not scored:
    empty_state(
        "No rated teams yet",
        "Enter game results in the Input Hub and track a few games — the War Room "
        "simulates straight from the league ratings.",
        cta="Start in the Input Hub")
    st.stop()

name_of = {t: r["name"] for t, r in scored.items()}
class_of = {t: r["class"] for t, r in scored.items()}
order = sorted(scored, key=lambda t: scored[t]["Rank"])


def _team_pair_colors(a, b):
    """Identity colours for two teams; fall back to accent/away if they collide."""
    ca, cb = team_color(name_of[a], a), team_color(name_of[b], b)
    return (ca, cb) if ca != cb else (ACCENT, AWAY)


def _round_labels(n_rounds):
    """Stage names for the bracket survival curve (named from the final inward)."""
    tail = ["Champion", "Final", "Semifinals", "Quarterfinals",
            "Round of 16", "Round of 32", "Round of 64"]
    out = []
    for k in range(1, n_rounds + 1):
        from_end = n_rounds - k          # 0 = champion
        out.append(tail[from_end] if from_end < len(tail) else f"Round {k}")
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _league_pool():
    """Every rated player league-wide for the cross-team lineup picker:
    pid, name, team(+id), class, gender, district + 0-100 ratings & per-game."""
    dist = {r["id"]: (r["district"] or "")
            for r in query("SELECT id, district FROM teams")}
    rows = []
    for _g in ("F", "M"):
        for pid, r in PR.player_stat_table(gender=_g, min_games=1).items():
            rows.append({
                "pid": pid, "name": r["name"], "team": r["team"],
                "team_id": r["team_id"], "class": r.get("class"), "gender": _g,
                "district": dist.get(r["team_id"], ""),
                "OVERALL": r.get("OVERALL"), "OFFENSE": r.get("OFFENSE"),
                "DEFENSE": r.get("DEFENSE"), "PLAYMAKING": r.get("PLAYMAKING"),
                "REBOUNDING": r.get("REBOUNDING"), "PPG": r.get("PPG"),
                "RPG": r.get("RPG"), "APG": r.get("APG")})
    return rows


@st.cache_data(ttl=600, show_spinner=False)
def _wl_table(g):
    return PR.player_stat_table(gender=g, min_games=1)


@st.cache_data(ttl=600, show_spinner=False)
def _wl_ctx(g):
    return TA.lineup_engine_context(g)


tab_match, tab_season, tab_bracket, tab_lineup, tab_gloss = st.tabs(
    ["Matchup", "Season sim", "Bracket", "Lineup", "Glossary"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — MATCHUP
# ══════════════════════════════════════════════════════════════════════════════
with tab_match:
    st.subheader("Matchup predictor")
    st.caption(
        f"Projected score, win probability, a line-by-line margin breakdown, and "
        f"the full margin distribution across {n:,} simulated games.")

    def _pfmt(t):
        return f"#{scored[t]['Rank']} {name_of[t]} ({class_of[t]})"

    pc = st.columns([3, 3, 2])
    ta = pc[0].selectbox("Team A", order, index=0, format_func=_pfmt, key="wr_a")
    tb = pc[1].selectbox("Team B", order, index=min(1, len(order) - 1),
                         format_func=_pfmt, key="wr_b")
    homep = pc[2].radio("Home court", ["Neutral", "Team A", "Team B"], key="wr_home")

    if ta == tb:
        st.info("Pick two different teams.")
    else:
        home_arg = ta if homep == "Team A" else (tb if homep == "Team B" else None)
        pred = PRED.predict_game(ta, tb, scored=scored, tracked=tracked,
                                 gender=gender, home=home_arg)
        if not pred:
            st.info("One of these teams is unrated.")
        else:
            wa, wb = pred["win_prob_a"] * 100, pred["win_prob_b"] * 100
            ca, cb = _team_pair_colors(ta, tb)

            m = st.columns(3)
            m[0].metric(pred["a_name"], f"{pred['pf_a']:.0f}", f"{wa:.0f}% win",
                        delta_color="off")
            m[1].metric("Spread", f"{name_of[pred['favorite']]} −{pred['spread']:.1f}",
                        pred["confidence"], delta_color="off")
            m[2].metric(pred["b_name"], f"{pred['pf_b']:.0f}", f"{wb:.0f}% win",
                        delta_color="off")

            # win-probability split bar (team-coloured)
            wp = go.Figure()
            wp.add_trace(go.Bar(
                x=[wa], y=["Win prob"], orientation="h", marker_color=ca,
                text=[f"{team_short(pred['a_name'])} {wa:.0f}%"],
                textposition="inside", insidetextanchor="middle",
                hovertemplate=f"{pred['a_name']}: {wa:.0f}%<extra></extra>"))
            wp.add_trace(go.Bar(
                x=[wb], y=["Win prob"], orientation="h", marker_color=cb,
                text=[f"{team_short(pred['b_name'])} {wb:.0f}%"],
                textposition="inside", insidetextanchor="middle",
                hovertemplate=f"{pred['b_name']}: {wb:.0f}%<extra></extra>"))
            wp.update_layout(barmode="stack", showlegend=False)
            wp.update_xaxes(range=[0, 100], visible=False)
            wp.update_yaxes(visible=False)
            _style(wp, 110, margin=dict(l=4, r=4, t=10, b=4))
            st.plotly_chart(wp, width="stretch", key="wr_wp")

            # simulated margin distribution
            sim = _sim_game(gender, ta, tb, home_arg, n)
            margins = np.asarray(sim["margins"])
            edges = np.linspace(float(margins.min()), float(margins.max()), 41)
            centers = (edges[:-1] + edges[1:]) / 2
            counts, _ = np.histogram(margins, bins=edges)
            share = counts / max(counts.sum(), 1) * 100
            bar_colors = [ca if c >= 0 else cb for c in centers]
            dist = go.Figure(go.Bar(
                x=centers, y=share, marker_color=bar_colors, marker_line_width=0,
                hovertemplate="margin %{x:+.0f} · %{y:.1f}% of sims<extra></extra>"))
            dist.add_vline(x=0, line=dict(color="#8b949e", dash="dot"))
            dist.add_vline(x=sim["mean_margin"], line=dict(color=ACCENT, width=2))
            dist.add_vrect(x0=sim["p05"], x1=sim["p95"], line_width=0,
                           fillcolor="rgba(240,165,0,0.07)")
            dist.update_xaxes(title=f"Projected margin  ({team_short(pred['a_name'])} "
                                    f"− {team_short(pred['b_name'])})")
            dist.update_yaxes(title="% of sims")
            _style(dist, 300)
            _chart(dist, key="wr_margin",
                   data=pd.DataFrame({"Margin": centers, "% of sims": share}))
            st.caption(
                f"**{pred['a_name']} {pred['pf_a']:.0f} – {pred['pf_b']:.0f} "
                f"{pred['b_name']}** · total {pred['total']:.0f} · "
                f"{pred['a_name']} wins **{sim['win_a'] * 100:.0f}%** of {n:,} sims · "
                f"90% of outcomes land between {sim['p05']:+.0f} and "
                f"{sim['p95']:+.0f} · {pred['confidence']}.")

            st.markdown("**Where the margin comes from**")
            st.dataframe(
                pd.DataFrame([{"Component": c["label"], "Points": c["value"],
                               "Detail": c["note"]} for c in pred["components"]]),
                hide_index=True, width="stretch")

            if pred["tracked"]:
                tk = pred["tracked"]
                st.markdown("**Tracked possession projection** — both teams have "
                            "tracked games")
                tcl = st.columns(4)
                tcl[0].metric("Pace", f"{tk['pace']:.0f}")
                tcl[1].metric(f"{team_short(pred['a_name'])} pts", f"{tk['pf_a']:.0f}")
                tcl[2].metric(f"{team_short(pred['b_name'])} pts", f"{tk['pf_b']:.0f}")
                tcl[3].metric("ORtg A / B", f"{tk['ortg_a']:.0f} / {tk['ortg_b']:.0f}")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — SEASON SIM
# ══════════════════════════════════════════════════════════════════════════════
with tab_season:
    st.subheader("Season simulation")
    st.caption(
        f"Replays every finished game {n:,} times from the ratings to get each "
        "team's **expected wins** — and the **luck** baked into their actual "
        "record (actual minus expected).")

    sea = _sim_season(gender, n)
    if not sea:
        empty_state("No finished games to simulate",
                    "Enter at least one final score in the Input Hub and the season "
                    "simulation lights up here.")
    else:
        rows = []
        for t, d in sea.items():
            actual = scored.get(t, {}).get("W")
            luck = (actual - d["exp_wins"]) if actual is not None else None
            rows.append({"Team": name_of.get(t, d["name"]), "G": d["games"],
                         "Actual W": actual, "Exp W": d["exp_wins"], "Luck": luck})
        rows.sort(key=lambda r: -r["Exp W"])
        df = pd.DataFrame(rows)

        # luck scatter — actual vs expected, y=x diagonal
        pts = [r for r in rows if r["Actual W"] is not None]
        if pts:
            xs = [r["Exp W"] for r in pts]
            ys = [r["Actual W"] for r in pts]
            lim = max(max(xs), max(ys)) + 1
            sc = go.Figure()
            sc.add_trace(go.Scatter(
                x=[0, lim], y=[0, lim], mode="lines",
                line=dict(color="#30363d", dash="dot"), hoverinfo="skip",
                showlegend=False))
            sc.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers+text",
                text=[team_short(r["Team"]) for r in pts], textposition="top center",
                textfont=dict(size=9, color="#8b949e"),
                marker=dict(size=11,
                            color=[GOOD if r["Luck"] >= 0 else BAD for r in pts],
                            line=dict(width=0.5, color="#0d1117")),
                hovertemplate="%{text}<br>expected %{x:.1f} · actual %{y} wins"
                              "<extra></extra>", showlegend=False))
            sc.update_xaxes(title="Expected wins (true talent)")
            sc.update_yaxes(title="Actual wins")
            _style(sc, 420)
            _chart(sc, data=pd.DataFrame(pts), key="wr_luck")
            st.caption("Above the line = winning more than the ratings expect "
                       "(green, lucky / clutch); below = unlucky (red).")

        st.dataframe(
            _style_df(df, grad_cols=["Exp W"], signed_cols=["Luck"]),
            hide_index=True, width="stretch", key="wr_seas_tbl")

        # per-team win distribution
        pick = st.selectbox("Win distribution for", order,
                            format_func=lambda t: name_of[t], key="wr_seas_pick")
        if pick in sea:
            d = sea[pick]
            wd = np.asarray(d["win_dist"])
            xs = list(range(len(wd)))
            fig = go.Figure(go.Bar(
                x=xs, y=wd * 100, marker_color=team_color(name_of[pick], pick),
                marker_line_width=0,
                hovertemplate="%{x} wins · %{y:.1f}% of seasons<extra></extra>"))
            actual = scored.get(pick, {}).get("W")
            if actual is not None:
                fig.add_vline(x=actual, line=dict(color=GOOD, width=2),
                              annotation_text=f"actual {actual}")
            fig.add_vline(x=d["exp_wins"], line=dict(color=ACCENT, dash="dot"),
                          annotation_text=f"exp {d['exp_wins']:.1f}")
            fig.update_xaxes(title="Wins", dtick=1)
            fig.update_yaxes(title="% of simulated seasons")
            _style(fig, 300)
            st.plotly_chart(fig, width="stretch", key="wr_seas_dist")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — BRACKET
# ══════════════════════════════════════════════════════════════════════════════
with tab_bracket:
    st.subheader("Bracket / tournament odds")
    st.caption(
        f"Seed a single-elimination field by rating and roll the bracket {n:,} "
        "times — byes to the next power of two are handled automatically.")

    default_field = order[:min(8, len(order))]
    field = st.multiselect(
        "Tournament field", order, default=default_field,
        format_func=lambda t: f"#{scored[t]['Rank']} {name_of[t]}", key="wr_field")

    if len(field) < 2:
        empty_state("Pick at least two teams",
                    "Choose a tournament field above to simulate championship odds.")
    else:
        res = _sim_bracket(gender, tuple(field), n)
        if not res:
            empty_state("Not enough rated teams in the field",
                        "Add more rated teams to simulate the bracket.")
        else:
            top = res[:12]
            names = [team_short(d["name"]) for d in top][::-1]
            vals = [d["champ_pct"] for d in top][::-1]
            texts = [f"{d['champ_pct']:.1f}%" for d in top][::-1]
            st.markdown("**Championship odds**")
            st.plotly_chart(bar_h(names, vals, texts, color=ACCENT),
                            width="stretch", key="wr_title")

            # round-by-round survival heatmap
            n_rounds = len(res[0]["rounds"]) - 1
            if n_rounds >= 1:
                labels = _round_labels(n_rounds)
                z = [[d["rounds"][k] * 100 for k in range(1, n_rounds + 1)]
                     for d in res]
                yt = [f"{d['seed']}. {team_short(d['name'])}" for d in res]
                hm = go.Figure(go.Heatmap(
                    z=z, x=labels, y=yt, colorscale="Turbo", zmin=0, zmax=100,
                    colorbar=dict(title="%", thickness=12),
                    hovertemplate="%{y}<br>%{x}: %{z:.1f}%<extra></extra>"))
                hm.update_yaxes(autorange="reversed")
                _style(hm, max(300, 26 * len(res) + 80))
                st.markdown("**Survival curve — odds of reaching each round**")
                st.plotly_chart(hm, width="stretch", key="wr_surv")

            df = pd.DataFrame([{
                "Seed": d["seed"], "Team": d["name"], "Champ %": d["champ_pct"],
                "Finals %": (round(d["finals_odds"] * 100, 1)
                             if d["finals_odds"] is not None else None),
            } for d in res])
            st.dataframe(
                df, hide_index=True, width="stretch", key="wr_brk_tbl",
                column_config={
                    "Champ %": st.column_config.ProgressColumn(
                        "Champ %", format="%.1f", min_value=0,
                        max_value=float(max(d["champ_pct"] for d in res) or 1))})


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — LINEUP CREATOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_lineup:
    st.subheader("Lineup creator")
    _lmode = st.radio("Build from", ["One team", "Any team"],
                      horizontal=True, key="wl_mode")

    if _lmode == "One team":
        st.caption("Pick a team and a five for a possession-calibrated "
                   "projection (ORtg / DRtg / Net vs the league) plus the observed "
                   "on-court rating and the best bench swaps.")
        _t = st.selectbox("Team", order,
                          format_func=lambda t: f"#{scored[t]['Rank']} {name_of[t]}",
                          key="wl1_team")
        _tbl = _wl_table(gender)
        _rows = [dict(r, _pid=pid) for pid, r in _tbl.items() if r["team_id"] == _t]
        if not _rows:
            empty_state("No rated players on this team yet",
                        "Track a game for them first.")
        else:
            _ctxd = _wl_ctx(gender)
            _lab = {}
            for r in _rows:
                _b = f"#{r['number']} {r['name']}"
                _lab[r["_pid"]] = (f"{_b} (OVR {r['OVERALL']:.0f})"
                                   if r.get("OVERALL") is not None else _b)
            _def5 = [r["_pid"] for r in
                     sorted(_rows, key=lambda r: (r.get("MIN") or 0), reverse=True)[:5]]
            _chosen = st.multiselect("Lineup (up to 5)", list(_lab), default=_def5,
                                     format_func=lambda pid: _lab[pid],
                                     max_selections=5, key="wl1_pick")
            if _chosen:
                _pred = TA.lineup_prediction(_rows, _chosen, _ctxd, _t)
                _m = st.columns(5)
                _m[0].metric("Proj ORtg", f"{_pred['ORtg']:.1f}"
                             if _pred["ORtg"] is not None else "—")
                _m[1].metric("Proj DRtg", f"{_pred['DRtg']:.1f}"
                             if _pred["DRtg"] is not None else "—")
                _tn = _pred["league"].get("team_net")
                _nd = (f"{_pred['NetRtg'] - _tn:+.1f} vs team"
                       if _tn is not None and _pred["NetRtg"] is not None else None)
                _m[2].metric("Proj Net", f"{_pred['NetRtg']:+.1f}"
                             if _pred["NetRtg"] is not None else "—", _nd)
                _m[3].metric("Proj score", _pred["score_line"])
                _m[4].metric("League rank",
                             f"#{_pred['league']['rank']} / {_pred['league']['of']}")
                _gids = [gr["id"] for gr in query(
                    "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) "
                    "AND tracked=1", (_t, _t))]
                _obs = LU.custom_unit(_t, list(_chosen), game_ids=_gids) if _gids else None
                if _obs and _obs.get("poss"):
                    st.markdown("**Observed together — tracked games**")
                    _oc = st.columns(4)
                    _oc[0].metric("Net / 100", f"{_obs['Net']:+.1f}")
                    _oc[1].metric("ORtg", f"{_obs['ORtg']:.1f}")
                    _oc[2].metric("DRtg", f"{_obs['DRtg']:.1f}")
                    _oc[3].metric("Possessions", f"{_obs['poss']:.0f}")
                else:
                    st.caption("This five hasn't shared the floor in tracked games "
                               "— no observed rating.")
                _cb = _pred.get("contrib") or []
                if _cb:
                    st.markdown("**Who drives the projection**")
                    _sca = go.Figure(go.Scatter(
                        x=[c["off_pts100"] for c in _cb],
                        y=[c["def_z"] for c in _cb], mode="markers+text",
                        text=[f"#{c['number']}" for c in _cb],
                        textposition="top center",
                        marker=dict(
                            size=[max(12, c["usg_share"] * 90) for c in _cb],
                            color=[c["off_pts100"] for c in _cb],
                            colorscale="Viridis", showscale=False,
                            line=dict(width=1, color="#30363d")),
                        hovertext=[c["name"] for c in _cb],
                        hovertemplate="%{hovertext}<br>Off/100 %{x:.1f} · "
                                      "Def z %{y:.2f}<extra></extra>"))
                    _sca.add_hline(y=0, line=dict(color="#30363d", dash="dot"))
                    _sca.update_xaxes(title="Offensive points / 100 contributed")
                    _sca.update_yaxes(title="Defensive z (higher = better)")
                    _style(_sca, 340)
                    st.plotly_chart(_sca, width="stretch", key="wl1_contrib")
                _bench = [r for r in _rows if r["_pid"] not in _chosen]
                if _bench and len(_chosen) == 5 and _pred["NetRtg"] is not None:
                    _base = _pred["NetRtg"]
                    _swaps = []
                    for _out in _chosen:
                        for _bp in _bench:
                            _nw = [_bp["_pid"] if x == _out else x for x in _chosen]
                            _nn = TA.lineup_prediction(_rows, _nw, _ctxd, _t)["NetRtg"]
                            if _nn is not None:
                                _swaps.append((_nn - _base, _out, _bp))
                    _ups = sorted([sw for sw in _swaps if sw[0] > 0.05],
                                  key=lambda sw: -sw[0])[:3]
                    _nmap = {r["_pid"]: r for r in _rows}
                    st.markdown("**Best bench swaps**")
                    if _ups:
                        for _d, _out, _bp in _ups:
                            _o = _nmap[_out]
                            st.markdown(f"- **+{_d:.1f} Net** — sub in "
                                        f"#{_bp['number']} {_bp['name']} for "
                                        f"#{_o['number']} {_o['name']}")
                    else:
                        st.caption("No bench swap improves this five — it's the "
                                   "team's best available unit.")
                for _f in _pred.get("flags", []):
                    st.caption(_f)
    else:
        st.caption(
            "Build any five — from one team or across the whole league. Filter the "
            "pool, pick up to five, and get a unit blended from each player's 0-100 "
            "ratings and per-game production. If all five are from one team, their "
            "observed on-court net from tracked games is shown too.")

        _pool = _league_pool()
        _fc = st.columns(4)
        _gsel = _fc[0].multiselect(
            "Gender", ["F", "M"], format_func=gender_label, key="wl_g")
        _dsel = _fc[1].multiselect(
            "District", sorted({r["district"] for r in _pool if r["district"]}),
            key="wl_d")
        _csel = _fc[2].multiselect(
            "Class", sorted({r["class"] for r in _pool if r["class"]}), key="wl_c")
        _tsel = _fc[3].multiselect(
            "Team", sorted({r["team"] for r in _pool}), key="wl_t")
        _filt = [r for r in _pool
                 if (not _gsel or r["gender"] in _gsel)
                 and (not _dsel or r["district"] in _dsel)
                 and (not _csel or r["class"] in _csel)
                 and (not _tsel or r["team"] in _tsel)]
        _idx = {r["pid"]: r for r in _filt}

        def _wl_label(pid):
            r = _idx[pid]
            ov = f" · OVR {r['OVERALL']:.0f}" if r["OVERALL"] is not None else ""
            return f"{r['name']} · {r['team']}{ov}"

        _pick = st.multiselect("Players (pick up to 5)", list(_idx),
                               format_func=_wl_label, max_selections=5, key="wl_pick")
        if not _pick:
            st.caption("Choose players above to build a unit. Tip: filter Team to one "
                       "team to build that team's five; leave filters open to mix "
                       "anyone in the league.")
        else:
            _sel = [_idx[p] for p in _pick]

            def _avg(k):
                vs = [r[k] for r in _sel if r[k] is not None]
                return sum(vs) / len(vs) if vs else None

            def _tot(k):
                return sum(r[k] or 0 for r in _sel)

            _rc = st.columns(5)
            for _col, (_lbl, _k) in zip(_rc, [
                    ("Overall", "OVERALL"), ("Offense", "OFFENSE"),
                    ("Defense", "DEFENSE"), ("Playmaking", "PLAYMAKING"),
                    ("Rebounding", "REBOUNDING")]):
                _v = _avg(_k)
                _col.metric(_lbl, f"{_v:.0f}" if _v is not None else "—")
            _pcols = st.columns(4)
            _pcols[0].metric("Combined PPG", f"{_tot('PPG'):.1f}")
            _pcols[1].metric("Combined RPG", f"{_tot('RPG'):.1f}")
            _pcols[2].metric("Combined APG", f"{_tot('APG'):.1f}")
            _pcols[3].metric("Teams in unit", len({r["team"] for r in _sel}))

            _cats = ["OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]
            _rad = go.Figure(go.Scatterpolar(
                r=[_avg(k) or 0 for k in _cats] + [_avg(_cats[0]) or 0],
                theta=[c.title() for c in _cats] + [_cats[0].title()],
                fill="toself", line=dict(color=ACCENT)))
            _rad.update_layout(polar=dict(radialaxis=dict(range=[0, 100])),
                               showlegend=False)
            _style(_rad, 330)
            st.plotly_chart(_rad, width="stretch", key="wl_radar")

            st.dataframe(pd.DataFrame([{
                "Player": r["name"], "Team": r["team"], "Class": r["class"],
                "OVR": round(r["OVERALL"]) if r["OVERALL"] is not None else None,
                "PPG": round(r["PPG"], 1) if r["PPG"] is not None else None,
                "RPG": round(r["RPG"], 1) if r["RPG"] is not None else None,
                "APG": round(r["APG"], 1) if r["APG"] is not None else None,
            } for r in _sel]), hide_index=True, width="stretch", key="wl_tbl")

            _teams = {r["team_id"] for r in _sel}
            if len(_teams) == 1 and len(_sel) >= 2:
                _tid = next(iter(_teams))
                _gids = [g["id"] for g in query(
                    "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) AND tracked=1",
                    (_tid, _tid))]
                _obs = LU.custom_unit(_tid, [r["pid"] for r in _sel],
                                      game_ids=_gids) if _gids else None
                if _obs and _obs.get("poss"):
                    st.markdown("**Observed together — tracked games**")
                    _oc = st.columns(4)
                    _oc[0].metric("Net / 100", f"{_obs['Net']:+.1f}")
                    _oc[1].metric("ORtg", f"{_obs['ORtg']:.1f}")
                    _oc[2].metric("DRtg", f"{_obs['DRtg']:.1f}")
                    _oc[3].metric("Possessions", f"{_obs['poss']:.0f}")
                else:
                    st.caption("This five hasn't shared the floor in tracked games — no "
                               "observed rating.")
            st.caption("Unit ratings = averaged 0-100 ratings + summed per-game "
                       "production. Observed net needs the five to have actually played "
                       "together (one team, tracked games); cross-team fives are a "
                       "ratings projection only.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_gloss:
    glossary_tab("wr")
