# Coach roadmap — 2026-07-25

> **BUILD LOG — Part 1 slice 1 shipped 2026-07-25.** Shot kinds (§1.6) is built,
> tested and rendering; the defense cross-tab is in; the xFG reprice is measured
> and held for review. **Seven claims in this document were wrong** and are
> corrected inline below, each marked `CORRECTED`. Read §BL at the bottom before
> building anything else here — several corrections change the specs still ahead.

Brainstorm output from the "think like a high school coach" pass over the whole app.
This is a **map for the next session**, not a deploy batch. Build order is fixed:

> **1. Insights → 2. OOTP-style UI → 3. Roster/graduation → 4. Coach-language explanation**

Everything below is written against verified code, not memory. Where a feature already
exists, it says so and the item becomes "surface it better," not "build it."

Constraints that shape every item:
- Prod droplet is **1 vCPU / 2 GB, no swap**. Bottleneck is CPU + the global cache clear
  on live-game writes — not RAM. Prefer derived reads over new tables; prefer one event
  pass reused by several sections over N passes.
- **DB is light right now.** Several items degrade to "not enough data" for months. Each
  one below states its coverage gate and what it renders when the gate fails.
- No new tracker taps unless explicitly noted. Coaches log at courtside; every extra tap
  costs data quality on the taps that already exist.

---

## 0. What already exists (do not rebuild)

Checked during this pass. This list exists so next session doesn't spend an hour
re-discovering it.

| Thing | Where | State |
|---|---|---|
| `grad_year` on players | `database/db.py:336-340`, `helpers/development.py:49` (`class_of`) | Column live, nullable, rollover-aware; identity propagates it (`helpers/identity.py:134`) |
| Development / progression | `helpers/development.py` | Season-over-season rows, class deltas, rest-of-season projection |
| Scoring runs | `helpers/runs.py` (`detect_runs`, RUN_MIN 6 / BIG_RUN 10 / garbage filter / momentum window) | Full engine. Surfaced in Rankings League Lab "Runs" + Situational tab |
| Live run alert | `helpers/courtside.py:100` `current_run`, `:153` `run_alert` | Tracker-side |
| Tempo buckets (transition ≤6s / early 7–14 / half-court 15+) | `helpers/insights_team.py:384`, glossary:260 | Derived from `possession_secs` |
| Score-state splits (leading/close/trailing, ±6) | `helpers/situational.py:31-32` | Real |
| ATO timeout splits | `helpers/situational.py:614` `timeout_splits` | **First possession only**, offense + defense vs baseline |
| play_type × defense cross-tab | `helpers/scout.py:434-440`, `helpers/defenses.py` | Real, on Scout — both defenses run and defenses faced |
| Shot coordinates | `game_events.shot_x/shot_y` (`database/db.py:261`), `helpers/court_geom.py` | Real x,y + `shot_distance` |
| Rest-days fatigue | `helpers/fatigue.py` | **Between**-game rest, not within-game load |
| Foul detail / bonus | `helpers/fouls.py` | Fouls drawn, FT by half, team fouls by quarter, bonus state |
| Ref crew outlook | `helpers/ref_tendencies.py`, `helpers/officials.py` | Pre-game crew synthesis: tightness, home lean, pace, late-game |
| Rebounding enrichment | `helpers/rebounding.py` | defender_secures, on/off-ball DREB, own-miss, PnR role |
| Charges | `helpers/charges.py` (gate dropped in `b6830fd`) | Live |
| Team Dashboard nav | `pages/6_Team_Dashboard.py:1473` `_TD_VIEWS` | 10 views, lazy `segmented_control` |
| Dashboard section modules | `helpers/dashboard/` (18 modules incl. `player_card.py`, `team_card.py`, `overview.py`) | The OOTP-card scaffolding already exists |
| **Foul trouble** `CORRECTED` | `helpers/foul_trouble.py` (381 lines, `b453ed9`), rendered at `6_Team_Dashboard.py:3978` | **Already built** — bench cost, team foul-state net, gated verdict, `tracker/test_foul_trouble.py`. §1.1 below is wrong to call it new. |
| **Player position** `CORRECTED` | `players.position` column, live | **Exists.** §3.4's "there is no position field" is false — verify how populated before designing around it. |

**Net read:** the math layer is far ahead of the presentation layer. Most of Part 1 is
joins across engines that already exist; Part 2 is almost entirely rendering.

---

## 0.5 Data recon — run 2026-07-25 against the live local DB

Read-only pass over `C:\Users\colby\AppData\Local\APP5\analytics.db`
(11.5 MB, last written 2026-07-22). **Note:** the repo-local
`APP5.0/analytics.db` is a 0-byte stub — always point recon scripts at the AppData
path, and use `C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe`
(shell `python` is the Store build and sees a virtualized shadow of AppData).

| Metric | Count | What it means for this roadmap |
|---|---|---|
| Tracked games | 43 | Enough for team-level reads, thin for lineup splits |
| Events | 7,731 | |
| Shots | 4,019 — **3,798 with x,y (94.5%)** | Shot-kind work is fully viable **today** |
| Fouls | 1,115 — **1,115 with official_id (100%)** | Foul-trouble + ref cross fully viable |
| Timeouts logged | **22, across only 4 games** | **Timeout ROI is blocked** — see 1.2 |
| play_type tagged | 5,236 events | Strong |
| defense tagged | 5,832 events | Strong |
| guarded_by tagged | 2,891 events | Good |
| event_lineup rows | 77,309 | Presence walk is well fed |
| Players | 541 — **grad_year set on 122 (22.6%)** | Part 3 blocked, as expected |
| rating_snapshots | **0 rows** | Table exists, never written — no rating history |

### The headline finding: the 5-zone system is hiding the league's biggest shot problem

Distance from rim, 2-point attempts only, 2-ft bands:

```
  0-2 ft   n=67    FG% 68.7   PPS 1.37
  2-4 ft   n=989   FG% 55.9   PPS 1.12
  4-6 ft   n=595   FG% 31.9   PPS 0.64   <-- cliff
  6-8 ft   n=220   FG% 26.4   PPS 0.53
  8-10 ft  n=143   FG% 20.3   PPS 0.41
 10-12 ft  n=134   FG% 30.6   PPS 0.61
 12-14 ft  n=116   FG% 25.9   PPS 0.52
 14-16 ft  n=85    FG% 22.4   PPS 0.45
 16-18 ft  n=67    FG% 26.9   PPS 0.54
```

