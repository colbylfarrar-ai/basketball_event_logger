# ML / Analytics Layer — Roadmap (beyond the current engine)

> Companion to `AUTO_TRACKER_FEASIBILITY.md`. Written 2026-06; grounded in the current
> `helpers/` engine, the event schema, and the data-scale reality (tens of tracked games this
> season). Built from a multi-agent ideation pass (6 data lenses) that was de-duped against every
> existing surface and adversarially culled for over-promise + small-sample noise.

## The honest framing (read this first)

Two things are true at once:

1. **It is NOT "basically just the War Room."** War Room is narrow — pre-game Monte-Carlo simulation
   + a league-generic lineup builder. Almost nothing below touches it.
2. **~60% of the value is sharper *use* of the engine you already have; ~40% is genuinely new
   analytical ground.** At tens of games, the wins are small-data-safe models (ridge, empirical-
   Bayes shrinkage, k-means, deterministic formulas, a thin regularized GBM) + a language layer —
   **not deep learning.** Neural nets / sequence models / a fine-tuned LLM are ruled out by volume
   (they need 1e4–1e6+ examples); see `AUTO_TRACKER_FEASIBILITY.md`'s "don't wait for an LLM" note.

Four areas the engine has **never** entered (verified absent in `helpers/`):

- **Live in-game decision tooling** — leverage, run alerts, late-game foul/clock, comeback math.
  Zero exists today. Highest-leverage cluster: it's deterministic (no data-volume risk), reuses
  `win_probability` / `wpa` / `gameflow`, and opens a whole **courtside product mode** you don't have.
- **Cross-team prescriptive bridges** — your offense × *their* defense exploit matrix, defender
  assignment, opponent-specific lineup pick. Your two single-team engines literally never meet.
- **Within-season trend + significance** — there is no `polyfit`/`linregress`/slope anywhere in
  `helpers/`; only a cosmetic 3-game rolling average.
- **A natural-language shell** over the engine (local LLM, tool-calling — never trained on the data).

Everything spatial (continuous shot-quality, SMOE, range curves) and most development ideas are
honest **upgrades** of metrics you already compute — high value, but precision/presentation, not new
surfaces.

---

## Tier 1 — build now (data-safe, high value, low effort)

Each is deterministic or EB-shrunk (no data-volume risk), reuses a verified existing helper, and
answers a question coaches actually ask. *(Ordering reflects the adversarial re-check: Box-prior
RAPM promoted up; synergy-pair score demoted to Tier 2; entropy/trend treated as thinner than first
billed.)*

| # | Capability | What | New? | Model |
|---|-----------|------|------|-------|
| 1 | **Courtside strip: Live Leverage + Run alert** | Live Leverage Index beside the WP strip (`li_at` math from `wpa.py`) + "opponent on a run, WP dropped — timeout?" banner (`gameflow.scoring_runs`, live). | NEW live surface | deterministic |
| 2 | **Box-prior RAPM** | RAPM shrinks toward each player's box-impact instead of toward zero. Stops the Impact Lab calling stars league-average on a 15-game book. | EXTENDS `rapm.py` | ridge, informed prior |
| 3 | **Late-game decision card + comeback math** | Final ~3 min: win-prob of foul-vs-guard / foul-up-3 / milk-vs-attack + comeback gauge (pts needed, possessions left, required PPP). Ships **league-rate-first**. | NEW | small Monte-Carlo + arithmetic |
| 4 | **Tagging-coverage panel** | "N tagged / % complete" for `play_type`, `defense`, `guarded_by`. The honesty keystone — gates trust in half of Tier 2. | NEW | none |
| 5 | **Self-scout predictability (entropy)** | Shannon-entropy "how scoutable are we" score + over-used-and-inefficient / under-used-but-efficient sets vs league. | EXTENDS scout *(thin — mostly the one new number)* | deterministic |

⚠️ **Main correctness risk:** the courtside items read a clean live `(elapsed, margin)` event walk —
must survive edits/undo, OT, and FT sequences in the Game Tracker.

## Tier 2 — build later (meatier, clearly worth it)

- **Exploit Matrix + opponent-specific lineup/defender recommender** — your set-call PPP × a SPECIFIC
  opponent's PPP-allowed-by-scheme → what to call, who to start, who guards their scorer. *Most new
  ground after the in-game lens.* (`defenses.cross_play_defense` is single-team today; nothing crosses
  the two engines.)
