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
ok(st["team_fouls"] == {"2": {"home": 0, "away": 1}},
   "team fouls by quarter (charged to the FOULER's team = away)")

hbox = {ln["jersey"]: ln for ln in st["box"]["home"]}
abox = {ln["jersey"]: ln for ln in st["box"]["away"]}
ok(hbox[1]["pts"] == 3 and hbox[1]["fgm3"] == 1 and hbox[1]["stl"] == 1,
   "shooter line: 3 pts, 1/1 from 3, 1 steal")
ok(hbox[2]["ast"] == 1, "assist credited to passer (#2)")
ok(hbox[3]["blk"] == 1 and hbox[4]["reb"] == 1, "block + rebound credited")
ok(hbox[5]["pf"] == 0 and abox[11]["pf"] == 1,
   "PF charged to the FOULER #11, not the fouled #5")
ok(abox[11]["ftm"] == 1 and abox[11]["fta"] == 1, "FT line for #11")
ok(abox[12]["tov"] == 1, "turnover on #12")
ok(all(ln["on"] for ln in st["box"]["home"] if ln["jersey"] <= 5), "on-floor flags set")

ok(len(st["shots"]) == 2 and st["shots"][0]["team"] == "home"
   and st["shots"][0]["make"] is True and st["shots"][0]["type"] == 3,
   "shot chart dots with x/y")
ok(any("#1 3PT make (assist #2)" == p["text"] for p in st["plays"]),
   "pbp is jersey-numbers-only text")
ok(any("#11 foul (on #5)" == p["text"] for p in st["plays"]),
   "foul pbp leads with the fouler (#11), notes the fouled (#5)")
# last_play = newest event = the steal-turnover; jersey-only, no shot dot
lp = st["last_play"]
ok(lp["text"] == "#12 turnover (steal #1)" and lp["team"] == "away"
   and lp["q"] == 3 and "shot" not in lp, "last_play = newest play (turnover)")
offs = {o["slot"]: o for o in st["officials"]}
ok(list(offs) == ["R", "U1", "U2"] and offs["R"]["fouls"] == 0
   and offs["U1"]["fouls"] == 1, "refs anonymized R/U1/U2 with foul counts")
