# Spec 2/3 + founder batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the TO-kind capture fix, the tracker/UI upgrades (possession WP,
live split, explainability, play frames), and the 2026-07-18 founder batch
(landscape noise filters, rebounding module, living recal, district standings,
retrack flow, FAQ) plus the season-default footgun fix.

**Architecture:** Pure engines in `helpers/` (Streamlit-free, tested via
`tracker/test_*.py`), thin page wiring in `pages/`, PWA changes in
`tracker/static/` with a sw.js cache bump. Model-constant adoption moves to an
`app_settings`-backed override layer so the living-recal loop adopts config,
not code.

**Tech Stack:** Python 3.12 / SQLite / Streamlit / FastAPI / vanilla-JS PWA /
plotly.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-18-spec23-founder-batch-design.md` —
  read the matching section before each task.
- Tests run ONE MODULE PER PROCESS with the real Python312 interpreter
  (`C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe -m pytest tracker/test_X.py`)
  — shell `python` sees a shadow AppData copy.
- DB-stays-small: no blobs, compact JSON, caps on saved items.
- GEI/summarize must keep reading the makes-only scoring curve (award-history
  stability) — the possession curve is display-only.
- Gates stay mandatory for any model-constant change; every living-recal run
  is logged whether it adopts or holds.
- One commit per task; deploy at the end per memory (push → ssh pull →
  restart app5-web + app5-tracker; PWA cache bump ships with Spec 3).

---

### Task 1: Spec 3 — TO-kind capture fix + quick-mode chips (PWA)

**Files:**
- Modify: `tracker/static/app.js:151` (SERVER_FIELDS), `:1602-1621` (quick-mode
  tov flow — replace buried selRow with a chip row shown in quick mode)
- Modify: `tracker/static/sw.js` (cache version bump)
- Test: `tracker/test_tov_capture.py` (new)

**Interfaces:**
- Produces: batch POST events carry `turnover_type`; quick mode shows a
  'TO kind' chip row (labelFn over TOV_TYPES) without `+ details`.

- [ ] Test: API-level regression — POST a flow-shaped batch with
  `turnover_type='pass'`, read back `/events`, assert the kind persisted; plus
  a static check that every key `logTov` writes appears in SERVER_FIELDS
  (regex over app.js source).
- [ ] Fix: add `'turnover_type'` to SERVER_FIELDS; render the TO-kind chip row
  in the quick-mode branch (labelFn `t => t[1]`, values `t[0]`, allowNone);
  keep detailed-mode selRow; bump sw.js CACHE version.
- [ ] Run test module; commit `fix(tracker): flow-logged turnovers keep their kind`.

### Task 2: Quick hit — season default fallback (stats/coverage)

**Files:**
- Modify: `helpers/seasons.py` (new `tracked_default_game_ids()` /
  clause helper), `helpers/stats.py:54-67,1186-1195`, `helpers/coverage.py:43-48`
- Test: `tracker/test_season_default.py` (new)

**Interfaces:**
- Produces: `seasons.tracked_default_clause() -> (sql_clause, params)` used by
  `stats._game_filter(None)` / `games_played` / `coverage._team_tracked_game_ids`;
  semantics: active season's tracked games, else most recent archived season
  with tracked games.

- [ ] Test: seed throwaway DB — tracked games only under '2025-2026', active
  empty → no-arg fetch_events returns those events; with active-season tracked
  games present → only those.
- [ ] Implement helper + rewire the three call sites; commit
  `fix(stats): post-rollover empty-active fallback for default tracked scope`.

### Task 3: Spec 2.1 — possession WP curve helper + surfaces

**Files:**
- Modify: `helpers/wpa.py` (new `possession_timeline(events, t1, t2, end=None,
  pregame_edge=0.0, sd_full=WP.SD_FULL)`), `pages/2_Game_Tracker.py:559-615`,
  `pages/6_Team_Dashboard.py` (adv_flow block), `pages/0_Analytics_Hub.py`
  "Game of the season" ribbon IF its data pack exposes raw events cheaply
  (else keep scoring curve there and say so in the commit)
- Test: `tracker/test_possession_timeline.py` (new)

**Interfaces:**
- Produces: `possession_timeline(...) -> [(elapsed, margin_home, wp_home)]`
  stepping on every shot/turnover/made-FT. `game_wpa`/`wp_curve` untouched.

- [ ] Test: synthetic event list — curve has a step at a miss and a turnover
  (times present), margin only moves on scores, wp in (0,1), monotone elapsed.
- [ ] Implement helper; swap tracker page inline walk; add WP ribbon to
  Score-Flow Explorer (paid-gated); commit
  `feat(wp): possession-model WP curve on tracker + game flow`.

### Task 4: Spec 2.2 — tracker/live split + live roster & insights picker

**Files:**
- Modify: `pages/2_Game_Tracker.py` (top-level `st.segmented_control`
  "Live" / "Log & fix"; Live gains roster panel + insights multiselect)
- Test: AppTest smoke (page renders in both views, no exceptions)

**Interfaces:**
- Consumes: existing panels; latest lineup snapshot via `game_event_lineup`.
- Produces: Live view = watch-only; `st.session_state['gt_view']`,
  `['gt_live_panels']`.

- [ ] Implement split: gate the "Logging & corrections"+Notes+QuickAdd half on
  the "Log & fix" view; Live view keeps scoreboard/WP/box/PBP and adds:
  insights multiselect (Scout cues, Win formula, WP strip, Shot chart, Box,
  PBP; defaults = today's set) and a Rosters panel (both teams full roster:
  #, name, on-court dot from latest snapshot, PF with bonus highlight, PTS).
- [ ] AppTest smoke both views; commit
  `feat(tracker-page): live/log split, insights picker, live rosters`.

### Task 5: Spec 2.3 — rating explainability + confidence tier

**Files:**
- Modify: `helpers/player_ratings.py` (capture per-player explain payload
  during the normal run; accessor `rating_explain(pid, gender, ...)`),
  `helpers/shrinkage.py` (reuse `rating_confidence`) — no formula changes,
  `pages/7_Players.py` + `helpers/dashboard/player_card.py` (?), the popover/
  expander + tier chip
- Test: `tracker/test_rating_explain.py` (new)

**Interfaces:**
- Produces: `player_ratings.rating_explain(...)` → {leaves: [{name, value, z,
  weight, contribution}], pillars: {...}, shrink: {evidence_games, k, anchor,
  raw, final}, samples: {gp, poss, coverage}}; `confidence_tier(gp, coverage_pct)`
  → (tier_idx 0-3, label, next_action).

- [ ] Test: explain payload exists for a rated player, contributions sum ≈
  pillar z (pre-shrink), tier boundaries hit all 4 tiers.
- [ ] Implement engine capture + `confidence_tier`; wire Players page main
  table (tier chip column) + player card OVERALL `?` expander; commit
  `feat(ratings): explainability payload + depth-of-track confidence tiers`.

### Task 6: Spec 2.4 — saved-play frame sequences

**Files:**
- Modify: `helpers/playbook.py` (seq_name/seq_idx columns + save_frame/list
  grouping; migration via the repo's schema-ensure pattern),
  `pages/10_Whiteboard.py` + `assets/whiteboard/index.html` (Save-frame button,
  slideshow playback)
- Test: `tracker/test_playbook.py` (extend) or new `test_play_frames.py`

**Interfaces:**
- Produces: `save_play(..., seq_name=None, seq_idx=None)`;
  `list_plays` returns seq fields; `list_sequences(coach)` groups ordered
  frames; cap unchanged (frames count).

- [ ] Test: save 3 frames, list_sequences orders them, cap counts each frame,
  delete one frame renumbers or leaves gap (pick: leave gap, order by idx).
- [ ] Implement + UI (frame picker + prev/next slideshow rendering existing
  component load path); commit `feat(playbook): frame sequences with slideshow`.

### Task 7: Item 8 — district standings intra-district

**Files:**
- Modify: `pages/5_Rankings.py:709-731`
- Test: AppTest smoke (Rankings Overview renders)

- [ ] Compute intra-district W-L per team (games where both teams share the
  non-empty district OR game_type='District'); columns: District W-L, GB (on
  district record), overall W-L; "—" + sort-last for no district games;
  caption. Commit `feat(rankings): district standings use intra-district games`.

### Task 8: Item 5 — landscape noise filters

**Files:**
- Modify: `pages/5_Rankings.py` (Runs / Play types / Defense / Player edge
  sub-tabs), engine touch-points where rates come raw
  (`helpers/runs.py`, `helpers/playtypes.py`, `helpers/defenses.py`,
  `helpers/player_edge.py` — shrink at the page boundary, engines untouched)
- Test: `tracker/test_landscape_shrink.py` (new, page-boundary helper)

**Interfaces:**
- Produces: small page-local `_shrunk(value, n, pool)` using
  `shrinkage.stabilize_value` + `eb_prior`; captions updated; foul-based reads
  (if any surface here) use ns counts via `late_game`.

- [ ] Audit the four tracked sub-tabs, apply shrink to per-team rates with
  visible n; commit `feat(rankings): EB shrink on thin landscape rates`.

### Task 9: Item 6 — rebounding enrichment

**Files:**
- Create: `helpers/rebounding.py`
- Modify: `pages/7_Players.py` (rebounding section), `pages/6_Team_Dashboard.py`
  (panel under Charts rebounding area)
- Test: `tracker/test_rebounding.py` (new)

**Interfaces:**
- Produces: `player_rebounding(gender=None, game_ids=None)` → per-pid dict:
  {def_secure_onball_pct, dreb_onball_share, pnr_reb (by playtype key),
  own_miss_recovery_pct, long3_reb_share, samples...}; team rollup
  `team_rebounding(team_id, ...)` with 3PA-vs-2PA OREB%/zone profile.

- [ ] Test on synthetic events (guarded_by + rebound_by + play_type + shot_type
  fixtures) for each rate's numerator/denominator.
- [ ] Implement engine (shrinkage on thin rates, coverage caveat surfaced);
  wire pages; commit `feat(rebounding): enrichment reads from existing tags`.

### Task 10: Item 7 — living recal loop

**Files:**
- Create: `helpers/model_constants.py`, `tools/living_recal.py`,
  `deploy/app5-living-recal.service`, `deploy/app5-living-recal.timer`
- Modify: `helpers/team_ratings.py` / `helpers/player_ratings.py` (resolve the
  six registered constants through overrides), `pages/12_Settings.py` (admin
  panel: last run + gate table + Run-now), `docs/RECAL_LOG.md` (seed)
- Test: `tracker/test_model_constants.py`, `tracker/test_living_recal.py`

**Interfaces:**
- Produces: `model_constants.get(name, default)` (app_settings JSON override,
  memoized w/ invalidation); `living_recal.run(force=False)` → {ran, new_games,
  gates: {...}, adopted: {...}|None, held_because: str|None}; state keys
  `living_recal:last_run`, `living_recal:history` (capped list),
  `model_constants` JSON.

- [ ] Tests: override round-trip + default fallback; run() below-threshold
  no-op; adoption only when every OOS gate beats-or-ties (fake gate fn
  injection); history append + cap.
- [ ] Implement; wire constants; Settings panel; systemd pair (mirrors
  ossaa-refresh pattern, weekly Mon 04:30); commit
  `feat(recal): living-recal loop — gated auto-adoption via config overrides`.

### Task 11: Item 9 — retrack notice + coach-visible duplicates

**Files:**
- Modify: `tracker/api.py` (new-game duplicate check → `duplicate_of` hint in
  response), `tracker/static/app.js` (notice on create), `pages/12_Settings.py`
  (duplicates panel visible read-only to involved coaches + change-request
  hook)
- Test: `tracker/test_retrack.py` (new; API duplicate hint)

- [ ] Test: create game A tracked for (date, t1, t2); POST new game same
  matchup → response carries duplicate hint; different date → none.
- [ ] Implement + client toast/confirm copy from spec; commit
  `feat(coop): retrack notice + coach-visible duplicate resolution`.

### Task 12: Item 10 — FAQ synced from founder Doc

**Files:**
- Create: `helpers/faq.py`, `pages/15_FAQ.py`
- Modify: `pages/12_Settings.py` (admin refresh button) — or FAQ page admin
  block; doc id constant from the founder URL.
- Test: `tracker/test_faq.py` (parse + cache logic; network mocked)

**Interfaces:**
- Produces: `faq.get_faq(force=False)` → {text, fetched_at, source_url,
  stale: bool}; fetch `export?format=txt`, cap 100KB, cache in app_settings
  (`faq:content`, `faq:fetched_at`, TTL 6h); `faq.parse_sections(text)` →
  [(question, answer)] heading heuristics.

- [ ] Tests: parse fixture text into Q/A sections; cache TTL + cap; fetch
  failure → cached copy + stale flag.
- [ ] Implement + page (search box, expander per Q, Doc link footer); commit
  `feat(faq): in-app FAQ synced from the founder's Google Doc`.

### Task 13: Verify + deploy

- [ ] Run every new/touched test module one-per-process; AppTest smokes for
  pages 2, 5, 6, 7, 10, 12, 15.
- [ ] `snapshot_report.py` sanity on local DB.
- [ ] Push; ssh pull; pip only if requirements changed (no); restart
  `app5-web` + `app5-tracker`; verify live site headers + PWA cache version.
- [ ] Update memory (tier status, new patterns worth keeping).
