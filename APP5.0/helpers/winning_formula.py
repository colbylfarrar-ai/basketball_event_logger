"""
winning_formula.py — what actually decides games in THIS league (spec 5l).

Every other engine here answers "how good is X". This one answers the question
underneath all of them: **of the edges a team can win, which one moves the
scoreboard most in this particular league?**

Dean Oliver published four-factor weights — 0.40 shooting / 0.25 turnovers /
0.20 rebounding / 0.15 free throws — fitted on the NBA. Those four numbers get
quoted in high-school gyms every winter as if they were physics. Nobody has ever
re-fitted them on 5A Oklahoma girls' basketball. This does, per gender pool, and
re-fits as games accrue.

WHAT THIS IS NOT
----------------
It is NOT a discovery that shooting wins games. Factor differentials and point
margin are mechanically linked: if you shoot better, turn it over less, rebound
more of your misses and get to the line more than your opponent, you scored
more — by arithmetic, not by insight. Any surface that presents "eFG%
differential correlates with winning" as a finding is showing a coach a
tautology dressed as analysis.

The tell is in the numbers themselves. The four-factor model reconstructs margin
at cross-validated R² ≈ 0.98 on the live book. That is NOT the model being
brilliant; that is the model being an accounting identity. A LOW R² here would
mean the plumbing is broken, so `reconstruction_r2` is used as a SANITY CHECK on
the inputs and is deliberately never presented as predictive skill.

WHAT IT IS
----------
The genuinely unknown quantity is the EXCHANGE RATE: in this league, how many
points of margin does one standard deviation of rebounding edge buy compared to
one standard deviation of shooting edge? That ratio is a real property of a
competition — a league with poor shooting and long rebounds weights the glass
far more heavily than the NBA does — and the interesting output is not the
ranking on its own but the ranking VERSUS OLIVER'S. "Your league is won on
turnovers, not the arc" is a sentence worth a coach's time precisely because the
published weights say otherwise.

TWO TIERS, ON PURPOSE
---------------------
  * CORE — the canonical four factors, and the only thing that enters the fit.
    Keeping the model to Oliver's four is what makes the comparison legitimate;
    adding more predictors would produce shares that are not comparable to his.
  * CONTEXT — three-point diet, ball movement, disruption, pace. Reported as
    plain correlations only. These are largely DOWNSTREAM of the four (a steal
    is an opponent turnover), so putting them in the fit would let collinearity
    quietly redistribute the four-factor weights. Measured on the live book,
    disruption correlates 0.815 with margin and yet carries a near-zero
    coefficient once turnovers are in the model — which is the right answer
    (it works THROUGH turnovers) and exactly why it is not a fifth factor.

Pure data layer: numpy for the solve, no streamlit, no plotting.
"""
from __future__ import annotations

import math

import helpers.stats as S
import helpers.seasons as SEAS
from database.db import query

#: Minimum games before a league fit is attempted. Below this the
#: standardization itself is unstable, never mind the coefficients.
MIN_LEAGUE_GAMES = 12

#: Minimum games before a single TEAM's own formula is offered. One team's games
#: are noisier per row than the pool's, and a coach reads a team-scoped number as
#: being about them specifically, so it has to be worth reading.
MIN_TEAM_GAMES = 8

#: Ridge penalty. Fixed rather than CV-tuned: with n in the tens, tuning lambda
#: by the same cross-validation used to report fit quality would leak the test
#: fold into model selection. A fixed penalty with an honest LOO score is the
#: better trade at this sample size.
RIDGE_LAMBDA = 1.0

#: Below this reconstruction R² something is wrong with the inputs — the four
#: factors are an accounting identity for margin, so they cannot fail to fit
#: unless boxes and scores disagree. Not a skill bar; a plumbing alarm.
MIN_RECONSTRUCTION_R2 = 0.5

