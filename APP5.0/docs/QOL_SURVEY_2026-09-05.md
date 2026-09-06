# QOL / performance survey — 2026-09-05

A read-only survey for the founder to rule on. Nothing was built. Every number
below was measured, not estimated, and the method is stated beside it so a
disputed figure can be re-run rather than re-argued.

**Repo state at survey time:** `main` == `origin/main`, working tree clean. All
three previously parked branches (`batch-2026-09-05`, `queue-2026-09-05`,
`officials-rating-2026-09-05`) are merged and pushed. The tablet layout is on
`main` (`html.is-wide` in `tracker/static/style.css:640`, no media queries — the
class is computed in `app.js:69`). So this survey starts from a clean slate, and
the iPad Mode item that was blocked on a parked branch is now unblocked.

---

## How this was read: the 2025-2026 lens

Everything here is measured against **`season = '2025-2026'`**, not `'Current'`.

`'Current'` is the 2026-2027 label and holds exactly one unplayed game
(`id 27077`, 2026-12-08, no score). The season does not start for two to three
months. Reading the app through `'Current'` today produces a healthy-looking
empty state that proves nothing — it is the season trap
`tracker/test_insights_layout.py` already documents in its header. The
2025-2026 book is what is live online and is the accurate picture of what a
coach sees going into next season.

**The sample:** 13.3 MB snapshot of the live book, taken 2026-09-05 20:24.
13,363 games, 7,731 events across **44 games with play-by-play** (43 flagged
tracked — see B3), 541 players, 1,448 teams, 70 officials, **704 teams with a
computable rating** under 2025-2026.

**The method for every timing below:** `streamlit.testing.v1.AppTest` driving
`pages/6_Team_Dashboard.py` against that snapshot with
`ta_season = '2025-2026'`, on this laptop, real Python312. Production is a
**1 vCPU / 2 GB no-swap droplet**, so multiply by roughly 2-3× for what a coach
actually waits. That multiplier is consistent with the previously recorded 85 s
prod cold / 0.97 s warm on Insights.

---

## THE HEADLINE — the cold cost, and the 45 things that cause it

Team Dashboard, per view, cold and warm (seconds):

| view | cold | warm |
|---|---:|---:|
| **Overview** (default) | **32.93** | 1.31 |
| Insights | 17.59 | **1.24** |
| Scout | 14.19 | 3.25 |
| **Schedule** | 9.35 | **7.43** |
| **Projection** | 6.88 | **6.31** |
| Roster | 2.09 | 1.41 |
| Charts | 1.24 | 1.08 |
| Lab | 1.27 | 1.14 |
| Share | 1.46 | 1.04 |
| Glossary | 1.03 | 1.12 |

Two separate stories in that table.

### Story one: 33 s cold, and it is the DEFAULT view

Overview ran first, so it paid every cold cache miss on the page — the 32.93 s
is **the flagship page's whole cold cost**, not Overview's own work (warm it
profiles at 2.4 s). On the droplet that is 60-90 s, and Overview is the default
view, so it is the first thing a coach sees after any cache reset.

**What resets it: 34 raw `st.cache_data.clear()` calls across 8 pages.** The
app has 251 `@st.cache_data` functions (201 at `ttl=600`). Streamlit's global
clear nukes all 251. (An earlier draft of this document said 45 across 12 files; that count
included comments that merely name the call.) Today a depth-chart save
(`pages/11_Setup.py:149`), a district edit (`:187`), a game tag (`:257`), a box
correction (`:334`, `:389`) — and a **theme toggle**
(`pages/12_Settings.py:318`) — each cold-bust the entire app for every coach on
the box.

**The scoped mechanism already exists and only the tracker uses it.** Batch #6a
built `game_events.bump_data_version(scope)` + `cache_clear_decision()` +
`ui.declare_scope()` so a cross-process phone write only invalidates its own
`(gender, season)` pool. In-process page writes never adopted it — they still
call the nuclear clear.

