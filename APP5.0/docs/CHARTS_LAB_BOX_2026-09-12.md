# Charts · Lab · the box score — the scrub, the plan, and what shipped

Written 2026-09-12 against `~/app5_prod/analytics.db` (production, pulled 09:23
the same morning — 63 tracked games, 43 of them on the girls' book). Everything
measured here was measured by rendering the real page headlessly against that
copy, not by reading the source and guessing.

Three surfaces were in scope, named by the founder:

* **Team Dashboard → Charts** — 7 top sections, 14 leaves, ~89 plots
* **Team Dashboard → Lab** — 3 sections, one of them 3 deep
* **The in-app box score** (`helpers/box_score.py`, 1,976 lines, 4 callers)

The benchmark was named too: *Insights is the standard; the player profile and
the scout sheet are right; Overview is good and open to change.* So this is not
a taste exercise. Those three surfaces already agree on a shape, the founder has
endorsed it twice, and the job is to find where these three do not follow it.

---

## 0 · The one sentence

**Insights, Scout and the player profile lead with a sentence and put the chart
underneath it. Charts, Lab and the box score lead with the chart.** Where they
do lead with a sentence — Stops, Trends, Scoring, Shot Profile, Efficiency & DNA
— they are as good as the benchmark. Where they do not, the coach is handed 35
plots and asked to do the reading.

Everything below is a consequence of that, or a lie the navigation tells on the
way there.

---
