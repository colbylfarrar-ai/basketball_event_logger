# APP5.0 — Full App Review (2026-07-17)

Comprehensive walk of the entire app in the requested order:
schema → helpers → engines → Team Dashboard → Rankings → Players → War Room →
Game Tracker → Input Hub → Setup → Event Editor → OSSAA Imports → Schedule →
Officials → Settings → Live app → Tracker app → Whiteboard → Hall of Fame →
Analytics Hub. For each area: **what's here**, **what's missing**, and
**what could be added** (including "exists elsewhere but not here" parity gaps).

---

## 1. Schema (`database/schema.sql` + `database/db.py`)

**What's here.** A small base `schema.sql` (8 tables) plus a ~100-statement
runtime migration ladder in `db.py` that carries the real schema: ~20 effective
tables (app_users, coach_teams, coach_notes, change_requests, audit_log,
manual_player_box, app_settings, team_class_history, tracker_guest_tokens,
fan_views, …). Strong operational hygiene: WAL + busy_timeout, data dir outside
cloud-sync folders, legacy DB migration, ISO date normalization, write-audit on
every mutation with actor attribution, delete-or-archive logic for players and
officials that respects FK history, idempotent one-time migrations with marker
keys.

**What's missing / worth fixing.**
- **`schema.sql` has drifted badly from the effective schema.** It documents 8
  tables; the other ~12 exist only inside the migration list. A fresh reader (or
  a future you) can't see the real schema in one place. Suggest a generated
  `schema.effective.sql` snapshot (`.schema` dump) committed alongside, or a
  docs table map.
- **No index on `games(date)` or `schedule(date)`.** The Schedule calendar,
  day drill-downs and every game-log ORDER BY date scan. Cheap win:
  `CREATE INDEX idx_games_date ON games(date)` (+ schedule).
- **`tracker_guest_tokens` is defined twice** (schema.sql and the migration
  list). Harmless, but one should go.
- **`audit_log` grows unboundedly** with no pruning or rotation. At high
  multi-coach volume this will bloat the season DB. A retention migration
  (e.g. keep 10k rows / 12 months) would cap it.
- **Two season-partition mechanisms coexist**: per-season DB files
  (seasons.json → db_file) *and* `season` columns inside each DB. It works
  (model A), but it's the subtlest part of the system — worth one doc page.
- **`schedule` vs `games` dual bookkeeping.** Two records of the same result
  (team_score/opp_score vs home_score/away_score) kept in sync by app logic
  only. No CHECK/trigger safety net; a drift-detection query in Settings →
  admin would be cheap insurance.
- **Event-type vocabulary is capped at shot / free_throw / foul / turnover.**
  Consequences:
  - **No timeout events** → no after-timeout (ATO) efficiency, no
    timeout-to-kill-a-run analysis (the courtside engine literally suggests
    "Consider a timeout" but the data never records whether one was taken).
    This is the single biggest missing *capture* in the app.
  - **No explicit substitution events** — subs are inferred from per-event
    lineup snapshots. Works, but minute totals resolve only to event
    boundaries.
  - **Technical fouls / foul kinds**: `foul_type` column reserved but unused
    (founder reverted 2026-07-11 — noted, by design).
  - Jump balls / possession arrow, deflections, kicked balls — all absent;
    only worth it if the tracker stays one-tap simple, so likely fine.
- **No per-event video timestamp.** `games.video_url` exists; a
  `video_ts` on events would turn the Event Editor into a film-room index.

## 2. Helpers (`helpers/`, ~95 modules)

**What's here.** A genuinely impressive engine layer: nearly every module is
Streamlit-free, documented with *why* headers, and tested (56 test files, ~840
asserts). Shared UI primitives consolidated (`ui.py`, `cards.py`), one glossary
as the stat source of truth, one write path for events (`game_events.py`) shared
by page + API, and the `dashboard/` render-module split pattern working well.

**Findings.**
- **No orphan engines.** Every module has a page/api consumer (checked by
  import graph). `postgame.py` is only reachable via a lazy import inside
  `box_score.py` — surfaced, but easy to think it's dead; a direct surface (see
  Game Tracker below) would give it a real home.
- **Monoliths remain**: `stats.py` (2,334 lines) and `team_analytics.py`
  (1,961) are the two biggest non-page files. They're stable, but any future
  split should follow the dashboard/ pattern.
- `pdf_export`/`printouts`/`court_png` ladder is sound (WeasyPrint →
  xhtml2pdf → HTML fallback).

## 3. Engines (analytics inventory + gaps)

**What's here** (by family):
- **Ratings**: team score + tracked iterative opponent-adjusted ratings,
  adj_efficiency (opponent-adjusted shooting), 5-dimension player ratings,
  RAPM (with CI), HoopWAR, WPA (two credit models), win probability + GEI +
  stakes-adjusted excitement, empirical-Bayes shrinkage, career projection,
  game_rating (per-game 0-10).
- **Tag engines**: playtypes (inferred + explicit), defenses, turnovers,
  charges (foul+turnover encoding), breakdown (four factors per tag),
  situational + scheme_situational (when a look spikes), coverage (tag honesty).
- **Spatial**: court_geom, shotquality (xPP-Q + SMOE), spacing, concession,
  rebound geography, handedness splits.
- **Meta/scout**: insights (player), team_insights, selfscout (scoutability
  entropy), exploit (your offense × their defense), matchups (guarded-by
  grid), scout/scoutboard, archetypes, badges.
- **Sim/planning**: predictor, Monte Carlo simulation (game/season/bracket),
  lineup_projection, rotation_plan (stagger + foul-trouble sim), fatigue.
- **Ops**: identity (cross-season person), development (YoY), seasons,
  game_dedup, entitlement (two-axis gating), public_feed (allowlisted),
  ossaa_sync.

**Missing engine candidates** (data already exists for all of these):
1. **Assist network** — `pass_from_id` on every made shot is a directed
   who-assists-whom graph. `networks.py` only does on-court pair chemistry.
   An assist-flow sankey/graph on the Team Dashboard would be a cheap,
   coach-legible win.
2. **Rating history / rank trajectory** — ratings are recomputed live; nothing
   snapshots them, so "we climbed from #14 to #6 over January" is unplottable.
   A tiny `rating_snapshots` table written by a weekly cron (deploy already has
   a systemd timer pattern) unlocks trajectory charts on Rankings and the Hub.
3. **ATO / timeout effect** — blocked on timeout capture (see schema).
4. **WP-model calibration report** — `tools/backtest.py` backtests ratings;
   nothing verifies the win-probability curve is calibrated (predicted 70% =
   real 70%). A calibration plot in the tools/ suite would harden GEI, WPA,
   excitement — everything downstream of WP.
5. **Auto awards feed** — "Player of the Week / Game of the Week" digest is a
   thin composition of existing engines (game_rating, GEI, insights) that would
   give the Hub a recurring reason to open the app weekly.

## 4. Team Dashboard (`pages/6_Team_Dashboard.py`, 5,189 lines + dashboard/)

**What's here.** The flagship: 10 views (Overview, Scout, Insights, Projection,
Roster, Schedule, Charts, Lab, Share, Glossary). Charts is a 6-story wall with
nested super-tabs (Offense/Play Style/Defense/Situational/Trends/Quarters),
Lab holds RAPM/WPA/lineups/networks/spacing/matchups, Scout folds in
selfscout + concession + shotquality, Share does social cards. Team banner
persists across views. This is the benchmark page and it shows.

