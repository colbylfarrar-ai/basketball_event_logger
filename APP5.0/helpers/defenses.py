"""
defenses.py — Synergy-style efficiency by the explicit DEFENSE tag.

The defensive companion to helpers/playtypes.py. Where ``play_type`` tags the
offensive set call on a shot, ``defense`` tags the SCHEME the defending team was
in for that possession — man, 2-3 / 1-3-1 zone, presses, traps, junk, scramble.
Same one-tap capture model (nullable, **sticky** in the tracker since a team
stays in a defense for stretches), the same PPP-by-context math, the same
league-percentile rank — plus the cross-tab the offense side can't give:
**play_type × defense** ("their pick-and-roll vs a 2-3 zone").

Two reads off one tag, exactly like playtypes' offense/allowed duality:
  • offense=False → the defenses a team RUNS (tagged on the shots it ALLOWED):
                    how effective each scheme is (PPP allowed). Scout headline.
  • offense=True  → the defenses a team FACED (tagged on its OWN shots): how it
                    attacks each scheme (PPP scored). Game-plan headline.

A shot ends a possession, so PPP == PPS — same convention as playtypes. The
percentile is good-oriented: on defense (offense=False) allowing FEWER points
ranks higher; on offense scoring MORE ranks higher.

Streamlit-free (pure python + sqlite). Reuses playtypes' tier / shot-profile /
tracked-game / baseline machinery so the two engines stay in lockstep.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S
import helpers.team_analytics as TA
import helpers.playtypes as PT

_safe = TA._safe
_tier = PT._tier                         # 0-100 percentile -> (label, colour)
MIN_POSS = PT.MIN_POSS                    # min shots in a cell before it ranks
MIN_POOL = PT.MIN_POOL                    # min teams in a pool before a rank means anything
MIN_PLAYER_POSS = PT.MIN_PLAYER_POSS

# ── the defense taxonomy ─────────────────────────────────────────────────────────
# key, label, family. Sticky one-tap tag on a shot/turnover (the defending team's
# scheme). "Other" is the catch-all the tracker also offers and unknown/legacy
# labels fold into. Add a scheme here and it flows everywhere (tracker, editor,
# dashboard, scout) — the one source of truth, mirroring NAMED_PLAY_TYPES.
DEFENSES = [
    ("man",        "Man-to-man",            "man"),
    ("man_press",  "Man press",             "press"),
    ("zone_23",    "2-3 zone",              "zone"),
    ("zone_32",    "3-2 zone",              "zone"),
    ("zone_131",   "1-3-1 zone",            "zone"),
    ("zone_122",   "1-2-2 zone",            "zone"),
    ("matchup",    "Match-up zone",         "zone"),
    ("trap_23",    "2-3 trap",              "trap"),
    ("trap_131",   "1-3-1 trap",            "trap"),
    ("press_221",  "2-2-1 press",           "press"),
    ("press_131",  "1-3-1 press",           "press"),
    ("press_1211", "1-2-1-1 press",         "press"),
    ("box1",       "Box-and-1",             "junk"),
    ("triangle2",  "Triangle-and-2",        "junk"),
    ("diamond1",   "Diamond-and-1",         "junk"),
    ("scramble",   "Scramble / transition", "transition"),
    ("other",      "Other",                 "other"),
]
_KEYS = {k for k, *_ in DEFENSES}
_LABEL = {k: lbl for k, lbl, _ in DEFENSES}
_FAMILY = {k: fam for k, _, fam in DEFENSES}

# Family rollup (the first-order read — "they're a zone team", "they press 35%
# of trips"), in display order. A whole scheme's keys collapse to one bar.
DEFENSE_FAMILIES = [
    ("man",        "Man"),
    ("zone",       "Zone"),
    ("press",      "Press"),
    ("trap",       "Trap"),
    ("junk",       "Junk (box/triangle/diamond)"),
    ("transition", "Scramble"),
    ("other",      "Other"),
]
_FAMILY_LABEL = dict(DEFENSE_FAMILIES)


def label(key):
    """Display label for a defense key (unknown -> the key itself)."""
    return _LABEL.get(key, key)


def family_of(key):
    """Family key for a defense key (man / zone / press / trap / junk / …)."""
    return _FAMILY.get(key, "other")


def _norm(d):
    """A tag value -> a known key, folding unknown/legacy labels into 'other'."""
    if not d:
        return None
    return d if d in _KEYS else "other"


# ── per-team defense lines (PPP by the explicit tag) ──────────────────────────────
def team_defenses(team_id, gender=None, game_ids=None, events=None, offense=True):
    """PPP by the explicit ``defense`` tag.

    offense=True  → the team's OWN shots, grouped by the defense it FACED (how it
                    attacks each scheme).
    offense=False → the shots it ALLOWED, grouped by the defense it RAN (how
                    effective each of its schemes is — PPP allowed).

    Self-contained: with no events it does one tracked-game pass for the gender
    (same scoping as playtypes). A shot ends a possession, so PPP == PPS.

    Returns {'rows':[{key,label,family,poss,FGM,PPP,FG%,eFG,SCE,3P%,2P%,3PA,share}],
    'total_tagged','untagged'}. Rows are only the schemes actually present, sorted
    by possessions (volume) — "which defense do they run most" is the headline.
    Unknown/legacy labels fold into 'other'."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    agg = {k: {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0}
           for k, *_ in DEFENSES}
    tagged = untagged = 0
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        d = _norm(e.get("defense"))
        if not d:
            untagged += 1
            continue
        tagged += 1
        cell = agg[d]
        cell["FGA"] += 1
        is3 = e["shot_type"] == 3
        if is3:
            cell["FG3A"] += 1
        if e["shot_result"] == "make":
            cell["FGM"] += 1
            cell["PTS"] += 3 if is3 else 2
            if is3:
                cell["FG3M"] += 1
    total_fga = sum(c["FGA"] for c in agg.values())
    rows = []
    for key, lbl, fam in DEFENSES:
        c = agg[key]
        if c["FGA"] == 0:
            continue
        _2pa, _2pm = c["FGA"] - c["FG3A"], c["FGM"] - c["FG3M"]
        rows.append({
            "key": key, "label": lbl, "family": fam,
            "poss": c["FGA"], "FGM": c["FGM"],
            "PPP": _safe(c["PTS"], c["FGA"]), "FG%": _safe(c["FGM"], c["FGA"]),
            "eFG": _safe(c["FGM"] + 0.5 * c["FG3M"], c["FGA"]),
            "SCE": _safe(c["PTS"], _2pa * 2 + c["FG3A"] * 3),
            "3P%": _safe(c["FG3M"], c["FG3A"]), "2P%": _safe(_2pm, _2pa),
            "3PA": c["FG3A"], "share": _safe(c["FGA"], total_fga),
        })
    rows.sort(key=lambda r: -r["poss"])
    return {"rows": rows, "total_tagged": tagged, "untagged": untagged}


