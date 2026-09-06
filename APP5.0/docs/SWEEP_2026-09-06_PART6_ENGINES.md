# Sweep — 2026-09-06 · Part 6: the engine inventory

Part of the September sweep (Parts 1 gating, 2 Team Dashboard, 3 Officiating Lab,
4 Rankings, 5 database). Read-only against a `sqlite3.backup` copy of the live
book. **The live book was never written to.** No application code changed.

898 public entry points across 130 helper modules. 853 reach a page; 45 do not,
and every one of those 45 was grep-verified and, where it survived, executed
against the snapshot with `season="2025-2026"`.

Read the method section first. This map has been wrong before — in both
directions — and the two traps that produced that are named up front:

* **the registry trap.** `insights.py`'s twenty `*_edges` builders are named by
  nothing outside their own module and are all LIVE, reached through a
  module-level `_FEED_STAGES` tuple. "No call sites outside its own module" is
  not evidence of death.
* **the render-site trap.** Three of this audit's own first-pass findings were
  wrong and are corrected in place rather than deleted, with the correction
  shown. Grepping a returned key name is not enough; the render site has to be
  read. One retraction (`shot_kinds.kind_by_tag`) is particularly worth reading,
  because the shipping module's docstring already names the exact number the
  first draft had "discovered".

## The four worth acting on

* **B1 — the play-type axis is never passed.** Both live call sites of
  `shot_kinds.kind_by_shot_tag` hardcode `"defense"`; `"play_type"` is never
  supplied, so a whole cross-tab the engine supports has never rendered.
  League-normalized on this book: Adair's post-ups reach the rim **71% against a
  50% league post-up rate**, and their off-screen actions land **16pp less
  arc-three and 12pp more 4-to-19ft** — the curls are getting caught short in the
  dead zone, which is the same band Part 2 §1.2 prices at 0.548 PPS.
* **B5 — `exploit.defensive_plan["their_leaks"]`** is a documented return key,
  computed on every call, and read by nothing. The War Room renders `throw` and
  `avoid` (6–11 possession rows) and drops the one half that answers *"what
  should my offense attack"* (106–842 possessions). Three lines.
* **B7 — `situational.player_margin_scoring`** reaches no renderer. Four Adair
  bench players score **63–94% of their points in garbage time** (one at 94.1%,
  with a 2.4% close-game share). Today that is visible only if a z-gate happens
  to fire.
* **B3 — `lineups.player_on_off` is buried, and should stay buried.**
  `reliability.MEASURED[("player","onoff_off")] = −0.213`: the offensive half
  anti-correlates with itself across split halves. The defensive half (+0.366) is
  the only defensible column. Recorded here so it is not "surfaced" by a future
  sweep that only counts call sites.

## One latent bug worth a ticket now

`pages/7_Players.py` calls `MX.matchup_table()` with no arguments, which resolves
to `fetch_events(None)` — every event in every season. Harmless on a
single-season book; silently cross-season the moment a rollover happens. Same
class as the `season="Current"` defaults in Part 1 §5.2.

---

# APP5.0 engine inventory — "engine done, surface missing" map
Audit date 2026-09-06 · read-only · snapshot `scratchpad/book/analytics.db` · season `2025-2026`

## Method
AST call-graph over `helpers/*.py`, `helpers/dashboard/*.py`, `pages/*.py`, `Main.py`,
plus `tools/`, `tracker/`, `database/` for "who else calls".
Reachability seeded from `pages.*` + `Main`, propagated through resolved call edges,
**including module-level scopes** (a function referenced only inside a module-level
tuple/dict — e.g. `insights._FEED_STAGES` — is reached when the module is imported by a
live path). Every unreached candidate was then grep-verified by name across the whole
tree, and the surviving BURIED/PARTIAL entries were executed against the snapshot.

Counts: **898 public module-level entry points** across 91 helper modules.
853 reach a rendered page by the call graph; 45 do not. Of those 45, verification
reclassifies most (tracker-API-live, internal, deliberately-off).

## Trap that broke the previous version of this map
`insights.py` defines 20 `*_edges` builders that **no other module names**. They are
LIVE: `_FEED_STAGES` (helpers/insights.py:1846) is a module-level tuple of
`(key, fn, needs_table)` consumed by `build_feed`, which is called from
`helpers/dashboard/insights_tab.py:324`, `helpers/dashboard/player_card.py:402`, and
`helpers/league_spotlight.py:175`. A naive "no external call sites" scan lists all 20
as dead. They are not.

## The second trap — and I walked into it twice
"No caller" is not the same as "no surface". Three of my own first-pass findings were
wrong because I searched for *function* and *key* names instead of reading the
consuming render code:

- **B1** — I reported "scramble concedes 55.5% of shots at the rim" as a buried
  finding. `shot_diet.render_concedes` ships that cross-tab league-normalized, and its
  docstring names that exact number as "a finding that was not one".
- **B2** — I reported `bench_cost` as rendering 1 of 10 rows. `pages/6_Team_Dashboard.py:4280`
  renders all 10. The keys I found unrendered (`in_game_drag`, `before_share`) are
  withheld *on purpose*, and the page says why.
- **B4** — I reported the steal-forced split as unsurfaced. `defense_tab.py:619`
  renders it as a stacked bar per scheme.

Each is corrected in place below rather than deleted, because the correction is the
useful artefact. Every remaining entry was re-verified by reading the render site, not
by grepping the name.

---

