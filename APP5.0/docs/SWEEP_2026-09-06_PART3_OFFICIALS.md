# Sweep — 2026-09-06 · Part 3: the Officiating Lab

Companion to Part 1 (gating) and Part 2 (Team Dashboard). Read-only, measured
against a `sqlite3.backup` copy of the live book. **The live book was never
written to.** No application code changed.

The headline is that **roadmap item 8 — the officials rating rework, described in
two documents as "the biggest single piece of thinking on the board" — is
already done**, and the thing that is actually wrong is smaller, sharper and
measurable. What is left is a sample-size problem the page does not admit to,
and a names problem that has put a physical description at the top of the
league table.

---

## 1 · The sample, first, because everything else depends on it

Officials are attributed on **fouls only**, and fouls are 1,115 of 7,731 events.

```
officials on file                                70
games carrying an assigned crew                  44   (43 tracked + 1 untracked)
fouls in the book                             1,115   (100% carry an official_id)
fouls in games with no assigned crew               5

games worked, per official:
    1 game    30 officials
    2 games   20
    3 games   14
    4 games    4
    5 games    2      <- the maximum any official has
```

**No official in this book has worked more than five games, and the busiest has
44 total calls.** The median official has worked one.

`RATING_MIN_GAMES = 3` therefore admits **20 of 70** officials — 29%. The other
50 render as unrated rows in the same table.

Crew sizes carry an artefact the code already knows about
(`CREW_MAX_REAL = 3`): 40 games have the normal three officials, one has one,
one has five, two have six.

Fouls by quarter, league-wide — a clean, publishable fact the page does not yet
state as a sentence:

```
Q1  227     Q2  288     Q3  283     Q4  314     OT  3
```

Q4 carries **38% more whistles than Q1**. That is a real coaching input (foul
trouble compounds late, and the bonus arrives) and it is exactly the kind of
league read the app is good at everywhere else.

---

## 2 · Roadmap item 8 is stale — both halves of it

**The roadmap says:** *"Officials rating rework … 60% of the current weight is a
property of the GAMES, not the referee. The priced-games floor is decided
(`rated_games >= 3`) and not yet applied."*

Both claims are already resolved in the tree.

### 2.1 · The game-environment terms are already out of the score

`helpers/officials.py:605-618` carries a completed reliability study:

> *"No game-environment metric survives either. Team-adjusted game fouls looked
> significant at 43 games (p=0.038) and decayed to p=0.191 on the 63-game
> superset, while team-adjusted pace moved the other way (p=0.397 → p=0.036). The
> significant result changes metrics between samples, which is multiple
> comparisons rather than an effect. FPG, leverage, PPP, pace and clutch stay on
> the row as DESCRIPTORS and enter no score. … Share DID hold up and strengthened
> with sample — across 63 games the top ref's slice averages 43.7% against a
> matched null of 40.8%."*

`_RATING_TERMS` is now two entries — `share` at 0.75 and `volume` at 0.25 — and
`official_ratings`' docstring says the descriptors "enter no score".

**Verified.** Correlations between the published rating and every descriptor,
over the 20 rated officials on this book:

```
rating vs leverage     r = +0.135
rating vs PPP          r = +0.286
rating vs POSSPG       r = -0.127
rating vs clutch_pg    r = +0.024
rating vs games        r = +0.143
```

None of those is a relationship. The rework the roadmap describes has happened.

### 2.2 · The floor is applied — to the wrong count

`RATING_MIN_GAMES = 3` is defined **and enforced**: `official_ratings:1002` and
`:1009` both gate on it. So the second half of the roadmap item is also stale.

But it gates on `r["games"]`, not on `r["rated_games"]` — and the docstring
distinguishes them deliberately:

> *"A ref is rated on games that could actually price a share, which is a
> stricter pool than 'games worked' — a blowout or a whistle-free night tells us
> nothing about how the crew split the work."*

The stricter pool is computed, stored on the row, and then not used as the
floor. On this book, four of the top fourteen officials carry
`rated_games < games`, including the one ranked first.

**Fix:** `if r["games"] < RATING_MIN_GAMES or r["rated_games"] < RATING_MIN_GAMES`.
One line, and it is what the roadmap item asked for.

---

## 3 · What IS wrong: `volume` re-imports the game

The rating is 75% share and 25% volume. Share is crew-relative — a ref's slice of
one game's live calls against their fair share of that same game — so game
context divides out. **Volume does not.** `live_pg` is a raw count of live calls
per game, z-scored across officials with no adjustment for the games those
officials happened to work.

The result, over the 20 rated officials:

```
rating vs share_z      r = -0.940      the design
rating vs worst_z      r = -0.924      the design
rating vs live_pg      r = -0.871
rating vs FPG          r = -0.814      <-- the problem
```

