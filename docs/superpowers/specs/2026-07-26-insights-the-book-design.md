# The Book — Insights view redesign

**Date:** 2026-07-26
**Surface:** Team Dashboard → Insights (`helpers/dashboard/insights_tab.py`, `insights_deep.py`, `insights_brief.py`)
**Status:** design, approved in brainstorm; not yet planned

---

## 1. Why

Insights has the best voice in the app and the smallest surface. A five-agent inventory of
Roster, Charts, Lab and Insights (2026-07-26) put numbers on it:

| View | Panels | Verdict boxes | Rank tiles / percentile rails |
|---|---|---|---|
| Roster | 41 player-card + 13 roster + 3 impact | ~9 | yes — percentile rails, tier, league rank |
| Charts | ~120 across 7 tabs / 13 sub-tabs | 18 | yes |
| Lab | 29 across 3 tabs | 5 | yes — DNA radar, efficiency landscape |
| Insights | ~25 across 6 tabs | many, from 3 uncoordinated families | **no — every league-relative read is a sentence** |

Six specific defects, all confirmed against the source:

1. **Filing-cabinet order.** Sub-tabs are named by data category (`👤 Players`, `🏀 Offense`,
   `🛡️ Defense`). A coach asks questions, not categories.
2. **No deck.** Nothing renders above the tabs, by design (`insights_tab.py:504-510`). The page
   opens on a tab bar. Seconds-to-verdict is zero.
3. **Three engines, three scales, no common ranking.** The player miner sorts by `|z|`
   (`insights.py:1432`). The team miner uses the same sort but several generators do not produce a
   `|z|` at all — `_t_chemistry` hardcodes `score: 1.4` (`team_insights.py:344`), `_t_deserved`
   adds `+0.5` to jump the queue (`:622`), `_t_keys` synthesises `z = (hi_pct − lo_pct)/0.15`
   (`:386`). The 13 ported engines (`insights_deep.py:792`) are not scored at all — their order is
   a hand-authored tuple. "Strongest first" is therefore not one scale, so nothing can honestly
   float to the top.
4. **z-scores are not coach speak.** "1.8 SD below the league on box-out payoff" is not
   "you give up four extra shots a night."
5. **Zero widgets.** No filter, no sort, no game window, no player pick, no export. The whole view
   is display-only except six tabs and four buttons.
6. **Evidence jumps are mostly dead.** `_evidence_jumps` has exactly one call site (`:539`, over
   the team feed). The ~30 player-side keys in `_EVIDENCE_VIEW` never render a button. The 13
   engines print their owning view as plain text (`insights_deep.py:859`). And a jump cannot select
   an inner `st.tabs`, so "Charts → Trends" lands on Charts' first sub-tab.

Plus the largest gap: the most decision-useful cluster in the app — 5-man units with confidence
intervals, chemistry, synergy, the finisher finder, rotation star-coverage — lives under
`🧪 Lab → Impact Lab`. Insights emits `Lineups` and `Chemistry` as single sentences and nothing else.

---

## 2. The spine

**The page reconciles to the scoreboard.**

`deserved.py` already splits every game's margin into four terms — extra shots, selection,
shot-making, free throws — that sum *exactly* to the final margin. That reconciliation becomes the
organizing law of the whole view, not one panel inside it. Every section is an account of the
season that balances.

**The currency is points per game.** Every finding that has an honest conversion carries
`≈ +2.3 pts/g`. That is the translation layer that turns 39 z-scored generators into coach speak,
and it is what makes a single severity ranking possible.

---

## 3. The law: rank, never hide

**Severity ordering is a sort. It is never a filter.**

If an engine fires a finding, that finding renders — regardless of its confidence, its rank, its
sample, or whether it has a points conversion. Fifty findings under one player's name is a correct
outcome; the coach decides what matters. Severity only decides what appears *first*.

This is already the codebase's position and is regression-tested — every cap that used to exist was
deliberately removed (`tracker/test_insights_layout.py:244-256` asserts the absence of `hb[:8]`,
`cb[:10]`, `views[:3]`, `rows[:3]`, rebounding `[:2]`), and Insights already passes `top=None` to
both miners (`insights_tab.py:295`, `:331`). The redesign must not reintroduce a cap anywhere,
including in THE FIVE.

**THE FIVE is a spotlight, not a replacement.** It surfaces the five highest-severity findings at
the top of the page. The complete, uncapped list still renders in full inside its section. The same
finding appearing twice — once in the deck, once in its section — is intended.

---

## 4. Layout

### 4.1 THE DECK — persistent, above the section switcher

Occupies the space that is deliberately empty today. Renders on every section.

