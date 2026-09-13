"""measure_garbage.py — how much does garbage time actually move the numbers?

READ-ONLY. IT CHANGES NO CONSTANT AND NO ENGINE. That is the whole design.

WHY THIS EXISTS

Cleaning the Glass's entire pitch is exclusion discipline, and a CTG reader will
ask "do you strip garbage time?" inside the first hour. Today the answer is a
shrug with two constants in it:

    helpers/situational.py:535   GARBAGE = 15          a scoring SPLIT
    helpers/runs.py:37           GARBAGE_MARGIN = 20   a 4th-quarter run FILTER

`runs.py` genuinely excludes. `situational.py` only splits — it reports the
share of a player's points scored while the game was decided, and excludes
nothing. **Nothing else in the app excludes anything**: team ratings, player
ratings, RAPM, lineups, shot quality, the player-edge boards and OVERALL are all
computed over every possession including a 29-point fourth quarter.

That gap was graded on DIRECTION and never on MAGNITUDE. Nobody has measured
how much it moves, and a threshold nobody has priced is not a decision — it is
a default. This prices it. Publishing what we found and what we currently do is
a complete and honest answer to the question, and it costs nothing in risk,
which is the point: three weeks before handing the app to five analysts is the
wrong moment to move every headline rating.

THE THREE DEFINITIONS MEASURED, AND WHY THE THIRD IS THERE

    flat15   |margin| >= 15, any quarter   (situational.GARBAGE)
    q4_20    |margin| >= 20 AND Q4         (runs.GARBAGE_MARGIN)
    wp47     |win probability - 0.5| > 0.47

The first two are blind to the clock, and a clock-blind margin rule is wrong in
both directions at once: 16 points down with nine minutes left is a live game
that flat15 discards, and 12 points down with forty seconds left is over and
flat15 keeps it. The win-probability cut knows the clock, which is why CTG-style
exclusion is usually expressed that way, so it is measured beside the other two
rather than argued about.

WHAT IT REPORTS

  * the share of tracked possessions each definition would exclude
  * ORtg / DRtg / NetRtg per team, with and without, and the deltas
  * OVERALL per player, with and without, and the biggest mover
  * whether the win-probability cut behaves differently from a flat margin

HOW THE PLAYER HALF IS MEASURED, AND ITS ONE HOLE

Team ratings are recomputed honestly: `stats.aggregate_player_boxes` takes an
`events` list, so the filtered and unfiltered runs use the IDENTICAL estimator
over two event sets. Nothing is approximated there.

`player_ratings.player_stat_table` takes no `events` seam, so the player half
reaches it by temporarily rebinding `stats.fetch_events` — measurement-only,
inside this tool, never shipped. One leaf escapes that rebinding and it is named
here rather than buried: `stats.py:1944` counts a player's floor share with its
own `SELECT COUNT(DISTINCT ge.id) FROM game_events`, so on-court share stays
computed over ALL events in both runs. The OVERALL deltas below are therefore a
LOWER bound on the movement, not an upper one.

Run:
    PYTHONIOENCODING=utf-8 \
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tools/measure_garbage.py
    ... --dir C:/Users/colby/app5_prod --gender F --season 2025-2026
"""
from __future__ import annotations

import argparse
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

# The three cuts, by name. The two margin values are READ from the modules that
# own them rather than retyped, so this tool cannot drift from the thresholds it
# is pricing.
WP_CUT = 0.47


def _classify(events):
    """Tag every event with the game state BEFORE it: (margin, secs_remaining).

    Replays each game's scoring in clock order against a reference team — the
    first scorer seen, exactly as `situational.player_margin_scoring` does.
    |margin| is perspective-invariant, so which side the replay anchors to does
    not change any of the three cuts.
    """
    import helpers.situational as SIT

    by_game = {}
    for e in events:
        by_game.setdefault(e.get("game_id"), []).append(e)

    tagged = []
    for gid, evs in by_game.items():
        evs = sorted(evs, key=lambda e: (SIT._elapsed(e), e.get("id") or 0))
        total = max((SIT._elapsed(e) for e in evs), default=0) or 1920.0
        margin, ref = 0, None
        for e in evs:
            el = SIT._elapsed(e)
            # The state BEFORE the event is what decides whether the possession
            # was played in garbage time. Tagging after it would let the shot
            # that CREATED a 15-point lead be the first one excluded.
            tagged.append((e, margin, max(total - el, 0.0), total))
            pts, scorer = SIT._event_points(e)
            if pts and scorer is not None:
                if ref is None:
                    ref = scorer
                margin += pts if scorer == ref else -pts
    return tagged


def _is_possession(e):
    """FGA + TOV — the app's exact possession count (`estimate_possessions`)."""
    et = (e.get("event_type") or "").lower()
    return et in ("shot", "turnover")