Two things fall out, and both are new information for this app:

**1. The cliff is at exactly 4 feet, and everything past it is the same shot.**
The 4–10 ft "floater" band shoots **worse than the midrange** (0.48–0.64 PPS vs
0.45–0.61). The received wisdom that a floater is a better shot than a 15-footer is
false in this data. And that band is **23% of all shots taken in the league.**

**2. Legacy zone C blends the best shot on the floor with the worst.**

```
  zone C   n=2034  median 3.9 ft   p10 2.5   p90 7.7
  zone LC  n=130   median 12.1 ft
  zone RC  n=152   median 11.2 ft
  zone LW  n=65    median 14.0 ft
  zone RW  n=62    median 14.4 ft
```

Zone C — which is **more than half of all located 2s** — spans 2.5 ft to 7.7 ft, i.e.
1.29 PPS rim shots and 0.48 PPS floaters in one bucket. A ~0.8 PPS spread, invisible.
The five zones are an *angle* system with no depth axis, so every shooting read in the
app currently averages across the sharpest efficiency cliff in the sport.

### Recommended taxonomy (tuned to this data, not to NBA convention)

| Kind | Rule | n | Share | FG% | PPS |
|---|---|---|---|---|---|
| Rim | ≤ 4 ft | 1,056 | 27.8% | 56.7% | **1.13** |
| Floater / short paint | 4–10 ft | ~900 | ~23% | ~29% | **0.57** |
| Mid | 10 ft – arc | ~500 | ~13% | 26.0% | **0.52** |
| Corner 3 | `shot_type=3`, \|x\| ≥ 20 & y ≤ 14 | 463 | 12.2% | 31.1% | **0.93** |
| Above-break 3 | `shot_type=3`, else | 892 | 23.5% | 28.4% | **0.85** |

Data quality is good: only 6 threes logged inside 19.75 ft, zero twos logged beyond
22.5 ft. Coaches are tapping the court accurately.

### Floater share by team — it's a team problem, not just a league one

> `CORRECTED` **The percentages below are shares of 2-POINT ATTEMPTS, not of all
> shots.** Measured over all located shots the same teams read: Jay **43.4%**
> (111 floaters of 256), Adair **18.5%** of 1,213. So *"Jay takes more than half
> its shots from the worst band"* is false as written — it takes 43% of its
> shots and just under half its twos there. Still the league's worst diet by a
> wide margin; still worth the sentence; but the denominator has to be stated.
> Note also these pool BOTH genders and every season. Scoped to the pool the app
> actually renders (F / 2025-2026, 35 games) the league floater share is 25.4%
> and the rim/floater PPS gap is **+0.52**, not +0.56.

```
  Jay Girls                   54.3% of shots   FG% 25.9   (n=139)
  Locust Grove Girls          41.9%            FG% 37.1
  Kansas Girls                40.8%            FG% 32.6   (n=129)
  Adair Girls                 33.5%            FG% 43.6   (n=406)
  Claremore (Sequoyah) Girls  32.2%            FG% 46.1
```

Jay takes more than half its shots from the worst band on the floor at 25.9%. That is a
season-changing sentence a coach can act on tomorrow, and the app cannot currently say it.

### Grad-year coverage — the Part 3 blocker, quantified

```
  Inola Girls        13/13  100%
  Adair Girls          8/9   89%
  Claremore Sequoyah   5/11   45%
  Kansas Girls         0/17    0%
  ...every other team  0%
```

122 of 541 players, concentrated in three teams. The flagship team has none. Confirms
the call: **build the coverage tool (3.3) before the cliff (3.1) or the projection (3.2).**

---

# PART 1 — INSIGHTS

Ordered by coach-value per unit of build.

## 1.1 Foul-trouble economics (+ ref crew cross)  ⭐ highest value

> `CORRECTED` **`helpers/foul_trouble.py` already exists** (commit `b453ed9`,
> same day as this doc, which is why §0 missed it). Items 2 and 3 of the build
> spec below — `trouble_windows` and `cost_of_sitting` — are **shipped**, as
> `bench_cost` and `team_foul_state_net`, with a gated verdict and a test file.
> What is actually left of §1.1: **`foul_clock` (1)** and **`crew_foul_rate`
> (4)**. Item 5 `bonus_risk` should batch with §1.8's bonus-discipline item
> rather than being built here. Read that module's docstring first — it records
> two traps (the inverted foul convention; the reserve entry-timing artifact)
> that any new foul work will hit too.

**Why a coach cares.** Foul trouble is the single most common in-game decision a HS coach
makes ("do I sit her with 2 in the second?") and it is the one decision with zero data
support anywhere in the app. You are also the only product on earth with a per-official
history attached to the same event stream — nobody else can even attempt the cross.

**What exists.** `helpers/fouls.py` (fouls drawn/committed, bonus, by-quarter team fouls),
`helpers/officials.py` + `ref_tendencies.py` (crew profile), `game_event_lineup` (who was
on the floor at every event), `helpers/situational.py` (score state).

**What's missing.** Nothing joins them. There is no "minutes lost," no "when does she pick
up #2," no "team net while she sits," no ref-crew × player foul-rate cell.

**Build spec — new `helpers/foul_trouble.py` (Streamlit-free):**

1. `foul_clock(player_id, events)` → per game, the elapsed-seconds stamp of each personal
   foul charged (`event_type='foul'`, `secondary_player_id = fouler`). Yields the
   distribution of "time of Nth foul."
2. `trouble_windows(player_id, events, lineups)` → periods where the player carried
   2+ fouls before halftime or 4 in the second half **and was off the floor**. Uses the
   `game_event_lineup` presence walk that `helpers/presence.py` / stint logic already does
   — reuse, don't re-derive.
3. `cost_of_sitting(...)` → team net rating during those windows vs the player's on-court
   baseline, expressed in **points**, not rate. Coach sentence: *"Foul trouble cost you
   8.4 minutes and −11 points across 6 games."*
4. `crew_foul_rate(player_id, gender)` → the player's PF/100 possessions split by
   officiating crew vs their own baseline. **Gate hard**: require ≥3 games with a crew
   before showing a lean, and label it a lean, never a fact. Mirror the
   `ref_tendencies.CONFIDENT_GAMES = 4` convention.
5. `bonus_risk(team_id, events)` → from `fouls.py` bonus math: which quarter you put teams
   in the bonus earliest, and points allowed from that state.

