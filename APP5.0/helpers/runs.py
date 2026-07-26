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


# ══════════════════════════════════════════════════════════════════════════════
#  RUN ANATOMY — what a run was MADE OF, not just that it happened
# ══════════════════════════════════════════════════════════════════════════════
# Everything above COUNTS runs. A count tells a coach a run happened; it does
# not tell them what to do differently, which is the whole point of looking. The
# anatomy answers three questions a coach actually asks about a surge:
#
#     how did it start          the event immediately before the first basket
#     what were we in           the defense tag across the run's possessions
#     what did it score with    the shot mix + free throws inside the window
#     who was out there         the on-floor five, from game_event_lineup
#
# The same four asked of runs ALLOWED is the more useful half: "when a team
# runs on us, we are in scramble 41% of the time" is a practice plan.
#
# RELIABILITY POSTURE. None of this is a trait claim and none of it is gated on
# split-half reliability, because none of it is a projection: it is a record of
# what was on the floor during specific stretches of specific games. It is
# reported with its n and described as history. A team's run COUNTS already
# ship as a verdict via `_t_runs`; the anatomy explains those counts rather
# than adding a new claim on top of them.

#: How a run started, in the order the classifier tries them.
TRIGGER_LABELS = {
    "takeaway": "off a forced TOV",
    "defensive_board": "off a DRB",
    "after_score": "after conceding a bucket",
    "off_own_miss": "off their own ORB",
    "period_start": "out of a quarter break",
    "unknown": "untagged",
}


def _lineups_for(event_ids):
    """{event_id: {team_id: (pid, ...)}} from game_event_lineup, or {}."""
    ids = [int(i) for i in event_ids if i is not None]
    if not ids:
        return {}
    out = defaultdict(lambda: defaultdict(list))
    # chunked so a long season does not blow the SQLite variable limit
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        ph = ",".join("?" * len(chunk))
        for r in query(f"SELECT event_id, player_id, team_id FROM "
                       f"game_event_lineup WHERE event_id IN ({ph})",
                       tuple(chunk)):
            out[r["event_id"]][r["team_id"]].append(r["player_id"])
    return {k: {t: tuple(sorted(v)) for t, v in d.items()}
            for k, d in out.items()}


def _classify_trigger(prev, team_id):
    """What handed this team the ball before its run's first basket."""
    if prev is None:
        return "period_start"
    et = prev.get("event_type")
    if et == "turnover":
        # the committer's team is not this team -> they gave it away
        return "takeaway" if prev.get("_team") != team_id else "unknown"
    if et == "shot":
        if prev.get("shot_result") == "make":
            return ("after_score" if prev.get("shooter_team_id") != team_id
                    else "unknown")
        rt = prev.get("rebounder_team_id")
        if rt == team_id:
            return ("off_own_miss"
                    if prev.get("shooter_team_id") == team_id
                    else "defensive_board")
        return "unknown"
    if et == "free_throw" and prev.get("shot_result") == "make":
        return ("after_score" if prev.get("shooter_team_id") != team_id
                else "unknown")
    return "unknown"


def _mode_share(counter):
    """(label, share, n) of the most common key, or None."""
    tot = sum(counter.values())
    if not tot:
        return None
    lbl, n = max(counter.items(), key=lambda kv: kv[1])
    return (lbl, n / tot, tot)


