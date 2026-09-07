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
