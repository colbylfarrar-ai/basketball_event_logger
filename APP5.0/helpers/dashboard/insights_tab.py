"""
insights_tab.py — Team Dashboard > Insights (the scout that reads itself,
scoped to the SELECTED team).

THE SPINE: THE PAGE RECONCILES TO THE SCOREBOARD
------------------------------------------------
`deserved.py` splits every game's margin into four terms — extra shots,
selection, shot-making, free throws — that sum EXACTLY to the final margin.
That reconciliation is the organising law of the whole view, not one panel
inside it, and the currency everywhere is points per game: every finding with
an honest conversion carries `≈ +2.3 pts/g` (`helpers/insights_severity.py`).
That translation is what turns 39 z-scored generators into coach speak and what
makes a single severity ranking possible across three engine families that
never shared a scale.

WHAT CHANGED, AND WHY
---------------------
This view used to be six sub-tabs named after data categories — Players,
Offense, Defense — and a coach asks questions, not categories. It now opens on
THE DECK (`insights_deck.py`, always visible) over seven sections cut by the
question each answers. Three structural rules hold the recut together:

  1. RANK, NEVER HIDE. Severity ordering is a sort, never a filter. Every
     finding an engine fires renders in full inside its section. THE FIVE at
     the top is a spotlight; the same finding appearing twice is intended.
  2. `_seg`, NOT `st.tabs`. st.tabs executes every tab body on every rerun, so
     six eager tabs ran on every interaction. One lazy section is what pays for
     sections 3, 4 and 5 existing at all on a 1 vCPU box.
  3. A REAL `@st.fragment` on `render`. The module docstring claimed one for
     months and the function carried no decorator, so every jump button reran
     the entire 6,000-line page. With real controls in the deck that is no
     longer survivable.

Team-scoped tracked data, so it sits behind the team tracked gate
(ctx.has_tracked). The page builds a SimpleNamespace ctx.
"""
from __future__ import annotations

import html
import re

import streamlit as st

from database.db import query
import helpers.insights_severity as SEV
import helpers.player_ratings as PR
import helpers.stats as S
import helpers.insights as IN
import helpers.insights_team as INT
import helpers.playtypes as PT
import helpers.wpa as WPA
from helpers.cards import dense_table, conf_dot, verdict_card


def _b(t):
    """Markdown **bold** → <b> for raw-HTML cards."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


# ── insight line → where its evidence actually lives ─────────────────────────
# Every insight names its `metric`; `insights_severity.METRIC_EVIDENCE` maps
# each one to (view, subview) so a jump lands on the chart rather than near it.
# The table lives beside the severity ranking because both are statements about
# what a metric MEANS, and splitting them across two modules is how they drift.
#
# The view-only projection is kept as a name because callers and tests read it.
_EVIDENCE_VIEW = {m: ev[0] for m, ev in SEV.METRIC_EVIDENCE.items()}

# How firmly a line's n= backs it, on the insight scale (n is shots/poss/games
# depending on the generator — k=8 reads games-scale lines as directional and
# attempt-scale lines as stable, which matches how a coach should hold them).
_CONF_K = 8


def _line_html(ln, new=False):
    """One insight line: metric badge + confidence dot + n + the sentence.
    `new=True` prepends a NEW chip (per-coach, see the insights_seen blob)."""
    n = ln.get("n")
    dot = conf_dot(n, k=_CONF_K) if isinstance(n, (int, float)) else ""
    new_chip = ("<span style='background:#f0a50022;color:#f0a500;"
                "border:1px solid #f0a50055;border-radius:6px;padding:0 4px;"
                "font-size:9px;font-weight:800;letter-spacing:1px;"
                "margin-right:4px;vertical-align:1px'>NEW</span>" if new else "")
    return (f"<div style='margin-top:4px;font-size:12px'>{new_chip}"
            f"<span class='badge accent'>{ln['metric']}</span> {dot}"
            f"<span style='color:var(--subtext);font-size:10px'>n={n}</span> "
            f"{_b(ln['text'])}</div>")


# ── per-coach NEW badges (Tier 2 item 16) ─────────────────────────────────────
# One JSON blob per coach (settings key `insights_seen`, USER_SCOPED):
# {str(team_id): {line_hash: first-seen iso date}}. A line is NEW until the
# coach has had it on screen on a PRIOR day — first sight stamps today, and the
# chip stays for the rest of that day (a mid-scroll rerun must not eat it).
def _ins_hash(ln):
    import hashlib
    raw = f"{ln.get('metric', '')}{str(ln.get('text', ''))[:40]}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def _seen_tracker(team_id):
    """(is_new(ln), persist()) for this coach + team. `persist` writes the
    updated blob once, only when something unseen actually rendered."""
    import datetime as _dt
    import json
    import helpers.settings_utils as SU
    tkey = str(team_id or "")
    today = _dt.date.today().isoformat()
    try:
        seen_all = json.loads(SU.get_setting("insights_seen", "") or "{}")
        if not isinstance(seen_all, dict):
            seen_all = {}
    except Exception:
        seen_all = {}
    seen = dict(seen_all.get(tkey) or {})
    fresh = {}

    def is_new(ln):
        h = _ins_hash(ln)
        if h not in seen:
            fresh[h] = today
        return seen.get(h, today) == today      # unseen, or first seen today

    def persist():
        if not (fresh and tkey):
            return
        seen.update(fresh)
        if len(seen) > 300:                     # cap the blob per team
            seen_d = sorted(seen.items(), key=lambda kv: kv[1])[-300:]
            seen.clear()
            seen.update(seen_d)
        seen_all[tkey] = seen
        try:
            SU.set_setting("insights_seen", json.dumps(seen_all))
        except Exception:
            pass

    return is_new, persist


# Handshake key for the view jumps below. `td_view` is the KEY OF A WIDGET —
# the segmented_control near the top of 6_Team_Dashboard.py — and Streamlit
# forbids assigning to a widget's key once that widget has been instantiated
# this run. This tab renders ~4,000 lines after the switcher, so the old inline
# `st.session_state["td_view"] = v` raised StreamlitAPIException and took the
# whole Insights page down the moment a coach clicked a jump.
#
# So the button parks its destination HERE (a plain, non-widget key, always
# legal to write) and asks for an app-scoped rerun; the page consumes it into
# `td_view` BEFORE building the switcher, which is legal and is the documented
# way to drive a keyed widget programmatically.
TD_VIEW_GOTO = "_td_view_goto"

#: Second half of the handshake: the INNER switcher's destination, consumed by
#: whichever `_sub_seg` owns it (Charts', Lab's) before that widget is built.
#: A view-only jump landed on Charts' first sub-tab when the evidence was on
#: Trends, and a jump that lands near the answer is a jump a coach stops using.
TD_SUB_GOTO = "_td_subview_goto"


def _request_view(view, sub=None):
    """Park a (view, subview) jump for the page to consume, then rerun.

    App-scoped on purpose: this tab is a fragment, and a fragment-scoped rerun
    would never repaint the switcher.
    """
    st.session_state[TD_VIEW_GOTO] = (view, sub)
    st.rerun(scope="app")


def _evidence_jumps(lines, key):
    """Row of jump buttons for the evidence behind a card's lines.

    EVERY distinct destination the card's lines point at gets a button, not the
    first three: a card whose reads live on four different tabs was silently
    dropping the fourth, which is the one a coach would not have thought to
    look for. Destinations are (view, subview) now, so two reads on the same
    view but different sub-tabs are two buttons, not one.
    """
    dests = []
    for ln in lines:
        ev = SEV.METRIC_EVIDENCE.get(ln.get("metric"))
        if ev and ev not in dests:
            dests.append(ev)
    if not dests:
        return
    cols = st.columns(max(3, len(dests)))
    for i, (view, sub) in enumerate(dests):
        label = _dest_label(view, sub)
        if cols[i].button(f"{label} →",
                          key=f"{key}_{label.replace(' ', '')}",
                          help=f"Open {label} — the charts behind these reads"):
            _request_view(view, sub)


#: shared with the deck so a button and its help text cannot describe two
#: different destinations
_dest_label = SEV.dest_label


def _jump_btn(view, label, key, sub=None):
    """A single 'the full table lives on X' jump."""
    if st.button(label, key=key,
                 help=f"Open {_dest_label(view, sub)} — the full chart and "
                      f"table"):
        _request_view(view, sub)


def _data_fp(gids=None):
    """Cheap change signature for everything this tab computes from: the event
    book (count + max id) and the finished scores (results_fingerprint). Passed
    into every cached wrapper so the heavy league engine recomputes only when
    data actually changes — with the old bare ttl=300 the whole tab silently
    re-ran the engine every 5 minutes, which is the 'Insights sometimes hangs
    on load' report. One aggregate query, a few ms.

    `gids` SCOPES the event half to the games this tab actually reads, and
    without it the count was over the WHOLE `game_events` table. That made the
    key global: any tracker write anywhere — another team, the other gender, an
    archived season — moved the fingerprint for every team's Insights page and
    forced the full cold rebuild (measured 84.7s on prod against 0.97s warm).
    On a 21-team league that is the common case, not the edge one, and none of
    those writes touch what this pool computes.

    The score half stays GLOBAL on purpose. Scores move a couple of times a
    night rather than ten times a game, so it is not what was busting the cache,
    and a conservative key there is the cheap way to stay correct about the
    league-wide rating inputs. Being too eager here costs 85 seconds; being too
    lazy shows a coach numbers that are quietly wrong.
    """
    import helpers.team_ratings as TR
    if gids:
        marks = ",".join("?" * len(gids))
        ev = query(f"SELECT COUNT(*) c, COALESCE(MAX(id),0) m FROM game_events "
                   f"WHERE game_id IN ({marks})", tuple(gids))[0]
    else:
        ev = query("SELECT COUNT(*) c, COALESCE(MAX(id),0) m "
                   "FROM game_events")[0]
    return (ev["c"], ev["m"], TR.results_fingerprint())


# ttl is a fallback only (the fp argument does the real invalidation);
# spinner messages make a cold engine run look like loading, not a hang.
@st.cache_data(ttl=6 * 3600,
               show_spinner="Scoring the league (fresh data — one-time crunch)…")
def _league(gender, season="Current", season_gp=None, fp=None):
    """League table + insight feed + role splits + win-impact + guarded cliffs,
    computed once per gender (the team view filters this to its own players, so the
    z-scores stay league-relative). `season`/`season_gp` scope the whole pass to
    one season — the gender's season tracked game ids (season_gp) drive the table +
    events, so an archive roster's players are actually in the pool."""
    gids = list(season_gp) if season_gp is not None else PT._tracked_game_ids(gender)
    table = PR.player_stat_table(
        gender=gender, min_games=1,
        game_ids=(set(gids) if season_gp is not None else None))
    # CAREER BLEND (founder rule): on the ACTIVE season, a current-roster player
    # with under PJ.CAREER_CUTOFF tracked games reads as their newest archived
    # season's row (identity chain) — insights roll over the season boundary
    # instead of going dark until the new sample builds. Substituted rows carry
    # row['career_src'] (the render captions them). Archive rows are an open
    # archive, so nothing entitlement-gated is widened.
    _career_ev = None          # archive events remapped onto current pids
    try:
        import helpers.seasons as _SEAS
        import helpers.projection as _PJ
        if _SEAS.is_current(season):
            table, _n_sub = _PJ.career_stat_table(gender=gender, season=season,
                                                  cur_table=table)
            # If the active season has NO tracked events yet, the career TABLE
            # rows are last season's — feed last season's EVENTS too, else only
            # the box-derived generators fire and career players get thin
            # 1-line reads. BUT the career rows are keyed by the CURRENT pid,
            # while archive events carry the ARCHIVE pid, so remap every
            # player-id field on the events onto the current pid (identity
            # chain) — otherwise the event generators' per-pid splits never
            # match the table and nothing extra fires.
            if _n_sub and not gids:
                _pr = query("SELECT id, COALESCE(identity_id, id) AS person, "
                            "archived FROM players")
                _person_cur = {r["person"]: r["id"] for r in _pr if not r["archived"]}
                _a2c = {r["id"]: _person_cur[r["person"]] for r in _pr
                        if r["archived"] and r["person"] in _person_cur}
                _egids = None
                for _lbl in _SEAS.archived_labels():
                    _p = _SEAS.game_pool(_lbl, gender=gender, tracked_only=True)
                    if _p:
                        _egids = list(_p)
                        break
                if _egids:
                    _PF = ("primary_player_id", "secondary_player_id",
                           "rebound_by_id", "pass_from_id", "shot_created_by_id",
                           "blocked_by_id", "guarded_by_id", "stolen_by_id")
                    _career_ev = []
                    for _e in S.fetch_events(_egids):
                        _d = dict(_e)
                        for _f in _PF:
                            if _d.get(_f) is not None:
                                _d[_f] = _a2c.get(_d[_f], _d[_f])
                        _career_ev.append(_d)
    except Exception:
        pass
    ev = _career_ev if _career_ev is not None else (S.fetch_events(gids) if gids else [])
    # on-floor impact feed (RAPM + HoopWAR) for the stats-vs-substance generator —
    # reuses the player-card caches so the ridge solves at most once per gender
    imp = None
    try:
        from helpers.dashboard.player_card import _rapm as _rapm_pc, _war as _war_pc
        imp = IN.impact_map(rapm=_rapm_pc(gender, season_gp),
                            war=_war_pc(gender, season, season_gp))
    except Exception:
        pass
    # top=None → EVERY qualifying insight per player (the tab is the deep-dive
    # home; the 3-line cap stays on player-card / rankings surfaces).
    feed = IN.build_feed(table, ev, top=None, impact=imp) if table else {}
    roles = PT.player_role_splits(events=ev) if ev else {}
    cliffs = IN.guarded_cliffs(ev) if ev else {}
    try:
        impact = WPA.season_wpa(gender, mode="possession", season=season)
    except Exception:
        impact = {}
    # `imp` (RAPM + HoopWAR, merged) is RETURNED rather than discarded: the
    # ridge has already been solved for the stats-vs-substance generator above,
    # so the impact board in "Who's helping" is close to free. Throwing it away
    # and having the board solve it again is the only way to make this
    # expensive.
    return table, feed, roles, impact, cliffs, (imp or {})


