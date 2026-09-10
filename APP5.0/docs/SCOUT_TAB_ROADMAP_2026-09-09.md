# Scout sheet — roadmap (2026-09-09)

Benchmarks: Team Dashboard **Insights** tab and **Player Profile** card.
Scope: `helpers/dashboard/scout_tab.py` (1,443 ln) + `helpers/scout.py` (1,489 ln,
owns `build_scout` and `printable_html`).

Two goals, in this order:

1. **Same depth, fewer printed pages.** The sheet's content is not the problem;
   its layout is. Most of the page count is duplication, dead full-width blocks
   and a print stylesheet that never got a second pass.
2. **Borrow the Insights grammar.** Scout is the one major view that leads every
   section with a table instead of a verdict, and the only one that uses neither
   `pctile_bar` nor `verdict_card`.

---

## Part 1 — Fewer pages (the print pass)

### 1.1 Three layout bugs costing pages right now

**`.wrap{max-width:840px}` is wider than the page.**
`helpers/scout.py:1425` sets the scout wrap to 840 CSS px = 8.75in. With
`@page{margin:.4in}` on Letter portrait the printable width is **7.7in**. The
content box is ~14% wider than the paper on every single print. Set the wrap to
the actual printable width and that 14% comes back as content instead of
shrink-to-fit.

**Compact mode only flows the middle third.**
`.flow2{column-count:2}` opens at `eff_html` and closes at `notes_html`
(`helpers/scout.py:1459-1480`). Everything before it — snapshot strip, keys,
auto-report, coach note, personnel, intel, matchups, the four-factor/zone row —
and everything after it — five shot-chart sections, saved plays, blank
diagrams — prints single-column full-width. Those are the page hogs, and they
are exactly the blocks compact mode never touches.

**No `size:` in `@page`.** Portrait is assumed, never chosen.

### 1.2 Landscape + 3 columns — the single biggest win

Letter landscape at `.4in` margins = **10.2in** printable. Three 3.2in columns
hold the current 11px tables comfortably (they are 5 columns wide at most).
Rough density gain over portrait-2-col: **~1.5x, with zero content removed.**

