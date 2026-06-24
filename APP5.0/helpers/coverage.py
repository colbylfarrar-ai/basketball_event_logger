"""
coverage.py — tagging-coverage panel (Tier 1, ML_LAYER_ROADMAP).

The honesty keystone for the whole roadmap: half the high-value reads (play_type ×
defense cross-tab, exploit matrix, contested shot-quality, self-scout drift) only mean
something when the OPTIONAL one-tap tags are actually filled in. This module answers,
per team, "how much have I tagged?" — so a coach knows whether to trust those surfaces
and what to capture next, and so the UI can show an honest "N tagged / % complete" chip
instead of silently implying full coverage.

Three optional signals are measured against the shots that *could* carry them:
  • play_type    — the set call, on the team's OWN shots (offense).
  • guarded_by   — the contesting defender, on the team's OWN shots (drives shot
                   quality / contested splits).
  • defense      — the scheme the team RAN, on the shots it ALLOWED (defense).

Pure data layer (reuses helpers.stats + helpers.playtypes scoping); no streamlit. A
shot is the unit; turnovers also carry play_type/defense but shots are the dominant,
comparable denominator, so coverage is reported over shots.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S
import helpers.playtypes as PT


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _label(pct):
    """Coarse status from a coverage percent (None = nothing to tag yet)."""
    if pct is None:
        return "none"
    if pct >= 80:
        return "strong"
    if pct >= 40:
        return "partial"
    return "sparse"


def _team_tracked_game_ids(team_id):
    """The team's tracked games this season (events logged), score-independent —
    mirrors scout.build_scout's game selection."""
    return [r["id"] for r in query(
        "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) AND tracked=1 "
        "AND season='Current'", (team_id, team_id))]


def team_coverage(team_id, game_ids=None, events=None):
    """Tagging coverage for one team over its tracked games.

    Returns {
      "games": n_tracked_games,
      "signals": {
        "play_type":  {"tagged","total","pct","label"},   # own (offense) shots
        "guarded_by": {"tagged","total","pct","label"},   # own (offense) shots
        "defense":    {"tagged","total","pct","label"},   # allowed (defense) shots
      },
      "overall_pct": weighted mean coverage across the three signals (None if no shots),
    }
    `total` is the taggable denominator for that signal (own shots, or allowed shots);
    `pct` None when that denominator is 0 (nothing to tag yet)."""
    gids = game_ids if game_ids is not None else _team_tracked_game_ids(team_id)
    if events is None:
        events = S.fetch_events(gids) if gids else []

    own_total = own_pt = own_guard = 0
    allowed_total = allowed_def = 0
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if e["shooter_team_id"] == team_id:          # our offense
            own_total += 1
            if e.get("play_type"):
                own_pt += 1
            if e.get("guarded_by_id") is not None:
                own_guard += 1
        else:                                         # shots we allowed (our defense)
            allowed_total += 1
            if e.get("defense"):
                allowed_def += 1

    signals = {
        "play_type":  {"tagged": own_pt,      "total": own_total,
                       "pct": _pct(own_pt, own_total)},
        "guarded_by": {"tagged": own_guard,   "total": own_total,
                       "pct": _pct(own_guard, own_total)},
        "defense":    {"tagged": allowed_def, "total": allowed_total,
                       "pct": _pct(allowed_def, allowed_total)},
    }
    for s in signals.values():
        s["label"] = _label(s["pct"])

    # overall = tagged across all three signals / taggable across all three (a single
    # honest "how complete is my tagging" number, weighted naturally by volume).
    tagged_all = own_pt + own_guard + allowed_def
    total_all = own_total + own_total + allowed_total
    return {
        "games": len(gids),
        "signals": signals,
        "overall_pct": _pct(tagged_all, total_all),
    }


def gender_coverage(gender=None, events=None):
    """League-wide coverage across every tracked game for a gender — the admin /
    pool-health view. Same three signals, but counted over ALL shots (denominator =
    every shot for play_type/guarded; every shot for defense, since each allowed shot
    is some team's defense). Returns the same shape as team_coverage minus per-team
    scoping (`games` = tracked-game count)."""
    gids = PT._tracked_game_ids(gender)
    if events is None:
        events = S.fetch_events(gids) if gids else []
    total = pt = guard = dfn = 0
    for e in events:
        if e["event_type"] != "shot":
            continue
        total += 1
        if e.get("play_type"):
            pt += 1
        if e.get("guarded_by_id") is not None:
            guard += 1
        if e.get("defense"):
            dfn += 1
    signals = {
        "play_type":  {"tagged": pt,    "total": total, "pct": _pct(pt, total)},
        "guarded_by": {"tagged": guard, "total": total, "pct": _pct(guard, total)},
        "defense":    {"tagged": dfn,   "total": total, "pct": _pct(dfn, total)},
    }
    for s in signals.values():
        s["label"] = _label(s["pct"])
    return {
        "games": len(gids),
        "signals": signals,
        "overall_pct": _pct(pt + guard + dfn, total * 3),
    }
