# The Sicko Book — September 2026
### What the beloved analytics sites actually do, where HoopTracks stands, and the plan to make the War Room the page a college-level analyst opens first

Written 2026-09-12 against the repo at `66359ee` and the production book
(13,383 games / 63 tracked / 11,402 events / 608 players). Consolidates and
**replaces** `COMPETITIVE_SCRUB_2026-09-12.md` and
`WHY_SICKOS_LOVE_THEM_2026-09-12.md`.

Companion to `THE_BOOK_2026-09.md` (§4–§7 scored the product against OOTP,
Synergy and Hudl InStat) and `THE_FREEZE_BOOK_2026-09-12.md` (freeze-ready,
shipped `66359ee`).

**The context that shaped this document, and it arrived late:** the five coaches
joining the October pilot were chosen **because they are already analytics
sickos at the college level.** They read KenPom, Torvik, CTG, Synergy. They have
never had any of it pointed at their own data. They are not novices being
onboarded — they are experts *comparing*, with a reference frame already
installed, in session one.

---

# CONTENTS

**I · The competitive read** — §1 three businesses · §2 the scorecard ·
§3 Easy Stats head-to-head

**II · Why sickos love those sites** — §4 the ten mechanics · §5 the residual ·
§6 the counterfactual · §7 the composable question · §8 scanning · §9 the rest ·
§10 the mechanic scorecard

**III · The tension** — §11 verdict-first is right for October and wrong for
these five

**IV · The plan** — §12 the War Room is already the sicko page · §13 the design ·
§14 what must NOT move there · §15 sequencing

---
---

# I · THE COMPETITIVE READ

## 1 · Three businesses, and you are only in one of them

| business | who | what they sell | do they capture? |
|---|---|---|---|
| **The publisher** | NBA.com/Stats, Baseball Savant, Sports-Reference, Torvik, PBPStats | *someone else's* league feed, made queryable | no — the league hands it over |
| **The interpreter** | CTG, Dunks & Threes, KenPom, EvanMiya, FanGraphs, BP, PFF, FTN, Hoop-Explorer | a model on top of that feed | no |
| **The capture tool** | **Easy Stats**, Hudl, GameChanger, Synergy(-ish), **HoopTracks** | the act of recording the game, plus what you derive | **yes — the hard part** |

Almost every product on the list starts with 1,230 NBA games or 6,000 college
games handed to them in a schema. You start with a coach holding a tablet.

That single fact explains nearly every gap below — and the one thing none of
them can do: **CTG cannot tell you who guarded whom on a high-school possession
in Oklahoma, and never will.** Their advantage is *n*. Yours is *depth per
event*, and there is no feed you can be scooped by.

## 2 · The scorecard

| axis | best-in-class | HoopTracks | verdict |
|---|---|---|---|
| Impact metric | D&T (EPM), EvanMiya (BPR) | `rapm.py` — real ridge RAPM off 77,309 lineup snapshots, λ-shrunk | **peer, smaller n** |
| Lineup / on-off | Hoop-Explorer, EvanMiya | `lineups.py`, `stats.py:2237` | **peer** |
| Opponent adjustment | KenPom | `team_ratings` iterative SRS + `adj_efficiency.py` ridge on shooting | **peer; the shooting half is rarer than KenPom's** |
| Shot quality | Savant (xwOBA), ShotQuality | `shotquality.py` — continuous logistic on real x/y, contest, angle; SMOE shrunk | **peer, and contest is *logged* not inferred** |
| Exclusion discipline | **Cleaning the Glass** | garbage time defined in two engines, applied to **neither ratings nor leaderboards** | ❌ **gap** |
| Arbitrary slicing | Torvik (date range), Stathead (query) | class · gender · season. No date range. | ❌ **gap** |
| Data liberation | Savant (CSV everywhere), PBPStats (API) | 21 `download_button` sites / ~40 tables; 4 public JSON endpoints | ⚠️ partial |
| Percentile framing | Savant sliders, CTG | `cards.pctile_bar` — **states its pool** | **peer/better** |
| Play-type economics | Synergy | classification + PPS built; frequency axis not on the same line | ⚠️ one framing change |
| Per-play grading | PFF | season-level only | ❌ gap, **refuse** |
| Prose / recap | Easy Stats ("AI recaps") | `postgame.game_report` — deterministic, cited | **you win** |
| Metric honesty | nobody | `reliability.py` — measured split-half, one metric *killed* on record | **you win, uncontested** |
| Capture depth | Synergy, InStat | on-ball defender, set call, scheme, possession length, tap x/y, per-event lineup | **you win at your level** |
| Distribution | Easy Stats (App Store, free, since 2012) | invite, PWA, five coaches in October | ❌ gap |

