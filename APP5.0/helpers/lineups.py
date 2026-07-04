"""
lineups.py — Observed 5-man unit ratings (who actually plays well together).

The Team Analytics page *simulates* lineups; this measures the real thing. From
the per-event 10-man on-court data it reconstructs every distinct 5-player unit
a team actually used and scores it: points produced per 100 possessions while
that exact five was on offense, points allowed per 100 while on defense, and the
net. This is the EvanMiya / DataBallR lineup explorer, computed from your own
possessions — the complement to RAPM (units vs individuals).

Possessions follow the app's locked rule (a shot or a turnover); free-throw
points are excluded from the per-possession scoring, consistent with [[rapm]].

Pure data layer: database.db + helpers.stats only. No streamlit, no numpy.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S


DEFAULT_MIN_POSS = 12   # a unit needs this many possessions to be reportable
_NET_PRIOR_POSS  = 40   # possessions of league-average (Net 0) prior mixed in


_safe = S._safe   # shared definition lives in helpers.stats


def _event_floor(game_ids=None):
    """{event_id: {team_id: frozenset(player_ids)}} for the on-court sets."""
    clause, params = S._game_filter(game_ids)
    lin = query(
        f"""SELECT gel.event_id eid, gel.player_id pid, gel.team_id tid
            FROM game_event_lineup gel
            JOIN game_events ge ON ge.id = gel.event_id
            WHERE 1=1{clause}""",
        params,
    )
    tmp = defaultdict(lambda: defaultdict(set))
    for r in lin:
        tmp[r["eid"]][r["tid"]].add(r["pid"])
    return {eid: {tid: frozenset(s) for tid, s in teams.items()}
            for eid, teams in tmp.items()}


def player_quality(gender=None, game_ids=None):
    """{pid: OVERALL rating} for the opponent adjustment (50 = league mean,
    +10 per SD). Unrated players are simply absent (treated as unknown).

    `game_ids` anchors the rating pool to the SEASON those games belong to
    (resolved to that season's full league tracked pool, so ratings stay
    league-relative): without this an archived season's players are simply
    unrated and the adjustment silently never fits. Current-season callers
    are unchanged — the resolved pool is the same league-wide default."""
    import helpers.player_ratings as PR
    pool = None
    if game_ids is not None:
        ids = list(game_ids)
        if ids:
            try:
                ph = ",".join("?" * len(ids))
                seasons = {r["season"] for r in query(
                    f"SELECT DISTINCT season FROM games WHERE id IN ({ph})",
                    tuple(ids))}
                if len(seasons) == 1:
                    import helpers.seasons as SEAS
                    pool = set(SEAS.game_pool(season=seasons.pop(), gender=gender,
                                              tracked_only=True,
                                              finished_only=False)) or set(ids)
                else:
                    pool = set(ids)
            except Exception:
                pool = set(ids)
    try:
        table = PR.player_stat_table(gender=gender, min_games=1, game_ids=pool)
    except Exception:
        return {}
    return {pid: r["OVERALL"] for pid, r in table.items()
            if r.get("OVERALL") is not None}


def _five_q(five, quality):
    """Mean rating of an on-court five (None when nobody in it is rated)."""
    vals = [quality[p] for p in five if p in quality]
    return sum(vals) / len(vals) if vals else None


_MIN_REG_POSS = 200      # possessions needed before the fitted slopes are trusted


def fit_opponent_slopes(events, floor, quality):
    """Fit the possession-level quality slopes on a sample: points ~ offense-
    five quality + defense-five quality (centered 2-var OLS over every
    possession of BOTH teams). Returns (b_off, b_def, qbar, adjusted) —
    the shared machinery behind unit_ratings and the chemistry network.
    adjusted=False (slopes 0) below _MIN_REG_POSS or on a degenerate sample."""
    reg = []
    for e in events:
        if e["event_type"] not in ("shot", "turnover"):
            continue
        off_team = e["shooter_team_id"]
        if off_team is None:
            continue
        sets = floor.get(e["id"])
        if not sets:
            continue
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make")
               else 0)
        off_five = sets.get(off_team)
        def_five = next((f for t, f in sets.items() if t != off_team), None)
        q_off = (_five_q(off_five, quality)
                 if off_five and len(off_five) == 5 else None)
        q_def = (_five_q(def_five, quality)
                 if def_five and len(def_five) == 5 else None)
        if q_off is not None and q_def is not None:
            reg.append((pts, q_off, q_def))

    b_off = b_def = 0.0
    qbar = 50.0
    adjusted = False
    if len(reg) >= _MIN_REG_POSS:
        n = len(reg)
        my = sum(r[0] for r in reg) / n
        m1 = sum(r[1] for r in reg) / n
        m2 = sum(r[2] for r in reg) / n
        s11 = s22 = s12 = s1y = s2y = 0.0
        for pts, q1, q2 in reg:
            x1, x2, y = q1 - m1, q2 - m2, pts - my
            s11 += x1 * x1
            s22 += x2 * x2
            s12 += x1 * x2
            s1y += x1 * y
            s2y += x2 * y
        det = s11 * s22 - s12 * s12
        if det > 1e-9:
            b_off = (s22 * s1y - s12 * s2y) / det
            b_def = (s11 * s2y - s12 * s1y) / det
            qbar = (m1 + m2) / 2.0
            adjusted = True
    return b_off, b_def, qbar, adjusted


def unit_ratings(team_id, game_ids=None, events=None, min_poss=DEFAULT_MIN_POSS,
                 quality=None, floor=None):
    """
    Observed 5-man unit ratings for one team, OPPONENT-ADJUSTED.

    Raw side (unchanged): ORtg / DRtg / Net per 100 possessions + the
    credibility-weighted NetAdj.

    Adjusted side: every possession's points are corrected for WHO WAS ON THE
    FLOOR for the opponent — the mean OVERALL rating of the opposing five —
    via slopes fit on THIS sample (points ~ offense-five quality +
    defense-five quality over every possession in the games, both teams). So
    a unit that fattened up on weak fives gives that edge back even when the
    weak five belonged to a good team, and holding serve against a strong
    five earns credit. Per row this adds:
        AdjORtg / AdjDRtg / AdjNet   opponent-adjusted per-100 ratings
        AdjNetAdj                    credibility-weighted adjusted net (sort key)
        ci95                         ±95% band on the adjusted net from the
                                     per-possession scoring variance — shrinks
                                     as possessions accumulate
        games_eq                     the unit's floor time in full team-games
                                     of possessions (sample size, coach units)
        adjusted                     False when the slopes couldn't be fit
                                     (thin sample / no rated opponents); the
                                     Adj* numbers then equal the raw ones.

    `quality` = {pid: 0-100 rating} (auto-fetched league-wide when omitted);
    `floor` = a precomputed _event_floor map (testability / reuse).
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if floor is None:
        floor = _event_floor(game_ids)
    if quality is None:
        quality = player_quality(game_ids=game_ids)

    # ── possession pass: per-unit (pts, opposing-five quality) + regression ──
    units = defaultdict(lambda: {"off": [], "def": []})
    reg = []                                  # (pts, q_off_five, q_def_five)
    n_games = set()
    total_poss = 0
    for e in events:
        if e["event_type"] not in ("shot", "turnover"):
            continue
        off_team = e["shooter_team_id"]
        if off_team is None:
            continue
        sets = floor.get(e["id"])
        if not sets:
            continue
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        n_games.add(e["game_id"])
        total_poss += 1
        off_five = sets.get(off_team)
        def_five = next((f for t, f in sets.items() if t != off_team), None)
        q_off = (_five_q(off_five, quality)
                 if off_five and len(off_five) == 5 else None)
        q_def = (_five_q(def_five, quality)
                 if def_five and len(def_five) == 5 else None)
        if q_off is not None and q_def is not None:
            reg.append((pts, q_off, q_def))
        five = sets.get(team_id)
        if five and len(five) == 5:
            if off_team == team_id:
                units[five]["off"].append((pts, q_def))
            else:
                units[five]["def"].append((pts, q_off))

    # ── fit the opponent slopes on this sample (2-var OLS, centered) ─────────
    b_off = b_def = 0.0
    qbar = 50.0
    adjusted = False
    if len(reg) >= _MIN_REG_POSS:
        n = len(reg)
        my = sum(r[0] for r in reg) / n
        m1 = sum(r[1] for r in reg) / n
        m2 = sum(r[2] for r in reg) / n
        s11 = s22 = s12 = s1y = s2y = 0.0
        for pts, q1, q2 in reg:
            x1, x2, y = q1 - m1, q2 - m2, pts - my
            s11 += x1 * x1
            s22 += x2 * x2
            s12 += x1 * x2
            s1y += x1 * y
            s2y += x2 * y
        det = s11 * s22 - s12 * s12
        if det > 1e-9:
            b_off = (s22 * s1y - s12 * s2y) / det
            b_def = (s11 * s2y - s12 * s1y) / det
            qbar = (m1 + m2) / 2.0
            adjusted = True

    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}
    # one full team-game of floor time, in possessions (both ends) — games_eq
    side_pg = total_poss / (2 * len(n_games)) if n_games else 0.0

    def _adj(rows, slope):
        """Per-possession points with the opposing-five quality term removed."""
        return [pts - slope * ((q if q is not None else qbar) - qbar)
                for pts, q in rows]

    def _var(vals):
        if len(vals) < 2:
            return None
        m = sum(vals) / len(vals)
        return sum((v - m) ** 2 for v in vals) / len(vals)

    out = []
    for five, u in units.items():
        n_off, n_def = len(u["off"]), len(u["def"])
        poss = n_off + n_def
        if poss < min_poss:
            continue
        off_pts = sum(p for p, _ in u["off"])
        def_pts = sum(p for p, _ in u["def"])
        ortg = 100 * _safe(off_pts, n_off)
        drtg = 100 * _safe(def_pts, n_def)
        net = ortg - drtg
        # opponent-adjusted: facing a better DEFENSIVE five earns offense
        # credit (b_def < 0), facing a better OFFENSIVE five earns defense
        # credit (b_off > 0)
        off_adj = _adj(u["off"], b_def)
        def_adj = _adj(u["def"], b_off)
        a_ortg = 100 * _safe(sum(off_adj), n_off)
        a_drtg = 100 * _safe(sum(def_adj), n_def)
        a_net = a_ortg - a_drtg
        vo, vd = _var(off_adj), _var(def_adj)
        ci = None
        if vo is not None and vd is not None:
            ci = 1.96 * 100 * (vo / n_off + vd / n_def) ** 0.5
        # Credibility-weight Net toward 0 by sample size: a 12-possession unit
        # that posts +40 is mostly noise, so it regresses hard; a 100-possession
        # unit keeps almost all of its edge.
        cred = poss / (poss + _NET_PRIOR_POSS)
        out.append({
            "players": tuple(sorted(five)),
            "names": [name_of.get(p, str(p)) for p in sorted(five)],
            "off_poss": n_off, "def_poss": n_def, "poss": poss,
            "pts_for": off_pts, "pts_against": def_pts,
            "ORtg": round(ortg, 1), "DRtg": round(drtg, 1),
            "Net": round(net, 1),
            "NetAdj": round(net * cred, 1), "cred": round(cred, 2),
            "AdjORtg": round(a_ortg, 1), "AdjDRtg": round(a_drtg, 1),
            "AdjNet": round(a_net, 1),
            "AdjNetAdj": round(a_net * cred, 1),
            "ci95": round(ci, 1) if ci is not None else None,
            "games_eq": round(poss / (2 * side_pg), 1) if side_pg else None,
            "adjusted": adjusted,
        })
    out.sort(key=lambda d: -d["AdjNetAdj"])
    return out


