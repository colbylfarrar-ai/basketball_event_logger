"""
Percentile labels must read 71st, not 71th.

Fourteen surfaces hardcoded `f"{pct}th"` after a percentile. Percentiles land on
every digit, so roughly a third of those labels were wrong at any moment -- the
live Team Dashboard rendered "71th pct", "73th" and "82th", and the Players page
did the same in its heatmap tooltip. Small, but it is the kind of thing a coach
notices immediately and it makes every number beside it look careless.

One helper now owns the suffix (stats.ordinal), and this file both unit-tests it
and re-scans the rendered pages, because the page scan is what found the bug in
the first place -- no unit test could have, since every call site was
independently hardcoded.

Run with the REAL interpreter:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/test_ordinals.py
"""
import os
import re
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

from helpers.stats import ordinal                    # noqa: E402

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print(f"  ok  {label}")


print("\n-- the helper ------------------------------------------------------")

CASES = [(0, "0th"), (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"),
         (10, "10th"), (11, "11th"), (12, "12th"), (13, "13th"), (14, "14th"),
         (20, "20th"), (21, "21st"), (22, "22nd"), (23, "23rd"),
         (71, "71st"), (72, "72nd"), (73, "73rd"), (82, "82nd"), (83, "83rd"),
         (100, "100th"), (101, "101st"), (111, "111th"), (112, "112th"),
         (113, "113th"), (121, "121st")]
bad = [(n, ordinal(n), want) for n, want in CASES if ordinal(n) != want]
ok(not bad, f"all {len(CASES)} suffix cases correct (got {bad})")

ok(ordinal(11) == "11th" and ordinal(12) == "12th" and ordinal(13) == "13th",
   "the teens exception holds")
ok(ordinal(111) == "111th" and ordinal(211) == "211th",
   "and holds past 100, where a naive n%10 rule breaks")
ok(ordinal(71.4) == "71st", "floats round before formatting")
ok(ordinal(None) is None, "None in, None out")
ok(ordinal("x") is None, "a non-number returns None rather than raising")
ok(ordinal("7") == "7th", "a numeric string still works")

print("\n-- no call site hardcodes the suffix any more ----------------------")

PAT = re.compile(r"\}th[\"'<)\s]|\}th pct|\}th pctile|\}th pctl")
offenders = []
for root, _dirs, files in os.walk(_APP):
    if "__pycache__" in root or "tracker" in root or ".git" in root:
        continue
    for f in files:
        if not f.endswith(".py"):
            continue
        p = os.path.join(root, f)
        if os.path.relpath(p, _APP).replace("\\", "/") == "helpers/stats.py":
            continue          # the helper's own docstring quotes the old form
        for i, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
            if PAT.search(line):
                offenders.append(f"{os.path.relpath(p, _APP)}:{i}")
ok(not offenders, f"no f-string hardcodes a 'th' suffix (found {offenders})")


def scan_pages():
    """Render the three pages that carry percentile labels and assert every
    ordinal on them is well formed."""
    global PASSED
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    import helpers.ui as UI
    import helpers.entitlement as ENT

    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    real = (UI.gender_radio, ENT.has_paid_plan, ENT.viewer_is_league_wide)
    UI.gender_radio = lambda *a, **k: "F"
    ENT.has_paid_plan = lambda *a, **k: True
    ENT.viewer_is_league_wide = lambda *a, **k: True
    try:
        for page, seed in (
                ("6_Team_Dashboard.py", {"ta_team": 1,
                                         "ta_season": "2025-2026",
                                         "td_view": "Charts"}),
                ("7_Players.py", {}),
                ("5_Rankings.py", {"rk_season": "2025-2026"})):
            at = AppTest.from_file(os.path.join(_APP, "pages", page),
                                   default_timeout=900)
            for k, v in seed.items():
                at.session_state[k] = v
            at.run()
            assert not at.exception, \
                f"{page} raised: {[repr(e.value)[:200] for e in at.exception]}"
            blob = "\n".join(
                str(getattr(e, "value", "")) for e in (at.get("markdown") or []))
            blob += "\n".join(
                str(getattr(e, "value", "")) for e in (at.get("caption") or []))
            found = set(re.findall(r"\b(\d+)(st|nd|rd|th)\b", blob))
            wrong = [f"{n}{s}" for n, s in found if ordinal(n) != f"{n}{s}"]
            ok(not wrong, f"{page}: every ordinal well formed (bad: {wrong})")
    finally:
        UI.gender_radio, ENT.has_paid_plan, ENT.viewer_is_league_wide = real


if __name__ == "__main__":
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        scan_pages()
    finally:
        os.chdir(cwd)
    print(f"\n{PASSED} checks passed.")
