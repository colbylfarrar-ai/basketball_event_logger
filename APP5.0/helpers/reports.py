"""
reports.py — printable HTML report cards (player season card + single-game recap).

Same zero-dependency, print-to-PDF approach as the scout sheet: pure HTML/CSS
strings a page hands to st.download_button. Assembles existing engines (player
stat table, badges, trends, fouls, gameflow, team boxes) — no new data.
Streamlit-free.
"""
from __future__ import annotations

import datetime
import html as _html

from database.db import query
import helpers.stats as S
import helpers.player_ratings as PR
import helpers.team_analytics as TA
import helpers.gameflow as GF
import helpers.trends as TRD
import helpers.fouls as FL
import helpers.badges as BG
import helpers.archetypes as ARC
import helpers.court_png as CPNG
import helpers.shrinkage as SH
import helpers.playtypes as PT
from helpers.scout import _BRAND_MARK   # baked HoopTracks mark (xhtml2pdf-safe)

e = _html.escape

_CSS = """
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-family:'Segoe UI',-apple-system,Arial,sans-serif;color:#16202c;margin:0;
  font-size:13px;line-height:1.45;background:#fff}
.wrap{max-width:920px;margin:0 auto;padding:0 26px 30px}
.band{background:linear-gradient(120deg,#0d1117 0%,#1b2433 60%,#243049 100%);
  color:#f0f6fc;padding:20px 26px;border-bottom:5px solid #f0a500;margin-bottom:16px}
.band .mark{font-size:10px;letter-spacing:3px;text-transform:uppercase;color:#f0a500;font-weight:800}
.band h1{margin:4px 0 2px;font-size:25px}
.band .meta{color:#aeb9c7;font-size:12.5px}
.chips{margin-top:10px}
.chip{display:inline-block;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);
  border-radius:999px;padding:4px 11px;margin:3px 6px 0 0;font-size:11.5px;color:#dbe4ee}
.chip b{color:#fff}
h2{font-size:13px;text-transform:uppercase;letter-spacing:1.4px;color:#0d1117;
  border-left:4px solid #f0a500;padding-left:9px;margin:18px 0 9px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th{text-align:left;font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;color:#5b6675;
  border-bottom:2px solid #16202c;padding:6px 8px}
td{padding:5px 8px;border-bottom:1px solid #e7ebf0}
tr:nth-child(even) td{background:#f7f9fb}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
table.kpis{width:100%;border-collapse:separate;border-spacing:5px 0;margin:6px 0 4px}
td.kpi{background:#f7f9fb;border:1px solid #e7ebf0;border-radius:9px;
  padding:9px 6px;text-align:center}
.kpi .v{font-size:20px;font-weight:800;color:#16202c;font-variant-numeric:tabular-nums}
.kpi .l{font-size:9.5px;text-transform:uppercase;letter-spacing:.5px;color:#5b6675}
.bdg{display:inline-block;font-size:10px;font-weight:700;color:#6b4e00;background:#fff3d6;
  border:1px solid #f0d692;border-radius:5px;padding:2px 7px;margin:3px 5px 0 0}
.foot{margin-top:20px;padding-top:10px;border-top:1px solid #e7ebf0;color:#8a94a2;font-size:11px}
@media print{.break{page-break-before:always}}
.court-img{display:block;margin:8px auto;border:1px solid #e7ebf0;border-radius:8px}
"""


def _today():
    try:
        d = datetime.date.today()
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    except Exception:
        return ""


def _doc(title, body):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{e(title)}</title><style>{_CSS}</style></head><body>{body}"
            f"<div class='wrap'><div class='foot'>Made with HoopTracks · app.hooptracks.com"
            f"{(' · ' + _today()) if _today() else ''}.</div></div></body></html>")


def _kpi(label, value):
    # A table cell, not a flex child — xhtml2pdf (the PDF engine) has no flexbox.
    return f"<td class='kpi'><div class='v'>{value}</div><div class='l'>{e(label)}</div></td>"


def _pctile(val, key, pool):
    """Percentile rank (0-100) of ``val`` for stat ``key`` within ``pool`` (a list
    of player rows). Mirrors helpers.cards.pctile without the Streamlit import so
    this printable module stays Streamlit-free."""
    vals = [row.get(key) for row in pool if row.get(key) is not None]
    if val is None or not vals:
        return None
    below = sum(1 for v in vals if v < val)
    eq = sum(1 for v in vals if v == val)
    return round((below + 0.5 * eq) / len(vals) * 100)


