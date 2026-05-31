"""
officials.py — the officiating stat engine (Streamlit-free, like stats.py).

Data model (see database/schema.sql):
  • officials                — one row per ref: id (PK), name, official_id (ext).
  • game_lineup_officials    — which refs were on the floor for a game
                               (authoritative "games worked" list; the tracker
                               writes a row for every on-court official).
  • game_events.official_id  — set ONLY on `foul` events: the ref who made the
                               call. The fouler is `secondary_player_id`, so the
                               foul is charged against THAT player's team.

So two grains of data exist per official:
  - foul-level   (who called what): exact, per-official, from foul events.
  - game-level   (pace / scoring of games worked): shared by all refs of a game,
                  from the games table + a possession estimate over its events.

Everything here is pure data — no Streamlit. `official_overview()` is the single
entry point the page reads; it returns a finished per-official table plus the
team lookup the charts need.
"""
import statistics
from collections import defaultdict

from database.db import query


# ── low-level loaders ───────────────────────────────────────────────────────

def _games(gender=None):
    """Tracked games with scores, optionally limited to one gender (team1's)."""
    rows = query(
        """SELECT g.id, g.team1_id, g.team2_id, g.date,
                  g.home_score, g.away_score, t1.gender AS gender
           FROM games g
           JOIN teams t1 ON t1.id = g.team1_id
           WHERE g.tracked = 1"""
    )
    if gender:
        rows = [r for r in rows if r["gender"] == gender]
    return {r["id"]: r for r in rows}


def _officials():
    return {r["id"]: r for r in query("SELECT id, name, official_id FROM officials")}


def _worked(game_ids):
    """{official_pk: set(game_id)} from game_lineup_officials, limited to game_ids."""
    if not game_ids:
        return {}
    rows = query("SELECT official_id AS off_pk, game_id FROM game_lineup_officials")
    out = defaultdict(set)
    gid_set = set(game_ids)
    for r in rows:
        if r["game_id"] in gid_set:
            out[r["off_pk"]].add(r["game_id"])
    return out


def _foul_events(game_ids):
    """Foul events in game_ids, with the fouler's team joined in."""
    if not game_ids:
        return []
    rows = query(
        """SELECT ge.game_id, ge.quarter, ge.official_id AS off_pk,
                  p.team_id AS fouler_team
           FROM game_events ge
           LEFT JOIN players p ON p.id = ge.secondary_player_id
           WHERE ge.event_type = 'foul'"""
    )
    gid_set = set(game_ids)
    return [r for r in rows if r["game_id"] in gid_set]


def _possessions_by_game(game_ids):
    """
    Combined (both teams) possessions per game, computed straight from raw
    events:  POSS = FGA + TOV  (FGA = #shot events, TOV = #turnover events).
    A possession is a shot or a turnover; free throws and fouls don't count.
    Returns {game_id: int}.
    """
    if not game_ids:
        return {}
    rows = query("SELECT game_id, event_type FROM game_events")
    gid_set = set(game_ids)
    acc = defaultdict(int)
    for r in rows:
        if r["game_id"] not in gid_set:
            continue
        if r["event_type"] in ("shot", "turnover"):
            acc[r["game_id"]] += 1
    return dict(acc)


def _safe(num, den):
    return num / den if den else 0.0


# ── main entry point ─────────────────────────────────────────────────────────

