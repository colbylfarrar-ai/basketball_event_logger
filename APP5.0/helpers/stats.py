"""
stats.py — Basketball stat engine for APP5.0.

Computes box-score and advanced stats from the `game_events` table.
Pure data layer: depends only on database.db, never on streamlit, so it can be
used from any page or a script.

Data model recap (see database/schema.sql, game_events):
    event_type          'shot' | 'free_throw' | 'foul' | 'turnover'
    primary_player_id   shooter / FT shooter / fouler / player who turned it over
    shot_result         'make' | 'miss'
    shot_type           2 | 3
    zone                'LC' | 'LW' | 'C' | 'RW' | 'RC'   (C = center / top)
    pass_from_id        player who passed into the shot   (assist if shot made)
    shot_created_by_id  screener who freed the shooter     ("SC" field)
    guarded_by_id       defender contesting the shot       (NULL = uncontested)
    rebound_by_id       player who grabbed the rebound
    blocked_by_id       player who blocked the shot
    stolen_by_id        player who got the steal

GLOSSARY SOURCES (for the canonical formulas below):
    NBA            https://www.nba.com/stats/help/glossary
    G-League       https://stats.gleague.nba.com/help/glossary/
    Bball-Ref      https://www.basketball-reference.com/about/glossary.html
    JustPlay       https://justplaysolutions.com/analytics-academy/basketball-stats-glossary/
    Mavs           https://www.nba.com/mavs/advanced-stats-glossary
    NBAstuffer     https://www.nbastuffer.com/analytics-101/
    ESPN           https://www.espn.com/editors/nba/glossary.html
    Yahoo          https://basketball.fantasysports.yahoo.com/nba/advancedstats
    JustPlay (ZD)  https://justplayss.zendesk.com/hc/en-us/articles/115001859694
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import query


# ══════════════════════════════════════════════════════════════════════════════
#  LOW-LEVEL FETCH
# ══════════════════════════════════════════════════════════════════════════════

#: SQL fragment that limits game_events (alias `ge`) to tracked games. Used as
#: the default sample everywhere — an untracked game is one that was started but
#: never fully logged (e.g. game 4, Adair vs Ketchum: 61 events, tracked=0), so
#: its partial events must never leak into "all games" aggregates.
#: Season scope: the default sample is the ACTIVE season only ('Current' sentinel)
#: so league/team event aggregates never blend seasons after a rollover. Viewing a
#: past season passes explicit game_ids instead (see helpers/seasons.py).
_TRACKED_SUBQUERY = "ge.game_id IN (SELECT id FROM games WHERE tracked=1 AND season='Current')"


def _game_filter(game_ids):
    """Return (sql_clause, params) restricting game_events (alias `ge`).

    A specific `game_ids` list limits to exactly those games. `None`/empty means
    "the whole sample" — which is every *tracked* game, NOT every game with rows
    (untracked games are partial logs and must stay out of aggregates).
    """
    if not game_ids:
        return f" AND {_TRACKED_SUBQUERY}", ()
    marks = ",".join("?" * len(game_ids))
    return f" AND ge.game_id IN ({marks})", tuple(game_ids)


def fetch_events(game_ids=None):
    """
    Pull all game_events (optionally limited to game_ids) with the shooter's and
    rebounder's team_id joined in, so offensive/defensive rebounds can be inferred.
    Returns a list of dict rows.
    """
    clause, params = _game_filter(game_ids)
    sql = f"""
        SELECT ge.*,
               sp.team_id AS shooter_team_id,
               rp.team_id AS rebounder_team_id
        FROM game_events ge
        LEFT JOIN players sp ON sp.id = ge.primary_player_id
        LEFT JOIN players rp ON rp.id = ge.rebound_by_id
        WHERE 1=1{clause}
    """
    return query(sql, params)


def _blank_box():
    return {
        "2PA": 0, "2PM": 0, "3PA": 0, "3PM": 0,
        "FTA": 0, "FTM": 0,
        "AST": 0, "AST2": 0, "AST3": 0, "ORB": 0, "DRB": 0,
        "STL": 0, "BLK": 0, "TOV": 0, "PF": 0,
        # Shots Created components
        "SC_shoot": 0, "SC_pass": 0, "SC_screen": 0,
        # screen assists: SCR_AST = screener credited on a MADE FG (the NBA
        # stat; SC_screen counts every credited screen, make or miss).
        # scr_tag_* = the shooter's shots where the SET CALL implies a screen
        # (pnr/dho/offscreen) but no screener was logged — screen-created with
        # the credit unassigned.
        "SCR_AST": 0, "scr_tag_FGA": 0, "scr_tag_FGM": 0,
        # shot-creation classification (counts of the player's OWN shot attempts)
        "shots_self": 0, "shots_pass": 0, "shots_sc": 0, "shots_both": 0,
        # paint (2PA in center zone)
        "paint_FGA": 0, "paint_FGM": 0,
    }


# Set calls whose action IS a screen (mirror of the keys in
# playtypes.NAMED_PLAY_TYPES — kept local; playtypes imports this module).
SCREEN_SETS = frozenset({"pnr", "dho", "offscreen"})


# ══════════════════════════════════════════════════════════════════════════════
#  BOX-SCORE AGGREGATION
# ══════════════════════════════════════════════════════════════════════════════

def aggregate_player_boxes(game_ids=None, events=None):
    """
    Build a per-player raw box score from game_events.

    Returns {player_id: box_dict}. Derived totals (PTS, FGA, FGM, ...) are added
    by `finalize_box`; call `player_box` for a single finalized player.
    """
    if events is None:
        events = fetch_events(game_ids)

    boxes = defaultdict(_blank_box)

    for e in events:
        etype = e["event_type"]
        pid   = e["primary_player_id"]

        if etype == "shot":
            made = e["shot_result"] == "make"
            stype = e["shot_type"]
            has_pass = e["pass_from_id"] is not None
            has_sc   = e["shot_created_by_id"] is not None

            # shooter's own attempt
            if pid is not None:
                b = boxes[pid]
                if stype == 3:
                    b["3PA"] += 1
                    if made:
                        b["3PM"] += 1
                else:  # treat anything non-3 as a 2
                    b["2PA"] += 1
                    if made:
                        b["2PM"] += 1
                    if e["zone"] == "C":
                        b["paint_FGA"] += 1
                        if made:
                            b["paint_FGM"] += 1

                # Shots Created: shooting a shot is +1
                b["SC_shoot"] += 1

                # creation classification of this attempt
                if has_pass and has_sc:
                    b["shots_both"] += 1
                elif has_pass:
                    b["shots_pass"] += 1
                elif has_sc:
                    b["shots_sc"] += 1
                else:
                    b["shots_self"] += 1

                # screen-created by TAG, credit unassigned: the set call is a
                # screen action but no screener was logged on the shot
                if not has_sc and (e.get("play_type") or "") in SCREEN_SETS:
                    b["scr_tag_FGA"] += 1
                    if made:
                        b["scr_tag_FGM"] += 1

            # passer: +1 Shot Created; assist only if the shot went in
            if has_pass:
                pb = boxes[e["pass_from_id"]]
                pb["SC_pass"] += 1
                if made:
                    pb["AST"] += 1
                    if stype == 3:
                        pb["AST3"] += 1
                    else:
                        pb["AST2"] += 1

            # screener (SC field): +1 Shot Created; a MAKE is a screen assist
            if has_sc:
                sb = boxes[e["shot_created_by_id"]]
                sb["SC_screen"] += 1
                if made:
                    sb["SCR_AST"] += 1

            # block credited to defender
            if e["blocked_by_id"] is not None:
                boxes[e["blocked_by_id"]]["BLK"] += 1

        elif etype == "free_throw":
            if pid is not None:
                b = boxes[pid]
                b["FTA"] += 1
                if e["shot_result"] == "make":
                    b["FTM"] += 1

        elif etype == "turnover":
            if pid is not None:
                boxes[pid]["TOV"] += 1
            if e["stolen_by_id"] is not None:
                boxes[e["stolen_by_id"]]["STL"] += 1

        elif etype == "foul":
            # primary_player_id = player who was fouled; the foul (PF) is charged
            # to secondary_player_id, the player who committed it.
            fouler = e["secondary_player_id"]
            if fouler is not None:
                boxes[fouler]["PF"] += 1

        # rebounds can occur on any missed shot/FT — classify off vs def
        if e["rebound_by_id"] is not None:
            rb = boxes[e["rebound_by_id"]]
            shooter_team   = e["shooter_team_id"]
            rebounder_team = e["rebounder_team_id"]
            if shooter_team is not None and rebounder_team == shooter_team:
                rb["ORB"] += 1
            else:
                rb["DRB"] += 1

    return {pid: finalize_box(b) for pid, b in boxes.items()}


def finalize_box(b):
    """Add derived totals (FGA/FGM/PTS/TRB/SC) to a raw box dict and return it."""
    b = dict(b)
    b["FGA"] = b["2PA"] + b["3PA"]
    b["FGM"] = b["2PM"] + b["3PM"]
    b["3PA"] = b["3PA"]
    b["TRB"] = b["ORB"] + b["DRB"]
    b["PTS"] = b["2PM"] * 2 + b["3PM"] * 3 + b["FTM"]
    b["SC"]  = b["SC_shoot"] + b["SC_pass"] + b["SC_screen"]
    b["stocks"]    = b["STL"] + b["BLK"]
    b["paint_PTS"] = b["paint_FGM"] * 2
    return b


def player_box(player_id, game_ids=None):
    """Finalized box score for a single player (zeros if no events)."""
    boxes = aggregate_player_boxes(game_ids)
    return boxes.get(player_id, finalize_box(_blank_box()))


# ══════════════════════════════════════════════════════════════════════════════
#  FULLY-DEFINED METRICS  (pure functions of a finalized box dict)
# ══════════════════════════════════════════════════════════════════════════════

def _safe(num, den):
    return num / den if den else 0.0


def scale100(z):
    """Map a z-score to a 0-100 index (50 = league average, +10 per SD), clamped."""
    return max(0.0, min(100.0, 50 + 10 * z))


def percentile(value, pool, higher_better=True):
    """Percentile (0-100) of `value` within `pool` (a list of numbers)."""
    vals = [v for v in pool if v is not None]
    if not vals or value is None:
        return None
    below = sum(1 for v in vals if (v < value) == higher_better)
    return round(100 * below / len(vals), 0)


# ── player measurables formatting (single source for every printable sheet) ─────
def fmt_height(inches):
    """Inches → feet-inches string (74 → 6'2\"); None / 0 / non-numeric → None."""
    try:
        n = int(round(float(inches)))
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    ft, inch = divmod(n, 12)
    return f"{ft}'{inch}\""


def fmt_hand(handedness):
    """'left' → 'LH'; anything else (incl None, the default 'right') → 'RH'."""
    return "LH" if handedness == "left" else "RH"


def fmt_measurables(row, include_hand=True):
    """Compact one-line measurables for a player row (dict OR sqlite Row) carrying
    height / weight / wingspan / handedness. Handedness ALWAYS shows (RH/LH) when
    include_hand — coaches want it on every sheet, so the line is never empty for a
    known player even with no height/weight/wingspan on file. None only when row is
    falsy."""
    if not row:
        return None

    def _get(k):
        try:
            return row[k]
        except (KeyError, IndexError, TypeError):
            return None

    ht = fmt_height(_get("height"))
    wt = _get("weight")
    wt = f"{wt:g} lb" if wt else None
    ws = fmt_height(_get("wingspan"))
    parts = [p for p in (ht, wt, (f"{ws} wing" if ws else None)) if p]
    if include_hand:
        parts.append(fmt_hand(_get("handedness")))
    return " · ".join(parts) if parts else None


# ── game-clock helpers (regulation 8:00 quarters, 4:00 OT) ──────────────────────
def clock_secs(t):
    """Seconds shown on the game clock for an 'M:S' string. Tolerant of bad input."""
    try:
        m, s = (str(t).split(":") + ["0"])[:2]
        return int(m) * 60 + int(s)
    except (ValueError, TypeError):
        return 0


def q_len(q):
    """Length in seconds of period q (480 in regulation, 240 in OT)."""
    return 480 if q <= 4 else 240


def q_base(q):
    """Seconds elapsed before period q tips off."""
    return 480 * (q - 1) if q <= 4 else 480 * 4 + 240 * (q - 5)


def elapsed(q, t):
    """Seconds since tip-off for clock time t in period q (chronological sort key)."""
    return q_base(q) + (q_len(q) - clock_secs(t))


def usage_pct(p_poss, player_min, team_poss, team_min_over5):
    """USG% core formula: 100 * pPoss * (TmMP/5) / (playerMin * TmPoss).

    A possession is a shot or a turnover (FTs and fouls don't count). `team_min_over5`
    is the team's clock-minutes (sum of its players' on-floor minutes / 5). Returns
    None when any denominator term is non-positive.
    """
    if player_min <= 0 or team_poss <= 0 or team_min_over5 <= 0:
        return None
    return 100 * _safe(p_poss * team_min_over5, player_min * team_poss)


def shot_efficiency(b):
    """(PTS - FT) / ((2PA * 2) + (3PA * 3)).  FG points scored vs. max FG points possible."""
    return _safe(b["PTS"] - b["FTM"], b["2PA"] * 2 + b["3PA"] * 3)


def ppsa(b):
    """Points Per Shot Attempt = PTS / FGA.  (Set true_shooting=True for TS-style denom.)"""
    return _safe(b["PTS"], b["FGA"])


def efg(b):
    """Effective FG% = (FGM + 0.5 * 3PM) / FGA."""
    return _safe(b["FGM"] + 0.5 * b["3PM"], b["FGA"])


def ts(b):
    """True Shooting % = PTS / (2 * (FGA + 0.44 * FTA))."""
    return _safe(b["PTS"], 2 * (b["FGA"] + 0.44 * b["FTA"]))


def scoring_efficiency(b):
    """ScEff — FG points captured vs the shot-value ceiling if every attempt fell:
    (2·2PM + 3·3PM) / (2·2PA + 3·3PA). A point-weighted make rate that rewards
    converting the harder, higher-value shots (free throws excluded). This is the
    canonical name for what the profile/team code has long called "SCE" — an alias
    of shot_efficiency so there's one implementation. 0-1, 0 with no FGA."""
    return shot_efficiency(b)


def paint_fga(b):
    """Paint FGA = 2-point attempts taken from the Center zone."""
    return b["paint_FGA"]


def paint_fg_pct(b):
    """Paint FG% = paint makes / paint attempts (2PA in Center zone)."""
    return _safe(b["paint_FGM"], b["paint_FGA"])


def game_score(b):
    """
    Hollinger Game Score (Basketball-Reference):
      PTS + 0.4*FGM - 0.7*FGA - 0.4*(FTA-FTM) + 0.7*ORB + 0.3*DRB
      + STL + 0.7*AST + 0.7*BLK - 0.4*PF - TOV
    """
    return (
        b["PTS"]
        + 0.4 * b["FGM"]
        - 0.7 * b["FGA"]
        - 0.4 * (b["FTA"] - b["FTM"])
        + 0.7 * b["ORB"]
        + 0.3 * b["DRB"]
        + b["STL"]
        + 0.7 * b["AST"]
        + 0.7 * b["BLK"]
        - 0.4 * b["PF"]
        - b["TOV"]
    )


def per(b):
    """
    PER proxy. True Hollinger PER is league-normalised to 15.0 and needs
    league-wide totals + pace, which a single-program DB lacks — so per your
    call we use Game Score as the stand-in. Identical to game_score().
    """
    return game_score(b)


def shot_breakdown(b):
    """
    Counts of the player's own shot attempts by how the shot was created:
      self  — no pass, no screen
      pass  — pass_from filled
      sc    — screen (SC) filled
      both  — pass AND screen filled
    """
    return {
        "self": b["shots_self"],
        "pass": b["shots_pass"],
        "sc":   b["shots_sc"],
        "both": b["shots_both"],
    }


def shot_breakdown_pct(b):
    """shot_breakdown as shares of the player's own attempts (self/pass/sc/both %)."""
    fga = b["FGA"]
    return {k: _safe(v, fga) for k, v in shot_breakdown(b).items()}


# ── shooting percentages ────────────────────────────────────────────────────────

def fg_pct(b):
    return _safe(b["FGM"], b["FGA"])

def fg2_pct(b):
    return _safe(b["2PM"], b["2PA"])

def fg3_pct(b):
    return _safe(b["3PM"], b["3PA"])

def ft_pct(b):
    return _safe(b["FTM"], b["FTA"])


# ── shot-mix rates ──────────────────────────────────────────────────────────────

def three_par(b):
    """3-Point Attempt Rate = 3PA / FGA (share of FGAs from three)."""
    return _safe(b["3PA"], b["FGA"])

def ftr(b):
    """Free Throw Rate = FTA / FGA (how often they get to the line per shot)."""
    return _safe(b["FTA"], b["FGA"])


# ── points-per-shot family ──────────────────────────────────────────────────────
#  PPS  = field-goal points per FG attempt (excludes free throws) — pure shooting.
#  PPSA = ALL points per FG attempt (includes FT points) — see ppsa() above.

def pps(b):
    """Points Per Shot = (2PM*2 + 3PM*3) / FGA.  FG scoring only, no free throws."""
    return _safe(b["2PM"] * 2 + b["3PM"] * 3, b["FGA"])


# ── simple counting derivations ─────────────────────────────────────────────────

def stocks(b):
    """Steals + blocks."""
    return b["STL"] + b["BLK"]

def paint_points(b):
    """Points scored in the paint = 2 * paint makes (2PM from the Center zone)."""
    return b["paint_FGM"] * 2


# ── composite box metrics ───────────────────────────────────────────────────────

def eff(b):
    """
    NBA Efficiency (EFF):
      (PTS + TRB + AST + STL + BLK) - ((FGA-FGM) + (FTA-FTM) + TOV)
    """
    return (
        b["PTS"] + b["TRB"] + b["AST"] + b["STL"] + b["BLK"]
        - (b["FGA"] - b["FGM"]) - (b["FTA"] - b["FTM"]) - b["TOV"]
    )


def fic(b):
    """
    Floor Impact Counter (RealGM / NBAstuffer):
      PTS + 0.75*ORB + 0.25*DRB + AST + STL + 0.75*BLK
      - 0.75*FGA - 0.375*FTA - TOV - 0.5*PF
    """
    return (
        b["PTS"]
        + 0.75 * b["ORB"] + 0.25 * b["DRB"]
        + b["AST"] + b["STL"] + 0.75 * b["BLK"]
        - 0.75 * b["FGA"] - 0.375 * b["FTA"] - b["TOV"] - 0.5 * b["PF"]
    )


def vps(b):
    """
    Hudl Value Point System — a production-to-mistakes ratio:
      (PTS + REB + 2·(AST + STL + BLK)) / (FT miss + 2·(FG miss + PF + TOV))
    Returns None when the denominator is 0 (no misses, fouls or turnovers).
    """
    reb = b.get("TRB", b["ORB"] + b["DRB"])
    num = b["PTS"] + reb + 2 * (b["AST"] + b["STL"] + b["BLK"])
    ft_miss = b["FTA"] - b["FTM"]
    fg_miss = b["FGA"] - b["FGM"]
    den = ft_miss + 2 * (fg_miss + b["PF"] + b["TOV"])
    return num / den if den > 0 else None


def prf(b):
    """
    Points Responsible For = own points + points created by assists
      = PTS + 2*(2-pt assists) + 3*(3-pt assists).
    """
    return b["PTS"] + 2 * b["AST2"] + 3 * b["AST3"]


def tov_pct(b):
    """Turnover % = 100 * TOV / (FGA + TOV).
    A possession is a shot or a turnover; free throws and fouls don't count."""
    return 100 * _safe(b["TOV"], player_possessions(b))


# ── Shots-Created composition (how a player earns their SC) ──────────────────────

def sc_composition(b):
    """
    Share of a player's Shots Created that come from each action:
      shoot%  SC_shoot / SC   (taking the shot)
      pass%   SC_pass  / SC   (passing into a shot)
      sc%     SC_screen/ SC   (screening someone open)
    """
    sc = b["SC"]
    return {
        "shoot": _safe(b["SC_shoot"], sc),
        "pass":  _safe(b["SC_pass"], sc),
        "sc":    _safe(b["SC_screen"], sc),
    }


# ── simple per-possession family (player-level) ─────────────────────────────────
#  Possession base = FGA + TOV (a possession is a shot or a turnover; free throws
#  and fouls never count). Same definition as estimate_possessions, applied to a
#  single player's box.

def player_possessions(b):
    """Possessions = FGA + TOV (shots + turnovers; FTs/fouls don't count)."""
    return estimate_possessions(b)

def ppp(b):
    """Points Per Possession = PTS / usage possessions."""
    return _safe(b["PTS"], player_possessions(b))

def app(b):
    """Assists Per Possession = AST / usage possessions."""
    return _safe(b["AST"], player_possessions(b))


# ══════════════════════════════════════════════════════════════════════════════
#  DATA-DRIVEN ESTIMATORS  (need the whole sample, not just one box)
# ══════════════════════════════════════════════════════════════════════════════

def _creation_bucket(has_pass, has_sc):
    if has_pass and has_sc:
        return "both"
    if has_pass:
        return "pass"
    if has_sc:
        return "sc"
    return "self"


def creation_fg_rates(game_ids=None, events=None):
    """
    Empirical FG% for each creation bucket (self / pass / sc / both), computed
    across every shot in the sample. This is the baseline xFG% draws from.
    Returns {bucket: {"FGA":n, "FGM":n, "pct":float}}.
    """
    if events is None:
        events = fetch_events(game_ids)
    agg = {k: {"FGA": 0, "FGM": 0} for k in ("self", "pass", "sc", "both")}
    for e in events:
        if e["event_type"] != "shot":
            continue
        bucket = _creation_bucket(e["pass_from_id"] is not None,
                                  e["shot_created_by_id"] is not None)
        agg[bucket]["FGA"] += 1
        if e["shot_result"] == "make":
            agg[bucket]["FGM"] += 1
    for k, v in agg.items():
        v["pct"] = _safe(v["FGM"], v["FGA"])
    return agg


def expected_fg_pct(player_id, game_ids=None, events=None, rates=None):
    """
    xFG% — expected FG% given the player's *mix* of shot-creation contexts.
    For each of the player's attempts, credit the sample-wide FG% for that
    bucket (self/pass/sc/both), then average. Compare a player's real FG% to
    this to see if they over/under-perform the difficulty of shots they take.
    """
    if events is None:
        events = fetch_events(game_ids)
    if rates is None:
        rates = creation_fg_rates(events=events)

    exp_makes = 0.0
    attempts = 0
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] != player_id:
            continue
        bucket = _creation_bucket(e["pass_from_id"] is not None,
                                  e["shot_created_by_id"] is not None)
        exp_makes += rates[bucket]["pct"]
        attempts += 1
    return _safe(exp_makes, attempts)


