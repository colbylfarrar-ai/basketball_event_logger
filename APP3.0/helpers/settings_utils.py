"""
App-wide settings stored in app_settings (SQLite key/value table).
Provides theme CSS injection for Rankings and Team Analytics pages.
"""
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import streamlit as st
from Database.db import query, execute


# ══════════════════════════════════════════════════════════════════════════════
#  DEFAULTS & PALETTES
# ══════════════════════════════════════════════════════════════════════════════

DEFAULTS = {
    "default_team":  "",
    "accent_color":  "#f0a500",
    "color_scheme":  "Gold",
    "app_style":     "Dark",
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
        "subtext":     "#8b949e",
        "text":        "#f0f6fc",
    },
    "Midnight": {
        "label":       "Midnight Blue",
        "card_bg":     "#0b1120",
        "card_border": "#1a2744",
        "card_grad":   "linear-gradient(135deg,#06091a 0%,#0b1120 100%)",
        "body_bg":     "#06091a",
        "subtext":     "#7a8fa8",
        "text":        "#e8edf5",
    },
    "Carbon": {
        "label":       "Carbon",
        "card_bg":     "#1e1e1e",
        "card_border": "#3a3a3a",
        "card_grad":   "linear-gradient(135deg,#111111 0%,#1e1e1e 100%)",
        "body_bg":     "#111111",
        "subtext":     "#9a9a9a",
        "text":        "#f5f5f5",
    },
    "Slate": {
        "label":       "Slate",
        "card_bg":     "#1e2a3a",
        "card_border": "#2d4060",
        "card_grad":   "linear-gradient(135deg,#131d2b 0%,#1e2a3a 100%)",
        "body_bg":     "#131d2b",
        "subtext":     "#7d9bb5",
        "text":        "#e2ecf4",
    },
    "Forest": {
        "label":       "Forest",
        "card_bg":     "#162318",
        "card_border": "#27422a",
        "card_grad":   "linear-gradient(135deg,#0c170e 0%,#162318 100%)",
        "body_bg":     "#0c170e",
        "subtext":     "#7aa87f",
        "text":        "#e2f4e5",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  READ / WRITE
# ══════════════════════════════════════════════════════════════════════════════

def get_setting(key: str, default: str = "") -> str:
    rows = query("SELECT value FROM app_settings WHERE key=?", (key,))
    if rows:
        return rows[0]["value"]
    return default if default else DEFAULTS.get(key, "")


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)",
        (key, value),
    )


def get_all_settings() -> dict:
    rows = query("SELECT key, value FROM app_settings")
    s = dict(DEFAULTS)          # start with defaults
    for r in rows:
        s[r["key"]] = r["value"]
    return s


# ══════════════════════════════════════════════════════════════════════════════
#  THEME CSS INJECTION
# ══════════════════════════════════════════════════════════════════════════════

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

    # Derive a slightly lighter version of the accent for hover/active states
    # (simple: just add 20 to each channel via opacity overlay)
    css = f"""
<style>
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
