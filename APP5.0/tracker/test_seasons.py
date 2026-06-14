"""
Smoke test for the season partition (model A), against a THROWAWAY DB.
Run: python tracker/test_seasons.py

Proves: stats default to the ACTIVE season ('Current'); an archived season is
excluded from the current view but reachable explicitly; the New-Season rollover
SQL moves 'Current' rows under a label so seasons stop blending.

NOTE: the throwaway data dir is seeded with the repo's stale analytics.db (via
db._migrate_legacy_db), so assertions are MEMBERSHIP/team-scoped (like
test_entitlement), never raw counts over the whole table.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_season_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query             # noqa: E402
import helpers.team_ratings as TR                    # noqa: E402
import helpers.team_analytics as TA                  # noqa: E402
import helpers.seasons as SZ                          # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# Fresh teams (high ids) so team-scoped queries see only OUR games.
A = execute("INSERT INTO teams (name,class,gender) VALUES ('SeasonTestA','3A','F')")
B = execute("INSERT INTO teams (name,class,gender) VALUES ('SeasonTestB','3A','F')")


def _game(season, hs, as_):
    return execute("INSERT INTO games (team1_id,team2_id,date,home_score,away_score,"
                   "tracked,season) VALUES (?,?, '2025-12-01', ?,?, 1, ?)",
                   (A, B, hs, as_, season))


g_cur = _game("Current", 60, 50)      # active season  (A wins)
g_old = _game("2099-2100", 40, 70)    # archived season (A loses) — unique label

print("active label")
ok(SZ.active_label() == "2025-2026", "active_label seeded to 2025-2026")
ok("2099-2100" in SZ.archived_labels(), "archived label discovered")
ok(SZ.is_current("Current") and SZ.is_current(None) and not SZ.is_current("2099-2100"),
   "is_current sentinel logic")

print("_finished_games season scoping (membership)")
cur_ids = {r["id"] for r in TR._finished_games(gender="F")}
ok(g_cur in cur_ids and g_old not in cur_ids, "default view = active season only")
old_ids = {r["id"] for r in TR._finished_games(gender="F", season="2099-2100")}
ok(g_old in old_ids and g_cur not in old_ids, "explicit archived season reachable")
all_ids = {r["id"] for r in TR._finished_games(gender="F", season=None)}
ok(g_cur in all_ids and g_old in all_ids, "season=None spans all seasons")

print("team_game_log season scoping (team-scoped -> only our games)")
log_cur = TA.team_game_log(A)
ok(len(log_cur) == 1 and log_cur[0]["game_id"] == g_cur and log_cur[0]["won"],
   "team log default = active season (the 60-50 win, archive loss excluded)")
ok(len(TA.team_game_log(A, season=None)) == 2, "team log season=None = all seasons")
ok(len(TA.team_game_log(A, season="2099-2100")) == 1, "team log reaches the archive")

print("entry points forward season (archive viewing)")
tb_old = TA.team_bundle(A, season="2099-2100")
ok(any(r["game_id"] == g_old for r in tb_old["game_log"]),
   "team_bundle(season=archive) surfaces the archived game")
ok(all(r["game_id"] != g_old for r in TA.team_bundle(A)["game_log"]),
   "team_bundle default (Current) excludes the archive")
ok(A in TR.score_ratings(gender="F", season="2099-2100"),
   "score_ratings accepts + forwards season")
ok(isinstance(TR.tracked_ratings(gender="F", season="2099-2100"), dict),
   "tracked_ratings accepts season without error")

print("rollover SQL partitions seasons")
execute("UPDATE games SET season=? WHERE season='Current'", ("2025-2026",))
execute("INSERT OR REPLACE INTO app_settings (key,value) VALUES ('active_season','2026-2027')")
ok(len(TA.team_game_log(A)) == 0, "after rollover the new (empty) season has no games for A")
ok(len(TA.team_game_log(A, season="2025-2026")) == 1, "last season archived intact")
ok(SZ.active_label() == "2026-2027", "active label advanced")

print(f"\nALL {PASS} CHECKS PASSED")
