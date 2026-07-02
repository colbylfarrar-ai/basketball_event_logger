"""
scout.py — coach's scouting-report engine (FastScout-style game prep).

The assembly + printable-HTML layer behind Team Analytics' "Scout" tab: four
factors with league percentiles, rule-based "how to guard / how to attack" keys,
personnel cards, hot zones, and a clean printable HTML the coach can hand out or
save to PDF (no reportlab dependency). Scout an opponent, or self-scout your own
team. Display-only — every number comes from the Streamlit-free engines
(team_ratings / league_analytics / player_ratings / badges / stats). There are NO
streamlit calls here; the page owns caching and rendering (mirror of box_score.py).
"""
from __future__ import annotations

import html

from database.db import query
import helpers.league_analytics as LA
import helpers.badges as BG
import helpers.stats as S
import helpers.court_png as CP
import helpers.playtypes as PT
import helpers.defenses as DEF
import helpers.player_ratings as PR
import helpers.spacing as SPACE

ZONE_LABELS = {"LC": "Left corner", "LW": "Left wing", "C": "Center / top",
               "RW": "Right wing", "RC": "Right corner"}

# Official HoopTracks mark (baked from assets/logo_mark.svg — kept self-contained
# so the print sheet never depends on the asset file being on the server). The
# gold "HoopTracks" text beside it always renders even where SVG is dropped
# (the pure-pip xhtml2pdf engine), so the brand survives every print path.
_BRAND_MARK = (
    "<svg width='15' height='15' viewBox='0 0 64 64' style='vertical-align:-2px'>"
    "<path d='M12 46 L23 35 L31 43 L41 38' fill='none' stroke='#f0a500' "
    "stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/>"
    "<circle cx='12' cy='46' r='2.9' fill='#0d1117' stroke='#f0a500' stroke-width='1.7'/>"
    "<circle cx='23' cy='35' r='2.9' fill='#0d1117' stroke='#f0a500' stroke-width='1.7'/>"
    "<circle cx='31' cy='43' r='2.9' fill='#0d1117' stroke='#f0a500' stroke-width='1.7'/>"
    "<circle cx='46' cy='35' r='12' fill='#f0a500'/>"
    "<path d='M46 23 L46 47 M34 35 L58 35' stroke='#0d1117' stroke-width='1.8' "
    "stroke-linecap='round'/>"
    "<path d='M40 24 C45 30 45 40 40 46' fill='none' stroke='#0d1117' stroke-width='1.5'/>"
    "<path d='M52 24 C47 30 47 40 52 46' fill='none' stroke='#0d1117' stroke-width='1.5'/>"
    "</svg>")

# Coarse scout-section keys that were split into per-table keys (so a coach can
# print just one table). A coach who previously hid the bundle keeps every child
# hidden — expand the legacy parent key into its children when reading the toggle
# set. Used by BOTH the on-screen tab and printable_html so they stay in lockstep.
SCOUT_LEGACY_KEYS = {
    "play_calls": ("pc_offense", "pc_defense", "pc_tendencies", "pc_handoff"),
    "defenses":   ("def_run", "def_attack", "def_cross"),
}


def expand_hidden(hidden):
    """Return ``hidden`` with any legacy bundle key expanded to its child keys, so
    an old 'play_calls'/'defenses' opt-out still hides all of that bundle's now-
    granular tables. Non-destructive (returns a new set)."""
    out = set(hidden or ())
    for parent, kids in SCOUT_LEGACY_KEYS.items():
        if parent in out:
            out.update(kids)
    return out


def _mean(pool):
    pool = [v for v in pool if v is not None]
    return sum(pool) / len(pool) if pool else 0.0


def team_zone(game_ids, team_pids):
    """Team shooting by zone over the given games (team's own shots only)."""
    if not game_ids:
        return {}
    zs = S.player_zone_splits(game_ids=list(game_ids))
    out = {z: {"FGA": 0, "FGM": 0} for z in S.ZONES}
    for pid in team_pids:
        for (z, _st), cell in zs.get(pid, {}).items():
            out[z]["FGA"] += cell["FGA"]
            out[z]["FGM"] += cell["FGM"]
    for z in out:
        out[z]["pct"] = (100 * out[z]["FGM"] / out[z]["FGA"]) if out[z]["FGA"] else 0.0
    return out


