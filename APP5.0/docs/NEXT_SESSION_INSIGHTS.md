# Next session — INSIGHTS. Written 2026-07-26.

Paste this whole file as the opening message.

---

## Read first, in this order

1. `docs/COACH_ROADMAP_2026-07-25.md` — **§BL3 at the bottom first**, then the
   body. **Thirteen claims in it are marked `CORRECTED` inline.** Do not trust
   an uncorrected line without checking the code. Thirteen were wrong.
2. `helpers/reliability.py` — the measured book and the description/prediction
   rule. Everything about what may be SAID on a surface flows from it.
3. `helpers/shot_kinds.py` docstring — the two taxonomies and what each forbids.

## WORKING PROTOCOL — follow it for every part

**BEFORE:** interview me one question at a time, multiple choice preferred,
wait for each answer, until you can state the vision back in a paragraph I
agree with. Cover: what a coach can DO after this ships; the one sentence it
lets the app say; where it lives and what it displaces; what "done" is and
what's out of scope; how it degrades on a thin sample.

**DURING:** build in the stated order. Show numbers from the real DB as you go,
not just code. **If the data contradicts the doc, say so immediately and stop.**

**AFTER:** interview again — coach language, what's missing now it's built, what
changes for the parts ahead, what gets cut. Update the roadmap, commit, then the
next BEFORE.

## STANDING CONSTRAINTS

- **Density, not simplicity. More information, always.** Never propose removing
  information, only giving it shape.
- **No page is removed, no depth consolidated away.** All 16 pages mean
  something.
- **`entitlement.tracked_gate` is what the whole app is built on.** Every new
  surface READS it. Reciprocal: a co-op member sees another team's
  current-season depth only when BOTH sides are pooled. Past seasons open to
  everyone across gender. Free = box score, Paid = own team. Navigation is never
  gated, only depth.
- **Measure before shipping a verdict.** Split-half first; the gate number comes
  from the measurement, not a guess.
- **Description is not prediction** (new, 2026-07-26 — see below). Gate the JOB
  the number does, not the number.
- Prod is 1 vCPU / 2 GB no swap. One event pass reused beats N passes.

## ENVIRONMENT

- Live DB `C:\Users\colby\AppData\Local\APP5\analytics.db`, open `mode=ro`.
  The repo's `APP5.0/analytics.db` is a 0-byte stub.
- Use `C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe` —
  shell `python` is the Store build and sees a virtualized shadow of AppData.
- `APP5_DATA_DIR=<dir>` points the app at a different DB. **Copy the live DB and
  point at the copy before testing anything that WRITES.**
- AppTest smokes: run from a cwd with NO `.streamlit/secrets.toml`; patch
  `helpers.auth`, `helpers.entitlement`, AND `helpers.ui.gender_radio` — without
  the last, two different teams render byte-identical pages and the smoke proves
  nothing. Seed `ta_team` / `ta_season='2025-2026'` / `td_view`.
  `st.session_state` has no `.update()` in AppTest — assign keys one at a time.
- `S.fetch_events([])` returns the ENTIRE database. Empty gid list means
  "everything", not "nothing". Guard explicitly.
- `SEAS.ACTIVE` is the sentinel `'Current'`, not a year. All 43 tracked games are
  under season label `2025-2026` (35 F / 8 M).
- Live preview: `.claude/launch.json` has `app` (8511) and `app-noauth` (8512).
  Use `preview_start`, never Bash. Launch at session start and keep it up.
- Test suite: `tracker/test_*.py`, run individually. **113 of 117 pass. The 4
  failures pre-date all recent work** (`test_charges`, `test_connection_matrix`,
  `test_pdf_export` (no PDF engine installed), `test_ratings_depth_smoke`
  (asserts a hard-coded xA sum)). Running all 117 in one loop takes >10 min.

## STATE

**61 commits unpushed on `main`.** Deploy is SUNDAY, not mid-week:
`push → ssh app5@107.170.27.154 → pull → restart app5-web`.

`rating_snapshots` was backfilled on the LOCAL dev DB (13,793 rows; it had 0).
Reversible with `DELETE FROM rating_snapshots`. Prod has none — the Rankings
page has a "Rebuild rating history" button under 🕘 Rating history.

---

# THE ONE THING TO BUILD FIRST — it is not an insight, it is a defect

