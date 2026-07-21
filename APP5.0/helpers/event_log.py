"""
event_log.py — read & repair the play-by-play event stream of a game.

The Game Tracker can only DELETE the last event during live logging. This is the
after-the-fact corrections layer: fix a mis-tagged shooter / zone / result / type,
or delete a bogus event, for ANY game that has events. Edits keep the derived
data consistent:

  * game_event_lineup (who was on the floor for each event) is UNCHANGED by a
    field edit and is cascade-deleted with an event — so on/off, RAPM and lineup
    ratings stay valid without re-snapshotting.
  * +/- in game_lineup_players is adjusted whenever an edit or delete changes a
    made basket's points or its scoring team (mirrors the Game Tracker's own
    +/- logic, so the stored +/- never drifts).
  * recompute_final_score() re-freezes games.home/away_score from the events, so
    records & rankings line up with the corrected log.

Pure data layer: database.db + court_geom (math only), no streamlit.
"""
from __future__ import annotations

from database.db import query, execute
import helpers.court_geom as CG

ZONES = ("LC", "LW", "C", "RW", "RC")
EVENT_TYPES = ("shot", "free_throw", "foul", "turnover")

# Fields kept per event_type; everything else is nulled on save so a type change
# can't leave stale columns (a turnover keeping a zone, a foul keeping a result).
_FIELDS_BY_TYPE = {
    "shot": ("primary_player_id", "shot_type", "shot_result", "zone",
             "pass_from_id", "shot_created_by_id", "rebound_by_id",
             "blocked_by_id", "guarded_by_id", "play_type", "defense"),
    "free_throw": ("primary_player_id", "shot_result", "rebound_by_id"),
    # defense (the scheme in effect) AND play_type (the offense's set call) are
    # captured on fouls + turnovers too, not just shots — a press forces both,
    # and a PnR can end in a strip or a drawn foul — so both survive a retype.
    "foul": ("primary_player_id", "secondary_player_id", "official_id",
             "play_type", "defense"),
    "turnover": ("primary_player_id", "stolen_by_id", "play_type", "defense",
                 "turnover_type"),
}

# Every nullable column the editor manages (written on each update).
_ALL_FIELDS = ("primary_player_id", "shot_type", "shot_result", "zone",
               "pass_from_id", "shot_created_by_id", "rebound_by_id",
               "blocked_by_id", "guarded_by_id", "secondary_player_id",
               "stolen_by_id", "official_id", "play_type", "defense",
               "turnover_type")
# Text columns among _ALL_FIELDS; the rest are integer ids / shot_type.
_STR_FIELDS = ("shot_result", "zone", "play_type", "defense", "turnover_type")


# ── people / labels ─────────────────────────────────────────────────────────────
def _abbr(name):
    """'Adair Girls' -> 'AG'."""
    return "".join(w[0].upper() for w in str(name).split() if w)


