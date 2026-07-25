"""
involvement.py — how often a player has a FINGERPRINT on their team's scores.

Spec Part 4d, lifted from soccer's build-up involvement. The question a coach
asks about a role player and cannot currently answer: *when we score, how often
did she have something to do with it?* A 4-point-per-game guard who screens,
feeds and crashes can be involved in half her team's baskets, and every
box-derived stat in the app will call her invisible.

THE DENOMINATOR IS THE WHOLE DESIGN
-----------------------------------
The obvious version — fingerprints divided by the team's total scores — is a
minutes stat wearing a percentage. A starter is on the floor for more scores, so
she "is involved in more of them", and the leaderboard just re-ranks the
rotation. Useless.

So the denominator here is **team scoring plays WHILE THAT PLAYER WAS ON THE
FLOOR**, read from the per-event lineup snapshots. That makes it a genuine rate:
a bench player who touches half the baskets during her twelve minutes reads
higher than a starter who touches a third of hers, which is the comparison worth
making. Minutes are still visible as the denominator itself, so nobody has to
guess at the sample.

WHAT COUNTS AS A FINGERPRINT
----------------------------
On a made field goal: the scorer, the passer (`pass_from_id`), the screener
(`shot_created_by_id`), and the hockey passer (`hockey_from_id`). On a made free
throw: the shooter only. Plus SECOND-CHANCE credit — the rebounder whose
offensive board directly preceded the score with no change of possession in
between.

Each is credited AT MOST ONCE per scoring play, so a player who both screened
and rebounded on the same basket counts once. The stat is "did you touch it",
not "how many ways".

HONESTY
-------
  * Screens and hockey assists are OPT-IN tags. A team that does not tag them
    will read lower on involvement than a team that does, and that is a capture
    difference, not a play difference. `tag_dependence` reports what share of a
    player's credits came from optional tags so the surface can say so.
  * Free-throw scores can only ever credit the shooter, which structurally
    depresses everyone else. Reported separately rather than hidden.
  * This is a PARTICIPATION rate, not a value stat. Touching the ball on a
    basket is not the same as causing it, and nothing here should be phrased as
    though it were.

Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S
from helpers.lineups import _event_floor

#: On-floor scoring plays below this and the rate is noise. A high-school team
#: scores roughly 20-25 field goals a game, so this is about two games of floor
#: time for a rotation player.
MIN_PLAYS = 25

#: Optional-tag share above this and the surface should caption the read as
#: tagging-dependent rather than comparable across teams.
TAG_DEPENDENCE_WARN = 0.35


def _scoring_plays(events):
    """Yield (event, team_id, credits, tagged_credits) per made scoring play.

    `credits` is the set of players with a fingerprint; `tagged_credits` is the
    subset that came from an OPTIONAL tag (screen or hockey assist), which is
    what `tag_dependence` later reports on.

    Second-chance credit walks BACKWARDS from the score to the most recent
    offensive rebound, stopping at any event involving the other team or at a
    previous score. That keeps "her board became points" to the possession it
    actually happened on, rather than smearing it across a quarter.
    """
    by_game = defaultdict(list)
    for e in events:
        if e.get("game_id") is not None:
            by_game[e["game_id"]].append(e)

    for _gid, evs in by_game.items():
        evs = sorted(evs, key=lambda r: r["id"])
        for i, e in enumerate(evs):
            if e["shot_result"] != "make":
                continue
            team = e.get("shooter_team_id")
            scorer = e.get("primary_player_id")
            if team is None or scorer is None:
                continue
            is_ft = e["event_type"] == "free_throw"
            if e["event_type"] not in ("shot", "free_throw"):
                continue

            credits = {scorer}
            tagged = set()
            if not is_ft:
                for key, optional in (("pass_from_id", False),
                                      ("shot_created_by_id", True),
                                      ("hockey_from_id", True)):
                    pid = e.get(key)
                    if pid is None:
                        continue
                    credits.add(pid)
                    if optional:
                        tagged.add(pid)

                # second chance: walk back to an offensive board on this trip
                for j in range(i - 1, max(-1, i - 12), -1):
                    p = evs[j]
                    if p.get("shooter_team_id") not in (None, team):
                        break                      # other team touched it
                    if p["shot_result"] == "make":
                        break                      # previous trip ended scoring
                    reb = p.get("rebound_by_id")
                    if reb is not None:
                        # an OREB is a board collected by the shooting team
                        if p.get("shooter_team_id") == team:
                            credits.add(reb)
                        break
            yield e, team, credits, tagged


def player_involvement(game_ids=None, events=None, floor=None, team_id=None):
    """{pid: {plays_on, involved, rate, as_scorer, as_passer, as_screener,
    as_hockey, as_rebounder, tagged, tag_dependence, team_id}}.

    `plays_on` is the team's scoring plays while the player was ON THE FLOOR —
    the denominator that turns this from a minutes stat into a rate. Players
    below MIN_PLAYS are returned but flagged by their own `plays_on`, so a
    caller can gate without re-deriving anything.
    """
    if events is None:
        events = S.fetch_events(game_ids)
    if floor is None:
        floor = _event_floor(game_ids)

    agg = defaultdict(lambda: {
        "plays_on": 0, "involved": 0, "as_scorer": 0, "as_passer": 0,
        "as_screener": 0, "as_hockey": 0, "as_rebounder": 0, "tagged": 0,
        "team_id": None})

    for e, team, credits, tagged in _scoring_plays(events):
        if team_id is not None and team != team_id:
            continue
        on = (floor.get(e["id"]) or {}).get(team) or frozenset()
        for pid in on:
            a = agg[pid]
            a["plays_on"] += 1
            a["team_id"] = team
        for pid in credits:
            a = agg[pid]
            a["team_id"] = a["team_id"] or team
            # only count involvement for players the lineup says were on the
            # floor; a credit without a snapshot would push rate above 100%
            if pid in on:
                a["involved"] += 1
            if pid in tagged:
                a["tagged"] += 1
        if e.get("primary_player_id") in on:
            agg[e["primary_player_id"]]["as_scorer"] += 1
        for key, slot in (("pass_from_id", "as_passer"),
                          ("shot_created_by_id", "as_screener"),
                          ("hockey_from_id", "as_hockey")):
            pid = e.get(key)
            if pid is not None and pid in on:
                agg[pid][slot] += 1
        # rebounder credit is whatever second-chance added beyond the named slots
        named = {e.get("primary_player_id"), e.get("pass_from_id"),
                 e.get("shot_created_by_id"), e.get("hockey_from_id")}
        for pid in credits - named:
            if pid in on:
                agg[pid]["as_rebounder"] += 1

    out = {}
    for pid, a in agg.items():
        if not a["plays_on"]:
            continue
        a["rate"] = round(100.0 * a["involved"] / a["plays_on"], 1)
        a["tag_dependence"] = (round(a["tagged"] / a["involved"], 3)
                               if a["involved"] else 0.0)
        out[pid] = a
    return out


def team_tag_dependence(rows):
    """Share of all involvement credits across the roster that came from an
    OPTIONAL tag. The number a surface needs before it lets one team's
    involvement be compared with another's."""
    inv = sum(r["involved"] for r in rows.values())
    tag = sum(r["tagged"] for r in rows.values())
    return (tag / inv) if inv else 0.0


