import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from Database.db import query, initialize_database
from helpers.settings_utils import get_all_settings, set_setting, apply_theme_css

initialize_database()

cfg = get_all_settings()
apply_theme_css(cfg)

st.title("⚙️ Settings")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  DEFAULT TEAM
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🏀 Default Team")
st.caption(
    "Team Analytics will open to this team automatically. "
    "You can still switch at any time from the dropdown."
)

all_teams       = query("SELECT id, name FROM teams ORDER BY name")
team_names      = [t["name"] for t in all_teams]
current_default = cfg.get("default_team", "")

col_team, col_team_btn = st.columns([4, 1])
with col_team:
    sel_default_team = st.selectbox(
        "Default team",
        options=["(None)"] + team_names,
        index=(team_names.index(current_default) + 1
               if current_default in team_names else 0),
        key="settings_default_team",
        label_visibility="collapsed",
    )
with col_team_btn:
    if st.button("Save", key="save_team", type="primary", use_container_width=True):
        val = "" if sel_default_team == "(None)" else sel_default_team
        set_setting("default_team", val)
        st.success("Saved!" if val else "Cleared.")
        st.cache_data.clear()
