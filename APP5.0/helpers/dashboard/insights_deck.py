"""insights_deck.py — THE DECK: what a coach sees before touching anything.

Insights used to open on a tab bar. Nothing rendered above it, by design, and
the effect was that seconds-to-verdict was zero — the page asked a question
("which category?") before it answered one. The deck occupies that space and
renders on EVERY section, so the frame never leaves the screen.

    FAYETTEVILLE  8-3 · +6.2 margin/g · #4 of 31 · 3 days rest · next: ...
    "You win on the glass and lose at the line."
    [★ Extra shots +3.1] [Selection +0.4] [Making -1.2] [Free throws -0.9]
    OFF ####### 78   DEF ##### 52   SHOOT ####### 71   BALL ### 34 ...
    THE FIVE — ranked worst first.

Almost none of this is new arithmetic. The identity sentence is
`insights_brief._identity`, the four terms are `deserved.team_deserved`, the
winning-formula line is imported from Charts, the DNA rail is Lab's eight radar
axes re-rendered as `cards.pctile_bar` rows. What IS new is the ranking behind
THE FIVE (`helpers/insights_severity.py`) and the fact that all of it is on one
screen.

THE FIVE IS A SPOTLIGHT, NOT A REPLACEMENT. The complete, uncapped list still
renders inside each section. The same finding appearing twice — once here, once
in its section — is intended, and the caption says so on screen.
"""
from __future__ import annotations

import html

import streamlit as st

import helpers.insights_severity as SEV
from database.db import query
from helpers.cards import pctile_bar
from helpers.dashboard import insights_brief as BR


#: session-state key holding the deck's control selections, so every section
#: reads the same window without the controls having to be re-rendered.
CONTROLS_KEY = "_ins_controls"


# ══════════════════════════════════════════════════════════════════════════════
#  CACHED PIECES
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner=False)
def _formula(gender, season, team_id, fp=None):
    """(team fit, league fit, suppressors) — the Winning Formula, imported.

    ONE `game_rows` walk serves both fits (the engine takes a prebuilt `rows`
    for exactly this reason), so putting the line on Insights costs one pass,
    not two, and Charts keeps its own copy untouched.
    """
    import helpers.winning_formula as WF
    rows = WF.game_rows(gender=gender, season=season)
    lg = WF.league_formula(rows=rows)
    tm = WF.team_formula(team_id, rows=rows)
    return tm, lg, WF.suppressors(tm or {})


@st.cache_data(ttl=600, show_spinner=False)
def _dna_axes(gender, season, team_id, fp=None):
    """Lab's eight DNA axes as [(label, percentile, value_str)].

    Same eight axes and the same percentile direction as the radar on
    Lab → Advanced (`6_Team_Dashboard.py`), deliberately: two surfaces showing
    one team's identity must not be able to disagree about it. The RENDERING
    differs — a rail reads as a ranking, a radar reads as a shape — which is
    the whole reason it is worth having in both places.
    """
    import helpers.team_analytics as TA
    import helpers.team_ratings as TR
    trk = TR.tracked_ratings(gender=gender, season=season) or {}
    mine = trk.get(team_id)
    lff = TA.league_four_factors(gender=gender, season=season) or {}
    ff = lff.get(team_id)
    if not mine or not ff:
        return []
    pool_o = [r["ORtg"] for r in trk.values() if r.get("ORtg") is not None]
    pool_d = [r["DRtg"] for r in trk.values() if r.get("DRtg") is not None]
    offp = {k: [v["off"][k] for v in lff.values()]
            for k in ("eFG", "TOV", "ORB", "FTR")}
    defp = {k: [v["def"][k] for v in lff.values()] for k in ("eFG", "TOV")}

    def pc(val, pool, hb=True):
        return TA.percentile(val, pool, higher_better=hb)

    return [
        ("Offense", pc(mine.get("ORtg"), pool_o, True),
         f"{mine.get('ORtg') or 0:.0f} ORtg"),
        ("Defense", pc(mine.get("DRtg"), pool_d, False),
         f"{mine.get('DRtg') or 0:.0f} DRtg"),
        ("Shooting", pc(ff["off"]["eFG"], offp["eFG"], True),
         f"{ff['off']['eFG'] * 100:.0f}% eFG"),
        ("Ball security", pc(ff["off"]["TOV"], offp["TOV"], False),
         f"{ff['off']['TOV'] * 100:.0f}% TOV"),
        ("Off. glass", pc(ff["off"]["ORB"], offp["ORB"], True),
         f"{ff['off']['ORB'] * 100:.0f}% ORB"),
        ("Free throws", pc(ff["off"]["FTR"], offp["FTR"], True),
         f"{ff['off']['FTR'] * 100:.0f}% FTr"),
        ("Forces TOs", pc(ff["def"]["TOV"], defp["TOV"], True),
         f"{ff['def']['TOV'] * 100:.0f}% opp TOV"),
        ("Shot defense", pc(ff["def"]["eFG"], defp["eFG"], False),
         f"{ff['def']['eFG'] * 100:.0f}% opp eFG"),
    ]


