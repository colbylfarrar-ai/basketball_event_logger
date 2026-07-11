"""
fouls.py — foul & free-throw detail, derived from the event stream.

The user logs a foul as (player fouled, player who fouled, official). In
game_events a foul row is: primary_player_id = the player who was FOULED,
secondary_player_id = the FOULER (the PF is charged here), official_id = the ref.
Free-throw rows are primary_player_id = shooter, shot_result = make/miss.

This surfaces what the plain box score can't: fouls drawn per player, FT% split by
half, team fouls by quarter and when a team put the opponent in the bonus
(NFHS since 2023-24: team fouls reset each quarter, two-shot bonus on the 5th
team foul of the quarter; OT extends Q4 — no reset). Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S


_safe = S._safe   # shared definition lives in helpers.stats


# ── foul-type taxonomy ────────────────────────────────────────────────────────
# Optional KIND tag on a foul event (game_events.foul_type, nullable — old rows
# stay NULL). One source of truth: tracker, PWA, editors all read this list.
# KEYS are permanent data values; only labels may change. 'offensive' = a charge
# / illegal screen (the fouler's team had the ball), 'rebounding' = over-the-back
# etc. on the glass. Untagged = a regular defensive foul; founder historically
# marked these via play_type='other', which stays readable as the legacy layer.
FOUL_TYPES = [
    ("offensive",  "Offensive"),
    ("rebounding", "Rebounding"),
]
_FT_KEYS = {k for k, _ in FOUL_TYPES}
_FT_LABEL = dict(FOUL_TYPES)


def foul_type_label(key):
    """Display label for a foul-type key (unknown -> the key itself)."""
    return _FT_LABEL.get(key, key)


def _half(q):
    return 1 if q <= 2 else 2


# A free throw is "clutch" when the moment's leverage (the win-probability
# swing a basket would cause) is >= CLUTCH_LI x the game's average moment —
# the same 1.5 threshold Clutch WPA uses, so "clutch" means ONE thing app-wide.
CLUTCH_LI = 1.5


def _ft_pressure(events, out):
    """Annotate `out` (the player_foul_ft accumulator) with clutch-FT and and-1
    counts. Walks each game's timeline once: score state -> leverage at every
    scoring event (normalized by the game's mean, mirroring wpa.py) for the
    clutch split; event ADJACENCY for and-1s (a made FG by P followed, within
    the next few rows, by a SINGLE-FT trip by P — a two/three-FT trip is a
    fouled-on-the-miss trip, not an and-1)."""
    import helpers.win_probability as WP
    by_game = defaultdict(list)
    for e in events:
        by_game[e["game_id"]].append(e)
    for evs in by_game.values():
        evs.sort(key=lambda e: (S.elapsed(e["quarter"], e["time"]),
                                e.get("id") or 0))
        end = max((S.elapsed(e["quarter"], e["time"]) for e in evs),
                  default=1) or 1
        pts = defaultdict(int)               # team_id -> points so far
        teams = []                           # the two team ids, discovery order
        fts = []                             # (shooter, made, leverage)
        lis = []
        for e in evs:
            if e["event_type"] not in ("shot", "free_throw"):
                continue
            team = e.get("shooter_team_id")
            if team is None:
                continue
            if team not in teams:
                teams.append(team)
            opp = None
            if len(teams) > 1:
                opp = teams[0] if team == teams[1] else teams[1]
            margin = pts[team] - (pts[opp] if opp is not None else 0)
            secs_left = max(end - S.elapsed(e["quarter"], e["time"]), 0)
            li = abs(WP.win_prob(margin + 2, secs_left, end)
                     - WP.win_prob(margin - 2, secs_left, end))
            lis.append(li)
            made = e["shot_result"] == "make"
            if e["event_type"] == "free_throw" \
                    and e["primary_player_id"] is not None:
                fts.append((e["primary_player_id"], made, li))
            if made:
                pts[team] += 1 if e["event_type"] == "free_throw" else \
                    (3 if e["shot_type"] == 3 else 2)
        mean_li = (sum(lis) / len(lis)) if lis else 0.0
        if mean_li > 0:
            for pid, made, li in fts:
                if li / mean_li >= CLUTCH_LI:
                    out[pid]["cFTA"] += 1
                    if made:
                        out[pid]["cFTM"] += 1
        # and-1 pass: a made FG then a lone FT by the same shooter right after
        for i, e in enumerate(evs):
            if e["event_type"] != "shot" or e["shot_result"] != "make" \
                    or e["primary_player_id"] is None:
                continue
            p = e["primary_player_id"]
            for j in range(i + 1, min(i + 4, len(evs))):
                nx = evs[j]
                if nx["event_type"] == "foul":
                    continue                 # the foul row between FG and FT
                if nx["event_type"] == "free_throw" \
                        and nx["primary_player_id"] == p:
                    run = 1
                    k = j + 1
                    while k < len(evs) \
                            and evs[k]["event_type"] == "free_throw" \
                            and evs[k]["primary_player_id"] == p:
                        run += 1
                        k += 1
                    if run == 1:             # one FT = the and-1 trip
                        out[p]["and1"] += 1
                        if nx["shot_result"] == "make":
                            out[p]["and1_made"] += 1
                break                        # anything else ends the window


def player_foul_ft(game_ids=None, events=None):
    """
    Per player: {PF (committed), drawn (times fouled), FTA, FTM, 'FT%',
    FTA_1h/FTM_1h, FTA_2h/FTM_2h, cFTA/cFTM/'ClutchFT%' (free throws in
    high-leverage moments), and1/and1_made (made FG + a lone FT right after,
    linked by event adjacency)} over the given games.

    PF = secondary_player_id on fouls (the fouler). drawn = primary_player_id on
    fouls (the player fouled). FT splits use the event's quarter (H1 = Q1-2).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    out = defaultdict(lambda: {"PF": 0, "drawn": 0, "FTA": 0, "FTM": 0,
                               "FTA_1h": 0, "FTM_1h": 0, "FTA_2h": 0, "FTM_2h": 0,
                               "cFTA": 0, "cFTM": 0, "and1": 0, "and1_made": 0})
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
    _ft_pressure(events, out)
    for d in out.values():
        d["FT%"] = _safe(d["FTM"], d["FTA"]) * 100
        d["ClutchFT%"] = (_safe(d["cFTM"], d["cFTA"]) * 100) if d["cFTA"] else None
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
