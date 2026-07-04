"""
team_insights.py — auto-mined TEAM insights (the team analog of insights.py).

The player miner (helpers/insights.py) scores each player's deviations vs the
league pool; this does the same for TEAMS: every generator z-scores one team
read against the league's tracked field, gates it on sample, and emits the 1-3
most surprising true findings as plain-English lines. Same contract as the
player feed: {"text","score","z","metric","n"} per line, ranked by |z|.

Reads the engine surfaces that already exist — league_analytics.team_tracked_pack
("ts" per-team analytics + quarter points) and team_form_stats (luck, close
games, volatility, momentum) — plus optional per-team ``extras`` feeds (lineup
outliers, matchup edges, possession outcomes, chemistry gaps) that later
generators light up on when a caller supplies them.

Streamlit-free; wrap calls in a cache at the page level.
"""
from __future__ import annotations

from helpers.insights import _pool, _z, MIN_Z

MIN_GAMES = 5          # a team read needs a real schedule behind it
MIN_TRACKED = 3        # tracked-plane generators (ts) need tracked games


def _num(d, key):
    v = (d or {}).get(key)
    return v if isinstance(v, (int, float)) else None


def _bcgap(fm):
    """Blowout-vs-close win% gap for the front-runner pool (None when thin)."""
    bw, bl = fm.get("blow_w", 0) or 0, fm.get("blow_l", 0) or 0
    cw, cl = fm.get("close_w", 0) or 0, fm.get("close_l", 0) or 0
    if (bw + bl) < 3 or (cw + cl) < 3:
        return None
    return bw / (bw + bl) - cw / (cw + cl)


# ── candidate generators ──────────────────────────────────────────────────────
# Each takes (tid, ts_row, form_row, pools, d) and returns a candidate or None.
# `d` holds per-team derived values + optional extras feeds.

def _t_luck(tid, ts, fm, pools, d):
    """Record vs Pythagorean expectation — is the record flattering the team?"""
    lw = _num(fm, "Luck_wins")
    gp = _num(fm, "games") or 0
    if lw is None or gp < MIN_GAMES:
        return None
    z = _z(lw, pools.get("luck"))
    if abs(z) < MIN_Z or abs(lw) < 1.2:
        return None
    w, l = fm.get("W", 0), fm.get("L", 0)
    pw, pl = fm.get("Pyth_W"), fm.get("Pyth_L")
    if lw > 0:
        txt = (f"**Record flatters them** — {w}-{l} but the scoring margin says "
               f"**{pw:.1f}-{pl:.1f}**; they've banked **{lw:+.1f} wins of "
               f"close-game luck**. Expect regression.")
    else:
        txt = (f"**Better than the record** — {w}-{l} undersells a "
               f"**{pw:.1f}-{pl:.1f}** margin profile ({lw:+.1f} luck); the "
               f"close ones haven't bounced their way.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Luck", "n": gp}


def _t_close(tid, ts, fm, pools, d):
    """Close-game record — clutch or crumbling when it's tight."""
    cw, cl = fm.get("close_w", 0) or 0, fm.get("close_l", 0) or 0
    n = cw + cl
    wpct = _num(fm, "close_wpct")
    if wpct is None or n < 4:
        return None
    z = _z(wpct, pools.get("close_wpct"))
    if abs(z) < MIN_Z:
        return None
    if z >= 0:
        txt = (f"**Closers** — **{cw}-{cl} in games decided by ≤5**; they "
               f"execute when it tightens up. (Some of this is luck — see the "
               f"Pythagorean read.)")
    else:
        txt = (f"**Can't close** — **{cw}-{cl} in games decided by ≤5**; the "
               f"tight ones keep slipping. Late-game execution is the gap.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Close games", "n": n}


