"""
OSSAA schedule importer -- PHASE 1 (offline, read-only dry run).

Scrapes ossaarankings.com per-team PrintSchedule pages (clean static HTML) and
turns them into the teams/games rows the app WOULD create. Phase 1 prints the
plan only -- it never touches the database.

Why PrintSchedule pages: the by-class / rankings pages render their team lists
via ASP.NET postback (no team links in the static HTML), but
    PrintSchedule.aspx?sel=teamschedule&t=<id>
is a plain server-rendered <table> with every game + opponent team-id. So we
seed from one team-id and crawl opponent links, staying inside the target
class+gender, which naturally discovers the rest of that class.

Stdlib only (urllib + re) -- no requests/bs4 needed for Phase 1.

Usage:
    # one team's schedule -> plan
    python tools/ossaa_import.py --team 158209

    # crawl a whole class from a seed, capped at 12 team fetches
    python tools/ossaa_import.py --crawl 158209 --class 2A --gender Boys --max 12

    # write the plan to CSV instead of (or as well as) printing
    python tools/ossaa_import.py --team 158209 --out plan.csv

Nothing here writes to analytics.db. Wiring into the app is Phase 2.
"""
from __future__ import annotations

import argparse
import csv
import html as _html
import os
import re
import sys
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field

BASE = "https://www.ossaarankings.com/PrintSchedule.aspx?sel=teamschedule&t={tid}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ossaa_cache")
POLITE_DELAY = 1.0  # seconds between live fetches

# OSSAA class token -> app teams.class enum (schema CHECK: B2,B1,A,2A,3A,4A,5A,6A,N/A)
# OSSAA basketball DOES split Class B into B1/B2 (e.g. "ARNETT (B2)"), so map them
# straight through. A bare "B" (rare) can't be split -> N/A.
CLASS_MAP = {"6A": "6A", "5A": "5A", "4A": "4A", "3A": "3A", "2A": "2A", "A": "A",
             "B1": "B1", "B2": "B2", "B": "N/A"}
GENDER_MAP = {"Boys": "M", "Girls": "F"}

# Out-of-state opponent detection. OSSAA lists Oklahoma teams, so anything with
# an ossaa id is 'OK'. A non-OSSAA opponent sometimes carries a trailing US
# state code ("Garden City, KS", "Hugoton KS"). Restrict to OK's neighbours so a
# school-type suffix like "MS" (middle school == Mississippi's code) isn't
# misread as a state. "OKC" (3 letters) never matches the 2-letter pattern.
NEIGHBOR_STATES = {"TX", "KS", "AR", "MO", "NM", "CO", "LA", "NE"}
_RE_STATE = re.compile(r",?\s+([A-Z]{2})\.?\s*$")


def detect_state(name: str) -> tuple[str, str]:
    """'Garden City, KS' -> ('Garden City', 'KS'); anything else -> (name, 'OK')."""
    m = _RE_STATE.search(name)
    if m and m.group(1) in NEIGHBOR_STATES:
        return name[:m.start()].rstrip(" ,").strip(), m.group(1)
    return name, "OK"


# --------------------------------------------------------------------------- #
# fetch (with on-disk cache so re-runs don't re-hit the site)
# --------------------------------------------------------------------------- #
def fetch(tid: int, *, force: bool = False) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"team_{tid}.html")
    if not force and os.path.exists(cache):
        return open(cache, encoding="utf-8").read()
    url = BASE.format(tid=tid)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", "replace")
    open(cache, "w", encoding="utf-8").write(body)
    time.sleep(POLITE_DELAY)
    return body


# --------------------------------------------------------------------------- #
# parse
# --------------------------------------------------------------------------- #
@dataclass
class Game:
    date: str          # ISO YYYY-MM-DD
    home_away: str     # "Home" | "Away"
    opp_id: int | None  # ossaa team id, None if opponent not on OSSAA
    opp_name: str
    opp_class: str     # app enum
    team_score: int | None
    opp_score: int | None
    outcome: str       # "W" | "L" | "" (future/canceled)
    raw_result: str


@dataclass
class TeamSchedule:
    tid: int
    school: str        # cleaned, e.g. "RIVERSIDE"
    klass: str         # app enum, e.g. "2A"
    gender: str        # "M" | "F"
    games: list = field(default_factory=list)


