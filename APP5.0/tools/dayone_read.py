"""dayone_read.py — what a day-one sicko actually SEES, per page.

`tools/freeze_smoke.py` answers "did the page raise". That is the question the
freeze needed. It is not the question October needs.

    "15 renders, 0 exceptions" is not the same as
    "an analyst found something to chew on."

The five coaches arriving in October are college-level analytics readers. They
are Paid, so plan gating is open — but the Coaches' Co-op is **reciprocal**, and
on day one they have shared nothing while their own team has zero tracked games.
Every surface in the app therefore resolves down one of three paths:

    a lock        one of the five `entitlement.MSG_*` sentences is on screen
    an empty      `ui.empty_state` fired, or a bare `st.info` said the same
    content       a dataframe, table, chart or metric actually rendered

Nobody has ever counted those three. This counts them.

TWO MEASUREMENT TRAPS, BOTH HIT WHILE WRITING THIS

1. **A lock CONSULTED is not a lock SHOWN.** `9_War_Room.py:535` resolves
   `_WR_LOCK` at page top on every run and displays it only inside three
   `if` branches. Counting `lock_reason` returns therefore over-reports what a
   coach sees. `locks` below is counted off the RENDERED TEXT; `consults` keeps
   the call count beside it, because the two disagreeing is itself a finding.

2. **Not every dead end is an `empty_state`.** The branded component is the
   instrumented funnel (`ui.py:730`), but plenty of surfaces say "no tracked
   games" through a bare `st.info`. Those are counted separately as `soft` —
   an empty state the telemetry does not see either.

HOW IT INSTRUMENTS, AND WHY IT IS NOT A GREP

`empty_state` is called from 50-odd sites and `lock_reason` from the whole
ladder; a static count would say how many *could* fire, which is already known
and is not the interesting number. The only way to learn which ones fire *for
this persona on this book* is to render the page and watch. So both functions
are wrapped, and `sys.modules` is swept before every run to rebind the wrapper
into helper modules that did `from helpers.ui import empty_state` at import time
and froze the original.

Read-only. Touches no book but the read-only production snapshot.

Run:
    PYTHONIOENCODING=utf-8 \
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tools/dayone_read.py
    ... --dir C:/Users/colby/app5_prod      # explicit book
    ... --persona dayone                    # one persona
    ... --page 9_War_Room.py                # one page
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
import time
import traceback

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

from tools.freeze_smoke import PAGES, SEASON, TEAM, _seed_identity, _text

# A team with a full schedule (35 finished games, so it is RATED and appears in
# every league table) and ZERO tracked games. That combination is what every
# October coach is on day one, and it is the only one that separates "the app
# has no data" from "this coach has no data" — the second is the real question.
TEAM_DAYONE = 64        # Lincoln Christian Girls — 35 games, 35 finished, 0 tracked

PERSONAS = {
    # The October coach, day one. Paid (the five are), assigned a team, and
    # NOT league-wide: the co-op is reciprocal and they have shared nothing.
    "dayone": {"email": "dayone@example.org", "name": "Day-One Coach",
               "role": "coach", "plan": "paid", "paid_until": "",
               "team_id": TEAM_DAYONE, "team_ids": [TEAM_DAYONE],
               "shares_pool": 0, "pool_banned": 0},
    # The same coach after the co-op opens — isolates the reciprocity gate from
    # the "my team has no data" problem. Same team, same book, one flag.
    "dayone_coop": {"email": "dayone@example.org", "name": "Day-One Co-op",
                    "role": "coach", "plan": "paid", "paid_until": "",
                    "team_id": TEAM_DAYONE, "team_ids": [TEAM_DAYONE],
                    "shares_pool": 1, "pool_banned": 0},
    # The control: the founder, on the team with 26 tracked games. Whatever
    # this persona sees is the ceiling the day-one numbers are read against.
    "admin": {"email": "colbyl.farrar@gmail.com", "name": "Colby Farrar",
              "role": "admin", "plan": "paid", "paid_until": "",
              "team_id": TEAM, "team_ids": [TEAM], "shares_pool": 1,
              "pool_banned": 0},
}

_EMPTIES: list[tuple[str, str]] = []      # (title, caller site)
_CONSULTS: list[str] = []                 # lock_reason returned a message

# Phrases a surface uses to say "nothing here" WITHOUT the branded component.
# Drawn from the bare `st.info` / `st.caption` strings actually in the pages —
# these are dead ends that `ui.py:730`'s telemetry never records.
_SOFT_EMPTY = (
    "no tracked games", "no finished games", "nothing logged yet",
    "no games yet", "not enough", "no data", "need at least",
    "no rated teams", "track a game", "no players",
)


def _install_probes():
    """Wrap `ui.empty_state` and `entitlement.lock_reason`, once."""
    import helpers.ui as UI
    import helpers.entitlement as ENT

    if getattr(UI.empty_state, "_probed", False):
        return
    _orig_empty, _orig_lock = UI.empty_state, ENT.lock_reason

    def empty_state(title, body="", **kw):
        try:
            from helpers import telemetry as _tel
            site = _tel.caller_site(2)
        except Exception:
            site = "?"
        _EMPTIES.append((str(title), site))
        return _orig_empty(title, body, **kw)

    def lock_reason(*a, **kw):
        msg = _orig_lock(*a, **kw)
        if msg:
            _CONSULTS.append(str(msg))
        return msg

    empty_state._probed = lock_reason._probed = True
    empty_state._orig, lock_reason._orig = _orig_empty, _orig_lock
    UI.empty_state, ENT.lock_reason = empty_state, lock_reason


def _rebind_probes():
    """Re-point modules that imported the ORIGINAL by name.

    `from helpers.ui import empty_state` at module import time binds the
    function object, not the module attribute, so patching `helpers.ui` after
    that module loaded misses it. AppTest re-execs the *page* each run, but the
    ~40 helper modules under it are imported once and keep the stale binding.
    """
    import helpers.ui as UI
    import helpers.entitlement as ENT
    for mod in list(sys.modules.values()):
        if mod is None or not getattr(mod, "__name__", "").startswith(
                ("helpers", "pages", "database")):
            continue
        for name, probe in (("empty_state", UI.empty_state),
                            ("lock_reason", ENT.lock_reason)):
            cur = getattr(mod, name, None)
            if cur is not None and cur is getattr(probe, "_orig", None):
                setattr(mod, name, probe)


def _run(page: str, persona: dict, season: str) -> dict:
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None

    _install_probes()
    _rebind_probes()
    _EMPTIES.clear()
    _CONSULTS.clear()
    _seed_identity(persona)

    t0 = time.perf_counter()
    row = {"page": page, "secs": 0.0, "exc": "", "chars": 0, "data": 0,
           "charts": 0, "empties": [], "consults": [], "locks": [], "soft": []}
    try:
        at = AppTest.from_file(os.path.join(_APP, "pages", page),
                               default_timeout=600)
        for k in ("ta_season", "rk_season", "pl_season", "sch_season",
                  "hof_season", "off_season", "wr_season", "bx_season"):
            at.session_state[k] = season
        for k in ("ta_team", "wr_team", "pl_team", "bx_team", "ee_team"):
            at.session_state[k] = persona["team_id"]
        at.run()
        _rebind_probes()          # anything imported DURING the run
        row["secs"] = round(time.perf_counter() - t0, 2)
        if at.exception:
            row["exc"] = "; ".join(repr(e.value)[:300] for e in at.exception)
        body = _text(at)
        row["chars"] = len(body)
        row["data"] = sum(len(at.get(k) or []) for k in
                          ("dataframe", "table", "metric"))
        row["charts"] = len(at.get("plotly_chart") or [])
        row["locks"] = _locks_on_screen(body)
        row["soft"] = _soft_on_screen(at)
    except Exception:
        row["secs"] = round(time.perf_counter() - t0, 2)
        row["exc"] = traceback.format_exc(limit=5)[-400:]
    row["empties"] = list(_EMPTIES)
    row["consults"] = list(_CONSULTS)
    return row


def _locks_on_screen(body: str) -> list[str]:
    """Which entitlement sentences a coach can actually READ on this page.

    Matched on a distinctive fragment rather than the whole constant: the
    messages carry markdown asterisks and the harness renders some of them
    through `st.info` and some inside a markdown block, so an equality test
    misses half of them.
    """
    import helpers.entitlement as ENT
    hits = []
    for name in ("MSG_PAID", "MSG_FREE_DEMO", "MSG_COOP_INVITE",
                 "MSG_NOT_SHARED", "MSG_POOL_BANNED"):
        msg = getattr(ENT, name, "")
        probe = msg[:60].lstrip("🔒🎁 ").strip()
        if probe and probe[:45] in body:
            hits.append(name)
    return hits


def _soft_on_screen(at) -> list[str]:
    """Dead ends written as a bare `st.info` / `st.warning` — the ones the
    `empty_hit` telemetry at `ui.py:730` will never see."""
    out = []
    for kind in ("info", "warning"):
        for e in (at.get(kind) or []):
            txt = str(getattr(e, "value", ""))
            low = txt.lower()
            if any(p in low for p in _SOFT_EMPTY):
                out.append(txt[:70])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("APP5_DATA_DIR")
                    or os.path.expanduser("~/app5_prod"))
    ap.add_argument("--persona", default="", choices=[""] + list(PERSONAS))
    ap.add_argument("--page", default="")
    ap.add_argument("--season", default=SEASON)
    args = ap.parse_args()

    book = os.path.join(os.path.expanduser(args.dir), "analytics.db")
    if not os.path.exists(book):
        print(f"NO BOOK at {book}", file=sys.stderr)
        return 2
    os.environ["APP5_DATA_DIR"] = os.path.expanduser(args.dir)

    from database.db import query
    n = query("SELECT COUNT(*) c FROM games WHERE tracked=1")[0]["c"]
    print(f"book: {book}  ({n} tracked games)  season={args.season}\n")

    # secrets-free cwd or every page renders the login wall (see freeze_smoke)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    pages = [args.page] if args.page else PAGES
    people = [args.persona] if args.persona else list(PERSONAS)
    totals = {}

    for pname in people:
        p = PERSONAS[pname]
        print(f"=== persona: {pname}  (team {p['team_id']}, plan {p['plan']}, "
              f"co-op {'yes' if p['shares_pool'] else 'NO'}) ===")
        print(f"  {'page':<24} {'secs':>6} {'data':>5} {'chart':>5} "
              f"{'mt':>3} {'soft':>4} {'lock':>4} {'cons':>4}  detail")
        rows = []
        for page in pages:
            r = _run(page, p, args.season)
            rows.append(r)
            det = []
            if r["exc"]:
                det.append("RAISED " + r["exc"][:120])
            seen = collections.Counter(t for t, _ in r["empties"])
            if seen:
                det.append("empty: " + "; ".join(
                    f"{t[:32]}x{c}" if c > 1 else t[:32]
                    for t, c in seen.most_common(3)))
            if r["soft"]:
                det.append("soft: " + "; ".join(s[:40] for s in r["soft"][:2]))
            if r["locks"]:
                det.append("LOCK: " + ", ".join(r["locks"]))
            print(f"  {r['page']:<24} {r['secs']:6.2f} {r['data']:5d} "
                  f"{r['charts']:5d} {len(r['empties']):3d} {len(r['soft']):4d} "
                  f"{len(r['locks']):4d} {len(r['consults']):4d}"
                  f"  {' | '.join(det)[:160]}")
        totals[pname] = rows
        d = sum(r["data"] for r in rows)
        c = sum(r["charts"] for r in rows)
        e = sum(len(r["empties"]) + len(r["soft"]) for r in rows)
        lk = sum(len(r["locks"]) for r in rows)
        dead = sum(1 for r in rows if r["data"] + r["charts"] == 0)
        print(f"  -- {len(rows)} pages · {d} data · {c} charts · {e} dead ends · "
              f"{lk} locks shown · {dead} pages with NOTHING to read\n")

    if len(totals) > 1:
        print("=== contrast ===")
        print(f"  {'persona':<14} {'data':>6} {'charts':>7} {'deadend':>8} "
              f"{'locks':>6} {'dead pages':>11}")
        for pname, rows in totals.items():
            print(f"  {pname:<14} {sum(r['data'] for r in rows):6d} "
                  f"{sum(r['charts'] for r in rows):7d} "
                  f"{sum(len(r['empties']) + len(r['soft']) for r in rows):8d} "
                  f"{sum(len(r['locks']) for r in rows):6d} "
                  f"{sum(1 for r in rows if r['data'] + r['charts'] == 0):11d}")

    raised = [r for rows in totals.values() for r in rows if r["exc"]]
    print(f"\n{sum(len(v) for v in totals.values())} renders · "
          f"{len(raised)} raised")
    return 1 if raised else 0


if __name__ == "__main__":
    sys.exit(main())