**`stats.shot_quality_rates` has no minimum cell size and no shrinkage, and
every consumer resolves a missing key with `.get(key, {}).get("pct", 0.0)` —
scoring an unseen shot as CERTAIN TO MISS.**

Measured out-of-sample on the girls' 2025-2026 book, varying only the cell floor:

```
  location term        raw (no floor)   floor 20   shrunk k=25
  zone                     0.72091       0.62734     0.62611
  KIND (shipped)           0.66753       0.61092     0.61123
  BANDS                    0.70204       0.60918     0.61069
  no location at all       0.63951       0.63906     0.63730
```

- Regularizing is worth **~8.5% of log loss** (.668 → .611). The kind-vs-zone
  reprice that was considered worth shipping bought 2.3%.
- Read the last row: **with no floor the location term is actively harmful** —
  dropping location entirely beats both zone and kind. The whole taxonomy thread
  only pays once the cells are regularized.

It touches every xFG / xPPS / SMOE / shot-quality number in the app across
**eleven call sites** (`stats`, `team_analytics`, `passing_chains`,
`insights_team`). That is why it was NOT slipped into a display change. **Give it
its own BEFORE interview.** Expect SMOE values to move for real players — the
last reprice moved 3 of 22 players' SMOE across a sign change.

Scratch harnesses are gone (scratchpad is session-scoped). Re-derive; the method
is: fit on odd games, score even, and the reverse, pooled; clamp p; report log
loss and Brier.

---

# WHAT CHANGED THIS SESSION THAT INSIGHTS WORK DEPENDS ON

## `helpers/reliability.py` is new and is the gate for every verdict

The measured book lives there, keyed `(unit, metric[, band])`. Callers ask it
instead of hardcoding a threshold. Levels: `stable` (SB ≥ .80) · `fair` (≥ .60)
· `weak` (≥ .30) · `withhold` (measured below .30) · `unmeasured` (never
measurable).

**The rule that matters most, learned by getting it wrong on screen:**

- `shows(sb, descriptive=True)` — a record of what happened (a season FG%, a
  shot count, a foul clock). **Always renders.** The dot only annotates whether
  it will repeat.
- `shows_verdict(sb)` — a trait claim, projection or prose line. Must have been
  measured AND clear the floor.

I originally gated description as if it were prediction and hid a team's own
shooting percentages behind a player-level reliability book. A coach could not
read their own box score. **Do not repeat that.** Ask what JOB the number is
doing.

`unmeasured` ≠ `withhold`. Team per-band FG% measures SB −.12 to .10 on FIVE
teams — that is not "measured as noise", it is not measurable, and asserting
either direction is a claim the data never made.

## Measured reliability you must respect (200 random half-splits, not one)

```
  player band/kind SHARE          SB .70-.92    reliable everywhere
  player 4ft-to-arc FG%           SB .52        best rate available, still weak
  player floater FG%              SB .285       withheld
  player rim FG%                  SB .11        withheld — "does she finish"
  player above-break-3 FG%        SB -.25       anti-correlated
  player overall foul rate        SB .68-.84    RELIABLE, and unused so far
  player x crew foul rate         SB -.68       anti-correlated, accumulate only
  team band SHARE                 SB .88
  team per-band FG%               unmeasurable at 6 teams
```

**Shares survive thin samples. Rates do not.** Any new insight quoting a
per-player percentage needs this check before it ships a number. A single
odd/even split at 24-28 units has a sampling spread near ±.2 — wider than most
differences you will be deciding on. Use repeated random splits.

## Two taxonomies now, both rendering

- **BANDS** (`rim04` / `two419` / `arc3` / `deep3`) — owns DISPLAY and every
  player-level read. `SK.DISPLAY_TAXONOMY`.
- **KINDS** (rim / floater / mid / corner3 / abovebreak3) — owns the
  shot-QUALITY model (`stats._sq_loc`) and still renders beside the bands.
- **Shot DIFFICULTY** (`stats._sd_loc`, `_bucket_make_rate`) uses BANDS — and
  kind measured WORSE there than the zone it replaced, because that key already
  carries `shot_type`. Two models, two different right answers. Measure each.

League table, F / 2025-2026, 3,056 located shots:

```
  rim04    836  27.4%  FG 54.3  PPS 1.086
  two419  1147  37.5%  FG 27.4  PPS 0.548     <- 37% of every shot, 0.55 a trip
  arc3     692  22.6%  FG 27.6  PPS 0.828
  deep3    381  12.5%  FG 25.7  PPS 0.772
```

