# TIER 3 HANDOFF — context for a fresh session (written 2026-07-17)

Read this first, then work the items in §3 in order. The master review +
ranked backlog lives in `docs/FULL_APP_REVIEW_2026-07-17.md` (§24 = ranking,
§25 = Tier 1 build log, §26 = Tier 2 build log). This file is the working
context so you don't re-derive it. Tier 3 items are BIGGER than Tiers 1-2 —
expect a day-plus each; it's fine to land a subset well rather than all nine
thin. §24's "per-tab quick hits" table is the grab-bag to pull from when an
item finishes early.

## 1. State of the world

- **Tiers 1 AND 2 (backlog items 1-17) are DONE and DEPLOYED** — one commit
  per item, `2238e94` … `1fa221e`. All services active. Working tree clean at
  `1fa221e` on main; `.claude/` is untracked, leave it.
- One leftover for the FOUNDER (not you — needs his sudo password): install
  the season-rollover timer. Command block in review §25 item 8. Verify with
  `ssh app5@107.170.27.154 "systemctl list-timers | grep rollover"`.
  **Item 21 below hits the SAME sudo wall** — see its note.
- Rating snapshots (`rating_snapshots`) started accruing on prod 2026-07-17.
  By your session there should be several days of history — the Δ Rk column /
  risers / trajectory surfaces should be live; eyeball them on prod if asked.

## 2. Environment facts you'd otherwise burn context rediscovering

**Deploy**: `git push` → `ssh app5@107.170.27.154` → `cd ~/app5 && git pull
--ff-only` → `sudo -n systemctl restart app5-web`. Server repo is `~/app5`,
NOT ~/basketball_event_logger.
- Passwordless sudo covers **systemctl restart ONLY** — you cannot cp into
  /etc/systemd or `systemctl enable` non-interactively. Don't try.
- Restart `app5-tracker` too when `tracker/api.py` or any helper the API
  imports changes (game_events, entitlement, …). Bump `const CACHE =
  'tracker-vNN'` in `tracker/static/sw.js` whenever anything in
  `tracker/static/` changes (currently **v46**).
- Systemd unit files live in `APP5.0/deploy/` (see
  `app5-season-rollover.{service,timer}` for the pattern). You can COMMIT new
  units; only the install step is founder-blocked.

**Tests**: script-style, NOT pytest — each file runs standalone
(`python tracker/test_X.py`). Pytest collection has ~11 pre-existing errors;
do not chase them. Full sweep:
`for f in tracker/test_*.py; do python "$f" >/dev/null 2>&1 || echo $f; done`
(~4-5 min, **61 tests** all pass as of `1fa221e`). Throwaway-DB test pattern:
set `os.environ["APP5_DATA_DIR"] = tempfile.mkdtemp(...)` BEFORE importing
database.db (see test_rating_history.py / test_bulk_retag.py).

**Local data gotcha**: the laptop DB is POST-rollover — real data is season
**'2025-2026'** (13k games, gender 'F' has the tracked depth), 'Current' is
nearly empty. Engines called with defaults return thin/empty; use
`helpers.seasons.game_pool('2025-2026', gender='F', tracked_only=True)`.
AppTest smoke on a page that hits an empty-season branch dies with KeyError
'url_pathname' inside `st.page_link` — **pre-existing harness artifact, not a
regression**; filter it. Seeds that reach populated branches: Players →
`pl_season='2025-2026'`; TD → `ta_season='2025-2026'` (+ `td_view=...`);
Game Tracker → `gt_game=<tracked game id>` (id 229 works). AppTest dialog
quirk: `selectbox.select()` round-trips through format_func — seed the
widget's session key directly instead. PROD's active season label is
2026-2027 (known, not a bug).

**Conventions established in Tiers 1-2 — reuse, don't reinvent:**
- Insight-line rendering: metric badge + `cards.conf_dot(n, k=8)` + n= chip +
  bolded sentence. Canonical copy `_line_html` in
  `helpers/dashboard/insights_tab.py` (now takes `new=` for the NEW chip);
  clones in player_card.py, 5_Rankings.py (~line 954), 9_War_Room.py Matchup.
- Per-coach persistence: `settings_utils.USER_SCOPED` exact-key set +
  `u:<email>:<key>` storage; multi-entity state = ONE JSON blob under ONE key
  (pattern: `insights_seen` + `insights_tab._seen_tracker`).
