# Session prompt — 2026-09-13 (day session)

Paste the block below into a fresh session. Everything it needs to find is in
the repo; it names the files rather than restating them.

---

```
Read docs/THE_BOOK_2026-09.md first — it is the entry point. Then read, in
order: docs/OVERNIGHT_2026-09-12_NIGHT.md (what last night shipped),
docs/LIVE_APP_REVIEW_2026-09-12.md (the fan site, reviewed against production),
and docs/FREEZE_PUNCHLIST_2026-09-09.md (the two ops blockers).

STATE OF THE REPO
- 6 commits on `main`, UNPUSHED: 2624ce9 offline demo launcher · 6f16400 matchup
  back-in-time + walk-forward backtest · b040d9d Input Hub consolidation (all
  five INPUT_HUB_SCRUB steps; pages/11_Setup.py deleted; Box Score Entry is its
  own page) · c6cd75f docs · 06c5b2d Event Editor restructured into _seg tools ·
  0ebf478 two live.hooptracks.com fixes.
- Suites green and both went UP: `python -m pytest -q` = 481 passed,
  `python tracker/run_all.py` = 104/0. Run them with
  %LOCALAPPDATA%\Programs\Python\Python312\python.exe, not the Store shim.
- `python run.py` is now the OFFLINE DEMO (frozen prod book at ~/app5_demo,
  signed in as colbyl.farrar@gmail.com, no network). `python run.py --dev` is
  the old dev behaviour. Do not break either.

RULINGS RECEIVED — treat as settled, do not re-litigate
1. The officiating table on the fan game page STAYS. It is not an officials
   feature — it exists so ASSIGNERS can see in real time whether a ref is being
   a hero, and a lopsided foul split being visible is the POINT, not a side
   effect. Assigners were asked and they like it. Recorded in
   LIVE_APP_REVIEW_2026-09-12.md; do not "fix" it.
2. Class rank is liked and wanted in MORE places, starting with the Rankings
   Overview table. The table is already dense; that density is deliberate.
3. Short team names on the live pages: approved to fix.
4. A fuller pregame fan page: approved to build.

TASK 1 — DEPLOY LAST NIGHT'S WORK (do this first, it is blocking nothing else
but it is the thing that has value today)
  git push
  ssh app5@107.170.27.154 "cd app5 && git pull"
  ssh app5@107.170.27.154 "sudo systemctl restart app5-web"
  # AND the tracker service — live.hooptracks.com will NOT change without it,
  # because both live fixes are in helpers/public_feed.py which the tracker
  # (uvicorn) process imports. Find its unit name on the box and restart it.
No static file changed, so the PWA cache does NOT need a bump this time.
Afterwards, verify on the real site: live.hooptracks.com should show LATEST
FINALS instead of "No games on this date", and live.hooptracks.com/team/1
should read 29-3, not 0-0.

TASK 2 — CLASS RANK ON THE RANKINGS OVERVIEW TABLE
Put the class rank next to the overall rank in the Overview table.
- pages/5_Rankings.py:1040 builds `df` from `ov_rows`, which is
  `[scored[t] for t in ov_tids]` (line ~825) — so the rows ALREADY carry
  `ClassRank` and `ClassOf` (set in helpers/team_ratings.py:794-795). No engine
  work needed, just columns.
- Add it to `_core_cols` AND `_comp_cols` (lines ~1078 and ~1083), immediately
  after "Rank". Render it as its own column — e.g. "Cls Rk" showing `3A #3` or
  `#3 of 74` — with a column_config help string that names the pool, per the
  house convention that a rank states its pool (see memory
  `pctile-pool-convention` and helpers/cards.pctile_bar).
- The class rank is partitioned by STATE + class (team_ratings.py:769), so an
  out-of-state team may have none. Render "—" rather than a bare number.
- The Overview "as of" board branch (the elif at ~1039 vs the asof branch above
  it) is a different frame — check whether the snapshot board can carry it; if
  `rating_snapshots` has no class rank, leave that branch alone and say so.
Acceptance: Rankings → Overview shows both ranks in Core and Composites column
sets; `python tracker/run_all.py` still 104/0.

TASK 3 — SHORT TEAM NAMES ON THE LIVE PAGES
At 375 px, "Claremore (Sequoyah) Girls" truncates to "Claremore (Sequoya…" in
the game hero and the linescore.
- helpers/cards.team_short only strips the " Girls"/" Boys" suffix, which is not
  enough, and the live pages are plain JS that cannot import Python helpers.
