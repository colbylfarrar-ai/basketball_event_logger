"""
playtypes.py — Synergy-style "play type" efficiency with a LEAGUE-PERCENTILE rank.

Synergy's signature view is points-per-possession (PPP) for each play type plus a
percentile rank vs the field. This app can't tag literal play calls (isolation,
pick-and-roll, post-up) — there is no video and the tracker is fixed — but the
event model already carries the two signals that *define* how a possession was
generated: its **tempo** (possession_secs) and its **shot creation** (was the
shooter set up by a pass and/or a screen). We classify every shot on those two
lenses, compute PPP per type, and rank each against the league pool of team PPPs.

Honest framing (the UI must say this): these are **inferred possession types from
logged tempo + shot creation, not video-tagged play calls.** It is the faithful
PPP-by-context analog of Synergy in this app's data.

Streamlit-free engine (numpy-free; pure python + sqlite). Reuses the shot
gathering / aggregation already in team_analytics so the math matches the rest of
the app: a shot ends a possession, so possessions == FGA and PPP == PPS.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S
import helpers.team_analytics as TA

_safe = TA._safe

# Minimum possessions in a cell before it earns a percentile, and minimum teams
# in a pool before a rank means anything (a short HS book is noisy).
MIN_POSS = 10
MIN_POOL = 4

# The play types, in display order, grouped by lens (axis).
#   key, label, axis, blurb
PLAY_TYPES = [
    ("transition", "Transition",            "tempo",
     "Shot up within 6s of the possession starting — push / fast break."),
    ("early",      "Early offense",         "tempo",
     "7–14s — secondary break and flowing into the set."),
    ("halfcourt",  "Half-court",            "tempo",
     "15s+ — a called set against a set defense."),
    ("self",       "Isolation / self-made", "creation",
     "No pass and no screen into the shot — pure self-creation off the bounce."),
    ("pass",       "Spot-up (off a pass)",  "creation",
     "Created by a pass with no screen — catch-and-shoot / drive-and-kick."),
    ("screen",     "Off a screen",          "creation",
     "A screen freed the shooter with no pass — off-ball / dribble hand-off."),
    ("both",       "Screen + pass",         "creation",
     "Both a screen and a pass — pick-and-roll / flare actions into the shot."),
]
_AXIS_LABEL = {"tempo": "By tempo", "creation": "By shot creation"}


def _tempo(secs):
    """Possession length → tempo bucket, or None for untimed (~16% carry 0s)."""
    if not secs or secs <= 0:
        return None
    if secs <= 6:
        return "transition"
    if secs <= 14:
        return "early"
    return "halfcourt"


def _creation(s):
    """self / pass / screen / both, from pass_from_id & shot_created_by_id."""
    hp = s["pass_from_id"] is not None
    hc = s["shot_created_by_id"] is not None
    return "both" if hp and hc else "pass" if hp else "screen" if hc else "self"


def _tier(pct):
    """Synergy-style label + colour off a 0-100 percentile (good already encoded)."""
    if pct is None:
        return ("—", "#8b949e")
    if pct >= 90:
        return ("Excellent", "#2ea043")
    if pct >= 75:
        return ("Very good", "#3fb950")
    if pct >= 55:
        return ("Good", "#58a6ff")
    if pct >= 45:
        return ("Average", "#f0a500")
    if pct >= 25:
        return ("Below avg", "#e3873c")
    return ("Poor", "#da3633")


# ── tracked game ids for a gender ────────────────────────────────────────────────
def _tracked_game_ids(gender=None):
    clause = "WHERE g.tracked = 1 AND g.season = 'Current'"
    params = []
    if gender:
        clause += " AND t1.gender = ?"
        params.append(gender)
    rows = query(
        f"SELECT g.id FROM games g JOIN teams t1 ON t1.id = g.team1_id {clause}",
        tuple(params))
    return [r["id"] for r in rows]


def _shooter_teams(events):
    return sorted({e["shooter_team_id"] for e in events
                   if e["event_type"] == "shot" and e["shooter_team_id"] is not None})


# ── per-team play-type lines ─────────────────────────────────────────────────────
def team_playtypes(team_id, game_ids=None, events=None, offense=True):
    """
    The team's own shots (offense=True) or the shots it allows (offense=False)
    grouped into the PLAY_TYPES — two overlapping lenses (tempo, shot creation).

    Returns {key: agg_shots line + label/axis/PPP/poss/share} for each play type
    plus 'total'. A shot lands in exactly one tempo bucket (or none, if untimed)
    AND one creation bucket — the two lenses are reported side by side, not summed.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    shots = TA._team_shots(team_id, events, offense=offense)
    groups = {k: [] for k, *_ in PLAY_TYPES}
    for s in shots:
        t = _tempo(s["possession_secs"])
        if t:
            groups[t].append(s)
        groups[_creation(s)].append(s)

    total = TA.agg_shots(shots)
    out = {"total": total}
    for key, label, axis, _blurb in PLAY_TYPES:
        a = TA.agg_shots(groups[key])
        a.update(label=label, axis=axis, PPP=a["PPS"], poss=a["FGA"],
                 share=_safe(a["FGA"], total["FGA"]))
        out[key] = a
    return out


