# Lineup Projection + Signature-Stat Optimizer — Design (B + C)

**Date:** 2026-07-06
**Branch:** feat/coach-tiers
**Status:** approved design → implementation plan (stacks on the career-player-projection base layer)
**Consumes:** `helpers/projection.py` (spec: 2026-07-06-career-player-projection-design.md)

## Purpose

Two coupled tools for a team that has real rotation history:

- **B — depth-chart / minutes projection.** Given a minutes allocation across the
  roster in a 32-minute game, project the team's four factors + Net vs the average
  tracked team.
- **C — signature-stat lineup optimizer.** Search minute allocations to *maximize* how
  many of **this team's own win/loss signature stats** it projects to hit — the ~4
  stats `insights_team.winloss_alignment` mines as most separating THIS team's wins from
  losses (different stats for every team), each with a goal threshold. Subject to real
  coaching constraints (foul trouble, star stagger, min/max minutes). The crown jewel.

**"4 stats" = the team's own signature stats, NOT Dean Oliver four factors.** They come
from the Insights win/loss miner (`insights_team.winloss_alignment`), which ranks 12
candidate team stats (PPP, eFG, 3P%, 3PAr, TOVr, FTr, ORBpct, AST%, oPPP, oeFG, forced,
pace) by effect size `d = (win-mean − loss-mean)/SD` and returns each team's top ~4 plus
a goal threshold (midpoint of win/loss means) and direction per stat.

C wraps B: the optimizer just searches over what B scores. One module.

## Data reality (drives scope)

Confirmed from the DB: one deep team (~17+ tracked games locally, 25+ live) and a long
tail of opponents at 1–3 tracked games. `game_event_lineup` (on-court fives), rotation
stints (`gameflow.rotation`), and `lineups.custom_unit` all exist. So the raw material
for real 5-man units and minute distributions is present **for the deep team**. A team
with 1–3 games has no rotation signal — a depth chart there would be noise.

**Team gate:** B/C only run for a team with `≥ MIN_TEAM_GAMES` tracked games
(default 8). Below that: "not enough rotation history to project a depth chart."
Correct behavior — this is a tool for *your own* tracked team, not for scouting a
one-game opponent.

**Signature-objective gate:** the `signature` objective additionally needs the team to
have both wins AND losses tracked (`winloss_alignment` requires ≥2 of each with a stat
clearing `min_d=0.8`). A team that qualifies for the depth chart but lacks the win/loss
split falls back to the `net` objective — the depth chart still works; only the target
degrades gracefully.

## Non-goals (YAGNI)

- **D (year-to-year team projection) is NOT built.** Only one season exists; a
  returning-production record projection with zero prior seasons is dishonest. This
  spec instead drops the *plumbing* D needs (roster assembly from projected players →
  `predictor`/`simulation`) as a thin, documented function that produces a
  *current-roster* projection now and becomes year-over-year for free when season 2 +
  departures exist. No fake next-year record.
- No usage/class modeling beyond what the base layer already defers.
- No new page — surfaces on the **Team Dashboard** as a new tab.
- Optimizer is a directional hill-climb, not a guaranteed global optimum (see below).

## Architecture

New pure-data module `helpers/lineup_projection.py` (db + stats + no streamlit), same
contract as `lineups.py`. Orchestrates existing pieces:

| Concern | Reused from |
|---|---|
| Projected intrinsic player rates (SC%/SMOE/def/eFG/TOV/OREB/FTR) | `projection.project_roster` |
| **The team's own signature win/loss stats + goal thresholds** | `insights_team.winloss_alignment` |
| **Team per-game stat-line contract (12 keys) that B projects** | `insights_team.team_stat_line` / `_WL_SPEC` |
| Observed 5-man unit Net (opp-adjusted, credibility-shrunk) | `lineups.unit_ratings`, `lineups.custom_unit` |
| Rotation stints → observed minutes distribution | `gameflow.rotation`, `rotation_plan._top_by_minutes` |
| Foul-proneness / foul limits | `rotation_plan.foul_prone` |
| Star-stagger coverage constraint | `rotation_plan.star_coverage` |
| Average-tracked-team baseline (E) | `projection.tracked_baseline` |
| Monte Carlo the projected team vs a schedule/opponent | `simulation`, `predictor` |

### B — project a lineup / minutes allocation

`project_minutes(team_id, minutes, ...)` where `minutes = {pid: minutes}` summing to
5×32 = 160 player-minutes.

1. **Project the team stat line.** Produce the full `team_stat_line` contract (the 12
   `_WL_SPEC` keys: PPP/eFG/3P%/3PAr/TOVr/FTr/ORBpct/AST%/oPPP/oeFG/forced/pace) for the
   candidate allocation — the SAME keys the win/loss miner ranks, so B's output is
   directly scoreable against the team's signature goals. Each key is the
   **minute-weighted** mix of the roster's projected intrinsic rates
   (`projection.project_roster`): offensive keys from the players' offensive rates,
   defensive keys (oPPP/oeFG/forced) from their projected RimDef/PerimDef/forced-TO,
   pace held at the team's observed pace (a stable style property). Rates travel;
   minutes are the environment weight the base layer left out.
2. **Fold in observed chemistry.** Where a 5-man unit in the allocation has enough
   observed possessions, blend `custom_unit`/`unit_ratings` Net in by credibility weight
   so real on-court results aren't discarded for a pure sum-of-parts.
