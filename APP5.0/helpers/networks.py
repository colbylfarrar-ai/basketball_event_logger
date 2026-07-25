"""
networks.py — Player chemistry network (who lifts whom on the floor).

The observed-lineup engine (helpers/lineups.py) rates whole five-player units;
this is the pairwise view EvanMiya/DataBallR call "teammate chemistry": for every
pair of teammates, how the team performs per 100 possessions while BOTH are on
the floor. Rendered as a node-link graph it answers "which duos drive this team,
and which pairings drag it down?" — the interactive network the dashboard layer
was missing.

Method (mirrors lineups.py, one level down):
  * A possession is a shot OR turnover (the app's locked rule); FG points only.
  * For each possession, take the on-court five for each team. Every unordered
    PAIR of those five shares that possession — offensive if their team had the
    ball, defensive otherwise.
  * Pair Net = 100·(pts_for/off_poss − pts_against/def_poss).
  * A node's solo net is the team's net per 100 while that single player is on —
    the individual on-court baseline each pairing is read against.

Pure data layer: database.db + helpers.stats + helpers.lineups (for the shared
event-floor builder). No streamlit, no numpy.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from database.db import query
import helpers.stats as S
from helpers.lineups import (_event_floor, _five_q, fit_opponent_slopes,
                             player_quality)


DEFAULT_MIN_POSS = 20   # a pair needs this many shared possessions to be drawn


_safe = S._safe   # shared definition lives in helpers.stats


def chemistry_network(team_id, game_ids=None, events=None,
                      min_poss=DEFAULT_MIN_POSS, quality=None):
    """
    Pairwise teammate chemistry for one team, CONTEXT-ADJUSTED.

    Raw side (unchanged keys): per-100 net while a player / pair is on the
    floor. Adjusted side — the founder's "who ACTUALLY lifts whom" read —
    corrects every possession for the two things a raw pair net conflates:
      • OPPONENT strength: the mean OVERALL of the opposing on-floor five
        (the unit_ratings v2 correction, same self-fit slopes).
      • TEAMMATE strength: the mean OVERALL of the OTHER teammates sharing
        the floor (the other 3 for a pair, other 4 for a solo) — a duo that
        only looks good next to the star gives that credit back.
    Slopes come from lineups.fit_opponent_slopes on this sample; when the
    sample can't support the fit (adjusted=False) the Adj* values equal the
    raw ones, so thin data never breaks a caller.

    Returns {nodes, edges, totals}:
      nodes  [{pid, name, off_poss, def_poss, poss, pts_for, pts_against,
               net, adj_net}]
      edges  [{a, b, names, off_poss, def_poss, poss, pts_for, pts_against,
               ORtg, DRtg, net, AdjORtg, AdjDRtg, adj_net}] pairs clearing
             `min_poss`, sorted by adj_net desc
      totals {pairs, drawn, min_poss, adjusted}
    """
    if events is None:
        events = S.fetch_events(game_ids)
    floor = _event_floor(game_ids)
    if quality is None:
        quality = player_quality(game_ids=game_ids)
    b_off, b_def, qbar, adjusted = fit_opponent_slopes(events, floor, quality)

    # per-possession rows: (pts, q_opponent_five, q_other_teammates)
    solo = defaultdict(lambda: {"off": [], "def": []})
    pair = defaultdict(lambda: {"off": [], "def": []})

    def _others_q(five, exclude):
        vals = [quality[p] for p in five if p not in exclude and p in quality]
        return sum(vals) / len(vals) if vals else None

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
        if not five or len(five) != 5:
            continue
        opp_five = next((f for t, f in sets.items() if t != team_id), None)
        q_opp = (_five_q(opp_five, quality)
                 if opp_five and len(opp_five) == 5 else None)
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        side = "off" if off_team == team_id else "def"
        for p in five:
            solo[p][side].append((pts, q_opp, _others_q(five, (p,))))
        for a, b in combinations(sorted(five), 2):
            pair[(a, b)][side].append((pts, q_opp, _others_q(five, (a, b))))

    # remove the context terms from each possession's points. On offense a
    # better opposing (defensive) five suppresses points (b_def < 0) and
    # better teammates inflate them (b_off > 0); on defense the roles flip.
    def _adj_sum(rows, opp_slope, own_slope):
        tot = 0.0
        for pts, q_opp, q_own in rows:
            tot += (pts
                    - opp_slope * ((q_opp if q_opp is not None else qbar) - qbar)
                    - own_slope * ((q_own if q_own is not None else qbar) - qbar))
        return tot

    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}

    def _rates(rows):
        n_off, n_def = len(rows["off"]), len(rows["def"])
        off_pts = sum(p for p, _q, _o in rows["off"])
        def_pts = sum(p for p, _q, _o in rows["def"])
        ortg = 100 * _safe(off_pts, n_off)
        drtg = 100 * _safe(def_pts, n_def)
        if adjusted:
            a_ortg = 100 * _safe(_adj_sum(rows["off"], b_def, b_off), n_off)
            a_drtg = 100 * _safe(_adj_sum(rows["def"], b_off, b_def), n_def)
        else:
            a_ortg, a_drtg = ortg, drtg
        return n_off, n_def, off_pts, def_pts, ortg, drtg, a_ortg, a_drtg

    nodes = []
    for p, rows in solo.items():
        n_off, n_def, off_pts, def_pts, ortg, drtg, a_o, a_d = _rates(rows)
        nodes.append({
            "pid": p, "name": name_of.get(p, str(p)),
            "off_poss": n_off, "def_poss": n_def, "poss": n_off + n_def,
            "pts_for": off_pts, "pts_against": def_pts,
            "net": round(ortg - drtg, 1),
            "adj_net": round(a_o - a_d, 1),
        })
    nodes.sort(key=lambda d: -d["poss"])

    edges = []
    for (a, b), rows in pair.items():
        n_off, n_def, off_pts, def_pts, ortg, drtg, a_o, a_d = _rates(rows)
        poss = n_off + n_def
        if poss < min_poss:
            continue
        edges.append({
            "a": a, "b": b,
            "names": [name_of.get(a, str(a)), name_of.get(b, str(b))],
            "off_poss": n_off, "def_poss": n_def, "poss": poss,
            "pts_for": off_pts, "pts_against": def_pts,
            "ORtg": round(ortg, 1), "DRtg": round(drtg, 1),
            "net": round(ortg - drtg, 1),
            "AdjORtg": round(a_o, 1), "AdjDRtg": round(a_d, 1),
            "adj_net": round(a_o - a_d, 1),
        })
    edges.sort(key=lambda d: -d["adj_net"])
    return {"nodes": nodes, "edges": edges,
            "totals": {"pairs": len(pair), "drawn": len(edges),
                       "min_poss": min_poss, "adjusted": adjusted}}


# ══════════════════════════════════════════════════════════════════════════════
#  TRIOS / QUADS — the missing middle (spec Part 4a)
# ══════════════════════════════════════════════════════════════════════════════
# helpers/lineups.py rates whole FIVES; chemistry_network above rates PAIRS.
# Groups of 3 and 4 are the gap, and they are where a coach's actual rotation
# decisions live ("keep these three together", "who do I put with this core?").
#
# lineups.custom_unit already SCORES an arbitrary 2-5 player set, but it
# re-fetches events and rebuilds the on-court floor on every call. Enumerating
# C(10,3) + C(10,4) = 330 groups through it would be 330 full event walks. This
# accumulates every group in ONE walk instead, exactly as the pair code above
# does.
#
# Samples thin out fast as the group grows (each added player intersects the
# possessions further), so trios and quads carry a HIGHER min-poss than pairs
# plus the same credibility shrink lineups.py applies to fives.

GROUP_MIN_POSS = {2: DEFAULT_MIN_POSS, 3: 25, 4: 30}
_GROUP_PRIOR_POSS = 40      # possessions of league-average (Net 0) prior mixed in


def group_units(team_id, sizes=(3, 4), game_ids=None, events=None,
                min_poss=None):
    """Observed net for every k-player GROUP a team actually played, k in `sizes`.

    Returns {k: [row]} sorted best-first by credibility-weighted net, where each
    row is {players, names, off_poss, def_poss, poss, pts_for, pts_against,
    ORtg, DRtg, Net, NetAdj, cred}.

    `Net` is the raw per-100 differential while exactly that group shared the
    floor; `NetAdj` shrinks it toward 0 by sample size (cred = poss/(poss+40)),
    the same credibility weighting lineups.unit_ratings applies to fives — a
    25-possession trio at +40 is mostly noise and must not outrank a
    120-possession trio at +12.

    ONE possession walk builds every size at once. Possession rule and FT
    exclusion follow lineups.py exactly, so these numbers are comparable with
    the pair and five-man surfaces rather than being a parallel dialect.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    floor = _event_floor(game_ids)
    mins = dict(GROUP_MIN_POSS)
    if min_poss is not None:
        mins = {k: min_poss for k in sizes}

    acc = defaultdict(lambda: {"off": [], "def": []})
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
        if not five or len(five) != 5:
            continue
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        side = "off" if off_team == team_id else "def"
        ordered = sorted(five)
        for k in sizes:
            for grp in combinations(ordered, k):
                acc[(k, grp)][side].append(pts)

    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}
    out = {k: [] for k in sizes}
    for (k, grp), rows in acc.items():
        n_off, n_def = len(rows["off"]), len(rows["def"])
        poss = n_off + n_def
        if poss < mins.get(k, DEFAULT_MIN_POSS):
            continue
        off_pts, def_pts = sum(rows["off"]), sum(rows["def"])
        ortg = 100 * _safe(off_pts, n_off)
        drtg = 100 * _safe(def_pts, n_def)
        net = ortg - drtg
        cred = poss / (poss + _GROUP_PRIOR_POSS)
        out[k].append({
            "players": grp, "names": [name_of.get(p, str(p)) for p in grp],
            "off_poss": n_off, "def_poss": n_def, "poss": poss,
            "pts_for": off_pts, "pts_against": def_pts,
            "ORtg": round(ortg, 1), "DRtg": round(drtg, 1),
            "Net": round(net, 1), "NetAdj": round(net * cred, 1),
            "cred": round(cred, 2),
        })
    for k in out:
        out[k].sort(key=lambda d: -d["NetAdj"])
    return out