## Snapshot facts used for every run below
- `games`: 13,362 rows in `2025-2026`, **43 tracked**; `Current` holds 1 untracked game.
- Team 1 (Adair Girls) = **24 tracked games**, 4,213 events. Girls tracked pool = 35 tracked games / 6,345 events.
- All engine calls below were made with `APP5_DATA_DIR` on the snapshot and `season="2025-2026"`.

---
# BURIED / PARTIAL — verified with real output

## B1. The play-type × shot-kind cross-tab — BURIED
### (and a correction: my first version of this entry was wrong)

**What I got wrong first.** I opened this audit by calling `shot_kinds.kind_by_tag`
(`helpers/shot_kinds.py:537`, zero callers) a buried analytic and led with the raw
number "scramble concedes 55.5% of its shots at the rim vs 23% in half-court man."
That is not a finding, and the codebase already says so. `helpers/dashboard/shot_diet.py:290`
(`render_concedes`) ships this exact cross-tab through the LIVE sibling
`kind_by_shot_tag`, and its docstring records the lesson verbatim:

> "The raw version of this table produced a finding that was not one: 'scramble
> concedes 55.5% of its shots at the rim, at 1.009 PPS'. True, and empty — a scramble
> IS a broken possession, so it gives up rim looks by definition, everywhere, for
> everyone."

I reproduced the pre-refuted number and presented it as new. The defense axis is
fully shipped, on both sides: `helpers/dashboard/defense_tab.py:381` calls
`render_concedes(..., own_side=not _off)`, so both "what each scheme we run gives up"
and "what we get against each defense we face" already render, **league-normalized**.
`kind_by_tag` (the events-fed variant) is therefore a **duplicate** of the live
shots-fed `kind_by_shot_tag`, not a missing capability — it is reclassified DEAD below.

**What actually survives.** Both live call sites hardcode the tag `"defense"`.
`kind_by_shot_tag(shots, "play_type")` is never called anywhere. So the *tag axis* is
the gap, not the function.

**Coach question:** *"When I call a post-up, what shot do I actually get — and is that
different from what everyone else's post-up gets?"*

Measured, Adair Girls (1,213 located shots) against the girls pool's **same play type**
(3,056 located shots), in the app's own display taxonomy. Delta in share points, with
Adair's own share in parentheses:

| play_type | n | rim 0-4ft | 4-19ft | arc 3 | deep 3 |
|---|---|---|---|---|---|
| post | 78 | **+21.4** (71%) | **−21.4** (29%) | +0.0 (0%) | +0.0 (0%) |
| duckin | 43 | **+14.1** (60%) | −15.6 (35%) | −1.0 (0%) | +2.6 (5%) |
| offscreen | 49 | +4.1 (20%) | **+11.7** (33%) | **−15.9** (22%) | +0.1 (24%) |
| cut | 52 | +6.0 (48%) | −12.8 (37%) | +6.2 (13%) | +0.6 (2%) |
| transition | 264 | +6.1 (58%) | −7.6 (21%) | +1.0 (12%) | +0.5 (9%) |
| dho | 21 | −0.9 (14%) | +1.2 (48%) | +8.4 (29%) | −8.7 (10%) |
| iso | 147 | +2.0 (20%) | −1.1 (71%) | −1.1 (5%) | +0.1 (3%) |
| spot | 294 | +0.0 (0%) | −1.9 (5%) | −1.7 (59%) | +3.6 (36%) |
| putback | 100 | +2.5 (61%) | −1.7 (39%) | −0.4 (0%) | −0.4 (0%) |
| blob | 54 | +1.9 (24%) | −7.0 (26%) | +1.6 (35%) | +3.4 (15%) |

These are not definitional. Every team's post-up starts near the basket; Adair's
finishes **at the rim 71% of the time against a league post-up rate of 50%** — their
interior actions get all the way there instead of settling for the 4-19ft floater.
The `offscreen` row is the mirror image and the one to act on: their off-screen
actions produce **16 points less arc-three and 12 points more 4-19ft** than everyone
else's — the curls are being caught short, straight into the dead zone.

**Natural home:** `helpers/dashboard/playstyle_tab.py` (the play-type view), or
`shot_diet.render_concedes` generalized to take a `tag` parameter — it is already
written to take `league_shots` and do exactly this normalization.

**Effort:** low, and lower than my first estimate, because the renderer exists.
`render_concedes` hardcodes `"defense"` in two places (L316, L330) and hardcodes its
heading; parameterizing the tag is a handful of lines. **The league-normalized form is
mandatory** — the raw table would reproduce the same non-finding the module already
threw out.

## B2. `foul_trouble.bench_cost` — RETRACTED as a surfacing win; docstring bug stands
### Correction: this is NOT a buried table. My first draft said it was.

I wrote that `bench_cost` reaches a page only through `foul_trouble_verdict`, which
renders one row, and that the other nine were discarded. **That is wrong.**
`pages/6_Team_Dashboard.py:4280-4303` renders the complete per-player, per-foul-level
table (Player / Foul / Games / Normal floor % / After that foul % / Drag), sorted by
drag, on Charts → Situational. All ten rows I measured are on screen today. My
key-name scan misled me: `in_game_drag` and `before_share` genuinely never render, and
I over-read that into "the table doesn't render".

I also proposed surfacing `in_game_drag` as "the sharper number". **The page already
explains why that is wrong**, at `pages/6_Team_Dashboard.py:4305-4310`:

> "Measured against each player's **own season floor share**, not against her minutes
> earlier in that same game. The in-game comparison looks obvious and is wrong: a
> reserve enters late, so her second foul lands late, and the before-window spans a
> game she mostly watched — on this book that made two reserves read as …"

