"""
pull_prod_snapshot.py — take a consistent, read-only copy of the PRODUCTION book
and leave it somewhere analysis can point at offline.

Why this exists: the QOL survey (2026-09-05) and the ten-part sweep (2026-09-06)
both ran against `%LOCALAPPDATA%\\APP5\\analytics.db` and both called it "the live
book". It is not — it is a development copy, and on 2026-09-06 it was three months
and twenty tracked games behind production (43 vs 63). Every sample-size
conclusion in both documents had to be re-measured. This script is the fix: one
command, no ambiguity about which book you are reading.

    python tools/pull_prod_snapshot.py                 # -> ~/app5_prod/analytics.db
    python tools/pull_prod_snapshot.py --dest D:/books # -> D:/books/analytics.db
    APP5_DATA_DIR=~/app5_prod python -m streamlit run Main.py

SAFETY — this only ever READS production:
  * the source is opened `mode=ro` through a URI, so SQLite itself refuses a write;
  * `.backup()` is used rather than `cp`, because the live DB is in WAL mode and
    copying the file under an open writer yields a torn read plus orphaned
    -wal/-shm sidecars (DEPLOY.md step 3 documents that exact failure);
  * the only thing written on the server is a temp file under /tmp, and it is
    removed on the way out even if the transfer fails.

The droplet has no `sqlite3` CLI, so the remote half runs through `python3`, which
is present because the app itself needs it.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

HOST = os.environ.get("APP5_PROD_HOST", "app5@107.170.27.154")
REMOTE_DB = os.environ.get("APP5_PROD_DB", "/var/lib/app5/analytics.db")
REMOTE_TMP = "/tmp/app5_prod_snap.db"

# Runs on the droplet. Kept as one string so there is a single quoting boundary.
_REMOTE = f"""
import sqlite3, os
src = sqlite3.connect("file:{REMOTE_DB}?mode=ro", uri=True)
if os.path.exists("{REMOTE_TMP}"):
    os.remove("{REMOTE_TMP}")
out = sqlite3.connect("{REMOTE_TMP}")
src.backup(out)
out.close(); src.close()
c = sqlite3.connect("file:{REMOTE_TMP}?mode=ro", uri=True)
print("BYTES", os.path.getsize("{REMOTE_TMP}"))
for label, q in (("games", "SELECT COUNT(*) FROM games"),
                 ("tracked", "SELECT COUNT(*) FROM games WHERE tracked=1"),
                 ("events", "SELECT COUNT(*) FROM game_events"),
                 ("players", "SELECT COUNT(*) FROM players"),
                 ("officials", "SELECT COUNT(*) FROM officials")):
    print(label.upper(), c.execute(q).fetchone()[0])
c.close()
"""


def _ssh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                           HOST] + cmd, capture_output=True, text=True, **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dest", default=os.path.join(os.path.expanduser("~"), "app5_prod"),
                    help="directory to write analytics.db into "
                         "(point APP5_DATA_DIR here afterwards)")
    args = ap.parse_args()

    dest_dir = os.path.abspath(args.dest)
    dest = os.path.join(dest_dir, "analytics.db")
    os.makedirs(dest_dir, exist_ok=True)

    print(f"source : {HOST}:{REMOTE_DB}  (read-only)")
    print(f"dest   : {dest}")

    r = _ssh(["python3", "-"], input=_REMOTE)
    if r.returncode != 0:
        print("remote snapshot FAILED:\n" + (r.stderr or r.stdout), file=sys.stderr)
        return 1
    counts = dict(line.split(maxsplit=1) for line in r.stdout.strip().splitlines()
                  if " " in line)
    print("remote snapshot ok — " + "  ".join(f"{k.lower()}={v}"
                                              for k, v in counts.items()))

    try:
        s = subprocess.run(["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                            f"{HOST}:{REMOTE_TMP}", dest],
                           capture_output=True, text=True)
        if s.returncode != 0:
            print("scp FAILED:\n" + (s.stderr or s.stdout), file=sys.stderr)
            return 1
    finally:
        # never leave the temp behind, even on a failed transfer
        _ssh(["rm", "-f", REMOTE_TMP])

    got = os.path.getsize(dest)
    want = int(counts.get("BYTES", 0))
    if want and got != want:
        print(f"SIZE MISMATCH: got {got}, remote reported {want}", file=sys.stderr)
        return 1

    # Prove the copy is readable and internally sound before anyone trusts it.
    import sqlite3
    c = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    ok = c.execute("PRAGMA integrity_check").fetchone()[0]
    trk = c.execute("SELECT COUNT(*) FROM games WHERE tracked=1").fetchone()[0]
    c.close()
    print(f"local  : {got:,} bytes · integrity_check={ok} · tracked={trk}")
    if ok != "ok":
        return 1

    print(f"\ndone. use it with:\n    APP5_DATA_DIR={dest_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
