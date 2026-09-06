# HoopTracks — The Book
### One read for September 2026. Everything the sweep found, everything it suggests, and every question it needs you to answer.

Written 2026-09-06 after a ten-part read-only audit (`SWEEP_2026-09-06_INDEX.md`
and Parts 1–10). **Revised the same day after founder review** — §0 lists what
changed, and three findings were retracted or downgraded.

Every number here was measured against a `sqlite3.backup` copy of the **local**
book at `%LOCALAPPDATA%/APP5/analytics.db`. **Nothing was ever written to. No
application code was changed.** Branch `sweep-2026-09-06`, unmerged.

✅ **Second revision, 2026-09-06 evening: production was pulled and every
sample-dependent number re-measured against it.** 63 tracked games, 11,392
events. `tools/pull_prod_snapshot.py` makes it one command from now on. §0.2
lists what moved — two more findings retracted, one got much bigger.

This document is the consolidation. The Parts are the working; this is the read.

---

# CONTENTS

**0 · What changed after founder review** — §0.1 retractions · §0.2 the wrong
book · §0.3 rulings received

**I · Where you actually are** — §1 the verdict · §2 the app by the numbers ·
§3 the constraint that should decide everything

**II · The vision, scored** — §4 OOTP · §5 Synergy · §6 Hudl InStat ·
§7 what nobody else has

**III · What is broken** — §8 correctness · §9 gating · §10 honesty ·
§11 performance

**IV · What to build** — §12 free wins · §13 new analytics · §14 consolidations
and deletions · §15 the rejected list

**V · The month** — §16 week by week · §17 the season autopilot

**VI · The rulings** — §18 all fourteen answered, nothing blocked

**VII · Reference** — §19 where everything is · §20 every number in one table ·
§21 the roadmap, September to next offseason

---
---

# 0 · WHAT CHANGED AFTER FOUNDER REVIEW

The audit ran cold, on a stale copy, without the capture history. Four things
came back that change the reading. They sit at the top rather than woven in,
because two of them were among the loudest findings in the original draft.

## 0.1 · Two retractions, a downgrade and a sharpening

### RETRACTED — "Free sees the paid product" is not a bug, it is the funnel

The original §9.1 called the offseason archive hole the headline commercial
finding. **The founder's ruling makes it deliberate:**

> *"Give away last season, sell this one. Old data is only meaningful to a point
> — sell the right-now current depth, let someone else use outdated information.
> High schoolers change so much year to year that old data is important, but not
> the end-all-be-all."*
>
> *"The past gating is the dangle. Dangle last season's almost-irrelevant data at
> a coach and they must think: what if I had that now, in season."*

That is a coherent product position and it is what the code already implements.
The "four-month window where the archive is the product" is not a hole — it is
the demo running at full volume in the month coaches arrive.

**What survives, and it is now the actual finding: the dangle is incomplete.**
Three page-level gates do not honour the archive rule while the War Room does, so
a Free coach in the offseason gets the Insights deck, the War Room and the whole
Players page — and is hard-stopped out of the Officiating Lab. On Rankings →
Team the page contradicts itself, hiding the tracked rank in the header while
rendering the full tracked deep dive below it. **The fix flips from "close the
hole" to "make the dangle total", which is cheaper and better.**

*One tension in the answers: Q1 chose the rolling window (last season closes when
the new one tips off); Q11 chose "give away last season, sell this one" (last
season stays open forever). **Q11 wins** — it is the product position, and it
means no window predicate is needed at all. The rule is simply past = open,
current = gated, applied without exception.*

### RETRACTED — the officials named after hair colour are not in production

The original §10 and Part 3 §4 led with `BEST SHARED CREW 55 · White Bald` and
called it "the single most embarrassing thing in the sweep".

**It is not in the live book.** Production officials are named `Unknown <n>`,
which `is_placeholder_name` already matches and already sorts below every named
official. The 13 description-named rows (`Bald Bald`, `White Bald`, `3rd W Hair`,
`Hefty`…) exist **only in the stale local copy** the audit ran against — verified
by re-snapshotting it: 0 `Unknown` rows, 13 description rows.

**So the placeholder detector is working and the widening I proposed is
unnecessary.** What remains is a one-line note: if a description-style name is
ever typed again, `^unknown` will not catch it. Worth a vocabulary widen someday,
not a session.

### DOWNGRADED — the 486 unnamed players are a capture-era artefact that fixes itself

The original §4 said "OOTP with unnamed players is not OOTP" and treated naming
as a project. The founder's context changes the trajectory entirely:

> *"This is information thrown in over three or four months from May/June to now.
> I did not have access to a book in a game to give names, which is why most teams
> have placeholder information. Next season I, and the other coaches, WILL have
> access to the scorebook for every game — roughly 90% player coverage and 70%
> officials."*

So: **the display fix (`player_label()`) is still worth doing this month**, because
today's screens still render `REBOUNDING 80.7 · 12`. But there is no data project
behind it, no import to build, and no rollover decision to agonise over. Scouting
will keep producing some unnamed players — scouted teams that never play a
pilot-program team — so the label helper earns its keep permanently.

**And it removes an item:** whether the OSSAA importer could name players was
listed as an open hour of work. It cannot, and it no longer matters.

### SHARPENED — the War Room Lineup Creator

The founder's instinct was right and it makes the fix better. There **is** an
8-game requirement: `lineup_projection.MIN_TEAM_GAMES = 8`, and the engine
returns a proper message carrying the count — `"only 3 tracked games (need 8)"`.

But the empty state I hit fires **before** the engine runs. `9_War_Room.py:1304`
tests whether the team has any *rated players at all*, and the picker defaults to
the league's #1 team, which has **zero** tracked games. Two distinct states, and
only one of them speaks:

```
0 tracked games    -> "No rated players on this team yet. Track a game for them
                       first."        <- what a coach sees, and it is bad advice:
                                         nobody can track another program's games
1-7 tracked games  -> "only N tracked games (need 8)"   <- correct, and never seen,
                                                           because of the default
```

**The fix is three lines, not two:** default the picker to the viewer's own team;
list only teams with tracked data; and make the zero-games copy state the
requirement (`needs 8 tracked games — this team has none tracked`) instead of
issuing an instruction the coach cannot follow.

## 0.2 · Production, pulled — and what moved

