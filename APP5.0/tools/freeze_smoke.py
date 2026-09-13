"""freeze_smoke.py — render EVERY page against the PRODUCTION book, as each persona.

Why this exists, and why it is not one of the 181 files in `tracker/`:

The suites prove engines. They do not prove that a page *opens*. Between
`tracker/run_all.py` (104 checks, mostly engine shapes) and `pytest` (495, same)
there is exactly one thing nobody measures: a coach clicking a page in the
sidebar and getting a screen instead of a traceback. In October five brand-new
coaches do precisely that, on a book none of the local suites read, wearing a
plan **no production user has ever worn**.

Three facts drove the design:

  1. **The book must be production.** `local-book-lags-prod` — four findings in
     the 2026-09-06 sweep turned out to be artefacts of `%LOCALAPPDATA%`. Point
     `APP5_DATA_DIR` at a `tools/pull_prod_snapshot.py` copy or this proves
     nothing. The runner refuses to start without one.

  2. **The persona must include Free.** `app_users` on production holds six rows
     and **all six are `plan='paid'`**. `auth.add_user` does not set a plan, so
     the schema default (`'free'`) is what every October coach gets. The most
     travelled path in the app next month is the least travelled path today.

  3. **The season must be driven.** `SEAS.ACTIVE` is the literal `'Current'`,
     which on production holds 23 untracked fixtures. Every page defaults there.
     A page that renders its empty state is not a page that works — see
     `_no_crash` vs `_has_content` below, which are scored separately for that
     reason.

Run:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tools/freeze_smoke.py
    ... --dir C:/Users/colby/app5_prod      # explicit book
    ... --persona free                      # one persona
    ... --page 6_Team_Dashboard.py          # one page

The Store `python` shim reads a virtualised shadow of %LOCALAPPDATA%\\APP5 and
will smoke a stale book without saying so (`store-python-appdata-virtualization`).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

SEASON = "2025-2026"          # where production's 63 tracked games actually live
TEAM = 1                      # Adair Girls — the founder's team, 48 tracked games
TEAM_M = 1755                 # Sequoyah (Claremore) Boys — the other tracked coach

# Every page in the sidebar, in the order a coach meets them.
PAGES = [
    "1_Input_Hub.py", "2_Game_Tracker.py", "3_Event_Editor.py", "4_Schedule.py",
    "5_Rankings.py", "6_Team_Dashboard.py", "7_Players.py", "8_Officials.py",
    "9_War_Room.py", "10_Whiteboard.py", "12_Settings.py", "13_OSSAA_Import.py",
    "14_Hall_of_Fame.py", "15_FAQ.py", "16_Box_Score_Entry.py",
]

# Pages converted from `st.tabs` to lazy `_seg` dispatch, and the session key +
# options that drive each switcher.
#
# These need their own pass, because a normal render proves the DEFAULT section
# and nothing else — and the entire risk of that conversion is a body which used
# to run on every rerun now running only when a coach clicks it. A cross-section
# variable leak is invisible until then. `tools/seg_leak_sweep.py` finds those
# statically; this finds whatever the AST cannot see.
SECTIONS = {
    "7_Players.py": ("pl_view", ["Leaders", "Ratings", "Impact & Splits",
                                 "Shot Lab", "Compare", "Player Profile",
                                 "Lab", "Glossary"]),
    "14_Hall_of_Fame.py": ("hof_view", ["Records", "Single-game records",
                                        "Tracked ratings"]),
}

# The three plans that exist, as identities. `admin` is the founder; `paid` is
# what today's six users are; `free` is what every new coach will be.
PERSONAS = {
    "admin": {"email": "colbyl.farrar@gmail.com", "name": "Colby Farrar",
              "role": "admin", "plan": "paid", "paid_until": "",
              "team_id": TEAM, "team_ids": [TEAM], "shares_pool": 0,
              "pool_banned": 0},
    "paid":  {"email": "brockthomas3030@gmail.com", "name": "Paid Coach",
              "role": "coach", "plan": "paid", "paid_until": "",
              "team_id": TEAM_M, "team_ids": [TEAM_M], "shares_pool": 0,
              "pool_banned": 0},
    "free":  {"email": "newcoach@example.org", "name": "New Coach",
              "role": "coach", "plan": "free", "paid_until": "",
              "team_id": TEAM_M, "team_ids": [TEAM_M], "shares_pool": 0,
              "pool_banned": 0},
}

RESULTS: list[dict] = []


def _seed_identity(persona: dict) -> None:
    """Rebind the local identity rather than seeding `session_state`.

    `require_login` resolves `_demo_identity() or _LOCAL_IDENTITY` and then
    OVERWRITES `st.session_state['auth_user']`, so anything seeded into the
    session is discarded on the first run (`apptest-persona-seeding`). The
    module global is the only seam that survives it.
    """
    import helpers.auth as AUTH
    AUTH._LOCAL_IDENTITY = dict(persona)


def _text(at) -> str:
    parts = []
    for kind in ("markdown", "header", "subheader", "title", "caption", "text",
                 "info", "warning", "error", "metric", "dataframe", "table"):
        for e in (at.get(kind) or []):
            parts.append(str(getattr(e, "value", ""))[:400])
            parts.append(str(getattr(e, "label", "")))
    return " ".join(parts)


def _run_page(page: str, persona_name: str, persona: dict,
              section: tuple | None = None) -> dict:
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    # page_link raises outside a real MPA run; it is chrome, not content.
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None

    _seed_identity(persona)
    t0 = time.perf_counter()
    row = {"page": page, "persona": persona_name, "secs": 0.0,
           "exc": "", "chars": 0, "widgets": 0, "empty": False}
    try:
        at = AppTest.from_file(os.path.join(_APP, "pages", page),
                               default_timeout=300)
        # Season + team, under every key the pages use. Seeding a key a page
        # does not read is free; missing the one it does read silently measures
        # the empty 'Current' partition instead of the real book.
        for k in ("ta_season", "rk_season", "pl_season", "sch_season",
                  "hof_season", "off_season", "wr_season", "bx_season"):
            at.session_state[k] = SEASON
        for k in ("ta_team", "wr_team", "pl_team", "bx_team", "ee_team"):
            at.session_state[k] = persona.get("team_id") or TEAM
        if section:
            at.session_state[section[0]] = section[1]
            row["section"] = section[1]
        at.run()
        row["secs"] = round(time.perf_counter() - t0, 2)
        if at.exception:
            row["exc"] = "; ".join(repr(e.value)[:400] for e in at.exception)
        body = _text(at)
        row["chars"] = len(body)
        row["widgets"] = sum(len(at.get(k) or []) for k in
                             ("dataframe", "table", "metric", "button",
                              "selectbox", "radio", "tabs", "plotly_chart"))
        row["empty"] = ("No finished games" in body
                        or "Nothing logged yet" in body
                        or "No tracked games" in body)
    except Exception:
        row["secs"] = round(time.perf_counter() - t0, 2)
        row["exc"] = traceback.format_exc(limit=6)[-600:]
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("APP5_DATA_DIR")
                    or os.path.expanduser("~/app5_prod"))
    ap.add_argument("--persona", default="", choices=[""] + list(PERSONAS))
    ap.add_argument("--page", default="")
    ap.add_argument("--sections", action="store_true",
                    help="drive every _seg section of the converted pages, "
                         "not just the one that opens by default")
    args = ap.parse_args()

    book = os.path.join(os.path.expanduser(args.dir), "analytics.db")
    if not os.path.exists(book):
        print(f"NO BOOK at {book}\n"
              f"Run: python tools/pull_prod_snapshot.py", file=sys.stderr)
        return 2
    os.environ["APP5_DATA_DIR"] = os.path.expanduser(args.dir)

    from database.db import query
    n = query("SELECT COUNT(*) c FROM games WHERE tracked=1")[0]["c"]
    print(f"book: {book}  ({n} tracked games)\n")

    # A SECRETS-FREE cwd, or every render below measures "Sign in to continue".
    # Streamlit resolves `.streamlit/secrets.toml` relative to the working
    # directory, and the real one carries an [auth] block that gates every page
    # (`local-run-auth-off`). Without this the smoke happily reports 15 green
    # pages at an identical 825 characters each — which is the login wall,
    # rendered fifteen times.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    import streamlit as st
    if st.secrets.load_if_toml_exists():
        print("WARNING: secrets still resolve from this cwd; auth may gate.",
              file=sys.stderr)

    pages = [args.page] if args.page else PAGES
    people = [args.persona] if args.persona else list(PERSONAS)

    for pname in people:
        print(f"=== persona: {pname} ({PERSONAS[pname]['plan']}) ===")
        for page in pages:
            # One run per section on a converted page, else one run for the page.
            key_views = SECTIONS.get(page) if args.sections else None
            jobs = ([(key_views[0], v) for v in key_views[1]]
                    if key_views else [None])
            for job in jobs:
                r = _run_page(page, pname, PERSONAS[pname], section=job)
                RESULTS.append(r)
                mark = ("FAIL" if r["exc"]
                        else ("thin" if r["chars"] < 300 else "ok"))
                label = f"{page} › {job[1]}" if job else page
                print(f"  {mark:5} {label:44} {r['secs']:6.2f}s "
                      f"{r['chars']:6d} chars {r['widgets']:3d} widgets"
                      f"{'  EMPTY-STATE' if r['empty'] else ''}")
                if r["exc"]:
                    print(f"        {r['exc'][:400]}")
        print()

    bad = [r for r in RESULTS if r["exc"]]
    thin = [r for r in RESULTS if not r["exc"] and r["chars"] < 300]
    slow = sorted(RESULTS, key=lambda r: -r["secs"])[:8]
    print(f"{len(RESULTS)} renders · {len(bad)} raised · {len(thin)} thin")
    print("slowest:", ", ".join(f"{r['page']}/{r['persona']} {r['secs']}s"
                                for r in slow))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
