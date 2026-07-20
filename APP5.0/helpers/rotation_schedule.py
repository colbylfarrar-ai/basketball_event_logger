"""
rotation_schedule.py — the Suggested Rotation: preset fives laid across the clock.

The rotation optimizer (lineup_projection.optimize_minutes) answers "how many
minutes should each player get". It does NOT answer the question a coach
actually writes on a card: **who is on the floor, minute by minute**. This module
answers that — it schedules the team's PRESET FIVES across sixteen 2-minute
blocks of a 32-minute game.

Two layers, deliberately:

  FRAME (the basketball)   Fixed roles per block. You open the game and the
                           second half with your anchor five, you close with it,
                           and the blocks between are free for the bench/lens
                           fives. No engine gets to decide that starters sit the
                           tip — that isn't an optimization, it's a convention.

  CHOICE (the engine)      Inside the free blocks, pick the five that best covers
                           whichever of the team's ~4 SIGNATURE win stats has had
                           the least floor time so far. Coverage is the objective
                           because minute TOTALS are already fixed by the
                           optimizer — reordering the same 160 player-minutes
                           cannot change the aggregate projected line. What
                           ordering DOES change is which five is together, and a
                           five either hits a signature goal or it doesn't. So
                           the honest objective is: don't leave a win stat
                           uncovered for 32 straight minutes.

Feasibility is a hard constraint, not a preference: every block spends exactly
five player-blocks, a player is never scheduled past their optimizer budget, and
a player whose remaining budget equals the remaining blocks is force-played. A
preset five that no longer fits the budget is REPAIRED (swap the spent players
for the highest-remaining-budget replacements) rather than dropped, so the
schedule keeps its preset identity to the end instead of collapsing into an
anonymous "whoever is left" five.

Pure data layer — db-free except through the injected `project` callable, so the
scheduler itself is unit-testable with a fake projector. No streamlit.
"""
from __future__ import annotations

GAME_MIN   = 32.0
BLOCK      = 2.0
N_BLOCKS   = 16          # 32 minutes in 2-minute blocks
SLOTS      = 5           # players on the floor
QUARTER    = 4           # blocks per quarter (8 minutes)

# Role per block — the FRAME. Anchor = your objective five (best overall / best
# signature fit, whichever lens the surface is showing); Close = the same five
# with the game on the line; Free = the engine chooses.
ANCHOR, FREE, CLOSE = "anchor", "free", "close"
FRAME = ([ANCHOR] * 2 + [FREE] * 6        # Q1 open · rest of Q1 + all of Q2
         + [ANCHOR] * 2 + [FREE] * 4      # Q3 open (out of the half) · into Q4
         + [CLOSE] * 2)                   # the last 4 minutes

# Scoring weights. A signature-goal hit on a fully-uncovered stat is worth ~1.0,
# so these set what a point of Net and a star's presence are worth against that.
NET_W    = 0.06     # per projected Net point (+10 Net ≈ 0.6 of a goal hit)
STAR_W   = 0.45     # having ≥1 star on the floor (the stagger rule, as a nudge)
PRESET_W = 0.25     # prefer an INTACT preset five over a repaired one
# Coaches sub in bunches, not every dead ball. Without a stickiness term the
# block-by-block argmax churns the floor every two minutes and the plan reads
# like a spreadsheet instead of a rotation — this buys continuity unless the
# alternative is clearly better.
STAY_W   = 0.40     # keeping the five that's already on the floor


# ══════════════════════════════════════════════════════════════════════════════
#  BUDGET
# ══════════════════════════════════════════════════════════════════════════════

def blocks_from_minutes(minutes):
    """{pid: minutes} → {pid: whole 2-minute blocks}, forced to sum to exactly
    N_BLOCKS·SLOTS so the schedule can spend every slot and no more."""
    b = {p: int(round(m / BLOCK)) for p, m in minutes.items() if (m or 0) > 0}
    b = {p: n for p, n in b.items() if n > 0}
    if not b:
        return {}
    need = N_BLOCKS * SLOTS
    order = sorted(b, key=lambda p: -b[p])
    guard = 0
    while sum(b.values()) != need and guard < 1000:
        guard += 1
        tot = sum(b.values())
        if tot > need:
            # trim the largest that can still afford it
            cand = [p for p in order if b[p] > 1]
            if not cand:
                break
            b[max(cand, key=lambda p: b[p])] -= 1
        else:
            b[min(order, key=lambda p: b[p])] += 1
    return b


# ══════════════════════════════════════════════════════════════════════════════
#  CANDIDATE FIVES
# ══════════════════════════════════════════════════════════════════════════════

