"""
backtest.py — the matchup predictor, back in time, and priced against what
actually happened.

Two surfaces, one mechanism.

  * **As of a date.** Rankings already has a week picker, and it is a pure table
    read: `rating_snapshots` stores a rank and a rating per team per day, which
    is all a BOARD needs (`helpers/resume.py`). A MATCHUP needs more than that —
    `predictor.predict_game` reads `AdjNet`, `ClassAdj`, `xPPG`, `xoPPG` and
    `GP` — and none of those are in the snapshot table. So the matchup's version
    of "back in time" cannot be the same read. It is a re-solve: both rating
    engines already accept a `game_ids` filter, so handing them the games
    finished on or before a date produces the board that existed then, and the
    predictor consumes it unchanged. `rating_history.backfill_weekly` recovers
    the snapshot table exactly this way — this module is that same move, held in
    memory for one question instead of written to a table.

  * **Walk-forward backtest.** Every prediction the app has ever shown was about
    a game that had not happened. Most of those games have now happened. For
    each finished game, solve the board over the games finished STRICTLY BEFORE
    that game's date, predict it, and compare. Nothing from the game's own day
    is in the board — same-day games are excluded, not just the game itself, so
    a Tuesday result cannot leak into a Tuesday prediction.

    That produces three numbers the app could not otherwise state: how far off a
    prediction typically is, whether it leans one way, and whether a stated
    win probability means what it says. It also PRICES TWO CONSTANTS that were
    adopted by argument rather than measurement — `predictor.PREGAME_SD` (11.0)
    and `team_ratings.DEFAULT_HCA` — because the empirical RMSE of the margin
    error *is* the pre-game SD, and the mean signed error on home floors
    against neutral floors *is* the home-court edge.

WHICH constants "today's" means depends on the process, and the difference is
measurable. `helpers/model_constants.apply()` folds every gate-adopted override
onto the engine globals at app startup (Main.py), so inside Streamlit this
measures the DEPLOYED model. A bare script that has not called `apply()` is
measuring the code defaults instead — on this book that moved the girls' hit
rate 84.7% → 85.3% and the RMSE 12.74 → 12.61, because `DEFAULT_REG` is adopted
at 0.15 rather than its code value. Call `apply()` first when measuring from a
script, or the number is about a model nobody is running.

THE CAVEAT, same as `resume.CAVEAT` and for the same reason: a reconstructed
board is solved with TODAY's model constants, not whatever was adopted at the
time. So this measures how well the CURRENT model would have done, which is the
question worth asking before a recal — and is NOT a claim about what the screen
actually showed in January.

Forfeits are excluded (`helpers/forfeits`): a 2-0 walkover is not a basketball
result and every margin engine in the app already drops it. Leaving them in
would put a 2-point margin against a 30-point prediction and call the model
wrong. See `forfeit-rule`.

Streamlit-free — pure reads plus engine calls, the house convention. The page
owns the render and the caching.
"""
from __future__ import annotations

import math

from database.db import query
import helpers.forfeits as FF
import helpers.seasons as SEAS
import helpers.team_ratings as TR
import helpers.predictor as PRED

#: Fewest finished games in the reconstructed board before it is allowed to
#: predict anything. Under this the SRS solve is fitting noise: two teams, one
#: result, and an "adjusted" net that is the raw margin wearing a hat.
MIN_BOARD_GAMES = 30

#: Fewest games a TEAM must carry in the reconstructed board for its prediction
#: to enter the headline numbers. `predictor._confidence` already calls anything
#: under 3 "Low · thin sample"; the summary honours the same line so the
#: headline is not an average of predictions the app itself labels untrustworthy.
MIN_TEAM_GP = 3

#: Win-probability bins for the calibration table. Reported on the FAVOURITE's
#: probability (always ≥ .5), because a bin pair like .20-.35/.65-.80 is the
#: same bin counted twice from opposite ends.
CAL_BINS = ((0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01))

CAVEAT = (
    "A board solved for a past date uses **today's** model constants, not "
    "whatever was adopted at the time — so this shows what the CURRENT model "
    "makes of that day, not what the screen actually showed back then."
)


def _label(season) -> str:
    """The season label rows are stored under (see resume._label — same two
    resolutions, and both are load-bearing for the same reasons)."""
    s = SEAS.resolve_read_season(season)
    return SEAS.active_label() if SEAS.is_current(s) else str(s)


