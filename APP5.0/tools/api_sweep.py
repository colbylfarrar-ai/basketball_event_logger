"""api_sweep.py — does the Streamlit we are about to run still have every
`st.*` this codebase calls?

`requirements.txt` pins `streamlit==1.58.0`. Bumping that pin is a deliberate
act, and this is the first thing to run after changing the number: it parses
every `st.<attr>` out of the source with `ast` (no imports, no rendering) and
asks the INSTALLED Streamlit whether each one still exists.

    python -m tools.api_sweep                 # against this machine's streamlit
    python -m tools.api_sweep --json          # machine-readable, for a remote box

To check the DROPLET's interpreter rather than this one, dump the names here and
resolve them there:

    python -m tools.api_sweep --names > /tmp/st_used.json
    scp /tmp/st_used.json app5@…:/tmp/
    ssh app5@… 'cd app5/APP5.0 && . .venv/bin/activate \\
                && python -m tools.api_sweep --check /tmp/st_used.json'

WHAT THIS CATCHES, AND WHAT IT DOES NOT. It catches a removed or renamed API —
the loud kind of break, where the attribute is simply gone. It does NOT catch a
changed CONTRACT on an API that still exists, which is the quiet kind and the
more common one: `st.image` still exists in every version, and the 2026-09-12
Whiteboard crash was it rejecting bytes where the page assumed it took them.
For those, write a consumer-contract test — `tracker/test_playbook.py` has the
pattern: call the real Streamlit helper with the real payload and assert on what
comes back.

Streamlit-free: imports `streamlit` only in `--check`/default mode, never while
collecting names.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent

#: Files whose local `st` is a mock, not Streamlit. Their attributes are the
#: mock's own surface and would always read as "missing".
_MOCK_ST = {"tracker/test_download_builder.py"}


def collect(root=_APP):
    """{attribute: [file:line, …]} for every `st.<attr>` in the tree."""
    used: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in {"__pycache__", ".venv", ".git"}]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if rel in _MOCK_ST:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "st"):
                    used.setdefault(node.attr, []).append(
                        f"{rel}:{node.lineno}")
    return {k: sorted(v) for k, v in sorted(used.items())}


def check(used):
    """(version, {attr: [sites]}) for every attribute this Streamlit lacks."""
    import streamlit as st
    missing = {k: v for k, v in used.items() if not hasattr(st, k)}
    return st.__version__, missing


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--names", action="store_true",
                    help="print the collected names as JSON and stop "
                         "(no streamlit import)")
    ap.add_argument("--check", metavar="NAMES.json",
                    help="resolve a names file produced by --names")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable result")
    a = ap.parse_args()

    used = (json.loads(Path(a.check).read_text(encoding="utf-8"))
            if a.check else collect())
    if a.names:
        print(json.dumps(used, indent=1))
        return 0

    version, missing = check(used)
    if a.json:
        print(json.dumps({"streamlit": version, "checked": len(used),
                          "missing": missing}, indent=1))
        return 1 if missing else 0

    print(f"streamlit {version} · {len(used)} distinct st.* attributes used")
    for attr, sites in sorted(missing.items()):
        print(f"  MISSING  st.{attr}")
        for s in sites[:3]:
            print(f"             {s}")
        if len(sites) > 3:
            print(f"             … {len(sites) - 3} more")
    if missing:
        print(f"\n{len(missing)} attribute(s) this Streamlit does not have. "
              f"Do NOT deploy this pin.")
        return 1
    print("\nevery attribute resolves. (A contract change on an attribute that "
          "still exists is invisible here — see the module docstring.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