@st.cache_data(ttl=6 * 3600, show_spinner="Reading the team's tendencies…")
def _team_feed(gender, season="Current", team_id=None, tids=None, fp=None,
               season_gp=None):
    """League-wide team insight feed (z-scored vs the tracked field) — the tab
    shows only the selected team's lines. The per-team extras (lineup / matchup
    / chemistry feeds) are built for the VIEWED team only, scoped to its own
    visible game ids, so nothing beyond the pools reads other teams' depth.

    `season_gp` is the GENDER's season pool, handed to the extras builder as
    the league baseline for the comparative reads (the allowed shot diet and
    the contest rate). Without it those generators fall back to comparing this
    team against only the opponents on its own schedule.
    """
    import helpers.team_insights as TIN
    try:
        extras = None
        if team_id is not None:
            _ex = TIN.team_extras(team_id, gender=gender,
                                  game_ids=(list(tids) if tids else None),
                                  season=season,
                                  league_game_ids=(list(season_gp)
                                                   if season_gp else None))
            extras = {team_id: _ex} if _ex else None
        # top=None → EVERY qualifying team read (the tab is the deep-dive home;
        # the 3-line cap stays on the league-wide surfaces).
        return TIN.team_insight_feed(gender=gender, season=season,
                                     extras=extras, top=None)
    except Exception:
        return {}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _strength(gender, team_id, tids, season="Current", fp=None):
    """Opponent-strength offense split for this team (top vs bottom half of the
    league), cached per (gender, team, visible games, season)."""
    return INT.strength_splits(team_id, gender=gender,
                               game_ids=list(tids) if tids else None,
                               season=season)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _winloss(gender, team_id, tids, fp=None):
    """Wins-vs-losses offense split for this team, cached per (gender, team, games)."""
    return INT.winloss_splits(team_id, gender=gender,
                              game_ids=list(tids) if tids else None)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _wl_align(gender, team_id, tids, fp=None):
    """This team's most win/loss-aligned stats (effect-size ranked)."""
    return INT.winloss_alignment(team_id, gender=gender,
                                 game_ids=list(tids) if tids else None)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _tendencies(gender, team_id, tids, fp=None):
    """Zone-based shot tendencies (force left/right, where shots live)."""
    return INT.shot_tendencies(team_id, gender=gender,
                               game_ids=list(tids) if tids else None)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _passers(gender, season_gp=None, fp=None):
    """Per-passer shot-creation quality (pass-from look quality vs finish).
    `season_gp` (a tuple of game ids) scopes an archive season; None = current."""
    return INT.passer_quality(
        gender=gender,
        game_ids=(list(season_gp) if season_gp is not None else None))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _ball_movement(gender, tids, fp=None):
    """Ball-movement reads over this team's tracked games (#8b):
    (expected_assists map, corsi map, {pid: hockey-assist count}). One
    fetch_events feeds all three; `fp` keys the cache to the data version."""
    if not tids:
        return {}, {}, {}
    events = S.fetch_events(list(tids))
    xa = S.expected_assists(events=events)
    corsi = S.corsi_all(events=events)
    hast = {}
    for e in events:
        h = e.get("hockey_from_id")
        if h is not None and e["event_type"] == "shot" \
                and e["shot_result"] == "make":
            hast[h] = hast.get(h, 0) + 1
    return xa, corsi, hast


def _pct(v):
    return f"{v * 100:.0f}%" if v is not None else "—"


def _split_rows(pa, pb, la, lb):
    """The shared 7-metric split table (used by every A-vs-B deep-dive section)."""
    _f2 = lambda v: f"{v:.2f}" if v is not None else "—"
    specs = [("PPP (pts/shot)", "PPP", _f2), ("eFG%", "eFG", _pct),
             ("Scoring eff (ScEff)", "SCE", _pct), ("3PA rate", "3PA_rate", _pct),
             ("Rim rate", "rim_rate", _pct), ("Assisted rate", "ast_rate", _pct),
             ("Open rate", "open_rate", _pct)]
    return [{"Metric": lbl, la: fmt(pa.get(k)), lb: fmt(pb.get(k))}
            for lbl, k, fmt in specs]


