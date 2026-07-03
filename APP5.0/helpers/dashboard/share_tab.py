"""
dashboard/share_tab.py — the Team Dashboard "Share" tab.

Premade social-media graphics: pick a card (game result / season record /
selected games), the data drops into the branded 1080×1080 template
(helpers/social_cards.py), preview it and download the PNG — post-ready, no
design work. Own-team surface: the cards exist to post YOUR team, and the
top-performer / best-player panels aggregate tracked events at full depth, so
the tab only renders where the viewer has full-depth rights on the dashboard
team (own team / admin — ctx.vis_key is None). See helpers/dashboard/__init__.py
for the ctx convention.

Team colours for the head-to-head game card are stored GLOBALLY (per team,
key ``team_color:<tid>`` — cosmetic, shared across coaches), defaulting to a
stable per-team colour until a coach picks one.
"""
from __future__ import annotations

import streamlit as st

import helpers.social_cards as SCARD
import helpers.settings_utils as SU


def _team_color(tid):
    return SU.get_setting(f"team_color:{tid}", SCARD.default_team_color(tid))


@st.cache_data(ttl=600, show_spinner=False)
def _card_game(game_id, team_id, ca, cb, quarters, gender):
    return SCARD.game_result_png(game_id, team_id, color_a=ca, color_b=cb,
                                 show_quarters=quarters, gender=gender)


@st.cache_data(ttl=600, show_spinner=False)
def _card_season(team_id, gender):
    return SCARD.season_record_png(team_id, gender)


@st.cache_data(ttl=600, show_spinner=False)
def _card_games(team_id, gender, game_ids, title):
    return SCARD.games_png(team_id, gender, game_ids=list(game_ids),
                           title=title or None)


@st.cache_data(ttl=600, show_spinner=False)
def _games(team_id):
    return SCARD._team_games(team_id)


def _dl(png, fname, key):
    c1, c2 = st.columns([2, 1])
    with c1:
        st.image(png, width="stretch")
    with c2:
        st.download_button("⬇ Download PNG", png, file_name=fname,
                           mime="image/png", type="primary", key=key)
        st.caption("1080×1080 PNG — drop it straight into a post. Cards refresh "
                   "as new results land (10-min cache).")


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
    _lbl = {gm["id"]: f"{gm['date']} — {'W' if gm['won'] else 'L'} "
                      f"{gm['pf']}–{gm['pa']} vs {gm['opp']}" for gm in games}
    kind = st.radio("Card", ["Game result", "Season record", "Selected games"],
                    horizontal=True, key="share_kind")

    if kind == "Game result":
        newest = list(reversed(games))
        pick = st.selectbox("Game", [g["id"] for g in newest],
                            format_func=lambda gid: _lbl.get(gid, str(gid)),
                            key="share_game")
        gm = next(g for g in games if g["id"] == pick)
        opp_id = gm["opp_id"]

        cc1, cc2, cc3 = st.columns([1, 1, 1])
        ca = cc1.color_picker(f"{ctx.team_name} colour", _team_color(ctx.team_id),
                              key="share_ca")
        cb = cc2.color_picker(f"{gm['opp']} colour", _team_color(opp_id),
                              key="share_cb")
        quarters = cc3.toggle("Quarter-by-quarter", value=False, key="share_qtr",
                              help="Add the per-quarter scoring line under the "
                                   "score (needs a tracked game).")
        # persist any change (global, per team)
        if ca != _team_color(ctx.team_id):
            SU.set_setting(f"team_color:{ctx.team_id}", ca)
        if cb != _team_color(opp_id):
            SU.set_setting(f"team_color:{opp_id}", cb)

        png = _card_game(pick, ctx.team_id, ca, cb, quarters, ctx.gender)
        if png and quarters and not gm["tracked"]:
            st.caption("This game isn't tracked play-by-play — the quarter line "
                       "will be empty. Track it in the Game Tracker for the split.")
        fname = f"{_slug}_final_{pick}.png"
        if not png:
            st.info("Not enough data for this card yet.")
            return
        _dl(png, fname, "share_dl_game")

    elif kind == "Season record":
        png = _card_season(ctx.team_id, ctx.gender)
        if not png:
            st.info("Not enough data for this card yet.")
            return
        _dl(png, f"{_slug}_season.png", "share_dl_season")

    else:   # Selected games — pick any set from the schedule
        st.caption("Pick the games to feature — every one you select lands on the "
                   "card (newest first).")
        title = st.text_input(
            "Card title", value="", max_chars=40, key="share_title",
            placeholder="e.g. Catoosa Tournament · Road to State",
            help="Your own headline for the set. Leave blank for a game count.")
        default = [g["id"] for g in games[-5:]]
        sel = st.multiselect("Games", [g["id"] for g in reversed(games)],
                             default=default,
                             format_func=lambda gid: _lbl.get(gid, str(gid)),
                             key="share_sel")
        if not sel:
            st.info("Select at least one game.")
            return
        png = _card_games(ctx.team_id, ctx.gender, tuple(sorted(sel)),
                          title.strip())
        if not png:
            st.info("Not enough data for this card yet.")
            return
        _dl(png, f"{_slug}_games.png", "share_dl_games")
