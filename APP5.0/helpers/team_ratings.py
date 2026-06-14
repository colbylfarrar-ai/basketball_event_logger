"""
team_ratings.py — Team power-rating engine for APP5.0.

Two ratings, each collapsing several sub-ratings into ONE number:

  SCORE version  (every team, results-only)
      Built from final scores + who-beat-who in the `games` table. Needs no
      tracking, so it covers all 126 teams.
        Offense  : PPG  + xPPG  (opponent-adjusted points scored)
        Defense  : oPPG + xoPPG (opponent-adjusted points allowed)
        Schedule : SOS (strength of schedule) · SOR (strength of record) ·
                   class adjustment
      → Rating (points vs an average team, neutral floor) and Power (0-100).

  TRACKED version  (only tracked games, advanced)
      Built from the stats engine (helpers/stats.py) over `tracked=1` games:
      possessions, efficiency, shooting. Far smaller sample, so its graph of
      who-played-who is sparse — treat as directional.
        Offense  : ORtg · PPP · eFG% · FG% · 3P% (all opponent-adjusted)
        Defense  : DRtg · oPPP · opp eFG% / FG% / 3P%
        Pace, and a Vegas-style point-spread predictor between any two teams.
        Schedule : same SOS / SOR / class adjustment as the Score version.

Design notes
------------
* `games` is the source of truth for results: team1_id ↔ home_score,
  team2_id ↔ away_score (the away team is "@" the home team). Ratings are
  computed neutral-floor; home-court is applied only in `predict_spread`.
* Opponent adjustment is the standard iterative SRS idea: a team's adjusted
  offense is its scoring with each game re-credited for how good the
  opponent's defense was, and vice-versa. Net = adjusted O − adjusted D.
* HS schedules frequently DON'T connect across class clusters (a B2 school and
  a 6A school rarely share an opponent), so adjusted ratings from disconnected
  components are not directly comparable. The class adjustment is the bridge:
  a small, configurable points bump per class step. Set class_step=0 to drop it.
* Pure data layer: depends only on database.db and helpers.stats, never on
  streamlit, so any page or script can import it.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S


# ══════════════════════════════════════════════════════════════════════════════
#  CLASS LADDER  (smallest school → largest)
# ══════════════════════════════════════════════════════════════════════════════

CLASS_ORDER = ["B2", "B1", "A", "2A", "3A", "4A", "5A", "6A"]
_CLASS_RANK = {c: i for i, c in enumerate(CLASS_ORDER)}  # 'N/A' handled separately

DEFAULT_CLASS_STEP = 1.5   # rating points added per class above the field's mean
DEFAULT_ITERS      = 25    # SRS iterations (converges well before this)
DEFAULT_HCA        = 3.0   # home-court advantage, points (predict_spread only)
DEFAULT_REG        = 4.0   # phantom average-games per team (shrinkage strength)
_SOR_MARGIN_CAP    = 20    # margin credited to a result is clamped to ±this


_safe = S._safe   # shared definition lives in helpers.stats


# ══════════════════════════════════════════════════════════════════════════════
#  RESULTS FETCH
# ══════════════════════════════════════════════════════════════════════════════

def _finished_games(gender=None, tracked_only=False, game_ids=None,
                    season="Current"):
    """
    Finished games (both scores present) as neutral team-vs-team rows.
    Returns list of dicts: home_id, away_id, home_pts, away_pts, tracked.
    `gender` filters via the home team ('M'/'F'); teams only play same gender.
    `game_ids` (a set/iterable, or None) is the entitlement read-filter: when
    given, only those games are returned — League-wide tracked aggregations pass
    the pooled set so a Solo coach's games never feed another coach's pool view.
    An empty `game_ids` means "no visible games" → returns [].
    `season` is the season partition: default 'Current' (active season) so ratings
    never blend seasons; pass a label to view an archive, or None for all seasons.
    """
    if game_ids is not None:
        game_ids = list(game_ids)
        if not game_ids:
            return []
    clause = "WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL"
    params = []
    if gender:
        clause += " AND t1.gender = ?"
        params.append(gender)
    if tracked_only:
        clause += " AND g.tracked = 1"
    if season is not None:
        clause += " AND g.season = ?"
        params.append(season)
    if game_ids is not None:
        clause += " AND g.id IN (%s)" % ",".join("?" * len(game_ids))
        params.extend(game_ids)
    rows = query(
        f"""SELECT g.id, g.team1_id AS home_id, g.team2_id AS away_id,
                   g.home_score AS home_pts, g.away_score AS away_pts, g.tracked
            FROM games g
            JOIN teams t1 ON t1.id = g.team1_id
            JOIN teams t2 ON t2.id = g.team2_id
            {clause}""",
        tuple(params),
    )
    return rows


def _team_meta(gender=None):
    """{team_id: {'name','class','gender'}} for teams, optionally one gender."""
    clause = "WHERE gender = ?" if gender else ""
    params = (gender,) if gender else ()
    return {
        r["id"]: {"name": r["name"], "class": r["class"], "gender": r["gender"]}
        for r in query(f"SELECT id, name, class, gender FROM teams {clause}", params)
    }


def _per_team_games(games):
    """
    Reshape game rows into {team_id: [ {opp, pts_for, pts_against, won}, ... ]}.
    Each game contributes one entry to each side.
    """
    out = defaultdict(list)
    for g in games:
        h, a = g["home_id"], g["away_id"]
        hp, ap = g["home_pts"], g["away_pts"]
        out[h].append({"opp": a, "pts_for": hp, "pts_against": ap, "won": hp > ap})
        out[a].append({"opp": h, "pts_for": ap, "pts_against": hp, "won": ap > hp})
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  CORE: ITERATIVE OPPONENT ADJUSTMENT
# ══════════════════════════════════════════════════════════════════════════════

def _adjust(team_games, value_for, value_against, league_avg,
            iters=DEFAULT_ITERS, reg=DEFAULT_REG):
    """
    Generic SRS-style opponent adjustment with shrinkage.

    `value_for[t]`/`value_against[t]` are the team's raw per-game offense/defense
    (points-per-game, or per-100 efficiency). Returns (adjO, adjD) dicts where
        adjO[t] = what t would score vs a league-average opponent
        adjD[t] = what t would allow  vs a league-average opponent
    by repeatedly re-crediting each game for the opponent's adjusted strength.

    `reg` adds that many phantom games at the league average to every team's
    book. This is essential here: most teams appear in only a game or two on a
    barely-connected HS schedule graph, where a raw SRS diverges into nonsense
    (sub-20 adjusted points allowed, etc). Shrinkage pulls thin / weakly-linked
    records toward neutral while deep records keep their earned rating.
    """
    adjO = dict(value_for)
    adjD = dict(value_against)
    for _ in range(iters):
        newO, newD = {}, {}
        for t, gl in team_games.items():
            o_acc = d_acc = 0.0
            for g in gl:
                opp = g["opp"]
                # opponent defense relative to average (how easy/hard they are)
                opp_def_edge = adjD.get(opp, league_avg) - league_avg
                opp_off_edge = adjO.get(opp, league_avg) - league_avg
                o_acc += g["pts_for"] - opp_def_edge
                d_acc += g["pts_against"] - opp_off_edge
            # phantom average-games regress thin records toward the mean
            o_acc += reg * league_avg
            d_acc += reg * league_avg
            denom = len(gl) + reg
            newO[t] = _safe(o_acc, denom)
            newD[t] = _safe(d_acc, denom)
        adjO, adjD = newO, newD
    return adjO, adjD


def _class_adj(meta, team_ids, class_step):
    """Points bump per team from school-class, centered on the field's mean rank."""
    ranks = {t: _CLASS_RANK.get(meta.get(t, {}).get("class"), None) for t in team_ids}
    known = [r for r in ranks.values() if r is not None]
    mean_rank = _safe(sum(known), len(known)) if known else 0.0
    out = {}
    for t in team_ids:
        r = ranks[t]
        out[t] = 0.0 if r is None else (r - mean_rank) * class_step
    return out