def expected_fg_pct_all(game_ids=None, events=None, rates=None):
    """
    {player_id: xFG%} for every shooter in the sample, in ONE pass over events
    (O(events) instead of O(players·events) from calling expected_fg_pct per
    player). xFG% = the player's shot-creation mix scored at the sample-wide FG%
    for each bucket; compare to real FG% for shot-making-over-expected (SMOE).
    """
    if events is None:
        events = fetch_events(game_ids)
    if rates is None:
        rates = creation_fg_rates(events=events)
    exp = defaultdict(float)
    att = defaultdict(int)
    for e in events:
        if e["event_type"] != "shot":
            continue
        pid = e["primary_player_id"]
        bucket = _creation_bucket(e["pass_from_id"] is not None,
                                  e["shot_created_by_id"] is not None)
        exp[pid] += rates[bucket]["pct"]
        att[pid] += 1
    return {pid: _safe(exp[pid], att[pid]) for pid in att}


def shot_quality_rates(game_ids=None, events=None):
    """
    Empirical make-rate for each (zone, creation-bucket, guarded?) combination,
    across the whole sample. This is the engine behind Shot Rating / expected
    points per shot — it scores a shot purely by where it came from, how it was
    created, and whether it was contested.
    Returns {(zone, bucket, guarded_bool): {"FGA","FGM","pct"}}.
    """
    if events is None:
        events = fetch_events(game_ids)
    agg = defaultdict(lambda: {"FGA": 0, "FGM": 0})
    for e in events:
        if e["event_type"] != "shot":
            continue
        key = (
            e["zone"],
            _creation_bucket(e["pass_from_id"] is not None,
                             e["shot_created_by_id"] is not None),
            e["guarded_by_id"] is not None,
        )
        agg[key]["FGA"] += 1
        if e["shot_result"] == "make":
            agg[key]["FGM"] += 1
    out = {}
    for k, v in agg.items():
        out[k] = {"FGA": v["FGA"], "FGM": v["FGM"], "pct": _safe(v["FGM"], v["FGA"])}
    return out


