import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from Database.db import query, execute, initialize_database

initialize_database()

st.title("Input Hub")

CLASS_OPTIONS  = ["B2", "B1", "A", "2A", "3A", "4A", "5A", "6A", "N/A"]
GENDER_OPTIONS = ["M", "F"]
HA_OPTIONS     = ["Home", "Away"]

EDITOR_HELP = "**Click any cell to edit.** Hover a row and click 🗑 to delete. Use the **＋** row at the bottom to add."


def sort_by_date(df: pd.DataFrame, col: str = "date", ascending: bool = False) -> pd.DataFrame:
    """Sort a dataframe by a date column regardless of text format."""
    if df.empty or col not in df.columns:
        return df
    df = df.copy()
    df["_sort"] = pd.to_datetime(df[col], errors="coerce", dayfirst=False)
    df = df.sort_values("_sort", ascending=ascending).drop(columns=["_sort"])
    return df.reset_index(drop=True)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def team_map():
    rows = query("SELECT id, name FROM teams ORDER BY name")
    return {r["name"]: r["id"] for r in rows}

def team_names():
    return list(team_map().keys())

def load_teams():
    rows = query("SELECT id, name, class, gender FROM teams ORDER BY name")
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id","name","class","gender"])

def load_players_for(team_id):
    rows = query(
        "SELECT id, name, number, height, wingspan, weight FROM players WHERE team_id=? AND archived=0 ORDER BY name",
        (team_id,)
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["id","name","number","height","wingspan","weight"])

def load_games_for_team(team_id):
    """Load all games involving team_id from the games table, presented from that team's POV."""
    rows = query("""
        SELECT g.id,
            CASE WHEN g.team1_id=? THEN t2.name ELSE t1.name END AS opponent,
            g.date,
            CASE WHEN g.team1_id=? THEN 'Home' ELSE 'Away' END   AS home_away,
            g.location,
            CASE WHEN g.team1_id=? THEN g.home_score ELSE g.away_score END AS team_score,
            CASE WHEN g.team1_id=? THEN g.away_score ELSE g.home_score END AS opp_score,
            g.tracked
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE g.team1_id=? OR g.team2_id=?
    """, (team_id,)*6)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["id","opponent","date","home_away","location","team_score","opp_score","tracked"])
    if not df.empty:
        df["tracked"] = df["tracked"].astype(bool)
    return sort_by_date(df, ascending=False)

def load_officials():
    rows = query("SELECT id, name, official_id FROM officials ORDER BY name")
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id","name","official_id"])

def load_games():
    rows = query("""
        SELECT g.id, t1.name AS team1, t2.name AS team2,
               g.date, g.location, g.home_score, g.away_score, g.tracked
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
    """)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["id","team1","team2","date","location","home_score","away_score","tracked"])
    if not df.empty:
        df["tracked"] = df["tracked"].astype(bool)
    return sort_by_date(df, ascending=False)


# ── delta applier ──────────────────────────────────────────────────────────────

def apply_delta(editor_key, orig_df, insert_fn, update_fn, delete_fn):
    delta = st.session_state.get(editor_key, {})
    errors = []
    for idx, changes in delta.get("edited_rows", {}).items():
        row = orig_df.iloc[int(idx)].to_dict()
        row.update(changes)
        try:
            update_fn(row)
        except Exception as e:
            errors.append(str(e))
    for row in delta.get("added_rows", []):
        try:
            insert_fn(row)
        except Exception as e:
            errors.append(str(e))
    for idx in sorted(delta.get("deleted_rows", []), reverse=True):
        row = orig_df.iloc[int(idx)].to_dict()
        try:
            delete_fn(row)
        except Exception as e:
            errors.append(str(e))
    return errors


# ── session cache (keyed so changing the team selector resets the editor) ──────

def get_orig(cache_key, loader):
    if cache_key not in st.session_state:
        st.session_state[cache_key] = loader()
    return st.session_state[cache_key]

def invalidate(*keys):
    for k in keys:
        st.session_state.pop(k, None)


# ══════════════════════════════════════════════════════════════════════════════
#  NEW SEASON
# ══════════════════════════════════════════════════════════════════════════════

with st.expander("New Season", expanded=False):
    st.warning(
        "Rolling over archives all current players and schedules under a season label, "
        "then starts fresh. Historical game data and tracked stats are always preserved."
    )
    season_label = st.text_input("Season label (e.g. 2024-25)", placeholder="2024-25", key="season_label_input")
    confirm = st.checkbox("I understand — roll over to a new season", key="new_season_confirm")
    can_go = confirm and bool(season_label.strip())
    if st.button("Start New Season", type="primary", disabled=not can_go, key="new_season_btn"):
        lbl = season_label.strip()
        execute("UPDATE players SET archived=1, season=? WHERE archived=0", (lbl,))
        execute("UPDATE schedule SET season=? WHERE season='Current'", (lbl,))
        invalidate("_players_orig", "players_editor", "_sched_orig", "sched_editor")
        st.success(f"Season '{lbl}' archived. Add new rosters and schedules to start fresh.")
        st.cache_data.clear()
        st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
