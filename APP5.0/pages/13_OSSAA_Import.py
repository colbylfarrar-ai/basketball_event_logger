import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ast
import datetime
import re
import subprocess
import sys

import pandas as pd
import streamlit as st

from helpers.ui import page_chrome, lab_hero as _lab_hero
from database import db
import helpers.auth as AUTH
import helpers.ossaa_sync as SYNC
from tools.ossaa_import import build_plan_single, build_plan_crawl, season_window

_cfg, ACCENT = page_chrome("OSSAA Import")
_lab_hero("OSSAA Import", phase="BUILD",
          sub="Pull team schedules from ossaarankings.com and turn them into "
              "teams + games. Preview first — nothing is written until you import.")

# Admin-only: a bulk write of teams + games into the SHARED league DB (it feeds
# every coach's league-wide rankings), and the per-team merge decisions below
# need a single trusted hand. Mirrors the admin idiom in change_requests.py.
if (AUTH.current_user() or {}).get("role") != "admin":
    st.warning("🔒 OSSAA import is **admin-only** — it bulk-writes teams & games "
               "to the shared league database and resolves team-merge decisions. "
               "Ask an admin to run an import.")
    st.stop()

CLASS_OPTIONS = ["6A", "5A", "4A", "3A", "2A", "A"]
GENDER_OPTIONS = ["Boys", "Girls"]
GMAP = {"M": "Boys", "F": "Girls"}

_active = (db.query("SELECT value FROM app_settings WHERE key='active_season'")
           or [{"value": ""}])[0]["value"]
WINDOW = season_window(_active)  # (start, end) or None

st.caption("Source: ossaarankings.com (unofficial; fetches are rate-limited). "
           "Team names get a **Boys**/**Girls** suffix, which also keeps boys & "
           "girls of the same school as separate teams.")
if WINDOW:
    st.warning(
        f"⚠️ OSSAA team-ids are **season-specific** — a team page shows that id's "
        f"own season, so a stale id silently imports the wrong year. Seed with an "
        f"id **from the {_active} season**. Hard guard: only games dated "
        f"{WINDOW[0]}…{WINDOW[1]} are imported; anything outside is dropped.")
else:
    st.warning("⚠️ OSSAA team-ids are season-specific — seed with a "
               "current-season id.")

mode = st.radio("Mode", ["Single team", "Crawl a class"], horizontal=True)
c = st.columns(4)
if mode == "Single team":
    seed = c[0].number_input("OSSAA team id", min_value=1, step=1, value=158209,
                             help="The t=NNNNN in an ossaarankings team URL.")
    klass = gender = None
    max_fetch = 1
else:
    seed = c[0].number_input("Seed team id", min_value=1, step=1, value=158209)
    klass = c[1].selectbox("Class", CLASS_OPTIONS, index=4)
    gender = c[2].radio("Gender", GENDER_OPTIONS, horizontal=True)
    max_fetch = c[3].slider("Max teams to fetch", 1, 60, 12,
                            help="Each team is one polite web request (~1s).")

# ── scrape (network runs only on this click, never on a plain rerender) ───────
if st.button("🔍 Preview plan", type="primary"):
    status = st.empty()
    seen = []

    def _progress(sched, tid):
        seen.append(sched.school)
        status.info(f"Fetched {len(seen)}: {sched.school} "
                    f"({sched.klass} {GMAP.get(sched.gender, '?')}) — "
                    f"{len(sched.games)} games")

    try:
        with st.spinner("Scraping ossaarankings.com…"):
            if mode == "Single team":
                plan, _ = build_plan_single(int(seed), window=WINDOW)
            else:
                plan, _ = build_plan_crawl(int(seed), klass, gender,
                                           int(max_fetch), window=WINDOW,
                                           progress=_progress)
        status.empty()
        st.session_state["ossaa_plan"] = plan
    except Exception as exc:  # network / parse failure — keep the page usable
        st.error(f"Scrape failed: {exc}")

# ── preview + import ──────────────────────────────────────────────────────────
plan = st.session_state.get("ossaa_plan")
if plan is not None and not plan.teams:
    st.info(f"No games dated in {_active or 'the active season'} from this seed — "
            "the team id is almost certainly from a different season. Find a "
            "current-season id on ossaarankings and try again.")
