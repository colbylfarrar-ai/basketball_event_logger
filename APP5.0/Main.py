"""
Main.py — multipage ROUTER for APP5.0 (st.navigation entrypoint).

The frame around every page: sets the page config ONCE, then defines a grouped,
sectioned sidebar (Analyze · Build · Plan & scout) via st.navigation and runs the
selected page. Team Dashboard is the `default` page — the coach's own team is
what the app opens on.

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

# Living-MLM overrides (founder batch item 7): fold any gate-adopted model
# constants onto the engine globals ONCE at app startup — takes effect on this
# process, so a deploy restart is what activates a newly-adopted set. Guarded:
# a bad/absent override row leaves the code defaults untouched.
try:
    import helpers.model_constants as _MC
    _MC.apply()
except Exception:
    pass

# Build → Analyze → Plan: the program's workflow, made legible in the sidebar.
_NAV = {
    "Analyze": [
        # The app opens on the coach's OWN team, not on the league. A front
        # office shows you your program first; the league is a place you go.
        # Team Dashboard resolves the team from the default_team setting and
        # falls back to the coach's identity team, so this lands somewhere
        # personal without any setup.
        st.Page("pages/6_Team_Dashboard.py", title="Team Dashboard",
                icon=":material/groups:", default=True),
        # Analytics Hub was CUT on 2026-09-05. Nine of its fourteen sections
        # restated Rankings or Players, and its "Jump in" block was a stale copy
        # of this very sidebar. The five that were genuinely its own moved to
        # Rankings → Spotlight (helpers/league_spotlight.py), so nothing a coach
        # could only get there was lost — there is just one league page now
        # instead of two that disagreed about which was the league page.
        st.Page("pages/5_Rankings.py", title="Rankings",
                icon=":material/leaderboard:"),
        st.Page("pages/7_Players.py", title="Players",
                icon=":material/person:"),
        st.Page("pages/14_Hall_of_Fame.py", title="Hall of Fame",
                icon=":material/emoji_events:"),
    ],
    "Build": [
        st.Page("pages/1_Input_Hub.py", title="Input Hub",
                icon=":material/edit_note:"),
        st.Page("pages/2_Game_Tracker.py", title="Game Tracker",
                icon=":material/sports_basketball:"),
        # The OTHER way a game gets its numbers, so it sits directly under the
        # Game Tracker rather than inside a settings page. It was the fourth tab
        # of "Roster & District" until 2026-09-12; that page is gone (see below).
        st.Page("pages/16_Box_Score_Entry.py", title="Box Score Entry",
                icon=":material/table_chart:"),
        st.Page("pages/3_Event_Editor.py", title="Event Editor",
                icon=":material/edit:"),
        # "Roster & District" (11_Setup.py) was REMOVED on 2026-09-12. Three of
        # its four tabs each edited ONE column of a row the Input Hub was
        # already editing — player position/availability, team district, game
        # type — which split one row across two pages and, worse, split its
        # ownership: those writes were scoped there and unscoped here. All three
        # moved into the Input Hub's grids, which now carry the scope. The
        # fourth tab was the box-score app above. Nothing was dropped.
        st.Page("pages/4_Schedule.py", title="Schedule",
                icon=":material/calendar_month:"),
    ],
    "Plan & scout": [
        st.Page("pages/9_War_Room.py", title="War Room",
                icon=":material/strategy:"),
        st.Page("pages/10_Whiteboard.py", title="Whiteboard",
                icon=":material/draw:"),
        st.Page("pages/8_Officials.py", title="Officials",
                icon=":material/sports:"),
    ],
    # Settings and FAQ sat under "Plan & scout", which is where a coach goes to
    # prepare for an opponent — neither page has anything to do with that. They
    # are the app's own controls, so they get their own section at the bottom.
    # Officials, Whiteboard, Rankings and the FAQ all keep their own entry,
    # because each carries real depth a coach needs. (Analytics Hub is the one
    # page ever removed — see the note above; its unique content is on Rankings.)
    "Settings & Help": [
        st.Page("pages/12_Settings.py", title="Settings",
                icon=":material/tune:"),
        st.Page("pages/15_FAQ.py", title="FAQ",
                icon=":material/help:"),
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
