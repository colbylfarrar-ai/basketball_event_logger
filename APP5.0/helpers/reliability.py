"""reliability.py — how firmly a metric predicts ITSELF, and what that permits.

The house rule is "measure before shipping a verdict": a number that does not
correlate with itself across a split of the same season cannot carry a coach
sentence, no matter how large its sample or how clean its provenance. Until now
that rule was enforced ad hoc — each module chose its own attempt gate, and the
confidence affordance in `cards.conf_dot` was keyed on VOLUME (n vs a prior
weight k), which answers a different question. Volume tells you how precisely a
quantity was estimated. Reliability tells you whether the quantity is stable
enough to be worth estimating. A player's rim FG% in this book is measured from
plenty of shots and still predicts itself at r=.06.

This module is the single place the reliability → display-permission mapping
lives, so a caller cannot quietly invent a friendlier threshold.

WHAT WAS MEASURED (2026-07-26)
------------------------------
Repeated random half-splits of the tracked games (200 splits, not the single
odd/even split used previously — at 24-28 qualifying players one split's r has
a sampling spread of roughly +/-.2, which is wider than the differences the
Part 1 decision turned on). r is the mean across splits; SB is that mean
Spearman-Brown corrected, and SB is what the gates below key on, because the
shipped number is computed on the FULL sample, not on half of it.

Player level, >=10 located attempts per half. Two scopes, because the gates in
shot_kinds.py were set from the whole book while the app renders the F pool:

    metric                  F/2025-26 SB    whole-book SB   qualifying players
    share, any band            .70 - .92       .70 - .92          24 / 32
    two419 (4ft-arc) FG%           .647            .519           10 / 11
    arc3 FG%                       .727            .506            4 /  6
    floater (4-10ft) FG%           .540            .285            5 /  6
    rim (0-4ft) FG%                .064            .107            5 /  6
    above-break-3 FG%             -.076           -.245            5 /  6

The gates take the WHOLE-BOOK column wherever the two disagree, because it
rests on more units and is the less flattering of the two. Being wrong in the
generous direction is the failure mode that costs a coach's trust.

WHAT THAT TABLE FORBIDS
-----------------------
SHARES are count ratios and are reliable everywhere — every band, both levels,
both scopes, SB .70+. RATES are not, and the pattern is not "small samples are
noisy": rim FG% has the LARGEST per-player sample of any band in the book and
the WORST reliability in it (SB .06-.11). Finishing at the rim, the read a
coach most wants from a shot chart, is the one this book cannot support.

Coarser bands help but do not rescue rates. Merging floater+mid into one 4ft-
to-arc band roughly doubles the qualifying players (5-6 -> 10-11) and lifts SB
from .285 to .519 — a real gain, and still short of a number that carries a
verdict. So per-band player rates ship DESCRIBED (hollow dot, r printed inline)
rather than withheld or asserted, and only above WEAK_SB.

Streamlit-free. No HTML — `cards.conf_dot_r` renders these levels.
"""
from __future__ import annotations

#: Spearman-Brown corrected split-half reliability at or above which a number
#: is presented as a finding a coach can act on.
STABLE_SB = 0.80

#: Directional: real signal, will still move with more games.
FAIR_SB = 0.60

#: The floor. Below this a metric does not meaningfully predict itself and is
#: withheld rather than dotted — a hollow dot on pure noise still puts the
#: number on screen, and coaches read numbers, not dots. Set above the measured
#: rim FG% (SB .11) and above the shipped floater FG% refusal (SB .285) so this
#: module cannot be used to undo a refusal the measurement already earned.
WEAK_SB = 0.30

LEVELS = ("stable", "fair", "weak", "withhold")

LEVEL_LABELS = {
    "stable": "Reliable — predicts itself across a split season",
    "fair": "Directional — real signal, will still move",
    "weak": "Early — shown for completeness, not a finding",
    "withhold": "Not shown — does not predict itself in this book",
}

