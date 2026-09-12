# HoopTracks — The Freeze Book
### The pre-October sweep. What was measured, what is left, and the one read that would justify the whole product.

Written 2026-09-12, after a full-app scrub run against **production**, not
against the repo and not against `%LOCALAPPDATA%`.

This is a companion to `THE_BOOK_2026-09.md`, not a replacement. THE BOOK is
still the entry point for *why* the app is shaped the way it is and what the
fourteen rulings settled. This document answers one question THE BOOK could not
answer in September, because the work had not happened yet:

> **Is it safe to freeze this and hand it to five coaches in October?**

**Yes.** With four things to do first, none of which is code, and one easy win
that is worth more than all four.

---

## How this was measured

Everything below was measured, not read. The methods, so the next person can
reproduce or contradict them:

| what | how |
|---|---|
| The book | `tools/pull_prod_snapshot.py` → `~/app5_prod/analytics.db`. 13,383 games, 63 tracked, 11,402 events, 1,448 teams, 608 players. `integrity_check=ok`. |
| Page health | `tools/freeze_smoke.py` — **new in this sweep**. Renders all 15 pages through `AppTest`, as three personas, against that book. |
| Page cost | The same tool, run **on the droplet** through `.venv/bin/python`, because a 1 vCPU box is the only machine whose timings mean anything. |
| Engine health | `pytest -q` (495) and `tracker/run_all.py` (106), locally; `run_all` again on the droplet's own interpreter. |
| Ops | `ssh` to `107.170.27.154` — `systemctl`, `crontab`, `litestream`, `df`, `free`. |
| Data integrity | `tools/repair_book.py` dry run against the snapshot, byte-identical to production. |

Nothing was written to production. The only thing placed on the droplet was
`/tmp/freeze_smoke.py` and an empty `/tmp/p3book` directory, both disposable.

---

# I · THE VERDICT

## 1 · Freeze-ready, and the evidence is better than last time

Three months ago the honest answer would have been "probably". It is now
"yes", and the difference is that there is a measurement behind each claim.

| check | result |
|---|---|
| Production vs `main` | `cb65e75` on both. Nothing unpushed, nothing undeployed, working tree clean. |
| `pytest -q` | **495 passed**, 0 failed |
| `tracker/run_all.py` | **106 passed**, 0 failed, 0 timeout |
| **Every page, every persona** | **45 renders, 0 exceptions** (15 pages × admin / paid / free) |
| **Day-one coach** (team with zero tracked games) | **15 renders, 0 exceptions** — the empty states hold |
| Backups | **Litestream → Cloudflare R2, lag −1s, continuous since 2026-09-04** |
| October instrumentation | **built and live** — 19 page-view rows on production |
| `TODO` / `FIXME` / `XXX` / `HACK` in `helpers/`, `pages/`, `database/` | **zero** |
| bare `except:` in the same tree | **zero** |
| Dependency drift on the one that bit you | `streamlit==1.58.0` pinned; production matches |

That last pair is worth sitting with. This is ~92,000 lines of Python across
15 pages and 110 engine modules, and it carries **no debt markers and no silent
exception swallowing**. That is not normal, and it is the single best reason to
believe the freeze will hold through March.

## 2 · The punch list, re-measured — four of six can be struck

`FREEZE_PUNCHLIST_2026-09-09.md` listed six items. Three days and two sessions
later, **four are closed** and the two that remain are both one command.

| # | item | state today |
|---|---|---|
| 1 | *"No timers, no cron, **no backups**"* | **HALF WRONG — struck in part.** See §3. Backups exist and are healthy. The timers genuinely do not. |
| 2 | `repair_book.py` never run on production | **STILL OPEN.** One command, one judgement call. §4. |
| 3 | Three sites re-widen an entitlement-scoped id set | **CLOSED.** All three now use `as_scope` / early-return. Verified at `insights_team_read.py:62`, `insights_tab.py:631`, `6_Team_Dashboard.py:6411`. |
| 4 | Two suite tests priced to a book that no longer exists | **CLOSED.** `run_all` is 106/0. Both were re-priced. |
| 5 | Phase 1 instrumentation is not built | **CLOSED.** `helpers/telemetry.py` is written, wired at three call sites, and has **19 real rows on production**. |
| 6 | 23 games wearing the season sentinel | **STRUCK 2026-09-13.** The premise was wrong; `'Current'` *is* the stamp an active-season row carries. |

### §5 deserves a correction, not just a strike

The punch list said *"`grep page_view` returns nothing"*. It now returns three
production call sites, and they are placed with more care than the item asked
for:

* `helpers/ui.py:258` — `page_view`, inside `page_chrome`, **deduped on the
  actor's last page** so a rerun storm writes one row, not forty.
* `helpers/ui.py:730` — `empty_hit`, funnelled through the one `empty_state`
  renderer, deduped per `(actor, site)`.
* `helpers/auth.py:237` — `coop_toggle`, never deduped, because every flip is a
  fact and there are ten a season.

