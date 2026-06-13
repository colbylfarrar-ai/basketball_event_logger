"""
Smoke test for helpers/change_requests.py — the admin delete-approval queue
(write-authz). Run: python tracker/test_change_requests.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_cr_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute, query        # noqa: E402
import helpers.change_requests as CR            # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


admin = {"role": "admin", "email": "admin@x"}
coach = {"role": "coach", "email": "coach@x"}

print("should_delete_now")
ok(CR.should_delete_now(admin), "admin deletes directly")
ok(not CR.should_delete_now(coach), "coach does NOT delete directly (queued)")
ok(not CR.should_delete_now(None), "no identity -> not direct")

# a team to target
T = execute("INSERT INTO teams (name,class,gender) VALUES ('Z','3A','F')")

print("request_delete -> pending")
CR.request_delete("teams", T, "team 'Z'", "coach@x")
ok(CR.pending_count() == 1, "one pending request")
ok(query("SELECT 1 FROM teams WHERE id=?", (T,)), "team still LIVE while pending")
CR.request_delete("teams", T, "team 'Z'", "coach@x")
ok(CR.pending_count() == 1, "duplicate pending request is idempotent")

print("whitelist guard")
try:
    CR.request_delete("app_users", 1, "hack", "coach@x")
    ok(False, "non-whitelisted table should raise")
except ValueError:
    ok(True, "request_delete rejects a non-whitelisted table")

print("accept -> runs the delete")
_rid = CR.pending()[0]["id"]
ok(CR.accept(_rid, "admin@x") is True, "accept returns True")
ok(not query("SELECT 1 FROM teams WHERE id=?", (T,)), "team is deleted after accept")
ok(CR.pending_count() == 0, "no pending after accept")
ok(CR.accept(_rid, "admin@x") is False, "re-accepting a decided request is a no-op")
ok(query("SELECT status FROM change_requests WHERE id=?", (_rid,))[0]["status"]
   == "accepted", "status recorded as accepted")

print("reject -> keeps the data")
T2 = execute("INSERT INTO teams (name,class,gender) VALUES ('Y','3A','F')")
CR.request_delete("teams", T2, "team 'Y'", "coach@x")
_rid2 = CR.pending()[0]["id"]
ok(CR.reject(_rid2, "admin@x") is True, "reject returns True")
ok(query("SELECT 1 FROM teams WHERE id=?", (T2,)), "team SURVIVES a reject")
ok(CR.pending_count() == 0, "no pending after reject")
ok(CR.reject(_rid2, "admin@x") is False, "re-rejecting a decided request is a no-op")

print(f"\nALL {PASS} CHECKS PASSED")
