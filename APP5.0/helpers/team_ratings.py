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
DEFAULT_REG        = 0.5   # phantom average-games per team (shrinkage strength).
                           # Re-recalibrated 2026-07-18 on the T6 walk-forward
                           # (train ≤ Jan, predict Feb-Mar, ~1900 held-out games
                           # per gender): MAE falls monotonically as reg drops
                           # (2.0 → 0.5 = 21.45 → 20.27 F+M sum; still falling
                           # at 0.15 = 20.07). 0.5 is the adopted knee: 4x more
                           # aggressive than the old 2.0, keeps a real phantom-
                           # game divergence guard for the sparse NOVEMBER
                           # schedule graph — the one regime the late-season
                           # walk-forward cannot test. Revisit next season.
_SOR_MARGIN_CAP    = 20    # margin credited to a result is clamped to ±this
DEFAULT_SOS_WEIGHT = 1.6   # schedule-strength nudge, in RATING POINTS PER
                           # STANDARD DEVIATION of SOS. The SRS opponent-adjustment
                           # already accounts for who you played, but its shrinkage
                           # (DEFAULT_REG phantom games) and the sparsely-connected
                           # HS schedule graph under-credit teams that played a
                           # brutal slate. SOS is standardized within the field
                           # (z-score) before this weight is applied, so the median
                           # team gets ~0, the bump is independent of the league's
                           # SOS scale, and the extreme tails are bounded at ~±2.5
                           # SD (~±0.9 pts here). A team one SD tougher than average
                           # gains 0.8 pts. Set 0 for pure AdjNet+Class.
                           # Retuned 2026-07-05 from 0.4 after a full season of OK
                           # data (1433 teams, median 24 GP) showed SOS is now a
                           # dense, reliable signal (SD~10.6) that 0.4 barely used
                           # (bump SD only 0.4, max ±1.8pts). 0.8 was chosen over
                           # 1.0+ because at 1.0 the reshuffle among real, classed,
                           # deep-GP (15+) teams was too big (23% moved >10 ranks
                           # vs 12.5% at 0.8) relative to a "slight nudge".
                           # Re-audited 2026-07-12: flat in SOS on the fold
                           # backtest, churn-based 0.8 stood. RETUNED 2026-07-18
                           # on the T6 walk-forward (~1900 held-out games per
                           # gender): MAE improves monotonically to 1.6 (F+M sum
                           # 21.14 @0.4 → 20.60 @1.6) and goes FLAT beyond
                           # (20.53 @2.5 = noise), so 1.6 is the evidence knee.
                           # The churn concern loses to out-of-sample accuracy.


