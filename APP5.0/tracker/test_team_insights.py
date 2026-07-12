"""
test_team_insights.py — the team insight miner (helpers/team_insights.py).

Pure-engine test (no DB): feeds team_insight_feed a synthetic tracked pack +
form dict and checks the generators fire and gate:
  1. luck — record vs Pythagorean divergence lines
  2. off-leak — high eFG% + mediocre ORtg names the leak
  3. quarter identity — a big Q3 swing headlines
  4. gates — thin schedules / league-average teams stay silent
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import helpers.team_insights as TIN              # noqa: E402


def _ts(**over):
    base = {"eFG": 48.0, "ORtg": 92.0, "oeFG": 47.0, "DRtg": 90.0,
            "TOVpct": 16.0, "ORBpct": 28.0, "DRBpct": 70.0, "pf_pg": 14.0,
            "three_share": 26.0, "TPpct": 31.0}
    base.update(over)
    return base


def _fm(**over):
    base = {"games": 12, "W": 7, "L": 5, "Luck_wins": 0.1, "Pyth_W": 6.9,
            "Pyth_L": 5.1, "close_w": 1, "close_l": 1, "close_wpct": 0.5,
            "Volatility": 11.0, "ceiling": 20, "floor": -18, "mom_delta": 0.5}
    base.update(over)
    return base


def _pack(n=8, q_swing_team=None):
    teams = list(range(1, n + 1))
    qfor, qagn = {}, {}
    for t in teams:
        qfor[t] = {1: 144, 2: 144, 3: 144, 4: 144}   # 12 gp × 12 pts/q
        qagn[t] = {1: 144, 2: 144, 3: 144, 4: 144}
    if q_swing_team:
        qfor[q_swing_team] = {1: 144, 2: 144, 3: 240, 4: 144}   # +8/g in Q3
    # realistic league spread so pool sd isn't degenerate (a flat pool makes
    # tiny deviations read as huge z)
    ts = {t: _ts(eFG=44.0 + t, ORtg=84.0 + 2 * t, oeFG=43.0 + t,
                 DRtg=84.0 + 1.5 * t, TOVpct=13.0 + t, ORBpct=24.0 + t,
                 DRBpct=66.0 + t, pf_pg=11.0 + t, three_share=22.0 + t,
                 TPpct=28.0 + t) for t in teams}
    return {"teams": teams, "ts": ts,
            "gp": {t: 12 for t in teams}, "qfor": qfor, "qagn": qagn}


class TestTeamMiner(unittest.TestCase):
    def test_luck_fires(self):
        pack = _pack()
        form = {t: _fm() for t in pack["teams"]}
        form[1] = _fm(W=10, L=2, Luck_wins=2.6, Pyth_W=7.4, Pyth_L=4.6)
        feed = TIN.team_insight_feed(pack=pack, form=form)
        lines = feed.get(1, [])
        self.assertTrue(any(l["metric"] == "Luck" for l in lines), lines)
        self.assertIn("Record flatters",
                      next(l for l in lines if l["metric"] == "Luck")["text"])

    def test_off_leak_names_turnovers(self):
        pack = _pack()
        form = {t: _fm() for t in pack["teams"]}
        pack["ts"][2] = _ts(eFG=56.0, ORtg=88.0, TOVpct=24.0)
        feed = TIN.team_insight_feed(pack=pack, form=form)
        lines = feed.get(2, [])
        line = next((l for l in lines if l["metric"] == "Off engine"), None)
        self.assertIsNotNone(line, lines)
        self.assertIn("turnovers", line["text"])

    def test_quarter_identity(self):
        pack = _pack(q_swing_team=3)
        form = {t: _fm() for t in pack["teams"]}
        feed = TIN.team_insight_feed(pack=pack, form=form)
        lines = feed.get(3, [])
        line = next((l for l in lines if l["metric"] == "Quarters"), None)
        self.assertIsNotNone(line, lines)
        self.assertIn("Q3", line["text"])

    def test_average_team_silent(self):
        pack = _pack()
        form = {t: _fm() for t in pack["teams"]}
        feed = TIN.team_insight_feed(pack=pack, form=form)
        # a mid-pool team deviates on nothing → no lines for it
        self.assertEqual(feed.get(4, []), [])

    def test_thin_schedule_gates(self):
        pack = _pack()
        pack["gp"] = {t: 1 for t in pack["teams"]}       # under MIN_TRACKED (2)
        form = {t: _fm(games=2) for t in pack["teams"]}  # under MIN_GAMES (3)
        form[1] = _fm(games=2, Luck_wins=3.0)
        pack["ts"][2] = _ts(eFG=60.0, ORtg=90.0, TOVpct=26.0)
        feed = TIN.team_insight_feed(pack=pack, form=form)
        self.assertEqual(feed, {})

    def test_scout_tier_fires(self):
        # a 3-game tournament book is the scout tier — it SHOULD earn its reads
        pack = _pack()
        pack["gp"] = {t: 3 for t in pack["teams"]}
        form = {t: _fm(games=3) for t in pack["teams"]}
        form[1] = _fm(games=3, W=3, L=0, Luck_wins=2.6, Pyth_W=1.6, Pyth_L=1.4)
        feed = TIN.team_insight_feed(pack=pack, form=form)
        self.assertTrue(any(l["metric"] == "Luck" for l in feed.get(1, [])),
                        feed.get(1))


if __name__ == "__main__":
    unittest.main()
