"""
game_rating.py — Per-game player RATING (0-10), the soccer-style match grade.

A single glanceable number graded PER GAME, base 6.0 = an average game
(7.5 good, 8.5 great, 9+ rare, <6 poor). It sits ALONGSIDE Game Score (which
stays as the raw analyst stat) and is NOT folded into the season OVERALL rating —
this is a per-game performance grade, a different altitude from season talent.

Anchoring is HYBRID: an absolute event-delta engine (points added vs expected,
walked off the event stream) plus a ROLE-expectation layer so a glue guy who
defends and sets screens can grade 7.5 on a thin box while a chucking scorer
sits 5.5. Roles come from a small FIXED taxonomy (role_for) assigned off season
style — deliberately NOT the k-means archetype (variable k / shifting membership
would make the grade non-comparable over time).

Pipeline:
  1. build_model(events)        league expected-points by (shot_type, zone)
  2. player_game_value(...)      event walk → 5 component deltas (points-added)
  3. weighted_value(comp, role)  role weights reshape what counts → V
  4. calibrate(pool)             global mean/sd + per-role baseline offset
  5. rating_from_value(...)      V → 0-10, involvement-shrunk toward 6.0

Tracked games only (needs the event stream); boxed/manual games get no rating.
Pure data layer: depends on database.db + helpers.stats, never streamlit, so any
page or script can import it. Every function accepts injected events/model so the
engine is DB-free unit-testable (see tracker/test_game_rating.py).
"""
from __future__ import annotations

import statistics
from collections import defaultdict

import helpers.stats as S

# ── tunables (points-added units; global z-normalization rescales, so relative
#    structure + role weights carry the signal — these are defensible defaults) ──
PPP_LEAGUE  = 1.0     # value of a possession (turnover cost, steal credit)
FT_EXP      = 0.7     # expected points per FT attempt (league ~70%)
OREB_VAL    = 0.5     # extra-possession value of an offensive board
DREB_VAL    = 0.2     # a defensive board (ends opponent trip) worth less
FOUL_DRAWN  = 0.4     # drawing a foul (bonus / FTs)
FOUL_COMMIT = 0.3     # committing one
ASSIST_SHARE = 0.5    # passer's share of the created shot's expected value
DEF_MAKE_PTS = 2.0    # avg points per contested make (defensive SMOE scaling)

BASE     = 6.0
Z_SCALE  = 1.3        # rating points per pool SD of value
K_INV    = 5.0        # involvement (event-count) shrink half-weight
MIN_INV  = 4          # hide a grade below this many involving events
ROLE_CORRECT = 0.5    # fraction of a role's systematic V deficit corrected

ROLES = ["Two-Way Star", "Primary Scorer", "Shooter/Wing",
         "Playmaker", "Interior/Big", "Glue/Defender"]

COMPONENTS = ["shooting", "playmaking", "defense", "rebounding", "fouls"]

# Role weights reshape which contributions count. Glue/Defender leans defense +
# boards and never gets a scoring-volume drag; scorers/stars amplify shooting;
# playmaker amplifies passing; interior amplifies boards.
ROLE_WEIGHTS = {
    "Two-Way Star":   {"shooting": 1.10, "playmaking": 1.00, "defense": 1.15, "rebounding": 1.00, "fouls": 1.00},
    "Primary Scorer": {"shooting": 1.20, "playmaking": 1.00, "defense": 0.85, "rebounding": 0.85, "fouls": 1.00},
    "Shooter/Wing":   {"shooting": 1.15, "playmaking": 0.90, "defense": 0.95, "rebounding": 0.85, "fouls": 1.00},
    "Playmaker":      {"shooting": 1.00, "playmaking": 1.20, "defense": 0.95, "rebounding": 0.85, "fouls": 1.00},
    "Interior/Big":   {"shooting": 1.00, "playmaking": 0.85, "defense": 1.10, "rebounding": 1.20, "fouls": 1.00},
    "Glue/Defender":  {"shooting": 0.90, "playmaking": 1.00, "defense": 1.25, "rebounding": 1.15, "fouls": 1.10},
}


# ══════════════════════════════════════════════════════════════════════════════
#  EXPECTED-POINTS MODEL  (league make-rate by shot_type × zone → expected points)
# ══════════════════════════════════════════════════════════════════════════════

def build_model(events):
    """League expected-points reference from a pool of events. Per (shot_type,
    zone) make rate when the bucket has >=5 attempts, else the global rate for
    that shot_type. Returns a dict consumed by expected_points()."""
    made = defaultdict(int); att = defaultdict(int)
    g_made = defaultdict(int); g_att = defaultdict(int)
    for e in events:
        if e.get("event_type") != "shot":
            continue
        stype = e.get("shot_type") or 2
        made_flag = 1 if e.get("shot_result") == "make" else 0
        key = (stype, e.get("zone"))
        att[key] += 1; made[key] += made_flag
        g_att[stype] += 1; g_made[stype] += made_flag
    return {"made": dict(made), "att": dict(att),
            "g_made": dict(g_made), "g_att": dict(g_att)}


