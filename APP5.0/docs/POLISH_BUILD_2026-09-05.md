# Polish build — 2026-09-05, branch `polish-2026-09-05`

Companion to `QOL_SURVEY_2026-09-05.md` (the survey is the "before"; this is what
got built). Founder rulings taken first: **cut the Analytics Hub in full**,
**delete `foul_type`**, **build duties 1-6**.

Six commits, off `main`, **not pushed**:

```
14139e5  fix(cache): one entry point for "data changed", and tell other sessions
e2e00cf  refactor(nav): cut the Analytics Hub, move its own content to Rankings
c98873d  chore(db): retire game_events.foul_type
484c6c4  fix(dedup): stop merge_teams manufacturing duplicate games
6b002b6  fix(seasons): the results-side default season survives a rollover
9dff150  perf(dashboard): cache the Projection and Schedule views
```

---

## Measured result

Team Dashboard, same harness, same book, before → after (seconds):

| view | cold before | cold after | warm before | warm after |
|---|---:|---:|---:|---:|
| **Overview** (default) | 32.93 | **20.70** | 1.31 | 1.28 |
| Insights | 17.59 | 17.99 | 1.24 | **1.06** |
| Scout | 14.19 | **11.73** | 3.25 | 3.42 |
| **Schedule** | 9.35 | **3.34** | 7.43 | **2.80** |
| **Projection** | 6.88 | **6.69** | 6.31 | **1.21** |
| Roster | 2.09 | 1.77 | 1.41 | 1.95 |
| Charts / Lab / Share / Glossary | ~1.2 | ~1.4 | ~1.1 | ~1.2 |

The two views that never cached now cache: **Projection 6.31 → 1.21 s warm**,
**Schedule 7.43 → 2.80 s** (cold 9.35 → 3.34). The page's whole cold cost falls
**32.9 → 20.7 s**, because the box score stopped rendering all nine of its tabs
in order to show one. On the 1 vCPU droplet that is roughly a minute off the
first load.

No view raised an exception, and every view's rendered character count is
unchanged except Schedule (53,505 → 47,923), which is the box score now drawing
one section instead of nine — the intended change, not a loss.

Every Insights section is still 1.0-1.6 s warm; the deck was already fast and
nothing on its path was touched.

**A measurement note worth keeping:** an earlier pass of this table was taken
while `run_all` and `pytest` were running concurrently and every number was
inflated 2-3× (Scout read 15.63 s warm against a 3.25 s baseline). On a 1 vCPU
box that contention is the same shape as the production constraint — but it is
not a code regression, and a timing run on this machine is only trustworthy with
nothing else running.

---

## What each duty actually turned into

Three of the six turned out to have a different root cause than the survey
claimed. Those corrections are the useful part of this document.

### 1 · Cache clears — the perf idea was half right, and it hid a real bug

The survey said 45 calls across 12 files. **Wrong: 34 real calls across 8 pages**
— the rest were comments naming the call. And the scoped-clear proposal was only
half implementable: Streamlit has no scoped global clear, so the honest version
is a single entry point, `ui.clear_data()`.

Building it surfaced **something worth more than the speed**: only the phone
tracker ever moved the cross-process version counters. A DESKTOP write — an Event
Editor correction, a score fixed in Setup, a player transferred in the Input Hub
— cleared only the *writer's* cache. Every other coach signed in kept serving the
old number until their own `ttl=600` happened to lapse.

**A corrected score another coach cannot see for ten minutes is a wrong number on
screen, not a slow one.** `clear_data()` now bumps those counters, and
`clear_data(game_id)` keeps the bump scoped to that game's `(gender, season)`
pool so unrelated sessions keep their warm caches. `clear_settings()` is the
counterpart for preference writes, which had no business destroying 251 cached
functions for everyone on the box because someone changed a theme.

### 2 · Season fallback — and one more live break found while verifying

Built as `seasons.DEFAULT` + `resolve_read_season()`: a third value, distinct
from `ACTIVE` ("Current", meaning literally this season) and `None` (every
season, a documented value on several of these signatures). An explicit
`'Current'` still means Current and still reads empty — a coach who picks the new
season must see the new season, not last year's numbers wearing this year's
label.

