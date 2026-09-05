# Officials rating rework — design

**Date:** 2026-09-05
**Branch:** `officials-rating-2026-09-05` (off `main`)
**Supersedes:** the `_RATING_WEIGHTS` composite at `helpers/officials.py:566`

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

## 2. What the sample actually supports

Measured against the live DB, 2025-2026, 43 tracked games, 70 officials.

**Games worked per official:** 31 refs at 1, 19 at 2, 14 at 3, 4 at 4, 2 at 5.
The maximum any official has worked is **5**. The DB audit's shippable threshold
of 15-20 games would rate **zero** officials, so that threshold is not an
option. `RATING_MIN_GAMES = 3` rates 20 of 70 and stays.

**Split-half reliability** — does a referee agree with themselves across their
own games?

| metric | r (n>=3, 20 refs) | r (n>=4, 6 refs) |
|---|---|---|
| FPG | +0.038 | -0.051 |
| foul_share | +0.158 | -0.342 |

**Permutation tests**, against a null that deals each game's fouls at random
among that game's crew:

| test | observed | null | p |
|---|---|---|---|
| FPG across-ref SD | 2.78 | 1.83 | <0.0001 |
| FPG_std across-ref spread | 1.75 | 1.19 | 0.0017 |
| mean `\|ha_diff\|` (vs binomial) | 3.70 | 4.06 | 0.71 |

The first two pass and the split-half sits at zero because the excess is
**within-game crew unevenness**, not a stable referee trait: max-minus-min share
of a game's calls is 0.235 observed vs 0.199 null (p=0.013). In one game ref A
dominates the whistle, in the next ref B does.

`ha_diff` — home cooking, the thing coaches name most about a bad ref — is
**indistinguishable from coin flips**, and if anything more balanced than
chance.

**Consequence.** No *predictive* per-referee quality claim survives at this
sample, so the rework does not make one. What it prices instead is observed
conduct: "in live minutes, was this a shared crew effort?" That is a fact about
games that happened, not a forecast, so the reliability result does not bar it.

## 3. What the environment metrics support

Does referee identity explain the game environment? Team-adjusted = the game's
value minus the mean of the two teams' own baselines across their tracked games.

| metric | form | spread vs null | split-half r |
|---|---|---|---|
| Pace | raw | p=0.236 | +0.039 |
| Pace | team-adjusted | p=0.397 | -0.030 |
| PPP | raw | p=0.884 | -0.196 |
| PPP | team-adjusted | p=0.926 | -0.303 |
| Game fouls | raw | p=0.580 | -0.056 |
| **Game fouls** | **team-adjusted** | **p=0.038** | **+0.251** |
| Clutch calls | — | — | -0.189 |

One metric survives: **team-adjusted game fouls**. With this crew on the floor,
did these two teams foul less than they normally do? That is "lets them play"
stated causally, and it is the only quantity in the study with positive
self-agreement.

Pace and PPP measure at or below chance in both forms. Clutch is 88 calls total
across 43 games (2.0/game across all crews), 5 of 20 rated refs have zero, and
it self-correlates negatively.

**Caveat to carry:** 7 tests, one hit at p=0.038, so ~0.35 false positives are
expected by chance. The split-half is a structurally separate check and it
agrees, which is why the metric is adopted — but it is suggestive, not settled.
Re-run this table when the sample grows.

## 4. Live-call pool

New `_live_foul_events()` in `helpers/officials.py`. A foul counts toward share
and volume only if it is neither:

- **strategic** — `late_game.strategic_foul_event_ids()`, the intentional
  clock-stop foul. 45 events. A team fouling to stop the clock is the coach's
  decision, not the official's.
- **garbage** — `quarter >= 4 and abs(margin) >= runs.GARBAGE_MARGIN` (20).
  104 events. Reuses the constant the Runs engine already applies to
  "this run doesn't count"; the app gains no fourth garbage-time definition.

1110 attributed fouls -> **961 live calls**.

## 5. Share deviation, per game

A flat 40% threshold cannot be used. Under pure random dealing the *top* ref's
share of a 3-man crew averages 42-48% depending on call count:

| crew | 12 calls | 18 | 24 | 30 |
|---|---|---|---|---|
| 3 refs | 48% | 45% | 43% | 42% |
| 5 refs | 36% | 33% | 31% | 30% |
| 6 refs | 33% | 30% | 28% | 27% |

Real games: observed mean top share 41.2% vs matched null 40.5%. Crews in the
data are 3 refs (40 games), 5 (1), 6 (2). A 40% line would fire on 30 of 43
games, nearly all blameless, while under-punishing 40% on a 6-man crew where
fair share is 17%.

So share is scored as deviation from fair share, weighted by sample. For each
(referee, game) with crew size `k >= 2` and live calls `n >= 6`:

```
p  = 1 / k
mu = n * p
sd = sqrt(n * p * (1 - p))
z  = (ref_live_calls - mu) / sd
```

