"""
rapm.py — Regularized Adjusted Plus-Minus (the gold-standard impact metric).

This is the metric DataBallR / EvanMiya are built on, and APP5.0 can compute the
real thing — not a box-score proxy — because every tracked event stores the full
10-player on-court set (game_event_lineup). RAPM solves, in one ridge regression
over every possession at once, "how many points per 100 does each player add on
offense and prevent on defense, holding their teammates AND opponents constant?"
That teammate/opponent adjustment is what raw +/- can't do.

Model (possession-level ridge):
    For each possession i, the offense scores y_i points (shot value if made,
    0 on a miss or turnover — the app's locked possession rule, FGA + TOV).
    Each player gets two coefficients: an offensive one (credited when their
    team has the ball) and a defensive one (when they're defending). Expected
    points on a possession =
        league_avg + Σ(offense players' O-coeff) + Σ(defense players' D-coeff)
    Ridge minimizes Σ(y − Xβ)² + λ‖β‖², which shrinks thin-sample players toward
    league average (0) — essential on a ~15-game book.

    ORAPM = 100·βᴼ            (points added per 100 offensive possessions)
    DRAPM = −100·βᴰ           (points prevented per 100 — sign flipped so + = good)
    RAPM  = ORAPM + DRAPM

Free-throw points are not modeled (FTs aren't possessions under the locked rule),
so RAPM measures field-goal scoring/prevention per 100 possessions. Directional
on this sample — but it is the genuine adjusted metric, λ-shrunk for safety.

Pure data layer: numpy + database.db + helpers.stats. Optionally uses
scikit-learn (RidgeCV — cross-validated penalty), which degrades gracefully if
absent. The certainty companion is closed-form numpy (see `inference`). No
streamlit.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from database.db import query
import helpers.stats as S

try:
    from sklearn.linear_model import RidgeCV as _RidgeCV
    _HAVE_SKLEARN = True
except Exception:
    _HAVE_SKLEARN = False



# Ridge penalty in "possession" units. Larger = more shrinkage toward average.
# Tuned for this small sample so stars land a few points above 0 and thin
# samples stay near 0 (see the Impact Lab caption). Exposed for re-tuning.
DEFAULT_LAMBDA = 1200.0
DEFAULT_MIN_POSS = 40   # report gate: players below this are too thin to trust

# Identifiability gate for `sig` (inference=True only) — the share of a player's
# coefficient that comes from the DATA rather than from the penalty, read off the
# diagonal of H = (X'X + λI)⁻¹X'X (whose trace is the fit's effective dof).
#
# Possessions alone do not make a player separable. A roster with one tracked
# game hands every one of its players nearly the same lineup set, so the ridge
# has no on/off variation to work with and simply spreads the TEAM's rating
# across them — estimates that are reproducible (small sampling SE) but not
# individually attributable. h measures precisely that: on the 2025-2026 book it
# correlates +0.92 with the number of distinct 5-man units a player appears in,
# and +0.87 with possessions.
#
# 0.35 is the centre of a measured plateau, not a taste: sweeping the cut over
# the girls' pool gives 34 players flagged at 0.00, 19 at 0.10, 7 at 0.20, then a
# flat {Ali Schwerdfeger, Kealey Sanders, Hannah Bond} for every cut in
# [0.30, 0.40], collapsing to none at 0.44. The boys' pool (20 games) reads none
# at any cut from 0.15 up. Re-measure this plateau before moving the number.
MIN_DATA_SHARE = 0.35

# Box-prior strength (Tier 1, ML_LAYER_ROADMAP): points-per-100 of prior impact per
# rating point above/below the ~average rating, when building the prior from
# player_ratings. Deliberately GENTLE — the prior only re-centers the ridge; the
# possession data still moves each player off it. 0.10 → a 90-rated player anchors at
# ~+4 pts/100. Tunable.
PRIOR_SCALE = 0.10


# ══════════════════════════════════════════════════════════════════════════════
#  POSSESSION EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _possessions(game_ids=None, events=None):
    """
    Build the per-possession training rows for RAPM.

    Returns (rows, on_off, on_def) where rows is a list of
    (offense_pids, defense_pids, points) for every shot/turnover possession that
    has a full on-court set, and on_off/on_def are {pid: possession count}.
    """
    if events is None:
        events = S.fetch_events(game_ids)

    # on-court sets per event: {event_id: [(pid, team_id), ...]}
    clause, params = S._game_filter(game_ids)
    lin = query(
        f"""SELECT gel.event_id eid, gel.player_id pid, gel.team_id tid
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            WHERE 1=1{clause}""",
        params,
    )
    floor = defaultdict(list)
    for r in lin:
        floor[r["eid"]].append((r["pid"], r["tid"]))

    rows = []
    on_off = defaultdict(int)
    on_def = defaultdict(int)
    for e in events:
        et = e["event_type"]
        if et not in ("shot", "turnover"):
            continue
        off_team = e["shooter_team_id"]
        if off_team is None:
            continue
        members = floor.get(e["id"])
        if not members:
            continue
        off = [pid for pid, tid in members if tid == off_team]
        deff = [pid for pid, tid in members if tid != off_team]
        if not off or not deff:
            continue
        if et == "shot":
            pts = (3 if e["shot_type"] == 3 else 2) if e["shot_result"] == "make" else 0
        else:
            pts = 0
        rows.append((off, deff, pts))
        for p in off:
            on_off[p] += 1
        for p in deff:
            on_def[p] += 1
    return rows, on_off, on_def


# ══════════════════════════════════════════════════════════════════════════════
#  RIDGE SOLVE
# ══════════════════════════════════════════════════════════════════════════════

def compute_rapm(game_ids=None, events=None, lam=None,
                 min_poss=DEFAULT_MIN_POSS, names=None, inference=False,
                 prior=None):
    """
    Compute two-way RAPM for every player from possession data.

    Returns {player_id: {"ORAPM","DRAPM","RAPM","poss","off_poss","def_poss",
    "name","team","lambda"}} for players clearing `min_poss` (offense+defense).
    Returns {} if there isn't enough data to solve.

    `lam` — ridge penalty (bigger = more regression to average). Default None
    auto-tunes it by cross-validation (scikit-learn RidgeCV) when sklearn is
    installed, else falls back to DEFAULT_LAMBDA; pass a number to force a value.
    The penalty actually used is reported per row as `lambda`.

    `prior` — optional box-impact prior {pid: (orapm_prior, drapm_prior)} in
    points-per-100 (see box_prior_from_ratings). When given, the ridge shrinks each
    player TOWARD their prior instead of toward league average (0) — the standard
    small-sample fix so stars on a ~15-game book don't collapse to average. Default
    None reproduces the shrink-to-average behaviour exactly.

    `inference=True` attaches a certainty companion per player:
        RAPM_se, RAPM_lo, RAPM_hi (95% CI), data_share, separable,
        clears_band, sig
    all measured on the SAME ridge estimate the rest of the row reports, so the
    band describes the number the app ranks on. Two conditions, kept separate so
    a caller can say WHICH one failed: `clears_band` (the estimate beats its own
    95% CI) and `separable` (data_share >= MIN_DATA_SHARE — the possessions
    actually identify this player rather than their team). `sig` is both. On a
    short book few players clear both — the honest read.

    `names` is an optional {pid: {"name","team",...}} map for labels.
    """
    rows, on_off, on_def = _possessions(game_ids, events)
    if len(rows) < 30:
        return {}

    players = sorted(set(on_off) | set(on_def))
    P = len(players)
    idx = {p: i for i, p in enumerate(players)}

    # design matrix: offense block [0..P), defense block [P..2P)
    n = len(rows)
    X = np.zeros((n, 2 * P), dtype=float)
    y = np.zeros(n, dtype=float)
    for i, (off, deff, pts) in enumerate(rows):
        for p in off:
            X[i, idx[p]] = 1.0
        for p in deff:
            X[i, P + idx[p]] = 1.0
        y[i] = pts

    ymean = y.mean()
    yc = y - ymean

    # ── box-impact prior (Tier 1): shrink TOWARD an informed center β0 rather than
    # toward 0. Ridge then minimizes ‖Xβ − yc‖² + λ‖β − β0‖²; fit the residual target
    # (yc − Xβ0) toward 0 with the same RidgeCV/closed-form path, then add β0 back.
    # prior maps a pid to (orapm_prior, drapm_prior) in pts/100; ORAPM = 100·βᴼ and
    # DRAPM = −100·βᴰ, so β0ᴼ = orapm/100 and β0ᴰ = −drapm/100. Default β0 = 0 ⇒
    # identical to shrink-to-average. ──
    beta0 = np.zeros(2 * P, dtype=float)
    if prior:
        for p, pr in prior.items():
            if p not in idx or not pr:
                continue
            opr, dpr = pr
            beta0[idx[p]] = (opr or 0.0) / 100.0
            beta0[P + idx[p]] = -(dpr or 0.0) / 100.0
    y_fit = yc - X @ beta0

    # ── ridge solve (no separate intercept — y is centered, so the average
    # possession maps to β = β0 = the player's prior, league-average when β0 = 0) ──
    if lam is None and _HAVE_SKLEARN:
        rcv = _RidgeCV(alphas=np.logspace(2.0, 4.0, 13), fit_intercept=False)
        rcv.fit(X, y_fit)
        beta = np.asarray(rcv.coef_, dtype=float) + beta0
        used_lam = float(rcv.alpha_)
    else:
        used_lam = float(lam) if lam is not None else DEFAULT_LAMBDA
        A = X.T @ X + used_lam * np.eye(2 * P)
        beta = np.linalg.solve(A, X.T @ y_fit) + beta0

    # ── certainty companion: the sampling variance OF THE RIDGE ─────────────
    # This design is EXACTLY rank-deficient by construction — every row carries
    # five 1s in the offense block and five in the defense block, so
    # col_j = Σ(defense cols) − Σ(other offense cols) for any j, and the
    # offense-all-ones minus defense-all-ones direction sits dead in the null
    # space. An unregularized refit on that matrix is not a second opinion about
    # the ridge, it is a different estimator with variance an order of magnitude
    # larger: on the 2025-2026 book the OLS bands ran a median ±34 (girls) /
    # ±40 (boys) points per 100 around estimates whose whole spread was ±12 and
    # ±4. Testing the ridge number against that band called every heavy-minutes
    # player "not separable" while flagging 42-possession noise as real.
    #
    # The ridge's own variance is closed form:
    #     β̂ = A⁻¹X'y,  A = X'X + λI   ⇒   Var(β̂) = σ²·A⁻¹(X'X)A⁻¹
    # with σ² = RSS / (n − edf) and edf = tr(X'X·A⁻¹) the effective degrees of
    # freedom the penalty actually spends. A fixed prior β0 only shifts the
    # centre, so it drops out of the variance. One extra solve of the same
    # matrix already formed — measured 0.37s on the girls' pool, and it agrees
    # with a 40-resample possession bootstrap to within ~0.5 pts/100.
    #
    # The band alone is still not the whole answer, so H's DIAGONAL comes back
    # with it as each coefficient's data share — see MIN_DATA_SHARE. Variance
    # says how much the number would move on another sample; the data share says
    # whether it is the player's number at all, or their team's.
    cov = hdiag = None
    if inference:
        try:
            XtX = X.T @ X
            A = XtX + used_lam * np.eye(2 * P)
            Ainv = np.linalg.inv(A)
            Hm = Ainv @ XtX
            resid = y_fit - X @ (beta - beta0)
            edf = float(np.trace(Hm))
            dof = max(n - edf, 1.0)
            s2 = float(resid @ resid) / dof
            cov = s2 * (Ainv @ XtX @ Ainv)
            hdiag = np.clip(np.diag(Hm), 0.0, 1.0)
        except Exception:
            cov = hdiag = None

    if names is None:
        names = {r["id"]: {"name": r["name"], "team": r["team"]}
                 for r in query(
                     """SELECT p.id, p.name, t.name team
                        FROM players p JOIN teams t ON t.id = p.team_id""")}

    out = {}
    for p in players:
        opos, dpos = on_off.get(p, 0), on_def.get(p, 0)
        if opos + dpos < min_poss:
            continue
        io, idd = idx[p], P + idx[p]
        orapm = 100.0 * beta[io]
        drapm = -100.0 * beta[idd]
        m = names.get(p, {})
        row = {
            "ORAPM": round(orapm, 2), "DRAPM": round(drapm, 2),
            "RAPM": round(orapm + drapm, 2),
            "off_poss": opos, "def_poss": dpos, "poss": opos + dpos,
            "name": m.get("name", str(p)), "team": m.get("team", ""),
            "lambda": round(used_lam, 1),
        }
        if cov is not None:
            # RAPM = 100·(βᴼ − βᴰ), so its variance is the contrast's:
            # Var(a−b) = Var(a) + Var(b) − 2Cov(a,b), scaled by 100².
            var = 1e4 * (cov[io, io] + cov[idd, idd] - 2 * cov[io, idd])
            se = float(np.sqrt(var)) if var > 0 else None
            rapm = orapm + drapm
            # a player is only as identified as their WEAKER half — a coefficient
            # the penalty is holding up on one end is not rescued by the other.
            share = (float(min(hdiag[io], hdiag[idd]))
                     if hdiag is not None else None)
            clears = bool(se and abs(rapm) > 1.96 * se)
            row.update({
                "RAPM_se": round(se, 2) if se is not None else None,
                "RAPM_lo": round(rapm - 1.96 * se, 2) if se else None,
                "RAPM_hi": round(rapm + 1.96 * se, 2) if se else None,
                "data_share": round(share, 3) if share is not None else None,
                "separable": bool(share is not None and share >= MIN_DATA_SHARE),
                "clears_band": clears,
                "sig": bool(clears and share is not None
                            and share >= MIN_DATA_SHARE),
            })
        out[p] = row
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  BOX-IMPACT PRIOR  (the informed center for box-prior RAPM)
# ══════════════════════════════════════════════════════════════════════════════

def box_prior_from_ratings(gender=None, game_ids=None, scale=PRIOR_SCALE,
                           center=50.0):
    """Build a RAPM box prior {pid: (orapm_prior, drapm_prior)} from player_ratings'
    0–100 OFFENSE / DEFENSE composites — the "shrink toward box impact" anchor that
    keeps stars off league-average on a short book.

    A rating of `center` (≈ pool average) maps to a 0 prior; each point above/below
    nudges the prior by `scale` points-per-100 (default PRIOR_SCALE=0.10 → a 90-rated
    player anchors at ~+4). Deliberately gentle: the prior only re-centers the ridge,
    the possession data still pulls each player off it. Lazy-imports player_ratings to
    keep this module's import graph light (rapm stays numpy + db only at import time).

    Pass the result as compute_rapm(..., prior=box_prior_from_ratings(gender))."""
    import helpers.player_ratings as PRt
    # include_impact=False: the box prior only needs the OFFENSE/DEFENSE composites,
    # and folding the impact pillar here would trigger a nested pure-RAPM solve just
    # to build the prior for the box-prior RAPM solve — wasteful, and circular in
    # spirit. The prior stays a pure box-composite anchor.
    rt = PRt.player_ratings(game_ids=game_ids, gender=gender, include_impact=False)
    prior = {}
    for pid, r in rt.items():
        off, dfn = r.get("OFFENSE"), r.get("DEFENSE")
        if off is None and dfn is None:
            continue
        opr = ((off - center) * scale) if off is not None else 0.0
        dpr = ((dfn - center) * scale) if dfn is not None else 0.0
        prior[pid] = (opr, dpr)
    return prior
