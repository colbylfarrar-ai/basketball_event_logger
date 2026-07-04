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
    _tpids = [k for k in _ppool if _ppool[k]["team_id"] == ctx.team_id]
    if not _tpids:
        st.info(f"No rated players for **{ctx.team['name']}** yet — track a game in "
                "the Game Tracker.")
    else:
        _porder = sorted(_tpids, key=lambda k: (_ppool[k]["Rank"] or 1e9))
        _plabels = [f"#{_ppool[k]['Rank']}  {_ppool[k]['name']}"
                    f"  ·  {_ppool[k]['class']}" for k in _porder]
        _ppick = st.selectbox("Player", range(len(_porder)),
                              format_func=lambda i: _plabels[i], key="td_prof_pick")
        _ppid = _porder[_ppick]
        _zs, _zg, _hs = ctx.pp_zone_tables()
        ctx.render_profile(_ppool[_ppid], _ppid, _prows, _zs, _zg, _hs)
