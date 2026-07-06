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


def _g_playtype(row, pools, d):
    """Signature action: the play_type set a player is most extreme on (vs the
    league pool of players on that same action). pct=league percentile."""
    pt = d.get("playtype")
    if not pt or pt.get("pct") is None or (pt.get("poss") or 0) < 8:
        return None
    pct, poss = pt["pct"], pt["poss"]
    if abs(pct - 50) < 20:
        return None
    label, ppp = pt["label"], pt["PPP"]
    z = (pct - 50) / 15.0
    if pct >= 50:
        txt = (f"**Go-to: {label}** — scores **{ppp:.2f} PPP** on {label.lower()} "
               f"({pct:.0f}th pctile, {poss} poss); their bread-and-butter.")
    else:
        txt = (f"**Take away the {label.lower()}** — only **{ppp:.2f} PPP** "
               f"({pct:.0f}th pctile, {poss} poss); make them beat you another way.")
    return {"text": txt, "score": abs(pct - 50) / 15.0, "z": z,
            "metric": "PlayType", "n": poss}


def _g_playstyle(row, pools, d):
    """Cross-dimension: what a player's SET produces (the shot it generates), not
    its PPP — a 3-hunting transition set, a rim-pressure call, or a set they get
    clean looks on. Reads the precomputed profile-edge for this player."""
    ps = d.get("playstyle")
    if not ps or (ps.get("poss") or 0) < 8:
        return None
    val, poss = ps.get("val"), ps["poss"]
    if val is None:
        return None
    kind, label = ps.get("kind"), ps.get("label") or ps.get("key") or "this set"
    low = label.lower()
    score = abs(val - 0.4) / 0.15
    if kind == "3pa":
        txt = (f"**Hunts 3s out of {low}** — **{val:.0%} of their {low} shots are "
               f"3s** ({poss} poss); chase shooters off the line.")
    elif kind == "rim":
        txt = (f"**{label} rim pressure** — **{val:.0%} of {low} shots are at the "
               f"rim** ({poss} poss); wall up the paint.")
    elif kind == "open":
        txt = (f"**Gets clean looks on {low}** — **{val:.0%} open** ({poss} poss); "
               f"close out harder.")
    else:
        return None
    return {"text": txt, "score": score, "z": score, "metric": "PlayStyle",
            "n": poss}


def _g_situational(row, pools, d):
    """Situational scoring: a player's PPP swing in a game situation (4th quarter /
    early) vs their OWN overall rate. Reads the precomputed situational edge — the
    'who shows up late' read, quarter-based so it needs no score-margin context."""
    sit = d.get("situational")
    if not sit or (sit.get("poss") or 0) < 8:
        return None
    delta = sit.get("delta")
    if delta is None:
        return None
    z = delta / 0.25                  # ~PPP-swing sd; manual scale like _g_playtype
    if abs(z) < MIN_Z:
        return None
    label = (sit.get("label") or "this stretch").lower()
    here, over, n = sit["ppp_here"], sit["ppp_overall"], sit["poss"]
    if delta >= 0:
        txt = (f"**Steps up in the {label}** — **{here:.2f} PPP vs {over:.2f} "
               f"overall** ({n} poss); wants the ball in the moment.")
    else:
        txt = (f"**Cools in the {label}** — **{here:.2f} PPP vs {over:.2f} "
               f"overall** ({n} poss); press them when it matters.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Situational", "n": n}


def _g_totype(row, pools, d):
    """Turnover signature: one giveaway kind dominating the tagged mix — the
    'how to force it' read for a defense."""
    tt = d.get("totype")
    if not tt or (_num(row, "TPG") or 0) < 1.5:
        return None
    share, n = tt["share"], tt["n"]
    score = (share - 0.4) / 0.15
    if score < MIN_Z:
        return None
    key, label = tt["key"], tt["label"].lower()
    if key == "pass":
        txt = (f"**Telegraphs the pass** — **{share:.0%} of their giveaways are "
               f"bad passes** ({n} tagged); jump the passing lanes and run.")
    elif key == "drive":
        txt = (f"**Strip them on the drive** — **{share:.0%} of their turnovers "
               f"come attacking off the bounce** ({n} tagged); wall up and dig "
               f"at the ball.")
    elif key == "shot_clock":
        txt = (f"**Stalls out** — **{share:.0%} of their giveaways are shot-clock "
               f"violations** ({n} tagged); deny the first option and the "
               f"possession dies on its own.")
    elif key == "held":
        txt = (f"**Ties up easy** — **{share:.0%} of their giveaways are held "
               f"balls** ({n} tagged); dig at the ball and swarm — they get "
               f"stuck with it.")
    elif key == "travel":
        txt = (f"**Happy feet** — **{share:.0%} of their giveaways are "
               f"travels/violations** ({n} tagged); crowd the catch and "
               f"pressure the handle, they rush.")
    else:
        txt = (f"**Turnover tell** — **{share:.0%} of their giveaways are "
               f"{label}** ({n} tagged); a pattern a defense can sit on.")
    return {"text": txt, "score": score, "z": score, "metric": "TO type", "n": n}