# ── per-player season report card ────────────────────────────────────────────────
def player_card_html(player_id, gender=None, table=None):
    if table is None:
        table = PR.player_stat_table(gender=gender, min_games=1)
    r = table.get(player_id)
    if not r:
        return _doc("Player card", "<div class='wrap'>Player not found.</div>")
    badges = BG.award_badges(table).get(player_id, [])
    log = TRD.player_game_log(player_id)
    highs = TRD.season_highs(log)
    ff = FL.player_foul_ft().get(player_id, {})
    # archetypes — the k-means style cluster (the chip the on-screen card shows) and
    # the transparent badge-driven role, so the printout carries the same identity.
    try:
        _arch = ARC.cluster_players(table)["players"].get(player_id, {}).get("archetype")
    except Exception:
        _arch = None
    _barch = BG.badge_archetype(badges)["archetype"]
    conf = SH.rating_confidence(r.get("GP") or 0)          # scouted-confidence read
    twr = PR.team_relative(r, list(table.values()))        # rank among teammates

    def g(k, f="{:.1f}"):
        v = r.get(k)
        return f.format(v) if v is not None else "—"

    def pg(k):
        v = r.get(k)
        return f"{v:.0f}%" if v is not None else "—"

    _bio = query("SELECT height, wingspan, weight, handedness FROM players WHERE id=?",
                 (player_id,))
    meas = S.fmt_measurables(_bio[0]) if _bio else None
    band = (
        f"<div class='band'><div class='mark'>{_BRAND_MARK} HoopTracks · Player Card</div>"
        f"<h1>#{r.get('number','')} {e(r['name'])}</h1>"
        f"<div class='meta'>{e(r['team'])} · {e(r.get('class','N/A'))} · "
        f"{r.get('GP',0)} games" + (f" · {e(meas)}" if meas else "")
        + f" · Scouted {conf['label']} (±{conf['ci']:.0f} OVR)" + "</div>"
        f"<div class='chips'>"
        f"<span class='chip'><b>{g('OVERALL','{:.0f}')}</b> OVR</span>"
        f"<span class='chip'><b>{g('OFFENSE','{:.0f}')}</b> OFF</span>"
        f"<span class='chip'><b>{g('DEFENSE','{:.0f}')}</b> DEF</span>"
        f"<span class='chip'><b>{g('PLAYMAKING','{:.0f}')}</b> PLAY</span>"
        f"<span class='chip'><b>{g('REBOUNDING','{:.0f}')}</b> REB</span>"
        + (f"<span class='chip'><b>{g('PHYSICAL','{:.0f}')}</b> PHY</span>"
           if r.get("PHYSICAL") is not None else "")
        + (f"<span class='chip'>{e(_arch)}</span>" if _arch else "")
        + f"<span class='chip'>Role · {e(_barch)}</span>"
        # the profile's verdict read: do the two archetype lenses agree?
        + (f"<span class='chip'>{'lenses agree' if _arch == _barch else 'lenses differ'}</span>"
           if _arch else "")
        + "</div></div>")

    kpis = "".join([
        _kpi("PPG", g("PPG")), _kpi("RPG", g("RPG")), _kpi("APG", g("APG")),
        _kpi("SPG", g("SPG")), _kpi("BPG", g("BPG")), _kpi("TPG", g("TPG")),
        _kpi("FPG", g("PF/G")), _kpi("FG%", g("FG%", "{:.0f}")),
        _kpi("3P%", g("3P%", "{:.0f}")), _kpi("TS%", g("TS%", "{:.0f}")),
        _kpi("USG%", g("USG%", "{:.0f}")),
    ])

    # Impact & signature strip — the invented/impact tiles the on-screen card leads
    # with, so the printout carries the same headline advanced read.
    _selfcr = r.get("SelfCr%")
    _passpct = (100 - _selfcr) if _selfcr is not None else None
    try:
        import helpers.spacing as SP
        _space = SP.league_player_spacing(gender).get(player_id, {}).get("index")
    except Exception:
        _space = None
    sig = "".join([
        _kpi("MIN/G", g("MPG")), _kpi("+/-", g("+/-", "{:+.0f}")),
        _kpi("EFF", g("EFF", "{:.0f}")), _kpi("VPS", g("VPS", "{:.2f}")),
        _kpi("2-WAY", g("2WAY", "{:.0f}")), _kpi("SMOE", g("SMOE", "{:+.2f}")),
        _kpi("SELF-CR%", g("SelfCr%", "{:.0f}")),
        _kpi("PASS%", f"{_passpct:.0f}" if _passpct is not None else "—"),
        _kpi("SPACING", f"{_space:.0f}" if _space is not None else "—"),
        # the profile's Signature defense splits (FG% allowed at the rim / arc)
        _kpi("RIM D FG%", g("RimDFG%", "{:.0f}")),
        _kpi("PERIM D FG%", g("PerimDFG%", "{:.0f}")),
    ])

    # Form — the profile's trajectory chips (last 5 games vs season, measured
    # play — never a projection). ASCII words, xhtml2pdf's fonts have no arrows.
    form_html = ""
    if len(log) >= 6:
        _tspec = [("OVERALL (GS)", lambda b: S.game_score(b), 1.5),
                  ("OFF (PTS)", lambda b: b.get("PTS", 0), 2.0),
                  ("DEF (STK)", lambda b: b.get("STL", 0) + b.get("BLK", 0), 0.8),
                  ("PLAY (AST)", lambda b: b.get("AST", 0), 0.8),
                  ("REB", lambda b: b.get("TRB", 0), 1.2)]
        _fcells = []
        for _lbl, _fn, _eps in _tspec:
            try:
                _series = [_fn(gm["box"]) for gm in log]
            except Exception:
                continue
            _d = sum(_series[-5:]) / 5 - sum(_series) / len(_series)
            _word = "UP" if _d >= _eps else ("DOWN" if _d <= -_eps else "FLAT")
            _fcells.append(_kpi(_lbl, f"{_word} {_d:+.1f}"))
        if _fcells:
            form_html = ("<h2>Form — last 5 games vs season</h2>"
                         f"<table class='kpis'><tr>{''.join(_fcells)}</tr></table>")

    # Full stat line — mirrors the on-screen "Scoring & shooting" +
    # "Rebounding · Playmaking · Defense" detail tables (the tab's "full stat line").
    def _sr(label, val):
        return f"<tr><td>{label}</td><td class='num'>{val}</td></tr>"
    statline = "".join([
        _sr("Points (PPG)", f"{r.get('PTS', 0)} ({g('PPG')}/g)"),
        _sr("FG", f"{r.get('FGM', 0)}/{r.get('FGA', 0)} ({pg('FG%')})"),
        _sr("Three", f"{r.get('3PM', 0)}/{r.get('3PA', 0)} ({pg('3P%')})"),
        _sr("Free throw", f"{r.get('FTM', 0)}/{r.get('FTA', 0)} ({pg('FT%')})"),
        _sr("eFG% / TS%", f"{pg('eFG%')} / {pg('TS%')}"),
        _sr("Scoring Eff. (ScEff)", pg("ScEff")),
        _sr("Pts / shot (PPS)", g("PPS", "{:.2f}")),
        _sr("Rebounds (RPG)", f"{r.get('REB', 0)} ({g('RPG')}/g)"),
        _sr("OREB / DREB", f"{r.get('OREB', 0)} / {r.get('DREB', 0)}"),
        _sr("Assists (APG)", f"{r.get('AST', 0)} ({g('APG')}/g)"),
        _sr("Assist / turnover", g("AST/TOV", "{:.2f}")),
        _sr("Potential assists",
            f"{r.get('PotAST', 0)}"
            + (f" ({r['FeedConv%']:.0f}% finished)"
               if r.get("FeedConv%") is not None else "")),
        _sr("Screen assists", f"{r.get('ScrAST', 0)}"),
        _sr("Steals / Blocks", f"{r.get('STL', 0)} / {r.get('BLK', 0)}"),
        _sr("Rim defense (FG% allowed)",
            f"{pg('RimDFG%')} on {r.get('RimDShots', 0)}"
            if r.get("RimDShots") else "—"),
        _sr("Perimeter defense (3P% allowed)",
            f"{pg('PerimDFG%')} on {r.get('PerimDShots', 0)}"
            if r.get("PerimDShots") else "—"),
        _sr("Turnovers (TPG)", f"{r.get('TOV', 0)} ({g('TPG')}/g)"),
        _sr("Fouls (FPG)", f"{r.get('PF', 0)} ({g('PF/G')}/g)"),
        _sr("Game Score / game", g("GS/G")),
    ])

    bdg = "".join(f"<span class='bdg'>{e(b['emoji'])} {e(b['name'])}</span>"
                  for b in badges[:8]) or "<span style='color:#8a94a2'>—</span>"

    hrows = ""
    for k, lbl in TRD.HIGH_KEYS:
        h = highs.get(k)
        if h:
            hrows += (f"<tr><td>{e(lbl)}</td><td class='num'>{h['value']}</td>"
                      f"<td>{e(h['opp'])}</td><td class='num'>{e(h['date'])}</td></tr>")

    ftline = ""
    if ff:
        _cft = (f"{ff.get('cFTM', 0)}/{ff.get('cFTA', 0)} "
                f"({ff['ClutchFT%']:.0f}%)" if ff.get("cFTA") else "—")
        _a1 = (f"{ff.get('and1_made', 0)}/{ff.get('and1', 0)}"
               if ff.get("and1") else "—")
        ftline = (f"<table class='kpis'><tr>{_kpi('Fouls drawn', ff.get('drawn',0))}"
                  f"{_kpi('Fouls', ff.get('PF',0))}"
                  f"{_kpi('FT', str(ff.get('FTM',0))+'/'+str(ff.get('FTA',0)))}"
                  f"{_kpi('FT%', ('%.0f%%'%ff['FT%']) if ff.get('FTA') else '—')}"
                  f"{_kpi('CLUTCH FT', _cft)}"
                  f"{_kpi('AND-1', _a1)}</tr></table>")

    lrows = ""
    for game in log[-15:][::-1]:
        b = game["box"]
        lrows += (f"<tr><td class='num'>{e(game['date'])}</td><td>{e(game['opp'])}</td>"
                  f"<td class='num'>{b.get('PTS',0)}</td><td class='num'>{b.get('TRB',0)}</td>"
                  f"<td class='num'>{b.get('AST',0)}</td><td class='num'>{b.get('STL',0)}</td>"
                  f"<td class='num'>{b.get('BLK',0)}</td><td class='num'>{b.get('TOV',0)}</td>"
                  f"<td class='num'>{b.get('PF',0)}</td>"
                  f"<td class='num'>{b.get('FGM',0)}/{b.get('FGA',0)}</td>"
                  f"<td class='num'>{b.get('FTM',0)}/{b.get('FTA',0)}</td></tr>")

    pool = list(table.values())
    prows = ""
    for key, lbl in (("PPG", "Points"), ("RPG", "Rebounds"), ("APG", "Assists"),
                     ("SPG", "Steals"), ("BPG", "Blocks"), ("TS%", "True shooting"),
                     ("eFG%", "Effective FG"), ("3P%", "Three-point %"),
                     ("PPS", "Points / shot"), ("USG%", "Usage"),
                     ("AST/TOV", "Assist / TO"), ("REB%", "Rebound %"),
                     ("EFF", "Efficiency"), ("FIC", "Floor impact"),
                     ("GS/G", "Game Score"), ("VPS", "Value Point System"),
                     ("OVERALL", "Overall")):
        p = _pctile(r.get(key), key, pool)
        if p is None:
            continue
        prows += (f"<tr><td>{e(lbl)}</td><td class='num'>{g(key)}</td>"
                  f"<td class='num'>{p}th</td></tr>")
    pct_html = (f"<h2>Percentile ranks</h2><table><tr><th>Stat</th>"
                f"<th class='num'>Value</th><th class='num'>Percentile</th></tr>"
                f"{prows}</table>") if prows else ""

    shots = S.located_shots(player_id=player_id)
    chart_html = ""
    if shots:
        # the accuracy line the profile prints under its fold shot map
        chart_html = (
            f"<h2>Shot chart</h2>{CPNG.shot_chart_png(shots, width=320)}"
            f"<div style='font-size:9px;color:#5b6470'>Paint FG% {pg('Paint%')}"
            f" &middot; FG% {pg('FG%')} &middot; 3P% {pg('3P%')}</div>")

    # Vs teammates — league rating ranked among this player's own roster.
    twr_rows = ""
    for k, lbl in (("OVERALL", "Overall"), ("OFFENSE", "Offense"),
                   ("DEFENSE", "Defense"), ("PLAYMAKING", "Playmaking"),
                   ("REBOUNDING", "Rebounding")):
        tr = twr.get(k)
        if tr:
            twr_rows += (f"<tr><td>{e(lbl)}</td><td class='num'>{g(k,'{:.0f}')}</td>"
                         f"<td class='num'>#{tr['rank']} of {tr['n']}</td></tr>")
    tw_html = (f"<h2>Vs teammates</h2><table><tr><th>Rating</th>"
               f"<th class='num'>Value</th><th class='num'>Team rank</th></tr>"
               f"{twr_rows}</table>") if twr_rows else ""

    # Impact — RAPM · WPA (directional; heavy league scans, guarded so an export
    # never fails on thin data or a missing engine).
    imp_html = ""
    try:
        import helpers.rapm as RP
        import helpers.wpa as WP
        import helpers.hoopwar as HW
        _gids = PT._tracked_game_ids(gender)
        _rpall = (RP.compute_rapm(game_ids=_gids,
                                  prior=RP.box_prior_from_ratings(gender=gender))
                  if _gids else {})
        _rp = _rpall.get(player_id, {})
        _wr = (HW.war_table(gender, rapm=_rpall) or {}).get(player_id, {})
        _ws = WP.season_wpa(gender, mode="scoring").get(player_id, {})
        _wq = WP.season_wpa(gender, mode="possession").get(player_id, {})

        def _sv(d, k, f="{:+.1f}"):
            v = d.get(k)
            return f.format(v) if v is not None else "—"
        if _rp or _ws or _wq:
            _cells = "".join([
                _kpi("HOOPWAR", _sv(_wr, "WAR", "{:+.2f}")),
                _kpi("ORAPM", _sv(_rp, "ORAPM")), _kpi("DRAPM", _sv(_rp, "DRAPM")),
                _kpi("RAPM", _sv(_rp, "RAPM")), _kpi("WPA", _sv(_ws, "wpa", "{:+.2f}")),
                _kpi("CLUTCH WPA", _sv(_ws, "clutch_wpa", "{:+.2f}")),
                _kpi("OWA", _sv(_wq, "off_wpa", "{:+.2f}")),
                _kpi("DWA", _sv(_wq, "def_wpa", "{:+.2f}")),
            ])
            imp_html = (f"<h2>Impact — HoopWAR &middot; RAPM &middot; WPA</h2>"
                        f"<table class='kpis'><tr>{_cells}</tr></table>")
    except Exception:
        imp_html = ""

    body = (
        f"{band}<div class='wrap'>"
        f"<h2>Season averages</h2><table class='kpis'><tr>{kpis}</tr></table>"
        f"<h2>Impact &amp; signature</h2><table class='kpis'><tr>{sig}</tr></table>"
        + form_html
        + imp_html
        + f"<h2>Full stat line</h2><table>{statline}</table>"
        + tw_html + pct_html + chart_html
        + f"<h2>Badges</h2><div>{bdg}</div>"
        + (f"<h2>Fouls &amp; free throws</h2>{ftline}" if ff else "")
        + (f"<h2>Season highs</h2><table><tr><th>Stat</th><th class='num'>High</th>"
           f"<th>vs</th><th class='num'>Date</th></tr>{hrows}</table>" if hrows else "")
        + (f"<h2>Recent games</h2><table><tr><th>Date</th><th>Opp</th>"
           f"<th class='num'>PTS</th><th class='num'>REB</th><th class='num'>AST</th>"
           f"<th class='num'>STL</th><th class='num'>BLK</th><th class='num'>TOV</th>"
           f"<th class='num'>PF</th><th class='num'>FG</th>"
           f"<th class='num'>FT</th></tr>{lrows}</table>" if lrows else "")
        + "</div>")
    return _doc(f"Player card · {r['name']}", body)


