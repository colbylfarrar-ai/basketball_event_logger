# Sweep — 2026-09-06 · Part 4: Rankings, Schedule, Hall of Fame — and one pattern that costs every page

Companion to Parts 1 (gating), 2 (Team Dashboard) and 3 (Officiating Lab).
Read-only, measured against a `sqlite3.backup` copy of the live book. **The live
book was never written to.** No application code changed.

Two findings here are bigger than the page they were found on:

* **§1 — forfeits are in the ratings as real games**, and one of them is
  currently published as the league's best defence. 117 games, no handling
  anywhere in the tree.
* **§5 — six printable reports are built eagerly as function arguments**, on six
  different surfaces, and at least four of them drag matplotlib onto the critical
  path. Part 2 found one of them; this is the pattern.

---

## 1 · The Team-leader cards are a forfeit and four one-game teams

Rendered, Rankings → Overview, default filters, girls:

```
Team leaders
  Top rating           57.9   Lincoln Christian Girls          OK 4A · 33-2
  Best offense (PPG)   80.0   Frenship Girls                   N/A   · 1-0
  Best defense (PA/G)   0.0   Mercy Institute Girls            N/A   · 1-0
  Point margin        +59.0   Owasso Preparatory Academy Girls N/A   · 1-0
  Strength of record  59.21   Bishop Gorman Girls              N/A   · 1-0

Signature metrics
  Most dominant          75   Owasso Preparatory Academy Girls · N/A
  Most consistent        66   Oark, Ark Girls                  · N/A
  Clutch king            68   Booker T Washington Girls        · OK 5A
  Hottest               W27   Washington Girls                 · OK 3A
  Luckiest            +10.2   W BEAVER Girls                   · OK B2
```

Four of the five Team-leader cards, and the top Signature card, belong to teams
with a **1-0 record**.

Traced to the games:

```
Frenship Girls          game 22634  2025-12-29   80–33
Owasso Prep Academy     game 23912  2025-12-11   76–17
Bishop Gorman Girls     game 22575  2025-12-22   66–51
Mercy Institute Girls   game 25891  2026-01-06    1–0     <-- a forfeit
```

**"Best defense (PA/G) 0.0" is a forfeit.** The app's league page currently tells
a coach that the best defensive team in Oklahoma girls' basketball allowed zero
points, on the strength of a 1–0 walkover.

### 1.1 · Why: the default min-games filter is 1, over a pool that is a third one-game teams

The filter exists. `pages/5_Rankings.py:687`:

```python
_MIN_GP = (_rkf2.slider("Min games played", 1, int(_rk_maxgp), 1, key="rk_mingp_page")
           if _rk_maxgp > 1 else 1)
```

It is applied correctly at `:790` and the leader cards ride the same filtered
pool (`ov_rows`). The problem is the **default of 1** against this book:

```
games played, across the 704 rated girls teams
    1 game    169 teams        <-- 24% of the pool
    2 games    32
    3 games    13
    4 games    10
    <5 games  224 teams        <-- 32% of the pool
```

361 teams across both genders appear in exactly one finished game. They are
almost all out-of-state and one-off opponents from the OSSAA import — real games,
correctly recorded, and useless as a leaderboard sample.

**Fix, in two parts, both small:**

1. **Default `_MIN_GP` to 5**, matching `MIN_SNAPSHOT_GP`, which is already the
   book's stated floor for "this team has enough of a season to rank". The
   slider still lets a coach drop it.
2. **Give the leader and signature cards their own floor** independent of the
   slider, so a coach who deliberately sets min-games to 1 to look up a specific
   opponent does not get a forfeit crowned as league best.

### 1.2 · The bigger half: forfeits are in every margin-based engine

**`forfeit` appears nowhere in the tree.** Not in the schema, not in
`game_type`, not in `helpers/team_ratings.py`, not in any comment.

Measured on the live book, finished games only:

```
either side scored 0                123
exact 1-0 or 0-1                     19
exact 2-0 or 0-2                     98      (117 of the 123 are one of these two)
either side under 10 points         313
total under 20 points               120
```

The 1–0 and 2–0 notations are the two conventional ways a forfeit is recorded.
117 of them sit in the book as ordinary results, and they feed:

| engine | effect |
|---|---|
| W-L record | **correct** — a forfeit *is* a win |
| PPG / opponent PPG | wrong — one point scored, zero allowed |
| MOV / point margin | wrong — a +1 or +2 game |
| Pythagorean W-L and **Luck** | wrong — both are pure margin math |
| Strength of schedule / SOR | wrong-ish, via the opponent's distorted rating |
| **Power rating** | wrong — "built from results, margin and a class bridge" |

