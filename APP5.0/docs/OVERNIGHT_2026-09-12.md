# Overnight run — 2026-09-12

Branch **`overnight-2026-09-12`**, six commits, **unmerged and unpushed** as
asked. Both suites green after the last one.

| | |
|---|---|
| Commits | `5fed8f7` · `f27d135` · `3817ce2` · `c26508a` · `925c442` · `80ab2e4` |
| Suites | `pytest` **479 passed** (was 476) · `tracker/run_all.py` **100 / 0** (was 99 / 0) |
| Verified against | `~/app5_prod/analytics.db` — 43 tracked girls' games in `2025-2026`, headless AppTest |
| Source docs | `THE_BOOK_2026-09.md` §21 · `FREEZE_PUNCHLIST_2026-09-09.md` · `SCOUT_PROFILE_PRINT_2026-09-11.md` |

Both suite counts went **up**, never down; the additions are new test files, not
re-priced assertions. Nothing in `test_offline_readiness.py` or
`test_ratings_depth_smoke.py` was touched.

---

## 1 · October instrumentation — THE BOOK §21 Phase 1 (`5fed8f7`, `80ab2e4`)

`grep page_view` returned nothing. None of the three counters existed, and the
training session that would have produced the evidence happens exactly once.

One Streamlit-free engine — `helpers/telemetry.py` — one append-only table of
six scalar columns, and three call sites picked so that nothing has to be
remembered later:

| counter | instrumented at | why there |
|---|---|---|
| page views | `helpers.ui.page_chrome` | the single page boot; every page in `pages/` goes through it |
| empty-state hits | `helpers.ui.empty_state` | the single "nothing to show" funnel — **53 call sites covered, zero edited** |
| co-op toggles | `helpers.auth.set_shares_pool` / `set_team_shares_pool` | the two setters, not the two Settings widgets, so a third call site added later is covered for free |

### Per-event rows, not daily counters — and why the volume objection is misaimed

§21 asks for pages "in what order", and a daily counter cannot answer ordering
at all. The real objection to per-event rows is volume, and on Streamlit it is
worse than it first looks: `page_chrome` and `empty_state` both run on every
**rerun**, not every open, so a naive row-per-call logs a row for every widget
click — hundreds per coach per hour.

The fix is to dedupe at the source rather than to throw the ordering away:

* `page_view` writes only when the actor's page **changes**. Overview → Scout →
  Overview is three rows; clicking twelve filters inside Scout is none.
* `empty_hit` writes at most once per `(actor, site)` per 90 s, so an empty state
  that stays empty across a rerun storm is one hit, not forty.
* `coop_toggle` is never deduped. Every flip is a fact, and there are maybe ten
  of them a season.

An empty state is named by the **caller's `module:line`**, not by its title:
"No tracked games yet" is written in at least four different tabs, so titles
alone would merge four distinct dead ends into one row. `sys._getframe(2)` costs
nanoseconds; `inspect.stack()` would not have been acceptable here.

### Measured, and what the measurement changed

| | |
|---|---|
| 5,000 rows written | **3.78 s** → 757 µs/row (includes the two commits `db.execute` does per call, and the index) |
| database file growth | **476 KB** → **97.5 bytes/row** |

The first cut kept 180 days on an assumed ~60 B/row. At the top of plausible use
(five coaches, ~200 navigations a day each ≈ 98 KB/day) that is **~17 MB against
a production book that is currently 17 MB** — doubling the database to hold page
views. `80ab2e4` cuts retention to **90 days** (the October training at full
resolution plus the first two months of the season; the read surface only ever
asks for 30) and adds `MAX_ROWS = 150_000` as a hard ceiling, deleted by `id`
rather than by date because ids are monotonic with one writer.

### Guard rails

* Every public function wrapped — but logging at **WARNING**, so a broken counter
  is a missing number rather than an invisible one.
* The kill switch (`app_settings.telemetry_off`) **fails closed**: if the switch
  itself cannot be read, telemetry is off. Losing a counter is cheaper than
  raising on every page load.
* `telemetry` added to `_AUDIT_SKIP_TABLES`. Without it the write-audit hook
  writes a second row for every page view — doubling the cost of the cheapest
  thing in the app and burying real moderation signal under it.
* The prune runs on the **write** path (once per day per process), so a founder
  who never opens Settings still cannot grow the table.

### The read surface

An expander in Settings beside "Coaches online & server capacity", because the
founder already looks there once a week by design. Order: **dead ends first**
(it is a direct list of the reasons a coach opens a page in anger), then pages
opened with an "opened first" column, then every co-op flip. A live Recording
toggle writes the kill switch.

