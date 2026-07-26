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


def _hdr(text, sub=None):
    st.markdown(f"<div class='lab-hdr'>{text}</div>", unsafe_allow_html=True)
    if sub:
        st.markdown(f"<div class='hdr-sub'>{sub}</div>",
                    unsafe_allow_html=True)


def _pct(v):
    return f"{v * 100:.0f}%" if v is not None else "—"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _events(tids, fp=None):
    """One event pass for every ported section (prod is 1 vCPU — the whole point
    of doing this once is that nine sections below would otherwise be nine
    fetches of the same rows)."""
    return S.fetch_events(list(tids)) if tids else []


@st.cache_data(ttl=6 * 3600, show_spinner="Building the ten-minute brief…")
def brief_bundle(tids, team_id, gender, league_gids=None, fp=None):
    """Everything the masthead needs, off ONE event pass.

    The brief quotes three engines that would otherwise each fetch the same
    rows — the margin decomposition, the allowed shot diet, and the run
    anatomy. Prod is 1 vCPU; one pass reused beats three.

    `league_gids` scopes the LEAGUE baseline for the allowed-diet comparison.
    Without it the comparison falls back to this team's own schedule, which is
    a narrower read and is labelled as such by the caller.
    """
    out = {}
    ev = _events(tids, fp=fp)
    if not ev:
        return out
    try:
        import helpers.deserved as DES
        out["deserved"] = DES.team_deserved(team_id, events=ev,
                                            game_ids=list(tids))
    except Exception as exc:
        out["deserved_error"] = f"{type(exc).__name__}: {exc}"
    try:
        import helpers.runs as RN
        out["anatomy"] = RN.run_anatomy(team_id, ev)
    except Exception as exc:
        out["anatomy_error"] = f"{type(exc).__name__}: {exc}"
    try:
        import helpers.team_insights as TIN
        lg_ev = None
        if league_gids:
            lg_ev = _events(tuple(league_gids), fp=fp)
        ad = TIN.allowed_diet_extra(team_id, events=ev, league_events=lg_ev)
        out["allowed"] = ad.get("allowed_diet")
        out["allowed_league_scoped"] = bool(lg_ev)
    except Exception as exc:
        out["allowed_error"] = f"{type(exc).__name__}: {exc}"
    return out


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
    diets = DP.team_relative(DP.defender_diets(ev))
    return (diets, DP.diet_edges(diets),
            DP.defender_load(ev, game_ids=gids),
            DP.defensive_footprint(ev, game_ids=gids),
            DP.team_allowed_diet(ev))


@st.cache_data(ttl=6 * 3600, show_spinner="Reading the offensive profile…")
def _off_board(tids, fp=None):
    """(diets, edges, load, footprint, own) — the offensive twin of _def_board.

    One `_event_floor` walk feeds both load and footprint, as on the defensive
    side; prod is 1 vCPU and this tab is already the expensive one.
    """
    import helpers.offense_profile as OP
    import helpers.defense_profile as DP
    ev = _events(tids, fp=fp)
    if not ev:
        return {}, {}, {}, {}, {}
    gids = list(tids)
    try:
        import helpers.lineups as LU
        floor = LU._event_floor(gids)
    except Exception:
        floor = None
    # The generic pool/edge/team-relative helpers live on the defensive module
    # and are shape-generic; offense_profile returns that shape on purpose so
    # the two sides cannot drift into two implementations of one idea.
    diets = DP.team_relative(OP.shooter_diets(ev), keys=OP.TEAM_RELATIVE)
    return (diets, DP.diet_edges(diets),
            OP.shooter_load(ev, floor=floor, game_ids=gids),
            OP.offensive_footprint(ev, floor=floor, game_ids=gids),
            OP.team_own_diet(ev))