The audit ran on `%LOCALAPPDATA%/APP5/analytics.db`, which turned out to be a
development copy three months behind. **Production has now been pulled** —
read-only, `.backup()` through a `mode=ro` URI, temp removed, `integrity_check`
ok, 0 foreign-key violations — and every sample-dependent number re-measured.

`tools/pull_prod_snapshot.py` does it in one command from here on, so this
particular way of being wrong is closed.

```
                        local copy        PRODUCTION
tracked games                43               63
play-by-play events       7,731           11,392
players                     541              608
officials                    70               79
girls tracked pool     21 teams/35g     22 teams/43g/261 players
boys  tracked pool      5 teams/8g      10 teams/20g/110 players
officials naming     description-style   19 x "Unknown <n>", 0 description-style
games in 'Current'            1               23   (next season's schedule started)
```

### Two more retractions

**RETRACTED — `passing_chains` does not return an empty graph.** The original
§12.5 called it "a complete, tested module producing nothing on every call",
because `hockey_from_id` was NULL on 0 of 4,019 shots locally. **On production
the tag is being pressed:** 317 shots across 19 games, and the module's own
readiness check agrees —

```
hast_coverage() -> {'tagged': 317, 'made': 115, 'missed': 202,
                    'games': 19, 'pairs': 220, 'regate_at': 50, 'ready': True}
```

`ready: True`. HAST and xA2 are live, not inert. **What survives is a smaller,
different finding:** the module uses 317 hockey-tagged shots and discards the
**3,978 shots that carry a plain `pass_from_id`** — 1,087 distinct passer→shooter
edges, 89 of them at ten shots or more. The 2-node graph is **twelve times the
sample** of the 3-node one and still unused. Making the hockey tag optional is
now an enrichment, not a rescue.

**CONFIRMED harder — the officials naming.** §0.1 retracted the hair-colour
finding on your word; production confirms it outright. 79 officials, **19 named
`Unknown <n>`, zero description-style.** `is_placeholder_name` is doing its job.

### What got materially better

| finding | local | production |
|---|---|---|
| boys percentile values possible | {0,20,40,60,80,100} | {0,10,20,…30,…90} |
| officials with ≥5 games worked | **0** | **11** (one at 9) |
| officials with ≥3 (the rating floor) | 20 of 70 | **34 of 79** |
| play_type coverage, shots / turnovers | 90% / 63% | **93% / 74%** |
| play-type PPP overstatement | +0.002 to +0.080 | **+0.002 to +0.055** |
| hockey-assist tag | 0 of 4,019 | **317 of 6,002** |

The officials row is the one that changes a decision. §15 rejected per-official
profiles because *"zero officials have worked five tracked games"*. Eleven now
have, one has nine, and `RATING_MIN_GAMES = 3` admits 34 of 79 rather than 20 of
70. **It is still thin — nine games is not a whistle profile — but the rejection
is now "wait one more season", not "the sampling regime is wrong".** Exactly as
§15 predicted it would compound.

### What got worse

**Own-creation is now the largest gating number in this document.**

```
tracked games                                    63
own-TEAM games (team 1)                          26
games this coach LOGGED                          48
logged but NOT their own team                    37
  ...and not pooled either                       32      <- invisible to them
```

**32 of 63 tracked games — 51% of the book — were typed in by this coach and
cannot be read by them** as a Paid Solo coach. It was 14 of 43. Q3's ruling
(*"if the coach tracked it, they get to see it"*) is now unblocking half the
book, not a third.

**And the boys leaderboard is worse than the girls one.** §8.2's forfeit example
was `Best defense (PA/G) 0.0 — Mercy Institute Girls, 1-0`. Production adds:

```
M  Best defense (PA/G)   1.00   Unity Academy Boys        0-3
M  Point margin        +67.00   South Western Hieghts     1-0
M  Strength of record   72.82   Bryant (Bryant, Arkansas) 1-0
```

**A team that lost all three of its games is the boys' best defence**, on 1.00
points allowed per game — three forfeits recorded as 0–1 losses. Q2 fixes it.
(Note also `South Western Hieghts` — a misspelling that has produced one of the
six remaining duplicate-team collisions.)

### What did not move at all

Forfeits are **identical**: 123 games with a zero on one side, 19 at exactly 1–0,
98 at exactly 2–0, 313 with a side under ten. All of it is 2025-2026 data that
finished before either copy diverged.

The **4-ft cliff** is stable to three decimals on the girls' side and moved on the
boys': girls 4ft-arc **0.548** PPS against a rim of **1.072** (was 0.548 / 1.086);
boys **0.753** against **1.276** (was 0.675 / 1.318). So `shot_diet.py`'s
hardcoded *"0.55 a trip against 1.09 at the rim"* is now an almost exact match for
the **girls'** numbers and out by 27% and 15% for the boys — §8.4 stands, and the
diagnosis that it is one gender's numbers shown to everyone is confirmed.

**The shot-clock read holds and sharpens** (§13.1, rewritten below).

**The in-stint fatigue rejection holds.** Ten qualifying players, **seven still
better late in a stint**, pooled delta **+0.025** the wrong way (was +0.058).
Still no signal. Do not build it.

**Referential integrity is perfect on production too** — `integrity_check` ok,
zero foreign-key violations.

### Two more local-copy artefacts, retracted

**`turnover_type` was never abandoned.** Part 9 §1.2 found it switching off on
2026-01-30 and staying off for the last ten games, and built an argument about
habits failing mid-season on top of that. **On production it runs to 2026-03-14 —
the last game of the year — at 53.5% coverage** (1,108 of 2,071), against 34.7% on
the local copy. The tag was being pressed all along; the local book simply stopped
receiving those games. **The recommendation survives for a different reason:**
`coverage.py` still does not gate `turnover_type`, and 53.5% is still a
partial sample that any live-vs-dead-ball split should disclose.

**The co-op has coaches now.** The local copy had two accounts. Production has
**six** — two admins and four coaches, **all six on `plan='paid'`**. But
`teams.shares_pool = 1` on exactly **one** team, and **11 of 63 tracked games are
pooled**. So the pilot has six paying accounts and a pool one team deep. That is
not a bug, it is the state of the business, and it is the number §7's
"the co-op is the business" claim actually rests on today. Q3's ruling — a coach
in the co-op sharing their scout games with the whole co-op — is the lever that
moves it.

