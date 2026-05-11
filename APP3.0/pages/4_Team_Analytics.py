import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import streamlit as st
from Database.db import query, initialize_database

initialize_database()

st.title("Team Analytics")

ZONES = ["LC", "LW", "C", "RW", "RC"]

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
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def games_for_team(tid, tracked_only=False):
    cond = "AND g.tracked=1" if tracked_only else ""
    return query(f"""
        SELECT g.*, t1.name AS t1_name, t2.name AS t2_name
        FROM games g
        JOIN teams t1 ON t1.id=g.team1_id
        JOIN teams t2 ON t2.id=g.team2_id
        WHERE (g.team1_id=? OR g.team2_id=?) {cond}
          AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
        ORDER BY g.date
    """, (tid, tid))

def win_loss(game, tid):
    my   = game["home_score"] if game["team1_id"]==tid else game["away_score"]
    opp  = game["away_score"] if game["team1_id"]==tid else game["home_score"]
    return ("W" if my>opp else "L"), my, opp

def opponent_name(game, tid):
    return game["t2_name"] if game["team1_id"]==tid else game["t1_name"]

def home_away(game, tid):
    return "Home" if game["team1_id"]==tid else "Away"

def record_from_games(games_list, tid):
    w=l=pf=pa=0
    for g in games_list:
        res,my,opp = win_loss(g, tid)
        pf+=my; pa+=opp
        if res=="W": w+=1
        else:        l+=1
    return w,l,pf,pa

def zone_color(m, a):
    if not a: return "#2d2d2d","#555"
    p=m/a
    if p>=0.5: return "#1a5c38","#fff"
    if p>=0.35: return "#7a5200","#fff"
    return "#6b1515","#fff"

def render_hot_zones(shot_rows, title=""):
    if title: st.markdown(f"**{title}**")
    zd={z:{2:[0,0],3:[0,0]} for z in ZONES}
    for s in shot_rows:
        z,t=s.get("zone"),s.get("shot_type")
        if z and t:
            zd[z][t][1]+=1
            if s.get("shot_result")=="make": zd[z][t][0]+=1
    for stype,lbl in [(2,"2-Point"),(3,"3-Point")]:
        st.markdown(f"*{lbl}*")
        cols=st.columns(5)
        for i,zone in enumerate(ZONES):
            m,a=zd[zone][stype]
            pct=m/a*100 if a else 0
            bg,fg=zone_color(m,a)
            cols[i].markdown(
                f"""<div style="background:{bg};color:{fg};padding:12px 4px;
                border-radius:8px;text-align:center;font-size:0.85em">
                <b>{zone}</b><br>{m}/{a}<br>{pct:.0f}%</div>""",
                unsafe_allow_html=True)

# ── Player career stats ───────────────────────────────────────────────────────

def compute_player_career(player_id: int):
    rows = query("""
        SELECT glp.game_id, glp.team_id
        FROM game_lineup_players glp
        JOIN games g ON g.id=glp.game_id
        WHERE glp.player_id=? AND g.tracked=1
    """, (player_id,))
    if not rows:
        return None
    game_team = {r["game_id"]: r["team_id"] for r in rows}

    tot = dict(gp=len(rows), pts=0,ast=0,oreb=0,dreb=0,stl=0,blk=0,tov=0,
               fgm=0,fga=0,tpm=0,tpa=0,ftm=0,fta=0,sc=0,pf=0,poss_secs=0.0,
               shots=[])

    for game_id, my_team in game_team.items():
        pt_map = {r["player_id"]:r["team_id"] for r in
                  query("SELECT player_id,team_id FROM game_lineup_players WHERE game_id=?", (game_id,))}
        events = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (game_id,))

        # All lineup players get full game time — no subs tracked
        tot["poss_secs"] += sum(ev["possession_secs"] or 0.0 for ev in events)

        for ev in events:
            pid  = player_id
            et=ev["event_type"]

            if et=="shot":
                if ev["primary_player_id"]==pid:
                    tot["fga"]+=1; tot["sc"]+=1
                    if ev["shot_type"]==3: tot["tpa"]+=1
                    if ev["shot_result"]=="make":
                        tot["fgm"]+=1; tot["pts"]+=ev["shot_type"]
                        if ev["shot_type"]==3: tot["tpm"]+=1
                    if ev["zone"]:
                        tot["shots"].append({"zone":ev["zone"],"shot_type":ev["shot_type"],"shot_result":ev["shot_result"]})
                if ev["pass_from_id"]==pid:
                    tot["sc"]+=1
                    if ev["shot_result"]=="make": tot["ast"]+=1
                if ev["shot_created_by_id"]==pid: tot["sc"]+=1
                if ev["blocked_by_id"]==pid: tot["blk"]+=1
                if ev["rebound_by_id"]==pid:
                    sh_team=pt_map.get(ev["primary_player_id"])
                    if sh_team==my_team: tot["oreb"]+=1
                    else:                tot["dreb"]+=1

            elif et=="free_throw":
                if ev["primary_player_id"]==pid:
                    tot["fta"]+=1
                    if ev["shot_result"]=="make": tot["ftm"]+=1; tot["pts"]+=1
                if ev["rebound_by_id"]==pid:
                    sh_team=pt_map.get(ev["primary_player_id"])
                    if sh_team==my_team: tot["oreb"]+=1
                    else:                tot["dreb"]+=1

            elif et=="foul":
                if ev["secondary_player_id"]==pid: tot["pf"]+=1

            elif et=="turnover":
                if ev["primary_player_id"]==pid: tot["tov"]+=1
                if ev["stolen_by_id"]==pid:      tot["stl"]+=1
    return tot

