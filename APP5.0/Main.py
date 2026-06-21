"""
Main.py — multipage ROUTER for APP5.0 (st.navigation entrypoint).

The frame around every page: sets the page config ONCE, then defines a grouped,
sectioned sidebar (Analyze · Build · Plan & scout) via st.navigation and runs the
selected page. The executive dashboard that used to live here now lives in
pages/0_Analytics_Hub.py (the `default` page).

Why a router: st.navigation gives real sidebar SECTIONS + per-page icons the auto
pages/ discovery can't. Per the Streamlit docs, once st.navigation runs the app
ignores pages/ auto-discovery — so no doubled sidebar; the pages are referenced
explicitly below.

The set_page_config gotcha (cost a deploy attempt earlier): pages run AFTER
st.navigation has started, so a page's own set_page_config can't take effect — and
worse, re-calling it suppresses the nav sidebar. So the config MUST live here,
before navigation, and pages must SKIP their own set_page_config. We signal that
with st.session_state["_nav_router"]; settings_utils.apply_page_config honours it
and returns early. Everything else page_chrome does (CSS, theme, auth, cache-sync)
still runs per page.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Tell page_chrome/apply_page_config that the router owns the page config, so
# pages skip their own set_page_config (see module docstring).
st.session_state["_nav_router"] = True

# set_page_config MUST be the first st.* call. Layout follows the stored wide_mode.
try:
    from helpers.settings_utils import get_all_settings
    _wide = get_all_settings().get("wide_mode", "1") == "1"
except Exception:
    _wide = True
st.set_page_config(
    page_title="APP5 Analytics", page_icon="🏀",
    layout="wide" if _wide else "centered",
    initial_sidebar_state="expanded",
)

# Build → Analyze → Plan: the program's workflow, made legible in the sidebar.
_NAV = {
    "Analyze": [
        st.Page("pages/0_Analytics_Hub.py", title="Analytics Hub",
                icon=":material/dashboard:", default=True),
        st.Page("pages/5_Rankings.py", title="Rankings",
                icon=":material/leaderboard:"),
        st.Page("pages/6_Team_Dashboard.py", title="Team Dashboard",
                icon=":material/groups:"),
        st.Page("pages/7_Players.py", title="Players",
                icon=":material/person:"),
        st.Page("pages/10_Data_Explorer.py", title="Data Explorer",
                icon=":material/table_chart:"),
    ],
    "Build": [
        st.Page("pages/1_Input_Hub.py", title="Input Hub",
                icon=":material/edit_note:"),
        st.Page("pages/2_Game_Tracker.py", title="Game Tracker",
                icon=":material/sports_basketball:"),
        st.Page("pages/3_Event_Editor.py", title="Event Editor",
                icon=":material/edit:"),
        st.Page("pages/4_Schedule.py", title="Schedule",
                icon=":material/calendar_month:"),
        st.Page("pages/11_Setup.py", title="Setup",
                icon=":material/settings_suggest:"),
    ],
    "Plan & scout": [
        st.Page("pages/9_War_Room.py", title="War Room",
                icon=":material/strategy:"),
        st.Page("pages/8_Officials.py", title="Officials",
                icon=":material/sports:"),
        st.Page("pages/12_Settings.py", title="Settings",
                icon=":material/tune:"),
    ],
}

st.navigation(_NAV).run()