- Shared player-card ctx: `player_card.build_card_ctx(pid, gender, season,
  season_gp, *, vis, P, rows, ...)` + `quick_view` dialog; chart keys
  namespace via `ctx.key_suffix`.
- Daily history: `helpers/rating_history.py` (snapshot_board / movement /
  team_series / risers / arrow).
- Bulk event writes: `event_log.bulk_retag` (canonical-set validation +
  event-type eligibility from `_FIELDS_BY_TYPE`).
- Command palette: `ui._palette_dialog`; page seeds `ta_gender`/`ta_team`,
  `pl_gender`/`_palette_player`. Both consumer pages drop out-of-pool seeds.
- Dense tables: `ui.grid(df, key, height=..., pin_first=...)`; do NOT convert
  tables using ProgressColumn / LineChartColumn / pandas Styler — grid strips
  them. `ui.glossary_key(...)` popover above dense-table zones (silently
  skips unknown abbrs; the canon is `helpers/glossary.STAT_DEFS`).
- Migrations: append idempotent statements to the `migrations` list in
  `database/db.py` (`initialize_database`); derived/telemetry tables also go
  in `_AUDIT_SKIP_TABLES`.

## 3. THE WORK — Tier 3 items, in order (backlog numbering kept)

**18. Theme-reactive charts.**
Today `helpers/ui.py` hardcodes the chart tokens (`CARD_BG`/`GRID` ~line 36,
`HEAT` builds on them; `style_fig` ~line 345 uses them) while cards reskin
via `settings_utils.STYLE_PRESETS` (~line 39: card_bg, body_bg, track,
subtext, text per preset — applied in `apply_theme_css` ~line 217). Fix:
resolve the chart tokens from the ACTIVE preset at call time — e.g. a
`_theme_tokens()` in ui.py reading `get_setting('app_style')` →
STYLE_PRESETS row (cache per session; style changes already rerun the page),
then style_fig / HEAT / gauge / wp_ribbon pull from it instead of module
constants. DANGER: dozens of modules import `CARD_BG`/`GRID` by value —
keep the names as module attrs that update, or sweep the importers. Verify
on TD Charts + Hub with a non-Dark preset (AppTest: markdown/plotly specs
carry the colors; or set `app_style` setting then screenshot via preview).

**19. Roster CSV import (Input Hub).**
`pages/1_Input_Hub.py` roster section (season-scoped roster helpers ~line
76; retro-add + identity linking ~lines 280-501 — REUSE their insert path so
grad_year / identity / season stamping stay right). Add: `st.file_uploader`
(csv) + paste-a-block `st.text_area` alternative → parse
name/number/height/grad_year (tolerant: header sniff, extra cols ignored) →
preview `st.dataframe` with per-row dedup verdict (same name+number on
roster = skip/update) → one confirm button inserts. Engine bit
(`helpers/roster_import.py`: parse + plan, pure, script-testable) + thin
page glue. Test: parse variants (headers/no headers, "5'11" heights, blank
numbers), dedup plan, insert via throwaway DB.

**20. Hall of Fame single-game records + records watch.**
`pages/14_Hall_of_Fame.py`; fuel is `stats.player_game_boxes` (~line 2288,
{pid: {gid: box}}) — career/season aggregation there already resolves
identity via COALESCE(identity_id, id); mirror it. New "Single-game records"
tab: top-10 scoring/rebounds/assists/steals/blocks nights (player, opponent,
date — join games for the matchup label), all-seasons pool. "Records watch":
active players within N of a career mark (e.g. within 5 games' typical pace
of a season/career top-10) → chip row on the HoF page + optionally the Hub.
Engine in `helpers/hall_of_fame.py` (or extend if it exists — check) with a
script test on synthetic boxes.

**21. Nightly OSSAA refresh timer.**
`tools/ossaa_refresh.py` ALREADY EXISTS (wraps helpers/ossaa_sync: reconcile
+ ingest with update_scores) — read it first; the job is packaging, not
scraping. Copy the `deploy/app5-season-rollover.{service,timer}` pattern →
`app5-ossaa-refresh.{service,timer}` (nightly ~04:30, `Persistent=true`,
ExecStart the venv python + tools/ossaa_refresh.py with whatever args its
__main__ wants). COMMIT the units + add the install block to the founder's
TODO — **you cannot install them** (sudo wall, same as rollover). Dry-run
the tool locally against the laptop DB first (it's rate-limited and
idempotent; scores land via update_scores).

