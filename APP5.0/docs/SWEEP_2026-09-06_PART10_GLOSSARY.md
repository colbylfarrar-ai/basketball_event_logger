# Sweep — 2026-09-06 · Part 10: the explanation layer

Final part of the September sweep (Parts 1 gating, 2 Team Dashboard, 3 Officiating
Lab, 4 Rankings, 5 database, 6 engines, 7 War Room / Players, 8 what to build,
9 capture). Read-only, static analysis plus direct engine calls against a
`sqlite3.backup` copy of the live book. **The live book was never written to.**
No application code changed.

The premise: this app computes 0-100 ratings, RAPM, WAR, expected points per
shot, shot rating, SMOE, four factors, WPA, archetypes, possession value and luck
for a high-school basketball coach. A number a coach cannot interpret is worse
than no number — it costs screen space, it costs trust, and it invites the wrong
decision. So the explanation layer is a feature, not documentation.

## Two findings verified independently before committing this

**1 · `SCE` is one key doing two jobs, and the glossary knows.** `STAT_DEFS`
carries both `("ScEff", "Scoring Efficiency", …)` and `("SCE", "Self-Creation %",
…)`, and the ScEff entry's own text warns *"NOT the same as SCE /
Self-Creation %"* — so the authors knew. But the **data layer** uses the key
`SCE` for Scoring Efficiency everywhere it renders it:

```
helpers/defenses.py:162            "SCE": _safe(c["PTS"], _2pa*2 + FG3A*3)     <- ScEff's formula
helpers/box_score.py:751           column_config.NumberColumn("ScEff", …)      keyed on SCE
helpers/dashboard/insights_tab.py:438   ("Scoring eff (ScEff)", "SCE", _pct)
pages/6_Team_Dashboard.py:3285          ("ScEff", "SCE")
```

while `pages/7_Players.py:296` registers `glossary_key(…, "SCE", …)`, whose
popover resolves to **Self-Creation %**. A coach who taps the stat key on the
Players page to decode a column learns the wrong metric from the app's own
glossary.

**2 · `Leverage` is defined twice for unrelated concepts.** Confirmed
mechanically — 121 rows, 120 unique abbreviations, and the collision is:

```
Leverage  Game leverage (officials)   0.6*team-quality + 0.4*closeness
Leverage  Leverage Index              how much a basket would swing win prob
```

Exact-match lookup takes the first. The Officials page's
`glossary_key("FPG","Leverage","PPP","Clutch")` happens to want the first one, so
it is right today by luck; any second consumer gets the wrong definition silently.

## Where this part agrees and disagrees with Part 8 §3

Part 8 §3 argued that the app publishes numbers whose sample it does not
disclose. This part confirms it at the widget level and adds the mechanism:
**`cards.pctile_bar` — the app's most-reused explanation primitive, 13+ call
sites — has no pool-size parameter at all**, so a percentile bar built from five
tracked teams is visually identical to one built from 748. It also confirms the
quantization directly: boys team percentiles land on exactly {10, 30, 50, 70, 90}.

It disagrees with one thing this sweep assumed. The audit's own opening
hypothesis — that dense tables ship without captions — is recorded as **largely
wrong**: the app captions well at the section level. The real gap is narrower and
more specific: individual columns left unexplained *inside* captioned tables.
Rankings' flagship Tracked-ratings grid is the example — `Rating`, `RatingPts`,
`ClassAdj` and `SOR` sit beside the well-explained `Power` with no glossary entry,
and two of them have no `help=` anywhere. Four numbers claim to answer "how good
is this team"; one is explained.

## The calibration checks are the part worth reading twice

Stated ranges measured against the book, and they do not all fail:

* `ShotRating`'s "50 = average" anchor is off by 7–15 points — this book shoots
  34.7%, so the real average sits nearer 57–65.
* `VPS`'s "~1.0 breaks even" is actually the **75th percentile**; the median is
  0.67.
* `AST/TO` states no range at all, and the real median is **0.30** — far below
  what a reader would assume.
* `OVERALL`'s stated ladder, by contrast, **matches** measured percentiles well.

Not everything is miscalibrated, which is why each one had to be measured.

## And one story worth keeping

The confidence infrastructure (`conf_dot`, `conf_dot_r`, Wilson intervals) is
well designed and narrowly wired — `stat_kpi()` is defined and never called, and
`conf_dot_r` reaches two files while `reliability.MEASURED` covers many more axes.
But the on/off-offense card, once the most-fired card in the app, was measured at
split-half −0.21, found unreliable, and **the code was actually rewired to gate on
RAPM agreement**. The measurement got acted on. That is the program working, and
it is the argument for extending it to the ~25 untouched percentage columns the
ranked list ends with.

---

# Explanation-Layer Audit — APP5.0 (read-only, static analysis)

Book snapshot: `.../scratchpad/book/analytics.db` (girls pool 242 players/21 teams/35 games,
boys pool 59 players/5 teams/8 games, season="2025-2026"). All measurements below were taken
against this snapshot with the pinned Python 3.12 interpreter, `streamlit` stubbed out so the
engines import cleanly outside a running app (no AppTest, per instructions).

## 0. Shape of the source of truth: `helpers/glossary.py`

`STAT_DEFS` is a flat list of 7-tuples: `(ABBR, Full name, Category, Formula, Definition,
"How to read it", invented?)`. **121 rows, but only 120 unique abbreviations** — see Finding
G-1 below. 11 categories: Box Score(12), Shooting(16), Playmaking(12), Rebounding(3),
Defense(9), Possession & Pace(11), Advanced(22), Shot Quality(4), Ratings(11),
Team & League(17), Officiating(4). 55 of 121 (45%) are flagged `invented=True` ("signature"
metrics unique to this app).

