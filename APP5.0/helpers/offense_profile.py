"""offense_profile.py — the OFFENSIVE half of the shot/role profile.

WHY THIS MODULE EXISTS
----------------------
`defense_profile.py` opens by saying it is "the DEFENSIVE mirror of the
offensive shot/role profile". That offensive profile was never actually
assembled. Its pieces were real but scattered — the shot diet on Charts, the
play-type mix on the playstyle tab, the creation split inside the scout cards —
and no surface put a roster's offensive roles beside each other the way the
Insights Defense tab does for assignments. So the app shipped a mirror of
something that did not exist, and the offense, which is the side the
measurement actually supports, had the weaker page.

This module assembles it in the SAME SHAPE as `defender_diets`, deliberately.
`defense_profile.team_relative`, `diet_pools` and `diet_edges` are generic over
that shape, so both sides share one implementation and cannot drift apart. Where
a concept has no offensive twin it is absent rather than faked.

THE MEASUREMENT POINTS THE OTHER WAY HERE, AND THAT IS THE HEADLINE
-------------------------------------------------------------------
`reliability.MEASURED_DEFENDER_NOTE` records that defensive assignment shares
measure SB .17–.64 against offensive shares' .70–.92, "because the assignment is
chosen by the opponent, not by the player". Read forwards, that same sentence is
the case for this module: an offensive share IS the player's own choice, and it
is the most repeatable thing in the book.

    ("player", "band_share")      SB .81   the depth diet — STABLE
    ("player", "playtype_share")  SB .761  the action axis (iso; spot .882)
    ("player", "kind_share")      SB .70   the angular cut
    ("player", "band_fg")         SB .52   4ft-to-arc, the only band that clears
    ("player", "pps")             SB .48   descriptive
    ("player", "kind_fg")         SB .11   rim FG% — WITHHELD, never a trait
    ("player", "playtype_ppp")   SB -.135  spot-up PPP — WITHHELD

So the ordering rule for anything rendered off this module is the same one the
defense board uses and the opposite of what a coach would ask for first: lead
with the shares, put the rates last and mark them descriptive, and never let a
per-player rim percentage carry a verdict.

Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S
import helpers.shot_kinds as SK
from helpers.defense_profile import (
    CREATION_LABELS, PLAY_FAMILIES, PLAY_FAMILY_LABELS, _shares,
)

__all__ = [
    "shooter_diets", "shooter_load", "offensive_footprint", "team_own_diet",
    "CREATION_LABELS", "PLAY_FAMILIES", "PLAY_FAMILY_LABELS",
    "MIN_SHOTS", "MIN_LOAD_DENOM", "MIN_FOOTPRINT", "TEAM_RELATIVE",
]

#: Minimum attempts before a shooter's DIET is reported. Matches the defensive
#: gate rather than `SK.MIN_PLAYER_SHARE_ATT` (20): that gate governs shares
#: shown as a standalone READ, where this table shows a whole roster at once and
#: a bench player's 12-shot diet is legitimate context beside a starter's 200.
#: Every row carries its own n, and the thin ones sort to the bottom.
MIN_SHOTS = 12

#: Minimum team shots on the floor before OLOAD% is reported.
MIN_LOAD_DENOM = 40

#: Minimum team shots on each side of the on/off split for the footprint.
MIN_FOOTPRINT = 60

#: Offensive shares that are mostly "which team she plays for" and so must be
#: scored against her own teammates. Transition share is the clear case: it is a
#: pace decision the coach makes for all five, exactly as man/zone share was on
#: defense. The band shares are deliberately NOT here — those are the player's
#: own shot selection and are the reads the .81 was measured on.
TEAM_RELATIVE = ("transition_share", "onball_share", "offball_share")


# ══════════════════════════════════════════════════════════════════════════════
#  1. THE SHOT DIET — what a player chooses to take
# ══════════════════════════════════════════════════════════════════════════════

def shooter_diets(events, min_shots=MIN_SHOTS, team_id=None):
    """{player_id: diet} — the SHARE breakdown of what each player shoots.

    Deliberately the same dict shape as `defense_profile.defender_diets`, keyed
    on the SHOOTER (`primary_player_id`) instead of the nearest defender, so the
    generic pool/edge/team-relative helpers over there serve both sides.

    Each diet carries, all as shares of that player's own attempts:

        band     {rim04|two419|arc3|deep3: share}    depth of the look taken
        kind     {rim|floater|mid|corner3|abovebreak3: share}
        play     {play_type: share}                  the action she scored off
        creation {self|pass|sc|both: share}          how the shot was manufactured
        family   {onball|offball|transition|broken}  the grouped action axis
        scheme   {man|zone: share}                   the coverage she shot INTO

    plus the descriptive record (`FGA`, `FGM`, `FG%`, `PTS`, `PPS`,
    `three_FGA`, `three_FG%`) and `n` = FGA.

    NOTE ON `scheme`: on defense this axis is the player's own job. On offense it
    is what the OPPONENT chose to play, so it is a record of the games played and
    not a trait — the same standing this module gives the play axis on defense.
    It is carried because a coach will ask "what do they do to us in zone", and
    it is captioned, never verdicted.

    `team_id` (optional) restricts to shooters on that roster.
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
        "paint": 0, "guarded": 0,
    })
    for e in events:
        if e["event_type"] != "shot":
            continue
        pid = e.get("primary_player_id")      # THE SHOOTER — see module docs
        if pid is None or (roster is not None and pid not in roster):
            continue
        c = raw[pid]
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
        c["creation"][S._creation_bucket(
            e["pass_from_id"] is not None,
            e["shot_created_by_id"] is not None)] += 1
        c["FGA"] += 1
        if e.get("guarded_by_id") is not None:
            c["guarded"] += 1
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
    for pid, c in raw.items():
        if c["FGA"] < min_shots:
            continue
        band_sh, _ = _shares(c["band"])
        kind_sh, _ = _shares(c["kind"])
        play_sh, play_n = _shares(c["play"])
        cre_sh, _ = _shares(c["creation"])
        fam_sh, fam_n = _shares(c["family"])
        sch_sh, sch_n = _shares(c["scheme"])
        n = c["FGA"]
        out[pid] = {
            "n": n, "FGA": n, "FGM": c["FGM"], "PTS": c["PTS"],
            "FG%": S._safe(c["FGM"], n), "PPS": S._safe(c["PTS"], n),
            "three_FGA": c["three_FGA"],
            "three_FG%": S._safe(c["three_FGM"], c["three_FGA"]),
            "band": dict(band_sh), "band_n": dict(c["band"]),
            "kind": dict(kind_sh), "kind_n": dict(c["kind"]),
            "play": dict(play_sh), "play_n": dict(c["play"]),
            "play_total": play_n,
            "creation": dict(cre_sh), "creation_n": dict(c["creation"]),
            "family": dict(fam_sh), "family_n": dict(c["family"]),
            "family_total": fam_n,
            "scheme": dict(sch_sh), "scheme_n": dict(c["scheme"]),
            "scheme_total": sch_n,
            "onball_share": fam_sh.get("onball", 0.0),
            "offball_share": fam_sh.get("offball", 0.0),
            "transition_share": fam_sh.get("transition", 0.0),
            "man_share": sch_sh.get("man", 0.0),
            "zone_share": sch_sh.get("zone", 0.0),
            "three_share": S._safe(c["three_FGA"], n),
            "rim_share": band_sh.get("rim04", 0.0),
            "paint_share": S._safe(c["paint"], n),
            # `drive_share` / `catch_share` keep the defensive module's names so
            # a renderer can hand either side's diet to the same formatter.
            "drive_share": cre_sh.get("self", 0.0),
            "catch_share": cre_sh.get("pass", 0.0) + cre_sh.get("both", 0.0),
            "assisted_share": cre_sh.get("pass", 0.0) + cre_sh.get("both", 0.0),
            "guarded_share": S._safe(c["guarded"], n),
        }
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  2. OLOAD% — the offensive twin of DLOAD%, and of usage
# ══════════════════════════════════════════════════════════════════════════════

