"""
living_recal loop (founder batch item 7) — throwaway DB, gate scoring stubbed.

The real T6 walk-forward is slow and data-dependent; this test injects a fake
_t6_sum so the loop's CONTROL logic is what's under test: the new-games
threshold, beat-or-tie adoption, history logging, and that only a strict win
writes overrides.

Run: python tracker/test_living_recal.py
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_lr_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import execute                   # noqa: E402
import tools.living_recal as LR                   # noqa: E402
import helpers.model_constants as MC              # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('A','3A','F')")
t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('B','3A','F')")


def add_tracked(n):
    for _ in range(n):
        execute("INSERT INTO games (team1_id,team2_id,date,tracked,season) "
                "VALUES (?,?, '2026-01-10', 1, 'Current')", (t1, t2))


# ── stub the gate so the incumbent scores 20.0 and any reg<incumbent scores
#    better (a clear beat), reg>=incumbent scores worse. ───────────────────────
def fake_t6(cfg):
    reg = cfg["team_ratings.DEFAULT_REG"]
    s = round(19.0 + reg, 3)          # lower reg -> lower (better) MAE
    return s, {"mae": s / 2}, {"mae": s / 2}


LR._t6_sum = fake_t6
LR._LOG = Path(_TMP) / "RECAL_LOG.md"   # never touch the committed repo doc
# keep the effective base deterministic (ignore any machine overrides)
LR._effective_base = lambda: {
    "team_ratings.DEFAULT_REG": 0.5,
    "team_ratings.DEFAULT_SOS_WEIGHT": 1.6,
    "player_ratings.RATING_K_GAMES": 2,
    "player_ratings.TEAM_PRIOR_LAMBDA": 0.5,
    "player_ratings.ARCH_ANCHOR_BLEND": 0.5,
    "player_ratings._OVERALL_PARTS": [["offense", 1.1]],
}

print("threshold gate")
add_tracked(1)
r = LR.run(force=False)
ok(not r["ran"] and "new tracked games" in r["reason"],
   "skips below MIN_NEW_GAMES")

print("runs on force, adopts a strict beat")
r = LR.run(force=True)
ok(r["ran"], "force runs")
# grid includes reg*0.5 = 0.25 -> score 19.25 < incumbent 19.5 -> adopt
ok(r["adopted"] and r["best_t6a"] < r["incumbent_t6a"],
   f"adopts the lower-reg winner ({r['incumbent_t6a']}->{r['best_t6a']})")
ok(MC.load().get("team_ratings.DEFAULT_REG") == r["changes"][
    "team_ratings.DEFAULT_REG"], "adopted value written to app_settings")

print("history logged")
h = LR.history()
ok(h and h[-1]["adopted"], "run appended to history")

print("tie holds (no strict improvement -> no adopt)")
LR._t6_sum = lambda cfg: (20.0, {"mae": 10.0}, {"mae": 10.0})  # flat everywhere
before = MC.load()
r2 = LR.run(force=True)
ok(r2["ran"] and not r2["adopted"], "a flat grid holds the incumbent")
ok(MC.load() == before, "no override change on a hold")

print("new-games counter advances (threshold now needs fresh games)")
r3 = LR.run(force=False)
ok(not r3["ran"], "no new games since last run -> skip")

print(f"\nALL {PASS} CHECKS PASSED")
