"""
Test for the live_state tag-coverage block (helpers/game_events.py) against a
THROWAWAY DB. Pins the PWA nudge's numbers:
  * play_type coverage counts SHOTS only (tagged/total/pct),
  * defense coverage counts shots + turnovers,
  * empty tags ('' or NULL) are untagged,
  * a game with no events reports totals 0 and pct None.
Run: python tracker/test_live_coverage.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_livecov_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute          # noqa: E402
import helpers.game_events as GE         # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


A = execute("INSERT INTO teams (name,class,gender) VALUES ('CovA','3A','F')")
B = execute("INSERT INTO teams (name,class,gender) VALUES ('CovB','3A','F')")
p1 = execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)", (A, "P1", 1))
g = execute("INSERT INTO games (team1_id,team2_id,date,tracked,season) "
            "VALUES (?,?, '2099-12-26', 0, 'Current')", (A, B))

_COLS = ("game_id", "event_type", "quarter", "time", "primary_player_id",
         "shot_result", "shot_type", "play_type", "defense")


def ev(et, **kw):
    row = {c: None for c in _COLS}
    row.update(game_id=g, event_type=et, quarter=1, time="7:00",
               primary_player_id=p1)
    row.update(kw)
    ph = ",".join("?" * len(_COLS))
    execute(f"INSERT INTO game_events ({','.join(_COLS)}) VALUES ({ph})",
            tuple(row[c] for c in _COLS))


print("empty game")
cov = GE.live_state(g, n_events=0)["coverage"]
ok(cov["play_type"]["total"] == 0 and cov["play_type"]["pct"] is None,
   "no shots -> total 0, pct None")
ok(cov["defense"]["total"] == 0 and cov["defense"]["pct"] is None,
   "no shot/tov events -> total 0, pct None")

print("mixed tagging")
# 4 shots: 2 with play_type (one of the others ''), 1 with defense
ev("shot", shot_result="make", shot_type=2, play_type="pnr", defense="man")
ev("shot", shot_result="miss", shot_type=2, play_type="iso")
ev("shot", shot_result="miss", shot_type=3, play_type="")     # '' = untagged
ev("shot", shot_result="make", shot_type=2)
# 2 turnovers: 1 with defense — count toward defense denominator, not play_type
ev("turnover", defense="2-3 zone")
ev("turnover")
# a foul must not enter either denominator
ev("foul")

cov = GE.live_state(g, n_events=0)["coverage"]
ok(cov["play_type"]["total"] == 4, f"play_type denominator = shots only "
                                   f"(got {cov['play_type']['total']})")
ok(cov["play_type"]["tagged"] == 2 and cov["play_type"]["pct"] == 50,
   "play_type: '' and NULL untagged -> 2/4 = 50%")
ok(cov["defense"]["total"] == 6, f"defense denominator = shots + turnovers "
                                 f"(got {cov['defense']['total']})")
ok(cov["defense"]["tagged"] == 2 and cov["defense"]["pct"] == 33,
   "defense: 2/6 tagged -> 33%")

print(f"\nALL {PASS} CHECKS PASSED")