So `in_game_drag` / `before_share` / `on_before` / `on_after` / `team_before` /
`team_after` are **deliberately withheld intermediates**, not missed opportunities.
Reclassify: LIVE, fully rendered. Nothing to surface.

### What does survive: the docstring is stale in a way the page is not
`helpers/foul_trouble.py`, `bench_cost` docstring:
> "`drag` = before − after, in share points"

Measured on the snapshot (Finley Grubbs, 2nd foul): `before_share` 98.8,
`after_share` 55.7 → their difference is **43.1**, which is the returned
`in_game_drag`. The returned `drag` is **13.1** = `season_share − after_share`
(68.9 − 55.7). The docstring therefore documents the *abandoned* definition, while the
on-screen caption 3,400 lines away states the correct one. It also omits three
returned keys (`season_share`, `in_game_drag`, `team_id`).

Anyone reading the engine to build a new surface would implement the wrong number and
walk straight into the reserve-enters-late trap the page already solved. One-line
docstring fix; no behaviour change.

For the record, the measured table (all of it on screen today):

| player | foul # | games | normal share | share after | drag |
|---|---|---|---|---|---|
| Kealey Sanders | 2 | 8 | 69.7% | 48.4% | +21.3pp |
| Hannah Bond | 2 | 13 | 63.8% | 50.6% | +13.3pp |
| Finley Grubbs | 2 | 9 | 68.9% | 55.7% | +13.1pp |
| Ali Schwerdfeger | 2 | 13 | 70.0% | 57.8% | +12.1pp |
| Hannah Bond | 4 | 3 | 63.8% | 59.1% | +4.8pp |
| Finley Grubbs | 3 | 5 | 68.9% | 68.4% | +0.5pp |
| Hannah Bond | 3 | 5 | 63.8% | 64.2% | −0.4pp |
| Ali Schwerdfeger | 3 | 6 | 70.0% | 79.3% | −9.3pp |
| Reagan Langley | 2 | 4 | 42.8% | 58.5% | −15.7pp |
| Morgan Boyles | 2 | 5 | 49.7% | 70.9% | −21.2pp |

## B3. `lineups.player_on_off` — BURIED, and correctly so (premise CONFIRMED)
`helpers/lineups.py:348`. Only caller is `insights.onoff_edges`, and the miner reduces
the whole table to at most two sentences per player, gated on `|z| ≥ MIN_Z` and on an
*adjusted* estimate (RAPM) also firing.

Full table, Adair Girls, 24 tracked games — 12 players clear the possession floor:

| player | ON ORtg/DRtg | OFF ORtg/DRtg | off Δ | def Δ | net Δ | poss on/off |
|---|---|---|---|---|---|---|
| Ali Schwerdfeger | 82.8 / 41.7 | 63.9 / 44.2 | +18.9 | −2.5 | +21.4 | 1137/474 |
| Hannah Bond | 83.7 / 41.6 | 66.6 / 43.9 | +17.1 | −2.3 | +19.4 | 1006/605 |
| Reagan Langley | 83.3 / 39.1 | 72.9 / 45.0 | +10.4 | −5.9 | +16.3 | 681/930 |
| Kealey Sanders | 83.5 / 43.5 | 63.7 / 39.8 | +19.8 | +3.6 | +16.2 | 1104/507 |
| … | | | | | | |
| Carly Buell | 60.8 / 44.6 | 83.3 / 41.7 | −22.5 | +2.9 | −25.4 | 431/1180 |

**Do NOT surface this.** `reliability.MEASURED[("player","onoff_off")] = **−0.213**` —
the offensive on/off split anti-correlates with itself across a split season. The app
already says so in three places (`pages/6_Team_Dashboard.py:4332`,
`helpers/dashboard/insights_deep.py:271` and `:443`). This is a case where "computed but
never rendered" is the right answer, and it is the same failure mode the
`second-quantity-catches-inverted-verdicts` note describes.

One asymmetry worth noting: `("player","onoff_def") = **+0.366**`, so the *defensive*
half is measurably real while the offensive half is not — and `def_diff`,
`on_drtg`, `off_drtg`, `on_dposs`, `off_dposs` are all returned and all unrendered.
A defence-only on/off column is defensible where the offensive one is not.

## B4. `defenses.team_turnover_forced_split` — DOWNGRADED to a KPI, not a new read
`helpers/defenses.py:377`. **Zero callers** outside `tracker/test_forced_turnovers.py`
— that part is correct.

**But the concept is already on screen.** `helpers/dashboard/defense_tab.py:619-646`
renders steal-forced vs unforced as a stacked bar per defensive scheme, both
directions, from the LIVE `defenses.team_defense_turnovers` (whose rows carry
`forced`/`unforced` with the identical semantics — its own docstring cross-references
`team_turnover_forced_split` at `helpers/defenses.py:344`). I initially wrote "nothing
on any page says it today". That was wrong.

**What the uncalled function actually adds**, measured on the snapshot:

| team | forced_split over ALL turnovers | the rendered chart's scheme-tagged coverage |
|---|---|---|
| Adair Girls (defense) | 316/528 = **59.8%** | 444/528 = 84% of them |
| Vinita Girls (defense) | 28/77 = **36.4%** | 77/77 = 100% |
| Adair Girls (committed) | 143/287 = 49.8% | — |
| Claremore (Sequoyah) (defense) | 48/101 = 47.5% | — |
| Kansas Girls (defense) | 81/144 = 56.3% | — |

