"""
league_spotlight.py — the five league-wide surfaces that outlived the Analytics Hub.

The Analytics Hub was cut on 2026-09-05 (founder ruling). Nine of its fourteen
sections were duplicates: Power rankings, the league power landscape, the luck /
Pythagorean chart and the top-team gauges all restated Rankings; the scoring
leaders restated Players; the search box restated the one Rankings already has;
and "Jump in" was a stale, worse copy of the sidebar. What was NOT a duplicate is
here, moved onto Rankings — which is the league page, and therefore where league
content belongs.

The five:

  * Tagging coverage   — pool health across the optional one-tap tags.
  * This week in the league — the weekly awards digest (player / game / riser).
  * Biggest risers     — board movement off the daily rating snapshots.
  * Game of the season — the dramatized win-probability ribbon + GEI.
  * What the data noticed — the auto-mined |z| insight strip, players + teams.
  * Notables           — streaks, double-doubles, top scoring games.

(Six, counting Notables — "the five" is the shape, not a count to defend.)

Every gate the Hub applied is preserved verbatim. The cross-team, event-derived
strips need a PAID **league-wide** viewer (the MULTI-TEAM rule: several teams in
one view is a Co-op question, not just a Paid one), and `vis` — the tuple of
tracked game ids that viewer may aggregate, or None for unrestricted — is passed
into every mined surface so a non-pooled Solo team's depth never leaks. An EMPTY
`vis` means "no tracked depth", which is not the same as "no filter", and the
empty-filter trap is guarded at each entry point.

Streamlit render module (the dashboard/*.py convention): the caller resolves
gender / entitlement and hands them in; everything else is computed here behind
its own caches.
"""
from __future__ import annotations

import streamlit as st

from database.db import query
import helpers.stats as S
import helpers.trends as TRD
import helpers.win_probability as WP
from helpers.ui import (mini_tile as _mini, spotlight as _spotlight,
                        wp_ribbon as _wp_ribbon, stat_help as _stat_help)


# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner=False)
def _risers(gender):
    import helpers.rating_history as RH
    try:
        return RH.risers(gender, system="score", days=7, top=3)
    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner=False)
def _awards(gender, vis):
    import helpers.awards as AW
    try:
        return AW.weekly_awards(gender, game_ids=None if vis is None else set(vis))
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _notables(gender):
    import helpers.player_ratings as PR
    table = PR.player_stat_table(gender=gender, min_games=1)
    return TRD.league_notables(table=table)


@st.cache_data(ttl=600, show_spinner="Finding the game of the season…")
def _game_of_season(gender, vis):
    """Highest-GEI tracked game, with the curve and drama summary kept so the
    page can DRAMATIZE it rather than throw the curve away for a scalar.

    The pool uses seasons.tracked_default_season_sql() — the same rollover
    fallback the rest of the read path now takes — so this does not go dark for
    the months between a rollover and the first game of the new year."""
    import helpers.seasons as SEAS
    from collections import defaultdict
    gids = None if vis is None else set(vis)
    best = None
    # TWO queries for the whole sweep, not two PER GAME. The Hub ran a metadata
    # query and an events query inside the loop — 86 round-trips over a 43-game
    # book — which was most of this function's cost. The pool is small enough to
    # fetch whole and group in Python.
    meta = {r["id"]: r for r in query(
        f"""SELECT g.id, g.team1_id t1, g.team2_id t2, t1.name n1, t2.name n2,
                   g.home_score hs, g.away_score aws, t1.gender gen
            FROM games g
            JOIN teams t1 ON t1.id=g.team1_id
            JOIN teams t2 ON t2.id=g.team2_id
            WHERE g.tracked=1 AND t1.gender = ?
              AND g.season = {SEAS.tracked_default_season_sql()}""", (gender,))}
    ids = [i for i in meta if gids is None or i in gids]
    if not ids:
        return None
    ph = ",".join("?" * len(ids))
    by_game = defaultdict(list)
    for r in query(
            f"""SELECT ge.game_id, ge.quarter, ge.time, ge.event_type,
                       ge.shot_type, p.team_id tid
                FROM game_events ge
                JOIN players p ON p.id=ge.primary_player_id
                WHERE ge.game_id IN ({ph}) AND ge.shot_result='make'
                  AND ge.event_type IN ('shot','free_throw')""", tuple(ids)):
        by_game[r["game_id"]].append(r)

    for gid in ids:
        g = meta[gid]
        evs = by_game.get(gid)
        if not evs:
            continue
        evs = sorted(evs, key=lambda e: S.elapsed(e["quarter"], e["time"]))
        h = a = 0
        mc = [(0.0, 0)]
        for e in evs:
            v = e["shot_type"] if e["event_type"] == "shot" else 1
            if e["tid"] == g["t1"]:
                h += v
            elif e["tid"] == g["t2"]:
                a += v
            mc.append((S.elapsed(e["quarter"], e["time"]), h - a))
        curve = WP.wp_curve(mc)
        gei = WP.game_excitement_index(curve)
        if best is None or gei > best[0]:
            # The events feed the win-prob curve only; the official final comes
            # from games.home_score/away_score, with the event tally as fallback.
            best = (gei, g["n1"], g["n2"],
                    g["hs"] if g["hs"] is not None else h,
                    g["aws"] if g["aws"] is not None else a,
                    curve, WP.summarize(curve), gid, g["t1"], g["t2"])
    return best


