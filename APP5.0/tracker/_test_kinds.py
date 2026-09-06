"""How to run each test file under tracker/ — one classifier, two consumers.

APP5.0/conftest.py uses this to tell pytest what to skip; tracker/run_all.py
uses it to pick up what pytest skipped. Keeping the rule in one place is the
point: when they disagree, a file silently runs twice or not at all.

Three kinds:

  PYTEST   — defines `def test_*` and is safe to collect. pytest runs it.
  SCRIPT   — assertions run at import under a `Run: python tracker/test_x.py`
             contract. run_all.py runs it, one process each.
  SCRIPT   — (also) files that define `def test_*` but are LINEAR: the module
             body performs the setup AND the first half of the scenario, so
             pytest re-running the functions afterwards double-executes them
             and they fail on state the script already advanced. These declare
             `RUN_AS_SCRIPT = True` at module level, because nothing about
             their shape distinguishes them from a real pytest module.

A file whose tests live only in a `unittest.TestCase` counts as PYTEST unless
it calls `unittest.main()` itself — see `_orphan_testcase`. Before 2026-09-06
that shape fell through to SCRIPT and ran in neither suite.
"""
import ast
from pathlib import Path

TRACKER = Path(__file__).resolve().parent


def _tree(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None


def is_script_style(path: Path) -> bool:
    """True when this file must be run as its own process, not collected."""
    tree = _tree(path)
    if tree is None:
        return True                      # can't parse it → don't let it abort a session
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "RUN_AS_SCRIPT"
                        for t in node.targets)
                and getattr(node.value, "value", False) is True):
            return True
    if _has_module_level_tests(tree):
        return False
    # A TestCase that never calls unittest.main() ran NOWHERE — see
    # _orphan_testcase below. pytest can collect it, so pytest gets it.
    return not _orphan_testcase(tree)


def _has_module_level_tests(tree) -> bool:
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name.startswith("test_")
               for n in tree.body)


def _calls_unittest_main(tree) -> bool:
    """AST, not a substring search: the first cut of this looked for the exact
    text `unittest.main()` and missed `unittest.main(verbosity=2)`, which would
    have dragged test_turnover_types.py — a file that has always run correctly
    as a script — into pytest for no reason."""
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "main"
                and getattr(n.func.value, "id", "") == "unittest"):
            return True
    return False


def _orphan_testcase(tree) -> bool:
    """A `unittest.TestCase` file with no `unittest.main()` — tests that ran in
    NEITHER suite.

    Found 2026-09-06. The classifier only ever looked for module-level
    `def test_*`, so a file whose tests live in a TestCase was routed to
    run_all.py as a SCRIPT. run_all runs a script with
    `python tracker/test_x.py` — and with no `unittest.main()` at the bottom
    that process imports the module, seeds its throwaway DB, exits 0 and
    reports PASS having executed none of its assertions. Meanwhile conftest.py
    told pytest to ignore the file. Two green suites, and the nine tests
    `test_results_season_rollover.py` shipped the night before had never run.

    Deliberately narrow. A TestCase file that DOES call `unittest.main()` is
    already running correctly under run_all in its own process, and its own
    `APP5_DATA_DIR` redirect is safe there in a way it is not under collection
    (that is the whole reason conftest.py splits the tree). Moving those would
    be gratuitous risk for no coverage, so `unittest.main()` is read here as
    what it is: an explicit "run me as a script" contract, the same role
    RUN_AS_SCRIPT plays above.
    """
    has_case = any(
        isinstance(n, ast.ClassDef)
        and any(getattr(b, "attr", "") == "TestCase"
                or getattr(b, "id", "") == "TestCase"
                for b in n.bases)
        for n in tree.body)
    return has_case and not _calls_unittest_main(tree)


def script_files(match: str = ""):
    return [p for p in sorted(TRACKER.glob("test_*.py"))
            if is_script_style(p) and match in p.name]


def pytest_files(match: str = ""):
    return [p for p in sorted(TRACKER.glob("test_*.py"))
            if not is_script_style(p) and match in p.name]
