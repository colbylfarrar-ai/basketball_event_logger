"""
supabase_sync.py
================
Bidirectional sync between local SQLite and Supabase (PostgreSQL).

All reads/writes go to SQLite first — the local DB is always the source of
truth during a session.  Supabase is the cloud mirror.

Sync modes
----------
  push  →  local SQLite  ──►  Supabase   (overwrite cloud with local)
  pull  ←  Supabase      ──►  local SQLite  (overwrite local with cloud)

Sync order respects foreign-key dependencies:
  teams → players → officials → games → schedule
  → game_lineup_players → game_lineup_officials
  → game_events → game_event_lineup → app_settings

No agent required — all functions are plain Python and can be called
from the Streamlit UI or a scheduled script.
"""

import json
import re
import sqlite3
import socket
from datetime import date
from pathlib import Path
from typing import Optional, Callable

# ── Optional supabase-py ──────────────────────────────────────────────────────
try:
    from supabase import create_client, Client as SupabaseClient
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False

_CONFIG_PATH = Path(__file__).resolve().parent / "seasons.json"

# Tables in dependency order (FK-safe for inserts)
SYNC_TABLES = [
    "teams",
    "players",
    "officials",
    "games",
    "schedule",
    "game_lineup_players",
    "game_lineup_officials",
    "game_events",
    "game_event_lineup",
    "app_settings",
]

# Tables that use a non-'id' primary key (composite or named differently)
COMPOSITE_PK_TABLES = {
    "game_event_lineup": ["event_id", "player_id"],
}


# ── Connectivity ──────────────────────────────────────────────────────────────

def is_online(host: str = "8.8.8.8", port: int = 53, timeout: float = 2.0) -> bool:
    """Return True if a DNS socket connection succeeds (no HTTP needed)."""
    try:
        socket.setdefaulttimeout(timeout)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        s.close()
        return True
    except (socket.error, OSError):
        return False


# ── Config helpers ────────────────────────────────────────────────────────────

def load_seasons_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"active_season": None, "seasons": {}}


