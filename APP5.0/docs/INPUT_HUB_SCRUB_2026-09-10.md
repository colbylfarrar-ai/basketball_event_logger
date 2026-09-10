# Input Hub consolidation scrub — 2026-09-10

Read-only sweep of the three edit pages (Input Hub, Setup/Roster & District, Event
Editor). No code changed. Companion memory: `input-hub-consolidation-scrub`.

---

Scrubbed all 1203 lines of `pages/1_Input_Hub.py` on 2026-09-10 against
`pages/11_Setup.py` (476) and `pages/3_Event_Editor.py` (765), to decide what
consolidates. Verdicts below are per-section, with the blockers named.

## The governing fact: Input Hub has NO ownership gate

`grep ENT\.` on 1_Input_Hub.py returns **nothing** — no `entitlement` import at
all. Its only gate is `_gated_delete` (line 24), which queues *deletes* for admin
approval via `change_requests`. **Every UPDATE and INSERT is league-wide open**:
any signed-in coach can rename any team, edit any player, rewrite any game's
score. Setup gates hard (`_team_scope`/`_game_scope`, `ENT._own_teams`,
11_Setup.py:40-58).

So the same write (a player's grad_year, editable on both pages) is scoped on one
page and unscoped on the other. **Ownership is decided by which page you opened.**
This is the reason to consolidate and it dictates the direction: any merge moves
toward Setup's scope. Merging the other way silently widens write access.
See `coop-gate-is-load-bearing`, `own-creation-read-filter`.

## CAN consolidate

**Players ← Setup roster tab.** One `players` row split across two pages by
column, with two columns editable in both:

| column | Input Hub Players | Setup Roster |
|---|---|---|
| name, number, height, wingspan, weight | edit | read-only |
| grad_year, handedness | **edit** | **edit** |
| position, availability | absent | edit |
| add a player | yes | no — bounces to Input Hub |

11_Setup.py:152 literally captions the seam ("come from the Input Hub, read-only
here"). Both save paths already call `IDN.propagate_person_fields`. Add
`position` + `availability` to the Input Hub grid and Setup's roster tab is
redundant. Carry the team scope across.

**Teams ← Setup district tab.** `district` is one TEXT column on `teams`; the
Input Hub Teams grid already edits name/class/gender/state on the same row.
Setup's version adds a search box worth keeping.

**Games ← Setup game-type tab.** `game_type` is one column on `games`; the Games
grid already edits nine columns of that row. Setup's filter + "Apply to all
shown" bulk-set is genuinely useful — keep it as an expander, not a page.

**Games + Team Schedule → one editor.** Same `games` table, two POVs (league grid
vs one-team home/away). They already know they collide: both saves invalidate the
other's cached frame (lines 949, 1065). Fold Team Schedule into a POV toggle.
**This merge fixes a live defect** — see below.

## CANNOT consolidate

**Officials.** I was wrong earlier that `pages/8_Officials.py` duplicates it —
that page is a read-only "Officiating Lab" (no `data_editor`, no writes). Input
Hub is the **only** officials editor in the app. It can be relocated, never
dropped. Its insert also carries real logic: `ON CONFLICT(official_id, state) DO
UPDATE SET archived=0` revives an archived ref, and the conflict target is the
PAIR because badge numbers repeat across states.

**Retroactive class** (Teams, line 473). Writes `team_class_history`, a different
table from the grid above it, for archived seasons only. Genuinely separate
concept — classes re-align yearly. Keep as its own expander.

**New Season rollover** (line 234, admin-only) and **cross-season sync** (line
745, admin-only). Destructive league-wide operations. Keep gated and separate.

**Box Score Entry** (Setup tab 4). Should leave Setup but must NOT fold into
Input Hub — it is a complete manual box-score app with MaxPreps CSV import, and
it is the peer of the Game Tracker (the other way a game gets its numbers).
Give it its own nav entry under Build, directly under Game Tracker.

## Two defects the split is hiding

**1. `ins_sched` is a strictly weaker copy of `ins_game`.** Input Hub's Games
insert (line ~860) pre-checks the duplicate matchup before writing, so the coach
reads a sentence instead of a raw constraint name and the rest of a pasted batch
still saves. **Team Schedule's `ins_sched` (line ~996) has no such check**, and
no "season for new games" picker either (hard-wired to auto-from-date). Adding a
game from Team Schedule can therefore double-book a matchup that the Games grid
would have refused. Ties into `merge-teams-makes-dup-games` and
`games-matchup-index-is-partial` — `ux_games_matchup` is partial
(`tracked_by=''`), so the index does not backstop this.

**2. Season Archive → Schedule tab reads a dead table.** It queries `schedule`
(lines 1182, 1195). Repo-wide grep: the ONLY write to `schedule` left anywhere is
`helpers/seasons.py:326`, which re-stamps a season label on existing rows. **No
INSERT path exists.** Local book: `schedule` = 30 rows, `games` = 13,363 — and
all 30 are one season (2025-2026). The tab renders a vestigial view of a table
the app stopped filling. (Counted on the local book, which lags prod —
`local-book-lags-prod` — but the missing-INSERT fact is code-level and
version-independent.) The Rosters tab beside it reads `players` and is fine.

## Structural notes

- `_seg` not `st.tabs` — line 381 documents why: `st.tabs` snaps back to tab 1 on
  every rerun and every Save reruns. **Setup never got this fix**: it uses
  `st.tabs` (11_Setup.py:79) *and* reruns at 243/338/476, so bulk-applying a game
  type throws you back to the Roster tab. See `seg-conversion-leaks-cross-tab-vars`
  for the AST sweep any such conversion needs.
- Reusable machinery worth keeping through any refactor: `apply_delta`,
  `_sortable` (resets the editor on sort change so positional `iloc` can't
  misapply), `get_orig`/`invalidate`, `flash` (messages survive `st.rerun`),
  `_live_game` + `_norm_score` (guard a tracked game's PBP-derived score from
  manual overwrite — both editors call this; do not lose it).
- Setup has four names for itself: file `11_Setup.py`, docstring `10_Setup.py`,
  `page_chrome("Setup")`, `page_header("Roster & District")`, nav title
  "Roster & District".

## Suggested order

1. Port `_team_scope`/`_game_scope` onto Input Hub — standalone, closes the
   access gap, prerequisite for everything else.
2. Fix `ins_sched`'s missing dup guard (or do step 4, which deletes the path).
3. Merge Setup's three thin tabs in; move Box Score Entry to its own nav page;
   delete `11_Setup.py`.
4. Fold Team Schedule into Games as a POV toggle.
5. Decide Season Archive's Schedule tab: repoint at `games` or drop it.

Event Editor is a separate job — its namesake grid sits ~380 lines down under
three expanders, and the quarter/type filters govern only three of its five
tools while the other two silently act on the whole game.
