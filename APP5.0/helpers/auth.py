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
                   "team_ids": [], "shares_pool": 1, "pool_banned": 0}


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


# ── assistant "scorer" guest links (the link IS the token; log-only) ────────────
def issue_guest_token(email: str, label: str = "") -> str:
    """Create a standing, revocable assistant-scorer link token for this coach and
    return it. The tracker API resolves it to this coach but flagged guest, so it
    can only log/undo events — never finish/create/edit. Separate from the coach's
    own tracker_token, so revoking an assistant never touches the coach."""
    tok = secrets.token_urlsafe(24)
    execute("INSERT INTO tracker_guest_tokens (token, owner_email, label) "
            "VALUES (?,?,?)", (tok, (email or "").strip().lower(), label or ""))
    return tok


def list_guest_tokens(email: str):
    """Active (non-revoked) assistant links for this coach, oldest first."""
    return query("SELECT token, label, created_at FROM tracker_guest_tokens "
                 "WHERE owner_email=? AND revoked=0 ORDER BY created_at",
                 ((email or "").strip().lower(),))


def revoke_guest_token(token: str):
    execute("UPDATE tracker_guest_tokens SET revoked=1 WHERE token=?", (token,))


# ── plan + team (tier management, set from the Settings page) ───────────────────
PLANS = ("free", "paid")


def set_plan(email: str, plan: str):
    if plan not in PLANS:
        raise ValueError(f"plan must be one of {PLANS}")
    execute("UPDATE app_users SET plan=? WHERE email=?",
            (plan, (email or "").strip().lower()))


def get_teams(email: str):
    """All team ids a coach staffs (multi-team). Source of truth = coach_teams;
    falls back to the legacy single app_users.team_id if there are no rows yet."""
    email = (email or "").strip().lower()
    rows = query("SELECT team_id FROM coach_teams WHERE coach_email=? "
                 "ORDER BY team_id", (email,))
    if rows:
        return [r["team_id"] for r in rows]
    t = _team_of(email)
    return [t] if t is not None else []


def set_teams(email: str, team_ids):
    """Assign the coach's team(s) — one team, or BOTH genders of one school.
    coach_teams is the source of truth; app_users.team_id is kept as the PRIMARY
    (first) team for legacy readers + the per-coach default_team. Applies the
    dual-staff co-op coupling and recomputes the pool."""
    email = (email or "").strip().lower()
    ids = []
    for t in (team_ids or []):
        if t is None:
            continue
        t = int(t)
        if t not in ids:
            ids.append(t)
    execute("DELETE FROM coach_teams WHERE coach_email=?", (email,))
    for t in ids:
        execute("INSERT OR IGNORE INTO coach_teams (coach_email, team_id) "
                "VALUES (?,?)", (email, t))
    primary = ids[0] if ids else None
    execute("UPDATE app_users SET team_id=? WHERE email=?", (primary, email))
    if primary is not None:
        rows = query("SELECT name FROM teams WHERE id=?", (primary,))
        if rows:
            from helpers.settings_utils import set_setting
            set_setting("default_team", rows[0]["name"], email=email)
    _apply_pool_coupling()
    from helpers.entitlement import recompute_game_pool
    recompute_game_pool()


def set_team(email: str, team_id):
    """Back-compat single-team assignment → delegates to set_teams."""
    set_teams(email, [team_id] if team_id is not None else [])


def _apply_pool_coupling():
    """Dual-staff coupling: if a coach staffs >=2 teams and ANY is League-wide,
    set ALL of that coach's teams League-wide (the rule — one gender in the pool
    -> both in). Iterates to a fixpoint so it propagates through shared coaches.
    Only ever turns sharing ON."""
    for _ in range(20):
        before = {r["id"] for r in
                  query("SELECT id FROM teams WHERE shares_pool=1")}
        rows = query("SELECT coach_email, team_id FROM coach_teams")
        by_coach = {}
        for r in rows:
            by_coach.setdefault(r["coach_email"], []).append(r["team_id"])
        for tids in by_coach.values():
            if len(tids) >= 2 and any(t in before for t in tids):
                ph = ",".join("?" * len(tids))
                execute(f"UPDATE teams SET shares_pool=1 WHERE id IN ({ph})",
                        tuple(tids))
        after = {r["id"] for r in
                 query("SELECT id FROM teams WHERE shares_pool=1")}
        if after == before:
            break


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
    _apply_pool_coupling()
    from helpers.entitlement import recompute_game_pool
    recompute_game_pool()


def _team_of(email: str):
    rows = query("SELECT team_id FROM app_users WHERE email=?",
                 ((email or "").strip().lower(),))
    return rows[0]["team_id"] if rows else None


def set_shares_pool(email: str, on: bool):
    """Flip the co-op toggle for ALL teams a coach staffs — a dual-staff coach's
    boys + girls teams move TOGETHER (the rule: one in the pool -> both in). No-op
    if the coach staffs no team."""
    email = (email or "").strip().lower()
    ids = get_teams(email)
    if not ids:
        return
    ph = ",".join("?" * len(ids))
    execute(f"UPDATE teams SET shares_pool=? WHERE id IN ({ph})",
            tuple([1 if on else 0] + ids))
    _apply_pool_coupling()
    from helpers.entitlement import recompute_game_pool
    recompute_game_pool()


def get_shares_pool(email: str) -> bool:
    """A coach's effective co-op status = ANY team they staff is League-wide
    (dual-staff teams are coupled, so a coach's teams agree anyway)."""
    return any(get_team_shares_pool(t) for t in get_teams(email))


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
        from pathlib import Path as _P
        try:
            _wm = (_P(__file__).resolve().parent.parent / "assets"
                   / "logo_wordmark.svg").read_text(encoding="utf-8")
            st.image(_wm, width=320)
        except Exception:
            st.title("🏀 HoopTracks")
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
    _teams = get_teams(email)
    ident = {"email": email, "name": name, "role": role,
             "plan": u.get("plan", "free"),
             "paid_until": u.get("paid_until", ""),
             "team_id": u.get("team_id"),          # PRIMARY team (legacy / default)
             "team_ids": _teams,                    # every team this coach staffs
             # team-level co-op: League-wide if ANY of the coach's teams shares
             "shares_pool": 1 if any(get_team_shares_pool(t) for t in _teams) else 0,
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
