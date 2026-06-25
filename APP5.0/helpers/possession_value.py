"""
possession_value.py — the possession-value ledger (Tier 2, ML_LAYER_ROADMAP).

Four-factors tell you eFG/TOV/OREB/FTr separately; this chains them into one
"where do our points per 100 come from, and where do they leak?" ledger by walking
every possession to its terminal outcome under the app's locked rule (a possession
ends on a SHOT or a TURNOVER; free throws never end one):

  scored          a made field goal           → points
  missed → board  missed FG, own offensive reb → the trip continues (2nd chance)
  missed → lost   missed FG, defense rebounds  → 0 (the empty-trip leak)
  turnover        → 0 (the give-it-away leak)

POINTS come from made 2s, made 3s and free throws; the OUTCOME mix is the share of
possessions ending each way. offense=True = our offense; offense=False = what we
ALLOW (the defensive ledger — there a turnover is forced, not committed). Pure data
layer over the event stream; no streamlit, volume-light so it's stable on a short
book (it's just counting).
"""
from __future__ import annotations

import helpers.stats as S
from helpers.stats import _safe, _team_game_ids   # single-source shared helpers


def possession_ledger(team_id, offense=True, game_ids=None, events=None):
    """Decompose a team's possessions into points sources + outcome mix.

    offense=True  → the team's own offense (points it scores, leaks it commits).
    offense=False → what the team ALLOWS on defense (opponent possessions vs it).

    Returns {
      side, poss, fga, ppp, pts_100,
      sources: [{key,label,pts,pts_100,share}],   # made2 / made3 / ft
      outcomes:[{key,label,n,pct}],               # scored / oreb / lost / turnover
      tov_pct, oreb_rate, efg,
    } or None if there are no possessions for that side."""
    gids = game_ids if game_ids is not None else _team_game_ids(team_id)
    if events is None:
        events = S.fetch_events(gids) if gids else []

    poss = fga = made2 = made3 = miss = oreb = lost = tov = 0
    pts2 = pts3 = ft_pts = 0
    for e in events:
        pteam = e.get("shooter_team_id")          # possessing team (shot OR turnover)
        et = e["event_type"]
        if et == "free_throw":
            if e["shot_result"] == "make" and (pteam == team_id) == offense \
                    and pteam is not None:
                ft_pts += 1
            continue
        if et not in ("shot", "turnover") or pteam is None:
            continue
        if (pteam == team_id) != offense:         # wrong side for this ledger
            continue
        poss += 1
        if et == "turnover":
            tov += 1
            continue
        # shot
        fga += 1
        if e["shot_result"] == "make":
            if e["shot_type"] == 3:
                made3 += 1
                pts3 += 3
            else:
                made2 += 1
                pts2 += 2
        else:
            miss += 1
            if e.get("rebounder_team_id") == pteam:
                oreb += 1                          # own board → 2nd chance
            else:
                lost += 1                          # defense rebounds (or unrecorded)

    if not poss:
        return None
    pts_total = pts2 + pts3 + ft_pts
    made = made2 + made3
    per100 = 100.0 / poss
    sources = [
        {"key": "made2", "label": "Made 2s", "pts": pts2},
        {"key": "made3", "label": "Made 3s", "pts": pts3},
        {"key": "ft", "label": "Free throws", "pts": ft_pts},
    ]
    for s in sources:
        s["pts_100"] = round(s["pts"] * per100, 1)
        s["share"] = round(_safe(s["pts"], pts_total), 3)
    outcomes = [
        {"key": "scored", "label": "Scored (made FG)", "n": made},
        {"key": "oreb", "label": "Missed → own board", "n": oreb},
        {"key": "lost", "label": "Missed → lost", "n": lost},
        {"key": "turnover", "label": "Turnover", "n": tov},
    ]
    for o in outcomes:
        o["pct"] = round(_safe(o["n"], poss), 3)
    return {
        "side": "offense" if offense else "defense",
        "poss": poss, "fga": fga,
        "ppp": round(_safe(pts_total, poss), 3),
        "pts_100": round(pts_total * per100, 1),
        "sources": sources, "outcomes": outcomes,
        "tov_pct": round(_safe(tov, poss), 3),
        "oreb_rate": round(_safe(oreb, miss), 3),
        "efg": round(_safe(made + 0.5 * made3, fga), 3),
    }


def team_ledger(team_id, game_ids=None, events=None):
    """Both sides in one pass: {'offense': ledger|None, 'defense': ledger|None} —
    the full 'where our points come from' vs 'what we give up' view."""
    gids = game_ids if game_ids is not None else _team_game_ids(team_id)
    if events is None:
        events = S.fetch_events(gids) if gids else []
    return {
        "offense": possession_ledger(team_id, offense=True, events=events),
        "defense": possession_ledger(team_id, offense=False, events=events),
    }
