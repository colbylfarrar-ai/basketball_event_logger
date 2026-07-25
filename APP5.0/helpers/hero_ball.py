"""
hero_ball.py — system offence or one player? (spec Part 5j)

A Gini coefficient over how a team's scoring and playmaking are distributed:
0 = every player contributes identically, 1 = one player does everything. The
soccer-analytics steal, and a one-number answer to a question coaches phrase as
"are we playing together or are we watching her?"

THE CONFOUND THAT MAKES THE NAIVE VERSION USELESS
-------------------------------------------------
Gini over raw point totals is mostly a ROTATION-DEPTH stat. A starter plays 30
minutes and a reserve plays 4, so of course the points are concentrated — a
team that plays seven and a team that plays eleven will differ on raw Gini even
if both share the ball identically while on the floor. Measured on the live
book, raw scoring Gini and minutes Gini correlate strongly enough that the raw
number is very nearly the rotation depth wearing a different name.

So the headline is a WEIGHTED Gini over per-floor-time scoring RATES, with each
player weighted by their floor time. That asks the question a coach means: given
who was out there, was the scoring spread among them? A short rotation of five
equal scorers reads LOW (a system), and a deep rotation where one player takes
everything reads HIGH (hero ball) — which is the correct way round, and the
opposite of what raw Gini does.

Raw Gini is still returned, clearly named `raw_gini`, because it is the number
other places quote and hiding it would just invite someone to recompute it
wrongly.

READING THE NUMBER
------------------
An absolute Gini means little without a pool — the 07-24 run's repeated lesson
is that an absolute cutoff on a compressed distribution flags everybody or
nobody. `league_context` therefore returns the team's percentile against every
other tracked team in the gender pool, and the verdict speaks in those terms.

NOT A JUDGEMENT. High concentration is not a flaw. A team with one genuinely
elite scorer SHOULD funnel; the useful reading is whether the concentration
matches the roster, and whether it changes when it needs to. Nothing here
should be phrased as "stop doing this".

Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S
from helpers.lineups import _event_floor

#: A player needs this much floor time before her rate enters the Gini, or a
#: two-minute cameo with one basket swings the whole team's number.
MIN_FLOOR_EVENTS = 60

#: And the team needs this many contributing players for a Gini to mean
#: anything. Below it the coefficient is dominated by who happened to play.
MIN_PLAYERS = 5

#: Games a team needs before it enters the LEAGUE pool. Most opponents appear in
#: the book only because a tracked team played them: measured on the live book,
#: 12 of 21 teams have exactly ONE tracked game, and a one-game Gini is a
#: description of one night. Without this gate those teams set the percentile
#: everyone else is judged against.
MIN_POOL_GAMES = 3

#: Below this many teams in the pool, a percentile is not worth quoting and the
#: verdict falls back to the bare coefficient.
MIN_POOL_TEAMS = 5


def gini(values, weights=None):
    """Weighted Gini coefficient of a non-negative distribution.

    `weights` lets each value carry its sample size — for scoring RATES the
    weight is floor time, so a 30-minute player's rate counts more toward the
    team's concentration than a 6-minute player's. Unweighted (weights=None) is
    the textbook coefficient over the values themselves.

    Returns None when there is nothing to measure (no values, all zero, or a
    single contributor — one player is not a distribution).
    """
    pairs = [(float(v), float(w) if weights else 1.0)
             for v, w in zip(values, weights or [1.0] * len(values))
             if v is not None and v >= 0 and (not weights or w > 0)]
    if len(pairs) < 2:
        return None
    total_w = sum(w for _v, w in pairs)
    total_v = sum(v * w for v, w in pairs)
    if total_w <= 0 or total_v <= 0:
        return None
    pairs.sort(key=lambda p: p[0])
    # weighted Gini via the cumulative-share formulation
    cum_w = 0.0
    cum_v = 0.0
    area = 0.0
    for v, w in pairs:
        prev_w, prev_v = cum_w, cum_v
        cum_w += w
        cum_v += v * w
        area += (cum_w - prev_w) * (cum_v + prev_v) / 2.0
    perfect = total_w * total_v / 2.0
    return max(0.0, min(1.0, (perfect - area) / perfect)) if perfect else None


def team_shares(game_ids=None, events=None, floor=None, team_id=None):
    """{pid: {pts, ast, floor_events, pts_rate, ast_rate}} for one team.

    Rates are per on-floor event, which is the same denominator involvement.py
    uses and the reason the Gini below is not a rotation-depth stat.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if floor is None:
        floor = _event_floor(game_ids)

    agg = defaultdict(lambda: {"pts": 0, "ast": 0, "floor_events": 0})
    games = set()
    for e in events:
        for tid, five in (floor.get(e["id"]) or {}).items():
            if team_id is not None and tid != team_id:
                continue
            if e.get("game_id") is not None:
                games.add(e["game_id"])
            for p in five:
                agg[p]["floor_events"] += 1
        if e["shot_result"] != "make":
            continue
        tid = e.get("shooter_team_id")
        if team_id is not None and tid != team_id:
            continue
        scorer = e.get("primary_player_id")
        if scorer is None:
            continue
        if e["event_type"] == "free_throw":
            agg[scorer]["pts"] += 1
        elif e["event_type"] == "shot":
            agg[scorer]["pts"] += 3 if e["shot_type"] == 3 else 2
            passer = e.get("pass_from_id")
            if passer is not None:
                agg[passer]["ast"] += 1

    out = {}
    for pid, a in agg.items():
        fe = a["floor_events"]
        if not fe:
            continue
        out[pid] = {**a,
                    "pts_rate": a["pts"] / fe,
                    "ast_rate": a["ast"] / fe,
                    "games": len(games)}
    return out


