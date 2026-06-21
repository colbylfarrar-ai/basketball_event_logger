"""
insights.py — auto-mined "what the data says" feed (the scout that reads itself).

For every player this scans the engine's splits and emits the 1-3 most SURPRISING
true findings as plain-English scouting lines — the read coaches miss. Each
candidate is scored by how far the player deviates from the league pool (a z-score)
and is GATED by a hard minimum sample, so a 2-for-3 night never produces a headline.
Every line carries its own sample size for honesty on a short HS book.

Pure read layer (numpy-free, no streamlit). Builds entirely off the keys already
in player_ratings.player_stat_table plus a couple of optional precomputed splits
(guarded-vs-open, Q4) — so it is fast (no per-player event pass) and works the
moment the table does. As more games are tracked (x,y + play_type), more generators
light up automatically.
"""
from __future__ import annotations

# Minimum |z| to count as "notable" — below this it isn't surprising enough to say.
MIN_Z = 1.0


def _pool(values):
    """(mean, sd) over a list, sd floored so z is always defined. None if thin."""
    vals = [v for v in values if v is not None]
    if len(vals) < 5:
        return None
    m = sum(vals) / len(vals)
    sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5
    return (m, sd if sd > 1e-9 else 1e-9)


def _z(val, pool):
    return (val - pool[0]) / pool[1] if (pool and val is not None) else 0.0


def _num(row, key):
    v = row.get(key)
    return v if isinstance(v, (int, float)) else None


# ── candidate generators ──────────────────────────────────────────────────────
# Each takes (row, pools, derived) and returns a candidate dict or None. `derived`
# holds this player's pre-computed combo metrics; `pools` holds (mean,sd) per metric.

def _g_poe(row, pools, d):
    """Shot-MAKING: points per shot over the league-expected for those looks."""
    poe = d.get("poe")
    if poe is None or (_num(row, "FGA") or 0) < 22:
        return None
    z = _z(poe, pools.get("poe"))
    if abs(z) < MIN_Z:
        return None
    n = int(row.get("FGA") or 0)
    if poe >= 0:
        txt = (f"**Shot-maker** — scores **{poe:+.2f} pts/shot over expected** for "
               f"the looks taken (elite finish quality, {n} FGA).")
    else:
        txt = (f"**Due to bounce back** — **{poe:+.2f} pts/shot under expected**; "
               f"the looks are fine, the makes aren't falling yet ({n} FGA).")
    return {"text": txt, "score": abs(z), "z": z, "metric": "POE", "n": n}


def _g_selection(row, pools, d):
    """Shot SELECTION: quality of the looks chosen (xPPS / ShotRating)."""
    sr = _num(row, "ShotRating")
    if sr is None or (_num(row, "FGA") or 0) < 22:
        return None
    z = _z(sr, pools.get("ShotRating"))
    if abs(z) < MIN_Z:
        return None
    n = int(row.get("FGA") or 0)
    if z >= 0:
        txt = (f"**Great shot selection** — consistently hunts high-value looks "
               f"(shot-quality {sr:.0f}, top of the league).")
    else:
        txt = (f"**Settles for tough shots** — low-value shot diet "
               f"(shot-quality {sr:.0f}); make them take the hard ones.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Selection", "n": n}


