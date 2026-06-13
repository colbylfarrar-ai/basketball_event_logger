# APP5.0 Improvements — Multi-Agent Review Synthesis

Eight review agents covered every page plus the shared design system. Findings below are
deduplicated, re-ranked by impact-per-effort, and corrected for work already finished:
the data_version cache-sync mechanism and the login gate are DONE, and the mobile PWA
(tracker/) now owns courtside logging — related findings are reframed accordingly.

---

## 1. Top 10 Overall

1. **Lock the dark theme — no .streamlit/config.toml exists.**
   Streamlit follows the viewer's OS light/dark preference, so a coach on a light-mode
   laptop gets white dataframes, dropdowns, and dialogs floating over your forced-dark
   cards. You will never see it on your own machine; a demo will. Add `[theme]`
   base="dark" + brand colors. File: .streamlit/config.toml (new). Effort: S.

2. **Rename the "His fouls" column.**
   Refs are frequently women and the customer base is girls-HS coaches — the single most
   embarrassing string in the app. Change to "Ref fouls". pages/8_Officials.py:593. Effort: S.

3. **Make save results visible in the Input Hub — failed edits currently vanish silently.**
   Every save handler renders success/error then immediately calls invalidate + st.rerun(),
   wiping the message and discarding the rejected rows; the tracked-game guard message is
   never shown. To a coach, a reverted edit with no explanation reads as data loss. Use a
   session-state flash; skip invalidate/rerun on error. pages/1_Input_Hub.py:220-227
   (same pattern at 285-292, 364-371, 475-482, 516-523). Effort: S.

4. **Stop swallowing exceptions as fake-empty data.**
   A global `except: pass` around the whole Main dashboard turns any internal error into
   "No finished games yet"; a WPA engine failure renders +0.000 for every player; the
   scatter explorer silently drops the user's Size choice. Catch per-section and show a
   "some data failed to load" warning. Main.py:166-167; helpers/box_score.py:1031-1037
   and 209-228; pages/10_Data_Explorer.py:131-135. Effort: S.

5. **Dedupe the on-court five before crediting plus-minus.**
   Picking the same kid in two lineup slots double-counts her +/- on every score, forever,
   invisibly — permanent corruption in a stat coaches quote. Fix the per-occurrence UPDATE
   in helpers/game_events.py:51-59 so the PWA write path is protected too, and warn when
   the lineup is not exactly 5. pages/2_Game_Tracker.py:423-435. Effort: S.

6. **Fix the tier caption that contradicts the tier math.**
   Caption says "S >= 68 / A >= 60 / ..." but _tier() buckets at 70/62/54/46. A coach with
   a 69-Power team sees A-tier under a caption claiming S, and stops trusting every number
   on the page. Derive the caption from one shared constant. pages/5_Rankings.py:1473
   vs 140-148. Effort: S.

7. **Team Dashboard first-impression bugs: literal HTML on Overview, four blank Charts sub-tabs.**
   The Overview caption prints raw `<span style=...>` as visible text (missing
   unsafe_allow_html), and Shooting/Rebounding/Defense/Trends render literally nothing for
   a team with no tracked games — exactly the state every trial coach starts in.
   pages/6_Team_Dashboard.py:801-802 and 1707-1712. Effort: S.

8. **Stop rendering results copy for unplayed games on Schedule.**
   Tomorrow's game day shows "Upset Alert: No upsets — higher-ranked teams held serve" and
   em-dash score cards — factually wrong copy about games that never happened. Suppress
   now; predictor-powered preview mode is Big Bet 2. pages/4_Schedule.py:274-355. Effort: S.

9. **Close the residual cache-sync gap left after the data_version work.**
   The mechanism is built and works — but Main.py:42-43, pages/1_Input_Hub.py:10-15, and
   pages/2_Game_Tracker.py:23-27 boot via require_login/apply_page_config directly and
   never run page_chrome()'s _sync_external_writes, so tracker writes can stay invisible
   on the landing page and both entry surfaces (they also miss the global stylesheet).
   pages/11_Setup.py:67-184 saves never invalidate any cache. And no page shows an
   "as of / refresh" control, so a coach can't force or even see freshness. Route all
   three pages through page_chrome, add clears to Setup, add a small refresh affordance.
   Effort: S-M.