@st.cache_data(ttl=600, show_spinner=False)
def _standing(gender, season, team_id, fp=None):
    """(net rank, field size) on tracked net rating."""
    import helpers.team_ratings as TR
    trk = TR.tracked_ratings(gender=gender, season=season) or {}
    rows = [(t, (r.get("NetRtg") if r.get("NetRtg") is not None else -999))
            for t, r in trk.items()]
    if team_id not in trk or not rows:
        return None, len(rows)
    rows.sort(key=lambda kv: -kv[1])
    for i, (t, _v) in enumerate(rows, start=1):
        if t == team_id:
            return i, len(rows)
    return None, len(rows)


@st.cache_data(ttl=600, show_spinner=False)
def _next_game(team_id, season="Current"):
    """(opponent name, date, home?) for the next UNPLAYED game, or None."""
    rows = query(
        "SELECT g.date, g.team1_id t1, g.team2_id t2, "
        "       t1.name n1, t2.name n2 "
        "FROM games g "
        "JOIN teams t1 ON t1.id = g.team1_id "
        "JOIN teams t2 ON t2.id = g.team2_id "
        "WHERE (g.team1_id = ? OR g.team2_id = ?) AND g.season = ? "
        "  AND (g.home_score IS NULL OR g.away_score IS NULL) "
        "ORDER BY g.date ASC LIMIT 1",
        (team_id, team_id, season))
    if not rows:
        return None
    r = rows[0]
    home = r["t1"] == team_id
    return ((r["n2"] if home else r["n1"]), r["date"], home)


@st.cache_data(ttl=600, show_spinner=False)
def _by_date(tids):
    """The tracked ids ordered OLDEST FIRST by their game date.

    "Last 5" has to mean the five most recent games played, and game ids are
    creation order — which matches the calendar right up until someone adds a
    make-up game or back-fills a result. Sorting on the date is the only
    version of this control that cannot quietly lie.
    """
    if not tids:
        return ()
    marks = ",".join("?" * len(tids))
    rows = query(f"SELECT id, date FROM games WHERE id IN ({marks})",
                 tuple(tids))
    return tuple(r["id"] for r in
                 sorted(rows, key=lambda r: (str(r["date"] or ""), r["id"])))


