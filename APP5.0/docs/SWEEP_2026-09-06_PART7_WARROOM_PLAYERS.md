# Sweep — 2026-09-06 · Part 7: the War Room, the Players page, and 486 players with no name

Part of the September sweep (Parts 1 gating, 2 Team Dashboard, 3 Officiating Lab,
4 Rankings, 5 database, 6 engines). Read-only against a `sqlite3.backup` copy of
the live book. **The live book was never written to.** No application code changed.

Three findings here, in descending order of how quickly a coach meets them:

* **§1** — the War Room's headline tool, the one the page's own caption calls
  *"the decision every game turns on"*, **opens on an empty state for every
  viewer**, because its team picker defaults to the league's #1 team and the #1
  team has no tracked data.
* **§2** — **486 of 541 players in the book have no name**, only a jersey number,
  and the app publishes them in league leaderboards as bare integers. Seven of the
  top twelve players by OVERALL are rendered as numbers.
* **§3** — the War Room is nonetheless the **most verdict-first page in the app**,
  and its Matchup view is the standard the rest of the app should be measured
  against — ahead of Insights.

---

## 1 · The Lineup Creator opens empty, for everyone

Rendered, War Room → Lineups, as a Paid League-wide coach who staffs Adair Girls
(the best-tracked team in the book — 24 tracked games, 12 rated players):

```
Adair Girls  GREAT · 3A · 29-3 · 32 G · L1 · #48 of 704 · tracked #1 of 21 · 24 tracked

  Pick a team and a five for a possession-calibrated projection …

  🏀  No rated players on this team yet
      Track a game for them first.
```

The banner knows the team has 24 tracked games. The tool below it says there is
no tracked data.

### The cause

`pages/9_War_Room.py:1298`:

```python
_team_opts = order if _li_any else [t for t in order if t == _my_team]
...
_t = st.selectbox("Team", _team_opts,
                  format_func=lambda t: f"#{scored[t]['Rank']} {name_of[t]}",
                  key="wl1_team")
_tbl = _wl_table(gender, season_pick)
_rows = [dict(r, _pid=pid) for pid, r in _tbl.items() if r["team_id"] == _t]
if not _rows:
    empty_state("No rated players on this team yet", "Track a game for them first.")
```

`order` is `sorted(scored, key=lambda t: scored[t]["Rank"])`, so for a League-wide
viewer the selectbox offers **all 704 rated girls teams, ranked**, and defaults to
index 0.

Measured on this book:

```
the first eight teams the picker offers        rated players
  #1  Lincoln Christian Girls                        0
  #2  Washington Girls                               0
  #3  PUTNAM CITY NORTH Girls                        0
  #4  CANUTE Girls                                   0
  #5  Staley (Kansas City, MO) Girls                 0
  #6  Bixby Girls                                    0
  #7  Muskogee Girls                                 0
  #8  Bishop Gorman Girls                            0

first team in the list with any rated players    #22 Locust Grove Girls
teams in the list with rated players             21 of 704
team 1 (Adair Girls, the viewer's own)           12 rated players
```

**A coach must scroll past twenty-one empty options to reach one that works, and
the default is always one of the empty ones.** The engine is fine —
`_wl_table` returns 12 rated players for team 1 — and this is a Paid-gated tool,
so the coach paying for it is the one meeting the empty state.

A Solo coach is unaffected: `_team_opts` collapses to their own team.

**Fix, in two parts:**

1. **Default to the viewer's own team** when it is in the pool. `_my_team` is
   already resolved two lines above for exactly this purpose and is used only to
   build the Solo list.
2. **Only offer teams that have rated players** — or at minimum sort those to the
   top with the rest under a "no tracked data" divider. Offering 704 options of
   which 683 produce an empty state is not a picker, it is a maze.

**Defensive assignments does NOT share it** — re-rendered with the same
team-bearing identity it loses the *"Your team has no rated players yet"* message
entirely, so that one was purely the no-team identity of §1.1. The **Whiteboard**
is the same case: *"Plays are private to you — no team is linked to this account,
so there is no staff to share them with."*

### 1.1 · A related identity gap

`helpers/auth._LOCAL_IDENTITY` — the identity every no-auth local run uses, and
the documented local-dev mode — carries `"team_id": None, "team_ids": []`. Three
own-team surfaces degrade to an empty or apologetic state because of it: War Room
Lineups, War Room Defensive assignments, and the Whiteboard's sharing note.

