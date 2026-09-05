"""
Cross-state badge collision — officials are keyed on (badge, state), not badge.

An association's official_id is unique only inside the state that issued it, so
Arkansas #1234 and Oklahoma #1234 are two different people. Under the old
globally-UNIQUE column, adding the Arkansas ref un-archived the Oklahoma one,
handed back the WRONG NAME, and pooled two careers into one row.

Covers: the quick-add upsert scoping, the host-state derivation, and the
one-time table rebuild that moves an existing book onto UNIQUE(official_id,
state) without dropping a single crew row.

Run: python -m pytest tracker/test_official_badges.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_offbadge_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient            # noqa: E402

import database.db as DB                             # noqa: E402
import helpers.officials as OFF                      # noqa: E402
from database.db import execute, query               # noqa: E402
from tracker.api import app                          # noqa: E402

# tracker.api runs initialize_database() the FIRST time it is imported, against
# whichever APP5_DATA_DIR was set then. Under `pytest tracker/` that is another
# module's temp dir, and the import above is a cached no-op — so this module has
# to migrate its own DB or every write below lands on "no such table".
# (conftest.py describes the same hazard from the other direction.)
DB.initialize_database()

# Two hosts in two states, so a game can be pinned to either association.
_OK = execute("INSERT INTO teams (name, class, gender, state) "
              "VALUES ('Okla High','3A','M','OK')")
_AR = execute("INSERT INTO teams (name, class, gender, state) "
              "VALUES ('Ark High','3A','M','AR')")
_OK_GAME = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?,'2026-01-05')",
                   (_OK, _AR))          # home = OK
_AR_GAME = execute("INSERT INTO games (team1_id,team2_id,date) VALUES (?,?,'2026-01-12')",
                   (_AR, _OK))          # home = AR

execute("INSERT INTO app_users (email, role, name, plan, tracker_token) "
        "VALUES ('c@test','coach','C','paid','tok')")
client = TestClient(app)
client.headers.update({"Authorization": "Bearer tok"})


def _add(name, badge, **kw):
    r = client.post("/api/officials",
                    json={"name": name, "official_id": badge, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_state_comes_off_the_host():
    """The host assigns the crew, so the badge is scoped to team1's state."""
    assert OFF.state_for_game(_OK_GAME) == "OK"
    assert OFF.state_for_game(_AR_GAME) == "AR"
    # a caller with no game to go on falls back — never to an empty string
    assert OFF.state_for_game(None) == OFF.DEFAULT_STATE
    assert OFF.state_for_game(999999) == OFF.DEFAULT_STATE


def test_same_badge_in_two_states_is_two_officials():
    a = _add("Oklahoma Ref", 1234, game_id=_OK_GAME)
    b = _add("Arkansas Ref", 1234, game_id=_AR_GAME)
    assert a["id"] != b["id"], "same badge in two states collapsed into one ref"
    # the bug's signature was the WRONG NAME coming back
    assert a["name"] == "Oklahoma Ref"
    assert b["name"] == "Arkansas Ref"
    rows = query("SELECT state FROM officials WHERE official_id=1234 ORDER BY state")
    assert [r["state"] for r in rows] == ["AR", "OK"]


def test_same_badge_same_state_still_revives_one_row():
    """Re-adding an archived ref in their OWN state is still an un-archive, and
    still answers with the stored name rather than the typed one."""
    first = _add("Real Name", 4321, game_id=_OK_GAME)
    execute("UPDATE officials SET archived=1 WHERE id=?", (first["id"],))
    again = _add("Typo Nmae", 4321, game_id=_OK_GAME)
    assert again["id"] == first["id"], "same state should upsert, not duplicate"
    assert again["name"] == "Real Name", "stored name must win on collision"
    assert query("SELECT archived FROM officials WHERE id=?",
                 (first["id"],))[0]["archived"] == 0


def test_explicit_state_overrides_the_game():
    """A travelling ref working an OK game but badged somewhere else."""
    r = _add("Kansas Ref", 555, game_id=_OK_GAME, state="ks")
    assert query("SELECT state FROM officials WHERE id=?",
                 (r["id"],))[0]["state"] == "KS", "state should normalise upper"


