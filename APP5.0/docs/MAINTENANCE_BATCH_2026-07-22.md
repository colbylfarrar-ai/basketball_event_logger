# Maintenance batch — Wednesday 2026-07-22 deploy

Bugs + features stacked during the coach-onboarding window (opened 2026-07-20).
Deploy target: Wednesday 2026-07-22. Deploy flow: push → ssh pull → restart app5-web.

---

## 1. BUG — Rosters panel doubles every returning player after a rollover  ✅ root-caused, fix ready

**Symptom:** In the Streamlit Game Tracker "Rosters" panel, each opponent player
is listed twice (one row carries the live On/PF/PTS, its twin shows zeros).
Reported via coach screenshot (Kansas Girls / Westville Girls, game #58).

**Root cause:** `pages/2_Game_Tracker.py:823-825` — the "Rosters" panel query is
the one roster read in the app that is **not** season-scoped:

```python
_ros = query(
    "SELECT id, name, number, team_id FROM players "
    "WHERE team_id IN (?,?) ORDER BY team_id, number", (t1id, t2id))
```

After a New-Season rollover every carried player has TWO rows in `players`:
- `archived=1, season='<label>'` — original (game_events point here)
- `archived=0, season='Current', identity_id → original` — the carry-forward

The unscoped query returns both → the panel doubles. The twin that events
reference shows the real stats; the empty carry shows zeros. Verified against the
live DB: Kansas "0" (no Current twin) appears once, "1"–"5" (twins) appear twice —
exact match to the screenshot.

Every OTHER roster read already scopes via `SEAS.roster_clause` (lines 182, 1098,
1457; PWA endpoint `tracker/api.py:296`, fixed in `be11b21`). This panel was
missed. **Not data corruption** — the two rows are the correct rollover artifact;
the panel just fails to pick one.

**Fix** (`_roster_c` / `_roster_p` already computed at line 324, in scope here):

```python
        _ros = query(
            f"SELECT id, name, number, team_id FROM players "
            f"WHERE team_id IN (?,?) AND {_roster_c} ORDER BY team_id, number",
            (t1id, t2id, *_roster_p))
```

Current game → `archived=0` drops the archived twin; past game → `season=<label>`
drops the Current twin. Simulated across all 56 Kansas/Westville games: zero
doubles after the change.

**Related (log-only, lower priority):** `pages/2_Game_Tracker.py:547` `proster`
is also unscoped, but it only builds an id→name/team dict so duplicate ids
collapse harmlessly. Scope it too for tidiness when touching this file.

**NOT a bug:** opponent players named by jersey number ("0".."33") — coaches
quick-add opponents by number, real names unknown. Identity linking intact.

---

## 2. FEATURE — Correct the on-court five (fix a missed sub)  ✅ BUILT + verified on branch (commit 82638de), NOT deployed

**Built:** engine in `helpers/event_log.py` (`recompute_game_plus_minus` — from-scratch
+/- rebuild, proven == live incremental on all 43 real games; `floor_run` — contiguous
stale-run detection; `correct_floor_forward` — dedupe + roster-validate + re-snapshot the
run + recompute; `floor_integrity` — flags != 5 floors for IMPROVEMENTS #5). UI: "Fix a
missed substitution" panel in `pages/3_Event_Editor.py` (pick anchor event + team, edit the
pre-filled five, auto-range preview, Apply). Model chosen: editable-five + auto contiguous
run (id-order). Unit `tracker/test_retro_floor.py`; click-path smoke-verified on a live-DB copy.



**Need:** coach misses a substitution → events get credited to the wrong five
until caught, and +/- is snapshotted per event, so the error persists.

**Where:** the floor is snapshotted into `game_event_lineup` per event by
`helpers/game_events.py:47 _snapshot_and_apply_pm`; live picker in the tracker
(`pages/2_Game_Tracker.py` lineup section ~423-435; PWA equivalent in
`tracker/static/app.js`). Retro correction likely belongs in the Event Editor
(`pages/3_Event_Editor.py`).

**Ask:** a way to change the on-court five from a chosen event forward (re-snapshot
`game_event_lineup` + recompute the affected +/-). Ties to IMPROVEMENTS.md #5
("warn when the lineup is not exactly 5" + dedupe the five) — do both together.

---

## 3. FEATURE — Hockey assists (secondary assist)  ⚠ needs new capture; LOW priority
### My additive READ path ✅ BUILT + verified on branch, NOT deployed (founder wires live capture Wed)
Built the opt-in, purely-additive read side: migration `game_events.hockey_from_id`
(nullable INTEGER REFERENCES players, NULL everywhere on existing DBs → HAST reads 0
until tagged); HAST slot in the `helpers/stats.py` box builder (`_blank_box` seeds
0; credited to `hockey_from_id` on a MADE shot, sibling to AST/SCR_AST, `.get()`-guarded
so hand-built event dicts don't KeyError); `P` mapping `HAST`/`HAST/G` in
`helpers/player_ratings.py:player_stat_table`; surfaced next to ScrAST in
`helpers/dashboard/player_card.py` render_card (row appears ONLY when HAST>0 — no
clutter pre-capture); glossary entry (Playmaking/Paid). Unit `tracker/test_hockey_assist.py`
(RED→GREEN, 9 asserts). Smoke: real DB → 242 players build P (HAST=0 everywhere);
render_card runs no-exception both branches; row hides at 0, draws `3 (1.0/g)` at >0.
STILL FOUNDER'S (Wed): capture tap on the 3 trackers (PWA app.js, Streamlit
2_Game_Tracker.py, Event Editor 3_Event_Editor.py) writing hockey_from_id.

**Need:** credit the pass that led to the assist (the "hockey assist").

**Capture — NOT derivable.** Shot events store only the terminal pass
(`pass_from_id` = assist) + the screener (`shot_created_by_id` = SC). Passes are
not standalone events, so the ball-movement chain isn't in the data. Requires a
**new field** `game_events.hockey_from_id` +:
- DB migration
- capture tap on all three trackers: PWA `tracker/static/app.js`, Streamlit
  `pages/2_Game_Tracker.py`, Event Editor `pages/3_Event_Editor.py`
  (optional "pass before the pass" on a made, assisted shot)

**Existing playmaking engine to fold into (don't build new):** `helpers/stats.py`
box builder (~140-200) already tallies **AST**, **SC** (shots created), **PotAST**
(potential assists), **ScrAST** (screen assists), `ast_rate`; plus `xPPS_created`
(look quality). Add **HAST** as a sibling; optionally discount-credit the secondary
passer in `xPPS_created`.

**Playmaking "tab" = ** the *Rebounding · Playmaking · Defense* block in
`helpers/dashboard/player_card.py:1058`; HAST slots next to PotAST/ScrAST at
lines 1080-1087.

**Recommendation:** LOW priority. Second-passer tap per made shot = real friction
on a live phone tracker (HS girls), and SC/PotAST already capture "movement created
this look." If built: opt-in, purely additive, no derivation shortcut exists.

---

## 4. FEATURE — Pull rebounding enrichment from Players page onto the Team Glass subtab  ✅ built + smoke-verified on branch (commit 262b36d), NOT deployed

**Need:** the richer rebounding reads added to the Players page aren't on the Team
Dashboard Glass subtab.

**Source (already built, Paid):** `helpers/rebounding.py` —
- `player_rebounding` — secures-own-contest % (box-out payoff), on-ball vs
  weak-side DREB split, own-miss recovery
- `team_long_rebound_profile(team_id, …)` — **already team-level**, 3PA long-rebound
  OREB% (2PT vs 3PT misses; who secures opp 3-miss boards)
- `pnr_rebound_roles` — who secures PnR misses (handler / screener / other / defense)

Surfaced per-player at `pages/7_Players.py:1172-1232` ("Rebounding enrichment").

**Gap:** Team Glass subtab (`pages/6_Team_Dashboard.py:2384-2458`) has only
box-derived OREB%/DREB%/Opp-OREB% + game-by-game trend — none of the enrichment.

**Scope:** wire enrichment into Glass at team level, same Paid gate, scoped to the
dashboard's season game pool:
- `team_long_rebound_profile` — drop-in (already team-scoped)
- `pnr_rebound_roles` — team-scope it
- team box-out-payoff — aggregate `player_rebounding` `def_secure_team_pct` to team,
  or add a team helper (on contested/`guarded_by` misses, how often the team ends
  the possession)

---

## 5. FEATURE — Coaches online on the MAIN app + capacity monitor  ✅ 5a+5b built + smoke-verified on branch (commit db78dca), NOT deployed. Cache-scoping (action-order #1) belongs to item #6 → Wednesday.

Scope narrowed (founder steer 2026-07-20): the live/fan/tracker side does NOT
matter (tracker works offline). What matters is the **main coaching app**
(`app.hooptracks.com` / `app5-web`) — a slow dashboard is the difference between a
quick halftime check and constant frustration. So: (a) how many coaches are on the
whole app at once, and (b) whether the box is close to needing an upgrade.

Env: droplet `app5@107.170.27.154` (hooptracks), Caddy proxy, systemd. **Droplet
size not in DEPLOY.md** — confirm via ssh (`nproc`, `free -m`) for absolute
thresholds. No `psutil` dep — read `/proc` directly (zero deps, pip-only ethos).

### 5a. Coaches online — whole app, concurrent — small, high value
NOT the per-game fan counter (`public_feed.py:254 fan_count` = cumulative
daily-unique per game; wrong tool). Streamlit runs ONE process (`app5-web`) and
every coach is authenticated, so:
- **Hook:** `helpers/ui.py page_chrome()` (runs on every page render; already
  resolves the coach via `require_login()` → email at `helpers/auth.py:297`). Stamp
  `presence[email] = now` there.
- **Store:** module dict behind `st.cache_resource` — shared across all sessions in
  the single process. No DB writes on the hot path.
- **Count:** `online = emails with last_seen < ~90s`. Surface "N coaches online"
  in the admin panel (`pages/12_Settings.py`).
- **Caveat:** Streamlit only reruns on interaction, so an idle-but-open tab ages
  out of the 90s window. "Active in last 90s" = *actively using* — the right number
  for load. "Tabs open" would need a client ping; not needed here.

### 5b. Capacity monitor "close to upgrade" — ops, admin card
Home: existing admin panel (`pages/12_Settings.py` + `helpers/server_control.py`,
already Linux-aware, has `live_games()`). Add `server_capacity()` reading `/proc`
(RAM% `/proc/meminfo`, load avg vs `nproc`, disk% `os.statvfs`) →
**healthy / watch / upgrade-soon**. Upgrade signal = peak RAM/CPU during game
windows (Fri/Sat) + **peak concurrent coaches (feeds from 5a)**; persist a rolling
weekly peak in `app_settings` so the founder sees worst-case load, not the idle
moment the page opened.

**IMPORTANT — separate load-bound from compute-bound slowness.** The dashboard is
heavily cached (`@st.cache_data(ttl=600)`, 20+ funcs) but the cache is GLOBAL and
cleared whenever `data_version` moves (`helpers/ui.py:118-134 _sync_external_writes`
→ `st.cache_data.clear()`), which the tracker bumps on finish/undo/edit/create/quick-add
(`GE.bump_data_version`, 10 call sites in `tracker/api.py`). So a halftime open
right after tracker activity can hit a COLD cache → full engine recompute, slow
even on a quiet box. The monitor must show BOTH server load AND last render time so
"slow" isn't misread as "need a bigger droplet" when it's really cache churn.
(Possible separate fix: scope invalidation instead of a global clear — flag for its
own investigation if halftime slowness persists.)

**Priority:** 5a + 5b together (5a feeds 5b's concurrency + the load-vs-compute read).

### 5c. Capacity reality — measured on the box (2026-07-20)
`ssh app5@…` read-only: **1 vCPU · 2 GB RAM · NO swap** (DO s-1vcpu-2gb). Idle load
0.01; `app5-web` 537 MB resident (peak 759 MB), ~970 MB free.

- **Binding constraint = 1 vCPU, not RAM.** Streamlit reruns are CPU-bound
  (pandas/sklearn/statsmodels) and serialize on one core. RAM is comfortable
  (shared `st.cache_data` is global, not per-session; per-session mem is small).
- **Warm cache** (weekday/offseason/staggered): cache hits are cheap → dozens
  onboarded, ~10+ concurrent browsing fine. Lots of headroom.
- **Cold cache = the Friday risk.** Live-game `data_version` churn → global cache
  clear → every coach's halftime open is a cold recompute; on 1 core those
  serialize and pile up. Multiple simultaneous games = cache never warms.
- **Trial sizing:** onboarded ≠ concurrent (peak concurrent ≈ 10-25% of onboarded).
  Onboard **~15-25 coaches** confidently IF the cache-scoping fix lands; ~10 and
  stagger without it.

**Action order (do the free things first, upgrade only on data):**
1. Scope cache invalidation (kill the global `st.cache_data.clear()` — see 5b note).
   Highest-leverage, $0. Keeps caches warm through live games.
2. Add a 2 GB swapfile — free OOM insurance (box has none today).
3. Ship 5a/5b, measure peak concurrent + render time over the first Fridays.
4. Resize 1→2 vCPU (~$12→$18/mo, 2-min DO resize) ONLY if measured Friday load
   stays >~1.5 on one core or cold renders exceed ~5 s.

**GPU droplet — do NOT (decision 2026-07-20).** Zero concurrency benefit here. GPUs
accelerate CUDA/parallel-matrix work (torch/tensorflow/rapids); the app is
Streamlit + pandas/numpy/sklearn/statsmodels = all CPU, no CUDA path — a GPU would
sit idle while reruns still run on the CPU. Concurrency is bound by **CPU cores +
the Python GIL** (each coach's rerun = one CPU-bound thread), which only more
**vCPUs** relieve, not a GPU. Scale path stays: cache-scoping (free) → more vCPUs → lighter engines.

**GPU for the ML layer "once we have enough data" — NO (also decided 2026-07-20).**
`ML_LAYER_ROADMAP.md` designs the whole layer as small-data classical ML (ridge,
EB shrinkage, k-means, thin regularized GBM, ridge-logistic, small Monte-Carlo) and
explicitly rules out deep learning by volume ("need 1e4–1e6+ examples"). Data is
structurally capped (fixed games/season; more coaches = more small tabular data,
never NBA-tracking scale), and GBMs beat NNs on tabular anyway — so no data
threshold ever makes a GPU pay off for analytics. All CPU, trains in seconds/minutes.
The ONLY genuine GPU workload is the **auto-tracker** (game film → events, computer
vision — `AUTO_TRACKER_FEASIBILITY.md`): if it ships, rent a GPU box by the hour for
training batches or use an inference API — a separate, temporary box, never the
serving droplet. (An on-box local LLM for the NL shell is inference-only, usually a
hosted API / small quantized CPU model — not a training-GPU need.)

---

## 6. PERF — Spike-hardening across app / tracker / live (clear winners)

Goal: keep all three surfaces fast so a random-Tuesday traffic spike is survivable
on the 1-vCPU/2-GB box (see 5c). Scoped from a hot-path read of the actual code.

**Already good — DO NOT redo:** DB has WAL + `busy_timeout=5000` + `synchronous=NORMAL`
+ broad indexes (`database/db.py:169-183, 275-522`). Live/fan already has 3 s TTL
caches (`helpers/public_feed.py:38 CACHE_TTL`, state/scoreboard/team/directory) —
"N fans = ~1 DB read per window." Tracker is offline-first, event-driven, flush every
20 s (`tracker/static/app.js:2457`) — no poll-hammer. Dashboard engines are
`@st.cache_data(ttl=600)` (20+ funcs).

### Tier A — biggest leverage, do first
1. **Scope cache invalidation (app).**  ✅ BUILT + verified on branch (commit 11e4682),
   NOT deployed. THE spike win. Was a GLOBAL `st.cache_data.clear()` on any
   `data_version` bump; now per-`(gender, season)` counters + a `declare_scope()` gate
   (`helpers/ui.py`, `helpers/game_events.py`). A live game only clears its own pool;
   other genders/seasons stay warm. Grain is (gender, season), NOT per-team (per-team
   needs fragile per-func arg-versioning — deliberately avoided; miss = stale data).
   Write side threads `game_id` through the 8 game-scoped tracker bumps + both desktop
   bumps; roster/officials/rollover stay ALL-scope. Rendezvous (read key == write key)
   smoke-verified on the real dashboard. Unit: `tracker/test_scope_invalidation.py`.
   NOTE: in-page desktop-edit clears (Event Editor / Input Hub `st.cache_data.clear()`)
   are still global in-process — acceptable (rare during the phone-tracked Friday
   spike), a possible follow-on.
2. **Reuse DB connections (app + tracker + live).**  ✅ BUILT + verified on branch
   (commit f0a0cf2), NOT deployed. Thread-local persistent connection keyed by db path
   + `cache_size=-65536` + `mmap_size=256MB` set once per connection, rollback-on-error
   so a persistent conn never carries an aborted txn. Real Team Dashboard render =
   2 sqlite opens (was hundreds). Unit: `tracker/test_conn_reuse.py`.

### Tier B — strong
3. **Lazy-gate dashboard tabs (app).**  ⚠ MOSTLY MOOT — code read (2026-07-21) shows
   Team Dashboard ALREADY gates every view behind `if _tdview == "X":` (only the open
   view's engines run). The unconditional pre-gate cost is just the shared
   league-ratings header (cached + now scope-warm via #6a). `st.fragment` would add
   little; skipped. Re-check the other pages only if measurement flags a specific view.
4. **Cache pre-warmer (app).** Small background job: after a bump settles, precompute
   current-season league aggregates so the FIRST coach open on a busy night is warm,
   not cold. Turns cold-Friday into warm-Friday.
5. **Swapfile (ops).** No swap today — free OOM cushion under spike. (Also in 5c.)

### Tier C — polish / defensive
6. **Caddy long cache-control** on PWA static (`tracker/static/*` app.js/css/court
   images) so repeat + spike loads hit browser/Caddy, not the app. *Verify the
   Caddyfile on the box — not in repo.* `sw.js` already caches PWA-side.
7. **Fold `fan_count` into the cached `state_by_token` payload** (live,
   `public_feed.py:207-257`) — saves 1 query per fan poll. Minor (state already 3 s
   cached).
8. **Prod Streamlit config** — usage-stats off, `client.showErrorDetails=false`, sane
   `server.maxUploadSize`. Minor.

**Order:** #1 + #2 = the spike-readiness core (stay warm + stop reconnect churn).
#3-#5 harden. #6-#8 cleanup. All safe to bank now, independent of what 5a/5b measure.

---

## 7. FEATURE FAMILY — Cross-sport analytics (ball movement & value-per-action)  ⚠ SCOPED, NOT BUILT

Origin: coach meeting asked for a **ball-movement metric**. Explored cheap paths;
locked the decisions below. These are **scoped, not shipped** — the batch's actual
built/deploying items are #1–#6. #7 is the next-session backlog.

### Taxonomy — LOCKED (do NOT re-litigate)
- **"Secondary" rename → REJECTED.** Collapsing screen / hockey / off-ball into one
  bucket loses specialty info and doesn't answer the ask.
- **Play-type-derived hockey assist → SCRAPPED.** Play type is a valid proxy for
  "a screen occurred," INVALID for "a 2nd pass occurred" (iso guarantees no 2nd
  pass → a false-positive machine, not a floor).
- **Hockey assist → SEPARATE FIELD** (founder building Wed). New
  `game_events.hockey_from_id` + capture tap on all 3 trackers (PWA
  `tracker/static/app.js`, Streamlit `pages/2_Game_Tracker.py`, Event Editor
  `pages/3_Event_Editor.py`); slot HAST into the `helpers/stats.py` box builder.
  Full detail in item #3.

**Two-axis model (the mental lock):**
- **Axis 1 = what the action IS** — typed slots: `screen_assist` = today's
  `shot_created_by_id`; `hockey_from_id` = a SIBLING slot, never an overload of it.
- **Axis 2 = play type (scheme).**
- Orthogonal — neither axis defines the other.

### Ship candidates — CODE READ DONE (2026-07-21), classified surface-vs-build
- **7a — xA (expected assists).**  ✅ DERIVABLE, SURFACE not build. The math already
  runs — it's just being AVERAGED away. `passer_completion` (`helpers/stats.py:831`)
  already sums `c["xsum"] = Σ make-rate[(zone,creation,guarded)]` over a passer's fed
  shots, then divides into `xfg_pct`. **That un-divided sum IS xA** (expected assist
  COUNT). And `passer_look_quality`/`xPPS_created` (`:799`) already sums
  `c["xpts"] = Σ rate*shot_value` (expected assist POINTS = the ball-movement value),
  divided into its per-feed average. So xA + xA-points = exposing the running sums the
  two engines already compute — no new math, no schema. Scope: extract the sums →
  map `xA` / `xA_pts` into the `player_stat_table` P dict → row next to AST/PotAST in
  `player_card.py`, with `AST − xA` (finishing luck on the passer's feeds) as the
  verdict line (both terms already in P). SMALL. Ship candidate.
- **7b — EPA / value-per-action.**  ⚠ SPLIT. True NFL-style EPA (EP(state_after) −
  EP(state_before) per action) = BUILD **and a poor fit**: it needs a possession-
  VALUE-STATE model, but the app ends a possession on shot/turnover with NO tracked
  intermediate states (no down/distance analog), and HS possessions are short — the
  state model has nothing to price. `helpers/possession_value.py` is a team possession
  LEDGER (points-sources + outcome mix + PPP), not per-action EP. **Defer true EPA.**
  A pragmatic "value-added per action vs baseline" IS cheap, though: shot action value
  = `expected_points_per_shot` (`:769`, xPPS) − league/team baseline PPP
  (`possession_ledger` ppp / `_league_ppp_by_type`); turnover = the ledger's empty-trip
  leak. That's an AGGREGATION of existing engines, optional cheap surface if coaches
  ask for "value per action" — but 7a is the better ball-movement answer.
- **7d — Corsi** (on-floor attempt differential) — reuses the +/- plumbing. Cheap.
- **7e — forced / unforced TO — FREE, no schema.** `stolen_by_id` already present →
  a `steal-forced` bucket (name it exactly that — it's a floor, not true "forced").
  Hooks `helpers/defenses.py:336 team_defense_turnovers`.

**Read verdict (GATE cleared):** 7a = SURFACE (small, ship candidate — the real
ball-movement answer coaches asked for). 7b = defer true EPA (build + poor data fit);
optional cheap "value-vs-baseline" surface only if asked. 7e still the free first step.
Batch order when #7 gets picked up: 7e (free) → 7a (surface) → 7d (cheap) → 7b optional.

---

## 7. FEATURE — Cross-sport analytics steals (coach-meeting "ball movement" ask)

Origin: coach meeting asked for a **ball-movement metric**. Decided NOT to solve it
by renaming `shot_created_by_id` → a generic "secondary" bucket — that collapses
distinct actions (hockey assist ≠ screen assist ≠ swing pass), destroys specialty
film, and doesn't answer the ask. Instead: purpose-built metrics below. Ranked by
effort:win. #7c (hockey assist) is the pre-existing item #3 — needs new capture, stays LOW.

### 7a. xA — expected assists  ✅ derivable, no schema — HIGHEST win
Value a completed assist by the **shot quality it created**, not whether it dropped.
Passer credit that survives a teammate's cold night = the real ball-movement read.
- **Data:** already there. Shots store the terminal pass (`pass_from_id` = assist);
  shot-quality engine exists (`helpers/stats.py:760 expected_points_per_shot`,
  `:791 xPPS_created` — "expected value of the LOOKS a passer sets up").
- **Scope:** xA ≈ sum of `expected_points_per_shot` over shots where this player is
  `pass_from_id`. `xPPS_created` may already BE this or 90% of it — **verify before
  building** (it may only need surfacing + an AST-side label, not new math).
- **Surface:** playmaking block, `helpers/dashboard/player_card.py:1058` next to
  AST/PotAST/ScrAST; add `AST − xA` (finishing luck on your passes) as the verdict line.

### 7b. EPA-style value-per-action (NFL steal)  ⚠ check-first, likely partial
Points-per-possession value added by each action vs expected. The engine may already
exist: `helpers/stats.py:760 expected_points_per_shot` + Tier-2 `possession_value` /
`concession` helpers (`:1697`). **Investigate before scoping as new** — if EP-per-
possession is computed, "action-level EPA" is an aggregation + surfacing job, not a
build. If it's genuinely missing, it's a bigger lift (needs a possession-value model) —
defer. Action: 30-min code read to classify (surface vs build), THEN size.

### 7c. Hockey assist — SEPARATE-FIELD CAPTURE (decided 2026-07-21). See item #3.
Founder decision: build it as a real captured field (`game_events.hockey_from_id`),
NOT derived. Play-type derivation was explored and **scrapped** — see the taxonomy
decision below for why it's impossible to floor. New field + capture tap on the three
trackers (per #3). Priority stays where #3 puts it; slot HAST into the playmaking box
(`helpers/stats.py` box builder) once captured.

### Taxonomy decision (2026-07-21) — LOCK THIS, do not re-litigate
Explored making "secondary" play-type-aware / play-type-derived to avoid new capture.
Conclusion:
- **Two orthogonal axes.** Axis 1 = what the action IS (screen assist / hockey assist /
  off-ball / DHO — each its own typed slot). Axis 2 = play type (the scheme). Neither
  defines the other. `shot_created_by_id` today = the `screen_assist` slot specifically;
  hockey assist is a SIBLING slot (`hockey_from_id`), never an overload of that field.
- **Play type is a valid proxy for "a screen occurred," an INVALID proxy for "a 2nd
  pass occurred."** PnR / Off Screen / DHO literally ARE screen actions → deriving a
  `screen_assist` floor from them is a definition, one-directional, safe (engines/helpers
  only, no schema). But "pass before the assist" is a possession-CHAIN fact no play type
  encodes; **Isolation guarantees its ABSENCE**, so mapping iso/post/spot-up → hockey
  assist FABRICATES ball-movement signal (false positives, not a floor). Fails the floor
  test → scrapped.
- **Mapping bugs found (if the screen floor is ever built):** Putback is NOT a screen
  (pull it); BLOB/SLOB are often scripted screen SETS (lean Screen, not "Secondary");
  Duck In / Post Up are weak/maybe.
- **The ball-movement ask coaches actually made is carried by xA (7a), not hockey
  assist** — xA is derivable from the already-stored terminal assist pass, floor-clean,
  no capture. Hockey assist is a separate nice-to-have, captured, additive.
- **Design B rule (if secondary ever gets a play-type view):** measure the action FLAT
  (always computes), SPLIT by play type only when tagged + min-N guard. Never make an
  action's value REQUIRE play type (that's "Design A" = death: couples two independent
  taps, shatters a thin HS-girls sample across an empty grid).

### 7d. Corsi-style on-floor shot-attempt differential (NHL steal)  ✅ small
On/off already exists (+/- snapshotted per event, `helpers/game_events.py:47`).
Add attempt-differential (shots FOR − AGAINST while player on floor, made+missed) —
a lower-variance running-mate to +/- (rewards generating/suppressing attempts, not
just makes). Reuses `game_event_lineup`; no new capture. Cheap once +/- plumbing is
understood.

### 7e. Forced vs unforced TO split (tennis steal)  ✅ FREE, no schema — do first
Proxy: `stolen_by_id` present → **steal-forced**; null → **unforced**. Zero new
capture (`charges.py:140`, `defenses.py:350` already carry it). Hooks the existing
disruption engine (`defenses.py:336 team_defense_turnovers` already tallies "forced
per defense").
- **Honest naming:** call it `steal-forced TO%`, NOT `forced TO%`. Bias is one-
  directional: pressured-but-no-steal (bad pass OOB, 8-sec, forced charge) tags as
  unforced → **forced is a floor (undercount), unforced inflated.** A floor is
  defensible; a random error is not. Ship the proxy, note the floor, upgrade to a
  real forced flag only if coaches push.

**Batch verdict:** 7e (free) + 7a (derivable, may already exist) = ship candidates.
7b + 7d = scope-then-size. 7c = separate-field capture (founder building it), see #3.
