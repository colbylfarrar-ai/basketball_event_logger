# Next session context — written 2026-07-25

Hand-off from the session that built Part 1 (shot depth) and Part 2 slice 1
(front-office frame). Read `docs/COACH_ROADMAP_2026-07-25.md` for the full map —
its §BL and §BL2 build logs carry the measurements, and ten of its original
claims are marked `CORRECTED` inline. **Do not trust an uncorrected line in that
doc without checking it against the code first.** Ten were wrong last session.

---

## Working protocol (unchanged, follow it)

BEFORE a part: interview one question at a time, multiple choice preferred, wait
for each answer, until you can state the vision back in a paragraph the coach
agrees with. Cover: what a coach can DO after this ships; the one sentence it
lets the app say; where it lives and what it displaces; what "done" is and
what's out of scope; how it degrades on a thin sample.

DURING: build in the stated order. Show numbers from the real DB as you go, not
just code. **If the data contradicts the doc, say so immediately and stop.**

AFTER: interview again — does it say what a coach needs in coach language, what's
missing now that it's built, what changes for the parts ahead, what gets cut.
Update the roadmap doc, commit, then start the next part's BEFORE interview.

## Standing constraints

- **Density, not simplicity. More information, always.** Never propose removing
  information — only giving it shape.
- **No page is removed, no depth consolidated away.** All 16 pages mean
  something. Reorganize, never delete.
- **`entitlement.tracked_gate` is what the whole app is built on.** Every new
  surface READS it. Reciprocal: a co-op member sees another team's
  current-season depth only when BOTH sides are pooled. Past seasons are open to
  everyone, across gender. Free = box score; Paid = own team; navigation is never
  gated, only depth.
- **Measure before shipping a verdict.** Split-half reliability first; the gate
  number comes from the measurement, not from a guess.
- Prod is 1 vCPU / 2 GB, no swap. Prefer one event pass reused by several
  sections over N passes.

## Environment

- Live DB: `C:\Users\colby\AppData\Local\APP5\analytics.db`, open `mode=ro`.
  The repo's `APP5.0/analytics.db` is a **0-byte stub**.
- Use `C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe` —
  shell `python` is the Store build and sees a virtualized shadow of AppData.
- Headless page checks: `AppTest.from_file` from a cwd with **no**
  `.streamlit/secrets.toml`, and patch `helpers.auth` (auth_enabled /
  require_login / current_user), `helpers.entitlement` (has_paid_plan /
  viewer_is_league_wide), **and `helpers.ui.gender_radio`** — without the last
  one, two different teams render byte-identical pages and the smoke proves
  nothing. Seed `ta_team` / `ta_season='2025-2026'` / `td_view`.
- **`S.fetch_events([])` returns the ENTIRE database.** An empty game-id list
  means "everything", not "nothing", and `PT._tracked_game_ids(gender)` returns
  `[]` because the active season is an empty rollover. Guard explicitly.
- `SEAS.ACTIVE` is the sentinel string `'Current'`, not a year label.
- All 43 tracked games live under season label **`2025-2026`** (35 F / 8 M).

## Preview (asked for explicitly)

**Launch a local preview at the start of the session and keep it up while doing
UI work** — the coach wants to look at it while you build. `.claude/launch.json`
already has `app` (port 8511) and `app-noauth`. Use `preview_start`, never Bash.

---

## Done last session — 7 commits, none pushed

| commit | what |
|---|---|
| `041cebf` | `helpers/shot_kinds.py` + 51 checks — rim/floater/mid/corner3/abovebreak3 |
| `631864d` | Shot-depth block on Charts, verdict card on Insights |
| `6b336c7` | Defense × depth cross-tab |
| `7394522` | Roadmap: 7 claims corrected, §BL build log |
| `6bc25b3` | **xFG reprice** — `stats._sq_loc`, kind instead of zone, 11 call sites |
| `574cf53` | Roadmap: reprice recorded |
| `9687aaf` | **Part 2 slice 1** — landing swap, labeled season fallback, War Room banner, nav section |
| `fa44b01` | Roadmap: Part 2 premises corrected, §BL2 |

