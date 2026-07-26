"""The Insights evidence-jump buttons — clicked, not just rendered.

WHY THIS FILE EXISTS. `test_insights_layout.py` renders the Insights view and
passes 51 checks over a page that crashed the moment a coach touched it. It
seeds `td_view` in session_state and asserts on the RENDER; the defect lived in
the button's CLICK handler, which no smoke had ever run:

    st.session_state["td_view"] = v          # inside the tab body
    StreamlitAPIException: `st.session_state.td_view` cannot be modified
    after the widget with key `td_view` is instantiated.

`td_view` is the key of the segmented_control at the top of
`6_Team_Dashboard.py`. The Insights tab renders ~4,000 lines later, so by then
the widget exists and the write is illegal — a full-page traceback, not a
degraded card. The fix parks the destination in a plain (non-widget) key,
`insights_tab.TD_VIEW_GOTO`, and the page consumes it into `td_view` before
building the switcher.

The lesson worth keeping: rendering a control is not exercising it. Any
session_state write aimed at a WIDGET key needs a click test, because the
render test cannot reach it.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_view_jumps.py
"""
import os
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print("  ok  " + str(label).encode("ascii", "replace").decode("ascii"))


import helpers.seasons as SEAS                            # noqa: E402
from database.db import query                             # noqa: E402
from helpers.dashboard import insights_tab as IT          # noqa: E402


def _tracked():
    best = (None, None, [])
    for value, _label in SEAS.season_options():
        for g in ("F", "M"):
            pool = SEAS.game_pool(value, gender=g, tracked_only=True) or []
            if len(pool) > len(best[2]):
                best = (value, g, sorted(pool))
    return best


SEASON, GENDER, GIDS = _tracked()
if not GIDS:
    print("  -- no tracked games in this DB; skipped")
    sys.exit(0)

counts = {}
for r in query("SELECT team1_id a, team2_id b FROM games WHERE tracked=1"):
    for t in (r["a"], r["b"]):
        if t is not None:
            counts[t] = counts.get(t, 0) + 1
TEAM_ID = max(counts, key=counts.get)


print("-- the parked-jump contract ------------------------------------------")

ok(IT.TD_VIEW_GOTO != "td_view",
   "the handshake key is NOT the widget key -- that is the whole point")
_src = (_APP / "helpers" / "dashboard" / "insights_tab.py").read_text(
    encoding="utf-8")
# Comment lines are exempt: the fix's own comment quotes the illegal write to
# explain why it is illegal, and that explanation is worth more than a grep
# that cannot tell code from prose.
_code = [ln for ln in _src.splitlines() if not ln.lstrip().startswith("#")]
ok(not any('st.session_state["td_view"]' in ln for ln in _code),
   "the Insights tab never writes the switcher's widget key directly")
_page_src = (_APP / "pages" / "6_Team_Dashboard.py").read_text(encoding="utf-8")
ok(_page_src.index("TD_VIEW_GOTO") < _page_src.index('key="td_view"'),
   "and the page consumes the parked jump BEFORE instantiating the switcher, "
   "which is the only moment the write is legal")


print("\n-- clicking a jump does not blow the page up -------------------------")

import streamlit as st                                    # noqa: E402
from streamlit.testing.v1 import AppTest                  # noqa: E402
import helpers.ui as UI                                   # noqa: E402

st.page_link = lambda *a, **k: None
st.sidebar.page_link = lambda *a, **k: None

# HARNESS PATCH, not a product concession. AppTest cannot round-trip a
# SINGLE-SELECT `st.segmented_control`: it rebuilds the selection with
# `[options.index(format_func(v)) for v in self.value]`, and for a single
# select `self.value` is the string "Insights", so it iterates CHARACTERS and
# dies on `ValueError: content: "I" is not in list`. That is an AppTest defect,
# not ours, and it is why no existing smoke could ever click this control.
#
# `helpers.ui.seg` already documents an `st.radio` fallback for hosts without
# segmented_control, so the test drives THAT path. The widget differs; the thing
# under test does not -- both take `key="td_view"`, and the regression is about
# who may write that key and when. The page imports `seg` by value at module
# scope, and AppTest re-executes the page each run, so patching here lands.
_real_seg = UI.seg


