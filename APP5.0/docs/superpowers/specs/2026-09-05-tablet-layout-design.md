# Tracker tablet layout — quick-mode-first, no-scroll on an iPad mini

Date: 2026-09-05
Status: approved design, not yet implemented
Touches: `APP5.0/tracker/static/{index.html,style.css,app.js,sw.js}`

---

## The problem

The wide layout shipped in `batch-2026-09-05` put the tracker into two columns,
which was the right move, but it split them the wrong way for how the app is
actually used. Today:

- **left column** — `#court-wrap`, `#shot-caption`, `#mode-row`
- **right column** — `#defense-bar`, `#playtype-bar`, `#flow-opts`, `#flow`,
  `#to-row`, `#action-row`, `#sync-status`, `#coverage-badge`, `#pbp-toggle`, `#pbp`
- **full-width bands** — `#track-head`, `#subs-panel`, `#track-tip`

Two things are wrong with it. The right column carries both the tagging surface
AND every rare control, so the things used once a quarter (timeouts, edit log,
end game) push the things used every possession down the screen. And the score /
clock band sits full-width on top, spending the most valuable vertical space in
the layout on a read-only number.

## The target

**iPad mini 6, landscape, 1133 × 744 CSS px.** The tracker is an installed PWA
(`sw.js`, standalone display), so there is no browser chrome — 744px is the
entire height budget. Larger iPads (1180 × 820, 1366 × 1024) inherit the same
layout with slack; the mini is the binding constraint and the only size the
no-scroll rule is measured against.

## The rule this design is built on

The founder's own split, in his words: *"I would like to be able to track the
entire game without scrolling outside of maybe undos, undo timeouts, subs, stuff
of that nature that I would not be using much at all or would have an extended
stoppage."*

That divides the screen into two zones:

**HOT — must be on screen at all times, zero scroll.**
Court, mode tabs, defense bar, play type bar, the flow block (shooter →
MAKE/MISS in quick; shooter → six detail rows → MAKE/MISS in detail), score,
quarter, clock.

**COLD — below the fold, reached by one scroll during a stoppage.**
Subs, TO Home / TO Away, Undo TO, edit log, leave (saved), end game,
play-by-play (collapsed by default — that is already how it is used).

**One deliberate promotion:** `#btn-undo` moves from COLD into the HOT row.
The founder grouped it with the rare controls, but undo is a mis-tap
correction — it fires immediately after a bad tap, mid-possession. It is the
only "rare" control that is time-critical. Timeouts genuinely are not.

## The height budget — why detail mode must go two-column

Measured from `style.css`, not estimated. Right column is ≈529px wide at a
1133px viewport (`.screen` max-width 1180, padding 16 a side, grid
`minmax(300px,1.05fr) minmax(320px,1fr)` with a 16px gap → 1085 split ≈ 556 / 529).

Full detail, six rows in a single stack:

| Element | Height |
|---|---|
| `#mode-row` (`.btn` 44 + margin 6) | 50 |
| `#defense-bar` (label + select + up to 5 chips → wraps to 2 lines) | 100 |
| `#playtype-bar` (same) | 100 |
| `#flow-opts` (quick/detail toggle) | 50 |
| `#flow` — Shooter `.chip-row` (label 19 + chip 44 + margin 10) | 73 |
| `#flow` — 6 × `.sel-row` @ 73 | 438 |
| `#flow` — `.mm-row` (margin 8 + `.btn.make` 64) | 72 |
| `#flow` padding 10×2 + border | 22 |
| `.screen` padding 16×2 | 32 |
| **total** | **937** |

Against 744. With both tag bars on a single line it is still 837. **A single
stack cannot fit an iPad mini.** Two columns of three drops the six rows from
438 to 219 and brings the total to **718** — clears 744 by 26px.

Quick mode, same column: 50 + 100 + 100 + 50 + (22 + 73 + 52 + 72) = **551**,
leaving ~190px of headroom. That headroom is what pays for bigger shooter
targets (below).

