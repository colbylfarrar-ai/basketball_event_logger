"""Whiteboard playbook engine (backlog item 24) — compaction, coach-scoped
CRUD on a throwaway DB, caps, and the SVG renderer.
Script-style: run directly (python tracker/test_playbook.py).
"""
import os
import sys
import json
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_play_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, query
initialize_database()

import helpers.playbook as PB

FAILS = []


def check(label, cond, detail=""):
    print(("PASS" if cond else "FAIL"), label, detail if not cond else "")
    if not cond:
        FAILS.append(label)


OPS = [
    {"t": "pen", "c": "#f0a500", "pts": [[10.123456, 5.987], [11.5, 6.5],
                                         [12.0, 7.0]]},
    {"t": "cut", "c": "#58a6ff", "x1": 5, "y1": 5, "x2": 20.55555, "y2": 30},
    {"t": "pass", "c": "#3fb950", "x1": 8, "y1": 8, "x2": 25, "y2": 12},
    {"t": "dribble", "c": "#ff7b72", "x1": 4, "y1": 40, "x2": 30, "y2": 20},
    {"t": "screen", "c": "#e6edf3", "x1": 15, "y1": 15, "x2": 22, "y2": 22},
    {"t": "O", "c": "#f0a500", "x": 25, "y": 20, "n": 1},
    {"t": "X", "c": "#e6edf3", "x": 27, "y": 22, "n": 3},
    {"t": "ball", "x": 26, "y": 21},
    {"t": "hack", "evil": True},                    # unknown type → dropped
    {"t": "cut", "x1": "NaNope"},                   # malformed → dropped
]

# ── compaction ───────────────────────────────────────────────────────────────
clean = PB.compact_ops(OPS)
check("junk ops dropped", len(clean) == 8, [o["t"] for o in clean])
check("coords rounded to 0.1", clean[0]["pts"][0] == [10.1, 6.0], clean[0])
check("two-point rounding", clean[1]["x2"] == 20.6)
check("blob is compact (no spaces)",
      " " not in json.dumps(clean, separators=(",", ":")))

# ── CRUD, coach-scoped ───────────────────────────────────────────────────────
A, B = "coach.a@x.com", "coach.b@x.com"
check("save ok", PB.save_play(A, "Horns flare", "half", OPS) is None)
check("empty board rejected",
      PB.save_play(A, "Empty", "half", []) == "Nothing on the board to save.")
check("nameless rejected", PB.save_play(A, "  ", "half", OPS) is not None)
pa = PB.list_plays(A)
check("A sees 1 play", len(pa) == 1 and pa[0]["name"] == "Horns flare")
check("A's play has 8 ops", pa[0]["n_ops"] == 8)
check("B sees none", PB.list_plays(B) == [])
check("B cannot fetch A's play", PB.get_play(B, pa[0]["id"]) is None)

# upsert by (coach, name): same name overwrites, count stays 1
PB.save_play(A, "Horns flare", "full", OPS[:3])
pa2 = PB.list_plays(A)
check("upsert keeps one row", len(pa2) == 1)
g = PB.get_play(A, pa2[0]["id"])
check("upsert updated mode+ops", g["mode"] == "full" and len(g["ops"]) == 3)

# delete is coach-scoped
PB.delete_play(B, pa2[0]["id"])
check("B's delete is a no-op", len(PB.list_plays(A)) == 1)
PB.delete_play(A, pa2[0]["id"])
check("A's delete works", PB.list_plays(A) == [])

# per-coach cap
for i in range(PB.MAX_PLAYS_PER_COACH):
    check_err = PB.save_play(A, f"p{i}", "half", OPS[:2])
    assert check_err is None, check_err
check("cap blocks a new name",
      "max" in (PB.save_play(A, "one too many", "half", OPS[:2]) or ""))
check("cap still allows overwriting an existing name",
      PB.save_play(A, "p0", "half", OPS[:3]) is None)

# ── stored size stays small (living-archive rule) ────────────────────────────
row = query("SELECT ops FROM coach_plays WHERE coach_email=? AND name='p0'", (A,))
check("stored blob < 200 bytes for 3 ops", len(row[0]["ops"]) < 200,
      len(row[0]["ops"]))

# ── SVG renderer ─────────────────────────────────────────────────────────────
svg = PB.play_svg(OPS, "half")
check("svg well-formed", svg.startswith("<svg") and svg.endswith("</svg>"))
check("svg has court + strokes",
      "polyline" in svg and "circle" in svg and "stroke-dasharray" in svg)
check("svg white-paper default", "fill='#ffffff'" in svg)
check("white stroke inked for paper", "#e6edf3" not in svg)
svg_full = PB.play_svg(OPS, "full")
check("full-court svg renders", svg_full.startswith("<svg")
      and "rotate(90)" in svg_full)
check("O marker number rendered", ">1</text>" in svg)

# ── team scope (2026-07-26) — this is a PRIVACY boundary, so pin it ──────────
print()
A, B, C = "a@x.com", "b@x.com", "c@y.com"
TEAM, OTHER = 901, 902

PB.save_play(A, "A private", "half", OPS)                       # no team
PB.save_play(A, "A shared", "half", OPS, team_id=TEAM)
PB.save_play(B, "B shared", "half", OPS, team_id=TEAM)
PB.save_play(B, "B private", "half", OPS)
PB.save_play(C, "C other team", "half", OPS, team_id=OTHER)

_a_names = {p["name"] for p in PB.list_plays(A, TEAM)}
check("own private play is visible to its author", "A private" in _a_names)
check("a teammate's SHARED play is visible", "B shared" in _a_names)
check("a teammate's PRIVATE play is NOT visible", "B private" not in _a_names)
check("another team's shared play is NOT visible",
      "C other team" not in _a_names)

_a_solo = {p["name"] for p in PB.list_plays(A)}
check("with no team in scope a coach sees only their own",
      _a_solo == {"A private", "A shared"}, str(_a_solo))

# The trap this guards: if the team filter were written `team_id=?` with a NULL
# argument, NULL=NULL is not true in SQL but a careless `IS ?` or an OR without
# the NOT NULL check would expose every private play in the database.
_b_priv = [p for p in PB.list_plays(B) if p["name"] == "B private"][0]
check("a private play reports itself as unshared", _b_priv["shared"] is False)
_shared = [p for p in PB.list_plays(A, TEAM) if p["name"] == "B shared"][0]
check("a teammate's play is flagged not-mine", _shared["mine"] is False)
check("and carries its author so the UI can say whose it is",
      _shared["author"] == B)

check("get_play reads a teammate's shared play",
      (PB.get_play(A, _shared["id"], TEAM) or {}).get("name") == "B shared")
check("get_play refuses a teammate's PRIVATE play",
      PB.get_play(A, _b_priv["id"], TEAM) is None)
check("get_play refuses a shared play without the team in scope",
      PB.get_play(A, _shared["id"]) is None)

# Visible is not deletable.
PB.delete_play(A, _shared["id"])
check("a coach CANNOT delete a teammate's shared play",
      (PB.get_play(B, _shared["id"], TEAM) or {}).get("name") == "B shared")
PB.delete_play(B, _shared["id"])
check("but its author can", PB.get_play(B, _shared["id"], TEAM) is None)

# Pre-existing rows are never migrated into a team.
_legacy = query("SELECT COUNT(*) n FROM coach_plays WHERE team_id IS NULL")
check("plays saved without a team stay team-less", _legacy[0]["n"] >= 2)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:", *FAILS, sep="\n  ")
    sys.exit(1)
print("test_playbook: ALL PASS")
