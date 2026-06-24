"""
ref_tendencies.py — pre-game crew outlook (Tier 2, ML_LAYER_ROADMAP).

The Officials Lab already profiles each ref historically (FP100 whistle tightness,
home/away lean, quarter-timing fingerprint, PPP/pace environment, vs-league deltas).
The one missing, game-prep piece: given the CREW assigned to an upcoming game, what
should we expect tonight? This synthesizes the assigned officials' histories into a
league-relative outlook — whistle tightness, home/away lean, scoring environment,
late-game tendency — plus a one-line "play accordingly" read.

Thin synthesis over helpers.officials.official_overview (no new data math); honest at
this scale — flagged low-confidence under a combined games threshold. No streamlit.
"""
from __future__ import annotations

from statistics import mean

import helpers.officials as OFF

MIN_LEAN_FOULS = 6      # min home+away attributable fouls before a lean is meaningful
CONFIDENT_GAMES = 4     # combined crew games-worked for a confident read


def _fp100(r):
    return (r["fouls"] / r["game_poss"] * 100.0) if r.get("game_poss") else 0.0


def crew_outlook(official_pks, gender=None, game_ids=None, overview=None):
    """Pre-game outlook for the crew `official_pks` (a list of officials.id PKs).

    Returns None if none of the picked refs have history, else {
      crew:      [{off_pk,name,games,fp100,ha_diff}],
      crew_fp100, lg_fp100, whistle ('tight'/'lenient'/'average'),
      lean_pct, lean ('home'/'away'/'even'),
      crew_ppp, lg_ppp, scoring ('high'/'low'/'average'),
      q4_share, games, confident, tags:[str], summary:str }."""
    if overview is None:
        overview = OFF.official_overview(gender=gender, game_ids=game_ids)
    by_pk = {r["off_pk"]: r for r in overview["officials"]}
    crew = [by_pk[p] for p in official_pks if p in by_pk]
    if not crew:
        return None

    allr = [r for r in overview["officials"] if r["games"] >= 1]
    lg_fp100 = mean([_fp100(r) for r in allr]) if allr else 0.0
    _ppp_pool = [r["PPP"] for r in allr if r.get("game_poss")]
    lg_ppp = mean(_ppp_pool) if _ppp_pool else 0.0

    crew_fp100 = mean([_fp100(r) for r in crew])
    _cppp = [r["PPP"] for r in crew if r.get("game_poss")]
    crew_ppp = mean(_cppp) if _cppp else 0.0
    home_f = sum(r["home_fouls"] for r in crew)
    away_f = sum(r["away_fouls"] for r in crew)
    ha_tot = home_f + away_f
    lean_pct = ((home_f - away_f) / ha_tot * 100.0) if ha_tot else 0.0
    q4 = sum(r["q4"] for r in crew)
    ftot = sum(r["fouls"] for r in crew)
    q4_share = (q4 / ftot * 100.0) if ftot else 0.0
    games = sum(r["games"] for r in crew)

    whistle = ("tight" if lg_fp100 and crew_fp100 >= lg_fp100 * 1.10
               else "lenient" if lg_fp100 and crew_fp100 <= lg_fp100 * 0.90
               else "average")
    lean = ("home" if (ha_tot >= MIN_LEAN_FOULS and lean_pct >= 15) else
            "away" if (ha_tot >= MIN_LEAN_FOULS and lean_pct <= -15) else "even")
    scoring = ("high" if lg_ppp and crew_ppp >= lg_ppp * 1.05
               else "low" if lg_ppp and crew_ppp <= lg_ppp * 0.95 else "average")

    tags = [f"{whistle} whistle ({crew_fp100:.1f} FP100 vs {lg_fp100:.1f} lg)"]
    if lean != "even":
        tags.append(f"{lean}-leaning ({lean_pct:+.0f}%)")
    if scoring != "average":
        tags.append(f"{scoring}-scoring env ({crew_ppp:.2f} PPP)")
    if q4_share >= 32:
        tags.append(f"calls it late ({q4_share:.0f}% of fouls in Q4)")

    _w = {"tight": "Expect a tightly-called game — value the ball, no cheap reach-ins, "
                   "and your bigs are at foul risk early.",
          "lenient": "A let-them-play crew — physical defense goes uncalled, so attack "
                     "the rim and don't wait on whistles.",
          "average": "An average whistle — no strong adjustment needed."}[whistle]
    _l = ("" if lean == "even"
          else f" Slight {lean}-team foul lean, so "
               + ("the road crowd won't help you at the line."
                  if lean == "home" else "you may get the benefit at home."))
    summary = _w + _l
    if not (games >= CONFIDENT_GAMES):
        summary = "Low-confidence (thin crew history). " + summary

    return {
        "crew": [{"off_pk": r["off_pk"], "name": r["name"], "games": r["games"],
                  "fp100": round(_fp100(r), 1), "ha_diff": r["ha_diff"]} for r in crew],
        "crew_fp100": round(crew_fp100, 1), "lg_fp100": round(lg_fp100, 1),
        "whistle": whistle, "lean_pct": round(lean_pct, 0), "lean": lean,
        "crew_ppp": round(crew_ppp, 3), "lg_ppp": round(lg_ppp, 3), "scoring": scoring,
        "q4_share": round(q4_share, 0), "games": games,
        "confident": games >= CONFIDENT_GAMES, "tags": tags, "summary": summary,
    }