def finisher_finder(team_id, core, game_ids=None, events=None, min_poss=None):
    """THE ROTATION LEVER: given a strong core, rank every candidate to fill it.

    `core` is any 2-4 player set. Returns candidates who played enough
    possessions ALONGSIDE the whole core, sorted best-first by NetAdj — "with
    these four, who is the best fifth?".

    Reports the COMBINED unit's net rather than the candidate's solo net,
    because the question is which FIVE works: a strong player can still be the
    wrong fit beside a particular four. `delta_vs_core` is the honest
    comparison — the combined net minus the core's own net over all its
    possessions — so a candidate is credited for what they ADD instead of for
    the core's quality.

    Zero new capture, one event walk shared with the core measurement.
    """
    core = frozenset(core)
    if not (2 <= len(core) <= 4):
        raise ValueError("core must be 2-4 players")
    if events is None:
        events = S.fetch_events(game_ids)
    floor = _event_floor(game_ids)
    k = len(core) + 1
    mp = min_poss if min_poss is not None else GROUP_MIN_POSS.get(k, 25)

    core_rows = {"off": [], "def": []}
    cand = defaultdict(lambda: {"off": [], "def": []})
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
        if not five or len(five) != 5 or not core.issubset(five):
            continue
        pts = ((3 if e["shot_type"] == 3 else 2)
               if (e["event_type"] == "shot" and e["shot_result"] == "make") else 0)
        side = "off" if off_team == team_id else "def"
        core_rows[side].append(pts)
        for p in five:
            if p not in core:
                cand[p][side].append(pts)

    def _net(rows):
        n_off, n_def = len(rows["off"]), len(rows["def"])
        ortg = 100 * _safe(sum(rows["off"]), n_off)
        drtg = 100 * _safe(sum(rows["def"]), n_def)
        return ortg, drtg, ortg - drtg, n_off, n_def

    _co, _cd, core_net, c_off, c_def = _net(core_rows)
    name_of = {r["id"]: r["name"]
               for r in query("SELECT id, name FROM players WHERE team_id=?",
                              (team_id,))}
    rows = []
    for p, r in cand.items():
        ortg, drtg, net, n_off, n_def = _net(r)
        poss = n_off + n_def
        if poss < mp:
            continue
        cred = poss / (poss + _GROUP_PRIOR_POSS)
        rows.append({
            "pid": p, "name": name_of.get(p, str(p)),
            "off_poss": n_off, "def_poss": n_def, "poss": poss,
            "ORtg": round(ortg, 1), "DRtg": round(drtg, 1),
            "Net": round(net, 1), "NetAdj": round(net * cred, 1),
            "cred": round(cred, 2),
            "delta_vs_core": round(net - core_net, 1),
        })
    rows.sort(key=lambda d: -d["NetAdj"])
    return {"core": tuple(sorted(core)),
            "core_names": [name_of.get(p, str(p)) for p in sorted(core)],
            "core_poss": c_off + c_def, "core_net": round(core_net, 1),
            "candidates": rows, "min_poss": mp}


