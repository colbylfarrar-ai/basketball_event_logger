"""
test_late_game.py — intentional-foul window detection (spec 2026-07-18 §4).

Throwaway-DB e2e (the test_turnover_types pattern). One synthetic game builds a
score state (home up 6 late), then fouls in and out of the window assert the
boundary conditions: trailing-side late foul flagged; leading-side, early, or
blowout fouls not; the produced free throws land in the damped set.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_lategame_")
os.environ["APP5_DATA_DIR"] = _TMP

from database.db import execute                 # noqa: E402
import helpers.game_events as GE                # noqa: E402
import helpers.stats as S                       # noqa: E402
import helpers.late_game as LG                  # noqa: E402


HOME, AWAY = 9001, 9002          # home leads late; away fouls to stop the clock
H_P, A_P = 9011, 9021            # one player each side is enough


def _seed():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(9001,'Home','4A','F'),(9002,'Away','4A','F')")
    execute("INSERT INTO players (id, team_id, name, number) VALUES "
            "(9011,9001,'H1',1),(9012,9001,'H2',2),"
            "(9021,9002,'A1',11),(9022,9002,'A2',12)")
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
            "VALUES (9400,9001,9002,'2026-01-05',1,'2025-2026')")


def _make(pid, q, time, pts=2):
    GE.log_event(9400, {"event_type": "shot", "quarter": q, "time": time,
                        "primary_player_id": pid, "shot_result": "make",
                        "shot_type": pts, "zone": "C"}, on_court=[])


def _foul(fouled, fouler, q, time):
    return GE.log_event(9400, {"event_type": "foul", "quarter": q, "time": time,
                               "primary_player_id": fouled,
                               "secondary_player_id": fouler}, on_court=[])


def _ft(pid, q, time, result="make"):
    return GE.log_event(9400, {"event_type": "free_throw", "quarter": q,
                               "time": time, "primary_player_id": pid,
                               "shot_result": result}, on_court=[])


class LateGameDetector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed()
        # Build the score: home 3 makes (6-0) by Q4. Baseline events early.
        _make(H_P, 1, "5:00")
        _make(H_P, 2, "5:00")
        _make(H_P, 3, "5:00")
        # Q3 foul by trailing away — early, NOT strategic
        cls.f_early = _foul(H_P, A_P, 3, "0:30")
        # Q4 1:30, away down 6 — strategic window foul + resulting home FTs
        cls.f_strategic = _foul(H_P, A_P, 4, "1:30")
        cls.ft1 = _ft(H_P, 4, "1:30")
        cls.ft2 = _ft(H_P, 4, "1:30", "miss")
        # Q4 1:00, HOME (leading) fouls — not strategic
        cls.f_leading = _foul(A_P, H_P, 4, "1:00")
        # away FTs from the leading-team foul — not damped
        cls.ft_away = _ft(A_P, 4, "1:00", "miss")
        # blowout branch: home piles on to +19, away fouls again at 0:20
        for tm in ("0:50", "0:48", "0:46", "0:44", "0:42", "0:40"):
            _make(H_P, 4, tm)
        _make(H_P, 4, "0:38", 3)         # home now up 6+1+12+3-2 = +18 vs away 2
        cls.f_blowout = _foul(H_P, A_P, 4, "0:20")
        # timeline extender so the window fouls aren't at the exact buzzer
        _make(A_P, 4, "0:05")
        cls.ctx = LG.strategic_context(S.fetch_events([9400]))

    def test_trailing_late_foul_flagged(self):
        self.assertIn(self.f_strategic, self.ctx["fouls"])

    def test_early_foul_not_flagged(self):
        self.assertNotIn(self.f_early, self.ctx["fouls"])

    def test_leading_team_foul_not_flagged(self):
        self.assertNotIn(self.f_leading, self.ctx["fouls"])

    def test_blowout_foul_not_flagged(self):
        self.assertNotIn(self.f_blowout, self.ctx["fouls"])

    def test_resulting_fts_damped(self):
        self.assertIn(self.ft1, self.ctx["fts"])
        self.assertIn(self.ft2, self.ctx["fts"])

    def test_other_side_fts_not_damped(self):
        self.assertNotIn(self.ft_away, self.ctx["fts"])


if __name__ == "__main__":
    unittest.main()
