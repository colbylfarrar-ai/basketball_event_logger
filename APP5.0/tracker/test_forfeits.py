"""A forfeit counts in the record and nowhere else.

THE BOOK §8.1, the biggest correctness item in the sweep, ruled by Q2: *"a zero
on one side is a forfeit. Counts in W-L. Out of strength of schedule"* — and by
the same logic out of PPG, points allowed, MOV, Pythagorean, Luck and the Power
rating, all of which are margin math.

The bug this closes, on the production book with the default filters:

    F  Best defense (PA/G)   0.00   Mercy Institute Girls      1-0
    M  Best defense (PA/G)   1.00   Unity Academy Boys         0-3
    M  Point margin        +67.00   South Western Hieghts      1-0

A team that lost all three of its games was the boys' best defence.

The fixture is deliberately built so that EVERY assertion below fails without
the fix and passes with it — a real team with real games plus one walkover,
where the walkover is the extreme value on every margin axis. Fixture games get
distinct dates because `game_dedup` collapses same-date same-matchup rows and
seeding them on one day would test the deduper instead.

Run: python -m pytest tracker/test_forfeits.py
"""
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_forfeit_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                          # noqa: E402
import database.db as DB                               # noqa: E402
from database.db import execute                        # noqa: E402
import helpers.forfeits as FF                          # noqa: E402
import helpers.team_ratings as TR                      # noqa: E402
import helpers.league_analytics as LA                  # noqa: E402

DB.initialize_database()

SEASON = "2025-2026"


@pytest.fixture(autouse=True)
def _this_modules_db():
    """The collection hazard test_read_filter_empty_scope.py documents: the
    LAST module to set APP5_DATA_DIR at import wins at run time, so re-pin it
    per test rather than trusting the import-time assignment."""
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    yield
    if prev is not None:
        os.environ["APP5_DATA_DIR"] = prev


def _seed():
    """Two teams that played three real games, plus a walkover each way.

    REAL:  #1 beats #2   60-50, 55-52, 48-58    -> #1 is 2-1, MOV +1.0
    FF:    #1 beats #3    2-0                   -> a 1-0 team's PA is 0.00
           #4 loses to #2 0-2                   -> the 0-3 "best defence" shape
    """
    execute("DELETE FROM games")
    execute("DELETE FROM teams")
    for tid, name in ((1, "Real One Girls"), (2, "Real Two Girls"),
                      (3, "Walkover Girls"), (4, "Shutout Girls")):
        execute("INSERT INTO teams (id, name, class, gender, state) "
                "VALUES (?,?,?,?,?)", (tid, name, "4A", "F", "OK"))
    rows = [
        # distinct dates — game_dedup collapses same-date same-matchup rows
        (101, 1, 2, "2025-12-01", 60, 50),
        (102, 1, 2, "2025-12-08", 55, 52),
        (103, 1, 2, "2025-12-15", 48, 58),
        (104, 1, 3, "2025-12-22", 2, 0),      # walkover, #1 wins
        (105, 2, 4, "2025-12-29", 2, 0),      # walkover, #4 loses
    ]
    for gid, t1, t2, date, hs, aser in rows:
        execute("INSERT INTO games (id, team1_id, team2_id, date, home_score, "
                "away_score, tracked, season) VALUES (?,?,?,?,?,?,0,?)",
                (gid, t1, t2, date, hs, aser, SEASON))


# ── the detector ─────────────────────────────────────────────────────────────

def test_the_signature_is_1_0_and_2_0_and_nothing_else():
    assert FF.is_forfeit(1, 0) and FF.is_forfeit(0, 1)
    assert FF.is_forfeit(2, 0) and FF.is_forfeit(0, 2)
    # basketball has no genuine 1- or 2-point games, which is what makes the
    # signature safe; a 3-0 is not a scoreline this sport produces either, but
    # it is not the convention and is left alone deliberately
    assert not FF.is_forfeit(3, 0)
    assert not FF.is_forfeit(0, 0)
    assert not FF.is_forfeit(60, 50)


def test_a_rout_with_a_zero_side_is_not_reclassified():
    """The six production games this protects: 69-0, 65-0, 51-0, 15-0, 0-15 x2.

    Ruled reported, not classified. Deleting a legitimate blowout from the
    ratings is the more expensive of the two mistakes available here.
    """
    for hi in (15, 51, 65, 69):
        assert not FF.is_forfeit(hi, 0), f"{hi}-0 is a rout, not a walkover"
        assert FF.suspect_zero(hi, 0), f"{hi}-0 should still be reportable"
    assert not FF.suspect_zero(2, 0), "the signature is classified, not suspect"
    assert not FF.suspect_zero(60, 50)


def test_an_unscored_game_is_not_a_forfeit():
    assert not FF.is_forfeit(None, None)
    assert not FF.is_forfeit(2, None)


def test_the_label_keeps_the_result_and_marks_it():
    assert FF.label(True, True) == "W (ff)"
    assert FF.label(False, True) == "L (ff)"
    assert FF.label(True, False) == "W"


# ── the engines ──────────────────────────────────────────────────────────────