def game_people(game_id):
    """Resolve the two teams' players + officials for a game.

    Returns dict with:
      players   [{id, name, number, team_id, label}]  (the GAME'S SEASON roster,
                plus any player its events already reference — so a rolled-over
                team doesn't show two of everyone)
      officials [{id, name}]
      pid2label, label2pid, oid2name, name2oid, pid2team
    Labels are 'ABBR #num Name', de-duplicated with an [id] suffix if needed.

    SEASON SCOPING: after a New-Season rollover a returning player has BOTH an
    archived row (stamped with last season's label) AND a fresh Current row —
    both on the same team_id. An unscoped `team_id IN (?,?)` therefore listed
    every returner twice (once suffixed [id]). The picker now shows the roster
    of the GAME'S OWN season (SEAS.roster_clause) — the rows the game's events
    actually point at — then UNIONs any event-referenced pid outside it (a
    transfer, a manual cross-season correction) so every reference resolves.
    """
    import helpers.seasons as SEAS
    g = query("""SELECT g.team1_id, g.team2_id, g.season, t1.name n1, t2.name n2
                 FROM games g JOIN teams t1 ON t1.id=g.team1_id
                              JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?""",
              (game_id,))
    empty = {"players": [], "officials": [], "pid2label": {}, "label2pid": {},
             "oid2name": {}, "name2oid": {}, "pid2team": {}}
    if not g:
        return empty
    g = g[0]
    abbr = {g["team1_id"]: _abbr(g["n1"]), g["team2_id"]: _abbr(g["n2"])}
    # roster for THIS game's season (current → archived=0; a past label → that
    # season's snapshot rows).
    _rclause, _rparams = SEAS.roster_clause(g["season"], alias="p")
    rows = query(f"""SELECT p.id, p.name, p.number, p.team_id FROM players p
                     WHERE p.team_id IN (?,?) AND {_rclause}
                     ORDER BY p.team_id, p.number, p.name""",
                 (g["team1_id"], g["team2_id"], *_rparams))
    # any pid the game's events already reference but that the season roster
    # missed (defensive — keeps every historical edit resolvable).
    _seen = {r["id"] for r in rows}
    _cols = ("primary_player_id", "secondary_player_id", "rebound_by_id",
             "pass_from_id", "shot_created_by_id", "blocked_by_id",
             "guarded_by_id", "stolen_by_id")
    _refd = set()
    for c in _cols:
        for r in query(f"SELECT DISTINCT {c} pid FROM game_events "
                       f"WHERE game_id=? AND {c} IS NOT NULL", (game_id,)):
            _refd.add(r["pid"])
    _extra = _refd - _seen
    if _extra:
        ph = ",".join("?" * len(_extra))
        rows = list(rows) + query(
            f"SELECT id, name, number, team_id FROM players WHERE id IN ({ph}) "
            f"ORDER BY team_id, number, name", tuple(_extra))
    pid2label, label2pid, pid2team, players = {}, {}, {}, []
    for r in rows:
        lbl = f"{abbr.get(r['team_id'], '')} #{r['number']} {r['name']}".strip()
        if lbl in label2pid:
            lbl = f"{lbl} [{r['id']}]"
        pid2label[r["id"]] = lbl
        label2pid[lbl] = r["id"]
        pid2team[r["id"]] = r["team_id"]
        players.append({**r, "label": lbl})
    offs = query("SELECT id, name FROM officials ORDER BY name")
    return {
        "players": players, "officials": offs,
        "pid2label": pid2label, "label2pid": label2pid,
        "oid2name": {o["id"]: o["name"] for o in offs},
        "name2oid": {o["name"]: o["id"] for o in offs},
        "pid2team": pid2team,
    }


# ── load ────────────────────────────────────────────────────────────────────────
def games_with_events():
    """[{id, date, n1, n2, t1_id, t2_id, tracked, season, in_pool, n_events}] for
    every game that has events, most recent first — the games the editor can open."""
    return query("""
        SELECT g.id, g.date, t1.name n1, t2.name n2,
               g.team1_id t1_id, g.team2_id t2_id, g.tracked, g.season, g.in_pool,
               COUNT(ge.id) n_events
        FROM games g
        JOIN teams t1 ON t1.id=g.team1_id
        JOIN teams t2 ON t2.id=g.team2_id
        JOIN game_events ge ON ge.game_id=g.id
        GROUP BY g.id
        ORDER BY g.date DESC, g.id DESC""")


def load_events(game_id, quarter=None):
    """Raw event rows for a game (optionally one quarter), in log order."""
    if quarter:
        return query(
            "SELECT * FROM game_events WHERE game_id=? AND quarter=? ORDER BY id",
            (game_id, quarter))
    return query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (game_id,))


def quarters_in_game(game_id):
    return [r["quarter"] for r in query(
        "SELECT DISTINCT quarter FROM game_events WHERE game_id=? ORDER BY quarter",
        (game_id,))]


