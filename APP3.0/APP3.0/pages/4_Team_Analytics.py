import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from Database.db import query, initialize_database
from helpers.constants import ZONES, SHOT_RATING, EST_FGP
from helpers.game_utils import games_for_team, win_loss, opponent_name, home_away, record_from_games
from helpers.charts import (zone_color, render_hot_zones, show_shot_chart, show_scoring_pie,
                            show_four_factors_bars, show_trend_chart, show_player_radar)
from helpers.stats_team import (compute_player_game_log, compute_player_career,
                                compute_team_tracked, compute_on_off,
                                compute_league_drtg, compute_league_four_factors,
                                compute_matchup)

initialize_database()

st.title("Team Analytics")

# ══════════════════════════════════════════════════════════════════════════════
#  TEAM SELECTOR
# ══════════════════════════════════════════════════════════════════════════════

all_teams = query("SELECT id, name, class, gender FROM teams ORDER BY name")
if not all_teams:
    st.warning("No teams found. Add teams in the Input Hub first.")
    st.stop()

team_map   = {t["name"]: t["id"] for t in all_teams}
team_meta  = {t["id"]: t for t in all_teams}
sel_name   = st.selectbox("Select Team", list(team_map.keys()))
team_id    = team_map[sel_name]
team_info  = team_meta[team_id]

st.caption(f"Class {team_info['class']} · {'Men' if team_info['gender']=='M' else 'Women'}")
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_ov, tab_ts, tab_pl, tab_gm, tab_mu, tab_notes, tab_ai = st.tabs(
    ["Overview", "Team Stats", "Players", "Games", "Matchup Simulator", "Notes", "AI Insights"]
)

# ══════════════════════════════════════════════════════════════════════════════
#  OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_ov:
    all_gs  = games_for_team(team_id)
    tr_gs   = games_for_team(team_id, tracked_only=True)
    adv     = compute_team_tracked(team_id)
    w,l,pf,pa = record_from_games(all_gs, team_id)
    gp=len(all_gs)

    # ── KPI row ──
    k1,k2,k3,k4,k5,k6 = st.columns(6)
    k1.metric("Record",   f"{w}-{l}")
    k2.metric("Win %",    f"{w/gp*100:.1f}%" if gp else "—")
    k3.metric("PPG",      f"{pf/gp:.1f}" if gp else "—")
    k4.metric("PA/G",     f"{pa/gp:.1f}" if gp else "—")
    k5.metric("Diff",     f"{(pf-pa)/gp:+.1f}" if gp else "—")
    k6.metric("GP",       gp)

    st.divider()

    if adv:
        st.subheader("Advanced (Tracked Games Only)")
        a1,a2,a3,a4 = st.columns(4)
        a1.metric("ORtg",     f"{adv['ortg']:.1f}")
        a2.metric("DRtg",     f"{adv['drtg']:.1f}")
        a3.metric("Net Rtg",  f"{adv['net']:+.1f}")
        a4.metric("Pace",     f"{adv['pace']:.1f}")
        b1,b2,b3,b4,b5,b6 = st.columns(6)
        b1.metric("eFG%",  f"{adv['efg']*100:.1f}%")
        b2.metric("Opp eFG%",f"{adv['oefg']*100:.1f}%")
        b3.metric("TS%",   f"{adv['ts']*100:.1f}%")
        b4.metric("TOV%",  f"{adv['tov_r']*100:.1f}%")
        b5.metric("OREB%", f"{adv['oreb_p']*100:.1f}%")
        b6.metric("FT Rate",f"{adv['ft_r']:.2f}")
        st.divider()

    # ── Schedule summary ──
    st.subheader("Schedule")
    sched_rows=[]
    for g in all_gs:
        res,my,opp=win_loss(g,team_id)
        sched_rows.append({
            "Date":g["date"],"Opponent":opponent_name(g,team_id),
            "H/A":home_away(g,team_id),"Result":res,
            "Score":f"{my}-{opp}","Tracked":"✓" if g["tracked"] else ""
        })
    if sched_rows:
        st.dataframe(pd.DataFrame(sched_rows), use_container_width=True, hide_index=True)

    # ── Hot zones aggregate ──
    if tr_gs:
        st.divider()
        st.subheader("Shooting Zones (All Tracked Games)")
        gids=tuple(g["id"] for g in tr_gs)
        if len(gids)==1:
            shots=query("""
                SELECT e.zone,e.shot_type,e.shot_result
                FROM game_events e
                JOIN game_lineup_players glp ON glp.game_id=e.game_id AND glp.player_id=e.primary_player_id
                WHERE e.game_id=? AND e.event_type='shot' AND e.zone IS NOT NULL AND glp.team_id=?
            """, (gids[0], team_id))
        else:
            shots=query(f"""
                SELECT e.zone,e.shot_type,e.shot_result
                FROM game_events e
                JOIN game_lineup_players glp ON glp.game_id=e.game_id AND glp.player_id=e.primary_player_id
                WHERE e.game_id IN ({','.join('?'*len(gids))}) AND e.event_type='shot'
                  AND e.zone IS NOT NULL AND glp.team_id=?
            """, (*gids, team_id))
        render_hot_zones(shots)