Streamlit has no scoped global clear, but every cached function carries its own
`.clear()`. A `helpers/ui.clear_scope(gender, season)` over a registry of the
expensive wrappers gets most of the win, and the four or five settings-only
sites (theme, display prefs) should clear **nothing** — they do not touch data.

**This is the single biggest felt-speed lever in the app.** Everything else in
this document is smaller.

### Story two: two views that never cache at all

Schedule and Projection are ~as slow warm as cold. They are not expensive
computations that need optimizing — they are uncached.

- `helpers/dashboard/projection_tab.py` — **9 functions, zero `@st.cache_data`.**
  6.8 s warm. Profiles as **208 `database/db.py:976 query()` calls** (1.58 s
  cumulative) — an N+1 pattern under `LP.build_context`
  (`helpers/lineup_projection.py:94`) and `RS.suggest_rotation`
  (`helpers/rotation_schedule.py:236`), both of which are Streamlit-free engines
  with zero caching of their own **by design** — the dashboard layer is supposed
  to cache them, and here it doesn't.
- `helpers/dashboard/sched.py` — 2 cached of 3 functions; `render` (`:46`) is
  the uncached one. **10.0 s warm.** Profiles as `stats.shot_rating`
  (`helpers/stats.py:1393`) ×318, `stats.expected_points_per_shot` (`:990`)
  ×259, and `player_ratings.resolve_leaves` ×13,992 — per-shot model evaluation
  re-run on every rerun.

Every other dashboard module caches properly (`insights_tab` 5+, `player_card`
6+, `team_card` 8+). These two were missed. **Adding the decorators is the whole
fix** — no math changes, no new engines.

### Story three (smaller): eager `st.tabs` inside the flagship

The `_seg` conversion made top-level views lazy. **18 `st.tabs` calls survive**,
4 of them on `pages/6_Team_Dashboard.py` — including
`qt1, qt2, qt3, qt4 = st.tabs([...])` at `:3407`, which runs all four
Quarters bodies on every rerun of that view. Rankings has 4 more. Same
conversion, same known failure mode (see the cross-tab variable leak note — AST
sweep before converting).

---

## BUGS — root cause found

### B1 · `team_ratings._finished_games` has no rollover fallback

`helpers/team_ratings.py:112` hardcodes `season="Current"` with **no fallback**,
unlike `playtypes._tracked_game_ids`, which does fall back. Measured against the
live book:

```
TR.score_ratings(gender='F')                 ->   0 teams
TR.score_ratings(gender='F', '2025-2026')    -> 704 teams
LA.team_form_stats(gender='F')               ->   0
LA.team_form_stats(gender='F', '2025-2026')  -> 704
```

Rankings and Team Dashboard survive because they pass a picker value
(`SEAS.default_read_season_index`). These callers take the bare default and get
nothing:

| site | effect |
|---|---|
| `pages/0_Analytics_Hub.py:69` | `if not scored: return d` → **the whole page collapses to the hero + "Jump in"** |
| `pages/4_Schedule.py:187` | no ratings on the schedule; the page has **zero** season handling anywhere in it |
| `helpers/predictor.py:68` | predictor dead |
| `helpers/wpa.py:476`, `helpers/box_score.py:194`, `helpers/team_ratings.py:759` | silent zeros |
| `pages/5_Rankings.py:496` | the no-season call inside the compare |

**This is the same class as N5**, which `queue-2026-09-05` already fixed for
`stats._team_game_ids` / `_team_game_ids_all` using
`seasons.tracked_default_season_sql()`. This is the next instance, and unlike
N5 it is **not latent — it is live right now.**

One design note for the fix: `_finished_games` is not `tracked_only`, so the
fallback wants "most recent season with FINISHED games", not with *tracked*
games. That is a sibling of `tracked_default_season_sql()`, not the same
expression.

