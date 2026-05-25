"""
APP.py — Streamlit multipage entry point.

On startup, if connected to the internet and Supabase is configured,
pulls the latest data from Supabase into the local SQLite DB.
After that the app runs entirely on SQLite (offline-safe).
"""
import streamlit as st
from pathlib import Path

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Analytics Hub",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────────
_css_path = Path(__file__).resolve().parent / "assets" / "styles.css"
if _css_path.exists():
    st.markdown(
        f"<style>{_css_path.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )

# ── Startup cloud sync (pull once per session) ─────────────────────────────────
if "startup_sync_done" not in st.session_state:
    st.session_state["startup_sync_done"] = True
    try:
        from Database.supabase_sync import auto_sync_on_startup, get_sync_status

        status = get_sync_status()
        if status["online"] and status["configured"]:
            with st.spinner("☁️ Syncing from cloud…"):
                result = auto_sync_on_startup()
            # Only show if sync actually ran (not just "offline" message)
            if "✅" in result:
                st.toast("☁️ Cloud sync complete", icon="✅")
        # If offline or not configured — silent, just use local DB
    except Exception:
        pass  # Never block startup due to sync errors

# ── Landing content ─────────────────────────────────────────────────────────────
st.title("📊 Analytics Hub")
st.markdown(
    "Use the **sidebar** to navigate: "
    "Input Hub · Game Tracker · Rankings · Team Analytics · "
    "Players Hub · Officials Hub · Daily Breakdown · Settings."
)

# ── Connection status badge ────────────────────────────────────────────────────
try:
    from Database.supabase_sync import get_sync_status
    s = get_sync_status()
    if s["configured"]:
        badge = "🟢 Online — cloud sync active" if s["online"] else "🔴 Offline — local database only"
        st.caption(badge)
except Exception:
    pass
