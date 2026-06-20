"""
handedness.py — single source for "which hand side did this shot come from?".

A player has a shooting hand (players.handedness, 'right'|'left', default 'right').
Each shot's FLOOR side is a true half-court split about the center line, taken from
the tap x when available and the coarse zone otherwise:
  tap shot_x : x < 0 -> left, x > 0 -> right, x == 0 -> dead-center (ignored)
  legacy zone: LC/LW -> left, RW/RC -> right, C -> center (ignored)
Shots dead-center are DROPPED, not bucketed — only left/right shots count, so the
split is the two halves of the floor with the middle thrown out.

Mapping side -> hand bucket, per the shooter's handedness:
  right-handed shooter: RIGHT half = DOMINANT, LEFT half = WEAK
  left-handed  shooter: LEFT  half = DOMINANT, RIGHT half = WEAK

Using the tap x (not just the zone) means a shot in the left of the paint counts as
LEFT instead of being swallowed by the central 'C' zone — the whole court splits in
half, only the dead-center line is ignored.

Pure + Streamlit-free (mirrors helpers/stats.py). The aggregation functions that
roll shots into these buckets live next to their siblings:
  - per-player : helpers.stats.player_hand_splits
  - per-team   : helpers.team_analytics.hand_splits
so callers reach them as S.* / TA.* like the guarded/zone splits.
"""
from __future__ import annotations

from database.db import query

LEFT_ZONES = frozenset({"LC", "LW"})
RIGHT_ZONES = frozenset({"RC", "RW"})

# Two buckets only — dead-center shots are ignored, never bucketed.
HAND_BUCKETS = ("dominant", "weak")
HAND_LABELS = {"dominant": "Dominant side", "weak": "Weak side"}


def shot_side(shot_x, zone):
    """'left' | 'right' | None for a shot. Prefer the exact tap x (a true split
    about the half-court center line); fall back to the coarse zone for legacy
    shots with no tap location. None => dead-center / unknown -> caller ignores it."""
    if shot_x is not None:
        if shot_x < 0:
            return "left"
        if shot_x > 0:
            return "right"
        return None                     # exactly on the center line
    if zone in LEFT_ZONES:
        return "left"
    if zone in RIGHT_ZONES:
        return "right"
    return None                         # zone C (straightaway) or no zone


def hand_bucket(shot_x, zone, handedness):
    """'dominant' | 'weak' | None for a shot given the shooter's handedness.
    None => the shot is dead-center / unclassifiable and should be ignored."""
    side = shot_side(shot_x, zone)
    if side is None:
        return None
    dominant_side = "left" if (handedness == "left") else "right"
    return "dominant" if side == dominant_side else "weak"


def hand_map() -> dict:
    """{player_id: 'right'|'left'} for every player (defaults blanks to 'right')."""
    return {r["id"]: (r["handedness"] or "right")
            for r in query("SELECT id, handedness FROM players")}
