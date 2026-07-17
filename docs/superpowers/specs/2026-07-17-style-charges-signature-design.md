# Style charts, scheme situationals, signature stats, rebound maps, charges

Date: 2026-07-17
Status: approved (brainstormed with founder 2026-07-17, implemented same night)

Five tasks, in the founder's priority order. A sixth (live tracker roster sync)
was considered and **dropped** — the existing identity/merge path already syncs
renamed players after the fact, and live re-resolution risks mis-attributing
events during a game for no real gain.

---

## Task 1 — Rankings: cross-team style charts

### Problem

`_fx_chart()` (`pages/5_Rankings.py:1409`) is the league's "Team Charts" view:
one sorted bar per team over box-score metrics, with a `chart_team_filter`
multiselect that trims which teams appear. It is a single undifferentiated
scroll, and it has **no play-style or defensive-scheme content at all** — the
`playtypes.py` (13 named set calls + inferred tempo/creation) and `defenses.py`
(17 schemes) engines exist but are wired only into the Team Dashboard.

### Decision

Port the **Team Dashboard Charts skeleton, not its bodies.**

The two pages answer different questions. Dashboard Charts is one-team-deep
(percentile bars, fingerprint cards). Rankings Team Charts is cross-team (one
sorted bar per team). The chart code cannot be shared. What ports is the *tab
structure*, so muscle memory transfers between pages:

| Story | Sub-tabs | Content |
|---|---|---|
| Offense | Scoring · Shooting · Playmaking | today's box-score wall, split up |
| Play Style | — | PPP by set call, style mix, tempo mix, creation mix |
| Defense | Team Defense · Scheme · Glass | opp box stats; scheme PPP; rebound maps |

Situational, Trends and Quarters are **not** ported — they are single-team reads
by nature and their cross-team analog is thin (and Trends duplicates the
sparkline already in the rankings table).

Every body is cross-team sorted bars. The `chart_team_filter` multiselect trims
graphs; tables always show the full league.

### Structure

Top level uses a **segmented control**, not `st.tabs` — `st.tabs` computes every
tab body on every rerun, and the style pack makes bodies heavy. Nested sub-tabs
inside a story may use `st.tabs` (cheap bodies, one pack already in hand).

### Engine

`playtypes.team_named_playtypes` and the `defenses.py` equivalents are per-team.
A league loop is N teams x a heavy engine. Both accept an `events` param, so:

- New `league_analytics.team_style_pack(gender, season)` — **one** event fetch,
  loop tracked teams passing the same events, cache the whole result. Sits next
  to the existing `team_tracked_pack` and follows its cache contract.

---

## Task 2 — Scheme / style situational insights

### Problem

The dashboard shows scheme usage as a flat season %. The data supports the far
better question: *where does a scheme spike relative to that team's own
baseline?* ("plays zone to stop a run", "man against BLOB").

Separately: `lineups.player_on_off` already returns `on_drtg` / `off_drtg` /
`def_diff`, but the insight generator `_g_onoff` (`helpers/insights.py:771`)
reads only `off_diff`. **The defensive half is computed and thrown away.**

### Decision

New `helpers/scheme_situational.py`. For each cut, compare scheme (and set-call)
usage rate within the cut against the team's own baseline rate; flag spikes past
a threshold, gated on a minimum possession count.

Cuts (founder-selected):

1. **After a run against them** — possessions following 6+ unanswered by the
   opponent. Crosses `runs.py` with `defenses.py`.
2. **Dead-ball sets** — `play_type IN (blob, slob)` crossed with `defense`.
   Both directions: what scheme they sit in on inbounds, and what sets they call
   against each scheme.
3. **Score margin & clutch** — scheme mix by margin bucket and by late clock.

Quarter/period openers were **explicitly not selected** despite being cited as a
motivating example ("zone to open the 3rd"). Left out; cheapest to add later
since `situational.py` already slices by quarter.

Rendering: verdict lines in the existing `defense_tab.py` and `playstyle_tab.py`
(verdict-first, matching the Insights tab house style).

Defensive on/off: add a `_g_onoff_def` generator alongside `_g_onoff`, reading
`def_diff`. One generator, no engine work.

---