# ── family rollup (man / zone / press …) ──────────────────────────────────────────
def team_defense_families(team_id, gender=None, game_ids=None, events=None,
                          offense=True):
    """team_defenses collapsed to the man/zone/press/trap/junk/scramble FAMILIES —
    the first-order read ("they're a zone team", "they press a third of trips").
    Returns {'rows':[{family,label,poss,FGM,PPP,FG%,eFG,SCE,share}],'total_tagged'},
    sorted by possessions."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    fam_shots = {f: [] for f, _ in DEFENSE_FAMILIES}
    tagged = 0
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        d = _norm(e.get("defense"))
        if not d:
            continue
        tagged += 1
        fam_shots[_FAMILY[d]].append(e)
    rows = []
    for fam, lbl in DEFENSE_FAMILIES:
        a = TA.agg_shots(fam_shots[fam])
        if a["FGA"] == 0:
            continue
        rows.append({
            "family": fam, "label": lbl, "poss": a["FGA"], "FGM": a["FGM"],
            "PPP": a["PPS"], "FG%": a["FG%"], "eFG": a["eFG"], "SCE": a["SCE"],
            "share": _safe(a["FGA"], tagged)})
    rows.sort(key=lambda r: -r["poss"])
    return {"rows": rows, "total_tagged": tagged}


# ── league baseline + percentiles ─────────────────────────────────────────────────
def _baseline_from_events(events, offense=True):
    """One pool of team PPPs per defense key (the baseline the percentiles rank
    against). Mirrors playtypes._named_baseline_from_events."""
    pool = {k: [] for k, *_ in DEFENSES}
    for tid in PT._shooter_teams(events):
        td = team_defenses(tid, events=events, offense=offense)
        for r in td["rows"]:
            if r["poss"] >= MIN_POSS:
                pool[r["key"]].append(r["PPP"])
    return pool


def team_defense_percentiles(team_id, gender=None, game_ids=None, events=None,
                             offense=True, baseline=None):
    """team_defenses PLUS each scheme's **league percentile** + tier (good already
    encoded — on defense, allowing fewer points ranks higher). Self-contained:
    with no events/baseline it does one tracked-game pass for the gender and ranks
    the team off that same pass. Rows below MIN_POSS / pools below MIN_POOL get
    pct=None ("thin sample", never a fake rank).

    Returns {'rows':[{...team_defenses row, pct, tier, color, lg_ppp}],
    'total_tagged','untagged','offense'}."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    if baseline is None:
        baseline = _baseline_from_events(events, offense=offense)
    td = team_defenses(team_id, events=events, offense=offense)
    rows = []
    for r in td["rows"]:
        pool = baseline.get(r["key"], [])
        ranked = r["poss"] >= MIN_POSS and len(pool) >= MIN_POOL
        pct = TA.percentile(r["PPP"], pool, higher_better=offense) if ranked else None
        tier_label, tier_color = _tier(pct)
        rows.append({**r, "pct": pct, "tier": tier_label, "color": tier_color,
                     "lg_ppp": (sum(pool) / len(pool)) if pool else None})
    return {"rows": rows, "total_tagged": td["total_tagged"],
            "untagged": td["untagged"], "offense": offense}


