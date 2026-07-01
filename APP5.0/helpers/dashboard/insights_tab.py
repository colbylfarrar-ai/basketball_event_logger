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


def _pct(v):
    return f"{v * 100:.0f}%" if v is not None else "—"


@st.fragment
def render(ctx):
    if not getattr(ctx, "has_tracked", False):
        st.info("🔒 Insights read tracked play-by-play (shot quality, contest "
                "splits, win-impact). Track this team's games — or unlock the "
                "Paid tier — to light them up.")
        return

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

        def _drow(label, key, fmt):
            tv, bv = _tp.get(key), _bt.get(key)
            return {"Metric": label,
                    f"vs Top-half ({_ss['top_games']}g)": fmt(tv),
                    f"vs Bottom-half ({_ss['bottom_games']}g)": fmt(bv)}
        _f2 = lambda v: f"{v:.2f}" if v is not None else "—"
        rows = [
            _drow("PPP (pts/shot)", "PPP", _f2),
            _drow("eFG%", "eFG", _pct),
            _drow("Scoring eff (SCE)", "SCE", _pct),
            _drow("3PA rate", "3PA_rate", _pct),
            _drow("Rim rate", "rim_rate", _pct),
            _drow("Assisted rate", "ast_rate", _pct),
            _drow("Open rate", "open_rate", _pct),
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
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
