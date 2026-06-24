"""
selfscout.py — "how scoutable are we?" predictability engine (Tier 1, ML_LAYER_ROADMAP).

The scout tab already re-runs the opponent sheet on yourself; what it does NOT give is
the two reads an opposing coach actually makes when prepping you:

  1. Predictability (scoutability) — a single 0–100 score from the Shannon ENTROPY of
     your tagged play-call mix. A team that runs one set 60% of the time is trivial to
     key on; a balanced mix is hard to game-plan. Low entropy → high predictability.

  2. Tendency drift vs league — which sets you OVER-use *and* are inefficient at
     (predictable AND bad → a scout's gift), and which you UNDER-use *and* are good at
     (a weapon you're leaving on the shelf). The cross-check (share × league
     percentile) is the point — being predictable is only a problem if the predictable
     thing isn't working.

Both run off the explicit one-tap `play_type` tags (and, for the defense twin, the
`defense` tags), reusing playtypes/defenses' percentile machinery so the league
baseline matches every other surface. Works for YOUR team (self-scout) or any
opponent (their scoutability). Pure data layer — no streamlit. Honest at this scale:
silent / "thin" when tagging is sparse; entropy is reported with the tagged-shot count
so a coach never reads a confident number off 9 shots.
"""
from __future__ import annotations

import math

import helpers.playtypes as PT
import helpers.defenses as DEF


# Don't emit a scoutability score off fewer than this many tagged shots — entropy on a
# tiny sample is noise. Drift flags use the per-set MIN_POSS gate playtypes already owns.
MIN_TAGGED = 20

# Over/under-use thresholds (share of tagged offense) and the league-percentile cut
# that decides "inefficient" (<=35th) vs "efficient" (>=65th).
OVERUSE_SHARE = 0.22
UNDERUSE_SHARE = 0.08
LOW_PCT = 35
HIGH_PCT = 65


def _entropy_index(shares):
    """Normalized Shannon entropy of a share vector → 0–100 'unpredictability'.
    1.0·100 = perfectly balanced across the present sets; 0 = one set every time.
    Normalized by log(k) so the score doesn't just reward having more set types."""
    ps = [s for s in shares if s and s > 0]
    if len(ps) <= 1:
        return 0.0
    h = -sum(p * math.log(p) for p in ps)
    return round(100.0 * h / math.log(len(ps)), 1)


def _scoutability_from_rows(rows, label_key="label"):
    """Shared core: rows = [{share, ...}] → {entropy, predictability, top, mix}."""
    rows = [r for r in rows if r.get("poss")]
    shares = [r["share"] for r in rows]
    entropy = _entropy_index(shares)
    top = max(rows, key=lambda r: r["share"]) if rows else None
    return {
        "entropy": entropy,                       # 0–100, higher = harder to scout
        "predictability": round(100 - entropy, 1),  # the headline "scoutability" score
        "top_set": (top[label_key] if top else None),
        "top_share": (round(top["share"] * 100, 1) if top else None),
        "n_sets": len(rows),
    }


def scoutability(team_id, gender=None, events=None, offense=True):
    """The headline predictability read for one team's OFFENSIVE play-call mix.

    Returns {"predictability","entropy","top_set","top_share","n_sets","tagged",
    "rated"} — `rated` is False (and the score is None-ish/low-confidence) when the
    team has fewer than MIN_TAGGED tagged shots. `predictability` 0–100: higher = more
    scoutable (a scout keys on you fast)."""
    pct = PT.team_named_playtype_percentiles(
        team_id, gender=gender, events=events, offense=offense)
    tagged = pct.get("total_tagged", 0)
    core = _scoutability_from_rows(pct["rows"])
    core["tagged"] = tagged
    core["rated"] = tagged >= MIN_TAGGED
    if not core["rated"]:
        core["predictability"] = None
        core["entropy"] = None
    return core


def defense_scoutability(team_id, gender=None, events=None):
    """The defensive twin: how predictable is the team's DEFENSIVE scheme mix (the
    shots it allowed, grouped by the defense it ran)? Same entropy → predictability."""
    fam = DEF.team_defense_families(team_id, gender=gender, events=events, offense=False)
    tagged = fam.get("total_tagged", 0)
    core = _scoutability_from_rows(fam["rows"])
    core["tagged"] = tagged
    core["rated"] = tagged >= MIN_TAGGED
    if not core["rated"]:
        core["predictability"] = None
        core["entropy"] = None
    return core


def tendency_drift(team_id, gender=None, events=None, offense=True):
    """Over/under-use flags vs the league, cross-checked with efficiency.

    Returns {"overused":[...], "underused":[...]} where each row is a play-call dict
    (key,label,share,PPP,pct,lg_ppp) that is:
      • overused  — share ≥ OVERUSE_SHARE AND league pct ≤ LOW_PCT (predictable AND
                    inefficient → the scout's gift; cut it or fix it).
      • underused — share ≤ UNDERUSE_SHARE AND league pct ≥ HIGH_PCT AND real volume
                    (a weapon you're under-running).
    Only ranked rows (enough possessions + pool) carry a pct, so unranked sets never
    trip a flag — silent until the data supports it."""
    pct = PT.team_named_playtype_percentiles(
        team_id, gender=gender, events=events, offense=offense)
    over, under = [], []
    for r in pct["rows"]:
        p = r.get("pct")
        if p is None:
            continue
        if r["share"] >= OVERUSE_SHARE and p <= LOW_PCT:
            over.append(r)
        elif r["share"] <= UNDERUSE_SHARE and p >= HIGH_PCT and r["poss"] >= PT.MIN_POSS:
            under.append(r)
    over.sort(key=lambda r: -r["share"])
    under.sort(key=lambda r: -(r["pct"] or 0))
    return {"overused": over, "underused": under}


def self_scout_report(team_id, gender=None, events=None):
    """Bundle for the scout tab's self-scout section: offensive scoutability, the
    defensive twin, and the over/under-use drift. One call, one events pass when the
    caller pre-fetches `events`."""
    return {
        "offense": scoutability(team_id, gender=gender, events=events, offense=True),
        "defense": defense_scoutability(team_id, gender=gender, events=events),
        "drift": tendency_drift(team_id, gender=gender, events=events, offense=True),
    }