# ── Team advanced stats (tracked) ────────────────────────────────────────────

def compute_team_tracked(tid):
    tracked = games_for_team(tid, tracked_only=True)
    if not tracked:
        return None

    agg=dict(fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,oreb=0,dreb=0,
             tov=0,stl=0,blk=0,ast=0,poss_secs=0.0,pts=0,
             opp_fga=0,opp_fgm=0,opp_tpa=0,opp_tpm=0,opp_fta=0,opp_ftm=0,
             opp_oreb=0,opp_dreb=0,opp_tov=0,opp_pts=0)

    for g in tracked:
        t1id=g["team1_id"]; t2id=g["team2_id"]
        lp=query("SELECT player_id,team_id FROM game_lineup_players WHERE game_id=?", (g["id"],))
        if not lp: continue
        pt={r["player_id"]:r["team_id"] for r in lp}
        events=query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (g["id"],))

        def ts_(team): return agg if team==tid else None
        def op_(team): return None  # we track opp separately below

        my_s  = dict(fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,oreb=0,dreb=0,tov=0,stl=0,blk=0,ast=0,poss_secs=0.0,pts=0)
        opp_s = dict(fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,oreb=0,dreb=0,tov=0,pts=0)

        for ev in events:
            prim=ev["primary_player_id"]
            ptm =pt.get(prim)
            psec=ev["possession_secs"] or 0.0
            is_mine = ptm==tid

            if is_mine: my_s["poss_secs"]+=psec

            et=ev["event_type"]
            if et=="shot":
                if ptm:
                    bucket = my_s if ptm==tid else opp_s
                    bucket["fga"]+=1
                    if ev["shot_type"]==3: bucket["tpa"]+=1
                    if ev["shot_result"]=="make":
                        bucket["fgm"]+=1; bucket["pts"]+=ev["shot_type"]
                        if ev["shot_type"]==3: bucket["tpm"]+=1
                        pf=ev["pass_from_id"]
                        if pf and pt.get(pf)==ptm:
                            (my_s if ptm==tid else {})["ast"] = my_s["ast"]+(1 if ptm==tid else 0)
                            if ptm==tid: my_s["ast"]+=1
                blk=ev["blocked_by_id"]
                if blk and pt.get(blk)==tid: my_s["blk"]=(my_s.get("blk",0)+1)
                reb=ev["rebound_by_id"]
                if reb and prim:
                    rt=pt.get(reb); st2=pt.get(prim)
                    if rt and st2:
                        if rt==st2:
                            (my_s if rt==tid else opp_s)["oreb"]+=1
                        else:
                            (my_s if rt==tid else opp_s)["dreb"]+=1
            elif et=="free_throw":
                if ptm:
                    bucket = my_s if ptm==tid else opp_s
                    bucket["fta"]+=1
                    if ev["shot_result"]=="make": bucket["ftm"]+=1; bucket["pts"]+=1
            elif et=="turnover":
                if ptm:
                    (my_s if ptm==tid else opp_s)["tov"]+=1
                stl=ev["stolen_by_id"]
                if stl and pt.get(stl)==tid: my_s["stl"]=my_s.get("stl",0)+1

        for k in my_s:  agg[k]+=my_s[k]
        for k in opp_s: agg[f"opp_{k}"]+=opp_s[k]

    gp=len(tracked)
    poss   = max(0.1,agg["fga"]-agg["oreb"]+agg["tov"]+0.44*agg["fta"])
    op_pos = max(0.1,agg["opp_fga"]-agg["opp_oreb"]+agg["opp_tov"]+0.44*agg["opp_fta"])
    ortg=100*agg["pts"]/poss
    drtg=100*agg["opp_pts"]/op_pos
    pace=(poss+op_pos)/(2*gp) if gp else 0
    efg =(agg["fgm"]+0.5*agg["tpm"])/agg["fga"] if agg["fga"] else 0
    ts_ = agg["pts"]/(2*(agg["fga"]+0.44*agg["fta"])) if (agg["fga"]+0.44*agg["fta"]) else 0
    oefg=(agg["opp_fgm"]+0.5*agg["opp_tpm"])/agg["opp_fga"] if agg["opp_fga"] else 0
    tov_r=agg["tov"]/(agg["fga"]+0.44*agg["fta"]+agg["tov"]) if (agg["fga"]+0.44*agg["fta"]+agg["tov"]) else 0
    oreb_p=agg["oreb"]/(agg["oreb"]+agg["opp_dreb"]) if (agg["oreb"]+agg["opp_dreb"]) else 0
    ft_r=agg["fta"]/agg["fga"] if agg["fga"] else 0
    tpar=agg["tpa"]/agg["fga"] if agg["fga"] else 0
    fgp=agg["fgm"]/agg["fga"] if agg["fga"] else 0
    tpp=agg["tpm"]/agg["tpa"] if agg["tpa"] else 0
    ftp=agg["ftm"]/agg["fta"] if agg["fta"] else 0

    return dict(gp=gp,poss=poss,op_pos=op_pos,ortg=ortg,drtg=drtg,net=ortg-drtg,pace=pace,
                efg=efg,oefg=oefg,ts=ts_,tov_r=tov_r,oreb_p=oreb_p,ft_r=ft_r,tpar=tpar,
                fgp=fgp,tpp=tpp,ftp=ftp,
                ast_pg=agg["ast"]/gp,stl_pg=agg.get("stl",0)/gp,blk_pg=agg.get("blk",0)/gp,
                tov_pg=agg["tov"]/gp,oreb_pg=agg["oreb"]/gp,dreb_pg=agg["dreb"]/gp,
                pts_pg=agg["pts"]/gp, **agg)

