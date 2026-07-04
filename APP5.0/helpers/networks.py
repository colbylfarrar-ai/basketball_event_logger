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
from helpers.lineups import (_event_floor, _five_q, fit_opponent_slopes,
                             player_quality)


DEFAULT_MIN_POSS = 20   # a pair needs this many shared possessions to be drawn


_safe = S._safe   # shared definition lives in helpers.stats


def chemistry_network(team_id, game_ids=None, events=None,
                      min_poss=DEFAULT_MIN_POSS, quality=None):
    """
    Pairwise teammate chemistry for one team, CONTEXT-ADJUSTED.

    Raw side (unchanged keys): per-100 net while a player / pair is on the
    floor. Adjusted side — the founder's "who ACTUALLY lifts whom" read —
    corrects every possession for the two things a raw pair net conflates:
      • OPPONENT strength: the mean OVERALL of the opposing on-floor five
        (the unit_ratings v2 correction, same self-fit slopes).
      • TEAMMATE strength: the mean OVERALL of the OTHER teammates sharing
        the floor (the other 3 for a pair, other 4 for a solo) — a duo that
        only looks good next to the star gives that credit back.
    Slopes come from lineups.fit_opponent_slopes on this sample; when the
    sample can't support the fit (adjusted=False) the Adj* values equal the
    raw ones, so thin data never breaks a caller.

    Returns {nodes, edges, totals}:
      nodes  [{pid, name, off_poss, def_poss, poss, pts_for, pts_against,
               net, adj_net}]
      edges  [{a, b, names, off_poss, def_poss, poss, pts_for, pts_against,
               ORtg, DRtg, net, AdjORtg, AdjDRtg, adj_net}] pairs clearing
             `min_poss`, sorted by adj_net desc
      totals {pairs, drawn, min_poss, adjusted}
    """
    if events is None:
        events = S.fetch_events(game_ids)
    floor = _event_floor(game_ids)
    if quality is None:
        quality = player_quality(game_ids=game_ids)
    b_off, b_def, qbar, adjusted = fit_opponent_slopes(events, floor, quality)

    # per-possession rows: (pts, q_opponent_five, q_other_teammates)
    solo = defaultdict(lambda: {"off": [], "def": []})
    pair = defaultdict(lambda: {"off": [], "def": []})

    def _others_q(five, exclude):
        vals = [quality[p] for p in five if p not in exclude and p in quality]
        return sum(vals) / len(vals) if vals else None

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
        opp_five = next((f for t, f in sets.items() if t != team_id), None)
        q_opp = (_five_q(opp_five, quality)
                 if opp_five and len(opp_five) == 5 else None)
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        side = "off" if off_team == team_id else "def"
        for p in five:
            solo[p][side].append((pts, q_opp, _others_q(five, (p,))))
        for a, b in combinations(sorted(five), 2):
            pair[(a, b)][side].append((pts, q_opp, _others_q(five, (a, b))))

    # remove the context terms from each possession's points. On offense a
    # better opposing (defensive) five suppresses points (b_def < 0) and
    # better teammates inflate them (b_off > 0); on defense the roles flip.
    def _adj_sum(rows, opp_slope, own_slope):
        tot = 0.0
        for pts, q_opp, q_own in rows:
            tot += (pts
                    - opp_slope * ((q_opp if q_opp is not None else qbar) - qbar)
                    - own_slope * ((q_own if q_own is not None else qbar) - qbar))
        return tot

    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}

    def _rates(rows):
        n_off, n_def = len(rows["off"]), len(rows["def"])
        off_pts = sum(p for p, _q, _o in rows["off"])
        def_pts = sum(p for p, _q, _o in rows["def"])
        ortg = 100 * _safe(off_pts, n_off)
        drtg = 100 * _safe(def_pts, n_def)
        if adjusted:
            a_ortg = 100 * _safe(_adj_sum(rows["off"], b_def, b_off), n_off)
            a_drtg = 100 * _safe(_adj_sum(rows["def"], b_off, b_def), n_def)
        else:
            a_ortg, a_drtg = ortg, drtg
        return n_off, n_def, off_pts, def_pts, ortg, drtg, a_ortg, a_drtg

    nodes = []
    for p, rows in solo.items():
        n_off, n_def, off_pts, def_pts, ortg, drtg, a_o, a_d = _rates(rows)
        nodes.append({
            "pid": p, "name": name_of.get(p, str(p)),
            "off_poss": n_off, "def_poss": n_def, "poss": n_off + n_def,
            "pts_for": off_pts, "pts_against": def_pts,
            "net": round(ortg - drtg, 1),
            "adj_net": round(a_o - a_d, 1),
        })
    nodes.sort(key=lambda d: -d["poss"])

    edges = []
    for (a, b), rows in pair.items():
        n_off, n_def, off_pts, def_pts, ortg, drtg, a_o, a_d = _rates(rows)
        poss = n_off + n_def
        if poss < min_poss:
            continue
        edges.append({
            "a": a, "b": b,
            "names": [name_of.get(a, str(a)), name_of.get(b, str(b))],
            "off_poss": n_off, "def_poss": n_def, "poss": poss,
            "pts_for": off_pts, "pts_against": def_pts,
            "ORtg": round(ortg, 1), "DRtg": round(drtg, 1),
            "net": round(ortg - drtg, 1),
            "AdjORtg": round(a_o, 1), "AdjDRtg": round(a_d, 1),
            "adj_net": round(a_o - a_d, 1),
        })
    edges.sort(key=lambda d: -d["adj_net"])
    return {"nodes": nodes, "edges": edges,
            "totals": {"pairs": len(pair), "drawn": len(edges),
                       "min_poss": min_poss, "adjusted": adjusted}}
