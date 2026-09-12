"""
telemetry.py — the three October counters (THE BOOK §21 Phase 1).

The training session happens **exactly once**. These three counters are the only
evidence that will ever exist about what five brand-new coaches actually did with
the app, and none of them existed before this file:

  1. **page views** — which page, which coach, which day, *in what order*
  2. **empty-state hits** — every dead end in the app, funnelled through the one
     function that renders them (`helpers.ui.empty_state`)
  3. **co-op toggles** — every change to `teams.shares_pool`, old value and new

They are deliberately cheap and deliberately disposable. One table, no blobs,
scalar columns only, a retention prune, and a kill switch that needs no deploy.

---
DESIGN NOTES — the decisions, and why

**Per-event rows, not daily counters.** §21 asks for pages "in what order", and a
daily counter cannot answer ordering at all. The objection to per-event rows is
volume, and on Streamlit that objection is real but misaimed: `page_chrome` runs
on every *rerun*, not every *open*, so a naive row-per-call would log a row for
every widget click — hundreds per coach per hour. The fix is to dedupe at the
source rather than to throw the ordering away:

  · `page_view` writes only when the actor's page CHANGES (a real navigation).
    Overview → Scout → Overview is three rows; clicking twelve filters inside
    Scout is none.
  · `empty_hit` writes at most once per (actor, site) per `_DEDUP_SECS`, so an
    empty state that stays empty across a rerun storm is one hit, not forty.
  · `coop_toggle` is never deduped. Every flip is a fact and there are maybe
    ten of them all season.

After that dedup the write rate is bounded by human navigation — order 10^3
rows/day at five coaches, ~60 bytes a row. A single unindexed-path INSERT on a
WAL database is sub-millisecond; the page render it rides on costs 0.15–85 s.
This is not the thing that will be felt on a 1 vCPU box.

**The dedup state is per-process, in memory.** `app5-web` is one Streamlit
process (see `helpers/presence.py`, which relies on the same fact), so one
process-shared dict is enough and costs no query. A restart re-arms the dedup and
at worst duplicates one row per actor — irrelevant at this precision.

**Actor is the plain email**, matching `audit_log.actor` and the `u:<email>:`
scoping in `settings_utils`. Hashing was considered and rejected: with five known
coaches a hash is not anonymity, it is only an extra join the founder has to do
by hand at 11pm in October. Nothing in this table is more sensitive than the
audit log already is.

**Never raises.** Every public function is wrapped. A broken counter must not be
able to take a page down — but it logs at WARNING so it cannot be *invisible*
either, which is the failure mode of a bare `except: pass`.

**Kill switch**: `app_settings.telemetry_off = '1'` turns every write off with no
deploy. Read through a 60-second in-process cache, the same staleness contract
the settings snapshot uses, so the switch costs no query on the hot path and
still takes effect within a minute.

This module imports **no Streamlit** — only `database.db` and the stdlib — so the
engine layer and the script tests can use it unchanged.
"""
from __future__ import annotations

import logging
import sys
import time

from database.db import query, execute

_log = logging.getLogger(__name__)

# ── knobs ────────────────────────────────────────────────────────────────────
KINDS = ("page", "empty", "coop")

# An empty state that is still empty on the next rerun is the same dead end.
_DEDUP_SECS = 90

# How long rows live. The window that has to stay readable is the October
# training plus the season it feeds (Nov–Mar), so six months rather than the
# read surface's 30 days. At the measured shape (~60 B/row, ~10^3 rows/day at
# five coaches) that is a few MB — see docs/OVERNIGHT_2026-09-12.md.
RETAIN_DAYS = 180

_KILL_KEY = "telemetry_off"
_KILL_TTL = 60          # seconds; matches settings_utils._SNAP_TTL

# process-shared state: last page per actor, last (actor, kind, name) stamp,
# the kill-switch cache, and the day the retention prune last ran.
_last_page: dict = {}
_last_hit: dict = {}
_kill = {"bucket": -1, "off": False}
_pruned_day = {"day": ""}


# ── kill switch ──────────────────────────────────────────────────────────────
def enabled() -> bool:
    """False when `app_settings.telemetry_off = '1'`. Cached for `_KILL_TTL`
    seconds so the check costs no query on a page render; a flip therefore takes
    effect within a minute, without a deploy or a restart."""
    try:
        bucket = int(time.time() // _KILL_TTL)
        if _kill["bucket"] != bucket:
            rows = query("SELECT value FROM app_settings WHERE key=?",
                         (_KILL_KEY,))
            _kill["off"] = bool(rows) and str(rows[0]["value"]).strip() == "1"
            _kill["bucket"] = bucket
        return not _kill["off"]
    except Exception:
        # Cannot read the switch → assume ON is unsafe; assume OFF loses a
        # counter. Losing a counter is the cheaper failure.
        return False


def set_enabled(on: bool) -> None:
    """Flip the kill switch and drop the cache so the change is immediate for
    this process."""
    execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)",
            (_KILL_KEY, "0" if on else "1"))
    _kill["bucket"] = -1


# ── the write ────────────────────────────────────────────────────────────────
def _write(kind: str, name: str, actor: str, detail: str = "") -> None:
    """The single INSERT. Callers go through the three public recorders."""
    execute(
        "INSERT INTO telemetry (kind, actor, name, detail) VALUES (?,?,?,?)",
        (kind[:12], (actor or "")[:120], (name or "")[:120],
         (detail or "")[:200]))
    _prune_once()