# ── Matchup projection ────────────────────────────────────────────────────────

def compute_matchup(a_id, b_id):
    gs_a = games_for_team(a_id)
    gs_b = games_for_team(b_id)
    wa,la,pfa,paa = record_from_games(gs_a, a_id)
    wb,lb,pfb,pab = record_from_games(gs_b, b_id)
    gpa=len(gs_a); gpb=len(gs_b)
    ppg_a=pfa/gpa if gpa else 0; papg_a=paa/gpa if gpa else 0
    ppg_b=pfb/gpb if gpb else 0; papg_b=pab/gpb if gpb else 0

    adv_a = compute_team_tracked(a_id)
    adv_b = compute_team_tracked(b_id)

    if adv_a and adv_b:
        # League avg DRtg for calibration
        all_tr = query("""
            SELECT team1_id,team2_id FROM games WHERE tracked=1
              AND home_score IS NOT NULL AND away_score IS NOT NULL
        """)
        league_drtg=100.0  # default
        adv_list=[]
        for t in query("SELECT id FROM teams"):
            ta=compute_team_tracked(t["id"])
            if ta: adv_list.append(ta["drtg"])
        if adv_list: league_drtg=np.mean(adv_list)

        avg_pace=(adv_a["pace"]+adv_b["pace"])/2
        proj_a = (adv_a["ortg"]/100) * avg_pace * (adv_b["drtg"]/league_drtg)
        proj_b = (adv_b["ortg"]/100) * avg_pace * (adv_a["drtg"]/league_drtg)
        method = "efficiency"
    else:
        proj_a = (ppg_a + papg_b) / 2
        proj_b = (ppg_b + papg_a) / 2
        method = "score"

    diff = proj_a - proj_b
    prob_a = 1 / (1 + np.exp(-diff * 0.15))

    # Head-to-head
    h2h = query("""
        SELECT home_score,away_score,date,team1_id
        FROM games
        WHERE ((team1_id=? AND team2_id=?) OR (team1_id=? AND team2_id=?))
          AND home_score IS NOT NULL AND away_score IS NOT NULL
        ORDER BY date DESC
    """, (a_id, b_id, b_id, a_id))

    return dict(proj_a=proj_a, proj_b=proj_b, prob_a=prob_a,
                method=method, h2h=h2h,
                adv_a=adv_a, adv_b=adv_b,
                ppg_a=ppg_a, papg_a=papg_a, ppg_b=ppg_b, papg_b=papg_b,
                wa=wa, la=la, wb=wb, lb=lb)

