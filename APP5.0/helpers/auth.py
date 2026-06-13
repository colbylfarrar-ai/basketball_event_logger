"""
auth.py — login gate + role lookup for the Streamlit app.

Uses Streamlit's native OIDC auth (st.login / st.user, Streamlit >= 1.42,
requires Authlib). The gate is enabled ONLY when .streamlit/secrets.toml has
an [auth] section (see .streamlit/secrets.toml.example) — without it the app
runs open, which is today's local single-coach behavior. NEVER expose the
Streamlit app to the internet without configuring [auth].

Who gets in: emails in the app_users table, managed from the Settings page.
Bootstrap: the FIRST person to sign in while app_users is empty becomes the
admin — that's you; add coaches afterwards.

OIDC provides authentication only; roles live here in SQLite:
  admin — everything + manage users on the Settings page
  coach — everything except user management
"""
from __future__ import annotations

import secrets

import streamlit as st

from database.db import execute, query, set_audit_actor

ROLES = ("admin", "coach")

# Local/owner identity when auth is off: full access (matches today's open
# single-coach behavior) — admin role + paid plan so every gate passes.
_LOCAL_IDENTITY = {"email": "", "name": "Local", "role": "admin",
                   "plan": "paid", "paid_until": "", "team_id": None,
                   "shares_pool": 1, "pool_banned": 0}


def auth_enabled() -> bool:
    """True when an [auth] block exists in secrets — the deploy-time switch."""
    try:
        return "auth" in st.secrets
    except Exception:
        return False


# ── user table (pure DB — testable without streamlit) ───────────────────────────
def lookup_role(email: str):
    rows = query("SELECT role FROM app_users WHERE email=?",
                 ((email or "").strip().lower(),))
    return rows[0]["role"] if rows else None


def lookup_user(email: str):
    """Full allowlist row (role, plan, team_id, paid_until, shares_pool,
    pool_banned) or None."""
    rows = query("SELECT email, role, name, plan, paid_until, team_id, "
                 "shares_pool, pool_banned FROM app_users WHERE email=?",
                 ((email or "").strip().lower(),))
    return rows[0] if rows else None


def list_users():
    return query("SELECT email, role, name, plan, team_id, shares_pool, "
                 "pool_banned, added_at FROM app_users ORDER BY role, email")


def add_user(email: str, role: str = "coach", name: str = "",
             added_by: str = ""):
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("valid email required")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    execute("""INSERT INTO app_users (email, role, name, added_by)
               VALUES (?,?,?,?)
               ON CONFLICT(email) DO UPDATE SET role=excluded.role""",
            (email, role, name, added_by))


def remove_user(email: str):
    execute("DELETE FROM app_users WHERE email=?",
            ((email or "").strip().lower(),))


# ── per-coach tracker tokens (mobile API auth) ─────────────────────────────────
def gen_tracker_token() -> str:
    return secrets.token_urlsafe(24)


def set_tracker_token(email: str) -> str:
    """Generate + store a fresh tracker token for this coach; returns it.
    The coach pastes it into the PWA; the API resolves it back to this user."""
    tok = gen_tracker_token()
    execute("UPDATE app_users SET tracker_token=? WHERE email=?",
            (tok, (email or "").strip().lower()))
    return tok


def clear_tracker_token(email: str):
    execute("UPDATE app_users SET tracker_token='' WHERE email=?",
            ((email or "").strip().lower(),))


def get_tracker_token(email: str) -> str:
    rows = query("SELECT tracker_token FROM app_users WHERE email=?",
                 ((email or "").strip().lower(),))
    return rows[0]["tracker_token"] if rows else ""


# ── plan + team (tier management, set from the Settings page) ───────────────────
PLANS = ("free", "paid")


def set_plan(email: str, plan: str):
    if plan not in PLANS:
        raise ValueError(f"plan must be one of {PLANS}")
    execute("UPDATE app_users SET plan=? WHERE email=?",
            (plan, (email or "").strip().lower()))


def set_team(email: str, team_id):
    """Assign the coach's own team (their own-data scope). team_id int or None.
    Also points their PER-COACH default_team at the assigned team so it's the
    pre-selected team for them across the app. Unassigning (None) leaves any
    default they've set alone."""
    email = (email or "").strip().lower()
    execute("UPDATE app_users SET team_id=? WHERE email=?", (team_id, email))
    if team_id is not None:
        rows = query("SELECT name FROM teams WHERE id=?", (team_id,))
        if rows:
            from helpers.settings_utils import set_setting
            set_setting("default_team", rows[0]["name"], email=email)


