You are working unattended overnight on the HoopTracks basketball analytics app
(Streamlit + SQLite) at C:\Users\colby\basketball_event_logger\APP5.0. The founder
is asleep and CANNOT answer questions. If a decision is genuinely ambiguous, pick
the conservative option, WRITE DOWN the assumption, and keep going — never stop
and wait, and never guess at something destructive.

Read these three docs first; they are the full context for this work:
  APP5.0/docs/ROADMAP_2026-09.md            <- your task list, items 1, 5, 7 + deletions
  APP5.0/docs/POLISH_BUILD_2026-09-05.md    <- what shipped tonight and why
  APP5.0/docs/QOL_SURVEY_2026-09-05.md      <- the measurements behind it

Start from `main` (clean, 10 commits ahead of origin, both suites green).
Create ONE branch `overnight-2026-09-06` and commit to it. DO NOT merge to main —
the founder reviews in the morning.

## ENVIRONMENT — get these wrong and you will waste hours

* Use the PINNED interpreter for everything. The shell's bare `python` sees a
  Store-virtualized shadow copy of AppData and will read the WRONG database:
      C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe
* The live book is %LOCALAPPDATA%\APP5\analytics.db. NEVER write to it. Make a
  read-only snapshot and point APP5_DATA_DIR at the copy:
      mkdir <scratch>\data
      # sqlite3 .backup, or Python: sqlite3.connect(src).backup(sqlite3.connect(dst))
      # dst MUST be named analytics.db inside the dir you pass as APP5_DATA_DIR
* Both test suites are disjoint by design (tracker/_test_kinds.py). Run BOTH:
      python.exe -m pytest tracker/ -q                  # 258 passed, ~1 min
      python.exe -u tracker/run_all.py                  # 98 passed, ~40 min
  Baseline on main: pytest 258/258, run_all 98/98. Any drop is yours.
* DO NOT export APP5_DATA_DIR when running run_all.py — its modules build their
  own temp DBs and the export poisons them. Export it only for the AppTest
  timing/render harnesses.
* run_all buffers; redirect to a file and poll rather than waiting on a pipe.
* Timing runs are only trustworthy with NOTHING else running. A concurrent suite
  inflates every number 2-3x on this box.
* The season trap: SEAS.ACTIVE is "Current" and holds ONE unplayed game. All real
  data is under the "2025-2026" label. Any harness must drive the picker there
  (ta_season / rk_season = "2025-2026") or it renders a healthy-looking empty
  state and proves nothing.
* AppTest render harness: chdir into APP5.0/tracker (a secrets-free cwd bypasses
  auth), then AppTest.from_file(page, default_timeout=1800), seed session_state,
  .run(), and assert `not at.exception`. tracker/test_insights_layout.py is the
  worked example.

## DO NOT DO (hard boundaries)

1. DO NOT run `tools/repair_book.py --apply`, or otherwise modify the live book.
   That is a founder decision and one pair has disagreeing scores.
2. DO NOT add the UNIQUE index on `games` (roadmap item 3). It is blocked on the
   repair AND on a founder ruling about same-day rematches.
3. DO NOT convert the page-level `st.tabs` (roadmap item 6). It needs an AST
   sweep for cross-tab variable leaks and supervision.
4. DO NOT push, deploy, ssh, or touch the droplet.
5. DO NOT merge to main.
6. DO NOT change any model constant without the measured gate the house rules
   require (split-half stability + a second independent column).
7. DO NOT start the officials rework or iPad Mode (roadmap 8 and 9).

## WORK, IN THIS ORDER

### TASK 1 (the big one) — point-in-time résumé. Roadmap item 1.

`rating_snapshots` already holds 18 backfilled weekly boards (2025-11-16 ->
2026-03-14, both genders, ~480 teams each, system='score'). It is fully
reconstructed and nothing reads it for any of this. Build the three surfaces.
Put shared logic in a new `helpers/resume.py` (Streamlit-free engine, the house
convention), and keep the render in the pages.

* 1a — Rankings: a WEEK picker beside the season picker that renders the board as
  it stood on any snapshot day. This is a PURE READ of rating_snapshots, no
  engine call, so it must be FASTER than the live board. Default to "Current
  (live)"; the picker only offers days that exist.
* 1b — the opponent's rank GOING INTO the game, on game-log and schedule rows:
  "beat #6 Broken Bow". Resolve against the snapshot day BEFORE the game date.
  9,485 of 9,676 team-games resolve; the 191 that do not are pre-first-snapshot —
  render those with no rank rather than guessing one.
