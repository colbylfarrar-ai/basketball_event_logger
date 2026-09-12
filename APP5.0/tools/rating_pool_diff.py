"""rating_pool_diff.py — does the POOL a rating is computed over change the rating?

Not a constant audit (that is `tools/rating_diff.py`). This one holds every
constant still and moves only the set of games the engine is handed, because
the Team Dashboard hands it two different sets on one render.

WHY THIS EXISTS
---------------
Traced on 2026-09-12, one cold render of Team Dashboard -> Charts -> Defense ->
Team Defense calls `player_ratings._pure_rapm_cached` twice, with two different
pools and the same gender:

    player_ratings:1487 < player_stat_table < team_player_rows < team_bundle
        gender=F   63 games   <- EVERY tracked game that season, both genders
    player_ratings:1487 < player_stat_table < _ptable_full < _matchup_grid
        gender=F   43 games   <- the girls' tracked pool

`team_analytics.team_player_rows` builds its pool as

    SELECT id FROM games WHERE tracked=1 AND season=?

with no gender predicate, and then passes `gender=gender` down — so the GENDER
filter reaches the players and never reaches the possessions the RAPM leaf is
solved over. The other path is gender-scoped.

Both tables are labelled "girls", both are rendered on the same page, and they
do not agree. Measured on the production book (43 F / 20 M tracked games, 261
rated girls):

    OVERALL delta (63-pool minus 43-pool)
        -0.4  8 players     -0.1  26      +0.1  53
        -0.3  4 players      0.0 167      +0.2   3
    league RANK differs for 136 of 261; biggest move 10 places (#127 -> #117)
    the top ten is NOT identical

The magnitudes are small. The property is not: a player has two league ranks on
one screen depending on which code path drew the table, which is THE BOOK 8.3's
"two engines that answer the same question differently" in a new place.

WHICH ONE IS RIGHT is a founder call, which is why this is a measuring script
and not a patch. The gender-scoped pool is the obvious candidate — a girls'
league rank computed against a pool that includes boys' possessions is hard to
defend — but it moves published OVERALL numbers, and the standing rule
(`recal-round2`) is that nothing that moves a rating ships without its own gate.
This script IS that gate: run it, read the two columns, decide.

    python -m tools.rating_pool_diff                  # F, the read season
    python -m tools.rating_pool_diff --gender M --top 40
    APP5_DATA_DIR=~/app5_prod python -m tools.rating_pool_diff
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.player_ratings as PR          # noqa: E402
import helpers.seasons as SEAS               # noqa: E402


def pools(gender, season=None):
    """(ungendered pool, gendered pool) of tracked game ids for `season`."""
    season = season or SEAS.default_read_season()
    every = sorted(SEAS.game_pool(season, tracked_only=True) or [])
    mine = sorted(SEAS.game_pool(season, gender=gender, tracked_only=True) or [])
    return season, every, mine


def diff(gender="F", season=None, min_games=1):
    """Rows for every player whose rating or rank moves between the two pools."""
    season, every, mine = pools(gender, season)
    if not every or not mine:
        return season, every, mine, []
    wide = PR.player_stat_table(gender=gender, min_games=min_games,
                                game_ids=set(every))
    narrow = PR.player_stat_table(gender=gender, min_games=min_games,
                                  game_ids=set(mine))
    rows = []
    for pid in sorted(set(wide) & set(narrow)):
        w, n = wide[pid], narrow[pid]
        dv = (None if w.get("OVERALL") is None or n.get("OVERALL") is None
              else round(w["OVERALL"] - n["OVERALL"], 2))
        dr = (None if w.get("Rank") is None or n.get("Rank") is None
              else w["Rank"] - n["Rank"])
        if not dv and not dr:
            continue
        rows.append({
            "pid": pid, "name": n.get("name"), "team": n.get("team"),
            "OVERALL_wide": w.get("OVERALL"), "OVERALL_gendered": n.get("OVERALL"),
            "dOVERALL": dv,
            "Rank_wide": w.get("Rank"), "Rank_gendered": n.get("Rank"),
            "dRank": dr,
        })
    rows.sort(key=lambda r: (-abs(r["dOVERALL"] or 0), -abs(r["dRank"] or 0)))
    return season, every, mine, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gender", default="F", choices=("F", "M"))
    ap.add_argument("--season", default=None)
    ap.add_argument("--min-games", type=int, default=1)
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    season, every, mine, rows = diff(a.gender, a.season, a.min_games)
    print(f"season {season}  ·  gender {a.gender}")
    print(f"  ungendered tracked pool : {len(every)} games   "
          f"(what team_player_rows hands the engine)")
    print(f"  gendered tracked pool   : {len(mine)} games   "
          f"(what _ptable_full hands it)")
    if not rows:
        print("\n  the two pools produce identical ratings and ranks.")
        return 0
    moved_v = sum(1 for r in rows if r["dOVERALL"])
    moved_r = sum(1 for r in rows if r["dRank"])
    print(f"\n  {moved_v} players get a different OVERALL, "
          f"{moved_r} a different league Rank.")
    print(f"\n  {'player':<26}{'team':<22}{'OVR wide':>9}{'OVR gen':>9}"
          f"{'dOVR':>7}{'dRank':>7}")
    for r in rows[:a.top]:
        nm = str(r["name"] or f"#{r['pid']}")[:25]
        tm = str(r["team"] or "")[:21]
        print(f"  {nm:<26}{tm:<22}"
              f"{(r['OVERALL_wide'] or 0):>9.1f}{(r['OVERALL_gendered'] or 0):>9.1f}"
              f"{(r['dOVERALL'] or 0):>+7.2f}{(r['dRank'] or 0):>+7d}")
    if len(rows) > a.top:
        print(f"  … {len(rows) - a.top} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