- **Continuous shot-quality (xPP-Q) + SMOE + per-player range curves** — ridge-logistic make-prob on
  real (x,y)+angle+contested, replacing radial distance×value. **League-pooled only — never per-team.**
- **Opponent shot-concession heatmap + our shot-selection-efficiency map** — kernel-smoothed
  where-to-attack / where-we-leak. Rides on xPP-Q.
- **Stagger / minutes optimizer + foul-trouble simulator** — star floor-time overlap, foul-out
  projection, sit-vs-play net cost (`gameflow.rotation` reports who-played-when only today).
- **Coach Chat + auto game-prep brief** (LLM shell, L effort) — plain-English Q&A routed to existing
  helpers + a one-tap brief auto-built for the next scheduled opponent.
- **Synergy pair score** *(demoted from Tier 1)* — pair residual-net-vs-expected; needs shrinkage,
  thin at tens of games.
- **Skill-trend detector** — Theil-Sen slope + significance over the within-season game log. Honest,
  but on ~10–20-game logs will often read "no real change" until volume grows.
- **Possession-value ledger** — where our points/100 come from vs leak (TOV rate, OREB 2nd-chance,
  shot quality), one unified chain.
- **Referee / crew tendency profile** — `official_id` is already on fouls; per-crew foul-rate / pace
  / home-lean = a free pre-game edge.

## Tier 3 — only if data volume / seasons grow

- **Cross-season player development** — **BLOCKED**: every season a player gets a fresh `player_id`
  (no carryover column on any `INSERT INTO players`). Needs a `players.identity_id` (or a `person`
  table) + a New-Season match UI before it is even possible.
- **Clock/score-state stratified lineup + tendency splits** — crunch-time five, what they run when
  trailing. Per-bucket samples too thin now.
- **Spacing / floor-balance index** from lineup (x,y) shot dispersion.
- **Comparable-trajectory finder** ("developing like") — depends on the trend detector existing first.

## Cut (already shipped or pure cosmetics)

Role-fit gap, practice-priority board, rest-of-season per-stat projection, bench-swap finder
(`team_analytics.lineup_prediction` already does it), handedness floor-side split (fold into spatial),
dead-ball/inbound board, 2-for-1 manager (fold into the courtside strip), and the four narration
features (rating tooltips / scout prose / recap / weekly digest — all collapse into the one Coach-Chat
LLM-shell investment).

## Prerequisites the good ideas depend on

- **Player identity carryover** (schema) → unlocks all longitudinal/development work.
- **Persisted per-event running-margin + possession index** → unlocks situational/crunch-time splits
  without re-deriving on the fly.
- **League-pooled shot minimums + shrinkage routing** for every sparse bucket (`shrinkage.py` exists —
  just route every per-context read through it with visible CIs).
- **Local-LLM runtime + a read-only / season-scoped / LIMIT-capped SELECT guard** for Coach Chat
  (can't live on the ~$5/1GB droplet; run a small model on a separate box, or a cloud API for the
  language layer only on de-identified inputs).

---

## Build status — Tier 1 SHIPPED ✅

- **Engine (Streamlit-free, mirrors the engine/display split):**
  - `helpers/courtside.py` — live leverage, run alert, late-game decision, comeback gauge.
  - `helpers/selfscout.py` — predictability (entropy) index + over/under-use flags.
  - `helpers/coverage.py` — tagging-coverage panel data.
  - `helpers/rapm.py` — extended with an optional box-impact prior (`prior=` + `box_prior_from_ratings`).
  - Tests: `tracker/test_tier1_engine.py` (15 pass).
- **UI wired:**
  - Courtside strip + late-game card → `pages/2_Game_Tracker.py` (live command center, reuses the
    existing 480/240 win-prob clock; guarded, live games only).
  - Box-prior RAPM toggle → `pages/6_Team_Dashboard.py` Impact Lab (`_rapm(g, box_prior=…)`).
  - Self-scout predictability → `helpers/dashboard/scout_tab.py` (Self-scout framing).
  - Tagging-coverage strip → `pages/0_Analytics_Hub.py` (league-wide, Co-op-gated).
## Tier 2 — in progress