def _power_scale(rating_by_team):
    """Map ratings to a 0-100 Power index: 50 = field average, +10 per std dev."""
    vals = list(rating_by_team.values())
    n = len(vals)
    if n == 0:
        return {}
    mean = sum(vals) / n
    var = _safe(sum((v - mean) ** 2 for v in vals), n)
    sd = var ** 0.5
    out = {}
    for t, v in rating_by_team.items():
        z = _safe(v - mean, sd) if sd else 0.0
        out[t] = S.scale100(z)
    return out


def _sos_sor(team_games, adj_net):
    """
    SOS = average opponent adjusted-net (schedule difficulty).
    SOR = résumé strength: per game credit the opponent's net plus a clamped
          margin (positive on a win, negative on a loss), then average. Beating
          strong teams convincingly raises it; losing to weak teams sinks it.
    """
    sos, sor = {}, {}
    for t, gl in team_games.items():
        if not gl:
            sos[t] = sor[t] = 0.0
            continue
        opp_net = 0.0
        resume = 0.0
        for g in gl:
            on = adj_net.get(g["opp"], 0.0)
            opp_net += on
            margin = g["pts_for"] - g["pts_against"]
            margin = max(-_SOR_MARGIN_CAP, min(_SOR_MARGIN_CAP, margin))
            resume += on + margin
        sos[t] = opp_net / len(gl)
        sor[t] = resume / len(gl)
    return sos, sor


