"""Weekly awards digest engine (backlog item 26b) — pure composition on
synthetic rows. Script-style: run directly (python tracker/test_awards.py).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_awards_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.awards as AW

FAILS = []


def check(label, cond, detail=""):
    print(("PASS" if cond else "FAIL"), label, detail if not cond else "")
    if not cond:
        FAILS.append(label)


# anchor = 2026-02-10; window = 02-04..02-10. Game 3 (01-20) is OUT of window.
games = [
    {"id": 1, "date": "2026-02-10", "tracked": 1, "n1": "A", "n2": "B",
     "home_score": 50, "away_score": 48},
    {"id": 2, "date": "2026-02-05", "tracked": 1, "n1": "A", "n2": "C",
     "home_score": 60, "away_score": 40},
    {"id": 3, "date": "2026-01-20", "tracked": 1, "n1": "B", "n2": "C",
     "home_score": 70, "away_score": 30},
]
# Game-score fuel: PTS/FGM/FGA drive stats.game_score
box = lambda pts: {"PTS": pts, "FGM": pts // 2, "FGA": pts // 2, "FTM": 0,
                   "FTA": 0, "ORB": 0, "DRB": 2, "AST": 1, "STL": 0, "BLK": 0,
                   "PF": 0, "TOV": 0}
boxes = {
    10: {1: box(30), 2: box(20)},        # 2 window games — the week's body of work
    11: {1: box(40)},                    # one big night
    12: {3: box(60)},                    # monster night OUTSIDE the window
    99: {1: box(50)},                    # no meta -> ignored
}
meta = {10: {"name": "Jane", "number": 12, "team": "A"},
        11: {"name": "Kate", "number": 23, "team": "B"},
        12: {"name": "Old", "number": 5, "team": "C"}}

aw = AW.compose_awards(games, boxes, meta,
                       gei_fn=lambda g: {1: 8.5, 2: 3.0}.get(g["id"]),
                       riser=("Adair Girls", 4, 2.3))
check("window anchors on latest date", aw["window"] == ("2026-02-04", "2026-02-10"),
      aw["window"])
check("player of week = best WEEK sum (Jane, 2 games)",
      aw["player"]["name"] == "Jane" and aw["player"]["gp"] == 2, aw["player"])
check("out-of-window monster ignored", aw["player"]["name"] != "Old")
check("meta-less player ignored", aw["player"]["pid"] != 99)
check("player pts totalled", aw["player"]["pts"] == 50)
check("game of week = highest GEI", aw["game"]["gid"] == 1
      and aw["game"]["gei"] == 8.5, aw["game"])
check("riser carried", aw["riser"] == {"team": "Adair Girls", "d_rank": 4,
                                       "d_rating": 2.3})

# no games at all -> None
check("empty pool -> None", AW.compose_awards([], {}, {}) is None)

# undated games only -> None
check("undated pool -> None",
      AW.compose_awards([{"id": 9, "date": None, "tracked": 0, "n1": "A",
                          "n2": "B", "home_score": 1, "away_score": 0}],
                        {}, {}) is None)

# no tracked boxes in window -> player None, dict still returned
aw2 = AW.compose_awards(games, {}, meta, gei_fn=lambda g: None)
check("no boxes -> player None", aw2["player"] is None)
check("no gei -> game None", aw2["game"] is None)
check("no riser -> None", aw2["riser"] is None)

# gei_fn raising never breaks the digest
def _boom(g):
    raise RuntimeError("nope")
aw3 = AW.compose_awards(games, boxes, meta, gei_fn=_boom)
check("gei exception swallowed", aw3["game"] is None and aw3["player"] is not None)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:", *FAILS, sep="\n  ")
    sys.exit(1)
print("test_awards: ALL PASS")
