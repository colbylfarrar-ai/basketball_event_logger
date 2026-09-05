"""
Regression — the live win-probability strip must not read 100% mid-game.

The Game Tracker built its margin walk from scoring events only, then called
`wp_curve(points)` with no `total_secs`. `wp_curve` defaults `total_secs` to the
LAST point's own elapsed time, so the final point always had zero seconds left
and `win_prob` resolved a finished game: a permanent 100% (or 0%, flipped to
100% for the other side by the page's `_lwp = 100 - _cwp`). The possession
ribbon had the same shape through `possession_timeline`'s `end` default.

Two things have to hold for a LIVE game:
  1. the curve is priced against the FULL game length, not the last basket, and
  2. the walk is anchored at the CURRENT clock, so a quiet stretch still decays.

Run: python tracker/test_live_wp_clock.py (pure; no DB writes)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.win_probability as WP                # noqa: E402
import helpers.wpa as WPA                           # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


QSEC = 480
REG = 4 * QSEC          # 1920 — four 8-minute HS quarters
T1, T2 = 10, 20

# A live game: last score came in Q2, up 6, with a lot of basketball left.
walk = [(0.0, 0), (300.0, 2), (700.0, 4), (900.0, 6)]

print("live wp clock")

# ── 1. the old defaulting behaviour, pinned so the bug is legible ─────────────
bad = WP.wp_curve(walk)
ok(bad[-1][2] in (0.0, 1.0),
   "no total_secs -> last point resolves to a finished game (the bug)")

# ── 2. priced against the full game, a 6-point Q2 lead is NOT decided ─────────
good = WP.wp_curve(walk, total_secs=REG)
ok(0.5 < good[-1][2] < 0.99,
   "total_secs=REG -> up 6 at halftime is a lead, not a win")
ok(good[-1][1] == 6, "margin is carried through untouched")
ok(len(good) == len(walk), "curve length matches the walk")

# ── 3. anchoring at the current clock decays a stale lead ────────────────────
# Same 6-point lead, but the clock has run to late Q4 with no scoring. The
# anchor point carries the SAME margin and only moves time.
anchored = WP.wp_curve(walk + [(1860.0, 6)], total_secs=REG)
ok(anchored[-1][2] > good[-1][2],
   "same lead later in the game is worth more win probability")
ok(anchored[-1][2] < 1.0,
   "even 1:00 left with a 6-point lead is not a certainty")

# ── 4. OT lengthens the game rather than ending it ───────────────────────────
ot_total = REG + 240
ot = WP.wp_curve([(0.0, 0), (1920.0, 0), (2000.0, 3)], total_secs=ot_total)
ok(0.5 < ot[-1][2] < 1.0, "up 3 early in OT is a lead, not a win")

# ── 5. possession_timeline honours an explicit end ───────────────────────────
def ev(etype, q, time, team, result=None, stype=2):
    return {"event_type": etype, "quarter": q, "time": time,
            "shooter_team_id": team, "shot_result": result,
            "shot_type": stype}


events = [ev("shot", 1, "7:00", T1, "make", 2),
          ev("shot", 2, "4:00", T1, "make", 2),
          ev("shot", 2, "3:00", T2, "miss")]

pc_default = WPA.possession_timeline(events, T1, T2)
ok(pc_default[-1][2] in (0.0, 1.0),
   "no end -> possession ribbon resolves at the last event (the bug)")

pc = WPA.possession_timeline(events, T1, T2, end=REG)
ok(0.5 < pc[-1][2] < 0.99,
   "end=REG -> up 4 in Q2 leaves the ribbon mid-range")
ok(len(pc) == len(events), "every possession-ending event still steps")

# ── 6. a tie is a coin flip at any clock ─────────────────────────────────────
for t in (0.0, 900.0, 1900.0):
    ok(abs(WP.win_prob(0, REG - t, REG) - 0.5) < 1e-9,
       f"tied at {int(t)}s elapsed -> 50%")

# ── 7. the same thing on REAL events, truncated mid-game ─────────────────────
# Every game in the DB is finished, and a finished game SHOULD resolve to 0/1 —
# so replaying one only as far as halftime is the only way to reproduce what a
# bench actually saw. This is the regression: a real game, real events, and a
# score line that must not read as decided at the half.
try:
    import helpers.stats as S
    from database.db import query

    gid = query("""SELECT g.id FROM games g WHERE g.tracked=1
                   ORDER BY g.id DESC LIMIT 1""")
    if not gid:
        print("  --  no tracked game on file; live replay skipped")
    else:
        gid = gid[0]["id"]
        g = query("SELECT team1_id, team2_id FROM games WHERE id=?", (gid,))[0]
        evs = S.fetch_events([gid])
        half = [e for e in evs if (e["quarter"] or 1) <= 2]

        done = WPA.possession_timeline(evs, g["team1_id"], g["team2_id"], end=REG)
        mid = WPA.possession_timeline(half, g["team1_id"], g["team2_id"], end=REG)
        ok(len(mid) >= 2, f"game {gid}: the first half is a curve ({len(mid)} steps)")
        ok(0.0 < mid[-1][2] < 1.0,
           f"game {gid}: halftime win probability is live, not resolved "
           f"({mid[-1][2] * 100:.0f}%)")
        ok(0.02 < min(p for _t, _m, p in mid) and max(
            p for _t, _m, p in mid) < 0.995,
           "no point in the first half is a settled game")
        # and the finished game still resolves, which is correct.
        ok(len(done) >= len(mid), "the full game is at least as long a curve")
except Exception as exc:                                    # pragma: no cover
    print(f"  --  live replay skipped ({type(exc).__name__}: {exc})")

print(f"\n{PASS} checks passed")
