"""pytest configuration for the APP5.0 tree.

Two kinds of file live under tracker/ and they need different runners:

  * ~38 PYTEST modules — they define `def test_*` and pytest runs them.
  * ~89 SCRIPT modules — their assertions run at import, under a
    `Run: python tracker/test_x.py` contract. Many redirect
    `os.environ["APP5_DATA_DIR"]` to a throwaway dir at import, seven call
    `sys.exit(0)` at module scope when the live DB has nothing to check, and a
    few are linear scenarios that pytest would double-execute.

Collecting the second group broke the first, badly and non-obviously:

  * a module-level `sys.exit()` raises SystemExit during collection, which
    pytest does not handle there — the whole session died with
    `INTERNALERROR> SystemExit: 0` and NOTHING ran. `python -m pytest tracker/`
    was aborting rather than reporting, so there was no regression gate at all.
  * `APP5_DATA_DIR` is re-read on every `get_db_path()`, so the first hermetic
    module to import silently redirects every later module to an empty DB.
    Alphabetical import order decided the result.

So pytest owns the pytest modules and `tracker/run_all.py` owns the scripts.
Neither half is skipped — each runs under the tool that can actually run it.
The rule itself lives in tracker/_test_kinds.py so the two cannot drift.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tracker._test_kinds import script_files      # noqa: E402

_ROOT = Path(__file__).parent
collect_ignore = [str(p.relative_to(_ROOT)) for p in script_files()]
