"""
test_turnover_types.py — the explicit turnover-kind tag, write path + engine.

Throwaway-DB e2e (the test_playtype_outcomes pattern): APP5_DATA_DIR points at
a temp dir before database.db imports, so the real migration runs and the real
write path (game_events.log_event) persists turnover_type. Covers:
  1. write path — log_event stores turnover_type; NULL stays NULL
  2. team engine — offense (giveaways) vs defense (forced) + play_type layer
  3. allowed-side gate — offense=False only counts games the team played
  4. player engine — per-player kinds, TO charged to primary_player_id
  5. editor field map — turnover_type survives event_log update/retype
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_tovtypes_")
os.environ["APP5_DATA_DIR"] = _TMP

from database.db import execute, query          # noqa: E402  (migrates _TMP db)
import helpers.game_events as GE                # noqa: E402
import helpers.turnovers as TOV                 # noqa: E402
import helpers.stats as S                       # noqa: E402
import helpers.event_log as EL                  # noqa: E402


def _seed():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(9001,'Alpha','4A','F'),(9002,'Beta','4A','F'),(9003,'Gamma','4A','F')")
    for pid, tid in ((9011, 9001), (9012, 9001), (9021, 9002), (9031, 9003)):
        execute("INSERT INTO players (id, team_id, name, number) VALUES (?,?,?,?)",
                (pid, tid, f"P{pid}", pid % 100))
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked) VALUES "
            "(9100,9001,9002,'2026-01-01',1),"   # Alpha vs Beta
            "(9101,9002,9003,'2026-01-08',1)")   # Beta vs Gamma (NOT Alpha's game)


def _tov(gid, pid, kind=None, play=None, stolen=None):
    GE.log_event(gid, {"event_type": "turnover", "quarter": 1, "time": "5:00",
                       "primary_player_id": pid, "stolen_by_id": stolen,
                       "play_type": play, "turnover_type": kind}, on_court=[])


class TurnoverTypes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed()
        # Alpha giveaways in game 9100: 2 pass (one in pnr, one stolen),
        # 1 drive, 1 untagged. Beta giveaway in 9100: 1 travel.
        _tov(9100, 9011, "pass", "pnr", stolen=9021)
        _tov(9100, 9011, "pass")
        _tov(9100, 9012, "drive", "iso")
        _tov(9100, 9012)                                   # untagged
        _tov(9100, 9021, "travel")
        # Beta vs Gamma (Alpha not involved): Gamma loses one on a drive —
        # must NEVER leak into Alpha's forced-TO view.
        _tov(9101, 9031, "drive")
        cls.events = S.fetch_events([9100, 9101])

    def test_write_path_persists_kind(self):
        rows = query("SELECT turnover_type FROM game_events WHERE game_id=9100 "
                     "ORDER BY id")
        self.assertEqual([r["turnover_type"] for r in rows],
                         ["pass", "pass", "drive", None, "travel"])

    def test_team_offense_giveaways(self):
        tv = TOV.team_turnover_types(9001, events=self.events, offense=True)
        self.assertEqual(tv["total"], 4)
        self.assertEqual(tv["total_tagged"], 3)
        self.assertEqual(tv["untagged"], 1)
        by = {r["key"]: r for r in tv["rows"]}
        self.assertEqual(by["pass"]["n"], 2)
        self.assertEqual(by["pass"]["stolen"], 1)
        self.assertEqual(by["pass"]["sets"], {"pnr": 1})
        self.assertEqual(by["drive"]["n"], 1)
        self.assertAlmostEqual(by["pass"]["share"], 2 / 3)

    def test_team_defense_forced_and_allowed_side_gate(self):
        tv = TOV.team_turnover_types(9001, events=self.events, offense=False)
        # Beta's travel in Alpha's game counts; Gamma's drive in 9101 must NOT.
        self.assertEqual(tv["total"], 1)
        self.assertEqual([r["key"] for r in tv["rows"]], ["travel"])

    def test_player_breakdown(self):
        pv = TOV.player_turnover_types(events=self.events)
        p = pv[9011]
        self.assertEqual(p["total"], 2)
        self.assertEqual(p["rows"][0], {"key": "pass", "label": "Bad pass",
                                        "n": 2, "share": 1.0})
        self.assertEqual(pv[9012]["untagged"], 1)

    def test_unknown_folds_to_other_and_editor_fields(self):
        self.assertEqual(TOV._norm("granny_shot"), "other")
        self.assertIsNone(TOV._norm(None))
        self.assertIn("turnover_type", EL._FIELDS_BY_TYPE["turnover"])
        self.assertIn("turnover_type", EL._ALL_FIELDS)
        self.assertIn("turnover_type", EL._STR_FIELDS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
