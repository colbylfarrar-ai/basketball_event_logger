You are working on the HoopTracks basketball analytics app (Streamlit + SQLite)
at C:\Users\colby\basketball_event_logger\APP5.0. This session is a BIG OVERVIEW
SWEEP, not a build sprint. Three workstreams, in this order of value:

  A. Audit the Free / Paid / Co-op gating end to end — correctness first.
  B. Raise the rest of the app toward the flagship (Team Dashboard → Insights).
  C. Find the free wins — high value ÷ effort, already-computed-but-unsurfaced.

Read before you start:
  APP5.0/docs/OVERNIGHT_2026-09-06.md   <- last night's build + 4 roadmap corrections
  APP5.0/docs/ROADMAP_2026-09.md        <- polish-month scope, now marked up
  APP5.0/docs/QOL_SURVEY_2026-09-05.md  <- the measurements behind the roadmap
  APP5.0/helpers/entitlement.py         <- READ THE DOCSTRING. It is the spec.

## REPO STATE

`main` is clean and IN SYNC with origin/main at 439684d (the overnight merge).
Branch for this session's work; do not commit to main directly. Nothing is
blocked on a merge.

## ENVIRONMENT — get these wrong and you will waste hours

* Use the PINNED interpreter for everything. The shell's bare `python` sees a
  Store-virtualized shadow copy of AppData and will read the WRONG database:
      C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe
* The live book is %LOCALAPPDATA%\APP5\analytics.db. NEVER write to it. Snapshot
  it and point APP5_DATA_DIR at the copy — the copy MUST be named analytics.db
  inside the directory you pass:
      sqlite3.connect(src).backup(sqlite3.connect(dst))
* Both test suites are disjoint by design (tracker/_test_kinds.py). Run BOTH:
      python.exe -m pytest tracker/ -q         # 290 passed, ~20 s
      python.exe -u tracker/run_all.py         # 97 passed, ~35 min
  Those are the CURRENT baselines (they moved last night — see below). Any drop
  is yours.
* DO NOT export APP5_DATA_DIR when running run_all.py — its modules build their
  own temp DBs and the export poisons them. Export it only for AppTest harnesses.
* run_all buffers; redirect to a file and poll rather than waiting on a pipe.
* Timing runs are only trustworthy with NOTHING else running. A concurrent suite
  inflates every number 2-3x on this box.
* THE SEASON TRAP: SEAS.ACTIVE is "Current" and holds ONE unplayed game. All real
  data is under the "2025-2026" label. Any harness must drive the picker there
  (ta_season / rk_season = "2025-2026") or it renders a healthy-looking empty
  state and proves nothing.
* AppTest render harness: chdir into APP5.0/tracker (a secrets-free cwd bypasses
  auth), then AppTest.from_file(page, default_timeout=1800), seed session_state,
  .run(), assert `not at.exception`. Worked examples:
  tracker/test_insights_layout.py, and the state keys that matter are
      Team Dashboard: ta_team, ta_season, td_view, lab_sub, lab_adv_sub,
                      ins_section
      Rankings:       rk_season, rk_view, rk_asof
  NOTE: a SECOND at.run() on the same AppTest can raise inside Streamlit's own
  widget-state code on pages with multiselects. Time cold runs in fresh
  processes instead of running twice.
* TEST CLASSIFICATION CHANGED LAST NIGHT. A file whose tests live only in a
  `unittest.TestCase` now counts as PYTEST unless it calls `unittest.main()`
  itself. Before the fix such a file was routed to run_all, which "passed" it for
  importing cleanly without executing a single assertion — nine tests had never
  run. If you add a TestCase-style test, do NOT add `unittest.main()` unless you
  genuinely want run_all to own it.

## WORKSTREAM A — the gating audit (do this first, it is correctness)

`helpers/entitlement.py` gates TWO INDEPENDENT AXES and its module docstring is
the authoritative spec — read it before forming any opinion:

  AXIS 1 DEPTH   Free vs Paid. Box score + final results are Free to everyone,
                 always. Tracked play-by-play depth is Paid.
  AXIS 2 SHARING teams.shares_pool, DEFAULT 0 = Solo. RECIPROCAL and binary:
                 share to scout. A program is ONE unit — any coach opting in
                 makes the whole team League-wide.

