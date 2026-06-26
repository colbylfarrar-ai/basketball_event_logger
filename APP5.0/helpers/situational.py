"""
situational.py — play_type / defense breakdown sliced by GAME SITUATION.

The play_type + defense tags already power per-set four-factors (helpers/breakdown.py).
This layer asks a different question: *when* does a team lean on a set or scheme —
which quarter, what score-state, on a run? It replays a team's tracked events once,
tags each with the game-state at that moment ({quarter, margin_before, run}), then
re-runs the existing breakdown engine on each situation slice. No new aggregation
math: situations are just pre-filters fed to ``breakdown.factors_by_tag``.

Streamlit-free (the engine mirror of stats.py / breakdown.py). The display layer is
helpers/dashboard/situational_tab.py + the scout sheet + the insights generators.

Sparsity is the binding constraint: tagged play_type/defense is thin, and slicing by
situation multiplies it — so every cell carries ``poss`` + ``stable`` and the UI gates
hard. Broad slices (by-quarter, leading/trailing) fill first; narrow ones light up as
tagging grows (the same dormant-until-tagged pattern as the rest of the play_type
engine).
"""
from __future__ import annotations

import helpers.gameflow as GF
from helpers.breakdown import factors_by_tag
from helpers.defenses import DEFENSES
from helpers.playtypes import NAMED_PLAY_TYPES

# Gates. Situational slices are inherently smaller than the 70-poss four-factors
# gate, so 'stable' uses a lower bar; below it a cell still returns, just flagged.
SIT_MIN_POSS = 12          # possessions for a situation cell to read as stable
RUN_PTS = 6                # unanswered points by one team = "on a run" (mirrors courtside.run_alert min_run)
LEAD = 6                   # margin >= +LEAD  -> leading
TRAIL = -6                 # margin <= TRAIL  -> trailing
TRAIL10 = -10              # margin <= TRAIL10 -> down 10+
CLOSE = 5                  # |margin| <= CLOSE -> one-possession-ish game

_PLAY_KEYS = {k for k, _ in NAMED_PLAY_TYPES}
_PLAY_LABELS = dict(NAMED_PLAY_TYPES)
_DEF_KEYS = {d[0] for d in DEFENSES}
_DEF_LABELS = {d[0]: d[1] for d in DEFENSES}

# Each situation is an independent LENS (not a partition) — a possession can be both
# "4th Q" and "Down 10+". (key, label, group, predicate over the {q,margin,run} tag).
_SITUATIONS = [
    ("q1",      "1st quarter",        "Quarter", lambda a: a["q"] == 1),
    ("q2",      "2nd quarter",        "Quarter", lambda a: a["q"] == 2),
    ("q3",      "3rd quarter",        "Quarter", lambda a: a["q"] == 3),
    ("q4",      "4th quarter / OT",   "Quarter", lambda a: a["q"] >= 4),
    ("lead",    "Leading (6+)",       "Score",   lambda a: a["margin"] >= LEAD),
    ("close",   "Close (±5)",         "Score",   lambda a: abs(a["margin"]) <= CLOSE),
    ("trail",   "Trailing (6+)",      "Score",   lambda a: a["margin"] <= TRAIL),
    ("trail10", "Down 10+",           "Score",   lambda a: a["margin"] <= TRAIL10),
    ("run_us",  "On a run",           "Run",     lambda a: a["run"] == "us"),
    ("run_opp", "Opponent on a run",  "Run",     lambda a: a["run"] == "opp"),
]


def _elapsed(e):
    """Seconds since tip for chronological sort; degrade to a quarter-coarse key."""
    try:
        return GF.elapsed(e)
    except Exception:
        try:
            return int(e.get("quarter") or 1) * 100000
        except Exception:
            return 0


def _event_points(e):
    """(points, scoring_team_id) for a made FG/FT, else (0, None)."""
    et = e.get("event_type")
    if et == "shot" and e.get("shot_result") == "make":
        return (3 if e.get("shot_type") == 3 else 2), e.get("shooter_team_id")
    if et == "free_throw" and e.get("shot_result") == "make":
        return 1, e.get("shooter_team_id")
    return 0, None


