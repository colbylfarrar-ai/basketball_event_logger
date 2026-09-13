# Overnight run — 2026-09-13 · the sicko layer

Branch `overnight-2026-09-13-sicko`, **unmerged**, 10 commits on top of
`ef4481b`. Production still runs `66359ee`. Nothing pushed, nothing deployed, no
ssh, neither book modified, no engine constant touched.

Governed by `THE_SICKO_BOOK_2026-09-12.md` §12–§15, inside `THE_BOOK_2026-09.md`
§18's fourteen rulings.

---

## Suites — nothing regressed

| suite | baseline, measured on this branch before anything moved | final |
|---|---|---|
| `pytest -q` | **498 passed** | **541 passed** |
| `tracker/run_all.py` | **107 passed · 0 failed · 0 timeout** | **107 passed · 0 failed · 0 timeout** |
| `tools/freeze_smoke.py` | 45 renders / 0 exceptions | **45 renders · 0 raised · 0 thin** |

Both baselines landed exactly where the prompt predicted. `run_all` was run
WITHOUT `APP5_DATA_DIR` exported, against `%LOCALAPPDATA%\APP5`, per its own
contract; every AppTest harness and measurement tool was pointed at
`~/app5_prod`.

pytest RISES by 43 because this run added two test files —
`tracker/test_heat_table.py` (11) and `tracker/test_refusals.py` (24) — and
eight cases to `tracker/test_lineup_picker.py` for the day-one fix.
`tracker/_test_kinds.script_files()` still returns 107, so `run_all`'s
denominator is unchanged.

### The commits

```
1c9d3fa polish(export): the button goes under the table, everywhere
90bdb40 fix(war room): chunk the pool-size count past SQLite parameter limit
992f7c4 polish(analyze): the caption follows the grid mode
d19eca7 feat(export): the Hall of Fame's record boards, and the defenders-allowed table
a20d972 fix(team card): say that the Pythagorean saturates
6b3145f feat(ui): ui.table_with_export / export_button, and a careful partial sweep
bc6180e feat(faq,reliability): publish what we measured and refused
84f5d6e feat(residuals): the disagreement, staged beside the number it contradicts
ef4a2fc feat(ui): a table you scan, with pctile_bar's pool discipline
6bca0f7 feat(war room): promote the playground, and make the lock a door
```

---


## TASK 1 — what a day-one sicko actually sees, and it is not what the book feared

`tools/dayone_read.py`, read-only against `~/app5_prod` (63 tracked games), the
`2025-2026` label. Three personas × 15 pages = **45 renders, 0 exceptions**,
which agrees with `freeze_smoke`. The new part is what is *on* those screens.

The day-one persona is **team 64, Lincoln Christian Girls — 35 games on the
schedule, all finished, ZERO tracked**, on a Paid plan and NOT in the co-op.
That combination is what every October coach is in week one, and it is the only
one that separates "the app has no data" from "*this coach* has no data".

| persona | data elements | charts | dead ends | **locks shown** | pages with nothing to read |
|---|---:|---:|---:|---:|---:|
| **dayone** (own team untracked, solo) | 65 | 40 | 3 | **0** | 6 of 15 |
| **dayone_coop** (same coach, co-op ON) | 65 | 40 | 3 | **0** | 6 of 15 |
| admin (26 tracked games, co-op ON) | 81 | 44 | 1 | **0** | 4 of 15 |

### The headline, and it is a ruling rather than a bug

**Not one entitlement lock fires anywhere in the app, for any persona.** And
`dayone` and `dayone_coop` are **byte-identical on every single page** — the
co-op flag changes nothing.

The reason is `THE_BOOK` §18's own ruling: *give away last season*. Every game in
this book lives under `2025-2026`, which is a PAST season, so
`entitlement.lock_reason` returns `None` on every surface and `_is_past_season`
opens the co-op gate everywhere. The day-one coach sees **80% of what the founder
sees** (65 data elements against 81) on day one, with nothing shared.

**So the sicko book's worry is inverted, and the commercial problem is the
opposite of the one it named.** A day-one analyst does NOT land on a wall of
locks. They land on a nearly complete product they did not pay for the depth of.
The co-op lock — this app's whole reciprocity mechanic, and the thing TASK 2c
spent the night turning into a sell — **is commercially inert on this book and
cannot be reached at all.** I had to force `SEAS.is_current` to return True just
to render it for verification.