10. **Kill the spurious full-page reruns coming from shared helpers.**
    ui.grid's AgGrid has no update_mode, so one sort click re-executes the entire host
    script — including the 5,544-line Team Dashboard (used at 6_Team_Dashboard.py:4918,
    7_Players.py:609, 8_Officials.py:299, 10_Data_Explorer.py:99); glossary search reruns
    its whole host page per keystroke. Set GridUpdateMode.NO_UPDATE (and drop the unused
    allow_unsafe_jscode), wrap glossary_tab in @st.fragment. helpers/ui.py:231-246;
    helpers/glossary.py:444-474. Effort: S.

---

## 2. Quick Wins Under an Hour

Batch these (plus Top 10 items 1-8) into one cleanup PR:

- Stale docstring sweep: Main.py:2, pages/4_Schedule.py:2, pages/5_Rankings.py:2,
  pages/6_Team_Dashboard.py:2, pages/8_Officials.py:2, pages/10_Data_Explorer.py:2 all
  name the wrong file; assets/style.css:2 still says "APP4.0".
- Delete the "Database ready (analytics.db)" footer from the landing page (Main.py:405-411).
- Rename "Everything rank/ranking" to "League rank" and delete the duplicated metric rows
  (pages/5_Rankings.py:291-294, 539, 577-581; pages/6_Team_Dashboard.py:804-811, 830-836).
- Hot & cold N+1: streaks already sit in cached form_stats — delete the per-team query
  loop (pages/5_Rankings.py:893-899).
- Player game-log N+1: build from the cached _pgb() instead of per-game
  aggregate_player_boxes (pages/7_Players.py:1406-1418; same fix at
  pages/6_Team_Dashboard.py:5242-5243).
- eFG% shown as 0.512 and 51.2% on the same page — format the Tracked table as percents
  (pages/5_Rankings.py:966-970).
- One green: #2ecc71 / #2ea043 / GOOD all mean "win" (pages/5_Rankings.py:913, 1822 vs :51).
- Bracket "Champ %": format="%.1f%%", max_value=100 so the favorite isn't a full bar
  (pages/9_War_Room.py:386-389).
- Correlation heatmap skips _style() — near-invisible navy text on dark background
  (pages/10_Data_Explorer.py:180-183).
- "Hottest" KPI can show an em-dash as the team name (Main.py:90-94); zero-PPG players
  render blank cells via falsy checks (Main.py:334, 117, 323).
- Hub banner score: display stored home/away score instead of reconstructing from events
  (Main.py:152-164).
- "IN PROGRESS" forever on hand-entered games; winner arrow on ties
  (helpers/box_score.py:249, 199-243).
- Add DNP rows so no kid vanishes from the box score (helpers/box_score.py:1122-1124).
- Compare table shows raw keys ("PTSsd", "bestPTS") — use the labels that already exist in
  STAT_GROUPS (pages/7_Players.py:1041).
- Delete the blank icon slots (empty 26-40px divs) on podium, hero, and scouting cards
  (pages/7_Players.py:226, 404, 1648-1679).
- Input validation trio: DateColumn instead of free-text dates (pages/1_Input_Hub.py:316,
  406), NumberColumn min/max + consistency checks on the manual box (pages/11_Setup.py:166-172),
  home != away guard (pages/1_Input_Hub.py:314-315).
- Settings copy: replace the secrets.toml/AUTH_SETUP.md developer instructions with
  coach-facing text (pages/12_Settings.py:162-166); fix the wrong "reload other pages"
  caption (:28).
- "Upcoming" list needs a date floor so February's forgotten game doesn't show in June
  (pages/5_Rankings.py:676-688).
- empty_state's CTA pill looks like a button but is dead HTML — render a real st.page_link
  (helpers/ui.py:273).
- Browser tabs all say "Analytics Hub" with no favicon — per-page titles via page_chrome
  (helpers/settings_utils.py:128-134).