The docstring is explicit that FPG must not carry a goodness sign:

> *"In particular FPG carries no goodness sign: a tight crew is a different game
> plan, not a worse crew."*

**In practice the published rating correlates −0.81 with fouls per game.** A crew
that works fast, physical, foul-heavy games is marked down for it. That is the
roadmap's "a property of the GAMES, not the referee" claim — correct in
substance, wrong in target: it is not 60% of the weight spread across leverage
and pace, it is the **one term at 25%** that was consciously kept.

Rendered, the whole table is monotone in fouls per game:

```
name                gms  rated  rating  share_z  worst_z  live/g   FPG
White Bald            3      2    54.6    -1.98    -0.65    2.50   1.67
Dustin McGraw         3      3    53.6    -1.51    -0.69    4.00   5.33
Watch                 3      3    52.9    -1.36    -0.60    5.67   5.67
Gene Brooks           3      2    52.4    -0.85    -0.65    5.00   6.67
Female 3rd            4      3    51.1    -0.63     0.98    3.33   2.75
James Francis         5      4    50.7    -0.60     0.76    5.25   4.60
Colby Farrar          3      3    50.6    -0.45    -0.25    8.33   9.00
Kurt Schultz          3      3    45.8     0.06     1.10    7.33   7.33
Nate Haney            4      4    44.9     0.32     1.30    6.25   8.25
Tevin Gibson          3      2    44.6     0.39     0.45    9.00   9.67
Ray Wilson            3      3    44.5     0.16     1.32    7.33   7.67
Jimmy Williams        3      3    44.2     0.42     1.00    7.33   8.00
Jamie Waltonbaugh     5      4    44.0     0.59     1.20    6.00   5.00
Kaleb Trowbridge      4      3    43.2     0.04     1.25    9.33   7.50
```

### 3.1 · And the credit asymmetry did not achieve its stated goal

The block comment above `_RATING_TERMS` says:

> *"The credit side is asymmetric on purpose. Scoring low share symmetrically
> would crown the quietest ref in the league as its best; at a quarter slope they
> land above average and nowhere near the top. Quiet is worth a little.
> Disappearing is not excellence."*

On this book **the quietest official IS the top of the table.** "White Bald" is
ranked first at 54.6 on 1.67 fouls per game across three games worked and **two**
priceable — the lowest FPG of any rated official. `CREDIT_FACTOR = 0.25` moved
them "above average"; it did not stop them being first, because nobody on the
credit side of the ledger has a strong enough positive to overtake them.

**Two fixes, either of which works:**

* a **hard floor on live calls** before a rating is published — an official who
  called five fouls across three games has not demonstrated anything, in either
  direction; or
* score `|share deviation|` toward 50 rather than signed, and rank on
  *confidence-weighted* distance from a normal split, so both tails are "unusual"
  and the middle is "normal". That is what the rating claims to measure
  ("50 = a crew that split the game normally") and it removes the need for the
  asymmetry constant entirely.

The second is the more honest reading of the docstring's own sentence.

---

## 4 · The names problem, which is on screen right now

`is_placeholder_name` matches `^\s*unknown\b` and nothing else:

```python
_PLACEHOLDER_NAME = re.compile(r"^\s*unknown\b", re.I)
```

Its docstring explains the intent — *"the `Unknown 11` rows the tracker writes
when nobody caught the official's name … they sort below every named ref so the
ends of the table stay actionable."*

The book does not use `Unknown N`. It uses physical descriptions:

```
3rd W Hair · Bald Bald · Balding · Chubby Bald · Female 3rd · Grey Hair ·
Hefty · Hefty Bald · Old Bald · Watch · White Bald · Assistant AD
```

Twelve of seventy. None of them matches the regex, so all twelve sort among the
named officials, and the consequences are visible on the rendered page:

```
BEST SHARED CREW    55   White Bald
BIGGEST H/A LEAN    +3   Bald Bald
```

The app's league-leader card for officiating fairness currently names a hair
colour. **This is the single most embarrassing thing in the sweep** and it is
also the easiest to fix.

**Fix:** widen the detector. A name is a placeholder when it matches a small
vocabulary of appearance/role words (`bald`, `hair`, `hefty`, `chubby`, `grey`,
`white`, `old`, `3rd`, `female`, `male`, `watch`, `assistant`, `unknown`), or —
better and more durable — add an explicit `officials.is_placeholder` column set
by the tracker when a coach uses the "describe them" path instead of typing a
name. The regex is a stopgap; the flag is the right answer, and Setup already
has the officials-management UI to expose it.

There is also **"Colby Farrar" in the officials table** with three games worked
and 9.00 FPG. Either the founder officiates, or the tracker recorded the logging
coach as an official on three games. Worth one look at those three game ids
before any of this is published to other coaches.

