"""
adj_efficiency.py — opponent-adjusted SHOOTING (the missing KenPom half).

The efficiency numbers were already adjusted: tracked_ratings (helpers/
team_ratings.py) runs an iterative opponent adjustment over per-game ORtg/DRtg,
so every tracked ORtg / DRtg / NetRtg / PPP / oPPP surface is KenPom-style
schedule-corrected. SHOOTING was not — eFG% / opp eFG% everywhere are raw box
sums, so a team that faced elite defenses reads worse than it shot.

This module closes that gap with a weighted ridge on per-game shooting:

    efg(game: i attacks j) = μ + o_i + d_j

  μ     FGA-weighted league eFG over the sample
  o_i   team i's shooting effect (positive = shoots better than schedule says)
  d_j   defense j's effect on shooters (positive = shooters fatten up on them)

Solved in one closed-form weighted ridge (rows weighted by FGA; teams×2
unknowns, trivial at league scale). The ridge shrinks a thin team toward the
league mean — LAMBDA_GAMES sets how many average games of evidence it takes to
trust a team's own signal (mirrors the RAPM philosophy).

    AdjeFG_i  = μ + o_i    what the team would shoot against an AVERAGE defense
    AdjoeFG_j = μ + d_j    what an AVERAGE offense would shoot against them
                           (lower is better — true defensive shooting pressure)

Pure data layer (numpy + DB), no streamlit. Rows come straight from the event
stream grouped per (game, shooting team) — the game pairs are explicit, so
there is no allowed-side leak to guard.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from database.db import query
import helpers.stats as S

# Evidence (in average-games of FGA) required before a team's own shooting
# signal outweighs the league-mean prior. 2 ≈ half-shrunk at two games.
LAMBDA_GAMES = 2.0


def _tracked_pairs(gender=None, game_ids=None):
    """[(game_id, team1, team2)] for finished tracked Current-season games."""
    sql = """SELECT g.id, g.team1_id t1, g.team2_id t2
             FROM games g JOIN teams t ON t.id = g.team1_id
             WHERE g.tracked = 1 AND g.season = 'Current'"""
    params: tuple = ()
    if gender:
        sql += " AND t.gender = ?"
        params = (gender,)
    rows = query(sql, params)
    out = [(r["id"], r["t1"], r["t2"]) for r in rows]
    if game_ids is not None:
        keep = set(game_ids)
        out = [r for r in out if r[0] in keep]
    return out


def _game_shooting(pairs):
    """{(game_id, team_id): {"FGM","3PM","FGA"}} from the event stream."""
    gids = [g for g, _, _ in pairs]
    if not gids:
        return {}
    box = defaultdict(lambda: {"FGM": 0.0, "3PM": 0.0, "FGA": 0.0})
    for e in S.fetch_events(gids):
        if e["event_type"] != "shot" or e.get("shooter_team_id") is None:
            continue
        b = box[(e["game_id"], e["shooter_team_id"])]
        b["FGA"] += 1
        if e["shot_result"] == "make":
            b["FGM"] += 1
            if e["shot_type"] == 3:
                b["3PM"] += 1
    return box


def adjusted_shooting(gender=None, game_ids=None, lambda_games=LAMBDA_GAMES):
    """Opponent-adjusted eFG% for every tracked team.

    Returns {team_id: {"AdjeFG","AdjoeFG","RawEFG","RawOeFG","dEFG","dOeFG",
    "games","FGA"}} (eFG on the 0-1 scale, deltas = adjusted − raw) plus a
    "_meta" key {"mu","lam","rows"}; {} below 2 games or 2 teams.
    `game_ids` is the entitlement read-filter, same contract as tracked_ratings.
    """
    pairs = _tracked_pairs(gender, game_ids)
    box = _game_shooting(pairs)

    # one offense row per (game, shooting team) with a known defender
    rows = []                                  # (off_team, def_team, efg, fga)
    for gid, t1, t2 in pairs:
        for off, deff in ((t1, t2), (t2, t1)):
            b = box.get((gid, off))
            if not b or b["FGA"] < 1:
                continue
            rows.append((off, deff,
                         (b["FGM"] + 0.5 * b["3PM"]) / b["FGA"], b["FGA"]))
    teams = sorted({r[0] for r in rows} | {r[1] for r in rows})
    if len(rows) < 4 or len(teams) < 2:
        return {}

    w = np.array([r[3] for r in rows], dtype=float)
    y = np.array([r[2] for r in rows], dtype=float)
    mu = float(np.average(y, weights=w))

    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    X = np.zeros((len(rows), 2 * T))
    for i, (off, deff, _, _) in enumerate(rows):
        X[i, idx[off]] = 1.0                   # offense effect o_i
        X[i, T + idx[deff]] = 1.0              # defense effect d_j

    lam = lambda_games * float(w.mean())
    A = X.T @ (X * w[:, None]) + lam * np.eye(2 * T)
    beta = np.linalg.solve(A, X.T @ (w * (y - mu)))

    # per-team raw sums + volume for the honesty columns
    raw_o = defaultdict(lambda: [0.0, 0.0, 0.0])   # FGM, 3PM, FGA (own shots)
    raw_d = defaultdict(lambda: [0.0, 0.0, 0.0])   # shots ALLOWED
    gp = defaultdict(int)
    for off, deff, _, _ in rows:
        gp[off] += 1
    for gid, t1, t2 in pairs:
        for off, deff in ((t1, t2), (t2, t1)):
            b = box.get((gid, off))
            if not b:
                continue
            for acc, key in ((raw_o[off], off), (raw_d[deff], deff)):
                acc[0] += b["FGM"]; acc[1] += b["3PM"]; acc[2] += b["FGA"]

    out = {"_meta": {"mu": round(mu, 4), "lam": round(lam, 1),
                     "rows": len(rows)}}
    for t in teams:
        if gp[t] < 2:                          # one game = pure prior, skip
            continue
        ro = raw_o[t]
        rd = raw_d[t]
        raw_efg = (ro[0] + 0.5 * ro[1]) / ro[2] if ro[2] else None
        raw_oefg = (rd[0] + 0.5 * rd[1]) / rd[2] if rd[2] else None
        adj_efg = mu + float(beta[idx[t]])
        adj_oefg = mu + float(beta[T + idx[t]])
        out[t] = {
            "AdjeFG": round(adj_efg, 3), "AdjoeFG": round(adj_oefg, 3),
            "RawEFG": round(raw_efg, 3) if raw_efg is not None else None,
            "RawOeFG": round(raw_oefg, 3) if raw_oefg is not None else None,
            "dEFG": round(adj_efg - raw_efg, 3) if raw_efg is not None else None,
            "dOeFG": (round(adj_oefg - raw_oefg, 3)
                      if raw_oefg is not None else None),
            "games": gp[t], "FGA": int(ro[2]),
        }
    return out if len(out) > 1 else {}