**Gaps / candidates.**
- **Big Bet 5 split is unfinished**: Overview/Players/Sched/Scout/Insights/
  Profile/Playstyle/Defense/Situational/Projection/Share are extracted, but
  **Charts (~2,300 lines) and Lab (~900 lines) still live on the page**, which
  is why it's still 5,189 lines. Finishing the split is the maintainability
  play.
- **No team "season report" export.** Players get a printable card, games get
  a recap, scouts get a sheet — the *team season in review* (record, rating
  trend, four factors, top performers, signature wins) has no printable. All
  components exist in `reports.py`/`printouts.py` style.
- Rebound maps, charges, scheme sections all landed recently and are wired —
  no parity complaints.

## 5. Rankings (`pages/5_Rankings.py`, 3,177 lines)

**What's here.** Overview (score ratings + leaders + signature stats), Compare,
Team deep dive (shares `team_card` with the Dashboard — good anti-drift move),
Tracked ratings, League landscape (Team Charts + League Lab merged, lazy
per-section compute). Uses excitement, runs, wpa, player_edge, insights.

**Gaps / candidates.**
- **Rank trajectory** (needs rating snapshots — see Engines #2). This is the
  page that most wants it.
- **District standings**: `teams.district` exists and Setup edits it; Rankings
  filters by class but I found no district/conference standings table — the
  thing OSSAA playoff seeding actually runs on. Worth confirming and adding a
  District view if absent.
- Rankings is the only page with a committed AppTest story test
  (`test_rankings_stories.py`) — the pattern exists; other pages don't use it
  (see Testing, §21).

## 6. Players (`pages/7_Players.py`, 1,792 lines)

**What's here.** Leaders, Ratings, Shot Lab, Compare, Player Profile (shared
`player_card` — includes development YoY, WPA, game rating, projection),
Lab (badges, archetypes + similarity, shrinkage, matchups). Printable player
report card via `reports.py`.

**Gaps / candidates.**
- **No per-player insights on the profile.** The auto-scout lines
  (`insights.py`) surface on the Team Dashboard Insights tab and the Hub, but
  the Players page never shows "what the data says" for the selected player —
  the most natural home for it. ("Here but not there.")
- **Compare caps at 2 players.** A 3-4 player radar for depth-chart battles is
  a small change with real coaching use.
- No watchlist/pin (a coach tracking 5 opponents' stars re-picks them every
  visit). `coach_notes`-style per-coach persistence pattern already exists.

## 7. War Room (`pages/9_War_Room.py`, 1,712 lines)

**What's here.** Lineups (creator/optimizer/compare on one engine), Matchup
(predictor + sim distribution + matchup one-pager download + **crew outlook**
via ref_tendencies + fatigue context), Season sim, Bracket, Defensive
assignments, Analyze (shared with the analytics playground), Glossary.

**Gaps / candidates.**
- **Nothing persists.** A built lineup, a bracket seeding, a matchup prep —
  all evaporate on refresh. A per-coach "saved scenarios" table (same shape as
  coach_notes) would turn the War Room from a toy into a prep workflow.
- **Bracket is rating-seeded single-elim only** — no manual seeding override
  for the *actual* OSSAA bracket once it's announced. Manual seed entry +
  "simulate the real bracket" is the February feature.
- Exploit matrix lives on the Team Dashboard scout side and `exploit` is
  imported here — verify the matchup view surfaces it prominently in the
  game-plan section (it's the page's whole premise).

## 8. Game Tracker page (`pages/2_Game_Tracker.py`, 1,350 lines)

**What's here.** Correct architectural stance: PWA owns capture, this page is
the bench second screen — auto-refresh scoreboard, quarter scores, bonus/foul
trouble, live box, live shot chart, play-by-play, courtside engine (leverage,
run alerts, foul-trouble sim via rotation_plan), manual logging demoted to a
corrections expander. Shares `game_events.py` write path with the API.

**Gaps / candidates.**
- **Postgame read isn't offered at the buzzer.** `postgame.py` produces the
  "text after the game" paragraph but it's buried inside the box-score
  helper. On game finish, this page should show it (and offer the social
  card + recap PDF in the same breath). All three exist; none is one tap from
  the final whistle.
- Timeout capture (see schema) would naturally live here + PWA.

## 9. Input Hub (`pages/1_Input_Hub.py`, 1,083 lines)

**What's here.** Teams / Players / Games / Team Schedule / Officials / Season
Archive sections; gated deletes through the change-request queue; season
archive with rosters + schedules.

**Gaps / candidates.**
- **No roster bulk import.** OSSAA import seeds teams/games but rosters are
  typed by hand, player by player. A CSV paste/upload (name, number, height,
  grad year) is the highest-leverage onboarding feature for a new paid coach.
  (Setup already has a MaxPreps CSV import for box scores — the pattern
  exists; "here but not there.")
- **No duplicate-player merge UI.** Team merge exists (OSSAA page), game dedup
  exists (Settings), identity linking exists (Setup, cross-season) — but two
  same-season duplicate player rows on one roster have no merge tool.

## 10. Setup (`pages/11_Setup.py`, 411 lines)

**What's here.** Positions & availability, district, game types, manual box
entry (with MaxPreps CSV import), identity linking. Focused and clean.

**Gaps.** None serious. Availability is a flat Active/etc. field — an injured
list with return dates feeding lineup_projection would be the deluxe version.

## 11. Event Editor (`pages/3_Event_Editor.py`, 616 lines)

**What's here.** Full corrections desk: any game, editable grid, tag editing
(play_type/defense/turnover_type), +/- re-derivation, lineup snapshot
preservation, cascade-clear on delete, re-freeze final score. The data-quality
moat is real.

**Gaps / candidates.**
- **No bulk re-tag.** Coaches who ignore tags live, then film-review, want
  "select these 12 events → set defense=2-3". Row-at-a-time only today.
- Per-event film timestamp (see schema) would complete the film-room story.

## 12. OSSAA Imports (`pages/13_OSSAA_Import.py` + `tools/`)

**What's here.** Two-phase importer (scrape plan → idempotent DB write),
ambiguity resolution UI, refresh-by-date, duplicate-team merge, state
auto-detect for out-of-state opponents, auto season rollover tool + systemd
timer, backtest and rating-diff tools.

**Gaps / candidates.**
- **No scheduled nightly score refresh.** deploy/ has the rollover timer but
  results still arrive when someone runs refresh manually. A nightly
  `ossaa_refresh` timer keeps score-based ratings current all season for every
  coach at zero effort.
- **No playoff bracket import** in February (pairs with the War Room manual
  bracket gap).

## 13. Schedule page (`pages/4_Schedule.py`, 600 lines)

**What's here.** Interactive month calendar, day drill: summary, Game of the
Day, Upset Alert, day leaders, every final with box on demand, film widget.

**Gaps / candidates.** *(Corrected during the Tier-1 build:)*
- ~~The calendar never shows upcoming games~~ — **CORRECTED**: future games DO
  appear. OSSAA import seeds them as `games` rows with NULL scores, and the
  day view renders "Game previews" with the predictor's projected line for
  any unplayed day. (It's the per-team `schedule` table this page never
  reads, which is fine — `games` is the canonical calendar source.)
- **Game of the Day = highest combined score** → FIXED in the Tier-1 build:
  now the *marquee matchup* (lowest average ranking of the two teams,
  founder rule 2026-07-17 — works for every scored game where GEI would
  cover only tracked ones; ties break to the closer, then higher-scoring
  final).
