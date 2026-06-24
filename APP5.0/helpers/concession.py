"""
concession.py — spatial defense-concession + shot-selection maps (Tier 2).

Rides on the xPP-Q league shot-quality model (helpers/shotquality.py) to answer two
game-prep questions the zone shooting tables can't:

  defense_concession(opp)
      Where does THIS defense give up shots — and good ones? Over the shots the team
      ALLOWED, per court zone: attempt share, points-per-shot allowed, the league-
      expected points from those exact looks (xPPS — shot quality conceded), and the
      residual (allowed − expected = do opponents finish above the look's value here).
      High xPPS zones = where to attack; high residual = where they also fail to
      contest.

  shot_selection(me)
      The self-scout twin over our OWN shots: same per-zone read, flagging where we
      OVER-shoot a spot we underperform (a residual leak) and where we UNDER-use a
      spot we're good at — "you over-shoot the right elbow, under-use the left corner."

Per-zone (not a kernel surface): at tens of games a smoothed 2D surface is noise, so
the 5 angular zones the app already derives are the honest, stable unit. Pure data
layer — reuses helpers.stats.located_shots + the xPP-Q model. No streamlit.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S
import helpers.shotquality as SQ

ZONE_ORDER = S.ZONES                       # ("LC","LW","C","RW","RC")
ZONE_LABELS = {"LC": "Left corner", "LW": "Left wing", "C": "Center / top",
               "RW": "Right wing", "RC": "Right corner"}

MIN_ZONE = 5            # min attempts before a zone earns a read
OVERSHOOT_SHARE = 0.18  # share of our shots from a zone to call it "heavily used"
UNDERUSE_SHARE = 0.10   # share below which a good zone is "under-used"


def _team_game_ids(team_id):
    return [r["id"] for r in query(
        "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) AND tracked=1 "
        "AND season='Current'", (team_id, team_id))]


def allowed_shots(team_id, game_ids=None):
    """Located shots this team ALLOWED (opponents' shots in its tracked games)."""
    gids = game_ids if game_ids is not None else _team_game_ids(team_id)
    ev = S.fetch_events(gids) if gids else []
    return [s for s in S.located_shots(events=ev) if s["team_id"] != team_id]


def own_shots(team_id, game_ids=None):
    """The team's OWN located shots."""
    gids = game_ids if game_ids is not None else _team_game_ids(team_id)
    ev = S.fetch_events(gids) if gids else []
    return S.located_shots(events=ev, team_id=team_id)


def zone_breakdown(shots, model):
    """Per-zone {zone,label,n,share,pps,xpps,residual} over `shots`, scored against
    the xPP-Q `model`. Returns (rows, total, overall_xpps). Empty zones carry None
    rates so every caller shows the same five rows."""
    agg = {z: {"n": 0, "pts": 0.0, "xpts": 0.0} for z in ZONE_ORDER}
    tot = 0
    tot_x = 0.0
    for s in shots:
        z = s.get("zone")
        if z not in agg:
            continue
        a = agg[z]
        a["n"] += 1
        tot += 1
        if s["make"]:
            a["pts"] += s["value"]
        xp = SQ.expected_points_shot(s, model)
        a["xpts"] += xp
        tot_x += xp
    rows = []
    for z in ZONE_ORDER:
        a = agg[z]
        n = a["n"]
        if not n:
            rows.append({"zone": z, "label": ZONE_LABELS[z], "n": 0, "share": 0.0,
                         "pps": None, "xpps": None, "residual": None})
            continue
        pps, xpps = a["pts"] / n, a["xpts"] / n
        rows.append({"zone": z, "label": ZONE_LABELS[z], "n": n,
                     "share": n / tot if tot else 0.0,
                     "pps": round(pps, 3), "xpps": round(xpps, 3),
                     "residual": round(pps - xpps, 3)})
    return rows, tot, (tot_x / tot if tot else 0.0)


def defense_concession(team_id=None, model=None, game_ids=None, shots=None):
    """Where a defense concedes. Returns {rows, total, leaks, locked, note}.
      leaks  — zones (n>=MIN_ZONE) whose conceded shot quality (xPPS) is above the
               defense's own average, worst first → "attack here."
      locked — zones held below average xPPS → "they protect this."
    Pass `shots` directly (the allowed shots) or a team_id to pull them."""
    if shots is None:
        shots = allowed_shots(team_id, game_ids=game_ids)
    rows, total, avg_x = zone_breakdown(shots, model)
    ranked = [r for r in rows if r["n"] >= MIN_ZONE and r["xpps"] is not None]
    leaks = sorted([r for r in ranked if r["xpps"] > avg_x],
                   key=lambda r: -r["xpps"])
    locked = sorted([r for r in ranked if r["xpps"] <= avg_x],
                    key=lambda r: r["xpps"])
    note = ("Zones with the highest conceded shot quality (xPPS) are where this "
            "defense gives up the best looks — attack there."
            if leaks else
            "Not enough located shots allowed to map concession yet.")
    return {"rows": rows, "total": total, "leaks": leaks, "locked": locked,
            "note": note}


def shot_selection(team_id=None, model=None, game_ids=None, shots=None):
    """Our shot-selection efficiency by zone. Returns {rows, total, overshoot,
    underused, note}.
      overshoot — zones we lean on (share>=OVERSHOOT_SHARE) but underperform the
                  expected value at (residual<0) → stop forcing these.
      underused — zones we're good at (residual>0) but barely use
                  (share<=UNDERUSE_SHARE) → get more of these.
    Pass `shots` directly (our own shots) or a team_id to pull them."""
    if shots is None:
        shots = own_shots(team_id, game_ids=game_ids)
    rows, total, _ = zone_breakdown(shots, model)
    ranked = [r for r in rows if r["n"] >= MIN_ZONE and r["residual"] is not None]
    overshoot = sorted([r for r in ranked
                        if r["share"] >= OVERSHOOT_SHARE and r["residual"] < 0],
                       key=lambda r: r["residual"])
    underused = sorted([r for r in ranked
                        if r["share"] <= UNDERUSE_SHARE and r["residual"] > 0],
                       key=lambda r: -r["residual"])
    note = ("Over-used zones you underperform = stop forcing; efficient zones you "
            "barely use = get more of these."
            if (overshoot or underused) else
            "Shot selection is balanced across zones (or too few located shots yet).")
    return {"rows": rows, "total": total, "overshoot": overshoot,
            "underused": underused, "note": note}
