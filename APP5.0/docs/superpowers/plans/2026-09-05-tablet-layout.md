# Tracker Tablet Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the basketball tracker log an entire game on an iPad mini 6 in landscape without scrolling, in quick mode and in full detail, while leaving the phone layout byte-identical.

**Architecture:** Replace the current per-element `grid-column` assignments with three wrapper elements (`.col-left`, `.col-right`, `.tracker-cold`) that are `display: contents` on a phone and real flex columns on a tablet. A single `html.is-wide` class, computed once in JS, drives every wide rule — today the same rules are duplicated between a media query and a `.force-wide` class. Hot controls (court, tag bars, flow, score, clock, undo) live above the 744px fold; rare controls (timeouts, edit log, end game, play-by-play) live below it.

**Tech Stack:** Vanilla JS, hand-written CSS, no build step. Files are served directly by the FastAPI tracker (`APP5.0/tracker/`). Python 3.13 + pytest for the guard test.

**Spec:** `APP5.0/docs/superpowers/specs/2026-09-05-tablet-layout-design.md` — read it first. It carries the measured height budget this plan is built on.

## Global Constraints

- Target viewport: **1133 × 744 CSS px** (iPad mini 6, landscape, installed PWA — no browser chrome). Must also be correct at 1180 × 820 and 1366 × 1024.
- **The narrow/phone layout must not change.** Any difference in element order or `offsetTop` at 390 × 844 is a bug.
- Do not modify `selRow`, `playerOpts`, or the `<optgroup>` team grouping inside the detail dropdowns.
- Do not modify `APP5.0/tracker/api.py`, the event model, or any Streamlit page. This is `tracker/static/` plus one test file.
- `display: contents` requires Safari 15+ / iPadOS 15+. That is below the floor an installed PWA already needs. Do not put a landmark role on the wrappers.
- Every wide-mode CSS rule keys off `html.is-wide` and nothing else. No new `@media` blocks for layout, no new `.force-wide` / `.force-narrow` rules.
- Bump `CACHE` in `tracker/static/sw.js` exactly once, in the final task.
- Run `python -m pytest tracker/` from `APP5.0/`. It is 256 passed on `main` as of 2026-09-05; it must stay 256+ with no failures.

---

### Task 1: Collapse wide-mode detection into one `is-wide` class

Today the tablet rules are written twice — once under `@media (min-width: 768px) html:not(.force-narrow)` and once under `html.force-wide`. Every rule this plan adds would have to be written twice too. Compute the effective mode once in JS instead.

**Files:**
- Modify: `APP5.0/tracker/static/app.js` (the `applyWideMode` function, ~line 49)
- Modify: `APP5.0/tracker/static/style.css` (the "Tablet layout" block, ~lines 630-685)

**Interfaces:**
- Consumes: nothing.
- Produces: `html.is-wide` — present exactly when the tracker should use the tablet layout. Every later task styles against `html.is-wide <selector>`. Also `wideMode()` returning `'auto' | 'on' | 'off'`, unchanged.

- [ ] **Step 1: Read the current implementation**

Run: `sed -n '40,60p' APP5.0/tracker/static/app.js`

You should see `wideMode()` reading `LS.wideMode` with an `'auto'` default, and `applyWideMode()` toggling `force-wide` / `force-narrow` on `document.documentElement`.

- [ ] **Step 2: Rewrite `applyWideMode` to also set `is-wide`**

Replace the existing `applyWideMode` function with:

```javascript
// The tablet breakpoint, in one place. `auto` asks the viewport; `on`/`off` are
// the coach's override from Bench setup, because the query alone guesses wrong
// in both directions -- a phone in landscape measures wide, an iPad in a Split
// View pane measures narrow.
const WIDE_QUERY = '(min-width: 768px)';

function wideActive() {
  const m = wideMode();
  if (m === 'on') return true;
  if (m === 'off') return false;
  return window.matchMedia(WIDE_QUERY).matches;
}

function applyWideMode() {
  const r = document.documentElement;
  const m = wideMode();
  // force-wide / force-narrow stay on the element: they are what the Bench
  // setup selector reflects, and .screen max-width still keys off them.
  r.classList.toggle('force-wide', m === 'on');
  r.classList.toggle('force-narrow', m === 'off');
  // is-wide is the single class every tablet layout rule uses.
  r.classList.toggle('is-wide', wideActive());
}
```

