"""
test_wpa_recal.py — recal round 2: EP baseline scoping + DWPA team-split credit.

Throwaway-DB e2e (the test_turnover_types pattern): APP5_DATA_DIR points at a
temp dir before database.db imports, so the real migration runs and the real
write path persists events. Covers:
  1. league_ep gender scoping — season_wpa must score a gender's possessions
     against THAT gender's expected points, not the mixed-league average
  2. DWPA team-split — orphaned positive defensive credit (unforced TOs, misses
     with no credited defensive rebound) lands on the on-floor defenders, made
     baskets split on-ball vs help, and league Def WPA sums to ~0
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_wparecal_")
os.environ["APP5_DATA_DIR"] = _TMP

from database.db import execute                 # noqa: E402  (migrates _TMP db)
import helpers.game_events as GE                # noqa: E402
import helpers.wpa as WPA                       # noqa: E402


GIRLS = (9001, 9002)
BOYS = (9101, 9102)


def _seed_once():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(9001,'GA','4A','F'),(9002,'GB','4A','F'),"
            "(9101,'BA','4A','M'),(9102,'BB','4A','M')")
    pid = 9010
    rows = []
    for tid in (9001, 9002, 9101, 9102):
        for _ in range(6):
            rows.append((pid, tid))
            pid += 1
    for p, t in rows:
        execute("INSERT INTO players (id, team_id, name, number) VALUES (?,?,?,?)",
                (p, t, f"P{p}", p % 100))
    execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) VALUES "
            "(9200,9001,9002,'2026-01-05',1,'2025-2026'),"
            "(9201,9101,9102,'2026-01-05',1,'2025-2026')")


_seed_once()   # module level: test classes run alphabetically, all need the rows


def _players_of(tid, n=5):
    base = {9001: 9010, 9002: 9016, 9101: 9022, 9102: 9028}[tid]
    return list(range(base, base + n))


def _floor(t_off, t_def):
    return [(p, t_off) for p in _players_of(t_off)] + \
           [(p, t_def) for p in _players_of(t_def)]


def _shot(gid, t_off, t_def, pid, q, time, result="make", guarded=None,
          rebound=None, blocked=None):
    GE.log_event(gid, {"event_type": "shot", "quarter": q, "time": time,
                       "primary_player_id": pid, "shot_result": result,
                       "shot_type": 2, "zone": "C",
                       "guarded_by_id": guarded, "rebound_by_id": rebound,
                       "blocked_by_id": blocked},
                 on_court=_floor(t_off, t_def))


def _tov(gid, t_off, t_def, pid, q, time, stolen=None):
    GE.log_event(gid, {"event_type": "turnover", "quarter": q, "time": time,
                       "primary_player_id": pid, "stolen_by_id": stolen},
                 on_court=_floor(t_off, t_def))


class EPScoping(unittest.TestCase):
    """Girls game: every possession a made 2 (PPP=2). Boys game: every
    possession a turnover (PPP=0). Mixed EP = 1.0; scoped girls EP = 2.0.
    A girl who scores exactly the girls' EP each possession must earn ~0
    offensive WPA — under the unscoped baseline she'd wrongly earn a lot."""

    @classmethod
    def setUpClass(cls):
        times = ["7:00", "6:00", "5:00", "4:00", "3:00", "2:00"]
        for i, tm in enumerate(times):
            _shot(9200, 9001, 9002, 9010, 1, tm, "make", guarded=9016)
            _tov(9201, 9101, 9102, 9022, 1, tm)
        # second-quarter mirrors so both teams appear on offense
        for i, tm in enumerate(times):
            _shot(9200, 9002, 9001, 9016, 2, tm, "make", guarded=9010)
            _tov(9201, 9102, 9101, 9028, 2, tm)

    def test_league_ep_scoped_vs_mixed(self):
        self.assertAlmostEqual(WPA.league_ep(game_ids=[9200]), 2.0, places=6)
        self.assertAlmostEqual(WPA.league_ep(game_ids=[9201]), 0.0, places=6)
        self.assertAlmostEqual(WPA.league_ep(game_ids=[9200, 9201]), 1.0, places=6)
        # The no-arg call filters season='Current' (empty post-rollover) -> 0.0.
        # This is the bug season_wpa must never hit again: it must ALWAYS pass
        # its own scoped game_ids instead of relying on the no-arg default.
        self.assertAlmostEqual(WPA.league_ep(), 0.0, places=6)

    def test_season_wpa_uses_gender_scoped_ep(self):
        sw = WPA.season_wpa(gender="F", mode="possession", opp_adjust=False,
                            season="2025-2026")
        girl = sw[9010]
        # scoring exactly the scoped EP every time -> ~zero value over expected
        self.assertLess(abs(girl["off_wpa"]), 0.02,
                        f"off_wpa {girl['off_wpa']} — EP baseline not scoped?")