def _cuts(tagged):
    """{name: set(event ids to EXCLUDE)} for each definition."""
    import helpers.situational as SIT
    import helpers.runs as RN
    from helpers.win_probability import win_prob

    flat, q4, wp = set(), set(), set()
    for e, margin, left, total in tagged:
        eid = e.get("id")
        if eid is None:
            continue
        if abs(margin) >= SIT.GARBAGE:
            flat.add(eid)
        if abs(margin) >= RN.GARBAGE_MARGIN and int(e.get("quarter") or 1) >= 4:
            q4.add(eid)
        if abs(win_prob(margin, left, total) - 0.5) > WP_CUT:
            wp.add(eid)
    return {f"flat{SIT.GARBAGE}": flat,
            f"q4_{RN.GARBAGE_MARGIN}": q4,
            f"wp{int(WP_CUT * 100)}": wp}


#: Offensive possessions a team needs IN THE TRACKED SET before its ORtg is
#: reported here. Without it the table is dominated by teams that appear in one
#: tracked game as somebody else's opponent — where only the tracking side's
#: events are fully logged, so the "rating" is a fragment of a box score. Those
#: rows produce ORtg swings of 50 points on a handful of possessions and would
#: set the headline mean, which is the `thin-books-inflate-plain-z` failure in a
#: new costume. 200 is roughly three games of one team's offense.
MIN_POSS = 200


def _team_ratings_from(events, team_ids):
    """{team_id: (ORtg, DRtg, Net)} computed from an events list.

    The SAME estimator the app ships (`aggregate_player_boxes` →
    `estimate_possessions` → 100*PTS/POSS), so the with/without comparison is
    two event sets through one function rather than two functions.
    """
    import helpers.stats as S
    from database.db import query

    boxes = S.aggregate_player_boxes(None, events=events)
    team_of = {r["id"]: r["team_id"] for r in query(
        "SELECT id, team_id FROM players")}
    per = {}
    for pid, b in boxes.items():
        t = team_of.get(pid)
        if t is None:
            continue
        acc = per.setdefault(t, {"PTS": 0, "FGA": 0, "TOV": 0})
        for k in acc:
            acc[k] += b.get(k, 0) or 0

    # The defensive side is "everyone this team's games were played against",
    # summed over the same filtered events — the opp_id=None convention in
    # stats.team_ratings.
    out = {}
    for t in team_ids:
        mine = per.get(t)
        if not mine:
            continue
        opp = {"PTS": 0, "FGA": 0, "TOV": 0}
        # Opponents only in games this team actually played in the filtered set.
        gids = {e["game_id"] for e in events
                if team_of.get(e.get("primary_player_id")) == t}
        sub = [e for e in events if e.get("game_id") in gids]
        ob = S.aggregate_player_boxes(None, events=sub)
        for pid, b in ob.items():
            if team_of.get(pid) == t or team_of.get(pid) is None:
                continue
            for k in opp:
                opp[k] += b.get(k, 0) or 0
        op, dp = mine["FGA"] + mine["TOV"], opp["FGA"] + opp["TOV"]
        if not op or not dp:
            continue
        o, d = 100.0 * mine["PTS"] / op, 100.0 * opp["PTS"] / dp
        out[t] = (o, d, o - d, op)
    return out