All three are wrapped so that a telemetry failure cannot reach page boot. The
counters are the only evidence that will ever exist about what five brand-new
coaches did on training day, and they are collecting now rather than being
switched on that morning.

---

# II · THE TWO OPS BLOCKERS, RE-MEASURED

## 3 · Backups exist. The punch list was wrong about this, and it matters

The punch list checked `ls ~/backups`, got "No such file or directory", and
concluded **"there are no backups at all"**. That conclusion was the single
scariest line in the September documents and it is not true.

```
systemctl list-units | grep litestream
  app5-litestream.service   loaded active running
      Litestream continuous backup of the APP5 SQLite DB
```

```
litestream generations -config /etc/litestream.yml /var/lib/app5/analytics.db
  name  generation        lag  start                 end
  s3    eca027e59a9c3621  -1s  2026-09-04T00:34:12Z  2026-09-12T22:17:19Z
```

Continuous WAL replication to a Cloudflare R2 bucket, **lag −1 second**,
hourly snapshots, unbroken for eight days. `/etc/litestream.yml` is
`-rw------- app5:app5`, which is the correct mode for a file holding a live
secret.

This is a *better* backup than the `~/backups` tarball the punch list wanted.
A nightly tarball loses up to 24 hours; this loses one second.

### What is still genuinely missing — and it is smaller than it looked

| job | state | real urgency |
|---|---|---|
| **A restore has never been tested** | no evidence one was ever attempted | **This is the actual blocker.** A backup nobody has restored from is a hypothesis. |
| **Retention is 168h** | `retention: 168h` in the config | Seven days. A corruption found on day eight is unrecoverable. For a season that runs November–March, this is the wrong number. |
| `ANALYZE` | run **once**, ever (`sqlite_stat1` = 40 rows) | Low. The query planner's stats go stale slowly on a book this shape. |
| rating-history rebuild | 13,807 rows, newest day 2026-03-14 | **Medium.** It stops moving the day the season starts, and `resume.quality_wins`, the Hall of Fame board, and the Schedule's `Rk @` column all resolve against it. |
| `auto_season_rollover.py` | written, idempotent, not installed | **Low, and lower than the punch list thought.** Production's `active_season` is already 2026-2027. The next real boundary is **1 October 2027**. |

**The fix list, in the order that matters:**

1. **Test a restore.** `tools/verify_backup.py` exists. Point it at the R2
   replica, restore to a scratch path, run `integrity_check`, count the games.
   Thirty minutes, and it converts a hypothesis into a fact.
2. **Raise `retention` from `168h` to at least `2160h`** (90 days) before
   November. One line in `/etc/litestream.yml`, one `systemctl restart`. The
   season is five months long; a seven-day window cannot cover it.
3. Install the two timers that actually go stale in-season (`ANALYZE`,
   rating-history rebuild). The rollover timer can wait a year.

## 4 · `repair_book.py` — still never run, and one row needs your eye

Unchanged from 2026-09-13. **43 findings**, re-confirmed today against a fresh
snapshot. Two classes are fixable, the rest are report-only by design.

**Class 1 — 2 games carry events but `tracked=0`:**

```
game 4      2025-12-10   2025-2026   61 events
game 13959  2026-02-10   2025-2026   11 events
```

72 tapped events that are invisible to every tracked pool, every rating, and
every insight. Someone did that capture work and the app throws it away.

**Class 2 — 9 duplicate matchups**, all untracked, all carrying a score, so
**every one of those nine results counted twice** in W–L, SOS and the
results-only power ratings.

**One of the nine still needs a human.** Yukon vs Alva, 2026-01-10:

```
KEEP  id=323    score=43-55  loc='Wheat Capitol'
drop  id=22449  score=44-53  loc=''
```

The two rows **disagree on the score**. Every other pair matches (sometimes
home/away flipped). The tool keeps `323` — the one with a venue, which is the
better provenance signal — but that is a guess about somebody's actual game and
it should be yours.

**And it is holding an index open.** `ux_games_matchup` does not exist on
production. That is *by design*, not a deploy failure: `database/db.py:729`
documents that a `CREATE UNIQUE INDEX` over a table holding duplicates raises
`IntegrityError`, the migration records the skip, and boot continues. The index
takes on the **first boot after the repair**. So the duplicate-game class is
closed in code and open in production, and will stay that way until this runs.

```bash
ssh app5@107.170.27.154 "cd app5/APP5.0 && APP5_DATA_DIR=/var/lib/app5 .venv/bin/python tools/repair_book.py --apply"
```

```bash
ssh app5@107.170.27.154 "sudo systemctl restart app5-web"
```

Litestream has you covered on the backup (§3) — but test the restore *first*,
because this is the first write where you would want it.

---

# III · WHAT THE SCRUB FOUND THAT NOBODY KNEW

Five findings, none of which appear in any previous document. Two are
freeze-relevant, one is a real bug, one is a measurement that changes a
priority, and one is the best thing in this report.

## 5 · Every October coach lands on a code path production has never run

```sql
SELECT email, plan FROM app_users;
-- all six rows: plan = 'paid'
```