- **Exploit Matrix + defensive plan (cross-team bridge) — SHIPPED ✅:** `helpers/exploit.py`
  (`offensive_exploits` / `defensive_plan` / `game_plan`), tests `tracker/test_exploit.py` (5 pass),
  wired into the War Room **Matchup** tab (`pages/9_War_Room.py`, `_game_plan`, co-op-gated). A=you,
  B=opponent; your set-call PPP × their PPP-allowed on the same set, plus the scheme to play on D.
  Tag-driven — lights up as `play_type` / `defense` get tagged. Defender-level assignment deferred
  (needs denser per-player `guarded_by`).
- **xPP-Q continuous shot-quality + SMOE — SHIPPED ✅:** `helpers/shotquality.py` — a pure-numpy
  ridge-logistic make-prob on (x,y)→[dist, dist², is_three, contested, |angle|], league-pooled
  (`fit_league_model`, gated at MIN_FIT=150 shots), with `make_prob` / `expected_points` and per-player
  `player_smoe` (points-over-expected, shrunk toward 0 by volume). Tests `tracker/test_shotquality.py`
  (5 pass). Wired into the Team Dashboard Impact Lab (`_shot_quality`, SMOE leaderboard). No sklearn
  dependency (own IRLS solver) → no silent graceful-degradation.
- **Opponent shot-concession + shot-selection maps — SHIPPED ✅:** `helpers/concession.py` —
  per-zone (not a kernel surface; zones are the stable unit at this scale) over-expected via xPP-Q.
  `defense_concession` (where a defense gives up the best looks — attack-here zones) + `shot_selection`
  (self-scout: over-used-and-underperforming vs efficient-but-under-used zones). Tests
  `tracker/test_concession.py` (4 pass). Wired into the scout tab: concession on the opponent view,
  shot-selection on self-scout (cached `_xpp_model`).
- **Stagger / minutes optimizer + foul-trouble simulator — SHIPPED ✅:** `helpers/rotation_plan.py` —
  `star_coverage` (uncovered floor-time + the net bleed when no key player is on → stagger their rest),
  `foul_prone` (season PF/32 flags), `foul_out_projection` (live: minutes-to-foul-out + risk tier).
  Tests `tracker/test_rotation_plan.py` (8 pass). Wired: live foul-watch in the Game Tracker box,
  stagger + foul-prone in the Team Dashboard Impact Lab.
- **Possession-value ledger — SHIPPED ✅:** `helpers/possession_value.py` — `possession_ledger`
  walks every possession to its terminal outcome (scored / missed→own-board / missed→lost / turnover)
  → points/100 sources (made 2s, 3s, FTs) + outcome mix + eFG/TOV/OREB, both offense and allowed.
  Tests `tracker/test_possession_value.py` (4 pass). Wired into the Team Dashboard Impact Lab.
- **Referee/crew tendency profile — SHIPPED ✅ (mostly pre-existing):** the per-ref profile already
  lived in the Officials Lab (FP100 whistle tightness, home/away lean, quarter-timing fingerprint,
  PPP/pace env, vs-league deltas, archetype quadrant). The one real gap — a **pre-game crew outlook** —
  is new: `helpers/ref_tendencies.py` `crew_outlook` synthesizes tonight's assigned refs into a
  league-relative whistle / lean / scoring expectation + a "value-the-ball vs attack-the-rim" read.
  Tests `tracker/test_ref_tendencies.py` (5 pass). Wired into the Officials Overview tab.

**Tier 2 engine items COMPLETE + DEPLOYED** (prod HEAD b6541d3, 2026-06-24).

## Tier 3 — in progress

- **LLM Coach-Chat: SCRAPPED** (founder decision 2026-06-24 — not pursuing the conversational layer).
- **Player-identity carryover (the plant-now piece) — IN PROGRESS:** a stable `players.identity_id` +
  a New-Season match UI so a returning player links across seasons (today the New Season rollover
  archives the old row and a returning player gets a fresh player_id, so year-over-year is impossible).
  Read-time resolution via `COALESCE(identity_id, id)` (unmatched = own identity, no mass backfill).
  Must ship BEFORE the next rollover so the linkage exists.
- **Season-2-gated (build after a 2nd tracked season links, ~2027):** cross-season development
  trajectory (YoY rating/stat deltas, EB-shrunk), returning-player projection, comparable-trajectory.
- **Volume-gated (defer until density grows):** clock/score-state lineup + tendency splits (needs a
  persisted per-event running-margin), spacing/floor-balance index. The Tier-1 late-game card stays
  league-rate v1 until opponent FT/3P rates are dense.