@st.cache_data(ttl=600, show_spinner=False)
def _opp_halves(gender, team_id, tids, season="Current", fp=None):
    """({game ids vs the top half}, {vs the bottom half}) by tracked net rating.

    Used by the opponent control. Computed here rather than post-filtering a
    rendered table, so a narrowed selection is a smaller cache key and does
    LESS work — which is the whole reason the controls are allowed to exist on
    a 1 vCPU box.
    """
    import helpers.team_ratings as TR
    if not tids:
        return (), ()
    trk = TR.tracked_ratings(gender=gender, season=season) or {}
    nets = sorted(((t, r.get("NetRtg") or 0.0) for t, r in trk.items()),
                  key=lambda kv: -kv[1])
    half = max(1, len(nets) // 2)
    top = {t for t, _ in nets[:half]}
    marks = ",".join("?" * len(tids))
    rows = query(f"SELECT id, team1_id t1, team2_id t2 FROM games "
                 f"WHERE id IN ({marks})", tuple(tids))
    hi, lo = [], []
    for r in rows:
        opp = r["t2"] if r["t1"] == team_id else r["t1"]
        (hi if opp in top else lo).append(r["id"])
    return tuple(sorted(hi)), tuple(sorted(lo))


# ══════════════════════════════════════════════════════════════════════════════
#  CONTROLS — the first widgets this view has ever had
# ══════════════════════════════════════════════════════════════════════════════

WINDOWS = ("All games", "Last 10", "Last 5")
OPPONENTS = ("All opponents", "Top half", "Bottom half")


def controls(ctx, table, pids):
    """Render the deck's three controls and return the NARROWED scope.

    Returns `(tracked_ids, pid_filter, label)`. Both are cache-key inputs for
    every wrapper on the page — a narrowed window recomputes a smaller pool
    rather than filtering a bigger one after the fact.

    The controls live in the deck so they apply to every section at once; a
    per-section filter would let two sections on one screen disagree about what
    "this team" means.
    """
    tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    c1, c2, c3 = st.columns([2, 1, 1])
    names = {p: (table.get(p) or {}).get("name") or f"#{p}" for p in pids}
    pick = c1.multiselect(
        "Players", options=list(pids), default=[],
        format_func=lambda p: names.get(p, str(p)), key="ins_ctl_players",
        help="Empty = the whole roster. Narrows every player board at once.")
    win = c2.selectbox("Game window", WINDOWS, index=0, key="ins_ctl_window",
                       help="Recompute over the most recent games only.")
    opp = c3.selectbox("Opponent", OPPONENTS, index=0, key="ins_ctl_opp",
                       help="Split the book by the field's own net rating.")

    scoped = tids
    bits = []
    if opp != "All opponents" and tids:
        hi, lo = _opp_halves(ctx.gender, getattr(ctx, "team_id", None), tids,
                             getattr(ctx, "season", "Current"))
        keep = set(hi if opp == "Top half" else lo)
        scoped = tuple(g for g in scoped if g in keep)
        bits.append(opp.lower())
    if win != "All games" and scoped:
        k = 10 if win == "Last 10" else 5
        scoped = tuple(_by_date(tuple(scoped))[-k:])
        bits.append(win.lower())
    if not scoped and tids:
        st.caption("No tracked game matches that combination — showing the "
                   "full book instead.")
        scoped = tids
        bits = []
    label = (" · ".join(bits) if bits else "")
    st.session_state[CONTROLS_KEY] = {
        "window": win, "opponent": opp, "players": list(pick),
        "n_games": len(scoped), "label": label}
    return scoped, set(pick), label


def scope_note(label, n_games, book=None):
    """The always-visible reminder that the page is NOT showing the full book.

    Every number below it changes when a control moves, and a coach who forgets
    she narrowed the window reads a five-game sample as a season. It prints the
    full book size beside the narrowed one for exactly that reason.
    """
    if not label:
        return ""
    of = f" of {book}" if book else ""
    return (f"<span class='badge accent'>SCOPED</span> "
            f"<span style='color:var(--subtext);font-size:11px'>"
            f"{html.escape(label)} · {n_games}{of} tracked games — every number "
            f"below is recomputed over this window</span>")


# ══════════════════════════════════════════════════════════════════════════════
#  THE DECK
# ══════════════════════════════════════════════════════════════════════════════

def _masthead(ctx, des, gender, season, team_id, fp):
    rec = getattr(ctx, "rec", None) or {}
    wins = rec.get("wins") if isinstance(rec, dict) else None
    losses = rec.get("losses") if isinstance(rec, dict) else None
    bits = []
    nm = getattr(ctx, "team_name", None)
    if nm:
        bits.append(f"<b style='letter-spacing:.5px'>{html.escape(str(nm))}"
                    f"</b>")
    if wins is not None and losses is not None:
        bits.append(f"<b>{wins}–{losses}</b>")
    if des.get("means"):
        bits.append(f"<b>{BR._signed(des['means'].get('margin', 0.0))}</b> "
                    f"margin/g")
    rank, field = _standing(gender, season, team_id, fp=fp)
    if rank:
        bits.append(f"<b>#{rank}</b> of {field}")
    try:
        import helpers.fatigue as FT
        import datetime as _dt
        rest = FT.rest_on_date(team_id, _dt.date.today().isoformat())
        if rest is not None:
            bits.append(f"{rest} day{'s' if rest != 1 else ''} rest")
    except Exception:
        pass
    try:
        nx = _next_game(team_id, season)
        if nx:
            opp, date, home = nx
            bits.append(f"next: {'vs' if home else 'at'} "
                        f"<b>{html.escape(str(opp))}</b> "
                        f"<span style='color:var(--subtext)'>"
                        f"{str(date or '')[:10]}</span>")
    except Exception:
        pass
    if bits:
        st.markdown(
            "<div class='gloss-card' style='padding:9px 14px;font-size:12.5px;"
            "display:flex;flex-wrap:wrap;gap:14px;align-items:center'>"
            + "".join(f"<span>{b}</span>" for b in bits) + "</div>",
            unsafe_allow_html=True)


def _formula_line(ctx, gender, season, team_id, fp):
    """The one sentence the whole app is arguing about: what decides games
    HERE, and how good this team is at it. Imported from Charts → Winning
    Formula; that tab keeps its full fit, its factor table and its charts."""
    try:
        import helpers.winning_formula as WF
        tm, lg, supp = _formula(gender, season, team_id, fp=fp)
    except Exception as exc:
        st.caption(f"Winning formula unavailable — {type(exc).__name__}: {exc}")
        return
    lines = WF.verdict_lines(tm, lg)
    if not lines:
        return
    from helpers.cards import verdict_card
    st.markdown(verdict_card(lines), unsafe_allow_html=True)
    if supp:
        st.caption(
            "⚠ " + ", ".join(f"**{f['noun']}**" for f in supp)
            + " fits POSITIVE but correlates NEGATIVE with margin in the raw "
              "column — game state, not a real inversion (losing teams get "
              "fouled late). The fit is what removes it.")


def _dna_rail(ctx, gender, season, team_id, fp):
    try:
        axes = _dna_axes(gender, season, team_id, fp=fp)
    except Exception as exc:
        st.caption(f"Team DNA unavailable — {type(exc).__name__}: {exc}")
        return []
    if not axes:
        return []
    cols = st.columns(4)
    for i, (label, pct, val) in enumerate(axes):
        cols[i % 4].markdown(pctile_bar(label, val, pct),
                             unsafe_allow_html=True)
    return axes


_DIR_MARK = {1: "✓", -1: "⚠", 0: "•"}


def the_five(ranked, *, jump=None, key="deck5", n=5):
    """THE FIVE — the highest-severity findings the whole page produced.

    Straight off the top of the single ranking, with NO re-sort by direction.
    Pushing the bad news to the front would be a second ordering, and the whole
    point of `insights_severity` is that the page has exactly one — a coach who
    sees a ✓ above a ⚠ is being told the ✓ is worth more points, which is true.

    `n` is a SPOTLIGHT SIZE, not a cap: the full uncapped list renders in each
    section, and the caption below says so, because a coach who cannot tell a
    spotlight from a truncation has to assume the page is hiding things.
    """
    if not ranked:
        return
    show = ranked[:n]
    BR._hdr(
        f"The {len(show)} — biggest first",
        f"Severity = points at stake × measured reliability × sample. "
        f"{len(ranked)} findings fired in total; every one of them renders in "
        f"full inside its section — this is a spotlight, not a cap.")
    for i, f in enumerate(show, start=1):
        c1, c2 = st.columns([9, 1])
        mark = _DIR_MARK.get(f.get("direction", 0), "•")
        colour = {"⚠": "var(--bad)", "✓": "var(--good)"}.get(mark,
                                                             "var(--subtext)")
        pts = SEV.pts_chip(f.get("pts"))
        subj = f.get("subject") or ""
        sect = SEV.SECTION_LABELS.get(f.get("section"), "Receipts")
        c1.markdown(
            f"<div style='display:flex;gap:9px;align-items:baseline;"
            f"padding:5px 0;border-bottom:1px solid var(--card-border);"
            f"font-size:12.5px'>"
            f"<span style='color:var(--subtext);width:14px'>{i}.</span>"
            f"<span style='color:{colour};font-weight:800'>{mark}</span>"
            f"<span class='badge accent'>{html.escape(str(f['metric']))}</span>"
            + (f"<span style='color:var(--subtext);font-size:11px'>"
               f"{html.escape(str(subj))}</span>" if subj else "")
            + f"<span style='flex:1'>{f.get('text') or ''}</span>"
            f"<span style='font-weight:800;color:{colour};white-space:nowrap'>"
            f"{pts}</span>"
            f"<span style='color:var(--subtext);font-size:10.5px;"
            f"white-space:nowrap'>r={f.get('r', 0):.2f}</span>"
            f"<span style='color:var(--subtext);font-size:10.5px;"
            f"white-space:nowrap'>→ {html.escape(sect)}</span></div>",
            unsafe_allow_html=True)
        ev = f.get("evidence")
        if ev and jump is not None:
            view, sub = (list(ev) + [None])[:2]
            if view and c2.button("see it", key=f"{key}_{i}",
                                  help=f"Open {SEV.dest_label(view, sub)}"):
                jump(view, sub)


def render(ctx, *, table, pids, ranked, bundle, fp=None, jump=None):
    """The deck. Renders on every section — this is the frame, not a section.

    Returns the DNA axes so a section that wants to expand on them does not
    pay for the pools twice.
    """
    gender = ctx.gender
    season = getattr(ctx, "season", "Current")
    team_id = getattr(ctx, "team_id", None)
    des = (bundle or {}).get("deserved") or {}

    _masthead(ctx, des, gender, season, team_id, fp)

    # ── the identity sentence + the four terms that add to the scoreboard ────
    if des.get("available") and des.get("games", 0) >= 3:
        m = des["means"]
        lead = des["ranked_terms"][0][0]
        cols = st.columns(4)
        subs = {"volume": f"ORB {BR._signed(m['orb_gap'])} · "
                          f"TOV {BR._signed(m['tov_gap'])}",
                "quality": "look value vs opp",
                "making": "vs what the looks were worth",
                "ft_margin": "FT margin"}
        for i, (key, label) in enumerate(BR._TERMS):
            v = m.get(key, 0.0)
            cols[i].markdown(
                BR._tile(label + (" ★" if key == lead else ""),
                         BR._signed(v), subs.get(key, ""),
                         tone="good" if v >= 0 else "bad"),
                unsafe_allow_html=True)
        st.markdown(BR._margin_bar(m), unsafe_allow_html=True)
        st.markdown(BR._bullets([(None, BR._b(BR._identity(des)))]),
                    unsafe_allow_html=True)
    elif des.get("available"):
        st.caption("The margin split needs 3+ tracked games — the sections "
                   "below are already live.")

    _formula_line(ctx, gender, season, team_id, fp)
    axes = _dna_rail(ctx, gender, season, team_id, fp)

    the_five(ranked, jump=jump)
    return axes
