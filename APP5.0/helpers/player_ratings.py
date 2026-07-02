"""
player_ratings.py — Per-player 0-100 rating engine for APP5.0.

Rates every eligible player on FIVE numbers, each on a 0-100 scale where
50 = pool average and +10 = one standard deviation better than the pool
(the same scaling as helpers/team_ratings._power_scale):

    OVERALL      four category ratings + Game Score · EFF · FIC (production)
    OFFENSE      Shooting · Finishing · scoring VOLUME (PPG · PRF/G)
    DEFENSE      Steals · Blocks · Guarded% · DSHOT%(inv) · Fouls(inv)
                 · RimProt · PerimD (FG% saved vs league at the rim / arc)
    PLAYMAKING   Assists · Shots Created · SC-Pass · AST/TOV · TOV%(inv) · pass look-quality
    REBOUNDING   OREB · DREB · REB · REB% · OREB% · DREB%

Each rating is built bottom-up in THREE passes so the spread is real, not
collapsed toward 50:

  1. every underlying stat is turned into a z-score across the eligible pool;
  2. a category's leaf z-scores are combined with per-leaf WEIGHTS (high-signal
     stats count more, redundant/noisy ones less) into a raw category z;
  3. each raw category/overall z is RE-STANDARDIZED across the pool (z' =
     (z-mean)/sd) before mapping to 0-100.

Step 3 is the load-bearing fix: averaging k weakly-correlated z's shrinks the
composite's SD well below 1, so without re-standardizing, scale100's "+10 per
SD" silently became "+5 per real SD" and crushed everyone to ~50 (top player
66). Re-standardizing restores SD=1 so the 50=avg / +10=1 SD contract that
cards.tier() and the lineup engine assume actually holds — and, crucially, it
flips the sign of "more leaves": under raw mean-of-z, extra stats TIGHTEN the
spread; under re-standardized weighted composites, signal-bearing stats WIDEN
it. (Tiny/degenerate pools below MIN_POOL_FOR_RESTD skip step 3 and fall back
to the raw averaged z so a 2-player pool can't blow up.)

Counting stats are per-game so players with different games-played are
comparable. Rate stats (3P%, TS%, Paint%, Guarded%, REB%, DSHOT% …) and
"% while on court" come straight from the engine.

Sub-rating definitions (per the ratings spec):
    Shooting  = 3PR (3PA/FGA) · 3P% · TS% · eFG% · FTR
    Finishing = Paint FG% · Paint shots per game
    SC-Pass   = SC - FGA  (shots created that aren't the player's own attempts)
    DSHOT%    = FG% allowed as the contesting defender (helpers/stats.defended_fg_pct)
    PRF       = Points Responsible For = own pts + assist pts (helpers/stats.prf)

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


def overall_blurb(off, deff, ply, reb):
    """One-line plain-English read of an OVERALL rating from its four 0-100
    pillars (50 = league average) — so a coach can defend the number to a player
    or parent ("Elite rebounding, dragged by turnovers"). Returns '' when too few
    pillars are present to say anything. Pure + gender-neutral."""
    pillars = [("scoring", off), ("defense", deff),
               ("playmaking", ply), ("rebounding", reb)]
    pillars = [(lbl, v) for lbl, v in pillars if v is not None]
    if len(pillars) < 2:
        return ""
    hi_lbl, hi = max(pillars, key=lambda t: t[1])
    lo_lbl, lo = min(pillars, key=lambda t: t[1])

    def _tier(v):
        if v >= 65:
            return "Elite"
        if v >= 57:
            return "Strong"
        if v >= 52:
            return "Solid"
        return ""

    strength = _tier(hi)
    weak = lo <= 43 and lo_lbl != hi_lbl
    if strength and weak:
        return f"{strength} {hi_lbl}, dragged by {lo_lbl}"
    if strength:
        return f"{strength} {hi_lbl}, no real holes" if lo >= 48 else f"{strength} {hi_lbl}"
    if weak:
        return f"Below-average {lo_lbl}, no standout strength"
    return "Balanced — no standout strength or hole"


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


TEAM_REL_COLS = ("OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING")


def team_relative(P, rows, cols=TEAM_REL_COLS):
    """Where a player sits AMONG THEIR OWN TEAMMATES on each rating.

    Display-only: this does NOT re-standardize a team-only pool (that would let a
    weak player on a weak team read as elite). It just ranks the player's
    league-computed ratings against their own roster and reports the position on
    the team's spread — the "true separation between our guys" view that rides
    alongside the master league rating, never replacing it.

    `P` is one player row, `rows` the full league pool (each carrying `team_id`
    and the rating cols). Returns {col: {"rank","n","pos","val"}} where `pos` is
    the 0-1 position on the team's min→max span for that rating (0.5 when the
    team is flat), or {col: None} when there aren't ≥2 rated teammates.
    """
    tid = P.get("team_id")
    mates = [r for r in rows if r.get("team_id") == tid]
    out = {}
    for c in cols:
        vals = [r[c] for r in mates if r.get(c) is not None]
        v = P.get(c)
        if v is None or len(vals) < 2:
            out[c] = None
            continue
        lo, hi = min(vals), max(vals)
        rank = sum(1 for x in vals if x > v) + 1        # 1 = best on the team
        pos = (v - lo) / (hi - lo) if hi > lo else 0.5
        out[c] = {"rank": rank, "n": len(vals), "pos": round(pos, 3), "val": v}
    return out


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


def _wavg(pairs):
    """Weighted mean of (z, weight) pairs over the present (non-None) z's; None
    if none are present. A missing leaf simply drops out of the weighted mean
    (its weight is not counted), so players aren't penalized for an undefined
    stat — they're scored on what they do have."""
    num = wsum = 0.0
    for z, w in pairs:
        if z is not None:
            num += z * w
            wsum += w
    return (num / wsum) if wsum else None


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
    dfg = S.defended_fg_pct(game_ids, events=events)   # DSHOT% — defense quality
    ddr = S.individual_defensive_rating_all(game_ids, events=events)  # DRtg (lower=better)
    xfg = S.expected_fg_pct_all(game_ids, events=events)             # xFG% baseline for SMOE
    plq = S.passer_look_quality(events=events)   # xPPS created — passer look quality
    rpd, _rpd_lg = S.rim_perimeter_defense(events=events)  # rim/perimeter defense
    import helpers.fouls as FL
    ftp = FL.player_foul_ft(events=events)       # clutch FT + and-1 detail
    meta = _player_meta(gender=gender)

    profiles = {}
    for pid, m in meta.items():
        g = gp.get(pid, 0)
        if g < min_games:
            continue
        b = boxes.get(pid, S.finalize_box(S._blank_box()))
        o = oc.get(pid, {})
        df = dfg.get(pid, {})

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
            # ── OFFENSE: efficiency ─────────────────────────────────
            "3PR":   _safe(b["3PA"], FGA) if FGA else None,
            "3P%":   _safe(b["3PM"], b["3PA"]) if b["3PA"] else None,
            "TS%":   S.ts(b) if (FGA or b["FTA"]) else None,
            "eFG%":  S.efg(b) if FGA else None,
            "FTR":   S.ftr(b) if FGA else None,
            # SMOE — shot-making over expected: real FG% minus the FG% expected
            # from the player's shot-creation mix (positive = finishes the looks
            # they take better than the league does).
            "SMOE":  ((_safe(b["FGM"], b["FGA"]) - xfg[pid])
                      if (FGA and pid in xfg) else None),
            "Paint%": S.paint_fg_pct(b) if b["paint_FGA"] else None,
            "PaintSh/G": per_g(b["paint_FGA"]),
            # ── OFFENSE: scoring volume ─────────────────────────────
            "PPG":   per_g(b["PTS"]),
            "PRF/G": per_g(S.prf(b)),
            # ── DEFENSE ─────────────────────────────────────────────
            "Stocks/G": per_g(b["STL"] + b["BLK"]),
            "STL/G": per_g(b["STL"]),
            "BLK/G": per_g(b["BLK"]),
            "Guarded%": o.get("guarded_pct") if o.get("opp_FGA_on") else None,
            "DSHOT%": df.get("pct") if df.get("def_FGA") else None,
            # rim protection / perimeter defense: league FG% − FG% allowed on
            # contested rim 2s / threes (positive = saves points); None below
            # the 8-shot gate so the leaf drops from the weighted mean.
            "RimProt": rpd.get(pid, {}).get("RimProt"),
            "PerimD": rpd.get(pid, {}).get("PerimD"),
            "RimD_FGA": rpd.get(pid, {}).get("rim_fga", 0),
            "RimD_pct": rpd.get(pid, {}).get("rim_pct"),
            "PerimD_FGA": rpd.get(pid, {}).get("per_fga", 0),
            "PerimD_pct": rpd.get(pid, {}).get("per_pct"),
            # clutch free throws + and-1 trips (fouls.py pressure walk)
            "cFTA": ftp.get(pid, {}).get("cFTA", 0),
            "cFTM": ftp.get(pid, {}).get("cFTM", 0),
            "And1": ftp.get(pid, {}).get("and1", 0),
            "And1M": ftp.get(pid, {}).get("and1_made", 0),
            "DRtg":  ddr.get(pid),   # Oliver individual DRtg (per-100, lower=better)
            "PF/G":  per_g(b["PF"]),
            # ── PLAYMAKING ──────────────────────────────────────────
            "AST/G": per_g(b["AST"]),
            "SC/G": per_g(b["SC"]),
            "SCPass/G": per_g(b["SC"] - FGA),
            "TOV/G": per_g(b["TOV"]),
            "TOV%":  S.tov_pct(b) if (FGA or b["TOV"]) else None,
            "AST/TOV": ast_tov,
            # xPPS of the looks this player's passes create (make-independent shot-
            # quality); None for non-passers / < min feeds so it drops from the mean.
            "SCPassQ": plq.get(pid),
            # ── REBOUNDING ──────────────────────────────────────────
            "OREB/G": per_g(b["ORB"]),
            "DREB/G": per_g(b["DRB"]),
            "REB/G": per_g(b["TRB"]),
            "OREB%": o.get("oreb_pct") if o.get("oreb_avail") else None,
            "DREB%": o.get("dreb_pct") if o.get("dreb_avail") else None,
            "REB%":  o.get("reb_pct") if o.get("reb_avail") else None,
            # ── PRODUCTION (feeds OVERALL) ──────────────────────────
            "GS/G":  per_g(S.game_score(b)),
            "EFF/G": per_g(S.eff(b)),
            "FIC/G": per_g(S.fic(b)),
        }
    return profiles


