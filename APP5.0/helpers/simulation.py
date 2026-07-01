"""
simulation.py — Monte Carlo: games, brackets, and seasons.

Ratings give a single expected margin; simulation turns that into the
distributions coaches actually want — "what are our title odds?", "how many wins
should we expect?", "how often do we beat them?". Each game is modeled as a
Normal around the rating-implied margin (same family as the predictor), and we
roll it thousands of times: one game for a score distribution, a single-elim
bracket for championship odds, or a full schedule for a wins distribution
(true-talent record vs the one we actually got — a luck lens).

Vectorized with numpy for speed (10k seasons in a blink on a CPU laptop). Pure
data layer: numpy + helpers.team_ratings + helpers.predictor. No streamlit.
"""
from __future__ import annotations

import numpy as np

import helpers.team_ratings as TR
import helpers.predictor as PRED

DEFAULT_N = 20000
SD = PRED.PREGAME_SD       # single-game margin SD around the predicted margin
DEFAULT_SEED = 17


def _rating(scored, t):
    """Neutral-floor team strength in points (Rating already includes class)."""
    r = scored.get(t)
    return r["Rating"] if r else 0.0


def expected_margin(scored, a, b, home=None, hca=TR.DEFAULT_HCA):
    """Predicted margin a − b in points (+ home court if given)."""
    m = _rating(scored, a) - _rating(scored, b)
    if home == a:
        m += hca
    elif home == b:
        m -= hca
    return m


# ══════════════════════════════════════════════════════════════════════════════
#  SINGLE GAME
# ══════════════════════════════════════════════════════════════════════════════

def simulate_game(scored, a, b, home=None, n=DEFAULT_N, sd=SD, seed=DEFAULT_SEED,
                  total_points=None):
    """
    Monte Carlo a single game.

    Returns {"win_a","win_b","mean_margin","p05","p95","margins"(np array),
    "score_a","score_b"} — win odds, the margin distribution and its 5/95
    percentiles, and (if a `total_points` estimate is given) a representative
    score line. `total_points` defaults to a neutral 0 (scores omitted).
    """
    rng = np.random.default_rng(seed)
    mu = expected_margin(scored, a, b, home)
    margins = rng.normal(mu, sd, n)
    win_a = float((margins > 0).mean())
    res = {
        "win_a": round(win_a, 3), "win_b": round(1 - win_a, 3),
        "mean_margin": round(float(margins.mean()), 1),
        "p05": round(float(np.percentile(margins, 5)), 1),
        "p95": round(float(np.percentile(margins, 95)), 1),
        "margins": margins,
    }
    if total_points:
        res["score_a"] = round((total_points + mu) / 2, 1)
        res["score_b"] = round((total_points - mu) / 2, 1)
    return res


# ══════════════════════════════════════════════════════════════════════════════
#  SINGLE-ELIMINATION TOURNAMENT
# ══════════════════════════════════════════════════════════════════════════════

def _win_prob_matrix(scored, teams, sd, hca=0.0):
    """P[i, j] = probability team i beats team j (neutral)."""
    ratings = np.array([_rating(scored, t) for t in teams])
    diff = ratings[:, None] - ratings[None, :]
    # normal CDF via erf, vectorized
    from math import sqrt
    return 0.5 * (1 + _erf_vec(diff / (sd * sqrt(2))))


def _erf_vec(x):
    """Vectorized erf (Abramowitz-Stegun 7.1.26) — no scipy."""
    x = np.asarray(x, dtype=float)
    sign = np.sign(x)
    ax = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * ax)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                - 0.284496736) * t + 0.254829592) * t * np.exp(-ax * ax)
    return sign * y


