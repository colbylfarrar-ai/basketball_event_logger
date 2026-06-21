"""
13_Insights.py — Insights Lab: the scout that reads itself.

The "think like a data scientist" surface. It mines every tracked split for the
non-obvious reads box scores hide and presents them as plain-English scouting:
  • Auto-Scout   — each player's most surprising true fact (helpers/insights.py)
  • Shot Quality — selection (xPPS) vs making (PPS−xPPS) on a 2×2
  • Scouting boards — force-to-off-hand + guarded-vs-open "space dependence"
  • Roles & sets — pick-&-roll ball-handler vs roll-man (lights up as games are
    tagged with play_type)

Display-only; every number comes from the Streamlit-free engine. Event-derived,
so it sits behind the Paid gate like the other tracked analytics.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from helpers.ui import (page_chrome, lab_hero as _lab_hero, gender_radio,
                        style_fig as _style, empty_state, mini_tile as _mini,
                        chip as _chip)
import helpers.player_ratings as PR
import helpers.stats as S
import helpers.insights as IN
import helpers.playtypes as PT
import helpers.wpa as WPA
import helpers.cards as C
import helpers.auth as AUTH
import helpers.entitlement as ENT

_cfg, ACCENT = page_chrome("Insights")

_lab_hero("Insights Lab", phase="ANALYZE",
          sub="The scout that reads itself — what the tracked data says about every "
              "player that box scores hide.")

gender = gender_radio()
_paid = ENT.has_paid_plan(AUTH.current_user())
if not _paid:
    st.info("🔒 **Insights are a Paid feature.** Auto-scouting, shot quality, "
            "hand-side and contest splits all come from tracked play-by-play.")
    st.stop()


# ── cached data bundle ────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _bundle(g):
    table = PR.player_stat_table(gender=g, min_games=1)
    gids = PT._tracked_game_ids(g)
    events = S.fetch_events(gids) if gids else []
    feed = IN.build_feed(table, events, top=3) if table else {}
    roles = PT.player_role_splits(events=events) if events else {}
    try:
        impact = WPA.season_wpa(g, mode="possession")
    except Exception:
        impact = {}
    return {"table": table, "feed": feed, "roles": roles, "impact": impact,
            "n_events": len(events)}


with st.spinner("Reading the game…"):
    D = _bundle(gender)
table = D["table"]
if not table:
    empty_state("No tracked players yet",
                "Track a game in the Game Tracker and the insights light up here.",
                cta="Open the Game Tracker", page="pages/2_Game_Tracker.py")
    st.stop()

feed = D["feed"]
_names = {pid: f"{r['name']} · {r.get('team','')}" for pid, r in table.items()}


def _b(t):
    """Markdown **bold** → <b> for injection inside raw-HTML cards (st.markdown
    doesn't process markdown inside an HTML block)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)

tab_scout, tab_quality, tab_board, tab_impact, tab_roles = st.tabs(
    ["🔎 Auto-Scout", "🎯 Shot Quality", "🧭 Scouting Boards", "🛡️ Win Impact",
     "⚙️ Roles & Sets"])

# ══════════════════════════════════════════════════════════════════════════════
#  AUTO-SCOUT — the feed
# ══════════════════════════════════════════════════════════════════════════════
with tab_scout:
    st.caption("Every line is the player's biggest deviation from the league, "
               "gated by sample size so a hot night never headlines. The number "
               "in each line is real; trust the ones with bigger samples.")

    # ── league snapshot — quick KPI tiles ─────────────────────────────────────
    _snap = st.columns(4)
    _poe_lead = max(((r["PPS"] - r["xPPS"], r["name"]) for r in table.values()
                     if r.get("PPS") is not None and r.get("xPPS") is not None
                     and (r.get("FGA") or 0) >= 20), default=None)
    _hand_lead = max(((r["Dom_FG%"] - r["Weak_FG%"], r["name"])
                      for r in table.values()
                      if r.get("Dom_FG%") is not None and r.get("Weak_FG%") is not None
                      and (r.get("Dom_FGA") or 0) >= 6 and (r.get("Weak_FGA") or 0) >= 6),
                     default=None)
    _def_lead = min(((r["DSHOT%"], r["name"]) for r in table.values()
                     if r.get("DSHOT%") is not None and (r.get("GP") or 0) >= 4),
                    default=None)
    _avg_q = [r["ShotRating"] for r in table.values()
              if r.get("ShotRating") is not None and (r.get("FGA") or 0) >= 15]
    if _poe_lead:
        _snap[0].metric("Top shot-maker", _poe_lead[1].split()[-1],
                        f"{_poe_lead[0]:+.2f} pts/shot", delta_color="off")
    if _hand_lead:
        _snap[1].metric("Most one-handed", _hand_lead[1].split()[-1],
                        f"+{_hand_lead[0]:.0f} FG% gap", delta_color="off")
    if _def_lead:
        _snap[2].metric("Best on-ball D", _def_lead[1].split()[-1],
                        f"{_def_lead[0]:.0f}% allowed", delta_color="off")
    if _avg_q:
        _snap[3].metric("League shot quality", f"{sum(_avg_q) / len(_avg_q):.0f}")

    # league board — biggest single signals across all players
    flat = []
    for pid, lines in feed.items():
        for ln in lines:
            flat.append((abs(ln["z"]), pid, ln))
    flat.sort(key=lambda t: -t[0])

    st.markdown("<div class='lab-hdr'>Biggest signals in the league</div>",
                unsafe_allow_html=True)
    if not flat:
        st.caption("Not enough tracked volume yet for league-wide signals — "
                   "they sharpen with every game.")
    else:
        for _, pid, ln in flat[:8]:
            nm = table[pid]["name"]
            st.markdown(
                f"<div class='gloss-card' style='border-left-color:var(--accent)'>"
                f"<b>{nm}</b> &nbsp;<span class='badge'>{ln['metric']}</span> "
                f"<span style='color:var(--subtext);font-size:11px'>n={ln['n']}</span>"
                f"<div style='margin-top:4px'>{_b(ln['text'])}</div></div>",
                unsafe_allow_html=True)

    st.markdown("<div class='lab-hdr'>Scout a player</div>", unsafe_allow_html=True)
    order = sorted(table.keys(),
                   key=lambda p: -(table[p].get("OVERALL") or 0))
    pick = st.selectbox("Player", order, format_func=lambda p: _names[p],
                        key="ins_pick")
    lines = feed.get(pick, [])
    r = table[pick]
    chips = []
    if r.get("PPG") is not None:
        chips.append(f"{r['PPG']:.1f} PPG")
    if r.get("OVERALL") is not None:
        chips.append(f"OVR {r['OVERALL']:.0f}")
    if r.get("GP") is not None:
        chips.append(f"{r['GP']} GP")
    st.markdown("".join(_chip(c) for c in chips), unsafe_allow_html=True)
    if not lines:
        st.info("No standout signal yet — this player reads close to league "
                "average on the tracked splits, or hasn't the sample. More games "
                "sharpen it.")
    else:
        for ln in lines:
            st.markdown(
                f"<div class='gloss-card'><span class='badge accent'>{ln['metric']}</span> "
                f"<span style='color:var(--subtext);font-size:11px'>sample {ln['n']}</span>"
                f"<div style='margin-top:5px;font-size:14px'>{_b(ln['text'])}</div></div>",
                unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  SHOT QUALITY — selection (xPPS) vs making (PPS−xPPS)
# ══════════════════════════════════════════════════════════════════════════════
with tab_quality:
    st.caption("Splits **shot SELECTION** (the quality of looks chosen, x-axis) "
               "from **shot MAKING** (points per shot over what those looks are "
               "worth, y-axis). FG% blurs the two; this separates a gunner from a "
               "player taking great shots who's just due to bounce back.")
    qrows = []
    for pid, row in table.items():
        sr, pps, xpps = row.get("ShotRating"), row.get("PPS"), row.get("xPPS")
        fga = row.get("FGA") or 0
        if sr is None or pps is None or xpps is None or fga < 15:
            continue
        qrows.append({"pid": pid, "name": row["name"], "team": row.get("team", ""),
                      "sel": sr, "poe": pps - xpps, "fga": fga,
                      "ovr": row.get("OVERALL") or 50})
    if len(qrows) < 4:
        empty_state("Not enough shot volume yet",
                    "Track more games — the shot-quality map needs a pool of "
                    "shooters to place everyone.", icon="🎯")
    else:
        import statistics as _stt
        mx = _stt.median([q["sel"] for q in qrows])
        my = _stt.median([q["poe"] for q in qrows])
        fig = go.Figure(go.Scatter(
            x=[q["sel"] for q in qrows], y=[q["poe"] for q in qrows],
            mode="markers+text",
            text=[q["name"].split()[-1] for q in qrows], textposition="top center",
            textfont=dict(size=9, color="#c9d1d9"),
            marker=dict(size=[max(9, min(34, 8 + q["fga"] / 6)) for q in qrows],
                        color=[q["ovr"] for q in qrows], colorscale="YlOrRd",
                        showscale=True, colorbar=dict(title="OVR", thickness=12,
                                                      len=0.6),
                        line=dict(width=1, color="#0d1117")),
            customdata=[(q["fga"],) for q in qrows],
            hovertemplate="%{text}<br>selection %{x:.0f} · making %{y:+.2f} pts/shot"
                          " · %{customdata[0]} FGA<extra></extra>"))
        fig.add_vline(x=mx, line=dict(color="#8b949e", width=1, dash="dot"))
        fig.add_hline(y=my, line=dict(color="#8b949e", width=1, dash="dot"))
        _ax = max(abs(min(q["poe"] for q in qrows)),
                  abs(max(q["poe"] for q in qrows)), 0.2)
        for qx, qy, txt, clr in (
                (0.97, 0.95, "Star — good shots, makes them", "#3fb950"),
                (0.03, 0.95, "Gunner — tough shots, makes them", "#f0a500"),
                (0.97, 0.05, "Reps away — good shots, not falling", "#58a6ff"),
                (0.03, 0.05, "Struggling", "#e74c3c")):
            fig.add_annotation(xref="x domain", yref="y domain", x=qx, y=qy,
                               text=txt, showarrow=False, opacity=0.7,
                               font=dict(size=10, color=clr),
                               xanchor="right" if qx > 0.5 else "left")
        fig.update_xaxes(title="Shot selection (look quality) →")
        fig.update_yaxes(title="Shot making (pts/shot over expected) →")
        _style(fig, 480)
        st.plotly_chart(fig, width="stretch", key="ins_poe")
        qdf = pd.DataFrame([{
            "Player": q["name"], "Team": q["team"], "FGA": q["fga"],
            "Selection": round(q["sel"]), "Over expected (+pts/shot)": round(q["poe"], 2),
        } for q in sorted(qrows, key=lambda q: -q["poe"])])
        st.dataframe(qdf, hide_index=True, width="stretch",
                     column_config={"Over expected (+pts/shot)":
                                    st.column_config.NumberColumn(format="%+.2f")})

# ══════════════════════════════════════════════════════════════════════════════
#  SCOUTING BOARDS — hand-side + guarded-vs-open
# ══════════════════════════════════════════════════════════════════════════════
with tab_board:
    bc1, bc2 = st.columns(2)
    with bc1:
        st.markdown("<div class='lab-hdr'>Force them off their hand</div>",
                    unsafe_allow_html=True)
        st.caption("Dominant vs weak floor-side FG%. Biggest gap = send him to "
                   "his off hand.")
        hb = []
        for pid, row in table.items():
            dom, weak = row.get("Dom_FG%"), row.get("Weak_FG%")
            dfa, wfa = row.get("Dom_FGA") or 0, row.get("Weak_FGA") or 0
            if dom is None or weak is None or dfa < 6 or wfa < 6:
                continue
            hb.append((dom - weak, row["name"], dom, weak, int(dfa + wfa)))
        hb.sort(key=lambda t: -t[0])
        if not hb:
            st.caption("Needs tap-located shots on both sides — fills in as games "
                       "are tagged with the court tap.")
        for gap, nm, dom, weak, n in hb[:10]:
            w = max(2, min(100, dom))
            ww = max(2, min(100, weak))
            st.markdown(
                f"<div style='margin-bottom:8px'><div style='display:flex;"
                f"justify-content:space-between;font-size:12px'><b>{nm}</b>"
                f"<span style='color:var(--accent)'>+{gap:.0f} gap · n={n}</span></div>"
                f"<div style='font-size:10px;color:var(--subtext)'>strong {dom:.0f}% "
                f"· weak {weak:.0f}%</div>"
                f"<div class='pl-pct-track'><div class='pl-pct-fill' style='width:{w}%;"
                f"background:var(--good)'></div></div>"
                f"<div class='pl-pct-track' style='margin-top:2px'><div class='pl-pct-fill'"
                f" style='width:{ww}%;background:var(--bad)'></div></div></div>",
                unsafe_allow_html=True)

    with bc2:
        st.markdown("<div class='lab-hdr'>Space dependence (guarded vs open)</div>",
                    unsafe_allow_html=True)
        st.caption("FG% open minus contested. Big = needs space (close out hard); "
                   "negative = contest-proof (deny the catch).")
        cliffs = IN.guarded_cliffs(S.fetch_events(PT._tracked_game_ids(gender))) \
            if D["n_events"] else {}
        cb = sorted(((v["cliff"], table[pid]["name"], v["n"])
                     for pid, v in cliffs.items() if pid in table),
                    key=lambda t: -t[0])
        if not cb:
            st.caption("Needs more contested shots (guarded_by tag) to rank.")
        for cliff, nm, n in cb[:12]:
            tag = ("needs space" if cliff > 8 else
                   "contest-proof" if cliff < -2 else "neutral")
            clr = ("var(--bad)" if cliff > 8 else
                   "var(--good)" if cliff < -2 else "var(--subtext)")
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"padding:5px 0;border-bottom:1px solid var(--card-border);font-size:12px'>"
                f"<span><b>{nm}</b> <span style='color:var(--subtext);font-size:10px'>"
                f"n={n}</span></span>"
                f"<span style='color:{clr}'>{cliff:+.0f} · {tag}</span></div>",
                unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  WIN IMPACT — possession-mode WPA (who won games on DEFENSE)
# ══════════════════════════════════════════════════════════════════════════════
with tab_impact:
    st.caption("Win Probability Added in **possession mode** — the only metric "
               "that values steals, stops and blocks in WIN terms. **Def WPA** = "
               "wins created on defense; **Clutch** weights high-leverage moments. "
               "Filtered to players with real minutes so two-game cameos don't top "
               "the board.")
    sw = D.get("impact") or {}
    irows = [{"pid": p, **v} for p, v in sw.items()
             if (v.get("games") or 0) >= 4 and p in table]
    if not irows:
        empty_state("Not enough tracked games yet",
                    "Win-impact needs several tracked games to separate signal "
                    "from noise.", icon="🛡️")
    else:
        irows.sort(key=lambda r: -(r.get("def_wpa") or 0))
        top = irows[0]
        st.markdown(
            f"**{top['name']}** won the most games on **defense** — "
            f"**{top.get('def_wpa') or 0:+.2f} Def WPA** across "
            f"{top.get('games')} games (steals, stops & blocks in win terms).")
        idf = pd.DataFrame([{
            "Player": r["name"], "Team": r.get("team", ""), "GP": r.get("games"),
            "Def WPA": round(r.get("def_wpa") or 0, 2),
            "Off WPA": round(r.get("off_wpa") or 0, 2),
            "Clutch WPA": round(r.get("clutch_wpa") or 0, 2),
            "Total / game": round(r.get("wpa_per_game") or 0, 3),
        } for r in irows[:20]])
        st.dataframe(
            idf, hide_index=True, width="stretch",
            column_config={
                "Def WPA": st.column_config.NumberColumn(format="%+.2f"),
                "Off WPA": st.column_config.NumberColumn(format="%+.2f"),
                "Clutch WPA": st.column_config.NumberColumn(format="%+.2f"),
                "Total / game": st.column_config.NumberColumn(format="%+.3f"),
            })
        st.caption("Sorted by defensive win value. Possession-mode WPA is novel "
                   "for a HS coach — it credits the plays box scores never reward.")


# ══════════════════════════════════════════════════════════════════════════════
#  ROLES & SETS — PnR ball-handler vs roll man (lights up with play_type tags)
# ══════════════════════════════════════════════════════════════════════════════
with tab_roles:
    st.caption("Splits each pick-&-roll by who finished it — the **ball-handler** "
               "(used the screen) vs the **roll man** (set it and finished). "
               "Lights up as games are tagged with play type in the tracker.")
    st.markdown(
        f"<div class='badge'>How we read it</div> "
        f"<span style='font-size:12px;color:var(--subtext)'>Ball-handler = shooter "
        f"who used a teammate's screen (Shot-Created-By filled); Roll man = the "
        f"screener who finished (empty).</span>", unsafe_allow_html=True)
    roles = D["roles"]
    rrows = []
    for pid, byk in roles.items():
        pnr = byk.get("pnr")
        if not pnr:
            continue
        h, ro = pnr.get("handler", {}), pnr.get("roller", {})
        if (h.get("poss", 0) + ro.get("poss", 0)) < 1:
            continue
        rrows.append({
            "Player": table.get(pid, {}).get("name", str(pid)),
            "Handler PPP": round(h.get("PPP") or 0, 2), "Handler FGA": h.get("poss", 0),
            "Roller PPP": round(ro.get("PPP") or 0, 2), "Roller FGA": ro.get("poss", 0),
        })
    if not rrows:
        empty_state("No tagged pick-&-rolls yet",
                    "Tag shots with a play type in the Game Tracker (one tap) and "
                    "the ball-handler vs roll-man split appears here automatically.",
                    icon="⚙️")
    else:
        st.dataframe(pd.DataFrame(sorted(rrows, key=lambda r: -(r["Handler FGA"]
                     + r["Roller FGA"]))), hide_index=True, width="stretch")
