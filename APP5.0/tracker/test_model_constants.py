"""
Living-MLM override layer (founder batch item 7) — throwaway DB.

Run: python tracker/test_model_constants.py
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_mc_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.model_constants as MC              # noqa: E402
import helpers.team_ratings as TR                 # noqa: E402
import helpers.player_ratings as PR               # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


print("empty by default")
ok(MC.load() == {}, "no overrides -> empty")
ok(MC.apply() == {}, "apply is a no-op with nothing stored")

print("set + validate + apply")
_reg0 = TR.DEFAULT_REG
MC.set_constants({"team_ratings.DEFAULT_REG": 0.9,
                  "player_ratings.RATING_K_GAMES": 3,
                  "not.a.real.key": 5,          # dropped (not in REGISTRY)
                  "player_ratings.RATING_K_GAMES_BAD": "x"})
d = MC.load()
ok("team_ratings.DEFAULT_REG" in d and "not.a.real.key" not in d,
   "only registered keys stored")
applied = MC.apply()
ok(TR.DEFAULT_REG == 0.9, "DEFAULT_REG written onto the live global")
ok(PR.RATING_K_GAMES == 3, "RATING_K_GAMES written onto the live global")
ok(applied["team_ratings.DEFAULT_REG"] == 0.9, "apply reports what it set")

print("score_ratings honors the override via call-time resolution")
# the entry point resolves reg=None -> module global, so setattr reaches it
import inspect
src = inspect.getsource(TR.score_ratings)
ok("reg is None" in src and "reg = DEFAULT_REG" in src,
   "score_ratings resolves reg at call time")

print("bad coercion rejected, not fatal")
MC.set_constants({"player_ratings.RATING_K_GAMES": 0})   # _posint rejects < 1
ok(MC.load().get("player_ratings.RATING_K_GAMES") == 3,
   "invalid value ignored, prior kept")

print("_OVERALL_PARTS round-trips through JSON as tuples")
parts = [["offense", 1.1], ["defense", 1.0]]
MC.set_constants({"player_ratings._OVERALL_PARTS": parts})
MC.apply()
ok(PR._OVERALL_PARTS[0] == ("offense", 1.1),
   "list-of-lists coerced back to (name, weight) tuples")

print("clear reverts")
MC.clear()
ok(MC.load() == {}, "clear empties the override set")

# restore the process global we mutated (other tests share the interpreter only
# per-process, but be tidy)
TR.DEFAULT_REG = _reg0

print(f"\nALL {PASS} CHECKS PASSED")
