import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from database.db import (query, execute, normalize_date,
                         delete_or_archive_player, delete_or_archive_official,
                         delete_or_block_team, team_history_counts)
from helpers.ui import (page_chrome, page_header, lab_hero as _lab_hero,
                        seg as _seg, empty_state)
import helpers.seasons as SZ
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.change_requests as CR
import helpers.identity as IDN
import helpers.officials as OFF
import helpers.ui as _uimod          # clear_data() — see its docstring
from helpers.stats import player_label as _PLBL

_cfg, ACCENT = page_chrome("Input Hub")
_me = AUTH.current_user()
_is_admin = (_me or {}).get("role") == "admin"

# ── ownership scope ───────────────────────────────────────────────────────────
# Until 2026-09-12 this page had no entitlement import at all. Its only gate was
# _gated_delete below, which queues DELETES for admin approval — so every UPDATE
# and INSERT was league-wide open, and any signed-in coach could rename any team,
# edit any player or rewrite any game's score. Roster & District gated the SAME
# writes hard, which meant a player's grad year was scoped on one page and
# unscoped on the other: ownership was decided by which page you opened.
#
# These two helpers are the ones that page used, ported verbatim so the two
# cannot drift. They are applied in two places, and the split is deliberate:
#
#   * READS default to your own teams, with an explicit "show the whole league"
#     switch — a coach still needs to SEE the league to enter an opponent.
#   * WRITES are gated with no switch. A row outside your scope is rejected by
#     _guard_team / _guard_game with a sentence, and apply_delta's per-row
#     try/except means the rest of a pasted batch still saves.
#
# INSERTS stay open on purpose. Creating a team, a game or an official is how a
# league gets entered, and closing it would break the only path a coach has to
# add an opponent. Editing somebody else's existing row is the hole this closes.
_OWN = ENT._own_teams(_me)


def _team_scope(alias="", col="id"):
    """(sql, params) restricting a query to the coach's own teams. Empty for
    admin. Callers AND this into their WHERE."""
    if _is_admin:
        return "", ()
    pre = f"{alias}." if alias else ""
    if not _OWN:
        return f"{pre}{col} IS NULL", ()      # no team assigned → nothing editable
    ph = ",".join("?" * len(_OWN))
    return f"{pre}{col} IN ({ph})", tuple(_OWN)


def _game_scope(a1="t1", a2="t2"):
    """(sql, params) restricting a games query to games one of the coach's own
    teams plays in."""
    if _is_admin:
        return "", ()
    if not _OWN:
        return "1=0", ()
    ph = ",".join("?" * len(_OWN))
    return f"({a1}.id IN ({ph}) OR {a2}.id IN ({ph}))", tuple(_OWN) * 2


def _owns(team_id) -> bool:
    return _is_admin or (team_id is not None and int(team_id) in set(_OWN))


def _guard_team(team_id, label=""):
    """Raise unless this team is the coach's to change. apply_delta turns the
    message into a row-level error and saves the rest of the batch."""
    if _owns(team_id):
        return
    raise ValueError(
        f"{label or 'That team'} isn't one of your teams, so the edit wasn't "
        "saved. You can add new rows, and edit your own — ask the admin for "
        "anything else.")


def _guard_game(game_id, label=""):
    """Raise unless one of the coach's teams actually plays in this game."""
    if _is_admin:
        return
    r = query("SELECT team1_id, team2_id FROM games WHERE id=?", (int(game_id),))
    if r and (_owns(r[0]["team1_id"]) or _owns(r[0]["team2_id"])):
        return
    raise ValueError(
        f"{label or 'That game'} doesn't involve one of your teams, so the edit "
        "wasn't saved. Scores and schedules belong to the teams that played.")


def _league_switch(key):
    """The read-scope switch. Admin sees everything already; a coach with no
    team assigned would otherwise meet an empty page with no explanation."""
    if _is_admin:
        return True
    if not _OWN:
        st.info("No team is assigned to you yet, so there is nothing here that "
                "is yours to edit. You can still see the league and add new "
                "rows — ask the admin to assign your team on the Settings page.")
        return True
    return st.toggle("Show the whole league", key=key, value=False,
                     help="Other teams' rows are visible so you can enter an "
                          "opponent, but only your own are editable.")


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

#: Coaching fields that used to live on Roster & District. Kept as module
#: constants with the same names that page used, so a reader following either
#: history lands in one place.
POSITIONS = ["", "PG", "SG", "SF", "PF", "C"]
AVAIL = ["Active", "Questionable", "Out", "Injured", "Suspended"]
GAME_TYPES = ["Regular", "District", "Rivalry", "Playoff", "Showcase", "Tournament"]

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

TEAM_COLS = ["id", "name", "class", "gender", "state", "district"]
#: One roster row, whole. `position` and `availability` used to live on Roster &
#: District and the rest here, which split one players row across two pages by
#: column — with grad_year and handedness editable on BOTH. One grid now.
PLAYER_COLS = ["id", "name", "number", "position", "availability", "grad_year",
               "height", "wingspan", "weight", "handedness"]


