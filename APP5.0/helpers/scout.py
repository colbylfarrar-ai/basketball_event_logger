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

ZONE_LABELS = {"LC": "Left corner", "LW": "Left wing", "C": "Center / top",
               "RW": "Right wing", "RC": "Right corner"}


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

    # how each player gets their shots: self / off a pass / off a screen / both,
    # as a share of their own FGA (the shooter-side creation mix).
    cmix = {}
    for e in ev:
        if e["event_type"] != "shot" or e["primary_player_id"] is None:
            continue
        hp = e["pass_from_id"] is not None
        hc = e["shot_created_by_id"] is not None
        k = "both" if hp and hc else "pass" if hp else "screen" if hc else "self"
        cmix.setdefault(e["primary_player_id"],
                        {"self": 0, "pass": 0, "screen": 0, "both": 0})[k] += 1
    for p in personnel:
        c = cmix.get(p["pid"])
        tot = sum(c.values()) if c else 0
        p["creation"] = {k: 100 * c[k] / tot for k in c} if tot else None

    # how each player gets their shots by the one-tap play_type tag (pnr / iso /
    # post / …): the literal set call, as a share of that player's TAGGED shots.
    # Sparse until a coach tags — None when this player has no tagged shots.
    _PT_LABEL = dict(PT.NAMED_PLAY_TYPES)
    pmix = {}
    for e in ev:
        if e["event_type"] != "shot" or e["primary_player_id"] is None:
            continue
        pt = e.get("play_type")
        if not pt:
            continue
        pt = pt if pt in _PT_LABEL else "other"
        d = pmix.setdefault(e["primary_player_id"], {})
        d[pt] = d.get(pt, 0) + 1
    for p in personnel:
        c = pmix.get(p["pid"])
        tot = sum(c.values()) if c else 0
        if tot:
            ordered = sorted(c.items(), key=lambda kv: -kv[1])
            p["playmix"] = [(_PT_LABEL.get(k, k), 100 * n / tot) for k, n in ordered]
            p["playmix_n"] = tot
        else:
            p["playmix"] = None
            p["playmix_n"] = 0

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

    # ── how they get their shots: explicit one-tap play-call tags ─────────────
    # The literal set call a coach taps on a shot in the tracker (pnr / iso /
    # post / spot / …). Reuses the events already pulled and the same visible
    # game set, so it honours the entitlement filter like every view above.
    play_calls = PT.team_named_playtypes(team_id, events=ev, offense=True)

    return {
        "name": name, "class": s.get("class", "N/A"),
        "record": f"{s.get('W',0)}-{s.get('L',0)}",
        "rank": s.get("Rank"), "of": len(scored), "power": s.get("Power"),
        "trk": tracked.get(team_id),
        "factors": factors, "strengths": strengths, "weaknesses": weaknesses,
        "guard": guard, "attack": attack, "personnel": personnel,
        "zones": zones, "zones_by_type": zones_by_type,
        "team_shots": team_shots, "play_calls": play_calls,
        "has_tracked": me is not None,
    }


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


