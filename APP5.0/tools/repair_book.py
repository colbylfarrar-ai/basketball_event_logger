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

  teams     One school in `teams` under two names, splitting its games between
            them. REPORT-ONLY, always. The merge itself already exists — it is
            `ossaa_sync.merge_teams`, exposed admin-only on the OSSAA Import
            page — and WHICH id survives is a decision about someone's season.

            The detector deliberately does NOT strip a parenthetical. On this
            book the parentheses are the disambiguator, not noise: "Central
            (Tulsa)" and "Central (Sallisaw)" are two schools, as are
            "Sequoyah (Tahlequah)" and "Sequoyah (Claremore)", and a matcher
            that folds them reports four confident false merges before it
            reports a true one. What it looks for instead is near-identical
            names within one gender — a doubled space, a dropped comma, a
            misspelling ("South Western Hieghts", "OKC Knighrs", "Candy
            Valley"), or the same school with and without a state suffix.

            It still cannot tell a real second team from a duplicate. "Bridge
            Creek" and "Bridge Creek J.V." score 0.917 and are two teams. Read
            every row before acting on any of them.

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
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import query, execute, initialize_database   # noqa: E402
import helpers.game_dedup as GD                               # noqa: E402

CHECKS = ("tracked", "dups", "teams", "jersey", "selffoul")


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


#: How alike two names have to be, within one gender, to be worth a human look.
#: Tuned on the production book: 0.90 surfaces the doubled space, the dropped
#: comma and the three misspellings; below it the list fills with real schools
#: that share a town name.
TEAM_NAME_RATIO = 0.90


def _team_key(name):
    """A team name reduced for comparison — case, punctuation and the
    Boys/Girls suffix removed, and NOTHING else. The parenthetical stays: on
    this book it is what tells two schools apart."""
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"\s+(boys|girls)$", "", s, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def check_teams(apply_it):
    from difflib import SequenceMatcher
    rows = query("""SELECT t.id, t.name, t.gender,
                           (SELECT COUNT(*) FROM games g
                             WHERE g.team1_id = t.id OR g.team2_id = t.id) gp
                    FROM teams t""")
    by_gender = {}
    for r in rows:
        by_gender.setdefault(r["gender"], []).append(r)

    pairs = []
    for gender, ts in by_gender.items():
        ts = sorted(ts, key=lambda t: _team_key(t["name"]))
        for i, a in enumerate(ts):
            ka = _team_key(a["name"])
            # sorted by key, so a near-match is a near neighbour; the window
            # keeps this off O(n^2) on a 1,448-team book
            for b in ts[i + 1:i + 12]:
                kb = _team_key(b["name"])
                if ka == kb:
                    pairs.append((1.0, a, b))
                    continue
                if abs(len(ka) - len(kb)) > 3:
                    continue
                ratio = SequenceMatcher(None, ka, kb).ratio()
                if ratio >= TEAM_NAME_RATIO:
                    pairs.append((round(ratio, 3), a, b))
    pairs.sort(key=lambda p: -p[0])

    _p(f"\n== one school under two names ==  ({len(pairs)} pairs to read)")
    for ratio, a, b in pairs:
        _p(f"   {ratio:<5}  {a['gender']}  "
           f"[{a['id']}] {a['name']} ({a['gp']} games)  <->  "
           f"[{b['id']}] {b['name']} ({b['gp']} games)")
    if pairs:
        _p(f"   split across these pairs: "
           f"{sum(a['gp'] + b['gp'] for _r, a, b in pairs)} team-games")
        _p("   REPORT-ONLY - merge on the OSSAA Import page (admin), which is "
           "where merge_teams lives. Not every pair is a duplicate: a J.V. "
           "team and a second school in the same town both score high here.")
    return len(pairs)


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
                  "teams": check_teams, "jersey": check_jersey,
                  "selffoul": check_selffoul}[name](a.apply)
    _p(f"\n{found} finding(s).")
    if found and not a.apply:
        _p("Re-run with --apply to act on the fixable ones "
           "(tracked, dups). Back the book up first.")


if __name__ == "__main__":
    main()
