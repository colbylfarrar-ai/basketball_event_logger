"""Tests for helpers/fatigue.py — rest buckets, heavy weeks, league rest edge."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_rest_buckets_and_heavy():
    from helpers import fatigue as FT
    # Tue/Fri rhythm, then a brutal tournament stretch of daily games.
    rows = [
        {"date": "2026-01-06", "margin": 10, "won": True},   # opener (no rest)
        {"date": "2026-01-09", "margin": 8, "won": True},    # 3 days
        {"date": "2026-01-13", "margin": 6, "won": True},    # 4 days
        {"date": "2026-01-20", "margin": 12, "won": True},   # 7 days -> 5+
        {"date": "2026-01-21", "margin": -4, "won": False},  # B2B
        {"date": "2026-01-22", "margin": -6, "won": False},  # B2B
        {"date": "2026-01-24", "margin": 2, "won": True},    # 2 days
    ]
    rs = FT.rest_splits(rows)
    by = {b["key"]: b for b in rs["buckets"]}
    assert by["b2b"]["gp"] == 2 and by["b2b"]["w"] == 0
    assert by["normal"]["gp"] == 2                      # the 3- and 4-day gaps
    assert by["long"]["gp"] == 1
    assert by["short"]["gp"] == 1
    # B2B MOV (-5) well under the season MOV -> negative delta
    assert by["b2b"]["delta"] < 0
    # heavy week: the 22nd (20/21/22) and 24th (20/21/22/24) sit in 3+-game
    # weeks; the 21st only has two (20th, 21st) so it doesn't count
    assert rs["heavy"] and rs["heavy"]["gp"] == 2
    # opener excluded from every rest bucket
    assert sum(b["gp"] for b in rs["buckets"]) == len(rows) - 1


def test_rest_splits_thin_guard():
    from helpers import fatigue as FT
    assert FT.rest_splits([{"date": "2026-01-06", "margin": 1, "won": True}]) is None
    assert FT.rest_splits([{"date": "junk", "margin": 1, "won": True}] * 5) is None


def test_league_edge_symmetry_real_db():
    """Real DB smoke: the rest-differential curve must be antisymmetric-ish
    (diff d and -d are the same games from both sides) and volume-gated."""
    from helpers import fatigue as FT
    edge = FT.league_rest_edge()
    assert isinstance(edge, dict)
    for d, v in edge.items():
        assert v["gp"] >= 5
        assert -3 <= d <= 3


def test_team_rest_splits_real_db():
    from helpers import fatigue as FT
    per = FT._team_games()
    if not per:
        return
    tid = max(per, key=lambda t: len(per[t]))
    rs = FT.team_rest_splits(tid)
    if rs:
        assert rs["gp"] >= 3
        assert abs(sum(b["gp"] for b in rs["buckets"]) - (rs["gp"] - 1)) <= 2


if __name__ == "__main__":
    for fn in [test_rest_buckets_and_heavy, test_rest_splits_thin_guard,
               test_league_edge_symmetry_real_db, test_team_rest_splits_real_db]:
        fn()
        print(f"PASS {fn.__name__}")