```
FAYETTEVILLE  8-3  ·  +6.2 margin/g  ·  #4 of 31  ·  3 days rest  ·  next: Bentonville (#2)
────────────────────────────────────────────────────────────────────────────────
"You win on the glass and lose at the line."
In this league SHOOTING decides games (38% of the pull). You are 71st percentile at it.
────────────────────────────────────────────────────────────────────────────────
[★ Extra shots +3.1]  [Selection +0.4]  [Making −1.2]  [Free throws −0.9]   = +6.2
────────────────────────────────────────────────────────────────────────────────
OFF ███████░░ 78   DEF █████░░░░ 52   SHOOT ███████░ 71   BALL ███░░░░░ 34   …
────────────────────────────────────────────────────────────────────────────────
THE FIVE — ranked worst first.  The full list lives in each section; nothing here is a cap.
1. ⚠ Box-out payoff, 31st pct     ≈ −4.6 pts/g   r=.74   → Defense   [see it]
2. ⚠ Weak-hand cliff, #12         ≈ −2.9 pts/g   r=.81   → Players   [see it]
3. ✓ Kill-strings, 88th pct       ≈ +3.4 pts/g   r=.69   → Defense   [see it]
4. ⚠ Scoutability, 22nd pct       —              r=.66   → Scout     [see it]
5. ✓ Second-chance rate, 84th pct ≈ +2.1 pts/g   r=.70   → Offense   [see it]
```

Deck components, and where each already exists:

| Element | Source | New? |
|---|---|---|
| Record / margin / rank / rest / next opponent | `bundle`, `fatigue.rest_splits`, `predictor` | assembled here |
| Identity sentence | `insights_brief._identity` (`:184`) | reuse |
| Winning-formula line | `winning_formula.team_formula` + `verdict_lines` (`:330`, `:390`) | **imported from Charts** |
| Four margin terms + ★ | `deserved.team_deserved`, `insights_brief._margin_bar` (`:155`) | reuse, promoted |
| DNA percentile rail | Lab's 8 DNA axes (`6_Team_Dashboard.py:4791-4800`) rendered as `cards.pctile_bar` | **imported from Lab**, re-rendered as a rail not a radar |
| THE FIVE | new severity engine (§5.1) | **new** |

### 4.2 Sections — recut by the question a coach asks

Replaces the six category tabs. `_seg` switcher, lazily gated (§6).

| # | Section | Contents (⊕ = imported, new to Insights) |
|---|---|---|
| 1 | **Who we are** | Team DNA percentiles ⊕, Efficiency Landscape ⊕, Winning Formula fit + suppressors ⊕, opponent-adjusted shooting ⊕, floor-spacing index ⊕, shot diet vs league, scoutability, style tags |
| 2 | **Why we win / why we lose** | deserved-per-game ledger, signature stats, record-by-goals, strength splits, W/L swing, runs & stops, quarter profile ⊕, score-flow shapes ⊕, close-game luck |
| 3 | **Who's helping** | the uncapped player feed (as today) + impact board ⊕ (RAPM / HoopWAR / WPA with CI whiskers), OLOAD/DLOAD boards, foul rate, development trajectory ⊕ |
| 4 | **Who to play together** | the whole Impact Lab ⊕ — 5-man units ±95%, trios & quads, chemistry pairs, synergy, finisher finder, star-coverage gaps, foul-prone |
| 5 | **What they'll take away** | the scout's report *on you* — scoutability, tendency drift, set & scheme fingerprints, matchup grid ⊕, situational spikes, hand gaps, space cliffs, shot map ⊕ |
| 6 | **Monday** | every actionable finding as a ranked practice priority with the points at stake (§4.3) |
| 7 | **Receipts** | all 13 ported engines + the failed-engine diagnostics drawer. Appendix, unchanged. |

Section 5 is written in the second person of an opposing scout — the same content as a self-scout,
framed as what someone else would key on.

### 4.3 Monday

Ranked practice priorities. Each row: the finding, what it costs in points per game, the sample,
the reliability `r`, and the section that holds the evidence.

**Monday names the problem. It does not prescribe the drill.** A metric→drill mapping would be
authored by us rather than measured by the app, and the app's standing rule is that a sentence
needs a measurement behind it (`reliability.py`, and the split-half discipline already in the book).
The coach decides how to fix it.

Monday is a view over the same severity-ranked list as THE FIVE, narrowed to findings whose
direction is negative *and* whose metric carries a `rehearsable` flag. That flag is an explicit,
authored property of the metric in the severity table — never inferred from the text — so it is
auditable and defaults to `False` for anything new.

That narrowing is a **display grouping inside Monday only**. It removes nothing from any other
section, and the full uncapped list still renders in each section per §3.

---

## 5. New machinery

### 5.1 `helpers/insights_severity.py`

