"""
projection.py — career player projection (the base layer).

Every other projection surface (depth-chart minutes, the signature-stat lineup
optimizer, the future year-to-year team projection) needs one honest thing first:
a *stabilized* read of how good a player is per opportunity, that survives a
3-game sample. This module is that read.

It invents no new statistic and no new math. It orchestrates:

  * helpers.player_ratings.player_stat_table  — the raw per-player rate leaves
  * helpers.shrinkage                          — the empirical-Bayes stabilizers
  * helpers.archetypes                         — the role-aware prior anchor
  * helpers.identity                           — the cross-season career window

For each player-INTRINSIC rate (efficiency / skill — the things that travel with
the player across rosters and seasons) it returns a projection:

    own → proj (blended toward a prior by how much evidence backs it),

plus the prior it used, the credibility weight, a directional flag, and a delta
vs the **average tracked team** (which, for a league-relative rate, IS the league
pool mean — so the baseline is free).

WHY intrinsic-only: usage / minutes / raw volume are *shares* of a fixed team
pie. They redistribute when the roster changes, so projecting them flat double-
counts a departed player's share. Those are the roster-aware layer's job
(helpers.lineup_projection). This module stays on skill rates that genuinely
carry.

WHY the prior: on a ~15-game single-program sample most players have 1-3 tracked
games, where a raw rate is noise. The stabilizer pulls a thin rate toward its
archetype's mean (or the league mean when the archetype itself is too thin to
trust) by the opportunity volume behind it — a 21-game starter keeps almost all
of their edge, a 3-game cameo is a near-even blend with the prior.

Pure data layer: db + stats + shrinkage + archetypes + identity. No streamlit.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.shrinkage as SH


# ── the player-intrinsic rate leaves this layer projects ────────────────────────
# (out_name, table_key, volume_fn, lower_is_better). volume_fn(row) -> the
# opportunity count backing the rate (the evidence weight for the shrink). Rates
# are kept in their native table unit; the shrink is unit-agnostic. lower_better
# is metadata for delta interpretation + the downstream optimizer, not the math.
def _poss(r):
    return (r.get("FGA") or 0) + 0.44 * (r.get("FTA") or 0) + (r.get("TOV") or 0)


def _tsvol(r):
    return (r.get("FGA") or 0) + 0.44 * (r.get("FTA") or 0)


def _fga(r):
    return r.get("FGA") or 0


_STAT_SPECS = [
    # scoring / shot-making skill
    ("eFG%",     "eFG%",     _fga,                             False),
    ("TS%",      "TS%",      _tsvol,                           False),
    ("3P%",      "3P%",      lambda r: r.get("3PA") or 0,      False),
    ("SMOE",     "SMOE",     _fga,                             False),
    ("ScEff",    "ScEff",    _fga,                             False),
    # creation / playmaking
    ("SelfCr%",  "SelfCr%",  _fga,                             False),
    ("PassFG%",  "PassFG%",  lambda r: r.get("PotAST") or 0,   False),
    ("AST%",     "AST%",     lambda r: (r.get("PotAST") or 0) or (r.get("MIN") or 0), False),
    # ball security / free throws
    ("TOV%",     "TOV%",     _poss,                            True),
    ("FTR",      "FTR",      _fga,                             False),
    # rebounding (backed by floor time — a positional-opportunity proxy)
    ("OREB%",    "OREB%",    lambda r: r.get("MIN") or 0,      False),
    ("DREB%",    "DREB%",    lambda r: r.get("MIN") or 0,      False),
    # defense (defended FG% allowed — LOWER is better)
    ("RimDFG%",  "RimDFG%",  lambda r: r.get("RimDShots") or 0,   True),
    ("PerimDFG%","PerimDFG%",lambda r: r.get("PerimDShots") or 0, True),
]

# attempts-equivalent prior weight for the volume shrink (shrinkage's tuned
# default: ~60 opportunities keeps almost all of an edge, ~4 is dragged back).
K = SH.DEFAULT_RATE_K

# an archetype's pooled opportunities for a stat must clear this before its mean
# is trusted as a prior anchor; below it, the league mean is used instead. On a
# one-season sample almost nothing clears it — by design, it degrades to league.
ARCHETYPE_MIN_OPP = 150.0

# credibility → directional honesty flag (c = vol / (vol + K))
_SOLID_C = 0.70      # ~28 opportunities
_THIN_C  = 0.35      # ~6.5 opportunities


def _weighted_mean(rows, key, vol_fn):
    """Volume-weighted pool mean of a rate in its native unit (None-safe)."""
    num = den = 0.0
    for r in rows:
        v = r.get(key)
        w = vol_fn(r)
        if v is None or not w or w <= 0:
            continue
        num += v * w
        den += w
    return (num / den) if den > 0 else None


def build_priors(table, clusters=None):
    """Compute the league prior and the per-archetype priors for every stat.

    `table`   = {pid: stat_row} (a player_stat_table slice).
    `clusters`= {pid: archetype_name} (from archetypes.cluster_players); optional.

    Returns {"league": {stat: mean}, "arch": {archetype: {stat: mean}},
             "arch_vol": {archetype: {stat: total_opp}}}.
    A None mean means the stat had no volume anywhere in the pool.
    """
    rows = list(table.values())
    league = {}
    for name, key, vol_fn, _lb in _STAT_SPECS:
        league[name] = _weighted_mean(rows, key, vol_fn)

    arch_rows = defaultdict(list)
    if clusters:
        for pid, r in table.items():
            a = clusters.get(pid)
            if a and a != "—":
                arch_rows[a].append(r)

    arch, arch_vol = {}, {}
    for a, rs in arch_rows.items():
        arch[a], arch_vol[a] = {}, {}
        for name, key, vol_fn, _lb in _STAT_SPECS:
            arch[a][name] = _weighted_mean(rs, key, vol_fn)
            arch_vol[a][name] = sum(vol_fn(r) for r in rs)
    return {"league": league, "arch": arch, "arch_vol": arch_vol}


def _select_prior(stat, archetype, priors):
    """(prior_mean, source) for a stat — the archetype mean when that archetype
    has enough pooled volume, else the league mean. Source ∈ {archetype, league}."""
    league = priors["league"].get(stat)
    if archetype and archetype in priors["arch"]:
        av = priors["arch_vol"].get(archetype, {}).get(stat, 0.0)
        am = priors["arch"][archetype].get(stat)
        if am is not None and av >= ARCHETYPE_MIN_OPP:
            return am, "archetype"
    return league, "league"


def _flag(c):
    if c >= _SOLID_C:
        return "solid"
    if c >= _THIN_C:
        return "directional"
    return "thin"


def project_player(pid, table, priors, clusters=None):
    """Projected intrinsic rates for one player.

    `table`/`priors`/`clusters` are the shared structures from `project_roster`
    (pass them in for a batch; a lone call can build them, but the roster path is
    the intended one). Returns None if the player isn't in the table.
    """
    row = table.get(pid)
    if row is None:
        return None
    archetype = clusters.get(pid) if clusters else None
    games = row.get("GP") or 0
    poss = int(round(_poss(row)))
    conf = SH.rating_confidence(games, poss=poss)

    stats = {}
    for name, key, vol_fn, lower in _STAT_SPECS:
        own = row.get(key)
        vol = vol_fn(row)
        prior, src = _select_prior(name, archetype, priors)
        if prior is None:
            # nothing to anchor to anywhere in the pool — skip the stat
            continue
        proj = SH.stabilize_value(own, vol, prior, K) if own is not None else prior
        c = vol / (vol + K) if (vol + K) > 0 else 0.0
        base = priors["league"].get(name)          # baseline = average tracked team
        stats[name] = {
            "own": round(own, 2) if own is not None else None,
            "prior": round(prior, 2),
            "proj": round(proj, 2) if proj is not None else None,
            "c": round(c, 3),
            "delta": (round(proj - base, 2)
                      if (proj is not None and base is not None) else None),
            "prior_src": src,
            "lower_better": lower,
            "flag": _flag(c) if own is not None else "thin",
        }

    return {
        "pid": pid,
        "name": row.get("name"),
        "team": row.get("team"),
        "team_id": row.get("team_id"),
        "archetype": archetype or "—",
        "class": row.get("class", "N/A"),   # passed through, NOT modeled (no aging curve)
        "games": games,
        "poss": poss,
        "confidence": conf,
        "stats": stats,
    }


def _clusters_for(table):
    """{pid: archetype_name} from the archetype engine; {} if it can't fit."""
    try:
        import helpers.archetypes as AR
        res = AR.cluster_players(table)
        return {pid: info.get("archetype", "—")
                for pid, info in (res.get("players") or {}).items()}
    except Exception:
        return {}


