"""
rebuild_rating_history.py — keep the rank trajectory current without a press.

Run daily by a systemd timer on the droplet, beside the rollover and ANALYZE:

    APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/rebuild_rating_history.py

WHY IT IS A TIMER. THE BOOK §17 item 4: all three résumé surfaces — the rank
trajectory, the news feed's Power deltas and the risers board — are empty until
someone opens Rankings and presses "Rebuild rating history". That press is a
memory, and memories fail in January. The rule §3 states is that any feature
whose correctness depends on remembering to press something will be wrong by
mid-season.

IDEMPOTENT BY CONSTRUCTION, which is what makes it safe to run nightly.
`rating_history.backfill_weekly` writes INSERT OR IGNORE per
(day, gender, system, team_id), so a second run over a week that already has a
board writes nothing. It also skips weeks under BACKFILL_MIN_GAMES finished
games, where a rating is the sample arriving rather than anything a team did.

WHAT IT COVERS. Both genders, and the season a READ would scope to — which is
`default_read_season()`, not the literal 'Current'. Between a rollover and the
new year's first game, 'Current' names an empty partition, so a rebuild keyed
on it would report "nothing to rebuild" every night while the season everybody
is actually looking at went stale. `--season` overrides for a manual catch-up.

ONE HONEST CAVEAT, inherited from the engine: a reconstructed board uses
today's model constants rather than whatever was adopted at the time, so a
recal makes backfilled history disagree with history that accrued live.
Re-running after a recal is both worth doing and safe.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database          # noqa: E402
import helpers.rating_history as RH                   # noqa: E402
import helpers.seasons as SEAS                        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--season", default=None,
                    help="season label (default: the current READ season)")
    ap.add_argument("--gender", choices=("M", "F"), default=None,
                    help="one league only (default: both)")
    a = ap.parse_args()

    initialize_database()
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    season = a.season or SEAS.default_read_season()
    genders = (a.gender,) if a.gender else ("F", "M")

    total_days = total_rows = 0
    for g in genders:
        try:
            res = RH.backfill_weekly(g, season=season)
        except Exception as exc:                    # never take the timer down
            print(f"[{stamp}] rating history {g} {season}: FAILED "
                  f"{type(exc).__name__}: {exc}")
            continue
        total_days += res["days"]
        total_rows += res["rows"]
        if res["days"]:
            print(f"[{stamp}] rating history {g} {season}: "
                  f"{res['days']} weeks ({res['from']} -> {res['to']}), "
                  f"{res['rows']} rows written, {res['skipped']} thin weeks "
                  f"skipped")
        else:
            print(f"[{stamp}] rating history {g} {season}: no-op "
                  f"(no finished games)")
    if total_rows == 0 and total_days:
        # every week already had a board — the steady state, and worth saying
        # so plainly in journalctl rather than looking like a failure
        print(f"[{stamp}] rating history: already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
