"""
Smoke test for the tracker API + shared write path, against a THROWAWAY DB.

Sets APP5_DATA_DIR to a temp folder BEFORE importing the app, so the live DB in
%LOCALAPPDATA%\\APP5 is never touched. Run: python tracker/test_api.py
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_tracker_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient          # noqa: E402

from database.db import execute, query             # noqa: E402
import helpers.game_events as GE                   # noqa: E402
from tracker.api import app                        # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── seed: two teams, twelve players, one game ───────────────────────────────────
t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('Home HS','3A','F')")
t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('Away HS','3A','F')")
home, away = [], []
for i in range(6):
    home.append(execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
                        (t1, f"H{i+1}", i + 1)))
    away.append(execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)",
                        (t2, f"A{i+1}", i + 10)))
gid = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?, '2026-06-11')",
              (t1, t2))

client = TestClient(app)
# Per-coach auth (fail-closed): seed a Paid coach + a Free coach, then send the
# Paid coach's token on every call. games.tracked_by attribution flows from this.
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('coach@test','coach','Test Coach','paid','tok-paid')")
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('free@test','coach','Free Coach','free','tok-free')")
client.headers.update({"Authorization": "Bearer tok-paid"})
floor = home[:5] + away[:5]

print("game list / detail")
r = client.get("/api/games").json()
ok(any(g["id"] == gid for g in r["games"]), "game appears in /api/games")
r = client.get(f"/api/games/{gid}").json()
ok(r["home"]["name"] == "Home HS" and len(r["players"]) == 12, "detail: teams + rosters")

print("batch event sync")
batch = {"events": [
    {  # corner three, make, by H1 — x/y must derive zone RC and 3 points
        "uuid": "u-shot3", "event_type": "shot", "quarter": 1, "time": "7:40",
        "primary_player_id": home[0], "shot_result": "make",
        "shot_x": 21.0, "shot_y": 2.0,
        "on_court": floor, "officials_on": []},
    {  # paint two, miss, away rebound -> dreb side
        "uuid": "u-shot2", "event_type": "shot", "quarter": 1, "time": "7:10",
        "primary_player_id": home[1], "shot_result": "miss",
        "shot_x": 0.0, "shot_y": 8.0, "rebound_by_id": away[0],
        "on_court": floor, "officials_on": []},
    {"uuid": "u-ft", "event_type": "free_throw", "quarter": 1, "time": "6:55",
     "primary_player_id": away[0], "shot_result": "make",
     "on_court": floor, "officials_on": []},
    {"uuid": "u-foul", "event_type": "foul", "quarter": 1, "time": "6:55",
     "primary_player_id": home[2], "secondary_player_id": away[1],
     "on_court": floor, "officials_on": []},
    {"uuid": "u-tov", "event_type": "turnover", "quarter": 2, "time": "7:50",
     "primary_player_id": away[2], "stolen_by_id": home[3],
     "on_court": floor, "officials_on": []},
]}
r = client.post(f"/api/games/{gid}/events", json=batch).json()
ok(all(x["status"] == "inserted" for x in r["results"]), "5 events inserted")
ok(r["live"]["home_pts"] == 3 and r["live"]["away_pts"] == 1, "score 3-1 from events")
ok(r["live"]["home_poss"] == 2 and r["live"]["away_poss"] == 1, "possessions 2-1")
ok(r["live"]["quarters"]["1"] == {"home": 3, "away": 1}, "quarter scores")

ev = query("SELECT * FROM game_events WHERE client_uuid='u-shot3'")[0]
ok(ev["shot_type"] == 3 and ev["zone"] == "RC", "x/y derived 3PT + RC zone")
ok(ev["possession_secs"] == 20.0, "possession secs from 8:00 quarter start")
ev2 = query("SELECT * FROM game_events WHERE client_uuid='u-shot2'")[0]
ok(ev2["shot_type"] == 2 and ev2["zone"] == "C", "paint tap derived 2PT + C zone")
ok(ev2["possession_secs"] == 30.0, "possession secs vs previous event")

pm = {r["player_id"]: r["plus_minus"] for r in query(
    "SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?", (gid,))}
ok(pm[home[0]] == 3 - 1 and pm[away[0]] == 1 - 3, "plus/minus credited both ways")
ok(len(pm) == 10, "all 10 floor players have lineup rows")
gel = query("SELECT COUNT(*) n FROM game_event_lineup gel JOIN game_events ge "
            "ON ge.id=gel.event_id WHERE ge.game_id=?", (gid,))[0]["n"]
ok(gel == 50, "lineup snapshot: 5 events x 10 players")

print("idempotent retry (flaky-wifi replay)")
r = client.post(f"/api/games/{gid}/events", json=batch).json()
ok(all(x["status"] == "duplicate" for x in r["results"]), "full replay -> all duplicates")
ok(r["live"]["home_pts"] == 3 and r["live"]["away_pts"] == 1, "score unchanged after replay")

print("undo")
r = client.post(f"/api/games/{gid}/undo").json()
ok(r["deleted_event_id"] is not None, "undo deleted last event (tov)")
ok(query("SELECT COUNT(*) n FROM game_events WHERE game_id=?", (gid,))[0]["n"] == 4,
   "4 events remain")
# undo a scoring event -> +/- reverses
client.post(f"/api/games/{gid}/events", json={"events": [
    {"uuid": "u-shot3b", "event_type": "shot", "quarter": 2, "time": "6:00",
     "primary_player_id": home[0], "shot_result": "make",
     "shot_x": 0.0, "shot_y": 25.0, "on_court": floor, "officials_on": []}]})
pm_before = query("SELECT plus_minus FROM game_lineup_players WHERE game_id=? AND player_id=?",
                  (gid, home[0]))[0]["plus_minus"]
client.post(f"/api/games/{gid}/undo")
pm_after = query("SELECT plus_minus FROM game_lineup_players WHERE game_id=? AND player_id=?",
                 (gid, home[0]))[0]["plus_minus"]
ok(pm_before - pm_after == 3, "undoing a made 3 reverses +/- by 3")

print("auth (fail-closed, per-coach)")
no = TestClient(app)   # no default Authorization header
ok(no.get("/api/games").status_code == 401, "no token -> 401")
ok(no.get("/api/games", headers={"Authorization": "Bearer wrong"}).status_code == 401,
   "unknown token -> 401")
ok(no.get("/api/games", headers={"Authorization": "Bearer tok-free"}).status_code == 403,
   "Free plan token -> 403")
ok(no.get("/api/games", headers={"Authorization": "Bearer tok-paid"}).status_code == 200,
   "Paid coach token -> 200")
os.environ["TRACKER_TOKEN"] = "owner-master"
ok(no.get("/api/games", headers={"Authorization": "Bearer owner-master"}).status_code == 200,
   "env owner master token -> 200")
del os.environ["TRACKER_TOKEN"]
ok(no.get("/").status_code in (200, 404), "PWA shell never token-blocked")

print("finish")
r = client.post(f"/api/games/{gid}/finish").json()
ok(r["ok"] and r["home"] == 3 and r["away"] == 1, "finish freezes 3-1")
g = query("SELECT tracked, home_score, away_score FROM games WHERE id=?", (gid,))[0]
ok(g["tracked"] == 1 and g["home_score"] == 3, "games row tracked + frozen")
ok(query("SELECT tracked_by FROM games WHERE id=?", (gid,))[0]["tracked_by"] == "coach@test",
   "game attributed to its logging coach (tracked_by)")

print("direct helper (Streamlit page path)")
gid2 = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?, '2026-06-12')",
               (t1, t2))
oc = [(p, t1) for p in home[:5]] + [(p, t2) for p in away[:5]]
GE.log_event(gid2, {"event_type": "shot", "quarter": 1, "time": "7:00",
                    "primary_player_id": home[0], "shot_result": "make",
                    "shot_type": 2, "zone": "LW"}, oc)   # dropdown path, no x/y
ev = query("SELECT * FROM game_events WHERE game_id=?", (gid2,))[0]
ok(ev["zone"] == "LW" and ev["shot_type"] == 2 and ev["client_uuid"] is None,
   "no-xy fallback keeps explicit zone/type")

print("courtside setup endpoints")
r = client.get("/api/teams").json()
ok(any(t["name"] == "Home HS" for t in r["teams"]), "teams listed")
r = client.post("/api/teams", json={"name": "New Opp", "class": "4A", "gender": "F"}).json()
ok(r["created"] and r["id"], "team created")
t3 = r["id"]
r = client.post("/api/teams", json={"name": "New Opp", "class": "4A", "gender": "F"}).json()
ok(not r["created"] and r["id"] == t3, "duplicate team name reused")
r = client.post("/api/games", json={"team1_id": t1, "team2_id": t3, "date": "6/13/26"}).json()
gid3 = r["id"]
ok(gid3, "game created")
ok(query("SELECT date FROM games WHERE id=?", (gid3,))[0]["date"] == "2026-06-13",
   "date normalized to ISO")
r = client.post(f"/api/games/{gid3}/players",
                json={"team_id": t3, "name": "Newbie", "number": 23}).json()
ok(r["created"], "quick-add player")
r = client.post(f"/api/games/{gid3}/players",
                json={"team_id": t3, "name": "Newbie", "number": 23}).json()
ok(not r["created"], "duplicate player reused")
r = client.post("/api/officials", json={"name": "Ref One", "official_id": 9001}).json()
ok(r["id"], "quick-add official")
r = client.post("/api/officials", json={"name": "Ref One", "official_id": 9001}).json()
ok(r["id"], "duplicate official id ignored, id returned")
r = client.post(f"/api/games/{gid3}/players",
                json={"team_id": 999999, "name": "X", "number": 1})
ok(r.status_code == 422, "player for foreign team rejected")

print("event editor endpoints")
r = client.get(f"/api/games/{gid}/events").json()
ok(len(r["events"]) == 4, "full event list")
shot_ev = next(e for e in r["events"] if e["client_uuid"] == "u-shot3")
edit_body = {
    "event_type": "shot", "quarter": shot_ev["quarter"], "time": shot_ev["time"],
    "primary_player_id": home[4],          # re-tag shooter H1 -> H5
    "shot_result": "make", "shot_type": 3, "zone": shot_ev["zone"],
    "pass_from_id": home[1], "shot_created_by_id": None, "rebound_by_id": None,
    "blocked_by_id": None, "guarded_by_id": None, "secondary_player_id": None,
    "official_id": None, "stolen_by_id": None,
}
r = client.put(f"/api/games/{gid}/events/{shot_ev['id']}", json=edit_body).json()
ok(r["changed"], "edit applied")
ok(r["live"]["home_pts"] == 3, "score unchanged (same team scorer)")
ev = query("SELECT * FROM game_events WHERE id=?", (shot_ev["id"],))[0]
ok(ev["primary_player_id"] == home[4] and ev["pass_from_id"] == home[1],
   "shooter + assist re-tagged")
r = client.put(f"/api/games/{gid}/events/{shot_ev['id']}", json=edit_body).json()
ok(not r["changed"], "identical edit -> no-op")
# flip the make to a miss on a FINAL game -> stored score must re-freeze
edit_body["shot_result"] = "miss"
r = client.put(f"/api/games/{gid}/events/{shot_ev['id']}", json=edit_body).json()
ok(r["live"]["home_pts"] == 0, "make->miss drops score")
g = query("SELECT home_score FROM games WHERE id=?", (gid,))[0]
ok(g["home_score"] == 0, "tracked game's stored score re-frozen after edit")
ft_ev = next(e for e in client.get(f"/api/games/{gid}/events").json()["events"]
             if e["event_type"] == "free_throw")
r = client.delete(f"/api/games/{gid}/events/{ft_ev['id']}").json()
ok(r["deleted"] and r["live"]["away_pts"] == 0, "delete FT removes away point")
g = query("SELECT away_score FROM games WHERE id=?", (gid,))[0]
ok(g["away_score"] == 0, "stored away score re-frozen after delete")
ok(client.delete(f"/api/games/{gid}/events/999999").status_code == 404,
   "deleting unknown event -> 404")

print("alignment fixes")
# game creation: location stored, garbage rejected
r = client.post("/api/games", json={"team1_id": t1, "team2_id": t3,
                                    "date": "2026-06-14", "location": "Adair HS"}).json()
ok(query("SELECT location FROM games WHERE id=?", (r["id"],))[0]["location"] == "Adair HS",
   "game location stored")
ok(client.post("/api/games", json={"team1_id": t1, "team2_id": t3, "date": ""}).status_code == 422,
   "empty date rejected")
ok(client.post("/api/games", json={"team1_id": t1, "team2_id": t3, "date": "soon"}).status_code == 422,
   "garbage date rejected")
ok(client.post("/api/games", json={"team1_id": t1, "team2_id": 424242,
                                   "date": "2026-06-14"}).status_code == 422,
   "unknown team rejected")
# player anthro fields + jersey bounds
r = client.post(f"/api/games/{gid3}/players",
                json={"team_id": t3, "name": "Tall Kid", "number": 50,
                      "height": 74.5, "wingspan": 78.0, "weight": 160.0}).json()
row = query("SELECT height, wingspan, weight FROM players WHERE id=?", (r["id"],))[0]
ok(row["height"] == 74.5 and row["wingspan"] == 78.0 and row["weight"] == 160.0,
   "height/wingspan/weight stored")
ok(client.post(f"/api/games/{gid3}/players",
               json={"team_id": t3, "name": "X", "number": 1000}).status_code == 422,
   "jersey > 999 rejected")
# officials: empty name 422, stored name returned on id collision
ok(client.post("/api/officials", json={"name": "  ", "official_id": 9002}).status_code == 422,
   "blank official name rejected")
r = client.post("/api/officials", json={"name": "Wrong Name", "official_id": 9001}).json()
ok(r["name"] == "Ref One", "id collision returns STORED name")
# archived players flagged in detail (editor needs them)
execute("UPDATE players SET archived=1 WHERE id=?", (home[5],))
r = client.get(f"/api/games/{gid}").json()
arch = next(p for p in r["players"] if p["id"] == home[5])
ok(arch["archived"] == 1 and len(r["players"]) == 12, "archived player included + flagged")
# drift protection: manually-corrected score on a tracked game must survive edits
tov = client.post(f"/api/games/{gid}/events", json={"events": [
    {"uuid": "u-tov2", "event_type": "turnover", "quarter": 3, "time": "7:00",
     "primary_player_id": away[1], "on_court": floor, "officials_on": []}]}).json()
execute("UPDATE games SET home_score=55, away_score=41 WHERE id=?", (gid,))   # coach's manual fix
tov_id = tov["results"][0]["event_id"]
r = client.put(f"/api/games/{gid}/events/{tov_id}", json={
    "event_type": "turnover", "quarter": 3, "time": "6:50",
    "primary_player_id": away[2], "shot_result": None, "shot_type": None,
    "zone": None, "pass_from_id": None, "shot_created_by_id": None,
    "rebound_by_id": None, "blocked_by_id": None, "guarded_by_id": None,
    "secondary_player_id": None, "official_id": None, "stolen_by_id": None}).json()
g = query("SELECT home_score, away_score FROM games WHERE id=?", (gid,))[0]
ok((g["home_score"], g["away_score"]) == (55, 41), "manual score NOT clobbered by edit")
ok(r["drift"] is True, "drift flagged to client")
# explicit rescore brings it back in line
r = client.post(f"/api/games/{gid}/rescore").json()
g = query("SELECT home_score, away_score FROM games WHERE id=?", (gid,))[0]
ok((g["home_score"], g["away_score"]) == (r["home"], r["away"]), "manual rescore re-freezes")
# in-sync tracked game still auto-rescores on edit (old default behavior)
r = client.delete(f"/api/games/{gid}/events/{tov_id}").json()
ok(r["drift"] is False, "in-sync game: no drift after delete")
# data_version bumps so Streamlit page_chrome clears caches
v0 = query("SELECT value FROM app_settings WHERE key='data_version'")
v0 = int(v0[0]["value"]) if v0 else 0
client.post(f"/api/games/{gid3}/finish")
v1 = int(query("SELECT value FROM app_settings WHERE key='data_version'")[0]["value"])
ok(v1 > v0, "data_version bumped on finish")

print(f"\nALL {PASS} CHECKS PASSED  (db: {_TMP})")
