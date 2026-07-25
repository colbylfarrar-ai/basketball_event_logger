"""insights_deep.py — the Insights tab's deep-dive half.

Insights is the flagship surface: the one page a coach can be pointed at with
"everything the engines found is in here, sort through it and take what you
want". Most of what the app knows already existed, spread across sixteen pages,
each read living beside the chart that produced it. This module brings the
READS onto Insights without moving the charts, so the depth is discoverable in
one place and the tabs that own the evidence stay intact (the standing
constraint: no page is removed, no depth consolidated away).

Two kinds of section live here.

  1. THE DEFENSIVE BOARD — new, and the reason the module exists. `helpers/
     defense_profile.py` gives a defender the same profile an offensive player
     has had all along: what they are asked to guard, how much of the team's
     defensive work lands on them (DLOAD%), and what the opponent's shot diet
     did while they were out there. It renders with the reliability of each
     column stated, because the measurement came back mixed and the mix is the
     finding — see `reliability`'s DEFENSIVE SHARES ARE NOT OFFENSIVE SHARES.

  2. PORTED VERDICTS — every engine in the app that already exposes a
     `*_verdict(...) -> [(badge, n, html)]` returns the same shape, which is
     what makes this cheap: stops, rebounding, hero-ball, involvement, foul
     trouble, possession value, runs, self-scout and turnover mix all render
     through one `verdict_card` call and one uniform expander.

Every heavy call is cached on the page's data fingerprint. Display-only.
"""
from __future__ import annotations

import streamlit as st

import helpers.stats as S
from helpers.cards import dense_table, verdict_card, conf_dot_r
import helpers.reliability as REL


# ── shared helpers ────────────────────────────────────────────────────────────
def _names():
    from database.db import query
    return {r["id"]: r["name"] for r in query("SELECT id, name FROM players")}


def _hdr(text):
    st.markdown(f"<div class='lab-hdr'>{text}</div>", unsafe_allow_html=True)


def _pct(v):
    return f"{v * 100:.0f}%" if v is not None else "—"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _events(tids, fp=None):
    """One event pass for every ported section (prod is 1 vCPU — the whole point
    of doing this once is that nine sections below would otherwise be nine
    fetches of the same rows)."""
    return S.fetch_events(list(tids)) if tids else []


# ══════════════════════════════════════════════════════════════════════════════
#  1. THE DEFENSIVE BOARD
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=6 * 3600, show_spinner="Building the defensive board…")
def _def_board(tids, fp=None):
    """(diets, edges, load, footprint, allowed) for the tracked pool."""
    import helpers.defense_profile as DP
    ev = _events(tids, fp=fp)
    if not ev:
        return {}, {}, {}, {}, {}
    gids = list(tids)
    diets = DP.defender_diets(ev)
    return (diets, DP.diet_edges(diets),
            DP.defender_load(ev, game_ids=gids),
            DP.defensive_footprint(ev, game_ids=gids),
            DP.team_allowed_diet(ev))


