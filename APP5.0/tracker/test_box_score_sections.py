"""Every box-score section stands up alone, and the ones that can, lead with a read.

`render_box_score` runs nine sections behind one lazy switcher (the 2026-09-05
conversion off `st.tabs`, which used to execute all nine on every open and
profiled at 10.7s of the Schedule view's 10.8s). Lazy dispatch means a section
that used to be carried by a sibling's work has to stand up alone, so every one
of them is rendered separately here.

The second half of the file is the shape assertion: the box score is the
artefact every coach already knows how to read AND the Free tier's whole
funnel, and until this pass its only sentence sat in an expander below five
metric tiles. Five sections now lead with a verdict card. Four deliberately do
not, and the list of those four is in the test so that dropping a read is a
decision someone has to make on purpose.

ORDER matters too, and it is asserted: "Box Score" sat sixth, behind four
analytics sections, in a thing called a box score.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%/Programs/Python/Python312/python.exe
        tracker/test_box_score_sections.py
"""
import os
import re
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print("  ok  " + str(label).encode("ascii", "replace").decode("ascii"))


from database.db import query             # noqa: E402

_ROWS = query("SELECT g.id, COUNT(e.id) AS n FROM games g "
              "JOIN game_events e ON e.game_id = g.id "
              "WHERE g.tracked = 1 GROUP BY g.id ORDER BY n DESC LIMIT 1")
if not _ROWS:
    print("  -- no tracked games in this DB; smoke skipped")
    sys.exit(0)
GAME_ID = _ROWS[0]["id"]
print(f"game {GAME_ID} ({_ROWS[0]['n']} events)")

#: The order a coach meets them in. Overview is the read; the box table is the
#: artefact and follows it; Lineups is last because it is the most specialised
#: section and the most expensive one.
ORDER = ["Overview", "Box Score", "Flow", "Shooting", "Quarters",
         "Four Factors", "Play Types", "Defense", "Lineups"]

#: Sections that deliberately carry no verdict card, and why.
QUIET = {
    # the table IS the artefact; the Overview read three clicks up already
    # says what happened, and saying it twice teaches a coach to skim
    "Box Score",
    # KPI tiles (most used / best / worst) do this section's reading, and they
    # carry their own sample gate
    "Play Types",
    "Defense",
    # single-game five-man units. The section's own caption says to read them
    # directionally; a verdict over 6 possessions would be an invented one
    "Lineups",
}


def _render(section):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "_bs_section_probe.py")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("import sys, streamlit as st\n"
                 f"sys.path.insert(0, r'{_APP}')\n"
                 "from helpers.ui import page_chrome\n"
                 "page_chrome('probe')\n"
                 "from helpers.box_score import render_box_score\n"
                 f"render_box_score({GAME_ID})\n")
    cwd = os.getcwd()
    os.chdir(here)                                  # secrets-free cwd
    try:
        at = AppTest.from_file(src, default_timeout=1800)
        at.session_state[f"bs{GAME_ID}_section"] = section
        at.run()
        assert not at.exception, (
            f"section {section!r} raised: "
            f"{[repr(e.value)[:500] for e in at.exception]}")
        md = " ".join(m.value for m in at.markdown if isinstance(m.value, str))
        cap = " ".join(c.value for c in at.caption
                       if isinstance(c.value, str))
        return md, cap, len(at.dataframe)
    finally:
        os.chdir(cwd)
        try:
            os.remove(src)
        except OSError:
            pass


# -- the order, read off the module rather than off a screenshot --------------
print("\nthe box table is the second thing in a box score, not the sixth")
import helpers.box_score as BS            # noqa: E402
_src = open(BS.__file__, encoding="utf-8").read()
_m = re.search(r"_SECTIONS = \[(.*?)\]", _src, re.S)
_declared = re.findall(r'"([^"]+)"', _m.group(1)) if _m else []
ok(_declared == ORDER, f"_SECTIONS is {ORDER}, got {_declared}")


# -- every section renders alone ---------------------------------------------
print("\nevery section renders alone, with no engine degraded")
BODIES, TABLES = {}, {}
for _s in ORDER:
    _md, _cap, _ndf = _render(_s)
    BODIES[_s], TABLES[_s] = _md + " " + _cap, _ndf
    ok(len(_md) > 500, f"'{_s}' rendered ({len(_md)} chars of markdown)")
    _bad = re.findall(r"[A-Za-z' /]+unavailable [—-] [A-Za-z]+Error",
                      BODIES[_s])
    ok(not _bad, f"'{_s}' did not fall into an error caption {_bad}")


# -- the read leads ----------------------------------------------------------
#: What each opted-out section carries INSTEAD. A section is allowed to skip
#: the verdict card, but not to lead with nothing — so the opt-out has to name
#: the thing doing the reading in its place.
INSTEAD = {
    # "Box Score" reads through its TABLES, which are dataframes and carry no
    # markdown at all — so that one is checked by count.
    "Play Types": "kpi-tile",             # most used / best / worst
    "Defense": "kpi-tile",
    "Lineups": "read directionally",      # the sample warning, in words
}

print("\nfive sections lead with a verdict card; four name what reads for them")
for _s in ORDER:
    _has = "gloss-card" in BODIES[_s]
    if _s == "Box Score":
        ok(TABLES[_s] >= 2,
           f"'Box Score' opts out of a verdict card and leads with the two "
           f"box TABLES ({TABLES[_s]} rendered)")
    elif _s in QUIET:
        ok(INSTEAD[_s] in BODIES[_s],
           f"'{_s}' opts out of a verdict card and leads with "
           f"{INSTEAD[_s]!r} instead")
    else:
        ok(_has, f"'{_s}' leads with a verdict card")


# -- and the Overview read is the engine's, not a second opinion --------------
print("\nthe Overview read is postgame's, badged")
_ov = BODIES["Overview"]
ok("the result" in _ov, "the result line is badged")
ok("Auto-generated from the four-factors" in _ov,
   "and says which engines wrote it")
ok("Team comparison" in _ov, "the comparison table follows the read")
ok("Edge" in _ov or "rows that have a better direction" in _ov,
   "and the comparison says who won each row")


print(f"\nALL {PASSED} CHECKS PASSED")