def load_teams(scoped=False):
    where, params = _team_scope() if scoped else ("", ())
    rows = query("SELECT id, name, class, gender, state, district FROM teams"
                 + (f" WHERE {where}" if where else "") + " ORDER BY name", params)
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=TEAM_COLS)

def load_players_for(team_id, season=SZ.ACTIVE):
    """A team's roster for one season — the live roster (archived=0) for the
    current season, or the season-stamped rows for a past one (roster_clause),
    so archived seasons are editable with the same grid."""
    rc, rp = SZ.roster_clause(season)
    rows = query(
        f"SELECT id, name, number, position, availability, grad_year, height, "
        f"wingspan, weight, handedness "
        f"FROM players WHERE team_id=? AND {rc} ORDER BY name",
        (team_id, *rp)
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=PLAYER_COLS)

SCHED_COLS = ["id", "opponent", "date", "home_away", "location", "team_score",
              "opp_score", "game_type", "tracked", "video_url"]


def load_games_for_team(team_id, season="__all__"):
    """Load games involving team_id, presented from that team's POV — the same
    `games` rows the league grid shows, pivoted. Both POVs are one editor now."""
    rows = query("""
        SELECT g.id,
            CASE WHEN g.team1_id=? THEN t2.name ELSE t1.name END AS opponent,
            g.date,
            CASE WHEN g.neutral=1 THEN 'Neutral'
                 WHEN g.team1_id=? THEN 'Home' ELSE 'Away' END   AS home_away,
            g.location,
            CASE WHEN g.team1_id=? THEN g.home_score ELSE g.away_score END AS team_score,
            CASE WHEN g.team1_id=? THEN g.away_score ELSE g.home_score END AS opp_score,
            g.game_type, g.tracked, g.video_url
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        WHERE (g.team1_id=? OR g.team2_id=?)
          AND (? = '__all__' OR g.season = ?)
    """, (team_id,)*6 + (str(season), str(season)))
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=SCHED_COLS)
    if not df.empty:
        df["tracked"] = df["tracked"].astype(bool)
    return sort_by_date(df, ascending=False)

def load_officials():
    rows = query("SELECT id, name, official_id, state FROM officials WHERE archived=0 ORDER BY name")
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id","name","official_id","state"])

GAME_COLS = ["id", "team1", "team2", "date", "location", "home_score",
             "away_score", "neutral", "game_type", "tracked", "video_url"]


def load_games(season=None, scoped=False):
    """Games for the editor, optionally scoped to one season. `season` None or
    '__all__' loads every season; a label ('Current' / '2025-2026') filters to it,
    so the table doesn't balloon with every past season's games at once.
    `scoped` further narrows to games the coach's own teams play in."""
    w, params = [], []
    if season not in (None, "__all__"):
        w.append("g.season = ?"); params.append(season)
    if scoped:
        _gs, _gp = _game_scope()
        if _gs:
            w.append(_gs); params += list(_gp)
    where = ("WHERE " + " AND ".join(w)) if w else ""
    rows = query(f"""
        SELECT g.id, t1.name AS team1, t2.name AS team2,
               g.date, g.location, g.home_score, g.away_score, g.neutral,
               g.game_type, g.tracked, g.video_url
        FROM games g
        JOIN teams t1 ON t1.id = g.team1_id
        JOIN teams t2 ON t2.id = g.team2_id
        {where}
    """, tuple(params))
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=GAME_COLS)
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
            _uimod.clear_data()
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
                        _PLBL(s), vals, index=_idx,
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
                    _uimod.clear_data()
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
                    _cur_opts = {s["pid"]: _PLBL(s) for s in _sug}
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
                                _uimod.clear_data()
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
# "Team Schedule" is gone as a section — it was the SAME `games` rows in a
# one-team pivot, with a strictly weaker insert (no duplicate-matchup check, no
# season picker), and the two editors invalidated each other's cached frame
# because they knew they collided. It is now a POV toggle inside Games, over one
# insert path.
_HUB_TABS = ["Teams", "Players", "Games", "Officials", "Season Archive"]
_hubview = _seg("Section", _HUB_TABS, default="Teams", key="hub_section") or "Teams"


