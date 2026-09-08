"""
verify_backup.py — prove the replica restores, don't assume it.

Run weekly by a systemd timer on the droplet:

    APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/verify_backup.py

THE BOOK §17 item 3: litestream is replicating and Settings offers a backup
download, and neither of them tells anyone it is WORKING. A replica that has
been silently failing for a month looks exactly like one that has not. This is
the difference between having backups and believing you do.

WHAT IT DOES. Restores the newest replica to a temp path with
`litestream restore`, opens the restored file read-only, runs
`PRAGMA integrity_check` and `PRAGMA foreign_key_check`, counts the rows that
matter, and compares them against the live book. Then it deletes the temp file,
including on failure — the same discipline `tools/pull_prod_snapshot.py`
already applies to its own temp.

WHAT COUNTS AS A PASS. Not "the counts are equal". A restore is taken from a
snapshot plus the WAL frames shipped so far, so it legitimately lags the live
book by whatever was written in the last few seconds. It passes when the
restore is INTACT and NOT BEHIND BY MORE THAN `MAX_LAG_ROWS` events — a
threshold, not an equality, because equality would cry wolf every time somebody
was mid-game.

EXIT CODES, because a timer's whole value is that something notices:
    0  verified
    1  restore produced a file that is damaged, or too far behind
    2  could not restore at all (no litestream, no config, no replica)
`journalctl -u app5-verify-backup` carries the reason either way.
"""
from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: How far behind the live book a healthy restore may be. Litestream ships WAL
#: frames continuously, so the gap is normally zero and is bounded in practice
#: by one game's worth of events — a tracked game is ~180 events. Anything past
#: this is replication that has stopped, not replication that is busy.
MAX_LAG_ROWS = 500

#: The tables whose emptiness would mean a restore that "worked" and is useless.
COUNTED = ("games", "game_events", "teams", "players", "officials")


def _live_path() -> Path:
    from database.db import get_db_path
    return Path(get_db_path())


def _counts(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out = {}
        for t in COUNTED:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                out[t] = None          # table absent = a finding, not a crash
        out["_integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        out["_fk"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        return out
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--config", default="/etc/litestream.yml")
    ap.add_argument("--max-lag", type=int, default=MAX_LAG_ROWS)
    a = ap.parse_args()

    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    live = _live_path()
    if not live.exists():
        print(f"[{stamp}] backup verify: FAILED — no live book at {live}")
        return 2
    if shutil.which("litestream") is None:
        print(f"[{stamp}] backup verify: FAILED — litestream is not installed")
        return 2
    if not Path(a.config).exists():
        print(f"[{stamp}] backup verify: FAILED — no config at {a.config}")
        return 2

    tmpdir = tempfile.mkdtemp(prefix="app5_verify_")
    dest = Path(tmpdir) / "restored.db"
    try:
        proc = subprocess.run(
            ["litestream", "restore", "-config", a.config, "-o", str(dest),
             str(live)],
            capture_output=True, text=True, timeout=900)
        if proc.returncode != 0 or not dest.exists():
            err = (proc.stderr or proc.stdout or "").strip().splitlines()
            print(f"[{stamp}] backup verify: FAILED — restore returned "
                  f"{proc.returncode}: {err[-1] if err else 'no output'}")
            return 2

        got = _counts(dest)
        want = _counts(live)
        if got["_integrity"] != "ok":
            print(f"[{stamp}] backup verify: FAILED — restored book is "
                  f"damaged (integrity_check: {got['_integrity']})")
            return 1
        if got["_fk"]:
            print(f"[{stamp}] backup verify: FAILED — restored book has "
                  f"{got['_fk']} foreign-key violations")
            return 1

        worst = None
        for t in COUNTED:
            if got.get(t) is None:
                print(f"[{stamp}] backup verify: FAILED — restored book has "
                      f"no `{t}` table")
                return 1
            lag = (want.get(t) or 0) - got[t]
            if worst is None or lag > worst[1]:
                worst = (t, lag)
        table, lag = worst
        size = dest.stat().st_size
        summary = " ".join(f"{t}={got[t]}" for t in COUNTED)
        if lag > a.max_lag:
            print(f"[{stamp}] backup verify: FAILED — restore is {lag} rows "
                  f"behind on `{table}` (limit {a.max_lag}). {summary}")
            return 1
        print(f"[{stamp}] backup verify: OK — restored {size / 1e6:.1f} MB, "
              f"integrity ok, 0 FK violations, worst lag {lag} rows on "
              f"`{table}`. {summary}")
        return 0
    except subprocess.TimeoutExpired:
        print(f"[{stamp}] backup verify: FAILED — restore timed out")
        return 2
    finally:
        # remove the temp copy whether or not any of the above worked; a
        # verification job that leaves a full copy of the book on a 2 GB box
        # every week is its own outage
        shutil.rmtree(tmpdir, ignore_errors=True)
        if os.path.exists(tmpdir):
            print(f"[{stamp}] backup verify: WARNING — could not remove "
                  f"{tmpdir}")


if __name__ == "__main__":
    raise SystemExit(main())