`helpers/auth.py:77`'s `add_user` takes `email`, `role`, `name`, `added_by` —
**and never sets a plan.** New rows take the schema default:

```
database/db.py:440
ALTER TABLE app_users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'
```

So: production has six users, all Paid, and **zero Free users have ever
existed**. In October five brand-new coaches are added, every one of them lands
on `plan='free'`, and the most-travelled path in the app next month is the
least-travelled path in its history.

**This was the highest-value thing to measure, so it was measured.**
`tools/freeze_smoke.py` renders all 15 pages as a Free coach against the
production book. Result:

> **15 renders, 0 exceptions.** And again for a *day-one* coach whose team has
> games on the schedule but zero tracked games: **15 renders, 0 exceptions**,
> with Team Dashboard correctly collapsing from 14,594 characters to 5,964 —
> the empty state, rendering as designed rather than as a blank.

**The Free path holds.** This is now measured rather than assumed, and the tool
that measured it is committed so it can be re-run after any change.

One thing the measurement also shows, which is a *ruling*, not a bug:
`7_Players.py` renders **100,603 characters for Free and 100,603 for Admin** —
byte-identical. THE BOOK already retracted this as a defect: *"Free sees the
paid product is not a bug, it is the funnel."* Recorded here only so the next
reader does not re-open it.

## 6 · Cold page cost — one page is bad for a Free coach, four are bad for a Paid one

This is the freeze finding that is actually about the software, and it is worse
than it first looked, because **the cost lives in the Paid tier** — which is
where every paying customer lives, and where you live.

Measured on the droplet — the real 1 vCPU box, production book, cold cache:

| page | **Free** | **Paid / admin** | |
|---|---:|---:|---|
| **7_Players** | **51.91s** | **68.70s** | eager `st.tabs` |
| **2_Game_Tracker** | 2.46s | **38.87s** | §6.2 |
| **6_Team_Dashboard** | 7.81s | **34.04s** | the shared `team_bundle` |
| **9_War_Room** | 5.71s | **21.45s** | real Monte-Carlo work |
| 14_Hall_of_Fame | 8.26s | 9.25s | eager `st.tabs` |
| 8_Officials | 5.14s | 6.01s | |
| 5_Rankings | 2.10s | 4.95s | |
| 4_Schedule | 1.26s | 2.45s | |
| 1_Input_Hub | 1.11s | 2.34s | |
| the other six | ≤ 0.6s | ≤ 0.4s | |

Two readings of that table, and the second one is the important one:

* **For a Free coach — the October persona — fourteen of fifteen pages are
  fine.** Only Players is bad. That is a genuinely good freeze position.
* **For a Paid coach, four pages cross twenty seconds.** The gating that
  unlocks tracked depth is also what unlocks the cost, and nobody has ever
  measured it, because the founder's own caches are warm from the moment he
  opens the app.

A coach who clicks "Players" waits the better part of a minute and concludes
the app is broken — and Players is the page they will click first, because it
is the one with their kids' names on it.

### The profile says exactly why, and the fix is already invented

`cProfile` on the droplet, 74.9s under instrumentation:

```
74.92s  pages/7_Players.py:1(<module>)
  45.77s  pages/7_Players.py:1467(_fx_prof)          ← Player Profile tab
    39.38s  player_card.py:842(render_card)
      23.51s  player_card.py:531(_insight_feed)      ← the single biggest leaf
       6.35s  player_card.py:206(build_card_ctx)
       5.98s  player_card.py:476(_war)
       5.97s  player_card.py:447(_rapm)
       4.97s  player_card.py:141(_ctx_archetypes)
       4.93s  player_card.py:659(_render_matchups)
  12.00s  pages/7_Players.py:1547(_fx_plab)          ← Lab tab
   7.62s  pages/7_Players.py:340(_stat_table)
```

The cause is one line:

```python
pages/7_Players.py:569
(tab_lead, tab_rate, tab_impact, tab_shot, tab_cmp, tab_prof, tab_plab,
 tab_gloss) = st.tabs([...])
```

**`st.tabs` renders every tab body eagerly.** Eight tabs, all computed before
the coach sees anything, including the two expensive ones. `@st.fragment` does
not save you here — a fragment still runs on the first full render. The coach
pays 45.8 seconds for the Player Profile tab whether or not they ever click it.

**Players is the last big page still on `st.tabs`.** The Insights tab solved
this exact problem with `_seg` — a segmented control that renders **one** body —
and Team Dashboard, Charts, Lab, Quarters and the Event Editor have all been
converted. The pattern is proven, the helper exists (`_sub_seg`,
`pages/6_Team_Dashboard.py:1830`), and the known hazard has a tool:
`tools/seg_leak_sweep.py` catches the cross-tab variable leaks that a
`st.tabs → _seg` conversion turns from silent bugs into `NameError`s. It reports
**CLEAN** on all three pages already converted.

> **This is the one code change worth making before the freeze.** It takes the
> page from 52s to roughly the cost of whichever tab opens first — call it
> 5–8s — and it uses a pattern that has already shipped five times.

