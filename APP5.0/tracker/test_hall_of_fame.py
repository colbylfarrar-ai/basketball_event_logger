"""Hall of Fame engines (backlog item 20) — single-game records + records
watch on synthetic boxes. Pure-engine test, no DB needed (throwaway data dir
set anyway to keep the standard pattern safe on import).
Script-style: run directly (python tracker/test_hall_of_fame.py).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_hof_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.hall_of_fame as HOF

FAILS = []


def check(label, cond, detail=""):
    print(("PASS" if cond else "FAIL"), label, detail if not cond else "")
    if not cond:
        FAILS.append(label)


# ── single_game_records ──────────────────────────────────────────────────────
boxes = {
    1: {101: {"PTS": 30, "TRB": 5, "AST": 2, "STL": 1, "BLK": 0},
        102: {"PTS": 42, "TRB": 8, "AST": 4, "STL": 3, "BLK": 1}},
    2: {101: {"PTS": 12, "TRB": 15, "AST": 9, "STL": 0, "BLK": 4},
        103: {"PTS": 42, "TRB": 3, "AST": 1, "STL": 2, "BLK": 0}},
    3: {103: {"PTS": 8, "TRB": 2, "AST": 11, "STL": 5, "BLK": 0}},
    99: {101: {"PTS": 50, "TRB": 20, "AST": 20, "STL": 9, "BLK": 9}},  # no meta
}
meta = {1: {"name": "Jane", "number": 12, "team": "A"},
        2: {"name": "Kate", "number": 23, "team": "B"},
        3: {"name": "Amy", "number": 3, "team": "A"}}
games = {101: {"date": "2025-12-01", "matchup": "A vs B", "season": "2025-2026"},
         102: {"date": "2026-01-10", "matchup": "A vs C", "season": "2025-2026"},
         103: {"date": "2024-12-05", "matchup": "B vs C", "season": "2024-2025"}}

rec = HOF.single_game_records(boxes, meta, games, top_n=3)
check("PTS board sizes to top_n", len(rec["PTS"]) == 3, rec["PTS"])
check("42-point tie breaks to OLDER date first",
      rec["PTS"][0]["name"] == "Kate" and rec["PTS"][0]["date"] == "2024-12-05",
      rec["PTS"][:2])
check("second 42 is Jane", rec["PTS"][1]["name"] == "Jane")
check("meta-less player excluded",
      all(r["pid"] != 99 for s in rec for r in rec[s]))
check("TRB top is Kate 15", rec["TRB"][0]["value"] == 15
      and rec["TRB"][0]["name"] == "Kate")
check("AST top is Amy 11", rec["AST"][0]["value"] == 11
      and rec["AST"][0]["name"] == "Amy")
check("zero-stat games dropped", all(r["value"] > 0 for r in rec["BLK"]))
check("matchup label carried", rec["PTS"][1]["matchup"] == "A vs C")

# ── records_watch ────────────────────────────────────────────────────────────
# Board (PTS, top_n=3): Vet1 500, Vet2 400, Vet3 300. Active chaser at 290,
# 29 gp -> pace 10/gm, needs 11 to pass 300 -> 1.1 games. On watch.
careers = {
    "v1": {"name": "Vet1", "team": "A", "gp": 50, "active": False,
           "PTS": 500, "TRB": 100, "AST": 50},
    "v2": {"name": "Vet2", "team": "B", "gp": 50, "active": False,
           "PTS": 400, "TRB": 90, "AST": 40},
    "v3": {"name": "Vet3", "team": "C", "gp": 50, "active": False,
           "PTS": 300, "TRB": 80, "AST": 30},
    "chase": {"name": "Chaser", "team": "A", "gp": 29, "active": True,
              "PTS": 290, "TRB": 10, "AST": 5},
    "slow": {"name": "Slow", "team": "B", "gp": 40, "active": True,
             "PTS": 100, "TRB": 12, "AST": 6},
    "fresh": {"name": "Fresh", "team": "C", "gp": 2, "active": True,
              "PTS": 60, "TRB": 8, "AST": 4},   # pace unreliable (< min_gp)
}
w = HOF.records_watch(careers, stats=("PTS",), top_n=3, horizon_games=5)
check("chaser on watch", any(x["name"] == "Chaser" for x in w), w)
_c = next(x for x in w if x["name"] == "Chaser")
check("chaser targets Vet3 rung", _c["target"] == 300
      and _c["target_holder"] == "Vet3")
check("chaser would ENTER the board", _c["entering"] is True)
check("chaser needs 11", _c["need"] == 11)
check("slow chaser off watch (too far at pace)",
      all(x["name"] != "Slow" for x in w))
check("min_gp guard (Fresh excluded)", all(x["name"] != "Fresh" for x in w))
check("inactive vets never on watch", all(x["name"] not in
      ("Vet1", "Vet2", "Vet3") for x in w))

# climbing case: active player ALREADY on the board chasing the next rung
careers["v3"]["active"] = True
careers["v3"]["gp"] = 30            # pace 10/gm, needs 101 to pass 400 -> off
w2 = HOF.records_watch(careers, stats=("PTS",), top_n=3, horizon_games=5)
check("board climber beyond horizon stays off",
      all(x["name"] != "Vet3" for x in w2))
careers["v3"]["PTS"] = 396          # pace 13.2, needs 5 -> ~0.4 games
w3 = HOF.records_watch(careers, stats=("PTS",), top_n=3, horizon_games=5)
_v3 = [x for x in w3 if x["name"] == "Vet3"]
check("board climber inside horizon on watch", len(_v3) == 1, w3)
check("climber flagged as climbing (not entering)",
      _v3 and _v3[0]["entering"] is False)
check("soonest-first ordering",
      [x["games_needed"] for x in w3] == sorted(x["games_needed"] for x in w3))

# top-line holder has nobody above -> never on watch
careers["top"] = {"name": "Top", "team": "A", "gp": 20, "active": True,
                  "PTS": 600, "TRB": 5, "AST": 2}
w4 = HOF.records_watch(careers, stats=("PTS",), top_n=3, horizon_games=5)
check("record holder skipped", all(x["name"] != "Top" for x in w4))

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:", *FAILS, sep="\n  ")
    sys.exit(1)
print("test_hall_of_fame: ALL PASS")