# ── the games, once ──────────────────────────────────────────────────────────
def finished_games(gender, season=SEAS.DEFAULT) -> list[dict]:
    """Every finished, dated, non-forfeit game for this gender and season,
    oldest first: {id, day, home, away, hs, as_, neutral}.

    `team1_id` is the HOME side and `team2_id` the away side — the column names
    say so (`home_score`/`away_score`) and `news_feed.team_games` reads them
    that way. `neutral` means the venue granted nobody the home floor.
    """
    rows = query(
        """SELECT g.id, g.date, g.team1_id, g.team2_id, g.home_score,
                  g.away_score, g.neutral, g.game_type
           FROM games g JOIN teams t ON t.id = g.team1_id
           WHERE g.season = ? AND t.gender = ?
             AND g.date IS NOT NULL
             AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
           ORDER BY g.date, g.id""",
        (_label(season), gender))
    out = []
    for r in rows:
        day = str(r["date"])[:10]
        if len(day) != 10:               # undated / malformed — cannot be placed
            continue
        hs, as_ = r["home_score"], r["away_score"]
        if FF.is_forfeit(hs, as_) or FF.is_forfeit(as_, hs):
            continue
        out.append({"id": r["id"], "day": day,
                    "home": r["team1_id"], "away": r["team2_id"],
                    "hs": hs, "as_": as_, "neutral": bool(r["neutral"]),
                    "game_type": r["game_type"] or "Regular"})
    return out


# ── the board, as of a date ──────────────────────────────────────────────────
def game_ids_through(day, gender, season=SEAS.DEFAULT, strict=False) -> list[int]:
    """Ids of the finished games this board is allowed to know about.

    `strict=False` is "on or before `day`" — what the Rankings week picker
    means by a board stamped with a date, and what `backfill_weekly` writes.
    `strict=True` is "strictly before", which is what a PREDICTION of a game on
    `day` may use: excluding the whole day, not just the one game, is the
    difference between a walk-forward test and one that has read ahead.
    """
    return [g["id"] for g in finished_games(gender, season)
            if (g["day"] < day if strict else g["day"] <= day)]


def ratings_as_of(day, gender, season=SEAS.DEFAULT, form_weight=0.0,
                  strict=False, _gids=None):
    """The score board as it stood on `day` — the same dict `score_ratings`
    returns, so every consumer (the predictor, the spread, the sims) takes it
    with no change.

    A re-solve, not a table read, and it costs one (0.2 s on the production
    book). `form_weight` is honoured so the War Room's form knob means the same
    thing in the past as it does today: a form-weighted matchup asks who was hot
    THEN, which is the only reading of the knob that makes sense on a date
    picker.

    Returns {} when too few games had been played to solve anything worth
    showing (see MIN_BOARD_GAMES) rather than a board of noise.
    """
    gids = _gids if _gids is not None else game_ids_through(
        day, gender, season, strict=strict)
    if len(gids) < MIN_BOARD_GAMES:
        return {}
    return TR.blended_ratings(gender=gender, season=season, game_ids=gids,
                              form_weight=form_weight)


def tracked_as_of(day, gender, season=SEAS.DEFAULT, strict=False, _gids=None):
    """The tracked (possession) board as of `day`, or {}.

    Separate from `ratings_as_of` and allowed to fail quietly: tracked games are
    a small fraction of the book, so early in a season there is genuinely no
    tracked board to solve, and the predictor already treats a missing tracked
    dict as "no possession detail" rather than as an error.
    """
    gids = _gids if _gids is not None else game_ids_through(
        day, gender, season, strict=strict)
    if not gids:
        return {}
    try:
        return TR.tracked_ratings(gender=gender, season=season, game_ids=gids)
    except Exception:
        return {}


# ── the walk-forward test ────────────────────────────────────────────────────
def _brier(p, won) -> float:
    return (p - (1.0 if won else 0.0)) ** 2


