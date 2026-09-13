You are working unattended overnight on the HoopTracks basketball analytics app
(Streamlit + SQLite) at C:\Users\colby\basketball_event_logger\APP5.0. The founder
is asleep and CANNOT answer questions. If a decision is genuinely ambiguous, pick
the conservative option, WRITE DOWN the assumption, and keep going — never stop
and wait, and never guess at something destructive.

## READ FIRST, IN THIS ORDER

  APP5.0/docs/THE_SICKO_BOOK_2026-09-12.md   <- the governing document for THIS
                                                run. Part IV (§12-§15) is the
                                                plan; §5, §8, §9 are the specs
                                                for TASKS 4-6.
  APP5.0/docs/THE_BOOK_2026-09.md            <- why the app is shaped as it is;
                                                the fourteen rulings (§18) bind
                                                you. §7 is what to protect.
  APP5.0/docs/THE_FREEZE_BOOK_2026-09-12.md  <- what shipped and how it was
                                                measured. §16 is the receipt.

## THE CONSTRAINT THAT DECIDES EVERY TRADE-OFF — AND IT CHANGED

Previous overnight runs were governed by "September is not improve-the-app, it is
remove-every-reason-to-open-a-page-in-anger". **That is now half wrong, and the
reason is new information.**

**The five coaches arriving in October were chosen because they are ALREADY
analytics sickos at the college level** — KenPom / Torvik / Cleaning the Glass /
Synergy readers. They have never had any of it pointed at their own data. They
are not novices being onboarded. They arrive with the reference frame already
installed, they are *comparing*, and **they convert in session one or not at
all.**

So the trade-off is: **surface the depth that already exists.** Not new metrics —
`THE_BOOK`'s rule still holds that every new metric costs forever, and this app's
engines already grade A while its *staging* grades C. Every task below is a
rendering, naming or ordering change over an engine that already runs correctly.

**The freeze is deliberately being broken for this run.** The founder will
re-freeze afterwards. That does NOT license engine changes — see the boundaries.

## STATE

Start from `main`: clean, and **one commit ahead of `origin/main`** — that commit
is the two documents governing this run (`THE_SICKO_BOOK_2026-09-12.md` and this
prompt), committed to main deliberately so you can read them from a fresh branch.
Production still runs `66359ee`, the commit beneath it. Nothing is pushed.

Create ONE branch `overnight-2026-09-13-sicko` and commit to it in small,
reviewable commits. **DO NOT merge to main** — the founder reviews in the morning.

**Measure the baseline before you touch anything, and write both numbers into
the report.** Do not trust a number quoted in a document; the suites have been
re-priced twice and `run_all` is priced to the LOCAL book:

    PYTHONIOENCODING=utf-8 <pinned python> -m pytest -q
    PYTHONIOENCODING=utf-8 <pinned python> tracker/run_all.py

Expect roughly 498 / 107 but confirm. You must not regress whatever you measure.

## ENVIRONMENT — get these wrong and you will waste hours

* **Use the pinned interpreter for everything.** The shell's bare `python` sees a
  Store-virtualized shadow copy of AppData and reads the WRONG database:
      C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe
* **Prefix every command with `PYTHONIOENCODING=utf-8`.** This codebase's output
  is full of em-dashes and box-drawing characters; without it the console raises
  UnicodeEncodeError mid-run and you lose the result, not just the formatting.
* **Two books, and they are different.**
  - `%LOCALAPPDATA%\APP5\analytics.db` — the local dev book. `run_all` is priced
    to THIS one and only reproduces green here. NEVER write to it.
  - `~/app5_prod/analytics.db` — a read-only production snapshot, 63 tracked
    games, already on disk. Point AppTest harnesses at it via
    `os.environ["APP5_DATA_DIR"] = os.path.expanduser("~/app5_prod")`.
  Do NOT refresh the snapshot (it needs ssh — banned below). Do NOT export
  APP5_DATA_DIR when running `run_all.py`; its modules build their own temp DBs
  and the export poisons them.
* **The season trap.** `SEAS.ACTIVE` is "Current" and holds games with ZERO
  tracked. All real data is under the "2025-2026" label. Any harness must seed
  `ta_season = "2025-2026"` or it renders a healthy-looking empty state and
  proves nothing.
