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
import sqlite3
import statistics
from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.shrinkage as SHR


CATEGORIES = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]

DEFAULT_MIN_GAMES = 1   # players below this are dropped from the pool (and z-math)

# Discounted-evidence weight for a HAND-ENTERED (untracked) box-score game vs a
# fully play-by-play tracked one. Founder rule: "tracked > manual box completely
# and entirely." A boxed game feeds ONLY box-derivable leaves (shooting %s, per-
# game counting rates) — never the event leaves (SMOE, DSHOT%, USG%, rim/perim,
# passer quality, on-court %). And it counts at this fraction of a tracked game
# toward EVIDENCE (the games-equivalent that drives shrink-to-50 and the
# confidence tier), so a box-heavy player never earns full-tracked confidence.
# The per-game RATE itself blends all games at face value (18 games of shooting
# is 18 games of shooting); only the trust weighting is discounted.
MANUAL_GAME_WEIGHT = 0.35

# Base box fields a hand-entered manual_player_box row can supply (mapped to the
# engine's finalized-box keys). Everything else in a finalized box (paint_*, SC*,
# shots_*) is event-only and stays 0 for a manual game — so combined-box leaves
# built from these fields are honest, and event leaves never read manual data.
_MANUAL_BOX_KEYS = ("FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "2PM", "2PA",
                    "ORB", "DRB", "TRB", "AST", "STL", "BLK", "TOV", "PF", "PTS")


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


def sample_confidence(gp, box_heavy=False):
    """Coarse reliability flag for how much to trust a player's ratings.

    A 0-100 rating built on 2 games is mostly noise; this lets every view label
    or gray-out thin samples instead of presenting them with false precision.
    `gp` here is the EVIDENCE games-equivalent (tracked games + discounted manual
    games), so a box-heavy player already reads thinner. `box_heavy` (most of the
    evidence came from hand-entered boxes) caps the ceiling one notch and tags the
    label, since a boxed game carries no event context however many there are.
    """
    if gp >= 10:
        tier = "High"
    elif gp >= 6:
        tier = "Medium"
    elif gp >= 3:
        tier = "Low"
    else:
        tier = "Very Low"
    if box_heavy:
        # a box-heavy sample can't be "High" — no event context behind it
        tier = {"High": "Medium"}.get(tier, tier)
        return f"{tier} (box)"
    return tier


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
    """{player_id: {'name','number','team_id','team','height','wingspan',
    'weight'}} (optionally one gender). The physical columns are nullable —
    most rosters carry height at best."""
    clause = "WHERE t.gender = ?" if gender else ""
    params = (gender,) if gender else ()
    rows = query(
        f"""SELECT p.id, p.name, p.number, p.team_id,
                   p.height, p.wingspan, p.weight,
                   t.name AS team, t.class AS class
            FROM players p JOIN teams t ON t.id = p.team_id
            {clause}""",
        params,
    )
    return {r["id"]: {"name": r["name"], "number": r["number"],
                      "team_id": r["team_id"], "team": r["team"],
                      "class": r["class"], "height": r["height"],
                      "wingspan": r["wingspan"], "weight": r["weight"]}
            for r in rows}


def _manual_box_totals(gender=None, season="Current"):
    """{player_id: {**base box totals, "manual_gp": n}} from hand-entered boxes on
    UNtracked games (games.tracked=0). Tracked wins: a game tracked after its box
    was entered is excluded here (the event stream is the truth) — the same
    g.tracked=0 guard helpers/manual_box.py uses everywhere.

    Only the base counting fields a box supplies are summed (see _MANUAL_BOX_KEYS);
    paint / shot-creation / on-court fields are event-only and never faked from a
    box. `season` scopes to the active season so ratings never blend seasons.
    """
    clause = "WHERE g.tracked=0"
    params = []
    if gender:
        clause += " AND t.gender=?"
        params.append(gender)
    if season is not None:
        clause += " AND g.season=?"
        params.append(season)
    try:
        rows = query(
            f"""SELECT m.player_id pid, m.fgm, m.fga, m.tpm, m.tpa, m.ftm, m.fta,
                       m.oreb, m.dreb, m.ast, m.stl, m.blk, m.tov, m.pf
                FROM manual_player_box m
                JOIN games g ON g.id = m.game_id
                JOIN players p ON p.id = m.player_id
                JOIN teams t ON t.id = p.team_id
                {clause}""",
            tuple(params),
        )
    except sqlite3.OperationalError:
        # legacy / minimal DB without manual_player_box or games.season — the
        # manual-box merge is optional enrichment, so degrade to tracked-only.
        return {}
    out = {}
    for r in rows:
        d = out.get(r["pid"])
        if d is None:
            d = out[r["pid"]] = {k: 0 for k in _MANUAL_BOX_KEYS}
            d["manual_gp"] = 0
        fgm, fga, tpm, tpa, ftm = r["fgm"], r["fga"], r["tpm"], r["tpa"], r["ftm"]
        d["FGM"] += fgm; d["FGA"] += fga
        d["3PM"] += tpm; d["3PA"] += tpa
        d["FTM"] += ftm; d["FTA"] += r["fta"]
        d["2PM"] += fgm - tpm; d["2PA"] += fga - tpa
        d["ORB"] += r["oreb"]; d["DRB"] += r["dreb"]; d["TRB"] += r["oreb"] + r["dreb"]
        d["AST"] += r["ast"]; d["STL"] += r["stl"]; d["BLK"] += r["blk"]
        d["TOV"] += r["tov"]; d["PF"] += r["pf"]
        d["PTS"] += 2 * fgm + tpm + ftm
        d["manual_gp"] += 1
    return out


