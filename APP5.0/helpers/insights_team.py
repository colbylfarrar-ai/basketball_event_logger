"""
insights_team.py — TEAM-level deep-dive splits for the Insights tab.

The player auto-scout lives in helpers/insights.py; this is the team read: how a
team's OWN offense changes by context. First split: opponent strength — does the
team keep scoring against top teams, or feast only on weak ones? Reuses the
play-type profile machinery (eFG / SCE / 3PA-rate / rim-rate / assisted / open /
zone) so the splits speak the same language as the rest of the app.

Streamlit-free (engines + sqlite). Scoped to the team's OWN shots in the passed
games, so there is no cross-game leak.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S
import helpers.playtypes as PT
import helpers.team_ratings as TR

MIN_SPLIT_SHOTS = 15        # a side needs this many shots before its split is shown

# ── "Team at a glance" — the stats a team is most DEFINED by ───────────────────
# (team_stat_table label, higher_better [None=neutral identity], category,
#  high-percentile tag, low-percentile tag). One stat per category surfaces, so
# the glance stays diverse (not five shooting stats). higher_better feeds the
# percentile direction so "high pct" always means the good/notable end of the tag.
_GLANCE_SPEC = [
    ("Pace",      None,  "tempo",       "plays fast",                "grind-it-out pace"),
    ("3PAr",      None,  "shot profile", "bombs away from three",    "rarely shoots threes"),
    ("Paint pt%", None,  "shot profile", "scores inside",            "perimeter-oriented"),
    ("eFG%",      True,  "shooting",    "shoots it well",            "poor shooting team"),
    ("3P%",       True,  "shooting",    "hot from deep",             "cold from deep"),
    ("FTr",       True,  "aggression",  "attacks the rim / line",    "settles for jumpers"),
    ("ORtg",      True,  "offense",     "high-powered offense",      "offense struggles"),
    ("DRtg",      False, "defense",     "elite defense",             "leaky defense"),
    ("Opp eFG%",  False, "defense",     "contests everything",       "gives up clean looks"),
    ("ORB%",      True,  "rebounding",  "crashes the offensive glass", "one-and-done offense"),
    ("DRB%",      True,  "rebounding",  "owns the defensive glass",  "gives up second chances"),
    ("TOV%",      False, "ball control", "protects the ball",        "turnover-prone"),
    ("AST%",      True,  "ball movement", "moves the ball",          "iso-heavy"),
    ("STL/G",     True,  "pressure",    "ball-hawking defense",      "low-pressure defense"),
    ("MOV",       True,  "results",     "wins by a lot",             "plays close / loses"),
]


_GAME_TYPE_ORDER = {"Regular": 0, "District": 1, "Rivalry": 2, "Tournament": 3,
                    "Showcase": 4, "Playoff": 5}


def team_by_game_type(team_id, gender=None, season="Current"):
    """How the team plays by GAME TYPE (Regular / District / Playoff / …). Per
    type: record (W-L) + avg margin from every played game, plus — for the TRACKED
    games of that type — efficiency (off/def points-per-possession, eFG%/opp eFG%,
    pace) and shot mix (rim / 3-point attempt rate). Returns a list ordered
    Regular→Playoff; [] when the team has no played games. Tracked-only fields are
    None when a type has no tracked game."""
    import helpers.team_analytics as TA          # lazy — avoids an import cycle
    from collections import defaultdict
    gs = query(
        """SELECT id, game_type, team1_id, home_score, away_score, tracked
           FROM games
           WHERE (team1_id=? OR team2_id=?) AND season=?
             AND home_score IS NOT NULL AND away_score IS NOT NULL""",
        (team_id, team_id, season))
    if not gs:
        return []
    buckets = defaultdict(lambda: {"trk": [], "W": 0, "L": 0, "mov": 0, "n": 0})
    for r in gs:
        gt = r["game_type"] or "Regular"
        us = r["home_score"] if r["team1_id"] == team_id else r["away_score"]
        them = r["away_score"] if r["team1_id"] == team_id else r["home_score"]
        b = buckets[gt]
        b["n"] += 1
        b["mov"] += (us - them)
        if r["tracked"]:
            b["trk"].append(r["id"])
        if us > them:
            b["W"] += 1
        elif us < them:
            b["L"] += 1

    out = []
    for gt, b in buckets.items():
        row = {"type": gt, "GP": b["n"], "W": b["W"], "L": b["L"],
               "MOV": round(b["mov"] / b["n"], 1) if b["n"] else None,
               "trk_gp": len(b["trk"])}
        if b["trk"]:
            ev = S.fetch_events(b["trk"])
            tb, ob = TA.team_and_opp_box(team_id, b["trk"], events=ev)
            _poss = lambda x: (x.get("FGA", 0) + x.get("TOV", 0)) or 0
            op, dp = _poss(tb), _poss(ob)
            rim = mid = three = tot = 0
            for e in ev:
                if e.get("event_type") != "shot" or e.get("shooter_team_id") != team_id:
                    continue
                tot += 1
                if e.get("shot_type") == 3:
                    three += 1
                elif e.get("zone") == "C":
                    rim += 1
                else:
                    mid += 1
            row.update({
                "oPPP": round(tb["PTS"] / op, 2) if op else None,
                "dPPP": round(ob["PTS"] / dp, 2) if dp else None,
                "eFG": round(S.efg(tb) * 100) if tb.get("FGA") else None,
                "oeFG": round(S.efg(ob) * 100) if ob.get("FGA") else None,
                "pace": round(op / len(b["trk"]), 1) if op else None,
                "rim%": round(rim / tot * 100) if tot else None,
                "3PA%": round(three / tot * 100) if tot else None,
            })
        out.append(row)
    out.sort(key=lambda r: _GAME_TYPE_ORDER.get(r["type"], 9))
    return out


def team_glance(gender, team_id, n=6, season="Current"):
    """The 4-8 stats this team is MOST distinctive on vs the league — a quick
    identity fingerprint. Percentile-ranks the team on each curated stat, keeps
    the single most-extreme stat per category (so the read stays diverse), and
    returns them most-distinctive first: [{label, value, pct, tag, good, dist}].
    Empty when the team isn't in the tracked table. `season` scopes the field to
    one season (archive views)."""
    import helpers.league_analytics as LA        # lazy — avoids an import cycle
    row = query("SELECT name FROM teams WHERE id=?", (team_id,))
    if not row:
        return []
    name = row[0]["name"]
    rows = LA.team_stat_table(gender=gender, season=season)
    me = next((r for r in rows if r.get("Team") == name), None)
    if not me or len(rows) < 5:
        return []
    by_cat = {}
    for label, hb, cat, hi_tag, lo_tag in _GLANCE_SPEC:
        myv = me.get(label)
        if not isinstance(myv, (int, float)):
            continue
        pool = [r[label] for r in rows if isinstance(r.get(label), (int, float))]
        if len(pool) < 5:
            continue
        pct = S.percentile(myv, pool, higher_better=(True if hb is None else hb))
        if pct is None:
            continue
        item = {"label": label, "value": myv, "pct": round(pct),
                "dist": abs(pct - 50),
                "tag": (hi_tag if pct >= 50 else lo_tag),
                "good": (None if hb is None else pct >= 50)}
        if cat not in by_cat or item["dist"] > by_cat[cat]["dist"]:
            by_cat[cat] = item
    return sorted(by_cat.values(), key=lambda d: -d["dist"])[:n]


def _team_game_opponents(team_id, game_ids=None):
    """{game_id: opponent_team_id} for the team's tracked games. With no
    `game_ids` this defaults to the CURRENT season; a passed set is trusted as
    already season-scoped (the dashboard hands the bundle's season ids), so an
    archive view isn't filtered down to nothing by the Current clause."""
    if game_ids is not None:
        allow = set(game_ids)
        if not allow:
            return {}
        ph = ",".join("?" * len(allow))
        rows = query(
            f"SELECT id, team1_id, team2_id FROM games "
            f"WHERE id IN ({ph}) AND (team1_id=? OR team2_id=?) AND tracked=1",
            tuple(allow) + (team_id, team_id))
    else:
        rows = query(
            "SELECT id, team1_id, team2_id FROM games "
            "WHERE (team1_id=? OR team2_id=?) AND tracked=1 AND season='Current'",
            (team_id, team_id))
    return {r["id"]: (r["team2_id"] if r["team1_id"] == team_id else r["team1_id"])
            for r in rows}


def passer_quality(gender=None, game_ids=None, events=None, rates=None, min_feeds=8):
    """Per-PASSER shot-creation quality — the "pass-from FG%" read, split into the
    two things it conflates:
      • xPPS_created — the expected value of the LOOKS a passer creates (from the
        shot's zone/creation/contest, independent of whether it went in). High = the
        passer sets up good shots. This is the passer's own playmaking signal.
      • PPS / FG% — what those looks ACTUALLY produced.
      • finish_delta = PPS − xPPS_created — did the shooters convert the looks? A
        big POSITIVE gap = great finishers (or lucky); a big NEGATIVE gap = a GOOD
        pass to a POOR shooter (the look was there, the shot missed).
    So a low pass-from FG% with a HIGH xPPS_created is a good playmaker feeding poor
    shooters — not a bad passer. Returns {passer_id: {feeds, FG%, PPS, xPPS_created,
    finish_delta, team_id}} for passers with ≥ min_feeds assisted attempts."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    if rates is None:
        rates = S.shot_quality_rates(events=events)
    agg = {}
    for e in events:
        if e["event_type"] != "shot":
            continue
        passer = e.get("pass_from_id")
        if passer is None:
            continue
        key = (e["zone"],
               S._creation_bucket(True, e["shot_created_by_id"] is not None),
               e["guarded_by_id"] is not None)
        xpct = rates.get(key, {}).get("pct", 0.0)
        val = 3 if e["shot_type"] == 3 else 2
        c = agg.setdefault(passer, {"feeds": 0, "FGM": 0, "pts": 0, "xpts": 0.0,
                                    "team_id": e["shooter_team_id"]})
        c["feeds"] += 1
        c["xpts"] += xpct * val
        if e["shot_result"] == "make":
            c["FGM"] += 1
            c["pts"] += val
    out = {}
    for pid, c in agg.items():
        if c["feeds"] < min_feeds:
            continue
        f = c["feeds"]
        pps, xpps = c["pts"] / f, c["xpts"] / f
        out[pid] = {"feeds": f, "FG%": c["FGM"] / f, "PPS": pps,
                    "xPPS_created": xpps, "finish_delta": pps - xpps,
                    "team_id": c["team_id"]}
    return out


_ZONE_SIDE = {"LC": "Left", "LW": "Left", "C": "Middle", "RW": "Right", "RC": "Right"}
_ZONE_LABEL = {"LC": "Left corner", "LW": "Left wing", "C": "Paint / middle",
               "RW": "Right wing", "RC": "Right corner"}
MIN_TENDENCY_SHOTS = 30


def shot_tendencies(team_id, gender=None, game_ids=None, events=None):
    """Self-scout shot map from ZONE (present on every shot, so it's dense): where
    this team's own shots come from and how they score there — the "force them left/
    right, here's where they live" read a scout builds. Returns {available, total,
    side (Left/Middle/Right shares), zones [{zone,label,poss,share,PPP,FG%}], plus
    rim/mid/three rate}. Robust without the sparse play-type/defense tags."""
    if events is None:
        gids = list(_team_game_opponents(team_id, game_ids))
        events = S.fetch_events(gids) if gids else []
    zc = {z: {"FGA": 0, "FGM": 0, "PTS": 0} for z in _ZONE_LABEL}
    side = {"Left": 0, "Middle": 0, "Right": 0}
    rim = mid = three = total = 0
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] != team_id:
            continue
        total += 1
        is3 = e["shot_type"] == 3
        made = e["shot_result"] == "make"
        z = e.get("zone")
        if is3:
            three += 1
        elif z == "C":
            rim += 1
        else:
            mid += 1
        if z in zc:
            c = zc[z]
            c["FGA"] += 1
            if made:
                c["FGM"] += 1
                c["PTS"] += 3 if is3 else 2
            side[_ZONE_SIDE[z]] += 1
    if total < MIN_TENDENCY_SHOTS:
        return {"available": False, "total": total}
    zoned = sum(side.values()) or 1
    zones = [{"zone": z, "label": _ZONE_LABEL[z], "poss": c["FGA"],
              "share": c["FGA"] / zoned,
              "PPP": (c["PTS"] / c["FGA"]) if c["FGA"] else None,
              "FG%": (c["FGM"] / c["FGA"]) if c["FGA"] else None}
             for z, c in zc.items()]
    return {
        "available": True, "total": total,
        "side": {k: v / zoned for k, v in side.items()},
        "zones": zones,
        "rim_rate": rim / total, "mid_rate": mid / total, "three_rate": three / total,
    }


def _bucket_profiles(team_id, events, bucket_of, labels):
    """Build a finished play-type-style profile of the team's OWN shots per bucket.
    ``bucket_of(game_id)`` returns a bucket key (or None to skip); ``labels`` maps
    bucket key -> display label. No cross-game leak (own shots only)."""
    profs = {k: PT._blank_profile() for k in labels}
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] != team_id:
            continue
        b = bucket_of(e["game_id"])
        if b in profs:
            PT._profile_add(profs[b], e)
    return {k: PT._profile_fin(p, k, labels[k]) for k, p in profs.items()}


def winloss_splits(team_id, gender=None, game_ids=None, events=None):
    """The team's own-offense profile split by RESULT — how it plays in WINS vs
    LOSSES (what makes it go, what shows up when it loses). Same profile fields as
    strength_splits. `available` False until both sides clear MIN_SPLIT_SHOTS."""
    # A passed game_ids set is trusted as season-scoped (archive views); only the
    # no-args default pins to the current season.
    if game_ids is not None:
        allow = set(game_ids)
        if not allow:
            return {"available": False}
        ph = ",".join("?" * len(allow))
        rows = query(
            f"SELECT id, team1_id, home_score, away_score FROM games "
            f"WHERE id IN ({ph}) AND (team1_id=? OR team2_id=?) AND tracked=1 "
            f"AND home_score IS NOT NULL AND away_score IS NOT NULL",
            tuple(allow) + (team_id, team_id))
    else:
        rows = query(
            "SELECT id, team1_id, home_score, away_score FROM games "
            "WHERE (team1_id=? OR team2_id=?) AND tracked=1 AND season='Current' "
            "AND home_score IS NOT NULL AND away_score IS NOT NULL",
            (team_id, team_id))
    result = {}                       # game_id -> 'win' | 'loss'
    for r in rows:
        is_home = r["team1_id"] == team_id            # team1 = home in this app
        my = r["home_score"] if is_home else r["away_score"]
        opp = r["away_score"] if is_home else r["home_score"]
        if my == opp:
            continue
        result[r["id"]] = "win" if my > opp else "loss"
    if not result:
        return {"available": False}
    if events is None:
        events = S.fetch_events(list(result))
    profs = _bucket_profiles(team_id, events, lambda g: result.get(g),
                             {"win": "In wins", "loss": "In losses"})
    wins = sum(1 for v in result.values() if v == "win")
    return {
        "win": profs["win"], "loss": profs["loss"],
        "win_games": wins, "loss_games": len(result) - wins,
        "available": (profs["win"]["poss"] >= MIN_SPLIT_SHOTS
                      and profs["loss"]["poss"] >= MIN_SPLIT_SHOTS),
    }


# ── win/loss stat alignment — "what separates wins from losses" ────────────────
# Per-game team stats split by result, ranked by effect size. Founder read:
# most teams have ~4 stats that visibly track their win/loss expectancy, and
# they're different stats for every team — this finds each team's own set.
_WL_SPEC = [
    # key, label, higher-is-what-wins-look-like?, pct format?
    ("PPP",    "Points / possession",   "{:.2f}"),
    ("eFG",    "eFG%",                  "pct"),
    ("3P%",    "3P%",                   "pct"),
    ("3PAr",   "3PA rate",              "pct"),
    ("TOVr",   "Turnover rate",         "pct"),
    ("FTr",    "FT rate",               "{:.2f}"),
    ("ORBpct", "Off. rebound %",        "pct"),
    ("AST%",   "Assisted rate",         "pct"),
    ("oPPP",   "Opp points / poss",     "{:.2f}"),
    ("oeFG",   "Opp eFG%",              "pct"),
    ("forced", "Forced TO rate",        "pct"),
    ("pace",   "Possessions",           "{:.0f}"),
]


def winloss_alignment(team_id, gender=None, game_ids=None, events=None,
                      min_each=2, top=4, min_d=0.8):
    """The ~``top`` stats that most separate this team's WINS from its LOSSES.

    Splits every tracked, finished game by result, computes a per-game stat
    line (offense + defense), and ranks each stat by effect size
    d = (win mean − loss mean) / all-games SD. Returns {available, win_games,
    loss_games, rows: [{key,label,win,loss,d,fmt}]} — rows sorted by |d|,
    gated at |d| >= min_d and both sides >= min_each games. game_ids (when
    given) is trusted as season-scoped, same contract as winloss_splits."""
    import helpers.team_analytics as TA          # lazy — avoids an import cycle
    if game_ids is not None:
        allow = set(game_ids)
        if not allow:
            return {"available": False}
        ph = ",".join("?" * len(allow))
        rows = query(
            f"SELECT id, team1_id, home_score, away_score FROM games "
            f"WHERE id IN ({ph}) AND (team1_id=? OR team2_id=?) AND tracked=1 "
            f"AND home_score IS NOT NULL AND away_score IS NOT NULL",
            tuple(allow) + (team_id, team_id))
    else:
        rows = query(
            "SELECT id, team1_id, home_score, away_score FROM games "
            "WHERE (team1_id=? OR team2_id=?) AND tracked=1 AND season='Current' "
            "AND home_score IS NOT NULL AND away_score IS NOT NULL",
            (team_id, team_id))
    result = {}
    for r in rows:
        my = r["home_score"] if r["team1_id"] == team_id else r["away_score"]
        opp = r["away_score"] if r["team1_id"] == team_id else r["home_score"]
        if my != opp:
            result[r["id"]] = "win" if my > opp else "loss"
    n_w = sum(1 for v in result.values() if v == "win")
    n_l = len(result) - n_w
    if n_w < min_each or n_l < min_each:
        return {"available": False, "win_games": n_w, "loss_games": n_l}

    if events is None:
        events = S.fetch_events(list(result))
    by_game = {}
    for e in events:
        if e["game_id"] in result:
            by_game.setdefault(e["game_id"], []).append(e)

    def _line(gid):
        evg = by_game.get(gid) or []
        if not evg:
            return None
        tb, ob = TA.team_and_opp_box(team_id, [gid], events=evg)
        poss = (tb.get("FGA", 0) or 0) + (tb.get("TOV", 0) or 0)
        opos = (ob.get("FGA", 0) or 0) + (ob.get("TOV", 0) or 0)
        if not poss:
            return None
        sf = lambda a, b_: (a / b_) if b_ else None
        return {
            "PPP":  sf(tb.get("PTS", 0), poss),
            "eFG":  S.efg(tb) if tb.get("FGA") else None,
            "3P%":  sf(tb.get("3PM", 0), tb.get("3PA", 0)),
            "3PAr": sf(tb.get("3PA", 0), tb.get("FGA", 0)),
            "TOVr": sf(tb.get("TOV", 0), poss),
            "FTr":  sf(tb.get("FTA", 0), tb.get("FGA", 0)),
            "ORBpct": sf(tb.get("ORB", 0),
                         (tb.get("ORB", 0) or 0) + (ob.get("DRB", 0) or 0)),
            "AST%": sf(tb.get("AST", 0), tb.get("FGM", 0)),
            "oPPP": sf(ob.get("PTS", 0), opos) if opos else None,
            "oeFG": S.efg(ob) if ob.get("FGA") else None,
            "forced": sf(ob.get("TOV", 0), opos) if opos else None,
            "pace": float(poss),
        }

    lines = {gid: ln for gid in result if (ln := _line(gid))}
    if (sum(1 for g in lines if result[g] == "win") < min_each
            or sum(1 for g in lines if result[g] == "loss") < min_each):
        return {"available": False, "win_games": n_w, "loss_games": n_l}

    out_rows = []
    for key, label, fmt in _WL_SPEC:
        wv = [lines[g][key] for g in lines
              if result[g] == "win" and lines[g][key] is not None]
        lv = [lines[g][key] for g in lines
              if result[g] == "loss" and lines[g][key] is not None]
        if len(wv) < min_each or len(lv) < min_each:
            continue
        allv = wv + lv
        mean = sum(allv) / len(allv)
        sd = (sum((v - mean) ** 2 for v in allv) / len(allv)) ** 0.5
        if not sd:
            continue
        mw, ml = sum(wv) / len(wv), sum(lv) / len(lv)
        d = (mw - ml) / sd
        if abs(d) < min_d:
            continue
        out_rows.append({"key": key, "label": label, "win": mw, "loss": ml,
                         "d": d, "fmt": fmt})
    out_rows.sort(key=lambda r: -abs(r["d"]))
    return {"available": bool(out_rows), "win_games": n_w, "loss_games": n_l,
            "rows": out_rows[:top]}


def strength_splits(team_id, gender=None, game_ids=None, events=None, scored=None,
                    season="Current"):
    """The team's own-offense profile split by OPPONENT STRENGTH (top vs bottom
    half of the league by Power rank).

    Returns {'top': prof, 'bottom': prof, 'top_games', 'bottom_games',
    'available': bool} where each prof is a play-type-style profile (PPP/eFG/SCE/
    3PA_rate/rim_rate/ast_rate/open_rate/top_zone/poss). `available` is False until
    both sides clear MIN_SPLIT_SHOTS. Also carries the opponent list per side."""
    if scored is None:
        scored = TR.score_ratings(gender=gender, season=season)
    opps = _team_game_opponents(team_id, game_ids)
    if not opps or not scored:
        return {"available": False}

    # median rank cut over the league (stable), then classify each opponent.
    ranks = [s["Rank"] for s in scored.values() if s.get("Rank")]
    if not ranks:
        return {"available": False}
    med = sorted(ranks)[len(ranks) // 2]
    # rank 1 = best; <= median => a TOP-half (strong) opponent.
    top_games, bottom_games = set(), set()
    top_opps, bottom_opps = [], []
    for gid, opp in opps.items():
        rk = (scored.get(opp) or {}).get("Rank")
        if rk is None:
            continue
        if rk <= med:
            top_games.add(gid)
            top_opps.append(opp)
        else:
            bottom_games.add(gid)
            bottom_opps.append(opp)

    if events is None:
        gids = list(opps)
        events = S.fetch_events(gids) if gids else []

    top_p, bot_p = PT._blank_profile(), PT._blank_profile()
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] != team_id:
            continue
        gid = e["game_id"]
        if gid in top_games:
            PT._profile_add(top_p, e)
        elif gid in bottom_games:
            PT._profile_add(bot_p, e)

    top = PT._profile_fin(top_p, "top", "vs Top-half")
    bot = PT._profile_fin(bot_p, "bottom", "vs Bottom-half")
    return {
        "top": top, "bottom": bot,
        "top_games": len(top_games), "bottom_games": len(bottom_games),
        "top_opps": top_opps, "bottom_opps": bottom_opps,
        "available": (top["poss"] >= MIN_SPLIT_SHOTS
                      and bot["poss"] >= MIN_SPLIT_SHOTS),
    }
