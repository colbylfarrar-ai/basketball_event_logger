"""
Unit test for initialize_database() surviving an OLDER database.

The defect this pins: the migration loop caught only sqlite3.OperationalError.
That covers the EXPECTED failures (duplicate column, index already exists) but
not a migration that fails on the DATA — CREATE UNIQUE INDEX over a table that
already holds duplicates raises IntegrityError. That escaped the loop, escaped
initialize_database(), and aborted `import database.db` — which every page and
the tracker API do at import — on exactly the older databases the migrations
exist to upgrade. Every page, every restart, until the DB was hand-repaired.

Second defect: _INIT_DONE.add(key) ran BEFORE the schema work, so a failed init
was never retried and every later caller in the process believed a
half-migrated DB was ready.

Covers, against a synthesized pre-migration DB:
  * init completes and does NOT raise when a unique index can't be built,
  * the offending statement is recorded in init_skipped() rather than vanishing,
  * game_lineup_officials duplicates are REPAIRED and uidx_glo ends up in place
    (that index is load-bearing: without it the ON CONFLICT upsert in
    _snapshot_and_apply_pm has no conflict target, which now fails a whole
    event),
  * duplicate client_uuids are NOT deleted — a double-logged event is the
    coach's data, not a migration's call — and the DB still opens,
  * a failed init leaves the path unmarked so the next call retries,
  * a normal init still marks the path done and is a no-op on the second call.
Run: python tracker/test_init_resilience.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

_DIR = tempfile.mkdtemp(prefix="app5_init_test_")
os.environ["APP5_DATA_DIR"] = _DIR
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database.db as db                                        # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


DB = Path(_DIR) / "analytics.db"


def _seed_old_db():
    """An 'older' DB: the tables exist, the unique indexes do NOT, and the data
    already violates two of them. Exactly the shape a long-running install has
    when it first pulls a build that adds those indexes."""
    if DB.exists():
        DB.unlink()
    c = sqlite3.connect(DB)
    c.executescript("""
        CREATE TABLE games (id INTEGER PRIMARY KEY, team1_id INT, team2_id INT,
                            date TEXT, tracked INT DEFAULT 0);
        CREATE TABLE officials (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE game_lineup_officials (
            game_id INT NOT NULL, official_id INT NOT NULL, slot INTEGER);
        CREATE TABLE game_events (
            id INTEGER PRIMARY KEY, game_id INT, event_type TEXT,
            client_uuid TEXT);
    """)
    c.execute("INSERT INTO games (id) VALUES (1)")
    # the SAME crew member recorded on the same game three times — the shape a
    # missing uidx_glo allows, since INSERT OR IGNORE ignores nothing without it
    c.execute("INSERT INTO game_lineup_officials VALUES (1, 7, NULL)")
    c.execute("INSERT INTO game_lineup_officials VALUES (1, 7, 2)")
    c.execute("INSERT INTO game_lineup_officials VALUES (1, 7, NULL)")
    c.execute("INSERT INTO game_lineup_officials VALUES (1, 9, NULL)")
    # two events sharing an idempotency key — a genuinely double-logged tap
    c.execute("INSERT INTO game_events (game_id, event_type, client_uuid) "
              "VALUES (1, 'shot', 'dupe-uuid')")
    c.execute("INSERT INTO game_events (game_id, event_type, client_uuid) "
              "VALUES (1, 'shot', 'dupe-uuid')")
    c.commit()
    c.close()


def _reinit():
    db._INIT_DONE.discard(str(DB))
    db.initialize_database()


print("an older DB with constraint-violating data still initialises")
_seed_old_db()
_reinit()                                   # the bug: this used to raise
ok(True, "initialize_database() returned instead of aborting the import")
ok(str(DB) in db._INIT_DONE, "the path is marked done after a clean run")

print("the unrepairable index is skipped, and SAID so")
skipped = db.init_skipped(DB)
uuid_skips = [s for s in skipped if "uidx_ge_client_uuid" in s[0]]
ok(len(uuid_skips) == 1,
   f"the duplicate-uuid index is recorded as skipped ({len(skipped)} total)")
ok("IntegrityError" in uuid_skips[0][1],
   f"recorded with its real error: {uuid_skips[0][1][:80]}")

print("duplicate events are LEFT ALONE — that data is the coach's")
c = sqlite3.connect(DB)
n = c.execute("SELECT COUNT(*) FROM game_events WHERE client_uuid='dupe-uuid'"
              ).fetchone()[0]
ok(n == 2, "both double-logged events survive the migration")

print("the officials index IS repaired, because it is load-bearing")
rows = c.execute("SELECT game_id, official_id, slot FROM game_lineup_officials "
                 "ORDER BY game_id, official_id").fetchall()
ok(len(rows) == 2, f"the three rows for (1,7) collapsed to one, got {rows}")
ok((1, 7, 2) in rows, "the row carrying the crew SLOT is the one kept")
idx = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND name='uidx_glo'")]
ok(idx == ["uidx_glo"], "uidx_glo now exists")
# the index is what makes the tracker's slot upsert work at all
c.execute("INSERT INTO game_lineup_officials (game_id, official_id, slot) "
          "VALUES (1, 7, 3) ON CONFLICT(game_id, official_id) "
          "DO UPDATE SET slot=excluded.slot")
c.commit()
ok(c.execute("SELECT slot FROM game_lineup_officials WHERE game_id=1 AND "
             "official_id=7").fetchone()[0] == 3,
   "ON CONFLICT(game_id, official_id) resolves against it")
ok(c.execute("SELECT COUNT(*) FROM game_lineup_officials WHERE game_id=1 AND "
             "official_id=7").fetchone()[0] == 1,
   "and the upsert did not add a second row")
c.close()

print("a FAILED init is retried, not remembered as done")
db._INIT_DONE.discard(str(DB))
_real = db._run_init
calls = []


def _boom(path):
    calls.append(path)
    raise sqlite3.DatabaseError("disk I/O error")


db._run_init = _boom
try:
    try:
        db.initialize_database()
        raised = False
    except sqlite3.DatabaseError:
        raised = True
    ok(raised, "the failure reaches the caller instead of being hidden")
    ok(str(DB) not in db._INIT_DONE,
       "the path is NOT marked done, so a half-migrated DB is never assumed ready")
    try:
        db.initialize_database()
    except sqlite3.DatabaseError:
        pass
    ok(len(calls) == 2, f"the next call retried the init (ran {len(calls)}x)")
finally:
    db._run_init = _real

print("a clean init is a no-op the second time")
db._INIT_DONE.discard(str(DB))
db.initialize_database()
ran = []
db._run_init = lambda p: ran.append(p)
try:
    db.initialize_database()
    ok(not ran, "second call short-circuits on _INIT_DONE")
finally:
    db._run_init = _real

print("a FRESH DB initialises clean, with nothing skipped")
for f in Path(_DIR).glob("analytics.db*"):
    f.unlink()
_reinit()
ok(db.init_skipped(DB) == [], f"no skipped migrations: {db.init_skipped(DB)[:2]}")
c = sqlite3.connect(DB)
have = {r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='index'")}
for want in ("uidx_glo", "uidx_ge_client_uuid"):
    ok(want in have, f"{want} built on a fresh DB")
c.close()

print(f"\nALL {PASS} ASSERTS PASS")
