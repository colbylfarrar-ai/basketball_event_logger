"""
xA2 — secondary expected assists (spec Part 1 §4). Synthetic events, no DB.

Two invariants carry this file:

1. xA2 is MAKE-INDEPENDENT, like xA. `hockey_from_id` is captured on every shot
   flow, so xA2 sums over ALL tagged chains rather than conditioning on the
   finish. An earlier draft of the spec modelled it as a make-conditioned
   floor; that was wrong about the capture, and this pins the correction.

2. xA2 NEVER touches xA. `xA/G` is a gate-adopted rating leaf (0.75, #8d), so
   folding secondary credit into it would change an adopted rating with no
   gate. They are separate stats with separate keys.

Run: python tracker/test_xa2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.stats as S                          # noqa: E402
import helpers.player_ratings as PR                # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


IGN, AST_, SHOOTER = 11, 12, 13


def shot(made, hockey=IGN, passer=AST_, stype=2, gid=1, zone="C"):
    return {"event_type": "shot", "game_id": gid,
            "shot_result": "make" if made else "miss", "shot_type": stype,
            "primary_player_id": SHOOTER, "pass_from_id": passer,
            "hockey_from_id": hockey, "shot_created_by_id": None,
            "shooter_team_id": 1, "rebound_by_id": None,
            "rebounder_team_id": None, "guarded_by_id": None, "zone": zone,
            "blocked_by_id": None, "secondary_player_id": None,
            "stolen_by_id": None, "play_type": None, "defense": None,
            "turnover_type": None, "period": 1, "assist_type": None}


print("make-independence (the correction to the earlier draft)")

# Same look, same count, opposite outcomes. If xA2 were make-conditioned these
# two would differ; the whole point is that they must not.
_made = [shot(True) for _ in range(6)]
_missed = [shot(False) for _ in range(6)]
# Pool the rate table over one combined book so both runs price the same look.
_rates = S.shot_quality_rates(events=_made + _missed)

xa_made = S.expected_assists_secondary(events=_made, rates=_rates)[IGN]
xa_miss = S.expected_assists_secondary(events=_missed, rates=_rates)[IGN]
ok(abs(xa_made["xA2"] - xa_miss["xA2"]) < 1e-9,
   f"6 made and 6 missed chains earn the SAME xA2 "
   f"({xa_made['xA2']:.3f} vs {xa_miss['xA2']:.3f})")
ok(xa_made["HAST"] == 6 and xa_miss["HAST"] == 0,
   "...while HAST correctly splits 6 vs 0 (it is a sibling of AST)")
ok(xa_made["PotHAST"] == xa_miss["PotHAST"] == 6,
   "PotHAST counts both books equally — the capture measure")

print("credit share and shot value")

_one = S.expected_assists_secondary(events=[shot(True)], rates=_rates)[IGN]
_rate = _rates.get(("C", "pass", False), {}).get("pct", 0.0)
ok(abs(_one["xA2"] - S.XA2_CREDIT * _rate) < 1e-9,
   f"xA2 is exactly XA2_CREDIT x the look's make-rate "
   f"({S.XA2_CREDIT} x {_rate:.3f})")
ok(S.XA2_CREDIT == 0.5,
   "the second passer gets half: they made the advantage, the assister "
   "still had to deliver it")
_three = S.expected_assists_secondary(
    events=[shot(True, stype=3)], rates=_rates)[IGN]
ok(abs(_three["xA2_pts"] - _three["xA2"] * 3) < 1e-9,
   "xA2_pts follows shot value, so feeding threes is not flattened")
ok(abs(_one["xA2_pts"] - _one["xA2"] * 2) < 1e-9, "...and twos price as twos")

print("credit lands on the SECOND passer only")

_res = S.expected_assists_secondary(events=_made, rates=_rates)
ok(IGN in _res, "the hockey passer earns xA2")
ok(AST_ not in _res, "the assister earns NO xA2 — their credit is xA")
ok(SHOOTER not in _res, "the shooter earns no xA2")
ok(S.expected_assists_secondary(
    events=[shot(True, hockey=None)], rates=_rates) == {},
   "an untagged shot produces no xA2 at all")

print("xA is untouched (it is a gate-adopted leaf)")

_xa = S.expected_assists(events=_made, rates=_rates)
ok(AST_ in _xa and IGN not in _xa,
   "xA still credits the ASSISTER only — no secondary credit leaked in")
_xa_alone = S.expected_assists(events=[shot(True, hockey=None)], rates=_rates)
ok(abs(_xa_alone[AST_]["xA"] - _xa[AST_]["xA"] / 6) < 1e-9,
   "one feed's xA is unchanged by whether a hockey tag was present")

print(f"coverage gate (XA2_MIN_GAMES = {PR.XA2_MIN_GAMES})")

ok(PR.XA2_MIN_GAMES == 3, "gate is the spec-registered 3 tagged games")


def _gated(games):
    """Mirror of the profiles gate: None below the game threshold."""
    tagged = {g for g in games}
    return len(tagged) >= PR.XA2_MIN_GAMES


ok(not _gated([1]), "one tagged game does not become a season stat")
ok(not _gated([1, 2]), "two tagged games still below the gate")
ok(_gated([1, 2, 3]), "three tagged games clears it")
ok(not _gated([1, 1, 1, 1, 1]),
   "five chains in ONE game is still one game — the gate counts games, "
   "not chains, so a single hot possession cannot unlock it")

print(f"\nALL {PASS} CHECKS PASSED")
