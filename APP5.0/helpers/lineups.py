"""
lineups.py — Observed 5-man unit ratings (who actually plays well together).

The Team Analytics page *simulates* lineups; this measures the real thing. From
the per-event 10-man on-court data it reconstructs every distinct 5-player unit
a team actually used and scores it: points produced per 100 possessions while
that exact five was on offense, points allowed per 100 while on defense, and the
net. This is the EvanMiya / DataBallR lineup explorer, computed from your own
possessions — the complement to RAPM (units vs individuals).

Possessions follow the app's locked rule (a shot or a turnover); free-throw
points are excluded from the per-possession scoring, consistent with [[rapm]].

Pure data layer: database.db + helpers.stats only. No streamlit, no numpy.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S


DEFAULT_MIN_POSS = 12   # a unit needs this many possessions to be reportable


def _safe(num, den):
    return num / den if den else 0.0


def _event_floor(game_ids=None):
    """{event_id: {team_id: frozenset(player_ids)}} for the on-court sets."""
    clause, params = S._game_filter(game_ids)
    lin = query(
        f"""SELECT gel.event_id eid, gel.player_id pid, gel.team_id tid
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            WHERE 1=1{clause}""",
        params,
    )
    tmp = defaultdict(lambda: defaultdict(set))
    for r in lin:
        tmp[r["eid"]][r["tid"]].add(r["pid"])
    return {eid: {tid: frozenset(s) for tid, s in teams.items()}
            for eid, teams in tmp.items()}


def unit_ratings(team_id, game_ids=None, events=None, min_poss=DEFAULT_MIN_POSS):
    """
    Observed 5-man unit ratings for one team.

    Returns a list of dicts (sorted by Net desc), one per distinct five that
    cleared `min_poss` total possessions:
        players (sorted pid tuple), names, off_poss, def_poss, poss,
        ORtg, DRtg, Net  (per 100 possessions), pts_for, pts_against
    Off/def possessions are counted separately (a unit is on the floor for both
    ends), so ORtg uses offensive possessions and DRtg uses defensive ones.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    floor = _event_floor(game_ids)

    units = defaultdict(lambda: {"off_poss": 0, "off_pts": 0,
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
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        if off_team == team_id:
            five = sets.get(team_id)
            if five and len(five) == 5:
                u = units[five]
                u["off_poss"] += 1
                u["off_pts"] += pts
        else:
            # team_id is on defense this possession; its five is the non-offense set
            five = sets.get(team_id)
            if five and len(five) == 5:
                u = units[five]
                u["def_poss"] += 1
                u["def_pts"] += pts

    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}
    out = []
    for five, u in units.items():
        poss = u["off_poss"] + u["def_poss"]
        if poss < min_poss:
            continue
        ortg = 100 * _safe(u["off_pts"], u["off_poss"])
        drtg = 100 * _safe(u["def_pts"], u["def_poss"])
        out.append({
            "players": tuple(sorted(five)),
            "names": [name_of.get(p, str(p)) for p in sorted(five)],
            "off_poss": u["off_poss"], "def_poss": u["def_poss"], "poss": poss,
            "pts_for": u["off_pts"], "pts_against": u["def_pts"],
            "ORtg": round(ortg, 1), "DRtg": round(drtg, 1),
            "Net": round(ortg - drtg, 1),
        })
    out.sort(key=lambda d: -d["Net"])
    return out


def custom_unit(team_id, player_ids, game_ids=None, events=None):
    """
    On-court ratings for an ARBITRARY player set — every possession where all of
    `player_ids` were on the floor together for `team_id` (a subset match, so
    picking 2–5 players works; pick 5 for an exact lineup). Returns one dict:
        off_poss, def_poss, poss, pts_for, pts_against, ORtg, DRtg, Net, PPP.
    Same possession rule and FT exclusion as unit_ratings.
    """
    want = frozenset(player_ids)
    if not want:
        return {"off_poss": 0, "def_poss": 0, "poss": 0, "pts_for": 0,
                "pts_against": 0, "ORtg": 0.0, "DRtg": 0.0, "Net": 0.0, "PPP": 0.0}
    if events is None:
        events = S.fetch_events(game_ids)
    floor = _event_floor(game_ids)
    off_poss = off_pts = def_poss = def_pts = 0
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
        if not five or not want.issubset(five):
            continue
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        if off_team == team_id:
            off_poss += 1
            off_pts += pts
        else:
            def_poss += 1
            def_pts += pts
    ortg = 100 * _safe(off_pts, off_poss)
    drtg = 100 * _safe(def_pts, def_poss)
    return {
        "off_poss": off_poss, "def_poss": def_poss, "poss": off_poss + def_poss,
        "pts_for": off_pts, "pts_against": def_pts,
        "ORtg": round(ortg, 1), "DRtg": round(drtg, 1), "Net": round(ortg - drtg, 1),
        "PPP": round(_safe(off_pts, off_poss), 2),
    }


def player_unit_summary(team_id, game_ids=None, min_poss=DEFAULT_MIN_POSS):
    """
    Per-player rollup over the reportable units they appear in: total possessions
    and possession-weighted Net. A quick "who lifts the lineups they're in" read.
    Returns {pid: {"name","poss","wnet"}}.
    """
    units = unit_ratings(team_id, game_ids=game_ids, min_poss=min_poss)
    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}
    agg = defaultdict(lambda: {"poss": 0, "netposs": 0.0})
    for u in units:
        for p in u["players"]:
            agg[p]["poss"] += u["poss"]
            agg[p]["netposs"] += u["Net"] * u["poss"]
    return {p: {"name": name_of.get(p, str(p)), "poss": a["poss"],
                "wnet": round(_safe(a["netposs"], a["poss"]), 1)}
            for p, a in agg.items()}
