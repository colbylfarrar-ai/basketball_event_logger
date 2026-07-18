"""
Unit test for the per-rerun app_settings snapshot in helpers/settings_utils.py.
Runs on a THROWAWAY DB (temp APP5_DATA_DIR). Pins:
  * bare mode (no Streamlit session) → _snapshot() is None and get_setting /
    get_all_settings fall back to the original per-call query path,
  * with an injected session store: ONE table query serves many get_setting
    calls (query-count assertion), user-scoped keys resolve coach-then-global,
    defaults still apply, empty-string values round-trip,
  * set_setting patches the live snapshot (read-your-own-writes),
  * a data_version move or TTL-bucket move refetches the table,
  * get_all_settings from the snapshot == get_all_settings from direct queries.
Run: python tracker/test_settings_memo.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_smemo_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database          # noqa: E402
import helpers.settings_utils as SU                  # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


EMAIL = "coach@test.com"

print("bare mode (no session)")
ok(SU._snapshot() is None, "no session -> _snapshot() is None")
SU.set_setting("accent_color", "#123456")                 # global bucket
SU.set_setting("accent_color", "#abcdef", email=EMAIL)    # coach override
SU.set_setting("team_color::7", "#ff0000")                # dynamic global key
SU.set_setting("wide_mode", "")                           # empty-string value
ok(SU.get_setting("accent_color") == "#123456", "bare: global read")
ok(SU.get_setting("accent_color", email=EMAIL) == "#abcdef",
   "bare: user-scoped override wins")
ok(SU.get_setting("team_color::7") == "#ff0000", "bare: dynamic key read")
ok(SU.get_setting("wide_mode") == "", "bare: empty string round-trips")
ok(SU.get_setting("app_style") == "Dark", "bare: DEFAULTS fallback")
ok(SU.get_setting("nope", "zz") == "zz", "bare: explicit default wins")
bare_all = SU.get_all_settings(email=EMAIL)

print("snapshot mode (injected session store)")
FAKE = {"_data_version_seen": "v1"}
SU._session_store = lambda: FAKE                     # inject

CALLS = {"n": 0}
_real_query = SU.query


def counting_query(sql, params=()):
    CALLS["n"] += 1
    return _real_query(sql, params)


SU.query = counting_query

CALLS["n"] = 0
ok(SU.get_setting("accent_color") == "#123456", "snap: global read")
ok(SU.get_setting("accent_color", email=EMAIL) == "#abcdef",
   "snap: user-scoped override wins")
ok(SU.get_setting("team_color::7") == "#ff0000", "snap: dynamic key read")
ok(SU.get_setting("wide_mode") == "", "snap: empty string round-trips")
ok(SU.get_setting("app_style") == "Dark", "snap: DEFAULTS fallback")
ok(SU.get_setting("nope", "zz") == "zz", "snap: explicit default wins")
_ = SU.get_all_settings(email=EMAIL)
ok(CALLS["n"] == 1, f"one table query served everything (got {CALLS['n']})")
ok(_ == bare_all, "get_all_settings identical snapshot vs direct")

print("read-your-own-writes")
SU.set_setting("accent_color", "#999999")
ok(SU.get_setting("accent_color") == "#999999",
   "set_setting patches live snapshot")
ok(SU.get_setting("accent_color", email=EMAIL) == "#abcdef",
   "coach override untouched by global write")

print("invalidation")
before = CALLS["n"]
FAKE["_data_version_seen"] = "v2"                    # external write signal
ok(SU.get_setting("accent_color") == "#999999", "read after version bump")
ok(CALLS["n"] == before + 1, "version bump forced exactly one refetch")
before = CALLS["n"]
FAKE[SU._SNAP_KEY]["bucket"] -= 1                    # simulate TTL expiry
_ = SU.get_setting("accent_color")
ok(CALLS["n"] == before + 1, "TTL bucket move forced a refetch")

SU.query = _real_query
print(f"\nALL {PASS} ASSERTS PASS")
