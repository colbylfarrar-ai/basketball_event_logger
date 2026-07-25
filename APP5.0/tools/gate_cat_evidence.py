"""
gate_cat_evidence.py — spec Part 3 mechanism 2: gate PER-CATEGORY EVIDENCE.

Today every rating shrinks toward 50 on ONE games-equivalent shared by all
five. That treats a coach who tags nothing as having supplied the same evidence
for DEFENSE as one who tags everything, which is precisely the falsely-precise
behaviour the depth commitment promises not to have.

`CATEGORY_EVIDENCE = True` shrinks each rating on the evidence that fed THAT
category: tracked_gp x share + MANUAL_GAME_WEIGHT x manual_gp x box_share.

WHAT THIS GATE CAN AND CANNOT SHOW. It is a one-sided test. Per-category
evidence can only ever LOWER a category's evidence (share <= 1), so ratings
move toward 50 and never away. Whether that is more HONEST is not a question
lean-T2 can answer — the harness has no held-out truth for "was this player's
DEFENSE rating justified". What it can answer is whether the extra shrink
DAMAGES the one thing that is measurable: how well OVERALL tracks held-out Game
Score. See tools/sweep_recal.print_cohort_report for why the per-cohort
instrument cannot referee this either on the current book (no manual games, and
nearly every player feeds a T3 leaf, so the cohorts do not separate).

ADOPTION RULE: adopt only if rho >= baseline. A TIE IS AN ADOPT HERE, and this
is the one place in the run where that is defensible — the change is an
honesty correction with an argument behind it (a box score genuinely does not
feed DEFENSE's tracked leaves), and a tie means the correction costs nothing
measurable. That reasoning is exactly the "reason beyond the gate" the tie rule
asks for; it is recorded here so the call can be audited rather than assumed.
A LOSS is a reject, no matter how good the argument sounds.

Usage:  python -m tools.gate_cat_evidence
"""
from __future__ import annotations

import statistics

import tools.backtest as BT
import tools.sweep_recal as SR
import helpers.player_ratings as PR


def _impact_summary():
    """How far the change actually moves ratings, so a tie can be read as
    'no measurable cost' rather than 'the flag did nothing'."""
    tid, gender, _n = BT.focus_team()
    tracked = [g["id"] for g in BT.tracked_games()]
    with BT.override({"player_ratings.CATEGORY_EVIDENCE": False}):
        off = PR.player_ratings(game_ids=tracked, gender=gender,
                                season=BT.SEASON, stabilize=True)
    with BT.override({"player_ratings.CATEGORY_EVIDENCE": True}):
        on = PR.player_ratings(game_ids=tracked, gender=gender,
                               season=BT.SEASON, stabilize=True)
    moved = {}
    for cat in PR.CATEGORIES:
        d = [abs(on[p][cat] - off[p][cat])
             for p in off if p in on
             and off[p].get(cat) is not None and on[p].get(cat) is not None]
        if d:
            moved[cat] = {"n": len(d), "mean_abs": round(statistics.mean(d), 2),
                          "max_abs": round(max(d), 2),
                          "n_moved": sum(1 for x in d if x >= 0.05)}
    return moved


def main():
    print("=== Part 3 gate: per-category evidence for shrink-to-50 (lean T2) ===")

    print("\nhow much do ratings actually move?")
    for cat, m in _impact_summary().items():
        print(f"  {cat:<11}: {m['n_moved']}/{m['n']} players move, "
              f"mean |delta| {m['mean_abs']}, max {m['max_abs']}")

    rows = []
    for label, val in (("baseline (flat evidence)", False),
                       ("per-category evidence", True)):
        with BT.override({"player_ratings.CATEGORY_EVIDENCE": val}):
            rho, n = SR._lean_t2()
        rows.append((label, rho, n))
        print(f"\n  {label:<26}: rho {rho} (n={n})")

    base_rho, new_rho = rows[0][1], rows[1][1]
    print("\n=== verdict ===")
    if base_rho is None or new_rho is None:
        print("  NO DATA")
    elif new_rho > base_rho:
        print(f"  PASS (+{new_rho - base_rho:.4f}) — adopt")
    elif new_rho == base_rho:
        print("  TIE — ADOPT. The correction costs nothing measurable and has "
              "a standing argument (a hand-entered box score does not feed "
              "DEFENSE's tracked leaves, so it must not buy evidence for "
              "them). Recorded as the reason beyond the gate.")
    else:
        print(f"  FAIL ({new_rho - base_rho:.4f}) — REJECT. The honesty "
              "argument does not license a measurable loss.")

    print("\n--- depth-commitment cohort report at the CANDIDATE setting ---")
    with BT.override({"player_ratings.CATEGORY_EVIDENCE": True}):
        SR.print_cohort_report()


if __name__ == "__main__":
    main()
