# Officials rating rework — design

**Date:** 2026-09-05
**Branch:** `officials-rating-2026-09-05` (off `main`)
**Supersedes:** the `_RATING_WEIGHTS` composite at `helpers/officials.py:566`
**Evidence base:** prod snapshot, 63 tracked games, 79 officials, 2025-2026.
A first pass on the 43-game local DB is retained below only where the two
samples disagree, because the disagreement is the finding.

---

## 1. Why the current rating goes

```python
_RATING_WEIGHTS = [
    ("fpg",     -0.30),
    ("leverage", 0.25),   # game property
    ("ppp",      0.20),   # game property
    ("pace",     0.15),   # game property
    ("clutch",   0.10),
]
```

60% of the weight describes the games a referee was assigned, not the referee.
`leverage`, `ppp` and `pace` are the scoring environment and tempo of someone
else's basketball; a ref who draws two run-and-gun teams outranks an identical
ref who draws two grinders.

## 2. What the sample supports

**Games worked per official** (63 games): 20 refs at 1, 25 at 2, 15 at 3, 8 at
4, 5 at 5, 3 at 6, 1 at 7, 1 at 8. Maximum is **8**. The DB audit's 15-20
threshold would rate **zero** officials, so it is not an option.
`RATING_MIN_GAMES = 3` rates 33 of 79 and stays.

**Split-half reliability** — does a referee agree with themselves across their
own games?

| metric | 43 games | 63 games |
|---|---|---|
| FPG | +0.038 | +0.067 |
| foul_share | +0.158 | +0.027 |
| FPG, refs with n>=5 | -0.051 | +0.012 |

**`ha_diff`** (home fouls minus away fouls) against a binomial null: observed
mean 4.67 vs null 4.49, **p=0.391**. Home cooking — the thing coaches name most
about a bad official — is indistinguishable from coin flips in both samples.

**Consequence.** No *predictive* per-referee quality claim is supportable, so
the rework does not make one. It prices observed conduct instead: "in live
minutes, was this a shared crew effort?" That is a fact about games that
happened, not a forecast, so the reliability result does not bar it.

## 3. Why no environment metric is in the score

Does referee identity explain the game environment? Team-adjusted = the game's
value minus the mean of the two teams' own baselines.

| metric | form | 43 games | 63 games |
|---|---|---|---|
| Game fouls | team-adjusted | p=0.038, r=+0.251 | **p=0.191, r=+0.116** |
| Game fouls | raw | p=0.580, r=-0.056 | p=0.604, r=-0.027 |
| Pace | team-adjusted | p=0.397, r=-0.030 | **p=0.036, r=+0.074** |
| Pace | raw | p=0.236, r=+0.039 | p=0.572, r=-0.049 |
| PPP | team-adjusted | p=0.926, r=-0.303 | p=0.893, r=-0.072 |
| PPP | raw | p=0.884, r=-0.196 | p=0.791, r=-0.098 |
| Clutch calls | — | r=-0.189 | r=-0.020 |

**The significant result moved metrics between samples.** Team-adjusted game
fouls looked like the one survivor at 43 games (p=0.038); on the larger superset
it decays to p=0.191, while team-adjusted pace — which measured at chance in the
first sample — takes its place at p=0.036. That is the signature of multiple
comparisons, not of an effect: with six tests, roughly one lands under 0.05 each
run, and it is not the same one twice. No split-half exceeds +0.12.

So "the best refs let teams play, creating low fouls and high pace" is a
reasonable belief that **this data cannot support**. Nothing about the game
environment enters the score. Clutch is 148 calls across 63 games (2.3/game
across all crews), 8 of 33 rated refs have zero, and it self-correlates at
-0.020.

`FPG`, `leverage`, `PPP`, `pace`, `clutch`, `FPG_std` and `ha_diff` all remain
on the row as **descriptors**. `FPG` reads tight vs let-them-play with no
goodness sign; coding it -0.30 baked in "fewer fouls = better ref", which is a
preference, not a fact.

