# Sweep — 2026-09-06 · Part 5: the database

Part of the September sweep (Parts 1 gating, 2 Team Dashboard, 3 Officiating Lab,
4 Rankings). Read-only against a `sqlite3.backup` copy of the live book, opened
`mode=ro`. **The live book was never written to.** No application code changed.

Two things to read first, because they change what the rest of the month builds:

* **§6.1** — `helpers/passing_chains.py` is a complete, tested module that returns
  an empty graph on every call, because every entry point drops the row when the
  *hockey* tag is missing and that tag has never been pressed (0 of 4,019 shots).
  The 2-node passer→shooter edge it does not need is fully captured: 2,678 shots,
  780 edges, 54 at ten or more. The module needs a `continue` removed, not data.
* **§6.2** — `possession_secs` is on 100% of rows and is only ever read as a mean.
  Bucketed, early-clock offence (<7s) returns **0.731 PPP** against 0.570 in the
  middle and 0.597 late, on n=5,341, and it survives split-half (0.727 / 0.735 on
  independent halves) and survives excluding transition (0.674 vs 0.566 / 0.597).
  *This team's worst offence is the middle of the shot clock, not the end of it*
  is a non-obvious, gated, coach-facing read that nothing in the app computes.

And one free speed-up: **§5b — `ANALYZE` has never been run on this book**, so the
planner picks the 13,362-row `idx_games_season` over the 43-row `idx_games_tracked`
for `WHERE tracked=1 AND season=?`, measured at 1.55 ms against 0.04 ms on a
predicate that appears at 74 sites.

## One number to reconcile before quoting §6.6

Part 3 of this sweep reports **two officials with five games worked** and the app's
own `official_ratings` table prints `games = 5` for James Francis and Jamie
Waltonbaugh. §6.6 below reports a maximum of four and zero officials at ≥5. The
two counts come from different sources — Part 3 counts distinct `game_id` in
`game_lineup_officials` (138 assignments across 70 officials, which is also what
the app displays), §6.6 counts something narrower. The disagreement does not
change either conclusion: **no official in this book has a publishable sample**,
and at production's 62 tracked games the ceiling is roughly six games each.
Use the crew-table count when quoting what the app shows on screen.

---

# APP5.0 database audit — snapshot 2026-09-06

Snapshot: `scratchpad/book/analytics.db`, 13,377,536 bytes (13.4 MB on disk), WAL empty (0-byte `-wal`).
Opened read-only (`file:...?mode=ro`) with `C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe`.
Nothing in this audit wrote to any database or repo file.

**Season trap honoured throughout.** `games.season` has exactly two values:
`2025-2026` = 13,362 rows and `Current` = 1 row (unplayed). Every count below is
the whole table unless it says otherwise; where season matters I say which.

**Snapshot vs production.** This book carries 43 games flagged `tracked=1` and 44
games that actually carry events (see §4). Production is ~62. Wherever a finding's
magnitude depends on tracked-game count I flag it `[scales with N]`.

---

## 0. Verdicts at a glance

| # | finding | number |
|---|---|---|
| 1 | Referential integrity is **perfect** — 0 orphans on 30+ probes, `foreign_key_check` clean, `integrity_check` ok | 0 / 0 |
| 2 | `hockey_from_id` never tagged, despite a full PWA→API→DB write path and ~8 reader modules | **0 / 4,019 shots** |
| 3 | `passing_chains.py` returns an empty graph, while the 2-node passer→shooter edge is fully captured | 2,678 shots, 780 edges |
| 4 | PHYSICAL rating is glossary-documented with no writer for its inputs | 0 / 541 players |
| 5 | Prior audit's nine duplicate games **all still present** | 5 same-orientation + 4 mirrored |
| 6 | `games.id=4` still has events and `tracked=0` | 61 events |
| 7 | Duplicate `#4` jersey on team 1 still live | ids 257, 424 |
| 8 | `game_events.foul_type` — **fixed**, column dropped | 23 cols, no `foul_type` |
| 9 | 13 more duplicate *teams* (one school, two names) | 14 surplus rows, 67 games |
| 10 | `ANALYZE` has never been run; planner picks the 13,362-row index over the 43-row one | **39× on the hottest predicate** |
| 11 | Shot-clock state never bucketed; early-clock offence is the best band and it survives split-half | n = 5,341 |
| 12 | `possession_secs` has 1,321 zeros and a 275-second "possession" | 17.1% unusable raw |
| 13 | `play_type` / `defense` / `turnover_type` abandoned late in the season | last tagged 02-26 / 02-26 / 02-06 |
| 14 | Officials: 100% capture, still zero officials with ≥5 games | 70 officials, max 4 games |
| 15 | `audit_log` is 56% of all payload; the play-by-play is 21% | 3.07 MB vs 1.14 MB |

---

## 1. Schema inventory

27 tables. Row counts:

| table | rows | | table | rows |
|---|---:|---|---|---:|
| game_event_lineup | 77,309 | | schedule | 30 |
| rating_snapshots | 13,793 | | game_timeouts | 22 |
| audit_log | 13,479 | | fan_views | 14 |
| games | 13,363 | | coach_notes | 11 |
| game_events | 7,731 | | app_settings | 38 |
| teams | 1,448 | | app_users | 2 |
| team_class_history | 1,448 | | coach_teams | 2 |
| game_lineup_players | 857 | | coach_plays | 1 |
| players | 541 | | sqlite_sequence | 12 |
| game_lineup_officials | 138 | | _litestream_seq | 1 |
| officials | 70 | | | |

Empty tables: `change_requests` 0 · `manual_player_box` 0 · `scout_notes` 0 · `tracker_guest_tokens` 0 · `_litestream_lock` 0.

Query used for every column:
`SELECT SUM(CASE WHEN c IS NULL THEN 1 ELSE 0 END), COUNT(DISTINCT c) FROM t`
plus a `TRIM(CAST(c AS TEXT))=''` blank count — SQLite `NOT NULL DEFAULT ''`
columns are blank, not NULL, so a pure NULL-rate hides them.

### 1a. Flagged columns — 100% NULL / constant / near-constant

Categorised by what the repo grep found. **W** = a code path writes it,
**R** = a code path reads it for a user-visible number.

#### (i) Zero readers AND zero writers — schema promises the app does not keep

| column | state | evidence |
|---|---|---|
| `coach_plays.seq_name` / `seq_idx` / `team_id` | 100% NULL over 1 row | Writers exist (`helpers/playbook.py:92-141`, `save_play`/`save_frame`), readers exist (`playbook.py:141` `MAX(seq_idx)`). The table has **one** row, so this is "feature shipped, never used", not dead schema. |
| `_litestream_lock` (0), `_litestream_seq` (1) | — | Litestream replication bookkeeping, not app tables. No repo reference. Expected. |
| `scout_notes` (0 rows) | dead by design | `database/db.py:502-503, 817-838` — explicitly retired into `coach_notes`, "kept for the backfill". `helpers/scoutboard.py:6` documents the retirement. Correctly dead. |
| `teams.notes` (1,439/1,448 blank) | same retirement | 9 non-blank rows are pre-migration residue. |

#### (ii) Writers but NO readers — captured-but-unsurfaced / never varied

