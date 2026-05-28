"""
db.py — SQLite connection factory with season-aware path resolution.

The active season's DB path is read from database/seasons.json on every
connection.  If seasons.json doesn't exist, falls back to analytics.db.
"""
import re
import sqlite3
from datetime import datetime
from pathlib import Path

_ROOT      = Path(__file__).resolve().parent
_SCHEMA    = _ROOT / "schema.sql"
_SEASONS   = _ROOT / "seasons.json"

# Track which DB files have already been initialised this process
_INIT_DONE: set[str] = set()


# ── Date normalisation ─────────────────────────────────────────────────────────
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Accepted input formats, tried in order. US month/day ordering.
_DATE_FORMATS = (
    "%Y-%m-%d",   # 2026-01-16  (already ISO)
    "%m/%d/%y",   # 1/16/26
    "%m/%d/%Y",   # 1/16/2026
    "%m-%d-%y",   # 1-16-26
    "%m-%d-%Y",   # 1-16-2026
    "%Y/%m/%d",   # 2026/01/16
)


def normalize_date(value) -> str:
    """Parse a date in any accepted format and return ISO 'YYYY-MM-DD'.

    Two-digit years map via strptime's pivot (00-68 -> 2000s). If the value
    can't be parsed it is returned unchanged so a save never loses data.
    """
    if value is None:
        return value
    s = str(value).strip()
    if not s or _ISO_RE.match(s):
        return s
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


# ── Active DB path ─────────────────────────────────────────────────────────────
def get_db_path() -> Path:
    """Return the SQLite path for the active season (reads seasons.json)."""
    if _SEASONS.exists():
        import json
        try:
            with open(_SEASONS, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            active = cfg.get("active_season")
            if active:
                season = cfg.get("seasons", {}).get(active, {})
                db_file = season.get("db_file", "analytics.db")
                p = _ROOT / db_file
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
        except Exception:
            pass
    return _ROOT / "analytics.db"


# ── Connection factory ────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ── Database initialisation ───────────────────────────────────────────────────
def initialize_database():
    """Idempotent — safe to call on every page load."""
    db_path = get_db_path()
    key = str(db_path)
    if key in _INIT_DONE:
        return
    _INIT_DONE.add(key)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        if _SCHEMA.exists():
            with open(_SCHEMA, "r", encoding="utf-8") as f:
                conn.executescript(f.read())

        migrations = [
            "ALTER TABLE players        ADD COLUMN archived    INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE players        ADD COLUMN season      TEXT    NOT NULL DEFAULT 'Current'",
            "ALTER TABLE schedule       ADD COLUMN season      TEXT    NOT NULL DEFAULT 'Current'",
            "ALTER TABLE game_lineup_players ADD COLUMN plus_minus INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE teams          ADD COLUMN notes       TEXT    NOT NULL DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS idx_glp_game_id       ON game_lineup_players(game_id)",
            "CREATE INDEX IF NOT EXISTS idx_glp_game_player   ON game_lineup_players(game_id, player_id)",
            "CREATE INDEX IF NOT EXISTS idx_glp_player_id     ON game_lineup_players(player_id)",
            "CREATE INDEX IF NOT EXISTS idx_ge_game_id         ON game_events(game_id)",
            "CREATE INDEX IF NOT EXISTS idx_gel_event_id       ON game_event_lineup(event_id)",
            "CREATE INDEX IF NOT EXISTS idx_gel_player_id      ON game_event_lineup(player_id)",
            "CREATE INDEX IF NOT EXISTS idx_games_tracked      ON games(tracked)",
            "CREATE INDEX IF NOT EXISTS idx_games_team1        ON games(team1_id)",
            "CREATE INDEX IF NOT EXISTS idx_games_team2        ON games(team2_id)",
            "CREATE INDEX IF NOT EXISTS idx_players_team_arch  ON players(team_id, archived)",
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

        # Normalise legacy date text to ISO 'YYYY-MM-DD' so ORDER BY and
        # parsing are reliable. Only touches rows not already ISO.
        for table in ("games", "schedule"):
            try:
                rows = conn.execute(
                    f"SELECT id, date FROM {table} "
                    "WHERE date IS NOT NULL AND date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
                ).fetchall()
                for rid, raw in rows:
                    iso = normalize_date(raw)
                    if iso != raw:
                        conn.execute(
                            f"UPDATE {table} SET date=? WHERE id=?", (iso, rid)
                        )
                conn.commit()
            except sqlite3.OperationalError:
                pass

        conn.commit()
    finally:
        conn.close()


# ── SELECT ─────────────────────────────────────────────────────────────────────
def query(sql: str, params: tuple = ()) -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ── INSERT / UPDATE / DELETE ───────────────────────────────────────────────────
def execute(sql: str, params: tuple = ()):
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ── Batch INSERT / UPDATE / DELETE ─────────────────────────────────────────────
def executemany(sql: str, seq_of_params: list) -> int:
    conn = get_connection()
    try:
        cur = conn.executemany(sql, seq_of_params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ── Auto-init ──────────────────────────────────────────────────────────────────
initialize_database()
