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
    # Tier gate: the full profile card is event-derived (ratings, shot charts,
    # signature metrics). ctx.has_tracked folds in the per-team entitlement, so a
    # Free / non-pool viewer gets a lock — box-score lines live on the Players tab.
    if not ctx.has_tracked:
        st.info("🔒 The player profile — ratings, shot charts, signature metrics "
                "and the scouting report — is tracked-analytics depth, a **Paid** "
                "feature. Per-game box lines are on the **Players** tab. Upgrade "
                "to unlock the full card.")
        return
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