def _g_hand(row, pools, d):
    """Force-left/right: dominant vs weak floor-side FG% gap."""
    gap = d.get("hand_gap")
    dfa, wfa = _num(row, "Dom_FGA") or 0, _num(row, "Weak_FGA") or 0
    if gap is None or dfa < 6 or wfa < 6:
        return None
    z = _z(gap, pools.get("hand_gap"))
    if abs(z) < MIN_Z or gap <= 0:
        return None
    dom, weak = _num(row, "Dom_FG%"), _num(row, "Weak_FG%")
    txt = (f"**Force to the weak hand** — **{dom:.0f}% strong side vs {weak:.0f}% "
           f"weak** ({int(dfa)}/{int(wfa)} att); a {gap:.0f}-pt cliff to the off hand.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "HandGap", "n": int(dfa + wfa)}


def _g_guarded(row, pools, d):
    """Space dependence: open vs contested FG% cliff (needs precomputed cliff)."""
    cliff = d.get("guard_cliff")
    n = d.get("guard_n") or 0
    if cliff is None or n < 16:
        return None
    z = _z(cliff, pools.get("guard_cliff"))
    if abs(z) < MIN_Z:
        return None
    if cliff >= 0:
        txt = (f"**Needs space** — **{cliff:.0f} pts of FG% better open than "
               f"contested**; close out hard — wilts under pressure ({n} shots).")
    else:
        txt = (f"**Contest-proof** — barely dips when guarded ({cliff:+.0f} open vs "
               f"contested); a tough cover one-on-one ({n} shots).")
    return {"text": txt, "score": abs(z), "z": z, "metric": "GuardCliff", "n": n}


def _g_q4(row, pools, d):
    """Late-game: 4th-quarter FG% swing vs the player's own earlier rate."""
    sw = d.get("q4_swing")
    n = d.get("q4_n") or 0
    if sw is None or n < 10:
        return None
    z = _z(sw, pools.get("q4_swing"))
    if abs(z) < MIN_Z:
        return None
    if sw >= 0:
        txt = (f"**Closer** — FG% **rises {sw:+.0f} pts in the 4th** vs their own "
               f"earlier rate ({n} Q4 shots); wants the ball late.")
    else:
        txt = (f"**Fades late** — FG% **drops {sw:.0f} pts in the 4th** ({n} Q4 "
               f"shots); pressure them in crunch time.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Q4", "n": n}


def _g_three(row, pools, d):
    """Perimeter threat: 3P% with real volume."""
    tp, tpa = _num(row, "3P%"), _num(row, "3PA")
    if tp is None or (tpa or 0) < 14:
        return None
    z = _z(tp, pools.get("3P%"))
    if abs(z) < MIN_Z:
        return None
    if z >= 0:
        txt = (f"**Deadeye** — **{tp:.0f}% from three on {int(tpa)} attempts**; "
               f"do not leave them open.")
    else:
        txt = (f"**Let them shoot it** — just **{tp:.0f}% on {int(tpa)} threes**; "
               f"sag and pack the paint.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "3P%", "n": int(tpa)}


def _g_consistency(row, pools, d):
    """Floor/ceiling reliability from scoring variance."""
    cv = d.get("cv")
    # only a real rotation scorer earns a reliability read — a 1.4±1.1 PPG bench
    # line is small-number noise, not "boom-or-bust".
    if cv is None or (_num(row, "GP") or 0) < 4 or (_num(row, "PPG") or 0) < 6:
        return None
    z = _z(cv, pools.get("cv"))
    if abs(z) < MIN_Z:
        return None
    ppg, sd = _num(row, "PPG"), _num(row, "PTSsd")
    if z <= 0:
        txt = (f"**Mr. Reliable** — **{ppg:.0f} ± {sd:.0f} a night**, lowest "
               f"variance in the pool; bankable production.")
    else:
        txt = (f"**Boom-or-bust** — **{ppg:.0f} ± {sd:.0f}** (high {int(_num(row,'bestPTS') or 0)} "
               f"ceiling); live with the swings or take them out of it.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Consistency",
            "n": int(_num(row, "GP") or 0)}


def _g_defense(row, pools, d):
    """On-ball defense: FG% allowed as the contester (DSHOT%, lower = better)."""
    ds = _num(row, "DSHOT%")
    if ds is None or (_num(row, "GP") or 0) < 4:
        return None
    z = _z(ds, pools.get("DSHOT%"))
    if abs(z) < MIN_Z:
        return None
    if z <= 0:
        txt = (f"**Stopper** — holds the matchup to **{ds:.0f}% from the "
               f"field**, among the best in the league.")
    else:
        txt = (f"**Targetable on D** — shooters hit **{ds:.0f}%** against them; "
               f"hunt the matchup in the half-court.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Defense",
            "n": int(_num(row, "GP") or 0)}


_GENERATORS = [_g_poe, _g_selection, _g_hand, _g_guarded, _g_q4, _g_three,
               _g_consistency, _g_defense]


# ── pool + per-player derivation ──────────────────────────────────────────────
def _derive(row):
    """This player's combo metrics from table keys (POE, hand gap, scoring CV)."""
    pps, xpps = _num(row, "PPS"), _num(row, "xPPS")
    dom, weak = _num(row, "Dom_FG%"), _num(row, "Weak_FG%")
    ppg, sd = _num(row, "PPG"), _num(row, "PTSsd")
    return {
        "poe": (pps - xpps) if (pps is not None and xpps is not None) else None,
        "hand_gap": (dom - weak) if (dom is not None and weak is not None) else None,
        "cv": (sd / ppg) if (sd is not None and ppg) else None,
    }


def league_insights(table, *, guarded=None, q4=None, top=3):
    """{player_id: [insight, ...]} — top findings per player, |z| vs the pool,
    hard-gated by sample. ``guarded`` = {pid: {'cliff','n'}} and ``q4`` =
    {pid: {'swing','n'}} are optional precomputed splits (guarded-vs-open, 4th-Q);
    when omitted those generators simply don't fire. Generators tied to play_type
    or x,y light up automatically once games carry that data."""
    rows = list(table.items())
    derived = {}
    for pid, row in rows:
        d = _derive(row)
        if guarded and pid in guarded:
            d["guard_cliff"] = guarded[pid].get("cliff")
            d["guard_n"] = guarded[pid].get("n")
        if q4 and pid in q4:
            d["q4_swing"] = q4[pid].get("swing")
            d["q4_n"] = q4[pid].get("n")
        derived[pid] = d

    # pools over the derived + raw metrics the generators z-score against
    def col(getter):
        return _pool([getter(pid, row) for pid, row in rows])
    pools = {
        "poe": col(lambda p, r: derived[p].get("poe")),
        "hand_gap": col(lambda p, r: derived[p].get("hand_gap")),
        "cv": col(lambda p, r: derived[p].get("cv")),
        "guard_cliff": col(lambda p, r: derived[p].get("guard_cliff")),
        "q4_swing": col(lambda p, r: derived[p].get("q4_swing")),
        "ShotRating": col(lambda p, r: _num(r, "ShotRating")),
        "3P%": col(lambda p, r: _num(r, "3P%")),
        "DSHOT%": col(lambda p, r: _num(r, "DSHOT%")),
    }

    out = {}
    for pid, row in rows:
        cands = []
        for g in _GENERATORS:
            try:
                c = g(row, pools, derived[pid])
            except Exception:
                c = None
            if c:
                cands.append(c)
        cands.sort(key=lambda c: -c["score"])
        if cands:
            out[pid] = cands[:top]
    return out


def player_insights(pid, table, *, guarded=None, q4=None, top=3):
    """The insight lines for a single player (wraps league_insights)."""
    return league_insights(table, guarded=guarded, q4=q4, top=top).get(pid, [])


# ── precomputed split feeds (the event-derived generators) ────────────────────
def guarded_cliffs(events):
    """{pid: {'cliff','n'}} — pts of FG% better OPEN than CONTESTED (the richest
    live signal: guarded_by_id is well-populated). Reads stats.player_zone_guarded."""
    import helpers.stats as S
    zg = S.player_zone_guarded(events=events)
    out = {}
    for pid, d in zg.items():
        g, o = d.get("guarded", {}), d.get("open", {})
        if g.get("FGA", 0) < 8 or o.get("FGA", 0) < 8:
            continue
        out[pid] = {"cliff": round((o["pct"] - g["pct"]) * 100, 0),
                    "n": g["FGA"] + o["FGA"]}
    return out


def q4_swings(events):
    """{pid: {'swing','n'}} — 4th-quarter FG% minus the player's own Q1-3 rate.
    Reads stats.quarter_boxes; needs real shot volume in both windows."""
    import helpers.stats as S
    qb = S.quarter_boxes(events=events)
    out = {}
    for pid, byq in qb.items():
        q4 = byq.get(4)
        if not q4 or q4.get("FGA", 0) < 8:
            continue
        em = ea = 0
        for q in (1, 2, 3):
            b = byq.get(q)
            if b:
                em += b.get("FGM", 0)
                ea += b.get("FGA", 0)
        if ea < 8:
            continue
        early = em / ea if ea else 0
        late = q4["FGM"] / q4["FGA"] if q4["FGA"] else 0
        out[pid] = {"swing": round((late - early) * 100, 0), "n": q4["FGA"]}
    return out


def build_feed(table, events, *, top=3):
    """One-call insight feed: precomputes the event-derived splits (guarded-cliff,
    Q4) and runs the miner. ``{pid: [insight,...]}``. Wrap heavy calls in a cache
    at the page level."""
    guarded = q4 = None
    try:
        guarded = guarded_cliffs(events)
    except Exception:
        pass
    try:
        q4 = q4_swings(events)
    except Exception:
        pass
    return league_insights(table, guarded=guarded, q4=q4, top=top)