Two things: (a) it covers turnovers with **no defense tag** — 16% of Adair's forced
turnovers are missing from the rendered chart entirely; (b) it gives the **single team
ratio** the stacked bar can only be eye-summed into. Adair takes 60% of the turnovers
it forces by steal; Vinita takes 36% — an "we take it away" vs "we wait for mistakes"
distinction that is real but currently requires mentally adding up eight bars.

**Natural home:** one KPI tile above the existing stacked-bar chart on
Charts → Defense. **Effort:** trivial. **Honest value: modest** — a headline number
over an existing chart, not a new analytic. The label **"steal-forced"** (an
acknowledged undercount, per the docstring) must ride onto the screen with it.

## B5. `exploit.defensive_plan["their_leaks"]` — PARTIAL
`helpers/exploit.py`. LIVE via `game_plan` → `pages/9_War_Room.py:873`. The page reads
`dfn["throw"]` (L897) and `dfn["avoid"]` (L900) and **never touches `their_leaks`**
(grep: the string appears nowhere in `pages/` or `helpers/dashboard/`).

Measured, opponent = Adair Girls, girls pool:

```
throw       (rendered): Man press 0.27 (55 poss) · Man-to-man 0.63 (545) · 2-3 zone 0.71 (316) · Box-and-1 0.79 (14)
avoid       (rendered): 3-2 zone 1.60 (10) · 1-3-1 zone 1.45 (11) · 1-2-1-1 press 1.33 (6)
their_leaks (NEVER RENDERED):
   Scramble / transition   0.52 PPP allowed   106 poss   stable=True
   2-3 zone                0.43 PPP allowed   120 poss   stable=True
   Man-to-man              0.40 PPP allowed   842 poss   stable=True
   Diamond-and-1           0.40 PPP allowed     5 poss   stable=False
```

`their_leaks` is the only half of this engine that answers **"what should MY offense
attack?"** — the other two answer "what defense should I play?". The War Room's
pre-game card is therefore missing its offensive side, and the three stable rows here
have far more sample behind them (106–842 poss) than the `avoid` rows the page *does*
render (6–11 poss).

**Natural home:** `pages/9_War_Room.py` around L900, as a third line in the same block.
**Effort:** trivial — the data is already in `dfn`; it is three lines of the same
formatting already written for `throw`/`avoid`.

## B6. `matchups.matchup_table` — PARTIAL (`top_shooter`, `fga_3`, `made_allowed_3`)
`helpers/matchups.py`. LIVE at `pages/7_Players.py:_fx_plab`, which renders `FGA`,
`FG%` and the difficulty chart. Three returned keys never reach a screen (grep-verified
across `pages/` + `helpers/dashboard/`).

Measured, Adair Girls' 24 tracked games (166 defenders in the full league pass):

| defender | contested FGA | FG% allowed | distinct assignments | top_shooter (unrendered) | 3PA allowed | 3PM allowed |
|---|---|---|---|---|---|---|
| Ali Schwerdfeger | 117 | 27.4% | 59 | K Holt | 23 | 2 |
| Hannah Bond | 114 | 19.3% | 59 | #34 | 17 | 2 |
| Kealey Sanders | 73 | 38.4% | 55 | L Schiesel | 23 | 4 |
| Reagan Langley | 62 | 22.6% | 42 | #13 | 12 | 2 |
| Finley Grubbs | 52 | 19.2% | 33 | #20 | 19 | 5 |
| Morgan Boyles | 49 | 32.7% | 33 | E Gibson | 17 | 4 |

Read at the render site (`pages/7_Players.py:1833-1846`), the shipped columns are
Defender / Team / Contested / Allowed / FG% allowed / Pts allowed / **Assignments**.

Honest split of the three unrendered keys:

- **`fga_3` / `made_allowed_3` — genuinely absent, no substitute anywhere.** They
  answer *"can she close out?"*: Finley Grubbs allows 5 makes on 19 threes (26%)
  against Hannah Bond's 2 on 17 (12%) — a separation the pooled FG% column hides
  completely. Two columns, zero new computation.
- **`top_shooter` — weaker than it looks.** `pages/7_Players.py:1848-1866` already
  ships a "Who did they guard?" selectbox rendering the full `by_shooter` table for
  one defender at a time, and `top_shooter` is just the argmax of that. It would add
  the at-a-glance version of an existing drill-down, not new information.

**Natural home:** the on-ball table already on Players → Lab. **Effort:** trivial.

## B7. `situational.player_margin_scoring` — BURIED behind a z-gate
`helpers/situational.py:538`. Only caller is `insights.garbage_edges`; the miner's
`_g_garbage` generator drops every player whose `|z| < MIN_Z`, so on a normal roster
most rows never produce a line.

**Coach question:** *"Whose points came when the game was still live?"*

Measured, Adair Girls, 24 tracked games:

| player | pts | garbage share | close share |
|---|---|---|---|
| Ali Schwerdfeger | 329 | 32.8% | 26.7% |
| Hannah Bond | 293 | 30.0% | 35.5% |
| Kealey Sanders | 180 | 39.4% | 26.1% |
| Reagan Langley | 169 | 32.5% | 27.2% |
| Finley Grubbs | 137 | 44.5% | 29.2% |
| **Carly Buell** | 85 | **94.1%** | **2.4%** |
| Katence Hughes | 76 | 69.7% | 6.6% |
| Morgan Boyles | 49 | 63.3% | 14.3% |
| Kodi Schwerdfeger | 48 | 87.5% | 0.0% |

