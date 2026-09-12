You are working unattended overnight on the HoopTracks basketball analytics app
(Streamlit + SQLite) at C:\Users\colby\basketball_event_logger\APP5.0. The founder
is asleep and CANNOT answer questions. If a decision is genuinely ambiguous, pick
the conservative option, WRITE DOWN the assumption, and keep going — never stop
and wait, and never guess at something destructive.

## READ FIRST, IN THIS ORDER

  APP5.0/docs/THE_BOOK_2026-09.md                  <- the governing document; go
                                                      straight to §21 (Phase 0/1)
  APP5.0/docs/FREEZE_PUNCHLIST_2026-09-09.md       <- what is actually left
  APP5.0/docs/SCOUT_PROFILE_PRINT_2026-09-11.md    <- last night's run; its
                                                      "Not done, and why" section
                                                      is TASK 3 and TASK 4 below

## THE CONSTRAINT THAT DECIDES EVERY TRADE-OFF

**Coaches are trained in OCTOBER, once.** September is not "improve the app", it
is "remove every reason to open a page in anger between November and March". From
October there are five readers, not one, and none of them know the pools. A wrong
number costs more than a missing one. Every new metric costs forever — prefer
surfacing an engine that already exists over writing one.

The code side of THE BOOK is DONE (verified against production 2026-09-09). What
remains is ops (founder sudo — not yours) and the items below.

## STATE

Start from `main`: clean, **10 commits ahead of origin**, both suites green.
Create ONE branch `overnight-2026-09-12` and commit to it. **DO NOT merge to
main** — the founder reviews in the morning.

Baseline you must not regress:
    pytest          476 passed   (~30 s)
    tracker/run_all  99 passed, 0 failed   (~12 min)

## ENVIRONMENT — get these wrong and you will waste hours

* **Use the pinned interpreter for everything.** The shell's bare `python` sees a
  Store-virtualized shadow copy of AppData and reads the WRONG database:
      C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe
* **Prefix every command with `PYTHONIOENCODING=utf-8`.** This codebase's output
  is full of em-dashes and box-drawing characters; without it the console raises
  UnicodeEncodeError mid-run and you lose the result, not just the formatting.
* **Two books, and they are different.**
  - `%LOCALAPPDATA%\APP5\analytics.db` — the local dev book. `run_all` is priced
    to THIS one and only reproduces 99/0 here. NEVER write to it.
  - `~/app5_prod/analytics.db` — a read-only production snapshot, 63 tracked
    games, already on disk. Point AppTest harnesses at it via
    `os.environ["APP5_DATA_DIR"] = os.path.expanduser("~/app5_prod")`.
  Do NOT refresh the snapshot (it needs ssh — banned below). Do NOT export
  APP5_DATA_DIR when running `run_all.py`; its modules build their own temp DBs
  and the export poisons them.
* **The season trap.** `SEAS.ACTIVE` is "Current" and holds 23 games with ZERO
  tracked. All real data is under the "2025-2026" label. Any harness must seed
  `ta_season = "2025-2026"` or it renders a healthy-looking empty state and
  proves nothing.
* **AppTest harness pattern** (a secrets-free cwd bypasses auth):
      os.chdir(<a dir with no secrets.toml>)
      at = AppTest.from_file(page, default_timeout=1800)
      at.session_state["ta_team"] = 1
      at.session_state["ta_season"] = "2025-2026"
      at.session_state["td_view"] = "Scout"        # or "Roster" + td_roster_view
      at.run(); assert not at.exception
* **AppTest cannot replay some of this page's multiselects** — clicking the
  "Prepare" download button raises inside the harness. To capture a built
  document, monkeypatch instead:
      import helpers.ui as UI
      CAUGHT = {}
      UI.pdf_or_html_download = lambda label, doc, base, *, key, fp=None: (
          CAUGHT.__setitem__(key, doc()) if callable(doc) else None)
      UI.prepared_doc = lambda key, fp=None: None
* `run_all` buffers; redirect to a file and poll rather than waiting on a pipe.
* Timing runs are only trustworthy with NOTHING else running.

## DO NOT DO (hard boundaries)

1. DO NOT push, deploy, ssh, or touch the droplet in any way.
2. DO NOT merge to main.
3. DO NOT run `tools/repair_book.py --apply` or otherwise modify either book.
4. DO NOT add the UNIQUE index on `games` — blocked on the repair AND on a
   founder ruling about same-day rematches.