# ══════════════════════════════════════════════════════════════════════════════
#  GROUP SYNERGY (spec Part 4b, extended past pairs)
# ══════════════════════════════════════════════════════════════════════════════
# Pair synergy already exists: chemistry_network's edges carry an
# opponent- AND teammate-adjusted `adj_net`, and team_insights.chemistry_extra
# already reports "pair net minus the mean of the two solo nets". What was
# missing is the same read for the TRIOS and QUADS that group_units enumerates.
#
# WHY RAW GROUP NET IS NOT ENOUGH, and the reason 4b exists as a separate item:
# a trio of the three best players will top any raw-net ranking on a high-school
# roster whether or not they fit together. Raw net re-ranks good players standing
# near each other. Synergy asks the different question — does this combination
# beat the sum of its parts? — and that is the one a coach cannot eyeball.

# ── how much of a synergy number is real (MEASURED 2026-07-25, live book) ────
# Split-half over the same groups' odd vs even games, Spearman-Brown stepped up:
#     pairs  r = -0.050  ->  SB -0.106   no repeatable signal
#     trios  r =  0.094  ->  SB  0.172   implied prior  822 possessions
#     quads  r =  0.200  ->  SB  0.333   implied prior  229 possessions
# That is much weaker than raw group NET, and it should be: synergy is a
# DIFFERENCE of two noisy quantities, so it carries both their errors. The house
# prior of 40 possessions is right for a level and far too generous for this.
#
# One conservative constant is used rather than three fitted ones, because the
# three estimates rest on n = 51 / 100 / 65 groups and their standard errors
# (~0.10-0.14 on r) comfortably overlap. 400 sits between the two positive
# implied priors; the pair estimate implies no finite prior at all.
#
# Consequence, and it is intended: on a 24-game book almost nothing clears a
# meaningful synergy bar, and the verdict says so out loud instead of ranking
# noise confidently. The table stays because it is a Lab exploration surface a
# coach reads WITH the caveat, not a prescriptive card.
_SYNERGY_PRIOR_POSS = 400