@st.fragment
@st.cache_data(ttl=600, show_spinner=False)
def _kind_shots(gender, season="Current", season_gp=None):
    """Mapped shots for the tracked pool — the shot-diet feed.

    Pool-wide on purpose: shot_kinds computes the team's diet and the league
    baseline from the same list, so one pass serves both and the two can't be
    scoped differently.

    The `if gids` guard is load-bearing: S.fetch_events([]) returns EVERY event
    in the database, across both genders and every season, so an empty pool
    would build this team's league baseline out of the entire book rather than
    rendering nothing. `_tracked_game_ids` returns [] on a freshly rolled-over
    season, which is precisely when that would bite.
    """
    gids = (list(season_gp) if season_gp is not None
            else PT._tracked_game_ids(gender))
    return S.mapped_shots(events=S.fetch_events(gids)) if gids else []


def _shot_diet_lines(ctx):
    """The shot-kind verdict for this team, in verdict_card shape, or []."""
    tid = getattr(ctx, "team_id", None)
    if not tid:
        return []
    import helpers.shot_kinds as SK
    shots = _kind_shots(ctx.gender, getattr(ctx, "season", "Current"),
                        getattr(ctx, "season_gp", None))
    if not shots:
        return []
    games = len(getattr(ctx, "tracked_ids", None) or ()) or None
    # NOT html.escape'd: SK.verdict emits its own <b> labels and interpolates
    # only module constants and floats (see its docstring's markup contract).
    # Escaping here printed a literal "<b>Diet</b>" on the card.
    return [("shot diet", ln["n"], ln["text"])
            for ln in SK.verdict(team_id=tid, shots=shots, games=games)]


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _pts_ctx(gender, season, team_id, fp=None):
    """The league constants the points-per-game translator prices against.

    `ts_all` is the per-team advanced pack (possessions per game, PPP, TOV%,
    ORB%…) and `wins_per_point` inverts the Pythagorean exponent at this
    pool's own scoring, so WPA converts to points using the league it was
    measured in rather than a constant borrowed from the NBA.

    Box-level only — no event walk — so tagging findings costs a pack build on
    cold and nothing at all when warm.
    """
    out = {"ts_all": {}, "ts": {}, "wins_per_point": None}
    try:
        import helpers.league_analytics as LA
        pack = LA.team_tracked_pack(gender=gender, season=season)
        out["ts_all"] = pack.get("ts") or {}
        out["ts"] = out["ts_all"].get(team_id) or {}
    except Exception:
        pass
    try:
        import helpers.hoopwar as HW
        out["wins_per_point"] = HW.wins_per_point(
            HW.league_ppg(gender=gender, season=season))
    except Exception:
        pass
    return out


def _scoped(ctx, tids):
    """A ctx copy narrowed to the deck's game window.

    The controls are CACHE-KEY inputs, not post-filters: every wrapper below
    takes the tracked ids as part of its key, so a narrowed window recomputes a
    smaller pool instead of computing the whole book and hiding most of it.
    """
    from types import SimpleNamespace
    d = dict(vars(ctx))
    d["tracked_ids"] = tuple(tids or ())
    return SimpleNamespace(**d)