- No season scoping (calendar spans all seasons implicitly by date — probably
  fine, but rolled-over seasons share the view).
- Fatigue/density engine exists (used by War Room, dashboard sched) — a
  "3 games in 4 nights" chip on calendar days would be trivial.

## 14. Officials (`pages/8_Officials.py`, 798 lines)

**What's here.** Ratings / Overview / Charts / Individual / Glossary on one
engine call; crew outlook (ref_tendencies) also feeds War Room matchup prep.
Honest data-caveat docstring.

**Gaps / candidates.**
- **Crew chemistry**: everything is per-ref; which *pairs/trios* call tight or
  lean home is derivable from game_lineup_officials and is the actual pre-game
  question (the crew, not one ref).
- Foul-differential → win-probability impact ("this ref swings ±4% WP") would
  be a signature stat; officials.py already computes the components.
- Printable ref one-pager for the coach's clipboard (printouts pattern
  exists).

## 15. Settings (`pages/12_Settings.py`, 471 lines)

**What's here.** Layout/theme/accent, default team, team colors, Coaches'
Co-op toggle, phone-tracker deep link + install guide, admin: user CRUD with
plan/teams/co-op/ban, tracker tokens, assistant guest links, change-request
review, audit log viewer, duplicate-game resolution.

**Gaps / candidates.**
- ~~Display settings are global~~ — **CORRECTED after code check**: theme,
  accent, wide mode, default team and scout_hidden_sections are already
  per-coach (`USER_SCOPED` namespacing `u:<email>:<key>` in
  settings_utils.py, falling back to the global bucket when logged out).
  No action needed.
- **No in-app backup/restore.** The audit-log caption says "restore from
  backup if needed" but only server-side litestream exists; the admin has no
  DB download button, and a laptop-only user has nothing. A "Download season
  DB" button is ~10 lines.
- **Billing is manual** (plan + paid_until hand-set; the Stripe poll is
  roadmapped, noted).
- Add-user has no invite email/notification — coaches must be told out of
  band.

## 16. Live app (fan links: `live.html`, `live_index.html`, `live_team.html`)

**What's here.** Token-gated allowlisted feed (explicitly constructed payload —
the right security posture), live scoreboard directory, single-game page
(score, quarters, last play, WP section, both boxes, shot filter court, PBP,
anonymized refs), team page (record, rank, form, games), fan QR from the
tracker, daily unique fan counter shown to the coach.

**Gaps / candidates.**
- **Final-score share graphic**: social_cards renders 1080×1080 result cards
  in the Streamlit app — the fan page could offer the same PNG at the final
  buzzer (parents *will* post it; it's free marketing). "Here but not there."
- Public team page shows games/record; season leaders (points only, box-level)
  would be safe within the free-tier taxonomy — worth a deliberate decision
  rather than absence.

## 17. Tracker app (PWA: `tracker/api.py` + `static/`)

**What's here.** Offline-first (IndexedDB queue + client UUID idempotency),
per-coach bearer tokens + guest scorer tokens (fail-closed), quick vs detailed
modes, subs via on-court toggle, official slots, shot/FT/foul/TOV modes with
tag capture, undo, finish/rescore, event editor endpoints, public-game toggle +
fan QR, whiteboard (wb.js), season awareness, handedness set from the bench.
31 API routes, all through the shared game_events write path.

**Gaps / candidates.**
- Timeout button (same schema blocker; the PWA is where it would be tapped).
- No end-of-quarter confirm/summary moment (guard against quarter drift when
  logging fast) — small UX, big data-quality effect.
- PWA has no live "coverage" nudge ("you've tagged defense on 12% of events
  tonight") — coverage.py exists; a tiny badge would raise tag rates, which
  raises the value of half the Tier-2 engines.

## 18. Whiteboard (`pages/10_Whiteboard.py` + PWA `wb.js`)

**What's here.** 60fps client-only canvas, real coaching notation (cut, pass,
dribble, screen, draggable numbered O/X, ball), PNG export, deliberate
zero-persistence, parity between Streamlit page and PWA.

**Gaps / candidates.**
- **Playbook persistence** is the obvious next rung: per-coach saved plays
  (name + JSON ops + PNG), reusing the coach_notes privacy model — and saved
  plays could then embed into the printable scout sheet. Ephemeral-by-design
  was the right v1 call; a save button doesn't break it.
- Animation (step-through of drawn actions) is the deluxe version — nice, not
  needed.

## 19. Hall of Fame (`pages/14_Hall_of_Fame.py`, 493 lines)

**What's here.** Records (open: season bests, career leaders via identity
chaining, 25+ game gate, team pantheon, HoopWAR + GEI teasers) and Tracked
ratings (paid, pool-relative all-time board). Correct free/paid split per the
gating taxonomy.

**Gaps / candidates.**
- **No single-game records** — best scoring night, most rebounds, etc.
  (`player_game_boxes` already computes it). The banner stat every gym
  argues about.
- **No "records watch"** — an active player 40 points from a career mark is
  the retention hook; identity + careers already give the math.

## 20. Analytics Hub (`pages/0_Analytics_Hub.py`, 638 lines)

**What's here.** Executive landing: KPI scorecard, gauges, hero charts,
leaderboards with sparklines, Game of the Season (WP ribbon), coverage panel,
quick links; AXIS-2 visibility filtering done correctly in the cached bundle.

