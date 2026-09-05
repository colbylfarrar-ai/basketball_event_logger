# Next session — queued from the 2026-09-05 queue run

Branch `queue-2026-09-05` is finished: three commits off `main`, covering items
1, 2 and 4 of the previous handoff. Item 3 was NOT built — see below, it is
blocked on a parked branch rather than on any decision.

---

## SHIPPED

### 1. Cross-state badge collision
`officials.official_id` was `INTEGER NOT NULL UNIQUE` — globally unique — so the
first out-of-state crew would have collided with an in-state ref of the same
badge number, un-archived them, handed back the wrong name and pooled two
careers into one row.

Uniqueness is now `UNIQUE(official_id, state)`. SQLite cannot drop a column-level
UNIQUE, so existing books go through a one-time guarded rebuild
(`mig_officials_state_unique_v1`) that copies `officials.id` verbatim — every FK
in `game_lineup_officials` and `game_events.official_id` still resolves — with
foreign_keys off for the swap, because DROP TABLE would otherwise CASCADE the
crew rows away. Pre-`state` rows backfill to `'OK'`.

`officials.state_for_game()` derives the state from the HOME team (team1): a
travelling team plays under the host's officials. All four write paths stamp it —
the tracker API (the PWA sends its `game_id`), the Input Hub editor, Setup's
untracked-game crew, and the Streamlit tracker's quick-add. The Officials page
shows the state beside the badge for out-of-state refs.

Guard: `tracker/test_official_badges.py` (7 tests, including the migration
rebuild against a synthetic old-shape DB).

### 2. Offline quick-add (N2)
Adding a player or a ref no longer refuses without a signal. The row goes on the
roster immediately under a LOCAL id — negative, so it can never collide with a
server AUTOINCREMENT id — held in its own IndexedDB store (`adds`, schema v2) so
it survives the tab iOS reclaims.

The part that had to be right is reconciliation. `drainAdds` runs FIRST in every
flush and gates the event batch: an event carrying a local id comes back
`rejected`, and flush DEQUEUES rejected events, so sending one would lose the tap
for good. When an add lands its server id is stamped over the queued events (on
disk too), the cached roster, the on-court five, the crew slots and the
half-finished flow — including the id-bearing arrays `on_court`, `officials_on`
and `official_slots`. Both endpoints are idempotent, so a half-delivered request
replays to the same id rather than a twin.

Verified end to end in the browser against a throwaway DB: offline add → tap →
back online → the shot persisted against the real player id, the lineup snapshot
carried it, and the crew row landed in slot R.

Guard: `tracker/test_offline_quick_add.py`. The static half is the one that
matters long-term — it asserts every `_id` field in `SERVER_FIELDS` appears in
`EVENT_ID_FIELDS`. **A new id field added to an event without being listed there
is a local id that sails into the batch and loses a tap.**

### 4. `stats._team_game_ids` rollover trap (N5)
Now uses `seasons.tracked_default_season_sql()`.

**One correction to the item as written.** N5 named only `_team_game_ids`, but
`_team_game_ids_all` on the very next function has the identical hardcode and it
IS reachable: `dashboard/player_card.py` calls the on/off rebounding and
playmaking splits with `game_ids=None` whenever the entitlement filter is
unrestricted. Both were fixed. Both readers go on to call `fetch_events()`, so a
season with no tracked games has nothing to offer either and the tracked-games
test is the right one for both.

Guard: `tracker/test_team_game_pool_rollover.py` — confirmed to FAIL without the
fix, not just pass with it.

---

## 3. iPad Mode (N4) — NOT BUILT, blocked on a parked branch

Not a judgement call and not a scope cut: **the thing it composes on top of is
not on `main`.** N4 is a composition change over the >=768px tablet layout, and
that layout — media queries plus the tablet-mode detection with its Bench setup
override — shipped in `adc679e` on `batch-2026-09-05`, which is still unpushed.
`main`'s `style.css` has no media queries at all.

Building it on `main` anyway would mean writing the base layout a second time and
guaranteeing a conflict in `style.css` and `app.js` the moment the batch merges.
**Founder ruling: skip and log.** It becomes the first item of the session after
`batch-2026-09-05` reaches `main`.

The design note stands unchanged and is worth restating, because it is the whole
point of the item: keep `S.screen` exactly as it is and change only what each
screen RENDERS at tablet width. `init()` restores a mid-game session by branching
on `st.screen`, and that path is what saves a game when iOS reclaims the tab.
Composition change, not a navigation change.

---

## The priced-games floor — DECIDED, not yet applied

**Founder ruling: yes, add a floor.** Gate on `rated_games >= 3`, matching
`RATING_MIN_GAMES`.

The reasoning, so it does not get relitigated: the gate today is on games
WORKED, but the estimator consumes games PRICED. `share_z` is the mean over
`rated_games` and `worst_z` is their max — and a max over n=1 is just the single
observation, so the "worst night" term carries no information at all and a ref
rated on one priced game is presented at the same weight as one with fifteen.
Mike Gaskins is the live example: 3 worked, 1 priced, the other two phantom-crew
games where he called nothing.

**This could not be applied in this session either.** `rated_games`,
`_share_z_by_game` and the whole crew-share rating live only on
`officials-rating-2026-09-05`; `main`'s `helpers/officials.py` still has the old
`_RATING_WEIGHTS` block. Apply it there, in `official_ratings`:

```python
rated = [r for r in rows
         if r["games"] >= RATING_MIN_GAMES
         and r["rated_games"] >= RATING_MIN_PRICED]
```

…and mirror the same test in the per-row loop that currently reads
`if r["games"] < RATING_MIN_GAMES or not zs`.

Note this changes the rated POPULATION, not a weight, so the constants rule
("gates required before any constant change") is not triggered — but it will
shrink the table, and how much is worth reading off the 63-game book before it
ships.

---

## STILL NOT CODE

### The data slip in the live book
`game_events.id = 7101` — game 14123 (2026-02-06), Q1 0:01 — has
`primary_player_id = secondary_player_id = 509`. A charge where the same player
drew it and committed it; event `7100` is a foul at the same timestamp with
509/498, so it looks like a double-log that took one player into both slots.

This is what fails `test_charges.py::test_real_book_encoding`, and it fails on
`main` too — it is not a regression from this work. **Fix it in the Event
Editor** — one row, one click. Left untouched again, deliberately.

### Both halves of the suite
`run_all.py` green is half the tree. `python -m pytest tracker/` is the other
half and the two are disjoint by design (`tracker/_test_kinds.py`). Run both.

---

## STATE AT HANDOFF

- Branch `queue-2026-09-05`: 3 commits off `main`.
- Three parked branches now, all unpushed: `batch-2026-09-05` (9),
  `officials-rating-2026-09-05` (4), and this one.
- New tests: `test_official_badges.py`, `test_offline_quick_add.py`,
  `test_team_game_pool_rollover.py`.
- `tracker/static/sw.js` cache bumped to `tracker-v54` (app.js changed, so the
  PWA has to re-fetch it).
