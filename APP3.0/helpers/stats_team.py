import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
import streamlit as st
from Database.db import query
from helpers.game_utils import games_for_team, win_loss, record_from_games
from helpers.constants import SHOT_RATING, EST_FGP


@st.cache_data(ttl=3600, show_spinner=False)
def compute_player_game_log(player_id: int, team_id: int) -> list:
    """Returns one dict per tracked game for this player, newest first.
    Batches all DB queries upfront — 5 queries total regardless of game count."""
    rows = query("""
        SELECT glp.game_id, g.date, g.team1_id, g.team2_id,
               g.home_score, g.away_score,
               t1.name AS t1_name, t2.name AS t2_name
        FROM game_lineup_players glp
        JOIN games g  ON g.id  = glp.game_id
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE glp.player_id = ? AND g.tracked = 1
    """, (player_id,))
    if not rows:
        return []

    game_ids = [r["game_id"] for r in rows]
    ph = ",".join("?" * len(game_ids))

    # Bulk 1: all lineup player-team maps
    lp_rows = query(f"SELECT game_id, player_id, team_id FROM game_lineup_players WHERE game_id IN ({ph})", tuple(game_ids))
    pt_map_by_game: dict = {}
    for r in lp_rows:
        pt_map_by_game.setdefault(r["game_id"], {})[r["player_id"]] = r["team_id"]

    # Bulk 2: all events across all games
    ev_rows = query(f"SELECT * FROM game_events WHERE game_id IN ({ph}) ORDER BY game_id, id", tuple(game_ids))
    events_by_game: dict = {}
    for ev in ev_rows:
        events_by_game.setdefault(ev["game_id"], []).append(ev)

    # Bulk 3: minutes (possession secs) per game for this player
    mins_rows = query(f"""
        SELECT ge.game_id, SUM(ge.possession_secs) AS secs
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id = gel.event_id
        WHERE ge.game_id IN ({ph}) AND gel.player_id = ?
          AND ge.possession_secs > 0
        GROUP BY ge.game_id
    """, (*game_ids, player_id))
    mins_by_game = {r["game_id"]: (r["secs"] or 0.0) for r in mins_rows}

    # Bulk 4: plus_minus per game for this player
    pm_rows = query(f"SELECT game_id, plus_minus FROM game_lineup_players WHERE game_id IN ({ph}) AND player_id = ?", (*game_ids, player_id))
    pm_by_game = {r["game_id"]: r["plus_minus"] for r in pm_rows}

    log = []
    for row in rows:
        gid   = row["game_id"]
        t1id  = row["team1_id"]
        pt_map = pt_map_by_game.get(gid, {})
        events = events_by_game.get(gid, [])

        my_score  = row["home_score"] if t1id == team_id else row["away_score"]
        opp_score = row["away_score"] if t1id == team_id else row["home_score"]
        opp_name  = row["t2_name"]    if t1id == team_id else row["t1_name"]
        result    = "W" if (my_score or 0) > (opp_score or 0) else "L"

        s = dict(pts=0, ast=0, oreb=0, dreb=0, stl=0, blk=0, tov=0,
                 fgm=0, fga=0, tpm=0, tpa=0, ftm=0, fta=0, sc=0, pf=0, poss_used=0)
        team_sc = 0

        for ev in events:
            et  = ev["event_type"]
            pid = player_id

            if et == "shot":
                if pt_map.get(ev["primary_player_id"]) == team_id:
                    team_sc += 1
                if ev["pass_from_id"] and pt_map.get(ev["pass_from_id"]) == team_id:
                    team_sc += 1
                if ev["shot_created_by_id"] and pt_map.get(ev["shot_created_by_id"]) == team_id:
                    team_sc += 1
                if ev["primary_player_id"] == pid:
                    s["fga"] += 1; s["sc"] += 1; s["poss_used"] += 1
                    if ev["shot_type"] == 3: s["tpa"] += 1
                    if ev["shot_result"] == "make":
                        s["fgm"] += 1; s["pts"] += ev["shot_type"]
                        if ev["shot_type"] == 3: s["tpm"] += 1
                if ev["pass_from_id"] == pid:
                    s["sc"] += 1
                    if ev["shot_result"] == "make": s["ast"] += 1
                if ev["shot_created_by_id"] == pid: s["sc"] += 1
                if ev["blocked_by_id"] == pid: s["blk"] += 1
                if ev["rebound_by_id"] == pid:
                    sh_team = pt_map.get(ev["primary_player_id"])
                    if sh_team == team_id: s["oreb"] += 1
                    else:                  s["dreb"] += 1

            elif et == "free_throw":
                if ev["primary_player_id"] == pid:
                    s["fta"] += 1
                    if ev["shot_result"] == "make": s["ftm"] += 1; s["pts"] += 1
                if ev["rebound_by_id"] == pid:
                    sh_team = pt_map.get(ev["primary_player_id"])
                    if sh_team == team_id: s["oreb"] += 1
                    else:                  s["dreb"] += 1

            elif et == "turnover":
                if ev["primary_player_id"] == pid:
                    s["tov"] += 1; s["poss_used"] += 1
                if ev["stolen_by_id"] == pid: s["stl"] += 1

            elif et == "foul":
                if ev["secondary_player_id"] == pid: s["pf"] += 1

        mins   = round(mins_by_game.get(gid, 0.0) / 60, 1)
        pm     = pm_by_game.get(gid, 0)
        fgp    = f"{s['fgm']/s['fga']*100:.0f}%" if s["fga"] else "—"
        tpp    = f"{s['tpm']/s['tpa']*100:.0f}%" if s["tpa"] else "—"
        ftp    = f"{s['ftm']/s['fta']*100:.0f}%" if s["fta"] else "—"
        sc_pct = round(s["sc"] / team_sc * 100, 1) if team_sc else 0
        gs     = round(
            s["pts"] + 0.4*s["fgm"] - 0.7*s["fga"]
            - 0.4*(s["fta"] - s["ftm"])
            + 0.7*s["oreb"] + 0.3*s["dreb"]
            + s["stl"] + 0.7*s["ast"] + 0.7*s["blk"]
            - 0.4*s["pf"] - s["tov"], 1)

        log.append({
            "Date": row["date"], "Opp": opp_name, "W/L": result,
            "Score": f"{my_score}-{opp_score}",
            "PTS": s["pts"], "AST": s["ast"],
            "REB": s["oreb"] + s["dreb"], "OREB": s["oreb"], "DREB": s["dreb"],
            "STL": s["stl"], "BLK": s["blk"], "TOV": s["tov"],
            "FGM": s["fgm"], "FGA": s["fga"], "FG%": fgp,
            "3PM": s["tpm"], "3PA": s["tpa"], "3P%": tpp,
            "FTM": s["ftm"], "FTA": s["fta"], "FT%": ftp,
            "SC": s["sc"], "SC%": sc_pct, "Poss": s["poss_used"],
            "+/-": pm, "MIN": mins, "GS": gs,
        })

    return sorted(log, key=lambda r: pd.to_datetime(r["Date"], format="mixed", errors="coerce"), reverse=True)


