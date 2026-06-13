"""
Smoke test for the write audit log (database/db.py execute() hook + set_audit_actor).
Run: python tracker/test_audit.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_audit_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query, set_audit_actor   # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def audit():
    return query("SELECT actor, op, table_name, row_id FROM audit_log ORDER BY id")


print("actor attribution")
set_audit_actor("coach@x")
T = execute("INSERT INTO teams (name,class,gender) VALUES ('Q','3A','F')")
ok(any(r["table_name"] == "teams" and r["op"] == "INSERT"
       and r["actor"] == "coach@x" and r["row_id"] == T for r in audit()),
   "team INSERT logged with actor + row_id")
execute("UPDATE teams SET class='4A' WHERE id=?", (T,))
ok(any(r["op"] == "UPDATE" and r["table_name"] == "teams" for r in audit()),
   "team UPDATE logged")

print("noise tables excluded")
_b = len(audit())
execute("INSERT OR REPLACE INTO app_settings (key,value) VALUES ('x','1')")
ok(len(audit()) == _b, "app_settings write NOT audited")
execute("INSERT INTO change_requests (op,table_name,target_id) VALUES ('delete','teams',?)",
        (T,))
ok(not any(r["table_name"] == "change_requests" for r in audit()),
   "change_requests write NOT audited")

print("no self-recursion")
_n = len(audit())
execute("UPDATE teams SET class='5A' WHERE id=?", (T,))
ok(len(audit()) == _n + 1, "one user write = exactly one audit row (audit_log not re-audited)")

print("default actor = 'local' when unset")
set_audit_actor("")
execute("INSERT INTO officials (name, official_id) VALUES ('Ref', 999)")
ok(any(r["actor"] == "local" and r["table_name"] == "officials" for r in audit()),
   "unset actor logged as 'local'")

print("delete logged")
set_audit_actor("coach@x")
execute("DELETE FROM teams WHERE id=?", (T,))
ok(any(r["op"] == "DELETE" and r["table_name"] == "teams" for r in audit()),
   "team DELETE logged")

print(f"\nALL {PASS} CHECKS PASSED")
