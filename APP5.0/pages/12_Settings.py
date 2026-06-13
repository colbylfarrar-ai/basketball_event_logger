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

from database.db import query, execute
from helpers.settings_utils import (
    set_setting, get_setting, ACCENT_PRESETS, STYLE_PRESETS, DEFAULTS,
)
from helpers.ui import page_chrome, team_color
import helpers.auth as AUTH

_cfg, _ = page_chrome("Settings")


st.title("Settings")
st.caption("Changes are saved immediately — other pages pick them up automatically "
           "the next time they load.")


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


# ══════════════════════════════════════════════════════════════════════════════
#  TEAM COLOURS
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Team colours")
st.caption("Give a team its own identity colour — used in its charts and the box "
           "score. Auto derives a stable colour from the team name; switch on "
           "Custom to override it.")

_tc_rows = query("SELECT id, name FROM teams ORDER BY name")
if not _tc_rows:
    st.info("No teams yet — add teams in the Input Hub first.")
else:
    tc1, tc2 = st.columns([3, 2])
    with tc1:
        _tc_team = st.selectbox("Team", _tc_rows, format_func=lambda r: r["name"],
                                key="tc_team")
    _tid = _tc_team["id"]
    _key = f"team_color::{_tid}"
    _cur = get_setting(_key, "")
    _auto = team_color(_tc_team["name"])
    with tc2:
        _use_custom = st.toggle("Custom colour", value=bool(_cur), key="tc_custom",
                                help="Off = Auto (derived from the team name).")
    if _use_custom:
        _picked = st.color_picker("Pick a colour", value=_cur or _auto, key="tc_pick")
        if _picked != _cur:
            set_setting(_key, _picked)
            st.rerun()
    elif _cur:                       # toggled off → clear the override
        set_setting(_key, "")
        st.rerun()
    st.markdown(
        f"<span style='display:inline-block;width:16px;height:16px;border-radius:4px;"
        f"background:{_cur or _auto};vertical-align:middle;margin-right:8px'></span>"
        f"<span style='color:var(--subtext)'>"
        f"{'Custom' if _cur else 'Auto'} · {_cur or _auto}</span>",
        unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  ACCOUNT & USERS  (login is enabled by [auth] in .streamlit/secrets.toml)
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Account & users")

_me = AUTH.current_user()

# ── Coaches' Co-op — the per-coach share-to-scout toggle (DEFAULT Solo) ─────────
# Visible to every signed-in coach (admin + coach). The whole reciprocity engine:
# Solo keeps your tracked depth private and off the pool; League-wide shares your
# games AND unlocks scouting of every other league-wide team.
if AUTH.auth_enabled() and _me.get("email"):
    st.markdown("### 🤝 Coaches' Co-op")
    _my_team = _me.get("team_id")
    if _my_team is None:
        st.caption("Join the **Coaches' Co-op** to share tracked games and scout "
                   "every league-wide team — but the opt-in is per **team**, so "
                   "ask the admin to assign you a team first.")
    else:
        _lw = AUTH.get_shares_pool(_me["email"])
        st.caption(f"Your team is currently "
                   f"**{'League-wide' if _lw else 'Solo (private)'}**.")
        _new_lw = st.toggle(
            "League-wide — share to scout", value=_lw, key="me_shares_pool",
            help="On (League-wide): your TEAM's tracked games join the shared pool "
                 "AND every coach on your team scouts every other league-wide team. "
                 "Off (Solo): full depth on your own games only; your tracked data "
                 "stays private (others see just your box scores).")
        st.caption("**Team-level, private by default.** This switch is for your "
                   "whole team — turn it on and *all* coaches on your team share "
                   "and scout. Flipping back to **Solo** stops sharing *future* "
                   "games; games already shared stay in the pool until the season "
                   "ends. The trade is reciprocal: share to scout.")
        if _new_lw != _lw:
            AUTH.set_shares_pool(_me["email"], _new_lw)
            st.rerun()
    st.divider()

if not AUTH.auth_enabled():
    st.info(
        "Sign-in is currently **off** — anyone who can reach this app can use "
        "it. That's fine while it runs only on your own computer, but turn "
        "sign-in on before sharing it with other coaches. Setup instructions "
        "for the app owner: copy `.streamlit/secrets.toml.example` to "
        "`.streamlit/secrets.toml`, fill in the Google OAuth credentials, and "
        "see `AUTH_SETUP.md`.")
elif _me["role"] != "admin":
    st.caption(f"Signed in as **{_me['email']}** ({_me['role']}). "
               "Only the admin can manage users.")
    if st.button("Log out", key="au_logout"):
        st.logout()
else:
    st.caption(f"Signed in as **{_me['email']}** (admin).")
    if st.button("Log out", key="au_logout"):
        st.logout()

    # ── Review panel — coaches' pending delete requests (write-authz) ─────────
    import helpers.change_requests as CR
    _pend = CR.pending()
    st.markdown(f"### 🗳️ Review panel ({len(_pend)})")
    if not _pend:
        st.caption("No pending requests. When a coach deletes shared data it waits "
                   "here — nothing is removed until you accept it.")
    else:
        st.caption("A coach asked to delete the items below. **Accept** runs the "
                   "delete; **Reject** discards the request. Nothing is gone yet.")
        for _cr in _pend:
            _c1, _c2, _c3 = st.columns([6, 1, 1])
            _c1.write(f"🗑️ Delete {_cr['label']} · by {_cr['requester'] or '—'} · "
                      f"{_cr['created_at']}")
            if _c2.button("Accept", key=f"cr_ok_{_cr['id']}", type="primary"):
                CR.accept(_cr["id"], _me["email"])
                st.cache_data.clear()
                st.rerun()
            if _c3.button("Reject", key=f"cr_no_{_cr['id']}"):
                CR.reject(_cr["id"], _me["email"])
                st.rerun()
    st.divider()

    # ── Audit log — who changed what (moderation) ────────────────────────────
    with st.expander("🧾 Audit log — recent data changes"):
        _actors = [r["actor"] for r in
                   query("SELECT DISTINCT actor FROM audit_log ORDER BY actor")]
        _pick = st.selectbox("Filter by coach", ["(all)"] + _actors, key="aud_actor")
        _aq = ('SELECT ts AS "When", actor AS "Coach", op AS "Op", '
               'table_name AS "Table", row_id AS "Row", rowcount AS "#", '
               'detail AS "SQL" FROM audit_log {} ORDER BY id DESC LIMIT 300')
        _arows = (query(_aq.format("")) if _pick == "(all)"
                  else query(_aq.format("WHERE actor=?"), (_pick,)))
        if not _arows:
            st.caption("No changes logged yet. Every team / player / game / official "
                       "edit or delete — and event corrections — lands here with the "
                       "coach who made it.")
        else:
            st.caption(f"Most recent {len(_arows)} changes (newest first). Spot a "
                       "coach acting out → ban them above, then restore from backup "
                       "if needed.")
            st.dataframe(_arows, hide_index=True, width="stretch")
    st.divider()

    _team_rows = query("SELECT id, name FROM teams ORDER BY name")
    _team_opts = [None] + [r["id"] for r in _team_rows]
    _team_name = {r["id"]: r["name"] for r in _team_rows}

    def _team_label(i):
        return "(no team)" if i is None else _team_name.get(i, f"#{i}")

    for _u in AUTH.list_users():
        _email = _u["email"]
        _is_self = _email == _me["email"]
        _plan = _u["plan"] if _u["plan"] in AUTH.PLANS else "free"
        _team_lw = AUTH.get_team_shares_pool(_u["team_id"])
        _coop = ("🚫 BANNED" if _u.get("pool_banned")
                 else ("League-wide" if _team_lw else "Solo"))
        _hdr = (f"{_email} · {_u['role']} · {_plan} · {_coop}"
                + (f" · {_team_label(_u['team_id'])}" if _u["team_id"] else ""))
        with st.expander(_hdr):
            mc1, mc2 = st.columns(2)
            _role = mc1.selectbox(
                "Role", AUTH.ROLES, index=AUTH.ROLES.index(_u["role"]),
                key=f"role_{_email}", disabled=_is_self,
                help="You can't change your own role." if _is_self else None)
            if not _is_self and _role != _u["role"]:
                AUTH.add_user(_email, _role)         # upserts role only
                st.rerun()
            _newplan = mc2.selectbox(
                "Plan", AUTH.PLANS, index=AUTH.PLANS.index(_plan),
                key=f"plan_{_email}",
                help="Paid unlocks tracked depth + the mobile tracker app.")
            if _newplan != _plan:
                AUTH.set_plan(_email, _newplan)
                st.rerun()
            _curteam = _u["team_id"] if _u["team_id"] in _team_opts else None
            _newteam = st.selectbox(
                "Team", _team_opts, index=_team_opts.index(_curteam),
                format_func=_team_label, key=f"team_{_email}",
                help="The coach's own team — defines their own-data scope.")
            if _newteam != _u["team_id"]:
                AUTH.set_team(_email, _newteam)
                st.rerun()

            if _u["team_id"] is None:
                st.caption("🤝 Coaches' Co-op: assign a team above first — the "
                           "opt-in is per team.")
            else:
                _coop_on = AUTH.get_team_shares_pool(_u["team_id"])
                _new_coop = st.toggle(
                    "Coaches' Co-op: League-wide (team)", value=_coop_on,
                    key=f"coop_{_email}",
                    help=("TEAM-LEVEL: on = this coach's whole team shares tracked "
                          "games to the pool and every coach on it scouts every "
                          f"league-wide team (reciprocal). Affects ALL coaches on "
                          f"{_team_label(_u['team_id'])}. Off = Solo/private. Comp a "
                          "founding cohort League-wide so the pool isn't empty."))
                if _new_coop != _coop_on:
                    AUTH.set_team_shares_pool(_u["team_id"], _new_coop)
                    st.rerun()

            _banned = bool(_u.get("pool_banned"))
            _new_ban = st.toggle(
                "🚫 Ban from Co-op (bad data)", value=_banned,
                key=f"ban_{_email}",
                help="Admin moderation: purge this coach's tracked games from the "
                     "league pool AND hide the pool from them (forced Solo), "
                     "regardless of their own toggle. They keep full depth on their "
                     "own team. Handle any refund separately.")
            if _new_ban != _banned:
                AUTH.set_pool_banned(_email, _new_ban)
                st.rerun()

            st.markdown("**Mobile tracker token**")
            _tok = AUTH.get_tracker_token(_email)
            if _tok:
                st.code(_tok, language=None)
                if st.button("Revoke token", key=f"tokrm_{_email}"):
                    AUTH.clear_tracker_token(_email)
                    st.rerun()
            else:
                _can_token = (_newplan == "paid") or (_role == "admin")
                if st.button("Issue token", key=f"tokgen_{_email}",
                             disabled=not _can_token,
                             help=None if _can_token else "Paid/admin only."):
                    AUTH.set_tracker_token(_email)
                    st.rerun()
                st.caption("The coach pastes this into the mobile tracker (Paid/admin only).")

            if st.button("Remove user", key=f"rm_{_email}", disabled=_is_self,
                         help="You can't remove yourself." if _is_self else None):
                AUTH.remove_user(_email)
                st.rerun()

    with st.form("au_add", clear_on_submit=True):
        _a1, _a2, _a3 = st.columns([4, 2, 1])
        _new_email = _a1.text_input("Email", placeholder="coach@gmail.com",
                                    label_visibility="collapsed")
        _new_role = _a2.selectbox("Role", AUTH.ROLES, index=1,
                                  label_visibility="collapsed")
        if _a3.form_submit_button("Add", type="primary"):
            try:
                AUTH.add_user(_new_email, _new_role, added_by=_me["email"])
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    st.caption("Add a coach by email, then set their plan, team, Co-op mode and "
               "tracker token above. Re-adding an email updates its role.")

    # The old per-TEAM league-pool toggle is gone — reciprocity is now PER-COACH
    # (the Coaches' Co-op toggle above, and each coach's own switch at the top of
    # this section). A coach is the unit that shares + scouts, not a team.
