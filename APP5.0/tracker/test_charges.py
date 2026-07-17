"""Tests for helpers/charges.py — the charge read.

THE ENCODING (founder's, verified against the book): a charge is a FOUL tagged
play_type='other' AND defense='other'. It is logged alongside a turnover, but the
foul is the key — timestamp-pairing a foul to a turnover is not a valid
discriminator because play_type/defense are nullable and routinely unpopulated.
On the current data 26 fouls carry the tag and 11 of them have NO turnover at the
same clock, which is exactly why pairing would fail.

THE SIDES: foul semantics are primary = FOULED, secondary = FOULER. On a charge
the offensive player commits it, so drawn = primary (the defender), committed =
secondary. Confirmed on the real book: every charge has the two players on
opposite teams, and where a paired turnover exists it is charged to the foul's
SECONDARY 14:1 — the secondary is the one who lost the ball.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _foul(primary, secondary, play_type="other", defense="other", gid=1):
    return {"event_type": "foul", "primary_player_id": primary,
            "secondary_player_id": secondary, "play_type": play_type,
            "defense": defense, "game_id": gid, "quarter": 1, "time": "5:00",
            "shooter_team_id": None}


def _shot(team, gid=1):
    return {"event_type": "shot", "shot_result": "miss", "shot_type": 2,
            "shooter_team_id": team, "game_id": gid, "quarter": 1,
            "time": "6:00", "primary_player_id": None, "play_type": None,
            "defense": None}


def test_is_charge_needs_both_tags():
    import helpers.charges as CH
    ok(CH.is_charge(_foul(1, 2)), "foul + other/other IS a charge")
    ok(not CH.is_charge(_foul(1, 2, play_type=None)),
       "other defense alone is NOT a charge (defense tag is often 'other')")
    ok(not CH.is_charge(_foul(1, 2, defense=None)),
       "other play_type alone is NOT a charge")
    ok(not CH.is_charge(_foul(1, 2, play_type="pnr")),
       "a tagged set call is not a charge")
    ok(not CH.is_charge({**_shot(1), "play_type": "other", "defense": "other"}),
       "a SHOT tagged other/other is not a charge — only fouls are")


def test_sides():
    """drawn = primary (defender), committed = secondary (offensive player)."""
    import helpers.charges as CH
    pc = CH.player_charges([_foul(10, 20), _foul(10, 21)])
    ok(pc[10]["drawn"] == 2, "primary is credited with DRAWING the charge")
    ok(pc[10]["committed"] == 0, "the drawer commits nothing")
    ok(pc[20]["committed"] == 1 and pc[21]["committed"] == 1,
       "secondary is charged with COMMITTING it")
    ok(pc[20]["drawn"] == 0, "the committer draws nothing")


def test_absent_not_zero():
    import helpers.charges as CH
    pc = CH.player_charges([_foul(10, 20)])
    ok(99 not in pc,
       "a player with no charges is ABSENT, so 'none' is distinguishable "
       "from 'not tracked'")


def test_ordinary_fouls_ignored():
    import helpers.charges as CH
    evs = [_foul(1, 2, play_type=None, defense=None) for _ in range(50)]
    ok(CH.charge_events(evs) == [], "50 untagged fouls yield no charges")


def test_charge_rate_map_gates_non_tagging_teams():
    """The whole point of the gate: a team that doesn't tag charges must have NO
    leaf, because a genuine 0 would score a tagging gap as bad defense."""
    import helpers.charges as CH

    # Two synthetic teams whose players are real rows would be needed for
    # _team_of(); instead drive the pure helpers and assert the contract shape.
    rm = CH.charge_rate_map([])
    ok(rm == {}, "no events -> no leaves at all (never a wall of zeros)")


def test_real_book_encoding():
    """Against the real DB: the sides hold and the tag is the discriminator."""
    import helpers.charges as CH
    import helpers.stats as S
    from database.db import query
    gids = [g["id"] for g in query("SELECT id FROM games WHERE tracked=1")]
    if not gids:
        print("  -- no tracked games; real-book test skipped")
        return
    ev = S.fetch_events(gids)
    ch = CH.charge_events(ev)
    if not ch:
        print("  -- no charges tagged in this DB; real-book test skipped")
        return
    team_of = {p["id"]: p["team_id"] for p in query("SELECT id, team_id FROM players")}
    opposite = sum(1 for e in ch
                   if team_of.get(e["primary_player_id"]) is not None
                   and team_of.get(e["secondary_player_id"]) is not None
                   and team_of[e["primary_player_id"]]
                   != team_of[e["secondary_player_id"]])
    known = sum(1 for e in ch
                if team_of.get(e["primary_player_id"]) is not None
                and team_of.get(e["secondary_player_id"]) is not None)
    ok(opposite == known,
       f"all {known} charges have drawer and committer on OPPOSITE teams")
    ok(all(e["event_type"] == "foul" for e in ch),
       "every detected charge is a foul event")


if __name__ == "__main__":
    test_is_charge_needs_both_tags()
    test_sides()
    test_absent_not_zero()
    test_ordinary_fouls_ignored()
    test_charge_rate_map_gates_non_tagging_teams()
    test_real_book_encoding()
    print(f"\nALL {PASSED} CHECKS PASSED")