# ── per-defense SHOT PROFILE (cross-dimension — reuses playtypes' machinery) ───────
def team_defense_shot_profiles(team_id, gender=None, game_ids=None, events=None,
                               offense=True):
    """Per-scheme SHOT PROFILE: each defense with PPP/FG%/eFG PLUS the cross-
    dimension read — 3PA-rate, rim/mid share, assisted-rate, open-rate, zone
    distribution (top_zone = where shots come from vs the scheme) and average
    possession length. offense=False = what each of the team's schemes ALLOWS
    ("their 2-3 gives up corner 3s"); offense=True = how the team shoots vs each
    scheme it faces. Returns {key: profile} for schemes actually present."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    profs = {}
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        d = _norm(e.get("defense"))
        if not d:
            continue
        PT._profile_add(profs.setdefault(d, PT._blank_profile()), e)
    return {k: PT._profile_fin(p, k, _LABEL.get(k, k)) for k, p in profs.items()}


# ══════════════════════════════════════════════════════════════════════════════
#  CROSS-TAB  —  play_type × defense  ("their PnR vs a 2-3 zone")
# ══════════════════════════════════════════════════════════════════════════════
# The overlap the offense side can't give: how each set call performs against each
# defensive scheme. Only shots carrying BOTH tags land in a cell. Sparse by
# nature (it needs dense double-tagging), so every consumer must gate on poss.
def cross_play_defense(team_id, gender=None, game_ids=None, events=None,
                       offense=True, min_poss=10):
    """play_type × defense cross-tab for a team's own shots (offense) or the shots
    it allowed (defense).

    Returns {
      'matrix': {play_key: {def_key: {poss,FGM,PPP,FG%,eFG,stable}}},
      'plays':   [present play keys, in NAMED_PLAY_TYPES order],
      'defenses':[present defense keys, in DEFENSES order],
      'play_label': {k: label}, 'def_label': {k: label},
      'tagged': n}   # shots that had BOTH a play_type and a defense
    `stable` flags cells with poss >= min_poss (the rest are too thin to trust)."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    cells = {}                       # (play_key, def_key) -> shot list
    tagged = 0
    for e in events:
        if e["event_type"] != "shot" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        pk = e.get("play_type")
        dk = _norm(e.get("defense"))
        if not pk or not dk:
            continue
        if pk not in PT._NAMED_KEYS:
            pk = "other"
        tagged += 1
        cells.setdefault((pk, dk), []).append(e)

    matrix = {}
    plays_present, defs_present = set(), set()
    for (pk, dk), shots in cells.items():
        a = TA.agg_shots(shots)
        matrix.setdefault(pk, {})[dk] = {
            "poss": a["FGA"], "FGM": a["FGM"], "PPP": a["PPS"],
            "FG%": a["FG%"], "eFG": a["eFG"], "stable": a["FGA"] >= min_poss}
        plays_present.add(pk)
        defs_present.add(dk)
    plays = [k for k, _ in PT.NAMED_PLAY_TYPES if k in plays_present]
    defenses = [k for k, *_ in DEFENSES if k in defs_present]
    return {
        "matrix": matrix, "plays": plays, "defenses": defenses,
        "play_label": {k: lbl for k, lbl in PT.NAMED_PLAY_TYPES},
        "def_label": dict(_LABEL), "tagged": tagged,
    }