class GarbageTimeSelfDamp(unittest.TestCase):
    """Spec §4 verification (no new mechanism): in a decided game, a late
    basket barely moves win probability, so WPA credit is already ~0."""

    @classmethod
    def setUpClass(cls):
        execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) "
                "VALUES (9310,9001,9002,'2026-01-09',1,'TEST-SPLIT')")
        # 9001 pours in 13 straight makes (26-0), then one more with a minute left
        times = [(1, "6:00"), (1, "5:00"), (1, "4:00"), (2, "6:00"), (2, "5:00"),
                 (2, "4:00"), (3, "6:00"), (3, "5:00"), (3, "4:00"), (4, "7:00"),
                 (4, "6:00"), (4, "5:00"), (4, "3:00")]
        for q, tm in times:
            _shot(9310, 9001, 9002, 9010, q, tm, "make", guarded=9016)
        _shot(9310, 9001, 9002, 9011, 4, "1:00", "make", guarded=9016)
        _shot(9310, 9002, 9001, 9016, 4, "0:10", "miss")   # timeline extender

    def test_late_blowout_basket_worth_nothing(self):
        res = WPA.game_wpa(9310, mode="scoring")
        # the up-26 basket at 1:00 moved WP by ~nothing
        tl = res["timeline"]
        self.assertGreater(tl[-1][2], 0.995)
        self.assertLess(abs(tl[-1][2] - tl[-2][2]), 0.005)
        shooter = res["players"].get(9011)
        if shooter:
            self.assertLess(abs(shooter["wpa"]), 0.005)


class DwpaTeamSplit(unittest.TestCase):
    """Defensive-credit assignment in possession mode (spec §3):
      * made basket   — on-ball defender ONBALL_SHARE, help splits the rest
      * unforced TO   — full positive credit split among on-floor defenders
      * dead miss     — (no credited defensive rebound) same team split
      * zero-sum      — with full floor data, Σdef_wpa == −Σoff_wpa per game
    One possession per game (plus a Q4 free-throw miss that only extends the
    timeline so the possession isn't at the buzzer)."""

    @classmethod
    def setUpClass(cls):
        execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, season) VALUES "
                "(9300,9001,9002,'2026-01-06',1,'TEST-SPLIT'),"
                "(9301,9001,9002,'2026-01-07',1,'TEST-SPLIT'),"
                "(9302,9001,9002,'2026-01-08',1,'TEST-SPLIT')")
        for gid in (9300, 9301, 9302):
            GE.log_event(gid, {"event_type": "free_throw", "quarter": 4,
                               "time": "0:30", "primary_player_id": 9010,
                               "shot_result": "miss"},
                         on_court=_floor(9001, 9002))
        # late-game possessions -> big WP swings, so the 3-decimal rounding of
        # def_wpa can't distort the share ratios under test
        _shot(9300, 9001, 9002, 9010, 4, "1:00", "make", guarded=9016)
        _tov(9301, 9001, 9002, 9010, 4, "1:00")                  # unforced
        _shot(9302, 9001, 9002, 9010, 4, "1:00", "miss")         # dead ball

    def _defs(self, gid):
        res = WPA.game_wpa(gid, mode="possession", ep=1.0)
        return {pid: r["def_wpa"] for pid, r in res["players"].items()
                if r["def_wpa"] != 0.0}, res

    def test_make_splits_onball_vs_help(self):
        d, _ = self._defs(9300)
        onball, help_ = d[9016], d[9017]
        self.assertLess(onball, 0.0)
        self.assertLess(help_, 0.0)
        self.assertAlmostEqual(
            onball / help_,
            WPA.ONBALL_SHARE / ((1 - WPA.ONBALL_SHARE) / 4),
            delta=0.35)   # def_wpa is stored rounded to 3 decimals
        for p in (9017, 9018, 9019, 9020):
            self.assertAlmostEqual(d[p], help_, places=6)

    def test_unforced_to_credits_floor_defense(self):
        d, _ = self._defs(9301)
        self.assertEqual(sorted(d), [9016, 9017, 9018, 9019, 9020])
        for v in d.values():
            self.assertGreater(v, 0.0)
        self.assertAlmostEqual(min(d.values()), max(d.values()), places=6)

    def test_dead_miss_credits_floor_defense(self):
        d, _ = self._defs(9302)
        self.assertEqual(sorted(d), [9016, 9017, 9018, 9019, 9020])
        for v in d.values():
            self.assertGreater(v, 0.0)

    def test_zero_sum_with_full_floor(self):
        for gid in (9300, 9301, 9302):
            res = WPA.game_wpa(gid, mode="possession", ep=1.0)
            tot_off = sum(r["off_wpa"] for r in res["players"].values())
            tot_def = sum(r["def_wpa"] for r in res["players"].values())
            self.assertAlmostEqual(tot_def, -tot_off, places=2,
                                   msg=f"game {gid} not zero-sum")


if __name__ == "__main__":
    unittest.main()
