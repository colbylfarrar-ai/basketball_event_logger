# Player Profile card — scrub (2026-09-09)

Benchmark: Team Dashboard **Insights** tab.
Scope: `helpers/dashboard/player_card.py` (2,065 ln, `render_card` is 1,591 of
them) plus its three mounts:

| Mount | Entry |
|---|---|
| Players → Player Profile | `pages/7_Players.py:1533` |
| Team Dashboard → Player Profile | `pages/6_Team_Dashboard.py:6562` |
| Quick-view modal (roster / leaders tables) | `player_card.quick_view` → `pages/7_Players.py:835`, `pages/6_Team_Dashboard.py:6584` |

One renderer, three surfaces — including a **modal dialog**. Everything below
lands on all three at once.

## Measured shape, today

- **26 `pl-hdr` sections**, 12 `st.plotly_chart`, 9 `st.dataframe`.
- **Zero controls inside the card** — no `st.selectbox`, `slider`, `toggle`,
  `seg`. Nothing is lazy, nothing is gated, nothing is scopeable.
- So every paid render does all 26 sections' work, every rerun, including
  inside the dialog. This is the exact problem the Insights recut solved with
  `_UI.seg` + `@st.fragment` (see `insights_tab.py:704`), and the card never got
  that pass.
- The verdict — Scouting report (`:1930`) and What the data says (`:2053`) — is
  **dead last**, after roughly twenty screens of tables.

---

## Part 1 — Consolidation (nothing lost, a third of the length gone)

### 1.1 The same number, printed three to five times