- [ ] **Step 3: React to rotation and Split View resizes**

`auto` mode must re-evaluate when the viewport changes. Find the line `applyWideMode();          // before first paint, so the layout never flips` (~line 3075) and add immediately after it:

```javascript
// An iPad rotated mid-game, or dragged out of Split View, changes the answer.
window.matchMedia(WIDE_QUERY).addEventListener('change', applyWideMode);
```

- [ ] **Step 4: Point the existing wide CSS at `.is-wide`**

In `style.css`, replace this block:

```css
@media (min-width: 768px) {
  html:not(.force-narrow) .screen { max-width: 1180px; padding: 16px; }
  html:not(.force-narrow) #screen-tracker:not([hidden]) { display: grid; }
}
html.force-wide .screen { max-width: 1180px; padding: 16px; }
html.force-wide #screen-tracker:not([hidden]) { display: grid; }

html.force-wide #screen-tracker,
html:not(.force-narrow) #screen-tracker {
  grid-template-columns: minmax(300px, 1.05fr) minmax(320px, 1fr);
  column-gap: 16px;
  align-items: start;
}
```

with:

```css
html.is-wide .screen { max-width: 1180px; padding: 16px; }
html.is-wide #screen-tracker:not([hidden]) { display: grid; }
html.is-wide #screen-tracker {
  grid-template-columns: minmax(300px, 1.05fr) minmax(320px, 1fr);
  column-gap: 16px;
  align-items: start;
}
```

- [ ] **Step 5: Delete the now-dead per-element column rules**

Still in `style.css`, delete these three rule blocks entirely — Task 2 replaces them with wrappers:

```css
#screen-tracker > #track-head,
#screen-tracker > #subs-panel,
#screen-tracker > #track-tip { grid-column: 1 / -1; }

#screen-tracker > #court-wrap,
#screen-tracker > #shot-caption,
#screen-tracker > #mode-row { grid-column: 1; }

#screen-tracker > #defense-bar,
#screen-tracker > #playtype-bar,
#screen-tracker > #flow-opts,
#screen-tracker > #flow,
#screen-tracker > #to-row,
#screen-tracker > #action-row,
#screen-tracker > #sync-status,
#screen-tracker > #coverage-badge,
#screen-tracker > #pbp-toggle,
#screen-tracker > #pbp { grid-column: 2; }
```

Keep `html.force-narrow .screen { max-width: 640px; padding: 12px; }` and `html.force-narrow #screen-tracker { display: block; }` — they are the override back to the phone column.

- [ ] **Step 6: Verify the class appears and tracks the viewport**

Start the preview: `preview_start` with `{name: "tracker"}` (`.claude/launch.json`, port 8500, cwd `APP5.0`, needs `uvicorn` and the localdev token).

Then `resize_window` to 1133 × 744 and run via `javascript_tool`:

```javascript
document.documentElement.classList.contains('is-wide')
```
Expected: `true`

`resize_window` to 390 × 844, then re-run the same expression.
Expected: `false`

- [ ] **Step 7: Commit**

```bash
git add APP5.0/tracker/static/app.js APP5.0/tracker/static/style.css
git commit -m "refactor(tracker): one is-wide class instead of two copies of every tablet rule"
```

---

### Task 2: Wrap the three groups, assign columns by wrapper

**Files:**
- Modify: `APP5.0/tracker/static/index.html` (the `#screen-tracker` section)
- Modify: `APP5.0/tracker/static/style.css`
- Test: `APP5.0/tracker/test_tablet_layout.py` (create)

**Interfaces:**
- Consumes: `html.is-wide` from Task 1.
- Produces: three wrapper elements — `.col-left`, `.col-right`, `.tracker-cold` — each holding a fixed set of ids. Tasks 3-6 style inside them.

