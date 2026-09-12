# Charts · Lab · the box score — the scrub, and what shipped

Written 2026-09-12 against `~/app5_prod/analytics.db` — production, pulled 09:23
the same morning (63 tracked games; 43 of them on the girls' book, 26 on team 1).
Every number below was measured by rendering the real page headlessly against
that copy, not by reading the source and estimating. The suites are green at
**492 pytest** and **106 `tracker/run_all.py`** (up from 104 — two new render
suites).

Three surfaces were named:

* **Team Dashboard → Charts** — 7 sections, 17 leaves
* **Team Dashboard → Lab** — 3 sections, one of them three switchers deep
* **The in-app box score** (`helpers/box_score.py`, 4 callers)

And so was the benchmark: *Insights is the standard; the player profile and the
scout sheet are right; Overview is good.* So this was not a taste exercise.
Those three surfaces already agree on a shape, and the job was to find where
these three do not follow it.

---

## 0 · The one sentence

**Insights, Scout and the player profile lead with a sentence and put the chart
underneath it. Charts, Lab and the box score led with the chart.**

Where they already led with a sentence — Stops, Trends, Scoring, Shot Profile,
Efficiency & DNA, Résumé & Form — they are as good as the benchmark. Where they
did not, a coach was handed the wall and asked to do the reading:

```
                    figures built on open     sentences over them
Charts / Quarters            38                        0
Charts / Trends              39                        1
Charts / Offense / Shooting  20                        1   (of its three tabs)
box score / Overview          3                        1   in an expander,
                                                           under five tiles
box score / Flow              7                        0
box score / Shooting         12                        0
box score / Quarters         16                        0
box score / Four Factors      1                        0
```

Everything below is a consequence of that, or a lie the navigation told on the
way there.

---

## 1 · What was wrong, and what it cost

### 1.1 · `st.tabs` in three places the page had already abandoned it

The Team Dashboard was converted off `st.tabs` months ago for two stated
reasons: **it executes every tab body on every rerun**, and **a tab cannot be
selected from session state**, so an Insights evidence jump can never name one.
Three sites never got the memo — and they were the biggest ones.

```
6_Team_Dashboard.py:2114   Charts ▸ Offense ▸ Shooting   3 bodies, 20 figures
6_Team_Dashboard.py:3431   Charts ▸ Quarters             4 bodies, 38 figures
```

Both were AST-swept for cross-body name leaks before conversion (the failure
mode is a `NameError` the first time a coach opens the section that was being
carried by a sibling's work). Both came back clean. `Lab ▸ Impact Lab` has two
more `st.tabs`, but they wrap dataframes over data already computed, so they
cost scroll and not CPU — left alone, on the record.

**Trends was worse than either and had no `st.tabs` at all.** It built
**39 figures in one scroll**, 34 of them one reference grid — a per-game line
for every stat in `PER_GAME_STAT_SPEC`. That grid is worth keeping; it is the
only place a coach can follow a single stat game by game. It is not what anyone
opens Trends to read.

### 1.2 · The tab about quarters did not say anything about the quarters

`helpers/quarters.py` has written the quarter axis as prose since 2026-09-07 —
which period decides the games, whether the halves disagree, which quarter this
team plays at a different tempo. One surface rendered it: Insights.

Charts → Quarters, whose entire subject is that axis, rendered 38 plots and not
one sentence. A coach reached a conclusion the app had already written by
reading the wall.

It also never disclosed what of that axis is real. `reliability.MEASURED` has
carried the answer since the same day:

```
("team", "quarter_pace")  +0.596   SHIPS
("team", "quarter_efg")   −0.135   REFUSED
("team", "quarter_tov")   +0.082   REFUSED
```

So "they shoot better in the second half" and "the fourth quarter is where they
give it away" — the two reads a coach most expects from that screen — were
measured on this book and refused. The screen said nothing either way.

### 1.3 · A caption that guessed where a measured number belongs

Charts → Offense → Scoring's "Scoring by possession length" panel closed with:

> *Transition looks are usually the most efficient.*

Folklore, printed in the exact place THE BOOK §8.4 is a whole section about.
`helpers/shot_clock.py` measures this axis and the Insights deck already quotes
it. Measured on the girls' book, for team 1:

```
early (<7s)   31% of this offense   league 27%
league PPP    0.69 early   0.52 after      +0.18 a possession
mid vs late   0.019 apart — nothing after the knee differs
excluding transition   the team still opens 26% inside the knee
```

The last line is the one that matters: it is **half-court tempo, not fast
breaks**, which makes it coachable. And the numbers had to be computed rather
than quoted — `shot_clock.py`'s own docstring pools both genders and prices the
early band at +0.14, where the girls' book prices it at +0.18.

### 1.4 · "Advanced" named nothing

```
Lab → Advanced → Efficiency & DNA
             → Résumé & Form        ← a coach's own schedule résumé,
             → Game Flow              three switchers deep
    → Impact Lab
    → Build
```

"Advanced" was a folder over three unrelated tools, and the word promises
statistics to someone looking for their own quality wins. "Build" said even
less. And the cross-link that pointed at it —

> *Game-margin dot plot & home/away splits → **Lab → Advanced → Résumé & Form***
> `[Open Lab →]`

— landed on Lab's first section, because `_jump` could only name a VIEW. A jump
that lands two switchers short is a jump a coach stops using after the second
try.

### 1.5 · Banners that named the wrong tab

Every `# TAB n —` banner in the 6,800-line page was **one section out of step**,
sitting above the dispatch of the *previous* view, because the file renders out
of declaration order and the banners were never moved with the code:

```
#  TAB 7 — INSIGHTS
if _tdview == "Lab":            ← what is actually under it
```

Nine of them. THE BOOK §14 lists deleting them; naming them correctly keeps the
anchors and costs the same. The module docstring listed **five** views where
there are ten.

### 1.6 · The box score buried the box score

```
Overview · Flow · Shooting · Quarters · Lineups · Box Score · Four Factors · …
                                                  ^^^^^^^^^
```

Sixth, behind four analytics sections, in a thing called a box score — the one
artefact every coach already knows how to read, and the Free tier's whole
funnel, which renders it *first*.

Its only sentence — `postgame.game_report`, the best prose the app writes — sat
in an expander below five metric tiles, which is the exact shape Insights, the
scout sheet and the player profile were all moved *away* from. Five of the nine
sections had no read at all, while computing every number one needs:
`WP.summarize` has carried `winner`, `min_wp_winner`, `comeback` and
`avg_tension` since it was written and only the GEI tile ever touched them.

### 1.7 · Three honesty leaks, all of them B1's exact shape

* **Both ranked box-score tables printed a bare `Pct` column** under a caption
  reading *"Pct = league percentile"*. `playtypes.py` and `defenses.py` have
  carried `pool_n` on every row since the B1 pass; nothing here read it. A
  percentile over five tracked teams rendered identically to one over 748.
* **Play Style's "League context" table** did the same with a `Pctile` column —
  and that pool is smaller still, since only the teams that ran *that set* often
  enough qualify.
* **`postgame`'s only sentence about a person named a jersey number**:
  `Top game RATING — Reagan Langley (6.9), 25 (7.4)`. It read the raw `name`
  column instead of `stats.player_label`, on a book where 539 of 608 players
  have no name.

### 1.8 · Two charts whose caption described colours that were not on screen

The box score's Quarters section draws fourteen small charts with
`showlegend=False` on every one, under:

> *Every stat by period · Adair Girls (accent) vs Westville Girls (red).*

"accent" and "red" are the names of two *variables*, each holding a team's own
identity colour. On most games the caption described nothing a viewer could see.

### 1.9 · Four helpers that existed four times

`_md_bold` — `**x**` → `<b>x</b>`, two lines — was defined privately in
`insights_team_read`, `scheme_section`, `scout_deep` and `scout`, each docstring
pointing at another as the reason it matched. `_pctile_or_thin` was defined
twice, identically, in `playstyle_tab` and `defense_tab`.

(`scout.py`'s copy stays: it *escapes*, which makes it a different function, and
it is in the engine layer, which may not import a module that imports Streamlit.
Recorded so a future sweep does not "fix" it.)

### 1.10 · The league quality table, rebuilt per consumer

`lineups.unit_ratings` and `networks.chemistry_network` auto-fetch
`{pid: OVERALL}` when it is omitted, and that fetch is a full
`player_stat_table` over the league pool:

```
lineups.player_quality(43 games)        11.30 s
unit_ratings(team 1) WITH quality        0.32 s
unit_ratings(team 1) without             3.46 s   (after the table warmed)
```

`box_score.py` learned this in June and wrapped it in `cache_resource`. The Team
Dashboard never did, and every consumer here asks for the same league-wide
table.

---

## 2 · What shipped

Five commits on `main`, each green on both suites.

| commit | what |
|---|---|
| `12d0471` | **the quarter tab says what the quarters mean** — `st.tabs` → `_seg` on Quarters and Shooting; `helpers/dashboard/quarter_read.py` (one renderer, shared with Insights); `cards.md_bold`; `_jump` takes a subview path; nine banners and the docstring corrected |
| `92867c5` | **the possession-length panel stops guessing; Lab is one level** — the measured shot-clock read; Lab flattened to five named sections; every pointer at the old path followed; `_sub_seg` self-heals a stale session value |
| `cb839ee` | **the read leads, the box is second, every percentile says its pool** — box-score order, `postgame.game_report_lines`, the Free-stage read, `Pct` carries its pool, an Edge column, the Quarters colour key, `player_label` in `postgame` |
| `25c7ed3` | **Flow, Shooting and Four Factors say what they found** — three more box-score reads |
| `d0bf55f` | **one pctile helper, and the quality table is built once** — `cards.pctile_or_thin`; `_player_quality` cached |
| `9db874e` | **the shapes, locked** — two render suites, 108 checks |

### The two decisions worth knowing about

**Charts → Quarters now discloses its own reliability.** The verdict card is
followed, on every surface that renders it, by:

> *Tempo is the one quarter read that repeats (SB .596); quarter shooting
> (SB −.135) and quarter ball security (SB +.082) were measured and refused —
> see `reliability.THE QUARTER AXIS`.*

That sentence lives in `quarter_read.CAPTION`, in the shared renderer, precisely
so it cannot be true on the Insights screen and absent on the Charts one.

**The Free box score got a sentence, but not `postgame`'s.** `game_report`
prices the four-factors battle in TOV% and ORB%, which are possession math and
Paid under the owner's carve-out. Putting it on the Free stage would have
satisfied §12.1 and broken §12.2. `box_score._free_read` builds only from what
the Free box table already prints — the scoreboard, the line score, and
`FREE_BOX_COLS`:

> **the result** · Washington Girls won 66–33, in a rout.
> **shooting** · Washington Girls shot it better — eFG% 50% against 30% …
> **the margins** · Washington Girls won the glass by 12 and gave it away 10 fewer times.
> **the swing** · Q1 decided it — Washington Girls 26–2 Adair Girls, a 24-point period.
> **who** · Game high 21 — Reagan Langley.

Four tests hold that allowlist, including that the sentence never renders a
jersey number as a person's name.

---

## 3 · The numbers

### 3.1 · Figures built when a coach opens the section

| section | before | after |
|---|---:|---:|
| Charts ▸ Quarters | **38** | **6** (Scoring & Efficiency; 9 / 14 / 9 on the others) |
| Charts ▸ Trends | **39** | **5** (Form & splits; 34 behind "Every stat, game by game") |
| Charts ▸ Offense ▸ Shooting | **20** | **7** (Shot Profile; 5 / 8 on the others) |

### 3.2 · Cold render, production snapshot, this machine

Multiply by 2–3× for the droplet. Measured one fresh process per leaf, with
nothing else running.

| leaf | before | after |
|---|---:|---:|
| Charts ▸ Quarters | 18.9 s | **15.1 s** |
| Charts ▸ Offense ▸ Shooting | 19.0 s | **15.8 s** |
| Charts ▸ Offense ▸ Scoring | 16.8 s | **15.2 s** — and it now also runs the shot-clock read |
| Charts ▸ Defense ▸ Team Defense | 22.5 s | 20.8 s |
| Lab ▸ Impact Lab | 33.3 s | **25.9 s** |

**And the finding under all of them: there is a ~15-second floor, and it is not
Charts.** Profiled, it is the page's shared `team_bundle` →
`team_player_rows` → `player_ratings`, 9.2 s of one call, paid on every leaf of
every view. Leaf-level work is 0–13 s on top of that. *The next performance pass
on this page should aim at the bundle, not at the charts* — recorded here so
nobody spends another session shaving figures.

### 3.3 · The reliability numbers now on screen

| read | SB | shipped? |
|---|---:|---|
| quarter pace deviation | +0.596 | yes — and the card says so |
| quarter eFG deviation | −0.135 | refused, and the card says so |
| quarter TOV% deviation | +0.082 | refused, and the card says so |
| shot-clock early SHARE | +0.746 | yes — the read is the share |
| shot-clock early PPP | +0.800 | quoted as the league price |

---

## 4 · What I did not do, and why

* **The `st.tabs` inside Impact Lab** (Trios/Quads, Pairs/Trios/Quads). They
  wrap dataframes over data the section already computed, so they cost scroll,
  not CPU. Converting them is cosmetic.
* **A verdict on box-score Lineups.** Single-game five-man units; the section's
  own caption already says to read them directionally, and a verdict over six
  possessions would be an invented one. The test names this as a decision.
* **A verdict on Play Types / Defense.** Their KPI tiles (most used / best /
  worst, each with a sample gate) already do the reading. Same — on the record
  in the test.
* **Touching the Overview view.** It was offered as open to change and it did
  not come up: it leads with a verdict, it was the fastest view measured, and
  nothing in the scrub pointed at it.
* **Any constant.** `recal-round2` stands: nothing moves without its own gate.

---

## 5 · What is next on these three surfaces

Ranked, with the reason each waited.

1. **The `team_bundle` floor** (§3.2). ~9 s of `player_stat_table` on every
   view of every team. It is the largest single number on this page and it is
   not in any of the three surfaces scoped here, which is exactly why it should
   be its own session.
2. **Charts ▸ Defense ▸ Team Defense, 20.8 s cold** — the slowest Charts leaf
   after the floor is subtracted. Not profiled; worth one pass.
3. **THE BOOK §13.5, the Synergy framing** (frequency × efficiency on one line)
   and **§13.6, the defensive mirror**. Both are deferred past September in
   §16, both land on Charts ▸ Play Style and Charts ▸ Defense ▸ Scheme, and
   both are better designed after a season of a coach actually reaching for
   play-type reads.
4. **A `pool_n` audit of the remaining bare percentiles.** Two were found here
   by reading two files; a static sweep for `"pct"` rendered without a sibling
   `pool_n` would find the rest in an hour and could be a test.
