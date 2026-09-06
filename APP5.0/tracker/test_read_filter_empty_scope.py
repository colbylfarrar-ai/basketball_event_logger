"""An EMPTY read-filter must never widen back into the whole league.

`entitlement.visible_tracked_game_ids` / `team_visible_tracked_ids` return three
different things and only two of them are the same shape:

    None        the viewer is unrestricted (admin / local owner / an open archive)
    {1, 2, 3}   these games and no others
    set()       this viewer may aggregate NOTHING

The third is the dangerous one, because `None` and `set()` are both falsy-adjacent
in the way people write filter plumbing. `stats._game_filter` already learned this
lesson the hard way and now branches on `is None` — an empty collection there means
" AND 0=1", and every engine probed against the live book honours it. What is NOT
fixed is the CALLER side: call sites still write

    game_ids=(set(gids) if gids else None)

which converts the "nothing" case into the "everything" case one line before the
engine's own guard can see it. The engine never gets a chance to be right.

Two gates here, deliberately different in kind:

  * a STATIC scan for that idiom, because the failure is invisible at runtime —
    the page renders a full, healthy, entirely wrong table, and nobody's eye
    catches a leaderboard for having too MANY names on it;
  * a BEHAVIOURAL check on `player_edge.edge_boards`, which is the one place the
    conversion lives inside an engine rather than a page, so no amount of careful
    plumbing at the call site can save it.

The reachable persona for all of this is a Paid coach — Solo with no tracked games
of their own, or League-wide in a league where nobody has shared yet — whose
visible set is legitimately empty. That is the coach the co-op exists to recruit,
and today several surfaces hand them the whole pool instead of an invitation.

Run: python -m pytest tracker/test_read_filter_empty_scope.py
"""
import ast
import os
import sys
import tempfile
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

_TMP = tempfile.mkdtemp(prefix="app5_readfilter_")
os.environ["APP5_DATA_DIR"] = _TMP

import pytest                                      # noqa: E402
import database.db as DB                           # noqa: E402
from database.db import execute                    # noqa: E402
import helpers.player_edge as PE                   # noqa: E402
import helpers.player_ratings as PR                # noqa: E402

# The throwaway DB has to exist before the module-level seed below runs, and
# pytest imports every test module during COLLECTION — so skipping this does not
# fail one file, it aborts the whole suite with "no such table: teams".
DB.initialize_database()


@pytest.fixture(autouse=True)
def _this_modules_db():
    # The collection hazard test_results_season_rollover.py documents: the LAST
    # module to set APP5_DATA_DIR at import time wins for the whole run, so a
    # sibling test module's temp dir would otherwise be live by the time these
    # tests execute. Re-pin per test.
    prev = os.environ.get("APP5_DATA_DIR")
    os.environ["APP5_DATA_DIR"] = _TMP
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("APP5_DATA_DIR", None)
        else:
            os.environ["APP5_DATA_DIR"] = prev


# ── the static gate ───────────────────────────────────────────────────────────
#: Keyword arguments that ARE a read-filter — the ones an engine reads as
#: "None means the whole tracked sample".
_FILTER_KWARGS = {"game_ids", "untracked_ids", "visible_game_ids",
                  "team_game_ids", "allow"}
#: Collection constructors. `coll(NAME) if NAME else None` is only the bug when
#: the body builds a collection out of the very name being truth-tested — that is
#: the "hand this set to an engine" idiom, and nothing innocent looks like it.
_COLL = {"list", "set", "tuple", "frozenset", "sorted"}


def _unwrap(node):
    """Peel `tuple(sorted(x))` down to `x`.

    Only single-argument collection constructors are peeled, and only by NAME.
    That precision is what keeps the scan honest: `frozenset(blocks[-1]["five"])
    if blocks else None` and `set(table.keys()) if table else None` both mention
    the tested name somewhere inside, and neither is this bug — the first is a
    lineup, the second a derived key set. Only a bare re-wrap of the very
    collection being truth-tested is the read-filter idiom."""
    while (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
           and node.func.id in _COLL and len(node.args) == 1
           and not node.keywords):
        node = node.args[0]
    return node


def _is_widening_ifexp(node):
    """`coll(NAME) if NAME else None` — the empty-becomes-everything idiom."""
    if not isinstance(node, ast.IfExp):
        return False
    if not (isinstance(node.orelse, ast.Constant) and node.orelse.value is None):
        return False
    if not isinstance(node.test, ast.Name):          # a truthiness test on a name
        return False
    inner = _unwrap(node.body)
    return isinstance(inner, ast.Name) and inner.id == node.test.id


