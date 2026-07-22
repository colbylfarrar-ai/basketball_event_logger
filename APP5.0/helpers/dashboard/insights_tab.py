"""
insights_tab.py — Team Dashboard > Insights tab (the scout that reads itself,
scoped to the SELECTED team).

Renders each of the team's players' most-surprising true facts (helpers/insights.py),
plus force-to-off-hand + space-dependence boards, defensive win-impact and the
pick-&-roll role split — all filtered to this team but scored vs the whole league
(so "elite" means elite leaguewide, not just on this roster). Team-scoped tracked
data, so it sits behind the team tracked gate (ctx.has_tracked).

render(ctx) @st.fragment — the page builds a SimpleNamespace ctx. Display-only.
"""
from __future__ import annotations

import re

import streamlit as st

from database.db import query
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


# ── insight line → the Team Dashboard VIEW holding its evidence ───────────────
# Every insight names its `metric`; this maps each metric to the top-level view
# where the underlying chart/table lives, so a line can offer a real jump
# instead of dead-ending. View-level only (st.tabs can't be selected
# programmatically — same constraint as the page's _jump helper).
_EVIDENCE_VIEW = {
    # player metrics → view
    "POE": "Charts", "Selection": "Charts", "3P%": "Charts",
    "Rim finish": "Charts", "HandGap": "Charts", "Spacing": "Charts",
    "Shot creation": "Charts", "Q4": "Charts", "Situational": "Charts",
    "Garbage time": "Charts", "Form": "Charts", "Consistency": "Charts",
    "PlayType": "Charts", "PlayStyle": "Charts", "PnR role": "Charts",
    "TO type": "Charts", "GuardCliff": "Charts",
    "Impact": "Lab", "On/off offense": "Lab", "On/off defense": "Lab",
    "Matchup": "Lab", "Defense": "Lab", "Rim D": "Lab", "Perim D": "Lab",
    "Disruption": "Lab", "Stint length": "Lab",
    "Usage": "Roster", "Playmaking": "Roster", "Rebounding": "Roster",
    "Fouls drawn": "Roster", "Clutch FT": "Roster",
    # team metrics → view
    "Quarters": "Charts", "Transition": "Charts", "Transition D": "Charts",
    "Runs": "Charts", "Momentum": "Charts", "Game script": "Charts",
    "Scheme": "Charts", "3PT diet": "Charts",
    "Lineups": "Lab", "Chemistry": "Lab", "Off engine": "Lab",
    "Def engine": "Lab",
    "Luck": "Schedule", "Close games": "Schedule", "Volatility": "Schedule",
    "Rest": "Schedule",
    "Keys": "Scout", "Scoutability": "Scout", "Ball security": "Scout",
    "Takeaways": "Scout",
}

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


def _evidence_jumps(lines, key):
    """Row of view-jump buttons for the evidence behind a card's lines. Sets the
    page's top-level View switcher and forces a FULL rerun (this tab is a
    fragment — a fragment-scoped rerun would never repaint the switcher)."""
    views = []
    for ln in lines:
        v = _EVIDENCE_VIEW.get(ln.get("metric"))
        if v and v not in views:
            views.append(v)
    if not views:
        return
    cols = st.columns(3)
    for i, v in enumerate(views[:3]):
        if cols[i].button(f"{v} →", key=f"{key}_{v}",
                          help=f"Open {v} — the charts behind these reads"):
            st.session_state["td_view"] = v
            st.rerun(scope="app")


def _data_fp():
    """Cheap change signature for everything this tab computes from: the event
    book (count + max id) and the finished scores (results_fingerprint). Passed
    into every cached wrapper so the heavy league engine recomputes only when
    data actually changes — with the old bare ttl=300 the whole tab silently
    re-ran the engine every 5 minutes, which is the 'Insights sometimes hangs
    on load' report. One aggregate query, a few ms."""
    import helpers.team_ratings as TR
    ev = query("SELECT COUNT(*) c, COALESCE(MAX(id),0) m FROM game_events")[0]
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
    return table, feed, roles, impact, cliffs


