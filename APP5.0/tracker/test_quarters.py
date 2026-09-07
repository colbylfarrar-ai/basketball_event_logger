"""Quarter reads, as verdicts — the biggest content gap on the Insights view.

Charts -> Quarters carries four sub-tabs of per-quarter splits. Insights carries
ZERO quarter reads beyond the foul-trouble lines in insights_deep. That gap has
been the highest-value unimported engine on the standing list for a while, and
the founder's team-read ask ("runs man more in the 4th") lands straight on it.

What Insights needs is not those charts. Insights is a prose surface: it needs
the SENTENCE a coach would say out loud. So this is a new engine beside stops.py
and winning_formula.py rather than a port of the panels — it reads
team_analytics.quarter_boxes and returns house verdict lines.

The rules it has to hold:

  * gate on the sample, per quarter — every game has Q1-Q4 but only some reach
    OT, and n_games is per quarter for exactly that reason
  * regulation only for best/worst — an OT "worst quarter" off two games is a
    coin flip wearing a verdict's clothes
  * say nothing when nothing moved. A flat team is a real finding and an
    invented one is worse than silence.

Run: python -m pytest tracker/test_quarters.py
"""
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

import helpers.quarters as Q                           # noqa: E402


def _q(pts_for, pts_against, n_games=10, poss=20):
    """One quarter's entry in a quarter_boxes dict — totals, not per game."""
    return {
        "team": {"PTS": pts_for * n_games, "FGA": poss * n_games},
        "opp": {"PTS": pts_against * n_games, "FGA": poss * n_games},
        "poss": poss * n_games,
        "opp_poss": poss * n_games,
        "n_games": n_games,
        "four_factors": {},
    }


#: +8/g in Q1, flat in Q2 and Q4, -6/g in Q3 — a team that comes out of the
#: locker room badly, which is the read a coach acts on the same week.
SPLIT = {1: _q(20, 12), 2: _q(15, 15), 3: _q(12, 18), 4: _q(16, 16)}
FLAT = {q: _q(15, 15) for q in (1, 2, 3, 4)}


def test_a_the_best_and_worst_quarter_are_named():
    lines = Q.quarter_verdict(SPLIT)
    txt = " ".join(l["text"] for l in lines)
    assert "1st" in txt, txt
    assert "3rd" in txt, txt


def test_b_the_numbers_are_in_the_sentence():
    """Nothing is asserted without its number — the house rule for every
    verdict line in the app."""
    txt = " ".join(l["text"] for l in Q.quarter_verdict(SPLIT))
    assert "+8" in txt or "8.0" in txt, txt
    assert "10" in txt, f"the sample is missing from: {txt}"


def test_c_a_flat_team_gets_no_invented_tendency():
    assert Q.quarter_verdict(FLAT) == []


def test_d_a_thin_quarter_is_dropped_not_reported():
    thin = dict(SPLIT)
    thin[3] = _q(12, 18, n_games=1)      # one game is not a tendency
    txt = " ".join(l["text"] for l in Q.quarter_verdict(thin))
    assert "3rd" not in txt, txt


def test_e_overtime_never_wins_best_or_worst():
    """OT is real basketball and terrible evidence — two games, huge margins."""
    with_ot = dict(SPLIT)
    with_ot[5] = _q(9, 1, n_games=3)     # +8/g in OT, same as Q1
    lines = Q.quarter_verdict(with_ot)
    txt = " ".join(l["text"] for l in lines)
    assert "OT" not in txt and "overtime" not in txt.lower(), txt


def test_f_the_half_split_is_reported_when_it_is_real():
    """+8 and level in the first half, -6 and level in the second: the halves
    disagree by more than either quarter does alone, and that is its own read."""
    lines = Q.quarter_verdict(SPLIT)
    assert any(l["cut"] == "half" for l in lines), [l["cut"] for l in lines]


def test_g_a_flat_half_split_says_nothing():
    even = {1: _q(20, 12), 2: _q(12, 20), 3: _q(20, 12), 4: _q(12, 20)}
    assert not any(l["cut"] == "half" for l in Q.quarter_verdict(even))


def test_h_lines_carry_the_house_shape():
    for line in Q.quarter_verdict(SPLIT):
        assert set(line) >= {"text", "cut", "n"}, line
        assert isinstance(line["text"], str) and line["text"].strip()
        assert isinstance(line["n"], int) and line["n"] > 0


def test_i_an_empty_book_is_not_an_error():
    assert Q.quarter_verdict({}) == []
    assert Q.quarter_verdict(None) == []


def test_j_strongest_read_first():
    """Ranked by size, like every other verdict list in the app."""
    lines = Q.quarter_verdict(SPLIT)
    mags = [abs(l.get("delta") or 0) for l in lines]
    assert mags == sorted(mags, reverse=True), mags
