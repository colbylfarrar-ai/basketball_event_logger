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


# ── the connection matrix (spec Part 4c) ─────────────────────────────────────
# The hockey graph above needs an opt-in tag and is empty on most books. THIS
# graph needs only `pass_from_id`, which is filled on 2,678 of 7,731 events
# (34.6%) today, so it works right now.
#
# What makes it different from everything already in the codebase:
#   * stats.expected_assists sums xA PER PASSER and throws the edge away;
#   * insights_team.passer_finishing does the same with a finishing-luck twist;
#   * networks.chemistry_network is the POSSESSION graph — two players sharing
#     the floor, which is not the same relationship as one feeding the other;
#   * team_analytics.assist_network IS a passer→finisher edge list and is
#     already drawn as the Playmaking node-link diagram — but it counts MADE
#     shots only (`if e["shot_result"] != "make": continue`, team_analytics.py
#     :1540). It therefore cannot see a pair that generates good looks the
#     shooter misses, which is precisely the blind spot xA exists to close.
#
# So the division of labour is deliberate and should stay that way:
#     assist_network      what DROPPED   — made assists, node-link picture
#     connection_matrix   what was CREATED — every feed, weighted by the shot
#                         quality it produced, plus the finishing gap
# Two surfaces, one question each. Do not merge them; the made-only graph is
# the right picture of what actually happened.

#: Feeds below this are noise on a high-school book — one lucky night of two
#: passes between a pair should not draw an edge on a graph a coach reads as
#: structure. Callers can lower it; the surfaces do not.
MIN_EDGE_FEEDS = 4


