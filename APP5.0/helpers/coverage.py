"""
coverage.py — tagging-coverage panel (Tier 1, ML_LAYER_ROADMAP).

The honesty keystone for the whole roadmap: half the high-value reads (play_type ×
defense cross-tab, exploit matrix, contested shot-quality, self-scout drift) only mean
something when the OPTIONAL one-tap tags are actually filled in. This module answers,
per team, "how much have I tagged?" — so a coach knows whether to trust those surfaces
and what to capture next, and so the UI can show an honest "N tagged / % complete" chip
instead of silently implying full coverage.

Five optional signals are measured against the events that *could* carry them:
  • play_type    — the set call, on the team's OWN shots (offense).
  • guarded_by   — the contesting defender, on the team's OWN shots (drives shot
                   quality / contested splits).
  • defense      — the scheme the team RAN, on the shots it ALLOWED (defense).
  • shot_created_by_id — the set-up-by tag, on the team's OWN shots; half of the
                   self-creation split, and measured nowhere until now.
  • turnover_type — the KIND of giveaway, on the team's OWN TURNOVERS.

Pure data layer (reuses helpers.stats + helpers.playtypes scoping); no streamlit.

TWO DENOMINATORS, NOT ONE. The first four are rates over shots. `turnover_type`
is a rate over turnovers, because a turnover tag counted against a shot
denominator is a coverage number that cannot reach 100% by construction — and a
panel whose whole job is honesty may not publish a ceiling it does not name.

WHY turnover_type IS HERE AT ALL. It runs to the last game of the 2025-2026
season at 53.5% coverage. Nothing on screen said so, so every live-vs-dead-ball
split built on it reads as complete. Disclosure is the fix; the tag is healthy.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S
import helpers.playtypes as PT


#: The signals `overall_pct` averages — DELIBERATELY the three it has always
#: averaged, and not every signal this module reports.
#:
#: `overall_pct` is not a display number. It feeds
#: `player_ratings.confidence_tier`, whose 0.35 / 0.60 / 0.80 tier boundaries
#: were fitted against these three. Folding two more (one of them a turnover
#: rate over a different denominator) into the mean would demote every player's
#: trust chip on the day a disclosure shipped — a constant change wearing a
#: display change's clothes, and exactly the kind of un-measured threshold move
#: the recal gates exist to stop. The new signals are reported and not averaged;
#: widening this set is a measurement, not an edit.
OVERALL_SIGNALS = ("play_type", "guarded_by", "defense")


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
    import helpers.seasons as SEAS
    return [r["id"] for r in query(
        "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) AND tracked=1 "
        f"AND season = {SEAS.tracked_default_season_sql()}", (team_id, team_id))]


def team_coverage(team_id, game_ids=None, events=None):
    """Tagging coverage for one team over its tracked games.

    Returns {
      "games": n_tracked_games,
      "signals": {
        "play_type":  {"tagged","total","pct","label"},   # own (offense) shots
        "guarded_by": {"tagged","total","pct","label"},   # own (offense) shots
        "defense":    {"tagged","total","pct","label"},   # allowed (defense) shots
        "shot_created_by_id": {...},                      # own (offense) shots
        "turnover_type":      {...},                      # own TURNOVERS
      },
      "overall_pct": weighted mean across OVERALL_SIGNALS (None if no shots),
    }
    `total` is the taggable denominator for that signal (own shots, allowed shots,
    or own turnovers); `pct` None when that denominator is 0 (nothing to tag yet).

    Read OVERALL_SIGNALS before adding a signal to the mean — the last two are
    reported and not averaged, on purpose."""
    gids = game_ids if game_ids is not None else _team_tracked_game_ids(team_id)
    if events is None:
        events = S.fetch_events(gids) if gids else []

    own_total = own_pt = own_guard = own_created = 0
    allowed_total = allowed_def = 0
    tov_total = tov_typed = 0
    for e in events:
        if e["shooter_team_id"] is None:
            continue
        if e["event_type"] == "turnover":
            # Own giveaways only — the defense's takeaway rate is the other
            # team's tagging discipline, not this team's.
            if e["shooter_team_id"] == team_id:
                tov_total += 1
                if e.get("turnover_type"):
                    tov_typed += 1
            continue
        if e["event_type"] != "shot":
            continue
        if e["shooter_team_id"] == team_id:          # our offense
            own_total += 1
            if e.get("play_type"):
                own_pt += 1
            if e.get("guarded_by_id") is not None:
                own_guard += 1
            if e.get("shot_created_by_id") is not None:
                own_created += 1
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
        "shot_created_by_id": {"tagged": own_created, "total": own_total,
                               "pct": _pct(own_created, own_total)},
        "turnover_type":      {"tagged": tov_typed,   "total": tov_total,
                               "pct": _pct(tov_typed, tov_total)},
    }
    for s in signals.values():
        s["label"] = _label(s["pct"])

    # overall = tagged / taggable across OVERALL_SIGNALS only (a single honest
    # "how complete is my tagging" number, weighted naturally by volume). The two
    # newer signals stay out — see OVERALL_SIGNALS for why that is a decision.
    tagged_all = sum(signals[k]["tagged"] for k in OVERALL_SIGNALS)
    total_all = sum(signals[k]["total"] for k in OVERALL_SIGNALS)
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
    total = pt = guard = dfn = created = 0
    tov_total = tov_typed = 0
    for e in events:
        if e["event_type"] == "turnover":
            tov_total += 1
            if e.get("turnover_type"):
                tov_typed += 1
            continue
        if e["event_type"] != "shot":
            continue
        total += 1
        if e.get("play_type"):
            pt += 1
        if e.get("guarded_by_id") is not None:
            guard += 1
        if e.get("defense"):
            dfn += 1
        if e.get("shot_created_by_id") is not None:
            created += 1
    signals = {
        "play_type":  {"tagged": pt,    "total": total, "pct": _pct(pt, total)},
        "guarded_by": {"tagged": guard, "total": total, "pct": _pct(guard, total)},
        "defense":    {"tagged": dfn,   "total": total, "pct": _pct(dfn, total)},
        "shot_created_by_id": {"tagged": created, "total": total,
                               "pct": _pct(created, total)},
        "turnover_type":      {"tagged": tov_typed, "total": tov_total,
                               "pct": _pct(tov_typed, tov_total)},
    }
    for s in signals.values():
        s["label"] = _label(s["pct"])
    return {
        "games": len(gids),
        "signals": signals,
        # OVERALL_SIGNALS only, for the reason recorded on that constant.
        "overall_pct": _pct(sum(signals[k]["tagged"] for k in OVERALL_SIGNALS),
                            total * len(OVERALL_SIGNALS)),
    }
