# Sweep — 2026-09-06 · Part 8: what to build next

The synthesis part. Parts 1–7 audited what is there; this is what is not, ranked
by coach value ÷ effort, with the measurement behind each one and — just as
important — **the ideas that were measured and failed**, so nobody spends a
session rediscovering that they do not work.

Everything here is measured against a `sqlite3.backup` copy of the live book.
**The live book was never written to.** No application code changed.

The rule this part follows is the house rule: *a read ships only if the
measurement behind it survives a second look.* Four candidates below did not, and
they are written up as fully as the ones that did.

---

## 0 · The shape of the opportunity

After seven parts, the pattern is consistent and it is not "compute more":

| where the wins are | count found | example |
|---|---|---|
| **an engine that is computed and never rendered** | 4 | `exploit`'s `their_leaks`, `situational.player_margin_scoring` |
| **an engine that is rendered on one axis and supports two** | 2 | `kind_by_shot_tag` hardcodes `"defense"`, never `"play_type"` |
| **a column that is captured and never bucketed** | 1 | `possession_secs`, on 100% of rows, read only as a mean |
| **a read that exists on one surface and belongs on four** | 2 | `postgame.game_report`, `team_insight_feed` |
| **a number that is right and unreadable** | many | percentiles over a 5-team pool; players named "12" |
| **genuinely new computation required** | 1 | the quarter generators |

Ten of the eleven highest-value items below are wiring, gating or labelling.
**One** requires new engine code.

---

## 1 · Build these — measured, gated, and not yet built

### 1.1 · Shot-clock state ★ the best unbuilt read in the app

`possession_secs` is non-NULL on 100% of `game_events` and is read in twelve
files — **only ever as a mean**. Bucketed into clock states over the honest
denominator (`event_type IN ('shot','turnover') AND possession_secs BETWEEN 1 AND
35`, n = 5,341):

| clock state | n | PPP |
|---|---:|---:|
| early (<7s) | 1,385 | **0.731** |
| mid (7–15s) | 2,213 | 0.570 |
| late (16–35s) | 1,755 | 0.597 |

**The middle of the shot clock is worse than the end of it.** That is not what
anyone expects, and it is the kind of read the Insights deck exists to deliver.

It survives both gates the house rules demand:

* **split-half** by alternating game date — early PPP 0.727 (n=737) against 0.735
  (n=648) on independent halves, the most stable number in the split;
* **the obvious confound** — excluding every `play_type='transition'` row, early
  is still 0.674 against mid 0.566 and late 0.597. Transition is 39.0% of early
  possessions, 21.5% of mid, 1.1% of late, so it is a real contributor and not
  the whole story.

**Build:** a `_t_clock` generator in `helpers/team_insights.py` on the
`_t_quarter` pattern, plus a `Clock` entry in `insights_severity.METRIC_SECTION`
(section: *Why we win / why we lose*) and `METRIC_EVIDENCE` (destination:
`("Charts", "Situational")`, which already owns possession-length charting).
One session. **Do this first.**

### 1.2 · The passing graph is one `continue` away

`helpers/passing_chains.py` is a complete, tested module that returns an empty
result on every call, because every entry point drops the row when the *hockey*
tag is NULL:

```
passing_chains.py:54    h = e.get("hockey_from_id");  if h is None: continue
passing_chains.py:318   if e["event_type"] != "shot" or e.get("hockey_from_id") is None: continue
```

`hockey_from_id` is NULL on **0 of 4,019 shots** — from the first game to the
last, so it is a never-pressed button, not a history artefact. Meanwhile the
2-node edge the module does not need is fully captured:

```
shots carrying a passer (PotAST)      2,678
distinct passer → shooter edges         780
edges with ≥10 shots                     54
edges with ≥20 shots                     14
team 1's own edges at ≥10 shots          29
```

29 edges at ten or more shots is a readable connection matrix for a ten-player
rotation. **Build:** make the hockey tag optional — 3-node chains when it is
present, the 2-node graph always. Half a session, and it lights up a module that
already has tests.

Note this is a *different question* from `networks.py`, which graphs who is on
the floor together. This one graphs the ball.

### 1.3 · The play-type axis that is never passed

Both live call sites of `shot_kinds.kind_by_shot_tag` hardcode `"defense"`;
`"play_type"` is never supplied, so a cross-tab the engine already supports has
never rendered. League-normalized on this book:

* Adair's **post-ups reach the rim 71%** of the time against a **50% league
  post-up rate**;
* their **off-screen actions land 16pp less arc-three and 12pp more 4-to-19ft** —
  the curls are getting caught short, in the exact band §1.6 prices at 0.548 PPS.

**Build:** pass the second axis at both call sites and render the cross. Half a
session.

### 1.4 · Two computed-and-never-read keys