def _scan(path):
    """(line, snippet) for every widening conversion in one file."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    lines = src.splitlines()
    hits = []
    for node in ast.walk(tree):
        # form 1 — straight into a read-filter keyword argument
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in _FILTER_KWARGS and _is_widening_ifexp(kw.value):
                    hits.append((kw.value.lineno,
                                 lines[kw.value.lineno - 1].strip()))
        # form 2 — assigned to a local that is handed on a line or two later, and
        # the cache-KEY form, where an empty scope silently shares the
        # unrestricted entry (`sig = tuple(sorted(game_ids)) if game_ids else None`)
        if isinstance(node, ast.Assign) and _is_widening_ifexp(node.value):
            hits.append((node.value.lineno, lines[node.value.lineno - 1].strip()))
    return sorted(set(hits))


def test_no_call_site_widens_an_empty_read_filter():
    """No page or helper turns an empty visible set into an unrestricted one.

    The fix at every site is the same two words — `is not None` — because every
    engine below already handles an empty collection correctly. Where a caller
    genuinely cannot produce an empty set the change is a no-op, so uniformity
    costs nothing and makes the rule mechanical instead of a comment somebody
    has to remember to re-read."""
    bad = []
    for sub in ("pages", "helpers"):
        for path in sorted((_APP / sub).rglob("*.py")):
            for line, snippet in _scan(path):
                bad.append(f"{path.relative_to(_APP)}:{line}: {snippet}")
    assert not bad, ("empty read-filter widens to the whole league at:\n  "
                     + "\n  ".join(bad))


# ── the behavioural gate ──────────────────────────────────────────────────────
def _seed():
    t1 = execute("INSERT INTO teams (name, class, gender) VALUES ('A HS','3A','F')")
    t2 = execute("INSERT INTO teams (name, class, gender) VALUES ('B HS','3A','F')")
    p1 = execute("INSERT INTO players (team_id,name,number,season) "
                 "VALUES (?,?,?,'Current')", (t1, "Ann", 4))
    gid = execute("INSERT INTO games (team1_id,team2_id,date,tracked,season,"
                  "home_score,away_score) VALUES (?,?,?,1,'Current',50,40)",
                  (t1, t2, "2026-01-10"))
    for q in (1, 2, 3, 4):
        for _ in range(8):
            execute("INSERT INTO game_events (game_id, event_type, quarter, time, "
                    "primary_player_id, shot_result, shot_type) "
                    "VALUES (?, 'shot', ?, '7:00', ?, 'make', 2)", (gid, q, p1))
    return t1, p1, gid


_T1, _P1, _GID = _seed()


def test_edge_boards_passes_an_empty_scope_through(monkeypatch):
    """`edge_boards(game_ids=[])` must hand `[]` down, not `None`.

    This is the one widening conversion that lives inside an ENGINE
    (`helpers/player_edge.py:51`), so every caller doing its own plumbing
    correctly is still handed the whole league. `player_stat_table` one call
    below is already right — it returns {} for an empty scope — which is exactly
    why this survived: the layer that was fixed is not the layer that is wrong.

    Asserted with a spy rather than on the returned boards, deliberately. The
    boards only populate at FGA >= 20 with a league shot-quality model behind
    them, which a hermetic fixture cannot cheaply produce — and a behavioural
    assertion that cannot fire is worse than none, because it reads as a guard.
    The spy tests the defect itself and needs no data at all."""
    seen = {}

    def _spy(*a, **kw):
        seen["game_ids"] = kw.get("game_ids", "<positional>")
        return {}

    monkeypatch.setattr(PE.PR, "player_stat_table", _spy)
    PE.edge_boards(gender="F", game_ids=[])
    assert seen["game_ids"] is not None, (
        "edge_boards turned an empty scope into an unrestricted one before "
        "player_stat_table could honour it")


def test_rapm_memo_keys_an_empty_scope_apart_from_the_unrestricted_one():
    """An empty game set and "every game" must not share a memo entry.

    `_pure_rapm_cached` builds its key as `tuple(sorted(game_ids)) if game_ids
    else None`, so a scoped-to-nothing call lands on the SAME key as the admin's
    unrestricted one. Whichever runs first wins for both: the admin poisons the
    scoped caller with the whole league's RAPM, or the scoped caller poisons the
    admin with {}. Nothing raises either way — it is a wrong answer served warm,
    which is the hardest kind to notice."""
    PR._RAPM_MEMO.clear()
    PR._pure_rapm_cached(None, "F")
    keys_after_unrestricted = set(PR._RAPM_MEMO)
    PR._pure_rapm_cached([], "F")
    assert set(PR._RAPM_MEMO) - keys_after_unrestricted, \
        ("the empty scope reused the unrestricted memo key "
         f"{keys_after_unrestricted}")
