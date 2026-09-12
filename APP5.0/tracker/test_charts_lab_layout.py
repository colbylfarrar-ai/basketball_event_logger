"""Every Charts and Lab section stands up alone, and leads with a sentence.

Two conversions made this file necessary, and they are the same two that made
`test_insights_layout.py` necessary after the Insights recut:

  * `st.tabs` became `_seg` on Charts -> Quarters (four bodies) and on
    Charts -> Offense -> Shooting (three). Under `st.tabs` every body ran on
    every rerun, so a section could lean on a name a sibling happened to
    define; under lazy dispatch only one body runs and that read is a
    NameError the moment a coach opens it. So every section is rendered
    SEPARATELY below - that is the whole point of the file.
  * Lab lost a level. "Advanced" was a folder over three unrelated tools and
    its three children are now Lab's own sections, which means the session key
    `lab_sub` changed vocabulary and every cross-link naming the old path had
    to follow.

And one rule, asserted rather than described: **a section leads with the
sentence its charts are evidence for.** Charts is the evidence wall behind
Insights, and a wall with no sentence over it is what this pass was for.

SEASON TRAP: SEAS.ACTIVE is "Current" and can hold zero tracked games; the
tracked book sits under an archived label. Drive the picker there or the page
renders a healthy-looking empty state and proves nothing.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%/Programs/Python/Python312/python.exe
        tracker/test_charts_lab_layout.py
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
    # the console here is cp1252 and these labels quote real UI strings
    print("  ok  " + str(label).encode("ascii", "replace").decode("ascii"))


import helpers.seasons as SEAS            # noqa: E402
from database.db import query             # noqa: E402


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
    print("  -- no tracked games in this DB; smoke skipped")
    sys.exit(0)

counts = {}
for r in query("SELECT team1_id a, team2_id b FROM games WHERE tracked=1"):
    for t in (r["a"], r["b"]):
        if t is not None:
            counts[t] = counts.get(t, 0) + 1
TEAM_ID = max(counts, key=counts.get)
print(f"pool: {SEASON} / {GENDER} - {len(GIDS)} games; team {TEAM_ID} "
      f"({counts[TEAM_ID]} tracked games)")

#: One entry per LEAF a coach can actually land on.
LEAVES = [
    ("Charts / Offense / Scoring",
     {"ch_sub": "Offense", "ch_sub_off": "Scoring"}),
    ("Charts / Offense / Shooting / Shot Profile",
     {"ch_sub": "Offense", "ch_sub_off": "Shooting",
      "ch_sh_sub": "Shot Profile"}),
    ("Charts / Offense / Shooting / Contest",
     {"ch_sub": "Offense", "ch_sub_off": "Shooting", "ch_sh_sub": "Contest"}),
    ("Charts / Offense / Shooting / Creation",
     {"ch_sub": "Offense", "ch_sub_off": "Shooting",
      "ch_sh_sub": "Creation & Shot-making"}),
    ("Charts / Offense / Playmaking",
     {"ch_sub": "Offense", "ch_sub_off": "Playmaking"}),
    ("Charts / Play Style", {"ch_sub": "Play Style"}),
    ("Charts / Defense / Team Defense",
     {"ch_sub": "Defense", "ch_sub_def": "Team Defense"}),
    ("Charts / Defense / Scheme",
     {"ch_sub": "Defense", "ch_sub_def": "Scheme"}),
    ("Charts / Defense / Glass", {"ch_sub": "Defense", "ch_sub_def": "Glass"}),
    ("Charts / Defense / Stops", {"ch_sub": "Defense", "ch_sub_def": "Stops"}),
    ("Charts / Situational", {"ch_sub": "Situational"}),
    ("Charts / Trends", {"ch_sub": "Trends"}),
    ("Charts / Quarters / Scoring & Efficiency",
     {"ch_sub": "Quarters", "ch_q_sub": "Scoring & Efficiency"}),
    ("Charts / Quarters / Shooting",
     {"ch_sub": "Quarters", "ch_q_sub": "Shooting"}),
    ("Charts / Quarters / Control",
     {"ch_sub": "Quarters",
      "ch_q_sub": "Control · Glass · Discipline"}),
    ("Charts / Quarters / Reference Tables",
     {"ch_sub": "Quarters", "ch_q_sub": "Reference Tables"}),
    ("Charts / Winning Formula", {"ch_sub": "Winning Formula"}),
]
LAB_LEAVES = [
    ("Lab / Efficiency & DNA", {"lab_sub": "Efficiency & DNA"}),
    ("Lab / Résumé & Form", {"lab_sub": "Résumé & Form"}),
    ("Lab / Game Flow", {"lab_sub": "Game Flow"}),
    ("Lab / Impact Lab", {"lab_sub": "Impact Lab"}),
    ("Lab / Chart Builder", {"lab_sub": "Chart Builder"}),
]


def _render(view, extra):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    page = os.path.join(_APP, "pages", "6_Team_Dashboard.py")
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        at = AppTest.from_file(page, default_timeout=1800)
        at.session_state["ta_team"] = TEAM_ID
        at.session_state["ta_season"] = SEASON
        at.session_state["ta_gender"] = GENDER
        at.session_state["td_view"] = view
        for k, v in extra.items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, (
            f"{view} {extra} raised: "
            f"{[repr(e.value)[:500] for e in at.exception]}")
        md = " ".join(m.value for m in at.markdown if isinstance(m.value, str))
        cap = " ".join(c.value for c in at.caption
                       if isinstance(c.value, str))
        return md, cap
    finally:
        os.chdir(cwd)


# -- every leaf stands up alone -----------------------------------------------
print("\nevery Charts / Lab section renders alone, with no engine degraded")
BODIES = {}
for _label, _extra in LEAVES + LAB_LEAVES:
    _view = "Charts" if _label.startswith("Charts") else "Lab"
    _md, _cap = _render(_view, _extra)
    BODIES[_label] = _md + " " + _cap
    ok(len(_md) > 1000, f"'{_label}' rendered ({len(_md)} chars of markdown)")
    _degraded = re.findall(
        r"[A-Za-z' /]+unavailable [—-] [A-Za-z]+Error", BODIES[_label])
    ok(not _degraded,
       f"'{_label}' did not fall into an error caption {_degraded}")

_ALL = " ".join(BODIES.values())


# -- the nav says what it is --------------------------------------------------
print("\nLab is one level, and every name says what it is")
_lab = BODIES["Lab / Efficiency & DNA"]
for _name in ("Efficiency & DNA", "Résumé & Form", "Game Flow",
              "Impact Lab", "Chart Builder"):
    ok(_name in _lab, f"Lab's caption names '{_name}'")


# -- Charts -> Quarters leads with the quarter read ---------------------------
print("\nCharts -> Quarters leads with the read, and discloses what repeats")
_q = BODIES["Charts / Quarters / Scoring & Efficiency"]
ok("gloss-card" in _q or "same team for 32 minutes" in _q,
   "the quarter read renders - a verdict card, or the 'level' sentence, "
   "which is an answer and not an empty state")
ok("SB .596" in _q, "the caption states the tempo reliability that ships")
ok("measured and refused" in _q,
   "and that quarter shooting / ball security were measured and refused")
ok("Scoring & Efficiency" in _q and "Reference Tables" in _q,
   "the four sections are a switcher, not four st.tabs bodies")


# -- the possession-length panel quotes a measured number ---------------------
print("\nCharts -> Offense -> Scoring prices the possession, it does not guess")
_sc = BODIES["Charts / Offense / Scoring"]
ok("usually the most efficient" not in _sc, "the folklore caption is gone")
ok("measured knee" in _sc,
   "the caption says the 7s cut is measured, not conventional")
ok("SB .746" in _sc, "and that the early SHARE is the half that repeats")


# -- every leaf that can carry a read, does -----------------------------------
# A leaf may legitimately say nothing (a thin book, a tag nobody pressed), so
# the bar is: a verdict card, a percentile rail, KPI tiles, or words saying
# why there is none.
print("\nevery section leads with a sentence, or says why it has none")
_QUIET = {
    # a free-form chart builder has no finding to report - it is a tool
    "Lab / Chart Builder",
    # reference grids under the Quarters read, which sits above the switcher
    "Charts / Quarters / Shooting",
    "Charts / Quarters / Control",
    "Charts / Quarters / Reference Tables",
}
for _label, _body in BODIES.items():
    if _label in _QUIET:
        continue
    _has = ("gloss-card" in _body or "pl-pct" in _body
            or "kpi-tile" in _body or "thin sample" in _body
            or "Tracked games needed" in _body or "No tracked games" in _body
            or "Need at least two tracked games" in _body
            or "same team for 32 minutes" in _body)
    ok(_has, f"'{_label}' leads with a read (or states why it has none)")


print(f"\nALL {PASSED} CHECKS PASSED")
