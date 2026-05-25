"""
APP.py — Streamlit multipage entry point.

All data lives in Supabase PostgreSQL — no local database, no sync required.
"""
import sys
import streamlit as st
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Page config (respects wide_mode setting) ───────────────────────────────────
_layout = "wide"
try:
    from Database.db import query as _q
    _rows = _q("SELECT value FROM app_settings WHERE key='wide_mode'")
    if _rows and _rows[0]["value"] == "0":
        _layout = "centered"
except Exception:
    pass

st.set_page_config(
    page_title="Analytics Hub",
    page_icon="📊",
    layout=_layout,
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────────
_css_path = Path(__file__).resolve().parent / "assets" / "styles.css"
if _css_path.exists():
    st.markdown(
        f"<style>{_css_path.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )

# ── Landing content ────────────────────────────────────────────────────────────
st.title("📊 Analytics Hub")
st.markdown(
    "Use the **sidebar** to navigate: "
    "Input Hub · Game Tracker · Rankings · Team Analytics · "
    "Players Hub · Officials Hub · Daily Breakdown · Settings."
)

# ── Supabase connection badge ──────────────────────────────────────────────────
try:
    from Database.db import get_connection as _gc
    _gc()
    st.caption("🟢 Connected to Supabase")
except Exception as _e:
    st.warning(f"⚠️ Database not connected — {_e}")