A team that forfeits picks up a loss that reads as an elite defensive
performance; the team that receives it picks up a +2 win that drags its margin
down. Concentrated on teams with few games, which is exactly where the
leaderboards look.

**Proposal.** Add a forfeit marker and honour it:

* detect on import by the 1–0 / 2–0 / 0-points signature and store it — either a
  `games.result_type` column or a new `game_type` value, whichever is cheaper
  given `game_type` is already a free-text-ish enum (`Regular`, `Playoff`,
  `District`, `Tournament`, `Rivalry`);
* count it in **W-L only**; exclude it from PPG, PA/G, MOV, Pythagorean, Luck,
  SOS, SOR and the Power rating;
* show it as `W (ff)` on the schedule so a coach is not left wondering where the
  score went.

The detection rule wants a founder eye first: 2–0 is also a plausible real score
in no other sport, but this app has 98 of them and zero genuine 2-point games, so
the signature is safe here. The `<10 points` and `<20 total` bands (313 and 120
games) should be **reported, not auto-classified** — some are real blowouts.

This is a bigger correctness item than anything in the polish month's list, and
it is invisible until you look at the leaderboards.

---

## 2 · Verdict density on the league surfaces

Same measurement as Part 2 §3 — rendered strings classified as **reads**
(sentences: ≥8 words with a finite verb) or **labels** (chart titles, column
headers, metric names).

| surface | reads | labels | read share |
|---|---:|---:|---:|
| Officiating Lab | 181 | 124 | 59% |
| RK → League landscape | 14 | 14 | 50% |
| RK → Spotlight | 18 | 23 | 44% |
| RK → Compare | 9 | 14 | 39% |
| RK → Tracked | 14 | 27 | 34% |
| RK → Team | 15 | 32 | 32% |
| **RK → Overview** | 11 | 38 | **22%** |
| **Hall of Fame** | 6 | 36 | **14%** |
| **Schedule** | **0** | 22 | **0%** |

Two caveats worth stating, because they change how the table reads:

* **Officiating Lab's 59% is inflated by the app-wide glossary** it appends
  (Part 3 §7.1). Its own content is far below that.
* **League landscape's 50% is inflated by four long captions.** Its body is
  thirteen chart titles — *"Effective FG%"*, *"True shooting %"*, *"Shot volume —
  FGA / game"*, *"Turnover % (lower better)"* … — with no verdict anywhere. On
  block count rather than character count it is one of the weakest.

**The Schedule page emits zero sentences.** Twenty-two labels, no reads at all —
the only surface in the app with a read share of exactly 0%.

---

## 3 · Rankings, view by view

### 3.1 · Overview — a strong page with a broken top

Beyond §1, the view is well built. **Recent results** carries class ranks inline,
which is the right density:

```
2026-03-14  Howe Girls OK 2A #4  50   Vanoss Girls OK 2A #5  42
2026-03-14  Washington Girls OK 3A #1  66   Adair Girls OK 3A #3  33
```

What is missing is the same thing missing everywhere: a read. The view answers
"who is ranked where" and never "what changed this week and why". `helpers/
news_feed.py` and `helpers/league_spotlight.py` both produce league-level
sentences; neither is on Overview.

### 3.2 · Team — the best "verdict" zone in the app, and still not a verdict

Rendered for Lincoln Christian Girls, the Team view's card carries **fifteen**
model reads where the Team Dashboard's equivalent zone carries five: Rating,
SOS/SOR, Adj O, Adj D, vs Top 5, Form Power, Form Δ, Form rank, last-10 strip,
Dominance, Consistency, Clutch, Momentum, Volatility, Ceiling, Floor.

Every one of them is a number under a label. Part 2 §1.4's proposal applies here
with more force, and `_team_insight_lines` (`pages/5_Rankings.py:481`) — the
generator that would fill it — **is already imported by this very page**.

Two smaller notes on this view:

* **`Engine — per 100 possessions: "Track games to unlock the possession
  economy"`** renders on the state's #1 team. The copy is an instruction the
  viewer cannot follow — nobody can track another program's games. For an
  untracked *other* team the line should read "no tracked data for this team",
  which is `MSG_NOT_SHARED`'s neighbourhood, not an upsell.
* The **League percentile profile** is honest here (704-team pool, so
  `Power 74.8 → 100th` is real), which is a useful contrast with Part 2 §2's
  five-team percentiles on the same app. The two pools need to be visually
  distinguishable.

### 3.3 · Tracked — the best writing in the app, in the wrong place