def preset_fives(ctxp, rotation, team_id, gender=None, spacing_map=None):
    """The team's preset lineups, restricted to the players actually in the
    rotation. Returns [{"pids": [..], "labels": [..]}]; [] when the rotation is
    too shallow or the ratings table is unavailable.

    Restricting to the rotation matters: a preset built from the full roster can
    name a player the optimizer gave zero minutes, and a schedule that opens with
    someone who isn't in the rotation is not a schedule a coach can run."""
    table = ctxp.get("table") or {}
    rows = [dict(r, _pid=p) for p, r in table.items() if p in set(rotation)]
    if len(rows) < SLOTS:
        return []
    try:
        import helpers.team_analytics as TA
        presets = TA.preset_lineups(rows, None, team_id,
                                    spacing_map=spacing_map, predict=False)
    except Exception:
        return []
    return [{"pids": [x["pid"] for x in p["players"]], "labels": list(p["labels"])}
            for p in presets]


def _repair(five, pool, must):
    """Make a five spendable this block out of `pool` ({pid: blocks left}): drop
    the players who are spent, force in the must-play players, refill from the
    deepest remaining budgets. Returns 5 pids, or None when the pool can't field
    a five at all."""
    avail = [p for p, n in pool.items() if n > 0]
    if len(avail) < SLOTS:
        return None
    out = [p for p in must if p in avail][:SLOTS]
    for p in sorted((x for x in five if x in avail), key=lambda x: -pool[x]):
        if len(out) >= SLOTS:
            break
        if p not in out:
            out.append(p)
    for p in sorted(avail, key=lambda x: -pool[x]):
        if len(out) >= SLOTS:
            break
        if p not in out:
            out.append(p)
    return out[:SLOTS] if len(out) == SLOTS else None


def _split_pools(budget, anchor):
    """Split each player's block budget into an ANCHOR pool (the six framed
    blocks — both half-openings and the close) and a FREE pool (everything else).

    Splitting up front is what makes the schedule provably runnable: each pool
    holds exactly `blocks × 5` player-blocks, so a greedy walk that force-plays
    anyone whose remaining budget equals the remaining blocks can never strand a
    slot. Scheduling one shared budget instead lets the free window spend the
    anchor five's last minutes, and the second half opens with a group the coach
    never picked. An anchor player short of six blocks contributes what they
    have; the shortfall is reserved to the deepest remaining players, who become
    that five's substitutes."""
    a_blocks = sum(1 for r in FRAME if r != FREE)
    reserve = {}
    for p in anchor:
        reserve[p] = min(budget.get(p, 0), a_blocks)
    short = a_blocks * SLOTS - sum(reserve.values())
    for p in sorted(budget, key=lambda x: -budget[x]):
        if short <= 0:
            break
        room = min(budget[p], a_blocks) - reserve.get(p, 0)
        if room <= 0:
            continue
        take = min(short, room)
        reserve[p] = reserve.get(p, 0) + take
        short -= take
    residual = {p: budget[p] - reserve.get(p, 0) for p in budget}
    return ({p: n for p, n in reserve.items() if n > 0},
            {p: n for p, n in residual.items() if n > 0})


# ══════════════════════════════════════════════════════════════════════════════
#  SCORING
# ══════════════════════════════════════════════════════════════════════════════

def _hits(line, goals):
    """The signature goal KEYS a projected line reaches."""
    out = set()
    for g in goals:
        v = line.get(g["key"])
        if v is None:
            continue
        if (v >= g["target"]) if g["win_high"] else (v <= g["target"]):
            out.add(g["key"])
    return out


def _goal_weights(goals, d_by_key):
    """Effect-size weights normalized so the strongest signature stat = 1.0."""
    w = {g["key"]: abs(d_by_key.get(g["key"], 1.0)) or 1.0 for g in goals}
    top = max(w.values()) if w else 1.0
    return {k: v / top for k, v in w.items()}


def _score(five, hit, net, coverage, gw, stars, intact, prev=None):
    """Block score: cover the least-covered signature stats, with Net, star
    presence, preset integrity and staying on the floor as tie-breakers."""
    sig = 0.0
    for k in hit:
        scarce = max(0.0, 1.0 - coverage.get(k, 0.0) / GAME_MIN)
        sig += gw.get(k, 0.0) * scarce
    s = sig + NET_W * (net or 0.0)
    if stars and any(p in stars for p in five):
        s += STAR_W
    if intact:
        s += PRESET_W
    if prev is not None:
        s += STAY_W * (len(frozenset(five) & prev) / SLOTS)
    return s


# ══════════════════════════════════════════════════════════════════════════════
#  THE SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════