#: Glyphs, for text surfaces and for captions that cannot carry HTML.
LEVEL_GLYPHS = {"stable": "●", "fair": "◐", "weak": "○",
                "withhold": ""}


def spearman_brown(r):
    """Half-sample r corrected to the full-sample reliability it implies.

    The split-half correlation measures a HALF of the season against the other
    half. The number actually rendered is computed on both halves at once, so
    the relevant reliability is the corrected one: 2r / (1 + r).
    """
    if r is None or r <= -1:
        return None
    return 2.0 * r / (1.0 + r)


def level(sb):
    """Reliability band for a Spearman-Brown corrected r → one of LEVELS.

    `sb` is None when a metric was never measured — that is `withhold`, not a
    pass. An unmeasured verdict is exactly what the house rule exists to stop.
    """
    if sb is None:
        return "withhold"
    if sb >= STABLE_SB:
        return "stable"
    if sb >= FAIR_SB:
        return "fair"
    if sb >= WEAK_SB:
        return "weak"
    return "withhold"


def shows(sb):
    """May a caller render this number at all?"""
    return level(sb) != "withhold"


def caption(sb, *, metric=None):
    """The inline honesty string that rides a weak/fair number.

    Prints the reliability rather than hiding it, so a hollow dot is a claim a
    coach can check instead of a decoration: "does not predict itself (r=.11)".
    """
    lvl = level(sb)
    name = metric or "this number"
    if lvl == "withhold":
        return (f"{name} does not predict itself in this book"
                + (f" (r={sb:.2f})" if sb is not None else "")
                + " — withheld.")
    if lvl == "weak":
        return f"Early (r={sb:.2f}) — shown for completeness, not a finding."
    if lvl == "fair":
        return f"Directional (r={sb:.2f}) — real, will still move."
    return f"Reliable (r={sb:.2f}) across a split season."


# ── the measured book ─────────────────────────────────────────────────────────
# Keyed (unit, metric) -> SB. Callers look their read up here instead of
# hardcoding a threshold, so re-measuring updates every surface at once.
# `share` entries are the floor across bands, not the best band, so a caller
# that does not name its band still gets an honest answer.
MEASURED = {
    ("player", "kind_share"): 0.70,
    ("player", "kind_fg"): 0.11,        # rim — the worst, and the default ask
    ("player", "band_share"): 0.81,
    ("player", "band_fg"): 0.52,        # 4ft-to-arc, the only band that clears
    ("player", "pps"): 0.48,
    ("team", "kind_share"): 0.71,
    ("team", "band_share"): 0.88,
    ("team", "kind_fg"): 0.67,
    ("team", "pps"): 0.73,
}

#: Per-band overrides where a band's own reliability differs materially from
#: its family's floor. Keyed (unit, metric, band).
MEASURED_BAND = {
    ("player", "fg", "rim"): 0.11,
    ("player", "fg", "rim04"): 0.11,
    ("player", "fg", "floater"): 0.285,
    ("player", "fg", "mid"): None,       # never enough attempts to measure
    ("player", "fg", "two419"): 0.52,
    ("player", "fg", "arc3"): 0.51,
    ("player", "fg", "corner3"): None,
    ("player", "fg", "abovebreak3"): -0.25,
    ("player", "fg", "deep3"): None,
    ("player", "share", "mid"): 0.70,
    ("player", "share", "two419"): 0.87,
    ("player", "share", "deep3"): 0.91,
    ("player", "share", "rim"): 0.81,
    ("player", "share", "rim04"): 0.81,
    ("team", "share", "deep3"): 0.62,
    ("team", "share", "mid"): 0.73,
}


def measured(unit, metric, band=None):
    """The measured SB for a read, or None when it was never measured."""
    if band is not None:
        key = (unit, metric, band)
        if key in MEASURED_BAND:
            return MEASURED_BAND[key]
    return MEASURED.get((unit, metric))


def band_level(unit, metric, band=None):
    """Reliability level for a (unit, metric, band) read — the caller's gate."""
    return level(measured(unit, metric, band))
