# Sweep — 2026-09-06 · Part 2: Team Dashboard (and the Players page it shares code with)

Companion to `SWEEP_2026-09-06.md` (Part 1, the gating audit). Same rules: read-only,
measured against a `sqlite3.backup` copy of the live book, **the live book was never
written to**. No application code changed.

Two teams were rendered end to end, deliberately:

* **Adair Girls** (team 1) — 32 games, **24 tracked**, in a 21-team tracked pool.
  The rich case.
* **SEQUOYAH (CLAREMORE) Boys** (team 1755) — 25 games, **8 tracked**, in a
  **5-team** tracked pool. The thin case, and it is where most of §2 comes from.

Rendering both is what made §2 visible at all. A sweep that only looked at the
flagship team would have called this page healthy.

---

## 0 · The measured shape of the book

```
                scored teams   TRACKED teams   tracked games   players in pool
girls (F)            704             21             35              242
boys  (M)            748              5              8               59
```

Hold those two tracked-team counts. Every percentile, every "vs league", every
"elite / poor" verdict on this page is computed against **21** teams or **5**,
while the rank beside it (`#422 / 748`) is computed against the full results
pool. The page does not distinguish them anywhere.

---

## 1 · Correctness — four things that are wrong on screen

### 1.1 · The Insights masthead shows a "next game" nine months in the past

Adair Girls, season 2025-2026, rendered masthead:

```
Adair Girls  29–3  +27.7 margin/g  #1 of 21  next: at Salina Girls 2025-12-05
```

The season finished in March. There is no next game.

There are **two** `_next_game` implementations and only one of them is right:

| | guard | result |
|---|---|---|
| `helpers/dashboard/team_card.py:118` | `if not _SEAS.is_current(season): return None`, plus `AND g.date >= today` | correct — Overview shows nothing |
| `helpers/dashboard/insights_deck.py:132` | neither | shows the stale fixture |

`team_card`'s docstring even names the bug it fixed — *"fixes past-season games
showing under a prior season's 'Next'"*. The same fix was never carried across.
One-line change; two surfaces stop disagreeing.

Underneath it there is a data slip worth a separate look: game **22350** (Salina
Girls vs Adair Girls, 2025-12-05) sits in a completed season with `home_score`
and `away_score` both NULL. It is the only unscored 2025-2026 game team 1 has.

### 1.2 · Three different hardcoded values for the same league fact

Two captions hardcode the league's shot-depth economics. They disagree with each
other **and** with the engine that computes the same numbers on the same screen.

```
helpers/dashboard/insights_identity.py:252
  "The 4-to-arc band is over a third of every shot in this league at
   0.60 points per shot against 1.14 at the rim."

helpers/dashboard/shot_diet.py:427
  "...It is 37% of every shot taken in this league at 0.55 points a trip,
   against 1.09 at the rim."   (also: "2–4 ft shoots 56%, 4–6 ft shoots 32%")

helpers/shot_kinds.py:761  — computed, per gender, from the book:
  "that band returns {lg[bad]['pps']:.2f} PPS league-wide against
   {lg[good]['pps']:.2f} at the rim."
```

Measured today, `shot_kinds.league_table(taxonomy="band")` over the 2025-2026
tracked pool:

| band | girls share | girls PPS | girls FG% | boys share | boys PPS | boys FG% |
|---|---:|---:|---:|---:|---:|---:|
| rim 0–4 ft | 25.8% | **1.086** | 54.3% | 29.6% | **1.318** | 65.9% |
| 4 ft–arc | 35.3% | **0.548** | 27.4% | 32.3% | **0.675** | 33.8% |
| 3 at the arc | 21.3% | 0.828 | 27.6% | 26.0% | 1.088 | 36.3% |
| 3 from 23+ | 11.7% | 0.772 | 25.7% | 12.0% | 1.281 | 42.7% |

(girls n = 3,246 located shots over 35 games; boys n = 742 over 8)

So:

