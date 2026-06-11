"""
player_ratings.py — Per-player 0-100 rating engine for APP5.0.

Rates every eligible player on FIVE numbers, each on a 0-100 scale where
50 = pool average and +10 = one standard deviation better than the pool
(the same scaling as helpers/team_ratings._power_scale):

    OVERALL      average of the other four ratings + PER + Game Score
    OFFENSE      Shooting rating + Finishing rating
    DEFENSE      Stocks · Steals · Blocks · Guarded%
    PLAYMAKING   Assists · Shots Created · SC-Pass · Turnovers(inv) · AST/TOV
    REBOUNDING   OREB · DREB · REB · REB% · OREB% · DREB%

Each rating is built bottom-up: every underlying stat is turned into a z-score
across the eligible pool, related z-scores are averaged into a category z, and
the category z is mapped to 0-100. Counting stats are per-game so players with
different games-played are comparable. Rate stats (3P%, TS%, Paint%, Guarded%,
REB% …) and "% while on court" come straight from the engine.

Sub-rating definitions (per the ratings spec):
    Shooting  = 3PR (3PA/FGA) · 3P% · TS%
    Finishing = Paint FG% · Paint shots per game
    SC-Pass   = SC - FGA  (shots created that aren't the player's own attempts)
    PER       = Game Score proxy (see helpers/stats.per — single-program DB)

Pure data layer: depends only on database.db and helpers.stats, never on
streamlit, so any page or script can import it.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.shrinkage as SHR


CATEGORIES = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]

DEFAULT_MIN_GAMES = 1   # players below this are dropped from the pool (and z-math)


def sample_confidence(gp):
    """Coarse reliability flag for how much to trust a player's ratings.

    A 0-100 rating built on 2 games is mostly noise; this lets every view label
    or gray-out thin samples instead of presenting them with false precision.
    """
    if gp >= 10:
        return "High"
    if gp >= 6:
        return "Medium"
    if gp >= 3:
        return "Low"
    return "Very Low"


_safe = S._safe   # shared definition lives in helpers.stats


# ══════════════════════════════════════════════════════════════════════════════
#  SCALING  (pool-relative z-score -> 0-100, 50 = average)
# ══════════════════════════════════════════════════════════════════════════════

def _zscores(values):
    """
    {pid: value} -> {pid: z}, computed over the non-None values only.
    Players whose value is None get z=None (they sit out this stat's average).
    """
    present = {p: v for p, v in values.items() if v is not None}
    n = len(present)
    if n == 0:
        return {p: None for p in values}
    mean = sum(present.values()) / n
    var = _safe(sum((v - mean) ** 2 for v in present.values()), n)
    sd = var ** 0.5
    out = {}
    for p, v in values.items():
        out[p] = None if v is None else (_safe(v - mean, sd) if sd else 0.0)
    return out


def _scale100(z):
    """z-score -> 0-100 power index (50 = pool average, +10 per std dev)."""
    if z is None:
        return None
    return S.scale100(z)


def _avg_z(zs):
    """Average the present (non-None) z-scores; None if none are present."""
    vals = [z for z in zs if z is not None]
    return sum(vals) / len(vals) if vals else None


# ══════════════════════════════════════════════════════════════════════════════
#  RAW PER-PLAYER PROFILE
# ══════════════════════════════════════════════════════════════════════════════

def _player_meta(gender=None):
    """{player_id: {'name','number','team_id','team'}} (optionally one gender)."""
    clause = "WHERE t.gender = ?" if gender else ""
    params = (gender,) if gender else ()
    rows = query(
        f"""SELECT p.id, p.name, p.number, p.team_id,
                   t.name AS team, t.class AS class
            FROM players p JOIN teams t ON t.id = p.team_id
            {clause}""",
        params,
    )
    return {r["id"]: {"name": r["name"], "number": r["number"],
                      "team_id": r["team_id"], "team": r["team"],
                      "class": r["class"]} for r in rows}


def player_profiles(game_ids=None, gender=None, min_games=DEFAULT_MIN_GAMES):
    """
    Raw stat profile for every eligible player (GP >= min_games, matching gender).

    Returns {player_id: profile} where profile holds the box, games played, the
    per-game / rate inputs the ratings are built from, and meta (name/team).
    A value of None means "undefined for this player" (e.g. 3P% with no 3PA) and
    is skipped in the z-score math rather than counted as zero.
    """
    events = S.fetch_events(game_ids)
    boxes = S.aggregate_player_boxes(game_ids, events=events)
    gp = S.games_played(game_ids)
    oc = S.oncourt_rate_stats(game_ids, events=events)
    meta = _player_meta(gender=gender)

    profiles = {}
    for pid, m in meta.items():
        g = gp.get(pid, 0)
        if g < min_games:
            continue
        b = boxes.get(pid, S.finalize_box(S._blank_box()))
        o = oc.get(pid, {})

        FGA = b["FGA"]
        per_g = lambda x: x / g if g else 0.0

        # AST/TOV: undefined with no turnovers AND no assists; else assists if
        # turnover-free (denominator 1), otherwise the true ratio.
        if b["TOV"]:
            ast_tov = b["AST"] / b["TOV"]
        elif b["AST"]:
            ast_tov = float(b["AST"])
        else:
            ast_tov = None

        profiles[pid] = {
            **m,
            "GP": g,
            "box": b,
            # ── OFFENSE ─────────────────────────────────────────────
            "3PR":   _safe(b["3PA"], FGA) if FGA else None,
            "3P%":   _safe(b["3PM"], b["3PA"]) if b["3PA"] else None,
            "TS%":   S.ts(b) if (FGA or b["FTA"]) else None,
            "Paint%": S.paint_fg_pct(b) if b["paint_FGA"] else None,
            "PaintSh/G": per_g(b["paint_FGA"]),
            # ── DEFENSE ─────────────────────────────────────────────
            "Stocks/G": per_g(b["STL"] + b["BLK"]),
            "STL/G": per_g(b["STL"]),
            "BLK/G": per_g(b["BLK"]),
            "Guarded%": o.get("guarded_pct") if o.get("opp_FGA_on") else None,
            # ── PLAYMAKING ──────────────────────────────────────────
            "AST/G": per_g(b["AST"]),
            "SC/G": per_g(b["SC"]),
            "SCPass/G": per_g(b["SC"] - FGA),
            "TOV/G": per_g(b["TOV"]),
            "AST/TOV": ast_tov,
            # ── REBOUNDING ──────────────────────────────────────────
            "OREB/G": per_g(b["ORB"]),
            "DREB/G": per_g(b["DRB"]),
            "REB/G": per_g(b["TRB"]),
            "OREB%": o.get("oreb_pct") if o.get("oreb_avail") else None,
            "DREB%": o.get("dreb_pct") if o.get("dreb_avail") else None,
            "REB%":  o.get("reb_pct") if o.get("reb_avail") else None,
            # ── PRODUCTION (feeds OVERALL) ──────────────────────────
            "GS/G":  per_g(S.game_score(b)),
            "PER/G": per_g(S.per(b)),
        }
    return profiles


# ══════════════════════════════════════════════════════════════════════════════
#  RATINGS
# ══════════════════════════════════════════════════════════════════════════════

# leaf stats grouped by sub-rating; True = lower is better (z gets negated)
_SHOOTING  = [("3PR", False), ("3P%", False), ("TS%", False)]
_FINISHING = [("Paint%", False), ("PaintSh/G", False)]
_DEFENSE   = [("Stocks/G", False), ("STL/G", False), ("BLK/G", False),
              ("Guarded%", False)]
_PLAYMAKING = [("AST/G", False), ("SC/G", False), ("SCPass/G", False),
               ("TOV/G", True), ("AST/TOV", False)]
_REBOUNDING = [("OREB/G", False), ("DREB/G", False), ("REB/G", False),
               ("REB%", False), ("OREB%", False), ("DREB%", False)]


def player_ratings(game_ids=None, gender=None, min_games=DEFAULT_MIN_GAMES,
                   stabilize=True):
    """
    Compute every player's five 0-100 ratings over the eligible pool.

    Returns {player_id: row} where row has:
        name, number, team, team_id, GP,
        OVERALL, OFFENSE, DEFENSE, PLAYMAKING, REBOUNDING,   (0-100)
        Shooting, Finishing,                                 (0-100 sub-ratings)
        Rank,                                                (1 = best OVERALL)
        plus the raw stat inputs (3P%, TS%, Guarded%, REB%, GS/G, …) for display.
    Empty dict if no eligible players.

    `stabilize` (default True) pulls every 0-100 rating toward 50 by games played
    (helpers.shrinkage.stabilize_index), so a 1-game cameo can't post a 90 OVERALL
    on noise. Ranks are assigned on the stabilized OVERALL. Pass stabilize=False
    for the raw, unregressed z-score ratings (e.g. to show raw-vs-stable).
    """
    profiles = player_profiles(game_ids, gender=gender, min_games=min_games)
    if not profiles:
        return {}

    pids = list(profiles)

    # z-score every leaf stat across the pool, once
    def zcol(stat):
        return _zscores({p: profiles[p][stat] for p in pids})

    def zcol_signed(stat, lower_better):
        z = zcol(stat)
        if lower_better:
            z = {p: (None if v is None else -v) for p, v in z.items()}
        return z

    def group_z(group):
        """Per-player averaged z over a list of (stat, lower_better) leaves."""
        cols = {stat: zcol_signed(stat, lb) for stat, lb in group}
        return {p: _avg_z([cols[stat][p] for stat, _ in group]) for p in pids}

    shooting_z  = group_z(_SHOOTING)
    finishing_z = group_z(_FINISHING)
    defense_z    = group_z(_DEFENSE)
    playmaking_z = group_z(_PLAYMAKING)
    rebounding_z = group_z(_REBOUNDING)
    offense_z = {p: _avg_z([shooting_z[p], finishing_z[p]]) for p in pids}

    # OVERALL = average of the four category z's + PER + Game Score (per game)
    gs_z  = zcol("GS/G")
    per_z = zcol("PER/G")
    overall_z = {
        p: _avg_z([offense_z[p], defense_z[p], playmaking_z[p], rebounding_z[p],
                   per_z[p], gs_z[p]])
        for p in pids
    }

    def _rate(z, g):
        """0-100 rating from a z-score, regressed toward 50 by games when on."""
        v = _scale100(z)
        if stabilize:
            v = SHR.stabilize_index(v, g)
        return _round(v)

    out = {}
    for p in pids:
        prof = profiles[p]
        b = prof["box"]
        g = prof["GP"]
        out[p] = {
            "name": prof["name"], "number": prof["number"],
            "team": prof["team"], "team_id": prof["team_id"], "GP": prof["GP"],
            "OVERALL":    _rate(overall_z[p], g),
            "OFFENSE":    _rate(offense_z[p], g),
            "DEFENSE":    _rate(defense_z[p], g),
            "PLAYMAKING": _rate(playmaking_z[p], g),
            "REBOUNDING": _rate(rebounding_z[p], g),
            "Shooting":   _rate(shooting_z[p], g),
            "Finishing":  _rate(finishing_z[p], g),
            # raw stats for display
            "PTS": b["PTS"], "REB": b["TRB"], "AST": b["AST"],
            "STL": b["STL"], "BLK": b["BLK"], "TOV": b["TOV"],
            "3P%":  _pct(prof["3P%"]), "TS%": _pct(prof["TS%"]),
            "Paint%": _pct(prof["Paint%"]),
            "Guarded%": _pct(prof["Guarded%"]),
            "REB%": _pct(prof["REB%"]),
            "OREB%": _pct(prof["OREB%"]), "DREB%": _pct(prof["DREB%"]),
            "AST/TOV": _round(prof["AST/TOV"]),
            "SC": b["SC"],
            "GS/G": _round(prof["GS/G"]),
        }
    _assign_ranks(out)
    return out


def _assign_ranks(ratings):
    """Add 1-based 'Rank' by descending OVERALL (in place)."""
    order = sorted(ratings, key=lambda p: ratings[p]["OVERALL"], reverse=True)
    for i, p in enumerate(order, 1):
        ratings[p]["Rank"] = i


def _round(v, nd=1):
    return None if v is None else round(v, nd)


def _pct(v, nd=1):
    """Rate (0-1) -> percentage rounded; None passes through."""
    return None if v is None else round(100 * v, nd)


def _ci_pct(made, att):
    """95% Wilson CI for a make/attempt rate as (lo, hi) in 0-100; (None, None)
    with no attempts. Lets the UI show how wide a small-sample % really is."""
    lo, hi = SHR.wilson_interval(made, att)
    if lo is None:
        return None, None
    return round(100 * lo, 1), round(100 * hi, 1)


def _versatility(per_game, pool_means):
    """
    Versatility Index (0-100) — how evenly a player fills the box score.

    Each of the five per-game pillars (PTS, REB, AST, STL, BLK) is normalised by
    the pool average for that stat, so they share comparable "x times league
    average" units. The normalised contributions are turned into shares and run
    through Shannon entropy, scaled by ln(5) so a player who contributes evenly
    across all five scores 100 and a one-dimensional player scores near 0. It
    rewards genuine do-it-all production, not raw volume. Made-up, but meaningful.
    """
    parts = []
    for key in ("PPG", "RPG", "APG", "SPG", "BPG"):
        m = pool_means.get(key, 0.0)
        parts.append(per_game[key] / m if m > 0 else 0.0)
    tot = sum(parts)
    if tot <= 0:
        return None
    shares = [p / tot for p in parts]
    h = -sum(s * math.log(s) for s in shares if s > 0)
    return round(max(0.0, 100 * h / math.log(len(parts))), 1)


# ══════════════════════════════════════════════════════════════════════════════
#  COMPREHENSIVE STAT TABLE  (one flat row per player — every stat we track)
# ══════════════════════════════════════════════════════════════════════════════

def player_stat_table(game_ids=None, gender=None, min_games=DEFAULT_MIN_GAMES,
                      stabilize=True):
    """
    A single flat row per eligible player holding EVERY stat the app computes:
    meta (name/number/team/class), games, the five 0-100 ratings, raw totals,
    per-game rates, shooting splits, on-court rate stats and the advanced shot
    metrics. This is what the Players page leaderboards / Best-Five / compare /
    profile views all read from, so they never re-derive anything.

    Percentages are returned 0-100 (e.g. 47.5), counting stats are integers,
    per-game stats are rounded floats. A None means the stat is undefined for
    that player (e.g. 3P% with no 3PA) and should be skipped, not treated as 0.
    """
    profiles = player_profiles(game_ids, gender=gender, min_games=min_games)
    if not profiles:
        return {}
    ratings = player_ratings(game_ids, gender=gender, min_games=min_games,
                             stabilize=stabilize)

    # shared event pass + rate tables so the per-player advanced metrics below
    # don't each refetch / recompute the whole sample.
    events     = S.fetch_events(game_ids)
    diff_rates = S.shot_difficulty_rates(events=events)
    qual_rates = S.shot_quality_rates(events=events)
    cre_rates  = S.creation_fg_rates(events=events)

    # whole-sample lineup tables (minutes / +/- / defended FG%), computed once.
    mins     = S.minutes_played(game_ids)
    pm       = S.plus_minus(game_ids)
    dfg      = S.defended_fg_pct(events=events)

    # per-quarter + per-game box passes (clutch scoring, DD/TD, highs, variance)
    qbox  = S.quarter_boxes(events=events)
    gbox  = S.player_game_boxes(events=events)

    # pool per-game means for the Versatility entropy normaliser
    _pm_keys = ("PPG", "RPG", "APG", "SPG", "BPG")
    _pm_box  = {"PPG": "PTS", "RPG": "TRB", "APG": "AST", "SPG": "STL", "BPG": "BLK"}
    pool_means = {}
    for k in _pm_keys:
        vals = [profiles[p]["box"][_pm_box[k]] / profiles[p]["GP"]
                for p in profiles if profiles[p]["GP"]]
        pool_means[k] = (sum(vals) / len(vals)) if vals else 0.0

    # team possessions across the sample (denominator for USG%), over ALL of a
    # team's players, not just the ones who clear the games filter.
    all_boxes = S.aggregate_player_boxes(game_ids, events=events)
    team_of = {r["id"]: r["team_id"]
               for r in query("SELECT id, team_id FROM players")}
    team_poss = defaultdict(float)
    team_min  = defaultdict(float)
    for ppid, bb in all_boxes.items():
        tid = team_of.get(ppid)
        team_poss[tid] += S.estimate_possessions(bb)
        team_min[tid]  += mins.get(ppid, 0.0)
    # Per-team "Tm MP / 5" for USG%: the team's own clock-minutes, = sum of its
    # players' on-floor minutes / 5 (5 players on the floor each moment). This is
    # per-TEAM, not a single global figure — a 1-game opponent's denominator must
    # reflect ~32 min, not the whole league's ~480. Using sum(player min)/5 also
    # cancels the ~16% zero-second minutes undercount (it's in both num & denom).

    out = {}
    for pid, prof in profiles.items():
        b = prof["box"]
        g = prof["GP"]
        rt = ratings.get(pid, {})
        pg = lambda v: round(v / g, 2) if g else 0.0
        has_fga = b["FGA"] > 0

        shot_rt = S.shot_rating(pid, events=events, rates=diff_rates)
        xpps    = S.expected_points_per_shot(pid, events=events, rates=qual_rates) if has_fga else None
        xfg     = S.expected_fg_pct(pid, events=events, rates=cre_rates) if has_fga else None

        # impact / usage
        pmin   = mins.get(pid, 0.0)
        p_poss = S.estimate_possessions(b)
        tposs  = team_poss.get(prof["team_id"], 0.0)
        gmin_t = team_min.get(prof["team_id"], 0.0) / 5.0   # this team's Tm MP/5
        usg    = S.usage_pct(p_poss, pmin, tposs, gmin_t)
        d      = dfg.get(pid, {})
        plus   = pm.get(pid, 0)

        # ── shot-location profile (share of FGA from rim / mid / three) ──
        fga = b["FGA"]
        rim_a = b["paint_FGA"]
        mid_a = b["2PA"] - b["paint_FGA"]
        self_a = b["shots_self"]
        astd_a = b["shots_pass"] + b["shots_both"]

        # ── clutch: 4th-quarter scoring ──────────────────────────────────
        q4 = qbox.get(pid, {}).get(4, {})
        q4_pts = q4.get("PTS", 0)

        # ── versatility (entropy balance of the five per-game pillars) ───
        vers = _versatility(
            {"PPG": b["PTS"] / g, "RPG": b["TRB"] / g, "APG": b["AST"] / g,
             "SPG": b["STL"] / g, "BPG": b["BLK"] / g}, pool_means) if g else None

        # ── per-game milestones / consistency from individual games ──────
        ddtd = S.double_triple_doubles(gbox.get(pid, {}))
        pts_games = ddtd["pts_list"]
        pts_sd = round(statistics.pstdev(pts_games), 1) if len(pts_games) > 1 else 0.0

        # ── two-way index (offense + defense, both 0-100) ────────────────
        off_r, def_r = rt.get("OFFENSE"), rt.get("DEFENSE")
        two_way = (round((off_r + def_r) / 2, 1)
                   if off_r is not None and def_r is not None else None)

        # 95% Wilson confidence bands on the headline shooting rates
        fg_lo, fg_hi = _ci_pct(b["FGM"], b["FGA"])
        tp_lo, tp_hi = _ci_pct(b["3PM"], b["3PA"])
        ft_lo, ft_hi = _ci_pct(b["FTM"], b["FTA"])

        out[pid] = {
            # ── meta ────────────────────────────────────────────────
            "name": prof["name"], "number": prof["number"],
            "team": prof["team"], "team_id": prof["team_id"],
            "class": prof.get("class", "N/A"), "GP": g,
            "Confidence": sample_confidence(g),
            "Rank": rt.get("Rank"),
            # ── ratings (0-100) ─────────────────────────────────────
            "OVERALL": rt.get("OVERALL"), "OFFENSE": rt.get("OFFENSE"),
            "DEFENSE": rt.get("DEFENSE"), "PLAYMAKING": rt.get("PLAYMAKING"),
            "REBOUNDING": rt.get("REBOUNDING"),
            "Shooting": rt.get("Shooting"), "Finishing": rt.get("Finishing"),
            # ── totals ──────────────────────────────────────────────
            "PTS": b["PTS"], "FGM": b["FGM"], "FGA": b["FGA"],
            "2PM": b["2PM"], "2PA": b["2PA"], "3PM": b["3PM"], "3PA": b["3PA"],
            "FTM": b["FTM"], "FTA": b["FTA"],
            "OREB": b["ORB"], "DREB": b["DRB"], "REB": b["TRB"],
            "AST": b["AST"], "STL": b["STL"], "BLK": b["BLK"],
            "STOCKS": b["STL"] + b["BLK"], "TOV": b["TOV"], "PF": b["PF"],
            "SC": b["SC"], "PaintM": b["paint_FGM"], "PaintA": b["paint_FGA"],
            # ── per game ────────────────────────────────────────────
            "PPG": pg(b["PTS"]), "RPG": pg(b["TRB"]), "APG": pg(b["AST"]),
            "SPG": pg(b["STL"]), "BPG": pg(b["BLK"]), "TPG": pg(b["TOV"]),
            "STOCKS/G": pg(b["STL"] + b["BLK"]),
            "OREB/G": pg(b["ORB"]), "DREB/G": pg(b["DRB"]),
            "FGA/G": pg(b["FGA"]), "3PA/G": pg(b["3PA"]),
            "SC/G": pg(b["SC"]), "PF/G": pg(b["PF"]),
            # ── shooting rates (0-100) ──────────────────────────────
            "FG%":  _pct(_safe(b["FGM"], b["FGA"])) if has_fga else None,
            "2P%":  _pct(_safe(b["2PM"], b["2PA"])) if b["2PA"] else None,
            "3P%":  _pct(prof["3P%"]),
            "FT%":  _pct(_safe(b["FTM"], b["FTA"])) if b["FTA"] else None,
            "eFG%": _pct(S.efg(b)) if has_fga else None,
            "TS%":  _pct(prof["TS%"]),
            "Paint%": _pct(prof["Paint%"]),
            "3PR":  _pct(prof["3PR"]),
            "PPSA": _round(S.ppsa(b)) if has_fga else None,
            # ── 95% confidence bands on shooting rates (small-sample honesty) ──
            "FG%lo": fg_lo, "FG%hi": fg_hi,
            "3P%lo": tp_lo, "3P%hi": tp_hi,
            "FT%lo": ft_lo, "FT%hi": ft_hi,
            # ── on-court / playmaking rates ─────────────────────────
            "Guarded%": _pct(prof["Guarded%"]),
            "REB%": _pct(prof["REB%"]),
            "OREB%": _pct(prof["OREB%"]), "DREB%": _pct(prof["DREB%"]),
            "AST/TOV": _round(prof["AST/TOV"]),
            # ── split assists / paint scoring ───────────────────────
            "AST2": b["AST2"], "AST3": b["AST3"],
            "PaintPTS": b["paint_PTS"], "PRF": S.prf(b),
            "PRF/G": pg(S.prf(b)),
            # ── extra shooting / scoring rates ──────────────────────
            "PPS": _round(S.pps(b), 2) if has_fga else None,
            "FTR": _round(S.ftr(b), 2) if has_fga else None,
            # ── impact / usage / per-possession ─────────────────────
            "MIN": _round(pmin), "MPG": pg(pmin),
            "+/-": plus, "+/-/G": pg(plus),
            "USG%": _round(usg),
            "TOV%": _round(S.tov_pct(b)) if p_poss > 0 else None,
            "PPP": _round(S.ppp(b), 2) if p_poss > 0 else None,
            "DSHOT%": _pct(d["pct"]) if d.get("def_FGA") else None,
            "defFGA": d.get("def_FGA", 0),
            # ── composite box metrics ───────────────────────────────
            "EFF": _round(S.eff(b)), "EFF/G": pg(S.eff(b)),
            "FIC": _round(S.fic(b)), "FIC/G": pg(S.fic(b)),
            "VPS": _round(S.vps(b), 2),
            # ── advanced ────────────────────────────────────────────
            "GS": _round(S.game_score(b)), "GS/G": _round(prof["GS/G"]),
            "ShotRating": _round(shot_rt),
            "xPPS": _round(xpps),
            "xFG%": _pct(xfg),
            # SMOE = Shot-Making Over Expected: actual FG% minus the expected FG%
            # of the looks they take (positive = finishes better than shot quality).
            "SMOE": (_round((_safe(b["FGM"], b["FGA"]) - xfg) * 100, 1)
                     if has_fga and xfg is not None else None),
            # ── shot-location profile (% of FGA) ────────────────────
            "RimFGA%": _pct(_safe(rim_a, fga)) if has_fga else None,
            "MidFGA%": _pct(_safe(mid_a, fga)) if has_fga else None,
            # ── shot independence ───────────────────────────────────
            "SelfCr%": _pct(_safe(self_a, fga)) if has_fga else None,
            "Astd%":   _pct(_safe(astd_a, fga)) if has_fga else None,
            # ── shot-creation source mix (shares of the player's total SC) ──
            # SC = own shots (SC_shoot) + passes into shots (SC_pass) + screens
            # that freed a shooter (SC_screen). These three sum to 100% of SC.
            "SCShot%":    _pct(_safe(b["SC_shoot"], b["SC"])) if b["SC"] else None,
            "SCPass%":    _pct(_safe(b["SC_pass"], b["SC"])) if b["SC"] else None,
            "SCCreated%": _pct(_safe(b["SC_screen"], b["SC"])) if b["SC"] else None,
            # ── clutch (4th quarter) ────────────────────────────────
            "Q4PTS": q4_pts, "Q4PPG": pg(q4_pts),
            "Q4%": _pct(_safe(q4_pts, b["PTS"])) if b["PTS"] else None,
            # ── disruption (defensive activity per 32 min) ──────────
            "STOCKS/32": (_round(S.per_minutes(b["STL"] + b["BLK"], pmin, 32))
                          if pmin > 0 else None),
            # ── made-up composites ──────────────────────────────────
            "VERSATILITY": vers,
            "2WAY": two_way,
            # ── per-game milestones / consistency ───────────────────
            "DD": ddtd["dd"], "TD": ddtd["td"],
            "bestPTS": ddtd["best_pts"], "bestREB": ddtd["best_reb"],
            "bestAST": ddtd["best_ast"], "PTSsd": pts_sd,
        }
    return out