**Gaps / candidates.**
- Weekly awards digest (see Engines #5) belongs here.
- "What changed since you last opened" (new insights since last visit) —
  insights engine already dedupes/rotates; a per-coach last-seen timestamp
  completes it.

## 21. Cross-cutting

- **Testing**: 56 engine test files (~840 asserts) is excellent, but only
  Rankings has a committed page-level AppTest story test. The AppTest smoke
  pattern (headless page load per page) is proven in this repo — committing a
  16-page smoke suite would catch the classic "engine fine, page crashes"
  regression class.
- **Top 5 recommendations by leverage**:
  1. Timeout capture (PWA + schema) → unlocks ATO, run-stopping analysis.
  2. Rating snapshots table + weekly timer → rank trajectory on Rankings/Hub.
  3. Per-coach app settings (theme/default team) — multi-tenant correctness.
  4. Schedule page: upcoming games + predictor lines + GEI Game of the Day.
  5. Roster CSV import in Input Hub — onboarding friction for paying coaches.
- **Housekeeping**: games(date) index, schema snapshot doc, audit_log
  retention, finish the Team Dashboard Charts/Lab extraction, nightly OSSAA
  refresh timer, in-app DB backup button.

---

## 22. Deployed-vs-repo verification (2026-07-17)

Checked live VPS (app5@107.170.27.154):
- **No drift.** Server repo at `b26794c` = local HEAD = origin/main; working
  tree clean on both ends. Every finding in this review applies to production.
- Services running: `app5-web`, `app5-tracker`, `app5-litestream` — all
  active.
- **NEW finding: `deploy/app5-season-rollover.timer` is in the repo but NOT
  installed/enabled on the VPS.** `systemctl list-timers` shows no app5 timers
  at all. The auto season rollover will not fire on its own — install the
  service+timer or the July rollover is manual.

## 23. UI helper layer review (`helpers/ui.py`, `helpers/cards.py`, `assets/style.css`, `settings_utils.py`)

**What's here.** A real design system for a Streamlit app: one `page_chrome`
boot, cross-process cache invalidation via `data_version`, theme tokens as CSS
variables consumed by a 740-line stylesheet, branded headers (masthead /
lab_hero / page_header ladder), KPI tiles with tier tint + percentile bar +
**confidence dots** (stat_kpi/conf_dot — genuinely rare in amateur analytics
UIs), glossary popovers wired to STAT_DEFS, graceful-degrade wrappers for
aggrid/segmented-control/chart-container/status, shot-panel and cross-filter
court primitives, WP ribbon, empty states, per-team identity colors,
`st.fragment` adopted across all heavy pages, reduced-motion respected.

### Consistency gaps (primitive exists, pages don't use it)

1. **Four header systems coexist.** `masthead` (built as the flagship brand
   band) is used by exactly one page (Team Dashboard); 6 pages use
   `lab_hero`, 5 use `page_header`, and **Settings + Whiteboard still use raw
   `st.title`**. Pick one ladder (masthead for flagships, page_header for
   utility pages) and finish the rollout.
2. **`grid()` (sortable/filterable table) barely adopted.** Rankings has 18
   raw `st.dataframe` vs 1 grid; War Room 8 vs 0; Hall of Fame, Analytics
   Hub, Game Tracker all 0 grids. The dense leaderboards these pages exist
   for are exactly the grid() use case.
3. **`stat_help` / `glossary_key` on only 3 pages** (Hub, TD, Players).
   Officials, Rankings and War Room ship dense stat tables with no inline
   decode — and the glossary content already exists.
4. **Cross-filter courts (`chart_select`/`court_panel`/`shot_panel`) only on
   the Players page.** Team Dashboard and Scout shot charts are static
   renders; the tap-to-slice experience stops at one page.
5. **`season_picker` integration incomplete by its own docstring** — wired on
   4 pages (Rankings/TD/Players/War Room); Officials and Schedule have no
   season awareness at all.
6. Duplicate palettes: `ui.PALETTE` vs a page-local `PALETTE` in
   6_Team_Dashboard.py (line ~112) — one should go.

### Theme-reactivity gaps (dark presets exist; parts don't follow)

7. **Plotly charts don't follow the theme presets.** `ui.CARD_BG`/`GRID` and
   the `HEAT` colorscale are baked GitHub-dark hexes; `style_fig` hardcodes
   text/hover colors. Switch to Midnight/Forest/Slate and every card reskins
   (CSS vars) but **every chart keeps the old grey grid + card tones**.
   Fix: resolve chart tokens from the active `STYLE_PRESETS` entry inside
   `style_fig`/`HEAT` (page_chrome already has the cfg).
8. **`cards.dense_table` bakes `#0d1117`/`#161b22`/`#21262d` inline** —
   same non-reactivity; should use `var(--card-bg)`/`var(--track)` like
   `factor_tile` already does.
9. `apply_theme_css` hardcodes the `.pl-card`/`.rpl-card` navy gradient
   (`#0f3460 → #16213e`) regardless of preset — looks like a leftover, makes
   player cards ignore the chosen style.

### Performance

10. **`get_setting` is uncached** — every call is a fresh SQLite query, and
    `team_color()` calls it per team. A Rankings render with ~100 team chips
    = ~100 queries per rerun (plus `_scope_email` overhead). Cache the
    settings dict once per run (session_state keyed on `data_version`) or
    batch team_color overrides in one query.

### Component hygiene

11. **Three gauges**: `ui.gauge`, `cards.gauge_dial`, `cards.gauge_range`.
    The two in cards are documented as intentionally distinct; `ui.gauge`
    duplicates `gauge_range`'s job. Consolidate to two.
12. `seg()`/`info_popover`/`engine_status` catch bare `Exception` as a
    version fallback — fine today, but they'll also swallow real bugs
    (e.g. a bad `default` not in options). Narrow to the specific
    AttributeError/TypeError.

### Named UI upgrades (new, not just adoption)

- **Command palette / global search** (`st.dialog` + text input): type a
  team or player name from any page → jump to its dashboard/profile. The
  app is 16 pages deep; navigation is its biggest UX tax. Highest-value
  single upgrade.
- **Player quick-view modal**: click a player name in ANY leaderboard →
  `st.dialog` rendering the existing `player_card` ctx — no page switch,
  no lost scroll position. The shared card makes this nearly free.
- **Skeleton loading**: the CSS already ships a `pl-shimmer` animation;
  replace spinner-blank-flash on heavy tabs (RAPM, League Lab) with shimmer
  placeholder tiles so perceived speed jumps.
- **Mobile pass for dashboards**: style.css has exactly ONE `@media` query
  (and Schedule carries its own inline mobile CSS). Coaches open dashboards
  on phones at the gym. Centralize: KPI rows wrap to 2-up, tables get
  `overflow-x` containers, masthead shrinks. The PWA proves the mobile
  discipline exists — the Streamlit side never got it.
- **Colorblind-safe mode**: GOOD/BAD is pure red/green everywhere (charts,
  deltas, heat tables). Add one "Colorblind" accent preset that swaps to
  blue/orange and have `style_df`/DIVERGE read the semantic pair from
  settings — the CSS-var architecture makes this a token swap.
- **Sticky section nav on the Team Dashboard**: `_jump()` link pattern
  exists; a slim floating in-page TOC (or `st.segmented_control` pinned via
  CSS `position:sticky`) would tame the 5,000-line scroll.
- **Undo toast for admin deletes**: coach deletes go through the
  change-request queue, but admin deletes are instant and final. A 10-second
  "Undo" toast (soft-delete then commit) closes the last data-loss hole.
- **`chart()` export adoption**: the CSV-export chart container exists in
  ui.py; most pages call `st.plotly_chart` directly. Where a chart answers a
  question coaches ask ("send me that"), wrap it.

---

## 24. MASTER RANKED BACKLOG — simple fixes, big change (2026-07-17)

Everything below is ordered by **importance = coach value ÷ effort**, merging
insights improvements, UI, event helpers, schema adds, and per-tab ideas.
Grounding notes: the insights engine is 33 player generators + ~25 team
generators, z-scored with tier-gated samples (`insights.py`,
`team_insights.py`); the `game_events.event_type` CHECK constraint
(schema.sql:85) means a new event *type* requires a table rebuild — so
timeouts go in a **new tiny table** instead (item 2), which is the simple
path.

### TIER 1 — Hours each, outsized payoff

**1. Insight lines → evidence jumps.** Every insight line already names its
`metric` and renders in `insights_tab.py`; the `_jump()` view-switch helper
already exists on the Team Dashboard. Map each metric to its home tab
(Q4 scoring → Charts·Quarters, hand splits → Shot Lab, on/off → Lab) and
append "see the evidence →" to each line. Insights stop being a dead-end
feed and become the navigation hub of the whole app. ~1 map dict + 1 line
per render. *(Insights is the benchmark tab — this is its single biggest
upgrade.)*

**2. `game_timeouts` table + PWA button → ATO analytics.** Do NOT touch the
event_type CHECK (table rebuild). Instead:
`CREATE TABLE game_timeouts (id, game_id, team_id, quarter, time, client_uuid)`
— one migration line in the established ladder, one POST endpoint, one PWA
button next to Undo. The situational engine then joins "possessions
following a timeout" (same pattern as `team_after_outcome`) → after-timeout
PPP for us/them, "do their timeouts kill our runs", coach-challenge data.
Biggest missing capture, and the schema-safe version is small.

**3. Player insights on the Players page profile.** Engine exists, feed
exists, page never calls it (§6). One `render` block inside
`profile_tab`/`player_card` ctx: "What the data says" card with the
player's 1-3 lines. Parity, ~30 lines.

**4. Team insight feed on the Rankings team deep-dive.** `team_insights`
feeds Hub + Team Dashboard but Rankings' Team view (the page opposing
coaches actually browse) has zero insight lines (verified: 0 references).
Same `verdict_card` pattern as insights_tab. ~40 lines.