Left column, detail or quick: court is width-limited at 556 wide × `aspect-ratio
50/39` = **434** tall, + caption ~20 + score line ~50 + quarter/clock row ~50 =
**~554**. The right column is the taller of the two and therefore sets the fold.

**Decision: two columns of three in wide mode, on every device size**, not only
where the height demands it. A single stack would fit a 12.9" Pro (837 < 1024),
but a coach who picks up a different iPad should not find the rows rearranged.
Muscle memory beats fidelity to the original sketch.

Team separation in the detail dropdowns is unaffected by column count — it lives
*inside* each `<select>` as `<optgroup>`, built by `playerOpts()`
(`app.js`, `group: S.game[side].name`). Do not touch it.

## Layout

```
┌─ 1133 × 744, wide mode ───────────────────────────────────────────────┐
│ ┌── col-left (556) ─────────┐ ┌── col-right (529) ─────────────────┐  │
│ │ #court-wrap    556 × 434  │ │ #mode-row   shot  ft  foul  tov    │  │
│ │                           │ │ #defense-bar                       │  │
│ │                           │ │ #playtype-bar                      │  │
│ │                           │ │ #flow-opts        [⚡/📋 toggle]    │  │
│ │ #shot-caption             │ │ #flow                              │  │
│ │ #track-head               │ │   Shooter  (wrapping jersey grid)  │  │
│ │   Home 0 — 2 Away         │ │   quick:   [ MAKE ] [ MISS ]       │  │
│ │   Q1  −7+  −40+  ↩ Undo   │ │   detail:  ┌─────────┬─────────┐   │  │
│ └───────────────────────────┘ │            │Pass from│Rebound  │   │  │
│                               │            │Hockey   │Blocked  │   │  │
│                               │            │Set up by│Guarded  │   │  │
│                               │            └─────────┴─────────┘   │  │
│                               │            [ MAKE ] [ MISS ]       │  │
│                               └────────────────────────────────────┘  │
├───────────────────── fold (744) ──────────────────────────────────────┤
│ #subs-panel · #to-row · #action-row · #sync-status · #coverage-badge  │
│ #pbp-toggle · #pbp (collapsed)                                        │
└───────────────────────────────────────────────────────────────────────┘
```

Column assignment changes from today:

| Element | Today | New |
|---|---|---|
| `#track-head` | full-width band, top | col-left, **below** court |
| `#mode-row` | col-left | col-right, top |
| `#btn-undo` | `#action-row` (col-right) | `#track-head` controls (hot) |
| `#to-row`, `#action-row` | col-right | full-width, below fold |
| `#pbp-toggle`, `#pbp` | col-right | full-width, below fold |
| `#sync-status`, `#coverage-badge` | col-right | full-width, below fold |
| `#court-wrap`, `#shot-caption` | col-left | unchanged |
| tag bars, `#flow-opts`, `#flow` | col-right | unchanged |

## Architecture — why wrapper elements, not more `grid-column` rules

The current wide CSS assigns `grid-column` per element and lets grid
auto-placement pick the row. That couples the two columns: an item in col 1 and
an item in col 2 can land in the same implicit row, and that row grows to the
taller of the two. It survives today only because `align-items: start` hides the
symptom. A no-scroll layout cannot be built on it — the court (434px) sharing a
row with the mode row (50px) wastes 384px.

**Introduce two wrapper elements** in `#screen-tracker`:

- `.col-left` — `#court-wrap`, `#shot-caption`, `#track-head`
- `.col-right` — `#mode-row`, `#defense-bar`, `#playtype-bar`, `#flow-opts`, `#flow`

Each is `display: flex; flex-direction: column` in wide mode, so its children
stack independently of the other column. `#screen-tracker` becomes a two-cell
grid holding exactly these two wrappers plus the below-fold band.

**The narrow (phone) layout must not change at all.** Achieve that with
`display: contents` on both wrappers in narrow mode, so their children render as
if they were still direct children of `#screen-tracker` in DOM order.
`display: contents` is supported from Safari 15 / iPadOS 15, below the floor this
app already requires for an installed PWA.