def expected_points_per_shot(player_id, game_ids=None, events=None, rates=None):
    """
    xPPS — for each of the player's attempts, expected points =
        sample make-rate[(zone, creation, guarded)] * shot_value (2 or 3).
    Returns the average expected points per attempt. This is a shot-QUALITY
    metric (how many points the player's shots are worth on average). It is
    separate from shot_rating(), which measures shot DIFFICULTY.
    """
    if events is None:
        events = fetch_events(game_ids)
    if rates is None:
        rates = shot_quality_rates(events=events)

    total_xpts = 0.0
    attempts = 0
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] != player_id:
            continue
        key = (
            e["zone"],
            _creation_bucket(e["pass_from_id"] is not None,
                             e["shot_created_by_id"] is not None),
            e["guarded_by_id"] is not None,
        )
        value = 3 if e["shot_type"] == 3 else 2
        total_xpts += rates.get(key, {}).get("pct", 0.0) * value
        attempts += 1
    return _safe(total_xpts, attempts)


def passer_look_quality(game_ids=None, events=None, rates=None, min_feeds=8):
    """{passer_id: xPPS_created} — the expected value of the LOOKS a passer sets up.

    Each shot the passer fed (pass_from_id) is scored by the league make-rate for
    its (zone, creation-bucket, contested?) — so it measures the QUALITY of the look
    created, independent of whether the shooter made it. A playmaking-quality signal
    the PLAYMAKING rating folds in (a passer who creates good looks rates as a good
    playmaker even when poor shooters miss them). Passers below ``min_feeds``
    assisted attempts are omitted (too noisy to score).
    """
    if events is None:
        events = fetch_events(game_ids)
    if rates is None:
        rates = shot_quality_rates(events=events)
    agg = defaultdict(lambda: {"feeds": 0, "xpts": 0.0})
    for e in events:
        if e["event_type"] != "shot":
            continue
        passer = e.get("pass_from_id")
        if passer is None:
            continue
        key = (e["zone"],
               _creation_bucket(True, e["shot_created_by_id"] is not None),
               e["guarded_by_id"] is not None)
        val = 3 if e["shot_type"] == 3 else 2
        c = agg[passer]
        c["feeds"] += 1
        c["xpts"] += rates.get(key, {}).get("pct", 0.0) * val
    return {pid: c["xpts"] / c["feeds"]
            for pid, c in agg.items() if c["feeds"] >= min_feeds}


# ══════════════════════════════════════════════════════════════════════════════
#  SHOT RATING  (difficulty: 50 = sample-average shot, 100 = contested self-3)
# ══════════════════════════════════════════════════════════════════════════════
#
#  Rates shots by DIFFICULTY, off the three factors you named: where the shot was
#  from (zone + 2/3), how it was created (self/pass/SC/both), and whether it was
#  guarded. Difficulty of a shot = 1 - (sample make-rate for that bucket): the
#  less often a kind of shot goes in, the "harder" it is. The 0-100 scale is then
#  anchored to your two points:
#       50  = the average shot in the sample
#       100 = a contested, self-created 3 (your defined hardest shot)
#  A player's Shot Rating = the average rating of the shots they actually took, so
#  someone who lives on tough self-created jumpers rates high; someone fed easy
#  assisted layups rates low. (This is about shot SELECTION difficulty, not makes.)

_MIN_BUCKET_FGA = 5  # below this, fall back to a coarser bucket for a stable rate