Converted the whole engine layer: `team_ratings`, `league_analytics`,
`entitlement`, `team_analytics`, `awards`, `hoopwar`, `hero_ball`,
`adj_efficiency`, `insights_team`, `lineup_projection`. `helpers/dashboard/*` is
deliberately **not** converted — see the follow-up list.

**Found while verifying: `awards.weekly_awards` had the same default**, so "This
week in the league" rendered nothing at all. It renders now — that is what
confirmed the fix end to end.

`test_seasons.py` had one assertion encoding the trap *as the contract* ("after
rollover the new (empty) season has no games for A"). Replaced with the real
contract plus its converse, so the fallback can never quietly swallow a
deliberate choice. `test_results_season_rollover.py` is new and was confirmed to
**fail before the fix**, per the house rule.

### 3 · The uncached views — Schedule was not what the survey said

Projection was as described: 9 functions, zero `@st.cache_data`, 208 SQL
round-trips per rerun.

Schedule was **not**. `sched.py` was almost innocent. The cost was
`render_box_score` — **10.66 s of the view's 10.79 s** — because `box_score.py`
opened nine `st.tabs` and every body ran to show one. Converted to a lazy section
selector, which is safe here in a way a page-level `_seg` conversion is not: the
bodies were already closure functions over state computed above them, so no body
could be leaning on a sibling's variable. Inside Lineups,
`lineups.player_quality` (5.0 s of that tab's 5.5 s) is now fingerprint-keyed
`cache_resource` — it resolves to the game's whole SEASON pool internally, so the
answer was identical for every game in the season and recomputed on every open
anyway.

### 4 · The duplicate games — the importer was innocent

The survey blamed the OSSAA importer. **Wrong.** `ingest()`'s guard checks both
home/away orientations and is sound.

The cause is `ossaa_sync.merge_teams`. It reassigns the dupe team's rows with
`UPDATE OR IGNORE` and then deletes "whatever couldn't move (UNIQUE collision vs
the keeper)". That reasoning holds for `coach_teams` and the rest, which do carry
unique constraints — but **`games` has no unique constraint on the matchup**, so
nothing ever collides, every row moves, and any game the two teams both had on
file survives as two rows under the keeper. It is exactly why seven of the nine
are against out-of-state opponents: those are the teams most likely to have been
created twice under name variants and then merged.

Fixed at the source. `game_dedup` gained the result-row half, with a survivor
rule deliberately different from the double-track one (tracked > more events >
has a score > has a location > lowest id) and a hard refusal to delete any row
carrying events.

### 5 · Analytics Hub — cut, 725 lines

Deleted. Its five unique surfaces live in `helpers/league_spotlight.py`, rendered
from **Rankings → Spotlight**: tagging coverage, the weekly awards digest, the
risers strip, the game of the season, the auto-mined league reads, and Notables.
Every entitlement gate preserved verbatim, including the MULTI-TEAM rule and the
empty-filter trap.

`_game_of_season` also stopped running two queries per game — 86 round-trips over
a 43-game book. Spotlight cold 59.4 → 38.8 s, and unlike the Hub it is an opt-in
lazy view rather than the landing page, so nobody pays it on arrival.

### 6 · `foul_type` — dropped

Migration is guarded twice: the column must be present AND empty. A non-NULL
value would mean someone wired it after all, and a migration does not get to
destroy data it was not told about. Verified on a copy of the live book: column
gone, both indexes on `game_events` kept, all 7,731 events intact,
`integrity_check` ok, `foreign_key_check` clean, second run a no-op.

---

## The repair tool — needs your decision

`tools/repair_book.py` reports and **changes nothing without `--apply`**.

**I did not run it against your live book.** Deleting rows from your season is
your call, not an unattended one. Verified against a copy: 12 findings, `--apply`
fixes the two mechanical ones (game 4's `tracked` flag; the nine duplicates) and
is idempotent on a second run.

```bash
python tools/repair_book.py
```

Two findings are report-only by design — which of two players wearing #4 is wrong
is a roster question with a human answer, and the same-player-in-both-slots
charge (`game_events.id 7101`) wants the Event Editor, where the neighbouring
rows are visible.

**Worth an eyeball before you apply:** the **Yukon vs Alva** pair disagrees on the
score — 43-55 vs 44-53. The tool keeps the row that has a location; you may want
the other one.

---

## Test state

- `pytest tracker/` — **258 passed, 0 failed.** Baseline was 241/242; the delta is
  the 9 new tests plus the previously data-dependent charge failure, which does
  not reproduce against the hermetic temp DBs.
- `tracker/run_all.py` — **98 passed, 0 failed, 0 timeout.**
- The two halves are disjoint by design (`tracker/_test_kinds.py`). Run both —
  `run_all` green is half the tree.

---

## FLAGGED FOR LATER — polish-month candidates, none blocking

Ranked by value. All deliberately not built tonight.

1. **`games` has no unique index on the matchup.** A partial
   `UNIQUE(date, team1_id, team2_id)` would make `merge_teams`' `UPDATE OR IGNORE`
   behave the way its own comment already claims, making this class of duplicate
   *impossible* rather than merely repaired. Needs the existing dups cleared
   first, and needs a ruling on legitimate same-day rematches.
2. **`helpers/dashboard/*` still carries ~25 latent `season="Current"` defaults**
   (`insights_tab`, `player_card`, `team_card`, `share_tab`, `analyze`,
   `insights_deck`). Latent, not live — the pages always pass an explicit season —
   but it is the same trap and it will bite the first caller that forgets.
3. **18 eager `st.tabs` remain**, 4 on Team Dashboard (including `qt1..qt4` at
   `:3407`, which runs all four Quarters bodies every rerun) and 4 on Rankings.
   Same conversion as the box score, but these are page-level: AST-sweep for
   cross-tab variable leaks first.
4. **`archetypes._choose_k` fits KMeans 60 times per call** (k=4..8 × `n_init=10`,
   then 10 more) — 2.5 s inside `player_ratings`. `n_init=3` plus memoizing `k` on
   the matrix fingerprint takes it to ~0.3 s. Gate it: `k` feeds the archetype
   taxonomy and therefore the team prior.
5. **Quarter analysis is still absent from Insights.** Charts has four sub-tabs of
   it; the deck has none. "We're a third-quarter team" is a sentence coaches say
   out loud and the flagship cannot say it. Highest-value remaining import.
6. **Spotlight cold is 38.8 s**, essentially all `_intel` (`player_stat_table` at
   `min_games=2` + RAPM + the team feed). Opt-in and cached, but the first click
   is slow.
7. **Scout is the next slowest view** at 3.4 s warm and 11.7 s cold; nothing
   else is above 2.8 warm.
8. **`_finished_games` applies no dedup**, so results-only ratings would
   double-count any future duplicate exactly as they did these nine. Item 1 is the
   better fix; this is the belt to its braces.
9. **Genuinely dead, safe to delete:** `team_insights.keys_extra`,
   `development.project_rest_of_season` — zero call sites outside their own module.
10. **Receipts (257k chars) and Who's helping (214k)** are ~3× the sections around
    them. Not a cap — the rank-never-hide law is regression-tested and should stay
    — but they may want internal structure. A human eye, not a change.
11. **The officials rating rework** and **iPad Mode (N4)** remain the standing
    headline items. N4 is now unblocked: the tablet layout reached `main`.

## Corrections to two memory notes

- The **buried-analytics** map lists the shot map and the matchup grid as "still
  not on Insights". Both are there now (`insights_tab.py:747` / `:1151` and
  `:1192`), and `charges.charge_rate_map` is no longer dead either —
  `player_ratings` consumes it. Quarter analysis is the one real gap left.
- The **local suite baseline** note says run_all is 93/95 with two data-dependent
  failures. The counts have moved (98 script-style files, 258 pytest tests);
  worth re-pinning after this branch lands.
