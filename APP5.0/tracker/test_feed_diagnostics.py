"""
A broken engine must not look like an engine with nothing to say.

`build_feed` had fourteen `except Exception: pass` blocks. If an engine raised,
the coach got a quietly thinner feed and nobody -- not the coach, not the log,
not an admin panel -- could tell the difference between "this engine broke" and
"this player has no notable read". Failure was indistinguishable from silence.

Stages are still isolated (one broken engine must not empty the whole feed),
but they now report.

Run: python tracker/test_feed_diagnostics.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.insights as IN                      # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


class _Catch(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


print("\n-- stage table covers every kwarg league_insights takes -----------")

import inspect                                     # noqa: E402
sig = set(inspect.signature(IN.league_insights).parameters)
keys = {k for k, _fn, _t in IN._FEED_STAGES}
ok(keys <= sig, f"every stage key is a real league_insights kwarg ({len(keys)})")
ok(len(keys) == len(IN._FEED_STAGES), "no duplicate stage keys")
ok("impact" not in keys, "impact is the caller's, not a stage")
missing = sig - keys - {"table", "top", "impact"}
ok(not missing, f"no league_insights split kwarg is left unfed (missing: {missing})")

print("\n-- a raising stage is recorded, not swallowed --------------------")

boom_calls = []


def boom(events, *a):
    boom_calls.append(1)
    raise ValueError("engine exploded")


orig = IN._FEED_STAGES
try:
    IN._FEED_STAGES = (("guarded", boom, False),
                       ("q4", lambda ev: {}, False))
    diag = {}
    handler = _Catch()
    IN._log.addHandler(handler)
    try:
        feed = IN.build_feed({}, [], diagnostics=diag)
    finally:
        IN._log.removeHandler(handler)

    ok(boom_calls, "the failing stage actually ran")
    ok("guarded" in diag, "the failure is recorded under its stage key")
    ok("ValueError" in diag["guarded"], "the record names the exception type")
    ok("engine exploded" in diag["guarded"], "the record carries the message")
    ok("q4" not in diag, "a healthy stage records nothing")
    ok(isinstance(feed, dict), "the feed still returns rather than propagating")
    ok(any("guarded" in r.getMessage() for r in handler.records),
       "the failure is logged as well as recorded")
    ok(all(r.levelno >= logging.WARNING for r in handler.records),
       "logged at WARNING or above, not debug-only")

    # the isolation property the try/except existed for in the first place
    diag2 = {}
    IN._FEED_STAGES = (("guarded", boom, False), ("q4", boom, False))
    feed2 = IN.build_feed({}, [], diagnostics=diag2)
    ok(len(diag2) == 2, "every failing stage is recorded, not just the first")
    ok(isinstance(feed2, dict), "an all-broken feed still returns a dict")
finally:
    IN._FEED_STAGES = orig

print("\n-- diagnostics is optional ---------------------------------------")

feed = IN.build_feed({}, [])
ok(isinstance(feed, dict), "build_feed works with no diagnostics dict passed")
ok(IN.build_feed({}, [], top=1) == {}, "empty table still yields an empty feed")

print("\n-- a raising GENERATOR logs once, not per player -----------------")


def bad_gen(row, pools, d):
    raise RuntimeError("generator exploded")


orig_gens = IN._GENERATORS
try:
    IN._GENERATORS = [bad_gen]
    handler = _Catch()
    IN._log.addHandler(handler)
    try:
        table = {i: {"GP": 10, "MPG": 20} for i in range(50)}
        out = IN.league_insights(table)
    finally:
        IN._log.removeHandler(handler)
    ok(out == {}, "a broken generator yields no insights rather than crashing")
    hits = [r for r in handler.records if "bad_gen" in r.getMessage()]
    ok(len(hits) == 1,
       f"logged exactly once for 50 players, not 50 times (got {len(hits)})")
finally:
    IN._GENERATORS = orig_gens

print("\n-- the real feed still builds ------------------------------------")

import helpers.seasons as SEAS                     # noqa: E402
import helpers.stats as S                          # noqa: E402
import helpers.player_ratings as PR                # noqa: E402

gids = sorted(SEAS.game_pool("2025-2026", gender="F", tracked_only=True))
ev = S.fetch_events(gids)
table = PR.player_stat_table(gender="F", min_games=1, game_ids=set(gids))
diag = {}
feed = IN.build_feed(table, ev, top=None, diagnostics=diag)
print(f"  live: {len(feed)} players with insights, stage failures: {diag or 'none'}")
ok(len(feed) > 50, f"live feed still populated ({len(feed)} players)")
ok(diag == {}, f"no stage is currently failing in production code ({diag})")

print(f"\n{PASS} checks passed.")