@st.fragment
def render(ctx):
    # (Team at a glance moved to the Overview tab — UI_DENSITY_PLAN phase A.)
    #
    # THE FRAGMENT IS NOT DECORATION. This module's docstring has claimed
    # `render(ctx) @st.fragment` since it was written and the function carried
    # no decorator, so every one of the four jump buttons reran the whole
    # ~6,000-line page. The deck now owns three real widgets; without this the
    # first keystroke in the player filter would rebuild the entire dashboard.
    # The jump buttons still ask for an APP-scoped rerun explicitly, because
    # they have to repaint a switcher that lives outside this fragment.
    #
    # Cache key: recompute only when data THIS POOL reads changes. Scoped to the
    # gender+season tracked pool, which is exactly what _league and every other
    # cached wrapper below compute over.
    #
    # Keyed on `season_fp_gp`, NOT `season_gp`. The latter is deliberately None
    # on the current season (it makes the page's engine binders the identity), so
    # keying on it sent _data_fp down its unscoped branch and counted the whole
    # game_events table — leaving the global-key regression fully in place for
    # every coach, all season. season_fp_gp is the same pool, always resolved.
    _fp = _data_fp(getattr(ctx, "season_fp_gp", None)
                   or getattr(ctx, "season_gp", None))
    table, feed, roles, impact, cliffs, impmap = _league(
        ctx.gender, getattr(ctx, "season", "Current"),
        getattr(ctx, "season_gp", None), fp=_fp)
    # career rows (last season's read, open archive) keep the tab alive on a
    # freshly rolled-over season even before this season's tracked gate opens
    _career_here = [r for r in table.values()
                    if r.get("career_src")
                    and r.get("team_id") == getattr(ctx, "team_id", None)]
    if not getattr(ctx, "has_tracked", False) and not _career_here:
        st.info("🔒 Insights read tracked play-by-play (shot quality, contest "
                "splits, win-impact). Track this team's games — or unlock the "
                "Paid tier — to light them up.")
        return
    if not table:
        st.caption("No tracked players yet for this league.")
        return
    if _career_here:
        _src = _career_here[0].get("career_src")
        st.info(f"📅 {len(_career_here)} player read"
                f"{'s' if len(_career_here) != 1 else ''} on this roster come "
                f"from **{_src}** (career) — a player switches to this season's "
                "read once they have 5 tracked games in it.")

    # this team's player ids, ordered by rating. Derive from the (career-blended)
    # LEAGUE TABLE filtered to this team — NOT from ctx.players, which is the
    # current-season bundle and is EMPTY on a freshly rolled-over season (0
    # tracked games), so the career rows would never render. ctx.players still
    # seeds the set (a current-season player who IS rated), then any career row
    # for this team is unioned in.
    _team = getattr(ctx, "team_id", None)
    pids = {p.get("_pid") for p in (ctx.players or [])
            if isinstance(p, dict) and p.get("_pid") in table}
    pids |= {pid for pid, r in table.items() if r.get("team_id") == _team}
    pids = sorted(pids, key=lambda p: -(table[p].get("OVERALL") or 0))
    if not pids:
        st.caption("No tracked shooters on this roster yet.")
        return

    # per-coach NEW chips: unseen lines get flagged; the blob is persisted once
    # after the player feed renders (so a fragment rerun mid-scroll never eats
    # chips).
    _is_new, _seen_persist = _seen_tracker(getattr(ctx, "team_id", None))

    from helpers.dashboard import insights_deck as _DECK
    from helpers.dashboard import insights_deep as _DEEP

    # ══════════════════════════════════════════════════════════════════════════
    #  THE CONTROLS, THEN THE DECK, THEN THE SECTIONS
    # ══════════════════════════════════════════════════════════════════════════
    # The controls come FIRST because they are cache-key inputs: everything
    # below is computed over the window they select, so they cannot be rendered
    # after the work they scope.
    _book = len(getattr(ctx, "tracked_ids", None) or ())
    _tids, _pid_filter, _scope = _DECK.controls(ctx, table, pids)
    sctx = _scoped(ctx, _tids)
    if _pid_filter:
        pids = [p for p in pids if p in _pid_filter]
        if not pids:
            st.caption("No player on this roster matches that filter.")
            return

    _tlines = _team_feed(
        ctx.gender, getattr(ctx, "season", "Current"),
        getattr(ctx, "team_id", None),
        tuple(_tids or ()) or None,
        fp=_fp,
        season_gp=tuple(getattr(ctx, "season_gp", None) or ()) or None,
    ).get(getattr(ctx, "team_id", None), [])

    _bundle = {}
    try:
        _bundle = _DEEP.brief_bundle(
            tuple(_tids or ()), getattr(ctx, "team_id", None), ctx.gender,
            league_gids=tuple(getattr(ctx, "season_gp", None) or ()) or None,
            fp=_fp)
    except Exception as _exc:
        st.caption(f"Engine bundle unavailable — {type(_exc).__name__}: {_exc}")

    _plines, _pdiag = {}, {}
    try:
        _plines, _pdiag = _DEEP._ported(getattr(ctx, "team_id", None),
                                        ctx.gender, tuple(_tids or ()), fp=_fp)
    except Exception as _exc:
        st.caption(f"Engine verdicts unavailable — "
                   f"{type(_exc).__name__}: {_exc}")

    # ── ONE ORDERING ACROSS THREE ENGINE FAMILIES ───────────────────────────
    # The three families keep their own internal order inside their own
    # sections; this is an ADDITIONAL ordering used by the deck and by Monday.
    # Nothing upstream is rewritten, so the miners' regression tests stay green.
    _gp = len(_tids or ())
    _pctx = _pts_ctx(ctx.gender, getattr(ctx, "season", "Current"),
                     getattr(ctx, "team_id", None), fp=_fp)
    _pctx = dict(_pctx)
    _pctx.update({
        "gp": _gp,
        "deserved": (_bundle or {}).get("deserved") or {},
        "cliffs": cliffs,
        "wpa": impact,
        # the WHOLE rated pool, not just this roster: the per-player
        # conversions price a gap against the league, and a gap measured
        # against nine teammates is not a league gap.
        "player_pool": table,
        "player_gp": {p: ((table[p].get("GP") or table[p].get("games")))
                      for p in pids if p in table},
    })
    _ranked = SEV.rank(
        SEV.collect(
            player_feed={p: feed.get(p, []) for p in pids},
            names={p: table[p]["name"] for p in pids if p in table},
            team_lines=_tlines,
            ported=_plines,
            ported_sections={k: (_DEEP._PORT_SHORT.get(k, k), home)
                             for k, _h, _c, home in _DEEP._PORT_SECTIONS}),
        _pctx, gp=_gp)
    _by_sect = SEV.by_section(_ranked)

    if _scope:
        st.markdown(_DECK.scope_note(_scope, len(_tids or ()), book=_book),
                    unsafe_allow_html=True)

    _axes = []
    try:
        _axes = _DECK.render(sctx, table=table, pids=pids, ranked=_ranked,
                             bundle=_bundle, fp=_fp, jump=_request_view)
    except Exception as _exc:
        st.caption(f"Deck unavailable — {type(_exc).__name__}: {_exc}")

    # ══════════════════════════════════════════════════════════════════════════
    #  THE SECTIONS — cut by the question a coach asks, not by data category
    # ══════════════════════════════════════════════════════════════════════════
    # `_seg`, NOT `st.tabs`: st.tabs executes EVERY tab body on every rerun, so
    # the old six-tab layout did all six sections' work on every interaction.
    # This is what pays for sections 3, 4 and 5 existing at all — per-rerun work
    # goes DOWN even though the section count went up.
    import helpers.ui as _UI
    _sections = ["Who we are", "Why we win / why we lose", "Who's helping",
                 "Who to play together", "What they'll take away", "Monday",
                 "Receipts"]
    _sec = _UI.seg("Section", _sections, default=_sections[0],
                   key="ins_section", label_visibility="collapsed") \
        or _sections[0]

    # ── 1 · WHO WE ARE ──────────────────────────────────────────────────────
    if _sec == "Who we are":
        try:
            from helpers.dashboard import insights_identity as _ID
            _ID.render(sctx, axes=_axes, shot_diet_lines=_shot_diet_lines(ctx),
                       ported=_plines, tids=_tids, fp=_fp)
        except Exception as _exc:
            st.caption(f"Who we are unavailable — "
                       f"{type(_exc).__name__}: {_exc}")
        _section_feed(_by_sect, SEV.S_IDENTITY, "insj_id")

    # ── 2 · WHY WE WIN / WHY WE LOSE ────────────────────────────────────────
    elif _sec == "Why we win / why we lose":
        _render_winloss(sctx, _tids, _fp)
        _render_deserved_games(_bundle, sctx)
        _ported_cards(_plines, ("runs", "anatomy", "stops", "ledger",
                                "deserved"))
        _section_feed(_by_sect, SEV.S_WHY, "insj_why")

    # ── 3 · WHO'S HELPING ───────────────────────────────────────────────────
    elif _sec == "Who's helping":
        _player_feed(feed, pids, table)
        for pid in pids:
            for ln in feed.get(pid, []):
                _is_new(ln)
        _seen_persist()      # stamp today's first-sight dates (one write, if any)
        _impact_board(pids, table, impmap, impact)
        try:
            _DEEP.render_offense_board(sctx, pids, table, fp=_fp)
        except Exception as _exc:
            st.caption(f"Offensive board unavailable — "
                       f"{type(_exc).__name__}: {_exc}")
        try:
            _DEEP.render_defense_board(sctx, pids, table, fp=_fp)
        except Exception as _exc:
            st.caption(f"Defensive board unavailable — "
                       f"{type(_exc).__name__}: {_exc}")
        _render_wpa(pids, impact, table, side="off")
        _render_wpa(pids, impact, table, side="def")
        _render_pnr(pids, roles, table)
        try:
            _DEEP.render_foul_rates(pids, table)
        except Exception as _exc:
            st.caption(f"Foul-rate board unavailable — "
                       f"{type(_exc).__name__}: {_exc}")
        _render_passers(sctx, pids, table, _fp)
        _render_ball_movement(sctx, pids, table, _tids, _fp)
        _ported_cards(_plines, ("involve", "hero", "fouls", "clock", "reb"))
        _section_feed(_by_sect, SEV.S_HELPING, "insj_help")

    # ── 4 · WHO TO PLAY TOGETHER ────────────────────────────────────────────
    elif _sec == "Who to play together":
        try:
            from helpers.dashboard import insights_lineups as _LU
            _LU.render(sctx, table=table, fp=_fp)
        except Exception as _exc:
            st.caption(f"Lineup section unavailable — "
                       f"{type(_exc).__name__}: {_exc}")
        _section_feed(_by_sect, SEV.S_TOGETHER, "insj_tog")

    # ── 5 · WHAT THEY'LL TAKE AWAY ──────────────────────────────────────────
    elif _sec == "What they'll take away":
        st.caption(
            "The same content as a self-scout, written the way an opposing "
            "staff would write it. Nothing here is opponent prep — game "
            "planning against someone else stays in the War Room.")
        _ported_cards(_plines, ("selfscout", "tovs", "scheme"))
        _render_tendencies(sctx, _tids, _fp)
        _render_shot_map(sctx, _tids, _fp)
        _render_boards(pids, table, cliffs)
        _render_matchup_grid(sctx, pids, table, _tids, _fp)
        _section_feed(_by_sect, SEV.S_SCOUT, "insj_scout")

    # ── 6 · MONDAY ──────────────────────────────────────────────────────────
    elif _sec == "Monday":
        _render_monday(_ranked)

    # ── 7 · RECEIPTS ────────────────────────────────────────────────────────
    else:
        try:
            _DEEP.ported_blocks(sctx, fp=_fp, cols=4)
        except Exception as _exc:
            st.caption(f"Engine blocks unavailable — "
                       f"{type(_exc).__name__}: {_exc}")
        try:
            _DEEP.render_ported(sctx, fp=_fp)
        except Exception as _exc:
            st.caption(f"Ported sections unavailable — "
                       f"{type(_exc).__name__}: {_exc}")
        _section_feed(_by_sect, SEV.S_RECEIPTS, "insj_rec")
        _severity_audit(_ranked)


def _section_feed(by_sect, section, key):
    """Every ranked finding that belongs to this section, in full.

    THE LAW, ON SCREEN. The deck shows five; this shows all of them, ordered by
    the same severity. No cap, no confidence floor, no "top N" — if an engine
    fired it, a coach is entitled to it, and severity only decides what she
    reads first.
    """
    from helpers.dashboard import insights_brief as _BR
    rows = by_sect.get(section) or []
    if not rows:
        return
    _BR._hdr(f"Every finding here — {len(rows)}",
             "Ranked by points at stake × reliability × sample. Nothing is "
             "capped: severity decides the order, never the membership.")
    _BR.grid([_BR.block(
        str(f.get("metric") or "Read"),
        n=(f.get("subject") or None),
        lines=[(SEV.pts_chip(f.get("pts")) if f.get("pts") is not None
                else SEV.r_chip(f),
                _b(str(f.get("text") or "")))])
        for f in rows], cols=3)
    _meas, _tot = SEV.measured_count(rows)
    if _meas:
        st.caption(
            f"**{_meas} of {_tot}** sit on metrics the reliability book has "
            f"actually measured, and those carry their `r=` inline. The rest "
            f"have no chip because there is nothing measured to put in one — "
            f"they rank at the book's floor and they all still render. "
            f"Reliability decides the ORDER here, never the membership.")
    else:
        st.caption(
            f"None of these {_tot} sit on a metric the reliability book has "
            "measured yet, so none carries an `r=` chip. They still render in "
            "full — reliability decides the order, never the membership.")
    _evidence_jumps([{"metric": f.get("metric")} for f in rows], key=key)


def _ported_cards(plines, keys):
    """A ported engine's verdict, rendered where its question is asked.

    The long-form accordion version with its captions and its evidence pointers
    still lives on Receipts — this is the same lines, unhidden, beside the
    section they answer.
    """
    from helpers.dashboard import insights_deep as _DEEP
    for key, header, cap, _home in _DEEP._PORT_SECTIONS:
        if key not in keys:
            continue
        v = (plines or {}).get(key)
        if not v:
            continue
        st.markdown(f"<div class='lab-hdr'>{header}</div>",
                    unsafe_allow_html=True)
        st.markdown(f"<div class='hdr-sub'>{html.escape(cap)}</div>",
                    unsafe_allow_html=True)
        st.markdown(verdict_card(v), unsafe_allow_html=True)


