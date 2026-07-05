"""
officials.py — the officiating stat engine (Streamlit-free, like stats.py).

Data model (see database/schema.sql):
  • officials                — one row per ref: id (PK), name, official_id (ext).
  • game_lineup_officials    — which refs were on the floor for a game
                               (authoritative "games worked" list; the tracker
                               writes a row for every on-court official).
  • game_events.official_id  — set ONLY on `foul` events: the ref who made the
                               call. The fouler is `secondary_player_id`, so the
                               foul is charged against THAT player's team.

So two grains of data exist per official:
  - foul-level   (who called what): exact, per-official, from foul events.
  - game-level   (pace / scoring of games worked): shared by all refs of a game,
                  from the games table + a possession estimate over its events.

Everything here is pure data — no Streamlit. `official_overview()` is the single
entry point the page reads; it returns a finished per-official table plus the
team lookup the charts need.
"""
import statistics
from collections import defaultdict

from database.db import query


# ── low-level loaders ───────────────────────────────────────────────────────

def _games(gender=None, allow=None, season="Current"):
    """Tracked games with scores, optionally limited to one gender (team1's).

    `allow` is the entitlement read-filter (a set/iterable of game ids the viewer
    may aggregate) or None = unrestricted. A solo-paid coach passes their OWN
    tracked games (refs/foul depth scoped to their own games); a league-wide coach
    passes the pooled set; admin passes None.

    `season` — 'Current' (default), an archive label, or None = ALL seasons.
    Officials are career-long (same person, same official_id, ~15-year careers,
    never archived at rollover), so the Officials page aggregates across seasons
    by default (season=None) and offers a per-season view.
    """
    clause = "AND g.season = ?" if season is not None else ""
    params = (season,) if season is not None else ()
    rows = query(
        f"""SELECT g.id, g.team1_id, g.team2_id, g.date,
                  g.home_score, g.away_score, t1.gender AS gender
           FROM games g
           JOIN teams t1 ON t1.id = g.team1_id
           WHERE g.tracked = 1 {clause}""", params
    )
    if gender:
        rows = [r for r in rows if r["gender"] == gender]
    if allow is not None:
        allow = set(allow)
        rows = [r for r in rows if r["id"] in allow]
    return {r["id"]: r for r in rows}


def _officials():
    return {r["id"]: r for r in query("SELECT id, name, official_id FROM officials")}


def _worked(game_ids):
    """{official_pk: set(game_id)} from game_lineup_officials, limited to game_ids."""
    if not game_ids:
        return {}
    rows = query("SELECT official_id AS off_pk, game_id FROM game_lineup_officials")
    out = defaultdict(set)
    gid_set = set(game_ids)
    for r in rows:
        if r["game_id"] in gid_set:
            out[r["off_pk"]].add(r["game_id"])
    return out


def _foul_events(game_ids):
    """Foul events in game_ids, with the fouler's team joined in."""
    if not game_ids:
        return []
    rows = query(
        """SELECT ge.game_id, ge.quarter, ge.official_id AS off_pk,
                  p.team_id AS fouler_team
           FROM game_events ge
           LEFT JOIN players p ON p.id = ge.secondary_player_id
           WHERE ge.event_type = 'foul'"""
    )
    gid_set = set(game_ids)
    return [r for r in rows if r["game_id"] in gid_set]


def _possessions_by_game(game_ids):
    """
    Combined (both teams) possessions per game, computed straight from raw
    events:  POSS = FGA + TOV  (FGA = #shot events, TOV = #turnover events).
    A possession is a shot or a turnover; free throws and fouls don't count.
    Returns {game_id: int}.
    """
    if not game_ids:
        return {}
    rows = query("SELECT game_id, event_type FROM game_events")
    gid_set = set(game_ids)
    acc = defaultdict(int)
    for r in rows:
        if r["game_id"] not in gid_set:
            continue
        if r["event_type"] in ("shot", "turnover"):
            acc[r["game_id"]] += 1
    return dict(acc)


from helpers.stats import _safe   # shared definition lives in helpers.stats


# ── main entry point ─────────────────────────────────────────────────────────

