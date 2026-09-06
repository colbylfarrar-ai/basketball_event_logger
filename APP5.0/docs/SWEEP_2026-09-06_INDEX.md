# Sweep — 2026-09-06 · Index

An eight-part audit of HoopTracks, run over one night. Read-only throughout:
every measurement is against a `sqlite3.backup` copy of the live book, **the live
book was never written to**, and **no application code was changed**. Branch
`sweep-2026-09-06`, unmerged.

One file was added to the repo besides these documents:
`tracker/test_read_filter_empty_scope.py`, which **fails on `main` today** and is
the receipt for Part 1 §2.2.

---

## The five that matter most

**1 · Right now, a Free coach sees the paid product.** Rendered persona by
persona, a free-solo coach's output is byte-identical to admin's on 20 of 24
surfaces, including the whole 202,706-character Players page. Not a bug — the
open-archive rule is correct and was written assuming a live season sits beside
the archive. Between a rollover and the first game of the new year the archive
*is* the product, and that window is four months wide and covers October.
**Needs a ruling.** → Part 1 §1

**2 · Forfeits are in the ratings as real games.** The word "forfeit" appears
nowhere in the tree. 117 games are scored 1–0 or 2–0, and they count correctly in
W-L and wrongly in PPG, points allowed, MOV, Pythagorean, Luck, strength of
schedule and the Power rating. One of them is currently published on the Rankings
Overview as **the best defence in the league** (0.0 points allowed). **Needs a
ruling on the detection rule.** → Part 4 §1

**3 · Six printable reports are built eagerly as function arguments.** Player
card, two game recaps, two scout sheets, a matchup one-pager — each built on every
render whether or not anyone clicks download, and at least four of them drag
matplotlib onto the critical path of a live page. It is why Players is the
slowest surface in the app (56.6 s cold, 43 s of it one figure). All six are fixed
by changing one helper. → Part 4 §5, Part 2 §6

**4 · The app publishes numbers whose sample it does not disclose.** A percentile
over five teams rendered identically to a rank over 748. 0.6 offensive rebounds a
game called "elite". A hair colour named best shared crew. A jersey number leading
the league in rebounding. Seven instances across four pages, all fixed by the same
four rules, and the machinery (`reliability.MEASURED`, `cards.conf_dot`) already
exists. → Part 8 §3

**5 · The War Room's headline tool opens empty for everyone.** The Lineup
Creator's team picker is ranked and defaults to index 0 — the league's #1 team,
which has no tracked data. Twenty-one of the first twenty-one options are empty;
21 of 704 produce anything at all. It is Paid-gated, so the coach paying for it is
the one meeting the empty state. → Part 7 §1

---

## The parts

| part | file | what it covers |
|---|---|---|
| 1 | `SWEEP_2026-09-06.md` | **Gating.** Free / Paid / Co-op end to end: the persona × surface matrix (rendered, with the seeding method), leaks, false denials, and the offseason archive problem. |
| 2 | `…_PART2_TEAM_DASHBOARD.md` | **Team Dashboard**, read on two teams — the flagship and a thin one. Percentile honesty, four on-screen errors, verdict density per view, and the Players perf finding. |
| 3 | `…_PART3_OFFICIALS.md` | **Officiating Lab.** Roadmap item 8 is already done; what is actually wrong is one term at 25% weight. Plus the placeholder-name problem. |
| 4 | `…_PART4_RANKINGS.md` | **Rankings, Schedule, Hall of Fame.** Forfeits, the one-game leaderboards, and the eager-report pattern. |
| 5 | `…_PART5_DATABASE.md` | **The database.** Schema, integrity (perfect), duplicates, indexes, what the data can already support, and growth. |
| 6 | `…_PART6_ENGINES.md` | **Engine inventory.** 898 entry points traced to a page or not, with three of its own findings retracted in place. |
| 7 | `…_PART7_WARROOM_PLAYERS.md` | **War Room and Players.** The empty Lineup Creator, 486 nameless players, and why Matchup is the app's best surface. |
| 8 | `…_PART8_IDEAS.md` | **What to build next.** Ranked across all parts, with four ideas measured and rejected. |

---

## What needs a founder ruling before work starts

1. **The offseason archive regime** (Part 1 §1). Three options costed; a rolling
   window is the cheap correct answer. Everything else in Part 1 sits behind it.
2. **The forfeit detection rule** (Part 4 §1.2). The 1–0 / 2–0 signature is safe
   on this book — 98 games at exactly 2–0 and no genuine 2-point games — but it is
   a data-classification decision, not an engineering one.