def save_seasons_config(config: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_active_season_info() -> Optional[dict]:
    """Return the active season's config dict, or None."""
    cfg = load_seasons_config()
    active = cfg.get("active_season")
    if not active:
        return None
    return cfg.get("seasons", {}).get(active)


def get_active_db_path() -> Path:
    """Return the SQLite DB path for the active season."""
    info = get_active_season_info()
    base = Path(_CONFIG_PATH).resolve().parent
    if info:
        db_file = info.get("db_file", "analytics.db")
        db_path = base / db_file
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return db_path
    return base / "analytics.db"


def switch_season(season_name: str) -> bool:
    """Switch the active season. Returns True on success."""
    cfg = load_seasons_config()
    if season_name not in cfg.get("seasons", {}):
        return False
    cfg["active_season"] = season_name
    save_seasons_config(cfg)
    return True


def add_season(name: str, supabase_url: str = "", supabase_key: str = "",
               supabase_project_id: str = "") -> bool:
    """
    Register a new season. Creates a new SQLite DB file named
    'seasons/<name>.db' and initialises its schema.
    Returns True on success.
    """
    cfg = load_seasons_config()
    if name in cfg.get("seasons", {}):
        return False  # already exists

    safe_name = re.sub(r"[^\w\-.]", "_", name)
    db_file = f"seasons/{safe_name}.db"
    db_path = Path(_CONFIG_PATH).resolve().parent / db_file
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialise schema on the new DB
    schema_path = Path(_CONFIG_PATH).resolve().parent / "schema.sql"
    if schema_path.exists():
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        # Apply same migrations as db.py
        _apply_migrations(conn)
        conn.close()

    cfg.setdefault("seasons", {})[name] = {
        "name": name,
        "db_file": db_file,
        "supabase_url": supabase_url.strip(),
        "supabase_key": supabase_key.strip(),
        "supabase_project_id": supabase_project_id.strip(),
        "created": str(date.today()),
    }
    save_seasons_config(cfg)
    return True


def update_season_credentials(season_name: str, supabase_url: str,
                               supabase_key: str, supabase_project_id: str = "") -> bool:
    """Update Supabase credentials for a season."""
    cfg = load_seasons_config()
    if season_name not in cfg.get("seasons", {}):
        return False
    cfg["seasons"][season_name]["supabase_url"] = supabase_url.strip()
    cfg["seasons"][season_name]["supabase_key"] = supabase_key.strip()
    if supabase_project_id:
        cfg["seasons"][season_name]["supabase_project_id"] = supabase_project_id.strip()
    save_seasons_config(cfg)
    return True


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply the same idempotent migrations as db.py initialise_database()."""
    migrations = [
        "ALTER TABLE players ADD COLUMN archived INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE players ADD COLUMN season TEXT NOT NULL DEFAULT 'Current'",
        "ALTER TABLE schedule ADD COLUMN season TEXT NOT NULL DEFAULT 'Current'",
        "ALTER TABLE game_lineup_players ADD COLUMN plus_minus INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE teams ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS idx_glp_game_id ON game_lineup_players(game_id)",
        "CREATE INDEX IF NOT EXISTS idx_glp_game_player ON game_lineup_players(game_id, player_id)",
        "CREATE INDEX IF NOT EXISTS idx_glp_player_id ON game_lineup_players(player_id)",
        "CREATE INDEX IF NOT EXISTS idx_ge_game_id ON game_events(game_id)",
        "CREATE INDEX IF NOT EXISTS idx_gel_event_id ON game_event_lineup(event_id)",
        "CREATE INDEX IF NOT EXISTS idx_gel_player_id ON game_event_lineup(player_id)",
        "CREATE INDEX IF NOT EXISTS idx_games_tracked ON games(tracked)",
        "CREATE INDEX IF NOT EXISTS idx_games_team1 ON games(team1_id)",
        "CREATE INDEX IF NOT EXISTS idx_games_team2 ON games(team2_id)",
        "CREATE INDEX IF NOT EXISTS idx_players_team_arch ON players(team_id, archived)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uidx_glo ON game_lineup_officials(game_id, official_id)",
        """CREATE TABLE IF NOT EXISTS app_settings (
               key   TEXT PRIMARY KEY,
               value TEXT NOT NULL DEFAULT ''
           )""",
    ]
    for stmt in migrations:
        try:
            conn.execute(stmt)
            conn.commit()
        except sqlite3.OperationalError:
            pass


# ── Supabase client ───────────────────────────────────────────────────────────

def get_supabase_client(season_info: Optional[dict] = None) -> Optional["SupabaseClient"]:
    """
    Return a Supabase client for the given (or active) season.
    Returns None if: package missing, no credentials, or offline.
    """
    if not _SUPABASE_AVAILABLE:
        return None
    info = season_info or get_active_season_info()
    if not info:
        return None
    url = info.get("supabase_url", "").strip()
    key = info.get("supabase_key", "").strip()
    if not url or not key:
        return None
    if not is_online():
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def get_sync_status() -> dict:
    """Return a dict with online status and whether Supabase is configured."""
    online = is_online()
    info = get_active_season_info()
    configured = bool(info and info.get("supabase_url") and info.get("supabase_key"))
    client_ok = False
    if online and configured:
        client_ok = get_supabase_client() is not None
    return {
        "online": online,
        "configured": configured,
        "client_ok": client_ok,
        "season": (info or {}).get("name", "unknown"),
    }


# ── Push: Local → Supabase ────────────────────────────────────────────────────

def push_to_supabase(
    db_path: Optional[Path] = None,
    status_cb: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    """
    Push all local SQLite data to Supabase via upsert.
    Returns (success, message).
    """
    client = get_supabase_client()
    if client is None:
        return False, "Supabase unavailable — check internet connection and credentials."

    if db_path is None:
        db_path = get_active_db_path()

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        errors: list[str] = []

        for table in SYNC_TABLES:
            try:
                rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
                if not rows:
                    if status_cb:
                        status_cb(f"  {table}: empty — skipped")
                    continue

                if status_cb:
                    status_cb(f"  Pushing {table} ({len(rows)} rows)…")

                # Determine conflict column(s)
                pk = COMPOSITE_PK_TABLES.get(table, "id")
                on_conflict = ",".join(pk) if isinstance(pk, list) else pk

                # Upsert in chunks of 500
                for i in range(0, len(rows), 500):
                    chunk = rows[i : i + 500]
                    client.table(table).upsert(chunk, on_conflict=on_conflict).execute()

            except Exception as exc:
                errors.append(f"{table}: {exc}")
                if status_cb:
                    status_cb(f"  ⚠ {table} error: {exc}")

        conn.close()

        if errors:
            return False, "Partial push — errors:\n" + "\n".join(errors)
        return True, f"✅ Push complete — {len(SYNC_TABLES)} tables synced to Supabase."

    except Exception as exc:
        return False, f"Push failed: {exc}"


# ── Pull: Supabase → Local ────────────────────────────────────────────────────

def pull_from_supabase(
    db_path: Optional[Path] = None,
    status_cb: Optional[Callable[[str], None]] = None,
) -> tuple[bool, str]:
    """
    Pull all Supabase data into local SQLite (full replace).
    ⚠  Deletes all local data first — make sure you want this direction.
    Returns (success, message).
    """
    client = get_supabase_client()
    if client is None:
        return False, "Supabase unavailable — check internet connection and credentials."

    if db_path is None:
        db_path = get_active_db_path()

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = OFF")
        errors: list[str] = []

        # Clear local in reverse FK order
        for table in reversed(SYNC_TABLES):
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        conn.commit()

        # Pull and insert in FK order
        for table in SYNC_TABLES:
            try:
                result = client.table(table).select("*").execute()
                rows = result.data or []
                if not rows:
                    if status_cb:
                        status_cb(f"  {table}: empty in Supabase — skipped")
                    continue

                if status_cb:
                    status_cb(f"  Pulling {table} ({len(rows)} rows)…")

                cols = list(rows[0].keys())
                placeholders = ",".join(["?" for _ in cols])
                col_names = ",".join(cols)
                conn.executemany(
                    f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})",
                    [tuple(r[c] for c in cols) for r in rows],
                )
                conn.commit()

            except Exception as exc:
                errors.append(f"{table}: {exc}")
                if status_cb:
                    status_cb(f"  ⚠ {table} error: {exc}")

        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        conn.close()

        if errors:
            return False, "Partial pull — errors:\n" + "\n".join(errors)
        return True, f"✅ Pull complete — local DB updated from Supabase."

    except Exception as exc:
        return False, f"Pull failed: {exc}"


# ── Startup auto-sync (pull if online) ───────────────────────────────────────

def auto_sync_on_startup(status_cb: Optional[Callable[[str], None]] = None) -> str:
    """
    Called once at app startup.  If online and configured, pulls the latest
    data from Supabase into the local SQLite DB.
    Returns a status string.
    """
    status = get_sync_status()
    if not status["online"]:
        return "offline — using local database only"
    if not status["configured"]:
        return "no Supabase credentials — using local database only"
    if not status["client_ok"]:
        return "could not connect to Supabase — using local database only"
    ok, msg = pull_from_supabase(status_cb=status_cb)
    return msg


# ── CLI entry point (for scheduled tasks / cron) ──────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analytics Hub — Supabase sync")
    parser.add_argument("direction", choices=["push", "pull", "status"],
                        help="push=local→cloud, pull=cloud→local, status=check")
    parser.add_argument("--season", help="Season name to operate on (default: active)")
    args = parser.parse_args()

    if args.season:
        switch_season(args.season)

    if args.direction == "status":
        s = get_sync_status()
        print(f"Online:      {s['online']}")
        print(f"Configured:  {s['configured']}")
        print(f"Client OK:   {s['client_ok']}")
        print(f"Season:      {s['season']}")

    elif args.direction == "push":
        print("Pushing local → Supabase…")
        ok, msg = push_to_supabase(status_cb=print)
        print(msg)

    elif args.direction == "pull":
        print("Pulling Supabase → local…")
        ok, msg = pull_from_supabase(status_cb=print)
        print(msg)
