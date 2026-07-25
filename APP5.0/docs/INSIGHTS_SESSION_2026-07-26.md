# Insights session — 2026-07-26. What shipped, and the one finding that matters.

Two commits on `main` (`637cce1`, `eed95a1`), still **unpushed** along with the
61 that were already waiting. Deploy is Sunday.

---

## Read this part first — the measurement said no

The plan was: offensive SHARES measure SB .70–.92 while offensive RATES collapse
to SB .11, so port every defensive read as a share and inherit the reliability.
Built it, measured it (200 random half-splits, the same method as the rest of
the book), and **it does not port.**

```
  defender read                 F/2025-26 SB   whole-book SB   adopted
  paint_share (interior)             .595           .643        .578
  three_share (perimeter)            .578           .640        .578
  DLOAD%  (share of contests)        .574           .579        .574
  arc3 assignment share              .438           .461        .438
  PPS allowed                        .437           .604        .437
  spot-up assignment share           .418           .532        .418
  FG% allowed                        .399           .559        .399
  pick-&-roll assignment share       .354           .309        .309
  rim04 assignment share             .260           .313        .260
  4ft-to-arc assignment share        .172           .228        .172
  off-the-dribble share             -.017           .153       -.017
  ISOLATION assignment share        -.061          -.150       -.150
  on/off delta, opp rim share       -.030          -.077       -.060
  on/off delta, opp three share      .099           .071        .071
  on/off delta, opp PPS              .028           .130        .028
```

The reason is structural, not sample size. **An offensive share is a choice the
player makes. A defensive assignment share is a choice the opponent makes.** A
guard who hunts floaters hunts floaters every night; a defender whose assignment
took 60% isolations last week drew a different offense this week. Split-half
reliability is detecting exactly that — the metric is a property of the fixture.

So the two sentences you asked for by name are the two the data refuses:

- **"#3 comes on and their man's press% skyrockets"** → the on/off footprint
  deltas measure **-.06 to .23**. Same failure mode as raw offensive on/off
  (r = -.096), same reason: the four teammates move with her.
- **"they are an iso defender"** → isolation assignment share measures
  **SB -.15**, anti-correlated. Worse than any offensive read in the book.

Both still **render**, flagged `descriptive`, with the sentence itself saying it
is a record of these games rather than a trait. They are not withheld — a coach
preparing for these games is entitled to know what happened in them. They just
never become a projection. Full write-up in `helpers/reliability.py`, block
`DEFENSIVE SHARES ARE NOT OFFENSIVE SHARES`.

**What survived**, and both survive because they aggregate over *who* the
opponent was:

- **DLOAD%** (SB .574) — the defensive twin of usage. Share of the team's tagged
  contests a player takes on while she is on the floor. Five players share every
  possession so **20% is average by construction**, which makes it readable with
  no pool at all. Live book: mean 20.9%, top 35.3%, bottom 6.8%.
- **The coarse interior/perimeter axis** (SB .578). The fine band cut inside it
  (rim04 .26, two419 .17) does not survive — that split is the opponent's shot
  selection wearing the defender's name.

---

## The defect from the last handoff is fixed

`stats.shot_quality_rates` had no floor and no shrinkage, and all eleven
consumers resolved a missing key with `.get(key, {}).get("pct", 0.0)` — pricing
an unseen look as **certain to miss**.

```
  location term    raw miss=0.0   raw miss=global   floor 20   hier EB k=50
  zone                0.67343         0.67105        0.62595      0.62388
  KIND (shipped)      0.66613         0.65250        0.60787      0.60455
  BANDS               0.65408         0.64270        0.60584      0.60445
  no location at all  0.63549         0.63549        0.63504      0.63466
```

Worth **9.2% of log loss**. The kind-vs-zone reprice that was thought worth
shipping bought 2.3%. And the bottom row is the one to remember: **unregularized,
the location term was actively harmful** — dropping location entirely beat both
taxonomies. The whole shot-kind thread only pays once the cells are regularized.

Fix is a three-level EB backoff (global → kind → kind+guarded → cell) at k=50,
returned as a `_RateBook` whose `get()` resolves unseen keys to a parent. All
eleven call sites fixed without touching any of them.

**It is rho-neutral, and that was verified rather than assumed.** Swept through
the rating gate, k = 0/10/25/50/80 all return 0.6850, as does a hand-rebuilt
copy of the pre-shrinkage engine. The stale `0.688` pin in
`test_ratings_depth_smoke` was drift in the book, not this change — that test
was one of the four known failures and **now passes** (114/117).

---

## What is on the Insights tab now

Feed went **315 → 413 lines**, 31 distinct reads, 111 of 242 players.

Six new generators:

| Generator | Status | Note |
|---|---|---|
| `Def load` | verdict | DLOAD%, SB .574 |
| `Def area` | verdict | interior/perimeter, SB .578 |
| `Assignment` | **descriptive** | measured and refused (SB -.15) |
| `Def footprint` | **descriptive** | measured and refused |
| `Foul rate` | verdict | fouls/32min — **SB .68–.84**, the most repeatable player defensive number in the book, and surfaced *nowhere* before |
| `Vs scheme` | verdict | `player_defenses_faced` already existed with no surface — fired 38 times, the most of any generator |

New `helpers/dashboard/insights_deep.py` brings other tabs' reads onto Insights
**without moving their charts**: the defensive board, the foul-rate board, and
11 ported verdict sections (stops · hero-ball · involvement · foul trouble · foul
clock · possession ledger · runs · self-scout · giveaway mix · rebounding ·
vs-scheme). All 11 fire on the live book. Engines that raise are *reported*, not
swallowed.

`tracker/test_insights_deep.py` — **57 checks**, including an end-to-end AppTest
render of the Insights view (164k chars) and assertions that the refused reads
stay flagged descriptive and say so in their own sentences.

---

## Still open

- **xPPP game prediction — not started.** Its prerequisite (the rate-book fix
  above) is now done, which was the blocker. The premise is intact and this
  session added a third measurement supporting it.
- The remaining three known test failures: `test_charges`,
  `test_connection_matrix`, `test_pdf_export` (no PDF engine installed).
- `helpers/defense_profile.py` also exposes `team_allowed_diet` (the defensive
  mirror of shot diet) — rendered on the tab, but **no team-level generator
  reads it yet**. Cheap next win.
- Nothing in the defensive engine is wired into the player card or Scout tab
  yet; it is Insights-only so far.

## Traps found this session, worth not re-finding

- `league_run_table`'s profile carries **per-game rates** (`made_pg`,
  `allowed_pg`, `by_count`, `biggest`), not counts. Wrong keys make the section
  silently produce nothing rather than erroring.
- `selfscout`'s `top_share` is **already 0-100**. Scaling it again prints
  "Isolation at 2740% of tagged calls".
- Passing the league game pool where `ctx.tracked_ids` carries the **team's**
  games produces a 4,136-possession defensive ledger against a 372-possession
  offensive one. Both numbers computed correctly; only the ratio gave it away.
- Play-type labels mix prose ("Off screen") with acronyms ("DHO", "BLOB"). A
  blanket `.lower()` yields "drew the dho action". `insights._lc` handles it.
- Turnover labels are terse table nouns ("Pass", "Drive") and read as
  truncations in a sentence.
