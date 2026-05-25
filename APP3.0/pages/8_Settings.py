"""
8_Settings.py
=============
Settings, Season Management, and Cloud Sync controls.
All logic is pure Python — no agent required.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from Database.db import query, initialize_database, get_db_path
from helpers.settings_utils import get_all_settings, set_setting, apply_page_config, apply_theme_css
from Database.supabase_sync import (
    load_seasons_config,
    save_seasons_config,
    get_active_season_info,
    switch_season,
    add_season,
    update_season_credentials,
    is_online,
)

initialize_database()
cfg = get_all_settings()
apply_page_config(cfg)
apply_theme_css(cfg)

st.title("⚙️ Settings")

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

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  SEASON MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🗓️ Season Management")
st.caption(
    "Each season stores data in its own SQLite file and optionally syncs "
    "to a dedicated Supabase project. Switching seasons hot-swaps the database — "
    "the app reloads automatically."
)

seasons_cfg = load_seasons_config()
active_name = seasons_cfg.get("active_season", "")
all_seasons = list(seasons_cfg.get("seasons", {}).keys())

# ── Current season status ──────────────────────────────────────────────────
active_info = get_active_season_info()

col_a, col_b = st.columns(2)
with col_a:
    st.markdown(f"**Active season:** `{active_name}`")
    st.markdown("**Database:** Supabase PostgreSQL")
with col_b:
    rows_total = 0
    for tbl in ["teams", "games", "players", "game_events"]:
        try:
            r = query(f"SELECT COUNT(*) AS n FROM {tbl}")
            rows_total += r[0]["n"] if r else 0
        except Exception:
            pass
    st.markdown(f"**Records (teams+games+players+events):** {rows_total:,}")
    try:
        from Database.db import get_connection as _gc
        _gc()
        st.markdown("**Connection:** 🟢 Connected")
    except Exception:
        st.markdown("**Connection:** 🔴 Not connected")

st.markdown("---")

# ── Switch season ──────────────────────────────────────────────────────────
if len(all_seasons) > 1:
    col_sw, col_sw_btn = st.columns([4, 1])
    with col_sw:
        target = st.selectbox(
            "Switch to season",
            options=[s for s in all_seasons if s != active_name],
            key="switch_season_select",
            label_visibility="collapsed",
        )
    with col_sw_btn:
        if st.button("Switch", key="btn_switch_season", use_container_width=True):
            switch_season(target)
            st.success(f"Switched to **{target}**. Reloading…")
            st.cache_data.clear()
            st.rerun()
else:
    st.info("Only one season exists. Add a new season below to enable switching.")

st.markdown("---")

# ── Add New Season ─────────────────────────────────────────────────────────
with st.expander("➕ Register a New Season", expanded=False):
    st.markdown(
        "Each season is a separate **Supabase project**. "
        "Create a new project on [supabase.com](https://supabase.com), "
        "apply the schema, then register its credentials here."
    )
    new_name = st.text_input(
        "Season name (e.g. 2025-26)",
        key="new_season_name",
        placeholder="2025-26",
    )
    new_url = st.text_input(
        "Supabase URL",
        key="new_season_url",
        placeholder="https://yourproject.supabase.co",
    )
    new_key = st.text_input(
        "Supabase Anon Key",
        key="new_season_key",
        type="password",
        placeholder="eyJhbGci…",
    )
    new_dbpw = st.text_input(
        "Database Password",
        key="new_season_dbpw",
        type="password",
        placeholder="your-supabase-db-password",
        help="Found at: Supabase dashboard → Project Settings → Database → Database Password",
    )
    new_proj = st.text_input(
        "Project ID (optional)",
        key="new_season_proj",
        placeholder="abcdefghijklmnop",
    )
    col_ns1, col_ns2 = st.columns(2)
    with col_ns1:
        if st.button("Register Season", key="btn_create_season", type="primary",
                     use_container_width=True):
            if not new_name.strip():
                st.error("Enter a season name.")
            elif new_name.strip() in all_seasons:
                st.error(f"Season '{new_name.strip()}' already exists.")
            else:
                ok = add_season(
                    name=new_name.strip(),
                    supabase_url=new_url,
                    supabase_key=new_key,
                    supabase_project_id=new_proj,
                    supabase_db_password=new_dbpw,
                )
                if ok:
                    st.success(
                        f"Season **{new_name.strip()}** registered. "
                        "Click **Switch** above to activate it."
                    )
                    st.rerun()
                else:
                    st.error("Failed to register season. Check the name and try again.")
    with col_ns2:
        st.caption(
            "💡 Steps:\n"
            "1. Create a new project on [supabase.com](https://supabase.com)\n"
            "2. Run the schema SQL in the Supabase SQL editor\n"
            "3. Copy the URL from Project Settings → API\n"
            "4. Copy the DB password from Project Settings → Database"
        )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE CONNECTION
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 🗄️ Database Connection")
st.caption(
    "All data reads and writes go directly to Supabase PostgreSQL. "
    "There is no local database — Supabase is the single source of truth."
)

_online = is_online()
_db_ok  = False
_db_err = ""
try:
    from Database.db import get_connection as _gc
    _gc()
    _db_ok = True
except Exception as _exc:
    _db_err = str(_exc)

col_s1, col_s2 = st.columns(2)
with col_s1:
    st.markdown(f"{'🟢' if _online else '🔴'} **Internet:** {'Online' if _online else 'Offline'}")
with col_s2:
    st.markdown(f"{'🟢' if _db_ok else '🔴'} **PostgreSQL:** {'Connected' if _db_ok else 'Not connected'}")

if not _db_ok:
    _has_seasons_file = (
        Path(__file__).resolve().parent.parent / "Database" / "seasons.json"
    ).exists()

    if not _has_seasons_file:
        st.warning(
            "**Database not configured.**\n\n"
            "Add your Supabase database password to **Streamlit Secrets**:\n\n"
            "1. Go to your app on **share.streamlit.io**\n"
            "2. Click **⋮ → Settings → Secrets**\n"
            "3. Add:\n"
            "```toml\n"
            "SUPABASE_URL = \"https://your-project.supabase.co\"\n"
            "SUPABASE_DB_PASSWORD = \"your-database-password\"\n"
            "```\n"
            "Find your password at: "
            "Supabase dashboard → Project Settings → Database → Database Password\n\n"
            "4. Save — the app will restart and connect automatically."
        )
    else:
        st.info(
            "No database password for this season. "
            "Expand **Edit Credentials** below and add your Database Password."
        )
    if _db_err:
        with st.expander("Error details"):
            st.code(_db_err)

st.markdown("---")

# ── Update credentials ──────────────────────────────────────────────────────
with st.expander("🔑 Edit Credentials for Current Season", expanded=False):
    cur_url  = (active_info or {}).get("supabase_url", "")
    cur_key  = (active_info or {}).get("supabase_key", "")
    cur_proj = (active_info or {}).get("supabase_project_id", "")
    cur_dbpw = (active_info or {}).get("supabase_db_password", "")

    upd_url  = st.text_input("Supabase URL",       value=cur_url,  key="upd_url")
    upd_key  = st.text_input("Supabase Anon Key",  value=cur_key,  key="upd_key",  type="password")
    upd_dbpw = st.text_input("Database Password",  value=cur_dbpw, key="upd_dbpw", type="password",
                              help="Supabase dashboard → Project Settings → Database → Database Password")
    upd_proj = st.text_input("Project ID (optional)", value=cur_proj, key="upd_proj")

    if st.button("Save Credentials", key="btn_save_creds", type="primary"):
        ok = update_season_credentials(active_name, upd_url, upd_key, upd_proj)
        if ok:
            # Also save db password (update_season_credentials doesn't handle it)
            try:
                import json as _json
                from Database.supabase_sync import load_seasons_config, save_seasons_config
                _scfg = load_seasons_config()
                if active_name in _scfg.get("seasons", {}):
                    _scfg["seasons"][active_name]["supabase_db_password"] = upd_dbpw.strip()
                    save_seasons_config(_scfg)
            except Exception:
                pass
            st.success("Credentials saved.")
            st.rerun()
        else:
            st.error("Failed to save credentials.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  APPEARANCE
# ══════════════════════════════════════════════════════════════════════════════
from helpers.settings_utils import ACCENT_PRESETS, STYLE_PRESETS

st.markdown("### 🎨 Appearance")

col_c1, col_c2 = st.columns(2)

with col_c1:
    st.markdown("**Accent Colour**")
    preset_names = list(ACCENT_PRESETS.keys())
    cur_scheme = cfg.get("color_scheme", "Gold")
    scheme_idx = preset_names.index(cur_scheme) if cur_scheme in preset_names else 0
    sel_scheme = st.selectbox(
        "Accent colour preset",
        options=preset_names,
        index=scheme_idx,
        key="sel_scheme",
        label_visibility="collapsed",
    )
    if st.button("Apply Accent", key="btn_accent", type="primary", use_container_width=True):
        set_setting("color_scheme", sel_scheme)
        set_setting("accent_color", ACCENT_PRESETS[sel_scheme])
        st.success(f"Accent set to {sel_scheme}.")
        st.rerun()

with col_c2:
    st.markdown("**App Style**")
    style_names = list(STYLE_PRESETS.keys())
    cur_style   = cfg.get("app_style", "Dark")
    style_idx   = style_names.index(cur_style) if cur_style in style_names else 0
    sel_style   = st.selectbox(
        "App style",
        options=style_names,
        format_func=lambda k: STYLE_PRESETS[k]["label"],
        index=style_idx,
        key="sel_style",
        label_visibility="collapsed",
    )
    if st.button("Apply Style", key="btn_style", type="primary", use_container_width=True):
        set_setting("app_style", sel_style)
        st.success(f"Style set to {sel_style}.")
        st.rerun()

st.markdown("---")

# ── Wide mode toggle ────────────────────────────────────────────────────────────
st.markdown("**Layout**")
_wide_now = cfg.get("wide_mode", "1") == "1"
_wide_new = st.toggle(
    "Wide mode",
    value=_wide_now,
    key="toggle_wide_mode",
    help="Use the full browser width. Turn off for a narrower centred layout.",
)
if _wide_new != _wide_now:
    set_setting("wide_mode", "1" if _wide_new else "0")
    st.success("Layout updated — reloading…")
    st.cache_data.clear()
    st.rerun()
