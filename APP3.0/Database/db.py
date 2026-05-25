"""
db.py — PostgreSQL connection via Supabase (psycopg2).

All reads and writes go directly to Supabase's PostgreSQL database.
Supabase is the single source of truth — no local SQLite fallback.

Credential resolution (first match wins):
  1. st.secrets["SUPABASE_DB_URL"]                       full PostgreSQL URL
  2. st.secrets["SUPABASE_URL"] + ["SUPABASE_DB_PASSWORD"]  built automatically
  3. Database/seasons.json active season "db_url"          local override
  4. Database/seasons.json supabase_url + supabase_db_password

How to get your SUPABASE_DB_PASSWORD:
  Supabase dashboard → Project Settings → Database → Database Password
"""

import json
import re
from pathlib import Path

_ROOT    = Path(__file__).resolve().parent
_SEASONS = _ROOT / "seasons.json"

# Per-table primary keys used for INSERT OR REPLACE → upsert translation
_TABLE_PK: dict = {
    "teams":                 "id",
    "players":               "id",
    "officials":             "id",
    "games":                 "id",
    "schedule":              "id",
    "game_lineup_players":   "id",
    "game_lineup_officials": ["game_id", "official_id"],
    "game_events":           "id",
    "game_event_lineup":     ["event_id", "player_id"],
    "app_settings":          "key",
}

# ── Module-level connection singleton ─────────────────────────────────────────
# Reused across Streamlit reruns (module cached in sys.modules).
_conn = None
_conn_url = ""


# ── Credential resolution ─────────────────────────────────────────────────────

