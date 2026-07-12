"""
backtest.py — out-of-sample validation harness for the full-season recalibration.

Every weight change in the recal project (spec: docs/superpowers/specs/
2026-07-11-full-season-recalibration-design.md) must beat — or at worst tie —
the incumbent constants on these held-out targets before it ships. The harness
never invents data: it hides real games from the engines and scores how well
the engine-under-test predicts them.

Targets
    T1a  Adair-fold margin MAE      team_ratings.score_ratings built without a
                                    fold of Adair games; predicted margin =
                                    Rating diff vs the actual held-out margins.
    T1b  league-tail margin MAE     same, holding out the latest ~10% of ALL
                                    dated finished games (league-wide signal).
    T2   rating validity            player_ratings OVERALL on train games vs
                                    held-out Game Score per game (Spearman,
                                    players on the fold team).
    T3   projection error           projection.project_roster on train games vs
                                    held-out observed shooting/ball-security
                                    rates, volume-weighted |error| per stat.
    T4   shrink-k LOGO              leave-one-game-out over EVERY tracked game
                                    (all teams, incl. 1-3 game thin teams):
                                    predict a player's held-out Game Score from
                                    their train GS/G shrunk toward the pool mean
                                    by a candidate k — the direct instrument for
                                    the index-shrink constants.

Data facts this is built around (measured 2026-07-12 on the prod snapshot):
29 tracked games total, 23 of them Adair Girls; zero manual boxes; the season
label is '2025-2026' (post-rollover — 'Current' holds nothing, so every query
here scopes the season EXPLICITLY and passes explicit game_ids, never None).

Usage
    python -m tools.backtest              # human report, incumbent constants
    python -m tools.backtest --json       # machine-readable
Importable
    run_all(constants=None) -> dict       # sweep entry point
    override(constants)                   # context manager for constant configs
"""
from __future__ import annotations

import argparse
import contextlib
import json
from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.shrinkage as SHR
import helpers.player_ratings as PR
import helpers.team_ratings as TR
import helpers.projection as PJ