def official_overview(gender=None):
    """
    Returns {"officials": [row, ...], "teams": {team_id: name}}.

    Each official row:
      off_pk, name, ext_id
      games            games worked
      fouls            fouls THIS ref called (assigned foul events)
      FPG              fouls / game
      q1..q4           foul counts by quarter
      team_fouls       {team_id: fouls this ref called against that team}
      home_fouls       fouls called against the home team (team1)
      away_fouls       fouls called against the away team (team2)
      game_pts         combined points scored across games worked
      game_poss        combined possessions across games worked
      PPP              game_pts / game_poss  (scoring environment of their games)
      PTSPG            combined points per game
      POSSPG           combined possessions per game
      game_fouls       total fouls called by ANYONE in their games
      foul_share       fouls / game_fouls  (share of calls this ref made)
    """
    games = _games(gender)
    game_ids = list(games.keys())
    offs = _officials()
    worked = _worked(game_ids)
    fouls = _foul_events(game_ids)
    poss_by_game = _possessions_by_game(game_ids)

    teams = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}

    # per-official foul tallies
    f_total = defaultdict(int)
    f_qtr = defaultdict(lambda: defaultdict(int))
    f_team = defaultdict(lambda: defaultdict(int))
    f_home = defaultdict(int)
    f_away = defaultdict(int)
    # fouls this ref called per game — for FPG consistency (std)
    f_by_game = defaultdict(lambda: defaultdict(int))
    # total fouls per game (by anyone) — for foul_share
    game_total_fouls = defaultdict(int)

    for e in fouls:
        gid = e["game_id"]
        game_total_fouls[gid] += 1
        opk = e["off_pk"]
        if opk is None:
            continue
        f_total[opk] += 1
        f_by_game[opk][gid] += 1
        q = e["quarter"]
        if q in (1, 2, 3, 4):
            f_qtr[opk][q] += 1
        tid = e["fouler_team"]
        if tid is not None:
            f_team[opk][tid] += 1
            g = games.get(gid)
            if g:
                if tid == g["team1_id"]:
                    f_home[opk] += 1
                elif tid == g["team2_id"]:
                    f_away[opk] += 1

    rows = []
    for opk, gset in worked.items():
        if opk not in offs:
            continue
        o = offs[opk]
        n = len(gset)
        # game-level scoring environment over games worked
        gpts = 0
        gposs = 0.0
        gfouls = 0
        for gid in gset:
            g = games.get(gid)
            if g and g["home_score"] is not None and g["away_score"] is not None:
                gpts += g["home_score"] + g["away_score"]
            gposs += poss_by_game.get(gid, 0.0)
            gfouls += game_total_fouls.get(gid, 0)

        ftot = f_total.get(opk, 0)
        # per-game foul counts (0 for worked games where this ref called none)
        per_game = [f_by_game[opk].get(gid, 0) for gid in gset]
        fpg_std = statistics.pstdev(per_game) if len(per_game) > 1 else 0.0
        home_f = f_home.get(opk, 0)
        away_f = f_away.get(opk, 0)
        rows.append({
            "off_pk": opk,
            "name": o["name"],
            "ext_id": o["official_id"],
            "games": n,
            "fouls": ftot,
            "FPG": _safe(ftot, n),
            "FPG_std": fpg_std,
            "q1": f_qtr[opk].get(1, 0),
            "q2": f_qtr[opk].get(2, 0),
            "q3": f_qtr[opk].get(3, 0),
            "q4": f_qtr[opk].get(4, 0),
            "team_fouls": dict(f_team.get(opk, {})),
            "home_fouls": home_f,
            "away_fouls": away_f,
            "ha_diff": home_f - away_f,
            "game_pts": gpts,
            "game_poss": gposs,
            "PPP": _safe(gpts, gposs),
            "PTSPG": _safe(gpts, n),
            "POSSPG": _safe(gposs, n),
            "game_fouls": gfouls,
            "foul_share": _safe(ftot, gfouls),
        })

    rows.sort(key=lambda r: (-r["fouls"], r["name"]))
    return {"officials": rows, "teams": teams}


def official_game_log(off_pk, gender=None):
    """
    Per-game detail for one official, newest first. Each row:
      game_id, date, matchup, home, away, home_score, away_score,
      fouls (this ref's calls), game_fouls (all calls), poss, ppp.
    """
    games = _games(gender)
    game_ids = list(games.keys())
    worked = _worked(game_ids).get(off_pk, set())
    if not worked:
        return []

    fouls = _foul_events(game_ids)
    poss_by_game = _possessions_by_game(game_ids)
    teams = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}

    mine = defaultdict(int)
    allf = defaultdict(int)
    for e in fouls:
        allf[e["game_id"]] += 1
        if e["off_pk"] == off_pk:
            mine[e["game_id"]] += 1

    out = []
    for gid in worked:
        g = games.get(gid)
        if not g:
            continue
        home = teams.get(g["team1_id"], "?")
        away = teams.get(g["team2_id"], "?")
        poss = poss_by_game.get(gid, 0.0)
        pts = 0
        if g["home_score"] is not None and g["away_score"] is not None:
            pts = g["home_score"] + g["away_score"]
        out.append({
            "game_id": gid,
            "date": g["date"],
            "matchup": f"{home} vs {away}",
            "home": home,
            "away": away,
            "home_score": g["home_score"],
            "away_score": g["away_score"],
            "fouls": mine.get(gid, 0),
            "game_fouls": allf.get(gid, 0),
            "poss": poss,
            "ppp": _safe(pts, poss),
        })
    out.sort(key=lambda r: (r["date"] or ""), reverse=True)
    return out
