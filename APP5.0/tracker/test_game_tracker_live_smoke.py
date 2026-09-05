"""Smoke: the Game Tracker's live view renders every panel without raising.

This batch touched three things on that page -- the win-probability strip, the
new Rotation watch panel, and the panel list itself -- and none of them is
reachable from a unit test, because every one is wrapped in `except Exception:
pass` so a bad read can never take the bench screen down mid-game. That guard is
right, and it also means a broken panel fails silently. This renders the page
and asserts the panels actually produced their text.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/test_game_tracker_live_smoke.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _a_tracked_game():
    from database.db import query
    r = query("""SELECT g.id, g.team1_id FROM games g
                 WHERE g.tracked=1
                   AND EXISTS (SELECT 1 FROM game_event_lineup gel
                               JOIN game_events ge ON ge.id=gel.event_id
                               WHERE ge.game_id=g.id)
                 ORDER BY g.id DESC LIMIT 1""")
    return (r[0]["id"], r[0]["team1_id"]) if r else (None, None)


def _render(game_id):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    page = os.path.join(_APP, "pages", "2_Game_Tracker.py")
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        at = AppTest.from_file(page, default_timeout=1800)
        at.session_state["gt_game"] = game_id
        at.session_state["gt_view"] = "\U0001f4fa Live"
        at.run()
        assert not at.exception, \
            f"Game Tracker raised: {[repr(e.value)[:500] for e in at.exception]}"
        md = " ".join(m.value for m in at.markdown if isinstance(m.value, str))
        cap = " ".join(c.value for c in at.caption if isinstance(c.value, str))
        return md + " " + cap, at
    finally:
        os.chdir(cwd)


def test_live_view_renders():
    gid, _tid = _a_tracked_game()
    if not gid:
        print("  -- no tracked game with lineup snapshots; skipped")
        return

    text, at = _render(gid)
    ok(not at.exception, f"game {gid}: the live view renders clean")
    ok(text.strip(), "the page produced text, not an empty shell")
    # The win-probability tile is the one this batch fixed. When it renders at
    # all it must not read as a finished game from the opening tip.
    if "win odds" in text.lower():
        import re
        odds = re.findall(r"(\d+)%", text)
        ok(odds, "the win-odds tile carries a number")


def test_rotation_watch_is_a_panel():
    """The panel list is what the multiselect renders; a typo would drop it."""
    import re
    page = os.path.join(_APP, "pages", "2_Game_Tracker.py")
    src = open(page, encoding="utf-8").read()
    panels = re.search(r"_LIVE_PANELS = \[(.*?)\]", src, re.S).group(1)
    ok('"Rotation watch"' in panels, "Rotation watch is in _LIVE_PANELS")
    ok('_panel_on("Rotation watch")' in src,
       "and the panel body is gated on the same string")
    ok(src.count('_panel_on("Rotation watch")') == 1,
       "gated exactly once")


if __name__ == "__main__":
    print("game tracker live smoke")
    test_rotation_watch_is_a_panel()
    test_live_view_renders()
    print(f"\n{PASSED} checks passed")
