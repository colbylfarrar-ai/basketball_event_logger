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

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

import helpers.auth as AUTH

# Tell page_chrome/apply_page_config that the router owns the page config, so
# pages skip their own set_page_config (see module docstring).
st.session_state["_nav_router"] = True

# set_page_config MUST be the first st.* call. Layout follows the stored wide_mode.
try:
    from helpers.settings_utils import get_all_settings
    _wide = get_all_settings().get("wide_mode", "1") == "1"
except Exception:
    _wide = True
_ASSETS = _ROOT / "assets"
_FAVICON = _ASSETS / "logo_mark.png"      # raster favicon (tools/make_brand.py)
st.set_page_config(
    page_title="HoopTracks",
    page_icon=str(_FAVICON) if _FAVICON.exists() else "🏀",
    layout="wide" if _wide else "centered",
    initial_sidebar_state="expanded",
)

# Brand lockup pinned to the TOP of the sidebar (above the nav) on every page, via
# st.logo. Two jobs: the app self-identifies as HoopTracks instead of a bare URL,
# and every shared screenshot carries the wordmark for free. The vector SVGs are
# the source of truth (crisp at any size, font rendered browser-side so no server
# font dependency); st.image accepts the raw SVG markup. icon_image is the square
# mark shown when the sidebar is collapsed.
try:
    st.logo(
        (_ASSETS / "logo_wordmark.svg").read_text(encoding="utf-8"),
        icon_image=(_ASSETS / "logo_mark.svg").read_text(encoding="utf-8"),
        size="large", link="https://app.hooptracks.com",
    )
except Exception:
    pass

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
    ],
    "Build": [
        st.Page("pages/1_Input_Hub.py", title="Input Hub",
                icon=":material/edit_note:"),
        st.Page("pages/2_Game_Tracker.py", title="Game Tracker",
                icon=":material/sports_basketball:"),
        st.Page("pages/3_Event_Editor.py", title="Event Editor",
                icon=":material/edit:"),
        st.Page("pages/11_Setup.py", title="Roster & District",
                icon=":material/settings_suggest:"),
        st.Page("pages/4_Schedule.py", title="Schedule",
                icon=":material/calendar_month:"),
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

# OSSAA bulk importer is ADMIN-ONLY — hidden from non-admins' sidebar entirely
# (the page also st.stop()s as a backstop). Resolve the role read-only here; the
# full login flow (st.stop on sign-in / not-authorized) runs per page in
# page_chrome, so we must NOT call require_login() from the router.
def _is_admin() -> bool:
    try:
        if not AUTH.auth_enabled():
            return True                      # auth off -> local owner is admin
        if not getattr(st.user, "is_logged_in", False):
            return False
        email = (getattr(st.user, "email", "") or "").strip().lower()
        return AUTH.lookup_role(email) == "admin"
    except Exception:
        return False                         # uncertain -> hide (admin-only)


if _is_admin():
    _NAV["Build"].append(
        st.Page("pages/13_OSSAA_Import.py", title="OSSAA Import",
                icon=":material/cloud_download:"))

st.navigation(_NAV).run()