def _player_feed(feed, pids, table):
    """One dense block per player, packed 4 across, uncapped."""
    from helpers.dashboard import insights_brief as _BR
    n_lines = sum(len(feed.get(p, [])) for p in pids)
    _BR._hdr("Every player, every read",
             f"{n_lines} findings across "
             f"{sum(1 for p in pids if feed.get(p))} players · scored vs the "
             f"whole league, not this roster · every line shown")
    blocks = []
    for pid in pids:
        lines = feed.get(pid, [])
        if not lines:
            continue
        r = table[pid]
        sub = []
        if r.get("OVERALL") is not None:
            sub.append(("OVR", f"{r['OVERALL']:.0f}"))
        if r.get("MIN"):
            sub.append(("MIN", f"{r['MIN']:.0f}"))
        blocks.append(_BR.block(
            r["name"], n=f"{len(lines)} read"
                         f"{'s' if len(lines) != 1 else ''}",
            rows=sub,
            lines=[(ln.get("metric"),
                    f"<span style='color:var(--subtext)'>"
                    f"n={ln.get('n')}</span> {_b(ln['text'])}")
                   for ln in lines]))
    if blocks:
        _BR.grid(blocks, cols=4)
    else:
        st.caption("No standout signals yet — this roster reads close to "
                   "league average on the tracked splits, or needs more games.")


def _impact_board(pids, table, impmap, wpa):
    """RAPM · HoopWAR · WPA on one row, with the possession sample beside each.

    Free: `_league` already solves the ridge for the stats-vs-substance
    generator, so this board reads a result the page has paid for rather than
    solving it a second time.
    """
    rows = []
    for pid in pids:
        im = (impmap or {}).get(pid) or {}
        wp = (wpa or {}).get(pid) or {}
        if not im and not wp:
            continue
        rows.append({
            "Player": (table.get(pid) or {}).get("name") or f"#{pid}",
            "RAPM": (f"{im['rapm']:+.1f}" if im.get("rapm") is not None
                     else "—"),
            "O-RAPM": (f"{im['orapm']:+.1f}" if im.get("orapm") is not None
                       else "—"),
            "D-RAPM": (f"{im['drapm']:+.1f}" if im.get("drapm") is not None
                       else "—"),
            "HoopWAR": (f"{im['war']:+.2f}" if im.get("war") is not None
                        else "—"),
            "Off WPA": f"{wp.get('off_wpa') or 0:+.2f}",
            "Def WPA": f"{wp.get('def_wpa') or 0:+.2f}",
            "Clutch": f"{wp.get('clutch_wpa') or 0:+.2f}",
            "Poss": im.get("poss") or 0,
            "_s": (im.get("rapm") if im.get("rapm") is not None else -99),
        })
    if not rows:
        return
    rows.sort(key=lambda r: -r["_s"])
    for r in rows:
        r.pop("_s")
    from helpers.dashboard import insights_brief as _BR
    _BR._hdr("Impact board — adjusted, not raw",
             "RAPM strips out who a player shared the floor with; HoopWAR "
             "prices that in wins; WPA is the leverage-weighted record of what "
             "actually swung games. Read them together — they disagree when a "
             "player's minutes flatter her.")
    st.markdown(dense_table(rows), unsafe_allow_html=True)
    st.caption("Poss = the possessions the ridge had to work with. A player "
               "under a few hundred is being carried by the box-impact prior, "
               "not measured.")


def _render_monday(ranked):
    """Ranked practice priorities, with the points at stake.

    MONDAY NAMES THE PROBLEM. IT DOES NOT PRESCRIBE THE DRILL. A metric→drill
    mapping would be authored by us rather than measured by the app, and this
    book's standing rule is that a sentence needs a measurement behind it. The
    coach decides how to fix it.

    The narrowing — negative direction AND an authored `rehearsable` metric —
    is a display grouping INSIDE Monday. It removes nothing from any other
    section; the full uncapped list still renders in each of them.
    """
    from helpers.dashboard import insights_brief as _BR
    rows = SEV.monday(ranked)
    _BR._hdr(f"Monday — {len(rows)} things practice can move",
             "Everything below points the wrong way AND sits on a metric the "
             "app has authored as rehearsable. Ordered by what it is costing.")
    if not rows:
        st.caption(
            "Nothing on the rehearsable list is pointing the wrong way right "
            "now. That is a real answer, not an empty state — the findings "
            "that fired are either going the right way or sit on metrics a "
            "practice plan does not move (schedule luck, opponent strength, "
            "close-game variance).")
        return
    _priced = [f for f in rows if f.get("pts") is not None]
    st.markdown(dense_table([{
        "Priority": i,
        "What": f.get("metric"),
        "Who": f.get("subject") or "Team",
        "Costing": SEV.pts_chip(f.get("pts")),
        "Sample": f.get("n"),
        "Reliability": SEV.r_cell(f),
        "Evidence in": SEV.SECTION_LABELS.get(f.get("section"), "Receipts"),
    } for i, f in enumerate(rows, start=1)]), unsafe_allow_html=True)
    if _priced:
        st.caption(
            f"**{len(_priced)} of {len(rows)}** carry a points conversion, and "
            f"together they are worth "
            f"**{sum(abs(f['pts']) for f in _priced):.1f} pts/g** — that is "
            f"the size of the practice list, not a projection of what fixing "
            f"it returns.")
    else:
        st.caption(
            "**None of these carry a points conversion yet.** `Costing` is an "
            "em dash rather than a zero because no tag beats a wrong tag — the "
            "derivation table in `helpers/insights_severity.py` grows only as "
            "conversions are proven, and every one of these metrics is still "
            "waiting for one. The ORDER is still real: it is reliability × "
            "sample.")
    st.markdown(verdict_card([
        (f.get("metric"), f.get("n"), str(f.get("text") or ""))
        for f in rows]), unsafe_allow_html=True)


def _severity_audit(ranked):
    """The whole ranked list, as a table, with its inputs exposed.

    Lives on Receipts because that is where a coach goes to check the app's
    work. The two bands are visible as a column, so "why is this above that"
    is answerable without reading the source.
    """
    if not ranked:
        return
    tagged = sum(1 for f in ranked if f.get("band") == SEV.BAND_TAGGED)
    unmeasured = sum(1 for f in ranked if f.get("r_measured") is None)
    with st.expander(f"⚖️ The severity ranking — all {len(ranked)} findings, "
                     f"and how each was scored", expanded=False):
        st.caption(
            f"**{tagged}** findings carry a points-per-game conversion and "
            f"sort above the **{len(ranked) - tagged}** that do not. The bands "
            "never interleave: a neutral stand-in for missing materiality "
            "would let an untagged read outrank a genuinely small tagged one, "
            "which is the app inventing a number it does not have. Within a "
            "band the score can tie, and the order finishes on the miner's own "
            "|z| — a tiebreak, not part of the score.")
        st.caption(
            f"**Reliability** is the book's measured split-half r — an em dash "
            f"means `helpers/reliability.py` has never measured that metric, "
            f"which is true of **{unmeasured}** of these. Those are RANKED at "
            f"the book's floor ({SEV.UNMEASURED_R:.2f}) so they sort last "
            f"within their band, and that floor is deliberately never printed "
            f"in the r= column: it is a ranking weight, not a finding about "
            f"the metric. `weight` is what the sort actually used, which is "
            f"why the two columns differ.")
        st.markdown(dense_table([{
            "#": i,
            "Band": ("pts/g" if f.get("band") == SEV.BAND_TAGGED
                     else "no conversion"),
            "Metric": f.get("metric"),
            "Who": f.get("subject") or "Team",
            "pts/g": SEV.pts_chip(f.get("pts")),
            "Reliability": SEV.r_cell(f),
            "weight": f"{f.get('r', 0):.2f}",
            "conf": f"{f.get('confidence', 0):.2f}",
            "severity": f"{f.get('severity', 0):.3f}",
            "Section": SEV.SECTION_LABELS.get(f.get("section"), "Receipts"),
        } for i, f in enumerate(ranked, start=1)]), unsafe_allow_html=True)


