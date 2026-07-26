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

THE SECOND CAVEAT IS RETIRED, NOT INHERITED
-------------------------------------------
The other stated caveat was that xPPS inherits the `guarded_by_id` tagging rate
(an opt-in tap on 72-75% of shots, and per-game coverage ranges .23 to .96).
Measured: refitting the whole book with NO contest term at all picks the same
expected winner in 52 of 52 games, r = .995 with the contested version. Coverage
moves the LEVEL of xPPS but not the MARGIN, because both teams in a game share
one tracker operator and therefore one coverage rate. The margin is safe;
`coverage` still rides along on every row so a thin game can be captioned.

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

#: Per-game guarded-tagging coverage under which a row is flagged thin. The
#: MARGIN survives low coverage (r = .995 against a contest-free book) — this
#: only drives a caption, never a gate.
THIN_COVERAGE = 0.50


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
        lambda: dict(fga=0, val=0.0, pts=0.0, xpts=0.0, tagged=0,
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
            if e["guarded_by_id"] is not None:
                a["tagged"] += 1
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
            "coverage": ((h["tagged"] + a["tagged"]) / cov_n) if cov_n else 0.0,
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
        "coverage": row["coverage"], "agree": row["agree"],
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
        "thin": [r for r in rows if r["coverage"] < THIN_COVERAGE],
    }


def _pts(v):
    return f"{v:+.0f}" if abs(v) >= 0.5 else "0"


def deserved_verdict(d, team_name="This team"):
    """[(badge, n, html)] for helpers.cards.verdict_card.

    Written for a reader who has never watched a basketball game: every term is
    spelled out in what it physically means, and the units are points on the
    scoreboard throughout.
    """
    if not d.get("available") or d["games"] < 3:
        return []
    lines = []
    n = d["games"]
    m = d["means"]
    w, l = d["record"]

    # 1. the headline — what the four terms say about the season as a whole
    lead_key, lead_lbl, lead_abs, lead_signed = d["ranked_terms"][0]
    lines.append((
        "Where the margin comes from", n,
        f"Across <b>{n} tracked games</b> ({w}–{l}), every point of every "
        f"final margin lands in one of four buckets, and they add up exactly. "
        f"Per game this team is <b>{_pts(m['volume'])}</b> on extra shots, "
        f"<b>{_pts(m['quality'])}</b> on the quality of those shots, "
        f"<b>{_pts(m['making'])}</b> on whether the ball went in, and "
        f"<b>{_pts(m['ft_margin'])}</b> at the free-throw line — "
        f"<b>{_pts(m['margin'])}</b> a game overall. The biggest single "
        f"influence on this team's results is <b>{lead_lbl}</b> "
        f"(±{lead_abs:.1f} pts a game)."))

    # 2. the volume term, named by its cause — the coachable half
    orb, tov = m["orb_gap"], m["tov_gap"]
    if abs(m["volume"]) >= 1.0:
        who = "more" if m["volume"] > 0 else "fewer"
        cause = []
        if abs(orb) >= 0.7:
            cause.append(
                f"they {'win' if orb > 0 else 'lose'} the offensive glass by "
                f"<b>{abs(orb):.1f} rebounds a game</b> (every offensive "
                f"rebound is a whole extra shot)")
        if abs(tov) >= 0.7:
            cause.append(
                f"they give the ball away <b>{abs(tov):.1f} "
                f"{'more' if tov > 0 else 'fewer'} times a game</b> than the "
                f"opponent (every turnover is a possession with no shot at "
                f"all)")
        why = (" Why: " + "; and ".join(cause) + ".") if cause else ""
        lines.append((
            "Extra shots", n,
            f"This team takes <b>{abs(m['fga_gap']):.1f} {who} shots a game</b> "
            f"than its opponents, worth <b>{_pts(m['volume'])} points</b>."
            f"{why} Over the whole book the shot gap is explained by rebounds "
            f"minus turnovers at <b>r = 0.98</b>, so this is the half of the "
            f"scoreboard a coach has the most direct control over."))

    # 3. did the shots and possessions agree with the scoreboard
    if d["agree_pct"] is not None and d["decided"] >= 3:
        miss = d["decided"] - d["agree"]
        up = d["biggest_upset"]
        if up is not None:
            # a genuine sign flip — the only case that earns the phrase
            example = (
                f"The clearest was <b>vs {up['opp_name']}</b>: this team "
                f"{'won' if up['margin'] > 0 else 'lost'} by "
                f"<b>{abs(up['margin']):.0f}</b>, while the shots taken and "
                f"the chances created were worth "
                f"<b>{up['xmargin']:+.1f}</b> — the looks went one way and "
                f"the ball went the other.")
        else:
            g = d["biggest_gap"]
            example = (
                f"No game on this book was actually won by the team the "
                f"shots favoured the other way. The widest stretch was "
                f"<b>vs {g['opp_name']}</b>: a "
                f"<b>{abs(g['margin']):.0f}-point</b> "
                f"{'win' if g['margin'] > 0 else 'loss'} where the shots and "
                f"chances were worth <b>{g['xmargin']:+.1f}</b> — the right "
                f"team came out ahead, by more than the play deserved.")
        lines.append((
            "Deserved result", d["decided"],
            f"Counting only the shots taken and the chances created — "
            f"before a single one went in or rimmed out — the game pointed "
            f"at the eventual winner in <b>{d['agree']} of {d['decided']}</b> "
            f"games ({d['agree_pct']:.0f}%). The other {miss} are the "
            f"interesting ones. {example} That is a fact about the night it "
            f"happened, not a prediction about the rematch."))

    # 4. shot-making, stated as what it is: the least controllable term
    if abs(m["making"]) >= 1.0:
        hot = m["making"] > 0
        lines.append((
            "Shot-making", n,
            f"The ball went in <b>{abs(m['making']):.1f} points a game "
            f"{'more' if hot else 'less'}</b> than the quality of the looks "
            f"would predict. "
            + ("That is the flattering half of this record: it is real, it "
               "happened, and it is the term least likely to hold up on its "
               "own — the possession and selection numbers above are the "
               "ones to build on."
               if hot else
               "The looks were better than the results. That is the "
               "encouraging reading of a disappointing record — the shots "
               "being created are worth more than the scoreboard has paid "
               "out.")))
    return lines