- [ ] **Step 1: Write the failing guard test**

The real proof is browser measurement, but a cheap structural test catches someone later moving an id into the wrong wrapper. Create `APP5.0/tracker/test_tablet_layout.py`:

```python
"""The tablet layout depends on three CONTIGUOUS groups of elements in
index.html. If an id moves between groups the wide layout silently breaks --
an element lands in the wrong column, or a hot control drops below the fold --
and nothing else in the suite would notice. See
docs/superpowers/specs/2026-09-05-tablet-layout-design.md."""
import pathlib
import re

STATIC = pathlib.Path(__file__).resolve().parent / "static"

COL_LEFT = ["track-head", "subs-panel", "court-wrap", "shot-caption"]
COL_RIGHT = ["mode-row", "track-tip", "defense-bar", "playtype-bar",
             "flow-opts", "flow"]
COLD = ["to-row", "action-row", "sync-status", "coverage-badge",
        "pbp-toggle", "pbp"]


def _wrapper_body(html, cls):
    """The markup between <div class="cls"> and its matching close.

    The wrappers hold no nested <div class=...> siblings of their own at author
    time, so a non-greedy match to the next wrapper open (or </section>) is
    enough -- and is checked by the id assertions below anyway."""
    m = re.search(r'<div class="' + cls + r'">(.*?)\n  </div>', html, re.S)
    assert m, f"no <div class=\"{cls}\"> wrapper in index.html"
    return m.group(1)


def test_wrappers_hold_exactly_their_groups():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for cls, expected in (("col-left", COL_LEFT),
                          ("col-right", COL_RIGHT),
                          ("tracker-cold", COLD)):
        body = _wrapper_body(html, cls)
        found = re.findall(r'id="([\w-]+)"', body)
        got = [i for i in found if i in expected]
        assert got == expected, f"{cls}: expected {expected}, got {got}"
        # nothing from another group leaked in
        others = set(COL_LEFT + COL_RIGHT + COLD) - set(expected)
        assert not (set(found) & others), f"{cls} contains foreign ids"


def test_wide_rules_key_off_is_wide_only():
    """Every wrapper rule either is the one shared display:contents reset, or is
    scoped to html.is-wide. A wrapper rule that is scoped to neither -- say one
    left inside an `@media (min-width: 768px)` block -- would apply the flex
    column to a phone held in landscape, the one regression this layout must
    not have."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    reset = ".col-left, .col-right, .tracker-cold { display: contents; }"
    assert reset in css, f"missing the shared narrow-mode reset: {reset}"
    for m in re.finditer(r"^([^\n{]*\.(?:col-left|col-right|tracker-cold)[^\n{]*)\{",
                         css, re.M):
        sel = m.group(1).strip()
        if sel + " {" == reset.split("{")[0].strip() + " {":
            continue                      # the reset itself, intentionally global
        assert "is-wide" in sel, f"wrapper rule not scoped to html.is-wide: {sel}"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd APP5.0 && python -m pytest tracker/test_tablet_layout.py -v`
Expected: FAIL — `no <div class="col-left"> wrapper in index.html`

- [ ] **Step 3: Add the wrappers to `index.html`**

All three groups are already contiguous, so nothing moves — you are only opening and closing three `div`s. Inside `<section id="screen-tracker" class="screen" hidden>`:

1. Insert `<div class="col-left">` immediately before `<header id="track-head">`, and `</div>` immediately after `<p id="shot-caption" class="caption"></p>`.
2. Insert `<div class="col-right">` immediately before `<div id="mode-row">`, and `</div>` immediately after `<div id="flow"></div>`.
3. Insert `<div class="tracker-cold">` immediately before `<div id="to-row">`, and `</div>` immediately after `<ul id="pbp" class="pbp" hidden></ul>`.

Indent the wrapped children one extra level so the closing `\n  </div>` the test matches sits at two spaces. Do not reorder a single element.

- [ ] **Step 4: Make the wrappers vanish on a phone and become columns on a tablet**

In `style.css`, directly after the `html.is-wide #screen-tracker { ... }` rule from Task 1, add:

