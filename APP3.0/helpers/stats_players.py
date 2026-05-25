"""
Player-level aggregate stats for Rankings page leaderboards.
Also: per-game box score, official stats.
"""
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st
from Database.db import query
from collections import defaultdict
from helpers.constants import SHOT_RATING


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYER RANKINGS (all tracked games)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def compute_player_rankings() -> pd.DataFrame:
    """Per-player per-game averages across all tracked games."""
    players = query("""
        SELECT p.id, p.name, p.number, p.team_id,
               t.name as team_name, t.class, t.gender
        FROM players p JOIN teams t ON t.id=p.team_id
        WHERE p.archived=0
    """)
    if not players:
        return pd.DataFrame()

    pid_info = {p["id"]: p for p in players}
    pid_team  = {p["id"]: p["team_id"] for p in players}

    # Which players appeared in which tracked games (via lineup snapshots)
    appearances = query("""
        SELECT DISTINCT glp.player_id, glp.game_id
        FROM game_lineup_players glp
        JOIN games g ON g.id=glp.game_id
        WHERE g.tracked=1
    """)
    player_games: dict = defaultdict(set)
    for a in appearances:
        player_games[a["player_id"]].add(a["game_id"])

    # All events from tracked games
    events = query("""
        SELECT ge.game_id,
               ge.primary_player_id   AS pid,
               ge.secondary_player_id AS sec_pid,
               ge.event_type, ge.shot_type, ge.shot_result,
               ge.pass_from_id, ge.blocked_by_id,
               ge.stolen_by_id, ge.rebound_by_id, ge.quarter,
               ge.shot_created_by_id, ge.zone, ge.guarded_by_id
        FROM game_events ge
        JOIN games g ON g.id=ge.game_id
        WHERE g.tracked=1
    """)

    def _blank():
        return dict(pts=0, fgm=0, fga=0, tpm=0, tpa=0, ftm=0, fta=0,
                    ast=0, oreb=0, dreb=0, stl=0, blk=0, tov=0, pf=0, q4_pts=0,
                    sc=0, shot_rating=0.0, shot_rating_n=0)

    stats: dict = defaultdict(_blank)

    for ev in events:
        pid   = ev["pid"]
        etype = ev["event_type"]

        if etype == "shot":
            if pid and pid in pid_info:
                s = stats[pid]
                s["fga"] += 1
                s["sc"]  += 1   # shooter always gets 1 SC
                if ev["shot_type"] == 3:
                    s["tpa"] += 1
                if ev["shot_result"] == "make":
                    pts = ev["shot_type"]
                    s["fgm"] += 1
                    s["pts"] += pts
                    if ev["shot_type"] == 3:
                        s["tpm"] += 1
                    if ev["quarter"] == 4:
                        s["q4_pts"] += pts
                    passer = ev["pass_from_id"]
                    if passer and passer in pid_info:
                        stats[passer]["ast"] += 1
                # Shot rating (zone + creation context)
                if ev["zone"] and ev["shot_type"]:
                    _con  = bool(ev["guarded_by_id"])
                    _key  = (ev["shot_type"], ev["zone"], _con)
                    _hp   = bool(ev["pass_from_id"])
                    _hc   = bool(ev["shot_created_by_id"])
                    if _hp and _hc:    _r_mod = +0.30
                    elif _hp:          _r_mod = +0.15
                    elif _hc:          _r_mod = +0.08
                    else:              _r_mod = -0.10
                    s["shot_rating"]   += SHOT_RATING.get(_key, 0.0) + _r_mod
                    s["shot_rating_n"] += 1
            # Passer and shot creator also earn SC
            pf = ev["pass_from_id"]
            if pf and pf in pid_info and pf != pid:
                stats[pf]["sc"] += 1
            scb = ev["shot_created_by_id"]
            if scb and scb in pid_info and scb != pid:
                stats[scb]["sc"] += 1
            blk = ev["blocked_by_id"]
            if blk and blk in pid_info:
                stats[blk]["blk"] += 1
            reb = ev["rebound_by_id"]
            if reb and pid and reb in pid_info:
                sh_t = pid_team.get(pid)
                rb_t = pid_team.get(reb)
                if sh_t and rb_t:
                    stats[reb]["oreb" if sh_t == rb_t else "dreb"] += 1

        elif etype == "free_throw":
            if pid and pid in pid_info:
                s = stats[pid]
                s["fta"] += 1
                if ev["shot_result"] == "make":
                    s["ftm"] += 1
                    s["pts"] += 1
                    if ev["quarter"] == 4:
                        s["q4_pts"] += 1
            reb = ev["rebound_by_id"]
            if reb and pid and reb in pid_info:
                sh_t = pid_team.get(pid)
                rb_t = pid_team.get(reb)
                if sh_t and rb_t:
                    stats[reb]["oreb" if sh_t == rb_t else "dreb"] += 1

        elif etype == "turnover":
            if pid and pid in pid_info:
                stats[pid]["tov"] += 1
            stl = ev["stolen_by_id"]
            if stl and stl in pid_info:
                stats[stl]["stl"] += 1

        elif etype == "foul":
            fouler = ev["sec_pid"]
            if fouler and fouler in pid_info:
                stats[fouler]["pf"] += 1

    # Plus / minus totals
    pm_rows = query("""
        SELECT glp.player_id, SUM(glp.plus_minus) AS total_pm
        FROM game_lineup_players glp
        JOIN games g ON g.id=glp.game_id
        WHERE g.tracked=1
        GROUP BY glp.player_id
    """)
    pm_map = {r["player_id"]: (r["total_pm"] or 0) for r in pm_rows}

    # Minutes (possession seconds summed from event lineup snapshots)
    mins_rows = query("""
        SELECT gel.player_id, SUM(ge.possession_secs) AS secs
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id=gel.event_id
        JOIN games g ON g.id=ge.game_id
        WHERE g.tracked=1 AND ge.possession_secs > 0
        GROUP BY gel.player_id
    """)
    mins_map = {r["player_id"]: (r["secs"] or 0) / 60 for r in mins_rows}

    # Paint shots — zone-C 2-pointers used as paint-area proxy
    paint_rows = query("""
        SELECT ge.primary_player_id AS pid,
               COUNT(*) AS pfga,
               SUM(CASE WHEN ge.shot_result='make' THEN 1 ELSE 0 END) AS pfgm
        FROM game_events ge
        JOIN games g ON g.id=ge.game_id
        WHERE g.tracked=1 AND ge.event_type='shot'
          AND ge.zone='C' AND ge.shot_type=2
          AND ge.primary_player_id IS NOT NULL
        GROUP BY ge.primary_player_id
    """)
    paint_fga_map = {r["pid"]: r["pfga"] for r in paint_rows}
    paint_fgm_map = {r["pid"]: r["pfgm"] for r in paint_rows}

    # Shot contest — how often each player was the listed defender on an opp shot
    def_rows = query("""
        SELECT ge.guarded_by_id AS pid, COUNT(*) AS def_fga
        FROM game_events ge
        JOIN games g ON g.id = ge.game_id
        WHERE g.tracked = 1
          AND ge.event_type = 'shot'
          AND ge.guarded_by_id IS NOT NULL
        GROUP BY ge.guarded_by_id
    """)
    def_fga_map = {r["pid"]: r["def_fga"] for r in def_rows}

    # Opponent shots while each player was on court (denominator for DSh%)
    # Uses game_event_lineup snapshots: player_id present → on court for that event
    oc_opp_rows = query("""
        SELECT gel.player_id AS pid, COUNT(*) AS opp_shots
        FROM game_event_lineup gel
        JOIN game_events ge   ON ge.id  = gel.event_id
        JOIN players p_shot   ON p_shot.id = ge.primary_player_id
        JOIN players p_def    ON p_def.id  = gel.player_id
        JOIN games g          ON g.id  = ge.game_id
        WHERE g.tracked = 1
          AND ge.event_type = 'shot'
          AND p_shot.team_id != p_def.team_id
        GROUP BY gel.player_id
    """)
    oc_opp_map = {r["pid"]: r["opp_shots"] for r in oc_opp_rows}

    rows = []
    for pid, s in stats.items():
        info = pid_info.get(pid)
        if not info:
            continue
        gp = len(player_games.get(pid, set()))
        if gp == 0:
            continue

        reb       = s["oreb"] + s["dreb"]
        total_min = mins_map.get(pid, 0)
        mins_pg   = total_min / gp if gp else 0
        pm        = pm_map.get(pid, 0)

        fg_pct = s["fgm"] / s["fga"] * 100 if s["fga"] else 0
        tp_pct = s["tpm"] / s["tpa"] * 100 if s["tpa"] else 0
        ft_pct = s["ftm"] / s["fta"] * 100 if s["fta"] else 0
        efg    = (s["fgm"] + 0.5 * s["tpm"]) / s["fga"] * 100 if s["fga"] else 0
        ts_d   = 2 * (s["fga"] + 0.44 * s["fta"])
        ts     = s["pts"] / ts_d * 100 if ts_d else 0
        gs_tot = (s["pts"] + 0.4*s["fgm"] - 0.7*s["fga"]
                  - 0.4*(s["fta"]-s["ftm"]) + 0.7*s["oreb"] + 0.3*s["dreb"]
                  + s["stl"] + 0.7*s["ast"] + 0.7*s["blk"]
                  - 0.4*s["pf"] - s["tov"])

        # Per-32 (only for players with ≥5 min/g)
        p32 = 32 / mins_pg if mins_pg >= 5 else None

        # ── Additional advanced metrics ────────────────────────────────────────
        # Free Throw Rate (drawing fouls)
        ftr = round(s["fta"] / s["fga"], 2) if s["fga"] else 0.0

        # Points Per Shot (raw scoring efficiency per FGA)
        pps = round(s["pts"] / s["fga"], 2) if s["fga"] else 0.0

        # Points Per Scoring Attempt (includes FT trips)
        _ppsa_d = s["fga"] + 0.44 * s["fta"]
        ppsa    = round(s["pts"] / _ppsa_d, 2) if _ppsa_d else 0.0

        # Turnover Rate (% of possessions ending in TOV)
        _tov_d  = s["fga"] + 0.44 * s["fta"] + s["tov"]
        tov_pct = round(s["tov"] / _tov_d * 100, 1) if _tov_d else 0.0

        # Usage Volume per game (proxy for USG% without team data)
        usg_vol = round(_tov_d / gp, 1)

        # NBA Efficiency (PTS+REB+AST+STL+BLK - missed FG - missed FT - TOV)
        _eff_raw = (s["pts"] + reb + s["ast"] + s["stl"] + s["blk"]
                    - (s["fga"] - s["fgm"]) - (s["fta"] - s["ftm"]) - s["tov"])
        eff_pg = round(_eff_raw / gp, 1)

        # Floor Impact Counter (Hollinger-style composite)
        _fic_raw = (s["fgm"] * 2   + s["tpm"] * 0.5  + s["ftm"]
                    + s["oreb"] * 1.2 + s["dreb"] * 0.8
                    + s["blk"]  * 3.0 + s["stl"]  * 3.0
                    + s["ast"]  * 1.5
                    - s["tov"]  * 2.0
                    - (s["fga"] - s["fgm"]) * 1.0
                    - (s["fta"] - s["ftm"]) * 0.5)
        fic_pg = round(_fic_raw / gp, 1)

        # Points Responsible For (own pts + assisted pts estimated at 2 pts each)
        prf = round((s["pts"] + s["ast"] * 2.0) / gp, 1)

        # 2-point splits
        _twopm = s["fgm"] - s["tpm"]
        _twopa = s["fga"] - s["tpa"]
        twopc  = round(_twopm / _twopa * 100, 1) if _twopa else 0.0

        # Stocks per game (STL + BLK)
        stocks_pg = round((s["stl"] + s["blk"]) / gp, 1)

        # AST/TOV ratio
        ast_tov_r = round(s["ast"] / s["tov"], 2) if s["tov"] else round(s["ast"] / 0.5, 1)

        # Double-doubles & triple-doubles approximated from career totals
        # (can't count per-game instances from aggregates, so skip)

        row = {
            "pid":    pid,
            "Player": info["name"],
            "#":      info["number"],
            "Team":   info["team_name"],
            "Class":  info["class"] or "—",
            "Gender": info["gender"] or "—",
            "GP":     gp,
            "MIN":    round(mins_pg, 1),
            # per-game
            "PTS":    round(s["pts"]  / gp, 1),
            "REB":    round(reb       / gp, 1),
            "AST":    round(s["ast"]  / gp, 1),
            "OREB":   round(s["oreb"] / gp, 1),
            "DREB":   round(s["dreb"] / gp, 1),
            "STL":    round(s["stl"]  / gp, 1),
            "BLK":    round(s["blk"]  / gp, 1),
            "TOV":    round(s["tov"]  / gp, 1),
            "PF":     round(s["pf"]   / gp, 1),
            # shooting
            "FGM":    round(s["fgm"]  / gp, 1),
            "FGA":    round(s["fga"]  / gp, 1),
            "FG%":    round(fg_pct,   1),
            "3PM":    round(s["tpm"]  / gp, 1),
            "3PA":    round(s["tpa"]  / gp, 1),
            "3P%":    round(tp_pct,   1),
            "FTM":    round(s["ftm"]  / gp, 1),
            "FTA":    round(s["fta"]  / gp, 1),
            "FT%":    round(ft_pct,   1),
            "eFG%":   round(efg,      1),
            "TS%":    round(ts,       1),
            # advanced
            "+/-":    round(pm / gp,  1),
            "GS":     round(gs_tot / gp, 1),
            "Q4 PPG": round(s["q4_pts"] / gp, 1),
            "SC":     round(s["sc"] / gp, 1),
            "ShotRat": round(s["shot_rating"] / s["shot_rating_n"], 2)
                       if s["shot_rating_n"] else 0.0,
            # per-32 helpers
            "PTS32":  round(s["pts"]  / total_min * 32, 1) if p32 and total_min else None,
            "REB32":  round(reb       / total_min * 32, 1) if p32 and total_min else None,
            "AST32":  round(s["ast"]  / total_min * 32, 1) if p32 and total_min else None,
            "STL32":  round(s["stl"]  / total_min * 32, 1) if p32 and total_min else None,
            "BLK32":  round(s["blk"]  / total_min * 32, 1) if p32 and total_min else None,
            "TOV32":  round(s["tov"]  / total_min * 32, 1) if p32 and total_min else None,
            "SC32":   round(s["sc"]   / total_min * 32, 1) if p32 and total_min else None,
            # 2PT splits
            "2PM":   round(_twopm / gp, 1),
            "2PA":   round(_twopa / gp, 1),
            "2P%":   twopc,
            # paint / shot-selection helpers (used by position ratings)
            "PaintFGA":  round(paint_fga_map.get(pid, 0) / gp, 1),
            "PaintFGM":  round(paint_fgm_map.get(pid, 0) / gp, 1),
            "PaintFG%":  round(paint_fgm_map.get(pid, 0) / paint_fga_map[pid] * 100, 1)
                         if paint_fga_map.get(pid, 0) else 0.0,
            "3PAr":      round(s["tpa"] / s["fga"] * 100, 1) if s["fga"] else 0.0,
            # Shot contest % — defended shots ÷ total opp shots while on court
            "DSh%":      round(def_fga_map.get(pid, 0) / oc_opp_map[pid] * 100, 1)
                         if oc_opp_map.get(pid, 0) else 0.0,
            # ── New advanced metrics ──────────────────────────────────────────
            "FTr":    ftr,          # Free Throw Rate (FTA/FGA)
            "PPS":    pps,          # Points Per Shot
            "PPSA":   ppsa,         # Points Per Scoring Attempt
            "TOV%":   tov_pct,      # Turnover Rate %
            "USG":    usg_vol,      # Usage Volume per game
            "EFF":    eff_pg,       # NBA Efficiency
            "FIC":    fic_pg,       # Floor Impact Counter
            "PRF":    prf,          # Points Responsible For (PTS + AST*2)
            "Stocks": stocks_pg,    # Stocks (STL+BLK) per game
            "AST/TOV": ast_tov_r,  # Assist-to-Turnover ratio
        }
        rows.append(row)

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  PER-GAME BOX SCORE (single game)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def compute_game_box_score(game_id: int):
    """
    Player-level box score for one game.
    Returns (df_team1, df_team2, game_info_dict).
    """
    game_rows = query("""
        SELECT g.id, g.date, g.home_score, g.away_score, g.tracked,
               t1.id AS t1id, t1.name AS t1name,
               t2.id AS t2id, t2.name AS t2name
        FROM games g
        JOIN teams t1 ON t1.id=g.team1_id
        JOIN teams t2 ON t2.id=g.team2_id
        WHERE g.id=?
    """, (game_id,))
    if not game_rows:
        return pd.DataFrame(), pd.DataFrame(), {}

    g     = game_rows[0]
    t1id  = g["t1id"]
    t2id  = g["t2id"]

    # Players who appeared (via lineup snapshots)
    players = query("""
        SELECT DISTINCT p.id, p.name, p.number, p.team_id
        FROM game_lineup_players glp
        JOIN players p ON p.id=glp.player_id
        WHERE glp.game_id=?
        ORDER BY p.team_id, p.number, p.name
    """, (game_id,))

    pid_info = {p["id"]: p for p in players}
    pid_team  = {p["id"]: p["team_id"] for p in players}

    def _blank():
        return dict(pts=0, fgm=0, fga=0, tpm=0, tpa=0, ftm=0, fta=0,
                    ast=0, oreb=0, dreb=0, stl=0, blk=0, tov=0, pf=0,
                    ast_fgm=0, unast_fgm=0)

    stats: dict = defaultdict(_blank)

    events = query("""
        SELECT event_type,
               primary_player_id   AS pid,
               secondary_player_id AS sec_pid,
               shot_type, shot_result,
               pass_from_id, blocked_by_id,
               stolen_by_id, rebound_by_id
        FROM game_events WHERE game_id=? ORDER BY id
    """, (game_id,))

    for ev in events:
        pid   = ev["pid"]
        etype = ev["event_type"]

        if etype == "shot":
            if pid and pid in pid_info:
                s = stats[pid]
                s["fga"] += 1
                if ev["shot_type"] == 3:
                    s["tpa"] += 1
                if ev["shot_result"] == "make":
                    s["fgm"] += 1
                    s["pts"] += ev["shot_type"]
                    if ev["shot_type"] == 3:
                        s["tpm"] += 1
                    passer = ev["pass_from_id"]
                    if passer and passer in pid_info:
                        stats[passer]["ast"] += 1
                        s["ast_fgm"] += 1   # assisted make
                    else:
                        s["unast_fgm"] += 1  # self-created make
            blk = ev["blocked_by_id"]
            if blk and blk in pid_info:
                stats[blk]["blk"] += 1
            reb = ev["rebound_by_id"]
            if reb and pid and reb in pid_info:
                sh_t = pid_team.get(pid)
                rb_t = pid_team.get(reb)
                if sh_t and rb_t:
                    stats[reb]["oreb" if sh_t == rb_t else "dreb"] += 1

        elif etype == "free_throw":
            if pid and pid in pid_info:
                s = stats[pid]
                s["fta"] += 1
                if ev["shot_result"] == "make":
                    s["ftm"] += 1
                    s["pts"] += 1
            reb = ev["rebound_by_id"]
            if reb and pid and reb in pid_info:
                sh_t = pid_team.get(pid)
                rb_t = pid_team.get(reb)
                if sh_t and rb_t:
                    stats[reb]["oreb" if sh_t == rb_t else "dreb"] += 1

        elif etype == "turnover":
            if pid and pid in pid_info:
                stats[pid]["tov"] += 1
            stl = ev["stolen_by_id"]
            if stl and stl in pid_info:
                stats[stl]["stl"] += 1

        elif etype == "foul":
            fouler = ev["sec_pid"]
            if fouler and fouler in pid_info:
                stats[fouler]["pf"] += 1

    pm_rows = query(
        "SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?",
        (game_id,))
    pm_map = {r["player_id"]: (r["plus_minus"] or 0) for r in pm_rows}

    mins_rows = query("""
        SELECT gel.player_id, ROUND(SUM(ge.possession_secs)/60.0, 1) AS mins
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id=gel.event_id
        WHERE ge.game_id=? AND ge.possession_secs > 0
        GROUP BY gel.player_id
    """, (game_id,))
    mins_map = {r["player_id"]: (r["mins"] or 0.0) for r in mins_rows}

    def _build_team_rows(team_id):
        rows = []
        for p in players:
            if p["team_id"] != team_id:
                continue
            pid  = p["id"]
            s    = stats.get(pid, _blank())
            fgm, fga = s["fgm"], s["fga"]
            tpm, tpa = s["tpm"], s["tpa"]
            ftm, fta = s["ftm"], s["fta"]
            pts      = s["pts"]
            reb      = s["oreb"] + s["dreb"]
            mins     = mins_map.get(pid, 0.0)
            pm       = pm_map.get(pid, 0)
            # Advanced metrics
            efg  = round((fgm + 0.5*tpm) / fga * 100, 1) if fga else None
            ts_d = 2 * (fga + 0.44 * fta)
            ts   = round(pts / ts_d * 100, 1) if ts_d > 0 else None
            gs   = round(pts + 0.4*fgm - 0.7*fga - 0.4*(fta-ftm)
                         + 0.7*s["oreb"] + 0.3*s["dreb"] + s["stl"]
                         + 0.7*s["ast"] + 0.7*s["blk"] - 0.4*s["pf"] - s["tov"], 1)
            ast_fgm   = s["ast_fgm"]
            unast_fgm = s["unast_fgm"]
            w_pass  = round(ast_fgm   / fga * 100, 1) if fga else None
            wo_pass = round(unast_fgm / fga * 100, 1) if fga else None
            rows.append({
                "_pid":     pid,
                "_totals":  False,
                "Player":   f"#{p['number']} {p['name']}",
                "MIN":      mins,
                "PTS":      pts,
                "OREB":     s["oreb"],
                "DREB":     s["dreb"],
                "REB":      reb,
                "AST":      s["ast"],
                "STL":      s["stl"],
                "BLK":      s["blk"],
                "TOV":      s["tov"],
                "PF":       s["pf"],
                "FGM":      fgm,
                "FGA":      fga,
                "3PM":      tpm,
                "3PA":      tpa,
                "FTM":      ftm,
                "FTA":      fta,
                "+/-":      pm,
                "eFG%":     efg,
                "TS%":      ts,
                "GmSc":     gs,
                "AST_FGM":  ast_fgm,
                "UNAST_FGM": unast_fgm,
                "W/Pass%":  w_pass,
                "W/O%":     wo_pass,
            })

        rows.sort(key=lambda r: r["PTS"], reverse=True)

        if rows:
            # Aggregate totals (before appending the totals row)
            tot_fgm = sum(r["FGM"] for r in rows)
            tot_fga = sum(r["FGA"] for r in rows)
            tot_tpm = sum(r["3PM"] for r in rows)
            tot_tpa = sum(r["3PA"] for r in rows)
            tot_ftm = sum(r["FTM"] for r in rows)
            tot_fta = sum(r["FTA"] for r in rows)
            tot_pts = sum(r["PTS"] for r in rows)
            tot_min = round(sum(r["MIN"] for r in rows), 1)
            tot_efg = round((tot_fgm + 0.5*tot_tpm) / tot_fga * 100, 1) if tot_fga else None
            tot_ts_d = 2 * (tot_fga + 0.44*tot_fta)
            tot_ts  = round(tot_pts / tot_ts_d * 100, 1) if tot_ts_d > 0 else None
            tot_gs  = round(sum(r["GmSc"] for r in rows if r.get("GmSc") is not None), 1)
            tot_ast_fgm   = sum(r["AST_FGM"]   for r in rows)
            tot_unast_fgm = sum(r["UNAST_FGM"] for r in rows)
            tot_w_pass  = round(tot_ast_fgm   / tot_fga * 100, 1) if tot_fga else None
            tot_wo_pass = round(tot_unast_fgm / tot_fga * 100, 1) if tot_fga else None
            rows.append({
                "_pid":      None,
                "_totals":   True,
                "Player":    "TOTALS",
                "MIN":       tot_min,
                "PTS":       tot_pts,
                "OREB":      sum(r["OREB"] for r in rows),
                "DREB":      sum(r["DREB"] for r in rows),
                "REB":       sum(r["REB"] for r in rows),
                "AST":       sum(r["AST"] for r in rows),
                "STL":       sum(r["STL"] for r in rows),
                "BLK":       sum(r["BLK"] for r in rows),
                "TOV":       sum(r["TOV"] for r in rows),
                "PF":        sum(r["PF"] for r in rows),
                "FGM":       tot_fgm,
                "FGA":       tot_fga,
                "3PM":       tot_tpm,
                "3PA":       tot_tpa,
                "FTM":       tot_ftm,
                "FTA":       tot_fta,
                "+/-":       None,
                "eFG%":      tot_efg,
                "TS%":       tot_ts,
                "GmSc":      tot_gs,
                "AST_FGM":   tot_ast_fgm,
                "UNAST_FGM": tot_unast_fgm,
                "W/Pass%":   tot_w_pass,
                "W/O%":      tot_wo_pass,
            })

        return rows

    return _build_team_rows(t1id), _build_team_rows(t2id), dict(g)