# ══════════════════════════════════════════════════════════════════════════════
#  RATINGS
# ══════════════════════════════════════════════════════════════════════════════

# Leaf stats grouped by sub-rating as (stat, weight, lower_better):
#   weight       how much this leaf counts in the category's weighted-mean z
#                (high-signal stats > redundant/shot-mix ones).
#   lower_better True negates the z (turnovers, fouls, FG% allowed → less is more).
# Every leaf is None-skipped per player (3P% with no 3PA, DSHOT% with no contested
# FGA, …), so a missing stat drops out of the weighted mean rather than counting 0.
_SHOOTING  = [("TS%", 1.5, False), ("3P%", 1.0, False), ("eFG%", 1.0, False),
              ("SMOE", 1.0, False), ("FTR", 0.75, False), ("3PR", 0.5, False)]
_FINISHING = [("Paint%", 1.0, False), ("PaintSh/G", 0.75, False)]
_DEFENSE   = [("DSHOT%", 1.25, True), ("DRtg", 1.0, True), ("STL/G", 1.0, False),
              ("BLK/G", 1.0, False), ("Guarded%", 0.75, False), ("PF/G", 0.5, True),
              # WHERE the defense happens: FG% saved vs league on contested rim
              # 2s / threes (positive = better, so not inverted). Secondary
              # weight — DSHOT% already carries the overall contest signal;
              # these split it into rim protection and perimeter containment.
              ("RimProt", 0.75, False), ("PerimD", 0.75, False)]
