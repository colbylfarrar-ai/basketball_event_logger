import streamlit as st
from pathlib import Path

# ============================================================
#  APP.PY — STREAMLIT MULTIPAGE ENTRY POINT
#  - Loads global styles
#  - Registers pages in clean order
#  - No business logic
# ============================================================

# ------------------------------------------------------------
# Apply global CSS
# ------------------------------------------------------------
def load_styles():
    css_path = Path(__file__).resolve().parent / "assets" / "styles.css"
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


# ------------------------------------------------------------
# Configure Streamlit
# ------------------------------------------------------------
st.set_page_config(
    page_title="Analytics Hub",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

load_styles()

# ------------------------------------------------------------
# Sidebar Navigation
# ------------------------------------------------------------
st.sidebar.title("Navigation")

pages = {
    "1. Input Hub": "pages/1_Input_Hub.py",
    "2. Game Tracker": "pages/2_Game_Tracker.py",
    "4. Rankings": "pages/4_Rankings.py",
    "5. Team Analytics": "pages/5_Team_Analytics.py",
}

choice = st.sidebar.radio("Go to:", list(pages.keys()))

# ------------------------------------------------------------
# Load Selected Page
# ------------------------------------------------------------
page_path = Path(__file__).resolve().parent / pages[choice]
with open(page_path, "r", encoding="utf-8") as f:
    code = f.read()
    exec(code, globals())