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

# ── assistant links: pinned to one game, or owner-wide ───────────────────────
# A guest link resolves to its owner coach, which keeps it inside that coach's
# games — but that is the whole season. game_id pins it to one. NULL keeps the
# owner-wide meaning, because that is what every link issued before the column
# existed was handed out as; narrowing them retroactively would break an
# assistant mid-season.
from database.db import execute as _exec, query as _q      # noqa: E402

_exec("INSERT INTO teams (id, name, gender, class) VALUES (1,'A','F','3A')")
_exec("INSERT INTO teams (id, name, gender, class) VALUES (2,'B','F','3A')")
_G1 = _exec("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-01')")
_G2 = _exec("INSERT INTO games (team1_id, team2_id, date) VALUES (1,2,'2026-01-02')")

_open = AUTH.issue_guest_token("coach@gmail.com", "Assistant")
_pin = AUTH.issue_guest_token("coach@gmail.com", "Parent", game_id=_G1)
_links = {r["token"]: r for r in AUTH.list_guest_tokens("coach@gmail.com")}
ok(set(_links) == {_open, _pin}, "both links list for their owner")
ok(_links[_open]["game_id"] is None,
   f"an unpinned link stores NULL — owner-wide, as before ({_links[_open]['game_id']!r})")
ok(_links[_pin]["game_id"] == _G1,
   f"a pinned link stores its game ({_links[_pin]['game_id']!r})")
ok(AUTH.issue_guest_token("coach@gmail.com", game_id=0) and
   _q("SELECT game_id FROM tracker_guest_tokens ORDER BY rowid DESC LIMIT 1"
      )[0]["game_id"] is None,
   "a falsy game_id is stored as NULL, not as game 0")

AUTH.revoke_guest_token(_pin)
_after = {r["token"] for r in AUTH.list_guest_tokens("coach@gmail.com")}
ok(_pin not in _after and _open in _after,
   "revoking the pinned link leaves the other one alone")

print(f"\nALL {PASS} CHECKS PASSED")
