"""Run the SCRIPT-style tests — the ones pytest cannot collect.

Most files under tracker/ are not pytest modules: their assertions run at import
time under a `Run: python tracker/test_x.py` contract, several redirect
APP5_DATA_DIR to a throwaway dir at import, and a few `sys.exit(0)` when the
live DB has nothing to check. They therefore need one process each — which is
exactly the isolation they already assume — and pytest is told to skip them in
APP5.0/conftest.py.

Usage, from APP5.0/:
    python tracker/run_all.py            # every script-style test
    python tracker/run_all.py insights   # only those matching a substring

Use the REAL interpreter, not the Microsoft Store shim: the Store python sees a
virtualized shadow copy of %LOCALAPPDATA%\\APP5 and reads a stale analytics.db
without saying so, which turns live-book tests into confident nonsense.
    %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe tracker/run_all.py

Exit code is the number of failures (0 = all green), so CI can gate on it.
"""
import subprocess
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_APP))

from tracker._test_kinds import script_files       # noqa: E402

TIMEOUT = 300


def _warn_if_virtualized():
    """The Microsoft Store python sandboxes %LOCALAPPDATA% into a stale shadow
    copy — and that view is INHERITED BY CHILD PROCESSES, so pinning the real
    interpreter per child does not help if THIS script is the Store one. Every
    live-book test then reads an empty analytics.db and fails with `0 games`
    that have nothing to do with the code."""
    if "WindowsApps" in sys.executable or "PythonSoftwareFoundation" in sys.executable:
        print("!! WARNING: running under the Microsoft Store python\n"
              f"!!   {sys.executable}\n"
              "!! Its virtualized %LOCALAPPDATA% is inherited by the child\n"
              "!! processes below, so live-book tests will read a stale, empty\n"
              "!! analytics.db and fail for no real reason. Re-run with:\n"
              "!!   %LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe "
              "tracker/run_all.py\n")


def main(argv):
    _warn_if_virtualized()
    match = argv[1] if len(argv) > 1 else ""
    files = script_files(match)
    if not files:
        print(f"no script-style tests match {match!r}")
        return 0

    print(f"{len(files)} script-style test file(s)\n")
    passed, failed, timedout = [], [], []
    for f in files:
        try:
            r = subprocess.run([sys.executable, str(f)], cwd=str(_APP),
                               capture_output=True, text=True,
                               errors="replace", timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            timedout.append(f.name)
            print(f"TIMEOUT  {f.name}")
            continue
        out = (r.stdout or "") + (r.stderr or "")
        lines = [ln for ln in out.splitlines() if ln.strip()]
        last = lines[-1][:160] if lines else "(no output)"
        if r.returncode == 0:
            passed.append(f.name)
            print(f"ok       {f.name}  |  {last}")
        else:
            failed.append((f.name, r.returncode, out))
            print(f"FAIL({r.returncode}) {f.name}  |  {last}")

    print("\n" + "=" * 70)
    print(f"passed {len(passed)}   failed {len(failed)}   timeout {len(timedout)}")
    for name, rc, out in failed:
        print("\n" + "-" * 70)
        print(f"{name}  exit={rc}")
        print("\n".join([ln for ln in out.splitlines() if ln.strip()][-20:]))
    return len(failed) + len(timedout)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
