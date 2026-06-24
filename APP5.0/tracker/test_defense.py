"""
End-to-end smoke test for the DEFENSE tag, against a THROWAWAY DB.

Covers the whole feature spine the live UI rides on:
  • write path  — defense persists on a shot AND a turnover through the tracker API
  • edit path   — editing an event PRESERVES / changes defense + play_type (the
                  PWA editor used to silently null play_type; this locks the fix)
  • engine math — helpers/defenses computes per-scheme PPP, the play_type×defense
                  cross-tab, the family rollup and forced-TO counts off the events

Sets APP5_DATA_DIR to a temp folder BEFORE importing the app so the live DB is
never touched. Run: python tracker/test_defense.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_def_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient          # noqa: E402

from database.db import execute, query             # noqa: E402
import helpers.stats as S                          # noqa: E402
import helpers.defenses as DEF                     # noqa: E402
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
gid = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?, '2026-06-12')",
              (t1, t2))
execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('coach@test','coach','Test','paid','tok')")
client = TestClient(app)
client.headers.update({"Authorization": "Bearer tok"})
floor = home + away


def shot(uuid, pid, made, x, y, defense, play):
    return {"uuid": uuid, "event_type": "shot", "quarter": 1, "time": "7:00",
            "primary_player_id": pid, "shot_result": "make" if made else "miss",
            "shot_x": x, "shot_y": y, "play_type": play, "defense": defense,
            "on_court": floor, "officials_on": []}


print("write path — defense persists on shots + a turnover")
# HOME faces MAN (away's scheme), runs PnR.  AWAY faces a 2-3 ZONE (home runs it).
batch = {"events": [
    shot("h1", home[0], True,  0.0, 8.0,  "man", "pnr"),     # paint 2, make
    shot("h2", home[1], True,  0.0, 8.0,  "man", "pnr"),     # paint 2, make
    shot("h3", home[2], False, 21.0, 2.0, "man", "pnr"),     # corner 3, miss
    shot("h4", home[3], False, 0.0, 8.0,  "man", "spot"),    # paint 2, miss
    shot("a1", away[0], True,  0.0, 8.0,  "zone_23", "iso"),
    shot("a2", away[1], False, 0.0, 8.0,  "zone_23", "iso"),
    shot("a3", away[2], False, 21.0, 2.0, "zone_23", "iso"),
    {"uuid": "tov1", "event_type": "turnover", "quarter": 1, "time": "6:30",
     "primary_player_id": away[0], "stolen_by_id": home[0], "defense": "press_221",
     "on_court": floor, "officials_on": []},
    {"uuid": "foul1", "event_type": "foul", "quarter": 1, "time": "6:20",
     "primary_player_id": home[0], "secondary_player_id": away[1], "defense": "man",
     "on_court": floor, "officials_on": []},
]}
r = client.post(f"/api/games/{gid}/events", json=batch).json()
ok(all(x["status"] == "inserted" for x in r["results"]), "9 events inserted")
ok(query("SELECT defense FROM game_events WHERE client_uuid='foul1'")[0]["defense"] == "man",
   "foul stored its defense tag (man)")
ok(query("SELECT defense FROM game_events WHERE client_uuid='h1'")[0]["defense"] == "man",
   "shot stored its defense tag (man)")
ok(query("SELECT defense FROM game_events WHERE client_uuid='a1'")[0]["defense"] == "zone_23",
   "opponent shot stored its defense tag (2-3 zone)")
ok(query("SELECT defense FROM game_events WHERE client_uuid='tov1'")[0]["defense"] == "press_221",
   "turnover stored its defense tag (press)")

print("edit path — defense + play_type survive / change on an edit")
h1 = query("SELECT id FROM game_events WHERE client_uuid='h1'")[0]["id"]
# edit only the time; body re-sends defense+play_type -> they must NOT be wiped
body = {"event_type": "shot", "quarter": 1, "time": "5:00",
        "primary_player_id": home[0], "shot_result": "make", "shot_type": 2,
        "zone": "C", "play_type": "pnr", "defense": "man"}
client.put(f"/api/games/{gid}/events/{h1}", json=body)
row = query("SELECT defense, play_type FROM game_events WHERE id=?", (h1,))[0]
ok(row["defense"] == "man" and row["play_type"] == "pnr",
   "editing time preserves defense + play_type (no silent wipe)")
# now change the scheme to a match-up zone
body2 = dict(body, defense="matchup", play_type="spot")
client.put(f"/api/games/{gid}/events/{h1}", json=body2)
row = query("SELECT defense, play_type FROM game_events WHERE id=?", (h1,))[0]
ok(row["defense"] == "matchup" and row["play_type"] == "spot",
   "editing changes defense + play_type")
# put it back so the engine math below is on the original tags
client.put(f"/api/games/{gid}/events/{h1}", json=body)

print("engine — per-scheme PPP, cross-tab, families, forced TOs")
ev = S.fetch_events([gid])

# HOME's own shots, grouped by the defense it FACED (man): 4 shots, 2 makes (both
# 2s) -> 4 pts / 4 = 1.00 PPP.
faced = {r["key"]: r for r in DEF.team_defenses(t1, events=ev, offense=True)["rows"]}
ok("man" in faced and faced["man"]["poss"] == 4, "home faced man on 4 shots")
ok(abs(faced["man"]["PPP"] - 1.00) < 1e-6, "home PPP vs man = 1.00")

# HOME's DEFENSE = shots it ALLOWED (away's shots), grouped by the scheme home ran
# (2-3 zone): 3 shots, 1 make (a 2) -> 2/3 PPP allowed.
run = {r["key"]: r for r in DEF.team_defenses(t1, events=ev, offense=False)["rows"]}
ok("zone_23" in run and run["zone_23"]["poss"] == 3, "home ran a 2-3 on 3 allowed shots")
ok(abs(run["zone_23"]["PPP"] - 2 / 3) < 1e-6, "home PPP allowed in 2-3 = 0.67")

# play_type × defense cross-tab (home offense): pnr × man = 3 shots (h1,h2,h3).
cx = DEF.cross_play_defense(t1, events=ev, offense=True)
ok(cx["matrix"]["pnr"]["man"]["poss"] == 3, "cross-tab: PnR vs man = 3 poss")
ok("man" in cx["defenses"] and "pnr" in cx["plays"], "cross-tab axes present")

# family rollup (home defense): the 2-3 zone shots roll up under 'zone'.
fam = {r["family"]: r for r in DEF.team_defense_families(t1, events=ev, offense=False)["rows"]}
ok("zone" in fam and fam["zone"]["poss"] == 3, "family rollup: zone = 3 poss")

# forced turnovers: home's press forced away's TO (offense=False on home).
tv = {r["key"]: r for r in DEF.team_defense_turnovers(t1, events=ev, offense=False)["rows"]}
ok(tv.get("press_221", {}).get("tovs") == 1, "home press forced 1 turnover")

# fouls: foul1 = home[0] fouled (drew it) under man -> home DREW a foul vs man
# (offense=True), and AWAY committed it under man (away offense=False).
flh = {r["key"]: r for r in DEF.team_defense_fouls(t1, events=ev, offense=True)["rows"]}
ok(flh.get("man", {}).get("fouls") == 1, "home drew 1 foul vs man (offense side)")
fla = {r["key"]: r for r in DEF.team_defense_fouls(t2, events=ev, offense=False)["rows"]}
ok(fla.get("man", {}).get("fouls") == 1, "away committed 1 foul running man (defense side)")

print("bulk-tag defense (Event Editor 'fill whole game, then tweak')")
import helpers.event_log as EL                                          # noqa: E402
# add an UNtagged shot + a free throw, then bulk-fill the blanks as man
client.post(f"/api/games/{gid}/events", json={"events": [
    {"uuid": "u-untag", "event_type": "shot", "quarter": 2, "time": "7:00",
     "primary_player_id": home[0], "shot_result": "make", "shot_x": 0.0,
     "shot_y": 8.0, "on_court": floor, "officials_on": []},
    {"uuid": "u-ft2", "event_type": "free_throw", "quarter": 2, "time": "6:55",
     "primary_player_id": home[0], "shot_result": "make",
     "on_court": floor, "officials_on": []}]})
_nb = EL.bulk_set_defense(gid, "man", only_blank=True)
ok(_nb >= 1, "bulk fill (only_blank) tagged the untagged shot")
ok(query("SELECT defense FROM game_events WHERE client_uuid='u-untag'")[0]["defense"]
   == "man", "untagged shot is now man")
ok(query("SELECT defense FROM game_events WHERE client_uuid='u-ft2'")[0]["defense"]
   is None, "bulk fill never tags free throws")
ok(query("SELECT defense FROM game_events WHERE client_uuid='h3'")[0]["defense"]
   == "man", "pre-tagged man shot unchanged by only_blank fill")
ok(EL.bulk_set_defense(gid, "man", only_blank=True) == 0,
   "re-run only_blank -> nothing left to fill")
_na = EL.bulk_set_defense(gid, "zone_23", only_blank=False)
ok(query("SELECT defense FROM game_events WHERE client_uuid='u-untag'")[0]["defense"]
   == "zone_23", "overwrite-all changed every eligible event")

# per-team scoping: fill only HOME's possessions (primary on home) with man —
# the defense tag is the DEFENDING (away) team's scheme, so this is "the defense
# home faced". Away's possessions (primary on away) must stay untouched.
_nh = EL.bulk_set_defense(gid, "man", only_blank=False, primary_team_id=t1)
ok(_nh >= 1, "team-scoped fill touched home's possessions")
ok(query("SELECT defense FROM game_events WHERE client_uuid='h1'")[0]["defense"]
   == "man", "home possession (primary on home) -> man")
ok(query("SELECT defense FROM game_events WHERE client_uuid='a1'")[0]["defense"]
   == "zone_23", "away possession untouched by home-scoped fill")

print(f"\nALL {PASS} CHECKS PASSED  (db: {os.environ['APP5_DATA_DIR']})")