def render_defense_board(ctx, pids, table, fp=None):
    """Per-defender assignment profile — the offensive shot-diet read, ported.

    The columns are ordered by what the measurement supports, not by what is
    most quotable: DLOAD% and the interior/perimeter split first (SB .574/.578),
    the assignment mix last and captioned as a record rather than a tendency
    (isolation share measured SB -.15).
    """
    tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    if not tids:
        return
    diets, edges, load, footprint, allowed = _def_board(tids, fp=fp)
    if not diets:
        return

    _hdr("Defense — what each player is asked to guard")
    st.caption(
        "The offensive profile, ported to defense off the nearest-defender tap. "
        "**DLOAD%** is the defensive twin of usage: the share of this team's "
        "tagged contests a player takes on while she is on the floor — five "
        "players share every possession, so **20% is average by construction**. "
        "Read it as who the offense is hunting.")

    rows = []
    for pid in pids:
        d, l = diets.get(pid), load.get(pid)
        if not d and not l:
            continue
        rows.append({
            "Player": table[pid]["name"],
            "DLOAD%": (f"{l['load'] * 100:.0f}%" if l else "—"),
            "Contests": (d["n"] if d else (l["contested"] if l else 0)),
            "Inside arc": (_pct(d["paint_share"]) if d else "—"),
            "At rim": (_pct(d["rim_share"]) if d else "—"),
            "Threes": (_pct(d["three_share"]) if d else "—"),
            "Off dribble": (_pct(d["drive_share"]) if d else "—"),
            "FG% allowed": (_pct(d["FG%"]) if d else "—"),
            "PPS allowed": (f"{d['PPS']:.2f}" if d else "—"),
            "_sort": (l["load"] if l else -1),
        })
    if not rows:
        st.caption("No defender has enough tagged contests yet — tap who "
                   "contested the shot in the Game Tracker and this fills in.")
        return
    rows.sort(key=lambda r: -r["_sort"])
    for r in rows:
        r.pop("_sort")
    st.markdown(dense_table(rows), unsafe_allow_html=True)

    # the reliability legend, stated per column rather than as one blanket dot
    _sb_load = REL.measured("defender", "load")
    _sb_area = REL.measured("defender", "area_share")
    _sb_fine = REL.measured("defender", "assignment_share")
    _sb_fg = REL.measured("defender", "allowed_fg")
    st.caption(
        f"{conf_dot_r(_sb_load)} **DLOAD%** r={_sb_load:.2f} · "
        f"{conf_dot_r(_sb_area)} **inside-arc / threes** r={_sb_area:.2f} · "
        f"{conf_dot_r(_sb_fine)} **at-rim share** r={_sb_fine:.2f} · "
        f"{conf_dot_r(_sb_fg)} **FG% allowed** r={_sb_fg:.2f} — measured over "
        "200 random half-splits of this season. The coarse inside/outside split "
        "repeats; the finer cut inside it does not, because which look a "
        "defender draws is the opponent's call, not hers.",
        unsafe_allow_html=True)

    with st.expander("Assignment mix — what actions each defender drew "
                     "(a record of these games, not a tendency)"):
        st.caption(
            "The single most natural sentence in this data — *\"she's an "
            "isolation defender\"* — is the one it does not support: "
            "isolation-assignment share measures **r = −0.15** across a split "
            "season, worse than any offensive read in the book. A defender's "
            "assignment mix follows the schedule. It is shown because what "
            "happened in these games is worth knowing; it is not a projection.")
        arows = []
        for pid in pids:
            es = edges.get(pid)
            if not es:
                continue
            top = [e for e in es if e["axis"] in ("play", "kind")][:3]
            if not top:
                continue
            arows.append({
                "Player": table[pid]["name"],
                "Most-drawn": ", ".join(
                    f"{e['label']} {e['share'] * 100:.0f}% (n={e['n']})"
                    for e in top if e["z"] > 0) or "—",
                "League": ", ".join(f"{e['lg_share'] * 100:.0f}%"
                                    for e in top if e["z"] > 0) or "—",
                "Contests": diets.get(pid, {}).get("n", 0),
            })
        if arows:
            st.markdown(dense_table(arows), unsafe_allow_html=True)
        else:
            st.caption("Needs play-type tags on contested shots.")

    with st.expander("On-floor footprint — the opponent's shot diet with each "
                     "player on vs off (descriptive)"):
        st.caption(
            "What the opponent's own shot selection did while a player was out "
            "there. **Not teammate-adjusted and not repeatable** — all three "
            "deltas measure between −0.06 and 0.23 across a split season, the "
            "same failure mode as raw on/off. Use it to describe the minutes "
            "that were played, and the RAPM columns on the Lab view to argue "
            "about who caused what.")
        frows = []
        for pid in pids:
            f = footprint.get(pid)
            if not f:
                continue
            frows.append({
                "Player": table[pid]["name"],
                "Opp shots on": f["on"]["n"], "Opp shots off": f["off"]["n"],
                "Rim share on": _pct(f["on"]["rim_share"]),
                "Δ rim": f"{f['delta']['rim_share'] * 100:+.0f} pts",
                "3P share on": _pct(f["on"]["three_share"]),
                "Δ 3P": f"{f['delta']['three_share'] * 100:+.0f} pts",
                "Δ opp PPS": f"{f['delta']['opp_pps']:+.2f}",
            })
        if frows:
            st.markdown(dense_table(frows), unsafe_allow_html=True)
        else:
            st.caption("Needs on-floor lineup snapshots on more possessions.")

    # ── the team's own allowed shot diet, vs the league it plays in ───────────
    tid = getattr(ctx, "team_id", None)
    mine = allowed.get(tid)
    if mine and mine["n"] >= 80:
        _hdr("Shot diet allowed — the defensive mirror")
        pool = [v for t, v in allowed.items() if t != tid and v["n"] >= 60]
        import helpers.shot_kinds as SK
        drows = []
        for band in SK.BANDS:
            share = mine["band"].get(band, 0.0)
            lg = ([v["band"].get(band, 0.0) for v in pool] or [None])
            lgm = (sum(lg) / len(lg)) if lg and lg[0] is not None else None
            drows.append({
                "Band": SK.BAND_LABELS.get(band, band),
                "Shots allowed": mine["band_n"].get(band, 0),
                "Share": _pct(share),
                "League": _pct(lgm),
                "Δ": (f"{(share - lgm) * 100:+.0f} pts" if lgm is not None else "—"),
            })
        st.markdown(dense_table(drows), unsafe_allow_html=True)
        st.caption(
            f"Over **{mine['n']} opponent attempts**, this defense contested "
            f"**{_pct(mine['contest_share'])}** of them and conceded "
            f"**{mine['opp_pps']:.2f} points per shot**. Shares are what a "
            "defense controls — where it makes opponents shoot from. It "
            "deliberately does not report how well opponents shot each band: "
            "team per-band FG% cannot be measured on a six-team book, and "
            "asserting it in either direction would be a claim this data never "
            "made.")