@st.cache_data(ttl=6 * 3600, show_spinner="Reading the team's tendencies…")
def _team_feed(gender, season="Current", team_id=None, tids=None, fp=None):
    """League-wide team insight feed (z-scored vs the tracked field) — the tab
    shows only the selected team's lines. The per-team extras (lineup / matchup
    / chemistry feeds) are built for the VIEWED team only, scoped to its own
    visible game ids, so nothing beyond the pools reads other teams' depth."""
    import helpers.team_insights as TIN
    try:
        extras = None
        if team_id is not None:
            _ex = TIN.team_extras(team_id, gender=gender,
                                  game_ids=(list(tids) if tids else None),
                                  season=season)
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
def render(ctx):
    # (Team at a glance moved to the Overview tab — UI_DENSITY_PLAN phase A.)
    _fp = _data_fp()          # cache key: recompute only when data changes
    table, feed, roles, impact, cliffs = _league(
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

    st.caption("What the tracked data says about this team — each line is the "
               "player's biggest deviation from the league, gated by sample size "
               "so a hot night never headlines. Scored vs the whole league.")

    # per-coach NEW chips: unseen lines get flagged; the blob is persisted once
    # after both feeds render (so a fragment rerun mid-scroll never eats chips).
    _is_new, _seen_persist = _seen_tracker(getattr(ctx, "team_id", None))

    # ── team auto-scout — the TEAM's own most surprising reads ────────────────
    _tlines = _team_feed(
        ctx.gender, getattr(ctx, "season", "Current"),
        getattr(ctx, "team_id", None),
        tuple(getattr(ctx, "tracked_ids", None) or ()) or None,
        fp=_fp,
    ).get(getattr(ctx, "team_id", None), [])
    if _tlines:
        st.markdown("<div class='lab-hdr'>Auto-scout — team read</div>",
                    unsafe_allow_html=True)
        _tbody = "".join(_line_html(ln, new=_is_new(ln)) for ln in _tlines)
        st.markdown(f"<div class='gloss-card'>{_tbody}</div>",
                    unsafe_allow_html=True)
        _evidence_jumps(_tlines, key="insj_team")

    # ── per-player auto-scout (the team-by-team feed) — 2-col boxed grid so a
    #    full roster's reads fit on ~half the page length ──────────────────────
    st.markdown("<div class='lab-hdr'>Auto-scout — this team</div>",
                unsafe_allow_html=True)
    _cards = []
    for pid in pids:
        lines = feed.get(pid, [])
        if not lines:
            continue
        nm = table[pid]["name"]
        body = "".join(_line_html(ln, new=_is_new(ln)) for ln in lines)
        _cards.append(
            (pid, lines,
             f"<div class='gloss-card'><b style='font-size:14px'>{nm}</b>{body}</div>"))
    if _cards:
        _pcols = st.columns(2)
        for i, (pid, lines, c) in enumerate(_cards):
            with _pcols[i % 2]:
                st.markdown(c, unsafe_allow_html=True)
                _evidence_jumps(lines, key=f"insj_{pid}")
    else:
        st.caption("No standout signals yet — this roster reads close to league "
                   "average on the tracked splits, or needs more games.")
    _seen_persist()   # stamp today's first-sight dates (one write, if any)

    # ── deep dive: offense vs TOP-half vs BOTTOM-half opponents ────────────────
    _tids = getattr(ctx, "tracked_ids", None)
    _ss = _strength(ctx.gender, ctx.team_id, _tids,
                    getattr(ctx, "season", "Current"), fp=_fp) \
        if getattr(ctx, "team_id", None) else {"available": False}
    st.markdown("<div class='lab-hdr'>Deep dive — vs top teams vs bottom teams</div>",
                unsafe_allow_html=True)
    if not _ss.get("available"):
        st.caption("Needs more tracked games against both stronger and weaker "
                   "opponents (≥15 shots each side) — this split fills in as the "
                   "schedule builds.")
    else:
        _tp, _bt = _ss["top"], _ss["bottom"]
        st.markdown(dense_table(_split_rows(
            _tp, _bt, f"vs Top-half ({_ss['top_games']}g)",
            f"vs Bottom-half ({_ss['bottom_games']}g)")),
            unsafe_allow_html=True)
        _dp = (_tp["PPP"] or 0) - (_bt["PPP"] or 0)
        if _dp <= -0.12:
            st.caption(f"⚠ Offense drops **{abs(_dp):.2f} PPP** against top-half "
                       "teams — the scoring is feasting on weaker opponents. Watch "
                       "the 3PA / rim mix above to see what stops working.")
        elif _dp >= 0.12:
            st.caption(f"This team *rises* **+{_dp:.2f} PPP** vs top-half teams — "
                       "it brings its best against the better opponents.")
        else:
            st.caption("Offense holds up about the same against strong and weak "
                       "opponents — a steady, opponent-proof profile.")

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

    # ── self-scout: shot tendencies (force left/right, where shots live) ──────
    _te = _tendencies(ctx.gender, ctx.team_id, _tids, fp=_fp) \
        if getattr(ctx, "team_id", None) else {"available": False}
    st.markdown("<div class='lab-hdr'>Self-scout — shot tendencies (how to defend "
                "us)</div>", unsafe_allow_html=True)
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

    # ── passer quality — look created vs finish (the pass-from FG% nuance) ────
    _pq = _passers(ctx.gender, getattr(ctx, "season_gp", None), fp=_fp)
    _prows = sorted(((pid, _pq[pid]) for pid in pids if pid in _pq),
                    key=lambda t: -t[1]["xPPS_created"])
    if _prows:
        st.markdown("<div class='lab-hdr'>Passer quality — looks created vs "
                    "finished</div>", unsafe_allow_html=True)
        st.caption("**Look quality** = expected value of the shots a passer sets up "
                   "(the zone/contest of the look, whether or not it dropped). "
                   "**Finish Δ** = actual − expected: a big minus means the looks "
                   "were there but the shooters missed — a *good pass to a poor "
                   "shooter*, not a bad passer.")
        st.markdown(dense_table([{
            "Passer": table[pid]["name"], "Feeds": v["feeds"],
            "Look quality (xPPS)": f"{v['xPPS_created']:.2f}",
            "Result (PPS)": f"{v['PPS']:.2f}",
            "Finish Δ": f"{v['finish_delta']:+.2f}",
            "Assist FG%": f"{v['FG%'] * 100:.0f}%",
        } for pid, v in _prows]), unsafe_allow_html=True)
        _best = _prows[0]
        st.caption(f"Top look-creator: **{table[_best[0]]['name']}** "
                   f"({_best[1]['xPPS_created']:.2f} xPPS created on "
                   f"{_best[1]['feeds']} feeds). Feeds this metric into the "
                   "playmaking read.")

    # ── ball movement — the verdict card (#8b): xA vs AST, hockey assists,
    #    on-floor attempt tilt. Every line carries a plain-word verdict. ───────
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
                   "for − against while on the floor (min 50 attempts).")

    # ── boards: force-hand + space dependence ─────────────────────────────────
    bc1, bc2 = st.columns(2)
    with bc1:
        st.markdown("<div class='lab-hdr'>Force them off their hand</div>",
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
        for gap, nm, dom, weak, n in hb[:8]:
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
        cb = sorted(((cliffs[p]["cliff"], table[p]["name"], cliffs[p]["n"])
                     for p in pids if p in cliffs), key=lambda t: -t[0])
        if not cb:
            st.caption("Needs more contested shots (guarded tag) to rank.")
        for cliff, nm, n in cb[:10]:
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

    # ── win impact (def / clutch WPA) for this team ───────────────────────────
    st.markdown("<div class='lab-hdr'>Who won games on defense</div>",
                unsafe_allow_html=True)
    irows = [{"pid": p, **impact[p]} for p in pids
             if p in impact and (impact[p].get("games") or 0) >= 4]
    if not irows:
        st.caption("Win-impact needs a few tracked games to separate signal "
                   "from noise.")
    else:
        irows.sort(key=lambda r: -(r.get("def_wpa") or 0))
        st.markdown(dense_table([{
            "Player": r["name"], "GP": r.get("games"),
            "Def WPA": f"{r.get('def_wpa') or 0:+.2f}",
            "Off WPA": f"{r.get('off_wpa') or 0:+.2f}",
            "Clutch": f"{r.get('clutch_wpa') or 0:+.2f}",
        } for r in irows]), unsafe_allow_html=True)

    # ── pick-&-roll role split (lights up with play_type tags) ────────────────
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
        st.caption("Ball-handler (used the screen) vs roll man (set it & finished). "
                   "Lights up as games are tagged with play type.")
        st.markdown(dense_table(rrows), unsafe_allow_html=True)