Quality of the definitions themselves is good where they exist: spot-checking a random sample,
almost every row answers "which direction is good" (explicit "Higher/Lower is better" or a
directional worked example) and most give a "so what" in the "how to read" field. The weak spot
is **typical range**: only a minority state a concrete number (e.g. RTG's "7.5 good · 8.5 great
· 9+ rare · <6 poor", TS%'s "~50%+ is strong at HS", VPS's "~1.0 breaks even, 2+ excellent").
Most just say "higher/lower is better" with no anchor — technically satisfies "direction" but
not "range". Quantified in the census table (Section 2).

Two structural findings from reading the whole file + its two call sites (`stat_help`,
`glossary_key` in `helpers/ui.py:833,858`), both of which do an **exact, first-match lookup**
(`next(d for d in STAT_DEFS if d[0] == abbr)`) with no de-dup and no fuzzy matching:

**Finding G-1 — duplicate abbreviation "Leverage" (data bug, not yet a visible bug).**
`glossary.py:491` defines `("Leverage", "Game leverage (officials)", ...)` and `glossary.py:573`
separately defines `("Leverage", "Leverage Index", ...)` — a completely different concept (how
decisive a single basket is, used by Clutch WPA). Because lookups take the *first* match,
`stat_help("Leverage")` or `glossary_key(..., "Leverage", ...)` called anywhere in a
player/WPA/clutch context would silently render the **officials** definition. Today this isn't
visibly wrong only because the one live call site (`pages/8_Officials.py:368`) happens to be in
the officiating context that matches the first row — it is one future edit away from silently
showing the wrong card next to Clutch WPA. In the full `render_glossary` browse/search view both
cards do appear (no dedup there either), so a coach searching "leverage" sees two same-named
cards with different bodies and no explanation that they're unrelated stats. Cheap fix: rename
one abbreviation (e.g. officials one → "GameLvg").

**Finding G-2 — "SCE" means two different things depending on which table you're looking at
(confirmed misleading, not just undefined).** The glossary's `SCE` entry (Playmaking) defines it
as **Self-Creation %** = self-created shots / FGA (`glossary.py` Playmaking block). That is a
*player* metric, and the player engine's real column for it is named `SelfCr%`
(`helpers/player_ratings.py`), not `SCE` — so the glossary's own `SCE` card does not correspond
to any live `player_stat_table` key by that name. Meanwhile `helpers/league_analytics.py:511`
defines the **team** stat-table column literally labeled `"SCE"`, sourced from
`S.shot_efficiency()` (`helpers/stats.py:418`, "(PTS − FT) / (2·2PA + 3·3PA)") — i.e. **Scoring
Efficiency**, the exact same formula the glossary separately and correctly documents under the
abbreviation `ScEff`. `helpers/stats.py:466`'s own docstring admits the collision: *"This is the
canonical name for what the profile/team code has long called 'SCE' — an alias of
shot_efficiency so there's one implementation."* Net effect: `pages/7_Players.py:295` puts `SCE`
in its stat-key popover list, so a coach on the Players page learns "SCE = Self-Creation %,
higher = shot-maker who doesn't need setup." That same coach then opens the Rankings "Full team
stat table" (`pages/5_Rankings.py`, `LA.team_stat_table`), sees a `SCE` column there too, and
has every reason to apply the *player* definition they just learned — but the team column is
actually shooting efficiency, an unrelated formula. Both readings happen to reward "higher is
better," which limits the damage, but the mental model ("we're isolation-heavy" vs "we shoot
efficiently") is simply wrong. No page currently runs `glossary_key`/`stat_help` on the team
`SCE` column, so today it is simultaneously **undefined-in-context** AND **primed to be
misread** because of the identical abbreviation living correctly elsewhere. This is the single
best example found of "defined badly" in the sense the task cares about, and ranks at the top of
the Section 2 misread-risk list.

Methodology note for what follows: the metric census is built from (a) the programmatic key set
of `player_stat_table()` (196 keys, called directly against the snapshot), (b) the hand-curated
`_TEAM_STAT_SPEC` display-label list in `helpers/league_analytics.py` (the team analogue, ~70
labels), (c) `helpers/league_analytics.py` league/form functions, and (d) grep of
`glossary_key(`, `stat_help(`, `help=`, `column_config`, and `.rename(columns=` across
`pages/*.py` and `helpers/dashboard/*.py` to find where each label actually reaches the screen
and whether it carries in-context help. Sections below are appended as each task completes.

## 1. Metric census — how it was built, and the headline counts

Programmatically calling the engines against the snapshot (streamlit stubbed, no AppTest):

- `player_ratings.player_stat_table(season="2025-2026", gender="F")` → **242 players, 196
  distinct dict keys** (confirms the pool size given in the brief). Roughly 30 of the 196 are
  meta (name/team/class/height…), ~25 are per-game (`/G`) or per-32 mechanical derivatives of an
  already-counted stat, ~10 are Wilson 95%-CI bounds (`FG%lo/hi` etc. — see the positive finding
  in §4), and a handful are internal engine pass-through duplicates the code deliberately keeps
  for OTHER engines to read (`def_secure_team_pct`, `onball_share`, `own_misses`,
  `tagged_dreb`…) and never surfaces as a column — the docstring at
  `helpers/player_ratings.py:1737` says as much. Net: **~140 keys are genuine, screen-worthy
  metrics.**
- `_TEAM_STAT_SPEC` in `helpers/league_analytics.py:488` is the hand-curated team analogue: **70
  display-label columns**, already using display names (not engine keys), feeding the Rankings
  "Full team stat table" (`pages/5_Rankings.py`, gated behind a load-on-demand toggle) and the
  smaller "Tracked ratings" grid on the same page.
- `helpers/league_analytics.team_form_stats` and `team_ratings.tracked_ratings` supply the
  results-only composites (Dominance, Consistency, Clutch, Momentum, Luck, Volatility, W/L/MOV)
  layered on top.
- `glossary_key(`/`stat_help(` call sites (the ONLY places the app links a number to its glossary
  card programmatically) — all 8 found by grep: `pages/5_Rankings.py:711`,
  `pages/6_Team_Dashboard.py:411`, `pages/7_Players.py:295`, `pages/8_Officials.py:368`,
  `pages/9_War_Room.py:511`, `helpers/box_score.py:1413,1496`, `helpers/league_spotlight.py:314`.
  Combined they cover well under half of the ~140 real metrics — most of the app's numbers reach
  the screen with **no programmatic link back to their own definition**, only the standalone
  Glossary tab as a manual lookup.
- `glossary_tab(` (the full ~105k-character catalogue) is embedded on **five** pages, not the
  three-plus-one the task brief names: `pages/5_Rankings.py:3436`, `pages/6_Team_Dashboard.py:6453`,
  `pages/7_Players.py:1894`, `pages/8_Officials.py:926`, `pages/9_War_Room.py:1974`. (Players was
  not called out in the brief but does carry it.)

## 2. Cross-reference against `STAT_DEFS`

### 2.1 Full census table (STAT_DEFS granularity, 121 rows)

"Dir?"/"Range?"/"So-what?" are a **mechanical** read of each row's own "how to read it" field
(keyword match for a direction word; digit-presence for a stated anchor/range; non-empty for any
"so what" at all) — a first pass, not a hand-grade, so treat borderline N's as "not asserted
crisply" rather than "totally absent." "Where shown" is hand-verified for every row I could
confirm by grep + reading the call site (the large majority); a handful marked
"(category-level: … pages)" are inferred from the page's known column set rather than
individually eyeballed — called out so the table doesn't overclaim precision it doesn't have.
"Measured on this book" is filled in only where I actually ran the engine against the snapshot
(§2.3 explains each one); blank does not mean "fine," it means not measured this pass.

| Metric | Full name | Category | Where shown | Dir? | Range? | So-what? | Measured on this book |
|---|---|---|---|---|---|---|---|
| **PTS** | Points | Box Score | Players full table, Team Dashboard box, Rankings | Y | N | Y |  |
| **REB** | Total Rebounds | Box Score | Players/Team Dashboard box | Y | N | Y |  |
| **OREB** | Offensive Rebounds | Box Score | Players/Team Dashboard box | N | N | Y |  |
| **DREB** | Defensive Rebounds | Box Score | Players/Team Dashboard box | N | N | Y |  |
| **AST** | Assists | Box Score | Players full table, box | Y | N | Y |  |
| **STL** | Steals | Box Score | Players/box | Y | N | Y |  |
| **BLK** | Blocks | Box Score | Players/box | Y | N | Y |  |
| **TOV** | Turnovers | Box Score | Players/box | Y | N | Y |  |
| **PF** | Personal Fouls | Box Score | box score | Y | N | Y |  |
| **+/-** | Plus / Minus | Box Score | Players full table | Y | N | Y |  |
| **MIN** | Minutes Played | Box Score | Players full table | N | N | Y |  |
| **FG%** | Field-Goal % | Shooting | Players full table, scout | Y | N | Y |  |
| **2P%** | Two-Point % | Shooting | Players scout/profile | Y | N | Y |  |
| **3P%** | Three-Point % | Shooting | Players full table | Y | Y | Y |  |
| **FT%** | Free-Throw % | Shooting | box score, profile | Y | Y | Y |  |
| **eFG%** | Effective FG% | Shooting | Players glossary_key list, Team Dash | Y | N | Y |  |
| **TS%** | True Shooting % | Shooting | Players Ratings tab caption, box | N | Y | Y | median 34.3, p10/p25 = 0 (n=204 with FGA/FTA>0) — the ~50%+ anchor is a real 'good' bar but sits far above the pool median; ~1 in 4 qualifying players is a 1-4 shot small sample at literal 0%. No sample-size caveat in the definition. |
| **ScEff** ✦ | Scoring Efficiency | Shooting | player_stat_table (ScEff key) — not confirmed as its own column label | Y | Y | Y |  |
| **AdjeFG%** | Adjusted eFG% | Shooting | Rankings Tracked grid, labeled 'Adj eFG%' (space) — cosmetic drift from abbr | N | N | Y |  |
| **3PAr** | Three-Point Rate | Shooting | Team Dashboard glossary_key list | N | N | Y |  |
| **FTr** | Free-Throw Rate | Shooting | Team Dashboard/Players glossary_key list | Y | N | Y |  |
| **PPS** | Points Per Shot | Shooting | Players glossary_key list, Team card | Y | N | Y |  |
| **PPSA** | Pts Per Scoring Att | Shooting | player_stat_table key only, not seen in a page column list | Y | N | Y |  |
| **Paint FG%** | Paint FG% | Shooting | scout/zone tables | Y | N | Y |  |
| **Paint PTS** | Paint Points | Shooting | shown as 'PaintPTS'/'Paint/G' (no space) — cosmetic drift | N | N | Y |  |
| **AST/TO** | Assist-to-Turnover | Playmaking | Players glossary_key list (as 'AST/TO'); player_stat_table key is 'AST/TOV' — drift | Y | Y | Y | player_stat_table's AST/TOV median 0.30, mean 0.53, p90 1.20, max 6.0 (n=198) — no range stated in the glossary at all; '>2.0 excellent' is confirmed rare (top ~1-2%), but a naive guess at 'typical' would badly overshoot the real median. |
| **AST%** | Assist % | Playmaking | player_stat_table key | Y | N | Y |  |
| **TOV%** | Turnover % | Playmaking | Team Dashboard/Players glossary_key list | Y | N | Y |  |
| **USG%** | Usage Rate | Playmaking | Players/Team Dashboard glossary_key list | Y | N | Y |  |
| **SC** | Shot Creation | Playmaking | player_card, scout_tab | Y | N | Y |  |
| **PotAST** ✦ | Potential Assists | Playmaking | player_card/scout as 'PotAST' | Y | N | Y |  |
| **ScrAST** ✦ | Screen Assists | Playmaking | player_card | N | N | Y |  |
| **HAST** ✦ | Hockey Assists | Playmaking | player_card (opt-in, reads 0 until tagged) | N | N | Y |  |
| **xA** ✦ | Expected Assists | Playmaking | player_card, Insights | N | N | Y |  |
| **xA2** ✦ | Secondary Expected Assists | Playmaking | player_card (gated, 3+ games team-tagged) | N | N | Y |  |
| **Corsi** ✦ | Corsi (attempt ±) | Playmaking | player_card/Insights | N | N | Y |  |
| **SCE** | Self-Creation % | Playmaking | Players glossary_key AND Team full stat table — SAME abbr, TWO DIFFERENT metrics (Finding G-2) | Y | N | Y |  |
| **OREB%** | Off. Rebound % | Rebounding | Players/scout | Y | N | Y |  |
| **DREB%** | Def. Rebound % | Rebounding | Players/scout | Y | N | Y |  |
| **TRB%** | Total Rebound % | Rebounding | shown as 'REB%' (no 'T') — cosmetic drift | Y | N | Y |  |
| **RimProt** ✦ | Rim Protection | Defense | (category-level: Defense pages) | Y | Y | Y |  |
| **PerimD** ✦ | Perimeter Defense | Defense | (category-level: Defense pages) | Y | Y | Y |  |
| **STOCKS** | Stocks | Defense | box/badges | Y | N | Y |  |
| **CHG** | Charges drawn | Defense | box (charges) where tagged | Y | N | Y |  |
| **DSHOT%** | Defended FG% | Defense | Players/Team Dashboard glossary_key list | Y | N | Y |  |
| **AdjDFG%** ✦ | Adjusted Defended FG% | Defense | computed in player_ratings.py, feeds DEFENSE rating — NEVER surfaced as its own column anywhere (Finding, see 2.2) | Y | N | Y |  |
| **DFGoe** ✦ | Defended FG% over expected | Defense | computed in player_ratings.py — NEVER surfaced as its own column anywhere (Finding, see 2.2) | Y | N | Y |  |
| **Guarded%** | Contest Rate | Defense | player_card/scout | Y | N | Y |  |
| **POSS** | Possessions | Possession & Pace | team tables (Poss/G) | N | N | Y |  |
| **Pace** | Pace | Possession & Pace | Rankings/Team Dashboard glossary_key list | Y | N | Y |  |
| **PPP** | Points Per Poss. | Possession & Pace | Rankings/Team Dashboard/Players/War Room/Officials glossary_key lists (most-cited stat in the app) | Y | N | Y |  |
| **Play Type** ✦ | Possession / Play Type | Possession & Pace | helpers/box_score.py section, Team Dashboard scheme_section | Y | N | Y |  |
| **Defense** ✦ | Defensive Scheme | Possession & Pace | team defensive-scheme tab (helpers/scheme_section.py) | Y | N | Y |  |
| **ORtg** | Offensive Rating | Possession & Pace | Rankings/Team Dashboard/Players/War Room glossary_key lists | Y | N | Y |  |
| **DRtg** | Defensive Rating | Possession & Pace | same as ORtg | Y | N | Y |  |
| **NetRtg** | Net Rating | Possession & Pace | same as ORtg | Y | N | Y |  |
| **RTG** ✦ | Game Rating (0-10) | Advanced | (category-level: Advanced pages) | Y | Y | Y |  |
| **GS** | Game Score | Advanced | player_card/box | Y | Y | Y |  |
| **PER** | Player Efficiency | Advanced | player_card (labeled same as GS per definition) | N | Y | Y |  |
| **EFF** | Efficiency (NBA) | Advanced | Players full table | Y | N | Y |  |
| **FIC** | Floor Impact Ctr. | Advanced | player_stat_table key, not seen in a page column list | Y | N | Y |  |
| **VPS** | Value Point System | Advanced | Players full table | Y | Y | Y | median 0.67, mean 0.75, p75 1.00, p90 1.50, max 4.5 (n=220) — the stated '~1.0 breaks even' anchor is actually ~p75 in this pool, well above the typical player. |
| **PRF** | Pts Responsible For | Advanced | player_stat_table key (PRF/G on scout cards); FAQ's own 'worth looking up first' example | Y | N | Y |  |
| **per-32** | Per-32 Minutes | Advanced | Players glossary_key list (generic pattern; STOCKS/32 is the one concrete column) | N | N | Y |  |
| **Shot Rating** ✦ | Shot Rating | Shot Quality | Players Shot Lab, player_card | Y | N | Y | median 59.2, mean 57.5 (n=202) vs the glossary's stated anchor '50 = sample-average shot'. League FG% on this book is 34.7% (3246 FGA), so the shot-weighted average difficulty implied by the book is ~65, not 50 — the '50' anchor assumes a 50%-FG% league that this book is not. Confirmed mismatch. |
| **xFG%** | Expected FG% | Shot Quality | Players glossary_key list, Shot Lab | N | N | Y |  |
| **SMOE** ✦ | Shot-Making Over Exp. | Shot Quality | Players Shot Lab (with its own caption, good example) | Y | N | Y |  |
| **xPPS** | Expected Pts/Shot | Shot Quality | Shot Lab/player_card | N | N | Y |  |
| **OVERALL** | Overall Rating | Ratings | Players/Team Dashboard/War Room/Rankings — the single most-shown number in the app | Y | Y | Y | girls pool (n=242, min_games=1): median 48.7, mean 50.9, p75 54.1, p90 59.2, max 83.7 — matches the stated 50/54/62/70 ladder reasonably well. |
| **OFFENSE** | Offense Rating | Ratings | Ratings tab, radar | Y | N | Y |  |
| **DEFENSE** | Defense Rating | Ratings | Ratings tab, radar | Y | N | Y |  |
| **PLAYMAKING** | Playmaking Rating | Ratings | Ratings tab, radar | Y | N | Y |  |
| **REBOUNDING** | Rebounding Rating | Ratings | Ratings tab, radar | Y | N | Y |  |
| **PHYSICAL** ✦ | Physical Rating | Ratings | player_card only | N | N | Y |  |
| **2WAY** ✦ | Two-Way Rating | Ratings | Players full table | Y | N | Y |  |
| **VERSATILITY** ✦ | Versatility | Ratings | Players full table (as 'VERS') | N | Y | Y |  |
| **Power** | Power Rating | Team & League | Rankings headline, Team Dashboard, War Room | Y | N | Y | boys pool is 5 tracked teams — percentiles off this pool land only on 10/30/50/70/90 (measured directly via cards.pctile on tracked Power), not arbitrary values; no widget surfaces pool size next to the percentile. |
| **Four Factors** | Dean Oliver's Four Factors | Team & League | Team Dashboard Charts tab | N | N | Y |  |
| **TO kind** ✦ | Turnover Kind | Team & League | Team Dashboard turnover breakdown (opt-in tag) | N | N | Y |  |
| **4F-PPP** ✦ | Four-Factor Expected PPP | Team & League | helpers/box_score.py glossary_key call site | N | Y | Y |  |
| **Pythag** | Pythagorean Wins | Team & League | Rankings team form table ('Pyth W%' — cosmetic drift) | N | N | Y |  |
| **Luck** ✦ | Luck | Team & League | Rankings glossary_key list ('Luck%' column — cosmetic drift) | Y | N | Y |  |
| **SOS** | Strength of Sched. | Team & League | Rankings Tracked grid + glossary_key list | Y | N | Y |  |
| **ClutchFT%** ✦ | Clutch Free-Throw % | Shooting | player_card clutch section | N | N | Y |  |
| **And-1** ✦ | And-One (3-Point Play) | Shooting | player_card/box splits | N | Y | Y |  |
| **Rest** ✦ | Rest & Fatigue Splits | Team & League | Team Dashboard Rest & Fatigue section | Y | N | Y |  |
| **Volatility** ✦ | Volatility | Team & League | Rankings full team table | Y | N | Y |  |
| **Dominance** ✦ | Dominance | Team & League | Rankings full team table | Y | N | Y |  |
| **Consistency** ✦ | Consistency | Team & League | Rankings full team table | Y | N | Y |  |
| **Clutch** ✦ | Clutch | Team & League | Officials glossary_key list AND Rankings full team table (team 'Clutch' 0-100 index) — same abbr, team vs officials context, formulas ARE both about close games so lower collision risk than SCE/Leverage | Y | N | Y |  |
| **Momentum** ✦ | Momentum | Team & League | Rankings full team table | Y | N | Y |  |
| **Balance** ✦ | Scoring Balance | Team & League | Team Dashboard scoring-balance panel | Y | N | Y |  |
| **FPG** | Fouls Per Game | Officiating | Officials glossary_key list + table | Y | N | Y |  |
| **Call %** | Call Share | Officiating | NOT shown directly — table shows the z-scored 'Share σ' derivative instead, which has its own inline caption but no glossary row | N | N | N |  |
| **H/A** | Home/Away Lean | Officiating | Officials table (home/away lean) | N | Y | Y |  |
| **±FPG** | FPG Consistency | Officiating | Officials table | Y | N | Y |  |
| **WinProb** | Win Probability | Advanced | Team Dashboard live win-probability chart (as full words 'Win Probability', not the abbr) | N | Y | Y |  |
| **GEI** ✦ | Game Excitement Index | Advanced | Rankings glossary_key list + Hall of Fame; has its own stat_help popover (league_spotlight.py) | Y | Y | Y |  |
| **Adj GEI** ✦ | Stakes-adjusted GEI | Advanced | Hall of Fame 'stakes-adjusted' exciting games list | Y | Y | Y |  |
| **OffRating** ✦ | Officials Rating | Advanced | Officials table — shown as bare 'Rating' column header, not 'OffRating' (cosmetic drift, high risk: 'Rating' is generic) | Y | Y | Y |  |
| **Leverage** ✦ | Game leverage (officials) | Advanced | Officials glossary_key list (officials sense) — DUPLICATE ABBR, see Finding G-1 | N | Y | Y |  |
| **sTS%** ✦ | Stabilized rate | Advanced | used internally by shrinkage.py; not a labeled column | N | N | Y |  |
| **Archetype** ✦ | Play-Style Cluster | Ratings | Players Lab -> Archetypes tab, player_card 'Cluster' chip | N | N | Y |  |
| **Role** ✦ | Scouting Role | Ratings | player_card hero card ('Scouting Role') | N | N | Y |  |
| **MtchDiff** ✦ | Matchup Difficulty | Defense | surfaced only as PROSE in Insights, never a labeled column | N | Y | Y |  |
| **Badge** ✦ | Skill Badge | Ratings | Players Badges tab | Y | N | Y |  |
| **ProjM** | Projected Margin | Team & League | War Room matchup sim — shown as prose 'Projected margin/score/spread', not the abbr or full name | Y | N | Y |  |
| **HoopWAR** ✦ | Wins Above Replacement | Advanced | War Room, player_card, Hall of Fame — shown as 'WAR' | Y | Y | Y |  |
| **RAPM** ✦ | Regularized Adjusted +/- | Advanced | War Room/Team Dashboard/player_card | N | Y | Y |  |
| **ORAPM** ✦ | Offensive RAPM | Advanced | player_card impact panel | Y | N | Y |  |
| **DRAPM** ✦ | Defensive RAPM | Advanced | player_card impact panel | Y | N | Y |  |
| **WPA** ✦ | Win Probability Added | Advanced | Team Dashboard 'Win Probability Added (WPA)' section | Y | N | Y |  |
| **Clutch WPA** ✦ | Clutch WPA | Advanced | player_card clutch panel | Y | N | Y |  |
| **Leverage** ✦ | Leverage Index | Advanced | Officials glossary_key list (officials sense) — DUPLICATE ABBR, see Finding G-1 | N | N | Y |  |
| **Unit Net** | Lineup Net Rating | Possession & Pace | War Room Lineups view | Y | N | Y |  |
| **Title Odds** | Championship Odds | Team & League | War Room Sims view | Y | N | Y |  |
| **Exp. Wins** ✦ | Expected Wins | Team & League | War Room Sims view | Y | N | Y |  |
| **Poss WPA** ✦ | Possession WPA | Advanced | shown split as 'Off WPA'/'Def WPA' columns (Team Dashboard, player_edge) — combined name itself never appears | Y | N | Y |  |
| **EP** | Expected Points / Possession | Possession & Pace | used inside Poss WPA's own text; not its own labeled column | N | N | Y |  |
| **Pair Net** ✦ | Chemistry (Pair Net) | Possession & Pace | War Room 'Chemistry' network view | Y | N | Y |  |
| **Tracked** | Tracked vs box score | Box Score | Team Dashboard/pages — the Free/Paid gate copy throughout | N | N | Y |  |
### 2.2 Shown but NOT in `STAT_DEFS` at all (not in the 121-row table above)

These are real, on-screen columns/labels with zero glossary presence under any spelling — ranked
by how likely a coach is to misread or be stuck, highest first.

| Rank | Label(s) on screen | Where | Why it's risky |
|---|---|---|---|
| 1 | **`SCE` (team)** | Rankings full team stat table | Not just undefined — actively primed to be misread as the Players page's "Self-Creation %" (Finding G-2). |
| 2 | **`Rating`, `RatingPts`** | Rankings "Tracked ratings" grid, right beside the glossary-defined `Power` | Three different numbers answer "how good is this team" (Power 0-100, Rating ~raw scale, RatingPts ~points/game scale) and only one is explained. No `help=`, no glossary row, no caption mention. A coach has no way to know these are the SAME underlying strength estimate at different scales rather than three independent readings. |
| 3 | **`ClassAdj`** | Rankings "Tracked ratings" + "Full team stat table" | A signed adjustment baked into `Rating`/`Power` for level of competition (the "class bridge" — that phrase exists only as a code comment in `team_ratings.py:372`, never in the UI). No `help=` anywhere, no caption, no glossary row. A coach sees e.g. `-1.35` with no unit, no sign convention, nothing. |
| 4 | **Officials `Rating`** | Officials leaderboard | Confirmed to BE `OffRating` (the glossary does define `OffRating`), but the column header is the bare, generic word "Rating" — the least distinctive possible label, and coincidentally the same literal word used for the unrelated team `Rating` above. Two "Rating" columns, two different apps-within-the-app, two different formulas, one glossary entry (`OffRating`) that neither column is spelled to match. |
| 5 | **`SOR`** (Strength of Record) | Rankings "Compare" leaders + one grid (has a good native `help=` there) AND the "Tracked ratings" grid (no `help=` there) | Inconsistent, not absent — well-explained in one table on the page, silent in another table of the *same metric* one scroll away. No glossary row either way, so the Glossary tab can't backstop the gap. |
| 6 | **`AST-xA`** | Players full player_stat_table output (feeds scout/profile reads) | The concept is explained, but only in prose *inside the `xA` glossary card* ("AST − xA is the finishing luck…") — a coach who lands on a raw `AST-xA` number without having first opened the `xA` card has no path to the explanation; the column itself has no independent hook. |
| 7 | **`Forced TOV%`** | Rankings full team stat table | Same family as the well-defined, offense-framed `TOV%` ("lower is better"), but this is its defensive mirror where HIGHER is better — a same-family sign flip with no glossary entry to catch it (the user's own "second quantity catches inverted verdicts" heuristic applies directly here: nothing cross-checks the direction). |
| 8 | **`SelfCr%`** | Players scout/shot-profile tables | This is the metric the glossary's own `SCE` card is trying to describe, under a key `stat_help("SCE")` will never find because the real column is spelled differently. |
| 9 | **`Off WPA` / `Def WPA`** | Team Dashboard WPA section, `player_edge.py` leaders | Halves of the glossary-defined `Poss WPA`; shown only under the split labels, which don't literal-match the glossary row a search would need to land on (substring search for "off wpa" does not hit the "Poss WPA" card's text either). |
| 10 | **`10-0 runs/G`, `10-0 allowed/G`, `Biggest run`** | Rankings full team stat table | Self-evident basketball language (lower risk of misreading) but a real, non-trivial engine (`helpers/runs.py`, garbage-time excluded) with zero definition anywhere — a coach can't tell if "2.3 runs/G" is high or low league-wide. |
| 11 | **`MOV`** | Rankings leader cards (spelled out as "Point margin" there — good) and one grid with a native `help=` | Lower risk than it looks: every instance I found either spells it out in English or carries a tooltip. Included for completeness, not as a live gap. |
| 12 | **`Share σ`** | Officials leaderboard | Has its own inline caption text right on the page (verified: *"Share σ is how far this ref's slice of a game's live calls sat…"*), so it is NOT silently unexplained — but it stands in for the glossary-defined `Call %` under a transformed (z-scored) and unrelated-looking name, so the Glossary tab's search can't find it and a coach can't connect the two. |

### 2.3 Measured ranges vs stated ranges (the "measure before you claim" checks)

Ran the actual engines against the snapshot rather than trusting the glossary prose:

- **`Shot Rating` — mismatch, confirmed.** Glossary: *"Anchors: 50 = sample-average shot, 100 =
  contested self-created three."* Measured on the girls pool (`player_stat_table`, n=202 players
  with FGA>0): **median 59.2, mean 57.5**, not 50. The book's actual league FG% is **34.7%** (3,246
  FGA), and Shot Rating's own formula is difficulty = 1 − bucket make-rate, so the shot-weighted
  "sample-average shot" implied by this book's real shooting is **~65**, not 50 — the "50" anchor
  silently assumes a 50%-league-FG% baseline that doesn't hold at the HS level. Every player's
  Shot Rating on screen is being read against a stated average that sits 7-15 points below the
  book's actual center.
