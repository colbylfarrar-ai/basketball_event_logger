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
    team_pids = tuple(r["id"] for r in
                      query("SELECT id FROM players WHERE team_id=?", (team_id,)))
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

    return {
        "name": name, "class": s.get("class", "N/A"),
        "record": f"{s.get('W',0)}-{s.get('L',0)}",
        "rank": s.get("Rank"), "of": len(scored), "power": s.get("Power"),
        "trk": tracked.get(team_id),
        "factors": factors, "strengths": strengths, "weaknesses": weaknesses,
        "guard": guard, "attack": attack, "personnel": personnel,
        "zones": zones, "zones_by_type": zones_by_type,
        "has_tracked": me is not None,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PRINTABLE HTML
# ══════════════════════════════════════════════════════════════════════════════

def printable_html(sc, opponent_label, hidden=None):
    """A compact, print-ready ONE-PAGE scouting sheet (browser → Print → PDF).
    Zero dependencies; intentionally small and simple — no branding band, bars or
    badges, four factors and zones sit side by side to keep it to a page."""
    import datetime
    e = html.escape
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

    # ── personnel: stats row + a full-width second line (shot source + note) ──
    pers_html = ""
    if _show("personnel"):
        _SRC = (("self", "SC"), ("pass", "Pass"), ("screen", "Screen"),
                ("both", "Both"))
        pers = ""
        for p in sc["personnel"]:
            fgp = f"{p['fg']:.0f}" if p.get("fg") is not None else "—"
            tp = f"{p['tp']:.0f}" if p["tp"] is not None else "—"
            pers += (f"<tr><td><b>#{p['num']} {e(p['name'])}</b></td>"
                     f"<td class='n'>{(p['ppg'] or 0):.1f}</td>"
                     f"<td class='n'>{(p['rpg'] or 0):.1f}</td>"
                     f"<td class='n'>{(p['apg'] or 0):.1f}</td>"
                     f"<td class='n'>{fgp}</td><td class='n'>{tp}</td></tr>")
            cm = p.get("creation")
            src = ""
            if _show("shot_source") and cm:
                src = "Shots: " + " · ".join(f"{lbl} {cm[k]:.0f}%"
                                             for k, lbl in _SRC if k in cm)
            note = e(p["note"]) if p.get("note") else ""
            line2 = " — ".join(x for x in (src, note) if x)
            if line2:
                pers += f"<tr><td colspan='6' class='note'>{line2}</td></tr>"
        pers_html = ("<h2>Personnel</h2><table><tr><th>Player</th>"
                     "<th class='n'>PPG</th><th class='n'>RPG</th>"
                     "<th class='n'>APG</th><th class='n'>FG%</th>"
                     f"<th class='n'>3P%</th></tr>{pers}</table>")

    # ── strengths & exploit (top / bottom factors by league percentile) ──
    edges_html = ""
    if _show("edges") and (sc["strengths"] or sc["weaknesses"]):
        st_li = "".join(f"<li>{e(f['label'])} — {(f['value'] or 0):.1f} "
                        f"({f['pct']:.0f}th)</li>"
                        for f in sc["strengths"]) or "<li>—</li>"
        wk_li = "".join(f"<li>{e(f['label'])} — {(f['value'] or 0):.1f} "
                        f"({f['pct']:.0f}th)</li>"
                        for f in sc["weaknesses"]) or "<li>—</li>"
        edges_html = (f"<table class='cols'><tr>"
                      f"<td class='col'><h2>Strengths (&ge;70th)</h2><ul>{st_li}</ul></td>"
                      f"<td class='col'><h2>Exploit (&le;30th)</h2><ul>{wk_li}</ul></td>"
                      f"</tr></table>")

    # ── scoring leaders (top 3 by PPG; personnel is pre-sorted) ──
    leaders_html = ""
    if _show("leaders") and sc["personnel"]:
        _lead = " · ".join(f"#{p['num']} {e(p['name'])} {(p['ppg'] or 0):.1f} ppg"
                           for p in sc["personnel"][:3])
        leaders_html = f"<h2>Scoring leaders</h2><p class='lead'>{_lead}</p>"

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
.note{{color:#555;font-size:10px}}
table.two{{width:100%;border-collapse:separate;border-spacing:10px 0;font-size:11px}}
td.two-col{{width:50%;vertical-align:top;border:none;padding:0}}
.foot{{margin-top:12px;color:#999;font-size:9px}}
@media print{{.wrap{{padding:8px 12px}}}}
</style></head><body><div class='wrap'>
<h1>SCOUT — {e(sc['name'])}</h1>
<div class='meta'>{e(opponent_label)} · {e(sc['class'])} · {e(sc['record'])} ·
  Power #{sc['rank']}/{sc['of']}</div>
<div class='rng'>{e(rng)}</div>
{keys_html}
{edges_html}
{two_html}
{leaders_html}
{pers_html}
<div class='foot'>Analytics Hub{(' · ' + today) if today else ''}</div>
</div></body></html>"""
