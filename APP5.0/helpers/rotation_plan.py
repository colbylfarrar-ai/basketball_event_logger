"""
rotation_plan.py — stagger / minutes optimizer + foul-trouble simulator (Tier 2).

Three rotation reads the app's gameflow.rotation (who-played-when) never turned into
decisions:

  star_coverage(team)
      Across tracked games, how much floor time has NONE of your key players on — and
      what does the team's net do in those "uncovered" minutes vs when a star is on?
      "When neither star is on you bleed X/100 over those minutes — stagger their
      rest." Time coverage from the rotation stints; the net bleed from a possession
      split (≥1 star on the floor vs none).

  foul_prone(team)
      Season fouls-per-32 per player, flagging the chronic foul-trouble guys before a
      game, not after.

  foul_out_projection(fouls, min_played, secs_left)
      The live in-game advisor: at the current foul pace, when does this player foul
      out, and is it a sit-now risk? Pure function — feeds the Game Tracker.

Pure data layer — reuses gameflow.rotation + lineups._event_floor + stats. No
streamlit. Everything volume-gated / flagged directional at this data scale.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.gameflow as GF
import helpers.lineups as LU

DEFAULT_TOP = 2          # how many key players define "covered" minutes
FOUL_LIMIT = 5           # HS foul-out
MIN_UNC_POSS = 20        # min uncovered possessions before the bleed is trustworthy
PRONE_PF32 = 4.0         # fouls-per-32 at/above which a player is "foul-prone"


def _team_game_ids(team_id):
    return [r["id"] for r in query(
        "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) AND tracked=1 "
        "AND season='Current'", (team_id, team_id))]


def _union_len(segments):
    """Total length of a set of (start, end) intervals after merging overlaps."""
    if not segments:
        return 0.0
    ivals = sorted(segments)
    total = 0.0
    cs, ce = ivals[0]
    for s, e in ivals[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            total += ce - cs
            cs, ce = s, e
    return total + (ce - cs)


def _top_by_minutes(team_id, gids, n):
    mins = defaultdict(float)
    names = {}
    for gid in gids:
        for r in GF.rotation(gid)["teams"].get(team_id, []):
            mins[r["player_id"]] += r["secs"]
            names[r["player_id"]] = r["name"]
    top = sorted(mins, key=lambda p: -mins[p])[:n]
    return [{"pid": p, "name": names.get(p, str(p)), "min": round(mins[p] / 60, 1)}
            for p in top]


def star_coverage(team_id, n=DEFAULT_TOP, game_ids=None, stars=None):
    """Star floor-time coverage + the net bleed when none of them are on.

    Returns {stars, uncovered_min_share, overlap_min_share, covered_net,
    uncovered_net, bleed, uncovered_poss, note}. `bleed` = covered_net −
    uncovered_net (per 100; positive = the team is worse with no star on).
    `stars` overrides the auto top-`n`-by-minutes selection."""
    gids = game_ids if game_ids is not None else _team_game_ids(team_id)
    star_rows = ([{"pid": p} for p in stars] if stars
                 else _top_by_minutes(team_id, gids, n))
    if not stars:
        named = star_rows
    else:
        nm = {r["id"]: r["name"] for r in query(
            "SELECT id, name FROM players WHERE team_id=?", (team_id,))}
        named = [{"pid": p, "name": nm.get(p, str(p)), "min": None} for p in stars]
    starset = {r["pid"] for r in named}

    # ── time coverage from the rotation stints ──
    tot_secs = cov_secs = 0.0
    star_secs = defaultdict(float)
    for gid in gids:
        rot = GF.rotation(gid)
        tot_secs += rot["end"] or 0
        segs = []
        for r in rot["teams"].get(team_id, []):
            if r["player_id"] in starset:
                segs.extend(r["segments"])
                star_secs[r["player_id"]] += r["secs"]
        cov_secs += _union_len(segs)
    uncovered_share = (tot_secs - cov_secs) / tot_secs if tot_secs else 0.0
    overlap_secs = max(0.0, sum(star_secs.values()) - cov_secs)
    overlap_share = overlap_secs / tot_secs if tot_secs else 0.0

    # ── net split: ≥1 star on the floor (covered) vs none (uncovered) ──
    events = S.fetch_events(gids) if gids else []
    floor = LU._event_floor(gids) if gids else {}
    buck = {"cov": {"op": 0, "opts": 0, "dp": 0, "dpts": 0},
            "unc": {"op": 0, "opts": 0, "dp": 0, "dpts": 0}}
    for e in events:
        if e["event_type"] not in ("shot", "turnover"):
            continue
        off_team = e["shooter_team_id"]
        if off_team is None:
            continue
        five = (floor.get(e["id"]) or {}).get(team_id)
        if not five:
            continue
        b = buck["cov"] if (starset & five) else buck["unc"]
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        if off_team == team_id:
            b["op"] += 1
            b["opts"] += pts
        else:
            b["dp"] += 1
            b["dpts"] += pts

    def _net(b):
        o = 100 * b["opts"] / b["op"] if b["op"] else None
        d = 100 * b["dpts"] / b["dp"] if b["dp"] else None
        net = round(o - d, 1) if (o is not None and d is not None) else None
        return net, b["op"] + b["dp"]

    cov_net, _ = _net(buck["cov"])
    unc_net, unc_poss = _net(buck["unc"])
    bleed = (round(cov_net - unc_net, 1)
             if (cov_net is not None and unc_net is not None) else None)

    if bleed is not None and bleed > 0 and unc_poss >= MIN_UNC_POSS \
            and uncovered_share >= 0.08:
        names = " & ".join(r.get("name", str(r["pid"])) for r in named)
        note = (f"When neither {names} is on, the team is {bleed:.1f}/100 worse "
                f"({unc_poss} uncovered poss, {uncovered_share * 100:.0f}% of minutes) "
                "— stagger their rest so one is always on.")
    elif unc_poss < MIN_UNC_POSS:
        note = ("Not enough uncovered minutes to measure the bench-only bleed yet.")
    else:
        note = ("Your stars' minutes already cover the floor well — little net lost "
                "when they rest.")
    return {
        "stars": named, "uncovered_min_share": round(uncovered_share, 3),
        "overlap_min_share": round(overlap_share, 3),
        "covered_net": cov_net, "uncovered_net": unc_net, "bleed": bleed,
        "uncovered_poss": unc_poss, "note": note,
    }


def foul_prone(team_id, game_ids=None, min_minutes=24):
    """Season fouls-per-32 per player, flagging the chronic foul-trouble guys.
    Returns a list (highest PF/32 first) of {pid,name,fouls,min,pf32,prone}."""
    gids = game_ids if game_ids is not None else _team_game_ids(team_id)
    events = S.fetch_events(gids) if gids else []
    mins = S.minutes_played(gids) if gids else {}
    fouls = defaultdict(int)
    for e in events:
        if e["event_type"] == "foul" and e["secondary_player_id"]:
            fouls[e["secondary_player_id"]] += 1
    roster = {r["id"]: r["name"]
              for r in query("SELECT id, name FROM players WHERE team_id=?", (team_id,))}
    out = []
    for pid, nm in roster.items():
        m = mins.get(pid, 0.0)
        f = fouls.get(pid, 0)
        if m < min_minutes or not f:
            continue
        pf32 = f / m * 32
        out.append({"pid": pid, "name": nm, "fouls": f, "min": round(m, 1),
                    "pf32": round(pf32, 1), "prone": pf32 >= PRONE_PF32})
    out.sort(key=lambda r: -r["pf32"])
    return out


def foul_out_projection(fouls, min_played, secs_left, foul_limit=FOUL_LIMIT):
    """Live foul-out advisor. At the player's current foul pace, project minutes to
    foul-out and a sit-now risk tier.

    Returns {fouls, pf32, to_foulout_min, will_foul_out, risk, note}. risk ∈
    {'out','high','med','low'}. Conservative: needs real floor time before it
    projects a pace."""
    fouls = int(fouls or 0)
    if fouls >= foul_limit:
        return {"fouls": fouls, "pf32": None, "to_foulout_min": 0.0,
                "will_foul_out": True, "risk": "out", "note": "Fouled out."}
    if not min_played or min_played <= 0 or fouls <= 0:
        return {"fouls": fouls, "pf32": 0.0, "to_foulout_min": None,
                "will_foul_out": False, "risk": "low", "note": ""}

    rate = fouls / min_played                    # fouls per floor-minute
    pf32 = rate * 32
    to_foulout = (foul_limit - fouls) / rate     # more floor-minutes to the limit
    min_left = max(secs_left, 0) / 60.0
    will = to_foulout <= min_left

    if fouls >= foul_limit - 1:
        risk = "high"                            # one foul from out
    elif will and to_foulout < min_left * 0.6:
        risk = "high"
    elif will:
        risk = "med"
    else:
        risk = "low"
    note = (f"{fouls} fouls · ~{pf32:.1f}/32 pace — on track to foul out in "
            f"~{to_foulout:.0f} more floor-min ({min_left:.0f} min left).")
    return {"fouls": fouls, "pf32": round(pf32, 1),
            "to_foulout_min": round(to_foulout, 1), "will_foul_out": will,
            "risk": risk, "note": note}