**Second, independent break on the same page.** `pages/0_Analytics_Hub.py:233`
calls `ENT.visible_tracked_game_ids(_hub_ident)` with no season, and
`helpers/entitlement.py:237` defaults to `"Current"` — so a paid league-wide
viewer gets an **empty** visible set, `_no_depth` goes true, and every tracked
surface gates off even if B1 were fixed. Same default in `pooled_game_ids`
(`:127`), `team_has_pooled_tracked` (`:190`), `team_visible_tracked_ids`
(`:285`), reached without a season from `helpers/box_score.py:289`,
`helpers/dashboard/analyze.py:91`, `helpers/dashboard/scout_tab.py:315`,
`pages/7_Players.py:431`, `pages/8_Officials.py:238`,
`pages/14_Hall_of_Fame.py:510`, `pages/9_War_Room.py:223`.

**The Analytics Hub is already half-migrated**, which is the tell that this was
a known pattern someone started and didn't finish: `:156` uses
`tracked_default_season_sql()` for the Game of the Season pool, while `:128`
hardcodes `season='Current'` for the sparkline dates and `:69` takes the bare
default. Three different behaviours in one file.

⚠️ Verified on the local snapshot. Prod carries 62 tracked games to this
snapshot's 44 — confirm there before shipping, though the **season labels** are
the same object and that is what the bug turns on.

### B2 · Projection and Schedule are uncached

See "Story two" above. `projection_tab.py` needs `@st.cache_data` wrappers over
`LP.build_context` / `RS.suggest_rotation`; `sched.py:46` needs the same over
whatever feeds `shot_rating` / `expected_points_per_shot`.

### B3 · One game has 61 events and `tracked = 0`

`games.id = 4`, 2025-12-10 at Adair, Tournament. 44 games carry events, 43 are
flagged tracked. Those 61 events are invisible to every tracked pool, every
rating, every insight. `tracked_by` is empty and the events carry no
`client_uuid`, so this is an old desktop-path game that never got its finish
call.

One flag flip — but worth deciding whether it should be a **guard** instead: a
`run_all` check that asserts `count(distinct game_id from game_events) ==
count(games where tracked=1)` would have caught it, and will catch the next one.

### B4 · Nine duplicate games in the book

Five same-orientation, four mirrored (home/away swapped, **both rows scored**).
Both teams get double-counted in W/L, SOS and power rating.

| a | b | date | matchup | note |
|---|---|---|---|---|
| 124 | 21347 | 2026-01-22 | Jay vs East Newton | identical 53-45 |
| 142 | 22297 | 2026-01-09 | Wyandotte vs Baxter Springs KS | identical 45-20 |
| 453 | 22045 | 2025-12-11 | Sequoyah vs Alma AR | identical 58-38 |
| 323 | 22449 | 2026-01-10 | Yukon vs Alva | **43-55 vs 44-53 — scores disagree** |
| 14381 | 16419 | 2026-02-05 | KIPP Tulsa vs Crossover Prep | one row has NULL scores |
| 115 | 21345 | 2025-12-11 | Bentonville AR / Jay | mirrored |
| 158 | 23837 | 2025-12-12 | Coffeyville / Oklahoma Union | mirrored |
| 400 | 23134 | 2025-12-04 | Coronado NV / Millwood | mirrored |
| 16621 | 17598 | 2026-01-22 | Santa Fe South / Christian Heritage | mirrored |

`helpers/game_dedup.py` exists. It is **not catching the mirror case** on OSSAA
import — that is the real bug; the nine rows are the symptom. Note that seven of
the nine involve an out-of-state or cross-border opponent, which is where a
second source is most likely to list the game from the other side.

### B5 · A live duplicate jersey number

`players` team 1: **Carly Buell (id 257)** and **Rylee Brown (id 424)**, both
`#4`, both `season='Current'`, both `archived=0`. B2 in the 09-05 batch fixed
the *box score* symptom; the row is still there. Every other apparent duplicate
in the table is a correct season pair (archived 2025-2026 + active Current) and
should be left alone.

### B6 · `game_events.foul_type` is a dead column

**100% NULL across all 1,115 fouls.** Grep finds it in exactly one place in the
entire tree: the `ALTER TABLE` at `database/db.py:569`. **Zero readers, zero
writers, no tracker UI.** It was added and never wired.

Two honest options, and the choice is a product call:

1. **Wire it.** Shooting / common / offensive-charge / intentional / technical
   is exactly the axis the officials rework needs to separate "a tight crew" from
   "a bad crew", and it unlocks and-1 rate, shooting fouls allowed, free-throw
   generation and drawn-charge rate — all standard on every competitor. Tracker
   cost is one more chip row on the foul flow, which the T2 one-tap work already
   built the pattern for.
2. **Drop it.** A column that has been NULL for a full season is a promise the
   schema is making and the app is not keeping.

Recommend (1), scheduled behind the officials rework rather than in front of it,
because the rework is what will consume it.

---

## COVERAGE — corrected twice; the founder's read is the right one

My first pass called the sparse columns "under-tagging". That was wrong, and the
founder's correction was right: `shot_x/y`, `play_type`, `turnover_type` and
`defense` were added well after the project started, so a whole-book NULL rate
is a **history artefact**, not a coach behaviour. But the per-game table tells a
third story that neither of us had:

Per-game tagging coverage, oldest to newest (44 games, `%` of the relevant
denominator):

- **`shot_x/y` and `play_type` are at 100% from the very first game**
  (2025-12-02) and stay there. There is no ramp visible in this book at all.
- **Three games have no optional tags whatsoever** — `gid 4` (2025-12-10),
  `gid 3` (2026-02-13), `gid 27` (2026-02-20): no `client_uuid`, no `shot_x/y`,
  no `play_type`, no `defense`, `tracked_by` empty, zone-only. These are
  **old-desktop-path games**, and two of the three are LATE in the season, so
  they are not chronologically early — they look like games entered after the
  fact from video or a box score.
- **Three late games are missing `defense` / `play_type`** — `gid 28`
  (2026-02-24), `gid 29` (2026-02-28), `gid 31` (2026-03-11), all mobile PWA with
  full `shot_x/y`. I first read this as "the optional tags get dropped exactly
  when the games matter most", since all three are playoff games. **That was
  wrong.** Founder correction 2026-09-05: this is a manual RETAG in progress —
  nearly every Adair girls' game has been gone back through and updated, these
  are simply the ones not reached yet, and the columns postdate the start of the
  project. It may or may not finish before the season starts; **everything will
  be full next season.** So the gap is backlog, not behaviour, and there is
  nothing to fix or measure here.
- **`turnover_type` sits at ~35% and is genuinely optional** — 512 of 1,475. It
  is *not* a broken write path and *not* split by tracker: it appears at 100%
  and at 0% on both desktop and mobile games, and it is uncorrelated with
  whether a steal was recorded (303 tagged-with-steal vs 209
  tagged-without). It is a tag the coach skips under pressure.
- `shot_created_by_id` never exceeds 24% on any game. That is not coverage
  failure either — it is a rare event being recorded honestly.
- `guarded_by_id` swings 23-96% per game and **that is signal, not a gap** —
  NULL means uncontested, which is a value.

**The consequence I went looking for is NOT there — checked, and the engines are
correct.** I expected league baselines to divide tagged production by *all*
possessions, which would let the three untagged games deflate every rate. They
do not: `helpers/defenses.py` carries `total_tagged` / `untagged` through
`team_defenses` (`:97`), `team_defense_families` (`:171`) and
`cross_play_defense` (`:283`), and `helpers/playtypes.py` does the same at
`:280` / `:326`. Separately, the seven `PLAY_TYPES` on the playtypes tab
(transition / early / halfcourt / self / pass / screen / both) are **inferred
from `possession_secs` and pass-or-screen presence, not from the `play_type`
column at all** — and `possession_secs` is 0% NULL — so those are immune by
construction.

**Net: coverage needs no engine work and no product work.** The retag
backlog closes it, and the engines already read tagged and untagged games
correctly in the meantime. The only thing worth carrying forward is that the
three zero-tag desktop games (`gid 3`, `4`, `27`) will never have `shot_x/y` at
all, since they were never captured — those are a different case from a row
awaiting a retag.

---

## THE FLAGSHIP — Team Dashboard → Insights