def team_concentration(game_ids=None, events=None, floor=None, team_id=None,
                       shares=None):
    """{scoring_gini, assist_gini, raw_gini, raw_assist_gini, minutes_gini,
    players, floor_events} for one team.

    `scoring_gini` is the headline: weighted over per-floor-time rates.
    `raw_gini` is the naive coefficient over point TOTALS, kept for comparison.
    `minutes_gini` is the rotation-depth number the raw version is mostly
    measuring — printing the two beside each other is what makes the point.
    """
    if shares is None:
        shares = team_shares(game_ids=game_ids, events=events, floor=floor,
                             team_id=team_id)
    elig = {p: s for p, s in shares.items()
            if s["floor_events"] >= MIN_FLOOR_EVENTS}
    n_games = max((s.get("games") or 0) for s in shares.values()) if shares else 0
    if len(elig) < MIN_PLAYERS:
        return {"scoring_gini": None, "assist_gini": None, "raw_gini": None,
                "raw_assist_gini": None, "minutes_gini": None,
                "players": len(elig), "floor_events": 0, "games": n_games}
    rates = [s["pts_rate"] for s in elig.values()]
    arates = [s["ast_rate"] for s in elig.values()]
    wts = [s["floor_events"] for s in elig.values()]
    return {
        "scoring_gini": gini(rates, wts),
        "assist_gini": gini(arates, wts),
        "raw_gini": gini([s["pts"] for s in elig.values()]),
        "raw_assist_gini": gini([s["ast"] for s in elig.values()]),
        "minutes_gini": gini(wts),
        "players": len(elig),
        "floor_events": sum(wts),
        "games": n_games,
    }


def league_context(gender=None, season="Current", game_ids=None, events=None,
                   floor=None):
    """{team_id: concentration} for every tracked team, plus each team's
    percentile within the pool under the key `pct`.

    An absolute Gini is unreadable without this. 0.42 is meaningless on its own;
    "more concentrated than 80% of the league" is a sentence.
    """
    import helpers.seasons as SEAS
    if game_ids is None:
        game_ids = sorted(SEAS.game_pool(season, gender=gender,
                                         tracked_only=True))
    if not game_ids:
        return {}
    if events is None:
        events = S.fetch_events(game_ids)
    if floor is None:
        floor = _event_floor(game_ids)

    teams = set()
    for e in events:
        for tid in (floor.get(e["id"]) or {}):
            teams.add(tid)

    out = {}
    for tid in teams:
        c = team_concentration(events=events, floor=floor, team_id=tid)
        if c["scoring_gini"] is not None:
            out[tid] = c

    # Percentiles are computed against the DEEP teams only. Most opponents are
    # in this book for a single game, and a one-game Gini describes one night;
    # letting those set the scale would make every real team's percentile a
    # comparison against noise. Shallow teams keep their coefficient and get
    # `pct = None`, which the verdict reads as "no league context".
    pool = sorted(c["scoring_gini"] for c in out.values()
                  if (c.get("games") or 0) >= MIN_POOL_GAMES)
    for c in out.values():
        c["pool_n"] = len(pool)
        if len(pool) < MIN_POOL_TEAMS or (c.get("games") or 0) < MIN_POOL_GAMES:
            c["pct"] = None
            continue
        below = sum(1 for v in pool if v < c["scoring_gini"])
        ties = sum(1 for v in pool if v == c["scoring_gini"])
        c["pct"] = round(100.0 * (below + 0.5 * ties) / len(pool), 1)
    return out


def hero_ball_verdict(conc, pool_pct=None, names=None, top_scorer=None):
    """[(badge, n, html)] for helpers.cards.verdict_card.

    Speaks in POOL terms, never in absolute Gini, and never tells a coach the
    concentration is wrong — a team with one elite scorer should funnel.
    """
    if not conc or conc.get("scoring_gini") is None:
        return []
    g = conc["scoring_gini"]
    lines = []
    if pool_pct is None:
        lines.append((
            "Ball share", conc["players"],
            f"Scoring concentration <b>{g:.2f}</b> across "
            f"{conc['players']} rotation players (0 = perfectly even, "
            f"1 = one player scores everything)."))
    else:
        if pool_pct >= 75:
            word, tail = ("concentrated",
                          "the offence runs through a short list")
        elif pool_pct <= 25:
            word, tail = ("spread", "scoring comes from everywhere")
        else:
            word, tail = ("balanced", "a fairly typical share for this league")
        lines.append((
            "Ball share", conc["players"],
            f"Scoring is <b>{word}</b> — more concentrated than "
            f"<b>{pool_pct:.0f}%</b> of tracked teams ({tail}). Gini "
            f"<b>{g:.2f}</b> over per-minute scoring rates."))

    a = conc.get("assist_gini")
    if a is not None:
        if a > g + 0.08:
            lines.append((
                "Creation", conc["players"],
                f"Creation is tighter than scoring (assist Gini "
                f"<b>{a:.2f}</b> vs <b>{g:.2f}</b>) — plenty of players "
                f"finish, but the passes come from a narrow group."))
        elif g > a + 0.08:
            lines.append((
                "Creation", conc["players"],
                f"Creation is wider than scoring (assist Gini "
                f"<b>{a:.2f}</b> vs <b>{g:.2f}</b>) — the whole roster sets "
                f"up the baskets, a smaller group finishes them."))

    raw, mins = conc.get("raw_gini"), conc.get("minutes_gini")
    if raw is not None and mins is not None and raw - g > 0.1:
        lines.append((
            "Why not the raw number", conc["players"],
            f"Raw point-total Gini is <b>{raw:.2f}</b>, but minutes alone are "
            f"already <b>{mins:.2f}</b> concentrated — most of that gap is "
            f"rotation depth, not ball-sharing. The read above divides it out."))
    return lines