@st.cache_data(ttl=3600, show_spinner=False)
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
    game_ids  = list(game_team.keys())
    ph        = ",".join("?" * len(game_ids))

    # Bulk 1: all lineup player-team maps across all games
    lp_rows = query(
        f"SELECT game_id, player_id, team_id FROM game_lineup_players WHERE game_id IN ({ph})",
        tuple(game_ids),
    )
    pt_map_by_game: dict = {}
    for r in lp_rows:
        pt_map_by_game.setdefault(r["game_id"], {})[r["player_id"]] = r["team_id"]

    # Bulk 2: all events across all games
    ev_rows = query(
        f"SELECT * FROM game_events WHERE game_id IN ({ph}) ORDER BY game_id, id",
        tuple(game_ids),
    )
    events_by_game: dict = {}
    for ev in ev_rows:
        events_by_game.setdefault(ev["game_id"], []).append(ev)

    # Bulk 3: minutes (possession secs on-court) per game for this player
    mins_rows = query(f"""
        SELECT ge.game_id, SUM(ge.possession_secs) AS secs
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id = gel.event_id
        WHERE ge.game_id IN ({ph}) AND gel.player_id = ?
          AND ge.possession_secs > 0
        GROUP BY ge.game_id
    """, (*game_ids, player_id))
    mins_by_game = {r["game_id"]: (r["secs"] or 0.0) for r in mins_rows}

    # Bulk 4: all event IDs where this player was on court (for on-court shot tracking)
    gel_bulk = query(f"""
        SELECT gel.event_id
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id = gel.event_id
        WHERE ge.game_id IN ({ph}) AND gel.player_id = ?
    """, (*game_ids, player_id))
    on_court_event_ids = {r["event_id"] for r in gel_bulk}

    tot = dict(gp=len(rows), pts=0, ast=0, oreb=0, dreb=0, stl=0, blk=0, tov=0,
               fgm=0, fga=0, tpm=0, tpa=0, ftm=0, fta=0, sc=0, pf=0,
               poss_secs=0.0, poss_used=0, plus_minus=0,
               shots=[],
               # Shot quality (offensive)
               shot_rating=0.0, est_fg_sum=0.0, est_fg_shots=0,
               # Defensive
               def_fga=0, def_fgm=0, def_3pa=0, def_3pm=0,
               on_court_opp_shots=0, def_shots=[])

    for game_id, my_team in game_team.items():
        pt_map = pt_map_by_game.get(game_id, {})
        events = events_by_game.get(game_id, [])
        tot["poss_secs"] += mins_by_game.get(game_id, 0.0)

        for ev in events:
            pid = player_id
            et  = ev["event_type"]

            if et == "shot":
                if ev["primary_player_id"] == pid:
                    tot["fga"] += 1; tot["sc"] += 1; tot["poss_used"] += 1
                    if ev["shot_type"] == 3: tot["tpa"] += 1
                    if ev["shot_result"] == "make":
                        tot["fgm"] += 1; tot["pts"] += ev["shot_type"]
                        if ev["shot_type"] == 3: tot["tpm"] += 1
                    if ev["zone"]:
                        tot["shots"].append({"zone": ev["zone"], "shot_type": ev["shot_type"], "shot_result": ev["shot_result"]})
                    # Shot quality — only when zone logged
                    if ev["zone"] and ev["shot_type"]:
                        _con = bool(ev["guarded_by_id"])
                        _key = (ev["shot_type"], ev["zone"], _con)

                        # Creation-context modifier:
                        # pass_from + shot_created_by → designed play, major boost
                        # pass_from only → assisted / catch-and-shoot boost
                        # shot_created_by only → screen/drive created the look
                        # neither → fully self-created, harder shot, small penalty
                        _has_pass    = bool(ev["pass_from_id"])
                        _has_created = bool(ev["shot_created_by_id"])
                        if _has_pass and _has_created:
                            _r_mod, _e_mod = +0.30, +0.07   # both: designed play
                        elif _has_pass:
                            _r_mod, _e_mod = +0.15, +0.04   # assisted shot
                        elif _has_created:
                            _r_mod, _e_mod = +0.08, +0.02   # creation w/o explicit pass
                        else:
                            _r_mod, _e_mod = -0.10, -0.02   # self-created

                        tot["shot_rating"] += SHOT_RATING.get(_key, 0.0) + _r_mod
                        _efg = EST_FGP.get(_key)
                        if _efg is not None:
                            tot["est_fg_sum"]   += max(0.0, min(1.0, _efg + _e_mod))
                            tot["est_fg_shots"] += 1
                if ev["pass_from_id"] == pid:
                    tot["sc"] += 1
                    if ev["shot_result"] == "make": tot["ast"] += 1
                if ev["shot_created_by_id"] == pid: tot["sc"] += 1
                if ev["blocked_by_id"] == pid: tot["blk"] += 1
                if ev["rebound_by_id"] == pid:
                    sh_team = pt_map.get(ev["primary_player_id"])
                    if sh_team == my_team: tot["oreb"] += 1
                    else:                  tot["dreb"] += 1
                # Defensive: this player was the listed defender
                if ev["guarded_by_id"] == pid:
                    tot["def_fga"] += 1
                    if ev["shot_result"] == "make": tot["def_fgm"] += 1
                    if ev["shot_type"] == 3:
                        tot["def_3pa"] += 1
                        if ev["shot_result"] == "make": tot["def_3pm"] += 1
                    if ev["zone"] and ev["shot_type"]:
                        tot["def_shots"].append({"zone": ev["zone"], "shot_type": ev["shot_type"], "shot_result": ev["shot_result"]})
                # On-court opponent shots (denominator for contested-shot%)
                if ev["id"] in on_court_event_ids and pt_map.get(ev["primary_player_id"]) != my_team:
                    tot["on_court_opp_shots"] += 1

            elif et == "free_throw":
                if ev["primary_player_id"] == pid:
                    tot["fta"] += 1
                    if ev["shot_result"] == "make": tot["ftm"] += 1; tot["pts"] += 1
                if ev["rebound_by_id"] == pid:
                    sh_team = pt_map.get(ev["primary_player_id"])
                    if sh_team == my_team: tot["oreb"] += 1
                    else:                  tot["dreb"] += 1

            elif et == "foul":
                if ev["secondary_player_id"] == pid: tot["pf"] += 1

            elif et == "turnover":
                if ev["primary_player_id"] == pid:
                    tot["tov"] += 1; tot["poss_used"] += 1
                if ev["stolen_by_id"] == pid: tot["stl"] += 1

    # Career +/- — single aggregate query (already fast)
    pm_row = query("""
        SELECT SUM(glp.plus_minus) AS total_pm
        FROM game_lineup_players glp
        JOIN games g ON g.id = glp.game_id
        WHERE glp.player_id = ? AND g.tracked = 1
    """, (player_id,))
    tot["plus_minus"] = (pm_row[0]["total_pm"] or 0) if pm_row else 0

    return tot