@st.cache_data(ttl=300, show_spinner="Mining the league…")
def _intel(gender, vis=None):
    """Top-|z| auto-mined findings across the pool — players and teams.

    `vis` is the entitlement read-filter: None = unrestricted, else the tuple of
    tracked game ids this viewer may aggregate. An EMPTY tuple means there is
    nothing this viewer may mine, and must never be passed on as a game_ids
    filter — an empty filter reads as "no scope given" one layer down and would
    silently widen to the whole league."""
    import helpers.player_ratings as PR
    import helpers.insights as IN
    import helpers.playtypes as PT
    import re

    if vis is None:
        table = PR.player_stat_table(gender=gender, min_games=2)
        gids = PT._tracked_game_ids(gender)
    elif not vis:
        return []
    else:
        gset = set(vis)
        table = PR.player_stat_table(game_ids=gset, gender=gender, min_games=2)
        gids = list(gset)
    ev = S.fetch_events(gids) if gids else []

    imp = None
    try:
        from helpers.dashboard.player_card import _rapm as _rapm_pc, _war as _war_pc
        gp = tuple(sorted(gids)) if vis is not None else None
        imp = IN.impact_map(rapm=_rapm_pc(gender, gp),
                            war=_war_pc(gender, "Current", gp))
    except Exception:
        pass

    feed = IN.build_feed(table, ev, top=1, impact=imp) if (table and ev) else {}

    def _b(t):
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)

    flat = [(abs(l["z"]), table[p]["name"], _b(l["text"]), l["metric"], l["n"])
            for p, ls in feed.items() for l in ls]
    try:
        import helpers.team_insights as TIN
        tname = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}
        tfeed = TIN.team_insight_feed(
            gender=gender, game_ids=(list(vis) if vis is not None else None))
        flat += [(abs(l["z"]), tname.get(t, "Team"), _b(l["text"]),
                  l["metric"], l["n"])
                 for t, ls in tfeed.items() for l in ls[:1]]
    except Exception:
        pass
    flat.sort(key=lambda t: -t[0])
    return flat[:8]


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER
# ══════════════════════════════════════════════════════════════════════════════

def _hdr(text):
    st.markdown(f"<div class='lab-hdr'>{text}</div>", unsafe_allow_html=True)


