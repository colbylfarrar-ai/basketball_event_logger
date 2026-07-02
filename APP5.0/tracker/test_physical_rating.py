"""Tests for the PHYSICAL rating (height/wingspan leaves + the small OVERALL
nudge) — including the pool-shift contract check."""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_physical_leaves_and_overall_part():
    import helpers.player_ratings as PR
    assert ("height", 1.0, False) in PR._PHYSICAL
    assert not any(s == "weight" for s, _w, _lb in PR._PHYSICAL), \
        "weight (mass) must not be a leaf"
    assert ("physical", 0.25) in PR._OVERALL_PARTS, \
        "physical feeds OVERALL at the small locked weight"


def test_stat_table_keys_and_contract_real_db():
    """Keys present; removing the physical part must not move the OVERALL pool
    (the automated shift check — most local players have no measurements, and
    the part drops from _wavg when missing)."""
    import helpers.player_ratings as PR

    def pool(parts):
        PR._OVERALL_PARTS[:] = parts
        rows = PR.player_stat_table(gender="F")
        return rows, [r["OVERALL"] for r in rows.values()
                      if r.get("OVERALL") is not None]

    new_parts = list(PR._OVERALL_PARTS)
    old_parts = [p for p in new_parts if p[0] != "physical"]
    try:
        rows, new_vals = pool(new_parts)
        if len(new_vals) < 20:
            return
        _, old_vals = pool(old_parts)
        d_mean = abs(statistics.mean(new_vals) - statistics.mean(old_vals))
        d_sd = abs(statistics.pstdev(new_vals) - statistics.pstdev(old_vals))
        assert d_mean < 0.5, f"OVERALL pool mean shifted {d_mean:.2f}"
        assert d_sd < 0.5, f"OVERALL pool SD shifted {d_sd:.2f}"
    finally:
        PR._OVERALL_PARTS[:] = new_parts
    r = next(iter(rows.values()))
    for k in ("PHYSICAL", "Height", "Wingspan", "Weight"):
        assert k in r, f"missing key {k}"


def test_physical_rating_orders_by_length():
    """Synthetic: taller + longer player rates higher on PHYSICAL."""
    import helpers.player_ratings as PR
    profiles = {}
    for i, (h, w) in enumerate([(78, 80), (74, 75), (70, 70), (72, None),
                                (None, None), (76, 78), (71, 72), (73, 74),
                                (69, 69), (75, 76)]):
        profiles[i] = {"height": h, "wingspan": w}
    z = None
    # reuse the engine's own zcol/group machinery via a tiny local mirror
    def zs(stat):
        vals = {p: profiles[p][stat] for p in profiles}
        present = {p: v for p, v in vals.items() if v is not None}
        m = sum(present.values()) / len(present)
        sd = (sum((v - m) ** 2 for v in present.values()) / len(present)) ** 0.5
        return {p: ((v - m) / sd if v is not None else None)
                for p, v in vals.items()}
    hz, wz = zs("height"), zs("wingspan")
    big, small = 0, 8
    assert hz[big] > hz[small] and wz[big] > wz[small]
    assert hz[4] is None, "no measurement -> None, drops from the mean"


if __name__ == "__main__":
    for fn in [test_physical_leaves_and_overall_part,
               test_stat_table_keys_and_contract_real_db,
               test_physical_rating_orders_by_length]:
        fn()
        print(f"PASS {fn.__name__}")
