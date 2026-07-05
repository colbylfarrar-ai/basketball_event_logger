"""
excitement.py — the STAKES adjustment for the Game Excitement Index (GEI).

Raw GEI (helpers.win_probability.summarize) measures the win-probability ride of
a single game. On its own a #450-vs-#415 frenzy can out-rank a #1-vs-#2
nailbiter, which isn't how a coach reads "the best games." The stakes lift fixes
that: multiply raw GEI by ``1 + stakes`` where stakes = how good the two teams
are (mean quality percentile) plus an upset kicker when the worse-seeded team
won. Multiplicative, so a blowout's low GEI is never rescued by stakes alone.

This is the single source for that math — both the Rankings "most exciting
games" board and the Hall of Fame's exciting-games teaser call ``stakes()`` so
the two can never drift (the Hall of Fame previously showed RAW GEI while
Rankings showed the adjusted value, so the same game read 3.2 in one place and
4.7 in the other). Pure data; no Streamlit.
"""
from __future__ import annotations

# How much the two teams' QUALITY and an UPSET lift a game's excitement. Tuned to
# the founder's ordering — a #1-vs-#2 back-and-forth at a 3.7 raw GEI should edge
# a #450-vs-#415 game at 4.2, and a competitive big upset lands between the two.
GEI_QUAL_W = 0.45      # weight on the two teams' mean quality percentile
GEI_UPSET_W = 0.60     # weight on the normalized rank gap when the underdog won


def stakes(scored, team1_id, team2_id, home_score, away_score):
    """(stakes, qual, upset) for one game from team ranks.

    `scored` = helpers.team_ratings.score_ratings for the game's SEASON (a
    {team_id: {..., 'Rank': int}} map). qual = mean quality percentile in [0,1]
    of the two teams (0 when EITHER team is unranked — an out-of-conference team
    with no rating adds no stakes). upset = normalized rank gap when the
    worse-seeded team won. Empty `scored` (or a single team in the pool) → all
    zeros, so the caller falls back to raw GEI."""
    n_teams = len(scored) or 1

    def _q(tid):
        rk = (scored.get(tid) or {}).get("Rank")
        if rk is None or n_teams < 2:
            return None
        return 1.0 - (rk - 1) / (n_teams - 1)

    q1, q2 = _q(team1_id), _q(team2_id)
    qual = ((q1 + q2) / 2) if (q1 is not None and q2 is not None) else 0.0
    upset = 0.0
    rk1 = (scored.get(team1_id) or {}).get("Rank")
    rk2 = (scored.get(team2_id) or {}).get("Rank")
    if (rk1 and rk2 and home_score is not None and away_score is not None
            and home_score != away_score and n_teams > 1):
        win_rk = rk1 if home_score > away_score else rk2
        los_rk = rk2 if home_score > away_score else rk1
        if win_rk > los_rk:                    # worse-seeded team won
            upset = (win_rk - los_rk) / (n_teams - 1)
    return GEI_QUAL_W * qual + GEI_UPSET_W * upset, qual, upset


def adj_gei(raw_gei, scored, team1_id, team2_id, home_score, away_score):
    """Convenience: raw GEI → stakes-adjusted GEI (``raw * (1 + stakes)``)."""
    stk, _q, _u = stakes(scored, team1_id, team2_id, home_score, away_score)
    return raw_gei * (1 + stk)
