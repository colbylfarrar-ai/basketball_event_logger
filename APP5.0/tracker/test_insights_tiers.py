"""
test_insights_tiers.py — game-count tier gates + the new engine generators.

Pure-engine (no DB): exercises the tier math, the new player form generator, and
the six new team generators through synthetic `extras` feeds.
  1. tier_factor / tier_gate — bounds, floors, monotonic
  2. _g_form — hot / cold / gated on a thin log
  3. _t_keys — signature-stat record split fires + gates
  4. _t_vs_scheme / _t_runs / _t_rest / _t_predictable / _t_pv_leak — fire + gate
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import helpers.insights as IN                     # noqa: E402
import helpers.team_insights as TIN               # noqa: E402


# ── tier math ─────────────────────────────────────────────────────────────────
class TestTierMath(unittest.TestCase):
    def test_factor_bounds(self):
        self.assertAlmostEqual(IN.tier_factor(0), 0.35)
        self.assertAlmostEqual(IN.tier_factor(2), 0.35)     # floored
        self.assertAlmostEqual(IN.tier_factor(20), 1.0)
        self.assertAlmostEqual(IN.tier_factor(40), 1.0)     # capped
        self.assertAlmostEqual(IN.tier_factor(10), 0.5)

    def test_gate_scales_and_floors(self):
        self.assertEqual(IN.tier_gate(22, 20), 22.0)        # full book
        self.assertEqual(IN.tier_gate(22, 3, 8), 8)         # scout floor
        self.assertLess(IN.tier_gate(22, 6), 22)            # district relaxed
        self.assertGreaterEqual(IN.tier_gate(22, 6), 8)

    def test_gate_monotonic(self):
        vals = [IN.tier_gate(22, gp) for gp in range(1, 25)]
        self.assertEqual(vals, sorted(vals))


# ── player form generator ─────────────────────────────────────────────────────
def _row(gp=10):
    return {"GP": gp, "name": "T Test"}


class TestForm(unittest.TestCase):
    def test_hot(self):
        d = {"form": {"last3_ppg": 22.0, "season_ppg": 14.0, "delta": 8.0,
                      "rtg_avg": 8.1, "streak": 4, "n": 3}}
        c = IN._g_form(_row(), {}, d)
        self.assertIsNotNone(c)
        self.assertIn("Heating up", c["text"])
        self.assertIn("straight", c["text"])         # streak surfaced

    def test_cold(self):
        d = {"form": {"last3_ppg": 6.0, "season_ppg": 14.0, "delta": -8.0,
                      "rtg_avg": None, "streak": 0, "n": 3}}
        c = IN._g_form(_row(), {}, d)
        self.assertIsNotNone(c)
        self.assertIn("Cooling off", c["text"])

    def test_gates_small_swing(self):
        d = {"form": {"last3_ppg": 15.0, "season_ppg": 14.0, "delta": 1.0,
                      "rtg_avg": None, "streak": 0, "n": 3}}
        self.assertIsNone(IN._g_form(_row(), {}, d))

    def test_gates_thin_book(self):
        d = {"form": {"last3_ppg": 22.0, "season_ppg": 14.0, "delta": 8.0,
                      "rtg_avg": None, "streak": 0, "n": 3}}
        self.assertIsNone(IN._g_form(_row(gp=4), {}, d))     # under GP 5


# ── new team generators (called directly with an extras-loaded d) ──────────────
class TestTeamGenerators(unittest.TestCase):
    def test_keys_fires(self):
        goals = [{"key": "eFG", "label": "eFG%", "target": 0.52,
                  "win_high": True, "fmt": "pct"},
                 {"key": "TOVr", "label": "Turnover rate", "target": 0.16,
                  "win_high": False, "fmt": "pct"},
                 {"key": "oeFG", "label": "Opp eFG%", "target": 0.48,
                  "win_high": False, "fmt": "pct"},
                 {"key": "ORBpct", "label": "Off. rebound %", "target": 0.30,
                  "win_high": True, "fmt": "pct"}]
        record = [{"n": 4, "wins": 3, "losses": 0, "games": 3},
                  {"n": 3, "wins": 2, "losses": 1, "games": 3},
                  {"n": 1, "wins": 0, "losses": 2, "games": 2},
                  {"n": 0, "wins": 0, "losses": 1, "games": 1}]
        d = {"keys": {"goals": goals, "record": record}}
        c = TIN._t_keys(1, {}, {}, {}, d)
        self.assertIsNotNone(c)
        self.assertIn("keys", c["text"].lower())
        self.assertIn("eFG%", c["text"])            # top key named

    def test_keys_gates_no_split(self):
        goals = [{"key": "eFG", "label": "eFG%", "target": 0.5,
                  "win_high": True, "fmt": "pct"}] * 3
        # hitting all vs none produces the same ~.5 win% → no split
        record = [{"n": 3, "wins": 2, "losses": 2, "games": 4},
                  {"n": 0, "wins": 2, "losses": 2, "games": 4}]
        d = {"keys": {"goals": goals, "record": record}}
        self.assertIsNone(TIN._t_keys(1, {}, {}, {}, d))

    def test_vs_scheme_fires(self):
        d = {"vs_scheme": [
            {"family": "man", "label": "Man", "PPP": 0.95, "poss": 60},
            {"family": "zone", "label": "Zone", "PPP": 0.66, "poss": 22}]}
        c = TIN._t_vs_scheme(1, {}, {}, {}, d)
        self.assertIsNotNone(c)
        self.assertIn("zone", c["text"].lower())

    def test_vs_scheme_gates_small_gap(self):
        d = {"vs_scheme": [
            {"family": "man", "label": "Man", "PPP": 0.95, "poss": 60},
            {"family": "zone", "label": "Zone", "PPP": 0.90, "poss": 22}]}
        self.assertIsNone(TIN._t_vs_scheme(1, {}, {}, {}, d))

    def test_runs_fires(self):
        d = {"runs": {"gp": 8, "made_pg": 1.6, "allowed_pg": 0.4,
                      "biggest": 14}}
        c = TIN._t_runs(1, {}, {}, {}, d)
        self.assertIsNotNone(c)
        self.assertIn("Run machine", c["text"])

    def test_rest_fires(self):
        d = {"rest": {"overall_mov": 4.0, "buckets": [
            {"key": "b2b", "label": "Back-to-back (1 day)", "gp": 4,
             "w": 1, "l": 3, "mov": -8.0, "delta": -12.0}]}}
        c = TIN._t_rest(1, {}, {}, {}, d)
        self.assertIsNotNone(c)
        self.assertIn("Fades", c["text"])

    def test_predictable_fires(self):
        d = {"predict": {"rated": True, "predictability": 74.0,
                         "top_set": "Isolation", "top_share": 58.0,
                         "tagged": 80}}
        c = TIN._t_predictable(1, {}, {}, {}, d)
        self.assertIsNotNone(c)
        self.assertIn("scout", c["text"].lower())

    def test_pv_leak_fires(self):
        d = {"pv": {"offense": {"poss": 200, "tov_pct": 0.26}}}
        c = TIN._t_pv_leak(1, {}, {}, {}, d)
        self.assertIsNotNone(c)
        self.assertIn("beat themselves", c["text"])

    def test_pv_gates_low_poss(self):
        d = {"pv": {"offense": {"poss": 40, "tov_pct": 0.30}}}
        self.assertIsNone(TIN._t_pv_leak(1, {}, {}, {}, d))


if __name__ == "__main__":
    unittest.main()
