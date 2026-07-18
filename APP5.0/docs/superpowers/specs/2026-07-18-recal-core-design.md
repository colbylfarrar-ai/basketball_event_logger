# Recal Core — Full-Season Weight Recalibration, Round 2

**Date:** 2026-07-18
**Status:** Design approved in conversation; this document is the written spec.
**Scope:** Spec 1 of 3. Spec 2 (tracker/UI: possession-WP display, tracker/live split,
explainability hovers, saved-frame sequences) and Spec 3 (TO-type capture fix) follow
separately. Spec 3 is gated on the diagnostic in §9 of this document.

## Motivation

The first recalibration round (spec: `2026-07-11-full-season-recalibration-design.md`,
harness: `tools/backtest.py`) shipped conservative weights on ~29 tracked games. The
founder's review of the live numbers:

- Overall ratings read well; stats-over-impact flags are correct and wanted.
- **Defensive WPA is broken in sign**: essentially every player shows negative Def WPA.
- Weights should get **aggressive**: wider sweeps, negative (penalty) leaves, team
  weights, official weights, and game-timing context (late intentional fouling must not
  help anyone's rating — player, team, or official).
- The prod DB now holds more games, including 4 boys games — pull it before recal so
  every decision runs on the biggest real sample.

## Root causes already diagnosed

### DWPA all-negative (helpers/wpa.py, possession mode)

Per possession `def_wpa = -off_wpa`, so league-wide defensive credit should sum to ~0.
It doesn't, because assignment is asymmetric:

- Negative defensive credit (a made basket) lands on `guarded_by_id`, which is almost
  always tracked.
- Positive defensive credit leaks: an unforced turnover (no `stolen_by_id`) is dropped
  entirely; a forced miss with no recorded defensive rebound (team rebound, ball out of
  bounds, dead ball) is dropped.

Assigned negatives ≈ complete; assigned positives ≈ partial → the whole league drifts
negative. This is an accounting hole, not "defense weighted too heavy."

### EP baseline unscoped (helpers/wpa.py season_wpa)

`season_wpa` computes `ep = league_ep()` with no gender or season filter — the
expected-points baseline mixes all genders and all seasons. Tolerable while the data
was nearly all Adair girls; wrong the moment the 4 boys games land.

## Design

### 1. Data pull (first, everything downstream uses it)

- Back up the local working DB aside (timestamped copy).
- Pull the prod snapshot from the VPS (`app5@107.170.27.154:/var/lib/app5/analytics.db`)
  to the local working path.
- Verify: tracked-game count, the 4 boys games present with correct gender, per-game
  event integrity (no null-heavy games), season labels.
- Record the new data facts (counts by gender, tag coverage %) in the build log —
  `tools/backtest.py`'s header documents the old facts and its assumptions must be
  rechecked against the new snapshot.

### 2. EP baseline scoping

`league_ep()` gains gender + season scoping (accept `game_ids` computed from the same
scoped tracked-game query `season_wpa` already runs). `season_wpa` passes it. Boys and
girls get separate expected-points-per-possession baselines; archived seasons stop
polluting the current baseline.

### 3. DWPA fix — team-split orphaned credit (approved approach)

In possession mode:

- **Orphaned positive credit** (unforced turnover; forced miss without a credited
  defensive rebounder) is split equally among the on-floor defenders from the lineup
  snapshot (same on-court data the RAPM possession walk uses).
- **Made-basket negative credit** is also softened: the on-ball defender
  (`guarded_by_id`) takes a majority share (~60%, constant), the remainder split among
  the other on-floor defenders — team defense is a team outcome.
- Possessions with no lineup snapshot fall back to current behavior (all-or-nothing to
  the tagged player).
- **Property test**: league-wide sum of assigned Def WPA ≈ 0 (tolerance for
  no-lineup-fallback possessions). Boards re-render; expectation is roughly half the
  pool positive.

### 4. Game-timing / intentional-foul context

New shared detector (in `helpers/stats.py` or `helpers/situational.py` — single source,
every engine imports it): flag possessions in an **intentional-foul window** — trailing
team commits a foul inside the final ~2:00 of Q4/OT, margin within roughly 1–10, fouling
team behind (constants tunable, backtest-gated). Flagged possessions:

- **WPA**: free-throw credit from these fouls is damped — no clutch windfall to the
  shooter for being fouled on purpose.
- **Fouls/discipline**: the fouler's discipline metrics skip strategic fouls.
- **Ref tendencies / officials**: call-rate profiles exclude flagged calls so a
  late-game foul barrage doesn't skew an official's profile.
- **Team ratings**: untouched — final score is the final score.
- Garbage time needs no new mechanism: WP swings in a decided game are already ≈ 0, so
  WPA self-damps. Verify with a test, don't rebuild.

### 5. Aggressive weight recalibration

- **Negative leaves**: the OVERALL player rating gains explicit penalty leaves —
  turnover rate, non-strategic foul rate (uses §4's flag), and a bad-shot/efficiency
  penalty where the tracked data supports it cleanly. SD=10 re-standardization contract
  holds (penalty leaves shift ranks, the scale re-centers).
- **Wider sweeps**: "aggressive" means widening the sweep ranges the optimizer may
  explore, not hand-picking bigger constants. Push limits, let the gates catch
  overreach, adjust from what survives.
- **Gates**: every constant change must beat or tie the incumbent on `tools/backtest.py`
  T1–T4 **plus the new T5** (below), all run on the new bigger snapshot.
- Stats-over-impact flags rechecked via T2 after reweighting.

### 6. Walk-forward validation (new backtest target T5)

Chronological holdout: train every engine on games dated through January, predict
February–March, score. Two tiers:

- **T5a — team ratings**: OSSAA league-wide finished scores (thousands of games both
  genders) — train-window `score_ratings`, predict late-season margins, MAE vs actual.
- **T5b — tracked engines**: the tracked pool's late-season games as holdout for player
  ratings and WPA-derived metrics (thin sample; reported but weighted below T5a).

This is the primary guard that makes aggressive sweeps safe: a weight that only wins
in-sample dies here.

### 7. Archetype pooling (empirical-Bayes shrink target)

Thin-sample players currently shrink toward the league/pool mean. Where an archetype /
play-style / similarity engine already classifies a player, shrink toward the
**archetype mean** instead (league mean stays the fallback for unclassified players).
Standard empirical-Bayes; k constants re-swept under T4 (LOGO) with the new snapshot.
This is how ~5,000 possessions support possession-level expectations: coarse
type-level parameters, not per-player ones.

### 8. Officials — WP impact, strictly objective

Extend the officials engine with what-happened facts only; no correctness judgments:

- **Call leverage profile**: every foul call already carries `official_id` + clock.
  Record the WP context (LI) at each call and the WP swing of the resulting
  possession(s). An official's high-LI call rate vs their own full-game baseline is a
  pure counting stat — the "swallows the whistle late" signature, with no opinion
  attached. Rewarded in the official rating.
- **Consequence context**: when a call fouls a player out, log (player rating ×
  minutes remaining) as context. Displayed; weighted small if at all in the rating.
- §4's intentional-foul exclusions apply before any of these aggregates.

### 9. Turnover-type diagnostic (log only — fix is Spec 3)

Write path verified intact end-to-end (PWA flow → API model → insert). On the new
snapshot, run a diagnostic: untyped turnovers grouped by game, quarter, and
`stolen_by_id` presence.

- If untyped TOs cluster on steal-TOs / quick-mode sessions → confirms the quick-mode
  capture gap (TO-kind selector hidden behind "+ details" in quick mode,
  `tracker/static/app.js` flow).
- Findings recorded in the build log; the capture fix (surface TO-kind chips in quick
  mode and/or a default kind for steal TOs) ships as Spec 3.

### 10. Tracked-team-rating ramp

The tracked-signal weight in team ratings becomes a function of tracked games played
(more tracked games → more tracked signal, less OSSAA prior) instead of a fixed
constant. Functional form swept and gated by T1a/T1b/T5a.

## Build order

1. Data pull + verification (§1) and TO diagnostic (§9) — data facts first.
2. EP scoping (§2) — small, prerequisite.
3. DWPA team-split (§3) with property test.
4. Timing/intentional-foul detector (§4) + engine exclusions.
5. Backtest T5 walk-forward harness (§6).
6. Aggressive sweeps: negative leaves, wider ranges, archetype-k, team ramp
   (§5, §7, §10) — gated on T1–T5.
7. Officials WP extension (§8).
8. Build-log doc: before/after backtest report, new data facts, DWPA distribution
   before/after.

## Error handling & fallbacks

- No lineup snapshot on a possession → DWPA falls back to current single-player credit.
- Unclassified player → shrink target falls back to pool mean.
- Unrated matchup → pregame edge 0 (existing behavior).
- VPS unreachable → recal blocked; do not run on the stale local DB (backtest header
  facts would silently lie).

## Testing

- Property test: league Def WPA sums ≈ 0 in possession mode (post-§3).
- Unit tests: intentional-foul detector boundary cases (margin, clock, fouling side).
- Garbage-time self-damping verification test (§4).
- Existing suites (`tracker/test_*.py`) stay green.
- Backtest T1–T5 before/after report is the shipping gate for every constant.

## Out of scope (this spec)

- Tracker/live page split, possession-WP display on tracker/flow, explainability
  hovers, saved-frame slideshows (Spec 2).
- TO-type capture fix (Spec 3, gated on §9 findings).
- Any change to HoopWAR's display-only status or the SD=10 contract.