**5. Confidence dots on insight lines.** Lines already carry `n=`;
`cards.conf_dot` already exists. Replace the raw "n=14" caption with the
dot + hover (and keep n). The honesty affordance the whole app uses,
missing from its flagship surface. ~5 lines.

**6. Schedule page: GEI Game of the Day + upcoming games.** Game of the Day
is literally `max(total points)` today; `excitement.py` is already used by
Rankings + HoF. Swap the ranking for tracked games. Then read the
`schedule` table for future days (page already imports the predictor) and
show the projected line on upcoming games. Turns a results archive into a
daily destination. (§13.)

**7. `games(date)` index + audit_log retention.** Two migration lines in the
existing ladder. Calendar and game-log queries stop scanning; audit stops
growing unboundedly.

**8. Install the season-rollover timer on the VPS.** The unit files exist in
deploy/ but are not enabled (§22 — verified `systemctl list-timers` empty).
`systemctl enable --now app5-season-rollover.timer`. Zero code.

### TIER 2 — A day-ish each, still high leverage

**9. Rating snapshots → rank trajectory.** New table
`rating_snapshots (day, gender, system, team_id, rating, rank — PK(day,
gender, system, team_id))`. Simplest write path: on the first Rankings
render of a day, `INSERT OR IGNORE` the current board (no timer needed).
After two weeks of data: movement arrows on the Rankings table (▲3),
"biggest risers this week" on the Hub, rating-over-time line on team
Overview. The single most-asked coach question ("are we trending up?")
becomes answerable. (§Engines-2.)

**10. Postgame card at the buzzer.** On game finish (Tracker page + PWA
finish endpoint response), surface the existing `postgame.py` paragraph +
one-tap social result card (`social_cards`) + recap PDF (`reports`). All
three engines exist; none is offered at the moment of maximum coach
attention. Mostly wiring.

**11. Opponent insights in the War Room Matchup view.** Two-column "their
tells / our tells": run the existing team feed for both teams side by side
above the predicted line. The insight engine becomes a game-prep tool, not
just a self-scout. ~60 lines reusing `_team_feed`.

**12. Command palette (global search).** `st.dialog` + one text input over
teams/players → route to dashboard/profile with prefilled session state.
16-page app; navigation is the biggest UX tax (§23). One new helper in
ui.py + a sidebar button in page_chrome.

**13. Player quick-view modal.** Click a player name in any leaderboard →
`st.dialog` rendering the existing shared `player_card`. Kills the
"switch page, lose scroll" loop everywhere. The shared card makes it
cheap; adopt on Players Leaders + Rankings first.

**14. PWA coverage nudge.** Tiny badge in the tracker: "defense tagged on
12% tonight" (coverage.py logic, one live endpoint field). Raising tag
rates raises the value of half the Tier-2 engines — a UI nudge with an
analytics multiplier. (§17.)

**15. Event Editor bulk re-tag + `bulk_retag` helper.** Multi-select rows →
set play_type/defense/turnover_type in one shot (`event_log` gains one
UPDATE-many function). Film-review taggers are the coverage engine's best
users; this is their missing tool. (§11.)

**16. Insight "NEW" badges per coach.** Store a per-coach last-seen
timestamp (settings pattern `u:<email>:insights_seen_<team>`); tag lines
that appeared since. Gives the Insights tab a pulse and a reason to
return. ~30 lines.

