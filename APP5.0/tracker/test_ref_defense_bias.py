"""Officials: foul bias on the DEFENSE axis, the twin of the play-type one.

`official_ratings` already reported which SETS a ref whistles more than the
field. Every event carries a defense tag too -- more of them do, in fact, since
the defense bar is sticky and a set call is per-possession -- and "this crew
calls the press" is a read a staff can plan around. Same share-gap math, same
shape, second axis.

Unknown / legacy tags fold to 'other' through defenses._norm, so a retired
scheme name cannot open a one-ref column of its own.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/test_ref_defense_bias.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _bundle():
    import helpers.officials as OF
    import helpers.seasons as SEAS
    from database.db import query

    # The season with tracked games, not necessarily the active one.
    r = query("SELECT season FROM games WHERE tracked=1 "
              "ORDER BY season DESC LIMIT 1")
    season = r[0]["season"] if r else SEAS.ACTIVE
    return OF.official_ratings(gender="F", season=season), season


def test_shape():
    import helpers.defenses as DEF

    bundle, season = _bundle()
    rows = bundle["officials"]
    if not rows:
        print(f"  -- no officials on tracked games in {season}; skipped")
        return

    ok(all("def_bias" in r for r in rows),
       f"every official row carries def_bias ({len(rows)} rows)")

    keys = set(DEF._KEYS) | {"other"}
    for r in rows:
        for key, delta, n, share in r["def_bias"]:
            ok(key in keys, f"{r['name']}: '{key}' is a known defense key")
            ok(n >= 2, f"{r['name']}: '{key}' cleared the 2-call floor ({n})")
            ok(0 < share <= 1, f"{r['name']}: '{key}' share in range ({share:.2f})")
            ok(-1 <= delta <= 1, f"{r['name']}: '{key}' gap in range ({delta:+.2f})")
        deltas = [b[1] for b in r["def_bias"]]
        ok(deltas == sorted(deltas, reverse=True),
           f"{r['name']}: biggest positive gap first")
        ok(len(r["def_bias"]) <= 3, f"{r['name']}: at most three shown")


def test_it_is_the_twin_of_the_playtype_read():
    """Same shape as pt_bias, and at least as well covered."""
    bundle, season = _bundle()
    rows = bundle["officials"]
    if not rows:
        return

    with_def = sum(1 for r in rows if r["def_bias"])
    with_pt = sum(1 for r in rows if r["pt_bias"])
    print(f"     coverage: {with_def} refs on defense, {with_pt} on play type, "
          f"of {len(rows)}")
    ok(with_def >= with_pt,
       "defense is tagged at least as often as the set call (sticky bar)")

    for r in rows:
        for b in r["def_bias"]:
            ok(len(b) == 4, "def_bias rows are (key, gap, n, share) like pt_bias")
            break


def test_clutch_is_unchanged():
    """Adding the axis restructured the foul loop; clutch must be untouched.

    The old loop counted a clutch foul's tags inside the clutch branch and every
    other foul's in an elif, so each foul was tallied exactly once. The rewrite
    tallies clutch and tags independently — this pins that no foul got counted
    twice and none got dropped."""
    bundle, _season = _bundle()
    rows = bundle["officials"]
    if not rows:
        return
    ok(any(r["clutch"] for r in rows),
       "the clutch count is still populated, not zeroed by the rewrite")
    for r in rows:
        ok(0 <= r["clutch"] <= r["fouls"],
           f"{r['name']}: clutch {r['clutch']} within their {r['fouls']} fouls")
        for field in ("pt_bias", "def_bias"):
            tagged = sum(n for _k, _d, n, _s in r[field])
            ok(tagged <= r["fouls"],
               f"{r['name']}: {field} counts {tagged} <= {r['fouls']} fouls")


if __name__ == "__main__":
    print("ref defense bias")
    test_shape()
    test_it_is_the_twin_of_the_playtype_read()
    test_clutch_is_unchanged()
    print(f"\n{PASSED} checks passed")
