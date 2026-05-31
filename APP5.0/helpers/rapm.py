"""
rapm.py — Regularized Adjusted Plus-Minus (the gold-standard impact metric).

This is the metric DataBallR / EvanMiya are built on, and APP4.0 can compute the
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

Pure data layer: numpy + database.db + helpers.stats only. No streamlit, no scipy.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from database.db import query
import helpers.stats as S


# Ridge penalty in "possession" units. Larger = more shrinkage toward average.
# Tuned for this small sample so stars land a few points above 0 and thin
# samples stay near 0 (see the Impact Lab caption). Exposed for re-tuning.
DEFAULT_LAMBDA = 1200.0
DEFAULT_MIN_POSS = 40   # report gate: players below this are too thin to trust


def _safe(num, den):
    return num / den if den else 0.0


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

def compute_rapm(game_ids=None, events=None, lam=DEFAULT_LAMBDA,
                 min_poss=DEFAULT_MIN_POSS, names=None):
    """
    Compute two-way RAPM for every player from possession data.

    Returns {player_id: {"ORAPM","DRAPM","RAPM","poss","off_poss","def_poss",
    "name","team"}} for players clearing `min_poss` (offense+defense), sorted
    callers can re-sort. Returns {} if there isn't enough data to solve.

    `lam` is the ridge penalty (bigger = more regression to average). `names`
    is an optional {pid: {"name","team",...}} map for labels (fetched if None).
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

    # ridge normal equations (do not penalize via a separate intercept — y is
    # centered, so the average possession maps to β = 0 = league-average player)
    A = X.T @ X + lam * np.eye(2 * P)
    b = X.T @ yc
    beta = np.linalg.solve(A, b)

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
        orapm = 100.0 * beta[idx[p]]
        drapm = -100.0 * beta[P + idx[p]]
        m = names.get(p, {})
        out[p] = {
            "ORAPM": round(orapm, 2), "DRAPM": round(drapm, 2),
            "RAPM": round(orapm + drapm, 2),
            "off_poss": opos, "def_poss": dpos, "poss": opos + dpos,
            "name": m.get("name", str(p)), "team": m.get("team", ""),
        }
    return out
