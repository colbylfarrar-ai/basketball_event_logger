"""
test_goals_attribution.py — the signature-goal set: how many, which night, and
which of them the tracker can actually score while the game is running.

Three things the engine gained:
  * the goal COUNT is the |d| gate's answer per team, capped at MAX_GOALS, not a
    flat 4 that truncated every team to the same number;
  * `per_game` keeps the per-game hit attribution the grouped record used to sum
    away — which game, which opponent, which goal dropped;
  * `goal_capture` says which goals depend on an optional per-shot tag, so a goal
    nobody has tagged can render as unmeasured instead of as a confident miss.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.insights_team as IT
from database.db import query


# ── goal_capture: pure, no DB ────────────────────────────────────────────────

def _shot(team, **kw):
    e = {"event_type": "shot", "shooter_team_id": team,
         "pass_from_id": None, "shot_created_by_id": None,
         "rebound_by_id": None}
    e.update(kw)
    return e


def test_goal_capture_only_reports_tag_backed_keys():
    """PPP and eFG need no optional tag, so they never appear in the report."""
    cap = IT.goal_capture(1, [_shot(1)], ["PPP", "eFG", "AST%", "run_diff"])
    assert set(cap) == {"AST%"}, cap


def test_goal_capture_counts_zero_partial_and_full():
    ev = [_shot(1), _shot(1, pass_from_id=7), _shot(1, pass_from_id=9),
          _shot(1)]
    cap = IT.goal_capture(1, ev, ["AST%", "ORBpct"])
    assert cap["AST%"]["shots"] == 4
    assert cap["AST%"]["tagged"] == 2
    assert cap["AST%"]["pct"] == 50.0
    # nobody tagged a rebound — the stat is unmeasured, not zero
    assert cap["ORBpct"]["tagged"] == 0


def test_goal_capture_ignores_the_other_team_and_non_shots():
    ev = [_shot(1, pass_from_id=3), _shot(2, pass_from_id=4),
          {"event_type": "turnover", "shooter_team_id": 1, "pass_from_id": 5}]
    cap = IT.goal_capture(1, ev, ["AST%"])
    assert cap["AST%"] == {"fields": ("pass_from_id",), "tagged": 1,
                           "shots": 1, "pct": 100.0}


def test_selfmade_needs_either_tag():
    """A shot with neither a pass nor a screen is COUNTED as self-created, so an
    untagged game inflates `selfmade` toward 1.0 rather than sinking it to 0 —
    the direction that silently reads as a hit. Both fields count as coverage."""
    assert IT.GOAL_INPUTS["selfmade"] == ("pass_from_id", "shot_created_by_id")
    ev = [_shot(1, shot_created_by_id=2), _shot(1, pass_from_id=3), _shot(1)]
    assert IT.goal_capture(1, ev, ["selfmade"])["selfmade"]["tagged"] == 2


def test_no_shots_yet_reports_no_percentage():
    cap = IT.goal_capture(1, [], ["AST%"])
    assert cap["AST%"]["shots"] == 0 and cap["AST%"]["pct"] is None


# ── the goal count and the per-game list, over whatever the DB holds ─────────

def _best_team():
    rows = query("""SELECT t.id, t.gender, COUNT(*) n FROM games g
                    JOIN teams t ON t.id IN (g.team1_id, g.team2_id)
                    WHERE g.tracked = 1 AND g.home_score IS NOT NULL
                      AND g.away_score IS NOT NULL
                    GROUP BY t.id ORDER BY n DESC LIMIT 1""")
    return rows[0] if rows else None


def _fit(t):
    gids = [r["id"] for r in query(
        """SELECT id FROM games WHERE (team1_id = ? OR team2_id = ?)
           AND tracked = 1 AND home_score IS NOT NULL
           AND away_score IS NOT NULL""", (t["id"], t["id"]))]
    return IT.winloss_alignment(t["id"], gender=t["gender"], game_ids=gids)


def test_goal_count_is_the_gate_not_a_fixed_four():
    t = _best_team()
    if not t:
        return                                   # empty DB — nothing to prove
    d = _fit(t)
    if not d.get("available"):
        return
    assert 0 < d["n_goals"] <= IT.MAX_GOALS
    assert len(d["goals"]) == d["n_goals"]


def test_per_game_attribution_reconciles_with_the_grouped_record():
    """The game list and the ladder must be the same hit test, counted twice."""
    t = _best_team()
    if not t:
        return
    d = _fit(t)
    if not d.get("available") or not d.get("per_game"):
        return
    pg = d["per_game"]
    # every attributed game names an opponent and a result
    for p in pg:
        assert p["result"] in ("win", "loss")
        assert 0 <= p["hit"] <= p["of"] <= d["n_goals"]
        assert set(p["goals"]) == {g["key"] for g in d["goals"]}
    # the ladder is exactly this list, grouped by hit count
    from collections import Counter
    got = Counter((p["hit"], p["result"]) for p in pg)
    for r in d["record"]:
        assert r["wins"] == got.get((r["n"], "win"), 0)
        assert r["losses"] == got.get((r["n"], "loss"), 0)
    assert sum(r["games"] for r in d["record"]) == len(pg)


def test_per_game_is_ordered_and_labelled():
    t = _best_team()
    if not t:
        return
    d = _fit(t)
    if not d.get("available") or not d.get("per_game"):
        return
    dates = [p["date"] for p in d["per_game"] if p["date"]]
    assert dates == sorted(dates), "per_game should read as a schedule"
