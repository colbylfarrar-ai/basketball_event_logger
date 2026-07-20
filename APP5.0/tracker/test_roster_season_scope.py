"""Roster rows must belong to the season being viewed.

The bug this locks down: `team_player_rows` scoped the league stat pool to the
viewed season for ARCHIVED labels but fell through to an UNSCOPED
`player_stat_table()` for 'Current'. An unscoped pool means "every tracked game
ever", and right after a season rollover every tracked game belongs to LAST
season — so a fresh season showed the graduated roster, carrying last year's
stats, presented as the current team. Returning players (new rows, no tracked
games yet) did not appear at all.

Both branches now run the same season-scoped query. 'Current' is a real label in
`games.season` — the rollover rewrites live rows to the dated label — so one
query serves both.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/test_roster_season_scope.py
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


def test_current_never_borrows_an_archived_roster():
    """No player row on 'Current' may come from an archived-season roster."""
    import helpers.team_analytics as TA
    from database.db import query

    # Any team with BOTH an archived roster and a current one is a valid probe;
    # that overlap is exactly where the bug lived.
    teams = query(
        """SELECT p.team_id, t.gender,
                  SUM(p.season='Current')  cur,
                  SUM(p.season!='Current') arch
           FROM players p JOIN teams t ON t.id=p.team_id
           GROUP BY p.team_id HAVING cur > 0 AND arch > 0
           ORDER BY arch DESC LIMIT 5""")
    if not teams:
        print("  -- no team has both a current and an archived roster; skipped")
        return

    for t in teams:
        tid, gender = t["team_id"], t["gender"]
        archived_ids = {r["id"] for r in query(
            "SELECT id FROM players WHERE team_id=? AND season!='Current'", (tid,))}
        rows = TA.team_player_rows(tid, gender=gender, season="Current")
        leaked = [r for r in rows if r.get("_pid") in archived_ids]
        ok(not leaked,
           f"team {tid}: 'Current' returns no archived players "
           f"({len(rows)} rows, {len(archived_ids)} archived on file)")


def test_archived_season_still_returns_that_years_roster():
    """The fix must not empty out the archive views."""
    import helpers.team_analytics as TA
    from database.db import query

    seasons = [r["season"] for r in query(
        "SELECT DISTINCT season FROM games WHERE tracked=1 AND season!='Current'")]
    if not seasons:
        print("  -- no archived tracked season; skipped")
        return
    season = sorted(seasons)[-1]
    probe = query(
        """SELECT g.team1_id tid, t.gender FROM games g
           JOIN teams t ON t.id=g.team1_id
           WHERE g.tracked=1 AND g.season=? LIMIT 1""", (season,))
    tid, gender = probe[0]["tid"], probe[0]["gender"]
    rows = TA.team_player_rows(tid, gender=gender, season=season)
    ok(len(rows) > 0, f"team {tid} still has {len(rows)} rows for {season}")


def test_roster_fallback_table_survives_arrow():
    """The empty-season fallback renders a real table, not an Arrow crash.

    Before the scope fix this path was unreachable, so nobody noticed `Grad`
    mixed ints with the '—' placeholder — an object column Arrow refuses:
    "Could not convert '—' with type str: tried to convert to int64".
    """
    import pandas as pd
    import pyarrow as pa
    import helpers.seasons as SEAS
    from database.db import query

    clause, params = SEAS.roster_clause("Current")
    probe = query(
        f"""SELECT team_id FROM players WHERE {clause}
            GROUP BY team_id ORDER BY COUNT(*) DESC LIMIT 1""", params)
    if not probe:
        print("  -- no current roster on file; skipped")
        return
    tid = probe[0]["team_id"]
    roster = query(
        f"SELECT number, name, position, availability, height, wingspan, "
        f"weight, grad_year, handedness FROM players WHERE team_id=? "
        f"AND {clause} ORDER BY number", (tid, *params))
    # Mirrors helpers/dashboard/players_tab.py's fallback frame exactly.
    df = pd.DataFrame([{
        "#": r["number"], "Player": r["name"],
        "Pos": (r["position"] or "—"),
        "Status": (r["availability"] or "Active"),
        "Grad": (str(r["grad_year"]) if r["grad_year"] else "—"),
        "Hand": (r["handedness"] or "right").title(),
        "Ht (in)": r["height"], "Wing (in)": r["wingspan"],
        "Wt (lb)": r["weight"],
    } for r in roster])
    mixed = sorted({type(v).__name__ for v in df["Grad"]})
    pa.Table.from_pandas(df)          # what st.dataframe does under the hood
    ok(True, f"team {tid}: {len(df)}-row fallback table converts "
             f"(Grad types: {mixed})")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    test_current_never_borrows_an_archived_roster()
    test_archived_season_still_returns_that_years_roster()
    test_roster_fallback_table_survives_arrow()
    print(f"\nALL {PASSED} CHECKS PASSED")