* **AppTest harness pattern** (a secrets-free cwd bypasses auth):
      os.chdir(<a dir with no secrets.toml>)
      at = AppTest.from_file(page, default_timeout=1800)
      at.session_state["ta_team"] = 1
      at.session_state["ta_season"] = "2025-2026"
      at.run(); assert not at.exception
* **Persona seeding does NOT survive `require_login`.** Rebind
  `helpers.auth._LOCAL_IDENTITY` — seeding `session_state` alone is silently
  ignored. `tools/freeze_smoke.py` already does this correctly; copy its shape
  rather than inventing one.
* `run_all` buffers; redirect to a file and poll rather than waiting on a pipe.
* Timing runs are only trustworthy with NOTHING else running.

## DO NOT DO (hard boundaries)

1. DO NOT push, deploy, ssh, or touch the droplet in any way.
2. DO NOT merge to main.
3. DO NOT run `tools/repair_book.py --apply` or otherwise modify either book.
4. DO NOT change any model constant without the measured gate the house rules
   require: split-half stability stepped up by Spearman-Brown, plus a second
   independent column agreeing in sign, landing in `reliability.MEASURED`.
   **This explicitly includes `situational.GARBAGE` and `runs.GARBAGE_MARGIN` —
   TASK 7 measures them and changes NOTHING.**
5. DO NOT ship a verdict, badge or threshold on an unmeasured quantity. If you
   cannot measure repeatability, render the number and skip the sentence.
6. DO NOT rename the War Room page. Ruled in `THE_SICKO_BOOK` §13.1: the five are
   trained in person, the name costs nothing in session one, and renaming buys
   discovery for coaches who do not exist yet.
7. DO NOT change any option **value** in `_WR_VIEWS`, `_TD_VIEWS`, or any `_seg`
   option list. Labels may change; values may not. Changing a value breaks
   `wr_view` session state and every existing deep link — the same class of
   failure as the `st.tabs` -> `_seg` conversion that silently broke routing
   *into* sections.
8. DO NOT move any residual engine's output onto the War Room. `THE_SICKO_BOOK`
   §14: a residual only works beside the number it contradicts. The hub composes
   questions; residuals live beside their claim.
9. DO NOT delete any page, view, tab or section. The "things that are just kinda
   there" instinct is uncalibrated and would eat the Officiating Lab, which has a
   standing ruling. Deletions wait for October telemetry.
10. DO NOT bypass any entitlement gate. Hall of Fame took a filter fix, not a
    bypass. Showing a locked door is the goal; opening it is not.
11. DO NOT build the date-range scope control or URL-scope/"copy this view".
    Both are blocked on prerequisites (see §15 "Deferred"): the ~35 caller sites
    that convert empty->None, and the `_seg` deep-link bug respectively.
12. DO NOT add a new page. The plan is promotion, not construction.

## WORK, IN THIS ORDER

### TASK 1 (do this FIRST, read-only, ~30 min) — what does a day-one sicko actually SEE?

Nobody has ever read this, and it should reorder everything below.
`tools/freeze_smoke.py` reports "day-one coach (team with zero tracked games):
15 renders, 0 exceptions". **Zero exceptions is not the same as "an analyst finds
something to chew on."** These five are Paid, so plan gating is open — but the
co-op is **reciprocal**, and on day one they have shared nothing while their own
team has zero tracked games.

Extend `freeze_smoke` (or write a sibling tool) so that for the day-one persona
it reports, per page, not just "did it raise" but:

* how many `empty_state` renders fired, and which ones
* how many entitlement locks fired, and which `lock_reason`
* a rough count of rendered data rows / charts vs. locks+empties

Write the result as a table into the run report. **If the day-one persona is
mostly locks and empty states, say so loudly at the top of the report** — it
means the co-op reciprocity gate, not the staging, is what decides October, and
the founder needs that on the morning read.

Do not fix anything you find here tonight. Report it.

### TASK 2 (the core ask) — promote the War Room's playground

`THE_SICKO_BOOK` §12-§13 is the spec. The finding it rests on: **the analytics
hub already exists and is buried.** `helpers/dashboard/analyze.py` is the
self-serve playground (filter the ~60-column player table, plot any stat against
any other with an OLS trendline, correlate anything, map shots, download CSV) and
it renders at `9_War_Room.py:2226` as the **6th of 7** segments.

