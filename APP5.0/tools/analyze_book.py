"""
analyze_book.py — hand SQLite the statistics it has never had (idempotent).

Run daily by a systemd timer on the droplet, beside the rollover:

    APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/analyze_book.py

WHAT IT FIXES. `ANALYZE` had never been run on this book, so `sqlite_stat1` did
not exist and the query planner was choosing from index shape alone. On the
hottest predicate in the app — `WHERE tracked=1 AND season=?`, which appears at
74 sites — it took `idx_games_season` (13,362 matching rows) over
`idx_games_tracked` (63). Measured on the production snapshot:

    before   2.826 ms/call   SEARCH games USING INDEX idx_games_season
    after    0.127 ms/call   SEARCH games USING INDEX idx_games_tracked
    ANALYZE  0.09 s on the whole 17 MB book

WHY IT IS A TIMER AND NOT A STARTUP STEP. It is a WRITE. Putting it in
`initialize_database()` would take a writer's lock on every page load and every
tracker request — including a Friday night with three games being logged into a
1 vCPU box. Nightly is often enough: the planner's choices drift with the shape
of the book, and the book changes by a game at a time.

WHY IT DOES NOT GO THROUGH `database.db.execute`. That path writes an audit row
per statement, and attributing a maintenance no-op to a coach every night would
fill the audit log with the one thing nobody did.
"""
from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection, initialize_database, query  # noqa: E402


def main() -> int:
    initialize_database()
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    t0 = time.perf_counter()
    conn = get_connection()
    conn.execute("ANALYZE")
    conn.commit()
    secs = time.perf_counter() - t0
    rows = query("SELECT COUNT(*) n FROM sqlite_stat1")[0]["n"]
    print(f"[{stamp}] ANALYZE: {rows} index statistics in {secs:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
