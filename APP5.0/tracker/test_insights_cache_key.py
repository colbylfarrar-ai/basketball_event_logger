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
from database.db import query                         # noqa: E402
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

# The fingerprint is a pure function of these aggregates, so the two write
# directions can be checked without touching the real database.
_old = (_mine["c"], _mine["m"])
_out_of_pool = (_mine["c"], _mine["m"])        # a row in a game we do not read
_in_pool = (_mine["c"] + 1, _mine["m"] + 1)    # a row in one of our own games
_old_global = (_tot["c"], _tot["m"])
_new_global = (_tot["c"] + 1, _tot["m"] + 1)

ok(_old_global != _new_global,
   "under the OLD global key, any write anywhere moved the key — this is the "
   "regression: 85s on someone else's game")
ok(_old == _out_of_pool,
   "under the scoped key an out-of-pool write leaves it untouched, so the "
   "cache stays warm")
ok(_old != _in_pool,
   "while a write to one of this pool's own games still busts it — her numbers "
   "really did change, and a stale page is worse than a slow one")

_outside = _tot["c"] - _mine["c"]
ok(_outside >= 0,
   f"{_outside} of {_tot['c']} event rows ({100.0 * _outside / _tot['c']:.0f}%) "
   f"live outside this pool and used to invalidate it")


print("\n-- the call site passes the scope ----------------------------------")

_src = (_APP / "helpers" / "dashboard" / "insights_tab.py").read_text(
    encoding="utf-8")
ok("_data_fp(getattr(ctx, \"season_gp\", None))" in _src,
   "render() keys on the pool it is viewing, not on the whole table")
_code = [ln for ln in _src.splitlines() if not ln.lstrip().startswith("#")]
ok(not any("_data_fp()" in ln for ln in _code),
   "and no call site takes the unscoped default any more")

print(f"\nALL {PASS} CHECKS PASSED")
