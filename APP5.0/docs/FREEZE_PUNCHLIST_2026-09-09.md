# Freeze punch list — 2026-09-09

What is left before the season freeze, **verified against the live droplet
rather than against `THE_BOOK_2026-09.md`**. Read THE BOOK for the reasoning;
read this for what is still undone.

## Where things stand

The code side of the September sweep is **finished**.

| check | result |
|---|---|
| production `/home/app5/app5` | `307f7cf` — identical to local `main` |
| `git log origin/main..HEAD` | 0 (nothing unpushed) |
| B1 · every number states its sample | shipped — `dcc128e`, `fc9cf44`, `8ac45e4` |
| B2 · the Free box score | shipped — `37cb487` |
| B3 · own creation via `tracked_by` | shipped — `2616966`, `5f74c8a` |
| B4 · one abbreviation, one meaning | shipped — `f9832b5` |
| `tracker/test_read_filter_empty_scope.py` | 5 passed — the three-red-by-design signal is green |
| gate suites (entitlement, lock_reason, own_creation, empty_scope, free_box) | 34 passed |

What remains is operations and polish.

---

## 1 · Timers are not installed — and nothing else is scheduled either

**BLOCKER. Needs founder sudo; nobody else can do it.**

Measured on the droplet:

```
systemctl list-timers --all   →  zero app5 units
crontab -l                    →  "no crontab for app5"
```

So all four of §17's autopilot jobs are still memories:

| job | state today |
|---|---|
| `tools/auto_season_rollover.py` | written, idempotent, forward-only — **not installed**. Fires off the 1 October cutoff. |
| `ANALYZE` | has run **once** (`sqlite_stat1` = 40 rows). Goes stale with no timer. |
| rating-history rebuild | `rating_snapshots` holds 13,801 rows through 2026-03-14 — current, but only until the season starts moving. |
| backup verification | `~/backups` does not exist. |

The rollover is the time-critical one: 1 October is the cutoff, and the trained
coaches arrive the same month.

## 2 · Production's book was never repaired — and it is holding the index open

**BLOCKER. One command, but it is a judgement about someone's season.**

On `/var/lib/app5/analytics.db` (13,383 games, 63 tracked):

* **9 duplicate pairs** still present, all `''`-on-both-sides
* **2 rows** with `tracked=0` and a tracker recorded
* **`ux_games_matchup` does not exist.** `games` carries only
  `idx_games_tracked`, `idx_games_team1`, `idx_games_team2`, `idx_games_season`,
  `idx_games_share_token`, `idx_games_date`.

The missing index is **by design**, not a deploy failure. `database/db.py:729`
says so in its own comment: `CREATE UNIQUE INDEX` over a table that already
holds duplicates raises `IntegrityError`, the migration loop records it in
`_INIT_SKIPPED` with its reason, and boot continues unharmed. It takes on the
next boot *after* the repair.

So today the duplicate-game class is **closed in code and open in production**.

```bash
ssh app5@107.170.27.154 "cd app5 && python3 tools/repair_book.py"          # read it first
ssh app5@107.170.27.154 "cd app5 && python3 tools/repair_book.py --apply"  # then this
ssh app5@107.170.27.154 "sudo systemctl restart app5-web"                  # index takes here
```

---

## 3 · Three sites re-widen an entitlement-scoped id set

Latent, not bleeding — but it is the exact class the sweep named, and the fix is
three lines.

| site | code |
|---|---|
| `pages/6_Team_Dashboard.py:6087` (`_ins_scheme_sit`) | `(tuple(game_ids) if game_ids else tuple(bundle["tracked_ids"])) or None` |
| `helpers/dashboard/insights_team_read.py:58` | `tuple(getattr(ctx, "tracked_ids", ()) or ()) or None` |
| `helpers/dashboard/insights_tab.py:631` | `tuple(_tids or ()) or None` → `_team_feed` |

`None` means **unrestricted** downstream. The sibling twelve lines below
`_ins_scheme_sit` — `_ins_quarter_read` — does it correctly:
`if not _gids: return []`.

**Reachability is narrow and unproven.** Two things stop it today:
`insights_tab.py:575` early-returns unless `ctx.has_tracked`, and `has_tracked`
is False whenever `lock_reason` fires. You would need `has_tracked` True *and*
the visible set empty — a pooled-or-own-tracked team with zero visible games in
the read season. That could not be constructed against the production book.

Close it anyway: cheaper now than to reason about in February.

**Smaller, same area:** `lock_reason:479` and `can_see_game_tracked:342` call
`team_has_pooled_tracked(team_id)` with no `season`, while
`team_visible_tracked_ids` filters `season=?`. They agree today because both
defaults resolve to the read season. A coupling, not a bug — the kind that
drifts silently.

## 4 · Two suite tests are priced to a book that no longer exists

`python tracker/run_all.py` — two files exit 1:

* `tracker/test_offline_readiness.py:83` — wants 8 M / 35 F tracked games. The
  local book holds **29 F and zero boys**; production holds 63 tracked.
* `tracker/test_ratings_depth_smoke.py:107` — "the do-it-all read stays
  distinctive (0 of 45)", failing for the same reason.

Neither is a regression (`run_all` only ever reached 97/0 on a synced
`%LOCALAPPDATA%` book). Re-price both off `tools/pull_prod_snapshot.py` before
November, or the suite cries wolf on every run — which is worse than no suite,
because in February it gets skipped.

## 5 · Phase 1 instrumentation is not built

THE BOOK §21 asks for three cheap, disposable counters **before** the October
training, because that session happens exactly once:

* which pages get opened, in what order — `grep page_view` returns nothing
* which empty states get hit — `helpers.ui.empty_state` renders but logs nothing
* whether the co-op toggle is ever touched

## 6 · 23 games are wearing the season sentinel as a label

`SELECT ... WHERE season='Current'` on production returns 23 rows, dated
**2026-12-08 → 2027-02-16**, none tracked — next season's schedule filed under
the sentinel. Confirm `auto_season_rollover.py` relabels them, or November opens
on an empty schedule.

---

## Gating — audited, and correct

Asked separately and answered separately: **the gate layer holds.**

* `lock_reason` (`helpers/entitlement.py:433`) is genuinely the one ladder;
  `tracked_gate` is a shape adapter that keeps only the rule that is its own
  ("no data at all is not a lock").
* The co-op ban bites in the **data** path, not just the message:
  `viewer_is_league_wide` returns False when `pool_banned`, and
  `own_created_game_ids` bans at the top so all four call sites inherit it —
  authorship cannot route around moderation.
* The archive bypass sits at the top of all six gates —
  `can_see_team_tracked`, `can_see_game_tracked`, `visible_tracked_game_ids`,
  `team_visible_tracked_ids`, `lock_reason`, `paid_or_open_archive`.
* The team bundle **intersects** rather than widening
  (`helpers/team_analytics.py:1885`), and the Free `game_log` is deliberately
  left unfiltered.
* Free box columns have one definition:
  `FREE_BOX_COLS = [c for c in BOX_COLS if c not in ("MIN", "+/-", "SC")]`
  over `EVENT_DERIVED_STATS` (`helpers/box_score.py:53`).

§3 above is the only asymmetry the audit found.

---

## Parked deliberately until after the freeze

`PLAYER_PROFILE_SCRUB_2026-09-09.md` and `SCOUT_TAB_ROADMAP_2026-09-09.md` are
both build documents, not blockers. Neither is a reason a coach opens a page in
anger between November and March, which is the only bar September answers to.
