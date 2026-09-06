# Roadmap — September 2026 (polish month)

Written 2026-09-05 after the QOL survey and the `polish-2026-09-05` build.
Target: October, when coaches start looking at data to get their teams ready.
Companion docs: `QOL_SURVEY_2026-09-05.md` (the read), `POLISH_BUILD_2026-09-05.md`
(what shipped tonight).

Ordered by value ÷ risk. Items 1-7 are polish-month scope; 8-9 are the standing
headline items and are bigger than polish.

---

## THE HEADLINE ITEM

### 1 · Point-in-time résumé — rankings that remember

**This is the highest value-to-effort item in the app, and 80% of it is already
built and already backfilled.**

`rating_snapshots` holds **18 weekly boards, 2025-11-16 → 2026-03-14**, both
genders, ~480 teams per board on the `score` system.
`rating_history.backfill_weekly` reconstructed them by re-solving each board over
exactly the games finished on or before that date — so this is not an estimate of
what the board would have said, it is what the board *does* say over the games
that existed at the time.

Wired today: `risers` (awards, Spotlight), `movement` (Rankings), `team_series`
(the Overview rank trajectory). **Nothing reads it for any of the three things
below.**

#### 1a · Rankings as of any week

A week picker beside the season picker on Rankings, reading `rating_snapshots`
directly. This is a **pure table read — no engine call**, so it is FASTER than
the live board, not slower. 18 days available for 2025-2026.

#### 1b · The opponent's rank going into the game

Every game-log and schedule row carries "beat **#6** Broken Bow" instead of "beat
Broken Bow", resolved against the snapshot day BEFORE the game date.

Measured feasibility: **9,485 of 9,676 team-games resolve.** The 191 that do not
are games played before the first snapshot day — render those without a rank
rather than guessing.

#### 1c · Quality wins, counted honestly

Wins over a team ranked top-N **at the time they were played**.

Every product that ships "wins vs top-25" computes it against *today's* board.
That is wrong, and on this book it is measurably wrong:

```
rank movement 2025-12-14 -> 2026-03-14:  median 68 places, p90 128, max 205
top-25 in December still top-25 in March:  11 of 25

quality wins vs then-top-25:  70
quality wins vs now-top-25:   75
teams whose count CHANGES depending on the board:  38 of 51
```

CANUTE has **3 quality wins at the time and 0 today**. Grind Prep has **0 then
and 3 today**. Beating Lincoln Christian on 2025-12-31 when they were #1 is a
résumé line; beating them in March after they slid is a different game, and
today's board cannot tell the difference.