* `shot_diet.py`'s numbers are **the girls' numbers** — 37% / 0.55 / 1.09 against
  a measured 35.3% / 0.548 / 1.086. Accurate for girls, and shown verbatim to
  boys teams where the truth is 32.3% / 0.675 / 1.318. The rim is understated by
  **21%** and the dead band by **23%** for half the app's users.
* `insights_identity.py`'s pair (0.60 / 1.14) matches **neither** gender. It is a
  stale measurement from an earlier book, and it sits in the section header
  directly above the computed line that contradicts it.

The irony is documented in the tree: `shot_kinds.py:749-755` carries a comment
explaining that an earlier evidence line hardcoded *"At the rim the league is at
1.09 points a shot; in that band it is 0.55"* and was replaced with the computed
version. The fix was applied to the evidence line and not to the two headers
above it.

**Fix:** thread `lg[bad]['pps']` / `lg[good]['pps']` / the measured share into
both captions. Half an hour. It also makes the app's single most actionable
coaching fact — *a shot moved from the 4-ft-to-arc band to the rim is worth
+0.54 points for a girls team* — a computed claim rather than a remembered one.

### 1.3 · A new coach lands on somebody else's team

`app_settings` carries both the per-coach key and a bare global:

```
u:colbyl.farrar@gmail.com:default_team = Adair Girls
u:c.farrar@adairschools.org:default_team = Adair Girls
default_team                            = SEQUOYAH (CLAREMORE) Boys
```

`settings_utils.get_setting` resolves a USER_SCOPED key as *this coach's value,
else the global one* (`:129-140`). A coach with no stored preference therefore
gets `SEQUOYAH (CLAREMORE) Boys`, and because that value is non-empty the
"fall back to the coach's own team" block at `pages/6_Team_Dashboard.py:421-431`
— written specifically so that *"the coach lands on their own program without
ever visiting Settings"* — **never runs.**

This is also why the first pass of this sweep rendered the wrong team: seeding
`ta_team=1` had no effect, because the gender radio had already opened on Boys
and team 1 was filtered out of the list.

**Fix:** for a USER_SCOPED key with a known email, do not fall through to the
global bucket. Resolution order should be: this coach's value → the identity's
own `team_id` → ranking order. The bare `default_team` row is a pre-multi-coach
leftover.

### 1.4 · "Verdict — model reads" contains no verdict

`helpers/dashboard/team_card.py:531` opens zone C with the header
`Verdict — model reads`. Rendered, for Adair Girls, it is five key-value rows:

```
Verdict — model reads
  Pythagorean W-L            26.1-5.9
  Luck (wins vs expected)    +2.9
  Momentum (L5 MOV − season) -0.1
  Close games (≤5)           2-1
  Tracked rank               #1 of 21
```

No sentence. The Team Dashboard's default landing view gives a coach roughly
forty numbers and zero plain-language reads, on a page whose sibling view
(Insights) is built entirely out of them.

**The generator already exists and is already wired to two other pages.**
`team_insights.team_insight_feed` is called from `pages/5_Rankings.py:487` and
`pages/9_War_Room.py:238`. Run against Adair Girls it returns, today:

```
Momentum    **Fading** — last 5 games are **-21.4 points/game off** their season
            line; something has slipped late.                              n=32
Takeaways   **Turnover factory** — forces a takeaway on **36% of opponent
            possessions**, tops in the field; the defense feeds the offense. n=1467
Quarters    **Q1 team** — they win the q1 by **+10.4 points/game** (+3.4 vs their
            other quarters); that's where the game breaks open.             n=24
Rebounding  **Owns the offensive glass** — puts back **45% of their own misses**
            against a **31%** field; box out or concede the extra shot.     n=784
3PT diet    **Lives and dies by the three** — **34% of their points** come from
            deep at 32%; run them off the line.                             n=24
```

