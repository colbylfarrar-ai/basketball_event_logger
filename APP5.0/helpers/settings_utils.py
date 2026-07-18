"""
App-wide settings stored in app_settings (SQLite key/value table).
Provides theme CSS injection for Rankings and Team Analytics pages.
"""
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import streamlit as st
from database.db import query, execute


# ══════════════════════════════════════════════════════════════════════════════
#  DEFAULTS & PALETTES
# ══════════════════════════════════════════════════════════════════════════════

DEFAULTS = {
    "default_team":  "",
    "accent_color":  "#f0a500",
    "color_scheme":  "Gold",
    "app_style":     "Dark",
    "wide_mode":     "1",   # "1" = wide, "0" = centered
    "cb_safe":       "0",   # "1" = colorblind-safe good/bad pair (blue/orange)
}

# Colorblind-safe semantic pair (deuteranopia/protanopia-friendly): the app's
# GOOD/BAD encoding is pure green/red everywhere; this swaps the PAIR while
# leaving team identity colours and the accent alone.
CB_GOOD = "#58a6ff"
CB_BAD = "#e67e22"


def semantic_pair(settings=None) -> tuple:
    """(good_hex, bad_hex) for the current viewer — the single source both the
    CSS vars and the chart tokens resolve from."""
    cb = (settings or {}).get("cb_safe") if settings is not None \
        else get_setting("cb_safe", "0")
    if cb == "1":
        return CB_GOOD, CB_BAD
    return "#3fb950", "#e74c3c"

# Named accent-color presets  {name: hex}
ACCENT_PRESETS = {
    "Gold":    "#f0a500",
    "Blue":    "#3498db",
    "Green":   "#2ecc71",
    "Orange":  "#e67e22",
    "Purple":  "#9b59b6",
    "Crimson": "#e74c3c",
    "Teal":    "#1abc9c",
    "Pink":    "#e91e8c",
}