def official_overview(gender=None, game_ids=None, season="Current"):
    """
    Returns {"officials": [row, ...], "teams": {team_id: name}}.

    `game_ids` is the entitlement read-filter (see _games): None = unrestricted.

    Each official row:
      off_pk, name, ext_id
      games            games worked
      fouls            fouls THIS ref called (assigned foul events)
      FPG              fouls / game
      q1..q4           foul counts by quarter
      team_fouls       {team_id: fouls this ref called against that team}
      home_fouls       fouls called against the home team (team1)
      away_fouls       fouls called against the away team (team2)
      game_pts         combined points scored across games worked
      game_poss        combined possessions across games worked
      PPP              game_pts / game_poss  (scoring environment of their games)
      PTSPG            combined points per game
      POSSPG           combined possessions per game
      game_fouls       total fouls called by ANYONE in their games
      foul_share       fouls / game_fouls  (share of calls this ref made)
    """
    games = _games(gender, allow=game_ids, season=season)
    game_ids = list(games.keys())
    offs = _officials()
    worked = _worked(game_ids)
    fouls = _foul_events(game_ids)
    poss_by_game = _possessions_by_game(game_ids)

    teams = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}

    # per-official foul tallies
    f_total = defaultdict(int)
    f_qtr = defaultdict(lambda: defaultdict(int))
    f_team = defaultdict(lambda: defaultdict(int))
    f_home = defaultdict(int)
    f_away = defaultdict(int)
    # fouls this ref called per game — for FPG consistency (std)
    f_by_game = defaultdict(lambda: defaultdict(int))
    # total fouls per game (by anyone) — for foul_share
    game_total_fouls = defaultdict(int)

    for e in fouls:
        gid = e["game_id"]
        game_total_fouls[gid] += 1
        opk = e["off_pk"]
        if opk is None:
            continue
        f_total[opk] += 1
        f_by_game[opk][gid] += 1
        q = e["quarter"]
        if q in (1, 2, 3, 4):
            f_qtr[opk][q] += 1
        tid = e["fouler_team"]
        if tid is not None:
            f_team[opk][tid] += 1
            g = games.get(gid)
            if g:
                if tid == g["team1_id"]:
                    f_home[opk] += 1
                elif tid == g["team2_id"]:
                    f_away[opk] += 1

    rows = []
    for opk, gset in worked.items():
        if opk not in offs:
            continue
        o = offs[opk]
        n = len(gset)
        # game-level scoring environment over games worked
        gpts = 0
        gposs = 0.0
        gfouls = 0
        for gid in gset:
            g = games.get(gid)
            if g and g["home_score"] is not None and g["away_score"] is not None:
                gpts += g["home_score"] + g["away_score"]
            gposs += poss_by_game.get(gid, 0.0)
            gfouls += game_total_fouls.get(gid, 0)

        ftot = f_total.get(opk, 0)
        # per-game foul counts (0 for worked games where this ref called none)
        per_game = [f_by_game[opk].get(gid, 0) for gid in gset]
        fpg_std = statistics.pstdev(per_game) if len(per_game) > 1 else 0.0
        home_f = f_home.get(opk, 0)
        away_f = f_away.get(opk, 0)
        rows.append({
            "off_pk": opk,
            "name": o["name"],
            "ext_id": o["official_id"],
            "games": n,
            "fouls": ftot,
            "FPG": _safe(ftot, n),
            "FPG_std": fpg_std,
            "q1": f_qtr[opk].get(1, 0),
            "q2": f_qtr[opk].get(2, 0),
            "q3": f_qtr[opk].get(3, 0),
            "q4": f_qtr[opk].get(4, 0),
            "team_fouls": dict(f_team.get(opk, {})),
            "home_fouls": home_f,
            "away_fouls": away_f,
            "ha_diff": home_f - away_f,
            "game_pts": gpts,
            "game_poss": gposs,
            "PPP": _safe(gpts, gposs),
            "PTSPG": _safe(gpts, n),
            "POSSPG": _safe(gposs, n),
            "game_fouls": gfouls,
            "foul_share": _safe(ftot, gfouls),
        })

    rows.sort(key=lambda r: (-r["fouls"], r["name"]))
    return {"officials": rows, "teams": teams}


def official_game_log(off_pk, gender=None, game_ids=None, season="Current"):
    """
    Per-game detail for one official, newest first. Each row:
      game_id, date, matchup, home, away, home_score, away_score,
      fouls (this ref's calls), game_fouls (all calls), poss, ppp.

    `game_ids` is the entitlement read-filter (see _games): None = unrestricted.
    """
    games = _games(gender, allow=game_ids, season=season)
    game_ids = list(games.keys())
    worked = _worked(game_ids).get(off_pk, set())
    if not worked:
        return []

    fouls = _foul_events(game_ids)
    poss_by_game = _possessions_by_game(game_ids)
    teams = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}

    mine = defaultdict(int)
    allf = defaultdict(int)
    for e in fouls:
        allf[e["game_id"]] += 1
        if e["off_pk"] == off_pk:
            mine[e["game_id"]] += 1

    out = []
    for gid in worked:
        g = games.get(gid)
        if not g:
            continue
        home = teams.get(g["team1_id"], "?")
        away = teams.get(g["team2_id"], "?")
        poss = poss_by_game.get(gid, 0.0)
        pts = 0
        if g["home_score"] is not None and g["away_score"] is not None:
            pts = g["home_score"] + g["away_score"]
        out.append({
            "game_id": gid,
            "date": g["date"],
            "matchup": f"{home} vs {away}",
            "home": home,
            "away": away,
            "home_score": g["home_score"],
            "away_score": g["away_score"],
            "fouls": mine.get(gid, 0),
            "game_fouls": allf.get(gid, 0),
            "poss": poss,
            "ppp": _safe(pts, poss),
        })
    out.sort(key=lambda r: (r["date"] or ""), reverse=True)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  OFFICIALS RATING — "the ref a coach WANTS: gets big games, lets them play,