def custom_unit(team_id, player_ids, game_ids=None, events=None):
    """
    On-court ratings for an ARBITRARY player set — every possession where all of
    `player_ids` were on the floor together for `team_id` (a subset match, so
    picking 2–5 players works; pick 5 for an exact lineup). Returns one dict:
        off_poss, def_poss, poss, pts_for, pts_against, ORtg, DRtg, Net, PPP.
    Same possession rule and FT exclusion as unit_ratings.
    """
    want = frozenset(player_ids)
    if not want:
        return {"off_poss": 0, "def_poss": 0, "poss": 0, "pts_for": 0,
                "pts_against": 0, "ORtg": 0.0, "DRtg": 0.0, "Net": 0.0, "PPP": 0.0}
    if events is None:
        events = S.fetch_events(game_ids)
    floor = _event_floor(game_ids)
    off_poss = off_pts = def_poss = def_pts = 0
    for e in events:
        if e["event_type"] not in ("shot", "turnover"):
            continue
        off_team = e["shooter_team_id"]
        if off_team is None:
            continue
        sets = floor.get(e["id"])
        if not sets:
            continue
        five = sets.get(team_id)
        if not five or not want.issubset(five):
            continue
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        if off_team == team_id:
            off_poss += 1
            off_pts += pts
        else:
            def_poss += 1
            def_pts += pts
    ortg = 100 * _safe(off_pts, off_poss)
    drtg = 100 * _safe(def_pts, def_poss)
    return {
        "off_poss": off_poss, "def_poss": def_poss, "poss": off_poss + def_poss,
        "pts_for": off_pts, "pts_against": def_pts,
        "ORtg": round(ortg, 1), "DRtg": round(drtg, 1), "Net": round(ortg - drtg, 1),
        "PPP": round(_safe(off_pts, off_poss), 2),
    }


def player_unit_summary(team_id, game_ids=None, min_poss=DEFAULT_MIN_POSS):
    """
    Per-player rollup over the reportable units they appear in: total possessions
    and possession-weighted Net. A quick "who lifts the lineups they're in" read.
    Returns {pid: {"name","poss","wnet"}}.
    """
    units = unit_ratings(team_id, game_ids=game_ids, min_poss=min_poss)
    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}
    agg = defaultdict(lambda: {"poss": 0, "netposs": 0.0})
    for u in units:
        for p in u["players"]:
            agg[p]["poss"] += u["poss"]
            agg[p]["netposs"] += u["NetAdj"] * u["poss"]
    return {p: {"name": name_of.get(p, str(p)), "poss": a["poss"],
                "wnet": round(_safe(a["netposs"], a["poss"]), 1)}
            for p, a in agg.items()}