tab_teams, tab_players, tab_games, tab_schedule, tab_officials, tab_archive = st.tabs(
    ["Teams", "Players", "Games", "Team Schedule", "Officials", "Season Archive"]
)


# ══════════════════════════════════════════════════════════════════════════════
#  TEAMS
# ══════════════════════════════════════════════════════════════════════════════
with tab_teams:
    st.caption(EDITOR_HELP)
    orig = get_orig("_teams_orig", load_teams)
    display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(columns=["name","class","gender"])

    st.data_editor(
        display,
        key="teams_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "name":   st.column_config.TextColumn("Team Name", required=True),
            "class":  st.column_config.SelectboxColumn("Class",  options=CLASS_OPTIONS,  required=True),
            "gender": st.column_config.SelectboxColumn("Gender", options=GENDER_OPTIONS, required=True),
        },
    )

    if st.button("Save Changes", key="save_teams", type="primary"):
        def ins_team(r):
            if r.get("name", "").strip():
                execute("INSERT OR IGNORE INTO teams (name, class, gender) VALUES (?,?,?)",
                        (r["name"].strip(), r.get("class","N/A"), r.get("gender","M")))
        def upd_team(r):
            execute("UPDATE teams SET name=?, class=?, gender=? WHERE id=?",
                    (r["name"].strip(), r["class"], r["gender"], r["id"]))
        def del_team(r):
            execute("DELETE FROM teams WHERE id=?", (r["id"],))

        errs = apply_delta("teams_editor", orig, ins_team, upd_team, del_team)
        if errs:
            st.error("\n".join(errs))
        else:
            st.success("Saved!")
        invalidate("_teams_orig", "teams_editor")
        st.cache_data.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYERS  (standalone team picker)
