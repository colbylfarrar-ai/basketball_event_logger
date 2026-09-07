"""If the coach tracked it, they get to see it. (B3)

`games.tracked_by` records who logged a game and was read by exactly one thing —
`recompute_game_pool`, which decides what to SHARE. Nothing ever asked it what
its author may READ. Measured on production:

    tracked games                                    63
    own-TEAM games (team 1)                          26
    games this coach LOGGED                          48
    logged but NOT their own team                    37
      ...and not pooled either                       32   <- invisible to them

51% of the book was typed in by one person and cannot be read back by them as a
Paid Solo coach. It is the largest gating number in THE BOOK, and it grew with
tracking: 14 of 43 on the stale copy, 32 of 63 on production.

The founder's ruling (Q3): "If the coach tracked it, they get to see it. If they
track a scout game, they see it, nobody else does. If they are in the co-op and
they track a scout game, everyone gets it in the co-op." The co-op half already
works — `recompute_game_pool` pools a game whose logging coach's team is
League-wide. This is the other half.

KEYED ON THE STAFF, NOT ON ONE EMAIL (§9.2.1). Measured, one email would recover
100% of today's book, because every attributed game carries the same gmail
address. It is still the wrong rule for October, for three reasons THE BOOK
spells out: the founder works from two accounts, four people already staff team
1, and Q3's own words about the co-op are the same idea one level down. So the
rule is every email that staffs any of the viewer's teams:

    tracked_by IN (SELECT coach_email FROM coach_teams WHERE team_id IN :my_teams)

plus the viewer's own address, so a scout with no program of their own can still
read what they logged.

THE ONE DECISION Q3 DID NOT COVER, made here rather than left to accident:
does a Solo coach's scout game become visible to their ASSISTANTS, or only to
themselves? This implements assistants, which is THE BOOK's own recommendation
(§9.2.1: "they are the same staff room") and the reading the coach_teams join
gives for free. Reversing it means dropping the join and keying on the signed-in
address alone.

Run: python -m pytest tracker/test_own_creation.py
"""
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_owncreate_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                          # noqa: E402
import database.db as DB                               # noqa: E402
from database.db import execute                        # noqa: E402
import helpers.entitlement as ENT                      # noqa: E402

DB.initialize_database()


@pytest.fixture(autouse=True)
def _this_modules_db():
    # The collection hazard test_read_filter_empty_scope.py documents: the LAST
    # module to set APP5_DATA_DIR at import time wins for the whole run.
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


HEAD = "head@adair.example"          # head coach, team MINE
ASSIST = "assist@adair.example"      # assistant on the same team
SCHOOL = "head@school.example"       # the same person's second account
OTHER = "other@elsewhere.example"    # a coach at a different program


def _seed():
    mine = execute("INSERT INTO teams (name, class, gender, shares_pool) "
                   "VALUES ('Mine','3A','F',0)")               # Solo
    them = execute("INSERT INTO teams (name, class, gender) VALUES ('Them','3A','F')")
    third = execute("INSERT INTO teams (name, class, gender) VALUES ('Third','3A','F')")
    elsewhere = execute("INSERT INTO teams (name, class, gender) "
                        "VALUES ('Elsewhere','3A','F')")
    for email, tid in ((HEAD, mine), (ASSIST, mine), (SCHOOL, mine),
                       (OTHER, elsewhere)):
        execute("INSERT INTO app_users (email, plan, role) VALUES (?,'paid','coach')",
                (email,))
        execute("INSERT INTO coach_teams (coach_email, team_id) VALUES (?,?)",
                (email, tid))

    # Each game gets its own DATE. Four tracks of the same matchup on the same
    # day are what `game_dedup` exists to collapse — it would keep one canonical
    # row and the fixture would be testing the deduper, not the gate.
    def _game(t1, t2, by, day, in_pool=0):
        return execute(
            "INSERT INTO games (team1_id,team2_id,date,tracked,season,"
            "home_score,away_score,tracked_by,in_pool) "
            f"VALUES (?,?,'2026-01-{day:02d}',1,'Current',50,40,?,?)",
            (t1, t2, by, in_pool))

    return {
        "mine": mine, "them": them, "third": third, "elsewhere": elsewhere,
        # the head coach's own team game — visible today by team membership
        "own_team": _game(mine, them, HEAD, 10),
        # a scout game they LOGGED between two OTHER teams — the 32 of 63
        "scouted": _game(them, third, HEAD, 11),
        # the same, logged from their school address
        "scouted_school": _game(them, third, SCHOOL, 12),
        # a scout game their ASSISTANT logged — the same staff room
        "scouted_assist": _game(them, third, ASSIST, 13),
        # someone else's scout game, not pooled — must stay invisible
        "strangers": _game(them, third, OTHER, 14),
    }


_G = _seed()


def _ident(email, team_ids, league_wide=False):
    return {"email": email, "role": "coach", "plan": "paid",
            "team_ids": list(team_ids), "team_id": (list(team_ids) or [None])[0],
            "shares_pool": 1 if league_wide else 0}


