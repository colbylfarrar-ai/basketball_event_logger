"""
fouls.py — foul & free-throw detail, derived from the event stream.

The user logs a foul as (player fouled, player who fouled, official). In
game_events a foul row is: primary_player_id = the player who was FOULED,
secondary_player_id = the FOULER (the PF is charged here), official_id = the ref.
Free-throw rows are primary_player_id = shooter, shot_result = make/miss.

This surfaces what the plain box score can't: fouls drawn per player, FT% split by
half, team fouls by quarter and when a team put the opponent in the bonus (NFHS:
7th team foul of a HALF = 1-and-1, 10th = double bonus). Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S


_safe = S._safe   # shared definition lives in helpers.stats


def _half(q):
    return 1 if q <= 2 else 2


def player_foul_ft(game_ids=None, events=None):
    """
    Per player: {PF (committed), drawn (times fouled), FTA, FTM, 'FT%',
    FTA_1h/FTM_1h, FTA_2h/FTM_2h} over the given games.

    PF = secondary_player_id on fouls (the fouler). drawn = primary_player_id on
    fouls (the player fouled). FT splits use the event's quarter (H1 = Q1-2).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    out = defaultdict(lambda: {"PF": 0, "drawn": 0, "FTA": 0, "FTM": 0,
                               "FTA_1h": 0, "FTM_1h": 0, "FTA_2h": 0, "FTM_2h": 0})
    for e in events:
        et = e["event_type"]
        if et == "foul":
            fouler = e["secondary_player_id"]
            fouled = e["primary_player_id"]
            if fouler is not None:
                out[fouler]["PF"] += 1
            if fouled is not None:
                out[fouled]["drawn"] += 1
        elif et == "free_throw":
            sh = e["primary_player_id"]
            if sh is None:
                continue
            made = e["shot_result"] == "make"
            half = f"_{_half(e['quarter'])}h"
            d = out[sh]
            d["FTA"] += 1
            d["FTA" + half] += 1
            if made:
                d["FTM"] += 1
                d["FTM" + half] += 1
    for d in out.values():
        d["FT%"] = _safe(d["FTM"], d["FTA"]) * 100
    return dict(out)


def team_foul_by_quarter(game_ids=None, events=None):
    """
    {team_id: {'by_q': {q: fouls committed}, 'total': n, 'games': g,
    'opp_fta': FTA the team's fouls sent the OTHER team to the line for}}.

    Team fouls are attributed to the fouler's team (secondary_player_id). Foul
    timing (by quarter) shows when a team gets into trouble.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    pteam = {r["id"]: r["team_id"]
             for r in query("SELECT id, team_id FROM players")}
    out = defaultdict(lambda: {"by_q": defaultdict(int), "total": 0, "opp_fta": 0})
    games_of_team = defaultdict(set)
    for e in events:
        if e["event_type"] == "foul":
            team = pteam.get(e["secondary_player_id"])
            if team is not None:
                out[team]["by_q"][e["quarter"]] += 1
                out[team]["total"] += 1
                games_of_team[team].add(e["game_id"])

    # opp_fta: FTAs the team's fouls sent the OTHER team to the line for
    fta_by_team_game = defaultdict(int)
    for e in events:
        if e["event_type"] == "free_throw" and e["primary_player_id"] is not None:
            st = pteam.get(e["primary_player_id"])
            if st is not None:
                fta_by_team_game[(e["game_id"], st)] += 1
    # map: for each game, the two teams; opp_fta[teamA] += FTA[teamB]
    game_teams = defaultdict(set)
    for (gid, t) in fta_by_team_game:
        game_teams[gid].add(t)
    for gid, teams in game_teams.items():
        for t in teams:
            for other in teams:
                if other != t:
                    out[t]["opp_fta"] += fta_by_team_game[(gid, other)]
    for t in out:
        out[t]["by_q"] = dict(out[t]["by_q"])
        out[t]["games"] = len(games_of_team.get(t, ())) or 1
    return dict(out)
