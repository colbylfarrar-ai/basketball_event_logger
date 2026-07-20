# Tracked-engine calibration — design

**Date:** 2026-07-19
**Status:** measurement complete; implementation awaiting approval
**Harness:** `tools/tracked_calib.py`
**Snapshot:** prod `/var/lib/app5/analytics.db`, 13,363 games / 12,648 finished / 1,448 teams / 41 tracked

## The question

Two ratings engines exist. `score_ratings` is fit on 12,648 finished games and is
MAE-validated by `tools.backtest`. `tracked_ratings` is fit on the play-by-play
games a coach has actually logged — 41 of them. `hybrid_ratings` exists to blend
the second into the first.

Before that blend is switched on: **on the tracked games themselves, does the
tracked engine predict the actual margin better than the score engine already
does?**

The original framing was broader — whether playoff depth and championship
proximity should feed the rankings. That was dropped on the principle that a
signal which does not help identify the best team does not belong in the number
that claims to. Playoff depth is downstream of quality the SRS already ingests
via the same wins. This spec is what remained: the tracked engine is the one
place with genuinely new information, so it is the one worth measuring.

## Protocol

| Engine | Fit | Why |
|---|---|---|
| score | ONCE, full league | Holding out one game moves it by ~1/12,648. In-sample bias is nil; 41 refits buy nothing. |
| tracked | strictly LEAVE-ONE-OUT | Holding out one of 41 is a 2.5% change, and for a team whose only tracked game is the held-out one it removes the team entirely. Anything less scores the engine on data it was fit to. |

**Coverage is a first-class result.** A game the tracked engine cannot predict
out-of-sample is the finding, not a filtered-out row.

**Every blend gain is reported against a shrink-only control.** Blending toward a
heavily-shrunk tracked rating is arithmetically close to just shrinking the score
prediction toward zero. Without the control, `k * score_prediction` masquerades as
tracked information. This test is the reason the boys result was rejected.

## Results

### Graph shape — the binding constraint

```
GIRLS  35 games / 21 teams   busiest team in 24/35 (69%)   12 teams with exactly 1 game
BOYS    6 games /  5 teams   busiest team in  6/6 (100%)    2 teams with exactly 1 game
```

Both are **stars**. You cannot identify N team strengths from N-ish games that all
share an endpoint — the system is rank-deficient. No choice of constants fixes
this, and neither does more games *around the same hub*.

Coverage follows directly: **23/35** girls games and **4/6** boys games are
LOO-predictable at all. A third of the tracked sample is invisible to its own
engine.

### Accuracy — girls, 23 coverable games