# ══════════════════════════════════════════════════════════════════════════════
#  SCORE VERSION  (results-only, all teams)
# ══════════════════════════════════════════════════════════════════════════════

def score_ratings(gender=None, class_step=DEFAULT_CLASS_STEP, iters=DEFAULT_ITERS,
                  reg=DEFAULT_REG, season="Current"):
    """
    Results-only power ratings for every team in `gender` (None = all).
    Returns {team_id: {...}} with, per team:
        name, class, GP, W, L,
        PPG, oPPG, MOV,                     raw box-result rates
        xPPG, xoPPG,                        opponent-adjusted O / D
        AdjNet,                             xPPG - xoPPG (neutral-floor margin)
        SOS, SOR,                           schedule difficulty / résumé
        ClassAdj,                           cross-cluster bridge bump
        Rating,                             AdjNet + ClassAdj  (THE one number)
        Power,                              Rating on a 0-100 scale (50 = avg)
        Rank                                1 = best (by Rating, within gender)
    """
    games = _finished_games(gender=gender, season=season)
    meta = _team_meta(gender=gender)
    tg = _per_team_games(games)
    if not tg:
        return {}

    # raw per-game offense / defense
    ppg, oppg, gp, wins = {}, {}, {}, {}
    tot_pts = tot_games = 0
    for t, gl in tg.items():
        pf = sum(g["pts_for"] for g in gl)
        pa = sum(g["pts_against"] for g in gl)
        n = len(gl)
        ppg[t] = pf / n
        oppg[t] = pa / n
        gp[t] = n
        wins[t] = sum(1 for g in gl if g["won"])
        tot_pts += pf
        tot_games += n
    league_avg = _safe(tot_pts, tot_games)  # avg points scored per team-game

    adjO, adjD = _adjust(tg, ppg, oppg, league_avg, iters=iters, reg=reg)
    adj_net = {t: adjO[t] - adjD[t] for t in tg}
    sos, sor = _sos_sor(tg, adj_net)
    cadj = _class_adj(meta, list(tg.keys()), class_step)

    rating = {t: adj_net[t] + cadj[t] for t in tg}
    power = _power_scale(rating)

    out = {}
    for t, gl in tg.items():
        out[t] = {
            "name": meta.get(t, {}).get("name", f"#{t}"),
            "class": meta.get(t, {}).get("class", "N/A"),
            "GP": gp[t], "W": wins[t], "L": gp[t] - wins[t],
            "PPG": round(ppg[t], 1), "oPPG": round(oppg[t], 1),
            "MOV": round(ppg[t] - oppg[t], 1),
            "xPPG": round(adjO[t], 1), "xoPPG": round(adjD[t], 1),
            "AdjNet": round(adj_net[t], 2),
            "SOS": round(sos[t], 2), "SOR": round(sor[t], 2),
            "ClassAdj": round(cadj[t], 2),
            "Rating": round(rating[t], 2),
            "Power": round(power[t], 1),
        }
    _assign_ranks(out)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  TRACKED VERSION  (advanced, tracked games only)
# ══════════════════════════════════════════════════════════════════════════════

