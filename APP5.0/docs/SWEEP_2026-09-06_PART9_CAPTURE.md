# Sweep — 2026-09-06 · Part 9: capture quality and the write pages

Part of the September sweep (Parts 1 gating, 2 Team Dashboard, 3 Officiating Lab,
4 Rankings, 5 database, 6 engines, 7 War Room / Players, 8 what to build).
Read-only against a `sqlite3.backup` copy of the live book. **The live book was
never written to.** No application code changed.

Everything downstream rests on what the tracker captures, so this part starts
there — including a correction to how two previous surveys measured it, and a
quantified bias it produces in a read that is live today.

---

## 1 · Tag coverage: both previous accounts used the wrong denominator

The QOL survey and this sweep's own first pass both measured `play_type` and
`defense` coverage against **all events**. That is the wrong denominator, and it
makes the coverage look worse and noisier than it is.

Measured by event type:

| event type | n | `play_type` set | `defense` set |
|---|---:|---:|---:|
| shot | 4,019 | **90%** | **88%** |
| turnover | 1,475 | **63%** | 89% |
| foul | 1,115 | **63%** | 88% |
| free throw | 1,122 | 0% | 0% |

Free throws carry neither, **by design** — a free throw has no set call and no
scheme in effect. `helpers/manual_box.py` and the Event Editor both say so
explicitly (*"Free throws don't carry a defense"*). So every all-events
denominator silently includes 1,122 rows that can never be tagged, which is 14.5%
of the book.

**The real picture is much better than reported:** shots are tagged at 90% / 88%,
which is excellent capture. The gap is `play_type` on **turnovers and fouls**, at
63% each — a coach taps a live turnover or a foul quickly and skips the set call.
That is a specific, believable behaviour, and it has a consequence.

### 1.1 · The consequence: every play-type PPP in the app reads high

Points per possession by set call is computed over *tagged* possessions. Shots
carry the tag at 90% and turnovers at 63%, so the tagged sample under-represents
the zero-point outcomes — and it does so more for turnover-prone actions than for
catch-and-shoot ones.

Scaling the turnover side up to the shot side's coverage rate (a factor of 1.41):

| set call | shots | tagged TOs | PPP as shown | PPP corrected | overstated by |
|---|---:|---:|---:|---:|---:|
| spot | 873 | 6 | 0.823 | 0.820 | +0.002 |
| putback | 298 | 9 | 0.834 | 0.824 | +0.010 |
| dho | 122 | 34 | 0.500 | 0.459 | +0.041 |
| iso | 724 | 289 | 0.421 | 0.376 | +0.044 |
| pnr | 123 | 33 | 0.603 | 0.554 | +0.048 |
| offscreen | 132 | 17 | 1.087 | 1.038 | +0.049 |
| duckin | 137 | 21 | 0.943 | 0.894 | +0.049 |
| blob | 178 | 45 | 0.637 | 0.588 | +0.049 |
| transition | 616 | 233 | 0.717 | 0.644 | **+0.073** |
| post | 210 | 120 | 0.594 | 0.516 | **+0.077** |
| cut | 168 | 116 | 0.553 | 0.473 | **+0.080** |

The **ordering survives** — no pair swaps — so no coaching decision flips. But
the **gaps compress**, and they compress in one direction: the turnover-prone
actions (cut, post, transition) are flattered relative to the ones that almost
never turn it over (spot, putback). Cut's true deficit behind a spot-up is
**0.347, not 0.270 — 29% larger than the app says.**

Two honest caveats:

* `spot` at 6 tagged turnovers against 873 shots is probably *real* — a
  catch-and-shoot rarely produces a turnover — so a uniform scaling over-corrects
  it. At +0.002 it does not matter, but the correction should be per-action
  coverage, not a single league factor, if this is ever built properly.
* The bias holds even if the coach's skipping is perfectly random. It is not a
  bias in the *rate*; it is a bias in the *composition of the denominator*.

**Fix, cheapest first:** report the turnover-tag coverage beside any play-type
PPP table, the way `helpers/defenses.py` and `helpers/playtypes.py` already carry
`total_tagged` / `untagged` for the shot side. Then, if it is worth more, apply
the per-action correction.

### 1.2 · `turnover_type` is a per-game switch, and it was switched off

`turnover_type` is 512 of 1,475 (34.7%) overall, and the previous survey's read —
*"it appears at 100% and at 0% on both desktop and mobile games… a tag the coach
skips under pressure"* — is right about the bimodality and misses the pattern.
Per game, ordered by date, it is almost perfectly **on or off**, and it goes off
and stays off:

