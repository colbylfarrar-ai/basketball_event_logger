# Maintenance batch — 2026-09-05

**STATUS: all nine items BUILT on branch `batch-2026-09-05`. Not pushed, not
deployed** — the branch is there to look at and decide on.

Captured from a month of live in-season use, then built the same day. Root
causes were found by a read-only pass against `8b0b87c`; the notes below keep
those line numbers, which have since moved.

## What shipped

| # | Item | Commit |
|---|---|---|
| B1 | Live Win% read 100% from the tip | `7e712d5` |
| B2 + B3 | Duplicate players; the N/A column on Rankings | `4d080cb` |
| T1 T2 T4 T5 T6 | Clock reset, one-tap tags, defense presets, tablet layout, ref search | `adc679e` |
| T3 | Tempo cuts to 8 / 20 | `ab97e98` |
| A1 | Ref foul bias by defense | `ef61d2d` |
| A2 | Rotation watch (live star coverage) | `1673ce3` |

## Found while building (not on the original list)

1. **The sticky defense and set call did not survive a reload.** `loadGame()`
   restored them; the cold-start path in `init()` never did. iOS reclaiming the
   PWA is the common case courtside, so a coach came back to untagged events.
   Fixed in `adc679e`.
2. **Intentional fouls were being counted as clutch whistles.**
   `official_overview` has always excluded strategic clock-stop fouls from
   `fouls`/FPG; the clutch and bias pass never did. All 45 strategic fouls in the
   sample fall in Q4/OT — 14% of every Q4/OT foul — which is exactly the clutch
   window. Clutch calls across the girls' season drop 49 → 35: **29% of what the
   officials rating scored as clutch whistles were teams deliberately fouling.**
   Fixed in `ef61d2d`; this moves the rating.
3. **The tempo cut had four copies at two different values** — playtypes 6/14,
   `POSS_BUCKETS` 6/14, `insights_team` 6/15, game-flow fast break 6. So
   "transition" already meant different things on different tabs. One home now
   (`ab97e98`).
4. **`stats._team_game_ids` hardcodes `season='Current'`**, which is empty right
   after a rollover. `star_coverage` and `foul_prone` use it as their default
   pool, so a no-arg call reports a team has no key players. Every caller passes
   `game_ids` today so nothing is broken — but it is a live trap. The new
   Rotation watch takes the game's own season instead. **Worth fixing at the
   source; not done here.**

## Corrections to this document's own claims

- **A2 said "none of `rotation_plan` surfaces".** Wrong — I had grepped for the
  definitions and not the callers. All three functions were already wired in
  (`insights_lineups`, `projection_tab`, `lineup_projection`,
  `6_Team_Dashboard`, and the tracker's foul watch). The real gap was a *live*
  rotation read, which is what got built.
- **T3's caution about the 8s boundary was overcautious.** Measured, it is the
  better cut on our own data — see the item below.

---

## BUGS (root cause found — build these first)

### B1 · Live Win% on Game Tracker always reads 100% — confirmed, small fix

`pages/2_Game_Tracker.py:620` calls `_WP.wp_curve(_mc)` with no `total_secs`.
`helpers/win_probability.py:79-81` then defaults
`total_secs = max(t for t, _ in pts)`, so for the **last** point
`total_secs - t == 0` — zero seconds remaining — and `win_prob` resolves a
finished game: 100% (or 0%, flipped to 100% for the other team by
`_lwp = 100 - _cwp` at line 645).

Fix has two halves:

1. Pass real regulation length: `total_secs = 4*480 + max(0, cur_q-4)*240`
   (the page already knows `_QSEC = 480` and `cur_q`).
2. Append a **current-clock** point to `_mc` before curving —
   `(_el_now, _s1 - _s2)` from the live quarter + clock — so the ribbon ends at
   *now*, not at the last made basket. Without this the strip also freezes
   whenever the game goes a few minutes without a score.

The GEI / lead-change tiles at 643-649 read the same `_curve`, so both are wrong
today too (GEI normalizes by `curve[-1][0]`, i.e. last-score elapsed).

### B2 · Duplicate players in box scores — confirmed

`helpers/box_score.py:1313` (`roster_all`, the DNP block) and `:83`
(`_build_boxes` meta) both run:

```sql
SELECT id AS pid, name, number, team_id FROM players
WHERE team_id IN (?,?) ORDER BY number, name
```

No `season` filter, no `archived` filter. `players` holds **per-season rows**
(`database/db.py:276` — `ALTER TABLE players ADD COLUMN season TEXT NOT NULL
DEFAULT 'Current'`), so a returning player has one row per season she was
rostered and every one lands in the DNP list. Worse in past-season box scores,
exactly as observed, because the current-season row is always extra.

Fix: scope both queries to the **game's** season (`g["season"]`, already loaded
at `box_score.py:335`) plus `AND archived=0`. Do not scope to `'Current'` — the
rollover sentinel is empty.

