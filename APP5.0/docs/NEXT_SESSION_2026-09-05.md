# Next session — queued from the 2026-09-05 batch

Branch `batch-2026-09-05` is finished and parked: 8 commits, unpushed, to be
pushed with everything else at push time. Do not build on it — start a new
branch off `main`.

---

## HEADLINE: rework the officials rating

The founder's ask: *"there is a ranking, but nothing crazy. I want to put a
finger on the scale for what most coaches consider good and bad."*

### The problem to lead with

`helpers/officials.py:566` — the whole rating today:

```python
_RATING_WEIGHTS = [
    ("fpg",     -0.30),   # fewer fouls/game is better
    ("leverage", 0.25),   # the games' stakes
    ("ppp",      0.20),   # scoring environment
    ("pace",     0.15),   # possessions/game
    ("clutch",   0.10),   # willingness to make the late call
]
```

**60% of the weight is a property of the GAMES, not the referee.** `leverage`,
`ppp` and `pace` all describe the games a ref happened to be assigned — the
scoring environment and tempo of someone else's basketball. Only `fpg` (30%) and
`clutch` (10%) describe anything the official did.

One caveat worth holding: `leverage` is not pure noise, because associations
assign their best crews to marquee games, so it is a weak proxy for peer
evaluation. `ppp` and `pace` have no such defence — a ref who works two
run-and-gun teams rates above an identical ref who works two grinders.

That is the finger on the scale to remove before adding one.

### What is already computed and unused

Every one of these is on the row today, costing nothing extra
(`official_overview`, `helpers/officials.py:184-193, 411-430`):

| field | meaning | why a coach cares |
|---|---|---|
| `FPG_std` | game-to-game spread of this ref's foul count | **consistency** — "you know what you're getting" is the #1 thing coaches say about a good ref |
| `ha_diff` | home fouls − away fouls | **home cooking** — the #1 thing they say about a bad one |
| `li_call_ratio` | high-leverage CALL share ÷ high-leverage MOMENT share | does the whistle change when it matters, or stay the same? |
| `avg_call_li` | mean leverage of the moments they blew the whistle | |
| `foulouts` / `foulout_impact` | players fouled out, weighted by their scoring share × time lost | **did the crew take a star off the floor** |
| `foul_share` | this ref's share of the calls in their own games | is one member of the crew doing all the whistling? |
| `q1..q4` | foul distribution by quarter | do they swallow the whistle late, or call it the same all night? |
| `strategic_calls` | intentional clock-stop fouls (already excluded from `fouls`) | |
| `pt_bias` / `def_bias` | which sets / defenses they call tight | new this batch |

### Suggested shape (to argue about, not to implement blind)

Two axes a coach actually names, rather than one blended number:

- **Predictability** — `FPG_std`, `q1..q4` flatness, `li_call_ratio` near 1.0.
  "Same game all night."
- **Fairness** — `|ha_diff|` near zero, `foul_share` near 1/3, low
  `foulout_impact`.

Then keep `FPG` as a *descriptor* (tight vs let-them-play) rather than a
goodness axis — a tight crew is not a bad crew, it is a different game plan, and
coding it `-0.30` bakes in "fewer fouls = better ref" which is a preference, not
a fact.

### Before touching a weight

- **Sample.** `RATING_MIN_GAMES = 3` today; the DB audit put the shippable
  threshold at ~15-20 games. At three games these numbers are noise. Decide
  whether the rework ships gated (fewer refs, honest) or labelled.
- **Gate the change.** Constants get measured before they move — see the tempo
  work in the last batch for the pattern: split the sample, check the metric is
  stable across halves, and price the read off a second independent column
  before believing it.

### Also fold in here

**N3** — the two bias tables (`pages/8_Officials.py`) list any ref with two calls
on a tag, ungated. Same sample problem, same fix, same session.

---

## QUEUED, in build order

### 1. Cross-state badge collision (the surviving half of N1)
`officials.official_id` is `INTEGER NOT NULL UNIQUE` — globally unique — with
`officials.state` sitting beside it unused. All 70 officials are `OK` today, but
**teams already span 23 states** (1,146 OK, 94 TX, 85 AR, 57 KS, 33 MO, …), so
the first out-of-state crew can collide.

Silent and bad when it happens: `quick_add_official` (`tracker/api.py`) upserts
`ON CONFLICT(official_id) DO UPDATE SET archived=0` and returns the STORED name,
so an Arkansas #1234 entered while Oklahoma #1234 exists un-archives the Oklahoma
ref, hands back the wrong name, and pools two careers into one record.

Fix: `UNIQUE(official_id, state)`, upsert on the pair, default the state from the
game's teams instead of the `'OK'` column default. Migration + a backfill that
stamps existing rows `OK`.

### 2. Offline quick-add (N2)
`quickAddOfficial` and quick-add player bail with "Needs connection" while every
other write in the tracker is queued and flushed. A gym with no signal is the
normal case. Queue them like events; reconcile server ids on flush.

### 3. iPad Mode proper (N4)
See the batch doc for the full note. Short version: collapse the lineup and
tracker into one composed view at tablet width — persistent left rail (roster,
on-court five, subs), court centre, flow right, edit log as a slide-over.
**Keep `S.screen` exactly as it is** and change only what each screen renders:
`init()` restores a mid-game session by branching on `st.screen`, and that path
is what saves a game when iOS reclaims the tab. Composition change, not a
navigation change.

### 4. `stats._team_game_ids` rollover trap (N5)
`stats.py:2085` hardcodes `season='Current'`, empty for the first weeks of a
season, and it is the default game pool for `rotation_plan.star_coverage` and
`foul_prone` — a no-arg call reports a team has no key players. Nothing broken
today because every caller passes `game_ids`. Give it the fallback
`seasons.tracked_default_season_sql()` already implements.
`rotation_plan._tracked_games_in_season_of` is the pattern to copy.

---

## TWO THINGS THAT ARE NOT CODE

### A data slip in the live book
`game_events.id = 7101` — game 14123 (2026-02-06), Q1 0:01 — has
`primary_player_id = secondary_player_id = 509` ("#21"). A charge where the same
player drew it and committed it. Event `7100` is a foul at the same timestamp
with 509/498, so it looks like a double-log that took one player into both slots.
This is what fails `test_charges.py::test_real_book_encoding` on `main`. **Fix it
in the Event Editor** — one row, one click. Left untouched deliberately.

### The pinned interpreter is missing declared dependencies
`%LOCALAPPDATA%\\Programs\\Python\\Python312` was missing `uvicorn`, `xhtml2pdf`
and **`pytest`**. Because `run_all.py` deliberately skips the ~38 pytest modules
(see `conftest.py`), a green `run_all` was covering roughly half the suite.
Installed during the last session, but worth a `pip install -r requirements.txt`
against that interpreter, and worth remembering that **`run_all` green is not the
suite green** — both halves have to run.

---

## STATE AT HANDOFF

- `run_all.py`: 95 / 95.
- `pytest tracker/`: 241 / 242 — the one failure is the data slip above, and it
  fails on `main` too.
- Branch `batch-2026-09-05`: 8 commits, unpushed, finished. Start new work from
  `main`.