"Opened first" is how ordering survives the dedup: how many coach-days started on
each page. The finer-grained sequence is in the rows if it is ever wanted.

---

## 2 · Five sites that re-widened an entitlement-scoped id set (`f27d135`)

Freeze punch list item 3. `tuple(x) or None` reads as harmless plumbing; `None`
means **unrestricted** downstream, so the narrower a coach's rights the more
play-by-play they were handed.

```
helpers/dashboard/insights_team_read.py:58     gids = tuple(...) or None
helpers/dashboard/insights_tab.py:631          tuple(_tids or ()) or None
helpers/dashboard/insights_tab.py:633          season_gp=...      or None
helpers/dashboard/insights_tab.py:640          league_gids=...    or None
pages/6_Team_Dashboard.py  (_ins_scheme_sit)   (... if ... else ...) or None
```

Two different cases inside those five:

* `_tids` is the **visible game set**. `controls()` always returns a tuple, empty
  exactly when the visible set is empty. Fixed by adopting the shape
  `_ins_quarter_read` has always had — return nothing when the scope is nothing.
* `season_gp` is `None` **by design** on the current season (the page's engine
  binders are the identity there) and a real tuple otherwise, so `None` and `()`
  must stay distinguishable. `stats.as_scope` is that one-liner, stated once.

**The punch list said reachability was unproven. It is reachable.**
`insights_tab.py`'s career-rows branch lets a team past the `has_tracked` gate
with `has_tracked` False and `tracked_ids` empty — which is precisely the
combination the punch list could not construct against the production book.

Three new tests construct it rather than trusting the fix, and the static scan
learns the spelling it was missing: it only knew `coll(x) if x else None`, and
every one of these five wore `or` instead. `_is_widening_boolop` requires the
left operand to be a collection **constructor**, so ordinary `name or None`
scalar-defaulting never trips it. Verified it matches exactly the five known
sites across `pages/` and `helpers/`, and **zero** after the fix.

---

## 3 · The Player Profile's game window (`3817ce2`)

Refused last night for a reason that turned out to be the design: every cached
read on the card takes `game_ids`, so narrowing that one pool narrows the league
percentile pools with it.

**Two scopes now, not one.**

| | reads | moved by the control? |
|---|---|---|
| `_gp` | percentile rails, `_pctile_n`, `pctile_bar`, rank tables, league bars, RAPM / WPA / WAR | **no** |
| `_win` | game log, shot map, per-game boxes, form block, foul/FT detail, matchup reads | yes |

`Season · Last 10 · Last 5`, placed **above the fold** rather than above the
sections: the fold carries her shot map and her form arrows, and a control that
scoped the sections while leaving two shot maps on one screen disagreeing is
worse than no control.

`_player_window` takes the games **she** appeared in (not the team's last five —
a different window for anyone who missed a game), intersected with the
entitlement pool first so it can only ever narrow. An empty entitlement stays
empty.

Because the pools now differ, every windowed block says which pool ranked it —
`_pool_note` under the control, under the league rail, and at the top of all six
sections, plus the window inline in the fold's shot-map header.
[[pctile-pool-convention]]: the pool a number was ranked over is part of the
number.

**Measured** on `~/app5_prod`, the three most-tracked players:

| | season | last 5 |
|---|---|---|
| per-game boxes | 26 | 5 |
| located shots (pid 3) | 165 | 28 |
| free-throw attempts (pid 3) | 16 | 2 |

All **18** combinations of 3 windows × 6 sections render with no exception.
AST-swept for cross-section leaks (collecting `ast.alias` as well as `ast.Name`,
so an import bound in one section and read in three is caught) — **clean**.

---

## 4 · Charts → Scout, Tier A (`c26508a`)

Four blocks the Charts tab already draws about your own team, pointed at the team
you are playing. `scout_deep` computes nothing: every input already rides on
`_opp_scout_ctx`. **One new ctx binder** (`strength_split`), **no new metric**.

1. **Where they force shots** (Sets & schemes) — their defensive shot chart,
   which read about *them* is our offensive game plan.
2. **Winning formula** (Team profile) — beside the four factors, because it is
   the verdict those bars are evidence for.
3. **Shot making vs shot quality** (Situational & shooting) — directly under the
   zone charts, because it is the question those charts raise and cannot answer.
4. **Top half vs bottom half** (Team profile) — one row, one line of prose.

### Three things found by reading the output, not the code

* **`verdict_lines` badges the fit "Your games".** Its only caller had been the
  self-scout, so on an opponent sheet it labelled *their* formula as ours — on
  the one surface whose entire job is telling the two apart. `scout_deep` builds
  its own lines from `WF.verdict(fit, scope=…)` rather than string-patching the
  engine's output, and sides every header on `is_self`.
