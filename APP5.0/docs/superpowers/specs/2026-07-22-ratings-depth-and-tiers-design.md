# Ratings depth & data-tier weighting — design (2026-07-22)

Status: DESIGN APPROVED IN SESSION (tracks A + coverage-gated xA2); NOT BUILT.
Usage-limit session — this doc is the handoff. Next session: writing-plans →
implement, gates last.

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
- Chain-pairs helper: `hockey_from → assister → shooter` triples on made
  shots; "who ignites whom" row (honest empty state until tagged).
- Coverage line in snapshot/admin: "HAST tagged: N — re-gate at ≥50".
- Re-gate: `tools/gate_xa_hast.py` unchanged, re-run at n ≥ 50; weights
  0.2/0.3 already defined. Adoption ONLY through the gate.
- Status: capture wired 2026-07-22 (founder); local DB shows 0 tagged.

### §4 Coverage-gated secondary xA — SEPARATE stat, never inside xA/G
- CONSTRAINT: `xA/G` is a gate-adopted rating leaf (0.75, #8d). Mutating its
  computation = silent unguarded rating change. Forbidden.
- New field `xA2` ("hockey xA"): λ = 0.5 × the shot's expected-make value,
  credited to `hockey_from_id`. Separate P keys `xA2` / `xA2_pts`; surfaced
  beside xA (player card + glossary).
- Honesty: HAST captured only on MADE shots → xA2 is make-conditioned (a
  floor), unlike xA. Caption states it.
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

### Part 5 ranking (founder taste filter)
1. 5l winning-formula miner — highest wow-per-line, uses everything.
2. 5a timeouts — table already there, zero capture, coach-daily question.
3. 5g four factors (if truly absent) + 5h pythag — famous, cheap, honest.
4. 5e chained possessions — extends already-approved rebounding work.
5. 5b height × outcomes — myth-buster fun, physical data finally earns use.
6. 5f sub-shock + 5j hero-ball + 5k hustle award — depth.
7. 5c crew × style — needs officials data maturity; 5i hot hand — fun page.