---

## 5 · Numbers published without a sample

The page's hero strip, rendered:

```
TIGHTEST WHISTLE    10.3   David Farley · FP100
MOST LENIENT         0.0   Mike Gaskins · FP100
BIGGEST H/A LEAN      +3   Bald Bald
MOST CONSISTENT     ±0.0   Alex Dout · FPG
HOTTEST ENV.        1.25   Damerion Hooks · PPP
BEST SHARED CREW      55   White Bald
MOST ONE-SIDED        23   John Cook · worst game +2.8σ
BIG-STAGE REF       0.85   Keith Bergman · leverage
MAKES THE CALL        10   David Farley · clutch
```

Cross-referenced against the book:

* **"MOST LENIENT 0.0 — Mike Gaskins"**. Mike Gaskins has **one** foul in the
  entire book. The card is an award for the smallest sample.
* **"MOST CONSISTENT ±0.0 — Alex Dout"**. A game-to-game foul swing of exactly
  zero is what you get from one game, or two identical ones. It is not
  consistency; it is an absence of evidence.
* **"BIGGEST H/A LEAN +3"** — three fouls of lean, on an official who has worked
  at most a handful of games.

None of the nine cards carries an `n` or a confidence dot, and `helpers/cards.py`
already exports `conf_dot` for exactly this.

The page also runs **three different minimum-sample floors on one screen**:

```
"Fouls per game — min. 2 games"
"FP100 leaders — min. 1 game"
RATING_MIN_GAMES = 3
```

One floor, stated once, applied everywhere.

---

## 6 · `foul_type` is gone — and that closes the survey item the other way

The QOL survey's B6 recommended wiring `game_events.foul_type` (shooting /
common / offensive-charge / intentional / technical), calling it *"exactly the
axis the officials rework needs to separate 'a tight crew' from 'a bad crew'"*.

**It was dropped instead, by founder ruling, on 2026-09-05** —
`mig_drop_foul_type_v1` at `database/db.py:919-951`, with the reasoning recorded
in full:

> *"Added 2026-07-11 for a foul-KIND tag that was trialed and reverted, it then
> sat NULL on all 1,115 fouls in the live book for a full season with zero
> readers and zero writers … Founder ruling 2026-09-05: delete rather than
> reserve."*

The column is genuinely absent from the live book's `game_events` (25 columns,
verified). So B6 is closed.

**But state the consequence plainly, because it lands on this page:** the axis
that would let the Officiating Lab distinguish *how* a crew calls a game — and
which unlocks and-1 rate, shooting fouls allowed, free-throw generation and
drawn-charge rate — no longer exists in the schema. Re-opening it is a column,
a tracker chip row, an Event Editor column and a backfill that can never reach
the 1,115 fouls already logged. That is a product decision, not a bug, and it
should be made deliberately rather than rediscovered.

Worth noting that `charges` are still captured separately, so drawn-charge rate
is not entirely lost.

---

## 7 · Layout

### 7.1 · Sixty thousand characters of unrelated glossary

`pages/8_Officials.py:926` calls `glossary_tab("off_gloss")`, which renders **the
full app-wide stat catalogue** — box score, shooting, playmaking, signature
metrics, everything — inline at the bottom of a page about referees.

The scale of it shows up in a measurement made for a different purpose. Rendered
for two personas whose officials data genuinely differs:

```
paid-solo    24 visible games → 50 officials, 566 fouls → page 110,520 chars
paid-league  29 visible games → 59 officials, 727 fouls → page 110,530 chars
```

Nine more officials and 161 more fouls move the page by **ten characters**,
because roughly 60% of it is a glossary neither coach came for.

Unlike Team Dashboard, Rankings and War Room, Officials has no view switcher, so
this is not a Glossary *tab* — it is an append. Either give the page a view
switcher (`Lab · Officials · Crews · Glossary`) or replace the call with the
four-term `glossary_key` popover the page already uses at `:368`.

### 7.2 · The page answers the wrong question

Rendered in order, the page is: a whistle-leaders hero strip, play-type foul
bias, defensive foul bias, most-fouls chart, fouls-per-game chart, home/away
lean, whistle archetype, the full official table, PPP of games worked, pace of
games worked, average total score, tightness-vs-pace, most consistent, fouls by
quarter, home vs away, fouls against each team, FP100, foul-timing fingerprint,
a per-official drill-down, crew pairs.

Twenty blocks, almost all of them **rating the officials**. A coach does not open
this page to rate officials. They open it the day of a game, having just been
told who the crew is, to answer one question: **what should we do differently
tonight?**

`helpers/ref_tendencies.crew_outlook` already produces exactly that answer and it
is *not on this page* — it is only reachable from the War Room's matchup view
(`pages/9_War_Room.py:747` and `:781`).

