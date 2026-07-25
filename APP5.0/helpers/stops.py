"""
stops.py — defensive stop-strings ("kills") and the answer rate.

Two cross-sport steals off one chronological walk (spec Part 4e / 4f):

  KILL          Miami Heat's defensive metric: >= KILL_MIN (3) consecutive
                opponent trips that produce NO points. runs.py already measures
                scoring runs in POINTS ("10-0"), and its docstring notes that
                long runs ARE strings of stops — this names the stops directly
                instead of inferring them from the scoreboard.
  ANSWER RATE   Volleyball's side-out%: after the opponent scores, how often does
                our very next trip score? The momentum-stopper stat, finer than
                runs.momentum (which measures a window of game clock AFTER a
                >= 6-point run ends, so it cannot see a single answered basket).

THE UNIT IS A TRIP, NOT A "POSSESSION" AS lineups.py COUNTS THEM. This is a
deliberate divergence and the numbers here are NOT comparable to the PPP /
per-100 surfaces:

  * lineups.py / networks.py count EVERY shot or turnover as a possession and
    exclude free-throw points, because they measure efficiency and need a stable
    denominator.
  * A stop means "they came down and did not score". An offensive rebound
    continues the same trip, and made free throws mean they DID score. So this
    walk groups consecutive events by the team with the ball and counts points
    from made FGs AND made FTs (via situational._event_points).

Reading a kill count as if it shared the possession denominator would be wrong,
which is why trips are named `trips` throughout rather than `poss`.

ON-FLOOR CREDIT uses game_event_lineup, so it needs lineup snapshots; a trip
with no snapshot still counts for the TEAM and simply credits nobody.

Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.situational as SIT

_safe = S._safe

KILL_MIN = 3        # consecutive scoreless opponent trips that make a "kill"


def _trips(events):
    """Chronological trips per game: [(game_id, off_team, points, [event_ids])].

    A trip is a maximal run of consecutive events belonging to the same team
    with the ball. Only shot / turnover / free_throw events carry possession
    here — fouls, substitutions and timeouts do not change who has the ball, so
    they are skipped rather than splitting a trip in two.
    """
    by_game = defaultdict(list)
    for e in events:
        if e.get("event_type") not in ("shot", "turnover", "free_throw"):
            continue
        if e.get("shooter_team_id") is None or e.get("game_id") is None:
            continue
        by_game[e["game_id"]].append(e)

    out = []
    for gid, evs in by_game.items():
        evs.sort(key=SIT._elapsed)
        cur_team = None
        pts = 0
        ids = []
        for e in evs:
            t = e["shooter_team_id"]
            if cur_team is None:
                cur_team = t
            elif t != cur_team:
                out.append((gid, cur_team, pts, ids))
                cur_team, pts, ids = t, 0, []
            p, _scorer = SIT._event_points(e)
            pts += p
            ids.append(e["id"])
        if cur_team is not None:
            out.append((gid, cur_team, pts, ids))
    return out


def _floor_map(game_ids=None):
    """{event_id: {team_id: frozenset(pids)}} — on-court sets for credit."""
    clause, params = S._game_filter(game_ids)
    rows = query(
        f"""SELECT gel.event_id eid, gel.player_id pid, gel.team_id tid
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            {clause}""", params)
    out = defaultdict(lambda: defaultdict(set))
    for r in rows:
        out[r["eid"]][r["tid"]].add(r["pid"])
    return {eid: {t: frozenset(s) for t, s in d.items()}
            for eid, d in out.items()}


def team_stops(team_id, game_ids=None, events=None, kill_min=KILL_MIN,
               with_players=True):
    """Kills + answer rate for one team.

    Returns {
      "trips_faced", "stops", "stop_pct",     defensive trips and how many scored 0
      "kills", "kills_per_game", "games",     stop-strings of >= kill_min
      "longest_stop_streak",
      "answer": {"chances", "answered", "rate"},   scored right after conceding
      "conceded_runs_allowed",                     opponent scored back-to-back
      "players": [{pid, name, kills_on, stops_on, trips_on, stop_pct,
                   answer_chances, answered, answer_rate}],
    }

    `stop_pct` is the share of opponent trips that produced nothing — the plain
    number behind the kill count, reported alongside it because kills are a
    threshold statistic and a team can improve its defense without its kill
    count moving.

    Player credit is ON-FLOOR: a player is credited with a kill when they were
    on the court for the LAST stop of the string (the one that completed it),
    which is the convention that keeps a kill attributable to a specific moment
    rather than smeared across substitutions mid-string.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    trips = _trips(events)
    floor = _floor_map(game_ids) if with_players else {}

    games = {gid for gid, _t, _p, _i in trips}
    trips_faced = stops = kills = 0
    longest = streak = 0
    answer_chances = answered = 0
    conceded_runs = 0
    p_stops = defaultdict(int)
    p_trips = defaultdict(int)
    p_kills = defaultdict(int)
    p_ans_ch = defaultdict(int)
    p_ans = defaultdict(int)

    # walk per game so a streak never spans the horn
    per_game = defaultdict(list)
    for gid, t, pts, ids in trips:
        per_game[gid].append((t, pts, ids))

    for gid, seq in per_game.items():
        streak = 0
        pending_answer = False          # opponent just scored; our next trip answers
        last_opp_scored = False         # did their PREVIOUS trip score?
        for t, pts, ids in seq:
            on = None
            if ids:
                fl = floor.get(ids[-1]) or {}
                on = fl.get(team_id)

            if t == team_id:
                # our trip — does it answer a concession?
                if pending_answer:
                    answer_chances += 1
                    if pts > 0:
                        answered += 1
                    if on:
                        for p in on:
                            p_ans_ch[p] += 1
                            if pts > 0:
                                p_ans[p] += 1
                    pending_answer = False
            else:
                # opponent trip — a defensive stop or a concession
                trips_faced += 1
                if on:
                    for p in on:
                        p_trips[p] += 1
                if pts == 0:
                    stops += 1
                    streak += 1
                    longest = max(longest, streak)
                    if on:
                        for p in on:
                            p_stops[p] += 1
                    if streak == kill_min:
                        kills += 1
                        if on:
                            for p in on:
                                p_kills[p] += 1
                    # a string longer than kill_min is still ONE kill; it is
                    # counted once, when it reaches the threshold
                else:
                    # They scored on consecutive trips DOWN — the read a coach
                    # means by "we couldn't get a stop". Deliberately measured
                    # across opponent trips only, NOT as "they scored twice with
                    # no trip of ours between": consecutive same-team events
                    # never change possession, so the trip walk merges them and
                    # that condition could essentially never fire.
                    if last_opp_scored:
                        conceded_runs += 1
                    streak = 0
                    pending_answer = True
                last_opp_scored = pts > 0

    players = []
    if with_players and (p_trips or p_ans_ch):
        name_of = {r["id"]: r["name"] for r in query(
            "SELECT id, name FROM players WHERE team_id=?", (team_id,))}
        for pid in set(p_trips) | set(p_ans_ch):
            tr = p_trips.get(pid, 0)
            ch = p_ans_ch.get(pid, 0)
            players.append({
                "pid": pid, "name": name_of.get(pid, str(pid)),
                "kills_on": p_kills.get(pid, 0),
                "stops_on": p_stops.get(pid, 0), "trips_on": tr,
                "stop_pct": (100.0 * p_stops.get(pid, 0) / tr) if tr else None,
                "answer_chances": ch, "answered": p_ans.get(pid, 0),
                "answer_rate": (100.0 * p_ans.get(pid, 0) / ch) if ch else None,
            })
        players.sort(key=lambda d: (-d["kills_on"], -(d["stop_pct"] or 0)))

    n_games = len(games) or 1
    return {
        "trips_faced": trips_faced, "stops": stops,
        "stop_pct": (100.0 * stops / trips_faced) if trips_faced else None,
        "kills": kills, "kills_per_game": round(kills / n_games, 2),
        "games": len(games), "longest_stop_streak": longest,
        "kill_min": kill_min,
        "answer": {"chances": answer_chances, "answered": answered,
                   "rate": ((100.0 * answered / answer_chances)
                            if answer_chances else None)},
        "conceded_runs_allowed": conceded_runs,
        "players": players,
    }


def stops_verdict(st):
    """[(badge, n, text)] for helpers.cards.verdict_card — verdict-first, and
    silent about anything the sample cannot support."""
    lines = []
    if st["trips_faced"] >= 20:
        lines.append((
            "Kills", st["trips_faced"],
            f"<b>{st['kills']}</b> kill{'s' if st['kills'] != 1 else ''} "
            f"({st['kills_per_game']}/game) — {st['kill_min']}+ straight trips "
            f"without conceding. Stopped <b>{st['stop_pct']:.0f}%</b> of "
            f"opponent trips overall; longest string "
            f"<b>{st['longest_stop_streak']}</b>."))
    a = st["answer"]
    if a["chances"] >= 20:
        lines.append((
            "Answer rate", a["chances"],
            f"Scored on <b>{a['rate']:.0f}%</b> of the trips right after "
            f"conceding. They gave up back-to-back scores "
            f"<b>{st['conceded_runs_allowed']}</b> times."))
    return lines