#: The canonical four, in Oliver's order. (key, label, coaching noun,
#: Oliver's published NBA weight).
CORE = (
    ("eFG",  "Shooting edge (eFG%)",         "the arc and the finish", 0.40),
    ("TOV",  "Ball-security edge (TOV%)",    "taking care of it",      0.25),
    ("ORB",  "Offensive-glass edge (OREB%)", "the glass",              0.20),
    ("FTR",  "Free-throw edge (FT rate)",    "the line",               0.15),
)

#: Descriptive companions — correlated with winning, never fitted. See the
#: module docstring for why adding them to the model would corrupt the shares.
CONTEXT = (
    ("3PR",  "Three-point diet (3PA share)", "shot selection"),
    ("AST",  "Ball movement (AST per FGM)",  "moving the ball"),
    ("STK",  "Disruption (steals + blocks)", "getting after it"),
    ("PACE", "Pace (possessions)",           "tempo"),
)

CORE_KEYS = tuple(k for k, _l, _n, _w in CORE)
CONTEXT_KEYS = tuple(k for k, _l, _n in CONTEXT)
ALL_KEYS = CORE_KEYS + CONTEXT_KEYS
LABEL = ({k: l for k, l, _n, _w in CORE} | {k: l for k, l, _n in CONTEXT})
NOUN = ({k: n for k, _l, n, _w in CORE} | {k: n for k, _l, n in CONTEXT})
OLIVER = {k: w for k, _l, _n, w in CORE}


def _safe(n, d):
    return (n / d) if d else None


def _factor_set(box, opp):
    """The raw factor values for one team in one game.

    Every value is oriented so HIGHER IS BETTER before differencing, so a
    differential's sign needs no per-factor lookup downstream. TOV% is negated
    at source (fewer turnovers is better) rather than flipped later, where the
    flip would be easy to lose in a refactor.
    """
    poss = S.estimate_possessions(box)
    # S.efg returns 0.0 rather than None on a box with no attempts, which would
    # enter the fit as "shot terribly" instead of "no data". A team-game with
    # zero FGA but some turnovers would otherwise slip through, since TOV% is
    # computable off possessions alone.
    fga = box["FGA"]
    return {
        "eFG": (S.efg(box) if fga else None),
        "TOV": (-_safe(box["TOV"], poss) if poss else None),
        "ORB": _safe(box["ORB"], box["ORB"] + opp["DRB"]),
        "FTR": _safe(box["FTM"], box["FGA"]),
        "3PR": _safe(box["3PA"], box["FGA"]),
        "AST": _safe(box["AST"], box["FGM"]),
        "STK": _safe(box["STL"] + box["BLK"], poss),
        "PACE": float(poss) if poss else None,
    }