```css
/* The wrappers exist only to build the two tablet columns. On a phone they are
   display:contents, so their children lay out as direct children of
   #screen-tracker in DOM order and the narrow layout is bit-for-bit what it
   was before the wrappers existed. */
.col-left, .col-right, .tracker-cold { display: contents; }

html.is-wide .col-left,
html.is-wide .col-right {
  display: flex;
  flex-direction: column;
  min-width: 0;          /* let long team names ellipsis instead of widening */
}
html.is-wide .col-left  { grid-column: 1; }
html.is-wide .col-right { grid-column: 2; }

/* The cold band spans both columns under the fold. It is the only part of the
   tracker that is meant to need a scroll. */
html.is-wide .tracker-cold {
  display: block;
  grid-column: 1 / -1;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd APP5.0 && python -m pytest tracker/test_tablet_layout.py -v`
Expected: PASS, 2 passed

- [ ] **Step 6: Verify the phone layout did not move**

This is the regression gate. Before comparing, capture the baseline from `main`:

```bash
git stash && git switch --detach main
```

`preview_start` `{name: "tracker"}`, `resize_window` to 390 × 844, enter a game's tracker screen, then `javascript_tool`:

```javascript
[...document.querySelectorAll('#screen-tracker [id]')]
  .map(e => e.id + ':' + Math.round(e.getBoundingClientRect().top))
  .join('\n')
```

Save that output. Then:

```bash
git switch - && git stash pop
```

Reload and run the identical expression. Expected: **character-for-character identical**. Any drift means a wide rule leaked out of `html.is-wide` — fix it before continuing.

- [ ] **Step 7: Commit**

```bash
git add APP5.0/tracker/static/index.html APP5.0/tracker/static/style.css APP5.0/tracker/test_tablet_layout.py
git commit -m "feat(tracker): build the tablet columns from wrappers, not per-element grid rules"
```

---

### Task 3: Court on top, score and clock beneath it

**Files:**
- Modify: `APP5.0/tracker/static/style.css`

**Interfaces:**
- Consumes: `.col-left` from Task 2.
- Produces: the left column's final visual order. No JS surface.

- [ ] **Step 1: Reorder the left column and drop sticky**

Add to `style.css` after the Task 2 wrapper rules:

```css
/* Left column reads court -> caption -> subs -> score/clock. The score is a
   check that the tracker has not drifted from the scoreboard, not something
   read live, so it earns the bottom slot; the court earns the top one.
   Subs opens between them, under the court and above the score. */
html.is-wide .col-left > #court-wrap   { order: 1; }
html.is-wide .col-left > #shot-caption { order: 2; }
html.is-wide .col-left > #subs-panel   { order: 3; }
html.is-wide .col-left > #track-head   { order: 4; }

/* Sticky bought a pinned clock while the phone column scrolled. The wide hot
   zone never scrolls, so it buys nothing here -- and once the cold band below
   the fold is scrolled, a sticky header would detach and cover the court. */
html.is-wide #track-head {
  position: static;
  margin: 8px 0 0;
  padding: 6px 0 0;
  border-bottom: 0;
  border-top: 1px solid var(--edge);
}
```

- [ ] **Step 2: Verify the order on a tablet**

`resize_window` to 1133 × 744, then `javascript_tool`:

```javascript
['court-wrap','shot-caption','track-head']
  .map(i => i + ':' + Math.round(document.getElementById(i).getBoundingClientRect().top))
```

Expected: three ascending numbers, `court-wrap` smallest, `track-head` largest.

- [ ] **Step 3: Verify the court is the size the budget predicts**

```javascript
const r = document.getElementById('court-wrap').getBoundingClientRect();
[Math.round(r.width), Math.round(r.height)]
```

