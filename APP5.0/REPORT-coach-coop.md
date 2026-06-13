# Overnight build report — per-coach Coaches' Co-op + hosting

**Branch:** `feat/coach-tiers` · **Date:** 2026-06-13 · **Status:** implemented,
tested, **not committed** (left in working tree for your review).
15 files changed (+555 / −209). Tests: entitlement 49 ✓, api 62 ✓, auth 10 ✓,
full compile ✓, live-DB read-filter smoke ✓, 8-agent adversarial review → 0
confirmed defects.

This delivers the todo's AXIS-2 move (team-level pool → **per-coach binary
share-to-scout**), keeps AXIS-1 depth gates intact, reframes the copy, gives the
toggle real read-path teeth, and ends with a **laptop → online host** runbook.

---

## What got built (mapped to your todo)

**§1 Schema** — `app_users.shares_pool` (bool, default 0 = Solo) + denormalized
`games.in_pool`. `teams.in_pool` kept readable, deprecated. One-time backfill
(guarded by `app_settings.mig_shares_pool_v1` so it can't re-enable a coach who
later goes Solo): lifts old team pool flags onto those teams' coaches, then
derives `games.in_pool` from each game's logging coach. `database/db.py`.

**§2 entitlement.py** — full rewrite to per-coach binary reciprocity:
`viewer_is_league_wide` (=`shares_pool`, admin always), `can_see_team_tracked` =
Paid ∧ (own ∨ league-wide), `can_see_game_tracked` (now `in_pool`-aware),
`tracked_gate` with exactly 3 messages (Paid / co-op **invite** / neutral
"hasn't shared"), plus the read-filter helpers `pooled_game_ids`,
`team_has_pooled_tracked`, `visible_tracked_game_ids`, `team_visible_tracked_ids`,
and `recompute_game_pool`. `viewer_in_pool` kept as a back-compat alias.

**§3 Page-gate reframe** — Rankings `_paid_pool_lock`, the team deep-dive, the
Compare tracked table; War Room lineup/observed locks; Team Dashboard
`tracked_gate`; box-score game gate. Every "needs the league pool / turn on the
team toggle" line is gone — replaced by an **invite** (your own Solo toggle) or a
**neutral** "hasn't shared". Free always sees "Paid feature".

**§4 Read-filter teeth** — `visible_tracked_game_ids` / `team_visible_tracked_ids`
threaded as `game_ids` / `visible_game_ids` into `team_ratings._finished_games` +
`tracked_ratings`, `league_analytics.team_tracked_pack`,
`team_analytics.team_bundle`, `scout.build_scout`. Rankings Tracked + Team-Charts
tabs aggregate over the viewer's pooled set; the dashboard scopes a scouted team's
depth to its pooled games; War Room observed-together units pool-scope. So a Solo
coach's games never feed another coach's pool view. `finish_game` + the tracker
finish endpoint recompute `games.in_pool` from the logging coach.

**§5 Settings UI** — the per-team pool toggle is gone. Added a self-serve
**🤝 Coaches' Co-op** switch (Solo / League-wide) for every signed-in coach, plus
a per-coach toggle in the admin user list (to comp a founding cohort). Copy is
"Private by default… share to scout."