**Where it renders.**
- Team Dashboard → **Insights**: verdict card, "Foul trouble is costing you X."
- Team Dashboard → **Roster/player profile**: per-player foul clock strip.
- Officials page: the reverse view — this crew vs my roster.
- Pre-game (Schedule / War Room): crew assigned tonight + my three highest-risk players.

**Coverage — verified viable.** 1,115 fouls logged, and **every single one carries an
`official_id`** (100%, not a typo). 43 tracked games, 77,309 event-lineup rows feeding the
presence walk. The foul clock and the cost-of-sitting number can be built and trusted today.

The **crew cross is the thin part**: the busiest officials have 3–4 games each
(Mark Mobra 44 fouls / 4 games, Blake Turner 39 / 4, Nate Haney 33 / 4). That is enough for
a *lean*, not a fact. Gate at ≥3 games with a crew, label it a lean, and shrink toward the
league whistle rate (`helpers/shrinkage.py`). Below the gate, show the foul clock only —
it's descriptive and always honest.

**Effort.** M. One engine module + three render blocks. No schema change, no new tracking.

---

## 1.2 Timeout ROI  ⛔ BLOCKED ON DATA — read this before building

**Recon result: 22 timeout markers across 4 games.** Every read below needs 15+ markers
*per team* to say anything. Do not build the engine yet — you would ship four empty cards.

**What to do instead, in this order:**

1. **Find out why logging is at 4 of 43 games.** Is the timeout button buried in the
   tracker, or do coaches not know it exists? One look at `tracker/static/app.js` and one
   question to a coach settles it. This is a 20-minute investigation with a large payoff —
   timeouts are the cheapest high-value event left untapped.
2. **Make it a one-tap, hard-to-miss control** on the tracker. A timeout is the easiest
   thing in the game to log: no players, no location, no result. There is no excuse for
   it to be at 9% coverage.
3. **Then** build the engine below, one season later, once markers accumulate.

Keeping the spec here so it's ready when the data is.

**What exists.** `situational.timeout_splits` — **first possession after the timeout only**,
our offense after our TO, our defense after theirs, each vs baseline PPP.

**What's missing** (all of it is the part coaches argue about):

1. **Run-stopping.** Cross `runs.detect_runs` with `game_timeouts`: when you called a TO
   during an opponent run, did the run end? Metric: *runs stopped / runs where you called
   a TO*, plus the same for runs where you didn't. This is the number.
2. **Timeout inventory.** How many you have left at the 4:00 mark of Q4, by game. Coach
   sentence: *"You averaged 0.7 timeouts left in the last four minutes; in your 4 losses
   under 5 points you had 0."* Pure chronology math, no new data.
