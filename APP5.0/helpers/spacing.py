"""
spacing.py — a floor-spacing index from the tap-located (x, y) shot chart.

Spacing is the offense's force multiplier: stretch the floor and every look gets
cleaner. This scores it from the located shots — NOT the legacy 5 zones, which
are being retired — using four x,y-native components, each percentile-ranked vs
the gender's league pool, then averaged into one 0-100 SpacingIndex (50 = league
average, higher = better spacing).

Components (all from located shots):
  • 3-point rate    — share of FGA beyond the arc (floor stretch)
  • Open-look rate  — share of FGA uncontested (`guarded_by_id` NULL): spacing's
                      OUTPUT — a spread floor the defense can't contest
  • Corner-3 rate   — share of FGA that are corner 3s (court geometry): the
                      signature spacing shot — shortest, highest-eFG three
  • Floor width     — spatial spread (stdev) of shot x-positions: do they use the
                      whole width or bunch in the middle

Honest about scale: volume-gated (``MIN_SHOTS`` located FGA) and needs a real
pool (``MIN_POOL`` teams) before the percentiles mean anything. No streamlit.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import pstdev

import helpers.stats as S
import helpers.playtypes as PT
import helpers.court_geom as CG

MIN_SHOTS = 30        # located FGA before a team's spacing read is stable
MIN_POOL = 4          # qualified teams needed for a meaningful percentile

# (key, label, higher_is_better) — every component is "more = better spacing".
COMPONENTS = [
    ("tpa_rate", "3-point rate", True),
    ("open_rate", "Open-look rate", True),
    ("corner3_rate", "Corner-3 rate", True),
    ("x_spread", "Floor width", True),
]


def team_components(shots):
    """Raw spacing components from one team's located shots (None if empty)."""
    n = len(shots)
    if not n:
        return None
    threes = sum(1 for s in shots if s["value"] == 3)
    corner3 = sum(1 for s in shots
                  if s["value"] == 3 and CG.is_corner_three(s["x"], s["y"]))
    openn = sum(1 for s in shots if not s["guarded"])
    xs = [s["x"] for s in shots]
    return {
        "n": n,
        "tpa_rate": threes / n,
        "open_rate": openn / n,
        "corner3_rate": corner3 / n,
        "x_spread": pstdev(xs) if n > 1 else 0.0,
    }


def _gender_located_by_team(gender, events=None, game_ids=None):
    """Located OFFENSIVE shots in the gender's tracked games, grouped by the
    shooter's team_id."""
    gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
    if not gids:
        return {}
    shots = S.located_shots(game_ids=gids, events=events)
    by_team = defaultdict(list)
    for s in shots:
        if s.get("team_id") is not None:
            by_team[s["team_id"]].append(s)
    return by_team


def spacing_index(team_id, gender=None, events=None, game_ids=None,
                  min_shots=MIN_SHOTS, team_game_ids=None):
    """A team's floor-spacing index — the league-percentile blend of the four
    located-shot components.

    Returns {'index': 0-100 or None, 'components': [{key,label,value,pct}],
             'n': located FGA, 'pool_n': qualified teams, 'note': str}. ``index``
    is None (with an explanatory note) until the team clears ``min_shots`` and the
    pool clears MIN_POOL — graceful while located-shot coverage is still thin.

    ``team_game_ids`` (AXIS-2 read-filter) scopes the TEAM's OWN components to the
    viewer's visible games for this team, while the percentile pool stays
    gender-wide. None = unrestricted (own team / admin). An empty collection means
    the viewer may see none of this team's games → no spacing read (never falls
    back to the full sample)."""
    by_team = _gender_located_by_team(gender, events=events, game_ids=game_ids)
    pool = {tid: c for tid, s in by_team.items()
            if (c := team_components(s)) and c["n"] >= min_shots}
    if team_game_ids is not None:
        # read-filtered: recompute the team's own components from ONLY its visible
        # games (empty → no read, never the full sample).
        me = (team_components(S.located_shots(game_ids=list(team_game_ids),
                                              team_id=team_id))
              if team_game_ids else None)
    else:
        me = pool.get(team_id) or team_components(by_team.get(team_id, []))

    if not me or me["n"] < min_shots:
        return {"index": None, "components": [], "n": me["n"] if me else 0,
                "pool_n": len(pool),
                "note": ("Not enough located shots yet — tap shot spots in the "
                         f"Game Tracker to build the spacing read (needs "
                         f"{min_shots}+).")}
    if len(pool) < MIN_POOL:
        return {"index": None, "components": [], "n": me["n"], "pool_n": len(pool),
                "note": ("Too few tracked teams in the league pool to rank "
                         "spacing yet — fills in as more teams log located "
                         "shots.")}

    comps = []
    for key, label, hb in COMPONENTS:
        vals = [c[key] for c in pool.values()]
        pct = S.percentile(me[key], vals, higher_better=hb)
        comps.append({"key": key, "label": label, "value": me[key],
                      "pct": round(pct) if pct is not None else None})
    valid = [c["pct"] for c in comps if c["pct"] is not None]
    idx = round(sum(valid) / len(valid)) if valid else None
    return {"index": idx, "components": comps, "n": me["n"], "pool_n": len(pool),
            "note": ("Floor-spacing index — the league-percentile blend of "
                     "3-point rate, open-look rate, corner-3 rate and floor "
                     "width (50 = league average, higher = better spacing).")}


# ── per-PLAYER spacing (same components, ranked vs the player pool) ──────────────
PLAYER_MIN_SHOTS = 20   # a player's located FGA before the read is stable
PLAYER_MIN_POOL = 8     # qualified players needed for a meaningful percentile


def _gender_located_by_player(gender, events=None, game_ids=None):
    """Located shots in the gender's tracked games, grouped by the shooter
    (``player_id``)."""
    gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
    if not gids:
        return {}
    shots = S.located_shots(game_ids=gids, events=events)
    by_player = defaultdict(list)
    for s in shots:
        if s.get("player_id") is not None:
            by_player[s["player_id"]].append(s)
    return by_player


def league_player_spacing(gender, events=None, game_ids=None,
                          min_shots=PLAYER_MIN_SHOTS):
    """{pid: {index, components, n}} for every player clearing ``min_shots``
    located FGA, each of the four components percentile-ranked vs the qualified-
    player pool then averaged into a 0-100 spacing index. Returns {} when the pool
    is too thin (< PLAYER_MIN_POOL). One pass — built for the scout sheet's whole
    roster (look each player up by pid)."""
    by_player = _gender_located_by_player(gender, events=events, game_ids=game_ids)
    pool = {pid: c for pid, s in by_player.items()
            if (c := team_components(s)) and c["n"] >= min_shots}
    if len(pool) < PLAYER_MIN_POOL:
        return {}
    poolvals = {key: [c[key] for c in pool.values()] for key, _, _ in COMPONENTS}
    out = {}
    for pid, c in pool.items():
        comps = []
        for key, label, hb in COMPONENTS:
            pct = S.percentile(c[key], poolvals[key], higher_better=hb)
            comps.append({"key": key, "label": label, "value": c[key],
                          "pct": round(pct) if pct is not None else None})
        valid = [x["pct"] for x in comps if x["pct"] is not None]
        out[pid] = {
            "index": round(sum(valid) / len(valid)) if valid else None,
            "components": comps, "n": c["n"]}
    return out