def _label_for(pids, preset_index):
    """Name a five: its preset labels when it IS a preset, the nearest preset
    (4-of-5 overlap) marked adjusted otherwise, else a plain rotation five."""
    key = frozenset(pids)
    exact = preset_index.get(key)
    if exact:
        return " / ".join(exact[:2]), True
    best, overlap = None, 0
    for k, labels in preset_index.items():
        n = len(key & k)
        if n > overlap:
            best, overlap = labels, n
    if best and overlap >= 4:
        return f"{best[0]} (adjusted)", False
    return "Rotation five", False


def suggest_rotation(team_id, ctxp, opt, presets=None, project=None,
                     game_ids=None):
    """Lay the team's preset fives across a 32-minute game.

    ``ctxp``   helpers.lineup_projection.build_context result
    ``opt``    optimize_minutes result (its ``minutes`` are the budget)
    ``presets`` [{"pids","labels"}] — defaults to preset_fives(...)
    ``project`` five(list) → {"line", "net_blended"} — defaults to the shared
                lineup engine (injectable so the scheduler is testable db-free)

    Returns {"blocks", "segments", "stints", "units", "coverage", "minutes",
    "target_minutes", "uncovered"} or {"gated": reason}.
    """
    minutes = (opt or {}).get("minutes") or {}
    budget = blocks_from_minutes(minutes)
    if len(budget) < SLOTS:
        return {"gated": "need at least five players with projected minutes"}

    rotation = list(budget)
    goals = ctxp.get("goals") or []
    gw = _goal_weights(goals, ctxp.get("d_by_key") or {})
    stars = set(ctxp.get("stars") or [])

    if presets is None:
        presets = preset_fives(ctxp, rotation, team_id)
    preset_index = {}
    for p in presets:
        pids = [x for x in p["pids"] if x in budget]
        if len(pids) == SLOTS:
            preset_index[frozenset(pids)] = p["labels"]

    # the anchor five = the optimizer's five biggest minute loads. This IS the
    # "best 5" on the dashboard's Best-5 lens and the best signature fit on the
    # signature lens — the surface picks the objective, the frame just uses it.
    anchor = sorted(rotation, key=lambda p: -minutes[p])[:SLOTS]

    if project is None:
        import helpers.lineup_projection as LP
        _cache = {}

        def project(five):
            k = frozenset(five)
            if k not in _cache:
                _cache[k] = LP.project_lineup(team_id, list(five), ctxp,
                                              game_ids=game_ids)
            return _cache[k]

    reserve, residual = _split_pools(budget, anchor)
    a_left = sum(1 for r in FRAME if r != FREE)
    f_left = N_BLOCKS - a_left

    coverage = {g["key"]: 0.0 for g in goals}
    blocks = []
    for i in range(N_BLOCKS):
        role = FRAME[i]
        if role == FREE:
            pool, left, base = residual, f_left, (
                [list(k) for k in preset_index] + [anchor])
        else:
            pool, left, base = reserve, a_left, [anchor]
        # force-play anyone whose remaining budget equals the remaining blocks —
        # the rule that keeps a perfectly-tight pool from stranding a slot.
        must = [p for p, n in pool.items() if n >= left]

        seen, cands = set(), []
        for five in base:
            fixed = _repair(five, pool, must)
            if not fixed:
                continue
            k = frozenset(fixed)
            if k in seen:
                continue
            seen.add(k)
            cands.append(fixed)
        if not cands:
            fallback = _repair(sorted(pool, key=lambda p: -pool[p]), pool, must)
            if not fallback:
                break
            cands = [fallback]

        prev = frozenset(blocks[-1]["five"]) if blocks else None
        best = None
        for five in cands:
            pr = project(five) or {}
            line = pr.get("line") or {}
            net = pr.get("net_blended", pr.get("net"))
            hit = _hits(line, goals)
            intact = frozenset(five) in preset_index
            s = _score(five, hit, net, coverage, gw, stars, intact, prev)
            if role in (ANCHOR, CLOSE):
                s += 10.0                       # the frame is not negotiable
            if best is None or s > best[0]:
                best = (s, five, hit, net, intact)

        _, five, hit, net, intact = best
        label, is_preset = _label_for(five, preset_index)
        blocks.append({
            "i": i, "quarter": i // QUARTER + 1,
            "start": i * BLOCK, "end": (i + 1) * BLOCK,
            "role": role, "five": list(five), "label": label,
            "preset": is_preset and intact, "net": net,
            "goals_hit": sorted(hit),
            "why": _why(role, hit, coverage, gw, goals, net),
        })
        for p in five:
            pool[p] -= 1
        if role == FREE:
            f_left -= 1
        else:
            a_left -= 1
        for k in hit:
            coverage[k] = coverage.get(k, 0.0) + BLOCK

    if not blocks:
        return {"gated": "could not build a feasible schedule from these minutes"}
    _uniquify_labels(blocks)

    return {
        "blocks": blocks,
        "segments": _merge_segments(blocks),
        "stints": _stints(blocks, ctxp),
        "units": _units(blocks),
        "coverage": coverage,
        "minutes": _scheduled_minutes(blocks),
        "target_minutes": {p: minutes[p] for p in rotation},
        "uncovered": [g["key"] for g in goals if coverage.get(g["key"], 0) <= 0],
        "anchor": anchor,
    }


