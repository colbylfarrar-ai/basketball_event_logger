"""
10_Setup.py — set the coaching fields the Game Tracker doesn't capture: player
POSITION & AVAILABILITY, team DISTRICT, and game TYPE.

These power the depth chart (Team Dashboard), standings (Rankings) and game tags.
Editing is bulk via st.data_editor; nothing here touches tracked event data, and
the Input Hub / Game Tracker stay untouched. Display + controls only.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from database.db import query, execute
from helpers.ui import page_chrome, page_header, empty_state
import helpers.manual_box as MB

_cfg, ACCENT = page_chrome("Setup")

page_header("Roster & District",
            sub="Set the extras the Game Tracker doesn't capture — player positions & "
                "availability, team district, and game type. These power the depth "
                "chart, standings and game tags. (The Input Hub & Game Tracker are "
                "untouched.)")

POSITIONS = ["", "PG", "SG", "SF", "PF", "C"]
AVAIL = ["Active", "Questionable", "Out", "Injured", "Suspended"]
GAME_TYPES = ["Regular", "District", "Rivalry", "Playoff", "Showcase", "Tournament"]

t_roster, t_teams, t_games, t_box = st.tabs(
    ["Roster — position & status", "Teams — district", "Games — type",
     "Box scores — entered"])


# ── roster: position + availability ───────────────────────────────────────────
with t_roster:
    teams = query("SELECT id, name FROM teams ORDER BY name")
    if not teams:
        empty_state("No teams yet", "Add teams in the Input Hub first.")
    else:
        tsel = st.selectbox("Team", teams, format_func=lambda r: r["name"],
                            key="su_team")
        pl = query(
            """SELECT id, number, name, position, availability, handedness,
                      grad_year, height, wingspan, weight
               FROM players WHERE team_id=? AND archived=0 ORDER BY number""",
            (tsel["id"],))
        if not pl:
            empty_state("No players on this team", "Add players in the Input Hub.")
        else:
            ed = st.data_editor(
                pd.DataFrame(pl), hide_index=True, width="stretch", key="su_roster",
                column_config={
                    "id": None,
                    "number": st.column_config.NumberColumn("#", disabled=True),
                    "name": st.column_config.TextColumn("Player", disabled=True),
                    "position": st.column_config.SelectboxColumn(
                        "Position", options=POSITIONS),
                    "availability": st.column_config.SelectboxColumn(
                        "Status", options=AVAIL),
                    "handedness": st.column_config.SelectboxColumn(
                        "Hand", options=["right", "left"], default="right",
                        help="Shooting hand — drives dominant- vs weak-side shot splits."),
                    "grad_year": st.column_config.NumberColumn(
                        "Grad yr", min_value=2000, max_value=2100, step=1, format="%d",
                        help="Class year (e.g. 2026). Seniors auto-graduate on New "
                             "Season rollover; everyone else carries forward "
                             "identity-linked. Drives cross-season development."),
                    "height": st.column_config.NumberColumn("Ht", disabled=True),
                    "wingspan": st.column_config.NumberColumn("Wing", disabled=True),
                    "weight": st.column_config.NumberColumn("Wt", disabled=True),
                })
            if st.button("Save roster", key="su_roster_save"):
                for _, r in ed.iterrows():
                    _gy = r.get("grad_year")
                    try:
                        _gy = int(_gy) if (_gy not in (None, "") and not pd.isna(_gy)) else None
                    except (ValueError, TypeError):
                        _gy = None
                    execute("UPDATE players SET position=?, availability=?, handedness=?, grad_year=? WHERE id=?",
                            (r["position"] or "", r["availability"] or "Active",
                             "left" if r["handedness"] == "left" else "right", _gy,
                             int(r["id"])))
                st.cache_data.clear()   # depth chart & co. read these via cached queries
                st.success("Roster saved.")
            st.caption("Height / wingspan / weight come from the Input Hub (read-only "
                       "here) and now show on the depth chart.")


# ── teams: district ───────────────────────────────────────────────────────────
with t_teams:
    trows = query("SELECT id, name, class, gender, district FROM teams ORDER BY name")
    if not trows:
        empty_state("No teams yet", "Add teams in the Input Hub first.")
    else:
        _tdf = pd.DataFrame(trows)
        _tq = st.text_input("Search teams", key="su_teams_q",
                            placeholder="team name, class, or district…").strip().lower()
        if _tq:
            _tm = pd.Series(False, index=_tdf.index)
            for _c in ("name", "class", "district"):
                _tm = _tm | _tdf[_c].astype(str).str.lower().str.contains(_tq, na=False)
            _tdf = _tdf[_tm]
        st.caption(f"{len(_tdf)} of {len(trows)} teams"
                   + (" — edit the District cell, then Save." if not _tdf.empty else ""))
        ed = st.data_editor(
            _tdf, hide_index=True, width="stretch", key="su_teams",
            column_config={
                "id": None,
                "name": st.column_config.TextColumn("Team", disabled=True),
                "class": st.column_config.TextColumn("Class", disabled=True),
                "gender": st.column_config.TextColumn("Gender", disabled=True),
                "district": st.column_config.TextColumn(
                    "District", help="Free text, e.g. '3A-4' — groups the standings."),
            })
        if st.button("Save districts", key="su_teams_save"):
            for _, r in ed.iterrows():
                execute("UPDATE teams SET district=? WHERE id=?",
                        (r["district"] or "", int(r["id"])))
            st.cache_data.clear()   # standings group by district via cached queries
            st.success("Districts saved.")


# ── games: type ───────────────────────────────────────────────────────────────
with t_games:
    st.caption("The full games table is too big to load at once, so filter to a "
               "group first, then set the type individually or in bulk. Playoffs "
               "often start the same day league-wide — filter by date (and class), "
               "then **Apply to all shown → Playoff**.")
    _gc1, _gc2, _gc3 = st.columns(3)
    _gteams = [r["name"] for r in query("SELECT name FROM teams ORDER BY name")]
    _gteam = _gc1.selectbox("Team", ["All teams"] + _gteams, key="su_g_team")
    _gclasses = [r["class"] for r in query(
        "SELECT DISTINCT class FROM teams WHERE class IS NOT NULL AND class!='' "
        "ORDER BY class")]
    _gclass = _gc2.selectbox("Class", ["All classes"] + _gclasses, key="su_g_class")
    _gdate = _gc3.text_input("On/after date", key="su_g_date",
                             placeholder="YYYY-MM-DD").strip()

    _w, _p = [], []
    if _gteam != "All teams":
        _w.append("(t1.name=? OR t2.name=?)"); _p += [_gteam, _gteam]
    if _gclass != "All classes":
        _w.append("(t1.class=? OR t2.class=?)"); _p += [_gclass, _gclass]
    if _gdate:
        _w.append("g.date>=?"); _p.append(_gdate)
    _wsql = ("WHERE " + " AND ".join(_w)) if _w else ""
    grows = query(
        f"""SELECT g.id, g.date, t1.name AS home, t2.name AS away, g.game_type
            FROM games g JOIN teams t1 ON t1.id=g.team1_id
                         JOIN teams t2 ON t2.id=g.team2_id
            {_wsql} ORDER BY g.date DESC LIMIT 500""", tuple(_p))
    if not grows:
        st.info("No games match — widen the filters." if _w
                else "No games yet. Add games in the Input Hub first.")
    else:
        _capped = len(grows) == 500
        st.caption(f"{len(grows)} game(s)"
                   + (" — first 500; narrow the filter to reach more" if _capped
                      else "") + ("" if _w else " · most recent"))
        _bc1, _bc2 = st.columns([2, 1])
        _bulk = _bc1.selectbox("Bulk-set all shown to", GAME_TYPES, key="su_g_bulk")
        if _bc2.button("Apply to all shown", key="su_g_bulk_btn"):
            for r in grows:
                execute("UPDATE games SET game_type=? WHERE id=?",
                        (_bulk, int(r["id"])))
            st.cache_data.clear()
            st.success(f"Set {len(grows)} game(s) to {_bulk}.")
            st.rerun()
        ed = st.data_editor(
            pd.DataFrame(grows), hide_index=True, width="stretch", key="su_games",
            column_config={
                "id": None,
                "date": st.column_config.TextColumn("Date", disabled=True),
                "home": st.column_config.TextColumn("Home", disabled=True),
                "away": st.column_config.TextColumn("Away", disabled=True),
                "game_type": st.column_config.SelectboxColumn(
                    "Type", options=GAME_TYPES),
            })
        if st.button("Save game types", key="su_games_save"):
            for _, r in ed.iterrows():
                execute("UPDATE games SET game_type=? WHERE id=?",
                        (r["game_type"] or "Regular", int(r["id"])))
            st.cache_data.clear()   # game tags feed cached rankings / dashboards
            st.success("Game types saved.")


# ── entered box scores (untracked games) ──────────────────────────────────────
with t_box:
    st.caption("Enter a box score for a game you didn't track play-by-play. It "
               "feeds possessions, PPP, ORtg & the four factors — and sets the "
               "final score so records & rankings count it — but never marks the "
               "game 'tracked' (lineup / play-type stats need the Game Tracker).")
    _g = query("""SELECT g.id, g.date, t1.name n1, t2.name n2,
                         g.team1_id, g.team2_id, g.tracked
                  FROM games g JOIN teams t1 ON t1.id=g.team1_id
                               JOIN teams t2 ON t2.id=g.team2_id
                  ORDER BY g.date DESC LIMIT 400""")
    _untr = [g for g in _g if not g["tracked"]]
    if not _untr:
        empty_state("No untracked games",
                    "Every game is tracked, or none added yet. Add games in the "
                    "Input Hub.")
    else:
        gsel = st.selectbox(
            "Game", _untr, key="mb_game",
            format_func=lambda g: (f"{g['date']} · {g['n1']} vs {g['n2']}"
                                   + ("  ✓ entered" if MB.has_manual(g["id"]) else "")))
        existing = MB.load_manual_box(gsel["id"])
        _UP = [c.upper() for c in MB.STAT_COLS]

        for _tid, _tnm in ((gsel["team1_id"], gsel["n1"]),
                           (gsel["team2_id"], gsel["n2"])):
            st.markdown(f"**{_tnm}**")
            roster = query(
                "SELECT id, number, name FROM players WHERE team_id=? AND "
                "archived=0 ORDER BY number", (_tid,))
            if not roster:
                st.caption("No players on this team — add them in the Input Hub.")
                continue
            ex = {r["player_id"]: r for r in existing.get(_tid, [])}
            base = pd.DataFrame([{
                "player_id": p["id"], "#": p["number"], "Player": p["name"],
                **{c.upper(): (ex.get(p["id"], {}).get(c, 0) or 0)
                   for c in MB.STAT_COLS},
            } for p in roster])
            ed = st.data_editor(
                base, hide_index=True, width="stretch",
                key=f"mb_ed_{gsel['id']}_{_tid}",
                column_config={
                    "player_id": None,
                    "#": st.column_config.NumberColumn("#", disabled=True),
                    "Player": st.column_config.TextColumn("Player", disabled=True),
                    "MIN": st.column_config.NumberColumn(
                        "MIN", min_value=0.0, max_value=200.0),
                    **{c.upper(): st.column_config.NumberColumn(
                           c.upper(), min_value=0, max_value=200, step=1)
                       for c in MB.STAT_COLS if c != "min"}})
            if st.button(f"Save {_tnm} box", key=f"mb_save_{gsel['id']}_{_tid}"):
                bad = []
                for _, r in ed.iterrows():
                    _v = lambda c: 0 if pd.isna(r[c]) else int(r[c])
                    if (_v("FGM") > _v("FGA") or _v("TPM") > _v("TPA")
                            or _v("FTM") > _v("FTA") or _v("TPM") > _v("FGM")
                            or _v("TPA") > _v("FGA")):
                        bad.append(f"#{r['#']} {r['Player']}")
                if bad:
                    st.error("Not saved — makes exceed attempts (or 3P exceed FG) "
                             "for: " + ", ".join(bad) + ". Fix those rows and save "
                             "again.")
                else:
                    rows = [{"player_id": int(r["player_id"]),
                             **{c: r[c.upper()] for c in MB.STAT_COLS}}
                            for _, r in ed.iterrows()]
                    MB.save_manual_box(gsel["id"], _tid, rows)
                    box = MB.load_manual_box(gsel["id"])
                    if gsel["team1_id"] in box and gsel["team2_id"] in box:
                        _hp = MB.team_totals(box[gsel["team1_id"]])["PTS"]
                        _ap = MB.team_totals(box[gsel["team2_id"]])["PTS"]
                        execute("UPDATE games SET home_score=?, away_score=? WHERE id=?",
                                (_hp, _ap, gsel["id"]))
                    st.cache_data.clear()   # box feeds records / rankings / four factors
                    st.success(f"{_tnm} box saved.")

        if MB.has_manual(gsel["id"]):
            st.divider()
            MB.render_manual_box(gsel["id"], accent=ACCENT)