The bench column is the finding and it is unambiguous: four players' scoring lines
are 63–94% garbage-time points. A roster table makes that legible in one look; the
miner can only ever say it about whichever single player clears the z-gate.

**Natural home:** Insights → "Who's helping", as a small table under the existing
`_ported_cards(... "garbage" ...)` line, or Team Dashboard → Charts → Situational.
**Effort:** low. `garbage_edges(events)` already returns the whole dict inside
`build_feed`'s `parts`; the values are simply not kept after the miner runs.

## B8. `deserved.game_ledgers` / `for_team` — PARTIAL
`helpers/deserved.py`. LIVE via `team_deserved` → `insights_tab._render_deserved_games`,
which renders Date / Opponent / Result / the four terms / FGA / ORB / TOV /
contest-rate for all 24 games.

Never rendered: `fg_margin`, `pts_fg`, `xpts`, `opp_pts_fg`, `opp_xpts`, per-row
`xmargin` (it shows only for the single "widest gap" game), and `low_contest`.

Measured, Adair Girls (first six of 24 rows):

```
2025-12-11 vs Westville          margin +21  xmargin +13.1  fg_margin +10  ft_margin +11
2025-12-13 vs Locust Grove       margin  -7  xmargin  +0.5  fg_margin  -6  ft_margin  -1
2026-01-03 vs Wyandotte          margin +50  xmargin +28.9  fg_margin +46  ft_margin  +4
2026-01-06 vs Oklahoma Union     margin +45  xmargin +37.1  fg_margin +36  ft_margin  +9
2026-01-08 vs Bishop Kelley      margin +34  xmargin +26.9  fg_margin +36  ft_margin  -2
2026-01-09 vs Glenpool           margin  +6  xmargin  -4.8  fg_margin  +4  ft_margin  +2
```

The cheapest win here is **`xmargin` as a per-row column**. The table's whole promise
is "what the play deserved vs what happened", and the deserved number is present for
every row but printed for one. Glenpool is a 6-point win on −4.8 of play; the page shows
only the +6.

`low_contest` (`LOW_CONTEST = 0.50`, `helpers/deserved.py:95`) flags **6 of 24** Adair
games whose contest tagging fell below 50% — 0.35 to 0.44. The table prints each game's
`Contested` percentage but never marks which rows the engine itself considers
under-tagged. One conditional glyph, data already in hand.

**Natural home:** `helpers/dashboard/insights_tab.py:_render_deserved_games`.
**Effort:** trivial.

## B9. `shot_kinds.share_reads` — PARTIAL/BURIED (a reliability gate that is never asked)
`helpers/shot_kinds.py:514`. Zero callers. Its twin `rate_reads` IS live at
`helpers/dashboard/shot_diet.py:208`.

The docstring states the module's own display rule:
> "It exists so a renderer asks the same question of both halves of a table instead of
> dotting rates and leaving shares naked."

That is exactly what happens today. Measured on the league kind table:

```
share_reads (NEVER CALLED)          rate_reads (LIVE at shot_diet.py:208)
  rim         fair  sb=0.71 show=True    rim         unmeasured sb=None show=False
  floater     fair  sb=0.71 show=True    floater     unmeasured sb=None show=False
  mid         fair  sb=0.73 show=True    mid         unmeasured sb=None show=False
  corner3     fair  sb=0.71 show=True    corner3     unmeasured sb=None show=False
  abovebreak3 fair  sb=0.71 show=True    abovebreak3 unmeasured sb=None show=False
```

