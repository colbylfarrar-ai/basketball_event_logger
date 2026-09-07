# Team read — one place for the whole team's tendencies

**Date:** 2026-09-07
**Status:** approved (founder, this session)
**Home:** Insights → "Who we are", second block, directly under the DNA verdict.

---

## The ask

> *"Team insights … shows any major TEAM reads, such as, plays zone against
> BLOB, runs man more in the 4th quarter, or any other team style insights. I
> think they are in other places, but coaches want to look in one place and get
> a full read of insights on the entire team with tendencies."*

Two separate problems sit behind that sentence, and only one of them is a
consolidation.

**The consolidation.** The team miner (`helpers/team_insights.py`, 24
generators) already runs on every Insights render, and its lines already reach
the tab. But `insights_severity.METRIC_SECTION` routes each one by metric, so
the team story is split across "Who we are", "Why we win / why we lose" and
"What they'll take away". No screen holds it whole.

**The genuine gap.** The two examples the founder gave are not consolidation
problems at all:

* *"plays zone against BLOB"* — `helpers/scheme_situational.py` computes exactly
  this. Its own docstring uses the founder's phrasing. It renders **only** on
  Team Dashboard → Play Style and → Defense, via
  `helpers/dashboard/scheme_section.py`. It has never reached Insights.
  `scheme_situational.verdict_lines` is on the standing list of prewritten
  coach-speak the Insights deck does not use.
* *"runs man more in the 4th"* — **not computable today.** That module's cuts
  are `after_run`, `own_run`, `deadball`, `margin_*` and `clutch`. A quarter cut
  was deliberately omitted.

And separately: quarter analysis is the single largest content gap on Insights.
Charts → Quarters carries four sub-tabs; Insights carries zero quarter reads
beyond the foul-trouble lines at `insights_deep.py:561`.

---

## Decisions taken

| # | Decision | Rejected alternative |
|---|---|---|
| 1 | The block lives in **"Who we are"**, not "Who's helping" | "Who's helping" is the player section by authored design; the section list is cut by the question a coach asks, and "what kind of team is this" is already section 1's question |
| 2 | Scope is **port + quarter cut + roll-up + quarter analysis** | Porting `scheme_situational` alone would leave "man in the 4th" readable only as *clutch* |
| 3 | Renders **eagerly**, no opt-in expander, no perf budget | Founder ruled. The cold delta still gets measured and reported — it just does not gate the merge |
| 4 | Position: **second, under the DNA verdict** | `insights_identity`'s ordering rule is stated in its docstring — "a coach who stops reading after two blocks should still have the answer" — and the plain-word identity read is that answer |
| 5 | The roll-up carries only team lines whose home section is **not** `S_IDENTITY` | Lines homed here already render in this section's own feed; including them would print the same sentence twice on one screen |

---

## Architecture

```
Insights → "Who we are"
  ├─ DNA verdict                        (unchanged)
  ├─ TEAM READ                          ← new
  │    ├─ Tendencies — defense          scheme_section.render(ctx, "defense", …)
  │    ├─ Tendencies — offense          scheme_section.render(ctx, "offense", …)
  │    ├─ Quarter read                  quarters.quarter_verdict(qbx)
  │    └─ Everything else we know       roll-up over family == "team"
  ├─ Efficiency quadrant                (unchanged)
  ├─ Winning formula                    (unchanged)
  ├─ Adjusted shooting · Spacing        (unchanged)
  └─ Section feed                       (unchanged)
```

### Files

| File | Change |
|---|---|
| `helpers/scheme_situational.py` | Add a `quarter` cut. Four `_add("q{n}", …)` calls over `sit["q"]`, gated by the existing `MIN_CUT_POSS` / `MIN_DELTA`. Rewrite the docstring paragraph that records the omission so it records the reversal instead |
| `helpers/quarters.py` | **NEW** engine. `quarter_verdict(qbx)` → house verdict-line shape from `team_analytics.quarter_boxes`. Streamlit-free, like `stops.py` / `runs.py` / `winning_formula.py`. Not added to `team_analytics.py`, which is already 2,024 lines |
| `helpers/dashboard/insights_team_read.py` | **NEW** renderer. Pure, ctx-driven. Calls `scheme_section.render` twice rather than reimplementing a spike renderer |
| `helpers/dashboard/insights_identity.py` | Call the new block between `_dna_verdict` and `_quadrant` |
| `pages/6_Team_Dashboard.py` | `_insights_ctx` gains `scheme_sit` and `quarter_read` binders. It has neither today; `_def_ctx` and `_ps_ctx` already bind `scheme_sit=_LGBIND(_scheme_sit_view)` |
| `helpers/insights_severity.py` | Register the new metrics in `METRIC_SECTION` and `METRIC_EVIDENCE`. `tracker/test_insights_severity.py` fails if a miner emits a metric with no section or no evidence destination |

### Game-window scoping

`_scheme_sit_view(g, tid, side, game_ids=None)` falls back to the whole season
tracked pool when `game_ids` is None. The Insights deck's game-window control is
a **cache-key input, not a post-filter** — every other wrapper on the tab takes
the narrowed `tracked_ids` as part of its key. This block passes
`sctx.tracked_ids` for the same reason: a block that silently ignores a window
the rest of the tab honours is a block a coach stops trusting.

### Reversing the quarter-cut omission

The omission was reasoned, and the reason was partly right:
`situational.team_situational` really does carry `q1`–`q4` lenses. What it
yields is four-factor **cells** — usage and efficiency per (situation × tag),
gated at `SIT_MIN_POSS`. What it does not yield is a **spike verdict**: "man
jumps to 74% of possessions in Q4 against a 51% season baseline". The verdict
shape is the thing missing, not the slice, and `scheme_situational` is where
verdict shapes live. The docstring records this rather than dropping the
sentence, so a future sweep does not "fix" it back.

---

## Testing

Test-first, per house rule.

* `tracker/test_scheme_situational.py` — extend. A fixture whose scheme mix is
  flat across Q1–Q3 and spikes in Q4 must produce a `q4` cut; one that is flat
  everywhere must not. Confirm the new assertions fail before the cut is added.
* `tracker/test_quarters.py` — **new.** `quarter_verdict` on a synthetic
  `quarter_boxes` dict: a team that is +8/game in Q1 and −6/game in Q3 gets both
  lines and neither is invented when the quarter never reached a real sample.
* `tracker/test_insights_severity.py` — already fails on an unregistered metric;
  it is the gate for step 6 above, not a new test.
* Seeded fixture games get **distinct dates** — `game_dedup` collapses
  same-date same-matchup rows, and a fixture that ignores that is testing the
  deduper.

Both suites run before this is called done: `pytest tracker/` and
`tracker/run_all.py`. Pytest green is not the suite green.

---

## Out of scope

* Charts → Quarters keeps its four sub-tabs and its Plotly panels. This block
  ports the **verdict**, not the charts — Insights is a prose surface.
* No re-routing of `METRIC_SECTION`. Existing team lines keep their homes; the
  roll-up mirrors them, the way `insights_identity` already mirrors Lab and
  Charts content ("a copy, gathered around one question instead of scattered
  across three").
* Entitlement is inherited, not re-decided. The block sits inside the Insights
  deck and is gated exactly as the rest of the deck is.