#: Measured Spearman-Brown reliability per group size, for the caveat line.
SYNERGY_RELIABILITY = {2: -0.11, 3: 0.17, 4: 0.33}


def group_synergy(team_id, sizes=(2, 3, 4), game_ids=None, events=None,
                  min_poss=None, groups=None):
    """{k: [row]} — group net MINUS what the members' solo nets predict.

    Each row is a `group_units` row plus:
      expected  mean of the members' solo on-floor nets
      synergy   Net - expected, in points per 100
      syn_adj   synergy shrunk by poss/(poss + _SYNERGY_PRIOR_POSS), which is
                what the list is ranked on. The prior is 400, not the 40 that
                group_units uses for raw net, because measured split-half
                reliability of synergy is far lower than of net — see the note
                above. A 26-possession trio at +30 synergy is noise and must not
                outrank a 150-possession trio at +9.

    SOLO NETS COME FROM group_units(sizes=(1,)), NOT chemistry_network. Two
    reasons, and both matter:

      * LIKE-FOR-LIKE BY CONSTRUCTION. chemistry_network's node carries
        `adj_net`, which is opponent- and TEAMMATE-corrected. Subtracting that
        from group_units' raw `Net` is apples-from-oranges — the teammate
        correction pulls every solo net toward or below zero on a good team, so
        the first draft of this reported an `expected` of about -7 against group
        nets of +46 and called essentially every trio +57 in "synergy". Taking
        both sides from the same function makes that class of mistake
        impossible rather than merely fixed.
      * COST. chemistry_network runs an opponent-slope ridge fit and takes
        16.5s on the live book; group_units is 0.2s and already walks every
        group size at once. Adding k=1 to the sizes it enumerates is free.

    HONESTY: synergy is not additive and does not decompose a lineup. Three
    players' solo nets already contain each other's minutes — they play
    together — so `expected` is a reference point, not a counterfactual. It
    answers "is this group better than its members usually are", which is
    useful, and NOT "what would happen if you played them more", which this
    cannot support.

    `groups` accepts a prebuilt `group_units` result (which must include size 1)
    so a surface showing units and synergy together pays for one walk, not two.
    """
    want = tuple(sorted(set(sizes) | {1}))
    if groups is None or 1 not in groups:
        groups = group_units(team_id, sizes=want, game_ids=game_ids,
                             events=events, min_poss=min_poss)
    solo = {}
    for row in groups.get(1) or []:
        solo[row["players"][0]] = row["Net"]

    out = {}
    for k in sizes:
        if k == 1:
            continue
        rows = []
        for g in groups.get(k) or []:
            solos = [solo.get(p) for p in g["players"]]
            if any(s is None for s in solos):
                continue
            expected = sum(solos) / len(solos)
            syn = g["Net"] - expected
            # NOT g["cred"] -- that is group_units' net credibility on a
            # 40-possession prior. Synergy is a difference and needs its own.
            syn_cred = g["poss"] / (g["poss"] + _SYNERGY_PRIOR_POSS)
            rows.append({**g,
                         "expected": round(expected, 1),
                         "synergy": round(syn, 1),
                         "syn_adj": round(syn * syn_cred, 1),
                         "syn_cred": round(syn_cred, 2)})
        rows.sort(key=lambda d: -d["syn_adj"])
        out[k] = rows
    return out