def walk_forward(gender, season=SEAS.DEFAULT, form_weight=0.0,
                 hca=None, progress=None) -> dict:
    """Predict every finished game from the board that existed the day before it.

    One solve per distinct game DATE, not per game: every game on a Tuesday sees
    the identical board (everything through Monday), so solving per game would
    repeat the same 0.2 s work twenty times. A season of one gender is ~100
    dates.

    `hca` defaults to the engine's own home-court constant; the home floor is
    granted only when the game was not at a neutral site, because that is what
    the predictor would have been told pre-game.

    Returns {"rows": [...], "summary": {...}, "calibration": [...],
             "by_confidence": [...]}. `rows` carries one dict per scored game so
    a page can show the worst misses; `summary` is the headline.
    """
    hca = TR.DEFAULT_HCA if hca is None else hca
    games = finished_games(gender, season)
    if not games:
        return {"rows": [], "summary": _summarize([], hca),
                "calibration": [], "by_confidence": []}

    days = sorted({g["day"] for g in games})
    by_day: dict[str, list[dict]] = {}
    for g in games:
        by_day.setdefault(g["day"], []).append(g)

    rows: list[dict] = []
    prior: list[int] = []            # ids of every game finished before `day`
    for i, day in enumerate(days):
        if progress:
            progress(i + 1, len(days), day)
        board = (ratings_as_of(day, gender, season, form_weight=form_weight,
                               _gids=prior) if len(prior) >= MIN_BOARD_GAMES
                 else {})
        if board:
            for g in by_day[day]:
                a, b = g["home"], g["away"]
                if a not in board or b not in board:
                    continue          # a team with no prior game is unrated
                home = None if g["neutral"] else a
                p = PRED.predict_game(a, b, scored=board, home=home, hca=hca)
                if not p:
                    continue
                actual = g["hs"] - g["as_"]
                err = p["margin"] - actual
                fav_is_home = p["margin"] >= 0
                fav_won = (actual > 0) if fav_is_home else (actual < 0)
                rows.append({
                    "game_id": g["id"], "day": day,
                    "home": a, "away": b,
                    "a_name": p["a_name"], "b_name": p["b_name"],
                    "pred": p["margin"], "actual": actual, "err": err,
                    "abs_err": abs(err),
                    "wp_fav": max(p["win_prob_a"], p["win_prob_b"]),
                    "fav_won": fav_won,
                    "push": actual == 0,
                    "neutral": g["neutral"], "game_type": g["game_type"],
                    "confidence": p["confidence"],
                    "min_gp": min(board[a].get("GP", 0), board[b].get("GP", 0)),
                })
        prior.extend(x["id"] for x in by_day[day])

    return {"rows": rows, "summary": _summarize(rows, hca),
            "calibration": calibration(rows), "by_confidence": by_confidence(rows),
            "by_game_type": by_game_type(rows)}


def _summarize(rows, hca) -> dict:
    """The headline numbers, plus the two constants this test can price."""
    scored = [r for r in rows if r["min_gp"] >= MIN_TEAM_GP]
    out = {"n_all": len(rows), "n": len(scored), "min_team_gp": MIN_TEAM_GP,
           "mae": None, "rmse": None, "bias": None, "hit": None, "n_decided": 0,
           "brier": None, "brier_baseline": 0.25, "skill": None,
           "sd_current": PRED.PREGAME_SD, "hca_current": hca,
           "hca_measured": None, "n_home": 0, "n_neutral": 0,
           "bias_home": None, "bias_neutral": None}
    if not scored:
        return out

    errs = [r["err"] for r in scored]
    n = len(errs)
    out["mae"] = round(sum(abs(e) for e in errs) / n, 2)
    out["bias"] = round(sum(errs) / n, 2)
    # RMSE of the margin error IS the empirical pre-game SD — the same quantity
    # PREGAME_SD asserts. Reported next to the constant on purpose.
    out["rmse"] = round(math.sqrt(sum(e * e for e in errs) / n), 2)

    decided = [r for r in scored if not r["push"]]
    out["n_decided"] = len(decided)
    if decided:
        out["hit"] = round(sum(1 for r in decided if r["fav_won"]) / len(decided), 4)
        b = sum(_brier(r["wp_fav"], r["fav_won"]) for r in decided) / len(decided)
        out["brier"] = round(b, 4)
        # Brier skill vs the only honest baseline: a coin flip on every game.
        out["skill"] = round(1 - b / 0.25, 4)

    # The home-court constant, measured. The model already ADDS hca to a home
    # prediction, so a residual bias on home floors that is absent on neutral
    # ones is the amount hca is wrong by — hence measured = hca - (bias_home -
    # bias_neutral), with the neutral games acting as the control for whatever
    # the model gets wrong everywhere.
    home_rows = [r for r in scored if not r["neutral"]]
    neut_rows = [r for r in scored if r["neutral"]]
    out["n_home"], out["n_neutral"] = len(home_rows), len(neut_rows)
    # `bias` above mixes the two, so it under-reads the home lean by whatever
    # share of the book is neutral. The split is what a reader of the home-court
    # number actually wants.
    bh = (sum(r["err"] for r in home_rows) / len(home_rows)) if home_rows else None
    bn = (sum(r["err"] for r in neut_rows) / len(neut_rows)) if neut_rows else None
    out["bias_home"] = None if bh is None else round(bh, 2)
    out["bias_neutral"] = None if bn is None else round(bn, 2)
    if len(home_rows) >= 30 and len(neut_rows) >= 30:
        out["hca_measured"] = round(hca - (bh - bn), 2)
    return out


