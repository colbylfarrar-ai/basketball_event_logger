"""
dashboard/player_card.py — the ONE player-profile card body.

Single source of truth for the rich player card rendered by BOTH the Players page
(pages/7_Players.py) and the Team Dashboard (pages/6_Team_Dashboard.py) Player Profile
tabs. They were near-identical copies that drifted; now both build a ctx and call
render_card(ctx). Edit the card HERE — never re-fork it.

ctx fields (SimpleNamespace built per page):
  P, pid, rows  - player row, its id, full eligible-player pool (ranks/percentiles)
  paid          - gates event-derived blocks (Players Free passes _PAID; Dashboard True)
  accent        - page theme accent colour
  zsplits/zguard/hsplits - per-player zone, guarded/open, hand-side split tables
  badges        - earned badge dicts for this player (unpacked to local `lab_badges`
                  so it never collides with the rating-number `badges` HTML string)
  archetype     - archetype label string (or None)
  pgb           - {pid: {gid: box}} per-game boxes (cached; game log + trends)
  located       - this player's tap (x,y) shots (or None -> zone-chart fallback)
  foulft        - this player's foul/FT detail dict (or None -> skip that block)
"""
from __future__ import annotations

from html import escape as html_escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
import helpers.badges as BG
import helpers.stats as S
import helpers.trends as TRD
import helpers.player_ratings as PR
import helpers.playtypes as PT
import helpers.shrinkage as SH
from helpers.ui import empty_state, rgb as _rgb, style_fig as _style, CARD_BG, GRID
from helpers.cards import (fmt as _fmt, pctile as _pctile, pctile_bar as _pctile_bar,
                           tier as _tier, glass as _glass, onoff_html as _onoff_html,
                           gauge_dial, scoring_donut as _donut)
from helpers.court import (shot_chart as _shot_chart, shot_map as _shot_map,
                           hot_zones as _hot_zones)

RATING_COLS = ["OVERALL", "OFFENSE", "DEFENSE", "PLAYMAKING", "REBOUNDING"]
_DEV_STATS = ("PPG", "RPG", "APG", "SPG", "BPG", "TPG", "FPG")   # cross-season trend stats
_DEV_INVERTED = ("TPG", "FPG")   # lower is better → inverse delta colouring

# Rating-bar palette for the dense Overview grid (mirrors the gauge-dial colours).
GRID_CLR = {"OVERALL": "#58a6ff", "OFFENSE": "#f0a500", "DEFENSE": "#e74c3c",
            "PLAYMAKING": "#bc8cff", "REBOUNDING": "#3fb950", "Floor spacing": "#56d4dd"}


def _rating_bar(label, value, color, ci=None, trend=None):
    """One dense rating row: label · track (+ faded confidence-interval band) ·
    value · trajectory chip.

    `ci` (0-100 half-width from shrinkage.rating_confidence) draws a lighter band
    from value−ci to value+ci behind the solid fill — the OOTP 'scouted' read of
    how firm the number is. None → no band (a fully-backed rating).

    `trend` = (delta, eps, proxy_label) — the last-5-games-vs-season change in
    the category's proxy stat (REAL measured games; deliberately NOT a video-game
    'potential'). Renders ↗ / → / ↘ with the delta; |delta| < eps reads flat.
    None → no chip (thin log)."""
    chip = ""
    if trend is not None:
        d, eps, proxy = trend
        if d >= eps:
            _a, _c = "↗", "#3fb950"
        elif d <= -eps:
            _a, _c = "↘", "#e74c3c"
        else:
            _a, _c = "→", "#6e7681"
        chip = (f"<div style='width:52px;text-align:right;font-size:10px;"
                f"color:{_c};font-weight:700' title='{proxy}: last 5 games vs "
                f"season average'>{_a} {d:+.1f}</div>")
    if value is None:
        return (f"<div style='display:flex;align-items:center;gap:8px;margin:5px 0'>"
                f"<div style='width:86px;font-size:11px;color:#8b949e'>{label}</div>"
                f"<div style='flex:1;height:8px;border-radius:4px;background:#161b22'></div>"
                f"<div style='width:28px;text-align:right;font-size:12px;color:#484f58'>—</div>"
                f"{chip}</div>")
    v = max(0.0, min(100.0, float(value)))
    band = ""
    if ci:
        lo, hi = max(0.0, v - ci), min(100.0, v + ci)
        band = (f"<div style='position:absolute;top:0;height:8px;border-radius:4px;"
                f"left:{lo}%;width:{hi-lo}%;background:{color};opacity:.28'></div>")
    return (
        f"<div style='display:flex;align-items:center;gap:8px;margin:5px 0'>"
        f"<div style='width:86px;font-size:11px;color:#8b949e'>{label}</div>"
        f"<div style='flex:1;position:relative;height:8px;border-radius:4px;background:#161b22'>"
        f"{band}"
        f"<div style='position:absolute;top:0;height:8px;border-radius:4px;width:{v}%;"
        f"background:{color}'></div></div>"
        f"<div style='width:28px;text-align:right;font-size:12px;font-weight:700;"
        f"color:#f0f6fc'>{value:.0f}</div>{chip}</div>")


# Trajectory proxies: each rating category tracked by ONE legible per-game stat
# from the real log (finalized boxes). eps = flat band so tiny wobble reads "→".
# This is the honest basketball read of OOTP's potential column — measured
# recent form, never an invented ceiling.
_TRAJ_SPEC = {
    "OVERALL":    (lambda b: S.game_score(b), 1.5, "Game Score"),
    "OFFENSE":    (lambda b: b["PTS"], 2.0, "Points"),
    "DEFENSE":    (lambda b: b["STL"] + b["BLK"], 0.8, "Stocks"),
    "PLAYMAKING": (lambda b: b["AST"], 0.8, "Assists"),
    "REBOUNDING": (lambda b: b["TRB"], 1.2, "Rebounds"),
}


def _trajectory(pid, pgb, min_games=6, last=5):
    """{category: (last-5 avg − season avg, eps, proxy label)} from the player's
    real game log. {} below `min_games` (a 5-game 'trend' on a 5-game season is
    just the season)."""
    log = TRD.player_game_log(pid, boxes=pgb)
    if len(log) < min_games:
        return {}
    out = {}
    for cat, (fn, eps, lbl) in _TRAJ_SPEC.items():
        try:
            series = [fn(r["box"]) for r in log]
        except Exception:
            continue
        season = sum(series) / len(series)
        recent = sum(series[-last:]) / last
        out[cat] = (recent - season, eps, lbl)
    return out


def _teamrow(label, tr):
    """One team-within row: a dot on the team's min→max spread + rank #k/n."""
    if not tr:
        return (f"<div style='display:flex;align-items:center;gap:8px;margin:5px 0;"
                f"font-size:11px'><div style='width:82px;color:#8b949e'>{label}</div>"
                f"<div style='flex:1;height:16px;border-radius:4px;background:#161b22'></div>"
                f"<div style='width:44px;text-align:right;color:#484f58'>—</div></div>")
    pos = tr["pos"] * 100
    return (
        f"<div style='display:flex;align-items:center;gap:8px;margin:5px 0;font-size:11px'>"
        f"<div style='width:82px;color:#8b949e'>{label}</div>"
        f"<div style='flex:1;position:relative;height:16px;border-radius:4px;background:#161b22'>"
        f"<div style='position:absolute;top:1px;height:14px;width:14px;border-radius:50%;"
        f"background:#bc8cff;border:2px solid #0d1117;left:calc({pos}% - 7px)'></div></div>"
        f"<div style='width:44px;text-align:right;font-weight:700;color:#f0f6fc'>"
        f"#{tr['rank']}/{tr['n']}</div></div>")


@st.cache_data(ttl=600, show_spinner=False)
def _class_curve(gender):
    """League class-curve for the projection (cached — it scans every player's
    season lines). Computed at most once per gender per 10 min."""
    import helpers.development as DV
    return DV.class_curve(gender)


@st.cache_data(ttl=600, show_spinner=False)
def _dev(pid, gender):
    """Cross-season development bundle for one player (cached per pid/gender)."""
    import helpers.development as DV
    return DV.player_development(pid, gender=gender, curve=_class_curve(gender))


# `game_ids`/`season` on these fetchers scope the card to a season (an archive
# view passes the season's gender tracked pool); None/'Current' keeps the current-
# season default, so the card is byte-identical for the live season.
@st.cache_data(ttl=600, show_spinner=False)
def _spacing(gender, game_ids=None):
    """League floor-spacing index per player {pid: {index, components, n}} —
    cached per gender (one league scan). {} when the pool is too thin."""
    import helpers.spacing as SP
    return SP.league_player_spacing(
        gender, game_ids=(list(game_ids) if game_ids is not None else None))


@st.cache_data(ttl=600, show_spinner=False)
def _rapm(gender, game_ids=None):
    """Two-way RAPM per player {pid: {ORAPM,DRAPM,RAPM,...}} — cached per gender.
    Uses the box-impact prior so stars on a ~15-game book don't collapse to 0.
    {} when there isn't enough possession data to solve."""
    import helpers.rapm as RP
    gids = list(game_ids) if game_ids is not None else PT._tracked_game_ids(gender)
    if not gids:
        return {}
    try:
        prior = RP.box_prior_from_ratings(gender=gender)
        return RP.compute_rapm(game_ids=gids, prior=prior)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _defended_located(pid, game_ids=None):
    """Tap-located shots this player contested or blocked — the defended-shot
    map. Restricted to events naming the player, so it only ever reads their
    own games."""
    try:
        return S.located_shots(
            defender_id=pid,
            game_ids=(list(game_ids) if game_ids is not None else None))
    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner=False)
def _war(gender, season="Current", game_ids=None):
    """HoopWAR per player {pid: {WAR, pts_added, ...}} — chains the cached RAPM
    solve through helpers/hoopwar.py. {} when RAPM or finished scores are absent."""
    import helpers.hoopwar as HW
    try:
        return HW.war_table(gender, rapm=_rapm(gender, game_ids),
                            game_ids=(list(game_ids) if game_ids is not None else None),
                            season=season)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _wpa(gender, season="Current"):
    """Season WPA per player in both modes {scoring:{pid:...}, possession:{...}}.
    scoring → wpa + clutch_wpa; possession → off_wpa (OWA) + def_wpa (DWA)."""
    import helpers.wpa as WP
    try:
        return {"scoring": WP.season_wpa(gender, mode="scoring", season=season),
                "possession": WP.season_wpa(gender, mode="possession", season=season)}
    except Exception:
        return {"scoring": {}, "possession": {}}