def _plain_seg(label, options, *, default=None, key=None, format_func=str,
               help=None, label_visibility="visible", container=None):
    c = container if container is not None else st
    idx = options.index(default) if default in options else 0
    return c.radio(label, options, index=idx, key=key, format_func=str,
                   horizontal=True, help=help,
                   label_visibility=label_visibility)


UI.seg = _plain_seg
# The unkeyed gender picker otherwise pops a `ta_team` outside its pool.
UI.gender_radio = lambda *a, **k: GENDER

_cwd = os.getcwd()
os.chdir(os.path.dirname(os.path.abspath(__file__)))       # secrets-free cwd
try:
    at = AppTest.from_file(str(_APP / "pages" / "6_Team_Dashboard.py"),
                           default_timeout=1800)
    at.session_state["ta_team"] = TEAM_ID
    at.session_state["ta_season"] = SEASON
    at.session_state["td_view"] = "Insights"
    at.run()
    ok(not at.exception,
       f"the Insights view renders (team {TEAM_ID}, {SEASON}/{GENDER})")

    jumps = [b for b in at.button if str(getattr(b, "key", "") or "")
             .startswith(("insj_", "ins_jump", "insjump", "deck5_"))]
    ok(bool(jumps), f"the evidence jumps are on the page ({len(jumps)} buttons)")

    _before = at.session_state["td_view"]
    jumps[0].click().run()
    ok(not at.exception,
       "clicking one does not raise -- this is the regression; it used to be "
       "StreamlitAPIException: cannot be modified after the widget ... is "
       "instantiated")
    _after = at.session_state["td_view"]
    ok(_after != _before,
       f"and it actually switches the view ({_before} -> {_after})")
    ok(IT.TD_VIEW_GOTO not in at.session_state,
       "the parked key is consumed, not left to fire again on the next run")

    # ── THE SUB-VIEW HALF (2026-07-26) ──────────────────────────────────────
    # A view-only jump landed on Charts' FIRST sub-tab whatever the evidence
    # actually was, because st.tabs cannot be selected from session state. The
    # payload is now (view, path) and the inner switchers are `_seg`, so each
    # one consumes the step it recognises on the way down.
    print("\n-- the sub-view half of the handshake -------------------------------")
    ok(IT.TD_SUB_GOTO != IT.TD_VIEW_GOTO,
       "the sub-destination has its own plain key")
    ok(_page_src.index("TD_SUB_GOTO") < _page_src.index('key="ch_sub"'),
       "and the page parks it BEFORE any inner switcher widget exists")

    at2 = AppTest.from_file(str(_APP / "pages" / "6_Team_Dashboard.py"),
                            default_timeout=1800)
    at2.session_state["ta_team"] = TEAM_ID
    at2.session_state["ta_season"] = SEASON
    at2.session_state["td_view"] = "Insights"
    at2.run()
    _named = [b for b in at2.button
              if "→" in str(getattr(b, "label", "") or "")
              and str(getattr(b, "key", "") or "").startswith("insj_")]
    ok(bool(_named),
       f"the evidence buttons name a full path ({[b.label for b in _named][:3]})")
    _target = _named[0]
    _label = str(_target.label)
    _target.click().run()
    ok(not at2.exception, "clicking a two-hop jump does not raise")
    ok(at2.session_state["td_view"] in _label,
       f"it lands on the named view ({at2.session_state['td_view']} in "
       f"{_label!r})")
    # the sub-step the button promised is now the inner switcher's selection
    _steps = [s.strip() for s in _label.replace("→", "|").split("|")][1:]
    _steps = [s for s in _steps if s]
    # AppTest's session_state has no .get(), and reading a missing key raises
    _picked = set()
    for _k in ("ch_sub", "ch_sub_off", "ch_sub_def", "lab_sub"):
        try:
            _picked.add(at2.session_state[_k])
        except (KeyError, AttributeError):
            pass
    if _steps:
        ok(_steps[0] in _picked,
           f"and on the named SUB-view: {_steps[0]!r} is selected "
           f"({sorted(x for x in _picked if x)})")
    ok(IT.TD_SUB_GOTO not in at2.session_state,
       "the parked path is fully consumed -- a leftover step would hijack a "
       "switcher three clicks later")
finally:
    os.chdir(_cwd)

print(f"\nALL {PASS} CHECKS PASSED")
