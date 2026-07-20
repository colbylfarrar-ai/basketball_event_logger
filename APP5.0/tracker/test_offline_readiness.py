"""Offline-readiness smoke: the laptop must render the meeting pages with the
network unplugged.

Three things are proved here, and they are different:
  1. DATA — the local DB really carries 8 M + 35 F tracked games for 2025-2026.
  2. CONTENT — Rankings and Team Dashboard show REAL ROWS, not their empty state.
     Counting rendered elements is not enough: `empty_state()` + `st.stop()`
     renders a perfectly healthy-looking page with zero data behind it, which is
     exactly the failure this run is meant to catch.
  3. OFFLINE — all of the above with every non-loopback socket hard-failed, so a
     call to the VPS or OSSAA raises instead of silently hanging (a hang on
     meeting wifi looks identical to a crash from the front row).

NOTE the season trap: SEAS.ACTIVE is "Current" == 2026-2027, which has ZERO
games. Every page defaults there. The tracked data lives under the archived
"2025-2026" label and the picker must be driven to it.

Run it with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/test_offline_readiness.py
The Microsoft Store `python` sees a virtualized shadow copy of %LOCALAPPDATA%\\APP5
and will read a stale analytics.db without saying so.
"""
import os
import socket
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

SEASON = "2025-2026"
PASSED = 0
BLOCKED = []


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def cut_the_wire():
    """Fail every non-loopback connect. Streamlit binds localhost, so loopback
    stays open; anything reaching out gets OSError, not a timeout."""
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo
    LOCAL = ("127.0.0.1", "::1", "localhost", "0.0.0.0", None)

    def guard(self, addr, *a, **k):
        host = addr[0] if isinstance(addr, tuple) else str(addr)
        if host not in LOCAL:
            BLOCKED.append(host)
            raise OSError(f"OFFLINE SMOKE: outbound connect to {host} blocked")
        return real_connect(self, addr, *a, **k)

    def guard_dns(host, *a, **k):
        if host not in LOCAL:
            BLOCKED.append(host)
            raise socket.gaierror(f"OFFLINE SMOKE: DNS for {host} blocked")
        return real_getaddrinfo(host, *a, **k)

    socket.socket.connect = guard
    socket.getaddrinfo = guard_dns


def test_data():
    from database.db import query
    rows = query(
        """SELECT t1.gender g, COUNT(*) n
           FROM games s JOIN teams t1 ON t1.id=s.team1_id
           WHERE s.tracked=1 AND s.season=? AND s.home_score IS NOT NULL
           GROUP BY 1""", (SEASON,))
    got = {r["g"]: r["n"] for r in rows}
    print(f"  .. tracked finished {SEASON}: {got}")
    ok(got.get("M") == 8, f"8 boys tracked games present (got {got.get('M')})")
    ok(got.get("F") == 35, f"35 girls tracked games present (got {got.get('F')})")

    import helpers.team_ratings as TR
    for g, want_tr in (("M", 5), ("F", 21)):
        sc = TR.score_ratings(gender=g, season=SEASON)
        tr = TR.tracked_ratings(gender=g, season=SEASON)
        ok(len(sc) > 500, f"{g}: score_ratings ranks {len(sc)} teams")
        ok(len(tr) == want_tr, f"{g}: tracked_ratings covers {len(tr)} teams")


def _text(at):
    """Everything the page put on screen, as one string."""
    parts = []
    for kind in ("markdown", "header", "subheader", "title", "caption",
                 "text", "info", "warning", "error", "metric"):
        for e in (at.get(kind) or []):
            parts.append(str(getattr(e, "value", "")))
            parts.append(str(getattr(e, "label", "")))
    return " ".join(parts)


def _no_empty_state(at, label):
    body = _text(at)
    assert "No finished games" not in body, \
        f"{label} rendered the EMPTY STATE — season picker never took"
    return body


def _new(page):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    return AppTest.from_file(os.path.join(_APP, "pages", page), default_timeout=900)


def test_rankings_offline():
    # gender_radio() on Rankings is UNKEYED, so there is no session_state slot to
    # seed — and at.radio[0].set_value() trips an unrelated AppTest bug on this
    # page's multiselect. Pin the shared helper instead; the page from-imports it
    # at exec time, so the patch lands on every run.
    import helpers.ui as UI
    real_radio = UI.gender_radio
    try:
        for gender, tag, team in (("M", "boys", "Sequoyah"), ("F", "girls", "Adair")):
            UI.gender_radio = lambda *a, _g=gender, **k: _g
            at = _new("5_Rankings.py")
            at.session_state["rk_season"] = SEASON   # widget is keyed on the LABEL
            at.run()
            assert not at.exception, \
                f"Rankings [{tag}] raised: {[repr(e.value)[:300] for e in at.exception]}"
            body = _no_empty_state(at, f"Rankings [{tag}]")
            n_df = len(at.get("dataframe") or [])
            ok(n_df > 0 or len(body) > 500,
               f"Rankings [{tag}] shows real content ({n_df} tables, {len(body)} chars)")
            # Do NOT assert a specific tracked team appears: Sequoyah is 422nd of
            # 748 and the default view is a leaderboard, so its absence is
            # correct. Prove the board is populated instead — many real team
            # names from this season's ratings, rendered on the page.
            import helpers.team_ratings as TR
            names = {r["name"] for r in TR.score_ratings(
                gender=gender, season=SEASON).values()}
            hits = sum(1 for n in names if n.lower() in body.lower())
            ok(hits >= 10,
               f"Rankings [{tag}] lists {hits} real {SEASON} teams by name")
    finally:
        UI.gender_radio = real_radio


def test_dashboard_offline():
    """Team 1755 is SEQUOYAH (CLAREMORE) Boys — the team the meeting is about,
    and the only one with all 8 tracked games behind it."""
    import helpers.ui as UI
    real_radio = UI.gender_radio
    UI.gender_radio = lambda *a, **k: "M"
    try:
        at = _new("6_Team_Dashboard.py")
        at.session_state["ta_team"] = 1755
        at.session_state["ta_season"] = SEASON
        at.run()
        assert not at.exception, \
            f"Team Dashboard raised: {[repr(e.value)[:300] for e in at.exception]}"
        body = _no_empty_state(at, "Team Dashboard")
        ok(len(body) > 300, f"Team Dashboard shows real content ({len(body)} chars)")
        ok("sequoyah" in body.lower(),
           "Team Dashboard renders SEQUOYAH (CLAREMORE) Boys")
    finally:
        UI.gender_radio = real_radio


if __name__ == "__main__":
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        cut_the_wire()
        print("NETWORK CUT — only loopback allowed\n")
        test_data()
        test_rankings_offline()
        test_dashboard_offline()
    finally:
        os.chdir(cwd)
    print(f"\nblocked outbound attempts: {sorted(set(BLOCKED)) or 'NONE'}")
    print(f"ALL {PASSED} CHECKS PASSED")