**17. Glossary + grid adoption pass on Rankings/War Room/Officials.**
Mechanical: `glossary_key(...)` above each dense table (3 pages have it,
the rest don't), `grid()` for the 18 raw dataframes on Rankings and 8 on
War Room. Pure consistency, no new code. (§23-2/3.)

### TIER 3 — Bigger builds, do when the above lands

**18. Theme-reactive charts.** Resolve `style_fig`/HEAT/CARD_BG tokens from
the active STYLE_PRESET (page_chrome already loads cfg). Fixes "cards
reskin, charts don't" (§23-7,-8,-9). Touches one helper, redraws
everywhere.

**19. Roster CSV import (Input Hub).** Paste/upload name-number-height-grad
list per team. Biggest onboarding friction for a new paid coach (§9).

**20. Hall of Fame single-game records + records watch.** Best scoring
night / boards / assists from `player_game_boxes`; "records watch" chip
when an active player is within reach of a career mark (identity chains
already exist). (§19.)

**21. Nightly OSSAA refresh timer.** Reuse the rollover unit pattern for
`ossaa_refresh` so scores flow in without anyone clicking (§12). Small,
but it's ops, not app code — needs a VPS session.

**22. Officials crew-pairs table.** Which 2-3-ref crews call tight / lean
home, from `game_lineup_officials` self-join (§14). Moderate engine work,
one new table on the Individual tab.

**23. Save/load in the War Room.** Persist built lineups + bracket seeds
per coach (coach_notes storage pattern). Turns the lab into a workflow
(§7). Pairs with manual bracket seeding for the real OSSAA field.

**24. Whiteboard playbook save.** Per-coach saved plays (name + ops JSON +
PNG), coach_notes privacy model; embed saved plays in the printable scout
sheet (§18).

**25. Mobile responsiveness pass for dashboards.** Centralize the
Schedule-page media-query pattern into style.css (KPI rows wrap, tables
scroll, masthead shrinks). One CSS file, all pages benefit (§23).

**26. WP calibration backtest + weekly awards digest.** Analytics trust
(tools/) and a Hub retention hook — valuable, but behind everything above.

### Per-tab quick hits (small, tab-local, grab-bag — roughly in order)

| Where | Idea |
|---|---|
| TD · Overview | **"Next game" strip**: opponent, predicted line (predictor), crew outlook (ref_tendencies), rest edge (fatigue) — every engine exists, one card composes them. The best single Overview add. |
| TD · Insights | After item 1 (jumps): a "prep mode" toggle that re-runs the same feed *as the opponent would read it* (selfscout flip). |
| TD · Charts·Trends | Rating trajectory line once item 9 lands. |
| TD · Roster | `conf_dot` on the ratings table rows (sample honesty at the roster scan level). |
| TD · Schedule tab | Fatigue chips ("3 in 4 nights") on upcoming rows — engine imported already in `sched.py`. |
| Rankings · Overview | Movement arrows (item 9); "clinched/eliminated"-style district context once district standings exist (§5). |
| Rankings · Compare | Add the exploit matrix edge summary (engine exists, only TD-scout uses it). |
| Players · Leaders | stat_help icons on column headers; quick-view modal (item 13). |
| Players · Compare | Allow 3-4 players (radar traces already parametric). |
| War Room · Season sim | Persist last sim config per coach (item 23 pattern). |
| War Room · Bracket | Manual seed override box (real OSSAA field). |
| Game Tracker | Postgame card at buzzer (item 10); "possession arrow" note field is NOT worth it — skip. |
| Input Hub · Players | Duplicate-player merge (same-season) — identity UI pattern from Setup covers 80%. |
| Event Editor | Bulk re-tag (item 15); a "tag coverage" header chip showing % tagged for the open game. |
| Officials · Individual | Crew-pairs table (item 22); foul-diff → WP swing headline stat. |
| Schedule | Items 6; day headers show GEI stars for tracked games. |
| Settings | "Download season DB" backup button (~10 lines, `get_db_path()` → `st.download_button`). |
| Hall of Fame | Single-game records tab (item 20). |
| Analytics Hub | Weekly awards digest (item 26); "new insights since last visit" chip (item 16 feeds it). |
| Live fan page | Final-score social card PNG at game end (social_cards exists server-side). |
| Tracker PWA | Coverage nudge (item 14); timeout button (item 2); end-of-quarter confirm toast. |

### Skip-for-now (looked at, deliberately not ranked)

- New event types via CHECK rebuild (timeouts table covers the need).
- Light theme (brand is dark; print sheets already handle paper).
- Per-event video timestamps (wait until film workflow is real).
- Animation on the whiteboard; deflection/jump-ball capture (tracker
  simplicity wins).

---

## 25. TIER 1 — BUILT (2026-07-17, while you were out)

All eight Tier-1 items shipped. What each looks like now:

**1. Insight → evidence jumps** *(insights_tab.py)*. Every metric an insight
line can carry (31 player + 20 team) is mapped to the Team Dashboard view
holding its evidence (`_EVIDENCE_VIEW`). Each auto-scout card (team card +
every player card) now ends with up to three "Charts → / Lab → / Scout →"
buttons that flip the top-level View switcher (full-app rerun from inside the
fragment). View-level only — st.tabs can't be selected programmatically.

**2. Timeouts → ATO** *(db.py, api.py, PWA, situational.py,
situational_tab.py)*. New `game_timeouts` table (separate from game_events —
the event_type CHECK can't be altered without a rebuild; a timeout is a clock
marker, not a possession event). `POST /api/games/{id}/timeouts` (idempotent
on client uuid, team-validated, fail-closed auth — verified end-to-end with
TestClient) + an undo endpoint. The phone tracker grew a `TO · <team>` button
pair above Undo (online-only v1 — a timeout is rare; a failed send toasts
"tap again"). New engine read `situational.timeout_splits`: ONLY the first
possession out of the huddle counts — our offense after OUR timeout vs
baseline PPP, our defense on their first possession after THEIRS (12-assert
unit test, `tracker/test_timeouts.py`). Surfaces on Charts → Situational as
"Out of a timeout — the drawn-up play" once markers exist. PWA cache bumped
to v45.

**3. Player insights on the player card** *(player_card.py + both call
sites)*. "What the data says" section at the bottom of the shared card
(Players page profile + TD profile) — the player's top-3 league-relative
lines with confidence dots. Feed computed once per (gender, season), not per
player. Verified on the archive season: 93 of 239 players carry lines.

**4. Team auto-scout on the Rankings team deep dive** *(5_Rankings.py)*.
3-line team insight feed under the form cards, gated on the viewer's tracked
entitlement for that team. Verified: 18 teams carry lines on 2025-2026.

**5. Confidence dots on insight lines** — every insight surface (tab, player
card, Rankings) now renders `conf_dot(n, k=8)` next to the sample chip.

**6. Game of the Day = marquee matchup** *(4_Schedule.py)* — per your note:
lowest average ranking of the two teams (GEI would only cover tracked), ties
to the closer then higher-scoring final. Upcoming-games half of the item was
already built (see corrected §13).

**7. Migrations** *(db.py)*: `games(date)` + `schedule(date)` indexes;
audit_log 12-month retention (runs each boot).

**8. Season-rollover timer** — units were already Oct-1-aware (daily 03:30
check, `Persistent=true` so a missed boundary still fires). **Install is
blocked on the VPS**: passwordless sudo covers `systemctl restart` but not
`cp`/`enable`, so I could not place the unit files non-interactively. The
script itself is verified working on the box (ran it as app5 — clean no-op,
"active 2026-2027"). ONE manual step for you, with your password:

```bash
ssh app5@107.170.27.154
sudo cp ~/app5/APP5.0/deploy/app5-season-rollover.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now app5-season-rollover.timer
```

(Note found while verifying: the VPS's active season label is already
**2026-2027** — prod rolled over ahead of the laptop DB, which sits on
2025-2026 archive + a nearly-empty Current. Expected if you rolled prod
manually; flagging in case it wasn't intentional.)

Verification: 12/12 new-engine asserts + existing situational tests pass;
timeout API exercised end-to-end (insert / duplicate / bad-team 400 /
no-auth 401 / undo) leaving the DB clean; AppTest smoke on Schedule + TD
Insights + TD Charts passes (Rankings/Players smoke hits a pre-existing
AppTest `page_link` harness artifact on the empty-season branch — their new
sections verified at engine level instead). NOTE: the laptop DB is
post-rollover ('2025-2026' archive + a nearly empty 'Current'), which is why
empty-season branches fire locally. Full script-test sweep ran before
commit.

**Deployed** (commit `2238e94`, pushed + pulled + app5-web/app5-tracker
restarted, both active): migrations confirmed live on prod (`game_timeouts`
table + `idx_games_date` / `idx_schedule_date` / `idx_gto_game` all present).
PWA cache bumped to v45 so phones pick up the TO buttons on next open.
Remaining for you: the one sudo command in item 8 above.

## 26. TIER 2 — BUILT (2026-07-17, while you were out)

All nine Tier-2 items (backlog 9–17) shipped, committed one item per commit
and each deployed to the VPS as it landed. What each looks like now:

**9. Rating snapshots → rank trajectory** *(rating_history.py, db.py,
Rankings, Hub, TD Overview)*. New `rating_snapshots` table; the first
Rankings visit each day INSERT OR IGNOREs both boards (score + tracked, full
pool — history is global truth, not per-coach) for the active season, stamped
with the REAL season label so rollover can't blend. No timer. Three surfaces
light up once two snapshot days exist: a **Δ Rk** movement column (▲3 / ▼2)
in the Overview rankings table, a **Rank trajectory** rating-vs-rank line on
the TD Overview tab, and a **Biggest risers this week** strip on the Hub.
History accrues from deploy day — expect the surfaces to appear from
tomorrow. 18-assert engine test (`test_rating_history.py`).

**10. Post-game read at the buzzer** *(Game_Tracker page, PWA)*. When the
selected game is FINAL, the Game Tracker shows the engine-derived post-game
paragraph (helpers/postgame) plus a "Share the result" expander: the branded
1080×1080 result-card PNG (coach's own team on top when they staff one of
the sides) and the recap PDF — no more hunting through Schedule → box score
right after tapping End Game. Paid depth, same gate as the command center.
The PWA finish toast now says "recap & share card ready in the app".

**11. Opponent tells in the War Room Matchup** *(War_Room)*. Under the
predicted line: a two-column "The tells" read — each side's top-3
league-relative insight lines (same feed as the TD Insights tab, cached once
per gender+season) in the Tier-1 line grammar (metric badge + confidence dot
+ n + sentence). Each column gates on the viewer's tracked entitlement for
THAT team, exactly like the Rankings deep dive; a locked side shows the
Co-op nudge instead.

**12. Command palette** *(ui.py + TD/Players consumers)*. A "🔎 Go to team /
player…" button in every page's sidebar (page_chrome) opens a search dialog
over all teams + active players. A team hit lands on its Team Dashboard
(league + team keys seeded); a player hit lands on Players with the Player
Profile pick seeded via the same mapping as the ?player= deep-link. Both
consumers now drop an out-of-pool seeded selection instead of crashing —
which also fixes the pre-existing league-flip stale-key edge.

**13. Player quick view** *(player_card.py, Players, TD)*. The heavy
per-player feed set (badges, archetypes, per-game boxes, located shots,
foul/FT, set/role/profile percentiles) moved into a shared cached
`build_card_ctx` in player_card.py — both Profile call sites shrank from ~10
feed lookups to one call, and the caches are now shared instead of
duplicated per page. On top of it: `quick_view` (@st.dialog) renders the
full card in a modal; first trigger is a picker + button under the Players
Leaders full stat table. Card chart keys gained a namespace so the modal can
coexist with a tab-rendered card.

**14. PWA coverage nudge** *(game_events.live_state, PWA)*. The /live
payload now carries tonight's tag coverage (play_type over shots, defense
over shots+turnovers — one aggregate COUNT, definitions mirroring
coverage.py). The phone shows a color-coded "🏷️ Tags: play 62% · def 41%"
badge next to sync-status once 5 shots exist — quick-mode users see it too,
which is the point. PWA cache → v46. 6-assert engine test
(`test_live_coverage.py`).

**15. Event Editor bulk re-tag** *(event_log.py, Event_Editor)*. New
`bulk_retag(event_ids, field, value)`: one batched UPDATE across many events
for play_type / defense / turnover_type, validated against the canonical
sets and scoped to the event types that legitimately carry the tag (a stray
free throw is skipped, never corrupted); the audit hook logs it. The editor
grew a "Bulk re-tag selected events" expander — multiselect over the
filtered rows (so filter to one quarter / just shots first) + field/value
pickers + one apply. Complements the whole-game defense fill. 13-assert
test (`test_bulk_retag.py`).

**16. Insight NEW badges** *(insights_tab.py, settings_utils)*. Per-coach
`insights_seen` JSON blob (USER_SCOPED, one key — {team_id: {line_hash:
first-seen date}}, hash = metric + first 40 chars). Unseen lines on the TD
Insights tab get a gold NEW chip that stays for the rest of that day
(day-sticky — a fragment rerun mid-scroll can't eat it) and is gone the next
day. One settings write per render, only when something new appeared; blob
capped at 300 hashes/team. 9-assert test (`test_insights_seen.py`).

**17. Glossary + grid adoption** *(Rankings, War Room, Officials)*. One
📖 stat-key popover at the top of each page's dense-table zone (Rankings
after the View switcher; War Room after its switcher; Officials above the
ratings table). Four big raw league walls on Rankings (play-type PPP, runs,
game-type efficiency, upsets) + the Officials game log converted to
`ui.grid` (in-grid sort/filter, pinned identity column). Styled tables
(Progress columns, gradient styles) deliberately left as dataframes — the
grid would strip their formatting.

Verification: every item has either a script test (rating history, live
coverage, bulk retag, insights seen — all green in the full 61-test sweep)
or an AppTest smoke on the touched page's populated branch (Hub, Rankings,
Game Tracker with a FINAL game — both new expanders render; Players Leaders
quick-view modal opens with the card; TD Insights renders 7 NEW chips; War
Room Matchup, Officials, Event Editor — re-tag expander + 163-row
multiselect present). The known `page_link url_pathname` harness artifact on
empty-season branches remains the only AppTest noise.

