"""Tests for the widened signature-stat pool + the de-correlation pass
(helpers/insights_team.py).

Two behaviours under test:

  1. A signature stat can be ANY stat. team_stat_line used to expose 12
     box-score keys only, so the tiles could only ever say box-score things.
     _style_line adds tempo / shot-creation / run keys off the same event pass.

  2. Effect-size ranking alone tells ONE story four ways: PPP, eFG and TS move
     together, so a team that wins by shooting well gets four tiles that all say
     "we shot well". _decorrelate drops a stat already explained by a stronger
     one. Real data may legitimately have four distinct leaders, so the pass is
     tested directly rather than through a live team.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _shot(team, secs, make=False, three=False, gid=1,
          pass_from=None, created_by=None):
    return {"event_type": "shot", "shot_result": "make" if make else "miss",
            "shot_type": 3 if three else 2, "shooter_team_id": team,
            "game_id": gid, "quarter": 1, "time": "7:00",
            "possession_secs": secs, "pass_from_id": pass_from,
            "shot_created_by_id": created_by, "primary_player_id": None}


def test_pearson():
    import helpers.insights_team as IT
    ok(abs(IT._pearson([1, 2, 3, 4], [2, 4, 6, 8]) - 1.0) < 1e-9,
       "perfect positive correlation is r=1")
    ok(abs(IT._pearson([1, 2, 3, 4], [8, 6, 4, 2]) + 1.0) < 1e-9,
       "perfect negative correlation is r=-1")
    ok(IT._pearson([1, 1, 1, 1], [1, 2, 3, 4]) is None,
       "no spread -> r undefined (None), not a crash or a 0")
    ok(IT._pearson([1, 2], [1, 2]) is None, "n<3 -> None")
    ok(IT._pearson([1, 2, 3, None], [1, 2, 3, 9]) is not None,
       "None samples are dropped pairwise, not treated as 0")


def test_decorrelate_drops_the_same_story():
    """A stat that moves in lockstep with a stronger one is dropped."""
    import helpers.insights_team as IT

    # 'a' and 'a_twin' are the same story; 'b' is independent.
    lines = {i: {"a": v, "a_twin": v * 2 + 1, "b": (i % 2)}
             for i, v in enumerate([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])}
    ranked = [{"key": "a", "d": 2.0}, {"key": "a_twin", "d": 1.9},
              {"key": "b", "d": 1.5}]
    kept = [r["key"] for r in IT._decorrelate(ranked, lines, {}, 4)]
    ok("a" in kept, "the strongest of a correlated pair is kept")
    ok("a_twin" not in kept,
       "its mirror is dropped — four tiles must not tell one story four ways")
    ok("b" in kept, "an independent stat survives")


def test_decorrelate_keeps_distinct_stats():
    """Distinct stats are all kept — the pass is a filter, not a quota."""
    import helpers.insights_team as IT
    lines = {0: {"a": 1.0, "b": 5.0}, 1: {"a": 2.0, "b": 1.0},
             2: {"a": 3.0, "b": 9.0}, 3: {"a": 4.0, "b": 2.0}}
    ranked = [{"key": "a", "d": 2.0}, {"key": "b", "d": 1.0}]
    kept = [r["key"] for r in IT._decorrelate(ranked, lines, {}, 4)]
    ok(kept == ["a", "b"], "uncorrelated stats both survive")


def test_style_line_keys():
    """Tempo / creation keys come off the raw events, with no tagging needed."""
    import helpers.insights_team as IT

    ev = [
        _shot(1, 4, make=True),                       # transition, made 2
        _shot(1, 5),                                  # transition, miss
        _shot(1, 20, make=True, created_by=99),       # half-court, off a screen
        _shot(1, 25, pass_from=98),                   # half-court, off a pass
        _shot(2, 3),                                  # opp transition
        _shot(2, 30),                                 # opp half-court
    ]
    s = IT._style_line(1, ev)
    ok(abs(s["transition"] - 0.5) < 1e-9,
       "transition rate = 2 of 4 timed own possessions")
    ok(abs(s["trans_PPP"] - 1.0) < 1e-9, "transition PPP = 2 pts / 2 poss")
    ok(abs(s["hc_PPP"] - 1.0) < 1e-9, "half-court PPP = 2 pts / 2 poss")
    ok(abs(s["SC%"] - 0.25) < 1e-9, "1 of 4 shots came off a screen")
    ok(abs(s["selfmade"] - 0.5) < 1e-9,
       "2 of 4 shots had neither a pass nor a screen")
    ok(abs(s["o_transition"] - 0.5) < 1e-9, "opponent transition rate = 1 of 2")


def test_style_line_untimed_excluded():
    """Untimed possessions leave the tempo denominator instead of counting as
    half-court (~16% of real possessions carry no clock)."""
    import helpers.insights_team as IT
    ev = [_shot(1, 0), _shot(1, 0), _shot(1, 4, make=True)]
    s = IT._style_line(1, ev)
    ok(s["transition"] == 1.0,
       "the only TIMED possession was transition -> rate 1.0, not 0.33")


def test_style_line_none_not_zero():
    """A rate with no denominator is None, so winloss_alignment skips it rather
    than averaging a fake zero into the team's line."""
    import helpers.insights_team as IT
    s = IT._style_line(1, [_shot(2, 10)])      # team 1 never touched the ball
    ok(s["transition"] is None, "no own timed possessions -> None, not 0.0")
    ok(s["hc_PPP"] is None, "no half-court possessions -> None, not 0.0")
    ok(s["SC%"] is None, "no own FGA -> None, not 0.0")


def test_spec_keys_all_produced():
    """Every key in _WL_SPEC must actually be produced by team_stat_line —
    a typo'd key would silently never rank."""
    import helpers.insights_team as IT
    import helpers.stats as S
    from database.db import query
    rows = query("SELECT id, team1_id FROM games WHERE tracked=1 LIMIT 1")
    if not rows:
        print("  -- no tracked games; spec-key test skipped")
        return
    gid, tid = rows[0]["id"], rows[0]["team1_id"]
    line = IT.team_stat_line(tid, gid, events=S.fetch_events([gid]))
    if line is None:
        print("  -- no possessions in that game; spec-key test skipped")
        return
    missing = [k for k, _l, _f in IT._WL_SPEC if k not in line]
    ok(not missing, f"every _WL_SPEC key is produced (missing: {missing})")


if __name__ == "__main__":
    test_pearson()
    test_decorrelate_drops_the_same_story()
    test_decorrelate_keeps_distinct_stats()
    test_style_line_keys()
    test_style_line_untimed_excluded()
    test_style_line_none_not_zero()
    test_spec_keys_all_produced()
    print(f"\nALL {PASSED} CHECKS PASSED")