- **`VPS` — mismatch, confirmed.** Glossary: *"~1.0 breaks even, 2+ is excellent."* Measured
  (n=220): median **0.67**, mean 0.75, p75 = **1.00**, p90 = 1.50, max 4.5. The stated "breakeven"
  point is actually the **75th percentile** in this pool — most players are, by the glossary's own
  framing, "underwater," which the "breaks even" language does not prepare a coach for.
- **`AST/TOV` (glossary `AST/TO`) — no range stated, and a naive guess would be badly wrong.**
  Measured (n=198): median **0.30**, mean 0.53, p90 = 1.20, max 6.0. The glossary gives only
  ">2.0 is excellent" (confirmed genuinely rare here — above p90) with no typical value; a coach
  who assumes "around 1.0 is normal" for a ratio stat would overshoot the real median by 3x.
- **`OVERALL` — matches reasonably well (a positive control).** Glossary: "70+ elite, 62+ great,
  54+ above average, ~50 average." Measured (n=242): mean 50.9 (≈50 ), p75 = 54.1 (≈ the "above
  average" line), p90 = 59.2, max = 83.7 (comfortably clears "70+ elite" only at the very top of
  the pool, as "elite" should). Included to show the audit isn't finding mismatches everywhere —
  this is the one headline number that is calibrated about as advertised.
