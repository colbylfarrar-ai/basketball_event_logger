import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import streamlit as st
from Database.db import query, initialize_database

initialize_database()

st.title("Rankings")

CLASS_ORDER = ["B2","B1","A","2A","3A","4A","5A","6A","N/A"]

# ══════════════════════════════════════════════════════════════════════════════
#  FILTERS
# ══════════════════════════════════════════════════════════════════════════════

f1, f2, f3 = st.columns(3)
sel_class  = f1.multiselect("Class", CLASS_ORDER, default=CLASS_ORDER)
sel_gender = f2.selectbox("Gender", ["All","M","F"])
min_gp     = f3.number_input("Min Games Played", min_value=0, value=0, step=1)

# ══════════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def normalize(s: pd.Series, higher_is_better=True) -> pd.Series:
    lo, hi = s.min(), s.max()
    if hi == lo:
        return pd.Series(0.5, index=s.index)
    n = (s - lo) / (hi - lo)
    return n if higher_is_better else 1 - n

def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df[df["Class"].isin(sel_class)]
    if sel_gender != "All":
        df = df[df["Gender"] == sel_gender]
    df = df[df["GP"] >= min_gp]
    return df

def streak(results: list[int]) -> str:
    """W/L streak from most-recent-first list of 1=win,0=loss."""
    if not results:
        return "—"
    cur, cnt = ("W" if results[0] else "L"), 0
    for r in results:
        if ("W" if r else "L") == cur:
            cnt += 1
        else:
            break
    return f"{cur}{cnt}"

def record_str(w, l):
    return f"{w}-{l}"