# ══════════════════════════════════════════════════════════════════════════════
with tab_players:
    tnames = team_names()
    if not tnames:
        st.warning("Add at least one team first.")
    else:
        selected_team = st.selectbox("Select Team", tnames, key="player_team_sel")
        tm = team_map()
        team_id = tm[selected_team]

        # Reset editor when team changes
        prev_key = "_players_prev_team"
        if st.session_state.get(prev_key) != selected_team:
            invalidate("_players_orig", "players_editor")
            st.session_state[prev_key] = selected_team

        st.caption(EDITOR_HELP)
        orig = get_orig("_players_orig", lambda: load_players_for(team_id))
        display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(
            columns=["name","number","height","wingspan","weight"])

        st.data_editor(
            display,
            key="players_editor",
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "name":     st.column_config.TextColumn("Player Name", required=True),
                "number":   st.column_config.NumberColumn("Number",      min_value=0, max_value=999, step=1),
                "height":   st.column_config.NumberColumn("Height (in)", min_value=0.0, step=0.5),
                "wingspan": st.column_config.NumberColumn("Wingspan (in)", min_value=0.0, step=0.5),
                "weight":   st.column_config.NumberColumn("Weight (lbs)", min_value=0.0, step=1.0),
            },
        )

        if st.button("Save Changes", key="save_players", type="primary"):
            def ins_player(r):
                if r.get("name","").strip():
                    execute(
                        "INSERT INTO players (team_id, name, number, height, wingspan, weight) VALUES (?,?,?,?,?,?)",
                        (team_id, r["name"].strip(), int(r.get("number") or 0),
                         r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None)
                    )
            def upd_player(r):
                execute(
                    "UPDATE players SET team_id=?, name=?, number=?, height=?, wingspan=?, weight=? WHERE id=?",
                    (team_id, r["name"].strip(), int(r.get("number") or 0),
                     r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None,
                     r["id"])
                )
            def del_player(r):
                execute("DELETE FROM players WHERE id=?", (r["id"],))

            errs = apply_delta("players_editor", orig, ins_player, upd_player, del_player)
            if errs:
                st.error("\n".join(errs))
            else:
                st.success("Saved!")
            invalidate("_players_orig", "players_editor")
            st.cache_data.clear()
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  GAMES
# ══════════════════════════════════════════════════════════════════════════════
with tab_games:
    tnames = team_names()
    if not tnames:
        st.warning("Add at least one team first.")
    else:
        st.caption(EDITOR_HELP)
        orig = get_orig("_games_orig", load_games)
        display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(
            columns=["team1","team2","date","location","home_score","away_score","tracked"])

        st.data_editor(
            display,
            key="games_editor",
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "team1":      st.column_config.SelectboxColumn("Home Team",    options=tnames, required=True),
                "team2":      st.column_config.SelectboxColumn("Away Team",    options=tnames, required=True),
                "date":       st.column_config.TextColumn("Date (MM/DD/YY)",   required=True),
                "location":   st.column_config.TextColumn("Location"),
                "home_score": st.column_config.NumberColumn("Home Score",      min_value=0, step=1),
                "away_score": st.column_config.NumberColumn("Away Score",      min_value=0, step=1),
                "tracked":    st.column_config.CheckboxColumn("Tracked",       default=False),
            },
        )

        if st.button("Save Changes", key="save_games", type="primary"):
            tm = team_map()
            def ins_game(r):
                if r.get("date","").strip() and r.get("team1") and r.get("team2"):
                    execute(
                        "INSERT INTO games (team1_id, team2_id, date, location, home_score, away_score, tracked) VALUES (?,?,?,?,?,?,?)",
                        (tm[r["team1"]], tm[r["team2"]], r["date"].strip(),
                         r.get("location") or None, r.get("home_score") or None,
                         r.get("away_score") or None, int(bool(r.get("tracked", False))))
                    )
            def upd_game(r):
                execute(
                    "UPDATE games SET team1_id=?, team2_id=?, date=?, location=?, home_score=?, away_score=?, tracked=? WHERE id=?",
                    (tm[r["team1"]], tm[r["team2"]], r["date"].strip(),
                     r.get("location") or None, r.get("home_score") or None,
                     r.get("away_score") or None, int(bool(r.get("tracked", False))), r["id"])
                )
            def del_game(r):
                execute("DELETE FROM games WHERE id=?", (r["id"],))

            errs = apply_delta("games_editor", orig, ins_game, upd_game, del_game)
            if errs:
                st.error("\n".join(errs))
            else:
                st.success("Saved!")
            invalidate("_games_orig", "games_editor")
            st.cache_data.clear()
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  TEAM SCHEDULE  — same games table as the Games tab, team POV
# ══════════════════════════════════════════════════════════════════════════════
with tab_schedule:
    tnames = team_names()
    if not tnames:
        st.warning("Add at least one team first.")
    else:
        selected_team = st.selectbox("Select Team", tnames, key="sched_team_sel")
        tm = team_map()
        team_id = tm[selected_team]

        prev_key = "_sched_prev_team"
        if st.session_state.get(prev_key) != selected_team:
            invalidate("_sched_orig", "sched_editor")
            st.session_state[prev_key] = selected_team

        st.caption(EDITOR_HELP)
        orig = get_orig("_sched_orig", lambda: load_games_for_team(team_id))
        display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(
            columns=["opponent","date","home_away","location","team_score","opp_score","tracked"])

        # Opponents are every team except the selected one
        opp_options = [t for t in tnames if t != selected_team]

        st.data_editor(
            display,
            key="sched_editor",
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "opponent":   st.column_config.SelectboxColumn("Opponent",       options=opp_options, required=True),
                "date":       st.column_config.TextColumn("Date (MM/DD/YY)",     required=True),
                "home_away":  st.column_config.SelectboxColumn("Home / Away",    options=HA_OPTIONS,  required=True),
                "location":   st.column_config.TextColumn("Location"),
                "team_score": st.column_config.NumberColumn("Team Score",        min_value=0, step=1),
                "opp_score":  st.column_config.NumberColumn("Opp Score",         min_value=0, step=1),
                "tracked":    st.column_config.CheckboxColumn("Tracked",         default=False),
            },
        )

        if st.button("Save Changes", key="save_sched", type="primary"):
            def ins_sched(r):
                opp = r.get("opponent")
                date = r.get("date", "").strip()
                if not opp or not date:
                    return
                opp_id = tm[opp]
                ha = r.get("home_away", "Home")
                t_score = r.get("team_score") or None
                o_score = r.get("opp_score")  or None
                tracked = int(bool(r.get("tracked", False)))
                if ha == "Home":
                    t1, t2, h_sc, a_sc = team_id, opp_id, t_score, o_score
                else:
                    t1, t2, h_sc, a_sc = opp_id, team_id, o_score, t_score
                execute(
                    "INSERT INTO games (team1_id, team2_id, date, location, home_score, away_score, tracked) VALUES (?,?,?,?,?,?,?)",
                    (t1, t2, date, r.get("location") or None, h_sc, a_sc, tracked)
                )

            def upd_sched(r):
                opp = r.get("opponent")
                date = r.get("date", "").strip()
                if not opp or not date:
                    return
                opp_id = tm[opp]
                ha = r.get("home_away", "Home")
                t_score = r.get("team_score") or None
                o_score = r.get("opp_score")  or None
                tracked = int(bool(r.get("tracked", False)))
                if ha == "Home":
                    t1, t2, h_sc, a_sc = team_id, opp_id, t_score, o_score
                else:
                    t1, t2, h_sc, a_sc = opp_id, team_id, o_score, t_score
                execute(
                    "UPDATE games SET team1_id=?, team2_id=?, date=?, location=?, home_score=?, away_score=?, tracked=? WHERE id=?",
                    (t1, t2, date, r.get("location") or None, h_sc, a_sc, tracked, r["id"])
                )

            def del_sched(r):
                execute("DELETE FROM games WHERE id=?", (r["id"],))

            errs = apply_delta("sched_editor", orig, ins_sched, upd_sched, del_sched)
            if errs:
                st.error("\n".join(errs))
            else:
                st.success("Saved!")
            invalidate("_sched_orig", "sched_editor", "_games_orig", "games_editor")
            st.cache_data.clear()
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  OFFICIALS
# ══════════════════════════════════════════════════════════════════════════════
with tab_officials:
    st.caption(EDITOR_HELP)
    orig = get_orig("_officials_orig", load_officials)
    display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(
        columns=["name", "official_id"])

    st.data_editor(
        display,
        key="officials_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "name":        st.column_config.TextColumn("Official Name", required=True),
            "official_id": st.column_config.NumberColumn("Official ID", required=True, step=1),
        },
    )

    if st.button("Save Changes", key="save_officials", type="primary"):
        def ins_official(r):
            if r.get("name", "").strip() and r.get("official_id") is not None:
                execute("INSERT OR IGNORE INTO officials (name, official_id) VALUES (?,?)",
                        (r["name"].strip(), int(r["official_id"])))
        def upd_official(r):
            execute("UPDATE officials SET name=?, official_id=? WHERE id=?",
                    (r["name"].strip(), int(r["official_id"]), r["id"]))
        def del_official(r):
            execute("DELETE FROM officials WHERE id=?", (r["id"],))

        errs = apply_delta("officials_editor", orig, ins_official, upd_official, del_official)
        if errs:
            st.error("\n".join(errs))
        else:
            st.success("Saved!")
        invalidate("_officials_orig", "officials_editor")
        st.cache_data.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  SEASON ARCHIVE