## Task 3 — Signature stats: widen the pool, de-correlate

### Problem

`winloss_alignment` (`helpers/insights_team.py:415`) ranks stats by effect size
to find what separates a team's wins from losses. Its candidate pool `_WL_SPEC`
(`insights_team.py:362`) is **12 box-score keys only**. PPP and oPPP dominate the
output — partly low sample, but also because the pool is narrow and the tiles
end up being four flavors of the same underlying signal.

### Decision

Two changes:

1. **Widen the pool.** Add ~15 keys to `team_stat_line` + `_WL_SPEC`: shot
   creation rate, SC%, AST/TOV, transition rate, halfcourt PPP, best/worst
   scheme PPP allowed, run differential, charges drawn, paint rate, rim rate.
   A signature stat can now be any stat, not just a box-score metric.

2. **De-correlate.** After effect-size ranking, walk the ranked list and compute
   pairwise correlation across the per-game series. When two stats correlate
   above ~0.8, drop the lower-|d| one. This is what stops "we shoot well when we
   win" from filling all four tiles as eFG, TS, PPP and 3P%.

---

## Task 4 — Rebounding shot maps by play type / scheme

`court.shot_map_grouped(shots, group_key="play_type")` already exists — this is
mostly wiring.

Filter shots to those carrying a `rebound_by_id`, split ORB vs DRB, render in:

- `playstyle_tab.py` — grouped by set call
- `defense_tab.py` (Glass) — grouped by scheme

Lands in both the Team Dashboard tabs and, via Task 1's skeleton, the Rankings
Defense → Glass story.

---

## Task 5 — Charges

### Detection

A charge is a **`foul` event with `play_type='other'` AND `defense='other'`.**

A charge is logged as a turnover *and* a foul (like an and-one is a FT after a
made shot). The turnover is logged normally; **the foul is the key**, because it
carries the `other`/`other` tag pair. Timestamp-pairing a foul to a turnover is
NOT a valid discriminator — `play_type` and `defense` are nullable by nature and
routinely go unpopulated, so only the explicit `other`/`other` pair identifies a
charge unambiguously.

Foul-event semantics (`helpers/fouls.py`): `primary_player_id` = the player
fouled, `secondary_player_id` = the fouler.

- **Charge drawn** = `primary_player_id` (the defender who took it)
- **Charge committed** = `secondary_player_id` (the offensive player)

### Engine

New `helpers/charges.py`: `is_charge(e)`, team rollups (drawn / committed),
player rollups. Streamlit-free, pure python + sqlite, matching the house engine
convention.

### Ratings

Drawing a charge earns **defensive credit only.** The offensive player who
committed it is already penalized twice — the turnover hits his TOV rate, and
the personal foul charges to the fouler (`secondary_player_id`), which is
already correct in `stats.py`. A third penalty would triple-count one play.

A charge is a discrete defensive event like a steal or block — neither rim nor
perimeter specifically. So it enters `_DEFENSE_PARTS` as its own small-weight
leaf, **not** inside `_RIMDEF` / `_PERIMDEF`.

### The zero-vs-None trap

The rating system is None-tolerant: a missing stat drops out of the weighted
mean rather than counting as 0. **That protection does not apply here.** Charge
tagging is opt-in and rare, so most players have a *genuine* 0, not a None — and
a real 0 pulls their z down. If charges are tagged in some games and not others,
players from untagged games get penalized for tagging gaps rather than for their
defense.

Mitigation: the `CHG/G` leaf returns **None for any player whose team has zero
tagged charges in the pool.** Untagged teams drop the leaf entirely instead of
eating a zero; teams that do tag it get their real rate.

### Blast radius

This is the only change that moves existing numbers: every DEFENSE and OVERALL
rating on the site shifts. Run a before/after ratings diff and report the spread.

---

## Verification

Per-task AppTest smoke check (no-secrets cwd bypasses auth; seed `ta_team=1` +
`ta_season=2025-2026`). Engine changes get unit tests alongside the existing
`tracker/test_*.py` suite. Task 5 additionally requires the ratings diff.

Deploy: each task commits + pushes + deploys once its checks pass. A task that
fails stays uncommitted and gets reported rather than forced through.