_PLAYMAKING = [("AST/G", 1.0, False), ("AST/TOV", 1.0, False), ("SC/G", 0.75, False),
               ("SCPass/G", 0.75, False), ("TOV%", 0.75, True),
               # look QUALITY a passer's feeds create (xPPS), not just volume —
               # rewards creating good shots even when poor shooters miss them.
               ("SCPassQ", 0.75, False)]
_REBOUNDING = [("OREB%", 1.0, False), ("DREB%", 1.0, False), ("REB%", 0.75, False),
               ("OREB/G", 0.75, False), ("DREB/G", 0.75, False), ("REB/G", 0.5, False)]

# How the headline ratings combine their parts (re-standardized component z, weight).
# OFFENSE folds scoring VOLUME (PPG/PRF) onto the two shooting sub-ratings so a
# high-efficiency low-usage spot-up shooter no longer rates like a 25-PPG engine.
_OFFENSE_PARTS = [("shooting", 1.0), ("finishing", 0.6), ("PPG", 1.0), ("PRF/G", 0.75)]
# OVERALL = the four pillars (offense-leaning) + three production anchors. PER was
# a literal duplicate of Game Score, so it is gone; EFF + FIC add independent
# all-around production signal instead of double-counting one composite.
_OVERALL_PARTS = [("offense", 1.1), ("defense", 1.0), ("playmaking", 1.0),
                  ("rebounding", 0.8), ("GS/G", 1.0), ("EFF/G", 0.6), ("FIC/G", 0.5)]

