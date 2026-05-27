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

@st.cache_data(ttl=3600, show_spinner=False)
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
                    sc=0, scs=0, scp=0, sco=0, shot_rating=0.0, shot_rating_n=0)

    stats: dict = defaultdict(_blank)

    for ev in events:
        pid   = ev["pid"]
        etype = ev["event_type"]

        if etype == "shot":
            if pid and pid in pid_info:
                s = stats[pid]
                s["fga"] += 1
                s["sc"]  += 1   # shooter always gets 1 SC
                s["scs"] += 1
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
                stats[pf]["sc"]  += 1
                stats[pf]["scp"] += 1
            scb = ev["shot_created_by_id"]
            if scb and scb in pid_info and scb != pid:
                stats[scb]["sc"]  += 1
                stats[scb]["sco"] += 1
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

    # ── Adjusted assist-rate denominator ─────────────────────────────────────
    # AST% = player's assists / teammate FGM while player is on court
    # "Teammate FGM" = made shots by same-team players (excluding the player)
    # while that player had a game_event_lineup entry for that event.
    ast_denom_rows = query("""
        SELECT
            gel.player_id,
            COUNT(*) AS teammate_fgm
        FROM game_event_lineup gel
        JOIN game_events  ge      ON ge.id       = gel.event_id
        JOIN games        g       ON g.id        = ge.game_id
        JOIN players      shooter ON shooter.id  = ge.primary_player_id
        JOIN players      p_on    ON p_on.id     = gel.player_id
        WHERE g.tracked = 1
          AND ge.event_type = 'shot'
          AND ge.shot_result = 'make'
          AND shooter.team_id = p_on.team_id
          AND shooter.id     != gel.player_id
        GROUP BY gel.player_id
    """)
    ast_denom_map = {r["player_id"]: max(r["teammate_fgm"] or 0, 1) for r in ast_denom_rows}

    # ── Adjusted rebound-rate denominators ───────────────────────────────────
    # For each player: while on court, how many OREB / DREB opportunities existed?
    #   OREB opp = your team's missed shots while you were on court
    #   DREB opp = opponent's missed shots while you were on court
    reb_opp_rows = query("""
        SELECT
            gel.player_id,
            SUM(CASE WHEN shooter.team_id  = p_on.team_id THEN 1 ELSE 0 END) AS oreb_opps,
            SUM(CASE WHEN shooter.team_id != p_on.team_id THEN 1 ELSE 0 END) AS dreb_opps
        FROM game_event_lineup gel
        JOIN game_events  ge      ON ge.id       = gel.event_id
        JOIN games        g       ON g.id        = ge.game_id
        JOIN players      shooter ON shooter.id  = ge.primary_player_id
        JOIN players      p_on    ON p_on.id     = gel.player_id
        WHERE g.tracked = 1
          AND ge.event_type IN ('shot', 'free_throw')
          AND ge.shot_result = 'miss'
        GROUP BY gel.player_id
    """)
    oreb_opps_map = {r["player_id"]: max(r["oreb_opps"] or 0, 1) for r in reb_opp_rows}
    dreb_opps_map = {r["player_id"]: max(r["dreb_opps"] or 0, 1) for r in reb_opp_rows}

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

        # ── Adjusted assist rate (opportunity-based) ─────────────────────────
        # AST% = what % of teammate made FGs did this player facilitate?
        _ast_denom = ast_denom_map.get(pid, 1)
        ast_pct = round(s["ast"] / _ast_denom * 100, 1) if _ast_denom > 0 else 0.0

        # ── Adjusted rebound rates (opportunity-based) ────────────────────────
        # OREB% = what % of available offensive rebound opportunities did player grab?
        # DREB% = what % of available defensive rebound opportunities did player grab?
        # TRB%  = combined (total player rebs / avg available rebs per possession)
        _oreb_o = oreb_opps_map.get(pid, 1)
        _dreb_o = dreb_opps_map.get(pid, 1)
        _trb_o  = _oreb_o + _dreb_o
        oreb_pct = round(s["oreb"] / _oreb_o * 100, 1) if _oreb_o > 0 else 0.0
        dreb_pct = round(s["dreb"] / _dreb_o * 100, 1) if _dreb_o > 0 else 0.0
        trb_pct  = round((s["oreb"] + s["dreb"]) / (_trb_o / 2) * 100, 1) if _trb_o > 0 else 0.0

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
            "SCS":    round(s["scs"] / gp, 1),
            "SCP":    round(s["scp"] / gp, 1),
            "SCO":    round(s["sco"] / gp, 1),
            "SCS%":   round(s["scs"] / s["sc"] * 100, 1) if s["sc"] else 0.0,
            "SCP%":   round(s["scp"] / s["sc"] * 100, 1) if s["sc"] else 0.0,
            "SCO%":   round(s["sco"] / s["sc"] * 100, 1) if s["sc"] else 0.0,
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
            "SCS32":  round(s["scs"]  / total_min * 32, 1) if p32 and total_min else None,
            "SCP32":  round(s["scp"]  / total_min * 32, 1) if p32 and total_min else None,
            "SCO32":  round(s["sco"]  / total_min * 32, 1) if p32 and total_min else None,
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
            # ── Adjusted assist rate ──────────────────────────────────────────
            "AST%":   ast_pct,     # % of teammate FGM player assisted while on court
            # ── Adjusted rebound rates ────────────────────────────────────────
            "OREB%": oreb_pct,     # % of team-miss opportunities player grabbed (offensive)
            "DREB%": dreb_pct,     # % of opp-miss opportunities player grabbed (defensive)
            "TRB%":  trb_pct,      # combined: player rebs / (avg available per event)
        }
        rows.append(row)

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  PER-GAME BOX SCORE (single game)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
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

