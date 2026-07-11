import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from database.db import (query, execute, normalize_date,
                         delete_or_archive_player, delete_or_archive_official)
from helpers.ui import page_chrome, page_header, lab_hero as _lab_hero, seg as _seg
import helpers.seasons as SZ
import helpers.auth as AUTH
import helpers.change_requests as CR

_cfg, ACCENT = page_chrome("Input Hub")
_me = AUTH.current_user()
_is_admin = (_me or {}).get("role") == "admin"


def _gated_delete(table, target_id, label):
    """Admin deletes now; a coach's delete is queued for admin approval (the row
    stays live until accepted). Returns True if the caller should delete now."""
    if CR.should_delete_now(_me):
        return True
    CR.request_delete(table, target_id, label, _me.get("email", ""))
    st.toast(f"Delete of {label} sent to the admin for approval 🕓")
    return False

_lab_hero("Input Hub", phase="BUILD",
          sub="Log games, manage rosters & officials, and seed the data the "
              "whole app runs on.")

# Render messages queued before an st.rerun (an inline message would be wiped).
for _level, _msg in st.session_state.pop("_flash", []):
    {"success": st.success, "warning": st.warning, "error": st.error}[_level](_msg)

CLASS_OPTIONS  = ["B2", "B1", "A", "2A", "3A", "4A", "5A", "6A", "N/A"]
GENDER_OPTIONS = ["M", "F"]
HA_OPTIONS     = ["Home", "Away", "Neutral"]
# US state codes for the team/official State tag (default OK — Oklahoma app).
# Oklahoma + its neighbours float to the top; the rest follow alphabetically.
STATE_OPTIONS  = ["OK", "TX", "KS", "AR", "MO", "NM", "CO", "LA", "NE",
                  "AL","AK","AZ","CA","CT","DC","DE","FL","GA","HI","IA","ID",
                  "IL","IN","KY","MA","MD","ME","MI","MN","MS","MT","NC","ND",
                  "NH","NJ","NV","NY","OH","OR","PA","RI","SC","SD","TN","UT",
                  "VA","VT","WA","WI","WV","WY"]

EDITOR_HELP = ("**Click any cell to edit.** Add with the **＋** row at the bottom. "
               "To delete: tick a row's checkbox and press the **Delete** key, then **Save Changes** "
               "(no Delete key on a tablet? use the **Remove** control below).")


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
    rows = query("SELECT id, name, class, gender, state FROM teams ORDER BY name")
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id","name","class","gender","state"])

def load_players_for(team_id, season=SZ.ACTIVE):
    """A team's roster for one season — the live roster (archived=0) for the
    current season, or the season-stamped rows for a past one (roster_clause),
    so archived seasons are editable with the same grid."""
    rc, rp = SZ.roster_clause(season)
    rows = query(
        f"SELECT id, name, number, grad_year, height, wingspan, weight, handedness "
        f"FROM players WHERE team_id=? AND {rc} ORDER BY name",
        (team_id, *rp)
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["id","name","number","grad_year","height","wingspan","weight","handedness"])

def load_games_for_team(team_id):
    """Load all games involving team_id from the games table, presented from that team's POV."""
    rows = query("""
        SELECT g.id,
            CASE WHEN g.team1_id=? THEN t2.name ELSE t1.name END AS opponent,
            g.date,
            CASE WHEN g.neutral=1 THEN 'Neutral'
                 WHEN g.team1_id=? THEN 'Home' ELSE 'Away' END   AS home_away,
            g.location,
            CASE WHEN g.team1_id=? THEN g.home_score ELSE g.away_score END AS team_score,
            CASE WHEN g.team1_id=? THEN g.away_score ELSE g.home_score END AS opp_score,
            g.tracked, g.video_url
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE g.team1_id=? OR g.team2_id=?
    """, (team_id,)*6)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["id","opponent","date","home_away","location","team_score","opp_score","tracked","video_url"])
    if not df.empty:
        df["tracked"] = df["tracked"].astype(bool)
    return sort_by_date(df, ascending=False)

def load_officials():
    rows = query("SELECT id, name, official_id, state FROM officials WHERE archived=0 ORDER BY name")
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id","name","official_id","state"])

def load_games(season=None):
    """Games for the editor, optionally scoped to one season. `season` None or
    '__all__' loads every season; a label ('Current' / '2025-2026') filters to it,
    so the table doesn't balloon with every past season's games at once."""
    where = "" if season in (None, "__all__") else "WHERE g.season = ?"
    params = () if season in (None, "__all__") else (season,)
    rows = query(f"""
        SELECT g.id, t1.name AS team1, t2.name AS team2,
               g.date, g.location, g.home_score, g.away_score, g.neutral,
               g.tracked, g.video_url
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        {where}
    """, params)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["id","team1","team2","date","location","home_score","away_score",
                 "neutral","tracked","video_url"])
    if not df.empty:
        df["neutral"] = df["neutral"].astype(bool)
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