Ship it as a print-layout picker beside the existing compact checkbox:
`Portrait · 1 col` / `Portrait · 2 col` (today's default) / `Landscape · 3 col`.
Store next to `scout_compact` in `app_settings` — same per-coach mechanism.

Caveat to verify before shipping: the docstring on `printable_html` says the
xhtml2pdf fallback ignores `column-count` and drops inline SVG. `@page size` is
supported there, but confirm which renderer `helpers/ui.pdf_or_html_download`
actually reaches for, and make landscape degrade to 1-col-landscape rather than
breaking.

### 1.3 Duplication to delete (~0.75–1 page, no information lost)

| Block | Duplicates | Action |
|---|---|---|
| **Efficiency summary** (`eff_html`) | ORtg/DRtg/Pace are already the band chips; eFG/TOV/OREB are already four-factor rows | **Delete.** Or collapse to the one tempo sentence. |
| **Auto scouting report** (`report_html`) | `sc["guard"]` / `sc["attack"]` — a second rule-based bullet list from a different code path, immediately after the first | **Merge into Keys.** They read the same inputs with *different thresholds* and can contradict each other on screen. |
| **Zone shooting vs expected** (`zx_html`) | Same zone rows as **Shooting by zone** (`z_cell`), different columns | **Merge to one table:** Zone / 2P att / 2P FG% (±x) / 3P att / 3P FG% (±x). |
| **Team snapshot KPI strip** | The comment at `helpers/scout.py:1408` claims it avoids reprinting — but the strip *is* the four-factor rows | Keep the strip, drop the factor table's duplicated rows, or vice-versa. |
| **Shots allowed by play type** + **by defensive scheme** | `def_concession` says the same thing in 6 table rows | Demote both to **off by default**. |

### 1.4 Blank diagrams: 8 hard-coded courts

`per_row, n_courts = 4, 8` (`helpers/scout.py:1336`). That is close to a full
page, every print, whether or not the coach draws on it. Make it a setting:
**0 / 2 / 4 / 8, default 4.**

### 1.5 Shot charts: five sections become one wall

`_shot_grid` runs four times (by play, by defense faced, allowed by play,
allowed by scheme) plus the main chart — up to ~20 courts at 150px, 3-across.
Replace with **one "Shot wall" section**: a build-time picker for which split
to print, capped at 6 courts, 6-across at 110px in landscape. A coach reads two
or three of these; they never read twenty.

### 1.6 Personnel cards

`td.pcard{width:50%}` — 2-up, and each card runs 8–10 lines (bio, 0–100
breakdown, `overall_blurb`, rating role, playmix, cues, spacing index, badges,
note). Seven players ≈ a page and a half.

- **3-up in landscape.**
- Cut the card to a fixed 5-line shape: identity + OVR/starts, stat line,
  the *one* highest-severity tactical cue, playmix top-2, coach note.
- Push everything else to an optional "deep personnel" appendix section.

### 1.7 Make the cost visible — page budget + presets

The two highest-taste fixes, both cheap:

**Estimated pages.** Give every entry in `SCOUT_SECTIONS` a rough height weight,
sum the visible ones, and print `≈ 3.2 pages` live at the top of the
"⚙ Customize sheet" expander. The toggle list becomes a budget instead of 38
disconnected checkboxes.

**Named presets.** `scout_hidden_sections` already persists a hidden-key CSV per
coach. Store *named* sets on top of it and ship three:
- **Bench card** — 1 page (see Part 2)
- **Staff sheet** — 3 pages
- **Everything** — today's default

### 1.8 Estimated result

| Change | Pages back |
|---|---|
| Wrap width fix | ~0.4 |
| Landscape 3-col | ~1.5x density on the flowed blocks |
| Duplication deletes (1.3) | 0.75–1.0 |
| Diagrams 8 → 4 | 0.5 |
| Shot wall (1.5) | 1.0–2.0 |
| Personnel 3-up + trim | 0.5–0.75 |

Today's 4-page "everything" print should land at **2, maybe 2.5** — with *more*
content than it carries now once Part 3/4 land.

---

## Part 2 — The one-page call sheet (new)

The artifact that doesn't exist yet and should. Not a preset of the existing
sheet — a purpose-built page 1 a coach holds at the scorer's table:

- Defensive matchups table (already built: `SC.build_matchups`)
- Top 5 guard / top 5 attack keys, **severity-ranked** (Part 3)
- One line per opponent player: `#  Name  OVR  force-hand cue  one note`
- Their top 3 sets with PPP + the go-to in each situation
- Their top 2 defenses + what scores against each (`defenses_faced` already
  computes this)
- The breakeven 3P% number, one line
- ATO / late-clock tendency, one line

Everything else in the current sheet becomes the appendix behind it.

---

## Part 3 — Missing Insights grammar

Verified: `scout_tab.py` uses **`pctile_bar` zero times** and **`verdict_card`
zero times.** `insights_*`, `player_card`, `team_card`, `playstyle_tab` and
`defense_tab` all use both.

| Missing | Where it lives today | What to do |
|---|---|---|
| **Verdict-first sections** | `helpers/cards.verdict_card` | Every section leads with a badge + `n=` + one plain sentence, table underneath. This is the single largest look-and-feel gap. |
| **Percentile bars with a stated pool** | `helpers/cards.pctile_bar` | Four-factors hand-rolls colored bars and prints a bare `%ile` column. Swapping in the shared component gets pool labelling free — "71st vs 22 tracked girls teams." Honour `POOL_FLOOR=10`. |
| **Severity ranking** | `helpers/insights_severity.rank()` | `guard`/`attack`/`_auto_report_tips` emit bullets in *code order*, not effect-size order. Run them through the same ranker so the top 3 keys are actually the top 3. This is what makes Part 2's one-pager honest. |
| **Sample gating** | Insights' `n=` chips | `_auto_report_tips` thresholds are absolute (`eFG >= 0.50`, `pace >= 70`) with no GP guard. A 1-game opponent gets the same confident sentence as a 20-game one. Thin books make plain rates extreme. |
| **NEW chips** | `insights_tab._seen_tracker` | Re-scouting the same opponent after three more tracked games looks byte-identical to the first scout. The per-coach seen-blob pattern is already written and portable. |
| **Evidence jumps** | `insights_tab._request_view` / `TD_VIEW_GOTO` | A key should be able to jump to the chart that proves it. |
| **A deck / masthead** | `insights_deck.render` | Scout's header is five bare `st.metric`s. Insights' masthead carries rest days, next opponent and the scope note. |

---

## Part 4 — Engines that exist and never reach Scout

The highest-value list in this document. Every one is already written, tested
and paid for somewhere else in the app.

**Top priority — `helpers/exploit.py` (War Room only, `pages/9_War_Room.py:191`).**
`offensive_exploits` is *our set-call efficiency × their vulnerability to that
same set*, and `defensive_plan` is *what to play on D against them*. This is the
most scout-shaped engine in the codebase and the Scout tab does not import it.
It is correctly excluded from Insights (Insights is self-scout by charter) —
but Scout is exactly where it belongs. `game_plan` bundles both.

**`exploit.defender_profiles`** — measured per-defender on-ball D from the
`guarded_by_id` tag. The matchup planner currently prices edges off generic
0–100 OFF vs DEF ratings; this is the real measurement.

**`helpers/foul_trouble.py`** — who fouls and in which quarter. Enormous
scouting value ("their 5 is in trouble by Q3") and it is nowhere on the sheet.
Trouble is measured against the *quarter*, not halftime, and a carried foul
compares a player against her own clean quarters — get the semantics from the
engine, don't re-derive them.

**`passing_chains.connection_matrix` / `connection_verdict`** — `build_scout`
already computes `feeders`, and the printable spends it only on the hand-off
note. "Deny the X→Y pass" is top-tier scouting prose sitting unused.

**`fatigue.rest_on_date`** — one line, already computed for the Insights
masthead. Opponent on a back-to-back is a game-plan input.

**`rotation_plan.star_coverage`** — when their star sits. Directly actionable.

**`helpers/late_game.py`, `helpers/runs.py`, `helpers/stops.py`** — end-of-game
and run tendencies. `runs` reached Insights; none reached Scout.

**`helpers/matchups.py` + `helpers/predictor.py`** — the War Room's projected
score/margin belongs at the top of an opponent scout, not two pages away.

**`helpers/turnovers.py`** — live-ball vs dead-ball turnover mix. Decides
whether pressing them is worth it.

**`scheme_situational`** — imported to Insights 2026-09-07 via
`helpers/quarters.py`; the Scout equivalent (their scheme by quarter) is not
built.

---

## Part 5 — Remove or demote

- **Efficiency summary** — delete (§1.3).
- **Auto scouting report** — merge into Keys (§1.3).
- **Zone vs expected** — merge into Zones (§1.3).
- **Shots allowed by play type / by scheme** — default off (§1.3).
- **Impact & rating splits** — the on-screen block calls `ADV.leaderboard`, a
  full league leaderboard rendered inside an opponent scouting report. That is a
  Roster-tab artifact. Demote to an expander, or drop from the sheet.
- **Predictability** — reads oddly as its own section for an opponent ("they are
  62/100 predictable"). Keep the number, fold it into Keys as a sentence.
- **Blank diagrams at 8** — make it a setting (§1.4).

---

## Part 6 — Structure and perf

`render(ctx)` is correctly a `@st.fragment`, but it renders **all ~35 sections
eagerly** in one linear scroll, gated only by `_show()`. Since most coaches
leave most toggles on, every rerun does nearly all the work. Insights moved from
six eager `st.tabs` to lazy `_UI.seg` sections for exactly this reason — and
per-rerun work went *down* while the section count went *up*.

Convert Scout to the same grammar, six sections:
**Call sheet · Personnel · Their offense · Their defense · Shooting · Notes & print**

One hazard: the `st.tabs`→`_seg` conversion turns silent cross-section variable
leaks into `NameError`s. AST-sweep first. Scout's late locals (`_pred`,
`_qsplit`, `_gsplit`, `_zxfg`, `_creat`, `_conc`) are each computed near the
bottom and used once, so they move cleanly — but `sc`, `_show`, `_hidden`,
`_compact`, `_self` and `_matchups` are read everywhere and must stay in the
outer scope.

Also: the cold-opponent branch builds its own download (`scout_dl_cold`) with a
second `printable_html` call site. Two places to keep in sync on every change
above — worth unifying while the print pass is open anyway.

---

## Suggested order

**Phase 1 — print (highest ratio, mostly CSS + deletes)**
wrap width fix · landscape 3-col option · the five duplication deletes ·
diagram count setting · named presets · page-count estimate.

**Phase 2 — the one-page call sheet.** Needs Phase 3's ranking to be honest, so
build the layout now and wire the ranking in Phase 3.

**Phase 3 — grammar.** `verdict_card` + `pctile_bar` + `n=` gating +
`insights_severity.rank()` over guard/attack.

**Phase 4 — engines.** `exploit.game_plan` first, then `defender_profiles` into
the matchup planner, then `foul_trouble` / `fatigue` / passing connections onto
the personnel cards.

**Phase 5 — `_seg` conversion.** Last, because every phase above moves sections
around and the AST sweep should only be paid once.

Phases 1 and 3 are independent of each other and of Phase 4 — Phase 1 alone
delivers the "fewer pages, same depth" result.


---
---

# ADDENDUM — what to take from Insights, Player Profile and Charts

Added 2026-09-09, second pass. Part 3 above covered the *grammar* of those
tabs. This is the *content* inventory: every block on those three tabs, and
whether it survives being aimed at an opponent.

## Part 7 — Two structural moves that unlock most of this

### 7.1 Split the section toggle into "show" and "print"

`SCOUT_SECTIONS` carries **one** key per section and it gates the tab *and* the
printable together (`scout_tab.py:36`, "Applies to BOTH this interactive tab and
the printable hand-out"). That single flag is why "add more depth" and "print
fewer pages" read as opposing goals. They are not.

**Give every section two flags: `on screen` and `on paper`.** Default new depth
to screen-only. The tab becomes as deep as Insights; the sheet stays at two
pages; the coach promotes the three blocks that matter for *this* opponent to
paper. `scout_hidden_sections` becomes `scout_hidden_screen` +
`scout_hidden_print` — same storage mechanism, one extra CSV.

Everything in Parts 8–10 below assumes this. Without it, half of these ports
are page-count regressions and should not ship.

### 7.2 Widen `_opp_scout_ctx` — the one function that unlocks the ports

`pages/6_Team_Dashboard.py:6028`. Scout already rebinds the whole report onto
the opponent (`ctx = ctx.opp_ctx(_opp_tid)`, `scout_tab.py:451`), so the
opponent-facing plumbing exists. But `_opp_scout_ctx` returns a *narrow*
namespace — `bundle`, `players`, `team_id`, `has_tracked`, `summ`, `soff`,
`brk`, `ff`, `tb`, `scout`, `archetypes`, `located_team`, `zone_pair_bars`.

The Insights and Player-Profile renderers want fields it does not carry:
`tracked_ids`, `season`, `season_gp`, `season_fp_gp`, `ptable_full`,
`pp_zone_tables`, `render_profile`, `badges`. Most are already computed on the
page for the home team and just need the opponent's read-filtered equivalents
(`ob["tracked_ids"]` is right there).

**Widen that one 17-line function and most of Parts 8–10 becomes a call, not a
rewrite.** Keep the entitlement read-filter (`_ovk`) threaded through every new
field — a League-wide coach must still only see their pooled games of that
opponent.

---

## Part 8 — From the Insights tab

Insights surfaces 13 ported engines (`insights_deep._PORT_SECTIONS`) plus its
own section renderers. Every one is a **self**-scout read today. Aimed at the
opponent, the same engine answers the opposite question — that is the whole
port, and it is cheap.

### Tier A — build these

| Insights block | Aimed at the opponent it becomes | Why it is top tier |
|---|---|---|
| **`fouls` — foul trouble, what it costs** + **`clock` — the foul clock** | "Attack #34 early: her second foul historically lands at 4:12 of Q2, and they are −11 per 100 with her on the bench" | The best single item on this list. A median-second-foul timestamp per opponent player is a weapon no other high-school product has. Get the semantics from the engine — trouble is measured against the *quarter*, and a carried foul compares a player to her own clean quarters. |
| **`anatomy` — run anatomy** | "Their 10-0 runs start off live-ball turnovers with the press on, with these four on the floor" | This is "don't let the game get away from you," with the actual mechanism. Scout has nothing like it. |
| **`scheme` — vs defensive schemes, what slows this offense** | "What to play on D" — normalized against the coverage faced | Scout's `defenses_faced` is the raw table; this is the verdict. Pairs directly with `exploit.defensive_plan` from Part 4. |
| **`tovs` — giveaway mix** | "Their dominant turnover kind — sit on it" | The engine's own description says it is "what an opposing defence sits on." It was written for the scout and shipped on the self-scout tab. |
| **`hero` — ball share & shot concentration** | Star-dependence, measured | Scout's version is a hand-rolled `share >= 0.28` threshold inside `_auto_report_tips`. This replaces it with the real engine, including the "a team with one elite scorer *should* funnel" nuance. |
| **`involve` — involvement, the glue the box score misses** | The screener/passer who makes their offense go and never shows in the box | Highest-value *personnel* addition. Answers "who do we actually have to take away" when it isn't the leading scorer. |
| **`_render_boards` — force them off their hand · space dependence** | Per-player: which way to force, and who dies without a catch-and-shoot look | Scout already carries `p["hand"]["cue"]` and `p["space"]["cue"]` as one chip each. Insights has the full boards with the gap sizes. Put the number on the personnel card. |
| **`_render_pnr` — pick-&-roll role split** | Handler vs roller, per player | Direct coverage decision (go under / hedge / switch), per opponent player. |

### Tier B — worth it, lower priority

- **`stops` — stops & kills**: how often they answer straight back after
  conceding. Tells you whether a 6-0 run actually buys anything.
- **`ledger` — possession ledger**: how every possession ends on both ends.
- **`_render_winloss` — "do they beat good teams, or just bad ones"** and the
  in-wins-vs-in-losses split. Which version of them shows up, and what changes.
- **`_render_passers` / `_render_ball_movement`**: looks created vs converted →
  the "deny this pass" line (see also `passing_chains` in Part 4).
- **`reb` — rebounding verdict**: plain-word glass identity per player.
- **`insights_lineups`**: their best observed 5-man unit, and
  `rotation_plan.star_coverage` — when their star sits. **Expensive**:
  `networks.chemistry_network` is ~16.5s and sits behind an opt-in button on
  Insights for that reason. Screen-only, opt-in, never on the print path.
- **Deck masthead**: rest days (`fatigue.rest_on_date`) and record strip for the
  opponent. Cheap, and Scout's header is five bare `st.metric`s today.

### Do not port

**Monday** (own to-do list), **Receipts** (own engine audit), and `deserved` are
self-scout by construction. The **NEW-chip seen tracker** ports as a *mechanism*
(Part 3), not as content.

---

## Part 9 — From the Player Profile card

This is the direct answer to "add insights onto the player blocks." The
personnel card is Scout's player block, and it currently prints the same eight
fields for every player whether or not those fields are what makes that player
dangerous.

### 9.1 The highest-leverage move: wire up `quick_view`

`player_card.quick_view(pid, …)` renders **the entire player card in a modal,
one click from any table, no page switch** (`player_card.py:176`). It already
exists and is already used from roster/leaders tables.

Hang it off every personnel card on the Scout tab. The coach gets the full
30-block card on the one opponent player they care about — **without the sheet
carrying it.** This is the cleanest possible reconciliation of "I love how much
information is on the sheet" with "I don't want four pages": depth on screen,
selection on paper.

### 9.2 Onto the personnel card itself

| Player-card block | Port verdict |
|---|---|
| **Signature metrics** (the effect-size-ranked glass tiles) | **Top of the list.** Instead of the same eight fields per player, each opponent player gets *their* three distinguishing stats. This is precisely the Insights-tab quality the personnel card lacks. |
| **League percentiles grid** (`pctile_bar`, 4-across) | High. "78th percentile finishing" beats "TS 54%" for a coach who is not a stats reader. State the pool; honour the floor. |
| **Recent form — last 5 vs season** + rolling 3-game form | **High, and a genuine free win.** The scout is season-flat today: a player who has been cold for three weeks reads identically to one who is on fire. One delta chip per player fixes it. |
| **Shot detail** — rim / mid / three with n and FG% | High. One line, and it is the whole "where do we make her shoot from" decision. |
| **Hot zones** (per-player zone table) | High, screen-only. Print the mini chart the card already has. |
| **Dominant vs weak hand side** (full block) | Medium — Scout has the one-line cue; the full block belongs in `quick_view`. |
| **Scoring by quarter** (per player) | Medium-high. When does she get hers — pairs with the foul clock. |
| **Screen-action role** (handler vs roller finishing) | High. Scout has `playmix` (top 4 sets + PPP); this adds the role inside the action. |
| **Fouls & free throws** (per player) | High — pairs with `clock` from Part 8. |
| **`verdict_card` player verdicts** (e.g. `rebounding_verdict`) | High. A sentence per player, ranked against a stated pool. |
| **Impact — HoopWAR · RAPM · WPA** | Medium. Already computed by `_league`; nearly free. Screen-only. |
| Career highs · milestones · development · trajectory · projection · game log | **Skip.** Roster-planning content, not game-plan content. Reachable via `quick_view` anyway. |

---

## Part 10 — From the Charts tab

Seven stories (`ch_sub`: Offense · Play Style · Defense · Situational · Trends ·
Quarters · Winning Formula) plus Lab. Most are chart-shaped, and charts cost
print pages — so read this list as **screen-first**, with only the named few
promoted to paper.

### Tier A

| Charts block | Aimed at the opponent |
|---|---|
| **Defense → Opponent shot profile — "where they force shots"** | The single best chart on that tab for a scout. Aimed at them it is *where they will force us to shoot* — the offensive game plan in one image. |
| **Winning Formula — `team_formula` / `verdict_lines` / `suppressors`** | "What has to be true for them to win" inverts cleanly into "what to take away." `suppressors` is literally the scout answer, already prewritten as coach-speak. |
| **Lab → Team DNA (8 axes, league percentiles)** | An opponent DNA rail at the top of the sheet is the perfect at-a-glance header — and it replaces five bare `st.metric`s with something shaped like the rest of the app. Cheap to print (one row of bars). |
| **Offense → Shot Lab — shot-making vs shot quality** | Separates "they get good looks" from "they make tough shots." That is the contest-or-concede decision, and Scout cannot currently answer it. |
| **Defense → Glass → Putbacks — where second-chance points come from** | Where to box out, spatially. Scout has OREB% and nothing about *where*. |
| **Trends → Vs top-half vs bottom-half** | Are they a good-team beater or a stat-padder. One row, one line of prose. |

### Tier B

- **Playmaking → Connection Matrix** and **Expected Assists** — the "deny the
  X→Y pass" pair (`build_scout` already computes `feeders` and spends it only on
  a hand-off note).
- **Playmaking → Attempt Tilt (Corsi%)** — who tilts the shot count when on the
  floor.
- **Situational → How Every Possession Ends** and **Scoring Balance**.
- **Defense → Scheme** (`helpers/dashboard/defense_tab.py`, the one-tap
  defensive-identity deep dive) — Scout's `defenses_run` is the flat table;
  this is the deep read. Screen-only.
- **Lab → Impact Lab**: "Shot quality — points over expected", "Rotation —
  stagger & foul", observed 5-man units. Screen-only, opt-in.
- **Lab → Advanced résumé block**: SOS, quality wins, form & streaks,
  situational record, margins & venue, "did they beat who they should?" —
  medium value individually, but cheap and they compress into one four-line
  résumé paragraph at the top of a scout.

### Quarters — port the sentences, not the panels, and only some of them

Charts → Quarters has eleven sections. Scout has `quarter_split` (pts, opp,
margin, eFG by quarter) and quarter rows inside `situational`.

Insights already solved this the right way: it imported quarter analysis as
**verdict lines from `helpers/quarters.py`**, not as the panels. Do the same
here.

**But apply the measured guardrail.** Only *tempo* was found to repeat reliably
across quarters (split-half ≈ .60); quarter shooting and quarter ball-security
did not clear reliability and were refused. So port the tempo and
scoring-margin quarter lines ("they are a third-quarter team, +8 per 100 after
half") and **do not** ship "they shoot 27% in Q2" — that is noise dressed as a
scouting key, and it is exactly the kind of line that costs a coach a game.
Anything quarter-shaped that is not already blessed needs a split-half read
before it ships.

---

## Revised priority — the ten to build first

1. **Split show/print flags** (§7.1) — nothing else is safe to add without it.
2. **Widen `_opp_scout_ctx`** (§7.2) — turns the rest into calls.
3. **`quick_view` on personnel cards** (§9.1) — most depth per line of code in
   this whole document.
4. **Foul clock + foul trouble, per opponent player** (§8 Tier A).
5. **Signature metrics + last-5 form on the personnel card** (§9.2).
6. **`exploit.game_plan`** (Part 4) — still the biggest single engine gap.
7. **Winning Formula suppressors + Team DNA rail** as the sheet's new header
   (§10 Tier A).
8. **Run anatomy** (§8 Tier A).
9. **Opponent shot profile — where they force shots** (§10 Tier A).
10. **Giveaway mix + ball-share/involvement** (§8 Tier A).

Items 1, 2 and 3 are prerequisites-by-leverage: build them first and 4–10 stop
being ports and start being one-liners. Only 7 and 5 add print pages, and both
replace something already on the sheet.