---

# INSIGHTS BACKLOG — un-interviewed, pick and interview

## The big one: xPPP game prediction (own part, INTERVIEW BEFORE BUILDING)

Predict games from expected shot quality alone, taking make/miss out entirely.
**This session added three more measurements supporting the premise** — shot
outcomes really are the noisy part.

Variables, all already in the DB: shot kind/band (done); `pass_from_id`;
`hockey_from_id`; `shot_created_by_id` — all three as SEPARATE weights plus
combinations; `guarded_by_id`; `defense` (5,832 tagged); `play_type` (5,236
tagged); OREB% (hypothesis: high-OREB teams knowingly take worse shots expecting
the board).

`helpers/shotquality.py` fits a continuous ridge logistic on
`[distance, distance², is_three, contested, angle]` and is the natural home to
extend. `stats._creation_bucket` collapses two signals into 4 buckets and DROPS
the hockey assist entirely — three separate weights plus interactions is a real
modelling change, not a relabel. ~4,000 shots is not much: regularization and
out-of-sample validation matter more than fit. Validate fit-on-half /
score-the-other (log loss, Brier), then walk-forward for the win-expectancy claim.

**Do the `shot_quality_rates` fix above first — it is the same failure mode this
model would inherit.**

## Ready to build, blocked on nothing

- **§1.7 Prescriptions** (insight → drill). Closes the "what do I run at
  practice tomorrow" loop no competitor answers. Key rules on **share and
  materiality, never on a per-player rate**. Floater/4ft-arc share is the
  confirmed best trigger. ~15 rules; mostly content authoring.
- **§1.3 Crash vs get-back.** ORB gain vs transition-allowed cost on one axis,
  split by lineup. Gate ≥8 games for the lineup split.
- **§1.4 Runs deep-dive.** `helpers/runs.py` is good and only COUNTS runs, never
  explains them. Run anatomy (what possession type started it, what defense, who
  was on) is the most coach-actionable chart in the roadmap.
- **§1.5 Minutes load / in-game fatigue.** `helpers/fatigue.py` is BETWEEN-game
  rest only. Within-game load is missing entirely.
- **§1.8 batch:** FT points left on the floor · bonus discipline · set × defense
  promoted off Scout. All XS, all inputs exist.
- **Player overall foul rate** — measured reliable this session (SB .68-.84) and
  nothing surfaces it. Cheap, honest, unused.

## Blocked, and what unblocks them

- **§1.2 timeout ROI** — 22 markers / 4 games. Unblocking move is a TRACKER
  logging fix, not an analytics build. Do it early so data accumulates.
- **Part 3 roster/graduation** — `grad_year` on 122/541. Build the §3.3 coverage
  tool first. `players.position` EXISTS (§3.4's claim is wrong).
- **§2.4 player card** — largest rendering job left. Its shot bars must be
  **SHARE** bars, not percentage bars.
- **crew_foul_rate** — accumulating, correctly unsurfaced. Busiest official has
  4 games. Revisit in a season.

---

# TRAPS THAT COST TIME — do not re-find these

- `S.fetch_events([])` returns the WHOLE DATABASE. Guard every pooled engine.
- `mapped_shots` fills unlocated shots with the ZONE CENTROID; a centroid has a
  distance and classifies happily. `classify_shot` sends `approx=True` to
  `unknown`.
- `team_card.render_for` needs the team's REAL gender and
  `SEAS.default_read_season()` — it resolves from a scored pool, and ACTIVE is
  the empty rollover, so it silently draws nothing otherwise.
- Foul rows are INVERTED: `secondary_player_id` is the FOULER,
  `primary_player_id` is who was fouled. Reading primary yields player-games with
  10+ fouls.
- `PT._tracked_game_ids` takes gender only, no season.
- A column format of `"%.0f%%"` on a 0-1 fraction prints `0%`. Bit the winning
  formula for an unknown length of time; the progress bar beside it was correct,
  which is why nobody caught it.
- `advanced_ratings.leaderboard` resolves list rows by `id`; Team Dashboard rows
  carry `_pid`. Mismatch renders a column present-but-empty rather than erroring.
- Tests should ask the engine for its key, not restate the taxonomy —
  `test_xa2` reported a credit-rule failure when the rule was untouched.
- Grep before naming a UI block. "Shot diet" already existed in three places.
