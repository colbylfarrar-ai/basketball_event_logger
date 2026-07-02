# UI Density Plan — Team surfaces + Player profile (OOTP-grade)

> Queue-v3 items #6 and #7, planned 2026-07-02 (founder asleep; build supervised).
> Inspiration: the OOTP player page — three dense columns above the fold plus a
> bottom log, and you're never overwhelmed because every block has one job.
> Founder's read: "so much data shown at one time" without overwhelm, and
> basketball can show MORE (shot chart, ratings, confidences).

## What OOTP actually does (anatomy of the screenshot)

| OOTP block | What makes it work | HoopTracks equivalent |
|---|---|---|
| Left rail — Personal details | Pure identity, no numbers to interpret | name/#/team/class, height·wingspan·weight (+ NEW PHYSICAL rating), handedness, GP + confidence |
| Center — ratings bars, **Current / Potential** side by side, scout-accuracy chips | Two numbers per skill + how much to trust them | rating bars + CI bands (built), **potential = development.py projection** (built, unwired as a column), conf chips from `shrinkage.rating_confidence` |
| Right — Summary box + Percentile Rankings w/ year selector | The verdict first, evidence beside it | OVR + HoopWAR + WPA verdict box; 21-stat percentile rail (built); season selector = archive-UI (deferred) |
| Bottom — game log + career line | History never steals the fold | game log + across-seasons table (built) |
| Tab strip + sub-tabs | Depth exists but doesn't crowd | seg-based views (lazy-load contract, STATUS 48) |

The trick is **zoning, not shrinking**: identity left, skill center, verdict right,
history bottom. Basketball's edge over OOTP: the **shot chart is a spatial block
no baseball page has** — it earns fold space.

## #7 Player profile — deltas (mostly wiring, engine exists)

1. **Identity card** (new left rail block): height / wingspan / weight + PHYSICAL
   bar (now rated), handedness, availability, GP + scouted-confidence chip.
2. **Potential column**: development.py projected rating rendered beside each
   current rating bar (the OOTP current/potential dual bar). Label honestly:
   "trajectory", not scouting.
3. **Per-rating confidence chips** (scout-accuracy analog): CI half-width →
   High/Med/Low chip beside each bar (`rating_confidence` already computes it).
4. **Verdict box** top-right: OVERALL ± CI, HoopWAR, WPA, badge archetype +
   style cluster (now same vocabulary — show agreement/disagreement).
5. **Shot chart into the fold**: move the x/y shot map + defended-shot map into
   the right column under the percentile rail; hot zones fold into hover.
6. Compress signature tiles to one thin strip; quarter-scoring moves down beside
   the game log.

## #6 Team surfaces — TD Overview + Rankings Team deep dive

**Architecture first: extract `helpers/dashboard/team_card.py`** — the team
analog of player_card.py, ONE render used by BOTH the TD Overview and the
Rankings Team view (they currently duplicate metric rows that drift apart).

Zones (same grammar as the player page):

- **A — identity (left)**: Power/Rank/Record/MOV/PF-PA, vs Top-10/25, game-type
  chips, **team glance tags moved up from the Insights tab** (already built —
  `insights_team.team_glance`, the single most OOTP-like thing we have and it's
  buried), rest & fatigue chips.
- **B — skill (center)**: four factors as dual off/def percentile bars,
  adjusted efficiency line (AdjO · AdjD · AdjNet · AdjeFG · Adj-oeFG — all
  built), possession-value ledger mini (points sources vs leaks), style row
  (pace / 3PAr / paint share).
- **C — verdict (right)**: power-tier chip + title odds + expected wins,
  next-game projection with crew outlook, top-3 play-type identities (PPP ·
  TO% · percentile), shot-concession mini-court (where we leak).
- **Bottom**: who-carries-them hero cards + game-by-game trend (both exist).

Rankings **Team deep dive** then becomes: team_card.render(ctx) + the
league-context extras it alone has (rank neighborhoods, win network slice).

## Phasing (each phase ships alone)

- **A (quick wins, ~1 session)**: team_glance → Overview top; profile identity
  card w/ physical; HoopWAR/verdict box; confidence chips.
- **B**: potential column (development wiring + honest labeling).
- **C**: team_card.py extraction + TD Overview re-grid.
- **D**: Rankings Team view adopts team_card + deep-dive condense.
- **E (polish)**: shot chart into the fold, tile compression.

## Standing rules for the build

- Lazy-load contract: seg + if-dispatch, never eager st.tabs for heavy bodies
  (STATUS 48/62); any render of a page function must sit AFTER its def
  (STATUS 73). AppTest-every-view after each move; seg preseeding renders the
  default view silently — verify moved blocks by running their code directly.
- Free/paid gating per surface is already correct — moving a block must carry
  its existing guard with it ([[app5-gating-taxonomy]]).
- reports.py printables keep parity where a moved block was exported.