def synergy_verdict(syn, names=None):
    """[(badge, n, html)] for helpers.cards.verdict_card.

    Reports the best and worst COMBINATION rather than the best group, because
    the best group is almost always just the best players and a coach already
    knows who those are.
    """
    def nm(pid):
        return (names or {}).get(pid, f"#{pid}")

    lines = []
    spoke = False
    for k in sorted(syn):
        rows = syn[k]
        if len(rows) < 3:          # too few groups to call anything the best
            continue
        best, worst = rows[0], rows[-1]
        word = {2: "pair", 3: "trio", 4: "four"}.get(k, f"{k}-man group")
        if best["syn_adj"] >= 3 or worst["syn_adj"] <= -3:
            spoke = True
        if best["syn_adj"] >= 3:
            lines.append((
                f"Best {word}", best["poss"],
                "<b>" + " · ".join(nm(p) for p in best["players"]) + "</b>"
                f" is <b>{best['synergy']:+.1f}</b> per 100 better together "
                f"than its members usually are ({best['Net']:+.1f} net against "
                f"an expected {best['expected']:+.1f}), over {best['poss']} "
                f"possessions."))
        if worst["syn_adj"] <= -3:
            lines.append((
                f"Worst {word}", worst["poss"],
                "<b>" + " · ".join(nm(p) for p in worst["players"]) + "</b>"
                f" is <b>{worst['synergy']:+.1f}</b> per 100 — good players who "
                f"have not fit together so far, on {worst['poss']} possessions."))
    if spoke:
        # Standing caveat, never omitted. Synergy is the weakest-measured read
        # on this page and a coach reading a confident ranking deserves to know
        # it repeats poorly game-to-game.
        lines.append((
            "How firm is this", 0,
            "Synergy repeats <b>weakly</b> on a book this size — split-half "
            "reliability measured 0.17 for trios and 0.33 for fours, and pairs "
            "did not repeat at all. Read these as places to LOOK, not as "
            "settled facts about who fits with whom."))
    return lines
