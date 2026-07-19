"""
Admin restart control — guards for helpers/server_control.py (2026-07-19).

The load-bearing test here is the ARGV FREEZE. The restart runs under a sudoers
NOPASSWD rule that matches the full command line; adding any flag (`--no-block`
is the tempting one) silently stops matching, falls through to the password-
required rule, and hangs. Nothing surfaces that until an admin clicks the button
on a live box, so the argv is pinned here instead.

Run: python tracker/test_server_control.py (throwaway DB; live DB untouched)
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_restart_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query          # noqa: E402
import helpers.server_control as SC             # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── seed ────────────────────────────────────────────────────────────────────────
TODAY = datetime.now().strftime("%Y-%m-%d")
LAST_MONTH = (datetime.now() - timedelta(days=32)).strftime("%Y-%m-%d")

execute("INSERT INTO teams (id, name, gender, class) VALUES (1,'Home HS','F','3A')")
execute("INSERT INTO teams (id, name, gender, class) VALUES (2,'Away HS','F','3A')")

# 10 = live today (untracked + events)   -> MUST warn
# 11 = final today (tracked + events)    -> must NOT warn
# 12 = scheduled today (no events)       -> must NOT warn
# 13 = abandoned last month (untracked + events) -> must NOT warn (date guard)
for gid, date, tracked in ((10, TODAY, 0), (11, TODAY, 1),
                           (12, TODAY, 0), (13, LAST_MONTH, 0)):
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
            "VALUES (?, 1, 2, ?, ?, '2025-2026')", (gid, date, tracked))
for gid in (10, 11, 13):
    execute("INSERT INTO game_events (game_id, event_type, quarter, time) "
            "VALUES (?, 'shot', 1, '08:00')", (gid,))


# ── the argv freeze ─────────────────────────────────────────────────────────────
def test_argv_matches_sudoers():
    """Character-exact against the NOPASSWD rule on the box."""
    ok(SC.RESTART_ARGV == ["sudo", "systemctl", "restart",
                           "app5-web", "app5-tracker"],
       "RESTART_ARGV matches the sudoers command string exactly")
    ok(all(not a.startswith("-") for a in SC.RESTART_ARGV[1:]),
       "no flags in the argv (any flag breaks the sudoers match)")
    ok("app5-litestream" not in SC.RESTART_ARGV,
       "litestream stays out (no sudo grant for it)")


def test_restart_available_reports_a_reason():
    can, why = SC.restart_available()
    if sys.platform != "linux":
        ok(can is False, "restart unavailable off-systemd")
        ok(bool(why), f"disabled reason is human-readable: {why!r}")
    else:
        ok(isinstance(can, bool), "linux host resolves to a bool")


# ── live-game warning ───────────────────────────────────────────────────────────
def test_live_games_finds_only_the_live_one():
    ids = [g["id"] for g in SC.live_games()]
    ok(10 in ids, "untracked game with events today counts as live")
    ok(11 not in ids, "tracked (final) game is not live")
    ok(12 not in ids, "game with no events is not live")
    ok(13 not in ids, "abandoned untracked game from last month is not live")
    ok(len(ids) == 1, f"exactly one live game, got {ids}")


def test_live_game_carries_team_names():
    g = SC.live_games()[0]
    ok(g["home"] == "Home HS" and g["away"] == "Away HS",
       "live game names both teams for the warning")
    ok(g["events"] == 1, "live game reports its event count")


# ── stamp round-trip ────────────────────────────────────────────────────────────
def test_record_and_read_back():
    ok(SC.last_restart() is None, "no stamp before the first restart")
    SC.record_restart("Admin@Example.COM")
    got = SC.last_restart()
    ok(got is not None, "stamp round-trips through app_settings")
    ok(got["by"] == "admin@example.com", "actor email is normalized lowercase")
    ok(len(got["at"]) == 19, f"timestamp is a full datetime, got {got['at']!r}")


def test_restart_is_audited():
    rows = query("SELECT actor, op, detail FROM audit_log WHERE op='RESTART'")
    ok(len(rows) == 1, "restart wrote exactly one audit row")
    ok(rows[0]["actor"] == "admin@example.com", "audit row names the admin")
    ok("app5-web" in rows[0]["detail"], "audit detail says what was restarted")


def test_second_restart_replaces_the_stamp():
    SC.record_restart("other@example.com")
    ok(SC.last_restart()["by"] == "other@example.com",
       "newest restart wins the stamp")
    ok(len(query("SELECT key FROM app_settings WHERE key='server:last_restart'")) == 1,
       "stamp stays a single row (no history bloat — DB stays small)")


# ── the spawn ───────────────────────────────────────────────────────────────────
def test_do_restart_spawns_detached():
    """Monkeypatched — this test never restarts anything."""
    seen = {}

    class _FakePopen:
        def __init__(self, argv, **kw):
            seen["argv"] = argv
            seen["kw"] = kw

    real = SC.subprocess.Popen
    SC.subprocess.Popen = _FakePopen
    try:
        SC.do_restart()
    finally:
        SC.subprocess.Popen = real

    ok(seen["argv"] == SC.RESTART_ARGV, "spawns the frozen argv")
    ok(seen["kw"].get("start_new_session") is True,
       "detached — not waiting on a process about to be killed with us")
    ok("shell" not in seen["kw"], "no shell=True (argv list, not a string)")


for _fn in (test_argv_matches_sudoers, test_restart_available_reports_a_reason,
            test_live_games_finds_only_the_live_one,
            test_live_game_carries_team_names, test_record_and_read_back,
            test_restart_is_audited, test_second_restart_replaces_the_stamp,
            test_do_restart_spawns_detached):
    print(f"\n{_fn.__name__}:")
    _fn()

print(f"\nAll {PASS} checks passed.")