Expected: approximately `[556, 434]` (the spec's width-limited court at `aspect-ratio: 50/39`). Anything under 500 wide means the grid columns are not splitting as expected — stop and investigate before continuing.

- [ ] **Step 4: Commit**

```bash
git add APP5.0/tracker/static/style.css
git commit -m "feat(tracker): court on top of the left column, score and clock beneath it"
```

---

### Task 4: Promote Undo into the hot row

Undo is a mis-tap correction — it fires mid-possession, right after a bad tap. It is the one control from the rare list that is time-critical, so it moves into `#track-head` rather than below the fold with the timeouts.

**Files:**
- Modify: `APP5.0/tracker/static/app.js`
- Modify: `APP5.0/tracker/static/style.css`

**Interfaces:**
- Consumes: `wideActive()` from Task 1; `.col-left` / `.tracker-cold` from Task 2.
- Produces: `placeUndo()` — idempotent, safe to call on every layout change.

- [ ] **Step 1: Add the mover**

Move the existing element rather than cloning it: one button, one listener, no drift. Add to `app.js` next to `applyWideMode`:

```javascript
// Undo lives with the rare controls on a phone, but on a tablet it belongs in
// the always-visible header -- it is the fix for a mis-tap and has to be one
// tap away mid-possession. The ELEMENT moves; its click handler rides along.
function placeUndo() {
  const btn = document.getElementById('btn-undo');
  if (!btn) return;
  const head = document.getElementById('track-controls');
  const cold = document.getElementById('action-row');
  if (!head || !cold) return;
  const want = wideActive() ? head : cold;
  if (btn.parentElement === want) return;          // idempotent
  if (want === cold) cold.insertBefore(btn, cold.firstChild);
  else want.appendChild(btn);
}
```

- [ ] **Step 2: Call it wherever the layout can change**

In `applyWideMode`, add `placeUndo();` as the last line of the function body, after the `is-wide` toggle. `applyWideMode` already runs before first paint and on the `matchMedia` change from Task 1, so that is every path.

- [ ] **Step 3: Style it in the header**

Add to `style.css`:

```css
/* Undo sits at the right end of the header controls, visually separated from
   the quarter stepper it must never be confused with. */
html.is-wide #track-controls #btn-undo { margin-left: auto; }
```

- [ ] **Step 4: Verify it moves both ways and still works**

`resize_window` to 1133 × 744, then `javascript_tool`:

```javascript
document.getElementById('btn-undo').parentElement.id
```
Expected: `"track-controls"`

`resize_window` to 390 × 844, re-run.
Expected: `"action-row"`

Then at 1133 × 744, log a shot, tap the header Undo, and confirm via `read_page` that the play-by-play lost its last entry. A moved element keeps its listener — this check proves it.

- [ ] **Step 5: Commit**

```bash
git add APP5.0/tracker/static/app.js APP5.0/tracker/static/style.css
git commit -m "feat(tracker): Undo moves into the header on a tablet, where a mis-tap needs it"
```

---

### Task 5: Six detail rows, two columns of three

This is the change the height budget requires. A single stack of six needs 937px against the 744px an iPad mini has; two columns of three brings the right column to 718px.

**Files:**
- Modify: `APP5.0/tracker/static/app.js` (the `SHOT_DETAILS.forEach` block in `renderFlow`, ~line 2115)
- Modify: `APP5.0/tracker/static/style.css`

**Interfaces:**
- Consumes: `.col-right` from Task 2; `selRow` and `playerOpts` unchanged.
- Produces: a `div.detail-grid` wrapping the six `.sel-row`s inside `#flow`.

- [ ] **Step 1: Wrap the six rows in a container**

In `renderFlow`, replace:

```javascript
        // dropdowns, not sliding chip strips — five detail rows fit one screen
        SHOT_DETAILS.forEach(function (d) {
          wrap.appendChild(selRow(d[1], playerOpts(players), f.details[d[0]],
            function (id) { f.details[d[0]] = id; renderFlow(); }, { numeric: true }));
        });
```

with:

```javascript
        // dropdowns, not sliding chip strips. They go in their own container so
        // the tablet layout can run them two-up: six stacked rows need 438px of
        // the 744px an iPad mini has, and the tag bars and MAKE/MISS want more
        // than the 306px that would leave.
        const dgrid = document.createElement('div');
        dgrid.className = 'detail-grid';
        SHOT_DETAILS.forEach(function (d) {
          dgrid.appendChild(selRow(d[1], playerOpts(players), f.details[d[0]],
            function (id) { f.details[d[0]] = id; renderFlow(); }, { numeric: true }));
        });
        wrap.appendChild(dgrid);
```

Nothing else changes: `selRow` still builds the row, `playerOpts` still builds the `<optgroup>` per team.

- [ ] **Step 2: Two columns on a tablet, one on a phone**

Add to `style.css`:

```css
/* Two-up on every tablet size, not only where the height forces it: a coach
   who picks up a different iPad should not find the rows rearranged. */
html.is-wide .detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 10px;
}
html.is-wide .detail-grid .sel-row { margin-bottom: 8px; }
html.is-wide .detail-grid .flow-select { width: 100%; }
```

- [ ] **Step 3: Verify the reading order is down-then-across**

`resize_window` to 1133 × 744, enter a game, switch to full detail (`#quick-toggle`), tap the court, pick a shooter, then `javascript_tool`:

```javascript
[...document.querySelectorAll('.detail-grid .sel-row .chip-label')].map(e => e.textContent)
```

Expected, in DOM order: `["Pass from","Hockey assist","Set up by","Rebound by","Blocked by","Guarded by"]`. CSS grid fills across by default, so on screen the left column reads Pass from / Set up by / Blocked by and the right reads Hockey assist / Rebound by / Guarded by. That pairs each assist-type row with a defensive one, which is fine — do **not** add `grid-auto-flow: column` to force down-then-across, because it breaks the single-column phone fallback.

- [ ] **Step 4: Verify the team grouping survived**

```javascript
const s = document.querySelector('.detail-grid .flow-select');
[...s.querySelectorAll('optgroup')].map(g => g.label)
```

Expected: the two team names from the loaded game. If this returns `[]` the `playerOpts` grouping was damaged — revert and investigate.

- [ ] **Step 5: Commit**

```bash
git add APP5.0/tracker/static/app.js APP5.0/tracker/static/style.css
git commit -m "feat(tracker): shot detail rows run two-up on a tablet so full detail fits the screen"
```

---

### Task 6: Shooter chips become a wrapping grid of big targets

Quick mode leaves ~190px of headroom in the right column. Spend it on the control that is tapped most.

**Files:**
- Modify: `APP5.0/tracker/static/style.css`

**Interfaces:**
- Consumes: `.col-right` from Task 2. CSS only — `chipRow` is not touched.
- Produces: no JS surface.

- [ ] **Step 1: Wrap the chips instead of sliding them**

`chipRow` builds `div.chip-row > span.chip-label + div.chips`. On a phone `.chips` is a horizontally sliding strip. Add to `style.css`:

```css
/* Quick mode has ~190px spare in the right column. A sliding strip hides half
   the roster behind a swipe; a wrapping grid puts every jersey one tap away. */
html.is-wide #flow .chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  overflow-x: visible;
}
html.is-wide #flow .chips .chip {
  flex: 0 0 auto;
  min-width: 64px;
  min-height: 52px;
  font-size: 1rem;
}
```

- [ ] **Step 2: Verify the chips wrap rather than overflow**

`resize_window` to 1133 × 744, quick mode, tap the court, then `javascript_tool`:

```javascript
const b = document.querySelector('#flow .chips');
[b.scrollWidth <= b.clientWidth + 1, b.getBoundingClientRect().height]
```

Expected: `[true, <a height over 52>]` — `true` means nothing is hidden behind a horizontal scroll.

- [ ] **Step 3: Confirm the phone strip is untouched**

`resize_window` to 390 × 844, tap the court, re-run the same expression.
Expected: `false` for the first value — the phone still slides, which is correct at that width.

- [ ] **Step 4: Commit**

```bash
git add APP5.0/tracker/static/style.css
git commit -m "feat(tracker): shooter chips wrap into big targets on a tablet"
```

---

### Task 7: Prove the no-scroll claim, then ship

**Files:**
- Modify: `APP5.0/tracker/static/sw.js` (the `CACHE` constant)

**Interfaces:**
- Consumes: everything above.
- Produces: the shipped layout.

- [ ] **Step 1: Assert no page scroll in quick mode**

`resize_window` to 1133 × 744, enter a game's tracker in quick mode, then `javascript_tool`:

```javascript
const d = document.documentElement;
[d.scrollHeight, d.clientHeight, d.scrollHeight <= d.clientHeight + 1]
```

Expected: third value `true`.

If it is `false`, read the spec's height table and find which element exceeded its budget before changing anything — the most likely culprit is a tag bar wrapping to a third line, whose documented fallback is to cap the chip strip to one line with internal horizontal scroll.

- [ ] **Step 2: Assert no page scroll in full detail**

Toggle `#quick-toggle` to full detail, tap the court, pick a shooter so all six rows render, then re-run the Step 1 expression.
Expected: third value `true`. This is the tighter of the two cases — the spec predicts 718 against 744.

- [ ] **Step 3: Assert every hot element is above the fold**

```javascript
['court-wrap','shot-caption','track-head','mode-row','defense-bar',
 'playtype-bar','flow-opts','flow']
  .map(i => { const e = document.getElementById(i);
              return [i, Math.round(e.getBoundingClientRect().bottom)]; })
  .filter(([, b]) => b > 744)
```

Expected: `[]` — an empty array means nothing hot crosses the fold.

- [ ] **Step 4: Confirm the cold band is reachable and not clipped**

Scroll to the bottom and confirm via `read_page` that `#to-row`, `#action-row`, `#pbp-toggle` are all present and none is cut off. Expand play-by-play and confirm it renders.

- [ ] **Step 5: Re-check the larger iPads**

Repeat Steps 1-3 at 1180 × 820 and at 1366 × 1024. Both should pass with slack. Then `resize_window` back to `desktop` to clear the emulation.

- [ ] **Step 6: Run both halves of the suite**

Run: `cd APP5.0 && python -m pytest tracker/ -q`
Expected: 258 passed (256 on `main` + the 2 from Task 2), 0 failed.

Run: `cd APP5.0 && python tracker/run_all.py`
Expected: the two known data-dependent failures only — `test_offline_readiness.py` ("8 boys tracked games present (got None)") and `test_ratings_depth_smoke.py` ("the do-it-all read stays distinctive"). Both reproduce on `main` on this machine and are the local book being nearly empty, not code. Any third failure is yours.

- [ ] **Step 7: Bump the service worker cache**

`app.js`, `index.html` and `style.css` all changed, so installed PWAs must re-fetch. In `sw.js`, change `const CACHE = 'tracker-v55';` to `const CACHE = 'tracker-v56';`.

- [ ] **Step 8: Commit**

```bash
git add APP5.0/tracker/static/sw.js
git commit -m "chore(tracker): bump PWA cache for the tablet layout"
```

- [ ] **Step 9: Deploy**

```bash
git push origin main
```

```bash
ssh app5@107.170.27.154 "bash ~/update.sh"
```

The script restarts `app5-web` **and** `app5-tracker`; the tracker restart is the one that matters here. Verify:

```bash
ssh app5@107.170.27.154 "cd ~/app5/APP5.0 && git rev-parse --short HEAD && systemctl is-active app5-tracker"
```

```bash
curl -s https://track.hooptracks.com/sw.js | grep -m1 "const CACHE"
```

Expected: `const CACHE = 'tracker-v56';`

---

## Notes for whoever runs this

- **The height budget is the design.** Every task either spends or saves vertical pixels against 744. If a step's measurement disagrees with the spec's table, the table is the thing to re-derive — do not just shrink something until it fits.
- **Task 2 Step 6 is the real gate.** The phone layout is the app's primary surface; a tablet win that costs a phone regression is not a win. Do not skip the `main` comparison because the change "looks fine".
- **Do not add a `grid-auto-flow: column` to `.detail-grid`.** It reads more naturally down-then-across but breaks the phone fallback, and the phone is what most sessions actually use.
