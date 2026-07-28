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
    return not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name.startswith("test_")
                   for n in tree.body)


def script_files(match: str = ""):
    return [p for p in sorted(TRACKER.glob("test_*.py"))
            if is_script_style(p) and match in p.name]


def pytest_files(match: str = ""):
    return [p for p in sorted(TRACKER.glob("test_*.py"))
            if not is_script_style(p) and match in p.name]
