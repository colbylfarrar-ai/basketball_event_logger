# Per-Game Player Rating (0-10) — Design

**Date:** 2026-07-11
**Branch:** feat/coach-tiers
**Status:** approved (founder), building

## Goal

Soccer-style single-number **per-game player grade, 0-10**, shown alongside every
game line. Base 6.0 = an average game. 7.5 good, 8.5 great, 9+ rare, <6 poor.
The marquee, glanceable per-game number; **Game Score stays** as the raw analyst
stat next to it.

## Decisions (locked)

- **Do NOT replace Game Score.** GS is embedded in OVERALL + 6 surfaces; keep it.
- **Do NOT fold into OVERALL.** Would double-count (built from the same inputs) and
  is the wrong altitude (per-game vs season). Separate layer.
- **Alongside**, as the headline per-game grade. GS is the nerd stat beside it.
- **Anchoring = hybrid C**: absolute event-delta engine + a role-expectation layer.
- **Tracked games only** (needs the event stream). Boxed/manual games → blank, no
  fake proxy (matches EVENT_DERIVED_STATS honesty).
- Gating: individual + event-derived → `has_paid_plan` for own team, same as
  box_score advanced table.

## The 6 fixed roles

A **new, stable** taxonomy for the expectation layer only — NOT the k-means
`cluster_players` archetype (that has variable k and shifting membership → not
comparable over time). Assigned per-player by a pure rule on the player's own
season style axes (reuse the `_AXES` concept from archetypes.py), no clustering.

| Role | Collapses | Graded hard on | Credited (not punished) |
|------|-----------|----------------|-------------------------|
| **Two-Way Star** | reserved: OFFENSE & DEFENSE composites both strong | both ends | relied on everywhere; hardest to grade well |
| **Primary Scorer** | Scorer, Offensive Engine, Flamethrower | scoring efficiency, shot quality, low TOV | volume expected (a quiet game drags) |
| **Shooter/Wing** | Sharpshooter | 3P efficiency, spacing, open-shot conversion | movement, catch-and-shoot |
| **Playmaker** | Floor General | AST, low TOV, entry passes | creation/passing value |
| **Interior/Big** | Interior Anchor, Rebounder | rim FG%, rebounding, rim protection | screens, boxouts |
| **Glue/Defender** | Glue Guy, Role Player, Defensive Specialist, Defensive Anchor | defense, low mistakes, hustle | **low usage NOT punished** |

`role_for(season_row)`: Two-Way Star first (both quality composites strong), else
top style axis + usage → one of the other five. Pure, stable, deterministic.

## The math — `helpers/game_rating.py`

New pure data-layer module (imports `database.db` + `helpers.stats` only, no
streamlit), mirroring possession_value.py. All functions accept `events=` /
injected rates so they're DB-free unit-testable.

### 1. Event → component deltas (points-added units)

Walk a player's events in one game. Self-contained expected-points model built
once from the pool (league make-rate by `(shot_type, zone)`; expected points =
p·value), mirroring `expected_fg_pct_all` but local so the module is
self-contained and injectable.

Five components:

- **shooting**: `Σ(pts_fg − exp_pts)` over own FG attempts  +  `(FTM − 0.7·FTA)`
  (made contested shot = big +; missed open look = big −).
- **playmaking**: `Σ exp_pts(assisted shot)·0.5` (shared passer credit)
  `− TOV · PPP_LEAGUE` (turnover = lost possession ≈ 1.0 pt).
- **defense**: `def_smoe_points` (as `guarded_by_id`: expected makes allowed −
  actual, ×avg points = points prevented) `+ STL·PPP_LEAGUE + BLK·exp_pts(blocked shot)`.
- **rebounding**: `OREB·0.5 + DREB·0.2` (extra-possession value; OREB worth more).
- **fouls**: `drawn·0.4 − committed·0.3`.

Constants are defensible defaults; the global z-normalization below rescales, so
relative structure + role weights carry the signal.

### 2. Role-weighted value

`V = Σ role_weight[role][cat] · components[cat]`

Role weights reshape what counts: Glue/Defender amplifies defense/rebounding and
zeroes any scoring-volume drag; Primary Scorer & Two-Way Star amplify shooting +
add a volume expectation; Playmaker amplifies playmaking; Interior amplifies
rebounding + rim. (Weight table in module constants.)

### 3. Pool calibration → 0-10

Compute `V` for **every tracked player-game this season** (one pass). Global
`POOL_MEAN`, `POOL_SD`. Per-role mean → `role_offset[role] = −role_mean_z·0.5`
(corrects half of a role's systematic deficit so glue guys aren't floored while
stars still pull up — Form reflects real quality, matching soccer).

```
z      = (V − POOL_MEAN) / POOL_SD
rating = clamp(6.0 + z·1.3 + role_offset[role]·1.3, 0, 10)
```

Global z (not within-role) so better players average higher, like real soccer
ratings; role only reshapes contribution + a modest baseline correction.

### 4. Minutes handling

- Shrink toward 6.0 by minutes: `rating' = 6.0 + (rating−6.0)·MIN/(MIN+K_MIN)`,
  `K_MIN≈6`, so a hot 5-min cameo can't show 9.0.
- Hide below ~8 minutes.

### Public API

```python
calibrate(events_all, roles_map)              -> calib dict (pool mean/sd, role_offset)
player_game_value(pid, events, model, role)   -> (V, components)   # pure
role_for(season_row)                          -> role str          # pure
season_game_ratings(game_ids=None)            -> {game_id: {pid: {rating, role, V, components}}}
game_ratings(game_id, calib=None)             -> {pid: {...}}       # one game, cached at UI
```

UI caches `season_game_ratings` with a season signature key (like other engines).

## Where it shows

- **Box-score advanced table**: new `RTG` column next to `GS` (GS stays).
- **Player-card**: game-log table column + game-log chart line + a **Form** strip
  (avg of last-5 game ratings) — Form is its own display, not in OVERALL.
- **Scout sheet / share cards**: per-game grade.
- **Glossary**: RTG entry + Form entry.

## Explicitly NOT

- Not folded into OVERALL. Not replacing Game Score. Not on boxed/manual games.

## Testing

- Unit tests (`tracker/test_game_rating.py`): synthetic events + injected model →
  exact component arithmetic; `role_for` boundary cases; calibration monotonicity;
  minutes shrink; clamp bounds. DB-free, mirrors test_possession_value.py.
- Live sanity: run `season_game_ratings()` on the 15 tracked games (Store Python →
  live DB), confirm ratings land in-range, 6.0-centered, stars > role players on
  season Form, no crashes.

## Deploy

Commit on feat/coach-tiers, bump PWA sw cache if UI shell changes, deploy per
hosting workflow — **only if tests green + live numbers sane**. Else stop + report.
