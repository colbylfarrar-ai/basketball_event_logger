"""
insights_tab.py — Team Dashboard > Insights tab (the scout that reads itself,
scoped to the SELECTED team).

Renders each of the team's players' most-surprising true facts (helpers/insights.py),
plus force-to-off-hand + space-dependence boards, defensive win-impact and the
pick-&-roll role split — all filtered to this team but scored vs the whole league
(so "elite" means elite leaguewide, not just on this roster). Team-scoped tracked
data, so it sits behind the team tracked gate (ctx.has_tracked).

render(ctx) @st.fragment — the page builds a SimpleNamespace ctx. Display-only.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

import helpers.player_ratings as PR
import helpers.stats as S
import helpers.insights as IN
import helpers.insights_team as INT
import helpers.playtypes as PT
import helpers.wpa as WPA


def _b(t):
    """Markdown **bold** → <b> for raw-HTML cards."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


@st.cache_data(ttl=300, show_spinner=False)
def _league(gender):
    """League table + insight feed + role splits + win-impact + guarded cliffs,
    computed once per gender (the team view filters this to its own players, so the
    z-scores stay league-relative)."""
    table = PR.player_stat_table(gender=gender, min_games=1)
    gids = PT._tracked_game_ids(gender)
    ev = S.fetch_events(gids) if gids else []
    feed = IN.build_feed(table, ev, top=3) if table else {}
    roles = PT.player_role_splits(events=ev) if ev else {}
    cliffs = IN.guarded_cliffs(ev) if ev else {}
    try:
        impact = WPA.season_wpa(gender, mode="possession")
    except Exception:
        impact = {}
    return table, feed, roles, impact, cliffs


@st.cache_data(ttl=300, show_spinner=False)
def _strength(gender, team_id, tids):
    """Opponent-strength offense split for this team (top vs bottom half of the
    league), cached per (gender, team, visible games)."""
    return INT.strength_splits(team_id, gender=gender,
                               game_ids=list(tids) if tids else None)


@st.cache_data(ttl=300, show_spinner=False)
def _winloss(gender, team_id, tids):
    """Wins-vs-losses offense split for this team, cached per (gender, team, games)."""
    return INT.winloss_splits(team_id, gender=gender,
                              game_ids=list(tids) if tids else None)


@st.cache_data(ttl=300, show_spinner=False)
def _tendencies(gender, team_id, tids):
    """Zone-based shot tendencies (force left/right, where shots live)."""
    return INT.shot_tendencies(team_id, gender=gender,
                               game_ids=list(tids) if tids else None)


@st.cache_data(ttl=300, show_spinner=False)
def _passers(gender):
    """Per-passer shot-creation quality (pass-from look quality vs finish)."""
    return INT.passer_quality(gender=gender)


def _pct(v):
    return f"{v * 100:.0f}%" if v is not None else "—"


def _split_rows(pa, pb, la, lb):
    """The shared 7-metric split table (used by every A-vs-B deep-dive section)."""
    _f2 = lambda v: f"{v:.2f}" if v is not None else "—"
    specs = [("PPP (pts/shot)", "PPP", _f2), ("eFG%", "eFG", _pct),
             ("Scoring eff (SCE)", "SCE", _pct), ("3PA rate", "3PA_rate", _pct),
             ("Rim rate", "rim_rate", _pct), ("Assisted rate", "ast_rate", _pct),
             ("Open rate", "open_rate", _pct)]
    return [{"Metric": lbl, la: fmt(pa.get(k)), lb: fmt(pb.get(k))}
            for lbl, k, fmt in specs]


