# War Room Revisit — scope & map (queue-v3 #8)

> Scoped 2026-07-02. Same delivery pattern as UI_DENSITY_PLAN.md: phases that
> each ship alone. OOTP is the reference, not the copy — real numbers only.

## What the War Room is today (pages/9_War_Room.py, ~1,200 lines)

Page-level **Paid** gate; Solo (non-Co-op) viewers effectively get the Lineup
creator only; league-wide surfaces carry `_WR_LOCK`. Seven **eager `st.tabs`**:

| Tab | What it does | State |
|---|---|---|
| Matchup | predictor (spread/win% + margin distribution) + Game plan (exploit matrix: your sets × their leaks, scheme to play) | flagship, but verdict is buried under pickers and the game plan sits below the fold |
| Season sim | Monte Carlo expected wins / title odds | good (recent) |
| Bracket | probabilistic bracket tree, manual seeding, byes | good (recent) |
| Lineup | One-team / Any-team five builder + projected statline | good; missing the new value stats |
| Matchup planner | who-guards-whom defender assignments (DEF vs OFF edge, saved per opponent) | distinct from Matchup's game plan — keep, but the name confuses |
| Analyze | the folded Data Explorer (stat grid / scatter / correlations / shot maps) | fine |
| Glossary | reference | fine |

## What's actually weak

1. **Eager tabs**: `st.tabs` computes every body on every rerun — the exact
   pattern Rankings/TD were cured of (STATUS 62 lazy-load contract). Heavy sims
   are button-gated so it's not fatal, but Matchup's predictor + exploit scans
   run even when you're on Bracket.
2. **The Matchup tab doesn't read like a scout's page.** Pick two teams → a
   metric row. No tale of the tape, no identity, the game plan below the fold.
3. **New engines aren't wired in**: rest-differential fatigue edge (fatigue.py),
   crew outlook (ref_tendencies — only Officials shows it), Adj eFG, HoopWAR.

## The plan

### W-A — mechanics (small, pure port of a proven pattern)
`st.tabs` → `seg` + `if`-dispatch (the Rankings `_rkseg` pattern) so only the
chosen view computes. GOTCHAS baked in blood: render must sit AFTER the def
(STATUS 73); AppTest-every-view after the move; seg preseeding renders the
default silently — verify moved blocks by running their code directly.

### W-B — Matchup becomes the flagship (the meat)
- **Tale of the tape**: compact two-column team read (new
  `team_card.render_mini(ctx)` — banner line + 6 key rows per side: Power/rank,
  record/streak, MOV, Off/Def rating, Adj eFG both ways, pace, glance-style
  identity tag). Reuses the shared card family — no third source of truth.
- **Verdict first**: projected score · win% · spread band at the TOP, pickers
  compact above it, distribution + factor breakdown below.
- **Rest edge**: both teams' days-since-last-game at the matchup date (from the
  schedule) + the league rest-differential curve → one honest line ("A on 1 day
  rest, B on 3 — league edge for fresher side: +x.x"). Display-only; NOT folded
  into the spread until a season validates the curve (real-numbers rule).
- **Crew outlook**: when officials are assigned to the scheduled game,
  `ref_tendencies.crew_outlook` renders its whistle/pace read here too.
- Game plan (exploit matrix) keeps its slot right under the verdict.

### W-C — Lineup creator value pass (small)
- Projected statline gains **HoopWAR** and the floor-time context per pick.
- Roster pick rows show PHY + trajectory arrow (both already in the stat table).

### W-D — naming + wayfinding (tiny)
- "Matchup planner" → **"Defensive assignments"** (what it is); one-line
  cross-links between Matchup ↔ assignments ↔ Lineup so the prep flow reads
  as one path: project it → plan the calls → assign the matchups → pick the five.

### Deliberately NOT doing
- No sim-engine changes (season/bracket are fresh and tested).
- No new tabs. No Analyze rework (recent fold, founder-approved shape).
- Rest edge stays OUT of the predictor's math this season (descriptive only).

## Order + effort
W-A (1 short session, mechanical) → W-B (1-2 sessions, the visible win) →
W-C + W-D together (1 short session). Each phase: AppTest every view both
trees, live textContent probes for moved blocks, ship-per-phase.