3. **Window, not one possession.** Extend the ATO read to the next 2 and 4 possessions.
   One possession is a coin flip at HS sample; a 4-possession window is where a coach's
   intuition actually lives. Keep the 1-poss number (it's the "did the drawn-up play
   work" read) and add the window beside it.
4. **Their timeouts against you.** Same three reads mirrored — do you get punched after
   an opponent TO?

**Build spec.** Extend `helpers/situational.py:614` to `timeout_splits(..., windows=(1,2,4))`
returning a dict per window; add `helpers/timeouts.py` for the run-stop + inventory reads
(they need the games table + runs engine, not just the event stream, so keep them out of
situational).

**Coverage gate.** Report the marker count openly — *"read from 41 logged timeouts across
12 games"* — and suppress everything under ~15 markers. **Today that gate fails: 22 markers,
4 games.**

**Effort.** S–M for the engine (the chronology merge is already written). The real work is
the tracker-side logging fix in step 2 above.

---

## 1.3 Crash vs get-back

**Why a coach cares.** It's a *decision*, not a stat. Every HS staff has this argument and
nobody has ever put a number on it at this level.

**What exists.** ORB% (four factors), `helpers/rebounding.py` (defender_secures — the
box-out read), transition-allowed rate (`insights_team.py:449 o_transition`), points off
turnovers (`gameflow.py`).

**What's missing.** The two sides have never been placed on the same axis.

**Build spec — `helpers/crash.py`:**

For each of your missed shots, walk forward to the opponent's next possession:
- **Gain** = your ORB rate × the PPP of your putback possessions.
- **Cost** = opponent transition PPP on the possessions immediately following your misses,
  minus their half-court PPP baseline (tempo buckets already give you the split).
- **Net** = gain − cost, per 100 misses, and scaled to points/game.

Split by **who** is on the floor — the lineup crash profile is the actionable half.
Coach sentence: *"Crashing earns +4.1 pts/game on the offensive glass and gives back 6.8
in transition. With your starting five it's +1.2. With the bench group it's −4.9."*

Add a proxy for effort where the tags allow: `rebound_by` coverage is ~85% league-wide
per `rebounding.py`, so state coverage explicitly rather than assuming misses with no
rebound tag were defensive boards.

**Coverage gate.** ≥8 tracked games for the lineup split; ≥4 for the team number.

**Effort.** M. One forward-walk over the event stream, cacheable with the existing bundle.

---

## 1.4 Runs — deeper dive (new Charts sub-tab)

**What exists.** `helpers/runs.py` is genuinely good: run detection, length in game-clock
seconds, momentum window, garbage-time exclusion, margin-before. Surfaced on Rankings
League Lab + the Situational tab.

**What's missing is the coach's question, which is "why."** Runs are currently *counted*,
never *caused*.

**Build spec — `Charts → Runs` sub-tab** (`pages/6_Team_Dashboard.py:1577` tab tuple,
new module `helpers/dashboard/runs_tab.py` following the sibling-module pattern):

1. **Run anatomy.** For every run you gave up: what possession type started it (live-ball
   TO / ORB allowed / missed FT / made basket), what defense you were in, who was on the
   floor. This is the single most coach-actionable chart in this whole document.
2. **Run ledger.** Timeline strip per game — your runs above the line, theirs below,
   timeout markers overlaid. Reads like a heartbeat monitor; extremely OOTP.
3. **Who's on the floor.** Runs for/against per 100 possessions by lineup and by player.
   Small sample at HS — shrink toward the team mean, reuse `helpers/shrinkage.py`.
4. **Response.** Momentum window is already computed — surface it as *"after you gave up a
   10-0, you answered within 2 minutes 3 of 11 times."*
5. **Did it decide games.** Games with 0 / 1 / 2 / 3+ runs against → record. Blunt, and
   coaches repeat it all season.

**Effort.** M, mostly rendering. Engine already returns every field needed except the
"what started it" tag, which is one walk backward from the run's first basket.

---

## 1.5 Minutes load / in-game fatigue

**What exists.** `helpers/fatigue.py` — **between**-game rest days and schedule density.
Good, and unrelated to what's missing.

**What's missing.** Within-game load. Nothing shows what a coach feels in Q4.

**Build spec — extend `helpers/fatigue.py` (new section, same module):**

1. **Minute-of-game efficiency.** Team and player eFG / TO rate / PPP by game segment
   (Q1–Q4, plus last-4-minutes). Compare the player to their own baseline, not the league.
2. **Load per player.** Minutes/game from the presence walk vs the league distribution.
   Coach sentence: *"Your starters average 29.4 minutes; the league average for a 12-player
   roster is 24.1. Your Q4 eFG is 9 points below your Q1–Q3 eFG. Nobody else's is."*
3. **Stint length.** `_g_stints` already exists in `helpers/insights.py:740` — the verdict
   was shrunk onto its real sample in `3f234bc`. Extend it: *effect of stint length on the
   next stint's efficiency*, i.e. does a 9-minute run cost you the following possession.
4. **Rest-differential edge is already built** (`fatigue.league_rest_edge`) — surface it
   pre-game on the Schedule page rather than leaving it in a lab. *"They played Tuesday,
   you didn't. League MOV edge at +2 rest: +3.1."*

**Coverage gate.** Minutes come from event-lineup presence, which has gaps between events —
say so in the caption ("minutes are event-derived; treat as ±1"). Never print a minutes
figure to a decimal you can't defend.

**Effort.** M.

---

## 1.6 Shot classification — floater / rim / mid  ✅ SHIPPED 2026-07-25

> **Built:** `helpers/shot_kinds.py` + `helpers/dashboard/shot_diet.py` +
> `tracker/test_shot_kinds.py` (51 checks). Commits `041cebf`, `631864d`,
> `6b336c7`. Four corrections to the spec below, all from measurement:
>
> 1. `CORRECTED` **The corner-3 box is wrong.** `court_geom.is_corner_three`
>    already exists, derived from the real NFHS arc. The proposed `CORNER_X=20 /
>    CORNER_Y=14` box disagrees with it on **101 of the 1,355 located 3s**, so
>    adopting it would have created two corner-3 definitions in one app. Shipped
>    delegating to `court_geom`; only `RIM_FT`/`FLOATER_FT` are constants here.
>    Under the real definition the corner table is **384 / 10.1% / 31.5% /
>    0.945**, not the 463 / 12.2% / 0.93 below.
> 2. `CORRECTED` **The scout line cannot be built as written.** Split-half on
>    the live book (odd/even games, Spearman-Brown): player floater **share**
>    r=.636 (SB .778); player floater **FG%** r=.078 (SB .145). A player's
>    floater percentage does not predict her own floater percentage. So *"their
>    #12 lives on the floater — 34% on 61 attempts"* is half signal, half noise:
>    ship the share half, never the rate half. The module refuses per-kind rates
>    below `MIN_KIND_RATE_ATT` for this reason.
> 3. `CORRECTED` **A sample gate is not enough.** With only the sample gate five
>    teams fired the headline verdict, four of them reading "1 more floater than
>    league average — 1 point left on the floor, 0.1 a game". Materiality is a
>    second, separate bar. After it, exactly one team on the live book has
>    something to say (Jay Girls, 37 excess floaters, 19 points, 3.8 a game).
>    Excess is measured against the **league share**, not zero — no team can take
>    zero floaters, and the zero-baseline sentence overstates by ~4x.
> 4. `CORRECTED` **The xFG target named below is the wrong module.**
>    `helpers/shotquality.py` is already a continuous logistic on distance,
>    distance², is_three, contested and angle — it is *not* zone-based and does
>    not hide the cliff. The module that does is `stats.shot_quality_rates`,
>    keyed on **(zone, creation, guarded)**, which feeds `team_analytics.zone_xfg`
>    / `zone_xfg_by_type` and every xFG% on screen. That is the reprice target.
>    See §BL for the measured result — including that kind and zone together are
>    *worse* than either alone at this sample.

**Promoted to #1 after recon.** See §0.5 for the evidence. Summary: 94.5% of shots have
coordinates, the efficiency cliff at 4 ft is enormous (1.12 → 0.64 PPS), the 4–10 ft band
is 23% of all shots at 0.57 PPS, and legacy zone C blends both sides of the cliff into one
bucket covering half of all located 2s. Every shooting number in the app currently averages
across it.

**Confirmed gap.** `shot_x`/`shot_y` are real (`database/db.py:261`), `court_geom.shot_distance`
exists, but no code buckets a shot into *what kind of shot it is*. Zones are the five angular
slices (LC/LW/C/RW/RC); `shot_type` is 2 or 3. The app cannot say "floater."

**Build spec — `helpers/shot_kinds.py`.** Pure geometry, no new tracking, retroactive over
all 3,798 located shots. Boundaries below are **tuned to the actual distribution**, not
copied from NBA convention — the 4 ft rim line and the 10 ft floater line are where this
league's cliffs actually sit:

```python
HOOP_Y      = 5.25   # court_geom, already defined
RIM_FT      = 4.0    # cliff: 2-4ft = 55.9% FG, 4-6ft = 31.9%
FLOATER_FT  = 10.0   # past here the 2 is a midrange, and no worse
CORNER_X    = 20.0   # |x| beyond this with y <= CORNER_Y is a corner 3
CORNER_Y    = 14.0
```

| Kind | Rule | n | Share | FG% | PPS |
|---|---|---|---|---|---|
| Rim | 2, ≤ 4 ft | 1,056 | 27.8% | 56.7% | 1.13 |
| Floater / short paint | 2, 4–10 ft | ~900 | ~23% | ~29% | 0.57 |
| Mid | 2, 10 ft – arc | ~500 | ~13% | 26.0% | 0.52 |
| Corner 3 | 3, \|x\| ≥ 20 & y ≤ 14 | 463 | 12.2% | 31.1% | 0.93 |
| Above-break 3 | 3, else | 892 | 23.5% | 28.4% | 0.85 |

Put the constants in `helpers/model_constants.py` (house convention) so a recal can move
them, and re-derive the table above each recal rather than hardcoding the shares.

**Handle the 5% without coordinates** explicitly: classify as `unknown`, never silently
drop, and report located-share in every caption. `zone` stays as the angular axis — the two
systems are complementary (where on the arc × how far from the rim), which is a better
shot chart than either alone.

**What it unlocks, immediately and everywhere** (all of these are computable the day the
classifier lands, with the sample already in the DB):

- **Shot-diet verdict, per team.** *"41% of your shots come from 4–10 feet, where you shoot
  32.6%. That's 0.65 points a trip. At the rim you're at 1.13. Every floater you convert
  into a layup is worth half a point."*
- **The league baseline that makes it land.** League floater share is 23%; Jay is at 54%,
  Claremore at 32%. A coach needs the comparison, and it exists.
- **Per-player shot profile** on the OOTP player card (§2.4) — the rim/floater/mid/3 bar.
- **A real shot chart**: angle (zone) × depth (kind), instead of five wedges.
- **xFG / SMOE gets a far better feature** than the 5 zones — `helpers/box_score.py:258`
  already has the shot-quality baseline plumbing, and shot quality is currently being
  estimated with a variable that hides a 0.8 PPS spread.
- **Scout:** *"Their #12 lives on the floater — 34% on 61 attempts. Wall off the rim and
  live with it."*
- **Defense:** what kind of shot each scheme concedes. `defense` is tagged on 5,832 events,
  so "our 2-3 gives up rim, our man gives up threes" is one cross-tab away.
- **Prescriptions (§1.7):** floater share is the single best drill trigger in the app.

**Effort.** S for the classifier (a half-day, including the recal of the constants), M for
the downstream surfaces. **Highest leverage-to-effort item in the document** — one function
reprices the entire shooting layer, retroactively, over every game ever tracked.

---

## 1.7 Prescriptions tab (insight → drill)

**Why.** Everything in this app answers "what happened." A HS coach's next question is
always "what do I run at practice tomorrow." No competitor closes that loop.

**Build spec — new page or Team Dashboard view, `helpers/prescriptions.py`:**

A rules table mapping a **fired insight** to a **drill prescription**. The insight engine
already emits structured verdicts (`helpers/insights.py` `_g_*` generators,
`helpers/insights_team.py`) — key the table on those, not on free text.

Shape:

```
{"trigger": "totype_badpass",        # an insight key that already fires
 "when": "share >= 0.40 and n >= 40",
 "drill": "3-man weave vs 2 trailing defenders",
 "focus": "Pass away from pressure, catch ready",
 "minutes": 10,
 "evidence": "44% of your turnovers are bad passes (63 of 143)"}
```

Render as a **practice plan**: top 3–5 fired triggers, minutes budget, printable.
`helpers/printouts.py` + `helpers/pdf_export.py` already exist — reuse for the print path.

Ship v1 with ~15 rules covering the highest-frequency triggers (turnover type, FT%,
defensive rebounding, shot diet, transition defense, foul rate). Make it obvious the drills
are suggestions a coach can override; store overrides in `coach_notes` (table exists).

**Effort.** M. Mostly content authoring, not code. Highest coach-perceived value in the doc.

---

## 1.8 Smaller insight items (batch these)

- **FT points left on the floor.** *"58% team FT = 3.1 pts/game gifted; 4 losses were within 3."*
  All inputs exist in `fouls.py`. One card. Effort: XS.
- **Bonus discipline.** Which quarter you put opponents in the bonus, and points allowed from
  bonus state. `fouls.py` has the bonus math already. Effort: XS.
- **Set × defense promoted off Scout.** Already computed (`scout.py:434-440`). It's a *call
  sheet*, not a scouting detail — it deserves to be printable and to live where a coach
  looks pre-game, not three levels down. Effort: XS (a surface move).
- **Possession start type.** Tempo buckets proxy this well already. True start typing
  (off make / off DREB / off live TO / after TO) is a backward walk from each possession's
  first event — worth doing *only as part of 1.4's run-anatomy work*, where it's needed
  anyway. Don't build it standalone.
- **Close-game profile.** Score-state splits exist at ±6. The garbage-time detector exists.
  The inverse — a dedicated "close games only" lens across the whole dashboard — is a
  filter, not an engine. Consider a global "close games only" toggle in the header.

---

# PART 2 — OOTP-STYLE UI

Stated design values from this session, in the coach's own words:

> "Lots of info that's easy to understand quickly." · "The header changing per team gives that
> super customized, personal feel." · "Depth, information, honestly overloading a coach with so
> much information so no matter what they can customize it to find what they want."
> **More information, more information, more information.**

So: **density is a feature, not a bug.** The job is not to remove information. It is to give
the information a *shape* so a coach can scan it in three seconds and drill for an hour.
That is exactly what OOTP does — its screens are dense to the point of absurdity, and they
read instantly, because of four rules:

1. **A persistent identity header.** You always know whose page this is.
2. **The card is the atom.** Every entity (player, team, game, opponent) has one canonical
   card that looks the same everywhere it appears.
3. **Numbers carry their own context.** A rating is never naked — it's colored, ranked,
   and sits next to a league bar.
4. **One click to the next entity.** Every name is a link. You never go back to a menu.

Audience note that unlocks a lot: the main app is **not public**. It's coaches and
administrators, 99% tied to one team or school. So it can and should behave like a
front office, not a website.

## 2.1 Team Dashboard becomes home

**Decision on the table and recommended: yes.** Replace the current Main landing with the
Team Dashboard Overview for the coach's own team.

- Default team = the coach's team from `coach_teams`; fall back to a picker if unresolved
  or if an admin has several.
- The current Main content (league-wide) doesn't disappear — it becomes a **League** page,
  reachable from the header.
- Watch the CPU cost: Overview is not free, and it would now run on every login. Cache
  aggressively, and consider a slimmer "home" render of Overview that lazy-loads the
  heavier zone/glance blocks below the fold.

## 2.2 The front-office header

One persistent bar across every page. `helpers/dashboard/team_card.py` already draws a
banner; promote it to app-level chrome.

```
[crest] KANSAS COMETS  ·  Girls 2A  ·  14-6 (7-2 dist)  ·  Power 68.2 ▲1.3 (A)  ·  #4 of 62
        Next: @ Westville  Fri 7:30   ·   Crew: Smith/Jones  (tight, +hm)   ·   [season ▾]
```

Team colors drive the accent — that's the "personal" feel, and it's cheap: one accent color
per team, applied to the header rule, the sparkline, and the tier chip. Everything else stays
on the dark system palette so the app doesn't turn into a coloring book.

## 2.3 Season news feed

The most OOTP thing you can add, and you already own every input
(`helpers/public_feed.py`, `helpers/social_cards.py`, `helpers/awards.py`,
`helpers/rating_history.py`, `helpers/postgame.py`).

Reverse-chronological, on home, below the header:

```
Fri 2/14  W 58-51 vs Kansas          Power 66.9 → 68.2 (+1.3)   [box] [postgame]
          #12 career-high 24 · 4th-quarter 12-0 run · your best defensive game (0.81 PPP allowed)
Wed 2/12  Practice note added
Tue 2/11  L 44-52 @ Westville        Power 67.4 → 66.9 (−0.5)
          Foul trouble: #23 sat 11:20 · 14 turnovers (season high)
```

Every item is generated from an engine that already runs post-game. Every noun is a link.

## 2.4 The player card as the atom

`helpers/dashboard/player_card.py` exists — make it the canonical unit and use it everywhere
(Roster grid, Compare, Leaders, Scout, hover in the news feed).

Card contents, OOTP-shaped:

```
┌──────────────────────────────────────────────────┐
│ #12  JORDAN REESE          Jr · 5'9" · 6'0" wing │
│                                                  │
│      OVERALL  78    ▲ +6 from last season        │
│                                                  │
│ Scoring    ███████░░░ 74   Rim     ████████░░ 81 │
│ Shooting   █████░░░░░ 58   Floater ███░░░░░░░ 34 │
│ Playmaking ████████░░ 80   Mid     ██████░░░░ 61 │
│ Defense    ██████░░░░ 66   3PT     ████░░░░░░ 45 │
│ Rebounding ████░░░░░░ 42                         │
│                                                  │
│ 🏅 Closer  🏅 Rim Pressure  🏅 Iron              │
│ Archetype: Downhill Creator                      │
│ "Gets to the rim at will against man; the floater│
│  is her tell — 34% on 61 attempts."              │
└──────────────────────────────────────────────────┘
```

Every input exists: `player_ratings.py` (OVERALL + components), `badges.py`, `archetypes.py`,
`shrinkage.py` (so small samples don't produce silly 99s), `development.py` (the season delta),
and 1.6 above supplies the shot-kind bars. The prose line is template-generated from the
top-firing insight for that player — same generator family as `helpers/scout.py`.

**Ratings scale decision to make next session:** 0–99 (OOTP/2K, instantly legible to a HS
audience) vs 20–80 (scouting-native, more honest about uncertainty). Recommend **0–99** for
the audience, with the underlying uncertainty expressed by a **confidence dot**, not by the
scale.

## 2.5 Navigation: group the 16 pages

Sixteen flat sidebar entries is the app's biggest structural UI problem. Group them:

```
MY TEAM      Home (Overview) · Roster · Schedule · Insights · Charts
GAME DAY     Tracker · Event Editor · Scout · War Room · Prescriptions
LEAGUE       Rankings · Players · Officials · Hall of Fame
ADMIN        Input Hub · Setup · Settings · OSSAA Import · FAQ
```

Nesting inside Team Dashboard is currently 3 deep (10 views → 6 tabs → 4 tabs). The Charts
overhaul already fought this; **Lab and War Room need the same treatment.** Rule of thumb:
two levels of chrome max, then it's a page.

## 2.6 Density patterns worth stealing from OOTP

- **Everything is a link.** Player name anywhere → player card. Opponent anywhere → scout.
  Date anywhere → box score.
- **Inline league bars.** Every team/player number gets a thin bar showing its position in
  the league distribution. Turns a naked number into a judgment without any prose.
- **Sortable everything.** Any table a coach might want ranked differently, they can.
- **Compare mode as a first-class verb**, not a tab. Two of anything, side by side.
- **Season-end rituals.** Awards night + a development report (who grew, who stalled) at
  rollover. `helpers/awards.py` and `helpers/hall_of_fame.py` are already there.

---

# PART 3 — ROSTER / GRADUATION

`grad_year` is live and scoped. The two things that use it and don't exist yet:

## 3.1 Graduation cliff

*"You lose 61% of minutes, 74% of shot creation, both rim protectors."*

**Build spec — `helpers/roster_horizon.py`:**

For a season, partition the roster by `class_of(grad_year, season_label)`
(`helpers/development.py:49`) into returning vs departing, then compute the departing share of:
minutes, points, possessions used, shot creation (`shot_created_by_id` + assists),
defensive rebounds, rim protection (blocks + defended-FG), and — the headline —
**share of team WAR / rating value** (`helpers/hoopwar.py`).

Render as a single stacked bar per category plus a verdict line, on a **Roster → Horizon**
sub-view.

## 3.2 Returning-production projection

Next season's Power estimate from who's back:

1. Returning players' current ratings, aged by the class-transition delta that
   `development.py:181` already computes (with its "always a lean" honesty).
2. Departing production redistributed to returners by a usage-continuity assumption —
   **state the assumption on screen**, don't hide it in code.
3. Feed the resulting roster through the existing team-rating path
   (`helpers/team_ratings.py`) for a projected Power + tier.
4. Show it as a **range**, not a point. At HS sample with unknown incoming freshmen, a
   point estimate is a lie.

`rating_snapshots` (`database/db.py:570`) is the natural store for the projection so
next season can score it against reality — that's the honesty loop that makes the number
worth trusting in year two.

`rating_snapshots` has **0 rows today** — the table was created and never written. Whatever
writes it needs to exist before the projection can ever be scored against reality, so wire
the write when you build 3.2, even if nothing reads it for a year.

## 3.3 The coverage problem (the real blocker)  ← do this one first

**Verified: 122 of 541 players have a `grad_year` (22.6%), and it is concentrated in three
teams** — Inola 13/13, Adair 8/9, Claremore Sequoyah 5/11. Every other team is at zero,
including Kansas Girls (0/17), which is the most-tracked team in the DB. A graduation cliff
built today would render for three teams and be blank everywhere that matters.

Design for that from line one, don't bolt it on:

- Compute a **coverage %** — share of *minutes* (not headcount) with a known `grad_year` —
  and gate the whole view on it. Under ~80%: show the coverage meter, list the unknowns
  with an inline "set grad year" control, and render nothing else. Half a cliff is worse
  than no cliff.
- Make filling it a **30-second job**: one grid, roster × grad year, saved in a single
  write. `helpers/roster_import.py` exists — extend the import path to carry grad year, and
  put the grid on Setup and on the Roster view's empty state.
- `helpers/identity.py:134` already propagates `grad_year` across a person's season rows, so
  a coach fills it once per player, ever. Say that on screen — it's the reason they'll do it.

**Do 3.3 first.** 3.1 and 3.2 are worthless without the data and are a small build once it's there.

## 3.4 Also missing on players: position

There is no position field. Depth chart, "you have no returning post," and position-relative
ratings all depend on it. Two options, and the second is better:

- **Manual** `position TEXT` — coach picks. Cheap, wrong often, and one more setup chore.
- **Derived role** from the archetype/usage engines that already exist (`archetypes.py`
  clusters, rebound/creation shares) → "Primary handler / Wing / Post" with a manual
  override stored in settings. **Recommended** — zero setup cost, and it self-corrects as
  the season fills in.

---

# PART 4 — COACH-LANGUAGE EXPLANATION

Approved this session: change the language.

## 4.1 Every number carries a "so what"

`helpers/glossary.py` (725 lines) defines terms. Definitions are not explanations. A coach
reading `TOV% 18.4` needs *"You give it away on 18 of every 100 trips. League is 15. That's
about 4 extra empty possessions a game — a two-possession swing."*

**Pattern to adopt app-wide:** every stat display gets an optional `coach_line` —
one sentence, second person, converted to **points or possessions per game**, never to a
rate a coach has to translate in their head. Store them next to the glossary entries so
there is exactly one source of truth per stat.

## 4.2 Confidence, inline and everywhere

The insight engine already shrinks and gates (`tier_gate`, `shrinkage.py`, the stint-verdict
fix in `3f234bc`). The *display* doesn't consistently say so. Adopt one visual vocabulary:

- ● solid = enough sample, trust it
- ◐ half = directional, will move
- ○ hollow = too early, shown for completeness

One dot, same meaning on every surface. This is what earns trust with a coach who's been
burned by a stat that flipped in February.

## 4.3 Verdict first, evidence under it

Already the house style on Insights (the benchmark). Extend it to Charts, Scout, and the
player card. Structure: **verdict sentence → the number → the comparison → the drill**
(the drill link comes free once 1.7 exists).

## 4.4 Kill the remaining stat-speak

Sweep for terms that mean nothing on a HS bench and give each a coach-facing alias while
keeping the real term in the glossary: SMOE, RAPM, DWPA, xA/G, HAST, shrinkage, prior.
The number stays. The label becomes something a coach would say out loud.

---

# Suggested next-session order

Revised after the §0.5 recon. Data viability, not just coach value, drives this list.

| # | Item | Why here | Data status |
|---|---|---|---|
| 1 | **1.6 shot kinds** | Half-day build, reprices the entire shooting layer retroactively, and surfaces the single largest actionable fact found in this whole pass | ✅ 3,798 located shots |
| 2 | **1.1 foul trouble + ref cross** | Highest coach value; uses ref data no competitor has | ✅ 1,115 fouls, 100% with official |
| 3 | **2.2 + 2.3 header + news feed** | The OOTP feel lands in one session, over engines that already exist | ✅ |
| 4 | **2.4 player card** | Pure rendering; §1.6 supplies its best new bar | ✅ after #1 |
| 5 | **3.3 grad-year coverage tool** | Unblocks all of Part 3; useless to build 3.1/3.2 first | ⚠️ 22.6% coverage — that's the point |
| 6 | **4.1 + 4.2 coach lines + confidence dots** | A sweep — do it alongside whatever else is open | ✅ |
| 7 | **1.7 prescriptions** | Closes the loop; #1 hands it its best trigger | ✅ after #1 |

**Second wave:** 1.3 crash/get-back, 1.4 runs tab, 1.5 minutes load, 2.1 home swap,
2.5 nav grouping, 3.1/3.2 cliff + projection, 3.4 derived position.

**Deliberately deferred:** 1.2 timeout ROI — blocked at 22 markers across 4 games. The
unblocking move is a tracker-side logging fix, not an analytics build. Do that fix early
(it's small) so the data accumulates while everything else ships.

---

# §BL — BUILD LOG, Part 1 slice 1 (2026-07-25)

Shipped: `helpers/shot_kinds.py`, `helpers/dashboard/shot_diet.py`,
`tracker/test_shot_kinds.py` (51 checks), renders on Charts → Offense → Shooting
→ Shot Profile, on Insights above the auto-scout, and on the Defense tab.
Commits `041cebf`, `631864d`, `6b336c7`.

## The measured league table (F / 2025-2026 — the pool the app renders)

Scope matters and the §0.5 table did not state its own. Pooled across BOTH
genders and ALL seasons the numbers differ from the pool any single team is
actually compared against. The girls' 2025-2026 book, 35 tracked games, 3,056
located shots:

```
  rim          836   27.4%   PPS 1.086
  floater      777   25.4%   PPS 0.569
  mid          370   12.1%   PPS 0.503
  corner3      285    9.3%   PPS 0.874
  abovebreak3  788   25.8%   PPS 0.784
  rim − floater gap: +0.517 pts/shot
```

The headline finding survives scoping: the 4–10 ft band is a quarter of every
shot at 0.57 PPS, and it is no better than the midrange. Data quality is better
than §0.5 claimed — **zero** 3s logged inside the arc, **zero** 2s beyond 22.5 ft.

## Reliability, and what it forbids

The gate numbers in the shipped module are not chosen, they are measured. Full
table in `shot_kinds.py`'s docstring. The load-bearing rows:

| unit · metric | r | SB | consequence |
|---|---|---|---|
| player floater share | .636 | .778 | gate 20 located attempts — trustworthy |
| player rim share | .626 | .770 | wants ~40 |
| player PPS | .317 | .481 | weak; goes **negative** at high thresholds |
| player floater PPS | **.078** | **.145** | **noise — never displayed as a judgment** |
| team floater share | .582 | .736 | gate 80 located attempts |
| team PPS | .569 | .725 | directional |

Unit counts are small (42 players, 9 teams), so treat these as order-of-
magnitude — which is the argument for setting gates *above* them, not at them.

**The general lesson for the rest of this document:** shares are count ratios
and survive thin samples; rates do not. Any spec line that quotes a per-player
percentage — §2.4's player card bars, §1.7's prescription evidence strings,
§1.1's crew cross — needs this same split-half check before it ships a number.

## The xFG reprice — ✅ LANDED (`6bc25b3`)

Out-of-sample (fit on odd games, score even, and the reverse):

```
  baseline key                   log loss     Brier
  zone × creation × guard         0.63879    0.22214
  KIND × creation × guard         0.62403    0.21290   <- better
  zone + kind × creation × guard  0.66671    0.21861   <- worse than either
```

Two results:

1. **Depth beats angle** as the shot-quality key — 2.3% better log loss, 4.2%
   better Brier. The spec's instinct was right.
2. **Both axes together are worse than either alone.** 3,246 shots cannot fill
   5 zones × 5 kinds × 4 creation × 2 contest cells. "Complementary axes" is
   true for DISPLAY and false for the MODEL at this sample. If the reprice
   lands, it is kind *instead of* zone in `stats.shot_quality_rates`, not both.

Per-player effect at n≥40 (22 players): mean |move| 1.55pp, max 5.85pp, and
**3 of 22 players' SMOE changes sign**. The largest movers are rim-heavy
players whose shot difficulty zone over-stated — Hannah Bond's SMOE falls from
+14.4 to +8.5, Reagan Langley's from +9.6 to +4.9. That is the cliff correction
doing exactly what it should.

Shipped as one shared key term, `stats._sq_loc`, **not** by editing
`shot_quality_rates` alone: the key was rebuilt inline at eleven call sites
across `stats`, `team_analytics`, `passing_chains` and `insights_team`, so
changing only the producer would have left every consumer silently missing its
lookup and falling back to 0.0. `_sq_loc` is now the single place the location
taxonomy is decided — change it there or nowhere.

Verified on the live book after landing: Bond +8.5, Langley +4.9, exactly the
pre-flight predictions. Zone remains the display axis everywhere.

**Not repriced:** `stats._bucket_make_rate` and its fine/coarse model at
`stats.py:1149` still key on zone. Separate model, own thin-cell fallback, not
part of this measurement — it needs its own out-of-sample run first. That is
the obvious next piece of this thread if anyone wants it.

**Test lesson worth carrying:** `tracker/test_xa2.py` asserted against a
hard-coded `("C","pass",False)` key and so reported a *credit-rule* failure
when the rule was untouched. Tests should ask the engine for its key, not
restate the taxonomy.

## Traps found, worth not re-finding

- **`S.fetch_events([])` returns the ENTIRE database** — 7,670 events, both
  genders, every season. An empty game-id list means "everything", not
  "nothing". `PT._tracked_game_ids(gender)` legitimately returns `[]` because
  the active season is a fresh rollover, so the first working version silently
  built a girls' league baseline out of boys' games. **Every new pooled engine
  needs an explicit empty guard.**
- **`PT._tracked_game_ids` takes gender only** — no season argument. Season
  scoping comes from the page's own `_gender_tracked_ids(g, season)` or from
  `ctx.season_gp`.
- **"Shot diet" was already three different blocks** (`6_Team_Dashboard.py:1997`,
  `player_card.py`, `5_Rankings.py`). The new one is "Shot depth". Grep before
  naming a block.
- **An AppTest smoke that does not patch `helpers.ui.gender_radio` renders the
  same team regardless of `ta_team`** — two teams produced byte-identical
  288,712-char pages. Add it to the patch list in the smoke pattern beside
  `auth_enabled` / `has_paid_plan`.
- **`mapped_shots` fills unlocated shots with the ZONE CENTROID.** A centroid
  has a distance, so it classifies happily and a zone-C centroid becomes a "rim"
  shot nobody took. `classify_shot` sends `approx=True` to `unknown`.

## Defense × kind — built, and one unpredicted finding

```
  scheme          n     rim   floater   ab-3    PPS allowed
  Man-to-man   1463   23.5%    27.5%   28.0%      0.704
  2-3 zone      639   18.6%    20.3%   33.0%      0.729
  Scramble      454   55.5%    18.7%   11.7%      1.009
  Man press     151   27.8%    31.8%   20.5%      0.583
```

The 2-3 behaves exactly as the cliché says — fewest rim shots conceded, most
threes — which is a good sign the axis measures what it claims. **Scramble
concedes 55.5% of its shots at the rim, at 1.009 PPS.** A broken-play state
naturally gives up rim looks, but that is a number a coach should see rather
than infer, and it is a candidate trigger for §1.7.

## What this changes for the parts still ahead

- **§2.4 player card:** the rim/floater/mid/3 bars must be **share** bars, not
  percentage bars. A per-player floater FG% on a card is a number that will not
  survive contact with next month's games.
- **§1.7 prescriptions:** floater share is confirmed as the best drill trigger
  in the document — it is the reliable metric AND the largest effect. Key the
  rule on share and materiality, never on floater FG%.
- **§1.1 crew cross:** apply the same split-half test before shipping any
  per-player-per-crew rate. Foul rate by crew is a rate at a thinner sample than
  floater FG%, which failed at r=.078. Expect it to fail too, and design the
  read as a *share/count* statement if it does.
- **§4.2 confidence dots:** there is now a measured basis for which reads get a
  solid dot. Wire the dot to the split-half number, not to a games count.
- **§3.4 position:** `players.position` exists. Check its fill rate before
  designing the derived-role fallback.

---

## Recon reproducibility

The scripts behind §0.5 were throwaway. To re-run:

```bash
"C:\Users\colby\AppData\Local\Programs\Python\Python312\python.exe" -c "import sqlite3,math; c=sqlite3.connect(r'file:C:\Users\colby\AppData\Local\APP5\analytics.db?mode=ro',uri=True); print(c.execute('SELECT COUNT(*) FROM game_events WHERE event_type=\"shot\" AND shot_x IS NOT NULL').fetchone())"
```

Two gotchas that cost time this session, worth remembering:
- `APP5.0/analytics.db` in the repo is a **0-byte stub**. The real DB is at
  `C:\Users\colby\AppData\Local\APP5\analytics.db`.
- Shell `python` is the Microsoft Store build and reads a **virtualized shadow copy** of
  AppData. Use the `Python312` path above (the same one `.claude/launch.json` pins) for any
  live-DB work, and open the DB read-only (`mode=ro`) so a recon script can never touch it.