_RE_SCHOOL = re.compile(r'id="ctl03_lblSchool"[^>]*>([^<]+)</span>')
_RE_SPORT = re.compile(r'id="ctl03_lblTeamSport"[^>]*>([^<]+)</span>')
_RE_CLASS = re.compile(r'Class\s+(\S+)\s+Basketball')
_RE_GENDER = re.compile(r'\((Boys|Girls)\)')
_RE_ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
_RE_CELL = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
_RE_DATE = re.compile(r'(\d{2})/(\d{2})/(\d{2})')
_RE_OPP_LINK = re.compile(r"href='\?sel=teamschedule&t=(\d+)'[^>]*>([^<]+)</a>")
_RE_RESULT = re.compile(r'(\d+)\s*-\s*(\d+)\s+([WL])')
_RE_TAGS = re.compile(r'<[^>]+>')


def _txt(fragment: str) -> str:
    return _html.unescape(_RE_TAGS.sub("", fragment)).strip()


def _clean_opp_name(raw: str) -> tuple[str, str]:
    """'DOVE SCIENCE - OKC (3A)' / 'HAMMON (B-# 6)' -> (name, app_class)."""
    raw = raw.strip()
    # opponent class lives in a trailing (CLASS) or (CLASS-# rank). Token is
    # uppercase+digits in either order (6A, 2A, A, B1, B2) -- crucially letter+
    # digit too. Stays uppercase-only so a real distinguishing paren like
    # "Sequoyah (Tahlequah)" (mixed case) is NOT mistaken for a class.
    klass = "N/A"
    m = re.search(r'\(([0-9A-Z]+)(?:-#\s*\d+)?\)\s*$', raw)
    if m:
        klass = CLASS_MAP.get(m.group(1), "N/A")
        raw = raw[:m.start()].strip()
    return raw, klass


def parse_schedule(tid: int, html_doc: str) -> TeamSchedule:
    sch = _RE_SCHOOL.search(html_doc)
    school = _txt(sch.group(1)) if sch else f"team {tid}"
    school = re.sub(r'\s+TEAM PAGE$', '', school, flags=re.I).strip()

    sport = _RE_SPORT.search(html_doc)
    sport_txt = sport.group(1) if sport else ""
    cm = _RE_CLASS.search(sport_txt)
    gm = _RE_GENDER.search(sport_txt)
    klass = CLASS_MAP.get(cm.group(1), "N/A") if cm else "N/A"
    gender = GENDER_MAP.get(gm.group(1), "") if gm else ""

    ts = TeamSchedule(tid=tid, school=school, klass=klass, gender=gender)

    # isolate the schedule grid
    gi = html_doc.find('id="ctl04_GridView1"')
    grid = html_doc[gi:html_doc.find('</table>', gi)] if gi != -1 else ""

    for row in _RE_ROW.findall(grid):
        if '<th' in row:
            continue
        cells = _RE_CELL.findall(row)
        if len(cells) != 3:
            continue
        date_cell, opp_cell, res_cell = cells

        dm = _RE_DATE.search(date_cell)
        if not dm:                       # trailing &nbsp; spacer row
            continue
        mm, dd, yy = dm.groups()
        iso = f"20{yy}-{mm}-{dd}"

        # away = the opponent cell's visible text begins with "@".
        # a tournament "@ venue" appears AFTER the opponent name (mid-string),
        # so only a LEADING "@" means this team travelled.
        home_away = "Away" if _txt(opp_cell).lstrip().startswith('@') else "Home"

        link = _RE_OPP_LINK.search(opp_cell)
        if link:
            opp_id = int(link.group(1))
            opp_name, opp_class = _clean_opp_name(link.group(2))
        else:
            opp_id = None
            bare = _txt(opp_cell).lstrip('@').strip()
            # drop trailing "@ tournament/venue ..." context
            bare = re.split(r'\s+@\s+', bare)[0]
            opp_name, opp_class = _clean_opp_name(bare)

        rm = _RE_RESULT.search(res_cell)
        if rm:
            ts_, os_, out = int(rm.group(1)), int(rm.group(2)), rm.group(3)
        else:
            ts_, os_, out = None, None, ""

        ts.games.append(Game(
            date=iso, home_away=home_away, opp_id=opp_id, opp_name=opp_name,
            opp_class=opp_class, team_score=ts_, opp_score=os_, outcome=out,
            raw_result=_txt(res_cell)))
    return ts


