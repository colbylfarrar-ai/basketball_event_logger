"""
test_rapm_certainty.py — the RAPM certainty companion: does the interval the app
prints belong to the number the app prints?

RAPM ships two things per player: a RIDGE point estimate (the ranking number) and
an uncertainty companion. Those must describe the same estimator. They did not:
`sig` was computed from an unregularized OLS refit on a design that is exactly
rank-deficient by construction (every possession row carries exactly five 1s in
each block, so `col_j = Σ(defense cols) − Σ(other offense cols)`), which made the
OLS standard errors an order of magnitude wider than the ridge's own sampling
noise — and the flag they produced selected for thin samples instead of thick
ones.

These run on synthetic possessions (no DB): a seeded league where one player has a
real, large offensive effect and plays constantly, and a bench player has no
effect and barely plays.
"""
import numpy as np

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.rapm as RA


# ── synthetic league ─────────────────────────────────────────────────────────

STAR = 1          # big true offensive effect, on the floor almost always
BENCH = 19        # no true effect, a thin sample — the noise magnet
TRUE_STAR_EFFECT = 0.30      # points per possession, far above any real player


def _fake_possessions(n=12000, seed=11):
    """A two-team league where STAR really does add points and BENCH does not.

    Team A = players 0-9, team B = players 10-19. Points are drawn from the
    possession's true expectation, so the ridge has real signal to find.

    STAR plays 60% of team A's possessions, NOT 95% — a player who never sits
    has no on/off variation for the model to read, and the identifiability gate
    correctly refuses to separate him from his teammates however many
    possessions he logs. That is the real pathology on thin rosters, so the
    fixture has to avoid it deliberately to test the ordinary case.
    """
    rng = np.random.default_rng(seed)
    a_pool = list(range(0, 10))
    b_pool = list(range(10, 20))
    rows, on_off, on_def = [], {}, {}
    for i in range(n):
        # STAR plays ~60% of team A's possessions; BENCH ~6% of team B's.
        a_rest = [p for p in a_pool if p != STAR]
        if rng.random() < 0.60:
            a_five = [STAR] + list(rng.choice(a_rest, 4, replace=False))
        else:
            a_five = list(rng.choice(a_rest, 5, replace=False))
        b_rest = [p for p in b_pool if p != BENCH]
        if rng.random() < 0.06:
            b_five = [BENCH] + list(rng.choice(b_rest, 4, replace=False))
        else:
            b_five = list(rng.choice(b_rest, 5, replace=False))

        a_has_ball = (i % 2 == 0)
        off, deff = (a_five, b_five) if a_has_ball else (b_five, a_five)
        mu = 1.0 + (TRUE_STAR_EFFECT if (a_has_ball and STAR in a_five) else 0.0)
        pts = 2.0 if rng.random() < mu / 2.0 else 0.0

        rows.append((list(off), list(deff), pts))
        for p in off:
            on_off[p] = on_off.get(p, 0) + 1
        for p in deff:
            on_def[p] = on_def.get(p, 0) + 1
    return rows, on_off, on_def


def _fake_possessions_always_on(n=12000, seed=11):
    """Same league, but STAR is on the floor for 97% of team A's possessions."""
    rng = np.random.default_rng(seed)
    a_pool, b_pool = list(range(0, 10)), list(range(10, 20))
    rows, on_off, on_def = [], {}, {}
    for i in range(n):
        a_rest = [p for p in a_pool if p != STAR]
        a_five = ([STAR] + list(rng.choice(a_rest, 4, replace=False))
                  if rng.random() < 0.97
                  else list(rng.choice(a_rest, 5, replace=False)))
        b_five = list(rng.choice(b_pool, 5, replace=False))
        a_has_ball = (i % 2 == 0)
        off, deff = (a_five, b_five) if a_has_ball else (b_five, a_five)
        mu = 1.0 + (TRUE_STAR_EFFECT if (a_has_ball and STAR in a_five) else 0.0)
        pts = 2.0 if rng.random() < mu / 2.0 else 0.0
        rows.append((list(off), list(deff), pts))
        for p in off:
            on_off[p] = on_off.get(p, 0) + 1
        for p in deff:
            on_def[p] = on_def.get(p, 0) + 1
    return rows, on_off, on_def


def _solve(monkeypatch_target=None, **kw):
    """compute_rapm over the synthetic league, with the DB paths bypassed."""
    fake = _fake_possessions()
    orig = RA._possessions
    RA._possessions = lambda game_ids=None, events=None: fake
    try:
        return RA.compute_rapm(inference=True, names={}, **kw)
    finally:
        RA._possessions = orig


# ── the invariant: the flag must describe the number on screen ───────────────

