"""
shotquality.py — continuous league shot-quality (xPP-Q) + per-player SMOE (Tier 2).

Upgrades the radial distance×value make-rate (stats.distance_make_model /
expected_points_at, a binned lookup) to a CONTINUOUS league make-probability model on
the real tap-captured (x, y): a ridge-penalized logistic on

    [ distance, distance², is_three, contested, |angle-from-straight-on| ]

so it knows a corner three beats a same-distance wing two, and a guarded shot is worth
less than an open one — context the distance bins can't carry. Expected points =
make_prob × shot value. Then each player is scored by SMOE — points scored OVER what
the league model expected from their exact shots — empirical-shrunk toward 0 by volume
so a hot 12-shot sample doesn't masquerade as elite shot-making.

LEAGUE-POOLED ONLY (never fit per team — tens of games per team is far too thin); the
pooled fit is what makes a ~5-feature logistic safe at this scale, and consumers should
gate on MIN_FIT. Pure numpy (a tiny IRLS solver, no sklearn dependency → no silent
graceful-degradation), reuses helpers.stats.located_shots. No streamlit.
"""
from __future__ import annotations

import math

import numpy as np

import helpers.stats as S


HOOP_Y = 5.25              # rim centre (matches court_geom.HOOP_Y; literal to avoid
                           # importing court_geom's matplotlib stack at module load)
MIN_FIT = 150              # min located shots to fit; below it return None (fall back)
DEFAULT_LAMBDA = 2.0       # L2 penalty on the standardized non-intercept coefficients
SMOE_K = 60                # shrink constant: a player's POE is trusted at ~n/(n+60)
MIN_SMOE_SHOTS = 15        # don't report SMOE below this many located shots


# ── feature row for one shot (order matters; mirrors the docstring) ─────────────
def _feat(x, y, value, guarded):
    dist = math.hypot(x, y - HOOP_Y)
    angle = abs(math.atan2(x, max(y - HOOP_Y, 1e-4)))     # 0 = straight on, ~1.57 = corner
    return (dist, dist * dist / 100.0,
            1.0 if value == 3 else 0.0,
            1.0 if guarded else 0.0,
            angle)


def _fit_logistic(X, y, lam, iters=40):
    """Ridge-penalized logistic via IRLS / Newton (intercept unpenalized). X is
    standardized (n×p, no intercept column); returns (intercept, coef[p])."""
    n, p = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(p + 1)
    pen = np.full(p + 1, float(lam))
    pen[0] = 0.0                                   # never penalize the intercept
    for _ in range(iters):
        eta = np.clip(Xb @ beta, -30.0, 30.0)
        mu = 1.0 / (1.0 + np.exp(-eta))
        w = np.clip(mu * (1.0 - mu), 1e-6, None)
        grad = Xb.T @ (y - mu) - pen * beta
        H = (Xb.T * w) @ Xb + np.diag(pen)
        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            break
        beta = beta + step
        if np.max(np.abs(step)) < 1e-7:
            break
    return float(beta[0]), beta[1:]


def fit_league_model(gender=None, game_ids=None, events=None, shots=None,
                     lam=DEFAULT_LAMBDA):
    """Fit the league make-probability logistic over every located shot. Returns a
    model dict {"intercept","coef","mean","std","n","lam"} or None if there are
    fewer than MIN_FIT located shots or the outcomes don't vary (all makes/misses).

    LEAGUE-POOLED: pass `shots` (a located_shots list) or let it pull the gender's
    tracked located shots once. Never fit on a single team."""
    if shots is None:
        ev = events
        if ev is None:
            import helpers.playtypes as PT
            gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
            ev = S.fetch_events(gids) if gids else []
        shots = S.located_shots(events=ev)
    if len(shots) < MIN_FIT:
        return None

    X = np.array([_feat(s["x"], s["y"], s["value"], s["guarded"]) for s in shots],
                 dtype=float)
    y = np.array([1.0 if s["make"] else 0.0 for s in shots], dtype=float)
    if y.min() == y.max():            # no variation → can't fit
        return None

    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-9] = 1.0
    Xs = (X - mean) / std
    intercept, coef = _fit_logistic(Xs, y, lam)
    return {"intercept": intercept, "coef": coef, "mean": mean, "std": std,
            "n": len(shots), "lam": lam}


def make_prob(x, y, value, guarded, model):
    """League make probability for a shot at (x, y) of the given value, contested or
    not, under `model`. Returns a probability in [0, 1]."""
    f = np.array(_feat(x, y, value, guarded), dtype=float)
    z = (f - model["mean"]) / model["std"]
    eta = model["intercept"] + float(z @ model["coef"])
    return 1.0 / (1.0 + math.exp(-max(min(eta, 30.0), -30.0)))


def expected_points(x, y, value, guarded, model):
    """Expected points = league make prob × shot value (the continuous xPP-Q analog
    of stats.expected_points_at, but context-aware)."""
    return make_prob(x, y, value, guarded, model) * value


def expected_points_shot(shot, model):
    """expected_points for a located_shots() dict."""
    return expected_points(shot["x"], shot["y"], shot["value"], shot["guarded"], model)


def player_smoe(gender=None, game_ids=None, events=None, shots=None, model=None,
                min_shots=MIN_SMOE_SHOTS, names=None):
    """Per-player SMOE — points scored OVER the league-expected from their exact
    shots, empirical-shrunk toward 0 by volume.

    Returns {player_id: {"n","pps","xpps","poe","poe_shrunk","name"}}:
      pps         points per shot actually scored
      xpps        league-expected points per shot for those exact shots (xPP-Q)
      poe         pps − xpps  (raw shot-making over expected, per shot)
      poe_shrunk  poe · n/(n+SMOE_K)  (regressed to 0 for small samples)
    Players below `min_shots` located attempts are dropped. The model is fit league-
    wide here if not supplied."""
    if shots is None:
        ev = events
        if ev is None:
            import helpers.playtypes as PT
            gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
            ev = S.fetch_events(gids) if gids else []
        shots = S.located_shots(events=ev)
    if model is None:
        model = fit_league_model(shots=shots)
    if model is None:
        return {}

    agg = {}
    for s in shots:
        pid = s["player_id"]
        if pid is None:
            continue
        a = agg.setdefault(pid, {"n": 0, "pts": 0.0, "xpts": 0.0})
        a["n"] += 1
        a["pts"] += s["value"] if s["make"] else 0.0
        a["xpts"] += expected_points_shot(s, model)

    if names is None:
        from database.db import query
        names = {r["id"]: r["name"] for r in query("SELECT id, name FROM players")}

    out = {}
    for pid, a in agg.items():
        if a["n"] < min_shots:
            continue
        pps = a["pts"] / a["n"]
        xpps = a["xpts"] / a["n"]
        poe = pps - xpps
        out[pid] = {
            "n": a["n"], "pps": round(pps, 3), "xpps": round(xpps, 3),
            "poe": round(poe, 3),
            "poe_shrunk": round(poe * a["n"] / (a["n"] + SMOE_K), 3),
            "name": names.get(pid, str(pid)),
        }
    return out