**`14_Hall_of_Fame.py:372` has the same defect** (three eager tabs, 9.25s) and
the same fix. It is a smaller win on a page coaches open less, so it rides
along or it waits.

**The other three expensive pages are not this problem.** Team Dashboard's top
level is already `_seg` — its 34s is the shared `team_bundle`, measured at 8.09s
on the droplet for Adair's 26 tracked games, paid on every leaf. War Room is
already fully `_seg` and its 21s is real Monte-Carlo work. Both are known,
neither is cheap to fix, and neither is a September job.

## 6.2 · Game Tracker sorts 13,383 games in Python, one `pd.to_datetime` at a time

`2_Game_Tracker.py` is the second-worst page for a Paid coach (38.87s), and the
profile turned up something specific and cheap:

```
13383 calls   1.963s   pages/2_Game_Tracker.py:293(<lambda>)
```

Thirteen thousand three hundred and eighty-three calls — **once per game in the
entire book** — on the page whose job is tracking *one* game.

```python
pages/2_Game_Tracker.py:293
all_games = sorted(all_games,
                   key=lambda g: pd.to_datetime(g["date"], format="mixed",
                                                errors="coerce"),
                   reverse=True)
```

`format="mixed"` makes pandas re-sniff the format **for every single row**.
Measured against the production book: **all 135 distinct dates in `games` are
`YYYY-MM-DD`**, with none malformed. ISO dates sort lexically, so
`ORDER BY g.date DESC` in the query that is already being run is exactly
equivalent and costs nothing — SQLite does the whole thing in 0.02s.

**~2 seconds, deleted, by moving one sort into SQL.** The safety argument is
the date audit above, and it should be pinned by a test so a future non-ISO
date fails loudly rather than silently mis-ordering the picker.

The same profile shows `_pure_rapm_cached` at **7.05s, called twice** (once per
team). That one is real work and correctly cached; it is noted only so the next
reader does not re-derive it.

### The smaller performance note

`14_Hall_of_Fame.py` is also the **only expensive page that never calls
`ui.declare_scope`**. Five pages declare their `(gender, season)` pool so a
live-game write to a *different* pool no longer dumps their warm cache; Hall of
Fame does not, so it pays its 9 seconds again after any write anywhere. One
line, same shape as the other five.

## 7 · The suites have never run on production's dependency stack

`requirements.txt` carries a nine-line comment explaining why Streamlit is
pinned — production drifted to 1.58.0 while the dev machine sat on 1.54.0, the
suites could not reproduce a prod-only break, and the hour spent proving the
Whiteboard crash was version-independent is "the cost this pin removes".

**One line below that comment, `pandas` floats.** And it has drifted further
than Streamlit ever did:

| package | local (where 601 checks run) | production |
|---|---|---|
| streamlit | 1.58.0 | 1.58.0 ✅ |
| **pandas** | **2.3.3** | **3.0.3** |
| scikit-learn | 1.8.0 | 1.9.0 |
| numpy | 2.4.2 | 2.4.6 |
| uvicorn | 0.52.4 | 0.49.0 |
| fastapi | 0.139.2 | 0.136.3 |

**A major version apart on pandas**, in an app whose every page builds
DataFrames. Pandas 3.0 made copy-on-write the default and removed a pile of
silent-downcasting behaviour. Every one of the 601 green checks is green on
pandas 2.

### So it was measured, and the news is good

`pytest` is not installed on the droplet — which is itself the proof that the
suites have never run there. `tracker/run_all.py` needs no pytest, so it was
run on production's own interpreter against a throwaway empty book:

> **90 passed. 16 failed — and 15 of the 16 are the empty-book artefact**
> ("0 players", "0 games", "0 edges"), exactly as expected when you point a
> data-dependent suite at an empty directory.
>
> **Zero pandas-3 API failures. No `AttributeError`, no copy-on-write
> breakage, no removed-method calls.**

**The risk is real, unmeasured-by-policy, and empirically clean.** The fix is
therefore not to panic — it is to pin the number so the next drift is a
decision instead of a surprise:

```
pandas==3.0.3        # was pandas>=2.3.3 — prod ran 3.0.3 while the suites ran 2.3.3
```

…and to install `pytest` in the droplet venv so the full 495 can run where the
app actually lives.

### The one non-artefact failure, and a second like it

Both are test bugs, both only bite on a book the dev machine never has — which
is to say, **a brand-new coach's book**:

* `tracker/test_hero_ball.py:98` — the engine correctly returns
  `scoring_gini = None` on a book with no rotation (the test *asserts* that
  gate nine lines earlier), and then the diagnostic `print` formats it as
  `:.3f` and raises `TypeError`. The engine is right; the test's own printout
  is not.
* `tracker/test_ordinals.py` — the "no f-string hardcodes a 'th' suffix" sweep
  walks the tree without excluding `.venv`, so on any machine where the venv
  lives inside the app directory it fails on **scipy's source code**. That is
  every deployment, including production.

