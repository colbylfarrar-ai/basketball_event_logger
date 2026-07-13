"""
auto_season_rollover.py — calendar-driven New-Season rollover (idempotent).

Run daily by a systemd timer on the droplet:

    APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/auto_season_rollover.py

It advances the active season to the one that OPENS this calendar year (Oct 1
cutoff) ONLY when that season is strictly newer than the stored active season —
so it is forward-only, respects an early manual roll, and does nothing on every
run until the next Oct 1 boundary. When it does roll it runs the SAME path as
the New Season button (helpers.seasons.execute_rollover) with the auto
graduate/return split (grad_year-based; unknown grad_year carries forward).

Safe to run any number of times a day; prints one line so `journalctl` shows
what happened.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database          # noqa: E402
import helpers.game_events as GE                      # noqa: E402
import helpers.seasons as SEAS                        # noqa: E402


def main() -> int:
    initialize_database()
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    res = SEAS.auto_advance_if_due()
    if res.get("rolled"):
        # dashboards watch data_version to drop their caches; bump so the app
        # reflects the new season on the next interaction. (The FastAPI public
        # feed uses short TTL caches and derives its display season from the
        # newest finished game, so it needs no explicit clear here.)
        GE.bump_data_version()
        print(f"[{stamp}] season rollover: {res['from']} -> {res['to']} "
              f"(carried {res['carried']}, graduated {res['graduated']})")
    else:
        print(f"[{stamp}] season rollover: no-op "
              f"({res.get('reason')}; active {res.get('active')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