def _render_winloss(ctx, _tids, _fp):
    """The wins-vs-losses half of the page.

    The strength split renders as its VERDICT here; the identical 7-metric
    table is on Charts → Trends (the page's `_strength_split`), and two copies
    of one table is length without information.
    """
    # ── deep dive: offense vs TOP-half vs BOTTOM-half opponents ──────────────
    _ss = _strength(ctx.gender, ctx.team_id, _tids,
                    getattr(ctx, "season", "Current"), fp=_fp) \
        if getattr(ctx, "team_id", None) else {"available": False}
    st.markdown("<div class='lab-hdr'>Do they beat good teams, or just bad "
                "ones?</div>", unsafe_allow_html=True)
    if not _ss.get("available"):
        st.caption("Needs more tracked games against both stronger and weaker "
                   "opponents (≥15 shots each side) — this split fills in as the "
                   "schedule builds.")
    else:
        _tp, _bt = _ss["top"], _ss["bottom"]
        _dp = (_tp["PPP"] or 0) - (_bt["PPP"] or 0)
        if _dp <= -0.12:
            _v = (f"⚠ <b>{abs(_dp):.2f} PPP drop</b> vs the top half — the "
                  f"record is built on the weaker half of the schedule.")
        elif _dp >= 0.12:
            _v = (f"<b>+{_dp:.2f} PPP</b> vs the top half — they raise their "
                  f"level against good teams.")
        else:
            _v = "Holds within 0.12 PPP either way — opponent-proof."
        st.markdown(verdict_card([(
            "Strength of opponent",
            _ss["top_games"] + _ss["bottom_games"],
            f"{_v} Top half <b>{_tp['PPP']:.2f}</b> PPP "
            f"({_ss['top_games']}g) · bottom half <b>{_bt['PPP']:.2f}</b> "
            f"({_ss['bottom_games']}g).")]),
            unsafe_allow_html=True)
        _jump_btn("Charts", "Charts → Trends: the full 7-metric split →",
                  "insj_str", sub="Trends")

    # ── deep dive: offense IN WINS vs IN LOSSES ───────────────────────────────
    _wl = _winloss(ctx.gender, ctx.team_id, _tids, fp=_fp) \
        if getattr(ctx, "team_id", None) else {"available": False}
    st.markdown("<div class='lab-hdr'>Deep dive — in wins vs in losses</div>",
                unsafe_allow_html=True)
    if not _wl.get("available"):
        st.caption("Needs ≥15 shots in both wins and losses — this split fills in "
                   "as the record builds.")
    else:
        _w, _l = _wl["win"], _wl["loss"]
        st.markdown(dense_table(_split_rows(
            _w, _l, f"In wins ({_wl['win_games']})",
            f"In losses ({_wl['loss_games']})")),
            unsafe_allow_html=True)
        # what changes when they lose — the biggest metric swing tells the story
        _cands = [("3-point volume", "3PA_rate"), ("rim pressure", "rim_rate"),
                  ("ball movement", "ast_rate"), ("open looks", "open_rate")]
        _sw = max(_cands, key=lambda c: abs((_w.get(c[1]) or 0)
                                            - (_l.get(c[1]) or 0)))
        _d = (_w.get(_sw[1]) or 0) - (_l.get(_sw[1]) or 0)
        _dir = "up" if _d > 0 else "down"
        st.caption(
            f"Biggest style swing: **{_sw[0]}** is {_dir} "
            f"{abs(_d) * 100:.0f} pts in wins ({_pct(_w.get(_sw[1]))} vs "
            f"{_pct(_l.get(_sw[1]))}). eFG% "
            f"{_pct(_w.get('eFG'))} in wins vs {_pct(_l.get('eFG'))} in losses — "
            "what shows up when this team is at its best.")

    # ── what separates wins from losses — THIS team's signature stats ────────
    _wa = _wl_align(ctx.gender, ctx.team_id, _tids, fp=_fp) \
        if getattr(ctx, "team_id", None) else {"available": False}
    if _wa.get("available"):
        st.markdown("<div class='lab-hdr'>What separates wins from losses — "
                    "this team's signature stats</div>", unsafe_allow_html=True)
        st.caption(
            f"Every team has its own handful of stats that track its results — "
            f"these are the ones that split this team's **{_wa['win_games']} "
            f"wins** from its **{_wa['loss_games']} losses** hardest "
            "(effect-size ranked over the tracked games).")

        def _wlfmt(v, fmt):
            return f"{v * 100:.0f}%" if fmt == "pct" else fmt.format(v)
        _wcols = st.columns(min(4, max(2, len(_wa["rows"]))))
        for i, r in enumerate(_wa["rows"]):
            up = r["d"] > 0
            arrow = "▲" if up else "▼"
            clr = "var(--good)" if up else "var(--bad)"
            _wcols[i % len(_wcols)].markdown(
                f"<div class='gloss-card' style='text-align:center'>"
                f"<div style='font-size:11px;color:var(--subtext)'>{r['label']}"
                f"</div><div style='font-size:17px;font-weight:800;color:{clr}'>"
                f"{arrow} {_wlfmt(r['win'], r['fmt'])}"
                f"<span style='font-size:11px;color:var(--subtext)'> in wins"
                f"</span></div><div style='font-size:11px;color:var(--subtext)'>"
                f"{_wlfmt(r['loss'], r['fmt'])} in losses · d={r['d']:+.1f}"
                f"</div></div>", unsafe_allow_html=True)
        st.caption("▲ = higher in wins · ▼ = higher in losses (for opponent "
                   "stats, lower is the winning direction). d = effect size — "
                   "how many SDs apart the win and loss averages sit.")

        # ── record by how many of the signature goals the team hit ────────────
        _rec = _wa.get("record") or []
        _goals = _wa.get("goals") or []
        if _rec and _goals:
            _n = len(_goals)
            # each goal's target, on the winning side (≥ / ≤)
            _gbits = []
            for gp in _goals:
                _t = _wlfmt(gp["target"], gp["fmt"])
                _gbits.append(f"{gp['label']} {'≥' if gp['win_high'] else '≤'} {_t}")
            st.markdown("<div class='lab-hdr'>Record by goals hit</div>",
                        unsafe_allow_html=True)
            st.caption(
                f"The **{_n} goals**: " + " · ".join(_gbits) +
                f". Each game hits 0–{_n} of them; the record shows how the team "
                "does at each level — the four-factors 'win the stats, win the "
                "game' read. Target = midpoint between the win and loss averages.")
            _rrows = []
            for r in _rec:
                w, l = r["wins"], r["losses"]
                _rrows.append({
                    "Goals hit": f"{r['n']} / {_n}",
                    "Record": f"{w}–{l}",
                    "Win%": (f"{100 * w / r['games']:.0f}%" if r["games"] else "—"),
                    "Games": r["games"],
                })
            st.markdown(dense_table(_rrows,
                        columns=["Goals hit", "Record", "Win%", "Games"]),
                        unsafe_allow_html=True)
    elif _wl.get("available"):
        st.caption("Signature win/loss stats need ≥2 tracked games on each "
                   "side of the record — fills in as results build.")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _team_located(team_id, tids, fp=None):
    """This team's tap-located attempts — the shot map's only input."""
    if not team_id or not tids:
        return []
    return S.located_shots(game_ids=list(tids), team_id=team_id)


def _render_shot_map(ctx, _tids, _fp):
    """The shot map, on Insights for the first time.

    Insights has had zone TABLES since it was written and no court anywhere,
    which is the one thing every coach reaches for first. It belongs in the
    scout's section rather than beside the offensive board: the question here
    is "what does an opponent see when they chart us", and a chart is the
    literal answer.
    """
    shots = _team_located(getattr(ctx, "team_id", None), tuple(_tids or ()),
                          fp=_fp)
    if len(shots) < 25:
        return
    try:
        import helpers.court as CRT
        fig, n = CRT.shot_map(shots, title="")
    except Exception as exc:
        st.caption(f"Shot map unavailable — {type(exc).__name__}: {exc}")
        return
    if not n:
        return
    from helpers.dashboard import insights_brief as _BR
    _BR._hdr(f"The shot chart an opponent would draw — {n} located attempts",
             "Green = make, red ✕ = miss. Only tap-located attempts appear; "
             "legacy zone-only shots are in the tables above, not here.")
    st.plotly_chart(fig, width="stretch", key="ins_scout_shotmap")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _matchups(gender, tids, _table, fp=None):
    """{defender_id: {difficulty, shots_faced, Difficulty100}} for the pool.

    `_table` is the league player table and carries a LEADING UNDERSCORE so
    Streamlit does not hash it: it is a 100+ row dict rebuilt every run, and
    hashing it would cost more than the engine it keys. `tids` + `fp` already
    identify the data it was built from. Without a table there is no scorer-
    quality map and the engine returns nothing, so it is required, not optional.
    """
    import helpers.matchups as MU
    if not tids or not _table:
        return {}
    return MU.matchup_difficulty(game_ids=list(tids), table=_table)


def _render_matchup_grid(ctx, pids, table, _tids, _fp):
    """Who each defender actually guarded, and how hard that assignment was.

    League-relative (50 = an average assignment), because "she guarded their
    best scorer" only means something against what everyone else was asked to
    do. It is a record of these games — assignment shares measure r .17-.64 —
    and the caption says so rather than letting the 0-100 index imply a trait.
    """
    mm = _matchups(ctx.gender, tuple(_tids or ()), table, fp=_fp)
    rows = []
    for pid in pids:
        m = mm.get(pid)
        if not m or not m.get("shots_faced"):
            continue
        rows.append({
            "Defender": (table.get(pid) or {}).get("name") or f"#{pid}",
            "Assignment difficulty": f"{m.get('Difficulty100') or 50:.0f}",
            "Avg shooter quality": f"{m.get('difficulty') or 0:.1f}",
            "Shots faced": m.get("shots_faced"),
            "_s": m.get("Difficulty100") or 0,
        })
    if len(rows) < 2:
        return
    rows.sort(key=lambda r: -r["_s"])
    for r in rows:
        r.pop("_s")
    from helpers.dashboard import insights_brief as _BR
    _BR._hdr("Matchup difficulty — who drew the hard jobs",
             "Attempt-weighted quality of the shooters each defender actually "
             "guarded, indexed against the league (50 = average assignment).")
    st.markdown(dense_table(rows), unsafe_allow_html=True)
    st.caption(
        "A RECORD of these games, not a trait. The opponent chooses the "
        "assignment, which is why defender assignment shares measure r "
        ".17-.64 against a shooter's own diet at .70-.92 — read this as what "
        "happened, and hide a defender by changing what happens next.")
    _jump_btn("Charts", "Charts → Defense → Team Defense: the full matchup "
              "grid →", "insj_mu", sub=("Defense", "Team Defense"))