That is not an argument to reverse the archive ruling. It IS the thing to know
before October: **the co-op gate has nothing to sell until the 2026-2027 season
has tracked games in it.** Every lock in the app goes live on the day the first
new-season game is tracked, and not one hour before — which means the five
coaches will meet the *ungated* product in training and the *gated* one in
November, and nobody has seen that transition.

### The two dead ends that are real

Of the six pages with nothing to read, four are input/config surfaces that were
never reads (`10_Whiteboard`, `12_Settings`, `13_OSSAA_Import`,
`16_Box_Score_Entry`). `15_FAQ` counts zero only because the tool counts
dataframes, tables, metrics and charts, and the FAQ is expanders and prose — it
renders 18k characters. Two are real:

**1 · `6_Team_Dashboard` — the coach's OWN team page is empty.** 0 data
elements, 2 charts, and the honest note *"No **tracked** games for this team yet"*.
This is correct behaviour and it is also the first page a coach opens about
themselves.

**2 · `9_War_Room` renders NOTHING for a day-one coach — including the view
this run just promoted.** 0 data, 0 charts, one empty state: *"Not enough tracked
games yet"*.

**FIXED after the run, and the first diagnosis in this document was wrong.**
Both the wrong answer and the right one are kept here, because the wrong one is
the more useful half: it is what a plausible reading of the code produces, and
it survived writing down.

*What this report first said.* `lineup_projection.pickable_teams` always offers
the viewer's own team and puts it first *so the picker opens on it* — a
Streamlit selectbox lands on index 0 — so a day-one coach opens the Creator on
a team with no tracked players while the tracked league sits one click away in
the same dropdown. The proposed fix was to stop leading with an empty own team.

*What was actually wrong.* That reading is coherent and it is not what was
happening. Implementing it changed the measurement by nothing at all — still 0
data, 0 charts. The binding constraint was one line further down the page:

```
9_War_Room.py:566   _wr_league_wide = True if not _is_cur_season else viewer_is_league_wide(...)
9_War_Room.py:1688  _li_any         = ENT.viewer_is_league_wide(_li)          # <- the bug
```

The page resolves "is this viewer league-wide" **twice**, and only the first one
knows that a PAST season is an open archive. So the Lineup Creator — the
sub-view that opens by default — took the solo branch of `pickable_teams` and
offered a day-one coach **only their own team**, on a season where the rest of
the page was already handing everyone the whole league. Rotation optimizer and
Compare, which go through `_wr_team_pick`, read `_wr_league_wide` and behaved
correctly. Two pickers, one page, one question, two answers.

This is the same defect `entitlement.paid_or_open_archive` was written to kill —
three page-level stops called `has_paid_plan` bare and hard-stopped Free on a
past season — appearing a fourth time, one level down. Nobody decided it either.

*The fix, and what it measures.* `_li_any` now reads `_wr_league_wide` instead of
re-deriving it. Measured with the same tool that found it:

| `9_War_Room.py`, day-one persona | before | after |
|---|---:|---:|
| data elements | 0 | **6** |
| charts | 0 | **1** |
| dead ends | 1 | **0** |
| Team options in the Creator (archived season) | 1 | **22** |
| Team options in the Creator (LIVE season, solo) | 1 | **1** |

The last row is the one that matters for the gate: on a live season nothing
moved. A solo coach still builds only their own team, which is the ruling.

Shipped with it, because the first diagnosis was not *wrong* so much as
*incomplete*: `lineup_projection.default_pick_index` now answers "where does the
picker LAND" separately from "what is in the list". The list keeps its rule —
own team first, always, so a coach can find their own program — and the landing
goes to the first option that can actually build. Without it, a coach whose own
team is empty but who IS league-wide would still have opened on nothing.

Guarded by `tracker/test_lineup_picker.py::test_j`, a static assert that the
War Room resolves league-wide exactly once. That failure is invisible at runtime
until somebody opens an archived season as a solo coach, which is nobody until
October.

**None of this reverses "Lineups stays the default"** — Analyze is co-op-gated
and default-landing a gated view is still the worse failure. It removes the
reason the default was empty.

### What the instrumentation cost to get right

Two traps, both hit while writing the tool, both recorded in its docstring:

* **A lock CONSULTED is not a lock SHOWN.** `9_War_Room.py:535` resolves
  `_WR_LOCK` at page top on every run and displays it inside three `if`
  branches. Counting `lock_reason` returns over-reports what a coach sees, so
  `locks` is counted off the RENDERED TEXT and the call count is kept beside it.
* **Not every dead end is an `empty_state`.** The branded component is the
  instrumented funnel (`ui.py:730`), but plenty of surfaces say "no tracked
  games" through a bare `st.info`. Those are counted separately as `soft`, and
  they are dead ends the `empty_hit` telemetry will never see either — which
  matters, because October's delete-on-counters plan reads that telemetry.



---


## What shipped

### TASK 2 — the War Room's playground is now second, not sixth

`6bca0f7`. The finding the whole plan rests on held up on inspection:
`helpers/dashboard/analyze.py` filters the full ~60-column player table, plots
any stat against any other with an OLS trendline, correlates anything and maps
shots — and it rendered **sixth of seven**, behind two Monte-Carlo simulators
and a bracket.

**2a · reorder.** `_WR_VIEWS` is now Lineups → Analyze → Defensive assignments →
Matchup → Season sim → Bracket → Glossary. **Every option value is
byte-identical**; only the list order and the `format_func` labels moved, so
`wr_view` session state and every existing deep link resolve exactly as they did
(the `6_Team_Dashboard.py:1794` pattern). **Lineups stays the default** —
Analyze is co-op-gated and default-landing a Paid-but-solo coach on a degraded
view is worse than any ordering buys back.

**2b · deck line.** The old `lab_hero` sub listed the features. It now states
the mechanic: *"Everything on this page is something you change and re-run:
build a five, swap a defender, replay the season, project any matchup, or take
the whole stat table apart yourself."* An analyst already knows what a matchup
projection is; what a page named after a room does not tell them is that they
are allowed to drive it.

**2c · the lock sells.** `st.info(_WR_LOCK)` at three sites became
`_wr_locked(view)`, which renders, in this order: a locked header, **what is
behind the door**, **a question it answers**, **the real size of the pool it
would draw on** — counted live off `games.in_pool` through
`ENT.pooled_game_ids`, so it cannot overstate — and then the existing
`MSG_COOP_INVITE`. Gated views keep a 🔒 glyph in the bar instead of
disappearing from it. Nothing is bypassed; the view still does not run.
Verified rendering on all three views (header, pool chip, question, invite).

An honest zero is handled: with nothing in the pool it says *"you would be first
in"* rather than advertising an empty room.

**2d · the suspicious comment was STALE, not wrong, and the audit found one
thing.** The comment counted five views against a seven-view list because it
predates the last two. The audited map is now in the file:

| view | gate |
|---|---|
| Lineups | open to any Paid coach; `_wr_team_pick` narrows the TEAM list instead |
| Glossary | open — definitions are not data |
| Matchup / Season sim / Bracket | hard-gated on `_wr_league_wide` — the "other three" |
| Analyze | gated inside `analyze.py:100`, and it **degrades** rather than refusing |
| Defensive assignments | **no view-level gate** — it gates per-opponent instead |

Two findings worth the founder's eye:

* **Analyze carries no padlock, deliberately.** Its gate hands a solo coach the
  box-score columns and withholds the tracked ones. A padlock on a door that
  opens would be a lie, and §13.3's argument is that a visible door is a sell —
  a *false* door is worse than none.
* **Defensive assignments is not ungated; it is gated one level down**, at
  `can_rate = _can_team(_id, opp)` inside `_render_planner`. An un-entitled coach
  still opens the planner, assigns their own five, and plans off their own
  hand-entered Scout intel instead of the opponent's rated players. That is the
  better design — the view works with no opponent data at all — and I left it.
  **No gate was added or removed anywhere tonight.**

**2e · the stale docstring** in `analyze.py` pointed at a standalone page that
died in the Input Hub consolidation. Corrected, with a note not to restore it.

### TASK 3 — `ui.heat_table`, and the pool discipline is the feature

`ef4a2fc`. `background_gradient` appeared **zero** times in this repo, so a coach
comparing twelve teams read forty numbers instead of noticing two colours.

The renderer carries `cards.pctile_bar`'s whole discipline, because a heated cell
over five teams is the same lie in a different shape:

* colour is the percentile **within the rendered rows**, and the pool size is
  stated under the table
