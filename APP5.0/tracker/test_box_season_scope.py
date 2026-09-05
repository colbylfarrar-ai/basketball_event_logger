"""Box scores must list a player once — the roster read is season-scoped.

`players` holds one row per season a player was rostered (the rollover gives a
returning player a brand-new id). `_build_boxes` and the DNP list under the box
tab both read `WHERE team_id IN (?,?)` with no season clause, so a returning
player came back once per season she had ever been on the roster and appeared
twice in the box — worst on a PAST-season box, where the active-season row is
always an extra beyond the ones that actually played.

Both reads now go through `seasons.roster_clause(game.season)`, the same
invariant the tracker's pickers and the event log already use.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/test_box_season_scope.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def test_clause_picks_the_games_own_season():
    """roster_clause on a past season selects that season's rows, not 'Current'."""
    import helpers.seasons as SEAS
    from database.db import query

    seasons = [r["season"] for r in query(
        "SELECT DISTINCT season FROM players ORDER BY season")]
    if len(seasons) < 2:
        print("  -- only one season on file; scope test skipped")
        return

    past = [s for s in seasons if not SEAS.is_current(s)]
    for label in past[:2]:
        clause, params = SEAS.roster_clause(label, alias="p")
        rows = query(
            f"SELECT p.id, p.season FROM players p WHERE {clause}", params)
        ok(rows and all(r["season"] == label for r in rows),
           f"roster_clause('{label}') returns only {label} rows ({len(rows)})")

    clause, params = SEAS.roster_clause(SEAS.ACTIVE, alias="p")
    ok(clause == "p.archived=0" and params == (),
       "roster_clause('Current') is unchanged live behaviour (archived=0)")


def test_no_duplicate_players_in_a_box():
    """Every tracked game's box lists each roster player at most once."""
    import helpers.box_score as BS
    from database.db import query

    games = query(
        """SELECT g.id, g.season, g.team1_id h, g.team2_id a
           FROM games g WHERE g.tracked=1 ORDER BY g.id DESC LIMIT 8""")
    if not games:
        print("  -- no tracked games on file; box test skipped")
        return

    for g in games:
        boxes, _pts, _q = BS._build_boxes(g["id"], g["h"], g["a"])
        keys = [(b["team_id"], b["number"], b["name"]) for b in boxes.values()]
        dupes = {k for k in keys if keys.count(k) > 1}
        ok(not dupes, f"game {g['id']} ({g['season']}): no repeated player "
                      f"({len(keys)} box rows)")

        # and every listed player really belongs to that game's season
        seasons = {r["season"] for r in query(
            "SELECT DISTINCT season FROM players WHERE id IN (%s)"
            % ",".join("?" * len(boxes)), tuple(boxes))} if boxes else set()
        ok(len(seasons) <= 1,
           f"game {g['id']}: box rows come from one season {sorted(seasons)}")


def test_the_bug_is_reproducible_unscoped():
    """Pin the old behaviour: an unscoped read really does double the roster."""
    from database.db import query

    probe = query(
        """SELECT team_id, SUM(season='Current') cur, SUM(season!='Current') arch
           FROM players GROUP BY team_id HAVING cur>0 AND arch>0 LIMIT 1""")
    if not probe:
        print("  -- no team carries both a current and an archived roster; "
              "regression probe skipped")
        return

    tid = probe[0]["team_id"]
    unscoped = query(
        "SELECT name FROM players WHERE team_id=?", (tid,))
    names = [r["name"] for r in unscoped]
    repeated = {n for n in names if names.count(n) > 1}
    ok(repeated,
       f"team {tid}: unscoped read repeats {len(repeated)} name(s) — the bug")


if __name__ == "__main__":
    print("box season scope")
    test_clause_picks_the_games_own_season()
    test_no_duplicate_players_in_a_box()
    test_the_bug_is_reproducible_unscoped()
    print(f"\n{PASSED} checks passed")
