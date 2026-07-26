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
# THE FIXTURE IS INTERNALLY COHERENT ON PURPOSE. Every z below points the same
# way as the raw numbers underneath it, because the sign-coherence check near
# the foot of this file is only meaningful over inputs that do not contradict
# themselves — an arbitrary z beside an unrelated stat line would fail that
# check for the fixture's reasons rather than the code's.
PLAYER_FEED = {
    # player 1: a big space cliff (bad), real on-floor impact, an untagged Q4
    1: [{"metric": "GuardCliff", "text": "space cliff", "n": 40, "z": 1.9},
        {"metric": "Impact", "text": "on-floor", "n": 300, "z": 1.4},
        {"metric": "Q4", "text": "fourth quarter", "n": 30, "z": 0.9},
        {"metric": "Selection", "text": "hard diet", "n": 200, "z": 1.6},
        {"metric": "TO type", "text": "bad passes", "n": 15, "z": 1.3,
         "share": 0.5}],
    # player 2: weak hand, cold at the line late, weak offensive glass
    2: [{"metric": "HandGap", "text": "weak hand", "n": 22, "z": 2.2},
        {"metric": "Clutch FT", "text": "foul her late", "n": 12, "z": -1.5},
        {"metric": "Rebounding", "text": "no glass threat", "n": 24,
         "z": -1.2, "side": "off"},
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

#: the league player pool the per-player conversions price against
PLAYER_POOL = {
    1: {"FGA": 200, "GP": 11, "TOV": 33, "xPPS": 0.86, "OREB/G": 1.0,
        "ClutchFT%": 70.0, "FT%": 72.0, "ClutchFTA": 8,
        "Dom_FG%": 44.0, "Weak_FG%": 30.0, "Weak_FGA": 33},
    2: {"FGA": 150, "GP": 11, "TOV": 20, "xPPS": 0.94, "OREB/G": 0.6,
        "ClutchFT%": 50.0, "FT%": 74.0, "ClutchFTA": 12,
        "Dom_FG%": 48.0, "Weak_FG%": 26.0, "Weak_FGA": 44},
    3: {"FGA": 180, "GP": 11, "TOV": 25, "xPPS": 1.02, "OREB/G": 1.8,
        "ClutchFT%": 80.0, "FT%": 76.0, "ClutchFTA": 10,
        "Dom_FG%": 46.0, "Weak_FG%": 40.0, "Weak_FGA": 30},
    # under POOL_MIN_FGA — must NOT drag the league means around
    4: {"FGA": 6, "GP": 3, "TOV": 2, "xPPS": 0.40, "OREB/G": 0.1},
}

CTX = {
    "gp": 11,
    "deserved": {"ranked_terms": [("volume", "Extra shots", 8.8, 3.1)],
                 "means": {"volume": 3.1}},
    "cliffs": {1: {"cliff": 12.0, "n": 40, "gn": 22}},
    "wpa": {1: {"off_wpa": 0.8, "def_wpa": 0.4, "games": 11}},
    "wins_per_point": 0.031,
    "player_pool": PLAYER_POOL,
    # this team gives it away MORE than the field, which is what its z says
    "ts": {"TOVpct": 22.0, "PPP": 0.88, "poss_pg": 60.0, "ORBpct": 26.0,
           "fga_pg": 49.0, "stl_r": 9.0},
    "ts_all": {
        1: {"TOVpct": 18.0, "PPP": 0.92, "poss_pg": 61.0, "ORBpct": 30.0,
            "fga_pg": 50.0, "stl_r": 7.0},
        2: {"TOVpct": 22.0, "PPP": 0.88, "poss_pg": 60.0, "ORBpct": 26.0,
            "fga_pg": 49.0, "stl_r": 8.0},
        3: {"TOVpct": 20.0, "PPP": 0.90, "poss_pg": 62.0, "ORBpct": 28.0,
            "fga_pg": 51.0, "stl_r": 6.0}},
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
# the sign of a rate conversion is the single easiest thing to get backwards,
# so both directions are asserted rather than one
_bs = next(f for f in RANKED if f["metric"] == "Ball security")
ok(_bs["pts"] < 0,
   f"a team ABOVE the league turnover rate is penalised ({_bs['pts']:+.2f})")
_good_ctx = dict(CTX)
_good_ctx["ts"] = dict(CTX["ts"], TOVpct=18.0)
ok(SEV.materiality({"metric": "Ball security", "family": "team"},
                   _good_ctx) > 0,
   "and a team BELOW it is credited -- same rule, mirrored input")

_ft = next(f for f in RANKED if f["metric"] == "Clutch FT")
_want_ft = ((50.0 - 74.0) / 100.0) * (12 / 11)
ok(abs(_ft["pts"] - _want_ft) < 1e-9,
   f"clutch FT is priced at one point per free throw, no model at all: "
   f"{_ft['pts']:.3f} == {_want_ft:.3f}")

_reb = next(f for f in RANKED if f["metric"] == "Rebounding")
ok(_reb["pts"] is not None and _reb["pts"] < 0,
   "a below-league OFFENSIVE rebounder is priced as the possessions she does "
   "not create")
ok(SEV.materiality({"metric": "Rebounding", "family": "player", "pid": 2,
                    "side": "def"}, CTX) is None,
   "and the DEFENSIVE half of the same read gets NO tag -- a defensive board "
   "is the expected end of the opponent's trip, not an extra possession")

_pool_x = SEV._pool_mean(CTX, "xPPS")
ok(_pool_x is not None and abs(_pool_x - (0.86 + 0.94 + 1.02) / 3) < 1e-9,
   f"league means skip players under POOL_MIN_FGA ({SEV.POOL_MIN_FGA} FGA) -- "
   f"a pool that includes six-shot players is a different league from the one "
   f"the generator z-scored against")


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
_luck = next(f for f in RANKED if f["metric"] == "Luck")
ok(_luck["r"] == SEV.UNMEASURED_R,
   f"an unmeasured metric is RANKED at the book's floor ({SEV.UNMEASURED_R}) "
   f"-- shown, ranked last, never flattered with a neutral 1.0")
ok(SEV.reliability_of("PnR role") >= 0.0,
   "a NEGATIVE measured reliability clamps to 0 rather than flipping the "
   "severity score's sign")
ok(all(f["r"] >= 0 for f in RANKED), "no finding carries a negative weight")

# THE FLOOR IS NOT A MEASUREMENT, AND MUST NOT BE PRINTED AS ONE. A page full
# of identical "r=0.30" chips tells a coach the app measured every one of those
# metrics and got 0.30. It has measured none of them.
ok(_luck["r_measured"] is None,
   "an unmeasured metric carries r_measured = None, distinct from its weight")
ok(SEV.r_chip(_luck) == "unmeasured",
   f"and renders as 'unmeasured', never as the floor "
   f"({SEV.r_chip(_luck)!r})")
ok(str(SEV.UNMEASURED_R) not in SEV.r_chip(_luck),
   "the floor value does not appear in the chip at all")
ok(SEV.r_chip(_cliff) == f"r={REL.measured('player', 'band_fg'):.2f}",
   f"a measured metric prints its real r ({SEV.r_chip(_cliff)})")
ok(SEV.measured_r("Luck") is None and SEV.measured_r("GuardCliff") is not None,
   "measured_r answers 'did the book measure this', reliability_of answers "
   "'what weight does it rank with' -- two questions, two functions")


print("\n-- the number agrees with the sentence --------------------------------")

# THE INVARIANT THAT CAUGHT A REAL BUG. `insights._g_selection` scored shot
# selection on `ShotRating`, which is DIFFICULTY ("higher = the player takes
# harder shots", stats.shot_rating), and wrote the sentence as though it were
# quality -- so the roster's best shot-selector was told she "settles for tough
# shots". Nothing caught it, because the sentence was the only description of
# the finding. Pricing the same read off a SECOND, independent quantity (xPPS,
# which correlates -0.72 with ShotRating on the live book) made the two
# disagree out loud.
ok(SEV.METRIC_Z_ORIENT.get("Selection") == -1,
   "Selection's authored orientation matches what ShotRating measures: a high "
   "z is a HARDER diet, which is the bad direction")

_incoherent = []
for f in RANKED:
    if f.get("pts") is None:
        continue
    _o, _z = SEV.METRIC_Z_ORIENT.get(f["metric"]), f.get("z")
    if _o is None or _z is None:
        continue
    _sentence = 1 if _o * _z > 0 else -1
    _number = 1 if f["pts"] > 0 else -1
    if _sentence != _number:
        _incoherent.append((f["metric"], f["subject"], _z, f["pts"]))
ok(not _incoherent,
   f"every priced finding's SIGN agrees with its own sentence's direction "
   f"(disagreements: {_incoherent})")

# and the generator itself, driven directly
import helpers.insights as _IN                             # noqa: E402
_pool = (50.0, 8.0)          # mean, sd of ShotRating across the field
_hard = _IN._g_selection(
    {"ShotRating": 70.0, "GP": 20, "FGA": 200, "name": "X"},
    {"ShotRating": _pool}, {})
_easy = _IN._g_selection(
    {"ShotRating": 32.0, "GP": 20, "FGA": 200, "name": "X"},
    {"ShotRating": _pool}, {})
ok("tough shots" in (_hard or {}).get("text", ""),
   "a HIGH shot-difficulty diet reads as settling for tough shots")
ok("Great shot selection" in (_easy or {}).get("text", ""),
   "and a LOW one reads as good selection -- this pair was inverted until "
   "2026-07-26")
ok("shot difficulty" in (_hard or {}).get("text", "").lower(),
   "the quoted number is named 'shot difficulty', matching every other "
   "surface in the app, instead of 'shot-quality'")


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