def render_offense_board(ctx, pids, table, fp=None):
    """Per-player offensive profile — the read the Defense tab was mirroring.

    Columns are ordered by what the measurement supports, exactly as on defense,
    and on this side the ordering is the flattering one for once: the shares a
    player CHOOSES measure SB .70-.92 against the .17-.64 of assignments an
    opponent chooses for her. So the diet leads, the action axis follows, and
    the percentages go last and stay descriptive — a per-player rim FG% (SB .11)
    is the single least repeatable number in the book and never carries a
    verdict here.
    """
    tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    if not tids:
        return
    diets, edges, load, footprint, own = _off_board(tids, fp=fp)
    if not diets:
        return

    _hdr("Offense — what each player actually shoots")
    st.caption(
        "The mirror of the Defense tab, on the side the measurement actually "
        "supports. **OLOAD%** is the offensive twin of DLOAD%: the share of her "
        "team's shots a player takes while she is on the floor — five players "
        "share every shot, so **20% is average by construction**. Read it as "
        "who the offense is looking for.")

    rows = []
    for pid in pids:
        d, l = diets.get(pid), load.get(pid)
        if not d and not l:
            continue
        rows.append({
            "Player": table[pid]["name"],
            "OLOAD%": (f"{l['load'] * 100:.0f}%" if l else "—"),
            "Shots": (d["n"] if d else (l["shots"] if l else 0)),
            "Inside 4ft": (_pct(d["band"].get("rim04")) if d else "—"),
            "4ft-arc": (_pct(d["band"].get("two419")) if d else "—"),
            "Threes": (_pct(d["three_share"]) if d else "—"),
            "Off dribble": (_pct(d["drive_share"]) if d else "—"),
            "Off catch": (_pct(d["catch_share"]) if d else "—"),
            "On-ball": (_pct(d["onball_share"]) if d else "—"),
            "FG%": (_pct(d["FG%"]) if d else "—"),
            "PPS": (f"{d['PPS']:.2f}" if d else "—"),
            "_sort": (l["load"] if l else -1),
        })
    if not rows:
        st.caption("No player has enough located attempts yet — this fills in "
                   "as shots are tapped onto the court in the Game Tracker.")
        return
    rows.sort(key=lambda r: -r["_sort"])
    for r in rows:
        r.pop("_sort")
    st.markdown(dense_table(rows), unsafe_allow_html=True)

    _sb_band = REL.measured("player", "band_share")
    _sb_kind = REL.measured("player", "kind_share")
    _sb_play = REL.measured("player", "playtype_share")
    _sb_pps = REL.measured("player", "pps")
    _sb_bfg = REL.measured("player", "band_fg")
    _sb_kfg = REL.measured("player", "kind_fg")
    st.caption(
        f"{conf_dot_r(_sb_band)} **depth shares** r={_sb_band:.2f} · "
        f"{conf_dot_r(_sb_play)} **action share** r={_sb_play:.2f} · "
        f"{conf_dot_r(_sb_kind)} **angular shares** r={_sb_kind:.2f} · "
        f"{conf_dot_r(_sb_bfg)} **4ft-arc FG%** r={_sb_bfg:.2f} · "
        f"{conf_dot_r(_sb_pps)} **PPS** r={_sb_pps:.2f} — measured over 200 "
        "random half-splits. **This is the inverse of the defensive legend, and "
        "for the stated reason**: a defender's assignment is chosen by the "
        "opponent and measures .17-.64, while a shot is chosen by the shooter "
        "and measures .70-.92. The shares here are the most repeatable numbers "
        "in the book. The percentages are not — and the one a coach asks for "
        f"first, per-player **rim FG%, measures r={_sb_kfg:.2f}**, the worst "
        "figure in the entire reliability book despite having the largest "
        "sample. It is shown nowhere on this page as a trait. FG% and PPS above "
        "are the record of these games, not a claim they repeat.",
        unsafe_allow_html=True)

    with st.expander("Shot edges — where each player's diet departs from the "
                     "league's"):
        st.caption(
            "Each player's most extreme shares against the pool of shooters, "
            "shrunk toward the league by a phantom-attempt prior so a 58% share "
            "on seven shots cannot outrank a real tendency. Unlike the "
            "defensive version of this table, these ARE tendencies: they are "
            "the player's own selection, which is what the .70-.92 was measured "
            "on.")
        arows = []
        for pid in pids:
            es = edges.get(pid)
            if not es:
                continue
            top = [e for e in es if e["axis"] in ("band", "kind", "play",
                                                  "creation")]
            if not top:
                continue
            over = [e for e in top if e["z"] > 0]
            under = [e for e in top if e["z"] <= 0]
            arows.append({
                "Player": table[pid]["name"],
                "Takes more than the league": ", ".join(
                    f"{e['label']} {e['share'] * 100:.0f}% vs "
                    f"{e['lg_share'] * 100:.0f}% (n={e['n']})"
                    for e in over) or "—",
                "Takes less": ", ".join(
                    f"{e['label']} {e['share'] * 100:.0f}% vs "
                    f"{e['lg_share'] * 100:.0f}% (n={e['n']})"
                    for e in under) or "—",
                "Shots": diets.get(pid, {}).get("n", 0),
            })
        if arows:
            st.markdown(dense_table(arows), unsafe_allow_html=True)
        else:
            st.caption("Needs more located attempts per player.")

    with st.expander("On-floor footprint — YOUR OWN shot diet with each player "
                     "on vs off (descriptive)"):
        st.caption(
            "What this team's own shot selection did while a player was out "
            "there — the read behind \"the offense changes shape when she checks "
            "in\". **Not teammate-adjusted and not repeatable**: the defensive "
            "twin of this delta measured −0.06 across a split season, the same "
            "failure mode as raw on/off. Describe the minutes with it; argue "
            "about who caused what with the RAPM columns on Lab.")
        frows = []
        for pid in pids:
            f = footprint.get(pid)
            if not f:
                continue
            frows.append({
                "Player": table[pid]["name"],
                "Shots on": f["on"]["n"], "Shots off": f["off"]["n"],
                "Rim share on": _pct(f["on"]["rim_share"]),
                "Δ rim": f"{f['delta']['rim_share'] * 100:+.0f} pts",
                "3P share on": _pct(f["on"]["three_share"]),
                "Δ 3P": f"{f['delta']['three_share'] * 100:+.0f} pts",
                "Δ own PPS": f"{f['delta']['own_pps']:+.2f}",
            })
        if frows:
            st.markdown(dense_table(frows), unsafe_allow_html=True)
        else:
            st.caption("Needs on-floor lineup snapshots on more possessions.")

    # ── the team's own shot diet, vs the league it plays in ───────────────────
    tid = getattr(ctx, "team_id", None)
    mine = own.get(tid)
    if mine and mine["n"] >= 80:
        _hdr("Shot diet taken — and what the league takes")
        pool = [v for t, v in own.items() if t != tid and v["n"] >= 60]
        import helpers.shot_kinds as SK
        drows = []
        for band in SK.BANDS:
            share = mine["band"].get(band, 0.0)
            lg = ([v["band"].get(band, 0.0) for v in pool] or [None])
            lgm = (sum(lg) / len(lg)) if lg and lg[0] is not None else None
            drows.append({
                "Band": SK.BAND_LABELS.get(band, band),
                "Shots taken": mine["band_n"].get(band, 0),
                "Share": _pct(share),
                "League": _pct(lgm),
                "Δ": (f"{(share - lgm) * 100:+.0f} pts" if lgm is not None
                      else "—"),
            })
        st.markdown(dense_table(drows), unsafe_allow_html=True)
        st.caption(
            f"Over **{mine['n']} attempts**, this offense was contested on "
            f"**{_pct(mine['contested_share'])}** of them, had "
            f"**{_pct(mine['assisted_share'])}** assisted, and scored "
            f"**{mine['own_pps']:.2f} points per shot**. Shares are what an "
            "offense controls — where it chooses to shoot from. Per-band FG% is "
            "deliberately absent for the same reason it is absent from the "
            "defensive mirror: team per-band shooting cannot be measured on a "
            "six-team book, and asserting it in either direction would be a "
            "claim this data never made.")


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
            "Threes": (_pct(d["three_share"]) if d else "—"),
            "On-ball": (_pct(d["onball_share"]) if d else "—"),
            "Off-ball": (_pct(d["offball_share"]) if d else "—"),
            "Zone mins": (_pct(d["zone_share"]) if d else "—"),
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
    _sb_fam = REL.measured("defender", "family_share")
    _sb_sch = REL.measured("defender", "scheme_share")
    st.caption(
        f"{conf_dot_r(_sb_area)} **inside-arc / threes** r={_sb_area:.2f} · "
        f"{conf_dot_r(_sb_load)} **DLOAD%** r={_sb_load:.2f} · "
        f"{conf_dot_r(_sb_sch)} **zone minutes** r={_sb_sch:.2f} · "
        f"{conf_dot_r(_sb_fam)} **on-ball / off-ball** r={_sb_fam:.2f} · "
        f"{conf_dot_r(_sb_fg)} **FG% allowed** r={_sb_fg:.2f} · "
        f"{conf_dot_r(_sb_fine)} **at-rim share** r={_sb_fine:.2f} — measured "
        "over 200 random half-splits. Two rules are doing the work here. "
        "**Coarse survives where fine does not**: inside-vs-outside repeats, "
        "the band cut inside it does not, and on-ball-vs-off-ball repeats where "
        "*isolation* alone measures −0.15. And **on-ball / off-ball / zone "
        "minutes are compared to this player's OWN TEAMMATES**, not the league "
        "— pooled leaguewide, man-defense share measures .73 and almost all of "
        "it is which team she plays for rather than anything about her.",
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
            # every assignment edge the engine ranked, not the top three — the
            # engine has already refused anything under EDGE_MIN_N, so a cap
            # here only hides reads that cleared the gate.
            top = [e for e in es if e["axis"] in ("play", "kind")]
            if not top:
                continue
            over = [e for e in top if e["z"] > 0]
            under = [e for e in top if e["z"] <= 0]
            arows.append({
                "Player": table[pid]["name"],
                "Drew more than the league": ", ".join(
                    f"{e['label']} {e['share'] * 100:.0f}% vs "
                    f"{e['lg_share'] * 100:.0f}% (n={e['n']})"
                    for e in over) or "—",
                "Drew less": ", ".join(
                    f"{e['label']} {e['share'] * 100:.0f}% vs "
                    f"{e['lg_share'] * 100:.0f}% (n={e['n']})"
                    for e in under) or "—",
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

    # ── engines with no verdict of their own; the lines are built here ───────
    def _ledger():
        """Where the points come from, and what is given up, on one axis."""
        import helpers.possession_value as PV
        led = PV.team_ledger(team_id, game_ids=gids, events=ev)
        lines = []
        for side, label in (("offense", "scored"), ("defense", "allowed")):
            l = led.get(side)
            if not l or not l.get("outcomes"):
                continue
            outs = {o["key"]: o for o in l["outcomes"]}
            srcs = sorted(l.get("sources") or [], key=lambda s: -s["pts"])
            n = sum(o["n"] for o in l["outcomes"])
            if n < 60:
                continue
            sc = outs.get("scored") or {}
            tov = outs.get("turnover") or {}
            oreb = outs.get("oreb") or {}
            # EVERY scoring source the ledger separated, not just the biggest —
            # the shape of the whole distribution is the read, and naming only
            # the top one hides that second and third are level.
            top_bit = (" Where the points come from: "
                       + " · ".join(f"<b>{s['label']}</b> "
                                    f"{s['share'] * 100:.0f}%" for s in srcs)
                       + "." if srcs else "")
            lines.append((
                f"Possessions {label}", n,
                f"<b>{sc.get('pct', 0) * 100:.0f}%</b> of these possessions "
                f"{label} at all; <b>{tov.get('pct', 0) * 100:.0f}%</b> ended "
                f"in a turnover and <b>{oreb.get('pct', 0) * 100:.0f}%</b> were "
                f"extended on the offensive glass.{top_bit}"))
        return lines

    def _runs():
        # Profile keys are PER-GAME rates, not counts: gp, made_pg/allowed_pg
        # (big runs), made6_pg/allowed6_pg, biggest, avg_secs, avg_momentum,
        # by_count {0,1,2,'3+' -> [W,L]}, garbage. Garbage-time runs are
        # excluded from every one of them except `garbage` itself.
        import helpers.runs as RN
        r = RN.team_runs(team_id, ev)
        p = (r or {}).get("profile")
        if not p:
            return []
        gp = p.get("gp") or 0
        made, allowed = p.get("made_pg"), p.get("allowed_pg")
        if gp < 3 or made is None or allowed is None:
            return []
        net = made - allowed
        if net > 0.3:
            read = "they win the run battle, and the swings go their way"
        elif net < -0.3:
            read = ("they lose the run battle, and the game gets away from "
                    "them in bursts")
        else:
            read = "runs come and go about evenly on both ends"
        mom = p.get("avg_momentum")
        mom_bit = (f" After one of their own, the next two minutes are "
                   f"<b>{mom:+.1f}</b> net." if mom is not None else "")
        lines = [("Runs", gp,
                  f"<b>{made:.1f}</b> big runs a game against "
                  f"<b>{allowed:.1f}</b> conceded ({net:+.1f}) — {read}. "
                  f"Biggest of the season: <b>{p.get('biggest') or 0}</b> "
                  f"unanswered.{mom_bit}")]
        rec = p.get("by_count") or {}
        bits = [f"{k} run{'s' if str(k) != '1' else ''}: {v[0]}–{v[1]}"
                for k, v in sorted(rec.items(), key=lambda kv: str(kv[0]))
                if (v[0] + v[1])]
        if bits:
            lines.append(("Record by runs", gp,
                          "Record split by how many big runs they put together "
                          "in the game — " + " · ".join(bits) + "."))
        garbage = p.get("garbage")
        if garbage:
            lines.append(("Garbage excluded", gp,
                          f"{garbage} further run{'s' if garbage != 1 else ''} "
                          f"came with the game already decided and are left out "
                          f"of the numbers above."))
        return lines

    def _selfscout():
        import helpers.selfscout as SS
        rep = SS.self_scout_report(team_id, gender=gender, events=ev)
        lines = []
        o = rep.get("offense") or {}
        if o.get("rated") and o.get("predictability") is not None:
            lines.append((
                "Scoutability", o.get("tagged"),
                # top_share is ALREADY 0-100 out of _scoutability_from_rows —
                # multiplying it again printed "Isolation at 2740% of calls"
                f"Play-call predictability <b>{o['predictability']:.0f}/100</b> "
                f"— the most-run set is <b>{o.get('top_set') or '—'}</b> at "
                f"{(o.get('top_share') or 0):.0f}% of tagged calls across "
                f"{o.get('n_sets') or 0} different sets. Higher means a scout "
                f"keys on this offense faster."))
        drift = rep.get("drift") or {}
        for key, label, why in (
                ("overused", "Overused",
                 "run often AND below league efficiency — the scout's gift"),
                ("underused", "Underused",
                 "above league efficiency and under-run — a weapon left on the "
                 "shelf")):
            rows = drift.get(key) or []
            if not rows:
                continue
            # every drifted set, not the top three
            lines.append((
                label, len(rows),
                ", ".join(f"<b>{r['label']}</b> ({r['share'] * 100:.0f}% of "
                          f"calls, {r['PPP']:.2f} points per possession)"
                          for r in rows)
                + f" — {why}."))
        return lines

    def _tovs():
        import helpers.turnovers as TOV
        t = TOV.team_turnover_types(team_id, gender=gender, events=ev,
                                    game_ids=gids)
        rows = (t or {}).get("rows") or []
        tagged = (t or {}).get("total_tagged") or 0
        if not rows or tagged < 12:
            return []
        top = rows[0]
        # The engine's labels are terse nouns ("Pass", "Drive", "Violation")
        # meant for a table header; spelled into a sentence they read as a
        # truncation, so each gets a phrase.
        phrase = {"pass": "bad passes", "drive": "lost handles on the drive",
                  "travel": "travels and violations",
                  "shot_clock": "shot-clock violations",
                  "held": "held balls", "other": "other giveaways"}

        def _what(r):
            return phrase.get(r["key"], r["label"].lower())
        # the FULL mix, not just the leading kind — a coach drilling this needs
        # to know whether it is one problem or three.
        rest = " · ".join(f"{_what(r)} {r['share'] * 100:.0f}%"
                          for r in rows[1:])
        return [("Giveaway mix", tagged,
                 f"<b>{top['share'] * 100:.0f}%</b> of this team's tagged "
                 f"turnovers are <b>{_what(top)}</b> ({tagged} tagged). That "
                 f"is the pattern an opponent sits on — and the one to drill "
                 f"out."
                 + (f" The rest: {rest}." if rest else ""))]

    def _reb():
        """The rebounding read for EVERY player the engine has one for.

        Was capped at the roster's top two rebounders. The cap is gone — a
        read that fired is a read a coach is entitled to see, and the engine
        already refuses to produce one for a player without the sample.
        """
        import helpers.rebounding as RB
        import helpers.player_ratings as PR
        tbl = PR.player_stat_table(gender=gender, min_games=1,
                                   game_ids=set(gids))
        pool = [r for r in tbl.values()]
        mine = [r for r in pool if r.get("team_id") == team_id]
        lines = []
        for row in sorted(mine, key=lambda r: -(r.get("REB") or 0)):
            for badge, n, txt in RB.rebounding_verdict(row, pool=pool):
                lines.append((f"{row['name']} · {badge}", n, txt))
        return lines

    def _anatomy():
        """What this team's runs were MADE of (helpers/runs.run_anatomy)."""
        import helpers.runs as RN
        return RN.anatomy_verdict(RN.run_anatomy(team_id, ev), names=names)

    def _deserved():
        """The four-term margin decomposition (helpers/deserved.py)."""
        import helpers.deserved as DES
        return DES.deserved_verdict(
            DES.team_deserved(team_id, events=ev, game_ids=gids))

    def _scheme():
        """What this offense does against each defensive scheme it has faced."""
        import helpers.defenses as DEF
        fam = DEF.team_defense_families(team_id, gender=gender, events=ev,
                                        game_ids=gids, offense=True)
        rows = [r for r in (fam or {}).get("rows", []) if r.get("poss", 0) >= 10]
        if len(rows) < 2:
            return []
        rows.sort(key=lambda r: -(r.get("PPP") or 0))
        best, worst = rows[0], rows[-1]
        gap = (best.get("PPP") or 0) - (worst.get("PPP") or 0)
        if gap < 0.10:
            return [("Vs schemes", sum(r["poss"] for r in rows),
                     "This offense scores at about the same rate against every "
                     "coverage it has faced — no scheme has slowed it "
                     "specifically, which is a real strength to state.")]
        return [("Vs schemes", sum(r["poss"] for r in rows),
                 f"Best against <b>{best['label']}</b> "
                 f"({best['PPP']:.2f} PPP, {best['poss']} poss), worst against "
                 f"<b>{worst['label']}</b> ({worst['PPP']:.2f}, "
                 f"{worst['poss']}) — a <b>{gap:.2f} PPP</b> spread. Expect to "
                 f"see the second one until it is fixed.")]

    stage("stops", _stops)
    stage("hero", _hero)
    stage("involve", _involve)
    stage("fouls", _fouls)
    stage("clock", _clock)
    stage("ledger", _ledger)
    stage("runs", _runs)
    stage("anatomy", _anatomy)
    stage("deserved", _deserved)
    stage("selfscout", _selfscout)
    stage("tovs", _tovs)
    stage("reb", _reb)
    stage("scheme", _scheme)
    return out, diag


#: Short uppercase heading per ported section, for the dense block grid on the
#: Auto-scout tab. The long headers below stay on the "Every engine" tab, where
#: there is room for them; a block heading has to fit one line at 9.5px.
_PORT_SHORT = {
    "stops": "Stops", "hero": "Ball share", "involve": "Involvement",
    "fouls": "Foul trouble", "clock": "Foul clock", "ledger": "Possessions",
    "runs": "Runs", "anatomy": "Run anatomy", "deserved": "Margin split",
    "selfscout": "Self-scout", "tovs": "Giveaways", "reb": "Rebounding",
    "scheme": "Vs schemes",
}


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
    ("ledger", "📒 Possession ledger — where points come from, what is given up",
     "Every possession classified by how it ended, on both ends, with the "
     "scoring sources behind it.", "Lab"),
    ("runs", "📈 Runs — the swing count behind close results",
     "Scoring runs put together against runs conceded, and the record split by "
     "how many the team managed.", "Charts"),
    ("anatomy", "🔬 Run anatomy — how the swings actually started",
     "What each 10-0 stretch was made of: the event that handed them the ball, "
     "the defense on the floor, where the points came from, and who was out "
     "there — for runs made AND runs conceded.", "Charts"),
    ("deserved", "⚖️ Where the margin came from — the four exact terms",
     "Every point of every final margin split into extra shots · shot "
     "selection · shot-making · free throws. The four add up to the "
     "scoreboard exactly.", "Schedule"),
    ("selfscout", "🔍 Self-scout — how fast an opponent keys on you",
     "Play-call predictability, plus the sets that are over-run and "
     "inefficient (the scout's gift) and the ones left on the shelf.", "Scout"),
    ("tovs", "🔄 Giveaway mix — the pattern to drill out",
     "The dominant tagged turnover kind, which is what an opposing defence "
     "sits on.", "Charts"),
    ("reb", "🏀 Rebounding — box-out payoff and glass identity",
     "The engine's plain-word read for the roster's biggest rebounders, ranked "
     "within their own team.", "Roster"),
    ("scheme", "🛡️ Vs defensive schemes — what slows this offense",
     "Own offense grouped by the coverage it faced, normalized against the "
     "league's own use of that scheme.", "Charts"),
)


def ported_blocks(ctx, fp=None, cols=4):
    """Render every ported engine's verdict as a dense block grid.

    Same lines as `render_ported`, without the expanders: on the Auto-scout tab
    these sit open and packed so a coach sees all thirteen engines at once
    instead of opening thirteen accordions. The long-form version with its
    captions and its "evidence lives on X" pointers stays on Every engine.
    """
    tid = getattr(ctx, "team_id", None)
    tids = tuple(getattr(ctx, "tracked_ids", None) or ())
    if not tid or not tids:
        return
    lines, diag = _ported(tid, ctx.gender, tids, fp=fp)
    if not lines:
        return
    from helpers.dashboard import insights_brief as _BR
    blocks = []
    for key, _header, _cap, home in _PORT_SECTIONS:
        v = lines.get(key)
        if not v:
            continue
        blocks.append(_BR.block(
            _PORT_SHORT.get(key, key), n=home,
            lines=[(badge, txt) for badge, _n, txt in v]))
    if blocks:
        _hdr(f"Every engine — {len(blocks)} reads",
             "Each block is one engine's verdict; the tag on the right is the "
             "tab that owns its chart.")
        _BR.grid(blocks, cols=cols)


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