| column | state | evidence |
|---|---|---|
| `players.position` | 541/541 **blank** (`''`, NOT NULL DEFAULT) | **W** `pages/11_Setup.py:142` `UPDATE players SET position=?...`. **R** `helpers/dashboard/players_tab.py:69,103` (depth chart), `helpers/scout.py:267`. Editor and three readers exist; the coach has never filled one in. Every position-split view in the app runs on an empty column. |
| `players.availability` | constant `'Active'`, 541/541 | **W** `11_Setup.py:142`. **R** `players_tab.py:82,114` (status dot), `scout_tab.py:452`. Editable, read, never varied — the availability dot is decorative today. |
| `games.location` | 96.3% NULL (12,867/13,363; 129 distinct) | **W** `pages/1_Input_Hub.py:871,896,903`. **R** eight readers — `box_score.py:336`, `public_feed.py` ×4, `sched.py:206`, `news_feed.py:56`, and critically `helpers/game_dedup.py:251` where a non-blank location is a **dedup tiebreak signal**. Dedup is choosing between duplicate rows with this signal absent 96% of the time (see §4). |
| `games.video_url` | 13,363/13,363 **blank** | **W** `1_Input_Hub.py:871,896,903,996`. **R** `sched.py:125,167` ("Film" column), `team_analytics.py:142`. The Film column on the Team Dashboard schedule can never render. |
| `games.neutral` | constant 0 over 13,363 | **W** `1_Input_Hub.py`. **R** `team_analytics.py:142`, `news_feed.py:56`. `db.py:477-481` documents it as a coach override for home/away splits. Never once set → every home/away split treats neutral-floor games as true home games. |
| `teams.in_pool` | constant 0 over 1,448 | Superseded by `teams.shares_pool` (1 row = 1) and `app_users.shares_pool`; `db.py:439-451` documents the succession. Legacy column still carried on the widest table. |
| `officials.archived` | constant 0 over 70 | W/R pair exists, never exercised. |
| `officials.state` | constant `'OK'` over 70 | **R** `helpers/officials.py:64`; part of the `mig_officials_state_unique_v1` unique key (`db.py:863-912`). Constant-but-load-bearing — a uniqueness discriminator, not a display field. **Not a defect.** |
| `game_lineup_officials.slot` | 86.2% NULL (119/138) | **W** `helpers/game_events.py:75-79` (upsert from the tracker's role dropdowns); `game_events.py:57` says an unassigned crew keeps NULL **by design**. Only 19 of 138 assignments carry an R1/R2/U slot, so any crew-role (lead vs trail) analysis has n=19. |
| `players.grad_year` | 77.4% NULL (419/541), 4 distinct | **W** `11_Setup.py:142`. **R** `helpers/development.py:49-82` (`class_of` → Fr/So/Jr/Sr), `helpers/identity.py:134`. Class-based development curves run on 122 rows. |
| `teams.district` | 1,436/1,448 blank, 2 distinct | **W** `11_Setup.py:186`. |
| `app_users.paid_until` | blank ×2 | **R** `helpers/entitlement.py:97` (Stripe poll honours it when set). Correct empty state. |

#### (iii) Readers but NO effective writes — features that silently never fire

| column | rows | evidence |
|---|---|---|
| **`game_events.hockey_from_id`** | **0 / 7,731 tagged (100% NULL)** | The most-instrumented dead column in the book. Write path complete end-to-end: PWA field `['hockey_from_id','Hockey assist']` at `tracker/static/app.js:1899` (+6 refs), API model `tracker/api.py:243,244,273,274,427`, Streamlit `helpers/game_events.py:136-142`, `helpers/event_log.py:32,47,102`. Read path enormous: the whole of `helpers/passing_chains.py` (3-node passing graph), `helpers/involvement.py:102,166,172`, `helpers/player_ratings.py:339-341,1922` (HAST/G leaf), `helpers/dashboard/insights_tab.py:423`, `tracker/test_hockey_assist.py`, `test_hockey_capture.py`. **Not a broken write path** — a tag the coach has never once pressed. Note `passing_chains.py:15` asserts as a "CAPTURE FACT (verified 2026-07-22, re-verified 2026-07-24)" that it is "logged on EVERY shot flow"; the book says 0 of 4,019 shots. That comment describes the UI's *availability*, not capture, and reads as a claim about the data. `passing_chains.REGATE_AT = 50`; current = 0. |
| `players.height` / `wingspan` / `weight` | 0 / 541 (100% NULL) | Readers: `player_ratings.py:683-688` `_PHYSICAL = [("height",1.0,False),("wingspan",0.75,False)]`, `:758` tier map, `:1592`, `:1904`; `helpers/glossary.py:364-365` documents a **PHYSICAL** rating to users; `reports.py:80`, `scout.py:267`, `players_tab.py:69`, `scout_tab.py:665`; `seasons.py:50` carries them across rollover. **No writer anywhere** — `11_Setup.py:142` updates position/availability/handedness/grad_year only; height/wingspan/weight appear in no `UPDATE`/`INSERT` outside `seasons.py` carry-over and the schema. A rated, glossary-documented category with no way to enter its input. |
| `manual_player_box` (0 rows) | full R+W | `helpers/manual_box.py` save/load; read by `helpers/officials.py:173,192`, `player_ratings.py:266`, `hall_of_fame.py`, `entitlement.py:293`, cascade guard `db.py:1088,1124`. Hand-entered box scores for untracked games — never used once, so the officials foul-rate context join at `officials.py:173-192` returns nothing. |
| `change_requests` (0 rows) | full R+W | `helpers/change_requests.py` admin delete-approval queue, wired into `1_Input_Hub.py:13` and `12_Settings.py:304`. Never exercised. |
| `tracker_guest_tokens` (0 rows) | full R+W | `helpers/auth.py:119-136`, `tracker/api.py:79`. Guest-tracker sharing never used. |
| `players.identity_id` | 57.3% NULL (310/541) | Working as designed — `db.py:378-380`: readers resolve `COALESCE(identity_id, id)`, so NULL is the normal unmatched case. 231 rows matched. Recorded so it is not re-flagged. |

#### (iv) Sparse but legitimately sparse (not defects)

`game_events.blocked_by_id` 96.9% NULL (240 tagged), `shot_created_by_id` 95.6%
(341), `turnover_type` 93.4% (512 typed of 1,475 turnovers = 34.7% of the rows
where it can apply), `stolen_by_id` 89.6% (804), `secondary_player_id` 85.6%
(1,113 — foul rows; per the event-column convention this is the **fouler**),
`official_id` 85.6% (the same 1,113 foul rows). These are conditional columns:
NULL because the event was not a block/steal/foul. §2 separates the conditional
NULL rate from the true coverage rate.

`audit_log.row_id` 96.7% NULL — only INSERTs capture a rowid, and 12,740 of
13,479 log lines are UPDATEs. Expected.

`games.share_token` blank on 13,348/13,363 (15 issued), `is_public=1` on 3 games.
`public_feed.py:124` needs `is_public=1 AND tracked=0 AND share_token<>''`; that
intersection is small by design.

---

## 2. `game_events` in depth — 7,731 rows, 44 games, 2025-12-02 → 2026-03-11

Base query for every number in this section:

    SELECT g.id, g.date, COUNT(e.id) n, SUM(e.<col> IS NOT NULL)
    FROM games g JOIN game_events e ON e.game_id = g.id
    GROUP BY g.id ORDER BY g.date;

### 2a. The overall NULL rate is misleading — split conditional from actual

Most of `game_events` is a sparse union table: a `foul` row has no `zone`, a
`free_throw` row has no `shot_x`. Denominators matter. Event mix is
**shot 4,019 · turnover 1,475 · free_throw 1,122 · foul 1,115**.

| column | naive NULL% | conditional denominator | real coverage | verdict |
|---|---:|---|---:|---|
| `shot_result` | 33.5% | shot or free_throw | **5,141 / 5,141 = 100%** | perfect |
| `shot_type` | 48.0% | `event_type='shot'` | **4,019 / 4,019 = 100%** | perfect |
| `zone` | 48.0% | `event_type='shot'` | **4,019 / 4,019 = 100%** | perfect |
| `official_id` | 85.6% | `event_type='foul'` | **1,115 / 1,115 = 100%** | perfect — every foul names an official |
| `secondary_player_id` | 85.6% | `event_type='foul'` | **1,115 / 1,115 = 100%** | perfect (this is the **fouler**) |
| `possession_secs` | 0% | all rows | 7,731 / 7,731 | values are the problem — see 2d |
| `shot_x` / `shot_y` | 50.9% | `event_type='shot'` | **3,798 / 4,019 = 94.5%** | 3 games missing entirely (2b) |
| `defense` | 24.6% | shots + turnovers | **4,846 / 5,494 = 88.2%** | tag decays (2c) |
| `play_type` | 32.3% | shots + turnovers | **4,534 / 5,494 = 82.5%** | tag decays (2c) |
| `rebound_by_id` | 69.7% | missed shot or missed FT | **2,343 / 2,940 = 79.7%** | 597 misses with no rebounder |
| `guarded_by_id` | 62.6% | `event_type='shot'` | **2,891 / 4,019 = 71.9%** | NULL is a VALUE (uncontested), per repo convention |
| `pass_from_id` | 65.4% | made shots | **976 / 1,474 = 66.2%** | that is the assist rate, not a gap |
| `stolen_by_id` | 89.6% | `event_type='turnover'` | **805 / 1,475 = 54.6%** | the other 46% is the unforced half |
| `blocked_by_id` | 96.9% | missed shots | 241 / 2,545 = 9.5% | plausible real block rate |
| `shot_created_by_id` | 95.6% | `event_type='shot'` | **340 / 4,019 = 8.5%** | screen-assist tag, lightly used |
| `turnover_type` | 93.4% | `event_type='turnover'` | **512 / 1,475 = 34.7%** | **abandoned** (2c) |
| `client_uuid` | 35.4% | all rows | 4,994 / 7,731 = 64.6% | capture-path marker, not a defect (2b) |
| **`hockey_from_id`** | **100%** | `event_type='shot'` | **0 / 4,019 = 0.0%** | **never once tagged** |

`free_throw` rows are internally consistent: 1,122 rows, `shot_result` set on
1,122 (727 make / 395 miss), `shot_type` / `zone` / `shot_x` set on **0** —
correct by design.

### 2b. History artefact vs coach skip vs broken write path

**First, a caution about inferring history from ids.** `game_events.id` does NOT
track game date — game 2 (2026-01-16) holds ids 16–195, while game 86
(2025-12-02) holds 4223–4404. The book has been bulk re-entered / merged, so
"low id = early" is invalid. All timeline reasoning below uses `games.date`.

**`hockey_from_id` — NOT a history artefact.** Games with any non-NULL value:
**0 of 44**, from the first game (2025-12-02) to the last (2026-03-11). A column
that postdates the book shows a clean date cut-in; this shows nothing, ever. The
write path is live end-to-end (PWA field, API field, Streamlit field — §1a-iii).
**This is a coach-behaviour gap, not a broken write.** `helpers/passing_chains.py:15`
records it as a verified "CAPTURE FACT" that the tag is "logged on EVERY shot
flow" — true of the *form*, false of the *book*. The module's own pre-registered
gate `REGATE_AT = 50` stands at 0 of 50.

**`shot_x` / `shot_y` — three whole games, not a coverage ramp.** Games **4**
(2025-12-10, 61 events), **3** (2026-02-13, 172) and **27** (2026-02-20, 169)
have `shot_x` non-NULL on **0** rows — and simultaneously `play_type` 0,
`defense` 0, `client_uuid` 0. The other 41 games sit at 82–100% of shots. These
three were logged through a reduced flow (no court tap, no scheme tags), yet
still carry `zone` and `shot_type` at 100%, so the shot *kind* survives and only
the *coordinate* is lost. 402 events = 5.2% of the book. `[scales with N]`

**`client_uuid` — a capture-path marker, not coverage.** 16 games have it on 0%
of rows, 28 games on 100%. It is the PWA offline-idempotency key
(`tracker/static/app.js:368`, `tracker/api.py:427`); the Streamlit event-log path
(`helpers/event_log.py`) never sets one. The split is scattered across the
calendar (2025-12-10 through 2026-02-20 interleaved), so it says "which tool was
open", not "when". **Consequence:** any replay/de-dup logic keyed on
`client_uuid` protects only 64.6% of the book.

### 2c. Tags the coach stopped using — a late-season decay, visible by date

| game | date | n | `play_type` | `defense` | `turnover_type` |
|---|---|---:|---:|---:|---:|
| 15340 | 2026-02-26 | 152 | 88% | 88% | 0 |
| 28 | 2026-02-24 | 150 | 58% | **0%** | 0 |
| 29 | 2026-02-28 | 183 | **0%** | **0%** | 0 |
| 31 | 2026-03-11 | 163 | **0%** | 6% | 0 |

`play_type`'s last non-zero game is **2026-02-26**; `defense` likewise. The last
three games of the season (28, 29, 31 — the playoff dates) carry plain event
logging only. This is the opposite shape from `hockey_from_id`: a tag that WAS
used and then abandoned under game pressure.

**`turnover_type` is the clearest abandonment.** Non-NULL on **17 of 44 games**,
first `2025-12-08`, **last `2026-02-06`** — nothing in the final 10 games, and
only 12–28% of turnovers inside the games that do have it. Totals: `pass` 284,
`drive` 148, `travel` 57, `held` 15, `other` 6, `shot_clock` 2 = 512 of 1,475.

**`stolen_by_id`** at 805/1,475 (54.6%) is not a gap — the missing 670 are the
unforced half, which is itself the forced-vs-unforced signal. See §6.

### 2d. `possession_secs` — the one real data-quality defect

100% populated, but the *values* are wrong at both tails:

    SELECT COUNT(*) FROM game_events WHERE possession_secs > 35;  -- 120
    SELECT COUNT(*) FROM game_events WHERE possession_secs > 60;  -- 11
    SELECT MAX(possession_secs) FROM game_events;                 -- 275.0

- **1,321 rows at exactly 0.0** (17.1%). 1,101 are `free_throw` (correct — no
  possession clock on a FT) and 177 are `foul` (dead ball, plausible), but
  **14 shots and 29 turnovers at 0 seconds are impossible** and drag any
  possession-length mean toward zero.
- **120 rows above 35s** (a full shot-clock cycle), including a 275-second
  "possession" on a foul and an 84-second shot — stale-timer artefacts where the
  clock was not reset between logged events.
- Otherwise the distribution is real basketball: 0–4s 904 · 4–8s 1,164 ·
  8–14s 1,686 · 14–20s 1,380 · 20–35s 1,131.

Any tempo engine reading this column raw is averaging over 1,321 zeros and a
275-second outlier. The honest denominator is
`event_type IN ('shot','turnover') AND possession_secs BETWEEN 1 AND 35`
(**n = 5,341**).

### 2e. Shot coordinates are internally consistent

`shot_x` ∈ [−23.05, 22.93], `shot_y` ∈ [3.71, 37.81] — a real half-court in feet,
with **zero** (0,0) sentinel rows. `zone` agrees with the sign of `x` in every
bucket:

| zone | n | mean x | mean y | zone set but no x |
|---|---:|---:|---:|---:|
| C (centre) | 2,349 | +0.2 | 10.2 | 118 |
| RC (right corner) | 477 | +17.6 | 9.4 | 25 |
| LC (left corner) | 459 | −18.3 | 8.9 | 20 |
| RW (right wing) | 336 | +13.4 | 21.6 | 28 |
| LW (left wing) | 398 | −14.4 | 21.9 | 30 |

221 shots carry a `zone` with no coordinate (the three reduced-flow games plus
scattered rows). One overtime period exists in the whole book: `quarter=5`,
28 events, 1 game.

---

## 3. Referential integrity — clean in every direction

`PRAGMA integrity_check` → `ok`. `PRAGMA foreign_key_check` → **0 violations**.
Every LEFT-JOIN orphan probe below returned **0**:

| direction | orphans |
|---|---:|
| `game_events.game_id` → `games.id` | 0 |
| `game_events.{primary,secondary,rebound_by,pass_from,shot_created_by,blocked_by,guarded_by,stolen_by,hockey_from}_id` → `players.id` (9 probes) | 0 each |
| `game_events.official_id` → `officials.id` | 0 |
| `game_event_lineup.{event_id,player_id,team_id}` → parents | 0 each |
| `game_lineup_players.{game_id,player_id,team_id}` → parents | 0 each |
| `game_lineup_officials.{game_id,official_id}` → parents | 0 each |
| `game_timeouts.{game_id,team_id}` → parents | 0 each |
| `players.team_id` → `teams.id`; `players.identity_id` → `players.id` | 0 each |
| `games.team1_id` / `team2_id` → `teams.id`; `team1_id = team2_id` self-game | 0 each |
| `rating_snapshots.team_id` → `teams.id` (13,793 rows, 961 distinct teams) | 0 |
| `team_class_history.team_id`, `schedule.{team_id,opponent_id}`, `coach_notes.team_id`, `coach_teams.team_id`, `app_users.team_id`, `fan_views.game_id` | 0 each |

Probe shape used throughout:

    SELECT COUNT(*) FROM child c LEFT JOIN parent p ON p.id = c.fk
    WHERE c.fk IS NOT NULL AND p.id IS NULL;

### 3a. Semantic integrity (stronger than FK) — also clean

| check | result |
|---|---|
| `game_event_lineup.team_id` is one of the event's game's two teams | **0** violations / 77,309 rows |
| `game_lineup_players.team_id` is one of that game's two teams | **0** / 857 |
| the on-floor player's `players.team_id` equals the lineup row's `team_id` | **0** / 77,309 |
| an event's `primary_player_id` belongs to one of that game's two teams | **0** / 7,731 |
| `players.season` vs the `games.season` they appear in | one bucket only: `2025-2026` × `2025-2026`, 308 players, 77,309 rows |

No duplicate composite keys anywhere:
`game_event_lineup(event_id,player_id)` 0 dups · `game_lineup_officials(game_id,official_id)` 0 ·
`game_lineup_players(game_id,player_id)` 0 · `rating_snapshots(day,gender,system,team_id)` 0 ·
`team_class_history(team_id,season)` 0.

### 3b. Three small anomalies worth naming (none are orphans)

1. **One event has a 9-player lineup snapshot.** `event_id=7720`, game 15344
   (2025-12-16), Q4 `0:42`, a `free_throw`: team 1752 has **4** players on the
   floor, team 1755 has 5. Every other event in the book is exactly 5+5
   (7,730 events at size 10, 15,461 team-slices at size 5). Zero events have no
   snapshot at all. Consequence: any per-100-possession on/off number for team
   1752 divides one event by 4 instead of 5. Immaterial at n=1, but it means the
   tracker permits a sub-5 lineup to be saved.
   ```sql
   SELECT event_id, COUNT(*) FROM game_event_lineup GROUP BY 1 HAVING COUNT(*)<>10;
   ```

2. **Three games carry more than a 3-official crew, one carries none.**
   40 of 44 games with events have exactly 3 officials. The exceptions:

   | game | date | n | official ids |
   |---|---|---:|---|
   | 2 | 2026-01-16 | **6** | 1, 2, 3, 29, 31, 33 |
   | 3 | 2026-02-13 | **6** | 4, 5, 6, 29, 31, 32 |
   | 129 | 2026-02-07 | **5** | 26, 28, 33, 59, 61 |
   | 4 | 2025-12-10 | **0** | — (the only game with events and no crew) |

   Games 2 and 3 each look like **two complete crews stacked on one game row** —
   ids 1/2/3 and 4/5/6 are the low-numbered originals, 29/31/32/33 the later
   set. That is the signature of a duplicate-game merge that carried both crews
   across (see §4). Any per-official foul-rate denominator on games 2, 3 and 129
   is inflated: those three games contribute 17 official-game rows where they
   should contribute 9. Against 138 total assignments that is **5.8% of the
   officials denominator**. `[scales with N]`

3. **`game_lineup_officials` has one row on a future game.** `game_id=27077`,
   date `2026-12-08`, official 66, `slot=1` — the single `season='Current'` row
   (Keys vs team 1, `is_public=1`, `share_token='HShbeS8MsqU'`, no scores). This
   is a *pre-assigned* crew for an unplayed game and is correct, but it is worth
   knowing that it is the only row where `slot` is set without a full crew, and
   the only `games` row dated after 2026-06-01.

### 3c. Who owns the tracked games

    SELECT CASE WHEN 1 IN (team1_id,team2_id) THEN 'team 1 plays' ELSE 'other' END,
           tracked_by, COUNT(*) FROM games WHERE tracked=1 GROUP BY 1,2;

| | `tracked_by` | games |
|---|---|---:|
| team 1 plays | *(blank)* | 15 |
| team 1 plays | colbyl.farrar@gmail.com | 9 |
| other teams | colbyl.farrar@gmail.com | 19 |

**19 of the 43 tracked games (44%) do not involve the coach's own team** — they
are scouting/co-op logs of Vinita, Kansas, Jay, Inola, Sequoyah (Claremore),
Adair, Grove, Locust Grove, Salina, both genders. 5 of them carry `in_pool=1`.
This is not a defect; it materially changes what §6 can support, because the
league-context sample is far larger than "my team's games".

**15 tracked games have a blank `tracked_by`** even though the same coach
plainly logged them. `helpers/entitlement.py:369` keys the free-slot / co-op
logic on `tracked_by`; a blank value on a third of the tracked book is a real
gap in that gate's input, not a cosmetic one.

---

## 4. Duplicates and contradictions

### 4a. Re-check of `docs/QOL_SURVEY_2026-09-05.md` — four claims, verbatim verdicts

| prior claim | verdict on TODAY's snapshot |
|---|---|
| **B4 · Nine duplicate games** | **REPRODUCES EXACTLY — all nine, unchanged.** Five same-orientation + four mirrored, and the id pairs match the prior table row for row. Nothing has been deduped. |
| **B3 · `games.id=4` has 61 events and `tracked=0`** | **REPRODUCES EXACTLY.** `games.id=4`, 2025-12-10, Adair Girls vs Ketchum Girls, `tracked=0`, `tracked_by=''`, 61 events, `season='2025-2026'`. Note the direction: the prior wording ("mis-flagged tracked") is easy to read backwards — the game is **not** flagged tracked but **does** carry events, so its 61 events are invisible to every tracked pool. It is the ONLY such row: `tracked=1 AND no events` returns **0**. |
| **B5 · Duplicate `#4` jersey on team 1** | **REPRODUCES EXACTLY.** `players` 257 Carly Buell and 424 Rylee Brown, both `number=4`, `team_id=1`, `season='Current'`, `archived=0`. Both carry distinct `identity_id`s (19 and 190), so this is not an identity-merge artefact — it is two live players holding one number. |
| **B6 · `game_events.foul_type` is a dead column** | **FIXED.** The column no longer exists in `PRAGMA table_info(game_events)` (23 columns, no `foul_type`). `app_settings` carries `mig_drop_foul_type_v1`, and `database/db.py:919-944` implements the retirement with a safety guard that refuses to drop if any row carries a value. The product call in the prior doc was resolved as **drop**, not wire — so the foul-KIND axis it argued for (shooting / common / charge / intentional / technical, and-1 rate, shooting fouls allowed) is now **not capturable at all**. Worth re-raising, because §6 shows the officials data is otherwise the strongest under-used asset in the book. |

One correction to the prior audit's framing of B5: it says "every other apparent
duplicate in the table is a correct season pair". That is **true** — I checked
every number on team 1 and each other collision is exactly one `Current`/`archived=0`
row paired with one `2025-2026`/`archived=1` row. `#4` is the only genuine one.

### 4b. Duplicate games — the full picture

**Same orientation** (`GROUP BY team1_id, team2_id, date HAVING COUNT(*)>1`):
5 groups, 5 extra rows.

| ids | date | scores | note |
|---|---|---|---|
| 124 / 21347 | 2026-01-22 | identical | |
| 142 / 22297 | 2026-01-09 | identical | |
| 453 / 22045 | 2025-12-11 | identical | |
| **323 / 22449** | 2026-01-10 | **43-55 vs 44-53** | **contradiction — the two rows disagree on the score** |
| **14381 / 16419** | 2026-02-05 | **70-68 vs NULL-NULL** | one row unscored |

**Mirrored** (`g2.team1_id=g1.team2_id AND g2.team2_id=g1.team1_id AND same date`):
4 pairs, all four **score-consistent mirrors** (`h1=a2 AND a1=h2`), so no
contradiction — just double-counting.

| ids | date | teams | scores |
|---|---|---|---|
| 400 / 23134 | 2025-12-04 | t214 / t144 | 40-63 ↔ 63-40 |
| 115 / 21345 | 2025-12-11 | t2703 / t7 | 71-33 ↔ 33-71 |
| 158 / 23837 | 2025-12-12 | t2724 / t9 | 56-39 ↔ 39-56 |
| 16621 / 17598 | 2026-01-22 | t1861 / t1934 | 41-76 ↔ 76-41 |

None of the nine are tracked (`tracked=0` on every row), so **no event data is
double-counted** — but W/L, SOS and every `rating_snapshots` power number for
those 18 team-sides is. `helpers/game_dedup.py` exists and still does not catch
the mirror case. Note from memory `merge_teams` makes dup games: `games` has no
UNIQUE constraint on `(team1_id, team2_id, date, season)`, so `UPDATE OR IGNORE`
during a team merge can never collide — the schema cannot prevent this class.

### 4c. Score and flag contradictions

    -- games flagged tracked with no events
    SELECT COUNT(*) FROM games g WHERE g.tracked=1
      AND NOT EXISTS (SELECT 1 FROM game_events e WHERE e.game_id=g.id);   -- 0

    -- games with events not flagged tracked
    ... WHERE g.tracked=0 AND EXISTS (...);                                -- 1  (id=4)

- **0** games flagged tracked with no events.
- **1** game with events not flagged tracked (`id=4`, 61 events).
- **1** same-orientation duplicate pair with genuinely disagreeing scores (323/22449).
- **1** pair where one row is unscored (14381/16419).
- `home_score`/`away_score` are NULL on 722 of 13,363 games (5.4%) — unplayed or
  unscraped, expected.
- **0** self-games (`team1_id = team2_id`).
- **0** duplicate officials by name; `officials.official_id` differs from
  `officials.id` on 69 of 70 rows, i.e. it is a genuine external key, not a copy.
- `team_class_history` (1,448 rows) agrees with `teams.class` on **all** 1,448 —
  it currently carries a single season and duplicates `teams` exactly.

### 4d. Teams that look like one school under two names

Method: uppercase, strip parentheticals, strip GIRLS/BOYS/HS/SCHOOL, strip
non-alphanumerics, group within the same `gender`. 20 collisions, which split
cleanly into two kinds.

**Seven are genuinely different schools** and must be left alone — the
parenthetical my normaliser stripped IS the disambiguator, and each side carries
its own `ossaa_id`: Central (Tulsa) 164827 vs Central (Sallisaw) 164805 (both
genders); Claremore (Sequoyah) 171383 vs Claremore 165135; Sequoyah (Tahlequah)
171404 vs Sequoyah (Claremore) 171382; Wilson (Henryetta) 173385/173384 vs
Wilson 173363/173362 (both genders); Caney Valley OK 164541 vs Caney Valley (KS).
Confirming: **no two teams share an `ossaa_id`** — the partial unique index
`idx_teams_ossaa_id ... WHERE ossaa_id IS NOT NULL` is holding.

**Thirteen are real duplicates** — 14 surplus team rows, all out-of-state or
non-OSSAA opponents where the scraper had no `ossaa_id` to match on:

| ids | names | games each |
|---|---|---|
| 1940 / 2076 | `Desoto Boys` / `De Soto Boys` (TX) | 1 / 1 |
| 1991 / 2134 | `Fayetteville Boys` / `Fayetteville (Fayeteville, Arkansas) Boys` — note the misspelling in the source | 1 / 1 |
| 3028 / 3031 / 3100 | `Grayson Christian Girls` / `... (Texas)` / `... (Sherman, Texas)` | 1 / 1 / 1 |
| 2411 / 2456 | `Grayson Christian Boys` / `... (Sherman, Texas) Boys` | 1 / 1 |
| 1969 / 2202 | `ISchool (Lewisville, TX) Boys` **state=TX** / `iSCHOOL Boys` **state=OK** | 1 / 1 |
| 1802 / 2088 | `Lifeway Christian School Boys` / `Lifeway Christian Boys` | 1 / 1 |
| 3010 / 3045 | `Mercy School Girls` / `Mercy Girls` | 1 / 4 |
| **1827 / 1880** | `OKC Storm Boys` / `OKC Storm (Oklahoma City, OK) Boys` | **15 / 1** |
| 1937 / 2003 | `Piper Boys` / `Piper HS Boys` | 1 / 1 |
| 1794 / 2378 | `Putnam City Heights Boys` / `Putnam​  City  Heights Boys` (double spaces) | 1 / 1 |
| 2559 / 3057 | `South Central, Kansas Girls` / `South Central Kansas Girls` | 1 / 1 |
| **2598 / 3046** | `SOUTHEAST Girls` (5A, ossaa 171647) / `Southeast High School Girls` (no ossaa) | **23 / 1** |
| 3052 / 3109 | `Southwestern Heights Girls` **state=KS** / `South Western Heights Girls` **state=OK** | 2 / 1 |

67 games touch at least one of these 27 rows. Only **2 of the 27** appear in
`rating_snapshots` at all, so the rating damage is small today — but the two that
matter are exactly the two with real schedules (`OKC Storm` 15 games split off 1,
`SOUTHEAST` 23 split off 1), which is where an opponent-strength lookup silently
finds a 1-game team instead of the real one. **None of these 27 rows carries any
`game_event_lineup` data**, so no tracked analysis is affected. `[scales with N]`
— the count grows with every OSSAA/out-of-state import, not with tracked games.

Two of the pairs also disagree on `state` (`ISchool` TX/OK, `Southwestern
Heights` KS/OK), which will scramble any state-level filter.

---

## 5. Indexes

31 explicit indexes plus SQLite auto-indexes. Full list with **actual entry
counts** (an index on a NOT-NULL column has one entry per row):

| index | table | entries | columns |
|---|---|---:|---|
| `idx_ge_game_id` | game_events | 7,731 | (game_id) |
| `uidx_ge_client_uuid` | game_events | **4,994** | (client_uuid) partial, `WHERE NOT NULL` |
| `idx_gel_event_id` | game_event_lineup | 77,309 | (event_id) |
| `idx_gel_player_id` | game_event_lineup | 77,309 | (player_id) |
| `idx_games_tracked` | games | 13,363 | (tracked) |
| `idx_games_season` | games | 13,363 | (season) |
| `idx_games_team1` / `idx_games_team2` | games | 13,363 each | (team1_id) / (team2_id) |
| `idx_games_date` | games | 13,363 | (date) |
| `idx_games_share_token` | games | 13,363 | (share_token) |
| `idx_glp_game_id` | game_lineup_players | 857 | (game_id) |
| `idx_glp_game_player` | game_lineup_players | 857 | (game_id, player_id) |
| `uidx_glp` | game_lineup_players | 857 | (game_id, player_id) **UNIQUE** |
| `idx_glp_player_id` | game_lineup_players | 857 | (player_id) |
| `uidx_glo` | game_lineup_officials | 138 | (game_id, official_id) UNIQUE |
| `idx_gto_game` / `uidx_gto_client_uuid` | game_timeouts | 22 each | |
| `idx_rsnap_board` | rating_snapshots | 13,793 | (gender, system, season, day) |
| `idx_audit_ts` / `idx_audit_actor` | audit_log | 13,479 each | |
| `idx_players_team_arch` | players | 541 | (team_id, archived) |
| `idx_players_identity` | players | 541 | (identity_id) |
| `idx_teams_ossaa_id` | teams | **929** | (ossaa_id) partial UNIQUE |
| `idx_officials_archived` | officials | 70 | (archived) |
| `idx_schedule_date` | schedule | 30 | (date) |
| `idx_chgreq_status`, `idx_mpb_game`, `idx_mpb_team`, `idx_guest_tokens_owner` | (empty tables) | **0** | |
| `idx_cplays_coach`, `idx_cplays_team` | coach_plays | 1 each | |

### 5a. The five heaviest query shapes — is each covered?

Timings are on this snapshot, on a warm cache, SQLite 3.49.1. The prod droplet
is 1 vCPU / 2 GB, so treat these as a lower bound.

**1 · `helpers/stats.py:96 fetch_events(None)`** — the single most-called shape
in the app (154 documented call sites route through `_game_filter`).

    SELECT ge.*, sp.team_id, rp.team_id FROM game_events ge
    LEFT JOIN players sp ON sp.id = ge.primary_player_id
    LEFT JOIN players rp ON rp.id = ge.rebound_by_id
    WHERE ge.game_id IN (SELECT id FROM games WHERE tracked=1 AND season=…)

Plan: `SEARCH ge USING INDEX idx_ge_game_id` + a Bloom filter + two INTEGER PK
lookups. **Covered.** 7,670 rows in 49 ms. Row counts: 7,731 events, 541 players.
*But the subquery is mis-planned — see 5b.*

**2 · `helpers/stats.py:1229 / 1436 / 1492 / 1567 / 2222` — the lineup join**
(assist_rate, corsi, on/off, rebound on/off, all share the shape):

    SELECT gel.event_id, gel.player_id, gel.team_id
    FROM game_event_lineup gel JOIN game_events ge ON ge.id = gel.event_id
    WHERE ge.game_id IN (SELECT id FROM games WHERE tracked=1 AND season=…)

Plan: `SEARCH ge USING COVERING INDEX idx_ge_game_id` then
`SEARCH gel USING INDEX idx_gel_event_id`. **Covered — optimally.** But it
returns **76,699 of 77,309 rows** in 88 ms, and it is re-run per engine. This is
the app's real cost centre and **no index can fix it**: the query genuinely
wants the whole table. The fix is caching one materialisation, not indexing.
The `event_type='shot'` variant (corsi) still reads 39,880 rows / 61 ms because
there is no `game_events(event_type)` index — but see 5c on why adding one is
the wrong call.

**3 · `helpers/officials.py:119` — the foul rows**

    SELECT ge.id, ge.game_id, ge.quarter, ge.time, ge.official_id,
           ge.secondary_player_id, p.team_id
    FROM game_events ge LEFT JOIN players p ON p.id = ge.secondary_player_id
    WHERE ge.event_type = 'foul'

Plan: **`SCAN ge`** — not covered; there is no index on `event_type`. 1,115 rows
out of 7,731 in 5.0 ms. **Do not add an index**: the predicate selects 14.4% of
the table, which is well past the ~5% break-even where SQLite would prefer a
scan anyway, and the row count is trivial. The actual defect here is different:
the function takes `game_ids` and then filters **in Python** (`officials.py:132`,
`rows = [r for r in rows if r["game_id"] in gid_set]`), so it reads every foul in
every season and every game to answer a per-game question.

**4 · `helpers/officials.py:145 _possessions_by_game`**

    SELECT game_id, event_type FROM game_events        -- no WHERE at all

Plan: `SCAN game_events`, 7,731 rows in 6.9 ms, then filtered in Python. Same
shape of problem as #3. A covering index on `(game_id, event_type)` would turn
it into a covering scan, but that buys almost nothing against 7,731 rows —
**pushing the `game_ids` filter into SQL is the fix, not an index.**

**5 · `helpers/team_ratings.py:152 _game_rows`**

    SELECT g.id, g.team1_id, g.team2_id, g.home_score, g.away_score, g.tracked, g.date
    FROM games g JOIN teams t1 ON t1.id=g.team1_id JOIN teams t2 ON t2.id=g.team2_id
    WHERE g.season = ?

Plan: `SEARCH g USING INDEX idx_games_season` + 26,724 PK lookups into `teams`.
13,362 rows in 30.5 ms. **The index is a pessimisation here** — 13,362 of 13,363
rows carry `season='2025-2026'`, so it walks the whole index and then does a
rowid lookup per row. Forcing a table scan (`WHERE +g.season=?`) gives 28.4 ms —
the same, within noise, which is the point: `idx_games_season` on a 2-value
column is buying nothing. The two `JOIN teams` are also pure existence checks
(no column from `t1`/`t2` is selected), so they are ~26,700 needless B-tree
descents. **This is the shape that scales worst**, because it grows with the
*scraped schedule* (already 13,363 rows and rising with every OSSAA import), not
with tracked games.

### 5b. The one concrete, measured index finding: **`ANALYZE` has never been run**

    SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1';   -- 0

No `sqlite_stat1` table exists, and `grep -rn "ANALYZE" --include=*.py` finds
only UI labels (`pages/5_Rankings.py:322`, `pages/7_Players.py:292`) — never the
SQL statement. Without stats the planner guesses index selectivity, and on this
book it guesses wrong on the most-executed predicate in the codebase:

    SELECT id FROM games WHERE tracked=1 AND season='2025-2026';

| plan | rows scanned | time |
|---|---:|---:|
| planner's choice, `idx_games_season` | 13,362 index entries + 13,362 rowid lookups | **1.55 ms** |
| forced `INDEXED BY idx_games_tracked` | 43 index entries | **0.04 ms** |

**39× on a query that appears at 74 grep sites** (`grep -c "tracked=1"` over
`helpers/ pages/ tracker/` = 74) and inside `SEAS.tracked_default_season_sql()`
at 24 more. Selectivity: `tracked=1` is 43 of 13,363 rows (0.32%);
`season='2025-2026'` is 13,362 of 13,363 (99.99%). Running `ANALYZE` once (and
after bulk imports) costs nothing at this size and lets the planner see that.
No schema change, no new index.

### 5c. Redundant indexes (small, but free to remove)

- **`game_lineup_players` carries four indexes over 857 rows**, two of which are
  *the same columns*: `idx_glp_game_player ON (game_id, player_id)` and
  `uidx_glp UNIQUE ON (game_id, player_id)`. `idx_glp_game_id ON (game_id)` is
  additionally a strict prefix of both. Two of the four (`idx_glp_game_player`,
  `idx_glp_game_id`) are dead weight; `uidx_glp` + `idx_glp_player_id` cover
  every access. 857 rows makes this cosmetic today, but it is three write
  amplifications per row instead of one.
- **`idx_games_share_token`** indexes 13,363 entries to serve 15 non-blank
  tokens (`public_feed.py:220 WHERE g.share_token=?`). A partial index
  `WHERE share_token <> ''` would be 15 entries instead of 13,363. Correctness
  is unaffected either way.
- **`idx_officials_archived`** (70 entries, all `0`) and the four indexes on
  permanently-empty tables (`idx_chgreq_status`, `idx_mpb_game`, `idx_mpb_team`,
  `idx_guest_tokens_owner`) cost nothing measurable — listed for completeness,
  not as a recommendation.

**No index is proposed anywhere in this section.** Every shape that is hot is
already covered; the two that scan are scanning 7,731 rows, which is cheaper
than an index would be. The measured win is `ANALYZE`, and the structural wins
are pushing `game_ids` into SQL (#3, #4) and dropping the two dead `teams` joins
(#5).

---

## 6. What the data can already support that the app is not asking of it

The app is not short of engines — `helpers/` carries 100+ modules including
`breakdown.py` (four-factors per `play_type` / per `defense`), `playtypes.py`,
`rebounding.py`, `charges.py`, `rapm.py`, `officials.py`, `coverage.py` (the
capture-honesty gate). So this section is deliberately narrow: only reads where
**the rows exist and nothing consumes them**, each with its n and an honest
verdict on whether that n is enough.

### 6.1 — `passing_chains.py` returns an empty graph while 2,678 tagged passes sit unused ★

**The highest-leverage finding in this audit.** `helpers/passing_chains.py` is a
complete, tested module for "who ignites whom" — the passing graph, and the
stated future home of the wider connection matrix. Every entry point drops the
row when the *hockey* tag is missing:

    passing_chains.py:54   h = e.get("hockey_from_id");  if h is None: continue
    passing_chains.py:318  if e["event_type"] != "shot" or e.get("hockey_from_id") is None: continue

`hockey_from_id` is NULL on **0 / 4,019** shots (§2), so the module returns
nothing on every call, and `player_ratings.py:1922`'s HAST/G leaf is inert.

But the **2-node edge** — `pass_from_id → primary_player_id` — is fully captured:

| quantity | n |
|---|---:|
| shots carrying a passer (PotAST) | **2,678** |
| distinct passer → shooter edges | **780** |
| edges with ≥10 shots | **54** |
| edges with ≥20 shots | 14 |
| edges with ≥40 shots | 5 |
| team 1's own edges with ≥10 shots | **29** |

**Is 2,678 enough?** Yes, comfortably, for the edge-level question the module
exists to answer. 29 team-1 edges at ≥10 shots each is a readable connection
matrix for a 10-player rotation. The 3-node chain needs a tag nobody has pressed;
the 2-node graph needs nothing new at all. `networks.py` covers the *possession*
graph (who is on the floor together), not the ball — the two are different
questions, as `passing_chains.py:4-12` itself says.

### 6.2 — Shot-clock state: captured on 100% of rows, never bucketed ★

`possession_secs` is read in 12 files, but **only ever as a mean** —
`situational.py:142` and `playtypes.py:705` both accumulate `secs_sum / secs_n`
for an average possession length. Nothing buckets it into clock states.

n = **5,341** clean possessions (`event_type IN ('shot','turnover') AND
possession_secs BETWEEN 1 AND 35`, the §2d honest denominator):

| clock state | n | shots | TOs | PPP |
|---|---:|---:|---:|---:|
| early (<7s) | 1,385 | 975 | 410 | **0.731** |
| mid (7–15s) | 2,213 | 1,606 | 607 | 0.570 |
| late (16–35s) | 1,755 | 1,343 | 412 | 0.597 |

**This survives both checks.** Split-half by alternating game date:

| half | early | mid | late |
|---|---|---|---|
| A (22 games) | n=737 **PPP 0.727** | n=1,221 PPP 0.518 | n=858 PPP 0.621 |
| B (22 games) | n=648 **PPP 0.735** | n=992 PPP 0.633 | n=897 PPP 0.573 |

Early-clock PPP is 0.727 / 0.735 across independent halves — the most stable
number in the split. And it is **not just transition**: excluding every
`play_type='transition'` row, early is still 0.674 (n=951) against mid 0.566
(n=1,822) and late 0.597 (n=1,739). Transition is 39.0% of early possessions,
21.5% of mid, 1.1% of late.

**Is n enough?** Yes. Each band clears 1,300 possessions, the split-half holds,
and the confound was priced out. The coach-facing verdict — *this team's worst
offence is the middle of the shot clock, not the end of it* — is the kind of
non-obvious read the Insights tab is built for and nothing computes it.

### 6.3 — Contest value × set call: both halves exist, the cross does not

`guarded_by_id` NULL means **uncontested** (a value, not a gap — repo
convention). Measured over all 4,019 shots:

| | n | FG% | PPS |
|---|---:|---:|---:|
| contested | 2,891 | 33.0% | 0.745 |
| uncontested | 1,128 | 46.1% | **1.082** |

The contest is worth **0.337 PPS** — which independently reproduces the 0.34
figure already on record. Open-shot rate by set call varies four-fold:

| play_type | n | open % | PPS |
|---|---:|---:|---:|
| duckin | 137 | 36.5% | 1.088 |
| transition | 616 | 35.1% | 0.989 |
| offscreen | 132 | 34.1% | **1.227** |
| spot | 873 | 33.9% | 0.828 |
| putback | 298 | 23.8% | 0.859 |
| dho | 122 | 22.1% | 0.639 |
| **iso** | **724** | **12.6%** | **0.588** |
| pnr | 123 | 10.6% | 0.764 |
| post | 210 | 8.6% | 0.933 |

**Is n enough?** For the big cells yes — `iso` at n=724 generating an open look
12.6% of the time for 0.588 PPS, versus `spot` at n=873 / 33.9% / 0.828, is a
1,597-shot comparison and safe. `offscreen` (n=132, PPS 1.227) and `duckin`
(n=137) are the interesting cells and are **too thin to act on** — flag them,
don't rank them. `playtypes.py:698` already counts `p["open"]`, and
`breakdown.py` already does four factors per tag, so this is an unbuilt *cross*,
not an unbuilt capture.

### 6.4 — The 8–16ft dead zone reproduces, at ample n

    SELECT CASE WHEN shot_type=3 THEN 'three' WHEN shot_y<8 THEN 'rim'
                WHEN shot_y<16 THEN 'mid' ELSE 'long2' END, COUNT(*), …
    FROM game_events WHERE event_type='shot' AND shot_y IS NOT NULL;

| band | n | FG% | PPS |
|---|---:|---:|---:|
| rim (<8ft) | 1,423 | 50.0% | 1.001 |
| three | 1,355 | 29.3% | 0.879 |
| **mid (8–16ft)** | **872** | **27.2%** | **0.544** |
| long 2 (16ft+) | 148 | 30.4% | 0.608 |

The mid-range band is worth **0.544 PPS — 46% less than a rim attempt and 38%
less than a three** — on 872 attempts, 21.7% of the shot diet. n is ample. This
confirms an earlier finding rather than discovering one, but it is worth
restating that the evidence has only got stronger.

### 6.5 — Defender-level shot defense: YES. Individual matchups: NO.

2,891 shots carry a named on-ball defender across **260 distinct defenders**.

| threshold | defenders |
|---|---:|
| ≥30 shots defended | 27 |
| ≥50 | **12** |
| ≥100 | 2 |

Among the 12 at ≥50, PPS allowed spans **0.400 (n=115) to 1.259 (n=58)** — a
0.86 spread, well beyond the 0.337 the contest itself is worth, so it is not
purely a contest-rate artefact. **Verdict: rankable, with shrinkage, for ~12
players.** At n=50–115 per defender the standard error on PPS is roughly ±0.13,
so publish tiers, not ranks, and never a leaderboard past the 27 at ≥30.

**The individual matchup read is not available and will not be soon.** Only
**1** (shooter, defender) pair in the entire book has ≥15 shots. A matchup grid
needs a different sampling regime, not more games at this rate.

### 6.6 — Officials: 100% capture, and the n is still not there

Every one of the 1,115 foul events names an official — perfect capture, the best
in the book — plus 138 crew assignments across 70 officials. And it is still not
enough for a per-official verdict:

| games worked | officials |
|---:|---:|
| 1 | 35 |
| 2 | 16 |
| 3 | 13 |
| 4 | **6** |
| **≥5** | **0** |

**Zero officials have worked five tracked games.** The busiest has 4 games / 44
fouls. 135 distinct official *pairs* exist and only **4** have been seen 3+ times,
so crew-chemistry reads are out too. `[scales with N]` — at production's 62
games the ceiling is roughly 6 games per official, which is still not a whistle
profile.

**What IS supportable today**: the *pooled* reads — fouls per possession across
all crews (1,115 fouls / 5,494 shot+TO possessions), and the home/away foul split
pooled over 43 games. **What is not**: any sentence naming a single official.
The good news is structural: `officials.py:41-44` keeps officials career-long and
never archives them at rollover, so this compounds across seasons rather than
resetting — three seasons at this rate puts the busiest crew members past 15
games. This is a *wait*, not a *fix*.

### 6.7 — 5-man units: supportable for the top eight and nothing else

77,309 lineup rows resolve to **597 distinct (team, 5-man unit) combinations**:

| events on the floor | units |
|---:|---:|
| ≥50 | 63 |
| ≥100 | 23 |
| ≥200 | 9 |
| ≥400 | 4 |

Team 1 specifically: 80 distinct units, 15 at ≥50 events, **8 at ≥100**, with the
starting five at 1,266 events and the next four at 549 / 306 / 219 / 148.
**Verdict: on/off at the unit level is honest for team 1's top ~8 units** (the
5th-ranked unit at 148 events is already marginal) and dishonest for the other
72. `rapm.py` and `lineups.py` exist; what is missing is the *gate* — a stated
minimum-events threshold so the 72-unit tail never renders.

### 6.8 — Where the league sample really is

| team | tracked games | events |
|---|---:|---:|
| Adair Girls (t1) | 25 | 4,274 |
| Sequoyah (Claremore) Boys | 8 | 1,325 |
| Kansas Girls | 7 | 1,248 |
| Claremore (Sequoyah) Girls | 6 | 1,075 |
| Vinita Girls / Jay Girls | 5 each | 1,013 / 1,066 |
| …then a tail of 21 more teams at 1–3 games | | |

27 teams and 308 players have on-floor data — but only **6 teams have ≥5 tracked
games** and only **1 has ≥10**. So **team-level league percentiles have an
effective n of 6, not 27** and should not be published as percentiles. The
**player** pool is the better denominator: 308 players on the floor, 22 with ≥50
shots, 6 with ≥100, 2 with ≥200. League z-scores over 22 players are defensible;
over 308 (most of whom played one game) they are not.

### 6.9 — Two capture-honesty gaps `coverage.py` does not cover

`helpers/coverage.py` is the app's stated "honesty keystone" and gates exactly
three tags: `play_type`, `defense`, `guarded_by` (`coverage.py:59,79,124`). It
does **not** gate:

- **`turnover_type`** — 512 of 1,475 turnovers (34.7%), on 17 of 44 games, and
  **last tagged 2026-02-06** with 10 games after it untagged (§2c).
  `helpers/turnovers.py` reads it with no coverage gate, so any live-vs-dead-ball
  turnover split is silently weighted to the first 60% of the season. This is the
  clearest place where an existing read is being computed on a biased sample.
- **`shot_created_by_id`** — 340 of 4,019 shots (8.5%). `rebounding.py` uses it
  as the PnR "roller vs setter" discriminator; at 8.5% capture that split is
  built on a self-selected subset.

Adding both to `coverage.py` costs nothing and is the single cheapest honesty win
in the audit.

### 6.10 — Things the data genuinely cannot support yet (stated so they are not attempted)

| read | rows | verdict |
|---|---:|---|
| hockey assists / 3-node passing chains | **0** | impossible until the tag is pressed |
| foul KIND (shooting / common / charge / intentional / technical) | **0** — column dropped (§4a) | not capturable at all today |
| PHYSICAL rating (height / wingspan) | **0 / 541** | glossary-documented, no writer exists |
| individual (shooter × defender) matchups | 1 pair ≥15 shots | no |
| per-official whistle profile | 0 officials ≥5 games | no — wait for seasons |
| crew-chemistry / pair effects | 4 pairs ≥3 games | no |
| timeout impact | 22 timeouts over 4 games | no |
| position-based lineup/depth reads | `players.position` blank on 541/541 | no input captured |
| home-court vs neutral-floor splits | `games.neutral` constant 0 | no input captured |
| charges as a per-player rate | 55 charges over 308 players | season total only, not a rate |
| rebound LOCATION | not captured; 2,051 misses carry the SHOT's x/y | shot-origin resolution is an upgrade over `rebounding.py`'s zone axis, but it is not the same question — say so in the UI |

---

## 7. Size and growth

    PRAGMA page_size  = 4096
    PRAGMA page_count = 3266     -> 13,377,536 bytes, matching the file exactly
    PRAGMA freelist_count = 0    -> no wasted pages; the file is compact

Measured payload per table (sum of every column's byte length — this excludes
index and b-tree overhead, hence the 2.44× gap to the file size):

| table | payload | rows | B/row | share of payload |
|---|---:|---:|---:|---:|
| **audit_log** | **3,069,493** | 13,479 | 228 | **55.9%** |
| games | 621,206 | 13,363 | 46 | 11.3% |
| game_event_lineup | 608,923 | 77,309 | 8 | 11.1% |
| game_events | 533,096 | 7,731 | 69 | 9.7% |
| rating_snapshots | 504,606 | 13,793 | 37 | 9.2% |
| app_settings | 50,793 | 38 | 1,337 | 0.9% |
| teams | 45,588 | 1,448 | 31 | 0.8% |
| team_class_history | 21,805 | 1,448 | 15 | 0.4% |
| players | 16,802 | 541 | 31 | 0.3% |
| everything else | <16,000 | | | 0.3% |
| **total** | **5,490,968** | | | |

**The play-by-play is not what is big.** Events plus lineups are 1.14 MB of
5.49 MB — 21%. `audit_log` alone is more than twice all the basketball data
combined.

### 7a. `audit_log` dominates, and it is a developer artefact

    SELECT MIN(ts), MAX(ts), COUNT(DISTINCT substr(ts,1,10)) FROM audit_log;
    -- 2026-06-13 23:17:26 .. 2026-09-06 05:39:50, 34 distinct active days

Column split: `detail` **1,683,999 B** (the SQL text — the largest single column
in the database), `params` 676,808 B, `ts` 256,101 B, `actor` 204,267 B.
By table: `games` 7,782 rows, `game_events` 4,634, `players` 572, `teams` 380.
Busiest day 2026-07-01 with 2,647 rows.

Retention exists — `database/db.py:687`,
`DELETE FROM audit_log WHERE ts < datetime('now','-12 months')`, run on every
boot and indexed on `ts` — so this is bounded, not unbounded. But the bound is
**12 months of writes**, and 3 months of the current (heavy, developer-driven:
bulk imports, retracks, dedup passes) write rate already produces 3.07 MB. A
season of ordinary coach usage will be far lighter; a season with another import
campaign will not be. Two honest notes:

- The `DELETE` never `VACUUM`s. `freelist_count` is 0 today, so nothing is
  stranded yet, but once the 12-month window starts evicting, the file will hold
  freed pages until something vacuums. On a droplet this shows up as disk that
  never comes back.
- `detail` storing full SQL text is the whole cost. Storing a statement *hash* +
  the params (already a separate column) would cut `audit_log` payload by ~55%
  with no loss of the moderation trail's actual purpose.

### 7b. Trajectory of the basketball data — 44 → 62 → 200 tracked games

Per tracked game, measured on 44 games: **175.7 events**, **1,757 lineup rows**,
12,116 B of `game_events` + 13,839 B of `game_event_lineup` = **25,955 B/game**
payload. Applying the observed 2.44× file/payload ratio:

| tracked games | events | lineup rows | payload | on disk |
|---:|---:|---:|---:|---:|
| 44 (this snapshot) | 7,731 | 77,309 | 1.14 MB | ~2.79 MB |
| **62 (production today)** | ~10,894 | ~108,935 | 1.61 MB | **~3.93 MB** |
| 200 | ~35,141 | ~351,405 | 5.19 MB | ~12.67 MB |

**Disk is a non-issue.** Even at 200 tracked games the play-by-play is under
13 MB, and the whole database lands around 25–30 MB. On a 2 GB droplet that is
noise.

### 7c. What actually scales badly on 1 vCPU / 2 GB

**1 · The lineup materialisation (§5 shape 2) — the real cliff.**

    SELECT gel.event_id, gel.player_id, gel.team_id
    FROM game_event_lineup gel JOIN game_events ge ON ge.id = gel.event_id
    WHERE ge.game_id IN (SELECT id FROM games WHERE tracked=1 AND season=…)

Returns **76,699 of 77,309 rows in 88 ms** here, index-optimally, and is re-run
by `assist_rate`, `corsi`, on/off and rebound-on/off (`stats.py:1229, 1436, 1492,
1567, 2222`). It is O(tracked games) with a 1,757-row-per-game constant:

| tracked games | rows returned | extrapolated (this machine) |
|---:|---:|---:|
| 44 | 76,699 | 88 ms |
| 62 | ~108,000 | ~124 ms |
| 200 | ~351,000 | ~400 ms |

× 5 engines × a slower single vCPU, and this is where a cold Insights render's
seconds live. **No index fixes it** — the query legitimately wants every row.
The fix is one cached materialisation shared across the engines, which is a
code change, not a schema change.

**2 · `team_ratings._game_rows` grows with the SCRAPED schedule, not with tracked games.**
13,362 rows / 30.5 ms today, with 26,724 pure-existence PK lookups into `teams`
that select no column. `games` gains a full state schedule (~13,000 rows) per
season, so this shape roughly doubles each season while the *useful* data does
not move. Two seasons in, it is ~27,000 rows and ~60 ms per call. Dropping the
two dead `JOIN teams` halves the descents immediately.

**3 · `rating_snapshots` is a weekly ratchet that is never pruned.**
18 snapshot days so far, growing from 15 rows (2025-11-16) to 968 rows/day once
the league filled in, and from 1 system to 2 on 2026-01-11 (so ~968 rows per
weekly run). A full season ≈ 20 runs ≈ 19,400 rows ≈ 710 KB payload. `season` is
currently constant `'2025-2026'`, so a rollover starts a fresh season's worth
rather than replacing. Five seasons ≈ 97,000 rows ≈ 3.5 MB payload ≈ 8.6 MB on
disk. Not alarming, but it is the only table with no retention policy at all and
it is already the 5th-largest.

**4 · `app_settings` is being used as a document store.** One row,
`faq:content`, is **38,197 bytes** — 75% of that table's payload and the single
largest value in the database. `insights_seen` is 6,072 B and its per-user twin
`u:colbyl.farrar@gmail.com:insights_seen` is 5,197 B, so that pair grows
**per coach**, not per game. At 50 coaches that is ~260 KB of settings rows read
through a key-value table with no per-user index. This runs against the
project's own "no blobs in tables, compact JSON, cap saved items" rule.

**5 · Connection pragmas, in context.** `database/db.py:213-214` sets
`cache_size = -65536` (64 MB) and `mmap_size = 268435456` (256 MB) per
connection. At a 13 MB database the 64 MB cache is effectively "hold the entire
book in RAM", which is the right answer and costs at most 13 MB. That stops
being true somewhere around a 60 MB database — several seasons of scraped
schedules plus audit — at which point 64 MB × N live connections becomes a real
number on 2 GB with no swap. Worth a note in the deploy doc, not a change today.

### 7d. Summary of the growth picture

| driver | grows with | today | risk |
|---|---|---|---|
| `audit_log` | write volume, 12-month window | 3.07 MB (56%) | **medium** — biggest table, no VACUUM after eviction |
| `games` | scraped schedule, per season | 621 KB / 13,363 rows | **medium** — drives §5 shape 5 CPU |
| `game_event_lineup` | tracked games × 1,757 | 609 KB / 77,309 rows | **medium (CPU)**, low (disk) |
| `game_events` | tracked games × 175.7 | 533 KB / 7,731 rows | low |
| `rating_snapshots` | weeks × teams × systems | 505 KB / 13,793 rows | low, but unpruned forever |
| `app_settings` | coaches, and one 38 KB FAQ blob | 51 KB | low, wrong shape |

**Nothing here threatens 2 GB of disk or RAM at any horizon the app will reach.**
The scaling risk is entirely CPU, and it is concentrated in one query shape
(the lineup materialisation) plus one table that grows for reasons unrelated to
basketball (`games`, from the scraper).