* **below `POOL_FLOOR` nothing is coloured at all**, and the caption says why —
  over five rows the sort order *is* the rank
* average is left uncoloured, so what the eye catches is the outliers
* a constant column paints nothing — there is no order to draw

`pool_n` defaults to the rows on screen, which is the honest default: a coach who
filtered 240 players down to six gets the thin-pool treatment, and should.

Direction is a **curated** set (`ui.HEAT_LOWER_BETTER`) rather than parsed out of
the glossary's prose, which classifies *Consistency* (low volatility ranks high)
as lower-is-better and would paint the most consistent team red. `HEAT_NEVER`
carries the **direction-free** columns as well as the identity ones —
`ShotRating` is shot DIFFICULTY, and `USG%` and the shot-diet shares describe
what a player does rather than how well. Heat asserts a direction; those do not
have one.

Debuts on Analyze's stat grid behind a **Filter / Heat map** switch (AgGrid
cannot carry a pandas Styler, so it is a switch and not one grid).
**Not propagated to the league tables.** One proving ground, then a decision.

`tracker/test_heat_table.py` — 11 tests, and the thin-pool assert is the point of
the file.

### TASK 4 — the disagreement column, exactly two sites

`84f5d6e`. Five residual engines on five pages under five names and not one
framed as a residual.

* **Team header** (`team_card._banner_html`, the ONE renderer every team-scoped
  page draws): `record 29-3 · scoring says 32.0-0.0 · −3.0 W`. Results-math, so
  Free-safe beside a record that is also results-math — no gate to resolve and
  no tracked depth in it. Floored at 6 games with a real margin.
* **Game row** (Team Dashboard → Schedule): `Margin · Deserved · Gap`, blank for
  untracked games, and both columns drop out entirely when a season has none.

**The gap is what is rendered**, not two numbers with the subtraction left to the
reader.

**One correctness catch worth naming.** The first version scoped the deserved
pass off `ctx.log`'s `tracked` flag. That is wrong: the game log is box-score
level and deliberately **unfiltered** (Free sees every result), while
`bundle["tracked_ids"]` is the same list after `team_bundle` applies the AXIS-2
read filter. Taking the flag off the log would have leaked a possession-level
read past the co-op gate on a column nobody would think to check. It reads
`bundle["tracked_ids"]`.

**Cost:** `deserved.game_ledgers` over one team's 26 tracked games measures
**0.14 s** on the prod snapshot, cached at 600 s on the game-id tuple. The
Schedule view is one of the cheap ones and stays that way.

**No verdict sentence on either**, per boundary 5. `reliability.MEASURED` holds
the decomposition's DESCRIPTIVE agreement (`xmargin_picks_winner` = .731, 38 of
52 out of sample) and holds nothing at all about whether a close-game record
repeats. Both numbers ship; neither sentence does.

The player card's FG% / xPPS / SMOE row is the third site and is untouched,
pending review of these two.

### TASK 5 — "what we measured and refused", plus reliability chips

`bc6180e`. Six entries in `faq.REFUSALS`, each in a claim / measurement /
verdict shape and each citing the file that computes it. Nothing invented; every
number was read out of the repo and checked:

| entry | the number | source |
|---|---|---|
| on/off offense | r −0.096, **SB −0.21** — killed, rewired to gate on ORAPM agreement | `MEASURED ("player","onoff_off")` · `insights.py:930` |
| xPPP forecasting | quality predicts future scoring at **.176**, past scoring at **.655** — refused | `reliability.py` SHOT QUALITY block |
| the quarter axis | tempo **SB .596** ships; eFG% **−0.135** and turnovers **.082** refused | `MEASURED ("team","quarter_*")` |
| defensive shares | **SB .17–.64** against .70–.92, because the OPPONENT picks the assignment | `MEASURED_DEFENDER_NOTE` |
| the depth-band term | the proposed taxonomy measured **worse** than the zone it would have replaced | `stats.py:1439` |
| garbage time | TASK 7's table, published and NOT applied | `tools/measure_garbage.py` |

Rendered at the **top** of `15_FAQ.py`, and rendered **even when the Doc sync
fails** — it is code, not a fetch, and the laptop with no connection is a gym.

