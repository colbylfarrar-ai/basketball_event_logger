"""Possession-length tempo cuts: 8 / 20, and only one copy of them.

The app used to hold the same cut in four places with two different values --
`playtypes._tempo` at 6/14, `team_analytics.POSS_BUCKETS` at 6/14,
`insights_team` at 6/15, and `gameflow`'s fast-break split at 6 -- so
"transition" already meant two different things depending on which tab a coach
was looking at. team_analytics now owns the numbers and everything else reads
them.

The values themselves come from the 43-game sample (docs/DB_AUDIT_2026-07-28
section 2.2 plus a per-2s follow-up): 8s is where the share of putback/
transition-tagged shots falls off a cliff (51% at 7-8s, 25% at 9-10s), and 21s+
is 0.70 PPS -- the worst and largest bucket in the database -- against a flat
0.78-0.84 plateau from 4s to 20s. The old split did not separate its own last
two buckets (0.794 vs 0.760); this one is monotone at roughly 0.10 PPS a step.

The last check re-measures that on whatever is in the DB now, so a future
sample that disagrees fails here instead of quietly shipping.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/test_tempo_cuts.py
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


def test_the_cuts():
    import helpers.team_analytics as TA
    import helpers.playtypes as PT

    ok(TA.TEMPO_TRANSITION_MAX == 8, "transition ends at 8s")
    ok(TA.TEMPO_EARLY_MAX == 20, "early offense ends at 20s")
    ok(PT.TEMPO_TRANSITION_MAX == TA.TEMPO_TRANSITION_MAX
       and PT.TEMPO_EARLY_MAX == TA.TEMPO_EARLY_MAX,
       "playtypes re-exports the same numbers, it does not restate them")

    cases = [(None, None), (0, None), (-3, None),
             (1, "transition"), (8, "transition"),
             (9, "early"), (20, "early"),
             (21, "halfcourt"), (600, "halfcourt")]
    for secs, want in cases:
        ok(PT.tempo_bucket(secs) == want, f"{secs}s -> {want}")
    ok(PT._tempo is PT.tempo_bucket, "the old private name still resolves")


def test_every_surface_agrees():
    """POSS_BUCKETS, the tempo play types and the fast-break split are one cut."""
    import helpers.team_analytics as TA
    import helpers.playtypes as PT

    names = [b[0] for b in TA.POSS_BUCKETS]
    ok("8" in names[0] and "9" in names[1] and "20" in names[1]
       and "21" in names[2],
       f"bucket labels carry the live numbers: {names}")

    # Each bucket's (lo, hi) has to select exactly what tempo_bucket() calls it.
    keys = ["transition", "early", "halfcourt"]
    for (label, lo, hi), key in zip(TA.POSS_BUCKETS, keys):
        inside = [s for s in range(1, 40) if lo < s <= hi]
        ok(inside and all(PT.tempo_bucket(s) == key for s in inside),
           f"{label} holds exactly the {key} seconds")


def test_the_cuts_still_beat_the_old_ones():
    """Re-measure on the live DB: monotone PPS, and the 20s cliff is real."""
    from database.db import query

    rows = query(
        """SELECT possession_secs s, shot_type, shot_result
           FROM game_events
           WHERE event_type='shot' AND possession_secs IS NOT NULL
             AND possession_secs > 0""")
    if len(rows) < 500:
        print(f"  -- only {len(rows)} timed shots on file; measurement skipped")
        return

    def pps(sel):
        n = len(sel)
        pts = sum((r["shot_type"] or 0) for r in sel if r["shot_result"] == "make")
        return n, (pts / n if n else 0.0)

    def split(lo, hi):
        a = pps([r for r in rows if r["s"] <= lo])
        b = pps([r for r in rows if lo < r["s"] <= hi])
        c = pps([r for r in rows if r["s"] > hi])
        return a, b, c

    (an, ap), (bn, bp), (cn, cp) = split(8, 20)
    print(f"     8/20  transition {an} {ap:.3f} | early {bn} {bp:.3f} "
          f"| halfcourt {cn} {cp:.3f}")
    ok(ap > bp > cp, "8/20 is monotone: transition > early > half-court PPS")
    ok(bp - cp >= 0.05,
       f"the 20s cliff is a real gap, not noise ({bp - cp:.3f} PPS)")

    (_oa, oap), (_ob, obp), (_oc, ocp) = split(6, 14)
    print(f"     6/14  transition {oap:.3f} | early {obp:.3f} "
          f"| halfcourt {ocp:.3f}")
    ok((bp - cp) > (obp - ocp),
       "the new cut separates early from half-court better than the old one")


if __name__ == "__main__":
    print("tempo cuts")
    test_the_cuts()
    test_every_surface_agrees()
    test_the_cuts_still_beat_the_old_ones()
    print(f"\n{PASSED} checks passed")
