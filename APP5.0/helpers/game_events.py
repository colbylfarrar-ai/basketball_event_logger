"""
game_events.py — the single live-logging WRITE path for game events.

Extracted from pages/2_Game_Tracker.py so the Streamlit tracker page and the
mobile tracker API (tracker/api.py) insert events through the SAME code: one
place owns possession-secs math, the lineup snapshot, +/- credits and the
x/y -> zone/2-3 derivation. event_log.py remains the after-the-fact EDIT layer;
this module is the live APPEND layer.

Idempotency: an event may carry a client_uuid (mobile tracker generates one per
tap so a flaky-wifi retry can't double-log). If an event with that uuid already
exists, log_event() returns its id without inserting.

Pure data layer: database.db + court_geom only, no streamlit.
"""
from __future__ import annotations

from database.db import query, execute
import helpers.court_geom as CG
from helpers.event_log import delete_event, game_people, score_from_events

EVENT_TYPES = ("shot", "free_throw", "foul", "turnover")

# Quarter length: 8-minute HS quarters, 4-minute overtimes (matches the page).
def quarter_start_secs(quarter: int) -> float:
    return 8 * 60 if quarter <= 4 else 4 * 60


def time_to_secs(t: str) -> float:
    try:
        m, s = str(t).strip().split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return 0.0


def possession_secs(game_id: int, quarter: int, t: str) -> float:
    """Elapsed clock since the previous event of this quarter (0 for the first
    event of a quarter at full clock — same convention the tracker page used)."""
    prev = query(
        "SELECT time FROM game_events WHERE game_id=? AND quarter=? "
        "ORDER BY id DESC LIMIT 1", (game_id, quarter))
    start = time_to_secs(prev[0]["time"]) if prev else quarter_start_secs(quarter)
    return max(0.0, start - time_to_secs(t))


def _snapshot_and_apply_pm(game_id, event_id, on_court, on_officials,
                           scoring_team_id=None, pts: int = 0,
                           on_official_slots=()):
    """Snapshot the floor into game_event_lineup, ensure everyone has a
    game_lineup_players row, credit +/- on scoring events, record officials.

    on_official_slots: iterable of (official_id, slot) where slot is the crew
    role (1=R, 2=U1, 3=U2 — see helpers/public_feed._SLOT_LABELS). Assigned from
    the tracker's role dropdowns; upserts the slot so a mid-game role change
    sticks, while plain on_officials rows (e.g. a foul's calling ref not on the
    assigned crew) keep a NULL slot."""
    # Dedupe by player — a pid listed twice would be credited +/- twice
    # (permanent stat corruption). Keep the first (pid, tid) per player.
    deduped: dict = {}
    for pid, tid in on_court:
        deduped.setdefault(pid, tid)
    for pid, tid in deduped.items():
        execute("INSERT OR IGNORE INTO game_event_lineup (event_id, player_id, team_id) VALUES (?,?,?)",
                (event_id, pid, tid))
        execute("INSERT OR IGNORE INTO game_lineup_players (game_id, team_id, player_id) VALUES (?,?,?)",
                (game_id, tid, pid))
        if scoring_team_id and pts:
            delta = pts if tid == scoring_team_id else -pts
            execute("UPDATE game_lineup_players SET plus_minus = plus_minus + ? "
                    "WHERE game_id=? AND player_id=?", (delta, game_id, pid))
    for oid in on_officials:
        execute("INSERT OR IGNORE INTO game_lineup_officials (game_id, official_id) VALUES (?,?)",
                (game_id, oid))
    for oid, slot in on_official_slots:
        execute("INSERT INTO game_lineup_officials (game_id, official_id, slot) "
                "VALUES (?,?,?) "
                "ON CONFLICT(game_id, official_id) DO UPDATE SET slot=excluded.slot",
                (game_id, oid, slot))