# --------------------------------------------------------------------------- #
# plan-building (what the app WOULD insert)  -- still a dry run
# --------------------------------------------------------------------------- #
def app_team_name(school: str, gender: str) -> str:
    # user preference: append the word, not "(G)" -> "RIVERSIDE Boys"
    suffix = {"M": "Boys", "F": "Girls"}.get(gender, "")
    return f"{school} {suffix}".strip()


@dataclass
class Plan:
    teams: dict = field(default_factory=dict)   # app_name -> (class, gender, ossaa_id|None, state)
    games: list = field(default_factory=list)   # (date, home_name, away_name, hs, as, tracked)
    seen_game_keys: set = field(default_factory=set)
    # (start_iso, end_iso) inclusive. OSSAA team-ids are SEASON-SPECIFIC and a
    # team page shows that id's own season, so a stale/cross-season id silently
    # yields the wrong year. This window is the hard guard: games outside it are
    # dropped, and a team with NO in-window game is never created. Without it the
    # importer has no concept of season (this caused a multi-season blend once).
    window: tuple = None

    def _in_window(self, date: str) -> bool:
        return (self.window is None) or (self.window[0] <= date <= self.window[1])

    def add_team(self, name, klass, gender, ossaa_id=None, state="OK"):
        if name not in self.teams:
            self.teams[name] = (klass, gender, ossaa_id, state)

    def add_game(self, sched: TeamSchedule):
        gender = sched.gender
        me = app_team_name(sched.school, gender)
        kept = [g for g in sched.games if self._in_window(g.date)]
        if not kept:
            return  # this team has no games in the target season -> skip entirely
        self.add_team(me, sched.klass, gender, sched.tid, "OK")
        for g in kept:
            # OSSAA-listed opponents are Oklahoma; only sniff a state off the
            # name for non-OSSAA opponents (and strip it from the name).
            if g.opp_id:
                opp_name, state = g.opp_name, "OK"
            else:
                opp_name, state = detect_state(g.opp_name)
            opp = app_team_name(opp_name, gender)
            self.add_team(opp, g.opp_class, gender, g.opp_id, state)
            if g.home_away == "Home":
                home, away, hs, as_ = me, opp, g.team_score, g.opp_score
            else:
                home, away, hs, as_ = opp, me, g.opp_score, g.team_score
            # dedupe: same matchup same date from either side's schedule
            key = (g.date, *sorted((home, away)))
            if key in self.seen_game_keys:
                continue
            self.seen_game_keys.add(key)
            tracked = 0
            self.games.append((g.date, home, away, hs, as_, tracked))


# --------------------------------------------------------------------------- #
# crawl (BFS over opponent links, bounded to target class+gender)
# --------------------------------------------------------------------------- #
def crawl(seed, want_class, want_gender, max_fetch, *, progress=None, force=False):
    """BFS opponent links, including only teams whose page header matches
    want_class+want_gender. `progress(sched, tid)` is called per included team
    (the CLI prints; the app updates a Streamlit status line)."""
    want_g = GENDER_MAP.get(want_gender, want_gender)
    seen, schedules = set(), []
    q = deque([seed])
    while q and len(schedules) < max_fetch:
        tid = q.popleft()
        if tid in seen:
            continue
        seen.add(tid)
        try:
            sched = parse_schedule(tid, fetch(tid, force=force))
        except Exception as e:
            print(f"  !! fetch/parse failed for t={tid}: {e}", file=sys.stderr)
            continue
        if sched.gender != want_g or sched.klass != want_class:
            continue  # wrong bucket -- don't expand, don't include
        schedules.append(sched)
        if progress:
            progress(sched, tid)
        for g in sched.games:
            if g.opp_id and g.opp_id not in seen:
                q.append(g.opp_id)
    return schedules


