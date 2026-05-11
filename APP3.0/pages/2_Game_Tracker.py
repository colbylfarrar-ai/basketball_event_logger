import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from Database.db import query, execute, initialize_database

initialize_database()

st.title("Game Tracker")

ZONES = ["LC", "LW", "C", "RW", "RC"]

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def time_to_secs(t: str) -> float:
    try:
        m, s = t.strip().split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return 0.0

def load_lineup(game_id: int) -> dict:
    game = query("""
        SELECT g.id, g.team1_id, g.team2_id, t1.name AS t1_name, t2.name AS t2_name
        FROM games g JOIN teams t1 ON t1.id=g.team1_id JOIN teams t2 ON t2.id=g.team2_id
        WHERE g.id=?
    """, (game_id,))[0]
    players = query("""
        SELECT glp.team_id, p.id AS pid, p.name AS pname, t.name AS tname
        FROM game_lineup_players glp
        JOIN players p ON p.id=glp.player_id JOIN teams t ON t.id=glp.team_id
        WHERE glp.game_id=? ORDER BY glp.team_id, p.name
    """, (game_id,))
    officials = query("""
        SELECT o.id AS oid, o.name AS oname
        FROM game_lineup_officials glo JOIN officials o ON o.id=glo.official_id
        WHERE glo.game_id=?
    """, (game_id,))
    return {"game": game, "players": players, "officials": officials}

def plookup(label: str, id_map: dict):
    return id_map.get(label) if label and label != "—" else None

# ══════════════════════════════════════════════════════════════════════════════
#  STAT COMPUTATIONS
# ══════════════════════════════════════════════════════════════════════════════