# Pools smaller than this skip composite re-standardization (an SD from 2-3 players
# is meaningless) and fall back to the raw weighted-mean z.
MIN_POOL_FOR_RESTD = 8

# Games-equivalent prior weight for the per-rating shrinkage toward 50 (passed to
# shrinkage.stabilize_index). Higher than shrinkage's default (3) so thin 1-2 game
# samples — typically lightly-tracked opponents — regress harder toward average and
# stop surfacing mid-pack on a single fluky line, without flattening full-season
# players (retention g/(g+k): 1 GP 0.17, 2 GP 0.29, 8 GP 0.62, 15 GP 0.75).
RATING_K_GAMES = 5


def _restandardize(zmap):
    """Re-z a composite z-vector across the pool so it regains unit SD.

    Averaging k weakly-correlated unit-variance leaf z's yields a composite with
    SD well below 1, which silently turns scale100's "+10 per SD" into far less.
    Re-standardizing (z' = (z-mean)/sd over the present values) restores the
    50=avg / +10=1 SD contract before the 0-100 map. Pools below
    MIN_POOL_FOR_RESTD, or with no spread, are returned unchanged (a 2-3 player
    SD is noise) so tiny/early-season pools fall back to the raw averaged z.
    """
    present = {p: v for p, v in zmap.items() if v is not None}
    if len(present) < MIN_POOL_FOR_RESTD:
        return dict(zmap)
    mean = sum(present.values()) / len(present)
    sd = (sum((v - mean) ** 2 for v in present.values()) / len(present)) ** 0.5
    if sd <= 1e-9:
        return dict(zmap)
    return {p: (None if v is None else (v - mean) / sd) for p, v in zmap.items()}


