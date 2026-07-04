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

# Some set calls have an INTRINSIC shot nature — a single play_type tag already
# implies it. A spot-up IS a catch-and-shoot three; an iso / post / cut / putback
# / duck-in IS a rim/paint attack (you only get the tag because that's what the
# action is). So calling that out as a "tendency" just restates the tag — the
# prose scout keys / insight generators suppress the attribute a set inherently
# has and only fire on the SURPRISING ones (a transition that hunts threes, a PnR
# that pops, a set that gets clean looks). Attributes: 'three' (3-point hunt),
# 'rim' (rim/paint attack).
INHERENT_ATTR = {
    "spot": {"three"},
    "iso": {"rim"}, "post": {"rim"}, "cut": {"rim"},
    "putback": {"rim"}, "duckin": {"rim"},
}


def is_inherent(key, attr):
    """True if set call ``key`` intrinsically has shot attribute ``attr`` (so
    surfacing it as a tendency is redundant — it's baked into the tag)."""
    return attr in INHERENT_ATTR.get(key, ())


def team_named_playtypes(team_id, gender=None, game_ids=None, events=None,
                         offense=True):
    """
    Per-possession numbers by the EXPLICIT one-tap `play_type` tag, for the
    team's own offense or what it allowed (defense). Self-contained: with no
    events it does one tracked-game pass for the gender (same scoping as
    team_playtype_percentiles).

    Since the trackers stamp the sticky set call on TURNOVERS and FOULS too, a
    possession here = tagged shot OR tagged turnover (the locked rule, per set),
    so PPP is a true per-possession rate and TO% is the set's give-it-away rate.
    Fouls are NOT possessions: FD counts fouls DRAWN running the set (offense)
    / committed defending it (offense=False). On legacy data with shot-only
    tags everything reduces to the old numbers exactly.

    Returns {'rows': [{key,label,poss,FGM,PPP,FG%,TOV,TO%,FD,share}],
    'total_tagged': n, 'untagged': n (untagged SHOTS — the coverage read)}.
    Rows with nothing logged are dropped; rows are sorted by PPP.
    Unknown/legacy labels fold into 'other'.
    """
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    agg = {k: {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0,
               "TOV": 0, "FD": 0}
           for k, _ in NAMED_PLAY_TYPES}
    tagged = untagged = 0
    for e in events:
        et = e["event_type"]
        if et not in ("shot", "turnover", "foul") \
                or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        pt = e.get("play_type")
        if not pt:
            if et == "shot":
                untagged += 1
            continue
        if pt not in _NAMED_KEYS:
            pt = "other"
        cell = agg[pt]
        if et == "turnover":
            cell["TOV"] += 1
            tagged += 1
            continue
        if et == "foul":
            cell["FD"] += 1          # drawn (offense) / committed (defense)
            continue
        tagged += 1
        cell["FGA"] += 1
        is3 = e["shot_type"] == 3
        if is3:
            cell["FG3A"] += 1
        if e["shot_result"] == "make":
            cell["FGM"] += 1
            cell["PTS"] += 3 if is3 else 2
            if is3:
                cell["FG3M"] += 1
    total_poss = sum(c["FGA"] + c["TOV"] for c in agg.values())
    rows = []
    for key, label in NAMED_PLAY_TYPES:
        c = agg[key]
        poss = c["FGA"] + c["TOV"]
        if poss == 0 and c["FD"] == 0:
            continue
        _2pa, _2pm = c["FGA"] - c["FG3A"], c["FGM"] - c["FG3M"]
        rows.append({
            "key": key, "label": label, "poss": poss, "FGM": c["FGM"],
            "PPP": _safe(c["PTS"], poss), "FG%": _safe(c["FGM"], c["FGA"]),
            "TOV": c["TOV"], "TO%": _safe(c["TOV"], poss), "FD": c["FD"],
            # eFG weights 3s; SCE = FG points / max possible (rewards shot
            # selection AND making); 2P%/3P% split the mix.
            "eFG": _safe(c["FGM"] + 0.5 * c["FG3M"], c["FGA"]),
            "SCE": _safe(c["PTS"], _2pa * 2 + c["FG3A"] * 3),
            "3P%": _safe(c["FG3M"], c["FG3A"]), "2P%": _safe(_2pm, _2pa),
            "3PA": c["FG3A"], "share": _safe(poss, total_poss),
        })
    rows.sort(key=lambda r: r["PPP"], reverse=True)
    return {"rows": rows, "total_tagged": tagged, "untagged": untagged}