#  makes the gutsy call when it matters"  (founder spec)
# ══════════════════════════════════════════════════════════════════════════════
# Founder's importance order (1 = most important): 1 low fouls/game · 2 works
# high-leverage games · 3 high scoring (PPP) · 4 high pace · 5 clutch calls.
# Each is z-scored across the rated pool, weighted by that order, and scaled to a
# 0-100 index (50 = pool average, +10 per SD). Rewards the "let them play" ref
# who still makes the call late in a close one.
_RATING_WEIGHTS = [
    ("fpg",     -0.30),   # fewer fouls/game is better (negative weight)
    ("leverage", 0.25),   # the games' stakes (team quality + drama)
    ("ppp",      0.20),   # scoring environment
    ("pace",     0.15),   # possessions/game
    ("clutch",   0.10),   # willingness to make the late high-leverage call
]
RATING_MIN_GAMES = 3      # below this an official isn't rated (too few games)
CLUTCH_MARGIN = 6         # |margin| within this in Q4/OT = a clutch situation


def _game_leverage(games, scored):
    """{game_id: leverage in [0,1]} — how much a game is worth to work: the mean
    quality percentile of the two teams (rank-based) blended with the game's
    drama (final closeness). scored = team_ratings.score_ratings for the ranks;
    empty → leverage 0. A marquee, close game scores ~1; a low-vs-low blowout ~0."""
    n = len(scored) or 1
    out = {}
    for gid, g in games.items():
        rk1 = (scored.get(g["team1_id"]) or {}).get("Rank")
        rk2 = (scored.get(g["team2_id"]) or {}).get("Rank")
        if rk1 and rk2 and n > 1:
            q = 1.0 - ((rk1 - 1) / (n - 1) + (rk2 - 1) / (n - 1)) / 2
        else:
            q = 0.0
        # drama from the final margin (no timeline needed): a 1-possession game
        # is max drama, a 20+ blowout ~0.
        hs, as_ = g.get("home_score"), g.get("away_score")
        if hs is not None and as_ is not None:
            drama = max(0.0, 1.0 - abs(hs - as_) / 20.0)
        else:
            drama = 0.0
        out[gid] = 0.6 * q + 0.4 * drama
    return out


def _clutch_and_playtype(game_ids):
    """One events pass → (clutch_fouls, playtype_fouls, league_playtype).

    clutch_fouls  {off_pk: n} — fouls a ref called in Q4/OT while the score was
                  within CLUTCH_MARGIN (running margin reconstructed from the
                  scoring events, like situational/runs).
    playtype_fouls {off_pk: {play_type: n}}  — fouls by the set they happened in.
    league_playtype {play_type: n}           — the pooled baseline for bias."""
    import helpers.gameflow as GF
    import helpers.stats as S
    clutch = defaultdict(int)
    pt_off = defaultdict(lambda: defaultdict(int))
    pt_lg = defaultdict(int)
    if not game_ids:
        return dict(clutch), pt_off, dict(pt_lg)
    ev = S.fetch_events(list(game_ids))   # provides derived shooter_team_id
    by_game = defaultdict(list)
    for e in ev:
        by_game[e["game_id"]].append(e)
    for gid, evs in by_game.items():
        evs.sort(key=lambda e: _elapsed_safe(e, GF))
        margin = 0            # team1 - team2, BEFORE the event
        t1 = _game_team1(gid)
        for e in evs:
            et = e["event_type"]
            if et == "foul":
                q = e["quarter"] or 0
                if q >= 4 and abs(margin) <= CLUTCH_MARGIN:
                    opk = e["official_id"]
                    if opk is not None:
                        clutch[opk] += 1
                        pk = e.get("play_type")
                        if pk:
                            pt_off[opk][pk] += 1
                            pt_lg[pk] += 1
                elif e.get("play_type") and e["official_id"] is not None:
                    pt_off[e["official_id"]][e["play_type"]] += 1
                    pt_lg[e["play_type"]] += 1
            elif ((et == "shot" and e["shot_result"] == "make")
                  or (et == "free_throw" and e["shot_result"] == "make")):
                pts = (3 if e["shot_type"] == 3 else 2) if et == "shot" else 1
                if e["shooter_team_id"] == t1:
                    margin += pts
                elif e["shooter_team_id"] is not None:
                    margin -= pts
    return dict(clutch), pt_off, dict(pt_lg)


