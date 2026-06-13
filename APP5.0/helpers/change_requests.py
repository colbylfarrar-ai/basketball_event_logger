"""
change_requests.py — admin approval queue for destructive ops (write-authz).

A non-admin coach can't directly delete shared data via the Input Hub; their
delete becomes a PENDING request (the data stays live) that an admin accepts or
rejects in Settings → Review panel. REPLAY model: we store (op, table, target_id)
and re-run the delete on accept (FK cascades behave exactly as a direct delete
would). Admin / local owner delete directly — no queue.

Streamlit-free + pure so it's unit-testable headless. The viewer identity dict is
what helpers.auth.current_user() returns.
"""
from __future__ import annotations

from database.db import query, execute

# The table name is interpolated into SQL on accept, so it MUST be whitelisted.
# These are the Input-Hub-reachable deletes; never widen without auditing the
# delete's FK cascade.
ALLOWED_TABLES = {"teams", "players", "games", "officials"}


def should_delete_now(ident: dict | None) -> bool:
    """Admin (or the auth-off local owner, whose identity role is 'admin') deletes
    directly; every other coach's delete is queued for review."""
    return bool(ident) and ident.get("role") == "admin"


def request_delete(table: str, target_id, label: str, requester: str) -> None:
    """Queue a delete for admin approval. Idempotent: a duplicate pending request
    for the same row is a no-op (Input Hub may re-run across reruns)."""
    if table not in ALLOWED_TABLES:
        raise ValueError(f"table not allowed: {table}")
    dup = query(
        "SELECT id FROM change_requests WHERE status='pending' AND op='delete' "
        "AND table_name=? AND target_id=?", (table, target_id))
    if dup:
        return
    execute(
        "INSERT INTO change_requests (op, table_name, target_id, label, requester, "
        "status) VALUES ('delete', ?, ?, ?, ?, 'pending')",
        (table, target_id, label, (requester or "").strip().lower()))


def pending() -> list:
    return query(
        "SELECT id, op, table_name, target_id, label, requester, created_at "
        "FROM change_requests WHERE status='pending' ORDER BY created_at")


def pending_count() -> int:
    r = query("SELECT COUNT(*) AS n FROM change_requests WHERE status='pending'")
    return r[0]["n"] if r else 0


def accept(req_id, decider: str) -> bool:
    """Apply a pending request (run the delete) and mark it accepted. Returns True
    if applied. Whitelist-guards the table name before interpolating it into SQL."""
    rows = query(
        "SELECT op, table_name, target_id, status FROM change_requests WHERE id=?",
        (req_id,))
    if not rows or rows[0]["status"] != "pending":
        return False
    r = rows[0]
    if r["op"] != "delete" or r["table_name"] not in ALLOWED_TABLES:
        return False
    execute(f"DELETE FROM {r['table_name']} WHERE id=?", (r["target_id"],))
    execute(
        "UPDATE change_requests SET status='accepted', decided_by=?, "
        "decided_at=datetime('now') WHERE id=?",
        ((decider or "").strip().lower(), req_id))
    return True


def reject(req_id, decider: str) -> bool:
    """Discard a pending request without applying it. Returns True if it was pending."""
    rows = query("SELECT status FROM change_requests WHERE id=?", (req_id,))
    if not rows or rows[0]["status"] != "pending":
        return False
    execute(
        "UPDATE change_requests SET status='rejected', decided_by=?, "
        "decided_at=datetime('now') WHERE id=?",
        ((decider or "").strip().lower(), req_id))
    return True