FORM_HALF_LIFE = 8.0       # games: recency half-life for form_ratings. A game this
                           # many games back counts half as much as a team's latest.
                           # Chosen gentle (not 3-4) on purpose: HS records are short
                           # (median ~24 GP, many teams <8) and already shrunk by REG
                           # phantom games, so an aggressive half-life would starve the
                           # effective sample and go noisy. At 8, a ~20-game team's
                           # oldest games still carry ~15-18% weight — a real "who's
                           # hot NOW" tilt without throwing the body of work away.


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
                   g.home_score AS home_pts, g.away_score AS away_pts,
                   g.tracked, g.date AS date
            FROM games g
            JOIN teams t1 ON t1.id = g.team1_id
            JOIN teams t2 ON t2.id = g.team2_id
            {clause}""",
        tuple(params),
    )
    return rows


def _team_meta(gender=None, season=None):
    """{team_id: {'name','class','gender','state'}} for teams, optionally one
    gender. `season` (an archive label) overlays each team's class with the
    class it PLAYED IN that season (helpers.seasons.team_classes_for → the
    team_class_history snapshot), so a past-season ranking groups by the class
    that was true then, not today's re-aligned class. None / current season =
    the live teams.class."""
    clause = "WHERE gender = ?" if gender else ""
    params = (gender,) if gender else ()
    meta = {
        r["id"]: {"name": r["name"], "class": r["class"], "gender": r["gender"],
                  "state": (r["state"] or "").strip()}
        for r in query(f"SELECT id, name, class, gender, state FROM teams {clause}",
                       params)
    }
    import helpers.seasons as _SEAS
    if season is not None and not _SEAS.is_current(season):
        hist = _SEAS.team_classes_for(season)
        for tid, m in meta.items():
            if tid in hist and hist[tid] is not None:
                m["class"] = hist[tid]
    return meta


def _per_team_games(games, half_life=None):
    """
    Reshape game rows into {team_id: [ {opp, pts_for, pts_against, won, w}, ... ]}.
    Each game contributes one entry to each side.

    `half_life` (games): when set, attach a recency weight `w` to each entry so a
    game HALF_LIFE games back counts half as much as the team's latest game
    (w = 0.5 ** (games_ago / half_life), newest = 1.0). Weights are TEAM-RELATIVE
    (each team's own game order) and drive the weighted means in _adjust /
    _sos_sor / score_ratings — this is the "current form" knob. Left None (default)
    every w is 1.0, so the whole engine is byte-identical to the flat season rating.
    """
    out = defaultdict(list)
    for g in games:
        h, a = g["home_id"], g["away_id"]
        hp, ap = g["home_pts"], g["away_pts"]
        d = g.get("date") or ""
        gid = g["id"]
        out[h].append({"opp": a, "pts_for": hp, "pts_against": ap, "won": hp > ap,
                       "date": d, "gid": gid, "w": 1.0})
        out[a].append({"opp": h, "pts_for": ap, "pts_against": hp, "won": ap > hp,
                       "date": d, "gid": gid, "w": 1.0})
    if half_life and half_life > 0:
        for gl in out.values():
            gl.sort(key=lambda e: (e["date"], e["gid"]))   # oldest → newest
            n = len(gl)
            for j, e in enumerate(gl):
                games_ago = (n - 1) - j
                e["w"] = 0.5 ** (games_ago / half_life)
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
    # per-team weight totals (all 1.0 → == len(gl), i.e. the flat season case)
    wsum = {t: sum(g.get("w", 1.0) for g in gl) for t, gl in team_games.items()}
    for _ in range(iters):
        newO, newD = {}, {}
        for t, gl in team_games.items():
            o_acc = d_acc = 0.0
            for g in gl:
                opp = g["opp"]
                w = g.get("w", 1.0)
                # opponent defense relative to average (how easy/hard they are)
                opp_def_edge = adjD.get(opp, league_avg) - league_avg
                opp_off_edge = adjO.get(opp, league_avg) - league_avg
                o_acc += w * (g["pts_for"] - opp_def_edge)
                d_acc += w * (g["pts_against"] - opp_off_edge)
            # phantom average-games regress thin records toward the mean
            o_acc += reg * league_avg
            d_acc += reg * league_avg
            denom = wsum[t] + reg
            newO[t] = _safe(o_acc, denom)
            newD[t] = _safe(d_acc, denom)
        adjO, adjD = newO, newD
    return adjO, adjD


def _class_adj(meta, team_ids, class_step):
    """Points bump per team from school-class, centered on the field's mean rank.

    NOTE: the bump reads the shared CLASS_ORDER ladder by label, so a '4A' in any
    state gets the same ordinal step — per-state ladders (Texas's 6A ≠ Missouri's
    ladder shape) are a down-the-line add once non-OSSAA scrapers exist. Class
    GROUPING (ranks, filters, labels) is already state-scoped via _assign_ranks."""
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
        wtot = 0.0
        for g in gl:
            w = g.get("w", 1.0)
            wtot += w
            on = adj_net.get(g["opp"], 0.0)
            opp_net += w * on
            margin = g["pts_for"] - g["pts_against"]
            margin = max(-_SOR_MARGIN_CAP, min(_SOR_MARGIN_CAP, margin))
            resume += w * (on + margin)
        sos[t] = opp_net / wtot if wtot else 0.0
        sor[t] = resume / wtot if wtot else 0.0
    return sos, sor


def _sos_bump(sos, pts_per_sd):
    """Standardized schedule-strength nudge in rating points: `pts_per_sd` points
    per standard deviation of SOS above/below the field mean. Self-centering (the
    median team gets ~0) and independent of the league's SOS scale, so the same
    weight behaves sanely whether SOS spans ±10 or ±30. 0 disables it."""
    if not sos or not pts_per_sd:
        return {t: 0.0 for t in sos}
    vals = list(sos.values())
    mean = sum(vals) / len(vals)
    sd = _safe(sum((v - mean) ** 2 for v in vals), len(vals)) ** 0.5
    if sd <= 0:
        return {t: 0.0 for t in sos}
    return {t: pts_per_sd * (sos[t] - mean) / sd for t in sos}


# ══════════════════════════════════════════════════════════════════════════════
#  SCORE VERSION  (results-only, all teams)
# ══════════════════════════════════════════════════════════════════════════════

def results_fingerprint():
    """Cheap signature of every finished-game SCORE — (count, ΣhomeScore,
    ΣawayScore, max game id). Changes iff a score is added or edited, NOT on
    event-location/tag edits. Lets the pages cache score_ratings (results-only,
    ~0.5s over the full league once the OSSAA schedule is loaded) so it survives
    an Event Editor session and the app's cache-clear storms, recomputing only
    when a score actually moves. Single aggregate query, a few ms."""
    r = query("SELECT COUNT(*) c, COALESCE(SUM(home_score),0) h, "
              "COALESCE(SUM(away_score),0) a, COALESCE(MAX(id),0) m "
              "FROM games WHERE home_score IS NOT NULL AND away_score IS NOT NULL")[0]
    return (r["c"], r["h"], r["a"], r["m"])


def score_ratings(gender=None, class_step=DEFAULT_CLASS_STEP, iters=DEFAULT_ITERS,
                  reg=None, sos_weight=None, game_ids=None,
                  season="Current", half_life=None):
    """
    Results-only power ratings for every team in `gender` (None = all).
    Returns {team_id: {...}} with, per team:
        name, class, GP, W, L,
        PPG, oPPG, MOV,                     raw box-result rates
        xPPG, xoPPG,                        opponent-adjusted O / D
        AdjNet,                             xPPG - xoPPG (neutral-floor margin)
        SOS, SOR,                           schedule difficulty / résumé
        ClassAdj,                           cross-cluster bridge bump
        Rating,            AdjNet + ClassAdj + slight SOS nudge (THE one number)
        Power,                              Rating on a 0-100 scale (50 = avg)
        Rank                                1 = best (by Rating, within gender)
    `sos_weight` is the points-per-SD schedule-strength nudge folded into Rating
    (standardized; see DEFAULT_SOS_WEIGHT); 0 reproduces pure AdjNet+Class.
    `half_life` (games) recency-weights each team's games — see form_ratings; None
    (default) is the flat, all-games-equal season rating.
    """
    # Resolve at CALL time (not as def-time defaults) so a living-recal
    # override of these module globals actually reaches production callers,
    # which pass only gender/season. Explicit reg=/sos_weight= still win.
    if reg is None:
        reg = DEFAULT_REG
    if sos_weight is None:
        sos_weight = DEFAULT_SOS_WEIGHT
    games = _finished_games(gender=gender, game_ids=game_ids, season=season)
    meta = _team_meta(gender=gender, season=season)
    tg = _per_team_games(games, half_life=half_life)
    if not tg:
        return {}

    # raw per-game offense / defense (recency-weighted when half_life is set; the
    # league average stays the flat, unweighted league scoring level — the stable
    # neutral floor the phantom-game shrinkage regresses toward). GP / W / L stay
    # true counts regardless of weighting.
    ppg, oppg, gp, wins = {}, {}, {}, {}
    tot_pts = tot_games = 0
    for t, gl in tg.items():
        n = len(gl)
        wtot = sum(g["w"] for g in gl)
        ppg[t] = _safe(sum(g["w"] * g["pts_for"] for g in gl), wtot)
        oppg[t] = _safe(sum(g["w"] * g["pts_against"] for g in gl), wtot)
        gp[t] = n
        wins[t] = sum(1 for g in gl if g["won"])
        tot_pts += sum(g["pts_for"] for g in gl)
        tot_games += n
    league_avg = _safe(tot_pts, tot_games)  # avg points scored per team-game

    adjO, adjD = _adjust(tg, ppg, oppg, league_avg, iters=iters, reg=reg)
    adj_net = {t: adjO[t] - adjD[t] for t in tg}
    sos, sor = _sos_sor(tg, adj_net)
    cadj = _class_adj(meta, list(tg.keys()), class_step)
    sbump = _sos_bump(sos, sos_weight)

    rating = {t: adj_net[t] + cadj[t] + sbump[t] for t in tg}
    power = _power_scale(rating)

    out = {}
    for t, gl in tg.items():
        out[t] = {
            "name": meta.get(t, {}).get("name", f"#{t}"),
            "class": meta.get(t, {}).get("class", "N/A"),
            "state": meta.get(t, {}).get("state", ""),
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


def form_ratings(gender=None, half_life=FORM_HALF_LIFE, game_ids=None,
                 season="Current", **kw):
    """Recency-weighted "current form" ratings: the SAME results-only engine as
    score_ratings, but each team's games are exponentially decayed by recency
    (see FORM_HALF_LIFE), so Power / Rating read "how good is this team RIGHT NOW"
    instead of over the whole season. Identical {team_id: {...}} shape and its own
    Rank (1 = hottest), so a page can drop it in beside score_ratings.

    Use it ALONGSIDE score_ratings, not instead of it. score_ratings is the résumé
    / source-of-truth ranking (SOS, SOR, seeding and predictions want the full body
    of work); form_ratings answers the different question of who is peaking now. A
    team's (Form Power − season Power) is the hot/cold signal.
    """
    return score_ratings(gender=gender, half_life=half_life, game_ids=game_ids,
                         season=season, **kw)


# points-scale fields blended between the season and form ratings. All live on the
# same neutral-floor points scale in BOTH engines (same SRS, same league_avg), so a
# convex blend is meaningful. Power is NOT here — it is re-derived from the blended
# Rating below (each engine standardizes Power to its OWN field, so blending the
# 0-100 numbers directly would be apples-to-oranges).
_BLEND_FIELDS = ("Rating", "AdjNet", "ClassAdj", "SOS", "SOR",
                 "PPG", "oPPG", "MOV", "xPPG", "xoPPG")


HYBRID_K_TRACKED = 6.0     # games-equivalent prior on the tracked-signal ramp:
                           # a team's tracked possession rating earns weight
                           # w = tracked_gp / (tracked_gp + K) in the hybrid, so
                           # the tracked signal GROWS with the tracked book
                           # instead of sitting behind a fixed constant
                           # (2026-07-18 recal §10; adopt only on a T1/T6 win).


def hybrid_ratings(gender=None, season="Current", game_ids=None,
                   k_tracked=None, scored=None, tracked=None):
    """score_ratings with each TRACKED team's Rating blended toward its
    possession-based tracked rating by tracked-games evidence.

    The tracked RatingPts (already points/game scale) is mean-aligned to the
    same teams' score Ratings (removes any calibration offset between the two
    engines), then blended per team:  (1-w)·score + w·tracked_aligned  with
    w = tgp/(tgp+k). Teams without tracked games pass through untouched, so
    the field stays comparable. Pass precomputed `scored`/`tracked` to reuse
    cached engines. Returns the scored dict shape with Rating (and hybrid_w)
    updated on tracked teams."""
    if k_tracked is None:
        k_tracked = HYBRID_K_TRACKED
    if scored is None:
        scored = score_ratings(gender=gender, season=season,
                               game_ids=(list(game_ids) if game_ids else None))
    if tracked is None:
        tracked = tracked_ratings(gender=gender, season=season,
                                  game_ids=(list(game_ids) if game_ids else None))
    out = {tid: dict(r) for tid, r in scored.items()}
    common = [t for t in tracked
              if t in out and tracked[t].get("RatingPts") is not None]
    if len(common) >= 3 and k_tracked is not None:
        m_s = sum(out[t]["Rating"] for t in common) / len(common)
        m_t = sum(tracked[t]["RatingPts"] for t in common) / len(common)
        shift = m_s - m_t
        for t in common:
            tgp = tracked[t].get("GP", 0) or 0
            w = tgp / (tgp + k_tracked) if (tgp + k_tracked) > 0 else 0.0
            r_t = tracked[t]["RatingPts"] + shift
            out[t]["Rating"] = (1.0 - w) * out[t]["Rating"] + w * r_t
            out[t]["hybrid_w"] = round(w, 3)
    return out


def blended_ratings(gender=None, form_weight=0.0, game_ids=None, season="Current",
                    **kw):
    """Season score_ratings blended toward form_ratings by `form_weight` in [0,1]:
    every points-scale field becomes (1-w)*season + w*form. This is the ONE dict a
    form-aware War Room feeds to the predictor and every simulation — they read a
    `scored` dict and never care how it was built, so blending here factors current
    form into matchups, win probabilities, season sims and bracket seeding with no
    change to those engines.

    `form_weight=0` returns the season ratings UNCHANGED (identity — the byte-for-
    byte default), so a page that leaves the knob at 0 behaves exactly as before.
    Power is recomputed and Rank reassigned on the blended Rating so a form-weighted
    bracket/prediction seeds off the blend. Non-strength fields (name/class/GP/W/L/
    state) come straight from the season row; each blended row also carries
    `SeasonPower` / `FormPower` for a hot-cold display.
    """
    w = max(0.0, min(1.0, form_weight))
    season_r = score_ratings(gender=gender, game_ids=game_ids, season=season, **kw)
    if w <= 0 or not season_r:
        return season_r
    form_r = form_ratings(gender=gender, game_ids=game_ids, season=season, **kw)

    out = {}
    for t, s in season_r.items():
        b = dict(s)
        f = form_r.get(t)
        if f:
            for k in _BLEND_FIELDS:
                if k in s and k in f:
                    b[k] = round((1 - w) * s[k] + w * f[k], 2)
            b["SeasonPower"] = s["Power"]
            b["FormPower"] = f["Power"]
        out[t] = b

    power = _power_scale({t: out[t]["Rating"] for t in out})
    for t in out:
        out[t]["Power"] = round(power[t], 1)
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
                    reg=DEFAULT_REG, game_ids=None, sos_weight=DEFAULT_SOS_WEIGHT,
                    season="Current"):
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
        Rating,            NetRtg + class bump + slight SOS nudge (THE one number)
        RatingPts,                          Rating expressed as pts/game (for spreads)
        Power, Rank
    Efficiency uses authoritative final scores for points and stats-engine
    possessions; shooting comes straight from the box.
    """
    games = _finished_games(gender=gender, tracked_only=True, game_ids=game_ids,
                            season=season)
    meta = _team_meta(gender=gender, season=season)
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
    sbump = _sos_bump(sos, sos_weight)

    rating = {t: adj_net[t] + cadj[t] + sbump[t] for t in tg}
    power = _power_scale(rating)

    out = {}
    for t, gl in tg.items():
        n = gp[t]
        pace = _safe(pace_acc[t], n)
        sh, osh = shoot[t], o_shoot[t]
        # rating expressed as points/game so spreads land in real points
        rating_pts = adj_net[t] / 100 * pace + cadj[t] + sbump[t]
        out[t] = {
            "name": meta.get(t, {}).get("name", f"#{t}"),
            "class": meta.get(t, {}).get("class", "N/A"),
            "state": meta.get(t, {}).get("state", ""),
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

def class_label(cls, state, multi):
    """Display label for a class group: '4A' in a one-state field, 'OK 4A' once
    the field spans states — a 4A in Oklahoma is not a 4A in Texas."""
    cls = cls or "N/A"
    state = (state or "").strip()
    return f"{state} {cls}" if (multi and state and cls != "N/A") else cls


def league_multi_state() -> bool:
    """Does the LEAGUE (the whole teams table) span more than one state?

    This is the ONE switch for state-qualified class labels. It must be a
    league-level fact, not a per-result-set one: a subset field (tracked teams,
    one game type's teams) can sit in a single state while the full field spans
    two — if each engine decided from its own rows, 'OK 3A' (scored) and '3A'
    (tracked) would name the same group and label-keyed filters would match
    nothing. Empty/NULL states don't count as a state."""
    return len({(r["s"] or "").strip() for r in query(
        "SELECT DISTINCT state AS s FROM teams") if (r["s"] or "").strip()}) > 1


def _assign_ranks(ratings):
    """Add a 1-based overall 'Rank' (by descending Rating within gender) plus
    'ClassRank'/'ClassOf' (the same order partitioned by each team's STATE +
    class — classes are state associations, so '4A' only groups within one
    state) to every team, in place. Also stamps 'class_lbl', the display label
    ('4A', or 'OK 4A' once the field spans states) every surface should show
    instead of raw 'class'. Both ranking systems (score_ratings +
    tracked_ratings) route through here. A one-state field (today's OSSAA-only
    data) is byte-identical to the old class-only behavior."""
    order = sorted(ratings, key=lambda t: ratings[t]["Rating"], reverse=True)
    for i, t in enumerate(order, 1):
        ratings[t]["Rank"] = i
    # Label qualification: the field's own states OR the league-level switch.
    # The league check matters for SUBSET fields (tracked teams, one game type)
    # that happen to sit in one state while the full field spans two — every
    # engine must label the same class group the same way or label-keyed
    # filters cross-match nothing ('OK 3A' vs '3A').
    _fs = {(ratings[t].get("state") or "").strip() for t in ratings}
    multi = len(_fs - {""}) > 1 or league_multi_state()
    by_class: dict = {}
    for t in order:                       # order already Rating-descending
        r = ratings[t]
        r["class_lbl"] = class_label(r.get("class"), r.get("state"), multi)
        by_class.setdefault((r.get("state") or "", r.get("class", "N/A")),
                            []).append(t)
    for ts in by_class.values():
        for i, t in enumerate(ts, 1):
            ratings[t]["ClassRank"] = i
            ratings[t]["ClassOf"] = len(ts)


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
                "class": r.get("class"), "state": r.get("state", ""),
                "class_lbl": r.get("class_lbl", r.get("class")),
                "class_rank": r.get("ClassRank"), "class_of": r.get("ClassOf"),
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
