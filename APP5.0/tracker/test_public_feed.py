"""
Public fan-link feed test: opt-in gate, allowlist payload, privacy sweep.

Same pattern as test_api.py — throwaway DB via APP5_DATA_DIR set BEFORE
imports. Run: python tracker/test_public_feed.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_public_feed_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient          # noqa: E402

from database.db import execute, query             # noqa: E402
import helpers.public_feed as PF                   # noqa: E402
from tracker.api import app                        # noqa: E402

PF.CACHE_TTL = 0.0   # every read rebuilds — the tests assert fresh state

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── seed: distinctive names so the privacy sweep can't false-positive ───────────
t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('Claremore','5A','M')")
t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('Visitor Prep','5A','M')")
home, away = [], []
HOME_NAMES = ["Zebulon Quimby", "Barnaby Yootz", "Casimir Vexley",
              "Dmitri Wobble", "Ezekiel Plum", "Fergus Knot"]
AWAY_NAMES = ["Gulliver Snipe", "Horatio Bleem", "Ignatius Crux",
              "Jasper Flint", "Kelvin Moss", "Lysander Poe"]
for i in range(6):
    home.append(execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
                        (t1, HOME_NAMES[i], i + 1)))
    away.append(execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
                        (t2, AWAY_NAMES[i], i + 10)))
gid = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?, date('now'))",
              (t1, t2))
REF_NAMES = ["Obadiah Whistle", "Percival Tweet", "Quincy Blowhard"]
refs = [execute("INSERT INTO officials (name, official_id) VALUES (?,?)",
                (REF_NAMES[i], 9000 + i)) for i in range(3)]

client = TestClient(app)
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('coach@test','coach','Test Coach','paid','tok-paid')")
coach = TestClient(app)
coach.headers.update({"Authorization": "Bearer tok-paid"})
floor = home[:5] + away[:5]

# events: assisted corner 3 (make), missed 2 w/ block+board, FT, ref'd foul,
# stolen turnover — each carries play_type/defense to prove tags never leak.
batch = {"events": [
    {"uuid": "p-shot3", "event_type": "shot", "quarter": 1, "time": "7:40",
     "primary_player_id": home[0], "shot_result": "make",
     "shot_x": 21.0, "shot_y": 2.0, "pass_from_id": home[1],
     "play_type": "pnr", "defense": "2-3 zone",
     "on_court": floor, "officials_on": refs},
    {"uuid": "p-shot2", "event_type": "shot", "quarter": 2, "time": "6:10",
     "primary_player_id": away[0], "shot_result": "miss",
     "shot_x": 0.0, "shot_y": 8.0, "blocked_by_id": home[2],
     "rebound_by_id": home[3], "play_type": "iso", "defense": "man",
     "on_court": floor, "officials_on": refs},
    {"uuid": "p-foul", "event_type": "foul", "quarter": 2, "time": "5:30",
     "primary_player_id": home[4], "secondary_player_id": away[1],
     "official_id": refs[1],
     "on_court": floor, "officials_on": refs},
    {"uuid": "p-ft", "event_type": "free_throw", "quarter": 2, "time": "5:30",
     "primary_player_id": away[1], "shot_result": "make",
     "on_court": floor, "officials_on": refs},
    {"uuid": "p-tov", "event_type": "turnover", "quarter": 3, "time": "7:00",
     "primary_player_id": away[2], "stolen_by_id": home[0],
     "play_type": "cut", "defense": "man press",
     "on_court": floor, "officials_on": refs},
]}
r = coach.post(f"/api/games/{gid}/events", json=batch).json()
assert all(x["status"] == "inserted" for x in r["results"]), r

print("opt-in gate")
ok(client.get("/api/public/game/nope").status_code == 404, "unknown token -> 404")
tok_row = query("SELECT share_token FROM games WHERE id=?", (gid,))[0]
ok(tok_row["share_token"] == "", "no token before opt-in")
ok(client.post(f"/api/games/{gid}/public").status_code == 401,
   "toggle needs auth (anon 401)")
d = coach.post(f"/api/games/{gid}/public").json()
ok(d["public"] is True and len(d["token"]) >= 8, "coach flips public + token minted")
tok = d["token"]
ok(d["url"] == f"/live/{tok}", "share url returned")

print("public payload (unauthenticated)")
res = client.get(f"/api/public/game/{tok}")
ok(res.status_code == 200, "anon fan can read the feed")
st = res.json()
ok(st["status"] == "live", "status live while untracked")
ok(st["home"]["name"] == "Claremore" and st["home"]["pts"] == 3, "home 3 pts")
ok(st["away"]["pts"] == 1, "away 1 pt (FT)")
ok(st["quarter"] == 3 and st["clock"] == "7:00", "quarter/clock from last event")
ok(st["quarters"] == {"1": {"home": 3, "away": 0}, "2": {"home": 0, "away": 1}},
   "quarter scores")
ok(st["team_fouls"] == {"2": {"home": 1, "away": 0}}, "team fouls by quarter")

hbox = {ln["jersey"]: ln for ln in st["box"]["home"]}
abox = {ln["jersey"]: ln for ln in st["box"]["away"]}
ok(hbox[1]["pts"] == 3 and hbox[1]["fgm3"] == 1 and hbox[1]["stl"] == 1,
   "shooter line: 3 pts, 1/1 from 3, 1 steal")
ok(hbox[2]["ast"] == 1, "assist credited to passer (#2)")
ok(hbox[3]["blk"] == 1 and hbox[4]["reb"] == 1, "block + rebound credited")
ok(hbox[5]["pf"] == 1, "foul on #5")
ok(abox[11]["ftm"] == 1 and abox[11]["fta"] == 1, "FT line for #11")
ok(abox[12]["tov"] == 1, "turnover on #12")
ok(all(ln["on"] for ln in st["box"]["home"] if ln["jersey"] <= 5), "on-floor flags set")

ok(len(st["shots"]) == 2 and st["shots"][0]["team"] == "home"
   and st["shots"][0]["make"] is True and st["shots"][0]["type"] == 3,
   "shot chart dots with x/y")
ok(any("#1 3PT make (assist #2)" == p["text"] for p in st["plays"]),
   "pbp is jersey-numbers-only text")
ok(st["officials"] == [{"slot": "R", "fouls": 0}, {"slot": "U1", "fouls": 1},
                       {"slot": "U2", "fouls": 0}],
   "refs anonymized R/U1/U2 with foul counts")

print("privacy sweep")
blob = json.dumps(st)
for name in HOME_NAMES + AWAY_NAMES + REF_NAMES:
    for part in name.split():
        assert part not in blob, f"LEAK: '{part}' in public payload"
ok(True, "no player/official name fragment in payload")
for tag in ("pnr", "iso", "2-3 zone", "man press", "play_type", "defense",
            "official_id", "turnover_type", "foul_type"):
    assert tag not in blob, f"LEAK: '{tag}' in public payload"
ok(True, "no play_type/defense/tag fields in payload")

print("explicit crew slots override id order")
execute("UPDATE game_lineup_officials SET slot=CASE official_id "
        "WHEN ? THEN 3 WHEN ? THEN 1 WHEN ? THEN 2 END WHERE game_id=?",
        (refs[0], refs[1], refs[2], gid))
st = client.get(f"/api/public/game/{tok}").json()
ok(st["officials"][0] == {"slot": "R", "fouls": 1},
   "slot column reorders crew (caller now R)")

print("toggle off/on + token stability")
d = coach.post(f"/api/games/{gid}/public").json()
ok(d["public"] is False, "toggle off")
ok(client.get(f"/api/public/game/{tok}").status_code == 404,
   "off -> same 404 as unknown token")
d = coach.post(f"/api/games/{gid}/public").json()
ok(d["public"] is True and d["token"] == tok, "token stable across off/on")

print("version + final status")
v1 = client.get(f"/api/public/game/{tok}").json()["version"]
coach.post(f"/api/games/{gid}/events", json={"events": [
    {"uuid": "p-shot2b", "event_type": "shot", "quarter": 4, "time": "3:00",
     "primary_player_id": home[1], "shot_result": "make",
     "shot_x": 0.0, "shot_y": 8.0, "on_court": floor, "officials_on": refs}]})
st = client.get(f"/api/public/game/{tok}").json()
ok(st["version"] != v1, "version moves on a new event")
ok(st["home"]["pts"] == 5, "score updates live")
coach.post(f"/api/games/{gid}/finish")
st = client.get(f"/api/public/game/{tok}").json()
ok(st["status"] == "final", "finish -> status final")

print("fan page shell")
res = client.get(f"/live/{tok}")
ok(res.status_code == 200 and "HoopTracks" in res.text, "/live/<token> serves the page")
ok("text/html" in res.headers.get("content-type", ""), "page is html")

print(f"\nALL {PASS} CHECKS PASSED")