**DOM order vs. visual order.** On a phone the score belongs at the top; in wide
mode it belongs under the court. Keep `#track-head` first in `.col-left` in the
DOM (phone order preserved by `display: contents`) and reorder visually in wide
mode with flex `order`: court 1, caption 2, track-head 3.

**`#subs-panel` is the one ordering hazard.** It currently sits between
`#track-head` and `#court-wrap`, which is inside the range `.col-left` needs to
wrap. It is a takeover panel, `hidden` by default, and belongs below the fold in
wide mode. Moving it in the DOM changes where it opens on a phone. The
implementation plan must resolve this explicitly and verify the phone layout is
byte-identical before and after — see Risks.

## Behaviour changes in `app.js`

1. **Shooter picker becomes a wrapping grid in wide mode.** `chipRow('Shooter', …)`
   renders a horizontally sliding `.chip-row` strip. With ~190px of quick-mode
   headroom, wide mode should wrap the jersey chips into a grid of larger tap
   targets instead. Narrow mode keeps the sliding strip. CSS-only if possible;
   no change to the chip-building JS.

2. **Undo in the header.** Render `#btn-undo` inside `#track-head`'s control row
   in wide mode. Prefer moving the existing button element (one undo button, one
   handler) over cloning it — a second element means a second listener and a
   drift risk.

3. **Detail rows two-up.** `SHOT_DETAILS.forEach` emits six `.sel-row`s into
   `#flow`. Wrap them in a container that is a 2-column grid in wide mode and a
   single column in narrow. Do not change `selRow`, `playerOpts`, or the
   `<optgroup>` behaviour.

Nothing about quick-vs-detail *toggling* changes: both render into the same
`#flow` box at the same screen position, so the toggle never relayouts the page.

## Verification

Layout is not unit-testable; verify it in a real browser at the real size.

1. Start the tracker preview (`launch.json` entry `tracker`, port 8500; needs
   `uvicorn`, cwd `APP5.0`, localdev token).
2. `resize_window` to **1133 × 744**, then load a game and enter the tracker.
3. Assert **no page scroll in either mode**:
   `document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1`
   — once in quick mode, once in full detail. This is the acceptance criterion;
   the height table above is the prediction it checks.
4. Confirm every HOT element is inside the viewport
   (`getBoundingClientRect().bottom <= 744`) in both modes.
5. Confirm the COLD band is reachable by scrolling and nothing there is clipped.
6. Re-check at **1180 × 820** and **1366 × 1024** — both should have slack.
7. **Regression: narrow mode is unchanged.** At 390 × 844, compare the rendered
   element order and each element's `offsetTop` against `main` before the change.
   Any difference is a bug, not an improvement.
8. `pytest tracker/` stays green (256 passed at the time of writing).

## Risks

- **`#subs-panel` DOM move breaks the phone layout.** Highest risk in the change.
  Verification step 7 is the gate. If the panel cannot be moved without shifting
  the phone layout, leave it where it is and give it `order` + full-width
  placement in wide mode instead.
- **Tag bars wrapping to a third line.** The budget assumes at most two lines per
  bar (label + select + up to five one-tap chips). A coach with five long defense
  preset names on a narrower-than-expected column could reach three lines and
  eat the 26px of slack. Verification step 3 catches it; the fallback is to cap
  the chip strip to one line with horizontal scroll inside the bar.
- **`display: contents` and accessibility.** Historically some engines dropped
  the a11y tree for `display: contents` elements. The wrappers are plain
  presentational `div`s with no semantics or ARIA, so nothing is lost, but do not
  put a landmark role on them.

## Out of scope

- Portrait tablet layout. Landscape only; portrait continues to use the phone
  column.
- Any change to what is logged, to the event model, or to `tracker/api.py`.
- The Streamlit pages. This is `tracker/static/` only.

## Ship checklist

- [ ] Bump `CACHE` in `tracker/static/sw.js` (currently `tracker-v55`) — `app.js`,
      `index.html` and `style.css` all change, so the PWA must re-fetch.
- [ ] Deploy restarts `app5-tracker`, not only `app5-web`.
