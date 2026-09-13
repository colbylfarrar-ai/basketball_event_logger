"""
dashboard/sched.py — the Team Dashboard "Schedule" tab.

Record vs every class, the full schedule with the model's retro projections
and film links, the upcoming-games projection table, and any tracked game's
box score on demand. Extracted from pages/6_Team_Dashboard.py (see
helpers/dashboard/__init__.py for the ctx convention).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from database.db import query
from helpers.box_score import render_box_score
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.predictor as PRED
import helpers.resume as RES
import helpers.team_ratings as TR
import helpers.forfeits as FF
from helpers.ui import export_button as _export


@st.cache_data(ttl=600, show_spinner=False)
def _deserved_rows(team_id, gids):
    """{game_id: deserved row} for this team's tracked games — the residual that
    belongs beside the result, not three pages away.

    THE RESIDUAL GOES WHERE THE CLAIM IS. `deserved.py` splits every point of a
    game's margin into volume, quality, making and free throws, it sums to the
    final margin exactly, and until now the only place a coach could read it was
    inside the Insights deck (`insights_deep.py:756`) — a different page from the
    one showing the score it disagrees with. Savant's xBA is not powerful because
    it exists; it is powerful because it sits in the same ROW as BA.

    THE COST IS WHY THIS IS CACHED AND SCOPED. It is one event pass over this
    team's tracked games (not the league's), keyed on the game-id tuple, behind
    the same 600s TTL as every other read on this tab. The Schedule view is one
    of the cheap ones and it must stay that way — `THE_SICKO_BOOK` §14's second
    rule is that cost must not move either.
    """
    if not gids:
        return {}
    import helpers.deserved as DES
    try:
        led = DES.game_ledgers(game_ids=set(gids))
    except Exception:
        return {}
    out = {}
    for gid, row in (led or {}).items():
        r = DES.for_team(row, team_id)
        if r is not None:
            out[gid] = r
    return out


@st.cache_data(ttl=600, show_spinner=False)
def _rank_hist(g, season):
    """Every saved board for this league in one read: {day: {team_id: rank}}.

    Cached because the schedule and the upcoming table both resolve against it
    and the Résumé view wants the same dict — one query per (gender, season)
    per rerun window instead of one per row."""
    try:
        return RES.rank_history(g, season=season)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _rest(team_id):
    """Rest/density splits for one team (helpers/fatigue) — score-based."""
    import helpers.fatigue as FT
    try:
        return FT.team_rest_splits(team_id)
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _rest_edge(g):
    """League margin-by-rest-differential curve (helpers/fatigue)."""
    import helpers.fatigue as FT
    try:
        return FT.league_rest_edge(g)
    except Exception:
        return {}


@st.fragment
def render(ctx):
    st.caption("The full schedule with results, the record against every class, "
               "and any tracked game's complete box score on demand.")

    rvc = ctx.bundle["record_vs_class"]
    cls_order = sorted(rvc, key=lambda c: TR._CLASS_RANK.get(c, 99))
    mcols = st.columns(max(len(cls_order) + 1, 2))
    mcols[0].metric("Overall", f"{ctx.rec['wins']}-{ctx.rec['losses']}")
    for col, cls in zip(mcols[1:], cls_order):
        w, l = rvc[cls]
        col.metric(f"vs {cls}", f"{w}-{l}")

    if rvc:
        # The chart restates the metric row above — demoted to an expander.
        with st.expander("Record vs each class — chart"):
            rcfig = go.Figure()
            rcfig.add_trace(go.Bar(x=cls_order, y=[rvc[c][0] for c in cls_order],
                                   name="Wins", marker_color=ctx.GOOD))
            rcfig.add_trace(go.Bar(x=cls_order, y=[rvc[c][1] for c in cls_order],
                                   name="Losses", marker_color=ctx.BAD))
            rcfig.update_layout(barmode="stack")
            rcfig.update_yaxes(title="Games")
            rcfig.update_xaxes(title="Opponent class")
            ctx.style(rcfig, 300)
            st.plotly_chart(rcfig, width="stretch", key="sc_rvc")

    # ── rest & fatigue — the schedule's dates as a signal (score-based) ──────
    _rs = _rest(ctx.team_id)
    if _rs and _rs["buckets"]:
        st.markdown("<div class='lab-hdr'>Rest &amp; fatigue</div>",
                    unsafe_allow_html=True)
        _cells = list(_rs["buckets"])
        _hv = _rs.get("heavy")
        fcols = st.columns(max(len(_cells) + (1 if _hv else 0), 2))
        for col, bkt in zip(fcols, _cells):
            col.metric(bkt["label"], f"{bkt['w']}-{bkt['l']}",
                       delta=f"{bkt['delta']:+.1f} MOV",
                       help=f"{bkt['gp']} games · avg margin {bkt['mov']:+.1f} "
                            f"(season MOV {_rs['overall_mov']:+.1f})")
        if _hv:
            fcols[len(_cells)].metric(
                "3+ games in 7 days", f"{_hv['w']}-{_hv['l']}",
                delta=f"{_hv['delta']:+.1f} MOV",
                help=f"{_hv['gp']} games in heavy weeks · avg margin "
                     f"{_hv['mov']:+.1f}")
        _edge = _rest_edge(getattr(ctx, "gender", None))
        _fresh = {d: v for d, v in _edge.items() if d > 0}
        if _fresh:
            _etxt = " · ".join(
                f"+{d} day{'s' if d > 1 else ''} fresher: "
                f"{v['mov']:+.1f} ({v['gp']} gms)"
                for d, v in sorted(_fresh.items()))
            st.caption(f"Record and margin-vs-usual by days of rest; MOV delta "
                       f"is against this team's own season margin. League-wide "
                       f"fatigue edge — {_etxt}.")
        else:
            st.caption("Record and margin-vs-usual by days of rest; MOV delta "
                       "is against this team's own season margin.")

    st.markdown("<div class='lab-hdr'>Schedule</div>", unsafe_allow_html=True)
    st.caption("Opponent ranking — **Rk @** is where they stood GOING INTO the "
               "game, **Opp Rk** where they stand today — plus opponent record "
               "& class, the model's projected score, and the result. "
               "Projected score uses opponent-adjusted ratings with home court "
               "applied to the actual venue.")
    any_film = any((g.get("video_url") or "").strip() for g in ctx.log)
    # An opponent's tracked rank is possession-based + cross-team → only show it for
    # an opponent the viewer is entitled to (own-team, or league-wide + that team
    # pooled). Free/solo viewers see "—" and the column is dropped entirely below.
    _viewer = AUTH.current_user()
    # The opponent's rank GOING INTO each game, from the saved weekly boards.
    # "beat #6 Broken Bow" is the line a coach actually says, and until now the
    # column could only show where that opponent sits TODAY — which on this book
    # moves a median of 68 places over three months, so the number on a December
    # row was routinely describing a March team. Empty when there is no saved
    # board before the game (pre-first-snapshot, or an opponent under the
    # snapshot floor); an honest blank beats a rank borrowed from the wrong day.
    _hist = _rank_hist(getattr(ctx, "gender", None),
                       getattr(ctx, "season", None))
    _then = RES.opponent_ranks(ctx.log, getattr(ctx, "gender", None),
                               season=getattr(ctx, "season", None),
                               history=_hist) if _hist else {}
    # The deserved margin, for the tracked games THIS VIEWER MAY AGGREGATE.
    #
    # The pool is `bundle["tracked_ids"]`, never `ctx.log`'s tracked flag. The
    # game log is box-score level and deliberately unfiltered (Free sees every
    # result); `tracked_ids` is the same list after `team_bundle` applies the
    # AXIS-2 read filter, so a league-wide coach scouting another team gets that
    # team's POOLED games and not its solo-tracked ones. Taking the flag off the
    # log instead would leak a possession-level read past the gate on a column
    # nobody would think to check.
    _des = _deserved_rows(
        ctx.team_id, tuple(sorted(getattr(ctx, "bundle", {}).get(
            "tracked_ids") or ())))
    sched_rows = []
    for g in ctx.log:
        oid = g["opp_id"]
        o_sc = ctx.scored.get(oid, {})
        o_tr = ctx.tracked.get(oid)
        ovr = o_sc.get("Rank")
        _see_opp = ENT.can_see_team_tracked(_viewer, oid)
        trk_rk = o_tr.get("Rank") if (o_tr and _see_opp) else None
        pred = PRED.predict_game(ctx.team_id, oid, scored=ctx.scored,
                                 tracked=ctx.tracked,
                                 home=(ctx.team_id if g["site"] == "vs" else oid))
        row = {
            "Date": g["date"], "": g["site"], "Opponent": g["opp"],
            "Cls": g["opp_class"],
            "Rk @": RES.rank_chip(_then.get(g["game_id"])) or "—",
            "Opp Rk": f"#{ovr}" if ovr else "—",
            "Trk Rk": f"#{trk_rk}" if trk_rk else "—",
            "Opp Rec": (f"{o_sc.get('W', 0)}-{o_sc.get('L', 0)}"
                        if o_sc else "—"),
            "Proj": (f"{pred['pf_a']:.0f}-{pred['pf_b']:.0f}" if pred else "—"),
            "Result": (FF.label(g["won"], g.get("ff"))
                       + f" {g['pf']}-{g['pa']}"),
            "Margin": f"{g['margin']:+d}",
            "Tracked": "✓" if g["tracked"] else "",
        }
        # ── the disagreement, in the row it disagrees with ──────────────────
        # Deserved = the margin the possessions earned (volume + quality +
        # making + free throws, summing to the final margin exactly). Gap =
        # deserved − actual, and the GAP is what is rendered: a reader handed
        # two numbers and left to subtract will not subtract.
        _d = _des.get(g["game_id"])
        if _d is not None and _d.get("xmargin") is not None:
            row["Deserved"] = f"{_d['xmargin']:+.1f}"
            row["Gap"] = f"{_d['xmargin'] - _d['margin']:+.1f}"
        else:
            row["Deserved"] = row["Gap"] = ""
        if any_film:
            row["Film"] = (g.get("video_url") or "").strip() or None
        sched_rows.append(row)
    # Drop the Trk Rk column entirely when the viewer can't see any opponent's
    # tracked rank (free / solo) — no column of bare dashes, no leak.
    if not any(r["Trk Rk"] != "—" for r in sched_rows):
        for r in sched_rows:
            r.pop("Trk Rk", None)
    # Same rule for the at-the-time rank: a book with no rating history yet
    # (nobody has pressed Rebuild, or the season is too young) would otherwise
    # grow a column of dashes advertising a feature that has no data behind it.
    _any_then = any(r.get("Rk @", "—") != "—" for r in sched_rows)
    if not _any_then:
        for r in sched_rows:
            r.pop("Rk @", None)
    # Same rule the tracked-rank column already follows: a column of blanks
    # advertises a feature with no data behind it. Untracked season, no columns.
    if not any(r.get("Deserved") for r in sched_rows):
        for r in sched_rows:
            r.pop("Deserved", None)
            r.pop("Gap", None)
    sched_cfg = {}
    if any(r.get("Deserved") for r in sched_rows):
        sched_cfg["Deserved"] = st.column_config.TextColumn(
            "Deserved", width="small",
            help="The margin these possessions earned: extra shots, the "
                 "quality of the looks, whether they fell, and the free-throw "
                 "margin — four terms that sum to the final margin exactly. "
                 "Tracked games only.")
        sched_cfg["Gap"] = st.column_config.TextColumn(
            "Gap", width="small",
            help="Deserved minus actual. Positive = the possessions were "
                 "better than the scoreboard says. A description of a game "
                 "that was played, never a claim about a rematch.")
    if _any_then:
        sched_cfg["Rk @"] = st.column_config.TextColumn(
            "Rk @", width="small",
            help="The opponent's league rank GOING INTO this game, from the "
                 "saved board for the week before it — not where they sit "
                 "today. Blank where no board had been saved yet, or the "
                 "opponent had too few games to be ranked at the time.")
    if any_film:
        sched_cfg["Film"] = st.column_config.LinkColumn(
            "Film", display_text="▶ Watch", width="small",
            help="Opens the game's film (Hudl / YouTube / NFHS) in a new tab.")
    _sched_df = pd.DataFrame(sched_rows)
    st.dataframe(_sched_df, hide_index=True, width="stretch",
                 height=min(680, 60 + 35 * len(sched_rows)),
                 column_config=sched_cfg)
    _export(_sched_df, f"schedule_{ctx.team_id}", key="sched_csv")
    if any(r.get("Gap") for r in sched_rows):
        # No verdict sentence here, and that is deliberate. The decomposition
        # agrees with the scoreboard winner on 38 of 52 games out of sample
        # (reliability.MEASURED ("game", "xmargin_picks_winner") = .731), which
        # is a measured DESCRIPTIVE agreement and not a measure of whether a
        # gap repeats. Nothing has measured that, so the number ships and the
        # sentence does not.
        st.caption("**Deserved** is the margin the possessions earned — extra "
                   "shots, the quality of the looks, whether they fell, and "
                   "the free-throw margin, summing to the final margin "
                   "exactly. **Gap** is that minus the actual result: where "
                   "the scoreboard and the possessions disagree. It describes "
                   "the game that was played and says nothing about a rematch.")
    # Disclose the exclusion where the excluded rows are visible (Q6). A "(ff)"
    # on a row whose margin the rest of the page ignores is only honest if the
    # page says so once.
    if any(g.get("ff") for g in ctx.log):
        st.caption(FF.NOTE)

    # ── post-game read (THE BOOK 12.1) ───────────────────────────────────────
    # The table above is thirteen columns of numbers and no sentence about any
    # of the games in it. `postgame.game_report` has written that sentence all
    # along and reached only the box score. One game at a time, chosen — a
    # season's worth eagerly would be one event pass per row on a single vCPU.
    _trk = [g for g in ctx.log if g.get("tracked")]
    if _trk:
        st.markdown("<div class='lab-hdr'>Post-game read</div>",
                    unsafe_allow_html=True)
        _opts = {f"{g['date']} {g['site']} {g['opp']} "
                 f"({FF.label(g['won'], g.get('ff'))} "
                 f"{g['pf']}-{g['pa']})":
                 g["game_id"] for g in reversed(_trk)}
        _pick = st.selectbox("Game", list(_opts), key="sched_pg_pick",
                             label_visibility="collapsed")
        try:
            import helpers.postgame as PG
            _bul = PG.game_report(_opts[_pick])
        except Exception:
            _bul = []
        if _bul:
            for _b in _bul:
                st.markdown("- " + _b)
            st.caption("Auto-generated from the four-factors, RATING and runs "
                       "engines — the same numbers as the tabs above.")
        else:
            st.caption("No events logged for that game yet.")

    # ── upcoming games — the model's pre-game read, for weekly prep ──────────
    # Date floor: a past game whose score never got entered must not lead the
    # "Upcoming" list. (Dates are ISO-normalised in the DB.) Today's games
    # stay listed — live tracked games keep NULL scores until finish_game.
    _today = datetime.now().strftime("%Y-%m-%d")
    # Upcoming only makes sense for the CURRENT season — a past season is over, so
    # its "upcoming" would just be next season's games (the archive bug). Scope to
    # the active season and skip entirely when viewing an archive.
    up_rows = [] if not getattr(ctx, "is_current", True) else query("""
        SELECT g.id, g.date, g.location, g.team1_id, g.team2_id,
               t1.name AS t1, t2.name AS t2
        FROM games g JOIN teams t1 ON t1.id = g.team1_id
                     JOIN teams t2 ON t2.id = g.team2_id
        WHERE (g.team1_id = ? OR g.team2_id = ?)
          AND (g.home_score IS NULL OR g.away_score IS NULL)
          AND g.date >= ? AND g.season = 'Current'
        ORDER BY g.date""", (ctx.team_id, ctx.team_id, _today))
    if up_rows:
        st.markdown("<div class='lab-hdr'>Upcoming — projections</div>",
                    unsafe_allow_html=True)
        # schedule-density chip per row — "3 in 4 nights" is the classic tired-legs
        # setup (quick-hit; fatigue engine's b2b/short-rest splits already render
        # above, this flags WHICH upcoming games carry the load).
        from datetime import date as _d_
        _all_dates = {g["date"] for g in ctx.log} | {g["date"] for g in up_rows}

        def _load_chip(diso):
            try:
                dd = _d_.fromisoformat(diso)
            except ValueError:
                return ""
            n4 = sum(1 for x in _all_dates
                     if 0 <= (dd - _d_.fromisoformat(x)).days <= 3)
            n7 = sum(1 for x in _all_dates
                     if 0 <= (dd - _d_.fromisoformat(x)).days <= 6)
            if n7 >= 4:
                return f"🔥 {n7} in 7"
            if n4 >= 3:
                return f"⚠️ {n4} in 4"
            return ""

        up_disp = []
        for g in up_rows:
            at_home = g["team1_id"] == ctx.team_id
            oid = g["team2_id"] if at_home else g["team1_id"]
            opp = g["t2"] if at_home else g["t1"]
            up_pred = PRED.predict_game(ctx.team_id, oid, scored=ctx.scored,
                                        tracked=ctx.tracked,
                                        home=(ctx.team_id if at_home else oid))
            o_sc = ctx.scored.get(oid, {})
            up_disp.append({
                "Date": g["date"], "": "vs" if at_home else "@",
                "Opponent": opp,
                "Opp Rk": f"#{o_sc['Rank']}" if o_sc.get("Rank") else "—",
                "Opp Rec": (f"{o_sc.get('W', 0)}-{o_sc.get('L', 0)}"
                            if o_sc else "—"),
                "Proj": (f"{up_pred['pf_a']:.0f}-{up_pred['pf_b']:.0f}"
                         if up_pred else "—"),
                "Our win %": (f"{up_pred['win_prob_a'] * 100:.0f}%"
                              if up_pred else "—"),
                "Call": up_pred["confidence"] if up_pred else "—",
                "Load": _load_chip(g["date"]),
            })
        st.dataframe(pd.DataFrame(up_disp), hide_index=True, width="stretch",
                     height=min(420, 60 + 35 * len(up_disp)))
        st.caption("Opponent-adjusted projection with home court at the actual "
                   "venue. **Load** flags schedule density going INTO that game "
                   "(⚠️ 3 games in 4 nights · 🔥 4+ in 7). Open the **Scout** tab "
                   "to build the game plan against the next opponent.")

    st.markdown("<div class='lab-hdr'>Box score</div>",
                unsafe_allow_html=True)
    tracked_games = [g for g in ctx.log if g["tracked"]]
    if not tracked_games:
        st.info("No tracked games to open a box score for yet.")
    else:
        glabels = [f"{g['date']}  {g['site']} {g['opp']}  "
                   f"({FF.label(g['won'], g.get('ff'))} "
                   f"{g['pf']}-{g['pa']})"
                   for g in tracked_games]
        gi = st.selectbox("Pick a tracked game", range(len(tracked_games)),
                          format_func=lambda i: glabels[i], key="sc_box")
        render_box_score(tracked_games[gi]["game_id"])
    # (Team stats over tracked games moved to Charts → Trends to avoid duplication.)
