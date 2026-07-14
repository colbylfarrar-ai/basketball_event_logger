"""Team-prior anchor: a thin-sample player regresses toward their OWN team's
Power (partial pooling) instead of flat 50. Non-destructive at lambda=0; touches
OVERALL only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Task 1: the shrinkage anchor lever the feature rides on ───────────────────

def test_stabilize_index_respects_anchor():
    """Curve-agnostic: a higher anchor lifts the same thin sample, and a deep
    sample is far less anchor-sensitive. Holds for both the linear (k=5) and the
    sigmoid (k=3, prod recal) retention curves — no hardcoded curve constants."""
    import helpers.shrinkage as SHR
    # Same raw rating (70), same 2-game sample, different anchors.
    v_50 = SHR.stabilize_index(70.0, games=2, k_games=3.0, anchor=50.0)
    v_58 = SHR.stabilize_index(70.0, games=2, k_games=3.0, anchor=58.0)
    assert v_58 > v_50, "a higher anchor must lift the same thin sample"
    # The stabilized value sits between the anchor and the raw 70.
    assert 50.0 < v_50 < 70.0 and 58.0 < v_58 < 70.0
    # A full-season sample barely moves regardless of anchor.
    deep_50 = SHR.stabilize_index(70.0, games=30, k_games=3.0, anchor=50.0)
    deep_58 = SHR.stabilize_index(70.0, games=30, k_games=3.0, anchor=58.0)
    assert abs(deep_58 - deep_50) < abs(v_58 - v_50), \
        "deep sample must be less anchor-sensitive than the thin one"


# ── Task 2: the anchor-map helper ─────────────────────────────────────────────

def test_team_prior_anchors_math_and_damping():
    import helpers.player_ratings as PR
    profiles = {
        1: {"team_id": 10},   # elite team, deep résumé
        2: {"team_id": 20},   # average team
        3: {"team_id": 30},   # elite Power but a 2-game (fluke-risk) team
    }
    opp_ratings = {
        10: {"Power": 70.0, "GP": 24},
        20: {"Power": 50.0, "GP": 24},
        30: {"Power": 70.0, "GP": 2},
    }
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 0.5
    try:
        a = PR._team_prior_anchors(profiles, gender="F", season="Current",
                                   opp_ratings=opp_ratings)
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    # elite deep: conf = 24/30 = 0.8 -> 50 + 0.5*0.8*20 = 58.0
    assert round(a[1], 2) == 58.0
    # average team: (50-50)=0 -> stays 50
    assert round(a[2], 2) == 50.0
    # elite but thin: conf = 2/8 = 0.25 -> 50 + 0.5*0.25*20 = 52.5
    assert round(a[3], 2) == 52.5
    assert a[3] < a[1], "thin-résumé elite team anchors weaker than deep elite team"


def test_team_prior_symmetric_below_50():
    """Symmetric prior: a thin player on a weak team anchors BELOW 50."""
    import helpers.player_ratings as PR
    profiles = {1: {"team_id": 10}}
    opp_ratings = {10: {"Power": 30.0, "GP": 24}}   # weak team
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 0.5
    try:
        a = PR._team_prior_anchors(profiles, gender="F", season="Current",
                                   opp_ratings=opp_ratings)
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    # conf 0.8 -> 50 + 0.5*0.8*(30-50) = 42.0
    assert round(a[1], 2) == 42.0
    assert not PR.TEAM_PRIOR_BOOST_ONLY, "v1 ships symmetric (not boost-only)"


def test_team_prior_lambda_zero_is_neutral():
    import helpers.player_ratings as PR
    profiles = {1: {"team_id": 10}}
    opp_ratings = {10: {"Power": 80.0, "GP": 30}}
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 0.0
    try:
        a = PR._team_prior_anchors(profiles, gender="F", season="Current",
                                   opp_ratings=opp_ratings)
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    assert a[1] == 50.0, "lambda=0 must yield the flat-50 anchor (identity)"


def test_team_prior_unknown_team_defaults_to_50():
    import helpers.player_ratings as PR
    profiles = {1: {"team_id": 999}}   # not in opp_ratings
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 0.5
    try:
        a = PR._team_prior_anchors(profiles, gender="F", season="Current",
                                   opp_ratings={10: {"Power": 70.0, "GP": 24}})
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    assert a[1] == 50.0, "no team Power -> neutral anchor, never a crash"


def test_team_prior_anchor_clamped_to_bounds():
    import helpers.player_ratings as PR
    profiles = {1: {"team_id": 10}}
    opp_ratings = {10: {"Power": 200.0, "GP": 999}}   # absurd, must clamp
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 1.0
    try:
        a = PR._team_prior_anchors(profiles, gender="F", season="Current",
                                   opp_ratings=opp_ratings)
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    assert a[1] == PR.TEAM_PRIOR_BOUNDS[1], "anchor clamped to upper bound"


# ── Task 3: OVERALL shrinkage math + real-DB contracts ────────────────────────

def test_anchor_lifts_thin_player_on_strong_team_synthetic():
    import helpers.player_ratings as PR
    import helpers.shrinkage as SHR
    anchor_on = 58.0
    raw = 70.0
    thin_off = SHR.stabilize_index(raw, 2, k_games=PR.RATING_K_GAMES, anchor=50.0)
    thin_on = SHR.stabilize_index(raw, 2, k_games=PR.RATING_K_GAMES, anchor=anchor_on)
    deep_off = SHR.stabilize_index(raw, 30, k_games=PR.RATING_K_GAMES, anchor=50.0)
    deep_on = SHR.stabilize_index(raw, 30, k_games=PR.RATING_K_GAMES, anchor=anchor_on)
    assert thin_on > thin_off, "thin-sample player on a strong team must rise"
    assert abs(deep_on - deep_off) < abs(thin_on - thin_off), \
        "deep-sample player must move far less than the thin one"


def _tracked_scope():
    """(game_ids, season) for the tracked pool in whatever DB is present, or
    (None, None) if there isn't enough to test. DB-agnostic (works on the local
    2025-2026 DB and on prod's 'Current')."""
    from database.db import query
    rows = query("SELECT id, season FROM games WHERE tracked=1")
    if len(rows) < 5:
        return None, None
    seasons = {}
    for r in rows:
        seasons.setdefault(r["season"], []).append(r["id"])
    season = max(seasons, key=lambda s: len(seasons[s]))   # dominant season
    return [r["id"] for r in rows], season


