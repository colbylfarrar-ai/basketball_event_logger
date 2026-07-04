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
the parallel, clearly-labelled surface for entered boxes. TRACKED WINS: if a game
is play-by-play tracked after a box was entered, its manual rows are ignored by
every aggregate here (g.tracked=0 filters) — the event stream is the truth. Records & power
rankings already count any game with a final score, so entering a box adds the
detail on top.

Both engine (save/load/aggregate) and a small render live here — the mirror of
box_score.py for entered data.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from database.db import query, execute
import helpers.auth as AUTH
import helpers.entitlement as ENT

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


# ── CSV import (round-trips the MaxPreps export from box_score.py) ──────────
def _split_made_att(val):
    """'5-11' → (5, 11). Tolerates blanks, plain numbers and floats."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0, 0
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return 0, 0
    if "-" in s:
        a, b = s.split("-", 1)
        try:
            return int(float(a)), int(float(b))
        except ValueError:
            return 0, 0
    try:
        return int(float(s)), 0
    except ValueError:
        return 0, 0


def parse_maxpreps_csv(df, team_names, rosters):
    """Parse a box CSV in the app's MaxPreps export shape (Team, #, Player,
    MIN, PTS, FG, 3P, FT, ORB, DRB, AST, STL, BLK, TOV, PF) into
    save_manual_box row dicts.

    team_names: {team_id: display name} for the game's two teams.
    rosters:    {team_id: [{id, number, name}, …]}.

    Returns ({team_id: [ {player_id, **STAT_COLS} ]}, problems). Players match
    by jersey number first, then exact name. Percent and derived columns
    (PTS, REB, FG% …) are ignored, except PTS which is cross-checked against
    the FG/3P/FT math. Rows that can't be matched or fail makes ≤ attempts are
    skipped with a problem string; a REB-only CSV imports REB as DRB.
    """
    cols = {str(c).strip().lower(): c for c in df.columns}

    def col(*names):
        for n in names:
            if n.lower() in cols:
                return cols[n.lower()]
        return None

    problems, rows_by_team = [], {}
    c_team = col("Team")
    c_num, c_name = col("#", "No", "Number"), col("Player", "Name")
    if c_team is None or (c_num is None and c_name is None):
        return {}, ["CSV needs a Team column plus a # or Player column."]

    have_split = col("ORB") is not None and col("DRB") is not None
    if not have_split and col("REB") is not None:
        problems.append("No ORB/DRB columns — total REB imported as DRB "
                        "(OREB% in the four factors will read low).")

    name_to_tid = {str(n).strip().casefold(): tid for tid, n in team_names.items()}
    unmatched_teams = set()

    for _, r in df.iterrows():
        pname = ("" if c_name is None or pd.isna(r[c_name])
                 else str(r[c_name]).strip())
        if pname.upper() == "TOTAL":
            continue
        tid = name_to_tid.get(str(r[c_team]).strip().casefold())
        if tid is None:
            unmatched_teams.add(str(r[c_team]).strip())
            continue

        num = None
        if c_num is not None and not pd.isna(r[c_num]):
            try:
                num = int(float(r[c_num]))
            except (TypeError, ValueError):
                num = None
        pid = next((p["id"] for p in rosters.get(tid, [])
                    if num is not None and p["number"] == num), None)
        if pid is None and pname:
            pid = next((p["id"] for p in rosters.get(tid, [])
                        if str(p["name"]).strip().casefold() == pname.casefold()),
                       None)
        label = f"#{num if num is not None else '?'} {pname or '?'}"
        if pid is None:
            problems.append(f"{team_names[tid]}: no roster match for {label} — "
                            "row skipped.")
            continue

        def _i(name):
            c = col(name)
            if c is None or pd.isna(r[c]):
                return 0
            try:
                return int(float(r[c]))
            except (TypeError, ValueError):
                return 0

        fgm, fga = _split_made_att(r[col("FG")]) if col("FG") else (0, 0)
        tpm, tpa = _split_made_att(r[col("3P")]) if col("3P") else (0, 0)
        ftm, fta = _split_made_att(r[col("FT")]) if col("FT") else (0, 0)
        if fgm > fga or tpm > tpa or ftm > fta or tpm > fgm or tpa > fga:
            problems.append(f"{team_names[tid]} {label}: makes exceed attempts "
                            "(or 3P exceed FG) — row skipped.")
            continue

        c_min = col("MIN")
        try:
            mins = 0.0 if c_min is None or pd.isna(r[c_min]) else float(r[c_min])
        except (TypeError, ValueError):
            mins = 0.0
        row = {"player_id": pid, "min": mins,
               "fgm": fgm, "fga": fga, "tpm": tpm, "tpa": tpa,
               "ftm": ftm, "fta": fta,
               "oreb": _i("ORB") if have_split else 0,
               "dreb": _i("DRB") if have_split else _i("REB"),
               "ast": _i("AST"), "stl": _i("STL"), "blk": _i("BLK"),
               "tov": _i("TOV"), "pf": _i("PF")}
        csv_pts = _i("PTS")
        if csv_pts and csv_pts != _pts(row):
            problems.append(f"{team_names[tid]} {label}: CSV PTS {csv_pts} ≠ "
                            f"FG/3P/FT math {_pts(row)} — imported anyway; "
                            "check the shooting columns.")
        rows_by_team.setdefault(tid, []).append(row)

    for t in sorted(unmatched_teams):
        problems.append(f"Team '{t}' in the CSV doesn't match either team in "
                        f"this game ({' / '.join(team_names.values())}) — rows "
                        "skipped.")
    return rows_by_team, problems


def maxpreps_df(game_id, team_names):
    """Entered box → a MaxPreps-format DataFrame (the same column shape
    box_score.py exports and parse_maxpreps_csv reads back — a full round
    trip). team_names = {team_id: display name}; teams ordered as given.
    Returns None when the game has no entered box."""
    box = load_manual_box(game_id)
    rows = []
    for tid, nm in team_names.items():
        for r in box.get(tid, []):
            rows.append({
                "Team": nm, "#": r["number"], "Player": r["name"],
                "MIN": r["min"], "PTS": _pts(r),
                "FG": f"{r['fgm']}-{r['fga']}",
                "FG%": round(100 * _safe(r["fgm"], r["fga"]), 1),
                "3P": f"{r['tpm']}-{r['tpa']}",
                "3P%": round(100 * _safe(r["tpm"], r["tpa"]), 1),
                "FT": f"{r['ftm']}-{r['fta']}",
                "FT%": round(100 * _safe(r["ftm"], r["fta"]), 1),
                "ORB": r["oreb"], "DRB": r["dreb"],
                "REB": r["oreb"] + r["dreb"],
                "AST": r["ast"], "STL": r["stl"], "BLK": r["blk"],
                "TOV": r["tov"], "PF": r["pf"]})
    if not rows:
        return None
    cols = ["Team", "#", "Player", "MIN", "PTS", "FG", "FG%", "3P", "3P%",
            "FT", "FT%", "ORB", "DRB", "REB", "AST", "STL", "BLK", "TOV", "PF"]
    return pd.DataFrame(rows, columns=cols)


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
    # tracked=0 guard: a game tracked AFTER its box was entered leaves stale
    # manual rows behind — the tracked event stream wins, so those games are
    # excluded here (and in combined_player_line) or they'd count twice.
    gids = [r["game_id"] for r in query(
        """SELECT DISTINCT m.game_id FROM manual_player_box m
           JOIN games g ON g.id=m.game_id
           WHERE m.team_id=? AND g.tracked=0""", (team_id,))]
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
    mrows = query(
        """SELECT m.* FROM manual_player_box m JOIN games g ON g.id=m.game_id
           WHERE m.player_id=? AND g.tracked=0""", (player_id,))
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

    # PPP is possession-derived (POSS = FGA+TOV) → Paid per the carve-out. eFG%
    # (pure shooting) is box-derivable → Free. Show both for paid, eFG% only free.
    if ENT.has_paid_plan(AUTH.current_user()):
        fc = st.columns(4)
        fc[0].metric(f"{g['n1']} PPP", f"{t1['PPP']:.2f}")
        fc[1].metric(f"{g['n1']} eFG%", f"{t1['eFG']:.0f}%")
        fc[2].metric(f"{g['n2']} PPP", f"{t2['PPP']:.2f}")
        fc[3].metric(f"{g['n2']} eFG%", f"{t2['eFG']:.0f}%")
    else:
        fc = st.columns(2)
        fc[0].metric(f"{g['n1']} eFG%", f"{t1['eFG']:.0f}%")
        fc[1].metric(f"{g['n2']} eFG%", f"{t2['eFG']:.0f}%")

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
