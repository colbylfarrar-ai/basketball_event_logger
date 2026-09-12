"""
run.py — the launcher.

Two modes, and the DEFAULT is the one that matters in October:

    python run.py            demo   — the frozen production book, no sign-in,
                                      signed in as the owner, no network
    python run.py --dev      dev    — what this file used to do: the working
                                      book at the ordinary data dir, secrets as
                                      configured (so real auth if it is on)

The demo exists because "show a coach the app" and "develop the app" are not the
same program. Three things differ, and every one of them is something a coach in
a gym would notice:

  * THE BOOK. The dev book at %LOCALAPPDATA%\\APP5 is a development copy and has
    been months behind production before (see `local-book-lags-prod`). Demo
    points at a snapshot pulled from production with
    `tools/pull_prod_snapshot.py` — and it is deliberately NOT under AppData,
    because the Store build of Python virtualizes that directory and hands the
    shell a shadow copy (`store-python-appdata-virtualization`). A demo that
    reads a different file than the one you refreshed is worse than no demo.

  * THE SIGN-IN. `.streamlit/secrets.toml` carries a real `[auth]` block, so
    every page of a plain local run says "Sign in to continue" and OIDC needs
    the network the demo does not have. Demo loads an empty secrets file
    instead, which turns the gate off.

  * WHO YOU ARE. With auth off the app falls back to an identity with an EMPTY
    email, and ownership — his teams, his co-op depth, his settings — resolves
    through that email. So the open-local app is not the product he sees signed
    in on the website: it is wider in places and thinner in others. Demo names
    the owner's email (`APP5_DEMO_AS`) and the identity is rebuilt from the
    `app_users` row, the same way a real sign-in builds it.

The demo book is WRITABLE on purpose — demonstrating the Game Tracker means
writing events. `--reset` restores it from the pristine copy taken at pull time,
so a demo can be given twice.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: Where the frozen production snapshot lives. Overridable, but the default is
#: a plain home-directory path on purpose — see the AppData note above.
DEMO_DIR = Path(os.environ.get("APP5_DEMO_DIR")
                or (Path.home() / "app5_demo")).expanduser()
DEMO_DB = DEMO_DIR / "analytics.db"
#: Pristine copy, written once at pull time; `--reset` copies it back over.
DEMO_FROZEN = DEMO_DIR / "analytics.frozen.db"

#: An empty secrets file. Passing it to --secrets.files REPLACES Streamlit's
#: default search (which would find .streamlit/secrets.toml and its [auth]
#: block), so the gate is off without editing or moving the real file.
DEMO_SECRETS = HERE / ".streamlit" / "secrets.demo.toml"

#: The identity the demo runs as. Must be an email in `app_users`.
DEMO_AS = os.environ.get("APP5_DEMO_AS") or "colbyl.farrar@gmail.com"


def _freeze_if_needed() -> None:
    """Keep a pristine copy beside the demo book the first time it is seen."""
    if DEMO_DB.exists() and not DEMO_FROZEN.exists():
        shutil.copy2(DEMO_DB, DEMO_FROZEN)
        print(f"froze a pristine copy: {DEMO_FROZEN}")


def _reset() -> int:
    if not DEMO_FROZEN.exists():
        print(f"no frozen copy at {DEMO_FROZEN} - nothing to restore.\n"
              "Re-pull instead:  python tools/pull_prod_snapshot.py "
              f"--dest {DEMO_DIR}", file=sys.stderr)
        return 1
    try:
        shutil.copy2(DEMO_FROZEN, DEMO_DB)
    except OSError as e:
        # WinError 1224: the book is memory-mapped by a running app. Copying
        # over it would be a torn write, so refuse rather than half-restore.
        print(f"could not restore: {e}\n"
              "Close the running demo first (Ctrl-C in its terminal), then "
              "re-run.", file=sys.stderr)
        return 1
    # The book is in WAL mode. A -wal/-shm pair left from the session being
    # discarded belongs to the OLD file; SQLite would replay it over the restored
    # one on next open and hand back exactly the state this command was asked to
    # throw away. DEPLOY.md step 3 documents the same trap for the production
    # copy.
    for side in ("-wal", "-shm"):
        p = DEMO_DB.with_name(DEMO_DB.name + side)
        if p.exists():
            p.unlink()
    print(f"restored {DEMO_DB} from the frozen copy.")
    return 0


def _demo_env() -> dict:
    env = dict(os.environ)
    env["APP5_DATA_DIR"] = str(DEMO_DIR)
    env["APP5_DEMO_AS"] = DEMO_AS
    env["APP5_OFFLINE"] = "1"
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch HoopTracks.")
    ap.add_argument("--dev", action="store_true",
                    help="developer mode: the ordinary data dir and real "
                         "secrets, instead of the frozen demo book.")
    ap.add_argument("--reset", action="store_true",
                    help="restore the demo book from its frozen copy, then exit.")
    ap.add_argument("--port", default=None, help="serve on this port.")
    args = ap.parse_args()

    if args.reset:
        return _reset()

    app_path = HERE / "Main.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    if args.port:
        cmd += ["--server.port", str(args.port)]

    if args.dev:
        # Initialize the working book (safe if it already exists), then run
        # exactly as before.
        from database.db import initialize_database
        initialize_database()
        return subprocess.run(cmd).returncode

    if not DEMO_DB.exists():
        print(f"No demo book at {DEMO_DB}.\n"
              "Pull one from production first:\n"
              f"    python tools/pull_prod_snapshot.py --dest {DEMO_DIR}\n"
              "…or run the working book with:  python run.py --dev",
              file=sys.stderr)
        return 1

    _freeze_if_needed()
    env = _demo_env()
    # Initialize against the DEMO book, not the default one — the env var has
    # to be in place BEFORE database.db resolves its path, and that module
    # resolves at import, so this import happens after the assignment.
    os.environ["APP5_DATA_DIR"] = env["APP5_DATA_DIR"]
    from database.db import initialize_database
    initialize_database()

    size_mb = DEMO_DB.stat().st_size / 1e6
    # ASCII only: the Windows console this is read in is cp1252, and an em dash
    # prints there as a replacement glyph.
    print(f"HoopTracks - DEMO\n"
          f"  book     : {DEMO_DB}  ({size_mb:.1f} MB)\n"
          f"  signed in: {DEMO_AS}\n"
          f"  sign-in  : off (empty secrets)\n"
          f"  network  : offline (the FAQ serves its cached copy)\n"
          f"  re-freeze: python run.py --reset\n")
    cmd += ["--secrets.files", str(DEMO_SECRETS)]
    return subprocess.run(cmd, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