**Honest sizing:** wiring it changes no number and hides no cell — every band comes
back `show=True` at r≈0.71, which the docstring already predicted ("this rarely
withholds"). What it adds is the `r=` chip and caption ("Directional (r=0.71) — real,
will still move") beside shares that currently carry no confidence mark at all, while
the rates next to them are being withheld entirely. **Effort:** trivial, one call
beside the existing `rate_reads` call. **Value:** consistency, not new information.

## B10. `passing_chains.hast_coverage` / `coverage_line` — BURIED (the empty-state explainer)
`helpers/passing_chains.py:301` / `:332`. Reached only from `tools/snapshot_report.py`
(an admin script), never from a page.

Measured, girls tracked pool:
```
hast_coverage(events) -> {'tagged': 0, 'made': 0, 'missed': 0, 'games': 0,
                          'pairs': 0, 'regate_at': 50, 'ready': False}
coverage_line(cov)    -> "Hockey assists: none tagged yet — turn on the Hockey Assist
                          picker in the shot flow to light this up."
hockey_triples(events) -> []   (empty, as expected from zero tagging)
```

Zero hockey assists tagged on the entire book. Verified at the render site:
`helpers/dashboard/player_card.py:1225-1235` wraps the whole "Who they ignite" block
in `if _ch:` — so with nothing tagged the section is **silently omitted with no empty
state at all**. The coach never learns the feature exists or what would light it up.
`coverage_line` is a one-sentence answer to exactly that, and it already speaks plainly
about an empty book rather than printing "0 / 50".

**Natural home:** `helpers/dashboard/player_card.py` beside the `hockey_chains` block,
and/or the coverage chip family in Setup. **Effort:** trivial (one call, one caption).
**Value:** low information, but it converts a silently dead feature into an
actionable prompt — this is the exact "HAST inert until tagged" state.

## B11. `shot_kinds.league_table` / `both_tables` — BURIED, low value
Both NOCALL. `league_table` produces the pooled baseline every team read compares to:
```
rim 27.4% (836)  floater 25.4% (777)  mid 12.1% (370)  corner3 9.3% (285)
abovebreak3 25.8% (788)  unknown n=190 (share None)
```
`both_tables` returns the band cut alongside:
```
rim04 27.4% (836)  two419 37.5% (1147)  arc3 22.6% (692)  deep3 12.5% (381)  unknown 190
```
The live renderer (`shot_diet.py`) reconstructs the league comparison through
`SK.diet(...)`, so this is duplicated capability rather than missing information.
The one novel number is **`unknown` = 190 of 3,246 shots (5.9%) with no usable
location** — a capture-coverage figure no page reports. Classify as low-priority.

---
# SUMMARY TABLE
898 public module-level entry points across 130 modules under `helpers/` (including
`helpers/dashboard/`). 853 reach a rendered page through the call graph; 45 do not.
Listed below: every priority module, plus every module with an unreached public entry.
"Reach a page" = a `pages/*.py` or `Main.py` call, directly or transitively, including
through module-level registries.

| module | public entry points | reach a page | not reached (names) |
|---|---|---|---|
| `helpers.archetypes` | 4 | 4 | — |
| `helpers.auth` | 24 | 23 | `set_team_shares_pool` |
| `helpers.cards` | 22 | 21 | `gauge_range` |
| `helpers.change_requests` | 6 | 5 | `pending_count` |
| `helpers.charges` | 5 | 5 | — |
| `helpers.courtside` | 6 | 5 | `late_game` |
| `helpers.dashboard.insights_brief` | 3 | 2 | `render` |
| `helpers.dashboard.insights_deep` | 6 | 6 | — |
| `helpers.dashboard.insights_tab` | 1 | 1 | — |
| `helpers.defense_profile` | 7 | 7 | — |
| `helpers.defenses` | 11 | 10 | `team_turnover_forced_split` |
| `helpers.deserved` | 5 | 5 | — |
| `helpers.development` | 8 | 8 | — |
| `helpers.entitlement` | 16 | 15 | `gating_identity` |
| `helpers.excitement` | 2 | 1 | `adj_gei` |
| `helpers.exploit` | 5 | 5 | — |
| `helpers.foul_trouble` | 11 | 10 | `crew_foul_rate` |
| `helpers.gameflow` | 6 | 6 | — |
| `helpers.hero_ball` | 5 | 5 | — |
| `helpers.identity` | 10 | 9 | `person_key_sql` |
| `helpers.insights` | 24 | 24 | — |
| `helpers.insights_severity` | 15 | 15 | — |
| `helpers.insights_team` | 8 | 8 | — |
| `helpers.involvement` | 3 | 3 | — |
| `helpers.lineup_projection` | 11 | 11 | — |
| `helpers.lineups` | 5 | 5 | — |
| `helpers.matchups` | 4 | 4 | — |
| `helpers.networks` | 5 | 5 | — |
| `helpers.offense_profile` | 4 | 4 | — |
| `helpers.passing_chains` | 7 | 4 | `hockey_triples`, `hast_coverage`, `coverage_line` |
| `helpers.playbook` | 8 | 8 | — |
| `helpers.player_ratings` | 19 | 17 | `leaf_tier`, `group_tier` |
| `helpers.playtypes` | 14 | 14 | — |
| `helpers.possession_value` | 3 | 3 | — |
| `helpers.projection` | 6 | 4 | `tracked_baseline`, `career_game_ids` |
| `helpers.public_feed` | 7 | 0 | `clear_cache`, `scoreboard`, `state_by_token`, `viewer_key`, `fan_count`, `team_profile`, `teams_directory` |
| `helpers.rating_history` | 8 | 7 | `has_history` |
| `helpers.reliability` | 7 | 5 | `spearman_brown`, `band_level` |
| `helpers.rotation_plan` | 4 | 4 | — |
| `helpers.rotation_schedule` | 4 | 4 | — |
| `helpers.runs` | 5 | 5 | — |
| `helpers.scoutboard` | 11 | 11 | — |
| `helpers.seasons` | 21 | 20 | `auto_advance_if_due` |
| `helpers.shot_kinds` | 18 | 14 | `both_tables`, `league_table`, `share_reads`, `kind_by_tag` |
| `helpers.simulation` | 6 | 5 | `simulate_tournament` |
| `helpers.situational` | 8 | 8 | — |
| `helpers.spacing` | 4 | 4 | — |
| `helpers.stats` | 93 | 89 | `paint_fga`, `stocks`, `app`, `team_game_ids` |
| `helpers.stops` | 2 | 2 | — |
| `helpers.team_insights` | 14 | 13 | `team_insights` |
| `helpers.team_ratings` | 10 | 9 | `hybrid_ratings` |
| `helpers.ui` | 38 | 32 | `clear_settings`, `season_picker`, `gauge`, `kpi`, `loading`, `chip` |
| `helpers.winning_formula` | 6 | 6 | — |

---
# LIVE, but not from a Streamlit page (do NOT read these as buried)
These 10 have no `pages/` caller and would be listed dead by a page-only scan. They
are the FastAPI tracker's surfaces and the admin/cron surfaces.

| function | real surface |
|---|---|
| `public_feed.scoreboard` | `tracker/api.py:public_scoreboard` — the public fan scoreboard |
| `public_feed.state_by_token` | `tracker/api.py:public_game` — a shared game link |
| `public_feed.viewer_key` | `tracker/api.py:public_game` |
| `public_feed.fan_count` | `tracker/api.py:game_detail`, `toggle_public` |
| `public_feed.team_profile` | `tracker/api.py:public_team` |
| `public_feed.teams_directory` | `tracker/api.py:public_teams` |
| `public_feed.clear_cache` | `tracker/api.py:finish`, `undo`, `toggle_public` |
| `excitement.adj_gei` | `public_feed._live_gei` -> the public scoreboard |
| `entitlement.gating_identity` | `tracker/api.py:_resolve_user` — the auth path |
| `seasons.auto_advance_if_due` | `tools/auto_season_rollover.py:main` — the rollover timer, **which is not installed on the VPS**, so in production this code currently runs nowhere |

---
# DEAD — with the trace that proves it
Everything here was grep-verified across the entire tree (`pages/`, `helpers/`,
`tools/`, `tracker/`, `database/`, `deploy/`, `Main.py`). Where a name still appears
somewhere, the appearance is a docstring or a same-named local, noted per row.

### Superseded — a newer implementation took the surface

| function | superseded by | trace |
|---|---|---|
| `helpers/dashboard/insights_brief.py:226 render` | `insights_deck.render` (`insights_tab.py:592`) plus `insights_deep` | Six modules import `insights_brief`, and every one imports only its **helpers** — `BR._hdr`, `BR._tile`, `BR._identity`, `BR._margin_bar`, `BR._signed`, `BR._TERMS`, `BR.block`, `BR.grid`. No importer names `render`. `insights_deck`'s own docstring says the deck "occupies that space". About 135 lines of dead renderer. |
| `helpers/team_insights.py:1208 team_insights` | `team_insight_feed` | Zero callers. Ran both against the snapshot: output **identical** for team 1. Also carries a bare `season="Current"` default — the rollover trap from the season-sentinel rule. |
| `helpers/simulation.py:98 simulate_tournament` | `bracket_tree` (`pages/9_War_Room.py:181`) | Zero callers. `bracket_tree`'s docstring says it returns `"odds": <same list as simulate_tournament>` and computes it itself; the War Room comment at L181 confirms it takes both from `bracket_tree`. Duplicated round-probability logic. |
| `helpers/courtside.py:251 late_game` | direct calls to its own parts | `pages/2_Game_Tracker.py` calls `_CS.leverage_now` (L745), `_CS.run_alert` (L758), `_CS.foul_up_3` (L774), `_CS.comeback_gauge` (L780) — every branch of the dispatcher, individually. The wrapper itself has zero callers. |
| `helpers/stats.py:574 stocks` | inline arithmetic | `helpers/stats.py:285` computes `b["stocks"] = b["STL"] + b["BLK"]` directly in the box builder; every consumer reads the key. The accessor has zero callers. Same pattern for `stats.paint_fga` (L475; consumers read `b["paint_FGA"]`, e.g. `box_score.py:908`) and `stats.app` (L702). |
| `helpers/shot_kinds.py:537 kind_by_tag` | `kind_by_shot_tag` (L573) | Zero callers; the only other mention in the tree is `kind_by_shot_tag`'s own docstring naming it. The live variant does the same cross-tab from an already-scoped shot feed instead of a second event pass, and its docstring says that is "the whole reason this variant exists" on a 1 vCPU box. Consumers: `shot_diet.py:316` and `:330`. See B1. |
| `helpers/stats.py:2036 team_game_ids` | `stats._team_game_ids` / `_team_game_ids_all` | Zero callers. `team_analytics.py:806` explicitly notes it is "Distinct from stats.team_game_ids", i.e. the codebase routed around it. Every remaining `team_game_ids` hit in the tree is an unrelated keyword argument (`spacing.py:90`, `insights_identity.py:45`). |

### Decided off / deliberately not rendered (dead by design, not by neglect)

| function | why |
|---|---|
| `helpers/team_ratings.py:479 hybrid_ratings` | `tools/tracked_calib.py:56` — "keep hybrid_ratings OFF until this harness says otherwise". Verified on the snapshot: for all 704 girls teams it returns the score rating unchanged (`hybrid_w=None` for every untracked team; top-8 order identical to `score_ratings`). |
| `helpers/foul_trouble.py:855 crew_foul_rate` | Its own docstring forbids it: "Handing back a `rate` key would invite a caller to render it... Call it, store it, let the sample grow; **do not put it on screen**." Measured at r = -.254 on about 6 qualifying cells. Correctly unsurfaced. |
| `helpers/lineups.py:348 player_on_off` (as a table) | `reliability.MEASURED[("player","onoff_off")] = -0.213`. See B3. |

### Test-only / tooling-only helpers

| function | only reachable from |
|---|---|
| `player_ratings.leaf_tier` (L805), `group_tier` (L811) | `tracker/test_leaf_tiers.py`, `test_reb_plumbing.py` — the tier-coverage audit. The app reads the `LEAF_TIER` dict directly. |
| `reliability.spearman_brown` (L112) | `tracker/test_shot_kinds.py`. The `MEASURED` book already stores SB-corrected values, so nothing corrects at runtime. Verified working: `spearman_brown(0.5) = 0.667`. |
| `projection.tracked_baseline` (L257), `career_game_ids` (L358) | `tracker/test_projection.py`. Both work: `tracked_baseline(gender="F", season="2025-2026")` returns 14 stats (eFG% 39.55, TS% 43.26, TOV% 27.88, OREB% 7.52, ...); `career_game_ids(1)` returns 8 ids. |
| `passing_chains.hast_coverage`, `coverage_line` | `tools/snapshot_report.py:106-107` only. See B10. |
| `identity.person_key_sql` (L26), `change_requests.pending_count` (L52), `auth.set_team_shares_pool` (L220), `rating_history.has_history` (L180), `defenses.team_turnover_forced_split` (L377), `passing_chains.hockey_triples` (L94), `shot_kinds.classify_shot` / `classify_band_shot` / `both_tables` / `share_reads` | their `tracker/test_*.py` and nothing else |

### Genuinely unused, zero mentions anywhere
`helpers/cards.py:529 gauge_range` (only its own module header at L15 names it);
`helpers/ui.py` — `clear_settings` (L196), `season_picker` (L434), `gauge` (L524),
`kpi` (L564), `loading` (L652), `chip` (L995). Every remaining tree hit for these
names is a CSS class string (`kpi-tile`, `stat-chip`) or an unrelated word in prose —
none is a call. `helpers/reliability.py:657 band_level` (works: returns `stable` for
`("team","band_share","rim")`) — a one-line convenience over `level(measured(...))`
that no caller uses.

**Filed as INTERNAL rather than DEAD** (could not prove unreachability): every
`insights.*_edges` builder (module-level `_FEED_STAGES` registry), every
`team_insights.*_extra` (reached via `team_extras`),
`development.progression` / `project_next` / `project_rest_of_season` / `season_lines`
(reached via `player_development` -> `player_card._dev`),
`exploit.offensive_exploits` / `defensive_plan` (reached via `game_plan`),
`deserved.game_ledgers` / `for_team` (reached via `team_deserved`),
`rotation_schedule.preset_fives` / `blocks_from_minutes` / `short_names`,
`shot_kinds.kind_table` / `team_table` / `player_table` / `conversion_value` /
`excess_floaters`, `spacing.team_components`, `hero_ball.team_shares`,
`gameflow.infer_starters` / `rotation`.

---
# MEASURED CONTRADICTIONS OF DOCSTRINGS AND COMMENTS

1. **`foul_trouble.bench_cost` — `drag` is not what the docstring says.**
   Docstring: "`drag` = before - after, in share points." Measured on the snapshot,
   Finley Grubbs / 2nd foul: `before_share` 98.8, `after_share` 55.7, difference
   **43.1**, but the returned `drag` is **13.1** = `season_share - after_share`
   (68.9 - 55.7). The docstring describes the *other* returned key, `in_game_drag`,
   which it does not mention at all — along with `season_share` and `team_id`.
   The verdict text ("she loses 13 percentage points of floor share") is correct for
   the value it prints; only the docstring is wrong.

2. **`projection.tracked_baseline` — "Shared with helpers.lineup_projection" is false.**
   `helpers/lineup_projection.py` contains no reference to `tracked_baseline`. Its
   only baseline concept is `net_vs_baseline`, computed locally at L331. The function
   has no non-test caller anywhere.

3. **`shot_kinds.share_reads` — the display rule it states is not the shipped one.**
   "It exists so a renderer asks the same question of both halves of a table instead
   of dotting rates and leaving shares naked." The shipped renderer
   (`shot_diet.py:208`) calls `rate_reads` and never `share_reads`, so shares ship
   naked and rates ship withheld — precisely the asymmetry the docstring is written
   against.

4. **`insights_brief.py` module docstring calls itself "the auto-scout board at the top
   of Insights."** It is not at the top of Insights; `insights_deck.render` is, and
   `insights_brief.render` is called by nobody. The file's "REGISTER, AND WHY IT
   CHANGED" and "DENSITY IS THE POINT" sections read as live design guidance for a
   surface that no longer exists.

5. **`exploit.defensive_plan` docstring documents `their_leaks` as a first-class
   return key** ("schemes THEY run that get scored on"). Its only consumer,
   `pages/9_War_Room.py`, reads `throw` and `avoid` and drops it. The documented
   contract is honoured by the engine and ignored by the surface.

6. **Not a contradiction, but worth recording:** `pages/7_Players.py` calls
   `MX.matchup_table()` with no arguments, so `stats.fetch_events(None)` returns
   **every event in the database, across every season**. That is the intended
   league-wide Lab behaviour on this book (one populated season), but it is
   unscoped by season and will silently pool seasons after the next rollover — the
   same class of latent bug as the bare `season="Current"` defaults.

---
# PRIORITY ORDER (coach value / effort)
1. **B5** `exploit.defensive_plan["their_leaks"]` — 3 lines in War Room, adds the
   missing offensive half of the pre-game plan, 106-842 poss behind each row.
2. **B7** `situational.player_margin_scoring` roster table — see 4 below; promoted
   because nothing renders it at all today.
3. **B1** the play-type axis of `kind_by_shot_tag` — parameterize the tag in
   `render_concedes` (it hardcodes `"defense"` twice). Their post-ups reach the rim
   71% vs a 50% league post-up rate; their off-screen actions land 16 points more
   short. Must be league-normalized, per the module's own recorded lesson.
4. **B6** `matchups.matchup_table` `top_shooter` plus the 3P split — two columns on a
   table already on screen (`assignments` already renders; these three do not).
5. **B8** `deserved` per-row `xmargin` plus the `low_contest` flag — trivial, and it is
   the number that table exists to show.
6. **B4** `defenses.team_turnover_forced_split` — a KPI tile over a chart that already
   shows the split per scheme. Modest.
7. **B9 / B10 / B11** — consistency and empty-state work, not new information.

**Retracted from this list after verification:** `foul_trouble.bench_cost` (B2 — the
full table already renders on Charts → Situational) and the defense axis of the
shot-kind cross-tab (B1 — already renders, league-normalized, on the Defense tab).
`lineups.player_on_off` (B3) is buried on purpose and must stay buried.
