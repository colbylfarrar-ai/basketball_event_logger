# Spec 2 (tracker/UI) + Spec 3 (TO capture) + founder batch — 2026-07-18 design

Scope pre-approved by the founder handoff ("brainstorm/spec/plan per
superpowers, then build"); design decisions made autonomously and recorded
here. Context: `docs/RECAL_2026-07-18.md`.

## Spec 3 — turnover-kind capture bug (ship first)

**Root cause (confirmed in code):** `SERVER_FIELDS` in
`tracker/static/app.js:151` does not include `'turnover_type'`. `logTov()`
sets `ev.turnover_type = f.tovKind` correctly, but `toServer()` whitelists
payload fields against `SERVER_FIELDS` before the batch POST, so the kind is
stripped from every flow-logged turnover. The server (`EventIn`,
`tracker/api.py:142`) accepts the field and defaults it to `None`. The edit
path builds its own body (`formFromEvent` → PUT) which *does* carry
`turnover_type` — exactly the founder's repro (edit saves, LOG TURNOVER
doesn't). Data signature matches: whole PWA-tracked games 95–100% untyped.

**Fix:**
1. Add `'turnover_type'` to `SERVER_FIELDS`. (The actual bug.)
2. Quick-mode capture surface: the TO-kind selector currently hides behind
   `+ details`. The taxonomy is 5 entries (`TOV_TYPES`), so show it as a
   one-tap **chip row directly in quick mode** (like the Stolen-by row),
   replacing the buried `selRow` there; detailed mode keeps the current
   layout. No default kind is auto-applied for steal-TOs — "steal" is not a
   kind in the taxonomy (stolen_by is orthogonal) and guessing would pollute
   the tag.
3. Bump the service-worker cache version (`sw.js`) so clients pick it up.
4. No backfill is possible: the selection never left the device. Post-deploy
   data check via `tools/snapshot_report.py`'s TO diagnostic on future games.

**Test:** extend tracker tests with a regression that round-trips a flow-shaped
batch POST carrying `turnover_type` (API-level), plus a JS-side static check
that `SERVER_FIELDS` ⊇ the keys `logTov` writes (grep-style test in Python is
acceptable; the repo has no JS test runner).

## Spec 2.1 — possession-model WP on the tracker page + flow view

Today the Game Tracker page builds an inline made-baskets-only margin walk and
renders `wp_ribbon` from it; `game_wpa`'s `timeline` is the same makes-only
walk. The possession model (recal round 2) evaluates WP at **every
possession-ending event** (shot make/miss, turnover) plus FT makes — the curve
coaches should see: stops and giveaways move it.

**Build:** new pure helper `wpa.possession_timeline(events, t1, t2, end=None,
pregame_edge=0.0, sd_full=...)` → `[(elapsed, margin_home, wp_home)]` stepping
at every shot / turnover / made FT (margin changes only on scores; the step
still lands so time-decay of WP is visible through stops). Reuse it:

- `pages/2_Game_Tracker.py` live WP strip: replace the inline makes-only walk.
- `pages/6_Team_Dashboard.py` → Game Flow → Score-Flow Explorer: add the WP
  ribbon under the margin curve (same paid gating as the tracker strip;
  Score-Flow itself stays results-of-tracking, so the panel is tracked-only
  already).
- Analytics Hub "Game of the season" ribbon: same helper.

`game_wpa()`'s `timeline` and `wp_curve` stay makes-only: **GEI and
summarize keep reading the scoring curve**, because a denser curve inflates
the |ΔWP| integral and would silently re-score every past game's GEI
(awards / Hall of Fame history). The possession curve is a display upgrade
only.

## Spec 2.2 — tracker / live split

`2_Game_Tracker.py` currently stacks the watch surfaces and the manual
logging on one scroll. Split it with a top-level view toggle (the app's
established inner-view pattern):

- **Live** (default): scoreboard, quarter scores, fouls/bonus, possession-WP
  strip, win formula, live box, shot chart, PBP — plus the two new panels:
  - **Insights dropdown**: a selector that mounts extra insight panels on
    demand (Scout cues, Win formula, Shot chart, Play-by-play, Box score,
    WP strip), so the live screen shows what the bench wants and nothing
    else. Default set preserved from today's layout; selection kept in
    session state.
  - **Roster panel**: both teams' full rosters (number, name), on-court
    indicator from the latest lineup snapshot, live PF with foul-trouble
    highlight and PTS from this game's events — bench included (that's the
    difference from the live box, which only shows players with stats).
- **Log & fix**: Floor expander, manual event form, event corrections, Team
  Notes, Quick Add — everything from the "Logging & corrections" half.

No new sidebar page (keeps page numbering/deep links stable); the toggle is
the "truly separate" boundary and the Live view carries zero input widgets.

## Spec 2.3 — rating explainability + depth-of-track confidence tier

**Explainability (MAIN ratings only):** on the Players page and the dashboard
player card, the OVERALL rating (and the four pillar ratings) gain a `?`
popover/expander showing, for that player:

