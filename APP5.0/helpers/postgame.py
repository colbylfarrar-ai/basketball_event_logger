"""
postgame.py — a short plain-English POST-GAME read for one finished game.

The box score already has every number; this is the paragraph a coach would text
after the buzzer — who won and why (the four-factors battle), the run that
decided it, the standout performers (per-game RATING), and how wild the ride was
(GEI). It reuses the same engines as the rest of the app (team_analytics four
factors, game_rating, runs) so a bullet can never disagree with its own tab.

Pure read layer (sqlite + engines, no streamlit). Every bullet is built behind
its own guard, so a thin or half-logged game just yields fewer bullets — it
never raises.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S


def _pct(x):
    return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "—"


def _factor_battle(ff_h, ff_a, hn, an):
    """One bullet on the four-factors battle. Each factor scored for the team it
    favored (eFG/ORB/FTr higher = better, TOV lower = better); ties ignored."""
    # (label, home_val, away_val, higher_is_better, formatter)
    facs = [
        ("shooting (eFG%)", ff_h.get("eFG"), ff_a.get("eFG"), True, _pct),
        ("ball security (TOV%)", ff_h.get("TOV"), ff_a.get("TOV"), False, _pct),
        ("the offensive glass (ORB%)", ff_h.get("ORB"), ff_a.get("ORB"), True, _pct),
        ("the foul line (FT rate)", ff_h.get("FTR"), ff_a.get("FTR"), True,
         lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else "—"),
    ]
    hw, aw, edges = 0, 0, []
    for label, hv, av, hib, fmt in facs:
        if not isinstance(hv, (int, float)) or not isinstance(av, (int, float)):
            continue
        if hv == av:
            continue
        home_better = (hv > av) if hib else (hv < av)
        (edges.append((label, hn, fmt(hv), fmt(av)) if home_better
                       else (label, an, fmt(av), fmt(hv))))
        if home_better:
            hw += 1
        else:
            aw += 1
    if hw == aw:
        return None
    winner, loser = (hn, an) if hw > aw else (an, hn)
    won = [e for e in edges if e[1] == winner]
    # name the two biggest edges the winner owned
    detail = "; ".join(f"{lbl} ({w} vs {l})" for lbl, _who, w, l in won[:2])
    return (f"**{winner}** won the four-factors battle {max(hw, aw)}–{min(hw, aw)}"
            + (f" — {detail}." if detail else "."))


def _runs_bullet(events, id2name):
    import helpers.runs as RN
    runs = RN.detect_runs(events)
    if not runs:
        return None
    big = max(runs, key=lambda r: (r["points"], -r["margin_before"]))
    floor = getattr(RN, "BIG_RUN", 8)
    if big["points"] < floor:
        return None
    who = id2name.get(big["team_id"], "A team")
    q = big["q_start"]
    qlbl = f"OT{q - 4}" if q > 4 else f"Q{q}"
    return (f"**{who}** ripped off a **{big['points']}-0 run** in {qlbl} — the "
            f"game's biggest, and it swung the momentum.")


def _top_performers(game_id, events, id2team, id2name, hn, an):
    import helpers.game_rating as GR
    ratings = GR.season_game_ratings([game_id], events=events).get(game_id, {})
    if not ratings:
        return None
    best = {}
    for pid, r in ratings.items():
        tid = id2team.get(pid)
        if tid is None:
            continue
        if tid not in best or r["rating"] > best[tid][1]:
            best[tid] = (pid, r["rating"])
    parts = []
    for tid, (pid, rt) in best.items():
        parts.append(f"{id2name.get(pid, '#?')} ({rt:.1f})")
    if not parts:
        return None
    return "Top game RATING — " + ", ".join(parts) + "."


def game_report(game_id, *, events=None, gei=None):
    """Return a list of markdown bullet strings — the post-game read for one game.
    `gei` is an optional (value, label) tuple (the caller usually already has the
    WP summary); when given it adds an excitement line. Empty list on a game with
    nothing logged."""
    g = query(
        "SELECT g.team1_id, g.team2_id, g.home_score, g.away_score, "
        "       t1.name AS hn, t2.name AS an "
        "FROM games g JOIN teams t1 ON t1.id=g.team1_id "
        "             JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?", (game_id,))
    if not g:
        return []
    g = g[0]
    t1, t2, hn, an = g["team1_id"], g["team2_id"], g["hn"], g["an"]
    if events is None:
        events = S.fetch_events([game_id])
    if not events:
        return []
    id2name, id2team = {}, {}
    for p in query(
            "SELECT id, name, team_id FROM players WHERE team_id IN (?,?)", (t1, t2)):
        id2name[p["id"]] = p["name"]
        id2team[p["id"]] = p["team_id"]
    tname = {t1: hn, t2: an}

    bullets = []

    # headline: result + margin
    hs, as_ = g["home_score"], g["away_score"]
    if hs is not None and as_ is not None and hs != as_:
        win, ws, ls = (hn, hs, as_) if hs > as_ else (an, as_, hs)
        margin = ws - ls
        how = ("in a nail-biter" if margin <= 3 else
               "comfortably" if margin <= 12 else "in a rout")
        bullets.append(f"**{win}** won **{ws}–{ls}**, {how}.")

    # four factors (offense box for each side)
    try:
        import helpers.team_analytics as TA
        tb, ob = TA.team_and_opp_box(t1, [game_id], events=events)
        ff_h = TA.four_factors(tb, ob)["off"]
        ff_a = TA.four_factors(ob, tb)["off"]
        fb = _factor_battle(ff_h, ff_a, hn, an)
        if fb:
            bullets.append(fb)
    except Exception:
        pass

    # biggest run
    try:
        rb = _runs_bullet(events, tname)
        if rb:
            bullets.append(rb)
    except Exception:
        pass

    # standout performers by per-game RATING
    try:
        tp = _top_performers(game_id, events, id2team, id2name, hn, an)
        if tp:
            bullets.append(tp)
    except Exception:
        pass

    # excitement
    if gei and isinstance(gei, (tuple, list)) and gei[0] is not None:
        val, lbl = gei[0], (gei[1] if len(gei) > 1 else "")
        tail = f" — {lbl}" if lbl else ""
        bullets.append(f"Game Excitement Index **{val:.1f}**{tail}.")

    return bullets