## 3 · Easy Stats — the only direct competitor

Free iOS app, App Store since 2012, v18. Unlimited teams/games/players free;
Pro $5.99. Two touches per stat, **opponent tracked as a team** (no opposing
roster), shot charts across five court geometries, game-flow chart, AI game
recaps (v17.1), lineup groups, CSV export, box-score share link, 10 languages.

Review asks: auto foul reset at half, timeout tracking, shot→assist linking.

**Read: Easy Stats is a scorekeeper. HoopTracks is a scouting department.** They
overlap for about ninety seconds — the moment a shot goes up — and diverge
completely after. You win every analytical axis and lose the two that decide who
installs: **it is free, and it does not need the opponent's roster.**

**The one idea worth stealing: opponent-as-a-blob.** A "quick game" mode logging
your own five in full depth and the opponent as a team total would cut
first-game friction to near zero and still feed team ratings, runs, WP, GEI and
`deserved`. The co-op upgrades it later when the other coach tracks it too.

**Refuse:** court-size switching (one league, one geometry — five geometries is
five ways for `court_geom` to be wrong), LLM recaps (`postgame.game_report` is
better *because* it cannot invent a run), free-unlimited (their data lives on the
phone; your marginal game is a 1 vCPU box clearing a global cache).

---
---

# II · WHY SICKOS LOVE THOSE SITES

## 4 · The thesis, and the ten mechanics

A sicko is not buying numbers. Numbers are free and everywhere. **They are
buying the feeling of arriving at something before anyone else did.**

Every site on that list is a machine for manufacturing that feeling, and the
machines are similar. Beloved sites run six or seven of these. Sites that ship
good data and are *not* beloved usually run two.

| # | mechanic | one-line version | best at it |
|---|---|---|---|
| 1 | **The residual** | "the obvious number is lying to you" | Savant, KenPom |
| 2 | **The counterfactual** | "what if this five instead" | Hoop-Explorer, EvanMiya, CTG |
| 3 | **The composable question** | "let me build the query myself" | Stathead, Torvik, FanGraphs |
| 4 | **Pre-cognitive scanning** | find the outlier before reading a number | CTG, Savant |
| 5 | **No naked numbers** | value · rank · percentile · **pool**, always | CTG, KenPom |
| 6 | **Layout fluency** | every entity page identical → read 360 fast | KenPom |
| 7 | **The arguable number** | one ranked metric worth fighting about | D&T, PFF, FTN |
| 8 | **Show your work** | publish the methodology *and* the failures | Baseball Prospectus, CTG's blog |
| 9 | **Give away the raw** | CSV/API → strangers build → they market you | Savant, PBPStats, Torvik |
| 10 | **The bespoke toy** | a weird tool that says a human with taste built this | Torvik, Savant |

**You already run 1, 2, 5, 8 and 10 at or above their level, and run none of
them where a sicko can find them.** That is the whole finding.

## 5 · Mechanic 1 — the residual

Shape is always the same: `ACTUAL − EXPECTED = the interesting part`.
Savant's `BA` next to `xBA`. KenPom's **Luck** column. PFF's grade against the
box score. CTG's on/off.

