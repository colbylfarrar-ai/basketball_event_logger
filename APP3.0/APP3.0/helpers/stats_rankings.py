import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import numpy as np
import streamlit as st
from Database.db import query
from helpers.game_utils import streak, record_str, normalize


def game_team_stats(game_id, t1id, t2id):
    lp = query("SELECT player_id,team_id FROM game_lineup_players WHERE game_id=?", (game_id,))
    if not lp:
        return None, None
    pt = {r["player_id"]: r["team_id"] for r in lp}

    def blank():
        return dict(
            pts=0, fga=0, fgm=0, tpa=0, tpm=0, fta=0, ftm=0,
            oreb=0, dreb=0, tov=0, stl=0, blk=0, ast=0,
            poss_secs=0.0, poss_count=0,
            # Extended tracking
            ast_fgm=0,                    # Assisted makes
            paint_fga=0, paint_fgm=0,    # Zone C, shot_type=2 (paint proxy)
            q4_pts=0,                     # Q4 points scored
        )
    s1, s2 = blank(), blank()
    def ts(tid): return s1 if tid == t1id else s2

    events = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (game_id,))
    for ev in events:
        prim = ev["primary_player_id"]
        ptm  = pt.get(prim)
        psec = ev["possession_secs"] or 0.0
        if ptm: ts(ptm)["poss_secs"] += psec

        if ev["event_type"] in ("shot","turnover") and ptm:
            ts(ptm)["poss_count"] += 1

        if ev["event_type"] == "shot":
            if ptm:
                s = ts(ptm)
                s["fga"] += 1
                is_3 = ev["shot_type"] == 3
                if is_3:
                    s["tpa"] += 1
                else:
                    if ev.get("zone") == "C":
                        s["paint_fga"] += 1
                if ev["shot_result"] == "make":
                    s["fgm"] += 1
                    s["pts"] += ev["shot_type"]
                    if is_3:
                        s["tpm"] += 1
                    else:
                        if ev.get("zone") == "C":
                            s["paint_fgm"] += 1
                    if ev.get("quarter") == 4:
                        s["q4_pts"] += ev["shot_type"]
                    pf = ev["pass_from_id"]
                    if pf and pt.get(pf) == ptm:
                        s["ast"] += 1
                        s["ast_fgm"] += 1

            if ev["blocked_by_id"]:
                bt = pt.get(ev["blocked_by_id"])
                if bt: ts(bt)["blk"] += 1
            reb = ev["rebound_by_id"]
            if reb and prim:
                rt, st2 = pt.get(reb), pt.get(prim)
                if rt and st2:
                    if rt == st2: ts(rt)["oreb"] += 1
                    else:         ts(rt)["dreb"] += 1

        elif ev["event_type"] == "free_throw":
            if ptm:
                s = ts(ptm)
                s["fta"] += 1
                if ev["shot_result"] == "make":
                    s["ftm"] += 1
                    s["pts"] += 1
                    if ev.get("quarter") == 4:
                        s["q4_pts"] += 1
            reb = ev["rebound_by_id"]
            if reb and prim:
                rt, st2 = pt.get(reb), pt.get(prim)
                if rt and st2:
                    if rt == st2: ts(rt)["oreb"] += 1
                    else:         ts(rt)["dreb"] += 1

        elif ev["event_type"] == "turnover":
            if ptm: ts(ptm)["tov"] += 1
            stl = ev["stolen_by_id"]
            if stl:
                st2 = pt.get(stl)
                if st2: ts(st2)["stl"] += 1

    return s1, s2