def game_rows(gender=None, season="Current", game_ids=None, events=None):
    """One row per (game, team): factor differentials and the point margin.

    Returns [{game_id, team_id, opp_id, margin, won, diffs: {key: value}}].
    Both teams in a game produce a row and the two are exact mirrors (margin and
    every differential negated). That symmetry is deliberate: the design matrix
    is balanced, so the fit cannot invent a home-court intercept it has no
    business learning on a book where 3.7% of games record a location.

    PACE is the one entry that is NOT a differential — both teams share a
    possession count by construction — so it enters as a level. It is context
    only and never reaches the model.
    """
    if game_ids is None:
        game_ids = sorted(SEAS.game_pool(season, gender=gender,
                                         tracked_only=True))
    game_ids = [int(g) for g in game_ids]
    if not game_ids:
        return []
    if events is None:
        events = S.fetch_events(game_ids)

    team_of = {r["id"]: r["team_id"] for r in query(
        "SELECT id, team_id FROM players")}

    by_game = {}
    for e in events:
        by_game.setdefault(e["game_id"], []).append(e)

    out = []
    for gid in game_ids:
        evs = by_game.get(gid)
        if not evs:
            continue
        boxes = S.aggregate_player_boxes(events=evs)
        per_team = {}
        for pid, b in boxes.items():
            tid = team_of.get(pid)
            if tid is None:
                continue
            tb = per_team.setdefault(tid, S._blank_box())
            for k in tb:
                tb[k] += b.get(k, 0)
        if len(per_team) != 2:
            continue                      # one-sided log; not a scoreable game
        per_team = {t: S.finalize_box(b) for t, b in per_team.items()}
        (ta, ba), (tb_id, bb) = per_team.items()
        for me, mine, opp, theirs in ((ta, ba, tb_id, bb), (tb_id, bb, ta, ba)):
            fa, fb = _factor_set(mine, theirs), _factor_set(theirs, mine)
            diffs = {}
            for key in ALL_KEYS:
                if key == "PACE":
                    diffs[key] = fa[key]          # shared level, not a diff
                elif fa[key] is None or fb[key] is None:
                    diffs[key] = None
                else:
                    diffs[key] = fa[key] - fb[key]
            out.append({"game_id": gid, "team_id": me, "opp_id": opp,
                        "margin": mine["PTS"] - theirs["PTS"],
                        "won": mine["PTS"] > theirs["PTS"],
                        "diffs": diffs})
    return out


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs)
                    * sum((b - my) ** 2 for b in ys))
    return (num / den) if den else None


def _ridge_standardized(X, y, lam=RIDGE_LAMBDA):
    """Ridge on z-scored columns and a centred target.

    Betas come out in points of margin per ONE STANDARD DEVIATION of that
    differential in this pool — the only scale on which "shooting vs rebounding"
    is a fair question, since the raw units are not commensurable.
    """
    import numpy as np
    A = np.asarray(X, dtype=float)
    t = np.asarray(y, dtype=float)
    mu = A.mean(axis=0)
    sd = A.std(axis=0)
    sd[sd == 0] = 1.0
    Z = (A - mu) / sd
    ybar = t.mean()
    p = Z.shape[1]
    beta = np.linalg.solve(Z.T @ Z + lam * np.eye(p), Z.T @ (t - ybar))
    return beta, mu, sd, ybar


def _loo_r2(X, y, lam=RIDGE_LAMBDA):
    """Leave-one-out R². Used as a RECONSTRUCTION check, not a skill claim —
    see the module docstring. In-sample R² on tens of rows would be a formality
    whatever the data said, so even the plumbing alarm is cross-validated."""
    import numpy as np
    A = np.asarray(X, dtype=float)
    t = np.asarray(y, dtype=float)
    n = len(t)
    if n < 6:
        return None
    preds = np.empty(n)
    idx = np.arange(n)
    for i in range(n):
        keep = idx != i
        beta, mu, sd, ybar = _ridge_standardized(A[keep], t[keep], lam)
        preds[i] = ybar + float(((A[i] - mu) / sd) @ beta)
    ss_res = float(((t - preds) ** 2).sum())
    ss_tot = float(((t - t.mean()) ** 2).sum())
    return (1.0 - ss_res / ss_tot) if ss_tot else None