```
on   (92-100%):  2025-12-08 … 2026-01-30      15 games
off  (0-3%):     2026-01-30 … 2026-03-11      the rest
```

The last game with meaningful coverage is 2026-01-30. Everything after it is 0%
or 3%. That is not pressure-skipping — that is a habit that stopped, and it
stopped mid-season with ten games to go.

`helpers/coverage.py` — the app's stated honesty keystone — gates `play_type`,
`defense` and `guarded_by` and **does not gate `turnover_type`**. So
`helpers/turnovers.py` reads it with no coverage gate, and any live-vs-dead-ball
turnover split is silently weighted to the first 60% of the season. Adding it to
`coverage.py` is the cheapest honesty win available.

### 1.3 · Location capture is essentially perfect

`shot_x/shot_y` is at **100% on every tracked game except three**, and those
three (`gid` 4, 3, 27) are the old desktop-path games with no `client_uuid`, no
tags of any kind, and 0% location. They were never captured, so they can never be
retagged — a different case from a row awaiting a back-fill, and the UI should
say so rather than lumping them into "untagged".

---

## 2 · The Event Editor is the best-designed page in the app

It is also the one this sweep expected least from.

Rendered header, for the most recent playoff game:

```
🏷️ Play calls tagged  0% · 0/83        🛡️ Defense tagged  6% · 7/110
```

Three things it gets right that no other page does:

1. **It states its own coverage, up front, with the correct denominator.**
   83 taggable events, not 163 total — it already knows free throws cannot carry
   the tag. Every analytics page in the app should be borrowing this line.
2. **It ships the fix, not just the diagnosis.** Bulk back-fill by quarter, by
   team, by event range — *"Applies to 17 event(s) — Q1 7:43 → Q1 4:30"* — plus a
   whole-game default with per-row exceptions.
3. **Its copy teaches the data model.** *"Pick the defense each team **faced** on
   its possessions (the scheme the OTHER team was running)"* is the single
   clearest sentence about this schema anywhere in the repo, and
   *"Events that can't carry the chosen tag (e.g. a free throw, or a non-turnover
   for TO kind) are skipped, never corrupted"* is exactly the reassurance a coach
   needs before pressing a bulk button.

**The finding is that this is invisible from everywhere else.** A coach with ten
untagged playoff games has no reason to open the Event Editor, because nothing
tells them the games are untagged. The coverage line belongs on the Team
Dashboard's schedule and in the season feed, with a link — *"3 games this season
have no set calls tagged · back-fill them"*.

---

## 3 · Hall of Fame already solved the problem Rankings has

Part 4 §1 found the Rankings leader cards defaulting to a minimum of one game and
crowning a forfeit as the league's best defence. The Hall of Fame, on the same
book, does it correctly:

```
🏅 Season bests — per game        (min 10 games)
🏛️ Career leaders — totals        (min 25 games)
🏆 Team pantheon
     Best seasons — Power rating  (min 10 games)
     Best records                 (min 15 games)
```

Every leaderboard carries a floor, and the floor is **stated in the heading**.
That is the pattern Rankings, Players and the Officiating Lab all need, and it is
already written, tested and shipping one page over.

Hall of Fame's own weakness is the opposite one: at a 14% read share (6 reads,
36 labels) it lists without interpreting. And the overnight doc named quality
wins as a nearly-free addition to it once `helpers/resume.py` shipped; that is
still not done.

---

## 4 · Setup runs four tab bodies on every rerun, and one of them is 1,448 rows

`pages/11_Setup.py:79` uses `st.tabs` over four tabs — the last surviving
top-level `st.tabs` on a heavy page, and one of the eighteen the roadmap's item 6
tracks. `st.tabs` executes **every** body on **every** rerun, so opening Setup to
change one player's position also builds:

* the Teams tab's editable dataframe — *"1448 of 1448 teams — edit the District
  cell, then Save"*;
* the Games tab's table — *"500 game(s) — first 500; narrow the filter to reach
  more"*;
* the box-score entry tab and its CSV importer.

A 1,448-row `st.data_editor` and a 500-row table, both rebuilt whenever anything
on the page changes. The `_seg` conversion the rest of the app uses is the fix,
and the roadmap correctly says it needs an AST sweep for cross-tab variable leaks
first — but this page is the one where the conversion is worth the most.