def _sortable(df, editor_key, cols, default=0):
    """Sort control for an editable table. Returns the df sorted + index-reset so
    apply_delta's positional iloc still lines up. Uses a static editor key; when
    the sort changes it RESETS that editor (drops any pending edits) — mirroring
    the team-change reset — so stale row indices can never misapply on Save."""
    if df.empty:
        return df
    sc1, sc2 = st.columns([3, 1])
    col = sc1.selectbox("Sort by", cols, index=default, key=f"{editor_key}_scol")
    asc = sc2.radio("Order", ["A→Z", "Z→A"], index=0,
                    key=f"{editor_key}_sdir", horizontal=True) == "A→Z"
    cur = (col, asc)
    if st.session_state.get(f"{editor_key}_sprev") != cur:
        st.session_state.pop(editor_key, None)
        st.session_state[f"{editor_key}_sprev"] = cur
    return df.sort_values(col, ascending=asc, kind="stable",
                          na_position="last").reset_index(drop=True)


def _norm_score(v):
    """Editor score cell → int or None (NumberColumn can yield float / NaN)."""
    if v is None:
        return None
    try:
        if v != v:          # NaN
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _live_game(gid):
    """Current DB row (tracked flag + PBP-derived scores) for a game, or None.

    Tracked games own their score — it is derived from play-by-play in the Game
    Tracker — so the manual editors here must not overwrite it. Used by
    upd_game / upd_sched to guard a tracked game's score.
    """
    rows = query("SELECT tracked, home_score, away_score FROM games WHERE id=?",
                 (int(gid),))
    return rows[0] if rows else None


# ── session cache (keyed so changing the team selector resets the editor) ──────

def get_orig(cache_key, loader):
    if cache_key not in st.session_state:
        st.session_state[cache_key] = loader()
    return st.session_state[cache_key]

def invalidate(*keys):
    for k in keys:
        st.session_state.pop(k, None)

def flash(level, msg):
    """Queue a message to render at the top of the page after the next st.rerun."""
    st.session_state.setdefault("_flash", []).append((level, msg))


# ══════════════════════════════════════════════════════════════════════════════
#  NEW SEASON
# ══════════════════════════════════════════════════════════════════════════════