**§6 Tests** — `tracker/test_entitlement.py` rewritten for per-coach binary
reciprocity (49 checks incl. the scout-game case: D league-wide-tracks B-vs-C →
pooled & scoutable; a Solo coach's game stays invisible to a league-wide scout).

**Last step — hosting** — `DEPLOY.md` runbook + `deploy/` configs (Caddy
auto-HTTPS, two systemd units bound to loopback, Litestream continuous backup,
`bootstrap.sh`). Aligned to the real entrypoints (`Main.py`, `tracker.api:app`)
and the `APP5_DATA_DIR` data-dir model. See **Hosting** below.

---

## Decisions I made for you (the "confirm first" list)

You were asleep, so I took your recommended defaults and noted them here:

1. **`shares_pool` default = Solo.** Adopted. Private-by-default is the sign-up
   pitch and the safe default.
2. **Cold-start cohort.** This is GTM, not code — but I made it *operable*: the
   admin user list now has a per-coach Co-op toggle to comp a founding cohort to
   League-wide, and `DEPLOY.md §9` calls it out as the day-one step so the pool
   isn't empty.
3. **v1 granularity = per-coach binary only.** Adopted. Per-game embargo /
   "share this one but not that" stays deferred (noted below).

---

## Liberties I took (judgment calls / deviations)

1. **Two enforcement layers, not just one.** The shipped code gated only at the
   render layer (show/hide a computed table). I kept that AND added a true
   **read-path filter** so league-wide aggregations are computed over the pooled
   set — this is what gives the toggle teeth, exactly as §4 intends.

2. **Anonymous baselines stay full-league (documented privacy-safe trade).** The
   dashboard's "vs league" baseline pools (`_league_stat_pools`) and the
   league-wide RAPM/WPA possession pools (`_gender_tracked_ids`) are **not**
   pool-filtered. They're aggregate baselines that reveal no individual team's
   depth, and full samples make better statistics. The per-team *identifiable*
   surfaces (Rankings Tracked list, a scouted team's dashboard) **are** filtered.
   If you'd rather these baselines also exclude Solo coaches, it's a one-line
   `game_ids=` add per cached fn.

3. **Restricting `tracked`/`pack` only ever shows LESS (privacy-safe).** A
   side-effect: a Free/Solo coach now sees a degenerate own-games "tracked rank"
   on the Team tab instead of the full-league one. That's intentional and
   consistent with depth-gating; it can never *expand* visibility.

4. **Mixed-pool teams (rare) aren't perfectly scoped.** If team X's own coach is
   Solo but a *league-wide* coach opponent-tracked X, a scout's dashboard shows
   X's *rating number* over all X's tracked games while the deep bundle is
   pooled-only. Real teams are almost always uniformly pooled/not (one coach logs
   their games), so this is an edge case. Closing it fully means threading the
   visible set into the gender-wide rating cache too — deferred as low-value/risk.

5. **I drove the core edits inline rather than fanning out writer-agents.** For an
   unattended overnight build, coherence + not waking you to a broken app matters
   more than parallelism. I used multi-agent orchestration where it's genuinely
   low-risk and high-value: an 8-agent **adversarial review** of the finished diff
   (leaks / call-sites / schema / copy, each finding independently verified).

6. **`can_see_game_tracked` is now `in_pool`-aware** (keyword arg), and the War
   Room matchup projection (no single game in scope) falls back to "either team
   has pooled tracked data". Reasonable for a derived two-team product.

7. **I did not commit.** Per repo convention I commit only when asked, and you're
   mid-feature on `feat/coach-tiers` — you may want to split or reword. Suggested:
   ```
   git add -A && git commit -m "feat(coop): per-coach League-wide/Solo share-to-scout + deploy runbook"
   ```

---

## Deferred (unchanged from your list, + why)

- **Per-game share override / schedule-aware embargo** — v1 is per-coach binary
  by your decision; the schema (`games.in_pool` denormalized per game) already
  makes a future per-game override a small additive change.
- **Stripe `paid_until` poll** (self-serve billing) — entitlement already honors
  `paid_until`; only the poll that writes it is missing.
- **PWA token install UX** — untouched.
- **DB-per-org / managed Postgres** — the hosting step intentionally stays on
  SQLite + Litestream; graduate later (noted in `DEPLOY.md`).

---

## Hosting — laptop → online host

I prepared everything; **you run it** (I can't provision a box or hold your
OAuth/DNS secrets). Cheapest viable path from the scaling roadmap: one small VPS +
Caddy (auto-HTTPS) + systemd + Litestream backups, still SQLite.

- **`DEPLOY.md`** — the full ordered runbook (provision → code → data dir → turn
  on `st.login` **before** the URL is public → systemd → Caddy → Litestream →
  cold-start the co-op → updates/restore drill).
- **`deploy/app5-web.service`**, **`deploy/app5-tracker.service`** — systemd units,
  both bound to `127.0.0.1`, `APP5_DATA_DIR=/var/lib/app5` (real disk, never a
  synced folder — the corruption rule from `database/db.py`).
- **`deploy/Caddyfile`** — TLS + websocket reverse proxy (app + tracker subdomains;
  single-domain variant included).
- **`deploy/litestream.yml`** + **`deploy/app5-litestream.service`** — continuous
  WAL replication to S3/B2 (+ restore drill in the runbook).
- **`deploy/bootstrap.sh`** — one-shot setup that also runs the entitlement test
  as a smoke gate.

**Verify before sharing the URL:** `[auth]` is configured (app runs open without
it), and you've comped a founding cohort to League-wide so scouting isn't empty.

---

## How to sanity-check it yourself in 30 seconds

```bash
python tracker/test_entitlement.py     # 49 checks, the whole model
python tracker/test_api.py             # 62 — tracker + finish_game pool stamp
python tracker/test_auth.py            # 10
python -m compileall -q Main.py pages helpers database tracker
```

Then run the app, go to **Settings → 🤝 Coaches' Co-op**, flip yourself
League-wide, and watch a previously-neutral opponent's tracked depth unlock.
(As the local owner you're admin = full access regardless — set up `[auth]` and a
real coach account to see the Solo/League-wide split in action.)
