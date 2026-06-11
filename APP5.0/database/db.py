"""
db.py — SQLite connection factory with season-aware path resolution.

The active season's DB path is read from database/seasons.json on every
connection.  If seasons.json doesn't exist, falls back to analytics.db.
"""
import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

_ROOT      = Path(__file__).resolve().parent   # repo dir: schema.sql + seasons.json
_SCHEMA    = _ROOT / "schema.sql"
_SEASONS   = _ROOT / "seasons.json"


# ── Data directory (lives OUTSIDE any cloud-sync folder) ────────────────────────
# A live SQLite file + its WAL/-shm sidecars must never sit in OneDrive/Dropbox/
# iCloud: a mid-write sync (or opening the app on a second machine) can corrupt
# it. Code + schema stay in the repo; the DATA moves out. Resolution order:
#   1. $APP5_DATA_DIR            (explicit override — put the DB anywhere)
#   2. %LOCALAPPDATA%\APP5       (Windows, per-user, not synced)
#   3. ~/.app5                   (other OS / no LOCALAPPDATA)
def _data_dir() -> Path:
    env = os.environ.get("APP5_DATA_DIR")
    if env:
        d = Path(env)
    else:
        base = os.environ.get("LOCALAPPDATA")
        d = (Path(base) / "APP5") if base else (Path.home() / ".app5")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _migrate_legacy_db(target: Path) -> None:
    """One-time move-out: if `target` is absent but a legacy copy still sits in
    the repo (database/<name>), copy it to the data dir so existing data (teams,
    games, tracked events) survives the relocation. Never overwrites."""
    if target.exists():
        return
    legacy = _ROOT / target.name
    if legacy.exists() and legacy.resolve() != target.resolve():
        try:
            shutil.copy2(legacy, target)
        except OSError:
            pass

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
    """Return the SQLite path for the active season, under the external data dir.

    The DB file *name* still comes from seasons.json (active season), but it now
    resolves inside `_data_dir()` instead of the repo, and any legacy in-repo copy
    is migrated out on first access."""
    db_file = "analytics.db"
    if _SEASONS.exists():
        import json
        try:
            with open(_SEASONS, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            active = cfg.get("active_season")
            if active:
                season = cfg.get("seasons", {}).get(active, {})
                db_file = season.get("db_file", "analytics.db")
        except Exception:
            pass
    target = _data_dir() / db_file
    _migrate_legacy_db(target)
    return target


# ── Connection factory ────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    # Reliability hardening (matters even single-user on a laptop):
    #   WAL        — readers never block the writer and vice-versa; far fewer
    #                "database is locked" errors when an antivirus / backup / a
    #                second Streamlit tab touches the file mid-write.
    #   busy_timeout — wait up to 5s for a lock instead of erroring instantly.
    #   synchronous=NORMAL — safe under WAL, noticeably faster writes.
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
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
            "ALTER TABLE players        ADD COLUMN position     TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE players        ADD COLUMN availability TEXT    NOT NULL DEFAULT 'Active'",
            "ALTER TABLE teams          ADD COLUMN district     TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE games          ADD COLUMN game_type    TEXT    NOT NULL DEFAULT 'Regular'",
            "ALTER TABLE games          ADD COLUMN video_url    TEXT    NOT NULL DEFAULT ''",
            # Exact shot location in court-feet (half-court model in helpers/court.py).
            # Nullable: old shots have only `zone`; new shots store x/y AND a zone
            # derived from it, so every zone-based stat keeps working unchanged.
            "ALTER TABLE game_events     ADD COLUMN shot_x       REAL",
            "ALTER TABLE game_events     ADD COLUMN shot_y       REAL",
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
            # Hand-entered player box scores for games NOT play-by-play tracked.
            # Feeds box-derived stats (possessions = FGA + TOV → PPP/ORtg/four
            # factors) without ever setting games.tracked = 1.
            """CREATE TABLE IF NOT EXISTS manual_player_box (
                   id        INTEGER PRIMARY KEY AUTOINCREMENT,
                   game_id   INTEGER NOT NULL REFERENCES games(id)   ON DELETE CASCADE,
                   team_id   INTEGER NOT NULL REFERENCES teams(id)   ON DELETE CASCADE,
                   player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                   min  REAL    NOT NULL DEFAULT 0,
                   fgm  INTEGER NOT NULL DEFAULT 0, fga INTEGER NOT NULL DEFAULT 0,
                   tpm  INTEGER NOT NULL DEFAULT 0, tpa INTEGER NOT NULL DEFAULT 0,
                   ftm  INTEGER NOT NULL DEFAULT 0, fta INTEGER NOT NULL DEFAULT 0,
                   oreb INTEGER NOT NULL DEFAULT 0, dreb INTEGER NOT NULL DEFAULT 0,
                   ast  INTEGER NOT NULL DEFAULT 0, stl INTEGER NOT NULL DEFAULT 0,
                   blk  INTEGER NOT NULL DEFAULT 0, tov INTEGER NOT NULL DEFAULT 0,
                   pf   INTEGER NOT NULL DEFAULT 0,
                   UNIQUE(game_id, player_id)
               )""",
            "CREATE INDEX IF NOT EXISTS idx_mpb_game ON manual_player_box(game_id)",
            "CREATE INDEX IF NOT EXISTS idx_mpb_team ON manual_player_box(team_id)",
            # Scouting: per-team game-plan notes. (The play-drawing board was
            # dropped — streamlit-drawable-canvas is incompatible with Streamlit
            # 1.53 — so scout_plays is removed.)
            """CREATE TABLE IF NOT EXISTS scout_notes (
                   id      INTEGER PRIMARY KEY AUTOINCREMENT,
                   team_id INTEGER NOT NULL UNIQUE REFERENCES teams(id) ON DELETE CASCADE,
                   notes   TEXT    NOT NULL DEFAULT ''
               )""",
            "DROP TABLE IF EXISTS scout_plays",
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
