import sqlite3
from pathlib import Path

DB_PATH    = Path(__file__).resolve().parent / "analytics.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_INITIALIZED = False   # module-level guard — only run migrations once per process


# ── Connection factory ────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ── Database initialisation ───────────────────────────────────────────────────
def initialize_database():
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    if not DB_PATH.exists():
        print("Creating new analytics.db…")

    conn = get_connection()
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        migrations = [
            # Schema additions (idempotent via try/except OperationalError)
            "ALTER TABLE players        ADD COLUMN archived    INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE players        ADD COLUMN season      TEXT    NOT NULL DEFAULT 'Current'",
            "ALTER TABLE schedule       ADD COLUMN season      TEXT    NOT NULL DEFAULT 'Current'",
            "ALTER TABLE game_lineup_players ADD COLUMN plus_minus INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE teams          ADD COLUMN notes       TEXT    NOT NULL DEFAULT ''",
            # Indexes — safe to run every startup (CREATE IF NOT EXISTS)
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
            # Settings table
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
                pass   # column/index already exists — expected on re-runs
            except Exception as exc:
                print(f"[db] Unexpected migration error: {exc}\nSQL: {stmt[:80]}")

        conn.commit()
    finally:
        conn.close()


# ── SELECT helper ─────────────────────────────────────────────────────────────
def query(sql: str, params: tuple = ()) -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ── INSERT / UPDATE / DELETE helper ──────────────────────────────────────────
def execute(sql: str, params: tuple = ()):
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ── Batch INSERT / UPDATE / DELETE helper ────────────────────────────────────
def executemany(sql: str, seq_of_params: list) -> int:
    conn = get_connection()
    try:
        cur = conn.executemany(sql, seq_of_params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ── Auto-init on first import ─────────────────────────────────────────────────
initialize_database()
