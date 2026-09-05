"""Rotation watch: the LIVE half of star_coverage.

`star_coverage` has always answered "over the season you bleed X/100 in the
minutes neither key player is on". That is a planning read, and the decision it
implies gets made during a game with a clock running -- nothing told a coach
they were three minutes into exactly those minutes. `live_star_watch` is that
read at a point in time, and the Game Tracker's Rotation watch panel shows it.

Two things it must get right:
  * the star set comes from the team's OTHER games, so a live game's partial
    minutes cannot decide who counts as a star; and
  * "off together" means the union of their stints, not any one player's.

Run with the REAL interpreter, not the Store shim:
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/test_live_star_watch.py
"""
import os
import sys

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP)

PASSED = 0


def ok(cond, label):
    global PASSED
    assert cond, label
    PASSED += 1
    print(f"  ok  {label}")


def _busiest_team():
    from database.db import query
    r = query("""SELECT t.id, t.name, COUNT(*) n FROM games g
                 JOIN teams t ON t.id IN (g.team1_id, g.team2_id)
                 WHERE g.tracked=1 GROUP BY t.id ORDER BY n DESC LIMIT 1""")
    if not r:
        return None, None, []
    tid = r[0]["id"]
    gids = [x["id"] for x in query(
        """SELECT id FROM games WHERE tracked=1
           AND (team1_id=? OR team2_id=?) ORDER BY id""", (tid, tid))]
    return tid, r[0]["name"], gids


def test_reads_a_real_game():
    import helpers.rotation_plan as RP

    tid, name, gids = _busiest_team()
    if not gids or len(gids) < 3:
        print("  -- not enough tracked games; skipped")
        return

    gid = gids[-1]
    sw = RP.live_star_watch(tid, gid, 600.0)
    ok(sw["stars"], f"{name}: picked key players from the other games "
                    f"({[s.get('name') for s in sw['stars']]})")
    ok(all(s["pid"] for s in sw["stars"]), "every star row carries a pid")
    ok(sw["risk"] in ("low", "note", "alert"), f"risk is a known tier ({sw['risk']})")
    ok(sw["note"], "a live read always says something")
    ok(sw["off_secs"] >= 0, "off_secs is never negative")
    ok(not (sw["on"] and sw["off_secs"]),
       "a star on the floor means nobody has been off")


def test_the_season_scope_survives_a_rollover():
    """The default pool is the GAME'S season, not the 'Current' sentinel.

    stats._team_game_ids hardcodes season='Current', which holds no games at all
    right after a rollover -- a default scoped to it would report that a team has
    no key players rather than reading the season the game belongs to.
    """
    import helpers.rotation_plan as RP
    import helpers.stats as S
    from database.db import query

    tid, _name, gids = _busiest_team()
    if not gids:
        print("  -- no tracked games; skipped")
        return

    gid = gids[-1]
    scoped = RP._tracked_games_in_season_of(tid, gid)
    season = query("SELECT season FROM games WHERE id=?", (gid,))[0]["season"]
    ok(gid in scoped, f"the game itself is in its own season pool ({season})")
    ok(len(scoped) == len(gids),
       f"every tracked game for this team is in one season ({len(scoped)})")

    if not S._team_game_ids(tid):
        ok(RP.live_star_watch(tid, gid, 600.0)["stars"],
           "still finds key players even though the 'Current' pool is empty")
    else:
        print("  -- the active season has games, so the trap is not live here")


def test_off_together_is_the_union():
    """A star subbing out alone must not start the clock."""
    import helpers.rotation_plan as RP
    import helpers.gameflow as GF

    tid, _name, gids = _busiest_team()
    if len(gids) < 3:
        return

    for gid in gids:
        rot = GF.rotation(gid)
        end = rot["end"] or 0
        if end < 600:
            continue
        # Walk the game and check the claim at every point we sample.
        bad = 0
        for t in range(60, int(end), 60):
            sw = RP.live_star_watch(tid, gid, float(t))
            starset = {s["pid"] for s in sw["stars"]}
            if not starset:
                break
            live = set()
            for r in rot["teams"].get(tid, []):
                if r["player_id"] in starset and any(
                        s <= t <= e for s, e in r["segments"]):
                    live.add(r["player_id"])
            if bool(live) != bool(sw["on"]):
                bad += 1
        ok(bad == 0, f"game {gid}: 'on the floor' matches the stints at every "
                     f"sampled minute")
        return


def test_thresholds_are_ordered():
    import helpers.rotation_plan as RP
    ok(0 < RP.STARS_OFF_NOTE_SECS < RP.STARS_OFF_ALERT_SECS,
       f"note ({RP.STARS_OFF_NOTE_SECS}s) fires before alert "
       f"({RP.STARS_OFF_ALERT_SECS}s)")


if __name__ == "__main__":
    print("live star watch")
    test_reads_a_real_game()
    test_the_season_scope_survives_a_rollover()
    test_off_together_is_the_union()
    test_thresholds_are_ordered()
    print(f"\n{PASSED} checks passed")
