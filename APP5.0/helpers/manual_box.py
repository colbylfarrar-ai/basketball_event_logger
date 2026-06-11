"""
manual_box.py — hand-entered box scores for games NOT play-by-play tracked.

The Game Tracker is the only source of TRUE tracked stats (lineups, possession
length, zones, play types). But a plain box score still yields the possession
math the app cares about: a possession is one shot OR one turnover, so
POSSESSIONS = FGA + TOV — both in any box score. From entered totals we get
points-per-possession, ORtg/DRtg and the four factors; what we can't get is
anything needing the event stream.

Storage = manual_player_box (one row per player per game). These games are NEVER
marked games.tracked = 1, so the event-based engines ignore them; this module is
the parallel, clearly-labelled surface for entered boxes. Records & power
rankings already count any game with a final score, so entering a box adds the
detail on top.

Both engine (save/load/aggregate) and a small render live here — the mirror of
box_score.py for entered data.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from database.db import query, execute

# Editable counting columns (DB column names).
STAT_COLS = ["min", "fgm", "fga", "tpm", "tpa", "ftm", "fta",
             "oreb", "dreb", "ast", "stl", "blk", "tov", "pf"]


from helpers.stats import _safe   # shared definition lives in helpers.stats


# ── load / save ──────────────────────────────────────────────────────────────
def has_manual(game_id):
    return bool(query("SELECT 1 FROM manual_player_box WHERE game_id=? LIMIT 1",
                      (game_id,)))


def load_manual_box(game_id):
    """{team_id: [ {player_id, name, number, min, fgm, …} ]} for an entered game."""
    rows = query(
        """SELECT m.*, p.name, p.number FROM manual_player_box m
           JOIN players p ON p.id=m.player_id WHERE m.game_id=?
           ORDER BY p.number""", (game_id,))
    out = {}
    for r in rows:
        out.setdefault(r["team_id"], []).append(r)
    return out


def save_manual_box(game_id, team_id, rows):
    """Upsert one team's player boxes. `rows` = list of dicts with player_id +
    STAT_COLS. Rows that are all-zero are skipped (and removed if present)."""
    for r in rows:
        pid = r.get("player_id")
        if pid is None:
            continue
        vals = {k: int(r.get(k, 0) or 0) if k != "min" else float(r.get(k, 0) or 0)
                for k in STAT_COLS}
        if not any(vals.values()):
            execute("DELETE FROM manual_player_box WHERE game_id=? AND player_id=?",
                    (game_id, int(pid)))
            continue
        cols = ", ".join(STAT_COLS)
        ph = ", ".join("?" * len(STAT_COLS))
        execute(
            f"""INSERT INTO manual_player_box (game_id, team_id, player_id, {cols})
                VALUES (?,?,?,{ph})
                ON CONFLICT(game_id, player_id) DO UPDATE SET
                team_id=excluded.team_id,
                {", ".join(f"{c}=excluded.{c}" for c in STAT_COLS)}""",
            (game_id, int(team_id), int(pid)) + tuple(vals[k] for k in STAT_COLS))


# ── aggregation ──────────────────────────────────────────────────────────────
def _pts(d):
    return 2 * d["fgm"] + d["tpm"] + d["ftm"]


def team_totals(rows):
    """Sum a team's player rows into a totals dict + derived box/efficiency."""
    t = {k: 0 for k in STAT_COLS}
    for r in rows:
        for k in STAT_COLS:
            t[k] += r.get(k, 0) or 0
    t["TRB"] = t["oreb"] + t["dreb"]
    t["PTS"] = _pts(t)
    t["POSS"] = t["fga"] + t["tov"]            # locked rule: shot OR turnover
    t["FG%"] = _safe(t["fgm"], t["fga"]) * 100
    t["3P%"] = _safe(t["tpm"], t["tpa"]) * 100
    t["FT%"] = _safe(t["ftm"], t["fta"]) * 100
    t["eFG"] = _safe(t["fgm"] + 0.5 * t["tpm"], t["fga"]) * 100
    t["TS"] = _safe(t["PTS"], 2 * (t["fga"] + 0.44 * t["fta"])) * 100
    t["PPP"] = _safe(t["PTS"], t["POSS"])
    return t


def manual_team_profile(team_id):
    """
    Possession profile over a team's ENTERED games: own & opponent totals,
    possessions, PPP, ORtg/DRtg/Net and the four factors. Only games where both
    teams' boxes are entered contribute to the opponent/defense side.
    Returns None if the team has no entered games.
    """
    gids = [r["game_id"] for r in query(
        "SELECT DISTINCT game_id FROM manual_player_box WHERE team_id=?", (team_id,))]
    if not gids:
        return None
    own = {k: 0 for k in ("PTS", "POSS", "fga", "fgm", "tpm", "fta", "oreb",
                          "dreb", "tov")}
    opp = dict(own)
    games = opp_games = 0
    for gid in gids:
        box = load_manual_box(gid)
        if team_id not in box:
            continue
        games += 1
        ot = team_totals(box[team_id])
        for k in own:
            own[k] += ot[k] if k in ot else ot.get(k, 0)
        others = [tid for tid in box if tid != team_id]
        if others:
            opp_games += 1
            obx = team_totals(box[others[0]])
            for k in opp:
                opp[k] += obx[k] if k in obx else obx.get(k, 0)

    def _ff(o, d):
        return {
            "eFG": _safe(o["fgm"] + 0.5 * o["tpm"], o["fga"]) * 100,
            "TOVpct": _safe(o["tov"], o["fga"] + o["tov"]) * 100,
            "ORBpct": _safe(o["oreb"], o["oreb"] + d["dreb"]) * 100 if d["dreb"] or o["oreb"] else None,
            "FTr": _safe(o["fta"], o["fga"]),
            "PPP": _safe(o["PTS"], o["POSS"]),
        }
    out = {"games": games, "opp_games": opp_games, "own": own, "opp": opp,
           "PPP": _safe(own["PTS"], own["POSS"]),
           "ORtg": _safe(own["PTS"], own["POSS"]) * 100,
           "off_ff": _ff(own, opp)}
    if opp_games:
        out["oPPP"] = _safe(opp["PTS"], opp["POSS"])
        out["DRtg"] = _safe(opp["PTS"], opp["POSS"]) * 100
        out["Net"] = out["ORtg"] - out["DRtg"]
        out["def_ff"] = _ff(opp, own)
    return out