def _fit(rows, min_games):
    """Shared fit for the league and single-team paths.

    Result keys:
      enough        — cleared the game minimum
      valid         — reconstruction R² is high enough to trust the inputs
      recon_r2      — LOO R² of the four-factor model (a plumbing check)
      factors       — the four CORE entries: beta, share, oliver, gap, r
      context       — the CONTEXT entries: correlation only, no beta
      n_games/n_rows
    """
    usable = [r for r in rows
              if all(r["diffs"].get(k) is not None for k in CORE_KEYS)]
    n_games = len({r["game_id"] for r in usable})
    base = {"n_rows": len(usable), "n_games": n_games,
            "min_games": min_games, "factors": [], "context": [],
            "recon_r2": None, "enough": False, "valid": False}
    if n_games < min_games:
        return base

    base["enough"] = True
    y = [r["margin"] for r in usable]
    X = [[r["diffs"][k] for k in CORE_KEYS] for r in usable]

    try:
        beta, _mu, sd, _yb = _ridge_standardized(X, y)
        recon = _loo_r2(X, y)
    except Exception:
        return base

    base["recon_r2"] = round(recon, 3) if recon is not None else None
    base["valid"] = bool(recon is not None and recon >= MIN_RECONSTRUCTION_R2)

    # Shares are taken over |beta| so they are comparable to Oliver's weights,
    # which are also a positive-sum decomposition. A negative coefficient on a
    # good-oriented differential is a small-sample artifact, not a factor that
    # hurts you, so its magnitude is what enters the share.
    mags = [abs(float(b)) for b in beta]
    tot = sum(mags) or 1.0
    for i, k in enumerate(CORE_KEYS):
        col = [r["diffs"][k] for r in usable]
        share = mags[i] / tot
        base["factors"].append({
            "key": k, "label": LABEL[k], "noun": NOUN[k],
            "beta": round(float(beta[i]), 2),
            "share": round(share, 3),
            "oliver": OLIVER[k],
            "gap": round(share - OLIVER[k], 3),
            "sd": round(float(sd[i]), 4),
            "r": (lambda c: round(c, 3) if c is not None else None)(
                _pearson(col, y)),
        })
    base["factors"].sort(key=lambda f: -f["share"])

    for k in CONTEXT_KEYS:
        col = [r["diffs"].get(k) for r in usable]
        pairs = [(c, m) for c, m in zip(col, y) if c is not None]
        c = _pearson([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None
        base["context"].append({
            "key": k, "label": LABEL[k], "noun": NOUN[k],
            "r": (round(c, 3) if c is not None else None), "n": len(pairs),
        })
    base["context"].sort(key=lambda f: -abs(f["r"] or 0.0))
    return base


def league_formula(gender=None, season="Current", game_ids=None, events=None,
                   rows=None):
    """What decides games in this gender's tracked pool."""
    if rows is None:
        rows = game_rows(gender=gender, season=season, game_ids=game_ids,
                         events=events)
    return _fit(rows, MIN_LEAGUE_GAMES)


def team_formula(team_id, gender=None, season="Current", game_ids=None,
                 events=None, rows=None):
    """The same fit over one team's own games — "which edge decides YOUR games".

    `rows` accepts a prebuilt `game_rows` result so a surface showing both the
    league and the team pays for ONE event walk, not two.
    """
    if rows is None:
        rows = game_rows(gender=gender, season=season, game_ids=game_ids,
                         events=events)
    return _fit([r for r in rows if r["team_id"] == team_id], MIN_TEAM_GAMES)


#: A share has to beat Oliver's by this much before it is worth a sentence.
#: Anything smaller is inside what a few dozen games can resolve.
NOTABLE_GAP = 0.08


def verdict(fit, *, scope="this league"):
    """One coaching sentence, or an honest refusal.

    Refuses in two cases: too few games, and a reconstruction R² so low that the
    boxes and the scores must disagree. Never claims predictive skill — the
    claim is always about the EXCHANGE RATE between edges.
    """
    if not fit or not fit.get("enough"):
        need = (fit or {}).get("min_games", MIN_LEAGUE_GAMES)
        have = (fit or {}).get("n_games", 0)
        return {"kind": "thin",
                "text": f"Not enough tracked games to fit {scope} yet — "
                        f"{have} of the {need} needed."}
    if not fit.get("valid"):
        return {"kind": "broken",
                "text": f"The four factors should reconstruct margin almost "
                        f"exactly, and here they do not (R² {fit['recon_r2']}). "
                        f"That points at the box data, not at {scope} — the "
                        f"ranking below is not safe to read."}
    top = fit["factors"][0]
    parts = [f"In {scope}, the biggest lever on the scoreboard is "
             f"**{top['noun']}** ({top['label']}): one standard deviation of it "
             f"is worth **{abs(top['beta']):.1f} points** of margin, "
             f"**{top['share'] * 100:.0f}%** of the four factors' combined pull."]
    # the part a coach cannot get anywhere else: how this league differs from
    # the weights everyone quotes
    diffs = sorted(fit["factors"], key=lambda f: -abs(f["gap"]))
    big = diffs[0]
    if abs(big["gap"]) >= NOTABLE_GAP:
        direction = "more" if big["gap"] > 0 else "less"
        # phrased without a verb agreeing with `scope`, so callers can pass
        # "this league" or "your games" without breaking the sentence
        parts.append(
            f"That is **{direction} weight on {big['noun']}** than Dean "
            f"Oliver's NBA weights predict "
            f"({big['share'] * 100:.0f}% here vs {big['oliver'] * 100:.0f}% "
            f"in the textbook).")
    parts.append(f"Fitted on {fit['n_games']} tracked games.")
    return {"kind": "verdict", "text": " ".join(parts), "top": top,
            "biggest_gap": big, "n_games": fit["n_games"]}


def verdict_lines(team_fit, league_fit):
    """[(badge, n, html)] for helpers.cards.verdict_card — verdict-first, and
    silent about anything the sample cannot support.

    Leads with the TEAM read when it exists, because "which edge decides YOUR
    games" is the question a coach actually has, and follows with the league
    line only when it says something different. Two identical sentences in one
    box reads as a bug.
    """
    lines = []
    tv = verdict(team_fit, scope="your games") if team_fit else None
    lv = verdict(league_fit, scope="this league") if league_fit else None

    def _plain(t):
        return t.replace("**", "")

    if tv and tv["kind"] == "verdict":
        top = tv["top"]
        lines.append((
            "Your games", team_fit["n_games"],
            f"Decided most by <b>{top['noun']}</b> — one standard deviation of "
            f"{top['label'].split(' (')[0].lower()} is worth "
            f"<b>{abs(top['beta']):.1f} points</b> of margin, "
            f"<b>{top['share'] * 100:.0f}%</b> of the four factors' pull."))
    if lv and lv["kind"] == "verdict":
        lt = lv["top"]
        same = (tv and tv.get("kind") == "verdict"
                and tv["top"]["key"] == lt["key"])
        if same:
            lines.append((
                "The league", league_fit["n_games"],
                f"Same lever league-wide (<b>{lt['share'] * 100:.0f}%</b> of the "
                f"pull vs Dean Oliver's <b>{lt['oliver'] * 100:.0f}%</b> for "
                f"{lt['noun']}) — this is how the whole competition plays, not "
                f"a quirk of your roster."))
        else:
            lines.append((
                "The league", league_fit["n_games"],
                f"League-wide the biggest lever is <b>{lt['noun']}</b> "
                f"(<b>{lt['share'] * 100:.0f}%</b> of the pull) — your games "
                f"turn on something else."))
    elif lv:
        lines.append(("The league", (league_fit or {}).get("n_games", 0),
                      _plain(lv["text"])))
    if not lines and tv:
        lines.append(("Your games", (team_fit or {}).get("n_games", 0),
                      _plain(tv["text"])))
    return lines


def suppressors(fit):
    """Factors whose fitted contribution and raw correlation disagree in sign.

    Worth surfacing rather than hiding: on the live book FT-rate edge carries a
    POSITIVE coefficient but a NEGATIVE raw correlation with margin (r = -0.143),
    because losing teams get fouled deliberately late — the raw column is picking
    up game state, and the fit is what removes it. A reader comparing the two
    columns will notice the clash, so the surface should explain it first.
    """
    out = []
    for f in fit.get("factors", []):
        if f["r"] is None or f["beta"] is None:
            continue
        if (f["r"] > 0) != (f["beta"] > 0):
            out.append(f)
    return out
