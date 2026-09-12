# Scout · Player Profile · Printables — build log (2026-09-11)

Ordered as asked: scout sheet, then player profile, then printables aligned to
the screens they represent. Six commits, all on `main`, **unpushed and
undeployed**.

| | |
|---|---|
| Commits | `07f5d8d` · `2dce9aa` · `556f712` · `b979caa` · `ba606e5` · `859dd0d` · `3b73fae` |
| Suites | 99/0 script tests · 476 pytest, green after every commit |
| Verified against | `~/app5_prod/analytics.db` (63 tracked games), headless AppTest |
| Source docs | `SCOUT_TAB_ROADMAP_2026-09-09.md`, `PLAYER_PROFILE_SCRUB_2026-09-09.md` |

---

## 1 · Scout sheet

### Phase 1 — the print pass (`07f5d8d`)

The roadmap's three layout bugs, all real:

* `.wrap` was 840 CSS px = **8.75in** against **7.7in** of printable width, so
  every portrait print was shrink-to-fit and the overflow came out of the
  content. The wrap is the paper now, in inches.
* `@page` never named a size. Portrait was assumed, never chosen.
* Compact mode flowed only the middle third of the document; the blocks before
  and after it — the page hogs — were never touched by it.

Layout is one decision now (page + column count): **Portrait 1-col / Portrait
2-col / Landscape 3-col**. Everything table- or text-shaped flows; only blocks
with their own grid (personnel cards, courts, saved plays) sit outside and set
their own N-up from the same layout. xhtml2pdf ignores `column-count` but honours
`@page size`, so landscape degrades to one wide column rather than breaking.

**Three sections deleted, no numbers lost** — and deleted from the *tab* as well
as the sheet:

| Deleted | Because |
|---|---|
| Efficiency summary | ORtg/DRtg/Pace are the band chips and the tab's header metrics; eFG/TOV%/OREB% are four-factor rows and snapshot tiles. Six numbers, in prose, twice. |
| Auto scouting report | A second rule-based bullet list, from a second code path, printed directly under Guard/Attack, reading the same inputs at different thresholds — free to contradict the first list on the same page. Its tips are sided and merged into Keys. |
| Zone shooting vs expected | Same five zones as Shooting by zone with different columns. The xFG deltas are the (±) inside that one table. |

Also: blank courts became a setting (0/2/4/8, was hard-coded at 8 ≈ a full page);
the four shot-chart grid sections became one "shot wall" with a coach-picked
split capped at 6 courts; personnel cards went to a fixed five-line shape with an
optional deep-card appendix, 3-up in landscape.

**Sections carry two flags now — screen and paper.** One flag gating both is why
"more depth on the tab" and "fewer printed pages" read as opposing goals. The
pre-split key seeds both on first read. The ⚙ panel shows a live page estimate in
its header and ships three presets.

Measured: `estimate_pages` puts "everything" at **3.0pp** portrait-2-col,
**2.2pp** landscape-3-col, **0.7pp** for the Bench card preset.

Two bugs found in passing: `scout_compact` was never in `USER_SCOPED`, so one
coach's layout choice changed it for the whole program; and the cold-opponent
branch had a second `printable_html` call site, so every change to the sheet had
two places to keep in sync.

### Engines aimed at the opponent (`2dce9aa`)

New `helpers/dashboard/scout_deep.py`. **It computes nothing.** Insights runs
thirteen ported engines as a self-scout; Scout rebinds its whole ctx onto the
opponent, so the identical call answers the opposite question — and the tab was
not making it.

* **`exploit.game_plan`** — our set-call efficiency × their vulnerability to the
  same set, plus what to play on D. The most scout-shaped engine in the codebase,
  living only in the War Room.
* **Foul clock, run anatomy, giveaway mix, glue/involvement, vs-schemes, ball
  share, stops, rebounding identity, runs, possession ledger** — eleven ported
  reads, opponent-framed. Monday, Receipts and `deserved` do **not** port; they
  are self-scout by construction.
