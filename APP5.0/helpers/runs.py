"""
runs.py — scoring-run detection + the team/league run profiles.

The tracker already knows about runs in the moment (courtside.run_alert) and the
situational engine tags "on a run" possessions, but nothing SHOWED the run data:
how many 10-0 runs a team lands per game, how many it gives up, whether games
with 1 / 2 / 3+ runs actually get won, how long runs take, and whether the
momentum carries after the run ends. This module is that engine.

Definitions
  run          >= RUN_MIN (6) unanswered points by one team; BIG_RUN (10) is the
               headline "10-0 run" everywhere a single number is shown.
  length       game-clock seconds from the run's first to last made basket —
               a 25-second 10-0 flurry reads very differently from a 4-minute
               squeeze built on defensive stops (the founder's "killer defensive
               stop" read: long runs ARE strings of stops).
  momentum     net points (run owner's perspective) in the MOMENTUM_WINDOW of
               game clock after the run's last basket — did the surge carry, or
               did the opponent answer right back?
  garbage      a run that STARTS in the 4th quarter with the margin already
               >= GARBAGE_MARGIN is bench-vs-bench noise; it is detected but
               kept OUT of every headline count (the founder's GEI concern —
               a run only matters when the game is live).

Streamlit-free (sqlite + pure walks). Display: Rankings League Lab "Runs" tab +
the Team Dashboard Situational tab's runs section.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.situational as SIT

RUN_MIN = 6              # unanswered points = a run (mirrors situational.RUN_PTS)
BIG_RUN = 10             # the "10-0 run" headline threshold
GARBAGE_MARGIN = 20      # 4th-quarter margin that marks a run as garbage time
MOMENTUM_WINDOW = 120.0  # seconds of game clock the "did it carry" read covers


def _scoring_list(events):
    """{game_id: [(elapsed, team_id, pts), ...]} chronological scoring plays."""
    out = defaultdict(list)
    for e in events:
        pts, scorer = SIT._event_points(e)
        if pts and scorer is not None and e.get("game_id") is not None:
            out[e["game_id"]].append((SIT._elapsed(e), scorer,
                                      int(e.get("quarter") or 1), pts))
    for gid in out:
        out[gid].sort(key=lambda t: t[0])
    return out


def detect_runs(events, min_run=RUN_MIN):
    """Every >= min_run-0 scoring run in the events, one dict per run:
    {game_id, team_id, points, secs, q_start, q_end, margin_before (owner's
    perspective at the run's first basket), momentum (net pts in the
    MOMENTUM_WINDOW after the run ends, owner's perspective), garbage}."""
    runs = []
    for gid, plays in _scoring_list(events).items():
        score = defaultdict(int)
        streak = None          # {team, pts, t0, q0, t_last, q_last, margin0}
        game_runs = []

        def _flush():
            if streak and streak["pts"] >= min_run:
                game_runs.append({
                    "game_id": gid, "team_id": streak["team"],
                    "points": streak["pts"],
                    "secs": max(0.0, streak["t_last"] - streak["t0"]),
                    "t_end": streak["t_last"],
                    "q_start": streak["q0"], "q_end": streak["q_last"],
                    "margin_before": streak["margin0"],
                    "garbage": (streak["q0"] >= 4
                                and abs(streak["margin0"]) >= GARBAGE_MARGIN),
                })

        for t, team, q, pts in plays:
            if streak and team == streak["team"]:
                streak["pts"] += pts
                streak["t_last"], streak["q_last"] = t, q
            else:
                _flush()
                others = score.copy()
                others.pop(team, None)
                opp_pts = max(others.values()) if others else 0
                streak = {"team": team, "pts": pts, "t0": t, "q0": q,
                          "t_last": t, "q_last": q,
                          "margin0": score[team] - opp_pts}
            score[team] += pts
        _flush()

        # momentum: net points in the window after each run's last basket
        for r in game_runs:
            net = 0
            for t, team, _q, pts in plays:
                if r["t_end"] < t <= r["t_end"] + MOMENTUM_WINDOW:
                    net += pts if team == r["team_id"] else -pts
            r["momentum"] = net
        runs.extend(game_runs)
    return runs


def _game_results(game_ids):
    """{game_id: {team_id: 'W'|'L'}} for finished games in the set."""
    ids = list(game_ids)
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    rows = query(
        f"SELECT id, team1_id, team2_id, home_score, away_score FROM games "
        f"WHERE id IN ({ph}) AND home_score IS NOT NULL "
        f"AND away_score IS NOT NULL", tuple(ids))
    out = {}
    for r in rows:
        if r["home_score"] == r["away_score"]:
            continue
        hw = r["home_score"] > r["away_score"]
        out[r["id"]] = {r["team1_id"]: "W" if hw else "L",
                        r["team2_id"]: "L" if hw else "W"}
    return out


def league_run_table(gender=None, game_ids=None, events=None,
                     min_run=RUN_MIN, big=BIG_RUN):
    """{team_id: profile} of run behaviour over the tracked games.

    Profile keys (garbage-time runs excluded from ALL of them, counted in
    'garbage'): gp, made_pg / allowed_pg (>= big runs per game), made6_pg /
    allowed6_pg (>= min_run), biggest, avg_secs (mean length of own big runs),
    avg_momentum (net pts in the 2 minutes after own big runs), by_count
    {0,1,2,'3+' -> [W, L]} (record by number of own big runs in the game),
    garbage (own garbage-time runs, all sizes)."""
    import helpers.stats as S
    if events is None:
        import helpers.playtypes as PT
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    if not events:
        return {}
    runs = detect_runs(events, min_run=min_run)
    gids = {e["game_id"] for e in events if e.get("game_id") is not None}
    results = _game_results(gids)

    # every (game, team) side that has events — the per-game denominators
    sides = defaultdict(set)
    for e in events:
        t = e.get("shooter_team_id")
        if t is not None and e.get("game_id") is not None:
            sides[e["game_id"]].add(t)

    prof = defaultdict(lambda: {
        "gp": 0, "made": 0, "allowed": 0, "made6": 0, "allowed6": 0,
        "biggest": 0, "secs": [], "momentum": [], "garbage": 0,
        "by_count": {0: [0, 0], 1: [0, 0], 2: [0, 0], "3+": [0, 0]},
    })
    for gid, teams in sides.items():
        for t in teams:
            prof[t]["gp"] += 1

    per_game_big = defaultdict(int)          # (gid, team) -> own big runs
    for r in runs:
        t, gid = r["team_id"], r["game_id"]
        if r["garbage"]:
            prof[t]["garbage"] += 1
            continue
        prof[t]["made6"] += 1
        for opp in sides.get(gid, ()):  # the other side "allowed" it
            if opp != t:
                prof[opp]["allowed6"] += 1
        prof[t]["biggest"] = max(prof[t]["biggest"], r["points"])
        if r["points"] >= big:
            per_game_big[(gid, t)] += 1
            prof[t]["made"] += 1
            prof[t]["secs"].append(r["secs"])
            prof[t]["momentum"].append(r["momentum"])
            for opp in sides.get(gid, ()):
                if opp != t:
                    prof[opp]["allowed"] += 1

    for gid, teams in sides.items():
        res = results.get(gid)
        if not res:
            continue
        for t in teams:
            wl = res.get(t)
            if wl is None:
                continue
            n = per_game_big.get((gid, t), 0)
            key = n if n <= 2 else "3+"
            prof[t]["by_count"][key][0 if wl == "W" else 1] += 1

    out = {}
    for t, p in prof.items():
        gp = p["gp"] or 1
        out[t] = {
            "gp": p["gp"],
            "made_pg": p["made"] / gp, "allowed_pg": p["allowed"] / gp,
            "made6_pg": p["made6"] / gp, "allowed6_pg": p["allowed6"] / gp,
            "biggest": p["biggest"],
            "avg_secs": (sum(p["secs"]) / len(p["secs"])) if p["secs"] else None,
            "avg_momentum": (sum(p["momentum"]) / len(p["momentum"])
                             if p["momentum"] else None),
            "by_count": p["by_count"],
            "garbage": p["garbage"],
        }
    return out


def team_runs(team_id, events, big=BIG_RUN):
    """One team's run read off already-fetched events (the Situational tab
    section): the league_run_table profile for this team plus its raw run list
    (own + allowed, garbage flagged) for the drill table."""
    table = league_run_table(events=events, big=big)
    mine = table.get(team_id)
    if not mine:
        return None
    rl = [r for r in detect_runs(events)
          if r["team_id"] == team_id or team_id in
          {e.get("shooter_team_id") for e in events
           if e.get("game_id") == r["game_id"]}]
    return {"profile": mine, "runs": rl}
