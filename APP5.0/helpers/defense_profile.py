"""defense_profile.py — the DEFENSIVE mirror of the offensive shot/role profile,
built out of SHARES rather than rates.

WHY SHARES, AND WHY THIS MODULE EXISTS
--------------------------------------
The app already knows a great deal about what a player DOES on offense: their
shot diet by band, their play-type mix, how much of their shot volume they
create themselves. It knows almost nothing about what a player FACES on
defense, and the little it does know is stored as a rate — DSHOT%, RimDef,
PerimDef, "FG% allowed" — which is the one form the measured reliability book
says a high-school sample cannot support (`reliability.MEASURED`: player rim
FG% predicts itself at SB .11; player band SHARE at SB .70-.92).

Everything on offense ports to defense if you express it as a rate or a share
of a defender's own workload. That is what this module does. For every player
tagged as the nearest defender (`guarded_by_id`) it computes:

  * **the assignment diet** — what share of the shots they contest come from
    each depth band, each shot kind, each play type, and each creation bucket.
    "41% of what she guards is a rim attempt" is an assignment fact, not a
    make-rate, so it survives a thin book.
  * **the defensive load share (DLOAD%)** — of the opponent shots tagged with
    ANY defender while this player was on the floor, what share did THIS player
    contest. League average is 1/5 = 20% by construction. A player at 32% is
    the point of attack; a player at 9% is being hidden. Both numerator and
    denominator are drawn from the tagged subset, so a game where the tracker
    tagged fewer contests moves neither — the diligence confound cancels.
  * **the defensive footprint** — the opponent's own shot diet while this
    player is on the floor versus while they sit. A rim-share that collapses
    when a player checks in is a wall; a three-share that spikes is a defense
    that is running shooters off the line (or dying on closeouts).

The allowed FG% / PPS ride along because a coach will ask for them and they are
a record of what happened, but they are marked `descriptive` — see
`reliability`'s description-is-not-prediction rule. Nothing in here builds a
prose verdict on an allowed percentage.

Coverage is honest by construction: `guarded_by_id` is an opt-in per-shot tap
(2,891 of 4,019 shots on the live book), so every read carries its own `n` and
the module returns empty rather than thin when a defender is under the gate.

Streamlit-free, DB-free except for the optional on-floor join. Wrap in a cache
at the page level.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S
import helpers.shot_kinds as SK


#: Minimum contested shots before a defender's DIET is reported. Shares
#: stabilize fast (they are count ratios), but under ~12 the denominator itself
#: is the noise — a 3-shot "diet" is a list, not a distribution.
MIN_CONTESTED = 12

#: Minimum tagged opponent shots on the floor before DLOAD% is reported.
MIN_LOAD_DENOM = 40

#: Minimum opponent shots on each side of the on/off split for the footprint.
MIN_FOOTPRINT = 60

#: The creation buckets, in the order they read as a defensive story:
#: `self` = attacked off the dribble with no setup, `pass` = spot-up / catch,
#: `sc` = shot created by a screen or off-ball action, `both` = both tagged.
CREATION_LABELS = {
    "self": "off the dribble",
    "pass": "off the catch",
    "sc": "off an action",
    "both": "off an action & a pass",
}

# ── the ACTION grouping (measured 2026-07-26) ────────────────────────────────
# Individual play-type assignment shares do not repeat: isolation share measures
# SB -.15, worse than anything in the offensive book. Rolled up to ON-BALL vs
# OFF-BALL they do — .373 / .347 within team — which is the same lesson the band
# axis taught (rim04 alone .26, rolled up to paint .578). Two groups is the
# right coarseness: splitting on-ball back into ball-screen and iso/post
# collapses it again (.215 / .088), because that split is once more the
# opponent's call rather than the defender's job.
#
# The distinction the two groups encode is a real difference in what a defender
# is asked to do: contain a live dribble, or navigate screens and close out.
PLAY_FAMILIES = {
    "iso": "onball", "pnr": "onball", "post": "onball", "dho": "onball",
    "spot": "offball", "offscreen": "offball", "cut": "offball",
    "duckin": "offball",
    "transition": "transition",
    "putback": "broken", "blob": "broken", "slob": "broken",
}

PLAY_FAMILY_LABELS = {
    "onball": "on the ball", "offball": "off the ball",
    "transition": "in transition", "broken": "in broken play",
}

#: Scheme families whose per-defender share survives the within-team test, and
#: therefore says something about the PLAYER rather than about her coach.
#: `press` is deliberately absent: pooled it measures SB .541, but demeaned
#: within its own team it is .050 — it was entirely "which team she plays for".
PLAYER_SCHEME_FAMILIES = ("man", "zone")


def _shares(counts):
    """{key: count} → ({key: share}, total). Empty in, ({} , 0) out."""
    tot = sum(counts.values())
    if not tot:
        return {}, 0
    return {k: v / tot for k, v in counts.items()}, tot


def _play_label(key):
    try:
        import helpers.playtypes as PT
        return dict(PT.NAMED_PLAY_TYPES).get(key, key)
    except Exception:
        return key


# ══════════════════════════════════════════════════════════════════════════════
#  1. THE ASSIGNMENT DIET — what a defender is asked to guard
# ══════════════════════════════════════════════════════════════════════════════

def defender_diets(events, min_shots=MIN_CONTESTED, team_id=None):
    """{defender_id: diet} — the SHARE breakdown of what each defender faces.

    A "contested shot" here is a shot carrying this player in `guarded_by_id`;
    that is the tracker's nearest-defender tap, so it is the assignment, not a
    claim that the shot was well contested.

    Each diet carries, all as shares of that defender's own contested volume:

        band     {rim04|two419|arc3|deep3: share}    depth of the look faced
        kind     {rim|floater|mid|corner3|abovebreak3: share}
        play     {play_type: share}                  the action run at them
        creation {self|pass|sc|both: share}          how the shot was manufactured
        three_share / rim_share / paint_share        the headline collapses
        drive_share                                  faced off the dribble
        catch_share                                  faced off the catch

    plus the descriptive record of what dropped (`FGA`, `FGM`, `FG%`, `PTS`,
    `PPS`, `three_FGA`, `three_FG%`) and `n` = FGA. Defenders below `min_shots`
    contested attempts are omitted entirely rather than reported thin.

    `team_id` (optional) restricts to defenders on that roster.
    """
    roster = None
    if team_id is not None:
        from database.db import query
        roster = {r["id"] for r in
                  query("SELECT id FROM players WHERE team_id=?", (team_id,))}

    import helpers.defenses as DEF

    raw = defaultdict(lambda: {
        "band": defaultdict(int), "kind": defaultdict(int),
        "play": defaultdict(int), "creation": defaultdict(int),
        "family": defaultdict(int), "scheme": defaultdict(int),
        "FGA": 0, "FGM": 0, "PTS": 0, "three_FGA": 0, "three_FGM": 0,
        "paint": 0,
    })
    for e in events:
        if e["event_type"] != "shot":
            continue
        did = e.get("guarded_by_id")
        if did is None or (roster is not None and did not in roster):
            continue
        c = raw[did]
        x, y, stype = e.get("shot_x"), e.get("shot_y"), e.get("shot_type")
        band = SK.classify_band(x, y, stype)
        kind = SK.classify(x, y, stype)
        c["band"][band] += 1
        c["kind"][kind] += 1
        if e.get("play_type"):
            c["play"][e["play_type"]] += 1
            fam = PLAY_FAMILIES.get(e["play_type"])
            if fam:
                c["family"][fam] += 1
        _d = DEF._norm(e.get("defense"))
        if _d:
            _fam = DEF._FAMILY.get(_d)
            if _fam:
                c["scheme"][_fam] += 1
        c["creation"][S._creation_bucket(e["pass_from_id"] is not None,
                                         e["shot_created_by_id"] is not None)] += 1
        c["FGA"] += 1
        is3 = stype == 3
        if is3:
            c["three_FGA"] += 1
        if band in ("rim04", "two419"):
            c["paint"] += 1
        if e["shot_result"] == "make":
            c["FGM"] += 1
            c["PTS"] += 3 if is3 else 2
            if is3:
                c["three_FGM"] += 1

    out = {}
    for did, c in raw.items():
        if c["FGA"] < min_shots:
            continue
        band_sh, _ = _shares(c["band"])
        kind_sh, _ = _shares(c["kind"])
        play_sh, play_n = _shares(c["play"])
        cre_sh, _ = _shares(c["creation"])
        fam_sh, fam_n = _shares(c["family"])
        sch_sh, sch_n = _shares(c["scheme"])
        n = c["FGA"]
        out[did] = {
            "n": n, "FGA": n, "FGM": c["FGM"], "PTS": c["PTS"],
            "FG%": S._safe(c["FGM"], n), "PPS": S._safe(c["PTS"], n),
            "three_FGA": c["three_FGA"],
            "three_FG%": S._safe(c["three_FGM"], c["three_FGA"]),
            "band": dict(band_sh), "band_n": dict(c["band"]),
            "kind": dict(kind_sh), "kind_n": dict(c["kind"]),
            "play": dict(play_sh), "play_n": dict(c["play"]),
            "play_total": play_n,
            "creation": dict(cre_sh), "creation_n": dict(c["creation"]),
            # the grouped axes — the cuts that survived a split season
            "family": dict(fam_sh), "family_n": dict(c["family"]),
            "family_total": fam_n,
            "scheme": dict(sch_sh), "scheme_n": dict(c["scheme"]),
            "scheme_total": sch_n,
            "onball_share": fam_sh.get("onball", 0.0),
            "offball_share": fam_sh.get("offball", 0.0),
            "man_share": sch_sh.get("man", 0.0),
            "zone_share": sch_sh.get("zone", 0.0),
            "three_share": S._safe(c["three_FGA"], n),
            "rim_share": band_sh.get("rim04", 0.0),
            "paint_share": S._safe(c["paint"], n),
            "drive_share": cre_sh.get("self", 0.0),
            "catch_share": cre_sh.get("pass", 0.0) + cre_sh.get("both", 0.0),
        }
    return out


#: The reads whose pooled reliability is dominated by WHICH TEAM a player is on,
#: and which therefore have to be scored against her own teammates rather than
#: against the league. Man-defense share is the clearest case: pooled it
#: measures SB .734, demeaned within its team .321 — so a league-scored line
#: saying "she plays a lot of man" would mostly be saying "her team plays man".
TEAM_RELATIVE = ("onball_share", "offball_share", "man_share", "zone_share")

#: A team needs this many qualifying defenders before a within-team comparison
#: means anything — with two, each is just the other's mirror image.
MIN_TEAMMATES = 3


def team_relative(diets, team_of=None, keys=TEAM_RELATIVE,
                  min_mates=MIN_TEAMMATES):
    """Add `<key>_vs_team` residuals: each share minus her own team's mean.

    This is the form the measurement validated. The raw share repeats well for
    scheme reads, but almost all of that repeatability is between TEAMS — a
    coach's scheme choice, not a player trait. Subtracting the team mean leaves
    the part that is about the player: is SHE used differently from the four
    beside her.

    Players on a team with fewer than `min_mates` qualifying defenders get no
    residual at all rather than a zero, because with one or two teammates the
    residual is an artefact of the arithmetic instead of a comparison.
    """
    if team_of is None:
        from database.db import query
        team_of = {r["id"]: r["team_id"]
                   for r in query("SELECT id, team_id FROM players")}
    by_team = defaultdict(list)
    for pid in diets:
        by_team[team_of.get(pid)].append(pid)
    for tid, mates in by_team.items():
        if tid is None or len(mates) < min_mates:
            continue
        for key in keys:
            vals = [diets[p].get(key) for p in mates]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            mean = sum(vals) / len(vals)
            for p in mates:
                v = diets[p].get(key)
                if v is not None:
                    diets[p][f"{key}_vs_team"] = v - mean
                    diets[p][f"{key}_team_mean"] = mean
    return diets


def diet_pools(diets):
    """League pools for the diet shares, for z-scoring one defender vs the field.

    Returns {"band": {band: [shares]}, "kind": {...}, "play": {...},
             "creation": {...}, "scalar": {name: [values]}}. Only defenders who
    actually face a category contribute to it — a defender who has never been
    tagged on a corner three is absent from that pool rather than counted as a
    zero, because zero-share and never-faced are different facts.
    """
    pools = {"band": defaultdict(list), "kind": defaultdict(list),
             "play": defaultdict(list), "creation": defaultdict(list),
             "scalar": defaultdict(list)}
    for d in diets.values():
        for axis in ("band", "kind", "play", "creation"):
            for key, share in d[axis].items():
                pools[axis][key].append(share)
        for name in ("three_share", "rim_share", "paint_share",
                     "drive_share", "catch_share", "FG%", "PPS"):
            v = d.get(name)
            if v is not None:
                pools["scalar"][name].append(v)
    return {k: dict(v) for k, v in pools.items()}


#: Phantom attempts pulling a defender's category share toward the league's.
#: Without it the extreme edges are all tiny cells — the live book's top raw
#: edges were a 58% deep-three share on SEVEN shots and a 62% isolation share
#: on FIVE, which are sampling accidents wearing a percentage. At k=10 a cell
#: needs roughly its own size again in evidence before it reads as a tendency.
EDGE_PRIOR_K = 10.0

#: A category cell below this count is not reported as an edge at all, however
#: it shrinks — a coach cannot act on "she guarded three off-screen actions".
EDGE_MIN_N = 5


def diet_edges(diets, pools=None, min_pool=6, k=EDGE_PRIOR_K, min_n=EDGE_MIN_N):
    """{defender_id: [edge, ...]} — each defender's most EXTREME assignment
    shares versus the league of defenders, ranked by |z| of the SHRUNK share.

    An edge is {"axis","key","label","share","share_shrunk","lg_share","z","n"}.
    This is the "what is this player actually asked to do" read: an iso
    defender's `play` edge on isolation, a rim protector's `band` edge on
    rim04, a closeout specialist's spike on spot-ups. Every edge is a SHARE,
    which is the form the measured book supports at the player level
    (`reliability.MEASURED`: player band share SB .81, player rim FG% SB .11).

    `share` is what actually happened and is what a caller should PRINT;
    `share_shrunk` is what the ranking is done on, so a 5-of-8 cell cannot
    out-rank a 40-of-120 tendency. Both are returned so the display never has
    to lie about the raw count behind a line.
    """
    if pools is None:
        pools = diet_pools(diets)
    out = {}
    for did, d in diets.items():
        edges = []
        total = d["n"]
        for axis in ("band", "kind", "play", "creation"):
            # play shares are shares of the TAGGED-play subset, not of every
            # contested shot, so the credibility denominator differs by axis
            denom = d["play_total"] if axis == "play" else total
            for key, share in d[axis].items():
                pool = pools.get(axis, {}).get(key) or []
                if len(pool) < min_pool:
                    continue
                cnt = d.get(f"{axis}_n", {}).get(key, 0)
                if cnt < min_n:
                    continue
                m = sum(pool) / len(pool)
                sd = (sum((v - m) ** 2 for v in pool) / len(pool)) ** 0.5
                if sd < 1e-9:
                    continue
                shrunk = ((cnt + k * m) / (denom + k)) if denom else m
                label = (_play_label(key) if axis == "play"
                         else CREATION_LABELS.get(key, key) if axis == "creation"
                         else SK.BAND_LABELS.get(key, key) if axis == "band"
                         else SK.KIND_LABELS.get(key, key))
                edges.append({"axis": axis, "key": key, "label": label,
                              "share": share, "share_shrunk": shrunk,
                              "lg_share": m, "z": (shrunk - m) / sd,
                              "n": cnt, "denom": denom})
        edges.sort(key=lambda e: -abs(e["z"]))
        if edges:
            out[did] = edges
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  2. DEFENSIVE LOAD SHARE — who the offense actually attacks
# ══════════════════════════════════════════════════════════════════════════════

def defender_load(events, floor=None, game_ids=None, min_denom=MIN_LOAD_DENOM):
    """{player_id: {"load","contested","denom","team_id"}} — DLOAD%, the
    defensive twin of USG%.

        DLOAD% = shots this player contested
                 ─────────────────────────────────────────────────────────
                 opponent shots tagged with ANY defender while they were on

    Five players share every possession, so the league mean is 20% BY
    CONSTRUCTION — which is what makes the number readable without a pool: 32%
    is a point-of-attack defender being hunted, 9% is a player the offense is
    deliberately avoiding (or one being hidden in a zone).

    Both sides of the ratio come from the TAGGED subset, so a game the tracker
    tagged sparsely shrinks numerator and denominator together and the estimate
    is unmoved. That is the whole reason this is expressed as a share of tagged
    contests rather than as contests per opponent shot.

    `floor` = lineups._event_floor() output ({event_id: {team_id: frozenset}}).
    Fetched here when not supplied. Returns {} when the on-floor snapshots are
    missing, because without them the denominator is not defined.
    """
    if floor is None:
        try:
            import helpers.lineups as LU
            floor = LU._event_floor(game_ids)
        except Exception:
            return {}
    if not floor:
        return {}

    contested = defaultdict(int)
    denom = defaultdict(int)
    team_of = {}
    for e in events:
        if e["event_type"] != "shot" or e.get("guarded_by_id") is None:
            continue
        did = e["guarded_by_id"]
        contested[did] += 1
        onfloor = floor.get(e["id"])
        if not onfloor:
            continue
        shooter_team = e.get("shooter_team_id")
        for tid, five in onfloor.items():
            if shooter_team is not None and tid == shooter_team:
                continue          # the offense's own five isn't defending
            for pid in five:
                denom[pid] += 1
                team_of.setdefault(pid, tid)

    out = {}
    for pid, dn in denom.items():
        if dn < min_denom:
            continue
        out[pid] = {"load": contested.get(pid, 0) / dn,
                    "contested": contested.get(pid, 0), "denom": dn,
                    "team_id": team_of.get(pid)}
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  3. DEFENSIVE FOOTPRINT — what the opponent's shot diet does when you're on
# ══════════════════════════════════════════════════════════════════════════════

def defensive_footprint(events, floor=None, game_ids=None,
                        min_side=MIN_FOOTPRINT):
    """{player_id: {"on": diet, "off": diet, "delta": {...}}} — the opponent's
    own shot diet with this player on the floor versus off it.

    This is the read behind "she checks in and the paint closes": a rim-share
    that drops 9 points when a player is on, or a three-share that spikes
    because the defense is chasing shooters off the line and giving up the
    corner. It is a share-of-opponent-shots on both sides, so it is not a
    make-rate and does not inherit the rim-FG% reliability problem.

    It is NOT teammate-adjusted — the four players beside them move with them,
    exactly as with raw on/off. Treat it as a description of what happened while
    they were out there, and lean on the RAPM/DRAPM anchors for causal claims.
    Each side needs `min_side` opponent shots or the player is omitted.
    """
    if floor is None:
        try:
            import helpers.lineups as LU
            floor = LU._event_floor(game_ids)
        except Exception:
            return {}
    if not floor:
        return {}

    # Who DRESSED, per game per team. The off-floor sample must only contain
    # games a player was actually available for — pooling one global roster
    # would charge a player with every shot of every game they never travelled
    # to, which is the single easiest way to fake an on/off effect.
    ev_game = {e["id"]: e.get("game_id") for e in events}
    played = defaultdict(lambda: defaultdict(set))     # gid -> tid -> {pid}
    team_of = {}
    for eid, teams in floor.items():
        gid = ev_game.get(eid)
        if gid is None:
            continue
        for tid, five in teams.items():
            played[gid][tid] |= set(five)
            for pid in five:
                team_of.setdefault(pid, tid)

    def _blank():
        return {"n": 0, "rim": 0, "three": 0, "paint": 0, "pts": 0, "made": 0}

    on = defaultdict(_blank)
    off = defaultdict(_blank)

    def _add(c, band, is3, made, pts):
        c["n"] += 1
        c["rim"] += 1 if band == "rim04" else 0
        c["paint"] += 1 if band in ("rim04", "two419") else 0
        c["three"] += 1 if is3 else 0
        c["made"] += 1 if made else 0
        c["pts"] += pts

    for e in events:
        if e["event_type"] != "shot":
            continue
        onfloor = floor.get(e["id"])
        if not onfloor:
            continue
        shooter_team = e.get("shooter_team_id")
        band = SK.classify_band(e.get("shot_x"), e.get("shot_y"),
                                e.get("shot_type"))
        is3 = e.get("shot_type") == 3
        made = e["shot_result"] == "make"
        pts = (3 if is3 else 2) if made else 0
        dressed = played.get(e.get("game_id")) or {}
        for tid, five in onfloor.items():
            if shooter_team is not None and tid == shooter_team:
                continue                      # this five is the OFFENSE
            for pid in five:
                _add(on[pid], band, is3, made, pts)
            for pid in (dressed.get(tid) or ()):
                if pid not in five:
                    _add(off[pid], band, is3, made, pts)

    def _diet(c):
        n = c["n"]
        return {"n": n, "rim_share": c["rim"] / n, "paint_share": c["paint"] / n,
                "three_share": c["three"] / n, "opp_pps": c["pts"] / n,
                "opp_fg": c["made"] / n}

    out = {}
    for pid in set(on) | set(off):
        a, b = on.get(pid), off.get(pid)
        if not a or not b or a["n"] < min_side or b["n"] < min_side:
            continue
        da, db = _diet(a), _diet(b)
        out[pid] = {"on": da, "off": db, "team_id": team_of.get(pid),
                    "delta": {k: da[k] - db[k] for k in
                              ("rim_share", "paint_share", "three_share",
                               "opp_pps", "opp_fg")}}
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  4. TEAM: the shot diet a defense ALLOWS
# ══════════════════════════════════════════════════════════════════════════════

def team_allowed_diet(events, team_ids=None):
    """{team_id: {"band": {band: share}, "n", "opp_pps", ...}} — the depth
    profile of the shots each defense gives up, as shares of opponent attempts.

    The direct mirror of the offensive shot diet, and the same reliability
    footing: team band SHARE measured SB .88 in the book, team per-band FG% is
    unmeasurable at six teams. So this reports WHAT a defense concedes, never
    how well opponents shot it.

    Needs `shooter_team_id` on the events (S.fetch_events supplies it); the
    defending team is inferred as the game's other team.
    """
    from database.db import query
    gids = {e["game_id"] for e in events if e.get("game_id") is not None}
    if not gids:
        return {}
    ph = ",".join("?" * len(gids))
    opp = {}
    for r in query(f"SELECT id, team1_id t1, team2_id t2 FROM games "
                   f"WHERE id IN ({ph})", tuple(gids)):
        opp[r["id"]] = (r["t1"], r["t2"])

    raw = defaultdict(lambda: {"band": defaultdict(int), "n": 0, "pts": 0,
                               "made": 0, "three": 0, "guarded": 0})
    for e in events:
        if e["event_type"] != "shot":
            continue
        pair = opp.get(e["game_id"])
        st_ = e.get("shooter_team_id")
        if not pair or st_ is None:
            continue
        dteam = pair[1] if pair[0] == st_ else pair[0]
        if team_ids is not None and dteam not in team_ids:
            continue
        c = raw[dteam]
        band = SK.classify_band(e.get("shot_x"), e.get("shot_y"),
                                e.get("shot_type"))
        c["band"][band] += 1
        c["n"] += 1
        is3 = e.get("shot_type") == 3
        c["three"] += 1 if is3 else 0
        c["guarded"] += 1 if e.get("guarded_by_id") is not None else 0
        if e["shot_result"] == "make":
            c["made"] += 1
            c["pts"] += 3 if is3 else 2

    out = {}
    for tid, c in raw.items():
        if not c["n"]:
            continue
        sh, n = _shares(c["band"])
        out[tid] = {"n": n, "band": dict(sh), "band_n": dict(c["band"]),
                    "three_share": c["three"] / n,
                    "contest_share": c["guarded"] / n,
                    "opp_pps": c["pts"] / n, "opp_fg": c["made"] / n}
    return out
