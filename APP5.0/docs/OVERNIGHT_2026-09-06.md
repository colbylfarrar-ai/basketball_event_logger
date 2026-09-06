# Overnight build — 2026-09-06, branch `overnight-2026-09-06`

Unattended run against `docs/ROADMAP_2026-09.md` items 1, 5, 7 and the
deletions, plus the Spotlight quick win. Branched off `main` at `901facb`, **not
merged, not pushed**.

Seven commits:

```
c361a73  fix(tests): a TestCase with no unittest.main() ran in NEITHER suite
0f9ca81  feat(resume): the point-in-time résumé — rankings that remember
e6a3e34  fix(seasons): close the last 29 season="Current" defaults
da9b863  perf(archetypes): memoize _choose_k on the matrix — n_init stays at 10
1594b65  docs: point the stale Analytics Hub references at Rankings → Spotlight
0d02d81  perf(spotlight): the league miner is a button, not a toll
<this>   docs: the overnight handoff + roadmap corrections
```

---

## READ THIS FIRST — four things the roadmap got wrong

Three of tonight's corrections change what should be built next, and one of them
means a gate you thought you had has never existed. They are ahead of the build
log on purpose.

### 1. The nine tests written last night have never run

`test_results_season_rollover.py` — written specifically to guard the
season-rollover fix, and confirmed to fail before it — **ran in neither suite.**

`_test_kinds.is_script_style` decided a file was pytest-collectable by looking
for a module-level `def test_*`. That file's tests live in a `unittest.TestCase`
and it has none, so it was routed to `run_all.py` as a SCRIPT. run_all runs a
script with `python tracker/test_x.py`, and the file has no `unittest.main()` at
the bottom — so the process imported the module, seeded its throwaway DB, exited
0 and reported **PASS** having executed no assertions at all. `conftest.py`
meanwhile told pytest to ignore it. Two green suites, nine tests, no gate.

Fixed in the classifier rather than in the file: a TestCase counts as PYTEST
unless it calls `unittest.main()` itself, which is read as the same explicit
"run me as a script" contract `RUN_AS_SCRIPT` already provides. The `main()`
detection is AST, not a substring — the first cut looked for the literal
`unittest.main()` and missed `unittest.main(verbosity=2)`, which would have
dragged `test_turnover_types.py` (five tests, always running fine as a script)
into pytest for no coverage and real collection risk.

**This is why pytest goes 258 → 290 and not 258 → 281.** Nine of the thirty-two
new passes are tests you already had.

### 2. Both "safe deletions" are live code

`team_insights.keys_extra` and `development.project_rest_of_season` were both
listed as "zero call sites, verified twice". That is true of call sites
**outside their own module**, and completely misleading:

| function | in-module caller | reaches the screen via |
|---|---|---|
| `keys_extra` | `team_extras` (`team_insights.py:1123`) | `insights_tab.py:357` → the `keys` extra → `_t_keys`, a live generator in `_TEAM_GENERATORS`, tested in `test_insights_tiers.py` |
| `project_rest_of_season` | `player_development` (`development.py:283`) | `player_card.py:282` → `rest_of_season` → the whole "Rest of season" metric block at `player_card.py:1450` |

Deleting `keys_extra` would have removed the founder's own "undefeated unless
the four keys don't hit" read from the flagship. **Neither was deleted.** The
roadmap's DELETIONS section is struck with the trace, and the general lesson is
written next to it: *"no call sites outside its own module" is not evidence of
death — trace the in-module caller to a page first.*

### 3. `_choose_k` does not cost 2.5 seconds, and n_init=3 fails the gate

Roadmap item 7 said `_choose_k` costs 2.5 s and that `n_init=3` plus
memoization would take it to ~0.3 s. Measured on the live book:

```
call 1: _choose_k -> k=8 in  2155.6ms
call 2: _choose_k -> k=8 in   116.2ms
call 3: _choose_k -> k=8 in   110.3ms
call 4: _choose_k -> k=8 in    98.3ms
call 5: _choose_k -> k=8 in   100.1ms
```