**2a — reorder `_WR_VIEWS`.** Current:
`["Lineups", "Matchup", "Season sim", "Bracket", "Defensive assignments",
"Analyze", "Glossary"]`. Target order:

    Lineups -> Analyze -> Defensive assignments -> Matchup -> Season sim
    -> Bracket -> Glossary

**Lineups stays the default.** Hard constraint: never default-land a gated view.
Analyze is co-op-gated; a Paid-but-not-league-wide coach would open the page onto
a lock. Lineups is open to any Paid coach.

Follow the pattern already documented at `6_Team_Dashboard.py:1794` — *only the
label list drives display; the option values are unchanged so session state and
routing stay identical*. Icons are welcome (that comment explains why they help
the segment bar read as primary navigation).

**2b — a deck line under the page title.** `page_chrome("War Room")` at
`9_War_Room.py:51`. One sentence stating the mechanic: everything on this page is
something you change and re-run. Match the house voice; do not write marketing
copy.

**2c — make the gate sell instead of refuse.** The co-op lock is this page's
commercial job and right now it is a message. `_WR_LOCK` at `9_War_Room.py:535`
already resolves `lock_reason(scope="pool")` or `ENT.MSG_COOP_INVITE`.
  * **Show the gated views in the segment bar with a lock glyph — do not hide
    them.** A door you can see is a sell; a door you cannot see is nothing.
  * Opening a locked view shows *what is behind it* — which columns, an example
    question it answers, the size of the pool it would draw on — plus the one
    action that opens it.
  * Never bypass (boundary 10).

**2d — verify a suspicious comment.** `9_War_Room.py:529` reads *"Lineups +
Glossary stay open to any paid coach; the other three gate on league-wide"* —
against a **seven**-view list. Either the comment is stale or two views gate
elsewhere. Determine which and fix the comment (or the gate, if a view is
genuinely ungated that should not be). Report what you found.

**2e — fix a stale docstring.** `helpers/dashboard/analyze.py:6` claims "the same
code powers the standalone page". That page no longer exists; War Room is the
only caller. Correct the docstring. Do NOT restore the page (boundary 12).

### TASK 3 — the percentile-heated table renderer, debuting on Analyze

`THE_SICKO_BOOK` §8. `background_gradient` appears **zero** times in this repo.
A CTG reader scans a page for dark blue and dark red and reads only those cells;
you currently cannot scan a field of teams at all.

Build one renderer and use it. **It must carry `cards.pctile_bar`'s pool
discipline** — read `helpers/cards.py:126` before writing a line. That component
exists because "DRtg 96.1 · 80th pct · elite defense" once meant *second of five*
on screen. A heated cell computed over a 5-team pool is the identical lie in a
different shape:

* colour comes from the percentile **within the rendered pool**
* below `POOL_FLOOR` the column renders neutral (no heat) and states the rank,
  exactly as `pctile_bar` degrades to "2nd of 5"
* the pool size is stated on the table, not assumed

Debut it on Analyze's ~60-column player table — gated page, fewest eyes on a
first version, densest tables in the app. **Do not propagate it to the league
tables tonight**; one proving ground, then the founder decides.

Write a test that a thin pool renders neutral. That test is the point of the
task.

### TASK 4 — the disagreement column, TWO sites only

`THE_SICKO_BOOK` §5. You have **five** residual engines — `deserved`, SMOE,
Pythagorean luck, RAPM, `adj_efficiency` — on five different pages under five
different names, and **not one is framed as a residual.** Savant's power is not
that xBA exists; it is that xBA sits in the same row as BA, every page, every
time. The disagreement *is* the layout.

Ship exactly two, the highest-traffic ones. Resist doing forty.

* **Team header card:** record · Pythagorean record · **luck**
  (`league_analytics.py`; currently only in the Rankings Lab at
  `5_Rankings.py:3300`).
* **Game row:** final margin · deserved margin · **the gap**
  (`deserved.py`; currently only inside the Insights deck at
  `insights_deep.py:756`).

**Render the gap itself**, not two numbers side by side and a reader doing
subtraction. Boundary 5 still applies: if a quantity has no measured
repeatability, render the number and skip the verdict sentence.

Do not touch the player card's FG%/xPPS/SMOE row tonight — it is the third site
and it can wait for review of the first two.

### TASK 5 — "what we refused and why", plus reliability chips