def shot_difficulty_rates(game_ids=None, events=None):
    """
    Sample make-rates at two granularities, used to score shot difficulty:
      fine   = (zone, shot_type, creation, guarded)
      coarse = (shot_type, creation, guarded)   — fallback when fine is too thin
    Also returns the overall make-rate and the contested-self-3 make-rate anchor.
    """
    if events is None:
        events = fetch_events(game_ids)

    fine   = defaultdict(lambda: {"FGA": 0, "FGM": 0})
    coarse = defaultdict(lambda: {"FGA": 0, "FGM": 0})
    tot_fga = tot_fgm = 0
    anchor_fga = anchor_fgm = 0  # contested self-created 3s

    for e in events:
        if e["event_type"] != "shot":
            continue
        creation = _creation_bucket(e["pass_from_id"] is not None,
                                    e["shot_created_by_id"] is not None)
        guarded  = e["guarded_by_id"] is not None
        stype    = 3 if e["shot_type"] == 3 else 2
        made     = e["shot_result"] == "make"

        fkey = (e["zone"], stype, creation, guarded)
        ckey = (stype, creation, guarded)
        fine[fkey]["FGA"]   += 1
        coarse[ckey]["FGA"] += 1
        tot_fga += 1
        if made:
            fine[fkey]["FGM"]   += 1
            coarse[ckey]["FGM"] += 1
            tot_fgm += 1

        if stype == 3 and creation == "self" and guarded:
            anchor_fga += 1
            if made:
                anchor_fgm += 1

    return {
        "fine": fine,
        "coarse": coarse,
        "overall_pct": _safe(tot_fgm, tot_fga),
        "anchor_pct": _safe(anchor_fgm, anchor_fga),
        "anchor_fga": anchor_fga,
    }


def _bucket_make_rate(e, rates):
    """Make-rate for one shot event, fine bucket with coarse fallback."""
    creation = _creation_bucket(e["pass_from_id"] is not None,
                                e["shot_created_by_id"] is not None)
    guarded  = e["guarded_by_id"] is not None
    stype    = 3 if e["shot_type"] == 3 else 2
    fkey = (e["zone"], stype, creation, guarded)
    f = rates["fine"].get(fkey)
    if f and f["FGA"] >= _MIN_BUCKET_FGA:
        return _safe(f["FGM"], f["FGA"])
    c = rates["coarse"].get((stype, creation, guarded))
    if c and c["FGA"]:
        return _safe(c["FGM"], c["FGA"])
    return rates["overall_pct"]


def shot_rating(player_id, game_ids=None, events=None, rates=None):
    """
    Player Shot Rating (difficulty). 50 = average-difficulty shot,
    100 = a contested self-created 3. Higher = the player takes harder shots.
    Returns None if there's no sample or the difficulty scale is degenerate.
    """
    if events is None:
        events = fetch_events(game_ids)
    if rates is None:
        rates = shot_difficulty_rates(events=events)

    d_avg = 1 - rates["overall_pct"]           # average shot difficulty
    d_100 = 1 - rates["anchor_pct"]            # contested self-3 difficulty
    span  = d_100 - d_avg
    if span <= 0 or rates["anchor_fga"] == 0:
        return None  # can't anchor the scale (no contested self-3s, or it's not the hardest)

    total = 0.0
    n = 0
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] != player_id:
            continue
        d = 1 - _bucket_make_rate(e, rates)
        r = 50 + 50 * (d - d_avg) / span
        total += max(0.0, min(100.0, r))
        n += 1
    return _safe(total, n) if n else None


# ══════════════════════════════════════════════════════════════════════════════
#  ON-COURT RATE STATS  (need who-was-on-the-floor, from game_event_lineup)
# ══════════════════════════════════════════════════════════════════════════════
#
#  These are the "% of X while on the court" stats: a player's share of the
#  defensive/rebounding action that happened during the events they were on the
#  floor for. They need game_event_lineup (who was on for each event), so they
#  can't be derived from a box dict alone.

def games_played(game_ids=None):
    """{player_id: # distinct games they appear on the floor for}."""
    clause, params = _game_filter(game_ids)
    rows = query(
        f"""SELECT gel.player_id pid, COUNT(DISTINCT ge.game_id) g
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            WHERE 1=1{clause}
            GROUP BY gel.player_id""",
        params,
    )
    return {r["pid"]: r["g"] for r in rows}


def games_started(game_ids=None, events=None):
    """{player_id: # distinct games they were in the STARTING five}.

    Starters are INFERRED as the five on the floor at each game's first event
    (no starter flag is tracked — see helpers.gameflow.infer_starters), so this
    is an inference. Pair with games_played() to get a games-started rate (GS%):
    GS% = 100 * games_started / games_played. `events` may be passed to reuse an
    already-fetched event stream (gameflow is imported lazily to avoid a cycle)."""
    from helpers.gameflow import infer_starters
    if events is None:
        events = fetch_events(game_ids)
    by_game = defaultdict(list)
    for e in events:
        by_game[e["game_id"]].append(e)
    started = defaultdict(int)
    for g_events in by_game.values():
        for _team, pids in infer_starters(g_events).items():
            for pid in pids:
                started[pid] += 1
    return dict(started)


def oncourt_rate_stats(game_ids=None, events=None):
    """
    Per-player on-court rate stats, in one pass over the events + lineups:

      guarded_FGA   opponent shots the player guarded (guarded_by_id == player)
      opp_FGA_on    opponent shots taken while the player was on the floor
      guarded_pct   guarded_FGA / opp_FGA_on   (share of opp shots they contested)

      oreb_made / oreb_avail   off. rebounds grabbed / available while on floor
      dreb_made / dreb_avail   def. rebounds grabbed / available while on floor
      reb_made  / reb_avail    all rebounds grabbed / available while on floor
      oreb_pct, dreb_pct, reb_pct   the corresponding shares

    "Available" = every rebound that occurred while the player was on the floor,
    split by whose missed shot it came off (the player's team -> offensive
    opportunity, the opponent -> defensive). This is the on-court version of the
    standard ORB%/DRB%/TRB% (player boards / boards available to them).
    """
    if events is None:
        events = fetch_events(game_ids)

    # who was on the floor for each event: {event_id: [(player_id, team_id), ...]}
    clause, params = _game_filter(game_ids)
    lin_rows = query(
        f"""SELECT gel.event_id eid, gel.player_id pid, gel.team_id tid
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            WHERE 1=1{clause}""",
        params,
    )
    on_floor = defaultdict(list)
    for r in lin_rows:
        on_floor[r["eid"]].append((r["pid"], r["tid"]))

    stat = defaultdict(lambda: {
        "guarded_FGA": 0, "opp_FGA_on": 0,
        "oreb_made": 0, "oreb_avail": 0,
        "dreb_made": 0, "dreb_avail": 0,
    })

    for e in events:
        floor = on_floor.get(e["id"])
        if not floor:
            continue
        shooter_team = e["shooter_team_id"]

        # defensive contest: every opponent shot the player was on the floor for
        if e["event_type"] == "shot" and shooter_team is not None:
            guard = e["guarded_by_id"]
            for pid, tid in floor:
                if tid != shooter_team:           # pid is on defense for this shot
                    s = stat[pid]
                    s["opp_FGA_on"] += 1
                    if guard == pid:
                        s["guarded_FGA"] += 1

        # rebound opportunity: any event that produced a rebound
        reb = e["rebound_by_id"]
        if reb is not None and shooter_team is not None:
            for pid, tid in floor:
                s = stat[pid]
                if tid == shooter_team:           # pid's team missed -> off. board chance
                    s["oreb_avail"] += 1
                    if reb == pid:
                        s["oreb_made"] += 1
                else:                             # opponent missed -> def. board chance
                    s["dreb_avail"] += 1
                    if reb == pid:
                        s["dreb_made"] += 1

    out = {}
    for pid, s in stat.items():
        reb_made = s["oreb_made"] + s["dreb_made"]
        reb_avail = s["oreb_avail"] + s["dreb_avail"]
        out[pid] = {
            **s,
            "reb_made": reb_made, "reb_avail": reb_avail,
            "guarded_pct": _safe(s["guarded_FGA"], s["opp_FGA_on"]),
            "oreb_pct": _safe(s["oreb_made"], s["oreb_avail"]),
            "dreb_pct": _safe(s["dreb_made"], s["dreb_avail"]),
            "reb_pct":  _safe(reb_made, reb_avail),
        }
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  MINUTES, +/-, USAGE, DEFENDED FG%, QUARTER SPLITS, PER-32
# ══════════════════════════════════════════════════════════════════════════════
#
#  Minutes come from game_events.possession_secs summed over the events a player
#  was on the floor for (via game_event_lineup). Total game time ≈ the sum of all
#  possession_secs, which lands near 32 min/game here (HS), so "per-32" == roughly
#  "per full game". Note ~16% of events have possession_secs = 0 (untimed), so
#  minutes are a slight undercount — directional, like the other lineup stats.

def minutes_played(game_ids=None):
    """{player_id: minutes on the floor} from possession_secs over on-court events."""
    clause, params = _game_filter(game_ids)
    rows = query(
        f"""SELECT gel.player_id pid, SUM(ge.possession_secs) / 60.0 mins
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            WHERE 1=1{clause}
            GROUP BY gel.player_id""",
        params,
    )
    return {r["pid"]: (r["mins"] or 0.0) for r in rows}


def plus_minus(game_ids=None):
    """{player_id: cumulative +/-} from game_lineup_players.plus_minus."""
    if game_ids:
        marks = ",".join("?" * len(game_ids))
        clause, params = f" WHERE game_id IN ({marks})", tuple(game_ids)
    else:
        # default sample = tracked games only, ACTIVE season (mirror _game_filter
        # + _TRACKED_SUBQUERY; this table has no `ge` alias so it can't reuse them)
        clause = " WHERE game_id IN (SELECT id FROM games WHERE tracked=1 AND season='Current')"
        params = ()
    rows = query(
        f"SELECT player_id pid, SUM(plus_minus) pm FROM game_lineup_players{clause} GROUP BY player_id",
        params,
    )
    return {r["pid"]: (r["pm"] or 0) for r in rows}


def per_minutes(value, minutes, base=32):
    """Normalise a counting total to a per-`base`-minutes rate (default per-32)."""
    return _safe(value * base, minutes)