## 0.3 · Rulings received

All eleven answered. §18 carries each answer and what it settles; this is the
short version.

| Q | ruling | effect |
|---|---|---|
| 1 + 11 | **Give away last season, sell this one.** No window. | §9.1 retracted; becomes "make the dangle total" |
| 2 | **A zero on one side = forfeit.** Out of SOS, in W-L. | §8.1 unblocked |
| 3 | **If the coach tracked it, they see it.** Solo → private to them; co-op → the whole co-op gets it. Survives leaving. Empty `tracked_by` → leave open. | §9.2 unblocked, and more generous than proposed |
| 4 | Percentile floor **10**. | §10 unblocked |
| 5 | Rankings min games **5**. | §8.2 unblocked |
| 6 | **Both gates, and disclose.** Transparency over silence. | §10 unblocked |
| 7 | Leave the names — the scorebook fixes it next season; the Input Hub already consolidates players. | downgraded to display-only |
| 8 | **Officials rating reviewed — no change.** | Part 3 §3 becomes a record, not a proposal |
| 9 | Film timecodes **not worth it**. | §13.7 deleted |
| 10 | Whiteboard — **revisit next offseason**; no coach has had hands on it in season. | parked |

**And the three that were open are now closed too:**

| Q | ruling | effect |
|---|---|---|
| 12 | **`SCE` = Self-Created %** (shots with no pass-from and no set-up-by). **`ScEff` = points scored / points possible**, splittable by 2s, 3s and all. | the glossary is right and the CODE is wrong — §18 Q12 |
| 13 | **No same-day rematches.** Teams play once per day. | `UNIQUE` index unblocked — §18 Q13 |
| 14 | **Pull production.** Done — §0.2, and `tools/pull_prod_snapshot.py` makes it repeatable. | every sample number re-measured |

**Nothing in this document is blocked on a decision any more.**

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

the book          13,383 games · 12,647 finished · 63 tracked
                  11,392 play-by-play events
                  1,448 teams · 608 players · 79 officials
                  17.3 MB · integrity ok · 0 FK violations

the tracked pool  girls   22 teams · 43 games · 261 players
                  boys    10 teams · 20 games · 110 players

capture quality   shot x/y      100% on every tracked game but three
                  play_type      93% of shots, 74% of turnovers and fouls
                  defense        92% of shots, 92% of turnovers
                  officials     100% of 1,659 fouls name one
                  hockey_from    317 of 6,002 shots, 19 games — now live

infrastructure    1 vCPU / 2 GB no-swap droplet, litestream replicating
                  a FastAPI courtside PWA (3,166 lines of JS) + Streamlit app

PRODUCTION, pulled 2026-09-06 evening. Earlier drafts used a local copy at
  43 tracked games; §0.2 lists everything that moved.
```

**Read the tracked-pool line twice.** Ten boys teams means every boys percentile
is a multiple of ten — verified, the distinct values are exactly
{0,10,20,…90}. Everything in §10 comes from that.

## 3 · The constraint that should decide everything

You asked for something a single person can hold afloat across a season with
little or no thought. That is a stronger constraint than "make it good", and it
should be the tiebreaker on every item in this document.

**And it has a date on it now.** You are training coaches in **October** — which
is why everything here has to land in September:

> *"This is why this is important to fix everything now, so I can fully focus on
> this season instead of baby-sitting this all season."*

That reframes the whole month. **September is not "improve the app"; it is
"remove every reason you will have to open a page in anger between November and
March".** Anything that fails that test can wait until next offseason — and two
items in this document already have (§13.7 film timecodes, the Whiteboard).

It also changes who the audience is. Every screen in here has, until now, been
read by exactly one person who already knows what every number means. **In
October it acquires four or five readers who do not**, which is what makes §10
(numbers published without their sample) and §18 Q12 (an abbreviation meaning two
things) go from tidy-ups to launch blockers.

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

*The names.* **539 of 608 players have no name** on production, only a jersey
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
Oklahoma girls' basketball. **The boys' side is worse:**

```
M  Best defense (PA/G)   1.00   Unity Academy Boys   0-3
```

A team that **lost all three of its games** is the boys' best defence, on one
point allowed per game — three forfeits recorded as 0–1 losses.

**Fix:** a forfeit marker set on import from the 1–0 / 2–0 signature (safe on this
book — 98 games at exactly 2–0 and no genuine 2-point games), counted in W-L only,
excluded from every margin engine, displayed as `W (ff)`. **Needs your ruling on
the detection rule** (§18 Q2).

### 8.2 · The one-game leaderboards

On production, **168 of 703 rated girls teams and 210 of 748 boys teams have
played exactly one game**; 223 and 266 respectively have fewer than five.
`_MIN_GP` defaults to **1**. So four of the five Team-leader cards and
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

The engine behind it is fine and has a proper gate —
`lineup_projection.MIN_TEAM_GAMES = 8`, returning `"only 3 tracked games (need
8)"`. That message is **never seen**, because `9_War_Room.py:1304` short-circuits
on "no rated players at all" first and the default lands on a zero-game team.
See §0.1 for the three-line fix.

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

### 9.1 · The dangle, and the three places it stops — *reframed, see §0.1*

`default_read_season()` = `2025-2026`. `_is_past_season()` calls that PAST. Every
archive-bypassed read gate returns `None` = unrestricted. Rendered persona by
persona, **a free-solo coach is byte-identical to admin on 20 of 24 surfaces**,
including the whole 202,706-character Players page.

**That is the intended product**, per the ruling: give away last season, sell
this one. The measurement stands; the alarm was mine and it is withdrawn.

**The finding is that the dangle stops in three places and nobody decided that.**
`pages/8_Officials.py:219`, `pages/14_Hall_of_Fame.py:504` and
`pages/6_Team_Dashboard.py:6038` hard-stop Free with no archive bypass, while
`pages/9_War_Room.py:256` guards correctly with
`if _is_cur_season and not has_paid_plan`. So a Free coach browsing last season
gets the Insights deck, the whole War Room and the Players page — and is locked
out of the Officiating Lab, the Hall of Fame's tracked block, and Projection.

Worse, one screen contradicts itself. On Rankings → Team,
`can_see_team_tracked` (`:1161`, no archive bypass) hides the tracked rank in the
header while `tracked_gate` (`:1405`, bypassed) renders the full tracked deep
dive immediately below it. Compare prints a literal
**"The tracked four-factor & efficiency compare is Paid"** (with a padlock) over
data the rule says is free.