# ── single-game recap ────────────────────────────────────────────────────────────
#: Recap sections a coach can include/exclude (key, label) — mirrors the scout
#: sheet's per-section toggles. Order = print order.
RECAP_SECTIONS = [
    ("totals", "Team totals"), ("factors", "Four factors"),
    ("quarters", "Scoring by quarter"), ("scoring", "Scoring breakdown"),
    ("shots1", "Home shot chart"), ("shots2", "Away shot chart"),
    ("box1", "Home box score"), ("box2", "Away box score"),
]


def game_recap_html(game_id, hidden=None):
    _hid = set(hidden or [])

    def _show(k):
        return k not in _hid
    g = query("""SELECT g.id, g.date, g.team1_id, g.team2_id, g.home_score,
                        g.away_score, t1.name n1, t2.name n2
                 FROM games g JOIN teams t1 ON t1.id=g.team1_id
                              JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?""",
              (game_id,))
    if not g:
        return _doc("Game recap", "<div class='wrap'>Game not found.</div>")
    g = g[0]
    t1id, t2id = g["team1_id"], g["team2_id"]
    events = S.fetch_events([game_id])
    tb, ob = TA.team_and_opp_box(t1id, [game_id], events=events)
    sb = GF.scoring_buckets([game_id], events=events)
    meta = {r["id"]: r for r in
            query("SELECT id, name, number, team_id, handedness FROM players")}
    boxes = {pid: S.finalize_box(b)
             for pid, b in S.aggregate_player_boxes([game_id], events=events).items()}

    h1 = tb.get("PTS", 0)
    h2 = ob.get("PTS", 0)

    def _tcol(box, label):
        rows = (("PTS", box.get("PTS", 0)), ("FG", f"{box.get('FGM',0)}/{box.get('FGA',0)}"),
                ("3P", f"{box.get('3PM',0)}/{box.get('3PA',0)}"),
                ("FT", f"{box.get('FTM',0)}/{box.get('FTA',0)}"),
                ("REB", box.get("TRB", 0)), ("OREB", box.get("OREB", 0)),
                ("AST", box.get("AST", 0)), ("STL", box.get("STL", 0)),
                ("BLK", box.get("BLK", 0)), ("TOV", box.get("TOV", 0)),
                ("PF", box.get("PF", 0)))
        return "".join(f"<tr><td>{k}</td><td class='num'>{v}</td></tr>" for k, v in rows)

    bk1, bk2 = sb.get(t1id, {}), sb.get(t2id, {})
    bkrows = ""
    for lbl, key in (("Paint", "paint"), ("2nd chance", "second_chance"),
                     ("Off turnovers", "off_turnover"), ("Fast break", "fast_break"),
                     ("Bench", "bench")):
        bkrows += (f"<tr><td class='num'>{bk1.get(key,0)}</td><td>{e(lbl)}</td>"
                   f"<td class='num'>{bk2.get(key,0)}</td></tr>")

    def _pbox(team_id):
        rs = sorted([(pid, b) for pid, b in boxes.items()
                     if meta.get(pid, {}).get("team_id") == team_id],
                    key=lambda kb: -kb[1].get("PTS", 0))
        out = ""
        for pid, b in rs:
            m = meta.get(pid, {})
            hand = S.fmt_hand(m.get("handedness"))
            out += (f"<tr><td>#{m.get('number','')} {e(m.get('name','?'))} "
                    f"<span style='color:#8a94a2;font-size:11px'>{hand}</span></td>"
                    f"<td class='num'>{b.get('PTS',0)}</td>"
                    f"<td class='num'>{b.get('TRB',0)}</td><td class='num'>{b.get('AST',0)}</td>"
                    f"<td class='num'>{b.get('STL',0)}</td><td class='num'>{b.get('BLK',0)}</td>"
                    f"<td class='num'>{b.get('FGM',0)}/{b.get('FGA',0)}</td>"
                    f"<td class='num'>{b.get('FTM',0)}/{b.get('FTA',0)}</td></tr>")
        return out

    won1 = h1 >= h2
    band = (
        f"<div class='band'><div class='mark'>{_BRAND_MARK} HoopTracks · Game Recap</div>"
        f"<h1>{e(g['n1'])} {h1} &ndash; {h2} {e(g['n2'])}</h1>"
        f"<div class='meta'>{e(g['date'] or '')} · "
        f"{e(g['n1'] if won1 else g['n2'])} win</div></div>")

    def _phdr():
        return ("<tr><th>Player</th><th class='num'>PTS</th><th class='num'>REB</th>"
                "<th class='num'>AST</th><th class='num'>STL</th><th class='num'>BLK</th>"
                "<th class='num'>FG</th><th class='num'>FT</th></tr>")

    # ── four factors (eFG% · TOV% · ORB% · FTr, both teams) ───────────────────
    def _ff(off, dff):
        return (S.efg(off),
                S._safe(off.get("TOV", 0), off.get("FGA", 0) + off.get("TOV", 0)),
                S._safe(off.get("OREB", 0), off.get("OREB", 0) + dff.get("DREB", 0)),
                S._safe(off.get("FTA", 0), off.get("FGA", 0)))
    _f1, _f2 = _ff(tb, ob), _ff(ob, tb)

    def _ffc(v, pct=True):
        return "—" if v is None else (f"{v*100:.0f}%" if pct else f"{v:.2f}")
    ff_html = "".join(
        f"<tr><td class='num'>{_ffc(_f1[i], pct)}</td><td>{lbl}</td>"
        f"<td class='num'>{_ffc(_f2[i], pct)}</td></tr>"
        for lbl, i, pct in (("eFG%", 0, True), ("TOV%", 1, True),
                            ("ORB%", 2, True), ("FTr", 3, False)))

    # ── scoring by quarter ────────────────────────────────────────────────────
    from collections import defaultdict as _dd
    _q1, _q2 = _dd(int), _dd(int)
    for _ev in events:
        if (_ev.get("event_type") in ("shot", "free_throw")
                and _ev.get("shot_result") == "make"):
            _p = _ev["shot_type"] if _ev["event_type"] == "shot" else 1
            if _ev.get("shooter_team_id") == t1id:
                _q1[_ev.get("quarter")] += _p
            elif _ev.get("shooter_team_id") == t2id:
                _q2[_ev.get("quarter")] += _p
    _qs = sorted(q for q in (set(_q1) | set(_q2)) if q)
    _qhdr = "".join(f"<th class='num'>{'Q'+str(q) if q <= 4 else 'OT'+str(q-4)}</th>"
                    for q in _qs)

    # ── tap-located shot charts (base64 PNG, xhtml2pdf-safe) ───────────────────
    def _chart(tid):
        sh = S.located_shots(game_ids=[game_id], team_id=tid, events=events)
        return CPNG.shot_chart_png(sh, width=300) if sh else ""
    _sc1 = _chart(t1id) if _show("shots1") else ""
    _sc2 = _chart(t2id) if _show("shots2") else ""

    body = f"{band}<div class='wrap'>"
    if _show("totals"):
        body += (
            f"<h2>Team totals</h2>"
            f"<table style='width:100%;border-collapse:separate;border-spacing:12px 0'><tr>"
            f"<td style='width:50%;vertical-align:top;border:none;padding:0'>"
            f"<table><tr><th>{e(g['n1'])}</th><th></th></tr>{_tcol(tb,'')}</table></td>"
            f"<td style='width:50%;vertical-align:top;border:none;padding:0'>"
            f"<table><tr><th>{e(g['n2'])}</th><th></th></tr>{_tcol(ob,'')}</table></td>"
            f"</tr></table>")
    if _show("factors") and (tb.get("FGA") or ob.get("FGA")):
        body += (
            f"<h2>Four factors</h2><table>"
            f"<tr><th class='num'>{e(g['n1'])}</th><th></th>"
            f"<th class='num'>{e(g['n2'])}</th></tr>{ff_html}</table>")
    if _show("quarters") and _qs:
        body += (
            f"<h2>Scoring by quarter</h2><table>"
            f"<tr><th>Team</th>{_qhdr}<th class='num'>Total</th></tr>"
            f"<tr><td>{e(g['n1'])}</td>"
            + "".join(f"<td class='num'>{_q1.get(q,0)}</td>" for q in _qs)
            + f"<td class='num'>{h1}</td></tr>"
            f"<tr><td>{e(g['n2'])}</td>"
            + "".join(f"<td class='num'>{_q2.get(q,0)}</td>" for q in _qs)
            + f"<td class='num'>{h2}</td></tr></table>")
    if _show("scoring"):
        body += (
            f"<h2>Scoring breakdown</h2><table>"
            f"<tr><th class='num'>{e(g['n1'])}</th><th></th>"
            f"<th class='num'>{e(g['n2'])}</th></tr>{bkrows}</table>")
    if _sc1 or _sc2:
        body += "<h2>Shot charts</h2>"
        if _sc1:
            body += f"<div style='font-size:12px;color:#5b6675'>{e(g['n1'])}</div>{_sc1}"
        if _sc2:
            body += f"<div style='font-size:12px;color:#5b6675'>{e(g['n2'])}</div>{_sc2}"
    if _show("box1"):
        body += f"<h2>{e(g['n1'])} — box score</h2><table>{_phdr()}{_pbox(t1id)}</table>"
    if _show("box2"):
        body += (f"<h2 class='break'>{e(g['n2'])} — box score</h2>"
                 f"<table>{_phdr()}{_pbox(t2id)}</table>")
    body += "</div>"
    return _doc(f"Recap · {g['n1']} vs {g['n2']}", body)
