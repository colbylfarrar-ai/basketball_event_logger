import sqlite3
import os
from pathlib import Path

# ============================================================
#  DATABASE LAYER — CLEAN RESTART FOUNDATION
#  - Creates analytics.db if missing
#  - Loads schema.sql on first run
#  - Provides clean helper functions
# ============================================================

DB_PATH = Path(__file__).resolve().parent / "analytics.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# ------------------------------------------------------------
# Create connection with foreign keys ON
# ------------------------------------------------------------
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ------------------------------------------------------------
# Initialize database if missing
# ------------------------------------------------------------
def initialize_database():
    if not DB_PATH.exists():
        print("Creating new analytics.db...")
    conn = get_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    # Migrations for columns added after initial release
    for stmt in [
        "ALTER TABLE players ADD COLUMN archived INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE players ADD COLUMN season TEXT NOT NULL DEFAULT 'Current'",
        "ALTER TABLE schedule ADD COLUMN season TEXT NOT NULL DEFAULT 'Current'",
        "ALTER TABLE game_lineup_players ADD COLUMN plus_minus INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(stmt)
            conn.commit()
        except Exception:
            pass  # column already exists
    conn.commit()
    conn.close()


# ------------------------------------------------------------
# Helper: run SELECT queries
# ------------------------------------------------------------
def query(sql, params=()):
    conn = get_connection()
    conn.row_factory = sqlite3.Row  # THIS LINE IS CRITICAL
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ------------------------------------------------------------
# Helper: run INSERT/UPDATE/DELETE
# ------------------------------------------------------------
def execute(sql: str, params: tuple = ()):
    conn = get_connection()
    cur = conn.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


# ------------------------------------------------------------
# Helper: run many INSERT/UPDATE/DELETE
# ------------------------------------------------------------
def executemany(sql: str, seq_of_params: list):
    conn = get_connection()
    cur = conn.executemany(sql, seq_of_params)
    conn.commit()
    conn.close()
    return cur.rowcount


# ------------------------------------------------------------
# Ensure DB exists on import
# ------------------------------------------------------------
initialize_database()