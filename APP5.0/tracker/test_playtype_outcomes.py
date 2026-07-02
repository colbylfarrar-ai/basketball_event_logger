"""
End-to-end test: play_type on TURNOVERS and FOULS, against a THROWAWAY DB.

The set-call tag used to live on shots only; the trackers now stamp the sticky
play_type on TOs and fouls too, so per-set outcomes cover score / turnover /
foul. Covers:
  • write path  — play_type persists on a turnover AND a foul through the API
  • engine math — team_named_playtypes possessions = shots + tagged TOs (PPP is
                  a true per-possession rate), TO% and FD (fouls drawn) per set;
                  player_named_playtypes gets the same treatment
  • back-compat — shot-only data reproduces the old numbers exactly

Sets APP5_DATA_DIR to a temp folder BEFORE importing the app so the live DB is
never touched. Run: python tracker/test_playtype_outcomes.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_pt_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient          # noqa: E402

from database.db import execute, query             # noqa: E402
import helpers.stats as S                          # noqa: E402
import helpers.playtypes as PT                     # noqa: E402
from tracker.api import app                        # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── seed: two teams, ten players, one game, a paid coach ────────────────────────
t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('Home HS','3A','M')")
t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('Away HS','3A','M')")
home, away = [], []
for i in range(5):
    home.append(execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
                        (t1, f"H{i+1}", i + 1)))
    away.append(execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
                        (t2, f"A{i+1}", i + 10)))
gid = execute("INSERT INTO games (team1_id,team2_id,date,tracked) "
              "VALUES (?,?, '2026-07-01', 1)", (t1, t2))
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('coach@test','coach','Test','paid','tok')")
client = TestClient(app)
client.headers.update({"Authorization": "Bearer tok"})
floor = home + away


def shot(uid, pid, made, play):
    return {"uuid": uid, "event_type": "shot", "quarter": 1, "time": "7:00",
            "primary_player_id": pid, "shot_result": "make" if made else "miss",
            "shot_x": 0.0, "shot_y": 8.0, "play_type": play, "defense": "man",
            "on_court": floor, "officials_on": []}


print("write path — play_type persists on a turnover AND a foul")
batch = {"events": [
    # PnR: 2 makes, 1 miss, 2 TOs, 1 foul drawn -> poss 5, pts 4, TO% 40%
    shot("s1", home[0], True, "pnr"),
    shot("s2", home[0], True, "pnr"),
    shot("s3", home[1], False, "pnr"),
    {"uuid": "t1", "event_type": "turnover", "quarter": 1, "time": "6:40",
     "primary_player_id": home[0], "stolen_by_id": away[0], "play_type": "pnr",
     "defense": "man", "on_court": floor, "officials_on": []},
    {"uuid": "t2", "event_type": "turnover", "quarter": 1, "time": "6:20",
     "primary_player_id": home[1], "stolen_by_id": None, "play_type": "pnr",
     "defense": "man", "on_court": floor, "officials_on": []},
    {"uuid": "f1", "event_type": "foul", "quarter": 1, "time": "6:00",
     "primary_player_id": home[0], "secondary_player_id": away[1],
     "play_type": "pnr", "defense": "man", "on_court": floor, "officials_on": []},
    # ISO: 1 make, 1 miss, no TOs -> old-style shot-only rows still exact
    shot("s4", home[2], True, "iso"),
    shot("s5", home[2], False, "iso"),
    # one away possession so the allowed-side gate (event_team_games) knows
    # t2 played this game — offense=False scopes to games with a t2 PRIMARY
    shot("a1", away[2], False, None),
]}
r = client.post(f"/api/games/{gid}/events", json=batch).json()
ok(all(x["status"] == "inserted" for x in r["results"]), "9 events inserted")
ok(query("SELECT play_type FROM game_events WHERE client_uuid='t1'")[0]["play_type"] == "pnr",
   "turnover stored its play_type (pnr)")
ok(query("SELECT play_type FROM game_events WHERE client_uuid='f1'")[0]["play_type"] == "pnr",
   "foul stored its play_type (pnr)")

print("engine — possessions include tagged TOs; TO% and FD per set")
events = S.fetch_events([gid])
named = PT.team_named_playtypes(t1, events=events, offense=True)
rows = {row["key"]: row for row in named["rows"]}
pnr = rows["pnr"]
ok(pnr["poss"] == 5, f"PnR possessions = shots+TOs (5, got {pnr['poss']})")
ok(abs(pnr["PPP"] - 4 / 5) < 1e-9, f"PnR PPP includes TO possessions (0.8, got {pnr['PPP']})")
ok(abs(pnr["TO%"] - 2 / 5) < 1e-9, "PnR TO% = 40%")
ok(pnr["FD"] == 1, "PnR fouls drawn = 1")
iso = rows["iso"]
ok(iso["poss"] == 2 and iso["TOV"] == 0 and abs(iso["PPP"] - 1.0) < 1e-9,
   "shot-only set reproduces the old numbers exactly")

print("engine — defense view: forced TOs lower PPP allowed, fouls committed")
dnamed = PT.team_named_playtypes(t2, events=events, offense=False)
drows = {row["key"]: row for row in dnamed["rows"]}
ok(drows["pnr"]["poss"] == 5 and drows["pnr"]["TOV"] == 2,
   "defense sees the same 5 possessions with 2 forced TOs")
ok(drows["pnr"]["FD"] == 1, "defense side counts the foul it committed")

print("engine — player-level TO possessions")
per = PT.player_named_playtypes(events=events)
h0 = per[home[0]]["pnr"]
ok(h0["poss"] == 3 and h0["TOV"] == 1,
   "player possessions = own shots + own tagged TOs")
ok(h0["FD"] == 1, "player fouls drawn per set")

print("engine — percentile wrapper survives the new keys")
pct = PT.team_named_playtype_percentiles(t1, events=events, offense=True)
ok(any(row["key"] == "pnr" and "TO%" in row for row in pct["rows"]),
   "percentile rows carry TO% through")

print(f"\nALL {PASS} CHECKS PASSED")
