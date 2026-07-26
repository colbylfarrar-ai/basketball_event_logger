"""End-to-end render of THE BOOK — the Insights deck over its seven sections.

The 2026-07-26 recut replaced six sub-tabs named after data categories with a
persistent DECK over seven sections named after the question each answers. Four
things changed that only an end-to-end render can check:

  * `st.tabs` became `_seg`. Under st.tabs every body ran on every rerun, which
    is what made a six-tab page expensive; under `_seg` only the open section
    runs, so a section that used to be carried by its neighbours' work now has
    to stand up alone. This file renders EVERY section separately for exactly
    that reason — and it is how the Charts recut's one real casualty was found
    (`_td_shots`, defined in Shooting and used in Glass).
  * the deck renders on every section, so a masthead regression is a
    seven-section regression;
  * `render` finally carries the `@st.fragment` its docstring has claimed since
    it was written;
  * THE FIVE is a spotlight over an uncapped list. If it ever becomes a cap,
    the page silently stops being the deep-dive home. Every no-cap assertion
    from the previous layout survives below, plus new ones for the ranking.

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

SECTIONS = ["Who we are", "Why we win / why we lose", "Who's helping",
            "Who to play together", "What they'll take away", "Monday",
            "Receipts"]


def _render(section=None, extra=None):
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
        at.session_state["td_view"] = "Insights"
        if section:
            at.session_state["ins_section"] = section
        for k, v in (extra or {}).items():
            at.session_state[k] = v
        at.run()
        assert not at.exception, \
            f"Insights[{section}] raised: " \
            f"{[repr(e.value)[:500] for e in at.exception]}"
        md = " ".join(m.value for m in at.markdown if isinstance(m.value, str))
        cap = " ".join(c.value for c in at.caption if isinstance(c.value, str))
        return md + " " + cap, at
    finally:
        os.chdir(cwd)


# ── every section stands up on its own ───────────────────────────────────────
# This is the assertion the `_seg` conversion makes necessary. Under st.tabs a
# section could lean on a name another tab's body happened to define; under
# `_seg` only one body runs, and a leak is a NameError the moment a coach opens
# that section.
print("\nevery section renders alone, with no engine falling back to a caption")
BODIES, ATS = {}, {}
for _s in SECTIONS:
    body, at = _render(_s)
    BODIES[_s], ATS[_s] = body, at
    ok(len(body) > 5000, f"'{_s}' rendered ({len(body)} chars)")
    _degraded = re.findall(r"[A-Za-z' /]+unavailable — [A-Za-z]+Error", body)
    ok(not _degraded, f"'{_s}' did not fall into an error caption {_degraded}")

BODY, AT = BODIES[SECTIONS[0]], ATS[SECTIONS[0]]
_ALL = " ".join(BODIES.values())


# ── the deck ─────────────────────────────────────────────────────────────────
print("\nthe deck is above the switcher, on every section")
for _s in SECTIONS:
    ok("Severity =" in BODIES[_s],
       f"THE FIVE rides above '{_s}' — the deck is the frame, not a section")
for probe, label in (
        ("Extra shots", "the volume term is named"),
        ("Selection", "the quality term is named"),
        ("Shot-making", "the making term is named"),
        ("Free throws", "the free-throw term is named"),
        ("decide their games", "the identity sentence is on the deck"),
        ("pl-pct", "the DNA percentile rail rendered"),
        ("margin/g", "the masthead carries record and margin per game")):
    ok(probe in BODY, label)


# ── THE FIVE is a spotlight, and says so ─────────────────────────────────────
print("\nTHE FIVE is a spotlight over an uncapped list, and admits it")
ok("spotlight, not a cap" in BODY,
   "the deck states in words that nothing there is a cap")
ok("findings fired in total" in BODY,
   "the deck prints the FULL finding count beside the five it shows")
ok("Every finding here" in _ALL,
   "and the sections render the complete list for their own question")
_five = re.search(r"The (\d+) — biggest first", BODY)
ok(_five and int(_five.group(1)) <= 5, "the spotlight is five rows or fewer")
_total = re.search(r"(\d+) findings fired in total", BODY)
ok(_total and int(_total.group(1)) > 5,
   f"and the full list is larger than the spotlight "
   f"({_total.group(1) if _total else '?'} findings)")


# ── THE NON-NEGOTIABLE: the signature stats survive ─────────────────────────
# Four stats, ranked by effect size, that separate THIS team's wins from its
# losses — plus the record split by how many of them a game hit. It is the
# most-quoted block on the page and the recut moved it from a tab named
# "Wins & losses" to a section named "Why we win / why we lose". Moving it is
# fine. Losing it is not.
print("\nthe signature stats survived the recut")
_why = BODIES["Why we win / why we lose"]
for probe, label in (
        ("signature stats", "the signature-stat block is present"),
        ("What separates wins from losses",
         "under its own heading, in the section that asks the question"),
        ("effect-size ranked", "still ranked by effect size, not by taste"),
        ("in wins", "each stat prints its wins value"),
        ("in losses", "and its losses value"),
        ("Record by goals hit", "the record-by-goals-hit ladder is still here"),
        ("Target = midpoint", "and the goal targets are still explained"),
        ("Do they beat good teams", "the strength-of-opponent split is here"),
        ("in wins vs in losses", "the 7-metric win/loss split is here"),
        ("Game by game", "the per-game margin ledger is here")):
    ok(probe in _why, label)


# ── the depth is all still there, in its new home ───────────────────────────
print("\nnothing was consolidated away")
for probe, label in (
        ("what each player is asked to guard", "defensive board"),
        ("DLOAD", "DLOAD% column"),
        ("what each player actually shoots", "offensive board"),
        ("OLOAD", "OLOAD% column"),
        ("Foul rate", "foul-rate board"),
        ("Force them off their hand", "force-hand board"),
        ("Space dependence", "space-dependence board"),
        ("Who won games on defense", "defensive WPA"),
        ("Who won games on offense", "offensive WPA"),
        ("Passer quality", "the passer verdict"),
        ("Ball movement", "the ball-movement verdict"),
        ("Every player, every read", "the uncapped player feed"),
        ("gathered here", "the ported verdicts")):
    ok(probe in _ALL, f"{label} still renders")

# the largest gap the recut closes: the Impact Lab cluster is on Insights now
print("\nthe Impact Lab cluster reached Insights")
_tog = BODIES["Who to play together"]
for probe, label in (
        ("Five-man units", "the 5-man unit table"),
        ("±95%", "with its confidence band"),
        ("Trios & quads", "trios and quads"),
        ("Rotation", "the rotation block"),
        ("Chemistry, synergy and the best fifth", "the on-demand half"),
        ("run on request rather than on every visit",
         "which says on screen why it is behind a button")):
    ok(probe in _tog, f"{label} is on Insights")
ok(any("chemistry pass" in str(b.label).lower()
       for b in ATS["Who to play together"].button),
   "the ~20s chemistry walk is opt-in, not paid on every visit")
ok("Impact board" in BODIES["Who's helping"],
   "RAPM / HoopWAR / WPA render together, off the ridge the page already paid "
   "for")

# section 5 gained the two things Insights had never had: a court, and the
# record of who each defender actually drew
print("\nthe scout's section has a court and a matchup grid")
_scout = BODIES["What they'll take away"]
for probe, label in (
        ("shot chart an opponent", "the shot map — Insights had zone tables "
                                   "and no court anywhere until now"),
        ("Matchup difficulty", "the matchup grid"),
        ("Assignment difficulty", "with its league-relative index"),
        ("Self-scout", "the shot-tendency self-scout"),
        ("Force them off their hand", "the hand gaps"),
        ("Space dependence", "and the space cliffs")):
    ok(probe in _scout, label)
ok("RECORD of these games, not a trait" in _scout,
   "the matchup grid refuses to read an opponent-chosen assignment as a trait")


# ── Monday names the problem and refuses to prescribe the drill ─────────────
print("\nMonday is a priority list, not a practice plan")
_mon = BODIES["Monday"]
import helpers.dashboard.insights_tab as IT           # noqa: E402
_itsrc = open(IT.__file__, encoding="utf-8").read()
ok("Monday —" in _mon, "Monday renders")
ok("rehearsable" in _mon, "and says what put a row on it")

# THE COLUMN THAT WAS EMPTY. Monday's whole promise is "what it is costing",
# and it shipped with a column of em dashes because none of the rehearsable
# metrics had a derivation. Five now do.
ok(re.search(r"≈ [+-]?\d+\.\d+ pts/g", _mon),
   "at least one Monday row carries a real points conversion")
ok(re.search(r"\*\*\d+ of \d+\*\* carry a points conversion", _mon)
   or "None of these carry a points conversion" in _mon,
   "and Monday states HOW MANY of its rows are priced rather than leaving the "
   "reader to count em dashes")
ok("that is the size of the practice list" in _mon
   or "None of these carry" in _mon,
   "with the total at stake, framed as the size of the list and not as a "
   "projection of what fixing it returns")
ok("DOES NOT PRESCRIBE THE DRILL" in _itsrc,
   "the refusal to author a metric->drill mapping is written down where the "
   "next person will read it")
for _drill in ("box-out drill", "shell drill", "run this drill"):
    ok(_drill.lower() not in _mon.lower(),
       f"Monday does not prescribe '{_drill}'")


# ── the controls ─────────────────────────────────────────────────────────────
print("\nthe view has controls for the first time, and they scope everything")
_sel = [s.label for s in AT.selectbox]
_ms = [m.label for m in AT.multiselect]
ok("Players" in _ms, "the player filter exists")
ok("Game window" in _sel, "the game-window control exists")
ok("Opponent" in _sel, "the opponent-strength control exists")
import helpers.dashboard.insights_deck as DECK        # noqa: E402
_dsrc = open(DECK.__file__, encoding="utf-8").read()
ok("cache-key" in _dsrc.lower(),
   "the controls are documented as cache-key inputs, not post-filters")
ok("_opp_halves" in _dsrc and "st.cache_data" in _dsrc,
   "the opponent split is computed once and cached, not per render")


# ── lazy, and a real fragment ────────────────────────────────────────────────
print("\nthe sections are lazy and render() is finally a fragment")
ok("@st.fragment\ndef render(ctx):" in _itsrc,
   "render carries the @st.fragment its docstring has always claimed")
_rbody = _itsrc[_itsrc.index("@st.fragment\ndef render(ctx):"):]
# Comment lines are exempt: the fix's own comment names `st.tabs` to explain
# why it was wrong, and that explanation is worth more than a grep that cannot
# tell code from prose (same convention as tracker/test_view_jumps.py).
_rcode = [ln for ln in _rbody.splitlines() if not ln.lstrip().startswith("#")]
ok(not any("st.tabs" in ln for ln in _rcode),
   "the sections are a _seg switcher, not st.tabs — st.tabs runs EVERY body")
ok('_UI.seg("Section"' in _rbody, "and the switcher is the app's own _seg")

# the same conversion, one level down, on the jump targets
_page = open(os.path.join(_APP, "pages", "6_Team_Dashboard.py"),
             encoding="utf-8").read()
ok("_sub_seg" in _page, "Charts and Lab inner tabs are _seg too")
for _obj in ("with ch_sc:", "with ch_sh:", "with ch_df:", "with ch_rb:",
             "with ch_tr:", "with ch_adv:", "with ch_bld:", "with adv_eff:"):
    ok(_obj not in _page,
       f"'{_obj}' is gone — st.tabs no longer runs it eagerly")


# ── caps are gone, and the ranking did not sneak one back in ────────────────
print("\nno section is silently truncated")
import helpers.dashboard.insights_deep as ID          # noqa: E402
import helpers.insights_severity as SEV               # noqa: E402
_src = _itsrc + open(ID.__file__, encoding="utf-8").read()
for pat, label in ((r"hb\[:8\]", "force-hand board"),
                   (r"cb\[:10\]", "space-dependence board"),
                   (r"views\[:3\]", "evidence jumps"),
                   (r"rows\[:3\]", "self-scout drift"),
                   (r"key=lambda r: -\(r\.get\(\"REB\"\) or 0\)\)\[:2\]",
                    "rebounding verdicts")):
    ok(not re.search(pat, _src), f"{label} no longer caps its output")

_sevsrc = open(SEV.__file__, encoding="utf-8").read()
ok("EVERY line handed in comes back out" in _sevsrc,
   "the severity module states the rank-never-hide law in its own source")
_probe = SEV.rank(SEV.collect(team_lines=[
    {"metric": f"M{i}", "text": "t", "n": 3, "z": 0.1} for i in range(40)]), {})
ok(len(_probe) == 40,
   "rank() returns all 40 of 40 findings — no confidence floor, no top-N")
ok("never the membership" in _itsrc,
   "and the section renderer says on screen that it is not capping")


# ── the register: coach-to-coach, not explainer ──────────────────────────────
# The INVERSE of what it was on 2026-07-25. The first version of the brief
# glossed every term inline for a reader who had never seen a basketball game,
# and it read as condescending to the only audience that will ever open the
# page. A coach does not need ORB or TOV explained.
print("\nthe register is coach-to-coach, not explainer")
import ast                                           # noqa: E402
import helpers.dashboard.insights_brief as IB        # noqa: E402
_bsrc = open(IB.__file__, encoding="utf-8").read()
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

for banned, label in (
        ("never watched", "no 'never watched a game' framing"),
        ("quick orientation", "no orientation paragraph"),
        ("A team wins by scoring", "does not explain the object of the game"),
        ("losing the ball", "does not gloss 'turnover'"),
        ("trip down the floor", "does not gloss 'possession'"),
        ("is two players working together",
         "does not define a pick-and-roll")):
    ok(banned.lower() not in _lits.lower(), label)

_short = sorted(set(re.findall(r"\b(ORB|TOV|FGA|PPS|FT|FTs)\b", _lits)))
ok(len(_short) >= 3,
   f"standard shorthand is used without apology ({_short})")
ok("r=" in _lits, "reliability rides as an r= chip rather than as hedging")


# ── the dense block grid still does the layout ──────────────────────────────
print("\nthe dense block grid is doing the layout")
_help_body = BODIES["Who's helping"]
ok(_help_body.count("ins-block") >= 12,
   f"blocks are the layout unit ({_help_body.count('ins-block')} rendered)")
ok("ins-hd" in _ALL, "blocks carry their short uppercase heading")
ok("ins-row" in _ALL or "ins-line" in _ALL,
   "blocks carry tight rows / one-line findings")
ok(hasattr(IB, "block") and hasattr(IB, "grid"),
   "the block/grid helpers are exported for other sections to reuse")
_g = IB.grid.__doc__ or ""
ok("COLUMN-WISE" in _g or "round-robin" in _g,
   "the grid distributes round-robin so one tall block does not leave a "
   "ragged hole beside it")


# ── the ranking shows its own work ──────────────────────────────────────────
print("\nthe ranking shows its own work, on Receipts")
_rec = BODIES["Receipts"]
ok("points-per-game conversion" in _rec,
   "the audit table is on Receipts, where a coach goes to check the work")

# THE FLOOR IS NOT A MEASUREMENT. Unmeasured metrics are RANKED at
# UNMEASURED_R, and printing that as "r=0.30" told a coach the app had
# measured every one of them and got 0.30. It had measured none of them.
import helpers.insights_severity as _SEV2             # noqa: E402
_floor = f"r={_SEV2.UNMEASURED_R:.2f}"
for _s in SECTIONS:
    ok(_floor not in BODIES[_s],
       f"'{_s}' never prints the unmeasured floor ({_floor}) as if it were a "
       f"measurement")
# ...and the fix for that is not to stamp every line with the word
# "unmeasured" either. An unmeasured metric gets NO chip; the section states
# the count once, so the chips that survive are the ones carrying information.
ok("unmeasured" not in _ALL.lower().replace("unmeasured floor", ""),
   "no section repeats 'unmeasured' as a per-finding chip")
ok(re.search(r"\*\*\d+ of \d+\*\* sit on metrics the reliability book has "
             r"actually measured", _ALL),
   "a section states once how many of its findings are measured")
_rs = sorted(set(re.findall(r"r=0\.\d\d", BODIES["Who's helping"])))
ok(len(_rs) >= 6,
   f"and the chips that DO render carry real, varied measurements ({_rs})")
ok("deliberately never printed" in _rec,
   "the audit explains why the weight and the measurement are two columns")

# a measurement that lived only as prose in another module now grants
# display permission from the one table that is allowed to
import helpers.reliability as _REL2                   # noqa: E402
ok(_REL2.measured("player", "foul_rate") is not None,
   "player foul rate is IN the reliability book, not just in a comment")
ok("r=0.68" in BODIES["Who's helping"] or "r=0.68" in BODIES["Monday"],
   "and the foul-rate findings render its r instead of reading as unmeasured")
ok("never interleave" in _rec, "and it explains the two bands in words")
ok("no conversion" in _rec or "pts/g" in _rec,
   "the band is a visible column, so 'why is this above that' is answerable")
ok("a tiebreak, not part of the score" in _rec,
   "and it is honest that |z| only breaks ties")

print(f"\nALL {PASSED} CHECKS PASSED")