def _uniquify_labels(blocks):
    """Two different fives can land on the same name (two repairs of one preset).
    The chart colors and the legend key off the label, so a collision paints two
    distinct groups the same color — number the repeats instead."""
    seen, used = {}, {}
    for b in blocks:
        k = frozenset(b["five"])
        if k not in seen:
            n = used.get(b["label"], 0) + 1
            used[b["label"]] = n
            seen[k] = b["label"] if n == 1 else f"{b['label']} · {n}"
        b["label"] = seen[k]


def _why(role, hit, coverage, gw, goals, net):
    """One line of coach-facing reasoning for a block."""
    if role == ANCHOR:
        return "Anchor five — open the half with your best group."
    if role == CLOSE:
        return "Closing five — the game is decided here."
    best, bw = None, 0.0
    for k in hit:
        w = gw.get(k, 0.0) * max(0.0, 1.0 - coverage.get(k, 0.0) / GAME_MIN)
        if w > bw:
            best, bw = k, w
    if best and bw >= 0.15:
        import helpers.lineup_projection as LP
        lbl = LP.KEY_LABELS.get(best, best)
        return f"Covers {lbl} — your least-covered win stat at this point."
    if best:
        import helpers.lineup_projection as LP
        return ("Holds " + LP.KEY_LABELS.get(best, best)
                + " — every win stat is already well covered, so this is bench "
                  "time that costs you nothing.")
    if goals:
        return "Rest window — none of your win stats projects to land here; " \
               "these are the minutes to spend bench legs."
    return f"Rest window — best available Net ({(net or 0):+.1f})."


def _merge_segments(blocks):
    """Collapse consecutive blocks with the SAME five into one stint of play."""
    out = []
    for b in blocks:
        if out and frozenset(out[-1]["five"]) == frozenset(b["five"]):
            out[-1]["end"] = b["end"]
            out[-1]["blocks"] += 1
            continue
        out.append({"start": b["start"], "end": b["end"], "blocks": 1,
                    "five": list(b["five"]), "label": b["label"],
                    "preset": b["preset"], "net": b["net"],
                    "goals_hit": b["goals_hit"], "why": b["why"],
                    "quarter": b["quarter"]})
    return out


def _stints(blocks, ctxp):
    """Per-player rows for the rotation chart.

    ``segments`` are split by UNIT so the chart can color each bar by the five on
    the floor; ``entries`` counts actual trips onto the court (a player who stays
    on through a substitution around them never left, even though the unit — and
    so the bar color — changed). Reporting segments as stints would tell a coach
    they're subbing twice as much as the plan actually asks."""
    players = ctxp.get("players") or {}
    segs = {}
    for b in blocks:
        for p in b["five"]:
            row = segs.setdefault(p, {"pid": p,
                                      "name": (players.get(p) or {}).get("name",
                                                                         str(p)),
                                      "segments": [], "minutes": 0.0,
                                      "entries": 0})
            row["minutes"] += BLOCK
            contiguous = bool(row["segments"]) and row["segments"][-1][1] == b["start"]
            if not contiguous:
                row["entries"] += 1
            if contiguous and row["segments"][-1][2] == b["label"]:
                s, _, lbl = row["segments"][-1]
                row["segments"][-1] = (s, b["end"], lbl)
            else:
                row["segments"].append((b["start"], b["end"], b["label"]))
    return sorted(segs.values(), key=lambda r: -r["minutes"])


def _units(blocks):
    """The distinct fives used, deepest first — the chart's legend."""
    seen = {}
    for b in blocks:
        k = frozenset(b["five"])
        u = seen.setdefault(k, {"five": list(b["five"]), "label": b["label"],
                                "preset": b["preset"], "net": b["net"],
                                "minutes": 0.0})
        u["minutes"] += BLOCK
    return sorted(seen.values(), key=lambda u: -u["minutes"])


def _scheduled_minutes(blocks):
    out = {}
    for b in blocks:
        for p in b["five"]:
            out[p] = out.get(p, 0.0) + BLOCK
    return out