def defended_fg_pct(game_ids=None, events=None):
    """
    DSHOT% — Defended Field Goal %: the FG% a player allows as the contesting
    defender (guarded_by_id == player). Lower is better.
    Returns {player_id: {"def_FGA","def_FGM","pct"}}.
    (For 'share of opponent shots contested', see oncourt_rate_stats -> guarded_pct.)
    """
    if events is None:
        events = fetch_events(game_ids)
    agg = defaultdict(lambda: {"def_FGA": 0, "def_FGM": 0})
    for e in events:
        if e["event_type"] != "shot":
            continue
        g = e["guarded_by_id"]
        if g is None:
            continue
        agg[g]["def_FGA"] += 1
        if e["shot_result"] == "make":
            agg[g]["def_FGM"] += 1
    return {pid: {**v, "pct": _safe(v["def_FGM"], v["def_FGA"])} for pid, v in agg.items()}


def quarter_boxes(game_ids=None, events=None):
    """
    Per-player, per-quarter finalized box scores.
    Returns {player_id: {1: box, 2: box, 3: box, 4: box, ...}}.
    Divide a quarter total by games for per-quarter PPG/APG/etc.
    """
    if events is None:
        events = fetch_events(game_ids)
    by_q = defaultdict(list)
    for e in events:
        by_q[e["quarter"]].append(e)
    out = defaultdict(dict)
    for q, evs in by_q.items():
        for pid, b in aggregate_player_boxes(events=evs).items():
            out[pid][q] = b
    return dict(out)


# ══════════════════════════════════════════════════════════════════════════════
#  TEAM RATINGS  (per 100 possessions)
# ══════════════════════════════════════════════════════════════════════════════

def estimate_possessions(team_box):
    """
    Possessions = FGA + TOV.

    A possession is exactly one shot or one turnover (FGA = #shot events,
    TOV = #turnover events). Free throws and fouls never add a possession.
    This is an exact count off the box, not the Dean Oliver estimate, and it
    works on any box (team or player) since it only reads FGA and TOV.
    """
    return team_box["FGA"] + team_box["TOV"]


def _team_box(team_id, game_ids=None, events=None):
    """Sum player boxes for one team into a single team box."""
    boxes = aggregate_player_boxes(game_ids, events=events)
    # map player -> team
    rows = query("SELECT id, team_id FROM players")
    team_of = {r["id"]: r["team_id"] for r in rows}
    tb = finalize_box(_blank_box())
    for pid, b in boxes.items():
        if team_of.get(pid) != team_id:
            continue
        for k in tb:
            tb[k] += b.get(k, 0)
    return tb


def team_ratings(team_id, opp_id, game_ids=None):
    """
    Offensive / Defensive / Net Rating for a team over the given games.
        ORtg = 100 * PTS / POSS
        DRtg = 100 * opp_PTS / opp_POSS
        NetRtg = ORtg - DRtg
    `opp_id` is the opponent whose events define the defensive side. For a single
    head-to-head game set this is exact; across mixed opponents, pass opp_id=None
    to treat 'everyone else in the sample' as the opponent.
    """
    events = fetch_events(game_ids)
    tb = _team_box(team_id, game_ids, events=events)

    if opp_id is not None:
        ob = _team_box(opp_id, game_ids, events=events)
    else:
        # aggregate all non-team players as the opponent
        boxes = aggregate_player_boxes(game_ids, events=events)
        rows = query("SELECT id, team_id FROM players")
        team_of = {r["id"]: r["team_id"] for r in rows}
        ob = finalize_box(_blank_box())
        for pid, b in boxes.items():
            if team_of.get(pid) == team_id:
                continue
            for k in ob:
                ob[k] += b.get(k, 0)

    off_poss = estimate_possessions(tb)
    def_poss = estimate_possessions(ob)
    ortg = 100 * _safe(tb["PTS"], off_poss)
    drtg = 100 * _safe(ob["PTS"], def_poss)
    return {"ORtg": ortg, "DRtg": drtg, "NetRtg": ortg - drtg,
            "off_poss": off_poss, "def_poss": def_poss}


# ══════════════════════════════════════════════════════════════════════════════
#  INDIVIDUAL RATINGS  (Dean Oliver, "Basketball on Paper")
# ══════════════════════════════════════════════════════════════════════════════
#
#  Oliver's individual ORtg/DRtg normally need each player's MINUTES. This DB has
#  no minute tracking, but game_event_lineup records who was on the floor for
#  every event, so we substitute each player's ON-COURT FRACTION (events on court
#  / team events) wherever the formula uses MP/(Team_MP/5). That term is exactly
#  "fraction of game played", so the substitution is faithful — no need to know
#  whether a game is 32/40/48 minutes. Caveat: with a 15-game sample and inferred
#  ORB/DRB these are approximations; treat them as directional, not gospel.

def oncourt_fraction(game_ids=None):
    """{player_id: fraction of their team's events they were on the floor for}."""
    clause, params = _game_filter(game_ids)
    # events per game (denominator is # events, since 5 of each team are always on)
    n_rows = query(
        f"SELECT COUNT(DISTINCT ge.id) c FROM game_events ge WHERE 1=1{clause}",
        params,
    )
    n_events = n_rows[0]["c"] if n_rows else 0
    if not n_events:
        return {}
    rows = query(
        f"""SELECT gel.player_id pid, COUNT(*) c
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            WHERE 1=1{clause}
            GROUP BY gel.player_id""",
        params,
    )
    return {r["pid"]: r["c"] / n_events for r in rows}


def _opp_box_for(team_id, game_ids, events):
    """Aggregate every non-team player into a single opponent box."""
    boxes = aggregate_player_boxes(game_ids, events=events)
    rows = query("SELECT id, team_id FROM players")
    team_of = {r["id"]: r["team_id"] for r in rows}
    ob = finalize_box(_blank_box())
    for pid, b in boxes.items():
        if team_of.get(pid) == team_id:
            continue
        for k in ob:
            ob[k] += b.get(k, 0)
    return ob


def individual_offensive_rating(player_id, team_id, game_ids=None,
                                events=None, fp=None):
    """
    Oliver individual Offensive Rating = points produced per 100 individual
    possessions used. Returns None if the player has no usable possessions.
    """
    if events is None:
        events = fetch_events(game_ids)
    boxes = aggregate_player_boxes(game_ids, events=events)
    p = boxes.get(player_id)
    if not p:
        return None
    tb = _team_box(team_id, game_ids, events=events)
    ob = _opp_box_for(team_id, game_ids, events)
    if fp is None:
        fp = oncourt_fraction(game_ids).get(player_id, 0.0)
    if fp <= 0:
        return None

    # shorthand
    FGM, FGA = p["FGM"], p["FGA"]
    FTM, FTA = p["FTM"], p["FTA"]
    P3M, PTS, AST, ORB, TOV = p["3PM"], p["PTS"], p["AST"], p["ORB"], p["TOV"]
    tFGM, tFGA = tb["FGM"], tb["FGA"]
    tFTM, tFTA = tb["FTM"], tb["FTA"]
    t3M, tPTS, tAST, tORB, tTOV = tb["3PM"], tb["PTS"], tb["AST"], tb["ORB"], tb["TOV"]
    oppDRB = ob["DRB"]

    if FGA == 0 and FTA == 0 and AST == 0:
        return None

    ftpct = _safe(FTM, FTA)

    qAST = (fp * 1.14 * _safe(tAST - AST, tFGM)) + (
        _safe(tAST * fp - AST, tFGM * fp - FGM) * (1 - fp)
    )

    FG_Part = FGM * (1 - 0.5 * _safe(PTS - FTM, 2 * FGA) * qAST) if FGA else 0.0
    AST_Part = 0.5 * _safe((tPTS - tFTM) - (PTS - FTM), 2 * (tFGA - FGA)) * AST
    FT_Part = (1 - (1 - ftpct) ** 2) * 0.4 * FTA

    t_ftpct = _safe(tFTM, tFTA)
    Team_ScPoss = tFGM + (1 - (1 - t_ftpct) ** 2) * tFTA * 0.4
    Team_ORBpct = _safe(tORB, tORB + oppDRB)
    Team_Playpct = _safe(Team_ScPoss, tFGA + tFTA * 0.4 + tTOV)
    denom = (1 - Team_ORBpct) * Team_Playpct + Team_ORBpct * (1 - Team_Playpct)
    Team_ORB_Weight = _safe((1 - Team_ORBpct) * Team_Playpct, denom)
    ORB_Part = ORB * Team_ORB_Weight * Team_Playpct

    orb_adj = 1 - _safe(tORB, Team_ScPoss) * Team_ORB_Weight * Team_Playpct
    ScPoss = (FG_Part + AST_Part + FT_Part) * orb_adj + ORB_Part
    FGxPoss = (FGA - FGM) * (1 - 1.07 * Team_ORBpct)
    FTxPoss = ((1 - ftpct) ** 2) * 0.4 * FTA
    TotPoss = ScPoss + FGxPoss + FTxPoss + TOV
    if TotPoss <= 0:
        return None

    PProd_FG = 2 * (FGM + 0.5 * P3M) * (1 - 0.5 * _safe(PTS - FTM, 2 * FGA) * qAST) if FGA else 0.0
    PProd_AST = (
        2 * _safe(tFGM - FGM + 0.5 * (t3M - P3M), tFGM - FGM)
        * 0.5 * _safe((tPTS - tFTM) - (PTS - FTM), 2 * (tFGA - FGA)) * AST
    )
    pts_per_scposs = _safe(tPTS, tFGM + (1 - (1 - t_ftpct) ** 2) * 0.4 * tFTA)
    PProd_ORB = ORB * Team_ORB_Weight * Team_Playpct * pts_per_scposs
    PProd = (PProd_FG + PProd_AST + FTM) * orb_adj + PProd_ORB

    return 100 * PProd / TotPoss