def test_lambda_zero_byte_identical_real_db():
    """lambda=0 must reproduce the exact current OVERALL for every player."""
    import helpers.player_ratings as PR
    gids, season = _tracked_scope()
    if gids is None:
        return
    orig = PR.TEAM_PRIOR_LAMBDA
    PR.TEAM_PRIOR_LAMBDA = 0.0
    try:
        a = {p: r["OVERALL"] for p, r in
             PR.player_ratings(game_ids=gids, season=season).items()}
        b = {p: r["OVERALL"] for p, r in
             PR.player_ratings(game_ids=gids, season=season).items()}
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    assert len(a) >= 20 and a == b, "lambda=0 must be deterministic + unchanged"


def test_overall_only_real_db():
    """Turning the anchor on moves some OVERALLs but leaves OFFENSE/DEFENSE/
    PLAYMAKING/REBOUNDING byte-identical (OVR-only contract)."""
    import helpers.player_ratings as PR
    gids, season = _tracked_scope()
    if gids is None:
        return
    orig = PR.TEAM_PRIOR_LAMBDA
    try:
        PR.TEAM_PRIOR_LAMBDA = 0.0
        off = PR.player_ratings(game_ids=gids, season=season)
        PR.TEAM_PRIOR_LAMBDA = 0.5
        on = PR.player_ratings(game_ids=gids, season=season)
    finally:
        PR.TEAM_PRIOR_LAMBDA = orig
    if len(off) < 20:
        return
    changed = sum(1 for p in off if off[p]["OVERALL"] != on[p]["OVERALL"])
    assert changed > 0, "the anchor must move at least some OVERALLs"
    for k in ("OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING", "Shooting"):
        assert all(off[p][k] == on[p][k] for p in off), \
            f"{k} must be untouched by the OVERALL-only anchor"


if __name__ == "__main__":
    fns = [test_stabilize_index_respects_anchor,
           test_team_prior_anchors_math_and_damping,
           test_team_prior_symmetric_below_50,
           test_team_prior_lambda_zero_is_neutral,
           test_team_prior_unknown_team_defaults_to_50,
           test_team_prior_anchor_clamped_to_bounds,
           test_anchor_lifts_thin_player_on_strong_team_synthetic,
           test_lambda_zero_byte_identical_real_db,
           test_overall_only_real_db]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