* **`exploit.defender_profiles`** — what YOUR defenders actually allow on shots
  they contested, as the honest second opinion on the matchup planner's
  rating-based edges.
* **`quick_view` on every personnel card** — the full 30-block player card in a
  modal, one click, no page switch. This is the reconciliation of "I love how
  much information is on the sheet" with "I don't want four pages".
* **Foul clock + last-5 form per opponent player**, on the tile and on the paper.

`_opp_scout_ctx` was a 13-field namespace, so every one of these would have been
a rewrite. Widened with the opponent's read-filtered pool, tracked ids, stat
table, zone tables, badges and a bound card opener — entitlement threaded into
every new field, and an **empty** pool stays empty rather than widening to None.

**Keys are ranked by effect size**, not by the order the `if`s appear in the
source. Each key carries the league percentile of the quantity it fired on;
tag-derived keys carry their possession count. Bands never interleave, the same
rule `insights_severity` follows.

### One open section instead of thirty-five (`556f712`)

`render(ctx)` was correctly an `@st.fragment` and then rendered every one of its
~35 blocks linearly on every rerun. Seven lazy sections behind `_UI.seg`, along
the dividers the tab already drew. AST-swept first; four real leaks found and
fixed (`pandas` imported in one section and used in three, `_tips` and the
exploit plan computed in one section and read by the printable, `_zxfg` computed
twice).

The printable's `extra` block is a **callable** now. It used to be assembled on
every rerun for a document nobody had asked for — and it is the expensive half: a
league xPP-Q model fit, every saved play re-rendered to SVG, thirteen engines
walked.

Plus the **one-page call sheet** (roadmap Part 2): the plan, five ranked keys a
side, who guards whom, one line per opponent player, their three go-to sets, the
defenses to show them, the breakeven number. 9.6KB — genuinely one page.

---

## 2 · Player Profile card

### The cuts and the two bugs (`ba606e5`)

OVERALL appeared four times, the per-game line four times, last-5-vs-season three
times in three styles, and the same points series was charted twice with a
different smoother forty lines apart. Twelve consolidations; the 21-row
percentile rail (copy-pasted verbatim into the paid and free renderers 890 lines
apart) became one module constant.

