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
from helpers.stats import _team_game_ids   # single-source shared helper
import helpers.gameflow as GF
import helpers.lineups as LU

DEFAULT_TOP = 2          # how many key players define "covered" minutes
FOUL_LIMIT = 5           # HS foul-out
MIN_UNC_POSS = 20        # min uncovered possessions before the bleed is trustworthy
PRONE_PF32 = 4.0         # fouls-per-32 at/above which a player is "foul-prone"


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


# How long the stars can all sit before it is worth saying something, and how
# long before it is worth saying it loudly. A whole quarter is 8 minutes, so two
# and four minutes are "a long rest" and "most of a quarter".
STARS_OFF_NOTE_SECS = 120
STARS_OFF_ALERT_SECS = 240


def _tracked_games_in_season_of(team_id, game_id):
    """The team's tracked games in THE GAME'S OWN season.

    Not stats._team_game_ids, which hardcodes season='Current'. A live game is
    usually in the active season and the two agree — but right after a rollover
    the active-season sentinel holds no games at all, and a default scoped to it
    would quietly report that the team has no key players rather than reading
    the season the game actually belongs to."""
    return [r["id"] for r in query(
        """SELECT g.id FROM games g
           WHERE (g.team1_id=? OR g.team2_id=?) AND g.tracked=1
             AND g.season = (SELECT season FROM games WHERE id=?)""",
        (team_id, team_id, game_id))]


def live_star_watch(team_id, game_id, now_secs, n=DEFAULT_TOP, stars=None,
                    season_game_ids=None):
    """The LIVE twin of star_coverage: are your key players on the floor right
    now, and if not, how long have they all been off together?

    star_coverage answers this after the fact, over a season — "you bleed X/100
    in the minutes neither star is on". That is a planning read. The decision it
    implies is made during a game, with a clock running, and nothing was telling
    a coach they were four minutes into exactly those minutes.

    `now_secs` is elapsed game seconds at the latest logged event (the caller
    already computes it for the win-probability and foul-watch strips; taking it
    keeps one clock model). `stars` overrides the auto top-`n`-by-minutes pick,
    which is drawn from the team's OTHER tracked games — a live game's partial
    minutes must not decide who counts as a star.

    Returns {stars, on, off, off_secs, bleed, risk, note}. `risk` is 'low' while
    a star is on, then 'note' / 'alert' by how long they have all been off.
    Never raises: a game with no lineup snapshots returns risk 'low'."""
    prior = [g for g in (season_game_ids if season_game_ids is not None
                         else _tracked_games_in_season_of(team_id, game_id))
             if g != game_id]
    star_rows = ([{"pid": p} for p in stars] if stars
                 else _top_by_minutes(team_id, prior, n))
    if not star_rows:
        return {"stars": [], "on": [], "off": [], "off_secs": 0.0,
                "bleed": None, "risk": "low", "note": ""}
    if stars:
        nm = {r["id"]: r["name"] for r in query(
            "SELECT id, name FROM players WHERE team_id=?", (team_id,))}
        star_rows = [{"pid": p, "name": nm.get(p, str(p))} for p in stars]
    starset = {r["pid"] for r in star_rows}
    name_of = {r["pid"]: r.get("name", str(r["pid"])) for r in star_rows}

    rot = GF.rotation(game_id)
    mine = [r for r in rot["teams"].get(team_id, []) if r["player_id"] in starset]

    # Every second a star was on, merged — the same union star_coverage takes,
    # here so "off together" means off together and not merely subbed apart.
    covered = _union_len([s for r in mine for s in r["segments"]])
    on_now, last_on_end = [], 0.0
    for r in mine:
        for s, e in r["segments"]:
            if s <= now_secs <= e:
                on_now.append(name_of.get(r["player_id"], r["name"]))
                break
        last_on_end = max([last_on_end] + [e for _s, e in r["segments"]
                                           if e <= now_secs])

    off_secs = 0.0 if on_now else max(0.0, now_secs - last_on_end)
    risk = ("low" if on_now
            else "alert" if off_secs >= STARS_OFF_ALERT_SECS
            else "note" if off_secs >= STARS_OFF_NOTE_SECS
            else "low")

    bleed = None
    if prior:
        try:
            bleed = star_coverage(team_id, n=n, game_ids=prior,
                                  stars=sorted(starset))["bleed"]
        except Exception:
            bleed = None

    names = " & ".join(name_of[p] for p in sorted(starset,
                                                  key=lambda p: name_of[p]))
    if on_now:
        note = f"{', '.join(sorted(on_now))} on the floor."
    elif risk == "low":
        note = f"{names} resting ({off_secs / 60:.1f} min)."
    else:
        cost = (f" — you have been {bleed:.1f}/100 worse in these minutes "
                f"this season" if bleed and bleed > 0 else "")
        # "has", "have both", "have all" — the star count is a setting, so the
        # sentence has to survive n != 2.
        verb = ("has" if len(starset) == 1
                else "have both" if len(starset) == 2 else "have all")
        note = (f"{names} {verb} been off for {off_secs / 60:.1f} min"
                f"{cost}.")
    return {"stars": star_rows, "on": sorted(on_now),
            "off": sorted(name_of[p] for p in starset
                          if name_of[p] not in on_now),
            "off_secs": round(off_secs, 1),
            "covered_secs": round(covered, 1),
            "bleed": bleed, "risk": risk, "note": note}


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
