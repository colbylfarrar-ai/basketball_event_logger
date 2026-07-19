"""
server_control.py — admin-triggered service restart (2026-07-19).

Two admin surfaces already end with "takes effect on the next app restart"
(living-recal adoption in `model_constants`, and reverting to the committed
defaults). This closes that loop from inside the app instead of an SSH session.

THE SUDOERS CONTRACT — read before touching RESTART_ARGV.

`app5` on the box holds NOPASSWD on exactly three command strings:

    /usr/bin/systemctl restart app5-web app5-tracker
    /usr/bin/systemctl restart app5-web
    /usr/bin/systemctl restart app5-tracker

sudo matches the FULL command line, so the argv below must stay character-exact.
Appending a flag — `--no-block` is the tempting one — stops matching the
NOPASSWD rule, falls through to the general `(ALL : ALL) ALL` rule, and blocks
forever on a password prompt no web request can answer. test_server_control.py
freezes the argv for exactly this reason. `app5-litestream` has no grant and is
therefore out of scope.

SELF-RESTART. `app5-web` restarting `app5-web` kills the caller — same cgroup.
systemd accepts the job over dbus BEFORE it stops the unit, so the restart
completes anyway, but this process does not survive to see it. Hence
record_restart() writes BEFORE do_restart() fires, and the return code is never
inspected: the "last restart" timestamp the reconnected page reads back is the
only honest confirmation available.

Streamlit-free; pure app_settings/audit I/O + one subprocess call.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime

from database.db import query, execute

_KEY = "server:last_restart"

# Frozen — see the sudoers contract above. Do not add flags.
RESTART_ARGV = ["sudo", "systemctl", "restart", "app5-web", "app5-tracker"]

_SYSTEMCTL = "/usr/bin/systemctl"


def restart_available() -> tuple[bool, str]:
    """(can_restart, human_reason). False on a local dev box so the panel can
    disable the button WITH an explanation rather than hiding it or erroring."""
    if sys.platform != "linux":
        return False, f"not a systemd host ({sys.platform}) — local dev only"
    if not os.path.exists(_SYSTEMCTL):
        return False, f"{_SYSTEMCTL} not found on this host"
    return True, ""


def live_games() -> list[dict]:
    """Games being tracked RIGHT NOW — the restart's collateral damage.

    Mirrors the app's own live definition (public_feed._game_payload): `tracked`
    marks a game FINAL, so live = not tracked AND at least one event logged.
    Date-restricted to today so an abandoned half-tracked game from last month
    never trips the warning."""
    today = datetime.now().strftime("%Y-%m-%d")
    return [dict(r) for r in query(
        "SELECT g.id, t1.name AS home, t2.name AS away, "
        "       COUNT(e.id) AS events "
        "FROM games g "
        "JOIN teams t1 ON t1.id = g.team1_id "
        "JOIN teams t2 ON t2.id = g.team2_id "
        "JOIN game_events e ON e.game_id = g.id "
        "WHERE g.date = ? AND COALESCE(g.tracked, 0) = 0 "
        "GROUP BY g.id ORDER BY g.id", (today,))]


def record_restart(email: str) -> dict:
    """Stamp who restarted and when, BEFORE the command fires (this process
    won't outlive it). Returns the stamp. app_settings is audit-skipped in
    db.py, so the audit row is written explicitly — a restart is moderation
    signal, not config noise."""
    stamp = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "by": (email or "").strip().lower()}
    execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (_KEY, json.dumps(stamp, separators=(",", ":"))))
    execute("INSERT INTO audit_log (actor, op, table_name, detail) "
            "VALUES (?, ?, ?, ?)",
            (stamp["by"], "RESTART", "app_settings",
             "restarted app5-web + app5-tracker from the admin panel"))
    return stamp


def last_restart() -> dict | None:
    """The most recent stamp as ``{'at','by'}``, or None if never restarted
    from the panel."""
    r = query("SELECT value FROM app_settings WHERE key=?", (_KEY,))
    if not r or not r[0]["value"]:
        return None
    try:
        d = json.loads(r[0]["value"])
        return d if isinstance(d, dict) else None
    except (ValueError, TypeError):
        return None


def do_restart() -> None:
    """Fire the restart. Detached so the request thread isn't waiting on a
    process that is about to be killed along with this one. No shell, no added
    flags (sudoers contract). Never raises into the page — a failure to spawn
    is reported by the ABSENCE of a new timestamp after reconnect."""
    subprocess.Popen(RESTART_ARGV, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
