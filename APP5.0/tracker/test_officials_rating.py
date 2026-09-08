"""
test_officials_rating.py — the crew-share officials rating (2026-09-05 rework).

Two halves. The share maths is pure and tested against hand-computed binomial
values with no DB at all; the pool gating, crew normalization and table ordering
run against a throwaway DB.

The rating deliberately makes no claim about how GOOD an official is — see the
block comment above helpers.officials.RATING_MIN_GAMES. What it prices is
whether one member of a crew took the whole whistle in live minutes, so the
tests assert share behaviour, not quality.
"""
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP = tempfile.mkdtemp(prefix="app5_offrate_")
os.environ["APP5_DATA_DIR"] = _TMP

from database.db import execute                 # noqa: E402
import helpers.game_events as GE                # noqa: E402
import helpers.officials as OFF                 # noqa: E402

H, A = 8001, 8002
HP, AP = 8011, 8021
R1, R2, UNK = 8501, 8502, 8504          # the crew that works games 8600-8602
X1, X2, X3 = 8505, 8506, 8507           # the phantom half of a 6-man crew
THIN = 8508                             # only two games worked


# ── the share maths (no DB) ──────────────────────────────────────────────────
class ShareMaths(unittest.TestCase):
    def _z(self, counts, gid=1):
        """counts = {off_pk: live calls} for one game → {off_pk: z}."""
        live = {gid: dict(counts)}
        raw = {gid: dict(counts)}
        crew = {gid: set(counts)}
        by_off = OFF._share_z_by_game(live, raw, crew)
        return {o: by_off[o][gid] for o in by_off}

    def test_fair_share_scores_zero(self):
        """An evenly split game is the definition of a 50 — no ref is flagged."""
        for z in self._z({R1: 10, R2: 10, UNK: 10}).values():
            self.assertAlmostEqual(z, 0.0, places=9)

    def test_taking_more_than_the_crew_scores_positive(self):
        z = self._z({R1: 20, R2: 5, UNK: 5})
        self.assertGreater(z[R1], 0)
        self.assertLess(z[R2], 0)

    def test_the_motivating_game_reproduces(self):
        """Game 13979 on the book: 21 of 26 live calls on a three-man crew."""
        z = self._z({R1: 21, R2: 3, UNK: 2})
        self.assertAlmostEqual(z[R1], 5.13, places=2)

    def test_forty_percent_is_crew_size_dependent(self):
        """40% is roughly chance for a three-man crew and damning for a six-man
        one — which is why a flat threshold cannot be used."""
        three = self._z({R1: 12, R2: 9, UNK: 9})[R1]
        six = self._z({R1: 12, R2: 4, UNK: 4, X1: 4, X2: 3, X3: 3})[R1]
        self.assertLess(three, 1.0)
        self.assertGreater(six, 3.0)
        self.assertGreater(six, three)

    def test_thin_games_are_skipped(self):
        """Below SHARE_MIN_LIVE_CALLS a game prices nothing at all."""
        self.assertEqual(self._z({R1: 3, R2: 1, UNK: 0}), {})

    def test_binomial_matches_by_hand(self):
        n, k, mine = 26, 3, 21
        p = 1 / k
        expect = (mine - n * p) / math.sqrt(n * p * (1 - p))
        self.assertAlmostEqual(self._z({R1: 21, R2: 3, UNK: 2})[R1], expect,
                               places=9)


class EffectiveCrew(unittest.TestCase):
    def test_oversized_crew_drops_the_zero_call_rows(self):
        """Every >3 crew on the book has exactly three officials with any foul;
        the extras are a tournament day attached to one game."""
        crew = {R1, R2, UNK, X1, X2, X3}
        eff = OFF._effective_crew(crew, {R1: 12, R2: 7, UNK: 6})
        self.assertEqual(eff, {R1, R2, UNK})

    def test_normal_crew_keeps_a_silent_official(self):
        """8% of officials in a real three-man crew call nothing. Dropping them
        would erase the quiet ref and inflate everyone else's fair share."""
        crew = {R1, R2, UNK}
        self.assertEqual(OFF._effective_crew(crew, {R1: 12, R2: 7}), crew)


class ScoreShape(unittest.TestCase):
    def test_even_split_is_fifty(self):
        self.assertAlmostEqual(OFF._rating_from(0.0, 0.0, 0.0), 50.0)

    def test_one_bad_night_is_not_averaged_away(self):
        """Same mean, different worst game: the lopsided ref must rate lower."""
        spiky = OFF._rating_from(1.0, 3.0, 0.0)
        steady = OFF._rating_from(1.0, 1.0, 0.0)
        self.assertLess(spiky, steady)

    def test_credit_is_a_quarter_of_the_penalty(self):
        """Quiet is worth a little; disappearing is not excellence."""
        penalty = 50.0 - OFF._rating_from(1.0, 1.0, 0.0)
        credit = OFF._rating_from(-1.0, -1.0, 0.0) - 50.0
        self.assertGreater(credit, 0)
        self.assertAlmostEqual(credit / penalty, OFF.CREDIT_FACTOR, places=9)

    def test_rating_stays_in_range(self):
        self.assertEqual(OFF._rating_from(50.0, 50.0, 50.0), 0.0)
        self.assertEqual(OFF._rating_from(-50.0, -50.0, -50.0), 100.0)