# Card / background style presets
STYLE_PRESETS = {
    "Dark": {
        "label":       "Dark (default)",
        "card_bg":     "#161b22",
        "card_border": "#30363d",
        "card_grad":   "linear-gradient(135deg,#0d1117 0%,#161b22 100%)",
        "body_bg":     "#0d1117",
        "card_bg_2":   "#0d1117",
        "track":       "#21262d",
        "subtext":     "#8b949e",
        "text":        "#f0f6fc",
    },
    "Midnight": {
        "label":       "Midnight Blue",
        "card_bg":     "#0b1120",
        "card_border": "#1a2744",
        "card_grad":   "linear-gradient(135deg,#06091a 0%,#0b1120 100%)",
        "body_bg":     "#06091a",
        "card_bg_2":   "#06091a",
        "track":       "#16233f",
        "subtext":     "#7a8fa8",
        "text":        "#e8edf5",
    },
    "Carbon": {
        "label":       "Carbon",
        "card_bg":     "#1e1e1e",
        "card_border": "#3a3a3a",
        "card_grad":   "linear-gradient(135deg,#111111 0%,#1e1e1e 100%)",
        "body_bg":     "#111111",
        "card_bg_2":   "#111111",
        "track":       "#2a2a2a",
        "subtext":     "#9a9a9a",
        "text":        "#f5f5f5",
    },
    "Slate": {
        "label":       "Slate",
        "card_bg":     "#1e2a3a",
        "card_border": "#2d4060",
        "card_grad":   "linear-gradient(135deg,#131d2b 0%,#1e2a3a 100%)",
        "body_bg":     "#131d2b",
        "card_bg_2":   "#131d2b",
        "track":       "#24344a",
        "subtext":     "#7d9bb5",
        "text":        "#e2ecf4",
    },
    "Forest": {
        "label":       "Forest",
        "card_bg":     "#162318",
        "card_border": "#27422a",
        "card_grad":   "linear-gradient(135deg,#0c170e 0%,#162318 100%)",
        "body_bg":     "#0c170e",
        "card_bg_2":   "#0c170e",
        "track":       "#1d3320",
        "subtext":     "#7aa87f",
        "text":        "#e2f4e5",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  READ / WRITE
# ══════════════════════════════════════════════════════════════════════════════

# PER-COACH preferences: these keys are namespaced to the signed-in coach so one
# coach's theme / default team doesn't change another's. Everything else
# (data_version, active_season, team_color::*, migration markers) stays GLOBAL.
# Stored as "u:<email>:<key>"; a coach with no override inherits the global value.
USER_SCOPED = {"default_team", "accent_color", "color_scheme", "app_style",
               "wide_mode", "cb_safe", "scout_hidden_sections",
               # per-coach {team_id: {insight-line hash: first-seen date}} JSON
               # blob behind the Insights tab's NEW chips (one key, one blob —
               # USER_SCOPED is an exact-key set, so no per-team keys).
               "insights_seen",
               # War Room save/load (Tier 3 item 23): named saved lineups and
               # bracket seed configs — ONE JSON blob per concern per coach.
               "wr_saved_lineups", "wr_bracket_seeds"}


def _scope_email() -> str:
    """The signed-in coach who owns per-user settings. '' = no auth / not logged in
    yet → falls back to the shared/global bucket (today's single-coach behaviour)."""
    try:
        u = st.session_state.get("auth_user")
        if u and u.get("email"):
            return u["email"].strip().lower()
    except Exception:
        pass
    try:
        if getattr(st.user, "is_logged_in", False):
            return (getattr(st.user, "email", "") or "").strip().lower()
    except Exception:
        pass
    return ""


def _ukey(key: str, email: str) -> str:
    return f"u:{email}:{key}" if (email and key in USER_SCOPED) else key


# ── per-rerun settings snapshot ───────────────────────────────────────────────
# get_setting used to open a fresh SQLite connection per call; team_color()
# alone can call it dozens of times in one render. Instead: ONE
# `SELECT key, value FROM app_settings` per rerun, held in session_state and
# reused by every get_setting / get_all_settings on that run. Invalidation:
#   · keyed on `_data_version_seen` (page_chrome bumps it when another process
#     writes) so tracker-side writes refresh the snapshot the same rerun the
#     data caches refresh;
#   · plus a 60-second wall-clock bucket, so a settings write from ANOTHER web
#     session (no data_version bump) can stay stale for at most a minute —
#     the same staleness contract as the ttl'd data caches;
#   · set_setting patches the snapshot in place, so a session always reads its
#     own writes immediately.
# Outside a Streamlit run (script tests, bare imports) there is no session —
# _session_store() returns None and every reader falls back to direct queries,
# which is byte-for-byte the old behaviour.
_SNAP_TTL = 60
_SNAP_KEY = "_settings_snap"


def _session_store():
    """The live session_state dict, or None when there is no Streamlit run
    (bare script / test import). Split out so tests can inject a plain dict."""
    try:
        if st.runtime.exists():
            return st.session_state
    except Exception:
        pass
    return None


def _snapshot():
    """{key: value} for the whole app_settings table, one query per rerun.
    None = no session to memo in (caller uses the direct-query path)."""
    import time
    ss = _session_store()
    if ss is None:
        return None
    ver = ss.get("_data_version_seen", "")
    bucket = int(time.time() // _SNAP_TTL)
    snap = ss.get(_SNAP_KEY)
    if snap and snap["ver"] == ver and snap["bucket"] == bucket:
        return snap["data"]
    try:
        data = {r["key"]: r["value"]
                for r in query("SELECT key, value FROM app_settings")}
    except Exception:
        return None
    ss[_SNAP_KEY] = {"ver": ver, "bucket": bucket, "data": data}
    return data


def get_setting(key: str, default: str = "", email=None) -> str:
    email = _scope_email() if email is None else email
    snap = _snapshot()
    if snap is not None:
        # user-scoped key: prefer this coach's value, else the global one
        if email and key in USER_SCOPED:
            v = snap.get(_ukey(key, email))
            if v is not None:
                return v
        v = snap.get(key)
        if v is not None:
            return v
        return default if default else DEFAULTS.get(key, "")
    # no-session fallback — the original per-call query path
    if email and key in USER_SCOPED:
        rows = query("SELECT value FROM app_settings WHERE key=?",
                     (_ukey(key, email),))
        if rows:
            return rows[0]["value"]
    rows = query("SELECT value FROM app_settings WHERE key=?", (key,))
    if rows:
        return rows[0]["value"]
    return default if default else DEFAULTS.get(key, "")


def set_setting(key: str, value: str, email=None) -> None:
    email = _scope_email() if email is None else email
    execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)",
        (_ukey(key, email), value),
    )
    # read-your-own-writes: patch the live snapshot instead of waiting out TTL
    ss = _session_store()
    if ss is not None:
        snap = ss.get(_SNAP_KEY)
        if snap:
            snap["data"][_ukey(key, email)] = value


def get_all_settings(email=None) -> dict:
    email = _scope_email() if email is None else email
    snap = _snapshot()
    s = dict(DEFAULTS)                       # start with defaults
    if snap is not None:
        for k, v in snap.items():
            if not k.startswith("u:"):       # global values + non-scoped keys
                s[k] = v
        if email:                            # overlay THIS coach's scoped values
            prefix = f"u:{email}:"
            for k, v in snap.items():
                if k.startswith(prefix):
                    s[k[len(prefix):]] = v
        return s
    for r in query("SELECT key, value FROM app_settings"):
        if not r["key"].startswith("u:"):    # global values + non-scoped keys
            s[r["key"]] = r["value"]
    if email:                                # overlay THIS coach's scoped values
        prefix = f"u:{email}:"
        for r in query("SELECT key, value FROM app_settings WHERE key LIKE ?",
                       (prefix + "%",)):
            s[r["key"][len(prefix):]] = r["value"]
    return s


# ══════════════════════════════════════════════════════════════════════════════
#  THEME CSS INJECTION
# ══════════════════════════════════════════════════════════════════════════════

def apply_page_config(settings: dict = None, title: str = None) -> None:
    """
    Call st.set_page_config based on stored settings.
    Must be the first st.* call on the page — call before apply_theme_css.
    Safe to call even if APP.py already called set_page_config (exception is swallowed).
    `title` sets the browser-tab title ("<title> · APP5"); default stays the hub name.
    """
    # Under the st.navigation router (Main.py) the page config is OWNED by the
    # router and set once, before navigation runs. A page re-calling
    # set_page_config here would (a) raise — it's no longer the first st command —
    # and (b) suppress st.navigation's sidebar. So skip entirely when the router
    # flag is set; the router already applied layout + the per-page tab title
    # comes from st.Page(title=).
    if st.session_state.get("_nav_router"):
        return
    if settings is None:
        settings = get_all_settings()
    wide = settings.get("wide_mode", DEFAULTS["wide_mode"]) == "1"
    from pathlib import Path
    _favicon = Path(__file__).resolve().parent.parent / "assets" / "logo_mark.png"
    try:
        st.set_page_config(
            page_title=f"{title} · HoopTracks" if title else "HoopTracks",
            page_icon=str(_favicon) if _favicon.exists() else "🏀",
            layout="wide" if wide else "centered",
            initial_sidebar_state="expanded",
        )
    except Exception:
        pass  # Already set by Main.py — ignore


def apply_theme_css(settings: dict = None) -> None:
    """
    Inject a <style> block that overrides accent colour and card backgrounds
    based on the stored (or supplied) settings dict.
    Call once near the top of any page that uses themed CSS classes.
    """
    if settings is None:
        settings = get_all_settings()

    accent     = settings.get("accent_color", DEFAULTS["accent_color"])
    style_name = settings.get("app_style",    DEFAULTS["app_style"])
    style      = STYLE_PRESETS.get(style_name, STYLE_PRESETS["Dark"])

    # accent hex → "r,g,b" so the Modern UI 2.0 layer can build rgba() glows
    h = accent.lstrip("#")
    try:
        accent_rgb = f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"
    except Exception:
        accent_rgb = "240,165,0"

    _good, _bad = semantic_pair(settings)

    css = f"""
<style>
/* ── Theme tokens consumed by the Modern UI 2.0 layer in styles.css ── */
:root {{
    --accent: {accent};
    --accent-rgb: {accent_rgb};
    --card-bg: {style['card_bg']};
    --card-bg-2: {style.get('card_bg_2', style['body_bg'])};
    --card-border: {style['card_border']};
    --body-bg: {style['body_bg']};
    --text: {style['text']};
    --subtext: {style['subtext']};
    --track: {style.get('track', '#21262d')};
    --card-grad: {style['card_grad']};
    --good: {_good};
    --bad: {_bad};
}}
/* ── Accent colour ─────────────────────────────────────────── */
.dash-card-value,
.pl-value,
.rpl-score {{
    color: {accent} !important;
}}
.score-winner          {{ color: {accent} !important; }}
.rank-ps               {{ color: {accent} !important; }}
.section-hdr           {{ border-left-color: {accent} !important; }}
.rat-title             {{ color: {accent} !important; }}
.rank-1                {{ background: {accent} !important; color: #000 !important; }}

/* ── Card backgrounds ──────────────────────────────────────── */
.dash-card {{
    background: {style['card_grad']} !important;
    border-color: {style['card_border']} !important;
}}
.score-card, .rank-card {{
    background: {style['card_bg']} !important;
    border-color: {style['card_border']} !important;
}}
.pl-card {{
    background: {style['card_grad']} !important;
    border-color: {style['card_border']} !important;
}}
.rat-card {{
    background: {style['card_grad']} !important;
    border-color: {style['card_border']} !important;
}}
.rpl-card {{
    background: {style['card_grad']} !important;
    border-color: {style['card_border']} !important;
}}

/* ── Subtext / meta ────────────────────────────────────────── */
.dash-card-meta,
.dash-card-sub,
.rank-rec,
.score-card-date,
.pl-meta,
.rpl-meta,
.rat-comp {{
    color: {style['subtext']} !important;
}}
</style>
"""
    st.markdown(css, unsafe_allow_html=True)
