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


# ── Capacity monitor (batch item 5b) ──────────────────────────────────────────
# "Is the box close to needing an upgrade?" read straight from /proc — zero deps
# (no psutil, pip-only ethos). The binding constraint on this droplet is the 1
# vCPU (Streamlit reruns are CPU-bound and serialize on one core), so LOAD vs
# nproc is weighted the heaviest; RAM is comfortable at ~2 GB but watched for the
# no-swap OOM edge. Linux-only — returns available=False elsewhere so the card
# can explain rather than error. See the batch doc §5c for the measured baseline.

def _meminfo() -> dict:
    """Parse /proc/meminfo → {key: kB int}. Empty on any read failure."""
    out = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                k, _, rest = line.partition(":")
                out[k.strip()] = int(rest.strip().split()[0])
    except Exception:
        return {}
    return out


def server_capacity() -> dict:
    """Point-in-time box health for the admin capacity card.

    Returns {'available': bool, 'reason': str, 'ncpu': int,
             'load1', 'load5', 'load15': float, 'load_ratio': float,
             'ram_pct', 'disk_pct': float, 'ram_total_mb', 'ram_avail_mb': int,
             'status': 'healthy'|'watch'|'upgrade-soon',
             'drivers': [str]}.
    `load_ratio` = 1-min load average / vCPU count (>1 means work is queuing on
    the core). `status` is the worst of the three axes; `drivers` names which
    axis/axes pushed it there so the founder sees WHY, not just a colour."""
    if sys.platform != "linux":
        return {"available": False,
                "reason": f"not a Linux host ({sys.platform}) — prod only"}

    ncpu = os.cpu_count() or 1
    try:
        load1, load5, load15 = os.getloadavg()
    except (OSError, AttributeError):
        load1 = load5 = load15 = 0.0
    load_ratio = load1 / ncpu if ncpu else load1

    mi = _meminfo()
    ram_total = mi.get("MemTotal", 0)                     # kB
    ram_avail = mi.get("MemAvailable", mi.get("MemFree", 0))
    ram_pct = (ram_total - ram_avail) * 100.0 / ram_total if ram_total else 0.0

    try:
        sv = os.statvfs("/")
        disk_total = sv.f_blocks * sv.f_frsize
        disk_free = sv.f_bavail * sv.f_frsize
        disk_pct = (disk_total - disk_free) * 100.0 / disk_total \
            if disk_total else 0.0
    except OSError:
        disk_pct = 0.0

    # thresholds: CPU weighted hardest (the 1-vCPU bottleneck), RAM watched for
    # the no-swap edge, disk a slow-moving backstop.
    drivers = []
    status = "healthy"

    def _bump(level):
        nonlocal status
        order = {"healthy": 0, "watch": 1, "upgrade-soon": 2}
        if order[level] > order[status]:
            status = level

    if load_ratio > 1.5:
        _bump("upgrade-soon"); drivers.append("CPU load")
    elif load_ratio > 0.8:
        _bump("watch"); drivers.append("CPU load")
    if ram_pct > 90:
        _bump("upgrade-soon"); drivers.append("RAM")
    elif ram_pct > 75:
        _bump("watch"); drivers.append("RAM")
    if disk_pct > 90:
        _bump("upgrade-soon"); drivers.append("disk")
    elif disk_pct > 80:
        _bump("watch"); drivers.append("disk")

    return {"available": True, "reason": "", "ncpu": ncpu,
            "load1": load1, "load5": load5, "load15": load15,
            "load_ratio": load_ratio,
            "ram_pct": ram_pct, "disk_pct": disk_pct,
            "ram_total_mb": ram_total // 1024, "ram_avail_mb": ram_avail // 1024,
            "status": status, "drivers": drivers}