# ══════════════════════════════════════════════════════════════════════════════
#  TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_ov, tab_pl, tab_gm, tab_mu, tab_ai = st.tabs(
    ["Overview", "Players", "Games", "Matchup Simulator", "AI Insights"]
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
                    "SC":round(c["sc"]/gp,1),"MIN":round(c["poss_secs"]/60/gp,1),"GS":gs,
                    "_pid":p["id"],
                })
            else:
                stat_rows.append({"Player":p["name"],"#":p["number"],"GP":0,
                                   **{k:"—" for k in ["PTS","AST","REB","OREB","DREB","STL","BLK","TOV",
                                                       "FGM","FGA","FG%","3PM","3PA","3P%","FTM","FTA","FT%",
                                                       "eFG%","TS%","SC","MIN","GS"]},
                                   "_pid":p["id"]})

        disp_cols=["Player","#","GP","PTS","AST","REB","OREB","DREB","STL","BLK","TOV",
                   "FGM","FGA","FG%","3PM","3PA","3P%","FTM","FTA","FT%","eFG%","TS%","SC","MIN","GS"]
        df_pl=pd.DataFrame(stat_rows)
        st.subheader("Per Game Averages (Tracked Games)")
        if not df_pl.empty:
            st.dataframe(df_pl[disp_cols], use_container_width=True, hide_index=True)

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
                fgp=c["fgm"]/c["fga"] if c["fga"] else 0
                tpp=c["tpm"]/c["tpa"] if c["tpa"] else 0
                ftp=c["ftm"]/c["fta"] if c["fta"] else 0
                ts =c["pts"]/(2*(c["fga"]+0.44*c["fta"])) if (c["fga"]+0.44*c["fta"]) else 0
                shoot_cols[0].metric("FG%", f"{fgp*100:.1f}%")
                shoot_cols[1].metric("3P%", f"{tpp*100:.1f}%")
                shoot_cols[2].metric("FT%", f"{ftp*100:.1f}%")
                shoot_cols[3].metric("TS%", f"{ts*100:.1f}%")

                if c["shots"]:
                    render_hot_zones(c["shots"])