def run_anatomy(team_id, events, big=BIG_RUN, with_lineups=True):
    """What this team's runs — and the runs against it — were made of.

    Returns {"own": side, "allowed": side, "runs": [...]} where each side is
        {"n", "trigger": {label: count}, "defense": {tag: count},
         "points": {"rim04"/... : pts, "ft": pts}, "lineups": {five: count},
         "avg_pts", "avg_secs"}

    `events` must be the already-fetched pass (prod is 1 vCPU). Garbage-time
    runs are excluded, matching every other number in this module.
    """
    if not events or team_id is None:
        return {}
    import helpers.shot_kinds as SK
    pteam = None

    by_game = defaultdict(list)
    for e in events:
        if e.get("game_id") is not None:
            by_game[e["game_id"]].append(e)
    for gid in by_game:
        by_game[gid].sort(key=lambda e: SIT._elapsed(e))

    # turnovers carry the committer as primary_player_id -> resolve their team
    need = {e.get("primary_player_id") for e in events
            if e.get("event_type") == "turnover"}
    need.discard(None)
    if need:
        ids = [int(i) for i in need]
        ph = ",".join("?" * len(ids))
        pteam = {r["id"]: r["team_id"] for r in query(
            f"SELECT id, team_id FROM players WHERE id IN ({ph})", tuple(ids))}
    for e in events:
        if e.get("event_type") == "turnover":
            e["_team"] = (pteam or {}).get(e.get("primary_player_id"))

    runs = [r for r in detect_runs(events)
            if not r["garbage"] and r["points"] >= big]
    # only runs in games this team actually played
    mine_games = {gid for gid, evs in by_game.items()
                  if any(e.get("shooter_team_id") == team_id for e in evs)}
    runs = [r for r in runs if r["game_id"] in mine_games]
    if not runs:
        return {}

    lineup_map = {}
    if with_lineups:
        want = []
        for r in runs:
            for e in by_game[r["game_id"]]:
                t = SIT._elapsed(e)
                if r["t_end"] - r["secs"] <= t <= r["t_end"]:
                    want.append(e.get("id"))
        lineup_map = _lineups_for(want)

    def blank():
        return {"n": 0, "trigger": defaultdict(int), "defense": defaultdict(int),
                "points": defaultdict(float), "lineups": defaultdict(int),
                "pts": [], "secs": []}

    sides = {"own": blank(), "allowed": blank()}
    detail = []
    for r in runs:
        owner = r["team_id"]
        side = "own" if owner == team_id else "allowed"
        S_ = sides[side]
        S_["n"] += 1
        S_["pts"].append(r["points"])
        S_["secs"].append(r["secs"])
        t0 = r["t_end"] - r["secs"]
        evs = by_game[r["game_id"]]
        # the event immediately BEFORE the run's first scoring play
        prev = None
        first_idx = None
        for i, e in enumerate(evs):
            if SIT._elapsed(e) >= t0 and SIT._event_points(e)[0]:
                first_idx = i
                break
        if first_idx is not None:
            for j in range(first_idx - 1, -1, -1):
                if evs[j].get("event_type") in ("shot", "turnover",
                                                "free_throw"):
                    prev = evs[j]
                    break
        trig = _classify_trigger(prev, owner)
        S_["trigger"][trig] += 1

        run_def, fives = defaultdict(int), defaultdict(int)
        for e in evs:
            t = SIT._elapsed(e)
            if not (t0 <= t <= r["t_end"]):
                continue
            # what DEFENSE was on the floor. The tag describes the defense being
            # played against the shooter, so for the team that OWNS the run the
            # relevant tag is on its own attempts (what it attacked); for the
            # team being run on it is the same tag, read as "what we were in".
            if e.get("defense") and e.get("event_type") == "shot" \
                    and e.get("shooter_team_id") == owner:
                run_def[e["defense"]] += 1
                S_["defense"][e["defense"]] += 1
            pts, scorer = SIT._event_points(e)
            if pts and scorer == owner:
                if e.get("event_type") == "free_throw":
                    S_["points"]["ft"] += pts
                else:
                    band = SK.classify_band(e.get("shot_x"), e.get("shot_y"),
                                            e.get("shot_type"))
                    S_["points"][band] += pts
            lu = lineup_map.get(e.get("id")) or {}
            five = lu.get(team_id)
            if five and len(five) == 5:
                fives[five] += 1
                S_["lineups"][five] += 1
        detail.append({
            **r, "side": side, "trigger": trig,
            "defense": _mode_share(run_def),
            "five": (max(fives.items(), key=lambda kv: kv[1])[0]
                     if fives else None),
        })

    out = {"runs": sorted(detail, key=lambda d: (d["game_id"], d["t_end"]))}
    for k, S_ in sides.items():
        out[k] = {
            "n": S_["n"],
            "trigger": dict(S_["trigger"]), "defense": dict(S_["defense"]),
            "points": dict(S_["points"]), "lineups": dict(S_["lineups"]),
            "avg_pts": (sum(S_["pts"]) / len(S_["pts"])) if S_["pts"] else None,
            "avg_secs": (sum(S_["secs"]) / len(S_["secs"])
                         if S_["secs"] else None),
        }
    return out


def anatomy_verdict(an, names=None, team_name="This team"):
    """[(badge, n, html)] for helpers.cards.verdict_card — the anatomy in plain
    words. Descriptive: a record of the runs that happened, with their n."""
    if not an:
        return []
    lines = []
    names = names or {}

    for side, label, whose in (("own", "Their runs", "they"),
                               ("allowed", "Runs against them", "opponents")):
        s = an.get(side) or {}
        if not s.get("n"):
            continue
        trig = _mode_share(s["trigger"])
        bits = []
        if trig and trig[1] >= 0.30:
            bits.append(f"{trig[1] * 100:.0f}% "
                        f"<b>{TRIGGER_LABELS.get(trig[0], trig[0])}</b>")
        dfn = _mode_share(s["defense"])
        if dfn and dfn[1] >= 0.35:
            nice = str(dfn[0]).replace("_", " ")
            verb = "vs" if side == "own" else "in"
            bits.append(f"{verb} <b>{nice}</b> {dfn[1] * 100:.0f}%")
        pts = s.get("points") or {}
        tot = sum(pts.values())
        if tot:
            top = max(pts.items(), key=lambda kv: kv[1])
            where = ("the line" if top[0] == "ft" else _band_phrase(top[0]))
            bits.append(f"{top[1] / tot * 100:.0f}% from <b>{where}</b>")
        if not bits:
            continue
        lines.append((
            label, s["n"],
            f"<b>{s['n']}</b> × 10-0, <b>{s['avg_pts']:.0f} pts</b> in "
            f"<b>{s['avg_secs'] / 60:.1f} min</b> — " + " · ".join(bits) + "."))

    # The on-floor five, BOTH ways. Who is out there when the other team goes
    # on a run is the more actionable of the two and was the half originally
    # left out.
    for side, label, phrase in (
            ("own", "Floor — runs made", "most run minutes made"),
            ("allowed", "Floor — runs allowed", "most run minutes conceded")):
        lus = ((an.get(side) or {}).get("lineups") or {})
        if not lus or not names:
            continue
        five, n = max(lus.items(), key=lambda kv: kv[1])
        who = ", ".join(names.get(p, str(p)) for p in five)
        tot = sum(lus.values())
        lines.append((
            label, n,
            f"<b>{who}</b> — {phrase} ({n / tot * 100:.0f}%). Who was out "
            f"there, not proof of cause; five share every possession. RAPM "
            f"on Lab is the causal argument."))
    return lines


def _band_phrase(band):
    return {"rim04": "right at the rim", "two419": "the mid-range",
            "arc3": "the three-point line",
            "deep3": "well behind the arc"}.get(band, str(band))


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