5. DO NOT change any model constant without the measured gate the house rules
   require: split-half stability stepped up by Spearman-Brown, plus a second
   independent column agreeing in sign. A measurement only counts if it lands in
   `reliability.MEASURED`.
6. DO NOT ship a verdict, badge or threshold on an unmeasured quantity. If you
   cannot measure repeatability, render the number and skip the sentence.
7. DO NOT install systemd timers or anything needing sudo — founder-only.
8. DO NOT re-price `test_offline_readiness.py` / `test_ratings_depth_smoke.py`.
   The freeze punch-list lists them as mis-priced; they are GREEN on the current
   local book (8 M / 35 F, which is what they assert). That item is closed.

## WORK, IN THIS ORDER

### TASK 1 (the big one) — October instrumentation. THE BOOK §21 Phase 1.

THE BOOK wants three counters **before the training session, which happens
exactly once**, and `grep page_view` returns nothing. None of the three exist.
Without them, October produces no evidence about what five new coaches actually
did, and there is no second chance to collect it.

Build them as ONE small Streamlit-free engine — `helpers/telemetry.py` — plus
call sites. Append-only, one table, no blobs ([[db-stays-small]] applies: compact
rows, cap retention).

* **1a — page views.** Which page, which coach (hashed or by email — match how
  `app_settings` scopes per-coach, `u:<email>:`), which day. One row per
  page-view, or a daily counter row you increment; pick the cheaper one on a
  1 vCPU / 2 GB droplet and say which you picked and why. The write must be
  cheap enough to sit on every page load without being felt — the box is CPU-
  bound and a global cache-clear on live-game writes is already the constraint.
* **1b — empty-state hits.** `helpers/ui.empty_state()` is the single funnel for
  "this surface has nothing to show". Instrument it there, once, and you get
  every dead end in the app for free. Record WHICH empty state fired. This is the
  highest-value of the three: it is a direct list of the reasons a coach opens a
  page in anger.
* **1c — co-op toggle.** Every change to the sharing setting, with the old and
  new value. The business is the Coaches' Co-op and production currently has six
  paid accounts and ONE sharing team; October is when that number moves or does
  not, and nothing currently records it moving.

Then a **read surface**: a small admin-only block (Settings, beside the existing
"Coaches online & server capacity" glance) showing the last 30 days. The founder
looks at Settings once a week by design — put it where they already look, not on
a new page.

Guard rails: every write wrapped so a telemetry failure can NEVER take a page
down (the house `except Exception: pass` convention around non-essential reads,
but log at WARNING so a broken counter is not invisible). Add a kill switch in
`app_settings` so it can be turned off without a deploy.

### TASK 2 — four sites that re-widen an entitlement-scoped id set.

Freeze punch-list item 3, verified still live tonight. The pattern
`tuple(...) or None` turns an EMPTY visible-game set into `None`, and `None` means
UNRESTRICTED downstream. Same class as [[empty-gids-means-everything]].

    helpers/dashboard/insights_team_read.py:58     gids = tuple(...) or None
    helpers/dashboard/insights_tab.py:631          tuple(_tids or ()) or None
    helpers/dashboard/insights_tab.py:633          season_gp=tuple(...) or None
    helpers/dashboard/insights_tab.py:640          league_gids=tuple(...) or None
    pages/6_Team_Dashboard.py:6155  (_ins_scheme_sit)   ... or None

Their own sibling `_ins_quarter_read` (`pages/6_Team_Dashboard.py:6168`) guards
correctly — `if not _gids: return []`. Copy that shape. Latent, not bleeding:
reaching it needs `has_tracked` True AND the visible set empty, which could not
be constructed against the prod book — so **write the test that constructs it**
(`tracker/test_read_filter_empty_scope.py` is the existing home and already fails
by design; extend it) rather than only fixing the lines.

### TASK 3 — the Player Profile's game-window control. Refused last night, spec'd.

`PLAYER_PROFILE_SCRUB_2026-09-09.md` build step 6. The card cannot answer "last
five games only" at all. It was refused last night for a specific reason, and the
reason IS the design:

> Every cached read on the card takes `game_ids`. Narrowing that pool narrows the
> **league percentile pools** with it — and "78th percentile among everyone's last
> five games" is a different and much stranger claim than the bars make today.