The 2.2 s is **sklearn/BLAS thread-pool warm-up on the first KMeans fit in the
process.** It is paid whatever `n_init` is, and neither a memo nor a smaller
`n_init` can remove it. Steady state is ~0.10 s.

And the gate failed. See Task 3 below — `k` moved on 5 of 12 real matrices,
including the `_archetype_anchors` path that feeds the team prior. `n_init`
stays at 10; the memoization shipped alone, as instructed.

### 4. 1b resolves for 75% of team-games, not 98%

The roadmap's figure was "9,485 of 9,676 team-games resolve; the 191 that do not
are pre-first-snapshot". I could not reproduce that denominator from this book
and my measurement is materially different:

```
team-games in 2025-2026 (12,648 finished games x 2)   25,296
  resolved                                            19,080   75.4%
  opponent below the 5-GP snapshot floor               5,436   21.5%
  played before the first board (2025-11-16)             780    3.1%
```

The dominant gap is not pre-history — it is `MIN_SNAPSHOT_GP`. A board only
stores teams with five or more games played, so early in the season most
opponents have no row on the board at all. That is a deliberate design decision
in `rating_history` (the DB-stays-small constraint) and I did not change it, but
it means the "beat #6" chip is sparse in November and December and dense from
January on. **It barely affects quality wins**, which is the feature that
matters: a top-25 opponent has five games long before it is ranked top 25.

Method, so you can re-run it: every team's `team_game_log(season='2025-2026')`,
each row resolved with `resume.opponent_ranks`. Script kept in the branch's
history of this doc only; it is six lines against the public API.

---

## TASK 1 — the point-in-time résumé (roadmap item 1) — BUILT

`helpers/resume.py`, Streamlit-free, pure reads, the house convention. Three
surfaces on top of it.

### 1a — the board as of any week

A **"Board as of"** picker beside the season picker on Rankings. Picking a saved
day re-renders the rankings table as it stood: rank, movement since the previous
saved board, team, class, **the W-L as of that day**, the rating, and today's
rank alongside so the old board is worth reading. Defaults to "Current (live)",
and only offers days that exist — a day with no rows renders an empty board, and
on screen a league with no teams in it is indistinguishable from a broken page.

**On the speed claim, the roadmap is right about the read and wrong about the
view.** The board read is a pure indexed SELECT:

```
RES.board_as_of('M', '2026-01-18', '2025-2026')   478 teams   0.002 s
TR.score_ratings(gender='M', season='2025-2026')  748 teams   0.176 s
```

88× on the read. But the **page** does not get faster — 6.6 s cold either way,
measured in fresh processes both ways, twice each — because the Overview view's
cost was never the rankings table. It is the leaders, the form stats and the
tracked pack, all of which stay live and all of which the banner says stay live.

Scope decision, since the roadmap said "beside the season picker" but not what
the picker should govern: **the picker is at the top of the page and drives the
Overview rankings table only.** Everything else on Rankings is a live-engine
aggregation over the season's whole game pool, and there is no reconstruction of
those in the snapshot table. Inventing one would be a far bigger claim than this
feature makes. An `st.info` banner says exactly that on screen rather than
leaving a coach to work out which numbers moved.

Also worth knowing: an archived board is **shorter** than the live one (478 vs
748 teams at 2026-01-18) for the `MIN_SNAPSHOT_GP` reason in correction 4. The
caption says so. The page's class filter applies to the archived board; the
min-games filter does not, because snapshot rows carry no GP and applying
today's GP would filter a December board by a March sample.

### 1b — the opponent's rank going into the game

Two surfaces:

* **Team Dashboard → Schedule** gains an **`Rk @`** column beside `Opp Rk`.
  `Rk @` is where the opponent stood going in; `Opp Rk` is where they stand
  today. The column is dropped entirely when nothing resolves, the same rule
  `Trk Rk` already follows — no column of dashes advertising a feature with no
  data behind it.
