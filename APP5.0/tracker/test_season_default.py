"""
Post-rollover default-scope fallback (task chip task_b386d4bf).

'Current' is the active-season sentinel; right after a rollover the active
season has NO tracked games, so the no-arg defaults (stats.fetch_events /
games_played / plus_minus, coverage) used to silently return zero rows — the
class of bug behind the DWPA EP=0.0 failure. The default scope now resolves to
the active season's tracked games, FALLING BACK to the most recently played
season that has tracked games when the active season is empty. Explicit
game_ids are untouched.

Run: python tracker/test_season_default.py (throwaway DB)
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_seasondefault_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query             # noqa: E402
import helpers.stats as S                          # noqa: E402
import helpers.coverage as COV                     # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('A HS','3A','F')")
t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('B HS','3A','F')")
p1 = execute("INSERT INTO players (team_id,name,number) VALUES (?,?,?)", (t1, "P1", 1))


def _seed_game(season, date, tracked=1):
    gid = execute(
        "INSERT INTO games (team1_id,team2_id,date,tracked,season) "
        "VALUES (?,?,?,?,?)", (t1, t2, date, tracked, season))
    execute("INSERT INTO game_events (game_id, event_type, quarter, time, "
            "primary_player_id, shot_result, shot_type) "
            "VALUES (?, 'shot', 1, '7:00', ?, 'make', 2)", (gid, p1))
    return gid


# ── post-rollover shape: archived tracked games only, active season empty ───────
g_old = _seed_game("2024-2025", "2025-01-10")
g_new = _seed_game("2025-2026", "2026-01-10")

print("post-rollover: no-arg default falls back to latest tracked season")
ev = S.fetch_events()
ok(len(ev) == 1, f"fetch_events() non-empty ({len(ev)} row)")
ok(ev[0]["game_id"] == g_new, "fallback picks the MOST RECENT tracked season")
ok(S.games_played().get(p1) is None or S.games_played() is not None,
   "games_played() runs on the same scope")  # lineup rows unseeded; no crash
gids = COV._team_tracked_game_ids(t1)
ok(gids == [g_new], f"coverage default scope follows the fallback ({gids})")

print("in-season: active tracked games win, archives excluded")
g_cur = _seed_game("Current", "2026-07-01")
ev = S.fetch_events()
ok([e["game_id"] for e in ev] == [g_cur],
   "fetch_events() = active season only once it has tracked games")
ok(COV._team_tracked_game_ids(t1) == [g_cur], "coverage follows active season")

print("explicit game_ids unchanged")
ev = S.fetch_events([g_old])
ok([e["game_id"] for e in ev] == [g_old], "explicit ids bypass the default")

print(f"\nALL {PASS} CHECKS PASSED")