Under a box-score picker, the Tracked view renders an auto-generated post-game
read:

> * **Adair Girls** won **60–31**, in a rout.
> * **Adair Girls** won the four-factors battle 3–1 — shooting (eFG%) (56% vs
>   25%); ball security (TOV%) (21% vs 28%).
> * **Adair Girls** ripped off a **12-0 run** in Q1 — the game's biggest, and it
>   swung the momentum.
> * Top game RATING — 1 (6.8), Hannah Bond (8.2).
> * Game Excitement Index **1.2** — Comfortable.

That is exactly the voice the rest of the app is missing, and it comes from a
dedicated 130-line module, `helpers/postgame.py` (`game_report(game_id)`).

**It reaches exactly two surfaces**: `helpers/box_score.py:478` and
`pages/2_Game_Tracker.py:478`. It is not on the Schedule page, not on the Team
Dashboard's schedule, and — despite `news_feed.py`'s own docstring saying
*"`postgame` generates a game report, `awards` names the standouts"* —
**not in the season feed**, which uses its own thinner `_result_notes`
(`news_feed.py:112`).

**This is the cleanest free win in the sweep.** Three surfaces, one existing
cached engine, and it takes the Schedule page from 0% read share to a page that
tells a coach what happened.

### 3.4 · Compare — good, and one honest gap

The head-to-head table is dense and readable, and it says the right thing when it
cannot answer (*"These two haven't played each other yet"*, *"Four-factor &
efficiency compare needs both teams tracked"*). Two notes:

* The tracked compare is gated by `can_see_team_tracked` (`:3560`), which has no
  past-season archive bypass — so on an archived season it prints
  *"🔒 The tracked four-factor & efficiency compare is **Paid**"* over data the
  app's own open-archive rule says is free. Part 1 §3.3.
* There is no *why* line. The table shows Lincoln Christian ahead on nine of
  eleven rows and never says "this is a shooting mismatch" — which is exactly
  what `insights_severity` does one page over.

### 3.5 · League landscape — thirteen charts, zero reads

*"Every headline team stat"* followed by Effective FG%, How teams score, True
shooting %, Paint scoring, Offense vs defense, Four factors, Who can shoot, Shot
diet, Shot volume, Turnover %, Shooting map, Inside vs outside, Ball movement,
Assisted vs self-created.

It is a good exploration surface and a bad answering surface. The league-level
facts this book can already state as sentences are sitting one module away — the
Winning Formula block on the Team Dashboard produces *"one standard deviation of
ball-security edge is worth 10.8 points of margin, 45% of the four factors' pull
… same lever league-wide"*, and the shot-band table produces *"the 4-ft-to-arc
band is 35.3% of every girls' shot at 0.548 points, against 1.086 at the rim."*
Neither is on the page whose job is the league.

### 3.6 · Spotlight — healthy

Tagging coverage (*Play type 88% · 2,857 of 3,246 shots; Contested 68% · 2,217*),
this week's awards, game of the season with a real GEI breakdown (*lead changes
5, peak swing 59%, biggest comeback from 3% odds*), what the data noticed, and
Notables. Post-gating it renders in 7.6 s. Nothing to fix here; it is the model
for what a league view should be.

---

## 4 · Schedule and Hall of Fame

### 4.1 · Schedule — the only 0%-read surface in the app

Twenty-two labels, no sentences. It is a calendar with scores.

Everything needed to fix it exists:

* `helpers/postgame.game_report(game_id)` for each played game (§3.3);
* `helpers/resume.opponent_ranks` for the at-the-time opponent rank, which last
  night's build already wired into the Team Dashboard schedule and the Rankings
  team view — the overnight doc explicitly named the Schedule page as the
  "nearly free" fourth surface and it was not done;
* `helpers/predictor.predict_game` for unplayed games, which the page already
  calls at `:365` for its preview.