# ══════════════════════════════════════════════════════════════════════════════
#  ALL-GAMES COMPUTATION  (score-based only)
# ══════════════════════════════════════════════════════════════════════════════

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
        "results_chrono":[],   # 1=W,0=L oldest first
        "opponents":[],        # (opp_id, result)
        "margins":[],          # pts_for - pts_against per game
    } for t in teams}

    for g in games:
        t1,t2 = g["team1_id"],g["team2_id"]
        h,a   = g["home_score"],g["away_score"]
        if t1 not in rec or t2 not in rec:
            continue
        t1w = 1 if h > a else 0
        for tid,opp,sf,sa,is_home,win in [
            (t1,t2,h,a,True,t1w),
            (t2,t1,a,h,False,1-t1w),
        ]:
            r = rec[tid]
            r["gp"]          += 1
            r["pts_for"]     += sf
            r["pts_against"] += sa
            r["opponents"].append((opp, win))
            r["results_chrono"].append(win)
            r["margins"].append(sf - sa)
            if win:
                r["w"] += 1
                if is_home: r["hw"] += 1
                else:        r["aw"] += 1
            else:
                r["l"] += 1
                if is_home: r["hl"] += 1
                else:        r["al"] += 1

    # Raw win%
    wp = {tid: (r["w"]/r["gp"] if r["gp"] else 0.0) for tid,r in rec.items()}

    rows = []
    for tid,r in rec.items():
        opps = r["opponents"]
        if opps:
            opp_wp = [wp.get(oid,0.0) for oid,_ in opps]
            sos    = sum(opp_wp)/len(opp_wp)
            tot_w  = sum(opp_wp)
            win_w  = sum(w for (oid,res),w in zip(opps,opp_wp) if res==1)
            sor    = win_w/tot_w if tot_w else 0.0
        else:
            sos=sor=0.0

        gp   = r["gp"]
        ppg  = r["pts_for"]/gp  if gp else 0.0
        papg = r["pts_against"]/gp if gp else 0.0
        avg_margin  = np.mean(r["margins"]) if r["margins"] else 0.0
        best_win    = max(r["margins"]) if r["margins"] else 0
        worst_loss  = min(r["margins"]) if r["margins"] else 0
        cur_streak  = streak(list(reversed(r["results_chrono"])))

        rows.append({
            "Team":r["name"],"Class":r["class"],"Gender":r["gender"],
            "GP":gp,"W":r["w"],"L":r["l"],
            "W%":round(wp[tid]*100,1),
            "PPG":round(ppg,1),"PA/G":round(papg,1),
            "Diff":round(ppg-papg,1),
            "SOS":round(sos*100,1),
            "SOR":round(sor*100,1),
            "Home":record_str(r["hw"],r["hl"]),
            "Away":record_str(r["aw"],r["al"]),
            "Best Win":best_win,"Worst Loss":worst_loss,
            "Streak":cur_streak,
            # internal
            "_wp":wp[tid],"_sos":sos,"_sor":sor,"_diff":ppg-papg,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["Power Score"] = (
        normalize(df["_sor"])*0.35 +
        normalize(df["_wp"])*0.30  +
        normalize(df["_diff"])*0.20 +
        normalize(df["_sos"])*0.15
    ).mul(100).round(1)
    df["Rank"] = df["Power Score"].rank(ascending=False,method="min").astype(int)
    return df.sort_values("Rank").reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TRACKED-GAMES TEAM STATS  (event-level)
# ══════════════════════════════════════════════════════════════════════════════

def game_team_stats(game_id, t1id, t2id):
    """Returns (t1_stats, t2_stats) dicts from game events, or (None,None)."""
    lp = query("SELECT player_id,team_id FROM game_lineup_players WHERE game_id=?", (game_id,))
    if not lp:
        return None, None
    pt = {r["player_id"]: r["team_id"] for r in lp}

    def blank():
        return dict(pts=0,fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,
                    oreb=0,dreb=0,tov=0,stl=0,blk=0,ast=0,poss_secs=0.0)
    s1,s2 = blank(),blank()
    def ts(tid): return s1 if tid==t1id else s2

    events = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id",(game_id,))
    for ev in events:
        prim = ev["primary_player_id"]
        ptm  = pt.get(prim)
        psec = ev["possession_secs"] or 0.0
        if ptm: ts(ptm)["poss_secs"] += psec

        if ev["event_type"]=="shot":
            if ptm:
                s=ts(ptm); s["fga"]+=1
                if ev["shot_type"]==3: s["tpa"]+=1
                if ev["shot_result"]=="make":
                    s["fgm"]+=1; s["pts"]+=ev["shot_type"]
                    if ev["shot_type"]==3: s["tpm"]+=1
                    pf=ev["pass_from_id"]
                    if pf and pt.get(pf)==ptm: s["ast"]+=1
            if ev["blocked_by_id"]:
                bt=pt.get(ev["blocked_by_id"])
                if bt: ts(bt)["blk"]+=1
            reb=ev["rebound_by_id"]
            if reb and prim:
                rt,st2=pt.get(reb),pt.get(prim)
                if rt and st2:
                    (ts(rt)["oreb"] if rt==st2 else ts(rt).__setitem__("dreb",ts(rt)["dreb"]+1))
                    if rt==st2: ts(rt)["oreb"]+=1
                    else:        ts(rt)["dreb"]+=1

        elif ev["event_type"]=="free_throw":
            if ptm:
                s=ts(ptm); s["fta"]+=1
                if ev["shot_result"]=="make": s["ftm"]+=1; s["pts"]+=1
            reb=ev["rebound_by_id"]
            if reb and prim:
                rt,st2=pt.get(reb),pt.get(prim)
                if rt and st2:
                    if rt==st2: ts(rt)["oreb"]+=1
                    else:        ts(rt)["dreb"]+=1

        elif ev["event_type"]=="turnover":
            if ptm: ts(ptm)["tov"]+=1
            stl=ev["stolen_by_id"]
            if stl:
                st2=pt.get(stl)
                if st2: ts(st2)["stl"]+=1

    return s1,s2


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

    # Global win% from all games (for SOS)
    gall = {t["id"]:{"w":0,"gp":0} for t in teams}
    for g in all_scored:
        t1,t2,h,a=g["team1_id"],g["team2_id"],g["home_score"],g["away_score"]
        if t1 in gall:
            gall[t1]["gp"]+=1
            if h>a: gall[t1]["w"]+=1
        if t2 in gall:
            gall[t2]["gp"]+=1
            if a>h: gall[t2]["w"]+=1
    wp_all={tid:(v["w"]/v["gp"] if v["gp"] else 0.0) for tid,v in gall.items()}

    def blank_rec(t):
        return dict(name=t["name"],cls=t["class"],gen=t["gender"],
                    gp=0,w=0,l=0,pts_for=0,pts_against=0,
                    hw=0,hl=0,aw=0,al=0,
                    results_chrono=[],opponents=[],margins=[],
                    fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,
                    oreb=0,dreb=0,tov=0,stl=0,blk=0,ast=0,poss_secs=0.0,
                    opp_fga=0,opp_fgm=0,opp_tpa=0,opp_tpm=0,
                    opp_fta=0,opp_ftm=0,opp_oreb=0,opp_dreb=0,
                    opp_tov=0,opp_pts=0,opp_poss_secs=0.0)
    rec = {t["id"]: blank_rec(t) for t in teams}

    for g in tracked:
        t1,t2,h,a,gid=g["team1_id"],g["team2_id"],g["home_score"],g["away_score"],g["id"]
        if t1 not in rec or t2 not in rec: continue
        s1,s2 = game_team_stats(gid,t1,t2)
        t1w = 1 if h>a else 0

        for tid,opp,sf,sa,is_home,win,my_s,opp_s in [
            (t1,t2,h,a,True, t1w,   s1,s2),
            (t2,t1,a,h,False,1-t1w, s2,s1),
        ]:
            r=rec[tid]
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
                for k in ["fga","fgm","tpa","tpm","fta","ftm","oreb","dreb",
                          "tov","stl","blk","ast","poss_secs"]:
                    r[k]+=my_s[k]
            if opp_s:
                for k in ["fga","fgm","tpa","tpm","fta","ftm","oreb","dreb","tov","pts","poss_secs"]:
                    r[f"opp_{k}"]+=opp_s[k]

    rows=[]
    for tid,r in rec.items():
        opps=r["opponents"]
        if opps:
            owp=[wp_all.get(oid,0.0) for oid,_ in opps]
            sos=sum(owp)/len(owp)
            tw=sum(owp); ww=sum(w for (oid,res),w in zip(opps,owp) if res==1)
            sor=ww/tw if tw else 0.0
        else:
            sos=sor=0.0

        gp=r["gp"]
        ppg =r["pts_for"]/gp  if gp else 0.0
        papg=r["pts_against"]/gp if gp else 0.0
        wpc =r["w"]/gp if gp else 0.0

        # Possessions (Hollinger)
        poss    =max(0.1, r["fga"] - r["oreb"] + r["tov"] + 0.44*r["fta"])
        opp_pos =max(0.1, r["opp_fga"] - r["opp_oreb"] + r["opp_tov"] + 0.44*r["opp_fta"])

        ortg = 100*r["pts_for"]/poss
        drtg = 100*r["pts_against"]/opp_pos
        net  = ortg-drtg
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
        ast_r  = r["ast"]/r["fgm"] if r["fgm"] else 0.0  # ast-to-made ratio

        best_win   = max(r["margins"]) if r["margins"] else 0
        worst_loss = min(r["margins"]) if r["margins"] else 0
        cur_streak = streak(list(reversed(r["results_chrono"])))

        rows.append({
            "Team":r["name"],"Class":r["cls"],"Gender":r["gen"],
            "GP":gp,"W":r["w"],"L":r["l"],
            "W%":round(wpc*100,1),
            "PPG":round(ppg,1),"PA/G":round(papg,1),"Diff":round(ppg-papg,1),
            "SOS":round(sos*100,1),"SOR":round(sor*100,1),
            "ORtg":round(ortg,1),"DRtg":round(drtg,1),"Net Rtg":round(net,1),
            "Pace":round(pace,1),
            "eFG%":round(efg*100,1),"Opp eFG%":round(oefg*100,1),
            "TS%":round(ts_*100,1),"Opp TS%":round(ots*100,1),
            "FG%":round(fgp*100,1),"3P%":round(tpp*100,1),"FT%":round(ftp*100,1),
            "TOV%":round(tov_r*100,1),
            "OREB%":round(oreb_p*100,1),"DREB%":round(dreb_p*100,1),
            "FT Rate":round(ft_r,2),"3PAr":round(tpar*100,1),
            "AST Ratio":round(ast_r*100,1),
            "AST/G":round(r["ast"]/gp,1) if gp else 0,
            "STL/G":round(r["stl"]/gp,1) if gp else 0,
            "BLK/G":round(r["blk"]/gp,1) if gp else 0,
            "TOV/G":round(r["tov"]/gp,1) if gp else 0,
            "OREB/G":round(r["oreb"]/gp,1) if gp else 0,
            "DREB/G":round(r["dreb"]/gp,1) if gp else 0,
            "Home":record_str(r["hw"],r["hl"]),
            "Away":record_str(r["aw"],r["al"]),
            "Best Win":best_win,"Worst Loss":worst_loss,"Streak":cur_streak,
            "_wp":wpc,"_sos":sos,"_sor":sor,"_diff":ppg-papg,
            "_net":net,"_ts":ts_,"_oreb":oreb_p,"_tov":tov_r,
        })

    if not rows:
        return pd.DataFrame()

    df=pd.DataFrame(rows)
    df["Power Score"]=(
        normalize(df["_net"])*0.25  +
        normalize(df["_sor"])*0.25  +
        normalize(df["_wp"])*0.20   +
        normalize(df["_ts"])*0.15   +
        normalize(df["_diff"])*0.15
    ).mul(100).round(1)
    df["Rank"]=df["Power Score"].rank(ascending=False,method="min").astype(int)
    return df.sort_values("Rank").reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
#  DISPLAY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

_show_table_call_count = 0

def show_table(df: pd.DataFrame, display_cols: list[str], sort_default: str):
    global _show_table_call_count
    _show_table_call_count += 1
    uid = _show_table_call_count
    if df.empty:
        st.info("No data available.")
        return
    filtered = apply_filters(df)
    if filtered.empty:
        st.info("No teams match the selected filters.")
        return
    sort_col = st.selectbox("Sort by", display_cols,
                             index=display_cols.index(sort_default) if sort_default in display_cols else 0,
                             key=f"sort_{uid}_{sort_default}")
    asc = sort_col in ("DRtg","Opp eFG%","Opp TS%","TOV%","TOV/G","PA/G","Worst Loss","L")
    out = filtered[display_cols].sort_values(sort_col, ascending=asc).reset_index(drop=True)
    out.index += 1
    st.dataframe(out, use_container_width=True)

def show_class_breakdown(df: pd.DataFrame, display_cols: list[str]):
    if df.empty:
        return
    filtered = apply_filters(df)
    for cls in CLASS_ORDER:
        cls_df = filtered[filtered["Class"]==cls]
        if cls_df.empty:
            continue
        with st.expander(f"Class {cls}  ({len(cls_df)} teams)"):
            out = cls_df[display_cols].sort_values("Power Score",ascending=False).reset_index(drop=True)
            out.index += 1
            st.dataframe(out, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_all, tab_tracked = st.tabs(["Everything", "Tracked Games"])

with tab_all:
    st.caption("Rankings built from all games with a final score — tracked and non-tracked.")
    with st.spinner("Computing…"):
        df_all = compute_all_rankings()

    ALL_COLS = ["Rank","Team","Class","Gender","GP","W","L","W%",
                "PPG","PA/G","Diff","SOS","SOR",
                "Home","Away","Best Win","Worst Loss","Streak","Power Score"]

    st.subheader("Overall Rankings")
    show_table(df_all, ALL_COLS, "Rank")

    st.subheader("By Class")
    show_class_breakdown(df_all, ALL_COLS)

with tab_tracked:
    st.caption("Rankings built from fully-tracked games using possession logic and event data.")
    with st.spinner("Computing…"):
        df_tr = compute_tracked_rankings()

    # Two sub-tabs: core stats and advanced stats
    sub_core, sub_adv, sub_shoot, sub_misc = st.tabs(
        ["Core", "Efficiency", "Shooting", "Per Game / Misc"]
    )

    CORE_COLS = ["Rank","Team","Class","Gender","GP","W","L","W%",
                 "PPG","PA/G","Diff","SOS","SOR",
                 "Home","Away","Streak","Power Score"]

    EFF_COLS  = ["Rank","Team","Class","Gender","GP",
                 "ORtg","DRtg","Net Rtg","Pace",
                 "eFG%","Opp eFG%","TS%","Opp TS%",
                 "TOV%","OREB%","DREB%","Power Score"]

    SHOOT_COLS= ["Rank","Team","Class","Gender","GP",
                 "FG%","eFG%","TS%","3P%","FT%",
                 "3PAr","FT Rate","AST Ratio","Power Score"]

    MISC_COLS = ["Rank","Team","Class","Gender","GP",
                 "AST/G","STL/G","BLK/G","TOV/G","OREB/G","DREB/G",
                 "Best Win","Worst Loss","Streak","Power Score"]

    with sub_core:
        st.subheader("Overall")
        show_table(df_tr, CORE_COLS, "Rank")
        st.subheader("By Class")
        show_class_breakdown(df_tr, CORE_COLS)

    with sub_adv:
        st.subheader("Efficiency Ratings")
        st.caption("ORtg/DRtg = points per 100 possessions. Pace = estimated possessions per game.")
        show_table(df_tr, EFF_COLS, "Net Rtg")
        st.subheader("By Class")
        show_class_breakdown(df_tr, EFF_COLS)

    with sub_shoot:
        st.subheader("Shooting")
        st.caption("eFG% weights 3-pointers. TS% accounts for free throws. 3PAr = 3PA/FGA. FT Rate = FTA/FGA.")
        show_table(df_tr, SHOOT_COLS, "TS%")
        st.subheader("By Class")
        show_class_breakdown(df_tr, SHOOT_COLS)

    with sub_misc:
        st.subheader("Per-Game Totals")
        show_table(df_tr, MISC_COLS, "STL/G")
        st.subheader("By Class")
        show_class_breakdown(df_tr, MISC_COLS)