def compute_box(game_id: int, game_info: dict):
    t1id = game_info["team1_id"]
    t2id = game_info["team2_id"]
    events = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id", (game_id,))

    def blank():
        return {"pts":0,"ast":0,"oreb":0,"dreb":0,"stl":0,"blk":0,"tov":0,
                "fgm":0,"fga":0,"tpm":0,"tpa":0,"ftm":0,"fta":0,"sc":0,"pf":0}

    # All players on both rosters always appear
    all_players = query(
        "SELECT id AS pid, name AS pname, team_id FROM players "
        "WHERE team_id IN (?,?) AND archived=0 ORDER BY name",
        (t1id, t2id)
    )
    stats = {p["pid"]: {**blank(), "name": p["pname"], "team_id": p["team_id"]}
             for p in all_players}
    player_team = {pid: s["team_id"] for pid, s in stats.items()}

    # Minutes: sum possession_secs for events where each player was in the lineup snapshot
    mins_rows = query("""
        SELECT gel.player_id, SUM(ge.possession_secs) AS secs
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id = gel.event_id
        WHERE ge.game_id = ?
        GROUP BY gel.player_id
    """, (game_id,))
    player_mins = {r["player_id"]: r["secs"] or 0.0 for r in mins_rows}

    # +/- stored directly per player from event-time snapshots
    pm_rows = query("SELECT player_id, plus_minus FROM game_lineup_players WHERE game_id=?", (game_id,))
    stored_pm = {r["player_id"]: r["plus_minus"] for r in pm_rows}

    t1_pts = t2_pts = 0

    for ev in events:
        etype = ev["event_type"]
        prim  = ev["primary_player_id"]

        if etype == "shot":
            sh = prim
            if sh and sh in stats:
                stats[sh]["fga"] += 1
                stats[sh]["sc"]  += 1
                if ev["shot_type"] == 3: stats[sh]["tpa"] += 1
                if ev["shot_result"] == "make":
                    pts = ev["shot_type"]
                    stats[sh]["fgm"] += 1
                    stats[sh]["pts"] += pts
                    if ev["shot_type"] == 3: stats[sh]["tpm"] += 1
                    if stats[sh]["team_id"] == t1id: t1_pts += pts
                    else: t2_pts += pts
                    if ev["pass_from_id"] and ev["pass_from_id"] in stats:
                        stats[ev["pass_from_id"]]["ast"] += 1
            for col, key in [("pass_from_id","sc"),("shot_created_by_id","sc"),("blocked_by_id","blk")]:
                pid = ev[col]
                if pid and pid in stats: stats[pid][key] += 1
            reb = ev["rebound_by_id"]
            if reb and reb in stats and sh and sh in stats:
                stats[reb]["oreb" if player_team.get(sh)==player_team.get(reb) else "dreb"] += 1

        elif etype == "free_throw":
            sh = prim
            if sh and sh in stats:
                stats[sh]["fta"] += 1
                if ev["shot_result"] == "make":
                    stats[sh]["ftm"] += 1; stats[sh]["pts"] += 1
                    if stats[sh]["team_id"] == t1id: t1_pts += 1
                    else: t2_pts += 1
            reb = ev["rebound_by_id"]
            if reb and reb in stats and sh and sh in stats:
                stats[reb]["oreb" if player_team.get(sh)==player_team.get(reb) else "dreb"] += 1

        elif etype == "foul":
            f = ev["secondary_player_id"]
            if f and f in stats: stats[f]["pf"] += 1

        elif etype == "turnover":
            if prim and prim in stats: stats[prim]["tov"] += 1
            s = ev["stolen_by_id"]
            if s and s in stats: stats[s]["stl"] += 1

    rows = []
    for pid, s in stats.items():
        reb  = s["oreb"] + s["dreb"]
        mins = round(player_mins.get(pid, 0.0) / 60, 1)
        plus = stored_pm.get(pid, 0)
        gs   = round(s["pts"]+0.4*s["fgm"]-0.7*s["fga"]-0.4*(s["fta"]-s["ftm"])
                     +0.7*s["oreb"]+0.3*s["dreb"]+s["stl"]+0.7*s["ast"]+0.7*s["blk"]
                     -0.4*s["pf"]-s["tov"], 1)
        rows.append({"_tid": s["team_id"], "Player": s["name"],
                     "PTS":s["pts"],"AST":s["ast"],"OREB":s["oreb"],"DREB":s["dreb"],"REB":reb,
                     "STL":s["stl"],"BLK":s["blk"],"TOV":s["tov"],
                     "FGM":s["fgm"],"FGA":s["fga"],"3PM":s["tpm"],"3PA":s["tpa"],
                     "FTM":s["ftm"],"FTA":s["fta"],"SC":s["sc"],"+/-":plus,"MIN":mins,"GS":gs})
    return rows, t1_pts, t2_pts

def compute_off_box(game_id: int, game: dict):
    pt   = {r["player_id"]: r["team_id"] for r in query("SELECT player_id,team_id FROM game_lineup_players WHERE game_id=?", (game_id,))}
    offs = query("SELECT o.id AS oid, o.name AS oname FROM game_lineup_officials glo JOIN officials o ON o.id=glo.official_id WHERE glo.game_id=?", (game_id,))
    fouls= query("SELECT official_id, secondary_player_id FROM game_events WHERE game_id=? AND event_type='foul'", (game_id,))
    t1id = game["team1_id"]
    stats = {o["oid"]: {"name":o["oname"],"t1":0,"t2":0} for o in offs}
    for f in fouls:
        oid, fp = f["official_id"], f["secondary_player_id"]
        if oid in stats and fp in pt:
            if pt[fp]==t1id: stats[oid]["t1"]+=1
            else: stats[oid]["t2"]+=1
    return [{"Official":s["name"],"T1 Calls":s["t1"],"T2 Calls":s["t2"],"Total":s["t1"]+s["t2"]} for s in stats.values()]

# ══════════════════════════════════════════════════════════════════════════════
#  GAME SELECTOR
# ══════════════════════════════════════════════════════════════════════════════