def annotate(events, team_id):
    """Tag each event in place with ``e['_sit'] = {q, margin, run}`` = the game-state
    BEFORE that event, from ``team_id``'s perspective. One chronological pass:
    only made FG/FT move the margin / run streak; everything else inherits the
    state at its moment. ``run`` is 'us' / 'opp' / None (>= RUN_PTS unanswered).
    Returns the same list (mutated)."""
    order = sorted(events, key=_elapsed)
    margin = 0          # team_id - opponent, BEFORE the next event
    run_owner = None
    run_pts = 0
    for e in order:
        run = None
        if run_pts >= RUN_PTS and run_owner is not None:
            run = "us" if run_owner == team_id else "opp"
        e["_sit"] = {"q": int(e.get("quarter") or 1), "margin": margin, "run": run}
        pts, scorer = _event_points(e)
        if pts and scorer is not None:
            margin += pts if scorer == team_id else -pts
            if scorer == run_owner:
                run_pts += pts
            else:
                run_owner, run_pts = scorer, pts
    return events


def _off_totals(evs, team_id):
    """Team's OWN offensive totals over a slice (tagged OR untagged plays), so a
    situation has a true scoring line even where few plays carry a set tag."""
    FGA = FGM = FG3M = FTM = TOV = PTS = 0
    for e in evs:
        if e.get("shooter_team_id") != team_id:
            continue
        et = e.get("event_type")
        if et == "shot":
            FGA += 1
            if e.get("shot_result") == "make":
                FGM += 1
                if e.get("shot_type") == 3:
                    FG3M += 1
                    PTS += 3
                else:
                    PTS += 2
        elif et == "free_throw":
            if e.get("shot_result") == "make":
                FTM += 1
                PTS += 1
        elif et == "turnover":
            TOV += 1
    poss = FGA + TOV
    return {
        "poss": poss, "PTS": PTS, "FGA": FGA,
        "PPP": (PTS / poss) if poss else 0.0,
        "eFG": ((FGM + 0.5 * FG3M) / FGA) if FGA else 0.0,
        "FG%": (FGM / FGA) if FGA else 0.0,
    }


def _rows_from_cells(cells, labels):
    """factors_by_tag output -> ranked usage rows with share-of-tagged. Sorted by
    possessions (most-USED first — the situational question is 'what do they run'),
    not by PPP."""
    total = sum(c["poss"] for c in cells.values()) or 1
    rows = []
    for key, c in cells.items():
        rows.append({
            "key": key, "label": labels.get(key, key.title()),
            "poss": c["poss"], "share": c["poss"] / total,
            "PPP": c["PPP"], "eFG": c["eFG"], "FG%": c["FG%"],
            "stable": c["stable"],
        })
    rows.sort(key=lambda r: -r["poss"])
    return rows


def _slice(events, pred):
    return [e for e in events if pred(e.get("_sit") or {"q": 1, "margin": 0, "run": None})]


