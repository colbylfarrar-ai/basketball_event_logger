"""The tagging-coverage panel has to disclose the tags it never counted.

`coverage.py` measures three optional signals — play_type, guarded_by, defense —
and calls itself "the honesty keystone for the whole roadmap". Two more tags are
being pressed in production and neither is measured anywhere:

    turnover_type        53.5% of turnovers, tagged to the final game of the year
    shot_created_by_id   the set-up-by tag, half of the self-creation split

An earlier sweep read the local development copy, found turnover_type switching
off on 2026-01-30, and built an argument about a habit failing mid-season. The
tag was being pressed all along — the local book had simply stopped receiving
those games. The recommendation survived for a different reason: 53.5% is a
PARTIAL sample, and nothing on screen says so, so any live-vs-dead-ball split
built on it reads as complete.

Two things this pins down, and the second matters more than the first:

  * `turnover_type` is counted over TURNOVERS. Every existing signal is a rate
    over shots, and reporting a turnover tag against a shot denominator would be
    a coverage number that cannot reach 100% by construction.
  * `overall_pct` does NOT move. It feeds `player_ratings.confidence_tier`,
    whose 0.35 / 0.60 / 0.80 thresholds were set against the three shot signals.
    Widening the mean would demote every player's trust chip as a side effect of
    a disclosure change, which is a constant change wearing a display change's
    clothes.

Run: python -m pytest tracker/test_coverage_signals.py
"""
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_coverage_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                          # noqa: E402
import database.db as DB                               # noqa: E402
from database.db import execute                        # noqa: E402
import helpers.coverage as COV                         # noqa: E402

DB.initialize_database()


@pytest.fixture(autouse=True)
def _this_modules_db():
    # The collection hazard test_read_filter_empty_scope.py documents: the LAST
    # module to set APP5_DATA_DIR at import time wins for the whole run.
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


def _seed():
    """One tracked game: 4 own shots (2 set-up-tagged) and 4 own turnovers
    (1 typed). Deliberately different denominators, so a turnover tag counted
    over shots would land on a different percentage than the right one."""
    t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('A HS','3A','F')")
    t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('B HS','3A','F')")
    p1 = execute("INSERT INTO players (team_id,name,number,season) "
                 "VALUES (?,?,?,'Current')", (t1, "Ann", 4))
    p2 = execute("INSERT INTO players (team_id,name,number,season) "
                 "VALUES (?,?,?,'Current')", (t1, "Bea", 5))
    gid = execute("INSERT INTO games (team1_id,team2_id,date,tracked,season,"
                  "home_score,away_score) VALUES (?,?,?,1,'Current',50,40)",
                  (t1, t2, "2026-01-10"))
    for i in range(4):
        execute("INSERT INTO game_events (game_id, event_type, quarter, time, "
                "primary_player_id, shot_result, shot_type, shot_created_by_id) "
                "VALUES (?, 'shot', 1, '7:00', ?, 'make', 2, ?)",
                (gid, p1, p2 if i < 2 else None))
    for i in range(4):
        execute("INSERT INTO game_events (game_id, event_type, quarter, time, "
                "primary_player_id, turnover_type) "
                "VALUES (?, 'turnover', 1, '6:00', ?, ?)",
                (gid, p1, "pass" if i < 1 else None))
    return t1, gid


_T1, _GID = _seed()


def test_turnover_type_is_reported_against_a_turnover_denominator():
    """One of four turnovers is typed. Counted over shots it would read 25% of
    the wrong thing, or 12.5% of the two pooled."""
    s = COV.team_coverage(_T1)["signals"]["turnover_type"]
    assert (s["tagged"], s["total"], s["pct"]) == (1, 4, 25.0), s


def test_the_set_up_by_tag_is_reported_over_own_shots():
    """`shot_created_by_id` is half the self-creation split and was measured
    nowhere. Two of four own shots carry it."""
    s = COV.team_coverage(_T1)["signals"]["shot_created_by_id"]
    assert (s["tagged"], s["total"], s["pct"]) == (2, 4, 50.0), s


def test_the_new_signals_carry_a_label_like_every_other_one():
    """A caller reads `label` without knowing which signal it holds."""
    sig = COV.team_coverage(_T1)["signals"]
    for k in ("turnover_type", "shot_created_by_id"):
        assert sig[k]["label"] in ("none", "sparse", "partial", "strong")


def test_overall_pct_still_means_what_confidence_tier_was_calibrated_against():
    """The disclosure must not move a wired-in constant.

    Everything seeded here is untagged for play_type, guarded_by and defense, so
    the three-signal mean is 0.0. If the new signals joined it, the two tagged
    shots and one typed turnover would push it up and every player's trust chip
    would shift — a threshold change nobody measured, delivered by a caption."""
    cov = COV.team_coverage(_T1)
    assert cov["overall_pct"] == 0.0, cov["overall_pct"]
    assert set(COV.OVERALL_SIGNALS) == {"play_type", "guarded_by", "defense"}


def test_gender_coverage_reports_the_same_five_signals():
    """The league panel and the team panel must not disclose different things."""
    assert set(COV.gender_coverage("F")["signals"]) \
        == set(COV.team_coverage(_T1)["signals"])