if _is_admin:
    with st.expander("New Season", expanded=False):
        _cur_label = SZ.active_label()
        st.warning(
            f"Current season: **{_cur_label}**. Rolling over archives all current "
            "players, schedules **and games** under that label, then starts a fresh "
            "season. Nothing is deleted — past seasons become an open archive (free, "
            "full depth, visible to everyone), and current-season stats stop blending "
            "with last year's."
        )
        new_name = st.text_input("New season name (e.g. 2026-2027)",
                                 placeholder="2026-2027", key="season_label_input")
        _nm = new_name.strip()

        # ── carry-forward preview (Tier 3): grad_year auto-graduates seniors; everyone
        #    else carries to the new season pre-linked by identity. Coach overrides the
        #    edges (a returner who LEFT, a senior who's STAYING) before confirming. ──
        _plan = SZ.rollover_plan(_cur_label)
        _gy = _plan["grad_year"]
        _tn = {t["id"]: t["name"] for t in query("SELECT id, name FROM teams")}
        _ret_lbl = {r["id"]: f"#{r['number']} {r['name']} · {_tn.get(r['team_id'], '?')}"
                    for r in _plan["returning"]}
        _grad_lbl = {r["id"]: f"#{r['number']} {r['name']} · {_tn.get(r['team_id'], '?')} "
                     f"· '{str(r['grad_year'])[-2:]}" for r in _plan["graduating"]}
        st.caption(
            f"Graduating class **{_gy if _gy else '—'}** — will **carry {len(_ret_lbl)}** "
            f"returning player(s) forward (identity-linked) and **graduate "
            f"{len(_grad_lbl)}** senior(s). Set grad years on the Players tab to drive "
            "this; NULL grad year = carries forward.")
        _left = st.multiselect(
            "Returning players who LEFT the program (don't carry)", list(_ret_lbl),
            format_func=lambda i: _ret_lbl[i], key="roll_left")
        _stay = st.multiselect(
            "Seniors actually STAYING (keep them)", list(_grad_lbl),
            format_func=lambda i: _grad_lbl[i], key="roll_stay")
        _carry = (set(_ret_lbl) - set(_left)) | set(_stay)

        confirm = st.checkbox("I understand — roll over to a new season", key="new_season_confirm")
        can_go = confirm and bool(_nm) and _nm != _cur_label
        if st.button("Start New Season", type="primary", disabled=not can_go, key="new_season_btn"):
            # seasons.execute_rollover stamps+archives the outgoing season, then
            # re-creates the carry set as fresh CURRENT rows linked to each person.
            _n = SZ.execute_rollover(_nm, sorted(_carry), outgoing_label=_cur_label)
            invalidate("_players_orig", "players_editor", "_sched_orig", "sched_editor")
            flash("success", f"Archived '{_cur_label}'. Now playing **{_nm}** — carried "
                  f"{_n} returning player(s) forward (identity-linked); seniors graduated. "
                  "Add any transfers-in on the Players tab + link them under Returning "
                  "players.")
            st.cache_data.clear()
            st.rerun()

    # ── Returning players: link this season's roster to last season's identities ──
    # (Tier 3, ML_LAYER_ROADMAP) so year-over-year development tracks once two tracked
    # seasons exist. Dormant until the first New Season rollover creates archived rows.
    with st.expander("🔗 Returning players — link to last season", expanded=False):
        import helpers.identity as IDN
        st.caption("Match this season's players to the same person last season so "
                   "year-over-year development tracks once you've played two tracked "
                   "seasons. Suggestions match by name + number — confirm or override "
                   "each. Stays empty until your first New Season rollover.")
        _id_teams = query("SELECT id, name FROM teams ORDER BY name")
        if not _id_teams:
            st.info("Add teams first.")
        else:
            _idt = st.selectbox("Team", _id_teams, format_func=lambda t: t["name"],
                                key="idn_team_sel")
            _sug = IDN.suggest_matches(_idt["id"])
            if not _sug:
                st.info("No current-season players on this team yet.")
            elif not any(s["candidates"] or s["linked_to"] for s in _sug):
                st.info("No prior-season players to link yet — roll over a season "
                        "(New Season above), then returning players appear here.")
            else:
                _choice = {}
                for s in _sug:
                    cand = list(s["candidates"])
                    _keys = {c["identity_key"] for c in cand}
                    if s["linked_to"] and s["linked_to"] not in _keys:
                        cand.insert(0, {"identity_key": s["linked_to"], "name": s["name"],
                                        "number": s["number"], "season": "linked",
                                        "score": 1.0})
                    vals = ["__new__"] + [str(c["identity_key"]) for c in cand]
                    labmap = {"__new__": "➕ New player (no prior season)"}
                    for c in cand:
                        labmap[str(c["identity_key"])] = (
                            f"{c['name']} #{c['number']} · {c['season']} "
                            f"(match {c['score'] * 100:.0f}%)")
                    if s["linked_to"]:
                        _default = str(s["linked_to"])
                    elif cand and cand[0]["score"] >= 0.85:
                        _default = str(cand[0]["identity_key"])
                    else:
                        _default = "__new__"
                    _idx = vals.index(_default) if _default in vals else 0
                    _choice[s["pid"]] = st.selectbox(
                        f"#{s['number']} {s['name']}", vals, index=_idx,
                        format_func=lambda v, _m=labmap: _m[v],
                        key=f"idn_{_idt['id']}_{s['pid']}")
                if st.button("Save links", type="primary", key="idn_save"):
                    _linked = 0
                    for pid, v in _choice.items():
                        if v == "__new__":
                            IDN.unlink(pid)
                        else:
                            IDN.link(pid, int(v))
                            _linked += 1
                    st.cache_data.clear()
                    flash("success", f"Linked {_linked} returning player(s) to last season.")
                    st.rerun()

            # ── transferred in? league-wide lookup (a player from another team last
            #    season). Coach-typed so it never false-links same names; once linked,
            #    the player's development history follows them across schools. ──
            st.markdown("---")
            st.markdown("**Transferred in?** Link a player who was on another team last "
                        "season — their history follows them.")
            _xq = st.text_input("Search last season's players by name", key="idn_xfer_q",
                                placeholder="player name")
            if _xq.strip():
                _hits = IDN.transfer_search(_xq, exclude_team_id=_idt["id"])
                if not _hits:
                    st.caption("No archived players on other teams match that name.")
                else:
                    _cur_opts = {s["pid"]: f"#{s['number']} {s['name']}" for s in _sug}
                    for h in _hits:
                        xc = st.columns([3, 2, 1])
                        xc[0].caption(f"{h['name']} #{h['number']} · {h['team']} · "
                                      f"{h['season']} ({h['score'] * 100:.0f}%)")
                        if _cur_opts:
                            _tgt = xc[1].selectbox(
                                "to", list(_cur_opts), format_func=lambda p: _cur_opts[p],
                                key=f"xfer_tgt_{h['identity_key']}",
                                label_visibility="collapsed")
                            if xc[2].button("Link", key=f"xfer_link_{h['identity_key']}"):
                                IDN.link(_tgt, h["identity_key"])
                                st.cache_data.clear()
                                flash("success", f"Linked transfer {h['name']}.")
                                st.rerun()
                        else:
                            xc[1].caption("(add to this roster first)")

else:
    st.info("🔒 **New Season rollover** and **returning-player linking** are "
            "admin-only — they archive the whole league season and link cross-season "
            "identities, so a single trusted hand runs them. Ask your admin.")
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# Lazy sections via a segmented control (not st.tabs): st.tabs snaps back to the
# first tab on every full rerun (each Save fires st.rerun()), which kept bouncing
# the coach back to Teams. A keyed segmented_control persists the selection in
# session_state, so a Save leaves you on the section you were editing — and only
# the chosen section's queries run each rerun.
_HUB_TABS = ["Teams", "Players", "Games", "Team Schedule", "Officials",
             "Season Archive"]
_hubview = _seg("Section", _HUB_TABS, default="Teams", key="hub_section") or "Teams"