**Why it hits:** it is the only column that makes the reader feel smarter than
the room. A raw stat is public knowledge; a residual is a *private opinion with
evidence attached*, and the coach can walk into a gym and say something nobody
else in it knows. Everything else on this list is delivery mechanism.

**Where you stand — five residual engines, no residual staging:**

| engine | the residual | lives today |
|---|---|---|
| `deserved.py` | every point of margin split into four causes | Insights deck (`insights_deep.py:756`) |
| `shotquality.py` | **SMOE** — points over what the league expected from those exact shots | Team Dashboard Shot Lab (`6_Team_Dashboard.py:2873`) |
| `league_analytics.py` | Pythagorean wins & **luck** | Rankings Lab (`5_Rankings.py:3300`) |
| `rapm.py` / on-off | impact, teammates and opponents held constant | Impact Lab |
| `adj_efficiency.py` | eFG adjusted for defenses actually faced | ratings surfaces |

Five residuals, five pages, five names, **zero framed as residuals.** Savant's
power is not that xBA exists — it is that **xBA sits in the same row as BA, on
every page, every time.** The disagreement *is* the layout.

**Build: the disagreement column.** Record · Pythagorean · **luck** on the team
header. Final margin · deserved margin · **gap** on the game row. FG% · xPPS ·
**SMOE** on the player card. And the sentence that turns it into a find — not
"SMOE +2.3" but *"She shoots 41%, which reads ordinary. Against the shots she
actually takes, the league makes 36%. She is the third-best shot-maker in the
class and her FG% will never say so."*

## 6 · Mechanic 2 — the counterfactual

A surface where the reader **changes the world and sees the number move.**
Hoop-Explorer's on/off combinations. EvanMiya's pick-any-five. A table is a
fact; a sandbox is **agency**, and the finding is *theirs* because they chose the
inputs. Hoop-Explorer is genuinely ugly and genuinely beloved — which proves the
ranking: **uniqueness of the question you can ask beats polish, every time.**

You own the best version in the document: `lineups.py` (every real 5-man unit,
per-100 O/D/Net), the lineup Creator / Rotation optimizer / Compare
(`9_War_Room.py:1508`), and the **20,000-game Monte Carlo**, which `THE_BOOK`
calls the best surface in the app.

## 7 · Mechanic 3 — the composable question

Stathead: *"every game with 40+ points and 10+ assists in a loss."* Torvik:
**every control is a URL parameter**, so people hand-edit the address bar.

**Why it hits:** a curated page shows what *someone else* found interesting. A
composable one lets you find what they didn't. **A sicko's highest compliment is
"I found something on your site that you didn't know was there."** Only a
composable surface can earn it. Hackable URLs are also the cheapest virality on
the list — every finding becomes a link someone pastes into a group chat, and
the link *is* an ad that reproduces the finding exactly.

**Where you stand — weakest mechanic:**

```
st.query_params in the whole app:  3 sites
    6_Team_Dashboard.py:574   ?team=
    7_Players.py:607, :1517   ?player=
```

Class, gender, season, the scoped tab, every filter — **invisible to the URL.**
A coach who finds something cannot send it; they screenshot it, and a screenshot
is not clickable, not re-runnable, not an ad. The `st.tabs` → `_seg` conversion
also silently broke routing *into* a section, so the deep links you do have are
partial.

**Refuse Stathead itself.** A query builder over 63 tracked games is a toy. The
composability that matters here is *scope*, not *predicate*.

## 8 · Mechanic 4 — pre-cognitive scanning

You do not read a CTG team page; you scan it for dark blue and dark red and then
read only those cells. The number is confirmation, not discovery. It changes the
unit of work from "read 40 numbers" to "notice 2 colours" — and lets a sicko
compare twelve teams in the time one used to take. **Volume of comparison is
where findings come from.**