def player_profiles(game_ids=None, gender=None, min_games=DEFAULT_MIN_GAMES,
                    season="Current", include_manual=True):
    """
    Raw stat profile for every eligible player (combined GP >= min_games, gender).

    Returns {player_id: profile} where profile holds the box, games played, the
    per-game / rate inputs the ratings are built from, and meta (name/team).
    A value of None means "undefined for this player" (e.g. 3P% with no 3PA) and
    is skipped in the z-score math rather than counted as zero.

    DEPTH MODEL (founder: "tracked > manual box completely and entirely"):
      * tracked events drive every EVENT leaf (SMOE, DSHOT%, USG%, rim/perim,
        passer quality, on-court %, paint) — these read ONLY the tracked box `b`.
      * BOX-DERIVABLE leaves (shooting %s, per-game counting rates) read a COMBINED
        box `cb` = tracked box + hand-entered manual boxes on untracked games, so a
        player with 3 tracked + 15 boxed games is shot-rated on all 18. Per-game
        box leaves divide by combined GP (`cg`); event per-game leaves by tracked
        GP (`g`).
      * `eg` = tracked_gp + MANUAL_GAME_WEIGHT·manual_gp is the EVIDENCE
        games-equivalent — feeds shrink-to-50 and the confidence tier so a
        box-heavy player never earns full-tracked trust. `box_heavy` flags a
        player whose evidence is mostly manual.
    `include_manual=False` reproduces the pure tracked-only engine (cb == b).
    """
    events = S.fetch_events(game_ids)
    boxes = S.aggregate_player_boxes(game_ids, events=events)
    gp = S.games_played(game_ids)
    oc = S.oncourt_rate_stats(game_ids, events=events)
    dfg = S.defended_fg_pct(game_ids, events=events)   # DSHOT% — defense quality
    doe = S.defended_fg_over_expected(game_ids, events=events)  # shooter-adjusted
    ddr = S.individual_defensive_rating_all(game_ids, events=events)  # DRtg (lower=better)
    xfg = S.expected_fg_pct_all(game_ids, events=events)             # xFG% baseline for SMOE
    plq = S.passer_look_quality(events=events)   # xPPS created — passer look quality
    pcomp = S.passer_completion(events=events)   # FG%/xFG%/Open% on the passer's feeds
    asr = S.assist_rate(game_ids, events=events)  # AST% (on-court teammate FGM share)
    wtov = S.playmaking_weighted_tov(events=events)  # type-weighted TOs (playmaking)
    rpd, _rpd_lg = S.rim_perimeter_defense(events=events)  # rim/perimeter defense
    import helpers.charges as CHG
    # {pid: charges drawn per game}. Only players on teams that TAG charges are
    # keyed; everyone else is absent so the leaf drops out of their mean instead
    # of scoring a tagging gap as bad defense (see charges.charge_rate_map).
    chg = CHG.charge_rate_map(events)
    import helpers.fouls as FL
    ftp = FL.player_foul_ft(events=events)       # clutch FT + and-1 detail
    meta = _player_meta(gender=gender)
    manual = _manual_box_totals(gender=gender, season=season) if include_manual else {}

    # ── USAGE inputs: minutes + team possessions (event-only; tracked players) ──
    mins = S.minutes_played(game_ids)
    team_of = {r["id"]: r["team_id"]
               for r in query("SELECT id, team_id FROM players")}
    team_poss = defaultdict(float)
    team_min = defaultdict(float)
    for ppid, bb in boxes.items():
        tid = team_of.get(ppid)
        team_poss[tid] += S.estimate_possessions(bb)
        team_min[tid] += mins.get(ppid, 0.0)

    profiles = {}
    for pid, m in meta.items():
        g = gp.get(pid, 0)                       # tracked games
        mrow = manual.get(pid)
        mgp = mrow["manual_gp"] if mrow else 0   # manual (boxed) games
        cg = g + mgp                             # combined games (all)
        if cg < min_games:
            continue
        eg = g + MANUAL_GAME_WEIGHT * mgp        # evidence games-equivalent
        box_heavy = mgp > 0 and g < mgp * MANUAL_GAME_WEIGHT  # mostly boxed
        b = boxes.get(pid, S.finalize_box(S._blank_box()))    # TRACKED box (events)
        # COMBINED box: tracked base fields + manual base fields (box-derivable only)
        cb = dict(b)
        if mrow:
            for k in _MANUAL_BOX_KEYS:
                cb[k] = b.get(k, 0) + mrow.get(k, 0)
        o = oc.get(pid, {})
        df = dfg.get(pid, {})

        FGA = b["FGA"]           # tracked FGA (event leaves)
        cFGA = cb["FGA"]         # combined FGA (box leaves)
        per_g = lambda x: x / g if g else 0.0    # event per-game (tracked GP)
        cper_g = lambda x: x / cg if cg else 0.0  # box per-game (combined GP)

        # AST/TOV over the COMBINED box: undefined with no TOV AND no AST.
        if cb["TOV"]:
            ast_tov = cb["AST"] / cb["TOV"]
        elif cb["AST"]:
            ast_tov = float(cb["AST"])
        else:
            ast_tov = None

        # Playmaking-weighted TOV twins (event-tagged; TRACKED box only — a manual
        # game has no TO types, so these stay a tracked-only playmaking signal).
        wt = wtov.get(pid)
        if wt is None:
            wt = float(b["TOV"])
        if wt:
            ast_wtov = b["AST"] / wt
        elif b["AST"]:
            ast_wtov = float(b["AST"])
        else:
            ast_wtov = None

        # USG% (event-only): player possessions vs team possessions per minute.
        pmin = mins.get(pid, 0.0)
        tposs = team_poss.get(m["team_id"], 0.0)
        gmin_t = team_min.get(m["team_id"], 0.0) / 5.0
        usg = (S.usage_pct(S.estimate_possessions(b), pmin, tposs, gmin_t)
               if pmin > 0 and tposs > 0 else None)
        pc = pcomp.get(pid)

        profiles[pid] = {
            **m,
            "GP": g, "manual_gp": mgp, "combined_gp": cg,
            "evidence_gp": eg, "box_heavy": box_heavy,
            "box": b, "cbox": cb,
            # ── SHOOTING (box-derivable — read the combined box) ────
            "3PR":   _safe(cb["3PA"], cFGA) if cFGA else None,
            "3P%":   _safe(cb["3PM"], cb["3PA"]) if cb["3PA"] else None,
            "3PA/G": cper_g(cb["3PA"]),
            "TS%":   S.ts(cb) if (cFGA or cb["FTA"]) else None,
            "eFG%":  S.efg(cb) if cFGA else None,
            "FTR":   S.ftr(cb) if cFGA else None,
            # SMOE — shot-making over expected (event-only: needs the shot-quality
            # baseline from tracked events). Read the TRACKED box.
            "SMOE":  ((_safe(b["FGM"], b["FGA"]) - xfg[pid])
                      if (FGA and pid in xfg) else None),
            # ── FINISHING (event-only: paint comes from tap/zone) ───
            "Paint%": S.paint_fg_pct(b) if b["paint_FGA"] else None,
            "PaintSh/G": per_g(b["paint_FGA"]),
            "PPS":   S.pps(b) if FGA else None,          # points per shot (tracked)
            "ScEff": S.scoring_efficiency(b) if FGA else None,
            # ── OFFENSE: scoring volume / role ──────────────────────
            "PPG":   cper_g(cb["PTS"]),                  # box-derivable (combined)
            "PRF/G": per_g(S.prf(b)),                    # assist pts → tracked only
            "USG%":  usg,                                # event-only
            "MPG":   per_g(pmin) if pmin > 0 else None,  # event-only
            "PPP":   S.ppp(cb) if (cFGA or cb["TOV"]) else None,   # box (combined)
            "PPSA":  S.ppsa(cb) if cFGA else None,       # box (combined)
            "VPS":   S.vps(cb),                          # box (combined) — a ratio
            # ── DEFENSE ─────────────────────────────────────────────
            "Stocks/G": cper_g(cb["STL"] + cb["BLK"]),   # box (combined)
            "STL/G": cper_g(cb["STL"]),
            "BLK/G": cper_g(cb["BLK"]),
            "Guarded%": o.get("guarded_pct") if o.get("opp_FGA_on") else None,
            "DSHOT%": df.get("pct") if df.get("def_FGA") else None,
            # shooter-adjusted defended FG%: DSHOT% with WHO-they-guarded removed
            # (each guarded shot is scored vs the shooter's own expected make
            # rate — the defensive twin of PassFG%-vs-xPPS). Lower is better.
            "AdjDFG%": doe.get(pid, {}).get("adj_pct"),
            "DFGoe": doe.get(pid, {}).get("doe"),
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
            "PF/G":  cper_g(cb["PF"]),                   # box (combined)
            # non-strategic fouls per game: intentional clock-stop fouls
            # (helpers.late_game, counted by fouls.player_foul_ft) are a coach
            # call, not indiscipline — the OVERALL penalty leaf reads THIS.
            "nsPF/G": cper_g(max(cb["PF"]
                                 - (ftp.get(pid, {}).get("strategic") or 0), 0)),
            # charges DRAWN per game (event-only). None for a player whose team
            # doesn't tag charges at all — a genuine 0 would otherwise score a
            # tagging gap as bad defense, and the None-drops-out protection does
            # not fire on a real zero.
            "CHG/G": chg.get(pid),
            # ── PLAYMAKING ──────────────────────────────────────────
            "AST/G": cper_g(cb["AST"]),                  # box (combined)
            "AST%":  asr.get(pid),                       # event-only (on-court)
            "SC/G": per_g(b["SC"]),                      # event-only
            "SCPass/G": per_g(b["SC"] - FGA),            # event-only
            "TOV/G": cper_g(cb["TOV"]),                  # box (combined)
            "TOV%":  S.tov_pct(cb) if (cFGA or cb["TOV"]) else None,  # box (combined)
            "AST/TOV": ast_tov,                          # box (combined)
            # type-weighted twins (event-tagged; == raw when untagged) — tracked
            "pmTOV": wt,
            "AST/pmTOV": ast_wtov,
            "pmTOV%": (100 * _safe(wt, FGA + b["TOV"])
                       if (FGA or b["TOV"]) else None),
            # xPPS of the looks this player's passes create + how they resolve
            # (make-independent quality + actual FG%/open share). event-only.
            "SCPassQ": plq.get(pid),
            "PassFG%": pc["fg_pct"] if pc else None,
            "PassxFG%": pc["xfg_pct"] if pc else None,
            "PassOpen%": pc["open_pct"] if pc else None,
            # ── REBOUNDING ──────────────────────────────────────────
            "OREB/G": cper_g(cb["ORB"]),                 # box (combined)
            "DREB/G": cper_g(cb["DRB"]),
            "REB/G": cper_g(cb["TRB"]),
            "OREB%": o.get("oreb_pct") if o.get("oreb_avail") else None,  # event
            "DREB%": o.get("dreb_pct") if o.get("dreb_avail") else None,
            "REB%":  o.get("reb_pct") if o.get("reb_avail") else None,
            # ── PRODUCTION (feeds OVERALL) — combined box ───────────
            "GS/G":  cper_g(S.game_score(cb)),
            "EFF/G": cper_g(S.eff(cb)),
            "FIC/G": cper_g(S.fic(cb)),
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
# SHOOTING — perimeter + overall scoring efficiency. TS%/eFG% carry it; SMOE
# rewards finishing looks better than their difficulty warrants; 3P%/3PR reward
# range + volume-of-threes. Box-derivable leaves (all but SMOE) read the combined
# box so boxed games count.
_SHOOTING  = [("TS%", 1.5, False), ("3P%", 1.0, False), ("eFG%", 1.0, False),
              ("SMOE", 1.0, False), ("3PA/G", 0.5, False), ("FTR", 0.5, False),
              ("3PR", 0.4, False)]
# FINISHING — interior scoring. Paint FG% + how many rim/paint tries per game,
# points-per-shot, scoring efficiency, and shot-making over expected. Event-only
# (paint/PPS/SMOE need the tracked shot context), so boxed games don't inflate it.
_FINISHING = [("Paint%", 1.25, False), ("PaintSh/G", 0.75, False),
              ("PPS", 0.75, False), ("ScEff", 0.6, False), ("SMOE", 0.5, False)]
# RIM DEFENSE — protecting the basket. RimProt (league FG% − rim FG% allowed) is
# the headline; rim FG% allowed inverted is the raw twin; blocks are the event.
_RIMDEF    = [("RimProt", 1.5, False), ("RimD_pct", 0.75, True), ("BLK/G", 1.0, False)]
# PERIMETER DEFENSE — containment on the arc + ball pressure. PerimD (FG% saved on
# contested threes) + the raw twin, steals, and share of opp shots contested.
_PERIMDEF  = [("PerimD", 1.5, False), ("PerimD_pct", 0.75, True),
              ("STL/G", 1.0, False), ("Guarded%", 0.6, False)]
# DEFENSE (headline) = rim + perimeter defense components, plus the overall
# contest signal (DSHOT%), Oliver DRtg, foul discipline, and charges drawn. The
# rim/perim split is surfaced as its own sub-ratings; here it re-blends into one
# number.
# CHG/G sits HERE rather than inside _RIMDEF/_PERIMDEF on purpose: taking a
# charge is a discrete defensive event like a steal or a block, and it's a
# help-side play that belongs to neither rim protection nor on-ball containment.
# Small weight — it's a real skill but a rare event, and it must not swamp the
# per-possession signals that cover every possession.
_DEFENSE_PARTS = [("rimdef", 1.0), ("perimdef", 1.0), ("DSHOT%z", 1.0),
                  ("DRtgz", 0.75), ("PF/Gz", 0.4), ("CHG/Gz", 0.4)]
_PLAYMAKING = [("AST%", 1.25, False),   # on-court assist rate (share of teammate FGM)
               ("AST/G", 0.75, False),
               # AST/TOV + TOV% enter through their TYPE-WEIGHTED twins: a bad
               # pass counts 1.3, a lost drive 0.9, a shot-clock violation 0
               # (team turnover). Identical to the raw leaves until TOs are tagged.
               ("AST/pmTOV", 1.0, False), ("pmTOV%", 0.75, True),
               ("SC/G", 0.6, False), ("SCPass/G", 0.6, False),
               # look QUALITY a passer's feeds create (xPPS) + how they resolve:
               # actual FG% and OPEN% of the shots the passer sets up. Rewards
               # creating good, uncontested shots even when poor shooters miss.
               ("SCPassQ", 0.75, False), ("PassFG%", 0.6, False),
               ("PassOpen%", 0.5, False)]
# OFFENSIVE REBOUNDING — second chances. OREB% (on-court, event) + total/per-game.
_OREB = [("OREB%", 1.25, False), ("OREB/G", 1.0, False)]
# DEFENSIVE REBOUNDING — closing possessions. DREB% + total/per-game.
_DREB = [("DREB%", 1.25, False), ("DREB/G", 1.0, False)]
# REBOUNDING (headline) = offensive + defensive rebounding components + overall
# REB% as the tie-break. The O/D split is surfaced as its own sub-ratings.
_REBOUNDING_PARTS = [("oreb", 1.0), ("dreb", 1.0), ("REB%z", 0.6)]
# PHYSICAL — the measurables (players.height/wingspan, inches), pool-z'd like any
# leaf. Weight (mass) is deliberately excluded: no monotonic "more is better".
# Mostly a descriptive rating (founder: ~15% utility); it feeds OVERALL at a
# deliberately small weight below, and players with no measurements recorded
# simply drop the part (no penalty for an unfilled roster column).
_PHYSICAL   = [("height", 1.0, False), ("wingspan", 0.75, False)]

# How the headline ratings combine their parts (re-standardized component z, weight).
# OFFENSE folds scoring VOLUME/ROLE (PPG, USG%, MPG) and possession efficiency
# (PPP, PPSA, VPS) onto the two shooting sub-ratings, so a high-efficiency
# low-usage spot-up shooter no longer rates like a 25-PPG on-ball engine, and a
# high-usage possession-efficient scorer is rewarded. USG%/MPG are event-only
# (None for boxed-only players → they drop from the mean, not penalized).
_OFFENSE_PARTS = [("shooting", 1.0), ("finishing", 0.6),
                  ("PPG", 1.0), ("PRF/G", 0.6), ("USG%", 0.6), ("MPG", 0.3),
                  ("PPP", 0.75), ("PPSA", 0.5), ("VPS", 0.5)]
# OVERALL = the four pillars (offense-leaning) + production anchors + a length
# nudge + an OPPONENT-QUALITY bonus (oppadj) + a possession-IMPACT pillar (impact).
# `impact` is pure RAPM's z (opponent+teammate-adjusted points per 100) — a heavy,
# genuinely-adjusted signal folded at pillar weight, the "HoopWAR big in there"
# ask. It rides at 0.9 (just under offense): it measures on/off court value the box
# leaves can't see, but on a thin book it's noisy, so not the single dominant term.
# oppadj rewards genuine production against strong opposition (good-vs-good boosts,
# good-vs-bad ~0, weak production 0).
_OVERALL_PARTS = [("offense", 1.1), ("impact", 0.9), ("defense", 1.0),
                  ("playmaking", 1.0), ("rebounding", 0.8),
                  ("GS/G", 1.0), ("EFF/G", 0.6), ("FIC/G", 0.5),
                  ("physical", 0.25), ("oppadj", 0.6),
                  # explicit PENALTY leaves (2026-07-18 recal, spec §5): giveaways
                  # and non-strategic fouls subtract at the TOP level, not only
                  # buried inside playmaking/defense — "negative weights" so a
                  # stat-sheet stuffer who bleeds possessions stops rating clean.
                  # z's are sign-flipped (lower is better) before the blend.
                  # Weight 0.2 from the sweep: 0.2 rho .682 > 0.4 .680 > 0.7
                  # .668 on held-out Game Score — the penalties help small and
                  # hurt when they swamp the production signal.
                  ("TOV/Gz", 0.2), ("nsPF/Gz", 0.2)]

# Pools smaller than this skip composite re-standardization (an SD from 2-3 players
# is meaningless) and fall back to the raw weighted-mean z.
MIN_POOL_FOR_RESTD = 8

# Games-equivalent prior weight for the per-rating shrinkage toward 50 (passed to
# shrinkage.stabilize_index, which applies the SIGMOID retention curve — see
# shrinkage.DEFAULT_INDEX_POWER). 2026-07-11: sigmoid p=1.5, k=3. RETUNED
# 2026-07-18 on the deeper snapshot (39 tracked games): T4 LOGO now favors
# less shrink (pooled MAE k=1.0 3.814 < k=2 3.866 < k=3 3.908) and T2 is flat
# across k 1-3 (rho 0.679). k=2 is the adopted aggressive step: real seasons
# keep more of their edge while a 1-game cameo still only retains
# 1/(1+2^1.5) ≈ 0.26 of its distance from the anchor.
RATING_K_GAMES = 2

# ── team-prior anchor (partial pooling of thin player samples) ────────────────
# A thin-sample player is normally shrunk toward flat 50 (league average). This
# instead shrinks their OVERALL toward an anchor derived from their OWN team's
# results-only Power (team_ratings.score_ratings, 0-100, 50=avg — the SAME scale as
# the player rating, so the map is 1:1). Rationale: "good teams have good players"
# is a valid group-level (partial-pooling) prior; on a small sample the team's own
# résumé is a better guess than the grand mean. The pull is deliberately damped:
#   anchor = 50 + LAMBDA · team_confidence · (teamPower − 50)
# LAMBDA caps how far the anchor can drift from 50 (keeps a benchwarmer on an elite
# team from reading as a star); team_confidence = teamGP/(teamGP+K) so a team whose
# OWN Power rests on 2 lucky games can't over-anchor its players (honest: strong
# lift needs a real team résumé, not a fluke). LAMBDA=0 → anchor≡50 → byte-identical
# to the pre-feature engine. Symmetric: a thin player on a weak team also regresses
# slightly below 50 (set BOOST_ONLY=True for lift-only). Applies to OVERALL only.
TEAM_PRIOR_LAMBDA     = 0.5     # 0 = off; 0.35 shipped 2026-07-05 via
                                # tools/team_prior_diff.py; raised to 0.5 in the
                                # 2026-07-18 sweep (best lean-T2 rho, aggressive
                                # tie-break)
TEAM_PRIOR_K_GAMES    = 6.0     # team-confidence prior weight (games-equivalent)
TEAM_PRIOR_BOUNDS     = (35.0, 65.0)   # clamp the anchor to a sane band
TEAM_PRIOR_BOOST_ONLY = False   # True = never anchor below 50 (good-team lift only)

# ── archetype anchor (partial pooling by PLAYER TYPE — 2026-07-18 recal §7) ───
# A thin-sample player also borrows strength from players of their TYPE: k-means
# clusters on style features (helpers.archetypes' math, style-only feature list
# below — no OFFENSE/DEFENSE composites, so no circularity), and the cluster's
# mean overall-z becomes a second anchor. Blended with the team-prior anchor:
#   anchor = (1-BLEND)·team_anchor + BLEND·archetype_anchor
# Unclustered players (tiny pool, engine unavailable, cluster < MIN members)
# keep the team anchor alone; BLEND=0 turns the feature off.
ARCH_ANCHOR_BLEND  = 0.5
ARCH_MIN_CLUSTER   = 4          # smallest cluster allowed to anchor its members
_ARCH_FEATURES = ["PPG", "REB/G", "AST/G", "STL/G", "BLK/G",
                  "3PA/G", "3P%", "TS%", "USG%",
                  "OREB/G", "DREB/G", "AST/TOV", "TOV/G"]


def _archetype_anchors(profiles, overall_z):
    """{player_id: anchor} — each clustered player's anchor = its archetype's
    mean overall-z on the 0-100 scale, clamped to TEAM_PRIOR_BOUNDS. Empty on
    any failure (tiny pool, numpy/sklearn trouble) — callers fall back."""
    try:
        import helpers.archetypes as AR
        pids_m, X, _m, _s, _f = AR.build_matrix(profiles, _ARCH_FEATURES)
        n = len(pids_m)
        if n < 10:
            return {}
        k = max(1, min(AR._choose_k(X), n))
        labels, _C = AR._fit_kmeans(X, k)
    except Exception:
        return {}
    members = defaultdict(list)
    for i, p in enumerate(pids_m):
        members[int(labels[i])].append(p)
    lo, hi = TEAM_PRIOR_BOUNDS
    out = {}
    for mem in members.values():
        zs = [overall_z.get(p) for p in mem]
        zs = [z for z in zs if z is not None]
        if len(zs) < ARCH_MIN_CLUSTER:
            continue
        anchor = max(lo, min(hi, _scale100(sum(zs) / len(zs))))
        for p in mem:
            out[p] = anchor
    return out


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


# Opponent-strength memo: score_ratings covers every team results-only and is
# independent of player_ratings (no cycle), but recomputing it on every
# player_ratings call (badges/scout/lineups/cards) would tax the hot path. Memo it
# by (gender, season, results_fingerprint) so it recomputes only when a score moves.
_OPP_RATINGS_MEMO: dict = {}

# Pure-RAPM memo: the possession-impact leaf solves a ridge regression, far too
# heavy to redo on every player_ratings call. Memoized single-entry by (gender,
# game-set, events fingerprint) so it solves once per data-state and every caller
# in the process (badges/scout/cards/rankings) reuses it — OVERALL stays identical
# everywhere without paying the solve repeatedly.
_RAPM_MEMO: dict = {}


def _events_fingerprint():
    """Cheap (count, max id) signature of game_events — changes when any event is
    added/edited (including tag-only edits a score fingerprint would miss), so the
    RAPM memo invalidates exactly when the possession data moves. One aggregate."""
    try:
        r = query("SELECT COUNT(*) c, COALESCE(MAX(id),0) m FROM game_events")[0]
        return (r["c"], r["m"])
    except sqlite3.OperationalError:
        return None


def _pure_rapm_cached(game_ids, gender):
    """{player_id: RAPM} — pure (prior=None) opponent- and teammate-adjusted
    plus-minus, per 100 possessions, memoized by (gender, game-set, events fp).

    PURE (no box prior) is deliberate: it carries no re-packaging of the rating's
    own box leaves, so folding its z into OVERALL adds genuinely new adjusted-impact
    signal rather than double-counting (the concern that kept box-prior HoopWAR
    display-only). On a thin book it shrinks stars toward 0, but the z still RANKS
    them correctly, which is all the leaf needs. Returns {} when RAPM can't solve."""
    sig = tuple(sorted(game_ids)) if game_ids else None
    key = (gender, sig, _events_fingerprint())
    if key in _RAPM_MEMO:
        return _RAPM_MEMO[key]
    try:
        import helpers.rapm as RP
        solved = RP.compute_rapm(game_ids=game_ids, prior=None)
        cached = {pid: r["RAPM"] for pid, r in solved.items()
                  if r.get("RAPM") is not None}
    except Exception:
        cached = {}                        # numpy/schema missing or no solve
    # small bounded cache: hold a few data-states (F/M · None/explicit game sets)
    # so distinct surfaces don't evict each other and re-pay the ridge solve.
    if len(_RAPM_MEMO) >= 6:
        _RAPM_MEMO.pop(next(iter(_RAPM_MEMO)))
    _RAPM_MEMO[key] = cached
    return cached


def _score_ratings_cached(gender, season):
    """score_ratings(gender, season) memoized by the results fingerprint — the
    opponent-strength lookup the player opponent-adjustment rides on."""
    import helpers.team_ratings as TR
    try:
        fp = TR.results_fingerprint()
    except Exception:
        fp = None
    key = (gender, season, fp)
    cached = _OPP_RATINGS_MEMO.get(key)
    if cached is None:
        try:
            cached = TR.score_ratings(gender=gender, season=season)
        except sqlite3.OperationalError:
            cached = {}                    # legacy DB without games.season
        _OPP_RATINGS_MEMO.clear()          # keep it a single-entry cache
        _OPP_RATINGS_MEMO[key] = cached
    return cached


def _opponent_strength(profiles, gender, game_ids, season, opp_ratings=None):
    """{player_id: avg opponent team Rating faced} — the schedule-strength each
    player actually played against, from results-only team ratings (score_ratings,
    all teams, no dependency on player_ratings). Tracked games count full; boxed
    (untracked) games count at MANUAL_GAME_WEIGHT, mirroring the evidence discount.
    None for a player with no locatable opponents (drops from the adjustment)."""
    if opp_ratings is None:
        opp_ratings = _score_ratings_cached(gender, season)
    if not opp_ratings:
        return {}
    pids = set(profiles)
    # player → [(game_id, tracked?)] from the tracked lineup + manual boxes
    clause, params = S._game_filter(game_ids)
    try:
        trk = query(
            f"""SELECT DISTINCT gel.player_id pid, ge.game_id gid
                FROM game_event_lineup gel JOIN game_events ge ON ge.id = gel.event_id
                WHERE 1=1{clause}""", params)
        mparams = []
        mclause = "WHERE g.tracked=0"
        if season is not None:
            mclause += " AND g.season=?"; mparams.append(season)
        man = query(
            f"""SELECT DISTINCT m.player_id pid, m.game_id gid
                FROM manual_player_box m JOIN games g ON g.id=m.game_id {mclause}""",
            tuple(mparams))
    except sqlite3.OperationalError:
        return {}          # legacy DB without manual_player_box / games.season
    # game → (team1, team2)
    need = {r["gid"] for r in trk if r["pid"] in pids} | \
           {r["gid"] for r in man if r["pid"] in pids}
    gteams = {}
    if need:
        qmarks = ",".join("?" * len(need))
        for r in query(f"SELECT id, team1_id, team2_id FROM games WHERE id IN ({qmarks})",
                       tuple(need)):
            gteams[r["id"]] = (r["team1_id"], r["team2_id"])

    acc = defaultdict(lambda: [0.0, 0.0])   # pid -> [weighted opp-rating sum, weight]
    def _add(pid, gid, w):
        if pid not in pids:
            return
        tt = gteams.get(gid)
        if not tt:
            return
        own = profiles[pid]["team_id"]
        opp = tt[1] if tt[0] == own else tt[0]
        orr = opp_ratings.get(opp)
        if orr is None:
            return
        acc[pid][0] += orr["Rating"] * w
        acc[pid][1] += w
    for r in trk:
        _add(r["pid"], r["gid"], 1.0)
    for r in man:
        _add(r["pid"], r["gid"], MANUAL_GAME_WEIGHT)
    return {pid: s / w for pid, (s, w) in acc.items() if w > 0}


def _team_prior_anchors(profiles, gender, season, opp_ratings=None):
    """{player_id: OVERALL shrink anchor} from each player's OWN team Power.

    Partial-pooling prior: instead of regressing a thin sample toward flat 50,
    regress toward 50 + LAMBDA·team_confidence·(teamPower − 50). teamPower is the
    results-only score_ratings Power (0-100, 50=avg — identical scale to the player
    rating). team_confidence = teamGP/(teamGP+TEAM_PRIOR_K_GAMES) so a team whose
    Power rests on a tiny sample can't over-anchor its players. LAMBDA=0 → every
    anchor is exactly 50 (byte-identical to the pre-feature engine). Unknown team →
    50 (neutral). Clamped to TEAM_PRIOR_BOUNDS; optionally boost-only."""
    lam = TEAM_PRIOR_LAMBDA
    if not lam:
        return {p: 50.0 for p in profiles}          # identity fast-path
    if opp_ratings is None:
        opp_ratings = _score_ratings_cached(gender, season)
    lo, hi = TEAM_PRIOR_BOUNDS
    out = {}
    for p, prof in profiles.items():
        tr = opp_ratings.get(prof.get("team_id")) if opp_ratings else None
        if not tr or tr.get("Power") is None:
            out[p] = 50.0
            continue
        gp = tr.get("GP", 0) or 0
        conf = gp / (gp + TEAM_PRIOR_K_GAMES) if (gp + TEAM_PRIOR_K_GAMES) > 0 else 0.0
        anchor = 50.0 + lam * conf * (tr["Power"] - 50.0)
        if TEAM_PRIOR_BOOST_ONLY and anchor < 50.0:
            anchor = 50.0
        out[p] = max(lo, min(hi, anchor))
    return out


def player_ratings(game_ids=None, gender=None, min_games=DEFAULT_MIN_GAMES,
                   stabilize=True, profiles=None, season="Current",
                   opp_adjust=True, opp_ratings=None,
                   include_impact=True, rapm=None, explain=False):
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
        profiles = player_profiles(game_ids, gender=gender, min_games=min_games,
                                   season=season)
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

    # ── sub-rating components ────────────────────────────────────────────
    shooting_z   = group_z(_SHOOTING)
    finishing_z  = group_z(_FINISHING)
    rimdef_z     = group_z(_RIMDEF)
    perimdef_z   = group_z(_PERIMDEF)
    oreb_z       = group_z(_OREB)
    dreb_z       = group_z(_DREB)
    playmaking_z = group_z(_PLAYMAKING)
    physical_z   = group_z(_PHYSICAL)

    # signed raw-leaf z's the headline defense/rebounding blends fold in alongside
    # their split components (lower_better inverted where noted).
    # The contest leaf uses the SHOOTER-ADJUSTED allowed rate (AdjDFG% — DSHOT%
    # with who-they-guarded removed) so guarding elite shooters isn't punished;
    # it covers exactly the DSHOT% population, so the leaf's reach is unchanged.
    dshot_z = zcol_signed("AdjDFG%", True)
    drtg_z  = zcol_signed("DRtg", True)
    pf_z    = zcol_signed("PF/G", True)
    chg_z   = zcol_signed("CHG/G", False)   # more charges drawn = better
    rebpct_z = zcol_signed("REB%", False)

    defense_z = combine(_DEFENSE_PARTS,
                        {"rimdef": rimdef_z, "perimdef": perimdef_z,
                         "DSHOT%z": dshot_z, "DRtgz": drtg_z, "PF/Gz": pf_z,
                         "CHG/Gz": chg_z})
    rebounding_z = combine(_REBOUNDING_PARTS,
                           {"oreb": oreb_z, "dreb": dreb_z, "REB%z": rebpct_z})
    offense_z = combine(_OFFENSE_PARTS,
                        {"shooting": shooting_z, "finishing": finishing_z})

    # ── opponent-quality bonus (reward good production vs strong opposition) ──
    # oppadj = max(0, offense_z) · max(0, opp_strength_z) — a pure BONUS, never a
    # penalty (a star shouldn't be docked for a soft schedule they don't pick).
    # Both factors clamped at 0 give exactly the four cases the founder named:
    #   good-vs-good  → positive·positive = boost
    #   good-vs-bad   → positive·0        = 0  (rewarded LESS than good-vs-good)
    #   weak producer → 0·anything        = 0  (bad-vs-bad cancels, bad-on-good 0)
    # offense_z is the production signal (already re-standardized to unit SD).
    # The bonus is SHRUNK by evidence games (eg/(eg+k)) so a 1-game player who drew
    # one tough opponent can't buy a rating — only a player with a real sample AND a
    # genuinely strong slate earns it. On a thin single-team tracked pool this makes
    # the adjustment nearly inert (correct: little schedule spread to credit); it
    # grows into a real signal as league-wide tracking deepens.
    oppadj_z = {p: None for p in pids}
    if opp_adjust:
        opp_str = _opponent_strength(profiles, gender, game_ids, season, opp_ratings)
        opp_z = _zscores(opp_str)      # opponent-strength z across the pool
        for p in pids:
            oz, sz = offense_z.get(p), opp_z.get(p)
            if oz is None or sz is None:
                continue
            eg = profiles[p]["evidence_gp"]
            shrink = SHR.evidence_frac(eg, RATING_K_GAMES)
            oppadj_z[p] = max(0.0, oz) * max(0.0, sz) * shrink

    # ── possession-impact pillar (pure RAPM z — "HoopWAR big in there") ──────
    # Fold opponent+teammate-adjusted plus-minus as an OVERALL leaf. Memoized so
    # the ridge solves once per data-state and every caller reuses it. Players
    # below RAPM's min-possession gate get no value → the leaf drops from the mean
    # (thin samples aren't penalized). include_impact=False / rapm={} disables it.
    impact_z = {p: None for p in pids}
    if include_impact:
        if rapm is None:
            rapm = _pure_rapm_cached(game_ids, gender)
        if rapm:
            impact_z = _zscores({p: rapm.get(p) for p in pids})

    overall_z = combine(_OVERALL_PARTS,
                        {"offense": offense_z, "impact": impact_z,
                         "defense": defense_z, "playmaking": playmaking_z,
                         "rebounding": rebounding_z, "physical": physical_z,
                         "oppadj": oppadj_z,
                         # penalty leaves (sign-flipped: fewer TOs/fouls = better)
                         "TOV/Gz": zcol_signed("TOV/G", True),
                         "nsPF/Gz": zcol_signed("nsPF/G", True)})

    # per-player OVERALL shrink anchor: team Power prior blended with the
    # player's ARCHETYPE mean (partial pooling by team AND by type — §7)
    team_anchor = _team_prior_anchors(profiles, gender, season, opp_ratings)
    arch_anchor = (_archetype_anchors(profiles, overall_z)
                   if ARCH_ANCHOR_BLEND else {})
    anchor_of = {}
    for p in pids:
        ta = team_anchor.get(p, 50.0)
        aa = arch_anchor.get(p)
        anchor_of[p] = (ta if aa is None
                        else (1.0 - ARCH_ANCHOR_BLEND) * ta
                        + ARCH_ANCHOR_BLEND * aa)

    def _rate(z, g, anchor=50.0):
        """0-100 rating from a z-score, regressed toward `anchor` (50 = league
        average) by EVIDENCE games. OVERALL passes a team-derived anchor; every
        other rating keeps the flat-50 anchor (a box-heavy player already reads
        thinner, so it regresses harder)."""
        v = _scale100(z)
        if stabilize:
            v = SHR.stabilize_index(v, g, k_games=RATING_K_GAMES, anchor=anchor)
        return _round(v)

    out = {}
    for p in pids:
        prof = profiles[p]
        b = prof["box"]
        eg = prof["evidence_gp"]       # tracked + discounted-manual games
        out[p] = {
            "name": prof["name"], "number": prof["number"],
            "team": prof["team"], "team_id": prof["team_id"], "GP": prof["GP"],
            "OVERALL":    _rate(overall_z[p], eg, anchor=anchor_of.get(p, 50.0)),
            "OFFENSE":    _rate(offense_z[p], eg),
            "DEFENSE":    _rate(defense_z[p], eg),
            "PLAYMAKING": _rate(playmaking_z[p], eg),
            "REBOUNDING": _rate(rebounding_z[p], eg),
            "Shooting":   _rate(shooting_z[p], eg),
            "Finishing":  _rate(finishing_z[p], eg),
            # split sub-ratings (surfaced): rim/perimeter defense, off/def rebounding
            "RimDef":   (_rate(rimdef_z[p], eg) if rimdef_z.get(p) is not None else None),
            "PerimDef": (_rate(perimdef_z[p], eg) if perimdef_z.get(p) is not None else None),
            "OREBrtg":  (_rate(oreb_z[p], eg) if oreb_z.get(p) is not None else None),
            "DREBrtg":  (_rate(dreb_z[p], eg) if dreb_z.get(p) is not None else None),
            # possession impact: raw pure-RAPM (pts/100, opp+teammate adjusted) that
            # feeds the OVERALL impact pillar — None below RAPM's min-possession gate.
            "Impact": _round((rapm or {}).get(p), 2),
            # measurables rating — None when no height/wingspan recorded
            "PHYSICAL":   (_rate(physical_z[p], eg)
                           if physical_z.get(p) is not None else None),
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
        if explain:
            # spec 2.3 — the "why this number" payload, captured from the same
            # z-maps the rating was just built from (no second engine pass).
            _pillar_maps = {"offense": offense_z, "impact": impact_z,
                            "defense": defense_z, "playmaking": playmaking_z,
                            "rebounding": rebounding_z, "physical": physical_z,
                            "oppadj": oppadj_z}
            _parts = []
            for _nm, _w in _OVERALL_PARTS:
                _zm = _pillar_maps.get(_nm)
                _zv = (_zm.get(p) if _zm is not None else None)
                if _zm is None:
                    # raw/penalty leaf — recompute its z cheaply from the pool
                    if _nm == "TOV/Gz":
                        _zv = zcol_signed("TOV/G", True).get(p)
                    elif _nm == "nsPF/Gz":
                        _zv = zcol_signed("nsPF/G", True).get(p)
                    else:
                        _zv = zcol(_nm).get(p)
                _parts.append({"part": _nm, "weight": _w,
                               "z": (None if _zv is None else round(_zv, 3))})
            _raw100 = _scale100(overall_z[p])
            out[p]["_explain"] = {
                "parts": _parts,
                "shrink": {"evidence_gp": round(eg, 2),
                           "k": RATING_K_GAMES,
                           "anchor": round(anchor_of.get(p, 50.0), 1),
                           "raw": (None if _raw100 is None
                                   else round(_raw100, 1)),
                           "final": out[p]["OVERALL"]},
                "samples": {"GP": prof["GP"], "evidence_gp": round(eg, 2)},
            }
    _assign_ranks(out)
    return out


# ── depth-of-track confidence tier (spec 2.3) ─────────────────────────────────
# Two honest axes: games evidence (the same sigmoid curve the shrink uses) and
# optional-tag coverage (helpers.coverage). Combined into a 4-tier chip whose
# tooltip names the CHEAPEST next action — the PWA-header incentive mechanic,
# pushing coaches to track and tag more.
CONF_TIERS = ["Scouting look", "Solid read", "Deep book", "Full profile"]
_CONF_COLORS = ["#8b949e", "#d29922", "#58a6ff", "#3fb950"]


def confidence_tier(games, coverage_pct=None):
    """(idx 0-3, label, color, next_action) from evidence games + tag coverage.

    `coverage_pct` = the team's overall tag-coverage percent (0-100,
    coverage.team_coverage()['overall_pct']); None treats coverage as 0 —
    untagged is untagged, that's the incentive."""
    import helpers.shrinkage as _SHR
    ef = _SHR.evidence_frac(games or 0, RATING_K_GAMES)      # 0-1
    cov = (coverage_pct or 0.0) / 100.0
    score = 0.65 * ef + 0.35 * cov
    idx = 0 if score < 0.35 else 1 if score < 0.60 else 2 if score < 0.80 else 3
    if idx == 3:
        action = "the full analytics stack is live for this player"
    elif ef < 0.75:
        need = 1 if (games or 0) >= RATING_K_GAMES else RATING_K_GAMES
        action = f"track {max(need, 1)}+ more game(s) to firm this rating up"
    else:
        action = ("tag guarded-by / play type on shots to unlock the next "
                  "trust tier")
    return idx, CONF_TIERS[idx], _CONF_COLORS[idx], action


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
                      stabilize=True, season="Current", explain=False):
    """
    A single flat row per eligible player holding EVERY stat the app computes:
    meta (name/number/team/class), games, the five 0-100 ratings, raw totals,
    per-game rates, shooting splits, on-court rate stats and the advanced shot
    metrics. This is what the Players page leaderboards / Best-Five / compare /
    profile views all read from, so they never re-derive anything.

    `season` scopes the hand-entered manual-box merge + opponent adjustment (it
    must match the season the tracked `game_ids` belong to, or boxed games won't
    join). Percentages are returned 0-100 (e.g. 47.5), counting stats are integers,
    per-game stats are rounded floats. A None means the stat is undefined for
    that player (e.g. 3P% with no 3PA) and should be skipped, not treated as 0.
    """
    profiles = player_profiles(game_ids, gender=gender, min_games=min_games,
                               season=season)
    if not profiles:
        return {}
    ratings = player_ratings(game_ids, gender=gender, min_games=min_games,
                             stabilize=stabilize, profiles=profiles,
                             season=season, explain=explain)

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
            "ManualGP": prof.get("manual_gp", 0),
            "CombinedGP": prof.get("combined_gp", g),
            "Confidence": sample_confidence(prof.get("evidence_gp", g),
                                           prof.get("box_heavy", False)),
            "Rank": rt.get("Rank"),
            # ── ratings (0-100) ─────────────────────────────────────
            "OVERALL": rt.get("OVERALL"), "OFFENSE": rt.get("OFFENSE"),
            "DEFENSE": rt.get("DEFENSE"), "PLAYMAKING": rt.get("PLAYMAKING"),
            "REBOUNDING": rt.get("REBOUNDING"),
            "Shooting": rt.get("Shooting"), "Finishing": rt.get("Finishing"),
            # split sub-ratings (rim/perimeter defense, off/def rebounding)
            "RimDef": rt.get("RimDef"), "PerimDef": rt.get("PerimDef"),
            "OREBrtg": rt.get("OREBrtg"), "DREBrtg": rt.get("DREBrtg"),
            "Impact": rt.get("Impact"),
            "PHYSICAL": rt.get("PHYSICAL"),
            "_explain": rt.get("_explain"),   # spec 2.3 (None unless explain=True)
            "Height": prof.get("height"), "Wingspan": prof.get("wingspan"),
            "Weight": prof.get("weight"),
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
            # HAST = hockey assist (the pass that fed the assister on a made
            # shot). Opt-in capture (game_events.hockey_from_id) -> 0 until tagged.
            "HAST": b["HAST"], "HAST/G": pg(b["HAST"]),
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
            "AST%": _pct(prof.get("AST%")),
            # passer-quality: xPPS of looks created + how the fed shots resolve
            "PassFG%": _pct(prof.get("PassFG%")),
            "PassxFG%": _pct(prof.get("PassxFG%")),
            "PassOpen%": _pct(prof.get("PassOpen%")),
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
            # shooter-adjusted contest: DSHOT% rebased vs each guarded shooter's
            # own expected make rate (negative DFGoe = holds shooters under
            # their norm). This is the leaf the DEFENSE rating uses.
            "AdjDFG%": _pct(prof.get("AdjDFG%")),
            "DFGoe": _pct(prof.get("DFGoe")),
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
    # split sub-ratings + on-court playmaking rate + possession impact (event-derived)
    "RimDef", "PerimDef", "OREBrtg", "DREBrtg", "AST%", "Impact",
    "PassFG%", "PassxFG%", "PassOpen%",
    # shot-creation / usage / impact (lineups, minutes, possessions, events)
    "SC", "SC/G", "SCShot%", "SCPass%", "SCCreated%", "SelfCr%", "Astd%",
    "USG%", "MIN", "MPG", "+/-", "+/-/G", "STOCKS/32",
    # on-court rate stats (need game_event_lineup)
    "Guarded%", "REB%", "OREB%", "DREB%", "DSHOT%", "defFGA",
    "AdjDFG%", "DFGoe",
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