def player_ratings(game_ids=None, gender=None, min_games=DEFAULT_MIN_GAMES,
                   stabilize=True, profiles=None):
    """
    Compute every player's five 0-100 ratings over the eligible pool.

    Returns {player_id: row} where row has:
        name, number, team, team_id, GP,
        OVERALL, OFFENSE, DEFENSE, PLAYMAKING, REBOUNDING,   (0-100)
        Shooting, Finishing,                                 (0-100 sub-ratings)
        Rank,                                                (1 = best OVERALL)
        plus the raw stat inputs (3P%, TS%, Guarded%, REB%, GS/G, …) for display.
    Empty dict if no eligible players.

    Each rating is a weighted mean of its leaf z-scores, re-standardized across
    the pool (see _restandardize), then mapped to 0-100. `stabilize` (default
    True) then pulls every rating toward 50 by games played
    (helpers.shrinkage.stabilize_index), so a 1-game cameo can't post a 90
    OVERALL on noise. Ranks are assigned on the stabilized OVERALL. Pass
    stabilize=False for the raw, unregressed ratings (e.g. to show raw-vs-stable).
    `profiles` lets a caller (player_stat_table) hand in an already-built profile
    map so the engine isn't recomputed twice for one table.
    """
    if profiles is None:
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
        """Weighted-mean z over a list of (stat, weight, lower_better) leaves,
        then re-standardized to unit SD across the pool."""
        cols = {stat: zcol_signed(stat, lb) for stat, _w, lb in group}
        raw = {p: _wavg([(cols[stat][p], w) for stat, w, _lb in group])
               for p in pids}
        return _restandardize(raw)

    def combine(parts, comps):
        """Weighted blend of named component z-maps (from `comps`) and raw leaf
        columns, re-standardized to unit SD. `parts` = [(name, weight), …] where
        name is either a key in `comps` or a profile stat fed through zcol()."""
        cols = {name: (comps[name] if name in comps else zcol(name))
                for name, _w in parts}
        raw = {p: _wavg([(cols[name][p], w) for name, w in parts]) for p in pids}
        return _restandardize(raw)

    shooting_z   = group_z(_SHOOTING)
    finishing_z  = group_z(_FINISHING)
    defense_z    = group_z(_DEFENSE)
    playmaking_z = group_z(_PLAYMAKING)
    rebounding_z = group_z(_REBOUNDING)
    offense_z = combine(_OFFENSE_PARTS,
                        {"shooting": shooting_z, "finishing": finishing_z})
    overall_z = combine(_OVERALL_PARTS,
                        {"offense": offense_z, "defense": defense_z,
                         "playmaking": playmaking_z, "rebounding": rebounding_z})

    def _rate(z, g):
        """0-100 rating from a z-score, regressed toward 50 by games when on."""
        v = _scale100(z)
        if stabilize:
            v = SHR.stabilize_index(v, g, k_games=RATING_K_GAMES)
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
                             stabilize=stabilize, profiles=profiles)

    # shared event pass + rate tables so the per-player advanced metrics below
    # don't each refetch / recompute the whole sample.
    events     = S.fetch_events(game_ids)
    diff_rates = S.shot_difficulty_rates(events=events)
    qual_rates = S.shot_quality_rates(events=events)
    cre_rates  = S.creation_fg_rates(events=events)
    xfg_all    = S.expected_fg_pct_all(events=events, rates=cre_rates)  # one pass for all

    # whole-sample lineup tables (minutes / +/- / defended FG%), computed once.
    mins     = S.minutes_played(game_ids)
    pm       = S.plus_minus(game_ids)
    dfg      = S.defended_fg_pct(events=events)

    # per-quarter + per-game box passes (clutch scoring, DD/TD, highs, variance)
    qbox  = S.quarter_boxes(events=events)
    gbox  = S.player_game_boxes(events=events)

    # tracker-rich per-player signals (one shared pass each): hand-side splits,
    # true-distance bands from tap (x,y), and the one-tap play_type mix. Surfaced
    # for the badge wall + scout cards; sparse where coaches haven't tagged/tapped.
    import helpers.playtypes as PT
    hand_splits = S.player_hand_splits(events=events)
    loc_by_pid = {}
    for _sh in S.located_shots(events=events):
        loc_by_pid.setdefault(_sh["player_id"], []).append(_sh)
    play_by_pid = PT.player_named_playtypes(events=events)

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
        xfg     = xfg_all.get(pid) if has_fga else None

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

        # ── hand-side / true-distance / play_type (tracker-rich) ─────────
        _hs = hand_splits.get(pid) or {}
        _dom = _hs.get("dominant", {}).get("all")
        _weak = _hs.get("weak", {}).get("all")
        _db = S.distance_buckets(loc_by_pid.get(pid, []))
        _near = next((x for x in _db if x["label"] == "<5 ft"), None)
        _deep = next((x for x in _db if x["label"] == "19.75+ ft"), None)
        _pl = play_by_pid.get(pid, {})

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
            # ── shots-created family: feeds + screens ───────────────
            # PotAST = every pass into a shot, make or miss (the box SC_pass);
            # ScrAST = credited screens that freed a MADE FG; Scrn* = the
            # shooter's shots off a screen-action set call with no screener
            # logged (screen-created, credit unassigned).
            "PotAST": b["SC_pass"], "PotAST/G": pg(b["SC_pass"]),
            "ScrAST": b["SCR_AST"], "ScrAST/G": pg(b["SCR_AST"]),
            "ScrnFGA": b["scr_tag_FGA"], "ScrnFGM": b["scr_tag_FGM"],
            "FeedConv%": (_pct(_safe(b["AST"], b["SC_pass"]))
                          if b["SC_pass"] else None),
            "ScrnFG%": (_pct(_safe(b["scr_tag_FGM"], b["scr_tag_FGA"]))
                        if b["scr_tag_FGA"] else None),
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
            "ScEff": _pct(S.scoring_efficiency(b)) if has_fga else None,
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
            # rim / perimeter defended splits (FG% allowed + volume) and the
            # league-relative saves that feed the DEFENSE rating (± FG points)
            "RimDFG%": _pct(prof["RimD_pct"]),
            "RimDShots": prof["RimD_FGA"],
            "PerimDFG%": _pct(prof["PerimD_pct"]),
            "PerimDShots": prof["PerimD_FGA"],
            "RimProt": _pct(prof["RimProt"]),
            "PerimD": _pct(prof["PerimD"]),
            # clutch line trips + and-1s
            "ClutchFTA": prof["cFTA"],
            "ClutchFT%": (_pct(_safe(prof["cFTM"], prof["cFTA"]))
                          if prof["cFTA"] else None),
            "And1": prof["And1"], "And1M": prof["And1M"],
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
            # ── hand-side shooting (dominant vs weak), 0-100 FG% + volume ──
            "Dom_FGA": _dom["FGA"] if _dom else None,
            "Dom_FG%": _pct(_dom["pct"]) if (_dom and _dom["FGA"]) else None,
            "Weak_FGA": _weak["FGA"] if _weak else None,
            "Weak_FG%": _pct(_weak["pct"]) if (_weak and _weak["FGA"]) else None,
            # ── true tap-distance finishing / range (not the zone shadow) ──
            "Near_FGA": _near["n"] if _near else None,
            "Near_FG%": _pct(_near["fg"]) if (_near and _near["n"]) else None,
            "Deep_FGA": _deep["n"] if _deep else None,
            "Deep_FG%": _pct(_deep["fg"]) if (_deep and _deep["n"]) else None,
            # ── per-set play_type efficiency (one-tap coach tags; sparse) ──
            "PnR_poss": _pl.get("pnr", {}).get("poss"),
            "PnR_PPP": _round(_pl.get("pnr", {}).get("PPP"), 2),
            "Post_poss": _pl.get("post", {}).get("poss"),
            "Post_PPP": _round(_pl.get("post", {}).get("PPP"), 2),
            "Iso_poss": _pl.get("iso", {}).get("poss"),
            "Iso_PPP": _round(_pl.get("iso", {}).get("PPP"), 2),
            "Spot_poss": _pl.get("spot", {}).get("poss"),
            "Spot_PPP": _round(_pl.get("spot", {}).get("PPP"), 2),
            "Transition_poss": _pl.get("transition", {}).get("poss"),
            "Transition_PPP": _round(_pl.get("transition", {}).get("PPP"), 2),
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