**The fix, now that no window is needed:** give `can_see_team_tracked` and
`can_see_game_tracked` the `season` parameter and the same `_is_past_season`
bypass the other four gates have, then make the three page-level stops copy the
War Room's guard. Half a session, and `lock_reason()` (§14) makes it one site
instead of six.

### 9.2 · Provenance never enters the read filter

Your ruling: *Paid gets own-team depth **and own creation of tracked data**.*
`games.tracked_by` records who logged a game and is read by exactly one function,
which decides what to **share**, never what its author may **read**.

```
tracked games                                63
own-TEAM games (team 1)                      26
games this coach LOGGED                      48
logged but NOT their own team                37
  ...and not pooled either                   32      <- invisible to them
```

**32 of 63 tracked games — 51% of the book — were typed in by this coach and
cannot be read by them** as a Paid Solo coach. This is the largest gating number
in the document, and it grew as tracking grew: it was 14 of 43 on the local copy.
The pattern is a coach who scouts widely and is punished for it.

### 9.2.1 · The two-email constraint, measured — it does not bite, and the reason matters

You flagged that every tracked game to date was logged across **two separate
emails**, and worried that an own-creation rule keyed on identity would strand
half of it. **Measured on production, it does not:**

```
tracked_by = colbyl.farrar@gmail.com        48 of 63
tracked_by = c.farrar@adairschools.org       0
tracked_by empty (old desktop path)         15

visibility under each rule, for this coach:
  team membership only                      26 of 63
  + own creation, ONE email                 63 of 63     <- already everything
  + own creation, BOTH emails               63 of 63
```

Every attributed game carries the **gmail** address; the school address never
wrote one, and the 15 unattributed games are all team-1 games that the team rule
already covers. **So Q3 keyed on the signed-in email recovers 100% of the book
today** — the two-email split is real in your workflow and invisible in the data,
because the PWA writes whichever email owns the tracker token.

**But build the broader rule anyway, because October breaks the narrow one.**
Key own-creation on **every email that staffs any of the viewer's teams**, not on
the single signed-in address:

```sql
tracked_by IN (SELECT coach_email FROM coach_teams WHERE team_id IN (:my_teams))
```

Three reasons, all of them arriving in October:

1. **You will keep using two accounts.** The moment a game lands on the school
   address, a one-email rule strands it.
2. **Assistant coaches share a program.** `coach_teams` already has four people on
   team 1. If K. Burns tracks a game, A. Klucevsek should see it — they are the
   same staff. The `coach_teams` join gives that for free.
3. **It matches Q3's own words.** *"If they are in the co-op and they track a
   scout game, everyone gets it in the co-op."* Staff-level sharing is the same
   idea one level down.

**One thing to decide while implementing** (§18 Q3 did not cover it): does a Solo
coach's scout game become visible to their **assistants**, or only to themselves?
The `coach_teams` rule says assistants; a strict reading of *"they see it, nobody
else does"* says only them. **Assistants is almost certainly what you want** —
they are the same staff room — but it should be a decision, not an accident.

### 9.2.2 · What October does to the pool

Production today:

```
app_users        6, all plan='paid'  — 2 admins + 4 coaches
coach_teams      5 people on team 1 (Adair Girls) · 1 on team 1755 (Sequoyah Boys)
shares_pool=1    team 1 only
pooled games     11 of 63
team 1755        15 tracked games — ALL logged by colbyl.farrar@gmail.com
```

**Every tracked game in the book was created by one person.** The second pilot
program has 15 tracked games and its coach logged none of them. That is the
pre-October baseline, and it is what the training changes.

The mechanical consequence is worth seeing before it happens: **once Brock starts
logging Sequoyah's games on his own account, you stop seeing them** — you are not
on `coach_teams` for 1755, and team 1755 is Solo. The co-op toggle on 1755 is the
switch that keeps the league-wide view whole, and *"share to scout"* becomes a
live conversation in October rather than a hypothetical.
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
| ~~Officiating Lab~~ | ~~`BEST SHARED CREW 55 · White Bald`~~ | **RETRACTED — local copy only, see §0.1** |
| Players superlatives | `REBOUNDING 80.7 · 12` | **a jersey number** (fixes itself next season — §0.1) |

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
4. **Never render a placeholder as a name** — not a jersey number. (`Unknown <n>`
   is already handled in production; the description-style names were a local
   artefact.) The jersey-number case is permanent, because scouting will keep
   producing players nobody has a book for.

`reliability.MEASURED` and `cards.conf_dot` already exist. The machinery is built
and not wired to the places that need it most.

**And two calibration errors, measured:** `ShotRating`'s "50 = average" anchor is
off by 7–15 points on a book that shoots 34.7%; `VPS`'s "~1.0 breaks even" is
actually the **75th percentile** against a median of 0.67. `OVERALL`'s ladder, by
contrast, matches — which is why each had to be measured.

**Plus two abbreviation collisions, and the second one is a three-way.**

`Leverage` is defined twice in `STAT_DEFS` for unrelated concepts — the
officials' game-worth blend and the win-probability Leverage Index. Exact-match
lookup takes the first; the only current call site happens to want that one, so
it is right today by luck.

`SCE` / `ScEff` is worse, because **three different definitions are in play and
no two agree**:

