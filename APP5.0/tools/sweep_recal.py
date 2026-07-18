"""
sweep_recal.py — the 2026-07-18 aggressive weight sweep (spec §5, §11).

Two phases, each scored on the out-of-sample gates that can actually judge it:

  Phase A (team ratings)   reg × sos_weight grid, scored on the T6 walk-forward
                           margin MAE (F+M) with T1a/T1b as sanity — the
                           chronological holdout is king for team constants.
  Phase B (player ratings) coordinate descent over shrink/anchor/pillar
                           constants, scored on a lean T2 (train-fold OVERALL
                           vs held-out Game Score, stabilized only).

Prints every config's numbers; adoption is a HUMAN/agent decision made from
the table (beat-or-tie rule, aggressive value preferred on a tie). WPA credit
constants (ONBALL_SHARE, STRATEGIC_FT_DAMP, WINDOW_SECS) are deliberately not
swept: no harness target measures credit assignment quality — they are design
constants, documented in the spec.

Usage:  python -m tools.sweep_recal [--phase A|B|all]
"""
from __future__ import annotations

import argparse
import copy
import json

import tools.backtest as BT
import helpers.team_ratings as TR
import helpers.player_ratings as PR


# ── Phase A: team constants on the walk-forward ──────────────────────────────

def phase_a():
    print("=== Phase A: reg x sos_weight on T6a walk-forward ===")
    results = []
    for reg in (1.0, 1.5, 2.0, 3.0):
        for sos in (0.4, 0.8, 1.2, 1.6):
            wf_f = BT.t6_walkforward("F", reg=reg, sos_weight=sos)["t6a"]
            wf_m = BT.t6_walkforward("M", reg=reg, sos_weight=sos)["t6a"]
            score = (wf_f["mae"] or 99) + (wf_m["mae"] or 99)
            results.append({"reg": reg, "sos": sos, "t6a_F": wf_f["mae"],
                            "t6a_M": wf_m["mae"], "sum": round(score, 3)})
            print(f"  reg={reg:<4} sos={sos:<4} F={wf_f['mae']}  M={wf_m['mae']}"
                  f"  sum={score:.3f}")
    best = min(results, key=lambda r: r["sum"])
    print(f"  BEST: reg={best['reg']} sos={best['sos']} sum={best['sum']}")
    # sanity: T1a/T1b at the winner
    folds_env = _t1_env()
    t1a = BT.t1_adair(*folds_env, reg=best["reg"], sos_weight=best["sos"])
    t1b = BT.t1_league(folds_env[2], reg=best["reg"], sos_weight=best["sos"])
    print(f"  winner sanity: T1a {t1a}  T1b {t1b}")
    return {"results": results, "best": best,
            "t1a_at_best": t1a, "t1b_at_best": t1b}


def _t1_env():
    tid, gender, _n = BT.focus_team()
    tracked = BT.tracked_games()
    focus = [g for g in tracked if tid in (g["t1"], g["t2"])]
    folds = BT.make_folds(focus)
    all_fin = BT.finished_games(gender=gender)
    return folds, all_fin, gender


# ── Phase B: player constants on lean T2 ─────────────────────────────────────

def _lean_t2():
    """T2 with stabilize=True only (halves the engine runs of the full T2)."""
    tid, gender, _n = BT.focus_team()
    tracked = BT.tracked_games()
    focus = [g for g in tracked if tid in (g["t1"], g["t2"])]
    folds = BT.make_folds(focus)
    pairs = []
    for fold in folds:
        held_ids = {g["id"] for g in fold}
        train_ids = [g["id"] for g in tracked if g["id"] not in held_ids]
        held = BT._heldout_lines(held_ids)
        R = PR.player_ratings(game_ids=train_ids, gender=gender,
                              season=BT.SEASON, stabilize=True)
        for pid, row in R.items():
            h = held.get(pid)
            if (h and h["gp"] >= 2 and row.get("team_id") == tid
                    and row.get("OVERALL") is not None):
                pairs.append((row["OVERALL"], h["gsg"]))
    return BT._spearman(pairs), len(pairs)


def _overall_parts_with(**weights):
    """Copy of _OVERALL_PARTS with named weights replaced."""
    return [(name, weights.get(name, w)) for name, w in PR._OVERALL_PARTS]


def phase_b():
    print("=== Phase B: player constants on lean T2 (coordinate descent) ===")
    base_parts = copy.deepcopy(PR._OVERALL_PARTS)
    steps = [
        ("player_ratings.RATING_K_GAMES", [1, 2, 3, 5]),
        ("shrinkage.DEFAULT_INDEX_K", [1.5, 3.0, 5.0]),
        ("shrinkage.DEFAULT_INDEX_POWER", [1.0, 1.5, 2.0]),
        ("player_ratings.TEAM_PRIOR_LAMBDA", [0.35, 0.5, 0.7]),
        ("player_ratings.ARCH_ANCHOR_BLEND", [0.0, 0.3, 0.5, 0.7]),
        ("player_ratings._OVERALL_PARTS", [
            ("penalties 0.2", _overall_parts_with(**{"TOV/Gz": 0.2, "nsPF/Gz": 0.2})),
            ("penalties 0.4", base_parts),
            ("penalties 0.7", _overall_parts_with(**{"TOV/Gz": 0.7, "nsPF/Gz": 0.7})),
            ("impact 1.2", _overall_parts_with(impact=1.2)),
            ("offense 1.3", _overall_parts_with(offense=1.3)),
            ("impact1.2+off1.3", _overall_parts_with(impact=1.2, offense=1.3)),
        ]),
    ]
    adopted = {}
    log = []
    for name, grid in steps:
        rows = []
        for val in grid:
            label, value = (val if isinstance(val, tuple) and name.endswith("_OVERALL_PARTS")
                            else (str(val), val))
            cfg = dict(adopted)
            cfg[name] = value
            with BT.override(cfg):
                rho, n = _lean_t2()
            rows.append((label, value, rho, n))
            print(f"  {name} = {label:<18}: rho {rho} (n={n})")
        best_label, best_val, best_rho, _bn = max(
            rows, key=lambda r: (r[2] if r[2] is not None else -9))
        adopted[name] = best_val
        log.append({"constant": name,
                    "rows": [(l, r) for l, _v, r, _n in rows],
                    "best": best_label, "best_rho": best_rho})
        print(f"  -> keep {name} = {best_label} (rho {best_rho})")
    return {"adopted": {k: (v if not k.endswith("_OVERALL_PARTS") else "see log")
                        for k, v in adopted.items()},
            "log": log, "final_parts": adopted.get("player_ratings._OVERALL_PARTS")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all", choices=["A", "B", "all"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = {}
    if args.phase in ("A", "all"):
        out["phase_a"] = phase_a()
    if args.phase in ("B", "all"):
        out["phase_b"] = phase_b()
    if args.json:
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