def _g_ftdraw(row, pools, d):
    """Contact rate: how often they get fouled — the free-point engine (or the
    green light to play them physical)."""
    dpg = d.get("drawn_pg")
    ff = d.get("foulft") or {}
    if dpg is None or (_num(row, "GP") or 0) < 4:
        return None
    z = _z(dpg, pools.get("drawn_pg"))
    if abs(z) < MIN_Z:
        return None
    n = int(ff.get("drawn") or 0)
    if z >= 0:
        a1 = ff.get("and1") or 0
        a1_bit = f" ({a1} and-1s)" if a1 else ""
        txt = (f"**Lives at the line** — draws **{dpg:.1f} fouls a game**"
               f"{a1_bit}, tops in the pool; fouling them is the offense's "
               f"best friend.")
    else:
        txt = (f"**Never draws contact** — just {dpg:.1f} fouls drawn a game; "
               f"play them physical, the whistle isn't coming.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Fouls drawn", "n": n}


def _g_clutchft(row, pools, d):
    """High-leverage free throws vs the season rate — who to foul late."""
    ff = d.get("foulft") or {}
    cfta, cpct, base = ff.get("cFTA") or 0, ff.get("ClutchFT%"), ff.get("FT%")
    if cfta < 6 or cpct is None or base is None:
        return None
    swing = cpct - base
    if abs(swing) < 12:
        return None
    z = swing / 10.0
    if swing > 0:
        txt = (f"**Ice water** — **{cpct:.0f}% at the line in high-leverage "
               f"moments** (vs {base:.0f}% overall, {cfta} clutch FTs); fouling "
               f"them late is a gift.")
    else:
        txt = (f"**Foul them late** — free-throw shooting falls to "
               f"**{cpct:.0f}%** under pressure (vs {base:.0f}% overall, "
               f"{cfta} clutch FTs).")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Clutch FT", "n": cfta}