**Note for whoever does it:** Setup is also where the officials-on-untracked-games
flow lives, and its explainer is unusually good — *"they count as games worked and
feed the crew outlook the same way an untracked game does… It does NOT record
which ref made which call, so the Officials Rating stays tracked-only"*. Keep
that copy.

---

## 5 · The Game Tracker

The app's only live write surface, and it is in good shape. Its pre-game read is
genuinely useful:

> **Adair Girls** — Key scorers: Ali Schwerdfeger 13.7p · Hannah Bond 12.2p ·
> Reagan Langley 9.9p
> **Dewey Girls** — Key scorers: 14 10.0p · 22 10.0p · 10 9.0p

with the caption *"Built from each team's PRIOR tracked games — a pregame read,
not this game's live stats."*

Two notes:

* **The nameless-player problem is worst here.** Part 7 §2 counts 486 of 541
  players with no name; this is the surface where it costs the most, because
  "the opponent's key scorers are 14, 22 and 10" is the one line a coach reads
  before tip-off. `player_label()` fixes it everywhere, and this is the screen
  that justifies the work.
* **`Adair Girls win odds 100%`.** On a finished 63–41 game that is defensible,
  but a probability rendered as exactly 100% invites a coach to test it. Clamp
  the display at 99%.

The rest of the page's copy is strong, and the season banner —
*"📅 2025-2026 season game — rosters and quick-adds use that season's players;
nothing here touches current-season stats"* — is exactly the kind of guard the
rollover trap needs.

---

## 6 · Smaller notes

* **Input Hub's rollover warning is correct and clear**, including the
  open-archive consequence: *"past seasons become an open archive (free, full
  depth, visible to everyone)"*. Worth reading beside Part 1 §1 — the app already
  tells a coach the rule that turns out to be handing away the paid product in
  the offseason.
* **The rollover will carry forward 221 players**, of whom the large majority are
  named after their jersey number. Naming them, or deciding not to carry unnamed
  opponents forward, is a rollover-time decision that has not been made.
* **Settings is honest about the local state** — *"Sign-in is currently off —
  anyone who can reach this app can use it"* — and about the unset tracker URL.
* **Verdict density on the write pages** (Setup 50%, Input Hub 44%, Settings 33%,
  Event Editor 30%, Game Tracker 23%) is not comparable to the analytics pages:
  these surfaces are mostly widgets, which the harness does not capture as text.
  Recorded for completeness, not as a judgement.

---

## 7 · Ranked

| # | item | § | effort | risk | needs a ruling? |
|---|---|---|---|---|---|
| 1 | Add `turnover_type` (and `shot_created_by_id`) to `coverage.py` | 1.2 | 1 hour | none | no |
| 2 | Report turnover-tag coverage beside every play-type PPP table | 1.1 | ½ session | low | no |
| 3 | Surface the Event Editor's coverage line on the schedule + season feed | 2 | ½ session | low | no |
| 4 | `player_label()` — justified by the Game Tracker pre-game read alone | 5 | ½ session | low | no |
| 5 | Rankings / Players / Officials adopt Hall of Fame's stated-floor pattern | 3 | with Part 4 §1.1 | low | the values |
| 6 | Setup: `st.tabs` → `_seg` (AST sweep first) | 4 | 1 session | medium | no |
| 7 | Per-action turnover-coverage correction on play-type PPP | 1.1 | 1 session | medium | yes |
| 8 | Mark the three no-capture games as un-retaggable rather than untagged | 1.3 | 1 hour | none | no |
| 9 | Clamp displayed win probability at 99% | 5 | 15 min | none | no |
| 10 | Hall of Fame gets quality wins (named nearly-free in the overnight doc) | 3 | ½ session | low | no |

**1, 8 and 9 are under two hours together.**

---

## 8 · What is not finished

* **OSSAA Import and the Whiteboard were not swept.** The Whiteboard has one
  saved play in the book, so it is either unused or unfinished; that is a product
  question, not an audit one.
* **Setup's eager-tab cost was identified structurally, not timed.** The
  1,448-row editor is a strong hypothesis for the page's cost and it was not
  profiled.
* **The Event Editor rendered a different game than the one seeded** (its picker
  ignored the seeded key and defaulted to the most recent), so §2's numbers are
  from game 31, not 28. That does not change the finding, but the harness key for
  that page was never worked out.
* **§1.1's correction is a first-order estimate.** A proper version needs
  per-action coverage rates and a check on whether skipping correlates with
  anything (score margin, quarter, home/away) — none of which was tested.
* **The glossary and explainer audit is still outstanding** and overlaps §2 and
  §3 here.