# ══════════════════════════════════════════════════════════════════════════════
#  FREE / PAID GATING — which player_stat_table keys need tracked events
# ══════════════════════════════════════════════════════════════════════════════
#
# Single source of truth for tier gating (see helpers.entitlement and the
# app5-gating-taxonomy memory). A key is EVENT-DERIVED when it can't be computed
# from a final score + manual box line: the five 0-100 ratings (+ Rank/2WAY that
# ride on them), shot-creation/usage/impact (need lineups, minutes, possessions),
# on-court rate stats (need game_event_lineup), shot quality/location (need the
# court tap), assist-split and clutch (need event/quarter context). Also gated:
# any POSSESSION-derived rate (computed via S.estimate_possessions, POSS = FGA+TOV)
# — PPP and the possession-based TOV% — per the owner's possession carve-out
# (FINAL 2026-06-15): the Free line is "derivable WITHOUT estimating possessions,"
# so per-possession / per-100 rates are Paid even though their inputs are box stats.
# Everything NOT listed here is box-derivable and stays Free — including eFG%/TS%,
# GS/G, VERSATILITY, AST/TOV (pure box ratio) and the per-game milestones.
EVENT_DERIVED_STATS = frozenset({
    # 0-100 ratings (gated wholesale) + the rank that rides on OVERALL
    "OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING",
    "Shooting", "Finishing", "2WAY", "Rank",
    # shot-creation / usage / impact (lineups, minutes, possessions, events)
    "SC", "SC/G", "SCShot%", "SCPass%", "SCCreated%", "SelfCr%", "Astd%",
    "USG%", "MIN", "MPG", "+/-", "+/-/G", "STOCKS/32",
    # on-court rate stats (need game_event_lineup)
    "Guarded%", "REB%", "OREB%", "DREB%", "DSHOT%", "defFGA",
    # shot quality / location (need tap-captured shot context)
    "ShotRating", "xPPS", "xFG%", "SMOE", "RimFGA%", "MidFGA%",
    "PaintM", "PaintA", "PaintPTS", "Paint%", "PRF", "PRF/G",
    "AST2", "AST3",
    # hand-side splits, true tap-distance bands, one-tap play_type (all event/tap)
    "Dom_FGA", "Dom_FG%", "Weak_FGA", "Weak_FG%",
    "Near_FGA", "Near_FG%", "Deep_FGA", "Deep_FG%",
    "PnR_poss", "PnR_PPP", "Post_poss", "Post_PPP",
    "Iso_poss", "Iso_PPP", "Spot_poss", "Spot_PPP",
    "Transition_poss", "Transition_PPP",
    # clutch (need quarter splits from events)
    "Q4PTS", "Q4PPG", "Q4%",
    # possession-derived rates (POSS = FGA+TOV via estimate_possessions) — Paid per
    # the owner possession carve-out, even though their box inputs are Free.
    "PPP", "TOV%",
})


def box_only_table(table):
    """Strip every event-derived stat from a player_stat_table() result, leaving
    only box-derivable (Free-tier) columns. See EVENT_DERIVED_STATS."""
    return {pid: {k: v for k, v in row.items() if k not in EVENT_DERIVED_STATS}
            for pid, row in table.items()}