**The reliability chip.** `reliability.STAT_RELIABILITY` joins a glossary
abbreviation to a measured read, so a chip rides **every `ui.stat_help` popover
in the app from one site**. Anything unmapped resolves to **"not yet
measured"** — which is the sentence no competitor prints, and is true.
`glossary_key` (the multi-stat popover) chips only the MEASURED ones on purpose:
twelve "not yet measured"s at once is noise the eye learns to skip, which costs
the phrase exactly the weight it is there to carry.

`tracker/test_refusals.py` — 24 tests: every cited file exists, every cited
`MEASURED` key is real, and **every reliability quoted in prose still matches the
table**. That last one is what catches the real regression: re-measuring a metric
updates `MEASURED` and leaves the prose behind, and prose that disagrees with the
measurement is worse than no surface at all.

### TASK 6 — `table_with_export` / `export_button`, a careful partial sweep

`6b3145f`, `d19eca7`. Two functions, and the second one is what makes a sweep
possible without damage. A real pass over these tables runs into AgGrid grids,
heated grids and hand-built `column_config` (LinkColumns, ProgressColumns,
per-column help) — **swapping those renderers to gain a button would trade a
real feature for a button**, so the button goes to them instead.

**Converted (18 sites, chosen for leverage rather than count):**

| where | table |
|---|---|
| War Room | the matchup's margin breakdown · season-sim board · bracket odds · lineup Compare board · projected unit line |
| Rankings | four-factors grid · excitement board · **both** play-type economics boards |
| Team Dashboard | defender × shooter matchup grid · four-factor pull · possession-length economics · the full schedule |
| player_edge | **every board at once** — `_render_boards` is the single renderer behind the whole edge surface |
| Hall of Fame | **every record board at once** — `_board` is the single renderer, and the clean `table_with_export` convert |
| scout_tab | the set-vs-scheme matrix |
| scout_deep | the defenders-allowed table |
| analyze | the stat grid (converted from its bare `download_button`) |

Three of the named gaps are closed: the matchup grid, the lineup board and the
play-type economics all had none.

### TASK 7 — garbage time, measured and NOT applied

`tools/measure_garbage.py`, read-only against the prod snapshot. **No constant
and no engine changed.** 43 tracked girls' games, 5,510 possessions.

| definition | possessions excluded | median ΔNetRtg | mean ΔOVERALL | biggest mover |
|---|---:|---:|---:|---:|
| `situational.GARBAGE = 15`, any quarter | **38.6%** | 5.06 /100 | 2.27 | −12.9 |
| `runs.GARBAGE_MARGIN = 20`, 4th quarter | 12.5% | 2.73 /100 | 1.10 | −7.2 |
| win probability past 97% (`\|WP−.5\| > .47`) | 39.2% | **1.96 /100** | 2.28 | −12.4 |

**The third row is the finding.** The clock-aware cut throws away MORE
possessions than the flat 15-point rule and moves the ratings **less than half as
far**. The two rules disagree on 648 events (Jaccard .80): **233 the margin rule
discards from games that were still live**, and **415 it keeps from games that
were already over**. A clock-blind margin rule is wrong in both directions at
once — 16 down with nine minutes left is a live game, 12 down with forty seconds
is not.

**Recommendation, for the founder and not for tonight:** if exclusion is ever
adopted it should be the win-probability cut and neither margin constant, and it
wants a full walk-forward gate. A 5-points-per-100 shift on the most-read number
in the product is not a quiet change three weeks before training.

**Two measurement notes, so this is re-testable rather than quotable.**

1. **The team half is exact.** `stats.aggregate_player_boxes` takes an `events`
   list, so the with/without runs are the identical estimator over two event
   sets. A **200-possession floor** is applied: 6 of 22 teams clear it, and the
   other 16 appear in one or two tracked games as somebody else's opponent,
   where only the tracking side is fully logged. Without that floor the headline
   mean was **16.71** and was set entirely by teams with fragments of a box
   score — the `thin-books-inflate-plain-z` failure in a new costume.
2. **The player half is a LOWER bound.** `player_stat_table` has no `events`
   seam, so the tool rebinds `stats.fetch_events` for the duration.
   `stats.py:1944` counts a player's floor share with its own
   `SELECT COUNT(DISTINCT ge.id)` and escapes that rebinding, so on-court share
   stays computed over all events in both runs.

---

## Verification of the surfaces `freeze_smoke` cannot reach

`freeze_smoke` renders each page's DEFAULT view, which for the War Room is
Lineups — so it certifies none of tonight's new surfaces. Each was driven by
hand against the production snapshot, and all nine cases pass:

