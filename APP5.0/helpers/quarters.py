"""
quarters.py — the quarter splits as VERDICTS, not as charts.

Charts → Quarters already carries four sub-tabs of per-quarter splits, and it
keeps them: this is not a replacement. It is the sentence a coach would say out
loud about the same numbers, because Insights is a prose surface and had zero
quarter reads in it — the largest content gap on that view.

Reads `team_analytics.quarter_boxes`, which returns totals per quarter plus the
per-quarter `n_games` (every game has Q1–Q4; only some reach overtime, which is
exactly why that count is per quarter and not per book).

Three rules, and the third is the one that matters:

  * gate on the sample, per quarter;
  * regulation only for best/worst — an OT "worst quarter" drawn from two games
    is a coin flip wearing a verdict's clothes;
  * say nothing when nothing moved. A team whose quarters are level is a real
    finding, and an invented tendency is worse than silence.

Streamlit-free (the engine mirror of stops.py / winning_formula.py). Display:
the Insights team-read block.
"""
from __future__ import annotations

MIN_GAMES = 3          # a quarter needs a real book behind it
MIN_NET = 2.0          # points/game off level before a quarter is worth a line
MIN_HALF_GAP = 4.0     # points/game between the halves before that is a read

# ── the PACE read (THE BOOK §13.2) ───────────────────────────────────────────
# Of the five quarter reads §13.2 named, this is the one that survived being
# measured. See `reliability.THE QUARTER AXIS` for the study; the short version
# is that a team's per-quarter POSSESSION deviation repeats at SB .596 while
# its per-quarter eFG deviation repeats at SB -.135 and its turnover deviation
# at SB +.082. Tempo is a choice a team makes every night; shooting and ball
# security in a single quarter are the sample talking.
#
# Both gates, per Q6, because they fail in opposite directions. The t-stat is
# charged with the team's OWN game-to-game spread, so a 2-game book cannot
# reach it — that is the §"thin books inflate a plain z" fix in its paired
# form. The effect floor is what stops the opposite failure: once a book is
# long enough, t >= 2 will certify a half-possession wobble that no coach can
# act on, and the number would be true and useless.
MIN_PACE_T = 2.0       # paired t of the quarter's deviation across games
MIN_PACE_POSS = 1.0    # possessions/game off the team's own other quarters

QUARTER_NAMES = {1: "1st quarter", 2: "2nd quarter",
                 3: "3rd quarter", 4: "4th quarter"}


def _net_per_game(cell):
    """This team's scoring margin per game in one quarter, or None."""
    n = (cell or {}).get("n_games") or 0
    if n <= 0:
        return None
    for_pts = ((cell.get("team") or {}).get("PTS") or 0)
    against = ((cell.get("opp") or {}).get("PTS") or 0)
    return (for_pts - against) / n


def _regulation(qbx):
    """{q: (net/game, games)} for Q1–Q4 with a real sample. OT is dropped."""
    out = {}
    for q in (1, 2, 3, 4):
        cell = (qbx or {}).get(q)
        if not cell:
            continue
        n = cell.get("n_games") or 0
        net = _net_per_game(cell)
        if net is None or n < MIN_GAMES:
            continue
        out[q] = (net, n)
    return out


def quarter_verdict(qbx, min_net=MIN_NET):
    """The quarter story as ready-to-render prose, strongest read first.

    Returns [{text, cut, n, delta}] — the house verdict-line shape. `cut` is
    "quarter" for a single period and "half" for the halves disagreeing.

    An empty list means the quarters are level, which is an answer rather than a
    gap; the renderer says so in its own words.
    """
    reg = _regulation(qbx)
    if not reg:
        return []

    lines = []

    best_q = max(reg, key=lambda q: reg[q][0])
    worst_q = min(reg, key=lambda q: reg[q][0])
    for q, kind in ((best_q, "best"), (worst_q, "worst")):
        net, n = reg[q]
        if abs(net) < min_net or (kind == "best" and net <= 0) \
                or (kind == "worst" and net >= 0):
            continue
        name = QUARTER_NAMES[q]
        if kind == "best":
            txt = (f"**{name}** is where the game is won — **{net:+.1f} "
                   f"points a game** across {n} tracked games.")
        else:
            txt = (f"**{name}** is where it leaks — **{net:+.1f} points a "
                   f"game** across {n} tracked games.")
            if q == 3:
                # The out-of-the-locker-room quarter. A coach can act on this
                # one the same week, which is why it earns the extra clause.
                txt += " That is the quarter out of halftime."
        lines.append({"text": txt, "cut": "quarter", "n": n, "delta": net})

    # The halves. Reported separately because two quarters can each sit under
    # the per-quarter bar while the halves still disagree loudly.
    h1 = [reg[q] for q in (1, 2) if q in reg]
    h2 = [reg[q] for q in (3, 4) if q in reg]
    if h1 and h2:
        n1, n2 = sum(x[0] for x in h1), sum(x[0] for x in h2)
        gap = n1 - n2
        if abs(gap) >= MIN_HALF_GAP:
            games = min(min(x[1] for x in h1), min(x[1] for x in h2))
            better, worse = ("first", "second") if gap > 0 else ("second", "first")
            txt = (f"**The {better} half is the better team** — "
                   f"**{n1:+.1f}** a game before the break against "
                   f"**{n2:+.1f}** after, a **{abs(gap):.1f}-point** swing "
                   f"toward the {better}. Whatever changes at halftime is "
                   f"costing the {worse} half.")
            lines.append({"text": txt, "cut": "half", "n": games,
                          "delta": gap})

    lines.sort(key=lambda d: -abs(d.get("delta") or 0))
    return lines


