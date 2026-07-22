"""
charges.py — the charge: drawn and committed, per team and per player.

THE ENCODING. A charge is logged as a turnover AND a foul (the way an and-one is
a foul alongside a made shot). The **foul is the key**, because it is the row
that carries the tell:

    event_type == 'foul' AND play_type == 'other' AND defense == 'other'

Nothing else identifies it. Pairing a foul to a turnover by timestamp is NOT a
valid discriminator: play_type and defense are nullable by nature and go
unpopulated all the time, so "a foul next to a turnover" catches ordinary fouls.
Only the explicit other/other pair means charge. (On the current book 26 fouls
carry it; 11 of them have no turnover logged at the same clock at all, which is
exactly why timestamp pairing would not work.)

THE SIDES. Foul semantics (helpers/fouls.py): primary_player_id is the player
FOULED, secondary_player_id is the FOULER. On a charge the offensive player
commits the foul and the defender "draws" it, so:

    drawn     = primary_player_id    — the DEFENDER who took it
    committed = secondary_player_id  — the OFFENSIVE player who ran him over

Verified against the data rather than assumed: on every charge the two players
are on opposite teams, and where a paired turnover exists it is charged to the
foul's SECONDARY 14 times to 1 — i.e. the secondary is the one who lost the ball,
which is the offensive player.

DOUBLE COUNTING. A charge is already a personal foul against the offensive player
(stats.py charges PF to the fouler = secondary, which is correct here) and,
when logged, already a turnover. This module only ADDS the defensive read; it
does not re-penalise the offense. See player_ratings for the rating leaf.

Streamlit-free (pure python + sqlite).
"""
from __future__ import annotations

from collections import defaultdict

import helpers.stats as S
import helpers.team_analytics as TA


def is_charge(e):
    """True when this event is a charge — a foul tagged other/other.

    The single source of truth for the encoding. Everything else in the app that
    wants to know "was this a charge" must come through here.
    """
    return (e.get("event_type") == "foul"
            and e.get("play_type") == "other"
            and e.get("defense") == "other")


def charge_events(events):
    """Just the charges in `events`."""
    return [e for e in events if is_charge(e)]


def player_charges(events):
    """{player_id: {'drawn': n, 'committed': n}} over `events`.

    Only players who appear on a charge are keyed — a player with no charges is
    absent rather than present with zeros, so callers can tell "none" apart from
    "not tracked".
    """
    out = defaultdict(lambda: {"drawn": 0, "committed": 0})
    for e in charge_events(events):
        d, c = e.get("primary_player_id"), e.get("secondary_player_id")
        if d is not None:
            out[d]["drawn"] += 1
        if c is not None:
            out[c]["committed"] += 1
    return dict(out)


def team_charges(team_id, events, team_of=None):
    """{'drawn', 'committed', 'games', 'drawn_pg', 'committed_pg', 'net_pg'} for
    one team over its OWN games.

    Scoped through TA.event_team_games — on a league-wide event list an
    unscoped read would credit the team with charges from games it never played.
    """
    if team_of is None:
        team_of = _team_of()
    own = TA.event_team_games(team_id, events)
    drawn = committed = 0
    for e in charge_events(events):
        if e.get("game_id") not in own:
            continue
        if team_of.get(e.get("primary_player_id")) == team_id:
            drawn += 1
        if team_of.get(e.get("secondary_player_id")) == team_id:
            committed += 1
    n = max(len(own), 1)
    return {"drawn": drawn, "committed": committed, "games": len(own),
            "drawn_pg": drawn / n, "committed_pg": committed / n,
            "net_pg": (drawn - committed) / n}


def _team_of():
    from database.db import query
    return {p["id"]: p["team_id"] for p in query("SELECT id, team_id FROM players")}


def team_has_charges(team_id, events, team_of=None):
    """True when this team has ANY charge logged (either side) in its own games.

    The gate the rating leaf needs. Charge tagging is opt-in and rare, so most
    players hold a GENUINE zero rather than a None — and the rating system's
    "missing stats drop out of the weighted mean" protection does not fire on a
    real 0. Without this gate a team that simply doesn't tag charges would have
    every player scored as though they never drew one, i.e. penalised for a
    tagging gap rather than for their defense.
    """
    t = team_charges(team_id, events, team_of=team_of)
    return (t["drawn"] + t["committed"]) > 0


def charge_rate_map(events, game_ids=None):
    """{player_id: charges drawn per game} for every player on a team that tags
    charges; players on non-tagging teams are ABSENT (not zero).

    This is the shape player_ratings consumes: absent -> the leaf drops out of
    that player's weighted mean; present -> a real rate, including a real 0.0 for
    a player whose team tags charges and who has never drawn one.
    """
    from database.db import query
    if not events:
        return {}
    team_of = _team_of()
    pc = player_charges(events)

    # games played per player, from the lineup snapshots where available and the
    # event stream otherwise — the denominator for a per-game rate.
    gp = defaultdict(set)
    for e in events:
        gid = e.get("game_id")
        for k in ("primary_player_id", "secondary_player_id",
                  "rebound_by_id", "stolen_by_id"):
            pid = e.get(k)
            if pid is not None and gid is not None:
                gp[pid].add(gid)

    # which teams tag charges at all
    tagging = set()
    for e in charge_events(events):
        for k in ("primary_player_id", "secondary_player_id"):
            t = team_of.get(e.get(k))
            if t is not None:
                tagging.add(t)

    out = {}
    for pid, games in gp.items():
        if team_of.get(pid) not in tagging:
            continue                      # team doesn't tag charges -> no leaf
        n = len(games) or 1
        out[pid] = pc.get(pid, {}).get("drawn", 0) / n
    return out
