"""
gameflow.py — possession-sequenced "game flow" analytics: the classic coach
scoring buckets and on-court rotation, derived from the existing event stream.

Two things coaches always ask for that the box score alone can't answer:

  • Scoring buckets — points in the paint, second-chance points (after an
    offensive rebound), points off turnovers, fast-break / transition points,
    and bench points. All derived by walking the possession-ending events
    (shots + turnovers) in chronological order — no new tracking required.

  • Rotation — who was on the floor when, reconstructed by diffing the 10-man
    `game_event_lineup` snapshot between consecutive events, with stint segments
    and elapsed-clock minutes (more complete than the possession_secs estimate,
    which misses untimed events).

Locked possession rule (matches the rest of the app): a possession ends on a
SHOT or a TURNOVER; free throws and fouls never end one. Scoring-bucket points
are FIELD-GOAL points (2s/3s); bench points use full player points (incl. FTs),
the conventional definition. Starters are INFERRED as the five on the floor at a
game's first event (no starter flag is tracked) — labelled as such in the UI.

Streamlit-free engine. Reuses stats.fetch_events / player_game_boxes and
team_analytics._player_team_map; no new tracking, no Game-Tracker change.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.team_analytics as TA


# ── elapsed-clock helpers — canonical versions live in helpers.stats ─────────────
_clock_secs = S.clock_secs
_q_len = S.q_len
_q_base = S.q_base


def elapsed(e):
    """Seconds since tip-off for an event row (chronological sort key)."""
    return S.elapsed(e["quarter"], e["time"])


# ── starters (inferred: the five on the floor at the first event) ────────────────
def infer_starters(events_one_game):
    """{team_id: set(player_id)} — the five on the floor at the game's first event.
    No starter flag is tracked, so this is an inference; label it as such."""
    if not events_one_game:
        return {}
    first = min(events_one_game, key=elapsed)
    rows = query(
        "SELECT team_id, player_id FROM game_event_lineup WHERE event_id = ?",
        (first["id"],))
    starters = defaultdict(set)
    for r in rows:
        starters[r["team_id"]].add(r["player_id"])
    return dict(starters)


# ── scoring buckets ──────────────────────────────────────────────────────────────
def _blank_bucket():
    return {"paint": 0, "second_chance": 0, "off_turnover": 0, "fast_break": 0,
            "bench": 0, "fg_pts": 0}


def scoring_buckets(game_ids, events=None):
    """
    Classic scoring breakdown per team, summed over `game_ids` (pass one id for a
    single game, many for a season).

    Returns {team_id: {paint, second_chance, off_turnover, fast_break, bench,
    fg_pts}}. paint/second_chance/off_turnover/fast_break are FIELD-GOAL points;
    bench is total points (incl. FTs) by inferred non-starters; fg_pts is the
    team's total field-goal points (the denominator for shares).
    """
    games = list(game_ids)
    if events is None:
        events = S.fetch_events(games)
    by_game = defaultdict(list)
    for e in events:
        by_game[e["game_id"]].append(e)

    ptmap = TA._player_team_map()
    out = defaultdict(_blank_bucket)

    def _ender_team(e):
        if e["event_type"] == "shot":
            return e["shooter_team_id"]
        return ptmap.get(e["primary_player_id"])   # turnover → committer's team

    for gid in games:
        gev = by_game.get(gid, [])
        if not gev:
            continue
        starters = infer_starters(gev)

        enders = sorted([e for e in gev if e["event_type"] in ("shot", "turnover")],
                        key=elapsed)
        prev = None
        for e in enders:
            if e["event_type"] == "shot":
                team = e["shooter_team_id"]
                if team is not None and e["shot_result"] == "make":
                    pts = 3 if e["shot_type"] == 3 else 2
                    o = out[team]
                    o["fg_pts"] += pts
                    if e["zone"] == "C" and e["shot_type"] != 3:
                        o["paint"] += pts
                    psec = e["possession_secs"] or 0
                    if 0 < psec <= 6:
                        o["fast_break"] += pts
                    if prev is not None:
                        if (prev["event_type"] == "turnover"
                                and _ender_team(prev) != team):
                            o["off_turnover"] += pts
                        elif (prev["event_type"] == "shot"
                              and prev["shot_result"] == "miss"
                              and prev["shooter_team_id"] == team
                              and prev["rebounder_team_id"] == team):
                            o["second_chance"] += pts
            prev = e

        # bench = total points by inferred non-starters (incl. FTs)
        pgb = S.player_game_boxes(game_ids=[gid], events=gev)
        for pid, games_ in pgb.items():
            b = games_.get(gid)
            if not b:
                continue
            team = ptmap.get(pid)
            if team is not None and pid not in starters.get(team, set()):
                out[team]["bench"] += b["PTS"]

    return dict(out)


# ── rotation / stints / minutes ──────────────────────────────────────────────────
def _merge(intervals):
    """Merge touching/overlapping (start, end) intervals."""
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def rotation(game_id, events=None, names=None):
    """
    Reconstruct who was on the floor across one game by diffing the per-event
    10-man `game_event_lineup` snapshot.

    Returns {
      "teams": {team_id: [{player_id, name, number, starter, secs, segments:
                           [(start,end), …]}, … sorted by secs desc]},
      "end": elapsed seconds of the last event, "team_ids": [t1, t2]}.
    Minutes = secs/60. Uses elapsed-clock gaps (covers untimed events, unlike the
    possession_secs minutes estimate).
    """
    if events is None:
        events = S.fetch_events([game_id])
    ordered = sorted(events, key=elapsed)
    if not ordered:
        return {"teams": {}, "end": 0, "team_ids": []}

    floors = defaultdict(lambda: defaultdict(set))   # event_id -> team -> {pid}
    for r in query(
            """SELECT gel.event_id, gel.team_id, gel.player_id
               FROM game_event_lineup gel JOIN game_events ge ON ge.id = gel.event_id
               WHERE ge.game_id = ?""", (game_id,)):
        floors[r["event_id"]][r["team_id"]].add(r["player_id"])

    end = elapsed(ordered[-1])
    segs = defaultdict(lambda: defaultdict(list))    # team -> pid -> [(s,e)]
    for i, e in enumerate(ordered):
        t0 = elapsed(e)
        t1 = elapsed(ordered[i + 1]) if i + 1 < len(ordered) else end
        if t1 <= t0:
            continue
        for team, pids in floors.get(e["id"], {}).items():
            for pid in pids:
                segs[team][pid].append((t0, t1))

    if names is None:
        names = _player_meta()
    starters = infer_starters(events)

    teams = {}
    for team, players in segs.items():
        rows = []
        for pid, ivals in players.items():
            merged = _merge(ivals)
            secs = sum(e - s for s, e in merged)
            meta = names.get(pid, {})
            rows.append({
                "player_id": pid, "name": meta.get("name", f"#{pid}"),
                "number": meta.get("number"), "secs": secs, "segments": merged,
                "starter": pid in starters.get(team, set()),
            })
        rows.sort(key=lambda r: -r["secs"])
        teams[team] = rows

    return {"teams": teams, "end": end, "team_ids": list(teams.keys())}


def _player_meta():
    return {r["id"]: {"name": r["name"], "number": r["number"]}
            for r in query("SELECT id, name, number FROM players")}


def scoring_runs(game_id, events=None, min_run=6):
    """
    Detect scoring runs in one game: stretches where a team scored `min_run`+
    points in a row while the opponent scored none. Returns a list (biggest
    first) of {team_id, points, start, end} in elapsed seconds. Made FTs count.
    """
    if events is None:
        events = S.fetch_events([game_id])
    ptmap = TA._player_team_map()
    scoring = []
    for e in sorted(events, key=elapsed):
        team = pts = None
        if e["event_type"] == "shot" and e["shot_result"] == "make":
            team = e["shooter_team_id"]
            pts = 3 if e["shot_type"] == 3 else 2
        elif e["event_type"] == "free_throw" and e["shot_result"] == "make":
            team = ptmap.get(e["primary_player_id"])
            pts = 1
        if team is not None and pts:
            scoring.append((elapsed(e), team, pts))

    runs = []
    cur_team = None
    cur_pts = start = last = 0
    for t, team, pts in scoring:
        if team == cur_team:
            cur_pts += pts
            last = t
        else:
            if cur_team is not None and cur_pts:
                runs.append({"team_id": cur_team, "points": cur_pts,
                             "start": start, "end": last})
            cur_team, cur_pts, start, last = team, pts, t, t
    if cur_team is not None and cur_pts:
        runs.append({"team_id": cur_team, "points": cur_pts,
                     "start": start, "end": last})
    runs = [r for r in runs if r["points"] >= min_run]
    runs.sort(key=lambda r: -r["points"])
    return runs