def _tracked_team_game_boxes(games):
    """
    {(game_id, team_id): finalized box} for the two teams of each tracked game,
    aggregated from game_events via the stats engine.
    """
    team_of = {r["id"]: r["team_id"] for r in query("SELECT id, team_id FROM players")}
    keys = list(S.finalize_box(S._blank_box()).keys())
    out = {}
    for g in games:
        gid = g["id"]
        sides = {g["home_id"], g["away_id"]}
        boxes = S.aggregate_player_boxes(game_ids=[gid])
        agg = {tid: {k: 0 for k in keys} for tid in sides}
        for pid, b in boxes.items():
            tid = team_of.get(pid)
            if tid in agg:
                for k in keys:
                    agg[tid][k] += b.get(k, 0)
        for tid, b in agg.items():
            out[(gid, tid)] = b
    return out


def tracked_ratings(gender=None, class_step=DEFAULT_CLASS_STEP, iters=DEFAULT_ITERS,
                    reg=DEFAULT_REG, game_ids=None, season="Current"):
    """
    Advanced, possession-based power ratings over tracked games only.
    `game_ids` is the entitlement read-filter (see _finished_games): a League-wide
    surface passes the pooled set so only pooled games feed the ratings.
    Returns {team_id: {...}} with, per team:
        name, class, GP,
        Pace,                               possessions per game
        ORtg, DRtg, NetRtg,                 opponent-adjusted, per 100 poss
        PPP, oPPP,                          adjusted points per possession
        eFG, oeFG, FGpct, oFGpct, TPpct,    shooting (own / allowed)
        SOS, SOR, ClassAdj,                 schedule (in per-100 units)
        Rating,                             NetRtg + class bump (THE one number)
        RatingPts,                          Rating expressed as pts/game (for spreads)
        Power, Rank
    Efficiency uses authoritative final scores for points and stats-engine
    possessions; shooting comes straight from the box.
    """
    games = _finished_games(gender=gender, tracked_only=True, game_ids=game_ids,
                            season=season)
    meta = _team_meta(gender=gender)
    if not games:
        return {}

    boxes = _tracked_team_game_boxes(games)
    score_of = {}
    for g in games:
        score_of[(g["id"], g["home_id"])] = (g["home_pts"], g["away_pts"], g["away_id"])
        score_of[(g["id"], g["away_id"])] = (g["away_pts"], g["home_pts"], g["home_id"])

    # per-team accumulators
    tg = defaultdict(list)          # for SRS adjustment, in per-100 efficiency
    pace_acc = defaultdict(float)
    poss_acc = defaultdict(float)
    gp = defaultdict(int)
    shoot = defaultdict(lambda: defaultdict(float))  # summed box for shooting splits
    o_shoot = defaultdict(lambda: defaultdict(float))

    tot_pts = tot_poss = 0.0
    for (gid, tid), b in boxes.items():
        if (gid, tid) not in score_of:
            continue
        pts_for, pts_against, opp = score_of[(gid, tid)]
        poss = S.estimate_possessions(b)
        if poss <= 0:
            continue
        opp_box = boxes.get((gid, opp))
        opp_poss = S.estimate_possessions(opp_box) if opp_box else poss
        ortg = 100 * pts_for / poss
        drtg = 100 * pts_against / (opp_poss if opp_poss > 0 else poss)
        tg[tid].append({"opp": opp, "pts_for": ortg, "pts_against": drtg,
                        "won": pts_for > pts_against})
        pace_acc[tid] += (poss + (opp_poss if opp_poss > 0 else poss)) / 2
        poss_acc[tid] += poss
        gp[tid] += 1
        tot_pts += pts_for
        tot_poss += poss
        for k in ("FGM", "FGA", "3PM", "3PA"):
            shoot[tid][k] += b[k]
        if opp_box is not None:
            for k in ("FGM", "FGA", "3PM", "3PA"):
                o_shoot[tid][k] += opp_box[k]

    if not tg:
        return {}

    league_rtg = 100 * _safe(tot_pts, tot_poss)
    raw_o = {t: sum(g["pts_for"] for g in gl) / len(gl) for t, gl in tg.items()}
    raw_d = {t: sum(g["pts_against"] for g in gl) / len(gl) for t, gl in tg.items()}
    adjO, adjD = _adjust(tg, raw_o, raw_d, league_rtg, iters=iters, reg=reg)
    adj_net = {t: adjO[t] - adjD[t] for t in tg}
    sos, sor = _sos_sor(tg, adj_net)
    cadj = _class_adj(meta, list(tg.keys()), class_step)

    rating = {t: adj_net[t] + cadj[t] for t in tg}
    power = _power_scale(rating)

    out = {}
    for t, gl in tg.items():
        n = gp[t]
        pace = _safe(pace_acc[t], n)
        sh, osh = shoot[t], o_shoot[t]
        # rating expressed as points/game so spreads land in real points
        rating_pts = adj_net[t] / 100 * pace + cadj[t]
        out[t] = {
            "name": meta.get(t, {}).get("name", f"#{t}"),
            "class": meta.get(t, {}).get("class", "N/A"),
            "GP": n,
            "Pace": round(pace, 1),
            "ORtg": round(adjO[t], 1), "DRtg": round(adjD[t], 1),
            "NetRtg": round(adj_net[t], 2),
            "PPP": round(adjO[t] / 100, 3), "oPPP": round(adjD[t] / 100, 3),
            "eFG": round(S.efg({"FGM": sh["FGM"], "3PM": sh["3PM"], "FGA": sh["FGA"]}), 3),
            "oeFG": round(S.efg({"FGM": osh["FGM"], "3PM": osh["3PM"], "FGA": osh["FGA"]}), 3),
            "FGpct": round(_safe(sh["FGM"], sh["FGA"]), 3),
            "oFGpct": round(_safe(osh["FGM"], osh["FGA"]), 3),
            "TPpct": round(_safe(sh["3PM"], sh["3PA"]), 3),
            "SOS": round(sos[t], 2), "SOR": round(sor[t], 2),
            "ClassAdj": round(cadj[t], 2),
            "Rating": round(rating[t], 2),
            "RatingPts": round(rating_pts, 2),
            "Power": round(power[t], 1),
        }
    _assign_ranks(out)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  RANKING + SPREAD PREDICTION
