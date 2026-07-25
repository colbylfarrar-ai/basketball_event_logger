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

LEVELS = ("stable", "fair", "weak", "withhold", "unmeasured")

LEVEL_LABELS = {
    "stable": "Reliable — predicts itself across a split season",
    "fair": "Directional — real signal, will still move",
    "weak": "Early — shown for completeness, not a finding",
    "withhold": "Not a trait — does not predict itself in this book",
    "unmeasured": "Not measured — too few units to test repeatability",
}

#: Glyphs, for text surfaces and for captions that cannot carry HTML.
LEVEL_GLYPHS = {"stable": "●", "fair": "◐", "weak": "○",
                "withhold": "", "unmeasured": "·"}

# ── DESCRIPTION IS NOT PREDICTION ─────────────────────────────────────────────
# The distinction this module got wrong on its first pass, and it matters more
# than any threshold in it.
#
# A team's FG% from 4 ft to the arc, over 800 attempts this season, is a RECORD
# OF WHAT HAPPENED. It is the box score. It cannot be "unreliable" any more than
# a final score can — it is not making a claim about the future, so asking
# whether it predicts itself is asking the wrong question of it.
#
# "Does she finish at the rim" is a different kind of sentence. It reads a
# percentage as a TRAIT, something stable that will show up again next month.
# That claim is exactly what split-half reliability tests, and rim FG% fails it
# at SB .11.
#
# Same number, two jobs. So the gate is on the JOB, not on the number:
#
#   descriptive  the season's record. Always shown. The dot annotates whether
#                it is likely to repeat; it never decides whether to render.
#   predictive   a trait claim, a projection, a verdict, a scouting line.
#                Must clear WEAK_SB, and must have been MEASURED at all.
#
# The first version of this module hid a team's actual shooting percentages
# behind a player-level reliability book, which is how a coach ends up unable
# to read their own box score.


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

    `sb is None` means NEVER MEASURED, which is not the same as measured-and-
    failed and must not be collapsed into it. Team-level per-band FG% is the
    live example: it cannot be measured on this book at all, because there are
    six teams and a split-half r over six units is not a number. Reporting that
    as "does not predict itself" would be a claim the data never made.
    """
    if sb is None:
        return "unmeasured"
    if sb >= STABLE_SB:
        return "stable"
    if sb >= FAIR_SB:
        return "fair"
    if sb >= WEAK_SB:
        return "weak"
    return "withhold"


def shows(sb, descriptive=False):
    """May a caller render this number?

    `descriptive=True` for a record of what happened (a season FG%, a shot
    count, a foul clock) — those always render; the dot only annotates whether
    they are likely to repeat. Leave it False for anything presented as a trait,
    a projection or a verdict, which must have been measured AND have cleared
    the floor.
    """
    lvl = level(sb)
    if descriptive:
        return lvl != "withhold"
    return lvl in ("stable", "fair", "weak")


def shows_verdict(sb):
    """May a caller build a PROSE claim on this number?

    Strictest gate in the module: an unmeasured metric cannot carry a verdict,
    which is the rule the house convention exists to enforce.
    """
    return level(sb) in ("stable", "fair", "weak")


def caption(sb, *, metric=None):
    """The inline honesty string that rides a weak/fair number.

    Prints the reliability rather than hiding it, so a hollow dot is a claim a
    coach can check instead of a decoration: "does not predict itself (r=.11)".
    """
    lvl = level(sb)
    name = metric or "this number"
    if lvl == "unmeasured":
        return (f"{name}: a record of these games. Whether it repeats has not "
                f"been measured — too few units in this book to test it.")
    if lvl == "withhold":
        return (f"{name} does not predict itself in this book"
                + (f" (r={sb:.2f})" if sb is not None else "")
                + " — real for these games, but not a trait.")
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
    # Team per-band FG% is deliberately ABSENT rather than set to a number.
    # Measured 2026-07-26 it comes back SB -.12 to .10 on FIVE OR SIX teams,
    # and a split-half r over six units is not a measurement — the sampling
    # spread swamps the statistic. Absent means `unmeasured`, which renders the
    # number (it is the season's record) and declines to claim it repeats.
    # Setting it to the measured value would assert "team shooting is noise",
    # which this book cannot support in either direction.

    # ── DEFENDER reads (measured 2026-07-26, helpers/defense_profile.py) ──────
    # See DEFENSIVE SHARES ARE NOT OFFENSIVE SHARES below. These are the
    # per-defender assignment reads off `guarded_by_id`.
    ("defender", "assignment_share"): 0.26,   # the FINE band cut — floor, withheld
    ("defender", "area_share"): 0.578,        # interior-vs-perimeter, the coarse cut
    ("defender", "load"): 0.574,              # DLOAD% — share of tagged contests
    ("defender", "play_share"): -0.15,        # which ACTION they are asked to guard
    ("defender", "allowed_fg"): 0.399,
    ("defender", "allowed_pps"): 0.437,
    ("defender", "footprint"): -0.06,         # on/off opponent-diet delta
}


# ── DEFENSIVE SHARES ARE NOT OFFENSIVE SHARES ────────────────────────────────
# Measured 2026-07-26, same method as everything above: 200 random half-splits
# of the tracked games, Spearman-Brown corrected, defenders needing >=8
# contested shots in each half. Two scopes, and the book takes the LOWER of the
# two per metric (the F pool is what the app renders; the whole book rests on
# more units; taking the min keeps the more-units column from laundering a
# weak read).
#
#     defender read                 F/2025-26 SB   whole-book SB   book value
#     paint_share (interior)             .595           .643          .578*
#     three_share (perimeter)            .578           .640          .578
#     DLOAD%  (share of contests)        .574           .579          .574
#     arc3 assignment share              .438           .461          .438
#     PPS allowed                        .437           .604          .437
#     spot-up assignment share           .418           .532          .418
#     FG% allowed                        .399           .559          .399
#     pick-&-roll assignment share       .354           .309          .309
#     rim04 assignment share             .260           .313          .260
#     4ft-to-arc assignment share        .172           .228          .172
#     off-the-dribble share             -.017           .153         -.017
#     ISOLATION assignment share        -.061          -.150         -.150
#     on/off delta, opp rim share       -.030          -.077         -.060
#     on/off delta, opp three share      .099           .071          .071
#     on/off delta, opp PPS              .028           .130          .028
#     (* area_share is stored at the three_share value, the lower of the pair)
#
# THE FINDING, AND IT IS THE OPPOSITE OF THE OFFENSIVE ONE
# -------------------------------------------------------
# On offense, SHARES are the reliable currency: a player's own band shares
# measure SB .70-.92 while their band FG% collapses to SB .11. The obvious move
# was to port that wholesale — express every defensive read as a share and
# inherit the reliability. IT DOES NOT PORT. Defensive assignment shares come
# back .17 to .64, and the two most quotable ones are the worst in the table.
#
# The reason is structural, not a sample-size problem, and it is worth stating
# because it will keep being tempting: AN OFFENSIVE SHARE IS A CHOICE THE
# PLAYER MAKES; A DEFENSIVE ASSIGNMENT SHARE IS A CHOICE THE OPPONENT MAKES. A
# guard who hunts floaters hunts floaters every night. A defender whose
# assignment took 60% isolations last week drew a different opponent's offense
# this week, and the number moves with the schedule rather than with her. What
# split-half reliability is detecting here is exactly that: the metric is a
# property of the fixture, not of the player.
#
# Two things survive it, and they survive for the same reason — both are
# aggregated over WHO the opponent is:
#   * the coarse interior/perimeter axis (SB .578). Whether a player defends in
#     the paint or on the line is a role the coach assigns, so it repeats. The
#     FINE band cut inside it (rim04 .26, two419 .17) does not — that split is
#     the opponent's shot selection wearing the defender's name.
#   * DLOAD% (SB .574) — the share of her own team's tagged contests a player
#     accounts for. Being hunted is a property of the defender.
#
# WHAT THIS FORBIDS. "She is an isolation defender" is the single most natural
# sentence this data suggests and it is NOT SUPPORTED — iso assignment share
# measures SB -.15, anti-correlated, worse than the anti-correlated
# above-break-3 FG% that got withheld in the offensive book. Same for "the
# defense tightens when she checks in": all three on/off footprint deltas land
# between -.06 and .23, the identical failure mode as raw offensive on/off
# (r = -.096, see insights.ONOFF_PRIOR_POSS). Those reads still RENDER — they
# are a record of the games that were played — but they render descriptively,
# with their n, and no generator turns them into a trait.
MEASURED_DEFENDER_NOTE = (
    "Defensive assignment shares measure far weaker than offensive ones "
    "(SB .17-.64 vs .70-.92) because the assignment is chosen by the opponent, "
    "not by the player. Only the coarse interior/perimeter split and DLOAD% "
    "clear the floor."
)

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