| surface | driven as | asserted on screen |
|---|---|---|
| Analyze, promoted to 2nd | admin, `wr_view=Analyze` | the playground renders |
| the heated grid | admin, `dx_gridmode=Heat map` | *"Colour is each column's percentile within these N players"* + the mode-aware caption |
| Defensive assignments, 3rd | admin | *"who guards whom"* |
| the deck line | admin, default view | *"something you change and re-run"* |
| the lock-as-sell ×3 | solo coach, forced live | 🔒 header · pool chip · the question · `MSG_COOP_INVITE` |
| the deserved columns | admin, `td_view=Schedule` | *"scoring says"* · `Deserved` · *"the possessions earned"* |
| the refusals surface | admin, FAQ | the section header and every Verdict |
| the reliability chips | unit-driven through `ui.stat_help` | `TS%` → **"not yet measured"**; `PF` → *Directional (r = +0.68)*; `xPPS` → *Early (r = +0.48)* |

Two things the harness had to do that a normal smoke does not, both worth
knowing before anyone re-runs it:

* **Read untruncated element values.** `freeze_smoke._text` caps each element at
  400 characters and the team banner's residual line sits past that, so the
  first pass reported a miss on a line that was rendering perfectly.
* **Force `seasons.is_current` for the lock cases.** On this book every game is
  under the archived label, so the co-op gate is open everywhere and the lock is
  otherwise unreachable — which is TASK 1's finding, arriving a second time from
  a different direction.



---


## Not done, and why

**The player card's FG% · xPPS · SMOE row (TASK 4's third site).** The prompt
said not to, and I did not. Two sites shipped; review them before the third.

**Heat propagated to the league tables (TASK 3).** The prompt said one proving
ground. `ui.heat_table` is used at exactly one call site. The Rankings board and
the four-factors grid are the obvious next two and they are a founder decision,
not a sweep — heating a 696-team results-math board and a 22-team tracked board
with the same component means two very different claims in one visual language.

**Most of the `st.dataframe` sites (TASK 6).** 18 converted out of 143 calls.
The honest accounting: roughly 90 of those 143 are single-row
`pd.DataFrame([{...}])` summary strips, and a CSV of one row is not data
liberation. Of the genuinely multi-row tables left:

