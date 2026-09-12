"""`matchups.matchup_table` returns FG% on 0-100, and every renderer agrees.

Reported from the live app: the player profile's "who she guarded / who guarded
her" block printed FG% values like 2220%. The engine hands back a PERCENTAGE
(`round(100 * FGM/FGA, 1)`) and the card multiplied by 100 a second time.

Two teeth, because the bug has two halves:

  * a BEHAVIOURAL check that the engine's own numbers are on 0-100 and match
    hand-computed makes/attempts — the contract itself;
  * a STATIC check that no renderer multiplies one of these values by 100.
    The failure is invisible at runtime in the only way that matters: nothing
    raises, the table renders, and a coach reads a number that is wrong by two
    orders of magnitude. The Players Lab read the same table correctly two
    screens away, so "someone will notice" had already been disproved.

Run: python -m pytest tracker/test_matchup_fg_units.py
"""
import ast
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_matchup_units_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                      # noqa: E402
import database.db as DB                           # noqa: E402
from database.db import execute                    # noqa: E402
import helpers.matchups as MU                      # noqa: E402

DB.initialize_database()


@pytest.fixture(autouse=True)
def _this_modules_db():
    """The collection hazard test_results_season_rollover.py documents: the LAST
    module to set APP5_DATA_DIR at import wins at run time. Re-pin per test."""
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


def _seed():
    """One defender contesting one shooter: 2 makes on 5 attempts = 40.0%."""
    t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('A','3A','F')")
    t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('B','3A','F')")
    shooter = execute("INSERT INTO players (team_id,name,number,season) "
                      "VALUES (?,?,?,'Current')", (t1, "Shooter", 4))
    defender = execute("INSERT INTO players (team_id,name,number,season) "
                       "VALUES (?,?,?,'Current')", (t2, "Defender", 5))
    gid = execute("INSERT INTO games (team1_id,team2_id,date,tracked,season,"
                  "home_score,away_score) VALUES (?,?,?,1,'Current',50,40)",
                  (t1, t2, "2026-01-10"))
    for i in range(5):
        execute(
            "INSERT INTO game_events (game_id, event_type, quarter, time, "
            "primary_player_id, guarded_by_id, shot_result, shot_type, zone) "
            "VALUES (?, 'shot', 1, '7:00', ?, ?, ?, 2, 'C')",
            (gid, shooter, defender, "make" if i < 2 else "miss"))
    return shooter, defender, gid


_SHOOTER, _DEFENDER, _GID = _seed()


def test_matchup_table_reports_fg_pct_on_0_100():
    """2 of 5 is 40.0, not 0.4 — at every level of the returned structure."""
    tbl = MU.matchup_table([_GID])
    rec = tbl[_DEFENDER]
    assert rec["FGA"] == 5 and rec["FGM"] == 2
    assert rec["FG%"] == pytest.approx(40.0), (
        f"defender total FG% is {rec['FG%']}, expected 40.0 on a 0-100 scale")
    assert rec["by_shooter"][_SHOOTER]["FG%"] == pytest.approx(40.0), \
        "by_shooter FG% left the 0-100 scale"
    assert rec["by_zone"]["C"]["FG%"] == pytest.approx(40.0), \
        "by_zone FG% left the 0-100 scale"


#: (file, function) that render `matchup_table` output. Scoped deliberately:
#: most rate engines in this tree DO return a 0-1 fraction, so a blanket
#: "never multiply an FG% by 100" scan would flag the play-type blocks
#: elsewhere in the same file, where the `* 100` is correct. The unit hazard
#: belongs to this one table, so the gate is pointed at what reads it.
_MATCHUP_RENDERERS = [
    ("helpers/dashboard/player_card.py", "_render_matchups"),
]


def test_no_renderer_multiplies_a_matchup_fg_pct_by_100():
    """`x["FG%"] * 100` on a value from this table is the 2220% bug."""
    bad = []
    for rel, fname in _MATCHUP_RENDERERS:
        path = _APP / rel
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        fn = next((n for n in ast.walk(ast.parse(src, filename=str(path)))
                   if isinstance(n, ast.FunctionDef) and n.name == fname), None)
        assert fn is not None, f"{rel}: {fname} moved or was renamed"
        for node in ast.walk(fn):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)):
                continue
            if not any(isinstance(s, ast.Constant) and s.value == 100
                       for s in (node.left, node.right)):
                continue
            # does either side read a "FG%" subscript?
            if any(isinstance(sub, ast.Subscript)
                   and isinstance(sub.slice, ast.Constant)
                   and isinstance(sub.slice.value, str)
                   and sub.slice.value.endswith("FG%")
                   for sub in ast.walk(node)):
                bad.append(f"{rel}:{node.lineno}: "
                           f"{lines[node.lineno - 1].strip()}")
    assert not bad, (
        "matchup FG% is already 0-100; multiplying it by 100 renders 2220% for "
        "a 22.2% shooter:\n  " + "\n  ".join(bad))