def individual_defensive_rating(player_id, team_id, game_ids=None,
                                events=None, fp=None, boxes=None, tb=None, ob=None):
    """
    Oliver individual Defensive Rating = points allowed per 100 defensive
    possessions, blended off the team rate via the player's Stop%. Lower = better.
    Uses on-court fraction in place of minutes (see section header). Returns None
    if the player was never on the floor.

    `boxes` / `tb` / `ob` may be supplied precomputed (the player-box map, the
    player's team box, and the opponent box) so a batch caller can avoid the
    O(players) re-aggregation; each is computed on demand when None. See
    individual_defensive_rating_all for the batched whole-pool version.
    """
    if events is None:
        events = fetch_events(game_ids)
    if boxes is None:
        boxes = aggregate_player_boxes(game_ids, events=events)
    p = boxes.get(player_id)
    if not p:
        return None
    if tb is None:
        tb = _team_box(team_id, game_ids, events=events)
    if ob is None:
        ob = _opp_box_for(team_id, game_ids, events)
    if fp is None:
        fp = oncourt_fraction(game_ids).get(player_id, 0.0)
    if fp <= 0:
        return None

    STL, BLK, DRB, PF = p["STL"], p["BLK"], p["DRB"], p["PF"]
    tBLK, tSTL, tDRB, tPF = tb["BLK"], tb["STL"], tb["DRB"], tb["PF"]
    oFGM, oFGA = ob["FGM"], ob["FGA"]
    oFTM, oFTA = ob["FTM"], ob["FTA"]
    oORB, oTOV, oPTS = ob["ORB"], ob["TOV"], ob["PTS"]

    def_poss = estimate_possessions(ob)
    if def_poss <= 0:
        return None
    Team_DRtg = 100 * _safe(oPTS, def_poss)

    DOR_pct = _safe(oORB, oORB + tDRB)
    DFG_pct = _safe(oFGM, oFGA)
    fm_denom = DFG_pct * (1 - DOR_pct) + (1 - DFG_pct) * DOR_pct
    FMwt = _safe(DFG_pct * (1 - DOR_pct), fm_denom)

    Stops1 = STL + BLK * FMwt * (1 - 1.07 * DOR_pct) + DRB * (1 - FMwt)
    # per-minute terms collapse to (·)*(fp/5) since MP/Team_MP = fp/5
    Stops2 = (
        (oFGA - oFGM - tBLK) * (fp / 5) * FMwt * (1 - 1.07 * DOR_pct)
        + (oTOV - tSTL) * (fp / 5)
        + _safe(PF, tPF) * 0.4 * oFTA * (1 - _safe(oFTM, oFTA)) ** 2
    )
    Stops = Stops1 + Stops2

    # Stop% = Stops * (Opp_MP/MP) / Team_Poss ; Opp_MP/MP = 5/fp
    Stop_pct = _safe(Stops * (5 / fp), def_poss)
    Stop_pct = max(0.0, min(1.0, Stop_pct))

    D_pts_per_scposs = _safe(oPTS, oFGM + (1 - (1 - _safe(oFTM, oFTA)) ** 2) * oFTA * 0.4)
    return Team_DRtg + 0.2 * (100 * D_pts_per_scposs * (1 - Stop_pct) - Team_DRtg)


def individual_defensive_rating_all(game_ids=None, events=None):
    """
    {player_id: individual DRtg} for every player in the sample, in ONE pass.

    Same Oliver formula as individual_defensive_rating, but the player-box map,
    each team's box, and each team's opponent box are built once and reused, so
    the whole pool costs one box aggregation instead of one per player. Players
    who were never on the floor (fp<=0) or whose team has no defensive
    possessions are omitted. Lower is better.
    """
    if events is None:
        events = fetch_events(game_ids)
    boxes = aggregate_player_boxes(game_ids, events=events)
    if not boxes:
        return {}
    team_of = {r["id"]: r["team_id"] for r in query("SELECT id, team_id FROM players")}
    frac = oncourt_fraction(game_ids)

    # team boxes from the single box map; opp box = league total minus that team
    keys = list(finalize_box(_blank_box()).keys())
    team_box = {}
    for pid, b in boxes.items():
        tid = team_of.get(pid)
        if tid is None:
            continue
        tb = team_box.setdefault(tid, {k: 0 for k in keys})
        for k in keys:
            tb[k] += b.get(k, 0)
    total = {k: sum(tb[k] for tb in team_box.values()) for k in keys}
    opp_box = {tid: {k: total[k] - tb[k] for k in keys} for tid, tb in team_box.items()}

    out = {}
    for pid in boxes:
        tid = team_of.get(pid)
        if tid is None:
            continue
        d = individual_defensive_rating(
            pid, tid, events=events, fp=frac.get(pid, 0.0),
            boxes=boxes, tb=team_box.get(tid), ob=opp_box.get(tid))
        if d is not None:
            out[pid] = d
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  TEAM GAME FILTERS & SUMMARY  (wins/losses, MOV, POSS/G)
# ══════════════════════════════════════════════════════════════════════════════
#
#  games convention (see pages/1_Input_Hub.py): team1_id = home (home_score),
#  team2_id = away (away_score).

def team_games(team_id, outcome=None, tracked_only=True):
    """
    Game rows involving team_id, from that team's point of view. `outcome` filters
    to 'W' or 'L' (None = all). Each row: id, team_pts, opp_pts, margin, win, tracked.
    Only games with both scores recorded are returned.
    """
    rows = query(
        """SELECT id, team1_id, team2_id, home_score, away_score, tracked
           FROM games
           WHERE (team1_id=? OR team2_id=?)
             AND home_score IS NOT NULL AND away_score IS NOT NULL
             AND season='Current'""",
        (team_id, team_id),
    )
    out = []
    for r in rows:
        if tracked_only and not r["tracked"]:
            continue
        is_home = r["team1_id"] == team_id
        team_pts = r["home_score"] if is_home else r["away_score"]
        opp_pts  = r["away_score"] if is_home else r["home_score"]
        win = team_pts > opp_pts
        if outcome == "W" and not win:
            continue
        if outcome == "L" and win:
            continue
        out.append({
            "id": r["id"], "team_pts": team_pts, "opp_pts": opp_pts,
            "margin": team_pts - opp_pts, "win": win, "tracked": bool(r["tracked"]),
        })
    return out


def team_game_ids(team_id, outcome=None, tracked_only=True):
    """Just the game ids for team_games(...) — handy to feed other stat fns."""
    return [g["id"] for g in team_games(team_id, outcome, tracked_only)]


