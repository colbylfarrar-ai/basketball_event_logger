"""
turnovers.py — breakdown by the explicit TURNOVER-TYPE tag.

``turnover_type`` tags the KIND of giveaway on a turnover event: bad pass,
lost on a drive, held ball, shot-clock violation, travel. Nullable one-tap
capture like play_type/defense — hidden in the PWA's quick mode, offered in
detailed mode and both editors, so old rows stay NULL and this engine lights
up only as coaches tag.

``play_type`` stays the ORTHOGONAL extra layer on turnovers (the set call the
offense was running when it lost the ball — founder convention: a cut-TO is a
bad PASS and the TO is charged to whoever lost it). The cross view here
(``sets`` per type) answers "our PnR giveaways are mostly drives, our
post-entry giveaways are passes".

Two reads off one tag, mirroring defenses/playtypes' duality:
  • offense=True  → the team's OWN giveaways by kind (ball-security profile).
  • offense=False → the giveaways it FORCES (takeaway profile). Gated on the
    team's own games via TA.event_team_games — the allowed-side rule.

Streamlit-free (pure python + sqlite).
"""
from __future__ import annotations

import helpers.stats as S
import helpers.team_analytics as TA
import helpers.playtypes as PT

_safe = TA._safe

# ── the taxonomy ─────────────────────────────────────────────────────────────
# key, label. One source of truth — tracker, PWA, editors, dashboard all read
# this list. "other" is a fold-in for unknown/legacy values, not offered in UI.
# NOTE the KEYS are permanent data values (stored on game_events.turnover_type)
# — only the display LABELS change. The 'travel' key now reads "Violation" (it
# covers travels + other floor violations); order follows the founder's call.
TURNOVER_TYPES = [
    ("travel",     "Violation"),
    ("drive",      "Drive"),
    ("pass",       "Pass"),
    ("shot_clock", "Shot clock"),
    ("held",       "Held ball"),
    ("other",      "Other"),
]
_KEYS = {k for k, _ in TURNOVER_TYPES}
_LABEL = dict(TURNOVER_TYPES)


def label(key):
    """Display label for a turnover-type key (unknown -> the key itself)."""
    return _LABEL.get(key, key)


def _norm(t):
    """A tag value -> a known key, folding unknown/legacy labels into 'other'."""
    if not t:
        return None
    return t if t in _KEYS else "other"


# ── per-team breakdown ───────────────────────────────────────────────────────
def team_turnover_types(team_id, gender=None, game_ids=None, events=None,
                        offense=True):
    """Turnovers by the explicit ``turnover_type`` tag.

    offense=True  → the team's OWN turnovers (its giveaway profile).
    offense=False → turnovers it FORCED (opponents' giveaways in ITS games —
                    scoped via TA.event_team_games, never the whole pool).

    Returns {'rows': [{key,label,n,share,stolen,sets:{play_type_label: n}}],
    'total_tagged','untagged','total'} — rows only for kinds present, sorted
    by volume. ``share`` is of TAGGED turnovers; ``stolen`` counts the subset
    with a credited steal; ``sets`` is the play_type extra layer (top calls
    the giveaway happened in). Unknown/legacy tags fold into 'other'."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    agg = {k: {"n": 0, "stolen": 0, "sets": {}} for k, _ in TURNOVER_TYPES}
    tagged = untagged = total = 0
    for e in events:
        if e["event_type"] != "turnover" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        total += 1
        t = _norm(e.get("turnover_type"))
        if not t:
            untagged += 1
            continue
        tagged += 1
        cell = agg[t]
        cell["n"] += 1
        if e.get("stolen_by_id"):
            cell["stolen"] += 1
        pt = e.get("play_type")
        if pt:
            cell["sets"][pt] = cell["sets"].get(pt, 0) + 1
    rows = []
    for key, lbl in TURNOVER_TYPES:
        c = agg[key]
        if c["n"] == 0:
            continue
        rows.append({"key": key, "label": lbl, "n": c["n"],
                     "share": _safe(c["n"], tagged), "stolen": c["stolen"],
                     "sets": dict(sorted(c["sets"].items(),
                                         key=lambda kv: -kv[1]))})
    rows.sort(key=lambda r: -r["n"])
    return {"rows": rows, "total_tagged": tagged, "untagged": untagged,
            "total": total}


# ── per-player breakdown ─────────────────────────────────────────────────────
def player_turnover_types(gender=None, game_ids=None, events=None):
    """{player_id: {'rows':[{key,label,n,share}],'total_tagged','untagged',
    'total'}} over the pool — each player's giveaways by kind (the TO is
    charged to primary_player_id, founder convention: whoever lost it)."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    per = {}
    for e in events:
        if e["event_type"] != "turnover":
            continue
        pid = e.get("primary_player_id")
        if not pid:
            continue
        d = per.setdefault(pid, {"agg": {k: 0 for k, _ in TURNOVER_TYPES},
                                 "tagged": 0, "untagged": 0, "total": 0})
        d["total"] += 1
        t = _norm(e.get("turnover_type"))
        if not t:
            d["untagged"] += 1
            continue
        d["tagged"] += 1
        d["agg"][t] += 1
    out = {}
    for pid, d in per.items():
        rows = [{"key": k, "label": lbl, "n": d["agg"][k],
                 "share": _safe(d["agg"][k], d["tagged"])}
                for k, lbl in TURNOVER_TYPES if d["agg"][k]]
        rows.sort(key=lambda r: -r["n"])
        out[pid] = {"rows": rows, "total_tagged": d["tagged"],
                    "untagged": d["untagged"], "total": d["total"]}
    return out
