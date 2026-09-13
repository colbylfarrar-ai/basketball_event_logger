"""Every `games.date` is `YYYY-MM-DD`, so SQL may sort the picker.

`pages/2_Game_Tracker.py` used to order its game list in Python:

    sorted(all_games,
           key=lambda g: pd.to_datetime(g["date"], format="mixed", ...))

which is one date parse per row, with `format="mixed"` re-sniffing the format
every time. Profiled on the droplet, that was **13,383 calls and 1.96 seconds**
— on the page whose job is tracking one game.

It is now `ORDER BY g.date DESC` in the query that was already being run. That
substitution is only correct while every date in the book is ISO-shaped, because
ISO is the format whose lexical order IS its calendar order. `2026-1-5` sorts
after `2026-12-08`; `01/05/2026` sorts before everything.

So this file pins the invariant the optimisation rests on. If a future writer
(an importer, a hand edit, a new capture path) puts a non-ISO date in `games`,
this fails loudly — instead of the picker silently showing a coach the wrong
game at the top of the list on a night they are trying to start one.

Audited 2026-09-12 on the production book: 135 distinct dates, 135 ISO, none
malformed.

Run: python tracker/test_game_dates_iso.py
"""
import os
import re
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok  {label}")


def test_iso_sorts_like_a_calendar():
    """The property the query relies on, stated without touching the DB."""
    dates = ["2025-12-08", "2026-01-09", "2026-02-16", "2025-09-30"]
    ok(sorted(dates, reverse=True) == sorted(
        dates, key=lambda d: tuple(int(p) for p in d.split("-")), reverse=True),
       "ISO strings sort in calendar order lexically")
    # And the counterfactual, so the reason is on the record. February and
    # December: lexically "2026-2-05" > "2026-12-08" because "2" > "1" at the
    # month's first character, so a reverse sort puts February on top of a list
    # that claims to be newest-first.
    bad = ["2026-2-05", "2026-12-08"]
    ok(sorted(bad, reverse=True) == ["2026-2-05", "2026-12-08"],
       "an unpadded month sorts AHEAD of December — which is why this file exists")


def test_book_dates_are_iso():
    from database.db import query
    rows = query("SELECT DISTINCT date FROM games WHERE date IS NOT NULL")
    vals = [r["date"] for r in rows]
    bad = [v for v in vals if not ISO.match(str(v))]
    print(f"  .. {len(vals)} distinct dates in games")
    ok(not bad, f"every games.date is YYYY-MM-DD (offenders: {bad[:8]})")


def test_picker_query_orders_in_sql():
    """The page must not have quietly regained a Python sort."""
    lines = open(os.path.join(_APP, "pages", "2_Game_Tracker.py"),
                 encoding="utf-8").read().splitlines()
    ok(any("ORDER BY g.date DESC" in ln for ln in lines),
       "the game picker orders in SQL")
    # CODE only. The comment above that query quotes the old call on purpose,
    # so that the next reader knows what was removed and why — a scan that
    # cannot tell prose from code would force the fix to be undocumented.
    code = [ln for ln in lines if not ln.lstrip().startswith("#")]
    ok(not [ln for ln in code if 'format="mixed"' in ln or "format='mixed'" in ln],
       "no per-row pd.to_datetime(format='mixed') survives in this page's code")


if __name__ == "__main__":
    test_iso_sorts_like_a_calendar()
    test_book_dates_are_iso()
    test_picker_query_orders_in_sql()
    print(f"\n{PASSED} checks passed.")