- leaf inputs per pillar: raw per-game values and their z-scores,
- the weights that combine them (`WEIGHTS`, `_OVERALL_PARTS`) — rendered as
  "what moved this number",
- shrink applied: evidence games vs `RATING_K_GAMES`, the anchor used (team
  prior + archetype blend) and how far the raw z was pulled,
- sample sizes: GP, tracked possessions, tag coverage where a leaf depends on
  an optional tag.

Engine: `player_ratings.player_profiles`/`player_ratings()` already compute
all of this; add an `explain(pid)`-style accessor that captures the
per-player components during the normal cached run (no second engine). Keep
the payload compact (dict of leaf → value/z/weight/contribution).

**Confidence tier:** `shrinkage.rating_confidence` + `coverage.team_coverage`
already measure the two axes (games evidence, tag coverage). Combine into a
visible 4-tier chip shown next to OVERALL (and on the team's Players table):
e.g. `Scouting look → Solid read → Deep book → Full profile`, thresholds on
the evidence fraction × coverage. The chip's tooltip names the cheapest next
action ("track 2 more games", "tag guarded-by on shots") — the same incentive
mechanic as the PWA header's tag meter, pushing coaches to tag more.

## Spec 2.4 — saved-play frame sequences

`helpers/playbook.py` stores one op-list per play (upsert by coach+name, cap
40/coach). Frames:

- Schema: reuse `coach_plays` with two new nullable columns `seq_name` and
  `seq_idx` (migration in `database/`); a frame row is a normal play whose
  `seq_name` groups it and `seq_idx` orders it (1-based). Standalone plays
  leave both NULL. **Each frame is one row → counts against the 40-play cap**
  (the DB-stays-small rule, per the founder's instruction).
- Whiteboard UI: "Save frame" appends the current board as the next frame of
  the active sequence (name picker seeded from the base name); the playbook
  list groups sequences and offers **slideshow playback** (prev/next + a
  simple auto-advance) rendering each frame through the existing component
  load path; `play_svg` unchanged (prints one frame; the scout sheet prints
  frames in order).

## Item 5 — League Landscape noise filters

The Rankings → League landscape tracked sub-tabs surface thin per-team rates
raw. Apply the recal noise policy where the data is event-derived:

- **Shrinkage on thin rates** via `helpers/shrinkage`
  (`stabilize_rate`/`stabilize_value` with `eb_prior` where a pool exists):
  Runs per-game rates, Play-types PPP, Defense scheme points-per-possession,
  Player-edge rates. Columns keep the raw n (GP / possessions) visible and
  captions state that thin rows are stabilized toward league mean.
- **Strategic-foul exclusions** (`helpers/late_game`): any landscape read
  built on foul counts uses the ns (non-strategic) counts, mirroring the
  discipline read. Audit during build; results-only tabs (landscape, tiers,
  Pythagoras, momentum, network) have no event inputs → untouched.

## Item 6 — rebounding enrichment

New pure module `helpers/rebounding.py` (+ `test_rebounding.py`), feeding a
Players-page section and a Team Dashboard panel. All rates shrunk via
`shrinkage` and labelled with the rebound-by tag coverage (85% on misses
league-wide). Reads, per player (team rollups where meaningful):

- **Defender-secures rate**: on missed shots where the player is `guarded_by`
  (on-ball defender), how often the rebound is secured by them / by their
  team (boxing out the shooter's look).
- **On-ball vs off-ball split**: player's defensive rebounds split by whether
  they were the on-ball defender on that miss (guarded_by == rebounder) —
  the "cleans up own assignment vs crashes from the weak side" read.
- **PnR rebounds by role**: on misses from PnR-tagged possessions
  (`play_type`), who secures — shooter's side vs defense, and the shooter-
  role split the tags support (PnR handler vs roll-man shots per the
  `playtypes` taxonomy; exact keys resolved at build).
- **Own-miss recovery**: shooter rebounds their own miss (rate over their
  misses).
- **3PA long-rebound profile**: OREB%/DREB% and top rebounders on 3PT misses
  vs 2PT misses, split by shot zone — the long-carom profile (no rebound
  location is tracked, so the shot's location is the axis; stated in the
  caption).

## Item 7 — living MLM (fluid weights, gated)

Make the recal loop recurring without weakening the gates:

- **`tools/living_recal.py`** (oneshot): counts tracked games since the last
  run (state in `app_settings`); below a threshold (default 3 new games) it
  exits. Otherwise runs the T1/T2/T6 gate battery incumbent-vs-sweep
  (`tools/backtest.py`, `tools/sweep_recal.py` surfaces), applies the
  **beat-or-tie rule on the OOS gates** exactly as recal round 2 defined it,
  and only then adopts.
- **Adoption = config, not code:** new `helpers/model_constants.py` — a tiny
  override layer reading `app_settings` key `model_constants` (compact JSON).
  `team_ratings` / `player_ratings` resolve their sweepable constants
  (`DEFAULT_REG`, `DEFAULT_SOS_WEIGHT`, `RATING_K_GAMES`,
  `TEAM_PRIOR_LAMBDA`, penalty weight, `ARCH_ANCHOR_BLEND`) through it, code
  defaults unchanged. Only this registered surface can auto-adopt; WPA credit
  constants stay design constants (no honest gate — unchanged from recal 2).
- **Every run logged** (adopt or hold): appended to `app_settings`-backed
  compact history + a human line in `docs/RECAL_LOG.md` locally; the admin
  Settings panel shows the last run, its gate table, and what (if anything)
  changed.
- **Triggers:** `deploy/app5-living-recal.service` + weekly `.timer`
  (off-peak) added to the pending founder-sudo install batch, plus an admin
  "Run recal check now" button in Settings so the loop works before the
  timer lands. No mid-request background sweeps inside the web workers.

## Item 8 — district standings, intra-district games only

`5_Rankings.py` "Standings — by district": W-L currently uses overall record.
Change the group's standings to **intra-district record** — games where both
teams carry the same non-empty district, plus games tagged
`game_type='District'` (belt for schedules where the opponent's district
field is unset). Overall W-L stays as a second column; teams with no
intra-district games show "—" and sort last. Caption explains the rule.

## Item 9 — multi-coach same-game: audit + retrack flow

**Audit result (already verified in code):** dedup exists and is wired —
`helpers/game_dedup.py` collapses duplicate tracked games of the same real
game to ONE canonical row (admin override → detail-density → events/id
tie-break) and `helpers/entitlement.py` routes pool reads through
`representative_game_ids`, so aggregates don't double-count today.
`pages/12_Settings.py` has the admin resolve-duplicates UI. Remaining gaps:
(a) a coach starting a duplicate track gets no signal, (b) the live/fan links
are per-game rows, so two coaches can publish two live pages of one game.

**Retrack flow (build):**
- On PWA game creation, the API checks `matchup_key` against existing tracked
  games for that date/pair and returns a `duplicate_of` hint; the client
  shows a non-blocking notice: "Already tracked by <coach> — your track will
  be kept separate; the pool shows the most detailed version" with a
  **Retrack** confirm. No hard block (a second angle is legitimate).
- Settings duplicates panel: also surfaced to the two teams' own coaches
  (read-only candidates + "request canonical" via the existing
  change-request path); the pick itself stays admin/founder.
- Live links: unchanged this round (fans following either link still see a
  real feed); noted as a known quirk in the FAQ.

## Item 10 — FAQ in-app, founder keeps editing the Google Doc

**Pick: synced import** (over iframe embed / native editor). The founder
keeps editing the Doc; the app fetches the doc's plain-text export
(`.../export?format=txt`, works for link-shared docs), caches it in
`app_settings` (`faq:content`, capped ~100 KB, plus `faq:fetched_at`) with a
6-hour TTL and an admin "Refresh now" button, and renders it as a native page
— heading heuristics (the founder's Doc uses Q:/A: or heading lines) →
expander-per-question, searchable. Fallback when fetch fails: last cached
copy + a "view the Doc" link. New light page `pages/15_FAQ.py`, visible to
every signed-in role (and linked from the PWA header "?" if cheap).
Rationale: iframe embeds of Docs are mobile-hostile and style-broken; a
native editor breaks the founder's workflow.

## Quick hit — `season='Current'` empty-default footgun

`'Current'` is the correct active-season sentinel (model A), but post-rollover
the active season is empty, so the no-arg defaults (`stats._game_filter(None)`
→ `_TRACKED_SUBQUERY`, `games_played`, `coverage._team_tracked_game_ids`)
silently return zero events — the class of bug behind the DWPA EP failure.
Fix: resolve the default at call time — tracked games of the active season,
**falling back to the most recent archived season when the active season has
no tracked games**. One helper in `helpers/seasons.py`
(`default_tracked_season_clause()` or similar), reused by `stats` and
`coverage`; explicit `game_ids`/season args behave exactly as today. Tests
cover the post-rollover fallback and the in-season no-change case.

## Out of scope this round

§29 leftovers (ui.chart() export adoption, cross-filter courts, cards.tier()
ladder, gauge consolidation, undo-toast) unless a task already touches the
same lines; VPS timer installs (founder sudo); live-link merging for
double-tracked games.

## Testing & deploy

- Repo pattern: pure engines get `tracker/test_*.py` modules, run **one per
  process** with the Python312 interpreter (AppData virtualization rule).
- AppTest smokes for every changed page (no-secrets cwd bypasses auth; seed
  `ta_team=1`, `ta_season=2025-2026`).
- Deploy per memory: push → ssh pull → restart `app5-web` (+`app5-tracker`
  and PWA cache bump — app.js/sw.js change in Spec 3), `snapshot_report` TO
  diagnostic re-run after the founder's next tracked game.