- html.escape caller-supplied names in card helpers — rendering bug today, stored XSS once
  multi-coach (helpers/ui.py:140-143; helpers/cards.py:87-92, 113-115, 133-152).
- Loser score contrast #555d68 is unreadable; floor microcopy at 11px
  (assets/style.css:74, 171, 605).
- Team Charts multiselect defaults to all 30+ teams selected — default=[] means all
  (pages/5_Rankings.py:1028-1031).
- "Home court" radio says Team A/Team B instead of the chosen team names
  (pages/9_War_Room.py:168).
- Cache the officials game log like its sibling queries (pages/8_Officials.py:562).

---

## 3. Per-Page Findings

### Main + Schedule (Main.py, pages/4_Schedule.py)
- Calendar collapses to a vertical list of ~35 buttons on phones (7-wide st.columns,
  4_Schedule.py:200-226); ~31 disabled button widgets per month (:224-226) — CSS no-wrap
  or custom HTML grid with query-param day links.
- Every tracked game's box score renders eagerly inside expanders, and Game of the Day
  renders twice (4_Schedule.py:312-314, 418-420) — lazy-gate with checkbox or st.dialog,
  wrap day section in @st.fragment.
- Game-of-the-season is an N+1 loop with per-game WP-curve compute on the landing page
  (Main.py:136-165) — persist GEI at game finalization.
- Upset logic grades December games by June ranks and a 1-spot gap qualifies for a red
  alarm card (4_Schedule.py:114-120, 333-340) — threshold or win-prob gate.
- Game of the Day = highest combined score, so a 50-point blowout beats a 2-point thriller
  (4_Schedule.py:279) — rank by GEI, the engine already exists.
- Gender toggle: raw non-persistent radio on Main (:180-185), absent on Schedule so Day's
  Leaders mixes leagues (:358-389) — use the shared ui.gender_radio; month nav orphans the
  selected day, no Today button (4_Schedule.py:161-189, 241); search results aren't
  clickable (Main.py:318-346).

### Team Dashboard (pages/6_Team_Dashboard.py)
- ~140 Plotly figures serialized per load: 7 tabs x 10 sub-tabs, 37-chart QSPEC grid and
  59 leaderboards run even when collapsed (:750-753, 1632-1636, 3409-3424, 1531-1534) —
  segmented_control for Charts sections, checkbox-gate the walls. Biggest perf item in the app.
- Heavy caches (_rapm :581-587, league-wide _pp_zone_tables :698-703) recompute
  mid-session with spinners suppressed — multi-second silent freezes; key on data_version
  and show a spinner label.
- Overview prints rank/record three times in one screenful with two names for the same
  number (:638-655, 804-811, 830-836).
- Information architecture: 21 destinations, Scout buried while analyst toys (Build lab
  :4528, correlation heatmap :4888, RAPM whiskers :4351) sit at the same level — promote
  Scout to tab 2, bucket the rest under "Lab", move Glossary to a popover (:4928).
- Semantic color flips: self-created shots orange in Shooting (:2192, 2229) but red=BAD in
  Quarters (:3305-3316); 3PT blue on offense (:1929), orange on defense (:2518) — one
  semantic palette dict.
- Schedule tab shows only completed games — no upcoming opponents or projections, the one
  place "Proj" would be useful (:1577-1608).
- Format drift: PPP in 2dp/3dp/rounded, WPA 3dp beside 2dp (:1822, 2614, 4401-4419);
  "Opp FTA drawn" reads backwards (:2715).

### Players + Box Score (pages/7_Players.py, helpers/box_score.py)
- box_score.py has zero fragments — one slider tick rebuilds all 7 tabs / ~45 charts
  (:297-298, widgets at :776-1015); apply the fragment pattern 7_Players.py already proves
  (:732, 894, 1055, 1756).
- Leaders tab renders a 76-chart wall outside any fragment, and the Ratings selectbox
  reruns it (7_Players.py:89-188, 655, 707-726) — st.pills group picker, render one group.