**Proposal.** Zone C leads with the top two or three of those lines, then keeps
the numbers below them. This is wiring, not building: the feed is cached
league-wide per (gender, season) and both other consumers already pay for it.
Half a session.

---

## 2 · The credibility problem: percentiles on a five-team pool

This is the biggest single risk on the page and it is not a bug in any one line
of code — it is a missing guard applied consistently.

Rendered header, SEQUOYAH (CLAREMORE) Boys:

```
3A · Boys · 25 games · 8 tracked
RANK #422 / 748 · OK 3A #45      TRK RANK #3 / 5 · OK 3A #1
POWER 49.4   NET +2.1   RECORD 13-12 (52%)   MOV -0.1   STREAK 2L
```

and immediately under it, the glance strip:

```
DRB%  62.0   0th pct  gives up second chances
3PAr  44.9  80th pct  bombs away from three
eFG%  51.2  20th pct  poor shooting team
DRtg  96.1  80th pct  elite defense
AST%  61.1  20th pct  iso-heavy
MOV   -0.1  20th pct  plays close / loses
```

Every one of those percentiles is a multiple of 20, because the pool is five
teams. `0th pct` is not a percentile a coach has ever seen; it means "last of
five". `80th pct — elite defense` means "second of five". Neither says so.

The same page then puts `#422 / 748` — an honest 748-team rank — three
centimetres away, with nothing distinguishing the two pools.

It runs all the way through the derived language. From the Insights deck for the
same team:

```
5. ⚠ Rebounding  14  **Second-chance machine** — elite on the offensive glass
                     (**0.6 OREB/g**); box them out or they bury you on putbacks.
```

**0.6 offensive rebounds per game is called elite.** It is elite *within five
teams over eight games*. And note the sign: a verdict phrased as a strength
carries `≈ -0.8 pts/g`, because the deck is speaking in scout voice about the
viewed team's own player. Which brings up a second, smaller issue —

**Voice.** Three of the top five findings for this team are phrased as if
scouting an opponent (*"safe to leak out early against them"*, *"box them out"*)
while sitting under the section header **Who's helping**, which is the
own-team section. The self-scout voice belongs in *What they'll take away*.

### What to do

1. **Every percentile chip carries its pool.** `80th of 5 tracked` is honest and
   costs six characters. Better still, below a floor show the rank instead: a
   *rank* of 5 is a real fact, a *percentile* of 5 is not.
2. **A pool-size floor for derived language.** Below ~10 tracked teams, suppress
   the adjective ("elite", "poor shooting team") and show the raw comparison.
   `helpers/reliability.py` already exists and is the natural home for the floor.
3. **Absolute-value sanity gates on the superlatives.** "Elite on the offensive
   glass" should require a rate that is elite in basketball, not merely first in
   a five-team sample. One constant per generator.
4. **Say which pool in the masthead.** `TRK RANK #3 / 5` already does this well.
   The DNA rail and the glance tiles should copy it.

The girls' side is materially better (21 teams, ~5-point percentile steps) but
the same guard covers both, and at 62 tracked games in production the boys pool
will still be small.

---

## 3 · Verdict density — the measured Workstream-B target list

Every Team Dashboard view and sub-view was rendered and every emitted string
classified as a **read** (a sentence: ≥ 8 words with a finite verb) or a
**label** (a chart title, column header or metric name). The ratio is the
"verdict-first" measure, with Insights as the house benchmark.

SEQUOYAH Boys, all views and sub-views:

| surface | reads | labels | read share |
|---|---:|---:|---:|
| Charts → Winning Formula | 11 | 3 | **79%** |
| Lab → Impact Lab | 28 | 20 | 58% |
| Projection | 9 | 8 | 53% |
| Charts → Situational | 38 | 40 | 49% |
| **Insights** | 41 | 48 | **46%** |
| Charts → Play Style | 22 | 32 | 41% |
| Overview | 14 | 25 | 36% |
| Lab → Advanced | 5 | 9 | 36% |
| Share | 1 | 2 | 33% |
| Roster | 9 | 29 | 24% |
| Schedule | 8 | 26 | 24% |
| **Charts → Quarters** | 13 | 46 | **22%** |
| Charts → Defense | 6 | 25 | 19% |
| Charts → Offense | 3 | 14 | 18% |
| **Scout** | 3 | 18 | **14%** |
| **Charts → Trends** | 6 | 50 | **11%** |