def _overall_from(gids, gender, season, drop_ids):
    """{pid: OVERALL} with `drop_ids` removed, via the fetch_events rebinding
    described in the module docstring. `drop_ids` empty = the shipped numbers."""
    import helpers.stats as S
    import helpers.player_ratings as PR

    orig = S.fetch_events
    if drop_ids:
        def patched(game_ids=None):
            return [e for e in orig(game_ids) if e.get("id") not in drop_ids]
        S.fetch_events = patched
        PR.S.fetch_events = patched          # PR holds its own module ref
    try:
        tbl = PR.player_stat_table(game_ids=set(gids), gender=gender,
                                   min_games=1, season=season)
    finally:
        S.fetch_events = orig
        PR.S.fetch_events = orig
    return {pid: r.get("OVERALL") for pid, r in tbl.items()
            if r.get("OVERALL") is not None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("APP5_DATA_DIR")
                    or os.path.expanduser("~/app5_prod"))
    ap.add_argument("--gender", default="F")
    ap.add_argument("--season", default="2025-2026")
    ap.add_argument("--skip-players", action="store_true",
                    help="team half only (the player half is the slow one)")
    args = ap.parse_args()

    book = os.path.join(os.path.expanduser(args.dir), "analytics.db")
    if not os.path.exists(book):
        print(f"NO BOOK at {book}", file=sys.stderr)
        return 2
    os.environ["APP5_DATA_DIR"] = os.path.expanduser(args.dir)

    from database.db import query
    import helpers.stats as S
    import helpers.situational as SIT
    import helpers.runs as RN

    gids = [r["id"] for r in query(
        "SELECT g.id FROM games g JOIN teams t ON t.id = g.team1_id "
        "WHERE g.tracked=1 AND g.season=? AND t.gender=?",
        (args.season, args.gender))]
    print(f"book: {book}")
    print(f"pool: {len(gids)} tracked {args.gender} games in {args.season}")
    print(f"constants read live: situational.GARBAGE={SIT.GARBAGE}  "
          f"runs.GARBAGE_MARGIN={RN.GARBAGE_MARGIN}  wp cut=+/-{WP_CUT}\n")
    if not gids:
        return 1

    events = S.fetch_events(set(gids))
    tagged = _classify(events)
    cuts = _cuts(tagged)

    poss = [e for e in events if _is_possession(e)]
    n_poss = len(poss)
    print("── 1 · how much would each definition exclude ─────────────────────")
    print(f"  {'definition':<12} {'possessions cut':>16} {'share':>8} "
          f"{'events cut':>11}")
    for name, drop in cuts.items():
        cut_p = sum(1 for e in poss if e.get("id") in drop)
        print(f"  {name:<12} {cut_p:16d} {100.0 * cut_p / n_poss:7.1f}% "
              f"{len(drop):11d}")
    print(f"  {'(total)':<12} {n_poss:16d} {100.0:7.1f}%\n")

    # Overlap: do the flat cut and the clock-aware cut name the same plays?
    flat = cuts[f"flat{SIT.GARBAGE}"]
    wp = cuts[f"wp{int(WP_CUT * 100)}"]
    both = flat & wp
    print("── 2 · does the clock-aware cut behave differently? ───────────────")
    print(f"  flat{SIT.GARBAGE} only : {len(flat - wp):5d} events   "
          f"(live games a margin rule throws away)")
    print(f"  wp{int(WP_CUT * 100)} only     : {len(wp - flat):5d} events   "
          f"(decided games a margin rule keeps)")
    print(f"  both        : {len(both):5d} events")
    if flat or wp:
        j = len(both) / max(len(flat | wp), 1)
        print(f"  agreement (Jaccard): {j:.2f} — 1.00 would mean the clock "
              f"adds nothing\n")

    teams = sorted({r["team1_id"] for r in query(
        f"SELECT team1_id FROM games WHERE id IN "
        f"({','.join('?' * len(gids))})", tuple(gids))} |
        {r["team2_id"] for r in query(
            f"SELECT team2_id FROM games WHERE id IN "
            f"({','.join('?' * len(gids))})", tuple(gids))})
    names = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}

    base = _team_ratings_from(events, teams)
    qual = {t for t, v in base.items() if v[3] >= MIN_POSS}
    print("── 3 · how far do team ratings move? ──────────────────────────────")
    print(f"  {len(qual)} of {len(base)} teams clear the {MIN_POSS}-possession "
          f"floor. The rest appear in one or two tracked games as somebody "
          f"else's opponent, where only the tracking side is fully logged.")
    for name, drop in cuts.items():
        kept = [e for e in events if e.get("id") not in drop]
        alt = _team_ratings_from(kept, teams)
        rows = []
        for t, (o, d, n, op) in base.items():
            if t not in alt or t not in qual:
                continue
            ao, ad, an, _ = alt[t]
            rows.append((abs(an - n), t, o, ao, d, ad, n, an, op))
        if not rows:
            continue
        rows.sort(reverse=True)
        mean = sum(r[0] for r in rows) / len(rows)
        med = sorted(r[0] for r in rows)[len(rows) // 2]
        print(f"\n  [{name}]  |ΔNetRtg| mean {mean:.2f} · median {med:.2f} "
              f"pts/100 over {len(rows)} qualifying teams:")
        print(f"    {'team':<26} {'poss':>5} {'ORtg':>14} {'DRtg':>14} "
              f"{'Net':>15}")
        for d_, t, o, ao, dd, ad, n, an, op in rows:
            print(f"    {names.get(t, t)[:25]:<26} {op:5d} "
                  f"{o:6.1f}->{ao:6.1f} {dd:6.1f}->{ad:6.1f} "
                  f"{n:+6.1f}->{an:+6.1f}")

    if args.skip_players:
        print("\n(player half skipped)")
        return 0

    print("\n── 4 · how far does OVERALL move? ─────────────────────────────────")
    print("  (lower bound — floor share escapes the rebinding, see docstring)")
    shipped = _overall_from(gids, args.gender, args.season, set())
    for name, drop in cuts.items():
        alt = _overall_from(gids, args.gender, args.season, drop)
        deltas = [(abs(alt[p] - shipped[p]), p, shipped[p], alt[p])
                  for p in shipped if p in alt]
        if not deltas:
            continue
        deltas.sort(reverse=True)
        mean = sum(d[0] for d in deltas) / len(deltas)
        pnames = {r["id"]: r["name"] for r in query(
            "SELECT id, name FROM players")}
        print(f"\n  [{name}]  mean |ΔOVERALL| = {mean:.2f} over "
              f"{len(deltas)} players · dropped {len(shipped) - len(alt)} "
              f"below the games floor · biggest movers:")
        for d_, p, was, now in deltas[:5]:
            print(f"    {pnames.get(p, p)[:27]:<28} {was:5.1f} -> {now:5.1f} "
                  f"({now - was:+.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