- Profile and Compare ignore the tap-captured x/y data; only Shot Lab uses _shot_map
  (7_Players.py:1198, 986 vs 836-841) — mirror the Shot Lab branch. (Feeds Big Bet 1.)
- Misleading copy: "No located shots" gating zone charts (:1204, :991); box-score caption
  claims away team is "(red)" when it's their team color (box_score.py:902).
- Redundancy: 5 gauge dials repeat numbers shown twice above (7_Players.py:1170-1174);
  chip strip duplicates glass tiles (:310-316 vs 443-449); long team names truncate metric
  labels (box_score.py:307-314).
- Robustness/mobile: identity-based pid lookups can crash (:833, 985, 1062;
  box_score.py:1217-1226); 9-column rows and no flex-wrap hero crush phones (:645, 1156,
  1101); hardcoded quarter boundaries (box_score.py:1096).

### Rankings + Officials (pages/5_Rankings.py, pages/8_Officials.py)
- Team/Compare/Individual selectboxes outside fragments rerun ~50 charts
  (5_Rankings.py:550, 1801-1803; 8_Officials.py:487) — the fragment pattern exists on the
  same page.
- 22-chart "every stat" gallery plus ~15 more in one tab (5_Rankings.py:1059-1088) —
  pill-pick one stat at a time.
- Compare tab says head-to-head but never shows whether the teams actually played
  (:1791-1863) — query meetings, headline the result. (Feeds Big Bet 2.)
- Whistle-leader tiles rank by one metric and display another; one-game refs get crowned
  on a bias-adjacent page (8_Officials.py:182-203) — qualifier n>=2 + sample size on tile.
- Duplication: hero chips vs League pulse (:304-356); same fouls chart twice in Officials
  (8_Officials.py:247-249 vs 320-322); SOS in three precisions (:526, 572, 1845).
- Mobile: 21-column Tracked table (:946-950) and the static HTML compare table
  (:1831-1837) are unreadable on phones; gender_radio needs an include_all param so
  Officials stops hand-rolling its own (8_Officials.py:136-138).

### War Room + Data Explorer (pages/9_War_Room.py, pages/10_Data_Explorer.py)
- All sim tabs compute eagerly with spinners suppressed — cold load runs matchup + season
  + bracket serially, frozen page at 50k sims (:209, 263, 350) — fragments per tab,
  show_spinner labels.
- Bench-swap search: ~50 uncached lineup_prediction calls on every rerun, even from other
  tabs' widgets (:478-483) — cache keyed on the chosen lineup.
- Silent dead-ends: season-sim picker renders nothing for no-game teams (:310-312);
  bracket bar truncates to 12 teams without saying so (:355); shot-map "Team" scope
  silently falls back to league-wide data (10_Data_Explorer.py:204-207).
- No matchup export — the scouting one-pager is the thing Hudl coaches actually print
  (:155-250) — st.download_button with templated HTML.
- "Lucky / clutch" caption conflates opposite explanations (:302-303); sims select_slider
  should be a segmented control (:53-56).

### Input Hub + Setup + Event Editor + Settings
- Season rollover archives the dead `schedule` table while the app lives on `games` — the
  archive a coach expects after the scary confirm stays empty (1_Input_Hub.py:175 vs
  377-482, 573-598) — stamp season on games or archive by date range.
- Games tab and Team Schedule tab are duplicate editors over the same table with one-way
  invalidation — stale-orig clobbering (:298-371 vs 377-482; minimum fix at :369).
- Event Editor cannot fix shot_x/shot_y, and editing zone desyncs it from the tap data —
  the most likely live-tracking error is uncorrectable (3_Event_Editor.py:139;
  helpers/event_log.py:39-44). (Feeds Big Bets 1 and 6.)
- Time column accepts "12:99" verbatim, breaking clock math downstream
  (3_Event_Editor.py:131-132, 165) — regex-validate per row.
- Every save clears all ~75 caches app-wide; Setup saves loop one connection per row
  (1_Input_Hub.py:226 etc.; 11_Setup.py:68-123) — domain version tokens + diff-only
  writes before multi-coach.
