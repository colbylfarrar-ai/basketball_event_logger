"""
The Event Editor's five tools, each rendered on its own.

The page used to be one scroll: five tools stacked, the namesake grid ~380 lines
below the fold, and every rerun rebuilding all five. It is lazy `_seg` sections
now, and that conversion has exactly one failure mode — a name that one section
happened to define and another read is a NameError the moment a coach opens the
second one. `tools/seg_leak_sweep.py` catches that statically; this catches what
static analysis cannot, by rendering each tool alone against a real book.

Needs a book with tracked events. Prefers the frozen production snapshot at
~/app5_demo (see `offline-demo-run-py`), falls back to the ordinary data dir,
and skips cleanly when neither has a tracked game — this is a smoke test, not a
data assertion.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_event_editor_tools.py
"""
import os
import sys
from pathlib import Path

_APP = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _APP)

# Prefer the frozen prod snapshot; it is the only local book guaranteed to carry
# tracked events. Set BEFORE database.db resolves its path.
_DEMO = Path.home() / "app5_demo" / "analytics.db"
if _DEMO.exists() and not os.environ.get("APP5_DATA_DIR"):
    os.environ["APP5_DATA_DIR"] = str(_DEMO.parent)

from database.db import query                       # noqa: E402
import helpers.auth as AUTH                         # noqa: E402

PASSED = 0
TOOLS = ["Fix events", "Shot locations", "Add an event", "Bulk tags", "Lineups"]


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print("  ok  " + str(label).encode("ascii", "replace").decode("ascii"))


_games = query("SELECT g.id, COUNT(e.id) n FROM games g "
               "JOIN game_events e ON e.game_id=g.id GROUP BY g.id "
               "ORDER BY n DESC LIMIT 1")
if not _games:
    print("no tracked events in this book - nothing to render; skipping.")
    raise SystemExit(0)
GID = _games[0]["id"]

# The page is Paid-gated and read-filtered, so it needs a real identity. An
# admin on the allowlist is the one that can open any game.
_admin = query("SELECT email FROM app_users WHERE role='admin' ORDER BY added_at "
               "LIMIT 1")
if not _admin:
    print("no admin on the allowlist in this book; skipping.")
    raise SystemExit(0)
os.environ[AUTH.DEMO_AS_ENV] = _admin[0]["email"]


def render(tool):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        at = AppTest.from_file(os.path.join(_APP, "pages", "3_Event_Editor.py"),
                               default_timeout=900)
        at.session_state["ee_tool"] = tool
        at.run()
        assert not at.exception, (
            f"Event Editor[{tool}] raised: "
            f"{[repr(e.value)[:400] for e in at.exception]}")
        return at
    finally:
        os.chdir(cwd)


for _t in TOOLS:
    at = render(_t)
    ok(True, f"'{_t}' renders on its own")

# The grid is what the page is FOR, so it leads. A tool order that buries it
# again is the regression this pins.
_src = Path(_APP, "pages", "3_Event_Editor.py").read_text(encoding="utf-8")
ok('_EE_TOOLS = ["Fix events"' in _src, "the event grid is the first tool")
# `st.tabs(` — the call, not the word in the comment explaining why it is not used.
ok("st.tabs(" not in _src,
   "sections are _seg, not st.tabs (which snaps back on every rerun)")

# The filters govern three tools and are drawn only for those three. Drawing a
# filter above a tool it does not affect is what the two bulk captions used to
# have to apologise for.
ok('_EE_FILTERED = ("Fix events", "Shot locations", "Bulk tags")' in _src,
   "the quarter / event-type filters are scoped to the tools they govern")
_ins = render("Add an event")
ok(not [r for r in _ins.radio if r.label == "Quarter"],
   "no quarter filter is drawn over the insert form")
_lin = render("Lineups")
ok(not [r for r in _lin.radio if r.label == "Event type"],
   "no event-type filter is drawn over the lineup fixer")

print(f"\nALL {PASSED} CHECKS PASSED")
