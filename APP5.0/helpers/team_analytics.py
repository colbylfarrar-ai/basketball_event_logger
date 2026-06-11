"""
team_analytics.py — Streamlit-free team-level analytics engine for APP5.0.

Everything the Team Analytics page needs, derived from the source of truth
(`game_events`) plus the existing engines:

    helpers/stats.py          box / advanced / possession math
    helpers/team_ratings.py   opponent-adjusted power ratings (Score / Tracked)
    helpers/player_ratings.py the 0-100 player ratings + flat stat table

Design follows the same "engine does the math, the page only displays" split as
helpers/player_ratings.py. Counting stats are totals; the page divides for
per-game. Rate stats come back as fractions (0-1) unless noted; the page
formats them as percents. A None means "undefined for this sample" and should
be skipped, not treated as 0.

`games` convention (see pages/1_Input_Hub.py): team1_id = home (home_score),
team2_id = away (away_score). Shot/rebound events carry shooter_team_id /
rebounder_team_id (joined in by S.fetch_events), so events can be attributed to
a team without re-joining the roster.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.team_ratings as TR
import helpers.player_ratings as PR


_safe = S._safe   # shared definition lives in helpers.stats


# ══════════════════════════════════════════════════════════════════════════════
#  TEAM ROSTER / META
# ══════════════════════════════════════════════════════════════════════════════

def list_teams(gender=None):
    """[{'id','name','class','gender'}] for the league, alphabetical."""
    clause = "WHERE gender = ?" if gender else ""
    params = (gender,) if gender else ()
    return query(
        f"SELECT id, name, class, gender FROM teams {clause} ORDER BY name",
        params,
    )


def _player_team_map():
    """{player_id: team_id} across every player."""
    return {r["id"]: r["team_id"] for r in query("SELECT id, team_id FROM players")}


# ══════════════════════════════════════════════════════════════════════════════
#  TEAM + OPPONENT BOX (summed over a set of games)
# ══════════════════════════════════════════════════════════════════════════════

def team_and_opp_box(team_id, game_ids=None, events=None):
    """
    (team_box, opp_box) summed over `game_ids`. `team_box` adds every player on
    `team_id`; `opp_box` adds everyone else appearing in those events (so when
    game_ids are the team's own games, opp_box is exactly the opponents). Both
    are finalized box dicts.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    boxes = S.aggregate_player_boxes(game_ids, events=events)
    team_of = _player_team_map()
    tb = S.finalize_box(S._blank_box())
    ob = S.finalize_box(S._blank_box())
    for pid, b in boxes.items():
        dest = tb if team_of.get(pid) == team_id else ob
        for k in dest:
            dest[k] += b.get(k, 0)
    return tb, ob


# ══════════════════════════════════════════════════════════════════════════════
#  FOUR FACTORS  (Dean Oliver — the spine of the Insights tab)
# ══════════════════════════════════════════════════════════════════════════════
#
#  eFG% : (FGM + 0.5*3PM) / FGA           shooting (≈40% of winning)
#  TOV% : TOV / (FGA + TOV)               ball security (≈25%)
#  ORB% : ORB / (ORB + opp DRB)           second chances (≈20%)
#  FTR  : FTM / FGA                        getting to the line (≈15%)
#  The "defense" factors are the opponent's offensive factors against this team:
#  their eFG% (lower better), the TOV% we force (higher better), their ORB%
#  (lower better) and their FT rate (lower better).

FOUR_FACTOR_WEIGHTS = {"eFG": 0.40, "TOV": 0.25, "ORB": 0.20, "FTR": 0.15}


def _factors(b, opp):
    return {
        "eFG": S.efg(b),
        "TOV": _safe(b["TOV"], S.estimate_possessions(b)),
        "ORB": _safe(b["ORB"], b["ORB"] + opp["DRB"]),
        "FTR": _safe(b["FTM"], b["FGA"]),
    }


def four_factors(team_box, opp_box):
    """
    {'off': {...}, 'def': {...}} where 'off' is this team's four factors and
    'def' is the opponent's four factors against them (i.e. this team's defense).
    All values are fractions (eFG/ORB/TOV) or a rate (FTR).
    """
    return {
        "off": _factors(team_box, opp_box),
        "def": _factors(opp_box, team_box),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  GAME LOG / SCHEDULE  (all completed games, not just tracked)
# ══════════════════════════════════════════════════════════════════════════════

def team_game_log(team_id):
    """
    Every completed game for the team, oldest first. Each row:
        game_id, date, location, site ('vs'/'@'), opp_id, opp, opp_class,
        pf, pa, margin, won, tracked, video_url.
    """
    rows = query(
        """SELECT g.id, g.date, g.location, g.tracked, g.video_url,
                  g.team1_id, g.team2_id, g.home_score, g.away_score
           FROM games g
           WHERE (g.team1_id = ? OR g.team2_id = ?)
             AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
           ORDER BY g.date, g.id""",
        (team_id, team_id),
    )
    meta = {t["id"]: t for t in query("SELECT id, name, class FROM teams")}
    out = []
    for g in rows:
        is_home = g["team1_id"] == team_id
        pf = g["home_score"] if is_home else g["away_score"]
        pa = g["away_score"] if is_home else g["home_score"]
        opp = g["team2_id"] if is_home else g["team1_id"]
        out.append({
            "game_id": g["id"], "date": g["date"], "location": g["location"],
            "site": "vs" if is_home else "@",
            "opp_id": opp,
            "opp": meta.get(opp, {}).get("name", "?"),
            "opp_class": meta.get(opp, {}).get("class", "N/A"),
            "pf": pf, "pa": pa, "margin": pf - pa, "won": pf > pa,
            "tracked": bool(g["tracked"]),
            "video_url": g["video_url"],
        })
    return out


def record_vs_class(game_log):
    """{class: [wins, losses]} from a team_game_log."""
    rec = defaultdict(lambda: [0, 0])
    for g in game_log:
        rec[g["opp_class"]][0 if g["won"] else 1] += 1
    return dict(rec)


def record_summary(game_log):
    """Overall {games, wins, losses, win_pct, MOV, PF_pg, PA_pg} over all completed games."""
    n = len(game_log)
    wins = sum(1 for g in game_log if g["won"])
    return {
        "games": n, "wins": wins, "losses": n - wins,
        "win_pct": _safe(wins, n),
        "MOV": _safe(sum(g["margin"] for g in game_log), n),
        "PF_pg": _safe(sum(g["pf"] for g in game_log), n),
        "PA_pg": _safe(sum(g["pa"] for g in game_log), n),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  EVENT BREAKDOWN  (one pass: shot creation, quarter splits, OREB by quarter)
# ══════════════════════════════════════════════════════════════════════════════

def team_event_breakdown(team_id, game_ids=None, events=None):
    """
    A single pass over the team's tracked events, returning:

      creation         {'self': {FGA,FGM,pct}, 'asst': {FGA,FGM,pct}}
                       self-created = the shooter took it with NO pass into the
                       shot; assisted/created = a teammate passed into it. The
                       pct is the make-rate (FG%) on each kind of shot.
      creation_by_game {game_id: {self_FGA,self_FGM,self_pct,
                                  asst_FGA,asst_FGM,asst_pct}}
      quarter          {q: {pf, pa, oreb_for, oreb_against,
                            fga_for, fgm_for, 3pa_for, 3pm_for}}
                       pf/pa are points scored / allowed in that quarter.

    Shots are attributed to a team via shooter_team_id; rebounds via
    rebounder_team_id vs shooter_team_id (offensive when they match).
    """
    if events is None:
        events = S.fetch_events(game_ids)

    creation = {"self": {"FGA": 0, "FGM": 0}, "asst": {"FGA": 0, "FGM": 0}}
    by_game = defaultdict(lambda: {"self_FGA": 0, "self_FGM": 0,
                                   "asst_FGA": 0, "asst_FGM": 0})
    quarter = defaultdict(lambda: {"pf": 0, "pa": 0,
                                   "oreb_for": 0, "oreb_against": 0,
                                   "fga_for": 0, "fgm_for": 0,
                                   "3pa_for": 0, "3pm_for": 0})

    for e in events:
        st_team = e["shooter_team_id"]
        q = e["quarter"]
        etype = e["event_type"]
        made = e["shot_result"] == "make"

        # ── points by quarter (for / against) ──────────────────────────────
        if etype == "shot" and made:
            pts = 3 if e["shot_type"] == 3 else 2
            if st_team == team_id:
                quarter[q]["pf"] += pts
            elif st_team is not None:
                quarter[q]["pa"] += pts
        elif etype == "free_throw" and made:
            if st_team == team_id:
                quarter[q]["pf"] += 1
            elif st_team is not None:
                quarter[q]["pa"] += 1

        # ── team offense: self-created vs assisted shot detail ─────────────
        if etype == "shot" and st_team == team_id:
            bucket = "asst" if e["pass_from_id"] is not None else "self"
            creation[bucket]["FGA"] += 1
            quarter[q]["fga_for"] += 1
            if e["shot_type"] == 3:
                quarter[q]["3pa_for"] += 1
            g = by_game[e["game_id"]]
            g[f"{bucket}_FGA"] += 1
            if made:
                creation[bucket]["FGM"] += 1
                quarter[q]["fgm_for"] += 1
                g[f"{bucket}_FGM"] += 1
                if e["shot_type"] == 3:
                    quarter[q]["3pm_for"] += 1

        # ── rebounds by quarter (offensive boards, both sides) ─────────────
        reb_team = e["rebounder_team_id"]
        if e["rebound_by_id"] is not None and reb_team is not None \
                and st_team is not None:
            offensive = reb_team == st_team
            if offensive:
                if reb_team == team_id:
                    quarter[q]["oreb_for"] += 1
                else:
                    quarter[q]["oreb_against"] += 1

    for d in (creation["self"], creation["asst"]):
        d["pct"] = _safe(d["FGM"], d["FGA"])
    cbg = {}
    for gid, g in by_game.items():
        cbg[gid] = {
            **g,
            "self_pct": _safe(g["self_FGM"], g["self_FGA"]),
            "asst_pct": _safe(g["asst_FGM"], g["asst_FGA"]),
        }
    return {"creation": creation, "creation_by_game": cbg,
            "quarter": dict(quarter)}


# ══════════════════════════════════════════════════════════════════════════════
#  PER-QUARTER FULL BOXES  (the spine of the Quarters tab)
# ══════════════════════════════════════════════════════════════════════════════

def quarter_boxes(team_id, game_ids=None, events=None):
    """
    A complete team + opponent box for EVERY quarter (and overtime period),
    so any stat can be split by quarter.

    Returns {q: {'team': team_box, 'opp': opp_box, 'poss', 'opp_poss',
                 'n_games', 'four_factors'}} where q is 1..4 (5+ = OT). Boxes are
    finalized box dicts (so all of helpers/stats.py's box functions apply). poss
    is the possession count (FGA + TOV) for each side; n_games is how many
    distinct games actually reached that quarter (use it to divide for per-game
    averages — every game has Q1–Q4, but only some reach OT).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    by_q = defaultdict(list)
    games_in_q = defaultdict(set)
    for e in events:
        q = e["quarter"]
        if q is None:
            continue
        by_q[q].append(e)
        games_in_q[q].add(e["game_id"])
    out = {}
    for q, evs in by_q.items():
        tb, ob = team_and_opp_box(team_id, events=evs)
        out[q] = {
            "team": tb, "opp": ob,
            "poss": S.estimate_possessions(tb),
            "opp_poss": S.estimate_possessions(ob),
            "n_games": len(games_in_q[q]),
            "four_factors": four_factors(tb, ob),
        }
    return out


def quarter_boxes_by_game(team_id, game_ids=None, events=None):
    """
    Per-game, per-quarter team + opponent boxes — the "by tracked game quarter"
    view. Returns {game_id: {q: {'team','opp','poss','opp_poss'}}}. Lets a stat be
    charted as one line per tracked game across Q1..Q4 (+OT), instead of pooled.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    by_gq = defaultdict(lambda: defaultdict(list))
    for e in events:
        q = e["quarter"]
        if q is None:
            continue
        by_gq[e["game_id"]][q].append(e)
    out = {}
    for gid, qd in by_gq.items():
        out[gid] = {}
        for q, evs in qd.items():
            tb, ob = team_and_opp_box(team_id, events=evs)
            out[gid][q] = {"team": tb, "opp": ob,
                           "poss": S.estimate_possessions(tb),
                           "opp_poss": S.estimate_possessions(ob)}
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  SCORING SOURCES  (from box totals — no events needed)
# ══════════════════════════════════════════════════════════════════════════════

def scoring_sources(box):
    """Points split by source for one box: {pts2, pts3, ptsft, paint, total, ...%}."""
    pts2 = box["2PM"] * 2
    pts3 = box["3PM"] * 3
    ptsft = box["FTM"]
    paint = box["paint_PTS"]
    total = pts2 + pts3 + ptsft
    return {
        "pts2": pts2, "pts3": pts3, "ptsft": ptsft, "paint": paint,
        "total": total,
        "pct2": _safe(pts2, total), "pct3": _safe(pts3, total),
        "pctft": _safe(ptsft, total), "pct_paint": _safe(paint, total),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  2s vs 3s BREAKEVEN  (the Insights headline question)
# ══════════════════════════════════════════════════════════════════════════════

def shooting_breakeven(box):
    """
    Expected-value comparison between this team's 2s and 3s.

      ev2 = 2 * 2P%      points per 2-pt attempt
      ev3 = 3 * 3P%      points per 3-pt attempt
      be3 = (2 * 2P%)/3  the 3P% at which a three is worth exactly as much as
                         the team's current two. Shoot above it -> threes pay;
                         below it -> twos pay.
    Returns fractions for 2P%/3P%/be3 and points for ev2/ev3.
    """
    p2 = _safe(box["2PM"], box["2PA"])
    p3 = _safe(box["3PM"], box["3PA"])
    ev2 = 2 * p2
    ev3 = 3 * p3
    be3 = ev2 / 3.0
    return {
        "2P%": p2, "3P%": p3, "be3": be3,
        "ev2": ev2, "ev3": ev3, "edge": ev3 - ev2,
        "rec": "more 3s" if ev3 > ev2 else "more 2s",
        "3PA": box["3PA"], "2PA": box["2PA"], "FGA": box["FGA"],
        "3PAr": _safe(box["3PA"], box["FGA"]),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYERS ON THE TEAM  (filtered slice of the league-wide player table)
# ══════════════════════════════════════════════════════════════════════════════

def team_player_rows(team_id, gender=None, min_games=1):
    """
    Every eligible player on `team_id`, each row the full flat stat line from
    PR.player_stat_table (ratings are still pool-relative to the whole league,
    so they're comparable to players on other teams). Sorted by OVERALL desc.
    """
    table = PR.player_stat_table(gender=gender, min_games=min_games)
    rows = []
    for pid, r in table.items():
        if r["team_id"] == team_id:
            r = dict(r, _pid=pid)   # carry the id so lineups can be projected
            rows.append(r)
    rows.sort(key=lambda r: (r["OVERALL"] if r["OVERALL"] is not None else -1),
              reverse=True)
    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  PREDICTIVE LINEUP ENGINE
#
#  Projects a five's Offensive / Defensive / Net Rating from predictive,
#  per-possession, usage-normalised metrics — NOT by averaging the 0-100 ratings
#  and summing PPG (which rewarded volume scorers on good teams). The design
#  goals, and how each fights the "favours players on good teams" bias:
#
#    • per-possession, never per-game  — PPG is never summed; scoring is points
#      per possession used (2·TS% blended with PPP).
#    • usage as a SHARE, not a total    — each player's USG% is renormalised
#      across the chosen five (sums to ~1), so stacking ball-dominant players
#      dilutes each rather than adding up.
#    • shot-creation credited           — a creation factor from SC% (shots
#      created: shot + pass + screen). Because SC double-counts and runs past
#      100%, the unit's SC-per-attempt is normalised to the TEAM-AVERAGE SC/A:
#      a five that generates more creation per shot than a typical team five is
#      lifted, one that generates less is docked. Centred on 1.0 (team average).
#    • bottom-up, then league-calibrated — raw numbers are computed purely from
#      the players, then mapped onto the league's ORtg/DRtg scale via a single
#      global affine fit (mean+SD match over every tracked team's top-5 rotation
#      vs the actual opponent-adjusted team ratings). The map is the SAME for
#      every lineup, so no five is anchored to its own team's rating — a strong
#      player on a weak team projects on merit, and the result is directly
#      comparable to the field of team Net ratings.
# ══════════════════════════════════════════════════════════════════════════════

# Tunables (commented so they can be recalibrated as more games are tracked).
LINEUP_FGA_FULL = 40      # FGA at which a player's own efficiency is fully trusted;
                          # below it, shrink toward the league mean (small-sample guard)
LINEUP_RELIABLE_FGA = 15  # below this a player's row is flagged 'directional'
# Shot-creation factor: the lineup's SC/A (shots-created per attempt) is
# normalised to the TEAM-AVERAGE SC/A and mapped to a small offensive multiplier
# centred on 1.0 (a five that creates like a typical team five is neutral).
CREATION_LOW  = 0.92      # floor of the creation multiplier (creates far below avg)
CREATION_HIGH = 1.08      # ceiling of the creation multiplier (creates far above avg)
CREATION_SENS = 0.30      # how hard a unit's SC/A vs team-average swings the factor


def _mean_present(vals):
    """Mean of the non-None values, or None if there are none (never zero-fills)."""
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def _raw_off_eff(r):
    """A player's points-per-possession-used, blending 2·TS% (FT-aware) and PPP
    (turnover-aware). Both are on a ~points-per-possession scale. None if neither
    is defined."""
    parts = []
    if r.get("TS%") is not None:
        parts.append(2 * r["TS%"] / 100.0)   # TS% comes back 0-100
    if r.get("PPP") is not None:
        parts.append(r["PPP"])               # already points / possession
    return _mean_present(parts)


def _redistribute_usage(chosen):
    """Renormalise the five players' USG% so on-court usage sums to 1.0. Falls
    back to FGA weights (then equal weights) when usage is missing/zero."""
    us = [(r.get("USG%") or 0.0) for r in chosen]
    tot = sum(us)
    if tot > 0:
        return [u / tot for u in us]
    fg = [float(r.get("FGA") or 0.0) for r in chosen]
    tot = sum(fg)
    if tot > 0:
        return [f / tot for f in fg]
    n = len(chosen) or 1
    return [1.0 / n] * n


def _team_sc_per_a(player_rows):
    """The team-average shots-created-per-attempt: sum(SC)/sum(FGA) over the whole
    roster. SC = a player's own shots + passes into shots + screens that free a
    shooter, so a single made shot is credited to several creators and the team
    SC/A runs ABOVE 1.0. This team figure is the baseline a lineup's own SC/A is
    normalised against. Returns None when the team has no attempts."""
    sc  = sum(float(r.get("SC")  or 0.0) for r in player_rows)
    fga = sum(float(r.get("FGA") or 0.0) for r in player_rows)
    return (sc / fga) if fga > 0 else None


def _raw_offense(chosen, league_eff, team_sc_per_a=None):
    """Bottom-up raw offensive number for a lineup: usage-weighted, sample-shrunk
    scoring efficiency × a shot-creation factor, ×100. The creation factor uses
    SC% (shots created: shot + pass + screen) — but because SC double-counts and
    exceeds 100%, the unit's SC/A is normalised to the TEAM-AVERAGE SC/A so the
    factor measures whether THIS five creates more or less than a typical team
    five, not the raw inflated SC. Returns
    (raw, shares, eff_per_player, creation_index, team_selfcr)."""
    shares = _redistribute_usage(chosen)
    eff_each, eff_sum, selfcr = [], 0.0, 0.0
    for r, s in zip(chosen, shares):
        e = _raw_off_eff(r)
        if e is None:
            e = league_eff
        w = min(1.0, float(r.get("FGA") or 0.0) / LINEUP_FGA_FULL)
        e = w * e + (1.0 - w) * league_eff
        eff_each.append(e)
        eff_sum += s * e
        # usage-weighted SelfCr% kept only for the "off the dribble" display line
        selfcr += s * ((r.get("SelfCr%") or 0.0) / 100.0)

    # ── shot-creation factor (SC/A normalised to the team average) ──────────
    unit_sc  = sum(float(r.get("SC")  or 0.0) for r in chosen)
    unit_fga = sum(float(r.get("FGA") or 0.0) for r in chosen)
    unit_sc_per_a = (unit_sc / unit_fga) if unit_fga > 0 else None
    if team_sc_per_a and unit_sc_per_a is not None:
        creation_index = unit_sc_per_a / team_sc_per_a   # 1.0 = team-average creator
    else:
        creation_index = 1.0
    cf = _clamp(1.0 + CREATION_SENS * (creation_index - 1.0),
                CREATION_LOW, CREATION_HIGH)
    return 100.0 * cf * eff_sum, shares, eff_each, creation_index, selfcr


def _raw_defense(chosen, dnorm):
    """Bottom-up raw defensive *goodness* (z; higher = better) for a lineup,
    averaged over the five (all five defend every possession, so no usage
    weight). Blends the league-relative DEFENSE rating with league-normalised
    DSHOT% (defended FG% allowed, lower = better)."""
    zs, each = [], []
    for r in chosen:
        parts = []
        if r.get("DEFENSE") is not None:
            parts.append((r["DEFENSE"] - 50.0) / 10.0)        # 0-100 rating → ~z
        ds = r.get("DSHOT%")
        if ds is not None and dnorm["sd"]:
            parts.append(-(ds - dnorm["mu"]) / dnorm["sd"])    # lower allowed FG% → better
        z = _mean_present(parts)
        each.append(z if z is not None else 0.0)
        if z is not None:
            zs.append(z)
    return (_mean_present(zs) or 0.0), each


def _fit_affine(xs, ys):
    """Least-information affine map a + b·x that matches mean and SD of ys, with
    the slope sign taken from the covariance (so the mapping points the right
    way). Degenerates gracefully to a constant when there's no spread."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return (statistics.mean(ys) if ys else 0.0), 0.0
    xs2, ys2 = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = statistics.mean(xs2), statistics.mean(ys2)
    sx, sy = statistics.pstdev(xs2), statistics.pstdev(ys2)
    if sx == 0:
        return my, 0.0
    b = sy / sx
    cov = sum((x - mx) * (y - my) for x, y in pairs) / len(pairs)
    if cov < 0:
        b = -b
    return my - b * mx, b


def lineup_engine_context(gender=None, tracked_ratings=None, table=None):
    """
    Build the league-wide constants the lineup predictor needs, ONCE:
      • league_eff  — mean player scoring efficiency, the shrink target for
                      low-sample players (a league figure, not a team one, so a
                      quiet player on a good team isn't lifted by team context).
      • dnorm       — league mean/SD of DSHOT% for the defensive z-score.
      • o_cal/d_cal — (a, b) affine maps from raw offense / raw-defense-z onto the
                      actual opponent-adjusted ORtg / DRtg scale, fit over every
                      tracked team's top-5-by-minutes rotation. ONE global map.
      • net_field   — every tracked team's NetRtg (the comparison field).
      • league_pace — mean tracked-team pace (fallback when a team has no row).
    `table` lets the caller pass an already-built PR.player_stat_table to avoid
    recomputing it.
    """
    if table is None:
        table = PR.player_stat_table(gender=gender)
    if tracked_ratings is None:
        tracked_ratings = TR.tracked_ratings(gender)

    rows = list(table.values())
    league_eff = _mean_present([_raw_off_eff(r) for r in rows]) or 0.9
    dsh = [r["DSHOT%"] for r in rows if r.get("DSHOT%") is not None]
    dnorm = {"mu": (statistics.mean(dsh) if dsh else 0.0),
             "sd": (statistics.pstdev(dsh) if len(dsh) > 1 else 0.0)}

    by_team = defaultdict(list)
    for pid, r in table.items():
        by_team[r["team_id"]].append(dict(r, _pid=pid))

    raw_o, raw_d, act_o, act_d = [], [], [], []
    for tid, trow in tracked_ratings.items():
        roster = by_team.get(tid, [])
        if len(roster) < 5:
            continue
        top5 = sorted(roster, key=lambda r: (r.get("MIN") or 0.0), reverse=True)[:5]
        # normalise each team's top-5 to ITS OWN average SC/A, so calibration and
        # prediction share the same creation operating point (self-consistent).
        o, *_ = _raw_offense(top5, league_eff, _team_sc_per_a(roster))
        d, _ = _raw_defense(top5, dnorm)
        raw_o.append(o); act_o.append(trow["ORtg"])
        raw_d.append(d); act_d.append(trow["DRtg"])

    return {
        "league_eff": league_eff,
        "dnorm": dnorm,
        "o_cal": _fit_affine(raw_o, act_o),
        "d_cal": _fit_affine(raw_d, act_d),
        "net_field": [t["NetRtg"] for t in tracked_ratings.values()],
        "league_pace": (statistics.mean([t["Pace"] for t in tracked_ratings.values()])
                        if tracked_ratings else 64.0),
        "tracked": tracked_ratings,
    }


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lineup_prediction(player_rows, pids, ctx, team_id, opp_id=None):
    """
    Predict a five's ORtg / DRtg / NetRtg / score line from predictive metrics,
    calibrated to the league scale, and rank it against every tracked team.

      player_rows  this team's flat PR.player_stat_table rows (each carrying '_pid')
      pids         chosen player ids (1-5)
      ctx          lineup_engine_context(...) result (calibration + league field)
      team_id      the lineup's own team (pace + own-Net context)
      opp_id       optional opponent team_id → head-to-head spread

    Returns the prediction dict documented in the engine header. Degrades
    gracefully (None fields + `flags`) on thin lineups.
    """
    chosen = [r for r in player_rows if r.get("_pid") in pids]
    flags = []
    if not chosen:
        return {"n": 0, "ORtg": None, "DRtg": None, "NetRtg": None,
                "flags": ["No players selected."]}
    if len(chosen) < 5:
        flags.append(f"Partial lineup ({len(chosen)}/5) — projection is directional.")

    league_eff = ctx["league_eff"]
    team_sc_pa = _team_sc_per_a(player_rows)
    raw_o, shares, eff_each, creation_index, team_selfcr = _raw_offense(
        chosen, league_eff, team_sc_pa)
    raw_d, def_each = _raw_defense(chosen, ctx["dnorm"])

    a_o, b_o = ctx["o_cal"]
    a_d, b_d = ctx["d_cal"]
    ortg = _clamp(a_o + b_o * raw_o, 40.0, 140.0)
    drtg = _clamp(a_d + b_d * raw_d, 40.0, 140.0)
    net  = ortg - drtg

    tracked = ctx["tracked"]
    trow = tracked.get(team_id, {})
    pace = trow.get("Pace") or ctx["league_pace"]
    exp_pf = ortg / 100.0 * pace
    exp_pa = drtg / 100.0 * pace

    # low-sample flag
    thin = [r for r in chosen if (r.get("FGA") or 0) < LINEUP_RELIABLE_FGA]
    if thin:
        thin_nums = ", ".join(f"#{r['number']}" for r in thin)
        flags.append(f"{thin_nums}: <{LINEUP_RELIABLE_FGA} FGA — efficiency shrunk toward league mean.")
    if team_id not in tracked:
        flags.append("Team has no tracked rating — using league-average pace/Net for context.")

    net_field = ctx["net_field"]
    rank = 1 + sum(1 for v in net_field if v is not None and v > net)
    league = {
        "rank": rank, "of": len(net_field),
        "percentile": percentile(net, net_field, higher_better=True),
        "net_field_min": min(net_field) if net_field else None,
        "net_field_max": max(net_field) if net_field else None,
        "team_net": trow.get("NetRtg"),
    }

    matchup = None
    if opp_id is not None and opp_id in tracked:
        orow = tracked[opp_id]
        spread = (exp_pf - exp_pa) - (orow["NetRtg"] / 100.0 * pace)
        matchup = {"opp_id": opp_id, "opp": orow.get("name", f"#{opp_id}"),
                   "spread": round(spread, 1), "favored": spread > 0}

    contrib = []
    for r, s, e, dz in zip(chosen, shares, eff_each, def_each):
        contrib.append({
            "pid": r["_pid"], "name": r["name"], "number": r["number"],
            "usg_share": round(s, 3),
            "off_pts100": round(100.0 * s * e, 1),   # this player's slice of ORtg
            "scoring_eff": round(e, 3),              # points / possession used
            "def_z": round(dz, 2),                   # defensive goodness (z)
            "self_cr": r.get("SelfCr%"),
            "reliable": (r.get("FGA") or 0) >= LINEUP_RELIABLE_FGA,
        })
    contrib.sort(key=lambda c: c["off_pts100"], reverse=True)

    return {
        "n": len(chosen),
        "ORtg": round(ortg, 1), "DRtg": round(drtg, 1), "NetRtg": round(net, 1),
        "ORtg_raw": round(raw_o, 1), "DRtg_rawz": round(raw_d, 2),
        "pace": round(pace, 1),
        "exp_pf": round(exp_pf, 1), "exp_pa": round(exp_pa, 1),
        "exp_margin": round(exp_pf - exp_pa, 1),
        "score_line": f"{round(exp_pf)} – {round(exp_pa)}",
        "team_selfcr": round(100.0 * team_selfcr, 1),
        "creation_index": round(creation_index, 2),
        "league": league, "matchup": matchup, "contrib": contrib, "flags": flags,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  LEAGUE CONTEXT  (four factors for every tracked team — for percentile ranking)
# ══════════════════════════════════════════════════════════════════════════════

def league_four_factors(gender=None):
    """
    {team_id: {'off': {...}, 'def': {...}, 'GP': n}} for every team in the
    league with at least one tracked game. Used by the Insights tab to say
    whether a team's factor is a strength or a weakness *relative to the field*.
    Built from one box pass per tracked game (TR._tracked_team_game_boxes).
    """
    games = TR._finished_games(gender=gender, tracked_only=True)
    if not games:
        return {}
    boxes = TR._tracked_team_game_boxes(games)   # {(gid, tid): box}
    # which teams played in each game, to find the opponent box
    sides = defaultdict(list)
    for (gid, tid) in boxes:
        sides[gid].append(tid)

    team_box = defaultdict(lambda: S.finalize_box(S._blank_box()))
    opp_box = defaultdict(lambda: S.finalize_box(S._blank_box()))
    gp = defaultdict(int)
    for (gid, tid), b in boxes.items():
        for k in team_box[tid]:
            team_box[tid][k] += b.get(k, 0)
        gp[tid] += 1
        for other in sides[gid]:
            if other != tid:
                ob = boxes.get((gid, other))
                if ob:
                    for k in opp_box[tid]:
                        opp_box[tid][k] += ob.get(k, 0)

    out = {}
    for tid in team_box:
        ff = four_factors(team_box[tid], opp_box[tid])
        out[tid] = {**ff, "GP": gp[tid]}
    return out


percentile = S.percentile   # shared definition lives in helpers.stats


# ══════════════════════════════════════════════════════════════════════════════
#  SHOT-LEVEL ANALYTICS  (zones, contest, creation, possession length)
# ══════════════════════════════════════════════════════════════════════════════

ZONES = ["LC", "LW", "C", "RW", "RC"]
ZONE_LABELS = {"LC": "Left Corner", "LW": "Left Wing", "C": "Paint / Center",
               "RW": "Right Wing", "RC": "Right Corner"}


def _team_shots(team_id, events, offense=True):
    """Shot events taken by this team (offense=True) or by its opponents (False)."""
    out = []
    for e in events:
        if e["event_type"] != "shot":
            continue
        st_team = e["shooter_team_id"]
        if st_team is None:
            continue
        if (st_team == team_id) == offense:
            out.append(e)
    return out


def agg_shots(shots):
    """
    Aggregate a list of shot events into a standard line:
      FGA/FGM/FG%, 2PA/2PM/2P%, 3PA/3PM/3P%, PTS, eFG, PPS (pts per FGA).
    """
    fga = len(shots)
    fgm = sum(1 for s in shots if s["shot_result"] == "make")
    tpa = sum(1 for s in shots if s["shot_type"] == 3)
    tpm = sum(1 for s in shots if s["shot_type"] == 3 and s["shot_result"] == "make")
    twa, twm = fga - tpa, fgm - tpm
    pts = twm * 2 + tpm * 3
    # SCE = (FG points) / max FG points possible = PTS / (2PA*2 + 3PA*3). For a
    # shot list there are no free throws, so the "- FT" term is 0.
    sce_denom = twa * 2 + tpa * 3
    return {
        "FGA": fga, "FGM": fgm, "FG%": _safe(fgm, fga),
        "2PA": twa, "2PM": twm, "2P%": _safe(twm, twa),
        "3PA": tpa, "3PM": tpm, "3P%": _safe(tpm, tpa),
        "PTS": pts, "eFG": _safe(fgm + 0.5 * tpm, fga), "PPS": _safe(pts, fga),
        "SCE": _safe(pts, sce_denom),
    }


def zone_splits(team_id, game_ids=None, events=None):
    """
    {'off': {zone: agg}, 'def': {zone: agg}} — shooting by floor zone for the
    team's own shots and for the shots opponents take against them.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    out = {}
    for side, off in (("off", True), ("def", False)):
        shots = _team_shots(team_id, events, offense=off)
        by_zone = defaultdict(list)
        for s in shots:
            if s["zone"]:
                by_zone[s["zone"]].append(s)
        out[side] = {z: agg_shots(by_zone.get(z, [])) for z in ZONES}
    return out


def zone_xfg(team_id, game_ids=None, events=None, rates=None):
    """
    Per-zone actual FG% and expected FG% (xFG%) for the team's own shots.
    xFG% = the sample make-rate for each shot's (zone, creation, guarded) bucket
    (S.shot_quality_rates), averaged over the shots in that zone — i.e. how often
    that *kind* of shot goes in league-wide. Compare to actual to see which zones
    the team over/under-shoots relative to the difficulty of looks they get there.
    Returns {zone: {FGA, 'FG%', 'xFG%'}}.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if rates is None:
        rates = S.shot_quality_rates(events=events)
    shots = _team_shots(team_id, events, offense=True)
    agg = defaultdict(lambda: {"FGA": 0, "FGM": 0, "xsum": 0.0})
    for s in shots:
        z = s["zone"]
        if not z:
            continue
        bucket = S._creation_bucket(s["pass_from_id"] is not None,
                                    s["shot_created_by_id"] is not None)
        key = (z, bucket, s["guarded_by_id"] is not None)
        a = agg[z]
        a["FGA"] += 1
        if s["shot_result"] == "make":
            a["FGM"] += 1
        a["xsum"] += rates.get(key, {}).get("pct", 0.0)
    out = {}
    for z in ZONES:
        a = agg.get(z, {"FGA": 0, "FGM": 0, "xsum": 0.0})
        out[z] = {"FGA": a["FGA"], "FG%": _safe(a["FGM"], a["FGA"]),
                  "xFG%": _safe(a["xsum"], a["FGA"])}
    return out


def guarded_splits(team_id, game_ids=None, events=None, offense=True):
    """{'guarded': agg, 'unguarded': agg, 'all': agg, 'guard_share': frac} for the
    team's own shots (offense) — guarded = a defender tagged the contest."""
    if events is None:
        events = S.fetch_events(game_ids)
    shots = _team_shots(team_id, events, offense=offense)
    g = [s for s in shots if s["guarded_by_id"] is not None]
    u = [s for s in shots if s["guarded_by_id"] is None]
    return {"guarded": agg_shots(g), "unguarded": agg_shots(u),
            "all": agg_shots(shots), "guard_share": _safe(len(g), len(shots))}


def creation_breakdown(team_id, game_ids=None, events=None):
    """
    Four creation buckets for the team's own shots:
      both    (pass + screen)   pass_from_id AND shot_created_by_id
      pass    (off a pass)      pass_from_id only
      created (off a screen)    shot_created_by_id only
      self    (pure self-made)  neither
    Each -> agg_shots line. Returns {bucket: agg} in that order + 'total'.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    shots = _team_shots(team_id, events, offense=True)
    buckets = {"both": [], "pass": [], "created": [], "self": []}
    for s in shots:
        hp = s["pass_from_id"] is not None
        hc = s["shot_created_by_id"] is not None
        key = "both" if hp and hc else "pass" if hp else "created" if hc else "self"
        buckets[key].append(s)
    out = {k: agg_shots(v) for k, v in buckets.items()}
    out["total"] = agg_shots(shots)
    return out


# possession-length buckets, in seconds of possession_secs on the shot event
POSS_BUCKETS = [("Transition (≤6s)", 0.01, 6), ("Early (7–14s)", 6, 14),
                ("Half-court (15s+)", 14, 1e9)]


def _creation_counts(shots):
    """Count a shot list by how each shot was created: self/pass/screen/both.
    'screen' = shot_created_by_id only (a screen freed the shooter, no pass)."""
    cc = {"self": 0, "pass": 0, "screen": 0, "both": 0}
    for s in shots:
        hp = s["pass_from_id"] is not None
        hc = s["shot_created_by_id"] is not None
        k = "both" if hp and hc else "pass" if hp else "screen" if hc else "self"
        cc[k] += 1
    return cc


def possession_length_splits(team_id, game_ids=None, events=None):
    """
    The team's own shots bucketed by the possession length (possession_secs) of
    the shot event. Returns
      [{label, FGA, FGM, FG%, 3P%, 2P%, PTS, PPS, PPP, SCE, AST%,
        self, pass, screen, both}, …]
    plus an 'Untimed' bucket for the ~16% of events with possession_secs = 0.
    PPP here == PPS (a shot ends the possession, so possessions == FGA).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    shots = _team_shots(team_id, events, offense=True)

    def _row(label, bucket):
        a = agg_shots(bucket)
        ast = sum(1 for s in bucket if s["shot_result"] == "make"
                  and s["pass_from_id"] is not None)
        a.update(label=label, PPP=a["PPS"], **{"AST%": _safe(ast, a["FGM"])},
                 **_creation_counts(bucket))
        return a

    rows = [_row(label, [s for s in shots
                         if lo < (s["possession_secs"] or 0) <= hi])
            for label, lo, hi in POSS_BUCKETS]
    untimed = [s for s in shots if (s["possession_secs"] or 0) <= 0]
    if untimed:
        rows.append(_row("Untimed", untimed))
    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  SHOT-CREATION × COURT REGION  (for the stacked creation bar)
# ══════════════════════════════════════════════════════════════════════════════

# x-axis buckets for the stacked Shooting bar (creation context) and their labels.
CREATION_BUCKETS = [("self", "Self"), ("pass", "Off Pass"),
                    ("created", "Off Screen"), ("both", "Both")]


def _shot_region(s):
    """paint2 = a 2 from the Center zone · mid2 = any other 2 · three = a 3."""
    if s["shot_type"] == 3:
        return "three"
    return "paint2" if s["zone"] == "C" else "mid2"


def creation_region_crosstab(team_id, game_ids=None, events=None):
    """
    The team's own shots cross-tabbed by creation bucket × court region. Returns
        {bucket: {'paint2': agg, 'mid2': agg, 'three': agg, 'total': agg}}
    for bucket in self / pass / created / both (agg = agg_shots line). Feeds the
    stacked double-layer Shooting bar (paint-2 / mid-2 / 3 stacked, one bar per
    creation context).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    shots = _team_shots(team_id, events, offense=True)
    buckets = {k: {"paint2": [], "mid2": [], "three": [], "total": []}
               for k, _ in CREATION_BUCKETS}
    for s in shots:
        hp = s["pass_from_id"] is not None
        hc = s["shot_created_by_id"] is not None
        bk = "both" if hp and hc else "pass" if hp else "created" if hc else "self"
        buckets[bk][_shot_region(s)].append(s)
        buckets[bk]["total"].append(s)
    return {bk: {reg: agg_shots(v) for reg, v in regions.items()}
            for bk, regions in buckets.items()}


# ══════════════════════════════════════════════════════════════════════════════
#  ZONE / CREATION / GUARDED — split by 2s vs 3s (the "2/3 separation" views)
# ══════════════════════════════════════════════════════════════════════════════

def zone_splits_by_type(team_id, game_ids=None, events=None):
    """
    Shooting by zone, split into all shots / 2-pointers / 3-pointers, for the
    team's own shots ('off') and the shots opponents take against them ('def').
    Returns {'off': {'all': {zone: agg}, '2': {zone: agg}, '3': {zone: agg}},
             'def': {...}} (agg = agg_shots line).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    out = {}
    for side, off in (("off", True), ("def", False)):
        shots = _team_shots(team_id, events, offense=off)
        buckets = {"all": defaultdict(list), "2": defaultdict(list),
                   "3": defaultdict(list)}
        for s in shots:
            z = s["zone"]
            if not z:
                continue
            buckets["all"][z].append(s)
            buckets["3" if s["shot_type"] == 3 else "2"][z].append(s)
        out[side] = {b: {z: agg_shots(buckets[b].get(z, [])) for z in ZONES}
                     for b in ("all", "2", "3")}
    return out


def zone_xfg_by_type(team_id, game_ids=None, events=None, rates=None, offense=True):
    """
    Per-zone actual vs expected FG% split by 2s and 3s for the team's own shots.
    Mirrors zone_xfg but keyed by shot value. Returns
        {'all': {zone: {FGA, 'FG%', 'xFG%'}}, '2': {...}, '3': {...}}.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if rates is None:
        rates = S.shot_quality_rates(events=events)
    shots = _team_shots(team_id, events, offense=offense)
    agg = {b: defaultdict(lambda: {"FGA": 0, "FGM": 0, "xsum": 0.0})
           for b in ("all", "2", "3")}
    for s in shots:
        z = s["zone"]
        if not z:
            continue
        bucket = S._creation_bucket(s["pass_from_id"] is not None,
                                    s["shot_created_by_id"] is not None)
        p = rates.get((z, bucket, s["guarded_by_id"] is not None), {}).get("pct", 0.0)
        made = s["shot_result"] == "make"
        for bk in ("all", "3" if s["shot_type"] == 3 else "2"):
            a = agg[bk][z]
            a["FGA"] += 1
            a["FGM"] += 1 if made else 0
            a["xsum"] += p
    out = {}
    for bk in ("all", "2", "3"):
        out[bk] = {z: {"FGA": agg[bk][z]["FGA"],
                       "FG%": _safe(agg[bk][z]["FGM"], agg[bk][z]["FGA"]),
                       "xFG%": _safe(agg[bk][z]["xsum"], agg[bk][z]["FGA"])}
                   for z in ZONES}
    return out


def creation_by_type(team_id, game_ids=None, events=None):
    """
    Each shot-creation bucket (self / pass / created / both) split into 2s and 3s.
    Returns {bucket: {'2': agg, '3': agg, 'total': agg}} (agg = agg_shots line).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    shots = _team_shots(team_id, events, offense=True)
    buckets = {k: {"2": [], "3": [], "total": []}
               for k in ("both", "pass", "created", "self")}
    for s in shots:
        hp = s["pass_from_id"] is not None
        hc = s["shot_created_by_id"] is not None
        bk = "both" if hp and hc else "pass" if hp else "created" if hc else "self"
        buckets[bk]["3" if s["shot_type"] == 3 else "2"].append(s)
        buckets[bk]["total"].append(s)
    return {bk: {t: agg_shots(v) for t, v in d.items()}
            for bk, d in buckets.items()}


def creation_quarter_splits(team_id, game_ids=None, events=None):
    """
    The team's own shots split by quarter × creation: assisted (off a pass) vs
    self-created (no pass into the shot). Returns
        {q: {'ast': agg, 'sc': agg}}   (agg = an agg_shots line)
    for every quarter present (1..4, 5+ = OT). Mirrors APP3.0's "Off-Pass vs
    Self-Created by Quarter" view using this app's pass_from_id flag (assisted =
    a teammate passed into the shot).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    shots = _team_shots(team_id, events, offense=True)
    by_q = defaultdict(lambda: {"ast": [], "sc": []})
    for s in shots:
        q = s["quarter"]
        if q is None:
            continue
        bk = "ast" if s["pass_from_id"] is not None else "sc"
        by_q[q][bk].append(s)
    return {q: {"ast": agg_shots(d["ast"]), "sc": agg_shots(d["sc"])}
            for q, d in by_q.items()}


def guarded_detail(team_id, game_ids=None, events=None, offense=True):
    """
    Guarded vs unguarded shooting broken out four ways, all in one structure:
      overall      {'guarded','unguarded','all','guard_share'}
      by_type      {'2': {...}, '3': {...}}
      by_zone      {zone: {...}} for each of the 5 zones
      by_creation  {bucket: {...}} for self / pass / created / both
    Each {...} is {'guarded': agg, 'unguarded': agg, 'all': agg, 'guard_share'}.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    shots = _team_shots(team_id, events, offense=offense)

    def split(lst):
        g = [s for s in lst if s["guarded_by_id"] is not None]
        u = [s for s in lst if s["guarded_by_id"] is None]
        return {"guarded": agg_shots(g), "unguarded": agg_shots(u),
                "all": agg_shots(lst), "guard_share": _safe(len(g), len(lst))}

    def _cbucket(s):
        hp = s["pass_from_id"] is not None
        hc = s["shot_created_by_id"] is not None
        return "both" if hp and hc else "pass" if hp else "created" if hc else "self"

    return {
        "overall": split(shots),
        "by_type": {"2": split([s for s in shots if s["shot_type"] != 3]),
                    "3": split([s for s in shots if s["shot_type"] == 3])},
        "by_zone": {z: split([s for s in shots if s["zone"] == z]) for z in ZONES},
        "by_creation": {bk: split([s for s in shots if _cbucket(s) == bk])
                        for bk in ("self", "pass", "created", "both")},
    }


def player_zone_leaders(team_id, game_ids=None, min_fga=3):
    """
    For each floor zone, the team player with the best FG% on >= `min_fga` located
    attempts in that zone (2s and 3s combined). Returns
        {zone: {'pid','name','number','FGA','FGM','pct'} | None}.
    Ties broken by volume. Feeds the roster "best shooter per zone" court heatmap.
    """
    if not game_ids:
        return {z: None for z in ZONES}
    zs = S.player_zone_splits(game_ids=list(game_ids))
    meta = {r["id"]: r for r in query(
        "SELECT id, name, number FROM players WHERE team_id=?", (team_id,))}
    out = {}
    for z in ZONES:
        best = None
        for pid, m in meta.items():
            fga = fgm = 0
            for (zz, _st), c in zs.get(pid, {}).items():
                if zz == z:
                    fga += c["FGA"]
                    fgm += c["FGM"]
            if fga >= min_fga:
                pct = _safe(fgm, fga)
                if (best is None or pct > best["pct"]
                        or (pct == best["pct"] and fga > best["FGA"])):
                    best = {"pid": pid, "name": m["name"], "number": m["number"],
                            "FGA": fga, "FGM": fgm, "pct": pct}
        out[z] = best
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  SHOT QUALITY  (xFG% / xPPS / SMOE — league-baseline, applied to this team)
# ══════════════════════════════════════════════════════════════════════════════

def _agg_with_x(shots, rates):
    """agg_shots(shots) decorated with xFG%, xPPS and SMOE (=FG%−xFG%), using a
    league-wide (zone, creation, guarded) make-rate table `rates`."""
    a = agg_shots(shots)
    xsum = xpts = 0.0
    for s in shots:
        bucket = S._creation_bucket(s["pass_from_id"] is not None,
                                    s["shot_created_by_id"] is not None)
        key = (s["zone"], bucket, s["guarded_by_id"] is not None)
        p = rates.get(key, {}).get("pct", 0.0)
        xsum += p
        xpts += p * (3 if s["shot_type"] == 3 else 2)
    n = a["FGA"]
    a["xFG%"] = _safe(xsum, n)
    a["xPPS"] = _safe(xpts, n)
    a["SMOE"] = a["FG%"] - a["xFG%"]
    return a


def team_shot_quality(team_id, game_ids=None, events=None, rates=None,
                      offense=True):
    """
    One shot-quality line for the team's own shots: FGA/FGM/FG%, PPS, plus
    xFG%, xPPS and SMOE (FG%−xFG%). `rates` defaults to the LEAGUE-WIDE
    S.shot_quality_rates() so 'expected' is a real baseline, not self-referential
    on a single game — pass it in to reuse one computation across teams.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if rates is None:
        rates = S.shot_quality_rates()
    return _agg_with_x(_team_shots(team_id, events, offense=offense), rates)


def guarded_splits_by_type(team_id, game_ids=None, events=None, rates=None,
                           offense=True):
    """
    Contested vs open shooting split out BY 2s and 3s separately. Returns
        {'twos': {'guarded': agg+x, 'open': agg+x, 'all': agg+x},
         'threes': {...}}
    where each agg carries FG%/PPS plus xFG%/xPPS/SMOE. 'guarded' = a defender
    was tagged (guarded_by_id set). `rates` defaults to the league-wide table.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if rates is None:
        rates = S.shot_quality_rates()
    shots = _team_shots(team_id, events, offense=offense)
    out = {}
    for stype, skey in ((2, "twos"), (3, "threes")):
        sub = [s for s in shots if (3 if s["shot_type"] == 3 else 2) == stype]
        out[skey] = {
            "guarded": _agg_with_x([s for s in sub
                                    if s["guarded_by_id"] is not None], rates),
            "open": _agg_with_x([s for s in sub
                                 if s["guarded_by_id"] is None], rates),
            "all": _agg_with_x(sub, rates),
        }
    return out


def quarter_possession_secs(team_id, game_ids=None, events=None):
    """
    Mean possession length (seconds) per quarter for the team and its opponents.
    A possession ends on a shot or a turnover; possession_secs on that event is
    its length. Returns {q: {team_avg, opp_avg, team_poss, opp_poss}} (q 1..4,
    5+ = OT). Events with possession_secs ≤ 0 (untimed) are skipped.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    agg = defaultdict(lambda: {"ts": 0.0, "tn": 0, "os": 0.0, "on": 0})
    for e in events:
        if e["event_type"] not in ("shot", "turnover"):
            continue
        q = e["quarter"]
        st_team = e["shooter_team_id"]
        secs = e["possession_secs"] or 0
        if q is None or st_team is None or secs <= 0:
            continue
        a = agg[q]
        if st_team == team_id:
            a["ts"] += secs
            a["tn"] += 1
        else:
            a["os"] += secs
            a["on"] += 1
    return {q: {"team_avg": _safe(a["ts"], a["tn"]),
                "opp_avg": _safe(a["os"], a["on"]),
                "team_poss": a["tn"], "opp_poss": a["on"]}
            for q, a in agg.items()}


# ══════════════════════════════════════════════════════════════════════════════
#  PER-GAME TRENDS & SITUATIONAL SPLITS
# ══════════════════════════════════════════════════════════════════════════════

def per_game_metrics(team_id, game_log, events=None):
    """
    One efficiency row per tracked game, oldest first, for the trend charts:
      game_id, date, opp, margin, won, PF, PA,
      ORtg, DRtg, NetRtg, PPP, oPPP, Pace, eFG, oeFG, TOV, STL, AST, FGA.
    Possessions via S.estimate_possessions on each side's box.
    """
    tracked = [g for g in game_log if g["tracked"]]
    out = []
    for g in tracked:
        gid = g["game_id"]
        evs = [e for e in events if e["game_id"] == gid] if events is not None \
            else None
        tb, ob = team_and_opp_box(team_id, [gid], events=evs)
        poss = S.estimate_possessions(tb)
        opp_poss = S.estimate_possessions(ob)
        ortg = 100 * _safe(g["pf"], poss)
        drtg = 100 * _safe(g["pa"], opp_poss)
        out.append({
            "game_id": gid, "date": g["date"], "opp": g["opp"],
            "margin": g["margin"], "won": g["won"], "PF": g["pf"], "PA": g["pa"],
            "ORtg": ortg, "DRtg": drtg, "NetRtg": ortg - drtg,
            "PPP": _safe(g["pf"], poss), "oPPP": _safe(g["pa"], opp_poss),
            "Pace": (poss + opp_poss) / 2,
            "eFG": S.efg(tb), "oeFG": S.efg(ob),
            "TOV": tb["TOV"], "STL": tb["STL"], "AST": tb["AST"], "FGA": tb["FGA"],
        })
    return out


# stat spec for the "every team stat over tracked games" grids — (label, key,
# higher_is_better). Keys index the 'stats' dict per_game_team_stats returns.
PER_GAME_STAT_SPEC = [
    ("Points for", "PF", True), ("Points against", "PA", False),
    ("Margin", "Margin", True), ("Off Rating", "ORtg", True),
    ("Def Rating", "DRtg", False), ("Net Rating", "NetRtg", True),
    ("Pace", "Pace", True), ("Points / poss", "PPP", True),
    ("FG%", "FG%", True), ("2P%", "2P%", True), ("3P%", "3P%", True),
    ("FT%", "FT%", True), ("eFG%", "eFG%", True), ("TS%", "TS%", True),
    ("Paint FG%", "Paint FG%", True), ("FGA", "FGA", True), ("3PA", "3PA", True),
    ("FTA", "FTA", True), ("OREB", "OREB", True), ("DREB", "DREB", True),
    ("Rebounds", "REB", True), ("Assists", "AST", True),
    ("Turnovers", "TOV", False), ("Steals", "STL", True), ("Blocks", "BLK", True),
    ("Stocks", "Stocks", True), ("Fouls", "Fouls", False),
    ("AST/TO", "AST/TO", True), ("Opp eFG%", "oeFG%", False),
    ("Opp FG%", "oFG%", False), ("TOV%", "TOV%", False), ("OREB%", "OREB%", True),
    ("FT rate", "FTr", True), ("Forced TOV%", "fTOV%", True),
]


def per_game_team_stats(team_id, game_log, events=None):
    """
    One row per tracked game (oldest first) holding every team stat the trend
    grids chart. Each row: game_id, date, opp, site, won, margin, label, and a
    `stats` dict keyed by the PER_GAME_STAT_SPEC keys (percentages as 0-100).
    """
    tracked = [g for g in game_log if g["tracked"]]
    out = []
    for g in tracked:
        gid = g["game_id"]
        evs = [e for e in events if e["game_id"] == gid] if events is not None \
            else None
        tb, ob = team_and_opp_box(team_id, [gid], events=evs)
        poss = S.estimate_possessions(tb)
        opp_poss = S.estimate_possessions(ob)
        ff = four_factors(tb, ob)
        ortg = 100 * _safe(g["pf"], poss)
        drtg = 100 * _safe(g["pa"], opp_poss)
        out.append({
            "game_id": gid, "date": g["date"], "opp": g["opp"], "site": g["site"],
            "won": g["won"], "margin": g["margin"],
            "label": f"{g['date'][5:]} {g['site']} {g['opp'][:8]}",
            "stats": {
                "PF": g["pf"], "PA": g["pa"], "Margin": g["margin"],
                "ORtg": ortg, "DRtg": drtg, "NetRtg": ortg - drtg,
                "Pace": (poss + opp_poss) / 2, "PPP": _safe(g["pf"], poss),
                "FG%": S.fg_pct(tb) * 100, "2P%": S.fg2_pct(tb) * 100,
                "3P%": S.fg3_pct(tb) * 100, "FT%": S.ft_pct(tb) * 100,
                "eFG%": S.efg(tb) * 100, "TS%": S.ts(tb) * 100,
                "Paint FG%": S.paint_fg_pct(tb) * 100,
                "FGA": tb["FGA"], "3PA": tb["3PA"], "FTA": tb["FTA"],
                "OREB": tb["ORB"], "DREB": tb["DRB"], "REB": tb["TRB"],
                "AST": tb["AST"], "TOV": tb["TOV"], "STL": tb["STL"],
                "BLK": tb["BLK"], "Stocks": tb["stocks"], "Fouls": tb["PF"],
                "AST/TO": _safe(tb["AST"], tb["TOV"]),
                "oeFG%": S.efg(ob) * 100, "oFG%": S.fg_pct(ob) * 100,
                "TOV%": ff["off"]["TOV"] * 100, "OREB%": ff["off"]["ORB"] * 100,
                "FTr": ff["off"]["FTR"] * 100, "fTOV%": ff["def"]["TOV"] * 100,
            },
        })
    return out


def rolling(values, window=3):
    """Trailing moving average of `values` (lists shorter than window pass through)."""
    out = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1):i + 1]
        out.append(sum(chunk) / len(chunk) if chunk else 0.0)
    return out


def wins_losses_splits(team_id, game_log, events=None):
    """
    Per-game average box + efficiency split by wins vs losses (tracked games).
    Returns {'W': {...}, 'L': {...}} with PF, PA, eFG, TOV, ORB, AST, Pace per game.
    """
    out = {}
    for tag, want_win in (("W", True), ("L", False)):
        gids = [g["game_id"] for g in game_log
                if g["tracked"] and g["won"] == want_win]
        n = len(gids)
        if not n:
            out[tag] = None
            continue
        evs = [e for e in events if e["game_id"] in set(gids)] \
            if events is not None else None
        tb, ob = team_and_opp_box(team_id, gids, events=evs)
        poss = S.estimate_possessions(tb)
        opp_poss = S.estimate_possessions(ob)
        gl = [g for g in game_log if g["game_id"] in set(gids)]
        out[tag] = {
            "n": n,
            "PF": _safe(sum(g["pf"] for g in gl), n),
            "PA": _safe(sum(g["pa"] for g in gl), n),
            "MOV": _safe(sum(g["margin"] for g in gl), n),
            "eFG": S.efg(tb), "oeFG": S.efg(ob),
            "FG": S.fg_pct(tb), "TP": S.fg3_pct(tb), "TS": S.ts(tb),
            "TOV": tb["TOV"] / n, "ORB": tb["ORB"] / n, "DRB": tb["DRB"] / n,
            "AST": tb["AST"] / n, "STL": tb["STL"] / n, "BLK": tb["BLK"] / n,
            "ORtg": 100 * _safe(sum(g["pf"] for g in gl), poss),
            "DRtg": 100 * _safe(sum(g["pa"] for g in gl), opp_poss),
            "NetRtg": 100 * (_safe(sum(g["pf"] for g in gl), poss)
                             - _safe(sum(g["pa"] for g in gl), opp_poss)),
            "Pace": _safe(poss, n),
        }
    return out


def home_away_splits(team_id, game_log):
    """
    Record + scoring split by venue. `games` convention: team1_id = home, so the
    team is 'Home' when site=='vs', 'Away' when '@'. Returns {'Home':{...},'Away':{...}}.
    """
    out = {}
    for tag, site in (("Home", "vs"), ("Away", "@")):
        gl = [g for g in game_log if g["site"] == site]
        n = len(gl)
        out[tag] = {
            "n": n, "W": sum(1 for g in gl if g["won"]),
            "L": sum(1 for g in gl if not g["won"]),
            "PF": _safe(sum(g["pf"] for g in gl), n),
            "PA": _safe(sum(g["pa"] for g in gl), n),
            "MOV": _safe(sum(g["margin"] for g in gl), n),
        }
    return out


def player_oliver_ratings(team_id, game_ids=None, events=None):
    """
    {player_id: {'ORtg','DRtg'}} — Dean Oliver individual offensive/defensive
    ratings for this team's players over the tracked games (directional; see
    helpers/stats.py header). None where the player has no usable possessions.
    """
    if not game_ids:
        return {}
    if events is None:
        events = S.fetch_events(game_ids)
    fp = S.oncourt_fraction(game_ids)
    team_of = _player_team_map()
    out = {}
    for pid in [p for p, t in team_of.items() if t == team_id]:
        if pid not in fp:
            continue
        ortg = S.individual_offensive_rating(pid, team_id, game_ids,
                                             events=events, fp=fp.get(pid))
        drtg = S.individual_defensive_rating(pid, team_id, game_ids,
                                             events=events, fp=fp.get(pid))
        if ortg is None and drtg is None:
            continue
        out[pid] = {"ORtg": ortg, "DRtg": drtg}
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  ASSIST NETWORK  (who creates for whom — passer → finisher)
# ══════════════════════════════════════════════════════════════════════════════

def assist_network(team_id, game_ids=None, events=None):
    """
    The team's made-shot passing network over the tracked games. Every made field
    goal that came off a pass is an edge: passer → finisher.

    Returns (player ids only — the page maps them to names):
      edges        [{'from','to','count','pts'}] sorted by count desc (made FGs)
      assists      {pid: assists given}
      assisted_fgm {pid: made FGs the player scored off a teammate's pass}
      made_fg      {pid: total made FGs}
      unassisted   {pid: made FGs taken with no pass into them}
      totals       {'made','assisted','ast_rate'}
    Opponent shots are excluded (shooter_team_id must equal team_id).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    edges = defaultdict(lambda: {"count": 0, "pts": 0})
    assists = defaultdict(int)
    assisted_fgm = defaultdict(int)
    made_fg = defaultdict(int)
    unassisted = defaultdict(int)
    total_made = total_assisted = 0
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] != team_id:
            continue
        if e["shot_result"] != "make":
            continue
        shooter = e["primary_player_id"]
        if shooter is None:
            continue
        pts = 3 if e["shot_type"] == 3 else 2
        made_fg[shooter] += 1
        total_made += 1
        passer = e["pass_from_id"]
        if passer is not None:
            edges[(passer, shooter)]["count"] += 1
            edges[(passer, shooter)]["pts"] += pts
            assists[passer] += 1
            assisted_fgm[shooter] += 1
            total_assisted += 1
        else:
            unassisted[shooter] += 1
    edge_list = [{"from": p, "to": s, **d} for (p, s), d in edges.items()]
    edge_list.sort(key=lambda x: x["count"], reverse=True)
    return {
        "edges": edge_list,
        "assists": dict(assists),
        "assisted_fgm": dict(assisted_fgm),
        "made_fg": dict(made_fg),
        "unassisted": dict(unassisted),
        "totals": {"made": total_made, "assisted": total_assisted,
                   "ast_rate": _safe(total_assisted, total_made)},
    }


# ══════════════════════════════════════════════════════════════════════════════
#  SCORE FLOW  (cumulative score over a single game) + biggest runs
# ══════════════════════════════════════════════════════════════════════════════

# High-school period lengths (seconds): 8-minute quarters, 4-minute overtimes.
_Q_SECONDS = 8 * 60
_OT_SECONDS = 4 * 60


def _clock_to_secs(text):
    """'M:SS' game clock → seconds remaining (0 on parse failure)."""
    try:
        m, s = str(text).split(":")
        return int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return 0.0


def _period_start(q):
    """Elapsed game seconds at the START of period q (1-indexed)."""
    if q <= 1:
        return 0.0
    full_q = min(q - 1, 4)        # regulation quarters already complete
    ot = max(q - 5, 0)            # OT periods already complete before this one
    return full_q * _Q_SECONDS + ot * _OT_SECONDS


def score_flow(team_id, game_id, events=None):
    """
    The running score of a single game for this team vs its opponent, point by
    point. Returns:
      points  [{'t': minutes elapsed, 'team', 'opp', 'margin', 'q'}] (t ascending,
              starting 0-0)
      runs    {'team','opp'} the biggest unanswered run by each side
      final   {'team','opp','margin'}
      lead    {'max','min'} biggest lead / deepest deficit (min ≤ 0)
    Scoring events only (made shots + made FTs). Elapsed time uses 8-min quarters
    and 4-min OTs; sequence order (event id) breaks ties / handles bad clocks.
    """
    if events is None:
        events = S.fetch_events([game_id])
    evs = sorted([e for e in events if e["game_id"] == game_id],
                 key=lambda e: e["id"])
    seq = []        # (elapsed_minutes, scored_by_us, points, q)
    for e in evs:
        if e["shot_result"] != "make":
            continue
        if e["event_type"] == "shot":
            val = 3 if e["shot_type"] == 3 else 2
        elif e["event_type"] == "free_throw":
            val = 1
        else:
            continue
        st_team = e["shooter_team_id"]
        if st_team is None:
            continue
        q = e["quarter"] or 1
        plen = _Q_SECONDS if q <= 4 else _OT_SECONDS
        elapsed = _period_start(q) + (plen - _clock_to_secs(e["time"]))
        seq.append((elapsed / 60.0, st_team == team_id, val, q))
    seq.sort(key=lambda x: x[0])

    points = [{"t": 0.0, "team": 0, "opp": 0, "margin": 0, "q": 1}]
    ts = os = 0
    run_t = run_o = best_t = best_o = 0
    max_lead = min_lead = 0
    for t, ours, val, q in seq:
        if ours:
            ts += val
            run_t += val
            run_o = 0
            best_t = max(best_t, run_t)
        else:
            os += val
            run_o += val
            run_t = 0
            best_o = max(best_o, run_o)
        margin = ts - os
        max_lead = max(max_lead, margin)
        min_lead = min(min_lead, margin)
        points.append({"t": round(t, 2), "team": ts, "opp": os,
                       "margin": margin, "q": q})
    return {
        "points": points,
        "runs": {"team": best_t, "opp": best_o},
        "final": {"team": ts, "opp": os, "margin": ts - os},
        "lead": {"max": max_lead, "min": min_lead},
    }


# ══════════════════════════════════════════════════════════════════════════════
#  POSSESSION OUTCOMES  (for a Sankey — how every trip ends)
# ══════════════════════════════════════════════════════════════════════════════

def possession_outcomes(team_id, game_ids=None, events=None, offense=True):
    """
    How the team's possessions end (a possession = one shot OR one turnover — the
    locked rule, so 'total' == FGA + TOV == possessions). Returns counts for a
    Sankey diagram:
      {'twos': {'make','miss'}, 'threes': {'make','miss'}, 'tov',
       'assisted2','assisted3', 'total'}
    offense=True for the team's own trips; False for the opponents' trips. Note
    fetch_events joins shooter_team_id off the primary player, so it is the
    committing team for turnovers too.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    out = {"twos": {"make": 0, "miss": 0}, "threes": {"make": 0, "miss": 0},
           "tov": 0, "assisted2": 0, "assisted3": 0, "total": 0}
    for e in events:
        etype = e["event_type"]
        if etype not in ("shot", "turnover"):
            continue
        st_team = e["shooter_team_id"]
        if st_team is None or (st_team == team_id) != offense:
            continue
        if etype == "turnover":
            out["tov"] += 1
            out["total"] += 1
            continue
        made = e["shot_result"] == "make"
        three = e["shot_type"] == 3
        key = "threes" if three else "twos"
        out[key]["make" if made else "miss"] += 1
        if made and e["pass_from_id"] is not None:
            out["assisted3" if three else "assisted2"] += 1
        out["total"] += 1
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  STREAKS, FORM & SITUATIONAL RECORDS  (pure functions of the game log)
# ══════════════════════════════════════════════════════════════════════════════

def streaks_and_form(game_log):
    """
    Momentum & situational record from the full game log (oldest first):
      current     {'type': 'W'|'L'|None, 'len'}
      longest_win, longest_loss
      last5, last10  {'w','l'} over the most recent N games
      close       {'w','l'} games decided by ≤ 5
      one_poss    {'w','l'} games decided by ≤ 3
      blowout     {'w','l'} games decided by ≥ 15
      form        most recent 10 results ('W'/'L', oldest→newest)
      avg_win_margin, avg_loss_margin
    """
    results = [g["won"] for g in game_log]
    cur_type, cur_len = None, 0
    if results:
        last = results[-1]
        cur_type = "W" if last else "L"
        for r in reversed(results):
            if r == last:
                cur_len += 1
            else:
                break
    longest_win = longest_loss = run = 0
    prev = None
    for r in results:
        run = run + 1 if r == prev else 1
        prev = r
        if r:
            longest_win = max(longest_win, run)
        else:
            longest_loss = max(longest_loss, run)

    def _rec(games):
        w = sum(1 for g in games if g["won"])
        return {"w": w, "l": len(games) - w}

    close = [g for g in game_log if abs(g["margin"]) <= 5]
    one_poss = [g for g in game_log if abs(g["margin"]) <= 3]
    blow = [g for g in game_log if abs(g["margin"]) >= 15]
    wins = [g["margin"] for g in game_log if g["won"]]
    losses = [g["margin"] for g in game_log if not g["won"]]
    return {
        "current": {"type": cur_type, "len": cur_len},
        "longest_win": longest_win, "longest_loss": longest_loss,
        "last5": _rec(game_log[-5:]), "last10": _rec(game_log[-10:]),
        "close": _rec(close), "one_poss": _rec(one_poss), "blowout": _rec(blow),
        "form": ["W" if g["won"] else "L" for g in game_log[-10:]],
        "avg_win_margin": _safe(sum(wins), len(wins)),
        "avg_loss_margin": _safe(sum(losses), len(losses)),
    }


def strength_of_schedule(game_log, power_by_team, rank_by_team, n_teams):
    """
    Schedule strength from results-based power ratings:
      avg_opp_power   mean opponent Power (50 = league average)
      n_rated         opponents that had a rating
      vs_top   {'w','l'}  record vs top-25% ranked opponents
      vs_top10 {'w','l'}  record vs top-10 ranked opponents
      quality_wins    wins over top-25% opponents
      top_cut         the rank cutoff used for "top"
      toughest        {'opp','power','margin','won'} highest-power opponent faced
    `power_by_team` / `rank_by_team` are {team_id: value} (the page's scored dict).
    """
    top_cut = max(round(n_teams * 0.25), 1)
    powers = []
    vs_top = {"w": 0, "l": 0}
    vs_top10 = {"w": 0, "l": 0}
    quality_wins = 0
    toughest = None
    for g in game_log:
        opp = g["opp_id"]
        pw = power_by_team.get(opp)
        rk = rank_by_team.get(opp)
        if pw is not None:
            powers.append(pw)
            if toughest is None or pw > toughest["power"]:
                toughest = {"opp": g["opp"], "power": pw,
                            "margin": g["margin"], "won": g["won"]}
        if rk is not None and rk <= top_cut:
            vs_top["w" if g["won"] else "l"] += 1
            if g["won"]:
                quality_wins += 1
        if rk is not None and rk <= 10:
            vs_top10["w" if g["won"] else "l"] += 1
    return {
        "avg_opp_power": _safe(sum(powers), len(powers)),
        "n_rated": len(powers),
        "vs_top": vs_top, "vs_top10": vs_top10,
        "quality_wins": quality_wins, "top_cut": top_cut,
        "toughest": toughest,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CONVENIENCE BUNDLE
# ══════════════════════════════════════════════════════════════════════════════

def team_bundle(team_id, gender=None, min_games=1):
    """
    One call that assembles the team's analytics from tracked games:
        game_log, record (all games), tracked record/efficiency (S.team_summary),
        team_box, opp_box, four_factors, breakeven, scoring (off/def),
        event breakdown (creation + quarter + OREB), and the player rows.
    Ratings (Score/Tracked power) are NOT included — the page already computes
    the league-wide rating dicts and can index this team out of them.
    """
    game_log = team_game_log(team_id)
    tracked_ids = [g["game_id"] for g in game_log if g["tracked"]]

    events = S.fetch_events(tracked_ids) if tracked_ids else []
    tb, ob = team_and_opp_box(team_id, tracked_ids, events=events) if tracked_ids \
        else (S.finalize_box(S._blank_box()), S.finalize_box(S._blank_box()))

    return {
        "game_log": game_log,
        "tracked_ids": tracked_ids,
        "record": record_summary(game_log),
        "record_vs_class": record_vs_class(game_log),
        "summary": S.team_summary(team_id) if tracked_ids else {},
        "team_box": tb, "opp_box": ob,
        "four_factors": four_factors(tb, ob),
        "breakeven": shooting_breakeven(tb),
        "scoring_off": scoring_sources(tb),
        "scoring_def": scoring_sources(ob),
        "breakdown": team_event_breakdown(team_id, tracked_ids, events=events)
        if tracked_ids else {"creation": {"self": {"FGA": 0, "FGM": 0, "pct": 0},
                                          "asst": {"FGA": 0, "FGM": 0, "pct": 0}},
                             "creation_by_game": {}, "quarter": {}},
        "quarter_boxes": quarter_boxes(team_id, tracked_ids, events=events)
        if tracked_ids else {},
        "players": team_player_rows(team_id, gender=gender, min_games=min_games),
        # ── deep analytics (tracked only) ──────────────────────────────────
        "zones": zone_splits(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "zones_by_type": zone_splits_by_type(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "zone_xfg": zone_xfg(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "zone_xfg_by_type": zone_xfg_by_type(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "guarded": guarded_splits(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "guarded_detail": guarded_detail(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "creation_breakdown": creation_breakdown(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "creation_by_type": creation_by_type(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "creation_quarter": creation_quarter_splits(team_id, tracked_ids, events=events)
        if tracked_ids else {},
        "player_zone_leaders": player_zone_leaders(team_id, tracked_ids)
        if tracked_ids else None,
        "poss_length": possession_length_splits(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "trend": per_game_metrics(team_id, game_log, events=events)
        if tracked_ids else [],
        "per_game_full": per_game_team_stats(team_id, game_log, events=events)
        if tracked_ids else [],
        "quarter_by_game": quarter_boxes_by_game(team_id, tracked_ids, events=events)
        if tracked_ids else {},
        "wl_splits": wins_losses_splits(team_id, game_log, events=events)
        if tracked_ids else {"W": None, "L": None},
        "venue": home_away_splits(team_id, game_log),
        # ── futuristic / advanced lab (tracked only, except streaks) ──────────
        "assist_network": assist_network(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "poss_outcomes": possession_outcomes(team_id, tracked_ids, events=events)
        if tracked_ids else None,
        "poss_outcomes_def": possession_outcomes(team_id, tracked_ids,
                                                 events=events, offense=False)
        if tracked_ids else None,
        "streaks": streaks_and_form(game_log),
    }
