"""
test_spacing.py — unit tests for the floor-spacing index (helpers/spacing.py).
The component math is tested directly; the percentile blend is tested by stubbing
the league-pool fetch; a final smoke runs the real index on the local DB.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.spacing as SP
import helpers.court_geom as CG


def _shot(x, y, value, guarded, team_id=1):
    return {"x": x, "y": y, "value": value, "guarded": guarded, "team_id": team_id}


def test_is_corner_three_geometry():
    assert CG.is_corner_three(21.0, 6.0) is True        # deep corner, low y
    assert CG.is_corner_three(-21.0, 7.0) is True        # other corner
    assert CG.is_corner_three(0.0, 27.0) is False        # top-of-arc 3, not corner
    assert CG.is_corner_three(2.0, 8.0) is False         # a paint two


def test_team_components_rates():
    shots = (
        [_shot(21, 6, 3, False) for _ in range(4)]       # corner 3s, open
        + [_shot(-2, 28, 3, True) for _ in range(2)]     # arc 3s, guarded
        + [_shot(3, 10, 2, False) for _ in range(4)]     # rim 2s, open
    )
    c = SP.team_components(shots)
    assert c["n"] == 10
    assert round(c["tpa_rate"], 2) == 0.60               # 6 threes / 10
    assert round(c["corner3_rate"], 2) == 0.40           # 4 corner 3s / 10
    assert round(c["open_rate"], 2) == 0.80              # 8 unguarded / 10
    assert c["x_spread"] > 0
    assert SP.team_components([]) is None


def test_spacing_index_orders_and_gates(monkeypatch=None):
    # 4 teams, monotonically worse spacing 1 -> 4 (>= MIN_POOL, min_shots small)
    pools = {
        1: [_shot(x, 6, 3, False, 1) for x in (21, -21, 21, -21, 20, -20)],   # all corner 3s, wide, open
        2: [_shot(0, 27, 3, False, 2) for _ in range(3)]                       # arc 3s, open, narrow
             + [_shot(3, 10, 2, True, 2) for _ in range(3)],
        3: [_shot(0, 27, 3, True, 3)]                                          # one guarded arc 3
             + [_shot(3, 10, 2, True, 3) for _ in range(5)],
        4: [_shot(2, 9, 2, True, 4) for _ in range(6)],                        # all guarded rim 2s, bunched
    }
    orig = SP._gender_located_by_team
    SP._gender_located_by_team = lambda *a, **k: {t: list(s) for t, s in pools.items()}
    try:
        outs = {t: SP.spacing_index(t, min_shots=4) for t in (1, 2, 3, 4)}
        thin = SP.spacing_index(99, min_shots=4)          # team not in pool
        toohigh = SP.spacing_index(1, min_shots=1000)     # nobody clears the bar
    finally:
        SP._gender_located_by_team = orig

    idx = {t: outs[t]["index"] for t in (1, 2, 3, 4)}
    for t in (1, 2, 3, 4):
        assert idx[t] is not None and 0 <= idx[t] <= 100
        assert len(outs[t]["components"]) == 4
        assert outs[t]["pool_n"] == 4
    assert idx[1] >= idx[2] >= idx[3] >= idx[4]            # monotone by spacing
    assert idx[1] > idx[4]                                 # clear separation
    # team 1 is best on every component -> each percentile is the top of 4
    assert all(c["pct"] == 75 for c in outs[1]["components"])

    # gates: team with no shots, and an unreachable min_shots
    assert thin["index"] is None and "Not enough located shots" in thin["note"]
    assert toohigh["index"] is None


def test_spacing_index_min_pool_gate():
    one = {1: [_shot(21, 6, 3, False, 1) for _ in range(10)]}
    orig = SP._gender_located_by_team
    SP._gender_located_by_team = lambda *a, **k: {t: list(s) for t, s in one.items()}
    try:
        out = SP.spacing_index(1, min_shots=4)
    finally:
        SP._gender_located_by_team = orig
    assert out["index"] is None and "Too few tracked teams" in out["note"]


def test_league_player_spacing_map_and_pool_gate():
    # 8 players clear min_shots -> a map keyed by pid with index + components
    players = {}
    for pid in range(1, 9):
        # more-corner-open shots for lower pids -> better spacing
        c3 = 6 if pid <= 4 else 0
        players[pid] = (
            [_shot(21, 6, 3, False, pid) for _ in range(c3)]
            + [_shot(3, 10, 2, True, pid) for _ in range(6 - c3 + 4)]
        )
    orig = SP._gender_located_by_player
    SP._gender_located_by_player = lambda *a, **k: {p: list(s) for p, s in players.items()}
    try:
        m = SP.league_player_spacing("M", min_shots=4)
        # min_pool gate: only 3 players -> empty map
        SP._gender_located_by_player = lambda *a, **k: {1: players[1], 2: players[2], 3: players[3]}
        thin = SP.league_player_spacing("M", min_shots=4)
    finally:
        SP._gender_located_by_player = orig
    assert len(m) == 8
    for pid in range(1, 9):
        assert 0 <= m[pid]["index"] <= 100 and len(m[pid]["components"]) == 4
    # better-spacing players (1-4) outrank worse (5-8) on average index
    assert (sum(m[p]["index"] for p in (1, 2, 3, 4)) / 4
            > sum(m[p]["index"] for p in (5, 6, 7, 8)) / 4)
    assert thin == {}                                     # < PLAYER_MIN_POOL(8)


def test_spacing_index_smoke_real_db():
    from database.db import query
    t = query("SELECT id, gender FROM teams LIMIT 1")
    if not t:
        return
    out = SP.spacing_index(t[0]["id"], gender=t[0]["gender"])
    assert "index" in out and "components" in out and "note" in out


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f(); print("PASS", f.__name__)
    print(f"--- {len(fns)}/{len(fns)} spacing tests pass ---")