| file | left | why not tonight |
|---|---:|---|
| `helpers/box_score.py` | ~8 | the box score already has two exports; the rest are per-quarter fragments of the same game |
| `helpers/dashboard/player_card.py` | ~6 | four surfaces share this renderer (`THE_BOOK` §4's fluency problem) — converting it without settling that is how a fifth variant is born |
| `helpers/dashboard/scout_tab.py` | 5 | the on-screen twin of the printable scout sheet (`printables-match-their-screen`); a download button under a four-row quarter split is clutter on a curated hand-out |
| `helpers/dashboard/scout_deep.py` | 3 | frames built inline inside the render call; each needs a hoist, and I ran out of leverage before I ran out of night |
| `pages/6_Team_Dashboard.py` | ~10 | the remaining ones are zone/quarter/creation strips |
| `pages/7_Players.py` | ~7 | already has one export; the leaderboards go through `player_edge`, which is now converted |

**The date-range scope control and URL scope / "copy this view"** — boundary 11.
Both are blocked on prerequisites (the ~35 caller sites that convert empty→None,
and the `_seg` deep-link bug) and neither was touched.

**Any engine constant.** `situational.GARBAGE`, `runs.GARBAGE_MARGIN`,
`PYTHAG_EXP` and everything else are byte-identical to `ef4481b`. TASK 7
measured and changed nothing, which was the assignment.

~~**`pickable_teams`' own-team-first behaviour**~~ — **DONE after the run, on
request, and the diagnosis above it was wrong.** The cause was a second,
archive-blind resolution of `viewer_is_league_wide` at `9_War_Room.py:1688`, not
the option ordering. See the corrected TASK 1 section; the day-one War Room now
measures 6 data elements and 1 chart where it measured nothing, and the live
season gate is unchanged.

---

## Assumptions, where something was genuinely ambiguous

1. **Analyze carries no lock glyph.** §13.3 says show gated views with a lock.
   Analyze's gate *degrades* (box columns render, tracked columns do not) rather
   than refusing, so a padlock would say "you cannot open this" about a door that
   opens. I marked only the three hard-gated views and wrote the reasoning into
   the file. If the founder wants a half-lock affordance, `_WR_GATED` is one line.

2. **`faq.py` holds the refusals data.** The prompt named it as the natural home.
   It is a Google-Doc *sync* module, which is a slightly odd roommate — but it is
   already the "explain the app to a coach" layer, it is already Streamlit-free,
   and `15_FAQ.py` is already its renderer, so nothing needed a new page
   (boundary 12). The two halves share a file and no code.

3. **`glossary_key` chips only MEASURED stats; `stat_help` chips everything.**
   The instruction was to print "not yet measured" where there is none. Printing
   it against twelve columns at once turns a disclosure into wallpaper. The
   single-stat popover — where a coach asking about one number actually looks —
   prints it every time.

4. **The heat direction set is curated, not derived.** Parsing the glossary's
   `how` prose classifies *Consistency* as lower-is-better, which would paint the
   most consistent team red. 12 lower-better stats and a documented list of
   direction-FREE ones beat a clever parser that is silently wrong on a sign.

5. **A 200-possession floor on TASK 7's team table.** Unfloored, the headline
   mean |ΔNetRtg| was 16.71 and was set entirely by teams appearing in one
   tracked game as somebody else's opponent, where only the tracking side is
   logged. The floored median (5.06) is the number I would defend.

6. **`_deserved_rows` reads `bundle["tracked_ids"]`, not `ctx.log`.** Not really
   ambiguous once seen, but it was a live leak in the first draft and is worth
   the founder knowing the column is gate-correct.

7. **The Pythagorean saturation note is a tooltip, not a formula change.** 29-3
   with a wide enough margin expects 32.0-0.0. That is Pythagorean behaving
   normally at HS blowout margins and the Rankings Lab has printed the same
   number all along. Changing `PYTHAG_EXP` would need the measured gate
   (boundary 4), so the tooltip says what is happening instead.

---

## Contradictions, corrections and things worth arguing with

**1 · `THE_SICKO_BOOK` §15's closing question is answered, and the answer
inverts its premise.** It asks whether a day-one sicko lands on locks and empty
states, and says *"if so, every item above is decoration."* Measured: **zero
locks fire anywhere in the app, for any persona, and the co-op flag changes
nothing at all.** The archive ruling gives a brand-new coach 80% of the founder's
product on day one. The items above are not decoration — but the reciprocity
mechanic they were partly built to sell is inert until the new season has tracked
games, and that transition has never been seen by anyone.

**2 · `THE_SICKO_BOOK` §13.3's "verify the comment at `9_War_Room.py:529`"
resolves as STALE rather than as a gate defect.** The comment predates two views.
The audit's actual finding is elsewhere: **Defensive assignments has no
view-level gate**, and that is correct — it gates per-opponent inside
`_render_planner` and degrades to hand-entered Scout intel, which is a better
design than a page-level refusal. Nothing needed changing.

**3 · §12's implicit assumption that promoting Analyze helps a day-one coach is
right for a reason the book does not give.** On this book Analyze is *open* (past
season), Lineups renders an empty state for a coach with no tracked games, and
Analyze is the only view on the War Room with content in it for that persona. The
reorder helps — but the binding constraint was neither the order nor
`pickable_teams`: it was the archive-blind `_li_any` at `9_War_Room.py:1688`,
now fixed. See the correction in TASK 1.

**4 · `THE_SICKO_BOOK` §2 grades exclusion discipline ❌ against Cleaning the
Glass. After measuring it, the grade is too harsh in one direction and the fix it
implies is wrong.** The flat 15-point rule that carries the name today would
exclude **38.6% of all tracked possessions** to move the median team **5.06
points per 100** — and a clock-aware win-probability cut excludes *more*
possessions and moves the ratings *less than half as far*. Adopting
`situational.GARBAGE` as an exclusion rule would be adopting the worst of the
three definitions. The gap is real; the obvious patch for it would have been a
mistake.

**5 · A note on the freeze.** This run deliberately broke it, as instructed.
`tools/freeze_smoke.py` is the tool the founder re-freezes off and its result is
at the top of this document. The surfaces this run touched that `freeze_smoke`
does NOT reach on a default render — the reordered bar, the lock-as-sell panel,
the heated grid, the deserved columns, the refusals surface — were driven by hand
and are recorded above.



---
