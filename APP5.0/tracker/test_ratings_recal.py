"""
test_ratings_recal.py — recal round 2 rating changes (spec §5, §7).

Throwaway-DB e2e. Covers:
  1. penalty leaves — two otherwise-identical players, one bleeding turnovers
     and fouls, must separate on OVERALL (negative weights bite at the top)
  2. nsPF/G profile leaf — strategic fouls don't count against discipline
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_ratrecal_")
os.environ["APP5_DATA_DIR"] = _TMP

from database.db import execute                 # noqa: E402
import helpers.game_events as GE                # noqa: E402
import helpers.player_ratings as PR             # noqa: E402


A, B = 9001, 9002
CLEAN, SLOPPY = 9011, 9012        # same production; SLOPPY adds TOs + fouls
OPP = 9021


def _seed():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(9001,'Alpha','4A','F'),(9002,'Beta','4A','F')")
    for pid, tid, name in ((9011, 9001, 'Clean'), (9012, 9001, 'Sloppy'),
                           (9013, 9001, 'Filler1'), (9014, 9001, 'Filler2'),
                           (9015, 9001, 'Filler3'), (9016, 9001, 'Filler4'),
                           (9017, 9001, 'Filler5'), (9018, 9001, 'Filler6'),
                           (9021, 9002, 'Opp1'), (9022, 9002, 'Opp2'),
                           (9023, 9002, 'Opp3'), (9024, 9002, 'Opp4'),
                           (9025, 9002, 'Opp5')):
        execute("INSERT INTO players (id, team_id, name, number) VALUES (?,?,?,?)",
                (pid, tid, name, pid % 100))
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
            "VALUES (9100,9001,9002,'2026-01-05',1,'2025-2026'),"
            "(9101,9001,9002,'2026-01-12',1,'2025-2026'),"
            "(9102,9001,9002,'2026-01-19',1,'2025-2026')")


ONCOURT = ([(p, 9001) for p in (9011, 9012, 9013, 9014, 9015)]
           + [(p, 9002) for p in (9021, 9022, 9023, 9024, 9025)])


def _shot(gid, pid, q, tm, result="make"):
    GE.log_event(gid, {"event_type": "shot", "quarter": q, "time": tm,
                       "primary_player_id": pid, "shot_result": result,
                       "shot_type": 2, "zone": "C"}, on_court=ONCOURT)


class PenaltyLeaves(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed()
        mins = ["7:00", "6:30", "6:00", "5:30", "5:00", "4:30", "4:00", "3:30"]
        for gid in (9100, 9101, 9102):
            # identical scoring lines for CLEAN and SLOPPY + filler pool spread
            for tm in mins[:4]:
                _shot(gid, CLEAN, 1, tm)
                _shot(gid, SLOPPY, 2, tm)
            for i, pid in enumerate((9013, 9014, 9015, 9021, 9022, 9023)):
                _shot(gid, pid, 3, mins[i], "make" if i % 2 else "miss")
            # SLOPPY only: turnovers + early (non-strategic) fouls
            for tm in mins[:4]:
                GE.log_event(gid, {"event_type": "turnover", "quarter": 2,
                                   "time": tm, "primary_player_id": SLOPPY},
                             on_court=ONCOURT)
            for tm in mins[:3]:
                GE.log_event(gid, {"event_type": "foul", "quarter": 1,
                                   "time": tm, "primary_player_id": OPP,
                                   "secondary_player_id": SLOPPY},
                             on_court=ONCOURT)

    def test_penalty_leaves_separate_identical_scorers(self):
        R = PR.player_ratings(gender="F", season="2025-2026",
                              game_ids=[9100, 9101, 9102])
        clean, sloppy = R[CLEAN]["OVERALL"], R[SLOPPY]["OVERALL"]
        self.assertGreater(clean, sloppy,
                           f"clean {clean} should out-rate sloppy {sloppy}")

    def test_archetype_anchor_blend_changes_only_anchoring(self):
        """With BLEND on vs off, ratings still rank CLEAN over SLOPPY and stay
        on the 0-100 scale (the anchor only moves the shrink target; pool is
        tiny so clustering may no-op — either way nothing breaks)."""
        saved = PR.ARCH_ANCHOR_BLEND
        try:
            PR.ARCH_ANCHOR_BLEND = 0.0
            off = PR.player_ratings(gender="F", season="2025-2026",
                                    game_ids=[9100, 9101, 9102])
            PR.ARCH_ANCHOR_BLEND = 0.5
            on = PR.player_ratings(gender="F", season="2025-2026",
                                   game_ids=[9100, 9101, 9102])
        finally:
            PR.ARCH_ANCHOR_BLEND = saved
        for R in (off, on):
            self.assertGreater(R[CLEAN]["OVERALL"], R[SLOPPY]["OVERALL"])
            for row in R.values():
                self.assertTrue(0.0 <= row["OVERALL"] <= 100.0)

    def test_nspf_leaf_present(self):
        prof = PR.player_profiles(gender="F", min_games=1,
                                  game_ids=[9100, 9101, 9102])
        self.assertIn("nsPF/G", prof[SLOPPY])
        self.assertGreater(prof[SLOPPY]["nsPF/G"], 0.0)
        self.assertEqual(prof[CLEAN]["nsPF/G"], 0.0)


if __name__ == "__main__":
    unittest.main()