- **Percentile granularity — boys pool.** `cards.pctile` against `tracked_ratings(gender="M")`
  (5 teams) returns **exactly {10, 30, 50, 70, 90}** with no ties present — confirmed by direct
  call, not assumed. `pctile_bar()` — the shared widget used on player cards, team cards, Rankings
  Compare, the Officials/Defense/Playstyle tabs and both Insights decks (13 call sites found) —
  takes `(label, value_str, p)` with **no pool-size parameter at all**, so a 90th-percentile bar
  built from 5 boys teams renders pixel-identical to one built from 242 girls players or a
  748-team results-only pool. This is the single most-reused explanation widget in the app and it
  cannot express the one fact (`n`) that would let a coach calibrate how much to trust it.

### 2.4 Defined but never shown

Verified by grepping every one of the 120 abbreviations against `pages/*.py`, `helpers/*.py` and
`helpers/dashboard/*.py`, then hand-checking every zero/low-hit candidate (a raw text-presence
grep alone is unreliable — it can't tell a real column from a docstring, and every abbreviation
turned up *somewhere* in the source once comments/docstrings count). After hand-verification, the
list is short — most "zero hit" candidates turned out to be cosmetic label drift (§2.2/§3), not
true absence:

- **`AdjDFG%` and `DFGoe`** — genuinely never surfaced as their own column or number anywhere in
  `pages/` or `helpers/dashboard/`. Both are fully computed in `helpers/player_ratings.py` (shooter
  -adjusted contest rate and its raw over/under-expected form) and both explicitly **feed the
  DEFENSE 0-100 rating** — the glossary says as much ("the contest leaf the DEFENSE rating uses").
  A coach can watch a player's DEFENSE rating move and never see the one input the glossary itself
  points to as the reason. This is the cleanest true "defined but never shown" gap found — the
  data exists, is gated correctly (None below volume), and simply has no on-screen home.