**Deployed**: commits `a52eec9` → `c72b11d` (+ this log), each pulled +
app5-web restarted (app5-tracker restarted for item 14; sw.js v46 verified
on the box). All services active. Nothing left blocked on you from Tier 2;
the Tier-1 rollover-timer sudo step (§25 item 8) is still the one manual
item outstanding.

## 27. UI & PERFORMANCE PASS — BUILT (2026-07-18, second agent)

A parallel pass over §23's consistency/perf findings plus your vision note
("the TD Overview banner is the standard: personalized, stat-packed, color
coordinated, confidence shown"), run alongside the Tier-3 session. Five
commits, all tested; the two agents interleaved cleanly (one ride-along:
the War Room hero conversion landed inside the Tier-3 save/load commit).

**Perf: settings snapshot** *(9b91991)*. `get_setting` opened a fresh
SQLite connection per call — team_color alone fired it dozens of times per
render. Now ONE `SELECT` per rerun serves every settings read via a
session_state snapshot keyed on data_version + a 60s bucket; `set_setting`
patches it in place (read-your-own-writes); bare mode falls back to the old
path byte-for-byte. Also: page_chrome stops re-reading the 740-line
style.css from disk every rerun (mtime cache). 20-assert
`test_settings_memo.py`.

**Benchmark banners follow the preset** *(d9245aa)*. The team banner /
glance strip / zones (team_card) and the player-profile card baked
GitHub-dark hexes — your benchmark surface was the one thing that DIDN'T
reskin under Midnight/Forest/Slate. Now they consume
`--card-grad/--card-bg-2/--track/--subtext/--text/--good/--bad` (plotly
traces keep real hexes), and the `.pl-card`/`.rpl-card` leftover navy
gradient follows the preset.

**Header ladder finished** *(2d03101 + ride-along)*. War Room's hand-rolled
hero HTML → `ui.lab_hero`; Settings + Whiteboard → `page_header`. Ladder
now: masthead = flagship (TD), lab_hero = hero pages, page_header =
utility. The TD's page-local PALETTE renamed CHART_CYCLE — it is an
accent-led chart cycle, NOT a duplicate of ui.PALETTE (the frozen
team-identity hash palette that must never be reordered); §23-6 withdrawn.

**Skeleton shimmer** *(5bd3d98)*. New `ui.skeleton(tiles)` using the
`.skeleton` CSS that shipped unused; adopted on the two heaviest cold
paints (Rankings tracked box pass, TD Lab RAPM solve).

**Colorblind-safe mode** *(24864f8)*. Settings → Appearance toggle
(`cb_safe`, per-coach): swaps the green/red good-vs-bad pair for
blue/orange everywhere the tokens reach — CSS vars for cards/pills/bars,
`ui.GOOD/BAD` + HEAT/DIVERGE for charts, `cards.pctile_color` quartile
ladder, TD/Rankings page constants re-bound per run. One source:
`settings_utils.semantic_pair`. Team identity colours and the accent stay
put. 11-assert `test_cb_safe.py`.

**Findings, no code needed**: Officials already grew a season picker
(career default + per-season narrow) — §23-5's "no season awareness" is
stale for it; Schedule stays date-spanning per §13's own verdict.
`ui.season_picker` remains a documented, unconsumed helper.

**Remaining sweep (logged, not done)**: inline chart hexes in some
dashboard modules and the social-card PNGs keep classic green/red under
cb_safe; `cards.tier()` ladder (gold/green/blue) unchanged; `ui.chart()`
export container and cross-filter courts beyond the Players page still
unadopted (§23-4, C3/C4 of the overnight plan).

Verification: 68/68 script-test sweep; AppTest smoke on Hub, Rankings, TD
(Overview + Lab), Players, War Room, Settings (toggle renders), Whiteboard.

## 28. TIER 3 — BUILT (2026-07-18, while you were out)

All nine Tier 3 items (backlog 18-26) landed, one commit each, deployed to
the VPS after every item (app5-web restarted; tracker untouched all tier).
Verdicts first, receipts after.

**18. Theme-reactive charts — charts finally follow your preset.** You run
Midnight; every chart was hardcoded Dark. `CARD_BG/GRID/HEAT/DIVERGE` (+ new
text/subtext/border/body_bg tokens) now resolve from the active
STYLE_PRESETS row via `ui.refresh_theme_tokens()` (import-time fallback,
re-resolved every `page_chrome` run). The six cached helper modules that
froze the old constants at first import now read them off `helpers.ui` at
call time. Proof: AppTest under Forest carries the preset colour into 4
rendered Plotly figures on TD; `tracker/test_theme_tokens.py`.

**19. Roster CSV import — a whole roster in one paste.** Input Hub → Players
→ "📥 Import roster": upload a CSV or paste spreadsheet rows; tolerant parse
(header optional + alias-sniffed, `5'11`/`5-11`/`71` heights, "Last, First"
flip, per-line warnings) → previewed add/update/skip plan → one confirm that
runs the editor's own insert path (season stamping, identity auto-link,
grad-year default). Engine is pure (`helpers/roster_import.py`);
`tracker/test_roster_import.py` covers the variants + a throwaway-DB apply.

