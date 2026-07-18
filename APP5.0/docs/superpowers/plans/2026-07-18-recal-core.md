# Recal Core Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix DWPA sign bias, scope EP baselines, add intentional-foul context, walk-forward validation (T6), aggressive backtest-gated weight recal with negative leaves, archetype shrink anchors, officials WP profile — all on the fresh prod snapshot.

**Architecture:** Pure-data-layer changes in `helpers/` (wpa, late_game [new], fouls, ref_tendencies, officials, player_ratings, team_ratings) plus harness growth in `tools/backtest.py`. Every constant change ships only if it beats/ties incumbent on T1–T4 + new T6. Spec: `docs/superpowers/specs/2026-07-18-recal-core-design.md`.

**Tech Stack:** Python 3.12, SQLite, stdlib + numpy/scipy (already present), pytest (existing `tracker/test_*.py` pattern).

## Global Constraints

- Season label is `'2025-2026'` (post-rollover; `'Current'` holds nothing) — every query scopes season explicitly (backtest.py:29-32 pattern).
- DB = living archive: no blobs, compact data only.
- SD=10 re-standardization contract on player ratings holds.
- HoopWAR stays display-only.
- Walk-forward target is named **T6** (T5 = existing WP calibration).
- Local shell `python` sees a Store-virtualized shadow of `%LOCALAPPDATA%\APP5` — run all DB-reading tools with the real interpreter `C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe` or explicit `APP5_DATA_DIR`.
- Prod: `app5@107.170.27.154`, DB `/var/lib/app5/analytics.db`.
- Commits are frequent, conventional-commit style, normal English.

---

### Task 1: Prod snapshot pull + verification + TO diagnostic

**Files:**
- Create: scratch script `tools/snapshot_report.py` (kept — reusable data-facts reporter)
- No engine changes.

**Interfaces:**
- Produces: local prod snapshot as the working DB in `%LOCALAPPDATA%\APP5\analytics.db` (timestamped backup of prior file alongside), plus a data-facts block for the final report.

