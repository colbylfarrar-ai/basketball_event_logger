"""deserved.py — where a game's margin actually came from, in four exact terms.

THE ONE THING TO KNOW BEFORE USING THIS MODULE
----------------------------------------------
This is the surviving piece of the xPPP thread, and it survives as a
DESCRIPTION OF A GAME THAT WAS PLAYED — never as a forecast. `reliability.py`,
block SHOT QUALITY DOES NOT FORECAST SCORING ON THIS BOOK, measured the
forecasting premise and refused it: expected shot quality predicts future
scoring at r = .176 while past scoring predicts it at r = .655. Nothing in here
may be phrased as a claim about a rematch.

WHAT IT COMPUTES
----------------
Every point of a game's final margin, attributed to one of four causes that sum
to it EXACTLY (verified to 1e-9 on the live book, and the event book reproduces
the official scoreboard on 52 of 52 tracked games):

    final margin  =  VOLUME  +  QUALITY  +  MAKING  +  FREE THROWS

    VOLUME   how many more shots this team got than its opponent, priced at the
             league's neutral shot. Extra chances.
    QUALITY  those attempts being better or worse looks than neutral — the shot
             SELECTION term.
    MAKING   actual field-goal points minus expected. Whether the ball went in
             at more or less than the looks deserved.
    FREE     the margin at the line.

WHY THE ORDER MATTERS, AND WHY THIS MODULE EXISTS AT ALL
--------------------------------------------------------
The handoff that scoped this work carried the note that the expected-points
margin "partly restates possession count rather than quality per shot", filed
as a caveat to fix later. Measured over 52 tracked games it is not a caveat, it
is the headline:

    |VOLUME|   mean 12.91 pts   median 11.59
    |QUALITY|  mean  3.09 pts   median  2.43
    VOLUME is the larger of the two in 47 of 52 games.

So an "expected margin" presented as a shot-QUALITY verdict would be mislabelled
by roughly four to one. The fix is not to drop the number, it is to name its
parts — which turns out to make the read far more useful, because the dominant
term decomposes into the two most coachable events in basketball:

    r(attempt gap, offensive-rebound edge)              = +0.816
    r(attempt gap, turnover edge)                       = +0.899
    r(attempt gap, ORB edge - turnover edge)            = +0.979
    same direction in 49 of 52 games; residual sd 3.5 shots (pace / FT trips)

A team gets more shots than its opponent because it rebounds its own misses and
does not give the ball away. That is the sentence this module exists to let the
app say.

THE SECOND CAVEAT IS RETIRED, AND ITS PREMISE WAS WRONG TWICE OVER
------------------------------------------------------------------
The stated caveat was that xPPS inherits the `guarded_by_id` "tagging rate" —
described in the earlier notes as an opt-in tap present on 72-75% of shots.
That description is itself the error: `guarded_by_id` records WHO AFFECTED THE
SHOT, so an attempt without one is an UNCONTESTED shot, not an unrecorded one.
Contested attempts shoot .330 and uncontested .461; the rate runs 70.6% in
girls' games against 90.4% in boys' games, and it repeats at SB .69-.74. It is
a defensive trait, and `reliability.CONTEST RATE ALLOWED IS A REAL DEFENSIVE
TRAIT` now carries the measurement.

Either way the margin is unaffected, which is what this module needed to know.
Refitting the whole book with NO contest term at all picks the same expected
winner in 52 of 52 games, r = .995 with the contested version — the contest
term moves the LEVEL of xPPS on both sides of a game together, and cancels in
the difference. `contest_rate` still rides along on every row, now as a
descriptive figure worth reading rather than a caveat to apologise for.

HOW WELL THE EXPECTED MARGIN TRACKS THE SCOREBOARD (52 games, out of sample)
    picks the scoreboard winner   38/52  (73.1%)
    r with final margin           .874        [ceiling, actual FG margin: .981]
    disagrees on                  14 of 52

Those fourteen are the point of the surface, not its error bar: they are the
games where the shots and the possessions pointed one way and the ball went the
other.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S
from database.db import query

#: A side needs this many field-goal attempts before its game is decomposed.
#: Below it the neutral-shot pricing is carrying more weight than the sample.
MIN_FGA = 10

#: Contest rate (share of a game's attempts that a defender affected) below
#: which a row is captioned as an unusually uncontested game. This is a
#: DESCRIPTIVE flag about how the game was played, not a data-quality warning —
#: the margin is unaffected either way (r = .995 against a contest-free book).
LOW_CONTEST = 0.50


def _shot_key(e):
    """The (kind, creation, contested) key of the shot-quality rate book."""
    return (S._sq_loc(e),
            S._creation_bucket(e["pass_from_id"] is not None,
                               e["shot_created_by_id"] is not None),
            e["guarded_by_id"] is not None)


def game_ledgers(events=None, game_ids=None, rates=None):
    """{game_id: row} — the four-term decomposition of every tracked game.

    `events` should already be fetched by the caller when other engines need
    the same pass (prod is 1 vCPU; this module never re-fetches if handed a
    list). `rates` likewise — pass a shared `S.shot_quality_rates` book and it
    is not rebuilt.

    Each row is oriented from the HOME team's point of view (`team1_id`, which
    the live book confirms is home on 52 of 52 games); `for_team()` flips it.
    """
    if events is None:
        # S.fetch_events([]) returns the ENTIRE database — an empty pool must
        # mean "nothing", not "everything".
        if game_ids is not None and not game_ids:
            return {}
        events = S.fetch_events(game_ids)
    if not events:
        return {}
    if rates is None:
        rates = S.shot_quality_rates(events=events)

    gids = {e["game_id"] for e in events}
    games = {r["id"]: r for r in query(
        "SELECT id, team1_id, team2_id, home_score, away_score, date, season "
        "FROM games WHERE tracked=1")}
    pteam = {r["id"]: r["team_id"] for r in query(
        "SELECT id, team_id FROM players")}
    tname = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}

    per = defaultdict(lambda: defaultdict(
        lambda: dict(fga=0, val=0.0, pts=0.0, xpts=0.0, contested=0,
                     ft=0, fta=0, orb=0, tov=0)))
    for e in events:
        gid = e["game_id"]
        if gid not in games:
            continue
        et = e["event_type"]
        st = e["shooter_team_id"]
        if et == "shot" and st is not None:
            a = per[gid][st]
            v = 3 if e["shot_type"] == 3 else 2
            a["fga"] += 1
            a["val"] += v
            if e["shot_result"] == "make":
                a["pts"] += v
            a["xpts"] += rates.backoff_pct(_shot_key(e)) * v
            # guarded_by_id = who AFFECTED the shot, so this counts
            # genuinely contested attempts, not tagged ones.
            if e["guarded_by_id"] is not None:
                a["contested"] += 1
            if e["shot_result"] != "make":
                rt = e["rebounder_team_id"]
                if rt is not None and rt == st:
                    per[gid][rt]["orb"] += 1
        elif et == "free_throw" and st is not None:
            a = per[gid][st]
            a["fta"] += 1
            if e["shot_result"] == "make":
                a["ft"] += 1
        elif et == "turnover":
            t = pteam.get(e["primary_player_id"])
            if t is not None:
                per[gid][t]["tov"] += 1

    neutral_pct = rates.overall_pct
    out = {}
    for gid in gids:
        g = games.get(gid)
        sides = per.get(gid)
        if not g or not sides:
            continue
        home, away = g["team1_id"], g["team2_id"]
        if home is None or away is None:
            continue
        h, a = sides.get(home), sides.get(away)
        if not h or not a:
            continue
        if min(h["fga"], a["fga"]) < MIN_FGA:
            continue

        def neutral(s):
            """What this side's own attempts would be worth at league-average
            shooting — its shot VALUE mix priced at the pooled make rate, so a
            three-heavy diet is not mispriced as a diet of twos."""
            return neutral_pct * (s["val"] / s["fga"]) * s["fga"] if s["fga"] else 0.0

        volume = neutral(h) - neutral(a)
        quality = (h["xpts"] - neutral(h)) - (a["xpts"] - neutral(a))
        xmargin = h["xpts"] - a["xpts"]
        fg_margin = h["pts"] - a["pts"]
        making = fg_margin - xmargin
        ft_margin = h["ft"] - a["ft"]
        margin = fg_margin + ft_margin
        cov_n = h["fga"] + a["fga"]
        out[gid] = {
            "game_id": gid, "date": g["date"], "season": g["season"],
            "home_id": home, "away_id": away,
            "home_name": tname.get(home, str(home)),
            "away_name": tname.get(away, str(away)),
            "margin": margin, "fg_margin": fg_margin, "ft_margin": ft_margin,
            "xmargin": xmargin,
            "volume": volume, "quality": quality, "making": making,
            "home": dict(h), "away": dict(a),
            "fga_gap": h["fga"] - a["fga"],
            "orb_gap": h["orb"] - a["orb"],
            "tov_gap": h["tov"] - a["tov"],
            "contest_rate": ((h["contested"] + a["contested"]) / cov_n)
            if cov_n else 0.0,
            # did the expected margin point at the team that actually won?
            "agree": (margin != 0 and (xmargin > 0) == (margin > 0)),
            "decided": margin != 0,
        }
    return out


def for_team(row, team_id):
    """One ledger row re-oriented so every term is signed FOR `team_id`."""
    if row["home_id"] == team_id:
        s, us, them = 1, row["home"], row["away"]
        opp_id, opp = row["away_id"], row["away_name"]
    elif row["away_id"] == team_id:
        s, us, them = -1, row["away"], row["home"]
        opp_id, opp = row["home_id"], row["home_name"]
    else:
        return None
    return {
        "game_id": row["game_id"], "date": row["date"],
        "opp_id": opp_id, "opp_name": opp, "home": row["home_id"] == team_id,
        "margin": s * row["margin"], "fg_margin": s * row["fg_margin"],
        "ft_margin": s * row["ft_margin"], "xmargin": s * row["xmargin"],
        "volume": s * row["volume"], "quality": s * row["quality"],
        "making": s * row["making"],
        "fga": us["fga"], "opp_fga": them["fga"],
        "fga_gap": us["fga"] - them["fga"],
        "orb": us["orb"], "opp_orb": them["orb"],
        "orb_gap": us["orb"] - them["orb"],
        "tov": us["tov"], "opp_tov": them["tov"],
        "tov_gap": us["tov"] - them["tov"],
        "pts_fg": us["pts"], "xpts": us["xpts"],
        "opp_pts_fg": them["pts"], "opp_xpts": them["xpts"],
        "contest_rate": row["contest_rate"], "agree": row["agree"],
        "decided": row["decided"],
        "won": (s * row["margin"]) > 0,
    }


def team_deserved(team_id, events=None, game_ids=None, rates=None,
                  ledgers=None):
    """Season roll-up of the four-term ledger for one team.

    `ledgers` lets a caller that already built the league-wide pass hand it in
    rather than paying for it twice.
    """
    if ledgers is None:
        ledgers = game_ledgers(events=events, game_ids=game_ids, rates=rates)
    rows = [r for r in (for_team(v, team_id) for v in ledgers.values())
            if r is not None]
    if not rows:
        return {"available": False, "games": 0, "rows": []}
    rows.sort(key=lambda r: (r["date"] or "", r["game_id"]))
    n = len(rows)
    dec = [r for r in rows if r["decided"]]
    tot = {k: sum(r[k] for r in rows)
           for k in ("volume", "quality", "making", "ft_margin", "margin",
                     "xmargin", "orb_gap", "tov_gap", "fga_gap")}
    # The season's own biggest artefact. Two DIFFERENT things, and conflating
    # them writes a false sentence: an UPSET is a game whose expected margin
    # points at the other team (a real "the looks went one way, the ball went
    # the other"), while the biggest GAP may be a blowout that was merely more
    # of a blowout than the shots deserved — same team ahead on both counts.
    # Prefer a genuine upset; fall back to the gap and let the caller word it
    # differently.
    gap = max(rows, key=lambda r: abs(r["margin"] - r["xmargin"]))
    upsets = [r for r in rows if r["decided"] and not r["agree"]]
    upset = (max(upsets, key=lambda r: abs(r["margin"] - r["xmargin"]))
             if upsets else None)
    # Which term carries this team's season, by mean absolute size — the answer
    # to "what actually decides our games".
    terms = [("volume", "extra shots"), ("quality", "shot selection"),
             ("making", "shot-making"), ("ft_margin", "free throws")]
    ranked = sorted(
        ((k, lbl, sum(abs(r[k]) for r in rows) / n, tot[k] / n)
         for k, lbl in terms), key=lambda t: -t[2])
    return {
        "available": True, "games": n, "rows": rows,
        "record": (sum(1 for r in rows if r["won"]),
                   sum(1 for r in rows if r["decided"] and not r["won"])),
        "totals": tot, "means": {k: v / n for k, v in tot.items()},
        "agree": sum(1 for r in dec if r["agree"]), "decided": len(dec),
        "agree_pct": (100.0 * sum(1 for r in dec if r["agree"]) / len(dec)
                      if dec else None),
        "biggest_gap": gap, "biggest_upset": upset, "ranked_terms": ranked,
        "low_contest": [r for r in rows
                        if r["contest_rate"] < LOW_CONTEST],
    }


def _pts(v):
    return f"{v:+.0f}" if abs(v) >= 0.5 else "0"


def deserved_verdict(d, team_name="This team"):
    """[(badge, n, html)] for helpers.cards.verdict_card.

    Coach register: standard shorthand used bare (FGA, ORB, TOV, PPS), numbers
    before prose, and no term-of-art glossed. What IS spelled out is the thing
    a coach cannot get by looking — which of the four terms actually moved this
    team's season, and how firmly it is measured. Units are scoreboard points
    throughout so the four stay comparable.
    """
    if not d.get("available") or d["games"] < 3:
        return []
    lines = []
    n = d["games"]
    m = d["means"]
    w, l = d["record"]

    # 1. the headline — the four terms, largest first
    lead_key, lead_lbl, lead_abs, lead_signed = d["ranked_terms"][0]
    lines.append((
        "Margin split", n,
        f"<b>{n}g {w}–{l}</b>, <b>{_pts(m['margin'])}</b>/g. Extra shots "
        f"<b>{_pts(m['volume'])}</b> · selection "
        f"<b>{_pts(m['quality'])}</b> · making <b>{_pts(m['making'])}</b> · "
        f"FTs <b>{_pts(m['ft_margin'])}</b>. Biggest swing: "
        f"<b>{lead_lbl}</b> at ±{lead_abs:.1f}/g."))

    # 2. the volume term, named by its cause — the coachable half
    #
    # Both causes are margins (us minus them), but they push the shot gap in
    # OPPOSITE directions: +ORB is more shots, -TOV is also more shots. Printed
    # raw and side by side ("ORB +5.9 · TOV -10.4" under a +16.5 headline) the
    # two read as if they should sum to -4.5, and the reader is left to notice
    # the sign flip on their own. So each is quoted as its CONTRIBUTION to the
    # shot gap — same sign as the headline — and named in words.
    orb, tov = m["orb_gap"], m["tov_gap"]
    if abs(m["volume"]) >= 1.0:
        cause = []
        if abs(orb) >= 0.7:
            cause.append(f"<b>{orb:+.1f}</b> on the offensive glass")
        if abs(tov) >= 0.7:
            cause.append(f"<b>{-tov:+.1f}</b> from "
                         + ("giving it away less often" if tov < 0
                            else "giving it away more often"))
        why = (" — " + " and ".join(cause)) if cause else ""
        lines.append((
            "Extra shots", n,
            f"<b>{m['fga_gap']:+.1f} FGA/g</b> vs opponents, worth "
            f"<b>{_pts(m['volume'])}</b>{why}. Across the book those two "
            f"account for the shot gap at <b>r = .98</b> — the most directly "
            f"coachable half of the scoreboard."))

    # 3. did the shots and possessions agree with the scoreboard
    if d["agree_pct"] is not None and d["decided"] >= 3:
        up = d["biggest_upset"]
        if up is not None:
            # a genuine sign flip — the only case that earns the phrase
            example = (f"Widest miss <b>{up['opp_name']}</b>: "
                       f"{'W' if up['margin'] > 0 else 'L'}"
                       f"{abs(up['margin']):.0f} on "
                       f"<b>{up['xmargin']:+.1f}</b> play.")
        else:
            g = d["biggest_gap"]
            example = (f"No result went against the play. Widest stretch "
                       f"<b>{g['opp_name']}</b>: "
                       f"{'W' if g['margin'] > 0 else 'L'}"
                       f"{abs(g['margin']):.0f} on "
                       f"<b>{g['xmargin']:+.1f}</b>.")
        lines.append((
            "Deserved result", d["decided"],
            f"Play matched result in <b>{d['agree']} of {d['decided']}</b> "
            f"({d['agree_pct']:.0f}%). {example} Descriptive — shot quality "
            f"does not forecast scoring on this book."))

    # 4. shot-making, flagged as the least repeatable of the four
    if abs(m["making"]) >= 1.0:
        hot = m["making"] > 0
        lines.append((
            "Shot-making", n,
            f"<b>{m['making']:+.1f}/g</b> against what the looks were worth — "
            + ("the least repeatable of the four, so the volume and selection "
               "numbers are the ones to build on."
               if hot else
               "process is ahead of the record; the looks being created are "
               "worth more than the scoreboard has paid out.")))
    return lines


def game_story(row, team_name="This team", min_pts=0.5):
    """One game, term by term, coach register.

    Returns [(label, points, sentence)] ordered largest-influence-first, so the
    thing that decided the game leads regardless of which term it was.

    EVERY term is a MARGIN — this team's figure minus the opponent's — so every
    sentence quotes BOTH sides. Quoting only this team's own number next to a
    margin-sized total is the way this section would lie: a +24 shot-making
    term sitting beside "61 points scored against 58 expected" invites the
    reader to do the subtraction and get 3, when the other 21 points of it are
    the opponent shooting below their own looks.
    """
    us_make = row["pts_fg"] - row["xpts"]
    them_make = row["opp_pts_fg"] - row["opp_xpts"]
    terms = [
        ("Extra shots", row["volume"],
         f"<b>{row['fga_gap']:+d} FGA</b> ({row['fga']}–{row['opp_fga']}) · "
         f"ORB {row['orb']}–{row['opp_orb']} · "
         f"TOV {row['tov']}–{row['opp_tov']}"),
        ("Shot selection", row["quality"],
         f"looks worth <b>{row['xpts']:.0f}</b> to "
         f"<b>{row['opp_xpts']:.0f}</b> on "
         f"{row['fga']} and {row['opp_fga']} FGA"),
        ("Shot-making", row["making"],
         f"<b>{row['pts_fg']:.0f}</b> from the field on "
         f"<b>{row['xpts']:.0f}</b> expected (<b>{us_make:+.1f}</b>) vs "
         f"opponent <b>{row['opp_pts_fg']:.0f}</b> on "
         f"<b>{row['opp_xpts']:.0f}</b> (<b>{them_make:+.1f}</b>)"
         # the term is OURS minus THEIRS. Whether that reads as reinforcing or
         # as offsetting depends on the two signs, and asserting one of them
         # unconditionally printed a false clause about half the time.
         + (" — both push the same way, so they add rather than cancelling"
            if (us_make > 0) != (them_make > 0)
            else " — same direction on both ends, so they partly offset")),
        ("Free throws", float(row["ft_margin"]),
         f"<b>{row['ft_margin']:+d}</b> at the line"),
    ]
    terms.sort(key=lambda t: -abs(t[1]))
    # `min_pts=0` keeps all four, which is what a caller showing a TOTAL needs:
    # drop a 0.3-point term and the visible rows stop adding to the margin.
    return [(lbl, pts, txt) for lbl, pts, txt in terms if abs(pts) >= min_pts]
