"""
gate_reb_guarded.py — spec Part 1 §1: gate-test the guarded% rebounding leaf.

Candidate leaf: `def_secure_team_stab` — when a player is the ON-BALL DEFENDER
(guarded_by) on a missed shot, the EB-stabilized rate at which their TEAM ends
the possession. Home: `_DREB`. Weights swept 0.4 / 0.6 (spec-registered band).

Why this leaf and only this leaf (spec Part 1 §1): `onball_share` is a STYLE
axis — a low share means a player's boards come from helping elsewhere, which
is a different job, not a worse one, so ranking it would grade a preference.
`own_miss_rec` is a rare event. Both stay surface-only.

Why the TEAM twin and not `def_secure_self_pct`: walling your shooter off so a
TEAMMATE collects the board is the entire point of a box-out. The self-only
rate would punish the player doing it properly.

Why the STABILIZED twin: per spec Part 3 mechanism 4, a leaf reads the EB twin
wherever a pool prior exists, so a 5-contest sample cannot rate like a
70-contest one. The raw rate is surface-only.

The leaf is None below rebounding.MIN_ONBALL and for any player whose team
never tags guarded_by, so it None-skips out of the weighted mean rather than
scoring a tagging gap as bad rebounding — the CHG/G pattern.

Scored on the lean-T2 rho gate (tools.sweep_recal._lean_t2), same target that
adopted xA (#8d) and FT% (2026-07-24).

ADOPTION RULE (recal round-2 discipline): adopt only if rho >= baseline. A TIE
here is genuinely ambiguous rather than an automatic reject — the leaf is
None for most of the pool, so a tie can mean "no signal" OR "too few players
carry it to move the number". Read the coverage line printed below before
calling it either way.

Usage:  python -m tools.gate_reb_guarded
"""
from __future__ import annotations

import tools.backtest as BT
import tools.sweep_recal as SR
import helpers.player_ratings as PR
import helpers.rebounding as RB
from database.db import query


def _dreb_with(add=None, drop=()):
    """Copy of _DREB with leaves added/dropped."""
    parts = [t for t in PR._DREB if t[0] not in drop]
    return parts + list(add or [])


def main():
    print("=== Part 1 §1 gate: def_secure_team_stab as a _DREB leaf (lean T2) ===")

    # Capture coverage — the number that decides whether a tie is meaningful.
    cov = query(
        """SELECT COUNT(*) misses,
                  SUM(CASE WHEN guarded_by_id IS NOT NULL THEN 1 ELSE 0 END) guarded,
                  SUM(CASE WHEN guarded_by_id IS NOT NULL
                            AND rebound_by_id IS NOT NULL THEN 1 ELSE 0 END) both
             FROM game_events
            WHERE event_type='shot' AND shot_result='miss'""")[0]
    print(f"missed FGs: {cov['misses']} · with guarded_by: {cov['guarded']} "
          f"· with BOTH guarded_by + rebound_by: {cov['both']}")

    # How many players actually carry the leaf? A leaf None for most of the
    # pool cannot move rho much in either direction, and that context decides
    # how to read a tie.
    T = PR.player_stat_table(gender="F")
    carry = sum(1 for v in T.values()
                if v.get("def_secure_team_stab") is not None)
    print(f"players carrying the leaf (>= {RB.MIN_ONBALL} contests): "
          f"{carry} of {len(T)}")

    variants = [
        ("baseline", None),
        ("+guarded 0.4", _dreb_with(add=[("def_secure_team_stab", 0.4, False)])),
        ("+guarded 0.6", _dreb_with(add=[("def_secure_team_stab", 0.6, False)])),
    ]

    rows = []
    for label, parts in variants:
        cfg = {} if parts is None else {"player_ratings._DREB": parts}
        with BT.override(cfg):
            rho, n = SR._lean_t2()
        rows.append((label, rho, n))
        print(f"  {label:<16}: rho {rho} (n={n})")

    base_rho = rows[0][1]
    print("\n=== verdicts (adopt only if rho >= baseline) ===")
    for label, rho, _n in rows[1:]:
        if rho is None or base_rho is None:
            v = "NO DATA"
        elif rho > base_rho:
            v = f"PASS (+{rho - base_rho:.4f})"
        elif rho == base_rho:
            v = ("TIE — check the coverage line above before reading this as "
                 "'no signal'")
        else:
            v = f"FAIL ({rho - base_rho:.4f})"
        print(f"  {label:<16}: {v}")
    print(f"  (baseline rho {base_rho})")


if __name__ == "__main__":
    main()
