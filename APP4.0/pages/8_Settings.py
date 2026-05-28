"""
8_Settings.py — App-wide preferences.

Three controls, all persisted to the app_settings key/value table:
  • Wide Mode      — page layout (wide vs centered)         → wide_mode
  • Appearance     — dark style preset + accent colour      → app_style / accent_color
  • Default Team   — team pre-selected across other pages    → default_team

All read/write goes through helpers/settings_utils.py.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from database.db import query
from helpers.settings_utils import (
    set_setting, ACCENT_PRESETS, STYLE_PRESETS, DEFAULTS,
)
from helpers.ui import page_chrome

_cfg, _ = page_chrome()


st.title("⚙️ Settings")
st.caption("Changes are saved immediately. Reload other pages to see them applied.")


# ══════════════════════════════════════════════════════════════════════════════
#  LAYOUT — Wide Mode
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Layout")

wide_now = _cfg.get("wide_mode", DEFAULTS["wide_mode"]) == "1"
wide = st.toggle(
    "Wide mode",
    value=wide_now,
    help="Use the full browser width. Off centers content in a narrower column.",
)
if wide != wide_now:
    set_setting("wide_mode", "1" if wide else "0")
    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  APPEARANCE — Dark style + accent
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Appearance")

style_names = list(STYLE_PRESETS.keys())
style_labels = [STYLE_PRESETS[n]["label"] for n in style_names]
cur_style = _cfg.get("app_style", DEFAULTS["app_style"])
if cur_style not in style_names:
    cur_style = DEFAULTS["app_style"]

c1, c2 = st.columns(2)

with c1:
    new_style_label = st.selectbox(
        "Dark theme",
        style_labels,
        index=style_names.index(cur_style),
        help="Background and card colour scheme. All presets are dark themes.",
    )
    new_style = style_names[style_labels.index(new_style_label)]
    if new_style != cur_style:
        set_setting("app_style", new_style)
        st.rerun()

with c2:
    accent_names = list(ACCENT_PRESETS.keys())
    cur_scheme = _cfg.get("color_scheme", DEFAULTS["color_scheme"])
    if cur_scheme not in accent_names:
        cur_scheme = DEFAULTS["color_scheme"]
    new_scheme = st.selectbox(
        "Accent colour",
        accent_names,
        index=accent_names.index(cur_scheme),
        help="Highlight colour for values, winners and the #1 rank.",
    )
    if new_scheme != cur_scheme:
        set_setting("color_scheme", new_scheme)
        set_setting("accent_color", ACCENT_PRESETS[new_scheme])
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  DEFAULT TEAM
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Default Team")

teams = query("SELECT name FROM teams ORDER BY name")
team_names = [t["name"] for t in teams]

if not team_names:
    st.info("No teams yet — add teams in the Input Hub to set a default.")
else:
    options = ["(none)"] + team_names
    cur_team = _cfg.get("default_team", DEFAULTS["default_team"])
    idx = options.index(cur_team) if cur_team in options else 0
    new_team = st.selectbox(
        "Pre-selected team",
        options,
        index=idx,
        help="This team is highlighted/selected by default on other pages.",
    )
    saved = "" if new_team == "(none)" else new_team
    if saved != cur_team:
        set_setting("default_team", saved)
        st.rerun()