| model | MAE | RMSE |
|---|---|---|
| baseline (pick 'em) | 25.70 | — |
| **score engine** | **7.26** | 9.27 |
| tracked engine (LOO) | 12.94 | 14.43 |
| best blend, `w=0.00` | 7.26 | — |
| control: shrink only, `k=1.00` | 7.26 | — |

The optimizer, given full hindsight over the same 23 games and one free
parameter, puts **zero** weight on the tracked engine. `k=1.00` says the score
engine's spreads need no rescaling either — OLS slope 0.96, r=0.95. It is already
calibrated.

### Is it the tuning? — 28-config sweep

`tracked_ratings` inherits `DEFAULT_REG=0.5` and `DEFAULT_SOS_WEIGHT=1.6`, both
tuned on the T6 walk-forward over the dense score graph. Plausible that the
tracked engine fails because it is misconfigured rather than because the data is
thin. Swept `reg ∈ {0.5…32}` × `sos_weight ∈ {0, 1.6}` × `class_step ∈ {0, 1.5}`:

**Optimal blend weight was 0.00 in every one of the 28 configs.** It is the data,
not the tuning.

Two by-products, both against the pre-sweep hypothesis:

- `reg=0.5` is *already optimal* for the tracked engine — MAE rises monotonically
  with `reg` (11.61 → 20.67). The "sparse graph needs more shrinkage" hypothesis
  is **wrong**, and the shared constant is not the problem it looked like.
- `sos_weight=1.6` **costs** the tracked engine ~1.1 MAE (11.61 at 0.0 vs 12.75 at
  1.6). SOS across 21 teams that mostly played the same hub is noise, and
  amplifying it hurts. Real, but moot while tracked weight is zero.

### Boys — rejected by the control

The boys grid looked spectacular: gains to +6.02 MAE at `w=0.86`, improving
monotonically as `reg → 32`. That monotonicity is the tell — at `reg=32` the
tracked ratings are shrunk nearly flat (mean `|pred|` 3.7 vs the score engine's
16.1), so "blend toward tracked" ≈ "shrink the score prediction". The score
engine is measurably over-scaled here (slope 0.62), so shrinking *should* help.

Control: plain `0.28 × score` scores **8.04** against the blend's **8.45** —
better, using no tracked data at all. With n=4 and one free parameter, this is
arithmetic, not evidence.

## Verdict

**Do not wire `hybrid_ratings` into any ranking surface.** It currently has zero
callers; that is the correct state and should be enforced rather than left to
chance.

The tracked engine's value is **diagnostic, not ordinal**: possessions, four
factors, WPA, lineups, per-game and per-player explanation. It answers *why* a
team is good. The score engine answers *who* is good, at 7.26 MAE, and nothing in
this sample improves on that.

## What would change the verdict

Re-run `python -m tools.tracked_calib` when the tracked sample changes. Switch the
blend on only when all three hold:

1. `hub_share` < 0.5 — no single team dominates the sample
2. LOO coverage ≥ 80% of tracked games
3. Verdict `MAYBE` — `w* ≥ 0.15` **and** the blend beats the shrink-only control
   by ≥ 0.25 MAE

Condition 1 is the real one and it is about *scheduling the tracking*, not
volume. 30 more games around Adair buys nothing; 30 games among **disjoint
pairs** buys a rankable graph. The boys set is the better shape in miniature —
home-and-home repeats against 4 opponents — and repeat matchups are what let a
model separate improvement from noise. That is the pattern to grow.

## Defects found (independent of the verdict)

Each is real and none is currently in production, because `hybrid_ratings` has no
callers.

1. **`hybrid_ratings` never re-ranks.** It mutates `Rating` but never calls
   `_power_scale` or `_assign_ranks` (`helpers/team_ratings.py:484-497`).
   Confirmed: `Rating` moved up to 6 points while `Rank` and `Power` stayed
   identical to `score_ratings` for all 704 teams. `blended_ratings` does this
   correctly at `:534-537`; hybrid is missing the block.
2. **`hybrid_ratings` mean-shifts but never rescales.** `shift = m_s - m_t` is a
   pure translation. Measured tracked slope is 1.29, so the blend systematically
   drags good teams down and bad teams up — a regression-to-the-mean machine, not
   an information gain. Adair −6.08, Locust Grove −5.64, Central (Tulsa) +6.28.
3. **living_recal overrides cannot reach `tracked_ratings`.** `reg` and
   `sos_weight` are **def-time** defaults (`:568-569`), frozen at import.
   `score_ratings` resolves them at call time specifically to fix this (`:373-377`),
   with a comment describing the exact bug tracked still has.
4. **Unit mismatch in tracked `Rating`.** `rating = adj_net + cadj + sbump`
   (`:645`) adds per-100 `NetRtg` to points-scale `ClassAdj` / `sos_bump`.
   `RatingPts` converts correctly; `Rating` does not — and `_assign_ranks` sorts
   on `Rating`. Class and SOS terms land ~1.5× weaker than intended in tracked
   ranks. `predict_spread` uses `RatingPts`, so this study is unaffected.

## Proposed implementation

Shipped already (additive, no engine change):

- `tools/tracked_calib.py` — the harness, with graph/coverage/accuracy/scale
  reporting, the constants sweep, and the shrink-only control. Re-runnable as the
  gate.

Awaiting approval (touches `helpers/team_ratings.py`):

- **Gate `hybrid_ratings` off behind the three conditions above**, returning the
  score ratings unchanged when they fail, so a future caller cannot switch on a
  blend the data does not support.
- Fix defect 1 — re-power and re-rank after blending, matching `blended_ratings`.
- Fix defect 2 — rescale, not just shift, using the measured slope.
- Fix defect 3 — resolve `reg` / `sos_weight` at call time, matching `score_ratings`.
- Fix defect 4 — make tracked `Rating` unit-coherent, or rank on `RatingPts`.
- Give `tracked_ratings` its own `sos_weight` default of 0.0 (evidence: +1.1 MAE
  at 1.6), separate from the score engine's 1.6.

Defects 2 and 6 are only meaningful if a blend is ever switched on; 1, 3 and 4 are
worth fixing regardless.

## Open item

The 2 boys games missing from the local DB (`#15344` Kansas 12/16, `#13947` Inola
12/18) exist on prod and were pulled to a scratchpad copy for this study. The
local `analytics.db` has **not** been touched. Syncing it is a separate decision —
prod is a superset for tracked games and carries richer `game_type` tags, but
overwriting a working DB is not something to do without the go-ahead.

---

# Addendum — 2026-07-20: the completed boys set, and the one-team gate

## The boys set is complete (8 games), and the verdict did not move

The 2 games listed under "Open item" landed, plus 2 more. The boys tracked set is
now the full home-and-home against 4 opponents — Inola, Jay, Kansas, Adair — and
the local `analytics.db` has been synced from prod (backup:
`analytics.pre-sync-20260720.db`; prod verified a strict superset first, no
local-only rows or field values in any of the 26 tables).

Coverage improved exactly as predicted, and it changed nothing:

| | 6 games (07-19) | 8 games (07-20) |
|---|---|---|
| LOO coverage | 4/6 | **8/8 (100%)** |
| hub_share | 1.00 | **1.00** |
| score engine MAE | — | 10.43 |
| tracked engine MAE (LOO) | — | 12.78 |
| best blend | w=? | w=0.22 → 10.14 |
| shrink-only control | explained the gain | **k=0.28 → 7.65** |
| verdict | NO | **NO** |

**Coverage was never the binding constraint.** Every game is now LOO-predictable
and the tracked engine is still beaten by a control that uses no tracked data at
all — by 2.49 MAE. The sweep makes the mechanism unmissable: `vs ctrl` is
negative in **all 28 configs**, and tracked MAE improves monotonically as `reg`
climbs (12.93 at reg=0.5 → 8.60 at reg=32) toward the pick-'em baseline of 8.62.
The tracked engine looks best precisely where regularization has erased its
signal. That is not tuning; that is the engine being switched off.

Two further readings from this set, both cautionary:

- Tracked LOO **r = −0.13**. The tracked engine's spreads are *anti-correlated*
  with outcomes here. With 8 observations spent on 5 free team strengths, that is
  what an unidentified model looks like.
- Score engine MAE 10.43 is **worse than pick-'em (8.62)** on these 8 games.
  Margins were 3, 6, 29, 4, 15, 6, 5, 1 — a near-coin-flip subset. Any estimator
  validated on these 8 games is being validated on the hardest possible sample.
  n=8 does not support a verdict flip in *either* direction.

`hybrid_ratings` stays off. Nothing here is a reason to reopen it.

## The gate can never open for a single-team coach. That is correct — and it is
## also the wrong question

`hub_share < 0.5` is unreachable for a coach tracking only their own team: their
team is an endpoint of every game they log, so `hub_share = 1.0` permanently, by
construction and not by accident. The gate as written can never open for the
primary user. Three claims about that:

**1. For the job the gate actually guards — ranking — the gate is right, and
loosening it would be a bug.**

`hybrid_ratings` makes an *ordinal, cross-team* claim: it moves teams relative to
each other. A star graph cannot support one. With every game sharing the hub, the
design matrix identifies the *differences* `hub − opponent_i` but not the
opponents against each other, and the hub's own level is confounded with the mean
of its opponents. Tonight's r = −0.13 is that rank-deficiency showing up as
noise, on a set with perfect coverage.

The scale problem is worse than the identification problem. 5 of 748 boys teams
have any tracked data. Blending would perturb 5 rows against 743 untouched ones.
That is not a re-ranked league; it is 5 teams jumped for a reason no other team's
rating reflects. No value of `hub_share` makes that sound.

**2. "Rate MY team better" is a genuinely different estimand, and it is
better-posed, not worse.**

For the league question, `hub_share = 1.0` is a defect. For the my-team question
it is *the design*: the hub is the only team we have a real sample on, and the
opponents are nuisance parameters. And critically — those opponents are not
unknown. Each has a full season of score data (~20–30 games) behind a score
engine validated at 7.26 MAE league-wide.

So the right model for "how good is my team, using my tracked possessions" holds
opponent strength **fixed** at the score engine's estimate and frees exactly one
parameter: the hub's tracked strength. That is 8 observations for 1 parameter —
well-posed — versus the 8-for-5 that `tracked_ratings` is currently solving and
losing.

This is the load-bearing point: **relaxing the gate while keeping the estimator
would be strictly wrong.** `tracked_ratings` free-estimates all 5 teams, so under
a loosened gate it would spend a scarce 8-game sample re-deriving 4 opponents the
score engine already knows far better. The one-team case needs a different
*estimator*, and only then a different gate. A gate change alone is the worst of
the available options.

**3. The my-team case probably should not route through `hybrid_ratings` at all.**

The gate exists to protect a ranking. The my-team question does not make an
ordinal cross-team claim, so it does not need that protection — and the parts of
the tracked engine a coach actually wants (possessions, four factors, lineups,
WPA, play-type splits) make no cross-team claim either and are already ungated.
The spec's original framing holds: the tracked engine's value is **diagnostic,
not ordinal**. "How good are we?" is answered by the score engine at 7.26 MAE.
"Why are we good, and what do we fix?" is answered by the tracked layer, and
neither answer requires a blended rating.

### Recommendation (not implemented)

- Keep `hub_share < 0.5` exactly as written for `hybrid_ratings`. Do not add a
  one-team exemption. It correctly reports that a one-team sample cannot rank a
  league.
- Do **not** relax the gate for the my-team case. If a tracked my-team rating is
  wanted, it is a separate function — opponent strengths fixed from the score
  engine, one free hub parameter — with its own gate and its own shrink-only
  control, not a loosened `hybrid_ratings`.
- Any such gate needs a minimum-games condition that 8 does not obviously clear,
  and it cannot be validated on this particular 8-game set (score engine loses to
  pick-'em on it). Grow the sample first.

The tracking *pattern* is right, and worth saying plainly to the coach: the boys
set — home-and-home against 4 opponents — is the shape the girls set lacks.
Repeat matchups are what separate improvement from noise. More games in that
shape is the correct next move; more games around a single hub is not.
