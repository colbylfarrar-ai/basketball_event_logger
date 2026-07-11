"""
4_Schedule.py — Calendar-style, one-stop view of every game day.

Pick a month, click a day on the calendar, and the page unfolds everything that
happened: a day-at-a-glance summary, the Game of the Day, the biggest upset,
the day's stat leaders (tracked games), and every final with a full box score
one click away. Built on the same engine + box-score report as the rest of the
app, so it always agrees with the source of truth.

This is the APP5.0 successor to APP3.0's "Daily Breakdown" — the static HTML
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
from helpers.ui import (page_chrome, page_header, lab_hero as _lab_hero,
                        score_card, team_color, empty_state, rank_chip)
import helpers.team_ratings as TR
import helpers.predictor as PRED
import helpers.stats as S

_cfg, ACCENT = page_chrome("Schedule")


def _film_widget(url):
    """Render a game's film. YouTube / direct video file → inline player inside a
    collapsed expander; anything else (Hudl, NFHS, …) → a link button that opens
    in a new tab (those sites block iframe embedding)."""
    url = (url or "").strip()
    if not url:
        return
    low = url.lower()
    embeddable = ("youtube.com" in low or "youtu.be" in low
                  or low.endswith((".mp4", ".webm", ".ogg", ".mov")))
    if embeddable:
        with st.expander("▶ Film"):
            st.video(url)
    else:
        st.link_button("▶ Watch film", url)

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
div[data-testid="stColumn"] .stButton > button { min-height:46px; padding:4px 2px; }
/* Mobile: keep the 7-wide calendar rows on one line instead of stacking into a
   vertical list. Scoped to the rows after the .cal-grid-marker that have a 7th
   column, so the day-section's 3/4-column layouts still stack normally. */
@media (max-width: 640px) {
  div[data-testid="stElementContainer"]:has(.cal-grid-marker)
      ~ div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:nth-child(7)) {
    flex-wrap: nowrap !important;
    gap: 2px !important;
  }
  div[data-testid="stElementContainer"]:has(.cal-grid-marker)
      ~ div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:nth-child(7))
      > div[data-testid="stColumn"] {
    min-width: 0 !important;
    flex: 1 1 0 !important;
  }
  div[data-testid="stElementContainer"]:has(.cal-grid-marker)
      ~ div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"]:nth-child(7))
      .stButton > button {
    min-width: 0; min-height: 38px; padding: 2px 0; font-size: 11px;
  }
}
.upset-card {
    background:linear-gradient(135deg,#1a0a0a,#2a0d0d);
    border:1px solid var(--bad); border-radius:12px;
    padding:16px 18px; margin-bottom:10px;
}
.upset-title { font-size:14px; font-weight:800; color:var(--bad); margin-bottom:6px; }
.upset-body  { font-size:14px; color:var(--subtext); }
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

_lab_hero("Schedule", phase="BUILD",
          sub="A calendar of every game day. Click a day to see what happened — "
              "the headline game, the biggest upset, the day's leaders and every "
              "final with a full box score.")


# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════
def _filter_sql(gender, klass):
    """Shared WHERE fragments + params for the gender/class filter. Gender is a
    team property (both teams in a game share it); a class filter matches when
    EITHER team is that class (cross-class games count for both)."""
    clauses, params = [], []
    if gender:
        clauses.append("t1.gender = ?")
        params.append(gender)
    if klass:
        clauses.append("(t1.class = ? OR t2.class = ?)")
        params += [klass, klass]
    return clauses, params


@st.cache_data(ttl=600, show_spinner=False)
def _filter_opts():
    """(genders, classes) present in the league — the filter dropdown options."""
    gs = [r["gender"] for r in query(
        "SELECT DISTINCT gender FROM teams WHERE gender IS NOT NULL ORDER BY gender")]
    cs = [r["class"] for r in query(
        "SELECT DISTINCT class FROM teams WHERE class IS NOT NULL AND class <> '' "
        "ORDER BY class")]
    return gs, cs


@st.cache_data(ttl=600, show_spinner=False)
def _day_counts(gender=None, klass=None):
    """{ISO date: game count}, scoped to the gender/class filter."""
    where = ["g.date IS NOT NULL", "g.date <> ''"]
    extra, params = _filter_sql(gender, klass)
    where += extra
    rows = query(
        "SELECT g.date, COUNT(*) AS cnt FROM games g "
        "JOIN teams t1 ON t1.id = g.team1_id JOIN teams t2 ON t2.id = g.team2_id "
        "WHERE " + " AND ".join(where) + " GROUP BY g.date", tuple(params))
    return {r["date"]: r["cnt"] for r in rows}


@st.cache_data(ttl=600, show_spinner=False)
def _games_on(date_str, gender=None, klass=None):
    where = ["g.date = ?"]
    params = [date_str]
    extra, ep = _filter_sql(gender, klass)
    where += extra
    params += ep
    return query("""
        SELECT g.id, g.date, g.location, g.tracked, g.video_url,
               g.home_score, g.away_score, g.team1_id, g.team2_id,
               t1.name AS t1, t2.name AS t2, t1.gender AS gender,
               EXISTS(SELECT 1 FROM game_events ge
                      WHERE ge.game_id = g.id) AS has_events
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE """ + " AND ".join(where) + """
        ORDER BY g.tracked DESC, g.id
    """, tuple(params)) or []


@st.cache_data(ttl=600, show_spinner=False)
def _rank_of():
    """{team_id: rank} from results-only ratings (per-gender ranks). Built on
    the cached per-gender ratings so the rank prefix on a preview card always
    agrees with the ratings the projection used."""
    out = {}
    for gdr in ("M", "F"):
        for tid, r in _ratings(gdr).items():
            out[tid] = r["Rank"]
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _ratings(g):
    return TR.score_ratings(gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _tratings(g):
    return TR.tracked_ratings(gender=g)


@st.cache_data(ttl=600, show_spinner=False)
def _player_meta():
    return {r["id"]: (r["name"], r["team"]) for r in query(
        "SELECT p.id, p.name, t.name AS team "
        "FROM players p JOIN teams t ON t.id = p.team_id")}


# ── Filters (class · gender) — scope the whole calendar + day sections ──────────
_gopts, _copts = _filter_opts()
_GENDER_LBL = {"M": "Boys", "F": "Girls"}
_fc1, _fc2 = st.columns(2)
_gsel = _fc1.selectbox("Gender", ["All"] + _gopts,
                       format_func=lambda x: _GENDER_LBL.get(x, x),
                       key="sched_gender")
_csel = _fc2.selectbox("Class", ["All"] + _copts, key="sched_class")
_gender = None if _gsel == "All" else _gsel
_klass = None if _csel == "All" else _csel
_filtered = bool(_gender or _klass)

counts = _day_counts(_gender, _klass)
if not counts:
    if _filtered:
        empty_state("No games match this filter",
                    "No games for this class/gender. Clear the filters above to see "
                    "the full calendar.", icon="📅")
    else:
        empty_state("No games on the calendar yet",
                    "Add games with a date in the Input Hub and they'll appear "
                    "here, grouped by day.",
                    icon="📅", cta="Input Hub → Games")
    st.stop()

all_dates = sorted(counts)
first_ym, last_ym = all_dates[0][:7], all_dates[-1][:7]

st.session_state.setdefault("sched_ym", all_dates[-1][:7])
st.session_state.setdefault("sched_sel", all_dates[-1])
# If a filter change left the selected day with no matching games, jump to the
# latest day that DOES match so the page never opens on an empty selection.
if st.session_state["sched_sel"] not in counts:
    st.session_state["sched_sel"] = all_dates[-1]
    st.session_state["sched_ym"] = all_dates[-1][:7]


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
    """Game-load marker for a calendar day button — matches the legend below."""
    return "🟢" if cnt <= 2 else "🟠" if cnt <= 5 else "🔴"


# marker for the scoped mobile no-wrap CSS above — keep it directly before the grid
st.markdown('<div class="cal-grid-marker"></div>', unsafe_allow_html=True)

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
@st.fragment
def _day_section():
    """Everything below the calendar for the selected day. A fragment, so
    interactions inside it (load-box-score checkboxes, film expanders) rerun
    only this section — not the month grid above."""
    sel = st.session_state["sched_sel"]
    day_games = _games_on(sel, _gender, _klass)

    st.markdown("---")
    st.markdown(f"### {_fmt_long(sel)}")

    if not day_games:
        empty_state("Nothing on this day",
                    "Pick a highlighted day on the calendar above.", icon="📅")
        st.stop()

    scored = [g for g in day_games
              if g["home_score"] is not None and g["away_score"] is not None]
    tracked_games = [g for g in day_games if g["tracked"]]

    def _lazy_box(game_id, key):
        """Render a box score only once asked — keeps a day with many tracked
        games from computing every full report eagerly inside its expander."""
        if st.checkbox("Load box score", key=key):
            render_box_score(game_id)

    def _preview(g):
        """The model's pre-game read on an unplayed game. Home = team1 (the
        page's 'away @ home' convention everywhere). None when either team is
        unrated."""
        return PRED.predict_game(g["team1_id"], g["team2_id"],
                                 scored=_ratings(g["gender"]),
                                 tracked=_tratings(g["gender"]),
                                 home=g["team1_id"])

    # ── Day at a Glance ─────────────────────────────────────────────────────────
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

    # ── Scheduled day — nothing played yet, so this is GAME PREP: matchup
    #    preview cards with the model's projection instead of results copy. ──
    if not scored:
        st.markdown("<div class='section-hdr'>Game previews</div>",
                    unsafe_allow_html=True)
        rank_of = _rank_of()
        for g in day_games:
            pred = _preview(g)
            with st.container(border=True):
                r_home = rank_of.get(g["team1_id"])
                r_away = rank_of.get(g["team2_id"])
                away = (f"#{r_away} " if r_away else "") + g["t2"]
                home = (f"#{r_home} " if r_home else "") + g["t1"]
                pv1, pv2, pv3 = st.columns([4, 2, 2])
                pv1.markdown(f"**{away}** @ **{home}**")
                if g["has_events"]:
                    pv1.caption("🔴 Live — being tracked right now")
                elif g["location"]:
                    pv1.caption(g["location"])
                if pred is None:
                    pv2.caption("Not enough results to project this one yet.")
                else:
                    fav = (pred["a_name"] if pred["favorite"] == pred["team_a"]
                           else pred["b_name"])
                    wp = max(pred["win_prob_a"], pred["win_prob_b"]) * 100
                    pv2.metric("Projected (away–home)",
                               f"{pred['pf_b']:.0f}–{pred['pf_a']:.0f}",
                               f"total {pred['total']:.0f}", delta_color="off")
                    pv3.metric(fav, f"{wp:.0f}%", pred["confidence"],
                               delta_color="off")
        st.caption("Opponent-adjusted projections with home court to the home "
                   "team. The full margin breakdown and simulation live in the "
                   "War Room.")
        return

    # ── Game of the Day ─────────────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>Game of the Day</div>",
                unsafe_allow_html=True)

    gotd = max(scored, key=lambda g: g["home_score"] + g["away_score"])
    hs, as_ = gotd["home_score"], gotd["away_score"]
    h_win = hs >= as_
    badge = ("<div class='gotd-badge'>Tracked · full box inside</div>"
             if gotd["tracked"] else "")
    # Winner's score wears that team's identity colour (shared app-wide system);
    # the loser stays muted.
    c_away = team_color(gotd["t2"], gotd["team2_id"])
    c_home = team_color(gotd["t1"], gotd["team1_id"])
    # scored class-rank chip (ungated), same as the result cards below
    _gsr = _ratings(gotd["gender"])
    def _gchip(tid):
        r = _gsr.get(tid)
        return rank_chip(r.get("class_lbl", r["class"]),
                         r["ClassRank"]) if r else ""
    st.markdown(f"""
    <div class="game-hero">
        <div style="font-size:12px;color:#8b949e;margin-bottom:8px">
            {gotd['location'] or 'Highest-scoring game of the day'}
        </div>
        <table style="width:100%;border:none"><tr>
          <td style="width:42%;text-align:center">
            <div style="font-size:16px;font-weight:700;color:#c9d1d9">
              {'▸ ' if not h_win else ''}{gotd['t2']}{_gchip(gotd['team2_id'])}</div>
            <div style="font-size:46px;font-weight:900;line-height:1;
                 color:{c_away if not h_win else '#8b949e'}">{as_}</div>
          </td>
          <td style="width:16%;text-align:center;color:#8b949e;font-size:18px">@</td>
          <td style="width:42%;text-align:center">
            <div style="font-size:16px;font-weight:700;color:#c9d1d9">
              {'▸ ' if h_win else ''}{gotd['t1']}{_gchip(gotd['team1_id'])}</div>
            <div style="font-size:46px;font-weight:900;line-height:1;
                 color:{c_home if h_win else '#8b949e'}">{hs}</div>
          </td>
        </tr></table>
        {badge}
    </div>
    """, unsafe_allow_html=True)

    if gotd["tracked"]:
        with st.expander("Full report — Game of the Day"):
            _lazy_box(gotd["id"], f"sched_box_gotd_{gotd['id']}")
    _film_widget(gotd["video_url"])

    # ── Upset Alert ─────────────────────────────────────────────────────────────
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
            <div class="upset-title">Biggest upset of the day</div>
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

    # ── Day's Leaders (tracked games only) ──────────────────────────────────────
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
            l[0].metric("Top scorer", f"{int(best_pts[0])} PTS", _who(best_pts[1]))
        else:
            l[0].metric("Top scorer", "—")
        if best_reb and best_reb[0] > 0:
            l[1].metric("Top rebounder", f"{int(best_reb[0])} REB", _who(best_reb[1]))
        else:
            l[1].metric("Top rebounder", "—")
        if best_ast and best_ast[0] > 0:
            l[2].metric("Top playmaker", f"{int(best_ast[0])} AST", _who(best_ast[1]))
        else:
            l[2].metric("Top playmaker", "—")

    # ── All Results ─────────────────────────────────────────────────────────────
    st.markdown("<div class='section-hdr'>All Results</div>", unsafe_allow_html=True)

    for g in day_games:
        if g["id"] == gotd["id"]:
            st.caption(f"{g['t2']} @ {g['t1']} — Game of the Day, shown above.")
            continue

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
            pred = _preview(g)
            if pred:
                fav = (pred["a_name"] if pred["favorite"] == pred["team_a"]
                       else pred["b_name"])
                wp = max(pred["win_prob_a"], pred["win_prob_b"]) * 100
                meta = (f"Proj {pred['pf_b']:.0f}–{pred['pf_a']:.0f} · "
                        f"{fav} {wp:.0f}%")

        tracked_badge = ("<span class='tracked-badge'>tracked</span>"
                         if g["tracked"] else "")

        # Scored class-rank chip per team (results-only ranking → ungated). The
        # tracked/possession ranking stays behind its entitlement gate elsewhere.
        _sr = _ratings(g["gender"])
        def _chip(tid):
            r = _sr.get(tid)
            return rank_chip(r.get("class_lbl", r["class"]),
                             r["ClassRank"]) if r else ""

        st.markdown(score_card(
            [(g['t2'], as_s, t2_win, _chip(g['team2_id'])),
             (g['t1'], hs_s, t1_win, _chip(g['team1_id']))],
            footer=f"{meta}{tracked_badge}", style_names=True),
            unsafe_allow_html=True)

        if g["tracked"]:
            with st.expander(f"Box score — {g['t2']} @ {g['t1']}"):
                _lazy_box(g["id"], f"sched_box_{g['id']}")

        _film_widget(g["video_url"])


_day_section()