def test_a_solo_coach_can_read_the_scout_game_they_typed_in():
    """The headline number: 32 of 63 games on production, invisible to the
    person who logged them."""
    vis = ENT.visible_tracked_game_ids(_ident(HEAD, [_G["mine"]]), season="Current")
    assert _G["scouted"] in vis, (
        "the coach who logged this game still cannot read it")
    assert _G["own_team"] in vis          # unchanged


def test_a_strangers_unpooled_scout_game_stays_invisible():
    """The rule gives the AUTHOR their data back. It must not open anyone
    else's — that is the co-op's job, and it is opt-in."""
    vis = ENT.visible_tracked_game_ids(_ident(HEAD, [_G["mine"]]), season="Current")
    assert _G["strangers"] not in vis


def test_the_second_email_of_the_same_staff_sees_it():
    """The two-email constraint (§9.2.1). Both addresses staff team 1, so a game
    logged from either is readable from either — which is what stops a game
    landing on the school account from being stranded in October."""
    vis = ENT.visible_tracked_game_ids(_ident(SCHOOL, [_G["mine"]]), season="Current")
    assert _G["scouted"] in vis, "the gmail-logged game is invisible from the school account"
    assert _G["scouted_school"] in vis


def test_an_assistant_on_the_same_team_sees_it():
    """The decision §9.2.1 flagged and Q3 did not cover: same staff room, same
    scouting. Reversing this means keying on the signed-in address alone."""
    vis = ENT.visible_tracked_game_ids(_ident(ASSIST, [_G["mine"]]), season="Current")
    assert _G["scouted"] in vis
    assert _G["scouted_assist"] in vis


def test_a_coach_at_another_program_sees_none_of_it():
    """`coach_teams` is the boundary. Sharing across programs is the co-op."""
    vis = ENT.visible_tracked_game_ids(_ident(OTHER, [_G["elsewhere"]]),
                                       season="Current")
    for key in ("own_team", "scouted", "scouted_school", "scouted_assist"):
        assert _G[key] not in vis, key


def test_the_scouted_teams_dashboard_shows_the_games_this_coach_logged():
    """A Solo coach who scouted Them four times should see Them's depth from
    those four games — the read-filter, not just the game list."""
    ids = ENT.team_visible_tracked_ids(_ident(HEAD, [_G["mine"]]), _G["them"],
                                       season="Current")
    assert ids is not None
    assert _G["scouted"] in ids
    assert _G["strangers"] not in ids


def test_the_gate_opens_for_a_team_this_coach_has_tracked():
    """`tracked_gate` said "not shared" for a team the viewer had scouted
    themselves — a neutral, wrong answer over their own work."""
    visible, msg = ENT.tracked_gate(_ident(HEAD, [_G["mine"]]), _G["them"],
                                    True, season="Current")
    assert visible and msg is None, msg


def test_a_game_the_coach_logged_opens_its_own_depth():
    """The per-GAME gate, which the box score's DEPTH stage consults."""
    assert ENT.can_see_game_tracked(
        _ident(HEAD, [_G["mine"]]), _G["them"], _G["third"],
        in_pool=0, game_id=_G["scouted"])
    assert not ENT.can_see_game_tracked(
        _ident(HEAD, [_G["mine"]]), _G["them"], _G["third"],
        in_pool=0, game_id=_G["strangers"])


def test_a_banned_coach_does_not_get_their_scouting_back():
    """Moderation outranks authorship.

    A pool-banned coach is forced Solo and `tracked_gate` hands them a
    suspension notice. Own-creation must not become the way around that — the
    first version of this rule sat above the ban branch and turned the notice
    into full depth, which `tracker/test_entitlement.py` caught.

    Q3 did not rule on ban x own-creation. Whether a ban revokes READING your
    own tracked work or only SHARING it is a real question; this is the
    conservative answer, and it keeps the moderation contract that already had a
    test around it."""
    banned = _ident(HEAD, [_G["mine"]])
    banned["pool_banned"] = 1
    assert ENT.own_created_game_ids(banned, "Current") == set()
    visible, msg = ENT.tracked_gate(banned, _G["them"], True, season="Current")
    assert not visible and "suspend" in (msg or "").lower(), msg


def test_an_unattributed_game_is_not_claimed_by_anyone():
    """Q3: empty `tracked_by` needs no attribution. It must not match a viewer
    whose staff list happens to contain an empty string."""
    orphan = execute(
        "INSERT INTO games (team1_id,team2_id,date,tracked,season,"
        "home_score,away_score,tracked_by,in_pool) "
        "VALUES (?,?,'2026-01-20',1,'Current',50,40,'',0)",
        (_G["them"], _G["third"]))
    vis = ENT.visible_tracked_game_ids(_ident(HEAD, [_G["mine"]]), season="Current")
    assert orphan not in vis