def team_zone_by_type(game_ids, team_pids, events=None):
    """Team shooting by zone, split into 2PT and 3PT (team's own shots).
    {zone: {'2': {FGA,FGM,pct}, '3': {FGA,FGM,pct}}} with pct as 0-100."""
    out = {z: {"2": {"FGA": 0, "FGM": 0}, "3": {"FGA": 0, "FGM": 0}}
           for z in S.ZONES}
    if game_ids:
        zs = S.player_zone_splits(game_ids=list(game_ids), events=events)
        for pid in team_pids:
            for (z, stype), cell in zs.get(pid, {}).items():
                if z not in out:
                    continue
                k = "3" if stype == 3 else "2"
                out[z][k]["FGA"] += cell["FGA"]
                out[z][k]["FGM"] += cell["FGM"]
    for z in out:
        for k in ("2", "3"):
            a = out[z][k]
            a["pct"] = (100 * a["FGM"] / a["FGA"]) if a["FGA"] else 0.0
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  SCOUT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_scout(team_id, gender, scored, tracked, pack, table,
                personnel_limit=7, exclude_pids=None, visible_game_ids=None):
    """Assemble every piece of the scouting report for one team.

    personnel_limit=None shows the WHOLE roster (self-scout); exclude_pids drops
    players (e.g. injured/suspended) from the personnel list. `visible_game_ids`
    is the entitlement read-filter for the hot-zone / shot-creation views: None =
    unrestricted (own team / admin), a set restricts them to those games (a
    League-wide scout passes the team's pooled games)."""
    s = scored.get(team_id, {})
    ts = pack.get("ts", {})
    me = ts.get(team_id)
    name = s.get("name", f"#{team_id}")

    def pool(key):
        return [v[key] for v in ts.values() if v.get(key) is not None]

    # ── four factors + key tendencies, with league percentile ──
    factors = []
    if me:
        specs = [
            ("Shooting (eFG%)", "eFG", True, "off"),
            ("Ball security (TOV%)", "TOVpct", False, "off"),
            ("Off. rebounding (OREB%)", "ORBpct", True, "off"),
            ("Getting to line (FTr)", "FTr", True, "off"),
            ("Shooting allowed (opp eFG%)", "oeFG", False, "def"),
            ("Def. rebounding (DREB%)", "DRBpct", True, "def"),
            ("Pace (poss/g)", "poss_pg", True, "tempo"),
            ("3-pt reliance (3PA rate)", "TPAr", True, "off"),
        ]
        for label, key, hib, side in specs:
            val = me.get(key)
            pct = LA.percentile(val, pool(key), hib)
            factors.append({"label": label, "value": val, "pct": pct, "side": side})

    strengths = [f for f in factors if f["pct"] is not None and f["pct"] >= 70]
    weaknesses = [f for f in factors if f["pct"] is not None and f["pct"] <= 30]

    # ── how to GUARD / how to ATTACK (rule-based) ──
    guard, attack = [], []
    if me:
        if me.get("three_share", 0) >= 30:
            guard.append("They live beyond the arc — run shooters off the line, "
                         "no open catch-and-shoot threes.")
        if me.get("paint_share", 0) >= 48:
            guard.append("Paint-heavy offense — wall up the lane and force "
                         "contested jumpers.")
        if me.get("TOVpct", 0) >= 22:
            guard.append("Turnover-prone — pressure the ball and trap, they'll "
                         "give possessions away.")
        if me.get("ORBpct", 0) >= 33:
            guard.append("Crash the offensive glass hard — box out on every shot, "
                         "limit second chances.")
        if me.get("ast_to", 0) >= 1.2:
            guard.append("Good ball movement — jump passing lanes and disrupt the "
                         "first action.")
        if me.get("Pace", 0) >= _mean(pool("Pace")):
            guard.append("They want to run — get back in transition and make them "
                         "play in the half-court.")
        if me.get("oeFG", 0) >= _mean(pool("oeFG")):
            attack.append("They give up efficient shots — push the ball and hunt "
                          "good looks early in the clock.")
        if me.get("DRBpct", 100) <= 62:
            attack.append("Beatable on the defensive glass — send crashers, chase "
                          "offensive rebounds.")
        if me.get("pf_pg", 0) >= _mean(pool("pf_pg")):
            attack.append("Foul-prone — drive the ball, draw contact and get them "
                          "in the bonus.")
        if me.get("stl_pg", 0) <= 6:
            attack.append("They don't force many steals — patient ball movement "
                          "will get a clean look.")
    if not guard:
        guard.append("Balanced attack — take away their top scorer and make "
                     "role players beat you.")
    if not attack:
        attack.append("Sound defense — value the ball, attack early before their "
                      "defense is set.")

    # ── personnel cards ──
    roster = sorted([r for r in table.values() if r["team_id"] == team_id],
                    key=lambda r: -(r.get("PPG") or 0))
    badges = BG.award_badges({pid: r for pid, r in table.items()})
    pid_of = {r["name"]: pid for pid, r in table.items() if r["team_id"] == team_id}
    if exclude_pids:
        roster = [r for r in roster if pid_of.get(r["name"]) not in exclude_pids]
    _lim = len(roster) if personnel_limit is None else personnel_limit
    personnel = []
    for r in roster[:_lim]:
        notes = []
        if (r.get("3PR") or 0) >= 40 and (r.get("3P%") or 0) >= 30:
            notes.append("deny threes — close out high")
        if (r.get("RimFGA%") or 0) >= 45:
            notes.append("force jumper — wall the rim")
        if (r.get("SelfCr%") or 0) >= 55:
            notes.append("self-creator — make someone else beat you")
        if (r.get("APG") or 0) >= 3:
            notes.append("primary creator — pressure & deny")
        if (r.get("FTR") or 0) >= 0.35:
            notes.append("gets to the line — guard straight up")
        if not notes:
            notes.append("role player — help off, clog the lane")
        pid = pid_of.get(r["name"])
        bl = badges.get(pid, [])[:3] if pid else []
        personnel.append({
            "pid": pid,
            "name": r["name"], "num": r.get("number"),
            "ppg": r.get("PPG"), "rpg": r.get("RPG"), "apg": r.get("APG"),
            "usg": r.get("USG%"),
            "fg": r.get("FG%"), "tp": r.get("3P%"), "ts": r.get("TS%"),
            "rim": r.get("RimFGA%"), "three": r.get("3PR"),
            "ovr": r.get("OVERALL"), "note": "; ".join(notes),
            # 0-100 category breakdown behind the OVERALL (player_ratings)
            "off": r.get("OFFENSE"), "def": r.get("DEFENSE"),
            "ply": r.get("PLAYMAKING"), "reb": r.get("REBOUNDING"),
            "badges": [f"{b['emoji']} {b['name']}" for b in bl],
        })

    # ── hot zones (combined + 2/3 split) and per-player shot-creation mix ──
    # Select the team's tracked games by tracked=1 ALONE — NOT S.team_game_ids,
    # which also requires recorded final scores. A game can be tracked (events
    # logged) without its score entered in the games table; those still feed the
    # four-factors/personnel (event-based) so the zone + creation views must use
    # the same game set or they come back empty.
    gids = [r["id"] for r in query(
        "SELECT id FROM games WHERE (team1_id=? OR team2_id=?) AND tracked=1 "
        "AND season='Current'", (team_id, team_id))]
    if visible_game_ids is not None:
        _vis = set(visible_game_ids)
        gids = [g for g in gids if g in _vis]
    _proster = query("SELECT id, height, wingspan, weight, handedness, position "
                     "FROM players WHERE team_id=?", (team_id,))
    team_pids = tuple(r["id"] for r in _proster)
    bio = {r["id"]: r for r in _proster}
    for p in personnel:
        _b = bio.get(p["pid"])
        p["bio"] = S.fmt_measurables(_b)
        p["pos"] = (_b["position"].strip() or None) if (_b and _b["position"]) else None
    zones = team_zone(tuple(gids), team_pids)
    ev = S.fetch_events(list(gids)) if gids else []
    zones_by_type = team_zone_by_type(tuple(gids), team_pids, events=ev)

    # how each player gets their shots by the one-tap play_type tag (pnr / iso /
    # post / …): the literal set call WITH its efficiency, as a share of that
    # player's TAGGED shots. Reuses the engine so PPP/FG% ride along the share.
    # Sparse until a coach tags — None when this player has no tagged shots.
    _PT_LABEL = dict(PT.NAMED_PLAY_TYPES)
    pnp = PT.player_named_playtypes(events=ev)
    for p in personnel:
        sets = pnp.get(p["pid"])
        tot = sum(s["poss"] for s in sets.values()) if sets else 0
        if tot:
            ordered = sorted(sets.items(), key=lambda kv: -kv[1]["poss"])
            p["playmix"] = [(_PT_LABEL.get(k, k), 100 * s["poss"] / tot,
                             s["PPP"], s["FG%"]) for k, s in ordered]
            p["playmix_n"] = tot
            # one-line go-to directive: a dominant, efficient, real-volume set.
            top_k, top_s = ordered[0]
            p["goto"] = (_PT_LABEL.get(top_k, top_k)
                         if (top_s["poss"] / tot) >= 0.25 and top_s["PPP"] >= 1.0
                         and top_s["poss"] >= 8 else None)
        else:
            p["playmix"] = None
            p["playmix_n"] = 0
            p["goto"] = None

    # dominant- vs weak-hand-side shooting per player (helpers/handedness.py:
    # righty's right-side shots = dominant; center = straightaway, kept apart).
    hsplits = S.player_hand_splits(events=ev) if ev else {}
    for p in personnel:
        hb = hsplits.get(p["pid"])
        if hb and (hb["dominant"]["all"]["FGA"] or hb["weak"]["all"]["FGA"]):
            dom, wk = hb["dominant"]["all"], hb["weak"]["all"]
            # scouting directive: which way to make him go. Needs volume on the
            # worse side + a real FG% gap so it's not a 1-2 shot fluke.
            cue = None
            if wk["FGA"] >= 6 and dom["pct"] - wk["pct"] >= 0.10:
                cue = "force weak hand"
            elif dom["FGA"] >= 6 and wk["pct"] - dom["pct"] >= 0.10:
                cue = "force strong hand"
            p["hand"] = {"dom_fga": dom["FGA"], "dom_pct": dom["pct"],
                         "weak_fga": wk["FGA"], "weak_pct": wk["pct"], "cue": cue}
        else:
            p["hand"] = None

    # ── space dependence: open vs contested FG% (defensive game-plan cue) ─────
    # guarded_by_id is the richest tracked signal; the open−contested gap says
    # who to close out hard (needs space) vs who to deny the catch (contest-proof).
    zguard = S.player_zone_guarded(events=ev) if ev else {}
    for p in personnel:
        p["space"] = None
        gd = zguard.get(p["pid"])
        if gd:
            g, o = gd["guarded"], gd["open"]
            if g["FGA"] >= 8 and o["FGA"] >= 8:
                cliff = round((o["pct"] - g["pct"]) * 100)
                p["space"] = {
                    "cliff": cliff, "n": g["FGA"] + o["FGA"],
                    "cue": ("needs space" if cliff > 8 else
                            "contest-proof" if cliff < -2 else None)}

    # ── GS% (games started ÷ games played) — who normally starts ──────────────
    # Starters are inferred (five on the floor at each game's first event); see
    # stats.games_started. Scoped to this team's visible tracked games (gids).
    gp = S.games_played(list(gids)) if gids else {}
    gs = S.games_started(list(gids), events=ev) if gids else {}
    for p in personnel:
        played = gp.get(p["pid"], 0)
        p["gs_pct"] = (100 * gs.get(p["pid"], 0) / played) if played else None

    # ── located (x,y) shots: one team pull, bucketed per player for mini charts ─
    team_shots = (S.located_shots(game_ids=list(gids), events=ev, team_id=team_id)
                  if gids else [])
    shots_by_pid = {}
    for sh in team_shots:
        shots_by_pid.setdefault(sh["player_id"], []).append(sh)
    for p in personnel:
        p["shots"] = shots_by_pid.get(p["pid"], [])
    # ── per-player floor-spacing index (located x,y blend vs the league player
    #    pool) — one map for the whole league, looked up per roster player. Empty
    #    until located-shot coverage is real, so the sheet self-hides it. ────────
    _pspace = SPACE.league_player_spacing(gender)
    for p in personnel:
        p["spacing"] = _pspace.get(p["pid"])
    # same located shots bucketed by the one-tap PLAY-TYPE and DEFENSE tags, for
    # filtered shot charts on the sheet (sparse until a coach tags — sections that
    # read these self-hide when empty).
    shots_by_play, shots_by_def = {}, {}
    for sh in team_shots:
        _pk = sh.get("play_type")
        if _pk:
            shots_by_play.setdefault(_pk, []).append(sh)
        _dk = DEF._norm(sh.get("defense"))
        if _dk:
            shots_by_def.setdefault(_dk, []).append(sh)
    # the DEFENSIVE flip side: shots opponents took AGAINST this team (shooter is
    # the other team in this team's games). play_type = the action the OPPONENT ran
    # (what this team's D gives up); defense = the scheme THIS team was running
    # (what each of their defenses gives up). Same events / visible game set.
    opp_shots = ([s for s in S.located_shots(game_ids=list(gids), events=ev)
                  if s["team_id"] != team_id] if gids else [])
    shots_allowed_by_play, shots_allowed_by_def = {}, {}
    for sh in opp_shots:
        _pk = sh.get("play_type")
        if _pk:
            shots_allowed_by_play.setdefault(_pk, []).append(sh)
        _dk = DEF._norm(sh.get("defense"))
        if _dk:
            shots_allowed_by_def.setdefault(_dk, []).append(sh)

    # ── how they get their shots: explicit one-tap play-call tags ─────────────
    # The literal set call a coach taps on a shot in the tracker (pnr / iso /
    # post / spot / …). Reuses the events already pulled and the same visible
    # game set, so it honours the entitlement filter like every view above.
    play_calls = PT.team_named_playtypes(team_id, events=ev, offense=True)
    # companion "what they allow" view: the set calls opponents ran ON them
    # (offense=False flips the flag), same events / visible game set.
    play_calls_def = PT.team_named_playtypes(team_id, events=ev, offense=False)
    # cross-dimension: per-set SHOT PROFILE (what each set call PRODUCES — where
    # it shoots from, 3PA/rim/assisted/open share, top zone). The scouting value
    # behind the headline PPP: "they hunt a 3 in transition / get to the rim on
    # X". Reuses the same events / visible game set as everything above.
    set_profiles = PT.team_playtype_shot_profiles(team_id, events=ev,
                                                  offense=True)
    # initiator chains for hand-off / inbounds sets — who is the DHO hub, who
    # inbounds the BLOB/SLOB and the PPP that hub generates. Empty until those
    # sets carry a pass_from_id (hander / inbounder) tag.
    feeders = PT.team_playtype_feeders(team_id, events=ev, offense=True)
    # full DHO / BLOB / SLOB breakdown — the PnR-style treatment for hand-off /
    # inbounds sets: the set's overall efficiency, an INITIATOR-vs-FINISHER split
    # (roller = set it / handed off & shot; handler = received & finished, from
    # team_role_splits) and the hub chain (top hander/inbounder -> top target).
    # Reuses the same events / visible game set. Empty until the sets are tagged.
    role_hubs = PT.team_role_splits(team_id, events=ev,
                                    keys=("dho", "blob", "slob"), offense=True)
    _pc_by_key = {r["key"]: r for r in (play_calls.get("rows") or [])}
    _PT_LBL = dict(PT.NAMED_PLAY_TYPES)
    handoff = []
    for _hk in ("dho", "blob", "slob"):
        _setrow = _pc_by_key.get(_hk)
        _rh = role_hubs.get(_hk) or {}
        _init = _rh.get("roller")
        _fin = _rh.get("handler")
        _fb = (feeders.get(_hk) or {}).get("feeders") or []
        _init = _init if (_init and _init["poss"]) else None
        _fin = _fin if (_fin and _fin["poss"]) else None
        if not _setrow and not _init and not _fin and not _fb:
            continue
        _top = _fb[0] if _fb else None
        handoff.append({
            "key": _hk, "label": _PT_LBL.get(_hk, _hk.upper()),
            "set": _setrow, "initiator": _init, "finisher": _fin,
            "hub": ({"feeder_id": _top["feeder_id"], "feeds": _top["feeds"],
                     "ppp": _top["PPP"], "target_id": _top.get("top_target_id")}
                    if _top else None),
        })

    # ── DEFENSE: the schemes THEY run + how THEY attack a defense ─────────────
    # offense=False -> the defenses this opponent RUNS (PPP allowed): the scout
    # headline "what D do they play". offense=True -> how they ATTACK each scheme
    # thrown at them (PPP scored): drives YOUR defensive game plan. Plus the
    # play_type × defense cross-tab the user asked for ("their PnR vs a zone").
    defenses_run = DEF.team_defenses(team_id, events=ev, offense=False)
    defenses_faced = DEF.team_defenses(team_id, events=ev, offense=True)
    defense_families = DEF.team_defense_families(team_id, events=ev, offense=False)
    defense_cross = DEF.cross_play_defense(team_id, events=ev, offense=True)
    # prose scout keys (gender-neutral, volume-gated, silent when sparse):
    if defenses_run.get("total_tagged", 0) >= 12:
        _drun = sorted(defenses_run.get("rows", []), key=lambda r: -r["poss"])
        _dtop = _drun[0] if _drun else None
        if _dtop and _dtop["share"] >= 0.4:
            # "what they run" is YOUR offense's problem -> attack[]
            attack.append(
                f"They sit in {_dtop['label'].lower()} "
                f"({_dtop['share'] * 100:.0f}% of tagged trips) — have your "
                f"{_dtop['family']} offense ready.")
    # a scheme THEY can't score against (high volume, low PPP) -> YOUR defense
    _dfaced = [r for r in defenses_faced.get("rows", []) if r["poss"] >= 10]
    if _dfaced:
        _weak = min(_dfaced, key=lambda r: r["PPP"])
        if _weak["PPP"] <= 0.85:
            guard.append(
                f"They stall against {_weak['label'].lower()} "
                f"({_weak['PPP']:.2f} PPP on {_weak['poss']} poss) — show it.")

    # ── AUTO KEYS: high-volume + extreme set profile -> one prose scout key ────
    # Only fires when a set has real volume AND its profile is lopsided, so it
    # stays silent when sparse. Gender-neutral, no pronouns; rendered for free in
    # the existing guard[] / attack[] lists.
    if set_profiles:
        _set_total = sum(pr["poss"] for pr in set_profiles.values()) or 1
        for _k, _pr in sorted(set_profiles.items(),
                              key=lambda kv: -kv[1]["poss"]):
            _poss, _share = _pr["poss"], _pr["poss"] / _set_total
            _lbl = _pr.get("label") or _k
            # transition (or any set) that hunts the three at real volume — but
            # NOT a set that is a 3 by nature (spot-up), where it states the tag.
            if (_k == "transition" and _poss >= 10
                    and (_pr.get("3PA_rate") or 0) >= 0.45):
                guard.append("They hunt transition 3s — get back and find "
                             "shooters before they spot up.")
            elif (_poss >= 12 and _share >= 0.10
                    and (_pr.get("3PA_rate") or 0) >= 0.55
                    and not PT.is_inherent(_k, "three")):
                guard.append(f"Their {_lbl.lower()} is a three-point hunt — "
                             "chase shooters off the line.")
            # a set that gets to the rim at real volume — but NOT a set that is a
            # rim attack by nature (iso / post / cut / putback / duck-in).
            if (_poss >= 12 and (_pr.get("rim_rate") or 0) >= 0.6
                    and not PT.is_inherent(_k, "rim")):
                guard.append(f"Their {_lbl.lower()} attacks the rim — wall up "
                             "the lane and force a kick-out.")
            # a set that gets clean, open looks
            if _poss >= 12 and (_pr.get("open_rate") or 0) >= 0.6:
                guard.append(f"Their {_lbl.lower()} gets clean looks "
                             f"({(_pr['open_rate'] * 100):.0f}% open) — close "
                             "out hard and switch screens cleanly.")

    # ── situational tendencies: play_type/defense usage by quarter / score / run.
    # Reuses the events fetched + entitlement-scoped above, from team_id's own
    # game-state perspective. Dormant until shots carry play_type/defense tags.
    situational = None
    if ev:
        try:
            import helpers.situational as SIT
            situational = SIT.team_situational(team_id, ev, gender=gender)
        except Exception:
            situational = None

    return {
        "name": name, "class": s.get("class", "N/A"),
        "record": f"{s.get('W',0)}-{s.get('L',0)}",
        "rank": s.get("Rank"), "of": len(scored), "power": s.get("Power"),
        "trk": tracked.get(team_id),
        "factors": factors, "strengths": strengths, "weaknesses": weaknesses,
        "guard": guard, "attack": attack, "personnel": personnel,
        "zones": zones, "zones_by_type": zones_by_type,
        "team_shots": team_shots, "shots_by_play": shots_by_play,
        "shots_by_def": shots_by_def,
        "shots_allowed_by_play": shots_allowed_by_play,
        "shots_allowed_by_def": shots_allowed_by_def, "play_calls": play_calls,
        "play_calls_def": play_calls_def, "situational": situational,
        "defenses_run": defenses_run, "defenses_faced": defenses_faced,
        "defense_families": defense_families, "defense_cross": defense_cross,
        "set_profiles": set_profiles, "feeders": feeders, "handoff": handoff,
        # team-wide pid->name (covers feeder hubs / targets outside the top-N
        # personnel list) for the hand-off / inbounds hub note.
        "name_of": {pid: nm for nm, pid in pid_of.items()},
        "has_tracked": me is not None,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MATCHUPS  (who-guards-whom, shared with the War Room matchup planner)
# ══════════════════════════════════════════════════════════════════════════════

def build_matchups(my_team_id, opp_team_id, table, plan):
    """Resolve a saved defender↔scorer plan into print/display rows.

    `plan` = the per-coach matchup dict from scoutboard.get_plan(opp_team_id):
    ``{scorer_key: my_defender_pid}`` where ``scorer_key`` is ``str(player_id)``
    for a tracked opponent scorer or ``"name:"+name`` for a hand-entered (cold)
    one. `table` = player_ratings.player_stat_table (rows carry team_id, name,
    number, OFFENSE, DEFENSE). Mirrors the War Room planner's edge model exactly:
    edge = your defender's DEFENSE − their scorer's OFFENSE (0-100, 50 = lg avg);
    tag Edge ≥ +8 · Tough ≤ −8 · else Even. Streamlit-free.

    Returns ``[{scorer, scorer_off, defender, defender_def, edge, tag}]`` sorted by
    scorer OFFENSE (unrated/intel scorers last), skipping orphaned assignments."""
    mine = {pid: r for pid, r in table.items() if r["team_id"] == my_team_id}
    theirs = {pid: r for pid, r in table.items() if r["team_id"] == opp_team_id}

    def _lbl(r):
        return f"#{r.get('number') or ''} {r['name']}".strip()

    rows = []
    for skey, dpid in (plan or {}).items():
        if isinstance(skey, str) and skey.startswith("name:"):
            scorer, soff = skey[5:].strip(), None
        else:
            try:
                sr = theirs.get(int(skey))
            except (TypeError, ValueError):
                continue
            if not sr:
                continue
            scorer, soff = _lbl(sr), sr.get("OFFENSE")
        dr = mine.get(dpid)
        if not dr:
            continue
        ddef = dr.get("DEFENSE")
        edge = (ddef - soff) if (ddef is not None and soff is not None) else None
        tag = (("Edge" if edge >= 8 else "Tough" if edge <= -8 else "Even")
               if edge is not None else None)
        rows.append({"scorer": scorer, "scorer_off": soff, "defender": _lbl(dr),
                     "defender_def": ddef, "edge": edge, "tag": tag})
    rows.sort(key=lambda m: (m["scorer_off"] is None, -(m["scorer_off"] or 0)))
    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  PRINTABLE HTML
# ══════════════════════════════════════════════════════════════════════════════

def _md_bold(s):
    """Convert a `**bold**` markdown tip to escaped HTML with <b> spans."""
    parts = s.split("**")
    out = ""
    for i, seg in enumerate(parts):
        seg = html.escape(seg)
        out += f"<b>{seg}</b>" if i % 2 == 1 else seg
    return out


def _pf(frac, dp=0):
    """Format a 0–1 fraction as a percent string, or em-dash for None."""
    return f"{frac * 100:.{dp}f}%" if frac is not None else "—"


def usage_map_html(situations, kind, title, row_hdr="Set"):
    """Share-by-situation usage map as a self-styled, print-safe colored HTML
    table — the scout-sheet twin of the Situational tab's plotly heatmaps.

    ``kind`` = 'plays' (offense set-usage) or 'defenses' (defense-scheme usage);
    each cell is that set/scheme's % share of the situation's tagged possessions,
    gold-shaded by intensity. Every cell carries its own background + text colour
    so it reads on both the dark app screen and the white printed page. Returns
    '' when there's no tagged data (so the sheet self-hides it)."""
    e = html.escape
    if not situations:
        return ""
    base, sits = situations[0], situations[1:]
    rows = [r for r in base.get(kind, []) if r.get("poss", 0) > 0][:8]
    if not rows or not sits:
        return ""
    # OPAQUE pale-gold -> deep-orange heat so a cell reads on the dark app screen
    # AND the white printed page (alpha-on-transparent washed out on both).
    _lo, _hi = (255, 244, 191), (208, 58, 24)

    def _cell(share):
        n = min(1.0, max(0.0, share / 0.45))       # full heat by ~45% share
        rgb = tuple(round(_lo[i] + (_hi[i] - _lo[i]) * n) for i in range(3))
        txt = "#fff" if n > 0.55 else "#1a1a1a"     # white on the hot end
        return f"rgb{rgb}", txt

    _c = "padding:3px 5px;text-align:center;font-size:9px"
    _ax = "background:#243140;color:#fff;font-weight:700;padding:3px 5px;font-size:9px"
    th = "".join(f"<td style='{_ax};text-align:center'>{e(s['label'])}</td>"
                 for s in sits)
    body = ""
    for r in rows:
        cells = ""
        for s in sits:
            share = next((x["share"] for x in s.get(kind, [])
                          if x["key"] == r["key"]), 0.0)
            pct = round(share * 100)
            bg, txt = _cell(share)
            inner = f"{pct}%" if pct else "·"
            cells += (f"<td style='background:{bg};color:{txt if pct else '#c8b86a'};"
                      f"{_c}'>{inner}</td>")
        body += f"<tr><td style='{_ax}'>{e(r['label'])}</td>{cells}</tr>"
    return (f"<h2>{e(title)}</h2>"
            "<table style='border-collapse:collapse;width:100%;margin-bottom:7px'>"
            f"<tr><td style='{_ax}'>{e(row_hdr)}</td>{th}</tr>{body}</table>")


def printable_html(sc, opponent_label, hidden=None, extra=None, compact=True):
    """A print-ready scouting sheet (browser → Print → PDF, or the in-app
    preview). Zero hard dependencies — table-based so the xhtml2pdf fallback
    renders it; inline-SVG shot charts / blank courts print from the browser and
    WeasyPrint (xhtml2pdf simply omits the vector art, keeping every table).

    `extra` carries the page-derived blocks the build_scout engine doesn't own
    (breakeven, efficiency, auto-report, 3-pt profile, possession length, notes,
    diagram layout); each section is independently guarded so the sheet still
    renders if a block is missing. Honours the same per-coach `hidden` toggles as
    the on-screen tab."""
    import datetime
    e = html.escape
    extra = extra or {}
    try:
        _d = datetime.date.today()
        today = f"{_d.strftime('%b')} {_d.day}, {_d.year}"
    except Exception:
        today = ""

    hidden = expand_hidden(hidden or set())

    def _show(k):
        return k not in hidden

    # Compact mode flows the middle text/table sections into two columns (wide
    # visual blocks — keys, four-factor+zone row, shot chart, personnel cards,
    # diagrams — stay full width outside the flow).
    _flow_open = "<div class='flow2'>" if compact else ""
    _flow_close = "</div>" if compact else ""

    trk = sc["trk"]
    rng = (f"ORtg {trk['ORtg']:.0f} · DRtg {trk['DRtg']:.0f} · "
           f"Net {trk['NetRtg']:+.0f} · Pace {trk['Pace']:.0f}") if trk else ""

    # ── keys: how to guard / attack ──
    keys_html = ""
    if _show("keys"):
        guard = "".join(f"<li>{e(x)}</li>" for x in sc["guard"]) or "<li>—</li>"
        attack = "".join(f"<li>{e(x)}</li>" for x in sc["attack"]) or "<li>—</li>"
        keys_html = (f"<table class='cols'><tr>"
                     f"<td class='col'><h2>Guard them</h2><ul>{guard}</ul></td>"
                     f"<td class='col'><h2>Attack them</h2><ul>{attack}</ul></td>"
                     f"</tr></table>")

    # ── defensive matchups (who guards whom; shared with War Room planner) ──
    mu_html = ""
    mus = extra.get("matchups") or []
    if _show("matchups") and mus:
        _TAG = {"Edge": "✅ Edge", "Tough": "⚠ Tough", "Even": "Even"}
        rows_mu = ""
        for m in mus:
            off = f"{m['scorer_off']:.0f}" if m.get("scorer_off") is not None else "—"
            dfn = f"{m['defender_def']:.0f}" if m.get("defender_def") is not None else "—"
            edge = (f"{_TAG.get(m['tag'], m['tag'])} ({m['edge']:+.0f})"
                    if m.get("edge") is not None else "—")
            rows_mu += (f"<tr><td>{e(m['scorer'])}</td><td class='n'>{off}</td>"
                        f"<td>{e(m['defender'])}</td><td class='n'>{dfn}</td>"
                        f"<td>{e(edge)}</td></tr>")
        mu_html = (
            "<h2>Defensive matchups — who guards whom</h2><table><tr>"
            "<th>Their scorer</th><th class='n'>OFF</th><th>Your defender</th>"
            f"<th class='n'>DEF</th><th>Edge</th></tr>{rows_mu}</table>"
            "<p class='note'>Edge = your defender's DEFENSE − their scorer's OFFENSE "
            "(0–100, 50 = league avg). ✅ Edge ≥ +8 · ⚠ Tough ≤ −8.</p>")

    # ── four factors + shooting by zone (share one row) ──
    ff_cell = ""
    if _show("four_factors"):
        rows_f = ""
        for f in sc["factors"]:
            if f["value"] is None:
                continue
            p = f["pct"]
            rows_f += (f"<tr><td>{e(f['label'])}</td>"
                       f"<td class='n'>{f['value']:.1f}</td>"
                       f"<td class='n'>{('%.0f' % p) if p is not None else '—'}</td></tr>")
        ff_cell = ("<td class='two-col'><h2>Four factors</h2><table><tr>"
                   "<th>Factor</th><th class='n'>Val</th>"
                   f"<th class='n'>%ile</th></tr>{rows_f}</table></td>")
    z_cell = ""
    if _show("zones"):
        zrows = ""
        zbt = sc.get("zones_by_type", {})
        for z in S.ZONES:
            zz = zbt.get(z, {})
            for i, (tag, cell) in enumerate((("2", zz.get("2", {})),
                                             ("3", zz.get("3", {})))):
                fga, fgm = cell.get("FGA", 0), cell.get("FGM", 0)
                pct = cell.get("pct", 0)
                fg = f"{fgm}/{fga} · {pct:.0f}%" if fga else "—"
                lab = (f"<td rowspan='2'><b>{e(ZONE_LABELS[z])}</b></td>"
                       if i == 0 else "")
                zrows += f"<tr>{lab}<td>{tag}P</td><td class='n'>{fg}</td></tr>"
        z_cell = ("<td class='two-col'><h2>Shooting by zone</h2><table><tr>"
                  "<th>Zone</th><th>Type</th>"
                  f"<th class='n'>FG · %</th></tr>{zrows}</table></td>")
    two_html = (f"<table class='two'><tr>{ff_cell}{z_cell}</tr></table>"
                if (ff_cell or z_cell) else "")

    # ── should they shoot 2s or 3s? (breakeven) ──
    breakeven_html = ""
    bk = extra.get("breakeven")
    if _show("breakeven") and bk:
        edge = bk.get("edge", 0)
        if abs(edge) < 0.03:
            verdict = ("Their 2s and 3s pay off about equally — shot selection is "
                       "balanced.")
        elif edge > 0:
            verdict = (f"Shoot more 3s — a three returns {bk['ev3']:.2f} pts vs "
                       f"{bk['ev2']:.2f} for a two (+{edge:.2f} edge); they clear the "
                       f"{_pf(bk['be3'])} breakeven at {_pf(bk['3P%'])}.")
        else:
            verdict = (f"Shoot more 2s — a two returns {bk['ev2']:.2f} pts vs "
                       f"{bk['ev3']:.2f} for a three ({edge:.2f}); their {_pf(bk['3P%'])} "
                       f"from deep is below the {_pf(bk['be3'])} breakeven.")
        breakeven_html = (
            "<h2>Should they shoot 2s or 3s?</h2><table><tr>"
            "<th class='n'>2P%</th><th class='n'>3P%</th>"
            "<th class='n'>Breakeven 3P%</th><th class='n'>3PA rate</th>"
            "<th class='n'>Pts/2</th><th class='n'>Pts/3</th></tr>"
            f"<tr><td class='n'>{_pf(bk['2P%'])}</td><td class='n'>{_pf(bk['3P%'])}</td>"
            f"<td class='n'>{_pf(bk['be3'])}</td><td class='n'>{_pf(bk['3PAr'])}</td>"
            f"<td class='n'>{bk['ev2']:.2f}</td><td class='n'>{bk['ev3']:.2f}</td></tr>"
            f"</table><p class='note'>{e(verdict)}</p>")

    # ── efficiency summary ──
    eff_html = ""
    ef = extra.get("efficiency")
    if _show("efficiency") and ef:
        pace = ef.get("POSS_pg", 0)
        tempo = ("an up-tempo team." if pace >= 70 else
                 "a controlled pace." if pace >= 60 else "a slow, grind-it-out pace.")
        eff_html = (
            "<h2>Efficiency summary</h2><ul>"
            f"<li><b>Offense:</b> {ef['ORtg']:.1f} pts / 100 poss on "
            f"{_pf(ef['off_eFG'])} eFG; turns it over on {_pf(ef['off_TOV'])} of trips "
            f"and rebounds {_pf(ef['off_ORB'])} of its own misses.</li>"
            f"<li><b>Defense:</b> {ef['DRtg']:.1f} pts / 100 poss allowed on "
            f"{_pf(ef['def_eFG'])} eFG; forces a turnover on {_pf(ef['def_TOV'])} of "
            "opponent trips.</li>"
            f"<li><b>Tempo:</b> {pace:.1f} possessions/game — {tempo}</li></ul>")

    # ── auto scouting report ──
    report_html = ""
    tips = extra.get("auto_report")
    if _show("auto_report") and tips:
        li = "".join(f"<li>{_md_bold(t)}</li>" for t in tips)
        report_html = f"<h2>Scouting report</h2><ul>{li}</ul>"

    # ── coach's custom team note (the Custom notes editor; prints verbatim) ──
    coach_html = ""
    _coach = str(extra.get("coach_note") or "").strip()
    if _show("custom_notes") and _coach:
        coach_html = (f"<h2>Coach's notes</h2><p class='note' "
                      f"style='white-space:pre-wrap'>{e(_coach)}</p>")

    # ── how they get their shots: tagged play calls (one-tap from the tracker) ─
    # Each table is independently toggleable (pc_offense / pc_defense /
    # pc_tendencies / pc_handoff) so a coach can print just the one or two they
    # want — the charts are large, so granular selection keeps the sheet to a page.
    pc_html = ""
    pc = sc.get("play_calls")
    if _show("pc_offense") and pc and pc.get("rows"):
        rows_pc = "".join(
            f"<tr><td>{e(r['label'])}</td>"
            f"<td class='n'>{r['share'] * 100:.0f}%</td>"
            f"<td class='n'>{r['PPP']:.2f}</td>"
            f"<td class='n'>{(r.get('TO%') or 0) * 100:.0f}%</td>"
            f"<td class='n'>{r.get('FD', 0)}</td>"
            f"<td class='n'>{r['FG%'] * 100:.0f}%</td>"
            f"<td class='n'>{r['poss']}</td></tr>"
            for r in sorted(pc["rows"], key=lambda r: r["share"], reverse=True))
        pc_html += (
            "<h2>How they get their shots — play calls</h2><table><tr>"
            "<th>Play call</th><th class='n'>Share</th><th class='n'>PPP</th>"
            "<th class='n'>TO%</th><th class='n'>FD</th>"
            f"<th class='n'>FG%</th><th class='n'>Poss</th></tr>{rows_pc}</table>"
            f"<p class='note'>Coach-tagged set calls, {pc['total_tagged']} tagged "
            f"({pc['untagged']} untagged shots). Share = % of tagged possessions "
            "(shots + turnovers); TO% = the set's give-it-away rate; FD = fouls "
            "drawn running it; PPP = points per possession.</p>")
    # companion: what they ALLOW — the set calls opponents ran on them.
    pcd = sc.get("play_calls_def")
    if _show("pc_defense") and pcd and pcd.get("rows"):
        rows_pcd = "".join(
            f"<tr><td>{e(r['label'])}</td>"
            f"<td class='n'>{r['share'] * 100:.0f}%</td>"
            f"<td class='n'>{r['PPP']:.2f}</td>"
            f"<td class='n'>{(r.get('TO%') or 0) * 100:.0f}%</td>"
            f"<td class='n'>{r.get('FD', 0)}</td>"
            f"<td class='n'>{r['FG%'] * 100:.0f}%</td>"
            f"<td class='n'>{r['poss']}</td></tr>"
            for r in sorted(pcd["rows"], key=lambda r: r["share"], reverse=True))
        pc_html += (
            "<h2>What they allow — play calls defended</h2><table><tr>"
            "<th>Play call</th><th class='n'>Share</th><th class='n'>PPP</th>"
            "<th class='n'>TO%</th><th class='n'>FD</th>"
            f"<th class='n'>FG%</th><th class='n'>Poss</th></tr>{rows_pcd}</table>"
            f"<p class='note'>Set calls opponents ran on them, "
            f"{pcd['total_tagged']} tagged ({pcd['untagged']} untagged shots). "
            "Higher PPP allowed = a set to lean on; high TO% here = they force "
            "giveaways from it; FD = fouls they committed defending it.</p>")
    # cross-dimension: what each set PRODUCES — where it shoots from and the
    # 3PA / rim / assisted / open share. The "they shoot HERE on X / hunt a
    # 3 in transition" read, joined beside the play-calls table above.
    sp = sc.get("set_profiles")
    if _show("pc_tendencies") and sp:
        rows_sp = "".join(
            f"<tr><td>{e(pr.get('label') or k)}</td>"
            f"<td class='n'>{(pr.get('3PA_rate') or 0) * 100:.0f}%</td>"
            f"<td class='n'>{(pr.get('rim_rate') or 0) * 100:.0f}%</td>"
            f"<td class='n'>{(pr.get('ast_rate') or 0) * 100:.0f}%</td>"
            f"<td class='n'>{(pr.get('open_rate') or 0) * 100:.0f}%</td>"
            f"<td>{e(ZONE_LABELS.get(pr.get('top_zone'), '—'))}</td></tr>"
            for k, pr in sorted(sp.items(), key=lambda kv: -kv[1]["poss"]))
        pc_html += (
            "<h2>Set tendencies — what each set produces</h2><table><tr>"
            "<th>Set</th><th class='n'>3PA%</th><th class='n'>Rim%</th>"
            "<th class='n'>Assisted%</th><th class='n'>Open%</th>"
            f"<th>Where</th></tr>{rows_sp}</table>"
            "<p class='note'>3PA% / Rim% = shot-type share of the set; "
            "Assisted% = off a pass; Open% = uncontested; Where = the zone the "
            "set most lives in. High transition 3PA% = a get-back read.</p>")
    # full DHO / BLOB / SLOB breakdown — the PnR-style treatment: the set's
    # overall efficiency, an initiator-vs-finisher split, and the hub chain.
    ho = sc.get("handoff")
    if _show("pc_handoff") and ho:
        _name_of = sc.get("name_of") or {}
        blocks = []
        if True:
            for h in ho:
                lines = []
                stx = h.get("set")
                if stx:
                    lines.append(
                        f"<b>Set:</b> {stx['PPP']:.2f} PPP · "
                        f"{stx['FG%'] * 100:.0f}% FG · {stx['share'] * 100:.0f}% of "
                        f"tags ({stx['poss']} poss)")
                ini = h.get("initiator")
                if ini:
                    lines.append(
                        f"<b>Initiator (set it):</b> {ini['PPP']:.2f} PPP · "
                        f"{ini['FG%'] * 100:.0f}% FG · {ini['poss']} poss")
                fin = h.get("finisher")
                if fin:
                    lines.append(
                        f"<b>Finisher (got it):</b> {fin['PPP']:.2f} PPP · "
                        f"{fin['FG%'] * 100:.0f}% FG · "
                        f"{fin['3PA_rate'] * 100:.0f}% 3PA · {fin['poss']} poss")
                hub = h.get("hub")
                if hub:
                    nm = e(_name_of.get(hub["feeder_id"], f"#{hub['feeder_id']}"))
                    tgt = hub.get("target_id")
                    tgt_txt = (f" → {e(_name_of.get(tgt, '#' + str(tgt)))}"
                               if tgt is not None else "")
                    lines.append(
                        f"<b>Hub:</b> {nm} ({hub['feeds']} feeds){tgt_txt}")
                if lines:
                    body = "".join(
                        f"<div style='margin-left:10px;font-size:12px'>{ln}</div>"
                        for ln in lines)
                    blocks.append(
                        "<div style='margin:4px 0 8px'>"
                        f"<div style='font-weight:700'>{e(h['label'])}</div>"
                        f"{body}</div>")
            if blocks:
                pc_html += (
                    "<h2>Hand-off &amp; inbounds breakdown</h2>"
                    + "".join(blocks)
                    + "<p class='note'>The PnR-style read for DHO / BLOB / SLOB: "
                    "each set's overall efficiency, then the initiator (set it / "
                    "handed off &amp; shot) vs finisher (received &amp; shot) split, "
                    "and the hub who initiates it.</p>")

    # ── DEFENSE: schemes they run + how they attack a D + play×D cross-tab ──
    # Each table independently toggleable (def_run / def_attack / def_cross).
    def_html = ""
    drun = sc.get("defenses_run")
    if _show("def_run") and drun and drun.get("rows"):
        rows_dr = "".join(
            f"<tr><td>{e(r['label'])}</td>"
            f"<td class='n'>{r['share'] * 100:.0f}%</td>"
            f"<td class='n'>{r['PPP']:.2f}</td>"
            f"<td class='n'>{r['FG%'] * 100:.0f}%</td>"
            f"<td class='n'>{r['poss']}</td></tr>"
            for r in drun["rows"])
        def_html += (
            "<h2>Defenses they run</h2><table><tr>"
            "<th>Defense</th><th class='n'>Share</th><th class='n'>PPP allowed</th>"
            f"<th class='n'>FG%</th><th class='n'>Poss</th></tr>{rows_dr}</table>"
            f"<p class='note'>The schemes this team plays on defense, over "
            f"{drun['total_tagged']} tagged trips. Lower PPP allowed = the look "
            "they trust; biggest share = what to prep your offense against.</p>")
    dfaced = sc.get("defenses_faced")
    if _show("def_attack") and dfaced and dfaced.get("rows"):
        rows_df = "".join(
            f"<tr><td>{e(r['label'])}</td>"
            f"<td class='n'>{r['share'] * 100:.0f}%</td>"
            f"<td class='n'>{r['PPP']:.2f}</td>"
            f"<td class='n'>{r['FG%'] * 100:.0f}%</td>"
            f"<td class='n'>{r['poss']}</td></tr>"
            for r in dfaced["rows"])
        def_html += (
            "<h2>How they attack a defense</h2><table><tr>"
            "<th>Defense faced</th><th class='n'>Share</th><th class='n'>PPP</th>"
            f"<th class='n'>FG%</th><th class='n'>Poss</th></tr>{rows_df}</table>"
            "<p class='note'>How this team scores against each scheme thrown at "
            "it. A low PPP on real volume = a defense to play against them.</p>")
    cx = sc.get("defense_cross")
    if _show("def_cross") and cx and cx.get("plays") and cx.get("defenses"):
        _dl, _pl, _mx = cx["def_label"], cx["play_label"], cx["matrix"]
        # drop all-blank rows/columns + skip the whole table if too thin, so the
        # sheet never prints a grid of em-dashes.
        _stable = [(pk, dk) for pk in cx["plays"] for dk in cx["defenses"]
                   if (_mx.get(pk, {}).get(dk) or {}).get("stable")]
        _plays = [pk for pk in cx["plays"] if any(p == pk for p, _ in _stable)]
        _defs = [dk for dk in cx["defenses"] if any(d == dk for _, d in _stable)]
        if len(_stable) >= 2:
            _head = "".join(f"<th class='n'>{e(_dl.get(d, d))}</th>" for d in _defs)
            _brows = []
            for pk in _plays:
                _tds = []
                for dk in _defs:
                    c = _mx.get(pk, {}).get(dk)
                    _tds.append(f"<td class='n'>{c['PPP']:.2f} ({c['poss']})</td>"
                                if c and c["stable"] else "<td class='n'>—</td>")
                _brows.append(
                    f"<tr><td>{e(_pl.get(pk, pk))}</td>{''.join(_tds)}</tr>")
            def_html += (
                "<h2>Play type &times; defense — PPP they score</h2>"
                f"<table><tr><th>Set</th>{_head}</tr>{''.join(_brows)}</table>"
                "<p class='note'>PPP this team scores running each set vs each "
                "scheme (cells with ≥10 poss; blank = thin). The overlap that says "
                "which defense to throw at which action.</p>")

    # ── team shot chart (inline SVG from tap-captured x/y) ──
    shot_html = ""
    team_shots = sc.get("team_shots") or []
    if _show("shot_chart") and team_shots:
        fga = len(team_shots)
        fgm = sum(1 for s in team_shots if s.get("make"))
        pct = 100 * fgm / fga if fga else 0
        shot_html = (
            "<h2>Shot chart</h2>"
            f"<div class='chart'>{CP.shot_chart_png(team_shots, width=330)}</div>"
            f"<p class='note'>{fga} located attempts · {fgm}/{fga} · {pct:.0f}% "
            "— the spots to take away. ● make · ✕ miss.</p>")

    # ── shot charts split by one-tap PLAY-TYPE and DEFENSE tag (filtered courts) ─
    # A small court per tag (≥5 located shots). Self-hides when a team isn't tagged
    # — so an entry-level coach never sees it and an all-in one gets the depth.
    def _shot_grid(groups, labels, title, key):
        if not (_show(key) and groups):
            return ""
        cells = []
        for k, lbl in labels:
            shots = groups.get(k) or []
            if len(shots) < 5:
                continue
            fgm, fga = sum(1 for s in shots if s.get("make")), len(shots)
            cells.append(
                f"<td><div class='diaglabel'>{e(lbl)} — {fgm}/{fga} "
                f"({100 * fgm / fga:.0f}%)</div>"
                f"{CP.shot_chart_png(shots, width=150)}</td>")
        if not cells:
            return ""
        grid = "".join(f"<tr>{''.join(cells[i:i + 3])}</tr>"
                       for i in range(0, len(cells), 3))
        return f"<h2>{title}</h2><table class='diag'>{grid}</table>"

    _DEF_LABELS = [(k, lbl) for k, lbl, *_ in DEF.DEFENSES]
    # offense: how THEY shoot, by the action they ran / the defense they faced
    sbp_html = _shot_grid(sc.get("shots_by_play") or {}, PT.NAMED_PLAY_TYPES,
                          "Shot charts by play type (their offense)", "shot_by_play")
    sbd_html = _shot_grid(sc.get("shots_by_def") or {}, _DEF_LABELS,
                          "Shot charts by defense faced (their offense)", "shot_by_def")
    # defense: what they ALLOW — opponents' shots by the action run on them /
    # by the scheme this team was running.
    sbpd_html = _shot_grid(sc.get("shots_allowed_by_play") or {}, PT.NAMED_PLAY_TYPES,
                           "Shots allowed by play type (their defense)",
                           "shot_by_play_def")
    sbdd_html = _shot_grid(sc.get("shots_allowed_by_def") or {}, _DEF_LABELS,
                           "Shots allowed by defensive scheme (their defense)",
                           "shot_by_def_def")

    # ── personnel cards: identity + OVR & breakdown + GS% + shots + mini chart ──
    # Hand-entered key-player intel (coach's dropdown picks) is folded into the
    # matching player's box here; the leftover (unmatched) intel prints in its own
    # table below. Match by player id first, then by name.
    _intel = extra.get("manual_intel") or []
    _pnotes = extra.get("player_notes") or {}     # {str(pid): freeform note}
    _intel_by_pid = {r["pid"]: r for r in _intel if r.get("pid") is not None}
    _intel_by_name = {str(r.get("name", "")).strip().lower(): r for r in _intel
                      if str(r.get("name", "")).strip()}
    _matched_intel = set()
    pers_html = ""
    if _show("personnel") and sc["personnel"]:
        mini_on = _show("shot_chart")
        cards = []
        for p in sc["personnel"]:
            ovr = f"OVR {p['ovr']}" if p.get("ovr") is not None else ""
            gs = (f"Starts {p['gs_pct']:.0f}%"
                  if p.get("gs_pct") is not None else "")
            head_bits = " · ".join(x for x in (ovr, gs) if x)
            pos = f" <span class='pos'>{e(p['pos'])}</span>" if p.get("pos") else ""
            head = (f"<div class='phead'><b>#{p['num']} {e(p['name'])}</b>{pos}"
                    + (f" <span class='ovr'>{e(head_bits)}</span>" if head_bits else "")
                    + "</div>")
            # measurables: height · weight · wingspan · hand
            bio = f"<div class='brk'>{e(p['bio'])}</div>" if p.get("bio") else ""
            # 0-100 category breakdown
            br = [(lbl, p.get(k)) for k, lbl in
                  (("off", "Off"), ("def", "Def"), ("ply", "Ply"), ("reb", "Reb"))]
            br = [f"{lbl} {v}" for lbl, v in br if v is not None]
            brk = (f"<div class='brk'>{e(' · '.join(br))} "
                   f"<span style='color:#8b949e'>(0–100, 50 = lg avg)</span></div>"
                   if br else "")
            _why = PR.overall_blurb(p.get("off"), p.get("def"),
                                    p.get("ply"), p.get("reb"))
            if _why:
                brk += f"<div class='brk' style='color:#b25e00'>{e(_why)}</div>"
            tp = f"{p['tp']:.0f}%" if p.get("tp") is not None else "—"
            ts = f"{p['ts']:.0f}%" if p.get("ts") is not None else "—"
            _usg = f" · USG {p['usg']:.0f}%" if p.get("usg") is not None else ""
            stat = (f"<div class='pstat'>{(p['ppg'] or 0):.1f} ppg · "
                    f"{(p['rpg'] or 0):.1f} reb · {(p['apg'] or 0):.1f} ast · "
                    f"3P {tp} · TS {ts}{_usg}</div>")
            # play-type tags per player (one-tap set calls): top 4 sets with
            # share + efficiency (PPP), e.g. "Iso 38% (1.21 PPP) · PnR 24% (0.88)"
            pm = p.get("playmix")
            play = ""
            if _show("player_plays") and pm:
                _goto = (f" ▶ go-to: {p['goto']}" if p.get("goto") else "")
                play = ("<div class='brk'>Plays: " + e(" · ".join(
                    f"{lbl} {pct:.0f}% ({ppp:.2f} PPP)"
                    for lbl, pct, ppp, _fg in pm[:4])
                    + f" (n={p['playmix_n']}){_goto}") + "</div>")
            hd = p.get("hand")
            hand_html = ""
            if hd:
                hand_html = ("<div class='brk'>Hand side: " + e(
                    f"Dom {hd['dom_pct'] * 100:.0f}% ({hd['dom_fga']}) · "
                    f"Weak {hd['weak_pct'] * 100:.0f}% ({hd['weak_fga']})") + "</div>")
            sp = p.get("space")
            space_html = ""
            if sp and sp.get("cue"):
                space_html = ("<div class='brk'>Contest: " + e(
                    f"{sp['cliff']:+d} open vs guarded ({sp['n']})") + "</div>")
            _spi = (p.get("spacing") or {}).get("index")
            spc_html = (f"<div class='brk'>Floor spacing: {_spi}/100 vs league</div>"
                        if _spi is not None else "")
            # tactical cue tag (force-hand / space dependence) — the actionable
            # directives, surfaced prominently to match the on-screen scout tab's
            # ✋ badge (previously only buried at the tail of the detail lines).
            _cues = []
            if hd and hd.get("cue"):
                _cues.append(hd["cue"])
            if sp and sp.get("cue"):
                _cues.append(sp["cue"])
            cue_html = (f"<div class='pnote'>✋ {e(' · '.join(_cues))}</div>"
                        if _cues else "")
            note = (f"<div class='pnote'>▶ {e(p['note'])}</div>"
                    if p.get("note") else "")
            # your hand-entered scouting note for this player, in their box
            _mi = (_intel_by_pid.get(p.get("pid"))
                   or _intel_by_name.get(str(p.get("name", "")).strip().lower()))
            inote = ""
            if _mi and str(_mi.get("note", "")).strip():
                _mk = _mi.get("pid", str(_mi.get("name", "")).strip().lower())
                _matched_intel.add(_mk)
                inote = (f"<div class='pnote' style='color:#1a5fb4'>📋 "
                         f"{e(str(_mi['note']).strip())}</div>")
            # your freeform per-player note (the Custom notes editor)
            _cn = _pnotes.get(str(p.get("pid")))
            cnote = (f"<div class='pnote' style='color:#0a7d33'>&#9998; "
                     f"{e(str(_cn).strip())}</div>"
                     if _cn and str(_cn).strip() else "")
            shots = p.get("shots") or []
            mini = (f"<div class='mini'>"
                    f"{CP.shot_chart_png(shots, width=132)}</div>"
                    if mini_on and len(shots) >= 5 else "")
            cards.append(f"<td class='pcard'>{head}{bio}{brk}{stat}{play}"
                         f"{hand_html}{space_html}{spc_html}{cue_html}{note}"
                         f"{inote}{cnote}{mini}</td>")
        # two cards per row
        rows = ""
        for i in range(0, len(cards), 2):
            pair = cards[i:i + 2]
            if len(pair) == 1:
                pair.append("<td class='pcard empty'></td>")
            rows += f"<tr>{''.join(pair)}</tr>"
        pers_html = f"<h2>Personnel</h2><table class='cards'>{rows}</table>"

    # ── per-player 3-point profile ──
    three_html = ""
    tpr = extra.get("three_profile")
    if _show("three_profile") and tpr and tpr.get("players"):
        be3 = tpr.get("be3_pct", 0)
        rows3 = ""
        for pl in tpr["players"]:
            tag = "above" if pl["above"] else "below"
            rows3 += (f"<tr><td>{e(pl['label'])}</td>"
                      f"<td class='n'>{pl['p3']:.0f}%</td>"
                      f"<td class='n'>{pl['att']}</td><td>{tag} breakeven</td></tr>")
        three_html = (
            "<h2>Per-player 3-point profile</h2><table><tr><th>Player</th>"
            "<th class='n'>3P%</th><th class='n'>3PA</th><th>vs breakeven</th></tr>"
            f"{rows3}</table><p class='note'>Breakeven {be3:.0f}% — above = their "
            "threes beat their twos. Min 4 attempts.</p>")

    # ── scoring by possession length ──
    plen_html = ""
    pl = extra.get("poss_length")
    if _show("poss_length") and pl:
        rowsp = "".join(
            f"<tr><td>{e(r['label'])}</td><td class='n'>{r['PPP']:.2f}</td>"
            f"<td class='n'>{r['FGA']}</td><td class='n'>{r['FG%'] * 100:.0f}%</td></tr>"
            for r in pl)
        plen_html = (
            "<h2>Scoring by possession length</h2><table><tr><th>Length</th>"
            "<th class='n'>Pts/shot</th><th class='n'>FGA</th>"
            f"<th class='n'>FG%</th></tr>{rowsp}</table>")

    # ── scoring by quarter ──
    qs_html = ""
    qs = extra.get("quarter_split")
    if _show("quarter_split") and qs:
        rows = "".join(
            f"<tr><td>Q{r['q']}</td><td class='n'>{r['pts']}</td>"
            f"<td class='n'>{r['opp']}</td><td class='n'>{r['margin']:+d}</td>"
            f"<td class='n'>{_pf(r['efg'])}</td><td class='n'>{_pf(r['oefg'])}</td></tr>"
            for r in qs)
        qs_html = (
            "<h2>Scoring by quarter</h2><table><tr><th>Qtr</th><th class='n'>Pts</th>"
            "<th class='n'>Opp</th><th class='n'>+/-</th><th class='n'>eFG</th>"
            f"<th class='n'>opp eFG</th></tr>{rows}</table>")

    # ── contested vs open (eFG) ──
    gs_html = ""
    gsd = extra.get("guarded_split")
    if _show("guarded_split") and gsd:
        rows = "".join(
            f"<tr><td>{e(r['label'])}</td><td class='n'>{_pf(r['g_efg'])}</td>"
            f"<td class='n'>{_pf(r['o_efg'])}</td><td class='n'>{_pf(r['share'])}</td></tr>"
            for r in gsd)
        gs_html = (
            "<h2>Contested vs open (eFG)</h2><table><tr><th>Shots</th>"
            "<th class='n'>Guarded eFG</th><th class='n'>Open eFG</th>"
            f"<th class='n'>Contested%</th></tr>{rows}</table>"
            "<p class='note'>A big open − guarded gap = a shooter who needs space "
            "(close out hard); a small one = contest-proof (deny the catch).</p>")

    # ── zone shooting vs a league baseline (xFG), split 2s vs 3s ──
    zx_html = ""
    zx = extra.get("zone_xfg")
    if _show("zone_xfg") and zx:
        def _xcell(fg, xfg):
            if fg is None:
                return "—"
            d = (f" ({'%+.0f' % ((fg - xfg) * 100)})" if xfg is not None else "")
            return f"{fg * 100:.0f}%{d}"
        rows = "".join(
            f"<tr><td>{e(r['label'])}</td>"
            f"<td class='n'>{r['fga2']}</td><td class='n'>{_xcell(r['fg2'], r['xfg2'])}</td>"
            f"<td class='n'>{r['fga3']}</td><td class='n'>{_xcell(r['fg3'], r['xfg3'])}</td></tr>"
            for r in zx)
        zx_html = (
            "<h2>Zone shooting vs expected</h2><table><tr><th>Zone</th>"
            "<th class='n'>2P att</th><th class='n'>2P FG% (vs x)</th>"
            "<th class='n'>3P att</th><th class='n'>3P FG% (vs x)</th></tr>"
            f"{rows}</table>"
            "<p class='note'>FG% vs a league baseline (xFG%) for those shots, split "
            "2s vs 3s. The (±) is over/under expected — positive = take it away.</p>")

    # ── self-created vs assisted ──
    cr_html = ""
    cr = extra.get("creation")
    if _show("creation") and cr:
        rows = "".join(
            f"<tr><td>{e(r['label'])}</td><td class='n'>{r['fga']}</td>"
            f"<td class='n'>{_pf(r['fg'])}</td><td class='n'>{_pf(r['efg'])}</td>"
            f"<td class='n'>{r['pps']:.2f}</td></tr>" for r in cr)
        cr_html = (
            "<h2>Self-created vs assisted</h2><table><tr><th>Shot origin</th>"
            "<th class='n'>FGA</th><th class='n'>FG%</th><th class='n'>eFG</th>"
            f"<th class='n'>Pts/shot</th></tr>{rows}</table>"
            "<p class='note'>Heavy self-created = shot-maker reliant (key the "
            "creators, make role players beat you); heavy assisted = ball movement "
            "(jump the first pass).</p>")

    # ── where their defense concedes (allowed shot quality by zone) ──
    con_html = ""
    con = extra.get("def_concession")
    if _show("def_concession") and con and con.get("rows"):
        rows = "".join(
            f"<tr><td>{e(r['label'])}</td><td class='n'>{r['n']}</td>"
            f"<td class='n'>{_pf(r['share'])}</td><td class='n'>{r['pps']:.2f}</td>"
            f"<td class='n'>{r['xpps']:.2f}</td><td class='n'>{r['residual']:+.2f}</td></tr>"
            for r in con["rows"]
            if r.get("n") and r.get("pps") is not None and r.get("xpps") is not None
            and r.get("residual") is not None)
        if rows:
            con_html = (
                "<h2>Where their defense concedes</h2><table><tr><th>Zone</th>"
                "<th class='n'>Allowed</th><th class='n'>Share</th>"
                "<th class='n'>PPS</th><th class='n'>xPPS</th><th class='n'>+/-</th>"
                f"</tr>{rows}</table>"
                f"<p class='note'>{e(con.get('note', ''))} Positive +/- = a spot they "
                "give up better-than-expected looks — attack it.</p>")

    # ── how scoutable are they (play-call + defense-scheme predictability) ──
    pred_html = ""
    pr = extra.get("predictability")
    if _show("predictability") and pr and (pr.get("off_rated") or pr.get("def_rated")):
        who = "We are" if pr.get("is_self") else "They are"
        head = ""
        if pr.get("off_rated"):
            head += (f"<li><b>{who} {pr['off_pred']:.0f}/100 predictable on offense</b> "
                     "— higher = a scout keys on them faster. Most-run: "
                     f"{e(pr.get('off_top') or '—')} ({(pr.get('off_share') or 0):.0f}%).</li>")
        if pr.get("def_rated"):
            head += (f"<li><b>{who} {pr['def_pred']:.0f}/100 predictable on defense</b> "
                     "— their scheme mix. Most-run: "
                     f"{e(pr.get('def_top') or '—')} ({(pr.get('def_share') or 0):.0f}%).</li>")
        ou = "".join(
            f"<li>{e(r['label'])} — {r['share'] * 100:.0f}% of sets · {r['PPP']:.2f} "
            "PPP (predictable &amp; inefficient — sit on it)</li>"
            for r in (pr.get("overused") or []))
        un = "".join(
            f"<li>{e(r['label'])} — only {r['share'] * 100:.0f}% · {r['PPP']:.2f} PPP "
            "(efficient but under-run)</li>" for r in (pr.get("underused") or []))
        pred_html = f"<h2>How scoutable are they?</h2><ul>{head}{ou}{un}</ul>"

    # ── manual key-player intel (coach-entered; works for COLD opponents) ──
    # Only the rows NOT already shown inside a personnel box above (matched intel
    # rides in the player's card; the rest — e.g. for a cold opponent with no
    # rated personnel — print here so nothing is lost).
    intel_html = ""
    intel_rows = extra.get("manual_intel") or []
    if _show("manual_intel") and intel_rows:
        def _unmatched(r):
            _mk = r.get("pid", str(r.get("name", "")).strip().lower())
            return _mk not in _matched_intel
        rws = "".join(
            f"<tr><td class='n'>{e(str(r.get('num', '')))}</td>"
            f"<td>{e(str(r.get('name', '')))}</td>"
            f"<td>{e(str(r.get('note', '')))}</td></tr>"
            for r in intel_rows if str(r.get('name', '')).strip() and _unmatched(r))
        if rws:
            intel_html = (
                "<h2>Key players (your scouting)</h2><table><tr>"
                "<th class='n'>#</th><th>Player</th>"
                f"<th>How to guard / threat</th></tr>{rws}</table>")

    # ── game-plan notes (coach prose) ──
    notes_html = ""
    ntext = (extra.get("notes") or "").strip()
    if _show("notes") and ntext:
        notes_html = (f"<h2>Game-plan notes</h2>"
                      f"<div class='notes-box'>{e(ntext)}</div>")

    # ── blank play diagrams (hand-draw after printing) ──
    # A dense grid of blank half-courts with a write-your-own name line on top of
    # each (no pre-set BLOB/SLOB labels) — coaches name plays themselves. 4-across
    # × 2 rows = 8 courts in the same footprint the old 2×2 used; extra/unused
    # courts are intentional (better to have spare than run short).
    diag_html = ""
    if _show("play_diagrams"):
        legend = ("<p class='note'>Write each play's name on the line, draw below. "
                  "○ offense · ✕ defense · → cut · ⇢ pass · ⊢ screen · "
                  "∿ dribble</p>")
        court = CP.blank_halfcourt_png(width=165)   # cached; reuse the one string
        cell = f"<td><div class='diagname'></div>{court}</td>"
        per_row, n_courts = 4, 8
        rows = "".join(f"<tr>{cell * per_row}</tr>"
                       for _ in range(n_courts // per_row))
        diag_html = ("<h2>Play diagrams — draw by hand</h2>" + legend +
                     f"<table class='diag'>{rows}</table>")

    # ── situational tendencies (play/defense usage by quarter / score / run) ──
    sit_html = ""
    sit = sc.get("situational")
    if _show("situational") and sit and sit.get("rows"):
        rows_sit = "".join(
            f"<tr><td>{e(r['label'])}</td>"
            f"<td class='n'>{r['poss']}</td>"
            f"<td class='n'>{r['PPP']:.2f}</td>"
            f"<td class='n'>{r['FG%'] * 100:.0f}%</td>"
            f"<td>{e(r['top'])}</td></tr>" for r in sit["rows"])
        if rows_sit:
            sit_html = (
                "<h2>Situational tendencies — when they run it</h2><table><tr>"
                "<th>Situation</th><th class='n'>Poss</th><th class='n'>PPP</th>"
                f"<th class='n'>FG%</th><th>Go-to set</th></tr>{rows_sit}</table>")
            conc = sit.get("concentration") or []
            if conc:
                bits = " · ".join(
                    f"{e(c['play_label'])} in {e(c['sit_label'])} "
                    f"({c['lift']:.1f}×)" for c in conc[:4])
                sit_html += (f"<p class='note'><b>Situational sets:</b> {bits}. "
                             "Offensive profile by quarter, score state and running "
                             "game; PPP = points per possession.</p>")
            else:
                sit_html += ("<p class='note'>Offensive profile by quarter, score "
                             "state and running game; PPP = points per possession. "
                             "'Go-to set' needs tagged plays.</p>")
            # share-by-situation usage maps (offense sets + defensive schemes) —
            # the scout-sheet twin of the Situational tab heatmaps; self-hide empty.
            sit_html += usage_map_html(sit.get("situations") or [], "plays",
                                       "Set-usage map — share by situation", "Set")
            sit_html += usage_map_html(sit.get("situations") or [], "defenses",
                                       "Defense-usage map — share by situation",
                                       "Scheme")

    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<title>Scout · {e(sc['name'])}</title>
<style>
*{{box-sizing:border-box}}
html{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
body{{font-family:'Segoe UI',Arial,sans-serif;color:#111;margin:0;font-size:11px;
  line-height:1.35;background:#fff}}
.wrap{{max-width:760px;margin:0 auto;padding:14px 18px}}
h1{{margin:0;font-size:18px;letter-spacing:.2px}}
.meta{{color:#555;font-size:11px;margin-top:2px}}
.rng{{color:#222;font-size:11px;font-weight:600;margin:1px 0 8px}}
h2{{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:#111;
  border-bottom:1.5px solid #111;padding-bottom:2px;margin:11px 0 5px}}
table.cols{{width:100%;border-collapse:separate;border-spacing:10px 0;font-size:11px}}
td.col{{width:50%;vertical-align:top;border:none;padding:0}}
ul{{margin:2px 0;padding-left:15px}} li{{margin:2px 0}}
table{{border-collapse:collapse;width:100%;font-size:11px}}
th{{text-align:left;font-size:9px;text-transform:uppercase;letter-spacing:.4px;
  color:#666;border-bottom:1px solid #111;padding:2px 6px}}
td{{padding:2px 6px;border-bottom:1px solid #ddd;vertical-align:top}}
.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.note{{color:#555;font-size:10px;margin:3px 0}}
table.two{{width:100%;border-collapse:separate;border-spacing:10px 0;font-size:11px}}
td.two-col{{width:50%;vertical-align:top;border:none;padding:0}}
.chart{{text-align:center;margin:4px 0}}
img.court-img{{max-width:100%;height:auto}}
table.cards{{border-collapse:separate;border-spacing:8px 8px;width:100%}}
td.pcard{{width:50%;border:1px solid #ccc;padding:6px 8px;vertical-align:top}}
td.pcard.empty{{border:none}}
.phead{{font-size:12px;margin-bottom:1px}}
.ovr{{color:#444;font-size:10px;font-weight:700}}
.pos{{color:#444;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}}
.brk{{color:#555;font-size:10px}}
.pstat{{font-size:11px;margin:1px 0}}
.pnote{{color:#b25e00;font-size:10px;margin-top:1px}}
.mini{{text-align:center;margin-top:4px}}
.notes-box{{white-space:pre-wrap;border:1px solid #ddd;padding:6px;font-size:11px;
  min-height:46px}}
table.diag{{border-collapse:separate;border-spacing:7px;width:100%}}
table.diag td{{border:none;text-align:center;vertical-align:top;padding:1px}}
.diagname{{border-bottom:1px solid #999;height:13px;margin:0 3px 3px}}
.foot{{margin-top:12px;color:#999;font-size:9px}}
/* Compact layout: flow the text/table sections into TWO columns so far more
   fits per page (browser print honours column-count; xhtml2pdf ignores it and
   falls back to a single column — still valid). Keep each h2+table together. */
.flow2{{column-count:2;column-gap:18px}}
.flow2>h2:first-child{{margin-top:0}}
.flow2 h2{{break-after:avoid;-webkit-column-break-after:avoid}}
.flow2 table,.flow2 ul,.flow2 .note,.flow2 .notes-box,.flow2 .hb{{
  break-inside:avoid;-webkit-column-break-inside:avoid}}
table.brandbar{{width:100%;border-collapse:collapse;border-bottom:2px solid #f0a500;
  margin-bottom:6px}}
table.brandbar td{{border:none;padding:0 0 3px;vertical-align:bottom}}
.brand{{color:#f0a500;font-weight:800;font-size:14px;letter-spacing:.2px}}
.brandtag{{text-align:right;color:#999;font-size:9px;text-transform:uppercase;
  letter-spacing:1.2px}}
@page{{margin:.4in}}
@media print{{.wrap{{padding:6px 10px}} td.pcard,table.diag td{{page-break-inside:avoid}}}}
</style></head><body><div class='wrap'>
<table class='brandbar'><tr>
<td class='brand'>{_BRAND_MARK} HoopTracks</td>
<td class='brandtag'>scouting report</td></tr></table>
<h1>SCOUT — {e(sc['name'])}</h1>
<div class='meta'>{e(opponent_label)} · {e(sc['class'])} · {e(sc['record'])} ·
  Power #{sc['rank']}/{sc['of']}</div>
<div class='rng'>{e(rng)}</div>
{keys_html}
{report_html}
{coach_html}
{pers_html}
{intel_html}
{mu_html}
{two_html}
{_flow_open}{eff_html}
{breakeven_html}
{pred_html}
{pc_html}
{three_html}
{cr_html}
{plen_html}
{qs_html}
{def_html}
{con_html}
{sit_html}
{gs_html}
{zx_html}
{notes_html}{_flow_close}
{shot_html}
{sbp_html}
{sbd_html}
{sbpd_html}
{sbdd_html}
{diag_html}
<div class='foot'>Made with <b style='color:#f0a500'>HoopTracks</b> ·
  app.hooptracks.com{(' · ' + today) if today else ''}</div>
</div></body></html>"""
