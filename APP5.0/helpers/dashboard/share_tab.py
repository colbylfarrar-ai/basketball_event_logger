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
import helpers.seasons as SEAS


def _team_color(tid):
    return SU.get_setting(f"team_color:{tid}", SCARD.default_team_color(tid))


# `season` on each wrapper scopes the card to the dashboard's selected season
# ('Current' = live default, byte-identical) — an archive view builds cards from
# that season's games, ranks and player table (program-history posts).
@st.cache_data(ttl=600, show_spinner=False)
def _card_game(game_id, team_id, ca, cb, quarters, gender, title, bg,
               logo_a, logo_b, season="Current"):
    return SCARD.game_result_png(game_id, team_id, color_a=ca, color_b=cb,
                                 show_quarters=quarters, gender=gender,
                                 title=title or None, bg=bg,
                                 logo_a=logo_a, logo_b=logo_b, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _card_game_manual(team_id, b_id, a_pts, b_pts, date, location, ca, cb,
                      gender, title, bg, logo_a, logo_b, season="Current"):
    """Coach-typed final-score card — no DB game behind it (a scrimmage, a game
    from before tracking, a jamboree). Same template as the real game card."""
    return SCARD.game_result_png(
        0, team_id, color_a=ca, color_b=cb, gender=gender,
        title=title or None, bg=bg, logo_a=logo_a, logo_b=logo_b, season=season,
        manual={"b_id": b_id, "a_pts": a_pts, "b_pts": b_pts,
                "date": date, "location": location})


@st.cache_data(ttl=600, show_spinner=False)
def _card_season(team_id, gender, bg, season="Current"):
    return SCARD.season_record_png(team_id, gender, bg=bg, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _card_games(team_id, gender, game_ids, title, bg, season="Current"):
    return SCARD.games_png(team_id, gender, game_ids=list(game_ids),
                           title=title or None, bg=bg, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _games(team_id, season="Current"):
    return SCARD._team_games(team_id, season=season)


@st.cache_data(ttl=600, show_spinner=False)
def _card_spotlight(pid, mode, n, game_id, bg, game_ids=None, label=None):
    return SCARD.player_spotlight_png(pid, mode=mode, n=n, game_id=game_id,
                                      bg=bg, game_ids=game_ids, label=label)


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

    _szn = getattr(ctx, "season", "Current")
    games = _games(ctx.team_id, _szn)

    _slug = "".join(c if c.isalnum() else "_" for c in str(ctx.team_name))
    _lbl = {gm["id"]: f"{gm['date']} — {'W' if gm['won'] else 'L'} "
                      f"{gm['pf']}–{gm['pa']} vs {gm['opp']}" for gm in games}
    kind = st.radio("Card", ["Game result", "Custom game", "Season record",
                             "Selected games", "Player spotlight"],
                    horizontal=True, key="share_kind")

    # Custom game needs no DB game — everything else reads the season's results.
    if kind not in ("Custom game", "Player spotlight") and not games:
        st.info("No finished games yet — these cards need at least one final "
                "score. (The **Custom game** card works without one: type the "
                "matchup and score yourself.)")
        return

    if kind == "Custom game":
        # Coach-typed final score — a scrimmage, a jamboree, a game from before
        # tracking. Same branded template as the real game card; nothing is saved
        # to the games table (want it in the stats too? enter it in the Input Hub).
        st.caption("Type the matchup and score yourself — for scrimmages, "
                   "jamborees or games that aren't in the app. The card uses the "
                   "same template; nothing is added to your schedule or stats.")
        from database.db import query as _q
        _opps = {r["id"]: r["name"] for r in _q(
            "SELECT id, name FROM teams WHERE id != ? AND gender = "
            "(SELECT gender FROM teams WHERE id=?) ORDER BY name",
            (ctx.team_id, ctx.team_id))}
        if not _opps:
            st.info("Add at least one other team (Input Hub → Teams) to pick an "
                    "opponent.")
            return
        mc1, mc2, mc3 = st.columns([2, 1, 1])
        _opp = mc1.selectbox("Opponent", list(_opps),
                             format_func=lambda t: _opps[t], key="share_cust_opp")
        _apts = mc2.number_input(f"{ctx.team_name} score", 0, 200, 60, 1,
                                 key="share_cust_a")
        _bpts = mc3.number_input(f"{_opps[_opp]} score", 0, 200, 50, 1,
                                 key="share_cust_b")
        dc1, dc2 = st.columns([1, 2])
        _cdate = dc1.date_input("Date", key="share_cust_date")
        _cloc = dc2.text_input("Location (optional)", value="", max_chars=40,
                               key="share_cust_loc")
        _ctitle = st.text_input(
            "Card headline (optional)", value="", max_chars=60,
            key="share_cust_title",
            placeholder="e.g. Preseason Jamboree · Alumni Night")
        cc1, cc2, cc3 = st.columns(3)
        _cca = cc1.color_picker(f"{ctx.team_name} colour",
                                _team_color(ctx.team_id), key="share_cust_ca")
        _ccb = cc2.color_picker(f"{_opps[_opp]} colour", _team_color(_opp),
                                key="share_cust_cb")
        _cbg = cc3.color_picker("Background", SCARD.BG, key="share_cust_bg")
        lc1, lc2 = st.columns(2)
        _cup_a = lc1.file_uploader(f"{ctx.team_name} logo (optional)",
                                   type=["png", "jpg", "jpeg", "webp"],
                                   key="share_cust_logo_a")
        _cup_b = lc2.file_uploader(f"{_opps[_opp]} logo (optional)",
                                   type=["png", "jpg", "jpeg", "webp"],
                                   key="share_cust_logo_b")
        png = _card_game_manual(
            ctx.team_id, _opp, int(_apts), int(_bpts),
            _cdate.strftime("%Y-%m-%d") if _cdate else "",
            _cloc.strip(), _cca, _ccb, ctx.gender, _ctitle.strip(), _cbg,
            _cup_a.getvalue() if _cup_a else None,
            _cup_b.getvalue() if _cup_b else None, _szn)
        if not png:
            st.info("Could not build the card — check the inputs.")
            return
        _dl(png, f"{_slug}_custom_final.png", "share_dl_custom")

    elif kind == "Game result":
        newest = list(reversed(games))
        pick = st.selectbox("Game", [g["id"] for g in newest],
                            format_func=lambda gid: _lbl.get(gid, str(gid)),
                            key="share_game")
        gm = next(g for g in games if g["id"] == pick)
        opp_id = gm["opp_id"]

        gtitle = st.text_input(
            "Card headline (optional)", value="", max_chars=60,
            key="share_game_title",
            placeholder="e.g. Region Championship · Senior Night",
            help="Your own headline above the score. Leave blank for just the date.")

        cc1, cc2, cc3, cc4 = st.columns([1, 1, 1, 1])
        ca = cc1.color_picker(f"{ctx.team_name} colour", _team_color(ctx.team_id),
                              key="share_ca")
        cb = cc2.color_picker(f"{gm['opp']} colour", _team_color(opp_id),
                              key="share_cb")
        gbg = cc3.color_picker("Background", SCARD.BG, key="share_game_bg")
        quarters = cc4.toggle("Quarter-by-quarter", value=False, key="share_qtr",
                              help="Add the per-quarter scoring line under the "
                                   "score (needs a tracked game).")
        # optional logos — used in-memory only, nothing saved
        lc1, lc2 = st.columns(2)
        up_a = lc1.file_uploader(f"{ctx.team_name} logo (optional)",
                                 type=["png", "jpg", "jpeg", "webp"],
                                 key="share_logo_a")
        up_b = lc2.file_uploader(f"{gm['opp']} logo (optional)",
                                 type=["png", "jpg", "jpeg", "webp"],
                                 key="share_logo_b")
        logo_a = up_a.getvalue() if up_a else None
        logo_b = up_b.getvalue() if up_b else None
        # persist any colour change (global, per team) — logos are NOT saved
        if ca != _team_color(ctx.team_id):
            SU.set_setting(f"team_color:{ctx.team_id}", ca)
        if cb != _team_color(opp_id):
            SU.set_setting(f"team_color:{opp_id}", cb)

        png = _card_game(pick, ctx.team_id, ca, cb, quarters, ctx.gender,
                         gtitle.strip(), gbg, logo_a, logo_b, _szn)
        if png and quarters and not gm["tracked"]:
            st.caption("This game isn't tracked play-by-play — the quarter line "
                       "will be empty. Track it in the Game Tracker for the split.")
        fname = f"{_slug}_final_{pick}.png"
        if not png:
            st.info("Not enough data for this card yet.")
            return
        _dl(png, fname, "share_dl_game")

    elif kind == "Season record":
        sbg = st.color_picker("Background", _team_color(ctx.team_id),
                              key="share_season_bg",
                              help="Defaults to your team colour.")
        png = _card_season(ctx.team_id, ctx.gender, sbg, _szn)
        if not png:
            st.info("Not enough data for this card yet.")
            return
        _dl(png, f"{_slug}_season.png", "share_dl_season")

    elif kind == "Player spotlight":
        # One player's numbers — a season line, the whole career (identity
        # chain), one game, or a hot stretch. Box stats only (real numbers).
        from database.db import query as _q
        # Season-aware roster: an archive view lists THAT season's (archived)
        # roster rows, not the current one — a rollover gives players new ids,
        # so the current roster has no games in a past season.
        if SEAS.is_current(_szn):
            _roster = _q("SELECT id, name, number FROM players WHERE team_id=? "
                         "AND archived=0 ORDER BY number", (ctx.team_id,))
        else:
            _roster = _q("SELECT id, name, number FROM players WHERE team_id=? "
                         "AND archived=1 AND season=? ORDER BY number",
                         (ctx.team_id, _szn))
        if not _roster:
            st.info("No players on this roster for that season — pick another "
                    "season, or add players in the Input Hub." if not
                    SEAS.is_current(_szn) else
                    "No players on the roster yet — add them in the Input Hub.")
            return
        pc1, pc2 = st.columns([2, 2])
        _pid = pc1.selectbox("Player", [r["id"] for r in _roster],
                             format_func=lambda i: next(
                                 f"#{r['number']} {r['name']}" for r in _roster
                                 if r["id"] == i),
                             key="share_spot_pid")
        _mode_lbl = pc2.radio("Scope", ["Season", "Career", "One game",
                                        "Last N games", "Pick games"],
                              horizontal=True, key="share_spot_mode")
        _mode = {"Season": "season", "Career": "career", "One game": "game",
                 "Last N games": "stretch", "Pick games": "picked"}[_mode_lbl]
        _n, _gid, _gids = 5, None, None
        if _mode == "stretch":
            _n = st.slider("Games", 2, 15, 5, key="share_spot_n")
        elif _mode in ("game", "picked", "season"):
            _pg = SCARD._pid_game_rows(_pid)
            if not _pg and _mode != "season":
                st.info("No tracked games for this player yet — this card "
                        "needs play-by-play.")
                return
            _gfmt = {r["game_id"]: f"{r['date']} vs {r['opp']}" for r in _pg}
            if _mode == "game":
                _gid = st.selectbox(
                    "Game", [r["game_id"] for r in reversed(_pg)],
                    format_func=lambda g: _gfmt[g], key="share_spot_gid")
            elif _mode == "picked":
                _sel = st.multiselect(
                    "Games", [r["game_id"] for r in reversed(_pg)],
                    format_func=lambda g: _gfmt[g], key="share_spot_gids",
                    help="Any set — a tournament run, the district slate, "
                         "the games a college coach asked about.")
                if not _sel:
                    st.info("Pick at least one game — the card averages "
                            "whatever you select and lists the games on it.")
                    return
                _gids = tuple(_sel)
            elif _pg:               # season — optional featured-games pick
                _sel = st.multiselect(
                    "Featured games (optional)",
                    [r["game_id"] for r in reversed(_pg)],
                    format_func=lambda g: _gfmt[g], key="share_spot_feat",
                    help="The games listed on the card. Season stats stay "
                         "the full season line; leave empty for the most "
                         "recent five.")
                if _sel:
                    _gids = tuple(_sel)
        _slabel = None
        if _mode == "picked":
            _slabel = st.text_input(
                "Card label (optional)", value="", max_chars=40,
                key="share_spot_label",
                placeholder="e.g. District Tournament Run",
                help="Shown on the card instead of "
                     "“N selected games”.").strip() or None
        _sbg = st.color_picker("Background", _team_color(ctx.team_id),
                               key="share_spot_bg",
                               help="Defaults to your team colour.")
        png = _card_spotlight(_pid, _mode, _n, _gid, _sbg, _gids, _slabel)
        if not png:
            st.info("No games for this player in that scope yet — the card "
                    "needs at least one tracked or entered box.")
            return
        _dl(png, f"{_slug}_spotlight_{_pid}_{_mode}.png", "share_dl_spot")

    else:   # Selected games — pick any set from the schedule
        st.caption("Pick the games to feature — every one you select lands on the "
                   "card (newest first).")
        title = st.text_input(
            "Card title", value="", max_chars=60, key="share_title",
            placeholder="e.g. Catoosa Tournament · Road to State",
            help="Your own headline for the set. Leave blank for a game count.")
        gbg2 = st.color_picker("Background", _team_color(ctx.team_id),
                               key="share_games_bg",
                               help="Defaults to your team colour.")
        default = [g["id"] for g in games[-5:]]
        sel = st.multiselect("Games", [g["id"] for g in reversed(games)],
                             default=default,
                             format_func=lambda gid: _lbl.get(gid, str(gid)),
                             key="share_sel")
        if not sel:
            st.info("Select at least one game.")
            return
        png = _card_games(ctx.team_id, ctx.gender, tuple(sorted(sel)),
                          title.strip(), gbg2, _szn)
        if not png:
            st.info("Not enough data for this card yet.")
            return
        _dl(png, f"{_slug}_games.png", "share_dl_games")