- [ ] **Step 1:** Timestamped backup of local DB: copy `%LOCALAPPDATA%\APP5\analytics.db` → `analytics.pre-recal-2026-07-18.db` in same dir.
- [ ] **Step 2:** `scp app5@107.170.27.154:/var/lib/app5/analytics.db <local path>` (VPS sqlite in WAL mode — first run `ssh app5@… "sqlite3 /var/lib/app5/analytics.db 'PRAGMA wal_checkpoint(TRUNCATE);'"` to fold WAL, or use the Settings backup endpoint's consistent-snapshot approach: `sqlite3 … '.backup /tmp/app5-snap.db'` then scp that).
- [ ] **Step 3:** Write `tools/snapshot_report.py` printing: tracked games by gender/season, finished-game counts, event counts, tag coverage % (turnover_type, guarded_by, rebound_by, stolen_by, play_type, defense), lineup-snapshot coverage (% events with 10 rows in game_event_lineup), boys games list.
- [ ] **Step 4:** Run it; confirm 4 boys tracked games present; record numbers.
- [ ] **Step 5:** TO diagnostic: untyped turnovers grouped by game × stolen_by presence × tracked_by. Record findings (Spec 3 input).
- [ ] **Step 6:** Commit `tools/snapshot_report.py`.

### Task 2: EP baseline scoping

**Files:**
- Modify: `helpers/wpa.py` (`league_ep`, `season_wpa`)
- Test: `tracker/test_wpa_recal.py` (new)

**Interfaces:**
- Produces: `league_ep(game_ids=None, events=None)` unchanged signature; `season_wpa` now computes `ep = league_ep(game_ids=game_ids)` where `game_ids` is its already-scoped tracked-game list (gender+season respected).

- [ ] **Step 1:** Failing test: two fake-event pools with different PPP; assert `league_ep(events=pool)` differs and that `season_wpa`'s ep for gender F excludes M games (monkeypatch-light: call `league_ep(game_ids=[...])` with scoped ids on the snapshot DB and assert it ≠ unscoped when boys games present).
- [ ] **Step 2:** Implement: in `season_wpa`, move `game_ids = [row["id"] for row in tg]` above ep computation; `ep = league_ep(game_ids=game_ids) if mode == "possession" else None`.
- [ ] **Step 3:** Tests pass; commit.

### Task 3: DWPA team-split orphaned credit

**Files:**
- Modify: `helpers/wpa.py` (possession mode of `game_wpa`, `season_wpa` prefetch)
- Test: `tracker/test_wpa_recal.py`

**Interfaces:**
- Consumes: `game_event_lineup` rows (event_id, player_id, team_id).
- Produces: `game_wpa(..., floor=None)` new optional param: `{event_id: [(pid, tid), ...]}`; `season_wpa` prefetches it in one query. New module constant `ONBALL_SHARE = 0.6`.

Design (from spec §3):
- Made basket: on-ball defender gets `def_wpa * ONBALL_SHARE`; remaining `1-ONBALL_SHARE` split equally among the other on-floor defenders (defense side = players whose team_id != off_team). No guarded_by → whole amount split among on-floor defenders. No floor data → legacy behavior (all to guarded_by if present, else dropped).
- Unforced turnover (no stolen_by): whole def_wpa split among on-floor defenders (was dropped). Steal: unchanged (stealer takes all).
- Missed shot, no defensive rebound credited: def_wpa split among on-floor defenders (was dropped). With def rebound: unchanged (blocker/rebounder split).

```python
def _def_split(contribs, def_wpa, li, on_floor_def, main_pid=None, main_share=1.0):
    """Split defensive credit: main_pid gets main_share, the rest of the on-floor
    defense splits the remainder equally. No floor data -> main_pid takes all
    (legacy); no main_pid and no floor -> credit is dropped (legacy)."""
    others = [p for p in on_floor_def if p != main_pid]
    if main_pid is not None:
        rest = (1.0 - main_share) if others else 0.0
        contribs.append((main_pid, def_wpa * (main_share + (0.0 if others else 1.0 - main_share)), li, "def"))
        for p in others:
            contribs.append((p, def_wpa * rest / len(others), li, "def"))
    elif others:
        for p in others:
            contribs.append((p, def_wpa / len(others), li, "def"))
```

- [ ] **Step 1:** Failing property test on snapshot DB: `season_wpa(mode="possession")` league sum of `def_wpa` ≈ 0 (|sum| < 0.05 × Σ|def_wpa|, tolerance for no-floor fallback possessions), plus a hand-built 2-event unit test asserting the split fractions.
- [ ] **Step 2:** Implement `_def_split` + wire into the three defense branches of possession mode; add `floor` param + one-query prefetch in `season_wpa` (join game_event_lineup over the game_ids).
- [ ] **Step 3:** Property test passes; run `player_edge.edge_boards` smoke — def WPA board renders, roughly balanced signs.
- [ ] **Step 4:** Commit.

### Task 4: Intentional-foul window detector (new module)

**Files:**
- Create: `helpers/late_game.py`
- Test: `tracker/test_late_game.py`

**Interfaces:**
- Produces: `strategic_foul_event_ids(events) -> set[int]` — foul-event ids in an intentional-foul window; `is_window(quarter, time, margin_for_fouling_team) -> bool`; constants `WINDOW_SECS = 120`, `MARGIN_MIN = 1`, `MARGIN_MAX = 10`. Also `damped_ft_event_ids(events) -> set[int]`: FT events attributable to a strategic foul (same team's FTs within the next few rows after a flagged foul).

Detection: walk each game's sorted events tracking score; a foul event in Q4/OT with `secs_left <= WINDOW_SECS` where the FOULER's team trails by `MARGIN_MIN..MARGIN_MAX` → flagged. Fouler team = fouler's (secondary_player_id) team via one players query.

- [ ] **Step 1:** Failing tests: synthetic event list — trailing-team foul at 1:30 Q4 down 6 → flagged; leading-team foul same clock → not; down 18 → not; Q3 → not; FTs right after flagged foul → in damped set.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Tests pass; commit.

### Task 5: Wire timing exclusions into engines

**Files:**
- Modify: `helpers/wpa.py` (scoring mode: damp flagged FT credit ×`STRATEGIC_FT_DAMP = 0.25`), `helpers/fouls.py` (`player_foul_ft` adds `strategic` count; PF unchanged raw), `helpers/ref_tendencies.py` + `helpers/officials.py` (exclude flagged calls from tendency/rate aggregates; keep raw totals), `helpers/player_ratings.py` (discipline leaf uses PF−strategic, Task 7).
- Test: extend `tracker/test_late_game.py` + garbage-time self-damp test in `tracker/test_wpa_recal.py`.

- [ ] **Step 1:** Failing tests: scoring-mode WPA of a flagged FT ≈ 0.25 × unflagged twin; `player_foul_ft` returns `strategic` per fouler; garbage-time verification (made basket up 25 with 60s left has |WPA| < 0.005).
- [ ] **Step 2:** Implement: wpa scoring loop looks up damped FT ids once per game; fouls counts strategic fouls per fouler; ref_tendencies/officials filter flagged foul ids from per-call aggregates.
- [ ] **Step 3:** Tests pass; existing suites green; commit.

### Task 6: T6 walk-forward harness

**Files:**
- Modify: `tools/backtest.py`
- Test: harness self-verifies (report numbers); smoke via `python -m tools.backtest --t6`.

**Interfaces:**
- Produces: `t6_walkforward(gender, cutoff="2026-02-01", reg=None, sos_weight=None)` → `{"t6a": {mae, baseline, n}, "t6b": {rho, n}}`; wired into `run_all` (both genders for t6a) and the CLI printout.

- t6a: `score_ratings` on games dated < cutoff; MAE of predicted vs actual margin over games ≥ cutoff (same `_margin_mae` machinery, chronological split instead of folds).
- t6b: player OVERALL trained on tracked games < cutoff vs held-out GS/G on tracked games ≥ cutoff (Spearman, focus team; thin — reported, weighted below t6a).

- [ ] **Step 1:** Implement `t6_walkforward` reusing `_margin_mae` / `_heldout_lines` / `_spearman`; add `--t6` flag + `run_all` inclusion.
- [ ] **Step 2:** Run on snapshot; sanity: t6a n in the hundreds+ per gender, MAE near T1b's.
- [ ] **Step 3:** Commit.

### Task 7: Negative leaves + sweep surface widening

**Files:**
- Modify: `helpers/player_ratings.py` (`_OVERALL_PARTS` gains `("TOV/Gz", …)` penalty and `("DISCz", …)` non-strategic foul-rate penalty as new pooled-z leaves; profile rows gain `TOV/G` (exists) and `nsPF/G` = (PF − strategic)/G), `tools/backtest.py` (REGISTRY gains `player_ratings._OVERALL_PARTS`, `wpa.ONBALL_SHARE`, `late_game.WINDOW_SECS`, `player_ratings.TEAM_PRIOR_LAMBDA`).
- Test: `tracker/test_ratings_recal.py` — leaf presence + lower_better direction (player with more TOs, same else → lower OVERALL z input).

- [ ] **Step 1:** Failing test for penalty direction.
- [ ] **Step 2:** Implement leaves (z computed pool-wide, negated — follow `PF/Gz` pattern in `_DEFENSE_PARTS` wiring) at conservative starting weights (0.4 each; sweep decides final).
- [ ] **Step 3:** Tests + existing suites pass; commit.

### Task 8: Archetype shrink anchors

**Files:**
- Modify: `helpers/player_ratings.py` (anchor path: blend team-prior anchor with archetype-mean anchor), consuming `helpers/archetypes.py` classification.
- Test: `tracker/test_ratings_recal.py`.

**Interfaces:**
- Produces: `_archetype_anchor(table, gender) -> {pid: anchor}` — mean stabilized OVERALL-input (GS/G z mapped to 0-100 band, clamped to TEAM_PRIOR_BOUNDS) of the player's archetype cluster, only for clusters with ≥ 4 members; blend `anchor = 0.5·team_anchor + 0.5·arch_anchor` when both exist, else whichever exists, else 50. New constant `ARCH_ANCHOR_BLEND = 0.5` (registry entry).

- [ ] **Step 1:** Failing test: player in a strong cluster with 1 GP anchors above 50; unclassified falls back to team anchor.
- [ ] **Step 2:** Implement (archetypes.assign on the same pool; guard: archetype engine failure → team anchor only).
- [ ] **Step 3:** Tests pass; commit.

### Task 9: Tracked-team ramp (evaluated, adopt only if it wins)

**Files:**
- Modify: `helpers/team_ratings.py` — new `hybrid_ratings(gender, season, k_tracked=HYBRID_K)`: score_ratings Rating blended per team toward tracked_ratings-implied points rating by `w = tgp/(tgp+k_tracked)`; `predict_spread` untouched unless gates won.
- Test: backtest T1a/T1b/T6a comparison score_ratings vs hybrid.

- [ ] **Step 1:** Implement `hybrid_ratings` (tracked NetRtg → points scale via field SD match) + a backtest variant hook.
- [ ] **Step 2:** Gate: hybrid beats score_ratings on T1a+T6a → switch `season_wpa`'s edge source + predict_spread default; else leave opt-in and record numbers.
- [ ] **Step 3:** Commit either way with the evidence in the message.

### Task 10: Officials WP profile

**Files:**
- Modify: `helpers/officials.py` — `official_overview` rows gain: `hi_li_calls`, `li_call_ratio` (high-LI call rate vs own baseline), `avg_call_li`, `foulout_impact` (Σ fouled-out player OVERALL × frac of game remaining, context only), all computed excluding strategic-foul windows.
- Test: `tracker/test_officials_wp.py` — synthetic game: official who calls in high-LI moments scores ratio > 1; strategic-window calls excluded.

- [ ] **Step 1:** Failing tests.
- [ ] **Step 2:** Implement: per foul event compute LI (reuse `wpa.li_at` math via `win_probability`), normalize per game like fouls.py `_ft_pressure`; aggregate per official.
- [ ] **Step 3:** Tests pass; Officials page renders new columns (small UI touch); commit.

### Task 11: Aggressive sweeps (backtest-gated adoption)

**Files:**
- Create: `tools/sweep_recal.py` (grid runner over `override()` + t6)
- Modify: constants in their home modules per winners, with dated comments.

Grids (wide on purpose): RATING_K_GAMES {1,2,3,5}, DEFAULT_INDEX_K {1.5,3,5,8}, DEFAULT_INDEX_POWER {1.0,1.5,2.0}, DEFAULT_REG {1.0,1.5,2.0,3.0}, DEFAULT_SOS_WEIGHT {0.4,0.8,1.2,1.6}, TEAM_PRIOR_LAMBDA {0.35,0.5,0.7}, ARCH_ANCHOR_BLEND {0.3,0.5,0.7}, ONBALL_SHARE {0.5,0.6,0.7}, OVERALL penalty-leaf weights {0.2,0.4,0.7}, impact pillar {0.9,1.2}, offense {1.1,1.3}. Sweep marginally (coordinate descent, not full cross) — record every config's T1a/T1b/T2/T4/T6.

- [ ] **Step 1:** Baseline run (incumbents) on snapshot → save JSON.
- [ ] **Step 2:** Sweep; adopt only winners (beat-or-tie rule across gates; T6a is king for team constants, T2/T4 for player constants).
- [ ] **Step 3:** Update constants in modules with evidence comments; full backtest re-run saved.
- [ ] **Step 4:** Commit.

### Task 12: Report + push

**Files:**
- Create: `docs/RECAL_2026-07-18.md` — data facts, TO diagnostic, DWPA before/after distribution, per-gate before/after table, adopted vs rejected constants, officials profile sample, next steps (Spec 2/3).
- Update spec status; regenerate `docs/WP_CALIBRATION_2025-2026.md` (`--wp-report`).

- [ ] **Step 1:** Write report; run full test suite + backtest final.
- [ ] **Step 2:** Commit, push, deploy per DEPLOY flow (code-only: ssh pull + restart app5-web).