def player_named_playtypes(game_ids=None, events=None):
    """
    Per-PLAYER per-possession numbers by the explicit one-tap `play_type` tag —
    the player-level companion to team_named_playtypes. Shots count for the
    shooter, tagged TURNOVERS for the committer (both primary_player_id), so a
    player's possession = tagged shot OR tagged TO and PPP/TO% read true.
    Tagged fouls DRAWN (fouled player) count as FD, not possessions.
    Unknown/legacy labels fold into 'other'; untagged events are skipped.

    Returns {player_id: {key: {'poss','FGM','PPP','FG%','TOV','TO%','FD',…}}} —
    only the play_type keys a player actually has tagged events for. Feeds the
    per-set player badges (PnR Maestro / Post Hub) and the scout cards.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    agg = {}

    def _cell(pid, pt):
        return agg.setdefault(pid, {}).setdefault(
            pt, {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0,
                 "TOV": 0, "FD": 0})

    for e in events:
        if e["event_type"] not in ("shot", "turnover", "foul") \
                or e["primary_player_id"] is None:
            continue
        pt = e.get("play_type")
        if not pt:
            continue
        if pt not in _NAMED_KEYS:
            pt = "other"
        cell = _cell(e["primary_player_id"], pt)
        if e["event_type"] == "turnover":
            cell["TOV"] += 1
            continue
        if e["event_type"] == "foul":
            cell["FD"] += 1          # primary = the FOULED player (drawn)
            continue
        cell["FGA"] += 1
        is3 = e["shot_type"] == 3
        if is3:
            cell["FG3A"] += 1
        if e["shot_result"] == "make":
            cell["FGM"] += 1
            cell["PTS"] += 3 if is3 else 2
            if is3:
                cell["FG3M"] += 1
    return {pid: {k: {"poss": c["FGA"] + c["TOV"], "FGM": c["FGM"],
                      "PPP": _safe(c["PTS"], c["FGA"] + c["TOV"]),
                      "FG%": _safe(c["FGM"], c["FGA"]),
                      "TOV": c["TOV"],
                      "TO%": _safe(c["TOV"], c["FGA"] + c["TOV"]),
                      "FD": c["FD"],
                      "eFG": _safe(c["FGM"] + 0.5 * c["FG3M"], c["FGA"]),
                      "SCE": _safe(c["PTS"],
                                   (c["FGA"] - c["FG3A"]) * 2 + c["FG3A"] * 3),
                      "3P%": _safe(c["FG3M"], c["FG3A"])}
                  for k, c in d.items()
                  if c["FGA"] + c["TOV"] + c["FD"] > 0}
            for pid, d in agg.items()}


# ── play-type ROLE split (ball-handler vs roll man within a screen action) ────────
# game_events.shot_created_by_id is the "Shot Created By" tag — the SCREENER who
# freed this shooter. On a pick-&-roll the BALL-HANDLER uses the on-ball screen,
# so his shot carries a creator (filled); the ROLL MAN set the screen and was not
# screened himself, so his finish has no creator (empty). So among `pnr` shots the
# creator field splits the shooter's ROLE — the owner's headline read. The mapping
# is one constant (ROLE_EMPTY_IS) so it's trivial to flip if a program's tagging
# convention differs. Off-screen / DHO reuse the same split (screen-user vs setter).
ROLE_SPLIT_KEYS = ("pnr", "dho", "offscreen")
ROLE_EMPTY_IS = "roller"     # shot_created_by_id empty => this role; filled => the other
_ROLE_OTHER = {"roller": "handler", "handler": "roller"}


def _role_of(e):
    """Shooter's role on a screen action, from shot_created_by_id (the screener)."""
    return (ROLE_EMPTY_IS if e.get("shot_created_by_id") is None
            else _ROLE_OTHER[ROLE_EMPTY_IS])


def _role_fin(c):
    # 3PA_rate splits ROLL (rim, low 3PA) from POP (high 3PA) for a screen finisher
    # — "their roll man pops for 3" falls straight out of the roller's 3PA_rate.
    return {"poss": c["FGA"], "FGM": c["FGM"],
            "PPP": _safe(c["PTS"], c["FGA"]), "FG%": _safe(c["FGM"], c["FGA"]),
            "eFG": _safe(c["FGM"] + 0.5 * c["FG3M"], c["FGA"]),
            "3PA_rate": _safe(c.get("FG3A", 0), c["FGA"])}


