# Next session — INSIGHTS, round 3. Written 2026-07-26.

Paste this whole file as the opening message.

---

## Read first, in this order

1. `helpers/reliability.py` — **the three measurement blocks at the bottom**,
   before anything else. In order: DEFENSIVE SHARES ARE NOT OFFENSIVE SHARES ·
   GROUPING RESCUED TWO AXES · THE ACTION AXIS, BOTH SIDES · SHOT QUALITY DOES
   NOT FORECAST SCORING. Every constraint on what may be SAID flows from them.
2. `docs/INSIGHTS_SESSION_2026-07-26.md` — what shipped and why.
3. `docs/COACH_ROADMAP_2026-07-25.md` — **§BL3 at the bottom first**. Thirteen
   claims in the body are marked `CORRECTED` inline; do not trust an uncorrected
   line without checking the code.
4. `helpers/defense_profile.py` docstring — the new engine and its three axes.

## WORKING PROTOCOL — follow it for every part

**BEFORE:** interview me one question at a time, multiple choice preferred, wait
for each answer, until you can state the vision back in a paragraph I agree
with. Cover: what a coach can DO after this ships; the one sentence it lets the
app say; where it lives and what it displaces; what "done" is and what's out of
scope; how it degrades on a thin sample.

**DURING:** build in the stated order. Show numbers from the real DB as you go,
not just code. **If the data contradicts the doc, say so immediately and stop.**

**AFTER:** interview again — coach language, what's missing now it's built, what
changes for the parts ahead, what gets cut. Update the roadmap, commit, then the
next BEFORE.

## STANDING CONSTRAINTS

- **Density, not simplicity. More information, always.** Never propose removing
  information, only giving it shape.
- **No page is removed, no depth consolidated away.** All 16 pages mean
  something. Insights is the FLAGSHIP — the page a new coach is sent to. Reads
  get gathered there; the charts that produce them stay where they live.
- **`entitlement.tracked_gate` is what the whole app is built on.** Every new
  surface READS it. Reciprocal: a co-op member sees another team's
  current-season depth only when BOTH sides are pooled. Past seasons open to
  everyone across gender. Free = box score, Paid = own team. Navigation is never
  gated, only depth.