One calibrated score across all three engine families.

The list is ordered in **two bands**. Every tagged finding sorts above every untagged finding; the
bands never interleave.

```
band 1 (has pts/g):  severity = |materiality| × reliability × confidence
band 2 (no pts/g):   severity =                  reliability × confidence
```

- `materiality` — points per game at stake (§5.2). Its presence decides the band; its magnitude
  decides the order within band 1. Absence is **never** a reason to drop a finding (§3).
- `reliability` — the measured split-half `r` from `helpers/reliability.py`, already the app's
  gate for whether a metric may carry a sentence at all.
- `confidence` — sample weight, reusing the existing `tier_factor(gp)` /
  `clamp(gp/20, 0.35, 1.0)` ladder from `insights.py:42` so it agrees with the miners.
- `direction` — sign only, carried alongside the score. Drives ⚠ / ✓ and Monday's grouping. It is
  never part of the ordering and never suppresses.

Two bands rather than one blended score because a neutral stand-in for missing materiality would
let an untagged finding outrank a genuinely small tagged one — which reads as the app inventing a
number it does not have.

Inputs: the player feed, the team feed, and the 13 ported engines. Output: one ordered list of
`{key, text, metric, n, pts, r, direction, section, evidence}`.

The three families keep their own internal ordering for their own sections. The severity list is an
*additional* ordering used by the deck and Monday. Nothing is rewritten upstream, so the existing
regression tests on the miners stay green.

### 5.2 Points-per-game translator

A per-metric conversion table plus derivations. Some metrics already carry points natively — the
four deserved terms, the possession ledger's pts/100, foul-state net, WPA. Most do not.

**Rule: never fabricate a conversion.** A metric without a defensible derivation renders with no
`pts/g` tag and sorts below tagged findings. No tag beats a wrong tag.

Initial tagged set (each has a derivation from an existing engine):
deserved terms, possession ledger sources, foul-state net, box-out payoff → extra possessions ×
league PPP, guarded-cliff → FG% gap × attempts, forced-TOV rate → empty trips × PPP, OREB% gap →
extra shots × PPP, kill-strings → trips × PPP, WPA → wins × league points-per-win from
`hoopwar.wins_per_point`.

Everything else launches untagged. The table grows as derivations are proven, not guessed.

### 5.3 `_seg` lazy sections

`st.tabs` executes **every** tab body on every rerun. All six current Insights tabs do their work
each time; only the caches make it survivable. The top-level dashboard views already avoid this
with `_seg` + `if _tdview == …` (`6_Team_Dashboard.py:1653-1666`).

Converting the Insights sections to `_seg` is load-bearing, not cosmetic — it is what pays for
sections 3, 4 and 5. Per-rerun work goes *down* even while the section count goes up.

### 5.4 A real `@st.fragment` on `render`

`insights_tab.py:12` documents `render(ctx) @st.fragment`. The function at `:447` carries no
decorator. Today every widget interaction, including the four jump buttons, reruns the whole page.
With §5.6 adding real controls this becomes mandatory.

### 5.5 Precise evidence jumps

`TD_VIEW_GOTO` parks a destination consumed at `6_Team_Dashboard.py:1673-1675`, before the switcher
widget is built. It cannot address an inner `st.tabs` because Streamlit tabs are not selectable
from session state.

Fix: convert the jump targets' inner tabs (Charts' 7, Lab's 3) to `_seg`, then extend the parked
payload to `(view, subview)`. Then:

- wire `_evidence_jumps` on every board, not just the team feed;
- turn the 13 engines' `home` chip from text into a button;
- add `_EVIDENCE_VIEW` entries for the currently unmapped team metrics (`Shots allowed`,
  `Contest rate`, `Margin mix`, `Forced TOs`, `Front-runner`, `After push`, `After cold`,
  `After scramble`, `Vs scheme`, `Deserved`).

This also fixes Charts' and Lab's own rerun cost, since their inner tabs stop computing every body.

### 5.6 Controls

The first widgets the view has ever had, in the deck so they apply to every section:

- player filter (multiselect, empty = all)
- game window (all / last 5 / last 10)
- opponent filter (all / top half / bottom half)

Each is a cache-key input, not a post-filter, so a narrowed window does less work rather than more.

---

## 6. Performance

Prod is 1 vCPU / 2 GB with no swap. Insights measures 85 s cold, 0.97 s warm; `_league` is ~30 s of
the cold cost.

- **RAPM and HoopWAR are already paid for.** `_league` calls `player_card._rapm` and `_war` at
  `insights_tab.py:288-290`. Section 3's impact board is close to free.