Rendered end to end against the 2025-2026 book, team 1 (24 tracked games).
`tracker/test_insights_layout.py`: **all 135 checks pass**, 40 findings ranked
with no cap, 46 dense blocks, r-chips varied and real (`r=0.11` … `r=0.87`).
Per section, cold / warm / rendered markdown:

| section | cold | warm | chars |
|---|---:|---:|---:|
| Who we are | 1.16 | 1.28 | 72k |
| Why we win / why we lose | 1.79 | 1.04 | 92k |
| Who's helping | 1.62 | 1.17 | **214k** |
| Who to play together | 5.95 | 1.10 | 163k |
| What they'll take away | 1.20 | 1.50 | 83k |
| Monday | 1.14 | 1.18 | 72k |
| Receipts | 1.09 | 1.05 | **257k** |

**The flagship is healthy and it is fast.** THE BOOK recut worked: lazy `_seg`
sections, a real `@st.fragment`, ~1-1.5 s warm per section. Nothing in this
document argues for re-architecting it.

Three observations, in descending confidence:

1. **Two entries in the buried-analytics map are now stale and should be
   struck.** The shot map IS on Insights
   (`helpers/dashboard/insights_tab.py:747`, `_render_shot_map` at `:1151`) and
   the matchup grid IS on Insights (`:1192`, `MU.matchup_difficulty`). Both were
   listed as "still not on Insights"; both were built since. Likewise
   `charges.charge_rate_map` is no longer dead — `helpers/player_ratings.py`
   consumes it.
2. **Quarter analysis is still the one real content gap.** Charts → Quarters
   has four sub-tabs; Insights has **zero** quarter reads except the foul-trouble
   quarter lines at `insights_deep.py:561`. "We are a third-quarter team / they
   are" is a sentence every coach says out loud, and the deck has no way to say
   it. This is the highest-value remaining import, and per the lazy-section rule
   a new panel costs only when opened.
3. **Receipts at 257k and Who's helping at 214k characters are worth a
   density look** — not a cap (the rank-never-hide law is regression-tested and
   should stay), but Receipts is three times the size of the sections around it
   and may want internal structure. Flagging for a human eye, not proposing a
   change.

Genuinely dead and still safe to delete: `team_insights.keys_extra`,
`development.project_rest_of_season` — both have zero call sites outside their
own module.

---

## ANALYTICS HUB — the decision to make

725 lines. Its fourteen sections split three ways:

| duplicates Rankings outright | duplicates elsewhere | unique — nothing else has it |
|---|---|---|
| Power rankings | Scoring leaders (Players) | **Tagging coverage** |
| League power landscape | Search (Rankings has one) | **Game of the season** (WP ribbon + GEI) |
| Luck: actual vs expected wins | | **This week in the league** |
| Top team pulse gauges | | **What the data noticed** |
| | | **Notables** (streaks, double-doubles, top games) |

Plus **"Jump in"** (`:699-724`): eleven `st.page_link`s that are a worse copy of
the sidebar, and stale — missing Whiteboard, Hall of Fame and FAQ, and it labels
`11_Setup.py` "Setup" while the sidebar calls it "Roster & District". Delete
outright, no discussion needed.

**Recommendation: keep it, rename it "League", cut the four Rankings duplicates
and "Jump in".** 725 → roughly 400 lines. The honest split is Team Dashboard =
your team, League = the field, and today the Hub is neither because it opens
with four charts a coach has already seen on Rankings. The five unique surfaces
are good and have no other home.

It also stops being an empty page the moment B1 lands — which is the real reason
it currently reads as dead weight.

**Alternative if you'd rather not maintain it:** move Tagging coverage onto
Settings (it is an admin read), Game of the Season and This week onto Rankings,
and delete the page. I do not recommend this — it puts league content on a page
about ranking — but it is a defensible cut and it is your call, not mine.

---

## CHEAP ENGINE WINS

