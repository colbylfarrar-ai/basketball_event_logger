"""
passing_chains.py — the team PASSING graph: who ignites whom.

Distinct from helpers/networks.py, which is the POSSESSION graph (chemistry per
100 while two players share the floor). This module reads the ball itself:
`hockey_from_id -> pass_from_id -> shooter` on a single shot event, the 3-node
chain the hockey-assist tag makes visible.

Why it is its own module: networks.py never touches pass tags, and the passer
engines in helpers/stats.py (expected_assists / passer_completion /
passer_look_quality) are all PER-PASSER aggregates — none of them keep the
edge, so none can answer "who ignites whom". This keeps the edge, and is the
natural home for the wider connection matrix (spec Part 4c) when that lands.

CAPTURE FACT (verified 2026-07-22, re-verified 2026-07-24): `hockey_from_id` is
logged on EVERY shot flow, make or miss — the PWA offers it in SHOT_DETAILS and
the Streamlit selectbox is ungated. Only the HAST STAT is make-only, because it
is a sibling of AST and correct by definition. So:

    HAST     chains whose shot DROPPED       — the headline stat
    PotHAST  every tagged chain, make or miss — the capture-coverage twin,
             exactly the relationship PotAST has to AST

Counting coverage off HAST alone undercounts a coach's actual tagging by the
league miss rate, which is why the re-gate counter below reads PotHAST.

Honest empty state is the default: hockey assists are opt-in, and a team that
has never tagged one gets zero rows rather than a fabricated graph.

Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S

# Pre-registered re-gate threshold (spec Part 1 §3). The #8d run found the
# HAST/G leaf INERT at 0 tagged — every player None, so rho tied the baseline
# exactly and the gate was INCONCLUSIVE rather than a reject. Re-run
# tools/gate_xa_hast.py once tagged volume reaches this, and not before: a
# trivial tie must never be read as evidence.
REGATE_AT = 50


def _shot_chains(events):
    """Yield (hockey_from, assister, shooter, made, shot_type) for every shot
    carrying a hockey-assist tag. A chain needs the hockey passer; the assister
    slot can be empty on a badly-tagged row, and those are dropped rather than
    guessed at."""
    for e in events:
        if e["event_type"] != "shot":
            continue
        h = e.get("hockey_from_id")
        if h is None:
            continue
        a = e.get("pass_from_id")
        if a is None:
            continue
        yield (h, a, e.get("primary_player_id"),
               e["shot_result"] == "make", e.get("shot_type") or 2)


def hockey_chains(game_ids=None, events=None, min_n=1):
    """Who ignites whom: [{hockey_from, assister, chains, hast, pot_hast, pts}]
    sorted by volume, one row per (igniter -> assister) EDGE.

    `chains` counts every tagged chain (make or miss) and `hast` counts only the
    ones that dropped — both are reported because a pair can move the ball well
    and still be let down by the finish, and a coach reading only `hast` would
    call that pair unproductive.

    `pts` is the points those made chains produced (shot value), so a pair
    feeding threes is not flattened against a pair feeding layups.

    Pairs below `min_n` chains are dropped. Empty list when nothing is tagged —
    the honest empty state, not a zero-filled grid.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    agg = defaultdict(lambda: {"chains": 0, "hast": 0, "pts": 0})
    for h, a, _shooter, made, stype in _shot_chains(events):
        c = agg[(h, a)]
        c["chains"] += 1
        if made:
            c["hast"] += 1
            c["pts"] += stype
    rows = [{"hockey_from": h, "assister": a, "pot_hast": c["chains"], **c}
            for (h, a), c in agg.items() if c["chains"] >= min_n]
    rows.sort(key=lambda r: (-r["chains"], -r["hast"]))
    return rows


def hockey_triples(game_ids=None, events=None, min_n=1):
    """The full 3-node chain: [{hockey_from, assister, shooter, chains, hast,
    pts}] — the igniter -> assister -> finisher sequence, sorted by volume.

    Sparser than the pairs by construction (a third node splits the same
    sample), so it is a "show the top few" surface, never a ranking. Same
    make/miss split and the same honest empty state as hockey_chains.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    agg = defaultdict(lambda: {"chains": 0, "hast": 0, "pts": 0})
    for h, a, shooter, made, stype in _shot_chains(events):
        if shooter is None:
            continue
        c = agg[(h, a, shooter)]
        c["chains"] += 1
        if made:
            c["hast"] += 1
            c["pts"] += stype
    rows = [{"hockey_from": h, "assister": a, "shooter": s,
             "pot_hast": c["chains"], **c}
            for (h, a, s), c in agg.items() if c["chains"] >= min_n]
    rows.sort(key=lambda r: (-r["chains"], -r["hast"]))
    return rows


def hast_coverage(game_ids=None, events=None):
    """Capture-coverage counter for the pre-registered HAST re-gate:
    {tagged, made, missed, games, pairs, regate_at, ready}.

    `tagged` counts ALL hockey-tagged shots (make or miss) because that is what
    measures a coach's TAGGING, while the gate's HAST/G leaf stays make-only.
    Reading coverage off made chains alone would undercount real capture by the
    league miss rate and delay the re-gate for no reason.

    `ready` is True once `tagged` reaches REGATE_AT — the signal to re-run
    tools/gate_xa_hast.py, which is the ONLY route to adopting the leaf.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    tagged = made = 0
    games, pairs = set(), set()
    for e in events:
        if e["event_type"] != "shot" or e.get("hockey_from_id") is None:
            continue
        tagged += 1
        if e["shot_result"] == "make":
            made += 1
        if e.get("game_id") is not None:
            games.add(e["game_id"])
        if e.get("pass_from_id") is not None:
            pairs.add((e["hockey_from_id"], e["pass_from_id"]))
    return {"tagged": tagged, "made": made, "missed": tagged - made,
            "games": len(games), "pairs": len(pairs),
            "regate_at": REGATE_AT, "ready": tagged >= REGATE_AT}


def coverage_line(cov):
    """One-line status for the snapshot/admin surface. Speaks plainly about an
    empty book instead of printing '0 / 50' as if progress had stalled."""
    if not cov["tagged"]:
        return ("Hockey assists: none tagged yet — turn on the Hockey Assist "
                "picker in the shot flow to light this up.")
    ready = ("ready to re-gate" if cov["ready"]
             else f"re-gate at {cov['regate_at']}")
    return (f"Hockey assists tagged: {cov['tagged']} "
            f"({cov['made']} made / {cov['missed']} missed) across "
            f"{cov['games']} game{'s' if cov['games'] != 1 else ''} — {ready}.")