def team_summary(team_id, opp_id=None, outcome=None, game_ids=None):
    """
    Win/loss record, Margin of Victory, points for/against per game, possessions
    per game, and ORtg/DRtg/Net over the selected (optionally W- or L-only) games.

    `game_ids` is the entitlement read-filter: None = all of the team's games;
    a set restricts every aggregation (record, possession ratings) to those games
    so a co-op scout never sees a team's non-pooled tracked depth here.
    """
    games = team_games(team_id, outcome)
    if game_ids is not None:
        _allow = set(game_ids)
        games = [g for g in games if g["id"] in _allow]
    gids = [g["id"] for g in games]
    n = len(games)
    wins = sum(1 for g in games if g["win"])
    mov = _safe(sum(g["margin"] for g in games), n)
    pf_pg = _safe(sum(g["team_pts"] for g in games), n)
    pa_pg = _safe(sum(g["opp_pts"] for g in games), n)

    tb = _team_box(team_id, gids) if gids else finalize_box(_blank_box())
    poss = estimate_possessions(tb)
    ratings = team_ratings(team_id, opp_id, gids) if gids else {}
    return {
        "games": n, "wins": wins, "losses": n - wins,
        "MOV": mov, "PF_pg": pf_pg, "PA_pg": pa_pg,
        "POSS_pg": _safe(poss, n),
        **ratings,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  ON / OFF SPLITS  (how the TEAM performs with a player on vs off the floor)
# ══════════════════════════════════════════════════════════════════════════════
#
#  Uses game_event_lineup to split every event in the player's team's games into
#  "player on the floor" vs "player off the floor", then measures the TEAM's
#  rebounding / playmaking on each side. A positive on-minus-off delta means the
#  team does that thing better when the player plays. Directional on a small,
#  sparsely-tracked sample — the helpers return opportunity counts so the UI can
#  gate on sample size.

def _team_game_ids(team_id):
    """Tracked game ids the team appears in, active season only. Single source
    for the Tier-2 helpers (concession / possession_value / rotation_plan)."""
    return [r["id"] for r in query(
        "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) AND tracked=1 "
        "AND season='Current'", (team_id, team_id))]


def _team_game_ids_all(team_id):
    """All game ids the team appears in (tracked or not), active season only."""
    rows = query("SELECT id FROM games WHERE (team1_id=? OR team2_id=?) "
                 "AND season='Current'", (team_id, team_id))
    return [r["id"] for r in rows]


def _player_oncourt_event_ids(player_id, game_ids):
    """Set of event_ids (within game_ids) the player was on the floor for."""
    if not game_ids:
        return set()
    marks = ",".join("?" * len(game_ids))
    rows = query(
        f"""SELECT gel.event_id eid
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            WHERE gel.player_id = ? AND ge.game_id IN ({marks})""",
        (player_id, *game_ids),
    )
    return {r["eid"] for r in rows}


def player_rebound_onoff(player_id, team_id, game_ids=None):
    """
    Team rebounding with the player ON vs OFF the floor.

    Returns on/off OREB% / DREB% / TRB% (0-100) plus the opportunity counts that
    back each split, or None if the team has no events. OREB% = team offensive
    boards / team missed shots that were rebounded (while on/off); DREB% = team
    defensive boards / opponent missed shots that were rebounded.
    """
    gids = game_ids if game_ids is not None else _team_game_ids_all(team_id)
    if not gids:
        return None
    events = fetch_events(gids)
    on_ids = _player_oncourt_event_ids(player_id, gids)

    agg = {s: {"oreb_made": 0, "oreb_opps": 0, "dreb_made": 0, "dreb_opps": 0}
           for s in ("on", "off")}
    for e in events:
        reb = e["rebound_by_id"]
        shooter_team = e["shooter_team_id"]
        if reb is None or shooter_team is None:
            continue
        side = "on" if e["id"] in on_ids else "off"
        a = agg[side]
        got = (e["rebounder_team_id"] == team_id)
        if shooter_team == team_id:           # team missed -> offensive board chance
            a["oreb_opps"] += 1
            a["oreb_made"] += 1 if got else 0
        else:                                 # opponent missed -> defensive chance
            a["dreb_opps"] += 1
            a["dreb_made"] += 1 if got else 0

    def pct(made, opps):
        return 100 * _safe(made, opps) if opps else None

    out = {}
    for s in ("on", "off"):
        a = agg[s]
        out[f"{s}_oreb_pct"] = pct(a["oreb_made"], a["oreb_opps"])
        out[f"{s}_dreb_pct"] = pct(a["dreb_made"], a["dreb_opps"])
        out[f"{s}_trb_pct"] = pct(a["oreb_made"] + a["dreb_made"],
                                  a["oreb_opps"] + a["dreb_opps"])
        out[f"{s}_oreb_opps"] = a["oreb_opps"]
        out[f"{s}_dreb_opps"] = a["dreb_opps"]
    return out


def player_playmaking_onoff(player_id, team_id, game_ids=None):
    """
    Team ball-movement and ball-security with the player ON vs OFF the floor.

    Team AST% = assisted FGM / FGM; Team TOV% = TOV / (FGA + TOV),
    each split by whether the player was on the floor. Returns the percentages
    (0-100, None if undefined) plus the FGM / TOV counts behind each split.
    """
    gids = game_ids if game_ids is not None else _team_game_ids_all(team_id)
    if not gids:
        return None
    events = fetch_events(gids)
    on_ids = _player_oncourt_event_ids(player_id, gids)

    agg = {s: {"fgm": 0, "ast": 0, "fga": 0, "tov": 0}
           for s in ("on", "off")}
    for e in events:
        if e["shooter_team_id"] != team_id:   # only the team's own offense
            continue
        side = "on" if e["id"] in on_ids else "off"
        a = agg[side]
        et = e["event_type"]
        if et == "shot":
            a["fga"] += 1
            if e["shot_result"] == "make":
                a["fgm"] += 1
                if e["pass_from_id"] is not None:
                    a["ast"] += 1
        elif et == "turnover":
            a["tov"] += 1

    out = {}
    for s in ("on", "off"):
        a = agg[s]
        poss = a["fga"] + a["tov"]
        out[f"{s}_ast_pct"] = 100 * _safe(a["ast"], a["fgm"]) if a["fgm"] else None
        out[f"{s}_tov_pct"] = 100 * _safe(a["tov"], poss) if poss else None
        out[f"{s}_fgm"] = a["fgm"]
        out[f"{s}_tov"] = a["tov"]
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  SHOT-LOCATION SPLITS  (zone × 2/3 — powers shot charts & hot-zone grids)
# ══════════════════════════════════════════════════════════════════════════════

ZONES = ("LC", "LW", "C", "RW", "RC")  # left-corner, left-wing, center, right-wing, right-corner


def player_zone_splits(game_ids=None, events=None):
    """
    Per-player shooting broken out by court zone and shot value.

    Returns {player_id: {(zone, shot_type): {"FGA","FGM","pct"}}}, where zone is
    one of ZONES and shot_type is 2 or 3. Only shot events that carry a zone are
    counted, so the totals are the player's *located* attempts (in this DB every
    shot has a zone). This is the data behind the half-court shot chart and the
    5-zone hot-zone grid — the where-from view of a player's shot diet.
    """
    if events is None:
        events = fetch_events(game_ids)
    out = defaultdict(lambda: defaultdict(lambda: {"FGA": 0, "FGM": 0}))
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] is None:
            continue
        z = e["zone"]
        if not z:
            continue
        stype = 3 if e["shot_type"] == 3 else 2
        cell = out[e["primary_player_id"]][(z, stype)]
        cell["FGA"] += 1
        if e["shot_result"] == "make":
            cell["FGM"] += 1
    # finalize: add make-rate and collapse the defaultdicts to plain dicts
    final = {}
    for pid, cells in out.items():
        final[pid] = {k: {"FGA": v["FGA"], "FGM": v["FGM"],
                          "pct": _safe(v["FGM"], v["FGA"])}
                      for k, v in cells.items()}
    return final


def player_zone_guarded(game_ids=None, events=None, player_id=None):
    """
    Guarded vs unguarded shooting split for a player (or every player).

    Returns, per player, {"guarded": {FGA,FGM,pct}, "open": {FGA,FGM,pct}} where
    "guarded" = a defender was assigned (guarded_by_id set) and "open" = not. Lets
    the UI show how a player shoots when contested vs left open — a cleaner read on
    shot-making than raw FG%. When player_id is given, returns just that dict.
    """
    if events is None:
        events = fetch_events(game_ids)
    out = defaultdict(lambda: {"guarded": {"FGA": 0, "FGM": 0},
                               "open": {"FGA": 0, "FGM": 0}})
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] is None:
            continue
        side = "guarded" if e["guarded_by_id"] is not None else "open"
        cell = out[e["primary_player_id"]][side]
        cell["FGA"] += 1
        if e["shot_result"] == "make":
            cell["FGM"] += 1
    final = {}
    for pid, d in out.items():
        final[pid] = {s: {"FGA": v["FGA"], "FGM": v["FGM"],
                          "pct": _safe(v["FGM"], v["FGA"])}
                      for s, v in d.items()}
    if player_id is not None:
        return final.get(player_id, {"guarded": {"FGA": 0, "FGM": 0, "pct": 0.0},
                                     "open": {"FGA": 0, "FGM": 0, "pct": 0.0}})
    return final


def player_hand_splits(game_ids=None, events=None, player_id=None, hand=None):
    """
    Per-player shooting split by hand side: dominant vs weak.

    Each shot's floor side is a true half-court split (tap x when present, else the
    coarse zone; see helpers/handedness.py). The shooter's handedness maps that side
    to a bucket: a righty's right-half shots are "dominant", left-half "weak"; a
    lefty is mirrored. Dead-center shots (x==0, or legacy zone C) are IGNORED. Each
    bucket is also split guarded vs open, so the UI can show where a player shoots
    more, shoots better, and how contested those looks are — a sibling to
    player_zone_guarded keyed on hand side instead of contest.

    Returns {player_id: {bucket: {"all":{FGA,FGM,pct}, "guarded":{…}, "open":{…}}}}
    for bucket in ("dominant","weak"). With player_id, returns just that player's
    dict (zero-filled if they have no classifiable shots).
    """
    import helpers.handedness as HD
    if events is None:
        events = fetch_events(game_ids)
    if hand is None:
        hand = HD.hand_map()

    def _blank():
        return {k: {"FGA": 0, "FGM": 0} for k in ("all", "guarded", "open")}

    out = {}
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] is None:
            continue
        pid = e["primary_player_id"]
        bucket = HD.hand_bucket(e.get("shot_x"), e["zone"], hand.get(pid, "right"))
        if bucket is None:                 # dead-center / unclassifiable -> ignore
            continue
        d = out.setdefault(pid, {b: _blank() for b in HD.HAND_BUCKETS})
        gkey = "guarded" if e["guarded_by_id"] is not None else "open"
        made = e["shot_result"] == "make"
        for cell in (d[bucket]["all"], d[bucket][gkey]):
            cell["FGA"] += 1
            if made:
                cell["FGM"] += 1

    def _fin(d):
        return {b: {k: {"FGA": v["FGA"], "FGM": v["FGM"], "pct": _safe(v["FGM"], v["FGA"])}
                    for k, v in cells.items()}
                for b, cells in d.items()}

    final = {pid: _fin(d) for pid, d in out.items()}
    if player_id is not None:
        empty = {b: {k: {"FGA": 0, "FGM": 0, "pct": 0.0}
                     for k in ("all", "guarded", "open")} for b in HD.HAND_BUCKETS}
        return final.get(player_id, empty)
    return final


# ══════════════════════════════════════════════════════════════════════════════
#  SHOT LOCATIONS  (tap-captured x/y — the real shot chart, superset of zones)
# ══════════════════════════════════════════════════════════════════════════════

def located_shots(game_ids=None, events=None, player_id=None, team_id=None):
    """
    Tap-captured shot attempts that carry an (x, y) court location.

    Returns a list of {x, y, make, value, guarded, zone, player_id, team_id, dist}
    for every 'shot' event with shot_x/shot_y set, optionally filtered to one
    player (the shooter) or one team. Legacy zone-only shots (no x/y) are skipped,
    so callers can fall back to player_zone_splits()/shot_chart for those games.
    """
    if events is None:
        events = fetch_events(game_ids)
    import helpers.court_geom as CG
    out = []
    for e in events:
        if e["event_type"] != "shot":
            continue
        x, y = e.get("shot_x"), e.get("shot_y")
        if x is None or y is None:
            continue
        if player_id is not None and e["primary_player_id"] != player_id:
            continue
        if team_id is not None and e.get("shooter_team_id") != team_id:
            continue
        out.append({
            "x": x, "y": y,
            "make": e["shot_result"] == "make",
            "value": 3 if e["shot_type"] == 3 else 2,
            "guarded": e["guarded_by_id"] is not None,
            "zone": e["zone"],
            "player_id": e["primary_player_id"],
            "team_id": e.get("shooter_team_id"),
            "dist": CG.shot_distance(x, y),
            "play_type": e.get("play_type"),
            "defense": e.get("defense"),
        })
    return out


