"""
db.py — SQLite connection factory with season-aware path resolution.

The active season's DB path is read from Database/seasons.json on every
connection.  If seasons.json doesn't exist, falls back to analytics.db.

Write-through Supabase sync: every execute() / executemany() call mirrors
the change to Supabase immediately after the SQLite commit.  Failures are
caught silently so the app never blocks on network issues.
"""
import re
import sqlite3
from pathlib import Path

_ROOT      = Path(__file__).resolve().parent
_SCHEMA    = _ROOT / "schema.sql"
_SEASONS   = _ROOT / "seasons.json"

# Track which DB files have already been initialised this process
_INIT_DONE: set[str] = set()


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

    if not db_path.exists():
        print(f"Creating new database: {db_path.name}…")

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
            except Exception as exc:
                print(f"[db] Migration warning: {exc}")

        conn.commit()
    finally:
        conn.close()


# ── Supabase write-through helpers ────────────────────────────────────────────

def _parse_sql_op(sql: str) -> tuple[str, str]:
    """Return (operation, table_name) from a DML statement."""
    s = sql.strip()
    m_insert = re.match(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)", s, re.IGNORECASE)
    if m_insert:
        return "INSERT", m_insert.group(1)
    m_update = re.match(r"UPDATE\s+(\w+)", s, re.IGNORECASE)
    if m_update:
        return "UPDATE", m_update.group(1)
    m_delete = re.match(r"DELETE\s+FROM\s+(\w+)", s, re.IGNORECASE)
    if m_delete:
        return "DELETE", m_delete.group(1)
    return "", ""


def _supabase_write_through(
    sql: str,
    params: tuple,
    lastrowid: int | None,
    *,
    batch_rows: list[dict] | None = None,
) -> None:
    """
    Mirror a SQLite write to Supabase.
    Non-blocking — any exception is swallowed so the app never breaks.

    batch_rows: pre-built list of dicts (used by executemany paths).
    """
    try:
        # Import here to avoid circular dependency at module load time
        from Database.supabase_sync import get_supabase_client, COMPOSITE_PK_TABLES  # noqa: PLC0415
        client = get_supabase_client()
        if client is None:
            return

        op, table = _parse_sql_op(sql)
        if not table:
            return

        pk_cols = COMPOSITE_PK_TABLES.get(table, "id")
        on_conflict = ",".join(pk_cols) if isinstance(pk_cols, list) else pk_cols

        # ── Batch path (executemany) ──────────────────────────────────────────
        if batch_rows is not None:
            if not batch_rows:
                return
            for i in range(0, len(batch_rows), 500):
                client.table(table).upsert(
                    batch_rows[i : i + 500], on_conflict=on_conflict
                ).execute()
            return

        # ── Single-row paths ─────────────────────────────────────────────────
        db = get_db_path()
        conn2 = sqlite3.connect(db)
        conn2.row_factory = sqlite3.Row
        try:
            if op == "INSERT" and lastrowid:
                row = conn2.execute(
                    f"SELECT * FROM {table} WHERE rowid=?", (lastrowid,)
                ).fetchone()
                if row:
                    client.table(table).upsert(
                        [dict(row)], on_conflict=on_conflict
                    ).execute()

            elif op == "UPDATE" and params:
                # Most UPDATE statements end with WHERE id=? — last param is id.
                # Try that first; fall back to a full-table re-push for tiny tables.
                candidate_id = params[-1]
                rows = conn2.execute(
                    f"SELECT * FROM {table} WHERE id=?", (candidate_id,)
                ).fetchall()
                if rows:
                    client.table(table).upsert(
                        [dict(r) for r in rows], on_conflict=on_conflict
                    ).execute()

            elif op == "DELETE" and params:
                # WHERE id=? pattern — last param is the id
                if re.search(r"\bid\s*=\s*\?", sql, re.IGNORECASE):
                    client.table(table).delete().eq("id", params[-1]).execute()
        finally:
            conn2.close()

    except Exception:
        pass  # Never let sync failure break the app


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
        lastrowid = cur.lastrowid
    finally:
        conn.close()
    _supabase_write_through(sql, params, lastrowid)
    return lastrowid


# ── Batch INSERT / UPDATE / DELETE ─────────────────────────────────────────────
def executemany(sql: str, seq_of_params: list) -> int:
    conn = get_connection()
    try:
        cur = conn.executemany(sql, seq_of_params)
        conn.commit()
        rowcount = cur.rowcount
    finally:
        conn.close()

    # Build dicts from column names parsed out of the INSERT statement
    # e.g.  INSERT INTO tbl (col1, col2) VALUES (?,?)
    try:
        col_match = re.search(r"\(([^)]+)\)\s+VALUES", sql, re.IGNORECASE)
        if col_match and seq_of_params:
            cols = [c.strip() for c in col_match.group(1).split(",")]
            batch = [dict(zip(cols, row)) for row in seq_of_params]
            _supabase_write_through(sql, (), None, batch_rows=batch)
    except Exception:
        pass

    return rowcount


# ── Auto-init ──────────────────────────────────────────────────────────────────
initialize_database()