* **The team fit read the whole season, ignoring the read filter.** Fitting an
  opponent's formula over games the viewer may not see is the read filter leaking
  through a **model** instead of through a table. The TEAM half now takes
  `ctx.tracked_ids` (via `stats.as_scope`, so an empty entitlement yields no fit
  rather than a season-wide one); the LEAGUE half stays league-wide, because it
  is a property of the competition that Charts and Insights already print for
  everybody. **Verified:** an empty-entitlement ctx returns the league line only.
* **Two invented thresholds** — see *Refused*, below.

### Print

All four default to **screen ON / paper OFF**, which is what splitting
`scout_hidden_screen` from `scout_hidden_print` was for. A brand-new key is
absent from both stored CSV sets and would therefore default to visible on both,
so `_NEW_PRINT_OFF` adds them to the print set **additively** — re-running the v2
seed would have thrown away every print choice a coach has made since. Each still
has a paper form (verdict lines, never the charts), because a print toggle that
renders nothing is its own bug.

**Measured**, opponent with 11 visible tracked games: default sheet **171.5 KB**
carrying **zero** Tier A headers; all four promoted **174.1 KB** carrying all
four. All **14** combinations of 2 framings × 7 sections render with no
exception. AST-swept clean.

---

## 5 · The free-before-breakfast list

| item | outcome |
|---|---|
| `insights_deck._next_game` missing its twin's two guards | **already fixed.** The function carries both, with a docstring naming `team_card._next_game` as the source. Closed, no change. |
| `coverage.py` does not gate `turnover_type` | **already fixed.** It is a reported signal with its own denominator and a docstring section explaining why it is deliberately *not* in `OVERALL_SIGNALS`. Measured on prod for team 1: `turnover_type` 52.6% over 308 turnovers. Closed, no change. |
| two hardcoded shot-depth captions | **fixed** — `925c442`, below. |
| `auto_season_rollover.py` and the 23 `season='Current'` games | **written up, not fixed** — below. |

### Shot-depth captions (`925c442`)

`RIM_FT`, `FLOATER_FT` and `DEEP_FT` are registered in `model_constants` so a
recal can move them. Three of the five band labels typed the number in by hand
(`"0-4 ft"`, `"4 ft - arc"`, `"inside 4 feet"`, plus `"from 4-10 feet"` in the
verdict). A recal to 4.5 ft would have re-classified every shot and gone on
telling the coach the line was at 4. `deep3` already interpolated `DEEP_FT`,
which is how the disagreement was visible at all — one row of the same dict
honoured the engine and the others did not.

The second half is worse, and is why `deep3` was not safe either:
`model_constants.apply()` rebinds the attribute **after** import, so every
f-string evaluated at import time was frozen at the committed default for the
life of the process. Labels are now rebuilt **in place** (the dicts keep their
identity — seven call sites subscript them and `TAXONOMIES` holds a direct
reference) by `_on_constants_applied`, which `apply()` calls on every module it
touched. That hook is the general fix; `shot_kinds` is simply the first module to
declare it.

Committed defaults render **byte-identical** to before. A simulated recal to
4.5 / 11 / 23.5 moves all five.

### The rollover — what the dry run actually showed

Run against **two throwaway copies** of the prod snapshot. Neither book was
written to.

**The good news, and it is not what the punch list expected.** The roll has
**already happened**: `active_label()` on the snapshot is already `2026-2027`,
and `auto_advance_if_due(2026-10-01)` returns
`{'rolled': False, 'reason': 'up-to-date'}`. The 23 games wearing
`season='Current'` (2026-12-08 → 2027-02-16, none tracked) **are** the 2026-2027
schedule — `ACTIVE = "Current"` is the sentinel the active season's rows wear by
design, and `active_label()` maps it. Freeze punch list §6 is a false alarm:
**November opens on those 23 games, not on an empty schedule.**

**The hazard is real but deferred.** On the second copy I wound `active_season`
back to `2025-2026` and re-ran the same call:

```
auto_advance_if_due(2026-10-01) -> {'rolled': True, 'from': '2025-2026',
                                    'to': '2026-2027', 'carried': 228,
                                    'graduated': 2}

AFTER:  2025-2026   n=13383   2025-09-04 .. 2027-02-16
        (season='Current' is now EMPTY)
```

`seasons.execute_rollover:327` is `UPDATE games SET season=? WHERE
season='Current'` with the **outgoing** label, so all 23 future-dated games are
filed into last season's archive and November opens blank. The importer files
next season's schedule under the sentinel; the rollover assumes everything
wearing the sentinel belongs to the outgoing season. Those two assumptions
disagree, and the disagreement is only harmless this year because the roll
already ran.