@st.fragment
def render(ctx):
    if not getattr(ctx, "has_tracked", False):
        st.info("🔒 Insights read tracked play-by-play (shot quality, contest "
                "splits, win-impact). Track this team's games — or unlock the "
                "Paid tier — to light them up.")
        return

    # (Team at a glance moved to the Overview tab — UI_DENSITY_PLAN phase A.)
    table, feed, roles, impact, cliffs = _league(ctx.gender)
    if not table:
        st.caption("No tracked players yet for this league.")
        return

    # this team's player ids, ordered by rating
    pids = []
    for p in (ctx.players or []):
        pid = p.get("_pid") if isinstance(p, dict) else None
        if pid in table:
            pids.append(pid)
    pids = sorted(set(pids), key=lambda p: -(table[p].get("OVERALL") or 0))
    if not pids:
        st.caption("No tracked shooters on this roster yet.")
        return

    st.caption("What the tracked data says about this team — each line is the "
               "player's biggest deviation from the league, gated by sample size "
               "so a hot night never headlines. Scored vs the whole league.")

    # ── per-player auto-scout (the team-by-team feed) ─────────────────────────
    st.markdown("<div class='lab-hdr'>Auto-scout — this team</div>",
                unsafe_allow_html=True)
    any_line = False
    for pid in pids:
        lines = feed.get(pid, [])
        if not lines:
            continue
        any_line = True
        nm = table[pid]["name"]
        body = "".join(
            f"<div style='margin-top:4px'><span class='badge accent'>{ln['metric']}</span> "
            f"<span style='color:var(--subtext);font-size:10px'>n={ln['n']}</span> "
            f"{_b(ln['text'])}</div>" for ln in lines)
        st.markdown(
            f"<div class='gloss-card'><b style='font-size:14px'>{nm}</b>{body}</div>",
            unsafe_allow_html=True)
    if not any_line:
        st.caption("No standout signals yet — this roster reads close to league "
                   "average on the tracked splits, or needs more games.")

    # ── deep dive: offense vs TOP-half vs BOTTOM-half opponents ────────────────
    _tids = getattr(ctx, "tracked_ids", None)
    _ss = _strength(ctx.gender, ctx.team_id, _tids) if getattr(ctx, "team_id", None) \
        else {"available": False}
    st.markdown("<div class='lab-hdr'>Deep dive — vs top teams vs bottom teams</div>",
                unsafe_allow_html=True)
    if not _ss.get("available"):
        st.caption("Needs more tracked games against both stronger and weaker "
                   "opponents (≥15 shots each side) — this split fills in as the "
                   "schedule builds.")
    else:
        _tp, _bt = _ss["top"], _ss["bottom"]
        st.dataframe(pd.DataFrame(_split_rows(
            _tp, _bt, f"vs Top-half ({_ss['top_games']}g)",
            f"vs Bottom-half ({_ss['bottom_games']}g)")),
            hide_index=True, width="stretch")
        _dp = (_tp["PPP"] or 0) - (_bt["PPP"] or 0)
        if _dp <= -0.12:
            st.caption(f"⚠ Offense drops **{abs(_dp):.2f} PPP** against top-half "
                       "teams — the scoring is feasting on weaker opponents. Watch "
                       "the 3PA / rim mix above to see what stops working.")
        elif _dp >= 0.12:
            st.caption(f"This team *rises* **+{_dp:.2f} PPP** vs top-half teams — "
                       "it brings its best against the better opponents.")
        else:
            st.caption("Offense holds up about the same against strong and weak "
                       "opponents — a steady, opponent-proof profile.")

    # ── deep dive: offense IN WINS vs IN LOSSES ───────────────────────────────
    _wl = _winloss(ctx.gender, ctx.team_id, _tids) if getattr(ctx, "team_id", None) \
        else {"available": False}
    st.markdown("<div class='lab-hdr'>Deep dive — in wins vs in losses</div>",
                unsafe_allow_html=True)
    if not _wl.get("available"):
        st.caption("Needs ≥15 shots in both wins and losses — this split fills in "
                   "as the record builds.")
    else:
        _w, _l = _wl["win"], _wl["loss"]
        st.dataframe(pd.DataFrame(_split_rows(
            _w, _l, f"In wins ({_wl['win_games']})",
            f"In losses ({_wl['loss_games']})")),
            hide_index=True, width="stretch")
        # what changes when they lose — the biggest metric swing tells the story
        _cands = [("3-point volume", "3PA_rate"), ("rim pressure", "rim_rate"),
                  ("ball movement", "ast_rate"), ("open looks", "open_rate")]
        _sw = max(_cands, key=lambda c: abs((_w.get(c[1]) or 0)
                                            - (_l.get(c[1]) or 0)))
        _d = (_w.get(_sw[1]) or 0) - (_l.get(_sw[1]) or 0)
        _dir = "up" if _d > 0 else "down"
        st.caption(
            f"Biggest style swing: **{_sw[0]}** is {_dir} "
            f"{abs(_d) * 100:.0f} pts in wins ({_pct(_w.get(_sw[1]))} vs "
            f"{_pct(_l.get(_sw[1]))}). eFG% "
            f"{_pct(_w.get('eFG'))} in wins vs {_pct(_l.get('eFG'))} in losses — "
            "what shows up when this team is at its best.")

    # ── self-scout: shot tendencies (force left/right, where shots live) ──────
    _te = _tendencies(ctx.gender, ctx.team_id, _tids) if getattr(ctx, "team_id",
                                                                 None) \
        else {"available": False}
    st.markdown("<div class='lab-hdr'>Self-scout — shot tendencies (how to defend "
                "us)</div>", unsafe_allow_html=True)
    if not _te.get("available"):
        st.caption("Needs ~30 tracked shots to map the tendencies — fills in fast.")
    else:
        _sd = _te["side"]
        _lft, _rgt = _sd["Left"], _sd["Right"]
        if abs(_lft - _rgt) >= 0.10:
            _heavy = "left" if _lft > _rgt else "right"
            _force = "right" if _heavy == "left" else "left"
            st.caption(f"**{max(_lft, _rgt) * 100:.0f}%** of shots come from their "
                       f"**{_heavy} side** — a defense can **force them {_force}**. "
                       f"(Left {_pct(_lft)} · Middle {_pct(_sd['Middle'])} · Right "
                       f"{_pct(_rgt)}.)")
        else:
            st.caption(f"Balanced left/right (Left {_pct(_lft)} · Right {_pct(_rgt)})"
                       " — no strong side to force.")
        _zz = sorted(_te["zones"], key=lambda z: -z["poss"])
        st.dataframe(pd.DataFrame([{
            "Zone": z["label"], "Shots": z["poss"], "Share": _pct(z["share"]),
            "FG%": _pct(z["FG%"]),
            "PPP": (f"{z['PPP']:.2f}" if z["PPP"] is not None else "—")}
            for z in _zz]), hide_index=True, width="stretch")
        st.caption(f"Shot diet: rim {_pct(_te['rim_rate'])} · mid "
                   f"{_pct(_te['mid_rate'])} · three {_pct(_te['three_rate'])}. "
                   "Take away their best zone, live with the worst. (Play-call "
                   "predictability + over-used sets live on the Scout tab.)")

    # ── passer quality — look created vs finish (the pass-from FG% nuance) ────
    _pq = _passers(ctx.gender)
    _prows = sorted(((pid, _pq[pid]) for pid in pids if pid in _pq),
                    key=lambda t: -t[1]["xPPS_created"])
    if _prows:
        st.markdown("<div class='lab-hdr'>Passer quality — looks created vs "
                    "finished</div>", unsafe_allow_html=True)
        st.caption("**Look quality** = expected value of the shots a passer sets up "
                   "(the zone/contest of the look, whether or not it dropped). "
                   "**Finish Δ** = actual − expected: a big minus means the looks "
                   "were there but the shooters missed — a *good pass to a poor "
                   "shooter*, not a bad passer.")
        st.dataframe(pd.DataFrame([{
            "Passer": table[pid]["name"], "Feeds": v["feeds"],
            "Look quality (xPPS)": round(v["xPPS_created"], 2),
            "Result (PPS)": round(v["PPS"], 2),
            "Finish Δ": round(v["finish_delta"], 2),
            "Assist FG%": round(v["FG%"] * 100),
        } for pid, v in _prows]), hide_index=True, width="stretch",
            column_config={
                "Finish Δ": st.column_config.NumberColumn(format="%+.2f"),
                "Assist FG%": st.column_config.NumberColumn(format="%d%%")})
        _best = _prows[0]
        st.caption(f"Top look-creator: **{table[_best[0]]['name']}** "
                   f"({_best[1]['xPPS_created']:.2f} xPPS created on "
                   f"{_best[1]['feeds']} feeds). Feeds this metric into the "
                   "playmaking read.")

    # ── boards: force-hand + space dependence ─────────────────────────────────
    bc1, bc2 = st.columns(2)
    with bc1:
        st.markdown("<div class='lab-hdr'>Force them off their hand</div>",
                    unsafe_allow_html=True)
        hb = []
        for pid in pids:
            row = table[pid]
            dom, weak = row.get("Dom_FG%"), row.get("Weak_FG%")
            dfa, wfa = row.get("Dom_FGA") or 0, row.get("Weak_FGA") or 0
            if dom is None or weak is None or dfa < 6 or wfa < 6:
                continue
            hb.append((dom - weak, row["name"], dom, weak, int(dfa + wfa)))
        hb.sort(key=lambda t: -t[0])
        if not hb:
            st.caption("Needs tap-located shots on both sides — fills in as games "
                       "are tagged with the court tap.")
        for gap, nm, dom, weak, n in hb[:8]:
            st.markdown(
                f"<div style='margin-bottom:7px'><div style='display:flex;"
                f"justify-content:space-between;font-size:12px'><b>{nm}</b>"
                f"<span style='color:var(--accent)'>+{gap:.0f} · n={n}</span></div>"
                f"<div style='font-size:10px;color:var(--subtext)'>strong {dom:.0f}% "
                f"· weak {weak:.0f}%</div>"
                f"<div class='pl-pct-track'><div class='pl-pct-fill' "
                f"style='width:{max(2,min(100,dom)):.0f}%;background:var(--good)'>"
                f"</div></div><div class='pl-pct-track' style='margin-top:2px'>"
                f"<div class='pl-pct-fill' style='width:{max(2,min(100,weak)):.0f}%;"
                f"background:var(--bad)'></div></div></div>", unsafe_allow_html=True)

    with bc2:
        st.markdown("<div class='lab-hdr'>Space dependence (open vs guarded)</div>",
                    unsafe_allow_html=True)
        cb = sorted(((cliffs[p]["cliff"], table[p]["name"], cliffs[p]["n"])
                     for p in pids if p in cliffs), key=lambda t: -t[0])
        if not cb:
            st.caption("Needs more contested shots (guarded tag) to rank.")
        for cliff, nm, n in cb[:10]:
            tag = ("needs space" if cliff > 8 else
                   "contest-proof" if cliff < -2 else "neutral")
            clr = ("var(--bad)" if cliff > 8 else
                   "var(--good)" if cliff < -2 else "var(--subtext)")
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:5px 0;"
                f"border-bottom:1px solid var(--card-border);font-size:12px'>"
                f"<span><b>{nm}</b> <span style='color:var(--subtext);font-size:10px'>"
                f"n={n}</span></span><span style='color:{clr}'>{cliff:+.0f} · {tag}</span>"
                f"</div>", unsafe_allow_html=True)

    # ── win impact (def / clutch WPA) for this team ───────────────────────────
    st.markdown("<div class='lab-hdr'>Who won games on defense</div>",
                unsafe_allow_html=True)
    irows = [{"pid": p, **impact[p]} for p in pids
             if p in impact and (impact[p].get("games") or 0) >= 4]
    if not irows:
        st.caption("Win-impact needs a few tracked games to separate signal "
                   "from noise.")
    else:
        irows.sort(key=lambda r: -(r.get("def_wpa") or 0))
        st.dataframe(pd.DataFrame([{
            "Player": r["name"], "GP": r.get("games"),
            "Def WPA": round(r.get("def_wpa") or 0, 2),
            "Off WPA": round(r.get("off_wpa") or 0, 2),
            "Clutch": round(r.get("clutch_wpa") or 0, 2),
        } for r in irows]), hide_index=True, width="stretch",
            column_config={
                "Def WPA": st.column_config.NumberColumn(format="%+.2f"),
                "Off WPA": st.column_config.NumberColumn(format="%+.2f"),
                "Clutch": st.column_config.NumberColumn(format="%+.2f")})

    # ── pick-&-roll role split (lights up with play_type tags) ────────────────
    rrows = []
    for pid in pids:
        pnr = (roles.get(pid) or {}).get("pnr")
        if not pnr:
            continue
        h, ro = pnr.get("handler", {}), pnr.get("roller", {})
        if (h.get("poss", 0) + ro.get("poss", 0)) < 1:
            continue
        rrows.append({"Player": table[pid]["name"],
                      "Handler PPP": round(h.get("PPP") or 0, 2),
                      "Handler FGA": h.get("poss", 0),
                      "Roller PPP": round(ro.get("PPP") or 0, 2),
                      "Roller FGA": ro.get("poss", 0)})
    if rrows:
        st.markdown("<div class='lab-hdr'>Pick-&-roll role split</div>",
                    unsafe_allow_html=True)
        st.caption("Ball-handler (used the screen) vs roll man (set it & finished). "
                   "Lights up as games are tagged with play type.")
        st.dataframe(pd.DataFrame(rrows), hide_index=True, width="stretch")
