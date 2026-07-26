"""The severity ranking — the one ordering the redesigned Insights page trusts.

WHY THIS FILE EXISTS. Insights mines findings from three engine families that
never shared a scale: the player miner sorts by |z|, the team miner sorts by a
field several of its own generators never produce (`_t_chemistry` hardcodes
1.4, `_t_deserved` adds +0.5 to jump the queue), and the 13 ported engines are
not scored at all. `helpers/insights_severity.py` is the fourth, additional
ordering that lets a finding honestly float to the top of the page.

Four properties are load-bearing and none of them is visible in a render:

  1. RANK, NEVER HIDE. Every finding handed in comes back out. This is the
     page's oldest rule — every cap on the view was deliberately removed — and
     the severity engine is the newest place it could quietly be reintroduced.
  2. THE TWO BANDS NEVER INTERLEAVE. A finding with a points conversion always
     sorts above one without. A blended score with a neutral stand-in for
     missing materiality would let an untagged read outrank a genuinely small
     tagged one, which is the app inventing a number it does not have.
  3. pts/g IS ABSENT, NOT ZERO, when no derivation exists. Zero is a claim.
  4. `rehearsable` DEFAULTS TO FALSE, so a metric added tomorrow cannot appear
     on a coach's Monday practice list without someone deciding it should.

Streamlit-free — runs anywhere, no DB, no render.

    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe \\
        tracker/test_insights_severity.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, f"FAIL: {label}"
    PASSED += 1
    print("  ok  " + str(label).encode("ascii", "replace").decode("ascii"))


import helpers.insights_severity as SEV        # noqa: E402
import helpers.reliability as REL              # noqa: E402


# ── a book with all three families in it ─────────────────────────────────────
PLAYER_FEED = {
    1: [{"metric": "GuardCliff", "text": "space cliff", "n": 40, "z": -1.9},
        {"metric": "Impact", "text": "on-floor", "n": 300, "z": 1.4},
        {"metric": "Q4", "text": "fourth quarter", "n": 30, "z": 0.9}],
    2: [{"metric": "HandGap", "text": "weak hand", "n": 22, "z": -2.2},
        {"metric": "Usage", "text": "usage", "n": 120, "z": 1.1}],
}
NAMES = {1: "A. Player", 2: "B. Player"}
TEAM_LINES = [
    {"metric": "Margin mix", "text": "margin", "n": 11, "z": 2.2},
    {"metric": "Ball security", "text": "giveaways", "n": 11, "z": 1.8},
    {"metric": "Luck", "text": "close-game luck", "n": 11, "z": 1.1},
    {"metric": "Chemistry", "text": "a pair", "n": 90, "z": 1.4},
]
PORTED = {"stops": [("Kills", 40, "kill strings")],
          "reb": [("Box-out payoff", 55, "second chances")]}
PORT_SECTIONS = {"stops": ("Stops", "Defense"), "reb": ("Rebounding", "Roster")}

CTX = {
    "gp": 11,
    "deserved": {"ranked_terms": [("volume", "Extra shots", 8.8, 3.1)],
                 "means": {"volume": 3.1}},
    "cliffs": {1: {"cliff": 12.0, "n": 40, "gn": 22}},
    "wpa": {1: {"off_wpa": 0.8, "def_wpa": 0.4, "games": 11}},
    "wins_per_point": 0.031,
    "ts": {"TOVpct": 18.0, "PPP": 0.92, "poss_pg": 61.0, "ORBpct": 30.0,
           "fga_pg": 50.0, "stl_r": 9.0},
    "ts_all": {
        1: {"TOVpct": 18.0, "PPP": 0.92, "poss_pg": 61.0, "ORBpct": 30.0,
            "fga_pg": 50.0, "stl_r": 9.0},
        2: {"TOVpct": 22.0, "PPP": 0.88, "poss_pg": 60.0, "ORBpct": 26.0,
            "fga_pg": 49.0, "stl_r": 7.0},
        3: {"TOVpct": 20.0, "PPP": 0.90, "poss_pg": 62.0, "ORBpct": 28.0,
            "fga_pg": 51.0, "stl_r": 8.0}},
}

FINDINGS = SEV.collect(player_feed=PLAYER_FEED, names=NAMES,
                       team_lines=TEAM_LINES, ported=PORTED,
                       ported_sections=PORT_SECTIONS)
RANKED = SEV.rank(FINDINGS, CTX)


print("-- the law: rank, never hide -----------------------------------------")

_n_in = (sum(len(v) for v in PLAYER_FEED.values()) + len(TEAM_LINES)
         + sum(len(v) for v in PORTED.values()))
ok(len(FINDINGS) == _n_in,
   f"collect() returns every line it was handed ({len(FINDINGS)} of {_n_in})")
ok(len(RANKED) == len(FINDINGS),
   f"rank() returns every finding it was given ({len(RANKED)}) -- severity is "
   f"a SORT, never a filter")
ok({f["key"] for f in RANKED} == {f["key"] for f in FINDINGS},
   "and it is the same set, not a same-sized different one")

# the untagged, unmeasured, tiny-sample finding is still in the list
ok(any(f["metric"] == "Luck" for f in RANKED),
   "an unmeasured metric with no points conversion still renders -- it ranks "
   "last, it is never dropped")


print("\n-- the two bands never interleave ------------------------------------")

_bands = [f["band"] for f in RANKED]
ok(_bands == sorted(_bands), f"band order is monotonic ({_bands})")
_tagged = [f for f in RANKED if f["band"] == SEV.BAND_TAGGED]
_untagged = [f for f in RANKED if f["band"] == SEV.BAND_UNTAGGED]
ok(_tagged and _untagged, "the fixture exercises both bands")
_last_tagged = max(RANKED.index(f) for f in _tagged)
_first_untagged = min(RANKED.index(f) for f in _untagged)
ok(_last_tagged < _first_untagged,
   "every tagged finding sorts above every untagged one")
ok(all(f["pts"] is not None for f in _tagged)
   and all(f["pts"] is None for f in _untagged),
   "band membership is exactly 'has a points conversion'")

# the specific failure the two bands exist to prevent
_smallest_tagged = min(abs(f["pts"]) for f in _tagged)
ok(_smallest_tagged < 1.0,
   f"the fixture contains a genuinely small tagged finding "
   f"({_smallest_tagged:.2f} pts/g) -- the case a blended score would let an "
   f"untagged read outrank")


print("\n-- pts/g is absent, never zero ---------------------------------------")

ok(all(f["pts"] is None or f["pts"] != 0 for f in RANKED),
   "no finding carries a zero conversion -- zero is a claim, absence is not")
ok(SEV.pts_chip(None) == "—",
   "the chip renders an em dash rather than '0.0 pts/g' when untagged")
_q4 = next(f for f in RANKED if f["metric"] == "Q4")
ok(_q4["pts"] is None and _q4["band"] == SEV.BAND_UNTAGGED,
   "a metric with no authored derivation is untagged rather than guessed at")

# and the derivations that DO ship produce the number they claim to
_cliff = next(f for f in RANKED if f["metric"] == "GuardCliff")
_want = -(12.0 / 100.0) * (22 / 11) * 2.0
ok(abs(_cliff["pts"] - _want) < 1e-9,
   f"the guarded-cliff derivation is (cliff x contested/g x 2): "
   f"{_cliff['pts']:.3f} == {_want:.3f}")
_mix = next(f for f in RANKED if f["metric"] == "Margin mix")
ok(abs(_mix["pts"] - 3.1) < 1e-9,
   "the deserved terms are already points per game and are passed through")
_bs = next(f for f in RANKED if f["metric"] == "Ball security")
ok(_bs["pts"] > 0,
   "a team BELOW the league turnover rate is credited, not penalised -- the "
   "sign of a rate conversion is the thing easiest to get backwards")


print("\n-- the ordering is total and stable ----------------------------------")

ok([f["key"] for f in SEV.rank(list(reversed(FINDINGS)), CTX)]
   == [f["key"] for f in RANKED],
   "the same findings in a different input order rank identically -- the "
   "tiebreak makes the sort total, not just deterministic-by-accident")
_sev = [f["severity"] for f in RANKED if f["band"] == SEV.BAND_TAGGED]
ok(_sev == sorted(_sev, reverse=True),
   "within band 1 the order is descending severity")


print("\n-- Monday is opt-in, and it is a grouping not a filter ---------------")

_monday = SEV.monday(RANKED)
ok(all(f["rehearsable"] for f in _monday),
   "every Monday row sits on an authored-rehearsable metric")
ok(all(f["direction"] < 0 for f in _monday),
   "every Monday row points the wrong way")
ok(all(f["metric"] in SEV.REHEARSABLE for f in _monday),
   "and REHEARSABLE is the only source of that flag -- never the text")
ok("Q4" not in SEV.REHEARSABLE and "Luck" not in SEV.REHEARSABLE,
   "rehearsable defaults to False: a metric nobody marked cannot reach Monday")
_unknown = SEV.collect(team_lines=[{"metric": "Brand New Metric",
                                    "text": "x", "n": 5, "z": 3.0}])
ok(_unknown[0]["rehearsable"] is False,
   "a metric the table has never heard of is not rehearsable")
ok(len(SEV.rank(_unknown, CTX)) == 1,
   "...and it still ranks and still renders")
ok(len(_monday) < len(RANKED),
   "Monday is a narrowing, and it is a DISPLAY grouping -- the full ranked "
   "list is untouched")


print("\n-- direction is authored, and never suppresses ------------------------")

ok(all(f["direction"] in (-1, 0, 1) for f in RANKED),
   "direction is a sign, nothing more")
_neutral = [f for f in RANKED if f["direction"] == 0]
ok(_neutral, "a metric with no authored orientation reads NEUTRAL rather than "
             "being guessed at")
ok(all(f in RANKED for f in _neutral),
   "and a neutral direction never removes a finding from the list")


print("\n-- reliability comes from the measured book ---------------------------")

ok(_cliff["r"] == REL.measured("player", "band_fg"),
   "a measured metric takes its own split-half r")
ok(next(f for f in RANKED if f["metric"] == "Luck")["r"] == SEV.UNMEASURED_R,
   f"an unmeasured metric takes the book's floor ({SEV.UNMEASURED_R}) -- shown, "
   f"ranked last, never flattered with a neutral 1.0")
ok(SEV.reliability_of("PnR role") >= 0.0,
   "a NEGATIVE measured reliability clamps to 0 rather than flipping the "
   "severity score's sign")
ok(all(f["r"] >= 0 for f in RANKED), "no finding carries a negative weight")


print("\n-- every metric the miners emit has a home ----------------------------")

import ast                                              # noqa: E402
import re                                               # noqa: E402

_emitted = set()
for _f in ("helpers/insights.py", "helpers/team_insights.py"):
    _src = open(os.path.join(_APP, _f), encoding="utf-8").read()
    _emitted |= set(re.findall(r'"metric":\s*"([^"]+)"', _src))
ok(len(_emitted) >= 50, f"{len(_emitted)} distinct metrics are emitted")
_unmapped = sorted(m for m in _emitted if m not in SEV.METRIC_SECTION)
ok(not _unmapped,
   f"every emitted metric is assigned a section (unmapped: {_unmapped})")
_nojump = sorted(m for m in _emitted if m not in SEV.METRIC_EVIDENCE)
ok(not _nojump,
   f"every emitted metric names where its evidence lives (missing: {_nojump})")


print("\n-- the evidence map addresses real destinations -----------------------")

_page = open(os.path.join(_APP, "pages", "6_Team_Dashboard.py"),
             encoding="utf-8").read()
_views = set(re.findall(r'"(\w[\w ]*)"', _page[_page.index("_TD_VIEWS = ["):
                                               _page.index("# Icons make")]))
for _m, (_v, _sub) in SEV.METRIC_EVIDENCE.items():
    assert _v in _views, f"{_m} points at a view that does not exist: {_v}"
PASSED += 1
print("  ok  every evidence destination names a real top-level view")

# and every sub-step names an option of a real _sub_seg switcher
_subs = set()
for _opts in re.findall(r"_sub_seg\(\s*(\[[^\]]*\])", _page):
    try:
        _subs |= {s for s in ast.literal_eval(_opts.replace("\n", " "))}
    except Exception:
        pass
_bad = []
for _m, (_v, _sub) in SEV.METRIC_EVIDENCE.items():
    for _step in ([] if _sub is None else
                  list(_sub) if isinstance(_sub, (tuple, list)) else [_sub]):
        if _step not in _subs:
            _bad.append((_m, _step))
ok(not _bad,
   f"every sub-step names a real switcher option (bad: {_bad})")

ok(SEV.dest_label("Charts", ("Offense", "Shooting"))
   == "Charts → Offense → Shooting",
   "a two-hop destination renders as a full path, so the button and its help "
   "text cannot describe two different places")


print(f"\nALL {PASSED} CHECKS PASSED")
