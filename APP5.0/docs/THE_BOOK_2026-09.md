# HoopTracks — The Book
### One read for September 2026. Everything the sweep found, everything it suggests, and every question it needs you to answer.

Written 2026-09-06 after a ten-part read-only audit (`SWEEP_2026-09-06_INDEX.md`
and Parts 1–10). Every number here was measured against a `sqlite3.backup` copy
of the live book. **The live book was never written to. No application code was
changed.** Branch `sweep-2026-09-06`, unmerged.

This document is the consolidation. The Parts are the working; this is the read.

---

# CONTENTS

**I · Where you actually are** — §1 the verdict · §2 the app by the numbers ·
§3 the constraint that should decide everything

**II · The vision, scored** — §4 OOTP · §5 Synergy · §6 Hudl InStat ·
§7 what nobody else has

**III · What is broken** — §8 correctness · §9 gating · §10 honesty ·
§11 performance

**IV · What to build** — §12 free wins · §13 new analytics · §14 consolidations
and deletions · §15 the rejected list

**V · The month** — §16 week by week · §17 the season autopilot

**VI · Questions for you** — §18 eleven rulings, costed

**VII · Reference** — §19 where everything is · §20 every number in one table

---
---

# I · WHERE YOU ACTUALLY ARE

## 1 · The verdict

**You have built more analytics than you have built ways to read them.** That is
the single sentence this sweep produces.

The engines are excellent and mostly correct — 898 public entry points across 130
helper modules, 853 of which reach a page, referential integrity perfect across
thirty-odd probes, a reliability program that has already killed one of its own
metrics on measured evidence. The Insights deck and the War Room's Matchup view
are as good as anything in commercial basketball software at this level.

What is weak is everything around that: **which numbers a coach is allowed to
see, whether the page says how much data is behind a number, and whether a
sentence appears anywhere near the table.** Those three are the whole gap between
what this is and what it could be, and none of them requires new mathematics.

Nine of the eleven highest-value items in this document are wiring, gating or
labelling. One is new engine code. One is a data-classification decision.

Second sentence, and it is the commercial one: **right now, in the offseason,
a free coach sees the entire paid product.** That is not a bug — it is a rule
with an unhandled regime, and October is when coaches arrive.

## 2 · The app, measured

```
codebase          130 helper modules · 62,245 lines in helpers/ · 15 pages
                  6,800-line Team Dashboard · 3,600-line Rankings
                  898 public entry points, 853 reaching a page
                  290 pytest + 97 run_all script tests, both green

the book          13,363 games · 12,648 finished · 43 tracked
                  7,731 play-by-play events · 77,309 lineup snapshots
                  1,448 teams · 541 players · 70 officials
                  13,793 rating snapshots over 18 weekly boards
                  13.4 MB, no wasted pages

the tracked pool  girls   21 teams · 35 games · 242 players
                  boys     5 teams ·  8 games ·  59 players
                  6 teams have >=5 tracked games. 1 has >=10.

capture quality   shot x/y      100% on every tracked game but three
                  play_type      90% of shots, 63% of turnovers and fouls
                  defense        88% of shots, 89% of turnovers
                  guarded_by     72% (NULL means uncontested — a value)
                  officials     100% of fouls name one
                  turnover_type  on until 2026-01-30, off after
                  hockey_from    0 of 4,019 — never pressed

infrastructure    1 vCPU / 2 GB no-swap droplet, litestream replicating
                  a FastAPI courtside PWA (3,166 lines of JS) + Streamlit app
```

**Read the tracked-pool line twice.** Everything in §10 comes from it.

## 3 · The constraint that should decide everything

You asked for something a single person can hold afloat across a season with
little or no thought. That is a stronger constraint than "make it good", and it
should be the tiebreaker on every item in this document.

It implies four rules:

1. **Nothing that needs a human decision each week survives.** Any feature whose
   correctness depends on you remembering to press something is a feature that
   will be wrong by January. (See §17 — three of these already exist.)
2. **A wrong number costs more than a missing one.** You are the only reviewer.
   A number nobody checks and nobody can question is a liability, and §10 is
   entirely about that.
3. **Every new metric costs forever.** It has to be explained, gated, sampled,
   and kept honest as the book grows. Prefer surfacing one that exists over
   computing a new one — which, conveniently, is where every win has been.
4. **In-season, you touch exactly one surface: the phone.** Everything else has
   to be readable, not operable. The Streamlit app is a *reading* product during
   the season; treat any in-season admin step as a defect.

---
---

# II · THE VISION, SCORED

You named three products. Here is honestly where you stand against each, and
what it would cost to close the gap.

## 4 · OOTP — the management-sim read

**What OOTP actually does that matters here:** it gives you a *roster you can
reason about* — every player as a card of rated attributes with a scouting
opinion attached, a depth chart you can move, and a simulation that tells you
what the moves are worth. The magic is not the numbers; it is that every number
is on a common 0-100 scale with a stated meaning, and the whole thing is one
screen you can sit in.

**Where you are: closer than you think, and let down by presentation.**