def printable_html(sc, opponent_label, hidden=None, extra=None):
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

    hidden = hidden or set()

    def _show(k):
        return k not in hidden

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

    # ── how they get their shots: tagged play calls (one-tap from the tracker) ─
    pc_html = ""
    pc = sc.get("play_calls")
    if _show("play_calls") and pc and pc.get("rows"):
        rows_pc = "".join(
            f"<tr><td>{e(r['label'])}</td>"
            f"<td class='n'>{r['share'] * 100:.0f}%</td>"
            f"<td class='n'>{r['PPP']:.2f}</td>"
            f"<td class='n'>{r['FG%'] * 100:.0f}%</td>"
            f"<td class='n'>{r['poss']}</td></tr>"
            for r in sorted(pc["rows"], key=lambda r: r["share"], reverse=True))
        pc_html = (
            "<h2>How they get their shots — play calls</h2><table><tr>"
            "<th>Play call</th><th class='n'>Share</th><th class='n'>PPP</th>"
            f"<th class='n'>FG%</th><th class='n'>Poss</th></tr>{rows_pc}</table>"
            f"<p class='note'>Coach-tagged set calls on {pc['total_tagged']} shots "
            f"({pc['untagged']} untagged). Share = % of tagged shots; PPP = points "
            "per possession.</p>")

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

    # ── personnel cards: identity + OVR & breakdown + GS% + shots + mini chart ──
    pers_html = ""
    if _show("personnel") and sc["personnel"]:
        _SRC = (("self", "SC"), ("pass", "Pass"), ("screen", "Screen"),
                ("both", "Both"))
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
            brk = f"<div class='brk'>{e(' · '.join(br))}</div>" if br else ""
            tp = f"{p['tp']:.0f}%" if p.get("tp") is not None else "—"
            ts = f"{p['ts']:.0f}%" if p.get("ts") is not None else "—"
            stat = (f"<div class='pstat'>{(p['ppg'] or 0):.1f} ppg · "
                    f"{(p['rpg'] or 0):.1f} reb · {(p['apg'] or 0):.1f} ast · "
                    f"3P {tp} · TS {ts}</div>")
            cm = p.get("creation")
            src = ""
            if _show("shot_source") and cm:
                src = ("<div class='brk'>Shots: " + e(" · ".join(
                    f"{lbl} {cm[k]:.0f}%" for k, lbl in _SRC if k in cm)) + "</div>")
            # play-type tags per player (one-tap set calls): top 4, share of tagged
            pm = p.get("playmix")
            play = ""
            if _show("play_calls") and pm:
                play = ("<div class='brk'>Plays: " + e(" · ".join(
                    f"{lbl} {pct:.0f}%" for lbl, pct in pm[:4])
                    + f" (n={p['playmix_n']})") + "</div>")
            hd = p.get("hand")
            hand_html = ""
            if hd:
                _cue = f" ▶ {hd['cue']}" if hd.get("cue") else ""
                hand_html = ("<div class='brk'>Hand side: " + e(
                    f"Dom {hd['dom_pct'] * 100:.0f}% ({hd['dom_fga']}) · "
                    f"Weak {hd['weak_pct'] * 100:.0f}% ({hd['weak_fga']}){_cue}") + "</div>")
            sp = p.get("space")
            space_html = ""
            if sp and sp.get("cue"):
                space_html = ("<div class='brk'>Contest: " + e(
                    f"{sp['cliff']:+d} open vs guarded ({sp['n']}) ▶ {sp['cue']}")
                    + "</div>")
            note = (f"<div class='pnote'>▶ {e(p['note'])}</div>"
                    if p.get("note") else "")
            shots = p.get("shots") or []
            mini = (f"<div class='mini'>"
                    f"{CP.shot_chart_png(shots, width=132)}</div>"
                    if mini_on and len(shots) >= 5 else "")
            cards.append(f"<td class='pcard'>{head}{bio}{brk}{stat}{src}{play}"
                         f"{hand_html}{space_html}{note}{mini}</td>")
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
@media print{{.wrap{{padding:8px 12px}} td.pcard,table.diag td{{page-break-inside:avoid}}}}
</style></head><body><div class='wrap'>
<h1>SCOUT — {e(sc['name'])}</h1>
<div class='meta'>{e(opponent_label)} · {e(sc['class'])} · {e(sc['record'])} ·
  Power #{sc['rank']}/{sc['of']}</div>
<div class='rng'>{e(rng)}</div>
{keys_html}
{two_html}
{breakeven_html}
{eff_html}
{report_html}
{pc_html}
{shot_html}
{pers_html}
{three_html}
{plen_html}
{notes_html}
{diag_html}
<div class='foot'>Analytics Hub{(' · ' + today) if today else ''}</div>
</div></body></html>"""
