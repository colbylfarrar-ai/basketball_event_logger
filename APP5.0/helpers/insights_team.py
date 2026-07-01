"""
insights_team.py — TEAM-level deep-dive splits for the Insights tab.

The player auto-scout lives in helpers/insights.py; this is the team read: how a
team's OWN offense changes by context. First split: opponent strength — does the
team keep scoring against top teams, or feast only on weak ones? Reuses the
play-type profile machinery (eFG / SCE / 3PA-rate / rim-rate / assisted / open /
zone) so the splits speak the same language as the rest of the app.

Streamlit-free (engines + sqlite). Scoped to the team's OWN shots in the passed
games, so there is no cross-game leak.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S
import helpers.playtypes as PT
import helpers.team_ratings as TR

MIN_SPLIT_SHOTS = 15        # a side needs this many shots before its split is shown


def _team_game_opponents(team_id, game_ids=None):
    """{game_id: opponent_team_id} for the team's tracked, current-season games
    (optionally limited to game_ids)."""
    rows = query(
        "SELECT id, team1_id, team2_id FROM games "
        "WHERE (team1_id=? OR team2_id=?) AND tracked=1 AND season='Current'",
        (team_id, team_id))
    allow = set(game_ids) if game_ids is not None else None
    out = {}
    for r in rows:
        if allow is not None and r["id"] not in allow:
            continue
        out[r["id"]] = r["team2_id"] if r["team1_id"] == team_id else r["team1_id"]
    return out


def _bucket_profiles(team_id, events, bucket_of, labels):
    """Build a finished play-type-style profile of the team's OWN shots per bucket.
    ``bucket_of(game_id)`` returns a bucket key (or None to skip); ``labels`` maps
    bucket key -> display label. No cross-game leak (own shots only)."""
    profs = {k: PT._blank_profile() for k in labels}
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] != team_id:
            continue
        b = bucket_of(e["game_id"])
        if b in profs:
            PT._profile_add(profs[b], e)
    return {k: PT._profile_fin(p, k, labels[k]) for k, p in profs.items()}


def winloss_splits(team_id, gender=None, game_ids=None, events=None):
    """The team's own-offense profile split by RESULT — how it plays in WINS vs
    LOSSES (what makes it go, what shows up when it loses). Same profile fields as
    strength_splits. `available` False until both sides clear MIN_SPLIT_SHOTS."""
    rows = query(
        "SELECT id, team1_id, home_score, away_score FROM games "
        "WHERE (team1_id=? OR team2_id=?) AND tracked=1 AND season='Current' "
        "AND home_score IS NOT NULL AND away_score IS NOT NULL",
        (team_id, team_id))
    allow = set(game_ids) if game_ids is not None else None
    result = {}                       # game_id -> 'win' | 'loss'
    for r in rows:
        if allow is not None and r["id"] not in allow:
            continue
        is_home = r["team1_id"] == team_id            # team1 = home in this app
        my = r["home_score"] if is_home else r["away_score"]
        opp = r["away_score"] if is_home else r["home_score"]
        if my == opp:
            continue
        result[r["id"]] = "win" if my > opp else "loss"
    if not result:
        return {"available": False}
    if events is None:
        events = S.fetch_events(list(result))
    profs = _bucket_profiles(team_id, events, lambda g: result.get(g),
                             {"win": "In wins", "loss": "In losses"})
    wins = sum(1 for v in result.values() if v == "win")
    return {
        "win": profs["win"], "loss": profs["loss"],
        "win_games": wins, "loss_games": len(result) - wins,
        "available": (profs["win"]["poss"] >= MIN_SPLIT_SHOTS
                      and profs["loss"]["poss"] >= MIN_SPLIT_SHOTS),
    }


def strength_splits(team_id, gender=None, game_ids=None, events=None, scored=None):
    """The team's own-offense profile split by OPPONENT STRENGTH (top vs bottom
    half of the league by Power rank).

    Returns {'top': prof, 'bottom': prof, 'top_games', 'bottom_games',
    'available': bool} where each prof is a play-type-style profile (PPP/eFG/SCE/
    3PA_rate/rim_rate/ast_rate/open_rate/top_zone/poss). `available` is False until
    both sides clear MIN_SPLIT_SHOTS. Also carries the opponent list per side."""
    if scored is None:
        scored = TR.score_ratings(gender=gender)
    opps = _team_game_opponents(team_id, game_ids)
    if not opps or not scored:
        return {"available": False}

    # median rank cut over the league (stable), then classify each opponent.
    ranks = [s["Rank"] for s in scored.values() if s.get("Rank")]
    if not ranks:
        return {"available": False}
    med = sorted(ranks)[len(ranks) // 2]
    # rank 1 = best; <= median => a TOP-half (strong) opponent.
    top_games, bottom_games = set(), set()
    top_opps, bottom_opps = [], []
    for gid, opp in opps.items():
        rk = (scored.get(opp) or {}).get("Rank")
        if rk is None:
            continue
        if rk <= med:
            top_games.add(gid)
            top_opps.append(opp)
        else:
            bottom_games.add(gid)
            bottom_opps.append(opp)

    if events is None:
        gids = list(opps)
        events = S.fetch_events(gids) if gids else []

    top_p, bot_p = PT._blank_profile(), PT._blank_profile()
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] != team_id:
            continue
        gid = e["game_id"]
        if gid in top_games:
            PT._profile_add(top_p, e)
        elif gid in bottom_games:
            PT._profile_add(bot_p, e)

    top = PT._profile_fin(top_p, "top", "vs Top-half")
    bot = PT._profile_fin(bot_p, "bottom", "vs Bottom-half")
    return {
        "top": top, "bottom": bot,
        "top_games": len(top_games), "bottom_games": len(bottom_games),
        "top_opps": top_opps, "bottom_opps": bottom_opps,
        "available": (top["poss"] >= MIN_SPLIT_SHOTS
                      and bot["poss"] >= MIN_SPLIT_SHOTS),
    }