- **Measure before shipping a verdict.** Repeated random half-splits (200, not
  one — at ~30 units a single split's r has a sampling spread near ±.2). The
  gate number comes from the measurement, not a guess.
- **Description is not prediction.** Gate the JOB the number does, not the
  number. A season FG% is a record and always renders; a trait claim must clear
  `reliability.WEAK_SB` and must have been measured at all.
- **Ask whether it is a PLAYER number or a TEAM number.** New this session and
  it caught a live mistake — see below.
- Prod is 1 vCPU / 2 GB no swap. One event pass reused beats N passes.

## ENVIRONMENT

- Live DB `C:\Users\colby\AppData\Local\APP5\analytics.db`, open `mode=ro`.
  The repo's `APP5.0/analytics.db` is a 0-byte stub.
- Use `C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe` —
  shell `python` is the Store build and sees a virtualized shadow of AppData.
- `APP5_DATA_DIR=<dir>` points the app at a different DB. **Copy the live DB and
  point at the copy before testing anything that WRITES.**
- AppTest smokes: run from a cwd with NO `.streamlit/secrets.toml`; patch
  `helpers.auth`, `helpers.entitlement`, AND `helpers.ui.gender_radio`. Seed
  `ta_team` / `ta_season='2025-2026'` / `td_view`. `st.session_state` has no
  `.update()` in AppTest — assign keys one at a time.
  `tracker/test_insights_deep.py` is a working example end to end.
- `S.fetch_events([])` returns the ENTIRE database. Empty gid list means
  "everything", not "nothing". Guard explicitly.
- `SEAS.ACTIVE` is the sentinel `'Current'`, not a year. All 43 tracked games are
  under season label `2025-2026` (35 F / 8 M).
- Scratchpad is session-scoped — the measurement harnesses are GONE. Every
  method is written into `reliability.py` so they can be rebuilt.
- Test suite: `tracker/test_*.py`, run individually. **115 of 118 pass.** The 3
  failures pre-date this work (`test_charges`, `test_connection_matrix`,
  `test_pdf_export` — no PDF engine installed). `test_ratings_depth_smoke` was
  a fourth and now PASSES.

## STATE

**68 commits unpushed on `main`.** Deploy is SUNDAY:
`push → ssh app5@107.170.27.154 → pull → restart app5-web`.

`rating_snapshots` was backfilled on the LOCAL dev DB (13,793 rows). Prod has
none — the Rankings page has a "Rebuild rating history" button.

---

# WHAT LANDED, IN ONE PAGE

**The rate-book defect is fixed.** `stats.shot_quality_rates` had no floor and
no shrinkage, and all eleven consumers resolved a missing key to `0.0` —
pricing an unseen look as certain to miss. Now a three-level EB backoff at
k=50, returned as a `_RateBook` whose `get()` resolves to a parent. Worth **9.2%
of log loss**. Unregularized, the location term was *actively harmful* —
dropping location entirely beat both taxonomies. Verified rho-neutral by
sweeping k through the rating gate.

**The offensive profile is ported to defense** — `helpers/defense_profile.py`:
assignment diet by band/kind/action/creation/scheme, DLOAD% (defensive usage;
20% is average BY CONSTRUCTION), the on/off opponent-diet footprint, and the
shot diet a defense allows.

**Insights is now the flagship.** Feed 315 → 409 lines, 33 distinct reads. New
`helpers/dashboard/insights_deep.py` holds the defensive board, the foul-rate
board, and 11 ported verdict sections (stops · hero-ball · involvement · foul
trouble · foul clock · possession ledger · runs · self-scout · giveaway mix ·
rebounding · vs-scheme). Engines that raise are reported, not swallowed.

## The four findings that constrain everything ahead

1. **Defensive shares do not inherit offensive reliability.** Offensive shares
   .70–.92; defensive assignment shares .17–.64. An offensive share is a choice
   the PLAYER makes; a defensive assignment share is a choice the OPPONENT
   makes, so it tracks the schedule.

2. **Coarsening rescues, at exactly two groups.** Isolation share alone −.15;
   rolled into on-ball vs off-ball, .373/.347. A 3-way split collapses again
   (.215/.088). Same shape as the band axis (rim04 .26 → paint .643).

3. **Pooled reliability can be entirely a TEAM number.** Man-defense share
   measures .734 pooled and **.321** demeaned within team. Press share: .541 →
   **.050**, refused outright. Scheme and grouped-action reads now score against
   a player's own teammates. **Run this test on any new player metric.**

4. **Offensive play-type PPP does not repeat** (iso .425, spot-up **−.135**,
   pnr unmeasurable) while the SHARE does (.76–.88). `_g_playtype` had been
   shipping a trait claim off the PPP and was the third most-fired generator in
   the app. It now leads with the share.

---

# THE xPPP PREDICTION IDEA IS MEASURED AND REFUSED — DO NOT REBUILD IT

Predicting games from expected shot quality alone. The premise — shot outcomes
are the noise, shot quality is the signal — is **true at player level** and
**false at team level**, which is where a game prediction would live.

```
  predictor  ->  target                      mean r
  expected PPS -> future ACTUAL PPS            0.176
  actual PPS   -> future ACTUAL PPS            0.655
  expected PPS -> future expected PPS          0.619
  actual PPS   -> future expected PPS          0.176
```

Past scoring forecasts future scoring **~4x better** than expected quality does.
And note the symmetry: each predicts itself at ~.62–.66 and the other at .176.
Shot quality and shot making are **two orthogonal, individually stable team
traits**, and the scoreboard is carried by the second. Quality is not a noisy
estimate of scoring — it is a different quantity that shares units.

**What survives, and it is worth building: the DESCRIPTIVE "deserved result".**
Out of sample over 43 games, the expected-points margin picks the scoreboard
winner **72.1%** of the time (r = .886 with final margin) and **disagrees on 12
of 43**. Those twelve are the artefact — *"the looks were even, the makes were
not"*. Live example: Salina beat Vinita by 3 with the expected margin favouring
Vinita by 15.4.

Before building it, fix the two caveats in `reliability.py`: xMargin is a SUM
over attempts so it partly restates possession count, and xPPS inherits the
`guarded_by_id` tagging rate (72% of shots).

---

# BACKLOG — pick one and interview

## Ready, blocked on nothing

- **"Deserved result" per game** (above). Descriptive only. Postgame + Insights.
  The one piece of the xPPP thread the measurement supports.
- **Team-level generator for `team_allowed_diet`.** The engine is built and
  renders on the tab; no team generator reads it. Cheapest win on the board.
- **§1.7 Prescriptions** (insight → drill). Closes "what do I run at practice
  tomorrow". Key rules on **share and materiality, never a per-player rate** —
  and now the on-ball/off-ball defensive split is available as a trigger too.
- **§1.4 Runs deep-dive.** `helpers/runs.py` only COUNTS runs. Run anatomy (what
  possession type started it, what defense, who was on) is the most
  coach-actionable chart left in the roadmap.
- **§1.3 Crash vs get-back.** ORB gain vs transition-allowed, split by lineup.
  Gate ≥8 games for the lineup split.
- **§1.5 Minutes load / in-game fatigue.** `helpers/fatigue.py` is BETWEEN-game
  rest only. Within-game load is missing entirely.
- **§1.8 batch:** FT points left on the floor · bonus discipline · set × defense
  promoted off Scout. All XS, all inputs exist.

## Wire the new engine into more surfaces

`defense_profile` is Insights-only. It belongs on the **player card** (§2.4 —
its shot bars must be SHARE bars, not percentage bars) and the **Scout tab**.

## Blocked, and what unblocks them

- **§1.2 timeout ROI** — 22 markers / 4 games. Unblocking move is a TRACKER
  logging fix, not analytics. Do it early so data accumulates.
- **Part 3 roster/graduation** — `grad_year` on 122/541. Build the §3.3 coverage
  tool first. `players.position` EXISTS (§3.4's claim is wrong).
- **crew_foul_rate** — accumulating, correctly unsurfaced. Busiest official has
  4 games. Revisit in a season.

---

# TRAPS — do not re-find these

- `S.fetch_events([])` returns the WHOLE DATABASE. Guard every pooled engine.
- **Passing the league game pool where `ctx.tracked_ids` carries the TEAM's
  games** produced a 4,136-possession defensive ledger against a 372-possession
  offensive one. Both numbers computed correctly; only the ratio gave it away.
- `league_run_table`'s profile carries **per-game rates** (`made_pg`,
  `allowed_pg`, `by_count`, `biggest`), not counts. Wrong keys make a section
  silently produce nothing rather than erroring.
- `selfscout`'s `top_share` is **already 0-100**. Scaling again prints "2740%".
- **A share is determined by its DENOMINATOR** — gate on the total, not on the
  numerator. Gating the numerator threw away two-thirds of the play-type reads
  while still admitting a 60%-of-9 accident.
- **Branch prose on the RESIDUAL, not on z.** z is ranked against a league pool
  of residuals and can carry the opposite sign, which produced "guards off the
  ball" for a player above her own team's on-ball share.
- Play-type labels mix prose ("Off screen") with acronyms ("DHO", "BLOB"). A
  blanket `.lower()` yields "drew the dho action". Use `insights._lc`.
- Turnover labels are terse table nouns ("Pass", "Drive") and read as
  truncations in a sentence.
- `mapped_shots` fills unlocated shots with the ZONE CENTROID; a centroid has a
  distance and classifies happily. `classify_shot` sends `approx=True` to
  `unknown`.
- Foul rows are INVERTED: `secondary_player_id` is the FOULER,
  `primary_player_id` is who was fouled.
- `team_card.render_for` needs the team's REAL gender and
  `SEAS.default_read_season()` — ACTIVE is the empty rollover.
- `PT._tracked_game_ids` takes gender only, no season.
- A column format of `"%.0f%%"` on a 0-1 fraction prints `0%`.
- `advanced_ratings.leaderboard` resolves list rows by `id`; Team Dashboard rows
  carry `_pid`. Mismatch renders a column present-but-empty rather than erroring.
- **Do not pin a gate number to three decimals.** `test_ratings_depth_smoke`
  pinned rho at 0.688; it read 0.685 and the drift was in the BOOK, not any
  model. rho is a rank correlation at n=48 — one SE is ~.075.
- Grep before naming a UI block. "Shot diet" already existed in three places.
