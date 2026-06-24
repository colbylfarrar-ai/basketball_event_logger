"""
test_tier1_engine.py — smoke + unit tests for the Tier-1 ML-layer engine helpers
(courtside, selfscout, coverage) and the rapm box-prior extension. Pure-math where
possible so they run without a populated DB; DB-touching calls are only checked to
import and not raise.
"""
import inspect

import helpers.courtside as CS
import helpers.selfscout as SS
import helpers.coverage as CV
import helpers.rapm as RA


# ── courtside: leverage ──────────────────────────────────────────────────────
def test_leverage_higher_late_than_early():
    end = CS.WP.GAME_SECONDS
    early = CS.leverage_now(0, end - 60, end)      # 1 min in, tied
    late = CS.leverage_now(0, 20, end)             # 20s left, tied
    assert late["li"] > early["li"]
    assert 0.0 <= early["wp"] <= 1.0 and 0.0 <= late["wp"] <= 1.0


def test_leverage_tier_labels():
    end = CS.WP.GAME_SECONDS
    # tied with seconds left = a season-defining possession
    assert CS.leverage_now(0, 8, end)["tier"] == "🔥 Season-defining"
    # 30-point lead at the half = low leverage
    assert CS.leverage_now(30, end // 2, end)["tier"] == "Low"


def test_leverage_norm():
    end = CS.WP.GAME_SECONDS
    r = CS.leverage_now(0, 20, end, li_mean=0.05)
    assert r["li_norm"] == round(r["li"] / 0.05, 2)


# ── courtside: comeback gauge ────────────────────────────────────────────────
def test_comeback_none_when_not_trailing():
    assert CS.comeback_gauge(5, 120) is None
    assert CS.comeback_gauge(0, 120) is None


def test_comeback_bigger_deficit_needs_more():
    small = CS.comeback_gauge(-4, 240)
    big = CS.comeback_gauge(-16, 240)
    assert small and big
    assert big["req_ppp_margin"] > small["req_ppp_margin"]
    assert big["deficit"] == 16 and small["deficit"] == 4


def test_comeback_out_of_possessions():
    r = CS.comeback_gauge(-10, 5, sec_per_poss=15.0)
    assert r["your_poss"] < 1
    assert r["label"] == "Out of possessions"


# ── courtside: foul up 3 + late_game dispatch ────────────────────────────────
def test_foul_up_3_shape():
    r = CS.foul_up_3(10)
    assert r["recommend"] in ("foul", "guard")
    assert 0.0 <= r["guard_wp"] <= 1.0 and 0.0 <= r["foul_wp"] <= 1.0
    # fouling should not be worse than guarding when there's time (it denies the 3)
    assert r["foul_wp"] >= r["guard_wp"]


def test_late_game_dispatch():
    end = CS.WP.GAME_SECONDS
    up3 = CS.late_game(3, 20, end, on_defense=True)
    assert "foul_up_3" in up3 and "wp" in up3
    trailing = CS.late_game(-6, 120, end)
    assert "comeback" in trailing and trailing["comeback"] is not None
    cruise = CS.late_game(12, 200, end)
    assert "foul_up_3" not in cruise and cruise.get("comeback") is None


# ── selfscout: entropy index ─────────────────────────────────────────────────
def test_entropy_extremes():
    assert SS._entropy_index([1.0]) == 0.0          # one set every time
    assert SS._entropy_index([]) == 0.0
    assert SS._entropy_index([0.5, 0.5]) == 100.0   # perfectly balanced 2-way
    assert SS._entropy_index([0.25] * 4) == 100.0   # balanced 4-way


def test_entropy_monotonic_concentration():
    balanced = SS._entropy_index([0.34, 0.33, 0.33])
    skewed = SS._entropy_index([0.8, 0.1, 0.1])
    assert balanced > skewed


def test_scoutability_from_rows():
    rows = [{"label": "Iso", "share": 0.6, "poss": 30},
            {"label": "PnR", "share": 0.4, "poss": 20}]
    core = SS._scoutability_from_rows(rows)
    assert core["top_set"] == "Iso" and core["top_share"] == 60.0
    assert core["n_sets"] == 2
    assert core["predictability"] == round(100 - core["entropy"], 1)


# ── coverage: pct + label ────────────────────────────────────────────────────
def test_coverage_pct_and_label():
    assert CV._pct(0, 0) is None
    assert CV._pct(8, 10) == 80.0
    assert CV._label(None) == "none"
    assert CV._label(90) == "strong"
    assert CV._label(50) == "partial"
    assert CV._label(10) == "sparse"


# ── rapm box-prior: signature + builder presence ─────────────────────────────
def test_rapm_accepts_prior_kwarg():
    sig = inspect.signature(RA.compute_rapm)
    assert "prior" in sig.parameters
    assert callable(RA.box_prior_from_ratings)
    assert RA.PRIOR_SCALE > 0


def test_prior_none_matches_default_solve():
    # On whatever the local DB holds, prior=None must equal the legacy call exactly.
    a = RA.compute_rapm()
    b = RA.compute_rapm(prior=None)
    assert a == b


# ── DB-touching smoke (don't raise on the local DB, however populated) ───────
def test_db_calls_smoke():
    cov = CV.gender_coverage()
    assert "signals" in cov and "overall_pct" in cov
    # selfscout over an arbitrary team id should not raise (returns thin/none if empty)
    r = SS.scoutability(1)
    assert "predictability" in r and "rated" in r