def _render_tendencies(ctx, _tids, _fp):
    """Self-scout: shot tendencies (force left/right, where shots live)."""
    _te = _tendencies(ctx.gender, ctx.team_id, _tids, fp=_fp) \
        if getattr(ctx, "team_id", None) else {"available": False}
    st.markdown("<div class='lab-hdr'>Self-scout — shot tendencies (how to defend "
                "us)</div>", unsafe_allow_html=True)
    st.markdown("<div class='hdr-sub'>Where their shots live — side of the "
                "floor and depth. What an opposing scout keys on.</div>",
                unsafe_allow_html=True)
    if not _te.get("available"):
        st.caption("Needs ~30 tracked shots to map the tendencies — fills in fast.")
    else:
        _sd = _te["side"]
        _lft, _rgt = _sd["Left"], _sd["Right"]
        if abs(_lft - _rgt) >= 0.10:
            _heavy = "left" if _lft > _rgt else "right"
            _force = "right" if _heavy == "left" else "left"
            st.caption(f"**{max(_lft, _rgt) * 100:.0f}%** of shots come from their "
                       f"**{_heavy} side** — a defense can **force them {_force}**. "
                       f"(Left {_pct(_lft)} · Middle {_pct(_sd['Middle'])} · Right "
                       f"{_pct(_rgt)}.)")
        else:
            st.caption(f"Balanced left/right (Left {_pct(_lft)} · Right {_pct(_rgt)})"
                       " — no strong side to force.")
        st.caption(f"Shot diet: rim {_pct(_te['rim_rate'])} · mid "
                   f"{_pct(_te['mid_rate'])} · three {_pct(_te['three_rate'])}. "
                   "Take away their best zone, live with the worst. (Play-call "
                   "predictability + over-used sets live on the Scout tab.)")

        # ── split the zone tendencies by shot value (2PT vs 3PT) — a team can
        # be right-side heavy from three but rim-balanced, and lumping them hides
        # it. Two side-by-side tables, each zone-ranked within its shot type. ──
        def _tend_table(bucket, title):
            zz = sorted((z for z in bucket["zones"] if z["poss"]),
                        key=lambda z: -z["poss"])
            sd = bucket["side"]
            st.markdown(f"**{title}** · {bucket['total']} shots · "
                        f"L {_pct(sd['Left'])} / M {_pct(sd['Middle'])} / "
                        f"R {_pct(sd['Right'])}")
            if zz:
                st.markdown(dense_table([{
                    "Zone": z["label"], "Shots": z["poss"],
                    "Share": _pct(z["share"]), "FG%": _pct(z["FG%"]),
                    "PPP": (f"{z['PPP']:.2f}" if z["PPP"] is not None else "—")}
                    for z in zz]), unsafe_allow_html=True)
            else:
                st.caption("— none tracked —")

        _c2, _c3 = st.columns(2)
        with _c2:
            _tend_table(_te["two"], "2-point shots")
        with _c3:
            _tend_table(_te["three"], "3-point shots")


def _render_passers(ctx, pids, table, _fp):
    """Passer quality — the VERDICT only.

    The full table renders on Charts → Offense → Playmaking (the page's
    `_passer_quality`), and rendering it twice made the flagship longer without
    making it say more, and gave two surfaces the chance to drift apart. This
    module's own docstring claims the reads are gathered here while the charts
    stay where they live; for this section that claim was not true until now.
    """
    _pq = _passers(ctx.gender, getattr(ctx, "season_gp", None), fp=_fp)
    _prows = sorted(((pid, _pq[pid]) for pid in pids if pid in _pq),
                    key=lambda t: -t[1]["xPPS_created"])
    if not _prows:
        return
    st.markdown("<div class='lab-hdr'>Passer quality — looks created vs "
                "finished</div>", unsafe_allow_html=True)
    _best = _prows[0]
    _lines = [(
        "Look creator", _best[1]["feeds"],
        f"<b>{table[_best[0]]['name']}</b> creates the best looks on the "
        f"roster — <b>{_best[1]['xPPS_created']:.2f} xPPS</b> over "
        f"{_best[1]['feeds']} feeds.")]
    # every passer whose teammates under- or over-converted materially
    _gap = [(pid, v) for pid, v in _prows if abs(v["finish_delta"]) >= 0.15
            and v["feeds"] >= 10]
    for pid, v in _gap:
        cold = v["finish_delta"] < 0
        _lines.append((
            "Finish gap" if cold else "Finish bonus", v["feeds"],
            f"<b>{table[pid]['name']}</b> — {v['xPPS_created']:.2f} xPPS "
            f"created, {v['PPS']:.2f} returned "
            f"(<b>{v['finish_delta']:+.2f}</b>). "
            + ("Looks were there; the shooters missed them."
               if cold else "Teammates converted above the look value.")))
    st.markdown(verdict_card(_lines), unsafe_allow_html=True)
    _jump_btn("Charts", "Charts → Offense → Playmaking: the full passer table →",
              "insj_pq", sub=("Offense", "Playmaking"))


def _render_ball_movement(ctx, pids, table, _tids, _fp):
    """Ball movement — the verdict card (#8b): xA vs AST, hockey assists,
    on-floor attempt tilt. Every line carries a plain-word verdict."""
    _bm_tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    _xa_map, _corsi_map, _hast_map = _ball_movement(ctx.gender, _bm_tids, fp=_fp)
    _pidset = set(pids)
    _team_xa = [(pid, _xa_map[pid]) for pid in pids if pid in _xa_map]
    if _team_xa:
        _bm_lines = []
        # 1) team ΣxA vs actual AST — finishing luck on the looks created
        _sx = sum(v["xA"] for _, v in _team_xa)
        _sa = sum(v["AST"] for _, v in _team_xa)
        _sf = sum(v["feeds"] for _, v in _team_xa)
        _luck = _sa - _sx
        if _luck >= 1.5:
            _vtxt = ("shooters are <b>over-converting the looks</b> — raw "
                     "assists flatter the movement a touch; expect some to "
                     "come back to earth")
        elif _luck <= -1.5:
            _vtxt = ("<b>cold finishing is hiding good movement</b> — the "
                     "looks are there, trust the process (and xA), not the "
                     "assist column")
        else:
            _vtxt = ("finishing is running <b>right at expectation</b> — the "
                     "assist column is an honest read of the movement")
        _bm_lines.append((
            "Ball movement", _sf,
            f"created <b>{_sx:.1f} expected assists</b> vs {_sa} actual "
            f"({_luck:+.1f} finishing luck): {_vtxt}."))
        # 2) hockey assists — opt-in capture, honest about thinness
        _hn = sum(_hast_map.get(pid, 0) for pid in pids)
        if _hn:
            _hl = max(((pid, _hast_map.get(pid, 0)) for pid in pids),
                      key=lambda t: t[1])
            _bm_lines.append((
                "2nd pass", _hn,
                f"<b>{_hn} hockey assist{'s' if _hn != 1 else ''}</b> tagged — "
                f"<b>{table[_hl[0]]['name']}</b> leads ({_hl[1]}). The pass "
                "before the pass is getting credited."))
        else:
            _bm_lines.append((
                "2nd pass", 0,
                "no hockey assists tagged yet — it's an opt-in tap (the pass "
                "before the assist on a made shot); tag a few and the swing "
                "passers get their credit here."))
        # 3) attempt tilt — best/worst on-floor Corsi% with a real sample
        _cr = [(pid, c) for pid, c in ((p, _corsi_map.get(p)) for p in pids)
               if c and (c["cf"] + c["ca"]) >= 50 and c["corsi_pct"] is not None]
        if len(_cr) >= 2:
            _cb = max(_cr, key=lambda t: t[1]["corsi_pct"])
            _cw = min(_cr, key=lambda t: t[1]["corsi_pct"])
            _bm_lines.append((
                "Attempt tilt", _cb[1]["cf"] + _cb[1]["ca"],
                f"the floor tilts hardest with <b>{table[_cb[0]]['name']}</b> on "
                f"({_cb[1]['corsi_pct'] * 100:.0f}% of attempts ours, "
                f"{_cb[1]['corsi']:+d}) and leaks most with "
                f"<b>{table[_cw[0]]['name']}</b> "
                f"({_cw[1]['corsi_pct'] * 100:.0f}%, {_cw[1]['corsi']:+d}) — "
                "shot volume, not shooting luck, so it's a lineup lever you "
                "can actually pull."))
        st.markdown("<div class='lab-hdr'>Ball movement — verdict</div>",
                    unsafe_allow_html=True)
        st.markdown(verdict_card(_bm_lines), unsafe_allow_html=True)
        st.caption("xA values every feed by the LOOK it created (league "
                   "make-rate for that zone/creation/contest), so a teammate's "
                   "cold night can't erase good passing. Corsi = shot attempts "
                   "for − against while on the floor (min 50 attempts). The "
                   "per-player table lives on Charts → Offense → Playmaking.")
        _jump_btn("Charts", "Charts → Offense → Playmaking: the xA / Corsi "
                  "table →", "insj_bm", sub=("Offense", "Playmaking"))