- So the short name has to travel in the payload: add a `short` field in
  helpers/public_feed.py wherever a team name crosses the fence
  (state_by_token, scoreboard, team_profile, teams_directory) and use it in
  tracker/static/live.html, live_index.html and live_team.html where space is
  tight. Keep the full name in the <title> and the page header.
- Whatever shortening rule you write, write it ONCE in public_feed and let all
  four payloads call it. Two rules would drift.
- This DOES touch static files, so bump the PWA/service-worker cache
  (tracker/static/sw.js) when you deploy it, and load the pages with a ?bust=
  query when testing locally or the SW serves the old copy.

TASK 4 — A PREGAME FAN PAGE WORTH READING
Today a fan who scans the QR before tip-off gets: a PREGAME badge, 0-0, "No
stats yet", "Nothing logged yet". Give them both teams' records and ranks —
already computed in public_feed.teams_directory() — plus tip-off time and venue
if they are on the game row. Allowlist discipline is absolute: records, ordinal
ranks and class ranks only. No Power, no Rating, no AdjNet, no tags, no names.
Extend tracker/test_public_feed.py's privacy sweep to cover whatever you add.

TASK 5 — DECIDE THE PUBLIC-RANK QUESTION (founder call, do not decide alone)
live.hooptracks.com Teams → Boys currently reads "#1 · #2 · #5 · #6 …": #3 and
#4 are 1-0 out-of-state entries ranked above 24-2 Booker T Washington, then
hidden because the class chips default to the eight OSSAA classes. Rank is
computed over 743 teams; the list shows Oklahoma only. THE BOOK §8.2 (one-game
leaderboards) on the one page with no login in front of it. Three options are
written up in LIVE_APP_REVIEW_2026-09-12.md §3. The founder has said he LIKES
the class rank, which leans toward option 3, but has NOT ruled. Ask before
building.

THEN, IN THIS ORDER, AS TIME ALLOWS
a) THE BOOK §12.7 — the schedule's at-the-time opponent rank, and quality wins
   on the Hall of Fame. helpers/resume.py already does the work (board_as_of,
   day_before, rank_history); this has been called "nearly free" in two
   consecutive overnight docs and is still not done.
b) FREEZE_PUNCHLIST item 6 — 23 games on production still carry season='Current'
   as a literal label (dated 2026-12-08 → 2027-02-16, none tracked). Confirmed
   still true on tonight's snapshot. Confirm auto_season_rollover.py relabels
   them or November opens on an empty schedule.
c) The two ops BLOCKERS in FREEZE_PUNCHLIST §1 and §2 (systemd timers need
   founder sudo; tools/repair_book.py has never been run on production). Both
   need the founder at the keyboard — surface them, do not attempt them.
d) The Event Editor's deeper job, described at the end of
   INPUT_HUB_SCRUB_2026-09-10.md: its filters now govern only the tools they
   apply to, but the page is still five tools, and the scrub thought two of them
   wanted rethinking.

CONSTANTS — MEASURED LAST NIGHT, NOT CHANGED, AND STILL NOT YOURS TO CHANGE
The new walk-forward backtest (War Room → Matchup → "How accurate is this
predictor?") measured predictor.PREGAME_SD = 11.0 against a real 12.61 (girls) /
13.43 (boys), and team_ratings.DEFAULT_HCA = 3.0 against a measured home lean of
+1.78. Underneath the second: games.neutral is set on 3 rows of a 13,383-game
book, so the home bump lands on ~1,500 playoff games played on neutral floors.
Per memory `recal-round2-2026-07-18`, no constant moves without its own gate.
Report, propose, do not adopt. Note also that helpers/model_constants.apply()
must be called before any script that measures the model, or you are measuring
code defaults nobody is running.

HOUSE RULES THAT BIT LAST NIGHT
- Files are CRLF. A str.replace built with "\n" silently matches nothing.
- Any st.tabs → _seg conversion needs tools/seg_leak_sweep.py run over the page
  first; a name one section defined and another read is a NameError once only
  one body runs.
- games has a partial UNIQUE index on the matchup (tracked_by=''), so a test
  that inserts the same pair twice on one date fails on the constraint.
- SEAS.ACTIVE ("Current") has ZERO finished games. Read pages fall back via
  SEAS.default_read_season; write pages must not.
```

---

## Why each task is here

* **1** — nothing from last night is live yet, and the tracker-service restart is
  the step most likely to be skipped.
* **2, 3, 4** — founder-approved on 2026-09-13 in response to the live-app
  review.
* **5** — the one live-app finding deliberately left undecided.
* **a–d** — the standing backlog, ordered by how close each is to done.