def _get_db_url() -> str:
    """Return the PostgreSQL connection URL, or '' if not configured."""
    # 1 — Streamlit secrets: explicit full URL
    try:
        import streamlit as _st
        url = _st.secrets.get("SUPABASE_DB_URL", "") or ""
        if url:
            return url.strip()

        # 2 — build from SUPABASE_URL + SUPABASE_DB_PASSWORD
        supa_url = _st.secrets.get("SUPABASE_URL", "") or ""
        password = _st.secrets.get("SUPABASE_DB_PASSWORD", "") or ""
        if supa_url and password:
            m = re.search(r"https://([^.]+)\.supabase\.co", supa_url)
            if m:
                pid = m.group(1)
                return (
                    f"postgresql://postgres:{password}"
                    f"@db.{pid}.supabase.co:5432/postgres?sslmode=require"
                )
    except Exception:
        pass

    # 3 — seasons.json
    try:
        if _SEASONS.exists():
            with open(_SEASONS, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            active = cfg.get("active_season")
            if active:
                info = cfg.get("seasons", {}).get(active, {})
                url = info.get("db_url", "").strip()
                if url:
                    return url
                supa_url = info.get("supabase_url", "")
                password = info.get("supabase_db_password", "")
                if supa_url and password:
                    m = re.search(r"https://([^.]+)\.supabase\.co", supa_url)
                    if m:
                        pid = m.group(1)
                        return (
                            f"postgresql://postgres:{password}"
                            f"@db.{pid}.supabase.co:5432/postgres?sslmode=require"
                        )
    except Exception:
        pass

    return ""


# ── Connection factory ────────────────────────────────────────────────────────

def get_connection():
    """
    Return (and cache) a psycopg2 connection to Supabase PostgreSQL.
    autocommit=True so each statement is its own transaction — no explicit
    commit/rollback needed.
    """
    global _conn, _conn_url

    url = _get_db_url()
    if not url:
        raise RuntimeError(
            "Supabase database password not configured.\n\n"
            "Add SUPABASE_DB_PASSWORD to Streamlit Secrets:\n"
            "  share.streamlit.io → your app → ⋮ → Settings → Secrets\n\n"
            "Find your password at:\n"
            "  Supabase dashboard → Project Settings → Database → Database Password"
        )

    # Reuse existing live connection
    if _conn is not None and _conn_url == url:
        try:
            if not _conn.closed:
                return _conn
        except Exception:
            pass

    # (Re)connect
    try:
        if _conn is not None:
            _conn.close()
    except Exception:
        pass

    import psycopg2
    import psycopg2.extras

    new_conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    new_conn.autocommit = True
    _conn = new_conn
    _conn_url = url
    return _conn


# ── SQL translation: SQLite → PostgreSQL ─────────────────────────────────────

def _translate_sql(sql: str) -> str:
    """Minimal SQLite→PostgreSQL translation applied to every statement."""
    # ? → %s  (parameter placeholders)
    sql = sql.replace("?", "%s")
    # INSERT OR REPLACE → INSERT … ON CONFLICT DO UPDATE
    sql = _translate_upsert(sql)
    # Strip SQLite PRAGMAs (harmless no-ops otherwise)
    sql = re.sub(r"PRAGMA\s+\w+[^\n;]*", "", sql, flags=re.IGNORECASE)
    return sql.strip()


def _translate_upsert(sql: str) -> str:
    """Convert  INSERT OR REPLACE INTO tbl (cols) VALUES (…)
       to       INSERT INTO tbl (cols) VALUES (…) ON CONFLICT (pk) DO UPDATE SET …"""
    m = re.match(
        r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s+VALUES\s*(.+)",
        sql.strip(), re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return sql

    table    = m.group(1)
    cols_str = m.group(2)
    values   = m.group(3).rstrip(";")
    cols     = [c.strip() for c in cols_str.split(",")]

    pk     = _TABLE_PK.get(table, "id")
    pk_set = set(pk) if isinstance(pk, list) else {pk}
    conflict_clause = ", ".join(pk) if isinstance(pk, list) else pk

    non_pk = [c for c in cols if c not in pk_set]
    if non_pk:
        update = ", ".join(f"{c}=EXCLUDED.{c}" for c in non_pk)
        suffix = f"ON CONFLICT ({conflict_clause}) DO UPDATE SET {update}"
    else:
        suffix = f"ON CONFLICT ({conflict_clause}) DO NOTHING"

    return f"INSERT INTO {table} ({cols_str}) VALUES {values} {suffix}"


# ── Public API ────────────────────────────────────────────────────────────────

def query(sql: str, params: tuple = ()) -> list:
    """Execute a SELECT and return a list of dicts."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(_translate_sql(sql), params or None)
        return [dict(row) for row in cur.fetchall()]


def execute(sql: str, params: tuple = ()):
    """
    Execute an INSERT / UPDATE / DELETE.
    For INSERT on tables with a plain integer 'id' PK, returns the new row id.
    Returns None otherwise.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        translated = _translate_sql(sql)

        # Append RETURNING id for simple-PK inserts so callers get lastrowid
        is_insert = bool(re.match(r"\s*INSERT", translated, re.IGNORECASE))
        if is_insert:
            table_m = re.search(r"INTO\s+(\w+)", translated, re.IGNORECASE)
            table   = table_m.group(1) if table_m else ""
            if _TABLE_PK.get(table, "id") == "id" and "RETURNING" not in translated.upper():
                translated += " RETURNING id"

        cur.execute(translated, params or None)

        if is_insert and cur.description:
            row = cur.fetchone()
            return int(row["id"]) if row and "id" in row else None
    return None


def executemany(sql: str, seq_of_params: list) -> int:
    """Execute a batch INSERT / UPDATE / DELETE efficiently."""
    if not seq_of_params:
        return 0
    conn = get_connection()
    with conn.cursor() as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(
            cur, _translate_sql(sql), seq_of_params, page_size=500
        )
    return len(seq_of_params)


# ── Compatibility stubs ───────────────────────────────────────────────────────

def initialize_database() -> None:
    """
    In PostgreSQL mode the schema lives in Supabase — nothing to create locally.
    Called by every page; tests the connection so errors surface immediately.
    """
    try:
        get_connection()
    except RuntimeError:
        raise   # Let the "add SUPABASE_DB_PASSWORD" message surface to the user
    except Exception as exc:
        raise RuntimeError(f"Could not connect to Supabase PostgreSQL: {exc}") from exc


def get_db_path():
    """Compatibility stub — no local DB file in PostgreSQL mode."""
    return None
