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
from helpers.settings_utils import get_all_settings, set_setting, apply_theme_css
from Database.supabase_sync import (
    load_seasons_config,
    save_seasons_config,
    get_active_season_info,
    switch_season,
    add_season,
    update_season_credentials,
    get_sync_status,
    push_to_supabase,
    pull_from_supabase,
    is_online,
)

initialize_database()
cfg = get_all_settings()
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
db_path     = get_db_path()

col_a, col_b = st.columns(2)
with col_a:
    st.markdown(f"**Active season:** `{active_name}`")
    st.markdown(f"**Database file:** `{db_path.name}`")
with col_b:
    rows_total = 0
    for tbl in ["teams", "games", "players", "game_events"]:
        try:
            r = query(f"SELECT COUNT(*) AS n FROM {tbl}")
            rows_total += r[0]["n"] if r else 0
        except Exception:
            pass
    st.markdown(f"**Records (teams+games+players+events):** {rows_total:,}")
    supabase_url = (active_info or {}).get("supabase_url", "")
    cloud_icon = "☁️ linked" if supabase_url else "🔌 not linked"
    st.markdown(f"**Cloud:** {cloud_icon}")

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
with st.expander("➕ Start a New Season", expanded=False):
    st.markdown(
        "Creates a fresh, empty database for the new season. "
        "Your current season's data is preserved. "
        "Optionally link it to a Supabase project for cloud backup."
    )
    new_name = st.text_input(
        "Season name (e.g. 2025-26)",
        key="new_season_name",
        placeholder="2025-26",
    )
    new_url = st.text_input(
        "Supabase URL (optional — leave blank to add later)",
        key="new_season_url",
        placeholder="https://yourproject.supabase.co",
    )
    new_key = st.text_input(
        "Supabase Anon Key (optional)",
        key="new_season_key",
        type="password",
        placeholder="eyJhbGci…",
    )
    new_proj = st.text_input(
        "Supabase Project ID (optional)",
        key="new_season_proj",
        placeholder="abcdefghijklmnop",
    )
    col_ns1, col_ns2 = st.columns(2)
    with col_ns1:
        if st.button("Create Season", key="btn_create_season", type="primary",
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
                )
                if ok:
                    st.success(
                        f"Season **{new_name.strip()}** created with a fresh database. "
                        "Click **Switch** above to activate it."
                    )
                    st.rerun()
                else:
                    st.error("Failed to create season. Check the name and try again.")
    with col_ns2:
        st.caption(
            "💡 To get a Supabase project:\n"
            "1. Go to [supabase.com](https://supabase.com)\n"
            "2. Create a new project\n"
            "3. Copy the URL and anon key from Project Settings → API"
        )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
#  CLOUD SYNC
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### ☁️ Cloud Sync (Supabase)")

sync_status = get_sync_status()

# Status indicators
col_s1, col_s2, col_s3 = st.columns(3)
with col_s1:
    icon = "🟢" if sync_status["online"] else "🔴"
    st.markdown(f"{icon} **Internet:** {'Online' if sync_status['online'] else 'Offline'}")
with col_s2:
    icon = "🟢" if sync_status["configured"] else "⚪"
    st.markdown(f"{icon} **Supabase:** {'Configured' if sync_status['configured'] else 'Not configured'}")
with col_s3:
    icon = "🟢" if sync_status["client_ok"] else ("🔴" if sync_status["configured"] else "⚪")
    st.markdown(f"{icon} **Connection:** {'OK' if sync_status['client_ok'] else ('Failed' if sync_status['configured'] else 'N/A')}")

st.markdown("---")

if not sync_status["configured"]:
    # Check whether this is a deployed (no seasons.json) or local context
    _has_seasons_file = (
        Path(__file__).resolve().parent.parent / "Database" / "seasons.json"
    ).exists()

    if not _has_seasons_file:
        # Deployed on Streamlit Cloud — guide them to use secrets
        st.warning(
            "**Supabase not configured for this deployment.**\n\n"
            "Add your credentials to **Streamlit secrets** (not here — the Settings "
            "UI is for local use only):\n\n"
            "1. Go to your app on **share.streamlit.io**\n"
            "2. Click **⋮ → Settings → Secrets**\n"
            "3. Add these two lines:\n"
            "```toml\n"
            "SUPABASE_URL = \"https://your-project.supabase.co\"\n"
            "SUPABASE_KEY = \"eyJhbGci…your-anon-key\"\n"
            "```\n"
            "4. Save — the app restarts and sync activates automatically."
        )
    else:
        # Local — guide them to use the expander below
        st.info(
            "No Supabase credentials for this season. "
            "Expand **Edit Supabase Credentials** below to add them."
        )
else:
    col_push, col_pull = st.columns(2)

    with col_push:
        st.markdown("**⬆ Push — Local → Cloud**")
        st.caption(
            "Uploads your local data to Supabase. "
            "Overwrites any cloud data that differs. "
            "Use this after working offline."
        )
        if st.button("Push to Supabase", key="btn_push", type="primary",
                     use_container_width=True, disabled=not sync_status["online"]):
            log_lines: list[str] = []

            def _log(msg: str):
                log_lines.append(msg)

            with st.spinner("Pushing…"):
                ok, msg = push_to_supabase(status_cb=_log)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
            if log_lines:
                with st.expander("Push log", expanded=not ok):
                    st.text("\n".join(log_lines))
            st.cache_data.clear()

    with col_pull:
        st.markdown("**⬇ Pull — Cloud → Local**")
        st.caption(
            "Downloads Supabase data into your local DB. "
            "**Replaces all local data.** "
            "Use this to get changes from another device."
        )
        if st.button("Pull from Supabase", key="btn_pull", use_container_width=True,
                     disabled=not sync_status["online"]):
            confirm = st.session_state.get("pull_confirm", False)
            if not confirm:
                st.session_state["pull_confirm"] = True
                st.warning(
                    "⚠ This will overwrite ALL local data with the cloud version. "
                    "Click **Pull from Supabase** again to confirm."
                )
            else:
                st.session_state["pull_confirm"] = False
                log_lines: list[str] = []

                def _log2(msg: str):
                    log_lines.append(msg)

                with st.spinner("Pulling…"):
                    ok, msg = pull_from_supabase(status_cb=_log2)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
                if log_lines:
                    with st.expander("Pull log", expanded=not ok):
                        st.text("\n".join(log_lines))
                st.cache_data.clear()

st.markdown("---")

# ── Update credentials ──────────────────────────────────────────────────────
with st.expander("🔑 Edit Supabase Credentials for Current Season", expanded=False):
    cur_url = (active_info or {}).get("supabase_url", "")
    cur_key = (active_info or {}).get("supabase_key", "")
    cur_proj = (active_info or {}).get("supabase_project_id", "")

    upd_url  = st.text_input("Supabase URL",        value=cur_url,  key="upd_url")
    upd_key  = st.text_input("Supabase Anon Key",   value=cur_key,  key="upd_key",  type="password")
    upd_proj = st.text_input("Project ID (optional)", value=cur_proj, key="upd_proj")

    if st.button("Save Credentials", key="btn_save_creds", type="primary"):
        ok = update_season_credentials(active_name, upd_url, upd_key, upd_proj)
        if ok:
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