Adair Girls agrees on the shape (Insights 53%, Overview 36%, Roster 24%,
Schedule 21%, Charts 18%, Scout 14%).

Three things fall out of that table.

**Scout at 14% is the worst result on the page, and it is the wrong view to be
worst.** Scout is the game-day surface — the one a coach opens the night before
a game — and it renders three sentences against eighteen labels. Its rendered
content is almost entirely section headers (`Overview`, `Personnel`, `Offense
(play calls)`, `Defense (schemes)`, `Situational`, `Shooting`, `Extras`) with
charts underneath. It should be the *most* verdict-first view in the app.
(Caveat on the number: this render had no opponent selected, so part of the
gap is the empty state — but the empty state is itself the finding, see §5.1.)

**Charts → Trends at 11% with fifty labels is the densest wall of charts in the
app.** Six sentences for fifty things to interpret.

**Charts → Winning Formula at 79% is the proof that this page can do it.** It is
the same team, the same data, and it leads with what the numbers mean:

> *Decided most by taking care of it — one standard deviation of ball-security
> edge is worth 10.8 points of margin, 45% of the four factors' pull. Same lever
> league-wide (43% of the pull vs Dean Oliver's 25%) — this is how the whole
> competition plays, not a quirk of your roster.*

That is a genuinely strong league-level finding, well surfaced, and it is the
template for the other fifteen rows.

---

## 4 · Roadmap item 4 (Quarter analysis) — the premise is wrong, and the real
gap is better than the stated one

**The roadmap says:** *"the Insights deck has ZERO quarter reads except the
foul-trouble quarter lines at `insights_deep.py:561`."*

**That is not true.** `team_insights._t_quarter` (`:202`) is a registered
generator in `_TEAM_GENERATORS` (`:839`), emits `metric="Quarters"`, is routed by
`insights_severity.METRIC_SECTION` to *Why we win / why we lose* (`:163`) and by
`METRIC_EVIDENCE` to `("Charts", "Quarters")` (`:231`), and reaches the deck
through `insights_tab._team_feed` (`:365`) which calls the feed with `top=None`
— every qualifying read, uncapped. Measured on Adair Girls it fires:

> **Q1 team** — they win the q1 by **+10.4 points/game** (+3.4 vs their other
> quarters); that's where the game breaks open.

It did not appear for SEQUOYAH Boys only because `_t_quarter` returns `None`
when `abs(swing) < 3.0` (`:216`).

**The real gap, restated.** The app has exactly **one** sentence about quarters —
net points, single most-extreme quarter, one gate — while Charts → Quarters
carries roughly twenty charts and a 22% read share. The deck is not missing
quarter analysis; the quarter analysis is missing its verdict layer.

**Concrete build.** Five more `_t_*` generators in `helpers/team_insights.py`,
each modelled on `_t_quarter`'s shape (z-scored swing vs the team's own quarter
average, `MIN_TRACKED` gate, `{"text","score","z","metric","n"}`), plus one
`METRIC_SECTION` + `METRIC_EVIDENCE` entry each — `test_insights_severity.py`
fails if a miner emits a metric with no section or no evidence destination:

| generator | metric key | the sentence it makes possible |
|---|---|---|
| quarter shooting swing | `Q shooting` | "they shoot 8 points of eFG better in the second half" |
| quarter turnover swing | `Q ball security` | "the fourth quarter is where they give it away" |
| quarter pace swing | `Q pace` | "they play four possessions a game faster in the first" |
| **start-of-half** | `Half starts` | Q1 and Q3 openings together — the post-halftime read, the one a coach can actually act on |
| **opponent quarter identity** | `Q scout` | "they win the third" — the feed is already league-wide, so the scout can read the opponent's line at no extra cost |