@st.cache_data(ttl=3600, show_spinner=False)
def compute_team_tracked(tid):
    tracked = games_for_team(tid, tracked_only=True)
    if not tracked:
        return None

    agg=dict(fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,oreb=0,dreb=0,
             tov=0,stl=0,blk=0,ast=0,poss_secs=0.0,pts=0,sc=0,
             poss_count=0,real_poss_secs=0.0,
             ast_fgm=0,paint_fga=0,paint_fgm=0,
             q1_pts=0,q2_pts=0,q3_pts=0,q4_pts=0,
             q1_poss=0,q2_poss=0,q3_poss=0,q4_poss=0,
             opp_fga=0,opp_fgm=0,opp_tpa=0,opp_tpm=0,opp_fta=0,opp_ftm=0,
             opp_oreb=0,opp_dreb=0,opp_tov=0,opp_pts=0,
             opp_q1_pts=0,opp_q2_pts=0,opp_q3_pts=0,opp_q4_pts=0,
             opp_q1_poss=0,opp_q2_poss=0,opp_q3_poss=0,opp_q4_poss=0)
    game_log = []

    # ── Batch-load all lineup + event data upfront (eliminates N+1 queries) ──
    game_ids = [g["id"] for g in tracked]
    _ph = ",".join("?" * len(game_ids))
    _lp_rows = query(
        f"SELECT game_id, player_id, team_id FROM game_lineup_players WHERE game_id IN ({_ph})",
        tuple(game_ids))
    _pt_by_game: dict = {}
    for _r in _lp_rows:
        _pt_by_game.setdefault(_r["game_id"], {})[_r["player_id"]] = _r["team_id"]

    _ev_rows = query(
        f"SELECT * FROM game_events WHERE game_id IN ({_ph}) ORDER BY game_id, id",
        tuple(game_ids))
    _events_by_game: dict = {}
    for _ev in _ev_rows:
        _events_by_game.setdefault(_ev["game_id"], []).append(_ev)

    for g in tracked:
        pt = _pt_by_game.get(g["id"], {})
        if not pt:
            continue
        events = _events_by_game.get(g["id"], [])

        my_s  = dict(fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,oreb=0,dreb=0,tov=0,stl=0,blk=0,ast=0,poss_secs=0.0,pts=0,sc=0,
                     poss_count=0,real_poss_secs=0.0,
                     ast_fgm=0,paint_fga=0,paint_fgm=0,
                     q1_pts=0,q2_pts=0,q3_pts=0,q4_pts=0,
                     q1_poss=0,q2_poss=0,q3_poss=0,q4_poss=0)
        opp_s = dict(fga=0,fgm=0,tpa=0,tpm=0,fta=0,ftm=0,oreb=0,dreb=0,tov=0,pts=0,
                     q1_pts=0,q2_pts=0,q3_pts=0,q4_pts=0,
                     q1_poss=0,q2_poss=0,q3_poss=0,q4_poss=0)

        for ev in events:
            prim=ev["primary_player_id"]
            ptm =pt.get(prim)
            psec=ev["possession_secs"] or 0.0
            is_mine = ptm==tid

            _ev_quarter = ev["quarter"]
            if is_mine:
                my_s["poss_secs"] += psec
                # Count possession (exclude free throws, fouls, and 0-sec events)
                if ev["event_type"] not in ("free_throw", "foul") and psec > 0:
                    my_s["poss_count"]    += 1
                    my_s["real_poss_secs"] += psec
                # Per-quarter possession count: shots + turnovers, no psec requirement
                # (psec may be null on events where quarter IS populated)
                if ev["event_type"] in ("shot", "turnover") and _ev_quarter in (1, 2, 3, 4):
                    my_s[f"q{_ev_quarter}_poss"] += 1
            elif ptm is not None and ev["event_type"] in ("shot", "turnover") and _ev_quarter in (1, 2, 3, 4):
                # Track opponent per-quarter possessions (same shot/turnover approach)
                opp_s[f"q{_ev_quarter}_poss"] += 1

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
                # Paint proxy (zone C, 2PT) — our team only
                if ptm==tid and ev.get("zone")=="C" and ev["shot_type"]==2:
                    my_s["paint_fga"]+=1
                    if ev["shot_result"]=="make": my_s["paint_fgm"]+=1
                # Assisted FGM — made shot with a passer on our team
                if ev["shot_result"]=="make" and ptm==tid:
                    _pf=ev["pass_from_id"]
                    if _pf and pt.get(_pf)==tid: my_s["ast_fgm"]+=1
                # Quarter points from shots (Q1-Q4)
                if ev["shot_result"]=="make" and ptm and ev["quarter"] in (1,2,3,4):
                    _qk = f"q{ev['quarter']}_pts"
                    if ptm==tid: my_s[_qk]+=ev["shot_type"]
                    else:        opp_s[_qk]+=ev["shot_type"]
                # SC: shooter
                if ptm==tid: my_s["sc"]+=1
                # SC: passer
                pf2=ev["pass_from_id"]
                if pf2 and pt.get(pf2)==tid: my_s["sc"]+=1
                # SC: shot creator
                scb=ev["shot_created_by_id"]
                if scb and pt.get(scb)==tid: my_s["sc"]+=1
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
                    if ev["shot_result"]=="make":
                        bucket["ftm"]+=1; bucket["pts"]+=1
                        # Quarter FT points (Q1-Q4)
                        if ev["quarter"] in (1,2,3,4):
                            _qk = f"q{ev['quarter']}_pts"
                            if ptm==tid: my_s[_qk]+=1
                            else:        opp_s[_qk]+=1
            elif et=="turnover":
                if ptm:
                    (my_s if ptm==tid else opp_s)["tov"]+=1
                stl=ev["stolen_by_id"]
                if stl and pt.get(stl)==tid: my_s["stl"]=my_s.get("stl",0)+1

        # Per-game entry for trend chart
        _gp = max(0.1, my_s["fga"]-my_s["oreb"]+my_s["tov"]+0.44*my_s["fta"])
        _go = max(0.1, opp_s["fga"]-opp_s["oreb"]+opp_s["tov"]+0.44*opp_s["fta"])
        _t1 = g["team1_id"]
        _ms = (g["home_score"] if _t1==tid else g["away_score"]) or 0
        _os = (g["away_score"] if _t1==tid else g["home_score"]) or 0
        game_log.append({"date": g["date"],
                         "opp":  g["t2_name"] if _t1==tid else g["t1_name"],
                         "ortg": round(100*my_s["pts"]/_gp, 1),
                         "drtg": round(100*opp_s["pts"]/_go, 1),
                         "margin": _ms - _os})
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

    team_sce_denom = (agg["fga"] - agg["tpa"]) * 2 + agg["tpa"] * 3
    team_sce = agg["pts"] / team_sce_denom if team_sce_denom else 0

    pc   = agg["poss_count"]
    rps  = agg["real_poss_secs"]
    ppp  = agg["pts"] / pc if pc else 0
    avg_poss_secs = rps / pc if pc else 0
    poss_pg = pc / gp if gp else 0

    def _fmt_secs(s):
        m, sec = divmod(int(s), 60)
        return f"{m}:{sec:02d}"

    # ── New derived stats ────────────────────────────────────────────────────
    two_pa       = agg["fga"]  - agg["tpa"]
    two_pm       = agg["fgm"]  - agg["tpm"]
    two_pct      = two_pm/two_pa              if two_pa              else 0.0
    ast_pct      = agg["ast_fgm"]/agg["fgm"]*100 if agg["fgm"]     else 0.0
    unast_pct    = 100.0 - ast_pct
    paint_fg_p   = agg["paint_fgm"]/agg["paint_fga"] if agg["paint_fga"] else 0.0
    paint_pts_pg = agg["paint_fgm"]*2/gp              if gp               else 0.0
    opp_2pa      = agg["opp_fga"] - agg["opp_tpa"]
    blk_rate     = agg["blk"]/opp_2pa*100             if opp_2pa          else 0.0
    stl_rate     = agg["stl"]/op_pos*100
    ast_tov_r    = agg["ast"]/agg["tov"]              if agg["tov"]       else 0.0
    _otov_denom  = agg["opp_fga"]+0.44*agg["opp_fta"]+agg["opp_tov"]
    opp_tov_r    = agg["opp_tov"]/_otov_denom         if _otov_denom      else 0.0
    opp_ft_r2    = agg["opp_fta"]/agg["opp_fga"]      if agg["opp_fga"]   else 0.0
    dreb_p       = agg["dreb"]/(agg["dreb"]+agg["opp_oreb"]) if (agg["dreb"]+agg["opp_oreb"]) else 0.0
    opp_oreb_p   = agg["opp_oreb"]/(agg["opp_oreb"]+agg["dreb"]) if (agg["opp_oreb"]+agg["dreb"]) else 0.0
    q1_pts_pg    = agg["q1_pts"]/gp      if gp else 0.0
    q2_pts_pg    = agg["q2_pts"]/gp      if gp else 0.0
    q3_pts_pg    = agg["q3_pts"]/gp      if gp else 0.0
    q4_pts_pg    = agg["q4_pts"]/gp      if gp else 0.0
    opp_q1_pts_pg= agg["opp_q1_pts"]/gp  if gp else 0.0
    opp_q2_pts_pg= agg["opp_q2_pts"]/gp  if gp else 0.0
    opp_q3_pts_pg= agg["opp_q3_pts"]/gp  if gp else 0.0
    opp_q4_pts_pg= agg["opp_q4_pts"]/gp  if gp else 0.0
    h1_pts_pg    = q1_pts_pg + q2_pts_pg
    h2_pts_pg    = q3_pts_pg + q4_pts_pg
    opp_h1_pts_pg= opp_q1_pts_pg + opp_q2_pts_pg
    opp_h2_pts_pg= opp_q3_pts_pg + opp_q4_pts_pg
    # Per-quarter PPP (our offense, opponent offense)
    q1_ppp  = agg["q1_pts"]/agg["q1_poss"]         if agg["q1_poss"]                               else 0.0
    q2_ppp  = agg["q2_pts"]/agg["q2_poss"]         if agg["q2_poss"]                               else 0.0
    q3_ppp  = agg["q3_pts"]/agg["q3_poss"]         if agg["q3_poss"]                               else 0.0
    q4_ppp  = agg["q4_pts"]/agg["q4_poss"]         if agg["q4_poss"]                               else 0.0
    h1_poss = agg["q1_poss"]+agg["q2_poss"]
    h2_poss = agg["q3_poss"]+agg["q4_poss"]
    h1_ppp  = (agg["q1_pts"]+agg["q2_pts"])/h1_poss if h1_poss                                     else 0.0
    h2_ppp  = (agg["q3_pts"]+agg["q4_pts"])/h2_poss if h2_poss                                     else 0.0
    opp_q1_ppp  = agg["opp_q1_pts"]/agg["opp_q1_poss"] if agg["opp_q1_poss"]                       else 0.0
    opp_q2_ppp  = agg["opp_q2_pts"]/agg["opp_q2_poss"] if agg["opp_q2_poss"]                       else 0.0
    opp_q3_ppp  = agg["opp_q3_pts"]/agg["opp_q3_poss"] if agg["opp_q3_poss"]                       else 0.0
    opp_q4_ppp  = agg["opp_q4_pts"]/agg["opp_q4_poss"] if agg["opp_q4_poss"]                       else 0.0
    opp_h1_poss = agg["opp_q1_poss"]+agg["opp_q2_poss"]
    opp_h2_poss = agg["opp_q3_poss"]+agg["opp_q4_poss"]
    opp_h1_ppp  = (agg["opp_q1_pts"]+agg["opp_q2_pts"])/opp_h1_poss if opp_h1_poss               else 0.0
    opp_h2_ppp  = (agg["opp_q3_pts"]+agg["opp_q4_pts"])/opp_h2_poss if opp_h2_poss               else 0.0
    _tot_pts     = agg["pts"]
    pct_from_2   = two_pm*2/_tot_pts*100  if _tot_pts else 0.0
    pct_from_3   = agg["tpm"]*3/_tot_pts*100 if _tot_pts else 0.0
    pct_from_ft  = agg["ftm"]/_tot_pts*100   if _tot_pts else 0.0

    return dict(gp=gp,poss=poss,op_pos=op_pos,ortg=ortg,drtg=drtg,net=ortg-drtg,pace=pace,
                efg=efg,oefg=oefg,ts=ts_,tov_r=tov_r,oreb_p=oreb_p,ft_r=ft_r,tpar=tpar,
                fgp=fgp,tpp=tpp,ftp=ftp,two_pct=two_pct,
                ast_pg=agg["ast"]/gp,stl_pg=agg.get("stl",0)/gp,blk_pg=agg.get("blk",0)/gp,
                tov_pg=agg["tov"]/gp,oreb_pg=agg["oreb"]/gp,dreb_pg=agg["dreb"]/gp,
                pts_pg=agg["pts"]/gp,sc_pg=agg["sc"]/gp,team_sce=team_sce,
                poss_pg=poss_pg,ppp=ppp,
                poss_time_total=_fmt_secs(rps),
                avg_poss_len=_fmt_secs(avg_poss_secs),
                ast_pct=ast_pct, unast_pct=unast_pct,
                paint_fg_p=paint_fg_p, paint_pts_pg=paint_pts_pg,
                blk_rate=blk_rate, stl_rate=stl_rate, ast_tov_r=ast_tov_r,
                opp_tov_r=opp_tov_r, opp_ft_r=opp_ft_r2, dreb_p=dreb_p, opp_oreb_p=opp_oreb_p,
                q1_pts_pg=q1_pts_pg, q2_pts_pg=q2_pts_pg, q3_pts_pg=q3_pts_pg, q4_pts_pg=q4_pts_pg,
                opp_q1_pts_pg=opp_q1_pts_pg, opp_q2_pts_pg=opp_q2_pts_pg,
                opp_q3_pts_pg=opp_q3_pts_pg, opp_q4_pts_pg=opp_q4_pts_pg,
                h1_pts_pg=h1_pts_pg, h2_pts_pg=h2_pts_pg,
                opp_h1_pts_pg=opp_h1_pts_pg, opp_h2_pts_pg=opp_h2_pts_pg,
                q1_ppp=q1_ppp, q2_ppp=q2_ppp, q3_ppp=q3_ppp, q4_ppp=q4_ppp,
                h1_ppp=h1_ppp, h2_ppp=h2_ppp,
                opp_q1_ppp=opp_q1_ppp, opp_q2_ppp=opp_q2_ppp,
                opp_q3_ppp=opp_q3_ppp, opp_q4_ppp=opp_q4_ppp,
                opp_h1_ppp=opp_h1_ppp, opp_h2_ppp=opp_h2_ppp,
                pct_from_2=pct_from_2, pct_from_3=pct_from_3, pct_from_ft=pct_from_ft,
                game_log=game_log,
                **agg)