def involvement_verdict(rows, names=None, min_plays=MIN_PLAYS):
    """[(badge, n, html)] for helpers.cards.verdict_card.

    Leads with the player whose involvement most OUTRUNS their scoring, because
    that is the read no box score gives — the glue player the stat sheet calls
    quiet. Silent when the sample cannot carry it.
    """
    def nm(pid):
        return (names or {}).get(pid, f"#{pid}")

    elig = {p: r for p, r in rows.items() if r["plays_on"] >= min_plays}
    if not elig:
        return []
    lines = []

    top = max(elig.items(), key=lambda kv: kv[1]["rate"])
    pid, r = top
    lines.append((
        "Most involved", r["plays_on"],
        f"<b>{nm(pid)}</b> has a hand in <b>{r['rate']:.0f}%</b> of the "
        f"baskets scored while she is on the floor "
        f"({r['involved']} of {r['plays_on']})."))

    # The glue read: involved a lot, scoring little of it themselves. Ranked by
    # the COUNT of non-scoring involvement rather than by rate — ranking on rate
    # hands the line to whoever has the thinnest sample (on the live book that
    # was a 16-touch reserve over a 39-touch distributor).
    glue = [(p, x) for p, x in elig.items()
            if x["involved"] >= 8 and x["as_scorer"] < 0.45 * x["involved"]]
    if glue:
        gp, gr = max(glue, key=lambda kv: kv[1]["involved"] - kv[1]["as_scorer"])
        other = gr["involved"] - gr["as_scorer"]
        lines.append((
            "Glue", gr["plays_on"],
            f"<b>{nm(gp)}</b> is in on <b>{gr['rate']:.0f}%</b> of them but "
            f"scores only <b>{gr['as_scorer']}</b> — {other} of her "
            f"{gr['involved']} touches are passes, screens and second "
            f"chances. The box score will not show this."))

    dep = team_tag_dependence(elig)
    if dep >= TAG_DEPENDENCE_WARN:
        lines.append((
            "Tagging", int(round(dep * 100)),
            f"<b>{dep * 100:.0f}%</b> of these credits come from optional "
            f"screen and hockey-assist tags, so these rates are not comparable "
            f"with a team that does not tag them."))
    return lines