# ══════════════════════════════════════════════════════════════════════════════
#  TEAM STATS
# ══════════════════════════════════════════════════════════════════════════════
with tab_ts:
    ts_adv = compute_team_tracked(team_id)
    ts_all = games_for_team(team_id, tracked_only=True)
    gp_ts  = len(ts_all)

    if not ts_adv or gp_ts == 0:
        st.info("No tracked game data yet.")
    else:
        a = ts_adv  # shorthand

        # ── Per-game highlights ──────────────────────────────────────────────
        st.subheader("Per Game")
        r1 = st.columns(6)
        r1[0].metric("PPG",    f"{a['pts_pg']:.1f}")
        r1[1].metric("APG",    f"{a['ast_pg']:.1f}")
        r1[2].metric("RPG",    f"{(a['oreb_pg']+a['dreb_pg']):.1f}")
        r1[3].metric("SPG",    f"{a['stl_pg']:.1f}")
        r1[4].metric("BPG",    f"{a['blk_pg']:.1f}")
        r1[5].metric("TPG",    f"{a['tov_pg']:.1f}")

        st.divider()

        # ── Possessions ──────────────────────────────────────────────────────
        st.subheader("Possessions")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Total Possessions",  a["poss_count"],
                  help="Count of non-free-throw events with a primary player (same definition as Game Tracker)")
        p2.metric("Possessions / Game", f"{a['poss_pg']:.1f}")
        p3.metric("Points Per Poss.",   f"{a['ppp']:.3f}",
                  help="Total points scored ÷ total possessions")
        p4.metric("Avg Poss. Length",   a["avg_poss_len"],
                  help="Average time (M:SS) per possession")

        poss_rows = [
            {"Stat": "Total Possessions",    "Value": a["poss_count"]},
            {"Stat": "Possessions / Game",   "Value": f"{a['poss_pg']:.1f}"},
            {"Stat": "Total Poss. Time",     "Value": a["poss_time_total"]},
            {"Stat": "Avg Poss. Length",     "Value": a["avg_poss_len"]},
            {"Stat": "Points Per Possession","Value": f"{a['ppp']:.3f}"},
        ]
        st.dataframe(pd.DataFrame(poss_rows), hide_index=True, use_container_width=True)

        st.divider()

        # ── Shooting ────────────────────────────────────────────────────────
        st.subheader("Shooting")
        sh1, sh2, sh3 = st.columns(3)

        with sh1:
            st.markdown("**Field Goals**")
            _2pm = a["fgm"]-a["tpm"]; _2pa = a["fga"]-a["tpa"]
            fg_rows = [
                {"Stat": "FGM",  "Total": a["fgm"],               "Per Game": round(a["fgm"]/gp_ts, 1)},
                {"Stat": "FGA",  "Total": a["fga"],               "Per Game": round(a["fga"]/gp_ts, 1)},
                {"Stat": "FG%",  "Total": f"{a['fgp']*100:.1f}%", "Per Game": "—"},
                {"Stat": "2PM",  "Total": _2pm,                   "Per Game": round(_2pm/gp_ts, 1)},
                {"Stat": "2PA",  "Total": _2pa,                   "Per Game": round(_2pa/gp_ts, 1)},
                {"Stat": "2P%",  "Total": f"{a['two_pct']*100:.1f}%","Per Game": "—"},
                {"Stat": "eFG%", "Total": f"{a['efg']*100:.1f}%", "Per Game": "—"},
                {"Stat": "TS%",  "Total": f"{a['ts']*100:.1f}%",  "Per Game": "—"},
            ]
            st.dataframe(pd.DataFrame(fg_rows), hide_index=True, use_container_width=True)

        with sh2:
            st.markdown("**3-Pointers**")
            tp_rows = [
                {"Stat": "3PM",  "Total": a["tpm"],                         "Per Game": round(a["tpm"]/gp_ts, 1)},
                {"Stat": "3PA",  "Total": a["tpa"],                         "Per Game": round(a["tpa"]/gp_ts, 1)},
                {"Stat": "3P%",  "Total": f"{a['tpp']*100:.1f}%",           "Per Game": "—"},
                {"Stat": "3PAr", "Total": f"{a['tpar']*100:.1f}%",          "Per Game": "—"},
            ]
            st.dataframe(pd.DataFrame(tp_rows), hide_index=True, use_container_width=True)

        with sh3:
            st.markdown("**Free Throws**")
            ft_rows = [
                {"Stat": "FTM",     "Total": a["ftm"],                      "Per Game": round(a["ftm"]/gp_ts, 1)},
                {"Stat": "FTA",     "Total": a["fta"],                      "Per Game": round(a["fta"]/gp_ts, 1)},
                {"Stat": "FT%",     "Total": f"{a['ftp']*100:.1f}%",        "Per Game": "—"},
                {"Stat": "FT Rate", "Total": f"{a['ft_r']:.2f}",            "Per Game": "—"},
            ]
            st.dataframe(pd.DataFrame(ft_rows), hide_index=True, use_container_width=True)

        st.divider()

        # ── Other counting stats ─────────────────────────────────────────────
        st.subheader("Other Stats")
        other_rows = [
            {"Stat": "Assists",       "Total": a["ast"],  "Per Game": round(a["ast_pg"], 1)},
            {"Stat": "Off. Rebounds", "Total": a["oreb"], "Per Game": round(a["oreb_pg"], 1)},
            {"Stat": "Def. Rebounds", "Total": a["dreb"], "Per Game": round(a["dreb_pg"], 1)},
            {"Stat": "Rebounds",      "Total": a["oreb"]+a["dreb"], "Per Game": round(a["oreb_pg"]+a["dreb_pg"], 1)},
            {"Stat": "Steals",        "Total": a["stl"],  "Per Game": round(a["stl_pg"], 1)},
            {"Stat": "Blocks",        "Total": a["blk"],  "Per Game": round(a["blk_pg"], 1)},
            {"Stat": "Turnovers",     "Total": a["tov"],  "Per Game": round(a["tov_pg"], 1)},
        ]
        st.dataframe(pd.DataFrame(other_rows), hide_index=True, use_container_width=True)

        st.divider()

        # ── Advanced ─────────────────────────────────────────────────────────
        st.subheader("Advanced")
        adv1, adv2 = st.columns(2)
        with adv1:
            adv_off = [
                {"Stat": "Off. Rating (ORtg)",   "Value": f"{a['ortg']:.1f}",          "Note": "pts/100 poss"},
                {"Stat": "Net Rating",            "Value": f"{a['net']:+.1f}",           "Note": "ORtg − DRtg"},
                {"Stat": "Pace",                  "Value": f"{a['pace']:.1f}",           "Note": "poss/game"},
                {"Stat": "eFG%",                  "Value": f"{a['efg']*100:.1f}%",       "Note": "(FGM+0.5×3PM)/FGA"},
                {"Stat": "TS%",                   "Value": f"{a['ts']*100:.1f}%",        "Note": "true shooting"},
                {"Stat": "TOV%",                  "Value": f"{a['tov_r']*100:.1f}%",     "Note": "tov per poss"},
                {"Stat": "OREB%",                 "Value": f"{a['oreb_p']*100:.1f}%",    "Note": "off-glass rate"},
                {"Stat": "FT Rate",               "Value": f"{a['ft_r']:.3f}",           "Note": "FTA/FGA"},
                {"Stat": "AST%",                  "Value": f"{a.get('ast_pct',0):.1f}%", "Note": "% FGM assisted"},
                {"Stat": "AST/TOV",               "Value": f"{a.get('ast_tov_r',0):.2f}","Note": "assist-to-tov ratio"},
                {"Stat": "Paint FG%",             "Value": f"{a.get('paint_fg_p',0)*100:.1f}%","Note": "zone-C 2PT proxy"},
                {"Stat": "Paint Pts/G",           "Value": f"{a.get('paint_pts_pg',0):.1f}",   "Note": "pts from paint/g"},
            ]
            st.markdown("**Offense**")
            st.dataframe(pd.DataFrame(adv_off), hide_index=True, use_container_width=True)
        with adv2:
            adv_def = [
                {"Stat": "Def. Rating (DRtg)",   "Value": f"{a['drtg']:.1f}",                      "Note": "pts/100 poss"},
                {"Stat": "Opp eFG%",              "Value": f"{a['oefg']*100:.1f}%",                 "Note": "opp shooting qual"},
                {"Stat": "Opp TS%",               "Value": f"{(a['opp_pts']/(2*(a['opp_fga']+0.44*a['opp_fta'])) if (a['opp_fga']+0.44*a['opp_fta']) else 0)*100:.1f}%","Note": "opp true shooting"},
                {"Stat": "Opp TOV%",              "Value": f"{a.get('opp_tov_r',0)*100:.1f}%",      "Note": "forced tov rate"},
                {"Stat": "Opp FT Rate",           "Value": f"{a.get('opp_ft_r',0):.3f}",            "Note": "FTA/FGA allowed"},
                {"Stat": "DREB%",                 "Value": f"{a.get('dreb_p',0)*100:.1f}%",         "Note": "def rebound rate"},
                {"Stat": "BLK Rate",              "Value": f"{a.get('blk_rate',0):.1f}%",           "Note": "BLK/opp 2PA"},
                {"Stat": "STL Rate",              "Value": f"{a.get('stl_rate',0):.1f}%",           "Note": "STL/opp poss"},
                {"Stat": "Opp TOV/G",             "Value": f"{a['opp_tov']/gp_ts:.1f}",             "Note": "opp turnovers/g"},
            ]
            st.markdown("**Defense**")
            st.dataframe(pd.DataFrame(adv_def), hide_index=True, use_container_width=True)

        st.divider()

        # ── Shot Creation ────────────────────────────────────────────────────
        st.subheader("Shot Creation")
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("SC/G",   f"{a['sc_pg']:.1f}",       help="Shot creations per game (shots taken + passes on shots + dribble creates)")
        sc2.metric("SCE",    f"{a['team_sce']:.3f}",    help="PTS / ((2PT_att×2) + (3PT_att×3)) — points scored per shot opportunity")
        sc3.metric("PTS/SC", f"{(a['pts']/a['sc']):.2f}" if a['sc'] else "—", help="Points scored per shot creation act")
        sc4.metric("SC/FGA", f"{(a['sc']/a['fga']):.2f}" if a['fga'] else "—", help=">1 = team creates more than it shoots, <1 = shoots more than it creates")

        st.divider()

        # ── Four Factors ─────────────────────────────────────────────────────
        st.subheader("Dean Oliver's Four Factors")
        st.caption("The four factors that drive winning: Shooting (40%), Turnovers (25%), Rebounding (20%), Free Throws (15%)")
        _lg_ff = compute_league_four_factors()
        show_four_factors_bars(a, _lg_ff if _lg_ff else None)

        ff_col1, ff_col2, ff_col3, ff_col4 = st.columns(4)
        ff_col1.metric("eFG%",      f"{a['efg']*100:.1f}%",       help="Effective FG% — weights 3s by 1.5×")
        ff_col2.metric("TOV%",      f"{a['tov_r']*100:.1f}%",     help="Turnover rate — lower is better")
        ff_col3.metric("OREB%",     f"{a['oreb_p']*100:.1f}%",    help="Offensive rebound rate")
        ff_col4.metric("FT Rate",   f"{a['ft_r']:.3f}",           help="FTA per FGA — getting to the line")
        ff_col1.metric("Opp eFG%",  f"{a['oefg']*100:.1f}%",      help="Opponent effective FG% — lower is better")
        ff_col2.metric("Opp TOV%",  f"{a.get('opp_tov_r',0)*100:.1f}%", help="Forced turnover rate — higher is better")
        ff_col3.metric("DREB%",     f"{a.get('dreb_p',0)*100:.1f}%",    help="Defensive rebound rate")
        ff_col4.metric("Opp FT Rate",f"{a.get('opp_ft_r',0):.3f}",     help="FTA/FGA allowed — lower is better")

        st.divider()

        # ── Scoring Distribution ─────────────────────────────────────────────
        st.subheader("Scoring Distribution")
        _pts2 = (a["fgm"]-a["tpm"])*2
        _pts3 = a["tpm"]*3
        _ptft = a["ftm"]
        sd_col1, sd_col2 = st.columns([1, 1])
        with sd_col1:
            show_scoring_pie(_pts2, _pts3, _ptft, f"{sel_name} — Scoring Sources")
        with sd_col2:
            pct_rows = [
                {"Source": "2PT Field Goals", "Points": _pts2, "Pct": f"{a.get('pct_from_2',0):.1f}%",
                 "Per Game": f"{_pts2/gp_ts:.1f}"},
                {"Source": "3PT Field Goals", "Points": _pts3, "Pct": f"{a.get('pct_from_3',0):.1f}%",
                 "Per Game": f"{_pts3/gp_ts:.1f}"},
                {"Source": "Free Throws",     "Points": _ptft, "Pct": f"{a.get('pct_from_ft',0):.1f}%",
                 "Per Game": f"{_ptft/gp_ts:.1f}"},
                {"Source": "TOTAL",           "Points": _pts2+_pts3+_ptft,
                 "Pct": "100%", "Per Game": f"{a['pts_pg']:.1f}"},
            ]
            st.dataframe(pd.DataFrame(pct_rows), hide_index=True, use_container_width=True)
            st.markdown(f"**Ast%**: {a.get('ast_pct',0):.1f}% of FGM were assisted")
            st.markdown(f"**Unast%**: {a.get('unast_pct',0):.1f}% of FGM were unassisted")

        st.divider()

        # ── Shot Chart ───────────────────────────────────────────────────────
        st.subheader("Shot Chart (All Tracked Games)")
        _gids = tuple(g["id"] for g in ts_all)
        if _gids:
            if len(_gids) == 1:
                _shots_ts = query("""
                    SELECT e.zone, e.shot_type, e.shot_result
                    FROM game_events e
                    JOIN game_lineup_players glp ON glp.game_id=e.game_id
                                                AND glp.player_id=e.primary_player_id
                    WHERE e.game_id=? AND e.event_type='shot'
                      AND e.zone IS NOT NULL AND glp.team_id=?
                """, (_gids[0], team_id))
            else:
                _shots_ts = query(f"""
                    SELECT e.zone, e.shot_type, e.shot_result
                    FROM game_events e
                    JOIN game_lineup_players glp ON glp.game_id=e.game_id
                                                AND glp.player_id=e.primary_player_id
                    WHERE e.game_id IN ({','.join('?'*len(_gids))})
                      AND e.event_type='shot' AND e.zone IS NOT NULL AND glp.team_id=?
                """, (*_gids, team_id))
            sc_c1, sc_c2 = st.columns(2)
            with sc_c1:
                show_shot_chart(_shots_ts, f"{sel_name} — Offense")
            # Opponent shot chart
            if len(_gids) == 1:
                _opp_shots_ts = query("""
                    SELECT e.zone, e.shot_type, e.shot_result
                    FROM game_events e
                    JOIN game_lineup_players glp ON glp.game_id=e.game_id
                                                AND glp.player_id=e.primary_player_id
                    WHERE e.game_id=? AND e.event_type='shot'
                      AND e.zone IS NOT NULL AND glp.team_id!=?
                """, (_gids[0], team_id))
            else:
                _opp_shots_ts = query(f"""
                    SELECT e.zone, e.shot_type, e.shot_result
                    FROM game_events e
                    JOIN game_lineup_players glp ON glp.game_id=e.game_id
                                                AND glp.player_id=e.primary_player_id
                    WHERE e.game_id IN ({','.join('?'*len(_gids))})
                      AND e.event_type='shot' AND e.zone IS NOT NULL AND glp.team_id!=?
                """, (*_gids, team_id))
            with sc_c2:
                show_shot_chart(_opp_shots_ts, "Opponents — Offense (Defense Quality)")

        st.divider()

        # ── Q4 / Clutch ──────────────────────────────────────────────────────
        st.subheader("Q4 / Clutch Performance")
        q4_c1, q4_c2, q4_c3, q4_c4 = st.columns(4)
        q4_c1.metric("Q4 Pts/G",  f"{a.get('q4_pts_pg',0):.1f}",
                     help="Points scored in the 4th quarter per game")
        q4_c2.metric("Q4 PA/G",   f"{a.get('opp_q4_pts_pg',0):.1f}",
                     help="Points allowed in the 4th quarter per game")
        _q4diff = a.get('q4_pts_pg',0) - a.get('opp_q4_pts_pg',0)
        q4_c3.metric("Q4 Diff",   f"{_q4diff:+.1f}",
                     help="Q4 point differential per game — positive = closing strong")
        q4_c4.metric("Q4 Pts (total)", a.get("q4_pts", 0),
                     help="Total points scored in 4th quarter across all tracked games")

        st.caption(f"Based on {gp_ts} tracked game{'s' if gp_ts != 1 else ''}.")