def simulate_tournament(scored, teams, n=DEFAULT_N, sd=SD, seed=DEFAULT_SEED,
                        reseed=True):
    """
    Simulate a single-elimination bracket over `teams` (any list of team ids).

    Teams are seeded by Rating (best vs worst) when `reseed`, then padded with
    byes to the next power of two. Returns a list (best title odds first) of
    {team_id, name, seed, title_odds, finals_odds, champ_pct, rounds: [...]} where
    rounds[k] = probability of reaching round k+1.
    """
    teams = [t for t in teams if t in scored]
    if len(teams) < 2:
        return []
    if reseed:
        teams = sorted(teams, key=lambda t: -_rating(scored, t))

    size = 1
    while size < len(teams):
        size *= 2
    # standard 1 vs N seeding bracket order
    seed_order = _bracket_order(size)
    slots = [teams[s] if s < len(teams) else None for s in seed_order]  # None = bye

    P = _win_prob_matrix(scored, teams, sd)
    pidx = {t: i for i, t in enumerate(teams)}

    rng = np.random.default_rng(seed)
    n_rounds = size.bit_length() - 1
    # current[sim, slot] = team id (or -1 for bye/eliminated)
    cur = np.array([[(t if t is not None else -1) for t in slots]]
                   * 1, dtype=object)
    cur = np.tile(np.array([[(t if t is not None else -1) for t in slots]],
                           dtype=int), (n, 1))

    reached = {t: np.zeros(n_rounds + 1, dtype=float) for t in teams}
    # everyone present in round 0 (the field)
    for t in teams:
        reached[t][0] = n  # appearances counted, normalized later

    width = size
    for rnd in range(n_rounds):
        nxt = np.full((n, width // 2), -1, dtype=int)
        for m in range(width // 2):
            left = cur[:, 2 * m]
            right = cur[:, 2 * m + 1]
            winners = np.empty(n, dtype=int)
            # handle byes
            both = (left >= 0) & (right >= 0)
            winners[left < 0] = right[left < 0]
            winners[right < 0] = left[right < 0]
            if both.any():
                li = np.array([pidx.get(int(x), 0) for x in left[both]])
                ri = np.array([pidx.get(int(x), 0) for x in right[both]])
                p_left = P[li, ri]
                draws = rng.random(both.sum())
                w = np.where(draws < p_left, left[both], right[both])
                winners[both] = w
            nxt[:, m] = winners
        # tally who reached the next round
        for t in teams:
            reached[t][rnd + 1] = int((nxt == t).sum())
        cur = nxt
        width //= 2

    out = []
    for s, t in enumerate(teams):
        r = reached[t] / n
        out.append({
            "team_id": t, "name": scored[t]["name"], "seed": s + 1,
            "title_odds": round(float(r[n_rounds]), 4),
            "champ_pct": round(100 * float(r[n_rounds]), 1),
            "finals_odds": round(float(r[n_rounds - 1]), 4) if n_rounds >= 1 else None,
            "rounds": [round(float(x), 4) for x in r],
        })
    out.sort(key=lambda d: -d["title_odds"])
    return out


def bracket_tree(scored, teams, n=DEFAULT_N, sd=SD, seed=DEFAULT_SEED, reseed=True):
    """Roll the bracket `n` times and return a RENDER-READY probabilistic tree.

    A single-elim bracket is fixed-seeded, so every slot at a given round is only
    ever contested by the teams in that sub-bracket — which means "how often team
    t reaches round k" IS the occupancy probability of t's slot in round k. This
    fills each bracket position with its MOST-LIKELY occupant + that probability
    (plus the top alternates), the chalk-bracket a coach wants to see.

    Returns {"odds": <same list as simulate_tournament>, "cols": [...],
    "seed_of", "names", "size", "n_rounds", "n"} or None (<2 teams). `cols` is a
    list of columns left→right: cols[0] = the seeded first-round slots (size
    entries, prob 1), cols[k] = the size/2**k slots after round k, cols[-1] = the
    single champion slot. Each slot = {"team","seed","p","alts":[(tid,p),...]} or
    {"team": None} for a bye.
    """
    teams = [t for t in teams if t in scored]
    if len(teams) < 2:
        return None
    if reseed:
        teams = sorted(teams, key=lambda t: -_rating(scored, t))
    size = 1
    while size < len(teams):
        size *= 2
    seed_order = _bracket_order(size)
    slots = [teams[s] if s < len(teams) else None for s in seed_order]
    seed_of = {t: i + 1 for i, t in enumerate(teams)}
    names = {t: scored[t]["name"] for t in teams}

    P = _win_prob_matrix(scored, teams, sd)
    pidx = {t: i for i, t in enumerate(teams)}
    rng = np.random.default_rng(seed)
    n_rounds = size.bit_length() - 1
    cur = np.tile(np.array([[(t if t is not None else -1) for t in slots]],
                           dtype=int), (n, 1))

    reached = {t: np.zeros(n_rounds + 1, dtype=float) for t in teams}
    for t in teams:
        reached[t][0] = n

    def _slot(tid, p):
        return {"team": (tid if tid is not None and tid >= 0 else None),
                "seed": seed_of.get(tid), "p": round(float(p), 4), "alts": []}

    # column 0 — the deterministic seeded first-round slots
    cols = [[_slot(t, 1.0) for t in slots]]

    width = size
    for rnd in range(n_rounds):
        nxt = np.full((n, width // 2), -1, dtype=int)
        col = []
        for m in range(width // 2):
            left, right = cur[:, 2 * m], cur[:, 2 * m + 1]
            winners = np.empty(n, dtype=int)
            both = (left >= 0) & (right >= 0)
            winners[left < 0] = right[left < 0]
            winners[right < 0] = left[right < 0]
            if both.any():
                li = np.array([pidx.get(int(x), 0) for x in left[both]])
                ri = np.array([pidx.get(int(x), 0) for x in right[both]])
                draws = rng.random(both.sum())
                winners[both] = np.where(draws < P[li, ri], left[both], right[both])
            nxt[:, m] = winners
            # occupancy distribution for this slot
            vals, counts = np.unique(winners[winners >= 0], return_counts=True)
            order = np.argsort(-counts)
            ranked = [(int(vals[i]), counts[i] / n) for i in order]
            if ranked:
                s = _slot(ranked[0][0], ranked[0][1])
                s["alts"] = [(int(t), round(float(p), 4)) for t, p in ranked[1:3]]
                col.append(s)
            else:
                col.append(_slot(None, 0.0))
        cols.append(col)
        for t in teams:
            reached[t][rnd + 1] = int((nxt == t).sum())
        cur = nxt
        width //= 2

    odds = []
    for s, t in enumerate(teams):
        r = reached[t] / n
        odds.append({
            "team_id": t, "name": names[t], "seed": s + 1,
            "title_odds": round(float(r[n_rounds]), 4),
            "champ_pct": round(100 * float(r[n_rounds]), 1),
            "finals_odds": round(float(r[n_rounds - 1]), 4) if n_rounds >= 1 else None,
            "rounds": [round(float(x), 4) for x in r],
        })
    odds.sort(key=lambda d: -d["title_odds"])
    return {"odds": odds, "cols": cols, "seed_of": seed_of, "names": names,
            "size": size, "n_rounds": n_rounds, "n": n}


def _bracket_order(size):
    """Seed positions for a standard single-elim bracket of `size` (power of 2)."""
    order = [0, 1]
    while len(order) < size:
        m = len(order) * 2
        order = [v for s in order for v in (s, m - 1 - s)]
    return order


# ══════════════════════════════════════════════════════════════════════════════
#  SEASON SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

def simulate_season(scored, schedule, n=DEFAULT_N, sd=SD, seed=DEFAULT_SEED):
    """
    Re-simulate a set of games to get each team's WIN distribution.

    `schedule` = list of (team_a, team_b, home) tuples (home = a, b, or None).
    Returns {team_id: {"name","exp_wins","games","p_wins": {k: prob},
    "win_dist": np array of length games+1}} — the true-talent record the ratings
    imply, which you can compare to the actual record to see who over/under-
    performed. Vectorized: all sims for a game resolved at once.
    """
    rng = np.random.default_rng(seed)
    games_by_team = {}
    wins = {}
    counts = {}
    for a, b, home in schedule:
        if a not in scored or b not in scored:
            continue
        mu = expected_margin(scored, a, b, home)
        pa = 0.5 * (1 + _erf_vec(np.array([mu / (sd * (2 ** 0.5))]))[0])
        draws = rng.random(n)
        a_win = draws < pa
        for t, w in ((a, a_win), (b, ~a_win)):
            if t not in wins:
                wins[t] = np.zeros(n, dtype=int)
                counts[t] = 0
            wins[t] += w.astype(int)
            counts[t] += 1

    out = {}
    for t, w in wins.items():
        g = counts[t]
        dist = np.bincount(w, minlength=g + 1)[:g + 1] / n
        pw = {int(k): round(float(v), 4) for k, v in enumerate(dist) if v > 0.001}
        out[t] = {
            "name": scored[t]["name"], "games": g,
            "exp_wins": round(float(w.mean()), 1),
            "p_wins": pw, "win_dist": dist,
        }
    return out


def schedule_from_results(gender=None):
    """
    Build a (team_a, team_b, home) schedule from finished games for season sim.
    team_a = home (team1). Each completed game contributes one matchup.
    """
    from database.db import query
    clause = ("WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL "
              "AND g.season = 'Current'")   # active season only — never blend seasons
    params = []
    if gender:
        clause += " AND t1.gender = ?"
        params.append(gender)
    rows = query(
        f"""SELECT g.team1_id a, g.team2_id b FROM games g
            JOIN teams t1 ON t1.id=g.team1_id {clause}""", tuple(params))
    return [(r["a"], r["b"], r["a"]) for r in rows]
