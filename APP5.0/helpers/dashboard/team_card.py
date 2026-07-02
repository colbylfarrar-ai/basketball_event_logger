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


# ── cached data the header needs beyond ctx ─────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _glance(gender, team_id):
    import helpers.insights_team as INT
    return INT.team_glance(gender, team_id)


@st.cache_data(ttl=600, show_spinner=False)
def _form(gender):
    import helpers.league_analytics as LA
    return LA.team_form_stats(gender=gender)


@st.cache_data(ttl=600, show_spinner=False)
def _rest(team_id):
    import helpers.fatigue as FT
    try:
        return FT.team_rest_splits(team_id)
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _adj_shoot(gender):
    import helpers.adj_efficiency as AE
    try:
        return AE.adjusted_shooting(gender)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _ledger(team_id):
    import helpers.possession_value as PV
    try:
        return PV.possession_ledger(team_id)
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _next_game(team_id):
    """The next scheduled game (score-less, today or later) or None."""
    from datetime import datetime
    rows = query("""
        SELECT g.id, g.date, g.team1_id, g.team2_id, t1.name n1, t2.name n2
        FROM games g JOIN teams t1 ON t1.id = g.team1_id
                     JOIN teams t2 ON t2.id = g.team2_id
        WHERE (g.team1_id = ? OR g.team2_id = ?)
          AND (g.home_score IS NULL OR g.away_score IS NULL)
          AND g.date >= ?
        ORDER BY g.date LIMIT 1""",
        (team_id, team_id, datetime.now().strftime("%Y-%m-%d")))
    return dict(rows[0]) if rows else None


# ── tiny html primitives (same visual language as the player card) ──────────────
def _kv(k, v, vc="#f0f6fc"):
    return (f"<div style='display:flex;justify-content:space-between;"
            f"font-size:12px;padding:2px 0'><span style='color:#8b949e'>{k}"
            f"</span><span style='color:{vc};font-weight:600'>{v}</span></div>")


def _zone_hdr(t):
    return (f"<div style='font-size:10px;color:#8b949e;text-transform:uppercase;"
            f"letter-spacing:1.5px;margin:0 0 4px'>{t}</div>")


