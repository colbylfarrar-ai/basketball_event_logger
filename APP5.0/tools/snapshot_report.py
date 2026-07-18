"""
snapshot_report.py — data facts for the working DB, printed for a recal build log.

Run after pulling a prod snapshot so every recalibration decision is made against
recorded, dated facts (game counts, tag coverage, lineup coverage) instead of
memory. Also runs the turnover-type diagnostic (spec 2026-07-18 §9): where do
untyped turnovers cluster — steal-TOs (quick-mode capture gap) or whole games?

Usage
    python -m tools.snapshot_report            # human report
    python -m tools.snapshot_report --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from database.db import query, get_db_path


def game_facts():
    """Counts of finished/tracked games by season and gender."""
    rows = query(
        """SELECT g.season, t.gender,
                  COUNT(*) n,
                  SUM(g.tracked) tracked,
                  SUM(CASE WHEN g.home_score IS NOT NULL
                           AND g.away_score IS NOT NULL THEN 1 ELSE 0 END) finished
           FROM games g JOIN teams t ON t.id = g.team1_id
           GROUP BY g.season, t.gender ORDER BY g.season, t.gender""")
    return [dict(r) for r in rows]


def tracked_game_list(season="2025-2026"):
    """Every tracked game with team names, gender, date, event count."""
    return query(
        """SELECT g.id, g.date, t1.name n1, t2.name n2, t1.gender,
                  g.home_score hs, g.away_score aws,
                  (SELECT COUNT(*) FROM game_events ge WHERE ge.game_id=g.id) ev
           FROM games g JOIN teams t1 ON t1.id=g.team1_id
           JOIN teams t2 ON t2.id=g.team2_id
           WHERE g.tracked=1 AND g.season=? ORDER BY g.date""", (season,))


def tag_coverage(season="2025-2026"):
    """Per-tag fill rates over the season's tracked events — the depth-of-track
    facts. Denominators are the event rows the tag can apply to."""
    ev = query(
        """SELECT ge.event_type, ge.shot_result, ge.turnover_type,
                  ge.guarded_by_id, ge.rebound_by_id, ge.stolen_by_id,
                  ge.play_type, ge.defense, ge.official_id
           FROM game_events ge JOIN games g ON g.id=ge.game_id
           WHERE g.tracked=1 AND g.season=?""", (season,))
    n = defaultdict(int)
    d = defaultdict(int)
    for e in ev:
        et = e["event_type"]
        if et == "shot":
            d["guarded_by (makes)"] += (e["shot_result"] == "make")
            n["guarded_by (makes)"] += (e["shot_result"] == "make"
                                        and e["guarded_by_id"] is not None)
            d["rebound_by (misses)"] += (e["shot_result"] == "miss")
            n["rebound_by (misses)"] += (e["shot_result"] == "miss"
                                         and e["rebound_by_id"] is not None)
            d["play_type (shots)"] += 1
            n["play_type (shots)"] += e["play_type"] is not None
            d["defense (shots)"] += 1
            n["defense (shots)"] += e["defense"] is not None
        elif et == "turnover":
            d["turnover_type"] += 1
            n["turnover_type"] += e["turnover_type"] is not None
            d["stolen_by"] += 1
            n["stolen_by"] += e["stolen_by_id"] is not None
        elif et == "foul":
            d["official (fouls)"] += 1
            n["official (fouls)"] += e["official_id"] is not None
    return {k: {"n": n[k], "of": d[k],
                "pct": round(100.0 * n[k] / d[k], 1) if d[k] else None}
            for k in d}


def lineup_coverage(season="2025-2026"):
    """% of tracked events carrying a full (10-player) on-court snapshot, plus
    partial (1-9) and none — the DWPA team-split fallback rate."""
    rows = query(
        """SELECT ge.id, COUNT(gel.player_id) k
           FROM game_events ge JOIN games g ON g.id=ge.game_id
           LEFT JOIN game_event_lineup gel ON gel.event_id=ge.id
           WHERE g.tracked=1 AND g.season=? GROUP BY ge.id""", (season,))
    full = sum(1 for r in rows if r["k"] == 10)
    partial = sum(1 for r in rows if 0 < r["k"] < 10)
    none = sum(1 for r in rows if r["k"] == 0)
    tot = len(rows) or 1
    return {"events": len(rows), "full10": full, "partial": partial, "none": none,
            "full10_pct": round(100.0 * full / tot, 1)}


def to_diagnostic(season="2025-2026"):
    """Spec §9: untyped turnovers — do they cluster on steal-TOs / by game?"""
    rows = query(
        """SELECT ge.game_id, ge.turnover_type, ge.stolen_by_id, g.tracked_by
           FROM game_events ge JOIN games g ON g.id=ge.game_id
           WHERE ge.event_type='turnover' AND g.tracked=1 AND g.season=?""",
        (season,))
    tot = len(rows)
    untyped = [r for r in rows if r["turnover_type"] is None]
    u_steal = sum(1 for r in untyped if r["stolen_by_id"] is not None)
    t_steal = sum(1 for r in rows if r["stolen_by_id"] is not None)
    typed_steal = sum(1 for r in rows if r["stolen_by_id"] is not None
                      and r["turnover_type"] is not None)
    by_game = defaultdict(lambda: [0, 0])          # gid -> [untyped, total]
    for r in rows:
        by_game[r["game_id"]][1] += 1
        if r["turnover_type"] is None:
            by_game[r["game_id"]][0] += 1
    worst = sorted(by_game.items(), key=lambda kv: -kv[1][0])[:8]
    return {
        "turnovers": tot, "untyped": len(untyped),
        "untyped_pct": round(100.0 * len(untyped) / tot, 1) if tot else None,
        "steal_tos": t_steal,
        "steal_tos_typed": typed_steal,
        "untyped_with_steal": u_steal,
        "untyped_without_steal": len(untyped) - u_steal,
        "worst_games": [{"game_id": gid, "untyped": u, "total": t}
                        for gid, (u, t) in worst],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--season", default="2025-2026")
    args = ap.parse_args()
    rep = {
        "db_path": str(get_db_path()),
        "games": game_facts(),
        "tracked": [dict(r) for r in tracked_game_list(args.season)],
        "tag_coverage": tag_coverage(args.season),
        "lineup_coverage": lineup_coverage(args.season),
        "to_diagnostic": to_diagnostic(args.season),
    }
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
        return
    print(f"DB: {rep['db_path']}")
    print("\nGames by season/gender (n / tracked / finished):")
    for r in rep["games"]:
        print(f"  {r['season']:<12} {r['gender'] or '?'}  "
              f"{r['n']:>4} / {r['tracked'] or 0:>3} / {r['finished'] or 0:>4}")
    print(f"\nTracked games ({args.season}): {len(rep['tracked'])}")
    for g in rep["tracked"]:
        print(f"  {g['id']:>4} {g['date']} [{g['gender']}] {g['n1']} vs {g['n2']}"
              f"  {g['hs']}-{g['aws']}  ({g['ev']} events)")
    print("\nTag coverage:")
    for k, v in rep["tag_coverage"].items():
        print(f"  {k:<22} {v['n']:>5}/{v['of']:<5} {v['pct']}%")
    lc = rep["lineup_coverage"]
    print(f"\nLineup snapshots: {lc['full10']}/{lc['events']} full-10 "
          f"({lc['full10_pct']}%), {lc['partial']} partial, {lc['none']} none")
    td = rep["to_diagnostic"]
    print(f"\nTO diagnostic: {td['untyped']}/{td['turnovers']} untyped "
          f"({td['untyped_pct']}%)")
    print(f"  steal-TOs: {td['steal_tos']} ({td['steal_tos_typed']} typed) — "
          f"untyped w/ steal {td['untyped_with_steal']}, "
          f"untyped w/o steal {td['untyped_without_steal']}")
    print("  worst games (untyped/total):")
    for g in td["worst_games"]:
        print(f"    game {g['game_id']}: {g['untyped']}/{g['total']}")


if __name__ == "__main__":
    main()