42% on a 3-crew scores ~0 (it is chance). 90% of 25 live calls scores **+6.01**.
Crew size and call count are both handled without a hand-set constant, and thin
games mute themselves rather than spiking: were the `n >= 6` gate relaxed, 3 of
4 calls would be a 75% share but only z=+1.77. The gate is belt-and-braces on
top of that property, not the only thing holding it.

A game that fails `k >= 2` or `n >= 6` contributes to neither the mean nor the
worst-game term. A referee with no qualifying game has `rating = None`, the same
as one below `RATING_MIN_GAMES`, and their games-worked count still displays.

## 6. Volume vs league

The referee's live calls per game minus the league mean of **7.01** live calls
per ref-game, z-scored across the rated pool.

This correlates +0.862 with the share term, so it enters at low weight. Its one
independent contribution is separating a referee who dominates a chippy crew
(ref 8: +1.64 share-z on 12.0 calls/game) from one who dominates a quiet crew
(ref 57: +1.67 share-z on 8.7 calls/game).

## 7. The score

```
share_term = 0.6 * mean(z per game) + 0.4 * max(z per game)
d_conduct  = 0.75 * share_term + 0.25 * volume_z
d          = 0.80 * d_conduct   + 0.20 * env_z
if d < 0: d *= 0.25
rating     = clamp(0, 100, 50 - 12 * d)
```

`env_z` is the referee's mean team-adjusted game-foul residual, z-scored across
the rated pool, signed so that positive = these teams fouled *more* than their
own baseline = worse.

**The worst-game term (0.4 * max) is load-bearing.** Averaging alone dilutes the
case the rework exists for: one 90%-of-25-calls game inside three otherwise
normal games averages to z=+2.00 and rates 32.0 — indistinguishable from ref 57,
who never did anything remotely that extreme. With the worst-game term that ref
lands near 20.

**The credit clamp is asymmetric on purpose.** Below-fair-share earns 25% of the
penalty slope. Symmetric scoring would make ref 59 — who calls 1.7 fouls a game
— the best official in the league at 76.1; at 25% they reach ~56, above average
but nowhere near the top. Quiet is worth a little; disappearing is not
excellence.

## 8. Gate, framing, and scope

- `RATING_MIN_GAMES` stays **3**. Below it, `rating` is `None`.
- Every rated row displays games worked.
- The column is labelled as **crew-share conduct in live minutes**, not "good
  referee". The split-half work does not support a referee-quality claim at
  n<=5, and this framing is what lets a 3-game rating ship honestly.
- `FPG`, `leverage`, `ppp`, `pace`, `clutch`, `FPG_std`, `ha_diff` remain on the
  row as **descriptors**. `FPG` reads tight vs let-them-play with no goodness
  sign; coding it -0.30 baked in "fewer fouls = better ref", which is a
  preference, not a fact.

**Placeholder names.** Officials whose name matches `unknown #<n>`
(case-insensitive) are excluded from the rated pool and from both bias tables,
but stay in the overview and **still count toward crew size and the league
baseline** — they did work the game, and dropping them from the denominator
would inflate every named ref's share. The pattern stays narrow: this DB also
carries `'Bald Bald'`, `'Balding'`, `'3rd W Hair'`, `'Assistant AD'`, which are
the same phenomenon, but no regex can tell `Balding` the nickname from `Balding`
the surname.

**N3 — ungated bias tables.** The two bias tables in `pages/8_Officials.py`
list any referee with two calls on a tag. They get the same
`RATING_MIN_GAMES` gate and the same live-call pool.

## 9. Components

| unit | responsibility | depends on |
|---|---|---|
| `_live_foul_events(events)` | foul rows minus strategic and garbage | `late_game`, `runs.GARBAGE_MARGIN` |
| `_share_z_by_game(live, crew)` | `{off_pk: {game_id: z}}` binomial deviation | crew sizes |
| `_env_residuals(games, poss)` | team-adjusted game-foul residual per game | team baselines |
| `official_ratings(...)` | assembles the score, gates the pool | the three above |
| `pages/8_Officials.py` | renders rating + descriptors, gates bias tables | `official_ratings` |

## 10. Testing

- `_live_foul_events` drops exactly the strategic and garbage rows on a fixture
  game and nothing else.
- Share z is 0 when a referee calls exactly fair share; positive above; the
  90%-of-25 case reproduces +6.01 within tolerance.
- Crew size is respected: the same 40% share scores ~0 on a 3-crew and clearly
  positive on a 6-crew.
- The worst-game term: a referee with one extreme game and two neutral rates
  meaningfully below a referee whose games are all mildly high with the same
  mean.
- Credit asymmetry: a far-below-fair-share referee lands above 50 but below the
  worst penalised referee.
- `RATING_MIN_GAMES`: a 2-game referee has `rating is None` and appears in no
  bias table.
- Placeholder names are absent from the rated pool but still counted in crew
  size.
- Both suite halves: `python tracker/run_all.py` and `python -m pytest tracker/`.

## 11. Out of scope

Deliberately not in this change, and queued behind it: cross-state badge
collision (`UNIQUE(official_id, state)`), offline quick-add, iPad Mode, and the
`stats._team_game_ids` rollover trap.