Re-run `scratchpad/measure_officials.py` against a larger sample before
revisiting this. It is written to run on whatever `APP5_DATA_DIR` points at.

## 4. Crew normalization

Six of 63 games log more than three officials:

```
crew 6  game 2      2026-01-16   crew of 6, exactly 3 with any foul
crew 6  game 3      2026-02-13   crew of 6, exactly 3 with any foul
crew 5  game 129    2026-02-07   crew of 5, exactly 3 with any foul
crew 6  game 13960  2026-02-13   crew of 6, exactly 3 with any foul
crew 6  game 15338  2026-02-10   crew of 6, exactly 3 with any foul
crew 5  game 21886  2026-03-14   crew of 5, exactly 3 with any foul
```

Games 3 and 13960 share a date and four names: a tournament day where two crews
were attached to one game. Left uncorrected this poisons the share null badly —
fair share becomes 17% instead of 33%, and four of the ten most extreme games
become refs at an ordinary 43-56% share.

**Rule:** when a game logs **more than 3** officials, drop those with zero
attributed fouls from the effective crew. This normalizes all six games to
exactly 3 and leaves the other 57 untouched.

The rule deliberately does **not** fire on crews of 3 or fewer. In normal
three-man crews 14 of 171 logged officials (8%) genuinely called no fouls;
dropping them would erase the quiet referee and inflate every colleague's fair
share.

## 5. Live-call pool

New `_live_foul_events()`. A foul counts toward share and volume unless it is:

- **strategic** — `late_game.strategic_foul_event_ids()`, 67 events. A team
  fouling to stop the clock is the coach's decision, not the official's.
- **garbage** — `quarter >= 4 and abs(margin) >= runs.GARBAGE_MARGIN` (20),
  139 events. Reuses the constant the Runs engine already applies to "this run
  doesn't count"; the app gains no fourth garbage-time definition.

1654 attributed fouls -> **1448 live calls**.

## 6. Share deviation, per game

A flat 40% threshold cannot be used. Under random dealing the *top* ref's share
of a 3-man crew averages 41-45% depending on call count:

| crew | 12 calls | 18 | 24 | 30 |
|---|---|---|---|---|
| 3 refs | 45% | 43% | 41% | 41% |
| 5 refs | 34% | 31% | 30% | 29% |
| 6 refs | 31% | 28% | 27% | 26% |

Across the 63 real games the observed top share is **43.7%** vs a matched null
of **40.8%** — a real gap, and wider than the 41.2 / 40.5 seen at 43 games, so
the share signal firmed up as the sample grew. But a 40% line would still fire
on most games while under-punishing 40% on a larger crew.

Share is therefore scored as deviation from fair share, weighted by sample. For
each (referee, game) with effective crew `k >= 2` and live calls `n >= 6`:

```
p  = 1 / k
mu = n * p
sd = sqrt(n * p * (1 - p))
z  = (ref_live_calls - mu) / sd
```

42% on a 3-crew scores ~0 (it is chance). The worst real game in the data —
`Unknown 11`, game 13979, **21 of 26 live calls = 81%** — scores **z=+5.13**.
Thin games mute themselves rather than spiking: were the `n >= 6` gate relaxed,
3 of 4 calls would be a 75% share but only z=+1.77.

A game failing `k >= 2` or `n >= 6` contributes to neither the mean nor the
worst-game term. A referee with no qualifying game has `rating = None`, the same
as one below `RATING_MIN_GAMES`, and their games-worked count still displays.

## 7. Volume vs league

The referee's live calls per game minus the league mean live calls per ref-game,
computed at runtime from the rated pool (never hardcoded — it moves with the
season), then z-scored across that pool.

This correlates ~+0.86 with the share term, so it enters at low weight. Its one
independent contribution is separating a referee who dominates a chippy crew
from one who dominates a quiet crew.

## 8. The score