# ── forced / committed turnovers per defense (the press disruption read) ──────────
def team_defense_turnovers(team_id, gender=None, game_ids=None, events=None,
                           offense=True):
    """Turnovers tagged under each scheme — the press/trap disruption PPP-on-shots
    can't show. offense=False = TOs the team's defense FORCED (opponent lost it
    under the scheme); offense=True = TOs the team COMMITTED vs each scheme.
    Returns {'rows':[{key,label,family,tovs,share}],'total'} sorted by volume —
    only schemes with at least one tagged turnover."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    counts = {}
    total = 0
    for e in events:
        if e["event_type"] != "turnover" or e["shooter_team_id"] is None:
            continue
        # fetch_events joins shooter_team_id off primary_player_id, which for a
        # turnover is the player who committed it -> the committing team.
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        d = _norm(e.get("defense"))
        if not d:
            continue
        counts[d] = counts.get(d, 0) + 1
        total += 1
    rows = [{"key": k, "label": _LABEL.get(k, k), "family": _FAMILY.get(k, "other"),
             "tovs": n, "share": _safe(n, total)}
            for k, n in counts.items()]
    rows.sort(key=lambda r: -r["tovs"])
    return {"rows": rows, "total": total}


def team_defense_fouls(team_id, gender=None, game_ids=None, events=None,
                       offense=True):
    """Fouls tagged under each scheme — the line-risk read (a press/trap that
    fouls hands the ball back at the stripe). offense=False = fouls the team
    COMMITTED while running each scheme (the defensive cost); offense=True = fouls
    the team DREW vs each scheme it faced (we get to the line vs X).
    Returns {'rows':[{key,label,family,fouls,share}],'total'} sorted by volume —
    only schemes with at least one tagged foul.

    Foul rows: primary_player_id is the player FOULED, so fetch_events joins
    shooter_team_id = the FOULED (offensive) team. So (shooter_team_id==team_id)
    ==offense means: offense=True -> we were fouled (drew it); offense=False ->
    the opponent was fouled, i.e. WE committed it under our scheme. The same
    convention every other split here uses, so the orientation matches."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    own = None if offense else TA.event_team_games(team_id, events)
    counts = {}
    total = 0
    for e in events:
        if e["event_type"] != "foul" or e["shooter_team_id"] is None:
            continue
        if offense != (e["shooter_team_id"] == team_id):
            continue
        if own is not None and e["game_id"] not in own:
            continue
        d = _norm(e.get("defense"))
        if not d:
            continue
        counts[d] = counts.get(d, 0) + 1
        total += 1
    rows = [{"key": k, "label": _LABEL.get(k, k), "family": _FAMILY.get(k, "other"),
             "fouls": n, "share": _safe(n, total)}
            for k, n in counts.items()]
    rows.sort(key=lambda r: -r["fouls"])
    return {"rows": rows, "total": total}