3. **Own-creation entitlement** (Part 1 §3.1). Three questions: does it extend to
   the game view, does it survive a coach leaving, and what happens to the 15
   games with no `tracked_by`. Measured cost of the current rule: **14 of 43
   tracked games were typed in by this coach and are invisible to them** as a Paid
   Solo coach.
4. **Two threshold values** — the pool-size floor below which a percentile becomes
   a rank (Part 8 §3), and the default minimum games on the Rankings leaderboards
   (Part 4 §1.1).

---

## Free before breakfast

Under two hours between them, none needing a ruling:

* **`ANALYZE` on the book** — never run, so the planner picks the 13,362-row
  season index over the 43-row tracked index on the app's hottest predicate.
  **1.55 ms → 0.04 ms**, at 74 call sites. (Part 5 §5b)
* **`insights_deck._next_game`** gets the two guards `team_card._next_game`
  already has — the Insights masthead currently advertises a game nine months in
  the past. (Part 2 §1.1)
* **Un-hardcode the two shot-depth captions** — they disagree with each other and
  with the engine two lines below, and one of them shows the girls' league numbers
  to boys teams. (Part 2 §1.2)
* **`default_team` resolution order** — a bare global row shadows every coach
  without a stored preference, so the "land on your own program" fallback never
  runs and a new coach opens on a stranger's team. (Part 2 §1.3)

---

## Corrections to the roadmap and the survey

Recorded here because each one changes what should be built:

* **Roadmap item 8** (officials rating rework, "the biggest single piece of
  thinking on the board") — **already done.** The game-environment terms were
  removed to descriptor status by a completed reliability study, and
  `RATING_MIN_GAMES` is defined and enforced. What remains is one term at 25%
  weight. (Part 3 §2)
* **Roadmap item 4** (quarter analysis, "zero quarter reads in the deck") —
  **wrong.** `_t_quarter` is registered, routed and firing. The gap is the other
  five quarter reads. (Part 2 §4)
* **Roadmap item 5** (season defaults, ✅ DONE) — done for the *render* layer.
  **23 remain in the engine layer**, and `helpers/reports.py:276` is live.
  (Part 1 §5.2)
* **QOL survey B1's Analytics Hub half** — moot. The page was deleted at
  `e2e00cf`. (Part 1 §5.1)
* **QOL survey B6** (`foul_type`, "wire it") — closed the other way: dropped by
  ruling on 2026-09-05. The foul-KIND axis is no longer capturable. (Part 3 §6)
* **The memory note "fetch_events([]) returns everything"** — stale.
  `_game_filter` branches on `is None`; the risk moved up a layer to 35 caller
  sites. (Part 1 §5.4)
* **The session prompt's ENT inventory** ("77 sites across 16 files") — 19 files
  import it, and the list omits `tracker/api.py`, which is a **write** surface
  with its own identity assembly. (Part 1 §5.3)

---

## Method, so any number can be re-run

```
snapshot   sqlite3.connect(live).backup(sqlite3.connect(copy))   # copy named analytics.db
book A     APP5_DATA_DIR=<copy>                                  # as-is; default season is PAST
book B     UPDATE {games,players,rating_snapshots,schedule,team_class_history}
             SET season='Current' WHERE season='2025-2026'       # + players.archived=0
render     chdir APP5.0/tracker  (a secrets-free cwd bypasses auth)
           AppTest.from_file(page, default_timeout=1800); seed session_state; .run()
persona    import helpers.auth as AUTH; AUTH._LOCAL_IDENTITY = <dict>
profile    cProfile around one cold AppTest.run(), sorted by cumulative
```

Two traps worth carrying forward:

* **The persona line is the whole trick.** `require_login()` *writes*
  `_LOCAL_IDENTITY` into `session_state['auth_user']` and returns it, so seeding
  `session_state` directly is overwritten by the first line of every page.
  Rebinding the module global is seen by both entry points.
* **`ta_gender` must be seeded.** Without it the stale global `default_team`
  opens the Team Dashboard on the boys league and silently discards `ta_team` —
  which is how the first pass of Part 2 rendered the wrong team, and how the
  five-team-pool finding was discovered.

---

## Still outstanding

* **Part 9 — glossary and explainers.** Running at the time of writing. Part 8 §3
  overlaps it and should be reconciled against it rather than merged blindly.
* **Setup, Settings, Input Hub, Game Tracker, Event Editor, OSSAA Import,
  Whiteboard.** Not swept. The Game Tracker is the app's only live write surface
  and deserves its own part.
* **Book B's Team Dashboard rows** in Part 1 §1 should be re-run — the fixture
  needed a repair (`players.archived`) that landed after that matrix.
* **Nothing in Part 8 §1 has been prototyped**, so its effort estimates are
  estimates.
