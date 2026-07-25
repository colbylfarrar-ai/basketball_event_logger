"""
gate_ft_shooting.py — spec Part 2 item 1: gate-test FT% as a _SHOOTING leaf.

FT% has been computed in player_stat_table since forever
(`player_ratings.py:1411`, `_pct(_safe(b["FTM"], b["FTA"]))`) but was never
made a rating leaf — _SHOOTING carries FTR (how OFTEN you get to the line) and
not FT% (whether you convert once there). Free-throw shooting is the most
box-derivable skill there is, so adopting it deepens the T1 BOX tier: a coach
who only hand-enters box scores gets a richer SHOOTING read, not just tracked
coaches. Zero plumbing — this gate only needed _SHOOTING registered in the
backtest REGISTRY (2026-07-24).

Weights swept 0.3 / 0.5 / 0.75. The band is bracketed by the existing leaves it
sits between: FTR and 3PR ride at 0.5 / 0.4 as supporting shot-mix signals,
while TS% carries the group at 1.5. FT% is a real skill but a partial one — it
prices maybe a fifth of scoring — so anything at or above 1.0 would be claiming
it rivals true shooting, which it does not.

Scored on the lean-T2 rho gate (tools.sweep_recal._lean_t2: train-fold OVERALL
vs held-out Game Score, stabilized) — the same target that adopted xA in #8d.

ADOPTION RULE (recal round-2 discipline): adopt only if rho >= baseline. A tie
is NOT an adopt: unlike a never-tagged leaf, FT% is live for every player in
the pool, so a tie means the signal is genuinely already priced (TS% includes
free throws) rather than absent.

Usage:  python -m tools.gate_ft_shooting
"""
from __future__ import annotations

import tools.backtest as BT
import tools.sweep_recal as SR
import helpers.player_ratings as PR
from database.db import query


def _shooting_with(add=None, drop=()):
    """Copy of _SHOOTING with leaves added/dropped."""
    parts = [t for t in PR._SHOOTING if t[0] not in drop]
    return parts + list(add or [])


def main():
    print("=== Part 2.1 gate: FT% as a _SHOOTING leaf (lean T2) ===")

    # Coverage sanity: FT% is None for a player who never shot a free throw, and
    # a leaf that is None for most of the pool cannot move rho either way.
    cov = query(
        """SELECT COUNT(DISTINCT primary_player_id) n_shooters,
                  COUNT(DISTINCT CASE WHEN event_type='free_throw'
                                      THEN primary_player_id END) n_ft
             FROM game_events
            WHERE event_type IN ('shot','free_throw')
              AND primary_player_id IS NOT NULL""")[0]
    print(f"players with >=1 tracked FTA: {cov['n_ft']} of {cov['n_shooters']} "
          "who took any shot (manual box FTA adds more)")

    variants = [
        ("baseline", None),
        ("+FT% 0.3", _shooting_with(add=[("FT%", 0.3, False)])),
        ("+FT% 0.5", _shooting_with(add=[("FT%", 0.5, False)])),
        ("+FT% 0.75", _shooting_with(add=[("FT%", 0.75, False)])),
    ]

    rows = []
    for label, parts in variants:
        cfg = {} if parts is None else {"player_ratings._SHOOTING": parts}
        with BT.override(cfg):
            rho, n = SR._lean_t2()
        rows.append((label, rho, n))
        print(f"  {label:<14}: rho {rho} (n={n})")

    base_rho = rows[0][1]
    print("\n=== verdicts (adopt only if rho >= baseline) ===")
    for label, rho, _n in rows[1:]:
        if rho is None or base_rho is None:
            v = "NO DATA"
        elif rho > base_rho:
            v = f"PASS (+{rho - base_rho:.4f})"
        elif rho == base_rho:
            v = "TIE — do NOT adopt (FT% is live pool-wide, so a tie means "
            v += "already priced via TS%)"
        else:
            v = f"FAIL ({rho - base_rho:.4f})"
        print(f"  {label:<14}: {v}")
    print(f"  (baseline rho {base_rho})")


if __name__ == "__main__":
    main()
