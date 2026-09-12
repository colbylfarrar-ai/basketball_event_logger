# Overnight run — night of 2026-09-12

Four asks, all four done, on **`main`** and **unpushed**. Both suites green.

| | |
|---|---|
| Commits | `2624ce9` demo launcher · `6f16400` matchup back-in-time + backtest · `b040d9d` Input Hub consolidation · (+ this doc) |
| Suites | `pytest` **481 passed** (was 479) · `tracker/run_all.py` **103 / 0** (was 100 / 0) |
| Verified against | a snapshot pulled from production tonight — 17,350,656 bytes, 13,383 games, 63 tracked, `integrity_check=ok` |
| Source docs | `INPUT_HUB_SCRUB_2026-09-10.md` · `THE_BOOK_2026-09.md` §9 (gating), §12.7, §14 (consolidations), §8.4 (constants) |
| On `main`, not pushed | deploy is yours: `git push` → ssh → `systemctl restart app5-web` |

Both suite counts went **up**, never down. The three new files are new tests, not
re-priced assertions.

---

# 1 · `python run.py` is the offline demo (`2624ce9`)

Type it in the VS Code terminal and the app opens on the frozen production book,
already signed in as you, with no network needed.

```bash
python run.py
```

```
HoopTracks - DEMO
  book     : C:\Users\colby\app5_demo\analytics.db  (17.4 MB)
  signed in: colbyl.farrar@gmail.com
  sign-in  : off (empty secrets)
  network  : offline (the FAQ serves its cached copy)
  re-freeze: python run.py --reset
```

`python run.py --dev` is the old behaviour (working book, real secrets, real
auth) if you need it.

### Three things were in the way, and each was a real failure

**The book.** The dev copy at `%LOCALAPPDATA%\APP5` has been three months behind
production before (`local-book-lags-prod`), and the Store build of Python
virtualizes that directory and hands the shell a *shadow copy*
(`store-python-appdata-virtualization`) — so a demo pointed there can read a
different file than the one you refreshed, silently. The demo book is at
`C:\Users\colby\app5_demo`, a plain home path, pulled by
`tools/pull_prod_snapshot.py`. **It was pulled at 00:52 tonight and is byte-for-
byte production as of 05:48 this morning.**

**The sign-in.** `.streamlit/secrets.toml` carries a real `[auth]` block, so
every page of a plain local run says "Sign in to continue" — and OIDC needs the
network a gym does not have. Demo mode passes `--secrets.files` an empty file
(`.streamlit/secrets.demo.toml`), which *replaces* Streamlit's default search
rather than editing or moving your real secrets.