The last two are the ones worth building first. Everything Charts → Quarters
already computes feeds them; nothing new has to be measured.

---

## 5 · Layout and product notes, per view

### 5.1 · Overview

* **The first element on the page is an empty notes box.** `overview.py:33-39`
  renders the `📝 Team notes` expander above the team card. On a cold open a
  coach's first sight of their own dashboard is an empty text area. Move it
  below the header card, or collapse it into the masthead.
* **`vs Top 10 · Top 25   0-0 · 0-0`** renders zeros rather than being dropped
  (`team_card.py:552`). Every other conditional row on that card is suppressed
  when it has nothing to say; this one is not.
* **4F-PPP is a headline read rendered as 12px grey caption text**
  (`overview.py:225-240`). "Points/possession the four factors alone predict:
  off expected 1.03, actual 0.98 (−0.05 shot-making)" is the shot-making
  residual — the single most interesting derived number on the view — and it is
  styled as a footnote. It belongs in the header card as a tile.
  While it is being moved: the defensive half of the same line prints
  `def expected 1.07 actual 0.96` with **no** residual annotation, where the
  offensive half prints `(-0.05 shot-making)`. Asymmetric.
* **The four-factor tiles mislabel their comparison value on the defensive
  row.** `_ff_card(_d[0], "Opp eFG%", "oefg", "efg", ...)` renders as
  `Opp eFG% 53.3% · opp 51.2%` — where the second number is the team's *own*
  eFG%, not an opponent's. And `DREB% 62.0% · opp 38.0%` compares a defensive
  rebound rate against the opponent's *offensive* rebound rate, which are
  complements, not a like-for-like. Two labels.
* **The season feed is mostly board jitter.** Ten of twenty-four entries are
  rating-snapshot rows, several of them `Power -2.3 → -2.6 (-0.3) — down the
  board, -1 spot to #422` or `holding #425`. A coach scanning a season feed wants
  games. Suppress movements below a threshold, or fold a week's moves into one
  row.

### 5.2 · Scout

The lowest read share on the page and the highest stakes. On a cold open with no
opponent picked it renders seven section headers and this:

> *No rated players or hand-entered intel for this opponent yet — add key
> players in 'Manual scouting' below, then assign defenders here.*

The game-day surface's default state is an empty form. It should open on the
next scheduled opponent — the schedule knows who that is, and `team_card`'s
`_next_game` already resolves it correctly for the current season.

### 5.3 · Charts → Trends and Charts → Quarters

Fifty and forty-six labels respectively, six and thirteen reads. Both are pure
chart walls. Both have the engine output to lead with a verdict and neither does.
See §4 for Quarters; Trends wants the same treatment against
`team_analytics`' game-by-game series.

### 5.4 · The file itself

`pages/6_Team_Dashboard.py` is 6,800 lines and renders out of declaration order,
which the `RENDER MAP` comment at `:1631` documents honestly and well. But the
older banner comments were never updated to match and now actively mislead:
`TAB 1 — OVERVIEW` at `:1763` is followed at `:1782` by `if _tdview ==
"Overview"`; `TAB 2 — PLAYERS` at `:1780` sits above the Overview body; `TAB 7 —
INSIGHTS` at `:5345` is followed by `if _tdview == "Lab"`; `TAB 9 — GLOSSARY` at
`:6445` by another `if _tdview == "Lab"`. The module docstring lists five tabs;
there are ten views. Deleting the stale banners costs nothing and the RENDER MAP
already does their job.

---

## 6 · Performance — the biggest finding in this part

Per-surface timings, admin identity, one process, nothing else running
(SEQUOYAH Boys — the *thin* team, so these are floors not ceilings):