# ══════════════════════════════════════════════════════════════════════════════
#  QUARTER SCORES (single game)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def compute_game_quarter_scores(game_id: int):
    """Returns {quarter: {team_id: pts}} for a single game."""
    game_rows = query(
        "SELECT team1_id AS t1id, team2_id AS t2id FROM games WHERE id=?",
        (game_id,))
    if not game_rows:
        return {}
    t1id = game_rows[0]["t1id"]
    t2id = game_rows[0]["t2id"]

    rows = query("""
        SELECT ge.quarter, ge.event_type, ge.shot_result, ge.shot_type, p.team_id
        FROM game_events ge
        JOIN players p ON p.id=ge.primary_player_id
        WHERE ge.game_id=? AND ge.event_type IN ('shot','free_throw')
          AND ge.shot_result='make'
        ORDER BY ge.quarter, ge.id
    """, (game_id,))

    quarters: dict = {}
    for r in rows:
        q = r["quarter"]
        if q not in quarters:
            quarters[q] = {t1id: 0, t2id: 0}
        pts = r["shot_type"] if r["event_type"] == "shot" else 1
        if r["team_id"] in quarters[q]:
            quarters[q][r["team_id"]] += pts
    return quarters


# ══════════════════════════════════════════════════════════════════════════════
#  OFFICIAL STATS
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def compute_official_stats() -> pd.DataFrame:
    """Games worked and foul rates per official."""
    officials = query("SELECT id, name, official_id FROM officials ORDER BY name")
    if not officials:
        return pd.DataFrame()

    # Games per official (via lineup table)
    game_rows = query("""
        SELECT glo.official_id, COUNT(DISTINCT glo.game_id) AS gc
        FROM game_lineup_officials glo
        JOIN games g ON g.id=glo.game_id
        GROUP BY glo.official_id
    """)
    game_map = {r["official_id"]: r["gc"] for r in game_rows}

    # Fouls called per official
    foul_rows = query("""
        SELECT ge.official_id, COUNT(*) AS fc
        FROM game_events ge
        WHERE ge.event_type='foul' AND ge.official_id IS NOT NULL
        GROUP BY ge.official_id
    """)
    foul_map = {r["official_id"]: r["fc"] for r in foul_rows}

    # Home vs away foul differential
    ha_rows = query("""
        SELECT ge.official_id,
               g.team1_id, g.team2_id,
               p.team_id AS fouler_team
        FROM game_events ge
        JOIN games g ON g.id=ge.game_id
        JOIN players p ON p.id=ge.secondary_player_id
        WHERE ge.event_type='foul' AND ge.official_id IS NOT NULL
          AND ge.secondary_player_id IS NOT NULL
    """)
    home_fouls: dict = defaultdict(int)
    away_fouls: dict = defaultdict(int)
    for r in ha_rows:
        oid = r["official_id"]
        if r["fouler_team"] == r["team1_id"]:  # team1 = home
            home_fouls[oid] += 1
        else:
            away_fouls[oid] += 1

    rows = []
    for o in officials:
        oid = o["id"]
        gc  = game_map.get(oid, 0)
        fc  = foul_map.get(oid, 0)
        hf  = home_fouls.get(oid, 0)
        af  = away_fouls.get(oid, 0)
        rows.append({
            "Official":    o["name"],
            "Ref ID":      o["official_id"],
            "Games":       gc,
            "Total Fouls": fc,
            "Fouls/Game":  round(fc / gc, 1) if gc else 0,
            "Home Fouls":  hf,
            "Away Fouls":  af,
            "H/A Diff":    hf - af,
        })

    df = pd.DataFrame(rows).sort_values("Games", ascending=False).reset_index(drop=True)
    df.index += 1
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  POSITION RATINGS
# ══════════════════════════════════════════════════════════════════════════════