Two real bugs: the game log resolved opponents against the **current roster row**
(so a transferred player's archive log named her old team as the opponent), and
`home_score`/`away_score` were SELECTed and discarded — no result column at all.

### Verdict first, sections lazy, engines imported (`859dd0d`)

* **The verdict was last** — after roughly twenty screens of tables. It is §0
  now, directly under the fold.
* **The feed was capped at 3.** `helpers/insights` holds 39 player generators;
  the card called `build_feed(top=3)` and printed them in a grey box at the
  bottom. Uncapped and run through `insights_severity.rank()`. Measured on the
  prod snapshot: **mean lines/player 2.1 → 3.8, max 3 → 12.** Plus a Monday list
  and an expander with every remaining line.
* **Three archetype labels disagreed in public.** The eleven-branch if/elif
  ladder is demoted to the one case it is good at — naming a role when the
  cluster has nothing to group her on — and says so on screen.
* **26 eager sections, zero controls** → six lazy sections cut by the question a
  coach asks. AST-swept; every block reads only names bound in the fold.
* **Four engines imported**: who she guarded (shot by shot) + assignment
  difficulty, who guarded *her* (the same table inverted, on no surface before),
  her giveaway mix, and on/off **scoring** — the section carried rebounding and
  AST/TOV and had no scoring in it.

---

## 3 · Printables

### Ink (`b979caa`) — added mid-session at the founder's request

Every hand-out prints black-and-white on line work. Gone: the full-bleed gradient
masthead with its 5px gold rule (the single most expensive object in any of these
documents, repeated on all of them), zebra striping, filled tiles/badges/cards,
and the usage heat map's cell-by-cell colour ramp — which cost the most ink and
said the least, since on a mono laser the whole gold-to-orange ramp collapsed
into four indistinguishable greys. Intensity is carried by **weight and size**
now, which reads the same in colour, greyscale and photocopy.

Colour no longer carries meaning anywhere: percentile bars mark direction with
▲/▼, and shot charts separate a make from a miss by **fill** (solid dot vs open
ring) instead of green-vs-red. A blank court measures **1.17% dark pixels and
0.000% chromatic**; seventeen shots add 1.6 points.

**One filled background remains across all five documents** — the percentile bar,
and it is the number.

Two alignment bugs went with it: only the scout sheet ever declared an `@page`,
and the shared wrap was 920px (9.6in) against 7.7in of paper. Both live once now.
The matchup one-pager is finally on the shared chrome — it hand-rolled its own
720px stylesheet with no masthead and its own gold brand bar, which is why it was
the one printable that never looked like the others.

### Parity (`3b73fae`)

* The printed player card leads with the same verdict the screen does.
* `trends.player_game_log` had the same transfer bug and no result; both fixed,
  so the printed "Recent games" has W/L and margin.
* The scout sheet's personnel cards carry the foul clock and form lines the tab
  shows.
* The game recap was two different documents — the box-score mount had a section
  picker, the Game Tracker mount printed everything. Same picker in both.

---

## Not done, and why

1. **The profile's game-window control** (scrub build step 6). Every cached read
   on the card takes `game_ids`; narrowing that pool narrows the **league
   percentile pools** with it, and "78th percentile among everyone's last five
   games" is a different and much stranger claim than the bars make today. It
   needs the per-player reads scoped separately from the ranking pool — its own
   change, not the tail end of this one.
2. **The scrub's exact §1–§7 section names** for the profile. The six shipped
   sections merge the proposal's §2 into §1/§3 and keep the strengths/watch prose
   as its own section, so the split stayed contiguous-plus-one-hoist rather than
   a full reorder. Same for Scout: seven sections along the dividers a coach
   already sees, rather than the roadmap's proposed six.
3. **Chemistry / best-worst partners** on the profile (scrub 2.2, last item).
   `networks.chemistry_network` is ~16.5s and sits behind an opt-in button on
   Insights for that reason; it needs the same gate here and did not get built.
4. **Charts-tab ports to Scout** (roadmap Part 10 Tier A): opponent shot profile
   "where they force shots", Winning-Formula suppressors, Team DNA rail, Shot
   Lab, putbacks, top-half/bottom-half. The masthead carries a strongest/softest
   identity line off the four-factor profile instead.

## Liberties taken

* **Ink is global, with no toggle.** The ask was unambiguous, so there is no
  "branded colour" mode left for e.g. a recruiting-facing player card. One flag
  in `printouts.BASE_CSS` would restore it if you want the option.
* **`POOL_FLOOR` and `rank_from_pctile` moved** from `helpers/cards` to
  `helpers/stats` (Streamlit-free) so the engine-layer printable and the
  display-layer card cannot state different pools. `cards` re-exports both, so
  every existing reader — including `tracker/test_pctile_pool.py` — is untouched.
* **`scout_compact` and six new scout keys added to `USER_SCOPED`.** `compact`
  was global by omission; this changes behaviour for anyone who had set it.
* **Section deletions are from the tab as well as the sheet.** The roadmap only
  asked for the sheet; a printable that does not match its screen is its own bug,
  and that was the third item on the list anyway.
* **`build_feed`'s `top=3` default is unchanged**; only the card passes
  `top=None`. Nothing else moved.
* **A session doc** (this file) was written without being asked for.

## Next

* Push and deploy — neither was done. `git log origin/main..HEAD` is 7.
* The window control (1 above) is the biggest remaining profile item.
* Roadmap Part 10 (Charts → Scout) is untouched and is where the next real depth
  is.