- **`MtchDiff`** — computed (`helpers/matchups.py:126`) and consulted by `helpers/insights.py` to
  write a plain-language sentence in Insights, but the 0-100 index itself is never printed as a
  labeled number anywhere — only paraphrased into prose. Milder than the above (the coach still
  gets the finding, just not the underlying figure), and arguably a defensible design choice
  rather than a gap.
- **`ProjM`** — the concept (opponent-adjusted predicted margin) is well covered in the War Room
  matchup simulator, but always in plain English ("Projected score," "the spread") rather than
  under this name or abbreviation. The glossary card is close to redundant here since the live
  page already explains the concept better than a static card could; low priority.

Everything else nominally "defined but not shown" resolved to a label-drift case already counted
in §2.2/§3, not a true gap: `AdjeFG%`→shown as "Adj eFG%", `TRB%`→shown as "REB%", `Paint PTS`→
shown as "PaintPTS"/"Paint/G", `Call %`→stands in for as "Share σ", `Poss WPA`→split into
"Off WPA"/"Def WPA", `WinProb`→shown spelled out as "Win Probability", `Play Type`→shown in
`helpers/box_score.py` and the team scheme tab.

### 2.5 Defined badly (formula restatement, not an interpretation)

Reading every row for whether it explains itself or just restates its own math:

1. **`SCE` (Finding G-2, §0)** — not badly worded, but two different formulas share one card
   identity across contexts. The worst "defined badly" case in the app precisely because the
   *prose itself* reads fine in isolation — the failure is architectural (one abbreviation, two
   engines), not editorial.
2. **`Leverage` (Finding G-1, §0)** — same shape: two good, clear definitions, sharing a lookup
   key that guarantees one shadows the other.
3. **`Call %`** — the one row with a **completely empty "how to read it" field** (verified
   programmatically — the only true 0-byte case among 121 rows). Definition: "Share of the whistle
   an official accounts for in their games." No direction, no range, no so-what at all; contrast
   with every other Officiating row, which all carry at least a one-line read.