def compute_player_ratings() -> pd.DataFrame:
    """
    Four composite ratings for every qualified player (min 1 GP), all scaled 0–100
    relative to the league player pool.

    OFF — Offensive Rating
        Two equal sub-scores combined:
        • Shooting  (TS% 30%, eFG% 25%, 3P% 20%, FT% 15%, ShotRat 10%)
        • Finishing (PTS 35%, PaintFG% 30%, SC 20%, FG% 15%)

    DEF — Defensive Rating
        DSh% 30% · Stocks/G 25% · DREB/G 25% · STL/G 10% · BLK/G 10%

    PLY — Playmaking Rating
        AST/G 30% · AST/TOV 25% · TOV inv 20% · SC/G 15% · PTS/G 10%

    REB — Rebounding Rating
        OREB/G 35% · DREB/G 35% · REB/G 20% · PaintFGA/G 10%

    OVRL — Overall Rating
        OFF 30% + PLY 25% + DEF 25% + REB 20%, then normalised 0–100.
    """
    df = compute_player_rankings()
    if df.empty:
        return pd.DataFrame()

    df = df[df["GP"] >= 1].copy()
    if df.empty:
        return pd.DataFrame()

    # ── Derived helper columns ────────────────────────────────────────────────
    df["_ast_tov"] = df["AST"] / (df["TOV"] + 0.1)   # avoid ÷0
    df["Stocks"]   = df["STL"] + df["BLK"]            # steals + blocks per game

    def _norm(col: str, higher_is_better: bool = True) -> pd.Series:
        """Normalise column values to 0–100 within the current df."""
        s = df[col].fillna(0)
        lo, hi = s.min(), s.max()
        if hi == lo:
            return pd.Series(50.0, index=df.index)
        pct = (s - lo) / (hi - lo) * 100.0
        return pct if higher_is_better else (100.0 - pct)

    # ── OFF — Offensive Rating ────────────────────────────────────────────────
    # Sub-score A: Shooting efficiency
    _off_shoot_cfg = [
        ("TS%",     True, 0.30),
        ("eFG%",    True, 0.25),
        ("3P%",     True, 0.20),
        ("FT%",     True, 0.15),
        ("ShotRat", True, 0.10),
    ]
    df["_OFF_shoot"] = sum(_norm(c, h) * w for c, h, w in _off_shoot_cfg
                           if c in df.columns)

    # Sub-score B: Finishing & production
    _off_finish_cfg = [
        ("PTS",      True, 0.35),
        ("PaintFG%", True, 0.30),
        ("SC",       True, 0.20),
        ("FG%",      True, 0.15),
    ]
    df["_OFF_finish"] = sum(_norm(c, h) * w for c, h, w in _off_finish_cfg
                            if c in df.columns)

    # OFF = average of both sub-scores (each already 0–100)
    df["OFF"] = ((df["_OFF_shoot"] + df["_OFF_finish"]) / 2).round(1)

    # ── DEF — Defensive Rating ────────────────────────────────────────────────
    _def_cfg = [
        ("DSh%",   True, 0.30),
        ("Stocks", True, 0.25),
        ("DREB",   True, 0.25),
        ("STL",    True, 0.10),
        ("BLK",    True, 0.10),
    ]
    df["DEF"] = sum(_norm(c, h) * w for c, h, w in _def_cfg
                    if c in df.columns).round(1)

    # ── PLY — Playmaking Rating ───────────────────────────────────────────────
    _ply_cfg = [
        ("AST",      True,  0.30),
        ("_ast_tov", True,  0.25),
        ("TOV",      False, 0.20),
        ("SC",       True,  0.15),
        ("PTS",      True,  0.10),
    ]
    df["PLY"] = sum(_norm(c, h) * w for c, h, w in _ply_cfg
                    if c in df.columns).round(1)

    # ── REB — Rebounding Rating ───────────────────────────────────────────────
    _reb_cfg = [
        ("OREB",     True, 0.35),
        ("DREB",     True, 0.35),
        ("REB",      True, 0.20),
        ("PaintFGA", True, 0.10),
    ]
    df["REB_R"] = sum(_norm(c, h) * w for c, h, w in _reb_cfg
                      if c in df.columns).round(1)

    # ── OVRL — Overall Rating ─────────────────────────────────────────────────
    df["_ovrl_raw"] = (
        df["OFF"]   * 0.30
        + df["PLY"] * 0.25
        + df["DEF"] * 0.25
        + df["REB_R"] * 0.20
    )
    df["OVRL"] = _norm("_ovrl_raw", True).round(1)

    # ── Return trimmed frame ──────────────────────────────────────────────────
    keep = ["pid", "Player", "#", "Team", "Class", "Gender", "GP", "MIN",
            "PTS", "AST", "REB", "OREB", "DREB", "STL", "BLK", "TOV",
            "FGM", "FGA", "FG%", "2PM", "2PA", "2P%",
            "3PM", "3PA", "3P%", "3PAr",
            "FTM", "FTA", "FT%",
            "eFG%", "TS%",
            "PaintFG%", "PaintFGA", "PaintFGM",
            "+/-", "GS", "SC", "ShotRat", "Stocks", "Q4 PPG",
            "_ast_tov", "AST/TOV",
            "DSh%",
            "FTr", "PPS", "PPSA", "TOV%", "USG", "EFF", "FIC", "PRF",
            "PTS32", "REB32", "AST32", "STL32", "BLK32", "TOV32", "SC32",
            "_OFF_shoot", "_OFF_finish",
            "OFF", "DEF", "PLY", "REB_R", "OVRL"]
    return df[[c for c in keep if c in df.columns]]
