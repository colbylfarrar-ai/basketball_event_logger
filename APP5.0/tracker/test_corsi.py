"""
7d — Corsi (on-floor shot-attempt differential, helpers.stats.corsi_all). Reuses
the game_event_lineup snapshot the +/- plumbing already writes: for every shot
(make OR miss) a player is on the floor for, +1 CF if their team took it, +1 CA
if the opponent did. corsi = CF − CA; a lower-variance running mate to +/- that
rewards generating and suppressing ATTEMPTS, not just makes. No new capture.
Run: python tracker/test_corsi.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_corsi_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, execute              # noqa: E402
import helpers.game_events as GE                                  # noqa: E402
import helpers.stats as ST                                        # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


execute("INSERT INTO teams (id, name, class, gender) VALUES (1,'Home','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (2,'Away','3A','F')")
for pid in (101, 102, 103, 104, 105, 106):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)", (pid, f"H{pid}", pid))
for pid in (201, 202, 203, 204, 205):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,2,?,?)", (pid, f"A{pid}", pid))
G = execute("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-01')")

AWAY = [(201, 2), (202, 2), (203, 2), (204, 2), (205, 2)]
FLOOR_A = [(101, 1), (102, 1), (103, 1), (104, 1), (105, 1)] + AWAY   # 105 in
FLOOR_B = [(101, 1), (102, 1), (103, 1), (104, 1), (106, 1)] + AWAY   # 106 in


def shot(shooter, made, floor):
    return GE.log_event(G, {"event_type": "shot", "quarter": 1, "time": "5:00",
                            "primary_player_id": shooter,
                            "shot_result": "make" if made else "miss",
                            "shot_type": 2}, floor)


# 3 home attempts (2 make, 1 miss — Corsi counts ATTEMPTS) + 2 away, all FLOOR_A.
shot(101, True, FLOOR_A)
shot(102, False, FLOOR_A)
shot(103, True, FLOOR_A)
shot(201, True, FLOOR_A)
shot(202, False, FLOOR_A)
# one more away attempt with 106 in for 105.
shot(203, False, FLOOR_B)

c = ST.corsi_all([G])

# 101-104 are on BOTH floors -> on for all 6 attempts (3 home CF, 3 away CA);
# 105 only FLOOR_A (the first 5); 106 only FLOOR_B (the last away attempt).
print("attempts for/against split by who was on the floor")
ok(c[105]["cf"] == 3 and c[105]["ca"] == 2,
   f"105 (FLOOR_A only) on for 3 home + 2 away, got CF{c[105]['cf']}/CA{c[105]['ca']}")
ok(c[105]["corsi"] == 1, f"105 corsi = 3-2 = 1, got {c[105]['corsi']}")
ok(abs(c[105]["corsi_pct"] - 3 / 5) < 1e-9, f"105 corsi% = 3/5, got {c[105]['corsi_pct']}")

print("misses count too (attempts, not makes)")
# 101 on for all 6, including the two misses -> CF3/CA3, corsi 0
ok(c[101]["cf"] == 3 and c[101]["ca"] == 3, "a missed attempt still counts for Corsi")
ok(c[101]["corsi"] == 0, f"101 (on for all six) corsi = 0, got {c[101]['corsi']}")

print("a sub sees only the possessions they were on for")
ok(c[106]["cf"] == 0 and c[106]["ca"] == 1,
   f"106 on only for one away attempt, got CF{c[106]['cf']}/CA{c[106]['ca']}")
ok(c[106]["corsi"] == -1, f"106 corsi = -1, got {c[106]['corsi']}")

print("the away side mirrors: their FOR is the home team's AGAINST")
ok(c[201]["cf"] == 3 and c[201]["ca"] == 3,
   f"201 (on all six) 3 away CF + 3 home CA, got CF{c[201]['cf']}/CA{c[201]['ca']}")

print(f"\nALL {PASS} ASSERTS PASS")
