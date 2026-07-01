"""
shrinkage.py — Empirical-Bayes stabilization for small-sample player stats.

APP5.0 rates players on a ~15-game, single-program sample where raw rates are
noisy: a 2-for-3 night reads as 67% 3P%, a one-game opponent's USG% swings wildly.
This module pulls every rate toward the league mean by *how much evidence backs
it*, the way EvanMiya/Basketball-Index stabilize college samples. A player with
60 attempts keeps almost all of their edge; a player with 4 attempts is dragged
most of the way back to average. Nothing is invented — it is regression to the
mean with the prior strength estimated from the data itself.

Two stabilizers:

  stabilize_rate(made, att, prior_mean, k)
      Beta-binomial posterior mean = (made + k·prior_mean) / (att + k). `k` is an
      "attempts-equivalent" prior weight (k phantom attempts at the league rate).
      Use for FG% / 3P% / FT% and any make/attempt rate.

  stabilize_value(value, n, prior_mean, k)
      Same shrink for a rate that isn't a clean make/attempt count (TS%, eFG%,
      DSHOT%): treat `n` as the volume backing it (shot-equivalents, possessions).

  stabilize_index(value, games, k_games, anchor=50)
      Pull a 0-100 index (the player ratings, 50 = average) toward `anchor` by
      games played — a 1-game cameo can't post a 90 OVERALL.

`eb_prior(pairs)` estimates (prior_mean, k) for a make/attempt stat across the
pool via a beta-binomial method-of-moments fit, clamped to a sane band so a tiny
or degenerate sample can never produce a runaway prior.

Pure data layer: numpy/stdlib only, no streamlit, no DB. Feed it the rows from
player_ratings.player_stat_table (which already carry the raw counts).
"""
from __future__ import annotations


# Default prior weights when EB can't be estimated (or for non-binomial rates).
DEFAULT_RATE_K   = 12.0   # attempts-equivalent prior weight for a rate
DEFAULT_INDEX_K  = 3.0    # games-equivalent prior weight for a 0-100 index
_K_BOUNDS        = (4.0, 60.0)   # clamp EB-estimated k to this band
RATING_ANCHOR    = 50.0   # league-average value on the 0-100 rating scale


from helpers.stats import _safe   # shared definition lives in helpers.stats

try:
    from scipy.stats import norm as _norm   # exact z-quantile for any conf level
    _HAVE_SCIPY = True
except Exception:                            # scipy absent → 95% normal constant
    _HAVE_SCIPY = False


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIDENCE INTERVALS  (how wide is the uncertainty band on a small-sample rate?)
# ══════════════════════════════════════════════════════════════════════════════

def _z_for(conf):
    """Two-sided z critical value for confidence `conf` (0-1)."""
    if _HAVE_SCIPY:
        return float(_norm.ppf(0.5 + conf / 2.0))
    return 1.96  # 95% fallback when scipy is unavailable


