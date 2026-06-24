"""
test_development.py — Tier-3 cross-season development engine (helpers/development.py).
class_of + _trend are pure; progression/projection are tested with a stubbed
season_lines so the YoY math + gating are exact (no DB). A final real-DB smoke
confirms the one-season graceful path.
"""
import helpers.development as DV


def test_class_of():
    assert DV.class_of(2026, "2025-2026") == "Sr"
    assert DV.class_of(2027, "2025-2026") == "Jr"
    assert DV.class_of(2028, "2025-2026") == "So"
    assert DV.class_of(2029, "2025-2026") == "Fr"
    assert DV.class_of(None, "2025-2026") is None


def test_trend_tags():
    assert DV._trend("PPG", 2.0) == "▲"     # > eps 1.5
    assert DV._trend("PPG", 1.0) == "—"     # below eps
    assert DV._trend("TPG", -1.0) == "▲"    # fewer turnovers = improvement
    assert DV._trend("TPG", 1.0) == "▼"


def _line(season, klass, gp, ppg, rpg, fg):
    return {"season": season, "label": season, "team": "X", "player_id": hash(season) % 999,
            "grad_year": 2027, "klass": klass, "gp": gp, "PPG": ppg, "RPG": rpg,
            "APG": 2.0, "SPG": 1.0, "BPG": 0.5, "TPG": 2.0, "FG%": fg, "3P%": 33.0,
            "FT%": 70.0, "eFG": 48.0, "TS%": 52.0, "PTS": int(ppg * gp)}


def test_progression_deltas_and_headline():
    lines = [_line("2024-2025", "Jr", 18, 10.0, 4.0, 44.0),
             _line("Current", "Sr", 20, 15.0, 5.0, 47.0)]
    orig = DV.season_lines
    DV.season_lines = lambda k: lines
    try:
        prog = DV.progression(1)
    finally:
        DV.season_lines = orig
    assert prog["rated_seasons"] == 2
    assert prog["deltas"]["PPG"]["delta"] == 5.0 and prog["deltas"]["PPG"]["trend"] == "▲"
    assert prog["deltas"]["RPG"]["delta"] == 1.0
    assert "PPG +5.0" in prog["headline"]


def test_progression_single_season_no_deltas():
    orig = DV.season_lines
    DV.season_lines = lambda k: [_line("Current", "Sr", 20, 15.0, 5.0, 47.0)]
    try:
        prog = DV.progression(1)
    finally:
        DV.season_lines = orig
    assert prog["rated_seasons"] == 1 and prog["deltas"] is None


def test_project_next_needs_two_seasons():
    orig = DV.season_lines
    DV.season_lines = lambda k: [_line("Current", "Sr", 20, 15.0, 5.0, 47.0)]
    try:
        p = DV.project_next(1, curve={})
    finally:
        DV.season_lines = orig
    assert p["ok"] is False and "unlocks" in p["reason"]


def test_project_next_own_trend():
    lines = [_line("2024-2025", "Jr", 18, 10.0, 4.0, 44.0),
             _line("Current", "Sr", 20, 15.0, 5.0, 47.0)]
    orig = DV.season_lines
    DV.season_lines = lambda k: lines
    try:
        p = DV.project_next(1, curve={})          # no class curve -> own trend only
    finally:
        DV.season_lines = orig
    assert p["ok"] is True
    # next PPG = last 15.0 + 0.5*own_delta(5.0) = 17.5
    assert p["proj"]["PPG"] == 17.5
    assert p["basis"] == "own-trend"


def test_player_development_smoke_real_db():
    from database.db import query
    r = query("SELECT id FROM players WHERE archived=0 LIMIT 1")
    if not r:
        return
    out = DV.player_development(r[0]["id"])
    assert "progression" in out and "projection" in out
    assert out["progression"]["rated_seasons"] >= 0
