"""Tests for helpers/scheme_situational.py — the "when does a look spike" engine.

The headline test is the OWN-GAMES GATE. On the defense side the selector is
"the shooter isn't us", which on a league-wide event list silently matches every
possession in the league — including games the team never played. The first cut
of this engine had that bug: every team returned an identical baseline and the
league reported more teams-with-tendencies than it has teams. It reads as
plausible output, so only a test that puts a team in ONE game and other teams in
another catches it.
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


def _shot(team, defense, q="1", clock="7:00", gid=1, make=False, play_type=None):
    return {"event_type": "shot", "shot_result": "make" if make else "miss",
            "shot_type": 2, "shooter_team_id": team, "game_id": gid,
            "quarter": int(q), "time": clock, "defense": defense,
            "play_type": play_type, "primary_player_id": None}


def _played(team, gid=1, n=2):
    """Offensive possessions for `team` in `gid`.

    team_analytics.event_team_games derives a team's games from events where IT
    was the shooter, so a team must actually attack to be credited with the game
    it played. Real data always satisfies this (you can't play without shooting);
    synthetic fixtures have to say so explicitly.
    """
    return [_shot(team, None, clock=f"7:5{i}", gid=gid) for i in range(n)]


def test_own_games_gate():
    """A team's baseline must only count possessions from ITS OWN games."""
    import helpers.scheme_situational as SS

    # game 1: team 1 defends team 2, always man.
    # game 2: teams 3 v 4, always 2-3 zone — team 1 is nowhere near it.
    ev = _played(1, gid=1) + [_shot(2, "man", gid=1) for _ in range(40)]
    ev += _played(3, gid=2) + [_shot(4, "zone_23", gid=2) for _ in range(200)]

    r = SS.scheme_situational(1, ev, side="defense")
    ok(r["base_poss"] == 40,
       f"baseline counts only own-game possessions (got {r['base_poss']}, "
       "not 240 — the other game's zone must not leak in)")
    ok(set(r["base_rate"]) == {"man"},
       "a team that only played man shows only man in its mix")


def test_run_cut_spikes():
    """Zone off the bench while the opponent is on a run reads as a spike."""
    import helpers.scheme_situational as SS

    ev = _played(1)
    # 40 baseline man possessions, no run active (team 1 defending team 2)
    for i in range(40):
        ev.append(_shot(2, "man", clock=f"7:{i:02d}", gid=1))
    # team 2 goes on a 8-0 run (4 made shots), then team 1 switches to zone
    for i in range(4):
        ev.append(_shot(2, "man", clock=f"6:{i:02d}", gid=1, make=True))
    for i in range(20):
        ev.append(_shot(2, "zone_23", clock=f"5:{i:02d}", gid=1))

    r = SS.scheme_situational(1, ev, side="defense")
    ok(r["available"], "engine available with a real baseline")
    rows = {c["key"]: c for c in r["cuts"]}
    ok("after_run" in rows, "the after-a-run-against cut fired")
    tags = {x["tag"]: x for x in rows["after_run"]["rows"]}
    ok("zone_23" in tags and tags["zone_23"]["delta"] > 0,
       "zone spikes ABOVE the team's own baseline while the opponent runs")

    lines = SS.verdict_lines(r)
    ok(any("2-3 zone" in l["text"] for l in lines),
       "verdict line names the scheme in plain language")


def test_deadball_cut():
    """The BLOB/SLOB cut keys off the OFFENSE's set tag on the possession."""
    import helpers.scheme_situational as SS

    ev = _played(1) + [_shot(2, "zone_23", clock=f"7:{i:02d}", gid=1)
                       for i in range(40)]
    ev += [_shot(2, "man", clock=f"5:{i:02d}", gid=1, play_type="blob")
           for i in range(20)]

    r = SS.scheme_situational(1, ev, side="defense")
    rows = {c["key"]: c for c in r["cuts"]}
    ok("deadball" in rows, "the dead-ball cut fired off the play_type tag")
    tags = {x["tag"]: x for x in rows["deadball"]["rows"]}
    ok("man" in tags and tags["man"]["delta"] > 0,
       "man spikes on BLOB/SLOB vs the team's own baseline")


def test_untagged_excluded():
    """Untagged possessions must not read as a tendency in either direction."""
    import helpers.scheme_situational as SS

    ev = _played(1) + [_shot(2, "man", clock=f"7:{i:02d}", gid=1)
                       for i in range(30)]
    ev += [_shot(2, None, clock=f"6:{i:02d}", gid=1) for i in range(100)]

    r = SS.scheme_situational(1, ev, side="defense")
    ok(r["base_poss"] == 30,
       f"untagged possessions excluded from the baseline (got {r['base_poss']})")
    ok(set(r["base_rate"]) == {"man"},
       "no None/untagged bucket appears in the mix")


def test_deadball_cut_is_defense_only():
    """The dead-ball cut must not fire on the OFFENSE side.

    There the cut criterion (play_type is a BLOB/SLOB) is the very tag being
    measured, so it can only report "when they run a BLOB they run a BLOB" — a
    tautology that scores as an enormous spike and crowds out real findings.
    """
    import helpers.scheme_situational as SS

    ev = _played(1) + [_shot(1, "man", clock=f"7:{i:02d}", gid=1,
                            play_type="pnr") for i in range(40)]
    ev += [_shot(1, "man", clock=f"5:{i:02d}", gid=1, play_type="blob")
           for i in range(20)]

    off = SS.scheme_situational(1, ev, side="offense")
    ok(not any(c["key"] == "deadball" for c in off["cuts"]),
       "offense side has no dead-ball cut (it would be circular)")
    ok(not any("BLOB" in l["text"] and "dead ball" in l["text"]
               for l in SS.verdict_lines(off)),
       "no 'BLOB spikes on BLOB possessions' tautology in the verdict lines")


def test_thin_sample_gated():
    """A cut under MIN_CUT_POSS reports nothing rather than a loud fake spike."""
    import helpers.scheme_situational as SS

    ev = _played(1) + [_shot(2, "man", clock=f"7:{i:02d}", gid=1)
                       for i in range(40)]
    # a 3-possession "clutch" sample — 100% zone, but meaningless
    ev += [_shot(2, "zone_23", q="4", clock="0:30", gid=1) for _ in range(3)]

    r = SS.scheme_situational(1, ev, side="defense")
    ok(not any(c["key"] == "clutch" for c in r["cuts"]),
       f"a 3-possession clutch cut is suppressed (min {SS.MIN_CUT_POSS})")


if __name__ == "__main__":
    test_own_games_gate()
    test_run_cut_spikes()
    test_deadball_cut()
    test_deadball_cut_is_defense_only()
    test_untagged_excluded()
    test_thin_sample_gated()
    print(f"\nALL {PASSED} CHECKS PASSED")