# ══════════════════════════════════════════════════════════════════════════════
#  PLAYERS
# ══════════════════════════════════════════════════════════════════════════════
with tab_pl:
    players = query("SELECT id, name, number, height, wingspan, weight FROM players WHERE team_id=? ORDER BY name", (team_id,))
    if not players:
        st.info("No players on roster.")
    else:
        # Aggregate stats table
        stat_rows=[]
        player_careers={}
        for p in players:
            c=compute_player_career(p["id"])
            player_careers[p["id"]]=c

        # Team SC total (for SC%)
        team_sc_total = sum(c["sc"] for c in player_careers.values() if c and c["gp"]>0)

        # On/Off data (uses game_event_lineup snapshots)
        on_off_data = compute_on_off(team_id)

        for p in players:
            c=player_careers[p["id"]]
            if c and c["gp"]>0:
                gp=c["gp"]
                fgp=c["fgm"]/c["fga"] if c["fga"] else 0
                tpp=c["tpm"]/c["tpa"] if c["tpa"] else 0
                ftp=c["ftm"]/c["fta"] if c["fta"] else 0
                efg=(c["fgm"]+0.5*c["tpm"])/c["fga"] if c["fga"] else 0
                ts =c["pts"]/(2*(c["fga"]+0.44*c["fta"])) if (c["fga"]+0.44*c["fta"]) else 0
                reb=(c["oreb"]+c["dreb"])
                gs =round((c["pts"]+0.4*c["fgm"]-0.7*c["fga"]-0.4*(c["fta"]-c["ftm"])
                           +0.7*c["oreb"]+0.3*c["dreb"]+c["stl"]+0.7*c["ast"]
                           +0.7*c["blk"]-0.4*c["pf"]-c["tov"])/gp, 1)
                sc_pct  = round(c["sc"]/team_sc_total*100, 1) if team_sc_total else 0
                sce_den = (c["fga"] - c["tpa"]) * 2 + c["tpa"] * 3
                sce     = round(c["pts"] / sce_den, 3) if sce_den else 0
                ast_tov = round(c["ast"]/c["tov"], 2) if c["tov"] else ("∞" if c["ast"] else "—")
                sc_fga  = round(c["sc"]/c["fga"], 2) if c["fga"] else 0
                pts_sc  = round(c["pts"]/c["sc"], 2) if c["sc"] else 0
                # On/Off derived metrics
                oo = on_off_data.get(p["id"], {})
                on_p  = oo.get("on_poss", 0)
                off_p = oo.get("off_poss", 0)
                on_pf = oo.get("on_pts_for", 0)
                on_pa = oo.get("on_pts_against", 0)
                off_pf= oo.get("off_pts_for", 0)
                off_pa= oo.get("off_pts_against", 0)
                pu    = oo.get("poss_used", 0)

                net_on  = (on_pf  - on_pa)  / on_p  * 100 if on_p  else None
                net_off = (off_pf - off_pa) / off_p * 100 if off_p else None
                on_off  = round(net_on - net_off, 1) if (net_on is not None and net_off is not None) else "—"
                usg_pct = round(pu / on_p * 100, 1) if on_p else 0
                poss_pg = round(pu / gp, 1) if gp else 0
                pts_poss= round(c["pts"] / pu, 3) if pu else 0

                # Shot quality
                sht_q    = round(c["shot_rating"] / c["est_fg_shots"], 2) if c["est_fg_shots"] else "—"
                efg_est  = round(c["est_fg_sum"]  / c["est_fg_shots"] * 100, 1) if c["est_fg_shots"] else "—"
                # Defensive
                dfga_pg  = round(c["def_fga"] / gp, 1)
                dsh_pct  = round(c["def_fga"] / c["on_court_opp_shots"] * 100, 1) if c["on_court_opp_shots"] else "—"

                stat_rows.append({
                    "Player":p["name"],"#":p["number"],"GP":gp,
                    "PTS":round(c["pts"]/gp,1),"AST":round(c["ast"]/gp,1),
                    "REB":round(reb/gp,1),"OREB":round(c["oreb"]/gp,1),"DREB":round(c["dreb"]/gp,1),
                    "STL":round(c["stl"]/gp,1),"BLK":round(c["blk"]/gp,1),
                    "TOV":round(c["tov"]/gp,1),
                    "FGM":round(c["fgm"]/gp,1),"FGA":round(c["fga"]/gp,1),
                    "FG%":f"{fgp*100:.1f}","3PM":round(c["tpm"]/gp,1),"3PA":round(c["tpa"]/gp,1),
                    "3P%":f"{tpp*100:.1f}","FTM":round(c["ftm"]/gp,1),"FTA":round(c["fta"]/gp,1),
                    "FT%":f"{ftp*100:.1f}",
                    "eFG%":f"{efg*100:.1f}","TS%":f"{ts*100:.1f}",
                    "SC":round(c["sc"]/gp,1),"SC%":sc_pct,"SCE":sce,
                    "AST/TOV":ast_tov,"SC/FGA":sc_fga,"PTS/SC":pts_sc,
                    "MIN":round(c["poss_secs"]/60/gp,1),"GS":gs,
                    # Shot quality
                    "ShtQ":sht_q, "eFG%E":efg_est,
                    # Possession & On/Off
                    "+/-":c["plus_minus"],
                    "Poss/G":poss_pg, "Usg%":usg_pct, "PTS/Poss":pts_poss,
                    "Net On":round(net_on, 1) if net_on is not None else "—",
                    "Net Off":round(net_off,1) if net_off is not None else "—",
                    "On/Off":on_off,
                    # Defensive
                    "DFGA/G":dfga_pg, "DSh%":dsh_pct,
                    "_pid":p["id"],
                })
            else:
                stat_rows.append({"Player":p["name"],"#":p["number"],"GP":0,
                                   **{k:"—" for k in ["PTS","AST","REB","OREB","DREB","STL","BLK","TOV",
                                                       "FGM","FGA","FG%","3PM","3PA","3P%","FTM","FTA","FT%",
                                                       "eFG%","TS%","SC","SC%","SCE","AST/TOV","SC/FGA",
                                                       "PTS/SC","MIN","GS",
                                                       "ShtQ","eFG%E",
                                                       "+/-","Poss/G","Usg%","PTS/Poss",
                                                       "Net On","Net Off","On/Off",
                                                       "DFGA/G","DSh%"]},
                                   "_pid":p["id"]})

        disp_cols=["Player","#","GP","PTS","AST","REB","OREB","DREB","STL","BLK","TOV",
                   "FGM","FGA","FG%","3PM","3PA","3P%","FTM","FTA","FT%","eFG%","TS%",
                   "SC","SC%","SCE","AST/TOV","SC/FGA","PTS/SC","MIN","GS",
                   "ShtQ","eFG%E",
                   "+/-","Poss/G","Usg%","PTS/Poss","Net On","Net Off","On/Off",
                   "DFGA/G","DSh%"]
        df_pl=pd.DataFrame(stat_rows)
        st.subheader("Per Game Averages (Tracked Games)")
        if not df_pl.empty:
            st.dataframe(df_pl[disp_cols], use_container_width=True, hide_index=True)
            st.download_button("⬇ Export Player Stats (CSV)",
                               df_pl[disp_cols].to_csv(index=False),
                               file_name=f"{sel_name}_player_stats.csv",
                               mime="text/csv", key="dl_pl_stats")

        st.divider()
        st.subheader("Player Comparison Radar")
        show_player_radar(df_pl[df_pl["GP"] > 0].copy(), key="main_radar")

        st.divider()
        st.subheader("Individual Breakdowns")
        for p in players:
            c=player_careers.get(p["id"])
            label=f"#{p['number']}  {p['name']}"
            if p["height"]: label+=f"  ·  {p['height']}in"
            with st.expander(label):
                bio_cols=st.columns(4)
                bio_cols[0].metric("Height",  f"{p['height']}\"" if p['height'] else "—")
                bio_cols[1].metric("Wingspan", f"{p['wingspan']}\"" if p['wingspan'] else "—")
                bio_cols[2].metric("Weight",   f"{p['weight']} lbs" if p['weight'] else "—")
                bio_cols[3].metric("Number",   f"#{p['number']}")

                if not c or c["gp"]==0:
                    st.info("No tracked game data.")
                    continue

                mc=st.columns(5)
                mc[0].metric("PTS/G", f"{c['pts']/c['gp']:.1f}")
                mc[1].metric("REB/G", f"{(c['oreb']+c['dreb'])/c['gp']:.1f}")
                mc[2].metric("AST/G", f"{c['ast']/c['gp']:.1f}")
                mc[3].metric("STL/G", f"{c['stl']/c['gp']:.1f}")
                mc[4].metric("BLK/G", f"{c['blk']/c['gp']:.1f}")

                shoot_cols=st.columns(4)
                fgp_=c["fgm"]/c["fga"] if c["fga"] else 0
                tpp_=c["tpm"]/c["tpa"] if c["tpa"] else 0
                ftp_=c["ftm"]/c["fta"] if c["fta"] else 0
                ts_ =c["pts"]/(2*(c["fga"]+0.44*c["fta"])) if (c["fga"]+0.44*c["fta"]) else 0
                shoot_cols[0].metric("FG%", f"{fgp_*100:.1f}%")
                shoot_cols[1].metric("3P%", f"{tpp_*100:.1f}%")
                shoot_cols[2].metric("FT%", f"{ftp_*100:.1f}%")
                shoot_cols[3].metric("TS%", f"{ts_*100:.1f}%")

                # SC metrics
                sc_pct_  = round(c["sc"]/team_sc_total*100, 1) if team_sc_total else 0
                sce_den_ = (c["fga"] - c["tpa"]) * 2 + c["tpa"] * 3
                sce_     = round(c["pts"] / sce_den_, 3) if sce_den_ else 0
                ast_tov_ = round(c["ast"]/c["tov"], 2) if c["tov"] else ("∞" if c["ast"] else "—")
                sc_fga_  = round(c["sc"]/c["fga"], 2) if c["fga"] else 0
                pts_sc_  = round(c["pts"]/c["sc"], 2) if c["sc"] else 0

                st.markdown("**Shot Creation**")
                sc_cols = st.columns(6)
                sc_cols[0].metric("SC/G",    f"{c['sc']/c['gp']:.1f}")
                sc_cols[1].metric("SC%",     f"{sc_pct_}%",    help="% of team's total shot creation")
                sc_cols[2].metric("SCE",     f"{sce_:.3f}",    help="PTS / ((2PT_att×2) + (3PT_att×3))")
                sc_cols[3].metric("AST/TOV", f"{ast_tov_}",    help="Assist-to-turnover ratio")
                sc_cols[4].metric("SC/FGA",  f"{sc_fga_:.2f}", help="Shot creations per field goal attempt")
                sc_cols[5].metric("PTS/SC",  f"{pts_sc_:.2f}", help="Points scored per shot creation act")

                # ── Shot Quality ────────────────────────────────────────────
                _esf = c["est_fg_shots"]
                _sht_q   = round(c["shot_rating"] / _esf, 2) if _esf else None
                _efg_est = round(c["est_fg_sum"] / _esf * 100, 1) if _esf else None

                st.markdown("**Shot Quality** *(zone-logged shots only)*")
                sq_cols = st.columns(4)
                sq_cols[0].metric("Shot Rating",
                                  f"{_sht_q:+.2f}" if _sht_q is not None else "—",
                                  help="Avg shot rating per attempt. Positive = good looks (open, high-% spot), Negative = difficult shots (contested, low-% spot)")
                sq_cols[1].metric("Est FG%",
                                  f"{_efg_est:.1f}%" if _efg_est is not None else "—",
                                  help="Estimated FG% based on shot location and whether the shot was contested")
                sq_cols[2].metric("Actual FG%",
                                  f"{fgp_*100:.1f}%",
                                  help="Actual field goal percentage — compare to Est FG% to see if they over/under-perform their shot quality")
                _fg_diff = round(fgp_*100 - _efg_est, 1) if _efg_est is not None else None
                sq_cols[3].metric("FG% vs Est",
                                  f"{_fg_diff:+.1f}%" if _fg_diff is not None else "—",
                                  help="Actual FG% minus Estimated FG%. Positive = outperforming shot quality; Negative = underperforming")

                if c["shots"]:
                    # Shot quality breakdown by zone — uses uncontested baseline (guarded flag not stored per shot)
                    _zone_data = {}
                    for sh in c["shots"]:
                        _k = (sh["shot_type"], sh["zone"])
                        _e = _zone_data.setdefault(_k, {"fga":0,"fgm":0})
                        _e["fga"] += 1
                        if sh["shot_result"] == "make": _e["fgm"] += 1
                    _sq_table = []
                    for (stype, zone), d in sorted(_zone_data.items()):
                        _est_unc = EST_FGP.get((stype, zone, False))
                        _est_con = EST_FGP.get((stype, zone, True))
                        _sq_table.append({
                            "Type": f"{stype}PT", "Zone": zone,
                            "FGA": d["fga"],
                            "Actual FG%": f"{d['fgm']/d['fga']*100:.0f}%" if d["fga"] else "—",
                            "Open baseline": f"{_est_unc*100:.0f}%" if _est_unc else "—",
                            "Contested baseline": f"{_est_con*100:.0f}%" if _est_con else "—",
                            "Open rating": f"{SHOT_RATING.get((stype,zone,False),0):+.1f}",
                            "Contested rating": f"{SHOT_RATING.get((stype,zone,True),0):+.1f}",
                        })
                    if _sq_table:
                        st.dataframe(pd.DataFrame(_sq_table), hide_index=True, use_container_width=True)

                # ── Per-32 Stats (HS equivalent of per-36) ──────────────────
                _mins32 = c["poss_secs"]/60
                if _mins32 > 0:
                    _m32 = 32/_mins32
                    st.markdown("**Per-32 Minutes** *(high-school game equivalent)*")
                    p32_cols = st.columns(7)
                    p32_cols[0].metric("PTS/32",  f"{c['pts']*_m32:.1f}")
                    p32_cols[1].metric("AST/32",  f"{c['ast']*_m32:.1f}")
                    p32_cols[2].metric("REB/32",  f"{(c['oreb']+c['dreb'])*_m32:.1f}")
                    p32_cols[3].metric("STL/32",  f"{c['stl']*_m32:.1f}")
                    p32_cols[4].metric("BLK/32",  f"{c['blk']*_m32:.1f}")
                    p32_cols[5].metric("TOV/32",  f"{c['tov']*_m32:.1f}")
                    p32_cols[6].metric("FGA/32",  f"{c['fga']*_m32:.1f}")

                # ── Scoring Source ───────────────────────────────────────────
                _c_pts2 = (c["fgm"]-c["tpm"])*2
                _c_pts3 = c["tpm"]*3
                _c_ptft = c["ftm"]
                _c_tot  = _c_pts2 + _c_pts3 + _c_ptft
                if _c_tot > 0:
                    st.markdown("**Scoring Distribution**")
                    show_scoring_pie(_c_pts2, _c_pts3, _c_ptft,
                                     f"{p['name']} — Scoring Sources")

                # ── Defensive Impact ────────────────────────────────────────
                st.markdown("**Defensive Impact**")
                _dfga   = c["def_fga"]
                _oc_opp = c["on_court_opp_shots"]

                di_cols = st.columns(2)
                di_cols[0].metric("DFGA/G",
                                  f"{_dfga/c['gp']:.1f}",
                                  help="Shots defended per game (guarded_by logged on shot events)")
                di_cols[1].metric("Contested Sh%",
                                  f"{_dfga/_oc_opp*100:.1f}%" if _oc_opp else "—",
                                  help="Defended shots ÷ total opponent shots while on court — how often this player contests shots")

                # ── Possession & On/Off Impact ──────────────────────────────
                oo_ = on_off_data.get(p["id"], {})
                on_p_  = oo_.get("on_poss", 0)
                off_p_ = oo_.get("off_poss", 0)
                on_pf_ = oo_.get("on_pts_for", 0)
                on_pa_ = oo_.get("on_pts_against", 0)
                off_pf_= oo_.get("off_pts_for", 0)
                off_pa_= oo_.get("off_pts_against", 0)
                pu_    = oo_.get("poss_used", 0)

                has_oo = on_p_ > 0

                st.markdown("**Possession & On/Off Impact**")
                po_cols = st.columns(4)
                po_cols[0].metric("Poss Used/G",  f"{pu_/c['gp']:.1f}" if c['gp'] else "—",
                                  help="Shots taken + turnovers per game — times they touched ball and ended a possession")
                po_cols[1].metric("Usg%",         f"{pu_/on_p_*100:.1f}%" if on_p_ else "—",
                                  help="% of team possessions used by this player while on court")
                po_cols[2].metric("PTS/Poss",     f"{c['pts']/pu_:.3f}" if pu_ else "—",
                                  help="Points scored per possession used")
                po_cols[3].metric("Career +/-",   f"{c['plus_minus']:+d}",
                                  help="Total plus/minus across all tracked games")

                if has_oo:
                    net_on_  = (on_pf_  - on_pa_)  / on_p_  * 100
                    net_off_ = (off_pf_ - off_pa_) / off_p_ * 100 if off_p_ else None
                    on_off_v = f"{net_on_ - net_off_:+.1f}" if net_off_ is not None else "—"

                    st.markdown("*On-Court vs Off-Court (per 100 team possessions)*")
                    oc_cols = st.columns(3)
                    oc_cols[0].metric("Net Rtg ON",  f"{net_on_:+.1f}",
                                      help="Team point differential per 100 possessions while this player is on court")
                    oc_cols[1].metric("Net Rtg OFF",
                                      f"{net_off_:+.1f}" if net_off_ is not None else "—",
                                      help="Team point differential per 100 possessions while this player is off court")
                    oc_cols[2].metric("On/Off Impact", on_off_v,
                                      help="Net Rating ON minus Net Rating OFF — how much better/worse the team is with this player")

                    # Detailed on/off table
                    ortg_on  = on_pf_  / on_p_  * 100
                    drtg_on  = on_pa_  / on_p_  * 100
                    ortg_off = off_pf_ / off_p_ * 100 if off_p_ else 0
                    drtg_off = off_pa_ / off_p_ * 100 if off_p_ else 0
                    oo_table = pd.DataFrame([
                        {"Split": "ON Court",  "Poss": on_p_,
                         "ORtg": round(ortg_on,1),  "DRtg": round(drtg_on,1),
                         "Net": round(net_on_,1),
                         "Pts For": on_pf_,  "Pts Against": on_pa_},
                        {"Split": "OFF Court", "Poss": off_p_,
                         "ORtg": round(ortg_off,1), "DRtg": round(drtg_off,1),
                         "Net": round(net_off_,1) if net_off_ is not None else "—",
                         "Pts For": off_pf_, "Pts Against": off_pa_},
                    ])
                    st.dataframe(oo_table, hide_index=True, use_container_width=True)
                else:
                    st.caption("On/Off data requires games with lineup snapshots logged in Game Tracker.")

                if c["shots"]:
                    render_hot_zones(c["shots"])

                # ── Game Log ────────────────────────────────────────────────
                st.markdown("**Game Log**")
                gl = compute_player_game_log(p["id"], team_id)
                if gl:
                    gl_cols = ["Date","Opp","W/L","Score",
                               "PTS","AST","REB","STL","BLK","TOV",
                               "FGM","FGA","FG%","3PM","3PA","3P%",
                               "FTM","FTA","FT%","SC","SC%","Poss","+/-","MIN","GS"]
                    gl_df = pd.DataFrame(gl)[gl_cols]

                    # Colour W/L column green/red with styling
                    def _wl_style(val):
                        return "color:#2ecc71;font-weight:bold" if val=="W" else "color:#e74c3c;font-weight:bold"

                    st.dataframe(
                        gl_df.style.applymap(_wl_style, subset=["W/L"]),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "MIN":  st.column_config.NumberColumn("MIN",  format="%.1f"),
                            "SC%":  st.column_config.NumberColumn("SC%",  format="%.1f"),
                            "GS":   st.column_config.NumberColumn("GS",   format="%.1f"),
                        },
                    )
                    st.download_button(
                        "⬇ Export Game Log (CSV)",
                        gl_df.to_csv(index=False),
                        file_name=f"{p['name'].replace(' ','_')}_game_log.csv",
                        mime="text/csv",
                        key=f"dl_gl_{p['id']}",
                    )
                else:
                    st.caption("No tracked game data yet.")