**20. Hall of Fame — the record book opened.** New "Single-game records" tab:
top-10 PTS/TRB/AST/STL/BLK nights, all seasons, tracked + hand-entered boxes
pooled (same fuel as the career sums), ties to whoever did it first. Plus
"🔔 Records watch" under the career leaders: active players whose own pace
passes a displayed career rung within ~5 games, verdict-sentence chips.
Empty locally only because 'Current' has no careers yet — engine covered by
`tracker/test_hall_of_fame.py`, boards verified on the archive.

**21. Nightly OSSAA refresh — packaged, one sudo step left for you.**
`deploy/app5-ossaa-refresh.{service,timer}` on the rollover pattern: 04:30
nightly (after the rollover check), `--days 3` fast refresh (~20-40 pages,
untracked-scores-only, idempotent), Persistent=true. Dry-ran clean locally
(offseason no-op). **Your install step, same as the rollover timer:**

```bash
ssh app5@107.170.27.154
sudo cp ~/app5/APP5.0/deploy/app5-ossaa-refresh.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now app5-ossaa-refresh.timer
```

(While you're in there: the season-rollover timer from §25 item 8 is still
uninstalled too — same three lines with `app5-season-rollover`.)

**22. Officials crew pairs — how refs call it TOGETHER.** Individual tab
gains a crew table: every pair (and full 3-man crew) with 5+ tracked games
together — fouls/game in their shared games, home/away lean %, PPP, Q4 call
share — verdict line first (tightest / most home-leaning, conf-dotted at
k=8). The archive has 11 real pairs, none past n≥5 yet, so prod shows the
honest empty state until the book grows. `tracker/test_crew_pairs.py`.

**23. War Room save/load — your prep survives the tab close.** Named saved
lineups (Creator) and named bracket configs (size, manual seeds for the real
OSSAA draw or auto field, plus the sim count + form weight) — two USER_SCOPED
JSON blobs per coach, 20-name caps, out-of-pool ids dropped on load with a
toast. Verified by AppTest round trips: save five → clear → load → exact pids
back; save 4-team bracket → fresh session → load → size/sims/form restored.

**24. Whiteboard playbook — plays persist, and they print.** The board is
now a real two-way component (same canvas JS, no new deps): draw → "⬆ Send
to app" → name it in the new 📓 Playbook expander → saved to `coach_plays`,
PRIVATE per coach. Storage honours the living-archive rule: compact rounded
ops JSON only (~120 bytes for a small play), 40-play cap, audit-skipped, no
PNGs in the DB ever — a `play_svg` renderer regenerates print-vector art on
demand for the SVG download AND a new "Saved whiteboard plays" section on the
printable scout sheet (own toggle, tracked + cold paths). Verified end to
end in a real browser: drew, sent, saved (row inspected in the live DB),
reloaded the page, loaded the play back onto the canvas, deleted it.
`tracker/test_playbook.py`.

**25. Mobile pass — phones get a real layout.** One shared
`@media (max-width:640px)` layer in assets/style.css (every page loads it):
mastheads shrink, KPI/metric and card/tile rows wrap 2-up instead of
stacking into a tall column, metric values scale, wide tables scroll in
place, tighter gutters. Browser-verified with computed styles at 375px
(metric row wraps 4→2×2 at 169px cols, zero horizontal overflow on TD + HoF)
and at 1280px (single row, full sizes — query correctly scoped). The
Schedule calendar's 7-wide rules stay inline — calendar-specific.

**26. WP calibration + weekly awards.** (a) `python -m tools.backtest
--wp-report` → `docs/WP_CALIBRATION_2025-2026.md`: 29 tracked games, 1449
curve steps, **Brier 0.0677** vs 0.2478 base-rate guessing; second half
0.016 vs first half 0.117. The reliability table says the model is a touch
UNDERconfident mid-range (10-30% buckets almost never win) — worth a
constant pass when the pool is bigger. (b) Hub "This week in the league"
strip (Paid, league-wide): player of the week (best Game Score week), game
of the week (GEI), riser of the week (snapshots) — anchored on the latest
game DATE so archives/offseason read right. Archive run composes Hannah
Bond / Anadarko-vs-Adair for the season's closing week.
`tracker/test_awards.py`.

**Session notes.** (1) Laptop gotcha discovered: the shell's default
`python` is MS-Store Python, which VIRTUALIZES `AppData\Local\APP5` — live-DB
checks must use the Python312 binary (now in assistant memory). (2) A
`.claude/launch.json` "app-noauth" config (port 8512, empty secrets file)
now exists for browser-pane verification without the login wall — local
only, untracked. (3) Concurrent with the second agent's UI pass (§27);
rebased cleanly around it all session.

Verification: full script-test sweep green after every item (66 tests by
tier's end — 5 new files); per-item AppTest smokes as noted; browser-pane
verification for items 24 and 25.

## 29. QUICK-HITS BATCH — BUILT (2026-07-18, solo session)

Six §24 grab-bag items + the §27 "remaining sweep", after Tiers 1-3 closed.

**Settings backup** *(39b9ed4)*: admin "Download season DB" — SQLite
backup-API snapshot (consistent while live), two-step prepare/download,
season-labeled filename.

**Event Editor coverage chips** *(d10f74f)*: whole-game play-call + defense
coverage % above the filters, semantic-pair colored, next to the bulk tools
that close the gap.

**TD Overview next-game strip** *(ccc5587)*: banner-grammar card composing
opponent, model line, rest edge (fatigue.rest_on_date) and crew outlook
(ref_tendencies) when refs are assigned. Display-only; sleeps when nothing
is scheduled (offseason now — verify on prod once the 2026-27 schedule
imports).

**Colorblind sweep finished** *(ca56019)*: every inline green/red that MEANS
good/bad now reads ui.GOOD/BAD at call time (Players cues + leader bar,
Rankings form/best-win/worst-loss, TD RAPM quadrant + error dots, War Room
bracket ladder + form tone, scout matchup edges + spacing warning, Officials
tiles + lean bar, Schedule legend dot). Categorical palettes (pies, schemes,
tier ladders, social PNGs) deliberately keep their hues. box_score's dead
GOOD/BAD constants removed.

**Roster Conf glyphs + Schedule Load chips** *(this commit's sibling)*:
● ◐ ○ sample-honesty column on the roster ratings table (conf_level k=8);
⚠️ 3-in-4 / 🔥 4-in-7 density flags on upcoming projections.

Verification: 69/69 script-test sweep; AppTest smoke on all ten touched
pages/views. Not done (still open): ui.chart() export adoption, cross-filter
courts beyond Players, cards.tier() ladder under cb_safe, gauge
consolidation, undo-toast for admin deletes.
