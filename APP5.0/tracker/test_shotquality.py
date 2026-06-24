"""
test_shotquality.py — unit tests for the Tier-2 continuous shot-quality engine
(helpers/shotquality.py). Fits the league logistic on synthetic shots with a known
distance/contest structure and asserts the model recovers the right monotonicities,
plus SMOE sign + shrinkage behavior. No DB needed (shots passed directly).
"""
import math

import helpers.shotquality as SQ

HOOP_Y = SQ.HOOP_Y


def _synth():
    """~500 straight-on shots, 1–25 ft, make-rate decreasing with distance and lower
    when contested. player_id cycles 1/2/3."""
    shots = []
    for d in range(1, 26):
        for k in range(20):
            x, y = 0.0, HOOP_Y + d
            value = 3 if d >= 20 else 2
            guarded = (k % 2 == 0)
            rate = max(0.20, 0.72 - 0.02 * d) - (0.10 if guarded else 0.0)
            make = (k / 20.0) < rate
            shots.append({"x": x, "y": y, "value": value, "guarded": guarded,
                          "make": make, "dist": math.hypot(x, y - HOOP_Y),
                          "player_id": (d % 3) + 1})
    return shots


def test_fit_requires_min_and_variation():
    shots = _synth()
    assert SQ.fit_league_model(shots=shots[:50]) is None        # below MIN_FIT
    allmake = [{**s, "make": True} for s in shots]
    assert SQ.fit_league_model(shots=allmake) is None           # no variation
    m = SQ.fit_league_model(shots=shots)
    assert m is not None and m["n"] == len(shots) and len(m["coef"]) == 5


def test_make_prob_monotone_in_distance():
    m = SQ.fit_league_model(shots=_synth())
    near = SQ.make_prob(0.0, HOOP_Y + 3, 2, False, m)
    far = SQ.make_prob(0.0, HOOP_Y + 22, 3, False, m)
    assert near > far
    assert 0.0 <= far <= 1.0 and 0.0 <= near <= 1.0


def test_contested_penalty():
    m = SQ.fit_league_model(shots=_synth())
    openp = SQ.make_prob(0.0, HOOP_Y + 10, 2, False, m)
    guardp = SQ.make_prob(0.0, HOOP_Y + 10, 2, True, m)
    assert openp > guardp


def test_expected_points_bounds():
    m = SQ.fit_league_model(shots=_synth())
    ep2 = SQ.expected_points(0.0, HOOP_Y + 8, 2, False, m)
    ep3 = SQ.expected_points(0.0, HOOP_Y + 22, 3, False, m)
    assert 0.0 < ep2 < 2.0 and 0.0 < ep3 < 3.0


def test_player_smoe_sign_shrink_and_gate():
    base = _synth()
    m = SQ.fit_league_model(shots=base)
    extra = []
    # player 99: 30 mid makes (overperforms) ; 98: 30 mid misses ; 97: 10 makes (gated)
    for k in range(30):
        extra.append({"x": 0.0, "y": HOOP_Y + 12, "value": 2, "guarded": False,
                      "make": True, "dist": 12.0, "player_id": 99})
        extra.append({"x": 0.0, "y": HOOP_Y + 12, "value": 2, "guarded": False,
                      "make": False, "dist": 12.0, "player_id": 98})
    for k in range(10):
        extra.append({"x": 0.0, "y": HOOP_Y + 12, "value": 2, "guarded": False,
                      "make": True, "dist": 12.0, "player_id": 97})
    out = SQ.player_smoe(shots=base + extra, model=m,
                         names={99: "Over", 98: "Under", 97: "Thin"})
    assert out[99]["poe"] > 0 and out[98]["poe"] < 0
    assert abs(out[99]["poe_shrunk"]) < abs(out[99]["poe"])      # shrunk toward 0
    assert 97 not in out                                         # below MIN_SMOE_SHOTS
    assert out[99]["name"] == "Over"