# ══════════════════════════════════════════════════════════════════════════════
#  GAMES
# ══════════════════════════════════════════════════════════════════════════════
with tab_gm:
    all_gs = games_for_team(team_id)
    if not all_gs:
        st.info("No games with scores yet.")
    else:
        # Build log in chronological order (all_gs is oldest→newest)
        log=[]
        for g in all_gs:
            res,my,opp=win_loss(g,team_id)
            log.append({"Date":g["date"],"Opponent":opponent_name(g,team_id),
                        "H/A":home_away(g,team_id),"Result":res,
                        "Tm":my,"Opp":opp,"Margin":my-opp,"Tracked":"✓" if g["tracked"] else ""})

        # Table: newest first
        st.dataframe(pd.DataFrame(list(reversed(log))), use_container_width=True, hide_index=True)

        # Scoring trend: chronological (oldest→newest)
        st.subheader("Scoring Trend")
        _adv_gm = compute_team_tracked(team_id)
        if _adv_gm and _adv_gm.get("game_log"):
            show_trend_chart(_adv_gm["game_log"], sel_name)
        else:
            # Fallback — simple score chart for untracked games
            trend_df = pd.DataFrame(log)[["Date","Tm","Opp"]].copy()
            trend_df["Date"] = pd.to_datetime(trend_df["Date"], errors="coerce")
            trend_df = trend_df.dropna(subset=["Date"]).sort_values("Date").set_index("Date")
            st.line_chart(trend_df, color=["#2ecc71","#e74c3c"])

        # Tracked game box scores
        tr_gs = [g for g in all_gs if g["tracked"]]
        if tr_gs:
            st.subheader("Tracked Game Box Scores")
            for g in reversed(tr_gs):
                res,my,opp_sc=win_loss(g,team_id)
                opp_nm=opponent_name(g,team_id)
                lbl=f"{g['date']}  ·  {res}  {my}-{opp_sc}  vs {opp_nm}"
                with st.expander(lbl):
                    t1id=g["team1_id"]; t2id=g["team2_id"]
                    t1nm=g["t1_name"]; t2nm=g["t2_name"]

                    # ── Load all data once ───────────────────────────────────
                    all_gp = query(
                        "SELECT id AS pid, name AS pname, team_id FROM players "
                        "WHERE team_id IN (?,?) AND archived=0 ORDER BY name",
                        (t1id, t2id))
                    if not all_gp:
                        st.info("No players on roster.")
                        continue

                    def _blank_p():
                        return dict(pts=0,ast=0,oreb=0,dreb=0,stl=0,blk=0,tov=0,
                                    fgm=0,fga=0,tpm=0,tpa=0,ftm=0,fta=0,sc=0,pf=0)
                    stats_g = {p["pid"]: {**_blank_p(), "name": p["pname"], "team_id": p["team_id"]}
                               for p in all_gp}
                    player_team_id = {p["pid"]: p["team_id"] for p in all_gp}

                    mins_rows_g = query("""
                        SELECT gel.player_id, SUM(ge.possession_secs) AS secs
                        FROM game_event_lineup gel
                        JOIN game_events ge ON ge.id = gel.event_id
                        WHERE ge.game_id = ?
                        GROUP BY gel.player_id
                    """, (g["id"],))
                    player_mins_g = {r["player_id"]: r["secs"] or 0.0 for r in mins_rows_g}

                    pm_rows_g = query("SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?", (g["id"],))
                    stored_pm_g = {r["player_id"]: r["plus_minus"] for r in pm_rows_g}

                    events_g = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (g["id"],))
                    t1p = t2p = 0
                    for ev in events_g:
                        prim = ev["primary_player_id"]
                        et   = ev["event_type"]
                        if et == "shot":
                            sh = prim
                            if sh and sh in stats_g:
                                stats_g[sh]["fga"] += 1; stats_g[sh]["sc"] += 1
                                if ev["shot_type"] == 3: stats_g[sh]["tpa"] += 1
                                if ev["shot_result"] == "make":
                                    pts_ = ev["shot_type"]; stats_g[sh]["fgm"] += 1; stats_g[sh]["pts"] += pts_
                                    if ev["shot_type"] == 3: stats_g[sh]["tpm"] += 1
                                    if stats_g[sh]["team_id"] == t1id: t1p += pts_
                                    else: t2p += pts_
                                    if ev["pass_from_id"] and ev["pass_from_id"] in stats_g:
                                        stats_g[ev["pass_from_id"]]["ast"] += 1
                            for _col, _key in [("pass_from_id","sc"),("shot_created_by_id","sc"),("blocked_by_id","blk")]:
                                _pid2 = ev[_col]
                                if _pid2 and _pid2 in stats_g: stats_g[_pid2][_key] += 1
                            reb = ev["rebound_by_id"]
                            if reb and reb in stats_g and prim and prim in stats_g:
                                stats_g[reb]["oreb" if player_team_id.get(prim)==player_team_id.get(reb) else "dreb"] += 1
                        elif et == "free_throw":
                            sh = prim
                            if sh and sh in stats_g:
                                stats_g[sh]["fta"] += 1
                                if ev["shot_result"] == "make":
                                    stats_g[sh]["ftm"] += 1; stats_g[sh]["pts"] += 1
                                    if stats_g[sh]["team_id"] == t1id: t1p += 1
                                    else: t2p += 1
                            reb = ev["rebound_by_id"]
                            if reb and reb in stats_g and prim and prim in stats_g:
                                stats_g[reb]["oreb" if player_team_id.get(prim)==player_team_id.get(reb) else "dreb"] += 1
                        elif et == "foul":
                            f2 = ev["secondary_player_id"]
                            if f2 and f2 in stats_g: stats_g[f2]["pf"] += 1
                        elif et == "turnover":
                            if prim and prim in stats_g: stats_g[prim]["tov"] += 1
                            s2 = ev["stolen_by_id"]
                            if s2 and s2 in stats_g: stats_g[s2]["stl"] += 1

                    # ── Quarter scores (above tabs) ──────────────────────────
                    def _ql(qq): return f"Q{qq}" if qq <= 4 else f"OT{qq-4}"
                    q_sc = {}
                    for ev2 in events_g:
                        if ev2["event_type"] in ("shot","free_throw") and ev2["shot_result"] == "make":
                            qq = ev2["quarter"]
                            if qq not in q_sc: q_sc[qq] = {t1id: 0, t2id: 0}
                            pts_q = ev2["shot_type"] if ev2["event_type"] == "shot" else 1
                            s_tid = player_team_id.get(ev2["primary_player_id"])
                            if s_tid in q_sc[qq]: q_sc[qq][s_tid] += pts_q
                    if q_sc:
                        r1g = {"Team": t1nm}; r2g = {"Team": t2nm}
                        tot1g = tot2g = 0
                        for qq in sorted(q_sc.keys()):
                            r1g[_ql(qq)] = q_sc[qq].get(t1id, 0)
                            r2g[_ql(qq)] = q_sc[qq].get(t2id, 0)
                            tot1g += q_sc[qq].get(t1id, 0)
                            tot2g += q_sc[qq].get(t2id, 0)
                        r1g["Total"] = tot1g; r2g["Total"] = tot2g
                        st.dataframe(pd.DataFrame([r1g, r2g]), hide_index=True, use_container_width=True)

                    # ── Quarter PPP (above tabs) ─────────────────────────────
                    qp_g = {}
                    for ev2 in events_g:
                        pid2_ = ev2["primary_player_id"]
                        if not pid2_: continue
                        tid2_ = player_team_id.get(pid2_)
                        if tid2_ not in (t1id, t2id): continue
                        qq2 = ev2["quarter"]
                        if qq2 not in qp_g:
                            qp_g[qq2] = {t1id: {"poss":0,"pts":0}, t2id: {"poss":0,"pts":0}}
                        if ev2["event_type"] in ("shot","turnover"):
                            qp_g[qq2][tid2_]["poss"] += 1
                        if ev2["event_type"] == "shot" and ev2["shot_result"] == "make":
                            qp_g[qq2][tid2_]["pts"] += ev2["shot_type"] or 0
                        elif ev2["event_type"] == "free_throw" and ev2["shot_result"] == "make":
                            qp_g[qq2][tid2_]["pts"] += 1
                    if qp_g:
                        qp_r1 = {"Team": t1nm}; qp_r2 = {"Team": t2nm}
                        t1_tp = t2_tp = t1_tpts = t2_tpts = 0
                        for qq2 in sorted(qp_g.keys()):
                            lbl2 = _ql(qq2)
                            d1 = qp_g[qq2].get(t1id, {"poss":0,"pts":0})
                            d2 = qp_g[qq2].get(t2id, {"poss":0,"pts":0})
                            qp_r1[f"{lbl2} Poss"] = d1["poss"]
                            qp_r1[f"{lbl2} PPP"]  = round(d1["pts"]/d1["poss"],3) if d1["poss"] else "—"
                            qp_r2[f"{lbl2} Poss"] = d2["poss"]
                            qp_r2[f"{lbl2} PPP"]  = round(d2["pts"]/d2["poss"],3) if d2["poss"] else "—"
                            t1_tp += d1["poss"]; t1_tpts += d1["pts"]
                            t2_tp += d2["poss"]; t2_tpts += d2["pts"]
                        qp_r1["Total Poss"] = t1_tp
                        qp_r1["Total PPP"]  = round(t1_tpts/t1_tp,3) if t1_tp else "—"
                        qp_r2["Total Poss"] = t2_tp
                        qp_r2["Total PPP"]  = round(t2_tpts/t2_tp,3) if t2_tp else "—"
                        st.caption("Possessions per Quarter · PPP = points per possession")
                        st.dataframe(pd.DataFrame([qp_r1, qp_r2]), hide_index=True, use_container_width=True)

                    # ── Four tabs ────────────────────────────────────────────
                    gtab_box, gtab_ts, gtab_off, gtab_hz = st.tabs(
                        ["Box Score", "Team Stats", "Officials", "Hot Zones"])

                    # ── Box Score ────────────────────────────────────────────
                    with gtab_box:
                        _BOX_COLS = ["Player","PTS","AST","OREB","DREB","REB","STL","BLK","TOV",
                                     "FGM","FGA","3PM","3PA","FTM","FTA","SC","+/-","MIN","GS"]
                        all_box_export = []
                        for _tid, _tnm, _tpts in [(t1id, t1nm, t1p), (t2id, t2nm, t2p)]:
                            st.markdown(f"### {_tnm} — {_tpts}")
                            _rows = []
                            for pid2, s in stats_g.items():
                                if s["team_id"] != _tid: continue
                                _reb  = s["oreb"] + s["dreb"]
                                _mins = round(player_mins_g.get(pid2, 0.0) / 60, 1)
                                _plus = stored_pm_g.get(pid2, 0)
                                _gs   = round(s["pts"]+0.4*s["fgm"]-0.7*s["fga"]
                                              -0.4*(s["fta"]-s["ftm"])+0.7*s["oreb"]
                                              +0.3*s["dreb"]+s["stl"]+0.7*s["ast"]
                                              +0.7*s["blk"]-0.4*s["pf"]-s["tov"], 1)
                                _rows.append({
                                    "Player":s["name"],"PTS":s["pts"],"AST":s["ast"],
                                    "OREB":s["oreb"],"DREB":s["dreb"],"REB":_reb,
                                    "STL":s["stl"],"BLK":s["blk"],"TOV":s["tov"],
                                    "FGM":s["fgm"],"FGA":s["fga"],"3PM":s["tpm"],"3PA":s["tpa"],
                                    "FTM":s["ftm"],"FTA":s["fta"],"SC":s["sc"],
                                    "+/-":_plus,"MIN":_mins,"GS":_gs,
                                })
                            if _rows:
                                _df = pd.DataFrame(_rows)[_BOX_COLS]
                                st.dataframe(_df, use_container_width=True, hide_index=True)
                                all_box_export.append(_df.assign(Team=_tnm))
                        if all_box_export:
                            _exp = pd.concat(all_box_export)[["Team"]+_BOX_COLS]
                            st.download_button("⬇ Export Box Score (CSV)", _exp.to_csv(index=False),
                                               file_name=f"boxscore_{g['id']}_{opp_nm}.csv",
                                               mime="text/csv", key=f"dl_box_{g['id']}")

                    # ── Team Stats ───────────────────────────────────────────
                    with gtab_ts:
                        def _fmt_s(s):
                            _m, _sec = divmod(int(s), 60)
                            return f"{_m}:{_sec:02d}"

                        def _team_totals(tid_, pts_, poss_evs_):
                            _sr = [s for s in stats_g.values() if s["team_id"] == tid_]
                            if not _sr: return {}
                            _fgm=sum(r["fgm"] for r in _sr); _fga=sum(r["fga"] for r in _sr)
                            _tpm=sum(r["tpm"] for r in _sr); _tpa=sum(r["tpa"] for r in _sr)
                            _ftm=sum(r["ftm"] for r in _sr); _fta=sum(r["fta"] for r in _sr)
                            _oreb=sum(r["oreb"] for r in _sr); _dreb=sum(r["dreb"] for r in _sr)
                            _poss  = sum(1   for ev in poss_evs_ if player_team_id.get(ev["primary_player_id"])==tid_)
                            _psecs = sum(ev["possession_secs"] or 0 for ev in poss_evs_
                                         if player_team_id.get(ev["primary_player_id"])==tid_)
                            return {
                                "PTS":pts_, "POSS":_poss,
                                "POSS TIME":_fmt_s(_psecs),
                                "AVG POSS":_fmt_s(_psecs/_poss) if _poss else "—",
                                "PPP":round(pts_/_poss,3) if _poss else "—",
                                "FGM":_fgm,"FGA":_fga,"FG%":f"{_fgm/_fga*100:.1f}%" if _fga else "—",
                                "3PM":_tpm,"3PA":_tpa,"3P%":f"{_tpm/_tpa*100:.1f}%" if _tpa else "—",
                                "FTM":_ftm,"FTA":_fta,"FT%":f"{_ftm/_fta*100:.1f}%" if _fta else "—",
                                "AST":sum(r["ast"] for r in _sr),
                                "OREB":_oreb,"DREB":_dreb,"REB":_oreb+_dreb,
                                "STL":sum(r["stl"] for r in _sr),
                                "BLK":sum(r["blk"] for r in _sr),
                                "TOV":sum(r["tov"] for r in _sr),
                                "PF":sum(r["pf"]  for r in _sr),
                            }

                        _poss_evs = [ev for ev in events_g
                                     if ev["event_type"] != "free_throw" and ev["primary_player_id"]]
                        t1_tot_g = _team_totals(t1id, t1p, _poss_evs)
                        t2_tot_g = _team_totals(t2id, t2p, _poss_evs)

                        if t1_tot_g and t2_tot_g:
                            _stat_order = [
                                ("PTS","Points"),("POSS","Possessions"),
                                ("POSS TIME","Total Poss. Time"),("AVG POSS","Avg Poss. Length"),
                                ("PPP","Points Per Possession"),
                                ("FGM","FG Made"),("FGA","FG Attempted"),("FG%","FG%"),
                                ("3PM","3PT Made"),("3PA","3PT Attempted"),("3P%","3P%"),
                                ("FTM","FT Made"),("FTA","FT Attempted"),("FT%","FT%"),
                                ("AST","Assists"),("REB","Rebounds"),
                                ("OREB","Off. Rebounds"),("DREB","Def. Rebounds"),
                                ("STL","Steals"),("BLK","Blocks"),
                                ("TOV","Turnovers"),("PF","Personal Fouls"),
                            ]
                            _ts_rows = [{"Stat":lbl, t1nm:t1_tot_g.get(k,0), t2nm:t2_tot_g.get(k,0)}
                                        for k,lbl in _stat_order]
                            st.dataframe(pd.DataFrame(_ts_rows), use_container_width=True, hide_index=True)
                        else:
                            st.info("No events logged yet.")

                    # ── Officials ────────────────────────────────────────────
                    with gtab_off:
                        _game_offs = query("""
                            SELECT o.id AS oid, o.name AS oname
                            FROM game_lineup_officials glo
                            JOIN officials o ON o.id = glo.official_id
                            WHERE glo.game_id = ?
                        """, (g["id"],))
                        if not _game_offs:
                            st.info("No officials logged for this game.")
                        else:
                            _off_stats = {o["oid"]:{"name":o["oname"],"t1":0,"t2":0} for o in _game_offs}
                            for ev in events_g:
                                if ev["event_type"] != "foul": continue
                                _oid = ev["official_id"]; _fp = ev["secondary_player_id"]
                                if _oid in _off_stats and _fp and _fp in player_team_id:
                                    if player_team_id[_fp] == t1id: _off_stats[_oid]["t1"] += 1
                                    else: _off_stats[_oid]["t2"] += 1
                            _off_rows = [{"Official":s["name"],
                                          f"Calls vs {t1nm}":s["t1"],
                                          f"Calls vs {t2nm}":s["t2"],
                                          "Total":s["t1"]+s["t2"]}
                                         for s in _off_stats.values()]
                            st.dataframe(pd.DataFrame(_off_rows), use_container_width=True, hide_index=True)

                    # ── Hot Zones ────────────────────────────────────────────
                    with gtab_hz:
                        _zf1, _zf2 = st.columns(2)
                        _team_filt = _zf1.selectbox("Team", ["Both Teams", t1nm, t2nm],
                                                    key=f"hz_team_{g['id']}")
                        if _team_filt == t1nm:
                            _hz_pls = [{"pid":pid,"pname":s["name"]} for pid,s in stats_g.items() if s["team_id"]==t1id]
                        elif _team_filt == t2nm:
                            _hz_pls = [{"pid":pid,"pname":s["name"]} for pid,s in stats_g.items() if s["team_id"]==t2id]
                        else:
                            _hz_pls = [{"pid":pid,"pname":s["name"]} for pid,s in stats_g.items()]
                        _pl_filt = _zf2.selectbox("Player", ["All Players"]+[p["pname"] for p in _hz_pls],
                                                  key=f"hz_player_{g['id']}")

                        _shot_evs = [ev for ev in events_g
                                     if ev["event_type"]=="shot" and ev.get("zone")]
                        if _pl_filt != "All Players":
                            _mp = next((p for p in _hz_pls if p["pname"]==_pl_filt), None)
                            if _mp:
                                _shot_evs = [ev for ev in _shot_evs if ev["primary_player_id"]==_mp["pid"]]
                        elif _team_filt != "Both Teams":
                            _tf = t1id if _team_filt==t1nm else t2id
                            _shot_evs = [ev for ev in _shot_evs if player_team_id.get(ev["primary_player_id"])==_tf]

                        render_hot_zones(_shot_evs)

