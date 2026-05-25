"""
db.py — PostgreSQL via Supabase Edge Function (sql-proxy).

All reads and writes are routed through the deployed 'sql-proxy' Edge Function,
which runs inside Supabase's infrastructure and connects to the database using
the injected SUPABASE_DB_URL — no local database password required.

Credential resolution (first match wins):
  1. st.secrets["SUPABASE_URL"] + ["SUPABASE_KEY"]
  2. Database/seasons.json active season supabase_url + supabase_key
"""

import json
import re
import urllib.request
import urllib.error
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


# ── Credential resolution ─────────────────────────────────────────────────────

def _get_edge_config() -> tuple[str, str]:
    """Return (supabase_url, anon_key) from secrets or seasons.json."""
    try:
        import streamlit as _st
        url = (_st.secrets.get("SUPABASE_URL", "") or "").strip()
        key = (_st.secrets.get("SUPABASE_KEY", "") or "").strip()
        if url and key:
            return url, key
    except Exception:
        pass

    try:
        if _SEASONS.exists():
            with open(_SEASONS, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            active = cfg.get("active_season")
            if active:
                info = cfg.get("seasons", {}).get(active, {})
                url  = info.get("supabase_url", "").strip()
                key  = info.get("supabase_key", "").strip()
                if url and key:
                    return url, key
    except Exception:
        pass

    return "", ""


# ── Edge Function HTTP call ───────────────────────────────────────────────────

def _call_proxy(sql: str, params=(), mode: str = "query") -> dict:
    """POST to the sql-proxy Edge Function and return the parsed JSON."""
    base_url, anon_key = _get_edge_config()
    if not base_url or not anon_key:
        raise RuntimeError(
            "Supabase credentials not configured.\n\n"
            "Add to Streamlit Secrets or Database/seasons.json:\n"
            "  SUPABASE_URL  = \"https://<project>.supabase.co\"\n"
            "  SUPABASE_KEY  = \"<anon-key>\""
        )

    payload = json.dumps({
        "sql":    sql,
        "params": list(params) if params else [],
        "mode":   mode,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/functions/v1/sql-proxy",
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {anon_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"sql-proxy HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Could not reach sql-proxy: {exc}") from exc

    if "error" in data:
        raise RuntimeError(f"SQL error: {data['error']}")

    return data


# ── SQL translation: SQLite → PostgreSQL ─────────────────────────────────────

def _translate_sql(sql: str) -> str:
    """Translate SQLite SQL to PostgreSQL with $1/$2/… positional placeholders."""
    # ? → $1, $2, … (counter-based, left-to-right)
    counter = [0]
    def _next(m):  # noqa: E306
        counter[0] += 1
        return f"${counter[0]}"
    sql = re.sub(r"\?", _next, sql)
    # INSERT OR REPLACE → INSERT … ON CONFLICT DO UPDATE
    sql = _translate_upsert(sql)
    # Strip SQLite PRAGMAs
    sql = re.sub(r"PRAGMA\s+\w+[^\n;]*", "", sql, flags=re.IGNORECASE)
    return sql.strip()


def _translate_upsert(sql: str) -> str:
    """Convert INSERT OR REPLACE INTO tbl (cols) VALUES (…)
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
    result = _call_proxy(_translate_sql(sql), params, mode="query")
    return result.get("rows", [])


def execute(sql: str, params: tuple = ()):
    """
    Execute an INSERT / UPDATE / DELETE.
    For INSERT on tables with a plain integer 'id' PK, returns the new row id.
    Returns None otherwise.
    """
    translated = _translate_sql(sql)

    is_insert = bool(re.match(r"\s*INSERT", translated, re.IGNORECASE))
    if is_insert:
        table_m = re.search(r"INTO\s+(\w+)", translated, re.IGNORECASE)
        table   = table_m.group(1) if table_m else ""
        if _TABLE_PK.get(table, "id") == "id" and "RETURNING" not in translated.upper():
            translated += " RETURNING id"

    result = _call_proxy(translated, params, mode="execute")
    return result.get("id")


def executemany(sql: str, seq_of_params: list) -> int:
    """Execute a batch INSERT / UPDATE / DELETE efficiently."""
    if not seq_of_params:
        return 0
    translated = _translate_sql(sql)
    result = _call_proxy(translated, seq_of_params, mode="executemany")
    return result.get("rowCount", len(seq_of_params))


# ── Compatibility stubs ───────────────────────────────────────────────────────

def initialize_database() -> None:
    """Test the Edge Function connection. Called by every page at startup."""
    try:
        _call_proxy("SELECT 1 AS ok", mode="query")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not connect to Supabase: {exc}") from exc


def get_connection():
    """Compatibility stub — tests connectivity via the Edge Function."""
    initialize_database()
    return True


def get_db_path():
    """Compatibility stub — no local DB file in PostgreSQL mode."""
    return None
