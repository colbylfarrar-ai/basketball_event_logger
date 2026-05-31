"""
win_probability.py — In-game win probability + Game Excitement Index.

The one play-by-play artifact APP4.0 was missing that DomSamangy's NCAA
dashboards (and every pro site) have. From a score-margin-over-time trace it
produces a live win-probability curve, then distills the curve into a single
"how dramatic was this game" number — the Game Excitement Index (Luke Benz's
metric) — plus comeback / tension / lead-swing readouts.

Model (closed-form, no scipy): treat the eventual final margin as Normal around
the current margin, with a standard deviation that shrinks as the clock runs
out. Win probability for the home side = Φ(expected_final_margin / sd), where

    sd = sd_full · √(fraction of game remaining)

so early swings barely move WP and late swings move it a lot. With even teams
the expected final margin is just the current margin; pass `pregame_edge` (the
pre-game points spread, home − away) to tilt the curve for a known mismatch.
`sd_full` is the spread of final margins for an evenly-matched game over a full
game; ~12 pts fits HS basketball and is tunable.

The normal CDF is implemented via math.erf (stdlib) so there is NO scipy/numpy
dependency — safe for the lightweight deploy. Pure data layer, no streamlit.
"""
from __future__ import annotations

import math


GAME_SECONDS = 1920    # 4 × 480s HS regulation
SD_FULL      = 12.0    # SD of final margin, even game, full game (points) — tunable
_OT_SECONDS  = 240


def _norm_cdf(x):
    """Standard normal CDF via the error function (stdlib, no scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ══════════════════════════════════════════════════════════════════════════════
#  POINTWISE WIN PROBABILITY
# ══════════════════════════════════════════════════════════════════════════════

def win_prob(margin, secs_remaining, total_secs=GAME_SECONDS,
             pregame_edge=0.0, sd_full=SD_FULL):
    """
    P(home team wins) given the current `margin` (home − away) and
    `secs_remaining`. `pregame_edge` is the pre-game expected margin (0 = treat
    the teams as even, which is the right default for a pure score-flow replay).
    Returns a probability in [0, 1]; at the buzzer it collapses to 1/0 (or 0.5
    on a dead tie, which a real game then resolves in OT).
    """
    if secs_remaining <= 0:
        return 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
    frac = max(secs_remaining / total_secs, 1e-6) if total_secs else 1e-6
    sd = sd_full * math.sqrt(frac)
    exp_final = margin + pregame_edge * frac
    if sd <= 0:
        return 1.0 if exp_final > 0 else (0.0 if exp_final < 0 else 0.5)
    return _norm_cdf(exp_final / sd)


# ══════════════════════════════════════════════════════════════════════════════
#  WIN-PROBABILITY CURVE
# ══════════════════════════════════════════════════════════════════════════════

def wp_curve(points, total_secs=None, pregame_edge=0.0, sd_full=SD_FULL):
    """
    Build a win-probability curve from a margin-over-time trace.

    `points` = list of (elapsed_seconds, margin) in clock order (margin =
    home − away). `total_secs` defaults to the last elapsed value (so OT length
    is handled automatically). Returns a list of (elapsed, margin, wp) where wp
    is the home team's win probability at that moment.
    """
    pts = [(float(t), float(m)) for t, m in points]
    if not pts:
        return []
    if total_secs is None:
        total_secs = max(t for t, _ in pts) or GAME_SECONDS
    return [(t, m, win_prob(m, total_secs - t, total_secs, pregame_edge, sd_full))
            for t, m in pts]


# ══════════════════════════════════════════════════════════════════════════════
#  GAME EXCITEMENT INDEX + DRAMA SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def game_excitement_index(curve, total_secs=None, ref_secs=GAME_SECONDS):
    """
    GEI = total win-probability movement over the game, length-normalized.

    Sum of |ΔWP| between consecutive points (how much the win probability
    travelled — the textbook Game Excitement Index), scaled to a reference game
    length so a long OT thriller and a tight regulation game are comparable. A
    decisive wire-to-wire game needs only ~0.5 of movement; a back-and-forth
    nailbiter accumulates several, so values typically land ~0.5 (blowout) to
    ~5 (instant classic).
    """
    if len(curve) < 2:
        return 0.0
    movement = sum(abs(curve[i][2] - curve[i - 1][2]) for i in range(1, len(curve)))
    if total_secs is None:
        total_secs = curve[-1][0] or ref_secs
    norm = ref_secs / total_secs if total_secs else 1.0
    return round(movement * norm, 2)


def excitement_label(gei):
    """Human tier for a GEI value (textbook Σ|ΔWP| scale, ~0.5–5)."""
    if gei >= 4.0:
        return "🔥 Instant classic"
    if gei >= 3.0:
        return "⚡ Thriller"
    if gei >= 2.0:
        return "🍿 Competitive"
    if gei >= 1.0:
        return "📋 Comfortable"
    return "😴 Wire-to-wire"


def summarize(curve):
    """
    Distill a win-probability curve into drama metrics:

      gei              Game Excitement Index (see game_excitement_index)
      label            excitement tier
      winner           'home' | 'away' | 'tie' (by final margin)
      min_wp_winner    the eventual winner's lowest in-game win probability
                       (1.0 = never in doubt, low = staged a comeback)
      comeback         how far the winner climbed back = 0.5 − min_wp_winner,
                       clamped ≥ 0 (a real comeback only counts from below 50%)
      lead_changes     times the win probability crossed 50%
      avg_tension      mean closeness over the game (1 = perfect coin-flip the
                       whole way, 0 = decided from tip-off)
      peak_swing       biggest single-moment WP jump
    """
    if len(curve) < 2:
        return {"gei": 0.0, "label": excitement_label(0.0), "winner": "tie",
                "min_wp_winner": 0.5, "comeback": 0.0, "lead_changes": 0,
                "avg_tension": 0.0, "peak_swing": 0.0}

    total_secs = curve[-1][0] or GAME_SECONDS
    gei = game_excitement_index(curve, total_secs)
    final_margin = curve[-1][1]
    winner = "home" if final_margin > 0 else ("away" if final_margin < 0 else "tie")

    # winner's win probability over time (flip to away's perspective if needed)
    wp_winner = [(wp if winner != "away" else 1 - wp) for _, _, wp in curve]
    min_wp_winner = min(wp_winner) if winner != "tie" else 0.5

    lead_changes = 0
    prev = None
    for _, _, wp in curve:
        side = 1 if wp > 0.5 else (-1 if wp < 0.5 else 0)
        if side and prev and side != prev:
            lead_changes += 1
        if side:
            prev = side

    tension = sum(1 - abs(wp - 0.5) * 2 for _, _, wp in curve) / len(curve)
    peak_swing = max(abs(curve[i][2] - curve[i - 1][2])
                     for i in range(1, len(curve)))

    return {
        "gei": gei,
        "label": excitement_label(gei),
        "winner": winner,
        "min_wp_winner": round(min_wp_winner, 3),
        "comeback": round(max(0.0, 0.5 - min_wp_winner), 3),
        "lead_changes": lead_changes,
        "avg_tension": round(tension, 3),
        "peak_swing": round(peak_swing, 3),
    }