- **Chemistry is ~16.5 s** (`networks.chemistry_network`, measured, noted at
  `6_Team_Dashboard.py:1071-1074`). `lineups.unit_ratings`, `group_units` and `finisher_finder` are
  each their own possession walk.
- **Section 4 is lazy plus on-demand.** The section computes only when opened; inside it, the units
  / trios / quads / rotation block renders immediately, and chemistry + synergy + finisher sit
  behind their own button. Lab keeps its copies — nothing is retired.
- `_shot_diet_lines` is currently computed twice per run (`:545`, `:633`); the recut removes the
  duplicate.
- All existing `fp=`-keyed caches (`_data_fp`, `insights_tab.py:190`) carry over unchanged. The
  event-scoped / score-global split stays exactly as it is — that split is the fix for the
  84.7 s-cold regression and must not be touched.

Expected net: **warm gets faster** (six eager tab bodies → one lazy section), **cold is unchanged
until section 4 is opened**.

---

## 7. Component boundaries

| Module | Responsibility | Depends on |
|---|---|---|
| `helpers/insights_severity.py` | rank findings; own the pts/g table | `reliability`, the two feeds, `_ported` output |
| `helpers/dashboard/insights_deck.py` | the deck: identity, formula line, margin terms, DNA rail, THE FIVE, controls | `insights_severity`, `winning_formula`, `deserved`, `insights_brief` primitives |
| `helpers/dashboard/insights_tab.py` | section switcher + sections 2, 3, 5, 6 | deck, severity, existing renderers |
| `helpers/dashboard/insights_identity.py` | section 1 | `winning_formula`, `adj_efficiency`, `spacing`, DNA axes |
| `helpers/dashboard/insights_lineups.py` | section 4 | `lineups`, `networks`, `rotation_plan` |
| `helpers/dashboard/insights_deep.py` | boards + section 7 receipts | unchanged |
| `helpers/dashboard/insights_brief.py` | layout vocabulary (`block`, `grid`, `_tile`, `_margin_bar`) | unchanged, now shared by the deck |

`insights_tab.py` is 1150 lines today and would grow past 2000 without this split. Each new module
has one section's worth of responsibility and can be read on its own.

Rendering vocabulary is entirely existing: `insights_brief.block/grid/_tile/_bullets/_margin_bar`,
`cards.verdict_card/glass/pctile_bar/dense_table/stat_kpi/conf_dot_r`, the `.ins-*` CSS family, and
`reliability.measured` for the `r=` chip. No new CSS idiom is introduced.

---

## 8. Error handling

Unchanged in kind: every section stays wrapped so one failing engine degrades to a caption rather
than taking the page down (`"{Section} unavailable — {ExcType}: {msg}"`), and the `_ported`
diagnostics dict continues to distinguish a raising engine from a silent one. The severity engine
must itself be exception-isolated per finding — a bad `pts/g` derivation may not prevent the rest of
the list from ranking.

---

## 9. Testing

- `tracker/test_insights_layout.py` — update the stale "five sub-tabs" assertion (`:127-132`, it
  never probed `Offense`) to the new section list, and extend the no-caps assertions to cover the
  severity list and every new board.
- New: severity ordering is stable and total; the two bands never interleave (no untagged finding
  outranks any tagged finding); **every** input finding appears in the output list — the
  rank-never-hide law of §3, asserted directly by count.
- New: pts/g is absent rather than zero when no derivation exists.
- New: `rehearsable` defaults to `False`, so a newly added metric cannot silently appear in Monday.
- `tracker/test_view_jumps.py` — extend for the `(view, subview)` payload.
- AppTest smoke per the existing pattern (no-secrets cwd, `ta_team=1`, `ta_season=2025-2026`) on
  each of the seven sections, including the empty-roster and locked-tier states.

---

## 10. Build order

1. `_seg` lazy sections + real `@st.fragment` — pure restructure, no new content, measurable warm-time win.
2. `insights_severity.py` + the pts/g table, rendered as a plain ranked list inside Receipts to validate the ordering on real seasons before it drives anything.
3. THE DECK, once the ranking is trusted.
4. Section recut 1/2/3/5/7 from existing content.
5. Section 4, lazy + on-demand.
6. Precise jumps (`_seg` conversion of Charts and Lab inner tabs).
7. Controls.
8. Monday.

Steps 1 and 2 are independently shippable and independently valuable.

---

## 11. Explicitly out of scope

- Opponent-facing prep. Insights stays self-scout; `exploit.game_plan` remains War Room's.
- Retiring any panel from Charts, Lab or Roster. Every import is a copy.
- Drill prescriptions in Monday (§4.3).
- Changing any generator's own score, gate or threshold. The severity engine reads them; it does not
  rewrite them.
- Any change to the `_data_fp` cache-key split (§6).