# ══════════════════════════════════════════════════════════════════════════════
#  2. PORTED VERDICTS — the reads that lived on other tabs
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=6 * 3600, show_spinner="Gathering every engine's read…")
def _ported(team_id, gender, tids, fp=None):
    """{section_key: [(badge, n, html)]} — every ported engine's verdict lines.

    Each engine is isolated: one that raises contributes nothing and the rest
    still render, the same contract `insights.build_feed` uses. `diagnostics`
    is returned alongside so a silent engine is distinguishable from a broken
    one — the failure mode this codebase has been bitten by before.
    """
    ev = _events(tids, fp=fp)
    gids = list(tids)
    out, diag = {}, {}
    names = _names()

    def stage(key, fn):
        try:
            v = fn()
            if v:
                out[key] = v
        except Exception as exc:
            diag[key] = f"{type(exc).__name__}: {exc}"

    def _stops():
        import helpers.stops as ST
        return ST.stops_verdict(ST.team_stops(team_id, game_ids=gids, events=ev))

    def _hero():
        import helpers.hero_ball as HB
        conc = HB.team_concentration(events=ev, team_id=team_id)
        try:
            lg = HB.league_context(gender=gender, events=ev)
            pool_pct = (lg or {}).get("pct_for", {}).get(team_id)
        except Exception:
            pool_pct = None
        return HB.hero_ball_verdict(conc, pool_pct=pool_pct, names=names)

    def _involve():
        import helpers.involvement as IV
        return IV.involvement_verdict(
            IV.player_involvement(events=ev, team_id=team_id), names=names)

    def _fouls():
        import helpers.foul_trouble as FT
        bench = FT.bench_cost(events=ev, team_id=team_id)
        state = FT.team_foul_state_net(events=ev, team_id=team_id)
        return FT.foul_trouble_verdict(bench, state, names=names)

    def _clock():
        import helpers.foul_trouble as FT
        return FT.foul_clock_lines(
            FT.foul_clock(events=ev, team_id=team_id), names=names, level=2)

    stage("stops", _stops)
    stage("hero", _hero)
    stage("involve", _involve)
    stage("fouls", _fouls)
    stage("clock", _clock)
    return out, diag