Audit the same pattern before shipping: `helpers/event_log.py:94,113,565`,
`helpers/lineups.py:240`, `helpers/networks.py:115,233,314`,
`helpers/exploit.py:341`, `helpers/defense_profile.py:152` all select rosters by
`team_id` alone. The `{pid: team_id}` maps (charges, deserved, fouls, late_game,
league_analytics) are keyed by id, so they are harmless — leave them.

### B3 · Repeated "N/A" on the Rankings page — different root cause

Not a player dupe. `pages/5_Rankings.py:567` builds
`class_of = {tid: ... for tid, r in scored.items()}`, then lines 992 / 1139 /
1168 fall back to `"N/A"` for any opponent **not in `scored`** — teams with no
ranked season row (untracked, wrong season, or below `_MIN_GP`). The N/A rows
are opponents leaking in from outside the scored pool.

Same family as B2 (season scoping), different fix: decide whether an unscored
opponent shows its stored class from `teams`, or is suppressed. Recommend
falling back to the team's own `class` column and showing "N/A" only when the
team genuinely has none.

---

## TRACKER (highest coach value, lowest build cost)

### T1 · Auto-reset clock to 8:00 on quarter change

`tracker/static/app.js:2462-2468` moves `S.quarter` up/down and relabels, but
never touches `S.clockMin` / `S.clockSec`. Reset on **increment only** —
decrement is the "I misclicked" path, so leaving the clock alone there is the
undo. OT should reset to 4:00, not 8:00; the win-prob code already assumes 240s
OT. Make the value a setting (8:00 HS / 6:00 middle school), not a constant.

Accident guard: none needed, per the founder no-previous-state rule. The clock
is directly editable and the quarter-down button already exists, so an
accidental bump is two taps to correct -- cheaper than either a confirm dialog
or an undo chip that has to stash the old value.

### T2 - Quick boxes: "Other offense" / "Other defense"  -- DECIDED

One tap that sets `play_type='other'` + `defense='other'` and logs. Purely a
scroll-saver for offensive fouls, where neither tag is meaningful and the
current flow makes you reach the bottom of the pad to answer both.

**Do NOT save and restore the previous defense.** Founder rule for this whole
batch: *change what it is now, never track or revert to what it was.* The tap
leaves the sticky defense sitting on `other`; the dead-ball clock after an
offensive foul gives the coach plenty of time to scroll up and set the real
defense and play type before the next possession. `S.playType` and `S.defense`
are already sticky (`app.js:55,552,798`), so this is a two-field write on a
button.

### T3 - Auto play-type time buckets to 8 / 20  -- MEASURED, ADOPT

Current thresholds in `helpers/playtypes.py:_tempo` (56-64) are **6 / 14**, not
15. Change to **8 / 20**. Keys and labels stay exactly as they are
(`transition` / `early` / `halfcourt`) -- times only.

Checked against the local 2026-07-28 snapshot (43 tracked games, 4,005 timed
shots) rather than adopting on the external claim alone:

| split | transition | early | halfcourt |
|---|---|---|---|
| current 6 / 14 | n=975 - **1.038** | n=1429 - **0.794** | n=1601 - **0.760** |
| proposed 8 / 20 | n=1319 - **0.973** | n=1934 - **0.803** | n=752 - **0.701** |

Two independent reasons the new cuts are better, not merely different:

1. **The current split does not separate its own last two buckets** -- 0.794 vs
   0.760 is inside noise. The proposed one is cleanly monotone
   (0.97 / 0.80 / 0.70) with a ~0.10 PPS gap at each step.
2. **8s is where transition actually ends.** Per-2s share of shots tagged
   `putback`/`transition` -- an independent, manually-tagged column, so this is
   a real sign check rather than a circular one:

   | secs | 1-2 | 3-4 | 5-6 | **7-8** | 9-10 | 11-12 |
   |---|---|---|---|---|---|---|
   | % putback/transition | 75.3% | 56.1% | 52.4% | **51.2%** | 24.6% | 10.7% |

   The 7-8s band is still *majority* transition-flavoured; the floor drops out
   at 9s. The old 6s cut was leaving real transition in the halfcourt bucket.