def project_roster(team_id, gender=None, game_ids=None, min_games=1,
                   season="Current"):
    """Projected intrinsic rates for every player on `team_id`.

    Builds the stat table, archetype clusters and priors ONCE (league-wide, so the
    prior + the average-tracked baseline stay league-relative), then projects each
    of the team's players against them. Returns {pid: projection}.

    `season` scopes the manual-box merge + opponent adjustment and MUST match the
    season the `game_ids` belong to — on a rolled-over prod the active season is a
    real string, not the 'Current' sentinel, so callers pass season_pick through.
    """
    import helpers.player_ratings as PR
    table = PR.player_stat_table(game_ids=game_ids, gender=gender,
                                 min_games=min_games, season=season)
    if not table:
        return {}
    clusters = _clusters_for(table)
    priors = build_priors(table, clusters)
    return {pid: proj for pid, r in table.items()
            if r.get("team_id") == team_id
            and (proj := project_player(pid, table, priors, clusters)) is not None}


def tracked_baseline(gender=None, game_ids=None, min_games=1, table=None,
                     season="Current"):
    """The average-tracked-team baseline per stat (the league volume-weighted pool
    mean). Shared with helpers.lineup_projection. {stat: mean}."""
    if table is None:
        import helpers.player_ratings as PR
        table = PR.player_stat_table(game_ids=game_ids, gender=gender,
                                     min_games=min_games, season=season)
    if not table:
        return {}
    return build_priors(table)["league"]


# ── career window (cross-season hook; inert until a 2nd season is linked) ────────
def career_game_ids(pid, game_ids=None):
    """Every tracked game_id belonging to this player's PERSON across seasons.

    Resolves the player to their stable identity (helpers.identity) and unions the
    games of all rows sharing it. On a single season this is just the player's own
    games — the seam that makes `project_*` span a career for free once a 2nd
    season is linked. `game_ids`, when given, bounds the result to that window.
    """
    import helpers.identity as ID
    row = query("SELECT COALESCE(identity_id, id) AS k FROM players WHERE id=?",
                (int(pid),))
    if not row:
        return list(game_ids) if game_ids is not None else []
    key = row[0]["k"]
    pids = [r["id"] for r in ID.identity_history(key)] or [int(pid)]
    ph = ",".join("?" * len(pids))
    gids = [r["game_id"] for r in query(
        f"""SELECT DISTINCT ge.game_id
            FROM game_event_lineup gel JOIN game_events ge ON ge.id = gel.event_id
            WHERE gel.player_id IN ({ph})""", tuple(pids))]
    if game_ids is not None:
        allow = set(game_ids)
        gids = [g for g in gids if g in allow]
    return gids