def shot_location_summary(shots):
    """
    Roll a list of located_shots() into rim / mid-range / three splits plus the
    average shot distance. Returns None for an empty list. Rim = within 4 ft;
    mid = a 2 beyond the rim; three = value 3.
    """
    if not shots:
        return None
    n = len(shots)
    makes = sum(1 for s in shots if s["make"])
    rim = [s for s in shots if s["dist"] <= 4]
    mid = [s for s in shots if s["dist"] > 4 and s["value"] == 2]
    three = [s for s in shots if s["value"] == 3]

    def _fg(group):
        return (sum(1 for s in group if s["make"]) / len(group)) if group else None

    return {
        "n": n, "fg": _safe(makes, n),
        "avg_dist": _safe(sum(s["dist"] for s in shots), n),
        "rim_n": len(rim), "rim_fg": _fg(rim),
        "mid_n": len(mid), "mid_fg": _fg(mid),
        "three_n": len(three), "three_fg": _fg(three),
    }


# Shot-length buckets — the single source for every "by shot distance" breakdown.
# Top edge = court_geom.THREE_R (NFHS HS 3-pt arc, 19.75 ft); kept as a literal
# here so stats.py never imports court_geom's matplotlib stack at module load.
# These are PURE distance bands, independent of the 2/3 value: a corner three
# (~19 ft) lands in the 10-19.75 band by *length*, not the 19.75+ band — by design,
# since this answers "from how far" not "how many threes".
DIST_EDGES = (5.0, 10.0, 19.75)
DIST_LABELS = ("<5 ft", "5-10 ft", "10-19.75 ft", "19.75+ ft")


def distance_buckets(shots, edges=DIST_EDGES, labels=DIST_LABELS):
    """
    Roll a list of located_shots()/mapped_shots() (each carrying `dist`, `make`,
    `value`) into shot-length bands. `edges` are the inner cut points (feet); the
    bands are [0,e0) [e0,e1) … [e_last,∞) — len(edges)+1 buckets, labelled by
    `labels`. Right-edge exclusive, so a shot exactly on an edge falls in the
    upper band.

    Returns an ordered list (one dict per band, empties included so every caller
    shows the same columns):
        {label, lo, hi, n, fgm, fg, pps, share}
      fg    = make rate (0-1) or None for an empty band
      pps   = points per attempt (make×value averaged over the band's attempts)
      share = band attempts / total attempts (0-1)
    Returns [] for no shots.
    """
    if not shots:
        return []

    def _idx(dist):
        i = 0
        for e in edges:
            if dist < e:
                break
            i += 1
        return i

    nb = len(edges) + 1
    acc = [{"n": 0, "fgm": 0, "pts": 0} for _ in range(nb)]
    for s in shots:
        b = acc[_idx(s["dist"])]
        b["n"] += 1
        if s["make"]:
            b["fgm"] += 1
            b["pts"] += s["value"]
    total = len(shots)
    bounds = (0.0,) + tuple(edges) + (None,)   # lo/hi per band; hi None = open top
    out = []
    for i, b in enumerate(acc):
        n = b["n"]
        out.append({
            "label": labels[i] if i < len(labels) else f"band{i}",
            "lo": bounds[i], "hi": bounds[i + 1],
            "n": n, "fgm": b["fgm"],
            "fg": _safe(b["fgm"], n) if n else None,
            "pps": _safe(b["pts"], n) if n else None,
            "share": _safe(n, total),
        })
    return out


def distance_buckets_caption(buckets, *, show_pps=False):
    """One-line '· '-joined caption for distance_buckets(), matching the
    shot_location_summary captions ('label: n · fg%'). Empty bands render as '—'.
    Returns '' when there are no shots, so callers can `if cap: st.caption(cap)`."""
    if not buckets:
        return ""
    parts = []
    for b in buckets:
        if b["n"]:
            seg = f"{b['label']}: {b['n']} · {b['fg'] * 100:.0f}%"
            if show_pps and b["pps"] is not None:
                seg += f" · {b['pps']:.2f} PPS"
        else:
            seg = f"{b['label']}: —"
        parts.append(seg)
    return "  ·  ".join(parts)


def mapped_shots(game_ids=None, events=None, player_id=None, team_id=None,
                 include_approx=True):
    """
    Every shot placed on the court — real tap-captured (x, y) when present, else
    the zone centroid (flagged approx) so the new maps work on legacy zone data.

    Each: {x, y, make, value, guarded, zone, player_id, team_id, dist, approx}.
    `include_approx=False` keeps only real located shots. This is the feed for the
    hexbin / expected-points renders; it sharpens automatically as taps replace
    the zone approximations.
    """
    if events is None:
        events = fetch_events(game_ids)
    import helpers.court_geom as CG
    out = []
    for e in events:
        if e["event_type"] != "shot":
            continue
        if player_id is not None and e["primary_player_id"] != player_id:
            continue
        if team_id is not None and e.get("shooter_team_id") != team_id:
            continue
        value = 3 if e["shot_type"] == 3 else 2
        x, y, approx = e.get("shot_x"), e.get("shot_y"), False
        if x is None or y is None:
            if not include_approx:
                continue
            c = CG.zone_centroid(e["zone"], value)
            if c is None:
                continue
            x, y, approx = c[0], c[1], True
        out.append({
            "x": x, "y": y, "make": e["shot_result"] == "make", "value": value,
            "guarded": e["guarded_by_id"] is not None, "zone": e["zone"],
            "player_id": e["primary_player_id"], "team_id": e.get("shooter_team_id"),
            "dist": CG.shot_distance(x, y), "approx": approx,
            "play_type": e.get("play_type"),
            "defense": e.get("defense"),
        })
    return out


def distance_make_model(game_ids=None, events=None, shots=None, bin_ft=2.0):
    """
    League make-rate by (shot value, distance bin) — the engine behind the
    expected-points surface. Pools every shot (real + zone-approx) so the rates
    are stable on a small sample. Returns {"bins", "bins_n", "by_value",
    "overall", "bin_ft"}.
    """
    if shots is None:
        shots = mapped_shots(game_ids, events)
    agg = defaultdict(lambda: {"fga": 0, "fgm": 0})
    byval = defaultdict(lambda: {"fga": 0, "fgm": 0})
    tot = {"fga": 0, "fgm": 0}
    for s in shots:
        key = (s["value"], int(s["dist"] // bin_ft))
        agg[key]["fga"] += 1
        byval[s["value"]]["fga"] += 1
        tot["fga"] += 1
        if s["make"]:
            agg[key]["fgm"] += 1
            byval[s["value"]]["fgm"] += 1
            tot["fgm"] += 1
    return {
        "bins": {k: _safe(v["fgm"], v["fga"]) for k, v in agg.items()},
        "bins_n": {k: v["fga"] for k, v in agg.items()},
        "by_value": {k: _safe(v["fgm"], v["fga"]) for k, v in byval.items()},
        "overall": _safe(tot["fgm"], tot["fga"]), "bin_ft": bin_ft,
    }


def expected_points_at(x, y, model):
    """Expected points for a shot from (x, y): league make-rate at that distance &
    value × the value. Falls back to the value-wide rate for thin distance bins."""
    import helpers.court_geom as CG
    value = CG.shot_value(x, y)
    dist = CG.shot_distance(x, y)
    key = (value, int(dist // model["bin_ft"]))
    rate = model["bins"].get(key)
    if rate is None or model["bins_n"].get(key, 0) < 4:
        rate = model["by_value"].get(value, model["overall"])
    return rate * value


# ══════════════════════════════════════════════════════════════════════════════
#  PER-GAME BOX SCORES  (one event pass, grouped by game)
# ══════════════════════════════════════════════════════════════════════════════

def player_game_boxes(game_ids=None, events=None):
    """
    Every player's finalized box score for each game, in a single event pass.

    Returns {player_id: {game_id: finalized_box}}. This is the source for game
    logs, single-game career highs, double/triple-double counts and game-to-game
    consistency — anything that needs to look at a player's individual games
    rather than their season totals. One pass over the events (grouped by
    game_id) instead of re-aggregating per game.
    """
    if events is None:
        events = fetch_events(game_ids)
    by_game = defaultdict(list)
    for e in events:
        by_game[e["game_id"]].append(e)
    out = defaultdict(dict)
    for gid, evs in by_game.items():
        for pid, b in aggregate_player_boxes(events=evs).items():
            out[pid][gid] = b
    return dict(out)


def double_triple_doubles(box_by_game):
    """
    Count double-doubles / triple-doubles from a {game_id: box} mapping.

    A category counts when the per-game total is >= 10 across PTS / TRB / AST /
    STL / BLK; a double-double is >=2 such categories in a game, triple-double
    >=3. Returns {"dd","td","best_pts","best_reb","best_ast","pts_list"}. The
    counting-stat thresholds are the standard box-score milestones.
    """
    cats = ("PTS", "TRB", "AST", "STL", "BLK")
    dd = td = 0
    best = {"PTS": 0, "TRB": 0, "AST": 0}
    pts_list = []
    for b in box_by_game.values():
        n = sum(1 for c in cats if b.get(c, 0) >= 10)
        if n >= 2:
            dd += 1
        if n >= 3:
            td += 1
        for c in ("PTS", "TRB", "AST"):
            best[c] = max(best[c], b.get(c, 0))
        pts_list.append(b.get("PTS", 0))
    return {"dd": dd, "td": td, "best_pts": best["PTS"],
            "best_reb": best["TRB"], "best_ast": best["AST"],
            "pts_list": pts_list}