**Row level: best-in-class.** `cards.pctile_bar` (`helpers/cards.py:126`) is
better than Savant's slider, and the docstring says why: it renders the **pool**,
so `80th pct` can never silently mean *second of five*. Below `POOL_FLOOR` it
degrades to "2nd of 5" in a neutral colour **so the eye cannot read a five-team
ranking as an achievement**. Savant does not tell you its pool. KenPom does not
either. This belongs in the marketing copy.

**Grid level: absent.** `background_gradient` appears **zero** times in the repo.
Tables use `ProgressColumn` on a few percentage columns
(`box_score.py:232`, `advanced_ratings.py:115`) and are otherwise plain numbers.
43 call sites of a world-class *single-row* component, and no way to scan a
*field* of teams.

**Build: a percentile-heated table renderer**, carrying `pctile_bar`'s pool
discipline — a heated cell in a 5-team pool is a lie in exactly the way that
component was written to prevent.

## 9 · Mechanics 5–10, briefly

**5 · No naked numbers — you win.** A number without a rank is one the reader
must price themselves, and most won't. *Check rather than build:* 43 `pctile_bar`
sites against 110 engine modules deserves a coverage assert. *Fix:* the boys'
pool quantizes to `{0,10,…,90}` on 10 tracked teams — a bar moving in tenths
overstates its own precision; render those as the rank chip the component
already knows.

**6 · Layout fluency — C.** `THE_BOOK` §4 already flagged the player read spread
across four surfaces sharing `player_card.py`. The new argument for fixing it:
not tidiness — **four layouts for one entity means a coach never becomes fluent
in any of them**, and fluency is what makes volume comparison possible.