def _t_volatility(tid, ts, fm, pools, d):
    """Margin volatility — Jekyll-and-Hyde vs metronome."""
    vol = _num(fm, "Volatility")
    gp = _num(fm, "games") or 0
    if vol is None or gp < MIN_GAMES:
        return None
    z = _z(vol, pools.get("volatility"))
    if abs(z) < MIN_Z:
        return None
    ceil, floor = fm.get("ceiling"), fm.get("floor")
    if z >= 0:
        txt = (f"**Jekyll & Hyde** — the league's swingiest margins "
               f"(±{vol:.0f} a night, best {ceil:+.0f} / worst {floor:+.0f}); "
               f"which team shows up is a coin flip.")
    else:
        txt = (f"**Metronome** — the steadiest margins in the field "
               f"(±{vol:.0f}); you know exactly what you're getting, "
               f"win or lose.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Volatility", "n": gp}


def _t_momentum(tid, ts, fm, pools, d):
    """Last-5 form vs the season baseline — heating up or fading."""
    md = _num(fm, "mom_delta")
    gp = _num(fm, "games") or 0
    if md is None or gp < 8:
        return None
    z = _z(md, pools.get("momentum"))
    if abs(z) < MIN_Z or abs(md) < 4:
        return None
    if md > 0:
        txt = (f"**Heating up** — last 5 games are **{md:+.1f} points/game "
               f"better** than their season line; trending the right way "
               f"at the right time.")
    else:
        txt = (f"**Fading** — last 5 games are **{md:+.1f} points/game off** "
               f"their season line; something has slipped late.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Momentum", "n": gp}


def _t_off_leak(tid, ts, fm, pools, d):
    """Shooting-vs-offense divergence: great eFG% but mediocre ORtg (the
    possession game leaks it away) — or an offense that outperforms its
    shooting by winning the turnover/rebound battles."""
    efg, ortg = _num(ts, "eFG"), _num(ts, "ORtg")
    gp = d.get("trk_gp") or 0
    if efg is None or ortg is None or gp < MIN_TRACKED:
        return None
    div = _z(efg, pools.get("eFG")) - _z(ortg, pools.get("ORtg"))
    if abs(div) < 1.2:
        return None
    # name the leak: worse of ball security / offensive glass vs the pool
    ztov = _z(_num(ts, "TOVpct") or 0, pools.get("TOVpct"))    # higher = worse
    zorb = _z(_num(ts, "ORBpct") or 0, pools.get("ORBpct"))    # higher = better
    leak = ("turnovers" if ztov >= -zorb else "one-and-done possessions")
    if div > 0:
        txt = (f"**Shoots it, leaks it** — **{efg:.0f} eFG%** should buy more "
               f"than a {ortg:.0f} offensive rating; **{leak}** are giving the "
               f"points back. Fix the possession game, not the shots.")
    else:
        txt = (f"**Manufactures offense** — only {efg:.0f} eFG% but a "
               f"**{ortg:.0f} offensive rating**; they win the extra-possession "
               f"war (ball security + the offensive glass) and out-score "
               f"their shooting.")
    return {"text": txt, "score": abs(div), "z": div, "metric": "Off engine",
            "n": gp}


def _t_def_leak(tid, ts, fm, pools, d):
    """Contest-vs-defense divergence: forces tough shots but still bleeds points
    (second chances / fouls), or a defense that beats its contest quality."""
    oefg, drtg = _num(ts, "oeFG"), _num(ts, "DRtg")
    gp = d.get("trk_gp") or 0
    if oefg is None or drtg is None or gp < MIN_TRACKED:
        return None
    # lower is better on both — invert so positive z = good
    div = (-_z(oefg, pools.get("oeFG"))) - (-_z(drtg, pools.get("DRtg")))
    if abs(div) < 1.2:
        return None
    zdrb = _z(_num(ts, "DRBpct") or 0, pools.get("DRBpct"))    # higher = better
    zpf = _z(_num(ts, "pf_pg") or 0, pools.get("pf_pg"))       # higher = worse
    leak = ("the defensive glass" if zdrb <= zpf * -1 else "fouling")
    if div > 0:
        txt = (f"**Contests, then bleeds** — holds shooters to **{oefg:.0f} "
               f"eFG%** yet runs a {drtg:.0f} defensive rating; **{leak}** is "
               f"giving the stops back.")
    else:
        txt = (f"**Defense beats the contest** — allows {oefg:.0f} eFG% but a "
               f"**{drtg:.0f} defensive rating**; they finish stops (boards, "
               f"no fouls) better than the shot-contest numbers suggest.")
    return {"text": txt, "score": abs(div), "z": div, "metric": "Def engine",
            "n": gp}


