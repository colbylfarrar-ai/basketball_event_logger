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
}

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
               "wide_mode", "scout_hidden_sections"}


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


def get_setting(key: str, default: str = "", email=None) -> str:
    email = _scope_email() if email is None else email
    # user-scoped key: prefer this coach's value, else fall through to the global one
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


def get_all_settings(email=None) -> dict:
    email = _scope_email() if email is None else email
    s = dict(DEFAULTS)                       # start with defaults
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
    if settings is None:
        settings = get_all_settings()
    wide = settings.get("wide_mode", DEFAULTS["wide_mode"]) == "1"
    try:
        st.set_page_config(
            page_title=f"{title} · APP5" if title else "Analytics Hub · APP5",
            page_icon="🏀",
            layout="wide" if wide else "centered",
            initial_sidebar_state="expanded",
        )
    except Exception:
        pass  # Already set by APP.py — ignore


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
    background: linear-gradient(135deg,#0f3460 0%,#16213e 100%) !important;
    border-color: #1f4d8a !important;
}}
.rat-card {{
    background: {style['card_grad']} !important;
    border-color: {style['card_border']} !important;
}}
.rpl-card {{
    background: linear-gradient(135deg,#0f3460 0%,#16213e 100%) !important;
    border-color: #1f4d8a !important;
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