def expected_points(model, shot_type, zone):
    """Expected points for a shot of this type/zone = P(make) · value."""
    stype = shot_type or 2
    key = (stype, zone)
    a = model["att"].get(key, 0)
    if a >= 5:
        p = model["made"].get(key, 0) / a
    else:
        ga = model["g_att"].get(stype, 0)
        p = (model["g_made"].get(stype, 0) / ga) if ga else (0.5 if stype == 2 else 0.33)
    return p * stype


# ══════════════════════════════════════════════════════════════════════════════
#  EVENT WALK  →  COMPONENT DELTAS  (points-added units)
# ══════════════════════════════════════════════════════════════════════════════

def player_game_value(pid, events, model):
    """Walk one game's events and return this player's 5 component deltas
    (points-added) as a dict. Pure arithmetic; inject `events` + `model`."""
    comp = {c: 0.0 for c in COMPONENTS}
    involvement = 0
    def_exp_makes = 0.0; def_act_makes = 0

    for e in events:
        et = e.get("event_type")
        touched = False

        if et == "shot":
            stype = e.get("shot_type") or 2
            made = e.get("shot_result") == "make"
            xp = expected_points(model, stype, e.get("zone"))
            pts = stype if made else 0

            if e.get("primary_player_id") == pid:                 # shooter
                comp["shooting"] += pts - xp
                touched = True
            if made and e.get("pass_from_id") == pid:             # assist / created value
                comp["playmaking"] += xp * ASSIST_SHARE
                touched = True
            if e.get("blocked_by_id") == pid:                     # block: value prevented
                comp["defense"] += xp
                touched = True
            if e.get("guarded_by_id") == pid:                     # contested → def SMOE
                p = xp / stype if stype else 0.0
                def_exp_makes += p
                if made:
                    def_act_makes += 1
                touched = True

        elif et == "free_throw":
            if e.get("primary_player_id") == pid:
                comp["shooting"] += (1 if e.get("shot_result") == "make" else 0) - FT_EXP
                touched = True

        elif et == "turnover":
            if e.get("primary_player_id") == pid:                 # committed
                comp["playmaking"] -= PPP_LEAGUE
                touched = True
            if e.get("stolen_by_id") == pid:                      # forced
                comp["defense"] += PPP_LEAGUE
                touched = True

        elif et == "foul":
            if e.get("secondary_player_id") == pid:               # committer
                comp["fouls"] -= FOUL_COMMIT
                touched = True
            if e.get("primary_player_id") == pid:                 # drew it
                comp["fouls"] += FOUL_DRAWN
                touched = True

        # rebounds ride any missed shot/FT event
        if e.get("rebound_by_id") == pid:
            st_team = e.get("shooter_team_id"); rb_team = e.get("rebounder_team_id")
            if st_team is not None and rb_team == st_team:
                comp["rebounding"] += OREB_VAL
            else:
                comp["rebounding"] += DREB_VAL
            touched = True

        if touched:
            involvement += 1

    # defensive SMOE: points prevented vs expected as the contesting defender
    comp["defense"] += (def_exp_makes - def_act_makes) * DEF_MAKE_PTS
    comp["_involvement"] = involvement
    return comp


def weighted_value(comp, role):
    """Collapse component deltas to a single value V under a role's weights."""
    w = ROLE_WEIGHTS.get(role, ROLE_WEIGHTS["Glue/Defender"])
    return sum(w[c] * comp.get(c, 0.0) for c in COMPONENTS)


# ══════════════════════════════════════════════════════════════════════════════
#  ROLE ASSIGNMENT  (fixed 6-role taxonomy from season style — stable, no k-means)
# ══════════════════════════════════════════════════════════════════════════════

def role_for(row):
    """Map a player's SEASON stat row (player_ratings.player_stat_table shape) to
    one of the 6 fixed roles. Two-Way Star first (both quality composites strong),
    else top style axis + usage. Deterministic and stable across seasons."""
    o = row.get("OFFENSE"); d = row.get("DEFENSE")
    if o is not None and d is not None and o >= 62 and d >= 62:
        return "Two-Way Star"

    # NOTE: player_stat_table returns percentages on a 0-100 scale (USG% 11.6,
    # 3P% 33.3, 3PR 67.2, RimFGA% 22.4), NOT fractions — thresholds match that.
    usg   = row.get("USG%") or 0.0
    apg   = row.get("APG") or 0.0
    atov  = row.get("AST/TOV") or 0.0
    tpr   = row.get("3PR") or 0.0
    tp    = row.get("3P%") or 0.0
    rpg   = row.get("RPG") or 0.0
    rim   = row.get("RimFGA%") or 0.0
    ppg   = row.get("PPG") or 0.0

    if apg >= 3.5 or atov >= 1.8:
        return "Playmaker"
    if rim >= 50.0 or rpg >= 7.0:
        return "Interior/Big"
    if tpr >= 50.0 and tp >= 33.0:
        return "Shooter/Wing"
    if usg >= 24.0 or ppg >= 14.0:
        return "Primary Scorer"
    return "Glue/Defender"


