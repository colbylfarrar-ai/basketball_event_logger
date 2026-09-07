"""The Officiating Lab's hero tiles need one floor, and it has to be stated. (B1)

Five glass tiles head the page, and before this they ran FOUR different sample
rules between them — `games >= 2` for three of them, an inline "at least 4 fouls"
for the lean tile, nothing at all for the environment tile, and
`RATING_MIN_GAMES = 3` in the tab immediately below. THE BOOK §14 item 4 names
this exactly: three floors on one screen and no way to tell which is biting.

Measured on production before the fix (career view, all seasons):

    girls   BIGGEST H/A LEAN   Aaron Hughes          1 game,  6 fouls
    girls   HOTTEST ENV.       Donald Hollingsworth  1 game, 11 fouls
    girls   MOST CONSISTENT    Unknown 1             2 games (a stdev over two)
    girls   MOST LENIENT       Unknown 16            3 games, 5 fouls
    boys    BIGGEST H/A LEAN   Unknown 13            1 game,  7 fouls
    boys    HOTTEST ENV.       Damion Hooks          1 game,  5 fouls

A single game's PPP published as the league's hottest environment, and a single
game's foul split published as the league's biggest home/away lean. §10's own
example — "MOST LENIENT 0.0, one foul total" — is the same class of claim.

`whistle_leaders` puts all five behind ONE floor, reusing the officials' existing
`RATING_MIN_GAMES` rather than inventing a fourth number, and refuses to fill a
slot it cannot fill instead of falling back to the unfiltered pool. It also
returns each official at most once (§10 rule 3: one card per subject), so a
single busy ref cannot take four of the five tiles on a book this thin.

Run: python -m pytest tracker/test_whistle_leaders.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.officials as OFF                        # noqa: E402


def _ref(name, games, **kw):
    """One official_overview row, with every field the tiles read."""
    r = {"name": name, "games": games, "fouls": games * 8,
         "game_poss": games * 60.0, "game_pts": games * 50.0,
         "FPG_std": 2.0, "PPP": 0.80, "ha_diff": 2,
         "home_fouls": games * 4, "away_fouls": games * 4, "q4": games * 2}
    r.update(kw)
    return r


def test_a_one_game_official_cannot_headline_anything():
    """The two tiles that had no games floor at all: the environment tile ran
    over every row, and the lean tile gated on fouls instead of games."""
    pool = [_ref("One Gamer", 1, PPP=1.40, ha_diff=-9, fouls=7,
                 home_fouls=1, away_fouls=6),
            _ref("Real Ref", 6, PPP=0.75),
            _ref("Other Ref", 5, PPP=0.70, FPG_std=1.0)]
    OFF.derive_rates(pool)
    picks = OFF.whistle_leaders(pool)
    named = {slot: r["name"] for slot, r in picks.items() if r}
    assert "One Gamer" not in named.values(), named


def test_no_official_takes_two_tiles():
    """On a book with eleven officials at five games, one busy ref could
    otherwise hold four of the five slots and the strip would say nothing."""
    pool = [_ref("Busy", 9, PPP=1.30, FPG_std=0.1, ha_diff=-9, fouls=99,
                 home_fouls=1, away_fouls=9, game_poss=300.0),
            _ref("B", 5, PPP=0.70), _ref("C", 4, PPP=0.72),
            _ref("D", 6, PPP=0.74), _ref("E", 7, PPP=0.76)]
    OFF.derive_rates(pool)
    picks = OFF.whistle_leaders(pool)
    filled = [r["name"] for r in picks.values() if r]
    assert len(filled) == len(set(filled)), filled


def test_a_slot_it_cannot_fill_is_empty_not_faked():
    """The old code said `[r for r in rows if r["games"] >= 2] or rows` — an
    empty eligible pool fell back to every row, so the floor evaporated in
    exactly the case it existed for."""
    picks = OFF.whistle_leaders([_ref("Rookie", 1), _ref("Also New", 2)])
    assert all(r is None for r in picks.values()), picks


def test_the_floor_is_the_one_the_page_below_already_uses():
    """One floor on one screen (THE BOOK §14 item 4) — and no new constant."""
    assert OFF.WHISTLE_MIN_GAMES == OFF.RATING_MIN_GAMES


def test_every_pick_carries_the_sample_behind_it():
    """Q6 — disclose. The tile cannot say "3 games" unless the pick brings it."""
    pool = [_ref(n, 5, PPP=0.70 + i / 100) for i, n in enumerate("ABCDE")]
    OFF.derive_rates(pool)
    for slot, r in OFF.whistle_leaders(pool).items():
        assert r is not None and r.get("games"), (slot, r)