# ══════════════════════════════════════════════════════════════════════════════
with tab_archive:
    past_seasons = query(
        "SELECT DISTINCT season FROM players WHERE archived=1 ORDER BY season"
    )
    past_seasons += query(
        "SELECT DISTINCT season FROM schedule WHERE season != 'Current' ORDER BY season"
    )
    seen = set()
    seasons = []
    for r in past_seasons:
        if r["season"] not in seen:
            seen.add(r["season"])
            seasons.append(r["season"])
    seasons = sorted(seasons)

    if not seasons:
        st.info("No archived seasons yet. Use the New Season panel to roll over.")
    else:
        sel_season = st.selectbox("Select Season", seasons, key="archive_season_sel")

        arc_tab_rosters, arc_tab_schedule = st.tabs(["Rosters", "Schedule"])

        with arc_tab_rosters:
            st.subheader(f"Rosters — {sel_season}")
            teams_with_players = query("""
                SELECT DISTINCT t.id, t.name
                FROM players p
                JOIN teams t ON t.id = p.team_id
                WHERE p.archived=1 AND p.season=?
                ORDER BY t.name
            """, (sel_season,))
            if not teams_with_players:
                st.info("No player data for this season.")
            else:
                for team in teams_with_players:
                    with st.expander(team["name"]):
                        rows = query("""
                            SELECT name, number, height, wingspan, weight
                            FROM players
                            WHERE team_id=? AND archived=1 AND season=?
                            ORDER BY name
                        """, (team["id"], sel_season))
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        with arc_tab_schedule:
            st.subheader(f"Schedules — {sel_season}")
            teams_with_sched = query("""
                SELECT DISTINCT t.id, t.name
                FROM schedule s
                JOIN teams t ON t.id = s.team_id
                WHERE s.season=?
                ORDER BY t.name
            """, (sel_season,))
            if not teams_with_sched:
                st.info("No schedule data for this season.")
            else:
                for team in teams_with_sched:
                    with st.expander(team["name"]):
                        rows = query("""
                            SELECT o.name AS opponent, s.date, s.home_away,
                                   s.location, s.team_score, s.opp_score, s.tracked
                            FROM schedule s
                            JOIN teams o ON o.id = s.opponent_id
                            WHERE s.team_id=? AND s.season=?
                            ORDER BY s.date
                        """, (team["id"], sel_season))
                        df = pd.DataFrame(rows) if rows else pd.DataFrame()
                        if not df.empty:
                            df["tracked"] = df["tracked"].astype(bool)
                        st.dataframe(df, use_container_width=True, hide_index=True)