Key measurements to carry forward: player floater **share** r=.636 (SB .778);
player floater **FG%** r=.078 — noise. Shares survive thin samples, rates do
not. Out-of-sample, KIND beat zone (log loss .624 vs .639) and **kind+zone
together was worse than either** (.667) — 3,246 shots cannot fill both axes.

---

# BUILD ORDER FOR THIS SESSION

Decisions below came from the AFTER interview on 2026-07-25. They are settled —
build them, don't re-litigate.

## 1. Re-cut the shot bands and re-measure  ← FIRST, gates everything shot-related

The coach proposed **0–4 / 4–19 / 19–23 / 23+** instead of the current
rim / floater / mid / corner3 / abovebreak3.

This is well motivated by our own data: the floater band (0.578 PPS) and the
midrange (0.550) measured as *the same shot*, so merging them into one 4–19 band
follows the measurement rather than fighting it. It also splits 3s by DEPTH
(at-the-arc vs deep, NFHS arc = 19.75) instead of by angle.

Required before adopting:
- Re-run the league table on the live book under the new bands.
- Re-run **split-half** (odd/even games, Spearman-Brown) for share AND rate, at
  player and team level. The open question the coach raised is whether coarser
  bands give enough n per cell that **player-level rates finally clear the gate**
  — that is the whole reason to consider this cut (answers A2 and A3 together).
- Re-run the **out-of-sample** comparison (log loss / Brier) against the current
  5-kind taxonomy before changing `_sq_loc`.
- If player rates clear reliability under the new bands, surface them; if they
  still don't, keep withholding and say why.

Scripts to adapt live in the scratchpad pattern from last session — re-derive,
don't trust the old numbers, the bands are different.

## 2. Show BOTH zone and kind; push kind on ratings and impact

Coach: *"show both where possible, let the coach make their own decisions, but
push kind over zone on ratings and impact."*

- Displays: surface zone AND kind side by side rather than replacing.
- Ratings / impact paths: kind wins. That includes repricing
  **`stats._bucket_make_rate`** (`stats.py:1149`), the second shot-quality model
  deliberately left on zone last session. Measure it out-of-sample first, same
  as `shot_quality_rates` — it has its own fine/coarse fallback so it is not a
  copy-paste of the last change.

## 3. Normalize the defense cross-tab against league average

Coach on the scramble finding: *"scramble will have high rim% by nature and a
higher PPS overall, but regulating every play type against the league average
could solve it."* Show each scheme's kind mix as a **delta vs the league's mix
for that scheme**, not raw share, so "broken play concedes rim" stops
masquerading as a finding.

## 4. Banner + UI polish (small, do alongside)

- **Remove MOV** from the banner.
- Season-fallback notice: **first visit only** (per session), not every load.
- Nav section rename: **"Settings & Help"** (capital H).

## 5. Audit every read page's season picker

War Room had no `index=` and opened on the empty rollover season, rendering
blank over a full database. Coach confirmed: audit them all. Fix with
`SEAS.default_read_season_index(_season_opts)`. Write pages (Input Hub, Game
Tracker) must **not** get this — a new game defaults to the active season.

## 6. News feed (§2.3) + retroactive weekly rating snapshots

Coach picked the news feed over the player card, with a specific requirement:
**wire `rating_snapshots` so it works retroactively on 2025-2026** — the table
exists and has **0 rows**. Reconstruct weekly snapshots by recomputing ratings
as-of each week from games up to that date, then write them. Weekly cadence.

That unlocks the feed's Power-delta lines (`Power 66.9 → 68.2 (+1.3)`) on a
season that has already been played, instead of the feed being empty until
someone accumulates a year of history.

Inputs that already exist: `public_feed.py`, `social_cards.py`, `awards.py`,
`rating_history.py`, `postgame.py`.

## 7. Whiteboard team scoping (Schedule is OUT)

Coach: *"plays belong to teams and coaches I guess, just tie to teams and add a
disclaimer. add whiteboard, dont do schedule."*