def get_team_shares_pool(team_id) -> bool:
    """Is this TEAM in the Coaches' Co-op (teams.shares_pool)? The canonical
    TEAM-LEVEL opt-in flag — a program is one unit."""
    if team_id is None:
        return False
    rows = query("SELECT shares_pool FROM teams WHERE id=?", (team_id,))
    return bool(rows[0]["shares_pool"]) if rows else False


def set_team_shares_pool(team_id, on: bool):
    """Flip a TEAM's Coaches' Co-op toggle (Solo ↔ League-wide) — affects EVERY
    coach assigned to the team. Recomputes the denormalized games.in_pool so the
    team's tracked games join / leave the pool immediately (read-path teeth).
    No-op when team_id is None."""
    if team_id is None:
        return
    execute("UPDATE teams SET shares_pool=? WHERE id=?", (1 if on else 0, team_id))
    from helpers.entitlement import recompute_game_pool
    recompute_game_pool()


def _team_of(email: str):
    rows = query("SELECT team_id FROM app_users WHERE email=?",
                 ((email or "").strip().lower(),))
    return rows[0]["team_id"] if rows else None


def set_shares_pool(email: str, on: bool):
    """Flip the co-op toggle for the coach's TEAM (team-level opt-in) — applies to
    every coach on that team. No-op if the coach has no team assigned."""
    set_team_shares_pool(_team_of(email), on)


def get_shares_pool(email: str) -> bool:
    """A coach's effective co-op status = their TEAM's flag (team-level opt-in)."""
    return get_team_shares_pool(_team_of(email))


def set_pool_banned(email: str, banned: bool):
    """Admin moderation: ban/unban a coach from the Coaches' Co-op. Banning purges
    their tracked games from the pool and hides the pool from them (forced Solo);
    unbanning restores per their own shares_pool toggle. Recomputes games.in_pool."""
    execute("UPDATE app_users SET pool_banned=? WHERE email=?",
            (1 if banned else 0, (email or "").strip().lower()))
    from helpers.entitlement import recompute_game_pool
    recompute_game_pool()


def bootstrap_admin_if_empty(email: str, name: str = ""):
    """First sign-in on an empty user table becomes admin (one-time setup).
    Returns 'admin' if the bootstrap happened, else None."""
    if query("SELECT email FROM app_users LIMIT 1"):
        return None
    add_user(email, "admin", name, added_by="bootstrap")
    return "admin"


# ── the gate ─────────────────────────────────────────────────────────────────────
def require_login() -> dict:
    """Call once per page run, after set_page_config. Returns the identity
    {'email','name','role'} — or renders a sign-in / not-authorized screen and
    st.stop()s. With auth not configured, returns a local admin identity."""
    if not auth_enabled():
        st.session_state["auth_user"] = _LOCAL_IDENTITY
        set_audit_actor("")              # no-auth local owner → audited as 'local'
        return _LOCAL_IDENTITY

    if not getattr(st.user, "is_logged_in", False):
        st.title("🏀 APP5 Analytics")
        st.write("Sign in to continue.")
        if st.button("Sign in", type="primary"):
            st.login()
        st.stop()

    email = (getattr(st.user, "email", "") or "").strip().lower()
    name = getattr(st.user, "name", "") or email
    role = lookup_role(email) or bootstrap_admin_if_empty(email, name)
    if role is None:
        st.title("Not authorized")
        st.write(f"**{email}** isn't on the coach list. "
                 "Ask the admin to add you on the Settings page.")
        if st.button("Log out"):
            st.logout()
        st.stop()

    u = lookup_user(email) or {}
    ident = {"email": email, "name": name, "role": role,
             "plan": u.get("plan", "free"),
             "paid_until": u.get("paid_until", ""),
             "team_id": u.get("team_id"),
             # team-level co-op: effective sharing = the coach's TEAM flag
             "shares_pool": 1 if get_team_shares_pool(u.get("team_id")) else 0,
             "pool_banned": u.get("pool_banned", 0)}
    st.session_state["auth_user"] = ident
    set_audit_actor(email)               # attribute this run's writes to this coach
    return ident


def current_user() -> dict:
    """Identity stored by require_login() this run (local admin when auth off)."""
    return st.session_state.get("auth_user", _LOCAL_IDENTITY)


# ── entitlement (plan gating) ──────────────────────────────────────────────────
def has_tracked_access(ident: dict | None = None) -> bool:
    """True if this user may see tracked play-by-play depth (Paid tier).

    Admin always qualifies; otherwise plan == 'paid', or a paid_until date that
    hasn't passed. INERT until wired into the has_tracked render guards — adding
    it here changes no behavior yet."""
    ident = ident or current_user()
    if ident.get("role") == "admin":
        return True
    if ident.get("plan") == "paid":
        return True
    pu = (ident.get("paid_until") or "").strip()
    if pu:
        from datetime import date
        try:
            return pu >= date.today().isoformat()
        except Exception:
            return False
    return False
