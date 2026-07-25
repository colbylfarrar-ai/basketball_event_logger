"""
passing_chains.py — hockey-assist chains, PotHAST, re-gate counter
(spec Part 1 §3). Synthetic events, no DB.

The load-bearing fact under all of this: `hockey_from_id` is captured on EVERY
shot flow, make or miss. Only the HAST STAT is make-only (it is a sibling of
AST). So coverage must be counted over ALL tagged shots — counting makes alone
would undercount a coach's tagging by the league miss rate and delay the
pre-registered re-gate for no reason. Every check below defends that boundary.

Run: python tracker/test_passing_chains.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.passing_chains as PC                # noqa: E402
import helpers.stats as S                          # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


IGN, AST_, SHOOTER, SHOOTER2 = 11, 12, 13, 14


def shot(hockey, passer, shooter, made, stype=2, gid=1):
    return {"event_type": "shot", "game_id": gid,
            "shot_result": "make" if made else "miss", "shot_type": stype,
            "primary_player_id": shooter, "pass_from_id": passer,
            "hockey_from_id": hockey, "shot_created_by_id": None,
            "shooter_team_id": 1, "rebound_by_id": None,
            "rebounder_team_id": None, "guarded_by_id": None, "zone": "C",
            "blocked_by_id": None, "secondary_player_id": None,
            "stolen_by_id": None, "play_type": None, "defense": None,
            "turnover_type": None, "period": 1, "assist_type": None}


print("empty book -> honest empty state")

ok(PC.hockey_chains(events=[]) == [], "no events -> no chains (not a zero grid)")
ok(PC.hockey_triples(events=[]) == [], "no events -> no triples")
_cov0 = PC.hast_coverage(events=[])
ok(_cov0["tagged"] == 0 and _cov0["ready"] is False, "empty coverage is not ready")
ok("none tagged yet" in PC.coverage_line(_cov0),
   "empty state speaks plainly instead of printing '0 / 50'")

# Untagged shots must not create phantom chains.
ok(PC.hockey_chains(events=[shot(None, AST_, SHOOTER, True)]) == [],
   "a shot with no hockey tag yields no chain")
# A tagged shot with no assister is a badly-tagged row: dropped, not guessed.
ok(PC.hockey_chains(events=[shot(IGN, None, SHOOTER, True)]) == [],
   "hockey tag without an assister is dropped, not attributed")

print("chains count makes AND misses; HAST counts only makes")

EV = [
    shot(IGN, AST_, SHOOTER, True, 3),    # ignited three, dropped
    shot(IGN, AST_, SHOOTER, False),      # same pair, missed
    shot(IGN, AST_, SHOOTER2, True, 2),   # same pair, different finisher
]
ch = PC.hockey_chains(events=EV)
ok(len(ch) == 1, "one igniter->assister EDGE regardless of finisher")
ok(ch[0]["pot_hast"] == 3, "pot_hast counts every tagged chain (make or miss)")
ok(ch[0]["hast"] == 2, "hast counts only the chains that dropped")
ok(ch[0]["pts"] == 5, "points follow shot value (3 + 2), not chain count")
ok(ch[0]["chains"] == ch[0]["pot_hast"],
   "`chains` and `pot_hast` are the same number under two names")

tr = PC.hockey_triples(events=EV)
ok(len(tr) == 2, "triples split the same sample by finisher (sparser by design)")
ok(sum(t["pot_hast"] for t in tr) == 3, "triples conserve the chain total")
ok(tr[0]["pot_hast"] >= tr[1]["pot_hast"], "triples are sorted by volume")

# min_n prunes.
ok(len(PC.hockey_triples(events=EV, min_n=2)) == 1, "min_n prunes thin triples")

print("coverage counter reads ALL tagged shots")

cov = PC.hast_coverage(events=EV)
ok(cov["tagged"] == 3, "tagged counts make AND miss — the capture measure")
ok(cov["made"] == 2 and cov["missed"] == 1, "make/miss split reported")
ok(cov["games"] == 1 and cov["pairs"] == 1, "games and distinct pairs counted")
ok(cov["regate_at"] == PC.REGATE_AT == 50, "re-gate threshold is the registered 50")
ok(cov["ready"] is False, "3 tagged is not ready to re-gate")

_ready = PC.hast_coverage(events=EV * 20)   # 60 tagged
ok(_ready["ready"] is True, "past the threshold -> ready to re-gate")
ok("ready to re-gate" in PC.coverage_line(_ready), "line announces readiness")
# A miss-heavy book still counts toward the re-gate — the whole point.
_misses = PC.hast_coverage(events=[shot(IGN, AST_, SHOOTER, False)] * 50)
ok(_misses["ready"] is True and _misses["made"] == 0,
   "50 tagged MISSES reach the threshold: coverage measures tagging, not makes")

print("PotHAST in the box mirrors PotAST-vs-AST")

boxes = S.aggregate_player_boxes(None, events=EV)
ok(boxes[IGN]["PotHAST"] == 3, "PotHAST counts every tagged second pass")
ok(boxes[IGN]["HAST"] == 2, "HAST stays make-only (sibling of AST)")
ok(boxes[IGN]["PotHAST"] >= boxes[IGN]["HAST"],
   "PotHAST >= HAST always, by construction")
ok(boxes[AST_]["HAST"] == 0,
   "the ASSISTER earns no HAST — that credit belongs to the igniter")

print(f"\nALL {PASS} CHECKS PASSED")
