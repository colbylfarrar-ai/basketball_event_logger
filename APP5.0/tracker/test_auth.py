"""
Smoke test for helpers/auth.py user-table logic, against a THROWAWAY DB.
(The st.login flow itself needs a browser + Google credentials; everything
testable headlessly — roles, allowlist, bootstrap — is covered here.)
Run: python tracker/test_auth.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_auth_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.auth as AUTH                        # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


ok(AUTH.lookup_role("nobody@x.com") is None, "unknown email -> no role")
ok(AUTH.bootstrap_admin_if_empty("Coach@Gmail.com", "Colby") == "admin",
   "first login bootstraps admin")
ok(AUTH.lookup_role("coach@gmail.com") == "admin", "email normalized to lowercase")
ok(AUTH.bootstrap_admin_if_empty("second@x.com") is None,
   "bootstrap only fires on empty table")

AUTH.add_user("Friend@School.org", "coach", "Pat", added_by="coach@gmail.com")
ok(AUTH.lookup_role("friend@school.org") == "coach", "coach added")
AUTH.add_user("friend@school.org", "admin")
ok(AUTH.lookup_role("friend@school.org") == "admin", "re-add updates role")
ok(len(AUTH.list_users()) == 2, "list shows both users")

AUTH.remove_user("friend@school.org")
ok(AUTH.lookup_role("friend@school.org") is None, "removed user loses access")

for bad in ("", "   ", "not-an-email"):
    try:
        AUTH.add_user(bad)
        raise AssertionError(f"accepted bad email {bad!r}")
    except ValueError:
        pass
ok(True, "bad emails rejected")
try:
    AUTH.add_user("x@y.com", role="superuser")
    raise AssertionError("accepted bad role")
except ValueError:
    ok(True, "bad role rejected")

print(f"\nALL {PASS} CHECKS PASSED")