# ── scoring / +- bookkeeping ─────────────────────────────────────────────────────
def event_points(ev):
    """Points an event put on the board (0 unless a made shot / free throw)."""
    if ev.get("shot_result") != "make":
        return 0
    if ev.get("event_type") == "shot":
        return 3 if ev.get("shot_type") == 3 else 2
    if ev.get("event_type") == "free_throw":
        return 1
    return 0


def _pm_contrib(pts, scoring_tid, team_id):
    if not pts or scoring_tid is None:
        return 0
    return pts if team_id == scoring_tid else -pts


def _apply_pm_delta(game_id, event_id, old_pts, old_stid, new_pts, new_stid):
    """Shift game_lineup_players.plus_minus for the floor of one event when its
    scoring (points or scoring team) changed old -> new."""
    if (old_pts, old_stid) == (new_pts, new_stid):
        return
    floor = query(
        "SELECT player_id, team_id FROM game_event_lineup WHERE event_id=?",
        (event_id,))
    for r in floor:
        delta = (_pm_contrib(new_pts, new_stid, r["team_id"])
                 - _pm_contrib(old_pts, old_stid, r["team_id"]))
        if delta:
            execute("UPDATE game_lineup_players SET plus_minus = plus_minus + ? "
                    "WHERE game_id=? AND player_id=?",
                    (delta, game_id, r["player_id"]))


# ── mutate ───────────────────────────────────────────────────────────────────────
def _resolved(ev):
    """Type-cleaned field values of an existing event (irrelevant cols -> None)."""
    keep = set(_FIELDS_BY_TYPE.get(ev["event_type"], ()))
    return {f: (ev[f] if f in keep else None) for f in _ALL_FIELDS}


def event_changed(ev, vals):
    """True if `vals` differs from the stored event `ev` (so we only write edits)."""
    etype = vals.get("event_type") or ev["event_type"]
    if etype != ev["event_type"]:
        return True
    if str(vals.get("time") or ev["time"]) != str(ev["time"]):
        return True
    if int(vals.get("quarter") or ev["quarter"]) != int(ev["quarter"]):
        return True
    keep = set(_FIELDS_BY_TYPE[etype])
    for f in _ALL_FIELDS:
        nv = vals.get(f) if f in keep else None
        ov = ev[f]
        if f not in _STR_FIELDS:           # integer id / shot_type columns
            nv = int(nv) if nv is not None else None
            ov = int(ov) if ov is not None else None
        if (nv if nv is not None else None) != (ov if ov is not None else None):
            return True
    return False


def update_event(game_id, ev_id, vals, pid2team):
    """Write one corrected event. `vals` holds event_type + the managed fields
    (player/official ids already resolved, None where blank). Nulls fields the
    final type doesn't use, fixes +/- if the scoring changed, then UPDATEs."""
    old = query("SELECT * FROM game_events WHERE id=?", (ev_id,))
    if not old:
        return
    old = old[0]
    etype = vals.get("event_type")
    if etype not in EVENT_TYPES:
        etype = old["event_type"]
    keep = set(_FIELDS_BY_TYPE[etype])
    clean = {f: (vals.get(f) if f in keep else None) for f in _ALL_FIELDS}
    if etype != "shot":
        clean["shot_type"] = None
    clean = {f: (int(v) if v is not None and f not in _STR_FIELDS
                 else v) for f, v in clean.items()}

    # +/- adjustment from old scoring -> new scoring over this event's floor
    old_pts = event_points(old)
    new_pts = event_points({"event_type": etype,
                            "shot_result": clean["shot_result"],
                            "shot_type": clean["shot_type"]})
    _apply_pm_delta(game_id, ev_id, old_pts,
                    pid2team.get(old["primary_player_id"]),
                    new_pts, pid2team.get(clean["primary_player_id"]))

    # shot_x/shot_y aren't editor-managed fields, but they must not survive a
    # type change: a stale tap location on a row later flipped back to "shot"
    # would resurrect on every shot chart and override the user's zone/2-3.
    execute(
        "UPDATE game_events SET event_type=?, quarter=?, time=?, "
        + ", ".join(f"{f}=?" for f in _ALL_FIELDS)
        + (", shot_x=NULL, shot_y=NULL" if etype != "shot" else "")
        + " WHERE id=?",
        (etype, int(vals.get("quarter") or old["quarter"]),
         str(vals.get("time") or old["time"]),
         *[clean[f] for f in _ALL_FIELDS], ev_id))