The page also has **zero season handling anywhere in it** (noted in the QOL
survey's B1 and still true) — no season picker, no `season_pick`, so it reads
whatever the engine defaults give it.

### 4.2 · Hall of Fame — 14%, and unmeasured

Six reads, thirty-six labels, 5.3 s to render. The roadmap's note that it "calls
`score_ratings` per season label in a loop — likely slow, unmeasured" is still
unmeasured; 5.3 s on a two-season book is not alarming but scales with every
rollover. The overnight doc named quality-wins-in-the-HoF as a nearly-free
addition on top of `helpers/resume.py`; not done.

---

## 5 · The cross-cutting one: six printable reports built eagerly

Part 2 §6.1 found that the Players page builds its downloadable player card **as
a function argument**, so the report — including a matplotlib shot chart that
costs ~43 s of first-figure warm-up — is built on every render whether or not
anyone clicks download.

It is not one site. It is the house pattern:

| site | report | reaches `court_png`? |
|---|---|---|
| `pages/7_Players.py:1485` | Player card | yes — `reports.py:246` |
| `helpers/box_score.py:419` | Game recap | yes — `reports.py:434` |
| `pages/2_Game_Tracker.py:524` | Game recap | yes — same |
| `helpers/dashboard/scout_tab.py:567` | Scout sheet | yes — `scout.py:979/998/1122/1330` |
| `helpers/dashboard/scout_tab.py:1420` | Scout sheet | yes — same |
| `pages/9_War_Room.py:861` | Matchup one-pager | not traced |

At `scout_tab.py:564` the string is even assigned first —
`html_doc = SC.printable_html(...)` — and then used twice, once for the download
and once for a preview inside an expander, so the build happens before the
expander can decide not to render.

**This is very likely why Scout costs 12.7 s** and why the box score is slower
than its content warrants. `court_png.py`'s own docstring explains that the PNG
path exists because *"the pure-pip xhtml2pdf fallback only rasterises `<img>`
PNG/JPEG"* — a correct reason for the **print** path, and no reason at all to be
on a live page's critical path when the same page already draws an interactive
Plotly court.

**Fix — the pattern already exists in this repo.** Last night's Spotlight change
replaced an eager `_intel` mine with a `🔎 Mine the league` button and took
24.9 s → 14.3 s. Streamlit's `download_button` needs its bytes up front, which is
exactly why a two-step is required rather than optional:

```
[ Prepare scout sheet ]      →   (builds, caches)   →   [ ⬇ Download ]
```

One helper — `helpers/ui.pdf_or_html_download` already exists and is the single
place to add the gate, so **all six sites are fixed by changing one function**
plus the six call sites passing a *builder* (a zero-arg callable) instead of a
built string.

That is the single highest-value engineering item found anywhere in this sweep:
one helper, six call sites, and it removes matplotlib from the critical path of
the Players page, the Game Tracker, the box score and Scout.

---

## 6 · Ranked

| # | item | § | effort | risk | needs a ruling? |
|---|---|---|---|---|---|
| 1 | **`pdf_or_html_download` takes a builder; six sites gated** | 5 | 1 session | low | no |
| 2 | **Forfeit marker + excluded from margin engines** | 1.2 | 1–2 sessions | medium | yes — the detection rule |
| 3 | **Default `_MIN_GP` to 5; leader cards get their own floor** | 1.1 | 1 hour | low | the value |
| 4 | **`postgame.game_report` onto Schedule, TD schedule, season feed** | 3.3 | 1 session | low | no |
| 5 | Schedule gets `resume.opponent_ranks` (the named-but-undone 4th surface) | 4.1 | ½ session | low | no |
| 6 | RK → Team leads with `_team_insight_lines` (already imported) | 3.2 | ½ session | low | no |
| 7 | League landscape gets a verdict block | 3.5 | 1 session | low | no |
| 8 | "Track games to unlock" → "no tracked data for this team" on other teams | 3.2 | 15 min | none | no |
| 9 | Compare's archive bypass (`can_see_team_tracked`) | 3.4 | with Part 1 §3.3 | low | Part 1 §1 |
| 10 | Schedule page gets season handling | 4.1 | ½ session | low | no |
| 11 | Hall of Fame: measure the `score_ratings` loop; add quality wins | 4.2 | ½ session | low | no |

**1, 3, 5 and 8 need no ruling and total about a session and a half.** #2 is the
correctness item and wants a founder eye on the detection rule before anything
is written.

---

## 7 · What is not finished

* **The Rankings glossary view was not audited.** RK → Glossary renders 105k
  characters; whether it defines what this page shows is a Part-5 question.
* **No cold timings in a clean process for Rankings.** The figures quoted (7.6 s
  Spotlight, 2.3 s Overview, 2.8 s Tracked) come from the Part 1 persona matrix,
  which rendered them second-and-later in a warm process. The known page-base
  figure — 7.4 s that every Rankings view pays — was not re-derived.
* **The forfeit analysis stops at detection.** The downstream correction (what
  `score_ratings` should do with a W that has no margin) is not designed.
* **Hall of Fame and Schedule were rendered but not read block by block.**
* **The War Room was not swept at all.** Seven views, and it is the third-densest
  page in the app.
* Parts 5 (engines / buried analytics), 6 (database) and 7 (glossary and
  explainers) are outstanding; two of them are running.
