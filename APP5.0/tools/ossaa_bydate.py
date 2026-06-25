"""
By-date OSSAA scraper (headless browser) — the efficient daily refresh.

ossaarankings' by-date schedule view shows EVERY game on a given date in a single
page. It's a Telerik widget, so it needs a real browser to drive — but the date
is set via a non-strict <script> postback (the trick that cracked it), and from
then on it's one page render per date instead of fetching hundreds of team pages.

ROLLOVER-PROOF by design: the page is addressed by DATE, not by a season-specific
team id, so there are NO seeds to update each year. Teams are matched at ingest by
NAME (which doesn't change) — only OSSAA's internal ids roll over, and we don't
depend on them. The page only ever shows the live/upcoming season.

Ingests with update_scores: fills in scores for games now played, adds new games,
never duplicates, never touches tracked games.

Run (on the server, writes the live DB):
    cd /home/app5/app5/APP5.0
    APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/ossaa_bydate.py            # today
    ... tools/ossaa_bydate.py --days 3
    ... tools/ossaa_bydate.py --from 2026-12-05 --to 2026-12-12 --gender Girls

Needs: pip install playwright && playwright install chromium  (+ OS deps once via
`playwright install-deps chromium`).
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.ossaa_import import Plan, app_team_name, GENDER_MAP, season_window  # noqa: E402
import helpers.ossaa_sync as SYNC  # noqa: E402
from database import db  # noqa: E402


def _active_window():
    """(start,end) date window of the app's active season, + its label. The
    by-date page always shows the live/upcoming season, so this clamp keeps a
    refresh from stamping next-season games onto the current one."""
    row = db.query("SELECT value FROM app_settings WHERE key='active_season'")
    label = row[0]["value"] if row else ""
    return season_window(label), label

PAGE = "https://www.ossaarankings.com/Default.aspx?sel=schedules&spGK=Basketball{g}"
_RE_GRID = re.compile(r'<table[^>]*GridView[^>]*>(.*?)</table>', re.S)
_RE_ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
_RE_LINK = re.compile(r"t=(\d+)[^>]*>([^<]+)</a>")
_RE_SCORE = re.compile(r"\((\d+|-)\)")
_RE_TAGS = re.compile(r"<[^>]+>")


def _set_date_js(d: datetime.date) -> str:
    # set the Telerik picker + fire the postback from a NON-strict <script> tag
    # (a page.evaluate runs in strict mode and trips MS-Ajax's arguments access).
    return (f"var p=$find('ctl51_RadDatePicker1'); "
            f"p.set_selectedDate(new Date({d.year},{d.month - 1},{d.day})); "
            f"__doPostBack('ctl51$RadDatePicker1','');")


def scrape_date(page, d: datetime.date):
    """Return [(home_id, home_name, home_score, away_id, away_name, away_score)]
    for one date on an already-loaded by-date page. Scores are int or None."""
    page.add_script_tag(content=_set_date_js(d))
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1800)
    grid = _RE_GRID.search(page.content())
    games, seen = [], set()
    if not grid:
        return games
    for row in _RE_ROW.findall(grid.group(1)):
        if "sel=teamschedule" not in row:
            continue
        links = _RE_LINK.findall(row)
        if len(links) < 2:
            continue
        (sid, sname), (oid, oname) = links[0], links[1]
        sc = _RE_SCORE.findall(row)
        s_subj = int(sc[0]) if len(sc) > 0 and sc[0] != "-" else None
        s_opp = int(sc[1]) if len(sc) > 1 and sc[1] != "-" else None
        text = _RE_TAGS.sub(" ", row)
        # the home/away marker is the @/vs right after the subject's "(score)"
        sep = re.search(r"\)\s*(@|vs)\s", text)
        subj_away = bool(sep) and sep.group(1) == "@"
        if subj_away:                       # subject travels -> opponent is home
            home = (oid, oname.strip(), s_opp); away = (sid, sname.strip(), s_subj)
        else:
            home = (sid, sname.strip(), s_subj); away = (oid, oname.strip(), s_opp)
        key = tuple(sorted((int(sid), int(oid))))   # dedup the two-sided listing
        if key in seen:
            continue
        seen.add(key)
        games.append((home[0], home[1], home[2], away[0], away[1], away[2]))
    return games


def build_plan(browser, lo: datetime.date, hi: datetime.date, genders, window):
    plan = Plan(window=window)   # active-season window = the hard season guard
    gkeys = set()
    for gender in genders:
        gcode = GENDER_MAP[gender]
        page = browser.new_page()
        page.goto(PAGE.format(g=gender), wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)
        d = lo
        while d <= hi:
            if not plan._in_window(d.isoformat()):   # outside the active season
                d += datetime.timedelta(days=1)
                continue
            for (hid, hn, hs, aid, an, as_) in scrape_date(page, d):
                home = app_team_name(hn, gcode)
                away = app_team_name(an, gcode)
                plan.add_team(home, "N/A", gcode, int(hid), "OK")
                plan.add_team(away, "N/A", gcode, int(aid), "OK")
                key = (d.isoformat(), *sorted((home, away)))
                if key in gkeys:
                    continue
                gkeys.add(key)
                plan.games.append((d.isoformat(), home, away, hs, as_, 0))
            print(f"  {gender} {d.isoformat()}: {len(plan.games)} games so far", flush=True)
            d += datetime.timedelta(days=1)
        page.close()
    return plan


def run(lo: datetime.date, hi: datetime.date, genders, log=print):
    """Scrape [lo,hi] for the given genders and ingest. Clamped to the active
    season so it can't stamp next-season games onto the current one."""
    win, label = _active_window()
    if win:
        slo, shi = datetime.date.fromisoformat(win[0]), datetime.date.fromisoformat(win[1])
        lo, hi = max(lo, slo), min(hi, shi)
        if lo > hi:
            log(f"requested range is outside the active season ({label}); nothing to do")
            return {"teams_created": 0, "teams_matched": 0, "games_inserted": 0,
                    "games_skipped": 0, "games_updated": 0}
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            plan = build_plan(browser, lo, hi, genders, win)
        finally:
            browser.close()
    log(f"scraped {len(plan.games)} games, {len(plan.teams)} teams")
    rec = SYNC.reconcile(plan)
    overrides = {}
    for amb in rec["ambiguous"]:
        want = SYNC._norm_tokens(amb["name"])
        eq = [c for c in amb["candidates"] if SYNC._norm_tokens(c["name"]) == want]
        if len(eq) == 1:
            overrides[amb["name"]] = eq[0]["id"]
    return SYNC.ingest(plan, overrides=overrides, update_scores=True)


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(description="By-date OSSAA scrape + refresh")
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--to")
    ap.add_argument("--days", type=int)
    ap.add_argument("--gender", choices=["both", "Boys", "Girls"], default="both")
    a = ap.parse_args(argv)
    today = datetime.date.today()
    if a.frm and a.to:
        lo, hi = datetime.date.fromisoformat(a.frm), datetime.date.fromisoformat(a.to)
    elif a.days:
        lo, hi = today - datetime.timedelta(days=a.days - 1), today
    else:
        lo = hi = today
    genders = ["Boys", "Girls"] if a.gender == "both" else [a.gender]
    return lo, hi, genders


def main(argv=None):
    lo, hi, genders = _parse_args(argv)
    print(f"by-date refresh {lo} .. {hi}  {genders}")
    res = run(lo, hi, genders)
    print("RESULT:", res)


if __name__ == "__main__":
    main()