On production the admin has `team_id = 1`, so this is a local-development and
fresh-admin problem rather than a coach-facing one. It is still worth resolving
`_LOCAL_IDENTITY`'s team from the book when there is exactly one coached team, so
that running locally exercises the same code path production does — otherwise
these three views are never seen working by whoever is developing them.

---

## 2 · 486 of 541 players have no name

```
players in the book                                   541
  name is blank or a bare jersey number               486      (89.8%)
  actually named                                       55

players with at least one tracked appearance          279
  of those, unnamed                                   242      (86.7%)
  named                                                37

qualified girls pool (min_games = 2)                   97
  unnamed in it                                        75      (77.3%)
```

This is correct **capture** behaviour — a coach tracking a game against an
opponent does not know the other roster, and logging by jersey number is the only
sane thing to do. The problem is entirely in **display**: the app then publishes
those integers as if they were names.

Rendered, Players page, girls:

```
Who leads each rating
  OVERALL      80.2  Hannah Bond
  OFFENSE      69.4  Hannah Bond
  DEFENSE      70.4  Ali Schwerdfeger
  PLAYMAKING   74.4  Ali Schwerdfeger
  REBOUNDING   80.7  12                    <--
  2WAY         69.5  Hannah Bond
  VERSATILITY  99.7  Hannah Bond

League superlatives
  71.4  Toughest diet     14   · shot difficulty      <--
   5.0  Clutch (Q4 PPG)   21   · 4th-quarter scoring  <--
  18.0  PPG leader        32                          <--
```

and the top of the OVERALL board:

```
  80.3  Hannah Bond        Adair Girls
  79.8  Ali Schwerdfeger   Adair Girls
  69.9  32                 Locust Grove Girls
  68.5  Reagan Langley     Adair Girls
  67.8  13                 Locust Grove Girls
  67.8  25                 Vinita Girls
  67.1  13                 Kansas Girls
  63.1  2                  Kansas Girls
  62.0  21                 Jay Girls
  62.0  12                 Kansas Girls
  61.9  Kealey Sanders     Adair Girls
  59.7  Finley Grubbs      Adair Girls
```

**Seven of the top twelve players in the league are rendered as bare integers**,
and two of them are both "13". The league's rebounding leader is "12".

The team-level surfaces already do better — `overview.py:123`,
`players_tab.py:213`, `defense_tab.py:753` all render `#{number} {name}` — but for
an unnamed player that produces `#12 12`, which is not better, only different.

**Fix — one helper, used everywhere.** `player_label(row)` returning:

* `Hannah Bond` when there is a real name;
* `#12 · Kansas Girls` when the name is blank or a bare number — honest,
  readable, and disambiguating, since two players called "13" are on different
  teams;
* never `#12 12`.

Then a second, separate decision: **should unnamed players appear in league
superlative cards at all?** They earned the numbers, so excluding them would be a
lie of a different kind — but "REBOUNDING leader: 12" is not a card anyone can
act on. A reasonable rule is to keep them in tables and rankings and exclude them
from the hero/superlative cards, the way Part 3 §4 proposes for placeholder-named
officials. The two problems are the same problem.

**And there is a cheap way to shrink it:** `ossaa_sync` already imports rosters
for schedule purposes. If it carries names, a one-time match on
`(team_id, number)` would name a large share of the 486. Worth measuring before
building anything.

---

## 3 · Verdict density: the War Room wins

Same measurement as Parts 2 and 4 — rendered strings classified as **reads**
(sentences: ≥8 words with a finite verb) or **labels** (chart titles, column
headers, metric names).

| surface | reads | labels | read share |
|---|---:|---:|---:|
| WR → Bracket | 13 | 3 | 81% |
| WR → Lineups | 13 | 3 | 81% |
| FAQ | 203 | 56 | 78% |
| WR → Defensive assignments | 11 | 4 | 73% |
| **WR → Matchup** | 17 | 8 | **68%** |
| WR → Season sim | 11 | 6 | 65% |
| WR → Analyze | 12 | 8 | 60% |
| Whiteboard | 1 | 1 | 50% |
| Players | 209 | 303 | 41% |

(War Room rows re-measured with a team-bearing identity, so they are not
distorted by §1.1's no-team empty states. Lineups is still 81% *and* still
empty — that one is §1, not the identity.)

**Caveat, and it matters:** Lineups, Bracket and Defensive assignments score
81/81/75% partly because they are nearly empty — §1. **Matchup at 68% is the
honest number**, and it is the highest of any view in the app that is actually
full of content.

Players' 41% is on the largest absolute counts anywhere — 209 reads, 303 labels.
It is a big, dense page that explains a good deal of itself.