**It comes back on 1 October 2027**, with whatever 2027-2028 schedule has been
imported early. Not fixed here, per the brief: the correct fix is date-aware
stamping at rollover, that is a change to the one job that has to run unattended,
and it needs a founder ruling on what "belongs to the outgoing season" means for
a game with no result.

---

## Refused, and why

* **Two invented thresholds in the Shot Lab port.** The first cut graded look
  quality at `>= 0.45 xFG` and shot-making at `>= +2.0pp` and announced which
  side a team fell on. Neither constant is in `reliability.MEASURED`. Measured
  look quality on this book is **0.298**, so the 0.45 gate would have read
  "ordinary looks" for every team forever — a verdict that cannot fire is worse
  than none, because it reads as a finding. The block states both numbers and the
  rule for reading them instead. Over-expected keeps its **sign**, because that
  zero is the engine's own expectation and not a constant anybody chose.
* **The strength split's directional verdict on a thin side.** On the live book
  the opponent's bottom half is **2 games**. "A good-team beater" off two games
  is the superlative B1 bans. The split itself always prints — it is a number —
  and under three games a side the sentence is replaced by "the numbers are
  above, but which way they lean is not something this sample can say".
* **Anything quarter-shaped.** Nothing in Tier A needed it and nothing was
  shipped. The measured position stands: only tempo repeats.
* **Team DNA rail and putbacks** (roadmap Tier A, not in tonight's four). Left
  alone; the masthead already carries a strongest/softest identity line.
* **Chemistry on the profile** (`networks.chemistry_network`, ~16.5 s). Still
  unbuilt, still needs the opt-in gate Insights gives it.
* **Any model constant.** None moved. `925c442` makes the *labels* follow the
  constants; it does not change a value.

---

## Assumptions written down

1. **Telemetry actor is the plain email**, matching `audit_log.actor` and the
   `u:<email>:` scoping in `settings_utils`. Hashing was considered and rejected:
   with five known coaches a hash is not anonymity, only an extra join to do by
   hand in October. Nothing in the table is more sensitive than `audit_log`
   already is. One flag flips this if you disagree.
2. **The telemetry dedup state is per-process, in memory** — `app5-web` is one
   Streamlit process, which is the same fact `helpers/presence.py` already relies
   on. A restart re-arms it and at worst duplicates one row per actor.
3. **The profile's window control sits above the fold**, so the fold's shot map
   and form arrows honour it. The alternative (below the fold, scoping only the
   sections) leaves two shot maps on one screen disagreeing.
4. **The fold's ↗↘ trajectory chips keep the SEASON boxes.** They are "last 5 vs
   season" by construction; narrowing them would compare the last five to
   themselves and always read flat.
5. **Giveaway mix, on/off and the chemistry graph stay on the season pool** on
   the profile. They are not among the six per-player reads the spec named, and
   widening the window's reach past the spec was not mine to decide.
6. **The winning formula's LEAGUE half is not read-filtered.** It is a property
   of the competition, printed league-wide on Charts and Insights already, and
   discloses nothing about whose games are pooled. Only the TEAM half takes the
   entitlement pool.
7. **Tier A prints as verdict lines, never as its charts.** The sentences change
   a game plan; a chart costs a third of a page and all four default to paper
   off anyway.
8. **`_PREF_V` bumped 2 → 3 with an ADDITIVE migration.** Re-running the v2 seed
   would have rebuilt both hidden sets from the pre-split key and discarded every
   print choice made since 2026-09-11.

## One thing I did and then undid

The printable-gating check wrote `scout_hidden_print` / `scout_sections_v` /
`scout_hidden_screen` / `scout_layout` into **`~/app5_prod/analytics.db`**, and
the AppTest runs left 11 `telemetry` rows there. Both are settings/log rows, not
game data, and neither key can have existed in production (the screen/print split
shipped locally on 2026-09-11 and was never deployed). **All of it has been
deleted** — `app_settings` has no `scout_*` or `telemetry*` rows and `telemetry`
is empty. The snapshot's schema now carries the `telemetry` table, which is
idempotent and harmless. No game, event, player or team row was touched, and the
local dev book was never opened.

## Next

* Review and merge. Nothing is pushed; nothing is deployed.
* The two ops blockers are unchanged and still founder-only: the four systemd
  timers, and `tools/repair_book.py --apply` plus the restart that lets
  `ux_games_matchup` take.
* The 2027 rollover hazard above wants a ruling before next October, not before
  this one.
