"""
test_insights_impact.py — the impact-vs-box insight generator (_g_impact).

Pure-engine test (no DB): feeds league_insights a synthetic player table +
impact_map and checks the two divergence reads fire (and gate) correctly:
  1. "quiet winner"  — modest Game Score, strongly positive RAPM
  2. "stats over substance" — big Game Score, negative RAPM
  3. gates — thin possessions / missing impact / league-average both ways → no line
  4. impact_map merge — rapm + war inputs combine, _meta skipped
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import helpers.insights as IN                    # noqa: E402


def _row(name, gsg, gp=8):
    """Minimal table row the miner needs (other generators just won't fire)."""
    return {"name": name, "GS/G": gsg, "GP": gp}


def _pool_table(n=10, gsg=8.0):
    """A flat league pool so z-scores are driven by the outliers we add."""
    t = {}
    for i in range(n):
        # tiny spread so sd is defined but small signals don't fire
        t[100 + i] = _row(f"P{i}", gsg + (i % 3) * 0.5)
    return t


def _impact(table, rapm=0.0, poss=600):
    return {pid: {"rapm": rapm + (i % 3) * 0.2, "poss": poss}
            for i, pid in enumerate(table)}


class TestImpactGenerator(unittest.TestCase):
    def test_quiet_winner_fires(self):
        table = _pool_table()
        table[1] = _row("Quiet", 8.0)            # league-average box line
        imp = _impact(table)
        imp[1] = {"rapm": 9.0, "war": 1.4, "poss": 800}   # elite on-floor
        feed = IN.league_insights(table, impact=imp)
        lines = feed.get(1, [])
        self.assertTrue(any(l["metric"] == "Impact" for l in lines), lines)
        line = next(l for l in lines if l["metric"] == "Impact")
        self.assertIn("Quiet winner", line["text"])
        self.assertIn("HoopWAR", line["text"])
        self.assertGreater(line["z"], 0)

    def test_empty_stats_fires(self):
        table = _pool_table()
        table[2] = _row("Empty", 18.0)           # huge box line
        imp = _impact(table)
        imp[2] = {"rapm": -6.0, "poss": 700}     # scoreboard says worse
        feed = IN.league_insights(table, impact=imp)
        lines = feed.get(2, [])
        self.assertTrue(any(l["metric"] == "Impact" for l in lines), lines)
        line = next(l for l in lines if l["metric"] == "Impact")
        self.assertIn("Stats over substance", line["text"])
        self.assertLess(line["z"], 0)

    def test_gates(self):
        table = _pool_table()
        table[3] = _row("Thin", 8.0)
        imp = _impact(table)
        imp[3] = {"rapm": 9.0, "poss": 100}      # elite but thin possessions
        feed = IN.league_insights(table, impact=imp)
        self.assertFalse(any(l["metric"] == "Impact"
                             for l in feed.get(3, [])))
        # average both ways → nothing (pool players themselves)
        feed2 = IN.league_insights(table, impact=_impact(table))
        for pid in table:
            self.assertFalse(any(l["metric"] == "Impact"
                                 for l in feed2.get(pid, [])))
        # no impact feed at all → generator silent, miner still runs
        feed3 = IN.league_insights(table)
        self.assertIsInstance(feed3, dict)

    def test_impact_map_merge(self):
        rapm = {1: {"RAPM": 4.0, "off_poss": 300, "def_poss": 250}}
        war = {"_meta": {"ppg": 50}, 1: {"WAR": 0.8},
               2: {"WAR": -0.2, "rapm": -1.5, "off_poss": 100, "def_poss": 90}}
        m = IN.impact_map(rapm=rapm, war=war)
        self.assertEqual(m[1]["rapm"], 4.0)
        self.assertEqual(m[1]["poss"], 550)
        self.assertEqual(m[1]["war"], 0.8)
        self.assertEqual(m[2]["rapm"], -1.5)     # falls back to war table's rapm
        self.assertEqual(m[2]["poss"], 190)
        self.assertNotIn("_meta", m)


if __name__ == "__main__":
    unittest.main()