def test_clears_band_is_measured_on_the_published_estimate():
    """`clears_band` must be exactly "the published RAPM beats its own 95% band".

    This is the bug: it was `abs(RAPM_ols) > 1.96*se`, testing an estimate the
    app never shows against an interval belonging to a different fit.
    """
    out = _solve()
    assert out, "synthetic league should solve"
    for pid, r in out.items():
        if r.get("RAPM_se") is None:
            continue
        expect = abs(r["RAPM"]) > 1.96 * r["RAPM_se"]
        assert r["clears_band"] == expect, (
            f"player {pid}: clears_band={r['clears_band']} but RAPM {r['RAPM']} "
            f"vs 1.96*SE {1.96 * r['RAPM_se']:.2f}")


def test_sig_is_both_conditions():
    """`sig` = clears its band AND is identified by the data, never one alone."""
    out = _solve()
    for pid, r in out.items():
        if r.get("RAPM_se") is None:
            continue
        assert r["sig"] == (r["clears_band"] and r["separable"]), (
            f"player {pid}: sig={r['sig']} clears={r['clears_band']} "
            f"separable={r['separable']}")


def test_separable_tracks_the_data_share_constant():
    out = _solve()
    for pid, r in out.items():
        if r.get("data_share") is None:
            continue
        assert r["separable"] == (r["data_share"] >= RA.MIN_DATA_SHARE)


def test_interval_brackets_the_published_estimate():
    """RAPM_lo/RAPM_hi must bracket the RAPM the app ranks on, not another fit."""
    out = _solve()
    for pid, r in out.items():
        if r.get("RAPM_lo") is None:
            continue
        assert r["RAPM_lo"] <= r["RAPM"] <= r["RAPM_hi"], (
            f"player {pid}: {r['RAPM']} outside [{r['RAPM_lo']}, {r['RAPM_hi']}]")


# ── the symptom: thick samples must separate, thin ones must not ─────────────

def test_a_heavily_observed_real_effect_is_flagged():
    """The star plays ~5,500 possessions and truly adds points — he must clear."""
    out = _solve()
    star = out[STAR]
    assert star["poss"] > 4000, f"star should be heavily observed, got {star['poss']}"
    assert star["RAPM"] > 0, f"star should read positive, got {star['RAPM']}"
    assert star["separable"] is True, (
        f"a star who sits 40% of possessions must be identifiable; "
        f"data_share {star['data_share']}")
    assert star["sig"] is True, (
        f"a {star['poss']}-possession true effect of "
        f"{star['RAPM']:+.2f} must clear its band (SE {star['RAPM_se']})")


def test_a_thin_sample_with_no_effect_is_not_flagged():
    """The bench player has no true effect and a small sample — never flagged."""
    out = _solve()
    if BENCH not in out:            # below min_poss is also an acceptable answer
        return
    assert out[BENCH]["sig"] is False, (
        f"bench ({out[BENCH]['poss']} poss) must not clear its band; "
        f"RAPM {out[BENCH]['RAPM']} SE {out[BENCH]['RAPM_se']}")


def test_a_player_who_never_sits_is_not_separable():
    """The thin-roster pathology, stated as a test.

    Possessions are not identification. A player on the floor for ~97% of their
    team's possessions has almost no on/off variation, so the ridge cannot tell
    their contribution from their four permanent teammates' — it spreads the
    TEAM's rating across all five. The estimate is reproducible (small sampling
    SE) and still not theirs, which is exactly what the data-share gate exists
    to catch and what a 1-game roster looks like on the real book.
    """
    fake = _fake_possessions_always_on()
    orig = RA._possessions
    RA._possessions = lambda game_ids=None, events=None: fake
    try:
        out = RA.compute_rapm(inference=True, names={})
    finally:
        RA._possessions = orig
    star = out[STAR]
    assert star["poss"] > 4000
    assert star["separable"] is False, (
        f"a player who never sits should not be separable; "
        f"data_share {star['data_share']}")
    assert star["sig"] is False


def test_certainty_is_not_wildly_wider_than_the_estimator_it_describes():
    """A ridge SE describes the ridge. The OLS refit on this rank-deficient design
    produced bands an order of magnitude wider than the spread of the estimates
    they were drawn on, which is what made every player read as "not separable"."""
    out = _solve()
    ses = [r["RAPM_se"] for r in out.values() if r.get("RAPM_se")]
    spread = float(np.std([r["RAPM"] for r in out.values()]))
    assert ses and spread > 0
    assert float(np.median(ses)) < 5.0 * spread, (
        f"median SE {np.median(ses):.2f} vs RAPM spread {spread:.2f} — the "
        "interval does not describe the estimator")