Two rules that are load-bearing and easy to break by accident:
  * A PAST season is an OPEN ARCHIVE for READS and NOT for WRITES. The bypass
    covers visible_tracked_game_ids / visible_untracked_boxed_game_ids /
    team_visible_tracked_ids / tracked_gate. It deliberately does NOT cover
    can_see_tracked_game_view or the Event Editor's paid check.
  * An EMPTY visible-game set is not the same as None. None = unrestricted;
    an empty tuple/set means "nothing this viewer may aggregate" and must never
    be passed on as a game_ids filter — one layer down an empty filter reads as
    "no scope given" and silently widens to the whole league. There is at least
    one comment in league_spotlight._intel warning about exactly this.

The surface: 77 `ENT.` call sites across 16 files. Densest first —
  pages/9_War_Room.py (14), pages/5_Rankings.py (12), helpers/box_score.py (10),
  pages/2_Game_Tracker.py (7), pages/7_Players.py (6), pages/6_Team_Dashboard.py (5),
  pages/8_Officials.py (3), pages/3_Event_Editor.py (3),
  helpers/dashboard/{team_card,scout_tab}.py (3 each),
  pages/14_Hall_of_Fame.py (2), pages/11_Setup.py (2),
  helpers/dashboard/analyze.py (2), helpers/{stats,seasons}.py (1 each).

Existing guard: tracker/test_entitlement.py (87 checks, SCRIPT-style) and
tracker/test_team_game_pool_rollover.py.

What I want out of this workstream:

  A1. A MATRIX, actually rendered rather than reasoned about. Four viewer
      personas × the surfaces that gate:
          free-solo, free-league-wide, paid-solo, paid-league-wide
      (plus admin/local as the control). For each persona, drive the AppTest
      harness over Team Dashboard's ten views, Rankings' six, War Room, Players,
      Officials and the box score, and record what renders. The harness bypasses
      auth via a secrets-free cwd, so you will need to seed/patch the identity
      dict that helpers.auth.current_user() returns rather than log in — work out
      the least invasive way to do that and WRITE DOWN the method, because the
      matrix is only worth what the seeding is worth.
  A2. LEAKS: anything where a persona sees depth it should not. This is the
      finding that matters most. Check especially the aggregate paths — a
      league-wide chart built from a pool the viewer is not entitled to is a leak
      even when no single team is named.
  A3. FALSE DENIALS: anything where a persona is blocked from something the spec
      says is theirs. Free coaches seeing "upgrade" on box-score-level content,
      or a Paid League-wide coach being told they cannot scout a team, are both
      bugs against the docstring.
  A4. The COLD-START read. A brand-new free coach with one team and zero tracked
      games — what does the app actually look like? Every empty state on the
      path, in order. This is the first impression and nobody has walked it.
  A5. Any gate that is enforced in the PAGE rather than in entitlement.py. Those
      are the ones that drift.

Turn every confirmed A2/A3 finding into a failing test FIRST, then fix. The house
rule is that the test must fail before the fix, not merely pass after, and you
must say that you confirmed it.

## WORKSTREAM B — raise the rest toward the flagship

Team Dashboard → Insights is the benchmark for what a surface should be: depth
without clutter, verdict-first sections, a plain-language read before the table,
lazy sections so a panel costs only when opened. Insights is ~1.0-1.6 s warm per
section and the deck is already fast.

The job is a comparative read, not a rewrite:

  B1. Walk the other major surfaces — Rankings (6 views), War Room, Players,
      Officials, Schedule, Hall of Fame — and for each, name the specific thing
      Insights does that it does not. Be concrete: "no verdict line above the
      table", "four tabs where a coach wants one question answered", "the number
      is there but nothing says whether it is good".
  B2. Rank those gaps by (coach value) ÷ (effort), and say which are one-session
      jobs versus which are real projects.
  B3. Roadmap item 4 — QUARTER ANALYSIS INTO INSIGHTS — is the one untouched
      polish-month item that is pure build with no founder ruling behind it.
      Charts → Quarters has four sub-tabs; the Insights deck has ZERO quarter
      reads except the foul-trouble quarter lines at insights_deep.py:561.
      "We're a third-quarter team" is a sentence every coach says out loud and
      the flagship cannot say it. Adding a metric means METRIC_SECTION,
      METRIC_EVIDENCE and (only with a defensible derivation) PTS_RULES in
      insights_severity.py — test_insights_severity.py fails if a miner emits a
      metric with no section or no evidence destination. Build it if the sweep
      leaves time; otherwise scope it precisely for the next session.