* 1c — quality wins: wins over a team ranked top-N AT THE TIME. Surface on Team
  Dashboard. Default N=25. This is the feature that differentiates: 38 of 51
  teams get a different count than the naive "top-25 today" version.

MUST appear on screen somewhere in 1a/1c: backfilled boards use TODAY's model
constants, not whatever was adopted at the time, so reconstructed history can
disagree with history that accrued live, and backfilled days are worth
regenerating after a recal.

Scope to system='score' only. The 'tracked' system has 1-5 rows/day and cannot
rank yet.

Guard it: a new `tracker/test_resume.py`, pytest-style, hermetic temp DB, with
the autouse APP5_DATA_DIR re-pin fixture (copy the pattern from
tracker/test_results_season_rollover.py — the collection hazard is real). Cover:
the day-before resolution picks the right board; a game before the first snapshot
yields no rank rather than an exception; quality wins counted at-the-time differ
from counted-today on a seeded fixture; an empty snapshot table degrades to "no
history yet" instead of raising.

### TASK 2 — the remaining season defaults. Roadmap item 5.

~25 latent `season="Current"` defaults in helpers/dashboard/*: insights_tab,
player_card, team_card, share_tab, analyze, insights_deck. Convert to
`SEAS_DEFAULT` + `resolve_read_season(season)` exactly as the engine layer now
does — see helpers/team_ratings.py and helpers/seasons.py for the pattern, and
the commit `fix(seasons): the results-side default season survives a rollover`
for the reasoning.

These are render wrappers the pages always pass an explicit season to, so this is
trap-closing, not bug-fixing. Behaviour must be UNCHANGED. Verify by rendering
Team Dashboard (all 10 views) and Rankings before and after and diffing the
rendered markdown character counts — they should match.

### TASK 3 — archetypes._choose_k. Roadmap item 7. GATED.

helpers/archetypes.py:167 fits KMeans for k=4..8 at n_init=10 (50 fits), then
_fit_kmeans does 10 more. 2.5s inside player_ratings._archetype_anchors.

Try n_init=3 plus memoizing k on the matrix fingerprint. THE GATE: the chosen `k`
must be UNCHANGED for both genders on the real book before you adopt it, because
k feeds the archetype taxonomy and therefore the team prior. Write the comparison
out. If k moves at all, REVERT the change, keep the memoization only, and say so
in the handoff.

### TASK 4 — deletions and stale references.

* Delete `team_insights.keys_extra` and `development.project_rest_of_season` —
  both verified to have zero call sites outside their own module. Re-verify with
  a grep before deleting.
* MARKETING.md and ML_LAYER_ROADMAP.md still reference the deleted Analytics Hub.
  Update them to point at Rankings -> Spotlight.
* Do NOT delete `hockey_from_id` (NULL by design, HAST is inert until tagged) or
  `charges.charge_rate_map` (it IS consumed by player_ratings).

### TASK 5 — if time remains: gate the Spotlight cost.

Rankings -> Spotlight is 38.8s cold, essentially all `_intel` (player_stat_table
at min_games=2 + RAPM + the team feed). Put `_intel` behind an opt-in button the
way the Impact Lab gates its heavy three, so the view opens fast and the mining
is a click. Re-measure and report.

## HOUSE RULES THAT APPLY TO EVERY TASK

* Test-first for bug fixes: the test must FAIL before the fix, not merely pass
  after. State that you confirmed it.
* Match the surrounding code's comment density and voice. This codebase explains
  WHY in comments, at length, including what was tried and rejected. Do the same.
* Never claim something passes without pasting the command output.
* If a test you did not write starts failing, do not "fix" it by weakening the
  assertion unless you can argue the assertion encoded a bug. (One such case
  happened tonight — test_seasons.py asserted the rollover trap AS the contract.
  If you do this, explain it in the commit message.)
* Commit in logical chunks with real messages explaining the reasoning, not just
  the change. Look at tonight's six commits for the register.

## DELIVERABLE

Write `APP5.0/docs/OVERNIGHT_2026-09-06.md` covering:
  * what shipped, per task, with the measured before/after
  * both suite counts, pasted
  * every assumption you made where the roadmap was ambiguous
  * anything you found that was NOT on the list — a wrong root cause in the
    roadmap, a new bug, a better approach. Tonight three of six items had a
    different root cause than the survey claimed, and those corrections were the
    most valuable part of the write-up. Be equally willing to say the roadmap
    was wrong.
  * what you did NOT finish and exactly where you stopped

Then STOP. Leave the branch unmerged and unpushed.
