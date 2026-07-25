"""
dashboard/team_card.py — the OOTP-style team header card (UI_DENSITY_PLAN C).

The team analog of player_card.py: ONE dense above-the-fold read shared by the
Team Dashboard Overview (phase C) and, next, the Rankings Team deep dive
(phase D) — so the two team surfaces stop drifting apart.

Layout grammar (mirrors the player page): a BANNER (name · record · Power with
the tier hue), the team-glance strip (most-distinctive stats vs the league),
then three zones —
    A · Identity   record detail, vs-ranked, game-type records, rest & fatigue
    B · Engine     tracked efficiency: ORtg/DRtg/Net/Pace, adjusted shooting,
                   possession ledger (where points come from / leak)
    C · Verdict    Pythagorean expectation + luck, momentum, tracked rank,
                   the model's read on the NEXT game
Every number is measured or model-derived and labeled as such — the OOTP feel,
not a video game.
"""
from __future__ import annotations

import streamlit as st

from database.db import query
from helpers.cards import tier as _tier
import helpers.team_analytics as TA
from helpers.stats import ordinal as _ORD  # percentile suffixes: 71st, not 71th


# ── cached data the header needs beyond ctx ─────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _glance(gender, team_id, season="Current"):
    import helpers.insights_team as INT
    return INT.team_glance(gender, team_id, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _scored_pool(gender, season="Current"):
    """League results-math ratings — the banner's Free-safe half (Power, rank,
    W/L/MOV/GP). Cached here so a page that draws only the banner doesn't have
    to import the Team Dashboard's own rating wrappers."""
    import helpers.team_ratings as TR
    return TR.score_ratings(gender=gender, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _tracked_pool(gender, season="Current"):
    """League tracked ratings — the banner's DEPTH half (tracked rank + GP).
    Never rendered without a tracked_gate answer; see render_for."""
    import helpers.team_ratings as TR
    return TR.tracked_ratings(gender=gender, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _form(gender, season="Current"):
    import helpers.league_analytics as LA
    return LA.team_form_stats(gender=gender, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _rest(team_id):
    import helpers.fatigue as FT
    try:
        return FT.team_rest_splits(team_id)
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _adj_shoot(gender, season="Current"):
    import helpers.adj_efficiency as AE
    try:
        return AE.adjusted_shooting(gender, season=season)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _ledger(team_id, game_ids=None):
    # `game_ids` scopes the ledger to a season's tracked games (the page passes the
    # team's season-scoped bundle["tracked_ids"]); None = the engine's current
    # default. Hashable tuple in, list out for the engine.
    import helpers.possession_value as PV
    try:
        return PV.possession_ledger(
            team_id, game_ids=(list(game_ids) if game_ids is not None else None))
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _style_tags(gender, season="Current"):
    """League-wide team style archetypes (tracked plane) — one compute per
    gender; the banner shows only this team's tag."""
    import helpers.league_analytics as LA
    import helpers.archetypes as AR
    try:
        pack = LA.team_tracked_pack(gender=gender, season=season)
        return AR.team_style_tags(pack.get("ts", {}))
    except Exception:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def _next_game(team_id, season="Current"):
    """The next scheduled game (score-less, today or later) or None. A PAST season
    is over — there is no 'next game', so archive views get None (fixes past-season
    games showing under a prior season's 'Next')."""
    import helpers.seasons as _SEAS
    if not _SEAS.is_current(season):
        return None
    from datetime import datetime
    rows = query("""
        SELECT g.id, g.date, g.team1_id, g.team2_id, t1.name n1, t2.name n2
        FROM games g JOIN teams t1 ON t1.id = g.team1_id
                     JOIN teams t2 ON t2.id = g.team2_id
        WHERE (g.team1_id = ? OR g.team2_id = ?)
          AND (g.home_score IS NULL OR g.away_score IS NULL)
          AND g.date >= ? AND g.season = 'Current'
        ORDER BY g.date LIMIT 1""",
        (team_id, team_id, datetime.now().strftime("%Y-%m-%d")))
    return dict(rows[0]) if rows else None


# ── tiny html primitives (same visual language as the player card) ──────────────
def _kv(k, v, vc="var(--text)"):
    return (f"<div style='display:flex;justify-content:space-between;"
            f"font-size:12px;padding:2px 0'><span style='color:var(--subtext)'>{k}"
            f"</span><span style='color:{vc};font-weight:600'>{v}</span></div>")


def _zone_hdr(t):
    return (f"<div style='font-size:10px;color:var(--subtext);text-transform:uppercase;"
            f"letter-spacing:1.5px;margin:0 0 4px'>{t}</div>")


def render_mini(team_id, gender, scored, tracked=None, show_tracked=False):
    """Compact one-column team read for side-by-side comparisons (the War Room
    tale of the tape) — banner line + key rows, same visual language as the
    full header. Returns an HTML string (caller places it in a column).

    `show_tracked` gates the possession-depth rows (adjusted ORtg/DRtg, pace,
    Adj eFG) on the VIEWER's entitlement for this team — results-only rows
    render for everyone on a Paid plan."""
    r = (scored or {}).get(team_id) or {}
    tr = (tracked or {}).get(team_id) if show_tracked else None
    hue, tlabel = _tier(r.get("Power"))
    _trow = query("SELECT name, class FROM teams WHERE id=?", (team_id,))
    tname = _trow[0]["name"] if _trow else "Team"
    fm = _form(gender).get(team_id, {})
    _stk = (f" · {fm['streak_type']}{fm['streak_len']}"
            if fm.get("streak_type") and fm.get("streak_len") else "")
    html = (
        f"<div style='background:var(--card-bg-2);border:1px solid {hue}55;"
        f"border-radius:12px;padding:12px 14px'>"
        f"<div style='display:flex;justify-content:space-between;"
        f"align-items:baseline'>"
        f"<div style='font-size:16px;font-weight:800;color:var(--text)'>{tname}"
        f"</div><div style='font-size:22px;font-weight:900;color:{hue}'>"
        f"{r.get('Power', '—')}</div></div>"
        f"<div style='font-size:10px;color:{hue};letter-spacing:1px;"
        f"margin-bottom:6px'>{tlabel} · #{r.get('Rank', '—')}</div>")
    html += _kv("Record", f"{r.get('W', 0)}-{r.get('L', 0)}{_stk}")
    if r.get("MOV") is not None:
        html += _kv("Margin / game", f"{r['MOV']:+.1f}")
    if r.get("PPG") is not None:
        html += _kv("PPG / opp", f"{r['PPG']:.0f} / {r.get('oPPG', 0):.0f}")
    if r.get("SOS") is not None:
        html += _kv("SOS", f"{r['SOS']:.1f}")
    if fm.get("mom_delta") is not None:
        html += _kv("Momentum (L5 − season)", f"{fm['mom_delta']:+.1f}",
                    vc="var(--good)" if fm["mom_delta"] >= 0 else "var(--bad)")
    if tr:
        html += _kv("Adj Off / Def rating",
                    f"{tr['ORtg']:.0f} / {tr['DRtg']:.0f}")
        html += _kv("Pace", f"{tr['Pace']:.1f}")
        _aj = _adj_shoot(gender).get(team_id)
        if _aj:
            html += _kv("Adj eFG% (off / def)",
                        f"{_aj['AdjeFG'] * 100:.0f} / {_aj['AdjoeFG'] * 100:.0f}")
    html += "</div>"
    return html


def render_banner(ctx):
    """The slim team-identity banner (name · tier · record · Power).

    Page-level chrome: rendered once above the view switcher on EVERY Team
    Dashboard view (so the team you're reading is never ambiguous), and again as
    the top of ``render_header`` for the Overview / Rankings deep dive. Power,
    record and rank are results-math → Free-safe; the tracked-gated bits (the
    style tag, the tracked rank / tracked-game count) drop out when
    ``has_tracked`` is False.

    ``has_tracked`` must be the resolved ``entitlement.tracked_gate`` answer for
    THIS viewer and THIS team, never a raw "does data exist" flag. The tracked
    rank is co-op-gated depth: a team that has not opted into the pool must not
    have its tracked standing exposed by chrome that every page draws.
    """
    sc = ctx.sc_score or {}
    rec = ctx.rec
    _season = getattr(ctx, "season", "Current")
    st.markdown(
        _banner_html(
            team_id=ctx.team_id, gender=ctx.gender, season=_season,
            power=sc.get("Power"), rank=sc.get("Rank"),
            pool_n=len(ctx.scored or ()),
            wins=rec["wins"], losses=rec["losses"], mov=rec["MOV"],
            games=sc.get("GP"),
            has_tracked=getattr(ctx, "has_tracked", False),
            trk=(getattr(ctx, "tracked", None) or {}).get(ctx.team_id),
            trk_pool_n=len(getattr(ctx, "tracked", None) or ()),
        ),
        unsafe_allow_html=True)


def _banner_html(*, team_id, gender, season, power, rank, pool_n, wins, losses,
                 mov, games=None, has_tracked=False, trk=None, trk_pool_n=0):
    """The banner's markup — ONE renderer for every surface that draws it.

    Extracted so the Team Dashboard path (which already holds the ratings dicts)
    and the standalone page-chrome path (``render_for``, which resolves them
    itself) cannot drift into two different-looking banners. Everything the
    banner shows arrives as a plain value; this function does no I/O beyond the
    team name and the per-season class.
    """
    hue, tlabel = _tier(power)
    _trow = query("SELECT name, class FROM teams WHERE id=?", (team_id,))
    tname = _trow[0]["name"] if _trow else "Team"
    # class is per-season: a past-season view shows the class the team played in
    # (snapshotted at rollover), not the re-aligned current class.
    import helpers.seasons as _SEAS
    _cls = _SEAS.team_class(team_id, season) or ""
    fm = _form(gender, season).get(team_id, {})
    _stk = (f"{fm['streak_type']}{fm['streak_len']}"
            if fm.get("streak_type") and fm.get("streak_len") else "")
    # data-driven style identity (tracked plane, same gate as the glance strip)
    _style = _style_tags(gender, season).get(team_id) if has_tracked else None
    _style_bit = ""
    if _style and _style.get("tag") and _style["tag"] != "Balanced":
        _sig = f" — {_style['signature']}" if _style.get("signature") else ""
        _style_bit = (f" · <span style='color:#bc8cff;font-weight:700' "
                      f"title='Data-driven style read vs the league"
                      f"{_sig}'>{_style['tag']}</span>")

    # Games played sits next to the record because a 29-3 over 32 games and a
    # 29-3 over 40 are different seasons, and the record alone hides which.
    _gp_bit = f" · {games} G" if games else ""

    # Tracked standing — DEPTH, so it renders only behind the resolved gate.
    _trk_bit = ""
    if has_tracked and trk:
        _tr_rank = trk.get("Rank")
        _tr_gp = trk.get("GP")
        _bits = []
        if _tr_rank is not None and trk_pool_n:
            _bits.append(f"tracked #{_tr_rank} of {trk_pool_n}")
        if _tr_gp:
            _bits.append(f"{_tr_gp} tracked")
        if _bits:
            _trk_bit = (f"<div style='font-size:12px;color:var(--subtext);"
                        f"margin-top:3px'>{' · '.join(_bits)}</div>")

    return (
        f"<div class='team-banner' style='background:var(--card-grad);"
        f"border:1px solid {hue}66;border-radius:18px;padding:18px 24px;"
        f"margin-bottom:12px;position:relative;overflow:hidden'>"
        f"<div style='position:absolute;left:0;top:0;bottom:0;width:4px;"
        f"background:{hue};box-shadow:0 0 18px {hue}'></div>"
        f"<div style='display:flex;align-items:center;gap:22px'>"
        f"<div style='flex:1'>"
        f"<div style='font-size:28px;font-weight:900;color:var(--text);line-height:1.05'>"
        f"{tname}</div>"
        f"<div style='font-size:13px;color:var(--subtext);margin-top:4px'>"
        f"<span style='color:{hue};font-weight:700;letter-spacing:1px'>{tlabel}</span>"
        f"{_style_bit}"
        f"{' · ' + _cls if _cls else ''} · {wins}-{losses}{_gp_bit}"
        f"{' · ' + _stk if _stk else ''} · MOV {mov:+.1f} · "
        f"#{rank if rank is not None else '—'} of {pool_n}</div>"
        f"{_trk_bit}</div>"
        f"<div style='text-align:center'>"
        f"<div style='font-size:9px;color:{hue};letter-spacing:2px'>POWER</div>"
        f"<div style='font-size:46px;font-weight:900;color:{hue};line-height:1'>"
        f"{power if power is not None else '—'}</div></div></div></div>")


def render_for(team_id, gender, season="Current", ident=None):
    """Draw the banner as page chrome from just (team, gender, season).

    The Team Dashboard already holds `scored` / `tracked` / the resolved gate, so
    it calls ``render_banner``. Every OTHER team-scoped page (Schedule, War Room,
    Whiteboard, Event Editor) holds none of that, and making each one assemble it
    by hand is how four subtly different headers get born. This resolves the lot
    once, behind the page caches the dashboard already warms.

    THE GATE IS NOT OPTIONAL HERE. Tracked rank and tracked-game counts are
    co-op depth: a Paid coach may see them for their own team always, for another
    team only when both sides are in the pool, and for any team in a PAST season
    because a finished season is an open archive. That resolution belongs to
    ``entitlement.tracked_gate`` and this function asks it rather than deciding.
    Returns False (drawing nothing) when the team can't be resolved.
    """
    if not team_id:
        return False
    import helpers.team_ratings as TR
    import helpers.entitlement as ENT
    scored = _scored_pool(gender, season)
    row = scored.get(team_id)
    if not row:
        return False
    tracked = _tracked_pool(gender, season)
    if ident is None:
        try:
            import helpers.auth as AUTH
            ident = AUTH.current_user()
        except Exception:
            ident = None
    visible, _lock = ENT.tracked_gate(ident, team_id, team_id in tracked,
                                      season=season)
    st.markdown(
        _banner_html(
            team_id=team_id, gender=gender, season=season,
            power=row.get("Power"), rank=row.get("Rank"), pool_n=len(scored),
            wins=row.get("W", 0), losses=row.get("L", 0),
            mov=row.get("MOV") or 0.0, games=row.get("GP"),
            has_tracked=visible, trk=tracked.get(team_id),
            trk_pool_n=len(tracked),
        ),
        unsafe_allow_html=True)
    return True


def render_next_game_strip(ctx):
    """One card composing the next game's prep reads (§24 quick-hit): opponent,
    the model's line, the rest edge, and the crew outlook when officials are
    assigned. Every read exists elsewhere (predictor, fatigue, ref_tendencies) —
    this puts them together at the moment of preparation. Display-only; nothing
    folds into the spread (real-numbers rule). Renders nothing off-season or
    when no game is scheduled."""
    ng = _next_game(ctx.team_id, getattr(ctx, "season", "Current"))
    if not ng:
        return
    import helpers.predictor as PRED
    import helpers.fatigue as FT
    at_home = ng["team1_id"] == ctx.team_id
    oid = ng["team2_id"] if at_home else ng["team1_id"]
    opp = ng["n2"] if at_home else ng["n1"]
    rows = []
    try:
        pred = PRED.predict_game(ctx.team_id, oid, scored=ctx.scored,
                                 tracked=ctx.tracked,
                                 home=(ctx.team_id if at_home else oid))
    except Exception:
        pred = None
    if pred:
        rows.append(("Model line",
                     f"{pred['pf_a']:.0f}-{pred['pf_b']:.0f} · "
                     f"{pred['win_prob_a'] * 100:.0f}% win"))
    ra = FT.rest_on_date(ctx.team_id, ng["date"])
    rb = FT.rest_on_date(oid, ng["date"])
    if ra is not None and rb is not None:
        edge = ("even rest" if ra == rb
                else "you come in fresher" if ra > rb
                else "they come in fresher")
        rows.append(("Rest", f"you {ra}d · them {rb}d — {edge}"))
    refs = [r["official_id"] for r in query(
        "SELECT official_id FROM game_lineup_officials WHERE game_id=?",
        (ng["id"],))]
    if refs:
        try:
            import helpers.ref_tendencies as RTD
            co = RTD.crew_outlook(refs, gender=ctx.gender)
            if co:
                rows.append(("Crew", co["summary"]))
        except Exception:
            pass
    if not rows:
        return
    body = "".join(_kv(k, v) for k, v in rows)
    hdr = _zone_hdr(f"Next game — {'vs' if at_home else '@'} {opp} · {ng['date']}")
    st.markdown(
        f"<div style='background:var(--card-bg);border:1px solid "
        f"var(--card-border);border-left:3px solid var(--accent);"
        f"border-radius:10px;padding:10px 14px;margin-bottom:10px'>"
        f"{hdr}{body}</div>", unsafe_allow_html=True)


def render_header(ctx):
    """The dense team header: banner · glance strip · identity/engine/verdict."""
    render_banner(ctx)
    rec = ctx.rec
    import helpers.seasons as _SEAS
    _season = getattr(ctx, "season", "Current")
    fm = _form(ctx.gender, _season).get(ctx.team_id, {})

    # ── glance strip — most-distinctive stats vs the league (tracked only) ───
    if getattr(ctx, "has_tracked", False) and getattr(ctx, "team_id", None):
        _gl = _glance(ctx.gender, ctx.team_id, _season)
        if _gl:
            _tiles = ""
            for _gt in _gl:
                _clr = ("var(--good)" if _gt["good"] else "var(--bad)") \
                    if _gt["good"] is not None else "#58a6ff"
                _tiles += (
                    f"<div style='background:var(--card-bg-2);border:1px solid var(--track);"
                    f"border-left:3px solid {_clr};border-radius:8px;"
                    f"padding:8px 11px'>"
                    f"<div style='font-size:11px;color:var(--subtext)'>{_gt['label']}</div>"
                    f"<div style='font-size:18px;font-weight:700;color:var(--text)'>"
                    f"{_gt['value']}</div>"
                    f"<div style='font-size:11px;color:{_clr};font-weight:600'>"
                    f"{_ORD(_gt['pct'])} pct</div>"
                    f"<div style='font-size:11px;color:var(--subtext);margin-top:2px'>"
                    f"{_gt['tag']}</div></div>")
            st.markdown(
                "<div style='display:grid;grid-template-columns:"
                "repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:10px'>"
                + _tiles + "</div>", unsafe_allow_html=True)

    z1, z2, z3 = st.columns(3)

    # ── zone A · identity ─────────────────────────────────────────────────────
    with z1:
        _ranks = sorted(ctx.scored.items(), key=lambda kv: kv[1].get("Rank", 1e9))
        _top10 = {t for t, _ in _ranks[:10]}
        _top25 = {t for t, _ in _ranks[:25]}

        def _rec_vs(idset):
            wv = lv = 0
            for gg in ctx.log:
                if gg["opp_id"] in idset and gg["opp_id"] != ctx.team_id:
                    wv, lv = (wv + 1, lv) if gg["won"] else (wv, lv + 1)
            return wv, lv

        _w10, _l10 = _rec_vs(_top10)
        _w25, _l25 = _rec_vs(_top25)
        html = _zone_hdr("Identity")
        html += _kv("Points for / against",
                    f"{rec['PF_pg']:.0f} / {rec['PA_pg']:.0f}")
        html += _kv("vs Top 10 · Top 25", f"{_w10}-{_l10} · {_w25}-{_l25}")
        # game-type records (only when types are actually set)
        _bytype = {}
        for r in query("""SELECT game_type, team1_id, home_score, away_score
                          FROM games WHERE (team1_id=? OR team2_id=?)
                            AND home_score IS NOT NULL
                            AND away_score IS NOT NULL AND season=?""",
                       (ctx.team_id, ctx.team_id, _season)):
            won = ((r["home_score"] > r["away_score"])
                   if r["team1_id"] == ctx.team_id
                   else (r["away_score"] > r["home_score"]))
            d = _bytype.setdefault(r["game_type"] or "Regular", [0, 0])
            d[0 if won else 1] += 1
        if _bytype and (len(_bytype) > 1 or "Regular" not in _bytype):
            for k, v in sorted(_bytype.items()):
                html += _kv(k, f"{v[0]}-{v[1]}")
        _rs = _rest(ctx.team_id)
        if _rs and _rs["buckets"]:
            for b in _rs["buckets"]:
                if b["key"] in ("b2b", "short") and b["gp"] >= 2:
                    html += _kv(b["label"],
                                f"{b['w']}-{b['l']} ({b['delta']:+.1f} MOV)",
                                vc="var(--good)" if b["delta"] > 0 else "var(--bad)")
            if _rs.get("heavy") and _rs["heavy"]["gp"] >= 2:
                hv = _rs["heavy"]
                html += _kv("3+ games in 7 days",
                            f"{hv['w']}-{hv['l']} ({hv['delta']:+.1f} MOV)",
                            vc="var(--good)" if hv["delta"] > 0 else "var(--bad)")
        st.markdown(html, unsafe_allow_html=True)

    # ── zone B · engine (tracked possession economy) ──────────────────────────
    with z2:
        html = _zone_hdr("Engine — per 100 possessions")
        if ctx.has_tracked:
            summ = ctx.summ or {}
            html += _kv("Off / Def rating",
                        f"{summ.get('ORtg', 0):.1f} / {summ.get('DRtg', 0):.1f}")
            html += _kv("Net rating", f"{summ.get('NetRtg', 0):+.1f}",
                        vc="var(--good)" if summ.get("NetRtg", 0) >= 0 else "var(--bad)")
            html += _kv("Pace (poss/g)", f"{summ.get('POSS_pg', 0):.1f}")
            _aj = _adj_shoot(ctx.gender, _season).get(ctx.team_id)
            if _aj:
                html += _kv("Adj eFG% (off / def)",
                            f"{_aj['AdjeFG'] * 100:.1f} / {_aj['AdjoeFG'] * 100:.1f}")
            # team-level pool: the season-scoped tracked ids from the bundle when
            # present (Team Dashboard); Rankings' lean ctx has no bundle → None =
            # current default.
            _bd = getattr(ctx, "bundle", None)
            _tids = tuple(_bd["tracked_ids"]) if _bd else None
            _lg = _ledger(ctx.team_id, _tids)
            if _lg and _lg.get("outcomes"):
                _mix = {o["key"]: o["pct"] for o in _lg["outcomes"]}
                html += _kv("Possessions scored",
                            f"{_mix.get('scored', 0) * 100:.0f}%")
                html += _kv("Empty · turned over",
                            f"{_mix.get('lost', 0) * 100:.0f}% · "
                            f"{_mix.get('turnover', 0) * 100:.0f}%")
            st.markdown(html, unsafe_allow_html=True)
        else:
            html += ("<div style='font-size:12px;color:var(--subtext)'>Track games to "
                     "unlock the possession economy — efficiency, adjusted "
                     "shooting and where possessions go.</div>")
            st.markdown(html, unsafe_allow_html=True)

    # ── zone C · verdict (model reads, labeled as such) ───────────────────────
    with z3:
        html = _zone_hdr("Verdict — model reads")
        if fm:
            html += _kv("Pythagorean W-L",
                        f"{fm['Pyth_W']:.1f}-{fm['Pyth_L']:.1f}")
            _lw = fm.get("Luck_wins", 0)
            html += _kv("Luck (wins vs expected)", f"{_lw:+.1f}",
                        vc="var(--good)" if _lw >= 0 else "var(--bad)")
            _md = fm.get("mom_delta")
            if _md is not None:
                html += _kv("Momentum (L5 MOV − season)", f"{_md:+.1f}",
                            vc="var(--good)" if _md >= 0 else "var(--bad)")
            _cw, _cl = fm.get("close_w", 0), fm.get("close_l", 0)
            if _cw + _cl:
                html += _kv("Close games (≤5)", f"{_cw}-{_cl}")
        if ctx.rank_info.get("tracked"):
            _trk = ctx.rank_info["tracked"]
            html += _kv("Tracked rank", f"#{_trk['rank']} of {_trk['of']}")
        _ng = _next_game(ctx.team_id, _season)
        if _ng:
            import helpers.predictor as PRED
            at_home = _ng["team1_id"] == ctx.team_id
            oid = _ng["team2_id"] if at_home else _ng["team1_id"]
            opp = _ng["n2"] if at_home else _ng["n1"]
            pred = PRED.predict_game(ctx.team_id, oid, scored=ctx.scored,
                                     tracked=ctx.tracked,
                                     home=(ctx.team_id if at_home else oid))
            if pred:
                html += _kv(f"Next: {'vs' if at_home else '@'} {opp}",
                            f"{pred['pf_a']:.0f}-{pred['pf_b']:.0f} · "
                            f"{pred['win_prob_a'] * 100:.0f}%")
        st.markdown(html, unsafe_allow_html=True)
    st.caption("Pythagorean / luck / momentum are results-math; the next-game "
               "line is the opponent-adjusted model with home court at the "
               "actual venue. Every other number is measured play.")
