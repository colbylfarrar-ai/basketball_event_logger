"""
test_officials_wp.py — officials' win-probability call context (spec §8).

Throwaway-DB e2e. One close game: REF_EARLY calls only first-quarter fouls
(low leverage), REF_LATE calls only last-minute fouls of a tied game (high
leverage). Asserts the leverage profile separates them, the foul-out context
fires, and strategic clock-stop calls stay out of the profile.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_offwp_")
os.environ["APP5_DATA_DIR"] = _TMP

from database.db import execute                 # noqa: E402
import helpers.game_events as GE                # noqa: E402
import helpers.officials as OFF                 # noqa: E402

H, A = 9001, 9002
HP, AP = 9011, 9021          # main players
REF_EARLY, REF_LATE = 9501, 9502


def _seed():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(9001,'Home','4A','F'),(9002,'Away','4A','F')")
    execute("INSERT INTO players (id, team_id, name, number) VALUES "
            "(9011,9001,'H1',1),(9021,9002,'A1',11),(9022,9002,'A2',12)")
    execute("INSERT INTO officials (id, name, official_id) VALUES "
            "(9501,'Early Ref','E1'),(9502,'Late Ref','L1')")
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
            "VALUES (9600,9001,9002,'2026-01-05',1,'2025-2026')")
    execute("INSERT INTO game_lineup_officials (game_id, official_id) "
            "VALUES (9600,9501),(9600,9502)")


def _make(pid, q, tm, pts=2):
    GE.log_event(9600, {"event_type": "shot", "quarter": q, "time": tm,
                        "primary_player_id": pid, "shot_result": "make",
                        "shot_type": pts, "zone": "C"}, on_court=[])


def _foul(fouler, q, tm, ref):
    return GE.log_event(9600, {"event_type": "foul", "quarter": q, "time": tm,
                               "primary_player_id": HP if fouler == AP else AP,
                               "secondary_player_id": fouler,
                               "official_id": ref}, on_court=[])


class OfficialsWP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed()
        # tied, back-and-forth game — late moments carry big leverage
        seq = [("7:00", HP), ("6:30", AP), ("5:00", HP), ("4:30", AP)]
        for q in (1, 2, 3, 4):
            for tm, pid in seq:
                _make(pid, q, tm)
        # REF_EARLY: three Q1 calls on AP (low leverage)
        for tm in ("6:00", "5:30", "4:00"):
            _foul(AP, 1, tm, REF_EARLY)
        # REF_LATE: two last-minute calls in a TIED game (high leverage);
        # the second is AP's 5th foul -> foul-out context
        _foul(AP, 4, "0:40", REF_LATE)
        _foul(AP, 4, "0:25", REF_LATE)
        _make(HP, 4, "0:05")     # timeline extender / winner
        cls.ov = {r["off_pk"]: r for r in OFF.official_overview(
            gender="F", season="2025-2026")["officials"]}

    def test_leverage_separates_refs(self):
        early, late = self.ov[REF_EARLY], self.ov[REF_LATE]
        self.assertIsNotNone(early["avg_call_li"])
        self.assertIsNotNone(late["avg_call_li"])
        self.assertGreater(late["avg_call_li"], early["avg_call_li"])
        self.assertGreater(late["hi_li_calls"], 0)
        self.assertEqual(early["hi_li_calls"], 0)

    def test_foulout_context(self):
        late = self.ov[REF_LATE]
        self.assertEqual(late["foulouts"], 1)
        self.assertGreater(late["foulout_impact"], 0.0)
        self.assertEqual(self.ov[REF_EARLY]["foulouts"], 0)

    def test_strategic_calls_excluded(self):
        """A trailing-team clock-stop foul shows in strategic_calls, not the
        leverage profile."""
        # new game where away trails by 4 late and fouls — strategic
        execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
                "VALUES (9601,9001,9002,'2026-01-06',1,'2025-2026')")
        execute("INSERT INTO game_lineup_officials (game_id, official_id) "
                "VALUES (9601,9501)")
        for q, tm in ((1, "5:00"), (2, "5:00")):
            GE.log_event(9601, {"event_type": "shot", "quarter": q, "time": tm,
                                "primary_player_id": HP, "shot_result": "make",
                                "shot_type": 2, "zone": "C"}, on_court=[])
        GE.log_event(9601, {"event_type": "foul", "quarter": 4, "time": "0:30",
                            "primary_player_id": HP, "secondary_player_id": AP,
                            "official_id": REF_EARLY}, on_court=[])
        GE.log_event(9601, {"event_type": "shot", "quarter": 4, "time": "0:05",
                            "primary_player_id": HP, "shot_result": "make",
                            "shot_type": 2, "zone": "C"}, on_court=[])
        ov = {r["off_pk"]: r for r in OFF.official_overview(
            gender="F", season="2025-2026")["officials"]}
        early = ov[REF_EARLY]
        self.assertEqual(early["strategic_calls"], 1)
        self.assertEqual(early["li_calls"], 3)     # still only the 3 Q1 calls


if __name__ == "__main__":
    unittest.main()