# event types that carry a `defense` tag (the scheme in effect). FTs don't.
_DEFENSE_EVENT_TYPES = ("shot", "turnover", "foul")


def bulk_set_defense(game_id, defense, only_blank=True, primary_team_id=None):
    """Tag every defense-eligible event (shot / turnover / foul) in a game with
    ``defense`` in one write — the Event Editor's "fill the whole game as X, then
    tweak the exceptions" button. For coaches who play one or two defenses, this
    backfills a season's worth of possessions without per-event entry.

    only_blank=True (the safe default) touches only the UNtagged events, so a
    re-run never clobbers tweaks already made; False overwrites every eligible
    event. ``defense=None`` clears the tag. Free throws never carry defense and
    are excluded.

    primary_team_id scopes to events whose PRIMARY player is on that team — i.e.
    that team's possessions. Since the defense tag is the DEFENDING (other) team's
    scheme, this lets each side's possessions take a different scheme in one pass
    (a man team facing a zone team tags both correctly). None = the whole game.

    Defense is independent of scoring / lineups / +/-, so this is a plain targeted
    UPDATE (no per-event rewrite). Returns the number of events updated."""
    types = ",".join("?" for _ in _DEFENSE_EVENT_TYPES)
    where = f"game_id=? AND event_type IN ({types})"
    params = [game_id, *_DEFENSE_EVENT_TYPES]
    if only_blank:
        where += " AND defense IS NULL"
    if primary_team_id is not None:
        where += " AND primary_player_id IN (SELECT id FROM players WHERE team_id=?)"
        params.append(primary_team_id)
    params = tuple(params)
    n = query(f"SELECT COUNT(*) AS c FROM game_events WHERE {where}", params)[0]["c"]
    if n:
        execute(f"UPDATE game_events SET defense=? WHERE {where}", (defense, *params))
    return n


def bulk_retag(event_ids, field, value):
    """Set ONE tag column to ``value`` across many events in a single write —
    the Event Editor's multi-row re-tag (fix a whole stretch tagged with the
    wrong set call / scheme / TO kind at once).

    ``field`` ∈ {play_type, defense, turnover_type}; ``value`` must be a
    canonical key for that field (helpers/playtypes.NAMED_PLAY_TYPES /
    defenses.DEFENSES / turnovers.TURNOVER_TYPES), or None to clear. The
    UPDATE is scoped to the event types that legitimately carry the tag
    (_FIELDS_BY_TYPE), so a stray foul id in a turnover_type pass is skipped,
    not corrupted. Tags are independent of scoring / lineups / +/-, so this is
    a plain batched UPDATE (the db audit hook logs it). Returns rows updated.
    """
    import helpers.playtypes as PT
    import helpers.defenses as DEF
    import helpers.turnovers as TOV
    canon = {
        "play_type": {k for k, _ in PT.NAMED_PLAY_TYPES},
        "defense": {k for k, _lbl, _fam in DEF.DEFENSES},
        "turnover_type": {k for k, _ in TOV.TURNOVER_TYPES},
    }
    if field not in canon:
        raise ValueError(f"bulk_retag: field must be one of {sorted(canon)}")
    if value is not None and value not in canon[field]:
        raise ValueError(f"bulk_retag: {value!r} is not a canonical {field}")
    ids = [int(i) for i in (event_ids or [])]
    if not ids:
        return 0
    eligible = tuple(t for t, cols in _FIELDS_BY_TYPE.items() if field in cols)
    types = ",".join("?" for _ in eligible)
    from database.db import executemany
    return executemany(
        f"UPDATE game_events SET {field}=? "
        f"WHERE id=? AND event_type IN ({types})",
        [(value, i, *eligible) for i in ids])