# ══════════════════════════════════════════════════════════════════════════════
#  GAMES
# ══════════════════════════════════════════════════════════════════════════════
with tab_gm:
    all_gs = games_for_team(team_id)
    if not all_gs:
        st.info("No games with scores yet.")
    else:
        log=[]
        for g in reversed(all_gs):
            res,my,opp=win_loss(g,team_id)
            log.append({"Date":g["date"],"Opponent":opponent_name(g,team_id),
                        "H/A":home_away(g,team_id),"Result":res,
                        "Tm":my,"Opp":opp,"Margin":my-opp,"Tracked":"✓" if g["tracked"] else ""})
        st.dataframe(pd.DataFrame(log), use_container_width=True, hide_index=True)

        # Scoring trend
        st.subheader("Scoring Trend")
        trend_df=pd.DataFrame(log)[["Date","Tm","Opp"]].set_index("Date")
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
                    lp=query("""
                        SELECT glp.team_id, p.id AS pid, p.name AS pname, t.name AS tname
                        FROM game_lineup_players glp
                        JOIN players p ON p.id=glp.player_id
                        JOIN teams t ON t.id=glp.team_id
                        WHERE glp.game_id=?
                    """, (g["id"],))
                    if not lp:
                        st.info("No lineup saved for this game.")
                        continue
                    # Compute box score inline
                    t1id=g["team1_id"]; t2id=g["team2_id"]
                    pt_map={r["pid"]:r["team_id"] for r in lp}
                    player_team_id={r["pid"]:r["team_id"] for r in lp}

                    def blank_p():
                        return dict(pts=0,ast=0,oreb=0,dreb=0,stl=0,blk=0,tov=0,
                                    fgm=0,fga=0,tpm=0,tpa=0,ftm=0,fta=0,sc=0,pf=0,poss_secs=0.0)
                    stats_g={r["pid"]:{**blank_p(),"name":r["pname"],"team_id":r["team_id"]} for r in lp}
                    events_g=query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (g["id"],))
                    total_poss_g=sum(ev["possession_secs"] or 0.0 for ev in events_g)
                    t1p=t2p=0
                    for ev in events_g:
                        prim=ev["primary_player_id"]
                        et=ev["event_type"]
                        if et=="shot":
                            sh=prim
                            if sh and sh in stats_g:
                                stats_g[sh]["fga"]+=1; stats_g[sh]["sc"]+=1
                                if ev["shot_type"]==3: stats_g[sh]["tpa"]+=1
                                if ev["shot_result"]=="make":
                                    pts_=ev["shot_type"]; stats_g[sh]["fgm"]+=1; stats_g[sh]["pts"]+=pts_
                                    if ev["shot_type"]==3: stats_g[sh]["tpm"]+=1
                                    if stats_g[sh]["team_id"]==t1id: t1p+=pts_
                                    else: t2p+=pts_
                                    if ev["pass_from_id"] and ev["pass_from_id"] in stats_g: stats_g[ev["pass_from_id"]]["ast"]+=1
                            for col,key in [("pass_from_id","sc"),("shot_created_by_id","sc"),("blocked_by_id","blk")]:
                                pid2=ev[col]
                                if pid2 and pid2 in stats_g: stats_g[pid2][key]+=1
                            reb=ev["rebound_by_id"]
                            if reb and reb in stats_g and prim and prim in stats_g:
                                k2="oreb" if player_team_id.get(prim)==player_team_id.get(reb) else "dreb"
                                stats_g[reb][k2]+=1
                        elif et=="free_throw":
                            sh=prim
                            if sh and sh in stats_g:
                                stats_g[sh]["fta"]+=1
                                if ev["shot_result"]=="make":
                                    stats_g[sh]["ftm"]+=1; stats_g[sh]["pts"]+=1
                                    if stats_g[sh]["team_id"]==t1id: t1p+=1
                                    else: t2p+=1
                            reb=ev["rebound_by_id"]
                            if reb and reb in stats_g and prim and prim in stats_g:
                                k2="oreb" if player_team_id.get(prim)==player_team_id.get(reb) else "dreb"
                                stats_g[reb][k2]+=1
                        elif et=="foul":
                            f2=ev["secondary_player_id"]
                            if f2 and f2 in stats_g: stats_g[f2]["pf"]+=1
                        elif et=="turnover":
                            if prim and prim in stats_g: stats_g[prim]["tov"]+=1
                            s2=ev["stolen_by_id"]
                            if s2 and s2 in stats_g: stats_g[s2]["stl"]+=1
                    pm=t1p-t2p
                    for pid2 in stats_g:
                        stats_g[pid2]["poss_secs"]=total_poss_g
                    box_rows=[]
                    for pid2,s in stats_g.items():
                        if s["team_id"]!=team_id: continue
                        reb=s["oreb"]+s["dreb"]
                        mins=round(s["poss_secs"]/60,1)
                        box_rows.append({"Player":s["name"],"PTS":s["pts"],"AST":s["ast"],
                                         "REB":reb,"STL":s["stl"],"BLK":s["blk"],"TOV":s["tov"],
                                         "FGM":s["fgm"],"FGA":s["fga"],"3PM":s["tpm"],"3PA":s["tpa"],
                                         "FTM":s["ftm"],"FTA":s["fta"],"SC":s["sc"],"MIN":mins})
                    if box_rows:
                        st.dataframe(pd.DataFrame(box_rows), use_container_width=True, hide_index=True)
                    else:
                        st.info("No player data.")

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
