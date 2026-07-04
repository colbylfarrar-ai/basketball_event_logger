"""
test_lineup_adjust.py — opponent-adjusted 5-man unit ratings (helpers/lineups).

Pure test (no DB for the math): synthetic possessions + a prebuilt floor map +
quality map drive unit_ratings via its events/floor/quality params. Covers:
  1. two same-team units with IDENTICAL raw scoring — the one that did it
     against STRONG opposing fives rates higher after adjustment
  2. ci95 shrinks as possessions grow
  3. thin regression sample → adjusted False, Adj* == raw
  4. back-compat keys (ORtg/DRtg/Net/NetAdj) unchanged by the upgrade
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import helpers.lineups as LU                     # noqa: E402

TEAM, OPP = 1, 2
UNIT_A = frozenset(range(11, 16))      # faces WEAK opposing fives
UNIT_B = frozenset(range(21, 26))      # faces STRONG opposing fives
WEAK_FIVE = frozenset(range(51, 56))   # rated 40
STRONG_FIVE = frozenset(range(61, 66))  # rated 60

QUALITY = {p: 55.0 for p in range(11, 16)}
QUALITY.update({p: 55.0 for p in range(21, 26)})
QUALITY.update({p: 40.0 for p in WEAK_FIVE})
QUALITY.update({p: 60.0 for p in STRONG_FIVE})


def _mk(n_each=150, make_vs_weak=0.55, make_vs_strong=0.35):
    """Alternating offensive possessions for UNIT_A (vs weak) and UNIT_B
    (vs strong) with the SAME observed make rate for both units, plus mirrored
    defensive possessions so DRtg exists. Deterministic make pattern."""
    events, floor = [], {}
    eid = [0]

    def _poss(five, opp_five, offense, make):
        eid[0] += 1
        e = {"id": eid[0], "game_id": 1 + eid[0] % 4,
             "event_type": "shot",
             "shooter_team_id": TEAM if offense else OPP,
             "shot_result": "make" if make else "miss", "shot_type": 2}
        events.append(e)
        floor[eid[0]] = {TEAM: five, OPP: opp_five}

    for i in range(n_each):
        # both units make exactly 45% of their own shots (same raw offense)
        mk = (i % 20) < 9
        _poss(UNIT_A, WEAK_FIVE, True, mk)
        _poss(UNIT_B, STRONG_FIVE, True, mk)
        # defense: weak five scores 30% on A, strong five scores 60% on B
        _poss(UNIT_A, WEAK_FIVE, False, (i % 10) < 3)
        _poss(UNIT_B, STRONG_FIVE, False, (i % 10) < 6)
    return events, floor


class TestLineupAdjust(unittest.TestCase):
    def _units(self, events, floor, quality=QUALITY, **kw):
        with patch.object(LU, "query", lambda *a, **k: []):
            rows = LU.unit_ratings(TEAM, events=events, floor=floor,
                                   quality=quality, **kw)
        return {r["players"]: r for r in rows}

    def test_strong_schedule_unit_rates_higher_adjusted(self):
        events, floor = _mk()
        u = self._units(events, floor)
        a, b = u[tuple(sorted(UNIT_A))], u[tuple(sorted(UNIT_B))]
        self.assertTrue(a["adjusted"] and b["adjusted"])
        # identical raw offense; B allowed more raw (faced the strong five)
        self.assertEqual(a["ORtg"], b["ORtg"])
        self.assertLess(a["Net"] - b["Net"], 80)      # raw gap is large...
        self.assertGreater(a["Net"], b["Net"])
        # ...but adjustment closes most of it: B gains vs raw, A gives back
        self.assertGreater(b["AdjNet"], b["Net"])
        self.assertLess(a["AdjNet"], a["Net"])
        gap_raw = a["Net"] - b["Net"]
        gap_adj = a["AdjNet"] - b["AdjNet"]
        self.assertLess(abs(gap_adj), abs(gap_raw) * 0.6)

    def test_ci_shrinks_with_possessions(self):
        e_small, f_small = _mk(n_each=40)
        e_big, f_big = _mk(n_each=300)
        small = self._units(e_small, f_small)[tuple(sorted(UNIT_A))]
        big = self._units(e_big, f_big)[tuple(sorted(UNIT_A))]
        self.assertIsNotNone(small["ci95"])
        self.assertIsNotNone(big["ci95"])
        self.assertLess(big["ci95"], small["ci95"])
        self.assertIsNotNone(big["games_eq"])

    def test_thin_sample_falls_back_raw(self):
        events, floor = _mk(n_each=20)               # 80 poss < _MIN_REG_POSS
        u = self._units(events, floor, min_poss=10)
        a = u[tuple(sorted(UNIT_A))]
        self.assertFalse(a["adjusted"])
        self.assertEqual(a["AdjNet"], a["Net"])

    def test_backcompat_keys(self):
        events, floor = _mk()
        a = self._units(events, floor)[tuple(sorted(UNIT_A))]
        for k in ("players", "names", "off_poss", "def_poss", "poss",
                  "pts_for", "pts_against", "ORtg", "DRtg", "Net",
                  "NetAdj", "cred"):
            self.assertIn(k, a)
        # raw ORtg = makes/attempts × 2 pts × 100 (the (i%20)<9 pattern over
        # 150 possessions = 72 makes = 48%)
        self.assertAlmostEqual(a["ORtg"], 96.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