| source | `SCE` means | `ScEff` means |
|---|---|---|
| **the code** | an alias of `ScEff` — the same number (`stats.scoring_efficiency`'s docstring says so outright: *"the canonical name for what the profile/team code has long called SCE"*). Self-creation lives in a separate `SelfCr%` column. | point-weighted make rate: `(2·2PM + 3·3PM) / (2·2PA + 3·3PA)` |
| **the glossary** | Self-Creation % — and the `ScEff` entry explicitly warns *"NOT the same as SCE / Self-Creation %"* | Scoring Efficiency (matches the code) |
| **the founder** | Shot Created % | Shot Created **Efficiency** |

So the glossary's `SCE` entry contradicts the code, and the founder's `ScEff`
matches neither — the shipped `ScEff` has nothing to do with shot creation at
all. Tap the stat key on the Players page and you decode a scoring-efficiency
column as self-creation.

**This needs a ruling before it can be made consistent** (§18 Q12), and the
founder's *"done on some, needs to move to all"* is the right instinct applied to
a name that has not been settled yet. Once it is, it is one rename across the
glossary, `player_ratings`, `defenses`, `box_score`, `insights_tab` and the Team
Dashboard — mechanical, but only after the words mean one thing.

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

### 12.5 · The passing graph uses 317 passes and throws away 3,978 (½ session)

*Rewritten — the original claim that `passing_chains` returns nothing was a
local-copy artefact (§0.2).*

The module works on production. `hast_coverage()` reports **317 tagged shots
across 19 games, 220 pairs, `ready: True`** — so HAST and xA2 are live, not inert.

But every entry point still drops any row without a hockey tag, and the **2-node
passer→shooter edge is twelve times the sample**:

```
shots carrying a plain pass_from_id      3,978
distinct passer -> shooter edges         1,087
edges with >= 10 shots                      89
shots carrying the hockey tag              317
```

89 edges at ten shots or more is a readable connection matrix for several
rotations, not just one. Making the hockey tag **optional** — 3-node chains when
present, the 2-node graph always — turns a 317-shot feature into a 3,978-shot one
for the cost of a conditional.

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
**only ever as a mean**. Bucketed on production (n = 7,856 clean possessions):

```
early (<7s)     n=2,001    PPP 0.742
mid   (7-15s)   n=3,286    PPP 0.600
late  (16-35s)  n=2,569    PPP 0.603
```

**Getting into offence early is worth +0.14 points per possession, and nothing
after the first seven seconds differs at all.** That is a cleaner read than the
local copy gave (which had mid below late and suggested "the middle is worst") —
with 47% more possessions, mid and late converge to within 0.003 and the whole
effect lives in the early band.

It survives the obvious confound. Excluding every `play_type='transition'` row:

```
early  n=1,320  PPP 0.711        mid  n=2,676  PPP 0.603    late  n=2,546  PPP 0.605
```

So it is **not just fast breaks** — early half-court offence is still worth +0.11
over everything later. That is the coachable version: *hunt the first good look;
after seven seconds the possession is worth the same whenever you shoot it.*

Build it as a `_t_clock` generator on the `_t_quarter` template, section *Why we
win / why we lose*, evidence destination `("Charts", "Situational")`.

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
band          girls share   girls PPS    boys share   boys PPS     (production)
rim 0-4ft        25.2%        1.072        28.0%       1.276
4ft-arc          35.8%        0.548        35.0%       0.753
arc 3            22.0%        0.811        25.7%       0.951
deep 3           12.3%        0.745        11.3%       1.125
                 3,990 located shots        1,980 located shots
```

A girls' team moving one shot a game from the dead band to the rim gains **0.54
points**. Ten shots a game is **+5.4** — larger than any single four-factor edge
the Winning Formula prices. The app *says* this; it does not turn it into a
target: *"you take 88 from that band; a league-average diet at your volume is
113; each one converted to a rim attempt is worth +0.54."* That is a season goal.

### 13.4 · Contest × set call (½ session)

The contest is worth **0.324 PPS** league-wide on production — contested 0.773
on n=4,599 (34.2% FG), uncontested 1.098 on n=1,403 (46.9% FG). It reproduced at
0.337 on the local copy and 0.34 is already on record, so this is now three
independent measurements landing within 0.02.
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

### 13.7 · ~~Film timecodes~~ — **DROPPED** (Q9)

A `film_offset` field plus the quarter+clock already on every event would have
given a scrub timecode beside any number, for about a day of work. **Ruled not
worth the effort.** Recorded so it is not re-proposed; the InStat half of §6
stays out of scope.

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

**Park, do not touch:** the **Whiteboard**. One saved play in the book, and the
reason is not the feature — *"no coach has had their hands on this in season."*
Revisit next offseason with usage data instead of guessing now (Q10).

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

**Per-official whistle profiles — the sample is arriving, and the rating itself
is reviewed and closed.** *Updated on production:* the local copy showed **zero**
officials with five games worked; production has **eleven**, one at nine, and
`RATING_MIN_GAMES = 3` now admits 34 of 79 rather than 20 of 70. Nine games is
still not a whistle profile, but the verdict moves from *"the sampling regime is
wrong"* to **"wait one more season"** — which is exactly what this section
predicted would happen, since officials are career-long and never archived. Q8: the founder has looked at the composite and
is happy with it, so Part 3 §3's `volume` finding (the published rating
correlates −0.81 with fouls per game) is now a **record of a known trade-off**,
not a proposal. Re-open it only if the prod snapshot changes the picture. 70 officials,
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

**Re-sequenced after the rulings.** Every ruling except three is in, so almost
nothing is blocked now — the plan moves from "wait for decisions" to "ship in
value order". The three still open (§18 Q12–Q14) touch week 4 only.

Sequenced so the commercially-urgent work lands before October and nothing
depends on you remembering anything.

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

### Week 2 — honesty, and finish the dangle

*Goal: every number discloses its sample, and last season is open everywhere with
no exceptions.*

| | item | effort | §|
|---|---|---|---|
| Mon–Tue | Percentile pool honesty — `pctile_bar` gains a pool arg, **floor 10** (Q4), **both gates + disclose** (Q6) | 1 session | 10 |
| Tue | Hall of Fame's stated-floor pattern onto Rankings / Players / Officials; **Rankings `_MIN_GP` default 5** (Q5) | ½ session | 8.2 |
| Wed | Officials: `rated_games` floor, sample chips. *(Placeholder names dropped — §0.1.)* | ½ session | 10 |
| Wed–Thu | **Make the dangle total** — `can_see_*_tracked` take `season` and bypass; Officials / Hall of Fame / Projection copy the War Room's guard | ½ session | 9.1 |
| Thu | `lock_reason()` — retire six copies of the ladder, and the above becomes one site | ½ session | 14 |
| Fri | **Own-creation entitlement** (Q3) — `tracked_by` joins the read filter: tracked-by-you is yours, and if you are co-op it is the co-op's | 1 session | 9.2 |

*Q3 moved forward from week 4: it is unblocked, it is the ruling that most
changes what a paying coach sees, and it is the one that stops a coach being
unable to read the games they typed in themselves.*

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

*Goal: the book is clean and the app runs without you.*

| | item | effort | §|
|---|---|---|---|
| Mon | **Forfeits** (Q2) — a zero on one side is a forfeit; **counts in W-L, out of SOS** and every margin engine | 1–2 sessions | 8.1 |
| Tue | `season_wpa` takes `game_ids`; the 23 engine-layer season defaults | 1 session | 9.5 |
| Tue | Resolve the **8 duplicate game pairs** (4 same-orientation, 4 mirrored) and the 6 duplicate teams; flip `games.id=4`; fix the `#4` jersey | ½ session | 8.8 |
| Tue | **`UNIQUE` index on the normalised matchup** (Q13) — must follow the dedup | 1 hr | 18 Q13 |
| Thu | **`SCE` → `ScEff` key rename; `SelfCr%` → `SCE`** (Q12) — now unblocked | ½ session | 18 Q12 |
| Wed | **§17 — install the timers.** Rollover, `ANALYZE`, rating-history rebuild, backup verification | ½ session | 17 |
| Wed | Surface the retag-coverage count on the schedule + season feed | ½ session | 17 |
| Thu | The player view consolidated into one screen | 1 session | 14 |
| Fri | Deletions, the stale banners, and the decision-record for what stays buried | ½ session | 14 |

**Deferred past September, deliberately:** Setup's `st.tabs` conversion (needs
the AST sweep), the Synergy framing (§13.5) and the defensive mirror (§13.6).
All three are better done once the season is running and you can see what you
actually reach for. **Film timecodes are dropped, not deferred** (Q9). **The
Whiteboard is parked until next offseason** (Q10). **The depth-tiered archive is
off the table entirely** — Q11 settled that last season is given away whole.

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