@st.cache_data(ttl=3600, show_spinner=False)
def compute_on_off(team_id):
    """
    For each player on team_id, computes on-court vs off-court statistics
    using game_event_lineup snapshots across all tracked games.
    Returns dict: player_id -> {
        on_poss, off_poss,
        on_pts_for, on_pts_against,
        off_pts_for, off_pts_against,
        poss_used,   # shots + turnovers as primary player
    }
    Derived metrics (computed by caller):
        ORtg_on  = on_pts_for  / on_poss * 100
        DRtg_on  = on_pts_against / on_poss * 100
        Net_on   = ORtg_on - DRtg_on
        (same for _off)
        On/Off   = Net_on - Net_off
        Usg%     = poss_used / on_poss * 100
    Batches all DB queries — 4 queries total regardless of game count.
    """
    roster = query("SELECT id FROM players WHERE team_id=? AND archived=0", (team_id,))
    if not roster:
        return {}
    pids = {r["id"] for r in roster}

    result = {pid: dict(
        on_poss=0, off_poss=0,
        on_pts_for=0, on_pts_against=0,
        off_pts_for=0, off_pts_against=0,
        poss_used=0,
    ) for pid in pids}

    tracked = games_for_team(team_id, tracked_only=True)
    if not tracked:
        return result

    game_ids = [g["id"] for g in tracked]
    ph = ",".join("?" * len(game_ids))

    # Bulk 1: all lineup player-team maps
    lp_rows = query(
        f"SELECT game_id, player_id, team_id FROM game_lineup_players WHERE game_id IN ({ph})",
        tuple(game_ids),
    )
    pt_by_game: dict = {}
    for r in lp_rows:
        pt_by_game.setdefault(r["game_id"], {})[r["player_id"]] = r["team_id"]

    # Bulk 2: all lineup snapshots (event_id → set of player_ids)
    gel_rows = query(f"""
        SELECT gel.event_id, gel.player_id, ge.game_id
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id = gel.event_id
        WHERE ge.game_id IN ({ph})
    """, tuple(game_ids))
    gel_by_game: dict = {}
    for r in gel_rows:
        snap = gel_by_game.setdefault(r["game_id"], {})
        snap.setdefault(r["event_id"], set()).add(r["player_id"])

    # Bulk 3: all events
    ev_rows = query(
        f"SELECT * FROM game_events WHERE game_id IN ({ph}) ORDER BY game_id, id",
        tuple(game_ids),
    )
    events_by_game: dict = {}
    for ev in ev_rows:
        events_by_game.setdefault(ev["game_id"], []).append(ev)

    for gid in game_ids:
        pt = pt_by_game.get(gid, {})
        ev_lineup = gel_by_game.get(gid)
        if not ev_lineup:
            continue  # no lineup snapshots — skip game
        events = events_by_game.get(gid, [])

        for ev in events:
            prim  = ev["primary_player_id"]
            ptm   = pt.get(prim)
            et    = ev["event_type"]
            on_ct = ev_lineup.get(ev["id"], set())
            if not on_ct:
                continue

            # Points this event
            pts = 0; scoring_team = None
            if et == "shot" and ev["shot_result"] == "make":
                pts = ev["shot_type"] or 0; scoring_team = ptm
            elif et == "free_throw" and ev["shot_result"] == "make":
                pts = 1; scoring_team = ptm

            # Track team possessions (shot or turnover) for on/off split
            if et in ("shot", "turnover") and ptm == team_id:
                for pid in pids:
                    if pid in on_ct:
                        result[pid]["on_poss"] += 1
                    else:
                        result[pid]["off_poss"] += 1

            # Player's own possessions used (they are the primary player)
            if et in ("shot", "turnover") and prim in pids:
                result[prim]["poss_used"] += 1

            # Distribute points to on/off buckets for every roster player
            if pts > 0 and scoring_team is not None:
                for pid in pids:
                    is_on = pid in on_ct
                    if scoring_team == team_id:
                        if is_on: result[pid]["on_pts_for"]     += pts
                        else:      result[pid]["off_pts_for"]    += pts
                    else:
                        if is_on: result[pid]["on_pts_against"]  += pts
                        else:      result[pid]["off_pts_against"] += pts

    return result