### 3.1 · Why Matchup is the standard

Rendered:

> **Lincoln Christian Girls 53 — 58% win — MODEL VERDICT — Lincoln Christian
> −2.2 — Coin flip — Washington Girls 50 — 42% win**
>
> ⚖️ Form-weighted 35% — ratings leaned toward current form ·
> Lincoln Christian ▲ +1.8 · Washington ▬ −0.1 (form power vs season)
>
> **Lincoln Christian Girls 53 – 50 Washington Girls** · total 103 · wins **58%**
> of 20,000 sims · **90% of outcomes land between −16 and +20** · Coin flip.

Four things it does that most of the app does not:

1. **It states a verdict and then qualifies it** — "58% win" immediately followed
   by "Coin flip", so the number cannot be over-read.
2. **It publishes an interval, not just a point estimate** — "90% of outcomes
   land between −16 and +20" is the single most honest sentence in the app.
3. **It names its own assumptions inline** — the form weight is on screen with
   both teams' form deltas beside it.
4. **Its empty states teach.** *"No set call has tagged volume on both sides yet
   — tag play types in the Game Tracker for your team and this opponent to light
   up the exploit matrix"* tells a coach exactly what to do to fill the gap.
   Compare §1's *"Track a game for them first"*, which is wrong.

Everything Parts 2 and 4 ask other pages to become, this view already is.

---

## 4 · Smaller notes

* **Players → the pool is nine teams.** The page header reads *"97 players · 9
  teams"* at the default `min_games = 2`. The superlative cards are league-wide
  language over a nine-team sample — the same pool-honesty problem as Part 2 §2.
* **One player owns the board.** Hannah Bond leads OVERALL, OFFENSE, 2WAY,
  VERSATILITY, Finishing, Shot-making and Two-way index — seven of the visible
  cards. True on this book, and a symptom of the pool rather than of the metric,
  but a leaderboard where one name fills seven of eight slots reads as broken
  even when it is right. Worth a "one card per player" rule on the superlative
  strip.
* **`VERSATILITY 99.7`** on a 0-100 index. Either the scale saturates or she is a
  genuine outlier in a 97-player pool; either way a 99.7 needs a sample chip.
* **WR → Analyze is honest about its own weakness** — *"Pearson r = +0.06 across
  204 players (r² = 0.00). Correlation, not causation."* Good.
* **The hexbin's league baseline is computed, not hardcoded** — *"colour = points
  per shot (green above league 0.79, red below)"*, and 0.79 reconciles with the
  band table in Part 2 §1.2. Worth recording as a contrast with the two
  hardcoded captions that finding is about.
* **Whiteboard is effectively unused** — `coach_plays` has one row.

---

## 5 · Ranked

| # | item | § | effort | risk | needs a ruling? |
|---|---|---|---|---|---|
| 1 | **Lineup Creator defaults to the viewer's own team; picker lists only teams with tracked players** | 1 | ½ session | low | no |
| 2 | **`player_label()` — never render a bare jersey number as a name** | 2 | ½ session | low | no |
| 3 | Unnamed players excluded from hero/superlative cards (with placeholder officials, Part 3 §4) | 2 | ½ session | low | yes — the rule |
| 4 | Measure whether `ossaa_sync` carries rosters that could name the 486 | 2 | 1 hour | none | no |
| 5 | `_LOCAL_IDENTITY` resolves a team when the book has exactly one coached team | 1.1 | 1 hour | low | no |
| 6 | "One card per player" on the superlative strip | 4 | 1 hour | low | no |
| 7 | Sample chips on Players' superlative cards | 4 | with Part 3 §5 | low | no |
| 8 | Audit Defensive assignments for the same default-team shape as §1 | 1 | 1 hour | low | no |

**1 and 2 are the two a coach meets first**, and neither needs a ruling.

---

## 6 · What is not finished

* **The War Room's read shares are still partly chrome.** Every view was
  re-measured with a team-bearing identity, but Bracket, Season sim and
  Defensive assignments render most of their substance as widgets and charts,
  which the harness does not capture as text. Their 65–81% is captions and
  empty-state copy, not depth. Matchup's 68% is the only War Room number that is
  measuring content.
* **The Players page was profiled (Part 2 §6) but not reviewed block by block.**
  Its 303 labels were counted, not read.
* **The FAQ rendered 203 reads and was not audited for freshness** — that is the
  glossary/explainer part, which is still running.
* **Whiteboard, Setup, Settings, Input Hub, Game Tracker, Event Editor and OSSAA
  Import have not been swept at all.**
