"""
3_Rankings.py — Team rankings, deep dives, charts and a matchup predictor.

Four tabs:
  • Overview          — the source of truth. Results-only "Score" power ratings
                        for every team, plus a per-team deep dive (record, record
                        vs top 10, vs class, schedule).
  • Tracked           — possession-based ratings over tracked games only, with a
                        per-team tracked schedule that opens the full box score.
  • Team Charts       — how teams score / win, quarter breakdown, who can shoot,
                        shot volume — built from tracked-game events.
  • Matchup Predictor — Vegas-style spread, projected score, total and win
                        probability between any two teams, from the ratings.

All rating math lives in helpers/team_ratings.py; this page is display + controls.
"""
import sys
import math
from math import erf, sqrt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import defaultdict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.settings_utils import get_setting
from helpers.box_score import render_box_score
from helpers.ui import (page_chrome, rgb as _rgb, style_fig as _style,
                        q_label as _q_label, AWAY, CARD_BG, GRID)
from helpers.glossary import render_glossary
import helpers.team_ratings as TR
import helpers.stats as S
import helpers.league_analytics as LA

_cfg, ACCENT = page_chrome()

# futuristic-lab palette (mirrors the Team Analytics advanced layer)
GOOD = "#3fb950"
BAD = "#e74c3c"
BLUE = "#58a6ff"
PURPLE = "#bc8cff"
CYBER = "#00e5ff"
GREY = "#8b949e"
PINK = "#ff5db1"
GOLD = "#f0a500"
TIER_PALETTE = ["#00e5ff", "#3fb950", "#58a6ff", "#f0a500", "#8b949e"]


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _norm_cdf(x, mu=0.0, sd=1.0):
    return 0.5 * (1 + erf((x - mu) / (sd * sqrt(2))))


def _team_results(team_id):
    """Completed games for a team, oldest first. team1 = home, team2 = away."""
    rows = query(
        """SELECT g.id, g.date, g.location, g.tracked,
                  g.team1_id, g.team2_id, g.home_score, g.away_score
           FROM games g
           WHERE (g.team1_id=? OR g.team2_id=?)
             AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
           ORDER BY g.date, g.id""",
        (team_id, team_id))
    out = []
    for g in rows:
        if g["team1_id"] == team_id:
            pf, pa, opp, site = g["home_score"], g["away_score"], g["team2_id"], "vs"
        else:
            pf, pa, opp, site = g["away_score"], g["home_score"], g["team1_id"], "@"
        out.append({"game_id": g["id"], "date": g["date"], "opp": opp,
                    "site": site, "pf": pf, "pa": pa, "won": pf > pa,
                    "tracked": g["tracked"]})
    return out


def _team_streak(results):
    """Current W/L streak string (e.g. 'W3') from oldest-first results."""
    if not results:
        return ""
    last = results[-1]["won"]
    n = 0
    for g in reversed(results):
        if g["won"] == last:
            n += 1
        else:
            break
    return ("W" if last else "L") + str(n)


def _vs_topn(results, topn_set):
    """(wins, losses) against teams in topn_set."""
    w = sum(1 for g in results if g["won"] and g["opp"] in topn_set)
    l = sum(1 for g in results if not g["won"] and g["opp"] in topn_set)
    return w, l


def _filter_rows(rows, key):
    """Class multiselect + min-games slider. Returns the filtered rows."""
    classes = sorted({r["class"] for r in rows},
                     key=lambda c: TR._CLASS_RANK.get(c, 99))
    max_gp = max((r["GP"] for r in rows), default=1)
    c1, c2 = st.columns([2, 1])
    picked = c1.multiselect("Class", classes, default=classes,
                            key=f"{key}_cls")
    if max_gp > 1:
        min_gp = c2.slider("Min games played", 1, int(max_gp), 1,
                           key=f"{key}_gp")
    else:
        min_gp = 1
    return [r for r in rows
            if r["class"] in picked and r["GP"] >= min_gp]


# ── futuristic-lab UI helpers ─────────────────────────────────────────────────

def _lab_hdr(text):
    """Neon section header (the cyber look from Team Analytics)."""
    st.markdown(f"<div class='lab-hdr'>{text}</div>", unsafe_allow_html=True)


def _tier(power):
    """Power 0-100 → (tier name, color). 50 = league average on the z-scale."""
    if power is None:
        return "—", GREY
    if power >= 68:
        return "S · ELITE", "#00e5ff"
    if power >= 60:
        return "A · CONTENDER", "#3fb950"
    if power >= 52:
        return "B · SOLID", "#58a6ff"
    if power >= 44:
        return "C · MIDDLING", "#f0a500"
    return "D · REBUILDING", "#e74c3c"


def _pctile_color(pct):
    """Percentile (0-100) → quartile color."""
    if pct is None:
        return GREY
    if pct >= 75:
        return GOOD
    if pct >= 50:
        return BLUE
    if pct >= 25:
        return GOLD
    return BAD


def _pctile_bar(label, val_txt, pct):
    """One HTML percentile bar row (reuses the global .pctile-* classes)."""
    clr = _pctile_color(pct)
    width = 0 if pct is None else max(2, pct)
    rank_txt = "—" if pct is None else f"{pct:.0f}th"
    return (
        f"<div class='pctile-row'><div class='pctile-label-row'>"
        f"<span class='pctile-stat'>{label}</span>"
        f"<span><span class='pctile-val'>{val_txt}</span> "
        f"<span class='pctile-rank' style='color:{clr}'>{rank_txt}</span></span>"
        f"</div><div class='pctile-track'>"
        f"<div class='pctile-fill' style='width:{width}%;background:{clr}'></div>"
        f"</div></div>")


def _gauge(value, vmin, vmax, label, suffix="", good_high=True, ref=None,
           height=200):
    """Futuristic gauge vs a league [vmin,vmax] range, league avg (`ref`) drawn
    as a cyan threshold; red/amber/green zones key off `good_high`."""
    span = (vmax - vmin) or 1
    lo, hi = vmin + span / 3, vmin + 2 * span / 3
    if good_high:
        zones = [(vmin, lo, "rgba(231,76,60,.20)"), (lo, hi, "rgba(240,165,0,.16)"),
                 (hi, vmax, "rgba(63,185,80,.22)")]
    else:
        zones = [(vmin, lo, "rgba(63,185,80,.22)"), (lo, hi, "rgba(240,165,0,.16)"),
                 (hi, vmax, "rgba(231,76,60,.20)")]
    mode = "gauge+number+delta" if ref is not None else "gauge+number"
    ind = dict(
        mode=mode, value=value,
        number={"suffix": suffix, "font": {"size": 26, "color": "#f0f6fc"}},
        gauge={
            "axis": {"range": [vmin, vmax], "tickwidth": 1,
                     "tickcolor": "#30363d", "tickfont": {"size": 9}},
            "bar": {"color": ACCENT, "thickness": 0.3},
            "bgcolor": "rgba(0,0,0,0)", "borderwidth": 0,
            "steps": [{"range": [a, b], "color": c} for a, b, c in zones]},
        title={"text": label, "font": {"size": 12, "color": "#8b949e"}})
    if ref is not None:
        ind["delta"] = {"reference": ref, "increasing": {"color": GOOD},
                        "decreasing": {"color": BAD}, "font": {"size": 12}}
        ind["gauge"]["threshold"] = {"line": {"color": CYBER, "width": 3},
                                     "thickness": 0.85, "value": ref}
    fig = go.Figure(go.Indicator(**ind))
    fig.update_layout(template="plotly_dark", height=height,
                      paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=22, r=22, t=44, b=8),
                      font=dict(color="#c9d1d9"))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE HEADER + GENDER
# ══════════════════════════════════════════════════════════════════════════════

st.title("Rankings")

gender = st.radio(
    "League", ["F", "M"],
    format_func=lambda g: "Girls" if g == "F" else "Boys",
    horizontal=True)

