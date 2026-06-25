"""
Daily incremental refresh of the current OSSAA season.

The by-date schedule view on ossaarankings is a Telerik widget that can't be
driven reliably without a headless browser, so this uses the rock-solid static
per-team pages instead: it crawls both genders from current-season seeds, keeps
only games inside the requested DATE RANGE (default: today), and ingests with
score-update —
  * new games           -> inserted
  * existing UNTRACKED   -> scores filled in / corrected (e.g. a game now played)
  * tracked games        -> never touched
So running it daily keeps schedules + scores current without ever duplicating.

Run on the server (writes the live DB):
    cd /home/app5/app5/APP5.0
    APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/ossaa_refresh.py             # today
    APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/ossaa_refresh.py --days 3    # last 3 days
    APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/ossaa_refresh.py --from 2026-01-10 --to 2026-01-15

Seeds are SEASON-SPECIFIC OSSAA team-ids (a team page shows that id's own season).
The 2025-2026 defaults are Holland Hall boys/girls; pass --seed-boys/--seed-girls
to point at next season once it's posted (any current-season team id works).
"""
from __future__ import annotations

import argparse
import datetime
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import ossaa_import as OI       # noqa: E402
import helpers.ossaa_sync as SYNC          # noqa: E402

SEEDS = {"Boys": 174154, "Girls": 174155}  # 2025-2026 (Holland Hall)


def crawl_all_gender(seed, gender, *, force=True, log=print):
    """BFS every team of one gender (no class filter), fresh fetches by default
    so scores reflect the latest posting."""
    want = OI.GENDER_MAP[gender]
    seen, out, q = set(), [], deque([seed])
    while q:
        tid = q.popleft()
        if tid in seen:
            continue
        seen.add(tid)
        try:
            s = OI.parse_schedule(tid, OI.fetch(tid, force=force))
        except Exception:
            continue
        if s.gender != want:
            continue
        out.append(s)
        if len(out) % 50 == 0:
            log(f"  {gender}: {len(out)} teams…")
        for g in s.games:
            if g.opp_id and g.opp_id not in seen:
                q.append(g.opp_id)
    return out


def teams_playing(lo, hi, genders=None):
    """OSSAA ids of teams that already have a game in [lo, hi] this season — the
    only teams worth re-fetching to refresh that range's scores. `genders` is an
    optional list of 'M'/'F'."""
    from database import db
    q = ("SELECT DISTINCT t.ossaa_id oid FROM teams t "
         "JOIN games g ON (t.id = g.team1_id OR t.id = g.team2_id) "
         "WHERE g.date BETWEEN ? AND ? AND g.season='Current' "
         "AND t.ossaa_id IS NOT NULL")
    p = [lo, hi]
    if genders:
        q += " AND t.gender IN (%s)" % ",".join("?" * len(genders))
        p += list(genders)
    return [r["oid"] for r in db.query(q, tuple(p))]


def fast_refresh(lo, hi, genders=None, *, log=print):
    """Refresh a date range by re-fetching ONLY the teams already scheduled to
    play in it (~20-40 pages for a single day, vs ~960 for a full crawl). Fills in
    scores for games now played and any schedule tweaks for those teams; never
    touches tracked games; no duplicates. Returns (ingest_result, n_fetched).
    """
    ids = teams_playing(lo, hi, genders)
    log(f"{len(ids)} teams play {lo}..{hi} — fetching those pages")
    plan = OI.Plan(window=(lo, hi))
    for i, tid in enumerate(ids, 1):
        try:
            plan.add_game(OI.parse_schedule(tid, OI.fetch(tid, force=True)))
        except Exception:
            continue
        if i % 20 == 0:
            log(f"  fetched {i}/{len(ids)}")
    rec = SYNC.reconcile(plan)
    overrides = {}
    for amb in rec["ambiguous"]:
        want = SYNC._norm_tokens(amb["name"])
        eq = [c for c in amb["candidates"] if SYNC._norm_tokens(c["name"]) == want]
        if len(eq) == 1:
            overrides[amb["name"]] = eq[0]["id"]
    return SYNC.ingest(plan, overrides=overrides, update_scores=True), len(ids)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Daily OSSAA season refresh (date-range, score-update)")
    ap.add_argument("--from", dest="frm", help="start date YYYY-MM-DD")
    ap.add_argument("--to", help="end date YYYY-MM-DD")
    ap.add_argument("--days", type=int, help="last N days through today")
    ap.add_argument("--seed-boys", type=int, default=SEEDS["Boys"])
    ap.add_argument("--seed-girls", type=int, default=SEEDS["Girls"])
    ap.add_argument("--gender", choices=["Boys", "Girls", "both"], default="both")
    ap.add_argument("--full", action="store_true",
                    help="full BFS crawl (~960 teams) instead of the fast "
                         "DB-seeded fetch — use to discover brand-new teams/games")
    a = ap.parse_args(argv)

    today = datetime.date.today()
    if a.frm and a.to:
        lo, hi = a.frm, a.to
    elif a.days:
        lo, hi = (today - datetime.timedelta(days=a.days - 1)).isoformat(), today.isoformat()
    else:
        lo = hi = today.isoformat()
    print(f"refresh window {lo} .. {hi}")

    genders = None
    if a.gender != "both":
        genders = ["M"] if a.gender == "Boys" else ["F"]

    if not a.full:
        res, n = fast_refresh(lo, hi, genders)
        print(f"fast refresh fetched {n} teams. RESULT:", res)
        return

    plan = OI.Plan(window=(lo, hi))
    seeds = [("Boys", a.seed_boys), ("Girls", a.seed_girls)]
    if a.gender != "both":
        seeds = [g for g in seeds if g[0] == a.gender]
    for gender, seed in seeds:
        scheds = crawl_all_gender(seed, gender)
        print(f"  {gender}: {len(scheds)} teams crawled")
        for s in scheds:
            plan.add_game(s)
    rec = SYNC.reconcile(plan)
    overrides = {}
    for amb in rec["ambiguous"]:
        want = SYNC._norm_tokens(amb["name"])
        eq = [c for c in amb["candidates"] if SYNC._norm_tokens(c["name"]) == want]
        if len(eq) == 1:
            overrides[amb["name"]] = eq[0]["id"]
    res = SYNC.ingest(plan, overrides=overrides, update_scores=True)
    print("full RESULT:", res)


if __name__ == "__main__":
    main()