def team_situational(team_id, events, gender=None, min_poss=SIT_MIN_POSS):
    """Per-situation play_type (offense) + defense-scheme breakdown for ``team_id``.

    ``events`` = fetch_events() rows for the team's tracked games (already
    entitlement-scoped by the caller; ``gender`` is accepted for signature parity
    with the other engines but the events list already encodes the sample).

    Returns ``None`` when the team has no offensive possessions, else::

        {
          'situations': [ {key,label,group, off_poss,PPP,eFG,'FG%',
                           plays:[usage rows], top_play, defenses:[...], top_def,
                           tagged_poss, stable}, ... ],   # 'all' baseline first
          'concentration': [ {play_label, sit_label, share_here, share_overall, lift, poss} ],
          'rows': [ {label, poss, PPP, 'FG%', top} ],     # flat per-situation (scout sheet)
          'off_poss_total': int, 'tagged_total': int,
        }
    """
    if not events:
        return None
    annotate(events, team_id)

    def _build(evs):
        off = _off_totals(evs, team_id)
        plays = _rows_from_cells(
            factors_by_tag(evs, team_id, "play_type", _PLAY_KEYS,
                           offense=True, min_poss=min_poss), _PLAY_LABELS)
        defs = _rows_from_cells(
            factors_by_tag(evs, team_id, "defense", _DEF_KEYS,
                           offense=False, min_poss=min_poss), _DEF_LABELS)
        return off, plays, defs

    base_off, base_plays, _ = _build(events)
    if base_off["poss"] == 0:
        return None
    base_share = {p["key"]: p["share"] for p in base_plays}

    situations = [{
        "key": "all", "label": "All possessions", "group": "All",
        "off_poss": base_off["poss"], "PPP": base_off["PPP"],
        "eFG": base_off["eFG"], "FG%": base_off["FG%"],
        "plays": base_plays, "top_play": base_plays[0] if base_plays else None,
        "defenses": _build(events)[2], "top_def": None,
        "tagged_poss": sum(p["poss"] for p in base_plays),
        "stable": base_off["poss"] >= min_poss,
    }]
    situations[0]["top_def"] = (situations[0]["defenses"][0]
                                if situations[0]["defenses"] else None)

    concentration = []
    for key, label, group, pred in _SITUATIONS:
        evs = _slice(events, pred)
        off, plays, defs = _build(evs)
        if off["poss"] == 0:
            continue
        tagged = sum(p["poss"] for p in plays)
        situations.append({
            "key": key, "label": label, "group": group,
            "off_poss": off["poss"], "PPP": off["PPP"],
            "eFG": off["eFG"], "FG%": off["FG%"],
            "plays": plays, "top_play": plays[0] if plays else None,
            "defenses": defs, "top_def": defs[0] if defs else None,
            "tagged_poss": tagged, "stable": off["poss"] >= min_poss,
        })
        # "Situational set" signal: a play whose share spikes vs its overall share.
        for p in plays:
            ov = base_share.get(p["key"], 0.0)
            if p["poss"] >= 6 and p["share"] >= 0.18 and ov > 0 and p["share"] / ov >= 1.6:
                concentration.append({
                    "play_label": p["label"], "sit_label": label,
                    "share_here": p["share"], "share_overall": ov,
                    "lift": p["share"] / ov, "poss": p["poss"],
                })
    concentration.sort(key=lambda c: -c["lift"])

    rows = []
    for s in situations[1:]:
        tp = s["top_play"]
        rows.append({
            "label": s["label"], "poss": s["off_poss"], "PPP": s["PPP"],
            "FG%": s["FG%"],
            "top": (f"{tp['label']} {tp['share'] * 100:.0f}%" if tp else "—"),
        })

    return {
        "situations": situations, "concentration": concentration[:6],
        "rows": rows,
        "off_poss_total": base_off["poss"],
        "tagged_total": sum(p["poss"] for p in base_plays),
    }


# ── Per-player situational edge (auto-insight feed) ─────────────────────────────
# Quarter-based ONLY (team-agnostic, no margin perspective needed across players):
# does a player's scoring spike or crater in the 4th vs their overall? Feeds
# helpers/insights.py _g_situational. Gated on a min shot/poss sample.
PLAYER_SIT_MIN = 8


def _player_line(events, pid, quarters=None):
    FGA = FGM = FG3M = FTM = TOV = PTS = 0
    for e in events:
        if e.get("primary_player_id") != pid:
            continue
        if quarters is not None and int(e.get("quarter") or 1) not in quarters:
            continue
        et = e.get("event_type")
        if et == "shot":
            FGA += 1
            if e.get("shot_result") == "make":
                FGM += 1
                if e.get("shot_type") == 3:
                    FG3M += 1
                    PTS += 3
                else:
                    PTS += 2
        elif et == "free_throw":
            if e.get("shot_result") == "make":
                FTM += 1
                PTS += 1
        elif et == "turnover":
            TOV += 1
    poss = FGA + TOV
    return {"poss": poss, "PTS": PTS, "FGA": FGA,
            "PPP": (PTS / poss) if poss else 0.0}


def player_situational_edges(events, min_poss=PLAYER_SIT_MIN):
    """{pid: {situation, ppp_here, ppp_overall, poss, label}} — each player's most
    notable QUARTER-based scoring swing (4th-quarter clutch vs overall). Quarter is
    absolute, so this needs no team/margin perspective and works on any events list.
    Players below ``min_poss`` in the situation are omitted."""
    if not events:
        return {}
    pids = {e.get("primary_player_id") for e in events
            if e.get("primary_player_id") is not None}
    out = {}
    LENSES = [("4th quarter", {4, 5, 6, 7, 8}), ("1st quarter", {1})]
    for pid in pids:
        overall = _player_line(events, pid)
        if overall["poss"] < min_poss:
            continue
        best = None
        for label, qs in LENSES:
            line = _player_line(events, pid, quarters=qs)
            if line["poss"] < min_poss:
                continue
            delta = line["PPP"] - overall["PPP"]
            if best is None or abs(delta) > abs(best["delta"]):
                best = {"label": label, "ppp_here": line["PPP"],
                        "ppp_overall": overall["PPP"], "poss": line["poss"],
                        "delta": delta}
        if best is not None and abs(best["delta"]) >= 0.10:
            out[pid] = best
    return out
