"""
APP.py — Streamlit multipage entry point.
Uses Streamlit's native file-based multipage routing (pages/ directory).
This file only sets global config and loads shared CSS.
"""
import streamlit as st
from pathlib import Path

# ── Page config (set once, applies to all pages) ──────────────────────────────
st.set_page_config(
    page_title="Analytics Hub",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS (loaded from assets/styles.css) ────────────────────────────────
_css_path = Path(__file__).resolve().parent / "assets" / "styles.css"
if _css_path.exists():
    st.markdown(
        f"<style>{_css_path.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )

# ── Landing content ────────────────────────────────────────────────────────────
st.title("📊 Analytics Hub")
st.markdown(
    "Use the **sidebar** to navigate between pages: "
    "Input Hub · Game Tracker · Rankings · Team Analytics · "
    "Players Hub · Officials Hub · Daily Breakdown · Settings."
)
