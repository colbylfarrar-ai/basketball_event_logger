"""Deleting a team must not silently destroy its games.

`teams` is the root of the widest cascade in the schema: games.team1_id /
team2_id are ON DELETE CASCADE, games.id cascades into game_events, and that
cascades into game_event_lineup. So a plain `DELETE FROM teams WHERE id=?` —
which is what the Input Hub's team editor used to run — takes every game the
team ever played and every tracked event in them, with no FK error and no
warning. Tidying the team list before a season is exactly when that happens.

Players and officials have an `archived` column to fall back on; teams do not,
so the correct outcome is to REFUSE and say what would have been lost.

Hermetic: own temp DB, seeded rows. Run:
    python tracker/test_team_delete_guard.py
"""
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_teamdel_test_")
sys.path.insert(0, str(_APP))

from database.db import (execute, query, delete_or_block_team,   # noqa: E402
                         team_history_counts)

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def counts():
    return {t: query(f"SELECT COUNT(*) c FROM {t}")[0]["c"]
            for t in ("teams", "games", "game_events", "game_event_lineup")}


# ── seed ──────────────────────────────────────────────────────────────────────
execute("INSERT INTO teams (id, name, gender, class) VALUES (1,'Withgames','F','3A')")
execute("INSERT INTO teams (id, name, gender, class) VALUES (2,'Opponent','F','3A')")
execute("INSERT INTO teams (id, name, gender, class) VALUES (3,'Empty','F','3A')")
execute("INSERT INTO players (id, team_id, name, number) VALUES (1,1,'A',1)")
execute("INSERT INTO players (id, team_id, name, number) VALUES (2,2,'B',2)")
execute("INSERT INTO games (id, team1_id, team2_id, date, season, tracked) "
        "VALUES (10, 1, 2, '2026-01-05', 'Current', 1)")
for i in range(5):
    execute("INSERT INTO game_events (game_id, quarter, time, event_type, "
            "primary_player_id) VALUES (10, 1, '8:00', 'shot', 1)")
for r in query("SELECT id FROM game_events"):
    execute("INSERT INTO game_event_lineup (event_id, player_id, team_id) "
            "VALUES (?,1,1)", (r["id"],))

_before = counts()
print(f"seeded: {_before}")


print("\n-- the cascade this guard exists to stop ----------------------------")

c = team_history_counts(1)
ok(c["games"] == 1 and c["events"] == 5,
   f"team_history_counts names what a delete would take ({c['games']} game, "
   f"{c['events']} events)")

ok(delete_or_block_team(1) == "blocked",
   "a team with games is REFUSED, not deleted")

_after = counts()
ok(_after == _before,
   f"and nothing was destroyed — table counts unchanged {_after}")
ok(query("SELECT id FROM teams WHERE id=1"),
   "the team is still there to rename instead")


print("\n-- an unused team still deletes cleanly -----------------------------")

ok(team_history_counts(3) == {"players": 0, "games": 0, "events": 0,
                              "manual_box": 0},
   "a team with no footprint reports nothing to lose")
ok(delete_or_block_team(3) == "deleted",
   "so it hard-deletes — the guard does not block ordinary tidying")
ok(not query("SELECT id FROM teams WHERE id=3"), "and it is gone")


print("\n-- a team whose only footprint is a roster still deletes ------------")

execute("INSERT INTO teams (id, name, gender, class) VALUES (4,'Rosteronly','F','3A')")
execute("INSERT INTO players (id, team_id, name, number) VALUES (9,4,'C',3)")
ok(team_history_counts(4)["players"] == 1 and team_history_counts(4)["games"] == 0,
   "roster rows alone are not game history")
ok(delete_or_block_team(4) == "deleted",
   "players cascade harmlessly — only GAMES block the delete")


print("\n-- the Input Hub calls the guard, not a raw DELETE ------------------")

_src = (_APP / "pages" / "1_Input_Hub.py").read_text(encoding="utf-8")
_del_team = _src[_src.index("def del_team("):]
_del_team = _del_team[:_del_team.index("\n        errs =")]
ok("delete_or_block_team" in _del_team,
   "del_team routes through the guard")
ok("DELETE FROM teams" not in _del_team,
   "and no raw cascade delete survives in that handler")

print(f"\nALL {PASS} CHECKS PASSED")
