"""
test_badges.py — badge points + the badge-driven archetype layer (helpers/badges.py).

badge_archetype is pure (a badge list → a role), so the offense/defense tilt and
each named archetype are pinned with crafted badge hauls. A small award_badges
synthetic smoke confirms the awarding pipeline still runs.
"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import helpers.badges as BG


def _b(cat, tier, name="x"):
    return {"key": name, "name": name, "emoji": "", "cat": cat, "tier": tier,
            "pct": 90, "desc": ""}


def _arch(badges):
    return BG.badge_archetype(badges)["archetype"]


def test_badge_points_and_profile():
    hand = [_b("Shooting", "Gold"), _b("Defense", "Silver"), _b("Defense", "Bronze")]
    assert BG.badge_points(hand) == 5 + 3 + 1
    prof = BG.badge_profile(hand)
    assert prof["Shooting"] == 5 and prof["Defense"] == 4


def test_no_badges_is_role_player():
    assert _arch([]) == "Role Player"


def test_two_way_star_needs_both_ends_strong():
    # gold each side -> min(off,def)=5 -> star
    assert _arch([_b("Scoring", "Gold"), _b("Defense", "Gold")]) == "Two-Way Star"
    # gold offense + a single bronze defense -> NOT a star (weak side too light)
    assert _arch([_b("Scoring", "Gold"), _b("Defense", "Bronze")]) != "Two-Way Star"


def test_offensive_engine_vs_flamethrower_vs_floor_general():
    # scoring-led offense, negligible D -> Offensive Engine
    assert _arch([_b("Scoring", "Gold"), _b("Defense", "Bronze")]) == "Offensive Engine"
    # shooting is the top offensive category (>=3) -> Flamethrower
    assert _arch([_b("Shooting", "Gold"), _b("Shooting", "Silver")]) == "Flamethrower"
    # playmaking-led -> Floor General
    assert _arch([_b("Playmaking", "Gold")]) == "Floor General"


def test_defensive_anchor_vs_interior_anchor():
    # defense-led, no boards -> Defensive Anchor
    assert _arch([_b("Defense", "Gold")]) == "Defensive Anchor"
    # rebounding outweighs defense -> Interior Anchor
    assert _arch([_b("Rebounding", "Gold"), _b("Defense", "Bronze")]) == "Interior Anchor"


def test_modest_single_category_specialists():
    assert _arch([_b("Rebounding", "Bronze")]) == "Rebounder"
    assert _arch([_b("Two-Way", "Bronze")]) == "Glue Guy"


def test_archetype_carries_drivers_and_buckets():
    v = BG.badge_archetype([_b("Scoring", "Gold", "Bucket Getter"),
                            _b("Defense", "Gold", "Lockdown")])
    assert v["off"] == 5 and v["def"] == 5
    assert "Bucket Getter" in v["drivers"] and "Lockdown" in v["drivers"]


def test_award_badges_smoke():
    # two players; one elite scorer, one empty -> awarding runs, points sane
    table = {
        1: {"name": "star", "PPG": 25, "GP": 10, "3P%": 42, "3PA": 40, "FGA": 120,
            "TS%": 62, "eFG%": 60, "APG": 5, "RPG": 6, "SPG": 2, "BPG": 1,
            "OVERALL": 72, "2WAY": 70, "MPG": 30},
        2: {"name": "bench", "PPG": 1, "GP": 3, "FGA": 4, "OVERALL": 40, "MPG": 5},
    }
    aw = BG.award_badges(table)
    assert set(aw) == {1, 2}
    assert BG.badge_points(aw[1]) >= BG.badge_points(aw[2])


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for f in fns:
        try:
            f()
            ok += 1
            print(f"  ok  {f.__name__}")
        except Exception as ex:
            print(f"  FAIL {f.__name__} -> {ex!r}")
            traceback.print_exc()
    print(f"\n{ok}/{len(fns)} badge checks passed")
