"""
dashboard/profile_tab.py — the Team Dashboard "Player Profile" tab.

One player's full card — ratings, signature metrics, shot chart, game log,
league percentiles and a scouting report. The heavy renderer
(_render_profile) and the league-wide zone tables stay on the page and ride
in as ctx callables. Extracted from pages/6_Team_Dashboard.py (see
helpers/dashboard/__init__.py for the ctx convention).
"""
from __future__ import annotations

import streamlit as st

from database.db import query
import helpers.seasons as SEAS


@st.fragment
def render(ctx):
    st.caption("One player's full card — ratings, signature metrics, shot chart, "
               "game log, league percentiles and a scouting report. Ranks and "
               "percentiles are vs the whole league player pool.")
    # Tier gate — two different reasons the card can't show, with honest copy:
    #   tracked_lock → a REAL entitlement lock (Free viewer / non-pooled team on
    #                  the current season) → the Paid/co-op message.
    #   no lock      → simply no tracked data for this view yet (a brand-new
    #                  season with no archive to fall back on) → a neutral note,
    #                  never a misleading "Paid" lock for an entitled viewer.
    # ctx.fallback_note = the page fell back to LAST season's pool (empty current
    # season) — surfaced so the card is never mistaken for this season's data.
    if not ctx.has_tracked:
        _lock = getattr(ctx, "tracked_lock", None)
        if _lock:
            st.info(_lock)
        else:
            st.info("No tracked games for this view yet — player profiles are "
                    "built from play-by-play. Track a game in the Game Tracker "
                    "and the full card (ratings, shot charts, signature metrics) "
                    "lights up here.")
        return
    _note = getattr(ctx, "fallback_note", None)
    if _note:
        st.info(f"🗄️ {_note}")
    _ppool = ctx.ptable_full(ctx.gender)
    _prows = sorted(_ppool.values(), key=lambda r: (r["Rank"] or 1e9))
    # Selector list: for the live season (and the last-season fallback) it is the
    # CURRENT roster — every active player, rated or not — so new kids show up
    # before their first tracked game. An explicitly picked archive keeps the
    # season pool (graduated players must stay pickable there).
    _cur_view = (SEAS.is_current(getattr(ctx, "season", None))
                 or bool(getattr(ctx, "fallback_note", None)))
    if _cur_view:
        _roster = query("SELECT id, name, number FROM players WHERE team_id=? "
                        "AND archived=0 ORDER BY number", (ctx.team_id,))
        # Identity bridge: after a New-Season rollover a returning player is a
        # brand-new players.id, so their row is never in a past season's pool
        # directly — resolve through the person key (COALESCE(identity_id, id))
        # to that season's row instead. Team-agnostic, so a linked transfer's
        # old-school season shows too (labeled with the old team).
        _pk = {r["id"]: r["pk"] for r in
               query("SELECT id, COALESCE(identity_id, id) pk FROM players")}
        _pool_by_pk = {}
        for k in _ppool:
            _pool_by_pk.setdefault(_pk.get(k, k), k)
        _entries = []                     # (roster row, pool pid|None, linked?)
        for p in _roster:
            if p["id"] in _ppool:
                _entries.append((p, p["id"], False))
            else:
                _lk = _pool_by_pk.get(_pk.get(p["id"], p["id"]))
                _entries.append((p, _lk, _lk is not None))
        _rated = sorted([e for e in _entries if e[1] is not None],
                        key=lambda e: (_ppool[e[1]]["Rank"] or 1e9))
        _unrated = [e[0] for e in _entries if e[1] is None]

        def _lab(e):
            p, k, linked = e
            lab = (f"#{_ppool[k]['Rank']}  {p['name']}"
                   f"  ·  {_ppool[k]['class']}")
            if linked:
                lab += "  ·  last season"
                if _ppool[k]["team_id"] != ctx.team_id:
                    lab += f" ({_ppool[k]['team']})"
            return lab

        _porder = [e[1] for e in _rated] + [p["id"] for p in _unrated]
        _plabels = ([_lab(e) for e in _rated]
                    + [f"#{p['number']}  {p['name']}  ·  no tracked data yet"
                       for p in _unrated])
    else:
        _tpids = [k for k in _ppool if _ppool[k]["team_id"] == ctx.team_id]
        _porder = sorted(_tpids, key=lambda k: (_ppool[k]["Rank"] or 1e9))
        _plabels = [f"#{_ppool[k]['Rank']}  {_ppool[k]['name']}"
                    f"  ·  {_ppool[k]['class']}" for k in _porder]
    if not _porder:
        st.info(f"No players for **{ctx.team['name']}** yet — add them in the "
                "Input Hub, then track a game in the Game Tracker.")
    else:
        _ppick = st.selectbox("Player", range(len(_porder)),
                              format_func=lambda i: _plabels[i], key="td_prof_pick")
        _ppid = _porder[_ppick]
        if _ppid not in _ppool:
            st.info("No tracked data for this player yet — their full card "
                    "(ratings, shot chart, signature metrics) lights up once "
                    "they appear in a tracked game. Played last season? Link "
                    "them to their past-season identity (New Season → "
                    "Returning players) and that card shows here.")
        else:
            _zs, _zg, _hs = ctx.pp_zone_tables()
            ctx.render_profile(_ppool[_ppid], _ppid, _prows, _zs, _zg, _hs)
