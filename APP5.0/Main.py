"""
main.py — Executive Dashboard + multipage entry point for APP5.0.

The landing page is a best-in-class BI dashboard: a top KPI scorecard row, an
asymmetric command-center grid (gauges left, hero charts center, ranked
leaderboards with sparklines right), the Game of the Season, and quick links into
every tool. Data lives in a local SQLite database (database/analytics.db),
initialised on startup by database/db.py. Display-only; all math is in the
Streamlit-free engines.
"""
import sys
import streamlit as st
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Page config (respects wide_mode setting) ───────────────────────────────────
_layout = "wide"
try:
    from database.db import query as _q
    _rows = _q("SELECT value FROM app_settings WHERE key='wide_mode'")
    if _rows and _rows[0]["value"] == "0":
        _layout = "centered"
except Exception:
    pass

st.set_page_config(page_title="Analytics Hub", page_icon="", layout=_layout,
                   initial_sidebar_state="expanded")

# ── Global CSS + theme ─────────────────────────────────────────────────────────
_css_path = Path(__file__).resolve().parent / "assets" / "style.css"
if _css_path.exists():
    st.markdown(f"<style>{_css_path.read_text(encoding='utf-8')}</style>",
                unsafe_allow_html=True)
try:
    from helpers.settings_utils import get_all_settings, apply_theme_css
    apply_theme_css(get_all_settings())
except Exception:
    pass

import pandas as pd
import plotly.graph_objects as go
from helpers.ui import (style_fig as _style, gauge as _gauge, GOOD, BAD)
from helpers.settings_utils import get_setting
import helpers.trends as TRD