# ══════════════════════════════════════════════════════════════════════════════
#  TEAMS
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Teams":
    st.caption(EDITOR_HELP)
    orig = get_orig("_teams_orig", load_teams)
    orig = _sortable(orig, "teams_editor", ["name", "class", "gender", "state"])
    display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(columns=["name","class","gender","state"])

    st.data_editor(
        display,
        key="teams_editor",
        num_rows="dynamic",
        width="stretch",
        column_config={
            "name":   st.column_config.TextColumn("Team Name", required=True),
            "class":  st.column_config.SelectboxColumn("Class",  options=CLASS_OPTIONS,  required=True),
            "gender": st.column_config.SelectboxColumn("Gender", options=GENDER_OPTIONS, required=True),
            "state":  st.column_config.SelectboxColumn("State",  options=STATE_OPTIONS, default="OK"),
        },
    )

    if st.button("Save Changes", key="save_teams", type="primary"):
        def ins_team(r):
            if not r.get("name", "").strip():
                return
            # gender is a required column, but Streamlit's data_editor doesn't
            # enforce required= on newly-added rows — a blank here used to
            # silently default to 'M', saving Girls teams as Boys. Reject it.
            g = (r.get("gender") or "").strip()
            if g not in ("M", "F"):
                raise ValueError(
                    f"Team '{r['name'].strip()}': pick a gender before saving.")
            execute("INSERT OR IGNORE INTO teams (name, class, gender, state) VALUES (?,?,?,?)",
                    (r["name"].strip(), r.get("class","N/A"), g,
                     (r.get("state") or "OK")))
        def upd_team(r):
            execute("UPDATE teams SET name=?, class=?, gender=?, state=? WHERE id=?",
                    (r["name"].strip(), r["class"], r["gender"], (r.get("state") or "OK"), r["id"]))
        def del_team(r):
            if _gated_delete("teams", r["id"], f"team '{r.get('name','?')}'"):
                execute("DELETE FROM teams WHERE id=?", (r["id"],))

        errs = apply_delta("teams_editor", orig, ins_team, upd_team, del_team)
        if errs:
            st.error("\n".join(errs))  # no rerun — keep the rejected rows visible
        else:
            flash("success", "Saved!")
            invalidate("_teams_orig", "teams_editor")
            st.cache_data.clear()
            st.rerun()

    # ── Retroactive class — fix a team's class for a PAST season ──────────────
    # The editor above sets the LIVE (current-season) class. Classes re-align
    # each year, so a past-season view reads team_class_history (snapshotted at
    # each rollover). This lets a coach correct a wrong past-season class without
    # touching the current one. Appears only once a season has been archived.
    _past = SZ.archived_labels()
    if _past:
        with st.expander("🗄️ Retroactive class — change a team's class for a past season"):
            st.caption("Classes re-align each year, so this edits the class a team "
                       "played in during a PAST season only — the current-season "
                       "class stays as set in the table above.")
            _rc1, _rc2 = st.columns([1, 2])
            _rc_season = _rc1.selectbox("Season", _past, key="rc_season")
            _teams_rc = query("SELECT id, name, gender FROM teams ORDER BY name")
            _rc_team = _rc2.selectbox(
                "Team", _teams_rc, key="rc_team",
                format_func=lambda r: f"{r['name']} ({'Girls' if r['gender']=='F' else 'Boys'})")
            if _rc_team is not None:
                _cur = SZ.team_class(_rc_team["id"], _rc_season)
                _idx = CLASS_OPTIONS.index(_cur) if _cur in CLASS_OPTIONS else len(CLASS_OPTIONS) - 1
                _rc_class = st.selectbox(
                    f"Class in {_rc_season}", CLASS_OPTIONS, index=_idx, key="rc_class",
                    help=f"Currently recorded as **{_cur or 'N/A'}** for {_rc_season}.")
                if st.button("Save past-season class", key="rc_save", type="primary"):
                    execute("INSERT OR REPLACE INTO team_class_history "
                            "(team_id, season, class) VALUES (?,?,?)",
                            (_rc_team["id"], _rc_season, _rc_class))
                    flash("success",
                          f"{_rc_team['name']} recorded as {_rc_class} in {_rc_season}.")
                    st.cache_data.clear()
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYERS  (standalone team picker)
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Players":
    tnames = team_names()
    if not tnames:
        st.warning("Add at least one team first.")
    else:
        _pc1, _pc2 = st.columns([2, 1])
        selected_team = _pc1.selectbox("Select Team", tnames, key="player_team_sel")
        tm = team_map()
        team_id = tm[selected_team]

        # Season picker — the current season edits the live roster; a past season
        # edits that season's archived rows directly (names, numbers, grad years),
        # and NEW rows land on that season's roster (retro-add, identity-linked).
        _pszn_opts = SZ.season_options()
        if len(_pszn_opts) > 1:
            _pszn_lbls = [l for _v, l in _pszn_opts]
            _pszn_sel = _pc2.selectbox(
                "Season", _pszn_lbls, index=0, key="players_szn",
                help="Pick a past season to edit that season's roster — fix a "
                     "name or grad year, or add a player who was there. Edits to "
                     "a name/grad year sync to the same player's other seasons.")
            roster_season = next(v for v, l in _pszn_opts if l == _pszn_sel)
        else:
            roster_season = SZ.ACTIVE
        _is_cur_roster = SZ.is_current(roster_season)

        # Reset editor when team OR season changes
        prev_key = "_players_prev_team"
        _sel_key = (selected_team, roster_season)
        if st.session_state.get(prev_key) != _sel_key:
            invalidate("_players_orig", "players_editor")
            st.session_state[prev_key] = _sel_key

        if not _is_cur_roster:
            st.caption(f"📅 Editing the **{roster_season}** roster. New rows join "
                       "that season (and auto-link to the same player on other "
                       "seasons); name & grad-year edits sync across seasons.")
        st.caption(EDITOR_HELP)
        orig = get_orig("_players_orig", lambda: load_players_for(team_id, roster_season))
        display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(
            columns=["name","number","grad_year","height","wingspan","weight","handedness"])

        st.data_editor(
            display,
            key="players_editor",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "name":     st.column_config.TextColumn("Player Name", required=True),
                "number":   st.column_config.NumberColumn("Number",      min_value=0, max_value=999, step=1),
                "grad_year": st.column_config.NumberColumn(
                    "Grad yr", min_value=2000, max_value=2100, step=1, format="%d",
                    default=SZ.default_grad_year(roster_season),
                    help="Class year (e.g. 2026). New players default to season end "
                         "+3 (a freshman) so nobody ghosts on rosters for years — "
                         "correct it if they're older. Seniors auto-graduate on New "
                         "Season rollover; everyone else carries forward pre-linked."),
                "height":   st.column_config.NumberColumn("Height (in)", min_value=0.0, step=0.5),
                "wingspan": st.column_config.NumberColumn("Wingspan (in)", min_value=0.0, step=0.5),
                "weight":   st.column_config.NumberColumn("Weight (lbs)", min_value=0.0, step=1.0),
                "handedness": st.column_config.SelectboxColumn(
                    "Hand", options=["right", "left"], default="right",
                    help="Shooting hand — drives dominant- vs weak-side shot splits."),
            },
        )

        if st.button("Save Changes", key="save_players", type="primary"):
            import helpers.identity as IDN
            skipped_dupes = []
            def _gy(r):
                v = r.get("grad_year")
                try:
                    return int(v) if v not in (None, "") and v == v else None
                except (ValueError, TypeError):
                    return None
            def ins_player(r):
                name = r.get("name", "").strip()
                if not name:
                    return
                # dedupe: same name already on this team's roster for this season
                rc, rp = SZ.roster_clause(roster_season)
                if query(f"SELECT id FROM players WHERE team_id=? AND name=? AND {rc}",
                         (team_id, name, *rp)):
                    skipped_dupes.append(name)
                    return
                # auto grad year: season end +3 (a freshman) when left blank
                gy = _gy(r) or SZ.default_grad_year(roster_season)
                # a past season's new row is stamped onto THAT season (archived so
                # it never surfaces in current-season pickers)
                szn = SZ.ACTIVE if _is_cur_roster else str(roster_season)
                pid = execute(
                    "INSERT INTO players (team_id, name, number, grad_year, height, wingspan, weight, handedness, season, archived) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (team_id, name, int(r.get("number") or 0), gy,
                     r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None,
                     "left" if r.get("handedness") == "left" else "right",
                     szn, 0 if _is_cur_roster else 1)
                )
                # retro-add: link to the same person on other seasons (unique
                # same-name match on this team) so they never dupe as two people
                if not _is_cur_roster:
                    IDN.auto_link(pid)
            def upd_player(r):
                execute(
                    "UPDATE players SET team_id=?, name=?, number=?, grad_year=?, height=?, wingspan=?, weight=?, handedness=? WHERE id=?",
                    (team_id, r["name"].strip(), int(r.get("number") or 0), _gy(r),
                     r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None,
                     "left" if r.get("handedness") == "left" else "right",
                     r["id"])
                )
                # name / grad year are person-level — sync the edit to the same
                # player's rows on other seasons (identity-linked)
                IDN.propagate_person_fields(r["id"])
            def del_player(r):
                if _gated_delete("players", r["id"], f"player '{r.get('name','?')}'"):
                    if delete_or_archive_player(r["id"]) == "archived":
                        st.toast(f"{r.get('name','Player')} has tracked game "
                                 "history — archived (stats kept), not deleted.")

            errs = apply_delta("players_editor", orig, ins_player, upd_player, del_player)
            if errs:
                st.error("\n".join(errs))  # no rerun — keep the rejected rows visible
            else:
                flash("success", "Saved!")
                for _nm in skipped_dupes:
                    flash("warning", f"Skipped adding **{_nm}** — already on this "
                          f"team's {SZ.active_label() if _is_cur_roster else roster_season} "
                          "roster.")
                invalidate("_players_orig", "players_editor")
                st.cache_data.clear()
                st.rerun()

        # Explicit delete — the data_editor's row-delete needs a keyboard Delete key
        # (absent on tablets), so give a discoverable button path too.
        st.divider()
        with st.expander("🗑️ Remove a player"):
            if orig.empty:
                st.caption("No players on this team yet.")
            else:
                del_opts = {f"#{int(r['number'])} {r['name']}": int(r["id"])
                            for _, r in orig.iterrows()}
                pick = st.selectbox("Player to remove", list(del_opts.keys()),
                                    key="del_player_pick")
                st.caption("A player with tracked game history is archived (stats kept), "
                           "not permanently deleted.")
                if st.button("Delete player", key="del_player_btn"):
                    pid = del_opts[pick]
                    if _gated_delete("players", pid, f"player '{pick}'"):
                        outcome = delete_or_archive_player(pid)
                        flash("success", f"{pick} archived (tracked history kept)."
                              if outcome == "archived" else f"{pick} deleted.")
                    invalidate("_players_orig", "players_editor")
                    st.cache_data.clear()
                    st.rerun()

        # One-shot cross-season sync (admin): fix rosters renamed AFTER a rollover
        # (the archived rows kept the old names — e.g. a Current-roster rename that
        # should read back onto last season). Edits made from now on sync live;
        # this backfills the ones made before that existed.
        if _is_admin:
            with st.expander("🔁 Sync names & grad years across seasons (all teams)"):
                st.caption("For every identity-linked player, copies the newest "
                           "season's **name** (and freshest known **grad year**) "
                           "onto their older-season rows. Run once to clean up "
                           "renames done before cross-season sync existed.")
                if st.button("Run sync", key="idn_sync_btn"):
                    import helpers.identity as IDN
                    _n = IDN.sync_person_fields()
                    st.cache_data.clear()
                    flash("success", f"Synced {_n} past-season player row(s).")
                    st.rerun()

        # Transfer a player to another team — reassign their roster (team_id).
        # Past games stay attributed to the old team (events carry shooter_team_id),
        # and cross-season development history follows via identity. Same-gender
        # targets only (a Boys player can't move to a Girls roster). Current
        # season only — a past season's team_id is history, not a roster move.
        with st.expander("🔄 Transfer a player to another team"):
            if not _is_cur_roster:
                st.caption("Transfers apply to the current season's roster — a past "
                           "season's team is history. Switch Season to "
                           f"{SZ.active_label()} (current) to move a player.")
            elif orig.empty:
                st.caption("No players on this team to transfer.")
            else:
                _gmap = {r["name"]: r["gender"]
                         for r in query("SELECT name, gender FROM teams")}
                _dests = [t for t in tnames
                          if t != selected_team
                          and _gmap.get(t) == _gmap.get(selected_team)]
                _xopts = {f"#{int(r['number'])} {r['name']}": int(r["id"])
                          for _, r in orig.iterrows()}
                _xpick = st.selectbox("Player to transfer", list(_xopts),
                                      key="xfer_player_pick")
                if not _dests:
                    st.caption("No other same-gender team to transfer to yet.")
                else:
                    _xdest = st.selectbox("Move to team", _dests, key="xfer_dest_team")
                    st.caption("Moves the player to the new roster. Past games stay "
                               "with the old team; new games count for the new one. "
                               "Their development history follows them.")
                    if st.button("Transfer player", key="xfer_btn"):
                        execute("UPDATE players SET team_id=? WHERE id=?",
                                (tm[_xdest], _xopts[_xpick]))
                        invalidate("_players_orig", "players_editor")
                        st.cache_data.clear()
                        flash("success", f"Transferred {_xpick} to {_xdest}.")
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  GAMES
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Games":
    tnames = team_names()
    if not tnames:
        st.warning("Add at least one team first.")
    else:
        # Season filter for the LIST below (separate from the "Season for new
        # games" stamp-picker under the editor). Only shown once an archive
        # exists; defaults to the active season so the table stays lean. Changing
        # it resets the editor so pending edits can't misapply to another season.
        _gv_opts = SZ.season_options() + [("__all__", "All seasons")]
        if len(_gv_opts) > 2:
            _gv_lbls = [l for _v, l in _gv_opts]
            _gv_sel = st.selectbox(
                "Show games from", _gv_lbls, index=0, key="games_view_szn",
                help="Filters the table below to one season (or all). The 'Season "
                     "for new games' picker under the editor controls what NEW "
                     "rows are stamped with.")
            _gv_val = next(v for v, l in _gv_opts if l == _gv_sel)
        else:
            _gv_val = SZ.ACTIVE
        if st.session_state.get("_games_view_prev") != _gv_val:
            invalidate("_games_orig", "games_editor")
            st.session_state["_games_view_prev"] = _gv_val

        st.caption(EDITOR_HELP)
        orig = get_orig("_games_orig", lambda: load_games(_gv_val))
        orig = _sortable(orig, "games_editor",
                         ["date", "team1", "team2", "location",
                          "home_score", "away_score"])
        display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(
            columns=["team1","team2","date","location","home_score","away_score",
                     "neutral","tracked"])
        # DateColumn needs real dates; DB stores ISO strings (normalize_date on save).
        display["date"] = pd.to_datetime(display["date"], errors="coerce").dt.date

        st.data_editor(
            display,
            key="games_editor",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "team1":      st.column_config.SelectboxColumn("Home Team",    options=tnames, required=True),
                "team2":      st.column_config.SelectboxColumn("Away Team",    options=tnames, required=True),
                "date":       st.column_config.DateColumn("Date", format="YYYY-MM-DD", required=True),
                "location":   st.column_config.TextColumn("Location"),
                "home_score": st.column_config.NumberColumn("Home Score",      min_value=0, step=1),
                "away_score": st.column_config.NumberColumn("Away Score",      min_value=0, step=1),
                "neutral":    st.column_config.CheckboxColumn("Neutral", default=False, help="Neutral floor — no home-court. Home/Away Team still label the two sides for scoring; this just flags the venue."),
                "tracked":    st.column_config.CheckboxColumn("Tracked",       default=False),
                "video_url":  st.column_config.TextColumn("Film URL", help="Hudl / YouTube / NFHS link. Clickable from the Team Dashboard schedule — opens in a new tab."),
            },
        )

        # Season for NEW rows: Auto = infer from each game's date (Oct 1 cutoff —
        # a past-dated game lands in its real season automatically); or force one.
        _szn_opts = ["Auto (from date)"] + [v for v, _l in SZ.season_options()]
        _szn_pick = st.selectbox(
            "Season for new games", _szn_opts, index=0, key="games_szn",
            help="Auto stamps each new game with the season its DATE falls in "
                 "(seasons run Oct 1 – Apr 30), so back-dated games go straight "
                 "into their real season and never mix into current stats.")
        if st.button("Save Changes", key="save_games", type="primary"):
            tm = team_map()
            skipped = []
            def ins_game(r):
                if r.get("team1") and r.get("team1") == r.get("team2"):
                    skipped.append(f"Skipped a game with '{r['team1']}' as both home "
                                   "and away — pick two different teams.")
                    return
                if r.get("date","").strip() and r.get("team1") and r.get("team2"):
                    _d = normalize_date(r["date"])
                    _szn = SZ.resolve_new_game_season(
                        _d, None if _szn_pick.startswith("Auto") else _szn_pick)
                    execute(
                        "INSERT INTO games (team1_id, team2_id, date, location, home_score, away_score, neutral, tracked, video_url, season) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (tm[r["team1"]], tm[r["team2"]], _d,
                         r.get("location") or None, r.get("home_score") or None,
                         r.get("away_score") or None,
                         int(bool(r.get("neutral", False))),
                         int(bool(r.get("tracked", False))),
                         (r.get("video_url") or "").strip(), _szn)
                    )
            def upd_game(r):
                if r.get("team1") and r.get("team1") == r.get("team2"):
                    skipped.append(f"Skipped game #{int(r['id'])} — '{r['team1']}' "
                                   "can't play itself; pick two different teams.")
                    return
                live = _live_game(r["id"])
                if live and live["tracked"]:
                    # Tracked games own their PBP-derived score — keep it. Apply
                    # only non-score edits; reject a manual score / untrack change.
                    if (_norm_score(r.get("home_score")) != live["home_score"]
                            or _norm_score(r.get("away_score")) != live["away_score"]
                            or not bool(r.get("tracked", True))):
                        raise ValueError(
                            f"Game #{int(r['id'])} is play-by-play tracked — its score "
                            "and tracked flag are owned by the Game Tracker, so this "
                            "edit was not saved. Untrack it there to score it by hand.")
                    execute(
                        "UPDATE games SET team1_id=?, team2_id=?, date=?, location=?, neutral=?, video_url=? WHERE id=?",
                        (tm[r["team1"]], tm[r["team2"]], normalize_date(r["date"]),
                         r.get("location") or None,
                         int(bool(r.get("neutral", False))),
                         (r.get("video_url") or "").strip(), int(r["id"])))
                    return
                execute(
                    "UPDATE games SET team1_id=?, team2_id=?, date=?, location=?, home_score=?, away_score=?, neutral=?, tracked=?, video_url=? WHERE id=?",
                    (tm[r["team1"]], tm[r["team2"]], normalize_date(r["date"]),
                     r.get("location") or None, r.get("home_score") or None,
                     r.get("away_score") or None,
                     int(bool(r.get("neutral", False))),
                     int(bool(r.get("tracked", False))),
                     (r.get("video_url") or "").strip(), r["id"])
                )
            def del_game(r):
                if _gated_delete("games", r["id"],
                                 f"game {r.get('team1','?')} vs {r.get('team2','?')}"):
                    execute("DELETE FROM games WHERE id=?", (r["id"],))

            errs = apply_delta("games_editor", orig, ins_game, upd_game, del_game)
            if errs:
                st.error("\n".join(errs))  # no rerun — keep the rejected rows visible
                for _w in skipped:
                    st.warning(_w)
            else:
                flash("success", "Saved!")
                for _w in skipped:
                    flash("warning", _w)
                # Same games table as the Team Schedule tab — drop its cached
                # editor frame too so it can't save stale rows back over this edit.
                invalidate("_games_orig", "games_editor", "_sched_orig", "sched_editor")
                st.cache_data.clear()
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  TEAM SCHEDULE  — same games table as the Games tab, team POV
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Team Schedule":
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
        # DateColumn needs real dates; DB stores ISO strings (normalize_date on save).
        display["date"] = pd.to_datetime(display["date"], errors="coerce").dt.date

        # Opponents are every team except the selected one
        opp_options = [t for t in tnames if t != selected_team]

        st.data_editor(
            display,
            key="sched_editor",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "opponent":   st.column_config.SelectboxColumn("Opponent",       options=opp_options, required=True),
                "date":       st.column_config.DateColumn("Date", format="YYYY-MM-DD", required=True),
                "home_away":  st.column_config.SelectboxColumn("Home / Away",    options=HA_OPTIONS,  required=True),
                "location":   st.column_config.TextColumn("Location"),
                "team_score": st.column_config.NumberColumn("Team Score",        min_value=0, step=1),
                "opp_score":  st.column_config.NumberColumn("Opp Score",         min_value=0, step=1),
                "tracked":    st.column_config.CheckboxColumn("Tracked",         default=False),
                "video_url":  st.column_config.TextColumn("Film URL", help="Hudl / YouTube / NFHS link. Clickable from the Team Dashboard schedule — opens in a new tab."),
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
                # Away → team in the away slot; Home/Neutral → team in the home
                # slot (Neutral just flags the venue, scores map the same as Home).
                if ha == "Away":
                    t1, t2, h_sc, a_sc = opp_id, team_id, o_score, t_score
                else:
                    t1, t2, h_sc, a_sc = team_id, opp_id, t_score, o_score
                neu = 1 if ha == "Neutral" else 0
                _d = normalize_date(date)
                execute(
                    "INSERT INTO games (team1_id, team2_id, date, location, home_score, away_score, neutral, tracked, video_url, season) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (t1, t2, _d, r.get("location") or None, h_sc, a_sc, neu, tracked,
                     (r.get("video_url") or "").strip(),
                     SZ.resolve_new_game_season(_d))
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
                if ha == "Away":
                    t1, t2, h_sc, a_sc = opp_id, team_id, o_score, t_score
                else:                       # Home or Neutral → team in home slot
                    t1, t2, h_sc, a_sc = team_id, opp_id, t_score, o_score
                neu = 1 if ha == "Neutral" else 0
                live = _live_game(r["id"])
                if live and live["tracked"]:
                    # Tracked games own their PBP-derived score — keep it.
                    if (_norm_score(h_sc) != live["home_score"]
                            or _norm_score(a_sc) != live["away_score"]
                            or not tracked):
                        raise ValueError(
                            f"Game #{int(r['id'])} is play-by-play tracked — its score "
                            "and tracked flag are owned by the Game Tracker, so this "
                            "edit was not saved. Untrack it there to score it by hand.")
                    execute(
                        "UPDATE games SET team1_id=?, team2_id=?, date=?, location=?, neutral=?, video_url=? WHERE id=?",
                        (t1, t2, normalize_date(date), r.get("location") or None, neu,
                         (r.get("video_url") or "").strip(), int(r["id"])))
                    return
                execute(
                    "UPDATE games SET team1_id=?, team2_id=?, date=?, location=?, home_score=?, away_score=?, neutral=?, tracked=?, video_url=? WHERE id=?",
                    (t1, t2, normalize_date(date), r.get("location") or None, h_sc, a_sc, neu, tracked,
                     (r.get("video_url") or "").strip(), r["id"])
                )

            def del_sched(r):
                if _gated_delete("games", r["id"],
                                 f"scheduled game {r.get('team1','?')} vs {r.get('team2','?')}"):
                    execute("DELETE FROM games WHERE id=?", (r["id"],))

            errs = apply_delta("sched_editor", orig, ins_sched, upd_sched, del_sched)
            if errs:
                st.error("\n".join(errs))  # no rerun — keep the rejected rows visible
            else:
                flash("success", "Saved!")
                invalidate("_sched_orig", "sched_editor", "_games_orig", "games_editor")
                st.cache_data.clear()
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  OFFICIALS
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Officials":
    st.caption(EDITOR_HELP)
    orig = get_orig("_officials_orig", load_officials)
    orig = _sortable(orig, "officials_editor", ["name", "official_id", "state"])
    display = orig.drop(columns=["id"]) if not orig.empty else pd.DataFrame(
        columns=["name", "official_id", "state"])

    st.data_editor(
        display,
        key="officials_editor",
        num_rows="dynamic",
        width="stretch",
        column_config={
            "name":        st.column_config.TextColumn("Official Name", required=True),
            "official_id": st.column_config.NumberColumn("Official ID", required=True, step=1),
            "state":       st.column_config.SelectboxColumn("State", options=STATE_OPTIONS, default="OK"),
        },
    )

    if st.button("Save Changes", key="save_officials", type="primary"):
        def ins_official(r):
            if r.get("name", "").strip() and r.get("official_id") is not None:
                # Re-adding a previously-archived ref (same official_id) revives them
                # (un-archive); the stored name is kept, matching the tracker API.
                execute(
                    "INSERT INTO officials (name, official_id, state) VALUES (?,?,?) "
                    "ON CONFLICT(official_id) DO UPDATE SET archived=0",
                    (r["name"].strip(), int(r["official_id"]), (r.get("state") or "OK")))
        def upd_official(r):
            execute("UPDATE officials SET name=?, official_id=?, state=? WHERE id=?",
                    (r["name"].strip(), int(r["official_id"]), (r.get("state") or "OK"), r["id"]))
        def del_official(r):
            if _gated_delete("officials", r["id"], f"official '{r.get('name','?')}'"):
                if delete_or_archive_official(r["id"]) == "archived":
                    st.toast(f"{r.get('name','Official')} has game history — "
                             "archived (stats kept), not deleted.")

        errs = apply_delta("officials_editor", orig, ins_official, upd_official, del_official)
        if errs:
            st.error("\n".join(errs))  # no rerun — keep the rejected rows visible
        else:
            flash("success", "Saved!")
            invalidate("_officials_orig", "officials_editor")
            st.cache_data.clear()
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  SEASON ARCHIVE
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Season Archive":
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
        st.caption("Read-only view. To EDIT a past season's roster (fix a name, "
                   "add a player who was there), use the **Players** section and "
                   "pick the season there; past games are editable under **Games** "
                   "with its season filter.")

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
                        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

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
                        st.dataframe(df, width="stretch", hide_index=True)
