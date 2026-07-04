"""
league_analytics.py — Streamlit-free, LEAGUE-WIDE cross-team analytics for the
Rankings page.

Where helpers/team_analytics.py is the single-team deep dive, this module is the
bird's-eye view: it takes the whole field at once and derives the obscure,
résumé-level and "made-up" composite stats a coach would never ask for but that
separate good teams from lucky ones.

Two data planes, mirroring the rest of the app:

  RESULTS-ONLY  (every team — only needs final scores from `games`)
      Pythagorean win expectation + luck, scoring volatility / consistency,
      clutch (close-game) record, momentum (recent vs season form), a Dominance
      index, and the who-beat-who win network.

  TRACKED  (possession data from `game_events`, tracked games only)
      `team_tracked_pack` assembles the per-team advanced stat bundle (own +
      opponent box totals, the derived `ts` pack, quarter scoring and per-quarter
      boxes) ONCE, so the page's charts and the new analytics tabs all read the
      same numbers instead of re-deriving them.

Design: pure data layer. Depends on database.db + helpers.stats +
helpers.team_ratings only — never streamlit (so pages can cache it). Rate stats
are fractions (0-1) unless the key says "pct"/"%"; a None means "undefined for
this sample" and is skipped in pool math, never treated as 0.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.stats as S
import helpers.team_ratings as TR


# Pythagorean exponent for basketball. Basketball-Reference uses 14.0 for its
# "Pythagorean wins"; Daryl Morey's classic value is 13.91. 14.0 is the standard.
PYTHAG_EXP = 14.0


_safe = S._safe   # shared definition lives in helpers.stats


# ══════════════════════════════════════════════════════════════════════════════
#  RESULTS FETCH  (every finished game, oldest first, per team)
# ══════════════════════════════════════════════════════════════════════════════

def _finished_rows(gender=None, season="Current"):
    """Finished games for a gender (both scores present), oldest first.
    `season` partitions to the active season by default (pass None for all)."""
    clause = "WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL"
    params = []
    if gender:
        clause += " AND t1.gender = ?"
        params.append(gender)
    if season is not None:
        clause += " AND g.season = ?"
        params.append(season)
    return query(
        f"""SELECT g.id, g.date, g.team1_id, g.team2_id,
                   g.home_score, g.away_score, g.tracked
            FROM games g
            JOIN teams t1 ON t1.id = g.team1_id
            {clause}
            ORDER BY g.date, g.id""",
        tuple(params),
    )


def per_team_results(gender=None, rows=None, season="Current"):
    """
    {team_id: [ {game_id, date, opp, pf, pa, margin, won, tracked}, ... ]} with
    each team's completed games oldest-first (team1 = home). One game contributes
    a row to each side. `season` partitions to the active season by default.
    """
    if rows is None:
        rows = _finished_rows(gender, season)
    out = defaultdict(list)
    for g in rows:
        h, a = g["team1_id"], g["team2_id"]
        hp, ap = g["home_score"], g["away_score"]
        out[h].append({"game_id": g["id"], "date": g["date"], "opp": a,
                       "pf": hp, "pa": ap, "margin": hp - ap, "won": hp > ap,
                       "tracked": bool(g["tracked"])})
        out[a].append({"game_id": g["id"], "date": g["date"], "opp": h,
                       "pf": ap, "pa": hp, "margin": ap - hp, "won": ap > hp,
                       "tracked": bool(g["tracked"])})
    return dict(out)


# ══════════════════════════════════════════════════════════════════════════════
#  POOL SCALING  (50 = league average, +10 per std dev — the app's convention)
# ══════════════════════════════════════════════════════════════════════════════

def _scale100(by_team, higher_better=True):
    """
    Map a {team: value} dict to a 0-100 index (50 = field average, +10 per std
    dev, clamped). None values pass through as None and are skipped in the mean /
    std. Set higher_better=False to invert (low raw value → high score).
    """
    vals = [v for v in by_team.values() if v is not None]
    if not vals:
        return {t: None for t in by_team}
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    out = {}
    for t, v in by_team.items():
        if v is None:
            out[t] = None
            continue
        z = ((v - mean) / sd) if sd else 0.0
        if not higher_better:
            z = -z
        out[t] = round(S.scale100(z), 1)
    return out


percentile = S.percentile   # shared definition lives in helpers.stats


def _streak(results):
    """(type, length) of the current W/L streak from oldest-first results."""
    if not results:
        return (None, 0)
    last = results[-1]["won"]
    n = 0
    for g in reversed(results):
        if g["won"] == last:
            n += 1
        else:
            break
    return ("W" if last else "L", n)


def _longest(results):
    """(longest_win_run, longest_loss_run) over oldest-first results."""
    lw = ll = run = 0
    prev = None
    for g in results:
        run = run + 1 if g["won"] == prev else 1
        prev = g["won"]
        if g["won"]:
            lw = max(lw, run)
        else:
            ll = max(ll, run)
    return lw, ll


# ══════════════════════════════════════════════════════════════════════════════
#  RESULTS-ONLY TEAM PACK  (Pythagoras, luck, volatility, clutch, momentum)
# ══════════════════════════════════════════════════════════════════════════════

def team_form_stats(gender=None, results=None, exp=PYTHAG_EXP, season="Current"):
    """
    A rich, results-only stat pack for EVERY team in the league (needs final
    scores only, so it covers the whole field). Per team:

      games, W, L, win_pct, PF, PA, MOV, PF_pg, PA_pg
      Volatility      population std-dev of game margin (points)
      ceiling, floor  best win margin / worst loss margin (signed)
      Pyth_wpct       Pythagorean win expectation = PF^x / (PF^x + PA^x)
      Pyth_W, Pyth_L  expected wins / losses at that rate
      Luck            actual win% − Pythagorean win%  (+ = winning the close ones)
      Luck_wins       actual wins − expected wins
      close_w/l       record in games decided by ≤ 5
      one_w/l         record in games decided by ≤ 3 (one possession)
      blow_w/l        record in games decided by ≥ 15
      close_wpct, avg_close_margin
      l5_mov, l5_wpct momentum window (last 5 games)
      mom_delta       last-5 MOV − season MOV   (>0 = heating up)
      streak_type/len, longest_win, longest_loss
      form            last-10 results as 'W'/'L' (oldest→newest)

    Plus four league-relative 0-100 composites (50 = field average, +10 / std):
      Consistency     low margin volatility ranks high
      Dominance       blend of MOV, win% and blowout-win rate
      Clutch          blend of close-game win% and avg close margin
                      (None for teams with < 2 close games)
      Momentum        recent-vs-season form (mom_delta), scaled
    """
    if results is None:
        results = per_team_results(gender, season=season)
    raw = {}
    for tid, gl in results.items():
        n = len(gl)
        if not n:
            continue
        w = sum(1 for g in gl if g["won"])
        pf = sum(g["pf"] for g in gl)
        pa = sum(g["pa"] for g in gl)
        margins = [g["margin"] for g in gl]
        mov = sum(margins) / n
        var = sum((m - mov) ** 2 for m in margins) / n
        vol = var ** 0.5
        pyth = (pf ** exp / (pf ** exp + pa ** exp)) if (pf or pa) else 0.0
        actual = w / n

        def _rec(pred):
            sub = [g for g in gl if pred(g)]
            ww = sum(1 for g in sub if g["won"])
            return ww, len(sub) - ww, sub

        cw, cl, close = _rec(lambda g: abs(g["margin"]) <= 5)
        ow, ol, _ = _rec(lambda g: abs(g["margin"]) <= 3)
        bw, bl, _ = _rec(lambda g: abs(g["margin"]) >= 15)
        last5 = gl[-5:]
        l5_mov = sum(g["margin"] for g in last5) / len(last5)
        l5_w = sum(1 for g in last5 if g["won"])
        styp, slen = _streak(gl)
        lw, ll = _longest(gl)
        blow_rate = _safe(bw, n)

        raw[tid] = {
            "games": n, "W": w, "L": n - w, "win_pct": actual,
            "PF": pf, "PA": pa, "MOV": mov,
            "PF_pg": pf / n, "PA_pg": pa / n,
            "Volatility": vol,
            "ceiling": max(margins), "floor": min(margins),
            "Pyth_wpct": pyth, "Pyth_W": pyth * n, "Pyth_L": (1 - pyth) * n,
            "Luck": actual - pyth, "Luck_wins": w - pyth * n,
            "close_w": cw, "close_l": cl,
            "one_w": ow, "one_l": ol, "blow_w": bw, "blow_l": bl,
            "close_wpct": _safe(cw, cw + cl) if (cw + cl) else None,
            "avg_close_margin": (sum(g["margin"] for g in close) / len(close))
            if close else None,
            "n_close": cw + cl,
            "l5_mov": l5_mov, "l5_wpct": l5_w / len(last5),
            "mom_delta": l5_mov - mov,
            "streak_type": styp, "streak_len": slen,
            "longest_win": lw, "longest_loss": ll,
            "blow_rate": blow_rate,
            "form": ["W" if g["won"] else "L" for g in gl[-10:]],
        }

    # ── league-relative composites ──────────────────────────────────────────
    cons = _scale100({t: r["Volatility"] for t, r in raw.items()},
                     higher_better=False)
    dom_mov = _scale100({t: r["MOV"] for t, r in raw.items()})
    dom_wp = _scale100({t: r["win_pct"] for t, r in raw.items()})
    dom_bl = _scale100({t: r["blow_rate"] for t, r in raw.items()})
    mom = _scale100({t: r["mom_delta"] for t, r in raw.items()})
    cl_wp = _scale100({t: r["close_wpct"] for t, r in raw.items()})
    cl_mg = _scale100({t: r["avg_close_margin"] for t, r in raw.items()})

    def _avg(*xs):
        vals = [x for x in xs if x is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    for t, r in raw.items():
        r["Consistency"] = cons[t]
        r["Dominance"] = _avg(dom_mov[t], dom_wp[t], dom_bl[t])
        r["Momentum"] = mom[t]
        r["Clutch"] = _avg(cl_wp[t], cl_mg[t]) if r["n_close"] >= 2 else None
    return raw


# ══════════════════════════════════════════════════════════════════════════════
#  WIN NETWORK  (who beat whom — directed edges for a node-link graph)
# ══════════════════════════════════════════════════════════════════════════════

def win_network(gender=None, rows=None, scored=None, season="Current"):
    """
    The league's results as a directed graph: an edge winner → loser for each
    head-to-head result (count = how many times). Returns
        {'nodes': [{id, name, class, power, rank, W, L, degree}],
         'edges': [{'winner', 'loser', 'count'}]}
    Only teams that have played are included. `scored` (a score_ratings dict)
    supplies power / rank / name when given.
    """
    if rows is None:
        rows = _finished_rows(gender, season)
    if scored is None:
        scored = TR.score_ratings(gender=gender, season=season)
    edges = defaultdict(int)
    wins = defaultdict(int)
    losses = defaultdict(int)
    seen = set()
    for g in rows:
        hp, ap = g["home_score"], g["away_score"]
        if hp == ap:
            continue
        win, lose = (g["team1_id"], g["team2_id"]) if hp > ap \
            else (g["team2_id"], g["team1_id"])
        edges[(win, lose)] += 1
        wins[win] += 1
        losses[lose] += 1
        seen.add(win)
        seen.add(lose)
    nodes = []
    for tid in seen:
        r = scored.get(tid, {})
        nodes.append({
            "id": tid,
            "name": r.get("name", f"#{tid}"),
            "class": r.get("class", "N/A"),
            "power": r.get("Power", 50.0),
            "rank": r.get("Rank", 999),
            "W": wins.get(tid, 0), "L": losses.get(tid, 0),
            "degree": wins.get(tid, 0) + losses.get(tid, 0),
        })
    nodes.sort(key=lambda n: n["rank"])
    edge_list = [{"winner": w, "loser": l, "count": c}
                 for (w, l), c in edges.items()]
    return {"nodes": nodes, "edges": edge_list}


# ══════════════════════════════════════════════════════════════════════════════
#  TRACKED STAT PACK  (one box pass → every per-team advanced number)
# ══════════════════════════════════════════════════════════════════════════════

def team_tracked_pack(gender=None, tracked=None, game_ids=None, season="Current"):
    """
    Assemble the per-team advanced stat bundle from tracked games ONCE, so every
    chart that needs possession / shooting / quarter data reads the same numbers.
    `game_ids` is the entitlement read-filter (see team_ratings._finished_games):
    a League-wide surface passes the pooled set so only pooled games feed it.

    Returns a dict:
      teams     [team_id, ...] ordered by tracked Power rank
      tracked   the tracked_ratings(gender) dict (ORtg/DRtg/Pace/eFG/… per team)
      own,opp   {team_id: summed finalized box}  (own totals / opponent totals)
      gp        {team_id: tracked games played}
      ts        {team_id: {derived per-team stat pack}}  — see keys below
      qfor,qagn {team_id: {quarter: points}}  scored / allowed by quarter
      tqbox     {team_id: {quarter: summed box}}  per-quarter team box
      name_of, class_of  label maps

    `ts` keys (the analytic surface used across the page):
      TS, eFG, oeFG, FGpct, oFGpct, TPpct, oTPpct, FTpct, PPS, SCE,
      TOVpct, FTr, TPAr, ORBpct, DRBpct, REBpct,
      paint_pg, paint_share, three_share, ft_share, paint3_pg,
      ast_pg, tov_pg, ast_to, ast_per_fgm, Astpct,
      stl_pg, blk_pg, oreb_pg, dreb_pg, reb_pg, pf_pg, stocks_pg,
      fga_pg, tpa_pg, poss_pg, Pace, PPP, oPPP, ORtg, DRtg, NetRtg,
      stl_r, blk_r   (steals / blocks per 100 opponent possessions)
    """
    if tracked is None:
        tracked = TR.tracked_ratings(gender=gender, game_ids=game_ids, season=season)
    games = TR._finished_games(gender=gender, tracked_only=True, game_ids=game_ids,
                               season=season)
    if not tracked or not games:
        return {"teams": [], "tracked": tracked or {}, "own": {}, "opp": {},
                "gp": {}, "ts": {}, "qfor": {}, "qagn": {}, "tqbox": {},
                "name_of": {}, "class_of": {}}

    tgb = TR._tracked_team_game_boxes(games)          # {(game_id, team_id): box}
    keys = list(S.finalize_box(S._blank_box()).keys())
    own = defaultdict(lambda: {k: 0 for k in keys})
    opp = defaultdict(lambda: {k: 0 for k in keys})
    gp = defaultdict(int)
    for g in games:
        for tid, oid in ((g["home_id"], g["away_id"]),
                         (g["away_id"], g["home_id"])):
            if tid not in tracked:
                continue
            ob_self = tgb.get((g["id"], tid))
            ob_opp = tgb.get((g["id"], oid))
            if ob_self is None:
                continue
            for k in keys:
                own[tid][k] += ob_self.get(k, 0)
                if ob_opp:
                    opp[tid][k] += ob_opp.get(k, 0)
            gp[tid] += 1

    # quarter points scored / allowed, from the raw events
    tgids = [g["id"] for g in games]
    qrows = query(
        """SELECT ge.game_id AS gid, p.team_id AS tid, ge.quarter AS q,
                  SUM(CASE WHEN ge.event_type='free_throw' THEN 1
                           WHEN ge.shot_type=3 THEN 3 ELSE 2 END) AS pts
           FROM game_events ge
           JOIN players p ON p.id = ge.primary_player_id
           WHERE ge.game_id IN ({}) AND ge.shot_result='make'
             AND ge.event_type IN ('shot','free_throw')
           GROUP BY ge.game_id, p.team_id, ge.quarter""".format(
            ",".join("?" * len(tgids))), tuple(tgids)) if tgids else []
    game_q = defaultdict(lambda: defaultdict(float))
    for qr in qrows:
        game_q[(qr["gid"], qr["tid"])][qr["q"]] += qr["pts"] or 0
    qfor = defaultdict(lambda: defaultdict(float))
    qagn = defaultdict(lambda: defaultdict(float))
    for g in games:
        for tid, oid in ((g["home_id"], g["away_id"]),
                         (g["away_id"], g["home_id"])):
            if tid not in tracked:
                continue
            for q, v in game_q.get((g["id"], tid), {}).items():
                qfor[tid][q] += v
            for q, v in game_q.get((g["id"], oid), {}).items():
                qagn[tid][q] += v

    # per-team, per-quarter box → for quarter PPP etc.
    team_of = {p["id"]: p["team_id"] for p in query("SELECT id, team_id FROM players")}
    qboxes = S.quarter_boxes(game_ids=tgids) if tgids else {}
    tqbox = defaultdict(lambda: defaultdict(lambda: {k: 0 for k in keys}))
    for pid, qmap in qboxes.items():
        tid = team_of.get(pid)
        if tid not in tracked:
            continue
        for q, bx in qmap.items():
            for k in keys:
                tqbox[tid][q][k] += bx.get(k, 0)

    meta = TR._team_meta(gender=gender)
    name_of = {t: meta.get(t, {}).get("name", str(t)) for t in tracked}
    class_of = {t: meta.get(t, {}).get("class", "N/A") for t in tracked}
    teams = sorted([t for t in tracked if t in gp],
                   key=lambda t: tracked[t]["Rank"])

    ts = {}
    for t in teams:
        o, d, n = own[t], opp[t], max(gp[t], 1)
        tr = tracked[t]
        opp_poss = S.estimate_possessions(d)
        total_pts = o["PTS"] or 1
        ts[t] = {
            "TS": S.ts(o) * 100, "eFG": S.efg(o) * 100, "oeFG": S.efg(d) * 100,
            "FGpct": S.fg_pct(o) * 100, "oFGpct": S.fg_pct(d) * 100,
            "TPpct": S.fg3_pct(o) * 100, "oTPpct": S.fg3_pct(d) * 100,
            "FTpct": S.ft_pct(o) * 100,
            "PPS": S.pps(o), "SCE": S.shot_efficiency(o),
            "TOVpct": S.tov_pct(o), "FTr": S.ftr(o), "TPAr": S.three_par(o) * 100,
            "ORBpct": 100 * S._safe(o["ORB"], o["ORB"] + d["DRB"]),
            "DRBpct": 100 * S._safe(o["DRB"], o["DRB"] + d["ORB"]),
            "REBpct": 100 * S._safe(o["ORB"] + o["DRB"],
                                    o["ORB"] + o["DRB"] + d["ORB"] + d["DRB"]),
            "paint_pg": S.paint_points(o) / n, "paint3_pg": o["3PM"] * 3 / n,
            "paint_share": 100 * S._safe(S.paint_points(o), total_pts),
            "three_share": 100 * S._safe(o["3PM"] * 3, total_pts),
            "ft_share": 100 * S._safe(o["FTM"], total_pts),
            "ast_pg": o["AST"] / n, "tov_pg": o["TOV"] / n,
            "ast_to": S._safe(o["AST"], o["TOV"]),
            "ast_per_fgm": S._safe(o["AST"], o["FGM"]),
            "Astpct": 100 * S._safe(o["AST"], o["FGM"]),
            "stl_pg": o["STL"] / n, "blk_pg": o["BLK"] / n,
            "oreb_pg": o["ORB"] / n, "dreb_pg": o["DRB"] / n,
            "reb_pg": (o["ORB"] + o["DRB"]) / n, "pf_pg": o["PF"] / n,
            "stocks_pg": (o["STL"] + o["BLK"]) / n,
            "fga_pg": o["FGA"] / n, "tpa_pg": o["3PA"] / n,
            "poss_pg": S.estimate_possessions(o) / n,
            "Pace": tr["Pace"], "PPP": tr["PPP"], "oPPP": tr["oPPP"],
            "ORtg": tr["ORtg"], "DRtg": tr["DRtg"], "NetRtg": tr["NetRtg"],
            "stl_r": 100 * S._safe(o["STL"], opp_poss),
            "blk_r": 100 * S._safe(o["BLK"], opp_poss),
        }

    # key every sub-dict by `teams` so callers can index any tracked team safely
    return {"teams": teams, "tracked": tracked,
            "own": {t: own[t] for t in teams},
            "opp": {t: opp.get(t, {k: 0 for k in keys}) for t in teams},
            "gp": {t: gp[t] for t in teams}, "ts": ts,
            "qfor": {t: dict(qfor.get(t, {})) for t in teams},
            "qagn": {t: dict(qagn.get(t, {})) for t in teams},
            "tqbox": {t: {q: dict(b) for q, b in tqbox.get(t, {}).items()}
                      for t in teams},
            "name_of": name_of, "class_of": class_of}


# ══════════════════════════════════════════════════════════════════════════════
#  EVERY-STAT TEAM TABLE  (the team analog of player_ratings.player_stat_table)
# ══════════════════════════════════════════════════════════════════════════════

# Display spec for the comprehensive team table: (label, source, key, round[, pct]).
#   source ∈ {'trk' (tracked_ratings), 'ts' (tracked_pack['ts']),
#             'form' (team_form_stats), 'scored' (score_ratings)}
#   round  = decimal places (None = leave as-is / int)
#   pct    = optional multiplier applied before rounding (1-scale → 0-100)
# Column ORDER is this list's order (hand-curated, identity first), NOT alphabetical.
# Shooting/rate columns are pulled from `ts` (already on a 0-100 scale) so the
# table never mixes fraction-scale (tracked_ratings.eFG) with percent-scale values.
_TEAM_STAT_SPEC = [
    # identity
    ("Team",      "trk",    "name",        None),
    ("Rank",      "trk",    "Rank",        None),
    ("Class",     "trk",    "class",       None),
    ("Trk GP",    "trk",    "GP",          None),
    # power / rating
    ("Power",     "trk",    "Power",       1),
    ("Rating",    "trk",    "Rating",      2),
    ("Rating pts", "trk",   "RatingPts",   2),
    # record (results-only)
    ("W",         "form",   "W",           None),
    ("L",         "form",   "L",           None),
    ("Win%",      "form",   "win_pct",     1, 100),
    ("MOV",       "form",   "MOV",         1),
    # efficiency
    ("ORtg",      "ts",     "ORtg",        1),
    ("DRtg",      "ts",     "DRtg",        1),
    ("NetRtg",    "ts",     "NetRtg",      1),
    ("Pace",      "ts",     "Pace",        1),
    ("PPP",       "ts",     "PPP",         3),
    ("Opp PPP",   "ts",     "oPPP",        3),
    ("PPS",       "ts",     "PPS",         2),
    ("SCE",       "ts",     "SCE",         1),
    # shooting — offense
    ("eFG%",      "ts",     "eFG",         1),
    ("TS%",       "ts",     "TS",          1),
    ("FG%",       "ts",     "FGpct",       1),
    ("3P%",       "ts",     "TPpct",       1),
    ("FT%",       "ts",     "FTpct",       1),
    ("3PAr",      "ts",     "TPAr",        1),
    ("FTr",       "ts",     "FTr",         2),
    # shooting — defense
    ("Opp eFG%",  "ts",     "oeFG",        1),
    ("Opp FG%",   "ts",     "oFGpct",      1),
    ("Opp 3P%",   "ts",     "oTPpct",      1),
    # scoring mix (share of points)
    ("Paint pt%", "ts",     "paint_share", 1),
    ("3PT pt%",   "ts",     "three_share", 1),
    ("FT pt%",    "ts",     "ft_share",    1),
    ("Paint/G",   "ts",     "paint_pg",    1),
    # rebounding
    ("ORB%",      "ts",     "ORBpct",      1),
    ("DRB%",      "ts",     "DRBpct",      1),
    ("REB%",      "ts",     "REBpct",      1),
    ("OREB/G",    "ts",     "oreb_pg",     1),
    ("DREB/G",    "ts",     "dreb_pg",     1),
    ("REB/G",     "ts",     "reb_pg",      1),
    # playmaking / ball security
    ("AST/G",     "ts",     "ast_pg",      1),
    ("TOV/G",     "ts",     "tov_pg",      1),
    ("AST/TO",    "ts",     "ast_to",      2),
    ("AST%",      "ts",     "Astpct",      1),
    ("TOV%",      "ts",     "TOVpct",      1),
    # defense (counting + rate)
    ("STL/G",     "ts",     "stl_pg",      1),
    ("BLK/G",     "ts",     "blk_pg",      1),
    ("Stocks/G",  "ts",     "stocks_pg",   1),
    ("STL/100",   "ts",     "stl_r",       1),
    ("BLK/100",   "ts",     "blk_r",       1),
    ("PF/G",      "ts",     "pf_pg",       1),
    # volume
    ("FGA/G",     "ts",     "fga_pg",      1),
    ("3PA/G",     "ts",     "tpa_pg",      1),
    ("Poss/G",    "ts",     "poss_pg",     1),
    # results-only composites (made-up indices, 0-100 / signed)
    ("Dominance", "form",   "Dominance",   1),
    ("Consistency", "form", "Consistency", 1),
    ("Clutch",    "form",   "Clutch",      1),
    ("Momentum",  "form",   "Momentum",    1),
    ("Luck%",     "form",   "Luck",        1, 100),
    ("Pyth W%",   "form",   "Pyth_wpct",   1, 100),
    ("Volatility", "form",  "Volatility",  1),
    # schedule
    ("SOS",       "trk",    "SOS",         2),
    ("SOR",       "trk",    "SOR",         2),
    ("ClassAdj",  "trk",    "ClassAdj",    2),
    # opponent-adjusted shooting (adj_efficiency) + forced TOs + scoring runs
    # (runs.py) — the "ext" source is built inside team_stat_table off the
    # same pool, so these stay entitlement- and season-scoped.
    ("Adj eFG%",       "ext", "AdjeFG",       1, 100),
    ("Adj Opp eFG%",   "ext", "AdjoeFG",      1, 100),
    ("Forced TOV%",    "ext", "forced_tov",   1, 100),
    ("10-0 runs/G",    "ext", "runs_made",    2),
    ("10-0 allowed/G", "ext", "runs_allowed", 2),
    ("Biggest run",    "ext", "biggest_run",  None),
]


def _fmt_cell(val, ndigits, pct):
    """Round one cell for display; pass None / non-numeric straight through."""
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if pct is not None:
            val = val * pct
        if ndigits is None:
            return val
        return round(val, ndigits)
    return val


def team_stat_table(gender=None, tracked=None, pack=None, form=None,
                    game_ids=None, season="Current"):
    """
    The team analog of player_ratings.player_stat_table: ONE flat row per TRACKED
    team holding every team stat (power, efficiency, shooting on both ends,
    rebounding, playmaking, defense, volume, results-only composites and
    schedule), in a hand-curated column order.

    Rows cover only teams with at least one tracked game (the tracked plane),
    ordered by tracked Rank. Pass the already-computed `tracked`
    (team_ratings.tracked_ratings), `pack` (team_tracked_pack) and `form`
    (team_form_stats) dicts to reuse the page's caches — any left None is built
    here for `gender`. `game_ids` is the entitlement read-filter threaded into the
    tracked aggregations (League-wide pool scoping); results-only `form` columns
    are league-wide regardless.

    Returns a list of ordered dicts (display labels as keys, insertion order =
    column order), so a caller can `pd.DataFrame(rows)` directly. Display floats
    are pre-rounded and percents pre-scaled to 0-100 — the grid does no
    formatting. None = undefined for this sample (never coerced to 0).
    """
    if tracked is None:
        tracked = TR.tracked_ratings(gender=gender, game_ids=game_ids, season=season)
    if pack is None:
        pack = team_tracked_pack(gender=gender, tracked=tracked, game_ids=game_ids,
                                 season=season)
    if form is None:
        form = team_form_stats(gender=gender, season=season)

    ts = pack.get("ts", {})
    teams = pack.get("teams", sorted(tracked, key=lambda t: tracked[t]["Rank"]))

    # "ext" columns: opponent-adjusted shooting + forced-TO rate + scoring
    # runs, built off the same pool/season so the read-filter holds. Each
    # sub-build fails soft — a missing engine leaves its columns None.
    ext = {t: {} for t in teams}
    try:
        import helpers.adj_efficiency as AE
        adj = AE.adjusted_shooting(gender=gender, game_ids=game_ids,
                                   season=season)
        for t in teams:
            a = adj.get(t)
            if a:
                ext[t]["AdjeFG"] = a.get("AdjeFG")
                ext[t]["AdjoeFG"] = a.get("AdjoeFG")
    except Exception:
        pass
    for t in teams:
        ob = pack.get("opp", {}).get(t) or {}
        opos = (ob.get("FGA") or 0) + (ob.get("TOV") or 0)
        ext[t]["forced_tov"] = (ob.get("TOV") or 0) / opos if opos else None
    try:
        import helpers.runs as RN
        import helpers.seasons as SEAS
        _rgids = (list(game_ids) if game_ids is not None
                  else SEAS.game_pool(season=season, gender=gender,
                                      tracked_only=True, finished_only=False))
        rt = RN.league_run_table(events=S.fetch_events(_rgids)) if _rgids else {}
        for t in teams:
            r = rt.get(t)
            if r:
                ext[t]["runs_made"] = r["made_pg"]
                ext[t]["runs_allowed"] = r["allowed_pg"]
                ext[t]["biggest_run"] = r["biggest"] or None
    except Exception:
        pass

    sources = {"trk": tracked, "ts": ts, "form": form, "ext": ext}

    rows = []
    for t in teams:
        row = {}
        for label, src, key, *rest in _TEAM_STAT_SPEC:
            ndigits = rest[0] if rest else None
            pct = rest[1] if len(rest) > 1 else None
            row[label] = _fmt_cell(sources.get(src, {}).get(t, {}).get(key),
                                   ndigits, pct)
        rows.append(row)
    return rows