ACCENT = get_setting("accent_color", "#f0a500")
AWAY = "#e74c3c"


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD DATA  (one cached pass; resilient to an empty DB)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _dashboard(gender):
    """Everything the executive dashboard renders, in one cached bundle."""
    d = {"teams": 0, "tracked": 0, "players": 0, "games_played": 0,
         "scored": {}, "form": {}, "top": None, "hot": None,
         "scorer": None, "leaders": [], "scorer_rows": [], "game": None,
         "avg_ortg": None, "top_trk": None, "player_avg_ppg": 0}
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

        form = LA.team_form_stats(gender=gender)
        d["form"] = form
        hot_t = max(form, key=lambda t: (form[t]["Momentum"]
                    if form[t]["Momentum"] is not None else -1), default=None)
        if hot_t:
            d["hot"] = (scored.get(hot_t, {}).get("name", "—"),
                        form[hot_t]["Momentum"], "".join(form[hot_t]["form"][-5:]))

        # leaderboard rows (top 12 by power) with recent margin sparkline
        ptr = LA.per_team_results(gender)
        d["leaders"] = [{
            "Rank": s["Rank"], "Team": s["name"], "W": s["W"], "L": s["L"],
            "Power": s["Power"], "Net": s["AdjNet"],
            "Form": [g["margin"] for g in ptr.get(id_of.get(id(s)), [])[-7:]],
        } for s in order[:12]]

        # tracked efficiency for the top team's gauges
        tracked = TR.tracked_ratings(gender=gender)
        if tracked:
            d["avg_ortg"] = sum(t["ORtg"] for t in tracked.values()) / len(tracked)
            d["top_trk"] = tracked.get(top_tid)

        # player scoring leaderboard with per-game PTS sparkline
        table = PR.player_stat_table(gender=gender, min_games=1)
        d["players"] = len(table)
        if table:
            gbox = S.player_game_boxes()
            gdates = {r["id"]: r["date"] for r in query(
                "SELECT id, date FROM games WHERE tracked=1")}
            top_sc = sorted(table.values(), key=lambda r: -(r.get("PPG") or 0))[:10]
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
                             "Trend": series})
            d["scorer_rows"] = rows

        # game of the season (highest GEI)
        best = None
        for gid in [r["id"] for r in query("SELECT id FROM games WHERE tracked=1")]:
            g = query("""SELECT g.team1_id t1, g.team2_id t2, t1.name n1, t2.name n2,
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
            gei = WP.game_excitement_index(WP.wp_curve(mc))
            if best is None or gei > best[0]:
                best = (gei, g["n1"], g["n2"], h, a)
        d["game"] = best
    except Exception:
        pass
    return d


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER + LEAGUE TOGGLE
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    "<div class='lab-hero'><h1>Analytics Hub — Executive Dashboard</h1>"
    "<p>Track it · analyze it · predict it · scout it. The whole program at a glance.</p>"
    "</div>", unsafe_allow_html=True)

_gender = "F"
try:
    _gender = {"Girls": "F", "Boys": "M"}[
        st.radio("League", ["Girls", "Boys"], horizontal=True,
                 label_visibility="collapsed")]
except Exception:
    pass

D = _dashboard(_gender)

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

    # ── game of the season banner ──────────────────────────────────────────────
    if D["game"]:
        gei, n1, n2, h, a = D["game"]
        from helpers.win_probability import excitement_label
        st.markdown(
            f"<div class='glass-tile'><b>Game of the season</b> — "
            f"{n2} {a} @ {n1} {h} · "
            f"<span style='color:var(--accent)'>GEI {gei:.1f} · {excitement_label(gei)}</span>"
            f"</div>", unsafe_allow_html=True)

    # ── command-center grid (gauges | hero charts | leaderboards) ──────────────
    col = st.columns((2, 4.4, 3), gap="medium")

    with col[0]:
        st.markdown("<div class='lab-hdr'>Top team pulse</div>", unsafe_allow_html=True)
        if D["top"]:
            st.plotly_chart(_gauge(D["top"]["Power"], "Power", 0, 100, ref=50,
                                   accent=ACCENT, height=170),
                            width="stretch", key="g_power")
            trk = D.get("top_trk")
            if trk:
                st.plotly_chart(_gauge(trk["ORtg"], "Off. rating", 60, 120,
                                       ref=D.get("avg_ortg"), accent=GOOD,
                                       height=170), width="stretch", key="g_ortg")
                st.plotly_chart(_gauge(trk["DRtg"], "Def. rating (low=good)", 60, 120,
                                       ref=D.get("avg_ortg"), accent=AWAY,
                                       height=170), width="stretch", key="g_drtg")
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
            df = pd.DataFrame([{"Rank": r["Rank"], "Team": r["Team"],
                                "Rec": f"{r['W']}-{r['L']}", "Power": r["Power"],
                                "Form": r["Form"]} for r in D["leaders"]])
            st.dataframe(
                df, hide_index=True, width="stretch", key="lb_power",
                column_config={
                    "Power": st.column_config.ProgressColumn(
                        "Power", format="%.0f", min_value=0, max_value=100),
                    "Form": st.column_config.LineChartColumn(
                        "Margin trend", y_min=-30, y_max=30),
                })

        st.markdown("<div class='lab-hdr'>Scoring leaders</div>", unsafe_allow_html=True)
        if D["scorer_rows"]:
            sdf = pd.DataFrame(D["scorer_rows"])
            st.dataframe(
                sdf, hide_index=True, width="stretch", key="lb_scorers",
                column_config={
                    "PPG": st.column_config.NumberColumn("PPG", format="%.1f"),
                    "OVR": st.column_config.ProgressColumn(
                        "OVR", format="%.0f", min_value=0, max_value=100),
                    "Trend": st.column_config.LineChartColumn("PTS by game"),
                })

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
                        key=lambda p: -(p["ovr"] or 0))[:8]
            tm = sorted([s for s in D["scored"].values()
                         if q in (s["name"] or "").lower()],
                        key=lambda s: s["Rank"])[:8]
            sc1, sc2 = st.columns(2)
            with sc1:
                st.caption("Players")
                if pm:
                    st.dataframe(pd.DataFrame([
                        {"Player": p["name"], "Team": p["team"],
                         "PPG": round(p["ppg"], 1) if p["ppg"] else None,
                         "OVR": round(p["ovr"]) if p["ovr"] else None} for p in pm]),
                        hide_index=True, width="stretch")
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

try:
    from database.db import get_db_path as _gp
    _p = _gp()
    st.caption(f"Database ready ({_p.name})" if _p.exists()
               else "Database file not found — run the app once to initialise it.")
except Exception as _e:
    st.warning(f"Database error — {_e}")