elif plan:
    SYNC.ensure_schema()

    # Classify every team vs the current DB (no writes).
    rec = SYNC.reconcile(plan)
    status_of = {}
    for n in rec["auto"]:
        status_of[n] = "merge"
    for n in rec["new"]:
        status_of[n] = "new"
    for a in rec["ambiguous"]:
        status_of[a["name"]] = "review"

    team_rows = []
    for name, (k, g, oid, state) in sorted(plan.teams.items()):
        team_rows.append({"team": name, "class": k, "gender": GMAP.get(g, "?"),
                          "state": state, "ossaa_id": oid or "",
                          "status": status_of.get(name, "new")})
    tdf = pd.DataFrame(team_rows)

    game_rows = [{"date": d, "home": h, "away": a,
                  "score": (f"{hs}-{as_}" if hs is not None else "—")}
                 for (d, h, a, hs, as_, _t) in sorted(plan.games)]
    gdf = pd.DataFrame(game_rows)
    played = sum(1 for g in plan.games if g[3] is not None)

    st.subheader("Plan preview")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Will merge", len(rec["auto"]))
    m2.metric("New teams", len(rec["new"]))
    m3.metric("Needs your call", len(rec["ambiguous"]))
    m4.metric("Games", len(gdf), f"{played} played")

    # ── case-by-case: teams that resemble an existing one but don't auto-match ──
    overrides = {}
    if rec["ambiguous"]:
        st.subheader(f"⚠️ Needs your call ({len(rec['ambiguous'])})")
        st.caption("Each OSSAA team below resembles a team you already have "
                   "(shared name word, same gender) but matched neither by OSSAA "
                   "id nor exact name. Map it to merge (back-fills the OSSAA id so "
                   "future imports auto-merge), or leave **Create new team**.")
        for a in rec["ambiguous"]:
            opts = {0: "➕ Create new team"}
            for c in a["candidates"]:
                opts[c["id"]] = (f"↳ Merge into: {c['name']} ({c['class']}) "
                                 f"· shares {', '.join(c['shared'])}")
            sel = st.selectbox(
                f"**{a['name']}**  ·  {a['class']} {GMAP.get(a['gender'], '?')}",
                list(opts), format_func=lambda k: opts[k],
                key=f"ossaa_map_{a['name']}")
            if sel:
                overrides[a["name"]] = sel

    with st.expander(f"All teams ({len(tdf)})"):
        st.dataframe(tdf, use_container_width=True, hide_index=True)
    with st.expander(f"Games ({len(gdf)})", expanded=not rec["ambiguous"]):
        st.dataframe(gdf, use_container_width=True, hide_index=True)

    st.warning("Import writes to the **active season** DB. Existing teams are "
               "matched (by OSSAA id, else name — case-insensitive); existing "
               "games are skipped, never overwritten. Crawl mode imports the "
               "**whole scraped schedule** (every team + game, not just the seed "
               "team) — opponent-vs-opponent games show in league-wide Rankings.")
    n_mapped = sum(1 for v in overrides.values() if v)
    if st.button("⬇️ Import to database", type="primary"):
        with st.spinner("Writing teams & games…"):
            res = SYNC.ingest(plan, overrides=overrides)
        st.success(
            f"Done — {res['teams_created']} teams created "
            f"({res['teams_matched']} matched, {n_mapped} mapped by you), "
            f"{res['games_inserted']} games inserted "
            f"({res['games_skipped']} already present).")
        st.session_state.pop("ossaa_plan", None)


# ── Refresh by date (scores + newly-scheduled games) ──────────────────────────
st.divider()
st.subheader("🔄 Refresh by date")
st.caption("Pull a date range from the **by-date** schedule to fill in scores for "
           "games now played and add new games. Existing games are never "
           "duplicated and your **tracked** games are never touched.")
st.info("Efficient: one page per date covers every game that day across the state "
        "(~5–15s for a day). Date-driven, so it **survives the yearly rollover** "
        "with no maintenance. Shows the live/upcoming season only.")

rc = st.columns([1, 1, 1])
_today = datetime.date.today()
d_from = rc[0].date_input("From", value=_today, key="rf_from")
d_to = rc[1].date_input("To", value=_today, key="rf_to")
rf_gender = rc[2].radio("Gender", ["Both", "Boys", "Girls"], horizontal=True, key="rf_g")

if st.button("🔄 Refresh games in range", key="rf_go", type="primary"):
    lo, hi = d_from.isoformat(), d_to.isoformat()
    if lo > hi:
        st.error("‘From’ is after ‘To’.")
    else:
        _root = str(Path(__file__).resolve().parent.parent)
        cmd = [sys.executable, "tools/ossaa_bydate.py", "--from", lo, "--to", hi]
        if rf_gender != "Both":
            cmd += ["--gender", rf_gender]
        try:
            with st.spinner(f"Scraping the by-date schedule {lo} … {hi}…"):
                proc = subprocess.run(cmd, cwd=_root, capture_output=True,
                                      text=True, timeout=600)
            if proc.returncode == 0:
                m = re.search(r"RESULT:\s*(\{.*\})", proc.stdout)
                res = ast.literal_eval(m.group(1)) if m else {}
                st.success(
                    f"Refreshed {lo} … {hi}: "
                    f"**{res.get('games_updated', 0)}** scores updated, "
                    f"**{res.get('games_inserted', 0)}** new games, "
                    f"{res.get('games_skipped', 0)} unchanged.")
                with st.expander("Log"):
                    st.code(proc.stdout or "(no output)")
            else:
                st.error("Refresh failed. If this says a Chromium library is "
                         "missing, the browser deps aren't installed on the "
                         "server yet (one-time `playwright install-deps`).")
                st.code((proc.stderr or proc.stdout or "")[-1800:])
        except subprocess.TimeoutExpired:
            st.error("Timed out (>10 min). Try a smaller date range.")