def render_header(ctx):
    """The dense team header: banner · glance strip · identity/engine/verdict."""
    sc = ctx.sc_score or {}
    rec = ctx.rec
    power = sc.get("Power")
    hue, tlabel = _tier(power)
    _trow = query("SELECT name, class FROM teams WHERE id=?", (ctx.team_id,))
    tname = _trow[0]["name"] if _trow else "Team"
    _cls = (_trow[0]["class"] if _trow else "") or ""
    fm = _form(ctx.gender).get(ctx.team_id, {})
    _stk = (f"{fm['streak_type']}{fm['streak_len']}"
            if fm.get("streak_type") and fm.get("streak_len") else "")

    # ── banner — the player-card banner grammar, team-sized ──────────────────
    st.markdown(
        f"<div style='background:linear-gradient(135deg,#080c14,#0d1117 55%,#111827);"
        f"border:1px solid {hue}66;border-radius:18px;padding:18px 24px;"
        f"margin-bottom:12px;position:relative;overflow:hidden'>"
        f"<div style='display:flex;align-items:center;gap:22px'>"
        f"<div style='flex:1'>"
        f"<div style='font-size:28px;font-weight:900;color:#f0f6fc;line-height:1.05'>"
        f"{tname}</div>"
        f"<div style='font-size:13px;color:#8b949e;margin-top:4px'>"
        f"<span style='color:{hue};font-weight:700;letter-spacing:1px'>{tlabel}</span>"
        f"{' · ' + _cls if _cls else ''} · {rec['wins']}-{rec['losses']}"
        f"{' · ' + _stk if _stk else ''} · MOV {rec['MOV']:+.1f} · "
        f"#{sc.get('Rank', '—')} of {len(ctx.scored)}</div></div>"
        f"<div style='text-align:center'>"
        f"<div style='font-size:9px;color:{hue};letter-spacing:2px'>POWER</div>"
        f"<div style='font-size:46px;font-weight:900;color:{hue};line-height:1'>"
        f"{power if power is not None else '—'}</div></div></div></div>",
        unsafe_allow_html=True)

    # ── glance strip — most-distinctive stats vs the league (tracked only) ───
    if getattr(ctx, "has_tracked", False) and getattr(ctx, "team_id", None):
        _gl = _glance(ctx.gender, ctx.team_id)
        if _gl:
            _tiles = ""
            for _gt in _gl:
                _clr = ("#3fb950" if _gt["good"] else "#e74c3c") \
                    if _gt["good"] is not None else "#58a6ff"
                _tiles += (
                    f"<div style='background:#0d1117;border:1px solid #21262d;"
                    f"border-left:3px solid {_clr};border-radius:8px;"
                    f"padding:8px 11px'>"
                    f"<div style='font-size:11px;color:#8b949e'>{_gt['label']}</div>"
                    f"<div style='font-size:18px;font-weight:700;color:#f0f6fc'>"
                    f"{_gt['value']}</div>"
                    f"<div style='font-size:11px;color:{_clr};font-weight:600'>"
                    f"{_gt['pct']}th pct</div>"
                    f"<div style='font-size:11px;color:#8b949e;margin-top:2px'>"
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
                            AND away_score IS NOT NULL AND season='Current'""",
                       (ctx.team_id, ctx.team_id)):
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
                                vc="#3fb950" if b["delta"] > 0 else "#e74c3c")
            if _rs.get("heavy") and _rs["heavy"]["gp"] >= 2:
                hv = _rs["heavy"]
                html += _kv("3+ games in 7 days",
                            f"{hv['w']}-{hv['l']} ({hv['delta']:+.1f} MOV)",
                            vc="#3fb950" if hv["delta"] > 0 else "#e74c3c")
        st.markdown(html, unsafe_allow_html=True)

    # ── zone B · engine (tracked possession economy) ──────────────────────────
    with z2:
        html = _zone_hdr("Engine — per 100 possessions")
        if ctx.has_tracked:
            summ = ctx.summ or {}
            html += _kv("Off / Def rating",
                        f"{summ.get('ORtg', 0):.1f} / {summ.get('DRtg', 0):.1f}")
            html += _kv("Net rating", f"{summ.get('NetRtg', 0):+.1f}",
                        vc="#3fb950" if summ.get("NetRtg", 0) >= 0 else "#e74c3c")
            html += _kv("Pace (poss/g)", f"{summ.get('POSS_pg', 0):.1f}")
            _aj = _adj_shoot(ctx.gender).get(ctx.team_id)
            if _aj:
                html += _kv("Adj eFG% (off / def)",
                            f"{_aj['AdjeFG'] * 100:.1f} / {_aj['AdjoeFG'] * 100:.1f}")
            _lg = _ledger(ctx.team_id)
            if _lg and _lg.get("outcomes"):
                _mix = {o["key"]: o["pct"] for o in _lg["outcomes"]}
                html += _kv("Possessions scored",
                            f"{_mix.get('scored', 0) * 100:.0f}%")
                html += _kv("Empty · turned over",
                            f"{_mix.get('lost', 0) * 100:.0f}% · "
                            f"{_mix.get('turnover', 0) * 100:.0f}%")
            st.markdown(html, unsafe_allow_html=True)
        else:
            html += ("<div style='font-size:12px;color:#8b949e'>Track games to "
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
                        vc="#3fb950" if _lw >= 0 else "#e74c3c")
            _md = fm.get("mom_delta")
            if _md is not None:
                html += _kv("Momentum (L5 MOV − season)", f"{_md:+.1f}",
                            vc="#3fb950" if _md >= 0 else "#e74c3c")
            _cw, _cl = fm.get("close_w", 0), fm.get("close_l", 0)
            if _cw + _cl:
                html += _kv("Close games (≤5)", f"{_cw}-{_cl}")
        if ctx.rank_info.get("tracked"):
            _trk = ctx.rank_info["tracked"]
            html += _kv("Tracked rank", f"#{_trk['rank']} of {_trk['of']}")
        _ng = _next_game(ctx.team_id)
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