def insert_missed_event(game_id, ev):
    """Insert an after-the-fact event (the basket the scorekeeper missed).

    Runs the NORMAL live write path (game_events.log_event → snapshot, +/-,
    x/y→zone) with the floor cloned from the temporally adjacent event, then
    repairs the clock bookkeeping that an out-of-order insert breaks:
      * the new event's possession_secs is computed against its CHRONO
        predecessor (log_event uses insertion order, which is wrong here);
      * the chrono successor's possession_secs is re-split, so per-player
        minutes don't double-count the elapsed time around the insert.
    Returns (event_id, n_floor_players) — n_floor_players 0 means no adjacent
    event existed to clone a lineup from (first event of the game)."""
    import helpers.game_events as GE

    q = int(ev.get("quarter") or 1)
    tsec = GE.time_to_secs(str(ev.get("time") or "0:00"))
    knew = (q, -tsec)

    prev_ev = next_ev = None
    for e in query("SELECT id, quarter, time FROM game_events WHERE game_id=?",
                   (game_id,)):
        k = (e["quarter"], -GE.time_to_secs(e["time"]))
        if k <= knew and (prev_ev is None
                          or k > (prev_ev["quarter"],
                                  -GE.time_to_secs(prev_ev["time"]))):
            prev_ev = e
        if k > knew and (next_ev is None
                         or k < (next_ev["quarter"],
                                 -GE.time_to_secs(next_ev["time"]))):
            next_ev = e

    adjacent = prev_ev or next_ev
    on_court = []
    if adjacent:
        on_court = [(r["player_id"], r["team_id"]) for r in query(
            "SELECT player_id, team_id FROM game_event_lineup WHERE event_id=?",
            (adjacent["id"],))]
    offs = [r["official_id"] for r in query(
        "SELECT official_id FROM game_lineup_officials WHERE game_id=?",
        (game_id,))]

    eid = GE.log_event(game_id, ev, on_court, offs)

    start = (GE.time_to_secs(prev_ev["time"])
             if prev_ev and prev_ev["quarter"] == q
             else GE.quarter_start_secs(q))
    execute("UPDATE game_events SET possession_secs=? WHERE id=?",
            (max(0.0, start - tsec), eid))
    if next_ev and next_ev["quarter"] == q:
        execute("UPDATE game_events SET possession_secs=? WHERE id=?",
                (max(0.0, tsec - GE.time_to_secs(next_ev["time"])),
                 next_ev["id"]))
    return eid, len(on_court)


def set_shot_location(game_id, ev_id, x, y, pid2team):
    """Move a shot's tap-captured location (the mistap fixer). The x/y court-feet
    are the source of truth for WHERE: zone and 2/3 are re-derived from them —
    the same rule log_event applies — and +/- shifts when a made shot's value
    flips 2<->3. Returns the (zone, shot_type) now stored, or None if the event
    isn't a shot. Callers handle score drift the same way as other edits
    (recompute_final_score / the editor's drift banner)."""
    old = query("SELECT * FROM game_events WHERE id=? AND game_id=?",
                (ev_id, game_id))
    if not old or old[0]["event_type"] != "shot":
        return None
    old = old[0]
    zone = CG.zone_from_xy(x, y)
    val = CG.shot_value(x, y)
    stid = pid2team.get(old["primary_player_id"])
    old_pts = event_points(old)
    new_pts = event_points({"event_type": "shot",
                            "shot_result": old["shot_result"],
                            "shot_type": val})
    _apply_pm_delta(game_id, ev_id, old_pts, stid, new_pts, stid)
    execute("UPDATE game_events SET shot_x=?, shot_y=?, zone=?, shot_type=? "
            "WHERE id=?", (float(x), float(y), zone, val, ev_id))
    return zone, val