def connection_matrix(game_ids=None, events=None, team_id=None, team_of=None,
                      rates=None, min_feeds=MIN_EDGE_FEEDS):
    """Who feeds whom: [{passer, shooter, feeds, made, pts, xa, xa_pts,
    finish_delta, team_id}] — one row per DIRECTED passer→shooter edge.

    Weighted two ways on purpose:
      * `feeds` / `made` / `pts` — what happened.
      * `xa` / `xa_pts` — what the looks were WORTH, scored by the same
        (zone, creation, contested) make-rate table behind xA and xPPS. An edge
        that generates good looks the shooter misses is a real connection; raw
        assist counts would call it a bad one.
      * `finish_delta` = made − xa. Positive means this shooter over-converted
        this passer's looks. It is a FINISHING read about the pair, not a
        passing read, and small-n noise dominates it below ~10 feeds.

    Directed, and that matters: A→B and B→A are different facts about an
    offence, and collapsing them would hide which player is the hub.

    `team_id` filters to edges INSIDE one team (both ends on the roster).
    `team_of` accepts a prebuilt {pid: team_id} so a caller looping teams pays
    for one query. `rates` accepts a prebuilt shot_quality_rates result so a
    surface showing this beside xA does not rebuild the model.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if rates is None:
        rates = S.shot_quality_rates(events=events)
    if team_of is None:
        from database.db import query
        team_of = {r["id"]: r["team_id"] for r in query(
            "SELECT id, team_id FROM players")}

    agg = defaultdict(lambda: {"feeds": 0, "made": 0, "pts": 0,
                               "xa": 0.0, "xa_pts": 0.0})
    for e in events:
        if e["event_type"] != "shot":
            continue
        passer, shooter = e.get("pass_from_id"), e.get("primary_player_id")
        if passer is None or shooter is None or passer == shooter:
            continue
        t = team_of.get(passer)
        if team_id is not None and (t != team_id
                                    or team_of.get(shooter) != team_id):
            continue
        key = (e["zone"],
               S._creation_bucket(True, e["shot_created_by_id"] is not None),
               e["guarded_by_id"] is not None)
        pct = (rates.get(key) or {}).get("pct", 0.0)
        val = 3 if e["shot_type"] == 3 else 2
        c = agg[(passer, shooter)]
        c["feeds"] += 1
        c["xa"] += pct
        c["xa_pts"] += pct * val
        if e["shot_result"] == "make":
            c["made"] += 1
            c["pts"] += val

    rows = []
    for (p, s), c in agg.items():
        if c["feeds"] < min_feeds:
            continue
        rows.append({
            "passer": p, "shooter": s, "team_id": team_of.get(p),
            "feeds": c["feeds"], "made": c["made"], "pts": c["pts"],
            "xa": round(c["xa"], 2), "xa_pts": round(c["xa_pts"], 2),
            "finish_delta": round(c["made"] - c["xa"], 2),
        })
    rows.sort(key=lambda r: (-r["feeds"], -r["xa"]))
    return rows


def connection_hubs(rows):
    """{pid: {fed, received, feeds_out, feeds_in, xa_out, partners_out,
    partners_in}} — per-player roll-up of the edge list.

    The point of keeping the edge is being able to collapse it DELIBERATELY.
    `partners_out` (how many different teammates a player feeds) separates a
    genuine hub from a player locked into one two-man game, which is the
    distinction a per-passer total cannot make.
    """
    out = {}
    for r in rows:
        a = out.setdefault(r["passer"], {"feeds_out": 0, "feeds_in": 0,
                                         "xa_out": 0.0, "xa_in": 0.0,
                                         "partners_out": set(),
                                         "partners_in": set()})
        a["feeds_out"] += r["feeds"]
        a["xa_out"] += r["xa"]
        a["partners_out"].add(r["shooter"])
        b = out.setdefault(r["shooter"], {"feeds_out": 0, "feeds_in": 0,
                                          "xa_out": 0.0, "xa_in": 0.0,
                                          "partners_out": set(),
                                          "partners_in": set()})
        b["feeds_in"] += r["feeds"]
        b["xa_in"] += r["xa"]
        b["partners_in"].add(r["passer"])
    for pid, d in out.items():
        d["partners_out"] = len(d["partners_out"])
        d["partners_in"] = len(d["partners_in"])
        d["xa_out"] = round(d["xa_out"], 2)
        d["xa_in"] = round(d["xa_in"], 2)
    return out


def connection_verdict(rows, names=None):
    """[(badge, n, html)] for helpers.cards.verdict_card. Silent when the graph
    is too thin to describe, rather than narrating three feeds."""
    if not rows:
        return []

    def nm(pid):
        return (names or {}).get(pid, f"#{pid}")

    lines = []
    total = sum(r["feeds"] for r in rows)
    top = rows[0]
    lines.append((
        "Main line", top["feeds"],
        f"<b>{nm(top['passer'])} → {nm(top['shooter'])}</b> is the offence's "
        f"busiest connection — <b>{top['feeds']}</b> feeds worth "
        f"<b>{top['xa']:.1f}</b> expected assists."))

    hubs = connection_hubs(rows)
    if hubs:
        hub = max(hubs.items(), key=lambda kv: (kv[1]["partners_out"],
                                                kv[1]["feeds_out"]))
        pid, h = hub
        if h["partners_out"] >= 3:
            lines.append((
                "Hub", h["feeds_out"],
                f"<b>{nm(pid)}</b> feeds <b>{h['partners_out']}</b> different "
                f"teammates ({h['feeds_out']} feeds, {h['xa_out']:.1f} xA) — "
                f"the distributor, not just a high assist total."))

    # the finishing read, only where the sample can carry it
    thick = [r for r in rows if r["feeds"] >= 10]
    if thick:
        cold = min(thick, key=lambda r: r["finish_delta"])
        if cold["finish_delta"] <= -2.0:
            lines.append((
                "Cold line", cold["feeds"],
                f"<b>{nm(cold['passer'])} → {nm(cold['shooter'])}</b> has "
                f"produced <b>{cold['xa']:.1f}</b> expected assists but only "
                f"<b>{cold['made']}</b> made — good looks that are not "
                f"dropping, not a bad connection."))
    if total < 40:
        lines.append(("Sample", total,
                      "Thin passing graph so far — reads firm up as more "
                      "assists are logged."))
    return lines


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