Neither is a product defect. Both make the suite cry wolf in the one place it
most needs to be trusted.

## 8 · Tag coverage is high enough that the analytics are honest

`helpers/coverage.py` calls itself "the honesty keystone for the whole roadmap"
because half the high-value reads only mean something when the optional one-tap
tags are actually filled in. So here is what production actually carries, on
11,402 events across 63 tracked games:

| tag | filled | of | rate |
|---|---:|---:|---:|
| `possession_secs` | 5,985 | 6,010 shots | **99.6%** |
| `official_id` | 1,659 | 1,659 fouls | **100%** |
| `shot_x` / `shot_y` | 5,781 | 6,010 | **96.2%** |
| `play_type` | 5,590 | 6,010 | **93.0%** |
| `defense` | 5,519 | 6,010 | **91.8%** |
| `rebound_by_id` | 3,250 | 3,773 misses | **86.1%** |
| `guarded_by_id` | 4,604 | 6,010 | **76.6%** ¹ |
| `pass_from_id` | 1,439 | 2,237 makes | **64.3%** |
| `turnover_type` | 1,110 | 2,073 TOV | **53.5%** |
| `shot_created_by_id` | 555 | 6,010 | **9.2%** |
| `hockey_from_id` | 318 | 6,010 | **5.3%** |

¹ `guarded_by_id` NULL is a **value, not a gap** — it means uncontested. The
76.6% is the contested share, not the capture rate.

**This is the number that justifies the product.** A one-person courtside
tapping operation is capturing play-call and defensive-scheme tags on **93% and
92%** of shots. Synergy pays a hundred loggers for that. The two weak columns
(`hockey_from_id` at 5.3%, `shot_created_by_id` at 9.2%) are the two hardest
taps to make in live time, and both are already handled honestly: the passing
graph reads `pass_from_id` and only the 3-node chain needs the hockey column
(`passing_chains.py:186` vs `:318`).

`turnover_type` at 53.5% is the one worth a capture-habit nudge rather than a
code change. Half the turnovers in the book cannot answer "live ball or dead
ball", which is the difference between a transition problem and a decision
problem.

---

# IV · THE BEST THING IN THIS REPORT

## 9 · The shot-distance cliff — measured, unbuilt, and worth the whole product

`THE_BOOK_2026-09.md §13.3` listed *"The 4-foot cliff, as a plan rather than a
read (½ session)"*. It was never built. A grep for a range curve, a distance
band, or a dead-zone read returns **nothing** anywhere in `helpers/`,
`pages/`, or `helpers/dashboard/` — the only `cliff` in the codebase is the
*open-vs-contested* one in `insights.py:153`, which is a different thing.

So it was measured. **5,653 located shots, production, 63 tracked games:**

| band | FGA | FG% | **PPS** | share of shots |
|---|---:|---:|---:|---:|
| **Rim** 0–4 ft | 1,563 | 57.3% | **1.15** | 27.0% |
| **Short** 4–8 ft | 1,290 | 34.0% | **0.68** | 22.3% |
| **Dead zone** 8–20 ft | 844 | 25.6% | **0.51** | 14.6% |
| **Three** 20–26 ft | 1,956 | 29.3% | **0.88** | 33.8% |

Read the two middle rows again.

**36.9% of every shot taken in this league — 2,134 attempts — returns 0.62
points.** Against 1.15 at the rim and 0.88 from three. **Every single shot
between four feet and twenty feet is worth less than a three-pointer.**

And the cliff does not start where anyone expects. It is not a "midrange"
problem. **It starts at four feet.** Two steps off the block, the same shot
that returns 1.15 points at the rim returns 0.68. That is a 41% collapse over
the width of the lane, and it is the kind of fact that makes a coach lean
forward.

### Why this is the thing that pushes the product over the edge

Every other read in the app is *comparative* — you rate out 63rd, your DLOAD%
is high, this lineup is +6. Good, useful, and the coach has to trust the
model to act on it.

This one is not comparative and there is no model in it. It is 5,653 tapped
shots and a distance formula. There is nothing to trust and nothing to explain.
A coach looks at it once and changes what they run in practice on Monday.

It is also the read that **only HoopTracks can make for this league.** Synergy
does not cover Oklahoma 3A girls. The NBA's version of this chart is famous and
useless here, because the NBA cliff is at a different place and these are
fifteen-year-olds. The number above is *their* league, measured on *their*
games, and it does not exist anywhere else on earth.

### What to build, and what to refuse

**Build (½ session, and it is the last thing before the freeze):**

* A range curve on the shot surfaces: FGA and PPS by 2-foot band, team vs
  league pool, with the pool named — the house rule (`cards.pctile_bar`).
* One verdict line above it, because the house shape is verdict-first:
  *"38% of your shots come from the 0.62-point zone; the league takes 37%."*
* The same cut per player on the player card, gated on sample the way every
  other player read already is.

**Refuse:**

* Any phrasing that turns this into a forecast. `reliability.py` already
  measured and refused that premise — shot quality predicts future scoring at
  r = .176 while past scoring predicts it at r = .655
  (`xppp-prediction-refused`). This is a **description of shots that were
  taken**, and it must be phrased that way or it joins the list of things the
  app was right to throw out.