4. **`RatingPts`/`Rating` are not in the glossary at all** (see §2.2 #2) but functionally they ARE
   restatements of `Power` at a different scale with zero added interpretation anywhere on
   screen — the "defined badly" failure here is that the *good* definition (`Power`'s) doesn't
   mention its two undocumented siblings exist, so a coach cannot even use Power's card to
   understand Rating/RatingPts by analogy.
5. **A softer pattern, not a single row:** several Advanced/officiating formulas are given as
   pure math with a one-line gloss that doesn't really teach intuition — e.g. `sTS%` ("Stabilized
   rate") and `EP` ("Expected Points/Possession") are accurate but read as a data engineer's
   explanation of the mechanism rather than a coach's "why do I care." These aren't wrong, just
   thin on the "so what" the task is checking for; they're the tail of the 37-row "no directional
   keyword" mechanical scan in §2.1, most of which (unlike `Call %`) are fine on inspection —
   context-only stats like `MIN`/`POSS`/`EP` correctly have no "good/bad" direction because they
   aren't verdicts, they're denominators.

## 3. The Glossary view as a product

Read `render_glossary` + `glossary_tab` in full (`helpers/glossary.py:664-725`). What it actually
is: a flat list of 121 HTML "cards" (`_card_html`), each showing category tag, abbreviation, full
name, plain-English definition, formula (if any) and the "how to read it" line — rendered into a
2-column `st.columns(2)` grid, gated by one text-input (substring search over
abbr+name+cat+definition+good, case-insensitive) and one multiselect (the 11 STAT_DEFS categories
plus a synthetic "✦ Signature (invented)" pseudo-category). Wrapped in `@st.fragment` so a
keystroke only reruns the glossary, not the host page — a real and correct performance fix for
the *interaction* cost. It does **not** fix the *initial-paint* cost: with no filter applied (the
default state every time a coach opens the tab) it builds and ships all 121 cards — the ~105k
characters cited in the brief — every single time, on **five separate pages**
(`pages/5_Rankings.py:3436`, `6_Team_Dashboard.py:6453`, `7_Players.py:1894`, `8_Officials.py:926`,
`9_War_Room.py:1974`), identically, with the same intro caption, the same 121 cards, the same
default "no filter" state.

**Is it navigable?** Only by scrolling — 121 cards in 2 columns is ~60 rows deep with no anchor
links, no sticky category rail, no jump-to-letter, no "back to top." The only navigation primitive
is the category multiselect, which requires already knowing which of the 11 code-taxonomy buckets
a stat lives in.

**Is it searchable?** Yes, but narrowly: literal substring match, no fuzzy/typo tolerance, no
synonym or alias table. Given §2's finding that on-screen labels routinely drift from the glossary
abbreviation (`Adj eFG%` vs `AdjeFG%`, `REB%` vs `TRB%`, `Share σ` vs `Call %`, `Off WPA`/`Def WPA`
vs `Poss WPA`, bare `Rating` vs `OffRating`), a coach who searches for **exactly the string she
sees on her own screen** will regularly get zero results for a stat that IS defined — the search
box's honesty is undercut by the rest of the app not using consistent labels.

**Is it organized by the question a coach asks, or by how the code is organized?** By the code.
The 11 categories (Box Score, Shooting, Playmaking, Rebounding, Defense, Possession & Pace,
Advanced, Shot Quality, Ratings, Team & League, Officiating) are a reasonable *taxonomy* but not a
*question order* — "Advanced" alone holds 22 unrelated things (Game Score, WAR, RAPM, WPA, GEI,
officiating leverage, stabilization math) because they're all "not box score," not because a coach
asks one question that spans them. Contrast with the Insights benchmark (§4), which is organized
entirely around the questions a coach actually has ("what decided this game," "who should play
more"), never around which engine module produced the number. The Glossary is the one surface in
the app that never got that treatment.

**A gap the layout can't fix by itself:** the glossary has no entry, anywhere, explaining what a
confidence dot means, what "SB" (Spearman-Brown) is, or how to read the inline `r=0.XX` reliability
captions that Insights Deep prints next to real numbers (`helpers/dashboard/insights_deep.py:211`
-`388`). The one system in the app most responsible for telling a coach when NOT to trust a number
(`helpers/cards.conf_dot`/`conf_dot_r`, `helpers/reliability.MEASURED`) is undocumented in the one
place built to document every number.

### Proposed concrete layout

1. **Default to page-relevant, not everything.** `render_glossary(categories=...)` already accepts
   a category subset — `glossary_tab` just never uses it (`categories=None` always, by explicit
   design, "no per-page category subset"). Flip the default: each embed passes its page's relevant
   categories (Officials → Officiating + the Advanced officiating rows; Players → everything except
   Officiating; War Room → Advanced + Possession & Pace + Ratings + Team & League) with a single
   visible **"Show every stat in the app"** toggle to escape it. Same data, same component, same
   consistency goal — just don't make a coach on the Officials page wade past 16 Shooting cards to
   find `FPG`. This is a same-file, low-risk change (the parameter already exists).
2. **Re-cut the top-level grouping around coach questions, keep the code taxonomy as a secondary
   filter.** e.g. *How good are we (team)? · How good is this player? · Are we scoring well? ·
   Can we defend? · Who takes care of the ball? · Who should play, and when? · Is the whistle fair?
   · Can I trust this number?* — eight question-groups instead of eleven code categories; a stat
   can be tagged into one primary group without touching its existing `Category` field (add a
   `group` as an 8th tuple element, or a lookup dict keyed by abbr, so the change is additive and
   doesn't disturb the existing category filter anyone already relies on).
3. **Add the missing "Can I trust this number?" group** — a handful of new cards explaining
   `conf_dot`/`conf_dot_r`, what filled vs hollow dots mean, and in plain language what "SB .11"
   vs "SB .81" means for a coach (the reliability module's own docstrings in `helpers/reliability.py`
   already contain publication-quality plain-English explanations — e.g. the rim-FG%-is-noise
   paragraph — that just need to be lifted into 3-4 STAT_DEFS-shaped rows). This is the single
   highest-leverage content addition available, because it would explain the mechanism behind
   dots that already appear on screen in 8+ places (§5) rather than adding a 122nd disconnected fact.
4. **Fix search-by-what-you-see.** Add an `aliases` field (or a small `DISPLAY_ALIASES` dict) so
   `SelfCr%`, `Adj eFG%`, `REB%`, `Off WPA`/`Def WPA`, bare officials `Rating`, and `Share σ` all
   resolve to their real card. Cheap (a dict lookup folded into `_match`'s haystack) and it directly
   fixes the most concrete, reproducible failure mode found in this audit.
5. **A sticky category rail or anchor jump** for the "show everything" state, so the 121-card wall
   is at least skimmable without a scrollbar-only crawl.

## 4. In-context explanation: the Insights benchmark vs the rest of the app

### The benchmark

Read `helpers/dashboard/insights_tab.py` (1,591 lines) and `insights_deck.py` (453 lines) in full.
The design is genuinely disciplined, not just well-intentioned:

- **Everything reconciles to a currency a coach already has: points per game.**
  `deserved.py` splits every game's final margin into four terms (extra shots, selection,
  shot-making, free throws) that sum EXACTLY to the real margin, and `insights_severity.py` converts
  every one of 39 different z-scored generators into an honest `≈ +2.3 pts/g` conversion so findings
  from unrelated engines can be ranked on one scale. This is the single biggest reason Insights reads
  as coaching advice instead of a stats dump: the currency conversion IS the explanation.
- **THE FIVE is a ranked spotlight, never a filter** (`the_five()`,
  `insights_deck.py:359`) — explicit design rule: "a coach who cannot tell a spotlight from a
  truncation has to assume the page is hiding things," so the full uncapped list still renders in
  its section every time. Severity = points at stake × measured reliability × sample — i.e. §5's
  confidence system is load-bearing in the ranking logic, not decoration.
- **`scope_note()`** (`insights_deck.py:255`) is a reusable primitive whose entire job is printing
  "N of M tracked games — every number below is recomputed over this window" so a coach can't
  mistake a narrowed view for the whole season.
- **`insights_brief.block(title, *, rows=None, lines=None, n=None, tone=None)`** — the shared
  section-header primitive — takes `n` as a first-class parameter. Sample size isn't bolted on;
  it's part of the primitive's signature.
- Counter-intuitive results get a sentence, not just a number: the suppressor caveat
  (`insights_deck.py:333`) explicitly calls out fouls-drawn-late looking statistically backwards
  ("fits POSITIVE but correlates NEGATIVE... game state, not a real inversion") rather than letting
  a coach discover the contradiction and lose trust in the page.

### The rest of the app, by contrast

The good news first: general captioning discipline is **strong** app-wide. Sampling
`pages/9_War_Room.py` (69 `st.caption` calls across ~1,800 lines) and `pages/7_Players.py`
(30+ captions) shows nearly every section/table/chart has SOME adjacent framing text — this audit
did not find whole blocks of raw numbers dropped on screen with zero surrounding prose. That
initial hypothesis (going in) turned out to be largely wrong for this codebase; worth stating
plainly rather than manufacturing a gap that isn't really there.

The real gap is narrower and matches §2 precisely: **a caption explains the table, not every
column in it.** Two concrete examples, both already detailed in §2:

- Rankings "Tracked ratings" grid (`pages/5_Rankings.py:1645-1704`) carries a real, substantive
  caption — opponent-adjustment, AdjeFG, Pace are all explained — right above a table that ALSO
  contains `Rating`, `RatingPts`, `SOR` and `ClassAdj` with no mention in that caption and no
  per-column `help=`. The caption creates a false sense that the whole table has been explained.
- Players "Full stat table" (`pages/7_Players.py:779-825`) gets one header and one trailing
  caption ("every column defined in the Glossary tab") for a 29-visible/196-underlying-column grid —
  a reasonable division of labor IF the Glossary tab actually covered every column under the label
  shown (§2/§3 shows it often doesn't).

So the honest framing: this app does not have an "explanation-free zone" problem at the
page/section level — it has a **column-level long tail** problem, concentrated in the same handful
of team-strength and officiating numbers already flagged in §2 (`Rating`/`RatingPts`/`ClassAdj`/
`SOR`/bare officials `Rating`), plus the systemic gap of the Glossary tab (§3) not being kept in
sync with the labels the captions point at.

**One clear positive worth calling out on its own:** `helpers/dashboard/player_card.py:1073-1077`
prints the Wilson 95% confidence interval directly inline with the shooting line —
`FGM/FGA (FG%)` followed by the CI in the same string — so a coach reading a player's card sees
the shooting percentage AND its honest uncertainty band in one place, no separate lookup required.
This is exactly the pattern the rest of the app under-uses (see §5).

## 5. Confidence and sample

`helpers/cards.py` ships **three** confidence primitives, of increasing sophistication:
`conf_dot(n, k, sig)` (volume vs a shrinkage prior), `conf_dot_r(sb, metric)` (measured
split-half reliability, reading `helpers/reliability.MEASURED`), and `stat_kpi(...)` (a full
headline tile bundling value + tier colour + percentile bar + confidence dot in one call — the
stated fix for "every st.metric looks the same"). Usage counts across the whole app
(`pages/` + `helpers/`):

| Primitive | Call sites found | Files |
|---|---|---|
| `conf_dot(` | 8 | Rankings, Officials, War Room, `cards.py` itself, `insights_tab.py`, `player_card.py` |
| `conf_dot_r(` | 13 | `cards.py` itself, `insights_deep.py`, `shot_diet.py` **only** |
| `stat_kpi(` | 1 (its own definition) | nowhere else — **dead code** |

`helpers/reliability.py` (read in full) is the best-documented module in the codebase — it states
its own methodology (200 random half-splits, Spearman-Brown correction) and is refreshingly candid
about bad news: rim FG%, the shot chart read a coach most wants, measures **SB .06-.11** (doesn't
predict itself), while the coarser 4ft-to-arc band reaches .52-.65 and pure shot/attempt **shares**
(not rates) are reliable everywhere (.70-.92). Two case studies worth recording:

- **The raw offensive on/off split was the single most-fired card in the app** (37 of 242 players)
  and measured **SB = −0.096 to −0.213** — it doesn't even predict itself. The codebase's own
  response (`helpers/insights.py:911-940`, `_g_onoff`) is a genuine positive: the card was rewired
  to fire ONLY when the adjusted RAPM estimate agrees in sign with the raw split, and the text now
  leads with the adjusted number. This is the system working as designed — a clean example to
  point to when arguing the reliability-gating pattern is worth extending elsewhere.
- **Team per-band shooting (e.g. "this team shoots 61% from the 4-10ft floater area") is
  deliberately left OUT of `MEASURED`** rather than assigned a number — measured at SB −.12 to .10
  on 5-6 teams, which the module's author judged too few units for a split-half r to mean anything
  in either direction. `conf_dot_r` renders this as "unmeasured" (reuses the weak/hollow dot,
  never a confident one) specifically so absence-of-measurement never reads as absence-of-caveat.
  Careful, correct design.

### Where the confidence system does NOT reach (ranked, worst risk first)

1. **`cards.pctile_bar(label, value_str, p)` — the app's most-reused explanation widget (13+ call
   sites: player cards, team cards, Rankings Compare, Defense/Playstyle tabs, both Insights decks)
   — has no `n` parameter at all.** A 90th-percentile bar built from the boys pool's 5 tracked
   teams (percentiles land on exactly {10,30,50,70,90} — confirmed by direct call, §2.3) renders
   pixel-identical to one built from 242 girls players or a 748-team results-only pool. This is
   the single highest-leverage fix available: one function signature, dozens of call sites inherit
   it for free. `reliability.MEASURED` has no entry for "percentile pool size" because that's a
   structural property of the widget, not a per-metric reliability question — a `n` parameter is
   the fix, not a new MEASURED row.
2. **Shooting-rate leaderboards gate entry by a minimum volume, then show the winning number with
   no visible n.** Verified directly: `pages/7_Players.py:160` gates the DSHOT% leaderboard at
   `defFGA >= 10`, but `_leader_bar()` (`pages/7_Players.py:247`) renders only player name, team
   and the formatted percentage — the qualifying volume (which could be exactly 10-14 shots) never
   reaches the bar or its hover text. `MEASURED` has no direct DSHOT%/defender-FG% entry, but the
   closest analog, `("defender","allowed_fg")`, is only **0.399** — real but well short of
   "stable." Same shape for the `USG%` (MIN≥20) and `TOV%` (FGA≥10) leaderboards in the same table.
3. **Shot-location rate stats on the main Players/scout tables** (`RimDFG%`, `PerimDFG%`,
   `Dom_FG%`, `Weak_FG%`, `Near_FG%`, `Deep_FG%`) are exactly the metric family `reliability.py`
   proves is the LEAST trustworthy in the whole book (rim FG% SB .06-.11 — worse than everything
   else measured). `conf_dot_r` **is** wired to this family, but only inside
   `helpers/dashboard/shot_diet.py:248` and `insights_deep.py` — the same numbers reappear as bare
   percentages on the Players page's own zone tables and player-card shot splits without it.
4. **`RimProt`/`PerimD`** (Defense category) are correctly gated to `None` below 8 shots defended
   (`helpers/stats.py:2500`, `rim_perimeter_defense`, `min_shots=8`) — a real, good design — but
   once a player clears 8 they show a bare percentage-point number on the main table; the actual
   volume lives in a SEPARATE column (`RimDShots`/`PerimDShots`) a coach has to go find and
   mentally join. No `MEASURED` entry names `RimProt`/`PerimD` directly, though the underlying
   family (contested-shot rates) is the one this module warns about hardest.
5. **~25 other percentage columns** (`AdjDFG%`, `AST%`, `TOV%`, `USG%`, `OREB%`, `DREB%`, `REB%`,
   `Guarded%`, `ClutchFT%`, `ScrnFG%`, `SCPass%`, `SCShot%`, `SCCreated%`, `SelfCr%`, `Astd%`,
   `PassFG%`, `PassxFG%`, `PassOpen%`, `Q4%`…) get **none** of the three confidence treatments
   found elsewhere in the app — no Wilson CI (that treatment is confirmed wired to exactly `FG%`,
   `3P%`, `FT%` inside `player_card.py:1073-1077`, and nowhere else), no `conf_dot`, no
   `conf_dot_r`. `MEASURED` has no entries for most of these by name, which itself is a finding —
   the reliability program covered shot-location and playtype axes thoroughly but never
   systematically extended to the rest of the rate-stat surface.
6. **`stat_kpi()` — the primitive purpose-built to solve exactly this problem — is unused.** It
   bundles tier colour, percentile bar and confidence dot in one call and has zero call sites
   outside its own definition. Whatever blocked its adoption (a rewrite that predates it, or simply
   nobody wiring it in yet) is worth a look, because the infrastructure to fix a meaningful slice
   of #5 already exists and is sitting idle.

**The positive counter-example, for calibration:** `player_card.py`'s headline shooting line
(`FGM/FGA (FG%) [95% CI]`) shows exactly the discipline missing above — value, sample, and honest
uncertainty in one glance, no separate lookup. It proves the team already knows how to do this;
the gap is breadth of adoption, not know-how.

## 6. The FAQ

Read `pages/15_FAQ.py` (79 lines) and `docs/faq_source.txt` (564 lines) in full. Mechanically the
page is simple and sound: it pulls a plain-text export of the founder's Google Doc on a 6h TTL
(`helpers/faq.py`), caches it in `app_settings`, parses heading-ish lines into
(question, answer) `st.expander` sections, and serves the last-good copy with a visible "stale"
banner on fetch failure. **Caveat on this section:** the live source of truth is the Google Doc
itself, fetched at runtime — `docs/faq_source.txt` is a checked-in snapshot, and this audit (static,
no network fetch of the Doc) can only speak to that snapshot. It could be behind the live Doc.

**What it gets right, already:** the 28-section table of contents is organized by coach question,
not by app module (`How To Read Any Number Here`, `Three Levels Of Data`, `Current Seasons`,
`Why Numbers Change`, `Opponent Adjustment`, `Officials`, `Rankings And The League Pool`…) — this
is the layout §3 recommends for the Glossary itself, already realized here. Specifically, every
item the task brief asks about IS present in the snapshot:

- **Tracked vs box-only** — "Three Levels Of Data" spells out exactly what each of final-score-only
  / hand-entered-box / play-by-play-tracked unlocks, plus "Tracked always wins" (a tracked game
  overrides a hand-entered one for the same matchup).
- **What Paid gets you** — "Current Seasons" gives a literal bullet list per tier (Free: box +
  free ratings + one free tracked game; Paid: tracked data, Event Editor, Officials, War Room;
  Co-Op: full pool access) plus the blunt line "Box scores and final results are visible to every
  coach at every tier, always. The tier decides how deep you see, never whose data you are allowed
  to look at" — a clean, memorable answer.
- **What the Coaches' Co-Op is** — covered in the same section: reciprocal, program-level (one
  coach opting in brings the whole staff), "share to scout," a non-participating program "reads as
  neutral to everyone else." Matches the engine-level gate this app treats as load-bearing.
- **How to read the 0-100 ratings** — the "Four rules" up top (Fifty is average · Ratings are
  relative · Small samples get pulled toward average · Sample size is printed) is a genuinely
  excellent compression of the whole explanation layer into four sentences, and "Ratings vs
  Impact" / "How A Rating Gets Built" / "Shrinkage And Sample Size" go deeper for a coach who wants
  it.
- **Why a number moved with nobody playing** — "Why Numbers Change" gives three honest reasons
  (pool moved under you, opponent adjustment reaching backward, a re-tuned constant that passed a
  walk-forward backtest) — this is the rare FAQ answer that would actually stop a confused-coach
  support message before it's sent.

**What's missing or stale, found by direct search of the snapshot:**

- **"Why does this disagree with MaxPreps?" has no answer.** The string "MaxPreps" does not appear
  anywhere in the 564-line snapshot. "Why Numbers Change" answers why an APP5 number moves over
  time, but nothing addresses why an APP5 number might differ from an external site's for the same
  game/player right now (duplicate-game collapsing picking one coach's log over another's, minutes
  being estimated from possession seconds rather than a stat book, a turnover-kind reclass, etc. —
  all of which the FAQ already explains as INTERNAL mechanics, just never connects to the external
  question a parent or coach is actually asking). Genuinely the single most likely unanswered
  question for a coach fielding "why doesn't this match what I saw on MaxPreps" from a parent.
- **The Glossary section's own worked example is broken.** Its "a few worth looking up first" list
  names `PRF`, `SC-Pass`, `DSHOT%` and `Adjusted eFG` as good starting searches. `PRF`, `DSHOT%`
  and `Adjusted eFG%` all resolve fine (the last via substring match despite the missing `%`).
  **`SC-Pass` does not exist anywhere in `STAT_DEFS` under that spelling** — confirmed by grep of
  `helpers/glossary.py` — nor does the internal engine field it's presumably describing
  (`b["SC_pass"]`, which surfaces on screen as `PotAST`). A coach who follows the FAQ's own advice
  and searches the in-app Glossary for "SC-Pass" gets zero results for a term the FAQ told them to
  try first. Cheap fix: change the FAQ prose to "PotAST" (or add an alias per the §3 proposal).
- No section explains what a **confidence dot** or the reliability language (`SB`, "directional,"
  "stable") means, even though "Sample size is printed" (one of the FOUR headline rules) promises
  exactly that: *"Confidence dots mark how firmly a number is backed."* The promise is made on
  line 35 of the source and never cashed — matches the §3 gap precisely (the glossary doesn't
  explain the dots either), so a coach who reads the FAQ's own top-billed rule has nowhere in the
  app that actually teaches the dot vocabulary it just told them to trust.
- Nothing in the snapshot references "Analytics Hub," "Charts," or any other page name inconsistent
  with the current build — the recent renames (Analytics Hub → Rankings/Spotlight, per the repo's
  own recent commits) do not appear to have left stale FAQ prose behind, at least not in this
  snapshot. One clean bill of health worth stating so this section isn't read as all criticism.

## 7. Ranked action list (effort: XS < 1hr, S ~ half day, M ~ 1-2 days, L ~ multi-day/research)

1. **[XS] Rename the duplicate `"Leverage"` abbreviation** (`helpers/glossary.py:491` or `:573`) —
   one string change removes a latent wrong-card-shown bug (Finding G-1).
2. **[S] Resolve the `SCE` collision** (Finding G-2) — rename the team table's `SCE`
   (`helpers/league_analytics.py:511`) to something that doesn't collide (e.g. reuse `ScEff`,
   which is already the correct, unambiguous glossary entry for this exact formula), and check
   `insights_team.py:137` and any CSV consumers for the key rename.
3. **[S] Add `help=` (or STAT_DEFS rows) for `Rating`, `RatingPts`, `ClassAdj`** on the Rankings
   "Tracked ratings" grid (`pages/5_Rankings.py:1645-1704`) — the highest-traffic page in the app
   showing three-numbers-that-answer-"how good"-with-one-explained. `SOR`'s existing help text
   from the Compare view (`pages/5_Rankings.py:1074-1077`) can be copied into the Tracked grid
   directly — it's already written, just not reused.
4. **[S] Add a `DISPLAY_ALIASES` lookup to `render_glossary`'s search** so `SelfCr%`, `Adj eFG%`,
   `REB%`, `Off WPA`/`Def WPA`, officials' bare `Rating`, and `Share σ` all resolve to their real
   card. Directly fixes the FAQ's own broken "SC-Pass" pointer too (§6) once PotAST/SC_pass is
   added as an alias.
5. **[S] Wire `render_glossary(categories=...)` per page** (`glossary_tab` call sites in
   `pages/5,6,7,8,9`) to default to that page's relevant categories with a "show every stat"
   escape toggle — the parameter already exists and is simply never used; cuts the ~105k-character
   unfiltered dump on first paint for 4 of 5 embeds.
6. **[S] Add 3-5 STAT_DEFS rows (or a dedicated FAQ section) explaining the confidence-dot /
   reliability vocabulary itself** — `helpers/reliability.py`'s own docstrings already contain
   the plain-English explanation (the rim-FG%-is-noise paragraph is publication-ready); it just
   needs to reach the Glossary and the FAQ's "sample size is printed" promise (§6) that currently
   points at nothing.
7. **[S] Surface `AdjDFG%`/`DFGoe` somewhere on screen** — computed, gated, and named by the
   glossary as "the contest leaf the DEFENSE rating uses," but never shown (§2.4). Add to an
   existing Players/Defense scout table rather than building a new surface.
8. **[S] Add qualifying-`n` to `_leader_bar` hover/label text** (`pages/7_Players.py:247`) — the
   volume gates already exist (`defFGA>=10`, `MIN>=20`, `FGA>=10`); they just aren't shown once a
   player clears them.
9. **[M] Add an `n` parameter to `cards.pctile_bar`** and thread it through its ~13 call sites
   (player cards, team cards, Rankings Compare, Defense/Playstyle tabs, both Insights decks) —
   the single highest-leverage confidence fix in the app because one signature change inherits
   everywhere. Even a minimal version (append "(n=5 teams)" to the label when pool < ~15) would
   catch the boys-pool-percentile problem the task brief opens with.
10. **[M] Extend `conf_dot_r` coverage from `shot_diet.py`/`insights_deep.py` to the Players page's
    own shot-zone tables and player-card location splits** — same SB .06-.52 numbers, currently
    shown bare in the wider-reach surface and dot-annotated only in the narrower one.
11. **[M] Decide `stat_kpi()`'s fate** — either wire it into a couple of the highest-traffic
    headline numbers it was built for (OVERALL on player_card, Power on team_card) or remove it;
    dead, well-designed code sitting unused is worth a deliberate call either way.
12. **[L] Re-cut the Glossary's top-level grouping around coach questions** (§3's 8-group
    proposal) rather than the 11 code-taxonomy categories — the Insights benchmark shows the team
    already knows how to do this; it just hasn't been applied to the Glossary itself.
13. **[L] Extend the reliability program (`helpers/reliability.MEASURED`) to the ~25 percentage
    columns it hasn't reached** (`AdjDFG%`, `AST%`, `TOV%`, `USG%`, `Guarded%`, `ClutchFT%`,
    the `SC*%` family, `Pass*%` family…) — a genuine measurement task (200 half-splits each, per
    the house rule), not a UI change; sequence it behind items 9-10 since those make the RESULT of
    a future measurement actually visible once it exists.
14. **[Not code] Two Google-Doc edits for the founder**, since `docs/faq_source.txt` is a synced
    snapshot, not the source: fix the "SC-Pass" glossary pointer, and add a "why doesn't this match
    MaxPreps" entry to the FAQ (§6) — both cheap, both real coach questions this audit found no
    answer for.

*(End of static audit. All measurements were run directly against the read-only snapshot at
`.../scratchpad/book/analytics.db` with the pinned Python 3.12 interpreter; no repo file was
edited, created, or deleted, and no Streamlit page was rendered.)*
