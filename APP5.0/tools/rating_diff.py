"""
rating_diff.py — old-vs-new player-rating audit for the recalibration phases.

Runs player_ratings twice over the same tracked pool — incumbent constants vs a
candidate config — and reports every player's five ratings side by side, sorted
by |Δ OVERALL|. The eyeball gate before any constant change deploys: thin-sample
players drifting toward extremes with no new evidence = a bad config, whatever
the backtest says.

Usage
    python -m tools.rating_diff --set shrinkage.DEFAULT_INDEX_K=1.5 \
                                --set player_ratings.RATING_K_GAMES=2
    python -m tools.rating_diff --set ... --top 40
Importable
    diff_ratings(constants) -> list of row dicts (all players, sorted by |dOVR|)
"""
from __future__ import annotations

import argparse

import helpers.player_ratings as PR
from tools.backtest import (SEASON, override, clear_caches, tracked_games,
                            focus_team)

_CATS = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]


def _snapshot(gender, game_ids):
    clear_caches()
    R = PR.player_ratings(game_ids=game_ids, gender=gender, season=SEASON)
    return {pid: {c: row.get(c) for c in _CATS}
            | {"name": row["name"], "team": row["team"], "GP": row["GP"]}
            for pid, row in R.items()}


def diff_ratings(constants):
    """[{pid, name, team, GP, OVERALL_old, OVERALL_new, dOVERALL, …}] sorted by
    |Δ OVERALL| descending, every rated player."""
    _tid, gender, _n = focus_team()
    ids = [g["id"] for g in tracked_games()]
    old = _snapshot(gender, ids)
    with override(constants):
        new = _snapshot(gender, ids)
    rows = []
    for pid in old.keys() & new.keys():
        o, n = old[pid], new[pid]
        row = {"pid": pid, "name": o["name"], "team": o["team"], "GP": o["GP"]}
        for c in _CATS:
            ov, nv = o.get(c), n.get(c)
            row[f"{c}_old"] = ov
            row[f"{c}_new"] = nv
            row[f"d{c}"] = (round(nv - ov, 1)
                            if ov is not None and nv is not None else None)
        rows.append(row)
    rows.sort(key=lambda r: abs(r["dOVERALL"] or 0), reverse=True)
    return rows


def _parse_set(pairs):
    out = {}
    for p in pairs or []:
        name, _, val = p.partition("=")
        out[name.strip()] = float(val)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--set", action="append", metavar="NAME=VALUE",
                    help="constant override (repeatable), e.g. "
                         "shrinkage.DEFAULT_INDEX_K=1.5")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    constants = _parse_set(args.set)
    if not constants:
        ap.error("at least one --set NAME=VALUE required")
    rows = diff_ratings(constants)
    moved = [r for r in rows if (r["dOVERALL"] or 0) != 0]
    print(f"{len(rows)} players rated; {len(moved)} moved on OVERALL; "
          f"config: {constants}")
    print(f"{'player':<22}{'team':<20}{'GP':>3}  "
          f"{'OVR':>11}  {'dOFF':>6}{'dDEF':>6}{'dPLY':>6}{'dREB':>6}")
    for r in rows[:args.top]:
        ovr = f"{r['OVERALL_old']}->{r['OVERALL_new']}"
        print(f"{r['name'][:21]:<22}{r['team'][:19]:<20}{r['GP']:>3}  "
              f"{ovr:>11}  {r['dOFFENSE'] or 0:>6}{r['dDEFENSE'] or 0:>6}"
              f"{r['dPLAYMAKING'] or 0:>6}{r['dREBOUNDING'] or 0:>6}")


if __name__ == "__main__":
    main()