**Who you are — this is the one that would have bitten you in front of coaches.**
With auth off, the app fell back to an identity whose email is the empty string.
Every ownership read in the app resolves through that email: `coach_teams`, the
co-op flag, per-coach settings. So the open-local app was **not** the product
you see signed in on the website — wider in places (admin tools) and thinner in
others (your own team's gated reads). `APP5_DEMO_AS` now names your `app_users`
row and the identity is rebuilt from it through the same `identity_for` a real
sign-in uses. Verified on screen: Team Dashboard opens on **Adair Girls, 29-3,
26 tracked, #69 of 696, tracked #2 of 22** — your production view.

### Liberties taken

* **`identity_for` was extracted, and the signed-in path now uses it too.** A
  demo that assembled its own identity dict would be a second definition of who
  a coach is, and the first field it forgot would show a product that does not
  exist. One builder, two callers.
* **The demo book is writable.** Demonstrating the Game Tracker means writing
  events. `python run.py --reset` restores it from the pristine copy taken at
  pull time — and deletes the `-wal`/`-shm` pair, because SQLite would otherwise
  replay the session you just discarded over the restored file.
* **The FAQ page got an offline mode.** It is the only page in the app that
  touches the network on a page load, so offline it was the only page that could
  hang: 15 s of `urlopen` timeout in front of a room, to arrive at the cached
  copy it was always going to render. It now skips the call and says "Offline —
  showing the copy synced 2026-07-31" instead of implying the Doc is broken.
  The admin Refresh button is hidden offline rather than offered and broken.

### Worth knowing

* The demo runs fine under the Store `python` (3.13.14) — streamlit 1.58,
  pandas, plotly, numpy, scipy, PIL, matplotlib all present. You do not have to
  remember to use the Python312 path for this.
* A `demo` entry was added to `.claude/launch.json` (port 8514) so the same
  thing can be launched from the IDE.
* **The demo shows tonight's code**, including the new nav in §4. That is what
  you chose; if you want the demo pinned to a version, say so and it becomes a
  separate checkout.

---

# 2 · The matchup predictor, back in time — and priced (`6f16400`)

### Why it could not be the Rankings mechanism

Rankings' week picker is a pure table read: `rating_snapshots` stores a **rank
and a rating** per team per day, which is everything a *board* needs. A
*matchup* needs `AdjNet`, `ClassAdj`, `xPPG`, `xoPPG` and `GP`, and **none of
those are in that table.** So the predictor's version re-solves: both rating
engines already accept a `game_ids` filter, so handing them the games finished
on or before a date rebuilds the board that existed then and the predictor eats
it unchanged. That is the same move `rating_history.backfill_weekly` makes to
recover the snapshot table — held in memory for one question instead of written
to a table. One solve, ~0.2 s.

**On screen:** War Room → Matchup → "🕘 As of". Pick any date the league played
on. The whole view follows it — verdict, win probability, margin breakdown, the
20,000-game Monte-Carlo, and the printable one-pager.

Two things are deliberately *not* rewound, and the screen says so: the
auto-scout tells and the exploit/game-plan matrix are season-wide tracked reads
with no date filter, so leaving them up would have described games that had not
been played yet, sitting under a verdict that was careful not to. The tale of
the tape **is** handed the board, so it rewinds on its own.

### The backtest — the part that sells coaches

"How accurate is this predictor?" at the bottom of the Matchup view. Walk-
forward: every finished game re-predicted from the board solved over the games
finished **strictly before that day** — the whole day is held out, not just the
one game, so a Tuesday result cannot leak into a Tuesday prediction. Forfeits
excluded. One solve per game *date* (~100 a season), ~20 s, behind a button,
cached 30 min.

Measured tonight on the production book with the **deployed** constants:

| | girls 2025-2026 | boys 2025-2026 |
|---|---|---|
| games scored (walk-forward) | 5,048 | 5,092 |
| picked the winner | **85.3 %** | 81.9 % |
| typical miss (MAE) | 9.9 pts | 10.5 pts |
| RMSE of the margin error | 12.61 | 13.43 |
| Brier | .1045 → **skill .589** vs a coin flip | .1281 → skill .498 |
| home lean (mean signed error) | +1.78 | +1.67 |

Calibration, girls: said 55.0 → got 56.9 · said 64.9 → got 61.7 · said 75.2 →
got 74.2 · said 85.3 → got 83.5 · said 97.9 → got 97.0. **Inside three points in
every band.** Boys are the same shape but slightly overconfident at the top
(97.5 → 94.8).

### Two constants this prices — REPORTED, NOT CHANGED

Per `recal-round2-2026-07-18`, a constant does not move without its own gate. I
measured and left them alone.

* **`predictor.PREGAME_SD = 11.0` is too tight.** The RMSE of the margin error
  *is* the pre-game SD the win-probability model assumes, and it measures
  **12.61 (F) / 13.43 (M)**. That is the source of the residual overconfidence
  in the top probability bin. It is also the number the FAQ quotes as "about 11
  points" — see §3.
* **`team_ratings.DEFAULT_HCA = 3.0` is about 1.5 too big**, on a book whose raw
  home margin is +3.31. The model over-favours the home side by +1.78.

And a data problem underneath the second one: **`games.neutral` is set on 3 rows
of a 13,383-game book.** So the home bump is granted on ~1,500 playoff games
played on nobody's floor. The by-game-type split is in the panel precisely so
this reading is available — girls playoff bias **2.72** against regular-season
**1.61**. Two candidate fixes, both yours to call: flag neutral on
playoff/tournament games, or lower the constant. They are not the same fix and
doing both would overcorrect.

### One finding about measurement itself

`helpers/model_constants.apply()` runs at app startup and folds adopted
overrides onto the engine globals (`DEFAULT_REG` is adopted at 0.15). A bare
script that skips it measures a model **nobody is running** — it moved the
girls' hit rate 84.7 → 85.3 % and the RMSE 12.74 → 12.61. That is documented at
the top of `helpers/backtest.py`; call `apply()` first in any future script.

---

# 3 · FAQ — ten additions and revisions, drafted (`docs/FAQ_ADDITIONS_2026-09-12.md`)

**The app cannot write these and neither can I.** `pages/15_FAQ.py` renders the
plain-text export of your Google Doc; the Doc is the source. So the file is
paste-ready text in the Doc's voice, each item marked ADD or REVISE with the
section it belongs under.

The one that matters most is a **REVISE**: the Doc says "the honest uncertainty
band on a single game is about 11 points". That was the constant, not a
measurement. It is 12.6 / 13.4, and now the app can show its work. Two more
additions cover the back-in-time picker and the accuracy panel; the rest cover
the gate change and the new nav (§4), the empty-current-season landing, forfeits,
the neutral checkbox, and four new troubleshooting entries for messages the app
can now show you.

Also checked: the Doc as of tonight is 38,197 characters and **matches what
production is serving exactly**. Prod's `faq:fetched_at` reads 2026-07-31, which
is not a sync failure — `get_faq` only runs when somebody opens the FAQ page,
and nobody has since then.

---

# 4 · Input Hub consolidation — all five steps (`b040d9d`)

## The new nav (you asked for this explicitly)

```
Analyze        Team Dashboard · Rankings · Players · Hall of Fame
Build          Input Hub · Game Tracker · Box Score Entry · Event Editor · Schedule
               (· OSSAA Import, admin only)
Plan & scout   War Room · Whiteboard · Officials
Settings & Help  Settings · FAQ
```

**Changed:** "Roster & District" is **gone**. "Box Score Entry" is **new**, and
sits directly under the Game Tracker. Nothing else moved.

Inside the Input Hub, the sections are now **Teams · Players · Games ·
Officials · Season Archive** — "Team Schedule" is a point of view *inside* Games
(League / One team), not a section.

## Step 1 — the gate, which was the real reason to do any of this

`grep ENT.` on `1_Input_Hub.py` returned **nothing**. No entitlement import at
all. Its only gate queued *deletes* for admin approval, so **every UPDATE and
INSERT was league-wide open**: any signed-in coach could rename any team, edit
any player, or rewrite any game's score. Roster & District gated the *same*
writes hard — so one `players` row was scoped by column, with `grad_year`
protected on one page and open on the other. Ownership was decided by which page
you opened.

`_team_scope` / `_game_scope` are ported from that page **verbatim** so the two
cannot drift. The split of how they are applied is a liberty, and a considered
one:

* **Reads** default to your own teams, with an explicit "Show the whole league"
  switch. A coach still has to *see* the league to enter an opponent.
* **Writes** are gated with no switch, per row. An out-of-scope row is refused
  with a sentence naming it, and `apply_delta`'s per-row try/except means the
  rest of a pasted batch still saves.
* **Inserts stay open.** Creating a team, a game, a player or an official is how
  a league gets entered; closing it would break the only path a coach has to add
  an opponent. Editing somebody else's *existing* row is the hole this closes.

Admin is unchanged and league-wide, because somebody has to be able to clean up.

## Step 2 — the weaker copy

Team Schedule's insert had **no duplicate-matchup check and no season picker**,
so adding a game there could double-book a matchup the league grid would have
refused — and `ux_games_matchup` is partial (`tracked_by=''`), so the index does
not backstop it (`games-matchup-index-is-partial`). Both points of view now write
through one `_ins_game` / `_upd_game`, so the dup check, the season stamp, the
ownership guard and the tracked-score guard are each defined **once**.

## Step 3 — the three thin tabs, and the one that is not thin

Three of Roster & District's four tabs each edited **one column** of a row the
Input Hub was already editing:

| moved | to |
|---|---|
| player `position`, `availability` | Input Hub → Players grid |
| team `district` (+ its search box) | Input Hub → Teams grid |
| game `game_type` (+ "apply to all shown") | Input Hub → Games grid |

`pages/11_Setup.py` is **deleted**, and six stale pointers to "the Setup page" /
"Roster & District" across Rankings, the War Room, the dashboard and
`manual_box` now name where the control actually lives.

**Box Score Entry did not fold in**, per the scrub. It is a complete manual
box-score app with a MaxPreps importer, and it is the *peer* of the Game Tracker
— the other way a game gets its numbers — so it is its own page, carrying the
ownership gate it already had. A coach with no team assigned is stopped there
with a sentence, because a box score sets a game's final score for the whole
league.

## Step 4 — two editors, one table

Team Schedule is a POV toggle inside Games now. They used to invalidate each
other's cached frame because they knew they collided; there is one frame and one
save path.

## Step 5 — the dead table

The Season Archive's Schedule tab read `schedule`, whose only remaining write
anywhere is a season-label re-stamp on rows that already exist — **no INSERT
path exists**. Confirmed on the production snapshot, not just the local copy:
`schedule` = **30 rows**, all one season, against **13,383** in `games`. Both
reads (the tab and the season-label list that fed the picker) now go to `games`,
with a team search and a 60-team cap so a 1,448-team book does not render 1,448
expanders.

## Tests

`tracker/test_input_hub_scope.py` — **30 checks**, rendered end to end as an
admin and as a plain coach, because the gate is page-level and a unit test would
be testing a copy of the helpers. It pins: every section renders for both roles,
both game POVs render, a coach's grids and pickers hold only his own rows, admin
still sees the league, each absorbed column is actually present, `schedule` is
no longer read, `11_Setup.py` is gone and the nav does not point at it, and a
coach with no team is stopped on Box Score Entry.

---

# What I did NOT do

* **Did not change `PREGAME_SD`, `DEFAULT_HCA`, or any model constant.** Measured
  and reported only (§2). Those need your gate.
* **Did not backfill `games.neutral`.** It is a data edit across ~1,500 playoff
  rows and the right fix depends on which of the two corrections you want.
* **Did not push or deploy.** Everything is committed on `main`, unpushed.
* **Did not touch the Event Editor.** The scrub calls it a separate job (its
  namesake grid sits ~380 lines down under three expanders, and the quarter/type
  filters govern only three of its five tools). Still open.
* **Did not do THE BOOK §12.7** (the schedule's at-the-time opponent rank, and
  quality wins on the Hall of Fame). `resume.py` makes both nearly free and
  they are still not done — the closest adjacent win to tonight's work.

# Three things to look at first in the morning

1. `python run.py` — confirm the demo is the app you expect to show.
2. War Room → Matchup → "How accurate is this predictor?" → **Measure it**.
3. `docs/FAQ_ADDITIONS_2026-09-12.md`, then paste into the Doc.