def wilson_interval(made, att, conf=0.95):
    """Wilson score interval for a make/attempt proportion — returns (lo, hi) in
    0-1, or (None, None) with no attempts.

    The Wilson interval is the right CI for small, bounded samples (HS shot
    volumes): it never runs past [0,1] and stays sensible at 1-for-2 where the
    normal approximation breaks. Use it to show "38% (24-54%)" so a coach reads
    a hot night as the wide, uncertain band it actually is.
    """
    if not att or att <= 0:
        return (None, None)
    z = _z_for(conf)
    p = made / att
    n = float(att)
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def rating_confidence(games, poss=None, rating_sd=10.0, k_games=DEFAULT_INDEX_K,
                      conf=0.95):
    """How much to trust a player's 0-100 rating given the sample behind it.

    The OOTP "scouted" read: a lot of tracked evidence → tight band, "High"
    confidence; a one-game cameo → wide band, "Low". Ratings live on a scale
    where one SD across the pool ≈ `rating_sd` points (the SD=10 contract), so a
    player's own rating has sampling error ≈ rating_sd / √games. The CI half-width
    is that error times the two-sided z for `conf`.

    `poss` (tracked possessions / shot-equivalents behind the event-derived
    inputs) refines the evidence when given: the confidence fraction blends the
    games signal with a possession signal so a player with many games but almost
    no tracked possessions still reads as thin.

    Returns {"tier", "label", "frac", "ci", "games", "poss"} where `frac` is a
    0-1 trust fraction (drives the header meter) and `ci` is the ± half-width to
    draw as the band behind a rating bar.
    """
    g = max(0, int(games or 0))
    # games evidence → 0-1 (same shrink weight the ratings use toward 50)
    frac = g / (g + k_games) if (g + k_games) > 0 else 0.0
    if poss is not None:
        # possession evidence with a heavier phantom weight (a rating needs a
        # few dozen tracked possessions before it firms up)
        p = max(0, int(poss or 0))
        k_poss = 40.0
        frac_poss = p / (p + k_poss) if (p + k_poss) > 0 else 0.0
        frac = min(frac, frac_poss)   # the weaker signal governs
    z = _z_for(conf)
    ci = (z * rating_sd / (g ** 0.5)) if g > 0 else rating_sd * 2.5
    ci = max(2.0, min(25.0, ci))
    # Tier ladder matches player_ratings.sample_confidence (games-based) so the
    # card never shows two different confidence labels; frac/ci are the visual
    # extras that the string flag doesn't carry.
    if g >= 10:
        tier, label = "high", "High"
    elif g >= 6:
        tier, label = "medium", "Medium"
    elif g >= 3:
        tier, label = "low", "Low"
    else:
        tier, label = "very_low", "Very Low"
    return {"tier": tier, "label": label, "frac": round(frac, 3),
            "ci": round(ci, 1), "games": g,
            "poss": (int(poss) if poss is not None else None)}


# ══════════════════════════════════════════════════════════════════════════════
#  CORE STABILIZERS
# ══════════════════════════════════════════════════════════════════════════════

def stabilize_rate(made, att, prior_mean, k=DEFAULT_RATE_K):
    """Beta-binomial posterior mean for a make/attempt rate.

    Returns (made + k·prior_mean) / (att + k). With att=0 this is exactly the
    prior mean; as att grows it converges on the raw rate made/att.
    """
    denom = att + k
    return (made + k * prior_mean) / denom if denom > 0 else prior_mean


def stabilize_value(value, n, prior_mean, k=DEFAULT_RATE_K):
    """Shrink an already-computed rate `value` toward `prior_mean` by volume `n`.

    For rates without a clean integer make/attempt pair (TS%, eFG%, DSHOT%). `n`
    is the evidence behind the value (e.g. FGA+0.44·FTA for TS%, defended FGA for
    DSHOT%). Returns the prior mean when there is no volume.
    """
    if value is None:
        return None
    denom = n + k
    return (value * n + k * prior_mean) / denom if denom > 0 else prior_mean


def stabilize_index(value, games, k_games=DEFAULT_INDEX_K, anchor=RATING_ANCHOR):
    """Pull a 0-100 index toward `anchor` (50 = average) by games played.

    value' = anchor + (value − anchor)·games/(games + k_games). A full-season
    player keeps almost all of their rating; a 1-game sample is dragged most of
    the way back to league average.
    """
    if value is None:
        return None
    return anchor + (value - anchor) * _safe(games, games + k_games)


# ══════════════════════════════════════════════════════════════════════════════
#  EMPIRICAL-BAYES PRIOR  (estimate prior_mean + k from the pool)
# ══════════════════════════════════════════════════════════════════════════════

def eb_prior(pairs, k_bounds=_K_BOUNDS, default_k=DEFAULT_RATE_K):
    """
    Estimate (prior_mean, k) for a make/attempt rate from the whole pool.

    `pairs` = iterable of (made, attempts). prior_mean is the pooled rate
    (ΣM / ΣA). k (the prior's attempts-equivalent weight) comes from a
    beta-binomial method-of-moments fit:

        between-player variance  =  observed weighted variance − sampling noise
        k  =  prior_mean·(1 − prior_mean) / between_variance − 1

    Intuition: if players' rates cluster tighter than chance (skill barely
    varies), k is large → shrink hard; if they spread widely (real skill gaps),
    k is small → trust the individual. k is clamped to `k_bounds` so a thin or
    degenerate pool can't yield a runaway prior. Falls back to (0.0-safe mean,
    default_k) when there isn't enough signal.
    """
    data = [(float(m), float(n)) for m, n in pairs if n and n > 0]
    total_n = sum(n for _, n in data)
    if not data or total_n <= 0:
        return 0.0, default_k
    p = sum(m for m, _ in data) / total_n
    if p <= 0 or p >= 1 or len(data) < 3:
        return p, default_k

    # weighted variance of the per-unit rates around the pooled mean
    obs_var = sum(n * (m / n - p) ** 2 for m, n in data) / total_n
    # expected variance from sampling noise alone if everyone's true rate were p
    samp_var = p * (1 - p) * len(data) / total_n
    between = obs_var - samp_var
    if between <= 1e-9:
        # rates tighter than chance → skill ≈ constant → shrink hard
        return p, k_bounds[1]
    k = p * (1 - p) / between - 1
    k = max(k_bounds[0], min(k_bounds[1], k))
    return p, k