all_games = query("""
    SELECT g.id, t1.name AS t1, t2.name AS t2, g.date
    FROM games g JOIN teams t1 ON t1.id=g.team1_id JOIN teams t2 ON t2.id=g.team2_id
    ORDER BY g.date DESC
""")
if not all_games:
    st.warning("No games found. Add games in the Input Hub first.")
    st.stop()

game_labels = {f"{g['t1']} vs {g['t2']}  |  {g['date']}": g["id"] for g in all_games}
sel_label   = st.selectbox("Select Game", list(game_labels.keys()))
game_id     = game_labels[sel_label]
lineup      = load_lineup(game_id)
game_info   = lineup["game"]
t1id, t2id  = game_info["team1_id"], game_info["team2_id"]
t1name, t2name = game_info["t1_name"], game_info["t2_name"]

is_tracked = bool(query("SELECT tracked FROM games WHERE id=?", (game_id,))[0]["tracked"])

gc1, gc2 = st.columns([4, 1])
if is_tracked:
    gc2.success("✓ Game Final")
else:
    if gc2.button("End Game", type="primary", use_container_width=True):
        execute("UPDATE games SET tracked=1 WHERE id=?", (game_id,))
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  QUICK ADD — spreadsheet style
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("＋ Quick Add Player / Official"):
    qa_l, qa_r = st.columns(2)

    with qa_l:
        st.markdown("**Add Players**")
        all_teams  = query("SELECT id, name FROM teams ORDER BY name")
        qa_tm_map  = {t["name"]: t["id"] for t in all_teams}
        qa_tnames  = list(qa_tm_map.keys())

        qa_p_orig = st.session_state.get("_qa_players_orig",
                        pd.DataFrame(columns=["team","name","number","height","wingspan","weight"]))

        st.data_editor(
            qa_p_orig,
            key="qa_players_editor",
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "team":     st.column_config.SelectboxColumn("Team",         options=qa_tnames, required=True),
                "name":     st.column_config.TextColumn("Player Name",        required=True),
                "number":   st.column_config.NumberColumn("Number",           min_value=0, max_value=999, step=1),
                "height":   st.column_config.NumberColumn("Height (in)",      min_value=0.0, step=0.5),
                "wingspan": st.column_config.NumberColumn("Wingspan (in)",    min_value=0.0, step=0.5),
                "weight":   st.column_config.NumberColumn("Weight (lbs)",     min_value=0.0, step=1.0),
            },
        )
        if st.button("Save Players", key="qa_save_players", type="primary"):
            delta = st.session_state.get("qa_players_editor", {})
            # Merge added_rows with any edits applied to those same rows
            added = list(delta.get("added_rows", []))
            for idx_str, changes in delta.get("edited_rows", {}).items():
                idx = int(idx_str)
                if idx < len(added):
                    added[idx] = {**added[idx], **changes}
            saved = skipped = 0
            for r in added:
                name = r.get("name", "").strip()
                team = r.get("team")
                if not name or not team:
                    continue
                tid = qa_tm_map[team]
                exists = query(
                    "SELECT id FROM players WHERE team_id=? AND name=? AND archived=0",
                    (tid, name)
                )
                if exists:
                    skipped += 1
                    continue
                execute(
                    "INSERT INTO players (team_id, name, number, height, wingspan, weight) VALUES (?,?,?,?,?,?)",
                    (tid, name, int(r.get("number") or 0),
                     r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None)
                )
                saved += 1
            if saved or skipped:
                msg = f"Added {saved} player(s)."
                if skipped:
                    msg += f" {skipped} skipped (already exist)."
                st.success(msg)
                # Invalidate Input Hub player cache so it reloads from DB
                st.session_state.pop("_players_orig", None)
                st.session_state.pop("_qa_players_orig", None)
                st.session_state.pop("qa_players_editor", None)
                st.rerun()
            else:
                st.warning("Fill in at least one player row.")

    with qa_r:
        st.markdown("**Add Officials**")
        qa_o_orig = st.session_state.get("_qa_officials_orig",
                        pd.DataFrame(columns=["name","official_id"]))

        st.data_editor(
            qa_o_orig,
            key="qa_officials_editor",
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "name":        st.column_config.TextColumn("Official Name", required=True),
                "official_id": st.column_config.NumberColumn("Official ID", required=True, step=1),
            },
        )
        if st.button("Save Officials", key="qa_save_officials", type="primary"):
            delta = st.session_state.get("qa_officials_editor", {})
            added = delta.get("added_rows", [])
            saved = 0
            for r in added:
                if r.get("name","").strip() and r.get("official_id") is not None:
                    execute("INSERT OR IGNORE INTO officials (name, official_id) VALUES (?,?)",
                            (r["name"].strip(), int(r["official_id"])))
                    saved += 1
            if saved:
                st.success(f"Added {saved} official(s).")
                st.session_state.pop("_qa_officials_orig", None)
                st.session_state.pop("qa_officials_editor", None)
                st.rerun()
            else:
                st.warning("Fill in at least one official row.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  LINEUP  (no save button — read on every event log)
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("### Lineup")

t1_db  = query("SELECT id, name, number FROM players WHERE team_id=? AND archived=0 ORDER BY number, name", (t1id,))
t2_db  = query("SELECT id, name, number FROM players WHERE team_id=? AND archived=0 ORDER BY number, name", (t2id,))
all_offs = query("SELECT id, name FROM officials ORDER BY name")

t1_opts  = ["—"] + [f"#{p['number']} {p['name']}" for p in t1_db]
t2_opts  = ["—"] + [f"#{p['number']} {p['name']}" for p in t2_db]
off_opts_all = ["—"] + [o["name"] for o in all_offs]
t1_pmap  = {f"#{p['number']} {p['name']}": p["id"] for p in t1_db}
t2_pmap  = {f"#{p['number']} {p['name']}": p["id"] for p in t2_db}
off_imap = {o["name"]: o["id"] for o in all_offs}

lc1, lc2, lc3 = st.columns(3)
with lc1:
    st.markdown(f"**{t1name}**")
    cur_t1 = [st.selectbox(f"Slot {i+1}", t1_opts, key=f"t1_{game_id}_{i}") for i in range(5)]
with lc2:
    st.markdown(f"**{t2name}**")
    cur_t2 = [st.selectbox(f"Slot {i+1}", t2_opts, key=f"t2_{game_id}_{i}") for i in range(5)]
with lc3:
    st.markdown("**Officials**")
    cur_offs = [st.selectbox(f"Slot {i+1}", off_opts_all, key=f"off_{game_id}_{i}") for i in range(3)]

# Current on-court players (non-"—" selections) with their team
on_court = (
    [(t1_pmap[s], t1id) for s in cur_t1 if s != "—"] +
    [(t2_pmap[s], t2id) for s in cur_t2 if s != "—"]
)
on_court_offs = [off_imap[s] for s in cur_offs if s != "—"]

# Build player option lists for the event form
all_player_rows = query(
    "SELECT id AS pid, name AS pname, number, team_id FROM players "
    "WHERE team_id IN (?,?) AND archived=0 ORDER BY name", (t1id, t2id)
)
pid_to_row = {p["pid"]: p for p in all_player_rows}
pid_to_team = {p["pid"]: p["team_id"] for p in all_player_rows}

on_court_labels = []
for pid, tid in on_court:
    p = pid_to_row.get(pid)
    if p:
        tname_label = t1name if tid == t1id else t2name
        on_court_labels.append((f"{tname_label}: #{p['number']} {p['pname']}", pid))

all_opts = ["—"] + [lbl for lbl, _ in on_court_labels]
all_id   = {lbl: pid for lbl, pid in on_court_labels}
off_opts = ["—"] + [s for s in cur_offs if s != "—"]
off_eid  = {o["name"]: o["id"] for o in all_offs}

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  EVENT LOGGER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("### Log Event")

if not on_court:
    st.info("Select players in the lineup above first.")
else:
    event_type = st.selectbox("Event Type", ["Shot", "Free Throw", "Foul", "Turnover"], key="ev_type")

    with st.form("event_form", clear_on_submit=True):
        tc, qc = st.columns(2)
        time_input = tc.text_input("Time (MM:SS)", value="8:00")
        quarter    = qc.number_input("Quarter", min_value=1, max_value=10, step=1, value=1)

        st.markdown("---")

        if event_type == "Shot":
            r1a, r1b, r1c = st.columns(3)
            shooter   = r1a.selectbox("Shooter", all_opts[1:])
            shot_type = r1b.selectbox("Type", ["2", "3"])
            result    = r1c.selectbox("Result", ["make", "miss"])
            r2a, r2b, r2c = st.columns(3)
            zone      = r2a.selectbox("Zone", ZONES)
            pass_from = r2b.selectbox("Pass From", all_opts)
            created   = r2c.selectbox("Shot Created By", all_opts)
            r3a, r3b, r3c = st.columns(3)
            guarded   = r3a.selectbox("Guarded By", all_opts)
            rebound   = r3b.selectbox("Rebound By", all_opts)
            blocked   = r3c.selectbox("Blocked By", all_opts)

        elif event_type == "Free Throw":
            c1, c2, c3 = st.columns(3)
            shooter = c1.selectbox("Shooter", all_opts[1:])
            result  = c2.selectbox("Result", ["make", "miss"])
            rebound = c3.selectbox("Rebound By", all_opts)

        elif event_type == "Foul":
            c1, c2, c3 = st.columns(3)
            fouled   = c1.selectbox("Player Fouled", all_opts[1:])
            fouler   = c2.selectbox("Player Who Fouled", all_opts[1:])
            official = c3.selectbox("Official", off_opts)

        elif event_type == "Turnover":
            c1, c2 = st.columns(2)
            tov_p  = c1.selectbox("Turnover By", all_opts[1:])
            stolen = c2.selectbox("Stolen By", all_opts)

        submitted = st.form_submit_button("Log Event", type="primary", use_container_width=True)

    if submitted:
        q     = int(quarter)
        t     = time_input
        prev  = query("SELECT time FROM game_events WHERE game_id=? AND quarter=? ORDER BY id DESC LIMIT 1", (game_id, q))
        start = time_to_secs(prev[0]["time"]) if prev else (8*60 if q<=4 else 4*60)
        poss  = max(0.0, start - time_to_secs(t))

        def snapshot_and_apply_pm(event_id: int, scoring_team_id=None, pts: int = 0):
            """Snapshot the current lineup into game_event_lineup.
            If a scoring event, credit +/- to on-court players and persist
            them in game_lineup_players."""
            for pid, tid in on_court:
                execute("INSERT OR IGNORE INTO game_event_lineup (event_id, player_id, team_id) VALUES (?,?,?)",
                        (event_id, pid, tid))
                execute("INSERT OR IGNORE INTO game_lineup_players (game_id, team_id, player_id) VALUES (?,?,?)",
                        (game_id, tid, pid))
                if scoring_team_id and pts:
                    delta = pts if tid == scoring_team_id else -pts
                    execute("UPDATE game_lineup_players SET plus_minus = plus_minus + ? "
                            "WHERE game_id=? AND player_id=?", (delta, game_id, pid))
            for oid in on_court_offs:
                execute("INSERT OR IGNORE INTO game_lineup_officials (game_id, official_id) VALUES (?,?)",
                        (game_id, oid))

        if event_type == "Shot":
            eid = execute("""INSERT INTO game_events
                (game_id,event_type,quarter,time,possession_secs,primary_player_id,
                 shot_type,shot_result,pass_from_id,shot_created_by_id,
                 rebound_by_id,blocked_by_id,guarded_by_id,zone)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (game_id,"shot",q,t,poss,
                 plookup(shooter,all_id), int(shot_type), result,
                 plookup(pass_from,all_id), plookup(created,all_id),
                 plookup(rebound,all_id), plookup(blocked,all_id),
                 plookup(guarded,all_id), zone))
            sid = plookup(shooter, all_id)
            scoring_tid = pid_to_team.get(sid) if sid else None
            snapshot_and_apply_pm(eid, scoring_tid if result=="make" else None,
                                  int(shot_type) if result=="make" else 0)

        elif event_type == "Free Throw":
            eid = execute("""INSERT INTO game_events
                (game_id,event_type,quarter,time,possession_secs,
                 primary_player_id,shot_result,rebound_by_id)
                VALUES (?,?,?,?,?,?,?,?)""",
                (game_id,"free_throw",q,t,poss,
                 plookup(shooter,all_id), result, plookup(rebound,all_id)))
            sid = plookup(shooter, all_id)
            scoring_tid = pid_to_team.get(sid) if sid else None
            snapshot_and_apply_pm(eid, scoring_tid if result=="make" else None,
                                  1 if result=="make" else 0)

        elif event_type == "Foul":
            eid = execute("""INSERT INTO game_events
                (game_id,event_type,quarter,time,possession_secs,
                 primary_player_id,secondary_player_id,official_id)
                VALUES (?,?,?,?,?,?,?,?)""",
                (game_id,"foul",q,t,poss,
                 plookup(fouled,all_id), plookup(fouler,all_id),
                 off_eid.get(official) if official and official != "—" else None))
            snapshot_and_apply_pm(eid)

        elif event_type == "Turnover":
            eid = execute("""INSERT INTO game_events
                (game_id,event_type,quarter,time,possession_secs,
                 primary_player_id,stolen_by_id)
                VALUES (?,?,?,?,?,?,?)""",
                (game_id,"turnover",q,t,poss,
                 plookup(tov_p,all_id), plookup(stolen,all_id)))
            snapshot_and_apply_pm(eid)

        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  LIVE SCORE + PLAY-BY-PLAY
# ══════════════════════════════════════════════════════════════════════════════

st.divider()

pid_name = {p["pid"]: p["pname"] for p in all_player_rows}
oid_name = {o["id"]: o["name"] for o in all_offs}
def pn(pid): return pid_name.get(pid, f"ID:{pid}") if pid else "—"
def on_(oid): return oid_name.get(oid, "?") if oid else "—"

_, t1_live, t2_live = compute_box(game_id, game_info)
sc1, sc2, sc3 = st.columns([2,1,2])
sc1.metric(t1name, t1_live)
sc2.markdown("<div style='text-align:center;font-size:1.4em;padding-top:8px'>vs</div>", unsafe_allow_html=True)
sc3.metric(t2name, t2_live)

st.markdown("#### Play-by-Play")
recent = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id DESC", (game_id,))

if not recent:
    st.info("No events logged yet.")
else:
    log_rows = []
    for ev in recent:
        et = ev["event_type"]
        if et=="shot":
            icon = "✅" if ev["shot_result"]=="make" else "❌"
            desc = (f"{icon} {ev['shot_type']}pt · {ev['zone']} · Shooter:{pn(ev['primary_player_id'])} · "
                    f"Pass:{pn(ev['pass_from_id'])} · Reb:{pn(ev['rebound_by_id'])} · Blk:{pn(ev['blocked_by_id'])}")
        elif et=="free_throw":
            icon = "✅" if ev["shot_result"]=="make" else "❌"
            desc = f"FT {icon} · Shooter:{pn(ev['primary_player_id'])} · Reb:{pn(ev['rebound_by_id'])}"
        elif et=="foul":
            desc = (f"🟡 FOUL · Fouled:{pn(ev['primary_player_id'])} · "
                    f"By:{pn(ev['secondary_player_id'])} · Official:{on_(ev['official_id'])}")
        elif et=="turnover":
            desc = f"🔴 TOV · {pn(ev['primary_player_id'])} · Stolen:{pn(ev['stolen_by_id'])}"
        else:
            desc = et
        log_rows.append({"Q":ev["quarter"],"Time":ev["time"],"Poss(s)":round(ev["possession_secs"],1),"Play":desc})

    st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)

    if st.button("🗑 Delete Last Event", type="secondary"):
        last = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id DESC LIMIT 1", (game_id,))
        if last:
            ev  = last[0]
            eid = ev["id"]
            # Reverse +/- if this was a scoring event
            if ev["event_type"] in ("shot", "free_throw") and ev["shot_result"] == "make":
                pts = ev["shot_type"] if ev["event_type"] == "shot" else 1
                scorer_id   = ev["primary_player_id"]
                scoring_tid = pid_to_team.get(scorer_id) if scorer_id else None
                if scoring_tid and pts:
                    gel_rows = query(
                        "SELECT player_id, team_id FROM game_event_lineup WHERE event_id=?", (eid,))
                    for row in gel_rows:
                        pid, tid = row["player_id"], row["team_id"]
                        reverse_delta = -pts if tid == scoring_tid else pts
                        execute(
                            "UPDATE game_lineup_players SET plus_minus = plus_minus + ? "
                            "WHERE game_id=? AND player_id=?",
                            (reverse_delta, game_id, pid))
            execute("DELETE FROM game_events WHERE id=?", (eid,))
            st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  STATS TABS
# ══════════════════════════════════════════════════════════════════════════════

st.divider()
tab_box, tab_off, tab_zones = st.tabs(["Box Score", "Officials", "Hot Zones"])

with tab_box:
    rows, t1_pts, t2_pts = compute_box(game_id, game_info)
    cols = ["Player","PTS","AST","OREB","DREB","REB","STL","BLK","TOV",
            "FGM","FGA","3PM","3PA","FTM","FTA","SC","+/-","MIN","GS"]
    for tid, tname, pts in [(t1id,t1name,t1_pts),(t2id,t2name,t2_pts)]:
        st.markdown(f"### {tname} — {pts}")
        team_rows = [r for r in rows if r["_tid"]==tid]
        if team_rows:
            st.dataframe(pd.DataFrame(team_rows)[cols], use_container_width=True, hide_index=True)

with tab_off:
    off_rows = compute_off_box(game_id, game_info)
    if not off_rows:
        st.info("No officials or foul events yet.")
    else:
        df = pd.DataFrame(off_rows)
        df.columns = ["Official", f"Calls vs {t1name}", f"Calls vs {t2name}", "Total"]
        st.dataframe(df, use_container_width=True, hide_index=True)

with tab_zones:
    shots = query("SELECT zone, shot_type, shot_result FROM game_events WHERE game_id=? AND event_type='shot' AND zone IS NOT NULL", (game_id,))
    zd = {z: {2:[0,0], 3:[0,0]} for z in ZONES}
    for s in shots:
        z, t = s["zone"], s["shot_type"]
        if z and t:
            zd[z][t][1] += 1
            if s["shot_result"]=="make": zd[z][t][0] += 1

    def zcolor(m, a):
        if not a: return "#2d2d2d","#555555"
        p = m/a
        if p>=0.50: return "#1a5c38","#ffffff"
        if p>=0.35: return "#7a5200","#ffffff"
        return "#6b1515","#ffffff"

    for stype, label in [(2,"2-Point Zones"),(3,"3-Point Zones")]:
        st.markdown(f"**{label}**")
        cols = st.columns(5)
        for i, zone in enumerate(ZONES):
            m, a = zd[zone][stype]
            pct  = m/a*100 if a else 0
            bg, fg = zcolor(m, a)
            cols[i].markdown(
                f"""<div style="background:{bg};color:{fg};padding:16px 4px;border-radius:10px;text-align:center">
                <div style="font-weight:bold">{zone}</div>
                <div style="font-size:1.5em;font-weight:bold">{m}/{a}</div>
                <div style="font-size:0.85em">{pct:.0f}%</div></div>""",
                unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