def log_event(game_id: int, ev: dict, on_court, on_officials=(),
              client_uuid: str | None = None, on_official_slots=()) -> int:
    """Append one live event and return its game_events.id.

    ev keys: event_type (required), quarter (int), time ('M:SS'), plus the
    type-specific fields below (missing keys read as None):
      shot:       primary_player_id, shot_result, shot_x, shot_y,
                  shot_type, zone (both derived from x/y when present),
                  pass_from_id, shot_created_by_id, hockey_from_id
                  (the pass before the assist), rebound_by_id,
                  blocked_by_id, guarded_by_id, play_type, defense
      free_throw: primary_player_id, shot_result, rebound_by_id
      foul:       primary_player_id (fouled), secondary_player_id (fouler),
                  official_id, play_type, defense
      turnover:   primary_player_id, stolen_by_id, play_type, defense,
                  turnover_type (pass/drive/held/shot_clock/travel — the KIND
                  of giveaway; nullable, taxonomy in helpers/turnovers)

    play_type on a foul/turnover = the set call the OFFENSE was running when it
    happened (the sticky tag in the trackers), so per-set outcomes cover
    score / turnover / foul, not just shots.

    on_court: iterable of (player_id, team_id) currently on the floor.
    on_officials: iterable of official ids working the game.
    client_uuid: idempotency key — duplicate uuid returns the existing id.
    """
    if client_uuid:
        dup = query("SELECT id FROM game_events WHERE client_uuid=?", (client_uuid,))
        if dup:
            return dup[0]["id"]

    etype = ev.get("event_type")
    if etype not in EVENT_TYPES:
        raise ValueError(f"unknown event_type: {etype!r}")
    q = int(ev.get("quarter") or 1)
    t = str(ev.get("time") or "0:00")
    poss = possession_secs(game_id, q, t)
    g = lambda k: ev.get(k)

    if etype == "shot":
        sx, sy = g("shot_x"), g("shot_y")
        if sx is not None and sy is not None:
            zone = CG.zone_from_xy(sx, sy)
            shot_type = CG.shot_value(sx, sy)
        else:
            zone = g("zone")
            shot_type = int(g("shot_type") or 2)
        eid = execute("""INSERT INTO game_events
            (game_id,event_type,quarter,time,possession_secs,primary_player_id,
             shot_type,shot_result,pass_from_id,shot_created_by_id,hockey_from_id,
             rebound_by_id,blocked_by_id,guarded_by_id,zone,shot_x,shot_y,
             play_type,defense,client_uuid)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (game_id, "shot", q, t, poss,
             g("primary_player_id"), shot_type, g("shot_result"),
             g("pass_from_id"), g("shot_created_by_id"), g("hockey_from_id"),
             g("rebound_by_id"), g("blocked_by_id"),
             g("guarded_by_id"), zone, sx, sy,
             g("play_type"), g("defense"), client_uuid))
        pts = shot_type if g("shot_result") == "make" else 0

    elif etype == "free_throw":
        eid = execute("""INSERT INTO game_events
            (game_id,event_type,quarter,time,possession_secs,
             primary_player_id,shot_result,rebound_by_id,client_uuid)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (game_id, "free_throw", q, t, poss,
             g("primary_player_id"), g("shot_result"), g("rebound_by_id"),
             client_uuid))
        pts = 1 if g("shot_result") == "make" else 0

    elif etype == "foul":
        eid = execute("""INSERT INTO game_events
            (game_id,event_type,quarter,time,possession_secs,
             primary_player_id,secondary_player_id,official_id,
             play_type,defense,client_uuid)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (game_id, "foul", q, t, poss,
             g("primary_player_id"), g("secondary_player_id"), g("official_id"),
             g("play_type"), g("defense"), client_uuid))
        pts = 0

    else:  # turnover
        eid = execute("""INSERT INTO game_events
            (game_id,event_type,quarter,time,possession_secs,
             primary_player_id,stolen_by_id,play_type,defense,turnover_type,
             client_uuid)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (game_id, "turnover", q, t, poss,
             g("primary_player_id"), g("stolen_by_id"), g("play_type"),
             g("defense"), g("turnover_type"), client_uuid))
        pts = 0

    scoring_tid = None
    if pts:
        pid = g("primary_player_id")
        if pid:
            row = query("SELECT team_id FROM players WHERE id=?", (pid,))
            scoring_tid = row[0]["team_id"] if row else None
    _snapshot_and_apply_pm(game_id, eid, on_court, on_officials,
                           scoring_tid if pts else None, pts,
                           on_official_slots=on_official_slots)
    return eid


def undo_last_event(game_id: int) -> int | None:
    """Delete the newest event of a game, reversing its +/- contribution.
    Returns the deleted event id, or None if the game has no events."""
    last = query("SELECT id FROM game_events WHERE game_id=? ORDER BY id DESC LIMIT 1",
                 (game_id,))
    if not last:
        return None
    eid = last[0]["id"]
    delete_event(game_id, eid, game_people(game_id)["pid2team"])
    return eid