def render(gender, *, paid=False, vis=None, accent="#4c8bf5", scored=None):
    """Draw the league spotlight.

    `paid` is "Paid AND league-wide" as resolved by the caller — it gates every
    cross-team, event-derived strip. `vis` is the tracked-game read-filter (None
    = unrestricted). `scored` is the caller's score_ratings dict, used only to
    name the teams in the risers strip, so this never recomputes the board the
    page above it has already paid for."""
    scored = scored or {}
    drew = False

    if paid:
        try:
            import helpers.coverage as COV
            cov = COV.gender_coverage(gender)
            if cov["games"]:
                drew = True
                _hdr("Tagging coverage — how complete is the capture?")
                sig = cov["signals"]
                # Every signal coverage.py measures, and its own unit. The two
                # newest were being pressed for a season with nothing on screen
                # saying how completely — a partial sample that reads as a full
                # one is the failure this panel exists to prevent, so a measured
                # tag that is not listed here is a tag nobody can discount.
                _rows = (("play_type", "Play type", "shots"),
                         ("defense", "Defense", "shots"),
                         ("guarded_by", "Contested (guarded)", "shots"),
                         ("shot_created_by_id", "Set up by", "shots"),
                         ("turnover_type", "Turnover kind", "turnovers"))
                for _i in range(0, len(_rows), 3):
                    cc = st.columns(3)
                    for col, (key, lbl, unit) in zip(cc, _rows[_i:_i + 3]):
                        s = sig[key]
                        val = f"{s['pct']:.0f}%" if s["pct"] is not None else "—"
                        col.markdown(
                            _mini(lbl, val,
                                  sub=f"{s['tagged']}/{s['total']} {unit}"),
                            unsafe_allow_html=True)
                st.caption("Optional one-tap tags drive the play-type, defense, "
                           "shot-quality and giveaway views — the higher these "
                           "are, the more those surfaces can be trusted. A tag "
                           "at 50% is a half sample, not a half-finished chore. "
                           "Tag in the Game Tracker.")
        except Exception:
            pass

    rise = _risers(gender)
    if rise:
        drew = True
        _hdr("Biggest risers this week")
        rc = st.columns(3)
        for col, (tid, m) in zip(rc, rise):
            nm = scored.get(tid, {}).get("name", f"#{tid}")
            col.markdown(_mini(nm, f"▲{m['d_rank']}",
                               sub=f"rating {m['d_rating']:+.1f} "
                                   f"since {m['from_day'][5:]}"),
                         unsafe_allow_html=True)
        st.caption("Rank spots climbed on the results-only power board over the "
                   "last week (daily snapshots).")

    if paid:
        aw = _awards(gender, vis)
        if aw and (aw["player"] or aw["game"] or aw["riser"]):
            drew = True
            lo, hi = aw["window"]
            _hdr(f"This week in the league — {lo[5:]} → {hi[5:]}")
            ac = st.columns(3)
            if aw["player"]:
                p = aw["player"]
                ac[0].markdown(
                    _mini(f"#{p['number']} {p['name']}", f"GmSc {p['gs']:.0f}",
                          sub=f"Player of the week · {p['team']} · "
                              f"{p['pts']} pts in {p['gp']} gm"),
                    unsafe_allow_html=True)
            if aw["game"]:
                g = aw["game"]
                ac[1].markdown(
                    _mini(g["matchup"], f"GEI {g['gei']:.1f}",
                          sub=f"Game of the week · {g['score']} · {g['date']}"),
                    unsafe_allow_html=True)
            if aw["riser"]:
                r = aw["riser"]
                ac[2].markdown(
                    _mini(r["team"], f"▲{r['d_rank']}",
                          sub=f"Riser of the week · rating {r['d_rating']:+.1f}"),
                    unsafe_allow_html=True)
            st.caption("Composed from the week ending at the latest played date — "
                       "best Game Score week, most exciting tracked game (GEI), "
                       "biggest board climb.")

    if paid:
        game = _game_of_season(gender, vis)
        if game:
            drew = True
            from helpers.win_probability import excitement_label
            try:
                gei, n1, n2, h, a, curve, summ = game[:7]
                # possession-model display curve; GEI above stays on the scoring
                # curve, and we fall back to it if the events can't be fetched.
                try:
                    gid, t1id, t2id = game[7:10]
                    import helpers.wpa as WPA
                    pc = WPA.possession_timeline(S.fetch_events([gid]), t1id, t2id)
                    if len(pc) >= 2:
                        curve = pc
                except Exception:
                    pass
                _hdr("Game of the season")
                gc = st.columns((5, 2), gap="medium")
                with gc[0]:
                    fig = _wp_ribbon(curve, home_name=n1, accent=accent, height=230)
                    if fig is not None:
                        st.plotly_chart(fig, width="stretch", key="ls_wp_gots")
                    else:
                        st.markdown(f"<div class='glass-tile'>{n2} {a} @ {n1} {h}</div>",
                                    unsafe_allow_html=True)
                    st.caption(f"{n2} {a} @ {n1} {h} — {n1} win probability "
                               f"through the game.")
                with gc[1]:
                    st.markdown(_spotlight(f"{gei:.1f}", "Game Excitement Index",
                                           excitement_label(gei), color=accent),
                                unsafe_allow_html=True)
                    _stat_help("GEI", label="What's GEI?")
                    if summ:
                        m = st.columns(2)
                        m[0].markdown(_mini("Lead changes", summ.get("lead_changes", 0)),
                                      unsafe_allow_html=True)
                        m[1].markdown(_mini("Peak swing",
                                            f"{summ.get('peak_swing', 0) * 100:.0f}%"),
                                      unsafe_allow_html=True)
                        if summ.get("comeback", 0) > 0.02:
                            st.markdown(
                                _mini("Biggest comeback",
                                      f"from {summ.get('min_wp_winner', 0.5) * 100:.0f}% odds"),
                                unsafe_allow_html=True)
            except Exception:
                gei = game[0]
                n1, n2, h, a = game[1:5]
                st.markdown(
                    f"<div class='glass-tile'><b>Game of the season</b> — "
                    f"{n2} {a} @ {n1} {h} · "
                    f"<span style='color:var(--accent)'>GEI {gei:.1f} · "
                    f"{excitement_label(gei)}</span></div>",
                    unsafe_allow_html=True)

    if paid:
        # ── the mined league reads — OPT-IN ──────────────────────────────────
        # `_intel` is essentially the whole cost of this view: a league-wide
        # player_stat_table at min_games=2, a full event fetch, RAPM, WAR and
        # the team feed. Measured on this book it is ~24 s of a ~25 s cold
        # Spotlight, and it ran on arrival for everyone who opened the view —
        # including the coaches who came for the awards digest, the risers strip
        # or the game of the season, which are all cheap and all above it.
        #
        # So it is a button now. The header and the caption still render, so the
        # feature is visible rather than hidden — what changed is that the
        # mining is a decision instead of a toll. `_intel` keeps its own
        # cache_data(ttl=300), so pressing it once covers the next five minutes,
        # and the flag is per-GENDER because switching the radio is a different
        # pool and a second full mine.
        _hdr("What the data noticed")
        st.caption("Auto-mined from the tracked play-by-play — the biggest "
                   "signals across the league, gated by sample size.")
        _ikey = f"ls_intel_{gender}"
        if not (st.session_state.get(_ikey)
                or st.button("🔎 Mine the league", key=f"{_ikey}_btn",
                             help="Runs the league-wide miner: every tracked "
                                  "player and team, top signals only. Takes "
                                  "a few seconds; cached for five minutes "
                                  "after that.")):
            st.caption("Not run yet — this one reads every tracked possession "
                       "in the league, so it waits for a click rather than "
                       "charging every visit.")
            intel = []
        else:
            st.session_state[_ikey] = True
            intel = _intel(gender, vis)
        if intel:
            drew = True
            ic = st.columns(2)
            for i, (_z, nm, txt, met, n) in enumerate(intel):
                ic[i % 2].markdown(
                    f"<div class='gloss-card' style='border-left-color:var(--accent)'>"
                    f"<b>{nm}</b> <span class='badge'>{met}</span> "
                    f"<span style='color:var(--subtext);font-size:10px'>n={n}</span>"
                    f"<div style='margin-top:3px;font-size:13px'>{txt}</div></div>",
                    unsafe_allow_html=True)

    try:
        nb = _notables(gender)
    except Exception:
        nb = {}
    if any(nb.values()):
        drew = True
        _hdr("Notables")
        nc = st.columns(3)
        with nc[0]:
            st.caption("Hot hands — double-figure scoring streaks")
            for cur, longest, label in nb["streaks"]:
                if cur or longest:
                    st.markdown(f"**{cur}** in a row · {label} "
                                f"<span style='color:#8b949e'>(long {longest})</span>",
                                unsafe_allow_html=True)
        with nc[1]:
            st.caption("Most double-doubles")
            for cnt, label in nb["double_doubles"]:
                if cnt:
                    st.markdown(f"**{cnt}** · {label}")
        with nc[2]:
            st.caption("Top scoring games")
            for pts, label, date, opp in nb["highs"]:
                if pts:
                    st.markdown(f"**{pts}** · {label} "
                                f"<span style='color:#8b949e'>vs {opp[:14]}</span>",
                                unsafe_allow_html=True)

    if not drew:
        st.caption("Nothing to spotlight yet — track a few games and the league "
                   "reads, awards and game of the season fill in here.")
