# TIER 2 HANDOFF — context for a fresh session (written 2026-07-17)

Read this first, then work the items in §3 in order. The master review +
ranked backlog lives in `docs/FULL_APP_REVIEW_2026-07-17.md` (§24 = ranking,
§25 = what Tier 1 shipped). This file is the working context so you don't
re-derive it.

## 1. State of the world

- **Tier 1 (backlog items 1-8) is DONE and DEPLOYED** — commit `2238e94`
  (+ docs `d9ff000`). Live on the VPS, all services active.
- One Tier-1 leftover for the FOUNDER (not you — needs his sudo password):
  install the season-rollover timer. Command block is in the review §25
  item 8. If he says "did the timer", verify with
  `ssh app5@107.170.27.154 "systemctl list-timers | grep rollover"`.
- Working tree clean at `d9ff000` on main; `.claude/` is untracked, leave it.

## 2. Environment facts you'd otherwise burn context rediscovering

**Deploy** (memory also has this): `git push` → `ssh app5@107.170.27.154`
→ `cd ~/app5 && git pull --ff-only` → `sudo -n systemctl restart app5-web`.
Server repo is `~/app5` (= /home/app5/app5), NOT ~/basketball_event_logger.
- Passwordless sudo covers **systemctl restart ONLY** — you cannot cp into
  /etc/systemd or `systemctl enable` non-interactively. Don't try.
- Restart `app5-tracker` too when `tracker/api.py` or any helper the API
  imports changes. Bump `const CACHE = 'tracker-vNN'` in
  `tracker/static/sw.js` whenever anything in `tracker/static/` changes
  (currently **v45**).

**Tests**: script-style, NOT pytest — each file runs standalone
(`python tracker/test_X.py`). Pytest collection has ~11 pre-existing errors
(one-process import clash); do not chase them. Full sweep:
`for f in tracker/test_*.py; do python "$f" >/dev/null 2>&1 || echo $f; done`
(took ~4 min, all 57 pass as of `2238e94`).

**Local data gotcha**: the laptop DB (LOCALAPPDATA\APP5\analytics.db) is
POST-rollover — real data is season **'2025-2026'** (13k games), 'Current'
is nearly empty. So: league engines called with defaults return thin/empty;
to exercise tracked-data paths use
`helpers.seasons.game_pool('2025-2026', gender='F', tracked_only=True)`.
AppTest smoke on pages that hit an empty-season branch dies with a KeyError
'url_pathname' inside `st.page_link` — **pre-existing harness artifact, not
a regression**. TD smoke seeds: `at.session_state['td_view'] = 'Insights'`
etc. PROD's active season label is 2026-2027 (flagged to founder, not a bug
to fix).

**Conventions established in Tier 1 — reuse, don't reinvent:**
- Insight-line rendering: metric badge + `cards.conf_dot(n, k=8)` + n= chip
  + bolded sentence. Copies live in `helpers/dashboard/insights_tab.py`
  (`_line_html`), `player_card.py`, `pages/5_Rankings.py`.
- Metric → dashboard-view map: `_EVIDENCE_VIEW` in insights_tab.py (51
  metrics). View-jump from inside a fragment:
  `st.session_state['td_view'] = v; st.rerun(scope='app')`.