def test_the_record_still_counts_the_walkover():
    _seed()
    r = TR.score_ratings(gender="F", season=SEASON)
    assert r[1]["W"] == 3 and r[1]["L"] == 1, \
        "a forfeit win is a win — Q2 says it counts in W-L"
    assert r[1]["GP"] == 4, "and it counts in games played"
    assert r[1]["GP_margin"] == 3, "…but not in the games the margins came from"
    assert r[1]["forfeit_w"] == 1 and r[1]["forfeit_l"] == 0, \
        "the row says how many of its wins were walkovers"


def test_the_walkover_is_out_of_every_margin_number():
    _seed()
    r = TR.score_ratings(gender="F", season=SEASON)
    # #1's three PLAYED games: 60-50, 55-52, 48-58 -> PF 163, PA 160 over 3
    assert round(r[1]["PPG"], 1) == round(163 / 3, 1), \
        "the 2-point walkover is dragging PPG down"
    assert round(r[1]["oPPG"], 1) == round(160 / 3, 1), \
        "the 0 allowed in the walkover is dragging points-allowed down"
    assert round(r[1]["MOV"], 1) == 1.0


def test_a_team_whose_only_game_was_a_walkover_is_not_rated_at_all():
    """The Mercy Institute shape: 1-0, PA/G 0.00, best defence in the state.

    It leaves `score_ratings` rather than staying with None fields. The
    function's contract is results-only power ratings and a team with no played
    games has no results to rate; keeping the row with Nones would have moved
    the same failure into the 119 call sites that format these keys.
    """
    _seed()
    r = TR.score_ratings(gender="F", season=SEASON)
    for tid in (3, 4):
        assert tid not in r, \
            "a walkover-only team is still carrying a power rating"
    assert set(r) == {1, 2}

    # every surviving row is fully numeric — no None leaks downstream
    for row in r.values():
        for k in ("PPG", "oPPG", "MOV", "Rating", "Power", "SOS", "SOR",
                  "Rank"):
            assert isinstance(row[k], (int, float)), f"{k} went None"

    # and it cannot win the leaderboard it used to win
    best_def = min(r, key=lambda t: r[t]["oPPG"])
    assert best_def in (1, 2), "a forfeit is still the league's best defence"
    assert r[best_def]["oPPG"] > 0, "…and it is still 0.00 points allowed"


def test_the_record_of_an_unrated_team_is_still_readable():
    """Losing the RATING must not lose the RESULT — the W-L lives in the two
    engines that own records, and both mark the walkover."""
    _seed()
    fm = LA.team_form_stats(gender="F", season=SEASON)
    assert fm[3]["W"] == 0 and fm[3]["L"] == 1
    assert fm[3]["forfeit_l"] == 1
    assert fm[3]["margin_games"] == 0
    assert fm[3]["MOV"] is None and fm[3]["PF_pg"] is None, \
        "a team with no played games publishes no scoring rate"

    import helpers.team_analytics as TA
    log = TA.team_game_log(3, season=SEASON)
    assert len(log) == 1 and log[0]["ff"] is True, \
        "the game log dropped the walkover, or stopped marking it"


def test_form_stats_keep_the_record_and_drop_the_margin():
    _seed()
    fm = LA.team_form_stats(gender="F", season=SEASON)
    a = fm[1]
    assert a["W"] == 3 and a["L"] == 1, "W-L counts every game"
    assert a["games"] == 4
    assert a["margin_games"] == 3, "…and the margin math sees three"
    assert a["PF"] == 163 and a["PA"] == 160, \
        "PF/PA still carry the walkover's 2-0"
    assert round(a["MOV"], 2) == round(3 / 3, 2)
    # Pythagorean is built from PF/PA, so it moves too
    assert 0.0 < a["Pyth_wpct"] < 1.0
    assert a["forfeit_w"] == 1 and a["forfeit_l"] == 0


def test_a_walkover_is_not_a_blowout_and_not_a_close_game():
    """A 2-0 has a margin of 2, so an unfiltered engine files it as a
    one-possession thriller — which is how a forfeit ends up in a clutch
    composite."""
    _seed()
    fm = LA.team_form_stats(gender="F", season=SEASON)
    a = fm[1]
    # #1's real games are 60-50 (+10), 55-52 (+3) and 48-58 (-10). Exactly one
    # of them is close and one-possession. Before the split the 2-0 walkover
    # joined it in both buckets and doubled the clutch sample.
    assert a["one_w"] + a["one_l"] == 1, \
        "the 2-0 walkover is being counted as a one-possession game"
    assert a["close_w"] + a["close_l"] == 1, \
        "…and as a close game, which feeds the Clutch composite"
    assert a["one_w"] == 1 and a["close_w"] == 1


def test_forfeits_are_out_of_strength_of_schedule():
    """Q2 names SOS explicitly. #1 played #3 only in a walkover, so #3 must
    not appear in #1's schedule strength at all."""
    _seed()
    r = TR.score_ratings(gender="F", season=SEASON)
    games = TR._finished_games(gender="F", season=SEASON)
    tg = TR._per_team_games(games)
    opps = {e["opp"] for e in tg[1] if not e["ff"]}
    assert opps == {2}, "the walkover opponent is still in the schedule math"
    assert all("ff" in e for e in tg[1]), \
        "_per_team_games no longer marks which rows are walkovers"