- Workflow: switching team silently destroys unsaved rows (:244-246, 387-389); one
  untracked game touches three pages (:308-323 + 11_Setup.py:101-184); the PWA overlap is
  unacknowledged — cross-link surfaces, share one rescore path (tracker/api.py vs
  3_Event_Editor.py:75-79).

### Game Tracker desktop page (pages/2_Game_Tracker.py)
The PWA owns courtside logging now. This page should become the bench/desk second screen:
auto-refreshing scoreboard + live box + live shot chart fed by the phone's writes, with
the manual form demoted to a film-review/correction expander. (Big Bet 3.) Until then:
- Resurrect compute_box: 97 lines computing a full live box score that is never called
  (:73-169) — render it, highlight foul trouble.
- Auto-refresh: @st.fragment(run_every="3s") on the scoreboard/PBP block (:631-699);
  without it the page is frozen while the phone writes.
- If the form stays: confirm dialog + reopen for one-click "End Game" (:269-274); block
  logging into finalized games (:263 vs 468-625); clamp the clock input (:490); persist
  the on-court five so a browser refresh doesn't silently zero minutes (:423-429).
- Show team fouls/bonus per quarter — table stakes for a live product (:568-572).
- Dead/duplicate code: local live_score/possessions/quarter math drifts from
  helpers/game_events.py (:35-222); unused gc1 column (:265).
- Polish: one date-desc game selector with a LIVE badge instead of three cascading
  dropdowns (:240-256); CSV export ships emoji to Excel and lacks a running score
  (:681-698); route through page_chrome (:23-27, also Top 10 item 9).

---

## 4. Design-System Themes

One product vs. 13 experiments: the shell is unified, but five seams betray the layered build.

- **Two header systems.** st.title on 9 pages vs lab-hero banners on Main/Players/
  Officials, inconsistent casing, and Rankings has both at once (5_Rankings.py:243 and
  :332). Add ui.page_header(title, sub, chips) and replace all 12.
- **Heatmap palette anarchy.** Nine colorscales (Viridis, Turbo, RdYlGn, Plasma, ...)
  where "good" is yellow, green, or red depending on the page. Define HEAT and DIVERGE in
  helpers/ui.py anchored to the existing GOOD/BAD constants; mass-replace.
- **Empty-state schizophrenia.** ui.empty_state used 19x on six pages; the identical
  situation is bare st.info ~30x on Rankings/Players/Officials/Main. Unify on empty_state.
- **Icon anarchy.** Blank icon slots, color emoji, text glyphs, fullwidth plus, dingbats,
  and checkmark variants coexist (examples: 7_Players.py:226, 2_Game_Tracker.py:267 vs
  :681, 10_Data_Explorer.py:83-85, 1_Input_Hub.py:23). Standardize on Streamlit
  :material/...: icons; one pass app-wide.
- **Accent and theme presets are half-wired.** Hardcoded #f0a500 across style.css:48/127,
  cards.py:79/156/247, ui.py:187 and ~10 chart call sites defeats the Settings accent;
  presets force-paint navy player cards in the theme block itself
  (settings_utils.py:191-202) so "Forest" is a patchwork. Wire var(--accent) through, or
  cut presets to Dark-only until they work. Gold also simultaneously means brand, winner,
  1st place, and 25th-percentile mediocre (cards.py:79) — pick a non-brand color for the band.
- **Three gauge implementations** with different typography and band schemes (ui.py:179-216;
  cards.py:177-201, 246-280) — collapse to one parameterized gauge.
- **Per-call SQLite connections in hot paths.** get_setting and team_color open a fresh
  connection each call — 12-team chart = 12 connections per rerun
  (settings_utils.py:92-96; ui.py:296-302) — cache a color-override dict, reuse cfg in
  page_chrome.
- **Export exists only on Data Explorer.** ui.chart's CSV affordance has 3 call sites;
  ~237 other charts and 55 dataframes have none. Coaches live on "export and text it" —
  route flagship tables through ui.chart / add CSV buttons.
- **Number-precision drift** is app-wide (percents, PPP, SOS, win probabilities each
  rendered 2-3 ways) — one formatting rule in the shared helpers.

