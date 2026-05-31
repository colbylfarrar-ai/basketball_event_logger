"""
7_Schedule.py — Calendar-style, one-stop view of every game day.

Pick a month, click a day on the calendar, and the page unfolds everything that
happened: a day-at-a-glance summary, the Game of the Day, the biggest upset,
the day's stat leaders (tracked games), and every final with a full box score
one click away. Built on the same engine + box-score report as the rest of the
app, so it always agrees with the source of truth.

This is the APP4.0 successor to APP3.0's "Daily Breakdown" — the static HTML
calendar is now an interactive, clickable grid.
"""
import sys
import calendar as _cal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

import numpy as np
import streamlit as st

from database.db import query
from helpers.box_score import render_box_score
from helpers.ui import page_chrome
import helpers.team_ratings as TR
import helpers.stats as S

_cfg, ACCENT = page_chrome()

# ── Page-specific CSS (calendar grid + upset/leader cards) ──────────────────────
st.markdown("""
<style>
.cal-dow { font-size:10px; font-weight:700; color:#8b949e; text-align:center;
           text-transform:uppercase; letter-spacing:1px; padding:2px 0 6px; }
.cal-month-lbl { font-size:22px; font-weight:800; color:#f0f6fc; text-align:center;
                 line-height:1.4; }
.cal-legend { display:flex; gap:18px; margin:10px 2px 4px; align-items:center;
              flex-wrap:wrap; }
.cal-legend-item { display:flex; align-items:center; gap:6px;
                   font-size:11px; color:#8b949e; }
.cal-dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
/* shrink the calendar day buttons so the grid reads like a calendar */
div[data-testid="column"] .stButton > button { min-height:46px; padding:4px 2px; }
.upset-card {
    background:linear-gradient(135deg,#1a0a0a,#2a0d0d);
    border:1px solid #e74c3c; border-radius:12px;
    padding:16px 18px; margin-bottom:10px;
}
.upset-title { font-size:14px; font-weight:800; color:#e74c3c; margin-bottom:6px; }
.upset-body  { font-size:14px; color:#c9d1d9; }
.gotd-badge {
    display:inline-block; background:#0d419d; color:#fff; font-size:10px;
    font-weight:700; letter-spacing:1px; border-radius:20px; padding:3px 10px;
    text-transform:uppercase; margin-top:8px;
}
.tracked-badge {
    display:inline-block; background:#0d419d; color:#fff; font-size:9px;
    font-weight:700; letter-spacing:1px; border-radius:10px; padding:2px 8px;
    text-transform:uppercase; margin-left:6px;
}
</style>
""", unsafe_allow_html=True)

st.title("Schedule")
st.caption("A calendar of every game day. Click a day to see what happened — "
           "the headline game, the biggest upset, the day's leaders and every "
           "final with a full box score.")


# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def _day_counts():
    """{ISO date: game count}. Dates are already ISO-normalised in the DB."""
    rows = query("SELECT date, COUNT(*) AS cnt FROM games "
                 "WHERE date IS NOT NULL AND date <> '' GROUP BY date")
    return {r["date"]: r["cnt"] for r in rows}


@st.cache_data(ttl=600, show_spinner=False)
def _games_on(date_str):
    return query("""
        SELECT g.id, g.date, g.location, g.tracked,
               g.home_score, g.away_score, g.team1_id, g.team2_id,
               t1.name AS t1, t2.name AS t2
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE g.date = ?
        ORDER BY g.tracked DESC, g.id
    """, (date_str,)) or []


@st.cache_data(ttl=600, show_spinner=False)
def _rank_of():
    """{team_id: rank} from results-only ratings (per-gender ranks)."""
    out = {}
    for gdr in ("M", "F"):
        for tid, r in TR.score_ratings(gender=gdr).items():
            out[tid] = r["Rank"]
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _player_meta():
    return {r["id"]: (r["name"], r["team"]) for r in query(
        "SELECT p.id, p.name, t.name AS team "
        "FROM players p JOIN teams t ON t.id = p.team_id")}