def _t_three_dep(tid, ts, fm, pools, d):
    """Three-point dependence — how much of the scoring lives beyond the arc."""
    share, tp = _num(ts, "three_share"), _num(ts, "TPpct")
    gp = d.get("trk_gp") or 0
    if share is None or gp < MIN_TRACKED:
        return None
    z = _z(share, pools.get("three_share"))
    if abs(z) < MIN_Z:
        return None
    tp_bit = f" at {tp:.0f}%" if tp is not None else ""
    if z >= 0:
        txt = (f"**Lives and dies by the three** — **{share:.0f}% of their "
               f"points** come from deep{tp_bit}; run them off the line and "
               f"the offense has to reinvent itself.")
    else:
        txt = (f"**Doesn't need the three** — just {share:.0f}% of points from "
               f"deep; packing the paint is the only way to guard them, and "
               f"they know it.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "3PT diet", "n": gp}


def _t_quarter(tid, ts, fm, pools, d):
    """Quarter identity — the period where the game swings for (or against)
    this team, per game, vs their own average quarter."""
    net_pg = d.get("q_net_pg")           # {quarter: net pts per game}
    gp = d.get("trk_gp") or 0
    if not net_pg or gp < MIN_TRACKED:
        return None
    reg = {q: v for q, v in net_pg.items() if q in (1, 2, 3, 4)}
    if len(reg) < 4:
        return None
    avg = sum(reg.values()) / 4.0
    q, v = max(reg.items(), key=lambda kv: abs(kv[1] - avg))
    swing = v - avg
    if abs(swing) < 3.0:
        return None
    z = swing / 2.0                       # ~pts-of-swing scale, like _g_playtype
    lbl = f"Q{q}"
    if swing > 0:
        txt = (f"**{lbl} team** — they win the {lbl.lower()} by **{v:+.1f} "
               f"points/game** ({swing:+.1f} vs their other quarters); that's "
               f"where the game breaks open.")
    else:
        txt = (f"**{lbl} is the leak** — **{v:+.1f} points/game** in the "
               f"{lbl.lower()} ({swing:+.1f} vs their other quarters); "
               f"opponents make their run in the same window every night.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Quarters", "n": gp}


def _t_forced_tov(tid, ts, fm, pools, d):
    """Defensive turnover creation — the share of OPPONENT possessions this team
    ends with a takeaway (all turnovers, not just steals)."""
    ft = d.get("forced_tov")
    gp = d.get("trk_gp") or 0
    if ft is None or gp < MIN_TRACKED or (d.get("opp_poss") or 0) < 100:
        return None
    z = _z(ft, pools.get("forced_tov"))
    if abs(z) < MIN_Z:
        return None
    n = int(d.get("opp_poss") or 0)
    if z >= 0:
        txt = (f"**Turnover factory** — forces a takeaway on **{ft * 100:.0f}% "
               f"of opponent possessions**, tops in the field; the defense "
               f"feeds the offense.")
    else:
        txt = (f"**Never takes it away** — opponents cough it up on just "
               f"{ft * 100:.0f}% of trips; every stop has to be earned with a "
               f"contest and a rebound.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Takeaways", "n": n}


def _t_frontrunner(tid, ts, fm, pools, d):
    """Blowout-vs-close personality: dominant when separated but shaky in tight
    games (front-runner), or the reverse (fighter)."""
    bw, bl = fm.get("blow_w", 0) or 0, fm.get("blow_l", 0) or 0
    cw, cl = fm.get("close_w", 0) or 0, fm.get("close_l", 0) or 0
    if (bw + bl) < 3 or (cw + cl) < 3:
        return None
    gap = bw / (bw + bl) - cw / (cw + cl)
    z = _z(gap, pools.get("blow_close_gap"))
    if abs(z) < MIN_Z or abs(gap) < 0.4:
        return None
    n = bw + bl + cw + cl
    if gap > 0:
        txt = (f"**Front-runner** — **{bw}-{bl} when it's a blowout, "
               f"{cw}-{cl} when it's close**; dominant with a lead, shaky "
               f"in a dogfight.")
    else:
        txt = (f"**Built for the dogfight** — **{cw}-{cl} in close games** but "
               f"{bw}-{bl} in blowouts; they hang around and win the tight "
               f"ones, they just don't blow anyone out.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Game script",
            "n": n}


def _short(names):
    """'Jalen Smith' → 'Smith' — a five-man list that fits on one line."""
    return " · ".join((n or "").split()[-1] for n in names)


def _t_lineup(tid, ts, fm, pools, d):
    """Rotation read from observed 5-man units: an under-used unit that wins its
    minutes big, or a most-used five that's losing them. NetAdj (credibility-
    weighted net rating) so a hot 12-possession run never headlines."""
    lu = d.get("lineup")
    if not lu:
        return None
    best, used = lu.get("best"), lu.get("most_used")
    tot = lu.get("team_poss") or 0
    if not best or not used or not tot:
        return None
    if (best["players"] != used["players"] and best["NetAdj"] >= 6
            and best["poss"] / tot < 0.30):
        z = best["NetAdj"] / 4.0
        txt = (f"**Under-used unit** — {_short(best['names'])} is "
               f"**{best['NetAdj']:+.0f}/100** together but plays only "
               f"**{best['poss'] / tot:.0%}** of the tracked possessions "
               f"({best['poss']} poss); the best five isn't the usual five.")
        return {"text": txt, "score": abs(z), "z": z, "metric": "Lineups",
                "n": best["poss"]}
    if used["NetAdj"] <= -4 and best["NetAdj"] - used["NetAdj"] >= 8:
        z = used["NetAdj"] / 4.0
        txt = (f"**The go-to five is losing** — the most-used unit "
               f"({_short(used['names'])}) is **{used['NetAdj']:+.0f}/100** over "
               f"{used['poss']} possessions while {_short(best['names'])} runs "
               f"**{best['NetAdj']:+.0f}**; the rotation math wants a swap.")
        return {"text": txt, "score": abs(z), "z": z, "metric": "Lineups",
                "n": used["poss"]}
    return None


def _t_chemistry(tid, ts, fm, pools, d):
    """Pairwise chemistry: a duo whose shared minutes lift (or sink) the team
    beyond what either does alone, or two core players who never connect a
    pass. One line — the strongest of the three reads."""
    ch = d.get("chemistry")
    if not ch:
        return None
    cands = []
    best, worst = ch.get("best"), ch.get("worst")
    if worst and worst["syn"] <= -8 and worst["poss"] >= 40:
        z = worst["syn"] / 5.0
        cands.append({
            "text": (f"**This pairing drags** — {_short(worst['names'])} are "
                     f"**{worst['net']:+.0f}/100 together**, "
                     f"{abs(worst['syn']):.0f} points worse than either alone "
                     f"({worst['poss']} shared poss); stagger them."),
            "score": abs(z), "z": z, "metric": "Chemistry", "n": worst["poss"]})
    if best and best["syn"] >= 8 and best["poss"] >= 40:
        z = best["syn"] / 5.0
        cands.append({
            "text": (f"**Play them together** — {_short(best['names'])} are "
                     f"**{best['net']:+.0f}/100 as a duo**, "
                     f"{best['syn']:.0f} points better than either alone "
                     f"({best['poss']} shared poss)."),
            "score": abs(z), "z": z, "metric": "Chemistry", "n": best["poss"]})
    gap = ch.get("assist_gap")
    if gap:
        cands.append({
            "text": (f"**No connection** — {_short(gap['names'])} share "
                     f"**{gap['poss']} possessions** but have combined for "
                     f"**{gap['count']} assisted baskets to each other**; two "
                     f"core players playing separate games."),
            "score": 1.4, "z": 1.4, "metric": "Chemistry", "n": gap["poss"]})
    if not cands:
        return None
    return max(cands, key=lambda c: c["score"])


_TEAM_GENERATORS = [_t_luck, _t_close, _t_volatility, _t_momentum,
                    _t_off_leak, _t_def_leak, _t_three_dep, _t_quarter,
                    _t_lineup, _t_forced_tov, _t_frontrunner, _t_chemistry]


# ── extras builders (per-team feeds the league pools don't need) ──────────────
def lineup_extra(team_id, game_ids=None, min_poss=25):
    """{'lineup': {best, most_used, team_poss}} for one team — the observed-unit
    feed for _t_lineup. {} when no unit clears min_poss."""
    import helpers.lineups as LU
    try:
        units = LU.unit_ratings(team_id, game_ids=game_ids, min_poss=min_poss)
    except Exception:
        return {}
    if not units:
        return {}
    # read the OPPONENT-ADJUSTED net when the engine could fit it — the
    # generator's copy keeps the NetAdj key so its text stays one code path
    units = [dict(u, NetAdj=(u["AdjNetAdj"] if u.get("adjusted")
                             else u["NetAdj"])) for u in units]
    return {"lineup": {
        "best": max(units, key=lambda u: u["NetAdj"]),
        "most_used": max(units, key=lambda u: u["poss"]),
        "team_poss": sum(u["poss"] for u in units),
    }}


def chemistry_extra(team_id, game_ids=None, min_poss=40):
    """{'chemistry': {best, worst, assist_gap}} for one team — pair synergy
    (pair net minus the mean of the two solo nets) plus the weakest passing
    connection among the core. {} when no pair clears min_poss."""
    import helpers.networks as NW
    try:
        net = NW.chemistry_network(team_id, game_ids=game_ids,
                                   min_poss=min_poss)
    except Exception:
        return {}
    nodes = {n["pid"]: n for n in net.get("nodes", [])}
    edges = net.get("edges", [])
    if not edges:
        return {}
    best = worst = None
    for e in edges:
        sa, sb = nodes.get(e["a"]), nodes.get(e["b"])
        if not sa or not sb:
            continue
        rec = {**e, "syn": e["net"] - (sa["net"] + sb["net"]) / 2}
        if best is None or rec["syn"] > best["syn"]:
            best = rec
        if worst is None or rec["syn"] < worst["syn"]:
            worst = rec
    out = {"best": best, "worst": worst, "assist_gap": None}
    # passing-connection gap among the 4 highest-possession (core) players:
    # a pair sharing real floor time with (almost) no assisted baskets between
    # them, despite both being involved passers/finishers elsewhere
    try:
        import helpers.team_analytics as TA
        an = TA.assist_network(team_id, game_ids=game_ids)
        involved = {p: (an["assists"].get(p, 0) + an["assisted_fgm"].get(p, 0))
                    for p in nodes}
        core = [n["pid"] for n in net["nodes"][:4] if involved.get(n["pid"], 0) >= 8]
        cnt = {}
        for ed in an["edges"]:
            key = tuple(sorted((ed["from"], ed["to"])))
            cnt[key] = cnt.get(key, 0) + ed["count"]
        gap = None
        for e in edges:
            if e["a"] in core and e["b"] in core and e["poss"] >= 60:
                c = cnt.get((e["a"], e["b"]), 0)
                if c <= 1 and (gap is None or e["poss"] > gap["poss"]):
                    gap = {"names": e["names"], "poss": e["poss"], "count": c}
        out["assist_gap"] = gap
    except Exception:
        pass
    return {"chemistry": out}


def team_extras(team_id, game_ids=None):
    """One team's full extras bundle for the miner — merges every per-team feed
    (lineup / matchup / chemistry as they land). Each sub-builder fails soft, so
    a missing engine never blanks the rest."""
    out = {}
    out.update(lineup_extra(team_id, game_ids=game_ids))
    out.update(chemistry_extra(team_id, game_ids=game_ids))
    return out


# ── the miner ─────────────────────────────────────────────────────────────────
def team_insight_feed(gender=None, season="Current", game_ids=None, *,
                      pack=None, form=None, extras=None, top=3):
    """{team_id: [insight, ...]} — the 1-``top`` most surprising team reads,
    |z| vs the league's tracked field, hard-gated by sample.

    Pass the page's cached ``pack`` (league_analytics.team_tracked_pack) and
    ``form`` (team_form_stats) to skip recomputing; ``extras`` = {team_id:
    {...}} feeds for generators added by later surfaces (lineup / matchup /
    possession / chemistry) — absent keys simply don't fire."""
    import helpers.league_analytics as LA
    if pack is None:
        pack = LA.team_tracked_pack(gender=gender, game_ids=game_ids,
                                    season=season)
    if form is None:
        form = LA.team_form_stats(gender=gender, season=season)
    ts_all, gp_all = pack.get("ts", {}), pack.get("gp", {})
    teams = pack.get("teams", [])
    if not teams:
        return {}

    # per-team derived (quarter net per game, forced-TO rate, extras passthrough)
    derived = {}
    for t in teams:
        gp = gp_all.get(t, 0)
        qf, qa = pack.get("qfor", {}).get(t, {}), pack.get("qagn", {}).get(t, {})
        q_net = {q: (qf.get(q, 0) - qa.get(q, 0)) / gp
                 for q in set(qf) | set(qa)} if gp else {}
        d = {"trk_gp": gp, "q_net_pg": q_net}
        ob = pack.get("opp", {}).get(t) or {}
        opp_poss = (ob.get("FGA") or 0) + (ob.get("TOV") or 0)
        d["opp_poss"] = opp_poss
        d["forced_tov"] = (ob.get("TOV") or 0) / opp_poss if opp_poss else None
        if extras and t in extras:
            d.update(extras[t])
        derived[t] = d

    # league pools the generators z-score against
    def col(getter):
        return _pool([getter(t) for t in teams])
    pools = {
        "luck": col(lambda t: _num(form.get(t), "Luck_wins")),
        "close_wpct": col(lambda t: _num(form.get(t), "close_wpct")),
        "volatility": col(lambda t: _num(form.get(t), "Volatility")),
        "momentum": col(lambda t: _num(form.get(t), "mom_delta")),
        "eFG": col(lambda t: _num(ts_all.get(t), "eFG")),
        "ORtg": col(lambda t: _num(ts_all.get(t), "ORtg")),
        "oeFG": col(lambda t: _num(ts_all.get(t), "oeFG")),
        "DRtg": col(lambda t: _num(ts_all.get(t), "DRtg")),
        "TOVpct": col(lambda t: _num(ts_all.get(t), "TOVpct")),
        "ORBpct": col(lambda t: _num(ts_all.get(t), "ORBpct")),
        "DRBpct": col(lambda t: _num(ts_all.get(t), "DRBpct")),
        "pf_pg": col(lambda t: _num(ts_all.get(t), "pf_pg")),
        "three_share": col(lambda t: _num(ts_all.get(t), "three_share")),
        "forced_tov": col(lambda t: derived[t].get("forced_tov")),
        "blow_close_gap": col(lambda t: _bcgap(form.get(t) or {})),
    }

    out = {}
    for t in teams:
        ts, fm, d = ts_all.get(t, {}), form.get(t, {}), derived[t]
        cands = []
        for g in _TEAM_GENERATORS:
            try:
                c = g(t, ts, fm, pools, d)
            except Exception:
                c = None
            if c:
                cands.append(c)
        cands.sort(key=lambda c: -c["score"])
        if cands:
            out[t] = cands[:top]
    return out


def team_insights(team_id, gender=None, season="Current", game_ids=None, *,
                  pack=None, form=None, extras=None, top=3):
    """The insight lines for a single team (wraps team_insight_feed)."""
    return team_insight_feed(gender=gender, season=season, game_ids=game_ids,
                             pack=pack, form=form, extras=extras,
                             top=top).get(team_id, [])
