import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from database.db import query, execute, initialize_database
from helpers.settings_utils import get_all_settings, apply_page_config

ZONES = ["LC", "LW", "C", "RW", "RC"]

initialize_database()
_cfg = get_all_settings()
apply_page_config(_cfg)

st.title("Game Tracker")

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
    # Exclude 0-sec events (first event of a quarter at full clock has no elapsed time)
    mins_rows = query("""
        SELECT gel.player_id, SUM(ge.possession_secs) AS secs
        FROM game_event_lineup gel
        JOIN game_events ge ON ge.id = gel.event_id
        WHERE ge.game_id = ? AND ge.possession_secs > 0
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

def live_score(game_id: int, t1id: int, t2id: int) -> tuple:
    """Single aggregating query — only what's needed to show the scoreboard."""
    rows = query("""
        SELECT p.team_id,
               SUM(CASE WHEN ge.event_type='shot'       AND ge.shot_result='make' THEN ge.shot_type
                        WHEN ge.event_type='free_throw'  AND ge.shot_result='make' THEN 1
                        ELSE 0 END) AS pts
        FROM game_events ge
        JOIN players p ON p.id = ge.primary_player_id
        WHERE ge.game_id = ?
          AND ge.event_type IN ('shot','free_throw')
          AND ge.shot_result = 'make'
        GROUP BY p.team_id
    """, (game_id,))
    pts = {r["team_id"]: (r["pts"] or 0) for r in rows}
    return pts.get(t1id, 0), pts.get(t2id, 0)


def live_possessions(game_id: int, t1id: int, t2id: int) -> tuple:
    """Possession count per team. A possession ends on a shot or a turnover
    (+1); fouls and free throws do not change the count."""
    rows = query("""
        SELECT p.team_id, COUNT(*) AS poss
        FROM game_events ge
        JOIN players p ON p.id = ge.primary_player_id
        WHERE ge.game_id = ?
          AND ge.event_type IN ('shot','turnover')
        GROUP BY p.team_id
    """, (game_id,))
    poss = {r["team_id"]: (r["poss"] or 0) for r in rows}
    return poss.get(t1id, 0), poss.get(t2id, 0)


def compute_quarter_scores(game_id: int, t1id: int, t2id: int):
    """Returns a dict of {quarter: {t1id: pts, t2id: pts}} for all quarters played."""
    rows = query("""
        SELECT ge.quarter, ge.event_type, ge.shot_result, ge.shot_type, p.team_id AS tid
        FROM game_events ge
        JOIN players p ON p.id = ge.primary_player_id
        WHERE ge.game_id = ? AND ge.primary_player_id IS NOT NULL
          AND ge.event_type IN ('shot','free_throw') AND ge.shot_result = 'make'
        ORDER BY ge.quarter, ge.id
    """, (game_id,))
    quarters = {}
    for r in rows:
        q = r["quarter"]
        if q not in quarters:
            quarters[q] = {t1id: 0, t2id: 0}
        pts = r["shot_type"] if r["event_type"] == "shot" else 1
        if r["tid"] in quarters[q]:
            quarters[q][r["tid"]] += pts
    return quarters


# ══════════════════════════════════════════════════════════════════════════════
#  GAME SELECTOR  — Home Team → Away Team → Game
# ══════════════════════════════════════════════════════════════════════════════

all_games = query("""
    SELECT g.id, t1.name AS t1, t2.name AS t2, g.date
    FROM games g JOIN teams t1 ON t1.id=g.team1_id JOIN teams t2 ON t2.id=g.team2_id
""")
# Sort by real date (stored as text so ORDER BY is lexicographic)
all_games = sorted(all_games, key=lambda g: pd.to_datetime(g["date"], format="mixed", errors="coerce"), reverse=True)
if not all_games:
    st.warning("No games found. Add games in the Input Hub first.")
    st.stop()

# team1 = home, team2 = away
gs1, gs2, gs3 = st.columns(3)

home_teams = sorted({g["t1"] for g in all_games})
sel_home   = gs1.selectbox("Home Team", home_teams)

home_games = [g for g in all_games if g["t1"] == sel_home]
away_teams = sorted({g["t2"] for g in home_games})
sel_away   = gs2.selectbox("Away Team", away_teams)

matching = [g for g in home_games if g["t2"] == sel_away]
if len(matching) == 1:
    game_id = matching[0]["id"]
    gs3.selectbox("Date", [matching[0]["date"]], disabled=True)
else:
    date_labels = {g["date"]: g["id"] for g in matching}
    sel_date    = gs3.selectbox("Date", list(date_labels.keys()))
    game_id     = date_labels[sel_date]

lineup      = load_lineup(game_id)
game_info   = lineup["game"]
t1id, t2id  = game_info["team1_id"], game_info["team2_id"]
t1name, t2name = game_info["t1_name"], game_info["t2_name"]

is_tracked = bool(query("SELECT tracked FROM games WHERE id=?", (game_id,))[0]["tracked"])

gc1, gc2 = st.columns([4, 1])
if is_tracked:
    gc2.success("✓ Game Final")
else:
    if gc2.button("End Game", type="primary", width="stretch"):
        t1_final, t2_final = live_score(game_id, t1id, t2id)
        execute("UPDATE games SET tracked=1, home_score=?, away_score=? WHERE id=?",
                (t1_final, t2_final, game_id))
        st.cache_data.clear()   # clear rankings / analytics caches at game end
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  TEAM NOTES
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("📋 Team Notes", expanded=False):
    notes_col1, notes_col2 = st.columns(2)
    for col, tid, tname in [(notes_col1, t1id, t1name), (notes_col2, t2id, t2name)]:
        with col:
            st.markdown(f"**{tname}**")
            cur = query("SELECT notes FROM teams WHERE id=?", (tid,))
            existing_note = cur[0]["notes"] if cur else ""
            new_note = st.text_area(
                "Notes", value=existing_note, height=180,
                placeholder="Scouting notes, tendencies, game plan…",
                key=f"gt_notes_{game_id}_{tid}",
                label_visibility="collapsed",
            )
            if st.button("💾 Save", key=f"gt_save_notes_{game_id}_{tid}", type="primary"):
                execute("UPDATE teams SET notes=? WHERE id=?", (new_note, tid))
                st.success("Saved.")

# ══════════════════════════════════════════════════════════════════════════════
#  QUICK ADD — spreadsheet style
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("＋ Quick Add Player / Official"):
    qa_l, qa_r = st.columns(2)

    with qa_l:
        st.markdown("**Add Players**")
        qa_tm_map  = {t1name: t1id, t2name: t2id}
        qa_tnames  = [t1name, t2name]

        qa_p_orig = st.session_state.get("_qa_players_orig",
                        pd.DataFrame(columns=["team","name","number","height","wingspan","weight"]))

        st.data_editor(
            qa_p_orig,
            key="qa_players_editor",
            num_rows="dynamic",
            width="stretch",
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
                st.cache_data.clear()
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
            width="stretch",
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
                st.cache_data.clear()
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

def _abbr(name: str) -> str:
    """'Adair Girls' → 'AG', 'North Valley' → 'NV'"""
    return "".join(w[0].upper() for w in name.split() if w)

on_court_labels = []
for pid, tid in on_court:
    p = pid_to_row.get(pid)
    if p:
        abbr = _abbr(t1name if tid == t1id else t2name)
        on_court_labels.append((f"{abbr} #{p['number']} {p['pname']}", pid))

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

    _last_time = st.session_state.get(f"last_time_{game_id}", "8:00")
    _last_q    = st.session_state.get(f"last_q_{game_id}", 1)
    try:
        _lm, _ls = _last_time.split(":")
        _last_mins = int(_lm)
        _last_secs = int(_ls)
    except Exception:
        _last_mins, _last_secs = 8, 0

    with st.form("event_form", clear_on_submit=True):
        mc, sc, qc = st.columns(3)
        mins_input = mc.number_input("Minutes", min_value=0, max_value=99, step=1, value=_last_mins)
        secs_input = sc.number_input("Seconds", min_value=0, max_value=59, step=1, value=_last_secs)
        quarter    = qc.number_input("Quarter", min_value=1, max_value=10, step=1, value=int(_last_q))

        st.markdown("---")

        if event_type == "Shot":
            # Shooter gets more space; Type & Result are short lists
            r1a, r1b, r1c = st.columns([3, 1, 1])
            shooter   = r1a.selectbox("Shooter", all_opts[1:])
            shot_type = r1b.selectbox("Type", ["2", "3"])
            result    = r1c.selectbox("Result", ["make", "miss"])
            # Zone is short; Pass From & Created By need more room
            r2a, r2b, r2c = st.columns([1, 2, 2])
            zone      = r2a.selectbox("Zone", ZONES)
            pass_from = r2b.selectbox("Pass From", all_opts)
            created   = r2c.selectbox("Shot Created By", all_opts)
            # All three are player pickers — equal width
            r3a, r3b, r3c = st.columns(3)
            guarded   = r3a.selectbox("Guarded By", all_opts)
            rebound   = r3b.selectbox("Rebound By", all_opts)
            blocked   = r3c.selectbox("Blocked By", all_opts)

        elif event_type == "Free Throw":
            c1, c2, c3 = st.columns([3, 1, 2])
            shooter = c1.selectbox("Shooter", all_opts[1:])
            result  = c2.selectbox("Result", ["make", "miss"])
            rebound = c3.selectbox("Rebound By", all_opts)

        elif event_type == "Foul":
            c1, c2, c3 = st.columns([2, 2, 1])
            fouled   = c1.selectbox("Player Fouled", all_opts[1:])
            fouler   = c2.selectbox("Player Who Fouled", all_opts[1:])
            official = c3.selectbox("Official", off_opts)

        elif event_type == "Turnover":
            c1, c2 = st.columns(2)
            tov_p  = c1.selectbox("Turnover By", all_opts[1:])
            stolen = c2.selectbox("Stolen By", all_opts)

        submitted = st.form_submit_button("Log Event", type="primary", width="stretch")

    if submitted:
        q = int(quarter)
        t = f"{int(mins_input)}:{int(secs_input):02d}"
        # Persist so the form re-opens with the same time/quarter
        st.session_state[f"last_time_{game_id}"] = t
        st.session_state[f"last_q_{game_id}"]    = q
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

        st.session_state[f"last_time_{game_id}"] = t
        st.session_state[f"last_q_{game_id}"]    = q
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
#  LIVE SCORE + PLAY-BY-PLAY
# ══════════════════════════════════════════════════════════════════════════════

st.divider()

pid_name = {p["pid"]: p["pname"] for p in all_player_rows}
oid_name = {o["id"]: o["name"] for o in all_offs}
def pn(pid): return pid_name.get(pid, f"ID:{pid}") if pid else "—"
def on_(oid): return oid_name.get(oid, "?") if oid else "—"

t1_live, t2_live = live_score(game_id, t1id, t2id)
sc1, sc2, sc3 = st.columns([2,1,2])
sc1.metric(t1name, t1_live)
sc2.markdown("<div style='text-align:center;font-size:1.4em;padding-top:8px'>vs</div>", unsafe_allow_html=True)
sc3.metric(t2name, t2_live)

# Possessions — a possession ends on a shot or turnover (+1); fouls / free throws don't count
t1_poss, t2_poss = live_possessions(game_id, t1id, t2id)
pc1, pc2, pc3 = st.columns([2,1,2])
pc1.metric(f"{t1name} Poss.", t1_poss)
pc2.markdown("<div style='text-align:center;color:#888;padding-top:8px'>possessions</div>", unsafe_allow_html=True)
pc3.metric(f"{t2name} Poss.", t2_poss)

# Quarter-by-quarter breakdown
q_scores = compute_quarter_scores(game_id, t1id, t2id)
if q_scores:
    all_quarters = sorted(q_scores.keys())
    def q_label(q): return f"Q{q}" if q <= 4 else f"OT{q-4}"
    q_row_t1 = {"Team": t1name}
    q_row_t2 = {"Team": t2name}
    t1_tot = t2_tot = 0
    for q in all_quarters:
        lbl = q_label(q)
        q_row_t1[lbl] = q_scores[q].get(t1id, 0)
        q_row_t2[lbl] = q_scores[q].get(t2id, 0)
        t1_tot += q_scores[q].get(t1id, 0)
        t2_tot += q_scores[q].get(t2id, 0)
    q_row_t1["Total"] = t1_tot
    q_row_t2["Total"] = t2_tot
    st.dataframe(pd.DataFrame([q_row_t1, q_row_t2]), hide_index=True, width="stretch")

st.markdown("#### Play-by-Play")
recent = query("SELECT * FROM game_events WHERE game_id=? ORDER BY id DESC", (game_id,))

if not recent:
    st.info("No events logged yet.")
else:
    log_rows = []
    for ev in recent:
        et = ev["event_type"]
        # A possession ends on a shot or turnover (+1); fouls / free throws don't count
        poss_inc = 1 if et in ("shot", "turnover") else 0
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
        log_rows.append({"Q":ev["quarter"],"Time":ev["time"],"Poss":poss_inc,"Play":desc})

    pbp_df = pd.DataFrame(log_rows)
    st.dataframe(pbp_df, width="stretch", hide_index=True)
    st.download_button("⬇ Export Play-by-Play (CSV)", pbp_df.to_csv(index=False),
                       file_name=f"pbp_{game_id}.csv", mime="text/csv", key="dl_pbp")

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
            st.cache_data.clear()
            st.rerun()