@st.cache_data(ttl=3600, show_spinner=False)
def compute_league_drtg() -> float:
    """Average defensive rating across all teams that have tracked game data.
    Zero DB queries on cache hit; at most N dict-lookups into cached compute_team_tracked."""
    teams = query("SELECT id FROM teams")
    vals = []
    for t in teams:
        adv = compute_team_tracked(t["id"])
        if adv:
            vals.append(adv["drtg"])
    return float(np.mean(vals)) if vals else 100.0


@st.cache_data(ttl=3600, show_spinner=False)
def compute_league_four_factors() -> dict:
    """Mean of each Four Factor across all teams with tracked game data."""
    teams = query("SELECT id FROM teams")
    buckets: dict = {k: [] for k in
                     ["efg","tov_r","oreb_p","ft_r","oefg","opp_tov_r","dreb_p","opp_ft_r"]}
    for t in teams:
        adv = compute_team_tracked(t["id"])
        if not adv: continue
        buckets["efg"].append(adv["efg"])
        buckets["tov_r"].append(adv["tov_r"])
        buckets["oreb_p"].append(adv["oreb_p"])
        buckets["ft_r"].append(adv["ft_r"])
        buckets["oefg"].append(adv["oefg"])
        buckets["opp_tov_r"].append(adv.get("opp_tov_r", 0))
        buckets["dreb_p"].append(adv.get("dreb_p", 0))
        buckets["opp_ft_r"].append(adv.get("opp_ft_r", 0))
    return {k: float(np.mean(v)) if v else 0.0 for k, v in buckets.items()}


@st.cache_data(ttl=3600, show_spinner=False)
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
        # League avg DRtg for calibration — cached, zero DB queries on warm hit
        league_drtg = compute_league_drtg()

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
    h2h_raw = query("""
        SELECT home_score,away_score,date,team1_id
        FROM games
        WHERE ((team1_id=? AND team2_id=?) OR (team1_id=? AND team2_id=?))
          AND home_score IS NOT NULL AND away_score IS NOT NULL
    """, (a_id, b_id, b_id, a_id))
    h2h = sorted(h2h_raw, key=lambda g: pd.to_datetime(g["date"], format="mixed", errors="coerce"), reverse=True)

    return dict(proj_a=proj_a, proj_b=proj_b, prob_a=prob_a,
                method=method, h2h=h2h,
                adv_a=adv_a, adv_b=adv_b,
                ppg_a=ppg_a, papg_a=papg_a, ppg_b=ppg_b, papg_b=papg_b,
                wa=wa, la=la, wb=wb, lb=lb)