def delete_event(game_id, ev_id, pid2team):
    """Delete an event, first reversing its +/- contribution. The FK cascade
    clears its game_event_lineup snapshot."""
    old = query("SELECT * FROM game_events WHERE id=?", (ev_id,))
    if not old:
        return
    old = old[0]
    _apply_pm_delta(game_id, ev_id, event_points(old),
                    pid2team.get(old["primary_player_id"]), 0, None)
    execute("DELETE FROM game_events WHERE id=?", (ev_id,))


def score_from_events(game_id):
    """(home_pts, away_pts) computed from the event stream (team1 = home).
    Read-only — the authoritative live-score logic, reused for previews."""
    g = query("SELECT team1_id, team2_id FROM games WHERE id=?", (game_id,))
    if not g:
        return None
    t1, t2 = g[0]["team1_id"], g[0]["team2_id"]
    rows = query("""
        SELECT p.team_id,
               SUM(CASE WHEN ge.event_type='shot'       AND ge.shot_result='make'
                            THEN ge.shot_type
                        WHEN ge.event_type='free_throw'  AND ge.shot_result='make'
                            THEN 1 ELSE 0 END) pts
        FROM game_events ge JOIN players p ON p.id=ge.primary_player_id
        WHERE ge.game_id=? AND ge.shot_result='make'
        GROUP BY p.team_id""", (game_id,))
    pts = {r["team_id"]: (r["pts"] or 0) for r in rows}
    return pts.get(t1, 0), pts.get(t2, 0)


def recompute_final_score(game_id):
    """Re-freeze games.home_score/away_score from the events. Returns (h, a)."""
    hp_ap = score_from_events(game_id)
    if hp_ap is None:
        return None
    execute("UPDATE games SET home_score=?, away_score=? WHERE id=?",
            (hp_ap[0], hp_ap[1], game_id))
    return hp_ap


# ── on-court-five correction (batch #2) ───────────────────────────────────────
def recompute_game_plus_minus(game_id):
    """Rebuild game_lineup_players.plus_minus for a game FROM SCRATCH off the
    current game_event_lineup snapshots — the single source of truth after any
    lineup mutation, avoiding fragile incremental delta bookkeeping. For each
    scoring event the scoring team is the scorer's own on-floor team; every
    on-floor player gets +pts (same team) or -pts (opponent). Verified to
    reproduce the live incremental credit exactly (tracker/test_retro_floor)."""
    # Every player that appears on any floor must have a row to accumulate into.
    execute("INSERT OR IGNORE INTO game_lineup_players (game_id, team_id, player_id) "
            "SELECT ge.game_id, gel.team_id, gel.player_id "
            "FROM game_event_lineup gel JOIN game_events ge ON ge.id = gel.event_id "
            "WHERE ge.game_id = ?", (game_id,))
    execute("UPDATE game_lineup_players SET plus_minus = 0 WHERE game_id = ?", (game_id,))
    evs = query("SELECT id, event_type, shot_result, shot_type, primary_player_id "
                "FROM game_events WHERE game_id = ? ORDER BY id", (game_id,))
    for ev in evs:
        pts = event_points(ev)
        if not pts:
            continue
        # scoring team = the scorer's team on that event's floor (fall back to
        # the roster team if the scorer somehow isn't in their own snapshot).
        strow = query("SELECT team_id FROM game_event_lineup "
                      "WHERE event_id=? AND player_id=?",
                      (ev["id"], ev["primary_player_id"]))
        if strow:
            stid = strow[0]["team_id"]
        else:
            prow = query("SELECT team_id FROM players WHERE id=?",
                         (ev["primary_player_id"],))
            if not prow:
                continue
            stid = prow[0]["team_id"]
        for r in query("SELECT player_id, team_id FROM game_event_lineup WHERE event_id=?",
                       (ev["id"],)):
            delta = pts if r["team_id"] == stid else -pts
            execute("UPDATE game_lineup_players SET plus_minus = plus_minus + ? "
                    "WHERE game_id=? AND player_id=?",
                    (delta, game_id, r["player_id"]))


