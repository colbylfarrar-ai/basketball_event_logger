"""
test_preset_lineups.py — unit tests for team_analytics.preset_lineups.
The shared lineup_prediction is stubbed (Net = sum of pids) so the dedup/merge,
the volume gate, the min-size gate and the Net-desc sort are all checkable.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.team_analytics as TA


def _row(pid, **over):
    """A player_stat_table-shaped row with safe baselines, overridable per key."""
    d = {
        "_pid": pid, "name": f"P{pid}", "number": pid,
        "OVERALL": 50, "OFFENSE": 50, "DEFENSE": 50,
        "3P%": 33.0, "3PA": 20, "FT%": 70.0, "FTA": 12,
        "SPG": 1.0, "REBOUNDING": 50, "PLAYMAKING": 50, "BPG": 0.5,
        "2WAY": 50, "TOV%": 10.0, "USG%": 20.0, "Q4PPG": 4.0,
    }
    d.update(over)
    return d


def test_preset_lineups_merge_gate_sort():
    orig = TA.lineup_prediction
    TA.lineup_prediction = (lambda rows, pids, ctx, tid, opp_id=None:
                            {"ORtg": 100.0, "DRtg": 95.0, "NetRtg": float(sum(pids))})
    try:
        rows = [
            _row(1, OVERALL=95, OFFENSE=95, DEFENSE=70, TOV=8),
            _row(2, OVERALL=90, OFFENSE=90, DEFENSE=75),
            _row(3, OVERALL=85, OFFENSE=85, DEFENSE=80),
            _row(4, OVERALL=80, OFFENSE=80, DEFENSE=85),
            _row(5, OVERALL=75, OFFENSE=75, DEFENSE=90, **{"3PA": 5}),
            _row(6, OVERALL=70, OFFENSE=70, DEFENSE=95, **{"3PA": 5}),
        ]
        out = TA.preset_lineups(rows, ctx=None, team_id=1)
        empty = TA.preset_lineups(rows[:4], ctx=None, team_id=1)
    finally:
        TA.lineup_prediction = orig

    assert empty == []                                    # < size(5) rated players

    by_five = {frozenset(p["pid"] for p in o["players"]): o for o in out}
    # OVERALL & OFFENSE pick the same top five {1,2,3,4,5} -> merged labels
    ovr_five = by_five[frozenset({1, 2, 3, 4, 5})]
    assert "Best overall" in ovr_five["labels"]
    assert "Best offense" in ovr_five["labels"]
    # DEFENSE picks {2,3,4,5,6} -> a distinct five
    assert frozenset({2, 3, 4, 5, 6}) in by_five
    # 3-pt lens: only 4 players clear the 3PA>=15 gate -> lens skipped entirely
    assert not any("Best 3-pt shooting" in o["labels"] for o in out)
    # every preset is exactly five players
    assert all(len(o["players"]) == 5 for o in out)
    # sorted by projected Net desc: {2,3,4,5,6}=20 ranks above {1,2,3,4,5}=15
    nets = [o["pred"]["NetRtg"] for o in out]
    assert nets == sorted(nets, reverse=True)
    assert out[0]["pred"]["NetRtg"] >= 20


def test_preset_lineups_predictor_failure_is_graceful():
    orig = TA.lineup_prediction
    def _boom(*a, **k):
        raise RuntimeError("thin")
    TA.lineup_prediction = _boom
    try:
        rows = [_row(i) for i in range(1, 7)]
        out = TA.preset_lineups(rows, ctx=None, team_id=1)
    finally:
        TA.lineup_prediction = orig
    # at least one distinct five built; pred is None but the preset still lists
    assert out and all(o["pred"] is None for o in out)
    assert all(len(o["players"]) == 5 for o in out)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f(); print("PASS", f.__name__)
    print(f"--- {len(fns)}/{len(fns)} preset-lineup tests pass ---")