The 20 cut reproduces section 2.2 of `docs/DB_AUDIT_2026-07-28.md`: 21+ seconds
is 0.70 PPS, the worst and largest bucket, 99.4% halfcourt -- the shot-clock
bailout.

**Live DB pull not needed for this.** 43 games already separates the buckets by
~0.10 PPS each; 62 games will not reverse that. Worth pulling the live DB when
the ratings recal is next touched, not to unblock T3.

Still true, and the reason this is a build item and not a one-liner: flipping
`_tempo` **re-buckets every historical possession**, so every playtype rating,
percentile and league baseline moves. ~16% of possessions carry `secs = 0` and
already return `None` -- those are unaffected.

### T4 - Defense presets  -- SCOPE DECIDED

2-4 preset buttons on the tracker that set the current defense in one tap.
Editable from the **subs / setup tab** (the same panel that adds players and
sets officials), so a staff configures its own defenses preseason.

Per the founder rule: the button **sets** the defense. No previous-value
tracking, no auto-revert, no situational scripting. Storage is a per-team
setting (up to 4 defense keys, ordered), read alongside the existing sticky bar
at `app.js:1473-1490`; the presets sit above the full chip list, which stays as
the escape hatch for anything not preset.

### T5 - iPad mode  -- TOGGLE

`tracker/static/style.css` has **zero `@media` queries** -- the tracker is a
fixed phone-width layout. Biggest adoption item on this list: most staffs will
track on a tablet.

Founder leans toggle over auto-detect, and that is right here. A media query
alone guesses wrong in both directions -- a phone in landscape looks
tablet-sized, an iPad in a Split View pane looks phone-sized -- and a coach who
gets the wrong layout mid-game has no way out of it. Recommended:
**auto-detect as the default, plus an explicit override toggle** in the same
setup panel as T4, persisted in `localStorage` next to the other tracker prefs
(`LS` map, `app.js:13`). Detection gets it right for the masses; the toggle
means nobody is stuck.

Layout scope for the >=768px mode: widen the event flow, put the roster and the
action pad **side-by-side instead of stacked** (this is the whole point -- it
kills most of the scrolling that T2 and T6 are also working around), and grow
tap targets. A real design pass, not a max-width bump.

### T6 - Search the officials list  -- NEW

At season start there will be hundreds to thousands of officials in the table.
Today the picker is a **native `<select>` per slot** (`app.js:908-940`)
populated from `S.game.officials`, which `tracker/api.py:437` fills with
`SELECT id, name, archived FROM officials ORDER BY name` -- the entire table.
On iOS that is an OS wheel picker with no type-ahead: scroll, scroll, and the
ref may not be in there at all.

Fix: replace the `<select>` with a text input + filtered result list
(substring match on name, and on `official_id` since that column already
exists); tapping a result fills the slot. The existing quick-add form
(`app.js:1051-1076`, `POST /api/officials`) is the answer to "the ref is not
there" and should surface directly under a no-results state instead of sitting
behind a separate hidden form.

**Keep shipping the full list in the game payload.** The tracker is
offline-first, so a server-side search endpoint would fail in exactly the gym
where it is needed; a few thousand names is well under 100KB and filters
instantly client-side. Only revisit if the payload actually becomes a problem.


---

## DATA MODEL -- PARKED

### D1 (parked 2026-09-05) · Team turnovers / team rebounds

`game_events.primary_player_id` is already nullable (`database/schema.sql:89`),
so the row can exist. The problem is downstream: dozens of helpers do
`pid_team.get(e["primary_player_id"])`, and a NULL silently drops the event from
team totals — the same trap class as guarded_by, except here NULL would mean
"team", not "open".

Recommendation: **do not** use bare NULL. Add an explicit `team_id` column to
`game_events` (or a sentinel TEAM player row per team) so attribution is
positive rather than inferred. Only `shot_clock` exists today as a team-ish
turnover (`helpers/stats.py:650`); a proper team bucket also needs deadball
rebounds, out-of-bounds-off-them, and 10-second / backcourt violations.

Most likely item on this list to break existing ratings — gate it.

---

## ANALYTICS

### A1 · Ref splits by defense (mirror of the play-type split)

