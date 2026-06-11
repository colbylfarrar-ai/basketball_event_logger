"""
matchups.py — Defensive matchup intelligence (who guarded whom).

APP5.0 logs `guarded_by_id` on every shot, but only ever used it for a single
number (DSHOT%, the FG% a defender allows). That same field is a full matchup
grid: every contested shot is a (defender, shooter) pair, so we can reconstruct
who each defender was assigned to, how those shooters fared, and — crucially —
how *hard* each defender's assignments were (Basketball-Index's "Matchup
Difficulty": guarding the other team's best scorer all night is worth more than
hiding on their weakest). NBA.com's Matchups page is the pro analogue.

What it surfaces:
  * per-defender shot defense (FGA faced, FGM allowed, FG% / points allowed)
  * the by-shooter breakdown (the actual assignments)
  * by-zone breakdown of where they're attacked
  * Matchup Difficulty — opponent-scorer quality faced, attempt-weighted

Pure data layer: depends on database.db + helpers.stats only, never streamlit.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S


_safe = S._safe   # shared definition lives in helpers.stats


def player_names(gender=None):
    """{player_id: {'name','number','team_id','team','class'}} for label lookups."""
    clause = "WHERE t.gender = ?" if gender else ""
    params = (gender,) if gender else ()
    rows = query(
        f"""SELECT p.id, p.name, p.number, p.team_id,
                   t.name AS team, t.class AS class
            FROM players p JOIN teams t ON t.id = p.team_id {clause}""",
        params,
    )
    return {r["id"]: {"name": r["name"], "number": r["number"],
                      "team_id": r["team_id"], "team": r["team"],
                      "class": r["class"]} for r in rows}


# ══════════════════════════════════════════════════════════════════════════════
#  MATCHUP GRID
# ══════════════════════════════════════════════════════════════════════════════

def matchup_table(game_ids=None, events=None):
    """
    Per-defender shot-defense profile from every contested shot.

    Returns {defender_id: {
        "FGA", "FGM", "pts_allowed", "FG%",          totals as the contester
        "made_allowed_3", "fga_3",                   three-point splits
        "by_shooter": {shooter_id: {"FGA","FGM","pts","FG%"}},
        "by_zone":    {zone: {"FGA","FGM","FG%"}},
        "assignments": int,                          distinct shooters guarded
        "top_shooter": shooter_id | None,            most-faced assignment
    }}

    Only shot events carrying a `guarded_by_id` contribute. Lower FG%/points
    allowed = better on-ball defense.
    """
    if events is None:
        events = S.fetch_events(game_ids)

    out = defaultdict(lambda: {
        "FGA": 0, "FGM": 0, "pts_allowed": 0, "fga_3": 0, "made_allowed_3": 0,
        "by_shooter": defaultdict(lambda: {"FGA": 0, "FGM": 0, "pts": 0}),
        "by_zone": defaultdict(lambda: {"FGA": 0, "FGM": 0}),
    })

    for e in events:
        if e["event_type"] != "shot":
            continue
        d = e["guarded_by_id"]
        if d is None:
            continue
        s = e["primary_player_id"]
        made = e["shot_result"] == "make"
        val = 3 if e["shot_type"] == 3 else 2
        pts = val if made else 0

        rec = out[d]
        rec["FGA"] += 1
        rec["FGM"] += 1 if made else 0
        rec["pts_allowed"] += pts
        if val == 3:
            rec["fga_3"] += 1
            rec["made_allowed_3"] += 1 if made else 0

        sh = rec["by_shooter"][s]
        sh["FGA"] += 1
        sh["FGM"] += 1 if made else 0
        sh["pts"] += pts

        z = e["zone"]
        if z:
            zc = rec["by_zone"][z]
            zc["FGA"] += 1
            zc["FGM"] += 1 if made else 0

    final = {}
    for d, rec in out.items():
        by_shooter = {s: {**v, "FG%": round(100 * _safe(v["FGM"], v["FGA"]), 1)}
                      for s, v in rec["by_shooter"].items()}
        by_zone = {z: {**v, "FG%": round(100 * _safe(v["FGM"], v["FGA"]), 1)}
                   for z, v in rec["by_zone"].items()}
        top = max(by_shooter, key=lambda s: by_shooter[s]["FGA"], default=None)
        final[d] = {
            "FGA": rec["FGA"], "FGM": rec["FGM"], "pts_allowed": rec["pts_allowed"],
            "FG%": round(100 * _safe(rec["FGM"], rec["FGA"]), 1),
            "fga_3": rec["fga_3"], "made_allowed_3": rec["made_allowed_3"],
            "by_shooter": by_shooter, "by_zone": by_zone,
            "assignments": len(by_shooter), "top_shooter": top,
        }
    return final


# ══════════════════════════════════════════════════════════════════════════════
#  MATCHUP DIFFICULTY  (how good were the shooters this defender faced)
# ══════════════════════════════════════════════════════════════════════════════

def matchup_difficulty(game_ids=None, events=None, strength=None, table=None,
                       strength_key="OFFENSE"):
    """
    Attempt-weighted quality of the shooters each defender guarded.

    `strength` is a {player_id: scorer_quality} map; if omitted it is read from
    `table` (a player_stat_table mapping) using `strength_key` (default the
    OFFENSE rating, falling back to PPG). A defender who spends the night on the
    opponent's best scorer scores high; one hidden on weak shooters scores low.

    Returns {defender_id: {"difficulty": weighted_avg_strength,
                           "shots_faced": n, "Difficulty100": 0-100 index}}.
    The 0-100 index is league-relative (50 = average assignment difficulty).
    """
    if strength is None:
        strength = {}
        if table:
            for pid, row in table.items():
                v = row.get(strength_key)
                if v is None:
                    v = row.get("PPG")
                if v is not None:
                    strength[pid] = v
    mt = matchup_table(game_ids, events)

    raw = {}
    for d, rec in mt.items():
        num = den = 0.0
        for s, sv in rec["by_shooter"].items():
            q = strength.get(s)
            if q is None:
                continue
            num += q * sv["FGA"]
            den += sv["FGA"]
        if den > 0:
            raw[d] = {"difficulty": round(num / den, 1), "shots_faced": int(den)}

    # league-relative 0-100 (50 = average, +10 per SD)
    vals = [v["difficulty"] for v in raw.values()]
    if vals:
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        for d in raw:
            z = (raw[d]["difficulty"] - mean) / sd if sd > 1e-9 else 0.0
            raw[d]["Difficulty100"] = round(S.scale100(z), 1)
    return raw


def team_matchup_rows(team_id, game_ids=None, events=None, names=None):
    """
    Flattened (defender → shooter) rows for one team's defenders, ready for a
    table: [{defender, def_#, shooter, shooter_team, FGA, FGM, FG%, pts}], sorted
    by attempts. `names` is a player_names() map (fetched if omitted).
    """
    if names is None:
        names = player_names()
    mt = matchup_table(game_ids, events)
    rows = []
    for d, rec in mt.items():
        dm = names.get(d)
        if not dm or dm["team_id"] != team_id:
            continue
        for s, sv in rec["by_shooter"].items():
            sm = names.get(s, {})
            rows.append({
                "defender": dm["name"], "def_#": dm["number"],
                "shooter": sm.get("name", str(s)),
                "shooter_team": sm.get("team", ""),
                "FGA": sv["FGA"], "FGM": sv["FGM"], "FG%": sv["FG%"],
                "pts": sv["pts"],
            })
    rows.sort(key=lambda r: -r["FGA"])
    return rows
