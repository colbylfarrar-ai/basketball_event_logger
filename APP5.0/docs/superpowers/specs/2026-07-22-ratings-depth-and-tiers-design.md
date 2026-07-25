# Ratings depth & data-tier weighting — design (2026-07-22)

Status: DESIGN APPROVED (tracks A + coverage-gated xA2).
**Part 8 (2026-07-24) is the live build order and supersedes the Part 3 list.**
**BUILT 2026-07-24 through Part 8 commit 11** — FT% and box-out payoff adopted
(rho 0.681 -> 0.688), surfaces + xA2 shipped, ScrAST rejected, HAST still
inconclusive. Part 3 tier architecture and Parts 4-5 remain UNBUILT and are the
next session. Numbers and lessons: docs/MAINTENANCE_BATCH_2026-07-22.md §9.
Parts 1-6 are the 07-22 design; Part 7 captures roster rollover; Part 8 records
the code facts that reordered the build and where the 07-24 run stops.

Everything here obeys the recal-round-2 rule: **no leaf/constant ships without
the walk-forward gate** (lean-T2 rho ≥ baseline; T6/T4 where relevant).

---

## Part 1 — Approved this session (founder picked A: both tracks + xA2)

### §1 Guarded% rebounding leaf, gate-swept into REBOUNDING
- Leaf: `def_secure_team_stab` (EB-stabilized "on-ball defender → team ends
  possession", `helpers/rebounding.py:113`). Home: `_DREB`. Sweep 0.4 / 0.6.
- ONLY this leaf. `onball_share` = style axis, `own_miss_rec` = rare event —
  both stay surface-only.
- Plumbing: map `player_rebounding()` metrics into `player_stat_table` P /
  profiles (event-only; None below `MIN_ONBALL=5` → None-skip).
- Gate: new `tools/gate_reb_guarded.py` cloning `gate_xa_hast.py`; register
  `_DREB` in the backtest registry.
- Data check (live DB 2026-07-22): 2,545 missed FGs; 1,937 w/ guarded_by;
  1,636 w/ both guarded_by + rebound_by. Well-fed — gate-testable now.

### §2 "Do it all" surfaces (descriptive, no gate)
- New badge (Rebounding/Two-Way): box-out payoff, keyed on
  `def_secure_team_stab`, `onball_misses ≥ 5` gate.
- Player-card rebounding verdict line: off-ball crash + box-out payoff +
  own-miss recovery combined read.
- Archetypes k-means FEATURES untouched (cluster stability); Glue-Guy blurb
  may cite the read.

### §3 HAST context surfaces + pre-registered re-gate
- Chain-pairs helper: `hockey_from → assister → shooter` triples. HAST
  (made) is the headline; misses count as POTENTIAL hockey assists
  (PotHAST — same relationship PotAST has to AST, capture is make-or-miss,
  see §4). "Who ignites whom" row (honest empty state until tagged).
- Coverage line in snapshot/admin: "HAST tagged: N — re-gate at ≥50".
  N counts ALL tagged rows (make or miss — capture coverage), while the
  gate's HAST/G leaf stays make-only.
- Re-gate: `tools/gate_xa_hast.py` unchanged, re-run at n ≥ 50; weights
  0.2/0.3 already defined. Adoption ONLY through the gate.
- Status: capture wired 2026-07-22 (founder); local DB shows 0 tagged.

### §4 Coverage-gated secondary xA — SEPARATE stat, never inside xA/G
- CONSTRAINT: `xA/G` is a gate-adopted rating leaf (0.75, #8d). Mutating its
  computation = silent unguarded rating change. Forbidden.
- New field `xA2` ("hockey xA"): λ = 0.5 × the shot's expected-make value,
  credited to `hockey_from_id`. Separate P keys `xA2` / `xA2_pts`; surfaced
  beside xA (player card + glossary).
- CAPTURE FACT (verified 2026-07-22): `hockey_from_id` is logged make OR
  miss — PWA `SHOT_DETAILS` offers it on every shot flow (app.js:1403),
  Streamlit selectbox ungated (2_Game_Tracker.py:1243; its "only meaningful
  on made" comment is stale — update it). Only the HAST STAT is make-only
  (sibling of AST, correct by definition).
- Therefore xA2 = Σ expected-make value over ALL hockey-tagged shots, make
  or miss — genuinely make-independent, same construction as xA. NOT a
  make-conditioned floor (earlier draft wrong).
- Honesty caption: tag-selection bias instead — coaches may tag the second
  pass more often when the shot DROPS; state it, revisit once tag volume
  shows the make/miss tag mix.
- Coverage gate: render only when team has HAST tags in ≥ 3 games; else
  honest empty state. No cross-team pool comparison until league coverage
  is real. Ratings entry (if ever) = its own gate sweep.

### §5 Tests
- TDD units per helper (rebounding-leaf mapping, badge gate, chain pairs,
  xA2 credit + coverage gate). Gate runs recorded in the maintenance doc
  with rho numbers + verdicts. Real-DB smoke: P build + card render.

---

## Part 2 — Additional fold-in candidates (surveyed 2026-07-22, all gate-swept)

Ranked value:effort. Each ships ONLY on rho ≥ baseline.

1. **FT% → `_SHOOTING` 0.5.** Computed in P (`player_ratings.py:1411`) but
   never made a leaf (only FTR is). Box-derivable → raises depth for BOX
   coaches too, not just tracked. Zero plumbing. Sweep first.
2. **def_secure_team_stab → `_DREB`** (Part 1 §1).
3. **ScrAST/G → `_PLAYMAKING` 0.3/0.4.** Off-ball creation axis. Redundancy
   risk: screens partially inside SC/G + SCPass/G — sweep must include
   both-in vs replace variants (same discipline as xA-vs-SCPassQ in #8d).
4. **DWPA/G (possession-mode defensive WPA) → `_DEFENSE_PARTS` 0.3.**
   `helpers/wpa.py` mode="possession": credits stealer / def rebounder /
   blocker / on-ball defender in win-prob currency. Fixed in recal round 2
   (EP scope + team-split). Overlaps DRtg + RAPM impact → gate decides.
5. **WPA/G (offense) → `_OVERALL_PARTS` 0.2.** Likely rejected (GS + impact
   overlap) but free to sweep alongside DWPA in one harness run.
6. **ClutchFT% — SKIP.** Rare-event, noisy n. Surface-only.

Confirmed NON-candidates (do not re-litigate):
- **PotAST** — literally the same field as the existing SCPass/G leaf
  (`b["SC_pass"]`, `player_ratings.py:1375-1379`).
- **Corsi** — RAPM `impact` duplicate (locked, #8d).
- **onball_share / own_miss_rec** — style/rare, surface-only (§1).
- **spacing / exploit / handedness** — team-level scouting reads, not
  player-quality leaves.

---

## Part 3 — Data-tier weighting architecture (box → possession → tagged)

Commitment to uphold: every tier of data a coach provides INCREASES the
depth of the rating. Box coach gets an honest rating; tracked coach gets a
more detailed read with noise sorted.

### Today's mechanics (binary)
- Manual box game: `MANUAL_GAME_WEIGHT = 0.35` evidence; feeds only
  box-derivable leaves (`_MANUAL_BOX_KEYS`); event leaves never read it.
- Tracked game: full evidence, all leaves.
- Within tracked, optional-tag leaves (SMOE, DSHOT%, xA, …) None-skip per
  player when tags absent — ratings don't KNOW a coach's tag coverage.

### Design — three-tier leaf taxonomy
- **T1 BOX** — TS% / eFG% / 3P% / FT% / FTR / 3PR, per-game counting stats,
  GS / EFF / FIC.
- **T2 POSSESSION** — tracked events, no optional tags needed: USG%, MPG,
  PPP, PPSA, VPS, AST%, on/off, RAPM impact, WPA/DWPA, OREB%/DREB% on-court.
- **T3 TAGGED** — needs optional tags: SMOE, DSHOT%, RimProt/PerimD,
  Guarded%, SCPassQ, PassFG%/PassOpen%, xA, def_secure, HAST, xA2.

### Mechanisms
1. **Leaf registry gains a tier tag.** Every leaf tuple declared
   T1/T2/T3 in one table. Self-documenting; feeds everything below.
2. **Per-category evidence** replaces the single games-equivalent for
   shrink-to-50: a category's evidence = games that actually fed ITS leaves
   at their tier (manual still 0.35). Never-tags coach → DEFENSE built from
   T1+T2 only → lower evidence → more shrink → honest, not falsely precise.
   This is the "sort noise" mechanism.
3. **Per-category tier chip** on the player card: "rated from: box /
   possession / full tracked". Reuses `helpers/coverage.py` (already
   measures play_type / guarded_by / defense coverage per team).
4. **Stabilized twins standardized as leaf inputs** where thin (SMOE
   `poe_shrunk`, `def_secure_team_stab` pattern) — audit leaves for raw
   thin-n inputs and swap to EB twins where one exists.
5. **Depth commitment is structural** — re-standardized composites widen
   spread as leaves are added (player_ratings docstring, step 3). Make it
   MEASURABLE: extend the backtest to report rho/MAE per tier cohort
   (box-only vs possession vs full-tagged). The marketing claim becomes a
   number, re-checked every recal.
6. **Gate protocol unchanged.** Tier weights, per-category shrink k, every
   new leaf: lean-T2/T6 walk-forward before adoption. The per-category
   evidence change is itself a constant change → gate it (T4 LOGO MAE the
   natural metric, as in the k retune).

### Build order (next session)
1. FT% sweep (cheapest, box-tier win) + §1 def_secure sweep — one harness
   session, two gates.
2. §2 do-it-all surfaces + §3 HAST surfaces (no gate needed).
3. §4 xA2 (surface + coverage gate).
4. ScrAST / DWPA / WPA sweeps (one combined harness run).
5. Tier taxonomy tag on the leaf registry (mechanical, no behavior change).
6. Per-category evidence + tier chips — the real build; gate before adopt.
7. Backtest per-tier cohort reporting — proves the commitment.

---

## Part 4 — Backend deep-dive: idea backlog (surveyed 2026-07-22)

Founder ask: full engine/helper look for untried uses of the event table —
ball movement, cross-sport steals, player combos ("triples, groups of 4").

Inventory fact: 90 helpers. Existing combo coverage: PAIRS
(`networks.py` — pair net per 100, solo-net baseline) and FULL FIVES
(`lineups.py` — observed 5-man units, EB prior, min-poss guard). Trios and
quads are the missing middle — same possession-share machinery
(`itertools.combinations(five, 3|4)`), no new capture.

DEDUPE RULE for the deep-dive session: before building ANY idea below, read
the full docstring of every adjacent helper (they are rich) — several past
"new ideas" already existed (runs, GEI, late_game, situational,
scheme_situational, spacing, exploit, hoopwar, fatigue-as-rest-days).

### Combos (the direct ask)
- **4a. Trio / quad units.** Extend `lineups.py`/`networks.py` possession
  walk to 3-man and 4-man groups. Sparser samples → higher min-poss +
  the `_NET_PRIOR_POSS` EB pattern. Surfaces: best/worst trio; and the
  killer coach tool — **"finisher finder"**: given a strong 4-man core,
  rank candidate 5th players by that unit's observed net. Rotation lever,
  pure fun, zero new capture.
- **4b. Synergy above expectation.** Pair/trio net MINUS what the members'
  solo nets predict — chemistry as an interaction term, not raw net (raw
  net just re-ranks good players standing together).

### Ball movement
- **4c. Connection matrix.** Who→whom assist counts (`pass_from → shooter`),
  xA-weighted; with `hockey_from` tagged, 3-node chains ("who ignites
  whom" — extends Part 1 §3 pairs into a team passing graph). Hockey
  line-combo / soccer key-pass-combo steal. Surfable as a heat-grid on
  Charts → Offense.
- **4d. Involvement rate** (soccer build-up involvement): % of team scored
  possessions where the player has ANY fingerprint (scorer, assister,
  hockey, screen assist, OREB). Cheap walk over existing tags; the
  "do-it-all" team-play twin of the §2 rebounding read.

### Cross-sport steals not yet used
- **4e. Kill counts** (Miami Heat defensive metric): 3+ consecutive stops =
  a "kill"; team per-game + on-floor credit. `runs.py` is POINTS-based;
  stop-strings are not built. Complements the founder's "long runs ARE
  strings of stops" note in runs.py — this names the stops directly.
- **4f. Answer rate** (volleyball side-out%): after an opponent score, how
  often does the next possession score? Team + on-floor split; the
  momentum-stopper stat, finer-grained than runs.momentum.
- **4g. Quality stints** (hockey shift length): within-game stint detection
  from `game_event_lineup` sub sequences — stint net by length, optimal
  shift length per player, fatigue WITHIN a game (`fatigue.py` is
  schedule-level only). Feeds rotation_plan.
- **4h. Shot-diet shaping** (hockey high-danger chances): rim-attempt share
  ALLOWED while a lineup/player is on floor — Corsi machinery × zone tags.
  Defense that funnels to bad shots, visible per unit.
- **4i. Foul-trouble drag** (basketball-native): team net while a starter
  carries 2+/3+ fouls + minutes lost; links `fouls.py` to the on-floor
  data. Coaches argue this daily; no engine answers it.

Already covered — do NOT rebuild: clutch/LI (wpa), Corsi, forced TO split,
xA/HAST, runs+momentum, GEI (excitement), late-game, rest-day fatigue,
lineup SIMULATION (team_analytics/lineup_projection), pass-quality
(SCPassQ/xPPS_created), hoopwar (WAR).

### Ranking (fun × effort, founder taste: verdict-first, depth not clutter)
1. 4a trios/quads + finisher finder — the ask itself, machinery exists.
2. 4e kills + 4f answer rate — one possession-walk pass builds both.
3. 4c connection matrix — ball-movement ask, builds on §3 chains.
4. 4i foul-trouble drag — high coach resonance, small.
5. 4g stints — rotation value, medium.
6. 4d involvement — small, fun, do-it-all tie-in.
7. 4b synergy, 4h shot-diet — nice-to-have depth.

None are rating leaves initially — all surfaces. Any later rating entry
goes through the Part 2 gate protocol like everything else.

---

## Part 5 — Schema-correlation + cross-sport brain-dump (2026-07-22, pre-limit)

Unfiltered but schema-grounded. Same dedupe rule as Part 4 (check adjacent
helpers first — flagged where overlap is likely). All surfaces-first.

### Schema fields × fields nobody has crossed yet
- **5a. Timeout effectiveness.** `game_timeouts` exists but is only PBP
  decoration. Walk: net points in the 2-3 possessions after OWN timeout vs
  the 3 before — "do your timeouts stop the bleeding?" Team + situation
  (mid-run vs routine). Killer verdict line for the runs card.
- **5b. Height differential × outcomes.** `players.height/wingspan` ×
  `guarded_by`: make% vs shooter-minus-defender height delta ("mouse in
  the house" quantified); rebound winners by height gap (does length
  actually win HS girls' boards? myth-buster). Also **death-lineup
  detector**: lineup net × avg unit height — small-ball vs size, per team.
- **5c. Crew × style interaction.** `ref_tendencies` crew whistle-rates ×
  team style (drive-heavy FTR, press defense): "this Friday's crew calls
  tight → your drives are worth +X FTA". Pre-game scout line; nobody
  cross-references officials with scheme.
- **5d. Halftime adjustment index.** Q3-vs-Q2 net swing per team, season
  aggregate — coaching-adjustment read from the `quarter` field alone.
  Quarter profiles generally (slow starters, 4th-quarter fade) — dedupe
  vs `situational.py`/`late_game.py` first.
- **5e. Chained possessions.** Event ordering within game →
  steal→transition conversion (points on the possession right after own
  steal — per-player "theft value"; dedupe vs `defenses.py`
  points-off-TO), OREB→putback vs kick-out-3 split, second-chance PPP by
  rebounder ("her board becomes points"). Extends Part 1 rebounding.
- **5f. Sub-shock / instant offense.** `game_event_lineup` sub sequences
  (same walk as 4g stints): net in first 2 possessions after a multi-player
  sub (does mass-subbing cost points? hockey line-change steal) +
  per-player first-stint scoring rate ("super-sub / instant offense" —
  bench award candidate).

### More cross-sport
- **5g. Four factors** (Dean Oliver, the canonical one). eFG% / TOV% /
  OREB% / FT-rate, team vs opp, + WHICH factor decides YOUR games
  (per-game factor differential vs result). Dedupe vs
  `adj_efficiency`/`team_analytics` — if absent it's the classic missing
  piece, cheap and famous.
- **5h. Pythagorean luck** (baseball). Expected wins from point diff vs
  actual — "you're 2 games lucky/unlucky" banner. Dedupe vs `predictor.py`.
- **5i. Hot hand / streakiness** (baseball hot streak). P(make | previous
  make) vs base rate per player, within-game shot sequences — the classic
  test run on their own kids. Fun page material, honest small-n caption.
- **5j. Hero-ball index / assist Gini** (soccer possession networks).
  Gini coefficient on team scoring + assist distribution: "system offense
  vs hero ball" one-number read; pairs with 4c connection matrix and the
  networks.py graph. Also screen-partnership pairs (`shot_created_by` ×
  shooter) as the off-ball edge set.
- **5k. Hustle composite** ("hard-hat award"). Charges + steal-forced TOs +
  off-ball DREB crash + kills participation (4e) + own-miss recovery →
  weekly award via `awards.py`. Pure surfaces, founder's do-it-all theme.

### Meta — the one that scales
- **5l. League winning-formula miner.** Small engine: correlate every team
  P-dict stat with game outcomes WITHIN a league/gender pool → ranked
  "what actually wins games in THIS league" (e.g. "your league is won on
  the glass, not the arc"). Auto-updates as data grows; ridge-regularized
  per ML_LAYER_ROADMAP small-data rules; verdict-first card on Insights.
  Turns the whole stat table into one coach sentence — the "massive data
  table, fun uses" ask answered directly.

- **5m. Style-shift fingerprint** ("when X comes in they play different").
  Per player: team tendency VECTOR on-floor vs off-floor — pace (poss/min),
  3PR, rim/zone mix, assisted-FG%, hero-ball Gini, play-type mix, defense
  scheme mix, steal-forced rate, FTR both ways, OREB crash. Delta on−off,
  min-poss + EB shrink. Scalar on top: style-shift MAGNITUDE (vector
  distance) → "who changes team identity most" roster ranking (the
  press-igniter / pace-pusher, not necessarily the best player). Verdict:
  "With #12: +6 pace, +14% rim rate, more PnR, presses more." Timing axis
  (entry minute, stint onset) rides on 4g/5f machinery. HONESTY: raw
  on/off style is teammate-confounded (RAPM adjusts net points only, not
  style) — ship as captioned deltas, never causal claims. Dedupe:
  `selfscout.py` (team drift), `spacing.py` (gravity),
  `rotation_schedule.py` (entry timing) before build. Zero new capture.

- **5n. Defensive mirror — WHERE a defender gets attacked.** Founder ask:
  "can't guard an iso, doesn't close out on spot-ups — a defensive twin for
  every offensive insight?" Answer: YES but collapsed, not mirrored.
  MEASURED 2026-07-22 (live DB): 2,891 guarded shots (2,676 w/ play_type,
  100% w/ zone), but 260 defenders at MEDIAN 5 guarded shots — only 40 have
  ≥20, 12 have ≥50; per-defender × play_type cells with n≥10 = **39
  league-wide**. Full 11-type × per-player mirror = the "Design A death"
  the taxonomy lock forbids (couples two taps, shatters a thin sample).
  DESIGN:
  * **Split share from rate.** SHARE (what fraction of a defender's faced
    shots are iso / closeout / post) is a low-variance TENDENCY — readable
    ~n≥20. RATE (FG% allowed in that bucket) needs ~n≥50 + EB shrink to
    the pool. Ship share widely, rate gated. Target share is itself the
    insight: offenses hunt weak defenders, so "she faces 36 isos, most on
    the team" is a scouting fact before any percentage.
  * **Two buckets, not eleven.** ON-BALL CREATION (iso/pnr/post/dho ≈1,030
    guarded shots) vs OFF-BALL CLOSEOUT (spot/offscreen/cut/transition
    ≈1,190). Both fat enough to split. Zone already collapses via existing
    RimProt / PerimD (rim vs arc) — reuse, don't duplicate.
  * **Team level is the honest home for the fine grain.** Per-team ×
    play_type has real n (iso 633, spot 577, transition 400 league-wide) →
    "what gets run AT us and what scores" as the defensive twin of
    self-scout. Dedupe FIRST vs `exploit.py` (exploit matrix),
    `defenses.py`, `scheme_situational.py`, `matchups.py` — likely
    partially built.
  * Surfaces: player card defense block gets a faced-mix line + gated
    allowed-FG% by bucket; Charts → Defense gets the team attacked-at grid.
    Verdict-first: "Hunted in iso (36 faced, most on team); holds up on
    closeouts."
  * NOT a rating leaf initially. DSHOT%/RimProt/PerimD already carry
    defense in ratings; bucket rates could be gate-swept later ONLY if
    coverage grows (re-measure the n≥50 defender count first).

### Part 5 ranking (founder taste filter)
1. 5l winning-formula miner — highest wow-per-line, uses everything.
2. 5a timeouts — table already there, zero capture, coach-daily question.
3. 5g four factors (if truly absent) + 5h pythag — famous, cheap, honest.
4. 5e chained possessions — extends already-approved rebounding work.
5. 5n defensive mirror (share half) + 5b height × outcomes — myth-buster
   fun, physical data finally earns use.
6. 5f sub-shock + 5j hero-ball + 5k hustle award — depth.
7. 5c crew × style — needs officials data maturity; 5i hot hand — fun page.

---

## Part 6 — WHERE new insights live (load-time budget)

Founder constraint (2026-07-22): Parts 4-5 add a lot of engines; the box is
1 vCPU / 2 GB, CPU-bound, and reruns serialize (see [[droplet-capacity]]).
Placement is now a design decision, not an afterthought.

### The rule
**Default home for a new insight = a Charts subtab**, because Charts already
gates every view behind `if _tdview == "X":` — only the OPEN view's engines
run (verified code read 2026-07-21, batch doc #6 Tier B). An insight parked
there costs zero until a coach clicks it.

**Eager surfaces are the scarce resource** — anything that renders on page
open (Insights cards, player card blocks, dashboard headers). Adding an
engine there taxes EVERY coach on EVERY open, warm or cold.

Promotion test — an insight earns an eager slot only if ALL hold:
1. it answers a question a coach has BEFORE they know to look for it
   (verdict-first, e.g. "cold finishing is hiding good movement");
2. its engine is cheap or shares a fetch already on the eager path;
3. it survived as a Charts subtab first and got used.

Otherwise: Charts subtab, one cached fetch feeding every panel in the view
(the #8c pattern — one fetch drove both the xA scatter and Corsi bars).

### Applying it to Parts 4-5
- **Charts subtabs (default):** 4a trios/quads + finisher finder, 4c
  connection matrix, 4g stints, 4h shot diet, 5b height, 5e chains, 5f
  sub-shock, 5i hot hand, 5j Gini, 5m style-shift, 5n defensive mirror.
- **Eager candidates (earn it, one at a time):** 5l winning-formula miner
  (one sentence, top of Insights — the whole point is you didn't ask),
  5a timeouts (cheap, rides the runs card already rendering).
- **Awards/digest path, no page cost:** 5k hustle composite via
  `awards.py` (weekly job, not a render).

### Load-time follow-ups (own investigation, needs measurement)
- Per-view render timing instrumented before/after each batch — the 5a/5b
  capacity monitor already plans a "last render time" read; extend it
  per-view so a heavy new subtab is visible immediately.
- `st.fragment` for the heaviest Charts subtabs so a control change
  reruns ONE panel, not the view (previously judged low-value at the tab
  gate level; per-panel is the remaining win).
- Cache pre-warmer (batch doc #6 Tier B item 4) matters more as engine
  count grows — cold Friday cost scales with how many engines a view owns.
- Re-check: are any Parts 4-5 engines full-season event walks that could
  share ONE cached event fetch per view instead of each re-fetching?
  Bundle at build time; retrofitting is harder.

---

## Part 7 — Roster rollover (captured 2026-07-24; raised end of 07-22 session)

Founder ask, paraphrased: "at season end, auto-roll everyone forward and let
coaches delete who left." VERDICT AFTER CODE READ: **that is the existing
design.** `helpers/seasons.py` already implements it. What is missing is
deployment and one semantic gap — not the feature.

### Already built (do not rebuild)
- `rollover_plan()` (`seasons.py:251`) splits the CURRENT roster by grad_year
  vs the outgoing season's graduating year. A player auto-graduates ONLY when
  grad_year is set AND <= that year; **NULL grad_year returns** — the safe
  default, and the coach can still uncheck in the UI.
- `execute_rollover()` (`seasons.py:274`) stamps + archives the outgoing
  season, snapshots `team_class_history`, then re-creates each carried player
  as a fresh Current row `identity_id`-linked to the same person, so returners
  come back pre-linked and seniors simply aren't carried.
- `auto_advance_if_due()` (`seasons.py:324`) is calendar-driven (Oct 1 cutoff
  via `season_for_date`), **forward-only** and idempotent: an early manual roll
  is a no-op, running twice a day does nothing, and Jan-Sep dates can never
  un-roll a season in progress. It runs the SAME `execute_rollover` with the
  auto graduate/return split.
- `default_grad_year()` (`seasons.py:232`) gives every newly-added player a
  grad year (assume freshman: end year + 3) so nobody lingers on a roster for
  a decade with NULL.

### Gap (a) — the timer is not installed on the VPS  [BLOCKING in prod]
`app5-season-rollover.timer` is NOT installed, so `auto_advance_if_due()`
never fires in production. Needs founder sudo. Verify with:
`ssh app5@107.170.27.154 "systemctl list-timers | grep rollover"`.
Until then the New Season button is the only path, and the Oct 1 cutoff
silently does nothing. Cross-ref [[settings-and-deploy-facts]].

### Gap (b) — no TRANSFER path
A transfer out is currently indistinguishable from a delete, and a transfer IN
is indistinguishable from a new player. The founder has exactly one transfer so
far, so this is real but not urgent. Scope later; the identity layer
(`helpers/identity.py`) is the natural home since it already models
"same person, different season row".

### Gap (c) — delete ergonomics: VERIFIED GOOD (2026-07-24)
This was flagged UNVERIFIED in the handoff. Read the UI: no work needed.
`pages/1_Input_Hub.py:622` ships a "🗑️ Remove a player" expander →
selectbox of `#num name` → caption explaining the archive rule → gated
confirm button → `database/db.py:delete_or_archive_player`. The comment at
`1_Input_Hub.py:620` says this button exists precisely because the
`data_editor` row-delete needs a physical Delete key, "absent on tablets".
`delete_or_archive_player` (`db.py:806`) calls `player_has_history` first,
which checks all 8 `game_events` player columns plus `game_event_lineup`,
`manual_player_box` and `game_lineup_players` — the two CASCADE tables being
the silent-data-loss risks. History → `archived=1` (stats kept); clean row →
hard delete. `roster_clause` (`seasons.py:210`) then hides the archived row
from the Current roster, and its docstring already names this case:
"manually-archived quit-mid-season players stay hidden".
**Conclusion: "auto-roll everyone, coaches delete" works ergonomically today.**

### Gap (d) — NEW, found 2026-07-24: archive does not stamp the season
`db.py:813` archives with `UPDATE players SET archived=1 WHERE id=?` — it does
NOT set `season`. The rollover path (`seasons.py:299`) sets BOTH
(`archived=1, season=<outgoing_label>`). So a player removed MID-season keeps
`season='Current'` while carrying `archived=1`.

Consequence: the archived-roster browser at `pages/1_Input_Hub.py:1095` runs
`SELECT DISTINCT season FROM players WHERE archived=1 ORDER BY season`, so a
literal **"Current"** entry appears in the past-seasons dropdown. Harmless to
ratings (both `roster_clause` branches correctly exclude the row: the Current
branch on `archived=0`, a past branch on the label), purely a UI wart.

Fix is one line — stamp `season=SEAS.active_label()` alongside `archived=1` —
but it changes delete semantics for every coach, so it is NOT part of the
2026-07-24 overnight run. Logged to the maintenance batch for a supervised
deploy instead.

### Stale warning, corrected
The handoff warns about roster doubling at `pages/2_Game_Tracker.py:823`.
**That fix has already landed** — the query reads
`... AND {_roster_c} ORDER BY team_id, number` with `(t1id, t2id, *_roster_p)`.
The remaining unscoped read is `2_Game_Tracker.py:547` (`proster`), which the
batch doc correctly rates log-only: it builds an id→name/team dict, so
duplicate ids collapse harmlessly. The general rule still stands — any NEW
roster query must use `SEAS.roster_clause`.

---

## Part 8 — Revised build order (2026-07-24, supersedes the Part 3 list)

Reordered after reading the code the old order assumed. Principle:
**group by shared substrate, and let each gate sit immediately after the
plumbing it judges** — the old order split one plumbing job across steps 1
and 2, and paired a free leaf with an expensive one.

### Measured facts that forced the reorder
1. **Part 1 §2 is ~70% already built.** `pages/7_Players.py:1174-1235` already
   surfaces `def_secure_team_pct` + Stabilized + on-ball DREB% + own-miss
   recovery behind the ≥5-contest gate, and `pages/6_Team_Dashboard.py:765`
   (`_reb_enrich_team`) already rolls box-out payoff up to the team. Remaining
   §2 scope = the BADGE + the player-CARD verdict line only.
2. **The badge and the `_DREB` leaf share one prerequisite.** `badges.py`
   ranks off `player_stat_table` (module docstring: "Pass it the dict returned
   by player_stat_table"), and leaves read the same P. So "plumb
   `player_rebounding` → P" is ONE commit unlocking badge + verdict + gate.
3. **Every sweep was blocked on a 5-line commit.** `tools/backtest.py`
   REGISTRY held only `_OVERALL_PARTS` and `_PLAYMAKING`; `_SHOOTING`,
   `_DREB`, `_DEFENSE_PARTS` and the rest were absent, so `BT.override`
   would KeyError. Register them all once, first.
4. **FT% is genuinely zero-plumbing.** `"FT%"` is already a P key
   (`player_ratings.py:1411`), so the FT% gate needs nothing but fact 3.
5. **DWPA/WPA are the expensive outliers, not "free alongside".** There is no
   WPA key anywhere in `player_ratings`. Plumbing them would put a
   `season_wpa` walk inside `player_stat_table` — the eager engine — taxing
   every coach on every page open, which Part 6 forbids. ScrAST/G by contrast
   is already in P (`player_ratings.py:1380`). **Decision: DWPA/WPA dropped
   from this run entirely** (Part 2 already ranks WPA "likely rejected"; DWPA
   overlaps DRtg + RAPM impact). Revisit via a harness-only injection that
   never touches the eager path.
6. **The tier tag must be a SIDE-TABLE, not a 4th tuple element.** `group_z`
   unpacks `for stat, _w, lb in group` (`player_ratings.py:927`) and the
   `_*_PARTS` lists are 2-tuples — a 4th element breaks both shapes. A
   `stat → tier` dict costs nothing. It lands EARLY (not with Part 3) so any
   leaf adopted in this run ships tier-tagged rather than retro-tagged.
7. **Harness is cheap: 22s per lean-T2 variant.** All five candidate sweeps
   together are ~5 minutes of compute. Any plan that overlaps gate runs with
   build work to "save time" is optimizing the wrong resource — the cost is
   build + test. Order strictly sequentially for review clarity instead.
8. **Baseline for this run: lean-T2 rho 0.681 (n=48), 43 tracked games,**
   focus team `(1, 'F', 24)`. Up from 0.678 / 39 games at the #8d gate.
   `tools/backtest.py:57` hardcodes `SEASON = "2025-2026"`, so gates score the
   real pool regardless of the empty ACTIVE season
   (see [[season-rollover-active-is-empty]]).

### The order (11 commits)
1. **Spec** — this Part 7 + Part 8.
2. **Prep** — REGISTRY gains the unregistered leaf groups; `LEAF_TIER`
   side-table (T1 box / T2 possession / T3 tagged) + a test asserting every
   leaf in every group carries a tier, so no future leaf lands untagged.
   Zero behavior change.
3. **FT% gate** — `tools/gate_ft_shooting.py`, 0.3 / 0.5 / 0.75 into
   `_SHOOTING`. First because it needs nothing but commit 2, so it proves the
   registry → gate → verdict path end-to-end before any new code exists.
4. **Rebounding → P** — `player_rebounding` metrics into `player_stat_table`,
   tier T3, None below `MIN_ONBALL=5`, reusing the events fetch already there.
5. **Rebounding surfaces** — box-out payoff badge
   (`stat=def_secure_team_stab`, `gate=("onball_misses", 5)`) + player-card
   rebounding verdict line. Archetype FEATURES untouched.
6. **`_DREB` gate** — `tools/gate_reb_guarded.py`, 0.4 / 0.6.
7. **HAST chain-pairs** — stale-comment fix at `2_Game_Tracker.py:1241`,
   `hockey_from → assister → shooter` triples, PotHAST, coverage counter.
8. **xA2** — separate P keys, card + glossary, coverage-gated ≥3 games.
   `xA/G`'s computation never touched.
9. **HAST re-gate** — re-run on the deeper pool; expect INCONCLUSIVE at 0
   tagged. Record, do not adopt on a trivial tie.
10. **ScrAST gate** — baseline, +0.3, +0.4, +0.4 −SC/G, +0.4 −SCPass/G.
11. **Close out** — AppTest smoke, verdicts consolidated in
    `MAINTENANCE_BATCH_2026-07-22.md`.

### Stop line and policy (founder decisions, 2026-07-24)
- **Run stops after commit 11.** Part 3 tier architecture (chips,
  per-category evidence, per-cohort backtest) and Parts 4-5 fun are NOT built
  this run: per-category evidence reshapes shrink-to-50 for every coach even
  when its T4 gate passes, so it gets a supervised session.
- **On a REJECT: keep the gate tool, record rho + verdict, do not add the
  leaf, continue.** Rejections are results. No weight-shopping past the
  pre-registered band — that is what the gate exists to prevent.
- **Commits land on `main`, nothing pushed.** Review by `git log` before any
  deploy; today is Friday and the cadence is Wednesday
  (see [[maintenance-batch-doc]], [[deploy-flow]]).
