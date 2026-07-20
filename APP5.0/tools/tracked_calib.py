"""
tracked_calib.py — is the TRACKED rating engine good enough to move a ranking?

The score engine (team_ratings.score_ratings) is fit on the whole league —
12,648 finished games as of 2026-07-19 — and is MAE-validated by tools.backtest.
The tracked engine (team_ratings.tracked_ratings) is fit on the handful of
play-by-play games a coach has actually logged. `hybrid_ratings` exists to blend
the second into the first. This harness answers the only question that matters
before that blend is ever switched on:

    On the tracked games themselves, does the tracked engine predict the actual
    margin better than the score engine already does?

Protocol
--------
score engine   Fit ONCE on the full league. Holding out one game changes it by
               ~1/12648, so the in-sample bias is nil and the extra 41 refits
               would buy nothing.
tracked engine Strictly LEAVE-ONE-OUT. Holding one of ~41 games out is a 2.5%
               change, and for a team whose ONLY tracked game is the held-out
               one it removes the team entirely. Anything less than LOO scores
               the engine on data it was fit to.

Coverage is a first-class result, not a filtered-out row: a game the tracked
engine cannot predict out-of-sample is the finding. Under a star-shaped tracked
schedule most teams appear once, so most games are uncoverable.

Reported per gender
-------------------
  graph      tracked teams, GP distribution, connected components, repeat pairs.
             A star graph (one hub team in most games) is rank-deficient — you
             cannot identify N team strengths from N-ish games that all share an
             endpoint, no matter how the constants are tuned.
  coverage   how many tracked games the tracked engine can predict LOO at all.
  accuracy   MAE / RMSE for the score engine, the tracked engine, a pick-'em
             baseline, and the best convex blend of the two. `w*` is the blend
             weight an optimizer picks with full hindsight over these same
             games — an OPTIMISTIC ceiling. If w* is ~0, no honest weight helps.
  scale      OLS of actual margin on predicted margin. Slope != 1 means the
             engine's spreads are mis-scaled; `hybrid_ratings` mean-SHIFTS the
             tracked scale but never RESCALES it, so a slope far from 1 is a
             defect in the blend, not just a curiosity.
  control    the falsification test. A blend toward a heavily-shrunk tracked
             rating is arithmetically close to just shrinking the score
             prediction toward zero. If a plain `k * score_prediction` matches
             the blend, the tracked engine contributed NOTHING and the apparent
             gain was shrinkage. Never report a blend gain without this control.

Result on the 2026-07-19 snapshot (35 F + 6 M tracked games)
------------------------------------------------------------
Girls, 23 LOO-coverable games, swept over 28 (reg, sos_weight, class_step)
configs: the optimal blend weight was 0.00 in EVERY config. Score-engine MAE
7.26, tracked 11.61 at its own best tuning. The tracked engine is not
mis-tuned; the sample is a star graph and cannot support a ranking. Boys (4
coverable games) showed an apparent gain that the shrink-only control explained
away. Conclusion: keep hybrid_ratings OFF until this harness says otherwise.

Usage
    python -m tools.tracked_calib                    # human report
    python -m tools.tracked_calib --json
    python -m tools.tracked_calib --sweep            # constants sweep
    python -m tools.tracked_calib --gender F --season 2025-2026
Importable
    run(gender, season) -> dict
    graph_report(gender, season) -> dict
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict

import helpers.team_ratings as TR
from database.db import query


DEFAULT_SEASON = "2025-2026"

# A blend is only worth switching on if the optimizer wants real weight on the
# tracked engine AND that beats the shrink-only control by a real margin. Both
# thresholds are deliberately generous — w* and the gain are measured with
# hindsight on the same games, so the honest out-of-sample effect is smaller.
MIN_BLEND_WEIGHT = 0.15
MIN_GAIN_OVER_CONTROL = 0.25    # MAE points


# ══════════════════════════════════════════════════════════════════════════════
#  BOX-AGGREGATION MEMO
# ══════════════════════════════════════════════════════════════════════════════

def _install_box_memo():
    """Memoize tracked_ratings' per-game box aggregation across LOO refits.

    A box depends only on the game, never on the rating constants, but the
    engine re-aggregates every box on every call. Over a sweep (configs x LOO
    refits) that re-aggregation IS the runtime. Returns a restore callable.
    """
    orig = TR._tracked_team_game_boxes
    memo: dict = {}

    def cached(games):
        missing = [g for g in games if g["id"] not in memo]
        if missing:
            for (gid, tid), b in orig(missing).items():
                memo.setdefault(gid, {})[tid] = b
            for g in missing:
                memo.setdefault(g["id"], {})
        out = {}
        for g in games:
            for tid, b in memo.get(g["id"], {}).items():
                out[(g["id"], tid)] = b
        return out

    TR._tracked_team_game_boxes = cached
    return lambda: setattr(TR, "_tracked_team_game_boxes", orig)


# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════

def tracked_games(gender, season=DEFAULT_SEASON):
    """Finished tracked games for one gender, oldest first."""
    return query(
        """SELECT g.id, g.date, g.team1_id h, g.team2_id a,
                  g.home_score hs, g.away_score as_, g.game_type gt,
                  t1.name hn, t2.name an
           FROM games g JOIN teams t1 ON t1.id=g.team1_id
                        JOIN teams t2 ON t2.id=g.team2_id
           WHERE g.tracked=1 AND g.season=? AND t1.gender=?
             AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
           ORDER BY g.date, g.id""", (season, gender))


def graph_report(gender, season=DEFAULT_SEASON):
    """Shape of the tracked schedule graph — the thing that decides whether a
    ranking is identifiable at all. `hub_share` is the fraction of games touching
    the single busiest team; near 1.0 means a star, and a star cannot be ranked.
    """
    games = tracked_games(gender, season)
    gp, adj = Counter(), defaultdict(set)
    for g in games:
        gp[g["h"]] += 1
        gp[g["a"]] += 1
        adj[g["h"]].add(g["a"])
        adj[g["a"]].add(g["h"])

    seen, comps = set(), []
    for n in adj:
        if n in seen:
            continue
        stack, comp = [n], set()
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            seen.add(x)
            stack.extend(adj[x] - comp)
        comps.append(len(comp))

    pair = Counter(tuple(sorted((g["h"], g["a"]))) for g in games)
    hub_games = max(gp.values()) if gp else 0
    return {
        "games": len(games),
        "teams": len(gp),
        "gp_distribution": sorted(gp.values(), reverse=True),
        "teams_with_one_game": sum(1 for v in gp.values() if v == 1),
        "components": sorted(comps, reverse=True),
        "repeat_pairs": sum(1 for v in pair.values() if v > 1),
        "hub_games": hub_games,
        "hub_share": round(hub_games / len(games), 3) if games else 0.0,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  STATS
# ══════════════════════════════════════════════════════════════════════════════

def _ols(xs, ys):
    """(slope, intercept, r) of y on x, or (None, None, None) if degenerate."""
    n = len(xs)
    if n < 3:
        return None, None, None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None, None, None
    b = sxy / sxx
    return b, my - b * mx, sxy / (sxx * syy) ** 0.5


def _mae(rows, fn):
    return sum(abs(r["actual"] - fn(r)) for r in rows) / len(rows)


def _best_blend(rows):
    """(w, MAE) minimizing |actual - ((1-w)*score + w*tracked)| over w in [0,1].
    Fit on the same games it scores, so it is an optimistic ceiling."""
    return min(((i / 100.0,
                 _mae(rows, lambda r, w=i / 100.0: (1 - w) * r["p_sc"] + w * r["p_tr"]))
                for i in range(101)), key=lambda t: t[1])


def _best_shrink(rows):
    """(k, MAE) minimizing |actual - k*score|. The control: uses NO tracked
    data, so any blend gain it reproduces was never tracked information."""
    return min(((i / 100.0, _mae(rows, lambda r, k=i / 100.0: k * r["p_sc"]))
                for i in range(101)), key=lambda t: t[1])


# ══════════════════════════════════════════════════════════════════════════════
#  CORE
# ══════════════════════════════════════════════════════════════════════════════

def loo_rows(gender, season=DEFAULT_SEASON, reg=None, sos_weight=None,
             class_step=None, scored=None):
    """Per-tracked-game predictions from both engines, tracked one LEFT OUT.

    Returns a list of dicts with `p_tr=None` on games the tracked engine cannot
    predict once the game is held out (a side drops to zero tracked games).
    Those rows are the coverage finding — callers filter them for accuracy math
    but must report how many there were.
    """
    kw = {}
    if reg is not None:
        kw["reg"] = reg
    if sos_weight is not None:
        kw["sos_weight"] = sos_weight
    if class_step is not None:
        kw["class_step"] = class_step

    games = tracked_games(gender, season)
    gids = [g["id"] for g in games]
    if scored is None:
        scored = TR.score_ratings(gender=gender, season=season)

    rows = []
    for g in games:
        loo = [i for i in gids if i != g["id"]]
        tr = TR.tracked_ratings(gender=gender, season=season, game_ids=loo, **kw)
        rows.append({
            "game_id": g["id"], "date": g["date"], "game_type": g["gt"],
            "home": g["hn"], "away": g["an"],
            "actual": g["hs"] - g["as_"],
            "p_sc": TR.predict_spread(scored, g["h"], g["a"]),
            "p_tr": TR.predict_spread(tr, g["h"], g["a"]),
            "tgp_home": (tr.get(g["h"]) or {}).get("GP", 0),
            "tgp_away": (tr.get(g["a"]) or {}).get("GP", 0),
        })
    return rows


def run(gender, season=DEFAULT_SEASON, reg=None, sos_weight=None,
        class_step=None):
    """Full calibration verdict for one gender. See module docstring."""
    restore = _install_box_memo()
    try:
        rows = loo_rows(gender, season, reg, sos_weight, class_step)
    finally:
        restore()

    cov = [r for r in rows if r["p_tr"] is not None and r["p_sc"] is not None]
    out = {
        "gender": gender, "season": season,
        "graph": graph_report(gender, season),
        "games": len(rows),
        "coverage_score": sum(1 for r in rows if r["p_sc"] is not None),
        "coverage_tracked": len(cov),
        "uncovered": [f'{r["date"]} {r["home"]} vs {r["away"]}'
                      for r in rows if r["p_tr"] is None],
        "rows": rows,
    }
    if len(cov) < 3:
        out["verdict"] = "INSUFFICIENT — fewer than 3 leave-one-out coverable games"
        return out

    mae_sc = _mae(cov, lambda r: r["p_sc"])
    mae_tr = _mae(cov, lambda r: r["p_tr"])
    w, mae_blend = _best_blend(cov)
    k, mae_shrink = _best_shrink(cov)

    b_sc, a_sc, r_sc = _ols([r["p_sc"] for r in cov], [r["actual"] for r in cov])
    b_tr, a_tr, r_tr = _ols([r["p_tr"] for r in cov], [r["actual"] for r in cov])

    out.update({
        "mae_baseline": sum(abs(r["actual"]) for r in cov) / len(cov),
        "mae_score": mae_sc,
        "mae_tracked": mae_tr,
        "rmse_score": (sum((r["actual"] - r["p_sc"]) ** 2 for r in cov) / len(cov)) ** 0.5,
        "rmse_tracked": (sum((r["actual"] - r["p_tr"]) ** 2 for r in cov) / len(cov)) ** 0.5,
        "best_blend_w": w, "mae_blend": mae_blend,
        "best_shrink_k": k, "mae_shrink": mae_shrink,
        "gain_over_score": mae_sc - mae_blend,
        "gain_over_control": mae_shrink - mae_blend,
        "scale_score": {"slope": b_sc, "intercept": a_sc, "r": r_sc},
        "scale_tracked": {"slope": b_tr, "intercept": a_tr, "r": r_tr},
    })

    if w < MIN_BLEND_WEIGHT:
        out["verdict"] = (f"NO — the optimizer puts only {w:.2f} weight on the "
                          f"tracked engine even with full hindsight")
    elif out["gain_over_control"] < MIN_GAIN_OVER_CONTROL:
        out["verdict"] = (f"NO — the apparent gain is shrinkage: plain "
                          f"{k:.2f}x score scores {mae_shrink:.2f} vs the "
                          f"blend's {mae_blend:.2f}, using no tracked data")
    else:
        out["verdict"] = (f"MAYBE — blend w={w:.2f} beats both score alone "
                          f"({mae_sc:.2f} -> {mae_blend:.2f}) and the shrink-only "
                          f"control ({mae_shrink:.2f}). n={len(cov)}; confirm the "
                          f"sample is not a star before acting")
    return out


def sweep(gender, season=DEFAULT_SEASON,
          regs=(0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
          sos_weights=(0.0, 1.6), class_steps=(0.0, 1.5)):
    """Best achievable blend weight over a grid of tracked-engine constants.

    Answers the confound: is the tracked engine failing because the data is thin,
    or because it inherited constants tuned on the 12,648-game score graph? If
    w* stays ~0 across the whole grid, it is the data.
    """
    restore = _install_box_memo()
    results = []
    try:
        scored = TR.score_ratings(gender=gender, season=season)
        for reg in regs:
            for sw in sos_weights:
                for cs in class_steps:
                    rows = loo_rows(gender, season, reg, sw, cs, scored=scored)
                    cov = [r for r in rows
                           if r["p_tr"] is not None and r["p_sc"] is not None]
                    if len(cov) < 3:
                        continue
                    w, mae_b = _best_blend(cov)
                    k, mae_k = _best_shrink(cov)
                    results.append({
                        "reg": reg, "sos_weight": sw, "class_step": cs,
                        "n": len(cov),
                        "mae_tracked": _mae(cov, lambda r: r["p_tr"]),
                        "mae_score": _mae(cov, lambda r: r["p_sc"]),
                        "best_w": w, "mae_blend": mae_b,
                        "best_k": k, "mae_shrink": mae_k,
                        "gain_over_control": mae_k - mae_b,
                    })
    finally:
        restore()
    return results


# ══════════════════════════════════════════════════════════════════════════════
#  REPORT
# ══════════════════════════════════════════════════════════════════════════════

def _print(res):
    g = res["graph"]
    print("=" * 78)
    print(f"  {res['gender']}  season {res['season']}")
    print("=" * 78)
    print(f"  GRAPH  {g['games']} games / {g['teams']} teams   "
          f"components={g['components']}   repeat pairs={g['repeat_pairs']}")
    print(f"         busiest team in {g['hub_games']}/{g['games']} games "
          f"({g['hub_share']:.0%})   teams with exactly 1 game: "
          f"{g['teams_with_one_game']}")
    if g["hub_share"] >= 0.5:
        print("         ^ STAR GRAPH — team strengths are not identifiable here")
    print(f"\n  COVERAGE  score {res['coverage_score']}/{res['games']}   "
          f"tracked (LOO) {res['coverage_tracked']}/{res['games']}")
    for u in res["uncovered"]:
        print(f"            uncoverable: {u}")

    if "mae_score" not in res:
        print(f"\n  VERDICT  {res['verdict']}")
        return

    n = res["coverage_tracked"]
    print(f"\n  ACCURACY on {n} coverable games        MAE     RMSE")
    print(f"    baseline (pick 'em)             {res['mae_baseline']:>7.2f}")
    print(f"    score engine                    {res['mae_score']:>7.2f}"
          f"{res['rmse_score']:>9.2f}")
    print(f"    tracked engine (LOO)            {res['mae_tracked']:>7.2f}"
          f"{res['rmse_tracked']:>9.2f}")
    print(f"    best blend  (w={res['best_blend_w']:.2f})           "
          f"{res['mae_blend']:>7.2f}      <- optimistic, fit with hindsight")
    print(f"    CONTROL: shrink only (k={res['best_shrink_k']:.2f})  "
          f"{res['mae_shrink']:>7.2f}      <- uses NO tracked data")

    print("\n  SCALE (actual = a + b*pred)")
    for key, name in (("scale_score", "score"), ("scale_tracked", "tracked")):
        s = res[key]
        if s["slope"] is None:
            print(f"    {name:<9} degenerate")
        else:
            print(f"    {name:<9} slope={s['slope']:>6.2f}  "
                  f"intercept={s['intercept']:>7.2f}  r={s['r']:>5.2f}")

    print(f"\n  VERDICT  {res['verdict']}")


def _print_sweep(rows, label):
    print("=" * 88)
    print(f"  CONSTANTS SWEEP — {label}")
    print("=" * 88)
    print(f"{'reg':>6}{'sos_w':>7}{'cls':>6}{'n':>5}{'MAE_trk':>10}{'MAE_sc':>9}"
          f"{'w*':>7}{'MAE_bl':>9}{'vs ctrl':>9}")
    print("-" * 88)
    for r in rows:
        flag = ("  <<<" if (r["best_w"] >= MIN_BLEND_WEIGHT
                            and r["gain_over_control"] >= MIN_GAIN_OVER_CONTROL)
                else "")
        print(f"{r['reg']:>6.1f}{r['sos_weight']:>7.1f}{r['class_step']:>6.1f}"
              f"{r['n']:>5}{r['mae_tracked']:>10.2f}{r['mae_score']:>9.2f}"
              f"{r['best_w']:>7.2f}{r['mae_blend']:>9.2f}"
              f"{r['gain_over_control']:>9.2f}{flag}")
    if rows and max(r["best_w"] for r in rows) < MIN_BLEND_WEIGHT:
        print("\n  Every config puts ~zero weight on the tracked engine. This is "
              "the DATA,\n  not the tuning — no constant rescues a rank-deficient "
              "schedule graph.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Tracked-engine calibration: may hybrid_ratings be switched on?")
    ap.add_argument("--gender", choices=["M", "F"],
                    help="one gender (default: both)")
    ap.add_argument("--season", default=DEFAULT_SEASON)
    ap.add_argument("--sweep", action="store_true",
                    help="sweep tracked-engine constants instead of one report")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    genders = [args.gender] if args.gender else ["F", "M"]

    if args.sweep:
        out = {g: sweep(g, args.season) for g in genders}
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            for g, rows in out.items():
                _print_sweep(rows, f"{g} season {args.season}")
                print()
        return 0

    out = {}
    for g in genders:
        res = run(g, args.season)
        out[g] = res
        if not args.json:
            _print(res)
            print()
    if args.json:
        # drop the per-game rows from the JSON summary; they are large and the
        # verdict never depends on them
        print(json.dumps({g: {k: v for k, v in r.items() if k != "rows"}
                          for g, r in out.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
