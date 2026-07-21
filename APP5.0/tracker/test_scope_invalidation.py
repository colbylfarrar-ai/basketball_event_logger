"""
Unit test for per-scope cache invalidation (maintenance batch #6a).
Runs on a THROWAWAY DB (temp APP5_DATA_DIR). Pins:
  * data_scope_key() canonicalizes season the SAME way the engines do
    (Current sentinel vs archived label) so write- and read-side keys rendezvous,
  * bump_data_version(game_id) bumps the per-(gender,season) scope counter that
    the game belongs to, AND still bumps the global data_version (public_feed +
    settings-memo depend on it),
  * bump_data_version() with no game bumps the always-relevant ALL scope,
  * cache_clear_decision() clears iff a scope THIS session cares about moved:
    no move -> no clear; undeclared session -> clear on any move (safe default);
    ALL move -> always clear; disjoint move -> stay warm.
Run: python tracker/test_scope_invalidation.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_scope_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, query, execute      # noqa: E402
import helpers.game_events as GE                                  # noqa: E402

initialize_database()

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


def _dv(scope):
    r = query("SELECT value FROM app_settings WHERE key=?", (scope,))
    return int(r[0]["value"]) if r else 0


# ── seed a current-season F game and an archived-season M game ────────────────
execute("INSERT INTO teams (id, name, class, gender) VALUES (10,'Adair','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (11,'Westville','3A','F')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (20,'BoysA','4A','M')")
execute("INSERT INTO teams (id, name, class, gender) VALUES (21,'BoysB','4A','M')")
gF = execute("INSERT INTO games (team1_id, team2_id, date, season) "
             "VALUES (10,11,'2026-11-01','Current')")
gM = execute("INSERT INTO games (team1_id, team2_id, date, season) "
             "VALUES (20,21,'2025-12-01','2025-2026')")

print("data_scope_key canonicalization")
ok(GE.data_scope_key("F", "Current") == GE.data_scope_key("F", None),
   "None season canonicalizes to Current sentinel")
ok(GE.data_scope_key("F", "Current") != GE.data_scope_key("F", "2025-2026"),
   "current and archived label are distinct scopes")
ok(GE.data_scope_key("F", "Current") != GE.data_scope_key("M", "Current"),
   "gender splits the scope")

print("bump_data_version(game_id) hits the game's scope + global")
gv0 = _dv("data_version")
sF = GE.data_scope_key("F", "Current")
sM = GE.data_scope_key("M", "2025-2026")
f0, m0 = _dv(sF), _dv(sM)
GE.bump_data_version(gF)
ok(_dv(sF) == f0 + 1, "F/Current scope bumped by the F game write")
ok(_dv(sM) == m0, "M/archived scope untouched by the F game write")
ok(_dv("data_version") == gv0 + 1, "global data_version still bumped")

GE.bump_data_version(gM)
ok(_dv(sM) == m0 + 1, "M/archived scope bumped by the M game write")
ok(_dv(sF) == f0 + 1, "F scope NOT re-bumped by the M game write")

print("bump_data_version() with no game -> ALL scope")
a0 = _dv(GE.DATA_SCOPE_ALL)
GE.bump_data_version()
ok(_dv(GE.DATA_SCOPE_ALL) == a0 + 1, "non-game write bumps the ALL scope")

print("cache_clear_decision")
cur = {sF: 5, sM: 3, GE.DATA_SCOPE_ALL: 1}
ok(GE.cache_clear_decision(cur, dict(cur), {sF}) is False,
   "no move -> no clear")
ok(GE.cache_clear_decision(cur, {sF: 4, sM: 3, GE.DATA_SCOPE_ALL: 1}, None) is True,
   "undeclared session -> clear on any move")
ok(GE.cache_clear_decision(cur, {sF: 5, sM: 2, GE.DATA_SCOPE_ALL: 1}, {sF}) is False,
   "disjoint move (M moved, I watch F) -> stay warm")
ok(GE.cache_clear_decision(cur, {sF: 4, sM: 3, GE.DATA_SCOPE_ALL: 1}, {sF}) is True,
   "my scope moved -> clear")
ok(GE.cache_clear_decision(cur, {sF: 5, sM: 3, GE.DATA_SCOPE_ALL: 0}, {sF}) is True,
   "ALL scope moved -> always clear regardless of my scope")

print(f"\nALL {PASS} ASSERTS PASS")
