"""
0_Analytics_Hub.py — Executive Dashboard (the landing page).

A best-in-class BI dashboard: a top KPI scorecard row, an asymmetric
command-center grid (gauges left, hero charts center, ranked leaderboards with
sparklines right), the Game of the Season (dramatized win-prob ribbon), and quick
links into every tool. Data lives in a local SQLite database in the per-user data
dir (path resolved by database/db.py). Display-only; all math is in the
Streamlit-free engines.

Routed by Main.py via st.navigation (this is the `default` page). Lives under
pages/ but is referenced explicitly — st.navigation ignores pages/ auto-discovery.
"""
import sys
import streamlit as st
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Page boot (config + global CSS + theme + login + cache sync) ───────────────
from helpers.ui import (page_chrome, page_header, style_fig as _style,
                        gauge as _gauge, lab_hero as _lab_hero,
                        wp_ribbon as _wp_ribbon, spotlight as _spotlight,
                        mini_tile as _mini, GOOD, BAD, AWAY)

_cfg, ACCENT = page_chrome("Analytics Hub")

import pandas as pd
import plotly.graph_objects as go
import helpers.trends as TRD
import helpers.auth as AUTH
import helpers.entitlement as ENT


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD DATA  (one cached pass; resilient to an empty DB)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _dashboard(gender):
    """Everything the executive dashboard renders, in one cached bundle."""
    d = {"teams": 0, "tracked": 0, "players": 0, "games_played": 0,
         "scored": {}, "form": {}, "top": None, "hot": None,
         "scorer": None, "leaders": [], "scorer_rows": [], "game": None,
         "avg_ortg": None, "top_trk": None, "player_avg_ppg": 0, "errors": []}

    def _fail(section, exc):
        d["errors"].append(f"{section}: {type(exc).__name__}: {exc}")

    # core ratings — everything else depends on this; bail out if it fails
    try:
        import helpers.team_ratings as TR
        import helpers.league_analytics as LA
        import helpers.player_ratings as PR
        import helpers.stats as S
        import helpers.win_probability as WP
        from database.db import query

        scored = TR.score_ratings(gender=gender)
        d["scored"] = scored
        d["teams"] = len(scored)
        d["tracked"] = len(TR._finished_games(gender=gender, tracked_only=True))
        d["games_played"] = (sum(s["GP"] for s in scored.values()) // 2) if scored else 0
        if not scored:
            return d

        order = sorted(scored.values(), key=lambda r: r["Rank"])
        top = order[0]
        d["top"] = top
        id_of = {id(s): t for t, s in scored.items()}   # value-obj -> team id
        top_tid = id_of.get(id(top))
    except Exception as e:
        _fail("Team ratings", e)
        return d

    try:
        form = LA.team_form_stats(gender=gender)
        d["form"] = form
        hot_t = max((t for t in form if form[t]["Momentum"] is not None),
                    key=lambda t: form[t]["Momentum"], default=None)
        if hot_t and hot_t in scored:
            d["hot"] = (scored[hot_t]["name"], form[hot_t]["Momentum"],
                        "".join(form[hot_t]["form"][-5:]))
    except Exception as e:
        _fail("Team form", e)

    try:
        # leaderboard rows (top 12 by power) with recent margin sparkline
        ptr = LA.per_team_results(gender)
        d["leaders"] = [{
            "Rank": s["Rank"], "Team": s["name"], "W": s["W"], "L": s["L"],
            "Power": s["Power"], "Net": s["AdjNet"], "tid": id_of.get(id(s)),
            "Form": [g["margin"] for g in ptr.get(id_of.get(id(s)), [])[-7:]],
        } for s in order[:12]]
    except Exception as e:
        _fail("Power rankings", e)

    try:
        # tracked efficiency for the top team's gauges
        tracked = TR.tracked_ratings(gender=gender)
        if tracked:
            d["avg_ortg"] = sum(t["ORtg"] for t in tracked.values()) / len(tracked)
            d["top_trk"] = tracked.get(top_tid)
    except Exception as e:
        _fail("Efficiency gauges", e)

    try:
        # player scoring leaderboard with per-game PTS sparkline
        table = PR.player_stat_table(gender=gender, min_games=1)
        d["players"] = len(table)
        if table:
            gbox = S.player_game_boxes()
            gdates = {r["id"]: r["date"] for r in query(
                "SELECT id, date FROM games WHERE tracked=1 AND season='Current'")}
            top_sc = sorted(table.values(),
                            key=lambda r: -(r["PPG"] if r.get("PPG") is not None
                                            else 0))[:10]
            d["scorer"] = (top_sc[0]["name"], top_sc[0]["team"], top_sc[0].get("PPG"))
            d["player_avg_ppg"] = (sum(r.get("PPG") or 0 for r in table.values())
                                   / len(table))
            name_to_pid = {(r["name"], r["team"]): pid for pid, r in table.items()}
            rows = []
            for r in top_sc:
                pid = name_to_pid.get((r["name"], r["team"]))
                series = []
                if pid and pid in gbox:
                    series = [b["PTS"] for gid, b in sorted(
                        gbox[pid].items(), key=lambda kv: gdates.get(kv[0], ""))]
                rows.append({"Player": r["name"], "Team": r["team"],
                             "PPG": r.get("PPG"), "OVR": r.get("OVERALL"),
                             "Trend": series, "pid": pid})
            d["scorer_rows"] = rows
    except Exception as e:
        _fail("Scoring leaders", e)

    try:
        # game of the season (highest GEI)
        best = None
        for gid in [r["id"] for r in query(
                "SELECT id FROM games WHERE tracked=1 AND season='Current'")]:
            g = query("""SELECT g.team1_id t1, g.team2_id t2, t1.name n1, t2.name n2,
                                g.home_score hs, g.away_score aws,
                                t1.gender gen FROM games g
                         JOIN teams t1 ON t1.id=g.team1_id
                         JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?""", (gid,))
            if not g or g[0]["gen"] != gender:
                continue
            g = g[0]
            evs = query("""SELECT ge.quarter, ge.time, ge.event_type, ge.shot_type,
                                  p.team_id tid FROM game_events ge
                           JOIN players p ON p.id=ge.primary_player_id
                           WHERE ge.game_id=? AND ge.shot_result='make'
                             AND ge.event_type IN ('shot','free_throw')""", (gid,))
            if not evs:
                continue

            evs.sort(key=lambda e: S.elapsed(e["quarter"], e["time"]))
            h = a = 0
            mc = [(0.0, 0)]
            for e in evs:
                v = e["shot_type"] if e["event_type"] == "shot" else 1
                if e["tid"] == g["t1"]:
                    h += v
                elif e["tid"] == g["t2"]:
                    a += v
                mc.append((S.elapsed(e["quarter"], e["time"]), h - a))
            _curve = WP.wp_curve(mc)
            gei = WP.game_excitement_index(_curve)
            if best is None or gei > best[0]:
                # events feed the win-prob curve only; display the official
                # final from games.home_score/away_score (event fallback).
                # Keep the curve + drama summary so the landing can DRAMATIZE
                # the game instead of throwing the curve away for a scalar.
                best = (gei, g["n1"], g["n2"],
                        g["hs"] if g["hs"] is not None else h,
                        g["aws"] if g["aws"] is not None else a,
                        _curve, WP.summarize(_curve))
        d["game"] = best
    except Exception as e:
        _fail("Game of the season", e)
    return d


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER + LEAGUE TOGGLE
# ══════════════════════════════════════════════════════════════════════════════

_lab_hero("Analytics Hub",
          sub="Track it · analyze it · predict it · scout it — "
              "the whole program at a glance.")

_gender = "F"
try:
    _gender = {"Girls": "F", "Boys": "M"}[
        st.radio("League", ["Girls", "Boys"], horizontal=True,
                 label_visibility="collapsed")]
except Exception:
    pass

D = _dashboard(_gender)

# Plan-level gate for the event-derived league-overview stats below (GEI, the
# top team's possession ratings, the OVERALL rating columns). Per the gating
# taxonomy, league-overview / leaderboard data is pool-agnostic, so has_paid_plan.
_paid = ENT.has_paid_plan(AUTH.current_user())

if D.get("errors"):
    st.warning("Some dashboard data failed to load")
    with st.expander("Error details"):
        for _msg in D["errors"]:
            st.write(f"- {_msg}")

if not D["scored"]:
    st.info("No finished games yet for this league. Log games in the Input Hub and "
            "Game Tracker to light up the dashboard.")
else:
    # ── top KPI scorecard row (with deltas vs baselines) ───────────────────────
    k = st.columns(5)
    k[0].metric("Teams rated", D["teams"])
    k[1].metric("Tracked games", D["tracked"],
                f"{D['games_played']} played total", delta_color="off")
    if D["top"]:
        k[2].metric("Top team", D["top"]["name"],
                    f"Power {D['top']['Power']:.0f}", delta_color="off")
    if D["hot"]:
        k[3].metric("Hottest", D["hot"][0],
                    f"{D['hot'][2]}" if D["hot"][2] else None, delta_color="off")
    if D["scorer"]:
        dl = (D["scorer"][2] - D.get("player_avg_ppg", 0)) if D["scorer"][2] else None
        k[4].metric("Top scorer", D["scorer"][0],
                    f"{dl:+.1f} vs avg ppg" if dl is not None else None)

    # ── game of the season — DRAMATIZED win-prob ribbon (Paid only) ────────────
    if D["game"] and _paid:
        from helpers.win_probability import excitement_label
        try:
            gei, n1, n2, h, a, _curve, _summ = D["game"]
            st.markdown("<div class='lab-hdr'>Game of the season</div>",
                        unsafe_allow_html=True)
            _gc = st.columns((5, 2), gap="medium")
            with _gc[0]:
                _wpfig = _wp_ribbon(_curve, home_name=n1, accent=ACCENT,
                                    height=230)
                if _wpfig is not None:
                    st.plotly_chart(_wpfig, width="stretch", key="wp_gots")
                else:
                    st.markdown(
                        f"<div class='glass-tile'>{n2} {a} @ {n1} {h}</div>",
                        unsafe_allow_html=True)
                st.caption(f"{n2} {a} @ {n1} {h} — {n1} win probability through "
                           f"the game.")
            with _gc[1]:
                st.markdown(
                    _spotlight(f"{gei:.1f}", "Game Excitement Index",
                               excitement_label(gei), color=ACCENT),
                    unsafe_allow_html=True)
                if _summ:
                    _m = st.columns(2)
                    _m[0].markdown(_mini("Lead changes",
                                         _summ.get("lead_changes", 0)),
                                   unsafe_allow_html=True)
                    _m[1].markdown(_mini("Peak swing",
                                         f"{_summ.get('peak_swing', 0) * 100:.0f}%"),
                                   unsafe_allow_html=True)
                    if _summ.get("comeback", 0) > 0.02:
                        st.markdown(
                            _mini("Biggest comeback",
                                  f"from {_summ.get('min_wp_winner', 0.5) * 100:.0f}% odds"),
                            unsafe_allow_html=True)
        except Exception:
            gei = D["game"][0]
            n1, n2, h, a = D["game"][1:5]
            st.markdown(
                f"<div class='glass-tile'><b>Game of the season</b> — "
                f"{n2} {a} @ {n1} {h} · "
                f"<span style='color:var(--accent)'>GEI {gei:.1f} · "
                f"{excitement_label(gei)}</span></div>",
                unsafe_allow_html=True)

    # ── command-center grid (gauges | hero charts | leaderboards) ──────────────
    col = st.columns((2, 4.4, 3), gap="medium")

    with col[0]:
        st.markdown("<div class='lab-hdr'>Top team pulse</div>", unsafe_allow_html=True)
        if D["top"]:
            st.plotly_chart(_gauge(D["top"]["Power"], "Power", 0, 100, ref=50,
                                   accent=ACCENT, height=170),
                            width="stretch", key="g_power")
            trk = D.get("top_trk")
            if trk and _paid:
                st.plotly_chart(_gauge(trk["ORtg"], "Off. rating", 60, 120,
                                       ref=D.get("avg_ortg"), accent=GOOD,
                                       height=170), width="stretch", key="g_ortg")
                st.plotly_chart(_gauge(trk["DRtg"], "Def. rating (low=good)", 60, 120,
                                       ref=D.get("avg_ortg"), accent=AWAY,
                                       height=170), width="stretch", key="g_drtg")
            elif trk and not _paid:
                st.caption("🔒 Possession ratings (ORtg / DRtg) are a Paid feature.")
            else:
                st.caption("Track a game for the top team to unlock efficiency gauges.")

    with col[1]:
        st.markdown("<div class='lab-hdr'>League power landscape</div>",
                    unsafe_allow_html=True)
        lead = D["leaders"]
        if lead:
            names = [r["Team"] for r in lead][::-1]
            powers = [r["Power"] for r in lead][::-1]
            hfig = go.Figure(go.Bar(
                x=powers, y=names, orientation="h",
                marker_color=[ACCENT if p >= 50 else "#6b7280" for p in powers],
                marker_line_width=0, text=[f"{p:.0f}" for p in powers],
                textposition="auto", customdata=[r["Net"] for r in lead][::-1],
                hovertemplate="%{y}: Power %{x:.0f} · Net %{customdata:+.1f}<extra></extra>"))
            hfig.add_vline(x=50, line=dict(color="#8b949e", width=1, dash="dot"))
            hfig.update_xaxes(title="Power rating (50 = league average)", range=[0, 100])
            _style(hfig, max(360, 26 * len(lead)))
            st.plotly_chart(hfig, width="stretch", key="hero_power")

        if D["form"]:
            st.markdown("<div class='lab-hdr'>Luck — actual vs expected wins</div>",
                        unsafe_allow_html=True)
            sc = D["scored"]
            fitems = [(t, v) for t, v in D["form"].items() if t in sc]
            fitems.sort(key=lambda kv: kv[1]["Luck_wins"])
            rows = [(sc[t]["name"], v["Luck_wins"]) for t, v in fitems]
            if len(rows) > 15:
                rows = rows[:8] + rows[-7:]
            lfig = go.Figure(go.Bar(
                x=[r[1] for r in rows], y=[r[0] for r in rows], orientation="h",
                marker_color=[GOOD if r[1] >= 0 else BAD for r in rows],
                marker_line_width=0, text=[f"{r[1]:+.1f}" for r in rows],
                textposition="auto"))
            lfig.add_vline(x=0, line=dict(color="#8b949e", width=1, dash="dot"))
            lfig.update_xaxes(title="Wins above / below Pythagorean expectation")
            _style(lfig, max(300, 22 * len(rows)))
            st.plotly_chart(lfig, width="stretch", key="hero_luck")

    with col[2]:
        st.markdown("<div class='lab-hdr'>Power rankings</div>", unsafe_allow_html=True)
        if D["leaders"]:
            df = pd.DataFrame([{
                "Rank": r["Rank"], "Team": r["Team"],
                "Rec": f"{r['W']}-{r['L']}", "Power": r["Power"],
                "Form": r["Form"],
                # relative deep-link → Team Dashboard preselected on this team
                "Open": (f"Team_Dashboard?team={r['tid']}"
                         if r.get("tid") is not None else None),
            } for r in D["leaders"]])
            st.dataframe(
                df, hide_index=True, width="stretch", key="lb_power",
                column_config={
                    "Power": st.column_config.ProgressColumn(
                        "Power", format="%.0f", min_value=0, max_value=100),
                    "Form": st.column_config.LineChartColumn(
                        "Margin trend", y_min=-30, y_max=30),
                    "Open": st.column_config.LinkColumn(
                        "", display_text="↗", width="small"),
                })

        st.markdown("<div class='lab-hdr'>Scoring leaders</div>", unsafe_allow_html=True)
        if D["scorer_rows"]:
            sdf = pd.DataFrame(D["scorer_rows"])
            # deep-link each scorer to their Player Lab profile, then hide the id
            if "pid" in sdf.columns:
                sdf["Open"] = sdf["pid"].apply(
                    lambda p: f"Players?player={int(p)}" if pd.notna(p) else None)
                sdf = sdf.drop(columns=["pid"])
            # OVERALL is an event-derived rating — drop the OVR column for Free.
            _scfg = {"PPG": st.column_config.NumberColumn("PPG", format="%.1f"),
                     "Trend": st.column_config.LineChartColumn("PTS by game"),
                     "Open": st.column_config.LinkColumn("", display_text="↗",
                                                         width="small")}
            if _paid:
                _scfg["OVR"] = st.column_config.ProgressColumn(
                    "OVR", format="%.0f", min_value=0, max_value=100)
            else:
                sdf = sdf.drop(columns=["OVR"], errors="ignore")
            st.dataframe(sdf, hide_index=True, width="stretch", key="lb_scorers",
                         column_config=_scfg)

# ══════════════════════════════════════════════════════════════════════════════
#  SEARCH + NOTABLES
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def _search_notables(gender):
    import helpers.player_ratings as _PR
    table = _PR.player_stat_table(gender=gender, min_games=1)
    players = [{"name": r["name"], "team": r["team"], "ppg": r.get("PPG"),
                "ovr": r.get("OVERALL")} for r in table.values()]
    return {"players": players, "notables": TRD.league_notables(table=table)}


if D["scored"]:
    EX = _search_notables(_gender)
    with st.expander("🔎  Search players & teams"):
        q = st.text_input("Search by name", placeholder="player or team…",
                          label_visibility="collapsed").strip().lower()
        if q:
            pm = sorted([p for p in EX["players"] if q in (p["name"] or "").lower()],
                        key=lambda p: -(p["ovr"] if p["ovr"] is not None else 0))[:8]
            tm = sorted([s for s in D["scored"].values()
                         if q in (s["name"] or "").lower()],
                        key=lambda s: s["Rank"])[:8]
            sc1, sc2 = st.columns(2)
            with sc1:
                st.caption("Players")
                if pm:
                    _pdf = pd.DataFrame([
                        {"Player": p["name"], "Team": p["team"],
                         "PPG": round(p["ppg"], 1) if p["ppg"] is not None else None,
                         "OVR": round(p["ovr"]) if p["ovr"] is not None else None}
                        for p in pm])
                    if not _paid:   # OVERALL rating is Paid-only
                        _pdf = _pdf.drop(columns=["OVR"], errors="ignore")
                    st.dataframe(_pdf, hide_index=True, width="stretch")
                else:
                    st.caption("No players match.")
            with sc2:
                st.caption("Teams")
                if tm:
                    st.dataframe(pd.DataFrame([
                        {"Rank": s["Rank"], "Team": s["name"],
                         "Rec": f"{s['W']}-{s['L']}", "Power": round(s["Power"])}
                        for s in tm]), hide_index=True, width="stretch")
                else:
                    st.caption("No teams match.")

    nb = EX["notables"]
    if any(nb.values()):
        st.markdown("<div class='lab-hdr'>Notables</div>", unsafe_allow_html=True)
        nc = st.columns(3)
        with nc[0]:
            st.caption("Hot hands — double-figure scoring streaks")
            for cur, longest, label in nb["streaks"]:
                if cur or longest:
                    st.markdown(f"**{cur}** in a row · {label} "
                                f"<span style='color:#8b949e'>(long {longest})</span>",
                                unsafe_allow_html=True)
        with nc[1]:
            st.caption("Most double-doubles")
            for cnt, label in nb["double_doubles"]:
                if cnt:
                    st.markdown(f"**{cnt}** · {label}")
        with nc[2]:
            st.caption("Top scoring games")
            for pts, label, date, opp in nb["highs"]:
                if pts:
                    st.markdown(f"**{pts}** · {label} "
                                f"<span style='color:#8b949e'>vs {opp[:14]}</span>",
                                unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<div class='lab-hdr'>Jump in</div>", unsafe_allow_html=True)


def _links(items):
    cols = st.columns(len(items))
    for c, (path, label, icon) in zip(cols, items):
        with c:
            try:
                st.page_link(path, label=label, icon=icon or None)
            except Exception:
                st.markdown(f"{icon} {label}".strip())


st.caption("Build")
_links([("pages/1_Input_Hub.py", "Input Hub", ""),
        ("pages/2_Game_Tracker.py", "Game Tracker", ""),
        ("pages/3_Event_Editor.py", "Event Editor", ""),
        ("pages/4_Schedule.py", "Schedule", ""),
        ("pages/11_Setup.py", "Setup", "")])
st.caption("Analyze")
_links([("pages/5_Rankings.py", "Rankings", ""),
        ("pages/6_Team_Dashboard.py", "Team Dashboard", ""),
        ("pages/7_Players.py", "Players", ""),
        ("pages/10_Data_Explorer.py", "Data Explorer", "")])
st.caption("Plan & scout")
_links([("pages/9_War_Room.py", "War Room", ""),
        ("pages/8_Officials.py", "Officials", ""),
        ("pages/12_Settings.py", "Settings", "")])