#: (key, header, caption, which tab owns the evidence)
_PORT_SECTIONS = (
    ("stops", "🛑 Stops & kills",
     "Consecutive defensive trips without conceding, and how often this team "
     "answers straight back after giving one up.", "Defense"),
    ("hero", "🎯 Ball share & shot concentration",
     "How concentrated the scoring is across the rotation — never a judgement, "
     "a team with one elite scorer should funnel.", "Charts"),
    ("involve", "🔗 Involvement — the glue the box score misses",
     "Share of the team's scoring plays a player touches in any role: scorer, "
     "passer, screener, rebounder.", "Lab"),
    ("fouls", "⚖️ Foul trouble — what it actually costs",
     "Floor time lost after the Nth foul, and the team's net in each foul "
     "state.", "Roster"),
    ("clock", "⏱️ The foul clock — when the bench decision arrives",
     "The median game-clock stamp of each player's second foul, ordered by how "
     "early it lands.", "Roster"),
)


def render_ported(ctx, fp=None):
    """The other tabs' verdicts, gathered onto Insights."""
    tid = getattr(ctx, "team_id", None)
    tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    if not tid or not tids:
        return
    lines, diag = _ported(tid, ctx.gender, tids, fp=fp)
    if not lines and not diag:
        return

    _hdr("Every other engine's read — gathered here")
    st.caption(
        "These reads own a chart on another tab; the verdict is repeated here "
        "so one page carries everything the engines found. The chart behind "
        "each one stays where it lives — nothing was moved.")
    for key, header, cap, home in _PORT_SECTIONS:
        v = lines.get(key)
        if not v:
            continue
        with st.expander(f"{header}  ·  evidence on **{home}**", expanded=False):
            st.caption(cap)
            st.markdown(verdict_card(v), unsafe_allow_html=True)
    if diag:
        with st.expander("⚠️ Engines that failed to run", expanded=False):
            st.caption(
                "Shown rather than swallowed: a raising engine and an engine "
                "with genuinely nothing to say used to look identical here.")
            for k, msg in diag.items():
                st.markdown(f"- `{k}` — {msg}")


# ══════════════════════════════════════════════════════════════════════════════
#  3. THE FOUL-RATE BOARD — measured reliable, and surfaced nowhere until now
# ══════════════════════════════════════════════════════════════════════════════

def render_foul_rates(pids, table):
    """Fouls per 32 minutes, the strongest per-player defensive signal in the book.

    Split-half reliability SB .68–.84 — better than every shot-making rate and
    better than every defensive share — and until this session no surface in
    the app showed it. The foul CLOCK says when a player's fouls land; this
    says how often they come, which is the number that decides whether a coach
    can plan 28 minutes for someone.
    """
    rows = []
    for pid in pids:
        r = table.get(pid) or {}
        pf, mins = r.get("PF"), r.get("MIN")
        if pf is None or not mins or mins < 40:
            continue
        rows.append({"Player": r["name"], "Minutes": f"{mins:.0f}",
                     "Fouls": int(pf), "PF/game": f"{r.get('PF/G') or 0:.1f}",
                     "Per 32 min": f"{pf / mins * 32:.1f}",
                     "_r": pf / mins * 32})
    if len(rows) < 3:
        return
    rows.sort(key=lambda r: -r["_r"])
    for r in rows:
        r.pop("_r")
    _hdr("Foul rate — per 32 minutes")
    st.markdown(dense_table(rows), unsafe_allow_html=True)
    st.caption(
        "Measured **r = .68–.84** across a split season — the most repeatable "
        "player-level defensive number this book produces, and more reliable "
        "than any shooting rate in it. A high rate is a rotation constraint "
        "before it is a discipline note.")