* **`exploit.defensive_plan["their_leaks"]`** — a documented return key, computed
  on every call, read by nothing. The War Room renders its siblings `throw` and
  `avoid` (6–11 possession rows) and drops the one half that answers *"what
  should my offense attack"* (106–842 possessions). **Three lines.**
* **`situational.player_margin_scoring`** — reaches no renderer. Four Adair bench
  players score **63–94% of their points in garbage time**, one of them at 94.1%
  with a 2.4% close-game share. A coach deciding who can be trusted in a close
  game has that answer computed and hidden. **Half a session.**

### 1.5 · Quarter reads — five generators, on a pattern that exists

Roadmap item 4 says the deck has zero quarter reads. It has **one**
(`team_insights._t_quarter`, which fires *"Q1 team — they win the q1 by +10.4
points/game"* for Adair). What it lacks is the other five, against a Charts →
Quarters tab that carries roughly twenty charts at a 22% read share:

| generator | metric key | the sentence it makes possible |
|---|---|---|
| quarter shooting swing | `Q shooting` | "they shoot 8 points of eFG better in the second half" |
| quarter turnover swing | `Q ball security` | "the fourth quarter is where they give it away" |
| quarter pace swing | `Q pace` | "they play four possessions a game faster in the first" |
| **start-of-half** | `Half starts` | Q1 and Q3 openings together — the post-halftime read a coach can act on |
| **opponent quarter identity** | `Q scout` | "they win the third" — the feed is already league-wide, so this costs nothing extra |

**This is the one item that needs new engine code**, and it is still only five
functions on an existing template. One session.

### 1.6 · The 4-foot cliff, as a plan rather than a read

Measured over the 2025-2026 tracked pool:

| band | girls share | girls PPS | boys share | boys PPS |
|---|---:|---:|---:|---:|
| rim 0–4 ft | 25.8% | **1.086** | 29.6% | **1.318** |
| 4 ft–arc | 35.3% | **0.548** | 32.3% | **0.675** |
| 3 at the arc | 21.3% | 0.828 | 26.0% | 1.088 |
| 3 from 23+ | 11.7% | 0.772 | 12.0% | 1.281 |

A girls' team moving one shot a game from the dead band to the rim gains **0.54
points**. Ten shots a game is **+5.4** — larger than any single four-factor edge
the Winning Formula block prices.

The app already *says* this (the shot-diet verdict on Insights). What it does not
do is turn it into a target: *"you take 88 shots from that band; the league-average
diet at your volume is 113; each one you convert into a rim attempt is worth
+0.54."* That is a season goal a coach can coach.

**And fix the captions while you are there** — Part 2 §1.2: two headers hardcode
this league fact, disagree with each other, and are both wrong for at least one
gender.

### 1.7 · Contest × set call

`guarded_by_id` NULL means *uncontested* — a value, not a gap. The contest is
worth **0.337 PPS** league-wide (contested 0.745 on n=2,891, uncontested 1.082 on
n=1,128), which independently reproduces the 0.34 already on record.

Open-look rate by set call varies four-fold:

| play_type | n | open % | PPS |
|---|---:|---:|---:|
| spot | 873 | 33.9% | 0.828 |
| transition | 616 | 35.1% | 0.989 |
| **iso** | **724** | **12.6%** | **0.588** |
| post | 210 | 8.6% | 0.933 |
| pnr | 123 | 10.6% | 0.764 |

Iso at n=724 generating an open look 12.6% of the time for 0.588 PPS, against
spot at n=873 / 33.9% / 0.828, is a 1,597-shot comparison and safe to publish.
`offscreen` (n=132, PPS 1.227) and `duckin` (n=137) are the interesting cells and
are **too thin to rank** — flag, don't order.

Both halves exist (`playtypes.py:698` already counts `p["open"]`; `breakdown.py`
already does four factors per tag). The **cross** is unbuilt. Half a session.

### 1.8 · Put the post-game read where a coach reads

`helpers/postgame.game_report` produces the best writing in the app:

> *Adair Girls won 60–31, in a rout. Adair Girls won the four-factors battle 3–1
> — shooting (eFG%) 56% vs 25%; ball security (TOV%) 21% vs 28%. Adair Girls
> ripped off a 12-0 run in Q1 — the game's biggest, and it swung the momentum.*

It reaches **two** surfaces: the box score and the Game Tracker. It is absent
from the Schedule page (which emits **zero** sentences, the only 0%-read surface
in the app), from the Team Dashboard's schedule, and from the season feed —
despite `news_feed.py`'s own docstring saying *"`postgame` generates a game
report"*. One session, three surfaces, one existing cached engine.

---

## 2 · Measured and rejected — do not build these

Written up in full so the measurement is not repeated.

### 2.1 · In-stint fatigue — **no effect on this book**

The intuition: performance should decay the longer a player stays on the floor,
so a rotation tool should warn a coach when to sub.

The naive version is confounded and looks like the *opposite* of fatigue,
because the best players get the longest stints:

```
team 1, offensive possessions by depth into the shooter's current stint
  events into stint   poss   PPP
  1-10                 509   0.713
  11-25                489   0.769
  26-50                340   0.756
  51+                  273   0.912
```

Normalizing within player — each player against themselves, first 15 events of a
stint against everything after — does not rescue it:

```
player                early n  early PPP   late n  late PPP   delta
Ali Schwerdfeger          133      0.857      260     0.696   -0.161
Hannah Bond               112      0.920      139     0.993   +0.073
Kealey Sanders             62      0.903      123     0.894   -0.009
Reagan Langley             79      0.886       75     0.947   +0.061
Finley Grubbs              37      0.568       93     0.968   +0.400
Katence Hughes             77      0.571       36     0.667   +0.095
Kodi Schwerdfeger          36      0.389       58     0.534   +0.146
Carly Buell                46      0.652       45     0.756   +0.103
Morgan Boyles              48      0.604       28     0.536   -0.068
Peyton Cowan               35      0.457       33     0.697   +0.240
POOLED                    665      0.747      890     0.806   +0.058
```

**Seven of ten players are better late in a stint, and the pooled delta is +0.058
the wrong way.** There is no fatigue signal here to surface. Building a "sub him,
he's tired" read on this book would be inventing one.

What the data *does* support, and what a rotation tool should say instead, is
descriptive: 626 stints across 12 players over 25 games, median stint 22 events,
median 13 lineup changes per game. Those are facts. "He is tiring" is not.

Revisit only with real minutes (`possession_secs` accumulated on-floor rather
than event counts) and a larger book.

### 2.2 · Per-official whistle profiles — **the sample does not exist**

70 officials, 1,115 fouls, 100% attributed — the best capture in the book, and
still not enough. The busiest official has worked 4–5 games depending on how you
count, and **no official has a publishable sample**. 135 distinct official pairs
exist and 4 have been seen three or more times, so crew chemistry is out too.

This is a *wait*, not a *fix*: `officials.py` keeps officials career-long and
never archives them at rollover, so it compounds across seasons. Three seasons at
this rate puts the busiest crew members past 15 games. See Part 3 for what IS
supportable today (the pooled reads) and what is currently published that should
not be.

### 2.3 · Shooter × defender matchups — **one qualifying pair**

2,891 shots carry a named on-ball defender across 260 distinct defenders, which
supports **defender-level** shot defense with shrinkage for about twelve players
(12 at ≥50 shots defended; PPS allowed spans 0.400 to 1.259, a 0.86 spread well
beyond the 0.337 the contest itself is worth, so it is not a contest-rate
artefact). Publish **tiers, not ranks**, and never past the 27 defenders at ≥30.

The **individual matchup grid** is a different matter: exactly **one**
(shooter, defender) pair in the entire book has ≥15 shots. That needs a different
sampling regime, not more games at this rate.

### 2.4 · Timeout impact — **22 timeouts over 4 games**

`game_timeouts` has 22 rows. The after-timeout view exists; the metric does not
have a sample. Leave it.

### 2.5 · Also not supportable, stated so they are not attempted

| read | why not |
|---|---|
| hockey assists / 3-node chains | 0 of 4,019 shots tagged |
| foul KIND (shooting / common / charge / technical) | column dropped 2026-09-05 by ruling; not capturable at all |
| PHYSICAL rating | glossary-documented, 0 of 541 players have height or wingspan |
| position-based depth reads | `players.position` blank on all 541 |
| home / neutral-floor splits | `games.neutral` constant 0 |
| charges as a per-player rate | 55 charges over 308 players — a season total, not a rate |
| rebound LOCATION | not captured; misses carry the *shot's* x/y, which is a different question |

---

## 3 · The honesty layer — not new analytics, but the thing most likely to lose a coach

Four findings from Parts 2, 3, 4 and 7 are the same finding wearing different
clothes: **the app publishes numbers whose sample it does not disclose.**

| where | what it says | what it means |
|---|---|---|
| Team Dashboard glance strip | `DRtg 96.1 · 80th pct · elite defense` | 2nd of **5** tracked boys teams |
| Team Dashboard glance strip | `DRB% 62.0 · 0th pct` | last of 5 |
| Insights, THE FIVE | *"elite on the offensive glass (0.6 OREB/g)"* | 0.6 offensive rebounds a game |
| Rankings leader cards | `Best defense (PA/G) 0.0` | a **1–0 forfeit** |
| Officiating Lab | `MOST LENIENT 0.0 · Mike Gaskins` | one foul, total |
| Officiating Lab | `BEST SHARED CREW 55 · White Bald` | a hair colour |
| Players superlatives | `REBOUNDING 80.7 · 12` | a jersey number |

None of these is a computation error. Every one of them would be fixed by the
same four rules:

1. **Every percentile carries its pool.** `80th of 5 tracked` — six characters.
   Below a floor (~10 teams) show the rank instead; a rank of 5 is a fact, a
   percentile of 5 is not.
2. **Superlative language needs an absolute gate.** "Elite" should require a rate
   that is elite in basketball, not merely first in a five-team sample.
3. **Hero cards need a minimum sample**, and one card per subject so a single
   player cannot fill seven of eight slots.
4. **Never render a placeholder as a name** — not a jersey number, not a physical
   description.

`helpers/reliability.py` already holds measured split-half reliabilities and
`helpers/cards.py` already exports `conf_dot`. The machinery exists; it is not
wired to the places that need it most.

**This is cheaper than any analytic in §1 and protects all of them.** A coach who
catches the app calling 0.6 rebounds a game "elite" will not trust the shot-clock
read either.

---

## 4 · The ranked list

Value ÷ effort, across every part of this sweep.

| # | item | part | effort | needs a ruling? |
|---|---|---|---|---|
| 1 | `pdf_or_html_download` takes a builder — six eager reports gated | 4 §5 | 1 session | no |
| 2 | **Shot-clock state read** | 8 §1.1 | 1 session | no |
| 3 | Percentile pool honesty + superlative gates | 8 §3 | 1 session | the floor value |
| 4 | Free box score — split `render_box_score`, add `TEAM_EVENT_DERIVED` | 2 §3.2 | 2 sessions | no |
| 5 | `player_label()` — no bare jersey numbers | 7 §2 | ½ session | no |
| 6 | War Room Lineups defaults to the viewer's own team | 7 §1 | ½ session | no |
| 7 | Empty read-filter sweep (35 sites; the test already fails on main) | 1 §2.2 | 1 session | no |
| 8 | Forfeit marker, excluded from margin engines | 4 §1.2 | 1–2 sessions | **yes** |
| 9 | Rule the offseason archive regime | 1 §1 | a decision | **yes** |
| 10 | `postgame.game_report` onto three more surfaces | 4 §3.3 | 1 session | no |
| 11 | The passing graph (`passing_chains` `continue`) | 8 §1.2 | ½ session | no |
| 12 | Own-creation entitlement (`tracked_by` in the read filter) | 1 §3.1 | 1 session | **yes** |
| 13 | Overview zone C leads with `team_insight_feed` | 2 §1.4 | ½ session | no |
| 14 | `season_wpa` takes `game_ids` | 1 §2.1 | 1 session | no |
| 15 | Quarter generators ×5 | 8 §1.5 | 1 session | no |
| 16 | `their_leaks` + `player_margin_scoring` rendered | 8 §1.4 | ½ session | no |
| 17 | play_type × shot-kind cross | 8 §1.3 | ½ session | no |
| 18 | Officials: placeholder names, `rated_games` floor, sample chips | 3 §1–5 | 1 session | no |
| 19 | `ANALYZE` on the book | 5 §5b | 5 minutes | no |
| 20 | Default `_MIN_GP` to 5; leader cards get their own floor | 4 §1.1 | 1 hour | the value |
| 21 | Un-hardcode the shot-depth captions | 2 §1.2 | 1 hour | no |
| 22 | Contest × set-call cross | 8 §1.7 | ½ session | no |
| 23 | `insights_deck._next_game` gets `team_card`'s guards | 2 §1.1 | 15 min | no |
| 24 | `default_team` resolution order | 2 §1.3 | 1 hour | no |

**Free before breakfast:** 19 (`ANALYZE`), 23, 21, 24 — under two hours between
them, and 19 is a measured 39× on the app's hottest predicate.

**The four that need a founder ruling first:** 8 (the forfeit detection rule),
9 (the offseason archive), 12 (three questions in Part 1 §3.1), and the two
threshold values in 3 and 20.

---

## 5 · What is not finished

* **The glossary and explainer audit** is the last outstanding part and was still
  running when this was written. §3 above overlaps it and should be reconciled
  against it rather than merged blindly.
* **Setup, Settings, Input Hub, Game Tracker, Event Editor and OSSAA Import have
  not been swept.** The Game Tracker is the app's only write surface and the one
  a coach uses live; it deserves its own part.
* **§2.1's rejection uses event counts as a proxy for minutes.** `possession_secs`
  is on every row and would give real on-floor time; that version was not built,
  and it is the only way the fatigue question deserves a second look.
* **Nothing in §1 has been prototyped.** Every measurement here is from a direct
  engine call or a SQL query against the snapshot; none of it has been rendered
  through a page, so the effort estimates are estimates.
