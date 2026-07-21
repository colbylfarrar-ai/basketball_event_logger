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

## 2. FEATURE — Correct the on-court five (fix a missed sub)

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

## 4. FEATURE — Pull rebounding enrichment from Players page onto the Team Glass subtab

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

## 5. FEATURE — Coaches online on the MAIN app + capacity monitor

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
1. **Scope cache invalidation (app).** THE spike win. Today any `data_version` bump
   does a GLOBAL `st.cache_data.clear()` (`helpers/ui.py:118-134`), so one live-game
   write busts every coach's warm cache → everyone cold-recomputes on 1 core. Make
   the version per-scope (per-game / per-team) so a game only invalidates its own
   reads; season aggregates for other teams stay warm. (Same fix flagged in 5b — it
   is the #1 item.)
2. **Reuse DB connections (app + tracker + live).** `db.query()`/`execute()` open a
   NEW connection + 4 PRAGMAs + close on EVERY call (`database/db.py:170-183,
   692-713`). A cold dashboard render fires hundreds of queries → hundreds of
   reconnects on 1 vCPU. Use a thread-local persistent connection (safe under WAL;
   Streamlit ScriptRunner + uvicorn threadpool are per-thread — key the cache by db
   path so a season swap re-opens). Then set once per connection:
   `PRAGMA cache_size=-65536` (64 MB) + `PRAGMA mmap_size` (e.g. 256 MB). Helps all
   three surfaces since they all route through `db.query`.

### Tier B — strong
3. **Lazy-gate dashboard tabs (app).** No `st.fragment` anywhere today, so Streamlit
   computes every tab's engines on each render even though the coach views one.
   Gate so only the open tab computes (per-tab `st.fragment`, or a session_state
   guard). Cuts cold-render CPU roughly by tab-count.
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