`helpers/officials.py:608-639` already builds
`playtype_fouls {off_pk: {play_type: n}}` against a pooled `league_playtype`
baseline. The defense version is the same function with `e.get("defense")`
swapped for `e.get("play_type")` — cheap, and the read is arguably better than
the play-type one ("this crew calls the press"). Fold unknown → `other` the way
`helpers/defenses.py` already does.

### A2 · Rotation insights

`helpers/rotation_plan.py` already has `star_coverage`, `foul_prone`, and
`foul_out_projection` — none of it surfaces as an Insights section. This is a
surfacing item, not a new engine: decide which view owns it. Live Game Tracker
is probably right — "your top 3 have been off together for 4:20" is a *during*
-game read, not a postgame one.

---

## EXPORT -- PARKED

### E1 (parked 2026-09-05) · OOB table + Subs table → Hudl tagging export

Not too lofty, but it is two projects, not one.

- **Feasible now**: the tables themselves. Subs are derivable from
  `game_event_lineup` diffs; OOB needs D1's team-event work first (an OOB today
  is either unlogged or folded into a turnover).
- **The hard part is not us.** Hudl ingests tags via CSV/XML against a *video*
  clock, and our event clock is a **game clock the tracker operator types**.
  Any export needs a per-game sync anchor (one "video time at Q1 8:00" input)
  and will still drift across stoppages unless the operator re-anchors each
  quarter.

Suggested path: build OOB and Subs as first-class in-app views (useful on their
own), add a per-quarter video anchor to the game row, and only then emit the
Hudl CSV. Ship the tables even if the export never lands.

---

## SUGGESTED BUILD ORDER

1. **B1** -- wrong number on the most-looked-at live panel, smallest fix
2. **B2 + B3** -- correctness; B2 audit list is the real work
3. **T1, T2** -- sideline friction, both small, both fully specified
4. **T6 officials search** -- season-start blocker, self-contained, no API change
5. **T3** -- measured and cleared; the work is the re-bucket sweep, not the cuts
6. **A1** -- near-free mirror of shipped code
7. **T4 defense presets** -- needs the setup-tab editor, which T5 also wants
8. **T5 iPad** -- biggest adoption unlock, biggest design cost
9. **A2 rotation insights** -- surfacing, not building

**Parked:** D1 (team TOV/REB), E1 (Hudl export). E1 depends on D1 regardless.

## OPEN QUESTIONS

None blocking. Resolved 2026-09-05: T2 (no revert), T3 (8/20, measured and
adopted), T4 (setup-tab editor, set-only), T5 (auto-detect + override toggle).

**Standing founder rule from this session:** when a control changes state, just
change it -- never store the previous value to restore it later. Applies to
defense, play type, and anything else sticky on the tracker.



---

## TEST STATE ON THIS BRANCH

`tracker/run_all.py` (script half): **95 / 95**.
`python -m pytest tracker/` (pytest half): **241 / 242**, one pre-existing
failure that is a data slip, not code — see below.

### The environment was running less than it looked like

Three declared dependencies were missing from the pinned interpreter
(`%LOCALAPPDATA%\Programs\Python\Python312`):

- `uvicorn` (requirements.txt:29) — the tracker server could not start locally.
- `xhtml2pdf` (requirements.txt:41) — `test_pdf_export` failed with "a PDF
  engine is available", which reads like a code failure and is not one.
- **`pytest` itself** — so the ~38 pytest modules, the half `run_all.py`
  deliberately skips (see `conftest.py`), were collected by *nothing*. A green
  `run_all` was covering less than it appeared to.

All three are installed now. Worth a `pip install -r requirements.txt` against
that interpreter before the season, and worth knowing that "run_all is green"
is only half the suite.

### One real data slip, pre-existing and unfixed

`test_charges.py::test_real_book_encoding` fails on `main` too. Of 55 tagged
charges, exactly one has the drawer and the committer as the SAME player:

    game_events.id = 7101 — game 14123 (2026-02-06), Q1 0:01,
    primary_player_id = secondary_player_id = 509 ("#21", team 1678)

Event `7100` is a foul at the same timestamp with primary 509 / secondary 498,
so this looks like a double-log where the second row took the same player into
both slots. **Not touched** — it is live data in the coach's book, and the fix
belongs in the Event Editor, not in a script. One row.

### One test this batch legitimately invalidated

