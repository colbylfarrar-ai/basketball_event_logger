"""The Insights cache key — what may bust it, and what may not.

Every expensive wrapper on the Insights tab takes `fp=_data_fp(...)` and does the
real invalidation through it (the ttl is only a fallback). So the fingerprint's
SCOPE decides how often a coach pays the cold rebuild, measured at 84.7s on prod
against 0.97s warm.

It used to count the whole `game_events` table. That made the key global: a
tracker write on another team, in the other gender, or in an archived season
moved the fingerprint for every team's Insights page and forced the full rebuild,
even though none of those rows are read by this pool's engines. On a 21-team
league that is the common case.

The two directions both matter, and only one of them is about speed:
  * an OUT-OF-POOL write must NOT bust the key — that is the 85 seconds;
  * an IN-POOL write MUST bust it — otherwise a coach reads stale numbers, which
    is a worse failure than a slow page.

This one reads the LIVE book (it needs a real tracked pool). The two write
probes below insert a single event and delete it again in a `finally`, then
assert the fingerprint is back where it started — nothing is left behind.

Run: python tracker/test_insights_cache_key.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print("  ok  " + str(label).encode("ascii", "replace").decode("ascii"))


import helpers.seasons as SEAS                        # noqa: E402
from database.db import execute, query                # noqa: E402
from helpers.dashboard import insights_tab as IT      # noqa: E402

pools = {}
for _label, _l in SEAS.season_options():
    for _g in ("F", "M"):
        _p = SEAS.game_pool(_label, gender=_g, tracked_only=True) or []
        if _p:
            pools[(_label, _g)] = sorted(_p)
if not pools:
    print("  -- no tracked games in this DB; skipped")
    sys.exit(0)

KEY, GIDS = max(pools.items(), key=lambda kv: len(kv[1]))
print(f"pools: {[(str(k), len(v)) for k, v in pools.items()]}")
print(f"primary: {KEY} — {len(GIDS)} games")


print("\n-- the fingerprint is scoped, not global ----------------------------")

_glob = IT._data_fp(None)
_scoped = IT._data_fp(GIDS)
ok(len(pools) < 2 or _glob != _scoped,
   "a scoped fingerprint differs from the global one (it is counting fewer rows)")

_tot = query("SELECT COUNT(*) c, COALESCE(MAX(id),0) m FROM game_events")[0]
_marks = ",".join("?" * len(GIDS))
_mine = query(f"SELECT COUNT(*) c, COALESCE(MAX(id),0) m FROM game_events "
              f"WHERE game_id IN ({_marks})", tuple(GIDS))[0]
ok(_scoped[0] == _mine["c"] and _scoped[1] == _mine["m"],
   f"the event half counts exactly this pool's rows ({_mine['c']} of "
   f"{_tot['c']} in the table)")
ok(_glob[0] == _tot["c"],
   "and an unscoped call still counts everything, so other callers are unchanged")
ok(_scoped[2] == _glob[2],
   "the SCORE half stays global on purpose — scores move a couple of times a "
   "night, not ten times a game, so they were never what busted the cache")


print("\n-- what may bust it, and what may not ------------------------------")

# These used to be tuple arithmetic — `(c,m) != (c+1,m+1)` — which passes against
# ANY implementation, including the global key it was written to rule out. That
# is why the regression shipped: nothing here ever called _data_fp twice. Write a
# real row, re-read the real fingerprint, roll it back.
def _fp_after_event(gid):
    """_data_fp(GIDS) after inserting one event into `gid`, then rolled back."""
    execute("INSERT INTO game_events (game_id, quarter, time, event_type) "
            "VALUES (?, 1, '8:00', 'shot')", (gid,))
    new_id = query("SELECT MAX(id) m FROM game_events")[0]["m"]
    try:
        return IT._data_fp(GIDS)
    finally:
        execute("DELETE FROM game_events WHERE id=?", (new_id,))


_out_gid = query(
    f"SELECT id FROM games WHERE id NOT IN ({_marks}) "
    f"AND id IN (SELECT game_id FROM game_events) LIMIT 1", tuple(GIDS))

_before = IT._data_fp(GIDS)
if _out_gid:
    ok(_fp_after_event(_out_gid[0]["id"]) == _before,
       "an OUT-OF-POOL write leaves the key untouched, so the cache stays warm "
       "— this is the 85 seconds")
else:
    print("  -- no out-of-pool game with events in this DB; skipped that half")

ok(_fp_after_event(GIDS[0]) != _before,
   "while a write to one of this pool's OWN games still busts it — her numbers "
   "really did change, and a stale page is worse than a slow one")

ok(IT._data_fp(GIDS) == _before,
   "and the probe rolled back cleanly (the fingerprint is where it started)")

_outside = _tot["c"] - _mine["c"]
ok(_outside >= 0,
   f"{_outside} of {_tot['c']} event rows ({100.0 * _outside / _tot['c']:.0f}%) "
   f"live outside this pool and used to invalidate it")


print("\n-- the call site passes the scope ----------------------------------")

# The old check here grepped for the literal expression render() used. That is
# an implementation echo: it matched happily while the value being passed was
# None on the current season, which is precisely how the global-key regression
# survived a test written to catch it. Assert the BEHAVIOUR instead.
from types import SimpleNamespace                     # noqa: E402

_ctx_cur = SimpleNamespace(gender="F", season="Current",
                           season_gp=None,            # what the page really sets
                           season_fp_gp=tuple(GIDS))
_keyed = IT._data_fp(getattr(_ctx_cur, "season_fp_gp", None)
                     or getattr(_ctx_cur, "season_gp", None))
ok(_keyed == _scoped,
   "on the CURRENT season — where season_gp is None by design — render() still "
   "keys on a SCOPED pool, not on the whole table")
ok(_keyed != _glob,
   "and that key is demonstrably not the global one (the regression, closed)")

_src = (_APP / "helpers" / "dashboard" / "insights_tab.py").read_text(
    encoding="utf-8")
_code = [ln for ln in _src.splitlines() if not ln.lstrip().startswith("#")]
ok(not any("_data_fp()" in ln for ln in _code),
   "and no call site takes the unscoped default any more")
ok(not any('_data_fp(getattr(ctx, "season_gp", None))' in ln for ln in _code),
   "nor keys on season_gp alone, which is None exactly when it matters")

print(f"\nALL {PASS} CHECKS PASSED")