# ══════════════════════════════════════════════════════════════════════════════
#  POOL CALIBRATION  +  VALUE → 0-10
# ══════════════════════════════════════════════════════════════════════════════

def calibrate(pool):
    """pool = list of (role, V) over every tracked player-game. Returns
    {mean, sd, role_offset} — global mean/sd plus a per-role baseline offset that
    corrects HALF of each role's systematic V deficit (so a low-usage role isn't
    floored while better players still pull up — Form reflects real quality)."""
    vs = [v for _, v in pool]
    if not vs:
        return {"mean": 0.0, "sd": 1.0, "role_offset": {}}
    mean = statistics.mean(vs)
    sd = statistics.pstdev(vs) or 1.0
    by_role = defaultdict(list)
    for role, v in pool:
        by_role[role].append(v)
    role_offset = {role: -((statistics.mean(vals) - mean) / sd) * ROLE_CORRECT
                   for role, vals in by_role.items()}
    return {"mean": mean, "sd": sd, "role_offset": role_offset}


def rating_from_value(V, role, calib, involvement=None):
    """Map a role-weighted value to a 0-10 grade. 6.0 = pool-average game; global
    z (so better players average higher, like real soccer ratings) + role offset;
    clamped; then shrunk toward 6.0 by involvement so a hot cameo can't read 9.0."""
    z = (V - calib["mean"]) / (calib["sd"] or 1.0)
    off = calib.get("role_offset", {}).get(role, 0.0)
    r = BASE + z * Z_SCALE + off * Z_SCALE
    r = max(0.0, min(10.0, r))
    if involvement is not None and involvement > 0:
        r = BASE + (r - BASE) * involvement / (involvement + K_INV)
    return round(r, 1)


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC: SEASON / PER-GAME RATINGS  (the DB-facing entry point)
# ══════════════════════════════════════════════════════════════════════════════

def _roles_map(game_ids):
    """{pid: role} from the season stat table (falls back to Glue/Defender)."""
    try:
        import helpers.player_ratings as PR
        table = PR.player_stat_table(game_ids=game_ids)
    except Exception:
        table = {}
    return {pid: role_for(row) for pid, row in table.items()}, table


def season_game_ratings(game_ids=None, events=None, roles=None):
    """Per-game 0-10 ratings for every tracked player-game in the pool.

    Returns {game_id: {pid: {"rating", "role", "V", "components", "involvement"}}}.
    One calibration over the whole pool so grades are mutually comparable. Roles
    come from the season stat table unless injected (tests)."""
    gids = game_ids
    if events is None:
        events = S.fetch_events(gids)
    if not events:
        return {}

    model = build_model(events)
    ev_by_game = defaultdict(list)
    for e in events:
        ev_by_game[e.get("game_id")].append(e)

    if roles is None:
        roles, _table = _roles_map(gids)

    # pass 1: component deltas + role-weighted V per player-game
    raw = defaultdict(dict)
    pool = []
    for gid, evs in ev_by_game.items():
        pids = set()
        for e in evs:
            for col in ("primary_player_id", "pass_from_id", "shot_created_by_id",
                        "blocked_by_id", "guarded_by_id", "stolen_by_id",
                        "secondary_player_id", "rebound_by_id"):
                v = e.get(col)
                if v is not None:
                    pids.add(v)
        for pid in pids:
            role = roles.get(pid, "Glue/Defender")
            comp = player_game_value(pid, evs, model)
            inv = comp.pop("_involvement", 0)
            if inv < MIN_INV:
                continue
            V = weighted_value(comp, role)
            raw[gid][pid] = (role, V, comp, inv)
            pool.append((role, V))

    calib = calibrate(pool)

    # pass 2: value → grade
    out = defaultdict(dict)
    for gid, pm in raw.items():
        for pid, (role, V, comp, inv) in pm.items():
            out[gid][pid] = {
                "rating": rating_from_value(V, role, calib, inv),
                "role": role, "V": round(V, 2),
                "components": {c: round(comp[c], 2) for c in COMPONENTS},
                "involvement": inv,
            }
    return dict(out)