- 3-line insight cap on every surface EXCEPT the TD Insights tab (top=None
  there — it's the deep-dive home).
- Per-coach settings: `settings_utils.USER_SCOPED` set + `u:<email>:<key>`
  storage. NOTE: USER_SCOPED is an exact-key set — a per-team key like
  `insights_seen` must either be one JSON blob under one key, or you extend
  `_ukey` for prefix matching (prefer the JSON blob — smaller change).
- Timeouts: `game_timeouts` table, `situational.timeout_splits`,
  `fetch_timeouts`; PWA buttons post to `/api/games/{id}/timeouts`.
- Migrations: append to the `migrations` list in `database/db.py`
  (`initialize_database`) — every statement is try/except'd and runs on
  every boot, so idempotent statements only (`CREATE TABLE IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`, guarded backfills via app_settings markers).

## 3. THE WORK — Tier 2 items, in order (backlog numbering kept)

**9. Rating snapshots → rank trajectory.**
Migration: `CREATE TABLE IF NOT EXISTS rating_snapshots (day TEXT NOT NULL,
gender TEXT NOT NULL, system TEXT NOT NULL, team_id INTEGER NOT NULL,
rating REAL, rank INTEGER, PRIMARY KEY (day, gender, system, team_id))`.
Write path: on the Rankings page, after `_ratings(gender)` computes, a
cached-per-day function INSERT OR IGNOREs today's board for both systems
('score' via TR.score_ratings — has Rating + Rank; 'tracked' via
TR.tracked_ratings). No timer needed. Surfaces once ≥2 days exist:
movement arrows (▲3) next to rank in the Rankings Overview table; a
rating-over-time line in TD Overview / team_card; "biggest risers this
week" tile on the Hub. Season-stamp the rows (games.season pattern) so
rollover doesn't blend.

**10. Postgame read at the buzzer.**
`helpers/postgame.py` exists (only reachable via box_score's lazy import
today). Surface A: `pages/2_Game_Tracker.py` — when a game just finished
(tracked=1 + scores frozen), show the postgame paragraph + buttons for the
social result card (`helpers/social_cards.py`) and recap PDF
(`helpers/reports.py` + `ui.pdf_or_html_download`). Surface B (optional):
tracker finish flow — PWA shows a "recap ready in the app" toast.

**11. Opponent insights in the War Room Matchup view.**
`pages/9_War_Room.py`, view "Matchup" (view switcher `_wrview`, values in
`_WR_VIEWS`). Two-column "their tells / our tells" above the predicted
line: `team_insights.team_insight_feed(gender, season, top=3)` cached once,
look up both team ids. Render with the Tier-1 line pattern + conf dots.
Gate on the viewer's entitlement per team
(`ENT.can_see_team_tracked(AUTH.current_user(), tid)` — see how
5_Rankings.py's deep dive does it, `_see_trk`).

**12. Command palette (global search).**
New helper in `helpers/ui.py`; trigger button in `page_chrome` sidebar
(after the Refresh button). `@st.dialog("Go to…")` + `st.text_input` over
teams + players (one cached query each). On pick: teams →
`st.session_state` team key + `st.switch_page("pages/6_Team_Dashboard.py")`;
players → seed the Players profile keys + switch_page. Find the exact
session keys each page reads before writing them (TD team selector, Players
profile picker) — grep for their `key=` args.

**13. Player quick-view modal.**
`@st.dialog` wrapping `dashboard/player_card.render_card`. The ctx is heavy
(see the two existing builds: `pages/7_Players.py` ~line 1403 and
`pages/6_Team_Dashboard.py` ~line 5134) — extract a shared
`build_card_ctx(pid, gender, season, season_gp)` into player_card.py first,
THEN the modal is trivial and both call sites shrink. Start on the Players
Leaders table.

**14. PWA coverage nudge.**
Server: extend the `/api/games/{id}/live` payload (`GE.live_state`) with
tonight's tag coverage (% of shot/tov events carrying defense / play_type —
cheap COUNT over the game's events; coverage.py has the definitions).
Client: small badge near `sync-status` in `tracker/static/index.html` +
render in `refreshLive()` (app.js). Bump sw.js cache (→ v46). Quick-mode
users see it too — that's the point (nudge toward detailed mode).

**15. Event Editor bulk re-tag.**
`helpers/event_log.py`: add `bulk_retag(event_ids, field, value)` —
validate field ∈ {play_type, defense, turnover_type}, value against the
canonical sets (`playtypes` / `defenses.DEFENSES` / `turnovers.
TURNOVER_TYPES`), one executemany UPDATE (audit hook logs it
automatically). Page: `pages/3_Event_Editor.py` — add a checkbox column to
the grid (or st.multiselect over row labels) + field/value pickers + apply
button. Clear `st.cache_data` after (page already does this on save).

**16. Insight "NEW" badges per coach.**
Store one JSON blob per coach: key `insights_seen` in USER_SCOPED (add to
the set), value = {f"{team_id}": {metric_hash: iso_date}}. On Insights tab
render: lines whose (metric + text hash) isn't in the blob get a `NEW`
chip; update the blob after render. Keep it cheap — hash on
`ln['metric'] + ln['text'][:40]`.

**17. Glossary + grid adoption pass.**
Mechanical. `ui.glossary_key("ORtg", "DRtg", ...)` above dense tables on
Rankings / War Room / Officials (only 3 pages have it today: Hub, TD,
Players). `ui.grid(df, key=...)` for the big raw `st.dataframe` walls —
Rankings has 18, War Room 8. Unique keys per call. Don't convert small
single-entity tables (pin_first=False cases) — leave those as dataframes.

## 4. Definition of done, per item

Engine change → script test in `tracker/` (follow test_timeouts.py shape).
Page change → AppTest smoke where the page's populated branch is reachable
(remember the local-season gotcha; engine-level verification is acceptable
where it isn't). Then: full script-test sweep → commit (conventional,
one item or a few related items per commit) → push → deploy (pull +
restart app5-web, + app5-tracker/sw-bump when touched) → update
`docs/FULL_APP_REVIEW_2026-07-17.md` §25-style build log (append a §26
"TIER 2 — BUILT") as you land items, in the same verdict-first voice.

Founder taste (memory-backed): Insights tab is the benchmark — depth not
clutter, verdict-first sections, honest sample-size affordances. When in
doubt, copy its patterns.