@st.cache_data
def compute_all_rankings() -> pd.DataFrame:
    teams = query("SELECT id, name, class, gender FROM teams")
    games = query("""
        SELECT id, team1_id, team2_id, home_score, away_score, date
        FROM games
        WHERE home_score IS NOT NULL AND away_score IS NOT NULL
              AND home_score != away_score
        ORDER BY date
    """)
    if not teams:
        return pd.DataFrame()

    rec = {t["id"]: {
        "name":t["name"],"class":t["class"],"gender":t["gender"],
        "gp":0,"w":0,"l":0,"pts_for":0,"pts_against":0,
        "hw":0,"hl":0,"aw":0,"al":0,
        "results_chrono":[], "opponents":[], "margins":[],
    } for t in teams}

    for g in games:
        t1,t2 = g["team1_id"],g["team2_id"]
        h,a   = g["home_score"],g["away_score"]
        if t1 not in rec or t2 not in rec:
            continue
        t1w = 1 if h > a else 0
        for tid,opp,sf,sa,is_home,win in [
            (t1,t2,h,a,True,t1w),(t2,t1,a,h,False,1-t1w),
        ]:
            r = rec[tid]
            r["gp"]+=1; r["pts_for"]+=sf; r["pts_against"]+=sa
            r["opponents"].append((opp,win)); r["results_chrono"].append(win)
            r["margins"].append(sf-sa)
            if win:
                r["w"]+=1
                if is_home: r["hw"]+=1
                else:        r["aw"]+=1
            else:
                r["l"]+=1
                if is_home: r["hl"]+=1
                else:        r["al"]+=1

    wp = {tid:(r["w"]/r["gp"] if r["gp"] else 0.0) for tid,r in rec.items()}
    rows = []
    for tid,r in rec.items():
        opps = r["opponents"]
        if opps:
            owp = [wp.get(oid,0.0) for oid,_ in opps]
            sos = sum(owp)/len(owp)
            tw  = sum(owp)
            ww  = sum(w for (oid,res),w in zip(opps,owp) if res==1)
            sor = ww/tw if tw else 0.0
        else:
            sos=sor=0.0
        gp   = r["gp"]
        ppg  = r["pts_for"]/gp  if gp else 0.0
        papg = r["pts_against"]/gp if gp else 0.0
        rows.append({
            "Team":r["name"],"Class":r["class"],"Gender":r["gender"],
            "GP":gp,"W":r["w"],"L":r["l"],
            "W%":round(wp[tid]*100,1),
            "PPG":round(ppg,1),"PA/G":round(papg,1),
            "Diff":round(ppg-papg,1),
            "SOS":round(sos*100,1),"SOR":round(sor*100,1),
            "Home":record_str(r["hw"],r["hl"]),
            "Away":record_str(r["aw"],r["al"]),
            "Best Win":max(r["margins"]) if r["margins"] else 0,
            "Worst Loss":min(r["margins"]) if r["margins"] else 0,
            "Streak":streak(list(reversed(r["results_chrono"]))),
            "_wp":wp[tid],"_sos":sos,"_sor":sor,"_diff":ppg-papg,
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["Power Score"] = (
        normalize(df["_sor"])*0.35 + normalize(df["_wp"])*0.30 +
        normalize(df["_diff"])*0.20 + normalize(df["_sos"])*0.15
    ).mul(100).round(1)
    df["Rank"] = df["Power Score"].rank(ascending=False,method="min").astype(int)
    return df.sort_values("Rank").reset_index(drop=True)


@st.cache_data
def compute_tracked_rankings() -> pd.DataFrame:
    teams = query("SELECT id, name, class, gender FROM teams")
    tracked = query("""
        SELECT id,team1_id,team2_id,home_score,away_score,date
        FROM games
        WHERE tracked=1 AND home_score IS NOT NULL AND away_score IS NOT NULL
              AND home_score != away_score
        ORDER BY date
    """)
    all_scored = query("""
        SELECT team1_id,team2_id,home_score,away_score
        FROM games WHERE home_score IS NOT NULL AND away_score IS NOT NULL
              AND home_score != away_score
    """)
    if not teams:
        return pd.DataFrame()

    gall = {t["id"]:{"w":0,"gp":0} for t in teams}
    for g in all_scored:
        t1,t2,h,a = g["team1_id"],g["team2_id"],g["home_score"],g["away_score"]
        if t1 in gall:
            gall[t1]["gp"]+=1
            if h>a: gall[t1]["w"]+=1
        if t2 in gall:
            gall[t2]["gp"]+=1
            if a>h: gall[t2]["w"]+=1
    wp_all = {tid:(v["w"]/v["gp"] if v["gp"] else 0.0) for tid,v in gall.items()}

    def blank_rec(t):
        return dict(
            name=t["name"],cls=t["class"],gen=t["gender"],
            gp=0,w=0,l=0,pts_for=0,pts_against=0,
            hw=0,hl=0,aw=0,al=0,
            results_chrono=[],opponents=[],margins=[],
            fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,
            oreb=0,dreb=0,tov=0,stl=0,blk=0,ast=0,
            poss_secs=0.0,poss_count=0,
            ast_fgm=0, paint_fga=0, paint_fgm=0, q4_pts=0,
            opp_fga=0,opp_fgm=0,opp_tpa=0,opp_tpm=0,
            opp_fta=0,opp_ftm=0,opp_oreb=0,opp_dreb=0,
            opp_tov=0,opp_pts=0,opp_poss_secs=0.0,opp_poss_count=0,
            opp_q4_pts=0,
        )
    rec = {t["id"]: blank_rec(t) for t in teams}

    MY_KEYS = ["fga","fgm","tpa","tpm","fta","ftm","oreb","dreb",
               "tov","stl","blk","ast","poss_secs","poss_count",
               "ast_fgm","paint_fga","paint_fgm","q4_pts"]
    OPP_KEYS = ["fga","fgm","tpa","tpm","fta","ftm","oreb","dreb",
                "tov","pts","poss_secs","poss_count","q4_pts"]

    for g in tracked:
        t1,t2,h,a,gid = g["team1_id"],g["team2_id"],g["home_score"],g["away_score"],g["id"]
        if t1 not in rec or t2 not in rec: continue
        s1,s2 = game_team_stats(gid,t1,t2)
        t1w = 1 if h>a else 0

        for tid,opp,sf,sa,is_home,win,my_s,opp_s in [
            (t1,t2,h,a,True, t1w,   s1,s2),
            (t2,t1,a,h,False,1-t1w, s2,s1),
        ]:
            r = rec[tid]
            r["gp"]+=1; r["pts_for"]+=sf; r["pts_against"]+=sa
            r["opponents"].append((opp,win))
            r["results_chrono"].append(win)
            r["margins"].append(sf-sa)
            if win:
                r["w"]+=1
                if is_home: r["hw"]+=1
                else:        r["aw"]+=1
            else:
                r["l"]+=1
                if is_home: r["hl"]+=1
                else:        r["al"]+=1
            if my_s:
                for k in MY_KEYS:
                    r[k] += my_s.get(k,0)
            if opp_s:
                for k in OPP_KEYS:
                    r[f"opp_{k}"] += opp_s.get(k,0)

    rows = []
    for tid,r in rec.items():
        opps = r["opponents"]
        if opps:
            owp = [wp_all.get(oid,0.0) for oid,_ in opps]
            sos = sum(owp)/len(owp)
            tw  = sum(owp)
            ww  = sum(w for (oid,res),w in zip(opps,owp) if res==1)
            sor = ww/tw if tw else 0.0
        else:
            sos=sor=0.0

        gp   = r["gp"]
        ppg  = r["pts_for"]/gp  if gp else 0.0
        papg = r["pts_against"]/gp if gp else 0.0
        wpc  = r["w"]/gp if gp else 0.0

        poss    = max(0.1, r["fga"] - r["oreb"] + r["tov"] + 0.44*r["fta"])
        opp_pos = max(0.1, r["opp_fga"] - r["opp_oreb"] + r["opp_tov"] + 0.44*r["opp_fta"])

        ortg = 100*r["pts_for"]/poss
        drtg = 100*r["pts_against"]/opp_pos
        net  = ortg - drtg
        pace = (poss+opp_pos)/(2*gp) if gp else 0.0

        efg  = (r["fgm"]+0.5*r["tpm"])/r["fga"] if r["fga"] else 0.0
        ts_  = r["pts_for"]/(2*(r["fga"]+0.44*r["fta"])) if (r["fga"]+0.44*r["fta"])>0 else 0.0
        oefg = (r["opp_fgm"]+0.5*r["opp_tpm"])/r["opp_fga"] if r["opp_fga"] else 0.0
        ots  = r["opp_pts"]/(2*(r["opp_fga"]+0.44*r["opp_fta"])) if (r["opp_fga"]+0.44*r["opp_fta"])>0 else 0.0

        tov_r  = r["tov"]/(r["fga"]+0.44*r["fta"]+r["tov"]) if (r["fga"]+0.44*r["fta"]+r["tov"])>0 else 0.0
        oreb_p = r["oreb"]/(r["oreb"]+r["opp_dreb"]) if (r["oreb"]+r["opp_dreb"])>0 else 0.0
        dreb_p = r["dreb"]/(r["dreb"]+r["opp_oreb"]) if (r["dreb"]+r["opp_oreb"])>0 else 0.0
        ft_r   = r["fta"]/r["fga"] if r["fga"] else 0.0
        tpar   = r["tpa"]/r["fga"] if r["fga"] else 0.0
        fgp    = r["fgm"]/r["fga"] if r["fga"] else 0.0
        tpp    = r["tpm"]/r["tpa"] if r["tpa"] else 0.0
        ftp    = r["ftm"]/r["fta"] if r["fta"] else 0.0
        ast_r  = r["ast"]/r["fgm"] if r["fgm"] else 0.0

        # 2PT metrics
        two_pa  = r["fga"] - r["tpa"]
        two_pm  = r["fgm"] - r["tpm"]
        two_pct = two_pm/two_pa if two_pa else 0.0

        # Assisted / Unassisted FGM
        ast_pct   = r["ast_fgm"]/r["fgm"]*100 if r["fgm"] else 0.0
        unast_pct = 100.0 - ast_pct

        # Paint (zone C, 2PT proxy)
        paint_fg_pct  = r["paint_fgm"]/r["paint_fga"] if r["paint_fga"] else 0.0
        paint_pts_pg  = r["paint_fgm"]*2/gp if gp else 0.0

        # Defensive rates (all denominator from existing opp_ fields)
        opp_2pa   = r["opp_fga"] - r["opp_tpa"]
        blk_rate  = r["blk"]/opp_2pa*100 if opp_2pa else 0.0
        stl_rate  = r["stl"]/opp_pos*100

        # AST/TOV
        ast_tov = r["ast"]/r["tov"] if r["tov"] else 0.0

        # Opp turnover rate & FT rate
        opp_tov_r = r["opp_tov"]/(r["opp_fga"]+0.44*r["opp_fta"]+r["opp_tov"])*100 \
                    if (r["opp_fga"]+0.44*r["opp_fta"]+r["opp_tov"])>0 else 0.0
        opp_ft_r  = r["opp_fta"]/r["opp_fga"] if r["opp_fga"] else 0.0

        # Q4 clutch
        q4_pts_pg  = r["q4_pts"]/gp if gp else 0.0
        q4_pa_pg   = r["opp_q4_pts"]/gp if gp else 0.0
        q4_diff    = q4_pts_pg - q4_pa_pg

        # Scoring distribution (% of total pts from each source)
        total_pts = r["pts_for"] or 1
        pct_2 = (two_pm*2)/total_pts*100
        pct_3 = (r["tpm"]*3)/total_pts*100
        pct_ft= r["ftm"]/total_pts*100

        # Possession tab fields
        pc      = r["poss_count"]
        opc     = r["opp_poss_count"]
        ppp     = r["pts_for"]/pc if pc else 0.0
        opp_ppp = r["pts_against"]/opc if opc else 0.0
        poss_pg = pc/gp if gp else 0.0
        avg_poss_sec  = r["poss_secs"]/pc if pc else 0.0
        tov_per_poss  = r["tov"]/pc if pc else 0.0
        ast_per_poss  = r["ast"]/pc if pc else 0.0

        rows.append({
            "Team":r["name"],"Class":r["cls"],"Gender":r["gen"],
            "GP":gp,"W":r["w"],"L":r["l"],
            "W%":round(wpc*100,1),
            "PPG":round(ppg,1),"PA/G":round(papg,1),"Diff":round(ppg-papg,1),
            "SOS":round(sos*100,1),"SOR":round(sor*100,1),
            "ORtg":round(ortg,1),"DRtg":round(drtg,1),"Net Rtg":round(net,1),
            "Pace":round(pace,1),
            # Shooting
            "FG%":round(fgp*100,1),
            "2P%":round(two_pct*100,1),
            "2PA/G":round(two_pa/gp,1) if gp else 0,
            "eFG%":round(efg*100,1),"Opp eFG%":round(oefg*100,1),
            "TS%":round(ts_*100,1),"Opp TS%":round(ots*100,1),
            "3P%":round(tpp*100,1),"FT%":round(ftp*100,1),
            "TOV%":round(tov_r*100,1),
            "OREB%":round(oreb_p*100,1),"DREB%":round(dreb_p*100,1),
            "FT Rate":round(ft_r,2),"3PAr":round(tpar*100,1),
            "AST Ratio":round(ast_r*100,1),
            "Ast%":round(ast_pct,1),
            "Unast%":round(unast_pct,1),
            "Paint FG%":round(paint_fg_pct*100,1),
            "Paint Pts/G":round(paint_pts_pg,1),
            "Pts from 2%":round(pct_2,1),
            "Pts from 3%":round(pct_3,1),
            "Pts from FT%":round(pct_ft,1),
            # Per Game misc
            "AST/G":round(r["ast"]/gp,1) if gp else 0,
            "STL/G":round(r["stl"]/gp,1) if gp else 0,
            "BLK/G":round(r["blk"]/gp,1) if gp else 0,
            "TOV/G":round(r["tov"]/gp,1) if gp else 0,
            "OREB/G":round(r["oreb"]/gp,1) if gp else 0,
            "DREB/G":round(r["dreb"]/gp,1) if gp else 0,
            # Defense
            "BLK Rate":round(blk_rate,1),
            "STL Rate":round(stl_rate,1),
            "AST/TOV":round(ast_tov,2),
            "Opp TOV%":round(opp_tov_r,1),
            "Opp FT Rate":round(opp_ft_r,2),
            # Clutch
            "Q4 Pts/G":round(q4_pts_pg,1),
            "Q4 PA/G":round(q4_pa_pg,1),
            "Q4 Diff":round(q4_diff,1),
            # Home/Away
            "Home":record_str(r["hw"],r["hl"]),
            "Away":record_str(r["aw"],r["al"]),
            "Best Win":max(r["margins"]) if r["margins"] else 0,
            "Worst Loss":min(r["margins"]) if r["margins"] else 0,
            "Streak":streak(list(reversed(r["results_chrono"]))),
            # Possession tab
            "Poss/G":round(poss_pg,1),
            "PPP":round(ppp,3),
            "Opp PPP":round(opp_ppp,3),
            "Avg Poss (s)":round(avg_poss_sec,1),
            "TOV/Poss":round(tov_per_poss,3),
            "AST/Poss":round(ast_per_poss,3),
            # internals
            "_wp":wpc,"_sos":sos,"_sor":sor,"_diff":ppg-papg,
            "_net":net,"_ts":ts_,"_oreb":oreb_p,"_tov":tov_r,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["Power Score"] = (
        normalize(df["_net"])*0.25 + normalize(df["_sor"])*0.25 +
        normalize(df["_wp"])*0.20  + normalize(df["_ts"])*0.15  +
        normalize(df["_diff"])*0.15
    ).mul(100).round(1)
    df["Rank"] = df["Power Score"].rank(ascending=False,method="min").astype(int)
    return df.sort_values("Rank").reset_index(drop=True)