# ── live read state (scoreboard the page and the API both show) ─────────────────
def live_possessions(game_id: int, t1id: int, t2id: int) -> tuple:
    """Possession count per team — a possession ends on a shot or turnover."""
    rows = query("""
        SELECT p.team_id, COUNT(*) AS poss
        FROM game_events ge JOIN players p ON p.id = ge.primary_player_id
        WHERE ge.game_id=? AND ge.event_type IN ('shot','turnover')
        GROUP BY p.team_id""", (game_id,))
    poss = {r["team_id"]: (r["poss"] or 0) for r in rows}
    return poss.get(t1id, 0), poss.get(t2id, 0)


def quarter_scores(game_id: int, t1id: int, t2id: int) -> dict:
    """{quarter: {t1id: pts, t2id: pts}} for all quarters with scoring."""
    rows = query("""
        SELECT ge.quarter, ge.event_type, ge.shot_type, p.team_id AS tid
        FROM game_events ge JOIN players p ON p.id = ge.primary_player_id
        WHERE ge.game_id=? AND ge.primary_player_id IS NOT NULL
          AND ge.event_type IN ('shot','free_throw') AND ge.shot_result='make'
        ORDER BY ge.quarter, ge.id""", (game_id,))
    out: dict = {}
    for r in rows:
        qd = out.setdefault(r["quarter"], {t1id: 0, t2id: 0})
        pts = r["shot_type"] if r["event_type"] == "shot" else 1
        if r["tid"] in qd:
            qd[r["tid"]] += pts
    return out


def live_state(game_id: int, n_events: int = 25) -> dict:
    """Scoreboard + recent events for a game (home = team1, away = team2)."""
    g = query("SELECT team1_id, team2_id FROM games WHERE id=?", (game_id,))
    if not g:
        raise ValueError(f"no game {game_id}")
    t1, t2 = g[0]["team1_id"], g[0]["team2_id"]
    hp, ap = score_from_events(game_id) or (0, 0)
    p1, p2 = live_possessions(game_id, t1, t2)
    qs = quarter_scores(game_id, t1, t2)
    events = query(
        "SELECT * FROM game_events WHERE game_id=? ORDER BY id DESC LIMIT ?",
        (game_id, n_events))
    # Tonight's tag coverage — % of taggable events carrying the optional
    # one-tap tags (play_type on shots; defense on shots + turnovers, the two
    # event kinds that hold it). One aggregate COUNT; the PWA renders it as a
    # live nudge toward detailed mode (definitions mirror helpers/coverage.py).
    c = query(
        """SELECT
             SUM(CASE WHEN event_type='shot' THEN 1 ELSE 0 END) AS shots,
             SUM(CASE WHEN event_type='shot'
                       AND COALESCE(play_type,'') != '' THEN 1 ELSE 0 END) AS pt,
             SUM(CASE WHEN event_type IN ('shot','turnover')
                      THEN 1 ELSE 0 END) AS st,
             SUM(CASE WHEN event_type IN ('shot','turnover')
                       AND COALESCE(defense,'') != '' THEN 1 ELSE 0 END) AS df
           FROM game_events WHERE game_id=?""", (game_id,))[0]
    _shots, _st = c["shots"] or 0, c["st"] or 0
    coverage = {
        "play_type": {"tagged": c["pt"] or 0, "total": _shots,
                      "pct": round(100 * (c["pt"] or 0) / _shots) if _shots else None},
        "defense": {"tagged": c["df"] or 0, "total": _st,
                    "pct": round(100 * (c["df"] or 0) / _st) if _st else None},
    }
    return {
        "home_pts": hp, "away_pts": ap,
        "home_poss": p1, "away_poss": p2,
        "quarters": {str(q): {"home": d.get(t1, 0), "away": d.get(t2, 0)}
                     for q, d in qs.items()},
        "events": events,
        "coverage": coverage,
    }


# ── Per-scope cache invalidation (batch #6a) ──────────────────────────────────
# The global data_version below still moves on every write (public_feed's live
# payload and settings_utils' per-session memo both key on it). But clearing the
# EXPENSIVE dashboard cache (st.cache_data) is now scoped: a live-game write only
# invalidates its own (gender, season) pool, so one team's Friday game no longer
# cold-busts every other coach's warm cache. Read side: helpers/ui.py page_chrome.
DATA_SCOPE_ALL = "dv::*"          # always-relevant: every session clears on it