```
share_term = 0.6 * mean(z per game) + 0.4 * max(z per game)
d          = 0.75 * share_term + 0.25 * volume_z
if d < 0: d *= 0.25
rating     = clamp(0, 100, 50 - 12 * d)
```

**The worst-game term (0.4 * max) is load-bearing.** Averaging alone dilutes the
case the rework exists for: one extreme game inside three normal ones is divided
by three and lands among referees who did nothing unusual.

**The credit clamp is asymmetric on purpose.** Below-fair-share earns 25% of the
penalty slope. Symmetric scoring would make the quietest referee in the league
the best-rated; at 25% they land above average but nowhere near the top. Quiet
is worth a little; disappearing is not excellence.

## 9. Gate, framing, scope

- `RATING_MIN_GAMES` stays **3**. Below it, `rating` is `None`.
- Every rated row displays games worked.
- The column is labelled **crew-share conduct in live minutes**, not "good
  referee". The reliability work does not support a quality claim at n<=8, and
  this framing is what lets a 3-game rating ship honestly.

**Placeholder names.** 19 of 79 officials are named `Unknown <n>` — note the
prod convention has **no `#`**, so the pattern is `^\s*unknown\b`
(case-insensitive). They are rated normally and appear in the bias tables, but
**sort below all named referees**: named refs first by rating, then unknown refs
by rating. They are real people who really worked those games, and the most
extreme conduct in the data (game 13979) belongs to one — excluding them would
delete the case that motivated this work and cut the rated pool from 33 to 23.
Sorting them under the named refs keeps the top and bottom of the table
actionable while leaving the record visible as a prompt to enter real names.

The pattern stays narrow. This data also carries `'Bald Bald'`, `'Balding'`,
`'3rd W Hair'` and `'Assistant AD'`, which are the same phenomenon under older
conventions, but no regex can tell `Balding` the nickname from `Balding` the
surname.

**N3 — ungated bias tables.** The two bias tables in `pages/8_Officials.py` list
any referee with two calls on a tag. They get the same `RATING_MIN_GAMES` gate
and the same live-call pool.

## 10. Components

| unit | responsibility | depends on |
|---|---|---|
| `_effective_crew(game_crew, fouls)` | drops zero-foul officials when logged crew > 3 | — |
| `_live_foul_events(events)` | foul rows minus strategic and garbage | `late_game`, `runs.GARBAGE_MARGIN` |
| `_share_z_by_game(live, crew)` | `{off_pk: {game_id: z}}` binomial deviation | `_effective_crew` |
| `official_ratings(...)` | assembles the score, gates the pool, orders the table | the three above |
| `pages/8_Officials.py` | renders rating + descriptors, gates bias tables | `official_ratings` |

## 11. Testing

- `_live_foul_events` drops exactly the strategic and garbage rows on a fixture
  game and nothing else.
- `_effective_crew` normalizes a 6-official game with three zero-foul rows to 3,
  and leaves a 3-official game with one zero-foul ref at 3.
- Share z is 0 at exactly fair share, positive above; the 21-of-26-on-a-3-crew
  case reproduces +5.13 within tolerance.
- Crew size is respected: the same 40% share scores ~0 on a 3-crew and clearly
  positive on a 6-crew.
- The worst-game term: a referee with one extreme game and two neutral rates
  meaningfully below a referee whose games are all mildly high with the same
  mean.
- Credit asymmetry: a far-below-fair-share referee lands above 50 but below the
  worst-penalised referee.
- `RATING_MIN_GAMES`: a 2-game referee has `rating is None` and appears in no
  bias table.
- Ordering: every named referee precedes every `Unknown` referee regardless of
  rating.
- Both suite halves: `python tracker/run_all.py` and `python -m pytest tracker/`.

## 12. Out of scope

Queued for a later branch: cross-state badge collision
(`UNIQUE(official_id, state)`), offline quick-add, iPad Mode, and the
`stats._team_game_ids` rollover trap.