`THE_SICKO_BOOK` §9, mechanic 8. **This is the app's single most credible asset
and no coach can see any of it.** A college analyst has been burned by a black
box; a metric they cannot interrogate is one they will not stake a rotation
change on.

Build a surface — `helpers/faq.py` is its natural home — with short entries:
the claim, the measurement, the verdict. Everything below is already true and
already in the repo or the docs; **do not invent an entry, and cite where each
number comes from**:

* the on/off-offense card, measured at **−0.21**, found unreliable, and the code
  **rewired to gate on RAPM agreement** — a metric killed by evidence
* xPPP forecasting **refused**: shot quality predicts future scoring at r=.176
  while past scoring predicts it at r=.655; the descriptive "deserved result"
  shipped instead
* the quarter axis mostly **refused**: only tempo repeats (SB .596)
* defensive shares measured **non-portable** (SB .17–.64, not .70–.92) because
  the opponent picks the assignment
* the depth-band location term adopted over a shot-kind taxonomy on out-of-sample
  log loss and Brier, floor swept (`stats.py:1439` carries the table)

Then a **reliability chip** beside metrics that have one in `reliability.py` —
including the words **"not yet measured"** where there is none. That phrase will
buy more credibility with a coaching staff than any chart in this app. Do not
fabricate a reliability for a metric that has none.

### TASK 6 — `table_with_export` on every DataFrame

`THE_SICKO_BOOK` §9, mechanic 9. Savant puts a CSV button on every page in the
same place; you have **21 `download_button` sites across ~40 renderable tables**,
and the best tables (the matchup grid, the lineup board, the play-type economics)
have none.

Add `ui.table_with_export(df, name)` and convert call sites to it. Mechanical and
additive — adding a button does not change a table. Convert as many as you can do
*carefully*; a partial sweep with a list of what is left is a better outcome than
a rushed complete one. **Report which sites you converted and which you did not,
and why.**

### TASK 7 (measurement only — change NOTHING) — how much does garbage time move?

`THE_SICKO_BOOK` §2. Cleaning the Glass's entire pitch is exclusion discipline,
and a CTG reader will ask *"do you strip garbage time?"* in the first hour. Right
now there is no answer, and the gap was graded on **direction, not magnitude** —
nobody has measured how much it actually moves.

Two thresholds carry the name today:

    helpers/situational.py:535   GARBAGE = 15          (a scoring split)
    helpers/runs.py:37           GARBAGE_MARGIN = 20   (a 4th-qtr run filter)

`runs.py` genuinely excludes; `situational.py` only splits. **Nothing else does**
— team ratings, player ratings, RAPM, lineups, shot quality, the player-edge
boards and OVERALL are all computed over every possession including a 29-point
fourth quarter.

Measure, read-only, against `~/app5_prod/analytics.db`:

* what share of tracked possessions would be excluded, by each definition
* how far `tracked_ratings` (ORtg / DRtg / NetRtg) moves per team if they were
* how far `OVERALL` moves per player, and the max mover
* whether a win-probability cut (`|WP − 0.5| > 0.47`, which knows the clock)
  behaves differently from a flat margin

**Change no constant and no engine** (boundary 4). Write the finding into the
report AND as an entry in TASK 5's refusals surface, phrased honestly: here is
what we measured, here is what we currently do. That is a complete and honest
answer to the question a CTG reader asks, and it costs nothing in risk.

## WHEN YOU FINISH

1. Run both suites again. **Neither may regress against the baseline you
   measured at the start.** If something regresses and you cannot fix it, revert
   that task's commits and say so.
2. Run `tools/freeze_smoke.py` — 15 pages × 3 personas. **It must stay at 0
   exceptions.** This is the tool that certified the freeze; the founder will
   re-freeze off it.
3. Write `APP5.0/docs/OVERNIGHT_2026-09-13_SICKO.md` with:
   * **TASK 1's day-one persona table at the very top** — it is the finding that
     reorders the next session
   * baseline vs final suite numbers, and freeze_smoke's result
   * per task: what shipped, what did not, and **why not** (the "Not done, and
     why" section of previous overnight reports is the most useful thing in
     them — the founder reads it first)
   * every assumption you made when something was ambiguous
   * anything you found that contradicts `THE_SICKO_BOOK` or `THE_BOOK`. Both
     documents have a retractions section for exactly this reason and being
     wrong in writing is the house convention, not a failure.
4. Leave the branch unmerged.