def player_role_splits(game_ids=None, events=None, keys=ROLE_SPLIT_KEYS):
    """Per-PLAYER PPP/FG%/eFG split by ROLE within screen actions (the owner's
    PnR ball-handler-vs-roller read). Only shots whose ``play_type`` is in ``keys``.

    Returns ``{player_id: {play_key: {'handler': fin, 'roller': fin, 'all': fin}}}``
    where ``handler`` = shooter used a teammate's screen (shot_created_by_id filled)
    and ``roller`` = the screen-setter who finished (empty). Empty until games carry
    play_type tags, so it lights up as tracking fills in — graceful by construction.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    agg = {}
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] is None:
            continue
        pt = e.get("play_type")
        if pt not in keys:
            continue
        role = _role_of(e)
        d = agg.setdefault(e["primary_player_id"], {}).setdefault(pt, {
            "handler": {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0},
            "roller":  {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0},
            "all":     {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0}})
        made = e["shot_result"] == "make"
        is3 = e["shot_type"] == 3
        for r in (role, "all"):
            c = d[r]
            c["FGA"] += 1
            if is3:
                c["FG3A"] += 1
            if made:
                c["FGM"] += 1
                c["PTS"] += 3 if is3 else 2
                if is3:
                    c["FG3M"] += 1
    return {pid: {k: {r: _role_fin(c) for r, c in v.items()}
                  for k, v in d.items()}
            for pid, d in agg.items()}


def team_role_splits(team_id, game_ids=None, events=None, keys=ROLE_SPLIT_KEYS,
                     offense=True):
    """Team-level companion to ``player_role_splits`` — the team's own shots
    (offense) or shots it allowed (defense), split handler vs roller per set call.
    Returns ``{play_key: {'handler': fin, 'roller': fin, 'all': fin}}``."""
    if events is None:
        gids = game_ids if game_ids is not None else None
        events = S.fetch_events(gids)
    own = None if offense else TA.event_team_games(team_id, events)
    agg = {}
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        pt = e.get("play_type")
        if pt not in keys:
            continue
        role = _role_of(e)
        d = agg.setdefault(pt, {
            "handler": {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0},
            "roller":  {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0},
            "all":     {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0}})
        made = e["shot_result"] == "make"
        is3 = e["shot_type"] == 3
        for r in (role, "all"):
            c = d[r]
            c["FGA"] += 1
            if is3:
                c["FG3A"] += 1
            if made:
                c["FGM"] += 1
                c["PTS"] += 3 if is3 else 2
                if is3:
                    c["FG3M"] += 1
    return {k: {r: _role_fin(c) for r, c in v.items()} for k, v in agg.items()}


# ══════════════════════════════════════════════════════════════════════════════
#  EXPLICIT-TAG LEAGUE PERCENTILES  (the Synergy-style rank for the one-tap call)
# ══════════════════════════════════════════════════════════════════════════════
# team_named_playtypes / player_named_playtypes give raw PPP by the literal set
# call, but a raw "1.04 PPP on Iso" means nothing without a league rank. These
# mirror the INFERRED machinery above (_baseline_from_events / team_playtype_
# percentiles) but over NAMED_PLAY_TYPES, so the explicit tag gets the same
# percentile + tier treatment the tempo/creation lenses already have. Built to be
# trustworthy at dense tagging scale; rows under MIN_POSS / pools under MIN_POOL
# get pct=None (shown as "thin sample", never a fake rank). Min per-PLAYER poss is
# a touch lower (8) than per-TEAM (10) since a player runs fewer of any one set.
MIN_PLAYER_POSS = 8


def _named_baseline_from_events(events, offense=True):
    """One pool of team PPPs per NAMED_PLAY_TYPES key (the league baseline the
    explicit-tag percentiles rank against). Mirrors _baseline_from_events."""
    pool = {k: [] for k, _ in NAMED_PLAY_TYPES}
    for tid in _shooter_teams(events):
        named = team_named_playtypes(tid, events=events, offense=offense)
        for r in named["rows"]:
            if r["poss"] >= MIN_POSS:
                pool[r["key"]].append(r["PPP"])
    return pool


def team_named_playtype_percentiles(team_id, gender=None, game_ids=None,
                                    events=None, offense=True, baseline=None):
    """The explicit-tag analog of team_playtype_percentiles: each tagged set call
    with the team's PPP/FG%/share PLUS its **league percentile** + tier (good
    already encoded — on defense, allowing fewer points ranks higher). Self-
    contained: with no events/baseline it does one tracked-game pass for the
    gender and ranks the team off that same pass.

    Returns {'rows':[{key,label,poss,FGM,PPP,FG%,share,pct,tier,color,lg_ppp}],
    'total_tagged','untagged','offense'} — rows are only the set calls the team
    actually ran (sorted by PPP, as team_named_playtypes returns them)."""
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    if baseline is None:
        baseline = _named_baseline_from_events(events, offense=offense)
    named = team_named_playtypes(team_id, events=events, offense=offense)
    rows = []
    for r in named["rows"]:
        pool = baseline.get(r["key"], [])
        ranked = r["poss"] >= MIN_POSS and len(pool) >= MIN_POOL
        pct = TA.percentile(r["PPP"], pool, higher_better=offense) if ranked else None
        tier_label, tier_color = _tier(pct)
        rows.append({**r, "pct": pct, "tier": tier_label, "color": tier_color,
                     "lg_ppp": (sum(pool) / len(pool)) if pool else None})
    return {"rows": rows, "total_tagged": named["total_tagged"],
            "untagged": named["untagged"], "offense": offense}


def player_named_playtype_percentiles(gender=None, game_ids=None, events=None,
                                      min_poss=MIN_PLAYER_POSS, min_pool=MIN_POOL):
    """Per-PLAYER PPP by the explicit one-tap tag, each ranked vs the league pool
    of players' PPP on that same set (Synergy's player play-type page). Inverts
    player_named_playtypes into per-key pools, gates by ``min_poss``, percentiles
    each qualifying player, attaches _tier + per-player share-of-tagged.

    Returns {player_id: {play_key: {poss,FGM,PPP,FG%,share,pct,tier,color,
    lg_ppp}}} — only the keys a player has tagged attempts in. Empty until games
    carry tags, so it lights up as tracking fills in."""
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    per = player_named_playtypes(events=events)
    pools = {}
    for _pid, d in per.items():
        for key, c in d.items():
            if c["poss"] >= min_poss:
                pools.setdefault(key, []).append(c["PPP"])
    out = {}
    for pid, d in per.items():
        tot_poss = sum(c["poss"] for c in d.values())
        row = {}
        for key, c in d.items():
            pool = pools.get(key, [])
            ranked = c["poss"] >= min_poss and len(pool) >= min_pool
            pct = TA.percentile(c["PPP"], pool, higher_better=True) if ranked else None
            tier_label, tier_color = _tier(pct)
            row[key] = {**c, "share": _safe(c["poss"], tot_poss),
                        "pct": pct, "tier": tier_label, "color": tier_color,
                        "lg_ppp": (sum(pool) / len(pool)) if pool else None}
        out[pid] = row
    return out


def league_named_playtype_leaders(gender=None, game_ids=None, events=None,
                                  offense=True, min_poss=MIN_POSS, baseline=None):
    """League leaderboards by set call: for each NAMED_PLAY_TYPES key, the teams
    ranked by PPP on that action (offense=who runs it best; offense=False=who
    defends it best, fewest points allowed first). The team-facing companion to
    player_named_playtype_percentiles.

    Returns {key: {'label','lg_ppp','leaders':[{team_id,PPP,FG%,poss,share,pct,
    tier,color}]}} — only keys with at least one team above min_poss."""
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    per_team = {tid: team_named_playtypes(tid, events=events, offense=offense)
                for tid in _shooter_teams(events)}
    if baseline is None:
        baseline = {k: [] for k, _ in NAMED_PLAY_TYPES}
        for _tid, named in per_team.items():
            for r in named["rows"]:
                if r["poss"] >= min_poss:
                    baseline[r["key"]].append(r["PPP"])
    out = {}
    for key, label in NAMED_PLAY_TYPES:
        pool = baseline.get(key, [])
        leaders = []
        for tid, named in per_team.items():
            cell = next((r for r in named["rows"] if r["key"] == key), None)
            if not cell or cell["poss"] < min_poss:
                continue
            pct = (TA.percentile(cell["PPP"], pool, higher_better=offense)
                   if len(pool) >= MIN_POOL else None)
            tier_label, tier_color = _tier(pct)
            leaders.append({"team_id": tid, "PPP": cell["PPP"], "FG%": cell["FG%"],
                            "poss": cell["poss"], "share": cell["share"],
                            "pct": pct, "tier": tier_label, "color": tier_color})
        leaders.sort(key=lambda x: x["PPP"], reverse=offense)
        if leaders:
            out[key] = {"label": label,
                        "lg_ppp": (sum(pool) / len(pool)) if pool else None,
                        "leaders": leaders}
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  CROSS-DIMENSION INTEL  (play_type × everything else a shot already carries)
# ══════════════════════════════════════════════════════════════════════════════
# A set call's PPP is the headline; the SCOUTING read is what the set produces:
#   • shot_type   -> 3PA-rate per set     ("in transition they hunt a 3")
#   • zone        -> where the set scores  ("they shoot HERE on transition")
#   • pass_from_id-> assisted-rate + the FEEDER chain (who hands off the DHO,
#                    who inbounds the BLOB/SLOB) — the pass-side analog of the
#                    screen role split
#   • guarded_by_id-> open vs contested per set ("their iso gets clean looks")
#   • possession_secs -> true tempo per set
# Robust on zone+shot_type (every shot carries them); located x/y only sharpens.
# rim = a 2-pt attempt in the paint zone ('C'); mid = a non-paint 2; three = a 3.

_PROFILE_ZONES = ("LC", "LW", "C", "RW", "RC")


def _blank_profile():
    return {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0,
            "three": 0, "rim": 0, "rimM": 0, "mid": 0, "ast": 0, "open": 0,
            "guard_n": 0,
            "zones": {z: 0 for z in _PROFILE_ZONES}, "secs": 0.0, "secs_n": 0}


def _profile_add(p, e):
    """Fold one shot event into a profile cell."""
    is3 = e["shot_type"] == 3
    made = e["shot_result"] == "make"
    p["FGA"] += 1
    if is3:
        p["FG3A"] += 1
        p["three"] += 1
    elif e.get("zone") == "C":
        p["rim"] += 1
    else:
        p["mid"] += 1
    if made:
        p["FGM"] += 1
        p["PTS"] += 3 if is3 else 2
        if is3:
            p["FG3M"] += 1
        elif e.get("zone") == "C":
            p["rimM"] += 1
    if e.get("pass_from_id") is not None:
        p["ast"] += 1
    # guarded_by_id present == contested; absent == an open look (matches the
    # guarded/open convention team_analytics.guarded_splits already uses).
    if e.get("guarded_by_id") is None:
        p["open"] += 1
    else:
        p["guard_n"] += 1
    z = e.get("zone")
    if z in p["zones"]:
        p["zones"][z] += 1
    secs = e.get("possession_secs")
    if secs and secs > 0:
        p["secs"] += secs
        p["secs_n"] += 1


def _profile_fin(p, key=None, label=None):
    fga = p["FGA"]
    return {
        "key": key, "label": label, "poss": fga, "FGM": p["FGM"],
        "PPP": _safe(p["PTS"], fga), "FG%": _safe(p["FGM"], fga),
        "eFG": _safe(p["FGM"] + 0.5 * p["FG3M"], fga),
        "SCE": _safe(p["PTS"], (fga - p["FG3A"]) * 2 + p["FG3A"] * 3),
        "3PA_rate": _safe(p["FG3A"], fga),
        # finishing splits INSIDE the cell — FG% at the rim / from three vs this
        # scheme or set (None when that shot type never happened here).
        "rim_FG%": (_safe(p["rimM"], p["rim"]) if p["rim"] else None),
        "3P%": (_safe(p["FG3M"], p["FG3A"]) if p["FG3A"] else None),
        "rim_rate": _safe(p["rim"], fga), "mid_rate": _safe(p["mid"], fga),
        "ast_rate": _safe(p["ast"], fga), "open_rate": _safe(p["open"], fga),
        "zones": dict(p["zones"]), "top_zone": (max(p["zones"], key=p["zones"].get)
                                                if fga else None),
        "avg_secs": (p["secs"] / p["secs_n"]) if p["secs_n"] else None,
    }


def team_playtype_shot_profiles(team_id, gender=None, game_ids=None, events=None,
                                offense=True):
    """Per-set SHOT PROFILE for a team's own shots (offense) or shots it allowed
    (defense): each tagged set call with PPP/FG%/eFG PLUS the cross-dimension read
    — 3PA-rate, rim/mid share, assisted-rate, open-rate, zone distribution
    (top_zone = where the set most lives) and average possession length.

    Returns {key: {key,label,poss,FGM,PPP,FG%,eFG,3PA_rate,rim_rate,mid_rate,
    ast_rate,open_rate,zones,top_zone,avg_secs}} — only set calls actually run."""
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    label = dict(NAMED_PLAY_TYPES)
    profs = {}
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        pt = e.get("play_type")
        if not pt:
            continue
        if pt not in _NAMED_KEYS:
            pt = "other"
        _profile_add(profs.setdefault(pt, _blank_profile()), e)
    return {k: _profile_fin(p, k, label.get(k, k)) for k, p in profs.items()}


def player_playtype_shot_profiles(game_ids=None, events=None):
    """Per-PLAYER, per-set SHOT PROFILE (the player-level companion to
    team_playtype_shot_profiles). Each shot counts for its shooter. Returns
    {player_id: {key: profile}} — feeds the per-player 'in transition they hunt a
    3 / get to the rim' read on the player card and the auto-scout miner."""
    if events is None:
        events = S.fetch_events(game_ids)
    label = dict(NAMED_PLAY_TYPES)
    out = {}
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] is None:
            continue
        pt = e.get("play_type")
        if not pt:
            continue
        if pt not in _NAMED_KEYS:
            pt = "other"
        d = out.setdefault(e["primary_player_id"], {})
        _profile_add(d.setdefault(pt, _blank_profile()), e)
    return {pid: {k: _profile_fin(p, k, label.get(k, k)) for k, p in d.items()}
            for pid, d in out.items()}


