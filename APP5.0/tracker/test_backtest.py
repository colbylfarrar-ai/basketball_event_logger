"""
Walk-forward backtest + the as-of board (helpers/backtest.py), against a
THROWAWAY DB with a league whose answer is known in advance.

The synthetic league is a strict ladder: eight teams, team 1 strongest through
team 8 weakest, and the stronger team always wins by a margin proportional to
the gap. A model that has learned anything at all must pick nearly every game
right, so a hit rate near chance here means the walk-forward plumbing is broken
(the board arriving empty, the wrong team credited, the date filter inverted) —
not that basketball is hard.

The date filter is the thing most worth pinning. A backtest that lets a game
into its own board reports superb accuracy and is worthless, and the failure is
invisible in the output: the numbers just look good.

Run: python tracker/test_backtest.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_backtest_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute                     # noqa: E402
import helpers.backtest as BT                       # noqa: E402

PASS = 0
SEASON = "2025-2026"
N_TEAMS = 8


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


# ── the ladder ───────────────────────────────────────────────────────────────
for t in range(1, N_TEAMS + 1):
    execute("INSERT INTO teams (id, name, gender, class) VALUES (?,?,?,?)",
            (t, f"Team {t}", "F", "3A"))

# Six round-robin passes on six dates. Home/away alternate by pass so the home
# side is not confounded with strength, which is what lets the measured home
# lean mean anything.
DAYS = [f"2026-01-{d:02d}" for d in (5, 12, 19, 26)] + ["2026-02-02", "2026-02-09"]
#: Points per rung. Wider than DEFAULT_HCA on purpose: at a 2-point rung the
#: +3 home bump flips every adjacent matchup, and the test would be measuring
#: the home-court constant rather than whether the ladder was recovered.
RUNG = 6
#: Two more round-robins, flagged NEUTRAL. This league has no real home
#: advantage, so the neutral games are the control that lets the measured
#: home lean be read against the constant the model applied.
NEUTRAL_DAYS = ["2026-02-16", "2026-02-23"]


def _play(day, pass_i, neutral):
    for a in range(1, N_TEAMS + 1):
        for b in range(a + 1, N_TEAMS + 1):
            home, away = (a, b) if pass_i % 2 == 0 else (b, a)
            # the stronger (lower id) side wins by RUNG points per rung, home
            # or away — this league's floor is worth nothing
            hs = 60 + (N_TEAMS - home) * RUNG
            as_ = 60 + (N_TEAMS - away) * RUNG
            execute("INSERT INTO games (team1_id, team2_id, date, home_score, "
                    "away_score, season, neutral) VALUES (?,?,?,?,?,?,?)",
                    (home, away, day, hs, as_, SEASON, 1 if neutral else 0))


for pass_i, day in enumerate(DAYS):
    _play(day, pass_i, neutral=False)
for pass_i, day in enumerate(NEUTRAL_DAYS):
    _play(day, pass_i, neutral=True)

# One walkover, which must never reach a margin engine (see `forfeit-rule`).
# On its own date: `ux_games_matchup` is a real UNIQUE index on the matchup for
# untracked games, so re-using a date this pair already played is a constraint
# error rather than a second row (see `games-matchup-index-is-partial`).
_FF = execute("INSERT INTO games (team1_id, team2_id, date, home_score, "
              "away_score, season, neutral) VALUES (?,?,?,?,?,?,0)",
              (8, 1, "2026-03-02", 2, 0, SEASON))

_ROUND = N_TEAMS * (N_TEAMS - 1) // 2
games = BT.finished_games("F", SEASON)
ok(len(games) == (len(DAYS) + len(NEUTRAL_DAYS)) * _ROUND,
   f"every scheduled game is read back ({len(games)})")
ok(all(g["id"] != _FF for g in games),
   "the 2-0 walkover is excluded, not scored as a 2-point game")

# ── the date filter — the thing that makes it a backtest ─────────────────────
_day2 = DAYS[1]
_incl = BT.game_ids_through(_day2, "F", SEASON)
_strict = BT.game_ids_through(_day2, "F", SEASON, strict=True)
ok(len(_incl) > len(_strict),
   "inclusive 'on or before' sees that day's games; strict does not")
ok(len(_strict) == _ROUND,
   "strictly-before on the second date is exactly the first date's games")
ok(set(_strict) < set(_incl), "strict is a subset, not a different set")

# ── the as-of board ──────────────────────────────────────────────────────────
ok(BT.ratings_as_of(DAYS[0], "F", SEASON, strict=True) == {},
   "a board with no prior games returns {}, not a board of noise")
_early = BT.ratings_as_of(DAYS[1], "F", SEASON)
ok(_early, "a board solves once enough games exist")
ok(_early[1]["Rank"] < _early[8]["Rank"],
   "the ladder is recovered: team 1 outranks team 8 on the as-of board")

_late = BT.ratings_as_of(DAYS[-1], "F", SEASON)
ok(_late[1]["GP"] > _early[1]["GP"],
   "a later date carries more games for the same team")

# ── walk-forward ─────────────────────────────────────────────────────────────
res = BT.walk_forward("F", SEASON)
s = res["summary"]
ok(s["n"] > 0, f"the walk-forward scores games ({s['n']} of {s['n_all']})")
ok(s["hit"] > 0.95,
   f"a strict ladder is picked almost perfectly (hit {s['hit']})")
ok(s["mae"] < 4.0, f"margins land close on a deterministic league ({s['mae']})")

# The two constants the test can price, on a league where the true answer is
# known: this floor is worth nothing, so the model's own home bump is the whole
# of its home lean, and the neutral control must back that out to zero.
import helpers.team_ratings as _TR                  # noqa: E402
ok(abs(s["bias_home"] - _TR.DEFAULT_HCA) < 0.5,
   f"on home floors the lean recovers the constant the model applied "
   f"({s['bias_home']} vs hca {_TR.DEFAULT_HCA})")
ok(abs(s["bias_neutral"]) < 0.5,
   f"on neutral floors, where no bump is granted, there is no lean "
   f"({s['bias_neutral']})")
ok(abs(s["bias"]) < abs(s["bias_home"]),
   "the overall bias is diluted by the neutral games, which is why the split "
   "is reported")
ok(s["hca_measured"] is not None and abs(s["hca_measured"]) < 1.0,
   f"against a neutral control, the measured home court is ~0 — this league's "
   f"floor is worth nothing ({s['hca_measured']})")

_days_seen = {r["day"] for r in res["rows"]}
ok(DAYS[0] not in _days_seen,
   "the FIRST date is never scored — nothing existed to predict it from")
ok(all(r["min_gp"] >= 1 for r in res["rows"]),
   "no row is predicted off a team with zero prior games")

# The calibration and confidence tables must account for the same games the
# headline does, or the panel says two different things on one screen.
_cal_n = sum(r["n"] for r in res["calibration"])
ok(_cal_n == s["n_decided"],
   f"calibration bins cover every decided game ({_cal_n} vs {s['n_decided']})")
ok(sum(r["n"] for r in res["by_confidence"]) == s["n_all"],
   "the confidence table covers every predicted game, thin ones included")

ok(BT.worst_misses(res["rows"], top=3) ==
   sorted([r for r in res["rows"] if r["min_gp"] >= BT.MIN_TEAM_GP],
          key=lambda r: -r["abs_err"])[:3],
   "worst_misses is sorted by absolute error, biggest first")

print(f"\nALL {PASS} CHECKS PASSED")