_TEAM1_CACHE = {}


def _game_team1(gid):
    if gid not in _TEAM1_CACHE:
        r = query("SELECT team1_id FROM games WHERE id=?", (gid,))
        _TEAM1_CACHE[gid] = r[0]["team1_id"] if r else None
    return _TEAM1_CACHE[gid]


def _elapsed_safe(e, GF):
    try:
        return GF.elapsed(e)
    except Exception:
        return (e.get("quarter") or 1) * 100000


def _z(values):
    """{k: v} → {k: z} over present values (0 when SD is 0 / n<2)."""
    vals = [v for v in values.values() if v is not None]
    if len(vals) < 2:
        return {k: 0.0 for k in values}
    m = sum(vals) / len(vals)
    sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5
    return {k: (0.0 if (v is None or not sd) else (v - m) / sd)
            for k, v in values.items()}


def official_ratings(gender=None, game_ids=None, season="Current", scored=None):
    """The Officials Rating table — the founder's composite. Builds on
    official_overview (FPG / PPP / POSSPG), adds the mean leverage of the games
    each ref worked, a clutch-call count, a 0-100 rating, and each ref's
    play-type foul BIAS (which sets they whistle more than the field).

    `scored` = team_ratings.score_ratings (for game leverage); without it
    leverage falls back to game closeness only. Returns
    {"officials": [row + {leverage, clutch, clutch_pg, rating, pt_bias}],
     "weights": _RATING_WEIGHTS}."""
    base = official_overview(gender=gender, game_ids=game_ids, season=season)
    rows = base["officials"]
    if not rows:
        return {"officials": [], "weights": _RATING_WEIGHTS}

    games = _games(gender, allow=game_ids, season=season)
    lev = _game_leverage(games, scored or {})
    # per-official mean leverage over the games they worked
    worked = _worked(list(games.keys()))
    clutch, pt_off, pt_lg = _clutch_and_playtype(list(games.keys()))
    lg_pt_total = sum(pt_lg.values()) or 1

    for r in rows:
        opk = r["off_pk"]
        gset = worked.get(opk, set())
        r["leverage"] = (sum(lev.get(g, 0.0) for g in gset) / len(gset)
                         if gset else 0.0)
        r["clutch"] = clutch.get(opk, 0)
        r["clutch_pg"] = _safe(r["clutch"], r["games"])
        # play-type foul bias: this ref's share of a set among their fouls vs the
        # league share — the biggest positive gap is "calls this a lot".
        mine = pt_off.get(opk, {})
        mine_total = sum(mine.values()) or 1
        bias = []
        for pk, nn in mine.items():
            if nn < 2:
                continue
            my_share = nn / mine_total
            lg_share = pt_lg.get(pk, 0) / lg_pt_total
            bias.append((pk, my_share - lg_share, nn, my_share))
        bias.sort(key=lambda t: -t[1])
        r["pt_bias"] = bias[:3]

    # rated pool = officials with enough games; z-score each component there
    rated = [r for r in rows if r["games"] >= RATING_MIN_GAMES]
    metrics = {
        "fpg":      {r["off_pk"]: r["FPG"] for r in rated},
        "leverage": {r["off_pk"]: r["leverage"] for r in rated},
        "ppp":      {r["off_pk"]: r["PPP"] for r in rated},
        "pace":     {r["off_pk"]: r["POSSPG"] for r in rated},
        "clutch":   {r["off_pk"]: r["clutch_pg"] for r in rated},
    }
    zmaps = {k: _z(v) for k, v in metrics.items()}
    for r in rows:
        if r["games"] < RATING_MIN_GAMES:
            r["rating"] = None
            continue
        wz = sum(w * zmaps[k].get(r["off_pk"], 0.0) for k, w in _RATING_WEIGHTS)
        r["rating"] = max(0.0, min(100.0, 50.0 + 10.0 * wz))

    rows.sort(key=lambda r: (r["rating"] is not None, r["rating"] or -1),
              reverse=True)
    return {"officials": rows, "weights": _RATING_WEIGHTS, "teams": base["teams"]}