def calibration(rows) -> list[dict]:
    """Does a stated win probability mean what it says?

    One row per bin: how often the favourite actually won, against what the
    model claimed. A model can have a fine hit rate and still be badly
    calibrated — saying 90% when it means 70% is a different failure from
    picking the wrong team, and a coach who is told "90%" and loses four of ten
    stops believing the number.
    """
    out = []
    scored = [r for r in rows if r["min_gp"] >= MIN_TEAM_GP and not r["push"]]
    for lo, hi in CAL_BINS:
        bucket = [r for r in scored if lo <= r["wp_fav"] < hi]
        if not bucket:
            continue
        out.append({
            "bin": f"{int(lo * 100)}–{min(int(hi * 100), 100)}%",
            "n": len(bucket),
            "said": round(sum(r["wp_fav"] for r in bucket) / len(bucket), 3),
            "actual": round(sum(1 for r in bucket if r["fav_won"]) / len(bucket), 3),
        })
    return out


def by_confidence(rows) -> list[dict]:
    """The predictor's own confidence words, priced. `_confidence` hands a coach
    'High' / 'Solid' / 'Lean' / 'Coin flip'; this says what each one was worth.
    """
    order = ["High", "Solid", "Lean", "Coin flip", "Low · thin sample"]
    out = []
    for label in order:
        bucket = [r for r in rows if r["confidence"] == label]
        if not bucket:
            continue
        decided = [r for r in bucket if not r["push"]]
        out.append({
            "confidence": label, "n": len(bucket),
            "hit": (round(sum(1 for r in decided if r["fav_won"]) / len(decided), 3)
                    if decided else None),
            "mae": round(sum(r["abs_err"] for r in bucket) / len(bucket), 2),
        })
    return out


def by_game_type(rows) -> list[dict]:
    """Bias and error split by game type — and the reason this split is here.

    `games.neutral` is set on **3 rows of a 13,383-game book**, so the home-court
    bump is granted on every game the app has, including the ~1,500 playoff and
    tournament games that are mostly played on a floor neither team owns. If
    that is what drives the model's home lean, the bias on Playoff rows will be
    visibly worse than on Regular ones, and the fix is the neutral flag rather
    than the constant. If the two are the same, the constant itself is too big.
    A season-long mean bias cannot tell those apart; this split can.
    """
    out = []
    scored = [r for r in rows if r["min_gp"] >= MIN_TEAM_GP]
    for label in sorted({r["game_type"] for r in scored}):
        bucket = [r for r in scored if r["game_type"] == label]
        if len(bucket) < 20:
            continue
        n = len(bucket)
        out.append({
            "game_type": label, "n": n,
            "bias": round(sum(r["err"] for r in bucket) / n, 2),
            "mae": round(sum(r["abs_err"] for r in bucket) / n, 2),
            "flagged_neutral": sum(1 for r in bucket if r["neutral"]),
        })
    return sorted(out, key=lambda d: -d["n"])


def worst_misses(rows, top=10) -> list[dict]:
    """The games the model got most wrong, biggest first — the only part of a
    backtest a coach reads first, and the part that makes the rest credible."""
    scored = [r for r in rows if r["min_gp"] >= MIN_TEAM_GP]
    return sorted(scored, key=lambda r: -r["abs_err"])[:top]