* Any "you should shoot more threes" conclusion. The app reports the exchange
  rate; the coach decides what to run. Stating 0.62 against 0.88 is the honest
  read. Telling a coach to stop taking the shot their offense is built to
  generate is not.

### One number that is not a bug, recorded so nobody re-finds it

Four consecutive distance bands read **29.3%**: 18–20ft (12/41), 20–22
(269/918), 22–24 (211/721), 24–26 (93/317). Four different numerators over four
different denominators landing on the same figure looks exactly like a data
artefact and is not one — three-point percentage really is flat with distance
beyond the arc. Checked, and clean.

---

# V · THE SECOND AI'S BLUEPRINT, SCORED

The blueprint asked for a "full-stack basketball intelligence system". Scored
honestly against `helpers/`, the verdict is: **you have built roughly 70% of
it, you refused about 10% for good measured reasons, and about 20% requires
hardware you do not have and a document already exists explaining why.**

The blueprint's most useful contribution is not an idea. It is the confirmation
that an outside model, reasoning from scratch, converges on the architecture
you already chose.

## 10 · Section by section

### §1 Data foundation — **replaced, deliberately, and the replacement is better**

The blueprint opens with "full video capture, player + ball tracking (computer
vision or wearables)". That is the one place it is most confidently wrong for
this product, and `AUTO_TRACKER_FEASIBILITY.md` already says why in more detail
than the blueprint contains:

* Every working system (Pixellot, Veo, Trace, SportsVisio, KINEXON) requires a
  **fixed, elevated, full-court camera**. Nobody solves handheld.
* **Synergy and Hudl Assist still use human taggers in 2025-26** — Synergy runs
  100+ loggers. The two most accurate basketball products on earth have not
  automated.
* Jersey-number attribution, the brittle link, reads **69–74% in real
  conditions** and hallucinates impossible numbers.

Against which: one person with a phone is capturing `play_type` on **93%** of
shots and `shot_x,y` on **96%** (§8). The tap model did not lose to CV. It
**won on this league's economics**, and it produces the one thing CV struggles
with most — correct player attribution — for free, because a human taps a name.

| blueprint item | status |
|---|---|
| Event tagging: actions, results, coverages, spacing, tempo | **HAVE** — 25 columns on `game_events`; `play_type`, `defense`, `guarded_by_id`, `possession_secs` |
| Possession-level data: creator / extender / finisher / disruptor | **MOSTLY** — `pass_from_id` → `hockey_from_id` → shooter is the chain; `shot_created_by_id` is the screen-assist (extender). Disruptor is `stolen_by_id` / `blocked_by_id`. |
| Derived: xEV, xShot, spacing score, tempo fingerprint | **HAVE ALL FOUR** — `shotquality.py` (continuous xPP-Q + SMOE), `spacing.py` (SpacingIndex), `helpers/quarters.py` (tempo, and the only quarter signal that survived measurement) |
| Multi-angle video, ball tracking, wearables | **REFUSED, with a document** |

### §2 Analytics engine — **have nearly all of it**

| blueprint item | status | where |
|---|---|---|
| Advantage creation / conversion / **destruction** | **PARTIAL** — see §11 | `possession_value.py` walks every possession to its terminal outcome |
| Shot quality vs shot result | **HAVE** | `shotquality.py` SMOE; `deserved.py` |
| Defensive coverage success rates | **HAVE** | `defenses.py` — 13 functions incl. `cross_play_defense`, `team_defense_percentiles` |
| Spacing zones + optimal geometry | **HAVE** | `spacing.py`, `court_geom.py` |
| Defensive gaps + rim deterrence | **HAVE** | `defense_profile.py` — rim-share, interior/perimeter |
| Passing windows + movement trails | **NO** — needs tracking data | — |
| xPPP, xShot | **HAVE the honest half** | `shotquality.py`; the *forecast* half was measured and refused |
| xTO probability | **NO** | — |
| Lineup performance simulations | **HAVE** | `simulation.py` (Monte Carlo), `lineup_projection.py`, `rapm.py` |
| Coverage outcome simulations | **PARTIAL** | `exploit.py` crosses your offense × their defense |
| Role-based evaluation (Creator / Connector / Finisher / Spacer / Disruptor / Anchor) | **HAVE, and learned rather than declared** | `archetypes.py` — k-means with silhouette-chosen k over 21 features, then *names* each cluster from its centroid |
| Context-adjusted efficiency | **HAVE** | `adj_efficiency.py`, `shrinkage.py`, `rapm.py` box prior |

`archetypes.py` deserves a note: the blueprint hands you a fixed list of seven
role names. The app **learns** the roles from the data and names them from the
centroid signature, which is strictly better for a league whose roles do not
match the NBA's. It already emits Movement Shooter, Interior Force, Two-Way
Star, Offensive Engine, Defensive Anchor, Self-Creator, Spot-Up, Screen Setter.

