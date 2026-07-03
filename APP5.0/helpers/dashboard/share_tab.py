"""
dashboard/share_tab.py — the Team Dashboard "Share" tab.

Premade social-media graphics: pick a card (game result / season record /
last-N stretch), the data drops into the branded 1080×1080 template
(helpers/social_cards.py), preview it and download the PNG — post-ready, no
design work. Own-team surface: the cards exist to post YOUR team, and the
top-performer / best-player panels aggregate tracked events at full depth, so
the tab only renders where the viewer has full-depth rights on the dashboard
team (own team / admin — ctx.vis_key is None). See helpers/dashboard/__init__.py
for the ctx convention.
"""
from __future__ import annotations

import streamlit as st

import helpers.social_cards as SCARD


@st.cache_data(ttl=600, show_spinner=False)
def _card(kind, team_id, gender, arg=None):
    """Cached PNG bytes for one card. `arg` = game_id (game) or n (last-N)."""
    if kind == "game":
        return SCARD.game_result_png(arg, team_id)
    if kind == "season":
        return SCARD.season_record_png(team_id, gender)
    return SCARD.last_n_png(team_id, gender, n=arg or 5)


@st.cache_data(ttl=600, show_spinner=False)
def _games(team_id):
    return SCARD._team_games(team_id)


@st.fragment
def render(ctx):
    st.caption("Post-ready graphics — pick a card, the numbers drop into the "
               "HoopTracks template, download the PNG and post it. Square "
               "1080×1080, sized for Instagram / X / Facebook.")
    if ctx.vis_key is not None:
        # league-wide scout on another team's dashboard: the performer panels
        # aggregate full-depth tracked events — own-team / admin surface only.
        st.info("Share cards are built for posting your own team — open your "
                "team's dashboard to generate them.")
        return

    games = _games(ctx.team_id)
    if not games:
        st.info("No finished games yet — share cards need at least one final "
                "score.")
        return

    _slug = "".join(c if c.isalnum() else "_" for c in str(ctx.team_name))
    kind = st.radio("Card", ["Game result", "Season record", "Last X games"],
                    horizontal=True, key="share_kind")

    if kind == "Game result":
        opts = list(reversed(games))          # newest first
        pick = st.selectbox(
            "Game", [g["id"] for g in opts],
            format_func=lambda gid: next(
                (f"{g['date']} — {'W' if g['won'] else 'L'} {g['pf']}–{g['pa']} "
                 f"vs {g['opp']}" for g in opts if g["id"] == gid), str(gid)),
            key="share_game")
        png = _card("game", ctx.team_id, ctx.gender, pick)
        fname = f"{_slug}_final_{pick}.png"
    elif kind == "Season record":
        png = _card("season", ctx.team_id, ctx.gender)
        fname = f"{_slug}_season.png"
    else:
        _max = min(10, len(games))
        if _max > 3:
            n = st.slider("Games in the stretch", 3, _max, min(5, _max),
                          key="share_n")
        else:
            # 3 or fewer finished games — nothing to slide, use them all
            n = _max
            st.caption(f"Stretch = all {n} finished game{'s' if n != 1 else ''} "
                       "so far.")
        png = _card("lastn", ctx.team_id, ctx.gender, n)
        fname = f"{_slug}_last{n}.png"

    if not png:
        st.info("Not enough data for this card yet.")
        return
    c1, c2 = st.columns([2, 1])
    with c1:
        st.image(png, width="stretch")
    with c2:
        st.download_button("⬇ Download PNG", png, file_name=fname,
                           mime="image/png", type="primary",
                           key=f"share_dl_{kind}")
        st.caption("1080×1080 PNG — drop it straight into a post. Cards "
                   "refresh as new results land (10-min cache).")
