"""
repair_book.py — report (and optionally fix) the data slips found in a live book.

Reports by default and CHANGES NOTHING. Pass --apply to act. Run the report,
read it, then decide — every check below found something real in the 2026-09-05
book, but which row survives a de-dup is a judgement about someone's season, not
a migration's call.

    python tools/repair_book.py                 # report only
    python tools/repair_book.py --apply         # act
    python tools/repair_book.py --only dups     # one check
    APP5_DATA_DIR=... python tools/repair_book.py   # against a snapshot

Checks:

  tracked   Games that carry events but are not flagged tracked=1. Their events
            are invisible to every tracked pool, rating and insight. Found one on
            2026-09-05: game 4 (2025-12-10, Adair, Tournament) with 61 events —
            an old desktop-path game that never got its finish call.

  dups      The same real game sitting in `games` twice. Found nine, all
            untracked, all carrying a score, so BOTH rows fed the results-only
            power ratings and every one of those results counted twice in W/L,
            SOS and Rating. Root cause was ossaa_sync.merge_teams (fixed
            2026-09-05); these are the rows it already made. Survivor rule and
            the refusal to touch a row with events live in
            game_dedup.collapse_result_duplicates.

  jersey    Two ACTIVE players on one team wearing one number in one season.
            REPORT-ONLY, always — which of the two is wrong is a roster question
            with a human answer, and renumbering the wrong one is worse than
            leaving it. Found one: team 1 #4, Carly Buell (257) and Rylee Brown
            (424).

  selffoul  An event whose primary and secondary player are the same person — a
            charge where one player both drew it and committed it. REPORT-ONLY:
            fix these in the Event Editor, where you can see the neighbouring
            rows. Found one: game_events.id 7101 (game 14123, Q1 0:01, player
            509), which is what fails test_charges.py::test_real_book_encoding.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import query, execute, initialize_database   # noqa: E402
import helpers.game_dedup as GD                               # noqa: E402

CHECKS = ("tracked", "dups", "jersey", "selffoul")


def _p(s=""):
    # this console is cp1252; a team name can carry anything
    print(str(s).encode("ascii", "replace").decode("ascii"))


def check_tracked(apply_it):
    rows = query("""SELECT g.id, g.date, g.season, COUNT(e.id) n
                    FROM games g JOIN game_events e ON e.game_id = g.id
                    WHERE g.tracked != 1 GROUP BY g.id ORDER BY g.date""")
    _p(f"\n== events but tracked=0 ==  ({len(rows)} found)")
    for r in rows:
        _p(f"   game {r['id']}  {r['date']}  {r['season']}  {r['n']} events")
    if rows and apply_it:
        for r in rows:
            execute("UPDATE games SET tracked=1 WHERE id=?", (r["id"],))
        _p(f"   APPLIED: flagged {len(rows)} game(s) tracked=1")
    elif rows:
        _p("   (--apply would set tracked=1 on these)")
    return len(rows)


def check_dups(apply_it):
    groups = GD.result_duplicate_groups()
    _p(f"\n== duplicate game rows ==  ({len(groups)} matchups)")
    names = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}
    for g in groups:
        r0 = g["rows"][0]
        _p(f"   {g['date']}  {names.get(r0['team1_id'], r0['team1_id'])} vs "
           f"{names.get(r0['team2_id'], r0['team2_id'])}")
        for r in g["rows"]:
            tag = "KEEP" if r["id"] == g["keep"] else "drop"
            _p(f"      {tag}  id={r['id']:<6d} tracked={int(r['tracked'])} "
               f"events={r['events']:<4d} score={r['home_score']}-{r['away_score']} "
               f"loc='{r['location']}'")
    if groups and apply_it:
        res = GD.collapse_result_duplicates()
        _p(f"   APPLIED: collapsed {res['groups']} group(s); "
           f"deleted {res['deleted']}")
        if res["refused"]:
            _p(f"   REFUSED (carry events — resolve in Settings > duplicates): "
               f"{res['refused']}")
    elif groups:
        _p("   (--apply would delete every row marked 'drop')")
    return len(groups)


def check_jersey(apply_it):
    rows = query("""SELECT p.team_id, p.number, p.season, COUNT(*) c,
                           GROUP_CONCAT(p.name || ' (' || p.id || ')', ' + ') who
                    FROM players p WHERE p.archived = 0
                    GROUP BY p.team_id, p.number, p.season HAVING c > 1""")
    _p(f"\n== two active players on one number ==  ({len(rows)} found)")
    for r in rows:
        _p(f"   team {r['team_id']}  #{r['number']}  {r['season']}:  {r['who']}")
    if rows:
        _p("   REPORT-ONLY — fix on the roster; which one is wrong is a human call.")
    return len(rows)


def check_selffoul(apply_it):
    rows = query("""SELECT e.id, e.game_id, e.quarter, e.time, e.event_type,
                           e.primary_player_id pid, g.date
                    FROM game_events e JOIN games g ON g.id = e.game_id
                    WHERE e.secondary_player_id = e.primary_player_id""")
    _p(f"\n== event with the same player in both slots ==  ({len(rows)} found)")
    for r in rows:
        _p(f"   event {r['id']}  game {r['game_id']} ({r['date']})  "
           f"Q{r['quarter']} {r['time']}  {r['event_type']}  player {r['pid']}")
    if rows:
        _p("   REPORT-ONLY — fix in the Event Editor, where the neighbouring "
           "rows are visible.")
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--apply", action="store_true",
                    help="actually change the book (default: report only)")
    ap.add_argument("--only", choices=CHECKS, help="run one check")
    a = ap.parse_args()

    initialize_database()
    db = query("SELECT COUNT(*) c FROM games")[0]["c"]
    _p(f"book: {db} games   mode: {'APPLY' if a.apply else 'REPORT ONLY'}")

    run = [a.only] if a.only else list(CHECKS)
    found = 0
    for name in run:
        found += {"tracked": check_tracked, "dups": check_dups,
                  "jersey": check_jersey, "selffoul": check_selffoul}[name](a.apply)
    _p(f"\n{found} finding(s).")
    if found and not a.apply:
        _p("Re-run with --apply to act on the fixable ones "
           "(tracked, dups). Back the book up first.")


if __name__ == "__main__":
    main()
