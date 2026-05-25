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

NOTE: Streamlit Cloud blocks port 5432.  When auto-building the URL from
SUPABASE_URL + SUPABASE_DB_PASSWORD this code uses the Supabase Transaction
Pooler (port 6543) and the required username format  postgres.<project-id>.
If you supply a full SUPABASE_DB_URL make sure it also points at the pooler:
  postgresql://postgres.<project-id>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
"""

import json
import re
import urllib.parse
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
_conn_kwargs: dict = {}


# ── Credential resolution → psycopg2 kwargs ───────────────────────────────────

def _parse_url_to_kwargs(url: str) -> dict:
    """
    Parse a postgresql:// URL into psycopg2 connect kwargs.
    Uses urllib.parse so passwords with @, #, % etc. are handled correctly.
    """
    p = urllib.parse.urlparse(url)
    qs = dict(urllib.parse.parse_qsl(p.query))
    return {
        "host":    p.hostname or "",
        "port":    p.port or 5432,
        "dbname":  (p.path or "/postgres").lstrip("/") or "postgres",
        "user":    urllib.parse.unquote(p.username or ""),
        "password": urllib.parse.unquote(p.password or ""),
        "sslmode": qs.get("sslmode", "require"),
    }


def _get_connection_kwargs() -> dict:
    """
    Return psycopg2 connect kwargs by checking credentials in order:
      1. st.secrets["SUPABASE_DB_URL"]  (full URL → parsed safely)
      2. st.secrets["SUPABASE_URL"] + ["SUPABASE_DB_PASSWORD"]
         → Transaction Pooler URL (port 6543, user postgres.<pid>)
      3. seasons.json active season "db_url"
      4. seasons.json supabase_url + supabase_db_password
         → Transaction Pooler URL
    Returns {} if no credentials are found.
    """
    # ── 1 & 2: Streamlit secrets ──────────────────────────────────────────────
    try:
        import streamlit as _st

        # 1 — explicit full URL (user supplies the exact PostgreSQL URL)
        db_url = (_st.secrets.get("SUPABASE_DB_URL", "") or "").strip()
        if db_url:
            return _parse_url_to_kwargs(db_url)

        # 2 — build Transaction Pooler URL from SUPABASE_URL + SUPABASE_DB_PASSWORD
        supa_url = (_st.secrets.get("SUPABASE_URL", "") or "").strip()
        password = (_st.secrets.get("SUPABASE_DB_PASSWORD", "") or "").strip()
        if supa_url and password:
            kw = _build_pooler_kwargs(supa_url, password)
            if kw:
                return kw
    except Exception:
        pass

    # ── 3 & 4: seasons.json ───────────────────────────────────────────────────
    try:
        if _SEASONS.exists():
            with open(_SEASONS, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            active = cfg.get("active_season")
            if active:
                info = cfg.get("seasons", {}).get(active, {})

                # 3 — explicit full URL stored in seasons.json
                db_url = info.get("db_url", "").strip()
                if db_url:
                    return _parse_url_to_kwargs(db_url)

                # 4 — build from supabase_url + supabase_db_password
                supa_url = info.get("supabase_url", "").strip()
                password = info.get("supabase_db_password", "").strip()
                if supa_url and password:
                    kw = _build_pooler_kwargs(supa_url, password)
                    if kw:
                        return kw
    except Exception:
        pass

    return {}


def _build_pooler_kwargs(supabase_url: str, password: str) -> dict:
    """
    Given a Supabase project URL (https://<pid>.supabase.co) and a DB password,
    return psycopg2 kwargs targeting the Transaction Pooler on port 6543.

    Transaction Pooler is required on Streamlit Cloud because port 5432 is
    blocked.  The username MUST be  postgres.<project-id>  (not just postgres).
    """
    m = re.search(r"https://([^.]+)\.supabase\.co", supabase_url)
    if not m:
        return {}
    pid = m.group(1)
    # Derive region from project info if available; default to us-east-1.
    # Users who need a different region should supply SUPABASE_DB_URL directly.
    region = _guess_region(pid)
    return {
        "host":     f"aws-0-{region}.pooler.supabase.com",
        "port":     6543,
        "dbname":   "postgres",
        "user":     f"postgres.{pid}",
        "password": password,
        "sslmode":  "require",
    }


def _guess_region(project_id: str) -> str:
    """
    Return the AWS region for a known project ID.
    Falls back to 'us-east-1' (most common Supabase default).
    Add entries here if you use projects in other regions.
    """
    _KNOWN = {
        "llqmwczvribudrrsxzzj": "us-east-1",
    }
    return _KNOWN.get(project_id, "us-east-1")


# ── Connection factory ────────────────────────────────────────────────────────

def get_connection():
    """
    Return (and cache) a psycopg2 connection to Supabase PostgreSQL.
    autocommit=True so each statement is its own transaction — no explicit
    commit/rollback needed.
    """
    global _conn, _conn_kwargs

    kwargs = _get_connection_kwargs()
    if not kwargs:
        raise RuntimeError(
            "Supabase database password not configured.\n\n"
            "Add these to Streamlit Secrets  (Settings → Secrets on share.streamlit.io):\n\n"
            "  SUPABASE_URL = \"https://your-project.supabase.co\"\n"
            "  SUPABASE_DB_PASSWORD = \"your-database-password\"\n\n"
            "Find your password at:\n"
            "  Supabase dashboard → Project Settings → Database → Database Password\n\n"
            "Or supply a full Transaction Pooler URL:\n"
            "  SUPABASE_DB_URL = \"postgresql://postgres.<project-id>:<password>"
            "@aws-0-<region>.pooler.supabase.com:6543/postgres\""
        )

    # Reuse existing live connection if kwargs haven't changed
    if _conn is not None and _conn_kwargs == kwargs:
        try:
            if not _conn.closed:
                # Lightweight ping
                with _conn.cursor() as _cur:
                    _cur.execute("SELECT 1")
                return _conn
        except Exception:
            pass  # fall through to reconnect

    # (Re)connect
    try:
        if _conn is not None:
            _conn.close()
    except Exception:
        pass

    import psycopg2
    import psycopg2.extras

    new_conn = psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor,
        **kwargs,
    )
    new_conn.autocommit = True
    _conn = new_conn
    _conn_kwargs = kwargs
    return _conn


# ── SQL translation: SQLite → PostgreSQL ─────────────────────────────────────

def _translate_sql(sql: str) -> str:
    """Minimal SQLite→PostgreSQL translation applied to every statement."""
    # ? → %s  (parameter placeholders)
    sql = sql.replace("?", "%s")
    # INSERT OR REPLACE → INSERT … ON CONFLICT DO UPDATE
    sql = _translate_upsert(sql)
    # Strip SQLite PRAGMAs (harmless no-ops otherwise)
    import re as _re
    sql = _re.sub(r"PRAGMA\s+\w+[^\n;]*", "", sql, flags=_re.IGNORECASE)
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
