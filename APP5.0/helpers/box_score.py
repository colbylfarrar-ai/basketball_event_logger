"""
box_score.py — Reusable, tabbed single-game box-score report.

UI helper (imports streamlit): call `render_box_score(game_id)` from any page
that has a game in context. Everything is recomputed from `game_events`, so it
stays consistent with the source of truth. Box + advanced formulas come from
helpers/stats.py; team/shot-quality/lineup engines from helpers/team_analytics.py,
helpers/lineups.py, helpers/wpa.py. Display-only; PF is credited to the fouler.

Tabs: Overview · Flow · Shooting · Quarters · Lineups · Box Score · Four Factors.
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.ui import team_color, glossary_key
import helpers.cards as CARDS
import helpers.stats as S
import helpers.win_probability as WP
import helpers.team_analytics as TA
import helpers.lineups as LU
import helpers.wpa as WPA
import helpers.team_ratings as TR
import helpers.gameflow as GF
import helpers.reports as RP
import helpers.court as court
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.seasons as SEAS
import helpers.playtypes as PT
import helpers.defenses as DEF

ZONES = ["LC", "LW", "C", "RW", "RC"]
ZONE_LABELS = {"LC": "Left Corner", "LW": "Left Wing", "C": "Paint / Center",
               "RW": "Right Wing", "RC": "Right Corner"}
CARD_BG = "#161b22"
GRID = "#21262d"
BLUE = "#58a6ff"
PURPLE = "#9b59b6"
GOOD = "#3fb950"
BAD = "#e74c3c"


# ══════════════════════════════════════════════════════════════════════════════
#  TIME HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Game-clock helpers — canonical versions live in helpers.stats.
_clock_secs = S.clock_secs
_q_len = S.q_len
_q_base = S.q_base
_elapsed = S.elapsed


def _q_label(q: int) -> str:
    return f"Q{q}" if q <= 4 else f"OT{q - 4}"


def _rgb(c):
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _rgba(c, a):
    r, g, b = _rgb(c)
    return f"rgba({r},{g},{b},{a})"


# ══════════════════════════════════════════════════════════════════════════════
#  AGGREGATION  (stats.py-compatible; PF charged to the fouler)
# ══════════════════════════════════════════════════════════════════════════════

def _build_boxes(game_id, t1id, t2id):
    """Returns (boxes, team_pts, quarters) — per-player boxes decorated with
    roster meta + MIN + +/-, plus team points and a per-quarter point split."""
    boxes_raw = S.aggregate_player_boxes([game_id])
    roster = query(
        "SELECT id AS pid, name, number, team_id FROM players "
        "WHERE team_id IN (?,?) ORDER BY number, name", (t1id, t2id))
    meta = {p["pid"]: p for p in roster}

    mins = {r["player_id"]: (r["secs"] or 0.0) for r in query(
        "SELECT gel.player_id, SUM(ge.possession_secs) AS secs "
        "FROM game_event_lineup gel JOIN game_events ge ON ge.id=gel.event_id "
        "WHERE ge.game_id=? AND ge.possession_secs>0 GROUP BY gel.player_id", (game_id,))}
    pm = {r["player_id"]: r["plus_minus"] for r in query(
        "SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?", (game_id,))}

    boxes = {}
    for pid, b in boxes_raw.items():
        m = meta.get(pid)
        if not m:
            continue
        b = dict(b)
        b.update(name=m["name"], number=m["number"], team_id=m["team_id"],
                 MIN=round(mins.get(pid, 0.0) / 60, 1), PM=pm.get(pid, 0))
        boxes[pid] = b

    team_pts = {t1id: 0, t2id: 0}
    for b in boxes.values():
        if b["team_id"] in team_pts:
            team_pts[b["team_id"]] += b["PTS"]

    quarters = {}
    for r in query("""
        SELECT ge.quarter AS q, p.team_id AS tid,
               SUM(CASE WHEN ge.event_type='shot' AND ge.shot_result='make' THEN ge.shot_type
                        WHEN ge.event_type='free_throw' AND ge.shot_result='make' THEN 1
                        ELSE 0 END) AS pts
        FROM game_events ge JOIN players p ON p.id=ge.primary_player_id
        WHERE ge.game_id=? AND ge.shot_result='make'
        GROUP BY ge.quarter, p.team_id""", (game_id,)):
        quarters.setdefault(r["q"], {t1id: 0, t2id: 0})
        if r["tid"] in quarters[r["q"]]:
            quarters[r["q"]][r["tid"]] += (r["pts"] or 0)

    return boxes, team_pts, quarters


def _team_total(boxes, tid):
    keys = list(S.finalize_box(S._blank_box()).keys())
    tb = {k: 0 for k in keys}
    for b in boxes.values():
        if b["team_id"] == tid:
            for k in keys:
                tb[k] += b.get(k, 0)
    return tb


def _pct(n, d):
    return f"{100*n/d:.1f}%" if d else "—"


# ══════════════════════════════════════════════════════════════════════════════
#  PLOTLY STYLING
# ══════════════════════════════════════════════════════════════════════════════

def _style(fig, height=330, **kw):
    fig.update_layout(
        template="plotly_dark", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=CARD_BG,
        margin=dict(l=46, r=22, t=46, b=42),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)"),
        font=dict(size=12, color="#c9d1d9"),
        bargap=0.22, **kw)
    fig.update_xaxes(gridcolor=GRID, zerolinecolor="#30363d", showline=False)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor="#30363d", showline=False)
    return fig


def _quarter_bands(fig, qs, end_t):
    for i, q in enumerate(qs):
        x0 = _q_base(q)
        x1 = _q_base(q) + _q_len(q)
        if i % 2 == 1:
            fig.add_vrect(x0=x0, x1=min(x1, end_t), fillcolor="#ffffff",
                          opacity=0.025, layer="below", line_width=0)


def _bar(text):
    return dict(texttemplate=text, textposition="outside",
                textfont=dict(size=11), cliponaxis=False)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner=False)
def _recap(game_id):
    return RP.game_recap_html(game_id)


@st.cache_resource(show_spinner=False)
def _score_ratings_fp(gender, _fp):
    """Results-only league power rating for the header, cached on the results
    fingerprint. cache_resource SURVIVES st.cache_data.clear() (the app clears
    cache_data on every write), so opening a box score no longer re-runs the whole
    ~0.5s rankings engine from scratch — it recomputes only when a game SCORE
    actually moves. Mirrors the Team Dashboard / Rankings wrapper; output is
    read-only across callers, so sharing the cache is safe."""
    return TR.score_ratings(gender=gender)


@st.cache_data(ttl=600, show_spinner=False)
def _tracked_ratings_cached(gender, vis_key):
    """Possession (NetRtg) league rating behind the header's tracked rank, cached
    per (gender, viewer-visible game set). Cheaper than score_ratings but still
    league-wide, so cache it rather than recompute on every box-score open. The
    visible set is part of the key, so two viewers with different entitlements never
    share a result."""
    return TR.tracked_ratings(
        gender=gender, game_ids=list(vis_key) if vis_key is not None else None)


def render_box_score(game_id: int):
    """Render the full tabbed box-score report for one game."""
    g = query("""
        SELECT g.*, t1.name AS t1_name, t2.name AS t2_name, t1.gender AS gender
        FROM games g JOIN teams t1 ON t1.id=g.team1_id JOIN teams t2 ON t2.id=g.team2_id
        WHERE g.id=?""", (game_id,))
    if not g:
        st.info("Game not found.")
        return
    g = g[0]
    t1id, t2id = g["team1_id"], g["team2_id"]
    t1name, t2name = g["t1_name"], g["t2_name"]        # t1 = home, t2 = away
    accent = team_color(t1name, t1id)   # home / team1 identity colour
    away = team_color(t2name, t2id)     # away / team2 identity colour
    if away == accent:                  # keep the two teams visually distinct
        away = "#e74c3c"

    boxes, team_pts, quarters = _build_boxes(game_id, t1id, t2id)
    if not any(team_pts.values()) and not quarters:
        st.info("No events have been logged for this game yet.")
        return

    home_pts, away_pts = team_pts[t1id], team_pts[t2id]
    home_win = home_pts > away_pts
    away_win = away_pts > home_pts
    htb, atb = _team_total(boxes, t1id), _team_total(boxes, t2id)
    h_poss, a_poss = S.estimate_possessions(htb), S.estimate_possessions(atb)
    qs = sorted(quarters.keys())
    end_t = _q_base(max(qs)) + _q_len(max(qs)) if qs else 0

    # one event pass + league shot-quality baseline, reused by every advanced tab
    events = S.fetch_events([game_id])
    try:
        rates = S.shot_quality_rates()            # league-wide (zone,creation,guarded)
    except Exception:
        rates = {}
        st.caption("League shot-quality baseline unavailable — team SMOE/xFG% "
                   "may be unreliable for this game.")
    try:
        cr = S.creation_fg_rates()                # league-wide creation-bucket FG%
    except Exception:
        cr = {}
        st.caption("League creation baseline unavailable — player SMOE may be "
                   "unreliable for this game.")

    # ── season records + rankings for the header ───────────────────────────────
    # W-L record and the results-only Power rank are box-derivable → public. The
    # tracked rank is possession-based (NetRtg) AND league-wide, so it's gated like
    # the analytics tabs below (can_see_game_tracked) and read-filtered to the
    # viewer's visible set — never computed for a viewer who can't open this game's
    # depth. This must sit ABOVE the hero so the tag never leaks pre-gate.
    scored, trk_rank = {}, {}
    _gident = AUTH.current_user()
    _show_trk = ENT.can_see_game_tracked(_gident, t1id, t2id, in_pool=g["in_pool"])
    try:
        scored = _score_ratings_fp(g["gender"], TR.results_fingerprint())
    except Exception:
        scored = {}
        st.caption("Season records / power rankings unavailable for this game.")
    if _show_trk:
        try:
            _vis = ENT.visible_tracked_game_ids(_gident)
            trk = _tracked_ratings_cached(
                g["gender"], tuple(_vis) if _vis is not None else None)
            trk_rank = {tid: i + 1 for i, (tid, _) in enumerate(
                sorted(trk.items(), key=lambda kv: -kv[1]["NetRtg"]))}
        except Exception:
            trk_rank = {}
            st.caption("Tracked rankings unavailable for this game.")

    def _team_tag(tid):
        s = scored.get(tid, {})
        rec = f"{s['W']}-{s['L']}" if s else "—"
        rk = f"#{s['Rank']}" if s.get("Rank") else "—"
        base = f"{rec} · Power {rk}"
        if _show_trk:                    # tracked (possession) rank: entitled only
            tr = f"#{trk_rank[tid]}" if tid in trk_rank else "—"
            base += f" · tracked {tr}"
        return f"<span style='color:#8b949e;font-size:12px'>{base}</span>"

    # ── Scoreboard hero (always on top) ─────────────────────────────────────────
    def block(name, pts, won, color, tid):
        cls = color if won else "#8b949e"
        tag = "▸ " if won else ""
        return (f"<div style='text-align:center'>"
                f"<div style='font-size:15px;font-weight:700;color:#c9d1d9'>{tag}{name}</div>"
                f"<div style='font-size:48px;font-weight:900;color:{cls};line-height:1'>{pts}</div>"
                f"<div>{_team_tag(tid)}</div>"
                f"</div>")

    place = f" · {g['location']}" if g['location'] else ""
    if g["tracked"]:
        status = " · FINAL"
    elif g["home_score"] is not None and g["away_score"] is not None:
        status = " · FINAL (manual)"
    else:
        status = " · IN PROGRESS"
    st.markdown(
        f"<div class='game-hero'>"
        f"<div style='font-size:12px;color:#8b949e;margin-bottom:6px'>"
        f"{g['date']}{place}{status}</div>"
        f"<table style='width:100%;border:none'><tr>"
        f"<td style='width:42%'>{block(t2name, away_pts, away_win, away, t2id)}</td>"
        f"<td style='width:16%;text-align:center;color:#8b949e;font-size:18px'>@</td>"
        f"<td style='width:42%'>{block(t1name, home_pts, home_win, accent, t1id)}</td>"
        f"</tr></table></div>", unsafe_allow_html=True)

    # Tier gate: a tracked game's analytics tabs are tracked-depth. Everyone sees
    # the scoreboard (final score = box-score level); lock the tabs for viewers
    # who can't see this game's tracked depth — Free, or a Paid coach who is Solo
    # (not in the Coaches' Co-op) viewing a game that isn't their own, or a game
    # that simply isn't pooled (in_pool drives the per-game check).
    # Previous seasons are an OPEN ARCHIVE — free, full tracked depth to everyone
    # (last year's roster has turned over, so there's no edge left to protect; it's
    # a funnel, not a leak — see helpers/seasons.py). Only the CURRENT season's
    # tracked depth is gated.
    if SEAS.is_current(g["season"]) and not ENT.can_see_game_tracked(
            AUTH.current_user(), t1id, t2id, in_pool=g["in_pool"]):
        # Mirror the other gate sites' branched copy so each locked viewer gets the
        # right reason: Free -> Paid feature; banned -> suspension; Solo scouting ->
        # co-op invite; League-wide but this game isn't pooled -> neutral not-shared.
        _gident = AUTH.current_user()
        if not ENT.has_paid_plan(_gident):
            st.info(ENT.MSG_PAID)
        elif ENT.is_pool_banned(_gident):
            st.info(ENT.MSG_POOL_BANNED)
        elif not ENT.viewer_is_league_wide(_gident):
            st.info(ENT.MSG_COOP_INVITE)
        else:
            st.info(ENT.MSG_NOT_SHARED)
        return

    # ── shared scoring timeline (Overview KPI + Flow) ──────────────────────────
    scoring = [e for e in events
               if e["event_type"] in ("shot", "free_throw") and e["shot_result"] == "make"]
    scoring.sort(key=lambda e: _elapsed(e["quarter"], e["time"]))
    times, hc, ac, h, a = [0.0], [0], [0], 0, 0
    for e in scoring:
        pts = e["shot_type"] if e["event_type"] == "shot" else 1
        if e["shooter_team_id"] == t1id:
            h += pts
        elif e["shooter_team_id"] == t2id:
            a += pts
        times.append(_elapsed(e["quarter"], e["time"])); hc.append(h); ac.append(a)
    times.append(end_t); hc.append(h); ac.append(a)
    margin = [x - y for x, y in zip(hc, ac)]
    curve = WP.wp_curve(list(zip(times, margin)), total_secs=end_t) if end_t else []
    summ = WP.summarize(curve) if len(curve) >= 2 else None

    # possession outcomes per team (score% / turnover%) and shot quality (SMOE)
    po_h = TA.possession_outcomes(t1id, [game_id], events=events)
    po_a = TA.possession_outcomes(t2id, [game_id], events=events)

    def _score_pct(po):
        made = po["twos"]["make"] + po["threes"]["make"]
        return 100 * made / po["total"] if po["total"] else 0.0

    def _tov_pct(po):
        return 100 * po["tov"] / po["total"] if po["total"] else 0.0

    tsq_h = TA.team_shot_quality(t1id, [game_id], events=events, rates=rates)
    tsq_a = TA.team_shot_quality(t2id, [game_id], events=events, rates=rates)

    from helpers.ui import pdf_or_html_download
    pdf_or_html_download(
        "Game recap", _recap(game_id),
        f"recap_{t1name}_vs_{t2name}".replace(" ", "_"),
        key=f"bs{game_id}_recap")

    tabs = st.tabs(["Overview", "Flow", "Shooting", "Quarters",
                    "Lineups", "Box Score", "Four Factors", "Play Types",
                    "Defense"])

    # Each tab body is a @st.fragment so its widgets (team/player pickers,
    # lineup sliders, …) rerun only that tab instead of rebuilding all seven.
    # All shared game state above is captured by closure.

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 0 — OVERVIEW
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def _tab_overview():
        m = st.columns(5)
        m[0].metric("Game Excitement", summ["gei"] if summ else "—",
                    summ["label"] if summ else None, delta_color="off")
        m[1].metric(f"{t1name} FG%", f"{100*S.fg_pct(htb):.1f}%",
                    f"SMOE {tsq_h['SMOE']*100:+.1f} pp", delta_color="off")
        m[2].metric(f"{t2name} FG%", f"{100*S.fg_pct(atb):.1f}%",
                    f"SMOE {tsq_a['SMOE']*100:+.1f} pp", delta_color="off")
        m[3].metric(f"{t1name} score-poss%", f"{_score_pct(po_h):.0f}%",
                    f"TOV {_tov_pct(po_h):.0f}%", delta_color="off")
        m[4].metric(f"{t2name} score-poss%", f"{_score_pct(po_a):.0f}%",
                    f"TOV {_tov_pct(po_a):.0f}%", delta_color="off")
        st.caption("SMOE = FG% over expected (vs league shot-quality baseline). "
                   "Score-poss% = share of possessions ending in a made field goal.")

        # line score
        line = []
        for tid, nm in [(t2id, t2name), (t1id, t1name)]:
            row, tot = {"Team": nm}, 0
            for q in qs:
                v = quarters[q].get(tid, 0); row[_q_label(q)] = v; tot += v
            row["T"] = tot
            line.append(row)
        st.dataframe(pd.DataFrame(line), hide_index=True, width="stretch",
                     key=f"bs{game_id}_linescore")

        c1, c2 = st.columns([3, 2])
        with c1:
            st.markdown("**Team comparison**")
            comp = pd.DataFrame([
                {"Stat": "Field goals", t2name: f"{atb['FGM']}-{atb['FGA']} ({_pct(atb['FGM'],atb['FGA'])})",
                 t1name: f"{htb['FGM']}-{htb['FGA']} ({_pct(htb['FGM'],htb['FGA'])})"},
                {"Stat": "3-pointers", t2name: f"{atb['3PM']}-{atb['3PA']} ({_pct(atb['3PM'],atb['3PA'])})",
                 t1name: f"{htb['3PM']}-{htb['3PA']} ({_pct(htb['3PM'],htb['3PA'])})"},
                {"Stat": "Free throws", t2name: f"{atb['FTM']}-{atb['FTA']} ({_pct(atb['FTM'],atb['FTA'])})",
                 t1name: f"{htb['FTM']}-{htb['FTA']} ({_pct(htb['FTM'],htb['FTA'])})"},
                {"Stat": "eFG% / TS%", t2name: f"{100*S.efg(atb):.1f}% / {100*S.ts(atb):.1f}%",
                 t1name: f"{100*S.efg(htb):.1f}% / {100*S.ts(htb):.1f}%"},
                {"Stat": "Rebounds (O-D)", t2name: f"{atb['TRB']} ({atb['ORB']}-{atb['DRB']})",
                 t1name: f"{htb['TRB']} ({htb['ORB']}-{htb['DRB']})"},
                {"Stat": "Assists / Steals / Blocks",
                 t2name: f"{atb['AST']} / {atb['STL']} / {atb['BLK']}",
                 t1name: f"{htb['AST']} / {htb['STL']} / {htb['BLK']}"},
                {"Stat": "Turnovers / Fouls", t2name: f"{atb['TOV']} / {atb['PF']}",
                 t1name: f"{htb['TOV']} / {htb['PF']}"},
                {"Stat": "Paint points", t2name: f"{atb['paint_PTS']}", t1name: f"{htb['paint_PTS']}"},
                {"Stat": "3PA rate / FT rate",
                 t2name: f"{100*S.three_par(atb):.0f}% / {100*S.ftr(atb):.0f}%",
                 t1name: f"{100*S.three_par(htb):.0f}% / {100*S.ftr(htb):.0f}%"},
                {"Stat": "Points per shot (PPS)",
                 t2name: f"{S.pps(atb):.2f}", t1name: f"{S.pps(htb):.2f}"},
                {"Stat": "Turnover %", t2name: f"{S.tov_pct(atb):.1f}%", t1name: f"{S.tov_pct(htb):.1f}%"},
                {"Stat": "Possessions", t2name: f"{a_poss:.0f}", t1name: f"{h_poss:.0f}"},
                {"Stat": "Off. rating (pts/100)",
                 t2name: f"{100*away_pts/a_poss:.1f}" if a_poss else "—",
                 t1name: f"{100*home_pts/h_poss:.1f}" if h_poss else "—"},
            ])
            comp[t1name] = comp[t1name].astype(str)
            comp[t2name] = comp[t2name].astype(str)
            st.dataframe(comp, hide_index=True, width="stretch",
                         key=f"bs{game_id}_comp")
        with c2:
            st.markdown("**Shooting profile**")
            cats = ["FG%", "3P%", "FT%", "eFG%", "TS%"]
            av = [100*S._safe(atb['FGM'],atb['FGA']), 100*S._safe(atb['3PM'],atb['3PA']),
                  100*S._safe(atb['FTM'],atb['FTA']), 100*S.efg(atb), 100*S.ts(atb)]
            hv = [100*S._safe(htb['FGM'],htb['FGA']), 100*S._safe(htb['3PM'],htb['3PA']),
                  100*S._safe(htb['FTM'],htb['FTA']), 100*S.efg(htb), 100*S.ts(htb)]
            rad = go.Figure()
            for nm, vals, clr in [(t2name, av, away), (t1name, hv, accent)]:
                rr, rg, rb = _rgb(clr)
                rad.add_trace(go.Scatterpolar(
                    r=vals + [vals[0]], theta=cats + [cats[0]], fill="toself",
                    name=nm, line=dict(color=clr, width=2),
                    fillcolor=f"rgba({rr},{rg},{rb},0.18)"))
            rad.update_layout(
                template="plotly_dark", height=330,
                paper_bgcolor="rgba(0,0,0,0)",
                polar=dict(bgcolor=CARD_BG,
                           radialaxis=dict(range=[0, 100], gridcolor=GRID, tickfont=dict(size=9)),
                           angularaxis=dict(gridcolor=GRID)),
                margin=dict(l=40, r=40, t=50, b=30),
                legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)"))
            st.plotly_chart(rad, width="stretch", key=f"bs{game_id}_radar")

        st.markdown("**Game leaders**")

        def leader(stat):
            best = max(boxes.values(), key=lambda b: b[stat], default=None)
            return (best["name"], best[stat]) if best and best[stat] else ("—", 0)
        lc = st.columns(5)
        for col, (lbl, stat) in zip(lc, [("Points", "PTS"), ("Rebounds", "TRB"),
                                          ("Assists", "AST"), ("Steals", "STL"),
                                          ("Blocks", "BLK")]):
            nm, val = leader(stat)
            col.markdown(
                f"<div class='kpi-tile'><div class='kpi-label'>{lbl}</div>"
                f"<div class='kpi-value'>{val}</div>"
                f"<div class='kpi-sub'>{nm}</div></div>", unsafe_allow_html=True)

        # ── scoring breakdown (paint / 2nd chance / off TO / fast break / bench)
        st.markdown("**Scoring breakdown**")
        _sb = GF.scoring_buckets([game_id], events=events)
        _h, _a = (_sb.get(t1id) or {}), (_sb.get(t2id) or {})
        _cats = [("Paint", "paint"), ("2nd chance", "second_chance"),
                 ("Off TO", "off_turnover"), ("Fast break", "fast_break"),
                 ("Bench", "bench")]
        _sbfig = go.Figure()
        _sbfig.add_trace(go.Bar(
            name=t1name, x=[c[0] for c in _cats],
            y=[_h.get(c[1], 0) for c in _cats], marker_color=accent,
            marker_line_width=0, text=[_h.get(c[1], 0) for c in _cats],
            textposition="outside"))
        _sbfig.add_trace(go.Bar(
            name=t2name, x=[c[0] for c in _cats],
            y=[_a.get(c[1], 0) for c in _cats], marker_color=away,
            marker_line_width=0, text=[_a.get(c[1], 0) for c in _cats],
            textposition="outside"))
        _sbfig.update_layout(barmode="group")
        _sbfig.update_yaxes(title="Points")
        _style(_sbfig, 300)
        st.plotly_chart(_sbfig, width="stretch", key=f"bs{game_id}_buckets")
        st.caption("Field-goal points by type · bench = all points by inferred "
                   "non-starters (starters = the opening five on the floor).")

        _runs = GF.scoring_runs(game_id, events=events)
        if _runs:
            _rtxt = " · ".join(
                f"{(t1name if r['team_id'] == t1id else t2name)} on a "
                f"{r['points']}-0 run" for r in _runs[:3])
            st.caption(f"🔥 **Biggest runs:** {_rtxt}")

    with tabs[0]:
        _tab_overview()

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 1 — FLOW
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def _tab_flow():
        xticks = [_q_base(q) for q in qs] + [end_t]
        xlabels = [_q_label(q) for q in qs] + ["End"]

        st.markdown("**Score over time**")
        fig = go.Figure()
        for nm, cum, clr in [(t2name, ac, away), (t1name, hc, accent)]:
            fig.add_trace(go.Scatter(
                x=times, y=cum, name=nm, line_shape="hv",
                line=dict(color=clr, width=3), fill="tozeroy",
                fillcolor=_rgba(clr, 0.12),
                hovertemplate=nm + ": %{y}<extra></extra>"))
        _quarter_bands(fig, qs, end_t)
        for v in xticks[1:-1]:
            fig.add_vline(x=v, line=dict(color="#30363d", width=1, dash="dot"))
        fig.update_xaxes(tickvals=xticks, ticktext=xlabels, title="Game clock")
        fig.update_yaxes(title="Points")
        _style(fig, 360)
        st.plotly_chart(fig, width="stretch", key=f"bs{game_id}_score_time")

        # lead margin + lead changes
        lead_changes, prev = 0, 0
        for mm in margin:
            s = (mm > 0) - (mm < 0)
            if s and prev and s != prev:
                lead_changes += 1
            if s:
                prev = s
        st.markdown("**Lead margin**")
        mfig = go.Figure()
        mfig.add_trace(go.Scatter(
            x=times, y=margin, line_shape="hv", name="Margin",
            line=dict(color=accent, width=2), fill="tozeroy",
            fillcolor=_rgba(accent, 0.15),
            hovertemplate="Margin: %{y}<extra></extra>"))
        mfig.add_hline(y=0, line=dict(color="#30363d", width=1))
        _quarter_bands(mfig, qs, end_t)
        for _r in GF.scoring_runs(game_id, events=events)[:3]:
            mfig.add_vrect(
                x0=_r["start"], x1=_r["end"],
                fillcolor=(accent if _r["team_id"] == t1id else away),
                opacity=0.12, line_width=0, annotation_text=f"{_r['points']}-0",
                annotation_position="top left", annotation_font_size=9)
        mfig.update_xaxes(tickvals=xticks, ticktext=xlabels, title="Game clock")
        mfig.update_yaxes(title=f"+{t1name}  /  −{t2name}")
        _style(mfig, 260)
        st.plotly_chart(mfig, width="stretch", key=f"bs{game_id}_margin")
        f1, f2, f3 = st.columns(3)
        f1.metric(f"Biggest lead · {t1name}", f"+{max(margin) if margin else 0}")
        f2.metric(f"Biggest lead · {t2name}", f"+{-min(margin) if margin else 0}")
        f3.metric("Lead changes", lead_changes)

        # win probability
        if summ:
            st.markdown("**Win probability**")
            wp_home = [round(100 * c[2], 1) for c in curve]
            wfig = go.Figure()
            wfig.add_trace(go.Scatter(
                x=times, y=wp_home, line_shape="hv", name=f"{t1name} win %",
                line=dict(color=accent, width=2.5), fill="tozeroy",
                fillcolor=_rgba(accent, 0.13),
                hovertemplate=t1name + " win: %{y:.0f}%<extra></extra>"))
            wfig.add_hline(y=50, line=dict(color="#8b949e", width=1, dash="dot"))
            _quarter_bands(wfig, qs, end_t)
            for v in xticks[1:-1]:
                wfig.add_vline(x=v, line=dict(color="#30363d", width=1, dash="dot"))
            wfig.update_xaxes(tickvals=xticks, ticktext=xlabels, title="Game clock")
            wfig.update_yaxes(title=f"{t1name} win probability", range=[0, 100],
                              ticksuffix="%")
            _style(wfig, 260)
            st.plotly_chart(wfig, width="stretch", key=f"bs{game_id}_winprob")
            st.caption("Closed-form model (final margin ≈ Normal around the current "
                       "margin, variance shrinking as the clock runs; even-teams "
                       "assumption). Game Excitement is on the Overview tab.")

        st.divider()

        # possession outcomes + turnovers
        o1, o2 = st.columns(2)
        with o1:
            st.markdown("**Possessions ending in a score**")
            sfig = go.Figure()
            for nm, po, clr in [(t2name, po_a, away), (t1name, po_h, accent)]:
                tot = po["total"] or 1
                made2 = 100 * po["twos"]["make"] / tot
                made3 = 100 * po["threes"]["make"] / tot
                sfig.add_trace(go.Bar(x=[nm], y=[made2], name="2-pt make",
                                      marker_color=clr, marker_line_width=0,
                                      legendgroup="2", showlegend=(nm == t2name),
                                      text=f"{made2:.0f}%", textposition="inside",
                                      hovertemplate="2-pt make: %{y:.0f}%<extra></extra>"))
                sfig.add_trace(go.Bar(x=[nm], y=[made3], name="3-pt make",
                                      marker_color=_rgba(clr, 0.55), marker_line_width=0,
                                      legendgroup="3", showlegend=(nm == t2name),
                                      text=f"{made3:.0f}%", textposition="inside",
                                      hovertemplate="3-pt make: %{y:.0f}%<extra></extra>"))
            sfig.update_layout(barmode="stack")
            sfig.update_yaxes(title="% of possessions", range=[0, 100])
            _style(sfig, 300)
            st.plotly_chart(sfig, width="stretch", key=f"bs{game_id}_poss_score")
        with o2:
            st.markdown("**Possessions ending in a turnover**")
            tfig = go.Figure()
            for nm, po, clr in [(t2name, po_a, away), (t1name, po_h, accent)]:
                tfig.add_trace(go.Bar(x=[nm], y=[_tov_pct(po)], marker_color=clr,
                                      marker_line_width=0, name=nm,
                                      text=f"{_tov_pct(po):.0f}%", textposition="outside",
                                      hovertemplate="TOV: %{y:.0f}%<extra></extra>"))
            tfig.update_yaxes(title="% of possessions", range=[0, max(40, _tov_pct(po_h), _tov_pct(po_a)) + 8])
            tfig.update_layout(showlegend=False)
            _style(tfig, 300)
            st.plotly_chart(tfig, width="stretch", key=f"bs{game_id}_poss_tov")

        p1, p2 = st.columns(2)
        with p1:
            st.markdown("**Points per shot (PPS)**")
            ppsfig = go.Figure(go.Bar(
                x=[t2name, t1name], y=[round(S.pps(atb), 2), round(S.pps(htb), 2)],
                marker_color=[away, accent], marker_line_width=0,
                text=[f"{S.pps(atb):.2f}", f"{S.pps(htb):.2f}"], textposition="outside"))
            ppsfig.update_yaxes(title="Points per FG attempt")
            _style(ppsfig, 280)
            st.plotly_chart(ppsfig, width="stretch", key=f"bs{game_id}_pps")
        with p2:
            st.markdown("**Avg possession length by quarter**")
            qps = TA.quarter_possession_secs(t1id, [game_id], events=events)
            qsq = sorted(qps.keys())
            lfig = go.Figure()
            lfig.add_trace(go.Scatter(
                x=[_q_label(q) for q in qsq], y=[round(qps[q]["team_avg"], 1) for q in qsq],
                name=t1name, mode="lines+markers", line=dict(color=accent, width=2)))
            lfig.add_trace(go.Scatter(
                x=[_q_label(q) for q in qsq], y=[round(qps[q]["opp_avg"], 1) for q in qsq],
                name=t2name, mode="lines+markers", line=dict(color=away, width=2)))
            lfig.update_yaxes(title="Seconds / possession")
            _style(lfig, 280)
            st.plotly_chart(lfig, width="stretch", key=f"bs{game_id}_pace_qtr")

        # scoring by possession length
        st.markdown("**Scoring by possession length**")
        st.caption("Each team's own shots bucketed by how long the possession ran. "
                   "PPP = points per shot here · ScEff = scoring efficiency · "
                   "Self/Pass/Screen/Both = how the shot was created.")
        plcfg = {
            "FG%": st.column_config.NumberColumn("FG%", format="%.0f%%"),
            "2P%": st.column_config.NumberColumn("2P%", format="%.0f%%"),
            "3P%": st.column_config.NumberColumn("3P%", format="%.0f%%"),
            "SCE": st.column_config.NumberColumn("ScEff", format="%.0f%%"),
            "AST%": st.column_config.NumberColumn("AST%", format="%.0f%%"),
            "PPP": st.column_config.NumberColumn("PPP", format="%.2f"),
        }
        for tid, nm in [(t1id, t1name), (t2id, t2name)]:
            rows = TA.possession_length_splits(tid, [game_id], events=events)
            df = pd.DataFrame([{
                "Bucket": r["label"], "PPP": round(r["PPP"], 2), "FGA": r["FGA"],
                "FG%": round(100 * r["FG%"], 0), "2P%": round(100 * r["2P%"], 0),
                "3P%": round(100 * r["3P%"], 0), "SCE": round(100 * r["SCE"], 0),
                "AST%": round(100 * r["AST%"], 0), "Self": r["self"], "Pass": r["pass"],
                "Screen": r["screen"], "Both": r["both"]} for r in rows])
            st.markdown(f"*{nm}*")
            st.dataframe(df, hide_index=True, width="stretch", column_config=plcfg,
                         key=f"bs{game_id}_plen_{tid}")

    with tabs[1]:
        _tab_flow()

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 2 — SHOOTING
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def _tab_shooting():
        # 1) stacked creation × region bar (per team) + creation table
        st.markdown("**Shot profile — creation × shot type**")
        st.caption("Each bar = a creation context; stacked Paint-2 / Mid-2 / 3-pt by "
                   "attempts. Segment text = makes/attempts · FG%. Top = total FGA · "
                   "eFG% · TS%.")
        regions = [("paint2", "Paint 2", accent), ("mid2", "Mid 2", PURPLE),
                   ("three", "3-pt", BLUE)]
        bk_keys = [k for k, _ in TA.CREATION_BUCKETS]
        bk_labels = [lbl for _, lbl in TA.CREATION_BUCKETS]
        for tid, nm in [(t1id, t1name), (t2id, t2name)]:
            ct = TA.creation_region_crosstab(tid, [game_id], events=events)
            cfig = go.Figure()
            for rkey, rlbl, rclr in regions:
                ys = [ct[bk][rkey]["FGA"] for bk in bk_keys]
                txt = [(f"{ct[bk][rkey]['FGM']}/{ct[bk][rkey]['FGA']} · "
                        f"{100*ct[bk][rkey]['FG%']:.0f}%") if ct[bk][rkey]["FGA"] else ""
                       for bk in bk_keys]
                cfig.add_trace(go.Bar(x=bk_labels, y=ys, name=rlbl, marker_color=rclr,
                                      marker_line_width=0, text=txt,
                                      textposition="inside", insidetextanchor="middle",
                                      textfont=dict(size=10)))
            for i, bk in enumerate(bk_keys):
                tt = ct[bk]["total"]
                if tt["FGA"]:
                    cfig.add_annotation(
                        x=bk_labels[i], y=tt["FGA"], yshift=12, showarrow=False,
                        text=f"<b>{tt['FGA']}</b> · eFG {100*tt['eFG']:.0f}%",
                        font=dict(size=10, color="#c9d1d9"))
            cfig.update_layout(barmode="stack")
            cfig.update_yaxes(title="Attempts")
            _style(cfig, 340)
            st.markdown(f"*{nm}*")
            st.plotly_chart(cfig, width="stretch", key=f"bs{game_id}_creation_stack_{tid}")

        st.markdown("**Shot-creation breakdown**")
        split_lbl = {"self": "Self", "pass": "Off Pass", "created": "Off Screen",
                     "both": "Both", "total": "Total"}
        cbcfg = {c: st.column_config.NumberColumn(c, format="%.0f%%")
                 for c in ("FG%", "2P%", "3P%", "eFG%")}
        cbcfg["PPP"] = st.column_config.NumberColumn("PPP", format="%.2f")
        cbcfg["SCE"] = st.column_config.NumberColumn("ScEff", format="%.0f%%")
        for tid, nm in [(t1id, t1name), (t2id, t2name)]:
            cb = TA.creation_breakdown(tid, [game_id], events=events)
            df = pd.DataFrame([{
                "Split": split_lbl[k], "FGM": cb[k]["FGM"], "FGA": cb[k]["FGA"],
                "FG%": round(100*cb[k]["FG%"], 0), "2PM": cb[k]["2PM"], "2PA": cb[k]["2PA"],
                "2P%": round(100*cb[k]["2P%"], 0), "3PM": cb[k]["3PM"], "3PA": cb[k]["3PA"],
                "3P%": round(100*cb[k]["3P%"], 0), "eFG%": round(100*cb[k]["eFG"], 0),
                "PPP": round(cb[k]["PPS"], 2), "SCE": round(100*cb[k]["SCE"], 0),
                "PTS": cb[k]["PTS"]} for k in ("self", "pass", "created", "both", "total")])
            st.markdown(f"*{nm}*")
            st.dataframe(df, hide_index=True, width="stretch", column_config=cbcfg,
                         key=f"bs{game_id}_creation_tbl_{tid}")

        # assisted FG% / shot creation %
        st.markdown("**Assisted FG % · shot creation %**")
        afig = go.Figure()
        acats = ["Assisted FG%", "Self-created", "Off pass", "Off screen"]
        for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
            bd = S.shot_breakdown_pct(tb)
            ys = [round(100*S._safe(tb["AST"], tb["FGM"]), 1), round(100*bd["self"], 1),
                  round(100*bd["pass"], 1), round(100*bd["sc"], 1)]
            afig.add_trace(go.Bar(x=acats, y=ys, name=nm, marker_color=clr,
                                  text=[f"{v:.0f}%" for v in ys],
                                  marker_line_width=0, **_bar("%{text}")))
        afig.update_layout(barmode="group")
        afig.update_yaxes(title="%", range=[0, 105])
        _style(afig, 300)
        st.plotly_chart(afig, width="stretch", key=f"bs{game_id}_assisted_fg")

        st.divider()

        # scoring composition donuts
        st.markdown("**Where the points came from**")
        d1, d2 = st.columns(2)
        for di, (col, nm, tb, clr) in enumerate([(d1, t2name, atb, away), (d2, t1name, htb, accent)]):
            vals = [tb["2PM"]*2, tb["3PM"]*3, tb["FTM"]]
            tot = sum(vals)
            don = CARDS.scoring_donut(
                *vals, colors=(clr, BLUE, "#8b949e"), hole=0.62, height=300,
                title=nm, ft_label="Free throws", ring=True, margin_top=40,
                center=f"<b>{tot}</b><br>pts", center_size=18)
            col.plotly_chart(don, width="stretch", key=f"bs{game_id}_donut{di}")

        # shot distribution by zone, split 2 vs 3
        st.markdown("**Shot distribution by zone (2s vs 3s)**")
        zr = query("""
            SELECT p.team_id AS tid, ge.zone, ge.shot_type AS st, COUNT(*) AS fga,
                   SUM(CASE WHEN ge.shot_result='make' THEN 1 ELSE 0 END) AS fgm
            FROM game_events ge JOIN players p ON p.id=ge.primary_player_id
            WHERE ge.game_id=? AND ge.event_type='shot' AND ge.zone IS NOT NULL
            GROUP BY p.team_id, ge.zone, ge.shot_type""", (game_id,))
        zmap = defaultdict(lambda: {"fga": 0, "fgm": 0})
        for r in zr:
            zmap[(r["tid"], r["zone"], 3 if r["st"] == 3 else 2)] = {
                "fga": r["fga"], "fgm": r["fgm"] or 0}
        zc1, zc2 = st.columns(2)
        for col, tid, nm in [(zc1, t1id, t1name), (zc2, t2id, t2name)]:
            zfig = go.Figure()
            for stype, slbl, sclr in [(2, "2-pt", accent if tid == t1id else away),
                                      (3, "3-pt", BLUE)]:
                ys = [zmap[(tid, z, stype)]["fga"] for z in ZONES]
                txt = [f"{zmap[(tid,z,stype)]['fgm']}/{zmap[(tid,z,stype)]['fga']}"
                       if zmap[(tid,z,stype)]["fga"] else "" for z in ZONES]
                zfig.add_trace(go.Bar(x=[ZONE_LABELS[z] for z in ZONES], y=ys,
                                      name=slbl, marker_color=sclr, marker_line_width=0,
                                      text=txt, textposition="inside"))
            zfig.update_layout(barmode="stack")
            zfig.update_yaxes(title="Attempts")
            _style(zfig, 320)
            col.markdown(f"*{nm}*")
            col.plotly_chart(zfig, width="stretch", key=f"bs{game_id}_zones_{tid}")

        # shot diet + paint/perimeter (with PPS, merged scoring-source %)
        s1, s2 = st.columns(2)
        with s1:
            st.markdown("**Shot diet** (3PA rate · FT rate · PPS)")
            cats = ["3PA rate", "FT rate", "PPS ×100"]
            dfig = go.Figure()
            for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
                ys = [round(100*S.three_par(tb), 1), round(100*S.ftr(tb), 1),
                      round(100*S.pps(tb), 1)]
                dfig.add_trace(go.Bar(x=cats, y=ys, name=nm, marker_color=clr,
                                      text=ys, marker_line_width=0, **_bar("%{text}")))
            dfig.update_layout(barmode="group")
            _style(dfig, 320)
            st.plotly_chart(dfig, width="stretch", key=f"bs{game_id}_shot_diet")
        with s2:
            st.markdown("**Paint vs perimeter** (points · % · PPS)")
            pfig = go.Figure()

            def _cat_vals(tb):
                paint_pts = tb["paint_PTS"]
                paint_fga = tb["paint_FGA"]
                mid_pts = tb["2PM"] * 2 - paint_pts
                mid_fga = tb["2PA"] - paint_fga
                three_pts = tb["3PM"] * 3
                ft_pts = tb["FTM"]
                tot = tb["PTS"] or 1
                pts = [paint_pts, mid_pts, three_pts, ft_pts]
                pps = [S._safe(paint_pts, paint_fga), S._safe(mid_pts, mid_fga),
                       S._safe(three_pts, tb["3PA"]), S._safe(ft_pts, tb["FTA"])]
                share = [100*p/tot for p in pts]
                return pts, pps, share
            cats = ["Paint", "Mid-range 2", "3-pt", "Free throws"]
            for nm, tb, clr in [(t2name, atb, away), (t1name, htb, accent)]:
                pts, pps, share = _cat_vals(tb)
                txt = [f"{p} ({sh:.0f}% · {pp:.2f})" for p, sh, pp in zip(pts, share, pps)]
                pfig.add_trace(go.Bar(x=cats, y=pts, name=nm, marker_color=clr,
                                      marker_line_width=0, text=txt,
                                      textposition="outside", textfont=dict(size=9),
                                      cliponaxis=False))
            pfig.update_layout(barmode="group")
            pfig.update_yaxes(title="Points")
            _style(pfig, 320)
            st.plotly_chart(pfig, width="stretch", key=f"bs{game_id}_paint_perim")

        st.divider()

        # shot chart — real tap-located court when (x,y) exist, else 5-zone tiles
        st.markdown("**Shot chart** — tap-located shots on the court, or 5-zone "
                    "heat when the game has zone-only data")
        hz1, hz2, hz3 = st.columns(3)
        with hz1:
            team_pick = st.selectbox("Team", ["Both", t1name, t2name],
                                     key=f"bs{game_id}_hz_team")
        # player options scoped to the team pick
        tid_pick = {t1name: t1id, t2name: t2id}.get(team_pick)
        plist = sorted([b for b in boxes.values()
                        if b["FGA"] > 0 and (tid_pick is None or b["team_id"] == tid_pick)],
                       key=lambda b: -b["FGA"])
        pmap = {f"{b['name']} ({b['FGA']} FGA)": b for b in plist}
        with hz2:
            player_pick = st.selectbox("Player", ["All players"] + list(pmap.keys()),
                                       key=f"bs{game_id}_hz_player")
        pid = (_pid_of(pmap[player_pick], boxes)
               if player_pick != "All players" else None)

        # tap-captured (x,y) when present, else zone centroid (flagged approx)
        shots = S.mapped_shots(game_ids=[game_id], events=events,
                               team_id=tid_pick, player_id=pid)
        # play-type filter — only the tagged set calls present in this scope
        _PTL = dict(PT.NAMED_PLAY_TYPES)
        _pt_present = {s.get("play_type") for s in shots if s.get("play_type")}
        _lbl2key = {_PTL[k]: k for k, _ in PT.NAMED_PLAY_TYPES if k in _pt_present}
        with hz3:
            pt_pick = st.selectbox(
                "Play type", ["All sets"] + list(_lbl2key),
                key=f"bs{game_id}_hz_pt", disabled=not _lbl2key,
                help="Filter the chart to one tagged set call (Pick & roll, "
                     "Iso, Transition…). Tag shots in the Game Tracker to fill this.")
        _pk = _lbl2key.get(pt_pick)
        if _pk:
            shots = [s for s in shots if s.get("play_type") == _pk]
        who = (player_pick if player_pick != "All players"
               else team_pick if team_pick != "Both" else "Both teams")
        if _pk:
            who += f" · {pt_pick}"

        n_real = sum(1 for s in shots if not s["approx"])

        if not shots:
            st.info("No shots logged for this filter.")
        elif n_real:
            # real located shots → true half-court chart (dots or hexbin)
            view = st.radio("View", ["Shot map", "Hexbin (volume · PPS)"],
                            horizontal=True, key=f"bs{game_id}_hz_view")
            if view.startswith("Shot"):
                cfig, _ = court.shot_map(shots, title=f"{who} · shot chart")
            else:
                cfig, _ = court.shot_hexbin(shots, title=f"{who} · shot hexbin")
            # Chart-as-input: tap a spot on the court → filter the located shots
            # to that zone and summarise them. Scoped to this @st.fragment.
            from helpers.ui import court_panel as _cpanel, selected_xy as _sxy
            _csel = _cpanel(cfig, key=f"bs{game_id}_courtmap")
            _chits = _sxy(_csel)
            if _chits:
                from helpers.court_geom import zone_from_xy as _zfx
                _tz = _zfx(*_chits[0])
                _zs = [s for s in shots
                       if (not s["approx"]) and _zfx(s["x"], s["y"]) == _tz]
                if _zs:
                    _zm = sum(1 for s in _zs if s["make"])
                    _zp = sum((s["value"] if s["make"] else 0) for s in _zs)
                    st.markdown(
                        f"<span class='badge accent'>Zone {_tz}</span> &nbsp; "
                        f"<b>{_zm}/{len(_zs)}</b> "
                        f"({_zm / len(_zs) * 100:.0f}%) · "
                        f"{_zp / len(_zs):.2f} pts/shot "
                        f"<span style='color:var(--subtext)'>"
                        f"(tap-located shots in this zone)</span>",
                        unsafe_allow_html=True)
            if n_real < len(shots):
                st.caption(f"{n_real}/{len(shots)} shots are tap-located; the rest "
                           "sit at their zone centroid. Sharper as you tap shots in "
                           "the Game Tracker.")
            # length breakdown — tap-located shots only (centroids have no true dist)
            _dbl = S.distance_buckets([s for s in shots if not s["approx"]])
            if _dbl:
                st.caption("By length — " + S.distance_buckets_caption(_dbl))
        else:
            # legacy zone-only game → 5-zone heat tiles (no x/y captured yet)
            st.caption("Zone-only data for this game — tap shots in the Game "
                       "Tracker to unlock the full court map.")
            za = {(z, t): {"fga": 0, "fgm": 0} for z in ZONES for t in (2, 3)}
            for e in events:
                if e["event_type"] != "shot" or not e["zone"]:
                    continue
                if tid_pick is not None and e["shooter_team_id"] != tid_pick:
                    continue
                if pid is not None and e["primary_player_id"] != pid:
                    continue
                if _pk and e.get("play_type") != _pk:
                    continue
                c = za[(e["zone"], 3 if e["shot_type"] == 3 else 2)]
                c["fga"] += 1
                if e["shot_result"] == "make":
                    c["fgm"] += 1
            # two stacks of five — 3-pointers on top, 2-pointers on the bottom
            for stype, slbl in [(3, "3-pointers"), (2, "2-pointers")]:
                st.markdown(
                    f"<div style='font-size:12px;color:#8b949e;margin:6px 0 2px'>"
                    f"{slbl}</div>", unsafe_allow_html=True)
                cols = st.columns(5)
                for col, z in zip(cols, ZONES):
                    c = za[(z, stype)]
                    col.markdown(_zone_tile(ZONE_LABELS[z], c["fgm"], c["fga"]),
                                 unsafe_allow_html=True)

        st.divider()

        # shot making & quality
        st.markdown("**Shot making & quality** (vs league baseline)")
        q1, q2 = st.columns(2)
        with q1:
            st.markdown("*FG% vs expected (xFG%) · SMOE*")
            qfig = go.Figure()
            qfig.add_trace(go.Bar(
                x=[t2name, t1name], y=[round(100*tsq_a["FG%"], 1), round(100*tsq_h["FG%"], 1)],
                name="FG%", marker_color=[away, accent], marker_line_width=0,
                text=[f"{100*tsq_a['FG%']:.0f}%", f"{100*tsq_h['FG%']:.0f}%"],
                textposition="outside"))
            qfig.add_trace(go.Scatter(
                x=[t2name, t1name], y=[round(100*tsq_a["xFG%"], 1), round(100*tsq_h["xFG%"], 1)],
                name="xFG%", mode="markers", marker=dict(color="#f0f6fc", size=14,
                                                         symbol="line-ew", line=dict(width=3))))
            qfig.update_yaxes(title="%", range=[0, max(60, 100*tsq_h["FG%"], 100*tsq_a["FG%"]) + 10])
            _style(qfig, 320)
            st.plotly_chart(qfig, width="stretch", key=f"bs{game_id}_quality_fg")
            st.caption(f"SMOE — {t1name}: {tsq_h['SMOE']*100:+.1f} pp · "
                       f"{t2name}: {tsq_a['SMOE']*100:+.1f} pp. "
                       f"xPPS — {t1name}: {tsq_h['xPPS']:.2f} (actual {tsq_h['PPS']:.2f}) · "
                       f"{t2name}: {tsq_a['xPPS']:.2f} (actual {tsq_a['PPS']:.2f}).")
        with q2:
            st.markdown("*Contested vs open FG% — 2s & 3s*")
            gst_h = TA.guarded_splits_by_type(t1id, [game_id], events=events, rates=rates)
            gst_a = TA.guarded_splits_by_type(t2id, [game_id], events=events, rates=rates)
            ccats = ["2s open", "2s contested", "3s open", "3s contested"]

            def _cv(gst):
                return [round(100*gst["twos"]["open"]["FG%"], 1),
                        round(100*gst["twos"]["guarded"]["FG%"], 1),
                        round(100*gst["threes"]["open"]["FG%"], 1),
                        round(100*gst["threes"]["guarded"]["FG%"], 1)]

            def _ct(gst):
                return [f"{gst['twos']['open']['FGM']}/{gst['twos']['open']['FGA']}",
                        f"{gst['twos']['guarded']['FGM']}/{gst['twos']['guarded']['FGA']}",
                        f"{gst['threes']['open']['FGM']}/{gst['threes']['open']['FGA']}",
                        f"{gst['threes']['guarded']['FGM']}/{gst['threes']['guarded']['FGA']}"]
            cfig = go.Figure()
            for nm, gst, clr in [(t2name, gst_a, away), (t1name, gst_h, accent)]:
                cfig.add_trace(go.Bar(x=ccats, y=_cv(gst), name=nm, marker_color=clr,
                                      marker_line_width=0, text=_ct(gst),
                                      textposition="outside", textfont=dict(size=9),
                                      cliponaxis=False))
            cfig.update_layout(barmode="group")
            cfig.update_yaxes(title="FG%", range=[0, 105])
            _style(cfig, 320)
            st.plotly_chart(cfig, width="stretch", key=f"bs{game_id}_contested")

    with tabs[2]:
        _tab_shooting()

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 3 — QUARTERS
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def _tab_quarters():
        qb = TA.quarter_boxes(t1id, [game_id], events=events)
        qps = TA.quarter_possession_secs(t1id, [game_id], events=events)
        qsq = sorted(qb.keys())
        if not qsq:
            st.info("No per-quarter data yet.")
        else:
            xlab = [_q_label(q) for q in qsq]
            st.caption(f"Every stat by period · {t1name} (accent) vs {t2name} (red). "
                       "Counts as bars, rates as lines.")

            def qchart(label, kind, fn, key):
                fig = go.Figure()
                for nm, side, clr in [(t2name, "opp", away), (t1name, "team", accent)]:
                    ys = [round(fn(qb[q][side]), 2) for q in qsq]
                    if kind == "bar":
                        fig.add_trace(go.Bar(x=xlab, y=ys, name=nm, marker_color=clr,
                                             marker_line_width=0))
                    else:
                        fig.add_trace(go.Scatter(x=xlab, y=ys, name=nm, mode="lines+markers",
                                                 line=dict(color=clr, width=2)))
                if kind == "bar":
                    fig.update_layout(barmode="group")
                _style(fig, 250)
                fig.update_layout(title=dict(text=label, x=0.5, font=dict(size=12)),
                                  showlegend=False, margin=dict(l=34, r=12, t=34, b=26))
                st.plotly_chart(fig, width="stretch", key=key)

            groups = [
                ("Scoring", [("Points", "bar", lambda b: b["PTS"])]),
                ("Shooting", [
                    ("FG%", "line", lambda b: 100*S.fg_pct(b)),
                    ("3P%", "line", lambda b: 100*S.fg3_pct(b)),
                    ("eFG%", "line", lambda b: 100*S.efg(b)),
                    ("TS%", "line", lambda b: 100*S.ts(b))]),
                ("Playmaking", [
                    ("Assists", "bar", lambda b: b["AST"]),
                    ("Turnovers", "bar", lambda b: b["TOV"])]),
                ("Rebounding", [
                    ("Off. reb", "bar", lambda b: b["ORB"]),
                    ("Def. reb", "bar", lambda b: b["DRB"]),
                    ("Total reb", "bar", lambda b: b["TRB"])]),
                ("Defense", [
                    ("Steals", "bar", lambda b: b["STL"]),
                    ("Blocks", "bar", lambda b: b["BLK"]),
                    ("Stocks", "bar", lambda b: b["stocks"]),
                    ("Fouls", "bar", lambda b: b["PF"])]),
            ]
            for gname, stats in groups:
                st.markdown(f"**{gname}**")
                for i in range(0, len(stats), 3):
                    chunk = stats[i:i + 3]
                    cols = st.columns(len(chunk))
                    for col, (lbl, kind, fn) in zip(cols, chunk):
                        with col:
                            qchart(lbl, kind, fn, f"bs{game_id}_q_{gname}_{lbl}")

            # pace group
            st.markdown("**Pace**")
            pcols = st.columns(2)
            with pcols[0]:
                pf = go.Figure()
                for nm, key, clr in [(t2name, "opp_poss", away), (t1name, "poss", accent)]:
                    pf.add_trace(go.Bar(x=xlab, y=[qb[q][key] for q in qsq], name=nm,
                                        marker_color=clr, marker_line_width=0))
                pf.update_layout(barmode="group", title=dict(text="Possessions", x=0.5,
                                 font=dict(size=12)), showlegend=False,
                                 margin=dict(l=34, r=12, t=34, b=26))
                _style(pf, 250)
                st.plotly_chart(pf, width="stretch", key=f"bs{game_id}_q_poss")
            with pcols[1]:
                lf = go.Figure()
                lf.add_trace(go.Scatter(x=[_q_label(q) for q in sorted(qps)],
                                        y=[round(qps[q]["opp_avg"], 1) for q in sorted(qps)],
                                        name=t2name, mode="lines+markers",
                                        line=dict(color=away, width=2)))
                lf.add_trace(go.Scatter(x=[_q_label(q) for q in sorted(qps)],
                                        y=[round(qps[q]["team_avg"], 1) for q in sorted(qps)],
                                        name=t1name, mode="lines+markers",
                                        line=dict(color=accent, width=2)))
                lf.update_layout(title=dict(text="Avg poss length (s)", x=0.5,
                                 font=dict(size=12)), showlegend=False,
                                 margin=dict(l=34, r=12, t=34, b=26))
                _style(lf, 250)
                st.plotly_chart(lf, width="stretch", key=f"bs{game_id}_q_paceline")

    with tabs[3]:
        _tab_quarters()

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 4 — LINEUPS
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def _tab_lineups():
        st.caption("Observed five-man units and on-court splits from THIS game's "
                   "possessions (a possession = one shot or turnover; FTs excluded). "
                   "Single-game samples are small — read directionally.")
        lc1, lc2 = st.columns([2, 1])
        with lc1:
            team_pick = st.radio("Team", [t1name, t2name], horizontal=True,
                                 key=f"bs{game_id}_lu_team")
        tid = t1id if team_pick == t1name else t2id
        with lc2:
            mp = st.slider("Min possessions", 1, 12, 3, key=f"bs{game_id}_lu_mp")

        units = LU.unit_ratings(tid, [game_id], events=events, min_poss=mp)
        st.markdown("**Five-man units**")
        if not units:
            st.info("No unit cleared the possession threshold — lower the minimum.")
        else:
            udf = pd.DataFrame([{
                "Lineup": " / ".join(n.split()[-1] for n in u["names"]),
                "Poss": u["poss"], "Off": u["off_poss"], "Def": u["def_poss"],
                "ORtg": u["ORtg"], "DRtg": u["DRtg"], "Net": u["Net"],
                "PPP": round(S._safe(u["pts_for"], u["off_poss"]), 2)}
                for u in units])
            st.dataframe(udf, hide_index=True, width="stretch",
                         column_config={"Net": st.column_config.NumberColumn("Net", format="%+.1f")},
                         key=f"bs{game_id}_units_{tid}")

        # custom lineup builder
        st.markdown("**Build a lineup**")
        roster = sorted([b for b in boxes.values() if b["team_id"] == tid],
                        key=lambda b: -b["MIN"])
        name_to_pid = {b["name"]: _pid_of(b, boxes) for b in roster}
        picks = st.multiselect("Pick 2–5 players (possessions where all were on the floor)",
                               list(name_to_pid.keys()), max_selections=5,
                               key=f"bs{game_id}_lu_pick")
        if len(picks) >= 2:
            cu = LU.custom_unit(tid, [name_to_pid[p] for p in picks], [game_id], events=events)
            cc = st.columns(5)
            cc[0].metric("Possessions", cu["poss"])
            cc[1].metric("ORtg", f"{cu['ORtg']:.0f}" if cu["off_poss"] else "—")
            cc[2].metric("DRtg", f"{cu['DRtg']:.0f}" if cu["def_poss"] else "—")
            cc[3].metric("Net", f"{cu['Net']:+.0f}" if cu["poss"] else "—")
            cc[4].metric("PPP", f"{cu['PPP']:.2f}" if cu["off_poss"] else "—")
        else:
            st.caption("Select at least two players.")

        # per-player advanced
        st.markdown("**Player advanced — this game**")
        try:
            ws = WPA.game_wpa(game_id, mode="scoring")["players"]
        except Exception:
            ws = None
        try:
            wpp = WPA.game_wpa(game_id, mode="possession")["players"]
        except Exception:
            wpp = None
        if ws is None or wpp is None:
            st.caption("Win-probability data unavailable for this game.")
        rows = []
        for b in sorted([b for b in boxes.values() if b["team_id"] == tid],
                        key=lambda b: -S.game_score(b)):
            if not any([b["FGA"], b["FTA"], b["MIN"], b["TRB"], b["AST"], b["TOV"]]):
                continue
            pid = _pid_of(b, boxes)
            smoe = None
            if b["FGA"]:
                xfg = S.expected_fg_pct(pid, [game_id], events=events, rates=cr)
                smoe = round((S.fg_pct(b) - xfg) * 100, 1)
            row = {
                "Player": b["name"], "MIN": b["MIN"], "PTS": b["PTS"],
                "GS": round(S.game_score(b), 1), "PER": round(S.per(b), 1),
                "FIC": round(S.fic(b), 1), "TS%": round(100*S.ts(b), 1),
                "VPS": (round(S.vps(b), 2) if S.vps(b) is not None else None)}
            if ws is not None:
                row["WPA"] = round(ws.get(pid, {}).get("wpa", 0.0), 3)
            if wpp is not None:
                row["PossWPA"] = round(wpp.get(pid, {}).get("wpa", 0.0), 3)
            row["SMOE"] = smoe
            rows.append(row)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         column_config={
                             "TS%": st.column_config.ProgressColumn("TS%", format="%.0f",
                                    min_value=0, max_value=100),
                             "VPS": st.column_config.NumberColumn("VPS", format="%.2f"),
                             "WPA": st.column_config.NumberColumn("WPA", format="%+.3f"),
                             "PossWPA": st.column_config.NumberColumn("PossWPA", format="%+.3f"),
                             "SMOE": st.column_config.NumberColumn("SMOE", format="%+.1f")},
                         key=f"bs{game_id}_adv_players_{tid}")
            st.caption("GS = Game Score · PER ≈ Game Score (single-program proxy) · "
                       "FIC = Floor Impact Counter · VPS = Hudl Value Point System "
                       "(value ÷ mistakes) · WPA = win-probability added (scoring) · "
                       "PossWPA = possession-model WPA · SMOE = FG% over expected. "
                       "RAPM/shrunk metrics are season-scale — omitted here. "
                       "GS ranks THIS game only; for who's best on the season use "
                       "OVERALL on the Players page (GS/g is just one input to it).")

        # ── rotation / stint timeline ───────────────────────────────────────
        st.markdown("**Rotation — who was on the floor, when**")
        _rot = GF.rotation(game_id, events=events)
        if not _rot["team_ids"]:
            st.info("No lineup data logged for this game.")
        else:
            _endm = _rot["end"] / 60
            for _tid, _clr in ((t1id, accent), (t2id, away)):
                _rows = _rot["teams"].get(_tid, [])
                if not _rows:
                    continue
                _tname = t1name if _tid == t1id else t2name
                _fig = go.Figure()
                for r in _rows:
                    _last = r["name"].split()[-1] if r["name"] else ""
                    _lbl = f"{'★ ' if r['starter'] else ''}#{r['number']} {_last}"
                    for (s, e) in r["segments"]:
                        _fig.add_trace(go.Bar(
                            x=[(e - s) / 60], y=[_lbl], base=s / 60,
                            orientation="h", marker_color=_clr,
                            marker_line_width=0, showlegend=False,
                            hovertemplate=(f"{r['name']} · {s/60:.0f}–{e/60:.0f} "
                                           f"min<extra></extra>")))
                for _qb in (8, 16, 24, 32, 36, 40):
                    if _qb < _endm:
                        _fig.add_vline(x=_qb, line=dict(color="#30363d", dash="dot"))
                _fig.update_layout(barmode="overlay",
                                   title=f"{_tname} — {len(_rows)} played")
                _fig.update_xaxes(title="Game minute", range=[0, _endm])
                _fig.update_yaxes(autorange="reversed")
                _style(_fig, max(200, 26 * len(_rows) + 90))
                st.plotly_chart(_fig, width="stretch", key=f"bs{game_id}_rot_{_tid}")
            st.caption("Each bar = a stint on the floor (★ = inferred starter). "
                       "Minutes from the elapsed clock between events — more "
                       "complete than the possession-seconds estimate.")

    with tabs[4]:
        _tab_lineups()

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 5 — BOX SCORE
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def _tab_box():
        cols = ["#", "Player", "MIN", "PTS", "FG", "FG%", "3P", "3P%", "FT", "FT%",
                "ORB", "DRB", "REB", "AST", "STL", "BLK", "TOV", "PF", "+/-",
                "SC", "eFG%", "TS%", "GS"]
        roster_all = query(
            "SELECT id AS pid, name, number, team_id FROM players "
            "WHERE team_id IN (?,?) ORDER BY number, name", (t1id, t2id))

        def make_df(tid):
            rows, played = [], set()
            pls = sorted([b for b in boxes.values() if b["team_id"] == tid],
                         key=lambda b: (-b["PTS"], -b["MIN"]))
            for b in pls:
                if not any([b["FGA"], b["FTA"], b["MIN"], b["TRB"], b["AST"],
                            b["PF"], b["TOV"], b["STL"], b["BLK"]]):
                    continue
                played.add(_pid_of(b, boxes))
                rows.append({
                    "#": str(b["number"]), "Player": b["name"], "MIN": b["MIN"], "PTS": b["PTS"],
                    "FG": f"{b['FGM']}-{b['FGA']}", "FG%": round(100*S._safe(b['FGM'],b['FGA']),1),
                    "3P": f"{b['3PM']}-{b['3PA']}", "3P%": round(100*S._safe(b['3PM'],b['3PA']),1),
                    "FT": f"{b['FTM']}-{b['FTA']}", "FT%": round(100*S._safe(b['FTM'],b['FTA']),1),
                    "ORB": b["ORB"], "DRB": b["DRB"], "REB": b["TRB"], "AST": b["AST"],
                    "STL": b["STL"], "BLK": b["BLK"], "TOV": b["TOV"], "PF": b["PF"],
                    "+/-": b["PM"], "SC": b["SC"], "eFG%": round(100*S.efg(b),1),
                    "TS%": round(100*S.ts(b),1), "GS": round(S.game_score(b),1)})
            # DNP — rostered players with nothing recorded this game
            for p in roster_all:
                if p["team_id"] != tid or p["pid"] in played:
                    continue
                rows.append({
                    "#": str(p["number"]), "Player": f"{p['name']} (DNP)", "MIN": 0.0,
                    "PTS": 0, "FG": "0-0", "FG%": 0.0, "3P": "0-0", "3P%": 0.0,
                    "FT": "0-0", "FT%": 0.0, "ORB": 0, "DRB": 0, "REB": 0, "AST": 0,
                    "STL": 0, "BLK": 0, "TOV": 0, "PF": 0, "+/-": 0, "SC": 0,
                    "eFG%": 0.0, "TS%": 0.0, "GS": 0.0})
            tb = _team_total(boxes, tid)
            rows.append({
                "#": "", "Player": "TOTAL", "MIN": None, "PTS": tb["PTS"],
                "FG": f"{tb['FGM']}-{tb['FGA']}", "FG%": round(100*S._safe(tb['FGM'],tb['FGA']),1),
                "3P": f"{tb['3PM']}-{tb['3PA']}", "3P%": round(100*S._safe(tb['3PM'],tb['3PA']),1),
                "FT": f"{tb['FTM']}-{tb['FTA']}", "FT%": round(100*S._safe(tb['FTM'],tb['FTA']),1),
                "ORB": tb["ORB"], "DRB": tb["DRB"], "REB": tb["TRB"], "AST": tb["AST"],
                "STL": tb["STL"], "BLK": tb["BLK"], "TOV": tb["TOV"], "PF": tb["PF"],
                "+/-": None, "SC": tb["SC"], "eFG%": round(100*S.efg(tb),1),
                "TS%": round(100*S.ts(tb),1), "GS": None})
            return pd.DataFrame(rows, columns=cols)

        pcfg = {
            "MIN": st.column_config.NumberColumn("MIN", format="%.1f"),
            "PTS": st.column_config.NumberColumn("PTS", format="%d"),
            "FG%": st.column_config.ProgressColumn("FG%", format="%.0f", min_value=0, max_value=100),
            "3P%": st.column_config.ProgressColumn("3P%", format="%.0f", min_value=0, max_value=100),
            "FT%": st.column_config.ProgressColumn("FT%", format="%.0f", min_value=0, max_value=100),
            "TS%": st.column_config.ProgressColumn("TS%", format="%.0f", min_value=0, max_value=100),
            "eFG%": st.column_config.NumberColumn("eFG%", format="%.1f"),
            "+/-": st.column_config.NumberColumn("+/-", format="%d"),
            "GS": st.column_config.NumberColumn("GS", format="%.1f"),
        }
        glossary_key("MIN", "PTS", "FG%", "3P%", "FT%", "REB", "AST", "STL",
                     "BLK", "TOV", "PF", "+/-", "SC", "eFG%", "TS%", "GS")
        for tid, nm in [(t2id, t2name), (t1id, t1name)]:
            st.markdown(f"**{nm}**")
            df = make_df(tid)
            st.dataframe(df, hide_index=True, width="stretch", column_config=pcfg,
                         key=f"bs{game_id}_box_{tid}")
            st.download_button(f"{nm} box (CSV)", df.to_csv(index=False),
                               file_name=f"box_{game_id}_{nm}.csv", mime="text/csv",
                               key=f"dl_box_{game_id}_{tid}")

        # MaxPreps-friendly combined export: both teams, one row per player, with
        # a Team column and no TOTAL/derived-only cols — so a coach reporting to
        # MaxPreps doesn't have to re-enter the box by hand.
        mp_cols = ["Team", "#", "Player", "MIN", "PTS", "FG", "FG%", "3P", "3P%",
                   "FT", "FT%", "ORB", "DRB", "REB", "AST", "STL", "BLK", "TOV", "PF"]
        mp_rows = []
        for tid, nm in [(t1id, t1name), (t2id, t2name)]:
            for _, rr in make_df(tid).iterrows():
                if rr["Player"] == "TOTAL":
                    continue
                row = {"Team": nm}
                row.update({c: rr[c] for c in mp_cols if c != "Team"})
                mp_rows.append(row)
        mp_df = pd.DataFrame(mp_rows, columns=mp_cols)
        st.download_button(
            "⬇ MaxPreps box — both teams (CSV)", mp_df.to_csv(index=False),
            file_name=f"maxpreps_box_{game_id}_{t1name}_vs_{t2name}.csv",
            mime="text/csv", key=f"dl_maxpreps_{game_id}")

    with tabs[5]:
        _tab_box()

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 6 — FOUR FACTORS
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def _tab_factors():
        tb_ta, ob_ta = TA.team_and_opp_box(t1id, [game_id], events=events)
        ff_h = TA.four_factors(tb_ta, ob_ta)["off"]
        ff_a = TA.four_factors(ob_ta, tb_ta)["off"]
        FACTORS = [("eFG", "eFG%", "high"), ("TOV", "TOV%", "low"),
                   ("ORB", "ORB%", "high"), ("FTR", "FT rate", "high")]
        st.caption("Dean Oliver's Four Factors — each team's own offense. eFG% ≈40%, "
                   "TOV% ≈25% (lower better), ORB% ≈20%, FT rate ≈15% of winning.")

        ffig = go.Figure()
        cats = [lbl for _, lbl, _ in FACTORS]
        for nm, ff, clr in [(t2name, ff_a, away), (t1name, ff_h, accent)]:
            ys = [round(100*ff[k], 1) for k, _, _ in FACTORS]
            ffig.add_trace(go.Bar(x=cats, y=ys, name=nm, marker_color=clr,
                                  marker_line_width=0, text=[f"{v:.0f}" for v in ys],
                                  **_bar("%{text}")))
        ffig.update_layout(barmode="group")
        ffig.update_yaxes(title="%")
        _style(ffig, 360)
        st.plotly_chart(ffig, width="stretch", key=f"bs{game_id}_four_factors")

        rows, edges = [], []
        for k, lbl, better in FACTORS:
            hv, avv = 100*ff_h[k], 100*ff_a[k]
            if better == "high":
                win = t1name if hv > avv else (t2name if avv > hv else "—")
            else:
                win = t1name if hv < avv else (t2name if avv < hv else "—")
            rows.append({"Factor": lbl, t2name: f"{avv:.1f}%", t1name: f"{hv:.1f}%",
                         "Edge": win})
            edges.append(win)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     key=f"bs{game_id}_ff_tbl")
        h_edges = sum(1 for e in edges if e == t1name)
        a_edges = sum(1 for e in edges if e == t2name)
        e1, e2 = st.columns(2)
        e1.metric(f"{t1name} factor edges", h_edges)
        e2.metric(f"{t2name} factor edges", a_edges)

    with tabs[6]:
        _tab_factors()

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 7 — PLAY TYPES  (explicit one-tap set-call tags, league-ranked)
    # ════════════════════════════════════════════════════════════════════════
    @st.fragment
    def _tab_playtypes():
        side = st.radio("Lens", ["Offense (we ran)", "Defense (we allowed)"],
                        horizontal=True, key=f"bs{game_id}_pt_side")
        offense = side.startswith("Offense")
        st.caption("Your one-tap **Play type** tags on this game's shots, ranked "
                   "against the league. PPP = points per possession (a shot ends "
                   "the possession). On defense, allowing fewer points ranks higher.")

        _ptcfg = {
            "PPP": st.column_config.NumberColumn("PPP", format="%.2f"),
            "FG%": st.column_config.NumberColumn("FG%", format="%.0f%%"),
            "Share": st.column_config.NumberColumn("Share", format="%.0f%%"),
            "Pct": st.column_config.NumberColumn("Pct", format="%.0f"),
        }
        _rcfg = {
            "PPP": st.column_config.NumberColumn("PPP", format="%.2f"),
            "FG%": st.column_config.NumberColumn("FG%", format="%.0f%%"),
            "eFG%": st.column_config.NumberColumn("eFG%", format="%.0f%%"),
            "3PA%": st.column_config.NumberColumn("3PA%", format="%.0f%%"),
        }
        _fpcfg = {
            "3PA%": st.column_config.NumberColumn("3PA%", format="%.0f%%"),
            "Rim%": st.column_config.NumberColumn("Rim%", format="%.0f%%"),
            "Assisted%": st.column_config.NumberColumn("Assisted%", format="%.0f%%"),
            "Open%": st.column_config.NumberColumn("Open%", format="%.0f%%"),
            "avg s": st.column_config.NumberColumn("avg s", format="%.1f"),
        }

        for tid, nm in [(t1id, t1name), (t2id, t2name)]:
            st.markdown(f"**{nm}**")
            pt = PT.team_named_playtype_percentiles(
                tid, gender=g["gender"], game_ids=[game_id], events=events,
                offense=offense)
            rows = pt["rows"]
            if not rows:
                st.caption("No play-type tags yet — add a one-tap **Play type** to a "
                           "shot in the Game Tracker (Pick & roll, Iso, Post-up…) and "
                           "this fills in.")
            else:
                # KPI callouts: most-used (max share), best/worst PPP among poss>=3
                _ranked = [r for r in rows if r["poss"] >= 3]
                _most = max(rows, key=lambda r: r["share"], default=None)
                _best = max(_ranked, key=lambda r: r["PPP"], default=None)
                _worst = min(_ranked, key=lambda r: r["PPP"], default=None)
                kc = st.columns(3)
                for col, lbl, r in [(kc[0], "Most used", _most),
                                    (kc[1], "Best PPP", _best),
                                    (kc[2], "Worst PPP", _worst)]:
                    if r:
                        col.markdown(
                            f"<div class='kpi-tile'><div class='kpi-label'>{lbl}</div>"
                            f"<div class='kpi-value'>{r['label']}</div>"
                            f"<div class='kpi-sub'>{r['PPP']:.2f} PPP · "
                            f"{r['poss']} poss</div></div>", unsafe_allow_html=True)
                    else:
                        col.markdown(
                            f"<div class='kpi-tile'><div class='kpi-label'>{lbl}</div>"
                            f"<div class='kpi-value'>—</div>"
                            f"<div class='kpi-sub'>need 3+ poss</div></div>",
                            unsafe_allow_html=True)

                # horizontal PPP bar — one row per tagged set call, shaded by FG%
                _bn = [r["label"] for r in rows]
                _bv = [round(r["PPP"], 2) for r in rows]
                _bc = [_heat(r["FG%"]) for r in rows]
                _bt = [f"{r['PPP']:.2f} · {r['poss']}p" for r in rows]
                ptfig = go.Figure(go.Bar(
                    x=_bv, y=_bn, orientation="h", marker_color=_bc,
                    marker_line_width=0, text=_bt, textposition="auto",
                    textfont=dict(size=11), cliponaxis=False,
                    hovertemplate="%{y}: %{text}<extra></extra>"))
                _style(ptfig, 300)
                ptfig.update_layout(margin=dict(l=4, r=14, t=8, b=34))
                ptfig.update_xaxes(
                    title=f"Points per possession ({'scored' if offense else 'allowed'})")
                ptfig.update_yaxes(showgrid=False, automargin=True)
                st.plotly_chart(ptfig, width="stretch",
                                key=f"bs{game_id}_pt_bar_{tid}")

                # ranked table (Play call / Poss / PPP / FG% / Share / Pct / Tier)
                df = pd.DataFrame([{
                    "Play call": r["label"], "Poss": r["poss"],
                    "PPP": round(r["PPP"], 2), "FG%": round(r["FG%"] * 100, 0),
                    "Share": round(r["share"] * 100, 0),
                    "Pct": r["pct"], "Tier": r["tier"]} for r in rows])
                st.dataframe(df, hide_index=True, width="stretch",
                             column_config=_ptcfg, key=f"bs{game_id}_pt_tbl_{tid}")
                st.caption(f"{pt['total_tagged']} tagged · {pt['untagged']} untagged. "
                           "Pct = league percentile · Tier shades good→poor (shot-"
                           "quality color encodes the bar above).")

                # ── set fingerprint (how each set is GENERATED) ─────────────
                _prof = PT.team_playtype_shot_profiles(
                    tid, gender=g["gender"], game_ids=[game_id], events=events,
                    offense=offense)
                if _prof:
                    fdf = pd.DataFrame([{
                        "Set": p["label"],
                        "3PA%": round(p["3PA_rate"] * 100, 0),
                        "Rim%": round(p["rim_rate"] * 100, 0),
                        "Assisted%": round(p["ast_rate"] * 100, 0),
                        "Open%": round(p["open_rate"] * 100, 0),
                        "Where": (ZONE_LABELS.get(p["top_zone"], p["top_zone"])
                                  if p["top_zone"] else "—"),
                        "avg s": (round(p["avg_secs"], 1)
                                  if p["avg_secs"] is not None else None)}
                        for p in _prof.values()])
                    st.markdown("*Set fingerprint*")
                    st.dataframe(fdf, hide_index=True, width="stretch",
                                 column_config=_fpcfg,
                                 key=f"bs{game_id}_pt_profile_{tid}")
                    st.caption("How each set is generated — 3PA% = 3-point hunt, "
                               "Rim% = paint pressure, Where = zone it lives in.")

            # ── ball-screen role split (handler vs roller) ──────────────────
            roles = PT.team_role_splits(tid, game_ids=[game_id], events=events,
                                        offense=offense)
            _shown = False
            for key, label in PT.NAMED_PLAY_TYPES:
                rs = roles.get(key)
                if not rs or rs["all"]["poss"] <= 0:
                    continue
                if key not in PT.ROLE_SPLIT_KEYS:
                    continue
                if not _shown:
                    st.markdown("*Ball-screen role split (handler vs roller)*  \n"
                                "<span style='font-size:.82em;opacity:.7'>"
                                "roller 3PA% high = pops for 3 (low = rolls to "
                                "the rim)</span>", unsafe_allow_html=True)
                    _shown = True
                rdf = pd.DataFrame([{
                    "Role": rlbl, "Poss": rs[rk]["poss"], "FGM": rs[rk]["FGM"],
                    "PPP": round(rs[rk]["PPP"], 2), "FG%": round(rs[rk]["FG%"] * 100, 0),
                    "eFG%": round(rs[rk]["eFG"] * 100, 0),
                    "3PA%": round(rs[rk].get("3PA_rate", 0.0) * 100, 0)}
                    for rk, rlbl in [("handler", "Handler"), ("roller", "Roller"),
                                     ("all", "All")] if rs[rk]["poss"] > 0])
                st.markdown(f"&nbsp;&nbsp;{label}", unsafe_allow_html=True)
                st.dataframe(rdf, hide_index=True, width="stretch",
                             column_config=_rcfg,
                             key=f"bs{game_id}_role_{tid}_{key}")

            # ── hand-off / inbounds hubs (who initiates) ────────────────────
            def _pname(_pid):
                _b = boxes.get(_pid)
                return _b["name"] if _b else "—"

            _feeders = PT.team_playtype_feeders(
                tid, gender=g["gender"], game_ids=[game_id], events=events,
                offense=offense)
            _frows = []
            for key, fk in _feeders.items():
                for f in fk["feeders"]:
                    _frows.append({
                        "Type": fk["label"],
                        "Initiator": _pname(f["feeder_id"]),
                        "Feeds": f["feeds"],
                        "PPP": round(f["PPP"], 2),
                        "FG%": round(f["FG%"] * 100, 0),
                        "Top target": _pname(f["top_target_id"])})
            if _frows:
                st.markdown("*Hand-off & inbounds hubs (who initiates)*")
                st.dataframe(pd.DataFrame(_frows), hide_index=True,
                             width="stretch", column_config=_rcfg,
                             key=f"bs{game_id}_pt_feeders_{tid}")

    with tabs[7]:
        _tab_playtypes()

    # ════════════════════════════════════════════════════════════════════════
    #  TAB 8 — DEFENSE  (the one-tap defense-scheme tag, this game)
    # ════════════════════════════════════════════════════════════════════════
    # The defensive companion to Play Types: PPP by the explicit `defense` scheme
    # tag for THIS game, per team, with the play-type × defense cross-tab and the
    # press/trap disruption (TOs + fouls per scheme). Mirrors _tab_playtypes.
    @st.fragment
    def _tab_defense():
        side = st.radio("Lens", ["Our defense (we ran)", "Defenses we faced"],
                        horizontal=True, key=f"bs{game_id}_def_side")
        offense = side == "Defenses we faced"   # True => defenses this team FACED
        st.caption("The one-tap **Defense** scheme tag on this game's shots — "
                   "man / zone / press / trap / junk, ranked vs the league. PPP = "
                   "points per possession; on defense, allowing fewer ranks higher. "
                   "Sticky in the tracker, so one tap covers a whole stretch.")

        _dcfg = {
            "PPP": st.column_config.NumberColumn("PPP", format="%.2f"),
            "FG%": st.column_config.NumberColumn("FG%", format="%.0f%%"),
            "Share": st.column_config.NumberColumn("Share", format="%.0f%%"),
            "Pct": st.column_config.NumberColumn("Pct", format="%.0f"),
        }
        _fpcfg = {
            "3PA%": st.column_config.NumberColumn("3PA%", format="%.0f%%"),
            "Rim%": st.column_config.NumberColumn("Rim%", format="%.0f%%"),
            "Assisted%": st.column_config.NumberColumn("Assisted%", format="%.0f%%"),
            "Open%": st.column_config.NumberColumn("Open%", format="%.0f%%"),
            "avg s": st.column_config.NumberColumn("avg s", format="%.1f"),
        }

        for tid, nm in [(t1id, t1name), (t2id, t2name)]:
            st.markdown(f"**{nm}**")
            dv = DEF.team_defense_percentiles(
                tid, gender=g["gender"], game_ids=[game_id], events=events,
                offense=offense)
            rows = dv["rows"]
            if not rows:
                st.caption("No defense tags yet — set the **Defense** (man, 2-3, "
                           "press…) on shots in the Game Tracker; it's sticky, so "
                           "one tap covers a whole stretch.")
            else:
                # KPI tiles — Most used (max share), Best / Worst by league pct
                # (good-oriented, so it's correct on either side of the ball).
                _ranked = [r for r in rows if r["poss"] >= 3 and r["pct"] is not None]
                _most = max(rows, key=lambda r: r["share"], default=None)
                _best = max(_ranked, key=lambda r: r["pct"], default=None)
                _worst = min(_ranked, key=lambda r: r["pct"], default=None)
                kc = st.columns(3)
                for col, lbl, r in [(kc[0], "Most used", _most),
                                    (kc[1], "Best", _best), (kc[2], "Worst", _worst)]:
                    if r:
                        col.markdown(
                            f"<div class='kpi-tile'><div class='kpi-label'>{lbl}</div>"
                            f"<div class='kpi-value'>{r['label']}</div>"
                            f"<div class='kpi-sub'>{r['PPP']:.2f} PPP · "
                            f"{r['poss']} poss</div></div>", unsafe_allow_html=True)
                    else:
                        col.markdown(
                            f"<div class='kpi-tile'><div class='kpi-label'>{lbl}</div>"
                            f"<div class='kpi-value'>—</div>"
                            f"<div class='kpi-sub'>need 3+ poss</div></div>",
                            unsafe_allow_html=True)

                # horizontal PPP bar — one row per scheme, shaded by FG%
                _bn = [r["label"] for r in rows]
                _bv = [round(r["PPP"], 2) for r in rows]
                _bc = [_heat(r["FG%"]) for r in rows]
                _bt = [f"{r['PPP']:.2f} · {r['poss']}p" for r in rows]
                dfig = go.Figure(go.Bar(
                    x=_bv, y=_bn, orientation="h", marker_color=_bc,
                    marker_line_width=0, text=_bt, textposition="auto",
                    textfont=dict(size=11), cliponaxis=False,
                    hovertemplate="%{y}: %{text}<extra></extra>"))
                _style(dfig, 300)
                dfig.update_layout(margin=dict(l=4, r=14, t=8, b=34))
                dfig.update_xaxes(
                    title=f"Points per possession ({'scored' if offense else 'allowed'})")
                dfig.update_yaxes(showgrid=False, automargin=True)
                st.plotly_chart(dfig, width="stretch",
                                key=f"bs{game_id}_def_bar_{tid}")

                # ranked table
                df = pd.DataFrame([{
                    "Defense": r["label"], "Poss": r["poss"],
                    "PPP": round(r["PPP"], 2), "FG%": round(r["FG%"] * 100, 0),
                    "Share": round(r["share"] * 100, 0),
                    "Pct": r["pct"], "Tier": r["tier"]} for r in rows])
                st.dataframe(df, hide_index=True, width="stretch",
                             column_config=_dcfg, key=f"bs{game_id}_def_tbl_{tid}")
                st.caption(f"{dv['total_tagged']} tagged · {dv['untagged']} untagged. "
                           "Pct = league percentile · Tier shades good→poor.")

                # family rollup (man / zone / press …)
                fam = DEF.team_defense_families(
                    tid, gender=g["gender"], game_ids=[game_id], events=events,
                    offense=offense)
                if fam["rows"]:
                    famdf = pd.DataFrame([{
                        "Family": r["label"], "Poss": r["poss"],
                        "Share": round(r["share"] * 100, 0),
                        "PPP": round(r["PPP"], 2)} for r in fam["rows"]])
                    st.markdown("*By family*")
                    st.dataframe(famdf, hide_index=True, width="stretch",
                                 column_config={
                                     "Share": st.column_config.NumberColumn("Share", format="%.0f%%"),
                                     "PPP": st.column_config.NumberColumn("PPP", format="%.2f")},
                                 key=f"bs{game_id}_def_fam_{tid}")

                # scheme fingerprint (how shots vs each scheme are generated)
                _prof = DEF.team_defense_shot_profiles(
                    tid, gender=g["gender"], game_ids=[game_id], events=events,
                    offense=offense)
                if _prof:
                    fdf = pd.DataFrame([{
                        "Defense": p["label"],
                        "3PA%": round(p["3PA_rate"] * 100, 0),
                        "Rim%": round(p["rim_rate"] * 100, 0),
                        "Assisted%": round(p["ast_rate"] * 100, 0),
                        "Open%": round(p["open_rate"] * 100, 0),
                        "Where": (ZONE_LABELS.get(p["top_zone"], p["top_zone"])
                                  if p["top_zone"] else "—"),
                        "avg s": (round(p["avg_secs"], 1)
                                  if p["avg_secs"] is not None else None)}
                        for p in _prof.values()])
                    st.markdown("*Scheme fingerprint*")
                    st.dataframe(fdf, hide_index=True, width="stretch",
                                 column_config=_fpcfg,
                                 key=f"bs{game_id}_def_prof_{tid}")

            # ── play type × defense cross-tab (needs both tags on a shot) ───
            cx = DEF.cross_play_defense(
                tid, gender=g["gender"], game_ids=[game_id], events=events,
                offense=offense)
            if cx["plays"] and cx["defenses"]:
                _dl, _pl, _mx = cx["def_label"], cx["play_label"], cx["matrix"]
                _grid = []
                for pk in cx["plays"]:
                    _r = {"Set": _pl.get(pk, pk)}
                    for dk in cx["defenses"]:
                        c = _mx.get(pk, {}).get(dk)
                        _r[_dl.get(dk, dk)] = (round(c["PPP"], 2)
                                               if c and c["stable"] else None)
                    _grid.append(_r)
                st.markdown("*Play type × defense — PPP*")
                st.dataframe(pd.DataFrame(_grid), hide_index=True, width="stretch",
                             key=f"bs{game_id}_def_cross_{tid}")
                st.caption("PPP per set vs scheme (cells with ≥4 poss; blank = thin).")

            # ── disruption: turnovers + fouls per scheme ────────────────────
            tv = DEF.team_defense_turnovers(
                tid, gender=g["gender"], game_ids=[game_id], events=events,
                offense=offense)
            fl = DEF.team_defense_fouls(
                tid, gender=g["gender"], game_ids=[game_id], events=events,
                offense=offense)
            if tv["rows"] or fl["rows"]:
                _to = {r["key"]: r for r in tv["rows"]}
                _fo = {r["key"]: r for r in fl["rows"]}
                _keys = list(dict.fromkeys(list(_to) + list(_fo)))
                _tcol = "TOs " + ("forced" if not offense else "committed")
                _fcol = "Fouls " + ("committed" if not offense else "drawn")
                ddf = pd.DataFrame([{
                    "Defense": (_to.get(k) or _fo.get(k))["label"],
                    _tcol: _to.get(k, {}).get("tovs", 0),
                    _fcol: _fo.get(k, {}).get("fouls", 0)} for k in _keys])
                st.markdown("*Disruption — turnovers & fouls per scheme*")
                st.dataframe(ddf, hide_index=True, width="stretch",
                             key=f"bs{game_id}_def_disrupt_{tid}")

    with tabs[8]:
        _tab_defense()

    st.caption("Recomputed from game_events. Box/advanced formulas in helpers/stats.py; "
               "team, shot-quality & lineup engines in helpers/team_analytics.py + "
               "helpers/lineups.py + helpers/wpa.py. PF credited to the fouler.")


# ══════════════════════════════════════════════════════════════════════════════
#  SMALL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _pid_of(box, boxes):
    """Recover a player_id key from a decorated box dict (boxes is {pid: box})."""
    for pid, b in boxes.items():
        if b is box:
            return pid
    # fallback: match by name + team
    for pid, b in boxes.items():
        if b.get("name") == box.get("name") and b.get("team_id") == box.get("team_id"):
            return pid
    return None


def _heat(frac):
    """FG% fraction → red→amber→green colour, spread over a 20–60% range."""
    t = max(0.0, min(1.0, (frac - 0.20) / 0.40))
    if t < 0.5:
        u = t / 0.5
        r, g, b = 231 + (240 - 231) * u, 76 + (165 - 76) * u, 60 + (0 - 60) * u
    else:
        u = (t - 0.5) / 0.5
        r, g, b = 240 + (63 - 240) * u, 165 + (185 - 165) * u, 0 + (80 - 0) * u
    return f"rgb({int(r)},{int(g)},{int(b)})"


def _zone_tile(label, fgm, fga):
    """A heat-shaded zone tile: label + FG% on the colour block, FGM/FGA below."""
    if not fga:
        bg, pct, rec = "#21262d", "—", "0/0"
    else:
        bg, pct, rec = _heat(fgm / fga), f"{100*fgm/fga:.0f}%", f"{fgm}/{fga}"
    return (f"<div style='border-radius:10px;overflow:hidden;border:1px solid #30363d'>"
            f"<div style='background:{bg};padding:8px 4px;text-align:center'>"
            f"<div style='font-size:11px;font-weight:700;color:#0d1117'>{label}</div>"
            f"<div style='font-size:18px;font-weight:900;color:#0d1117'>{pct}</div></div>"
            f"<div style='padding:6px 4px;text-align:center;background:#161b22'>"
            f"<div style='font-size:14px;font-weight:700;color:#c9d1d9'>{rec}</div>"
            f"<div style='font-size:10px;color:#8b949e'>FGM/FGA</div></div></div>")