def shooter_load(events, floor=None, game_ids=None, min_denom=MIN_LOAD_DENOM):
    """{player_id: {"load","shots","denom","team_id"}} — OLOAD%.

        OLOAD% = shots this player took
                 ────────────────────────────────────────────────
                 her team's shots while she was on the floor

    The exact mirror of DLOAD%, and it inherits the property that makes that
    number readable without a pool: five players share every shot, so **20% is
    average BY CONSTRUCTION**. 32% is a first option, 9% is a player the offense
    is not looking for.

    Precisely: every shot adds 1 to one player's numerator and 1 to each of the
    five on-floor denominators, so sum(shots)/sum(denom) is exactly 1/5. That is
    the DENOMINATOR-WEIGHTED mean, and it lands on 20.00% on the live book. The
    unweighted mean across a roster runs a little under (18.7-19.0%), because
    bench players carry small denominators — so "20%" is the line to read a
    single player against, not a total the column should sum to.

    This is USG%-shaped but it is not USG%: `stats.usage_pct` divides by
    possessions and folds in turnovers and the 0.44·FTA term. This is shots over
    team shots on the floor, which is the quantity the diet above is a
    breakdown OF — so the two numbers compose (her share of the team's shots ×
    her own band mix = her contribution to the team's diet) and USG% does not.
    Both are worth having; they are not the same column.

    `floor` = lineups._event_floor() output. Returns {} without it, because the
    denominator is undefined.
    """
    if floor is None:
        try:
            import helpers.lineups as LU
            floor = LU._event_floor(game_ids)
        except Exception:
            return {}
    if not floor:
        return {}

    shots = defaultdict(int)
    denom = defaultdict(int)
    team_of = {}
    for e in events:
        if e["event_type"] != "shot" or e.get("primary_player_id") is None:
            continue
        shots[e["primary_player_id"]] += 1
        onfloor = floor.get(e["id"])
        if not onfloor:
            continue
        shooter_team = e.get("shooter_team_id")
        if shooter_team is None:
            continue
        five = onfloor.get(shooter_team)
        if not five:
            continue
        for pid in five:                 # only the SHOOTING team's five
            denom[pid] += 1
            team_of.setdefault(pid, shooter_team)

    out = {}
    for pid, dn in denom.items():
        if dn < min_denom:
            continue
        out[pid] = {"load": shots.get(pid, 0) / dn,
                    "shots": shots.get(pid, 0), "denom": dn,
                    "team_id": team_of.get(pid)}
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  3. OFFENSIVE FOOTPRINT — what YOUR OWN diet does when a player is on
# ══════════════════════════════════════════════════════════════════════════════

