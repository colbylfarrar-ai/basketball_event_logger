"""
16_Box_Score_Entry.py — the other way a game gets its numbers.

The Game Tracker records a game possession by possession. This records one that
nobody tracked: a full box score, typed in or imported from a MaxPreps CSV. It
feeds possessions, PPP, ORtg and the four factors, and it sets the final score
so records and rankings count the game — but it never marks the game `tracked`,
because lineup and play-type stats need the play-by-play.

It lived as the fourth tab of "Roster & District", behind three thin tabs that
each edited one column. Those three merged into the Input Hub on 2026-09-12 and
this did not: it is a complete manual box-score app with its own importer, and
it is the PEER of the Game Tracker, not an appendix to a settings page. So it
gets its own entry under Build, directly beneath the Game Tracker.

Ownership is gated the way it was on the old page — this writes
games.home_score / away_score, which feed every record, rating and ranking in
the league.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from database.db import query, execute
from helpers.ui import page_chrome, page_header, empty_state
import helpers.auth as AUTH
import helpers.entitlement as ENT
import helpers.manual_box as MB
import helpers.seasons as SZ
import helpers.officials as OFF

_cfg, ACCENT = page_chrome("Box Score Entry")

_IDENT = AUTH.current_user()
_IS_ADMIN = _IDENT.get("role") == "admin"
_OWN = ENT._own_teams(_IDENT)


def _game_scope(a1="t1", a2="t2"):
    """(sql, params) restricting a games query to games one of the coach's own
    teams plays in. Empty for admin."""
    if _IS_ADMIN:
        return "", ()
    if not _OWN:
        return "1=0", ()
    ph = ",".join("?" * len(_OWN))
    return f"({a1}.id IN ({ph}) OR {a2}.id IN ({ph}))", tuple(_OWN) * 2


page_header("Box Score Entry",
            sub="Enter or import the box score for a game nobody tracked — it "
                "sets the final score and feeds possessions, PPP, ORtg and the "
                "four factors. Play-by-play games belong in the Game Tracker.")

if not _IS_ADMIN and not _OWN:
    empty_state("No team assigned",
                "A box score sets a game's final score for the whole league, so "
                "you can only enter one for a game your team played. Ask the "
                "admin to assign your team on the Settings page.")
    st.stop()

st.caption("Enter a box score for a game you didn't track play-by-play. It "
           "feeds possessions, PPP, ORtg & the four factors — and sets the "
           "final score so records & rankings count it — but never marks the "
           "game 'tracked' (lineup / play-type stats need the Game Tracker).")

_bs, _bp = _game_scope()
_g = query("""SELECT g.id, g.date, t1.name n1, t2.name n2,
                     g.team1_id, g.team2_id, g.tracked
              FROM games g JOIN teams t1 ON t1.id=g.team1_id
                           JOIN teams t2 ON t2.id=g.team2_id
           """ + (f" WHERE {_bs}" if _bs else "")
           + " ORDER BY g.date DESC LIMIT 400", _bp)
_untr = [g for g in _g if not g["tracked"]]
if not _untr:
    empty_state("No untracked games",
                "Every game is tracked, or none added yet. Add games in the "
                "Input Hub.")
    st.stop()

gsel = st.selectbox(
    "Game", _untr, key="mb_game",
    format_func=lambda g: (f"{g['date']} · {g['n1']} vs {g['n2']}"
                           + ("  ✓ entered" if MB.has_manual(g["id"]) else "")))
existing = MB.load_manual_box(gsel["id"])
_UP = [c.upper() for c in MB.STAT_COLS]
# Rosters below are the GAME's season's (retro box entry on a past-season
# game lists who actually played that year, not the current roster).
_mb_rc, _mb_rp = SZ.roster_clause(SZ.game_season(gsel["id"]))

with st.expander("⬆ Import box from CSV (MaxPreps export format)"):
    st.caption("Upload a CSV in the same shape the Box Score tab's "
               "MaxPreps export produces (Team, #, Player, MIN, PTS, "
               "FG, 3P, FT, ORB, DRB, AST, STL, BLK, TOV, PF). Players "
               "match by jersey number, then name; percent / derived "
               "columns are ignored. Importing overwrites any entered "
               "stats for the matched players.")
    _up = st.file_uploader("Box CSV", type="csv", key=f"mb_csv_{gsel['id']}")
    if _up is not None:
        try:
            _csv = pd.read_csv(_up)
        except Exception as e:
            _csv = None
            st.error(f"Couldn't read CSV: {e}")
        if _csv is not None:
            _tn = {gsel["team1_id"]: gsel["n1"], gsel["team2_id"]: gsel["n2"]}
            _ros = {tid: query(
                f"SELECT id, number, name FROM players WHERE team_id=? "
                f"AND {_mb_rc}", (tid, *_mb_rp)) for tid in _tn}
            _rows_by_team, _probs = MB.parse_maxpreps_csv(_csv, _tn, _ros)
            for _p in _probs:
                st.warning(_p)
            _n = sum(len(v) for v in _rows_by_team.values())
            if not _n:
                st.error("Nothing importable — no rows matched this "
                         "game's rosters.")
            else:
                st.caption(" · ".join(f"{_tn[t]}: {len(v)} player(s)"
                                      for t, v in _rows_by_team.items()))
                if st.button(f"Import {_n} row(s)", key=f"mb_csv_go_{gsel['id']}"):
                    for _tid2, _rows in _rows_by_team.items():
                        MB.save_manual_box(gsel["id"], _tid2, _rows)
                    box = MB.load_manual_box(gsel["id"])
                    if gsel["team1_id"] in box and gsel["team2_id"] in box:
                        _hp = MB.team_totals(box[gsel["team1_id"]])["PTS"]
                        _ap = MB.team_totals(box[gsel["team2_id"]])["PTS"]
                        execute("UPDATE games SET home_score=?, "
                                "away_score=? WHERE id=?",
                                (_hp, _ap, gsel["id"]))
                    st.cache_data.clear()   # box feeds records / rankings
                    st.success("Box imported — review in the editors below.")
                    st.rerun()

for _tid, _tnm in ((gsel["team1_id"], gsel["n1"]), (gsel["team2_id"], gsel["n2"])):
    st.markdown(f"**{_tnm}**")
    roster = query(
        f"SELECT id, number, name FROM players WHERE team_id=? AND "
        f"{_mb_rc} ORDER BY number", (_tid, *_mb_rp))
    if not roster:
        st.caption("No players on this team — add them in the Input Hub.")
        continue
    ex = {r["player_id"]: r for r in existing.get(_tid, [])}
    base = pd.DataFrame([{
        "player_id": p["id"], "#": p["number"], "Player": p["name"],
        **{c.upper(): (ex.get(p["id"], {}).get(c, 0) or 0) for c in MB.STAT_COLS},
    } for p in roster])
    ed = st.data_editor(
        base, hide_index=True, width="stretch",
        key=f"mb_ed_{gsel['id']}_{_tid}",
        column_config={
            "player_id": None,
            "#": st.column_config.NumberColumn("#", disabled=True),
            "Player": st.column_config.TextColumn("Player", disabled=True),
            "MIN": st.column_config.NumberColumn("MIN", min_value=0.0, max_value=200.0),
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
    _mp_df = MB.maxpreps_df(gsel["id"], {gsel["team1_id"]: gsel["n1"],
                                         gsel["team2_id"]: gsel["n2"]})
    if _mp_df is not None:
        st.download_button(
            "⬇ MaxPreps box — both teams (CSV)",
            _mp_df.to_csv(index=False),
            file_name=(f"maxpreps_box_{gsel['id']}_{gsel['n1']}"
                       f"_vs_{gsel['n2']}.csv"),
            mime="text/csv", key=f"mb_dl_mp_{gsel['id']}")

# ── officials who worked this untracked game (feeds projections) ──────────────
st.divider()
with st.expander("👕 Officials who worked this game — helps projections"):
    st.caption(
        "Add the referees who worked this game. Once a box score is "
        "entered above, they count as games worked and feed the crew "
        "outlook / War-Room projection **the same way an untracked game "
        "does** — scoring, pace and total fouls. It does NOT record which "
        "ref made which call (that needs the Game Tracker), so the "
        "Officials **Rating** stays tracked-only. Tracked games always "
        "take priority.")
    if not MB.has_manual(gsel["id"]):
        st.info("Enter a box score above first — officials on an untracked "
                "game only count toward projections once it has a box.")
    else:
        _offs = query("SELECT id, name, official_id FROM officials "
                      "WHERE archived=0 ORDER BY name")
        _oby = {f"{o['name']} (#{o['official_id']})": o["id"] for o in _offs}
        _cur = {r["official_id"] for r in query(
            "SELECT official_id FROM game_lineup_officials WHERE game_id=?",
            (gsel["id"],))}
        _cur_lbls = [lbl for lbl, oid in _oby.items() if oid in _cur]
        _pick = st.multiselect("Assigned officials", list(_oby),
                               default=_cur_lbls, key=f"off_pick_{gsel['id']}")
        _oc1, _oc2 = st.columns([2, 1])
        _newnm = _oc1.text_input("Add a new official", placeholder="ref name",
                                 key=f"off_new_{gsel['id']}")
        _newid = _oc2.text_input("ID # (optional)", placeholder="auto",
                                 key=f"off_newid_{gsel['id']}")
        if st.button("Save officials", key=f"off_save_{gsel['id']}"):
            _pids = [_oby[l] for l in _pick]
            if _newnm.strip():
                _oid = None
                if _newid.strip():
                    try:
                        _oid = int(_newid.strip())
                    except ValueError:
                        _oid = None
                if _oid is None:      # no external ID → synthetic negative,
                    _oid = query(     # never collides with real ref IDs
                        "SELECT COALESCE(MIN(official_id),0)-1 AS x "
                        "FROM officials")[0]["x"]
                # create or revive the ref (mirrors the tracker's add path).
                # Badge numbers repeat across state associations, so the ref
                # is keyed on (badge, state) and the state comes off the
                # host team — the same number in another state is somebody
                # else and must not be overwritten here.
                _ostate = OFF.state_for_game(gsel["id"])
                execute(
                    "INSERT INTO officials (name, official_id, state) "
                    "VALUES (?,?,?) "
                    "ON CONFLICT(official_id, state) DO UPDATE SET archived=0, "
                    "name=excluded.name",
                    (_newnm.strip(), int(_oid), _ostate))
                _row = query("SELECT id FROM officials "
                             "WHERE official_id=? AND state=?",
                             (int(_oid), _ostate))
                if _row:
                    _pids.append(_row[0]["id"])
            # replace the crew for this game with the chosen set
            execute("DELETE FROM game_lineup_officials WHERE game_id=?",
                    (gsel["id"],))
            _pids = list(dict.fromkeys(_pids))
            for _pid in _pids:
                execute("INSERT OR IGNORE INTO game_lineup_officials "
                        "(game_id, official_id) VALUES (?,?)",
                        (gsel["id"], int(_pid)))
            st.cache_data.clear()   # officials env feeds cached projections
            st.success(f"Saved {len(_pids)} official(s) for this game.")
            st.rerun()