# ══════════════════════════════════════════════════════════════════════════════
#  CONVENIENCE: STABILIZE A WHOLE player_stat_table
# ══════════════════════════════════════════════════════════════════════════════

#: (row-rate key 0-100, made key, attempt key) for the clean binomial rates.
_RATE_SPECS = [
    ("FG%",  "FGM", "FGA"),
    ("3P%",  "3PM", "3PA"),
    ("FT%",  "FTM", "FTA"),
    ("2P%",  "2PM", "2PA"),
]


def stabilize_table(table, k_index=DEFAULT_INDEX_K):
    """
    Return {pid: {...stabilized stats...}} from a player_stat_table mapping.

    For every player it adds the regressed twins of the headline stats, named
    with an `s` prefix so the page can show raw-vs-stabilized side by side:

        sFG%, s3P%, sFT%, s2P%   (beta-binomial, EB prior per stat, 0-100)
        sTS%, seFG%              (volume-shrunk toward the pool mean, 0-100)
        sOVERALL, sOFFENSE, sDEFENSE, sPLAYMAKING, sREBOUNDING
                                (0-100 ratings pulled toward 50 by games played)
        priors                  {stat: (prior_mean_pct, k)} actually used

    Counts come straight from each row (FGM/FGA/3PM/3PA/…). Percentages in the
    table are 0-100, so the returned stabilized values are 0-100 too.
    """
    rows = list(table.values())
    if not rows:
        return {}

    # EB priors for the clean binomial rates (work in 0-1, report in 0-100)
    priors = {}
    for rate_key, mk, ak in _RATE_SPECS:
        priors[rate_key] = eb_prior((r.get(mk, 0), r.get(ak, 0)) for r in rows)

    # volume-weighted pool means for TS%/eFG% (their rates are already in rows)
    ts_mean = _safe(sum(r.get("PTS", 0) for r in rows),
                    2 * sum(r.get("FGA", 0) + 0.44 * r.get("FTA", 0) for r in rows))
    efg_num = sum(r.get("FGM", 0) + 0.5 * r.get("3PM", 0) for r in rows)
    efg_den = sum(r.get("FGA", 0) for r in rows)
    efg_mean = _safe(efg_num, efg_den)

    out = {}
    for pid, r in table.items():
        g = r.get("GP", 0) or 0
        d = {}
        for rate_key, mk, ak in _RATE_SPECS:
            pm, k = priors[rate_key]
            d["s" + rate_key] = round(
                100 * stabilize_rate(r.get(mk, 0), r.get(ak, 0), pm, k), 1)
        # TS% / eFG%: shrink the rate by its backing volume
        ts_vol = r.get("FGA", 0) + 0.44 * r.get("FTA", 0)
        efg_vol = r.get("FGA", 0)
        ts_raw = (r.get("TS%") or 0) / 100.0
        efg_raw = (r.get("eFG%") or 0) / 100.0
        d["sTS%"] = (round(100 * stabilize_value(ts_raw, ts_vol, ts_mean, DEFAULT_RATE_K), 1)
                     if ts_vol > 0 else None)
        d["seFG%"] = (round(100 * stabilize_value(efg_raw, efg_vol, efg_mean, DEFAULT_RATE_K), 1)
                      if efg_vol > 0 else None)
        # 0-100 ratings → pull toward 50 by games played
        for rk in ("OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"):
            v = r.get(rk)
            d["s" + rk] = (round(stabilize_index(v, g, k_index), 1)
                           if v is not None else None)
        d["priors"] = {rk: (round(100 * pm, 1), round(k, 1))
                       for rk, (pm, k) in priors.items()}
        out[pid] = d
    return out