`test_signature_stats.py::test_style_line_keys` built its fixture with a 20s
shot as "half-court", which was true under the old 15s+ rule and is early
offense under the measured 8/20 cuts. The fixture moved to 24s; the assertions
are unchanged, because the case it means to test ("two half-court possessions
worth two points") is unchanged. This is the re-bucketing cost T3 warned about,
showing up exactly where it should.


---

## NOTICED WHILE WORKING — ruled on by the founder 2026-09-05

### N1 · Badge numbers — CLOSED as designed, with one live remnant
**Founder ruling: by design.** Every ref has a number, it never changes across
their career, it is never duplicated, and the coach can get it before walking
into the gym — the ref writes it in the book pregame, same as the rosters. So
quick-add demanding an Official ID is correct, and the T6 no-results state is
asking for the right thing.

**The remnant is cross-state, and it is not hypothetical.** `officials.official_id`
is `INTEGER NOT NULL UNIQUE` — globally unique, with `officials.state` sitting
beside it and doing nothing. Today every official on file is `OK`. But the
**teams** table already spans 23 states (1,146 OK, 94 TX, 85 AR, 57 KS, 33 MO,
…), so the first out-of-state crew entered can collide on a number.

The failure is silent and bad: `quick_add_official` upserts
`ON CONFLICT(official_id) DO UPDATE SET archived=0` and returns the **stored**
name. An Arkansas #1234 entered while Oklahoma #1234 exists does not error — it
un-archives the Oklahoma ref, hands the coach back the wrong name, and pools two
careers' calls into one record.

Fix is a migration: `UNIQUE(official_id, state)`, upsert on the pair, and default
the state from the game's teams rather than the `'OK'` column default.
**Small, contained, and worth doing before out-of-state games are tracked.**

### N2 · Quick-add needs a connection — LOG, next session
`quickAddOfficial` and quick-add player bail with "Needs connection" while
everything else in the tracker is offline-first with a queue. A gym with no
signal is the normal case. Queue them the way events are queued and reconcile
on flush.

### N3 · The officials bias tables show refs with three games — LOG, next session
The rating is gated on `RATING_MIN_GAMES = 3`, but the two bias tables list
anyone with two calls on a tag. The audit put the shippable threshold at ~15-20
games. Gate the tables or label the low-sample rows. Pairs naturally with the
ref-rating rework below.

### N4 · A tablet-native layout — LOG, next session (thoughts below)
What shipped is the phone layout widened: same four screens, court beside the
pad at >=768px. A real "iPad Mode" would collapse screens rather than widen
them — the lineup and the tracker as ONE view with a persistent left rail
(roster, on-court five, subs), the court centre, the event flow right, and the
edit log as a slide-over instead of a screen swap. The wins are real: subs and
mistake-fixing without leaving the game, and no screen transitions during live
play.

**The cost is where it is not obvious.** `S.screen` is load-bearing for crash
recovery — `init()` restores a mid-game session by reading `st.screen` and
branching to `enterTracker()` or `renderLineup()`. Collapsing screens for real
means touching the restore path, which is the one piece of the tracker that must
never be wrong (it is what saves a game when iOS reclaims the tab).

**Recommendation: keep the screen state machine exactly as it is and change only
what each screen RENDERS at tablet width.** "iPad Mode" becomes a composition
choice, not a new navigation model — the lineup screen and tracker screen render
as one composed view while `S.screen` stays whatever it already was. Same visible
result, none of the recovery risk.

### N5 · `stats._team_game_ids` is a rollover trap — LOG, next session
Hardcodes `season='Current'`, empty for the first weeks of a season. Default pool
for `star_coverage` and `foul_prone`, so a no-arg call silently reports a team
has no key players. Nothing broken today (every caller passes `game_ids`); give
it the fallback `seasons.tracked_default_season_sql()` already implements.

### N6 · `cur_q` from events — CLOSED as designed
**Founder ruling: by design.** The bench page is event-sourced — it reconstructs
state from what was logged, rather than mirroring live tracker UI state. There is
no server-side "current quarter" to read and there should not be one. The only
residual is cosmetic: between the tracker advancing to OT and the first OT event
landing, the win-probability strip prices the game against regulation length.
Self-correcting on the next logged event. **No action.**

### N7 · Untimed possessions — CLOSED, the proposed rule is already the rule
**Founder ruling: by design, subtract them from the denominator.** That is
already what happens everywhere: `tempo_bucket()` returns `None` for `secs <= 0`,
`insights_team._style_line` gates its tempo counters on `secs > 0`,
`quarter_possession_secs` skips them, and `POSS_BUCKETS` reports them as a
separate `Untimed` row rather than folding them into half-court. Verified across
all four surfaces. **No action.**