# ══════════════════════════════════════════════════════════════════════════════
#  TEAMS
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Teams":
    st.caption(EDITOR_HELP)
    # Empty-current-season trap: the table below edits the LIVE (current-season)
    # class, but if the active season has no games yet, every ranking/dashboard
    # the coach views is scoped to the most recent ARCHIVE, whose class is read
    # from team_class_history — so a table edit "does nothing." Point them to the
    # Retroactive editor (and auto-open it) when that's the situation.
    _cur_games = query("SELECT COUNT(*) AS n FROM games WHERE season=?", (SZ.ACTIVE,))
    _cur_empty = (_cur_games[0]["n"] if _cur_games else 0) == 0 and bool(SZ.archived_labels())
    if _cur_empty:
        st.info(
            f"The current season (**{SZ.active_label()}**) has no games yet, so your "
            "rankings and dashboards are still showing last season's archive. The "
            "**Class** column below sets the *current-season* class — to change the "
            "class shown in those archive views, use **🗄️ Retroactive class** below.")
    _t_all = _league_switch("teams_all")
    if st.session_state.get("_teams_scope_prev") != _t_all:
        invalidate("_teams_orig", "teams_editor")
        st.session_state["_teams_scope_prev"] = _t_all
    orig = get_orig("_teams_orig", lambda: load_teams(scoped=not _t_all))
    # Search — carried over from Roster & District, which had it and this grid
    # did not. On a 1,448-team book it is the difference between editing your
    # district and scrolling for it.
    _tq = st.text_input("Search teams", key="teams_q",
                        placeholder="team name, class, or district…").strip().lower()
    if _tq and not orig.empty:
        _tm = pd.Series(False, index=orig.index)
        for _c in ("name", "class", "district"):
            _tm = _tm | orig[_c].astype(str).str.lower().str.contains(_tq, na=False)
        orig = orig[_tm].reset_index(drop=True)
        st.caption(f"{len(orig)} team(s) match — clear the box to edit or add others.")
    orig = _sortable(orig, "teams_editor",
                     ["name", "class", "gender", "state", "district"])
    display = (orig.drop(columns=["id"]) if not orig.empty
               else pd.DataFrame(columns=[c for c in TEAM_COLS if c != "id"]))

    st.data_editor(
        display,
        key="teams_editor",
        # A filtered view cannot take new rows: apply_delta maps an added row by
        # POSITION into `orig`, and `orig` here is a subset, so an insert while
        # searching would be applied against the wrong frame.
        num_rows="fixed" if _tq else "dynamic",
        width="stretch",
        column_config={
            "name":   st.column_config.TextColumn("Team Name", required=True),
            "class":  st.column_config.SelectboxColumn("Class",  options=CLASS_OPTIONS,  required=True),
            "gender": st.column_config.SelectboxColumn("Gender", options=GENDER_OPTIONS, required=True),
            "state":  st.column_config.SelectboxColumn("State",  options=STATE_OPTIONS, default="OK"),
            "district": st.column_config.TextColumn(
                "District", help="Free text, e.g. '3A-4' — groups the standings."),
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
            _guard_team(r["id"], f"'{r.get('name', '?')}'")
            execute("UPDATE teams SET name=?, class=?, gender=?, state=?, "
                    "district=? WHERE id=?",
                    (r["name"].strip(), r["class"], r["gender"],
                     (r.get("state") or "OK"), (r.get("district") or ""), r["id"]))
        def del_team(r):
            _guard_team(r["id"], f"'{r.get('name', '?')}'")
            # NOT a plain DELETE: teams cascade into games → game_events →
            # game_event_lineup, so removing a team while tidying the list used
            # to silently destroy every game it ever played. delete_or_block_team
            # refuses when there is anything to lose and reports what.
            if not _gated_delete("teams", r["id"], f"team '{r.get('name','?')}'"):
                return
            if delete_or_block_team(r["id"]) == "blocked":
                c = team_history_counts(r["id"])
                raise ValueError(
                    f"Team '{r.get('name','?')}' can't be deleted — it would take "
                    f"{c['games']} game(s) and {c['events']} tracked event(s) with "
                    f"it. Rename the team instead, or delete its games first.")

        errs = apply_delta("teams_editor", orig, ins_team, upd_team, del_team)
        if errs:
            st.error("\n".join(errs))  # no rerun — keep the rejected rows visible
        else:
            flash("success", "Saved!")
            invalidate("_teams_orig", "teams_editor")
            _uimod.clear_data()
            st.rerun()

    # ── Retroactive class — fix a team's class for a PAST season ──────────────
    # The editor above sets the LIVE (current-season) class. Classes re-align
    # each year, so a past-season view reads team_class_history (snapshotted at
    # each rollover). This lets a coach correct a wrong past-season class without
    # touching the current one. Appears only once a season has been archived.
    _past = SZ.archived_labels()
    if _past:
        with st.expander("🗄️ Retroactive class — change a team's class for a past season",
                         expanded=_cur_empty):
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
                    _uimod.clear_data()
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYERS  (standalone team picker)
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Players":
    tnames = team_names()
    if not tnames:
        st.warning("Add at least one team first.")
    else:
        # Own teams first, and only them unless the league switch is on: a
        # roster is the most team-owned thing in the book, and the old picker
        # offered all 1,448 with every one of them editable.
        _p_all = _league_switch("players_all")
        _own_names = [r["name"] for r in query(
            "SELECT name FROM teams WHERE id IN (%s) ORDER BY name"
            % ",".join("?" * len(_OWN)), tuple(_OWN))] if _OWN else []
        _p_opts = tnames if (_p_all or not _own_names) else _own_names
        _pc1, _pc2 = st.columns([2, 1])
        selected_team = _pc1.selectbox("Select Team", _p_opts, key="player_team_sel")
        tm = team_map()
        team_id = tm[selected_team]
        if not _owns(team_id):
            st.caption(f"👁 Viewing **{selected_team}** — not one of your teams, "
                       "so saves on existing players will be refused.")

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
        display = (orig.drop(columns=["id"]) if not orig.empty
                   else pd.DataFrame(columns=[c for c in PLAYER_COLS if c != "id"]))

        st.data_editor(
            display,
            key="players_editor",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "name":     st.column_config.TextColumn("Player Name", required=True),
                "number":   st.column_config.NumberColumn("Number",      min_value=0, max_value=999, step=1),
                # position + availability came from Roster & District. They power
                # the depth chart; nothing else on this page reads them.
                "position": st.column_config.SelectboxColumn(
                    "Position", options=POSITIONS,
                    help="Drives the depth chart on the Team Dashboard."),
                "availability": st.column_config.SelectboxColumn(
                    "Status", options=AVAIL, default="Active",
                    help="Out / Injured / Suspended drop a player from the "
                         "depth chart and the lineup builder's default five."),
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
                    "INSERT INTO players (team_id, name, number, position, "
                    "availability, grad_year, height, wingspan, weight, "
                    "handedness, season, archived) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (team_id, name, int(r.get("number") or 0),
                     r.get("position") or "", r.get("availability") or "Active", gy,
                     r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None,
                     "left" if r.get("handedness") == "left" else "right",
                     szn, 0 if _is_cur_roster else 1)
                )
                # retro-add: link to the same person on other seasons (unique
                # same-name match on this team) so they never dupe as two people
                if not _is_cur_roster:
                    IDN.auto_link(pid)
            def upd_player(r):
                _guard_team(team_id, f"'{selected_team}'")
                execute(
                    "UPDATE players SET team_id=?, name=?, number=?, position=?, "
                    "availability=?, grad_year=?, height=?, wingspan=?, weight=?, "
                    "handedness=? WHERE id=?",
                    (team_id, r["name"].strip(), int(r.get("number") or 0),
                     r.get("position") or "", r.get("availability") or "Active", _gy(r),
                     r.get("height") or None, r.get("wingspan") or None, r.get("weight") or None,
                     "left" if r.get("handedness") == "left" else "right",
                     r["id"])
                )
                # name / grad year are person-level — sync the edit to the same
                # player's rows on other seasons (identity-linked)
                IDN.propagate_person_fields(r["id"])
            def del_player(r):
                _guard_team(team_id, f"'{selected_team}'")
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
                _uimod.clear_data()
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
                    _uimod.clear_data()
                    st.rerun()

        # ── Import a whole roster at once — CSV upload or pasted block. Engine
        # (parse + dedup plan) lives in helpers/roster_import.py; this glue
        # applies the plan through the SAME insert/update path as the editor
        # above (season stamping, identity auto-link, grad-year default).
        with st.expander("📥 Import roster — CSV upload or paste"):
            import helpers.roster_import as RIMP
            st.caption(
                "Bring a whole roster in at once — upload a CSV or paste rows "
                "straight from a spreadsheet/program page. Columns read: "
                "**name, number, height, grad year** (header row optional, "
                "extra columns ignored, heights like `5'11` are fine). Preview "
                "shows what each row will do before anything saves.")
            _rup = st.file_uploader("Roster CSV", type=["csv", "txt", "tsv"],
                                    key="rimp_file")
            _rblk = st.text_area(
                "…or paste rows here", key="rimp_paste", height=120,
                placeholder="Jane Smith, 12, 5'9, 2027\nKate Jones, 23, 5'11, 2026")
            _rtext = ""
            if _rup is not None:
                _rtext = _rup.getvalue().decode("utf-8-sig", errors="replace")
            elif (_rblk or "").strip():
                _rtext = _rblk
            if _rtext.strip():
                _rrows, _rwarns = RIMP.parse_roster(_rtext)
                for _w in _rwarns[:8]:
                    st.warning(_w)
                if not _rrows:
                    st.info("Nothing importable found — need at least a name "
                            "per row.")
                else:
                    _rc2, _rp2 = SZ.roster_clause(roster_season)
                    _rexist = [dict(x) for x in query(
                        f"SELECT id, name, number, height, grad_year FROM players "
                        f"WHERE team_id=? AND {_rc2}", (team_id, *_rp2))]
                    _rplan = RIMP.plan_import(_rrows, _rexist)
                    _ric = {"add": "➕ add", "update": "✏️ update",
                            "skip": "⏭️ skip"}
                    st.dataframe(pd.DataFrame([{
                        "Action": _ric[p["verdict"]],
                        "Player": p["row"]["name"],
                        "#": p["row"]["number"],
                        "Ht (in)": p["row"]["height"],
                        "Grad": p["row"]["grad_year"],
                        "Why": p["reason"],
                    } for p in _rplan]), hide_index=True, width="stretch")
                    _radd = sum(1 for p in _rplan if p["verdict"] == "add")
                    _rupd = sum(1 for p in _rplan if p["verdict"] == "update")
                    _rskp = len(_rplan) - _radd - _rupd
                    if not (_radd or _rupd):
                        st.caption("Nothing to import — every row is already on "
                                   "this roster.")
                    elif st.button(f"Import — add {_radd}, update {_rupd}"
                                   + (f", skip {_rskp}" if _rskp else ""),
                                   type="primary", key="rimp_go"):
                        import helpers.identity as IDN
                        _rszn = SZ.ACTIVE if _is_cur_roster else str(roster_season)
                        for p in _rplan:
                            r = p["row"]
                            if p["verdict"] == "add":
                                _rgy = r["grad_year"] or SZ.default_grad_year(roster_season)
                                _rpid = execute(
                                    "INSERT INTO players (team_id, name, number, "
                                    "grad_year, height, wingspan, weight, handedness, "
                                    "season, archived) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                    (team_id, r["name"], int(r["number"] or 0), _rgy,
                                     r["height"], None, None, "right",
                                     _rszn, 0 if _is_cur_roster else 1))
                                if not _is_cur_roster:
                                    IDN.auto_link(_rpid)
                            elif p["verdict"] == "update":
                                _rsets = ", ".join(f"{k}=?" for k in p["changes"])
                                execute(f"UPDATE players SET {_rsets} WHERE id=?",
                                        (*p["changes"].values(), p["pid"]))
                                if "grad_year" in p["changes"]:
                                    IDN.propagate_person_fields(p["pid"])
                        invalidate("_players_orig", "players_editor")
                        _uimod.clear_data()
                        flash("success",
                              f"Roster imported — added {_radd}, updated {_rupd}"
                              + (f", skipped {_rskp} already-rostered" if _rskp
                                 else "") + ".")
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
                    _uimod.clear_data()
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
                        _uimod.clear_data()
                        flash("success", f"Transferred {_xpick} to {_xdest}.")
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  GAMES
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#  GAMES — shared preamble for both points of view
# ══════════════════════════════════════════════════════════════════════════════
# One `games` table, two ways to look at it: the league grid (home team / away
# team) and one team's schedule (opponent / home-away). They used to be two
# SECTIONS with two insert paths, and the second was a strictly weaker copy —
# no duplicate-matchup check and no season picker, so adding a game from the
# team view could double-book a matchup the league grid would have refused.
# Both now run through _ins_game / _upd_game below.
_games_pov = "League"
_gv_val = SZ.ACTIVE
if _hubview == "Games":
    _gpc1, _gpc2 = st.columns([2, 3])
    with _gpc1:
        _games_pov = _seg("Point of view", ["League", "One team"],
                          default="League", key="games_pov") or "League"
    # Season filter for the LIST below (separate from the "Season for new
    # games" stamp-picker under the editor). Only shown once an archive
    # exists; defaults to the active season so the table stays lean. Changing
    # it resets the editor so pending edits can't misapply to another season.
    _gv_opts = SZ.season_options() + [("__all__", "All seasons")]
    if len(_gv_opts) > 2:
        _gv_lbls = [l for _v, l in _gv_opts]
        _gv_sel = _gpc2.selectbox(
            "Show games from", _gv_lbls, index=0, key="games_view_szn",
            help="Filters the table below to one season (or all). The 'Season "
                 "for new games' picker under the editor controls what NEW "
                 "rows are stamped with.")
        _gv_val = next(v for v, l in _gv_opts if l == _gv_sel)
    if st.session_state.get("_games_view_prev") != (_gv_val, _games_pov):
        invalidate("_games_orig", "games_editor", "_sched_orig", "sched_editor")
        st.session_state["_games_view_prev"] = (_gv_val, _games_pov)

    # Season for NEW rows: Auto = infer from each game's date (Oct 1 cutoff —
    # a past-dated game lands in its real season automatically); or force one.
    # Shared by both POVs; the team view never had this picker at all.
    _szn_opts = ["Auto (from date)"] + [v for v, _l in SZ.season_options()]
    _szn_pick = st.selectbox(
        "Season for new games", _szn_opts, index=0, key="games_szn",
        help="Auto stamps each new game with the season its DATE falls in "
             "(seasons run Oct 1 – Apr 30), so back-dated games go straight "
             "into their real season and never mix into current stats.")

    _skipped = []

    def _dup_matchup(d, t1, t2):
        """True when this matchup is already on the schedule for that day.

        ux_games_matchup (db.py) forbids a second IMPORTED row for one matchup
        on one date, in either orientation. Checked HERE so the coach reads a
        sentence instead of a raw constraint name — and so the rest of a pasted
        batch still saves, which is what apply_delta's per-row try/except is
        for. Q13: teams play once a day.
        """
        return bool(query(
            "SELECT id FROM games WHERE date=? AND tracked_by=''"
            " AND ((team1_id=? AND team2_id=?) OR (team1_id=? AND team2_id=?))",
            (d, t1, t2, t2, t1)))

    def _ins_game(t1, t2, date, location, h_sc, a_sc, neutral, tracked,
                  video_url, game_type, n1="", n2=""):
        """The ONE insert. Both points of view reach the table through here."""
        if t1 == t2:
            _skipped.append(f"Skipped a game with '{n1 or t1}' as both home and "
                            "away — pick two different teams.")
            return
        _d = normalize_date(date)
        if _dup_matchup(_d, t1, t2):
            _skipped.append(
                f"Skipped {n1 or t1} vs {n2 or t2} on {_d} — that matchup is "
                "already on the schedule for that day (teams play once a day). "
                "Edit the existing row instead.")
            return
        _szn = SZ.resolve_new_game_season(
            _d, None if _szn_pick.startswith("Auto") else _szn_pick)
        execute(
            "INSERT INTO games (team1_id, team2_id, date, location, home_score, "
            "away_score, neutral, tracked, video_url, game_type, season) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (t1, t2, _d, location or None, h_sc, a_sc, int(bool(neutral)),
             int(bool(tracked)), (video_url or "").strip(),
             game_type or "Regular", _szn))

    def _upd_game(gid, t1, t2, date, location, h_sc, a_sc, neutral, tracked,
                  video_url, game_type):
        """The ONE update, with both guards a game edit needs: ownership, and
        the tracked game's PBP-derived score."""
        gid = int(gid)
        _guard_game(gid, f"Game #{gid}")
        live = _live_game(gid)
        if live and live["tracked"]:
            # Tracked games own their PBP-derived score — keep it. Apply only
            # non-score edits; reject a manual score / untrack change.
            if (_norm_score(h_sc) != live["home_score"]
                    or _norm_score(a_sc) != live["away_score"]
                    or not bool(tracked)):
                raise ValueError(
                    f"Game #{gid} is play-by-play tracked — its score and "
                    "tracked flag are owned by the Game Tracker, so this edit "
                    "was not saved. Untrack it there to score it by hand.")
            execute(
                "UPDATE games SET team1_id=?, team2_id=?, date=?, location=?, "
                "neutral=?, video_url=?, game_type=? WHERE id=?",
                (t1, t2, normalize_date(date), location or None,
                 int(bool(neutral)), (video_url or "").strip(),
                 game_type or "Regular", gid))
            return
        execute(
            "UPDATE games SET team1_id=?, team2_id=?, date=?, location=?, "
            "home_score=?, away_score=?, neutral=?, tracked=?, video_url=?, "
            "game_type=? WHERE id=?",
            (t1, t2, normalize_date(date), location or None, h_sc, a_sc,
             int(bool(neutral)), int(bool(tracked)), (video_url or "").strip(),
             game_type or "Regular", gid))

    def _del_game_row(gid, label):
        _guard_game(gid, label)
        if _gated_delete("games", gid, label):
            execute("DELETE FROM games WHERE id=?", (gid,))

    def _after_games_save(errs):
        """Both editors write the same rows, so BOTH cached frames are dropped —
        otherwise the other view can save stale rows back over this edit."""
        if errs:
            st.error("\n".join(errs))  # no rerun — keep rejected rows visible
            for _w in _skipped:
                st.warning(_w)
            return
        flash("success", "Saved!")
        for _w in _skipped:
            flash("warning", _w)
        invalidate("_games_orig", "games_editor", "_sched_orig", "sched_editor")
        _uimod.clear_data()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  GAMES — league point of view
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Games" and _games_pov == "League":
    tnames = team_names()
    if not tnames:
        st.warning("Add at least one team first.")
    else:
        _g_all = _league_switch("games_all")
        if st.session_state.get("_games_scope_prev") != _g_all:
            invalidate("_games_orig", "games_editor")
            st.session_state["_games_scope_prev"] = _g_all

        st.caption(EDITOR_HELP)
        orig = get_orig("_games_orig",
                        lambda: load_games(_gv_val, scoped=not _g_all))
        orig = _sortable(orig, "games_editor",
                         ["date", "team1", "team2", "location",
                          "home_score", "away_score", "game_type"])
        display = (orig.drop(columns=["id"]) if not orig.empty
                   else pd.DataFrame(columns=[c for c in GAME_COLS if c != "id"]))
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
                # game_type came from Roster & District. It tags the game for
                # standings and the district/playoff splits.
                "game_type":  st.column_config.SelectboxColumn(
                    "Type", options=GAME_TYPES, default="Regular",
                    help="District / Playoff drive the standings splits and the "
                         "record breakdown on the Team Dashboard."),
                "tracked":    st.column_config.CheckboxColumn("Tracked",       default=False),
                "video_url":  st.column_config.TextColumn("Film URL", help="Hudl / YouTube / NFHS link. Clickable from the Team Dashboard schedule — opens in a new tab."),
            },
        )

        # Bulk game-type set — carried over from Roster & District, the one
        # genuinely useful thing its games tab had. Playoffs often start the
        # same day league-wide: filter the table by season, then set them all.
        with st.expander("⚡ Set the type on every game shown"):
            st.caption("Applies to the rows in the table above, as filtered. "
                       "Narrow with the season picker first.")
            _bc1, _bc2 = st.columns([2, 1])
            _bulk = _bc1.selectbox("Set all shown to", GAME_TYPES, key="games_bulk")
            if _bc2.button("Apply to all shown", key="games_bulk_btn",
                           disabled=orig.empty):
                _n, _refused = 0, 0
                for _gid in orig["id"].tolist():
                    try:
                        _guard_game(int(_gid))
                    except ValueError:
                        _refused += 1
                        continue
                    execute("UPDATE games SET game_type=? WHERE id=?",
                            (_bulk, int(_gid)))
                    _n += 1
                _uimod.clear_data()
                invalidate("_games_orig", "games_editor")
                flash("success", f"Set {_n} game(s) to {_bulk}."
                      + (f" {_refused} skipped — not your teams' games."
                         if _refused else ""))
                st.rerun()

        if st.button("Save Changes", key="save_games", type="primary"):
            tm = team_map()

            def ins_game(r):
                if not (r.get("date", "").strip() and r.get("team1")
                        and r.get("team2")):
                    return
                _ins_game(tm[r["team1"]], tm[r["team2"]], r["date"],
                          r.get("location"), r.get("home_score") or None,
                          r.get("away_score") or None, r.get("neutral", False),
                          r.get("tracked", False), r.get("video_url"),
                          r.get("game_type"), r["team1"], r["team2"])

            def upd_game(r):
                if r.get("team1") and r.get("team1") == r.get("team2"):
                    _skipped.append(
                        f"Skipped game #{int(r['id'])} — '{r['team1']}' can't "
                        "play itself; pick two different teams.")
                    return
                _upd_game(r["id"], tm[r["team1"]], tm[r["team2"]], r["date"],
                          r.get("location"), r.get("home_score") or None,
                          r.get("away_score") or None, r.get("neutral", False),
                          r.get("tracked", False), r.get("video_url"),
                          r.get("game_type"))

            def del_game(r):
                _del_game_row(r["id"], f"game {r.get('team1', '?')} vs "
                                       f"{r.get('team2', '?')}")

            _after_games_save(
                apply_delta("games_editor", orig, ins_game, upd_game, del_game))