def _g_pnr_role(row, pools, d):
    """Screen-action role split: markedly better as the ball-handler or as the
    screener rolling to the rim — the 'who should screen for whom' read."""
    pr = d.get("pnr_role")
    if not pr:
        return None
    hp, rp = pr["h_ppp"], pr["r_ppp"]
    gap = hp - rp
    if abs(gap) < 0.35:
        return None
    z = gap / 0.25
    n = pr["h_n"] + pr["r_n"]
    if gap > 0:
        txt = (f"**Keep the ball in their hands** — **{hp:.2f} PPP using the "
               f"screen** vs {rp:.2f} finishing as the screener "
               f"({pr['h_n']}/{pr['r_n']} poss); a handler, not a roller.")
    else:
        txt = (f"**Let them screen and finish** — **{rp:.2f} PPP as the "
               f"roller** vs {hp:.2f} with the ball off the screen "
               f"({pr['r_n']}/{pr['h_n']} poss); use them as the screener.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "PnR role", "n": n}


def _g_spacing(row, pools, d):
    """Floor gravity: the spacing index (0-100 percentile composite) at either
    extreme — bends the defense, or lets it sag."""
    sp = d.get("spacing")
    if not sp:
        return None
    idx, n = sp["index"], sp["n"]
    if idx is None:
        return None
    if idx >= 88:
        txt = (f"**Gravity** — spacing index **{idx}** (top of the league): "
               f"their positioning alone bends the defense; every teammate "
               f"gets cleaner driving lanes ({n} located shots).")
    elif idx <= 12:
        txt = (f"**Sag off** — spacing index **{idx}**: the defense can help "
               f"off them without cost; they shrink the floor for everyone "
               f"else ({n} located shots).")
    else:
        return None
    z = (idx - 50) / 15.0
    return {"text": txt, "score": abs(z), "z": z, "metric": "Spacing", "n": n}


def _g_matchup(row, pools, d):
    """Assignment difficulty: who this defender actually guards (attempt-weighted
    quality of the shooters they contested). The two reads: takes the toughest
    cover every night, or gets hidden on weak shooters AND still leaks."""
    mu = d.get("matchup")
    if not mu or (mu.get("n") or 0) < 20:
        return None
    diff = mu.get("diff")
    if diff is None:
        return None
    z = (diff - 50.0) / 10.0          # Difficulty100 is 50-mean, 10/SD by design
    n = int(mu["n"])
    ds = _num(row, "DSHOT%")
    if z >= 1.2:
        held = (f", holding them to **{ds:.0f}%**" if ds is not None else "")
        txt = (f"**Takes the toughest cover** — assignment difficulty "
               f"**{diff:.0f}** (guards the other team's best scorer "
               f"night after night){held} ({n} shots contested).")
        return {"text": txt, "score": abs(z), "z": z, "metric": "Matchup", "n": n}
    if z <= -1.2 and ds is not None:
        zd = _z(ds, pools.get("DSHOT%"))
        if zd >= 0.5:
            txt = (f"**Hidden on D — and still leaking** — guards the weakest "
                   f"assignment (difficulty {diff:.0f}) yet allows "
                   f"**{ds:.0f}%**; there is nowhere left to stash them "
                   f"({n} shots contested).")
            return {"text": txt, "score": abs(z) + zd * 0.3, "z": z,
                    "metric": "Matchup", "n": n}
    return None


def _g_impact(row, pools, d):
    """Impact vs production: the box-score line vs what the scoreboard says when
    they're on the floor (RAPM, with HoopWAR as the wins read). The two headline
    divergences: a big box line that isn't turning into team points ('stats over
    substance'), and a modest box line hiding real on-floor impact ('quiet
    winner'). RAPM is shrunk toward a box prior, so only genuine gaps fire."""
    imp = d.get("impact")
    if not imp:
        return None
    rapm, gs = imp.get("rapm"), _num(row, "GS/G")
    poss = imp.get("poss") or 0
    if rapm is None or gs is None or poss < 300 or (_num(row, "GP") or 0) < 4:
        return None
    zb = _z(gs, pools.get("GS/G"))
    zi = _z(rapm, pools.get("RAPM"))
    div = zi - zb
    war = imp.get("war")
    war_bit = f" · {war:+.1f} HoopWAR" if war is not None else ""
    n = int(poss)
    if div <= -1.8 and zb >= 0.5 and rapm < 0:
        txt = (f"**Stats over substance?** — a big box line (**{gs:.1f} Game "
               f"Score/g**) but the team is **{rapm:+.1f} pts/100** with them on"
               f"{war_bit}; the production isn't turning into team points yet "
               f"({n} poss).")
    elif div >= 1.8 and zi >= 0.5:
        txt = (f"**Quiet winner** — a modest box line ({gs:.1f} Game Score/g) "
               f"hides **{rapm:+.1f} pts/100** of on-floor impact{war_bit}; the "
               f"team is simply better with them out there ({n} poss).")
    else:
        return None
    return {"text": txt, "score": abs(div), "z": div, "metric": "Impact", "n": n}


def _g_rimdef(row, pools, d):
    """Rim protection (the split RimDef rating): FG% allowed at the rim as the
    contester. High = a wall in the paint, low = a rim worth attacking."""
    rd = _num(row, "RimDef")
    shots = _num(row, "RimDShots") or 0
    if rd is None or shots < 12:
        return None
    z = _z(rd, pools.get("RimDef"))
    if abs(z) < MIN_Z:
        return None
    allowed = _num(row, "RimDFG%")
    ab = f" ({allowed:.0f}% at the rim)" if allowed is not None else ""
    if z >= 0:
        txt = (f"**Rim protector** — walls up the paint{ab} over {int(shots)} "
               f"contested rim shots; think twice before driving on them.")
    else:
        txt = (f"**Attack the rim on them** — gives it up{ab} at the basket "
               f"({int(shots)} rim shots faced); get downhill and finish over.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Rim D",
            "n": int(shots)}


def _g_perimdef(row, pools, d):
    """Perimeter defense (the split PerimDef rating): FG% allowed on jumpers as
    the contester. High = a close-out lockdown, low = shoot over them."""
    pd = _num(row, "PerimDef")
    shots = _num(row, "PerimDShots") or 0
    if pd is None or shots < 12:
        return None
    z = _z(pd, pools.get("PerimDef"))
    if abs(z) < MIN_Z:
        return None
    allowed = _num(row, "PerimDFG%")
    ab = f" ({allowed:.0f}% on perimeter shots)" if allowed is not None else ""
    if z >= 0:
        txt = (f"**Perimeter lockdown** — smothers shooters{ab} over "
               f"{int(shots)} contested jumpers; a tough close-out cover.")
    else:
        txt = (f"**Shoot over them** — concedes{ab} on the perimeter "
               f"({int(shots)} jumpers faced); pull up and make them chase.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Perim D",
            "n": int(shots)}


def _g_rebound(row, pools, d):
    """Rebounding identity from the split ratings — elite on the offensive glass
    (second chances) or the defensive glass (closing possessions); fires on the
    stronger of the two deviations."""
    gp = _num(row, "GP") or 0
    reb = (_num(row, "OREB") or 0) + (_num(row, "DREB") or 0)
    if gp < 4 or reb < 12:
        return None
    orb, drb = _num(row, "OREBrtg"), _num(row, "DREBrtg")
    zo = _z(orb, pools.get("OREBrtg")) if orb is not None else 0.0
    zd = _z(drb, pools.get("DREBrtg")) if drb is not None else 0.0
    off_side = abs(zo) >= abs(zd)
    z = zo if off_side else zd
    if abs(z) < MIN_Z:
        return None
    opg, dpg = _num(row, "OREB/G") or 0, _num(row, "DREB/G") or 0
    if off_side:
        if z >= 0:
            txt = (f"**Second-chance machine** — elite on the offensive glass "
                   f"(**{opg:.1f} OREB/g**); box them out or they bury you on "
                   f"putbacks.")
        else:
            txt = (f"**No offensive-glass threat** — just **{opg:.1f} OREB/g**; "
                   f"safe to leak out early against them.")
    else:
        if z >= 0:
            txt = (f"**Closes possessions** — elite on the defensive glass "
                   f"(**{dpg:.1f} DREB/g**); one shot and out when they're back.")
        else:
            txt = (f"**Crash on them** — weak defensive rebounder "
                   f"(**{dpg:.1f} DREB/g**); send extra bodies to the offensive "
                   f"glass.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Rebounding",
            "n": int(reb)}


def _g_selfcreate(row, pools, d):
    """Shot-creation independence (SelfCr%): makes their own off the dribble vs
    lives off the catch — the 'deny the ball' vs 'deny the pass' read."""
    sc = _num(row, "SelfCr%")
    fga = _num(row, "FGA") or 0
    if sc is None or fga < 22:
        return None
    z = _z(sc, pools.get("SelfCr%"))
    if abs(z) < MIN_Z:
        return None
    if z >= 0:
        txt = (f"**Creates their own** — **{sc:.0f}% of their shots are self-made** "
               f"off the bounce; doesn't need a setup, so pressure the ball and "
               f"cut off the drive.")
    else:
        txt = (f"**Setup-dependent** — only **{sc:.0f}% self-created**; take away "
               f"the catch — deny the entry pass and they can't manufacture their "
               f"own look.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Shot creation",
            "n": int(fga)}


def _g_playmaking(row, pools, d):
    """Creation for others (AST%): the offense's engine to blitz off the ball, or
    a non-creator to help off. AST/TOV rides along as the ball-security note."""
    ap = _num(row, "AST%")
    gp = _num(row, "GP") or 0
    if ap is None or gp < 4:
        return None
    z = _z(ap, pools.get("AST%"))
    if abs(z) < MIN_Z:
        return None
    ato = _num(row, "AST/TOV")
    ato_bit = f" ({ato:.1f} AST/TO)" if ato is not None else ""
    if z >= 0:
        txt = (f"**Offensive engine** — assists **{ap:.0f}%** of teammate baskets "
               f"while on the floor{ato_bit}; get the ball out of their hands — "
               f"blitz the screen and make someone else create.")
    else:
        txt = (f"**Not a creator** — sets up just **{ap:.0f}%** of teammate "
               f"buckets{ato_bit}; help off them onto the real playmaker.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Playmaking",
            "n": int(gp)}


def _g_disruption(row, pools, d):
    """Defensive event creation (STOCKS/32): a ball-hawk / shot-blocker worth
    respecting. High side only — low disruption isn't a scouting tell."""
    st32 = _num(row, "STOCKS/32")
    gp = _num(row, "GP") or 0
    if st32 is None or gp < 4:
        return None
    z = _z(st32, pools.get("STOCKS/32"))
    if z < MIN_Z:
        return None
    spg, bpg = _num(row, "SPG") or 0, _num(row, "BPG") or 0
    txt = (f"**Playmaker on defense** — **{st32:.1f} stocks/32** "
           f"({spg:.1f} stl · {bpg:.1f} blk a game); punishes careless passes and "
           f"pump-fakes — don't get loose with the ball near them.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Disruption",
            "n": int(gp)}


def _g_rimfinish(row, pools, d):
    """True tap-distance finishing at the rim (Near_FG%): a downhill finisher to
    wall off early, or a shaky one to funnel inside. Uses real shot location, not
    the zone shadow."""
    nfg = _num(row, "Near_FG%")
    na = _num(row, "Near_FGA") or 0
    if nfg is None or na < 12:
        return None
    z = _z(nfg, pools.get("Near_FG%"))
    if abs(z) < MIN_Z:
        return None
    if z >= 0:
        txt = (f"**Finishes everything inside** — **{nfg:.0f}% at the rim** on "
               f"{int(na)} close attempts; wall up early, don't give them a "
               f"downhill runway.")
    else:
        txt = (f"**Shaky finisher** — just **{nfg:.0f}% at the rim** ({int(na)} "
               f"close attempts); funnel them inside and contest straight up.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Rim finish",
            "n": int(na)}


def _g_usage(row, pools, d):
    """Offensive role (USG%): the focal point who ends a big share of possessions
    vs a low-usage complementary piece — the 'who runs the offense' read."""
    u = _num(row, "USG%")
    fga = _num(row, "FGA") or 0
    if u is None or (_num(row, "GP") or 0) < 4 or fga < 22:
        return None
    z = _z(u, pools.get("USG%"))
    if abs(z) < MIN_Z:
        return None
    if z >= 0:
        txt = (f"**Focal point** — ends **{u:.0f}% of possessions** while on the "
               f"floor; the offense runs through them — load to the ball and make "
               f"someone else beat you.")
    else:
        txt = (f"**Low-usage role** — uses just **{u:.0f}%** of possessions; a "
               f"complementary piece, not a first option — help off onto the "
               f"creators.")
    return {"text": txt, "score": abs(z), "z": z, "metric": "Usage",
            "n": int(fga)}


def _g_garbage(row, pools, d):
    """Garbage-time scoring: the share of a player's points scored with the game
    already decided (|margin| ≥ 15, win prob effectively settled) vs in the clutch
    (±5). The 'the box score flatters them' read — an empty-calories padder, or a
    scorer who shows up while it's still live."""
    g = d.get("garbage")
    if not g:
        return None
    gs = g.get("garbage_share")
    if gs is None:
        return None
    z = _z(gs, pools.get("garbage_share"))
    if abs(z) < MIN_Z:
        return None
    pts, cs = int(g.get("pts") or 0), (g.get("close_share") or 0)
    if z >= 0 and gs >= 0.30:
        txt = (f"**Pads it in garbage time** — **{gs * 100:.0f}% of their points "
               f"come with the game decided** (±15+), only {cs * 100:.0f}% in "
               f"one-possession moments; the scoring line flatters them.")
    elif z <= 0:
        txt = (f"**Every bucket counts** — just **{gs * 100:.0f}% of their points "
               f"in garbage time**; {cs * 100:.0f}% come in one-possession "
               f"moments — they score when the game is still live.")
    else:
        return None
    return {"text": txt, "score": abs(z), "z": z, "metric": "Garbage time",
            "n": pts}


_GENERATORS = [_g_poe, _g_selection, _g_hand, _g_guarded, _g_q4, _g_three,
               _g_consistency, _g_defense, _g_playtype, _g_playstyle,
               _g_situational, _g_impact, _g_matchup, _g_totype, _g_ftdraw,
               _g_clutchft, _g_pnr_role, _g_spacing,
               _g_rimdef, _g_perimdef, _g_rebound,
               _g_selfcreate, _g_playmaking, _g_disruption, _g_rimfinish,
               _g_usage, _g_garbage]


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


def league_insights(table, *, guarded=None, q4=None, playtypes=None,
                    playstyles=None, situational=None, impact=None,
                    matchup=None, totypes=None, foulft=None, pnr=None,
                    spacing=None, garbage=None, top=3):
    """{player_id: [insight, ...]} — top findings per player, |z| vs the pool,
    hard-gated by sample. ``guarded`` = {pid: {'cliff','n'}}, ``q4`` =
    {pid: {'swing','n'}}, ``playtypes`` = {pid: {'key','label','PPP','pct',
    'poss','share'}}, ``playstyles`` = {pid: {'kind','key','label','val',
    'poss','PPP'}}, and ``impact`` = {pid: {'rapm','war','poss'}} (see
    ``impact_map``) are optional precomputed splits (guarded-vs-open, 4th-Q,
    signature play_type PPP, cross-dimension play-type profile, on-floor impact);
    when omitted those generators simply don't fire. Generators tied to
    play_type or x,y light up automatically once games carry that data."""
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
        if playtypes and pid in playtypes:
            d["playtype"] = playtypes[pid]
        if playstyles and pid in playstyles:
            d["playstyle"] = playstyles[pid]
        if situational and pid in situational:
            d["situational"] = situational[pid]
        if impact and pid in impact:
            d["impact"] = impact[pid]
        if matchup and pid in matchup:
            d["matchup"] = matchup[pid]
        if totypes and pid in totypes:
            d["totype"] = totypes[pid]
        if foulft and pid in foulft:
            d["foulft"] = foulft[pid]
            gp = _num(row, "GP")
            if gp:
                d["drawn_pg"] = (foulft[pid].get("drawn") or 0) / gp
        if pnr and pid in pnr:
            d["pnr_role"] = pnr[pid]
        if spacing and pid in spacing:
            d["spacing"] = spacing[pid]
        if garbage and pid in garbage:
            d["garbage"] = garbage[pid]
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
        "GS/G": col(lambda p, r: _num(r, "GS/G")),
        "RAPM": col(lambda p, r: (derived[p].get("impact") or {}).get("rapm")),
        "drawn_pg": col(lambda p, r: derived[p].get("drawn_pg")),
        "RimDef": col(lambda p, r: _num(r, "RimDef")),
        "PerimDef": col(lambda p, r: _num(r, "PerimDef")),
        "OREBrtg": col(lambda p, r: _num(r, "OREBrtg")),
        "DREBrtg": col(lambda p, r: _num(r, "DREBrtg")),
        "SelfCr%": col(lambda p, r: _num(r, "SelfCr%")),
        "AST%": col(lambda p, r: _num(r, "AST%")),
        "STOCKS/32": col(lambda p, r: _num(r, "STOCKS/32")),
        "Near_FG%": col(lambda p, r: _num(r, "Near_FG%")),
        "USG%": col(lambda p, r: _num(r, "USG%")),
        "garbage_share": col(
            lambda p, r: (derived[p].get("garbage") or {}).get("garbage_share")),
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


def named_playtype_edges(events):
    """{pid: {'key','label','PPP','pct','poss','share'}} — each player's single
    most extreme play_type set vs the league pool of players on that same action
    (the |pct-50| outlier among their tagged sets). Reads
    playtypes.player_named_playtype_percentiles; empty until shots carry a
    one-tap play_type, so it lights up as tracking fills in."""
    import helpers.playtypes as PT
    labels = dict(PT.NAMED_PLAY_TYPES)
    per = PT.player_named_playtype_percentiles(events=events)
    out = {}
    for pid, d in per.items():
        best = None
        for key, c in d.items():
            pct, poss = c.get("pct"), c.get("poss") or 0
            if pct is None or poss < 8:
                continue
            edge = abs(pct - 50)
            if best is None or edge > best[0]:
                best = (edge, key, c)
        if best is None:
            continue
        _edge, key, c = best
        out[pid] = {"key": key, "label": labels.get(key, key),
                    "PPP": c["PPP"], "pct": c["pct"], "poss": c["poss"],
                    "share": c.get("share")}
    return out


def playtype_profile_edges(events):
    """{pid: {'kind','key','label','val','poss','PPP'}} — each player's single most
    notable PROFILE tendency across their set calls (what a set PRODUCES, not its
    PPP): a set they shoot 3s on at a very high clip (kind='3pa'), attack the rim on
    (kind='rim'), or get clean looks on (kind='open'). Crosses play_type with the
    shot signals every shot already carries. Picks the one set (poss>=8) whose rate
    deviates most from a neutral ~0.4. Reads playtypes.player_playtype_shot_profiles;
    empty until shots carry a one-tap play_type + location, so it lights up as
    tracking fills in."""
    out = {}
    try:
        import helpers.playtypes as PT
        labels = dict(PT.NAMED_PLAY_TYPES)
        per = PT.player_playtype_shot_profiles(events=events)
        # (rate-key, kind, threshold, inherent-attr) — only fire when the rate
        # clears its floor AND the attribute isn't baked into the tag (a spot-up
        # being a 3, an iso/post/cut being a rim attack restates the tag, no read).
        rules = (("3PA_rate", "3pa", 0.5, "three"),
                 ("rim_rate", "rim", 0.6, "rim"),
                 ("open_rate", "open", 0.65, None))
        for pid, profiles in per.items():
            best = None  # (deviation, kind, key, val, poss, ppp, label)
            for key, prof in profiles.items():
                if (prof.get("poss") or 0) < 8:
                    continue
                for rate_key, kind, floor, attr in rules:
                    val = prof.get(rate_key)
                    if val is None or val < floor:
                        continue
                    if attr and PT.is_inherent(key, attr):
                        continue
                    dev = abs(val - 0.4)
                    if best is None or dev > best[0]:
                        best = (dev, kind, key, val, prof["poss"],
                                prof.get("PPP"), labels.get(key, key))
            if best is None:
                continue
            _dev, kind, key, val, poss, ppp, label = best
            out[pid] = {"kind": kind, "key": key, "label": label, "val": val,
                        "poss": poss, "PPP": ppp}
    except Exception:
        return {}
    return out


def turnover_type_edges(events):
    """{pid: {'key','label','share','n'}} — a player's dominant tagged giveaway
    kind (≥50% of their tagged TOs). Empty until turnovers carry a kind tag."""
    import helpers.turnovers as TOV
    per = TOV.player_turnover_types(events=events)
    out = {}
    for pid, d in per.items():
        if d["total_tagged"] < 8 or not d["rows"]:
            continue
        top = d["rows"][0]
        if top["share"] >= 0.5:
            out[pid] = {"key": top["key"], "label": top["label"],
                        "share": top["share"], "n": d["total_tagged"]}
    return out


def foul_ft_edges(events):
    """{pid: foul/FT detail} — fouls drawn, and-1s, clutch FT splits. Reads
    fouls.player_foul_ft."""
    import helpers.fouls as FL
    ff = FL.player_foul_ft(events=events)
    return {pid: {"drawn": d.get("drawn"), "and1": d.get("and1"),
                  "FTA": d.get("FTA"), "FT%": d.get("FT%"),
                  "cFTA": d.get("cFTA"), "ClutchFT%": d.get("ClutchFT%")}
            for pid, d in ff.items()}


def pnr_role_edges(events):
    """{pid: {'h_ppp','r_ppp','h_n','r_n'}} — PnR handler-vs-roller PPP where
    both roles carry real volume. Empty until shots carry play_type tags."""
    import helpers.playtypes as PT
    rs = PT.player_role_splits(events=events)
    out = {}
    for pid, d in rs.items():
        pnr = d.get("pnr")
        if not pnr:
            continue
        h, r = pnr.get("handler") or {}, pnr.get("roller") or {}
        hp, rp = h.get("poss") or 0, r.get("poss") or 0
        if hp >= 6 and rp >= 6 and h.get("PPP") is not None \
                and r.get("PPP") is not None:
            out[pid] = {"h_ppp": h["PPP"], "r_ppp": r["PPP"],
                        "h_n": hp, "r_n": rp}
    return out


def spacing_edges(events):
    """{pid: {'index','n'}} — the 0-100 floor-spacing index per qualified player.
    Empty until enough shots carry a tap (x,y) location."""
    import helpers.spacing as SP
    gids = list({e["game_id"] for e in events if e.get("game_id") is not None})
    if not gids:
        return {}
    sp = SP.league_player_spacing(None, events=events, game_ids=gids)
    return {pid: {"index": v.get("index"), "n": v.get("n")}
            for pid, v in sp.items() if v.get("index") is not None}


def matchup_edges(events, table):
    """{pid: {'diff','n'}} — attempt-weighted assignment difficulty per defender
    (matchups.matchup_difficulty's 0-100 index). Empty until shots carry
    guarded_by tags."""
    import helpers.matchups as MU
    md = MU.matchup_difficulty(events=events, table=table)
    return {pid: {"diff": v.get("Difficulty100"), "n": v.get("shots_faced")}
            for pid, v in md.items() if v.get("Difficulty100") is not None}


def impact_map(rapm=None, war=None):
    """{pid: {'rapm','war','poss'}} — merges the cached engine outputs
    (rapm.compute_rapm, hoopwar.war_table) into the miner's impact feed. Pure
    merge, so callers keep their own caching; either input may be None/{}."""
    out = {}
    for pid, r in (rapm or {}).items():
        out[pid] = {"rapm": r.get("RAPM"),
                    "poss": (r.get("off_poss") or 0) + (r.get("def_poss") or 0)}
    for pid, w in (war or {}).items():
        if pid == "_meta":
            continue
        d = out.setdefault(pid, {})
        d["war"] = w.get("WAR")
        if not d.get("poss"):
            d["poss"] = (w.get("off_poss") or 0) + (w.get("def_poss") or 0)
        if d.get("rapm") is None:
            d["rapm"] = w.get("rapm")
    return out


def garbage_edges(events):
    """{pid: {'pts','garbage_share','close_share'}} — the share of a player's points
    scored with the game decided (|margin|≥15) vs in one-possession moments. Reads
    situational.player_margin_scoring; empty until games carry scored play-by-play."""
    import helpers.situational as SIT
    return SIT.player_margin_scoring(events)


def situational_edges(events):
    """{pid: {'label','ppp_here','ppp_overall','poss','delta'}} — each player's most
    notable quarter-based scoring swing (4th-quarter clutch vs their overall). Reads
    situational.player_situational_edges; empty until games carry enough per-player
    shots, so it lights up as tracking fills in."""
    import helpers.situational as SIT
    return SIT.player_situational_edges(events)


def build_feed(table, events, *, top=3, impact=None):
    """One-call insight feed: precomputes the event-derived splits (guarded-cliff,
    Q4, signature play_type, situational) and runs the miner. ``{pid: [insight,...]}``.
    ``impact`` = a precomputed ``impact_map`` (RAPM/WAR need gender+season the
    events alone don't carry, so the caller fetches those through its own cache).
    Wrap heavy calls in a cache at the page level."""
    guarded = q4 = pt = ps = sit = mu = tt = ff = pr = sp = None
    try:
        guarded = guarded_cliffs(events)
    except Exception:
        pass
    try:
        mu = matchup_edges(events, table)
    except Exception:
        pass
    try:
        tt = turnover_type_edges(events)
    except Exception:
        pass
    try:
        ff = foul_ft_edges(events)
    except Exception:
        pass
    try:
        pr = pnr_role_edges(events)
    except Exception:
        pass
    try:
        sp = spacing_edges(events)
    except Exception:
        pass
    try:
        q4 = q4_swings(events)
    except Exception:
        pass
    try:
        pt = named_playtype_edges(events)
    except Exception:
        pass
    try:
        ps = playtype_profile_edges(events)
    except Exception:
        pass
    try:
        sit = situational_edges(events)
    except Exception:
        pass
    gt = None
    try:
        gt = garbage_edges(events)
    except Exception:
        pass
    return league_insights(table, guarded=guarded, q4=q4, playtypes=pt,
                           playstyles=ps, situational=sit, impact=impact,
                           matchup=mu, totypes=tt, foulft=ff, pnr=pr,
                           spacing=sp, garbage=gt, top=top)