| OOTP element | you have | state |
|---|---|---|
| 0-100 rated attributes | OVERALL / OFFENSE / DEFENSE / PLAYMAKING / REBOUNDING / 2WAY / VERSATILITY / Finishing | ✅ built, explained, calibrated (`OVERALL`'s stated ladder **matches** measured percentiles) |
| player cards | `helpers/dashboard/player_card.py`, 1,988 lines | ✅ and it is genuinely good |
| archetypes / player types | `helpers/archetypes.py`, k-means with a gated k | ✅ |
| depth chart + minutes | `helpers/lineup_projection.py`, `rotation_schedule.py`, the Projection tab | ✅ |
| a simulation you can act on | War Room Monte-Carlo, 20,000 games, with an interval | ✅ **best surface in the app** |
| development / progression | `helpers/development.py`, `class_curve`, `project_rest_of_season` | ✅ built, needs two seasons to mean anything |
| **the one screen you sit in** | ✖ | **the gap** |
| **a name on every player** | ✖ 486 of 541 are a jersey number | **the gap** |

**The two gaps are both presentation.**

*The one screen.* OOTP's player page is one dense card. Yours is spread across
the Team Dashboard's Roster view, the Players page, a quick-view dialog and the
Insights deck's player lines — four surfaces sharing `player_card.py` and
disagreeing about what belongs where. Consolidating is §14.

*The names.* Part 7 §2: **486 of 541 players have no name**, only a jersey
number, and seven of the top twelve players in the league render as bare
integers. The league's rebounding leader is "12". This is correct capture — you
do not know the opponent's roster — and catastrophic display. **OOTP with
unnamed players is not OOTP.** One label helper fixes the display; naming them is
a separate, larger question (§18 Q7), and the OSSAA importer cannot help — I
checked, it writes teams and games only, never rosters.

**Verdict: you are ~80% of an OOTP view and 0% of the feeling of one**, because
the feeling comes from names on one screen.

## 5 · Synergy — the play-type product

**What Synergy sells:** every possession classified into ~11 play types, with
points per possession, percentile rank, and frequency, for offense and defense,
for every player and team, with video attached.

**Where you are: you have the classification and the economics. You are missing
the frequency-vs-efficiency framing and the defensive mirror.**

You already compute, on real tagged data:

```
set call      n      open%    PPS       (girls 2025-2026)
spot         873     33.9%    0.828
iso          724     12.6%    0.588
transition   616     35.1%    0.989
putback      298     23.8%    0.859
post         210      8.6%    0.933
blob         178       —      0.637
cut          168       —      0.553
duckin       137     36.5%    1.088
offscreen    132     34.1%    1.227
pnr          123     10.6%    0.764
dho          122     22.1%    0.639
```

That table *is* Synergy's core product. Three things stand between you and it:

1. **The frequency axis is missing from the framing.** Synergy's read is "you run
   iso on 18% of possessions at 0.588 — that is the 12th percentile and it is
   your most-run action." You have both halves and never put them on one line.
2. **The PPP is biased high** (Part 9 §1.1) — turnovers carry the tag at 63%
   while shots carry it at 90%, so every set call reads +0.002 to +0.080 high,
   and the turnover-prone actions (cut, post, transition) are flattered most.
   Fixable by reporting the coverage, then correcting per action.
3. **The defensive mirror exists and is separate.** `helpers/defenses.py` does
   the same work on the `defense` tag. Synergy's power is that offense and
   defense are the *same screen with the axis flipped*. Yours are two tabs.

**And you have something Synergy does not:** `guarded_by_id` gives you a
contest rate per set call, measured at **0.337 PPS for a contest** league-wide.
Synergy infers contest from video; you have it as a logged fact. Iso generating
an open look 12.6% of the time for 0.588 PPS against spot-ups at 33.9% / 0.828 is
a 1,597-shot comparison and it is a better argument than Synergy can make.

**Verdict: you are one framing change and one bias correction from a defensible
Synergy competitor at your level.** That is a week, not a season.

## 6 · Hudl InStat — the video product

**Be honest with yourself here: you are not competing with this and should not
try.** InStat's product is *video tagged to events*. You have no video pipeline,
no clip storage, and a 2 GB droplet.

**But the thing InStat sells underneath the video is a scouting report**, and
that you can beat, because your capture is denser than theirs on the axes that
matter to a high-school coach: on-ball defender, set call, defensive scheme,
possession length, and per-event lineup — 77,309 lineup snapshots.

**What you should take from InStat and what you should refuse:**

| InStat element | verdict |
|---|---|
| clip library keyed to events | **refuse** — no pipeline, no storage, no time |
| the printable/shareable scout report | ✅ **you already have it** (`scout.py`, `printable_html`, the PNG court) and it is good |
| opponent tendency profile | ✅ you have it, and `exploit.defensive_plan` computes a half of it nobody renders (§12) |
| shot map + zone efficiency | ✅ better than theirs — you have tap-captured x/y at 100% |
| a "what to do about it" line under each tendency | **partly** — this is §13 |
| video-linked timestamps | **defer** — one cheap version exists (§13.7) |

**One cheap step toward it that is worth taking.** Every event carries a quarter
and a clock time. If a coach films on a phone and notes the tip-off wall-clock,
you can render *"Q3 4:12 — 12-0 run starts"* as a **timecode a coach scrubs to
manually**. No storage, no upload, no pipeline — a column on the play-by-play and
a "film offset" field on the game. That is 80% of the value of clip linking for
about a day of work, and it is the single highest-leverage InStat-adjacent
feature available to you.

## 7 · What you have that none of them do

Worth writing down, because it should shape what you protect:

1. **The Coaches' Co-op.** A reciprocal share-to-scout pool is a genuinely novel
   distribution mechanism for a market where nobody has data. Synergy sells you
   data; you make coaches make it together. **This is the business.**
2. **The reliability program.** `helpers/reliability.py` holds *measured
   split-half reliabilities*, and there is a case on record — the on/off-offense
   card, measured at −0.21, found unreliable, and the code **rewired to gate on
   RAPM agreement**. No competitor at this level publishes a metric's reliability,
   let alone kills one over it. Say this out loud in marketing.
3. **The point-in-time résumé.** Quality wins counted *at the time*, off 18
   backfilled weekly boards. Every product that ships "wins vs top 25" computes it
   against today's board, and on your book **71 of 102 teams get a different
   count**. That is a real edge and it is already built.
4. **The auto-generated post-game read.** `postgame.game_report` writes better
   prose than most human recaps and reaches two surfaces (§12).
5. **The severity model.** "points at stake × measured reliability × sample" as
   the ranking function for findings is a better idea than anything Synergy or
   InStat does with prioritisation.

---
---

# III · WHAT IS BROKEN

Ranked by what a coach meets first.

## 8 · Correctness

### 8.1 · Forfeits are in the ratings as real games — **the biggest one**

The word "forfeit" appears **nowhere** in the codebase. The book carries:

```
finished games with a zero on one side      123
exactly 1-0 or 0-1                           19
exactly 2-0 or 0-2                           98      (117 of the 123)
games with a side under 10 points           313
```

Every one counts correctly in W-L and **wrongly** in PPG, points allowed, MOV,
Pythagorean, Luck, strength of schedule and the Power rating (which is "built
from results, margin and a class bridge").

Consequence on screen today, Rankings → Overview, default filters:

```
Best defense (PA/G)   0.0   Mercy Institute Girls   N/A · 1-0
```

That is game 25891, a 1–0 walkover, published as the best defensive team in
Oklahoma girls' basketball.

**Fix:** a forfeit marker set on import from the 1–0 / 2–0 signature (safe on this
book — 98 games at exactly 2–0 and no genuine 2-point games), counted in W-L only,
excluded from every margin engine, displayed as `W (ff)`. **Needs your ruling on
the detection rule** (§18 Q2).

### 8.2 · The one-game leaderboards

169 of 704 rated girls teams have played **exactly one game**; 224 have fewer
than five. `_MIN_GP` defaults to **1**. So four of the five Team-leader cards and
the top Signature card belong to 1-0 teams. The slider exists and is applied
correctly — the default is the bug. Hall of Fame already does this right, with
the floor stated in the heading (`min 10 games`, `min 25 games`).

### 8.3 · Two engines that answer the same question differently

* **`_next_game`.** `team_card`'s version guards on `date >= today` and on the
  season being current; `insights_deck`'s does neither. Adair Girls' Insights
  masthead currently reads **"next: at Salina Girls 2025-12-05"** on a season that
  ended in March, while the Overview card correctly shows nothing.
* **`can_see_team_tracked` vs `tracked_gate`.** On an archived season Rankings →
  Team hides the tracked rank in the header (`:1161`) and renders the full tracked
  deep dive immediately below it (`:1405`). Compare shows a literal
  **"🔒 The tracked four-factor & efficiency compare is Paid"** over data the
  app's own rule says is free.

### 8.4 · Three hardcoded league constants that disagree with each other

```
insights_identity.py:252   "0.60 points per shot against 1.14 at the rim"
shot_diet.py:427           "0.55 points a trip, against 1.09 at the rim"
shot_kinds.py:761          computed from the book — 0.548 / 1.086 girls
                                                    0.675 / 1.318 boys
```

`shot_diet`'s numbers are the **girls'** numbers, shown verbatim to boys teams
where the rim is worth 1.32. `insights_identity`'s pair matches neither.
`shot_kinds.py:749-755` even carries a comment explaining that an *earlier*
version of this same hardcoding was replaced with the computed version — the fix
was applied to the evidence line and not to the two headers above it.

### 8.5 · A new coach lands on a stranger's team

`app_settings` carries a bare global `default_team` row (`SEQUOYAH (CLAREMORE)
Boys`) alongside the per-coach keys, and `get_setting` falls through to it. So
the "land on your own program without ever visiting Settings" fallback at
`6_Team_Dashboard.py:421-431` **never runs**.

### 8.6 · The War Room's headline tool opens empty

Lineup Creator's team picker is ranked and defaults to index 0. The #1 team has
no tracked data; **21 of 704 options produce anything**; the first that works is
#22. It is Paid-gated, so the coach paying for it meets the empty state.

### 8.7 · The empty read-filter class

`stats._game_filter` was fixed to treat `None` and `[]` differently. **35 caller
sites still convert `[]` → `None` themselves** before the engine can be right.
Most are safe by caller; four are not, one of them inside an engine
(`player_edge.py:51`). A cache key does the same thing
(`player_ratings.py:1232`). `tracker/test_read_filter_empty_scope.py` is written
and **fails on `main`**.

### 8.8 · Smaller, all confirmed on today's book

* nine duplicate games, all still present, all untracked (so W/L, SOS and
  rating snapshots only)
* **thirteen duplicate teams** — one school under two names, splitting 67 games
* `games.id=4` carries 61 events and `tracked=0`
* a duplicate `#4` jersey on team 1
* game 22350 sits unscored in a completed season
* `possession_secs` has 1,321 zeros and one 275-second "possession"
* `reports.player_card_html` draws its shot chart over **every season**, ignoring
  both the season picker and the entitlement filter, inside a Paid-gated export

## 9 · Gating

### 9.1 · The offseason hole

`default_read_season()` = `2025-2026`. `_is_past_season()` calls that PAST. Every
archive-bypassed read gate returns `None` = unrestricted. Rendered persona by
persona, **a free-solo coach is byte-identical to admin on 20 of 24 surfaces**,
including the whole 202,706-character Players page.

The open-archive rule is right and was written assuming a live season sits beside
the archive. Between a rollover and the first game of the new year the archive
**is** the product — a four-month window that covers October.

Three closes, ascending: a **rolling window** (archive opens when the new season
tips off or on 1 December, whichever first — one predicate); gate on "does a live
season exist yet"; or a **depth-tiered archive** (past seasons open at box level,
tracked depth still Paid). The first is cheap and correct; the third is the right
long-term product and is a real project.

### 9.2 · Provenance never enters the read filter

Your ruling: *Paid gets own-team depth **and own creation of tracked data**.*
`games.tracked_by` records who logged a game and is read by exactly one function,
which decides what to **share**, never what its author may **read**.

```
tracked games                                43
own-TEAM games                               24
games this coach LOGGED                      28
logged but NOT their own team                19
  ...and not pooled either                   14      <- invisible to them
```

**14 of 43 tracked games — a third of the book — were typed in by this coach and
cannot be read by them** as a Paid Solo coach. Eight are ADAIR Boys: the same
person tracks that team, is not rostered on it, and cannot read their own work.
Turning the co-op on is the only way back, which inverts the pitch — share in
order to read something nobody else contributed.

### 9.3 · The box score is not Free

`entitlement.py`'s first sentence is *"Box score + final results are Free and
visible to everyone, always."* `render_box_score` gates at `:362` and every box
table below it (`:473`, `:493`, `:524`) is behind the gate. A Free coach on a
current-season tracked game gets a scoreboard and a padlock, and the view only
exists for tracked games at all.

**This is the funnel, and it is the paywall.** §12.2 has the layout.

### 9.4 · Three page-level gates that ignore the archive rule

Officials `:219`, Hall of Fame `:504` and Team Dashboard Projection `:6038` hard-
stop for Free with no archive bypass, while War Room `:256` guards correctly with
`if _is_cur_season and not has_paid_plan`. Today Free gets the War Room, the
Insights deck and the whole Players page for free, and is locked out of the
Officiating Lab.

### 9.5 · Leaks

* **`season_wpa` has no `game_ids` parameter at all** — it builds its own pool
  from `games WHERE tracked=1 AND season=? AND gender=?`. Five consumers. On this
  book that is **43 tracked games where the pool is 11**, so a league-wide coach's
  Def WPA leaderboard **names players from teams that chose Solo**.
* `visible_tracked_game_ids` does not check the plan, despite its docstring
  saying a Free viewer gets an empty set. Measured: a Free league-wide coach gets
  29 game ids. Latent — every caller gates upstream — but it is the function whose
  whole job is to be the teeth.

## 10 · Honesty — the one most likely to lose a coach

Seven findings across four pages are the same finding: **the app publishes
numbers whose sample it does not disclose.**

| where | what it says | what it means |
|---|---|---|
| TD glance strip | `DRtg 96.1 · 80th pct · elite defense` | 2nd of **5** tracked boys teams |
| TD glance strip | `DRB% 62.0 · 0th pct` | last of 5 |
| Insights, THE FIVE | *"elite on the offensive glass (0.6 OREB/g)"* | 0.6 rebounds a game |
| Rankings leaders | `Best defense (PA/G) 0.0` | a **1–0 forfeit** |
| Officiating Lab | `MOST LENIENT 0.0 · Mike Gaskins` | **one foul, total** |
| Officiating Lab | `BEST SHARED CREW 55 · White Bald` | **a hair colour** |
| Players superlatives | `REBOUNDING 80.7 · 12` | **a jersey number** |

The mechanism is now identified: **`cards.pctile_bar` — the app's most-reused
explanation primitive, 13+ call sites — has no pool-size parameter at all**, so a
percentile bar from five teams is visually identical to one from 748. Boys team
percentiles land on exactly {10, 30, 50, 70, 90}.

Four rules fix all seven:

1. **Every percentile carries its pool** — `80th of 5 tracked`, six characters.
   Below a floor (~10) show the **rank**; a rank of 5 is a fact, a percentile of
   5 is not.
2. **Superlatives need an absolute gate** — "elite" must require a rate that is
   elite in basketball, not first in a five-team sample.
3. **Hero cards need a minimum sample**, and one card per subject so one player
   cannot fill seven of eight slots.
4. **Never render a placeholder as a name** — not a jersey number, not "White
   Bald", not "Bald Bald".

`reliability.MEASURED` and `cards.conf_dot` already exist. The machinery is built
and not wired to the places that need it most.

**And two calibration errors, measured:** `ShotRating`'s "50 = average" anchor is
off by 7–15 points on a book that shoots 34.7%; `VPS`'s "~1.0 breaks even" is
actually the **75th percentile** against a median of 0.67. `OVERALL`'s ladder, by
contrast, matches — which is why each had to be measured.

**Plus two abbreviation collisions.** `Leverage` is defined twice in `STAT_DEFS`
for unrelated concepts. And `SCE` is worse: the glossary defines it as
Self-Creation % (and the `ScEff` entry explicitly warns *"NOT the same as SCE"*)
while `defenses.py`, `box_score.py`, `insights_tab.py` and the Team Dashboard all
use the key `SCE` to carry **Scoring Efficiency**. Tap the stat key on the
Players page and you learn the wrong metric from the app's own glossary.

## 11 · Performance

```
Players                56.6 s cold      <- slowest surface in the app
TD / Overview          21.6 s           (first render = whole page cold)
TD / Insights          17.8 s
TD / Scout             12.7 s
RK / Spotlight          7.6 s
TD / Projection         6.7 s
Hall of Fame            5.3 s
everything else        < 4 s
```

Multiply by 2–3× for the droplet.

**One pattern explains most of it.** Six printable reports are built **eagerly as
function arguments** — the report is constructed on every render whether or not
anyone clicks download:

```
pages/7_Players.py:1485            Player card        -> reports.py:246  -> matplotlib
helpers/box_score.py:419           Game recap         -> reports.py:434  -> matplotlib
pages/2_Game_Tracker.py:524        Game recap         -> same
helpers/dashboard/scout_tab.py:567 Scout sheet        -> scout.py:979    -> matplotlib
helpers/dashboard/scout_tab.py:1420 Scout sheet       -> same
pages/9_War_Room.py:861            Matchup one-pager
```

`court_png._light_court` costs **43 seconds** the first time it is touched in a
process — matplotlib import, backend init, font cache. That is 43 of the Players
page's 56.6 s, for a figure nobody looked at, on a page that already draws an
interactive Plotly court.

**All six are fixed by one change**: `ui.pdf_or_html_download` takes a *builder*
(a zero-arg callable) and gates it behind a "Prepare" step — exactly the shape of
the Spotlight button that took 24.9 s → 14.3 s last week.

**Two more, both free:**

* **`ANALYZE` has never been run on this book.** The planner picks
  `idx_games_season` (13,362 rows) over `idx_games_tracked` (43 rows) for
  `WHERE tracked=1 AND season=?` — measured **1.55 ms vs 0.04 ms**, on a predicate
  that appears at **74 sites**. Five minutes of work.
* **`clear_data()` still nukes the whole process.** The scoped cross-process
  bump was built and works, and `clear_settings()` correctly clears nothing for
  preference writes — but `ui.py:176` still calls `st.cache_data.clear()`
  unconditionally *before* the scoped bump. Streamlit is one process for all
  sessions, so a roster save still cold-busts every coach on the box. The scoping
  currently decides who *notices* a nuke that already happened. The real fix is
  the per-function `.clear()` over a registry that the QOL survey proposed.

---
---

# IV · WHAT TO BUILD

## 12 · Free wins — engine done, surface missing

### 12.1 · Put the post-game read where a coach reads (1 session)

`postgame.game_report` writes this, today, unprompted:

> *Adair Girls won 60–31, in a rout. Adair Girls won the four-factors battle 3–1
> — shooting (eFG%) 56% vs 25%; ball security (TOV%) 21% vs 28%. Adair Girls
> ripped off a 12-0 run in Q1 — the game's biggest, and it swung the momentum.
> Game Excitement Index 1.2 — Comfortable.*

It reaches **two** surfaces. It is absent from the **Schedule page — the only
0%-read surface in the app, 22 labels and not one sentence** — from the Team
Dashboard's schedule, and from the season feed, despite `news_feed.py`'s own
docstring saying *"`postgame` generates a game report"*.

### 12.2 · The Free box score (2 sessions) — **do this before October**

Split `render_box_score` into three stages instead of one gated function:

```
hero      scoreboard, date, venue, FINAL                       always
BOX       per-player counting lines, team totals, shooting %,
          quarter scores, the SHOOTING four-factor terms        always (Free)
          — no possessions, no ORtg/DRtg/Pace/PPP
          — no SMOE/xPPS/ShotRating (tap-captured shot quality)
DEPTH     everything currently below :362                       Paid
```

The player-level version of that list already exists —
`player_ratings.EVENT_DERIVED_STATS`, which already puts `PPP` and `TOV%` in the
Paid set with your possession carve-out written in the comment. **The team-level
equivalent does not exist and is the actual work.** Call it `TEAM_EVENT_DERIVED`
and put it next to its sibling so the two cannot drift.

### 12.3 · Overview's "Verdict" zone leads with a verdict (½ session)

`team_card.py:531` renders a header that says **"Verdict — model reads"** over
five key-value rows and no sentence. `team_insight_feed` is cached league-wide,
already consumed by Rankings and the War Room, and produces this for the same
team:

> **Turnover factory** — forces a takeaway on 36% of opponent possessions, tops
> in the field; the defense feeds the offense.
> **Q1 team** — they win the q1 by +10.4 points/game (+3.4 vs their other
> quarters); that's where the game breaks open.

### 12.4 · Two computed keys nobody reads (½ session)

* **`exploit.defensive_plan["their_leaks"]`** — documented, computed every call,
  read by nothing. The War Room renders its siblings `throw` and `avoid` (6–11
  possession rows) and drops the one half that answers *"what should my offense
  attack"* (106–842 possessions). **Three lines.**
* **`situational.player_margin_scoring`** — no renderer. Four Adair bench players
  score **63–94% of their points in garbage time**, one at 94.1% with a 2.4%
  close-game share. A coach deciding who to trust late has that computed and
  hidden.

### 12.5 · The passing graph is one `continue` away (½ session)

`passing_chains.py` is complete and tested and returns nothing on every call,
because every entry point drops rows with a NULL hockey tag — and that tag is
NULL on **0 of 4,019 shots**. The 2-node passer→shooter edge it does not need is
fully captured: **2,678 shots, 780 edges, 54 at ≥10 shots, 29 of them team 1's.**
Make the hockey tag optional.

### 12.6 · The play-type axis nobody passes (½ session)

Both live call sites of `shot_kinds.kind_by_shot_tag` hardcode `"defense"`.
`"play_type"` is never supplied. League-normalized: Adair's post-ups reach the rim
**71% against a 50% league rate**, and their off-screen actions land **16pp less
arc-three and 12pp more 4-to-19ft** — the curls get caught short in the dead zone.

### 12.7 · The schedule's at-the-time opponent rank (½ session)

Named "nearly free" in the overnight doc after `resume.py` shipped, and not done.
Same for quality wins on the Hall of Fame.

## 13 · New analytics the data supports

### 13.1 · Shot-clock state ★ — the best unbuilt read in the app (1 session)

`possession_secs` is non-NULL on 100% of rows and is read in twelve files —
**only ever as a mean**. Bucketed over 5,341 clean possessions:

```
early (<7s)    n=1,385    PPP 0.731
mid (7-15s)    n=2,213    PPP 0.570
late (16-35s)  n=1,755    PPP 0.597
```

**The middle of the shot clock is worse than the end of it.** Nobody expects
that. It survives both gates:

* split-half by alternating game date — early 0.727 (n=737) vs 0.735 (n=648);
* excluding every transition possession — early still 0.674 vs mid 0.566 and late
  0.597 (transition is 39.0% of early, 21.5% of mid, 1.1% of late).

Build it as a `_t_clock` generator on the `_t_quarter` template, section
*Why we win / why we lose*, evidence destination `("Charts", "Situational")`.

### 13.2 · Quarter reads ×5 — the only item needing new engine code (1 session)

The roadmap says the deck has zero quarter reads. **It has one** — `_t_quarter`
is registered, routed and firing (*"Q1 team — they win the q1 by +10.4
points/game"*). The gap is the other five, against a Charts → Quarters tab with
~20 charts and a 22% read share:

| metric key | the sentence |
|---|---|
| `Q shooting` | "they shoot 8 points of eFG better in the second half" |
| `Q ball security` | "the fourth quarter is where they give it away" |
| `Q pace` | "they play four possessions a game faster in the first" |
| **`Half starts`** | Q1 and Q3 openings — the post-halftime read you can act on |
| **`Q scout`** | "they win the third" — the feed is already league-wide |

### 13.3 · The 4-foot cliff, as a plan rather than a read (½ session)

```
band          girls share   girls PPS    boys share   boys PPS
rim 0-4ft        25.8%        1.086        29.6%       1.318
4ft-arc          35.3%        0.548        32.3%       0.675
arc 3            21.3%        0.828        26.0%       1.088
deep 3           11.7%        0.772        12.0%       1.281
```

A girls' team moving one shot a game from the dead band to the rim gains **0.54
points**. Ten shots a game is **+5.4** — larger than any single four-factor edge
the Winning Formula prices. The app *says* this; it does not turn it into a
target: *"you take 88 from that band; a league-average diet at your volume is
113; each one converted to a rim attempt is worth +0.54."* That is a season goal.

### 13.4 · Contest × set call (½ session)

The contest is worth **0.337 PPS** league-wide (contested 0.745 on n=2,891,
uncontested 1.082 on n=1,128) — independently reproducing the 0.34 on record.
Open-look rate by set call varies four-fold. Both halves exist
(`playtypes.py:698` counts `open`; `breakdown.py` does four factors per tag); the
**cross** is unbuilt. Flag `offscreen` (n=132) and `duckin` (n=137) rather than
ranking them.

### 13.5 · Synergy framing: frequency × efficiency on one line (1 session)

Every play-type read becomes *"iso — 18% of your possessions, 0.588 PPP, 12th
percentile, and your most-run action"*. You have all four numbers and never put
them together.

### 13.6 · The defensive mirror on the same screen (1 session)

`defenses.py` already does the offensive engine's work on the `defense` tag. Put
them on one screen with a flip, the way Synergy does, instead of two tabs.

### 13.7 · Film timecodes — the cheap InStat step (1 day)

A `film_offset` field on `games` (wall-clock at tip) plus the existing quarter +
clock on every event yields a scrub timecode on any play-by-play row and on every
Insights evidence line. No storage, no pipeline. *"Q3 4:12 — the 12-0 run starts
here"* next to a number a coach is already reading is most of what clip linking
is for.

### 13.8 · Rotation, honestly (½ session)

You have **626 stints across 12 players over 25 games**, median stint 22 events,
median 13 lineup changes a game. Unit-level on/off is honest for team 1's **top
~8 units** (8 at ≥100 events, 4 at ≥400) and dishonest for the other 72. What is
missing is not an engine — `rapm.py` and `lineups.py` exist — it is a **stated
minimum-events gate** so the 72-unit tail never renders.

## 14 · Consolidations, deletions and the things to merge

**Consolidate:**

1. **The player view, into one screen.** `player_card.py` is shared by the Team
   Dashboard Roster view, the Players page, a quick-view dialog and the Insights
   deck's player lines — four surfaces disagreeing about what belongs where. One
   OOTP-style card, one route in, everything else linking to it. (§4)
2. **One lock ladder.** Six copies of the Free/banned/Solo/not-shared message
   ladder exist (`Rankings:83`, `box_score:368`, `War_Room:489`, plus
   `tracked_gate` itself and two page-local variants). One
   `entitlement.lock_reason(ident, team_id, season)` retires all of them — and
   makes the §9.1 ruling a one-line change instead of a six-site change.
3. **One label helper.** `player_label(row)` → a real name, or `#12 · Kansas
   Girls`, never a naked integer and never `#12 12`.
4. **One minimum-sample floor**, stated in the heading, the way Hall of Fame
   already does it. The Officiating Lab currently runs **three different floors
   on one screen** (min 1 game, min 2 games, `RATING_MIN_GAMES = 3`).
5. **One `_next_game`.** Two implementations, one wrong.
6. **The glossary's `SCE`/`ScEff` and duplicate `Leverage`.**

**Delete or retire (all traced, none on a "zero call sites" claim):**

* `insights_brief.render` — ~135 lines of dead renderer; six modules import the
  file and every one takes only its private helpers.
* `team_insights.team_insights` (superseded, byte-identical output, plus a bare
  `season="Current"`), `simulation.simulate_tournament`, `courtside.late_game`,
  `stats.stocks` / `paint_fga` / `app` / `team_game_ids`.
* `cards.gauge_range`, five `helpers/ui.py` functions (`gauge`, `kpi`, `chip`,
  `loading`, `season_picker`), `reliability.band_level`, `stat_kpi()` (defined,
  never called). **Not `clear_settings`** — it is new, correct, and the reason a
  theme toggle no longer cold-busts the whole box.
* **Keep, deliberately:** `hybrid_ratings` (calibration says keep it off),
  `crew_foul_rate` (its docstring says "do not put it on screen", r = −.254),
  `lineups.player_on_off` (buried on purpose — offensive half anti-correlates
  with itself at −0.213). **Record these as decisions, not oversights**, or a
  future sweep will "fix" them.

### 14.1 · OSSAA Import — correctly built, and the origin of two data problems

Swept last, and it comes out well. It is **admin-only** (`:31`) with the right
reasoning stated — it bulk-writes teams and games into the *shared* league DB
that feeds every coach's rankings — and it carries a genuinely good guard that
most importers would miss: **OSSAA team-ids are season-specific**, so a stale id
silently imports the wrong year, and the page hard-drops any game outside the
active season's date window.

Three findings:

* **It writes teams and games only. It never touches `players`.** So there is no
  cheap import-based fix for the 486 unnamed players — Q7 has to be answered on
  its own terms. *(This corrects Part 7 §5 item 4, which listed "measure whether
  `ossaa_sync` carries rosters" as an open hour of work. It does not.)*
* **`merge_teams` is exposed only here**, which is right for an admin action —
  and it is the documented root cause of the mirrored duplicate games
  (`game_dedup.py:206-207`: *"Root cause is `ossaa_sync.merge_teams`, not the
  importer. The importer's guard checks both home/away orientations and is
  sound."*). So §8.8's 9 duplicate games and 13 duplicate teams are the same
  story, and the tool to resolve both already lives on this page.
* The whole duplicate class becomes *impossible* rather than *repairable* with
  `UNIQUE(date, team1_id, team2_id)` on `games` — which is blocked on the repair
  **and** on a ruling nobody has made: **are legitimate same-day rematches
  possible?** A tournament that plays the same pairing twice in one day would
  violate a strict constraint. Add that to §18 if you want it settled.

**Also delete:** the stale `TAB n —` banner comments in `6_Team_Dashboard.py`
(the RENDER MAP at `:1631` already does their job and they now actively lie —
`TAB 7 — INSIGHTS` sits above `if _tdview == "Lab"`), and the module docstring
listing five tabs where there are ten.

**Convert:** `pages/11_Setup.py:79` is the last `st.tabs` on a heavy page, and
it runs a **1,448-row editable dataframe** and a 500-row games table on every
rerun regardless of which tab is open. The `_seg` conversion is the fix and it
needs the AST sweep for cross-tab variable leaks first.

## 15 · The rejected list — measured, and do not build

Written up so nobody spends a session rediscovering them.

**In-stint fatigue — no effect on this book.** The naive read looks like
*anti*-fatigue because your best players get the longest stints (0.713 → 0.769 →
0.756 → 0.912 by stint depth). Normalizing within player does not rescue it:

```
POOLED (10 players, equal weight)   early n=665 PPP 0.747   late n=890 PPP 0.806   +0.058
```

**Seven of ten players are better late in a stint.** There is no signal. A "sub
him, he's tired" read would be invented. Revisit only with real on-floor minutes
(`possession_secs` accumulated, not event counts) and a bigger book.

**Per-official whistle profiles — the sample does not exist.** 70 officials,
1,115 fouls, 100% attributed, and the busiest has worked 4–5 games. 135 official
pairs exist and 4 have been seen three or more times. This is a **wait**, not a
fix: officials are career-long and never archived at rollover, so three seasons
puts the busiest past 15 games.

**Shooter × defender matchups — one qualifying pair.** *Defender-level* shot
defense IS supportable for ~12 players (12 at ≥50 shots defended, PPS allowed
spanning 0.400 to 1.259 — a 0.86 spread, well beyond the 0.337 a contest is
worth). Publish **tiers, not ranks**, and never past the 27 at ≥30. The
individual grid needs a different sampling regime.

**Timeout impact — 22 timeouts over 4 games.**

**Not capturable at all:** hockey assists / 3-node chains (0 tagged), foul KIND
(column dropped by your ruling 2026-09-05), PHYSICAL rating (0 of 541 have height
or wingspan), position-based depth reads (`players.position` blank on all 541),
home/neutral splits (`games.neutral` constant 0), rebound location.

---
---

# V · THE MONTH

## 16 · Week by week

Sequenced so the commercially-urgent work lands before October, the rulings
unblock the second half, and nothing depends on you remembering anything.

### Week 1 — the funnel, and the free hours

*Goal: a Free coach gets something real, and the app stops embarrassing itself.*

| | item | effort | §|
|---|---|---|---|
| Mon AM | `ANALYZE` on the book | 5 min | 11 |
| Mon AM | `insights_deck._next_game` gets its twin's guards | 15 min | 8.3 |
| Mon AM | Un-hardcode the two shot-depth captions | 1 hr | 8.4 |
| Mon AM | `default_team` resolution order | 1 hr | 8.5 |
| Mon AM | Duplicate `Leverage` + the `SCE` key collision | 1 hr | 10 |
| Mon AM | `coverage.py` gains `turnover_type` + `shot_created_by_id` | 1 hr | 9 |
| Mon PM | `ui.pdf_or_html_download` takes a builder — six sites | 1 session | 11 |
| Tue–Wed | **Free box score** — the split + `TEAM_EVENT_DERIVED` | 2 sessions | 12.2 |
| Thu | `player_label()` — no bare jersey numbers anywhere | ½ session | 10 |
| Thu | War Room Lineups defaults to your own team | ½ session | 8.6 |
| Fri | Empty read-filter sweep — 35 sites (**test already fails on main**) | 1 session | 8.7 |

**End of week 1 the app is measurably faster, stops publishing hair colours and
jersey numbers as names, and has a real free tier.**

### Week 2 — honesty, then the offseason ruling

*Goal: every number on screen discloses its sample. Then close the gate.*

| | item | effort | §|
|---|---|---|---|
| Mon–Tue | Percentile pool honesty — `pctile_bar` gains a pool arg; floor below ~10; superlative gates | 1 session | 10 |
| Tue | Hall of Fame's stated-floor pattern onto Rankings / Players / Officials | ½ session | 8.2 |
| Wed | Officials: placeholder names, `rated_games` floor, sample chips | 1 session | 10 |
| Thu | **The offseason archive ruling** → implement (one predicate if rolling window) | ½ session | 9.1 |
| Thu | `lock_reason()` — retire six copies of the ladder | ½ session | 14 |
| Fri | `can_see_*_tracked` get the archive bypass; the three page-level gates match the War Room | ½ session | 9.4 |

### Week 3 — the reads

*Goal: the app starts talking. This is the week that changes how it feels.*

| | item | effort | §|
|---|---|---|---|
| Mon | **Shot-clock state** — the best unbuilt read | 1 session | 13.1 |
| Tue | `postgame.game_report` onto Schedule, TD schedule, season feed | 1 session | 12.1 |
| Wed | Overview zone C leads with `team_insight_feed` | ½ session | 12.3 |
| Wed | `their_leaks` + `player_margin_scoring` rendered | ½ session | 12.4 |
| Thu | Quarter generators ×5 | 1 session | 13.2 |
| Fri | The passing graph + the play-type axis | 1 session | 12.5–12.6 |

### Week 4 — correctness, consolidation, and the season switch

*Goal: the book is clean and the app can run without you.*

| | item | effort | §|
|---|---|---|---|
| Mon | **The forfeit ruling** → marker + exclusion from margin engines | 1–2 sessions | 8.1 |
| Tue | **Own-creation entitlement** (`tracked_by` in the read filter) | 1 session | 9.2 |
| Wed | `season_wpa` takes `game_ids`; the 23 engine-layer season defaults | 1 session | 9.5 |
| Wed | Merge the 13 duplicate teams; resolve the 9 duplicate games; flip `games.id=4`; fix the `#4` jersey | ½ session | 8.8 |
| Thu | **§17 — install the timers.** Rollover, backup verification, `ANALYZE` | ½ session | 17 |
| Thu | The player view consolidated into one screen | 1 session | 14 |
| Fri | Deletions, the stale banners, and the decision-record for what stays buried | ½ session | 14 |

**Deferred past September, deliberately:** Setup's `st.tabs` conversion (needs
the AST sweep), the depth-tiered archive, film timecodes, the Synergy framing and
the defensive mirror. All of them are better done when the season is running and
you can see what you actually reach for.

## 17 · The season autopilot — what must run without you

This is the part of your brief that no Part covered, and it is the one that
decides whether November is pleasant.

**Three things that must be timers, not memories:**

1. **`tools/auto_season_rollover.py` is written and NOT installed.** It is
   idempotent, forward-only, calendar-driven off the 1 October cutoff, and runs
   the same path as the New Season button. **Install the systemd timer.** If you
   do not, the season rolls when you remember, and everything downstream of
   `season='Current'` is wrong until you do.
2. **`ANALYZE`** — add it to the same nightly timer. It is free and the planner
   drifts as the book grows.
3. **Backup verification.** You have litestream replicating and a backup
   download in Settings. Neither tells you it is *working*. A weekly job that
   restores the replica to a temp path and counts rows is twenty lines, and it is
   the difference between having backups and believing you do.

**Three things that must stop being manual:**

4. **The rating-history rebuild.** All three résumé surfaces are empty until
   someone presses "Rebuild rating history". That press is a memory, and memories
   fail in January. Fold it into the nightly timer.
5. **Living recal.** It is in the admin block behind an expander. Decide whether
   it runs on a schedule or never; an "occasionally, when I remember" model
   produces constants nobody can date.
6. **The retag backlog.** The Event Editor knows exactly which games are
   untagged and shows it — *"Play calls tagged 0% · 0/83"* — and nothing else in
   the app does. Surface that count on the Team Dashboard schedule and in the
   season feed, with a link. Otherwise ten playoff games sit untagged and you find
   out in September, which is what happened.

**One thing to watch, not automate:** the droplet is 1 vCPU / 2 GB with no swap,
and the constraint is CPU plus the global cache clear on live-game writes, not
RAM. §11's `clear_data()` finding matters most on a Friday night with three games
being tracked at once. The Settings admin block already has "Coaches online &
server capacity" — that is the panel to look at, and it is the one in-season
manual check worth keeping.

**In-season, the coach-facing loop should be exactly this:** open the PWA, log
the game, press End Game. Everything else — pooling, ratings, snapshots,
insights, the résumé, the recap — happens without a second surface being touched.
It very nearly does today. The gaps are the rating-history rebuild (#4) and the
retag prompt (#6).

---
---

# VI · QUESTIONS FOR YOU

Eleven rulings. Each has a cost either way; none of them is mine to make.

### Q1 · The offseason archive regime *(blocks all of §9)*

Today the archive is 100% of the product for four months a year, and Free sees
everything.

* **A · Rolling window** — the previous season opens when the new one tips off,
  or on 1 December, whichever comes first. One predicate. Costs nothing, keeps
  the funnel argument, and a coach can read the rule on a pricing page.
* **B · Gate on "does a live season exist"** — simpler, but shuts the archive for
  the whole offseason and loses the funnel.
* **C · Depth-tiered archive** — past seasons open at *box* level to everyone,
  tracked depth stays Paid. Best product, most work, touches every bypass site.

**My recommendation: A now, C as a Q1-2027 project.**

### Q2 · The forfeit detection rule *(blocks §8.1)*

Is `1–0 / 2–0 / a zero on one side` a safe automatic classification on your book?
98 games sit at exactly 2–0 and there are no genuine 2-point games, so I believe
it is — but 313 games have a side under 10 points and those must be **reported,
not auto-classified**. Also: should a forfeit count in strength of schedule at
all, or only in W-L?

### Q3 · Own-creation entitlement *(blocks §9.2)*

Three sub-questions:
* Does own-creation extend to the game **view** (`can_see_game_tracked`), or only
  to aggregates? *(I'd say yes — it is their work.)*
* Does it survive the coach leaving the program? `tracked_by` is an email.
  *(I'd say yes, and say so out loud.)*
* The **15 games with an empty `tracked_by`** (the old desktop path) — attribute
  them to anyone, or leave them to the team rule? *(I'd say leave them.)*

### Q4 · The percentile floor

Below how many tracked teams does a percentile become a rank? I suggest **10**.
At 5 the boys side quantizes to {10,30,50,70,90}; at 21 the girls side is
tolerable.

### Q5 · The Rankings minimum-games default

`_MIN_GP` currently defaults to 1 over a pool that is 24% one-game teams. I
suggest **5**, matching `MIN_SNAPSHOT_GP`, with the leader cards carrying their
own independent floor so a coach who drops the slider to look up an opponent
still does not see a forfeit crowned.

### Q6 · Superlative language

"Elite" currently means "first in a five-team sample". Do you want an absolute
gate per generator (e.g. OREB/g must clear a real threshold), or a pool-size gate
(no adjectives below N teams), or both? *(I'd do both — they fail differently.)*

### Q7 · The 486 unnamed players

Display is settled — `player_label()`. The open question is the data. Options:
* leave them as numbers forever (they are opponents; you will never know);
* name them opportunistically when you play a team twice;
* let a coach name opponent players from the Event Editor during retag;
* **do not carry unnamed opponents forward at rollover** — currently 221 players
  carry, most of them integers.

Related: should unnamed players appear in **league superlative cards** at all?
Same question as placeholder-named officials, and it should get the same answer.

### Q8 · The Officials rating

Roadmap item 8 is already done; what remains is that `volume` (25% of the
composite) is a raw per-game call count with no game adjustment, and the
published rating correlates **−0.81 with fouls per game** on a page whose
docstring says FPG carries no goodness sign. Three options:
* partial pace and team foul-drawing rate out of `volume` *(needs a walk-forward
  gate and this book cannot support it — prod's 62 games might)*;
* drop `volume`, leaving share and worst-game;
* score **distance from a normal split** rather than signed deviation, which is
  what the rating claims to measure and retires `CREDIT_FACTOR` entirely.

*(I'd take the third. It also fixes the quietest official being ranked first.)*

### Q9 · Film timecodes

Worth a day? It is the only realistic step toward the InStat half of your vision,
and it needs one new field and a wall-clock note at tip-off. Say no and I will
stop suggesting it.

### Q10 · The Whiteboard

One saved play in the book. It is a well-built 300-line component with a
print-to-SVG path and an embed on the scout sheet. Is it a feature you want, a
feature you forgot, or a feature to retire? *(It costs nothing to keep; it costs
attention to maintain.)*

### Q11 · What "Free" is actually for

Under your ruling Free is box-score-derived, excluding implied possessions. That
is a clean line. The commercial question is whether Free is **a funnel** (give
away last season entirely, sell this season) or **a floor** (give away box scores
forever, sell depth always). Q1 is really this question wearing a technical hat,
and answering it settles §9.1, §9.3 and half of §12.2.

---
---

# VII · REFERENCE

## 19 · Where everything is

**The sweep**, branch `sweep-2026-09-06`, `APP5.0/docs/`:

```
SWEEP_2026-09-06_INDEX.md          start here
SWEEP_2026-09-06.md                Part 1  gating — the persona matrix, leaks, false denials
..._PART2_TEAM_DASHBOARD.md        Part 2  the flagship, on two teams
..._PART3_OFFICIALS.md             Part 3  the Officiating Lab
..._PART4_RANKINGS.md              Part 4  Rankings, Schedule, Hall of Fame, forfeits
..._PART5_DATABASE.md              Part 5  schema, integrity, indexes, growth
..._PART6_ENGINES.md               Part 6  898 entry points, buried vs live
..._PART7_WARROOM_PLAYERS.md       Part 7  War Room, Players, the names
..._PART8_IDEAS.md                 Part 8  build / rejected, ranked
..._PART9_CAPTURE.md               Part 9  capture quality, the write pages
..._PART10_GLOSSARY.md             Part 10 the explanation layer
THE_BOOK_2026-09.md                this document
```

**The one test added:** `tracker/test_read_filter_empty_scope.py` — three
assertions, **all failing on `main`**, all failing for the right reason.

**Memory** (`~/.claude/projects/…/memory/`), for the next session:
`sweep-2026-09-06`, `tracked-pool-is-tiny`, `apptest-persona-seeding`,
`empty-gids-means-everything` (corrected), `season-default-sentinel` (corrected).

**The method**, so any number here can be re-run:

```
snapshot   sqlite3.connect(live).backup(sqlite3.connect(copy))
render     chdir APP5.0/tracker (secrets-free cwd bypasses auth)
           AppTest.from_file(page, default_timeout=1800); seed; .run()
persona    import helpers.auth as AUTH; AUTH._LOCAL_IDENTITY = {...}
profile    cProfile around one cold AppTest.run(), sorted by cumulative
```

Two traps that cost this sweep the most time: `require_login()` **writes**
`_LOCAL_IDENTITY` into session_state, so seeding `auth_user` is overwritten —
rebind the module global instead. And **`ta_gender` must be seeded**, or the
stale global `default_team` opens the Team Dashboard on the wrong league and
silently discards `ta_team`.

## 20 · Every number, one table

| quantity | value | where |
|---|---|---|
| free-solo surfaces identical to admin | **20 of 24** | §9.1 |
| forfeit-shaped finished games | **117** (1–0 or 2–0) | §8.1 |
| girls teams with exactly one game | **169 of 704** | §8.2 |
| tracked teams — girls / boys | **21 / 5** | §10 |
| boys percentile values possible | **{10,30,50,70,90}** | §10 |
| players with no name | **486 of 541** | §4 |
| tracked games this coach logged but cannot read | **14 of 43** | §9.2 |
| eager report builds | **6** | §11 |
| Players page cold | **56.6 s**, 43 s of it one figure | §11 |
| `ANALYZE` win on the hottest predicate | **1.55 ms → 0.04 ms**, 74 sites | §11 |
| caller sites widening an empty read-filter | **35** (4 unreachable-by-caller) | §8.7 |
| `season_wpa` pool vs entitled pool | **43 vs 11** | §9.5 |
| shot-clock PPP — early / mid / late | **0.731 / 0.570 / 0.597** (n=5,341) | §13.1 |
| 4ft-arc vs rim, girls | **0.548 vs 1.086** PPS | §13.3 |
| contest value | **0.337 PPS** | §13.4 |
| passer→shooter edges captured | **780** (54 at ≥10 shots) | §12.5 |
| `hockey_from_id` tagged | **0 of 4,019** | §12.5 |
| play_type coverage — shots / turnovers | **90% / 63%** | §10, Part 9 |
| play-type PPP overstatement | **+0.002 to +0.080** | Part 9 §1.1 |
| officials with a publishable sample | **0 of 70** | §15 |
| in-stint fatigue effect | **+0.058 the wrong way** | §15 |
| duplicate teams / games | **13 / 9** | §8.8 |
| engine entry points reaching a page | **853 of 898** | §1 |
| suite | **290 pytest + 97 run_all**, green | §19 |

---

## Closing

The honest summary is that you have built the hard part. The engines are good,
the reliability discipline is better than the market's, and the co-op is a real
idea. What is between you and the product you described is a month of gating,
labelling and wiring — plus two decisions (Q1 and Q11) that are really the same
decision about what you are selling.

**If you only do three things in September:** the Free box score, the percentile
honesty pass, and the eager-report fix. The first makes the product sellable, the
second makes it trustworthy, and the third makes it usable on the hardware you
have.