**One thing that stays manual, by decision:** the **OSSAA scraper**.

> *"I am fine with the OSSAA scraper being run by me daily — it is a simple click
> of a button every morning, little actual thought, and will sometimes be behind
> on games that are actually tracked."*

Good call, and worth writing down so nobody automates it later: an unattended
scraper that bulk-writes teams and games into the shared league DB is exactly the
job that needs a hand on it, and §14.1 shows why — the importer is the origin of
both the duplicate-team and duplicate-game classes, and `merge_teams` decisions
are not automatable.

**The one thing it needs is a note on screen.** Because the scrape runs on your
morning and a tracked game lands the night before, **the results board can be a
day behind the play-by-play**, and no page says so. One line under the Rankings
board — *"results synced through <date>; tracked games are live"* — costs nothing
and stops a coach in October reporting a bug that is a schedule.

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

# VI · THE RULINGS

## 18 · All fourteen answered

### Answered — and what each one settled

**Q1 + Q11 · What Free is for.** *"Give away last season, sell this one."* No
window, no depth tier, no offseason special case. The rule is **past = open,
current = gated, applied without exception** — which is what the code does, minus
the three page-level stops that do not honour it. Q1's rolling window is
withdrawn as inconsistent with Q11; Q11 is the product position and it wins.
**Settles:** §9.1 (retracted and reframed), §9.3, §12.2's shape.

**Q2 · Forfeits.** A zero on one side is a forfeit. **Counts in W-L. Out of
strength of schedule** — and by the same logic out of PPG, points allowed, MOV,
Pythagorean, Luck and the Power rating, all of which are margin math. The 313
games with a side under 10 points stay **reported, not classified**.
**Settles:** §8.1.

**Q3 · Own creation — and it is more generous than I proposed.**

> *"If the coach tracked it, they get to see it. If they track a scout game, they
> see it, nobody else does. If they are in the co-op and they track a scout game,
> everyone gets it in the co-op. Yes it survives leaving a program, because a
> coach leaves at the end of the year meaning everyone will see it after they
> leave anyway. Leave them, because no game as of now for last season should be
> gated at all."*

That is a clean rule with no exceptions to remember, and it is exactly the co-op
pitch: **track it and it is yours; share and it is everyone's.** It replaces the
current team-membership test, under which **14 of 43 tracked games this coach
typed in themselves are invisible to them**. Empty `tracked_by` needs no
attribution — those are all last-season games and last season is open.
**Settles:** §9.2.

**Q4 · Percentile floor: 10.** Below ten in the pool, show the rank.
**Q5 · Rankings minimum games: 5**, with the leader cards carrying their own
floor so dropping the slider cannot crown a forfeit.
**Q6 · Both gates, and disclose.** Pool-size gate *and* absolute gate on
superlatives, and say which is biting rather than silently withholding —
transparency over silence. **Settles:** §10.

**Q7 · Names.** Leave them; the scorebook closes the gap next season (~90%
players, ~70% officials), and the Input Hub already consolidates players. The
display fix stands because scouting will keep producing unnamed players forever.
**Settles:** §4's second gap, downgraded (§0.1).

**Q8 · Officials rating: reviewed, no change.** Part 3 §3's `volume` finding —
the published rating correlating −0.81 with fouls per game — becomes a **record
of a known trade-off**, not a proposal. Re-open only if the production snapshot
changes the picture.

**Q9 · Film timecodes: not worth the effort.** §13.7 deleted.

**Q10 · Whiteboard: revisit next offseason.** *"No coach has had their hands on
this in season."* The right reason to defer — usage data over speculation.

### Answered — the last three

**Q12 · `SCE` and `ScEff`.**

> *"SCE is self created %, which is the % of shots with a NULL pass-from or
> set-up-by field. ScEff is shot created efficiency, or points scored / total
> points possible — this can be for 2s, 3s and all shots. 2s would be
> (2PM × 2) / (2PA × 2)."*

**That settles it, and it says the glossary is right and the code is wrong.**

* **`SCE` = Self-Created %** — which is what `STAT_DEFS` already says, and what
  `player_ratings` already computes, **under a different key** (`SelfCr%`, from
  `shots_self`). One caveat to check while renaming: the ruling defines it as
  *no pass-from **and** no set-up-by*; confirm `shots_self` tests both fields, not
  just `pass_from_id`.
* **`ScEff` = points scored / points possible** — which is **exactly** what
  `stats.scoring_efficiency` computes today:
  `(2·2PM + 3·3PM) / (2·2PA + 3·3PA)`. The formula is correct and shipping.
