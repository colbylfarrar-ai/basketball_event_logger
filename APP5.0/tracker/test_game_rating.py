"""
test_game_rating.py — unit tests for the per-game 0-10 rating engine
(helpers/game_rating.py). Synthetic events with a known expected-points model →
exact component arithmetic; role assignment boundaries; calibration + clamp +
involvement shrink. DB-free (mirrors test_possession_value.py).
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.game_rating as GR


# ── expected-points model ──────────────────────────────────────────────────────

def _model_events():
    ev = []
    # (2,"C"): 5 attempts, 2 makes → p=0.4, xp=0.8
    for r in ["make", "make", "miss", "miss", "miss"]:
        ev.append({"event_type": "shot", "shot_type": 2, "zone": "C", "shot_result": r})
    # (3,"RW"): 5 attempts, 1 make → p=0.2, xp=0.6
    for r in ["make", "miss", "miss", "miss", "miss"]:
        ev.append({"event_type": "shot", "shot_type": 3, "zone": "RW", "shot_result": r})
    return ev


def test_expected_points_zone_rate():
    m = GR.build_model(_model_events())
    assert abs(GR.expected_points(m, 2, "C") - 0.8) < 1e-9      # 0.4 * 2
    assert abs(GR.expected_points(m, 3, "RW") - 0.6) < 1e-9     # 0.2 * 3


def test_expected_points_thin_bucket_falls_back_to_global():
    m = GR.build_model(_model_events())
    # zone "LW" has no attempts → global 2P rate = 2/5 = 0.4 → xp = 0.8
    assert abs(GR.expected_points(m, 2, "LW") - 0.8) < 1e-9


# ── component deltas ────────────────────────────────────────────────────────────

def test_shooting_delta_make_over_expected():
    m = GR.build_model(_model_events())
    P = 10
    # player 10 makes a 2 in C (xp 0.8) → +1.2 ; misses a 3 in RW (xp 0.6) → -0.6
    evs = [
        {"event_type": "shot", "shot_type": 2, "zone": "C", "shot_result": "make",
         "primary_player_id": P},
        {"event_type": "shot", "shot_type": 3, "zone": "RW", "shot_result": "miss",
         "primary_player_id": P},
    ]
    comp = GR.player_game_value(P, evs, m)
    assert abs(comp["shooting"] - (2 - 0.8 + 0 - 0.6)) < 1e-9   # +1.2 -0.6 = 0.6
    assert comp["_involvement"] == 2


def test_assist_and_turnover_playmaking():
    m = GR.build_model(_model_events())
    P = 7
    evs = [
        # P assists a made 2 in C (xp 0.8) → +0.8*ASSIST_SHARE(0.5)=+0.4
        {"event_type": "shot", "shot_type": 2, "zone": "C", "shot_result": "make",
         "primary_player_id": 99, "pass_from_id": P},
        # P turns it over → -PPP_LEAGUE (1.0)
        {"event_type": "turnover", "primary_player_id": P},
    ]
    comp = GR.player_game_value(P, evs, m)
    assert abs(comp["playmaking"] - (0.4 - 1.0)) < 1e-9


def test_defense_smoe_steal_block():
    m = GR.build_model(_model_events())
    P = 3
    evs = [
        # P contests a 2 in C (p=0.4) that MISSES → def SMOE credit
        {"event_type": "shot", "shot_type": 2, "zone": "C", "shot_result": "miss",
         "primary_player_id": 50, "guarded_by_id": P},
        # P steals → +PPP (1.0)
        {"event_type": "turnover", "primary_player_id": 51, "stolen_by_id": P},
        # P blocks a 3 in RW (xp 0.6) → +0.6
        {"event_type": "shot", "shot_type": 3, "zone": "RW", "shot_result": "miss",
         "primary_player_id": 52, "blocked_by_id": P},
    ]
    comp = GR.player_game_value(P, evs, m)
    # def SMOE: expected makes 0.4, actual 0 → (0.4-0)*DEF_MAKE_PTS(2.0)=0.8
    # + steal 1.0 + block 0.6 = 2.4
    assert abs(comp["defense"] - (0.8 + 1.0 + 0.6)) < 1e-9


def test_rebounding_oreb_worth_more():
    m = GR.build_model([])
    P = 5
    evs = [
        {"event_type": "shot", "shot_type": 2, "shot_result": "miss",
         "primary_player_id": 1, "rebound_by_id": P,
         "shooter_team_id": 100, "rebounder_team_id": 100},   # OREB
        {"event_type": "shot", "shot_type": 2, "shot_result": "miss",
         "primary_player_id": 1, "rebound_by_id": P,
         "shooter_team_id": 100, "rebounder_team_id": 200},   # DREB
    ]
    comp = GR.player_game_value(P, evs, m)
    assert abs(comp["rebounding"] - (GR.OREB_VAL + GR.DREB_VAL)) < 1e-9


def test_fouls_drawn_vs_committed():
    m = GR.build_model([])
    P = 8
    evs = [
        {"event_type": "foul", "primary_player_id": P, "secondary_player_id": 2},   # P drew it
        {"event_type": "foul", "primary_player_id": 3, "secondary_player_id": P},   # P committed
    ]
    comp = GR.player_game_value(P, evs, m)
    assert abs(comp["fouls"] - (GR.FOUL_DRAWN - GR.FOUL_COMMIT)) < 1e-9


# ── role assignment ─────────────────────────────────────────────────────────────

def test_role_two_way_star_needs_both_ends():
    assert GR.role_for({"OFFENSE": 70, "DEFENSE": 65}) == "Two-Way Star"
    # strong O, weak D → not a star (percentages on 0-100 scale)
    assert GR.role_for({"OFFENSE": 70, "DEFENSE": 40, "USG%": 30.0}) == "Primary Scorer"


def test_role_style_buckets():
    # percentages on the 0-100 scale that player_stat_table emits
    assert GR.role_for({"APG": 5.0}) == "Playmaker"
    assert GR.role_for({"RimFGA%": 60.0, "RPG": 8}) == "Interior/Big"
    assert GR.role_for({"3PR": 60.0, "3P%": 38.0}) == "Shooter/Wing"
    assert GR.role_for({"PPG": 18, "USG%": 28.0}) == "Primary Scorer"
    assert GR.role_for({"PPG": 3, "USG%": 10.0}) == "Glue/Defender"


# ── calibration + rating ────────────────────────────────────────────────────────

def test_rating_centers_at_six_for_pool_mean():
    calib = {"mean": 5.0, "sd": 2.0, "role_offset": {"Glue/Defender": 0.0}}
    # a value exactly at the pool mean, high involvement → ~6.0
    r = GR.rating_from_value(5.0, "Glue/Defender", calib, involvement=100)
    assert abs(r - 6.0) < 0.1


def test_rating_monotonic_and_clamped():
    pool = [("Primary Scorer", v) for v in range(-10, 11)]
    calib = GR.calibrate(pool)
    # clamp tested without involvement shrink (shrink is exercised separately)
    lo = GR.rating_from_value(-100, "Primary Scorer", calib, involvement=None)
    hi = GR.rating_from_value(100, "Primary Scorer", calib, involvement=None)
    assert lo == 0.0 and hi == 10.0
    mid_a = GR.rating_from_value(0, "Primary Scorer", calib, involvement=None)
    mid_b = GR.rating_from_value(3, "Primary Scorer", calib, involvement=None)
    assert mid_b > mid_a


def test_involvement_shrinks_toward_six():
    calib = {"mean": 0.0, "sd": 1.0, "role_offset": {}}
    full = GR.rating_from_value(3.0, "Primary Scorer", calib, involvement=100)
    cameo = GR.rating_from_value(3.0, "Primary Scorer", calib, involvement=1)
    assert abs(cameo - 6.0) < abs(full - 6.0)      # cameo pulled toward 6.0


def test_season_bundle_injected_roles():
    m_events = []
    P1, P2 = 11, 22
    # two games, injected roles, enough involvement each
    def line(pid, gid, makes):
        out = []
        for i in range(makes):
            out.append({"game_id": gid, "event_type": "shot", "shot_type": 2,
                        "zone": "C", "shot_result": "make", "primary_player_id": pid})
        for i in range(3):     # 3 misses so even a 1-make line clears MIN_INV=4
            out.append({"game_id": gid, "event_type": "shot", "shot_type": 2,
                        "zone": "C", "shot_result": "miss", "primary_player_id": pid})
        return out
    ev = line(P1, 1, 6) + line(P2, 1, 1) + line(P1, 2, 5) + line(P2, 2, 2)
    roles = {P1: "Primary Scorer", P2: "Glue/Defender"}
    res = GR.season_game_ratings(events=ev, roles=roles)
    assert 1 in res and 2 in res
    for gid in (1, 2):
        for pid, d in res[gid].items():
            assert 0.0 <= d["rating"] <= 10.0
            assert d["role"] in GR.ROLES
    # P1 (the high scorer) should out-grade P2 in game 1
    assert res[1][P1]["rating"] > res[1][P2]["rating"]