def test_no_game_lands_in_the_default_state():
    r = _add("Bare Add", 909)
    assert query("SELECT state FROM officials WHERE id=?",
                 (r["id"],))[0]["state"] == OFF.DEFAULT_STATE


def test_two_badge_twins_stay_two_rows():
    """The Officials page has to be able to tell the two #1234s apart, so the
    state has to survive on the row rather than being an insert-time detail."""
    rows = query("SELECT id, name, official_id, state FROM officials "
                 "WHERE official_id=1234")
    assert len(rows) == 2 and {r["state"] for r in rows} == {"OK", "AR"}


def test_migration_rebuilds_an_old_book_without_losing_crews():
    """An existing DB carries the old globally-UNIQUE column. The one-time
    rebuild has to swap the constraint while keeping every officials.id (the
    foreign keys point at it) and every game_lineup_officials row (DROP TABLE
    would otherwise CASCADE them away)."""
    old_dir = tempfile.mkdtemp(prefix="app5_offbadge_old_")
    db = Path(old_dir) / "analytics.db"
    con = sqlite3.connect(db)
    con.executescript(
        "CREATE TABLE teams (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL UNIQUE,"
        " class TEXT NOT NULL CHECK(class IN ('B2','B1','A','2A','3A','4A','5A','6A','N/A')),"
        " gender TEXT NOT NULL CHECK(gender IN ('M','F')));"
        "CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " team1_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,"
        " team2_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,"
        " date TEXT NOT NULL, location TEXT, home_score INTEGER, away_score INTEGER,"
        " neutral INTEGER NOT NULL DEFAULT 0, tracked INTEGER NOT NULL DEFAULT 0);"
        "CREATE TABLE officials (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL, official_id INTEGER NOT NULL UNIQUE);"
        "CREATE TABLE game_lineup_officials (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,"
        " official_id INTEGER NOT NULL REFERENCES officials(id) ON DELETE CASCADE,"
        " UNIQUE(game_id, official_id));"
        "INSERT INTO teams (name,class,gender) VALUES ('H','3A','M'),('A','3A','M');"
        "INSERT INTO games (team1_id,team2_id,date,tracked) VALUES (1,2,'2026-02-06',1);"
        "INSERT INTO officials (name, official_id) VALUES ('Legacy Ref',1234),('Other',77);"
        "INSERT INTO game_lineup_officials (game_id, official_id) VALUES (1,1),(1,2);")
    con.commit()
    con.close()

    prev = os.environ["APP5_DATA_DIR"]
    os.environ["APP5_DATA_DIR"] = old_dir
    try:
        DB.initialize_database()
        assert not [s for s in DB.init_skipped() if "officials" in s[0].lower()], \
            DB.init_skipped()
        con = sqlite3.connect(db)
        sql = con.execute("SELECT sql FROM sqlite_master "
                          "WHERE name='officials'").fetchone()[0]
        assert "UNIQUE(official_id, state)" in sql, sql
        # ids preserved -> every FK that points at officials(id) still resolves
        assert con.execute("SELECT id, name, official_id, state FROM officials "
                           "ORDER BY id").fetchall() == [
            (1, "Legacy Ref", 1234, "OK"), (2, "Other", 77, "OK")]
        assert con.execute("SELECT game_id, official_id FROM game_lineup_officials "
                           "ORDER BY official_id").fetchall() == [(1, 1), (1, 2)]
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        # and the collision this whole item exists for is now insertable
        con.execute("INSERT INTO officials (name, official_id, state) "
                    "VALUES ('AR Ref',1234,'AR')")
        con.commit()
        dup_taken = True
        try:
            con.execute("INSERT INTO officials (name, official_id, state) "
                        "VALUES ('Dup',1234,'OK')")
        except sqlite3.IntegrityError:
            dup_taken = False
        con.close()
        assert not dup_taken, "a same-state duplicate badge was accepted"
    finally:
        os.environ["APP5_DATA_DIR"] = prev


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
