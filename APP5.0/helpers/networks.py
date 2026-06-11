"""
networks.py — Player chemistry network (who lifts whom on the floor).

The observed-lineup engine (helpers/lineups.py) rates whole five-player units;
this is the pairwise view EvanMiya/DataBallR call "teammate chemistry": for every
pair of teammates, how the team performs per 100 possessions while BOTH are on
the floor. Rendered as a node-link graph it answers "which duos drive this team,
and which pairings drag it down?" — the interactive network the dashboard layer
was missing.

Method (mirrors lineups.py, one level down):
  * A possession is a shot OR turnover (the app's locked rule); FG points only.
  * For each possession, take the on-court five for each team. Every unordered
    PAIR of those five shares that possession — offensive if their team had the
    ball, defensive otherwise.
  * Pair Net = 100·(pts_for/off_poss − pts_against/def_poss).
  * A node's solo net is the team's net per 100 while that single player is on —
    the individual on-court baseline each pairing is read against.

Pure data layer: database.db + helpers.stats + helpers.lineups (for the shared
event-floor builder). No streamlit, no numpy.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from database.db import query
import helpers.stats as S
from helpers.lineups import _event_floor


DEFAULT_MIN_POSS = 20   # a pair needs this many shared possessions to be drawn


_safe = S._safe   # shared definition lives in helpers.stats


def chemistry_network(team_id, game_ids=None, events=None,
                      min_poss=DEFAULT_MIN_POSS):
    """
    Pairwise teammate chemistry for one team.

    Returns a dict:
      nodes  [{pid, name, off_poss, def_poss, poss, pts_for, pts_against, net}]
             one per player, `net` = team net/100 while that player is on
      edges  [{a, b, names, off_poss, def_poss, poss, pts_for, pts_against,
               ORtg, DRtg, net}] one per teammate pair clearing `min_poss`,
             sorted by net desc
      totals {pairs, drawn, min_poss}

    `net`/ORtg/DRtg are per-100-possession points; positive net = the team
    outscores opponents with that player (or pair) on the floor.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    floor = _event_floor(game_ids)

    solo = defaultdict(lambda: {"off_poss": 0, "off_pts": 0,
                                "def_poss": 0, "def_pts": 0})
    pair = defaultdict(lambda: {"off_poss": 0, "off_pts": 0,
                                "def_poss": 0, "def_pts": 0})

    for e in events:
        if e["event_type"] not in ("shot", "turnover"):
            continue
        off_team = e["shooter_team_id"]
        if off_team is None:
            continue
        sets = floor.get(e["id"])
        if not sets:
            continue
        five = sets.get(team_id)
        if not five or len(five) != 5:
            continue
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        side = "off" if off_team == team_id else "def"
        for p in five:
            solo[p][f"{side}_poss"] += 1
            solo[p][f"{side}_pts"] += pts
        for a, b in combinations(sorted(five), 2):
            pr = pair[(a, b)]
            pr[f"{side}_poss"] += 1
            pr[f"{side}_pts"] += pts

    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}

    nodes = []
    for p, s in solo.items():
        poss = s["off_poss"] + s["def_poss"]
        net = 100 * (_safe(s["off_pts"], s["off_poss"])
                     - _safe(s["def_pts"], s["def_poss"]))
        nodes.append({
            "pid": p, "name": name_of.get(p, str(p)),
            "off_poss": s["off_poss"], "def_poss": s["def_poss"], "poss": poss,
            "pts_for": s["off_pts"], "pts_against": s["def_pts"],
            "net": round(net, 1),
        })
    nodes.sort(key=lambda d: -d["poss"])

    edges = []
    for (a, b), pr in pair.items():
        poss = pr["off_poss"] + pr["def_poss"]
        if poss < min_poss:
            continue
        ortg = 100 * _safe(pr["off_pts"], pr["off_poss"])
        drtg = 100 * _safe(pr["def_pts"], pr["def_poss"])
        edges.append({
            "a": a, "b": b,
            "names": [name_of.get(a, str(a)), name_of.get(b, str(b))],
            "off_poss": pr["off_poss"], "def_poss": pr["def_poss"], "poss": poss,
            "pts_for": pr["off_pts"], "pts_against": pr["def_pts"],
            "ORtg": round(ortg, 1), "DRtg": round(drtg, 1),
            "net": round(ortg - drtg, 1),
        })
    edges.sort(key=lambda d: -d["net"])
    return {"nodes": nodes, "edges": edges,
            "totals": {"pairs": len(pair), "drawn": len(edges),
                       "min_poss": min_poss}}
