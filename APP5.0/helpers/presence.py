"""
presence.py — how many COACHES are actively using the main app right now
(batch item 5a, 2026-07-20).

The signal that matters for load is concurrent coaches on `app5-web`, NOT the
per-game fan counter (public_feed.fan_count = cumulative daily-unique per game,
the wrong tool). Streamlit runs ONE process and every coach is authenticated, so
a process-shared in-memory stamp is enough — no DB writes on the hot path.

  • Store: a dict behind @st.cache_resource, shared across every session in the
    single app5-web process (cache_resource returns the SAME object each call;
    cache_data would give per-key COPIES — wrong here).
  • Stamp: page_chrome() calls mark(email) on every page render, after the coach
    is resolved by require_login(). One dict write, no query.
  • Count: online = distinct emails stamped within the window (default 90 s).

Caveat (documented in the batch doc): Streamlit only reruns on interaction, so an
idle-but-open tab ages out of the window. "Online" therefore means *actively
using in the last ~90 s* — the right number for load, not "tabs open" (which
would need a client ping this deliberately avoids).

The in-memory peak-concurrent high-water mark rides alongside so the capacity
card (5b) can show worst-case load since the process last started; the SETTINGS
card is what persists a rolling weekly peak to app_settings (admin render only,
off the hot path). Streamlit-only dependency is @st.cache_resource; mark() is
wrapped so a presence failure can never break page boot.
"""
from __future__ import annotations

import time

import streamlit as st

WINDOW = 90        # seconds; a stamp older than this no longer counts as online
_PRUNE = 3600      # drop stamps older than this so `seen` can't grow unbounded


@st.cache_resource(show_spinner=False)
def _store() -> dict:
    """Process-shared presence state. One object for every session."""
    return {"seen": {}, "peak": 0, "peak_at": None}


def mark(email: str) -> None:
    """Stamp this coach as active NOW and refresh the peak-concurrent high-water
    mark. Called from page_chrome on EVERY render, so it must be cheap (one dict
    write + a walk over a handful of emails, no DB) and must never raise into
    page boot."""
    if not email:
        return
    try:
        s = _store()
        now = time.time()
        seen = s["seen"]
        seen[email] = now
        # prune ancient stamps and count the live window in one pass
        live = 0
        for e, ts in list(seen.items()):
            age = now - ts
            if age >= _PRUNE:
                del seen[e]
            elif age < WINDOW:
                live += 1
        if live > s["peak"]:
            s["peak"] = live
            s["peak_at"] = now
    except Exception:
        pass


def online(window: int = WINDOW) -> list[str]:
    """Emails active within `window` seconds (most-recent first)."""
    try:
        now = time.time()
        rows = [(e, ts) for e, ts in list(_store()["seen"].items())
                if now - ts < window]
        rows.sort(key=lambda r: r[1], reverse=True)
        return [e for e, _ in rows]
    except Exception:
        return []


def online_count(window: int = WINDOW) -> int:
    """How many distinct coaches are actively using the app right now."""
    return len(online(window))


def peak() -> dict:
    """In-memory peak concurrent since this process started:
    {'peak': int, 'peak_at': epoch|None}."""
    try:
        s = _store()
        return {"peak": s["peak"], "peak_at": s["peak_at"]}
    except Exception:
        return {"peak": 0, "peak_at": None}