```
Players                      56.6 s      <-- the slowest surface in the app
TD / Overview                21.6 s      (first render = the page's whole cold cost)
TD / Insights                17.8 s
TD / Scout                   12.7 s
RK / Spotlight                7.6 s
TD / Projection               6.7 s
WR / Lineups                  6.6 s
WR / Analyze                  5.8 s
Hall of Fame                  5.3 s
TD / Schedule                 3.4 s
Officials                     3.5 s
everything else             < 3 s
```

**The Players page is the slowest surface in the app and it is not on the
roadmap.** The roadmap's open perf item is Scout at 11.7 s, reproduced here at
12.7 s. Players is four to five times that. On a 1 vCPU / 2 GB droplet at the
recorded 2–3× multiplier, that is **two to three minutes**.

### 6.1 · Why: a printable report nobody asked for, built on every render

`cProfile` over a cold Players render, flat by cumulative time:

```
129.9 s  pages/7_Players.py  (whole render, box was loaded — see the caveat)
122.1 s    _fx_prof                       the Player Profile fragment
 51.3 s      _player_card
 43.3 s  helpers/court_png.py:92  shot_chart_png
 43.2 s    helpers/court_png.py:25  _light_court        <-- ONE matplotlib figure
 21.1 s  player_card.py:375  _insight_feed
 15.1 s  player_ratings.py:1737  player_stat_table   (7 calls)
 14.5 s  database/db.py:1011  query                   (3,275 calls)
 13.5 s  player_card.py:278  _dev
 13.4 s  development.py:65  season_lines             (312 calls)
 13.1 s  player_card.py:270  _class_curve
 12.7 s  stats.py:95  fetch_events                   (357 calls)
 11.2 s  sklearn ridge fit                            (4 calls)
```

The chain is `pages/7_Players.py:1486`:

```python
pdf_or_html_download(
    "Player card", _player_card(pid, gender, _vis_key), ...)
```

`_player_card` is evaluated **as an argument**, so the printable HTML report is
built on every render of the Profile view whether or not anyone ever clicks
download. That report calls `reports.player_card_html`, which at `:246` renders a
matplotlib base64 PNG shot chart — and `court_png._light_court` pays matplotlib's
import, backend init and font-cache build the first time it is touched in a
process. **43 seconds of a cold Players render is one figure nobody looked at.**

`court_png.py`'s own docstring says why it exists: *"the print sheet must render
identically in the browser, the in-app preview, AND both PDF engines… the pure-pip
xhtml2pdf fallback only rasterises `<img>` PNG/JPEG."* That is a correct reason
for the **print** path. The interactive page already has a Plotly court
(`helpers/court.shot_chart`, imported by `player_card.py:42`). The print-only
renderer has no business being on the critical path of a live page.

**Fix — and the pattern already exists in this repo.** Last night's Spotlight
change turned an eager `_intel` mine into a `🔎 Mine the league` button and took
24.9 s → 14.3 s. The same shape applies exactly: replace the eager
`download_button` with a two-step **"Prepare player card"** → then the download
button, so the report (and matplotlib) are paid only by the coach who wants the
file. Streamlit's `download_button` needs its data up front, which is precisely
why the two-step is required rather than optional.

Expected: Players cold from ~57 s to roughly ~14 s, with the remaining cost in
`player_stat_table` / RAPM, which is real work.

**Caveat on the absolute numbers.** The profiled run measured 130 s wall-clock
with two background agents on the box; the clean single-process measurement of
the same page was 56.6 s. Treat the *proportions* as solid and re-time the total
on an idle box before quoting a headline figure.

### 6.2 · Two more from the same profile

* **`development.season_lines` is called 312 times for 13.4 s.** It is reached
  through `_class_curve(gender)` → `DV.class_curve(gender)`, which scans every
  player's season lines to build the league class curve. Cached at 10 minutes,
  but it is an N+1 over the player table and it is paid inside the profile
  render. Worth a single batched query.