@st.cache_data(ttl=300, show_spinner=False)
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

@st.cache_data(ttl=3600, show_spinner=False)
def compute_official_stats() -> pd.DataFrame:
    """Games worked and foul rates per official.

    Game membership is sourced from BOTH game_lineup_officials (assignments)
    and foul events so officials with non-tracked games still appear correctly.

    Pace / PPP are computed by looking up shot+turnover counts per game_id
    rather than filtering game_events by official_id, because official_id is
    only populated on foul rows — it is NULL on every shot and turnover.
    """
    officials = query("SELECT id, name, official_id FROM officials ORDER BY name")
    if not officials:
        return pd.DataFrame()

    from collections import defaultdict

    # ── Source A: official ↔ game assignments (any game, tracked or not) ──────
    assign_rows = query(
        "SELECT official_id, game_id FROM game_lineup_officials"
    )

    # ── Source B: foul events (official_id is only set here) ─────────────────
    foul_rows = query("""
        SELECT
            ge.official_id,
            ge.game_id,
            g.team1_id,
            p.team_id AS fouler_team
        FROM game_events ge
        JOIN games   g ON g.id  = ge.game_id
        JOIN players p ON p.id  = ge.secondary_player_id
        WHERE ge.event_type             = 'foul'
          AND ge.official_id            IS NOT NULL
          AND ge.secondary_player_id    IS NOT NULL
    """)

    # Build per-official game sets
    game_sets_all:     dict = defaultdict(set)   # all games (assignments + foul events)
    game_sets_tracked: dict = defaultdict(set)   # games that have foul-event data

    for r in assign_rows:
        game_sets_all[r["official_id"]].add(r["game_id"])

    for r in foul_rows:
        game_sets_all[r["official_id"]].add(r["game_id"])
        game_sets_tracked[r["official_id"]].add(r["game_id"])

    # Foul count / home-away split
    foul_count: dict = defaultdict(int)
    home_fouls: dict = defaultdict(int)
    away_fouls: dict = defaultdict(int)

    for r in foul_rows:
        oid = r["official_id"]
        foul_count[oid] += 1
        if r["fouler_team"] == r["team1_id"]:   # team1 is always home
            home_fouls[oid] += 1
        else:
            away_fouls[oid] += 1

    # ── Pace / PPP: fetch per-game possession counts WITHOUT filtering by
    #    official_id (shot/turnover rows never carry an official_id). ──────────
    all_game_ids: set = set()
    for gids in game_sets_all.values():
        all_game_ids.update(gids)

    game_poss_map:  dict = {}   # game_id → shot+turnover count
    game_score_map: dict = {}   # game_id → combined score

    if all_game_ids:
        ph = ",".join("?" * len(all_game_ids))

        poss_rows = query(
            f"""SELECT game_id, COUNT(*) AS poss_count
                FROM game_events
                WHERE game_id IN ({ph})
                  AND event_type IN ('shot', 'turnover')
                GROUP BY game_id""",
            tuple(all_game_ids),
        )
        for r in poss_rows:
            game_poss_map[r["game_id"]] = r["poss_count"]

        score_rows = query(
            f"SELECT id, home_score, away_score FROM games WHERE id IN ({ph})",
            tuple(all_game_ids),
        )
        for r in score_rows:
            game_score_map[r["id"]] = (r["home_score"] or 0) + (r["away_score"] or 0)

    # ── Build one row per official ────────────────────────────────────────────
    rows = []
    for o in officials:
        oid       = o["id"]
        all_games = game_sets_all.get(oid, set())
        trk_games = game_sets_tracked.get(oid, set())

        gc  = len(all_games)
        tgc = len(trk_games)          # games with foul-event data (denominator for Fouls/Game)
        fc  = foul_count.get(oid, 0)
        hf  = home_fouls.get(oid, 0)
        af  = away_fouls.get(oid, 0)

        # Pace = total (shots + turnovers both teams) / games that had event data
        total_poss  = sum(game_poss_map.get(gid, 0) for gid in all_games)
        pace_games  = sum(1 for gid in all_games if game_poss_map.get(gid, 0) > 0)
        pace        = round(total_poss / pace_games, 1) if pace_games else 0.0

        # PPP = combined score / total possessions
        total_pts   = sum(game_score_map.get(gid, 0) for gid in all_games)
        ppp         = round(total_pts / total_poss, 3) if total_poss else 0.0

        # Avg total score per game (across all games with a recorded score)
        scored_games = sum(1 for gid in all_games if game_score_map.get(gid, 0) > 0)
        avg_score    = round(total_pts / scored_games, 1) if scored_games else 0.0

        # Fouls/Game uses tgc so we don't dilute with untracked game stubs
        fpg = round(fc / tgc, 1) if tgc else 0.0

        rows.append({
            "Official":        o["name"],
            "Ref ID":          o["official_id"],
            "Games":           gc,
            "Total Fouls":     fc,
            "Fouls/Game":      fpg,
            "Home Fouls":      hf,
            "Away Fouls":      af,
            "H/A Diff":        hf - af,
            "Avg Total Score": avg_score,
            "Pace":            pace,
            "PPP":             ppp,
        })

    df = pd.DataFrame(rows).sort_values("Games", ascending=False).reset_index(drop=True)
    df.index += 1
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  POSITION RATINGS
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
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

    df = df[df["GP"] >= 2].copy()   # min 2 GP to appear in OVRL — avoids single-game outliers
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
    # AST% leads (context-adjusted rate), then volume + quality + ball security
    _ply_cfg = [
        ("AST%",     True,  0.28),   # adjusted assist rate (primary context signal)
        ("AST",      True,  0.22),   # raw assist volume per game
        ("_ast_tov", True,  0.20),   # AST/TOV ratio (quality of decisions)
        ("TOV",      False, 0.15),   # fewer turnovers = better
        ("SC",       True,  0.10),   # shot creation
        ("PTS",      True,  0.05),   # scoring contribution to playmaking
    ]
    df["PLY"] = sum(_norm(c, h) * w for c, h, w in _ply_cfg
                    if c in df.columns).round(1)

    # ── REB — Rebounding Rating ───────────────────────────────────────────────
    # Adjusted rates (OREB%/DREB%) now lead; raw volume provides supporting signal
    _reb_cfg = [
        ("OREB%",    True, 0.25),   # adjusted offensive reb rate
        ("DREB%",    True, 0.25),   # adjusted defensive reb rate
        ("OREB",     True, 0.20),   # raw offensive reb volume per game
        ("DREB",     True, 0.15),   # raw defensive reb volume per game
        ("REB",      True, 0.10),   # total rebs per game
        ("PaintFGA", True, 0.05),   # glass proximity proxy
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
            "+/-", "GS", "SC", "SCS", "SCP", "SCO", "SCS%", "SCP%", "SCO%",
            "ShotRat", "Stocks", "Q4 PPG",
            "_ast_tov", "AST/TOV",
            "DSh%",
            "FTr", "PPS", "PPSA", "TOV%", "USG", "EFF", "FIC", "PRF",
            "PTS32", "REB32", "AST32", "STL32", "BLK32", "TOV32", "SC32",
            "SCS32", "SCP32", "SCO32",
            "AST%",
            "OREB%", "DREB%", "TRB%",
            "_OFF_shoot", "_OFF_finish",
            "OFF", "DEF", "PLY", "REB_R", "OVRL"]
    return df[[c for c in keep if c in df.columns]]


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYER ON/OFF REBOUNDING
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def compute_player_rebound_onoff(player_id: int, team_id: int) -> dict:
    """
    Return on-court vs off-court team rebounding rates for a single player.

    For each missed shot in games the player appeared in, we classify whether
    the player was on court (via game_event_lineup) and whether it was an
    offensive or defensive rebound opportunity for the player's team.

    Returns a dict with keys:
        on_oreb_pct  – team OREB% while player is on court
        off_oreb_pct – team OREB% while player is off court
        on_dreb_pct  – team DREB% while player is on court
        off_dreb_pct – team DREB% while player is off court
        on_trb_pct   – team TRB% (combined) while player is on court
        off_trb_pct  – team TRB% (combined) while player is off court
        on_oreb_opps, off_oreb_opps  – sample sizes
        on_dreb_opps, off_dreb_opps
        on_oreb, off_oreb, on_dreb, off_dreb  – raw team rebound counts
    Returns an empty dict if insufficient data.
    """
    # Get all games this player appeared in
    game_rows = query("""
        SELECT DISTINCT game_id FROM game_lineup_players WHERE player_id=?
    """, (player_id,))
    if not game_rows:
        return {}
    game_ids   = tuple(r["game_id"] for r in game_rows)
    if not game_ids:
        return {}

    placeholders = ",".join("?" * len(game_ids))

    # All missed shots in those games (tracked only)
    missed_rows = query(f"""
        SELECT
            ge.id          AS event_id,
            shooter.team_id AS shooting_team,
            reb_p.team_id   AS rebounding_team,
            ge.rebound_by_id
        FROM game_events ge
        JOIN games   g      ON g.id       = ge.game_id
        JOIN players shooter ON shooter.id = ge.primary_player_id
        LEFT JOIN players reb_p ON reb_p.id = ge.rebound_by_id
        WHERE g.tracked = 1
          AND ge.game_id IN ({placeholders})
          AND ge.event_type IN ('shot', 'free_throw')
          AND ge.shot_result = 'miss'
    """, game_ids)

    if not missed_rows:
        return {}

    # Which event ids had this player on court
    on_court_rows = query(f"""
        SELECT DISTINCT event_id
        FROM game_event_lineup
        WHERE player_id = ?
          AND event_id IN (
              SELECT ge.id FROM game_events ge
              WHERE ge.game_id IN ({placeholders})
          )
    """, (player_id,) + game_ids)
    on_court_ids = {r["event_id"] for r in on_court_rows}

    # Tally
    on_oreb_opps = off_oreb_opps = 0   # our team missed (OREB opportunity)
    on_dreb_opps = off_dreb_opps = 0   # opp missed     (DREB opportunity)
    on_oreb = off_oreb = 0              # our team grabbed OREB
    on_dreb = off_dreb = 0              # our team grabbed DREB

    for r in missed_rows:
        is_on         = r["event_id"] in on_court_ids
        shooting_team = r["shooting_team"]
        reb_team      = r["rebounding_team"]

        if shooting_team == team_id:
            # Our team missed → offensive rebound opportunity
            if is_on:
                on_oreb_opps += 1
                if reb_team == team_id:
                    on_oreb += 1
            else:
                off_oreb_opps += 1
                if reb_team == team_id:
                    off_oreb += 1
        else:
            # Opponent missed → defensive rebound opportunity
            if is_on:
                on_dreb_opps += 1
                if reb_team == team_id:
                    on_dreb += 1
            else:
                off_dreb_opps += 1
                if reb_team == team_id:
                    off_dreb += 1

    def _pct(num, den):
        return round(num / den * 100, 1) if den > 0 else None

    on_trb_opps  = on_oreb_opps  + on_dreb_opps
    off_trb_opps = off_oreb_opps + off_dreb_opps

    return {
        "on_oreb_pct":   _pct(on_oreb,  on_oreb_opps),
        "off_oreb_pct":  _pct(off_oreb, off_oreb_opps),
        "on_dreb_pct":   _pct(on_dreb,  on_dreb_opps),
        "off_dreb_pct":  _pct(off_dreb, off_dreb_opps),
        "on_trb_pct":    _pct(on_oreb + on_dreb,   on_trb_opps),
        "off_trb_pct":   _pct(off_oreb + off_dreb,  off_trb_opps),
        "on_oreb_opps":  on_oreb_opps,
        "off_oreb_opps": off_oreb_opps,
        "on_dreb_opps":  on_dreb_opps,
        "off_dreb_opps": off_dreb_opps,
        "on_oreb":       on_oreb,
        "off_oreb":      off_oreb,
        "on_dreb":       on_dreb,
        "off_dreb":      off_dreb,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYER ON/OFF PLAYMAKING
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def compute_player_assist_onoff(player_id: int, team_id: int) -> dict:
    """
    Return on-court vs off-court team playmaking metrics for a single player.

    For each team field goal made (and each team possession) in games the player
    appeared in, we check whether the player was on court via game_event_lineup.

    Metrics computed ON and OFF court:
        ast_pct    – team AST% (assisted FGM / total team FGM)
        tov_pct    – team TOV% (turnovers / possessions)
        ast_pg     – team assists per game
        tov_pg     – team turnovers per game
        team_fgm   – total team FGM (denominator for AST%)

    Returns an empty dict if insufficient data.
    """
    game_rows = query(
        "SELECT DISTINCT game_id FROM game_lineup_players WHERE player_id=?",
        (player_id,))
    if not game_rows:
        return {}
    game_ids     = tuple(r["game_id"] for r in game_rows)
    placeholders = ",".join("?" * len(game_ids))
    n_games      = len(game_ids)

    # ── Team made field goals in those games ──────────────────────────────────
    fgm_rows = query(f"""
        SELECT
            ge.id        AS event_id,
            ge.pass_from_id,
            shooter.team_id AS shooting_team
        FROM game_events ge
        JOIN games   g      ON g.id       = ge.game_id
        JOIN players shooter ON shooter.id = ge.primary_player_id
        WHERE g.tracked = 1
          AND ge.game_id IN ({placeholders})
          AND ge.event_type = 'shot'
          AND ge.shot_result = 'make'
          AND shooter.team_id = ?
    """, game_ids + (team_id,))

    # ── Team turnovers in those games ─────────────────────────────────────────
    tov_rows = query(f"""
        SELECT ge.id AS event_id
        FROM game_events ge
        JOIN games   g  ON g.id = ge.game_id
        JOIN players p  ON p.id = ge.primary_player_id
        WHERE g.tracked = 1
          AND ge.game_id IN ({placeholders})
          AND ge.event_type = 'turnover'
          AND p.team_id = ?
    """, game_ids + (team_id,))

    if not fgm_rows:
        return {}

    # ── Which event_ids had this player on court ──────────────────────────────
    all_event_ids = tuple({r["event_id"] for r in fgm_rows} |
                          {r["event_id"] for r in tov_rows})
    if not all_event_ids:
        return {}

    oc_ph = ",".join("?" * len(all_event_ids))
    on_court_rows = query(f"""
        SELECT DISTINCT event_id
        FROM game_event_lineup
        WHERE player_id = ? AND event_id IN ({oc_ph})
    """, (player_id,) + all_event_ids)
    on_court_ids = {r["event_id"] for r in on_court_rows}

    # ── Tally FGM with/without player ────────────────────────────────────────
    on_fgm = on_ast = off_fgm = off_ast = 0
    for r in fgm_rows:
        assisted = r["pass_from_id"] is not None
        if r["event_id"] in on_court_ids:
            on_fgm  += 1
            on_ast  += int(assisted)
        else:
            off_fgm += 1
            off_ast += int(assisted)

    # ── Tally TOV with/without player ────────────────────────────────────────
    on_tov = off_tov = 0
    for r in tov_rows:
        if r["event_id"] in on_court_ids:
            on_tov  += 1
        else:
            off_tov += 1

    def _pct(num, den):
        return round(num / den * 100, 1) if den > 0 else None

    # Approximate possessions for TOV%: FGM is a proxy (no team-possession
    # tracking beyond event lineup), so we use FGM + TOV as denominator
    on_pos_proxy  = on_fgm  + on_tov
    off_pos_proxy = off_fgm + off_tov

    return {
        # AST%: what fraction of team FGMs were assisted?
        "on_ast_pct":   _pct(on_ast,  on_fgm),
        "off_ast_pct":  _pct(off_ast, off_fgm),
        # TOV%: turnovers per possession (proxy)
        "on_tov_pct":   _pct(on_tov,  on_pos_proxy),
        "off_tov_pct":  _pct(off_tov, off_pos_proxy),
        # Per-game
        "on_ast_pg":    round(on_ast  / n_games, 1),
        "off_ast_pg":   round(off_ast / n_games, 1),
        "on_tov_pg":    round(on_tov  / n_games, 1),
        "off_tov_pg":   round(off_tov / n_games, 1),
        # Sample sizes
        "on_fgm":       on_fgm,
        "off_fgm":      off_fgm,
        "on_tov":       on_tov,
        "off_tov":      off_tov,
        "n_games":      n_games,
    }
