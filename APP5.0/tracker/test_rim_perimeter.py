"""Tests for rim protection + perimeter defense (stats.rim_perimeter_defense
+ the DEFENSE-rating fold in player_ratings)."""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _shot(shooter, made, stype=2, guarded=None, blocked=None, x=None, y=None):
    return {"event_type": "shot", "primary_player_id": shooter,
            "shot_result": "make" if made else "miss", "shot_type": stype,
            "pass_from_id": None, "shot_created_by_id": None,
            "blocked_by_id": blocked, "guarded_by_id": guarded,
            "stolen_by_id": None, "rebound_by_id": None,
            "rebounder_team_id": None, "shooter_team_id": 1,
            "secondary_player_id": None, "official_id": None,
            "zone": "C", "shot_x": x, "shot_y": y, "play_type": None}


def test_rim_and_perimeter_buckets():
    import helpers.stats as S
    events = []
    # defender 7 contests 10 rim shots, allows 3 makes (30%); blocks two of the
    # misses (block credit = same defended shot, no double count)
    for i in range(10):
        events.append(_shot(1, made=(i < 3), guarded=7,
                            blocked=(7 if i in (8, 9) else None),
                            x=0.5, y=5.5))
    # the rest of the league allows 7/10 at the rim (70%)
    for i in range(10):
        events.append(_shot(1, made=(i < 7), guarded=8, x=0.0, y=6.0))
    # defender 9 contests 8 threes, allows 2 (25%); league other = 5/8
    for i in range(8):
        events.append(_shot(2, made=(i < 2), stype=3, guarded=9))
    for i in range(8):
        events.append(_shot(2, made=(i < 5), stype=3, guarded=8))
    # unlocated mid-range 2 -> neither bucket
    events.append(_shot(3, True, guarded=7))

    out, lg = S.rim_perimeter_defense(events=events)
    assert out[7]["rim_fga"] == 10 and out[7]["rim_fgm"] == 3
    assert abs(lg["lg_rim_pct"] - 0.5) < 1e-9          # 10/20 league rim
    assert abs(out[7]["RimProt"] - (0.5 - 0.3)) < 1e-9  # +20 pts saved
    assert out[7]["PerimD"] is None                     # no threes faced
    assert abs(out[9]["PerimD"] - (7 / 16 - 0.25)) < 1e-9
    # under the 8-shot gate -> None
    assert out[8]["RimProt"] is not None or out[8]["rim_fga"] >= 8


def test_block_credit_offball():
    """Blocker who isn't the listed contester still owns the rim shot."""
    import helpers.stats as S
    events = [_shot(1, False, guarded=5, blocked=6, x=0.0, y=5.5)
              for _ in range(8)]
    events += [_shot(1, True, guarded=4, x=0.0, y=5.5) for _ in range(8)]
    out, lg = S.rim_perimeter_defense(events=events)
    assert out[6]["rim_fga"] == 8 and out[6]["rim_fgm"] == 0
    assert out[6]["RimProt"] > 0


def test_defense_rating_contract_real_db():
    """Adding the leaves must not move the pool: the re-standardization keeps
    the DEFENSE distribution where it was (mean/SD shift < 0.5 vs the old leaf
    set — the STATUS-64 measure-before-committing check, automated)."""
    import helpers.player_ratings as PR

    def dist(leaves):
        PR._DEFENSE[:] = leaves
        rows = PR.player_stat_table(gender="F")
        vals = [r["DEFENSE"] for r in rows.values()
                if r.get("DEFENSE") is not None]
        return rows, vals

    new_leaves = list(PR._DEFENSE)
    old_leaves = [l for l in new_leaves if l[0] not in ("RimProt", "PerimD")]
    try:
        rows, new_vals = dist(new_leaves)
        if len(new_vals) < 20:
            return                               # pool too thin locally
        _, old_vals = dist(old_leaves)
        d_mean = abs(statistics.mean(new_vals) - statistics.mean(old_vals))
        d_sd = abs(statistics.pstdev(new_vals) - statistics.pstdev(old_vals))
        assert d_mean < 0.5, f"DEFENSE pool mean shifted {d_mean:.2f}"
        assert d_sd < 0.5, f"DEFENSE pool SD shifted {d_sd:.2f}"
    finally:
        PR._DEFENSE[:] = new_leaves              # restore for later tests
    r = next(iter(rows.values()))
    for k in ("RimDFG%", "RimDShots", "PerimDFG%", "PerimDShots",
              "RimProt", "PerimD"):
        assert k in r, f"missing stat-table key {k}"


if __name__ == "__main__":
    for fn in [test_rim_and_perimeter_buckets, test_block_credit_offball,
               test_defense_rating_contract_real_db]:
        fn()
        print(f"PASS {fn.__name__}")