# ══════════════════════════════════════════════════════════════════════════════

def _assign_ranks(ratings):
    """Add 1-based 'Rank' to each team by descending Rating (in place)."""
    order = sorted(ratings, key=lambda t: ratings[t]["Rating"], reverse=True)
    for i, t in enumerate(order, 1):
        ratings[t]["Rank"] = i


def team_rank(team_id, scored=None, tracked=None, gender=None):
    """
    A team's standing in BOTH ranking systems, in one call:

      'overall' — the "everything" ranking from score_ratings (results-only,
                  covers every team in the league).
      'tracked' — the possession-based ranking from tracked_ratings (only teams
                  with at least one tracked game).

    Pass the already-computed `scored` / `tracked` dicts (from score_ratings /
    tracked_ratings) to reuse them — pages cache those, so this stays a couple of
    cheap dict lookups. Any dict left as None is computed here for `gender`.

    Returns:
        {
          'team_id': team_id,
          'overall': {'rank', 'of', 'power', 'rating'}  | None,
          'tracked': {'rank', 'of', 'power', 'netrtg'}  | None,
        }
    `of` is the field size (teams ranked in that system). 'overall' is None only
    when the team has no finished games; 'tracked' is None when it has no tracked
    games — so callers can show the tracked rank only "where possible".
    """
    if scored is None:
        scored = score_ratings(gender=gender)
    if tracked is None:
        tracked = tracked_ratings(gender=gender)

    def _standing(ratings, rating_key, rating_name):
        r = ratings.get(team_id)
        if not r:
            return None
        return {"rank": r["Rank"], "of": len(ratings),
                "power": r["Power"], rating_name: r[rating_key]}

    return {
        "team_id": team_id,
        "overall": _standing(scored, "Rating", "rating"),
        "tracked": _standing(tracked, "NetRtg", "netrtg"),
    }


def predict_spread(ratings, team_a, team_b, home=None, hca=DEFAULT_HCA):
    """
    Predicted margin for team_a vs team_b, from a ratings dict (score_ratings or
    tracked_ratings). Positive = team_a favored by that many points.

    `home`: pass team_a or team_b to give that side home-court (+hca); leave None
    for a neutral floor. For tracked ratings the points-scale 'RatingPts' is used
    so the spread is in real points; score ratings use 'Rating' directly.
    """
    if team_a not in ratings or team_b not in ratings:
        return None
    key = "RatingPts" if "RatingPts" in ratings[team_a] else "Rating"
    margin = ratings[team_a][key] - ratings[team_b][key]
    if home == team_a:
        margin += hca
    elif home == team_b:
        margin -= hca
    return round(margin, 1)