# ══════════════════════════════════════════════════════════════════════════════
#  MATCHUP SIMULATOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_mu:
    other_teams = [t for t in all_teams if t["id"]!=team_id]
    if not other_teams:
        st.info("Need at least two teams.")
    else:
        opp_map={t["name"]:t["id"] for t in other_teams}
        opp_name=st.selectbox("Select Opponent", list(opp_map.keys()))
        opp_id=opp_map[opp_name]

        with st.spinner("Projecting…"):
            mu=compute_matchup(team_id, opp_id)

        st.subheader(f"{sel_name}  vs  {opp_name}")

        c1,c2,c3=st.columns(3)
        c1.metric(sel_name,    f"{mu['proj_a']:.1f} pts")
        c2.metric("Win Prob",  f"{mu['prob_a']*100:.0f}% / {(1-mu['prob_a'])*100:.0f}%")
        c3.metric(opp_name,    f"{mu['proj_b']:.1f} pts")

        method_lbl = "efficiency-based (tracked game data)" if mu["method"]=="efficiency" else "score-based"
        st.caption(f"Projection method: {method_lbl}")

        # Head-to-head history
        if mu["h2h"]:
            st.subheader("Head-to-Head History")
            h2h_rows=[]
            for g in mu["h2h"]:
                if g["team1_id"]==team_id:
                    me,them=g["home_score"],g["away_score"]
                else:
                    me,them=g["away_score"],g["home_score"]
                res="W" if me>them else "L"
                h2h_rows.append({"Date":g["date"],"Result":res,f"{sel_name}":me,f"{opp_name}":them})
            st.dataframe(pd.DataFrame(h2h_rows), use_container_width=True, hide_index=True)

        # Side-by-side stat comparison
        st.subheader("Team Comparison")
        comp={"Stat":[],sel_name:[],opp_name:[]}
        basic_a=games_for_team(team_id); basic_b=games_for_team(opp_id)
        wa2,la2,pfa2,paa2=record_from_games(basic_a,team_id)
        wb2,lb2,pfb2,pab2=record_from_games(basic_b,opp_id)
        gpa2=len(basic_a); gpb2=len(basic_b)

        def add(label, va, vb): comp["Stat"].append(label); comp[sel_name].append(va); comp[opp_name].append(vb)
        add("Record", f"{wa2}-{la2}", f"{wb2}-{lb2}")
        add("Win %", f"{wa2/gpa2*100:.1f}%" if gpa2 else "—", f"{wb2/gpb2*100:.1f}%" if gpb2 else "—")
        add("PPG", f"{pfa2/gpa2:.1f}" if gpa2 else "—", f"{pfb2/gpb2:.1f}" if gpb2 else "—")
        add("PA/G", f"{paa2/gpa2:.1f}" if gpa2 else "—", f"{pab2/gpb2:.1f}" if gpb2 else "—")

        adv_a2=mu["adv_a"]; adv_b2=mu["adv_b"]
        if adv_a2 and adv_b2:
            add("ORtg",  f"{adv_a2['ortg']:.1f}",  f"{adv_b2['ortg']:.1f}")
            add("DRtg",  f"{adv_a2['drtg']:.1f}",  f"{adv_b2['drtg']:.1f}")
            add("Net Rtg",f"{adv_a2['net']:+.1f}", f"{adv_b2['net']:+.1f}")
            add("eFG%",  f"{adv_a2['efg']*100:.1f}%",  f"{adv_b2['efg']*100:.1f}%")
            add("Opp eFG%",f"{adv_a2['oefg']*100:.1f}%",f"{adv_b2['oefg']*100:.1f}%")
            add("TS%",   f"{adv_a2['ts']*100:.1f}%",  f"{adv_b2['ts']*100:.1f}%")
            add("TOV%",  f"{adv_a2['tov_r']*100:.1f}%",f"{adv_b2['tov_r']*100:.1f}%")
            add("OREB%", f"{adv_a2['oreb_p']*100:.1f}%",f"{adv_b2['oreb_p']*100:.1f}%")
            add("Pace",  f"{adv_a2['pace']:.1f}", f"{adv_b2['pace']:.1f}")
        st.dataframe(pd.DataFrame(comp), use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
#  NOTES
# ══════════════════════════════════════════════════════════════════════════════
with tab_notes:
    from Database.db import execute as db_execute
    current_notes = query("SELECT notes FROM teams WHERE id=?", (team_id,))
    existing = current_notes[0]["notes"] if current_notes else ""
    new_notes = st.text_area(
        f"Notes — {sel_name}",
        value=existing,
        height=400,
        placeholder="Scouting notes, tendencies, player observations, game plans…",
        key=f"team_notes_{team_id}",
    )
    if st.button("💾 Save Notes", type="primary", key="save_notes_analytics"):
        db_execute("UPDATE teams SET notes=? WHERE id=?", (new_notes, team_id))
        st.success("Notes saved.")

# ══════════════════════════════════════════════════════════════════════════════
#  AI INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.subheader("AI-Generated Insights")

    try:
        import anthropic as _ant
        HAS_ANT = True
    except ImportError:
        HAS_ANT = False

    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY") or ""
    except Exception:
        api_key = ""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
    if not api_key:
        api_key = st.text_input("Anthropic API Key", type="password",
                                 placeholder="sk-ant-…  (stored only for this session)")

    focus = st.multiselect("Focus Areas", ["Strengths","Weaknesses","Shooting","Defense",
                                            "Player Highlights","Game Trends","Coaching Tips"],
                           default=["Strengths","Weaknesses","Player Highlights"])

    if st.button("Generate Insights", type="primary", disabled=not (HAS_ANT and api_key)):
        if not HAS_ANT:
            st.error("anthropic package not installed.")
        elif not api_key:
            st.warning("Enter an API key above.")
        else:
            # Build context string
            all_gs2  = games_for_team(team_id)
            adv2     = compute_team_tracked(team_id)
            w2,l2,pf2,pa2 = record_from_games(all_gs2, team_id)
            gp2=len(all_gs2)

            ctx = f"""Team: {sel_name}
Class: {team_info['class']} | Gender: {'Men' if team_info['gender']=='M' else 'Women'}
Overall Record: {w2}-{l2}  ({w2/gp2*100:.1f}% win rate, {gp2} games)
PPG: {pf2/gp2:.1f} | PA/G: {pa2/gp2:.1f} | Avg Margin: {(pf2-pa2)/gp2:+.1f}
"""
            if adv2:
                ctx += f"""
--- Advanced Stats ({adv2['gp']} tracked games) ---
ORtg: {adv2['ortg']:.1f} | DRtg: {adv2['drtg']:.1f} | Net Rating: {adv2['net']:+.1f}
Pace: {adv2['pace']:.1f} poss/game
eFG%: {adv2['efg']*100:.1f}% | Opp eFG%: {adv2['oefg']*100:.1f}%
TS%: {adv2['ts']*100:.1f}% | TOV%: {adv2['tov_r']*100:.1f}%
OREB%: {adv2['oreb_p']*100:.1f}% | FT Rate: {adv2['ft_r']:.2f}
FG%: {adv2['fgp']*100:.1f}% | 3P%: {adv2['tpp']*100:.1f}% | FT%: {adv2['ftp']*100:.1f}%
AST/G: {adv2['ast_pg']:.1f} | STL/G: {adv2['stl_pg']:.1f} | BLK/G: {adv2['blk_pg']:.1f} | TOV/G: {adv2['tov_pg']:.1f}
"""
            # Top players
            players2 = query("SELECT id, name, number FROM players WHERE team_id=? ORDER BY name", (team_id,))
            top_players=[]
            for p in players2:
                c=compute_player_career(p["id"])
                if c and c["gp"]>0:
                    top_players.append((p["name"], c["pts"]/c["gp"], c))
            top_players.sort(key=lambda x: x[1], reverse=True)
            if top_players:
                ctx+="\n--- Top Players (per game averages) ---\n"
                for name,_,c in top_players[:5]:
                    gp3=c["gp"]
                    ctx+=(f"{name}: {c['pts']/gp3:.1f}pts {(c['oreb']+c['dreb'])/gp3:.1f}reb "
                          f"{c['ast']/gp3:.1f}ast {c['stl']/gp3:.1f}stl {c['blk']/gp3:.1f}blk "
                          f"| FG%: {c['fgm']/c['fga']*100:.1f}%" if c['fga'] else f"{name}: limited data")
                    ctx+="\n"

            focus_str = ", ".join(focus) if focus else "general analysis"
            prompt = f"""You are an expert basketball analyst. Analyze this team and provide actionable insights.

{ctx}

Focus your analysis on: {focus_str}

Structure your response with clear sections. Be specific, reference the actual numbers, and provide concrete recommendations. Keep it concise but insightful."""

            with st.spinner("Generating insights…"):
                try:
                    client = _ant.Anthropic(api_key=api_key)
                    with client.messages.stream(
                        model="claude-sonnet-4-6",
                        max_tokens=1024,
                        messages=[{"role":"user","content":prompt}]
                    ) as stream:
                        st.write_stream(stream.text_stream)
                except Exception as e:
                    st.error(f"API error: {e}")

    if not HAS_ANT:
        st.info("Run `pip install anthropic` to enable AI insights.")
    elif not api_key:
        st.info("Enter your Anthropic API key above to generate insights.")