## WORKSTREAM C — the free wins

"Engine done, surface missing" is where this codebase's wins have been, twice
running. Look for:

  C1. Engines that exist and are fully computed but reach no page. There is a
      memory note and a docs map on this ("Insights buried analytics"); verify it
      against the current tree rather than trusting it — last night two roadmap
      claims of the same shape turned out to be wrong in opposite directions.
  C2. helpers/resume.py shipped last night with three surfaces. A fourth is
      nearly free: the SCHEDULE page and the news feed could both carry the
      at-the-time opponent rank, and Hall of Fame could carry quality wins. Cheap
      because the engine and its tests already exist.
  C3. Perf that is a one-liner. Known unprofiled: Scout (11.7 s cold / 3.4 s
      warm, the slowest view left), Hall of Fame (calls score_ratings per season
      label in a LOOP, unmeasured). Measure before proposing.
  C4. Anything the gating audit surfaces as "this is gated but costs nothing to
      make Free and would sell the paid tier".

## HOUSE RULES THAT APPLY TO EVERY TASK

* Test-first for bug fixes. The test must FAIL before the fix. Say that you
  confirmed it.
* MEASURE BEFORE YOU CLAIM. Three of six roadmap items on 2026-09-05, and four of
  five on 2026-09-06, had a different root cause or a wrong magnitude than the
  survey claimed. Reproduce the number yourself before you build on it, and when
  it does not reproduce, say so and show your method — those corrections have
  been the most valuable part of every write-up so far.
* Never claim something passes without pasting the command output.
* Match the surrounding code's comment density and voice. This codebase explains
  WHY at length, including what was tried and rejected. Do the same.
* If a test you did not write starts failing, do not weaken the assertion unless
  you can argue the assertion encoded a bug — and if you do, explain it in the
  commit message.
* Commit in logical chunks with messages that explain the reasoning, not the
  diff. Look at the last thirteen commits for the register.
* No model constant changes without the measured gate (split-half stability + a
  second independent column). `archetypes._choose_k` last night is the worked
  example of a gate that FAILED and what to do about it.

## DO NOT DO

1. DO NOT run `tools/repair_book.py --apply`, or otherwise modify the live book.
   Founder decision; one pair (Yukon vs Alva) has disagreeing scores.
2. DO NOT add the UNIQUE index on `games` (roadmap item 3) — blocked on the
   repair and on a founder ruling about same-day rematches.
3. DO NOT convert the page-level `st.tabs` (roadmap item 6) unattended — it needs
   an AST sweep for cross-tab variable leaks.
4. DO NOT push, deploy, ssh, or touch the droplet without asking.
5. DO NOT merge to main without asking.
6. DO NOT delete anything on a "zero call sites" claim without tracing the
   in-module caller all the way to a page. Two of last night's listed deletions
   were live code reached from the flagship.
7. DO NOT start the officials rework or iPad Mode (roadmap 8 and 9).

## DELIVERABLE

`APP5.0/docs/SWEEP_2026-09-06.md`, structured as:

  * THE GATING MATRIX — personas × surfaces, rendered, with the seeding method
    stated so it can be re-run.
  * LEAKS and FALSE DENIALS — each with a failing test, then the fix.
  * THE COLD-START WALK — what a new free coach actually sees, in order.
  * FLAGSHIP GAP LIST — per surface, ranked by value ÷ effort, one-session jobs
    separated from real projects.
  * FREE WINS — ranked, with the measurement behind each.
  * ANYTHING THE ROADMAP OR THE DOCS GET WRONG. Be as willing to say a premise is
    wrong as to build the thing.
  * WHAT YOU DID NOT FINISH and exactly where you stopped.

Both suite counts pasted. Branch left unmerged unless I say otherwise.