def _prune_once() -> None:
    """Drop rows past `RETAIN_DAYS`, at most once per calendar day per process.
    Runs on the write path rather than on the admin read so that a founder who
    never opens Settings still cannot grow the table without bound."""
    day = time.strftime("%Y-%m-%d")
    if _pruned_day["day"] == day:
        return
    _pruned_day["day"] = day
    try:
        execute("DELETE FROM telemetry WHERE ts < datetime('now', ?)",
                (f"-{int(RETAIN_DAYS)} days",))
    except Exception as exc:
        _log.warning("telemetry prune failed: %s", exc)


# ── 1a · page views ──────────────────────────────────────────────────────────
def page_view(page: str, actor: str = "") -> None:
    """Record a page OPEN. Called from `helpers.ui.page_chrome`, which runs on
    every rerun — so this writes only when the actor's page actually changed.
    Returning to a page already counts as a new row (the dedup is on the last
    page, not on a time window), which is what "in what order" needs."""
    try:
        if not page or not enabled():
            return
        key = (actor or "")
        if _last_page.get(key) == page:
            return
        _last_page[key] = page
        _write("page", page, actor)
    except Exception as exc:
        _log.warning("telemetry page_view failed: %s", exc)


# ── 1b · empty-state hits ────────────────────────────────────────────────────
def empty_hit(title: str, actor: str = "", site: str = "") -> None:
    """Record that an empty state rendered. Instrumented once inside
    `helpers.ui.empty_state`, which is the single funnel for "this surface has
    nothing to show" — 53 call sites, zero of them edited.

    `site` is the caller's `module:line`, resolved by the caller with
    `sys._getframe` (cheap; `inspect.stack()` is not). It is what makes the row
    identify WHICH empty state fired: the titles collide badly — "No tracked
    games yet" alone is written in at least four different tabs."""
    try:
        if not enabled():
            return
        name = site or (title or "")[:120]
        key = (actor or "", "empty", name)
        now = time.time()
        if now - _last_hit.get(key, 0.0) < _DEDUP_SECS:
            return
        _last_hit[key] = now
        _write("empty", name, actor, title or "")
    except Exception as exc:
        _log.warning("telemetry empty_hit failed: %s", exc)


def caller_site(depth: int = 2) -> str:
    """`module:line` of the frame `depth` levels up. Used to name an empty state
    by where it is written rather than by what it says."""
    try:
        f = sys._getframe(depth)
        mod = f.f_code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
        return f"{mod}:{f.f_lineno}"
    except Exception:
        return ""


# ── 1c · co-op toggle ────────────────────────────────────────────────────────
def coop_toggle(scope: str, old: bool, new: bool, actor: str = "",
                target: str = "") -> None:
    """Record a change to the Coaches' Co-op sharing flag, with the old value and
    the new one. Instrumented inside `helpers.auth.set_shares_pool` /
    `set_team_shares_pool` so both Settings call sites (and anything added
    later) are covered without touching the UI.

    Never deduped: six paid accounts and ONE sharing team is the whole business
    question October answers, and a flip is a handful of rows a season."""
    try:
        if not enabled():
            return
        if bool(old) == bool(new):
            return          # a no-op save is not a decision
        _write("coop", scope, actor,
               f"{1 if old else 0}->{1 if new else 0}"
               + (f" {target}" if target else ""))
    except Exception as exc:
        _log.warning("telemetry coop_toggle failed: %s", exc)


# ── the read surface ─────────────────────────────────────────────────────────
def summary(days: int = 30) -> dict:
    """Everything the Settings panel shows, in one call and four queries.

    Returns
      pages    [{name, hits, coaches}]            most-opened first
      first    [{name, hits}]                     first page of a coach's session
      empties  [{name, title, hits, coaches}]     most-hit dead end first
      coop     [{ts, actor, name, detail}]        every flip, newest first
      total    int                                rows in the window
      days     int
    """
    out = {"pages": [], "first": [], "empties": [], "coop": [],
           "total": 0, "days": int(days)}
    since = f"-{int(days)} days"
    try:
        out["pages"] = query(
            "SELECT name, COUNT(*) AS hits, COUNT(DISTINCT actor) AS coaches "
            "FROM telemetry WHERE kind='page' AND ts >= datetime('now', ?) "
            "GROUP BY name ORDER BY hits DESC", (since,))
        # "in what order" at the only resolution that survives dedup: which page
        # a coach landed on FIRST each day.
        out["first"] = query(
            "SELECT name, COUNT(*) AS hits FROM telemetry t WHERE kind='page' "
            "AND ts >= datetime('now', ?) AND id = ("
            "  SELECT MIN(id) FROM telemetry x WHERE x.kind='page' "
            "  AND x.actor = t.actor AND substr(x.ts,1,10) = substr(t.ts,1,10)) "
            "GROUP BY name ORDER BY hits DESC", (since,))
        out["empties"] = query(
            "SELECT name, MAX(detail) AS title, COUNT(*) AS hits, "
            "COUNT(DISTINCT actor) AS coaches FROM telemetry "
            "WHERE kind='empty' AND ts >= datetime('now', ?) "
            "GROUP BY name ORDER BY hits DESC", (since,))
        out["coop"] = query(
            "SELECT ts, actor, name, detail FROM telemetry WHERE kind='coop' "
            "AND ts >= datetime('now', ?) ORDER BY id DESC LIMIT 50", (since,))
        rows = query("SELECT COUNT(*) AS n FROM telemetry "
                     "WHERE ts >= datetime('now', ?)", (since,))
        out["total"] = rows[0]["n"] if rows else 0
    except Exception as exc:
        _log.warning("telemetry summary failed: %s", exc)
    return out


def reset_dedup() -> None:
    """Clear the in-process dedup state. Tests only — production wants the
    dedup, which is the whole reason the write rate is bounded."""
    _last_page.clear()
    _last_hit.clear()
    _kill["bucket"] = -1
    _pruned_day["day"] = ""