# --------------------------------------------------------------------------- #
# reusable plan builders (imported by the Streamlit page; no printing)
# --------------------------------------------------------------------------- #
def season_window(label: str) -> tuple:
    """'2025-2026' -> ('2025-08-01', '2026-07-31') — the whole athletic year, so
    it captures every basketball game (late Oct .. early Apr) while excluding the
    adjacent seasons. Returns None if the label can't be parsed (no filtering)."""
    m = re.match(r"\s*(\d{4})\s*-\s*(\d{4})\s*$", label or "")
    if not m:
        return None
    return (f"{m.group(1)}-08-01", f"{m.group(2)}-07-31")


def build_plan_single(tid: int, *, window=None, force: bool = False):
    """One team -> (Plan, [TeamSchedule]). `window` = (start_iso, end_iso) season guard."""
    sched = parse_schedule(tid, fetch(tid, force=force))
    plan = Plan(window=window)
    plan.add_game(sched)
    return plan, [sched]


def build_plan_crawl(seed, klass, gender, max_fetch, *, window=None, progress=None, force=False):
    """Crawl a class -> (Plan, [TeamSchedule]). `window` = season date guard."""
    scheds = crawl(seed, klass, gender, max_fetch, progress=progress, force=force)
    plan = Plan(window=window)
    for s in scheds:
        plan.add_game(s)
    return plan, scheds


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def print_plan(plan: Plan):
    print("\n=== TEAMS the importer would create / ensure "
          f"({len(plan.teams)}) ===")
    for name in sorted(plan.teams):
        klass, gender, oid, state = plan.teams[name]
        gl = {"M": "Boys", "F": "Girls"}.get(gender, "?")
        oid_s = f"ossaa#{oid}" if oid else "(non-OSSAA)"
        print(f"  {name:<34} class={klass:<4} {gl:<5} {state:<3} {oid_s}")

    played = [g for g in plan.games if g[3] is not None]
    future = [g for g in plan.games if g[3] is None]
    print(f"\n=== GAMES ({len(plan.games)} total: "
          f"{len(played)} played, {len(future)} future/no-score) ===")
    for date, home, away, hs, as_, _ in sorted(plan.games):
        score = f"{hs}-{as_}" if hs is not None else "-- future --"
        print(f"  {date}  {home:<30} vs {away:<30} {score}")


def write_csv(plan: Plan, path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "home_team", "away_team", "home_score",
                    "away_score", "tracked"])
        for row in sorted(plan.games):
            w.writerow(row)
    print(f"\nwrote {len(plan.games)} games -> {path}")


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="OSSAA schedule importer (Phase 1 dry run)")
    ap.add_argument("--team", type=int, help="single ossaa team id")
    ap.add_argument("--crawl", type=int, metavar="SEED_ID",
                    help="BFS-crawl a class starting from this team id")
    ap.add_argument("--class", dest="klass", help="target class for --crawl, e.g. 2A")
    ap.add_argument("--gender", help="Boys|Girls (required for --crawl)")
    ap.add_argument("--max", type=int, default=10, help="max team fetches for --crawl")
    ap.add_argument("--out", help="write the game plan to this CSV")
    ap.add_argument("--force", action="store_true", help="ignore on-disk cache")
    ap.add_argument("--season", help="season label e.g. 2025-2026; drops games "
                    "outside that athletic year (OSSAA ids are season-specific)")
    args = ap.parse_args(argv)

    win = season_window(args.season) if args.season else None
    if args.season and not win:
        ap.error("--season must look like 2025-2026")
    plan = Plan(window=win)
    if args.team:
        sched = parse_schedule(args.team, fetch(args.team, force=args.force))
        print(f"Team: {sched.school}  class={sched.klass}  gender={sched.gender}  "
              f"games={len(sched.games)}")
        plan.add_game(sched)
    elif args.crawl:
        if not (args.klass and args.gender):
            ap.error("--crawl requires --class and --gender")
        print(f"Crawling class {args.klass} {args.gender} from seed {args.crawl} "
              f"(max {args.max} teams)...")

        def _show(sched, tid):
            print(f"  + {sched.school} ({sched.klass} {sched.gender}) "
                  f"{len(sched.games)} games  [t={tid}]")

        for sched in crawl(args.crawl, args.klass, args.gender, args.max,
                           progress=_show, force=args.force):
            plan.add_game(sched)
    else:
        ap.error("pass --team <id> or --crawl <seed_id>")

    print_plan(plan)
    if args.out:
        write_csv(plan, args.out)


if __name__ == "__main__":
    main()