# ── league baseline (one pool of team PPPs per play type) ────────────────────────
def _baseline_from_events(events, offense=True):
    pool = {k: [] for k, *_ in PLAY_TYPES}
    for tid in _shooter_teams(events):
        pt = team_playtypes(tid, events=events, offense=offense)
        for key, *_ in PLAY_TYPES:
            cell = pt[key]
            if cell["poss"] >= MIN_POSS:
                pool[key].append(cell["PPP"])
    return pool


def team_playtype_percentiles(team_id, gender=None, game_ids=None, events=None,
                              offense=True, baseline=None):
    """
    The display-ready table: each play type with the team's PPP, FG%, share of
    offense, and its **league percentile** (good already encoded — for defense,
    allowing fewer points ranks higher). Rows below MIN_POSS or pools below
    MIN_POOL get pct=None (shown as "thin sample", never a fake rank).

    Returns {'rows': [...], 'total': agg, 'offense': bool}. Self-contained: with
    no events/baseline it does one league event pass for the gender and ranks the
    team off that same pass, so the team cells and the pool are consistent.
    """
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    if baseline is None:
        baseline = _baseline_from_events(events, offense=offense)

    pt = team_playtypes(team_id, events=events, offense=offense)
    rows = []
    for key, label, axis, blurb in PLAY_TYPES:
        cell = pt[key]
        pool = baseline.get(key, [])
        ranked = cell["poss"] >= MIN_POSS and len(pool) >= MIN_POOL
        pct = TA.percentile(cell["PPP"], pool, higher_better=offense) if ranked else None
        tier_label, tier_color = _tier(pct)
        rows.append({
            "key": key, "label": label, "axis": axis, "axis_label": _AXIS_LABEL[axis],
            "blurb": blurb, "poss": cell["poss"], "PPP": cell["PPP"],
            "FG%": cell["FG%"], "eFG": cell["eFG"], "share": cell["share"],
            "pct": pct, "tier": tier_label, "color": tier_color,
            "lg_ppp": (sum(pool) / len(pool)) if pool else None,
        })
    return {"rows": rows, "total": pt["total"], "offense": offense}


# ── explicit one-tap play-call tags (the coach's literal set call) ────────────────
# The companion to the INFERRED team_playtypes above: this reads the optional
# `play_type` a coach taps on a shot in the tracker, so it stays empty until
# tagging begins. These are the literal set calls inference can't derive.
NAMED_PLAY_TYPES = [
    ("pnr", "Pick & roll"), ("iso", "Isolation"), ("post", "Post-up"),
    ("spot", "Spot-up"), ("cut", "Cut"), ("offscreen", "Off screen"),
    ("dho", "DHO"), ("duckin", "Duck in"),
    ("slob", "SLOB"), ("blob", "BLOB"),
    ("transition", "Transition"), ("putback", "Putback"), ("other", "Other"),
]
_NAMED_KEYS = {k for k, _ in NAMED_PLAY_TYPES}


def team_named_playtypes(team_id, gender=None, game_ids=None, events=None,
                         offense=True):
    """
    PPP by the EXPLICIT one-tap `play_type` tag, for the team's own shots
    (offense) or the shots it allowed (defense). Self-contained: with no events
    it does one tracked-game pass for the gender (same scoping as
    team_playtype_percentiles). A shot ends a possession, so PPP == PPS.

    Returns {'rows': [{key,label,poss,FGM,PPP,FG%,share}], 'total_tagged': n,
    'untagged': n}. Rows with no attempts are dropped; rows are sorted by PPP.
    Unknown/legacy labels fold into 'other'.
    """
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    agg = {k: {"FGA": 0, "FGM": 0, "PTS": 0} for k, _ in NAMED_PLAY_TYPES}
    tagged = untagged = 0
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        pt = e.get("play_type")
        if not pt:
            untagged += 1
            continue
        if pt not in _NAMED_KEYS:
            pt = "other"
        tagged += 1
        cell = agg[pt]
        cell["FGA"] += 1
        if e["shot_result"] == "make":
            cell["FGM"] += 1
            cell["PTS"] += 3 if e["shot_type"] == 3 else 2
    total_fga = sum(c["FGA"] for c in agg.values())
    rows = []
    for key, label in NAMED_PLAY_TYPES:
        c = agg[key]
        if c["FGA"] == 0:
            continue
        rows.append({
            "key": key, "label": label, "poss": c["FGA"], "FGM": c["FGM"],
            "PPP": _safe(c["PTS"], c["FGA"]), "FG%": _safe(c["FGM"], c["FGA"]),
            "share": _safe(c["FGA"], total_fga),
        })
    rows.sort(key=lambda r: r["PPP"], reverse=True)
    return {"rows": rows, "total_tagged": tagged, "untagged": untagged}