### §3 Coaching layer — **have it, and in the shape the blueprint recommends**

| blueprint item | status |
|---|---|
| Auto scout reports: actions, coverages, lineups, tendencies | **HAVE** — `scout.py` (2,071 lines), `scoutboard.py`, `matchup_sheet.py`, printables |
| Game-plan builder: select actions + coverages, simulate | **HAVE** — `exploit.py` is precisely "what do I call Friday and what do I play on D"; `playbook.py` + Whiteboard |
| Auto-generate matchup recommendations | **HAVE** — `matchups.py`, `player_edge.py` |
| **Auto-generate practice plans** | **NO** — see §12 |
| Practice optimization: load + improvement trends | **PARTIAL** — `development.py`, `fatigue.py`, `rotation_plan.py`; the movement/decision-speed half needs video |
| In-game: best lineup for current flow | **HAVE** — `courtside.py`, `lineup_projection.py` |
| In-game: shot quality + advantage trends, breakdown alerts | **HAVE** — `courtside.py` leverage_now, `runs.py`, `win_probability.py`, `wpa.py` |
| Auto-generated film playlists | **DROPPED** — THE BOOK §13.7, ruling Q9 |
| Self-scout: "how scoutable are we" | **HAVE, and the blueprint did not think of it** — `selfscout.py`, Shannon entropy over the play-call mix |

### §5 What to avoid — **already house rules, all five**

This is the section where the blueprint and the app agree most completely, and
the app got there first and wrote it down:

| blueprint warning | the app's existing rule |
|---|---|
| Over-complication (too many metrics) | `verdict-first-is-the-house-shape` — sentence over chart, enforced by two suites with a named opt-out list |
| Black-box models — coaches must trust outputs | `glossary.py`; every percentile states its pool (`pctile_bar`); `POOL_FLOOR = 10` |
| Box-score reliance is mostly useless | The whole event model; `EVENT_DERIVED_STATS` is the Paid tier |
| Copying Synergy directly — HS needs different insights | THE BOOK §5–§7 scored Synergy and named what it does not do here |
| Ignoring context (teammate-dependent efficiency) | `rapm.py`, `networks.py`, `shrinkage.py`, `adj_efficiency.py` |

### §6 "Holy grail" — two of five are shipped

| blueprint | status |
|---|---|
| Automatic action recognition (CV tagging) | **Refused with a document.** `AUTO_TRACKER_FEASIBILITY.md` |
| Advantage chain visualization | **PARTIAL** — `passing_chains.py` keeps the edge (`networks.py` keeps the possession graph); the chain exists, the visualization is thin |
| Defensive breakdown classifier | **HAVE** — `breakdown.py`, four-factors per `play_type` / per `defense` |
| Player development engine | **HAVE** — `development.py` + `identity.py` cross-season link, honest that it "unlocks after a 2nd linked season" |
| "What If?" simulator | **HAVE** — `simulation.py` + `lineup_projection.py`'s signature-stat optimizer |

### §7 North-star questions — all seven have an engine behind them

| question | answered by |
|---|---|
| Who creates advantages? | `SCE` / `SCCreated%` / `expected_assists` / `passing_chains` |
| **Who kills possessions?** | `possession_value.py`'s leak ledger + `turnovers.py` |
| Which actions generate the best shot quality? | `breakdown.py` × `shotquality.py` |
| Which coverages actually work? | `defenses.py`, `cross_play_defense` |
| Which lineups produce the best spacing? | `spacing.py` × `lineups.py` |
| Which players make teammates better? | `rapm.py`, `networks.py`, `group_synergy` |
| Who bends the defense / breaks down defensively? | `defense_profile.py`, `breakdown.py` |

**All seven have an engine. Not all seven have a surface** — which is the real
finding of this section, and it is already written down as
`insights-buried-analytics`.

## 11 · The one genuinely new idea in the blueprint

Everything above is either built, refused with a reason, or needs hardware. One
item is none of those:

> **Advantage creation → conversion → *destruction*, as one chain.**

The app has all three pieces and has never joined them. `possession_value.py`
walks every possession to its terminal outcome; `passing_chains.py` keeps the
passer edge; `turnovers.py` types the giveaway. What does not exist is a single
per-player ledger reading:

*"She created 41 advantages, converted 18, and destroyed 9."*

**And the data supports it**, because of a property of the schema that is easy
to miss: the app's locked rule is that **a possession ends on a shot or a
turnover, and free throws never end one** (`possession_value.py`). Both
terminal types are rows in `game_events`. So **every possession in the book is
already terminal and already attributed.** Nothing needs to be captured that is
not being captured.

The honest caveat, and it is a real one: the chain is **shot-anchored**. You
see the passes that ended in a shot (`pass_from_id`, 64.3%) and the possessions
that ended in a turnover (100%), but a possession's *middle* — the pass that
swung it, the drive that collapsed the defense and kicked out — is only visible
where it touched the terminal event. The ledger would therefore be honest as
"advantages that reached a shot", not "all advantages", and it must say so.

