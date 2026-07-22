"""
7a — expected assists (helpers.stats.expected_assists). The ball-movement answer
coaches asked for: value a completed feed by the SHOT QUALITY it created, not
whether the teammate finished, so a great passer on a cold night still reads well.

Derivable, no schema: each fed shot (pass_from_id) is scored by the league make-
rate for its (zone, creation, contested?) bucket.
  xA     = Σ make-rate over the passer's feeds   (expected assist COUNT)
  xA_pts = Σ make-rate * shot value              (expected assist POINTS)
  AST    = the feeds that actually dropped        (AST - xA = finishing luck)

The test builds a bucket with a KNOWN make-rate (0.5) so xA is exact, and pins
the cold-night property: a passer whose feeds all missed still earns xA > 0.
Run: python tracker/test_expected_assists.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_xa_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, query, execute      # noqa: E402
import helpers.stats as ST                                        # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


execute("INSERT INTO teams (id, name, class, gender) VALUES (1,'Home','3A','F')")
for pid in (101, 102, 103, 104, 105):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)", (pid, f"H{pid}", pid))
G = execute("INSERT INTO games (team1_id, team2_id, date) VALUES (1,1,'2026-01-01')")


def shot(shooter, made, pass_from):
    # all shots share one bucket: zone C, pass-created, uncontested, 2PT — so the
    # empirical make-rate for that bucket is exactly makes/total.
    execute(
        "INSERT INTO game_events (game_id, event_type, quarter, time, "
        "primary_player_id, shot_result, shot_type, zone, pass_from_id) "
        "VALUES (?, 'shot', 1, '5:00', ?, ?, 2, 'C', ?)",
        (G, shooter, "make" if made else "miss", pass_from))


# Bucket (C, pass, uncontested): 4 shots, 2 make -> league make-rate = 0.5.
# 103 fed the two MAKES; 101 fed the two MISSES.
shot(102, True, pass_from=103)
shot(104, True, pass_from=103)
shot(105, False, pass_from=101)
shot(102, False, pass_from=101)

ea = ST.expected_assists([G])

print("xA scores the LOOK, independent of whether it dropped")
ok(ea[101]["feeds"] == 2, f"101 fed 2 shots, got {ea[101]['feeds']}")
ok(ea[101]["AST"] == 0, f"101's feeds both missed -> 0 actual assists, got {ea[101]['AST']}")
ok(abs(ea[101]["xA"] - 1.0) < 1e-9, f"101 xA = 2 feeds * 0.5 rate = 1.0, got {ea[101]['xA']}")
ok(abs(ea[101]["xA_pts"] - 2.0) < 1e-9, f"101 xA_pts = 2 * 0.5 * 2pts = 2.0, got {ea[101]['xA_pts']}")
ok(ea[101]["xA"] > ea[101]["AST"], "cold-night: xA > actual assists when shooters miss")

print("finishing luck: AST - xA reads over/under conversion")
ok(ea[103]["AST"] == 2, f"103's feeds both made -> 2 assists, got {ea[103]['AST']}")
ok(abs(ea[103]["xA"] - 1.0) < 1e-9, f"103 xA = 1.0 (same bucket), got {ea[103]['xA']}")
ok(ea[103]["AST"] - ea[103]["xA"] > 0, "103's shooters over-converted (AST - xA > 0)")

print("min_feeds gate omits noisy passers")
ea2 = ST.expected_assists([G], min_feeds=3)
ok(101 not in ea2 and 103 not in ea2, "passers under min_feeds dropped")

print(f"\nALL {PASS} ASSERTS PASS")