| Number | Where it renders | Action |
|---|---|---|
| **OVERALL** | banner 60px (`:540`), rating bar (`:698`), `ADV.player_panel` glass tile (`advanced_ratings.py:204`), League ranking metric (`:1776`) | Keep banner + bar. Drop ADV's tile and the ranking metric (the rank row already carries it). |
| **Impact / RAPM** | Impact tiles `RAPM · net pts/100` (`:922`), then `ADV.player_panel` `Impact (RAPM)` tile twenty lines later (`:944`) | **Same engine, two tiles, adjacent.** Drop ADV's. |
| **Confidence** | Overview header "scouted *label* (N games · ±CI)" (`:612`), ADV glass tile, Scoring-table caption "Sample confidence" (`:1129`), Projection caption (`:1822`) | One home: the Overview header. Others reference it, not restate it. |
| **Per-game line** (PPG/RPG/APG/SPG/BPG/TPG/FPG) | chip strip (`:605`), Overview col 1 "Per game" (`:676`), Rebounding/Playmaking table (`:1135`), percentile rail (`:854`) | Chip strip is the banner's job; Overview col 1 is the fold's. **Cut the chip strip** — it is the weakest of the four. |
| **Paint FG% · FG% · 3P%** | shot-map caption (`:843`), Shot detail caption (`:1005`), Scoring table (`:1101`), percentile rail | Keep the fold caption + the table. Drop the Shot-detail repeat. |
| **SMOE** | Signature metrics tile (`:949`), Scoring table `Expected FG% (SMOE)` (`:1120`) | Tile wins (it is the "invented metric" spotlight); drop the table's parenthetical. |
| **Self-creation** | Signature pill `Self-cr %` (`:760`), Signature metrics tile `SELF-CR%` | One. Pill, since it sits in the fold. |
| **Dominant-hand share** | Signature metrics tile `DOM-SIDE%`, hand-split metric "Dominant share" (`:985`) | Drop the tile; the hand section owns it. |
| **USG% · +/- · EFF · FIC · VPS** | impact tiles row of 7 (`:882`) **and** the percentile rail directly above it | The rail gives each a league percentile; the tile gives a bare number. **Delete the tile row**, keep MIN/G and PRF (the only two not in the rail) as rail entries. |
| **Career / season highs** | Overview col 1 "Career highs" (`:692`), `TRD.season_highs` "Season highs" (`:1682`), free-tier "Career highs & milestones" (`:1559`) | Two real concepts (career best vs this season's best) presented as three blocks. Merge to **one table, two columns: season / career.** |
| **5-rating radar** (`:1063`) | The same five ratings as the Overview bars, which additionally carry a CI band and the ↗↘ trajectory chip | **Delete the radar.** Its only extra is the pool-average ring; add a 50-mark to the bars instead. |
| **Recent form** | trajectory chips on the rating bars (last-5 vs season, `:700`), Form (last 5) RTG metric (`:1654`), "Recent form — last 5 vs season" metrics (`:1693`) | Three last-5-vs-season reads in three styles. One block. |
| **PTS by game** | Game-log trend chart (`:1617`), Rolling form chart (`:1668`), Per-32 bars (`:1854`) | The first two are the same series with a different smoother. **One chart, a `seg` for raw / 3-game.** |

### 1.2 Three competing archetype labels on one card

1. `Cluster <name>` chip (`:613`) — `archetypes.cluster_players`, data-driven.
2. `Badges <a> / Style <b> · ✓ agree / ↔ differ` (`:645`) — `badges.badge_archetype` vs the same cluster.
3. **Scouting role** (`:1930-1975`) — a hand-written 11-branch `if/elif` ladder
   on percentile cutoffs, which knows nothing about either of the above and can
   label a "Glass Cleaner" whose cluster says *Perimeter creator*.

(3) is the weakest engine on the card and the most prominent-looking. Either
kill it and let the cluster + badge-archetype agreement line carry the role, or
demote it to the one case it is actually good at — **naming the role when the
cluster is thin** — and say so on screen.

### 1.3 Code-level

- The 21-row percentile list is **copy-pasted verbatim** at `:854` (paid) and
  `:1742` (free, filtered by `PR.EVENT_DERIVED_STATS`). One module constant,
  one filter.
- `render_card` is a 1,591-line function with no internal seams. Splitting it on
  the section boundaries proposed in Part 3 is a precondition for making the
  sections lazy at all.

---

## Part 2 — What is missing

### 2.1 The card truncates a 39-generator feed to three lines

`helpers/insights.py` holds **39 `_g_*` player generators** (shot-making,
selection, force-left/right, space dependence, Q4, consistency, on-ball
defense, signature play type, situational, turnover signature, contact rate,
clutch FT, PnR role, gravity, assignment difficulty, impact-vs-production, rim
/ perimeter defense, rebounding identity, self-creation, creation for others,
disruption, rim finishing, usage, garbage time, stints, form, on/off off, on/off
def, defensive load …).

The card calls `build_feed(..., top=3)` (`:433`) and renders at most three lines
in a grey box at the very bottom. The Insights tab runs the same feed through
`insights_severity.rank()` and shows **every** line, ordered, with section +
evidence destination — the rank-never-hide law.

**This is the single biggest gap.** The card should carry the player's full
ranked feed, verdict-card shaped, in the sections the lines belong to — and a
player-level **"Monday"**: the two or three lines that convert to a drill.

### 2.2 Engines already computed, never reaching the card

| Read | Engine | Where it lives today |
|---|---|---|
| **Who she guarded, shot by shot** | `matchups.matchup_table` (`by_shooter`) | Lab → Matchups, behind its own defender picker |
| **Assignment difficulty** (did she draw the other team's best?) | `matchups.matchup_difficulty` | same |
| **Who guarded *her*** | the same table, inverted — free | nowhere |
| **Plays like…** (cosine similarity) | `archetypes.similar_players` | `pages/7_Players.py:1730`, own picker |
| **Turnover signature** (which giveaway kind) | `turnovers.player_turnover_types` | Insights feed only |
| **Foul trouble the coach can act on** — carried load, early fouls, foul clock, crew rate | `foul_trouble.carried_load` / `early_fouls` / `foul_clock` / `crew_foul_rate` | Insights `insights_deep.py:563`, Team Dashboard `:1150` |
| **Bench cost of her fouls** | `foul_trouble.bench_cost` | team-level only |
| **On/off net rating** (pts per 100, adjusted) | `lineups.player_on_off` via `insights._g_onoff` | feed only — the card's On/Off section has rebounding + AST/TOV and **no scoring** |
| **Best / worst partners** | `networks.chemistry_network`, `group_synergy` | Insights §4 (opt-in button — ~16.5 s, so gate it here too) |
| **Individual ORtg / DRtg** | `stats.individual_offensive_rating` / `_defensive_` | `team_analytics.py:1556` |
| **Touches / tag dependence** | `involvement.player_involvement` | Insights, Team Dashboard |
| **Situational PPP edges**, margin scoring | `situational.player_situational_edges`, `player_margin_scoring` | feed only |
| **Connection verdict** (prewritten coach-speak for the feed graph) | `passing_chains.connection_verdict` | `pages/6_Team_Dashboard.py:4468` |
| **Program records / placement** | `hall_of_fame`, `awards.weekly_awards` | own pages |

Cheap wins in that list: the matchup reads (one cached table, already built for
Lab), turnover types, ORtg/DRtg, on/off net. Expensive: chemistry — gate it.

### 2.3 Coach reads absent outright

- **No W/L or margin in the game log.** `home_score, away_score` are *selected*
  at `:1587` and never used. One-line fix, and it is the first column a coach
  looks for.
- **No opponent quality** on any game row — no rank chip, no "vs winning teams"
  split. `resume.opponent_ranks` exists at team level.
- **No game-window control.** Insights scopes every cached read through its deck
  controls; the card cannot answer "last five games only" at all.
- **No minutes / stint read.** MPG is a tile; there is no minutes-by-game line
  and no stint-length read, though `insights._g_stints` computes one.
- **No home/away split.**
- **No compare affordance** from the profile, though Compare is a sibling tab
  and `similar_players` already names who to compare to.
- **No evidence jumps.** Insights' `_jump_btn` pattern (to Charts / Lab sub-segs)
  does not exist on the card, so every "see the full table" is a manual hunt.

Deliberately **not** proposed: per-quarter shooting or ball-security splits.
Measured unrepeatable — only tempo repeats (SB .596). The existing
points-by-quarter bar is the right depth and stays.

---

## Part 3 — The reorder

The card is cut by **data category**; Insights is cut by **the question a coach
asks**, which is why it reads better. Proposal: keep the fold, then seven lazy
`_UI.seg` sections.

**The fold (always rendered, unchanged in spirit):**
banner → Overview grid (`per game + highs | ratings + signature | vs teammates
+ play types | shot map`) → percentile rail.
That grid is the best thing on the card. Do not touch it beyond the 1.1 cuts.

**Then — new, directly under the fold, before any table:**

> **§0 · Verdict.** Reconciled role (cluster + badge archetype), the
> severity-ranked feed's top lines, strengths / watch, and the Monday list.
> This is §2.1 and 1.2 cashed in. It is what the user's own Insights bar asks
> for and it is currently the last thing on the page.

**Then seven sections, one open at a time:**

| § | Question | Absorbs |
|---|---|---|
| 1 | **How does she score?** | Shot detail, hot zones, zone fallback, shot diet, SC composition, set-call profile + screen role, hand splits, points-by-quarter, points by source |
| 2 | **Who does she make better?** | Scoring/shooting table, feeds + xA, hockey chains, connection verdict, **turnover types** (new), involvement (new) |
| 3 | **Can she defend?** | Rim/perimeter splits, defended map, guarded/open, **who she guarded + assignment difficulty** (new), DSHOT%, board/box-out verdict |
| 4 | **Does the team win with her on?** | HoopWAR/RAPM/WPA tiles, on/off (rebounding + playmaking + **net, new**), **ORtg/DRtg** (new), per-32, **partners** (gated, new) |
| 5 | **What is her form?** | Game log (+ **W/L, margin**), one PTS chart with a raw/3-game seg, merged highs, streaks, fouls & FT + **foul trouble** (new) |
| 6 | **Where does she rank?** | Percentile detail, rank table, league bar, **plays like…** (new) |
| 7 | **Where is she going?** | Across seasons, rest of season, next season, stabilized skill rates — **the four projection blocks that are currently scattered across 300 lines with six unrelated sections between them** |

Ordering principle, and the reason this beats the current sequence: **verdict
first, then the four things a coach changes practice over (score / pass /
defend / win), then history, then the league, then the future.** Today the page
opens with numbers and ends with meaning.

Laziness is the other half of the win: one open section instead of 26 eager
ones, which matters most in the quick-view modal.

---

## Part 4 — Bugs found in the scrub

1. **Game-log opponent is wrong for a transferred player on an archive season.**
   `:1601` resolves the opponent against `P["team_id"]`, which is the *current*
   roster row. The On/Off section 270 lines later fixes exactly this by
   resolving the lineup team (`S.player_lineup_team`, `:1887`) and says why in a
   comment. The game log needs the same resolution — today it prints her own old
   team as the opponent. The banner's `P['team']` has the same tell.
2. **`home_score` / `away_score` fetched and discarded** (`:1587`) — see 2.3.
3. **Tab-header comments on `pages/7_Players.py` are off by one.** "TAB 3" twice
   (`:1001`, `:1197`), "TAB 4 — COMPARE" sits above `with tab_shot` (`:1272`),
   "TAB 5 — PLAYER PROFILE" above `with tab_cmp` (`:1463`), "TAB 6 — LAB" above
   `with tab_prof` (`:1541`). Cosmetic, but it mislabels every section of a
   1,915-line page.

---

## Build order

1. **Part 1 cuts** — pure deletion, no new engine, immediately shorter. Plus the
   percentile-list constant.
2. **Part 4.1 + 4.2** — the log bug and W/L, both small.
3. **Split `render_card` on the Part 3 seams, add `_UI.seg`.** Structural, no
   content change, unlocks everything after it. Mind
   [[seg-conversion-leaks-cross-tab-vars]]: AST-sweep for cross-section
   variable leaks *before* converting, since `_conf`, `_ls`, `_hand*`, `_gp`,
   `_szn` are currently shared down the whole function.
4. **§0 Verdict** — raise `build_feed`'s cap, run it through
   `insights_severity.rank()`, reconcile the three archetype labels.
5. **2.2 imports, cheapest first** — matchups, turnover types, ORtg/DRtg, on/off
   net; foul trouble next; chemistry behind a button, last.
6. **Game-window control**, once sections are lazy and each owns its own reads.

Re-measure the card's cold/warm cost on the droplet before and after step 3 —
the local number will understate it
(cf. [[court-png-43s-is-cold-cache]], [[insights-cold-cost-on-prod]]).
