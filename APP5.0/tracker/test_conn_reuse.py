"""
Unit test for thread-local persistent DB connections (maintenance batch #6b).
Runs on a THROWAWAY DB (temp APP5_DATA_DIR). Pins:
  * get_connection() reuses ONE connection per (thread, db path) instead of
    opening + 4-PRAGMA + closing on every call,
  * query()/execute()/executemany() no longer close the shared connection,
  * the perf PRAGMAs (cache_size, mmap_size) are set on the connection,
  * a failing execute() rolls back and leaves the persistent connection usable
    (no wedged transaction on the shared object),
  * different threads get different connections (thread-local, no cross-thread
    sqlite object sharing under check_same_thread),
  * a db-path change (season swap) re-opens a fresh connection.
Run: python tracker/test_conn_reuse.py
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_conn_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import (                                   # noqa: E402
    initialize_database, get_connection, query, execute, executemany)
import database.db as db                                    # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("reuse")
c1 = get_connection()
c2 = get_connection()
ok(c1 is c2, "same thread + path -> same connection object reused")

print("query/execute do not close the shared connection")
execute("CREATE TABLE IF NOT EXISTS _t (id INTEGER PRIMARY KEY, v TEXT)")
execute("INSERT INTO _t (v) VALUES (?)", ("a",))
rows = query("SELECT v FROM _t ORDER BY id")
ok(rows == [{"v": "a"}], "execute insert visible via query on reused conn")
ok(get_connection() is c1, "connection still the same object after query/execute")
# a closed sqlite connection raises on use; prove it's still open
c1.execute("SELECT 1")
ok(True, "shared connection still open (not closed by query/execute)")

print("perf PRAGMAs set on the connection")
cache_size = c1.execute("PRAGMA cache_size").fetchone()[0]
mmap_size = c1.execute("PRAGMA mmap_size").fetchone()[0]
ok(cache_size == -65536, f"cache_size = -65536 (64MB), got {cache_size}")
ok(mmap_size > 0, f"mmap_size enabled, got {mmap_size}")

print("failing execute rolls back, connection stays usable")
try:
    execute("INSERT INTO _t (id, v) VALUES (1, 'dup')")   # PK collision with row 1
except Exception:
    pass
# the persistent connection must not be left in an aborted transaction
rows = query("SELECT COUNT(*) AS n FROM _t")
ok(rows == [{"n": 1}], "after failed execute, reused connection still queries")
execute("INSERT INTO _t (v) VALUES (?)", ("b",))
ok(query("SELECT COUNT(*) AS n FROM _t") == [{"n": 2}],
   "reused connection still writes after a prior failure")

print("thread isolation")
other = {}


def _worker():
    other["conn"] = get_connection()
    other["rows"] = query("SELECT COUNT(*) AS n FROM _t")


t = threading.Thread(target=_worker)
t.start()
t.join()
ok(other["conn"] is not c1, "different thread -> different connection object")
ok(other["rows"] == [{"n": 2}], "other thread queries its own connection fine")

print("db-path change re-opens")
other_dir = tempfile.mkdtemp(prefix="app5_conn_test2_")
other_path = Path(other_dir) / "analytics.db"
_real_get_db_path = db.get_db_path
db.get_db_path = lambda: other_path
try:
    c3 = get_connection()
    ok(c3 is not c1, "new db path -> fresh connection (keyed by path)")
finally:
    db.get_db_path = _real_get_db_path
ok(get_connection() is c1, "original path still returns the original connection")

print(f"\nALL {PASS} ASSERTS PASS")