* **`reports.player_card_html:241` calls `S.located_shots(player_id=player_id)`
  with no `game_ids` and no season.** The downloadable card's shot chart is
  therefore drawn over **every season and every game**, ignoring both the season
  picker and the entitlement read-filter — while the on-screen card is scoped to
  `_vis_key`. The comment above the download button at `:1480` says the export is
  gated "like the on-screen card"; the *gate* matches, the *scope* does not.
  That is a Part-1-class finding in an export path: a Paid Solo coach's
  downloaded file contains shots from games they may not aggregate on screen.

---

## 7 · Ranked, with the effort

| # | item | § | effort | risk | needs a ruling? |
|---|---|---|---|---|---|
| 1 | **Players: gate the printable card behind a button** | 6.1 | ½ session | low | no |
| 2 | **Percentile pool honesty** — chips carry `of N`, adjective floor below ~10 teams | 2 | 1 session | low | the floor value |
| 3 | **Overview zone C leads with `team_insight_feed` lines** | 1.4 | ½ session | low | no |
| 4 | Un-hardcode the shot-depth league constants (2 captions) | 1.2 | 1 hour | none | no |
| 5 | `insights_deck._next_game` gets `team_card`'s two guards | 1.1 | 15 min | none | no |
| 6 | `default_team` resolution order (user → own team → global) | 1.3 | 1 hour | low | no |
| 7 | **Quarter generators ×5** (start-of-half and opponent-quarter first) | 4 | 1 session | low | no |
| 8 | Scout opens on the next scheduled opponent | 5.2 | ½ session | low | no |
| 9 | `reports.player_card_html` scopes its shot chart | 6.2 | 1 hour | low | no |
| 10 | Four-factor tile labels; drop `0-0` rows; promote 4F-PPP | 5.1 | ½ session | none | no |
| 11 | Season-feed board-jitter suppression | 5.1 | ½ session | low | threshold |
| 12 | `development.class_curve` batched | 6.2 | ½ session | low | no |
| 13 | Trends gets a verdict layer | 5.3 | 1 session | low | no |
| 14 | Delete the stale `TAB n —` banners | 5.4 | 10 min | none | no |

**1, 4, 5 and 14 are the free ones** — an afternoon between them, and 1 is the
largest single speed win found anywhere in this sweep.

---

## 8 · What is not finished

* **Charts → Defense / Offense / Play Style / Situational** were rendered and
  counted but not read block by block. Same for Lab → Advanced / Build / Impact
  Lab and the Roster / Schedule / Share views. Their read-share numbers are in
  §3; their content has not been audited.
* **The Scout read-share number is contaminated by its empty state.** Re-measure
  with an opponent selected before quoting 14%.
* **The Players page has only been profiled, not reviewed.** It shares
  `player_card.py` with the Team Dashboard and deserves its own part.
* **Book B (the live-season fixture) needed a repair** — the relabel left the
  roster rows `archived=1`, so the dashboard rendered empty for every persona
  equally and the Part 1 §1 table's Team Dashboard rows on Book B should not be
  read as a gating result. Fixed in the fixture; the TD half of that matrix
  wants a re-run.
* Rankings, Officials, the engine inventory, the DB audit and the glossary audit
  are separate parts and are still outstanding.

### Method

```
snapshot   sqlite3.connect(live).backup(sqlite3.connect(copy))
render     chdir APP5.0/tracker (secrets-free cwd bypasses auth)
           AppTest.from_file(page, default_timeout=1800)
           seed ta_gender / ta_team / ta_season / td_view / ch_sub / lab_sub
           .run(); assert not at.exception
persona    import helpers.auth as AUTH; AUTH._LOCAL_IDENTITY = <dict>
profile    cProfile around a single cold AppTest.run(), sorted by cumulative
```

Note the season picker is keyed on the option **label** (`"2025-2026"`), not the
value, and `ta_gender` must be seeded too — without it the global `default_team`
in §1.3 opens the page on the wrong league and silently discards `ta_team`.
