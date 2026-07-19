"""
Spec 2.4 — saved-play frame sequences (throwaway DB).

save_frame appends ordered frames ('<seq> · <n>'), list_sequences groups and
orders them, every frame counts against the per-coach play cap, and a deleted
middle frame leaves a gap (order by seq_idx, no renumbering).

Run: python tracker/test_play_frames.py
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="app5_frames_test_")
os.environ["APP5_DATA_DIR"] = _TMP
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import helpers.playbook as PB                      # noqa: E402

PASS = 0


def ok(cond, label):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"  ok  {label}")


C = "coach@test"
OPS = [{"t": "O", "c": "#fff", "x": 10.0, "y": 10.0, "n": 1},
       {"t": "cut", "c": "#fff", "x1": 10.0, "y1": 10.0, "x2": 20.0, "y2": 20.0}]

print("frames append in order")
for want in (1, 2, 3):
    err, idx = PB.save_frame(C, "Horns flare", "half", OPS)
    ok(err is None and idx == want, f"frame {want} saved as idx {idx}")
seqs = PB.list_sequences(C)
ok(list(seqs) == ["Horns flare"], "one sequence listed")
ok([f["seq_idx"] for f in seqs["Horns flare"]] == [1, 2, 3], "ordered 1-2-3")
ok([f["name"] for f in seqs["Horns flare"]] ==
   ["Horns flare · 1", "Horns flare · 2", "Horns flare · 3"],
   "frame names carry the index")

print("frames count against the cap")
n_before = len(PB.list_plays(C))
ok(n_before == 3, f"3 rows used ({n_before})")
for i in range(PB.MAX_PLAYS_PER_COACH - 3):
    err = PB.save_play(C, f"filler {i}", "half", OPS)
    assert err is None, err
err, idx = PB.save_frame(C, "Horns flare", "half", OPS)
ok(err is not None and "max" in err, "cap blocks the next frame")

print("deleting a middle frame leaves a gap")
mid = seqs["Horns flare"][1]["id"]
PB.delete_play(C, mid)
seqs = PB.list_sequences(C)
ok([f["seq_idx"] for f in seqs["Horns flare"]] == [1, 3],
   "order preserved, no renumbering")
err, idx = PB.save_frame(C, "Horns flare", "half", OPS)
ok(err is None and idx == 4, "next frame continues from the max (4)")

print("standalone plays untouched")
p = PB.get_play(C, PB.list_plays(C)[-1]["id"])
ok(p["seq_name"] is None or p["seq_name"] == "Horns flare",
   "get_play returns seq fields")
solo = [pl for pl in PB.list_plays(C) if pl["seq_name"] is None]
ok(len(solo) == PB.MAX_PLAYS_PER_COACH - 3, "fillers are standalone")

print(f"\nALL {PASS} CHECKS PASSED")