So the change is **two scopes, not one**:

* `_gp` (the ranking pool) stays the season pool. Percentile rails, `_pctile_n`,
  `pctile_bar`, rank tables, league bars — all keep ranking against the season.
* a NEW `_window` scopes only the PER-PLAYER reads: the game log, the shot map,
  the per-game boxes, the form block, the foul/FT detail, the matchup reads.

Ship the control as `_UI.seg` in the fold: **Season · Last 10 · Last 5**. When
the window is not "Season", every block ranked against the season pool must SAY
so on screen — a one-line caption, not silence. Honour
[[pctile-pool-convention]]: the pool a number was ranked over is part of the
number.

The card is now six lazy `_seg` sections (`CARD_SECTIONS`); the window selector
lives above them with the fold and the verdict. Verify by rendering every section
standalone at each window setting — a cross-section leak is a NameError for
exactly one section, which is why the AST sweep below matters.

### TASK 4 — Charts → Scout, Tier A only. SCOUT_TAB_ROADMAP Part 10.

Screen-first, and **print only what the coach promotes**: the sheet now has
separate screen/paper flags (`scout_hidden_screen` / `scout_hidden_print`), so new
depth defaults to screen and costs zero printed pages. That is the whole point of
the split — use it.

In priority order:

1. **Defense → opponent shot profile, "where they force shots."** Aimed at them,
   this is *where they will force US to shoot* — the offensive game plan in one
   image. Best single chart on that tab for a scout.
2. **Winning Formula — `team_formula` / `verdict_lines` / `suppressors`.** "What
   has to be true for them to win" inverts cleanly into "what to take away", and
   `suppressors` is already written as coach-speak.
3. **Offense → Shot Lab, shot-making vs shot quality.** Separates "they get good
   looks" from "they make tough shots" — the contest-or-concede decision, which
   Scout cannot currently answer.
4. **Trends → vs top-half / bottom-half.** Good-team beater or stat-padder, one
   row and one line of prose.

Each goes through `helpers/dashboard/scout_deep.py`, which exists and whose rule
is: **it computes nothing.** It calls an existing engine with the opponent's id
and the opponent's read-filtered game ids and writes the sentence for the other
direction. Do not add a metric. If a port needs a new number, skip it and say so.

**Quarters guardrail, if you touch anything quarter-shaped:** only TEMPO was
measured to repeat across quarters (split-half ≈ .60). Quarter shooting and
quarter ball-security did NOT clear reliability and were refused. Ship the tempo
and scoring-margin lines; do NOT ship "they shoot 27% in Q2". That is noise
dressed as a scouting key and it is the kind of line that costs a coach a game.

### IF THERE IS TIME — free before breakfast

* `insights_deck._next_game` lacks the two guards its `team_card` twin has.
* Two hardcoded shot-depth captions disagree with each other AND with the engine.
* `coverage.py` does not gate `turnover_type`.
* Confirm `tools/auto_season_rollover.py` relabels the 23 `season='Current'`
  games (dates 2026-12-08 → 2027-02-16, 0 tracked). Run it DRY against a copy of
  the prod snapshot only. If it does not relabel them, November opens on an empty
  schedule — write that up, do not fix it blind.

## BEFORE EACH STRUCTURAL CHANGE

If you convert anything linear into lazy `_seg` sections, **AST-sweep the
proposed boundaries first**. A silent cross-section variable leak becomes a
NameError for exactly the one coach who opens the wrong section. Walk the
function, collect Name-Store per proposed section and Name-Load per section, and
report every name assigned in an earlier section and read in a later one — then
hoist those into the outer scope. Watch `import` statements specifically: an
`import pandas as pd` inside one section used by three is the leak an AST walk
over `ast.Name` alone will MISS, because imports bind via `ast.alias`.

## FINISHING

* Commit in coherent chunks with real messages — say what was wrong and why the
  fix is the fix, not what you typed.
* Run BOTH suites after each chunk. Any drop from 476 / 99-0 is yours.
* Write `APP5.0/docs/OVERNIGHT_2026-09-12.md`: what shipped, what you refused and
  why, every assumption you wrote down, and measured before/after numbers for
  anything you claim is faster or smaller.
* Leave the branch unmerged and unpushed.