def offensive_footprint(events, floor=None, game_ids=None,
                        min_side=MIN_FOOTPRINT):
    """{player_id: {"on": diet, "off": diet, "delta": {...}}} — the team's own
    shot diet with this player on the floor versus off it.

    The read behind "the offense changes shape when she checks in": a rim share
    that climbs because she draws help, or a three share that climbs because she
    is the only one who can pass out of a double.

    Carries the same warning as its defensive twin and for the same reason: it
    is NOT teammate-adjusted, the four players beside her move with her, and the
    defensive version of this delta measured SB −0.06. Treat it as a description
    of minutes that were played and use the RAPM columns for causal claims.
    """
    if floor is None:
        try:
            import helpers.lineups as LU
            floor = LU._event_floor(game_ids)
        except Exception:
            return {}
    if not floor:
        return {}

    # Who DRESSED, per game per team — the off-floor side must only contain
    # games the player was available for. Same guard as the defensive twin: a
    # global roster would charge her with every game she never travelled to.
    ev_game = {e["id"]: e.get("game_id") for e in events}
    played = defaultdict(lambda: defaultdict(set))
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
        if shooter_team is None:
            continue
        five = onfloor.get(shooter_team)
        if five is None:
            continue
        band = SK.classify_band(e.get("shot_x"), e.get("shot_y"),
                                e.get("shot_type"))
        is3 = e.get("shot_type") == 3
        made = e["shot_result"] == "make"
        pts = (3 if is3 else 2) if made else 0
        dressed = (played.get(e.get("game_id")) or {}).get(shooter_team) or set()
        for pid in dressed:
            _add(on[pid] if pid in five else off[pid], band, is3, made, pts)

    out = {}
    for pid in set(on) | set(off):
        a, b = on.get(pid) or _blank(), off.get(pid) or _blank()
        if a["n"] < min_side or b["n"] < min_side:
            continue

        def _diet(c):
            return {
                "n": c["n"],
                "rim_share": S._safe(c["rim"], c["n"]),
                "paint_share": S._safe(c["paint"], c["n"]),
                "three_share": S._safe(c["three"], c["n"]),
                "pps": S._safe(c["pts"], c["n"]),
                "fg": S._safe(c["made"], c["n"]),
            }

        da, db = _diet(a), _diet(b)
        out[pid] = {
            "on": da, "off": db, "team_id": team_of.get(pid),
            "delta": {
                "rim_share": (da["rim_share"] or 0) - (db["rim_share"] or 0),
                "paint_share": (da["paint_share"] or 0) - (db["paint_share"] or 0),
                "three_share": (da["three_share"] or 0) - (db["three_share"] or 0),
                "own_pps": (da["pps"] or 0) - (db["pps"] or 0),
            },
        }
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  4. THE TEAM'S OWN DIET — the thing team_allowed_diet is the mirror of
# ══════════════════════════════════════════════════════════════════════════════

