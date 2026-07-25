"""
gate_scrast.py — spec Part 2 item 3: gate-test ScrAST/G as a _PLAYMAKING leaf.

Candidate: `ScrAST/G` — screen assists per game (the screener credited when the
shot they freed goes in; `b["SCR_AST"]`, already a player_stat_table key, so
zero plumbing). The off-ball creation axis: a player who never touches the ball
on the possession but breaks the defense to create the look.

THE REDUNDANCY QUESTION is the point of this gate, exactly as it was for
xA-vs-SCPassQ in #8d. `_PLAYMAKING` already carries SC/G (shots created, of
which SC_screen is one component) and SCPass/G. So screens are ALREADY priced
in part, and adding ScrAST/G may just re-weight the same signal. Variants:

  * +ScrAST 0.3 / 0.4   both-in — does the specific screen-assist signal add
                        anything on top of the broader SC/G?
  * +ScrAST 0.4 -SC/G   replace test A — is the screen-assist the part of SC/G
                        that was carrying the water?
  * +ScrAST 0.4 -SCPass/G  replace test B — the other component, as a control:
                        if dropping the PASSING component also ties, then the
                        composite is simply insensitive here and no "replace"
                        result should be read as a real finding.

Control B matters. Without it, a tie on replace-A reads as "ScrAST subsumes
SC/G" when it may only mean the weighted mean barely moves when any one 0.6
leaf leaves a 10-leaf group.

Scored on lean-T2 rho (tools.sweep_recal._lean_t2).

ADOPTION RULE: adopt only if rho >= baseline. On a tie the aggressive value is
preferred (recal round-2 convention) — but a tie on a REPLACE variant is never
an adopt, because dropping a working leaf needs positive evidence, not an
absence of harm.

Usage:  python -m tools.gate_scrast
"""
from __future__ import annotations

import tools.backtest as BT
import tools.sweep_recal as SR
import helpers.player_ratings as PR
from database.db import query


def _playmaking_with(add=None, drop=()):
    """Copy of _PLAYMAKING with leaves SET (added or re-weighted) and dropped.
    Same 'set, not append' semantics as gate_xa_hast — a leaf named in `add` is
    dropped from the base first, so re-running after an adoption stays honest."""
    names = {t[0] for t in (add or ())} | set(drop)
    parts = [t for t in PR._PLAYMAKING if t[0] not in names]
    return parts + list(add or [])


def main():
    print("=== Part 2.3 gate: ScrAST/G as a _PLAYMAKING leaf (lean T2) ===")

    cov = query(
        """SELECT COUNT(*) screens,
                  SUM(CASE WHEN shot_result='make' THEN 1 ELSE 0 END) made
             FROM game_events
            WHERE event_type='shot' AND shot_created_by_id IS NOT NULL""")[0]
    print(f"credited screens: {cov['screens']} · of which made (= ScrAST): "
          f"{cov['made']}")

    T = PR.player_stat_table(gender="F")
    carry = sum(1 for v in T.values() if v.get("ScrAST"))
    print(f"players with >=1 screen assist: {carry} of {len(T)}")

    variants = [
        ("baseline", None),
        ("+ScrAST 0.3", _playmaking_with(add=[("ScrAST/G", 0.3, False)])),
        ("+ScrAST 0.4", _playmaking_with(add=[("ScrAST/G", 0.4, False)])),
        ("ScrAST0.4 -SC/G", _playmaking_with(add=[("ScrAST/G", 0.4, False)],
                                             drop=("SC/G",))),
        ("ScrAST0.4 -SCPass", _playmaking_with(add=[("ScrAST/G", 0.4, False)],
                                               drop=("SCPass/G",))),
        # control: drop a component WITHOUT adding ScrAST, to see how much the
        # composite moves on its own. If this ties too, no replace result means
        # anything.
        ("control -SC/G only", _playmaking_with(drop=("SC/G",))),
    ]

    rows = []
    for label, parts in variants:
        cfg = {} if parts is None else {"player_ratings._PLAYMAKING": parts}
        with BT.override(cfg):
            rho, n = SR._lean_t2()
        rows.append((label, rho, n))
        print(f"  {label:<20}: rho {rho} (n={n})")

    base_rho = rows[0][1]
    print("\n=== verdicts (adopt only if rho >= baseline) ===")
    for label, rho, _n in rows[1:]:
        replace = "-" in label and "control" not in label
        if rho is None or base_rho is None:
            v = "NO DATA"
        elif rho > base_rho:
            v = f"PASS (+{rho - base_rho:.4f})"
        elif rho == base_rho:
            v = ("TIE — never an adopt for a REPLACE variant (dropping a "
                 "working leaf needs positive evidence)" if replace
                 else "TIE — adopt only with a reason beyond the gate")
        else:
            v = f"FAIL ({rho - base_rho:.4f})"
        print(f"  {label:<20}: {v}")
    print(f"  (baseline rho {base_rho})")


if __name__ == "__main__":
    main()
