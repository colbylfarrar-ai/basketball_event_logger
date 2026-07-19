"""
Spec 2.3 — rating explainability payload + depth-of-track confidence tier.

Runs against the local snapshot (read-only): the explain payload must exist
for rated players, mirror _OVERALL_PARTS, and carry a coherent shrink story;
confidence_tier must hit all four tiers across its input space and name a
next action. Run: python tracker/test_rating_explain.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.player_ratings as PR                # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("explain payload (real snapshot, gender=F)")
ratings = PR.player_ratings(gender="F", explain=True)
if not ratings:
    print("  (no players in snapshot — skipped)")
else:
    pid, row = max(ratings.items(), key=lambda kv: kv[1]["GP"] or 0)
    ex = row.get("_explain")
    ok(ex is not None, "payload present")
    names = [p["part"] for p in ex["parts"]]
    ok(names == [n for n, _w in PR._OVERALL_PARTS],
       "parts mirror _OVERALL_PARTS order")
    ok(all(p["weight"] > 0 for p in ex["parts"]), "weights positive")
    sh = ex["shrink"]
    ok(sh["k"] == PR.RATING_K_GAMES, "k matches engine constant")
    ok(sh["final"] == row["OVERALL"], "final == published OVERALL")
    lo, hi = sorted((sh["raw"], sh["anchor"]))
    ok(lo - 0.11 <= sh["final"] <= hi + 0.11,
       f"shrunk rating sits between raw and anchor ({sh})")
    plain = PR.player_ratings(gender="F")
    ok(plain and "_explain" not in next(iter(plain.values())),
       "no payload unless explain=True")

print("confidence tier")
seen = set()
for g in (0, 1, 2, 4, 8, 20):
    for cov in (None, 0, 30, 60, 90, 100):
        idx, label, clr, action = PR.confidence_tier(g, cov)
        seen.add(idx)
        assert label == PR.CONF_TIERS[idx] and action
ok(seen == {0, 1, 2, 3}, f"all four tiers reachable ({sorted(seen)})")
i0 = PR.confidence_tier(0, None)[0]
i1 = PR.confidence_tier(20, 100)[0]
ok(i0 == 0 and i1 == 3, "monotone endpoints (0 games none -> 0, deep -> 3)")
ok("track" in PR.confidence_tier(1, 80)[3], "thin games -> 'track more' action")
ok("tag" in PR.confidence_tier(12, 10)[3], "low coverage -> 'tag' action")

print(f"\nALL {PASS} CHECKS PASSED")