* **Rankings → Team → Schedule & results**: the opponent chip used to read
  `#4 Bixby` using **today's** rank inline. That reads as a claim about the game
  and is not one — rank movement on this book from 2025-12-14 to 2026-03-14 has
  a median of 68 places, so a December row was describing a March team. The chip
  is now the at-the-time rank, with today's rank moved to its own `Rk now`
  column.

Resolution is **strictly the day before** the game, never on-or-before:
`backfill_weekly` solves each day over the games finished ON OR BEFORE it, so a
board stamped with the game's own date already contains that game's result. A
game with no board before it renders **no** rank rather than a borrowed one.

### 1c — quality wins, counted at the time

Team Dashboard → **Lab → Advanced → Résumé & Form**, directly under the Strength
of Schedule block whose `sos["quality_wins"]` is the naive version. The two are
shown together on purpose rather than left to disagree silently on one screen:
three metrics (at the time / on today's board / the difference), the qualifying
wins with both ranks and the board each came from, and plain-language lines for
the wins that only count one way.

Cutoff is a picker (10 / 25 / 50), default 25 — the number coaches and polls
already speak in, rather than the moving top-25% cut `strength_of_schedule` uses,
which is not comparable across genders or seasons.

Measured league-wide on this book, both genders, `top_n=25`:

```
teams with at least one quality win either way   102
teams whose count CHANGES with the board          71
total quality wins vs then-top-25                152
total quality wins vs now-top-25                 181

CANUTE Girls          then 3   now 0
Grind Prep Girls      then 0   now 3
BROKEN ARROW Boys     then 0   now 4
Lincoln Christian F   then 3   now 6
Bixby Girls           then 6   now 5
NORMAN / OWASSO / MUSTANG Boys   then 6   now 7
```

The roadmap's "38 of 51" was a one-gender read; 71 of 102 is the both-genders
version of the same finding, and CANUTE and Grind Prep reproduce exactly.

### The caveat, on screen

One string, `RES.CAVEAT`, rendered by both 1a and 1c, so it cannot drift between
two pages making the same claim:

> Reconstructed boards are solved with **today's** model constants, not whatever
> was adopted at the time — so history rebuilt after a recal can disagree with
> history that accrued live. Backfilled days are worth regenerating after a
> recal (Rankings → 🕘 Rating history → Rebuild); the write never duplicates a
> day.

Scoped to `system='score'` throughout. The `tracked` board has 1–5 rows per day
on this book, which is not a ranking.

### The guard

`tracker/test_resume.py`, **23 tests**, pytest-style, hermetic temp DB, with the
autouse `APP5_DATA_DIR` re-pin fixture copied from
`test_results_season_rollover.py`. Covers all four cases the roadmap asked for
plus the ones the fixture made obvious:

* the day-before resolution picks the right board, **including a game played ON
  a snapshot day**, which must read the previous board;
* a pre-first-snapshot game yields `None`, and separately an opponent with no row
  on an existing board yields `None` — two different gaps, and the second is 7×
  more common on the live book;
* then-vs-now genuinely disagree on a seeded fixture (Bravo and Charlie trade
  places between two boards), a loss to a then-ranked team is not counted, and
  `top_n` actually moves the answer;
* an empty snapshot table — and separately an empty *board* — degrades to
  `has_history=False` rather than raising;
* `SEAS.DEFAULT` resolves before the label lookup. Without that the module would
  query for the literal `'__default__'` and return a clean, silent, completely
  empty board — the exact shape of the rollover trap.

---

## TASK 2 — the remaining season defaults (roadmap item 5) — DONE

29 functions across the six modules named in the roadmap — `analyze`,
`insights_deck`, `insights_tab`, `player_card`, `share_tab`, `team_card` —
converted from `season="Current"` to `SEAS_DEFAULT` + `resolve_read_season()`,
exactly as the engine layer does.

**Behaviour verified, not asserted.** All ten Team Dashboard views and six
Rankings views rendered through the AppTest harness against a snapshot of the
live book, before and after, with the rest of this branch held constant so the
comparison isolates this change alone. Every rendered character count is
identical to the digit:

| view | before | after | view | before | after |
|---|---:|---:|---|---:|---:|
| TD Overview | 77,409 | 77,409 | TD Charts | 47,055 | 47,055 |
| TD Scout | 47,185 | 47,185 | TD Lab | 47,056 | 47,056 |
| TD Insights | 72,696 | 72,696 | TD Share | 46,171 | 46,171 |
| TD Projection | 64,135 | 64,135 | TD Glossary | 107,747 | 107,747 |
| TD Roster | 48,013 | 48,013 | RK Overview | 52,192 | 52,192 |
| TD Schedule | 48,962 | 48,962 | RK Compare | 45,728 | 45,728 |
| RK Team | 52,302 | 52,302 | RK Tracked | 46,854 | 46,854 |
| RK League landscape | 44,899 | 44,899 | RK Glossary | 105,350 | 105,350 |

No view raised.

`helpers/dashboard/sched.py` also changed tonight, but for Task 1 (the `Rk @`
column) — it had no `season="Current"` default.

---

## TASK 3 — `archetypes._choose_k` (roadmap item 7) — GATED, HALF ADOPTED

### The gate: FAILED for `n_init=3`

12 real matrices from the live book — both genders × `min_games` 1-3, on both
the `_archetype_anchors` feature set and the `cluster_players` default set.
Chosen `k` at `n_init=10` vs `n_init=3`:

```
anchors M/min_games=1   n= 59   k 8 -> 8   same
cluster M/min_games=1   n= 59   k 7 -> 8   MOVED
anchors M/min_games=2   n= 38   k 4 -> 4   same
cluster M/min_games=2   n= 38   k 7 -> 6   MOVED
anchors M/min_games=3   n= 10   k 4 -> 4   same
cluster M/min_games=3   n= 10   k 4 -> 4   same
anchors F/min_games=1   n=242   k 4 -> 4   same
cluster F/min_games=1   n=242   k 5 -> 4   MOVED
anchors F/min_games=2   n= 97   k 5 -> 5   same
cluster F/min_games=2   n= 97   k 5 -> 4   MOVED
anchors F/min_games=3   n= 70   k 5 -> 4   MOVED   <- the team-prior path
cluster F/min_games=3   n= 70   k 5 -> 5   same
```

Five of twelve, and one of them is the anchors path, which feeds the archetype
taxonomy and therefore the team prior. **`n_init` stays at 10.** A `k` that
moves is a model change wearing a speed-up's clothes, and the house rule says
that needs the full measured gate, not a silhouette table.

### Adopted: the memoization

`_choose_k` is a pure function of `X` and its three bounds, and pages call it
repeatedly on the *same* matrix:

```
Players render:      13 calls over  4 distinct matrices
TD Insights render:   6 calls over  2 distinct matrices
Rankings Spotlight:   3 calls over  2 distinct matrices
```

Keyed on a **blake2b of the matrix bytes, not its shape** — and that is not
hypothetical caution. One Players render built two different `(242, 13)`
matrices, the same pool at two different scopes, choosing `k=4` and `k=5`. A
shape-keyed memo would have handed one of them the other's taxonomy. Bounded at
32 entries, oldest out.

Measured, sum of time inside `_choose_k` per render:

| render | before | after |
|---|---:|---:|
| Players | 4.16 s | **2.70 s** |
| TD Insights | 2.99 s | **2.49 s** |

The page totals barely move, and correction 3 above is why: what was removed is
real repeated work, but the headline 2.5 s was never the 60 fits.

---

## TASK 4 — deletions and stale references — ONE HALF DONE, ONE HALF STRUCK

* **Deletions: NOT performed.** See correction 2 — both are live. The roadmap's
  DELETIONS section is struck with the trace and the general lesson.
* **`MARKETING.md`** — the "★ Analytics Hub" feature row now sells
  **Rankings → Spotlight** and describes what actually moved there. Its Rankings
  row also predated the view recut (it named "Team Charts" and "League lab",
  both folded into "League landscape", and did not mention Spotlight or the new
  week picker), so that is updated to the six views the page has.
* **`ML_LAYER_ROADMAP.md`** — the tagging-coverage strip now points at
  `helpers/league_spotlight.py` via Rankings → Spotlight, with a note that the
  entitlement gates moved across verbatim.
* **Left alone deliberately:** `MARKETING.md`'s "Officials Analytics Hub" is the
  Officials page and has nothing to do with the deleted one. The dated handoffs
  (`FULL_APP_REVIEW_2026-07-17`, `MAINTENANCE_BATCH_2026-07-22`,
  `TIER3_HANDOFF`, `COACH_ROADMAP_2026-07-25`) are point-in-time records that
  were accurate when written.
* `hockey_from_id` and `charges.charge_rate_map` untouched, per the roadmap.

---

## TASK 5 — gate the Spotlight cost — DONE

`_intel` ran on arrival for every entitled coach who opened Rankings →
Spotlight. It is a league-wide `player_stat_table` at `min_games=2`, a full event
fetch, RAPM, WAR and the team insight feed — and everything a coach usually comes
to Spotlight for (the awards digest, the risers strip, the game of the season,
Notables) sits above it and is cheap.

Now the header and caption still render — the feature stays visible rather than
hidden — and the mining waits for a **🔎 Mine the league** click. `_intel` keeps
its own `cache_data(ttl=300)`, so one press covers the next five minutes. The
opt-in flag is **per gender**: switching the radio is a different pool and a
second full mine.

Measured, AppTest harness against a snapshot of the live book, nothing else
running, three pairs:

```
ungated   24.65 / 24.42 / 23.84 s
gated     14.29 / 13.99 / 14.44 s
```

**~10.2 s off a cold Spotlight, 42%.**

Correction to the roadmap's "essentially all `_intel`" — instrumented in
process, the view splits:

```
_intel            14.61 s
_notables          2.13 s
_awards            0.06 s
_game_of_season    0.02 s
_risers            0.00 s
page base          7.37 s   <- the score board, tracked pack, class labels
```

The floor under Spotlight is the **page**, not the section. 14 s is where this
view now sits, not the ~2 s the roadmap's framing implies. If you want it lower,
the next cut is the Rankings page base, which every view on that page pays.

---

## SUITES

```
$ python.exe -m pytest tracker/ -q
290 passed, 7 warnings in 17.27s

$ python.exe -u tracker/run_all.py
97 script-style test file(s)

...
ok       test_winning_formula.py  |  46 checks passed.
ok       test_wpa_recal.py  |  OK
ok       test_xa2.py  |  ALL 18 CHECKS PASSED

======================================================================
passed 97   failed 0   timeout 0
```

Baseline on `main` was pytest 258, run_all 98 files. The pytest delta is +32:
23 new `test_resume.py` tests and the 9 in `test_results_season_rollover.py`
that were never running (correction 1). run_all is 98 → 97 files, and the one
that left is `test_results_season_rollover.py` — it moved to pytest, where it
now actually executes instead of being counted as a pass for importing
cleanly. `test_turnover_types.py` deliberately stayed in run_all.

Both suites run clean with nothing else on the box.

---

## ASSUMPTIONS I MADE

Places the roadmap left a decision open, and what I chose. All conservative,
all reversible.

1. **The week picker governs the Overview rankings table only**, not the whole
   page. The roadmap said "beside the season picker" (placement) but not scope,
   and there is no reconstruction of the leaderboards or the tracked views in
   the snapshot table. A banner says so on screen.
2. **The archived board carries the W-L as of that day**, computed with a dated
   scan of the games table. The snapshot rows have rank and rating only, and an
   "as it stood" board carrying today's record is telling two different dates at
   once. It stays a pure read — no engine call.
3. **1b adds a column rather than replacing one** on the Team Dashboard
   schedule (`Rk @` beside `Opp Rk`), so no existing number changes meaning. On
   the Rankings team view, where the rank was *inline in the opponent's name*,
   the chip did change to the at-the-time rank and today's moved to its own
   column — that one was the surface the roadmap actually described.
4. **Upcoming games keep today's rank.** For an unplayed game "the board before
   the game" resolves to the latest saved board, which is staler than the live
   one for no benefit.
5. **1c's default cutoff is a fixed top-25, not the top-25% cut**
   `strength_of_schedule` uses. 25 is what coaches and polls say; the percentage
   cut moves with the size of the pool and is not comparable across genders or
   seasons. The picker offers 10 / 25 / 50.
6. **1c lives under Strength of Schedule** in Résumé & Form rather than on the
   Overview banner. `sos["quality_wins"]` is the naive version and the two had
   to be visibly reconciled rather than left to disagree on separate screens.
7. **The classifier fix is narrow.** Only a TestCase file with no
   `unittest.main()` moves to pytest. The eleven TestCase files that DO call it
   are already running correctly in their own processes, where their
   module-level `APP5_DATA_DIR` redirect is safe in a way it is not under
   collection — moving them would be gratuitous risk for no coverage.
8. **`MIN_SNAPSHOT_GP` left at 5.** Lowering it would resolve most of the 21.5%
   gap in correction 4, but it is a deliberate DB-size decision with its own
   documented reasoning and it changes what `movement` and `risers` report. That
   is a founder call — see "what to do next".

---

## WHAT I DID NOT DO

Per the hard boundaries, and untouched:

* `tools/repair_book.py --apply` — not run. The live book was never written to;
  every measurement in this document is against a `sqlite3.backup` copy under
  `APP5_DATA_DIR`.
* The `UNIQUE` index on `games` (item 3) — blocked on the repair and the
  same-day-rematch ruling.
* The page-level `st.tabs` conversion (item 6) — needs the AST sweep and
  supervision.
* Officials rework (item 8), iPad Mode (item 9).
* No push, no ssh, no deploy. Branch is unmerged.
* No model constant changed. `n_init` stayed at 10 *because* the gate failed.

Also not done, and deliberately: **`scout_notes` and `manual_player_box`**
(0 rows each) are still in the DELETIONS list. After correction 2 I was not
willing to delete anything on a "zero rows / one consumer" claim without
tracing it to a page, and that tracing was not in tonight's scope.

---

## WHAT TO DO NEXT — ranked

1. **Press "Rebuild rating history" for any season you care about.** All three
   new surfaces are empty without it, and every one of them degrades to a
   "press Rebuild" message rather than a zero. The 2025-2026 boards already
   exist; a new season will not.
2. **Decide `MIN_SNAPSHOT_GP`.** At 5, the "beat #6" chip is sparse until
   January (correction 4). At 2 or 3 it would fill in, at a cost in rows and in
   what `movement`/`risers` mean early in a season. Quality wins are unaffected
   either way.
3. **The repair tool and the Yukon-vs-Alva score.** Still yours, still blocking
   item 3.
4. **Spotlight's remaining 14 s is the Rankings page base**, not Spotlight. If
   that view needs to be fast, the work is on the page, and it would make every
   view on that page faster.
5. **Quarter analysis into Insights** (item 4) is now the only untouched
   polish-month item that is pure build with no ruling behind it.

---

## FILES

New:

```
helpers/resume.py            the point-in-time résumé engine
tracker/test_resume.py       23 tests
docs/OVERNIGHT_2026-09-06.md this document
```

Changed:

```
tracker/_test_kinds.py                the classifier hole
pages/5_Rankings.py                   1a week picker + archived board; 1b chip
pages/6_Team_Dashboard.py             1c quality wins; sched ctx gains gender/season
helpers/dashboard/sched.py            1b "Rk @" column
helpers/dashboard/{analyze,insights_deck,insights_tab,player_card,share_tab,team_card}.py
                                      29 season defaults
helpers/archetypes.py                 _choose_k memo (n_init unchanged)
helpers/league_spotlight.py           the miner is a button
MARKETING.md, ML_LAYER_ROADMAP.md     Analytics Hub → Rankings → Spotlight
docs/ROADMAP_2026-09.md               status marks + the struck deletions
```