def _canon_season(season) -> str:
    """Canonicalize a season the SAME way the season-scoped engines do
    (helpers/seasons.game_pool et al.: the ACTIVE sentinel for the current
    season, else the stripped label) so a write-side scope key and the read-side
    declared scope rendezvous instead of silently missing (a miss = stale data)."""
    import helpers.seasons as SEAS
    return SEAS.ACTIVE if SEAS.is_current(season) else str(season).strip()


def data_scope_key(gender, season) -> str:
    """The app_settings counter key for one (gender, season) analytics pool.
    A missing gender collapses to the always-relevant ALL scope (safe over-clear
    rather than a bad narrow key)."""
    if not gender:
        return DATA_SCOPE_ALL
    return f"dv::{gender}::{_canon_season(season)}"


def _game_scope_key(game_id) -> str:
    """Resolve the (gender, season) scope a game belongs to. Gender comes from
    team1 (both teams share a gender in this app); season is the game's own
    column. Falls back to the ALL scope if the game can't be resolved."""
    row = query("SELECT t.gender AS gender, g.season AS season "
                "FROM games g JOIN teams t ON t.id = g.team1_id "
                "WHERE g.id = ?", (game_id,))
    if not row:
        return DATA_SCOPE_ALL
    return data_scope_key(row[0]["gender"], row[0]["season"])


def cache_clear_decision(current_scopes: dict, seen: dict, my_scopes) -> bool:
    """Pure gate: should this session clear its st.cache_data now?

    current_scopes / seen — {scope_key: version} now vs when this session last
    looked. my_scopes — the scopes this session declared it is viewing (a set),
    or None when it hasn't declared one yet.

    A scope that moved and that this session cares about (or the ALL scope, or
    ANY move when the session hasn't declared a scope) forces a clear. A move to
    a scope the session isn't viewing is ignored — that is the warmth win. The
    ONLY unsafe direction is missing a clear, so an undeclared session and the
    ALL scope both fall back to clearing."""
    moved = {s for s, v in current_scopes.items() if seen.get(s) != v}
    if not moved:
        return False
    if my_scopes is None:
        return True
    if DATA_SCOPE_ALL in moved:
        return True
    return bool(moved & set(my_scopes))


def bump_data_version(game_id=None, scope=None):
    """Signal that data changed OUTSIDE the Streamlit process (mobile tracker
    API). page_chrome() in helpers/ui.py watches these counters and clears
    st.cache_data when a scope the session cares about moves, so phone writes
    reach the dashboards without waiting out cache TTLs. Called on
    finish/undo/edits/creates — not per logged event, mirroring when the
    Streamlit pages call cache_data.clear().

    Pass ``game_id`` (or an explicit ``scope`` key) to invalidate only that
    game's (gender, season) analytics pool; with neither, the write is treated
    as global (roster/officials/rollover) and bumps the ALL scope so every
    session refreshes. The global ``data_version`` always moves too — it drives
    public_feed's live payload and the cheap settings memo, not the expensive
    dashboard clear."""
    execute("""INSERT INTO app_settings (key, value) VALUES ('data_version', '1')
               ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1""")
    key = scope or (_game_scope_key(game_id) if game_id is not None
                    else DATA_SCOPE_ALL)
    execute("""INSERT INTO app_settings (key, value) VALUES (?, '1')
               ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1""",
            (key,))


def finish_game(game_id: int) -> tuple:
    """Freeze the final score from the event stream and mark the game tracked."""
    hp, ap = score_from_events(game_id) or (0, 0)
    execute("UPDATE games SET tracked=1, home_score=?, away_score=? WHERE id=?",
            (hp, ap, game_id))
    # Denormalize the pooled flag from the logging coach's Co-op toggle so the
    # read-path (entitlement.pooled_game_ids) sees it without a join. Recomputed
    # here in case tracked_by was already stamped; the tracker API refreshes again
    # after it stamps attribution on the finish call.
    from helpers.entitlement import recompute_game_pool
    recompute_game_pool(game_id)
    # The desktop tracker's persisted on-court five is dead weight once the
    # game is final — drop it so app_settings doesn't accumulate one row per
    # game forever.
    execute("DELETE FROM app_settings WHERE key=?", (f"gt_floor_{game_id}",))
    return hp, ap


def reopen_game(game_id: int) -> None:
    """Un-finalize a game after an accidental End Game: tracked=0 and the
    frozen score cleared, so live logging can resume. The next finish_game()
    re-freezes the score from the event stream — a manually corrected final
    score does NOT survive a reopen/finish cycle."""
    execute("UPDATE games SET tracked=0, home_score=NULL, away_score=NULL "
            "WHERE id=?", (game_id,))