* **The bug is the data key.** `stats.scoring_efficiency`'s own docstring admits
  it: *"the canonical name for what the profile/team code has long called SCE"*.
  So `defenses.py:162`, `box_score.py:751`, `insights_tab.py:438` and
  `6_Team_Dashboard.py:2571/3285` all carry **`ScEff`'s number under the key
  `SCE`** — the one abbreviation the ruling reserves for something else.

**The fix, now unblocked:** rename the data key `SCE` → `ScEff` at those six
sites, promote `SelfCr%` → `SCE`, and delete the glossary's *"NOT the same as
SCE"* warning, which only existed because of the collision. Half a session,
mechanical, and it makes *"done on some, needs to move to all"* safe to do.

**Two additions worth taking while you are in there:**

1. **The 2s / 3s split.** The ruling says ScEff *"can be for 2s, 3s, and all
   shots"* and only "all" ships. `ScEff-2` = `(2PM·2)/(2PA·2)`, which is just
   2P%, and `ScEff-3` = 3P% — so the split is only interesting as the
   **decomposition**: it shows *which* half of the shot diet is costing the
   overall number. Worth one row, not three columns.
2. **One naming flag, then I will drop it.** "Shot Created Efficiency" will be
   read as a sibling of "Self-Created %" forever, and the metric has nothing to
   do with shot creation — it is points captured against the shot-value ceiling.
   **"Shot Efficiency" or "Scoring Efficiency" would cost one word and stop the
   confusion recurring.** Your call; the formula is settled either way.

**Q13 · Same-day rematches: no.** *"Teams only play once per day."* That
unblocks the index, with one wrinkle worth knowing before it is written.
Production carries **8 duplicate pairs, and only half of them the obvious index
would catch**:

```
same orientation  (date, t1, t2) identical      4 pairs
mirrored          home/away swapped             4 pairs
```

`UNIQUE(date, team1_id, team2_id)` catches the first four and **misses the
mirrored four entirely** — which is exactly the case `game_dedup.py` was written
for and the one `merge_teams` keeps producing. The constraint that actually
closes the class is on the **normalised pair**:

```sql
CREATE UNIQUE INDEX ux_games_matchup ON games (
    date, MIN(team1_id, team2_id), MAX(team1_id, team2_id));
```

SQLite supports expression indexes, so this is one statement — **after** the 8
pairs are resolved, because the index cannot be created while they exist.

**Q14 · Production snapshot: pulled.** §0.2 has what moved.
`tools/pull_prod_snapshot.py` makes it one command, reads through a `mode=ro`
URI, uses `.backup()` rather than `cp` (the live book is WAL), removes its own
temp file even on failure, and verifies `integrity_check` locally before anyone
trusts the copy.

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

**All measured against production**, pulled 2026-09-06 evening (63 tracked games,
11,392 events). Where a figure moved from the earlier local-copy draft, the old
value is in brackets.

| quantity | value | where |
|---|---|---|
| free-solo surfaces identical to admin | **20 of 24** | §9.1 |
| forfeit-shaped finished games | **117** (19 at 1–0, 98 at 2–0) | §8.1 |
| one-game teams — girls / boys | **168 of 703 / 210 of 748** | §8.2 |
| tracked teams — girls / boys | **22 / 10** [21 / 5] | §10 |
| tracked games — girls / boys | **43 / 20** [35 / 8] | §2 |
| boys percentile values possible | **{0,10,20…90}** [{0,20…}] | §10 |
| players with no name | **539 of 608** [486 of 541] | §4 |
| tracked games this coach logged but cannot read | **32 of 63** [14 of 43] | §9.2 |
| co-op: paying accounts / sharing teams / pooled games | **6 / 1 / 11 of 63** | §0.2 |
| eager report builds | **6** | §11 |
| Players page cold | **56.6 s**, 43 s of it one figure | §11 |
| `ANALYZE` win on the hottest predicate | **1.55 ms → 0.04 ms**, 74 sites | §11 |
| caller sites widening an empty read-filter | **35** (4 unreachable-by-caller) | §8.7 |
| `season_wpa` pool vs entitled pool | **63 vs 11** [43 vs 11] | §9.5 |
| shot-clock PPP — early / mid / late | **0.742 / 0.600 / 0.603** (n=7,856) | §13.1 |
| …excluding transition | **0.711 / 0.603 / 0.605** | §13.1 |
| 4ft-arc vs rim — girls | **0.548 vs 1.072** PPS | §13.3 |
| 4ft-arc vs rim — boys | **0.753 vs 1.276** PPS | §13.3 |
| contest value | **0.324 PPS** (n=6,002) | §13.4 |
| passer→shooter edges captured | **1,087** (89 at ≥10 shots) | §12.5 |
| `hockey_from_id` tagged | **317 of 6,002**, 19 games, `ready: True` | §12.5 |
| play_type coverage — shots / turnovers | **93% / 74%** [90% / 63%] | §10 |
| play-type PPP overstatement | **+0.002 to +0.055** [+0.002 to +0.080] | Part 9 |
| `turnover_type` coverage | **53.5%**, tagged to the final game | §0.2 |
| officials — total / ≥3 games / ≥5 games | **79 / 34 / 11** [70 / 20 / 0] | §15 |
| fouls carrying an official | **1,659 of 1,659** | §15 |
| in-stint fatigue effect | **+0.025 the wrong way**, 7 of 10 better late | §15 |
| duplicate game pairs — same / mirrored | **4 / 4** | §18 Q13 |
| duplicate teams (name + gender) | **6** | §8.8 |
| engine entry points reaching a page | **853 of 898** | §1 |
| suite | **290 pytest + 97 run_all**, green | §19 |

---

## 21 · The roadmap — September to next offseason

§16 is the four-week schedule. This is the shape around it, because the real
deadline is not the end of September — it is **the day you sit four coaches down
in October** and the app stops being yours alone.

```
  SEP          OCT              NOV — MAR                 APR — JUN
  ---------    -------------    ---------------------     -----------------
  FIX          HAND OVER        RUN (frozen)              BUILD
  4 blockers   train 4-5        one click a morning,      the things that
  + the month  coaches,         one capacity glance,      needed a season
  in §16       watch, log       a list not a branch       of real data
```

### Phase 0 · September — make it safe to hand over

Everything in §16, with four items promoted to **blockers**. A blocker is
something that, left alone, makes a new coach distrust the app in week one — and
distrust does not get re-earned.