# ══════════════════════════════════════════════════════════════════════════════
#  GAMES — one team's point of view (was the "Team Schedule" section)
# ══════════════════════════════════════════════════════════════════════════════
# The same `games` rows, pivoted onto one team: opponent instead of home/away
# team, and the scores labelled "us / them". Everything it writes goes through
# the shared _ins_game / _upd_game above, so this view now inherits the
# duplicate-matchup check and the season picker it never had.
if _hubview == "Games" and _games_pov == "One team":
    tnames = team_names()
    if not tnames:
        st.warning("Add at least one team first.")
    else:
        _s_all = _league_switch("sched_all")
        _own_names = [r["name"] for r in query(
            "SELECT name FROM teams WHERE id IN (%s) ORDER BY name"
            % ",".join("?" * len(_OWN)), tuple(_OWN))] if _OWN else []
        _s_opts = tnames if (_s_all or not _own_names) else _own_names
        selected_team = st.selectbox("Select Team", _s_opts, key="sched_team_sel")
        tm = team_map()
        team_id = tm[selected_team]

        prev_key = "_sched_prev_team"
        if st.session_state.get(prev_key) != (selected_team, _gv_val):
            invalidate("_sched_orig", "sched_editor")
            st.session_state[prev_key] = (selected_team, _gv_val)

        st.caption(EDITOR_HELP)
        orig = get_orig("_sched_orig",
                        lambda: load_games_for_team(team_id, _gv_val))
        display = (orig.drop(columns=["id"]) if not orig.empty
                   else pd.DataFrame(columns=[c for c in SCHED_COLS if c != "id"]))
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
                "game_type":  st.column_config.SelectboxColumn(
                    "Type", options=GAME_TYPES, default="Regular"),
                "tracked":    st.column_config.CheckboxColumn("Tracked",         default=False),
                "video_url":  st.column_config.TextColumn("Film URL", help="Hudl / YouTube / NFHS link. Clickable from the Team Dashboard schedule — opens in a new tab."),
            },
        )

        def _sides(r):
            """This team's POV row → (home_id, away_id, home_score, away_score,
            neutral). Away puts the team in the away slot; Home and Neutral both
            put it in the home slot — Neutral only flags the venue, and the two
            scores map the same way."""
            opp_id = tm[r["opponent"]]
            ha = r.get("home_away", "Home")
            t_score = r.get("team_score") or None
            o_score = r.get("opp_score") or None
            if ha == "Away":
                return opp_id, team_id, o_score, t_score, 0
            return team_id, opp_id, t_score, o_score, (1 if ha == "Neutral" else 0)

        if st.button("Save Changes", key="save_sched", type="primary"):
            def ins_sched(r):
                if not (r.get("opponent") and r.get("date", "").strip()):
                    return
                t1, t2, h_sc, a_sc, neu = _sides(r)
                _ins_game(t1, t2, r["date"], r.get("location"), h_sc, a_sc, neu,
                          r.get("tracked", False), r.get("video_url"),
                          r.get("game_type"), selected_team, r["opponent"])

            def upd_sched(r):
                if not (r.get("opponent") and r.get("date", "").strip()):
                    return
                t1, t2, h_sc, a_sc, neu = _sides(r)
                _upd_game(r["id"], t1, t2, r["date"], r.get("location"), h_sc,
                          a_sc, neu, r.get("tracked", False), r.get("video_url"),
                          r.get("game_type"))

            def del_sched(r):
                _del_game_row(r["id"], f"game {selected_team} vs "
                                       f"{r.get('opponent', '?')}")

            _after_games_save(
                apply_delta("sched_editor", orig, ins_sched, upd_sched, del_sched))


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
                # Re-adding a previously-archived ref (same badge in the same
                # state) revives them (un-archive); the stored name is kept,
                # matching the tracker API. Badge numbers repeat across states, so
                # the conflict target is the PAIR — the same number under another
                # state is a different official and gets its own row.
                execute(
                    "INSERT INTO officials (name, official_id, state) VALUES (?,?,?) "
                    "ON CONFLICT(official_id, state) DO UPDATE SET archived=0",
                    (r["name"].strip(), int(r["official_id"]),
                     (r.get("state") or OFF.DEFAULT_STATE).strip().upper()))
        def upd_official(r):
            execute("UPDATE officials SET name=?, official_id=?, state=? WHERE id=?",
                    (r["name"].strip(), int(r["official_id"]),
                     (r.get("state") or OFF.DEFAULT_STATE).strip().upper(), r["id"]))
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
            _uimod.clear_data()
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  SEASON ARCHIVE
# ══════════════════════════════════════════════════════════════════════════════
if _hubview == "Season Archive":
    # `schedule` is a dead table. Repo-wide, the only write left to it is
    # seasons.py re-stamping a season label onto rows that already exist — no
    # INSERT path has existed for a long time, and on the production book it
    # holds 30 rows against 13,383 in `games`, all of them from one season. Both
    # reads here now go to `games`, which is where a season's schedule has
    # actually lived since the rollover was built.
    past_seasons = query(
        "SELECT DISTINCT season FROM players WHERE archived=1 ORDER BY season"
    )
    past_seasons += query(
        "SELECT DISTINCT season FROM games WHERE season != ? AND season IS NOT NULL "
        "AND season != '' ORDER BY season", (SZ.ACTIVE,)
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
            # One team per expander, but only the teams that actually played
            # that season — a 1,448-row team list with one row each would be a
            # worse view than no view.
            teams_with_sched = query("""
                SELECT t.id, t.name, COUNT(*) AS n
                FROM games g JOIN teams t
                  ON t.id = g.team1_id OR t.id = g.team2_id
                WHERE g.season=?
                GROUP BY t.id, t.name
                ORDER BY t.name
            """, (sel_season,))
            _q = st.text_input("Find a team", key="arc_sched_q",
                               placeholder="team name…").strip().lower()
            if _q:
                teams_with_sched = [r for r in teams_with_sched
                                    if _q in r["name"].lower()]
            if not teams_with_sched:
                st.info("No games recorded for this season."
                        if not _q else "No team matches that.")
            else:
                st.caption(f"{len(teams_with_sched)} team(s) played in "
                           f"{sel_season}.")
                for team in teams_with_sched[:60]:
                    with st.expander(f"{team['name']} · {team['n']} game(s)"):
                        rows = query("""
                            SELECT CASE WHEN g.team1_id=? THEN t2.name ELSE t1.name END
                                     AS opponent,
                                   g.date,
                                   CASE WHEN g.neutral=1 THEN 'Neutral'
                                        WHEN g.team1_id=? THEN 'Home'
                                        ELSE 'Away' END AS home_away,
                                   g.location,
                                   CASE WHEN g.team1_id=? THEN g.home_score
                                        ELSE g.away_score END AS team_score,
                                   CASE WHEN g.team1_id=? THEN g.away_score
                                        ELSE g.home_score END AS opp_score,
                                   g.game_type, g.tracked
                            FROM games g
                            JOIN teams t1 ON t1.id=g.team1_id
                            JOIN teams t2 ON t2.id=g.team2_id
                            WHERE (g.team1_id=? OR g.team2_id=?) AND g.season=?
                            ORDER BY g.date
                        """, (team["id"],) * 6 + (sel_season,))
                        df = pd.DataFrame(rows) if rows else pd.DataFrame()
                        if not df.empty:
                            df["tracked"] = df["tracked"].astype(bool)
                        st.dataframe(df, width="stretch", hide_index=True)
                if len(teams_with_sched) > 60:
                    st.caption(f"Showing the first 60 of "
                               f"{len(teams_with_sched)} — use the box above to "
                               "find a team.")