---

## 5. Big Bets

**1. Real x/y shot charts everywhere (replace the 5-zone bubbles).**
The tap-captured court-feet data is the moat — it's what a Hudl-paying coach screenshots.
Today it renders in exactly one place (Players Shot Lab). Replace the hand-drawn 5-bubble
courts on Team Dashboard (_hotcourt :1942-1996, best-shooter-by-zone :1472-1521, Scout
:4228-4248) with real half-court scatter/hexbin from helpers/court_geom.py; wire Profile
and Compare (7_Players.py:1198, 986); add the live in-game chart on the tracker desktop
page; and build the Event Editor location fixer so mistaps are correctable
(3_Event_Editor.py:139). Zone tables stay as the legacy fallback.

**2. Predictor-powered "before the game" suite.**
The app owns a predictor that today mostly retro-projects finished games. One coherent
session wires it forward: Schedule preview mode for future game days (matchup cards with
win probability instead of wrong results copy, 4_Schedule.py:274-355), an Upcoming section
with projections and a Scout link on the Team Dashboard schedule tab (:1577-1608), actual
head-to-head results + projection in Rankings Compare (:1791-1863), and a downloadable
matchup one-pager from War Room (:155-250). This is the feature that makes the app part of
weekly game prep instead of postgame reading.

**3. Game Tracker desktop page becomes the live command center.**
With the PWA logging courtside, the desktop page's job is the bench/scorer's-table second
screen: @st.fragment(run_every) auto-refreshing scoreboard, the already-written-but-dead
live box score with foul-trouble highlighting (:73-169), team fouls/bonus per quarter, and
the live shot chart — with the manual event form demoted to a corrections expander and a
proper End Game confirm/reopen flow. Most of the parts already exist; this is assembly.

**4. One-click PDF exports.**
Four surfaces currently ship HTML with "open and print to PDF" instructions: the printable
scout (6_Team_Dashboard.py:4288-4297), game recap (box_score.py:291-295), player card
(7_Players.py:1063-1067), and the missing War Room matchup sheet. Render the existing HTML
through weasyprint behind the same download buttons. The shareable artifact is what gets
texted to ADs and parent groups — Hudl hands you a PDF, and so should this.

**5. Team Dashboard re-architecture.**
The 5,544-line flagship file has a hand-maintained RENDER MAP comment admitting it renders
out of declaration order, a shadowed _shot_row defined twice (:203 vs :3203), and 56 local
defs. Split each top tab into helpers/dashboard/{overview,players,sched,charts,scout,
profile}.py, promote Scout to tab 2, and bucket the analyst toys (Build lab, correlation
heatmap, RAPM whiskers, 59-leaderboard wall) under one "Lab" section. Pays for itself in
every future edit.

**6. Post-game corrections suite.**
The #1 corrections request after mistaps: a basket the scorekeeper missed is currently
unrecoverable without corrupting the score by hand (3_Event_Editor.py:28-30). Build an
"Insert event" dialog that clones the on-floor lineup snapshot from the temporally
adjacent event and runs the normal insert path, plus the shot-location fixer from Big
Bet 1 and the reopen-game flow from Big Bet 3. Closes the loop on data quality, which is
the product's whole credibility.

---

## Suggested Execution Order

**Batch 1 — Cleanup PR (one sitting).**
Top 10 items 1-8 plus the entire Quick Wins list. Almost all S-effort, zero architectural
risk, and it clears every embarrassment-tier item before the next demo.

**Batch 2 — One-day polish sprint (perf + consistency).**
Top 10 items 9-10; fragment/lazy-render passes on Team Dashboard, Players/box_score,
Rankings, War Room; a visible "as of / refresh" control; empty_state + page_header
unification; HEAT/DIVERGE palette swap; icon standardization; mobile column fixes;
input-validation set (dates, box scores, time strings); symmetric editor invalidation.

**Batch 3 — Big bets, one session each.**
Suggested order: (3) tracker command center, (1) x/y shot charts, (2) predictor suite,
(4) PDF exports, (6) corrections suite, (5) dashboard re-architecture.
