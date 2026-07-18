"""Roster CSV import engine (backlog item 19) — parse variants, height
tolerance, dedup plan, and an end-to-end apply against a throwaway DB using
the same insert path as the Input Hub glue.
Script-style: run directly (python tracker/test_roster_import.py).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(prefix="app5_rimp_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import initialize_database, query, execute
initialize_database()

import helpers.roster_import as RIMP

FAILS = []


def check(label, cond, detail=""):
    print(("PASS" if cond else "FAIL"), label, detail if not cond else "")
    if not cond:
        FAILS.append(label)


# ── height parsing ───────────────────────────────────────────────────────────
for raw, want in [("71", 71.0), ("5'11", 71.0), ("5'11\"", 71.0), ("5-11", 71.0),
                  ("5 ft 11", 71.0), ("6'", 72.0), ("6", 72.0), ("", None),
                  ("5'13", None), ("banana", None), ("68.5", 68.5)]:
    check(f"height {raw!r} -> {want}", RIMP.parse_height(raw) == want,
          f"got {RIMP.parse_height(raw)}")

# ── parse: headered CSV, extra cols ignored ──────────────────────────────────
rows, warns = RIMP.parse_roster(
    "Player Name,Jersey,Ht,Grad Year,Position,Coach Notes\n"
    "Jane Smith,12,5'9,2027,PG,quick\n"
    "Kate Jones,23,5'11\",2026,C,rim\n")
check("headered: 2 rows", len(rows) == 2, rows)
check("headered: name", rows[0]["name"] == "Jane Smith")
check("headered: number", rows[0]["number"] == 12)
check("headered: height", rows[0]["height"] == 69.0)
check("headered: grad", rows[1]["grad_year"] == 2026)

# ── parse: headerless, name-first ────────────────────────────────────────────
rows, warns = RIMP.parse_roster("Jane Smith, 12, 69, 2027\nKate Jones, 23,, ")
check("headerless: 2 rows", len(rows) == 2, rows)
check("headerless: blank height/grad ok",
      rows[1]["number"] == 23 and rows[1]["height"] is None
      and rows[1]["grad_year"] is None)
check("headerless warns about assumed order",
      any("No header" in w for w in warns), warns)

# ── parse: headerless, number-first (program-page paste) ─────────────────────
rows, _ = RIMP.parse_roster("12\tJane Smith\t5'9\n23\tKate Jones\t5'11\n"
                            "3\tAmy Cho\t6'")
check("number-first: names read", [r["name"] for r in rows]
      == ["Jane Smith", "Kate Jones", "Amy Cho"], rows)
check("number-first: numbers read", rows[2]["number"] == 3)
check("number-first: height", rows[2]["height"] == 72.0)

# ── parse: Last, First flip ──────────────────────────────────────────────────
rows, warns = RIMP.parse_roster('name,number\n"Smith, Jane",12\n"Jones, Kate",23')
check("last-first flipped", rows[0]["name"] == "Jane Smith", rows)
check("flip warned", any("flipped" in w for w in warns))

# ── parse: junk rows skipped with warnings ───────────────────────────────────
rows, warns = RIMP.parse_roster("name,number\n,12\nJane Smith,twelve")
check("nameless row skipped", len(rows) == 1)
check("bad number warned but row kept",
      rows[0]["number"] is None and any("number" in w for w in warns), warns)

# ── plan: add / update / skip / in-file dupe ─────────────────────────────────
existing = [{"id": 1, "name": "Jane Smith", "number": 12, "height": 69.0,
             "grad_year": 2027},
            {"id": 2, "name": "Kate Jones", "number": 23, "height": None,
             "grad_year": 2026}]
parsed = [
    {"name": "jane smith", "number": 12, "height": 69.0, "grad_year": 2027},  # skip
    {"name": "Kate Jones", "number": 23, "height": 71.0, "grad_year": 2026},  # update ht
    {"name": "Amy Cho", "number": 3, "height": 72.0, "grad_year": 2028},      # add
    {"name": "AMY CHO", "number": 3, "height": None, "grad_year": None},      # file dupe
]
plan = RIMP.plan_import(parsed, existing)
check("plan verdicts", [p["verdict"] for p in plan]
      == ["skip", "update", "add", "skip"], [p["verdict"] for p in plan])
check("update fills height only", plan[1]["changes"] == {"height": 71.0},
      plan[1]["changes"])
check("update targets pid", plan[1]["pid"] == 2)
check("file dupe reason", plan[3]["reason"] == "duplicate row in file")

# ── end-to-end apply on a throwaway DB (the page glue's insert path) ─────────
execute("INSERT INTO teams (name, class, gender, state) VALUES ('T','4A','F','OK')")
tid = query("SELECT id FROM teams WHERE name='T'")[0]["id"]
execute("INSERT INTO players (team_id, name, number, grad_year, height, season, "
        "archived) VALUES (?, 'Jane Smith', 12, 2027, 69, 'Current', 0)", (tid,))

text = "name,number,height,grad\nJane Smith,12,5'9,2027\nAmy Cho,3,6',2028"
rows, _ = RIMP.parse_roster(text)
exist = [dict(x) for x in query(
    "SELECT id, name, number, height, grad_year FROM players "
    "WHERE team_id=? AND archived=0", (tid,))]
plan = RIMP.plan_import(rows, exist)
for p in plan:
    r = p["row"]
    if p["verdict"] == "add":
        execute("INSERT INTO players (team_id, name, number, grad_year, height, "
                "wingspan, weight, handedness, season, archived) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tid, r["name"], int(r["number"] or 0), r["grad_year"],
                 r["height"], None, None, "right", "Current", 0))
    elif p["verdict"] == "update":
        sets = ", ".join(f"{k}=?" for k in p["changes"])
        execute(f"UPDATE players SET {sets} WHERE id=?",
                (*p["changes"].values(), p["pid"]))
final = query("SELECT name, number, height FROM players WHERE team_id=? "
              "ORDER BY name", (tid,))
check("apply: 2 players total (no dupe Jane)", len(final) == 2,
      [dict(x) for x in final])
check("apply: Amy inserted with height",
      final[0]["name"] == "Amy Cho" and final[0]["height"] == 72.0)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:", *FAILS, sep="\n  ")
    sys.exit(1)
print("test_roster_import: ALL PASS")