def game_story(row, team_name="This team"):
    """One game, in plain sentences a non-basketball reader can follow.

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
         f"took <b>{abs(row['fga_gap'])} "
         f"{'more' if row['fga_gap'] > 0 else 'fewer'}</b> "
         f"shot{'s' if abs(row['fga_gap']) != 1 else ''} than the opponent "
         f"(<b>{row['fga']}</b> to {row['opp_fga']}). Where the gap came from: "
         f"<b>{row['orb']}</b> offensive rebounds to {row['opp_orb']}, and "
         f"<b>{row['tov']}</b> turnovers to {row['opp_tov']}"),
        ("Shot selection", row["quality"],
         f"the looks created were "
         f"{'better' if row['quality'] > 0 else 'worse'} than the opponent's, "
         f"before anything went in: this team's attempts were worth "
         f"<b>{row['xpts']:.0f}</b> points, the opponent's "
         f"<b>{row['opp_xpts']:.0f}</b>, on "
         f"{row['fga']} and {row['opp_fga']} shots"),
        ("Shot-making", row["making"],
         f"the ball went in "
         f"{'more' if row['making'] > 0 else 'less'} than those looks were "
         f"worth. This team scored <b>{row['pts_fg']:.0f}</b> from the field "
         f"against <b>{row['xpts']:.0f}</b> expected, so "
         f"<b>{us_make:+.0f}</b>; the opponent scored "
         f"<b>{row['opp_pts_fg']:.0f}</b> against "
         f"<b>{row['opp_xpts']:.0f}</b>, so <b>{them_make:+.0f}</b>. One side "
         f"shooting above its looks and the other below both push the margin "
         f"the same way, which is why the two combine to "
         f"<b>{row['making']:+.0f}</b> rather than cancelling"),
        ("Free throws", float(row["ft_margin"]),
         f"the free-throw line was worth <b>{abs(row['ft_margin'])}</b> point"
         f"{'s' if abs(row['ft_margin']) != 1 else ''} "
         + ("to this team" if row["ft_margin"] > 0 else "to the opponent")),
    ]
    terms.sort(key=lambda t: -abs(t[1]))
    return [(lbl, pts, txt) for lbl, pts, txt in terms if abs(pts) >= 0.5]