That is a Tier-2 build for April, not September. It is listed here because it
is the only thing on the blueprint that is both new and buildable on the data
you already have.

## 12 · The one thing the blueprint has that the app does not, at all

**Practice plans.** A grep for "practice" across `helpers/` and `pages/`
returns three files, and all three are *narrative* uses of the word inside
insight copy. There is no practice-plan surface, no drill library, no
"what should Monday look like" output.

Every input for one already exists: `selfscout.py` knows what you over-run,
`breakdown.py` knows which sets are failing, `development.py` knows who is
regressing, `foul_trouble.py` knows who is costing you quarters, and §9's range
curve knows where your shots are going. The synthesis is missing.

**Do not build it before the freeze.** It is the single best April project,
and it is the natural home for §9's dead-zone read — a range curve tells a
coach what is wrong, a practice plan is what they do about it on Monday. But it
is a new surface with a new vocabulary, and September is not for new surfaces.

---

# VI · THE ANSWER

## 13 · Freeze — after four things, of which one is code

Ordered by what actually stops you.

| # | do this | why | effort |
|---|---|---|---|
| **1** | **Test a Litestream restore.** `tools/verify_backup.py`, restore to scratch, `integrity_check`, count games. | You are about to run `repair_book --apply`, which deletes nine rows. An untested backup is a hypothesis, and this is the week you would want it to be a fact. | 30 min |
| **2** | **Raise `retention: 168h` → `2160h`** in `/etc/litestream.yml`, restart. | The season is five months. A seven-day recovery window cannot cover it. | 5 min |
| **3** | **Run `repair_book.py --apply`**, after ruling on Yukon/Alva. Restart `app5-web` so `ux_games_matchup` takes. | 9 results counting twice in every rating; 72 captured events invisible. Closed in code, open in production. | 15 min + one judgement |
| **4** | **Convert `7_Players.py` from `st.tabs` to `_seg`.** Run `tools/seg_leak_sweep.py` first. Take `14_Hall_of_Fame.py:372` along if it is free. | 52s Free / 69s Paid on the droplet, six times the next-worst page, on the page with the kids' names on it. | ½ session |

**Then the four cheap ones, in the same sitting — all four are one line each:**

* **Move Game Tracker's sort into SQL** (§6.2). ~2s, and all 135 dates in the
  book are ISO, so it is provably equivalent. Pin it with a test.
* Pin `pandas==3.0.3` (§7) — prod runs 3.0.3, the suites run 2.3.3.
* Install `pytest` in the droplet venv, so the 495 can run where the app lives.
* Add `ui.declare_scope` to `14_Hall_of_Fame.py` (§6).

**Then, if there is one more session in the month — and there should be:**

* **Build the range curve** (§9). Half a session, no new engine, no new
  capture, and it is the read most likely to make a coach say *"I did not know
  that"* on training day. Nothing else on any roadmap has that ratio.

## 14 · What to explicitly NOT do before October

* **Do not install the rollover timer as urgent.** Production's `active_season`
  is already 2026-2027; the next real boundary is 1 October **2027**.
* **Do not build practice plans, the advantage chain, or anything from §11–12.**
  April.
* **Do not touch `PREGAME_SD` or `DEFAULT_HCA`.** Both are measured wrong
  (11.0 vs 12.61/13.43; 3.0 vs +1.78 with `neutral` set on 3 rows of 13,383),
  and doing both would overcorrect. Each needs its own gate, and a gate is not
  a September job.
* **Do not "fix" the officiating table on the fan page.** Ruled: it is an
  assigner tool and the lopsided foul split being visible is the point.
* **Do not re-open "Free sees the paid product".** Ruled: it is the funnel.

## 15 · The state of the app, in one paragraph, for whoever reads this in February

92,000 lines of Python, 15 pages, 110 engine modules, 181 test files and 601
green checks. One SQLite book of 13,383 games, 63 of them tracked at
possession level with 11,402 tapped events carrying play-call tags on 93% of
shots and locations on 96%. Six users, all Paid, on a 1 vCPU / 2 GB droplet at
`107.170.27.154`, backed up continuously to Cloudflare R2 with one second of
lag. For a Free coach — the October persona — fourteen of fifteen pages render
cold in under nine seconds; the fifteenth takes fifty-two and the fix is a
pattern that has already shipped five times. For a Paid coach four pages cross
twenty, which is the bill for tracked depth and is the next thing to work on
after the freeze. No `TODO`s, no bare `except`s, and every percentile on screen
states the pool it was drawn from. It is ready.

---

## Appendix · What this sweep added to the repo

| file | what it is |
|---|---|
| `tools/freeze_smoke.py` | Renders all 15 pages through `AppTest` against the production book, as admin / paid / free. Refuses to run without a real book. Prints per-page cold cost, character count, widget count, and flags empty states separately from crashes. Run it on the droplet for numbers that mean anything. |
| `docs/THE_FREEZE_BOOK_2026-09-12.md` | This document. |

```bash
python tools/pull_prod_snapshot.py && python tools/freeze_smoke.py
```
