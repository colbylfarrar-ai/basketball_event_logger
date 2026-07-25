"""
trends.game_meta scoping — the query that cost 71% of the insight-feed build.

`player_game_log` used to run `games JOIN teams JOIN teams` with NO where-clause
on every call: the full 13k-row games table, ~48 ms a pop. `insights.form_edges`
calls it once per player, so a 242-player league burned 11.6 s of 1-vCPU CPU to
produce four insight lines.

What must hold after the fix:
  1. game_meta returns exactly the requested games and nothing else.
  2. the log built with an injected `meta` is IDENTICAL to the log built without
     one — the optimisation must not change a single output row.
  3. chunking survives more ids than sqlite's host-parameter ceiling.
  4. form_edges is materially faster than the per-player-join cost it replaced.

Run: python tracker/test_trends_scope.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.trends as TR                        # noqa: E402
import helpers.seasons as SEAS                     # noqa: E402
import helpers.stats as S                          # noqa: E402
import helpers.insights as IN                      # noqa: E402
from database.db import query                      # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("\n-- game_meta scoping ---------------------------------------------")

all_gids = [r["id"] for r in query("SELECT id FROM games ORDER BY id")]
ok(len(all_gids) > 0, f"book has games ({len(all_gids)})")

ok(TR.game_meta([]) == {}, "empty id list returns empty dict")
ok(TR.game_meta([None, None]) == {}, "all-None id list returns empty dict")

some = all_gids[:5]
m = TR.game_meta(some)
ok(set(m) == set(some), "returns exactly the requested ids")
ok(all({"id", "date", "team1_id", "team2_id", "n1", "n2"} <= set(r.keys())
       for r in m.values()), "rows carry the columns the log reads")

ok(TR.game_meta(some + some) == m, "duplicate ids are de-duplicated, not doubled")
ok(TR.game_meta([-999]) == {}, "unknown id yields no row rather than raising")

# chunking: force more ids than one statement can bind
big = all_gids[:TR._SQL_VARS + 50] if len(all_gids) > TR._SQL_VARS + 50 else all_gids
mb = TR.game_meta(big)
ok(set(mb) == set(big), f"chunked fetch covers {len(big)} ids across statements")

print("\n-- injected meta changes nothing ---------------------------------")

gids = sorted(SEAS.game_pool("2025-2026", gender="F", tracked_only=True))
ok(len(gids) > 0, f"tracked pool non-empty ({len(gids)} games)")
ev = S.fetch_events(gids)
boxes = S.player_game_boxes(events=ev)
ok(len(boxes) > 0, f"player boxes built ({len(boxes)} players)")

shared = TR.game_meta(gids)
checked = 0
for pid in list(boxes)[:25]:
    a = TR.player_game_log(pid, boxes=boxes)                 # self-scoped
    b = TR.player_game_log(pid, boxes=boxes, meta=shared)    # injected
    assert a == b, f"FAIL: log differs for pid {pid}"
    checked += 1
ok(checked == 25, f"log identical with and without injected meta ({checked} players)")

nonempty = [p for p in boxes if TR.player_game_log(p, boxes=boxes, meta=shared)]
ok(len(nonempty) > 0, f"logs are actually populated ({len(nonempty)} non-empty)")

one = nonempty[0]
log = TR.player_game_log(one, boxes=boxes, meta=shared)
ok(all(r["date"] is None or isinstance(r["date"], str) for r in log),
   "rows carry a date")
ok(log == sorted(log, key=lambda r: (r["date"] or "", r["game_id"])),
   "log stays oldest-first")
ok(all(r["opp"] for r in log), "every row names an opponent")

print("\n-- the regression this exists to prevent -------------------------")

t0 = time.time()
query("""SELECT g.id, g.date, g.team1_id, g.team2_id, t1.name n1, t2.name n2
         FROM games g JOIN teams t1 ON t1.id = g.team1_id
                      JOIN teams t2 ON t2.id = g.team2_id""")
unscoped = time.time() - t0

t0 = time.time()
TR.game_meta(gids)
scoped = time.time() - t0
print(f"  unscoped join {unscoped * 1000:6.1f} ms   scoped {scoped * 1000:6.1f} ms")
ok(scoped < unscoped, "scoped fetch beats the unscoped join it replaced")

t0 = time.time()
fe = IN.form_edges(ev, {})
elapsed = time.time() - t0
budget = unscoped * len(boxes) * 0.5
print(f"  form_edges {elapsed:.2f}s over {len(boxes)} players "
      f"(old per-player-join floor was ~{unscoped * len(boxes):.1f}s)")
ok(elapsed < budget,
   f"form_edges under half the old join floor ({elapsed:.2f}s < {budget:.2f}s)")
ok(isinstance(fe, dict), "form_edges still returns its dict")

print(f"\n{PASS} checks passed.")
