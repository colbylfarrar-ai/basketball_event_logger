"""
8e — technical-foul capture (trick + tag). A player tech is logged as a foul
with fouled == fouler (the same-player trick keeps every non-null assumption
downstream honest) PLUS foul_type='technical' (the tag makes the row
explainable and lets drawn-side reads skip it).

Consumers pinned here:
  * PF        — charged to the fouler (NFHS: a player tech IS a personal foul).
  * drawn     — a tech is never "drawn": fouls.player_foul_ft excludes it, and
                the per-player tech count rides alongside.
  * charges   — is_charge() must never read a tech as a charge, even when the
                sticky tags left play_type/defense == 'other'/'other'.
  * defenses  — team_defense_fouls excludes techs on BOTH orientations: the
                same-player trick makes shooter_team_id the TECH'D player's
                team, so the committed-side read would attribute an opponent's
                tech to US. A tech is dead-ball — no scheme context exists.
  * playtypes — FD (fouls drawn per set) excludes techs on both team and
                player reads.
  * feed      — the public play-by-play line reads "technical", not
                "#N foul (on #N)".
Run: python tracker/test_tech_foul.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_tech_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, execute                # noqa: E402
import helpers.game_events as GE                                    # noqa: E402
import helpers.stats as S                                           # noqa: E402
import helpers.fouls as F                                           # noqa: E402
import helpers.charges as CH                                        # noqa: E402
import helpers.defenses as D                                        # noqa: E402
import helpers.playtypes as PT                                      # noqa: E402
import helpers.public_feed as PF                                    # noqa: E402

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
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)",
            (pid, f"H{pid}", pid - 100))
for pid in (201, 202, 203, 204, 205):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,2,?,?)",
            (pid, f"A{pid}", pid - 200))
G = execute("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-01')")
FLOOR = [(101, 1), (102, 1), (103, 1), (104, 1), (105, 1),
         (201, 2), (202, 2), (203, 2), (204, 2), (205, 2)]


def foul(fouled, fouler, foul_type=None, play_type=None, defense=None):
    ev = {"event_type": "foul", "quarter": 1, "time": "5:00",
          "primary_player_id": fouled, "secondary_player_id": fouler,
          "foul_type": foul_type, "play_type": play_type, "defense": defense}
    return GE.log_event(G, ev, FLOOR)


# seed a team-2 shot so TA.event_team_games can place team 2 in this game
# (the offense=False orientation filters by the team's own game pool)
GE.log_event(G, {"event_type": "shot", "quarter": 1, "time": "7:00",
                 "primary_player_id": 201, "shot_result": "miss",
                 "shot_type": 2, "zone": "C"}, FLOOR)

# a regular foul: away 201 fouls home 101 under home's man offense set
foul(101, 201, play_type="pnr", defense="man")
# a TECH on home 102: fouled == fouler == 102, tagged technical. Sticky tags
# deliberately left at other/other — the charge-encoding collision case.
foul(102, 102, foul_type="technical", play_type="other", defense="other")
# a real charge for contrast: home 103 draws it, away 202 commits (other/other)
foul(103, 202, play_type="other", defense="other")

events = S.fetch_events([G])
fouls = [e for e in events if e["event_type"] == "foul"]
tech = next(e for e in fouls if e.get("foul_type") == "technical")

print("write path: foul_type persists through log_event -> fetch_events")
ok(tech["primary_player_id"] == 102 and tech["secondary_player_id"] == 102,
   "tech row carries the same-player trick (fouled == fouler == 102)")

print("PF: a player tech is a personal foul, charged once to the player")
pf = F.player_foul_ft(events=events)
ok(pf[102]["PF"] == 1, f"102 charged 1 PF for the tech, got {pf[102]['PF']}")
ok(pf[201]["PF"] == 1, "201 charged 1 PF for the regular foul")

print("drawn: nobody draws their own tech")
ok(pf[102]["drawn"] == 0, f"102 drew 0 fouls, got {pf[102]['drawn']}")
ok(pf[101]["drawn"] == 1, "101 drew the regular foul")
ok(pf[102].get("tech") == 1, f"102 tech count = 1, got {pf[102].get('tech')}")
ok(pf[201].get("tech", 0) == 0, "201 tech count = 0")

print("charges: a tech tagged other/other is NOT a charge")
ok(not CH.is_charge(tech), "is_charge(tech) is False")
pc = CH.player_charges(events)
ok(103 in pc and pc[103]["drawn"] == 1, "real charge still detected (103 drew)")
ok(102 not in pc, "tech'd player never appears in the charge ledger")

print("defenses: scheme foul reads skip techs on BOTH orientations")
drew = D.team_defense_fouls(1, game_ids=[G], offense=True)
ok(all(r["key"] != "other" or r["fouls"] == 1 for r in drew["rows"]),
   f"home drew 1 foul under 'other' (the charge), not 2: {drew['rows']}")
# committed side for AWAY: home 102's tech has shooter_team == home, which the
# orientation math would misread as an AWAY-committed foul. Must be excluded.
comm = D.team_defense_fouls(2, game_ids=[G], offense=False)
_c_other = next((r["fouls"] for r in comm["rows"] if r["key"] == "other"), 0)
ok(_c_other == 1,
   f"away committed 1 'other' foul (the charge), tech excluded: got {_c_other}")

print("playtypes: FD (fouls drawn per set) excludes techs")
tp = PT.team_named_playtypes(1, game_ids=[G], offense=True)
fd_other = next((r["FD"] for r in tp["rows"] if r["key"] == "other"), 0)
ok(fd_other == 1, f"team FD under 'other' = 1 (charge only), got {fd_other}")
pp = PT.player_named_playtypes(game_ids=[G])
ok("other" not in pp.get(102, {}),
   "player FD: the tech'd player gets no drawn credit")
ok(pp.get(103, {}).get("other", {}).get("FD") == 1,
   "player FD: the charge-drawer keeps hers")

print("feed: the public line reads technical, never '#2 foul (on #2)'")
pmap = {102: {"jersey": 2, "team": "home"}}
line = PF._play_text(tech, pmap)
ok(line == "#2 technical foul", f"got {line!r}")

print("API gate: server enforces the trick + strips tags, client can't miss it")
from fastapi.testclient import TestClient           # noqa: E402
from tracker.api import app                         # noqa: E402
from database.db import query                       # noqa: E402

execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('coach@test','coach','T','paid','tok-t')")
client = TestClient(app)
client.headers.update({"Authorization": "Bearer tok-t"})
r = client.post(f"/api/games/{G}/events", json={"events": [
    {  # a sloppy client: tech tagged but fouled != fouler, sticky tags riding
        "uuid": "u-tech", "event_type": "foul", "quarter": 2, "time": "4:00",
        "primary_player_id": 105, "secondary_player_id": 104,
        "foul_type": "technical", "play_type": "pnr", "defense": "man",
        "on_court": [p for p, _ in FLOOR], "officials_on": []},
    {  # a non-foul smuggling a foul_type must have it nulled
        "uuid": "u-tov-ft", "event_type": "turnover", "quarter": 2,
        "time": "3:50", "primary_player_id": 205, "foul_type": "technical",
        "on_court": [p for p, _ in FLOOR], "officials_on": []},
]}).json()
ok(all(x["status"] == "inserted" for x in r["results"]), "both events inserted")
row = query("SELECT * FROM game_events WHERE client_uuid='u-tech'")[0]
ok(row["primary_player_id"] == 104 and row["secondary_player_id"] == 104,
   "server forced fouled = fouler (the fouler pick wins)")
ok(row["foul_type"] == "technical" and row["play_type"] is None
   and row["defense"] is None, "tag kept, sticky set/scheme stripped")
row = query("SELECT * FROM game_events WHERE client_uuid='u-tov-ft'")[0]
ok(row["foul_type"] is None, "foul_type nulled on a non-foul event")

print(f"\nALL {PASS} ASSERTS PASS")