def pace_verdict(by_game, min_t=MIN_PACE_T, min_poss=MIN_PACE_POSS):
    """Which quarter this team plays FASTER or SLOWER than its own others.

    Takes `team_analytics.quarter_boxes_by_game` — {game_id: {q: {...'poss'}}}
    — not the pooled `quarter_boxes`, and the per-game shape is the whole
    point. Pooling four quarters into four numbers throws away the only thing
    that says whether a 2-possession gap is a habit or one loose night, and a
    pooled gate fires hardest for the teams with the fewest games.

    Returns the house verdict-line shape, [{text, cut, n, delta}] with
    `cut="pace"`, strongest first. An empty list means this team plays its four
    quarters at one speed, which is an answer.
    """
    per = {q: [] for q in (1, 2, 3, 4)}
    for qd in (by_game or {}).values():
        if not all(q in qd for q in (1, 2, 3, 4)):
            continue                       # a game that did not finish four
        for q in (1, 2, 3, 4):
            per[q].append((qd[q] or {}).get("poss") or 0)
    games = len(per[1])
    if games < MIN_GAMES:
        return []

    lines = []
    for q in (1, 2, 3, 4):
        # paired: each game contributes this quarter MINUS that same game's
        # other three, so an opponent who plays fast cancels out of both sides.
        diffs = [per[q][i] - sum(per[x][i] for x in (1, 2, 3, 4) if x != q) / 3.0
                 for i in range(games)]
        mean = sum(diffs) / games
        var = sum((d - mean) ** 2 for d in diffs) / (games - 1)
        sd = var ** 0.5
        # Zero spread is the STRONGEST version of this read, not the absence of
        # one: the same gap in every game is a habit with no counter-example.
        # Guarding `sd < 1e-9` as "nothing to test" silenced exactly the teams
        # the read is for, so an unvarying gap gets an infinite t and is left
        # to the effect floor below. A zero gap with zero spread is still
        # nothing, and falls out on `abs(mean) < min_poss`.
        t = (mean / (sd / games ** 0.5)) if sd > 1e-9 else \
            (float("inf") if mean > 0 else float("-inf") if mean < 0 else 0.0)
        if abs(t) < min_t or abs(mean) < min_poss:
            continue
        name = QUARTER_NAMES[q]
        if mean > 0:
            txt = (f"**They push the {name}** — **{mean:+.1f} possessions a "
                   f"game** more than their own other quarters, across "
                   f"{games} tracked games. The tempo is a choice, and this is "
                   f"where they make it.")
        else:
            txt = (f"**The {name} slows down** — **{mean:+.1f} possessions a "
                   f"game** against their own other quarters, across {games} "
                   f"tracked games. Fewer trips is fewer chances to close a "
                   f"gap.")
        lines.append({"text": txt, "cut": "pace", "n": games, "delta": mean,
                      "t": t})

    lines.sort(key=lambda d: -abs(d.get("t") or 0))
    return lines


def quarter_reads(qbx, by_game=None):
    """Every quarter verdict this book supports: the scoring-margin lines from
    `quarter_verdict` plus, when the per-game boxes are supplied, the pace
    lines. One call so a surface cannot pick up half of the axis.
    """
    lines = list(quarter_verdict(qbx))
    if by_game:
        lines += pace_verdict(by_game)
    return lines