**`archetypes._choose_k` fits KMeans 60 times per call.**
`helpers/archetypes.py:167` loops `k = 4..8` fitting
`KMeans(n_init=10)` (`:183`) — 50 fits — then `_fit_kmeans` (`:161`) does 10
more. On ~100 players × 10 features. It costs **2.5 s inside
`player_ratings._archetype_anchors`**, which is 30% of `player_stat_table`'s
8.6 s warm profile (the other 4.2 s is `_pure_rapm_cached`, which is doing real
work).

`n_init=3` plus memoizing `k` on the matrix fingerprint takes it to roughly
0.3 s. Silhouette ordering is stable at `n_init=3` on this shape — but per the
house rule, **gate it**: assert the chosen `k` is unchanged across the book
before adopting, since `k` feeds the archetype taxonomy and therefore the team
prior.

---

## WHAT I CHECKED AND FOUND FINE

Recording these so they don't get re-surveyed:

- **Tagging denominators** — `defenses.py` and `playtypes.py` both carry
  `total_tagged` / `untagged` correctly. No baseline is polluted by the
  untagged games. (Detailed above.)
- **Indexes** — 32 indexes; `games` is covered on tracked / team1 / team2 /
  season / date. At 13k games none of this is the bottleneck; the cost is Python
  (RAPM, KMeans), not SQLite.
- **`hockey_from_id` 100% NULL** — known and by design; HAST stays inert until
  tagged. Not a bug, do not "fix" it.
- **`official_id` NULL on 86% of events** — correct: officials are attributed on
  fouls only, and fouls are 1,115 of 7,731.
- **The Insights deck** — 135/135 checks green against the real book.
- **Branch hygiene** — everything merged and pushed, tree clean.

---

## PROPOSED OVERNIGHT DUTIES — ranked, each with its done-test

Ordered by (coach-felt value ÷ risk). Numbers 1-4 are mechanical and low-risk;
5-6 need a judgement call first.

**1 · Cache clears stop being global.** Route the 45 in-process
`st.cache_data.clear()` calls through a scoped `ui.clear_scope(gender, season)`;
the settings-only sites clear nothing.
*Done-test:* a Setup roster save leaves a warm Team Dashboard warm — assert the
Insights section still renders in <2 s immediately after the save, and that a
tracked-game write to the *other* gender does not.

**2 · `_finished_games` gets the rollover fallback (B1).** New
`seasons.default_results_season()` (finished games, not tracked), default
`_finished_games(season=None)` to it, and fix the entitlement `"Current"`
defaults on the same pass.
*Done-test:* a new `tracker/test_results_season_rollover.py` that **fails before
the fix** (the house rule from `test_team_game_pool_rollover.py`) plus an
AppTest asserting Analytics Hub renders >5,000 chars of body under a
`Current`-empty book.

**3 · Projection and Schedule get their `@st.cache_data` (B2).**
*Done-test:* re-run the view-timing harness; warm Projection <1.5 s, warm
Schedule <2 s, and the rendered markdown is byte-identical to today's.

**4 · The three data slips (B3, B4, B5).** Flip `games.id=4`; dedupe the nine
game rows (and fix the mirror case in `game_dedup.py`, which is the actual bug);
resolve the `#4` jersey collision.
*Done-test:* the tracked-vs-events guard passes; no `(team1,team2,date)` or
mirrored pair returns >1 row; no active-season team has two active players on
one number. Also re-run `test_charges.py::test_real_book_encoding` — the
`game_events.id=7101` charge slip is still unfixed on `main` and is one click in
the Event Editor.

**5 · Analytics Hub cut** — *needs your ruling on rename-vs-delete first.*
*Done-test:* the four duplicate sections and "Jump in" are gone, the five unique
surfaces render, and the page is under 450 lines.

**6 · `foul_type` (B6)** — *needs your ruling on wire-vs-drop.* If wire:
tracker chip row + Event Editor column + backfill NULL, then it feeds the
officials rework rather than arriving after it.

**Not in this list, deliberately:** the officials rating rework, which is
already the standing headline item and is a bigger piece of thinking than an
overnight duty; iPad Mode (N4), now unblocked since the tablet layout reached
`main`; and the eager `st.tabs` conversion, which wants the AST sweep first and
should not be run unattended.