**Proposed layout**, following the Insights pattern (verdict first, then depth,
lazy sections):

```
Officiating Lab
├── CREW OUTLOOK  (leads)   pick tonight's crew → the plain-language read:
│                           expected whistle rate vs league, who it favours,
│                           how the calls skew by quarter, what it means for
│                           foul trouble — each line with its n and confidence
├── This official           the existing per-ref drill, unchanged
├── Crews                   crew_pairs, promoted out of the tail
├── League                  the quarter curve, home/away, FP100 distribution —
│                           the descriptive blocks, collapsed by default
└── Ratings                 the 0-100 table, with the floors of §2.2 and §5
```

The engine for the top section exists. Moving it here is wiring.

---

## 8 · Gating (carried over from Part 1, verified here)

* **The page hard-stops for Free at `:219`** with its own copy of the lock text,
  and — unlike `pages/9_War_Room.py:256`, which guards with
  `if _is_cur_season and not has_paid_plan` — it does **not** bypass for a past
  season. On the live book, where the only populated season is an archive, a
  Free coach is locked out of content the app's own open-archive rule says is
  free. Rendered: 41,303 characters against admin's 110,536.
* **`:238` calls `ENT.visible_tracked_game_ids(...)` with no season argument**,
  so the read-filter resolves to the default read season rather than the season
  the page's own picker is showing.
* **The empty-visible-set widening** at `:146`, `:155`, `:162`, `:179`
  (`game_ids=(set(gids) if gids else None)`): when the current-season branch at
  `:245` builds `tuple(sorted(_off_vis))` from an empty set, the result is `()`,
  which those four wrappers convert to `None` — unrestricted. Reachable by a Paid
  Solo coach with no tracked games of their own. Covered by
  `tracker/test_read_filter_empty_scope.py`, which fails on `main` today.
* **The engine itself scopes correctly** — verified, and worth recording so it is
  not re-suspected: `official_overview` returns 50 officials / 566 fouls for a
  paid-solo viewer, 59 / 727 for paid-league, 70 / 1,065 for admin. The near-
  identical rendered page sizes in §7.1 are the glossary, not a leak.

---

## 9 · Ranked

| # | item | § | effort | risk | needs a ruling? |
|---|---|---|---|---|---|
| 1 | **Widen the placeholder-name detector** (and add an `is_placeholder` flag) | 4 | ½ session | low | flag vs regex |
| 2 | **Gate the rating on `rated_games`, not `games`** | 2.2 | 15 min | low | no |
| 3 | **Sample chips on all nine hero cards** (`conf_dot` exists) | 5 | ½ session | low | no |
| 4 | **One minimum-games floor, stated once** | 5 | 1 hour | low | the value |
| 5 | **Fix `volume`'s game contamination** — crew-relative or drop the term | 3 | 1 session | medium | yes: the term is deliberate |
| 6 | **Rating as distance-from-normal rather than signed** — retires `CREDIT_FACTOR` | 3.1 | 1 session | medium | yes |
| 7 | **Crew outlook leads the page** (engine exists, in the War Room) | 7.2 | 1 session | low | no |
| 8 | Replace the inline full glossary with the popover | 7.1 | 15 min | none | no |
| 9 | Archive bypass on the Free stop, matching the War Room | 8 | 15 min | low | Part 1 §1 first |
| 10 | Empty read-filter widening (4 sites) | 8 | with the Part 1 sweep | low | no |
| 11 | Look at the three games where "Colby Farrar" is an official | 4 | 10 min | none | no |
| 12 | Publish the Q1→Q4 whistle curve as a sentence | 1 | ½ session | none | no |

**Items 1, 2, 8 and 11 are an afternoon between them**, and item 1 is the one a
coach would notice first.

---

## 10 · What is not finished

* **The rework proposal in §3 is a diagnosis, not a fitted model.** Partialling
  pace and team foul-drawing rate out of `volume` needs the walk-forward gate the
  house rules require before any constant moves, and this book (max 5 games per
  official) cannot support it. Production carries ~62 tracked games and the study
  quoted in `officials.py:605` was already run at 63 — that is the sample to
  re-run against, not this one.
* **`crew_pairs` and `ref_tendencies.crew_outlook` were read but not exercised.**
  §7.2 proposes promoting the outlook without having measured what it says on
  this book.
* **The per-official drill-down was not audited block by block** — only its
  section headers were captured.
* **No timing work.** The page rendered in 3.5 s for admin, which is not a
  problem, but `official_ratings` loops `score_ratings` over every distinct
  tracked season (`:169-175`) and that was not measured.
* **The 45-foul reconciliation gap** — the page header reports "Assigned fouls
  1065" against 1,115 fouls in the book, of which only 5 are in games with no
  crew. The remaining 45 were not chased.