# ── feeder / initiator chains (who hands off the DHO, who inbounds the BLOB) ──────
# On a hand-off or inbounds set, pass_from_id is the player who STARTED the action
# — the DHO hander, the BLOB/SLOB inbounder — and primary_player_id is the
# finisher. Grouping the set's shots by pass_from_id answers "who is the DHO hub"
# and "who runs the inbounds", with the PPP that hub generates and who it feeds.
FEEDER_KEYS = ("dho", "blob", "slob")


def team_playtype_feeders(team_id, gender=None, game_ids=None, events=None,
                          keys=FEEDER_KEYS, offense=True):
    """Initiator chains for hand-off / inbounds sets. Returns {key: {'label',
    'feeders': [{feeder_id, feeds, FGM, PPP, FG%, top_target_id, targets}]}} sorted
    by volume — feeder_id = pass_from_id (the hander / inbounder), targets =
    {finisher_id: count}. Empty until those sets carry a pass_from_id tag."""
    if events is None:
        gids = game_ids if game_ids is not None else _tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    keyset = set(keys)
    label = dict(NAMED_PLAY_TYPES)
    agg = {}
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        pt = e.get("play_type")
        if pt not in keyset:
            continue
        feeder = e.get("pass_from_id")
        if feeder is None:
            continue
        cell = agg.setdefault(pt, {}).setdefault(
            feeder, {"feeds": 0, "FGM": 0, "PTS": 0, "targets": {}})
        cell["feeds"] += 1
        if e["shot_result"] == "make":
            cell["FGM"] += 1
            cell["PTS"] += 3 if e["shot_type"] == 3 else 2
        tgt = e["primary_player_id"]
        if tgt is not None:
            cell["targets"][tgt] = cell["targets"].get(tgt, 0) + 1
    out = {}
    for k, feeders in agg.items():
        rows = []
        for fid, c in feeders.items():
            tgts = c["targets"]
            rows.append({
                "feeder_id": fid, "feeds": c["feeds"], "FGM": c["FGM"],
                "PPP": _safe(c["PTS"], c["feeds"]), "FG%": _safe(c["FGM"], c["feeds"]),
                "top_target_id": (max(tgts, key=tgts.get) if tgts else None),
                "targets": dict(tgts)})
        rows.sort(key=lambda r: r["feeds"], reverse=True)
        if rows:
            out[k] = {"label": label.get(k, k), "feeders": rows}
    return out
