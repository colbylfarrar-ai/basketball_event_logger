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


def _safe(num, den):
    return num / den if den else 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  RESULTS FETCH  (every finished game, oldest first, per team)
# ══════════════════════════════════════════════════════════════════════════════

def _finished_rows(gender=None):
    """Finished games for a gender (both scores present), oldest first."""
    clause = "WHERE g.home_score IS NOT NULL AND g.away_score IS NOT NULL"
    params = []
    if gender:
        clause += " AND t1.gender = ?"
        params.append(gender)
    return query(
        f"""SELECT g.id, g.date, g.team1_id, g.team2_id,
                   g.home_score, g.away_score, g.tracked
            FROM games g
            JOIN teams t1 ON t1.id = g.team1_id
            {clause}
            ORDER BY g.date, g.id""",
        tuple(params),
    )


def per_team_results(gender=None, rows=None):
    """
    {team_id: [ {game_id, date, opp, pf, pa, margin, won, tracked}, ... ]} with
    each team's completed games oldest-first (team1 = home). One game contributes
    a row to each side.
    """
    if rows is None:
        rows = _finished_rows(gender)
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
        out[t] = round(max(0.0, min(100.0, 50 + 10 * z)), 1)
    return out


def percentile(value, pool, higher_better=True):
    """Percentile (0-100) of `value` within `pool` (list of numbers)."""
    vals = [v for v in pool if v is not None]
    if not vals or value is None:
        return None
    below = sum(1 for v in vals if (v < value) == higher_better)
    return round(100 * below / len(vals), 0)


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

def team_form_stats(gender=None, results=None, exp=PYTHAG_EXP):
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
        results = per_team_results(gender)
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

def win_network(gender=None, rows=None, scored=None):
    """
    The league's results as a directed graph: an edge winner → loser for each
    head-to-head result (count = how many times). Returns
        {'nodes': [{id, name, class, power, rank, W, L, degree}],
         'edges': [{'winner', 'loser', 'count'}]}
    Only teams that have played are included. `scored` (a score_ratings dict)
    supplies power / rank / name when given.
    """
    if rows is None:
        rows = _finished_rows(gender)
    if scored is None:
        scored = TR.score_ratings(gender=gender)
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

def team_tracked_pack(gender=None, tracked=None):
    """
    Assemble the per-team advanced stat bundle from tracked games ONCE, so every
    chart that needs possession / shooting / quarter data reads the same numbers.

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
        tracked = TR.tracked_ratings(gender=gender)
    games = TR._finished_games(gender=gender, tracked_only=True)
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
                           ELSE ge.shot_type END) AS pts
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