def team_own_diet(events, team_ids=None):
    """{team_id: {"band": {band: share}, "n", "own_pps", ...}} — the depth
    profile of the shots each offense TAKES, as shares of its own attempts.

    `defense_profile.team_allowed_diet` calls itself "the direct mirror of the
    offensive shot diet"; this is that diet, computed on the same footing so the
    two can be read side by side without one of them having been assembled a
    different way.

    Same reliability footing, and it is the stronger side of it: team band SHARE
    measured SB .88. Team per-band FG% is deliberately not reported — at six
    teams it is unmeasurable in either direction (see `reliability.MEASURED`).
    """
    raw = defaultdict(lambda: {"band": defaultdict(int), "n": 0, "pts": 0,
                               "made": 0, "three": 0, "guarded": 0,
                               "assisted": 0})
    for e in events:
        if e["event_type"] != "shot":
            continue
        tid = e.get("shooter_team_id")
        if tid is None:
            continue
        if team_ids is not None and tid not in team_ids:
            continue
        c = raw[tid]
        band = SK.classify_band(e.get("shot_x"), e.get("shot_y"),
                                e.get("shot_type"))
        c["band"][band] += 1
        c["n"] += 1
        is3 = e.get("shot_type") == 3
        c["three"] += 1 if is3 else 0
        c["guarded"] += 1 if e.get("guarded_by_id") is not None else 0
        c["assisted"] += 1 if e.get("pass_from_id") is not None else 0
        if e["shot_result"] == "make":
            c["made"] += 1
            c["pts"] += 3 if is3 else 2

    out = {}
    for tid, c in raw.items():
        if not c["n"]:
            continue
        band_sh, _ = _shares(c["band"])
        out[tid] = {
            "band": dict(band_sh), "band_n": dict(c["band"]),
            "n": c["n"], "own_pps": S._safe(c["pts"], c["n"]),
            "fg": S._safe(c["made"], c["n"]),
            "three_share": S._safe(c["three"], c["n"]),
            "contested_share": S._safe(c["guarded"], c["n"]),
            "assisted_share": S._safe(c["assisted"], c["n"]),
        }
    return out
