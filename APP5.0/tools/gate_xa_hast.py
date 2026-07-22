"""
gate_xa_hast.py — #8d: gate-test xA and HAST as _PLAYMAKING leaves.

Candidate leaves (profiles already carry them, see player_ratings.profiles):
  xA/G    expected assists per game — make-independent feed quality
  HAST/G  hockey assists per game — opt-in capture (None until tagged)

Scored on the lean-T2 rho gate (tools.sweep_recal._lean_t2: train-fold OVERALL
vs held-out Game Score, stabilized). Variants:
  * baseline                    current _PLAYMAKING
  * +xA w                       xA/G added at 0.4 / 0.6 / 0.75 (SCPassQ kept)
  * xA replaces SCPassQ         the redundancy test — both engines price the
                                passer's feeds off the same rate table, so
                                both-in may double-count; replace-at-0.75 asks
                                whether xA carries SCPassQ's signal alone
  * +HAST w                     HAST/G added at 0.2 / 0.3 (CHG/G rare-event
                                pattern: tiny weight, None-skip until tagged)

ADOPTION RULE (recal round-2 discipline): adopt only if rho >= baseline.
HAST special case: if NO hockey assists are tagged in the pool the leaf is
inert (every player None -> drops out), rho == baseline EXACTLY, and the gate
is INCONCLUSIVE — do NOT adopt on a trivial tie; re-run once capture has data.

Corsi is deliberately NOT swept: it duplicates the RAPM `impact` leaf
(opponent+teammate adjusted where Corsi is raw) — see the batch doc.

Usage:  python -m tools.gate_xa_hast
"""
from __future__ import annotations

import tools.backtest as BT
import tools.sweep_recal as SR
import helpers.player_ratings as PR
from database.db import query


def _playmaking_with(add=None, drop=(), base=None):
    """Copy of _PLAYMAKING with leaves added/dropped."""
    parts = [t for t in (base or PR._PLAYMAKING) if t[0] not in drop]
    return parts + list(add or [])


def main():
    print("=== #8d gate: xA + HAST candidate _PLAYMAKING leaves (lean T2) ===")

    # Is HAST live yet? An untagged pool makes every HAST variant a trivial tie.
    n_hast = query(
        "SELECT COUNT(*) n FROM game_events WHERE hockey_from_id IS NOT NULL "
        "AND shot_result='make'")[0]["n"]
    print(f"hockey assists tagged in DB: {n_hast}")

    variants = [
        ("baseline", None),
        ("+xA 0.4", _playmaking_with(add=[("xA/G", 0.4, False)])),
        ("+xA 0.6", _playmaking_with(add=[("xA/G", 0.6, False)])),
        ("+xA 0.75", _playmaking_with(add=[("xA/G", 0.75, False)])),
        ("xA0.75 -SCPassQ", _playmaking_with(add=[("xA/G", 0.75, False)],
                                             drop=("SCPassQ",))),
        ("+HAST 0.2", _playmaking_with(add=[("HAST/G", 0.2, False)])),
        ("+HAST 0.3", _playmaking_with(add=[("HAST/G", 0.3, False)])),
    ]

    rows = []
    for label, parts in variants:
        cfg = {} if parts is None else {"player_ratings._PLAYMAKING": parts}
        with BT.override(cfg):
            rho, n = SR._lean_t2()
        rows.append((label, rho, n))
        print(f"  {label:<18}: rho {rho} (n={n})")

    base_rho = rows[0][1]
    print("\n=== verdicts (adopt only if rho >= baseline) ===")
    for label, rho, _n in rows[1:]:
        if rho is None or base_rho is None:
            v = "NO DATA"
        elif label.startswith("+HAST") and n_hast == 0 and rho == base_rho:
            v = "INCONCLUSIVE — leaf inert (no tagged HAST); do not adopt yet"
        elif rho > base_rho:
            v = f"PASS (+{rho - base_rho:.4f})"
        elif rho == base_rho:
            v = "TIE — adopt only with a reason beyond the gate"
        else:
            v = f"FAIL ({rho - base_rho:.4f})"
        print(f"  {label:<18}: {v}")
    print(f"  (baseline rho {base_rho})")


if __name__ == "__main__":
    main()
