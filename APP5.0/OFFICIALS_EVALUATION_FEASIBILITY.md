# Officials Call-Evaluation (Trusted Evaluators Grade the Whistle) — Feasibility Report

> Future-look reference. Not on the near-term roadmap. Written 2026-07; grounded in the officials
> engine that already ships (`helpers/officials.py`, `helpers/ref_tendencies.py`, `pages/8_Officials.py`).
> Revisit when (a) an assigner/observer wants to grade calls in-app, (b) the officials engine becomes
> a paid driver, or (c) an association asks for a defensible, shareable evaluation record.

## Goal

Let **assigners and other trusted evaluators** (veteran officials, association observers) grade what
a ref actually did on the floor — **whistle vs. no-whistle**, and the **correctness of the decision**
on a simple tier (**no-way / defensible / obvious**). Turn refereeing from *tendency* measurement
(how often he calls fouls) into *accuracy* measurement (how often he's **right**), producing an
objective, defensible evaluation record per official that today does not exist anywhere in HS ball.

This is the layer the FAQ already promises officials — "a true objective rating, not a reputation" —
but taken one step further: not just what the whistle did, but whether it was correct.

## Verdict (read this first)

**Realistic and differentiated — the engine and capture surface already exist; this is a new
event type + a grader role, not new analytics infrastructure.** The tracker already logs a foul
with the official who called it (`secondary_player_id` + official slot), the quarter/clock, and the
game state. Adding an **evaluation** on top of a call — or a **missed-call** marker where no whistle
blew — is a new tagging surface riding rails we already own (the Event Editor, the officials engine,
the crew/individual pages).

The hard parts are **not** technical:

1. **Subjectivity.** "Correct" is a judgment. One evaluator ≠ truth. Needs multiple graders,
   inter-rater agreement, and trust-weighting — or it becomes one person's opinion dressed as data.
2. **Politics.** Grading refs right/wrong is far hotter than the tendency stats, which were already
   flagged "politically touchy" (MARKETING.md). This must be **evaluator-only, never public**, and
   framed as development, not gotcha.
3. **The no-whistle problem.** Tendencies only see calls that happened. Evaluating *missed* calls
   means capturing non-events — a decision moment with no foul logged — which the tracker has no
   concept of today.

## The grading model — two axes

Per evaluated decision moment:

- **Axis 1 — Whistle state:** `WHISTLE` (a call was made) vs. `NO_WHISTLE` (play continued). For a
  no-whistle, the evaluator is asserting a decision point existed (potential missed call).
- **Axis 2 — Correctness tier:** the user's three-rung scale —
  - **OBVIOUS** — clearly the right decision; any competent official gets this.
  - **DEFENSIBLE** — reasonable; could go either way; not dinged.
  - **NO-WAY** — clearly wrong; a call that shouldn't have been made, or a foul that clearly should
    have been.

The cross-product is the useful part: a NO_WHISTLE + NO-WAY = **missed call**; a WHISTLE + NO-WAY =
**bad call**; anything DEFENSIBLE or OBVIOUS = clean. Per official you roll up a **correct-rate** and
a **missed-call rate** alongside the existing tightness/lean profile.

## Why this rides existing rails

1. **Capture** — the tracker already stamps a foul to an official with quarter/clock/game-state.
   An evaluation is a child record on that foul (WWA already has the anchor). A no-whistle needs a
   new lightweight "decision point" marker the evaluator drops (no player/foul required).
2. **Engine** — `helpers/officials.py` already aggregates per-official across every logger and
   shrinks thin samples toward league mean. A correct-rate is one more aggregate on the same grain,
   with the same shrinkage and low-confidence flagging.
3. **Surface** — the Individual tab in `pages/8_Officials.py` already shows a per-ref deep dive
   (foul rate, quarter splits, game log). Correct-rate / missed-call rate slot in as new rows,
   evaluator-gated.

## The subjectivity gate — do NOT skip

A single grader is an anecdote. To be defensible:

- **Multiple evaluators per game/clip** where possible; report **agreement**, not just a score.
- **Trust-weight graders** — a veteran observer's grade counts more than a first-year's, learned from
  how often each agrees with the consensus (same shrinkage philosophy as the rest of the app).
- **Print the n and the confidence** — an official with 6 graded calls is not rated; say so, exactly
  like the crew-outlook low-confidence flag already does.
- **Never a single "ref accuracy" leaderboard** shipped raw — that's the name-and-shame surface the
  whole officials design avoids. Development tool for the assigner, not a public rank.

## Capture-workflow options (cheapest first)

- **A) Live, on top of the tracker.** Evaluator in the gym taps a grade as calls happen. Fast, but
  in-the-moment and single-grader; no replay.
- **B) Post-game film review (recommended).** Evaluator scrubs the game video/event log and grades
  each logged foul + drops no-whistle markers. Slower, far more accurate, replay-defensible, allows
  multiple graders on the same game. Pairs naturally with the Event Editor we already have.
- **C) Clip queue.** System surfaces the highest-leverage moments (late-game, close-game fouls via
  `helpers/late_game.py`) for grading — grade what matters, not all 40 fouls.

## Access / role

Evaluation is **strictly evaluator-role**, a trust tier above coach: sees official *names* and grades
them, but has no team/roster/scout access, and **none of this ever touches the public feed**
(`helpers/public_feed.py` stays the single public gate — grades are added to the Never-Public list).
An assigner is the first evaluator role; veteran officials/observers can be granted it.

## Phased scope

- **Phase 1 (lowest risk): grade existing logged fouls, single evaluator, post-game.** New evaluation
  event keyed to a foul; three-tier correctness; evaluator role gates a new "Evaluate" surface reading
  the game's foul log. No no-whistle capture yet, no multi-grader. Ships on the existing engine +
  Event Editor + a role flag. This is the demo you can promise the assigner.
- **Phase 2: no-whistle / missed-call markers + correct-rate on the officials page.** Add the
  decision-point marker; roll correct-rate and missed-call rate into the Individual tab, evaluator-gated,
  shrunk + confidence-flagged.
- **Phase 3: multi-grader consensus + trust-weighting + agreement reporting.** Turn it from one
  opinion into a defensible measured rating.

## Data-quality reality (be honest with the assigner)

Grades are only as good as the evaluators and the coverage. Early on it's thin and subjective; the
value compounds as more trusted graders log more games — same flywheel as the rest of the app. The
honest pitch: "this becomes a real, defensible accuracy rating as your best evaluators grade more
games," not "instant objective truth."

## Effort / risk

Moderate. No CV, no GPU, no new math — new event type, an evaluator role, a grading surface, and
(Phase 3) a consensus/trust model. The real work is **policy**: the correctness rubric, the
name-visibility rule, and the development-not-gotcha framing. Phase 1 is the only piece to touch first.

## Open questions for the assigner conversation

- Is the three-tier scale (no-way / defensible / obvious) their rubric, or do they grade on a
  different scale (e.g. correct/incorrect, or a 1-5)? Match their existing evaluation language.
- **Live in the gym** or **post-game on film** — which fits how they already observe?
- Do they need **no-whistle / missed-call** capture, or only grading of calls that were made?
- Multiple evaluators per game (defensible consensus) or one trusted observer (faster)?
- Does the ref ever see their own grades (development) or is it assigner-eyes-only?
- Is this a **paid product** for their association, or a courtesy tool?