**22. Officials crew-pairs table.**
`pages/8_Officials.py` Individual tab (`_fx_individual` ~line 676, rendered
~line 792). Engine in `helpers/ref_tendencies.py`: self-join
`game_lineup_officials` on game_id → per PAIR (and full crew triple where
n≥sample) aggregate fouls/game, home/away foul split, PPP, leverage — reuse
the per-ref aggregates' queries. Gate rows on n≥5 games together (conf_dot
for honesty). Surface: one `ui.grid` table + a "tightest / most home-leaning
crews" verdict line above it (verdict-first, founder taste). Script test on
synthetic officials/games.

**23. Save/load in the War Room.**
Persist per coach: built lineups (Lineups → Creator picks), bracket seed
overrides, last sim config. Storage: ONE USER_SCOPED JSON blob per concern
(`wr_saved_lineups`, `wr_bracket_seeds` — the insights_seen pattern), NOT
coach_notes (that's team-keyed notes text). Manual seed override box on
Bracket (real OSSAA field) pairs naturally — do it in the same item. UI:
save-as-name + load/delete selectbox next to the existing pickers
(`_wrview` blocks: Lineups ~line 1073+, Bracket ~line 1063+). Mind widget-key
seeding rules (drop out-of-pool ids like the palette consumers do).

**24. Whiteboard playbook save.**
`pages/10_Whiteboard.py` is a JS canvas component; strokes live client-side
as `ops = {half: [], full: []}` (feet coords, ~line 149). To persist you
must round-trip ops out of the component — check how the component returns
value to Streamlit (if it doesn't, add a return payload). Storage: new
`coach_plays` table (coach_email, name, ops JSON, created_at — coach_notes
PRIVACY model, i.e. always filtered by AUTH.current_user() email) via a
migration. Save-as-name + load/delete + a PNG export (canvas toDataURL in
the payload) so saved plays can embed in the printable scout sheet
(`helpers/reports.py` scout sheet builder). BIGGEST unknown of the tier —
timebox the component round-trip investigation before committing to scope.

**25. Mobile responsiveness pass.**
The good media-query block lives INLINE on `pages/4_Schedule.py` (~line 67,
max-width 640px: KPI rows wrap, tables scroll, masthead shrinks).
Generalize it into `assets/style.css` (loaded by page_chrome for every
page): target the shared classes (.dash-card rows, .glass-tile grids,
.masthead, st.dataframe wrappers) instead of Schedule's local ids; then
delete the inline copy. Verify with the browser pane at 375px
(`resize_window` preset mobile) on Hub / Rankings / TD — screenshots before
you call it done. Pure CSS, no restart-sensitive code.

**26. WP calibration backtest + weekly awards digest.**
Two halves. (a) `tools/backtest.py` ALREADY EXISTS — read it; extend it into
a WP calibration report (predicted win prob vs actual outcome by bucket,
Brier score) over the '2025-2026' pool; output a markdown/PNG artifact into
docs/ — analytics trust, not a page. (b) Weekly awards digest on the Hub:
player of the week (top WPA or game-score), team riser of the week (reuse
`rating_history.risers`), game of the week (GEI) — one cached "this week"
strip under the KPI row, engine-composed from existing feeds, gated like the
other cross-team tracked surfaces (`_paid` in 0_Analytics_Hub.py).

## 4. Definition of done, per item

Engine change → script test in `tracker/` (throwaway-DB pattern). Page
change → AppTest smoke where the populated branch is reachable (remember
the local-season gotcha; engine-level verification acceptable where it
isn't). CSS/theme change → browser-pane screenshot at desktop + mobile.
Then: full script-test sweep → commit (conventional, one item per commit) →
push → deploy (pull + restart app5-web; + app5-tracker/sw-bump when
touched; units = commit only + founder TODO) → append to the review doc's
build log (a §27 "TIER 3 — BUILT") in the same verdict-first voice as
§25/§26.

Founder taste (memory-backed): Insights tab is the benchmark — depth not
clutter, verdict-first sections, honest sample-size affordances. When in
doubt, copy its patterns.