**7 · The arguable number — B−.** `OVERALL` and `HoopWAR` are exactly this
shape; `player_edge.py` ships the boards. Missing is the *argument surface* — a
top-N with a **why** line per entry ("gets there on defensive impact, not
scoring; RAPM agrees, on/off doesn't"), drawn from `insights_severity`. The
2026-09-12 ruling (no league-wide public ordinal, ever — class rank only) is
untouched: this lives inside the gate, between co-op coaches.

**8 · Show your work — A+ asset, F surface.** `reliability.py` holds measured
split-half reliabilities, and a metric was **killed** on record: the
on/off-offense card, measured at −0.21, rewired to gate on RAPM agreement. Plus
xPPP forecasting refused (shot quality predicts future scoring at r=.176 vs past
scoring at r=.655); the quarter axis mostly refused (only tempo repeats, SB
.596); defensive shares measured non-portable (SB .17–.64). **Not one site on
that list publishes the reliability of its own metric. Several would not survive
doing so.** A coach cannot read any of it. *Build:* a "what we refused and why"
surface (`helpers/faq.py` is its natural home) and a reliability chip beside
every metric that has one — including **"not yet measured"**, which will buy more
credibility with a staff than any chart in the app.

**9 · Give away the raw — C+.** Savant's CSV-on-every-page is trust; PBPStats'
free API means strangers build things and every one is a free ad. *Build:*
`ui.table_with_export(df, name)` as the only way a page renders a DataFrame, and
token-scoped **own-team** JSON (not a general API — the co-op gate decides
visibility and a general API routes around it).

**10 · The bespoke toy — A, already running it.** The **Officiating Lab** is a
Torvik-style oddity nobody asked for that no competitor has, and there is a
standing ruling that the officials table is for assigners and the fan-page
R/U1/U2 fouls are by design — **never propose cutting it.** Same family: the
Whiteboard, Hall of Fame, stakes-adjusted GEI. *Build nothing; recognise it.* One
weird tool a season is a real retention strategy for this audience.

## 10 · The mechanic scorecard

| # | mechanic | grade | the gap |
|---|---|---|---|
| 1 | The residual | **A− engine / D staging** | never rendered *next to* the number it contradicts |
| 2 | The counterfactual | **A engine / C− naming** | best surface in the app is named after a room |
| 3 | The composable question | **D** | findings can't leave the app as links |
| 4 | Pre-cognitive scanning | **A row / F grid** | can't scan a field of teams |
| 5 | No naked numbers | **A — unmatched** | coverage unproven; quantized pools overstate precision |
| 6 | Layout fluency | **C** | fluency tax on every comparison |
| 7 | The arguable number | **B−** | no board with a *why* line |
| 8 | Show your work | **A+ asset / F surface** | invisible to the coach it would convince |
| 9 | Give away the raw | **C+** | no universal export, no own-team JSON |
| 10 | The bespoke toy | **A — already running it** | recognise it; don't cut it |

**Pattern: your engines score A and your staging scores C.** Nearly every gap is
a rendering and naming problem sitting on an engine that already runs correctly.
That is a far better position than the reverse, and it means most of the build
list is small.

---
---

# III · THE TENSION

## 11 · Verdict-first is right for October and wrong for these five

The house shape is **verdict-first** — a sentence over a chart, enforced by two
suites, with the opt-out list as the load-bearing half.

**Every site in this document does the opposite, and that is *why* sickos love
them.** CTG hands you a wall of colour-coded cells. KenPom hands you a dense
table with no commentary. They do not tell you what to think, and the absence is
the product: **the finding feels earned because you did the finding.**

A verdict-first page, read by a sicko, has quietly done the interesting part
*for* them and handed over the conclusion. That is a service to a novice and a
theft from an expert.

**And the pilot is five experts.** The original sequencing in this analysis
assumed October was onboarding-for-novices and deferred the sicko layer to
"roughly January, when a coach has data." That was wrong twice: these five
arrive with the reference frame installed, and **conversion happens in session
one or not at all.** Novice conversion is "this tells me what to do."
Sicko conversion is "I found something you didn't show me."

### The resolution, and it reverses no ruling

Progressive disclosure, with the depth actually present:

> **verdict sentence → the chart → the table it came from → the export**

Verdict-first stays enforced exactly as it is. What changes is that **every
verdict must be openable down to the grid underneath it** — and today many
verdicts terminate in a chart with no way further down.

1. **The floor of a section is a table, not a chart.** A chart is a conclusion
   someone else composed; a table is territory. Both, in that order.
2. **The sicko layer is a depth, not a mode.** No "advanced toggle", no second
   product — which is already the house taste (*depth, not clutter*).

**The rule, stated once:** *the verdict is what the page opens with; it is never
what the page bottoms out at.*

---
---

# IV · THE PLAN

## 12 · The War Room is already the sicko page — you built it and buried it

This is the finding that changes the build list. Three facts, all verified:

**(a) The analytics playground exists.** `helpers/dashboard/analyze.py` — "the
self-serve analytics playground": filter the full ~60-column player table, plot
any stat against any other with an OLS trendline, **correlate anything**, map
shots, download CSV. It renders at `9_War_Room.py:2226` as the **6th of 7
segments**.

**(b) The gate you would design is the gate it already has.**

```
helpers/dashboard/analyze.py:100
_paid = ENT.has_paid_plan(_ident) and ENT.viewer_is_league_wide(_ident)
```

Paid **and** co-op league-wide, with the reasoning in its own docstring: a
whole-league multi-team pool is a cross-team aggregate, so it is co-op, not
merely Paid. Box columns stay public; a league-wide viewer's depth is
read-filtered to the games they may aggregate. The page-level ladder agrees —
`9_War_Room.py:299` gates on `paid_or_open_archive`, `:532` opens the co-op gate
for a past season (the archive rule), and `_WR_LOCK` at `:535` already resolves
`lock_reason(scope="pool")` or `MSG_COOP_INVITE`.

**One lock ladder. Do not add a rung.** The gate is built, reasoned and correct.

**(c) The page is already the counterfactual surface.** `_WR_VIEWS` =
`["Lineups", "Matchup", "Season sim", "Bracket", "Defensive assignments",
"Analyze", "Glossary"]`. Every item is something you change and re-run. That is
mechanic **2** and mechanic **3** on one page.

**So the answer to "should we build an Analytics Hub" is: no — promote the one
you have.** A 16th page would add a fifth surface for the same entity reads
(mechanic 6 gets worse, not better), and it would pay every bundle at once on a
1 vCPU box.

**One stale artefact to clean while in there:** `analyze.py`'s docstring says
"the same code powers the standalone page." That page is gone — the War Room
call site is the only caller left. Fix the docstring or restore the page; do not
leave a comment pointing at something that does not exist.

## 13 · The design

### 13.1 · Keep the name. Fix the order.

I recommended renaming "War Room" twice while working through this. On
inspection that is the wrong call for October and the ordering is the real
defect.

* These five are trained in person. They will be *told* what the page is; the
  name costs nothing in session one.
* Renaming a page the founder named, three weeks from training, buys discovery
  for coaches who do not exist yet.
* "War Room" is a good coach-facing name. It is a bad *analyst*-facing one.

**Ruling: keep the title, add a one-line deck beneath it that states the
mechanic** — something that says *everything on this page is something you
change and re-run*. Revisit the name post-pilot, with telemetry.

### 13.2 · Reorder the views, sicko-first

| new | view | why here |
|---|---|---|
| 1 | **Lineups** | **stays the default — it is ungated for any Paid coach.** Counterfactual, immediate, no lock. |
| 2 | **Analyze** | the playground. Mechanic 3, the thing nothing else at this level has. Currently 6th. |
| 3 | **Defensive assignments** | who guarded whom — the single most "nobody else has this" surface you own. Currently 5th. |
| 4 | Matchup | predictor, 85% hit / 9.9 MAE |
| 5 | Season sim | |
| 6 | Bracket | a delight, not a conversion |
| 7 | Glossary | |

**Hard constraint: never default-land a gated view.** Analyze is co-op-gated; a
viewer who is not league-wide would open the page onto a lock. Lineups stays the
default precisely because it is open to any Paid coach.

**Implementation note — do not break routing.** Copy the Team Dashboard pattern
at `6_Team_Dashboard.py:1794`: *only the label list drives display; the option
values are unchanged, so session state and routing stay identical*. Reordering
`_WR_VIEWS` must not change any option **value**, or `wr_view` session state and
every existing deep link break — the same class of failure as the `_seg`
conversion that silently broke routing into sections.

**Reordering is free at runtime.** `_seg` sections are lazy, so promoting
Analyze costs nothing; Season sim and Bracket stay expensive and stay
unevaluated until opened.

### 13.3 · Make the gate sell instead of refuse

The co-op lock is the page's commercial job, and right now it is a message.
Diffuse depth is a weak incentive — co-op currently unlocks *more of pages you
already see*. **A named surface you cannot open until you share is a sharp
one**, and that is the strongest part of the "definite sell" instinct.

* **Show the locked views in the segment bar with a lock glyph — do not hide
  them.** A door you can see is a sell; a door you cannot see is nothing.
* Opening a locked view shows **what is behind it** — the columns, an example
  question it answers, the size of the pool it would draw on — plus the one
  action that opens it. `MSG_COOP_INVITE` is the text hook that already exists.
* **Never bypass.** Hall of Fame took a filter fix, not a bypass; the same rule
  holds here.
* Verify the comment at `9_War_Room.py:529` — *"Lineups + Glossary stay open to
  any paid coach; the other three gate on league-wide"* — against a seven-view
  list. Either the comment is stale or two views gate elsewhere. Confirm which.

### 13.4 · Prove the heated table here first

The percentile-heated renderer (mechanic 4) should debut on this page. It is
gated, so fewer eyes on a first version; its tables are the densest in the app;
and Analyze's ~60-column player table is the exact surface where scanning beats
reading. Once proven, it propagates to the league tables.

## 14 · What must NOT move here

**The residuals stay in place, and this is the important half of the plan.**

The residual works *because it sits next to the number it contradicts*. Savant's
xBA is powerful because it is in the same row as BA on the page you were already
on. §5's finding was that five residual engines are scattered across five pages
— **a hub does not fix scattering, it renames it.** Moving them to a sixth page
puts the disagreement one more click from the claim.

**The rule:** *the hub is for composing questions. Residuals live beside their
claim.* Luck on the team header. Deserved on the game row. SMOE on the player
card. None of them on the War Room.

**Second thing that must not move: cost.** Team Dashboard's ~15s cold floor is
the shared `team_bundle`; Insights is 85s cold / 0.97s warm; `_league` is 30s. A
hub that assembles reads pays all of it at once, which is the worst cache shape
available on 1 vCPU. Analyze is cheap *because* it is one filtered table plus
plots. Keep it that way — promote the playground, never grow it into a
read-hub.

**Third: hold the deletions.** The instinct to clear out "things that are just
kinda there" is uncalibrated right now, and it is exactly what would eat the
Officiating Lab (mechanic 10, grade A, standing ruling not to cut). Telemetry is
live and deduped — `ui.py:258` `page_view`, `ui.py:730` `empty_hit` — and
October will produce real data on what five analysts actually open. **Delete on
counters, not on feel.**

## 15 · Sequencing

The freeze shipped today (`66359ee`). "Post-freeze" is now three windows:

| window | risk | note |
|---|---|---|
| **now → October training** | high | `freeze_smoke` just certified 45 renders clean; every edit reopens a verified surface |
| **training → season tip** | **best** | coaches trained, book static, no live writes |
| **Nov → Mar** | worst | live-game writes on 1 vCPU with a global cache clear |

### Pre-October — additive only, no engine touched

| # | item | §  | cost |
|---|---|---|---|
| 1 | **War Room reorder + deck line + lock-as-sell** | 13 | **S** |
| 2 | **Percentile-heated table renderer**, debuting on Analyze | 13.4 | **S** |
| 3 | **"What we refused and why" + reliability chips** | 9 | S |
| 4 | **Disagreement column — two sites only** (team header, game row) | 5 | S |
| 5 | **`table_with_export` on every DataFrame** | 9 | S |
| 6 | **Measure garbage time; publish the answer — do not change the engine** | §2 | S |

On (6): the garbage-time gap was graded on *direction*, not magnitude — nobody
has measured how much it moves. The measurement is read-only against the prod
snapshot. Changing headline ratings three weeks before handing the app to five
coaches is what a freeze forbids; **measuring and publishing what you found is
honest, cheap, and answers the question a CTG reader asks in the first hour.**

### Deferred — these are gates, not preferences

* **Date range.** The ~35 caller sites that convert empty→None themselves are a
  live correctness hazard: a range matching zero games is the exact input that
  silently renders a season aggregate under a "last 10 days" label. Audit first.
* **Scope in the URL / "copy this view".** The `_seg` deep-link breakage is a
  bug. Fix the bug before building sharing on top of it.
* Arbitrary-five picker, top-N board with why-lines, own-team JSON, player-read
  consolidation, opponent-as-a-blob capture mode.

### The thing to do before any of it

These five are Paid, so the plan gating is open — but the **co-op is
reciprocal**, and on day one they have shared nothing while their own team has
zero tracked games. `freeze_smoke` renders a day-one persona and reports 15
renders, 0 exceptions.

**Zero exceptions is not the same as "an analyst finds something to chew on."**
Nobody has read what that persona actually *sees*. If a day-one sicko lands on
locks and empty states, every item above is decoration. One command against the
prod snapshot settles it, and it should reorder this list.

---

## Sources

* [Easy Stats for Basketball — App Store](https://apps.apple.com/us/app/easy-stats-for-basketball/id561687907)
* [EvanMiya](https://evanmiya.com/)
* [CBB Analytics](https://www.linkedin.com/company/cbb-analytics)