def _team_floor(event_id, team_id):
    """The set of player ids snapshotted on the floor for one team at one event."""
    return frozenset(r["player_id"] for r in query(
        "SELECT player_id FROM game_event_lineup WHERE event_id=? AND team_id=?",
        (event_id, team_id)))


def floor_run(game_id, from_event_id, team_id):
    """The contiguous run of event ids (log order) starting at ``from_event_id``
    over which ``team_id`` carries the SAME floor it has at the anchor — i.e. the
    stale stretch a missed sub affects, ending where the five next changes in the
    log (or at the game's last event). Empty if the anchor has no floor for the
    team. Used both to preview the range in the editor and to apply the fix."""
    S0 = _team_floor(from_event_id, team_id)
    if not S0:
        return []
    run = []
    for e in query("SELECT id FROM game_events WHERE game_id=? AND id>=? ORDER BY id",
                   (game_id, from_event_id)):
        if _team_floor(e["id"], team_id) != S0:
            break
        run.append(e["id"])
    return run


def correct_floor_forward(game_id, from_event_id, team_id, new_pids):
    """Correct one team's on-court five from ``from_event_id`` forward across the
    contiguous run of events that share that team's stale floor (the stretch
    after a missed sub, ending where the five next changes in the log or at the
    game's last event), then recompute the game's +/-.

    ``new_pids`` is deduped and validated against the team's roster. Returns a
    summary dict {events_changed, size, range, old_five, new_five} for the
    editor's confirmation. Raises ValueError on an off-roster player or an
    anchor event that has no floor for the team."""
    deduped = []
    for p in new_pids:
        if p not in deduped:
            deduped.append(p)
    valid = {r["id"] for r in query("SELECT id FROM players WHERE team_id=?", (team_id,))}
    bad = [p for p in deduped if p not in valid]
    if bad:
        raise ValueError(f"players {bad} are not on team {team_id}'s roster")

    S0 = _team_floor(from_event_id, team_id)
    if not S0:
        raise ValueError(f"event {from_event_id} has no floor for team {team_id}")

    run = floor_run(game_id, from_event_id, team_id)

    for eid in run:
        execute("DELETE FROM game_event_lineup WHERE event_id=? AND team_id=?",
                (eid, team_id))
        for pid in deduped:
            execute("INSERT OR IGNORE INTO game_event_lineup (event_id, player_id, team_id) "
                    "VALUES (?,?,?)", (eid, pid, team_id))
            execute("INSERT OR IGNORE INTO game_lineup_players (game_id, team_id, player_id) "
                    "VALUES (?,?,?)", (game_id, team_id, pid))

    recompute_game_plus_minus(game_id)
    return {"events_changed": run, "size": len(run),
            "range": (run[0], run[-1]) if run else None,
            "old_five": sorted(S0), "new_five": sorted(deduped)}


def floor_integrity(game_id):
    """Events whose on-floor snapshot for a team is not exactly 5 players — a
    dedupe failure (6+), an under-pick (<5), or an unsnapshotted gap. The
    discovery aid for IMPROVEMENTS #5 ('warn when the lineup is not exactly 5').
    Returns [{event_id, team_id, n, quarter, time}] in event order. (A clean
    5-for-5 missed sub is NOT flagged here — that is found by the coach and
    fixed via correct_floor_forward.)"""
    return [dict(r) for r in query("""
        SELECT gel.event_id AS event_id, gel.team_id AS team_id, COUNT(*) AS n,
               ge.quarter AS quarter, ge.time AS time
        FROM game_event_lineup gel JOIN game_events ge ON ge.id = gel.event_id
        WHERE ge.game_id = ?
        GROUP BY gel.event_id, gel.team_id
        HAVING n != 5
        ORDER BY ge.id""", (game_id,))]
