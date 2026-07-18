"""Officials crew-pairs engine (backlog item 22) — synthetic officials/games
through ref_tendencies.crew_pairs with injected primitives (no DB).
Script-style: run directly (python tracker/test_crew_pairs.py).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_crew_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.ref_tendencies as RT

FAILS = []


def check(label, cond, detail=""):
    print(("PASS" if cond else "FAIL"), label, detail if not cond else "")
    if not cond:
        FAILS.append(label)


# 6 games: refs A(1),B(2) work all six; C(3) joins games 1-3 (a trio there).
games_map = {g: {"team1_id": 10, "team2_id": 20,
                 "home_score": 50, "away_score": 40} for g in range(1, 7)}
worked = {1: set(range(1, 7)), 2: set(range(1, 7)), 3: {1, 2, 3}}
names = {1: "Ref A", 2: "Ref B", 3: "Ref C"}
poss = {g: 100 for g in range(1, 7)}
# per game: 10 fouls — 6 on the HOME team (team 10), 4 away; 3 in Q4
fouls = []
for g in range(1, 7):
    for i in range(6):
        fouls.append({"game_id": g, "quarter": 4 if i < 3 else 1,
                      "off_pk": 1, "fouler_team": 10})
    for i in range(4):
        fouls.append({"game_id": g, "quarter": 1, "off_pk": 2,
                      "fouler_team": 20})

cp = RT.crew_pairs(games_map=games_map, worked=worked, fouls=fouls,
                   poss=poss, names=names, min_games=5)
rows = cp["rows"]
check("only the A+B pair clears n>=5", len(rows) == 1, rows)
r = rows[0]
check("pair label", r["label"] == "Ref A + Ref B")
check("games together", r["games"] == 6)
check("fouls/game = 10", r["fpg"] == 10.0)
check("home lean +20%", r["lean_pct"] == 20.0, r["lean_pct"])
check("PPP 0.9", r["ppp"] == 0.9)
check("q4 share 30%", r["q4_share"] == 30.0)
check("league fpg 10", cp["league_fpg"] == 10.0)

# lower the gate → trio + the C pairs appear
cp2 = RT.crew_pairs(games_map=games_map, worked=worked, fouls=fouls,
                    poss=poss, names=names, min_games=3)
kinds = {(x["kind"], x["label"]): x for x in cp2["rows"]}
check("trio surfaces at min 3",
      ("crew", "Ref A + Ref B + Ref C") in kinds, list(kinds))
check("A+C pair surfaces", ("pair", "Ref A + Ref C") in kinds)
_trio = kinds[("crew", "Ref A + Ref B + Ref C")]
check("trio counts its 3 games", _trio["games"] == 3)
check("sorted most-games-first",
      [x["games"] for x in cp2["rows"]]
      == sorted([x["games"] for x in cp2["rows"]], reverse=True))

# unknown refs (no name row) never form combos
worked2 = dict(worked); worked2[99] = set(range(1, 7))
cp3 = RT.crew_pairs(games_map=games_map, worked=worked2, fouls=fouls,
                    poss=poss, names=names, min_games=5)
check("nameless ref excluded", all("99" not in x["label"] for x in cp3["rows"]))

# scoreless game drops from PPP but not from games/fouls
games_map[6] = {"team1_id": 10, "team2_id": 20,
                "home_score": None, "away_score": None}
cp4 = RT.crew_pairs(games_map=games_map, worked=worked, fouls=fouls,
                    poss=poss, names=names, min_games=5)
r4 = cp4["rows"][0]
check("scoreless game still counts toward GP", r4["games"] == 6)
check("PPP pools only score-carrying games",
      r4["ppp"] == round(450 / 500, 3), r4["ppp"])

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:", *FAILS, sep="\n  ")
    sys.exit(1)
print("test_crew_pairs: ALL PASS")