`coach_plays` has `coach_email` and **no `team_id`** — needs the column. Tie
plays to a team, keep the coach association, show a disclaimer about the shared
scope. Then the banner can ride Whiteboard. **Do not** scope Schedule; it stays
the league calendar.

## 8. `foul_clock` (§1.1 remainder)

Coach: *"foul clock is the big one, keep logging crew foul rate for later."*
Build the time-of-Nth-foul distribution; it is descriptive and honest at any
sample and it gives the shipped `bench_cost` engine the context it lacks.

**`crew_foul_rate`: accumulate, don't surface.** Keep the data path so the
sample grows, hold the verdict. Expect it to fail split-half — it is a rate at a
thinner sample than floater FG%, which failed at r=.078. `helpers/foul_trouble.py`
already exists (bench cost, team foul-state net, gated verdict); read its
docstring first, it records two traps.

## 9. Deploy Sunday

Coach: *"must keep stacking and then deploy on Sunday."* **56 commits unpushed.**
Do not push mid-week. Deploy flow: push → ssh app5@107.170.27.154 → pull →
restart `app5-web`. Tracker / pip / PWA-cache steps only when their inputs change.

---

# THE BIG NEW ONE — xPPP game prediction (Part 1.5 / new part)

Raised by the coach in the AFTER interview (A4), and it is the largest new idea
in either part. **Interview before building** — this needs its own BEFORE pass.

A competitor predicts games from **expected shot quality alone**, taking
make/miss out entirely (every shot outcome is close to a coin flip, so shot-
making is the noisiest thing in the box score — the same reasoning behind the
SMOE shrinkage and the walk-forward gates already in this app).

Their shape, as described: rate every shot on many variables, aggregate to a
shot-quality **PPP** at game and season level, and derive win/loss expectancy
from that PPP alone.

Variables the coach named, **all of which this DB already has**:

| variable | column / helper |
|---|---|
| shot place (kind for us) | `shot_kinds.classify` — done |
| pass origin | `pass_from_id` |
| hockey assist | `hockey_from_id` |
| set by | `shot_created_by_id` |
| — and their **combinations**, weighted separately | `stats._creation_bucket` is a 4-way collapse of two of these; the coach wants all three as separate weights plus interactions |
| guarded or not | `guarded_by_id` |
| defense type | `defense` (5,832 tagged) |
| play type | `play_type` (5,236 tagged) |
| OREB% | four factors — hypothesis: high-OREB teams knowingly take worse shots because they expect the board |

Notes for whoever builds it:
- `helpers/shotquality.py` already fits a continuous ridge logistic on
  `[distance, distance², is_three, contested, angle]`. This is the natural home
  to extend — but the feature set above is much wider and 3,246–4,019 shots is
  not much sample, so regularization and out-of-sample validation matter more
  than fit.
- The creation term is currently a 4-way bucket (`self` / `pass` / `sc` / `both`)
  that **drops the hockey assist entirely**. The coach wants three separate
  weights and their combinations — that is a real modelling change, not a
  relabel.
- Validate the same way as the reprice: fit on one half of games, score the
  other, report log loss / Brier. Then walk-forward for the win-expectancy
  claim, per the house gate convention.
- The payoff is a prediction that doesn't move when a team shoots hot for a
  night — consistent with everything else this app has been built to do.

---

## Still deferred, unchanged

- **2.4 player card** — largest rendering job in Part 2. Its shot-kind bars must
  be **share** bars, not percentage bars (see the reliability finding).
- **1.2 timeout ROI** — blocked at 22 markers / 4 games. The unblocking move is a
  tracker-side logging fix, not an analytics build. Small; do it early so data
  accumulates.
- **Part 3 roster/graduation** — blocked on `grad_year` coverage (122/541, 22.6%).
  Build the coverage tool (§3.3) before the cliff or the projection. Note
  `players.position` **exists** — the roadmap's §3.4 claim that it doesn't is
  wrong; check its fill rate before designing a derived-role fallback.
- **Event Editor and Setup** are owed a full rework, "but today is not that day."
