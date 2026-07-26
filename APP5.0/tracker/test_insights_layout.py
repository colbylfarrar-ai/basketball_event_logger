"""End-to-end render of the RESTRUCTURED Insights tab (masthead + five tabs).

The 2026-07-25 restructure turned a flat ~20-block scroll into a plain-English
masthead over five sub-tabs, collapsed three tables that were rendering on both
Insights and Charts down to a verdict plus a jump, and removed every truncation
cap on the page.

What only an end-to-end render catches:

  * `st.tabs` executes EVERY tab body on every run, so a section that used to
    sit safely below an early `return` now runs unconditionally — a shape that
    was previously unreachable on a thin team is now reachable;
  * the masthead reads three engines through one cached bundle, and a missing
    key there degrades to an error caption that looks like normal empty state;
  * the brief's whole purpose is to be readable with no basketball knowledge,
    so the unglossed-jargon check below is a real requirement, not style
    policing.

SEASON TRAP: SEAS.ACTIVE is "Current" and has zero games; the tracked book is
under the archived "2025-2026" label. Drive the picker there or the page
renders a healthy-looking empty state and proves nothing.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_insights_layout.py
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
    # the console here is cp1252; labels quote real UI strings that carry
    # arrows and box glyphs, so never let a print kill a passing run
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

# the team with the MOST tracked games — a thin team proves nothing about a
# layout whose job is to organise a lot of output
counts = {}
for r in query("SELECT team1_id a, team2_id b FROM games WHERE tracked=1"):
    for t in (r["a"], r["b"]):
        if t is not None:
            counts[t] = counts.get(t, 0) + 1
TEAM_ID = max(counts, key=counts.get)
print(f"pool: {SEASON} / {GENDER} — {len(GIDS)} games; team {TEAM_ID} "
      f"({counts[TEAM_ID]} tracked games)")


def _render():
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.page_link = lambda *a, **k: None
    st.sidebar.page_link = lambda *a, **k: None
    page = os.path.join(_APP, "pages", "6_Team_Dashboard.py")
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))   # secrets-free cwd
    try:
        at = AppTest.from_file(page, default_timeout=1200)
        at.session_state["ta_team"] = TEAM_ID
        at.session_state["ta_season"] = SEASON
        at.session_state["td_view"] = "Insights"
        at.run()
        assert not at.exception, \
            f"Insights raised: {[repr(e.value)[:500] for e in at.exception]}"
        md = " ".join(m.value for m in at.markdown if isinstance(m.value, str))
        cap = " ".join(c.value for c in at.caption if isinstance(c.value, str))
        tabs = [t.label for t in at.tabs] if hasattr(at, "tabs") else []
        return md + " " + cap, tabs, at
    finally:
        os.chdir(cwd)


try:
    BODY, TABS, AT = _render()
except Exception as exc:                       # pragma: no cover
    print(f"  !! render could not run ({type(exc).__name__}: {exc})")
    raise

print(f"rendered {len(BODY)} chars, {len(TABS)} tab labels")

ok(len(BODY) > 5000, f"the Insights view rendered ({len(BODY)} chars)")


# ── the auto-scout board ─────────────────────────────────────────────────────
print("\nthe auto-scout board is present and built")
ok("Auto-scout" in BODY, "the auto-scout header rendered")
ok("Auto-scout unavailable" not in BODY,
   "the board did not fall into its error caption")
for probe, label in (
        ("Extra shots", "the volume term is named"),
        ("Selection", "the quality term is named"),
        ("Shot-making", "the making term is named"),
        ("Free throws", "the free-throw term is named")):
    ok(probe in BODY, label)
ok("Team flags" in BODY, "the team-flag block rendered")


# ── the sub-tabs ─────────────────────────────────────────────────────────────
print("\nthe five sub-tabs exist, and nothing sits above them")
for want in ("Auto-scout", "Players", "Defense", "Wins & losses",
             "Every engine"):
    ok(any(want in t for t in TABS), f"tab '{want}' is present")
ok(TABS and "Auto-scout" in TABS[0],
   "auto-scout is the FIRST tab — a coach lands on the read, not on a scroll")
ok("Deep-dive sections unavailable" not in BODY,
   "no tab fell into its error caption")
ok("Ported sections unavailable" not in BODY, "the ported half rendered")
ok("Defensive board unavailable" not in BODY, "the defensive board rendered")


# ── the depth is still all there ─────────────────────────────────────────────
print("\nnothing was consolidated away")
for probe, label in (
        ("what each player is asked to guard", "defensive board"),
        ("DLOAD", "DLOAD% column"),
        ("Foul rate", "foul-rate board"),
        ("gathered here", "ported verdicts"),
        ("Force them off their hand", "force-hand board"),
        ("Space dependence", "space-dependence board"),
        ("Who won games on defense", "defensive WPA"),
        ("Auto-scout", "the auto-scout feed"),
        ("Game by game", "the per-game margin ledger")):
    ok(probe in BODY, f"{label} still renders")


# ── the duplicate tables became verdict + jump ───────────────────────────────
print("\nthe three duplicated tables are verdicts here, tables on Charts")
_btns = [b.label for b in AT.button] if hasattr(AT, "button") else []
_jumps = [b for b in _btns if "Charts" in b]
ok(len(_jumps) >= 1,
   f"at least one 'the full table is on Charts' jump rendered ({_jumps})")
ok("Look quality (xPPS)" not in BODY,
   "the passer TABLE no longer renders here — Charts owns it")
ok("vs Top-half (" not in BODY,
   "the top-half/bottom-half TABLE no longer renders here — Charts owns it")
ok("Passer quality" in BODY, "the passer VERDICT is still here")
ok("Do they beat good teams" in BODY, "the strength VERDICT is still here")


# ── the register: coach-to-coach, not explainer ──────────────────────────────
# This assertion is the INVERSE of what it was on 2026-07-25. The first version
# of the brief glossed every term inline for a reader who had never seen a
# basketball game, and it read as condescending to the only audience that will
# ever open the page. A coach does not need ORB or TOV explained.
#
# Asserted against the brief MODULE's own prose rather than the page body: the
# AppTest body is all markdown followed by all captions, so the board cannot be
# sliced out of it by position, and a page-level check would silently pass by
# measuring the wrong text.
print("\nthe register is coach-to-coach, not explainer")
import ast                                           # noqa: E402
import helpers.dashboard.insights_brief as IB        # noqa: E402
_bsrc = open(IB.__file__, encoding="utf-8").read()
# Collect string CONSTANTS via ast, not by regex: f-strings are JoinedStr nodes
# whose literal halves are separate constants, and implicit concatenation across
# lines defeats any regex worth reading. Docstrings are dropped because this
# module's header discusses the register deliberately.
_tree = ast.parse(_bsrc)
_docs = set()
for _n in ast.walk(_tree):
    if isinstance(_n, (ast.Module, ast.FunctionDef, ast.ClassDef)):
        _d = ast.get_docstring(_n, clean=False)
        if _d:
            _docs.add(_d)
_lits = " ".join(
    _n.value for _n in ast.walk(_tree)
    if isinstance(_n, ast.Constant) and isinstance(_n.value, str)
    and _n.value not in _docs)

# the specific sentences that made it read as a lecture
for banned, label in (
        ("never watched", "no 'never watched a game' framing"),
        ("quick orientation", "no orientation paragraph"),
        ("A team wins by scoring", "does not explain the object of the game"),
        ("losing the ball", "does not gloss 'turnover'"),
        ("trip down the floor", "does not gloss 'possession'"),
        ("is two players working together",
         "does not define a pick-and-roll")):
    ok(banned.lower() not in _lits.lower(), label)

# shorthand is used BARE, which is the positive half of the same requirement
_short = sorted(set(re.findall(r"\b(ORB|TOV|FGA|PPS|FT|FTs)\b", _lits)))
ok(len(_short) >= 3,
   f"standard shorthand is used without apology ({_short})")

# what the brief still owes the reader: the measurement behind a claim
ok("r=" in _lits, "reliability rides as an r= chip rather than as hedging")

# the team feed is rendered ONCE, on the auto-scout board, not duplicated
ok(_bsrc.count("_team_flags(") <= 3,
   "the team feed has a single render path")


# ── caps are gone ────────────────────────────────────────────────────────────
print("\nno section is silently truncated")
import helpers.dashboard.insights_tab as IT          # noqa: E402
import helpers.dashboard.insights_deep as ID         # noqa: E402
_src = (open(IT.__file__, encoding="utf-8").read()
        + open(ID.__file__, encoding="utf-8").read())
for pat, label in ((r"hb\[:8\]", "force-hand board"),
                   (r"cb\[:10\]", "space-dependence board"),
                   (r"views\[:3\]", "evidence jumps"),
                   (r"rows\[:3\]", "self-scout drift"),
                   (r"key=lambda r: -\(r\.get\(\"REB\"\) or 0\)\)\[:2\]",
                    "rebounding verdicts")):
    ok(not re.search(pat, _src), f"{label} no longer caps its output")

print(f"\nALL {PASSED} CHECKS PASSED")