Résumés that fall straight out of the existing data: Bixby 6 QW (#1 Lincoln
Christian, #8 Mustang), Putnam City North 5 (#5 Bixby, #8 Broken Arrow),
Washington 4, Howe 3, Union 3.

**The one caveat that must appear on screen:** backfilled boards use *today's*
model constants, not whatever was adopted at the time, so a recal makes
reconstructed history disagree with history that accrued live. Regenerate
backfilled days after a recal — safe to do, the write is `INSERT OR IGNORE` per
`(day, gender, system, team_id)`.

**Note on the `tracked` system:** it has 1-5 rows per day (few tracked games), so
1a-1c should run on the `score` system only until the tracked pool is deep enough
to rank.

---

## POLISH-MONTH SCOPE

### 2 · Run the repair tool against the live book — FOUNDER DECISION

`tools/repair_book.py` reports and changes nothing without `--apply`. Verified
against a copy: 12 findings, `--apply` fixes the two mechanical ones (game 4's
`tracked` flag; the nine duplicate games) and is idempotent.

```bash
python tools/repair_book.py
```

⚠️ **Eyeball the Yukon vs Alva pair first** — the two rows disagree on the score
(43-55 vs 44-53). The tool keeps the row that has a location; the other may be
the right one. Two further findings are report-only by design: which of two
players wearing #4 is wrong is a roster question, and the same-player-in-both-
slots charge (`game_events.id 7101`) wants the Event Editor.

**Not an agent's call. Back the book up first.**

### 3 · `UNIQUE(date, team1_id, team2_id)` on `games`

Would make `ossaa_sync.merge_teams`' `UPDATE OR IGNORE` behave the way its own
comment already claims, turning this whole duplicate class from *repaired* into
*impossible*.

Blocked on **item 2** (the constraint cannot be added while duplicates exist) and
on a founder ruling: **are legitimate same-day rematches possible?** A tournament
that plays the same pairing twice in one day would violate a strict constraint. If
so, the index wants a third discriminator or has to stay partial.

### 4 · Quarter analysis into Insights

The only real content gap left in the flagship. Charts → Quarters has four
sub-tabs; the Insights deck has **zero** quarter reads except the foul-trouble
quarter lines at `insights_deep.py:561`.

"We're a third-quarter team" / "they are" is a sentence every coach says out loud,
and the flagship of the flagship cannot say it. Sections are lazy, so a new panel
costs only when opened. Adding a metric means `METRIC_SECTION`, `METRIC_EVIDENCE`
and (only with a defensible derivation) `PTS_RULES` in `insights_severity.py` —
`test_insights_severity.py` fails if a miner emits a metric with no section or no
evidence destination.

### 5 · The remaining `season="Current"` defaults

~25 latent ones in `helpers/dashboard/*`: `insights_tab`, `player_card`,
`team_card`, `share_tab`, `analyze`, `insights_deck`.

Latent, not live — those are render wrappers and the pages always pass an explicit
season. But it is the same trap that produced three live breaks in one evening,
and it will bite the first caller that forgets. Convert to `SEAS_DEFAULT` +
`resolve_read_season()`, exactly as the engine layer now does.

### 6 · The 18 eager `st.tabs`

4 on Team Dashboard — including `qt1..qt4` at `pages/6_Team_Dashboard.py:3407`,
which runs all four Quarters bodies on every rerun of that view — and 4 on
Rankings.

Same conversion as the box score, but these are **page-level**, where the known
failure mode is a body leaning on a name a sibling defined. **AST-sweep for
cross-tab variable leaks before converting**, and do not run this one unattended.

### 7 · `archetypes._choose_k` fits KMeans 60 times per call

`k = 4..8` with `n_init=10`, then `_fit_kmeans` does 10 more, on ~100 players ×
10 features. 2.5s inside `player_ratings._archetype_anchors`.

`n_init=3` plus memoizing `k` on the matrix fingerprint takes it to ~0.3s.
**Gate it** — assert the chosen `k` is unchanged across the book before adopting,
because `k` feeds the archetype taxonomy and therefore the team prior. This is a
constant-adjacent change and the house rule applies.

---

## STANDING HEADLINE ITEMS (bigger than polish)

### 8 · Officials rating rework

Unchanged from the 2026-09-05 handoff and still the biggest single piece of
thinking on the board. 60% of the current weight is a property of the GAMES, not
the referee. The priced-games floor is decided (`rated_games >= 3`) and not yet
applied.

### 9 · iPad Mode (N4) — now unblocked

Was blocked on a parked branch; the tablet layout reached `main`. Composition
change only: keep `S.screen` exactly as it is and change what each screen
renders at tablet width.

---

## DELETIONS

- `team_insights.keys_extra` — zero call sites, verified twice.
- `development.project_rest_of_season` — zero call sites.
- `scout_notes` (0 rows, one consumer), `manual_player_box` (0 rows) — finish or
  drop.
- `MARKETING.md` and `ML_LAYER_ROADMAP.md` still reference the Analytics Hub —
  stale since 2026-09-05.
- **Keep** `hockey_from_id` (100% NULL but by design — HAST is inert until
  tagged) and **keep** `charges.charge_rate_map` (a memory note calls it dead; it
  is consumed by `player_ratings`).

## QUICK WINS

- **Spotlight cold is 38.8s**, essentially all `_intel`. Put it behind an opt-in
  button, the way the Impact Lab gates its heavy three.
- **Scout is now the slowest view** — 11.7s cold / 3.4s warm. Nothing else is
  above 2.8 warm. Unprofiled.
- **Hall of Fame calls `score_ratings` per season label in a loop** — likely slow,
  unmeasured.
- **`_finished_games` applies no dedup**, so results-only ratings would
  double-count any future duplicate exactly as they did the nine. Item 3 is the
  real fix; this is the belt.

---

## THE PATTERN WORTH REMEMBERING

Two findings from this survey generalise, and both point the same way:

1. **One bug class accounts for most of what is actually broken.**
   `season="Current"` as a bare default produced three live breaks in one evening
   and has ~25 latent instances left. Grep for it reflexively.

2. **The highest-value work is surfacing what is already computed, not computing
   more.** `rating_snapshots` sat fully backfilled with nobody reading it for the
   three features in item 1. The buried-analytics map listed two engines as
   unimported that had already been built. Engine done, surface missing — that is
   where the wins are, and it is the right shape for polish month.