def _render_boards(pids, table, cliffs):
    """Force-hand + space dependence, side by side. Both lists render in FULL —
    they were capped at 8 and 10, which silently dropped the back half of a
    roster from a board whose whole job is to rank a roster."""
    bc1, bc2 = st.columns(2)
    with bc1:
        st.markdown("<div class='lab-hdr'>Force them off their hand</div>",
                    unsafe_allow_html=True)
        st.markdown("<div class='hdr-sub'>Strong-hand vs weak-hand FG%, "
                    "min 6 FGA each side. Push them to the red bar.</div>",
                    unsafe_allow_html=True)
        hb = []
        for pid in pids:
            row = table[pid]
            dom, weak = row.get("Dom_FG%"), row.get("Weak_FG%")
            dfa, wfa = row.get("Dom_FGA") or 0, row.get("Weak_FGA") or 0
            if dom is None or weak is None or dfa < 6 or wfa < 6:
                continue
            hb.append((dom - weak, row["name"], dom, weak, int(dfa + wfa)))
        hb.sort(key=lambda t: -t[0])
        if not hb:
            st.caption("Needs tap-located shots on both sides — fills in as games "
                       "are tagged with the court tap.")
        for gap, nm, dom, weak, n in hb:
            st.markdown(
                f"<div style='margin-bottom:7px'><div style='display:flex;"
                f"justify-content:space-between;font-size:12px'><b>{nm}</b>"
                f"<span style='color:var(--accent)'>+{gap:.0f} · n={n}</span></div>"
                f"<div style='font-size:10px;color:var(--subtext)'>strong {dom:.0f}% "
                f"· weak {weak:.0f}%</div>"
                f"<div class='pl-pct-track'><div class='pl-pct-fill' "
                f"style='width:{max(2,min(100,dom)):.0f}%;background:var(--good)'>"
                f"</div></div><div class='pl-pct-track' style='margin-top:2px'>"
                f"<div class='pl-pct-fill' style='width:{max(2,min(100,weak)):.0f}%;"
                f"background:var(--bad)'></div></div></div>", unsafe_allow_html=True)

    with bc2:
        st.markdown("<div class='lab-hdr'>Space dependence (open vs guarded)</div>",
                    unsafe_allow_html=True)
        st.markdown("<div class='hdr-sub'>Open FG% minus contested FG%. "
                    "High = needs space, negative = contest-proof.</div>",
                    unsafe_allow_html=True)
        cb = sorted(((cliffs[p]["cliff"], table[p]["name"], cliffs[p]["n"])
                     for p in pids if p in cliffs), key=lambda t: -t[0])
        if not cb:
            st.caption("Needs more contested shots (guarded tag) to rank.")
        for cliff, nm, n in cb:
            tag = ("needs space" if cliff > 8 else
                   "contest-proof" if cliff < -2 else "neutral")
            clr = ("var(--bad)" if cliff > 8 else
                   "var(--good)" if cliff < -2 else "var(--subtext)")
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:5px 0;"
                f"border-bottom:1px solid var(--card-border);font-size:12px'>"
                f"<span><b>{nm}</b> <span style='color:var(--subtext);font-size:10px'>"
                f"n={n}</span></span><span style='color:{clr}'>{cliff:+.0f} · {tag}</span>"
                f"</div>", unsafe_allow_html=True)


def _render_wpa(pids, impact, table, side="def"):
    """Win impact (WPA) for this team, sorted by the side that owns the tab.

    One renderer for both tabs. The table always shows defensive, offensive and
    clutch WPA together — the comparison between a player's two halves is the
    point — and only the heading and the sort change, so the Offense and Defense
    tabs cannot drift into two different versions of one table.
    """
    _off = side == "off"
    st.markdown(
        f"<div class='lab-hdr'>Who won games on "
        f"{'offense' if _off else 'defense'}</div>", unsafe_allow_html=True)
    st.markdown("<div class='hdr-sub'>Win probability added, min 4 GP. "
                "Defensive · offensive · clutch.</div>",
                unsafe_allow_html=True)
    irows = [{"pid": p, **impact[p]} for p in pids
             if p in impact and (impact[p].get("games") or 0) >= 4]
    if not irows:
        st.caption("Win-impact needs a few tracked games to separate signal "
                   "from noise.")
    else:
        _key = "off_wpa" if _off else "def_wpa"
        irows.sort(key=lambda r: -(r.get(_key) or 0))
        st.markdown(dense_table([{
            "Player": r["name"], "GP": r.get("games"),
            "Off WPA" if _off else "Def WPA":
                f"{r.get(_key) or 0:+.2f}",
            "Def WPA" if _off else "Off WPA":
                f"{r.get('def_wpa' if _off else 'off_wpa') or 0:+.2f}",
            "Clutch": f"{r.get('clutch_wpa') or 0:+.2f}",
        } for r in irows]), unsafe_allow_html=True)


def _render_pnr(pids, roles, table):
    """Pick-&-roll role split (lights up with play_type tags)."""
    rrows = []
    for pid in pids:
        pnr = (roles.get(pid) or {}).get("pnr")
        if not pnr:
            continue
        h, ro = pnr.get("handler", {}), pnr.get("roller", {})
        if (h.get("poss", 0) + ro.get("poss", 0)) < 1:
            continue
        rrows.append({"Player": table[pid]["name"],
                      "Handler PPP": f"{h.get('PPP') or 0:.2f}",
                      "Handler FGA": h.get("poss", 0),
                      "Roller PPP": f"{ro.get('PPP') or 0:.2f}",
                      "Roller FGA": ro.get("poss", 0)})
    if rrows:
        st.markdown("<div class='lab-hdr'>Pick-&-roll role split</div>",
                    unsafe_allow_html=True)
        st.markdown("<div class='hdr-sub'>Handler vs roller PPP. Lights up "
                    "as games get play-type tags.</div>",
                    unsafe_allow_html=True)
        st.markdown(dense_table(rrows), unsafe_allow_html=True)


def _render_deserved_games(bundle, ctx):
    """Game by game, the four terms that add up to each final margin.

    Every tracked game renders — no cap and no 'recent five'. The interesting
    rows are the disagreements, and which those are is not known in advance.
    """
    d = (bundle or {}).get("deserved") or {}
    if not d.get("available") or not d.get("rows"):
        return
    st.markdown("<div class='lab-hdr'>Game by game — margin, split four "
                "ways</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='hdr-sub'>Extra shots · selection · making · FTs sum to "
        "the final margin exactly. ⚠ = the play pointed at the other team."
        "</div>", unsafe_allow_html=True)
    rows = []
    for r in d["rows"]:
        flag = "⚠ " if (r["decided"] and not r["agree"]) else ""
        rows.append({
            "Date": (r["date"] or "")[:10],
            "Opponent": ("vs " if r["home"] else "at ") + r["opp_name"],
            "Result": f"{flag}{'W' if r['won'] else 'L'} {r['margin']:+.0f}",
            "Extra shots": f"{r['volume']:+.1f}",
            "Selection": f"{r['quality']:+.1f}",
            "Making": f"{r['making']:+.1f}",
            "Free throws": f"{r['ft_margin']:+d}",
            "Shots": f"{r['fga']}–{r['opp_fga']}",
            "Off. reb": f"{r['orb']}–{r['opp_orb']}",
            "Turnovers": f"{r['tov']}–{r['opp_tov']}",
            "Contested": f"{r['contest_rate'] * 100:.0f}%",
        })
    st.markdown(dense_table(rows), unsafe_allow_html=True)
    st.caption(
        f"Play matched result in **{d['agree']} of {d['decided']}**. "
        f"*Contested* = share of that game's FGA a defender affected "
        f"(contested .33 vs uncontested .46 leaguewide) — a feature of the "
        f"game, not a tracking figure.")

    # the single most interesting game, term by term
    import helpers.deserved as DES
    g = d.get("biggest_upset") or d.get("biggest_gap")
    if g:
        st.markdown("<div class='lab-hdr'>Widest gap between play and "
                    "result</div>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='hdr-sub'>{'vs' if g['home'] else 'at'} "
            f"{html.escape(g['opp_name'])} · final {g['margin']:+.0f} · "
            f"play {g['xmargin']:+.1f} · descriptive, not a rematch "
            f"projection</div>", unsafe_allow_html=True)
        # ONE DECIMAL, and an explicit total. At 0 dp the four terms visibly
        # failed to add to the margin the caption promised they added to
        # (+18 +4 −4 −3 = 15 against a +16 final), which reads as a broken
        # identity rather than as rounding.
        _story = DES.game_story(g, min_pts=0)
        st.markdown(verdict_card(
            [(lbl, None, f"<b>{pts:+.1f}</b> — {txt}.")
             for lbl, pts, txt in _story]
            + [("= Final", None,
                f"<b>{sum(p for _l, p, _t in _story):+.1f}</b> — the four "
                f"terms above, added up. Final margin "
                f"<b>{g['margin']:+.0f}</b>.")]),
            unsafe_allow_html=True)
