"""
Unit test for database.db.atomic() and the write paths that now use it.

The defect this pins: log_event() inserted the game_events row and then issued
~30 SEPARATELY COMMITTED statements for the lineup snapshot, the
game_lineup_players rows and the +/- credits. A crash between them left an
event that scores forever (score_from_events reads game_events) but that no
lineup engine can see (they read game_event_lineup) — and unrepairable, because
recompute_game_plus_minus rebuilds FROM the snapshot rows that were lost.

Covers:
  * atomic() commits everything in the block, or nothing,
  * a nested atomic() JOINS the outer one (only the outermost commits, and an
    outer failure discards the inner block's writes),
  * execute() inside atomic() does NOT roll back on its own — a caller catching
    the error keeps the earlier statements, and the block still owns the undo,
  * executemany() honours the open transaction the same way,
  * log_event() is all-or-nothing: a failure in the snapshot/+/- half leaves NO
    game_events row behind (the split-brain event is impossible),
  * delete_event() is all-or-nothing in the other direction,
  * the persistent thread-local connection stays usable after a rollback.
Run: python tracker/test_atomic_writes.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_atomic_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import (                                          # noqa: E402
    initialize_database, get_connection, query, execute, executemany, atomic)
import database.db as db                                           # noqa: E402
import helpers.game_events as GE                                   # noqa: E402
import helpers.event_log as EL                                     # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def n_t():
    return query("SELECT COUNT(*) AS n FROM _t")[0]["n"]


execute("CREATE TABLE IF NOT EXISTS _t (id INTEGER PRIMARY KEY, v TEXT)")

# ── atomic(): all or nothing ──────────────────────────────────────────────────
print("atomic commits the whole block")
with atomic():
    execute("INSERT INTO _t (v) VALUES ('a')")
    execute("INSERT INTO _t (v) VALUES ('b')")
ok(n_t() == 2, "both inserts committed on clean exit")

print("atomic rolls the whole block back")
try:
    with atomic():
        execute("INSERT INTO _t (v) VALUES ('c')")
        execute("INSERT INTO _t (v) VALUES ('d')")
        raise RuntimeError("boom")
except RuntimeError:
    pass
ok(n_t() == 2, "no partial write survives — 'c' did not stick without 'd'")
ok(query("SELECT COUNT(*) AS n FROM _t WHERE v='c'")[0]["n"] == 0,
   "the statement that already succeeded was undone too")

print("connection still usable after the rollback")
execute("INSERT INTO _t (v) VALUES ('e')")
ok(n_t() == 3, "plain execute works again on the shared connection")

# ── nesting ───────────────────────────────────────────────────────────────────
print("nested atomic joins the outer transaction")
try:
    with atomic():
        execute("INSERT INTO _t (v) VALUES ('f')")
        with atomic():
            execute("INSERT INTO _t (v) VALUES ('g')")
        # inner block exited cleanly, but it must NOT have committed
        raise RuntimeError("boom")
except RuntimeError:
    pass
ok(n_t() == 3, "inner block's clean exit did not commit past the outer failure")

with atomic():
    with atomic():
        execute("INSERT INTO _t (v) VALUES ('h')")
ok(n_t() == 4, "nested success still commits once at the outermost exit")
ok(not db._in_txn(), "transaction depth unwound back to zero")

# ── execute() inside atomic must not self-rollback ────────────────────────────
print("a failing execute inside atomic does not discard the block")
with atomic():
    execute("INSERT INTO _t (id, v) VALUES (999, 'keep')")
    try:
        execute("INSERT INTO _t (id, v) VALUES (999, 'dup')")   # PK collision
    except Exception:
        pass                                    # caller handles it; block goes on
    execute("INSERT INTO _t (v) VALUES ('after')")
ok(query("SELECT COUNT(*) AS n FROM _t WHERE v IN ('keep','after')")[0]["n"] == 2,
   "statements around a caught error still committed with the block")

print("executemany honours the open transaction")
try:
    with atomic():
        executemany("INSERT INTO _t (v) VALUES (?)", [("m1",), ("m2",)])
        raise RuntimeError("boom")
except RuntimeError:
    pass
ok(query("SELECT COUNT(*) AS n FROM _t WHERE v LIKE 'm%'")[0]["n"] == 0,
   "executemany rows rolled back with the block")

# ── the real thing: log_event ─────────────────────────────────────────────────
print("seed a game")
execute("INSERT INTO teams (id, name, class, gender) VALUES (1,'Home','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (2,'Away','3A','F')")
for pid in (101, 102, 103, 104, 105):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,1,?,?)",
            (pid, f"H{pid}", pid))
for pid in (201, 202, 203, 204, 205):
    execute("INSERT INTO players (id, team_id, name, number) VALUES (?,2,?,?)",
            (pid, f"A{pid}", pid))
G = execute("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-01')")
FLOOR = [(p, 1) for p in (101, 102, 103, 104, 105)] + [(p, 2) for p in (201, 202, 203, 204, 205)]

MADE_TWO = {"event_type": "shot", "quarter": 1, "time": "5:00",
            "primary_player_id": 101, "shot_result": "make", "shot_type": 2}


def n_events():
    return query("SELECT COUNT(*) AS n FROM game_events WHERE game_id=?",
                 (G,))[0]["n"]


print("log_event writes the event and its snapshot together")
e1 = GE.log_event(G, dict(MADE_TWO), FLOOR)
ok(n_events() == 1, "event row written")
ok(query("SELECT COUNT(*) AS n FROM game_event_lineup WHERE event_id=?",
         (e1,))[0]["n"] == 10, "all 10 floor players snapshotted")
ok(query("SELECT plus_minus AS pm FROM game_lineup_players "
         "WHERE game_id=? AND player_id=101", (G,))[0]["pm"] == 2,
   "+/- credited on the scoring team")

print("a failure in the snapshot half leaves NO event behind")
_real_snapshot = GE._snapshot_and_apply_pm


def _boom(*a, **k):
    # Fail PART WAY through, after some snapshot rows exist — the exact shape of
    # the old bug, where the already-committed rows could not be taken back.
    execute("INSERT OR IGNORE INTO game_event_lineup (event_id, player_id, team_id) "
            "VALUES (?,?,?)", (a[1], 101, 1))
    raise RuntimeError("crash mid-snapshot")


GE._snapshot_and_apply_pm = _boom
try:
    GE.log_event(G, dict(MADE_TWO, time="4:00"), FLOOR)
    raised = False
except RuntimeError:
    raised = True
finally:
    GE._snapshot_and_apply_pm = _real_snapshot
ok(raised, "the failure propagates to the caller (it is not swallowed)")
ok(n_events() == 1, "no scoring-but-invisible event survived the failure")
ok(query("SELECT COUNT(*) AS n FROM game_event_lineup gel "
         "LEFT JOIN game_events ge ON ge.id=gel.event_id "
         "WHERE ge.id IS NULL")[0]["n"] == 0, "no orphan snapshot rows either")

print("score and lineup views agree after the failed write")
ok(EL.score_from_events(G) == (2, 0), "score still reflects only the good event")

print("delete_event is all-or-nothing")
pid2team = {p: t for p, t in FLOOR}
_real_execute = EL.execute


def _fail_delete(sql, params=()):
    if sql.strip().upper().startswith("DELETE FROM GAME_EVENTS"):
        raise RuntimeError("crash before the delete lands")
    return _real_execute(sql, params)


EL.execute = _fail_delete
try:
    EL.delete_event(G, e1, pid2team)
except RuntimeError:
    pass
finally:
    EL.execute = _real_execute
ok(n_events() == 1, "the event is still there")
ok(query("SELECT plus_minus AS pm FROM game_lineup_players "
         "WHERE game_id=? AND player_id=101", (G,))[0]["pm"] == 2,
   "its +/- was NOT reversed while the event survived")

print("a clean delete still works")
EL.delete_event(G, e1, pid2team)
ok(n_events() == 0, "event deleted")
ok(query("SELECT plus_minus AS pm FROM game_lineup_players "
         "WHERE game_id=? AND player_id=101", (G,))[0]["pm"] == 0,
   "+/- reversed with it")

ok(get_connection() is get_connection(), "connection still shared and open")
print(f"\nALL {PASS} ASSERTS PASS")
