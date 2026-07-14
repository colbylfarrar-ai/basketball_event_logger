"""tools/team_prior_diff.py — before/after OVERALL under the team-Power anchor.

Focuses on the population the feature targets: players with few evidence games
whose team has an above-average Power. Run and eyeball whether the lift is
reasonable (thin players on strong teams rise a few points; nobody on an average
team moves; deep-sample stars barely move). Pick the largest LAMBDA whose top
movers still look sane.

DB-agnostic: auto-scopes to the tracked pool in whatever DB is present (local
2025-2026 or prod 'Current').

    python tools/team_prior_diff.py            # default lambdas 0.25/0.35/0.5
    python tools/team_prior_diff.py 0.35       # one lambda
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helpers.player_ratings as PR
import helpers.team_ratings as TR
from database.db import query


def _tracked_scope():
    rows = query("SELECT id, season FROM games WHERE tracked=1")
    if len(rows) < 5:
        return None, None
    seasons = {}
    for r in rows:
        seasons.setdefault(r["season"], []).append(r["id"])
    season = max(seasons, key=lambda s: len(seasons[s]))
    return [r["id"] for r in rows], season


def run(lambdas):
    gids, season = _tracked_scope()
    if gids is None:
        print("No tracked pool in this DB — nothing to diff.")
        return
    powers = {t: r["Power"] for t, r in TR.score_ratings(season=season).items()}
    profs = PR.player_profiles(gids, season=season)   # for evidence_gp (drives shrink)
    orig = PR.TEAM_PRIOR_LAMBDA
    try:
        PR.TEAM_PRIOR_LAMBDA = 0.0
        base = PR.player_ratings(game_ids=gids, season=season)
        print(f"pool: {len(base)} players, season={season}, {len(gids)} tracked games")
        for lam in lambdas:
            PR.TEAM_PRIOR_LAMBDA = lam
            now = PR.player_ratings(game_ids=gids, season=season)
            rows = []
            for p, r in now.items():
                d = r["OVERALL"] - base[p]["OVERALL"]
                if abs(d) < 0.05:
                    continue
                eg = profs.get(p, {}).get("evidence_gp", 0.0)
                rows.append((d, r.get("name", p), eg, powers.get(r.get("team_id"))))
            rows.sort(key=lambda x: -abs(x[0]))
            print(f"\n=== lambda={lam} : {len(rows)}/{len(base)} players moved ===")
            print(f"{'dOVR':>6}  {'name':<24} {'evG':>4} {'teamPow':>7}")
            for d, name, eg, pw in rows[:20]:
                print(f"{d:+6.1f}  {str(name):<24} {eg:>4.1f} "
                      f"{'   n/a' if pw is None else f'{pw:7.1f}'}")
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig


if __name__ == "__main__":
    lams = [float(a) for a in sys.argv[1:] if a.replace(".", "", 1).isdigit()] or \
           [0.25, 0.35, 0.5]
    run(lams)