3. **Net + baseline.** Derive projected ORtg/DRtg (PPP·100 / oPPP·100) → Net, and
   express Net and every stat as a delta vs the **average tracked team**.
4. Return `{minutes, line:{<12 keys>}, ortg, drtg, net, net_vs_baseline, flags}`.
   Every output carries the thin/directional flag discipline of `rotation_plan`.

### C — optimize the allocation

`optimize_minutes(team_id, ..., objective="signature" | "net")`:

- **Search space.** Rotation of up to `MAX_ROTATION` players (default 8–9) drawn from
  players with tracked floor time; minutes in discrete 2-minute blocks (160 player-min
  = 80 blocks to place). Roster ~10–12 → tractable.
- **Objective (default `signature`).** Call `insights_team.winloss_alignment(team_id)`
  to get this team's signature stats + per-stat `goals` (`target`, `win_high`). Score a
  projected stat line by **effect-size-weighted goal attainment**:
  `Σ over goals of |d| · reward(projected_value, target, win_high)`, where `reward`
  credits being on the winning side of the threshold and scales with the *margin* past
  it (so the optimizer pushes the stats that most decide THIS team's games, by how much
  they decide them). This directly maximizes the miner's "hit all N goals → we go X-Y"
  record.
- **Fallback objective `net`.** When `winloss_alignment` returns `available=False`
  (a team without enough wins AND losses, or no stat clears `min_d`), the objective
  falls back to projected **Net vs the average tracked team**. Honest degradation — no
  signature stats invented for a team that hasn't shown them. The UI states which
  objective was used.
- **Method.** Greedy seed (minutes ∝ projected player value) → **hill-climb** on
  2-minute swaps between players, keeping any swap that raises the objective, until no
  swap improves. Cheap, directional, deterministic. Not a global optimum — flagged as
  "directional."
- **Constraints (real coaching, not toy):**
  - min/max minutes per player (`MIN_PP`, `MAX_PP`);
  - foul cap — down-weight/cap minutes for `rotation_plan.foul_prone` players;
  - **star stagger** — penalize allocations that leave zero of the top-N on the floor
    (ties directly into `star_coverage`'s bleed number);
  - optional role coverage (don't field five of one archetype).
- **Output.** Recommended minutes, the projected signature-stat line vs each goal
  (hit/miss + margin), Net vs baseline, and a **diff vs the team's *observed* minutes** —
  "shift 6 min from X to Y → now hits 3/4 signature goals (+ORBpct past target), +N/100."
  That diff is the sellable "extra wins" prescription, framed in the exact stats the
  team's own games say decide wins.

### D-plumbing (built, not user-facing)

`project_team_current(team_id, ...)` assembles the projected roster (minute-weighted
projected rates) into a single team rating and runs it through `predictor`/`simulation`
vs an opponent or schedule → projected margin / win-odds / wins distribution, **for the
current roster**. This is honest today (it's a current-season projection, not a
next-year claim) and becomes the year-to-year engine unchanged once `identity` can see
a second season and departures. No next-season record is displayed until then.

## Surface

New **"Projection"** tab on the Team Dashboard (`pages/6_Team_Dashboard.py` /
`helpers/dashboard/`), paid-gated. Shows: the optimizer's recommended minutes vs
observed (diff highlighted), the projected line against **the team's own signature-stat
goals** (from `winloss_alignment`) with hit/miss + margin, Net vs average-tracked
baseline, the star-stagger note, and the current-roster projection. Team-gated behind
`MIN_TEAM_GAMES` with an honest "need more tracked games" empty state; states which
objective (`signature`/`net`) was used.

## Error / edge handling

- Team below `MIN_TEAM_GAMES` → tool returns a `gated` payload with the reason; UI shows
  the empty state.
- Player with no projection (unrated) → uses the base layer's prior + `thin` flag; the
  optimizer can still place them but the projection is flagged.
- Degenerate minutes (sum ≠ 160) → normalized, with a warning in the payload.
- No opponent for the D-plumbing call → project vs the average tracked team.

## Testing (`tracker/test_lineup_projection.py`)

1. `project_minutes` line is minute-weighted (double a player's minutes → team stat
   moves toward his projected rate, monotone), and returns all 12 `_WL_SPEC` keys.
2. Baseline delta sign correct vs a known tracked-average.
3. Observed-unit Net folds in by credibility (thin unit ≈ ignored, deep unit pulls).
4. Optimizer never violates min/max/foul/stagger constraints.
5. Optimizer objective is non-decreasing across hill-climb iterations; terminates.
6. `signature` objective scores against `winloss_alignment` goals (a line that hits more
   goals scores higher; effect-size `|d|` weighting respected).
7. Objective falls back to `net` when `winloss_alignment.available` is False; UI flag set.
8. Team below `MIN_TEAM_GAMES` returns `gated`, no crash.
9. `project_team_current` returns a valid predictor payload for the deep team.

## Build order

1. `projection.tracked_baseline` (E) — shared helper (also used by base layer).
2. `helpers/lineup_projection.py` — `project_minutes` (B), then `optimize_minutes` (C),
   then `project_team_current` (D-plumbing). TDD: `tracker/test_lineup_projection.py`
   first.
3. Team Dashboard "Projection" tab, paid-gated, team-gated.

Sequence overall: **A (base layer) → E (baseline, shared) → B → C → D-plumbing.**
True year-to-year projection (D) is a season-2 spec that reuses all of the above.
