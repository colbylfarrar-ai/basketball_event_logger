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