# ── league leaderboards per scheme ────────────────────────────────────────────────
def league_defense_leaders(gender=None, game_ids=None, events=None, offense=False,
                           min_poss=MIN_POSS, baseline=None):
    """League leaderboard per defense: for each scheme, the teams ranked by PPP
    (offense=False — the DEFAULT — = who defends it best, fewest points allowed
    first; offense=True = who attacks it best). The team-facing companion to
    team_defense_percentiles.

    Returns {key: {'label','family','lg_ppp','leaders':[{team_id,PPP,FG%,poss,
    share,pct,tier,color}]}} — only schemes with at least one team above min_poss."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    per_team = {tid: team_defenses(tid, events=events, offense=offense)
                for tid in PT._shooter_teams(events)}
    if baseline is None:
        baseline = {k: [] for k, *_ in DEFENSES}
        for _tid, td in per_team.items():
            for r in td["rows"]:
                if r["poss"] >= min_poss:
                    baseline[r["key"]].append(r["PPP"])
    out = {}
    for key, lbl, fam in DEFENSES:
        pool = baseline.get(key, [])
        leaders = []
        for tid, td in per_team.items():
            cell = next((r for r in td["rows"] if r["key"] == key), None)
            if not cell or cell["poss"] < min_poss:
                continue
            pct = (TA.percentile(cell["PPP"], pool, higher_better=offense)
                   if len(pool) >= MIN_POOL else None)
            tier_label, tier_color = _tier(pct)
            leaders.append({"team_id": tid, "PPP": cell["PPP"], "FG%": cell["FG%"],
                            "poss": cell["poss"], "share": cell["share"],
                            "pct": pct, "tier": tier_label, "color": tier_color})
        # offense -> highest PPP first; defense -> lowest allowed first
        leaders.sort(key=lambda x: x["PPP"], reverse=offense)
        if leaders:
            out[key] = {"label": lbl, "family": fam,
                        "lg_ppp": (sum(pool) / len(pool)) if pool else None,
                        "leaders": leaders}
    return out


# ── per-player: how each player does vs each defense FACED ─────────────────────────
def player_defenses_faced(gender=None, game_ids=None, events=None,
                          min_poss=MIN_PLAYER_POSS, min_pool=MIN_POOL):
    """Per-PLAYER PPP by the defense FACED on their own shots, each ranked vs the
    league pool of players' PPP vs that same scheme. (Defense is a team concept,
    so the player view is offense-only: how a scorer handles each scheme thrown at
    them — "their #3 cooks man but stalls vs the 2-3.")

    Returns {player_id: {def_key: {poss,FGM,PPP,FG%,eFG,share,pct,tier,color,
    lg_ppp}}} — only the schemes a player has tagged attempts in. Empty until
    games carry defense tags, so it lights up as tracking fills in."""
    if events is None:
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    per = {}                          # pid -> def_key -> raw agg
    for e in events:
        if e["event_type"] != "shot" or e["primary_player_id"] is None:
            continue
        d = _norm(e.get("defense"))
        if not d:
            continue
        cell = per.setdefault(e["primary_player_id"], {}).setdefault(
            d, {"FGA": 0, "FGM": 0, "FG3A": 0, "FG3M": 0, "PTS": 0})
        cell["FGA"] += 1
        is3 = e["shot_type"] == 3
        if is3:
            cell["FG3A"] += 1
        if e["shot_result"] == "make":
            cell["FGM"] += 1
            cell["PTS"] += 3 if is3 else 2
            if is3:
                cell["FG3M"] += 1
    pools = {}
    for _pid, d in per.items():
        for key, c in d.items():
            if c["FGA"] >= min_poss:
                pools.setdefault(key, []).append(_safe(c["PTS"], c["FGA"]))
    out = {}
    for pid, d in per.items():
        tot = sum(c["FGA"] for c in d.values())
        row = {}
        for key, c in d.items():
            ppp = _safe(c["PTS"], c["FGA"])
            pool = pools.get(key, [])
            ranked = c["FGA"] >= min_poss and len(pool) >= min_pool
            pct = TA.percentile(ppp, pool, higher_better=True) if ranked else None
            tier_label, tier_color = _tier(pct)
            row[key] = {
                "key": key, "label": _LABEL.get(key, key),
                "family": _FAMILY.get(key, "other"),
                "poss": c["FGA"], "FGM": c["FGM"], "PPP": ppp,
                "FG%": _safe(c["FGM"], c["FGA"]),
                "eFG": _safe(c["FGM"] + 0.5 * c["FG3M"], c["FGA"]),
                "share": _safe(c["FGA"], tot), "pct": pct,
                "tier": tier_label, "color": tier_color,
                "lg_ppp": (sum(pool) / len(pool)) if pool else None}
        out[pid] = row
    return out