def render_card(ctx):
    """Render the full player-profile card (header banner -> scouting report)."""
    P, pid, rows = ctx.P, ctx.pid, ctx.rows
    paid, accent = ctx.paid, ctx.accent
    zsplits, zguard, hsplits = ctx.zsplits, ctx.zguard, ctx.hsplits
    lab_badges = ctx.badges
    archetype = ctx.archetype
    pgb = ctx.pgb
    located = ctx.located
    foulft = ctx.foulft
    # Season scope for the card's own league fetchers (spacing / RAPM / WPA / WAR /
    # defended shots): None/'Current' = live season (byte-identical); an archive
    # view passes its gender tracked pool so those sections read that season too.
    _szn = getattr(ctx, "season", "Current")
    _gp = getattr(ctx, "season_gp", None)
    _hand = (hsplits or {}).get(pid, {})
    _hand_dom = _hand.get("dominant", {}).get("all") if _hand else None
    _hand_weak = _hand.get("weak", {}).get("all") if _hand else None
    _hand_tot = (_hand_dom["FGA"] if _hand_dom else 0) + (_hand_weak["FGA"] if _hand_weak else 0)
    _dom_share = (_hand_dom["FGA"] / _hand_tot) if _hand_tot else None

    # ── Player header banner — OVERALL/rating badges are event-derived → Paid.
    #    Free users get a box-only header (name · team · class · GP).
    hue, tier = (_tier(P["OVERALL"]) if (paid and P["OVERALL"] is not None)
                 else (accent, ""))

    # measurables for the identity line (roster columns; any may be missing)
    def _ftin(v):
        return f"{int(v) // 12}'{int(v) % 12}\""
    _phys_bits = []
    if P.get("Height"):
        _phys_bits.append(_ftin(P["Height"]))
    if P.get("Wingspan"):
        _phys_bits.append(f"ws {_ftin(P['Wingspan'])}")
    if P.get("Weight"):
        _phys_bits.append(f"{P['Weight']:.0f} lb")
    if paid and P.get("PHYSICAL") is not None:
        _phys_bits.append(f"PHY {P['PHYSICAL']:.0f}")
    _phys = (" · " + " · ".join(_phys_bits)) if _phys_bits else ""
    if paid and P["OVERALL"] is not None:
        badges = "".join(
            f"<div style='background:#0d1117;border:1px solid {hue}55;border-radius:8px;"
            f"padding:6px 14px;text-align:center'>"
            f"<div style='font-size:20px;font-weight:900;color:{hue}'>"
            f"{P[k]:.0f}</div><div style='font-size:8px;color:#8b949e;"
            f"text-transform:uppercase;letter-spacing:1px'>{k[:4]}</div></div>"
            for k in RATING_COLS if P[k] is not None)
        st.markdown(
            f"<div style='background:linear-gradient(135deg,#080c14,#0d1117 55%,#111827);"
            f"border:1px solid {hue}66;border-radius:18px;padding:24px 28px;"
            f"margin-bottom:18px;position:relative;overflow:hidden'>"
            f"<div style='position:absolute;right:-6px;top:50%;"
            f"transform:translateY(-50%);font-size:150px;font-weight:900;"
            f"color:rgba(255,255,255,0.03);line-height:1'>#{P['number']}</div>"
            f"<div style='display:flex;align-items:center;gap:22px;position:relative'>"
            f"<div style='background:{hue}18;border:2px solid {hue}55;border-radius:14px;"
            f"padding:12px 16px;text-align:center;min-width:74px'>"
            f"<div style='font-size:9px;color:#8b949e;letter-spacing:1px'>NO.</div>"
            f"<div style='font-size:44px;font-weight:900;color:{hue};line-height:1'>"
            f"{P['number']}</div></div>"
            f"<div style='flex:1'>"
            f"<div style='font-size:34px;font-weight:900;color:#f0f6fc;line-height:1.05'>"
            f"{P['name']}</div>"
            f"<div style='font-size:13px;color:#8b949e;margin-top:5px'>"
            f"<span style='color:{hue};font-weight:700;letter-spacing:1px'>{tier}</span> · "
            f"{P['team']} · {P['class']} · {P['GP']} GP · rank #{P['Rank']} of {len(rows)}"
            f"{_phys}</div></div>"
            f"<div style='text-align:center'>"
            f"<div style='font-size:9px;color:{hue};letter-spacing:2px'>OVERALL</div>"
            f"<div style='font-size:60px;font-weight:900;color:{hue};line-height:1'>"
            f"{P['OVERALL']:.0f}</div></div></div>"
            f"<div style='display:flex;gap:8px;margin-top:14px;padding-top:12px;"
            f"border-top:1px solid #21262d;flex-wrap:wrap'>{badges}</div></div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div style='background:linear-gradient(135deg,#080c14,#0d1117 55%,#111827);"
            f"border:1px solid {hue}66;border-radius:18px;padding:24px 28px;"
            f"margin-bottom:18px;position:relative;overflow:hidden'>"
            f"<div style='position:absolute;right:-6px;top:50%;"
            f"transform:translateY(-50%);font-size:150px;font-weight:900;"
            f"color:rgba(255,255,255,0.03);line-height:1'>#{P['number']}</div>"
            f"<div style='display:flex;align-items:center;gap:22px;position:relative'>"
            f"<div style='background:{hue}18;border:2px solid {hue}55;border-radius:14px;"
            f"padding:12px 16px;text-align:center;min-width:74px'>"
            f"<div style='font-size:9px;color:#8b949e;letter-spacing:1px'>NO.</div>"
            f"<div style='font-size:44px;font-weight:900;color:{hue};line-height:1'>"
            f"{P['number']}</div></div>"
            f"<div style='flex:1'>"
            f"<div style='font-size:34px;font-weight:900;color:#f0f6fc;line-height:1.05'>"
            f"{P['name']}</div>"
            f"<div style='font-size:13px;color:#8b949e;margin-top:5px'>"
            f"{P['team']} · {P['class']} · {P['GP']} GP{_phys}</div></div></div></div>",
            unsafe_allow_html=True)

    # ── header extras: per-game line (box, Free) · archetype + badges (Paid) ───
    _tc = {"Gold": "#f0c000", "Silver": "#c0c8d0", "Bronze": "#cd7f32"}
    _arch = (archetype
             if paid else None)
    _pg_chips = "".join(
        f"<span class='stat-chip'>{lbl} <b>{P[k]:.1f}</b></span>"
        for k, lbl in [("PPG", "PPG"), ("RPG", "RPG"), ("APG", "APG"),
                       ("SPG", "SPG"), ("BPG", "BPG"), ("TPG", "TPG"),
                       ("PF/G", "FPG")]
        if P.get(k) is not None)
    _arch_chip = (f"<span class='stat-chip' style='border-color:{accent}'>"
                  f"Cluster <b>{_arch}</b></span>" if _arch else "")
    st.markdown(f"<div class='form-strip' style='margin:-8px 0 10px'>"
                f"{_arch_chip}{_pg_chips}</div>", unsafe_allow_html=True)
    if paid:
        _pbadges = lab_badges
        if _pbadges:
            _bchips = "".join(
                f"<span style='display:inline-block;background:#0d1117;"
                f"border:1px solid {_tc.get(b['tier'], '#888')};border-radius:20px;"
                f"padding:4px 12px;margin:0 6px 7px 0;font-size:12px'>{b['emoji']} "
                f"<b>{b['name']}</b> <span style='color:"
                f"{_tc.get(b['tier'], '#888')};font-weight:700'>{b['tier']}</span></span>"
                for b in _pbadges[:8])
            st.markdown(
                f"<div style='margin:0 0 12px'><span style='font-size:11px;"
                f"color:#8b949e;text-transform:uppercase;letter-spacing:1px;"
                f"margin-right:8px'>Badges</span>{_bchips}</div>",
                unsafe_allow_html=True)
        else:
            st.caption("No badges earned yet — needs more volume or higher "
                       "percentile ranks.")

    # ══ Dense OVERVIEW grid — OOTP-style one-stop summary (event-derived → Paid) ══
    #    The above-the-fold read: ratings (with a scouted confidence band), the
    #    signature tiles, where the player ranks AMONG TEAMMATES, and the full
    #    league-percentile rail. Detail blocks below drill each of these.
    if paid:
        _conf = SH.rating_confidence(P.get("GP") or 0)
        _twrel = PR.team_relative(P, rows)
        _space = _spacing(getattr(ctx, "gender", None), _gp).get(pid, {}).get("index")
        _cclr = {"high": "#3fb950", "medium": "#f0a500",
                 "low": "#e74c3c", "very_low": "#e74c3c"}[_conf["tier"]]
        # verdict strip (OOTP summary box): season value in wins + the two
        # archetype lenses side by side — agreement is the scouting note
        _gnd = getattr(ctx, "gender", None)
        _gwar = _war(_gnd, _szn, _gp).get(pid, {}).get("WAR")
        _gwpa = ((_wpa(_gnd, _szn).get("scoring") or {}).get(pid, {}) or {}).get("wpa")
        _barch = BG.badge_archetype(lab_badges or [])["archetype"] \
            if lab_badges is not None else None
        _verdict_bits = []
        if _gwar is not None:
            _verdict_bits.append(f"HoopWAR <b>{_gwar:+.2f}</b>")
        if _gwpa is not None:
            _verdict_bits.append(f"WPA <b>{_gwpa:+.2f}</b>")
        if _barch and _arch:
            _agree = "✓ agree" if _barch == _arch else "↔ differ"
            _verdict_bits.append(
                f"Badges <b>{_barch}</b> / Style <b>{_arch}</b> "
                f"<span style='color:{'#3fb950' if _barch == _arch else '#f0a500'}'>"
                f"{_agree}</span>")
        _verdict = ("<span style='font-size:11px;color:#8b949e;font-weight:400;"
                    "float:right'>" + " · ".join(_verdict_bits) + "</span>"
                    if _verdict_bits else "")
        st.markdown(
            "<div class='pl-hdr' style='margin-top:0'>Overview · scouted "
            f"<span style='color:{_cclr};font-weight:800'>{_conf['label']}</span> "
            f"<span style='font-size:11px;color:#8b949e;font-weight:400'>"
            f"({_conf['games']} game{'s' if _conf['games'] != 1 else ''} · "
            f"OVERALL &plusmn;{_conf['ci']:.0f})</span>{_verdict}</div>",
            unsafe_allow_html=True)

        def _kv(k, v):
            return (f"<div style='display:flex;justify-content:space-between;"
                    f"font-size:12px;padding:2px 0'><span style='color:#8b949e'>{k}"
                    f"</span><span style='color:#f0f6fc;font-weight:600'>{v}</span></div>")

        def _g(key, d=0.0):
            return P.get(key) if P.get(key) is not None else d

        # 4th column = the shot maps IN the fold (phase E) — basketball's edge
        # over the OOTP page: the spatial read sits beside the ratings.
        g1, g2, g3, g4 = st.columns([0.9, 1.15, 0.9, 1.05])

        # ── col 1: per-game line + career highs ──────────────────────────────
        with g1:
            pg = (
                _kv("PTS", f"{_g('PPG'):.1f}")
                + _kv("REB · AST", f"{_g('RPG'):.1f} · {_g('APG'):.1f}")
                + _kv("STL · BLK", f"{_g('SPG'):.1f} · {_g('BPG'):.1f}")
                + _kv("TOV · AST:TO",
                      f"{_g('TPG'):.1f} · {_fmt(P.get('AST/TOV'), 'f2')}")
                + _kv("3P% · TS%", f"{_fmt(P.get('3P%'),'pct')} · {_fmt(P.get('TS%'),'pct')}"))
            st.markdown("<div class='pl-hdr' style='margin-top:0'>Per game</div>"
                        + pg, unsafe_allow_html=True)
            ch = (
                _kv("PTS", P.get("bestPTS", "—")) + _kv("REB", P.get("bestREB", "—"))
                + _kv("AST", P.get("bestAST", "—")) + _kv("Double-dbl", P.get("DD", 0))
                + _kv("Triple-dbl", P.get("TD", 0))
                + _kv("Scoring σ", _fmt(P.get("PTSsd"), "f1")))
            st.markdown("<div class='pl-hdr'>Career highs</div>" + ch,
                        unsafe_allow_html=True)

        # ── col 2: rating bars (+CI band, +trajectory chips) + signature tiles ──
        with g2:
            _traj = _trajectory(pid, pgb)
            bars = "".join(
                _rating_bar(k.title(), P.get(k), GRID_CLR.get(k, accent),
                            ci=_conf["ci"] if k == "OVERALL" else None,
                            trend=_traj.get(k))
                for k in RATING_COLS)
            bars += _rating_bar("Floor spacing", _space, GRID_CLR["Floor spacing"])
            _thdr = ("Ratings <span style='font-size:10px;color:#8b949e;"
                     "font-weight:400'>· ↗↘ = last 5 games vs season (real "
                     "form, not a projection)</span>") if _traj else "Ratings"
            st.markdown(f"<div class='pl-hdr' style='margin-top:0'>{_thdr}</div>"
                        + bars, unsafe_allow_html=True)
            _selfcr = P.get("SelfCr%")
            _passpct = (100 - _selfcr) if _selfcr is not None else None
            # Paint FG% reads off the shot chart, AST:TO lives in Per game —
            # their pills became the DEFENSE splits (FG% allowed rim / arc).
            _sig = [("Self-cr %", _fmt(_selfcr, "pct")),
                    ("Pass %", _fmt(_passpct, "pct")),
                    ("Usage", _fmt(P.get("USG%"), "pct")),
                    ("VPS", _fmt(P.get("VPS"), "f2")),
                    ("Rim D FG%", _fmt(P.get("RimDFG%"), "pct")),
                    ("Perim D FG%", _fmt(P.get("PerimDFG%"), "pct"))]
            # one thin pill strip (phase E) — the tiles were a 2-row grid that
            # pushed the fold down; same six numbers, a third of the height
            pills = "".join(
                f"<span style='background:#0d1117;border:1px solid #21262d;"
                f"border-radius:14px;padding:3px 10px;font-size:11px;"
                f"color:#8b949e;white-space:nowrap'>{l} "
                f"<b style='color:#f0f6fc;font-size:12px'>{v}</b></span>"
                for l, v in _sig)
            st.markdown(
                "<div class='pl-hdr'>Signature</div>"
                "<div style='display:flex;flex-wrap:wrap;gap:6px'>"
                + pills + "</div>", unsafe_allow_html=True)

        # ── col 3: team-within (rank among teammates) + play-type breakdown ──
        with g3:
            trows = "".join(_teamrow(k.title(), _twrel.get(k)) for k in RATING_COLS)
            st.markdown(
                "<div class='pl-hdr' style='margin-top:0'>Vs teammates</div>" + trows
                + "<div style='font-size:11px;color:#8b949e;margin-top:4px'>Dot = "
                "position on the team's min&rarr;max span. League rating stays the "
                "number up top.</div>", unsafe_allow_html=True)
            # Play-type PPP/FG% fills the space under the (short) teammate panel —
            # the one-tap set-call read, mirroring the scout sheet's play types.
            _pt_named = getattr(ctx, "named_sets", None)
            if _pt_named:
                _ptlbl = dict(PT.NAMED_PLAY_TYPES)
                # share % is out of the player's TOTAL tagged possessions (all sets,
                # not just the shown top 6) so the shares read as a true diet.
                _pt_tot = sum((c.get("poss") or 0) for c in _pt_named.values())
                _pt_ranked = sorted(
                    ((k, c) for k, c in _pt_named.items() if (c.get("poss") or 0) >= 5),
                    key=lambda kv: kv[1]["poss"], reverse=True)[:6]
                if _pt_ranked:
                    def _pt_row(k, c):
                        _sh = (c["poss"] / _pt_tot * 100) if _pt_tot else 0
                        return (
                            f"<div style='display:flex;justify-content:space-between;"
                            f"font-size:11px;padding:2px 0'><span style='color:#8b949e'>"
                            f"{_ptlbl.get(k, k.title())}</span><span style='color:#f0f6fc;"
                            f"font-weight:600'>{c['poss']} &middot; {_sh:.0f}% &middot; "
                            f"{c['PPP']:.2f} &middot; {c['FG%']*100:.0f}%</span></div>")
                    st.markdown(
                        "<div class='pl-hdr'>Play types &middot; poss &middot; share "
                        "&middot; PPP &middot; FG%</div>"
                        + "".join(_pt_row(k, c) for k, c in _pt_ranked),
                        unsafe_allow_html=True)

        # ── col 4: the shot map, IN the fold (phase E; defended map lives down
        #    in Shot detail — a scouting read, not an at-a-glance one) ─────────
        with g4:
            if located:
                sfig, _sn = _shot_map(located, "")
                sfig.update_layout(height=250,
                                   margin=dict(l=0, r=0, t=6, b=0),
                                   showlegend=False)
                st.markdown(
                    f"<div class='pl-hdr' style='margin-top:0'>Shot map · "
                    f"{len(located)} located</div>", unsafe_allow_html=True)
                st.plotly_chart(sfig, width="stretch", key="pcard_court_fold")
                _ls = S.shot_location_summary(located)
                if _ls:
                    st.markdown(
                        f"<div style='font-size:10px;color:#8b949e;margin-top:-6px'>"
                        f"avg {_ls['avg_dist']:.1f} ft · rim {_ls['rim_n']} · "
                        f"mid {_ls['mid_n']} · three {_ls['three_n']} — hover a "
                        f"dot for the shot</div>", unsafe_allow_html=True)
                # the accuracy line the map itself can't show
                st.markdown(
                    f"<div style='font-size:11px;color:#c9d1d9;margin-top:2px'>"
                    f"Paint FG% <b>{_fmt(P.get('Paint%'), 'pct')}</b> · FG% "
                    f"<b>{_fmt(P.get('FG%'), 'pct')}</b> · 3P% "
                    f"<b>{_fmt(P.get('3P%'), 'pct')}</b></div>",
                    unsafe_allow_html=True)
            else:
                st.markdown("<div class='pl-hdr' style='margin-top:0'>Shot map"
                            "</div><div style='font-size:11px;color:#8b949e'>"
                            "Tap-located shots build the court read — the zone "
                            "chart below covers older games.</div>"
                            f"<div style='font-size:11px;color:#c9d1d9;"
                            f"margin-top:6px'>Paint FG% "
                            f"<b>{_fmt(P.get('Paint%'), 'pct')}</b> · FG% "
                            f"<b>{_fmt(P.get('FG%'), 'pct')}</b> · 3P% "
                            f"<b>{_fmt(P.get('3P%'), 'pct')}</b></div>",
                            unsafe_allow_html=True)

        # ── full league-percentile rail (all 21, three columns) ──────────────
        st.markdown("<div class='pl-hdr'>League percentiles</div>",
                    unsafe_allow_html=True)
        _PPG = [
            ("PPG", "Points", "f1", False), ("RPG", "Rebounds", "f1", False),
            ("APG", "Assists", "f1", False), ("SPG", "Steals", "f1", False),
            ("BPG", "Blocks", "f1", False), ("STOCKS/G", "Stocks", "f1", False),
            ("TS%", "True shooting", "pct", False), ("eFG%", "Effective FG", "pct", False),
            ("3P%", "Three-point %", "pct", False), ("PPS", "Points / shot", "f2", False),
            ("USG%", "Usage", "pct", False), ("TOV%", "Ball security", "pct", True),
            ("AST/TOV", "Assist / TO", "f2", False), ("REB%", "Rebound %", "pct", False),
            ("Guarded%", "Contest rate", "pct", False), ("DSHOT%", "Defended FG%", "pct", True),
            ("EFF", "Efficiency", "f1", False), ("FIC", "Floor impact", "f1", False),
            ("+/-", "Plus/minus", "int", False), ("GS/G", "Game Score", "f1", False),
            ("VPS", "Value Point System", "f2", False),
        ]
        _third = (len(_PPG) + 2) // 3
        _gpc = st.columns(3)
        for _ci, _chunk in enumerate((_PPG[:_third], _PPG[_third:2*_third],
                                      _PPG[2*_third:])):
            _html = ""
            for _key, _lbl, _fm, _lb in _chunk:
                _p = _pctile(P.get(_key), _key, rows, lower_better=_lb)
                _html += _pctile_bar(_lbl, _fmt(P.get(_key), _fm), _p)
            _gpc[_ci].markdown(_html, unsafe_allow_html=True)

    # ── impact tiles + "why this OVERALL" (ratings live as bars in the grid) ──
    if paid:
        im = st.columns(7)
        im[0].metric("MIN/G", f"{P['MPG']:.1f}" if P["MPG"] else "—")
        im[1].metric("USG%", f"{P['USG%']:.1f}%" if P["USG%"] is not None else "—")
        im[2].metric("+/-", f"{P['+/-']:+d}")
        im[3].metric("EFF", P["EFF"] if P["EFF"] is not None else "—")
        im[4].metric("FIC", P["FIC"] if P["FIC"] is not None else "—")
        im[5].metric("PRF", P["PRF"])
        im[6].metric("VPS", f"{P['VPS']:.2f}" if P.get("VPS") is not None else "—",
                     help="Hudl Value Point System — value ÷ mistakes.")
        _why = PR.overall_blurb(P.get("OFFENSE"), P.get("DEFENSE"),
                                P.get("PLAYMAKING"), P.get("REBOUNDING"))
        if _why:
            st.markdown(f"<div style='color:{accent};font-weight:600;margin:2px 0 4px'>"
                        f"Why this OVERALL: {html_escape(_why)}</div>",
                        unsafe_allow_html=True)

    # ── Impact — RAPM · WPA (directional on a short book) → Paid ──────────────
    if paid:
        _g = getattr(ctx, "gender", None)
        _rp = _rapm(_g, _gp).get(pid, {})
        _wpm = _wpa(_g, _szn)
        _ws = (_wpm.get("scoring") or {}).get(pid, {})
        _wq = (_wpm.get("possession") or {}).get(pid, {})

        def _sv(d, k, fmt="{:+.1f}"):
            v = d.get(k)
            return fmt.format(v) if v is not None else "—"

        _wr = _war(_g, _szn, _gp).get(pid, {})
        _imp = [
            ("HoopWAR", _sv(_wr, "WAR", "{:+.2f}"), "wins vs replacement"),
            ("ORAPM", _sv(_rp, "ORAPM"), "off pts/100"),
            ("DRAPM", _sv(_rp, "DRAPM"), "def pts/100"),
            ("RAPM", _sv(_rp, "RAPM"), "net pts/100"),
            ("WPA", _sv(_ws, "wpa", "{:+.2f}"), "wins added"),
            ("Clutch WPA", _sv(_ws, "clutch_wpa", "{:+.2f}"), "high-leverage"),
            ("Off WPA", _sv(_wq, "off_wpa", "{:+.2f}"), "offense value"),
            ("Def WPA", _sv(_wq, "def_wpa", "{:+.2f}"), "defense value"),
        ]
        if any(v != "—" for _, v, _ in _imp):
            st.markdown("<div class='pl-hdr'>Impact — HoopWAR &middot; RAPM "
                        "&middot; WPA</div>",
                        unsafe_allow_html=True)
            _itiles = "".join(
                f"<div style='background:#0d1117;border:1px solid #21262d;"
                f"border-radius:8px;padding:6px 9px'>"
                f"<div style='font-size:10px;color:#8b949e'>{l}</div>"
                f"<div style='font-size:16px;font-weight:700;color:#f0f6fc'>{v}</div>"
                f"<div style='font-size:9px;color:#6e7681'>{s}</div></div>"
                for l, v, s in _imp)
            st.markdown(
                "<div style='display:grid;grid-template-columns:repeat(8,1fr);"
                "gap:6px'>" + _itiles + "</div>", unsafe_allow_html=True)
            st.caption("HoopWAR = RAPM impact paid out over floor time, vs a "
                       "replacement-level player, converted to wins (≈14 pts/win "
                       "at HS scoring). RAPM shrinks toward a box-score prior; WPA "
                       "credits the shots (and stops) that swung win probability. "
                       "Directional on a short book — read the sign and rough size, "
                       "not the decimals.")

    # ── impact & rating splits (rebuilt engine: possession impact + defense /
    #    rebounding sub-ratings + passer depth) → Paid ─────────────────────────
    import helpers.advanced_ratings as ADV
    ADV.player_panel(P, paid)

    # ── signature / invented metrics (glass tiles) ────────────────────────────
    #    VERSATILITY is box (kept for Free); the rest are event-derived → Paid.
    st.markdown("<div class='pl-hdr'>Signature metrics</div>",
                unsafe_allow_html=True)
    tile_specs = [
        ("VERSATILITY", _fmt(P["VERSATILITY"], "f1"), "even box impact", accent),
    ]
    if paid:
        tile_specs += [
            ("2-WAY", _fmt(P["2WAY"], "f1"), "offense + defense", "#56d4dd"),
            ("SMOE", _fmt(P["SMOE"], "spp"), "shot-making vs exp.", "#00e5ff"),
            ("Q4 PPG", _fmt(P["Q4PPG"], "f1"),
             f"{_fmt(P['Q4%'], 'pct')} of points", "#ff7b72"),
            ("SELF-CR%", _fmt(P["SelfCr%"], "pct"), "shot independence", "#d2a8ff"),
            ("STOCKS/32", _fmt(P["STOCKS/32"], "f1"), "defensive disruption", "#3fb950"),
            ("DOM-SIDE%", f"{_dom_share*100:.0f}%" if _dom_share is not None else "—",
             "strong-hand shot share", "#f0a500"),
        ]
    tiles = st.columns(len(tile_specs))
    for col, (lbl, val, sub, clr) in zip(tiles, tile_specs):
        col.markdown(_glass(lbl, val, sub, clr), unsafe_allow_html=True)

    # ── dominant vs weak hand side (event-derived → Paid) ─────────────────────
    if paid and _hand_dom and _hand_weak and (_hand_dom["FGA"] or _hand_weak["FGA"]):
        st.markdown("<div class='pl-hdr'>Dominant vs weak hand side</div>",
                    unsafe_allow_html=True)
        dom, wk = _hand_dom, _hand_weak
        hm = st.columns(4)
        hm[0].metric("Dominant FG%", f"{dom['pct']*100:.0f}%" if dom["FGA"] else "—",
                     help=f"{dom['FGM']}/{dom['FGA']} on the strong-hand half")
        hm[1].metric("Weak FG%", f"{wk['pct']*100:.0f}%" if wk["FGA"] else "—",
                     help=f"{wk['FGM']}/{wk['FGA']} on the off-hand half")
        hm[2].metric("Dominant share",
                     f"{_dom_share*100:.0f}%" if _dom_share is not None else "—",
                     help=f"{dom['FGA']} dominant / {wk['FGA']} weak attempts")
        hm[3].metric("FG% edge",
                     f"{(dom['pct']-wk['pct'])*100:+.0f}pp" if (dom["FGA"] and wk["FGA"]) else "—",
                     help="Dominant minus weak FG% — how much better on the strong side")

        def _po(c):
            return f"{c['pct']*100:.0f}% ({c['FGM']}/{c['FGA']})" if c["FGA"] else "—"
        dg, do = _hand["dominant"]["guarded"], _hand["dominant"]["open"]
        wg, wo = _hand["weak"]["guarded"], _hand["weak"]["open"]
        st.caption(
            f"Dominant — guarded {_po(dg)} · open {_po(do)}   ·   "
            f"Weak — guarded {_po(wg)} · open {_po(wo)}.  "
            "Right-handers' right half = dominant (lefties mirrored); "
            "dead-center shots ignored.")

    # ── shot detail (event-derived → Paid). The located shot map + defended map
    #    moved INTO the overview grid's 4th column (phase E); this section keeps
    #    the reads the fold can't carry — shot-length buckets, hot zones, and
    #    the zone-chart fallback for legacy zone-only games.
    if paid:
        st.markdown("<div class='pl-hdr'>Shot detail</div>", unsafe_allow_html=True)
        sc_l, sc_r = st.columns([3, 2])
        with sc_l:
            if located:
                _ls = S.shot_location_summary(located)
                if _ls:
                    def _seg(lbl, n, fg):
                        return f"{lbl} {n}" + (f" ({fg*100:.0f}%)" if fg is not None
                                               else "")
                    st.caption(
                        f"Avg distance **{_ls['avg_dist']:.1f} ft** · "
                        + _seg("Rim", _ls["rim_n"], _ls["rim_fg"]) + " · "
                        + _seg("Mid", _ls["mid_n"], _ls["mid_fg"]) + " · "
                        + _seg("Three", _ls["three_n"], _ls["three_fg"])
                        + " — the shot map lives up in the Overview grid.")
                _dbl = S.distance_buckets(located)
                if _dbl:
                    st.caption("By length — " + S.distance_buckets_caption(_dbl))
            else:
                fig, ok = _shot_chart(zsplits.get(pid, {}),
                                      f"{P['name']} — FG% by zone")
                if ok:
                    st.plotly_chart(fig, width="stretch", key="pcard_court")
                    st.caption("Zone chart (older games) — ≥45% · 30–44% · <30% · "
                               "bubble size = attempts. Tap-captured shots show "
                               "as a precise shot map in the Overview grid.")
                else:
                    empty_state("No shot locations yet",
                                "Shots logged with a court tap (phone or Game "
                                "Tracker) build the shot map; zone-only shots "
                                "feed the zone chart.")
        with sc_r:
            st.markdown("**Hot zones**")
            pz = zsplits.get(pid, {})
            if pz:
                _hot_zones(pz)
            else:
                st.caption("No zone data.")
            # defended-shot map — the scouting read, deliberately BELOW the
            # fold (founder call): where opponents shot when this player was
            # the contester/blocker, with the guarded/open split.
            _dshots = _defended_located(pid, _gp)
            if _dshots:
                dfig, _dn = _shot_map(
                    _dshots, f"Shots defended · {len(_dshots)} located")
                st.plotly_chart(dfig, width="stretch", key="pcard_defcourt")
                _gd4 = zguard.get(pid, {})
                _gg = (_gd4 or {}).get("guarded", {})
                _go = (_gd4 or {}).get("open", {})
                if _gg.get("FGA") and _go.get("FGA"):
                    st.caption(
                        f"Guarded FG% {_gg['pct']*100:.0f}% "
                        f"({_gg['FGM']}/{_gg['FGA']}) · open "
                        f"{_go['pct']*100:.0f}% ({_go['FGM']}/{_go['FGA']}). "
                        "Rim vs arc feeds the DEFENSE rating.")

    left, right = st.columns([2, 3])
    with left:
        # ratings radar is event-derived → Paid; points-by-source is box (Free)
        if paid:
            ar, ag, ab = _rgb(accent)
            vals = [P[c] or 0 for c in RATING_COLS]
            rad = go.Figure()
            rad.add_trace(go.Scatterpolar(
                r=[50] * (len(RATING_COLS) + 1),
                theta=RATING_COLS + [RATING_COLS[0]],
                line=dict(color="#8b949e", width=1, dash="dot"),
                name="Pool avg", hoverinfo="skip"))
            rad.add_trace(go.Scatterpolar(
                r=vals + [vals[0]], theta=RATING_COLS + [RATING_COLS[0]],
                fill="toself", name=P["name"], line=dict(color=accent, width=2),
                fillcolor=f"rgba({ar},{ag},{ab},0.25)"))
            rad.update_layout(
                template="plotly_dark", height=360, paper_bgcolor="rgba(0,0,0,0)",
                polar=dict(bgcolor=CARD_BG,
                           radialaxis=dict(range=[0, 100], gridcolor=GRID,
                                           tickfont=dict(size=9)),
                           angularaxis=dict(gridcolor=GRID)),
                margin=dict(l=50, r=50, t=40, b=30),
                legend=dict(orientation="h", y=1.12, x=0, bgcolor="rgba(0,0,0,0)"))
            st.plotly_chart(rad, width="stretch", key="pcard_radar")

        # points by source
        pts2, pts3, ptsf = P["2PM"] * 2, P["3PM"] * 3, P["FTM"]
        if pts2 + pts3 + ptsf > 0:
            dn = _donut(pts2, pts3, ptsf, colors=(accent, "#58a6ff", "#8b949e"),
                        height=260, margin_top=30, ft_label="FT",
                        title="Points by source")
            st.plotly_chart(dn, width="stretch", key="pcard_src")

    with right:
        def _row(stat, key, fmt):
            return {"Stat": stat, "Value": _fmt(P.get(key), fmt)}

        def _ci(lo_key, hi_key):
            """' · 95% CI 35-49%' band string, or '' when the rate has no attempts."""
            lo, hi = P.get(lo_key), P.get(hi_key)
            return (f"  ·  95% CI {lo:.0f}-{hi:.0f}%"
                    if lo is not None and hi is not None else "")

        st.markdown("**Scoring & shooting**")
        # box rows always; event-derived rows (Paint/ShotRating/xPPS/xFG%/SMOE)
        # only for Paid.
        _shoot_rows = [
            _row("Points (PPG)", "PTS", "int") | {"Value":
                f"{P['PTS']} ({P['PPG']:.1f}/g)"},
            _row("FG", "FG%", "pct") | {"Value":
                f"{P['FGM']}/{P['FGA']} ({_fmt(P['FG%'],'pct')}){_ci('FG%lo','FG%hi')}"},
            _row("Three", "3P%", "pct") | {"Value":
                f"{P['3PM']}/{P['3PA']} ({_fmt(P['3P%'],'pct')}){_ci('3P%lo','3P%hi')}"},
            _row("Free throw", "FT%", "pct") | {"Value":
                f"{P['FTM']}/{P['FTA']} ({_fmt(P['FT%'],'pct')}){_ci('FT%lo','FT%hi')}"},
            _row("eFG% / TS%", "TS%", "pct") | {"Value":
                f"{_fmt(P['eFG%'],'pct')} / {_fmt(P['TS%'],'pct')}"},
            _row("Scoring Eff. (ScEff)", "ScEff", "pct"),
            _row("Pts/shot (PPS)", "PPS", "f2"),
            _row("Free throw rate", "FTR", "f2"),
        ]
        if paid:
            _shoot_rows += [
                _row("Paint FG% (pts)", "Paint%", "pct") | {"Value":
                    f"{_fmt(P['Paint%'],'pct')}  ({P['PaintPTS']} pts)"},
                _row("Shot difficulty", "ShotRating", "f1"),
                _row("Expected pts/shot", "xPPS", "f2"),
                _row("Expected FG% (SMOE)", "xFG%", "pct") | {"Value":
                    f"{_fmt(P['xFG%'],'pct')}  ({_fmt(P['SMOE'],'spp')})"},
            ]
        st.dataframe(pd.DataFrame(_shoot_rows), hide_index=True, width="stretch")
        _conf = P.get("Confidence", "—")
        st.caption(
            f"Sample confidence: **{_conf}** ({P['GP']} game"
            f"{'s' if P['GP'] != 1 else ''}). Shooting lines carry a 95% Wilson "
            "confidence interval — the range a sample this size actually supports.")

        st.markdown("**Rebounding · Playmaking · Defense**")
        # box rows always; on-court rate stats (REB%/SC/Guarded%/DSHOT%) → Paid.
        _rpd_rows = [
            _row("Rebounds (RPG)", "REB", "int") | {"Value":
                f"{P['REB']} ({P['RPG']:.1f}/g)"},
            _row("OREB / DREB", "OREB", "int") | {"Value":
                f"{P['OREB']} / {P['DREB']}"},
            _row("Assists (APG)", "AST", "int") | {"Value":
                f"{P['AST']} ({P['APG']:.1f}/g)"},
            _row("Assist/turnover", "AST/TOV", "f2"),
            _row("Steals / Blocks", "STL", "int") | {"Value":
                f"{P['STL']} / {P['BLK']}"},
            _row("Turnovers (TPG)", "TOV", "int") | {"Value":
                f"{P['TOV']} ({P['TPG']:.1f}/g · {_fmt(P['TOV%'],'pct')})"},
            _row("Fouls (FPG)", "PF", "int") | {"Value":
                f"{P['PF']} ({P['PF/G']:.1f}/g)"},
            _row("Game Score / game", "GS/G", "f1"),
            _row("Value Point System (VPS)", "VPS", "f2"),
        ]
        if paid:
            _rpd_rows[2:2] = [_row("REB% (on court)", "REB%", "pct")]
            _rpd_rows += [
                _row("Shots created", "SC", "int"),
                # feeds = every pass into a shot (make or miss); conv% = the
                # share teammates finished (the assists that could have been)
                _row("Potential assists", "PotAST", "int") | {"Value":
                    f"{P['PotAST']} ({P['PotAST/G']:.1f}/g"
                    + (f" · {_fmt(P['FeedConv%'], 'pct')} finished)"
                       if P.get("FeedConv%") is not None else ")")},
                _row("Screen assists", "ScrAST", "int") | {"Value":
                    f"{P['ScrAST']} ({P['ScrAST/G']:.1f}/g)"},
                _row("Guarded% (on court)", "Guarded%", "pct"),
                _row("Defended FG% allowed", "DSHOT%", "pct"),
            ]
            # rim / perimeter defended splits (only when the player has faced
            # shots in the bucket); ± = FG points saved vs a league-average
            # contest — the values that feed the DEFENSE rating
            if P.get("RimDShots"):
                _rpd_rows.append(
                    _row("Rim defense (FG% allowed)", "RimDFG%", "pct") | {
                        "Value": f"{_fmt(P['RimDFG%'], 'pct')} on "
                                 f"{P['RimDShots']} shots"
                                 + (f" ({P['RimProt']:+.1f} vs lg)"
                                    if P.get("RimProt") is not None else "")})
            if P.get("PerimDShots"):
                _rpd_rows.append(
                    _row("Perimeter defense (3P% allowed)", "PerimDFG%", "pct") | {
                        "Value": f"{_fmt(P['PerimDFG%'], 'pct')} on "
                                 f"{P['PerimDShots']} threes"
                                 + (f" ({P['PerimD']:+.1f} vs lg)"
                                    if P.get("PerimD") is not None else "")})
        st.dataframe(pd.DataFrame(_rpd_rows), hide_index=True, width="stretch")

    # ── Shot diet · shot creation · quarter scoring (event-derived → Paid) ────
    if paid:
        st.markdown("<div class='pl-hdr'>Shot diet & impact mix</div>",
                    unsafe_allow_html=True)
        # season-scope like every other fetcher — the bare default is
        # Current-season only, which reads ZERO for an archive/fallback pid
        _gp_list = list(_gp) if _gp is not None else None
        pbox = S.player_box(pid, game_ids=_gp_list)
        d1, d2, d3 = st.columns(3)
        with d1:
            st.markdown("**Shot diet** — how their shots are created")
            diet = S.shot_breakdown_pct(pbox)
            dl = {"self": "Self", "pass": "Off pass", "sc": "Off screen",
                  "both": "Pass+screen"}
            dv = [(dl[k], diet[k] * 100) for k in ("self", "pass", "sc", "both")]
            df_ = go.Figure(go.Bar(
                x=[v for _, v in dv], y=[l for l, _ in dv], orientation="h",
                marker_color="#58a6ff", marker_line_width=0,
                text=[f"{v:.0f}%" for _, v in dv], textposition="auto"))
            df_.update_xaxes(visible=False)
            _style(df_, 240)
            df_.update_layout(margin=dict(l=4, r=14, t=10, b=6))
            st.plotly_chart(df_, width="stretch", key="pcard_diet")
        with d2:
            st.markdown("**Shots created** — how SC is earned")
            comp = S.sc_composition(pbox)
            if pbox["SC"] > 0:
                cd = go.Figure(go.Pie(
                    labels=["Shooting", "Passing", "Screening"],
                    values=[comp["shoot"], comp["pass"], comp["sc"]], hole=0.55,
                    sort=False, marker=dict(colors=[accent, "#bc8cff", "#3fb950"]),
                    textinfo="label+percent"))
                cd.update_layout(template="plotly_dark", height=240,
                                 paper_bgcolor="rgba(0,0,0,0)", showlegend=False,
                                 margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(cd, width="stretch", key="pcard_sccomp")
            else:
                st.caption("No shots created.")
        with d3:
            st.markdown("**Scoring by quarter**")
            qb = S.quarter_boxes(game_ids=_gp_list).get(pid, {})
            qs = sorted(qb)
            if qs:
                qfig = go.Figure(go.Bar(
                    x=[f"Q{q}" if q <= 4 else f"OT{q-4}" for q in qs],
                    y=[qb[q]["PTS"] for q in qs], marker_color=accent,
                    marker_line_width=0,
                    text=[qb[q]["PTS"] for q in qs], textposition="auto"))
                qfig.update_yaxes(title="Points")
                _style(qfig, 240)
                qfig.update_layout(margin=dict(l=30, r=10, t=10, b=24))
                st.plotly_chart(qfig, width="stretch", key="pcard_qtr")
            else:
                st.caption("No quarter data.")

    # ── Set-call profile (one-tap play_type tags → Paid) ──────────────────────
    _named = getattr(ctx, "named_sets", None)
    _roles = getattr(ctx, "role_splits", None)
    _setprof = getattr(ctx, "set_profiles", None)  # {key: shot-profile} or None
    _ZL = {"LC": "left corner", "LW": "left wing", "C": "the paint",
           "RW": "right wing", "RC": "right corner"}

    def _howline(pr):
        """Gender-neutral 'how they score it' sub-line from a shot profile."""
        if not pr or (pr.get("poss") or 0) < 5:
            return ""
        bits = [f"{pr['PPP']:.2f} PPP"]
        if pr.get("3PA_rate") is not None:
            bits.append(f"{round(pr['3PA_rate']*100)}% 3PA")
        if pr.get("rim_rate") is not None:
            bits.append(f"{round(pr['rim_rate']*100)}% rim")
        if pr.get("ast_rate") is not None:
            bits.append(f"{round(pr['ast_rate']*100)}% assisted")
        if pr.get("open_rate") is not None:
            bits.append(f"{round(pr['open_rate']*100)}% open")
        _tz = pr.get("top_zone")
        if _tz:
            bits.append(f"mostly {_ZL.get(_tz, str(_tz))}")
        return " · ".join(bits) + f" ({pr['poss']} poss)"

    if paid and (_named or _roles):
        _ptlbl = dict(PT.NAMED_PLAY_TYPES)
        st.markdown("<div class='pl-hdr'>Set-call profile</div>",
                    unsafe_allow_html=True)
        if _named:
            # Go-to / take-away chip pair (ranked sets only, ≥8 poss).
            _ranked = {k: c for k, c in _named.items()
                       if c.get("pct") is not None and c["poss"] >= 8}
            if _ranked:
                _go_k = max(_ranked, key=lambda k: _ranked[k]["pct"])
                _aw_k = min(_ranked, key=lambda k: _ranked[k]["pct"])

                def _chip(k):
                    c = _ranked[k]
                    return _glass(
                        "GO-TO SET" if k == _go_k else "TAKE-AWAY",
                        _ptlbl.get(k, k.title()),
                        f"{c['PPP']:.2f} PPP · {c['pct']}th pct · {c['poss']} poss",
                        c["color"])
                _keys = [_go_k] + ([_aw_k] if _aw_k != _go_k else [])
                _cc = st.columns(len(_keys))
                for _col, _k in zip(_cc, _keys):
                    _col.markdown(_chip(_k), unsafe_allow_html=True)

            # Per-set percentile rows, sorted by PPP desc.  Each row carries an
            # optional "how they score it" sub-line from the set shot profile.
            html = ""
            for _k, c in sorted(_named.items(), key=lambda kv: kv[1]["PPP"],
                                reverse=True):
                _lbl = _ptlbl.get(_k, _k.title())
                _v = f"{c['PPP']:.2f} PPP · {c['FG%']*100:.0f}% · {c['poss']} poss"
                if c.get("pct") is None:
                    _v += " · thin sample"
                html += _pctile_bar(_lbl, _v, c.get("pct"))
                _hl = _howline((_setprof or {}).get(_k)) if _setprof else ""
                if _hl:
                    html += ("<div style='font-size:11px;color:var(--subtext);"
                             "margin:-5px 0 9px 0'>"
                             f"{html_escape(_hl)}</div>")
            if html:
                st.markdown(html, unsafe_allow_html=True)

        # Screen-action role split (handler vs roller on screen sets).
        if _roles:
            _role_keys = [k for k in ("pnr", "dho", "offscreen")
                          if (_roles.get(k) or {}).get("all", {}).get("poss", 0) > 0]
            if _role_keys:
                st.markdown("**Screen-action role** — finishing as the ball-handler "
                            "vs the screen-setter who rolls/pops")
                for _k in _role_keys:
                    rc = _roles[_k]
                    h, r = rc.get("handler", {}), rc.get("roller", {})
                    st.markdown(f"**{_ptlbl.get(_k, _k.title())}**")
                    rcols = st.columns(2)
                    rcols[0].metric(
                        "Handler", f"{h.get('PPP', 0):.2f} PPP",
                        f"{h.get('poss', 0)} poss", delta_color="off",
                        help=f"As the ball-handler off the screen — "
                             f"{h.get('FG%', 0)*100:.0f}% FG · "
                             f"{h.get('eFG', 0)*100:.0f}% eFG")
                    # Roll-vs-pop: roller 3PA_rate splits a rim-roller from a
                    # pick-and-pop big (high 3PA% = they pop for the three).
                    _r3 = r.get("3PA_rate")
                    _rsub = (f"pops 3 on {round(_r3*100)}% of finishes"
                             if _r3 is not None else "")
                    _rhelp = (f"As the screen-setter who finishes — "
                              f"{r.get('FG%', 0)*100:.0f}% FG · "
                              f"{r.get('eFG', 0)*100:.0f}% eFG")
                    if _r3 is not None:
                        _rhelp += (f" · pops for 3 on {round(_r3*100)}% of "
                                   f"finishes (high = pick-and-pop)")
                    rcols[1].metric(
                        "Roller", f"{r.get('PPP', 0):.2f} PPP",
                        f"{r.get('poss', 0)} poss", delta_color="off",
                        help=_rhelp)
                    if _rsub:
                        rcols[1].caption(_rsub)
        if _named and not any(c.get("pct") is not None for c in _named.values()) \
                and not _roles:
            st.caption("No play types tagged yet — add a one-tap Play type to a "
                       "shot in the Game Tracker to light this up.")

    # ── Across seasons — development (Tier 3, ML_LAYER_ROADMAP) ───────────────
    # Season-by-season lines + YoY progression/regression + a rough next-season
    # projection. Auto-lights-up as rollovers link more seasons; on one season it
    # shows the single line + the "unlocks after a 2nd season" note.
    if paid:
        _dv = _dev(pid, getattr(ctx, "gender", None))
        _prog, _proj = _dv["progression"], _dv["projection"]
        _lines = _prog["lines"]
        st.markdown("<div class='pl-hdr'>Across seasons — development</div>",
                    unsafe_allow_html=True)
        if _lines:
            st.dataframe(pd.DataFrame([{
                "Season": L["label"], "Class": L.get("klass") or "—",
                "Team": L["team"], "GP": L["gp"], "PPG": L["PPG"], "RPG": L["RPG"],
                "APG": L["APG"], "SPG": L["SPG"], "BPG": L["BPG"],
                "TPG": L.get("TPG"), "FPG": L.get("FPG"),
                "FG%": L["FG%"], "3P%": L["3P%"], "TS%": L["TS%"],
            } for L in _lines]), hide_index=True, width="stretch")
        # progression / regression (two+ rated seasons)
        if _prog["deltas"]:
            if _prog["headline"]:
                st.markdown(f"**Trajectory:** {_prog['headline']}")
            _dcols = st.columns(len(_DEV_STATS))
            for _col, _lab in zip(_dcols, _DEV_STATS):
                _d = _prog["deltas"].get(_lab)
                _cur = (_prog["cur"] or {}).get(_lab)
                if _d is not None and _cur is not None:
                    _col.metric(_lab, f"{_cur:g}",
                                f"{_d['delta']:+.1f} {_d['trend']}",
                                delta_color="inverse" if _lab in _DEV_INVERTED
                                else "normal")
        # rest-of-THIS-season projection — works from the player's first
        # season (3+ games), no linked past season needed
        _ros = _dv.get("rest_of_season") or {}
        if _ros.get("ok"):
            st.markdown(
                f"<div class='pl-hdr'>Rest of season "
                f"<span style='font-size:11px;color:#8b949e;font-weight:400'>"
                f"· {_ros['gp']} played · {_ros['remaining']} left — projected "
                f"season-end totals (per-game)</span></div>",
                unsafe_allow_html=True)
            _rcols = st.columns(len(_DEV_STATS))
            for _col, _lab in zip(_rcols, _DEV_STATS):
                _t = _ros["season_end"].get(_lab)
                _r = _ros["per_game"].get(_lab)
                if _t is not None:
                    _col.metric(_lab.replace("PG", ""), f"{_t:g}",
                                f"{_r:g}/g", delta_color="off")
            st.caption(_ros["note"])
        # projection (two+ rated seasons) or the unlock note
        if _proj.get("ok"):
            st.markdown("<div class='pl-hdr'>Projected next season</div>",
                        unsafe_allow_html=True)
            _pcols = st.columns(len(_DEV_STATS))
            for _col, _lab in zip(_pcols, _DEV_STATS):
                _v = _proj["proj"].get(_lab)
                if _v is not None:
                    _col.metric(_lab, f"{_v:g}")
            _fc = (f" · {_proj['from_class']}→{_proj['to_class']}"
                   if _proj.get("from_class") and _proj.get("to_class") else "")
            st.caption(f"{_proj['note']} Basis: {_proj['basis']}{_fc}.")
        else:
            st.caption(_proj.get("reason", ""))

    # ── Career highs & milestones — Free tier (Paid gets them in the grid) ─────
    if not paid:
        st.markdown("<div class='pl-hdr'>Career highs &amp; milestones</div>",
                    unsafe_allow_html=True)
        cap_steady = ("steady" if (P["PTSsd"] or 0) < 5 else
                      "streaky" if (P["PTSsd"] or 0) > 9 else "moderate")
        ch = st.columns(6)
        ch[0].markdown(_glass("HIGH PTS", P["bestPTS"], "single game", accent),
                       unsafe_allow_html=True)
        ch[1].markdown(_glass("HIGH REB", P["bestREB"], "single game", "#3fb950"),
                       unsafe_allow_html=True)
        ch[2].markdown(_glass("HIGH AST", P["bestAST"], "single game", "#bc8cff"),
                       unsafe_allow_html=True)
        ch[3].markdown(_glass("DOUBLE-DBL", P["DD"], "games", "#58a6ff"),
                       unsafe_allow_html=True)
        ch[4].markdown(_glass("TRIPLE-DBL", P["TD"], "games", "#f0a500"),
                       unsafe_allow_html=True)
        ch[5].markdown(_glass("SCORING σ", _fmt(P["PTSsd"], "f1"),
                              f"game-to-game · {cap_steady}", "#ff7b72"),
                       unsafe_allow_html=True)

    # ── Game log ──────────────────────────────────────────────────────────────
    st.markdown("<div class='pl-hdr'>Game log</div>",
                unsafe_allow_html=True)
    gids = [r["gid"] for r in query(
        """SELECT DISTINCT ge.game_id AS gid
           FROM game_event_lineup gel
           JOIN game_events ge ON ge.id = gel.event_id
           WHERE gel.player_id = ?""", (pid,))]
    games = query(
        """SELECT g.id, g.date, g.team1_id, g.team2_id, g.home_score,
                  g.away_score
           FROM games g WHERE g.id IN ({})""".format(
            ",".join("?" * len(gids)) or "NULL"), tuple(gids)) if gids else []
    name_of = {t["id"]: t["name"] for t in query("SELECT id, name FROM teams")}
    log = []
    _boxes = pgb.get(pid, {})
    for g in sorted(games, key=lambda x: x["date"]):
        b = _boxes.get(g["id"])
        if not b:
            continue
        opp = g["team2_id"] if g["team1_id"] == P["team_id"] else g["team1_id"]
        log.append({
            "Date": g["date"], "Opp": name_of.get(opp, "?"),
            "PTS": b["PTS"], "REB": b["TRB"], "AST": b["AST"],
            "STL": b["STL"], "BLK": b["BLK"], "TOV": b["TOV"], "PF": b["PF"],
            "FG": f"{b['FGM']}/{b['FGA']}", "3P": f"{b['3PM']}/{b['3PA']}",
            "FT": f"{b['FTM']}/{b['FTA']}",
            "GS": round(S.game_score(b), 1),
        })
    if log:
        # trend across games
        gx = [f"{g['Date'][5:]} {g['Opp'][:8]}" for g in log]
        tr = go.Figure()
        tr.add_trace(go.Bar(x=gx, y=[g["PTS"] for g in log], name="PTS",
                            marker_color=accent, marker_line_width=0))
        tr.add_trace(go.Scatter(x=gx, y=[g["GS"] for g in log], name="Game Score",
                                mode="lines+markers", line=dict(color="#56d4dd",
                                                                width=2)))
        tr.update_yaxes(title="Points / Game Score")
        tr.update_xaxes(tickangle=-40)
        _style(tr, 320)
        st.plotly_chart(tr, width="stretch", key="pcard_log")

        st.dataframe(pd.DataFrame(log), hide_index=True,
                     width="stretch",
                     height=min(560, 60 + 35 * len(log)))
        st.caption(f"{len(log)} tracked games. Box scores are per game from "
                   "tracked events.")

        # ── rolling form · season highs · last-5 · foul & FT ────────────────
        _tlog = TRD.player_game_log(pid, boxes=pgb)
        if _tlog:
            _pseries = [g["box"].get("PTS", 0) or 0 for g in _tlog]
            _roll = TRD.rolling(_pseries)
            _gx2 = [f"{g['date'][5:]} {g['opp'][:8]}" for g in _tlog]
            st.markdown("<div class='pl-hdr'>Rolling form (3-game average)</div>",
                        unsafe_allow_html=True)
            rf = go.Figure()
            rf.add_trace(go.Bar(x=_gx2, y=_pseries, name="PTS",
                                marker_color="#30363d", marker_line_width=0))
            rf.add_trace(go.Scatter(x=_gx2, y=_roll, name="3-game avg",
                                    mode="lines+markers",
                                    line=dict(color=accent, width=3)))
            rf.update_yaxes(title="Points")
            rf.update_xaxes(tickangle=-40)
            _style(rf, 280)
            st.plotly_chart(rf, width="stretch", key="pcard_rolling")

            _hi = TRD.season_highs(_tlog)
            st.markdown("<div class='pl-hdr'>Season highs</div>",
                        unsafe_allow_html=True)
            _hc = st.columns(len(TRD.HIGH_KEYS))
            for _col, (_k, _lbl) in zip(_hc, TRD.HIGH_KEYS):
                _h = _hi.get(_k)
                _col.metric(_lbl, _h["value"] if _h else 0,
                            f"vs {_h['opp'][:10]}" if _h else None,
                            delta_color="off")

            _l5 = TRD.last_n_split(_tlog, n=5)
            _stk = TRD.streaks(_tlog)
            st.markdown("<div class='pl-hdr'>Recent form — last 5 vs season</div>",
                        unsafe_allow_html=True)
            _fc = st.columns(4)
            for _col, _k in zip(_fc[:3], ("PTS", "TRB", "AST")):
                _rec, _seas = _l5.get(_k, (0, 0))
                _col.metric(f"{_k} (last 5)", f"{_rec:.1f}",
                            f"{_rec - _seas:+.1f} vs season")
            _fc[3].metric("Double-figure scoring", f"{_stk['current']} in a row",
                          f"longest {_stk['longest']}", delta_color="off")

        _ff = foulft
        if _ff and (_ff["FTA"] or _ff["PF"] or _ff["drawn"]):
            st.markdown("<div class='pl-hdr'>Fouls &amp; free throws</div>",
                        unsafe_allow_html=True)
            _h1 = (_ff["FTM_1h"] / _ff["FTA_1h"] * 100) if _ff["FTA_1h"] else None
            _h2 = (_ff["FTM_2h"] / _ff["FTA_2h"] * 100) if _ff["FTA_2h"] else None
            _ffc = st.columns(7)
            _ffc[0].metric("Fouls drawn", _ff["drawn"])
            _ffc[1].metric("Fouls committed", _ff["PF"])
            _ffc[2].metric("Free throws", f"{_ff['FTM']}/{_ff['FTA']}")
            _ffc[3].metric("FT%", f"{_ff['FT%']:.0f}%")
            _ffc[4].metric(
                "FT% 1st / 2nd",
                f"{_h1:.0f} / {_h2:.0f}" if (_h1 is not None and _h2 is not None)
                else (f"{_h1:.0f} / —" if _h1 is not None else "—"))
            _ffc[5].metric(
                "Clutch FT", (f"{_ff['cFTM']}/{_ff['cFTA']} "
                              f"({_ff['ClutchFT%']:.0f}%)")
                if _ff.get("cFTA") else "—",
                help="Free throws in high-leverage moments (win-probability "
                     "swing ≥ 1.5× the game's average — the Clutch WPA bar).")
            _ffc[6].metric(
                "And-1s", (f"{_ff.get('and1_made', 0)}/{_ff.get('and1', 0)}"
                           if _ff.get("and1") else "—"),
                help="Made basket + the bonus free throw: trips and conversions "
                     "(linked from the event stream).")
            st.caption("Fouls drawn = times this player was fouled · FT% split by "
                       "half (1st = Q1–2) · Clutch FT = the line when it matters · "
                       "And-1s = three-point-play trips (converted/earned).")
    else:
        empty_state("No tracked games yet",
                    "Track a game with this player in the Game Tracker and "
                    "their game log will show up here.")

    # ── League percentiles — Free tier only (Paid gets the Overview grid rail) ──
    if not paid:
        st.markdown("<div class='pl-hdr'>League percentiles</div>",
                    unsafe_allow_html=True)
        # Free tier: keep box percentiles only (drop event-derived rows).
        PROF_PCT = [s for s in [
            ("PPG", "Points", "f1", False), ("RPG", "Rebounds", "f1", False),
            ("APG", "Assists", "f1", False), ("SPG", "Steals", "f1", False),
            ("BPG", "Blocks", "f1", False), ("STOCKS/G", "Stocks", "f1", False),
            ("TS%", "True shooting", "pct", False), ("eFG%", "Effective FG", "pct", False),
            ("3P%", "Three-point %", "pct", False), ("PPS", "Points / shot", "f2", False),
            ("USG%", "Usage", "pct", False), ("TOV%", "Ball security", "pct", True),
            ("AST/TOV", "Assist / TO", "f2", False), ("REB%", "Rebound %", "pct", False),
            ("Guarded%", "Contest rate", "pct", False), ("DSHOT%", "Defended FG%", "pct", True),
            ("EFF", "Efficiency", "f1", False), ("FIC", "Floor impact", "f1", False),
            ("+/-", "Plus/minus", "int", False), ("GS/G", "Game Score", "f1", False),
            ("VPS", "Value Point System", "f2", False),
        ] if s[0] not in PR.EVENT_DERIVED_STATS]
        pcol = st.columns(2)
        half = (len(PROF_PCT) + 1) // 2
        for ci, chunk in enumerate((PROF_PCT[:half], PROF_PCT[half:])):
            html = ""
            for key, lbl, fmt, lb in chunk:
                p = _pctile(P.get(key), key, rows, lower_better=lb)
                html += _pctile_bar(lbl, _fmt(P.get(key), fmt), p)
            pcol[ci].markdown(html, unsafe_allow_html=True)

    # ── League ranking (rides on OVERALL → Paid) ──────────────────────────────
    if paid:
        st.markdown("<div class='pl-hdr'>League ranking</div>",
                    unsafe_allow_html=True)
        n = len(rows)
        pctile_ovr = round((n - P["Rank"]) / max(n - 1, 1) * 100)
        rk = st.columns(3)
        rk[0].metric("League rank", f"#{P['Rank']} of {n}")
        rk[1].metric("OVERALL", f"{P['OVERALL']:.1f}")
        rk[2].metric("Percentile", f"{pctile_ovr}th")

        rank_stats = [("OVERALL", "f1"), ("OFFENSE", "f1"), ("DEFENSE", "f1"),
                      ("PLAYMAKING", "f1"), ("REBOUNDING", "f1"), ("PPG", "f1"),
                      ("RPG", "f1"), ("APG", "f1"), ("STOCKS", "int"), ("EFF", "int"),
                      ("TS%", "pct"), ("GS/G", "f1")]
        rrows = []
        for key, fmt in rank_stats:
            pool = [r for r in rows if r.get(key) is not None]
            if P.get(key) is None or not pool:
                continue
            sr = sorted(pool, key=lambda r: r[key], reverse=True)
            pos = next(i for i, r in enumerate(sr, 1) if r is P)
            rrows.append({"Stat": key, "Value": _fmt(P[key], fmt),
                          "Rank": f"#{pos} of {len(pool)}",
                          "Pctile": f"{round((len(pool)-pos)/max(len(pool)-1,1)*100)}th"})
        st.dataframe(pd.DataFrame(rrows), hide_index=True, width="stretch")

        with st.expander("OVERALL league bar — this player highlighted"):
            order_ovr = sorted([r for r in rows if r["OVERALL"] is not None],
                               key=lambda r: r["OVERALL"])
            bar = go.Figure(go.Bar(
                x=[r["OVERALL"] for r in order_ovr],
                y=[f"{r['name']}" for r in order_ovr], orientation="h",
                marker_color=[hue if r is P else "#30363d" for r in order_ovr],
                text=[f"{r['OVERALL']:.1f}" if r is P else "" for r in order_ovr],
                textposition="outside", textfont=dict(color=hue, size=12)))
            bar.update_layout(
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)", height=max(380, n * 22),
                margin=dict(l=4, r=40, t=10, b=10), showlegend=False,
                font=dict(size=10, color="#c9d1d9"))
            bar.update_xaxes(visible=False)
            bar.update_yaxes(showgrid=False, automargin=True, tickfont=dict(size=9))
            st.plotly_chart(bar, width="stretch", key="pcard_leaguebar")

    # ── Per-32 minutes (MIN-based → Paid) ─────────────────────────────────────
    if paid:
        st.markdown("<div class='pl-hdr'>Per-32 minutes</div>",
                    unsafe_allow_html=True)
        if (P["MPG"] or 0) >= 5 and (P["MIN"] or 0) > 0:
            scale = 32.0 / P["MIN"]
            per32 = [("PTS", P["PTS"]), ("REB", P["REB"]), ("AST", P["AST"]),
                     ("STL", P["STL"]), ("BLK", P["BLK"]), ("TOV", P["TOV"]),
                     ("SC", P["SC"])]
            p32 = go.Figure(go.Bar(
                x=[k for k, _ in per32], y=[v * scale for _, v in per32],
                marker_color=["#f0a500", "#3498db", "#2ecc71", "#58a6ff",
                              "#e74c3c", "#e67e22", "#9b59b6"],
                text=[f"{v*scale:.1f}" for _, v in per32], textposition="outside",
                marker_line_width=0))
            p32.update_yaxes(title="Per 32 min")
            _style(p32, 300)
            st.plotly_chart(p32, width="stretch", key="pcard_per32")
            st.caption("Totals × 32 ÷ tracked minutes. HS games run ≈32 min here, so "
                       "per-32 ≈ a full game's production. Minutes come from tracked "
                       "possession time (a slight undercount).")
        else:
            st.caption("Per-32 needs ≥5 minutes per game of tracked floor time.")

    # ── On / Off court impact (lineup-based → Paid) ───────────────────────────
    if paid:
        st.markdown("<div class='pl-hdr'>On / Off court impact</div>",
                    unsafe_allow_html=True)
        st.caption("Does the **team** rebound, share the ball, and protect "
                   "possessions better with this player on the floor? Covers every "
                   "game the team played; small samples are directional.")

        # Team for the split: on a PAST-season pool, resolve from the lineup
        # snapshots — players.team_id is the CURRENT roster, so a transferred
        # player (Vinita → Adair) would otherwise get the NEW team's on/off
        # over a season they played somewhere else.
        _oot = ((S.player_lineup_team(pid, list(_gp)) if _gp is not None
                 else None) or P["team_id"])
        ro = S.player_rebound_onoff(pid, _oot,
                                    game_ids=(list(_gp) if _gp is not None else None))
        pm = S.player_playmaking_onoff(pid, _oot,
                                       game_ids=(list(_gp) if _gp is not None else None))

        if ro and ro.get("on_oreb_opps", 0) >= 5:
            st.markdown("**Team rebounding**")
            oc1, oc2 = st.columns(2)
            oc1.markdown(_onoff_html(
                "Team OREB%", ro["on_oreb_pct"], ro["off_oreb_pct"],
                ro["on_oreb_opps"], ro["off_oreb_opps"], "opps", True),
                unsafe_allow_html=True)
            oc2.markdown(_onoff_html(
                "Team DREB%", ro["on_dreb_pct"], ro["off_dreb_pct"],
                ro["on_dreb_opps"], ro["off_dreb_opps"], "opps", True),
                unsafe_allow_html=True)
        else:
            st.info("Not enough tracked rebound opportunities for a reliable "
                    "rebounding on/off split yet (need ≥5 on-court).")

        if pm and pm.get("on_fgm", 0) >= 5:
            st.markdown("**Team playmaking & ball security**")
            pc1, pc2 = st.columns(2)
            pc1.markdown(_onoff_html(
                "Team AST%", pm["on_ast_pct"], pm["off_ast_pct"],
                pm["on_fgm"], pm["off_fgm"], "FGM", True),
                unsafe_allow_html=True)
            pc2.markdown(_onoff_html(
                "Team TOV%", pm["on_tov_pct"], pm["off_tov_pct"],
                pm["on_tov"], pm["off_tov"], "TOV", False),
                unsafe_allow_html=True)
            st.caption("AST% = assisted made FGs ÷ made FGs.  TOV% = turnovers ÷ "
                       "possessions.  Lower TOV% is better — green means the team "
                       "turns it over **less** with this player on.")
        else:
            st.info("Not enough tracked possessions for a reliable playmaking on/off "
                    "split yet (need ≥5 team FGM on-court).")

    # ── Scouting report — rides on the category ratings → Paid ────────────────
    if paid:
        st.markdown("<div class='pl-hdr'>Scouting report</div>",
                    unsafe_allow_html=True)

        def pc(key, lb=False):
            return _pctile(P.get(key), key, rows, lower_better=lb) or 0

        OFF, DEF, PLY, REB_R = (P["OFFENSE"] or 0, P["DEFENSE"] or 0,
                                P["PLAYMAKING"] or 0, P["REBOUNDING"] or 0)
        OVR = P["OVERALL"] or 0

        if OVR >= 65 and DEF >= 60:
            arch = ("Two-Way Force",
                    "Produces on offense and disrupts on defense — a rare both-ends impact.")
        elif OFF >= 62 and pc("PPG") >= 80:
            arch = ("Scoring Machine",
                    "A primary offensive weapon who creates and converts at volume.")
        elif PLY >= 62 and pc("APG") >= 80:
            arch = ("Floor General",
                    "Runs the offense through vision and distribution.")
        elif REB_R >= 62 or pc("REB") >= 85:
            arch = ("Glass Cleaner",
                    "Owns the boards and generates extra possessions.")
        elif DEF >= 62 or pc("STOCKS") >= 85:
            arch = ("Defensive Anchor",
                    "Disrupts opponents with steals, blocks, and contests.")
        elif pc("3P%") >= 70 and P["3PA"] >= 15 and pc("DSHOT%", True) >= 55:
            arch = ("3-and-D Wing",
                    "Spaces the floor and holds up defensively — a valuable role.")
        elif pc("3P%") >= 70 and P["3PA"] >= 20:
            arch = ("Spot-Up Shooter",
                    "An off-ball threat who punishes help defense from deep.")
        elif pc("Paint%") >= 70 and pc("REB") >= 60:
            arch = ("Interior Presence",
                    "Finishes inside efficiently and commands the paint.")
        elif OVR >= 56:
            arch = ("Versatile Contributor",
                    "Well-rounded across the board without one dominant trait.")
        elif pc("+/-") >= 75:
            arch = ("High-Impact Role Player",
                    "The team plays better with them on the floor.")
        else:
            arch = ("Developing Player",
                    "Still building their game — more tracked games will sharpen it.")

        st.markdown(
            f"<div style='background:linear-gradient(135deg,#1a1200,#0d1117);"
            f"border:1px solid {accent};border-radius:12px;padding:14px 18px;"
            f"margin-bottom:14px;display:flex;align-items:center;gap:14px'>"
            f"<div>"
            f"<div style='font-size:10px;font-weight:700;letter-spacing:.08em;"
            f"color:#8b949e;text-transform:uppercase'>Scouting role</div>"
            f"<div style='font-size:15px;font-weight:800;color:{accent}'>{arch[0]}</div>"
            f"<div style='font-size:12px;color:#8b949e;margin-top:3px'>{arch[1]}</div>"
            f"</div></div>", unsafe_allow_html=True)

        strengths, weaknesses = [], []
        if pc("PPG") >= 85:
            strengths.append(("Elite scorer", f"{P['PPG']:.1f} PPG — top of the league."))
        elif pc("PPG") >= 65:
            strengths.append(("Consistent scorer", f"{P['PPG']:.1f} PPG."))
        if pc("TS%") >= 80:
            strengths.append(("Efficient shooter", f"{_fmt(P['TS%'],'pct')} TS% — high value per shot."))
        if pc("3P%") >= 80 and P["3PA"] >= 12:
            strengths.append(("3-point threat", f"{_fmt(P['3P%'],'pct')} on {P['3PA']} attempts."))
        if pc("REB") >= 85:
            strengths.append(("Dominant rebounder", f"{P['RPG']:.1f} RPG."))
        if pc("APG") >= 85:
            strengths.append(("Elite facilitator", f"{P['APG']:.1f} APG."))
        if pc("AST/TOV") >= 80 and (P["AST/TOV"] or 0) >= 1.5:
            strengths.append(("Great ball security", f"{P['AST/TOV']:.2f} AST/TOV."))
        if pc("STOCKS") >= 85:
            strengths.append(("Disruptive defender", f"{P['STL']} STL / {P['BLK']} BLK."))
        if pc("+/-") >= 85:
            strengths.append(("Strong net impact", f"{P['+/-']:+d} plus/minus."))
        strengths = strengths[:4]

        if pc("TS%", ) <= 25 and P["FGA"] >= 20:
            weaknesses.append(("Below-average efficiency", f"{_fmt(P['TS%'],'pct')} TS%."))
        if pc("TOV%", True) <= 25 and P["TOV%"] is not None:
            weaknesses.append(("Turnover-prone", f"{_fmt(P['TOV%'],'pct')} turnover rate."))
        if pc("3P%") <= 25 and P["3PA"] >= 15:
            weaknesses.append(("Streaky from three", f"{_fmt(P['3P%'],'pct')} on {P['3PA']} attempts."))
        if P["FT%"] is not None and pc("FT%") <= 25 and P["FTA"] >= 10:
            weaknesses.append(("Shaky at the line", f"{_fmt(P['FT%'],'pct')} FT%."))
        if pc("REB%") <= 20 and (P["MPG"] or 0) >= 12:
            weaknesses.append(("Limited on the glass", "Low rebound rate for the minutes."))
        if pc("STOCKS") <= 15 and (P["MPG"] or 0) >= 14:
            weaknesses.append(("Low defensive activity", "Few steals or blocks for the minutes."))
        weaknesses = weaknesses[:3]

        def _bullets(items, empty):
            if not items:
                return f"<div style='font-size:12px;color:#484f58;font-style:italic'>{empty}</div>"
            return "".join(
                f"<div style='margin-bottom:9px'>"
                f"<div style='font-size:13px;font-weight:700;color:#f0f6fc'>{l}</div>"
                f"<div style='font-size:12px;color:#8b949e'>{d}</div></div>"
                for l, d in items)

        sc1, sc2 = st.columns(2)
        sc1.markdown(
            f"<div class='pl-scout'><div style='font-size:13px;font-weight:700;"
            f"color:#2ea043;margin-bottom:10px'>Strengths</div>"
            f"{_bullets(strengths, 'No standout strengths in this sample yet.')}</div>",
            unsafe_allow_html=True)
        sc2.markdown(
            f"<div class='pl-scout'><div style='font-size:13px;font-weight:700;"
            f"color:#f0a500;margin-bottom:10px'>Areas to watch</div>"
            f"{_bullets(weaknesses, 'No clear weaknesses in this sample yet.')}</div>",
            unsafe_allow_html=True)
