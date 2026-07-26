"""
foul_trouble.py — what foul trouble actually costs (spec Part 4i).

Coaches argue about this daily and no engine in the app answers it. helpers/
fouls.py knows who commits fouls; helpers/lineups.py knows who was on the floor;
nothing joins the two, so "how much does her second foul cost us" has never been
a number here.

READ THE FOUL CONVENTION BEFORE TOUCHING THIS
---------------------------------------------
On a `foul` row, `primary_player_id` is the player who was FOULED and
`secondary_player_id` is the FOULER (fouls.py:5). Getting this backwards is not
a subtle error — counting primary produced player-games with 10 and 11 fouls on
the live book, which is impossible under a five-foul disqualification, and would
have shipped a "foul trouble" engine measuring fouls DRAWN.

WHAT IS MEASURED, AND WHY ONLY THIS
-----------------------------------
Two different things, with very different sample quality, and the module keeps
them apart on purpose.

1. BENCH COST — the robust half. After a player commits her Nth foul, what share
   of the remaining floor time does she play, against the share she was playing
   before it? This is a ratio of counts, not a difference of noisy rates, and it
   is exactly the decision under discussion: the coach sat her, and this says
   for how long. On the live book 34% of player-games reach three fouls, so the
   sample is real.

2. NET WHILE CARRYING FOULS — the fragile half, POOLED ACROSS THE ROSTER and
   never reported per player. The 07-24/07-25 audit measured raw player on/off
   as having split-half reliability of -0.096 at 40 possessions; a single
   player's net during her own foul-trouble minutes is a far thinner slice than
   that and would be pure noise with a confident number attached. Pooling every
   rotation player's foul-trouble possessions into one team figure is the only
   version this book can support, and even that is captioned as descriptive.

WHAT IS NOT CLAIMED
-------------------
Foul trouble is not randomly assigned. Aggressive defenders foul more; players
foul more when chasing a game; a coach benches the player she can least afford
to lose. So a team playing worse with a starter in foul trouble is not evidence
the fouls caused it. The bench-cost number is a description of a COACHING
DECISION, which is the honest and still-useful thing to hand back.

Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S
from helpers.lineups import _event_floor

#: Foul counts worth reporting a bench cost for. Two is the classic first-half
#: decision, three the second-half one, four the endgame one. FIVE is absent on
#: purpose: a fifth foul is a disqualification, not a bench decision, so there
#: is no "what did sitting her cost" to compute — see CLOCK_LEVELS.
TROUBLE_LEVELS = (2, 3, 4)

#: The clock reports WHEN a foul landed and makes no causal claim, so it can
#: carry the fifth: "when does she foul out" is a real question and the answer is
#: a timestamp. Every level renders that clears the game gate.
CLOCK_LEVELS = (2, 3, 4, 5)

#: Five personals is a disqualification, so a player-game cannot hold six. The
#: prod book has two that do (game 187/player 26, game 15342/player 550, six
#: DISTINCT rows each — not duplicates and not the primary/secondary inversion,
#: which yields 10-11). Founder's call: that is a stat-keeper slip, so every
#: engine here CLAMPS the count and a sixth foul is simply the fifth. Clamping
#: rather than dropping the row keeps the disqualification timestamp, which is
#: the thing the clock is for.
MAX_PERSONALS = 5

#: A player needs this many games reaching a level before her bench cost is
#: reported at it. One game is an anecdote about one night's game state.
MIN_GAMES_AT_LEVEL = 3

#: And this many on-floor events before the level she reached is counted at all,
#: so a player who fouls out in her first minute does not read as "benched".
MIN_FLOOR_EVENTS = 40

#: The remaining window must be at least this share of the team's game, or there
#: was no bench decision to make -- a foul with a minute left cannot sit anyone.
MIN_REMAINING = 0.15

# ── the artifact this module had to be rebuilt around ────────────────────────
# The obvious comparator is the player's floor share BEFORE the Nth foul against
# her share AFTER it, in the same game. Measured on the live book that produces
# nonsense for reserves: #24 read before 32.5% / after 84.8%, and #14 read
# 27.1% / 85.5%. Neither was benched. A reserve enters late, so her Nth foul
# lands late; the "before" window spans a game she mostly watched and the
# "after" window is the short stretch she is actually playing. The in-game split
# was measuring ENTRY TIMING, and it pointed the wrong way for exactly the
# players a coach is least likely to sit.
#
# So the headline comparator is the player's own SEASON floor share -- her
# normal role -- and reporting is gated to the rotation core, pool-relative to
# the team's own median share rather than by an absolute cut (the same lesson as
# the 07-24 rebounding verdict: an absolute cutoff on a compressed distribution
# flags everybody). The in-game before/after is still returned, clearly named,
# because it is the right read for a starter and useful context; it is simply
# not what the verdict speaks from.


def _ordinal(n):
    n = int(n)
    suf = ("th" if 11 <= n % 100 <= 13
           else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))
    return f"{n}{suf}"


def season_floor_share(events, floor, team_id=None):
    """{pid: share of its team's events the player was on the floor for}.

    The role baseline every bench-cost read is measured against.
    """
    on = defaultdict(int)
    team_ev = defaultdict(int)
    of_team = {}
    for e in events:
        for tid, five in (floor.get(e["id"]) or {}).items():
            if team_id is not None and tid != team_id:
                continue
            team_ev[tid] += 1
            for p in five:
                on[p] += 1
                of_team[p] = tid
    return {p: (on[p] / team_ev[of_team[p]]) for p in on
            if team_ev.get(of_team.get(p))}


def _by_game(events):
    out = defaultdict(list)
    for e in events:
        if e.get("game_id") is not None:
            out[e["game_id"]].append(e)
    for gid in out:
        out[gid].sort(key=lambda r: r["id"])
    return out


def bench_cost(game_ids=None, events=None, floor=None, team_id=None,
               levels=TROUBLE_LEVELS):
    """{pid: {level: {games, before_share, after_share, drag, on_before,
    on_after, team_before, team_after}}} — floor share before vs after the Nth
    foul.

    `before_share` is the player's on-floor events divided by her TEAM's events
    in the same window, so it is a share of available floor time rather than a
    raw count: a foul in the first quarter and a foul in the fourth are then
    comparable. `drag` = before − after, in share points, and is positive when
    the coach sat her.

    Windows are per game and then summed across games, so a player benched hard
    in one game and not at all in another lands in between rather than being
    reported twice.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if floor is None:
        floor = _event_floor(game_ids)

    acc = defaultdict(lambda: defaultdict(
        lambda: {"games": 0, "on_before": 0, "on_after": 0,
                 "team_before": 0, "team_after": 0, "team_id": None}))

    for _gid, evs in _by_game(events).items():
        # index of each player's Nth foul in this game
        counts = defaultdict(int)
        nth = defaultdict(dict)          # pid -> {level: event index}
        for i, e in enumerate(evs):
            if e["event_type"] != "foul":
                continue
            f = e.get("secondary_player_id")     # THE FOULER. See module docs.
            if f is None:
                continue
            counts[f] = min(counts[f] + 1, MAX_PERSONALS)   # see MAX_PERSONALS
            if counts[f] in levels:
                nth[f][counts[f]] = i

        # per-team event index -> which of its players were on the floor
        on_at = []
        team_at = []
        for e in evs:
            sets = floor.get(e["id"]) or {}
            on_at.append(sets)
            team_at.append(set(sets))

        for pid, marks in nth.items():
            ptid = None
            for sets in on_at:
                for tid, five in sets.items():
                    if pid in five:
                        ptid = tid
                        break
                if ptid is not None:
                    break
            if ptid is None or (team_id is not None and ptid != team_id):
                continue
            for level, idx in marks.items():
                a = acc[pid][level]
                a["team_id"] = ptid
                on_b = on_a = tb = ta = 0
                for i, sets in enumerate(on_at):
                    five = sets.get(ptid)
                    if five is None:
                        continue
                    if i <= idx:
                        tb += 1
                        if pid in five:
                            on_b += 1
                    else:
                        ta += 1
                        if pid in five:
                            on_a += 1
                if on_b + on_a < MIN_FLOOR_EVENTS or not tb or not ta:
                    continue
                if ta < MIN_REMAINING * (tb + ta):
                    continue          # no game left to sit her out of
                a["games"] += 1
                a["on_before"] += on_b
                a["on_after"] += on_a
                a["team_before"] += tb
                a["team_after"] += ta

    # role baseline + the rotation gate, pool-relative to this team's own median
    season = season_floor_share(events, floor, team_id=team_id)
    med = {}
    tid_of = {pid: next(iter(lv.values()))["team_id"]
              for pid, lv in acc.items() if lv}
    # Median over the players whose team we know from the foul walk. A player
    # in `season` but never in `acc` has no team here, and lumping those under a
    # None key would pollute every real team's median.
    grouped = defaultdict(list)
    _floor_team = {}
    for e in events:
        for tid, five in (floor.get(e["id"]) or {}).items():
            for p in five:
                _floor_team[p] = tid
    for pid, sh in season.items():
        tid = tid_of.get(pid) or _floor_team.get(pid)
        if tid is None:
            continue
        grouped[tid].append(sh)
    for tid, vals in grouped.items():
        vals = sorted(vals)
        med[tid] = vals[len(vals) // 2] if vals else 0.0

    out = {}
    for pid, levels_d in acc.items():
        tid = tid_of.get(pid)
        base = season.get(pid)
        if base is None or base < med.get(tid, 0.0):
            continue                  # not a rotation regular for this team
        keep = {}
        for level, a in levels_d.items():
            if a["games"] < MIN_GAMES_AT_LEVEL:
                continue
            bs = a["on_before"] / a["team_before"] if a["team_before"] else None
            as_ = a["on_after"] / a["team_after"] if a["team_after"] else None
            if bs is None or as_ is None:
                continue
            keep[level] = {
                **a,
                "season_share": round(100.0 * base, 1),
                "before_share": round(100.0 * bs, 1),
                "after_share": round(100.0 * as_, 1),
                # HEADLINE: against her normal role, not against a before-window
                # whose length depends on when she happened to enter.
                "drag": round(100.0 * (base - as_), 1),
                # kept for context; right for a starter, timing-sensitive for
                # anyone else. See the note above _ordinal.
                "in_game_drag": round(100.0 * (bs - as_), 1),
            }
        if keep:
            out[pid] = keep
    return out


def team_foul_state_net(game_ids=None, events=None, floor=None, team_id=None,
                        level=3):
    """Pooled team scoring while ANY on-floor player carries `level`+ fouls.

    Returns {with_trouble: {events, pts_for, pts_against, per100_for,
    per100_against, net}, clean: {...}, level, poss_with, poss_clean}.

    POOLED DELIBERATELY. A single player's net across her own foul-trouble
    minutes is a far thinner slice than the raw on/off split this codebase
    already measured at split-half reliability -0.096, so it is not offered.
    Even pooled, this is descriptive: foul trouble is not randomly assigned.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if floor is None:
        floor = _event_floor(game_ids)

    agg = {"with_trouble": {"poss": 0, "pts_for": 0, "pts_against": 0},
           "clean": {"poss": 0, "pts_for": 0, "pts_against": 0}}

    for _gid, evs in _by_game(events).items():
        counts = defaultdict(int)
        for e in evs:
            sets = floor.get(e["id"]) or {}
            for tid, five in sets.items():
                if team_id is not None and tid != team_id:
                    continue
                bucket = ("with_trouble"
                          if any(counts[p] >= level for p in five) else "clean")
                # possession rule matches lineups: a shot or a turnover
                if e["event_type"] == "shot":
                    agg[bucket]["poss"] += 1
                elif e["event_type"] == "turnover":
                    agg[bucket]["poss"] += 1
                if e["shot_result"] == "make" and e["event_type"] in (
                        "shot", "free_throw"):
                    pts = (3 if (e["event_type"] == "shot"
                                 and e["shot_type"] == 3)
                           else (1 if e["event_type"] == "free_throw" else 2))
                    if e.get("shooter_team_id") == tid:
                        agg[bucket]["pts_for"] += pts
                    else:
                        agg[bucket]["pts_against"] += pts
            if e["event_type"] == "foul" and e.get("secondary_player_id"):
                counts[e["secondary_player_id"]] += 1

    out = {"level": level}
    for k, a in agg.items():
        poss = a["poss"]
        out[k] = {
            "poss": poss, "pts_for": a["pts_for"],
            "pts_against": a["pts_against"],
            "per100_for": (round(100.0 * a["pts_for"] / poss, 1) if poss
                           else None),
            "per100_against": (round(100.0 * a["pts_against"] / poss, 1)
                               if poss else None),
        }
        out[k]["net"] = (round(out[k]["per100_for"] - out[k]["per100_against"],
                               1)
                         if poss else None)
    return out


#: Below this many pooled possessions in EITHER state, the team net read is not
#: offered at all. Deliberately generous relative to the on/off gate this
#: codebase already found unreliable at 40.
MIN_STATE_POSS = 150


# ── foul clock — WHEN the fouls land (§1.1 remainder) ────────────────────────
#
# The distribution of "time of Nth foul". Deliberately the most modest thing in
# this module and the only one that is honest at ANY sample, because it makes no
# causal claim whatsoever: it reports when a thing that happened, happened.
#
# It exists because `bench_cost` above answers "what did sitting her cost" and
# cannot answer the question a coach actually asks first, which is "is it early?"
# A second foul at 6:10 of the first quarter and a second foul at 1:20 of the
# second are the same row in every existing read in this app and are completely
# different decisions on the bench. The clock is the context bench_cost lacks.
#
# Nothing here is gated on reliability, because nothing here is a rate. A median
# is a description of the games that were played; it does not predict the next
# one and does not claim to.

#: Game clock, seconds, at which a foul stops being "early". End of Q1 = 480,
#: halftime = 960. A second foul before halftime is the classic bench decision.
HALFTIME_SECS = 960


def _foul_secs(e):
    """Seconds since tip for a foul row, or None when the clock is missing."""
    q, t = e.get("quarter"), e.get("time")
    if not q or not t:
        return None
    try:
        return S.elapsed(int(q), t)
    except Exception:
        return None


def _roster_team():
    """{player_id: team_id} straight off the roster.

    `bench_cost` resolves a player's team from the on-floor sets because it
    needs that map anyway; the clock does not, and building an `_event_floor`
    just to answer "whose player is this" would cost a join for nothing.
    """
    from database.db import query
    return {r["id"]: r["team_id"]
            for r in query("SELECT id, team_id FROM players")
            if r["team_id"] is not None}


def foul_clock(game_ids=None, events=None, team_id=None, player_id=None,
               levels=CLOCK_LEVELS):
    """{pid: {level: {n, times, median, earliest, latest, pre_half}}}.

    `times` is the elapsed-seconds stamp of each Nth personal foul, one entry
    per game the player reached that level. `pre_half` counts how many of those
    landed before halftime.

    THE FOUL CONVENTION IS THE TRAP: on a foul row `secondary_player_id` is the
    FOULER and `primary_player_id` is the player who was FOULED. Reading primary
    here would produce a "foul clock" describing fouls DRAWN, and on the live
    book it yields player-games with 10 and 11 fouls, which is impossible under
    a five-foul disqualification. Same trap bench_cost documents; it is the
    single easiest way to get this whole module backwards.

    `team_id` FILTERS, and used not to. It was accepted and silently dropped, so
    every caller got the same league-wide leaderboard: all 21 girls' teams
    rendered the identical three names, and a coach opening her own page read
    another program's players. Both call sites passed it in good faith. An
    accepted-and-ignored argument is worse than a missing one — the caller looks
    correct.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    roster = _roster_team() if team_id is not None else None

    # per (player, game): the ordered stamps of her own fouls
    per = defaultdict(list)
    for e in events:
        if e.get("event_type") != "foul":
            continue
        fouler = e.get("secondary_player_id")     # NOT primary — see docstring
        if fouler is None:
            continue
        if player_id is not None and fouler != player_id:
            continue
        if roster is not None and roster.get(fouler) != team_id:
            continue
        secs = _foul_secs(e)
        if secs is None:
            continue
        per[(fouler, e.get("game_id"))].append(secs)

    out = defaultdict(dict)
    agg = defaultdict(lambda: defaultdict(list))
    for (pid, _gid), stamps in per.items():
        stamps.sort()
        stamps = stamps[:MAX_PERSONALS]      # a 6th personal is a stat-keeper slip
        for level in levels:
            if len(stamps) >= level:
                agg[pid][level].append(stamps[level - 1])

    for pid, by_level in agg.items():
        for level, times in by_level.items():
            times.sort()
            n = len(times)
            out[pid][level] = {
                "n": n,
                "times": times,
                "median": times[n // 2] if n % 2 else
                          (times[n // 2 - 1] + times[n // 2]) / 2,
                "earliest": times[0],
                "latest": times[-1],
                "pre_half": sum(1 for t in times if t < HALFTIME_SECS),
            }
    return dict(out)


# ── THE QUARTER-RELATIVE READS ────────────────────────────────────────────────
# `HALFTIME_SECS` above splits the game once, at the half, which is the classic
# framing of the SECOND foul and nothing else. A coach does not think in halves
# past that point: three fouls in the second quarter and four in the third are
# each their own decision, and "before halftime" cannot express either.
#
# The rule of thumb both reads below encode is that a player is on pace to foul
# out when her foul count reaches the quarter number. Two in the second, three
# in the third, four in the fourth — each projects to five by the end.
#
# It splits into two genuinely different questions, and they need separate reads
# because one is about the player and the other is about the bench:
#
#   EARLY   — did the Nth foul arrive BEFORE quarter N? That is a fact about
#             when she fouls, and it is the classic bench-decision trigger
#             (2nd in Q1, 3rd in Q2, 4th in Q3).
#   CARRIED — once she was at or past the quarter number, how much of the floor
#             did she actually get? That is a fact about what the staff DID with
#             the trouble, and it is the read the founder asked for: playing with
#             two in the second, or four in the third, is the thing to see.
#
# Neither is gated on reliability, for the same reason `foul_clock` is not:
# neither is a rate. Both are records of games that were played.

#: Regulation quarters. The EARLY read is undefined for the 5th foul (there is
#: no fifth quarter to be early for), and a disqualification is not a bench
#: decision anyway, so it is reported by the clock and not by EARLY.
EARLY_LEVELS = (2, 3, 4)


def early_fouls(game_ids=None, events=None, team_id=None, levels=EARLY_LEVELS):
    """{pid: {level: {games, early, share, quarters}}} — how often the Nth foul
    landed BEFORE quarter N.

    `games` counts the games she reached that level at all; `early` counts those
    where it arrived in an earlier quarter than its own number; `quarters` is the
    per-quarter tally so a caller can show the shape rather than one ratio.

    Overtime periods count as "not early" — a fourth foul in OT is late by any
    reading, and `quarter` is stored as 5+ for OT.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    roster = _roster_team() if team_id is not None else None

    per = defaultdict(list)          # (pid, gid) -> [(secs, quarter), ...]
    for e in events:
        if e.get("event_type") != "foul":
            continue
        fouler = e.get("secondary_player_id")     # THE FOULER. See module docs.
        if fouler is None:
            continue
        if roster is not None and roster.get(fouler) != team_id:
            continue
        secs, q = _foul_secs(e), e.get("quarter")
        if secs is None or not q:
            continue
        per[(fouler, e.get("game_id"))].append((secs, int(q)))

    agg = defaultdict(lambda: defaultdict(
        lambda: {"games": 0, "early": 0, "quarters": defaultdict(int)}))
    for (pid, _gid), stamps in per.items():
        stamps.sort()
        stamps = stamps[:MAX_PERSONALS]      # see MAX_PERSONALS
        for level in levels:
            if len(stamps) < level:
                continue
            q = stamps[level - 1][1]
            a = agg[pid][level]
            a["games"] += 1
            a["quarters"][q] += 1
            if q < level:
                a["early"] += 1

    out = {}
    for pid, by_level in agg.items():
        keep = {}
        for level, a in by_level.items():
            keep[level] = {
                "games": a["games"], "early": a["early"],
                "share": a["early"] / a["games"] if a["games"] else None,
                "quarters": dict(a["quarters"]),
            }
        if keep:
            out[pid] = keep
    return out


#: Quarters the CARRIED read counts. One foul in the first quarter is "on pace"
#: by the arithmetic and is not what any coach calls trouble; measured on the
#: live book it was 34% of all carrying events, diluting every real window.
#: The founder's own examples start at the second quarter — two in the second,
#: four in the third.
CARRY_MIN_QUARTER = 2


def carried_load(game_ids=None, events=None, floor=None, team_id=None,
                 min_events=MIN_FLOOR_EVENTS):
    """{pid: {carry_share, clean_share, drag, ...}} — the floor share a player
    got while carrying AT LEAST as many fouls as the quarter she was in.

    Trouble is evaluated per event, from her foul count so far and that event's
    period, and only from `CARRY_MIN_QUARTER` on.

    THE COMPARATOR IS THE WHOLE DESIGN, AND THE OBVIOUS ONE IS WRONG.
    The first version measured her carrying share against her SEASON share, the
    baseline `bench_cost` uses, and it reproduced exactly the artifact that
    function was rebuilt to avoid (see the note above `_ordinal`). Measured on
    the live book it read Kodi Schwerdfeger at 69.8% while carrying against a
    29.8% season role — a 40-point *gain* — and Morgan Boyles at +37. Neither
    was being played through trouble. They are reserves: a reserve enters late,
    so her fouls arrive late, so the carrying window IS the stretch she was
    finally on the floor. The season baseline was measuring entry timing.

    So the comparator here is her own CLEAN minutes IN THE SAME QUARTERS —
    quarter by quarter, her share while carrying against her share while not,
    pooled and weighted by carrying volume. A reserve who only plays fourth
    quarters is then compared against her own fourth quarters, and the timing
    confound cancels instead of being reported as a finding.

    `drag` = clean_share − carry_share, in share points, positive when she sat.
    `by_state` keys (quarter, fouls) so a caller can show "2 fouls in Q2" rows.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if floor is None:
        floor = _event_floor(game_ids)

    # per (pid, quarter): on/team split by carrying-vs-clean
    cell = defaultdict(lambda: defaultdict(
        lambda: {"c_on": 0, "c_team": 0, "k_on": 0, "k_team": 0}))
    by_state = defaultdict(lambda: defaultdict(lambda: {"on": 0, "team": 0}))
    games = defaultdict(set)
    team_of = {}

    for gid, evs in _by_game(events).items():
        fouls = defaultdict(int)          # pid -> fouls so far THIS game
        dressed = defaultdict(set)        # tid -> {pid} seen on the floor
        for e in evs:
            for tid, five in (floor.get(e["id"]) or {}).items():
                if team_id is None or tid == team_id:
                    dressed[tid] |= set(five)
                    for pid in five:
                        team_of.setdefault(pid, tid)
        for e in evs:
            q = e.get("quarter")
            sets = floor.get(e["id"]) or {}
            if q and int(q) >= CARRY_MIN_QUARTER:
                for tid, five in sets.items():
                    if team_id is not None and tid != team_id:
                        continue
                    # Every player who DRESSED for this team is in exactly one
                    # of the two windows at every event, which is what makes
                    # both numbers floor SHARES over the same denominator.
                    for pid in dressed.get(tid, ()):  # noqa: B020
                        nf = fouls.get(pid, 0)
                        carrying = nf >= int(q)
                        c = cell[pid][int(q)]
                        if carrying:
                            c["c_team"] += 1
                            st_ = by_state[pid][(int(q), nf)]
                            st_["team"] += 1
                            if pid in five:
                                c["c_on"] += 1
                                st_["on"] += 1
                                games[pid].add(gid)
                        else:
                            c["k_team"] += 1
                            if pid in five:
                                c["k_on"] += 1
            if e.get("event_type") == "foul":
                f = e.get("secondary_player_id")      # THE FOULER
                if f is not None:
                    # Clamped: a 6th personal is a stat-keeper slip, and without
                    # this `by_state` would grow a nonsense "6 fouls" row.
                    fouls[f] = min(fouls[f] + 1, MAX_PERSONALS)

    out = {}
    for pid, by_q in cell.items():
        c_on = sum(c["c_on"] for c in by_q.values())
        c_team = sum(c["c_team"] for c in by_q.values())
        if c_team < min_events:
            continue
        # The clean comparator is pooled over the SAME quarters, weighted by how
        # much carrying happened in each — so a player whose trouble is all in
        # the fourth is compared mostly against her own fourth quarters.
        num = den = 0.0
        for q, c in by_q.items():
            if not c["c_team"] or not c["k_team"]:
                continue
            num += (c["k_on"] / c["k_team"]) * c["c_team"]
            den += c["c_team"]
        if not den:
            continue
        carry = c_on / c_team
        clean = num / den
        out[pid] = {
            "on": c_on, "team": c_team,
            "carry_share": round(100.0 * carry, 1),
            "clean_share": round(100.0 * clean, 1),
            "drag": round(100.0 * (clean - carry), 1),
            "games": len(games[pid]),
            "team_id": team_of.get(pid),
            "quarters": sorted(by_q),
            "by_state": {k: dict(v) for k, v in by_state[pid].items()},
        }
    return out


def clock_label(secs):
    """Elapsed seconds → the period-and-clock a coach reads ('Q2 3:40')."""
    if secs is None:
        return "—"
    secs = max(0, int(secs))
    if secs < 1920:
        q = secs // 480 + 1
        left = 480 - (secs - 480 * (q - 1))
    else:
        ot = (secs - 1920) // 240 + 1
        q = f"OT{ot}" if ot > 1 else "OT"
        left = 240 - ((secs - 1920) - 240 * (ot - 1))
        return f"{q} {left // 60}:{left % 60:02d}"
    return f"Q{q} {left // 60}:{left % 60:02d}"


def foul_clock_lines(clock, names=None, level=None, levels=CLOCK_LEVELS,
                     min_games=MIN_GAMES_AT_LEVEL, per_level=3):
    """[(badge, n, html)] — the descriptive read, safe at any sample.

    Every level in `levels` reports, not only the second. The second foul is the
    classic first-half decision, but three in the third and four in the fourth
    are each their own call and used to be computed and then thrown away: both
    render sites passed `level=2` and the rest of the dict was never shown.

    Within a level, sorted by how EARLY the median lands — whoever tops that list
    is the player the bench decision keeps arriving for. `level=` still works and
    means "just this one", so older callers are unchanged.
    """
    def nm(pid):
        return (names or {}).get(pid, f"#{pid}")

    want = (level,) if level is not None else tuple(levels)
    lines = []
    for lv in want:
        rows = [(pid, d[lv]) for pid, d in (clock or {}).items()
                if lv in d and d[lv]["n"] >= min_games]
        rows.sort(key=lambda r: r[1]["median"])
        ord_ = _ordinal(lv)
        for pid, d in (rows[:per_level] if per_level else rows):
            share = d["pre_half"] / d["n"]
            # A fifth foul is a disqualification; "picks up her 5th" undersells
            # what a coach is reading, which is when she was lost for the night.
            verb = ("fouls out" if lv >= 5
                    else f"picks up her {ord_}")
            lines.append((
                f"{ord_} foul", d["n"],
                f"<b>{nm(pid)}</b> {verb} at <b>"
                f"{clock_label(d['median'])}</b> on a typical night "
                f"({d['n']} game{'s' if d['n'] != 1 else ''}; earliest "
                f"{clock_label(d['earliest'])})"
                + (f", and <b>{d['pre_half']} of {d['n']}</b> land before "
                   f"halftime." if share >= 0.5 else ".")))
    return lines


def quarter_rule_lines(early, carried, names=None,
                       min_games=MIN_GAMES_AT_LEVEL, min_drag=5.0):
    """[(badge, n, html)] for the two quarter-relative reads.

    EARLY first — it is a fact about the player and the trigger for the decision
    — then CARRIED, which is what the staff did once the trigger fired.
    """
    def nm(pid):
        return (names or {}).get(pid, f"#{pid}")

    lines = []

    # ── EARLY: the Nth foul before quarter N ─────────────────────────────────
    worst = None
    for pid, by_level in (early or {}).items():
        for lv, d in by_level.items():
            if d["games"] < min_games or not d["early"]:
                continue
            if worst is None or (d["share"], d["early"]) > \
                    (worst[2]["share"], worst[2]["early"]):
                worst = (pid, lv, d)
    if worst:
        pid, lv, d = worst
        ord_ = _ordinal(lv)
        lines.append((
            f"{ord_} early", d["games"],
            f"<b>{nm(pid)}</b> reaches her {ord_} foul before the "
            f"{_ordinal(lv)} quarter in <b>{d['early']} of {d['games']}</b> "
            f"games she gets there — on pace to foul out, with a quarter still "
            f"to play. That is the trigger; the row below is what the bench did "
            f"with it."))
    elif early:
        lines.append((
            "Foul pace", sum(d["games"] for by in early.values()
                             for d in by.values()),
            "Nobody on this roster is reaching her Nth foul before the Nth "
            "quarter often enough to call it a pattern — fouls are arriving on "
            "or behind the pace that projects to fouling out."))

    # ── CARRIED: floor share once she is at or past the quarter number ────────
    best = None
    for pid, d in (carried or {}).items():
        if d["games"] < min_games:
            continue
        if best is None or d["drag"] > best[1]["drag"]:
            best = (pid, d)
    if best:
        pid, d = best
        if d["drag"] >= min_drag:
            lines.append((
                "Played through it", d["games"],
                f"<b>{nm(pid)}</b> is on the floor for "
                f"<b>{d['carry_share']:.0f}%</b> of the game once she is "
                f"carrying as many fouls as the quarter, against "
                f"<b>{d['clean_share']:.0f}%</b> of the same quarters when she "
                f"is not — <b>{d['drag']:.0f} percentage points of floor share</b> across "
                f"{d['games']} games. Compared against her own clean quarters, "
                f"so a reserve who only plays fourths is not scored for "
                f"entering late."))
        else:
            lines.append((
                "Played through it", d["games"],
                f"Nobody's minutes move much once the fouls reach the quarter "
                f"number — the largest change is <b>{nm(pid)}</b> at "
                f"<b>{d['drag']:+.0f}</b> percentage points of floor share against her own "
                f"clean quarters. This staff plays through foul trouble."))
    return lines


# ── crew cross — ACCUMULATE, DO NOT SURFACE ──────────────────────────────────
#
# MEASURED 2026-07-26, and it fails harder than the roadmap predicted.
#
# 200 random half-splits of the girls' 2025-2026 book (35 games, 919 fouls, 65
# officials), foul rate per player-event of exposure:
#
#     unit                              r        SB     qualifying units
#     player foul rate (the ceiling)   .518     .682     26.8   @20 exposure
#                                      .619     .765     14.0   @40
#                                      .720     .837      4.5   @80
#     player x CREW foul rate         -.254    -.680      5.9   @20
#                                              not measurable   @40+
#
# The crew cell does not merely fail to predict itself — it ANTI-correlates, on
# about six qualifying cells, and above the lowest exposure threshold there are
# not enough cells to compute an r at all. The reason is structural rather than
# unlucky: the busiest official in this book has worked FOUR games. Splitting
# four games in half and asking whether a player's foul rate in two of them
# predicts the other two is not a thin measurement, it is not a measurement.
#
# The roadmap proposed gating at ">=3 games with a crew, labelled a lean". That
# gate would fire on a handful of cells and every one of them would be noise
# wearing a confidence label. So this function returns COUNTS and exposure and
# never a rate, a lean, or a verdict, and nothing renders it. It exists so the
# sample accrues against the day there are enough games — the read is genuinely
# valuable and no competitor can attempt it, which is exactly why it must not
# ship wrong first.
#
# The positive finding is worth more than the negative one: a player's OVERALL
# foul rate is reliable (SB .68 at 20 events of exposure, .84 at 80). Foul rate
# is a real player trait in this book. It is only the CREW split that this
# sample cannot carry, and that is a games problem which time fixes on its own.

#: Games with a crew before the accumulated cell is even worth returning. Not a
#: display gate -- nothing displays this -- just a floor on what is worth
#: carrying around.
MIN_CREW_GAMES = 3


def crew_foul_rate(game_ids=None, events=None, player_id=None, min_games=1):
    """{(pid, official_id): {fouls, exposure, games}} — the ACCUMULATOR.

    Deliberately returns no rate. See the measurement above: the player x crew
    cell anti-correlates with itself at r=-.254 on ~6 qualifying cells, because
    the busiest official in this book has worked four games. Handing back a
    `rate` key would invite a caller to render it, and there is no threshold in
    this book at which it means anything.

    `exposure` is the player's event count in those games — a floor-time proxy,
    the same one bench_cost's shares are built from. Call it, store it, let the
    sample grow; do not put it on screen.
    """
    if events is None:
        events = S.fetch_events(game_ids)

    crew_of = defaultdict(set)
    expo = defaultdict(int)
    for e in events:
        gid = e.get("game_id")
        if e.get("event_type") == "foul" and e.get("official_id"):
            crew_of[gid].add(e["official_id"])
        pid = e.get("primary_player_id")
        if pid is not None and gid is not None:
            expo[(pid, gid)] += 1

    out = defaultdict(lambda: {"fouls": 0, "exposure": 0, "games": set()})
    for e in events:
        if e.get("event_type") != "foul":
            continue
        fouler = e.get("secondary_player_id")     # NOT primary — see foul_clock
        oid = e.get("official_id")
        if fouler is None or not oid:
            continue
        if player_id is not None and fouler != player_id:
            continue
        cell = out[(fouler, oid)]
        cell["fouls"] += 1
        # Count the game HERE as well as in the exposure pass below. Committing
        # a foul is itself proof the player was in that game with that
        # official, and the exposure pass keys on `primary_player_id` — which a
        # defensive specialist may barely appear as. Relying on exposure alone
        # dropped whole cells that had fouls in them.
        if e.get("game_id") is not None:
            cell["games"].add(e["game_id"])

    for (pid, gid), n in expo.items():
        if player_id is not None and pid != player_id:
            continue
        for oid in crew_of.get(gid, ()):
            cell = out[(pid, oid)]
            cell["exposure"] += n
            cell["games"].add(gid)

    return {k: {"fouls": v["fouls"], "exposure": v["exposure"],
                "games": len(v["games"])}
            for k, v in out.items() if len(v["games"]) >= min_games}


def foul_trouble_verdict(bench, state, names=None):
    """[(badge, n, html)] for helpers.cards.verdict_card.

    Leads with the bench cost, which is the measurable half, and offers the
    pooled net only when both states clear MIN_STATE_POSS.
    """
    def nm(pid):
        return (names or {}).get(pid, f"#{pid}")

    lines = []
    # biggest drag at the level with the most evidence behind it
    best = None
    for pid, levels_d in (bench or {}).items():
        for level, d in levels_d.items():
            if best is None or d["drag"] > best[2]["drag"]:
                best = (pid, level, d)
    if best:
        pid, level, d = best
        ord_ = _ordinal(level)
        if d["drag"] > 5:
            # "a 21 point drop" in a basketball app reads as TWENTY-ONE POINTS.
            # It is 21 percentage points of floor share, and the units have to
            # be in the sentence — a coach should not have to infer them.
            lines.append((
                f"{ord_} foul", d["games"],
                f"<b>{nm(pid)}</b> is on the floor for "
                f"<b>{d['after_share']:.0f}%</b> of what is left after her "
                f"{ord_} foul, against <b>{d['season_share']:.0f}%</b> in a "
                f"normal game — she loses <b>{d['drag']:.0f} percentage points "
                f"of floor share</b> over {d['games']} such games. That is the "
                f"bench decision, measured."))
        else:
            lines.append((
                f"{ord_} foul", d["games"],
                f"Nobody's minutes move much on fouls — the biggest change is "
                f"<b>{nm(pid)}</b> at <b>{d['drag']:+.0f}</b> percentage points "
                f"of floor share against her normal role after her {ord_}. This "
                f"staff plays through foul trouble."))

    if state:
        w, c = state.get("with_trouble") or {}, state.get("clean") or {}
        if (w.get("poss") or 0) >= MIN_STATE_POSS and \
                (c.get("poss") or 0) >= MIN_STATE_POSS:
            delta = (w["net"] or 0) - (c["net"] or 0)
            worse = "worse" if delta < 0 else "better"
            lines.append((
                "On the floor", w["poss"],
                f"With someone carrying {state['level']}+ fouls the team is "
                f"<b>{w['net']:+.1f}</b> per 100 against "
                f"<b>{c['net']:+.1f}</b> otherwise — <b>{abs(delta):.1f}</b> "
                f"{worse}. Descriptive only: foul trouble is not handed out at "
                f"random, so this is not the cost of the fouls themselves."))
    return lines