def combined_player_line(player_id, tracked_boxes=None):
    """
    A player's COMBINED counting line over tracked + entered games — the "include
    the games I only have a box score for" view. Pure box stats only (no
    event-derived ratings). Returns None if the player has no games, else
    {tracked_gp, manual_gp, gp, PPG, RPG, APG, SPG, BPG, FG%, 3P%, FT%, + totals}.
    """
    import helpers.stats as S
    if tracked_boxes is None:
        tracked_boxes = S.player_game_boxes()
    F = ["PTS", "TRB", "AST", "STL", "BLK", "TOV",
         "FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB"]
    tot = {f: 0 for f in F}
    tb = tracked_boxes.get(player_id, {})
    tgp = len(tb)
    for b in tb.values():
        for f in F:
            tot[f] += b.get(f, 0) or 0
    mrows = query("SELECT * FROM manual_player_box WHERE player_id=?", (player_id,))
    mgp = len(mrows)
    for r in mrows:
        tot["FGM"] += r["fgm"]; tot["FGA"] += r["fga"]
        tot["3PM"] += r["tpm"]; tot["3PA"] += r["tpa"]
        tot["FTM"] += r["ftm"]; tot["FTA"] += r["fta"]
        tot["OREB"] += r["oreb"]; tot["DREB"] += r["dreb"]
        tot["TRB"] += r["oreb"] + r["dreb"]
        tot["AST"] += r["ast"]; tot["STL"] += r["stl"]; tot["BLK"] += r["blk"]
        tot["TOV"] += r["tov"]; tot["PTS"] += 2 * r["fgm"] + r["tpm"] + r["ftm"]
    gp = tgp + mgp
    if gp == 0:
        return None
    return {
        "tracked_gp": tgp, "manual_gp": mgp, "gp": gp,
        "PPG": tot["PTS"] / gp, "RPG": tot["TRB"] / gp, "APG": tot["AST"] / gp,
        "SPG": tot["STL"] / gp, "BPG": tot["BLK"] / gp,
        "FG%": _safe(tot["FGM"], tot["FGA"]) * 100,
        "3P%": _safe(tot["3PM"], tot["3PA"]) * 100,
        "FT%": _safe(tot["FTM"], tot["FTA"]) * 100, **tot}


# ── render (entered box score) ───────────────────────────────────────────────
def render_manual_box(game_id, accent="#f0a500", away="#e74c3c"):
    """A lite box-score view for an ENTERED (untracked) game."""
    box = load_manual_box(game_id)
    g = query("""SELECT g.date, g.team1_id, g.team2_id, t1.name n1, t2.name n2
                 FROM games g JOIN teams t1 ON t1.id=g.team1_id
                              JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?""",
              (game_id,))
    if not g:
        st.info("Game not found.")
        return
    g = g[0]
    t1id, t2id = g["team1_id"], g["team2_id"]
    if not box:
        st.info("No box score entered for this game yet — add one on the Setup page.")
        return
    t1 = team_totals(box.get(t1id, []))
    t2 = team_totals(box.get(t2id, []))

    st.markdown(
        f"<div class='glass-tile'><b>{g['n1']} {t1['PTS']} – {t2['PTS']} {g['n2']}</b>"
        f" · <span style='color:#8b949e'>entered box score (not play-by-play "
        f"tracked) · {g['date'] or ''}</span></div>", unsafe_allow_html=True)

    fc = st.columns(4)
    fc[0].metric(f"{g['n1']} PPP", f"{t1['PPP']:.2f}")
    fc[1].metric(f"{g['n1']} eFG%", f"{t1['eFG']:.0f}%")
    fc[2].metric(f"{g['n2']} PPP", f"{t2['PPP']:.2f}")
    fc[3].metric(f"{g['n2']} eFG%", f"{t2['eFG']:.0f}%")

    def _ptable(team_id, label):
        rows = box.get(team_id, [])
        if not rows:
            st.caption(f"{label}: no box entered.")
            return
        df = pd.DataFrame([{
            "#": r["number"], "Player": r["name"], "MIN": r["min"],
            "PTS": _pts(r), "FG": f"{r['fgm']}/{r['fga']}",
            "3P": f"{r['tpm']}/{r['tpa']}", "FT": f"{r['ftm']}/{r['fta']}",
            "REB": r["oreb"] + r["dreb"], "AST": r["ast"], "STL": r["stl"],
            "BLK": r["blk"], "TOV": r["tov"], "PF": r["pf"],
        } for r in rows])
        st.markdown(f"**{label}**")
        st.dataframe(df, hide_index=True, width="stretch",
                     key=f"mb_{game_id}_{team_id}")

    _ptable(t1id, g["n1"])
    _ptable(t2id, g["n2"])
    st.caption("Possessions = FGA + TOV · PPP = points per possession. From "
               "entered totals; lineup / play-type stats need the Game Tracker.")