| # | blocker | why it blocks October | § |
|---|---|---|---|
| **B1** | **No number without its sample** | Four new readers who do not already know the pools. "80th percentile" over ten teams and "0.6 rebounds a game is elite" are the two sentences that end trust fastest. | §10 |
| **B2** | **The Free box score** | You are recruiting coaches. Today a Free account sees a scoreboard and a padlock where the box score should be — the one artefact every coach already understands. | §12.2 |
| **B3** | **Own creation** (`tracked_by` in the read filter, joined through `coach_teams`) | 51% of the book is invisible to the person who typed it. In October there are five people on team 1 and the number gets worse, not better. | §9.2 |
| **B4** | **One abbreviation, one meaning** (`SCE` / `ScEff`) | A coach taps the stat key to learn a column and is told the wrong metric. It is unfixable-by-explanation once four people have learned it wrong. | §18 Q12 |

Everything else in §16 is a strong should. These four are the gate.

**Definition of done for Phase 0** — walk it as a *new coach*, not as yourself:

```
[ ] a Free account can open a box score and read it
[ ] every percentile on screen says what pool it is over
[ ] no superlative fires on a sample that cannot support it
[ ] no bare jersey number is rendered as a person's name
[ ] the coach who tracked a game can read it, on either email
[ ] a forfeit is not the league's best defence
[ ] SCE means one thing everywhere, and the glossary agrees with the code
[ ] the rollover, ANALYZE, rating-history and backup-verify timers are INSTALLED
[ ] pytest is green (the three red tests in test_read_filter_empty_scope go green
    when the empty-filter sweep lands — that is the signal, not a chore)
[ ] Players cold render is under ~15 s
```

### Phase 1 · October — hand over, and let the training be the test

The training session is the **best user research you will ever get for free**,
and it happens exactly once. Do not spend it demonstrating; spend it watching.

**Three things to instrument before the session** (all cheap, all disposable):

1. **Which pages get opened, in what order.** You have `audit_log` and a
   capacity panel; a page-view counter is a row. Your ordering instinct
   (Overview → Scout → Insights) has never been checked against anyone else's.
2. **Which empty states get hit.** Every empty state is a promise the app failed
   to keep. §0.1's Lineup Creator was found this way and it will not be the last.
3. **Whether the co-op toggle gets touched at all.** §0.2: six paid accounts,
   **one** sharing team, 11 of 63 pooled. If nobody flips it after being shown it,
   the pitch is wrong, not the coaches.

**Three things to say out loud in the room**, because they are the app's real
differentiators and none of them is self-evident from a screen:

* *"Every number tells you how much data is behind it"* — after B1, this is true
  and no competitor at this level can say it.
* *"Wins over top-25 teams are counted as of the day you played them"* — the
  point-in-time résumé. 71 of 102 teams get a different count than the naive
  version. Nobody else does this.
* *"Share to scout"* — and then show them the pooled view with their own team in
  it. The co-op only sells with a screen, not a sentence.

**What NOT to do in October: ship.** Every change after the training is a change
four people have to re-learn. Write it down instead.

### Phase 2 · November to March — run it, frozen

The season is the point of all of this. The operating loop should be exactly:

```
every morning     one click     the OSSAA scrape (§17 — manual by decision)
every game night  the phone     open, log, End Game. Nothing else.
once a week       one glance    Settings → Coaches online & server capacity
never             —            open a page in anger
```

Everything else runs on the timers installed in Phase 0. **The rule for the whole
season is: findings go in a list, not a branch.** A mid-season deploy is a
mid-season regression risk on the one thing you cannot re-run — the games.

Two exceptions worth pre-agreeing, so the judgement call is already made:

* **A wrong number on screen** is worth a hotfix. A missing feature is not.
* **A tracker (PWA) bug** is worth a hotfix, because it costs data permanently.
  A Streamlit reading bug can wait — the events are already safe.

### Phase 3 · April to June — the builds that needed a season

These are deferred on purpose, and each has a *reason it could not be done now*:

| item | why it waits | § |
|---|---|---|
| **Per-official whistle profiles** | 11 officials now have ≥5 games, one has 9. Another season puts the busiest past 15 — and officials are career-long and never archived, so this compounds without any work. | §15 |
| **The Synergy framing** (frequency × efficiency on one line) and the **defensive mirror** | Better designed against a season of coaches actually using play-type reads than against your own intuition. | §13.5–13.6 |
| **The player view as one OOTP screen** | Needs Phase 1's answer to "which page do they open first". | §4, §14 |
| **Setup's `st.tabs` → `_seg`** | Needs the AST sweep for cross-tab variable leaks, and it is a refactor with no coach-visible payoff — exactly the wrong shape for September. | §14 |
| **In-stint fatigue, revisited** | Only with real on-floor minutes (`possession_secs` accumulated) instead of event counts. Two rejections on two books say do not attempt it before then. | §15 |
| **The Whiteboard** | Revisit with usage data from a real season (Q10). | §14 |
| **Development / progression reads** | `helpers/development.py` is built and needs **two tracked seasons** to mean anything. April is the first time it does. | §4 |

**And one thing that arrives on its own:** next season's scorebook access takes
players from ~11% named to ~90% and officials to ~70%. Every naming decision in
this document was made assuming that — which is why §0.1 downgraded it from a
project to a label helper.

---

## Closing

The honest summary is that you have built the hard part. The engines are good,
the reliability discipline is better than the market's, and the co-op is a real
idea. What is between you and the product you described is a month of gating,
labelling and wiring.

The rulings and the production pull made it shorter. **Four of the loudest
findings in the first draft did not survive:** the open archive is the funnel and
not a leak; the hair-colour officials were never in production; `passing_chains`
is not returning an empty graph; and `turnover_type` was never abandoned. Three
of those four were the same mistake — auditing a development copy and calling it
the live book — and `tools/pull_prod_snapshot.py` closes that door.

**What got bigger is more interesting than what got retracted.** Own-creation now
strands **32 of 63 tracked games** from the coach who typed them in. The officials
sample went from *impossible* to *one more season*. The boys' leaderboard crowns a
**0–3 team as the best defence**. And nothing in this document is blocked on a
decision any more — all fourteen questions are answered.

**If you only do three things in September:** the Free box score, the percentile
honesty pass, and the eager-report fix. The first makes the product sellable, the
second makes it trustworthy, and the third makes it usable on the hardware you
have.