SEASON = "2025-2026"
N_FOLDS = 4
LEAGUE_TAIL_FRAC = 0.10

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANT REGISTRY  (the sweep's write surface)
# ══════════════════════════════════════════════════════════════════════════════
# Dotted name -> (module, attr). projection.K is BOUND AT IMPORT from
# shrinkage.DEFAULT_RATE_K — changing the shrinkage value at runtime does NOT
# propagate, so sweeps must set projection.K explicitly too.
REGISTRY = {
    "shrinkage.DEFAULT_RATE_K":            (SHR, "DEFAULT_RATE_K"),
    "shrinkage.DEFAULT_INDEX_K":           (SHR, "DEFAULT_INDEX_K"),
    "player_ratings.RATING_K_GAMES":       (PR, "RATING_K_GAMES"),
    "player_ratings.MANUAL_GAME_WEIGHT":   (PR, "MANUAL_GAME_WEIGHT"),
    "player_ratings.MIN_POOL_FOR_RESTD":   (PR, "MIN_POOL_FOR_RESTD"),
    "projection.K":                        (PJ, "K"),
    "projection.ARCHETYPE_MIN_OPP":        (PJ, "ARCHETYPE_MIN_OPP"),
    "team_ratings.DEFAULT_REG":            (TR, "DEFAULT_REG"),
    "team_ratings.DEFAULT_SOS_WEIGHT":     (TR, "DEFAULT_SOS_WEIGHT"),
}


def snapshot_constants():
    return {name: getattr(mod, attr) for name, (mod, attr) in REGISTRY.items()}


def clear_caches():
    """Engines memoize by data fingerprint, which doesn't see constant changes —
    flush between configs or a sweep scores stale numbers."""
    PR._RAPM_MEMO.clear()
    PR._OPP_RATINGS_MEMO.clear()


@contextlib.contextmanager
def override(constants):
    """Temporarily apply {dotted_name: value}; always restores on exit."""
    saved = snapshot_constants()
    try:
        for name, val in (constants or {}).items():
            mod, attr = REGISTRY[name]
            setattr(mod, attr, val)
        clear_caches()
        yield
    finally:
        for name, val in saved.items():
            mod, attr = REGISTRY[name]
            setattr(mod, attr, val)
        clear_caches()


# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════

def finished_games(gender=None, season=SEASON):
    """Dated, scored games — the margin-prediction universe."""
    clause = ("WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL "
              "AND g.season=? AND g.date IS NOT NULL")
    params = [season]
    if gender:
        clause += " AND t1.gender=?"
        params.append(gender)
    return query(
        f"""SELECT g.id, g.date, g.team1_id t1, g.team2_id t2,
                   g.home_score hs, g.away_score aws, g.tracked
            FROM games g JOIN teams t1 ON t1.id=g.team1_id
            {clause} ORDER BY g.date, g.id""", tuple(params))


def tracked_games(season=SEASON):
    return [g for g in finished_games(season=season) if g["tracked"]]


def focus_team(season=SEASON):
    """(team_id, gender, n) for the deepest-tracked team — the fold team."""
    rows = query(
        """SELECT t.id tid, t.gender gender, COUNT(*) n FROM games g
           JOIN teams t ON t.id IN (g.team1_id, g.team2_id)
           WHERE g.tracked=1 AND g.season=? GROUP BY t.id
           ORDER BY n DESC LIMIT 1""", (season,))
    r = rows[0]
    return r["tid"], r["gender"], r["n"]


def make_folds(games, n_folds=N_FOLDS):
    """Interleaved date-ordered folds: fold i holds out games i, i+n, i+2n…
    Keeps every fold's train set spanning the whole season (early+late), which
    matters because rosters and roles drift across a HS season."""
    folds = [[] for _ in range(n_folds)]
    for i, g in enumerate(games):
        folds[i % n_folds].append(g)
    return folds


def _team_gp(games):
    gp = defaultdict(int)
    for g in games:
        gp[g["t1"]] += 1
        gp[g["t2"]] += 1
    return gp


# ══════════════════════════════════════════════════════════════════════════════
#  T1 — TEAM MARGIN
# ══════════════════════════════════════════════════════════════════════════════

def _margin_mae(train_ids, heldout, gender, reg=None, sos_weight=None,
                min_train_gp=2, train_gp=None):
    """Build score_ratings on train_ids; MAE of (Rating diff) vs actual margin
    over held-out games where both teams have >= min_train_gp train games (a
    0-1 game team's rating is pure prior — scoring it just measures the prior).
    Returns (mae, baseline_mae, n)."""
    kw = {}
    if reg is not None:
        kw["reg"] = reg
    if sos_weight is not None:
        kw["sos_weight"] = sos_weight
    R = TR.score_ratings(gender=gender, season=SEASON,
                         game_ids=list(train_ids), **kw)
    errs, base = [], []
    for g in heldout:
        r1, r2 = R.get(g["t1"]), R.get(g["t2"])
        if r1 is None or r2 is None:
            continue
        if train_gp is not None and (train_gp[g["t1"]] < min_train_gp
                                     or train_gp[g["t2"]] < min_train_gp):
            continue
        actual = g["hs"] - g["aws"]
        errs.append(abs((r1["Rating"] - r2["Rating"]) - actual))
        base.append(abs(actual))
    n = len(errs)
    return ((sum(errs) / n, sum(base) / n, n) if n else (None, None, 0))


def t1_adair(folds, all_finished, gender, reg=None, sos_weight=None):
    """Margin MAE over the Adair folds (pooled across folds)."""
    tot_e = tot_b = tot_n = 0.0
    for fold in folds:
        held_ids = {g["id"] for g in fold}
        train = [g for g in all_finished if g["id"] not in held_ids]
        gp = _team_gp(train)
        mae, bmae, n = _margin_mae([g["id"] for g in train], fold, gender,
                                   reg=reg, sos_weight=sos_weight, train_gp=gp)
        if n:
            tot_e += mae * n
            tot_b += bmae * n
            tot_n += n
    if not tot_n:
        return {"mae": None, "baseline": None, "n": 0}
    return {"mae": round(tot_e / tot_n, 2), "baseline": round(tot_b / tot_n, 2),
            "n": int(tot_n)}


def t1_league(gender, reg=None, sos_weight=None, tail=LEAGUE_TAIL_FRAC):
    """Margin MAE holding out the latest `tail` fraction of all dated games."""
    allg = finished_games(gender=gender)
    cut = max(1, int(len(allg) * tail))
    train, held = allg[:-cut], allg[-cut:]
    gp = _team_gp(train)
    mae, bmae, n = _margin_mae([g["id"] for g in train], held, gender,
                               reg=reg, sos_weight=sos_weight, train_gp=gp)
    return {"mae": (round(mae, 2) if mae is not None else None),
            "baseline": (round(bmae, 2) if bmae is not None else None), "n": n}


# ══════════════════════════════════════════════════════════════════════════════
#  T2 — RATING VALIDITY   /   T3 — PROJECTION ERROR
# ══════════════════════════════════════════════════════════════════════════════

def _heldout_lines(held_ids):
    """{pid: {'gsg','gp',box}} over the held-out games (events are the truth)."""
    boxes = S.aggregate_player_boxes(list(held_ids))
    gp = S.games_played(list(held_ids))
    out = {}
    for pid, b in boxes.items():
        g = gp.get(pid, 0)
        if g:
            out[pid] = {"gsg": S.game_score(b) / g, "gp": g, "box": b}
    return out


def _spearman(pairs):
    """Spearman rho over [(a, b), …]; None under 4 pairs."""
    if len(pairs) < 4:
        return None
    try:
        from scipy.stats import spearmanr
        rho = spearmanr([a for a, _ in pairs], [b for _, b in pairs]).statistic
        return None if rho != rho else round(float(rho), 3)   # NaN guard
    except Exception:
        return None


def t2_rating_validity(folds, tracked, focus_tid, gender):
    """Train-side OVERALL vs held-out GS/G, focus-team players, pooled folds.

    Also returns raw (stabilize=False) validity so the shrink's *contribution*
    is visible: stabilized beating raw = the shrink constants are earning keep.
    """
    stab_pairs, raw_pairs = [], []
    for fold in folds:
        held_ids = {g["id"] for g in fold}
        train_ids = [g["id"] for g in tracked if g["id"] not in held_ids]
        held = _heldout_lines(held_ids)
        for stab, sink in ((True, stab_pairs), (False, raw_pairs)):
            R = PR.player_ratings(game_ids=train_ids, gender=gender,
                                  season=SEASON, stabilize=stab)
            for pid, row in R.items():
                h = held.get(pid)
                if (h and h["gp"] >= 2 and row.get("team_id") == focus_tid
                        and row.get("OVERALL") is not None):
                    sink.append((row["OVERALL"], h["gsg"]))
    return {"rho_stabilized": _spearman(stab_pairs),
            "rho_raw": _spearman(raw_pairs), "n": len(stab_pairs)}


# projection stats we can honestly recompute from a held-out event box
# (out_name, heldout_fn(box) -> rate in the table's 0-100 unit, volume_fn)
def _ho_3p(b):
    return 100.0 * b["3PM"] / b["3PA"] if b["3PA"] else None


_T3_STATS = [
    ("eFG%", lambda b: 100.0 * S.efg(b) if b["FGA"] else None,
     lambda b: b["FGA"]),
    ("TS%",  lambda b: 100.0 * S.ts(b) if (b["FGA"] or b["FTA"]) else None,
     lambda b: b["FGA"] + 0.44 * b["FTA"]),
    ("3P%",  _ho_3p, lambda b: b["3PA"]),
]


def t3_projection(folds, tracked, focus_tid, gender):
    """Volume-weighted |projected − held-out observed| per stat, pooled folds.
    Baseline = projecting the league prior for everyone (skill-blind). The
    engine earns its keep only if it beats the prior."""
    err = defaultdict(float)
    base = defaultdict(float)
    vol = defaultdict(float)
    for fold in folds:
        held_ids = {g["id"] for g in fold}
        train_ids = [g["id"] for g in tracked if g["id"] not in held_ids]
        held = _heldout_lines(held_ids)
        try:
            proj = PJ.project_roster(focus_tid, gender=gender,
                                     game_ids=train_ids, season=SEASON)
        except Exception:
            continue
        for pid, prow in (proj or {}).items():
            h = held.get(pid)
            if not h:
                continue
            for name, ho_fn, vol_fn in _T3_STATS:
                srow = (prow.get("stats") or {}).get(name)
                actual = ho_fn(h["box"])
                w = vol_fn(h["box"])
                if srow is None or actual is None or not w:
                    continue
                err[name] += abs(srow["proj"] - actual) * w
                pr = srow.get("prior")
                base[name] += (abs(pr - actual) * w if pr is not None
                               else abs(srow["proj"] - actual) * w)
                vol[name] += w
    out = {}
    for name, _f, _v in _T3_STATS:
        out[name] = ({"mae": round(err[name] / vol[name], 2),
                      "prior_mae": round(base[name] / vol[name], 2),
                      "vol": round(vol[name])} if vol[name] else None)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  T4 — SHRINK-K LOGO  (the direct instrument for the index-shrink constants)
# ══════════════════════════════════════════════════════════════════════════════

def t4_shrink_logo(tracked, k_grid=(0.0, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0)):
    """Leave-one-game-out over EVERY tracked game (all teams — this is the one
    target where the 1-5 game thin teams contribute real evidence).

    For each held-out game and player in it: predict their Game Score that game
    as  anchor + (train_GS/G − anchor)·gp/(gp+k)  where anchor is the train
    pool's GP-weighted mean GS/G. MAE per candidate k. The k that wins is the
    evidence-optimal index shrink for THIS data depth — read against
    shrinkage.DEFAULT_INDEX_K and player_ratings.RATING_K_GAMES.

    Analytic in k (no engine rerun), so the grid is cheap. Players must have
    >=1 train game to have a rate to shrink.

    Reported per TRAIN-GP BUCKET as well as pooled: the deep bucket (Adair,
    ~20 train games) barely feels k, so the pooled MAE understates how much
    the thin bucket — where the shrink constants actually bite — cares."""
    ids = [g["id"] for g in tracked]
    # per-game player lines, one events pass per game
    per_game = {}                                # gid -> {pid: gs}
    tot = defaultdict(float)                     # pid -> career GS
    gp = defaultdict(int)
    for gid in ids:
        boxes = S.aggregate_player_boxes([gid])
        per_game[gid] = {pid: S.game_score(b) for pid, b in boxes.items()}
        for pid, gs in per_game[gid].items():
            tot[pid] += gs
            gp[pid] += 1

    def bucket(tg):
        return "thin(1-4)" if tg <= 4 else ("mid(5-9)" if tg <= 9 else "deep(10+)")

    errs = {k: defaultdict(list) for k in k_grid}
    for gid in ids:
        held = per_game[gid]
        for pid, actual in held.items():
            tg = gp[pid] - 1                     # train games
            if tg < 1:
                continue
            train_rate = (tot[pid] - actual) / tg
            # train-pool anchor excluding this game's lines
            num = sum(tot.values()) - sum(held.values())
            den = sum(gp.values()) - len(held)
            anchor = num / den if den else 0.0
            b = bucket(tg)
            for k in errs:
                pred = anchor + (train_rate - anchor) * tg / (tg + k)
                errs[k][b].append(abs(pred - actual))
                errs[k]["all"].append(abs(pred - actual))
    out = {}
    for k, by_b in errs.items():
        out[k] = {b: (round(sum(v) / len(v), 3), len(v))
                  for b, v in sorted(by_b.items())}
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  DRIVER
# ══════════════════════════════════════════════════════════════════════════════

def run_all(constants=None, reg=None, sos_weight=None, include_t4=True):
    """Full harness pass under an optional constant config. Returns the report
    dict; team-ratings params (reg/sos_weight) ride as direct kwargs because
    score_ratings takes them per-call."""
    with override(constants or {}):
        tid, gender, n = focus_team()
        tracked = tracked_games()
        focus = [g for g in tracked if tid in (g["t1"], g["t2"])]
        folds = make_folds(focus)
        all_fin = finished_games(gender=gender)
        report = {
            "constants": snapshot_constants(),
            "focus_team": {"id": tid, "gender": gender, "tracked": n},
            "t1_adair": t1_adair(folds, all_fin, gender,
                                 reg=reg, sos_weight=sos_weight),
            "t1_league": t1_league(gender, reg=reg, sos_weight=sos_weight),
            "t2_validity": t2_rating_validity(folds, tracked, tid, gender),
            "t3_projection": t3_projection(folds, tracked, tid, gender),
        }
        if include_t4:
            report["t4_shrink_logo"] = t4_shrink_logo(tracked)
        return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-t4", action="store_true")
    args = ap.parse_args()
    rep = run_all(include_t4=not args.no_t4)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
        return
    ft = rep["focus_team"]
    print(f"focus team {ft['id']} ({ft['gender']}), {ft['tracked']} tracked")
    t = rep["t1_adair"]
    print(f"T1a Adair margin MAE  {t['mae']}  (baseline {t['baseline']}, n={t['n']})")
    t = rep["t1_league"]
    print(f"T1b league margin MAE {t['mae']}  (baseline {t['baseline']}, n={t['n']})")
    t = rep["t2_validity"]
    print(f"T2  validity rho      stabilized {t['rho_stabilized']}  raw {t['rho_raw']}  (n={t['n']})")
    for name, row in rep["t3_projection"].items():
        if row:
            print(f"T3  {name:5s} proj MAE   {row['mae']}  (prior-only {row['prior_mae']}, vol={row['vol']})")
    if "t4_shrink_logo" in rep:
        print("T4  shrink-k LOGO MAE per k (by train-GP bucket):")
        for k, by_b in rep["t4_shrink_logo"].items():
            parts = "  ".join(f"{b}={v[0]}(n={v[1]})" for b, v in by_b.items())
            print(f"      k={k:<5} {parts}")


if __name__ == "__main__":
    main()