# ── pool gating and ordering (throwaway DB) ──────────────────────────────────
def _seed():
    execute("INSERT INTO teams (id, name, class, gender) VALUES "
            "(8001,'Home','4A','F'),(8002,'Away','4A','F')")
    execute("INSERT INTO players (id, team_id, name, number) VALUES "
            "(8011,8001,'H1',1),(8021,8002,'A1',11)")
    execute("INSERT INTO officials (id, name, official_id) VALUES "
            "(8501,'Ref One','O1'),(8502,'Ref Two','O2'),"
            "(8504,'Unknown 4','O4'),(8505,'Ref Five','O5'),"
            "(8506,'Ref Six','O6'),(8507,'Ref Seven','O7'),"
            "(8508,'Thin Ref','O8')")
    # DISTINCT DATES. Six games of one matchup on one calendar day is not a
    # book that can exist (Q13) and `ux_games_matchup` refuses it; the crew
    # maths under test never looks at the date.
    for _i, gid in enumerate((8600, 8601, 8602, 8603, 8604, 8605)):
        execute("INSERT INTO games (id, team1_id, team2_id, date, tracked, "
                "season) VALUES (?,8001,8002,?,1,'2025-2026')",
                (gid, f"2026-01-{5 + _i:02d}"))
    for gid in (8600, 8601, 8602):
        for ref in (R1, R2, UNK):
            execute("INSERT INTO game_lineup_officials (game_id, official_id) "
                    "VALUES (?,?)", (gid, ref))
    # a 6-man crew: only three of them ever blow a whistle
    for ref in (R1, R2, UNK, X1, X2, X3):
        execute("INSERT INTO game_lineup_officials (game_id, official_id) "
                "VALUES (8603,?)", (ref,))
    # two games only, so THIN never clears RATING_MIN_GAMES
    for gid in (8604, 8605):
        for ref in (R1, R2, THIN):
            execute("INSERT INTO game_lineup_officials (game_id, official_id) "
                    "VALUES (?,?)", (gid, ref))


def _foul(gid, ref, q, tm):
    GE.log_event(gid, {"event_type": "foul", "quarter": q, "time": tm,
                       "primary_player_id": HP, "secondary_player_id": AP,
                       "official_id": ref}, on_court=[])


def _fouls(gid, spread):
    """spread = {ref: n}; spaced through Q1-Q3 so nothing lands in garbage."""
    t = 0
    for ref, n in spread.items():
        for _ in range(n):
            q = 1 + (t // 8) % 3
            _foul(gid, ref, q, f"{7 - (t % 7)}:00")
            t += 1


class RatedPool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _seed()
        _fouls(8600, {R1: 12, R2: 1, UNK: 1})     # R1 takes the whole whistle
        _fouls(8601, {R1: 5, R2: 5, UNK: 4})
        _fouls(8602, {R1: 4, R2: 5, UNK: 5})
        _fouls(8603, {R1: 6, R2: 6, UNK: 6})      # the phantom-crew game
        _fouls(8604, {R1: 5, R2: 5, THIN: 5})
        _fouls(8605, {R1: 5, R2: 5, THIN: 5})
        cls.rows = {r["name"]: r for r in
                    OFF.official_ratings(season=None)["officials"]}
        cls.order = [r["name"] for r in
                     OFF.official_ratings(season=None)["officials"]]

    def test_whistle_hog_rates_below_their_crew(self):
        self.assertLess(self.rows["Ref One"]["rating"],
                        self.rows["Ref Two"]["rating"])

    def test_the_lopsided_game_shows_up_as_the_worst(self):
        self.assertGreater(self.rows["Ref One"]["worst_z"], 3.0)

    def test_below_the_game_floor_is_unrated(self):
        self.assertIsNone(self.rows["Thin Ref"]["rating"])
        self.assertFalse(self.rows["Thin Ref"]["pt_bias"])

    def test_phantom_crew_members_are_not_rated(self):
        """X1-X3 were logged on 8603 but called nothing, so the share maths
        never saw them and they have no priced game."""
        for nm in ("Ref Five", "Ref Six", "Ref Seven"):
            self.assertEqual(self.rows[nm]["rated_games"], 0)
            self.assertIsNone(self.rows[nm]["rating"])

    def test_oversized_crew_still_prices_the_real_three(self):
        """8603 must count for the officials who actually worked it — if the
        crew were taken at face value their fair share would be 1/6. Every game
        Ref One worked carries enough live calls, so all of them price."""
        r = self.rows["Ref One"]
        self.assertEqual(r["rated_games"], r["games"])
        # an even 6/6/6 split on 8603 is fair share for THREE, not for six
        self.assertLess(self.rows["Ref Two"]["worst_z"], 1.0)

    def test_placeholder_names_sort_below_named_officials(self):
        named = [i for i, n in enumerate(self.order) if not
                 OFF.is_placeholder_name(n)]
        unknown = [i for i, n in enumerate(self.order) if
                   OFF.is_placeholder_name(n)]
        self.assertTrue(unknown, "fixture must contain a placeholder ref")
        self.assertLess(max(named), min(unknown))

    def test_placeholder_detection(self):
        self.assertTrue(OFF.is_placeholder_name("Unknown 11"))
        self.assertTrue(OFF.is_placeholder_name("unknown 4"))
        self.assertTrue(OFF.is_placeholder_name("  Unknown 7"))
        # the older free-text placeholders stay out of it: no regex can tell
        # 'Balding' the nickname from 'Balding' the surname
        self.assertFalse(OFF.is_placeholder_name("Balding"))
        self.assertFalse(OFF.is_placeholder_name("Unknowable Jones"))
        self.assertFalse(OFF.is_placeholder_name(None))


if __name__ == "__main__":
    unittest.main()
