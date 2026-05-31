"""
scout.py — coach's scouting-report engine (FastScout-style game prep).

The assembly + printable-HTML layer behind Team Analytics' "🎯 Scout" tab: four
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
from helpers.ui import GOOD, BAD
import helpers.league_analytics as LA
import helpers.badges as BG
import helpers.stats as S

ZONE_LABELS = {"LC": "Left corner", "LW": "Left wing", "C": "Paint/center",
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


# ══════════════════════════════════════════════════════════════════════════════
#  SCOUT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_scout(team_id, gender, scored, tracked, pack, table):
    """Assemble every piece of the scouting report for one team."""
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
    personnel = []
    for r in roster[:7]:
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
            "name": r["name"], "num": r.get("number"),
            "ppg": r.get("PPG"), "rpg": r.get("RPG"), "apg": r.get("APG"),
            "fg": r.get("FG%"), "tp": r.get("3P%"), "ts": r.get("TS%"),
            "rim": r.get("RimFGA%"), "three": r.get("3PR"),
            "ovr": r.get("OVERALL"), "note": "; ".join(notes),
            "badges": [f"{b['emoji']} {b['name']}" for b in bl],
        })

    # ── hot zones ──
    gids = S.team_game_ids(team_id, tracked_only=True)
    team_pids = tuple(r["id"] for r in
                      query("SELECT id FROM players WHERE team_id=?", (team_id,)))
    zones = team_zone(tuple(gids), team_pids)

    return {
        "name": name, "class": s.get("class", "N/A"),
        "record": f"{s.get('W',0)}-{s.get('L',0)}",
        "rank": s.get("Rank"), "of": len(scored), "power": s.get("Power"),
        "trk": tracked.get(team_id),
        "factors": factors, "strengths": strengths, "weaknesses": weaknesses,
        "guard": guard, "attack": attack, "personnel": personnel,
        "zones": zones, "has_tracked": me is not None,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PRINTABLE HTML
# ══════════════════════════════════════════════════════════════════════════════

def _bar_html(pct, color):
    pct = pct if pct is not None else 0
    return (f"<div style='background:#eee;border-radius:4px;height:12px;width:120px;"
            f"display:inline-block;vertical-align:middle'>"
            f"<div style='background:{color};width:{pct}%;height:12px;"
            f"border-radius:4px'></div></div>")


def printable_html(sc, opponent_label):
    e = html.escape
    trk = sc["trk"]
    rng = (f"ORtg {trk['ORtg']:.0f} · DRtg {trk['DRtg']:.0f} · "
           f"Net {trk['NetRtg']:+.0f} · Pace {trk['Pace']:.0f}") if trk else "—"
    rows_f = ""
    for f in sc["factors"]:
        if f["value"] is None:
            continue
        clr = GOOD if (f["pct"] or 0) >= 60 else (BAD if (f["pct"] or 0) <= 40 else "#888")
        rows_f += (f"<tr><td>{e(f['label'])}</td><td style='text-align:right'>"
                   f"{f['value']:.1f}</td><td>{_bar_html(f['pct'], clr)} "
                   f"{('%.0f' % f['pct']) + 'pctl' if f['pct'] is not None else ''}</td></tr>")
    guard = "".join(f"<li>{e(x)}</li>" for x in sc["guard"])
    attack = "".join(f"<li>{e(x)}</li>" for x in sc["attack"])
    pers = ""
    for p in sc["personnel"]:
        bdg = " ".join(e(b) for b in p["badges"])
        pers += (f"<tr><td><b>#{p['num']} {e(p['name'])}</b></td>"
                 f"<td>{(p['ppg'] or 0):.1f}</td><td>{(p['rpg'] or 0):.1f}</td>"
                 f"<td>{(p['apg'] or 0):.1f}</td>"
                 f"<td>{('%.0f%%'%p['tp']) if p['tp'] is not None else '—'}</td>"
                 f"<td>{e(p['note'])}<br><span style='color:#666;font-size:11px'>{bdg}</span></td></tr>")
    zr = ""
    for z in S.ZONES:
        zz = sc["zones"].get(z, {})
        zr += (f"<tr><td>{ZONE_LABELS[z]}</td><td>{zz.get('FGM',0)}/{zz.get('FGA',0)}</td>"
               f"<td>{zz.get('pct',0):.0f}%</td></tr>")

    return f"""<!doctype html><html><head><meta charset='utf-8'>
<title>Scout · {e(sc['name'])}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;color:#111;margin:24px;font-size:13px}}
h1{{margin:0;font-size:24px}} h2{{font-size:15px;border-bottom:2px solid #111;
padding-bottom:3px;margin:18px 0 8px}}
table{{border-collapse:collapse;width:100%}} td,th{{padding:4px 8px;border-bottom:1px solid #ddd}}
.sub{{color:#555;margin:2px 0 10px}} .cols{{display:flex;gap:24px}}
.col{{flex:1}} ul{{margin:4px 0;padding-left:18px}} li{{margin:3px 0}}
@media print{{body{{margin:10px}}}}
</style></head><body>
<h1>SCOUTING REPORT — {e(sc['name'])}</h1>
<div class='sub'>{e(opponent_label)} · {e(sc['class'])} · Record {sc['record']} ·
Power rank #{sc['rank']}/{sc['of']} · {e(rng)}</div>
<div class='cols'>
<div class='col'><h2>Keys — How to guard them</h2><ul>{guard}</ul></div>
<div class='col'><h2>Keys — How to attack them</h2><ul>{attack}</ul></div>
</div>
<h2>Team profile (four factors &amp; tendencies)</h2>
<table><tr><th>Factor</th><th style='text-align:right'>Value</th><th>League percentile</th></tr>{rows_f}</table>
<h2>Personnel</h2>
<table><tr><th>Player</th><th>PPG</th><th>RPG</th><th>APG</th><th>3P%</th><th>Scouting note</th></tr>{pers}</table>
<h2>Shooting by zone</h2>
<table><tr><th>Zone</th><th>FG</th><th>FG%</th></tr>{zr}</table>
<div class='sub' style='margin-top:18px'>Generated by APP4.0 Analytics Hub.
Percentiles are vs the tracked-game field; tendencies from logged possessions.</div>
</body></html>"""