@st.cache_data(ttl=600, show_spinner=False)
def _score_ratings(g):
    return TR.score_ratings(gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _tracked_ratings(g):
    return TR.tracked_ratings(gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _form_stats(g):
    return LA.team_form_stats(gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _tracked_pack(g, _tracked):
    return LA.team_tracked_pack(gender=g, tracked=_tracked)


@st.cache_data(ttl=600, show_spinner=False)
def _win_net(g, _scored):
    return LA.win_network(gender=g, scored=_scored)


scored = _score_ratings(gender)
tracked = _tracked_ratings(gender)
form_stats = _form_stats(gender)

if not scored:
    st.info("No finished games for this league yet. Enter results in the Input Hub "
            "and they'll rank here.")
    st.stop()

name_of = {tid: r["name"] for tid, r in scored.items()}
class_of = {tid: r["class"] for tid, r in scored.items()}
rank_of = {tid: r["Rank"] for tid, r in scored.items()}
TOP5 = {tid for tid, r in scored.items() if r["Rank"] <= 5}
TOP10 = {tid for tid, r in scored.items() if r["Rank"] <= 10}
TOP25 = {tid for tid, r in scored.items() if r["Rank"] <= 25}

# tracked advanced bundle (one cached box pass) — shared by League Lab + Stat Lab
pack = _tracked_pack(gender, tracked)

tab_over, tab_track, tab_chart, tab_lab, tab_stat, tab_pred, tab_gloss = st.tabs(
    ["🏆 Overview", "🎯 Tracked", "📊 Team Charts", "🚀 League Lab",
     "🔬 Stat Lab", "🆚 Matchup Predictor", "📖 Glossary"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — OVERVIEW  (source of truth: scored ratings)
# ══════════════════════════════════════════════════════════════════════════════
with tab_over:
    all_rows = list(scored.values())

    # ── futuristic league identity band ──────────────────────────────────────
    _n_games = int(sum(r["GP"] for r in all_rows) // 2)
    _trk_games = sum(1 for _ in TR._finished_games(gender=gender,
                                                   tracked_only=True))
    _avg_ppg = sum(r["PPG"] for r in all_rows) / len(all_rows)
    _top = min(all_rows, key=lambda r: r["Rank"])
    _best_off = max(all_rows, key=lambda r: r["PPG"])
    _best_def = min(all_rows, key=lambda r: r["oPPG"])

    def _form_leader(metric, hi=True, need=None):
        cand = [(t, form_stats[t]) for t in form_stats
                if form_stats[t].get(metric) is not None
                and (need is None or need(form_stats[t]))]
        if not cand:
            return None, None
        return (max if hi else min)(cand, key=lambda c: c[1][metric])

    _hot_t, _hot = _form_leader("streak_len", need=lambda r: r["streak_type"] == "W")
    _league_name = "Girls" if gender == "F" else "Boys"
    _chips = "".join(
        f"<span class='stat-chip'>{lbl} <b>{val}</b></span>"
        for lbl, val in [
            ("Teams", len(all_rows)), ("Games", _n_games),
            ("Tracked", _trk_games), ("Avg PPG", f"{_avg_ppg:.1f}"),
            ("#1", _top["name"]),
        ])
    st.markdown(
        f"<div class='lab-hero'>"
        f"<div class='lab-hero-name' style='color:{ACCENT}'>{_league_name} "
        f"Basketball · Command Center</div>"
        f"<div class='lab-hero-sub'>Opponent-adjusted power, résumé and "
        f"possession analytics across the whole league — results power every "
        f"team, tracked games add the deep layer.</div>"
        f"<div class='lab-hero-chips'>{_chips}</div></div>",
        unsafe_allow_html=True)

    st.caption(
        "**Source of truth.** Results-only power ratings for every team — built "
        "from final scores and who-beat-who, opponent-adjusted with a class "
        "bridge. **Power** is 0-100 (50 = league average, +10 per std dev); "
        "**Rating** is points vs an average team on a neutral floor.")

    # ── League pulse ─────────────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>League pulse</div>",
                unsafe_allow_html=True)
    lp = st.columns(5)
    lp[0].metric("Teams", len(all_rows))
    lp[1].metric("Games", int(sum(r["GP"] for r in all_rows) // 2))
    lp[2].metric("Avg PPG", f"{sum(r['PPG'] for r in all_rows)/len(all_rows):.1f}")
    lp[3].metric("Avg PA/G", f"{sum(r['oPPG'] for r in all_rows)/len(all_rows):.1f}")
    tracked_ct = sum(1 for g in TR._finished_games(gender=gender,
                                                   tracked_only=True))
    lp[4].metric("Tracked games", tracked_ct)

    # ── Recent results ───────────────────────────────────────────────────────
    recent = query(
        """SELECT g.date, g.home_score, g.away_score, g.tracked,
                  t1.name AS t1, t2.name AS t2
           FROM games g
           JOIN teams t1 ON t1.id = g.team1_id
           JOIN teams t2 ON t2.id = g.team2_id
           WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL
             AND t1.gender = ?
           ORDER BY g.date DESC, g.id DESC LIMIT 8""", (gender,))
    if recent:
        st.markdown("<div class='section-hdr'>Recent results</div>",
                    unsafe_allow_html=True)
        rc = st.columns(4)
        for i, g in enumerate(recent):
            t1w = g["home_score"] > g["away_score"]
            s1 = "score-winner" if t1w else "score-loser"
            s2 = "score-winner" if not t1w else "score-loser"
            rc[i % 4].markdown(
                f"<div class='score-card'>"
                f"<div class='score-card-date'>{g['date']}"
                f"{' · ●' if g['tracked'] else ''}</div>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<span class='score-card-team'>{g['t1']}</span>"
                f"<span class='score-card-pts {s1}'>{g['home_score']}</span></div>"
                f"<div style='display:flex;justify-content:space-between'>"
                f"<span class='score-card-team'>{g['t2']}</span>"
                f"<span class='score-card-pts {s2}'>{g['away_score']}</span></div>"
                f"</div>", unsafe_allow_html=True)

    # ── Team leaders ─────────────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Team leaders</div>",
                unsafe_allow_html=True)

    def _leader_card(col, label, key, hi=True, fmt="{:.1f}"):
        best = max(all_rows, key=lambda r: r[key]) if hi else \
            min(all_rows, key=lambda r: r[key])
        col.markdown(
            f"<div class='dash-card'><div class='dash-card-title'>{label}</div>"
            f"<div class='dash-card-value'>{fmt.format(best[key])}</div>"
            f"<div class='dash-card-sub'>{best['name']}</div>"
            f"<div class='dash-card-meta'>{best['class']} · "
            f"{best['W']}-{best['L']}</div></div>", unsafe_allow_html=True)

    tl = st.columns(5)
    _leader_card(tl[0], "Top rating", "Rating")
    _leader_card(tl[1], "Best offense (PPG)", "PPG")
    _leader_card(tl[2], "Best defense (PA/G)", "oPPG", hi=False)
    _leader_card(tl[3], "Point margin", "MOV", fmt="{:+.1f}")
    _leader_card(tl[4], "Strength of record", "SOR", fmt="{:.2f}")

    # ── signature (made-up, league-relative) metric leaders ──────────────────
    _lab_hdr("Signature metrics")
    st.caption(
        "New composite indices, all 0-100 with 50 = league average (+10 per std "
        "dev). **Dominance** blends margin, win% and blowout rate. "
        "**Consistency** rewards low game-to-game margin volatility. **Clutch** "
        "blends record and margin in games decided by ≤5. **Momentum** is recent "
        "(last-5) vs season form. **Luck** is wins above Pythagorean expectation.")

    def _sig_tile(col, title, metric, fmt="{:.0f}", hi=True, need=None,
                  color=CYBER, suffix=""):
        t, r = _form_leader(metric, hi=hi, need=need)
        if t is None:
            col.markdown(
                f"<div class='glass-tile'><div class='glass-label'>{title}</div>"
                f"<div class='glass-value' style='color:{GREY}'>—</div>"
                f"<div class='glass-sub'>no qualifier</div></div>",
                unsafe_allow_html=True)
            return
        col.markdown(
            f"<div class='glass-tile'><div class='glass-label'>{title}</div>"
            f"<div class='glass-value' style='color:{color}'>"
            f"{fmt.format(r[metric])}{suffix}</div>"
            f"<div class='glass-sub'>{name_of[t]} · {class_of[t]}</div></div>",
            unsafe_allow_html=True)

    sg = st.columns(5)
    _sig_tile(sg[0], "Most dominant", "Dominance", color=CYBER)
    _sig_tile(sg[1], "Most consistent", "Consistency", color=GOOD)
    _sig_tile(sg[2], "Clutch king", "Clutch", color=PURPLE)
    _sig_tile(sg[3], "Hottest", "streak_len", fmt="W{:.0f}",
              need=lambda r: r["streak_type"] == "W", color=GOLD)
    _sig_tile(sg[4], "Luckiest", "Luck_wins", fmt="{:+.1f}", suffix=" W", color=BLUE)

    with st.expander("📋 Advanced standings — every team, every composite"):
        adv = []
        for t, r in sorted(scored.items(), key=lambda kv: kv[1]["Rank"]):
            f = form_stats.get(t, {})
            adv.append({
                "Rank": r["Rank"], "Team": r["name"], "Class": r["class"],
                "W-L": f"{r['W']}-{r['L']}", "Power": r["Power"],
                "Dominance": f.get("Dominance"), "Consistency": f.get("Consistency"),
                "Clutch": f.get("Clutch"), "Momentum": f.get("Momentum"),
                "MOV": round(f.get("MOV", 0), 1),
                "Volatility": round(f.get("Volatility", 0), 1),
                "Pyth W": round(f.get("Pyth_W", 0), 1),
                "Luck (W)": round(f.get("Luck_wins", 0), 2),
            })
        adv_df = pd.DataFrame(adv)
        st.dataframe(
            adv_df, hide_index=True, width="stretch",
            height=min(640, 60 + 32 * len(adv_df)),
            column_config={
                k: st.column_config.ProgressColumn(k, format="%.0f", min_value=0,
                                                   max_value=100)
                for k in ("Power", "Dominance", "Consistency", "Clutch",
                          "Momentum")})
        st.download_button("⬇ Advanced standings (CSV)", adv_df.to_csv(index=False),
                           file_name=f"advanced_standings_{gender}.csv",
                           mime="text/csv", key="dl_adv")

    st.markdown("<div class='section-hdr'>Rankings table</div>",
                unsafe_allow_html=True)
    rows = _filter_rows(sorted(scored.values(), key=lambda r: r["Rank"]), "ov")
    if not rows:
        st.info("No teams match the current Class / games filter.")
    else:
        df = pd.DataFrame(rows)[[
            "Rank", "name", "class", "W", "L", "Power", "Rating",
            "PPG", "oPPG", "MOV", "xPPG", "xoPPG", "SOS", "SOR"]].rename(
            columns={"name": "Team", "class": "Class"})
        st.dataframe(
            df, hide_index=True, width="stretch",
            height=min(720, 60 + 35 * len(df)),
            column_config={
                "Power": st.column_config.ProgressColumn(
                    "Power", format="%.1f", min_value=0, max_value=100),
                "Rating": st.column_config.NumberColumn("Rating", format="%.2f"),
                "SOS": st.column_config.NumberColumn("SOS", format="%.2f"),
                "SOR": st.column_config.NumberColumn("SOR", format="%.2f"),
            })
        st.download_button("⬇ Rankings (CSV)", df.to_csv(index=False),
                           file_name=f"rankings_{gender}.csv", mime="text/csv",
                           key="dl_scored")

    # ── Team deep dive ───────────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Team deep dive</div>",
                unsafe_allow_html=True)

    order = sorted(scored.keys(), key=lambda t: scored[t]["Rank"])
    default_team = get_setting("default_team", "")
    default_idx = next((i for i, t in enumerate(order)
                        if name_of[t] == default_team), 0)
    pick = st.selectbox(
        "Team", order, index=default_idx,
        format_func=lambda t: f"#{scored[t]['Rank']}  {name_of[t]}  ({class_of[t]})",
        key="ov_team")
    r = scored[pick]

    results = _team_results(pick)
    # record splits
    t5_w, t5_l = _vs_topn(results, TOP5)
    t10_w, t10_l = _vs_topn(results, TOP10)
    t25_w, t25_l = _vs_topn(results, TOP25)
    streak = _team_streak(results)
    by_class = defaultdict(lambda: [0, 0])
    for g in results:
        oc = class_of.get(g["opp"], "N/A")
        by_class[oc][0 if g["won"] else 1] += 1

    m = st.columns(5)
    m[0].metric("Power", r["Power"])
    m[1].metric("Rating", r["Rating"])
    m[2].metric("Record", f"{r['W']}-{r['L']}", streak or None)
    m[3].metric("Margin / game", f"{r['MOV']:+.1f}")
    m[4].metric("SOS / SOR", f"{r['SOS']:.1f} / {r['SOR']:.1f}")

    # both rankings in one place: everything (this tab) + tracked (where possible)
    rk = TR.team_rank(pick, scored=scored, tracked=tracked)
    _trk = rk["tracked"]
    st.caption(
        f"**Everything ranking** #{r['Rank']} of {len(scored)}  ·  "
        + (f"**Tracked ranking** #{_trk['rank']} of {_trk['of']} "
           f"(Power {_trk['power']}, Net {_trk['netrtg']:+.1f})"
           if _trk else "**Tracked ranking** — not tracked yet"))

    mt = st.columns(3)
    mt[0].metric("vs Top 5", f"{t5_w}-{t5_l}")
    mt[1].metric("vs Top 10", f"{t10_w}-{t10_l}")
    mt[2].metric("vs Top 25", f"{t25_w}-{t25_l}")

    m2 = st.columns(4)
    m2[0].metric("PPG", r["PPG"])
    m2[1].metric("Opp PPG", r["oPPG"])
    m2[2].metric("Adj O (xPPG)", r["xPPG"])
    m2[3].metric("Adj D (xoPPG)", r["xoPPG"])

    # ── advanced profile (results-only composites + form) ────────────────────
    f = form_stats.get(pick, {})

    def _mv(x, fmt="{:.0f}"):
        return "—" if x is None else fmt.format(x)

    _lab_hdr("Advanced profile")
    if f.get("form"):
        pills = "".join(
            f"<span class='form-pill {'w' if x == 'W' else 'l'}"
            f"{' now' if i == len(f['form']) - 1 else ''}'>{x}</span>"
            for i, x in enumerate(f["form"]))
        st.markdown(f"<div class='form-strip'>{pills}</div>"
                    f"<div style='font-size:11px;color:#8b949e;margin:4px 0 10px'>"
                    f"last {len(f['form'])} · most recent outlined</div>",
                    unsafe_allow_html=True)

    am = st.columns(5)
    am[0].metric("Dominance", _mv(f.get("Dominance")))
    am[1].metric("Consistency", _mv(f.get("Consistency")))
    am[2].metric("Clutch", _mv(f.get("Clutch")))
    am[3].metric("Momentum", _mv(f.get("Momentum")))
    am[4].metric("Volatility", _mv(f.get("Volatility"), "{:.1f}"))

    pm = st.columns(5)
    pm[0].metric("Pythagorean W-L",
                 f"{f.get('Pyth_W', 0):.1f}-{f.get('Pyth_L', 0):.1f}")
    pm[1].metric("Luck (W vs exp)", _mv(f.get("Luck_wins"), "{:+.1f}"))
    pm[2].metric("Ceiling", _mv(f.get("ceiling"), "{:+d}"))
    pm[3].metric("Floor", _mv(f.get("floor"), "{:+d}"))
    pm[4].metric("Close (≤5)",
                 f"{f.get('close_w', 0)}-{f.get('close_l', 0)}")

    # league percentile profile (results-only, vs the whole field)
    st.markdown("**League percentile profile**")
    pow_pool = [s["Power"] for s in scored.values()]
    mov_pool = [s["MOV"] for s in scored.values()]
    off_pool = [s["PPG"] for s in scored.values()]
    def_pool = [s["oPPG"] for s in scored.values()]
    sos_pool = [s["SOS"] for s in scored.values()]
    sor_pool = [s["SOR"] for s in scored.values()]
    dom_pool = [fm.get("Dominance") for fm in form_stats.values()]
    con_pool = [fm.get("Consistency") for fm in form_stats.values()]
    prof = [
        ("Power", r["Power"], pow_pool, True, "{:.1f}"),
        ("Margin / game", r["MOV"], mov_pool, True, "{:+.1f}"),
        ("Offense (PPG)", r["PPG"], off_pool, True, "{:.1f}"),
        ("Defense (PA/G)", r["oPPG"], def_pool, False, "{:.1f}"),
        ("Strength of schedule", r["SOS"], sos_pool, True, "{:.2f}"),
        ("Strength of record", r["SOR"], sor_pool, True, "{:.2f}"),
        ("Dominance", f.get("Dominance"), dom_pool, True, "{:.0f}"),
        ("Consistency", f.get("Consistency"), con_pool, True, "{:.0f}"),
    ]
    pc1, pc2 = st.columns(2)
    for i, (lbl, val, pool, hib, fmt) in enumerate(prof):
        pct = LA.percentile(val, pool, higher_better=hib)
        txt = "—" if val is None else fmt.format(val)
        (pc1 if i % 2 == 0 else pc2).markdown(
            _pctile_bar(lbl, txt, pct), unsafe_allow_html=True)

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Schedule & results**")
        sched = []
        for g in reversed(results):  # most recent first
            opp = g["opp"]
            sched.append({
                "Date": g["date"],
                "": g["site"],
                "Opponent": f"#{rank_of.get(opp, '—')} {name_of.get(opp, '?')}",
                "Class": class_of.get(opp, "N/A"),
                "Result": f"{'W' if g['won'] else 'L'} {g['pf']}-{g['pa']}",
                "Tracked": "●" if g["tracked"] else "",
            })
        if sched:
            st.dataframe(pd.DataFrame(sched), hide_index=True,
                         width="stretch",
                         height=min(520, 60 + 35 * len(sched)))
        else:
            st.info("No completed games.")

        # upcoming (from the schedule table, unplayed)
        upcoming = query(
            """SELECT date, opponent_id, home_away, location
               FROM schedule
               WHERE team_id=? AND (opp_score IS NULL OR team_score IS NULL)
               ORDER BY date""", (pick,))
        if upcoming:
            st.markdown("**Upcoming**")
            up = [{"Date": u["date"],
                   "": "vs" if u["home_away"] == "Home" else "@",
                   "Opponent": name_of.get(u["opponent_id"],
                                           f"#{u['opponent_id']}"),
                   "Class": class_of.get(u["opponent_id"], "N/A")}
                  for u in upcoming]
            st.dataframe(pd.DataFrame(up), hide_index=True,
                         width="stretch")
    with c2:
        st.markdown("**Record by opponent class**")
        if by_class:
            cls_rows = [{"Class": c, "W": wl[0], "L": wl[1]}
                        for c, wl in sorted(
                            by_class.items(),
                            key=lambda kv: TR._CLASS_RANK.get(kv[0], 99))]
            st.dataframe(pd.DataFrame(cls_rows), hide_index=True,
                         width="stretch")
        st.markdown("**Offense vs defense**")
        bar = go.Figure()
        bar.add_trace(go.Bar(
            x=["Adj O", "Adj D"], y=[r["xPPG"], r["xoPPG"]],
            marker_color=[ACCENT, AWAY],
            text=[r["xPPG"], r["xoPPG"]], textposition="outside",
            marker_line_width=0))
        bar.update_yaxes(title="Points / game (opp-adjusted)")
        _style(bar, 240)
        st.plotly_chart(bar, width="stretch")

        # scoring profile in wins vs losses (from final scores)
        wins = [g for g in results if g["won"]]
        losses = [g for g in results if not g["won"]]
        if wins and losses:
            st.markdown("**Wins vs losses** — points for / against")
            def _avg(games, key):
                return sum(g[key] for g in games) / len(games)
            wl = go.Figure()
            wl.add_trace(go.Bar(
                x=["In wins", "In losses"], name="Scored",
                y=[_avg(wins, "pf"), _avg(losses, "pf")], marker_color=ACCENT))
            wl.add_trace(go.Bar(
                x=["In wins", "In losses"], name="Allowed",
                y=[_avg(wins, "pa"), _avg(losses, "pa")], marker_color=AWAY))
            wl.update_layout(barmode="group")
            wl.update_yaxes(title="Points / game")
            _style(wl, 260)
            st.plotly_chart(wl, width="stretch")

    # ── Hot & cold (current streaks across the league) ───────────────────────
    streaks = []
    for tid in scored:
        s = _team_streak(_team_results(tid))
        if s and len(s) > 1:
            streaks.append((tid, s[0], int(s[1:])))
    if streaks:
        st.markdown("<div class='section-hdr'>Hot &amp; cold</div>",
                    unsafe_allow_html=True)
        hot = sorted((x for x in streaks if x[1] == "W"),
                     key=lambda x: -x[2])[:5]
        cold = sorted((x for x in streaks if x[1] == "L"),
                      key=lambda x: -x[2])[:5]
        hc1, hc2 = st.columns(2)
        with hc1:
            st.markdown("🔥 **Win streaks**")
            for tid, _, n in hot:
                st.markdown(
                    f"**{name_of[tid]}** `{class_of[tid]}`  "
                    f"<span style='color:#2ecc71;font-weight:700'>W{n}</span>  "
                    f"({scored[tid]['W']}-{scored[tid]['L']})",
                    unsafe_allow_html=True)
        with hc2:
            st.markdown("🧊 **Losing streaks**")
            for tid, _, n in cold:
                st.markdown(
                    f"**{name_of[tid]}** `{class_of[tid]}`  "
                    f"<span style='color:#e74c3c;font-weight:700'>L{n}</span>  "
                    f"({scored[tid]['W']}-{scored[tid]['L']})",
                    unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — TRACKED  (possession-based, advanced)
# ══════════════════════════════════════════════════════════════════════════════
with tab_track:
    if not tracked:
        st.info("No tracked games for this league yet. Track a game in the Game "
                "Tracker and its advanced ratings appear here.")
    else:
        st.caption(
            "Possession-based ratings over **tracked games only** — a far smaller, "
            "sparsely-connected sample, so treat as directional. **NetRtg** is "
            "points per 100 possessions vs an average team; **Pace** is "
            "possessions per game.")

        rows = _filter_rows(
            sorted(tracked.values(), key=lambda r: r["Rank"]), "trk")
        if not rows:
            st.info("No teams match the current Class / games filter.")
        else:
            df = pd.DataFrame(rows)[[
                "Rank", "name", "class", "GP", "Power", "NetRtg",
                "ORtg", "DRtg", "Pace", "eFG", "FGpct", "TPpct", "SOS"]].rename(
                columns={"name": "Team", "class": "Class"})
            st.dataframe(
                df, hide_index=True, width="stretch",
                height=min(640, 60 + 35 * len(df)),
                column_config={
                    "Power": st.column_config.ProgressColumn(
                        "Power", format="%.1f", min_value=0, max_value=100),
                    "NetRtg": st.column_config.NumberColumn("NetRtg", format="%.1f"),
                    "eFG": st.column_config.NumberColumn("eFG%", format="%.3f"),
                    "FGpct": st.column_config.NumberColumn("FG%", format="%.3f"),
                    "TPpct": st.column_config.NumberColumn("3P%", format="%.3f"),
                    "SOS": st.column_config.NumberColumn("SOS", format="%.2f"),
                })
            st.download_button("⬇ Tracked ratings (CSV)", df.to_csv(index=False),
                               file_name=f"tracked_ratings_{gender}.csv",
                               mime="text/csv", key="dl_tracked")

        st.markdown("<div class='section-hdr'>Tracked schedule & box scores</div>",
                    unsafe_allow_html=True)
        torder = sorted(tracked.keys(), key=lambda t: tracked[t]["Rank"])
        tpick = st.selectbox(
            "Team", torder,
            format_func=lambda t: f"#{tracked[t]['Rank']}  {name_of.get(t, t)}",
            key="trk_team")

        tracked_games = [g for g in _team_results(tpick) if g["tracked"]]
        if not tracked_games:
            st.info("This team has no tracked games yet.")
        else:
            for g in reversed(tracked_games):
                opp = g["opp"]
                res = f"{'W' if g['won'] else 'L'} {g['pf']}-{g['pa']}"
                label = (f"{g['date']}  ·  {g['site']} {name_of.get(opp, '?')}"
                         f"  ·  {res}")
                with st.expander(label):
                    render_box_score(g["game_id"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — TEAM CHARTS  (tracked-event driven, cross-team)
# ══════════════════════════════════════════════════════════════════════════════
with tab_chart:
    if not tracked:
        st.info("Team charts are built from tracked-game events — none yet for "
                "this league.")
    else:
        st.caption("How teams score, how they win, and who can shoot — across all "
                   "tracked games in this league. Built from per-game team boxes, "
                   "so defensive splits (opp eFG%, ORB%) are included.")

        # per-team advanced bundle — the single shared box pass from
        # helpers/league_analytics.team_tracked_pack (computed once, cached, and
        # reused by League Lab + Stat Lab). `ts[t]` carries the same derived keys
        # this tab used inline, plus extras; 3P% is "TPpct".
        teams = pack["teams"]
        own, opp, gp, ts = pack["own"], pack["opp"], pack["gp"], pack["ts"]
        qfor, qagn, tqbox = pack["qfor"], pack["qagn"], pack["tqbox"]
        labels = [name_of.get(t, str(t)) for t in teams]

        def _hbar(metric, title, axis, pct=False, asc=False, n=2):
            """Sorted horizontal bar of one team metric."""
            srt = sorted(teams, key=lambda t: ts[t][metric], reverse=not asc)
            vals = [ts[t][metric] for t in srt]
            slab = [name_of.get(t, str(t)) for t in srt]
            fmt = "%{x:.1f}%" if pct else f"%{{x:.{n}f}}"
            fig = go.Figure(go.Bar(
                y=slab, x=vals, orientation="h", marker_color=ACCENT,
                text=vals, texttemplate=fmt, textposition="auto",
                marker_line_width=0))
            fig.update_xaxes(title=axis)
            _style(fig, max(320, 26 * len(srt)))
            st.markdown(f"**{title}**")
            st.plotly_chart(fig, width="stretch")

        # ════════════════ SCORING ════════════════
        st.markdown("<div class='section-hdr'>Scoring</div>",
                    unsafe_allow_html=True)
        st.markdown("**How teams score** — points per game by source")
        two = [own[t]["2PM"] * 2 / max(gp[t], 1) for t in teams]
        thr = [own[t]["3PM"] * 3 / max(gp[t], 1) for t in teams]
        ftp = [own[t]["FTM"] / max(gp[t], 1) for t in teams]
        sfig = go.Figure()
        sfig.add_trace(go.Bar(x=labels, y=two, name="2-pt", marker_color=ACCENT))
        sfig.add_trace(go.Bar(x=labels, y=thr, name="3-pt", marker_color="#58a6ff"))
        sfig.add_trace(go.Bar(x=labels, y=ftp, name="FT", marker_color="#8b949e"))
        sfig.update_layout(barmode="stack")
        sfig.update_yaxes(title="Points / game")
        _style(sfig, 380)
        st.plotly_chart(sfig, width="stretch")

        c1, c2 = st.columns(2)
        with c1:
            _hbar("TS", "True shooting %", "TS%", pct=True)
        with c2:
            _hbar("paint_pg", "Paint scoring — points / game", "Paint pts/g")

        # ════════════════ HOW TEAMS WIN ════════════════
        st.markdown("<div class='section-hdr'>How teams win</div>",
                    unsafe_allow_html=True)
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("**Offense vs defense** (bubble = pace)")
            ortg = [tracked[t]["ORtg"] for t in teams]
            drtg = [tracked[t]["DRtg"] for t in teams]
            pace = [tracked[t]["Pace"] for t in teams]
            wfig = go.Figure(go.Scatter(
                x=ortg, y=drtg, mode="markers+text", text=labels,
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=[max(8, p / 2) for p in pace], color=ortg,
                            colorscale="Viridis", showscale=False,
                            line=dict(width=1, color="#30363d"))))
            if ortg:
                wfig.add_vline(x=sum(ortg) / len(ortg),
                               line=dict(color="#30363d", dash="dot"))
                wfig.add_hline(y=sum(drtg) / len(drtg),
                               line=dict(color="#30363d", dash="dot"))
            wfig.update_xaxes(title="Offensive rating →")
            wfig.update_yaxes(title="← Defensive rating (lower better)",
                              autorange="reversed")
            _style(wfig, 400)
            st.plotly_chart(wfig, width="stretch")
        with c4:
            st.markdown("**Ball movement** — assists vs turnovers per game")
            mfig = go.Figure(go.Scatter(
                x=[ts[t]["tov_pg"] for t in teams],
                y=[ts[t]["ast_pg"] for t in teams],
                mode="markers+text", text=labels, textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=12, color=[ts[t]["ast_per_fgm"] for t in teams],
                            colorscale="Tealgrn", showscale=True,
                            colorbar=dict(title="AST/<br>FGM", thickness=10),
                            line=dict(width=1, color="#30363d"))))
            mfig.update_xaxes(title="Turnovers / game →")
            mfig.update_yaxes(title="Assists / game →")
            _style(mfig, 400)
            st.plotly_chart(mfig, width="stretch")

        # Four Factors table (Dean Oliver — offense + defensive eFG%)
        st.markdown("**Four factors** — eFG%, turnover %, offensive-rebound %, "
                    "free-throw rate (plus opponent eFG%)")
        ff = pd.DataFrame([{
            "Team": name_of.get(t, str(t)),
            "eFG%": round(ts[t]["eFG"], 1),
            "TOV%": round(ts[t]["TOVpct"], 1),
            "ORB%": round(ts[t]["ORBpct"], 1),
            "FT Rate": round(ts[t]["FTr"], 3),
            "Opp eFG%": round(ts[t]["oeFG"], 1),
            "DRB%": round(ts[t]["DRBpct"], 1),
        } for t in teams])
        st.dataframe(
            ff, hide_index=True, width="stretch",
            height=min(560, 60 + 35 * len(ff)),
            column_config={
                "eFG%": st.column_config.ProgressColumn(
                    "eFG%", format="%.1f", min_value=0, max_value=70),
                "Opp eFG%": st.column_config.ProgressColumn(
                    "Opp eFG%", format="%.1f", min_value=0, max_value=70),
                "ORB%": st.column_config.NumberColumn("ORB%", format="%.1f"),
                "DRB%": st.column_config.NumberColumn("DRB%", format="%.1f"),
                "TOV%": st.column_config.NumberColumn("TOV%", format="%.1f"),
            })

        # ════════════════ SHOOTING & STYLE ════════════════
        st.markdown("<div class='section-hdr'>Shooting & style</div>",
                    unsafe_allow_html=True)
        c5, c6 = st.columns(2)
        with c5:
            st.markdown("**Who can shoot** — eFG% & 3P%")
            srt = sorted(teams, key=lambda t: tracked[t]["eFG"])
            efg = [tracked[t]["eFG"] * 100 for t in srt]
            tp = [tracked[t]["TPpct"] * 100 for t in srt]
            slab = [name_of.get(t, str(t)) for t in srt]
            shfig = go.Figure()
            shfig.add_trace(go.Bar(y=slab, x=efg, name="eFG%", orientation="h",
                                   marker_color=ACCENT))
            shfig.add_trace(go.Bar(y=slab, x=tp, name="3P%", orientation="h",
                                   marker_color="#58a6ff"))
            shfig.update_layout(barmode="group")
            shfig.update_xaxes(title="%")
            _style(shfig, max(360, 26 * len(srt)))
            st.plotly_chart(shfig, width="stretch")
        with c6:
            st.markdown("**Shot diet** — 3-point reliance vs 3P% (bubble = FGA/g)")
            dfig = go.Figure(go.Scatter(
                x=[ts[t]["TPAr"] for t in teams],
                y=[ts[t]["TPpct"] for t in teams],
                mode="markers+text", text=labels, textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=[max(8, ts[t]["fga_pg"] / 4) for t in teams],
                            color="#58a6ff", line=dict(width=1, color="#30363d"))))
            dfig.update_xaxes(title="3PA rate (% of FGA) →")
            dfig.update_yaxes(title="3P% →")
            _style(dfig, 400)
            st.plotly_chart(dfig, width="stretch")

        c7, c8 = st.columns(2)
        with c7:
            _hbar("fga_pg", "Shot volume — FGA / game", "FGA/g", n=1)
        with c8:
            _hbar("TOVpct", "Turnover % (lower better)", "TOV%", pct=True,
                  asc=True)

        # crosshair scatter helper (mean lines, optional reversed y)
        def _scatter(xk, yk, xt, yt, title, color="#58a6ff",
                     yreverse=False, height=400):
            xs = [ts[t][xk] for t in teams]
            ys = [ts[t][yk] for t in teams]
            fig = go.Figure(go.Scatter(
                x=xs, y=ys, mode="markers+text", text=labels,
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=12, color=color,
                            line=dict(width=1, color="#30363d"))))
            if xs:
                fig.add_vline(x=sum(xs) / len(xs),
                              line=dict(color="#30363d", dash="dot"))
                fig.add_hline(y=sum(ys) / len(ys),
                              line=dict(color="#30363d", dash="dot"))
            fig.update_xaxes(title=xt)
            fig.update_yaxes(title=yt, autorange="reversed" if yreverse else None)
            _style(fig, height)
            st.markdown(f"**{title}**")
            st.plotly_chart(fig, width="stretch")

        c11, c12 = st.columns(2)
        with c11:
            _scatter("eFG", "TS", "eFG% →", "TS% →",
                     "Shooting map — eFG% vs TS% (crosshairs = league avg)")
        with c12:
            _scatter("paint_pg", "paint3_pg", "Paint pts/g →", "3PT pts/g →",
                     "Inside vs outside — paint vs 3PT scoring", color="#f0a500")

        # assisted vs self-created (Ast% of made FGs)
        st.markdown("**Ball movement** — assisted vs self-created field goals")
        srt = sorted(teams, key=lambda t: ts[t]["Astpct"], reverse=True)
        slab = [name_of.get(t, str(t)) for t in srt]
        afig = go.Figure()
        afig.add_trace(go.Bar(x=slab, y=[ts[t]["Astpct"] for t in srt],
                              name="Assisted %", marker_color="#1a9850"))
        afig.add_trace(go.Bar(x=slab, y=[100 - ts[t]["Astpct"] for t in srt],
                              name="Self-created %", marker_color=AWAY))
        afig.update_layout(barmode="stack")
        afig.update_yaxes(title="% of made FGs")
        afig.update_xaxes(tickangle=-40)
        _style(afig, 360)
        st.plotly_chart(afig, width="stretch")
        st.caption("Assisted% = made FGs off a pass (AST/FGM). High = ball-movement "
                   "offense; low = isolation / self-creation.")

        # ════════════════ DEFENSE ════════════════
        st.markdown("<div class='section-hdr'>Defense</div>",
                    unsafe_allow_html=True)
        d1, d2 = st.columns(2)
        with d1:
            _hbar("oeFG", "Opponent eFG% (lower better)", "Opp eFG%",
                  pct=True, asc=True)
        with d2:
            _scatter("blk_r", "stl_r", "Block rate (per 100) →",
                     "Steal rate (per 100) →",
                     "Rim vs perimeter D — blocks vs steals", color="#9b59b6")

        # ════════════════ POSSESSIONS & EFFICIENCY ════════════════
        st.markdown("<div class='section-hdr'>Possessions & efficiency</div>",
                    unsafe_allow_html=True)
        st.caption("A possession ends on a shot or a turnover (FGA + TOV); "
                   "free throws and fouls don't count. Pace is possessions per "
                   "game; PPP is points per possession.")
        c9, c10 = st.columns(2)
        with c9:
            _hbar("Pace", "Pace — possessions / game", "Poss/g", n=1)
        with c10:
            st.markdown("**Efficiency** — points per possession (own vs allowed)")
            srt = sorted(teams, key=lambda t: ts[t]["PPP"] - ts[t]["oPPP"])
            slab = [name_of.get(t, str(t)) for t in srt]
            efig = go.Figure()
            efig.add_trace(go.Bar(y=slab, x=[ts[t]["PPP"] for t in srt],
                                  name="PPP (off)", orientation="h",
                                  marker_color=ACCENT))
            efig.add_trace(go.Bar(y=slab, x=[ts[t]["oPPP"] for t in srt],
                                  name="Opp PPP (def)", orientation="h",
                                  marker_color=AWAY))
            efig.update_layout(barmode="group")
            efig.update_xaxes(title="Points / possession")
            _style(efig, max(360, 26 * len(srt)))
            st.plotly_chart(efig, width="stretch")

        # net efficiency margin per possession
        _hbar2_metric = {t: ts[t]["PPP"] - ts[t]["oPPP"] for t in teams}
        st.markdown("**Net points per possession** (PPP − opponent PPP)")
        srt = sorted(teams, key=lambda t: _hbar2_metric[t], reverse=True)
        vals = [_hbar2_metric[t] for t in srt]
        nfig = go.Figure(go.Bar(
            x=[name_of.get(t, str(t)) for t in srt], y=vals,
            marker_color=[ACCENT if v >= 0 else AWAY for v in vals],
            text=[f"{v:+.3f}" for v in vals], textposition="outside",
            marker_line_width=0))
        nfig.add_hline(y=0, line=dict(color="#30363d", width=1))
        nfig.update_yaxes(title="Net PPP")
        _style(nfig, 340)
        st.plotly_chart(nfig, width="stretch")

        # ════════════════ GAME FLOW (quarter data) ════════════════
        st.markdown("<div class='section-hdr'>Game flow — quarter data</div>",
                    unsafe_allow_html=True)
        allq = sorted({q for t in teams for q in qfor[t]} |
                      {q for t in teams for q in qagn[t]})
        qlabels = [_q_label(q) for q in allq]

        f1, f2 = st.columns(2)
        with f1:
            st.markdown("**Points scored by quarter** (top 8)")
            qfig = go.Figure()
            for t in teams[:8]:
                ys = [qfor[t].get(q, 0) / max(gp[t], 1) for q in allq]
                qfig.add_trace(go.Scatter(
                    x=qlabels, y=ys, mode="lines+markers",
                    name=name_of.get(t, str(t))))
            qfig.update_yaxes(title="Points / game")
            _style(qfig, 360)
            st.plotly_chart(qfig, width="stretch")
        with f2:
            st.markdown("**Points allowed by quarter** (top 8)")
            afig = go.Figure()
            for t in teams[:8]:
                ys = [qagn[t].get(q, 0) / max(gp[t], 1) for q in allq]
                afig.add_trace(go.Scatter(
                    x=qlabels, y=ys, mode="lines+markers",
                    name=name_of.get(t, str(t))))
            afig.update_yaxes(title="Points / game")
            _style(afig, 360)
            st.plotly_chart(afig, width="stretch")
        if len(teams) > 8:
            st.caption("Quarter lines show the top 8 teams to stay readable.")

        # league-average quarter shape: scored, allowed, net
        st.markdown("**League quarter shape** — average points scored & allowed")
        lf = [sum(qfor[t].get(q, 0) for t in teams) /
              max(sum(gp[t] for t in teams), 1) for q in allq]
        la = [sum(qagn[t].get(q, 0) for t in teams) /
              max(sum(gp[t] for t in teams), 1) for q in allq]
        lfig = go.Figure()
        lfig.add_trace(go.Bar(x=qlabels, y=lf, name="Scored", marker_color=ACCENT,
                              text=[f"{v:.1f}" for v in lf], textposition="outside"))
        lfig.add_trace(go.Bar(x=qlabels, y=la, name="Allowed", marker_color=AWAY,
                              text=[f"{v:.1f}" for v in la], textposition="outside"))
        lfig.update_layout(barmode="group")
        lfig.update_yaxes(title="Points / game (per team)")
        _style(lfig, 320)
        st.plotly_chart(lfig, width="stretch")

        # points per possession by quarter (league + per team), from quarter boxes
        st.markdown("**Points per possession by quarter** (top 8)")
        ppp_fig = go.Figure()
        for t in teams[:8]:
            ys = []
            for q in allq:
                bx = tqbox[t].get(q)
                poss = S.estimate_possessions(bx) if bx else 0
                ys.append(round(bx["PTS"] / poss, 3) if poss > 0 else None)
            ppp_fig.add_trace(go.Scatter(
                x=qlabels, y=ys, mode="lines+markers", connectgaps=True,
                name=name_of.get(t, str(t))))
        ppp_fig.update_yaxes(title="Points / possession")
        _style(ppp_fig, 360)
        st.plotly_chart(ppp_fig, width="stretch")
        st.caption("Quarter PPP uses each team's per-quarter box "
                   "(FGA + TOV possessions — shots + turnovers).")

        # ════════════════ TEAM COMPARISON RADAR ════════════════
        st.markdown("<div class='section-hdr'>Team comparison radar</div>",
                    unsafe_allow_html=True)
        st.caption("Pick 2–5 teams. Each axis is normalized across the shown "
                   "teams (100 = best); defensive/turnover axes are inverted so "
                   "outward is always better.")
        radar_cfg = [("ORtg", "Offense", True), ("DRtg", "Defense", False),
                     ("TS", "Shooting", True), ("ORBpct", "Off. reb", True),
                     ("TOVpct", "Ball security", False), ("Pace", "Pace", True),
                     ("stl_r", "Steals", True), ("blk_r", "Blocks", True)]
        sel = st.multiselect(
            "Teams", teams, default=teams[:min(3, len(teams))],
            format_func=lambda t: name_of.get(t, str(t)), max_selections=5,
            key="chart_radar")
        if len(sel) >= 2:
            cats = [lbl for _, lbl, _ in radar_cfg]
            keys_r = [k for k, _, _ in radar_cfg]
            hibs = [h for _, _, h in radar_cfg]
            # normalize each metric across the SELECTED pool
            norm = {}
            for k, hib in zip(keys_r, hibs):
                vals = [ts[t][k] for t in sel]
                lo, hi = min(vals), max(vals)
                d = {}
                for t in sel:
                    if hi == lo:
                        d[t] = 50.0
                    else:
                        frac = (ts[t][k] - lo) / (hi - lo)
                        d[t] = (frac if hib else 1 - frac) * 100
                norm[k] = d
            palette = ["#f0a500", "#58a6ff", "#2ecc71", "#e74c3c", "#9b59b6"]
            rfig = go.Figure()
            for i, t in enumerate(sel):
                clr = palette[i % len(palette)]
                rr, gg, bb = _rgb(clr)
                vals = [norm[k][t] for k in keys_r]
                hover = "<br>".join(f"{lbl}: {ts[t][k]:.1f}"
                                    for k, lbl, _ in radar_cfg)
                rfig.add_trace(go.Scatterpolar(
                    r=vals + [vals[0]], theta=cats + [cats[0]], fill="toself",
                    name=name_of.get(t, str(t)), line=dict(color=clr, width=2),
                    fillcolor=f"rgba({rr},{gg},{bb},0.15)",
                    hovertemplate=f"<b>{name_of.get(t, str(t))}</b><br>"
                                  f"{hover}<extra></extra>"))
            rfig.update_layout(
                template="plotly_dark", height=480,
                paper_bgcolor="rgba(0,0,0,0)",
                polar=dict(bgcolor=CARD_BG,
                           radialaxis=dict(range=[0, 100], showticklabels=False,
                                           gridcolor=GRID),
                           angularaxis=dict(gridcolor=GRID)),
                legend=dict(orientation="h", y=-0.08, x=0),
                margin=dict(l=60, r=60, t=30, b=60))
            st.plotly_chart(rfig, width="stretch")
        else:
            st.info("Select at least two teams to draw the radar.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — LEAGUE LAB  (futuristic, league-wide analytics)
# ══════════════════════════════════════════════════════════════════════════════
with tab_lab:
    st.caption(
        "The whole field at a glance. **Results-only** views (landscape, tiers, "
        "Pythagoras, momentum, network) cover every team; the tracked KenPom map, "
        "gauges and DNA radar use possession data.")

    ts = pack["ts"]
    pteams = pack["teams"]
    sv = list(scored.values())

    lab_land, lab_tier, lab_pyth, lab_mo, lab_net = st.tabs(
        ["🌌 Landscape", "🏅 Power tiers", "🎲 Pythagoras & luck",
         "📈 Momentum", "🕸 Win network"])

    # ──────────────────────────────────────────────────────────────────────
    #  LANDSCAPE
    # ──────────────────────────────────────────────────────────────────────
    with lab_land:
        _lab_hdr("Efficiency landscape — adjusted offense vs defense")
        st.caption("Every team by opponent-adjusted points scored (x) and allowed "
                   "(y, reversed so up = better defense). Crosshairs = league "
                   "average; top-right = elite both ends. Bubble & color = Power.")
        xs = [s["xPPG"] for s in sv]
        ys = [s["xoPPG"] for s in sv]
        powers = [s["Power"] for s in sv]
        txt = [f"#{s['Rank']} {s['name']} ({s['class']})" for s in sv]
        land = go.Figure(go.Scatter(
            x=xs, y=ys, mode="markers",
            marker=dict(size=[max(7, p / 4) for p in powers], color=powers,
                        colorscale="Turbo", showscale=True, cmin=0, cmax=100,
                        colorbar=dict(title="Power", thickness=12),
                        line=dict(width=0.5, color="#0d1117")),
            text=txt,
            hovertemplate="%{text}<br>Adj O %{x:.1f} · Adj D %{y:.1f}"
                          "<extra></extra>"))
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        land.add_vline(x=mx, line=dict(color="#30363d", dash="dot"))
        land.add_hline(y=my, line=dict(color="#30363d", dash="dot"))
        land.update_xaxes(title="Adjusted offense (xPPG) →")
        land.update_yaxes(title="← Adjusted defense (xoPPG) · up = better",
                          autorange="reversed")
        _style(land, 540)
        st.plotly_chart(land, width="stretch", key="lab_land")

        if pteams:
            _lab_hdr("Tracked KenPom map — efficiency per 100 possessions")
            ortg = [ts[t]["ORtg"] for t in pteams]
            drtg = [ts[t]["DRtg"] for t in pteams]
            pace = [ts[t]["Pace"] for t in pteams]
            net = [ts[t]["NetRtg"] for t in pteams]
            lbl = [name_of[t] for t in pteams]
            kp = go.Figure(go.Scatter(
                x=ortg, y=drtg, mode="markers+text", text=lbl,
                textposition="top center", textfont=dict(size=9),
                marker=dict(size=[max(10, p / 2) for p in pace], color=net,
                            colorscale="RdYlGn", cmid=0, showscale=True,
                            colorbar=dict(title="Net", thickness=12),
                            line=dict(width=1, color="#30363d")),
                hovertemplate="%{text}<br>ORtg %{x:.1f} · DRtg %{y:.1f}"
                              "<extra></extra>"))
            kp.add_vline(x=sum(ortg) / len(ortg),
                         line=dict(color="#30363d", dash="dot"))
            kp.add_hline(y=sum(drtg) / len(drtg),
                         line=dict(color="#30363d", dash="dot"))
            kp.update_xaxes(title="Offensive rating →")
            kp.update_yaxes(title="← Defensive rating · lower better",
                            autorange="reversed")
            _style(kp, 460)
            st.plotly_chart(kp, width="stretch", key="lab_kenpom")

            _lab_hdr("Team spotlight — gauges & DNA")
            spot = st.selectbox(
                "Spotlight team", pteams,
                format_func=lambda t: f"#{tracked[t]['Rank']} {name_of[t]}",
                key="lab_spot")
            allO = [ts[t]["ORtg"] for t in pteams]
            allD = [ts[t]["DRtg"] for t in pteams]
            allP = [ts[t]["Pace"] for t in pteams]
            allE = [ts[t]["eFG"] for t in pteams]
            gc = st.columns(4)
            gc[0].plotly_chart(_gauge(
                ts[spot]["ORtg"], min(allO), max(allO), "Off rating",
                ref=sum(allO) / len(allO)), width="stretch", key="lab_g_o")
            gc[1].plotly_chart(_gauge(
                ts[spot]["DRtg"], min(allD), max(allD), "Def rating",
                good_high=False, ref=sum(allD) / len(allD)),
                width="stretch", key="lab_g_d")
            gc[2].plotly_chart(_gauge(
                ts[spot]["Pace"], min(allP), max(allP), "Pace",
                ref=sum(allP) / len(allP)), width="stretch", key="lab_g_p")
            gc[3].plotly_chart(_gauge(
                ts[spot]["eFG"], min(allE), max(allE), "eFG%", suffix="%",
                ref=sum(allE) / len(allE)), width="stretch", key="lab_g_e")

            dna_cfg = [("ORtg", "Offense", True), ("DRtg", "Defense", False),
                       ("eFG", "Shooting", True), ("ORBpct", "Off reb", True),
                       ("DRBpct", "Def reb", True), ("ast_to", "Ball control", True),
                       ("stl_r", "Steals", True), ("blk_r", "Blocks", True)]
            cats, rvals, hov = [], [], []
            for k, lab, hib in dna_cfg:
                pool = [ts[t][k] for t in pteams]
                pct = LA.percentile(ts[spot][k], pool, higher_better=hib)
                cats.append(lab)
                rvals.append(pct if pct is not None else 0)
                hov.append(f"{lab}: {ts[spot][k]:.1f} ({pct:.0f}th)")
            rr, gg, bb = _rgb(ACCENT)
            dna = go.Figure(go.Scatterpolar(
                r=rvals + [rvals[0]], theta=cats + [cats[0]], fill="toself",
                line=dict(color=ACCENT, width=2),
                fillcolor=f"rgba({rr},{gg},{bb},0.18)",
                text=hov + [hov[0]],
                hovertemplate="%{text}<extra></extra>"))
            dna.update_layout(
                template="plotly_dark", height=420,
                paper_bgcolor="rgba(0,0,0,0)",
                polar=dict(bgcolor=CARD_BG,
                           radialaxis=dict(range=[0, 100], showticklabels=False,
                                           gridcolor=GRID),
                           angularaxis=dict(gridcolor=GRID)),
                margin=dict(l=60, r=60, t=30, b=30), showlegend=False)
            st.markdown(f"**{name_of[spot]} — Team DNA** (league percentile, "
                        f"outward = better)")
            st.plotly_chart(dna, width="stretch", key="lab_dna")
        else:
            st.info("Track games to unlock the possession-based KenPom map, "
                    "gauges and DNA radar.")

    # ──────────────────────────────────────────────────────────────────────
    #  POWER TIERS
    # ──────────────────────────────────────────────────────────────────────
    with lab_tier:
        _lab_hdr("Power tiers")
        st.caption("Teams bucketed by Power (0-100, 50 = league average). "
                   "S ≥ 68 · A ≥ 60 · B ≥ 52 · C ≥ 44 · D < 44.")
        tier_order = ["S · ELITE", "A · CONTENDER", "B · SOLID",
                      "C · MIDDLING", "D · REBUILDING"]
        buckets = defaultdict(list)
        for s in sorted(sv, key=lambda r: r["Rank"]):
            tname, _ = _tier(s["Power"])
            buckets[tname].append(s)
        tcols = st.columns(5)
        for i, tname in enumerate(tier_order):
            members = buckets.get(tname, [])
            _, tclr = _tier({"S · ELITE": 70, "A · CONTENDER": 62, "B · SOLID": 54,
                             "C · MIDDLING": 46, "D · REBUILDING": 40}[tname])
            chips = "".join(
                f"<div style='font-size:12px;color:#c9d1d9;margin:3px 0;"
                f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>"
                f"<b style='color:{tclr}'>{m['Power']:.0f}</b> "
                f"#{m['Rank']} {m['name']}</div>"
                for m in members[:8])
            more = (f"<div style='font-size:10px;color:#6e7681;margin-top:4px'>"
                    f"+{len(members) - 8} more</div>") if len(members) > 8 else ""
            tcols[i].markdown(
                f"<div class='glass-tile' style='text-align:left;height:100%'>"
                f"<div class='glass-label' style='color:{tclr}'>{tname}</div>"
                f"<div class='glass-value' style='color:{tclr};font-size:22px'>"
                f"{len(members)}</div>{chips}{more}</div>",
                unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Power distribution by class**")
            classes = sorted({s["class"] for s in sv},
                             key=lambda c: TR._CLASS_RANK.get(c, 99))
            vio = go.Figure()
            for c in classes:
                vals = [s["Power"] for s in sv if s["class"] == c]
                vio.add_trace(go.Violin(
                    y=vals, name=c, box_visible=True, meanline_visible=True,
                    points="all", marker=dict(size=3), line=dict(width=1),
                    fillcolor="rgba(88,166,255,0.10)"))
            vio.update_yaxes(title="Power")
            vio.update_layout(showlegend=False)
            _style(vio, 420)
            st.plotly_chart(vio, width="stretch", key="lab_violin")
        with c2:
            st.markdown("**Overachievers** — Power vs strength of schedule")
            st.caption("Up & right = strong despite a hard slate. Crosshairs = "
                       "league average.")
            sx = [s["SOS"] for s in sv]
            sy = [s["Power"] for s in sv]
            scl = [TR._CLASS_RANK.get(s["class"], 0) for s in sv]
            ov = go.Figure(go.Scatter(
                x=sx, y=sy, mode="markers",
                marker=dict(size=9, color=scl, colorscale="Viridis",
                            showscale=False, line=dict(width=0.5, color="#0d1117")),
                text=[f"{s['name']} ({s['class']})" for s in sv],
                hovertemplate="%{text}<br>SOS %{x:.2f} · Power %{y:.1f}"
                              "<extra></extra>"))
            ov.add_vline(x=sum(sx) / len(sx), line=dict(color="#30363d", dash="dot"))
            ov.add_hline(y=sum(sy) / len(sy), line=dict(color="#30363d", dash="dot"))
            ov.update_xaxes(title="Strength of schedule →")
            ov.update_yaxes(title="Power →")
            _style(ov, 420)
            st.plotly_chart(ov, width="stretch", key="lab_overach")

        st.markdown("**League map** — class → team (size = wins, color = Power)")
        labels, parents, vals, colors = [], [], [], []
        classes = sorted({s["class"] for s in sv},
                         key=lambda c: TR._CLASS_RANK.get(c, 99))
        # children first so each class value == sum of its children (branch=total)
        children = [(s["name"], s["class"], max(s["W"], 0.5), s["Power"])
                    for s in sv]
        cls_val = defaultdict(float)
        cls_pow = defaultdict(list)
        for nm, c, v, p in children:
            cls_val[c] += v
            cls_pow[c].append(p)
        for c in classes:
            labels.append(c)
            parents.append("")
            vals.append(cls_val[c])
            colors.append(sum(cls_pow[c]) / len(cls_pow[c]))
        for nm, c, v, p in children:
            labels.append(nm)
            parents.append(c)
            vals.append(v)
            colors.append(p)
        tree = go.Figure(go.Treemap(
            labels=labels, parents=parents, values=vals, branchvalues="total",
            marker=dict(colors=colors, colorscale="Turbo", cmid=50, cmin=0,
                        cmax=100, showscale=True,
                        colorbar=dict(title="Power", thickness=12)),
            hovertemplate="<b>%{label}</b><br>%{value} wins<extra></extra>",
            textfont=dict(size=12)))
        tree.update_layout(template="plotly_dark", height=520,
                           paper_bgcolor="rgba(0,0,0,0)",
                           margin=dict(l=6, r=6, t=10, b=6))
        st.plotly_chart(tree, width="stretch", key="lab_tree")

    # ──────────────────────────────────────────────────────────────────────
    #  PYTHAGORAS & LUCK
    # ──────────────────────────────────────────────────────────────────────
    with lab_pyth:
        _lab_hdr("Pythagorean wins & luck")
        st.caption(
            "Pythagorean expectation predicts win% from points scored vs allowed "
            f"(exponent {LA.PYTHAG_EXP:g}). **Luck** = actual wins − expected "
            "wins: above the line = winning more than the scoring says (clutch or "
            "fortunate); below = underperforming the margins.")
        fids = [t for t in form_stats]
        aw = [form_stats[t]["W"] for t in fids]
        pw = [form_stats[t]["Pyth_W"] for t in fids]
        lk = [form_stats[t]["Luck_wins"] for t in fids]
        nm = [name_of.get(t, str(t)) for t in fids]
        pyfig = go.Figure(go.Scatter(
            x=pw, y=aw, mode="markers",
            marker=dict(size=9, color=lk, colorscale="RdYlGn", cmid=0,
                        showscale=True, colorbar=dict(title="Luck", thickness=12),
                        line=dict(width=0.5, color="#0d1117")),
            text=nm,
            hovertemplate="%{text}<br>Expected %{x:.1f} · Actual %{y} W"
                          "<extra></extra>"))
        hi = max(max(aw, default=1), max(pw, default=1)) + 1
        pyfig.add_trace(go.Scatter(
            x=[0, hi], y=[0, hi], mode="lines", line=dict(color=GREY, dash="dot"),
            hoverinfo="skip", showlegend=False))
        pyfig.update_xaxes(title="Pythagorean (expected) wins →")
        pyfig.update_yaxes(title="Actual wins →")
        _style(pyfig, 480)
        st.plotly_chart(pyfig, width="stretch", key="lab_pyth_scatter")

        c1, c2 = st.columns(2)
        ranked = sorted(fids, key=lambda t: form_stats[t]["Luck_wins"])
        with c1:
            st.markdown("🍀 **Luckiest** — most wins above expectation")
            top = list(reversed(ranked[-10:]))
            lf = go.Figure(go.Bar(
                y=[name_of.get(t, str(t)) for t in top][::-1],
                x=[form_stats[t]["Luck_wins"] for t in top][::-1],
                orientation="h", marker_color=GOOD, marker_line_width=0,
                text=[f"{form_stats[t]['Luck_wins']:+.1f}" for t in top][::-1],
                textposition="auto"))
            lf.update_xaxes(title="Wins vs expected")
            _style(lf, 360)
            st.plotly_chart(lf, width="stretch", key="lab_lucky")
        with c2:
            st.markdown("💀 **Unluckiest** — most wins below expectation")
            bot = ranked[:10]
            uf = go.Figure(go.Bar(
                y=[name_of.get(t, str(t)) for t in bot][::-1],
                x=[form_stats[t]["Luck_wins"] for t in bot][::-1],
                orientation="h", marker_color=BAD, marker_line_width=0,
                text=[f"{form_stats[t]['Luck_wins']:+.1f}" for t in bot][::-1],
                textposition="auto"))
            uf.update_xaxes(title="Wins vs expected")
            _style(uf, 360)
            st.plotly_chart(uf, width="stretch", key="lab_unlucky")

    # ──────────────────────────────────────────────────────────────────────
    #  MOMENTUM
    # ──────────────────────────────────────────────────────────────────────
    with lab_mo:
        _lab_hdr("Momentum — recent form vs season")
        st.caption("**mom_delta** = last-5-game average margin minus season "
                   "average margin. Positive = heating up.")
        fids = [t for t in form_stats if form_stats[t]["games"] >= 3]
        ranked = sorted(fids, key=lambda t: form_stats[t]["mom_delta"])
        # show all teams when the field is small, else the 12 coldest + 12 hottest
        if len(fids) > 24:
            show = ranked[:12] + ranked[-12:]
        else:
            show = ranked
        vals = [form_stats[t]["mom_delta"] for t in show]
        mof = go.Figure(go.Bar(
            x=[name_of.get(t, str(t)) for t in show], y=vals,
            marker_color=[GOOD if v >= 0 else BAD for v in vals],
            marker_line_width=0,
            text=[f"{v:+.1f}" for v in vals], textposition="outside"))
        mof.add_hline(y=0, line=dict(color="#30363d"))
        mof.update_yaxes(title="Last-5 MOV − season MOV")
        mof.update_xaxes(tickangle=-45)
        _style(mof, 420)
        st.plotly_chart(mof, width="stretch", key="lab_momentum")

        st.markdown("**Trajectory** — season margin vs last-5 margin")
        st.caption("Above the line = playing better than their season; below = "
                   "cooling off.")
        sx = [form_stats[t]["MOV"] for t in fids]
        sy = [form_stats[t]["l5_mov"] for t in fids]
        traj = go.Figure(go.Scatter(
            x=sx, y=sy, mode="markers",
            marker=dict(size=9, color=[form_stats[t]["mom_delta"] for t in fids],
                        colorscale="RdYlGn", cmid=0, showscale=True,
                        colorbar=dict(title="Δ", thickness=12),
                        line=dict(width=0.5, color="#0d1117")),
            text=[name_of.get(t, str(t)) for t in fids],
            hovertemplate="%{text}<br>Season %{x:+.1f} · Last-5 %{y:+.1f}"
                          "<extra></extra>"))
        lo = min(sx + sy + [0]) - 2
        hh = max(sx + sy + [0]) + 2
        traj.add_trace(go.Scatter(x=[lo, hh], y=[lo, hh], mode="lines",
                                  line=dict(color=GREY, dash="dot"),
                                  hoverinfo="skip", showlegend=False))
        traj.update_xaxes(title="Season margin / game →")
        traj.update_yaxes(title="Last-5 margin / game →")
        _style(traj, 460)
        st.plotly_chart(traj, width="stretch", key="lab_traj")

    # ──────────────────────────────────────────────────────────────────────
    #  WIN NETWORK
    # ──────────────────────────────────────────────────────────────────────
    with lab_net:
        _lab_hdr("Win network — who beat whom")
        st.caption("Each arrow-free link is a head-to-head result; teams sit on "
                   "the ring by rank. Node size = games, color = Power. Filter to "
                   "keep it readable.")
        net = _win_net(gender, scored)
        classes = sorted({n["class"] for n in net["nodes"]},
                         key=lambda c: TR._CLASS_RANK.get(c, 99))
        fc1, fc2 = st.columns([2, 1])
        topn = fc1.slider("Show top-N teams (by rank)", 6,
                          min(40, len(net["nodes"])),
                          min(20, len(net["nodes"])), key="lab_net_n")
        pick_cls = fc2.multiselect("Limit to classes", classes, default=[],
                                   key="lab_net_cls")
        nodes = net["nodes"]
        if pick_cls:
            nodes = [n for n in nodes if n["class"] in pick_cls]
        nodes = sorted(nodes, key=lambda n: n["rank"])[:topn]
        keep = {n["id"] for n in nodes}
        if len(nodes) >= 2:
            n_n = len(nodes)
            pos = {}
            for i, n in enumerate(nodes):
                ang = 2 * math.pi * i / n_n
                pos[n["id"]] = (math.cos(ang), math.sin(ang))
            ex, ey = [], []
            for e in net["edges"]:
                if e["winner"] in keep and e["loser"] in keep:
                    x0, y0 = pos[e["winner"]]
                    x1, y1 = pos[e["loser"]]
                    ex += [x0, x1, None]
                    ey += [y0, y1, None]
            netfig = go.Figure()
            netfig.add_trace(go.Scatter(
                x=ex, y=ey, mode="lines",
                line=dict(color="rgba(88,166,255,0.25)", width=1),
                hoverinfo="skip", showlegend=False))
            nx = [pos[n["id"]][0] for n in nodes]
            ny = [pos[n["id"]][1] for n in nodes]
            netfig.add_trace(go.Scatter(
                x=nx, y=ny, mode="markers+text",
                text=[n["name"] for n in nodes], textposition="top center",
                textfont=dict(size=9),
                marker=dict(size=[max(10, n["degree"] * 1.6) for n in nodes],
                            color=[n["power"] for n in nodes], colorscale="Turbo",
                            cmin=0, cmax=100, showscale=True,
                            colorbar=dict(title="Power", thickness=12),
                            line=dict(width=1, color="#0d1117")),
                customdata=[[n["rank"], n["W"], n["L"]] for n in nodes],
                hovertemplate="<b>%{text}</b><br>#%{customdata[0]} · "
                              "%{customdata[1]}-%{customdata[2]}<extra></extra>",
                showlegend=False))
            netfig.update_layout(
                template="plotly_dark", height=560,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(visible=False), yaxis=dict(visible=False,
                                                      scaleanchor="x"))
            st.plotly_chart(netfig, width="stretch", key="lab_network")
        else:
            st.info("Not enough teams in this filter to draw a network.")

        # biggest upsets — winner Power far below loser Power
        st.markdown("**Biggest upsets** — winners who beat much higher-Power teams")
        rows = LA._finished_rows(gender)
        ups = []
        for g in rows:
            hp, ap = g["home_score"], g["away_score"]
            if hp == ap:
                continue
            win, lose = (g["team1_id"], g["team2_id"]) if hp > ap \
                else (g["team2_id"], g["team1_id"])
            pw_w = scored.get(win, {}).get("Power")
            pw_l = scored.get(lose, {}).get("Power")
            if pw_w is None or pw_l is None:
                continue
            gap = pw_l - pw_w
            if gap > 0:
                ups.append({"Date": g["date"],
                            "Winner": f"#{rank_of.get(win,'—')} {name_of.get(win,'?')}",
                            "Loser": f"#{rank_of.get(lose,'—')} {name_of.get(lose,'?')}",
                            "Score": f"{max(hp,ap)}-{min(hp,ap)}",
                            "Power gap": round(gap, 1)})
        ups.sort(key=lambda r: r["Power gap"], reverse=True)
        if ups:
            st.dataframe(pd.DataFrame(ups[:12]), hide_index=True, width="stretch")
        else:
            st.info("No upsets recorded.")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — STAT LAB  (configurable, hyper-dense stat exploration)
# ══════════════════════════════════════════════════════════════════════════════
with tab_stat:
    st.caption("Every tracked and derived stat, cross-team. Build your own views: "
               "a z-score heatmap, correlations, a free scatter explorer, parallel "
               "coordinates, a scatter matrix, per-team percentile profiles, and "
               "the full data matrix.")

    ts = pack["ts"]
    pteams = pack["teams"]

    # ── stat catalog (label, higher_better, format) by group ─────────────────
    RESULT_GROUPS = [
        ("Power & résumé", [
            ("Power", "Power", True, "{:.1f}"), ("Rating", "Rating", True, "{:.2f}"),
            ("MOV", "Margin/g", True, "{:+.1f}"), ("AdjNet", "Adj net", True, "{:.2f}"),
            ("SOS", "SOS", True, "{:.2f}"), ("SOR", "SOR", True, "{:.2f}"),
            ("Dominance", "Dominance", True, "{:.0f}"),
            ("Consistency", "Consistency", True, "{:.0f}"),
            ("Clutch", "Clutch", True, "{:.0f}"),
            ("Momentum", "Momentum", True, "{:.0f}"),
            ("Volatility", "Volatility", False, "{:.1f}"),
            ("Luck", "Luck (W)", True, "{:+.1f}"),
            ("PythW", "Pythag W", True, "{:.1f}")]),
        ("Scoring", [
            ("PPG", "PPG", True, "{:.1f}"), ("oPPG", "Opp PPG", False, "{:.1f}"),
            ("xPPG", "Adj O", True, "{:.1f}"), ("xoPPG", "Adj D", False, "{:.1f}")]),
    ]
    TRACK_GROUPS = [
        ("Efficiency", [
            ("ORtg", "Off rtg", True, "{:.1f}"), ("DRtg", "Def rtg", False, "{:.1f}"),
            ("NetRtg", "Net rtg", True, "{:+.1f}"), ("Pace", "Pace", True, "{:.1f}"),
            ("PPP", "PPP", True, "{:.2f}"), ("oPPP", "Opp PPP", False, "{:.2f}"),
            ("PPS", "Pts/shot", True, "{:.2f}"), ("SCE", "Scoring eff", True, "{:.3f}")]),
        ("Shooting", [
            ("eFG", "eFG%", True, "{:.1f}"), ("oeFG", "Opp eFG%", False, "{:.1f}"),
            ("TS", "TS%", True, "{:.1f}"), ("FGpct", "FG%", True, "{:.1f}"),
            ("oFGpct", "Opp FG%", False, "{:.1f}"), ("TPpct", "3P%", True, "{:.1f}"),
            ("oTPpct", "Opp 3P%", False, "{:.1f}"), ("FTpct", "FT%", True, "{:.1f}"),
            ("TPAr", "3PA rate", True, "{:.1f}"), ("FTr", "FT rate", True, "{:.2f}")]),
        ("Rebounding", [
            ("ORBpct", "OREB%", True, "{:.1f}"), ("DRBpct", "DREB%", True, "{:.1f}"),
            ("REBpct", "REB%", True, "{:.1f}"), ("oreb_pg", "OREB/g", True, "{:.1f}"),
            ("dreb_pg", "DREB/g", True, "{:.1f}"), ("reb_pg", "REB/g", True, "{:.1f}")]),
        ("Ball control & defense", [
            ("ast_pg", "AST/g", True, "{:.1f}"), ("tov_pg", "TOV/g", False, "{:.1f}"),
            ("ast_to", "AST/TO", True, "{:.2f}"), ("Astpct", "AST%", True, "{:.1f}"),
            ("TOVpct", "TOV%", False, "{:.1f}"), ("stl_pg", "STL/g", True, "{:.1f}"),
            ("blk_pg", "BLK/g", True, "{:.1f}"),
            ("stocks_pg", "Stocks/g", True, "{:.1f}"),
            ("stl_r", "STL/100", True, "{:.1f}"), ("blk_r", "BLK/100", True, "{:.1f}"),
            ("pf_pg", "Fouls/g", False, "{:.1f}")]),
        ("Style & volume", [
            ("paint_pg", "Paint pts/g", True, "{:.1f}"),
            ("paint_share", "Paint %", True, "{:.1f}"),
            ("three_share", "3PT %", True, "{:.1f}"),
            ("ft_share", "FT %", True, "{:.1f}"), ("fga_pg", "FGA/g", True, "{:.1f}"),
            ("tpa_pg", "3PA/g", True, "{:.1f}"), ("poss_pg", "Poss/g", True, "{:.1f}")]),
    ]
    PCT100 = {"Power", "Dominance", "Consistency", "Clutch", "Momentum"}
    META = {k: (lbl, hib, fmt) for grp in RESULT_GROUPS + TRACK_GROUPS
            for k, lbl, hib, fmt in grp[1]}

    # ── per-team matrix (results-only + tracked) ─────────────────────────────
    matrix = {}
    for t, s in scored.items():
        f = form_stats.get(t, {})
        d = {"name": s["name"], "class": s["class"], "rank": s["Rank"],
             "Power": s["Power"], "Rating": s["Rating"], "GP": s["GP"],
             "PPG": s["PPG"], "oPPG": s["oPPG"], "MOV": s["MOV"],
             "xPPG": s["xPPG"], "xoPPG": s["xoPPG"], "AdjNet": s["AdjNet"],
             "SOS": s["SOS"], "SOR": s["SOR"],
             "Dominance": f.get("Dominance"), "Consistency": f.get("Consistency"),
             "Clutch": f.get("Clutch"), "Momentum": f.get("Momentum"),
             "Volatility": f.get("Volatility"), "PythW": f.get("Pyth_W"),
             "Luck": f.get("Luck_wins")}
        tt = ts.get(t)
        for k in META:
            if k not in d:
                d[k] = tt.get(k) if tt else None
        matrix[t] = d

    def _plane(plane):
        """(groups, tids) for the chosen data plane."""
        if plane.startswith("Tracked") and pteams:
            return RESULT_GROUPS + TRACK_GROUPS, list(pteams)
        return RESULT_GROUPS, sorted(scored, key=lambda t: scored[t]["Rank"])

    def _flat(groups):
        return [(k, lbl, hib, fmt) for _, items in groups
                for k, lbl, hib, fmt in items]

    plane_opts = (["Tracked (deep stats)", "Results (all teams)"] if pteams
                  else ["Results (all teams)"])

    sl_heat, sl_corr, sl_scatter, sl_par, sl_prof, sl_table = st.tabs(
        ["🔥 Z-score heatmap", "🔗 Correlations", "🎛 Scatter explorer",
         "📐 Parallel / matrix", "🧬 Team profile", "🗃 Data matrix"])

    # ──────────────────────────────────────────────────────────────────────
    #  Z-SCORE HEATMAP
    # ──────────────────────────────────────────────────────────────────────
    with sl_heat:
        _lab_hdr("Z-score heatmap — teams × stats")
        st.caption("Each cell is standard deviations from the league mean, "
                   "oriented so green = good / red = bad (defensive & turnover "
                   "stats auto-flipped). The densest single view of the league.")
        plane = st.radio("Data plane", plane_opts, horizontal=True, key="heat_plane")
        groups, tids = _plane(plane)
        flat = _flat(groups)
        default_keys = [k for k, *_ in flat][:14]
        sel = st.multiselect(
            "Stats (columns)", [k for k, *_ in flat],
            default=default_keys,
            format_func=lambda k: META[k][0], key="heat_stats")
        maxn = len(tids)
        topn = st.slider("Teams (rows, by rank)", 5, maxn, min(24, maxn),
                         key="heat_n") if maxn > 5 else maxn
        tids_show = tids[:topn]
        if not sel or len(tids_show) < 2:
            st.info("Pick at least one stat and two teams.")
        else:
            stat_stats = {}
            for k in sel:
                vals = [matrix[t][k] for t in tids_show if matrix[t][k] is not None]
                stat_stats[k] = (float(np.mean(vals)), float(np.std(vals))) \
                    if len(vals) >= 2 else None
            z, hov = [], []
            for t in tids_show:
                zr, hr = [], []
                for k in sel:
                    v = matrix[t][k]
                    ms = stat_stats[k]
                    if v is None or ms is None or ms[1] == 0:
                        zr.append(None)
                        hr.append("—")
                    else:
                        zz = (v - ms[0]) / ms[1]
                        if not META[k][1]:
                            zz = -zz
                        zr.append(round(zz, 2))
                        hr.append(META[k][2].format(v))
                z.append(zr)
                hov.append(hr)
            heat = go.Figure(go.Heatmap(
                z=z, x=[META[k][0] for k in sel],
                y=[matrix[t]["name"] for t in tids_show],
                customdata=hov, colorscale="RdYlGn", zmid=0, zmin=-2.5, zmax=2.5,
                colorbar=dict(title="z", thickness=12),
                hovertemplate="<b>%{y}</b><br>%{x}: %{customdata} "
                              "(z %{z})<extra></extra>"))
            heat.update_layout(
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                height=max(360, 22 * len(tids_show) + 120),
                margin=dict(l=8, r=8, t=10, b=40),
                xaxis=dict(side="top", tickangle=-40, tickfont=dict(size=10)),
                yaxis=dict(autorange="reversed", tickfont=dict(size=10)))
            st.plotly_chart(heat, width="stretch", key="stat_heat")

    # ──────────────────────────────────────────────────────────────────────
    #  CORRELATIONS
    # ──────────────────────────────────────────────────────────────────────
    with sl_corr:
        _lab_hdr("Stat correlation matrix")
        st.caption("Pearson correlation between stats across teams — what tends to "
                   "travel together. Pick a focused set for a readable grid.")
        plane = st.radio("Data plane", plane_opts, horizontal=True, key="corr_plane")
        groups, tids = _plane(plane)
        flat = _flat(groups)
        sel = st.multiselect(
            "Stats", [k for k, *_ in flat],
            default=[k for k, *_ in flat][:10],
            format_func=lambda k: META[k][0], key="corr_stats")
        if len(sel) < 2:
            st.info("Pick at least two stats.")
        else:
            data = []
            for t in tids:
                row = [matrix[t][k] for k in sel]
                if all(v is not None for v in row):
                    data.append(row)
            arr = np.array(data, dtype=float)
            if arr.shape[0] < 3:
                st.info("Not enough teams with all of these stats to correlate.")
            else:
                corr = np.corrcoef(arr, rowvar=False)
                labels = [META[k][0] for k in sel]
                cfig = go.Figure(go.Heatmap(
                    z=corr, x=labels, y=labels, colorscale="RdBu", zmid=0,
                    zmin=-1, zmax=1, colorbar=dict(title="r", thickness=12),
                    text=[[f"{v:.2f}" for v in r] for r in corr],
                    texttemplate="%{text}", textfont=dict(size=9),
                    hovertemplate="%{y} × %{x}: r %{z:.2f}<extra></extra>"))
                cfig.update_layout(
                    template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                    height=max(380, 30 * len(sel) + 140),
                    margin=dict(l=8, r=8, t=10, b=10),
                    xaxis=dict(tickangle=-40, tickfont=dict(size=10)),
                    yaxis=dict(autorange="reversed", tickfont=dict(size=10)))
                st.plotly_chart(cfig, width="stretch", key="stat_corr")
                st.caption(f"Across {arr.shape[0]} teams in the "
                           f"{plane.split(' ')[0].lower()} plane.")

    # ──────────────────────────────────────────────────────────────────────
    #  SCATTER EXPLORER
    # ──────────────────────────────────────────────────────────────────────
    with sl_scatter:
        _lab_hdr("Scatter explorer — plot any stat against any other")
        plane = st.radio("Data plane", plane_opts, horizontal=True, key="sc_plane")
        groups, tids = _plane(plane)
        flat = _flat(groups)
        keys = [k for k, *_ in flat]
        c = st.columns(4)
        xk = c[0].selectbox("X axis", keys, index=0,
                            format_func=lambda k: META[k][0], key="sc_x")
        yk = c[1].selectbox("Y axis", keys,
                            index=min(2, len(keys) - 1),
                            format_func=lambda k: META[k][0], key="sc_y")
        size_opts = ["(uniform)"] + keys
        sk = c[2].selectbox("Bubble size", size_opts,
                            format_func=lambda k: k if k == "(uniform)"
                            else META[k][0], key="sc_size")
        ck = c[3].selectbox("Color", size_opts, index=0,
                            format_func=lambda k: "Power" if k == "(uniform)"
                            else META[k][0], key="sc_color")
        pts = [t for t in tids if matrix[t][xk] is not None
               and matrix[t][yk] is not None]
        if len(pts) < 2:
            st.info("Not enough teams with both stats.")
        else:
            xs = [matrix[t][xk] for t in pts]
            ys = [matrix[t][yk] for t in pts]
            if sk == "(uniform)":
                sizes = [12] * len(pts)
            else:
                sv2 = [matrix[t][sk] for t in pts]
                lo, hi = min(sv2), max(sv2)
                sizes = [10 + 26 * ((v - lo) / (hi - lo) if hi > lo else 0.5)
                         for v in sv2]
            colvals = [matrix[t]["Power"] if ck == "(uniform)"
                       else matrix[t][ck] for t in pts]
            cbar_title = "Power" if ck == "(uniform)" else META[ck][0]
            scx = go.Figure(go.Scatter(
                x=xs, y=ys, mode="markers+text",
                text=[matrix[t]["name"] for t in pts],
                textposition="top center", textfont=dict(size=8),
                marker=dict(size=sizes, color=colvals, colorscale="Turbo",
                            showscale=True,
                            colorbar=dict(title=cbar_title, thickness=12),
                            line=dict(width=0.5, color="#0d1117")),
                hovertemplate="<b>%{text}</b><br>" + META[xk][0] +
                              " %{x}<br>" + META[yk][0] + " %{y}<extra></extra>"))
            scx.add_vline(x=float(np.mean(xs)), line=dict(color="#30363d", dash="dot"))
            scx.add_hline(y=float(np.mean(ys)), line=dict(color="#30363d", dash="dot"))
            # OLS trend line
            if len(pts) >= 3:
                m, b = np.polyfit(xs, ys, 1)
                xr = [min(xs), max(xs)]
                scx.add_trace(go.Scatter(
                    x=xr, y=[m * v + b for v in xr], mode="lines",
                    line=dict(color=CYBER, dash="dash", width=1.5),
                    name="trend", hoverinfo="skip"))
                r = float(np.corrcoef(xs, ys)[0, 1])
            else:
                r = float("nan")
            invx = not META[xk][1]
            invy = not META[yk][1]
            scx.update_xaxes(title=META[xk][0] + (" (lower=better)" if invx else ""),
                             autorange="reversed" if invx else None)
            scx.update_yaxes(title=META[yk][0] + (" (lower=better)" if invy else ""),
                             autorange="reversed" if invy else None)
            _style(scx, 520)
            st.plotly_chart(scx, width="stretch", key="stat_scatter")
            if r == r:  # not NaN
                st.caption(f"Correlation r = {r:+.2f} across {len(pts)} teams.")

    # ──────────────────────────────────────────────────────────────────────
    #  PARALLEL COORDINATES + SCATTER MATRIX
    # ──────────────────────────────────────────────────────────────────────
    with sl_par:
        _lab_hdr("Parallel coordinates")
        st.caption("Every team is one line threading all the axes — drag along an "
                   "axis to brush a range and isolate team types. Colored by Power.")
        plane = st.radio("Data plane", plane_opts, horizontal=True, key="par_plane")
        groups, tids = _plane(plane)
        flat = _flat(groups)
        keys = [k for k, *_ in flat]
        sel = st.multiselect(
            "Axes", keys, default=keys[:6] if len(keys) >= 6 else keys,
            format_func=lambda k: META[k][0], key="par_stats")
        pts = [t for t in tids
               if all(matrix[t][k] is not None for k in sel)] if sel else []
        if len(sel) < 2 or len(pts) < 3:
            st.info("Pick at least two axes (teams need all of them tracked).")
        else:
            dims = []
            for k in sel:
                vals = [matrix[t][k] for t in pts]
                dims.append(dict(label=META[k][0], values=vals,
                                 range=[min(vals), max(vals)]))
            powers = [matrix[t]["Power"] for t in pts]
            par = go.Figure(go.Parcoords(
                line=dict(color=powers, colorscale="Turbo", cmin=0, cmax=100,
                          showscale=True, colorbar=dict(title="Power", thickness=12)),
                dimensions=dims))
            par.update_layout(template="plotly_dark",
                              paper_bgcolor="rgba(0,0,0,0)", height=460,
                              margin=dict(l=70, r=40, t=40, b=30),
                              font=dict(color="#c9d1d9", size=11))
            st.plotly_chart(par, width="stretch", key="stat_parcoords")

        _lab_hdr("Scatter matrix (SPLOM)")
        st.caption("Pairwise relationships among a handful of stats at once.")
        sel2 = st.multiselect(
            "Stats (3-5 best)", keys,
            default=[k for k in ("Power", "MOV", "SOS") if k in keys][:3] or keys[:3],
            format_func=lambda k: META[k][0], key="splom_stats")
        pts2 = [t for t in tids
                if all(matrix[t][k] is not None for k in sel2)] if sel2 else []
        if 2 <= len(sel2) <= 6 and len(pts2) >= 3:
            sp = go.Figure(go.Splom(
                dimensions=[dict(label=META[k][0], values=[matrix[t][k] for t in pts2])
                            for k in sel2],
                text=[matrix[t]["name"] for t in pts2],
                marker=dict(size=5, color=[matrix[t]["Power"] for t in pts2],
                            colorscale="Turbo", cmin=0, cmax=100, showscale=False,
                            line=dict(width=0.3, color="#0d1117")),
                diagonal=dict(visible=False)))
            sp.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                             height=560, margin=dict(l=10, r=10, t=10, b=10),
                             font=dict(color="#c9d1d9", size=9))
            st.plotly_chart(sp, width="stretch", key="stat_splom")
        else:
            st.info("Pick 2-6 stats (teams need all of them) for the matrix.")

    # ──────────────────────────────────────────────────────────────────────
    #  TEAM PROFILE  (percentile bars across everything)
    # ──────────────────────────────────────────────────────────────────────
    with sl_prof:
        _lab_hdr("Team percentile profile")
        st.caption("One team versus the whole field on every stat, as percentile "
                   "bars (green = top of the league). Tracked stats appear when "
                   "the team has tracked games.")
        order = sorted(scored, key=lambda t: scored[t]["Rank"])
        pteam = st.selectbox(
            "Team", order,
            format_func=lambda t: f"#{scored[t]['Rank']} {name_of[t]} ({class_of[t]})",
            key="prof_team")
        is_tracked = pteam in pteams
        res_pool_tids = order
        trk_pool_tids = list(pteams)
        groups = RESULT_GROUPS + (TRACK_GROUPS if is_tracked else [])
        for gname, items in groups:
            is_trk = gname not in [g[0] for g in RESULT_GROUPS]
            pool_tids = trk_pool_tids if is_trk else res_pool_tids
            st.markdown(f"**{gname}**")
            cols = st.columns(2)
            for i, (k, lbl, hib, fmt) in enumerate(items):
                val = matrix[pteam].get(k)
                pool = [matrix[t][k] for t in pool_tids]
                pct = LA.percentile(val, pool, higher_better=hib)
                txt = "—" if val is None else fmt.format(val)
                cols[i % 2].markdown(_pctile_bar(lbl, txt, pct),
                                     unsafe_allow_html=True)
        if not is_tracked:
            st.info("Track this team's games to add the possession-based stat "
                    "groups (efficiency, shooting, rebounding, defense, style).")

    # ──────────────────────────────────────────────────────────────────────
    #  DATA MATRIX  (the whole thing, sortable, downloadable)
    # ──────────────────────────────────────────────────────────────────────
    with sl_table:
        _lab_hdr("Full data matrix")
        st.caption("Every team, every stat, in one sortable table. Tracked-only "
                   "stats are blank for untracked teams. Download the lot as CSV.")
        cols_order = ["rank", "name", "class", "Power"]
        seen = set(cols_order)
        for _, items in RESULT_GROUPS + TRACK_GROUPS:
            for k, *_ in items:
                if k not in seen:
                    cols_order.append(k)
                    seen.add(k)
        recs = []
        for t in sorted(scored, key=lambda t: scored[t]["Rank"]):
            row = {"rank": matrix[t]["rank"], "name": matrix[t]["name"],
                   "class": matrix[t]["class"]}
            for k in cols_order[3:]:
                row[k] = matrix[t].get(k)
            recs.append(row)
        mdf = pd.DataFrame(recs).rename(
            columns={"rank": "Rank", "name": "Team", "class": "Class",
                     **{k: META[k][0] for k in META}})
        colcfg = {META[k][0]: st.column_config.ProgressColumn(
            META[k][0], format="%.0f", min_value=0, max_value=100)
            for k in PCT100}
        st.dataframe(mdf, hide_index=True, width="stretch",
                     height=min(720, 60 + 32 * len(mdf)), column_config=colcfg)
        st.download_button("⬇ Full data matrix (CSV)", mdf.to_csv(index=False),
                           file_name=f"stat_matrix_{gender}.csv", mime="text/csv",
                           key="dl_matrix")


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 6 — MATCHUP PREDICTOR  (Vegas style)
# ══════════════════════════════════════════════════════════════════════════════
with tab_pred:
    st.caption("Pick two teams and the model projects a Vegas-style line from the "
               "ratings — point spread, projected score, total and win probability.")

    src = st.radio(
        "Ratings source", ["Scored (all teams)", "Tracked (advanced)"],
        horizontal=True,
        help="Scored uses results-only ratings for every team. Tracked uses "
             "possession-based ratings — only teams with tracked games.")
    R = scored if src.startswith("Scored") else tracked
    if not R:
        st.info("No ratings available for this source yet.")
        st.stop()

    pool = sorted(R.keys(), key=lambda t: R[t]["Rank"])
    fmt = lambda t: f"#{R[t]['Rank']}  {R[t]['name']}  ({R[t]['class']})"
    c1, c2, c3 = st.columns([2, 2, 1.4])
    a = c1.selectbox("Team A", pool, index=0, format_func=fmt, key="pa")
    b = c2.selectbox("Team B", pool, index=min(1, len(pool) - 1),
                     format_func=fmt, key="pb")
    site = c3.selectbox("Home court", ["Neutral", "Team A", "Team B"], key="psite")

    if a == b:
        st.warning("Pick two different teams.")
        st.stop()

    home = a if site == "Team A" else b if site == "Team B" else None
    hca = TR.DEFAULT_HCA

    # projected score from the (adjusted) ratings
    if src.startswith("Scored"):
        ra, rb = scored[a], scored[b]
        a_pts = (ra["xPPG"] + rb["xoPPG"]) / 2
        b_pts = (rb["xPPG"] + ra["xoPPG"]) / 2
    else:
        ra, rb = tracked[a], tracked[b]
        poss = (ra["Pace"] + rb["Pace"]) / 2
        a_pts = (ra["ORtg"] + rb["DRtg"]) / 2 / 100 * poss
        b_pts = (rb["ORtg"] + ra["DRtg"]) / 2 / 100 * poss

    if home == a:
        a_pts += hca / 2; b_pts -= hca / 2
    elif home == b:
        b_pts += hca / 2; a_pts -= hca / 2

    margin = a_pts - b_pts                       # + => A favored
    total = a_pts + b_pts
    fav, dog = (a, b) if margin >= 0 else (b, a)
    line = abs(margin)
    # win probability: margin under a ~11-pt game-to-game std dev
    win_p = _norm_cdf(line, 0.0, 11.0)

    def _hero_block(t, pts):
        won = (t == fav)
        clr = ACCENT if won else "#555d68"
        tag = "▸ " if won else ""
        homemark = " 🏠" if home == t else ""
        return (
            f"<div style='text-align:center'>"
            f"<div style='font-size:15px;font-weight:700;color:#c9d1d9'>"
            f"{tag}{R[t]['name']}{homemark}</div>"
            f"<div style='font-size:11px;color:#8b949e'>#{R[t]['Rank']} · "
            f"{R[t]['class']}</div>"
            f"<div style='font-size:46px;font-weight:900;color:{clr};"
            f"line-height:1.1'>{pts:.0f}</div></div>")

    st.markdown(
        f"<div class='game-hero'><table style='width:100%;border:none'><tr>"
        f"<td style='width:42%'>{_hero_block(a, a_pts)}</td>"
        f"<td style='width:16%;text-align:center;color:#8b949e;font-size:18px'>vs</td>"
        f"<td style='width:42%'>{_hero_block(b, b_pts)}</td>"
        f"</tr></table></div>", unsafe_allow_html=True)

    m = st.columns(4)
    m[0].metric("Spread", f"{R[fav]['name']} −{line:.1f}")
    m[1].metric("Projected total", f"{total:.0f}")
    m[2].metric(f"{R[fav]['name']} win prob", f"{100*win_p:.0f}%")
    # confidence band off the win prob
    conf = ("Toss-up" if win_p < 0.58 else "Lean" if win_p < 0.68
            else "Solid" if win_p < 0.80 else "Strong")
    m[3].metric("Confidence", conf)

    st.caption(
        f"Neutral-floor projection with a {hca:.0f}-pt home-court edge "
        f"({'applied to ' + R[home]['name'] if home else 'neutral site'}). "
        "Win probability assumes an ~11-point game-to-game standard deviation. "
        + ("Tracked ratings come from a small, sparsely-connected sample — "
           "directional only." if not src.startswith("Scored") else
           "Scored ratings cover every team from results alone."))

    # ── win-probability split bar ────────────────────────────────────────────
    pa = win_p if fav == a else 1 - win_p
    pb = 1 - pa
    st.markdown(
        f"<div style='background:#2d333b;border-radius:6px;height:26px;"
        f"overflow:hidden;display:flex'>"
        f"<div style='background:{ACCENT};width:{pa*100:.0f}%;height:100%;"
        f"display:flex;align-items:center;justify-content:center;font-size:12px;"
        f"font-weight:700;color:#000'>"
        f"{str(round(pa*100)) + '%' if pa > 0.12 else ''}</div>"
        f"<div style='background:{AWAY};width:{pb*100:.0f}%;height:100%;"
        f"display:flex;align-items:center;justify-content:center;font-size:12px;"
        f"font-weight:700;color:#fff'>"
        f"{str(round(pb*100)) + '%' if pb > 0.12 else ''}</div></div>"
        f"<div style='display:flex;justify-content:space-between;font-size:12px;"
        f"margin-top:4px'><span style='color:{ACCENT};font-weight:700'>"
        f"{R[a]['name']}</span><span style='color:{AWAY};font-weight:700'>"
        f"{R[b]['name']}</span></div>", unsafe_allow_html=True)

    # ── side-by-side comparison table (✅ marks the better side) ──────────────
    st.markdown("#### Side-by-side")
    cmp_spec = [("Rank", "Power rank", False), ("Power", "Power", True),
                ("PPG", "Points / game", True), ("oPPG", "Opp PPG", False),
                ("MOV", "Point margin", True), ("SOS", "Strength of schedule", True),
                ("SOR", "Strength of record", True)]
    if not src.startswith("Scored"):
        cmp_spec += [("ORtg", "Off. rating", True), ("DRtg", "Def. rating", False),
                     ("NetRtg", "Net rating", True), ("Pace", "Pace", True),
                     ("eFG", "eFG%", True), ("TPpct", "3P%", True)]
    cmp_rows = []
    for key, label, hib in cmp_spec:
        if key not in R[a] or key not in R[b]:
            continue
        va, vb = R[a][key], R[b][key]
        a_better = va >= vb if hib else va <= vb
        cmp_rows.append({
            R[a]["name"]: f"{'✅ ' if a_better else ''}{va}",
            "Stat": label,
            R[b]["name"]: f"{'✅ ' if not a_better else ''}{vb}"})
    if cmp_rows:
        st.dataframe(pd.DataFrame(cmp_rows).set_index("Stat"),
                     width="stretch")

    # ── head-to-head history ─────────────────────────────────────────────────
    st.markdown("#### Head-to-head history")
    h2h = query(
        """SELECT g.id, g.date, g.home_score, g.away_score, g.tracked,
                  g.team1_id, g.team2_id
           FROM games g
           WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL
             AND ((g.team1_id=? AND g.team2_id=?) OR (g.team1_id=? AND g.team2_id=?))
           ORDER BY g.date DESC""", (a, b, b, a))
    if not h2h:
        st.info("These teams have not played each other yet.")
    else:
        a_w = sum(1 for g in h2h if
                  (g["team1_id"] == a and g["home_score"] > g["away_score"]) or
                  (g["team2_id"] == a and g["away_score"] > g["home_score"]))
        hh = st.columns(2)
        hh[0].metric(f"{R[a]['name']} wins", a_w)
        hh[1].metric(f"{R[b]['name']} wins", len(h2h) - a_w)
        for g in h2h:
            if g["team1_id"] == a:
                ap, bp = g["home_score"], g["away_score"]
            else:
                ap, bp = g["away_score"], g["home_score"]
            a_win = ap > bp
            tr = " · ●" if g["tracked"] else ""
            st.markdown(
                f"<div class='score-card'>"
                f"<span style='color:#8b949e;font-size:11px'>{g['date']}{tr}</span> "
                f"<span style='color:{ACCENT if a_win else '#8b949e'};font-weight:700'>"
                f"{R[a]['name']} {ap}</span> – "
                f"<span style='color:{AWAY if not a_win else '#8b949e'};font-weight:700'>"
                f"{R[b]['name']} {bp}</span></div>", unsafe_allow_html=True)
            if g["tracked"]:
                with st.expander("Box score"):
                    render_box_score(g["id"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 7 — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
with tab_gloss:
    st.markdown("<div class='lab-hdr'>League & team stat glossary</div>",
                unsafe_allow_html=True)
    render_glossary(
        key_prefix="rank_gloss",
        categories=["Team & League", "Possession & Pace", "Shooting"],
        intro="Every rating, power and league metric on this page — including the "
              "signature invented stats (Dominance, Consistency, Clutch, Momentum, "
              "Luck). Search by name or filter by category.")
