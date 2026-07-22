"""
7e — steal-forced vs unforced turnover split (helpers.defenses
.team_turnover_forced_split). FREE, no schema: derived from stolen_by_id.

steal-forced = a steal was logged on the turnover; unforced = none. It's a
FLOOR (a pressured giveaway with no steal reads unforced), so the test pins the
honest orientation both ways:
  * offense=True  -> the team's OWN turnovers, split by whether the defense stole it.
  * offense=False -> turnovers the team's defense CAUSED, split by steal vs not.
Run: python tracker/test_forced_turnovers.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_ftov_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, query, execute      # noqa: E402
import helpers.game_events as GE                                  # noqa: E402
import helpers.defenses as D                                      # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


execute("INSERT INTO teams (id, name, class, gender) VALUES (1,'Home','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (2,'Away','3A','F')")
for pid in (101, 102, 103, 104, 105):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)", (pid, f"H{pid}", pid))
for pid in (201, 202, 203, 204, 205):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,2,?,?)", (pid, f"A{pid}", pid))
G = execute("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-01')")
FLOOR = [(101, 1), (102, 1), (103, 1), (104, 1), (105, 1),
         (201, 2), (202, 2), (203, 2), (204, 2), (205, 2)]


def tov(committer, stolen_by=None, defense=None):
    ev = {"event_type": "turnover", "quarter": 1, "time": "5:00",
          "primary_player_id": committer, "stolen_by_id": stolen_by,
          "defense": defense}
    return GE.log_event(G, ev, FLOOR)


# HOME commits 3 turnovers: 2 stolen (by away 201/202), 1 unforced (dead-ball).
# Defense tags = the AWAY scheme home faced (per-scheme split feeds §G's card).
tov(101, stolen_by=201, defense="man_press")
tov(102, stolen_by=202, defense="zone_23")
tov(103, stolen_by=None, defense="man_press")
# AWAY commits 2 turnovers: 1 stolen (by home 101, under home's man), 1 unforced
# and UNTAGGED (drops out of the per-scheme rows, still counts in the flat split).
tov(201, stolen_by=101, defense="man")
tov(202, stolen_by=None)

print("offense=True -> the team's OWN turnovers, split by steal")
h = D.team_turnover_forced_split(1, game_ids=[G], offense=True)
ok(h["total"] == 3, f"home committed 3 TOs, got {h['total']}")
ok(h["forced"] == 2 and h["unforced"] == 1,
   f"2 stolen off home / 1 unforced, got {h['forced']}/{h['unforced']}")
ok(abs(h["forced_pct"] - 2 / 3) < 1e-9, f"steal-forced% = 2/3, got {h['forced_pct']}")

print("offense=False -> turnovers the team's DEFENSE forced")
hd = D.team_turnover_forced_split(1, game_ids=[G], offense=False)
ok(hd["total"] == 2, f"home defense faced 2 away TOs, got {hd['total']}")
ok(hd["forced"] == 1 and hd["unforced"] == 1,
   f"home stole 1 / 1 away unforced, got {hd['forced']}/{hd['unforced']}")

print("floor semantics: a no-steal turnover never counts as forced")
ok(h["forced"] + h["unforced"] == h["total"], "forced + unforced == total (no double count)")

print("empty pool -> forced_pct is None, not a divide-by-zero")
empty = D.team_turnover_forced_split(1, game_ids=[], offense=True)
ok(empty["total"] == 0 and empty["forced_pct"] is None, "empty pool safe")

print("8a: per-scheme rows carry the steal-forced/unforced split (stacked card)")
pv = D.team_defense_turnovers(1, game_ids=[G], offense=True)
prow = {r["key"]: r for r in pv["rows"]}
ok(set(prow) == {"man_press", "zone_23"},
   f"home's tagged TOs sit under 2 schemes, got {sorted(prow)}")
ok(prow["man_press"]["tovs"] == 2 and prow["man_press"]["forced"] == 1
   and prow["man_press"]["unforced"] == 1,
   f"man_press = 1 stolen + 1 unforced, got {prow['man_press']}")
ok(prow["zone_23"]["forced"] == 1 and prow["zone_23"]["unforced"] == 0,
   f"zone_23 = 1 stolen / 0 unforced, got {prow['zone_23']}")
ok(all(r["forced"] + r["unforced"] == r["tovs"] for r in pv["rows"]),
   "per-scheme forced + unforced == tovs (stack sums to the old bar)")

dv = D.team_defense_turnovers(1, game_ids=[G], offense=False)
drow = {r["key"]: r for r in dv["rows"]}
ok(set(drow) == {"man"} and drow["man"]["forced"] == 1
   and drow["man"]["unforced"] == 0,
   f"home defense forced 1 steal-TO under man (untagged TO excluded), got {drow}")

print(f"\nALL {PASS} ASSERTS PASS")
