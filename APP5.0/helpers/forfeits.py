"""
forfeits.py — a walkover counts in the record and nowhere else.

THE BOOK §8.1, ruling Q2: *"a zero on one side is a forfeit. Counts in W-L. Out
of strength of schedule"* — and by the same logic out of PPG, points allowed,
MOV, Pythagorean, Luck and the Power rating, every one of which is margin math.

Until this module existed the word "forfeit" appeared nowhere in the codebase
and 117 walkovers were rated as real games. What a coach met, on Rankings →
Overview with the default filters:

    F  Best defense (PA/G)   0.00   Mercy Institute Girls      1-0
    M  Best defense (PA/G)   1.00   Unity Academy Boys         0-3
    M  Point margin        +67.00   South Western Hieghts      1-0

A team that lost all three of its games was the boys' best defence, on three
forfeits recorded as 0-1 losses.

THE DETECTOR IS THE SCORE, NOT A COLUMN. Two reasons it is derived rather than
stored. It applies to all 12,647 finished games in the book the moment it
lands, with no migration and no backfill; and it cannot drift out of sync with
the scores it describes, which a column set at import time can and does. The
OSSAA convention for a walkover is a 1-0 or 2-0 line, and the signature is safe
on this book precisely because basketball has no genuine 1- or 2-point games:

    exactly 1-0 / 0-1        19
    exactly 2-0 / 0-2        98
                            ---
                            117

WHAT IS DELIBERATELY *NOT* CLASSIFIED, both per the ruling:

  * the 313 finished games with a side under ten points. Losing 62-8 is a real
    game with a real margin, and a team that plays a schedule full of them has
    earned the rating that comes with it. Reported, not classified.
  * six games carrying a zero on one side that are not the 1-0/2-0 signature —
    0-15, 15-0, 0-15, 65-0, 69-0, 51-0 (all 2025-2026). These are either real
    routs or a scoring hole, and the two cases are indistinguishable from here.
    Calling a 69-0 a forfeit would silently delete a legitimate blowout from
    the ratings, which is the more expensive mistake. `suspect_zero` names them
    so a human can look; nothing in the app acts on the answer.

Streamlit-free, no DB. Display: `label` appends "(ff)" to a result.
"""
from __future__ import annotations

#: The walkover signature. A finished game whose loser scored nothing and whose
#: winner scored 1 or 2 is a forfeit; nothing else is. Kept as a set of
#: (winner, loser) point pairs so the rule reads as the data it describes.
FORFEIT_LINES = frozenset({(1, 0), (2, 0)})


def is_forfeit(a_pts, b_pts):
    """True when this final score is a walkover rather than a played game.

    Order-independent: pass the two sides in either order.
    """
    if a_pts is None or b_pts is None:
        return False                       # unplayed / unscored is not a forfeit
    hi, lo = (a_pts, b_pts) if a_pts >= b_pts else (b_pts, a_pts)
    return (hi, lo) in FORFEIT_LINES


def suspect_zero(a_pts, b_pts):
    """True for a finished game with a zero side that is NOT the signature.

    A reporting hook, not a classifier — see the module docstring. Six games on
    production and none of them safe to reclassify automatically.
    """
    if a_pts is None or b_pts is None:
        return False
    return (a_pts == 0 or b_pts == 0) and not is_forfeit(a_pts, b_pts)


def label(won, forfeit):
    """"W (ff)" / "L (ff)" for a walkover, "W" / "L" otherwise.

    The result still shows, because it still counts: a forfeit win is a win.
    The suffix is there so a coach reading a 1-0 line knows why the margin
    engines behind it say nothing about the game."""
    base = "W" if won else "L"
    return f"{base} (ff)" if forfeit else base


def split(rows, *, key=is_forfeit):
    """(played, forfeited) over any iterable of rows, given a predicate.

    The shape every caller in this codebase wants: the record is counted over
    everything and the margin math over `played` only, so the two halves are
    produced once, together, instead of each engine re-deriving them.
    """
    played, ff = [], []
    for r in rows:
        (ff if key(r) else played).append(r)
    return played, ff


#: The caption every surface that hides a forfeit from its numbers should print
#: once, so the exclusion is disclosed rather than silent (Q6: both gates, and
#: disclose).
NOTE = ("Forfeits (a 1-0 or 2-0 walkover) count in the win-loss record and are "
        "excluded from every margin number — points for and against, MOV, "
        "Pythagorean expectation, luck, strength of schedule and the power "
        "rating. A walkover says nothing about how a team plays.")
