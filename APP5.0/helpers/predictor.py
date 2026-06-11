"""
predictor.py — Pre-game matchup predictor (the "War Room").

APP5.0 already opponent-adjusts team ratings (helpers/team_ratings) and predicts
a point spread; what it lacked was EvanMiya's *matchup preview*: pick any two
teams and get a projected score, a win probability, and — most importantly — a
transparent, line-by-line breakdown of where the number comes from (adjusted-net
edge + class bridge + home court). This module assembles exactly that on top of
the existing ratings, so it inherits the SRS opponent adjustment and shrinkage
for free and never re-touches game_events.

Win probability is a closed-form normal model on the projected margin (same math
family as helpers/win_probability, single-game SD instead of in-game time
decay). Pure data layer: depends on team_ratings + win_probability only.
"""
from __future__ import annotations

import helpers.team_ratings as TR
import helpers.win_probability as WP


# SD of a single game's actual margin around the predicted margin (points).
# Wider than the in-game SD_FULL because it includes pre-game uncertainty about
# how the two specific teams match up; ~11 fits HS scoring. Tunable.
PREGAME_SD = 11.0


def win_prob_from_margin(margin, sd=PREGAME_SD):
    """P(favorite covers 0) given a projected `margin`, via the normal CDF."""
    if sd <= 0:
        return 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
    return WP._norm_cdf(margin / sd)


def _confidence(spread, min_gp):
    if min_gp < 3:
        return "Low · thin sample"
    if spread >= 12:
        return "High"
    if spread >= 6:
        return "Solid"
    if spread >= 2.5:
        return "Lean"
    return "Coin flip"


def predict_game(team_a, team_b, scored=None, tracked=None, gender=None,
                 home=None, hca=TR.DEFAULT_HCA, pregame_sd=PREGAME_SD):
    """
    Predict team_a vs team_b.

    `scored` / `tracked` are score_ratings / tracked_ratings dicts (computed for
    `gender` if omitted — pass cached ones from the page). `home` = team_a or
    team_b to grant home court (+hca), or None for a neutral floor.

    Returns None if either team is unrated, else a dict:
        team_a, team_b, a_name, b_name,
        pf_a, pf_b,                 projected points
        total,                      projected combined points
        margin,                     a − b (signed)
        favorite, underdog, spread, favorite is favored by `spread`
        win_prob_a, win_prob_b,
        components: [{label, value, note}],   line-by-line margin build-up
        confidence, method ('score'|'tracked'), home,
        tracked: {pf_a, pf_b, pace, ortg_a, ortg_b} | None   (if both tracked)
    """
    if scored is None:
        scored = TR.score_ratings(gender=gender)
    if not scored or team_a not in scored or team_b not in scored:
        return None
    A, B = scored[team_a], scored[team_b]

    # authoritative margin (adjusted-net + class bridge + home court)
    margin = TR.predict_spread(scored, team_a, team_b, home=home, hca=hca)

    # projected total from opponent-adjusted offense vs opponent-adjusted defense
    exp_a = (A["xPPG"] + B["xoPPG"]) / 2
    exp_b = (B["xPPG"] + A["xoPPG"]) / 2
    total = exp_a + exp_b
    # reconcile the score line to the authoritative margin
    pf_a = (total + margin) / 2
    pf_b = (total - margin) / 2

    wp_a = win_prob_from_margin(margin, pregame_sd)

    # line-by-line build-up of the margin
    net_edge = A["AdjNet"] - B["AdjNet"]
    class_edge = A["ClassAdj"] - B["ClassAdj"]
    hca_val = 0.0
    if home == team_a:
        hca_val = hca
    elif home == team_b:
        hca_val = -hca
    components = [
        {"label": "Adjusted-net edge", "value": round(net_edge, 1),
         "note": f"{A['name']} {A['AdjNet']:+.1f} vs {B['name']} {B['AdjNet']:+.1f} (opp-adjusted)"},
        {"label": "Class bridge", "value": round(class_edge, 1),
         "note": f"{A['class']} vs {B['class']} school-size adjustment"},
        {"label": "Home court", "value": round(hca_val, 1),
         "note": "neutral floor" if home is None else
                 f"+{hca:.0f} to {(A if home == team_a else B)['name']}"},
    ]

    favorite, underdog = (team_a, team_b) if margin >= 0 else (team_b, team_a)
    min_gp = min(A.get("GP", 0), B.get("GP", 0))

    out = {
        "team_a": team_a, "team_b": team_b,
        "a_name": A["name"], "b_name": B["name"],
        "pf_a": round(pf_a, 1), "pf_b": round(pf_b, 1),
        "total": round(total, 1),
        "margin": round(margin, 1),
        "favorite": favorite, "underdog": underdog, "spread": round(abs(margin), 1),
        "win_prob_a": round(wp_a, 3), "win_prob_b": round(1 - wp_a, 3),
        "components": components,
        "confidence": _confidence(abs(margin), min_gp),
        "method": "score", "home": home,
        "tracked": None,
    }

    # richer projection if both teams have tracked possession data
    if tracked and team_a in tracked and team_b in tracked:
        TA, TB = tracked[team_a], tracked[team_b]
        pace = (TA["Pace"] + TB["Pace"]) / 2
        ortg_a = (TA["ORtg"] + TB["DRtg"]) / 2
        ortg_b = (TB["ORtg"] + TA["DRtg"]) / 2
        out["tracked"] = {
            "pace": round(pace, 1),
            "ortg_a": round(ortg_a, 1), "ortg_b": round(ortg_b, 1),
            "pf_a": round(ortg_a * pace / 100, 1),
            "pf_b": round(ortg_b * pace / 100, 1),
        }
    return out