counts = _day_counts()
if not counts:
    st.info("No games with dates yet. Add games in the Input Hub and they'll "
            "appear on the calendar here.")
    st.stop()

all_dates = sorted(counts)
first_ym, last_ym = all_dates[0][:7], all_dates[-1][:7]

st.session_state.setdefault("sched_ym", all_dates[-1][:7])
st.session_state.setdefault("sched_sel", all_dates[-1])


def _shift_month(ym, delta):
    y, m = int(ym[:4]), int(ym[5:7])
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _fmt_long(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%A, %B %d, %Y")
    except Exception:
        return d


# ══════════════════════════════════════════════════════════════════════════════
#  MONTH NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
ym = st.session_state["sched_ym"]
y, m = int(ym[:4]), int(ym[5:7])

nav_l, nav_c, nav_r = st.columns([1, 3, 1])
with nav_l:
    if st.button("◀ Prev", width="stretch", disabled=ym <= first_ym):
        st.session_state["sched_ym"] = _shift_month(ym, -1)
        st.rerun()
with nav_c:
    st.markdown(
        f"<div class='cal-month-lbl'>{_cal.month_name[m]} {y}</div>",
        unsafe_allow_html=True)
with nav_r:
    if st.button("Next ▶", width="stretch", disabled=ym >= last_ym):
        st.session_state["sched_ym"] = _shift_month(ym, 1)
        st.rerun()

# Quick-jump to any month that actually has games
months_with_games = sorted({d[:7] for d in all_dates})
if len(months_with_games) > 1:
    jump = st.selectbox(
        "Jump to a month with games", months_with_games,
        index=months_with_games.index(ym) if ym in months_with_games
        else len(months_with_games) - 1,
        format_func=lambda s: datetime.strptime(s, "%Y-%m").strftime("%B %Y"),
        key="sched_jump")
    if jump != ym:
        st.session_state["sched_ym"] = jump
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  CALENDAR GRID  (clickable)
# ══════════════════════════════════════════════════════════════════════════════
def _load_dot(cnt):
    return "🟢" if cnt <= 2 else "🟡" if cnt <= 5 else "🔴"


hdr = st.columns(7)
for i, dow in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
    hdr[i].markdown(f"<div class='cal-dow'>{dow}</div>", unsafe_allow_html=True)

first_wd, ndays = _cal.monthrange(y, m)        # first_wd: 0=Mon
flat = [None] * first_wd + list(range(1, ndays + 1))
while len(flat) % 7:
    flat.append(None)

for wk in range(0, len(flat), 7):
    cols = st.columns(7)
    for i, dd in enumerate(flat[wk:wk + 7]):
        if dd is None:
            cols[i].write("")
            continue
        iso = f"{y:04d}-{m:02d}-{dd:02d}"
        cnt = counts.get(iso, 0)
        if cnt > 0:
            selected = iso == st.session_state["sched_sel"]
            if cols[i].button(f"{dd}  {_load_dot(cnt)}", key=f"cal_{iso}",
                              width="stretch",
                              type="primary" if selected else "secondary"):
                st.session_state["sched_sel"] = iso
                st.rerun()
        else:
            cols[i].button(f"{dd}", key=f"cal_{iso}",
                           width="stretch", disabled=True)

st.markdown("""
<div class="cal-legend">
  <span style="font-size:11px;color:#8b949e;font-weight:700">GAME LOAD</span>
  <span class="cal-legend-item"><span class="cal-dot" style="background:#2ecc71"></span>1–2 games</span>
  <span class="cal-legend-item"><span class="cal-dot" style="background:#f0a500"></span>3–5 games</span>
  <span class="cal-legend-item"><span class="cal-dot" style="background:#e74c3c"></span>6+ games</span>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SELECTED DAY
# ══════════════════════════════════════════════════════════════════════════════
sel = st.session_state["sched_sel"]
day_games = _games_on(sel)

st.markdown("---")
st.markdown(f"### {_fmt_long(sel)}")

if not day_games:
    st.info("No games on this day. Pick a highlighted day on the calendar.")
    st.stop()

scored = [g for g in day_games
          if g["home_score"] is not None and g["away_score"] is not None]
tracked_games = [g for g in day_games if g["tracked"]]

# ── Day at a Glance ─────────────────────────────────────────────────────────────
st.markdown("<div class='section-hdr'>Day at a Glance</div>",
            unsafe_allow_html=True)

if scored:
    pts = [s for g in scored for s in (g["home_score"], g["away_score"])]
    margins = [abs(g["home_score"] - g["away_score"]) for g in scored]
    avg_score = float(np.mean(pts))
    largest_mov = int(max(margins))
else:
    avg_score, largest_mov = 0.0, 0

c = st.columns(4)
c[0].metric("Games", str(len(day_games)))
c[1].metric("Avg team score", f"{avg_score:.1f}" if scored else "—")
c[2].metric("Largest margin", str(largest_mov) if scored else "—")
c[3].metric("Tracked", str(len(tracked_games)))

# ── Game of the Day ─────────────────────────────────────────────────────────────
st.markdown("<div class='section-hdr'>Game of the Day</div>",
            unsafe_allow_html=True)

if scored:
    gotd = max(scored, key=lambda g: g["home_score"] + g["away_score"])
    hs, as_ = gotd["home_score"], gotd["away_score"]
    h_win = hs >= as_
    badge = ("<div class='gotd-badge'>Tracked · full box inside</div>"
             if gotd["tracked"] else "")
    st.markdown(f"""
    <div class="game-hero">
        <div style="font-size:12px;color:#8b949e;margin-bottom:8px">
            {gotd['location'] or 'Highest-scoring game of the day'}
        </div>
        <table style="width:100%;border:none"><tr>
          <td style="width:42%;text-align:center">
            <div style="font-size:16px;font-weight:700;color:#c9d1d9">
              {'▸ ' if not h_win else ''}{gotd['t2']}</div>
            <div style="font-size:46px;font-weight:900;line-height:1;
                 color:{ACCENT if not h_win else '#555d68'}">{as_}</div>
          </td>
          <td style="width:16%;text-align:center;color:#8b949e;font-size:18px">@</td>
          <td style="width:42%;text-align:center">
            <div style="font-size:16px;font-weight:700;color:#c9d1d9">
              {'▸ ' if h_win else ''}{gotd['t1']}</div>
            <div style="font-size:46px;font-weight:900;line-height:1;
                 color:{ACCENT if h_win else '#555d68'}">{hs}</div>
          </td>
        </tr></table>
        {badge}
    </div>
    """, unsafe_allow_html=True)

    if gotd["tracked"]:
        with st.expander("📊 Full report — Game of the Day"):
            render_box_score(gotd["id"])
else:
    st.info("No final scores yet for this day.")

# ── Upset Alert ─────────────────────────────────────────────────────────────────
st.markdown("<div class='section-hdr'>Upset Alert</div>",
            unsafe_allow_html=True)

rank_of = _rank_of()
best = None
for g in scored:
    if g["home_score"] == g["away_score"]:
        continue
    h_win = g["home_score"] > g["away_score"]
    win_id, lose_id = ((g["team1_id"], g["team2_id"]) if h_win
                       else (g["team2_id"], g["team1_id"]))
    win_name, lose_name = ((g["t1"], g["t2"]) if h_win else (g["t2"], g["t1"]))
    wr, lr = rank_of.get(win_id), rank_of.get(lose_id)
    if wr is None or lr is None or wr <= lr:
        continue
    diff = wr - lr
    score = (f"{max(g['home_score'], g['away_score'])}–"
             f"{min(g['home_score'], g['away_score'])}")
    if best is None or diff > best["diff"]:
        best = {"win": win_name, "lose": lose_name, "wr": wr, "lr": lr,
                "diff": diff, "score": score}

if best:
    st.markdown(f"""
    <div class="upset-card">
        <div class="upset-title">🚨 Biggest upset of the day</div>
        <div class="upset-body">
            <b>#{best['wr']} {best['win']}</b> beat
            <b>#{best['lr']} {best['lose']}</b> ({best['score']})
            — a <b>{best['diff']}-spot</b> ranking upset.
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.caption("No upsets — higher-ranked teams held serve (or no ranking data "
               "for the day's matchups).")

# ── Day's Leaders (tracked games only) ──────────────────────────────────────────
if tracked_games:
    st.markdown("<div class='section-hdr'>Day's Leaders</div>",
                unsafe_allow_html=True)

    pmeta = _player_meta()
    best_pts = best_reb = best_ast = None  # (value, player_id)
    for g in tracked_games:
        for pid, b in S.aggregate_player_boxes([g["id"]]).items():
            if best_pts is None or b["PTS"] > best_pts[0]:
                best_pts = (b["PTS"], pid)
            if best_reb is None or b["TRB"] > best_reb[0]:
                best_reb = (b["TRB"], pid)
            if best_ast is None or b["AST"] > best_ast[0]:
                best_ast = (b["AST"], pid)

    def _who(pid):
        name, team = pmeta.get(pid, ("?", ""))
        return f"{name} ({team})"

    l = st.columns(3)
    if best_pts and best_pts[0] > 0:
        l[0].metric("🏀 Top scorer", f"{int(best_pts[0])} PTS", _who(best_pts[1]))
    else:
        l[0].metric("🏀 Top scorer", "—")
    if best_reb and best_reb[0] > 0:
        l[1].metric("💪 Top rebounder", f"{int(best_reb[0])} REB", _who(best_reb[1]))
    else:
        l[1].metric("💪 Top rebounder", "—")
    if best_ast and best_ast[0] > 0:
        l[2].metric("🎯 Top playmaker", f"{int(best_ast[0])} AST", _who(best_ast[1]))
    else:
        l[2].metric("🎯 Top playmaker", "—")

# ── All Results ─────────────────────────────────────────────────────────────────
st.markdown("<div class='section-hdr'>All Results</div>", unsafe_allow_html=True)

for g in day_games:
    hs, as_ = g["home_score"], g["away_score"]
    has_score = hs is not None and as_ is not None
    t1_win = has_score and hs > as_
    t2_win = has_score and as_ > hs

    if has_score:
        t1_cls = "score-winner" if t1_win else "score-loser"
        t2_cls = "score-winner" if t2_win else "score-loser"
        hs_s, as_s = str(int(hs)), str(int(as_))
        meta = (f"Margin {abs(int(hs) - int(as_))}" if hs != as_ else "Tie")
    else:
        t1_cls = t2_cls = "score-loser"
        hs_s = as_s = "—"
        meta = "No score yet"

    tracked_badge = ("<span class='tracked-badge'>tracked</span>"
                     if g["tracked"] else "")

    st.markdown(f"""
    <div class="score-card">
        <div style="display:flex;justify-content:space-between;align-items:center">
            <span class="score-card-team {t2_cls}">{g['t2']}</span>
            <span class="score-card-pts {t2_cls}">{as_s}</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center">
            <span class="score-card-team {t1_cls}">{g['t1']}</span>
            <span class="score-card-pts {t1_cls}">{hs_s}</span>
        </div>
        <div class="score-card-date">{meta}{tracked_badge}</div>
    </div>
    """, unsafe_allow_html=True)

    if g["tracked"]:
        with st.expander(f"📊 Box score — {g['t2']} @ {g['t1']}"):
            render_box_score(g["id"])