ok(offs["U1"]["home"] == 0 and offs["U1"]["away"] == 1
   and offs["U1"]["q"] == {"2": 1},
   "assigner detail: charged side (fouler=away) + quarter splits")

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
ok(st["officials"][0]["slot"] == "R" and st["officials"][0]["fouls"] == 1,
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
# Auto-close at final: the fan link goes private so tracked depth (box/PBP/
# shot chart) can't be mined for scouting post-game. Token is preserved.
ok(client.get(f"/api/public/game/{tok}").status_code == 404,
   "finish auto-closes the fan link (deep feed goes private)")
# re-open to inspect the final payload (same stable token)
coach.post(f"/api/games/{gid}/public")
st = client.get(f"/api/public/game/{tok}").json()
ok(st["status"] == "final", "re-opened finished game -> status final")

print("win probability strip")
wp = st["wp"]
ok(len(wp) >= 3 and all(0.0 <= p["p"] <= 1.0 for p in wp), "wp series in [0,1]")
ok(wp[0]["p"] == 0.5 and wp[-1]["p"] == 1.0,
   "wp starts even, collapses to home winner at the final buzzer")
ok(st["home"]["id"] == t1 and st["away"]["id"] == t2,
   "team ids in payload (profile links)")

print("scoreboard (landing feed)")
today = query("SELECT date('now') d")[0]["d"]
ok(client.get("/api/public/scoreboard?date=garbage").status_code == 422,
   "bad date -> 422")
# a second, NON-public in-progress game the same day must list as plain
# upcoming — no score, no link, no hint it's being tracked
gid2 = execute("INSERT INTO games (team1_id,team2_id,date,location) "
               "VALUES (?,?, date('now'), 'Privacy Gym')", (t2, t1))
coach.post(f"/api/games/{gid2}/events", json={"events": [
    {"uuid": "sb-shot", "event_type": "shot", "quarter": 1, "time": "7:00",
     "primary_player_id": away[0], "shot_result": "make",
     "shot_x": 0.0, "shot_y": 8.0, "on_court": floor, "officials_on": []}]})
sb = client.get(f"/api/public/scoreboard?date={today}").json()
ok(sb["date"] == today and len(sb["games"]) == 2, "both games on today's slate")
g1 = next(g for g in sb["games"] if g["home"] == "Claremore")
g2 = next(g for g in sb["games"] if g["home"] == "Visitor Prep")
ok(g1["status"] == "final" and g1["home_score"] == 5 and g1["url"] == f"/live/{tok}",
   "public finished game: final + score + link")
ok(g2["status"] == "upcoming" and "home_score" not in g2 and "url" not in g2,
   "non-public in-progress game: upcoming, no score, no link")
ok(sb["live"] == [], "no live section while nothing public is in progress")
# flip game 2 public -> it becomes a LIVE card with a live score
d2 = coach.post(f"/api/games/{gid2}/public").json()
sb = client.get(f"/api/public/scoreboard?date={today}").json()
ok(len(sb["live"]) == 1 and sb["live"][0]["home"] == "Visitor Prep"
   and sb["live"][0]["home_pts"] == 2 and sb["live"][0]["url"] == d2["url"],
   "public in-progress game becomes a LIVE card")
g2 = next(g for g in sb["games"] if g["home"] == "Visitor Prep")
ok(g2["status"] == "live" and g2["url"] == d2["url"], "slate row flips to live")
blob = json.dumps(sb)
for name in HOME_NAMES + AWAY_NAMES + REF_NAMES:
    for part in name.split():
        assert part not in blob, f"LEAK: '{part}' in scoreboard payload"
ok(True, "scoreboard payload has no player/official names")

print("finals rail + class chips")
yday = query("SELECT date('now','-1 day') d")[0]["d"]
sb = client.get(f"/api/public/scoreboard?date={yday}").json()
ok(any(r["home"] == "Claremore" and r["home_score"] == 5 and r.get("url")
       for r in sb["recent"]), "today's final rides the latest-finals rail")
sb = client.get(f"/api/public/scoreboard?date={today}").json()
g1 = next(g for g in sb["games"] if g["home"] == "Claremore")
ok(g1["classes"] == ["5A"] and g1["home_id"] == t1, "slate rows carry class + team ids")

print("team profile")
ok(client.get("/api/public/team/999999").status_code == 404, "unknown team -> 404")
tp = client.get(f"/api/public/team/{t1}").json()
ok(tp["name"] == "Claremore" and tp["gender"] == "Boys" and tp["class"] == "5A",
   "team identity")
ok(tp["wins"] == 1 and tp["losses"] == 0, "record from finals")
fin = next(g for g in tp["games"] if g["status"] == "final")
ok(fin["won"] is True and fin["us"] == 5 and fin["them"] == 1
   and fin["url"] == f"/live/{tok}", "result row: W 5-1 + fan link")
blob = json.dumps(tp)
for name in HOME_NAMES + AWAY_NAMES + REF_NAMES:
    for part in name.split():
        assert part not in blob, f"LEAK: '{part}' in team payload"
ok(True, "team payload has no player/official names")

print("teams directory (rankings snapshot)")
PF.clear_cache()
res = client.get("/api/public/teams")
ok(res.status_code == 200, "anon fan can read the directory")
td = res.json()
ok(td["season"] == "", "active-season directory carries no archive label")
by_name = {t["name"]: t for t in td["teams"]}
ok({"Claremore", "Visitor Prep"} <= set(by_name), "every team listed")
c, v = by_name["Claremore"], by_name["Visitor Prep"]
ok(c["rank"] == 1 and c["of"] == 2 and c["wins"] == 1 and c["losses"] == 0,
   "winner ranked #1 with W-L record")
ok(v["rank"] == 2 and v["losses"] == 1, "loser ranked #2")
ok(c["class_lbl"] == "5A" and c["class_rank"] == 1 and c["class_of"] == 2,
   "class label + class rank ordinals")
ok(c["gender"] == "Boys", "gender label")
blob = json.dumps(td)
for name in HOME_NAMES + AWAY_NAMES + REF_NAMES:
    for part in name.split():
        assert part not in blob, f"LEAK: '{part}' in teams payload"
ok(True, "teams payload has no player/official names")
for key in ("Power", "Rating", "AdjNet", "SOS", "SOR", "xPPG", "xoPPG",
            "PPG", "oPPG", "MOV", "ClassAdj"):
    assert f'"{key}"' not in blob, f"LEAK: '{key}' in teams payload"
ok(True, "rank ordinals only — no rating-engine numbers in payload")
t3 = execute("INSERT INTO teams (name, class, gender) VALUES "
             "('Newbie High','4A','M')")
PF.clear_cache()
td = client.get("/api/public/teams").json()
nb = next(t for t in td["teams"] if t["name"] == "Newbie High")
ok(nb["rank"] is None and nb["gp"] == 0 and nb["wins"] == 0,
   "team with no finished games still listed, unranked")

print("fan counter")
f1 = coach.get(f"/api/games/{gid}").json()["public"]["fans"]
ok(f1 >= 1, "coach sees a fan count (test polls counted once)")
client.get(f"/api/public/game/{tok}", headers={"User-Agent": "second-phone"})
client.get(f"/api/public/game/{tok}", headers={"User-Agent": "second-phone"})
f2 = coach.get(f"/api/games/{gid}").json()["public"]["fans"]
ok(f2 == f1 + 1, "new viewer counts once, repeat polls don't")

print("fan link QR")
res = coach.get(f"/api/games/{gid}/fanqr")
ok(res.status_code == 200 and "svg" in res.headers.get("content-type", "")
   and "<svg" in res.text, "QR svg for a public game")
gid3 = execute("INSERT INTO games (team1_id,team2_id,date) "
               "VALUES (?,?, date('now'))", (t1, t2))
ok(coach.get(f"/api/games/{gid3}/fanqr").status_code == 404,
   "QR 404 when the fan link is off")
ok(client.get(f"/api/games/{gid}/fanqr").status_code == 401, "QR needs auth")

print("fan page shell")
res = client.get(f"/live/{tok}")
ok(res.status_code == 200 and "HoopTracks" in res.text, "/live/<token> serves the page")
ok("text/html" in res.headers.get("content-type", ""), "page is html")
res = client.get("/live")
ok(res.status_code == 200 and "SCHEDULE" in res.text, "/live serves the landing page")
res = client.get(f"/live/team/{t1}")
ok(res.status_code == 200 and "RESULTS" in res.text, "/live/team/<id> serves the team page")

print("rowid-reuse version guard (undo then relog)")
gid4 = execute("INSERT INTO games (team1_id,team2_id,date) "
               "VALUES (?,?, date('now'))", (t1, t2))
coach.post(f"/api/games/{gid4}/public")
tok4 = query("SELECT share_token FROM games WHERE id=?", (gid4,))[0]["share_token"]
coach.post(f"/api/games/{gid4}/events", json={"events": [
    {"uuid": "c-a", "event_type": "shot", "quarter": 1, "time": "7:00",
     "primary_player_id": home[0], "shot_result": "make",
     "shot_x": 0.0, "shot_y": 8.0, "on_court": floor, "officials_on": []}]})
va = client.get(f"/api/public/game/{tok4}").json()
# undo the newest event (frees the MAX rowid) then log a DIFFERENT one — SQLite
# reuses the freed rowid, so a last-id-only version key would collide and the fan
# page would freeze on the stale box. The data_version fold-in must break the tie.
coach.post(f"/api/games/{gid4}/undo")
coach.post(f"/api/games/{gid4}/events", json={"events": [
    {"uuid": "c-b", "event_type": "shot", "quarter": 1, "time": "6:30",
     "primary_player_id": away[0], "shot_result": "make",
     "shot_x": 0.0, "shot_y": 8.0, "on_court": floor, "officials_on": []}]})
vb = client.get(f"/api/public/game/{tok4}").json()
ok(vb["version"] != va["version"],
   "version differs after undo+relog even when SQLite reuses the rowid")
ok(vb["home"]["pts"] == 0 and vb["away"]["pts"] == 2,
   "box reflects the swap (home make undone, away make added)")

print(f"\nALL {PASS} CHECKS PASSED")
