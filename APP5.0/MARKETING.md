# HoopTracks — Capability Catalog & Marketing Playbook (June 2026)

> Internal marketing reference. Source: a code-grounded sweep of the live app (154 features
> verified across `pages/`, `helpers/`, `tracker/`) + competitive recon. Pairs with
> `AUTO_TRACKER_FEASIBILITY.md`. Live at app.hooptracks.com / track.hooptracks.com.

---

## 1. One-Liner & Elevator Pitch

**Category + wedge (one sentence):**
HoopTracks is the only real advanced-analytics platform for high school basketball — opponent-adjusted power ratings, possession-level impact (RAPM/WPA), and tap-captured shot charts — for $100 a year, with no cameras, no sensors, and no per-game tagging fees.

**Elevator pitch (~40 words):**
Track a game on your phone — no camera, no WiFi needed — and HoopTracks turns those taps into college-level analytics: opponent-adjusted power ratings, possession-level RAPM, real shot charts, and printable scout sheets. The depth Synergy and Hudl charge four figures for, for $100 a year.

---

## 2. The Full Capability Catalog — Everything HoopTracks Can Do

> ★ = genuinely unique versus competitors at the $100 price tier.

### A. Capture & Tracking

| Feature | What it does | Why a coach cares |
|---|---|---|
| ★ Offline-first PWA tracker | Responsive web app that logs a full game on any phone/tablet; events queue in IndexedDB and auto-sync when online. No app store. | Track courtside with zero connectivity risk — dead arena WiFi never costs a single possession. |
| ★ Tap-to-capture shot locations | Tap an SVG half-court to mark exactly where each shot was taken; auto-derives 2PT/3PT and zone. | Objective shot locations, not guessed zones — feeds every shot chart and heat map. |
| No-location shot entry | Skip the tap and pick value/zone manually for ambiguous shots. | Start logging instantly without perfect recall on every possession. |
| Play-type one-tap tags | Tag the play call (pick-and-roll, iso, post-up, spot-up, cut, off-screen, transition, putback, other) per event. | Captures set-play intent for scouting and possession analysis — no glossary needed. |
| ★ Shot detail capture | Mark pass-from, shot-created-by, rebounder, blocker, and on-ball defender per shot (all optional). | Builds credit assists, screen assists, rebound attribution, and the first real on-ball defense data. |
| Free throw logging | Separate FT event with shooter, result, and rebound attribution. | Clean efficiency splits and foul-line analysis. |
| Foul logging w/ official attribution | Records player fouled, fouler, and the official who called it. | Foul-trouble tracking, referee analysis, automatic NFHS bonus detection. |
| Turnover logging w/ steal | Captures who turned it over and (optionally) who stole it. | Turnover rates, steal counts, defensive pressure evaluation. |
| Live score + possession sync | Real-time score derived from logged shots/FTs, plus possession count on the court. | Glance at the phone to confirm the score is tracking before it locks. |
| Live play-by-play | Running event feed (newest first); queued events flagged with an hourglass. | A bench coach can watch the log and flag miscaps in real time. |
| Quarter & clock capture | Quarter (1–10, handles OT) and MM:SS clock with nudge buttons. | Every event is stamped to its exact game moment for timeline analysis. |
| On-court lineup capture | Select 5 home, 5 away, and up to 3 officials; snapshot saved on every event. | Enables minutes, +/-, and possession-level RAPM with no manual bench entry. |
| Substitution / floor management | Return to the lineup screen anytime to swap players in/out. | Accurate minutes and +/- across lineup changes without stopping the tracker. |
| Possession-seconds auto-calc | Each event stores elapsed time since the previous one, handling quarter boundaries. | Powers minute aggregation and shot-pacing with zero manual time math. |
| Undo / delete last event | One tap removes the most recent event (queued or synced), reversing +/-. | Miscap on the last shot? Gone in a tap — no hunting later. |
| Event-level edit + delete | Post-game editor: change type, time, player, result, zone, all detail fields, or delete; +/- and score re-derive. | Fix a mis-tag days later without re-logging the whole game. |
| ★ Quick-add player / official mid-game | Add a sub or new ref on the lineup screen without stopping. | Last-minute roster or crew change never halts logging. |
| ★ Plus/minus per player | Auto +/- to every on-court player on each make, snapshot-based so edits reverse cleanly. | Perfectly accurate +/- to the second, no hand tally. |
| Live box score | Per-player PTS, FG, 3P, FT, REB, AST, STL, BLK, TOV, PF, +/-, Game Score — updates live, foul-trouble color-coded. | The bench needs no separate stat sheet; foul trouble is visible at a glance. |
| ★ Live shot chart | Half-court map fills in as shots are logged (green make / red miss, sized by 2/3). | Scout the opponent's hot spots in real time and plan defensive adjustments. |
| Quarter scores + team fouls/bonus | By-quarter scoring table and NFHS per-quarter team-foul/bonus tracking. | Confirm quarter results and bonus state without manual tracking. |
| Manual / backup event logging | Log events from a laptop (Streamlit) through the same code path as the PWA. | If the phone dies, a laptop writer merges seamlessly into the same game. |
| Game creation & status | +New Game (teams, date, location, video URL); LIVE / FINAL / not-started badges; search by team or date. | Start a game in seconds at tip-off; know at a glance what needs finishing. |
| Finish / leave / reopen game | Freeze final score and lock, or leave mid-game (events preserved) and reopen later. | Timeout break? Leave and return without losing a possession. |
| Score recompute from log | Re-freeze the final score from the corrected event log, respecting manual overrides. | After edits, re-derive the official score with one button. |
| ★ Service-worker offline cache | App boots from cache and queues events even if the server is down. | The tracker keeps working when the arena (or the server) drops. |
| iOS "add to home screen" | Manifest + Apple meta tags for a standalone app-like icon. | App-like launch with no App Store review. |
| Sync status badge + auto-flush | Queued-count badge, online/offline dot; auto-sync every 20s and on reconnect. | See whether events landed; background sync needs no action. |
| Game-state restore + wake lock | Restores screen/game/lineup/clock after reload; keeps the screen awake. | Browser crash? Reload and you're back to the same on-court five. |
| ★ Client-side UUID idempotency | Every event carries a UUID; the server dedupes flaky retries. | Tap, hiccup, tap again — the event lands once, never twice. |

### B. The Analytics Engine

| Feature | What it does | Why a coach cares |
|---|---|---|
| ★ Opponent-adjusted SRS power ratings | Iterative opponent-strength adjustment over a sparse HS schedule graph with shrinkage and class-step bridges; results-only and possession-based versions. | See who's genuinely good vs. a schedule illusion — and bridge a B2 to a 6A. |
| ★ Win Probability Added (dual models) | Scoring-mode and possession-mode WPA; credits scorer, stealer, rebounder, blocker, on-ball defender; Leverage Index and Clutch WPA; spread-weighted. | Finally values steals, blocks, and stops — who actually wins close games. |
| ★ Regularized Adjusted +/- (RAPM) | Ridge regression over possession-level lineups; separate offensive/defensive coefficients, shrinkage tuned for a ~15-game book, optional 95% CIs. | True individual impact holding teammates and opponents constant. |
| ★ 5-man unit ratings | Reconstructs every observed lineup's ORtg/DRtg/Net per 100 possessions with credibility weighting. | See which fives actually play well together — observed, not simulated. |
| Inferred play-type efficiency (PPP) | Tempo (transition/early/half-court) × creation (self/pass/screen/both) PPP, percentile-ranked, plus coach's explicit play tags. | Rank 89th in transition but 30th in half-court — actionable for practice. |
| Player 0-100 ratings (five pillars) | Z-scored OVERALL, OFFENSE, DEFENSE, PLAYMAKING, REBOUNDING; regressed toward 50 by games played. | Five legible skill pillars on one scale; a scorer who plays no D is obvious. |
| ★ Shooting metrics suite | xFG%, Shot Rating (difficulty), xPPS, SMOE (making over expected), guarded-vs-uncontested splits. | Tells you if a hot % is earned or lucky, and who finishes the hard looks. |
| Advanced per-possession stats | Individual ORtg/DRtg, PPP, Usage%, Guarded%, board %, Defended FG%, TOV%, PER — pace-adjusted, no minute tracking needed. | The first real defense stats beyond blocks/steals; volume vs. efficiency clear. |
| ★ Player badges (2K-style) | Percentile-ranked, volume-gated badges in Gold/Silver/Bronze tiers with a transparent prerequisite stat. | Legible, engaging language players and parents love — gated against noise. |
| Player archetypes + similarity | K-means clustering on style features with named archetypes; cosine "who plays like X?" lookup. | Understand a player's role without jargon; find comps for scouting. |
| Four Factors + breakeven | Dean Oliver four factors (offense/defense) and a 2s-vs-3s breakeven recommendation. | The gold-standard win drivers, plus "shoot more 2s or 3s" answered. |
| ★ Defensive matchup grid | Per-defender FGA faced, FG% allowed, by-shooter and by-zone breakdown, difficulty-weighted assignment credit. | See if a defender is hiding on weak shooters or matched on the ace. |
| Game flow: buckets & rotation | Paint / second-chance / off-TO / fast-break / bench scoring; full rotation minutes; scoring runs. | Where points came from, who played with whom, and momentum swings. |
| Trends, streaks & season highs | Rolling-average form, season highs, double-digit streaks per stat. | Quantifies "hot" vs. "slumping" against the season average. |
| Foul & free-throw detail | PF committed/drawn, FTA/FTM, FT% by half, team fouls by quarter (NFHS). | Foul trouble and pressure sensitivity, plus discipline over time. |
| Comprehensive flat stat table | One row per player, every metric, with 95% Wilson confidence bands. | A complete profile in one row — honest about small samples. |
| ★ Empirical-Bayes stabilization | Beta-binomial shrinkage on rates; ratings regressed by games played; Wilson intervals. | A hot 2-game night isn't proof of elite status — honest on a thin book. |
| ★ Predictive lineup simulator | Bottom-up five-man projection with usage renormalization, league-calibrated to ORtg/DRtg. | "What if we start X instead of Y?" — accounts for pairing, not PPG sums. |
| Pythagorean wins | Expected record from ORtg vs. DRtg; quantifies luck vs. actual. | Are we overperforming (lucky) or underperforming (unlucky)? |
| Shots-created accounting | Own attempts + assist passes + screen assists, decomposed into shoot/pass/screen. | Separates scorers from facilitators; on-ball vs. off-ball creation. |
| League aggregation (no tracking) | Full-league SRS, records, home-court effect, class competition from final scores alone. | The whole league landscape with zero video tracking. |

### C. Dashboards & Views

| Feature | What it does | Why a coach cares |
|---|---|---|
| ★ Analytics Hub | One-screen season snapshot: KPIs, power landscape, luck distribution, leaders with sparklines, Game of the Season (excitement index), live search. | Everything that matters at a glance the moment you open the app. |
| ★ Team Dashboard (6 tabs) | Overview, Players, Schedule, Charts, Scout, and a Lab tab (RAPM, lineups, play types, correlations). | The entire team playbook on one page — overview to advanced labs. |
| ★ Player Analytics Lab (7 tabs) | Leaders, Ratings, Shot Lab, Compare, Player Profile, Lab (badges/archetypes/similarity), Glossary. | Full player lab: ratings, shot charts, archetypes, peer comparison. |
| ★ Rankings / Power Rankings | Overview, Team deep-dive, Compare, Tracked (possession ratings), Team Charts, League lab — district standings, composites, percentile bars. | League power structure with standings and advanced composites. |
| ★ Composite team indices | League-relative Dominance, Consistency, Clutch, Momentum, Luck (all 0-100). | See not just who wins, but how — blowout, clutch, hot, lucky. |
| ★ Shot charts & heat maps | Zone maps and tap-captured hexbin/scatter with FG% by zone; league/team/player scope. | Where you shoot and make; opponent personnel tendencies. |
| ★ Schedule page + calendar | Month grid with game-load dots, Game of the Day, Upset Alert, Day's Leaders, embedded film widget. | All games at a glance; drill into any day's results and highlights. |
| Game preview / matchup predictor | Projected score, win probability, margin breakdown; ★ Monte-Carlo distribution and printable one-pager. | Expected margin and odds before tip-off, with the math shown. |
| ★ Season simulation | Monte-Carlo replay of every game; expected wins vs. actual = luck. | True talent vs. record; spot lucky/unlucky teams and final standings. |
| ★ Tournament bracket simulator | Seed a field, run thousands of brackets; championship odds and survival curves. | Playoff prep — title odds and which seeds are live. |
| ★ Lineup creator | Projected ORtg/DRtg/Net vs. league, observed-together chemistry, bench-swap finder. | Test lineups, see your chemistry five, find upgrade swaps. |
| Best-Five leaderboards | Top-5 league leaders across ~60 stats, grouped by category. | Scout league talent by skill and position. |
| Leaderboards w/ volume gates | Sortable per-stat tables with qualification minimums; CSV export. | Reliable leaderboards that filter out one-lucky-make noise. |
| Percentile profile bars | Color-coded 0-100 rank bars on Power, Margin, Offense, Defense, SOS, SOR, etc. | Where your team stands on every metric, instantly. |
| ★ Data Explorer | Stat grid, scatter explorer (OLS trendline, Pearson r), PCA style map, correlation heatmap, shot maps. | A freeform analytics playground — build any chart, correlate any stats. |
| ★ Officials Analytics Hub | Per-ref FPG, home/away lean, whistle archetype quadrant, per-ref game logs. | Officiating trends and home-court bias, data over anecdote. |
| Possession Outcomes Sankey | Flow of possessions → shot type → make/miss/turnover. | Shot selection and turnover profile at a glance. |
| Game Excitement Index + WP curve | GEI score and a win-probability timeline per game. | "That was a nail-biter (GEI 87)" — show the team the swings. |

### D. Coach Outputs & Scouting (Printable Deliverables)

| Feature | What it does | Why a coach cares |
|---|---|---|
| ★ Printable scout sheet | One-page PDF/HTML: keys to guard/attack, four-factor percentiles, hot zones, breakeven economics, personnel cards, team shot chart, auto-tips, and a blank-court grid to sketch counters. | The game plan you tape to the locker-room whiteboard — works offline. |
| ★ Player season / recruit card | Full-page card: five rating tiles, KPIs, percentile ranks, badges, season highs, recent log, personal shot chart. | A shareable card for parents and college coaches that shows where a player ranks. |
| Game recap (PDF/HTML) | One-page box-score summary with scoring breakdown and both teams' boxes. | Print or text after the game to recap for staff and boosters. |
| ★ 7-tab interactive box score | Overview, Flow, Shooting, Quarters, Lineups, Box (MaxPreps export), Four Factors. | Deep single-game dive — what happened, when, and why. |
| MaxPreps both-teams CSV | Both teams, one row per player, ready for upload. | Report the box to MaxPreps without re-typing it. |
| Individual team box CSV | One team's box with totals row for spreadsheets or email. | Export one team's stats fast. |
| ★ Four-factor percentile bars | Horizontal league-percentile bars, color-coded strength/weakness. | See the percentile, not just the number — defend the green, attack the red. |
| ★ Personnel cards (GS% + badges) | Per-player card with OVR, GS% (inferred starts), category breakdown, splits, role note, badges, creation mix. | Know who starts, what they're good at, and how to guard them. |
| ★ Tap-captured shot chart | Plotly half-court of every make/miss with distance/value on hover; hexbin view. | Exactly where a team or player attacks — real dots, not bubbles. |
| Shooting by zone (2PT/3PT) | 5 zones × 2 point types, FGA/FGM/FG% per cell. | Where they want to shoot and where they finish. |
| ★ 2s-vs-3s breakeven | Breakeven 3P%, EV per 2 vs. per 3, verdict "more 2s / more 3s / balanced." | The game-plan question answered on one page. |
| Per-player 3-point profile | Each player's 3P% vs. team breakeven (above/below). | Who should shoot threes and who should work for twos. |
| ★ Auto scouting report | Rule-based keys ("pressure the ball," "run shooters off the line") from transparent thresholds. | 3–5 actionable points without reading every stat — no black box. |
| ★ Scoring by possession length | Transition/early/half-court PPP, FG%, and creation mix. | Adjust transition defense or half-court pressure accordingly. |
| ★ Blank play diagrams | 8 blank half-courts on the printed sheet for hand-drawn plays. | Print and sketch counters on the same sheet — no drawing UI needed. |
| ★ Possession WPA timeline | Per-possession win-probability swings, runs highlighted. | See which possessions decided the game. |
| Possession outcomes breakdown | Score% (2/3 split) vs. TOV% per team per game. | Lost because they scored, or because we turned it over? |
| ★ Shot-quality metrics (SMOE/xFG%/xPPS) | Actual vs. expected shooting, the luck filter, per game. | "We shot great but got unlucky" — quantified. |
| Contested vs. open splits | FG% on open vs. contested 2s and 3s. | "Their 3s drop 38% open, 22% contested — crank pressure." |
| ★ Lineup +/- & efficiency | Every 2–5 player combo on the floor: possessions, +/-, on-court ORtg/DRtg. | Spot chemistry problems or winning combos within a single game. |
| ★ Matchup prediction sheet | Printable: projected score, win %, spread, margin components, optional sim and possession projection. | Pregame scouting with the math, not gut feel. |
| Manual box-score entry | 14-stat grid for non-tracked games; still computes PPP/eFG%/TS%/ORtg/DRtg. | Record a JV game and still get efficiency metrics. |
| ★ Games-Started % (GS%) | Inferred starter rate from tracked games. | Know the role — starter vs. reserve — instantly. |

### E. Platform · Multi-Coach · Co-op

| Feature | What it does | Why a coach cares |
|---|---|---|
| ★ Multi-coach OIDC login + roles | Google/Microsoft sign-in, admin/coach hierarchy, per-coach identity/team/plan gating. | Multi-coach deployments scale without user-sync pain. |
| Free vs. Paid depth gate | Free = box scores + standings; Paid unlocks tracked depth; `paid_until` honors trial windows. | Box scores always free as the hook; paid unlocks the firepower. |
| ★ Coaches' Co-op (reciprocal pool) | Team-level opt-in: share your tracked games, scout the whole league back; reciprocal, monotonic, ban-able. | Scouting intel on every league opponent at once — one toggle. |
| ★ Multi-team staffing | One coach mapped to boys + girls (or any combo), coupled in the co-op, one login. | Prep both squads from one account and one shared pool. |
| ★ Per-coach tracker tokens | Unique, revocable Bearer token per paid coach; games stamped to the coach. | A private, rotatable mobile credential — no shared master token. |
| ★ Assistant-scorer guest links | Reusable, labeled, individually-revocable log-only links. | Hand a parent or JV coach a link to log — no account handoff. |
| ★ Delete-request approval queue | Non-admin deletes queue as pending; admin accepts/rejects. | No coach can accidentally nuke a roster or season. |
| Write audit log | Every insert/update/delete on user data recorded with actor/time/detail. | Trace exactly who changed what, when — blame-free troubleshooting. |
| ★ Admin moderation | Pool bans (purge bad data) and clean user removal that preserves team history. | Quarantine a bad-data coach without deleting their team's records. |
| Season archiving + open archives | Stamp and roll over seasons; past seasons are free, full-depth, read-only. | Multi-year records that stay with the school; clean slate each fall. |
| Officials tracking | Per-ref foul analytics, lean, scoring environment, game logs. | Spot tight/lenient refs; assign crews fairly. |
| ★ Per-coach private notes | Team and scout notes scoped per coach, no cross-coach bleed. | Your game-plan hunches stay yours; move with you between teams. |
| Theme & per-coach prefs | Dark presets, accent colors, layout, default team — per user. | Each coach's display is independent. |
| Native boys + girls separation | `gender` on teams drives every filter; girls and boys never mixed. | Equal airtime for girls' basketball; clean gender splits. |
| SVG court geometry | Scalable court with zone overlays and tap x/y, mobile-friendly. | Precise input and visualization on any screen. |
| Per-season SQLite database | Portable, local-first store with soft deletes and change-request queuing. | Reliable data, zero cloud lock-in, full CSV/PDF export. |

---

## 3. What to Lean On

### Hero Features & Headline Positioning

**Headline:** *College-level analytics for a high-school budget — no cameras, no sensors, no tagging fees, $100 a year.*

| Hero | Marketing angle | Proof points |
|---|---|---|
| **The Analytics Engine** (SRS power ratings + dual-model WPA + RAPM) | "See which teams are actually good and which players win close games — not just who scores." Frame it as the reason every other feature is trustworthy. | Genuine ridge-regression RAPM and opponent-adjusted SRS, the metric families NBA front offices use — not box-score proxies. Nothing at this price is even adjacent. |
| **Tap-to-capture shot locations** (no hardware) | "Real shot charts from your thumb, not a $2k camera rig." The hero screenshot/GIF — it sells the whole product in three seconds. | Before/after: vague 5-zone guesses vs. exact dots. Precise x/y tap capture is unique at this price; it feeds heat maps, scout sheets, and play-type analysis. |
| **Hardware-free Coaches' Co-op** | "Track one team, scout the whole league." Sell the early-mover advantage and the fairness of reciprocity. Pitch ADs and conferences, not just individuals. | Reciprocal, monotonic share-to-scout pool. More data = sharper league-wide ratings. A network effect no single-team tool can offer. |
| **Offline-first PWA + guest link** | "Hand the phone to a parent. Keep your eyes on the game." Lead on reliability (never lose a possession) and delegation. | IndexedDB queue + UUID dedupe + service worker; reusable, instantly-revocable log-only link. Removes the #1 objection: "I don't have time to track every game." |
| **Printable scout sheets + recruit cards** | "Your game plan, printed and on the whiteboard before tip-off." Sell the artifact, not the algorithm — coaches trust paper. | Opponent keys, four-factor percentiles, hot zones, breakeven, blank-court grid; recruit cards with shot charts and percentile ranks drive word-of-mouth. |

### Don't Lead With

- **Manual box-score entry / light analytics** — table stakes; GameChanger/MaxPreps do it free. Leading here cedes the whole differentiation.
- **MaxPreps / CSV exports** — a convenience that signals "data-entry tool," not "analytics platform."
- **Officials / whistle analytics** — distinctive and fun, but niche and politically touchy with refs; keep it a delight-on-discovery.
- **Season archiving, themes, admin/audit controls** — necessary plumbing, emotionally inert. They reassure during evaluation; they don't win attention.
- **Generic "7-tab box score" and long feature-count lists** — depth is the moat, but tab counts read as overwhelming. Lead with one outcome.
- **Pythagorean wins, Four Factors, archetypes, badges in isolation** — strong supporting acts (badges especially with players/parents), but as a lead they sound like jargon or gimmicks.
- **Free-vs-paid gating mechanics** — a business-model detail, never a marketing hero.

---

## 4. Messaging Kit

### Candidate Taglines

1. **"College-level analytics. High-school budget."**
2. **"Track one team. Scout the whole league."**
3. **"Real shot charts from your thumb — not a $2,000 camera."**
4. **"The analytics brain for your basketball program. $100 a year."**
5. **"No cameras. No sensors. No tagging fees. Just the numbers that win games."**

### Elevator Pitch

> Track a game on your phone — no camera, no WiFi needed — and HoopTracks turns those taps into college-level analytics: opponent-adjusted power ratings, possession-level RAPM, real shot charts, and printable scout sheets. The depth Synergy and Hudl charge four figures for, for $100 a year.

### Feature → Benefit One-Liners (Heroes)

- **Analytics Engine:** "It tells you which teams are actually good and which players win close games — math NBA front offices use, for the price of a team meal."
- **Tap-to-capture shot charts:** "Tap where the shot went; a real shot chart builds itself. No camera, no zones, no guessing."
- **Coaches' Co-op:** "Share your tracked games and scout every opponent in your league back — one toggle."
- **Offline PWA + guest link:** "Hand a parent a link, keep coaching, and never lose a possession when the gym WiFi dies."
- **Scout sheets / recruit cards:** "Your full game plan on one printable page — and a recruit card parents and college coaches actually want."

### One-Line Pitch per Buyer Persona

- **Head Coach (own pocket):** "The only real advanced-analytics engine a high school coach can actually afford — ratings, shot charts, lineups, and printable scout sheets for $100, no cameras, works courtside with no WiFi."
- **Assistant Coach:** "Turn the bench stat job into a live, self-correcting box score on your phone — the head coach shares one revocable link and the box, +/-, foul trouble, and MaxPreps export build themselves."
- **Athletic Director:** "Outfit your whole basketball program — boys and girls — with real analytics for $150 a year, no hardware, no contracts, with admin roles, an audit trail, and history that stays with the school."
- **Dual-Staff Coach:** "Run boys and girls from one login for $150 total — coupled co-op scouting for both schedules and cleanly separated gender data."
- **Club / AAU Coach:** "Hardware-free, WiFi-proof tracking that turns a chaotic tournament weekend into 2K-style player ratings, shot charts, and printable development cards parents and recruiters want."

---

## 5. Personas & Objection Handling

| Persona | Core pains | What sells them | Key rebuttals |
|---|---|---|---|
| **HS Head Coach** (own pocket, no budget) | No analytics budget; Hudl/Synergy = $1.5k–$7.5k + hardware; coaches by gut; free tools only give a box score; lone 11pm film scouting; flaky gym WiFi; distrusts black boxes. | Flat $100/team, no hardware; offline PWA; SRS power ratings; 2s-vs-3s breakeven + rule-based scout report; printable scout sheet with blank courts; tap shot charts; 5-man unit ratings + lineup creator; glossary + Wilson bands. | *"GameChanger's free"* → those give a box score your scorebook already has; HoopTracks is the only $100 tool with a real engine on top. *"I have Hudl"* → keep it for film; this is the analytics layer Hudl charges Assist money for. *"$100 is real money"* → under $10/mo, pays for itself in two close-game decisions; free tier first. *"No time to track"* → hand a parent the guest link; ratings work from final scores with zero tracking. *"Solo founder risk"* → offline-first, portable SQLite, full CSV/PDF export, no lock-in. |
| **Varsity Assistant** (runs bench stats) | Paper sheet always behind; unreadable scouting notes; mis-tags hard to fix; no budget authority; can't answer "who's hot/in foul trouble" fast; re-keys the box into MaxPreps nightly. | Log-only guest link; live box score with foul-trouble color coding + live +/-; undo + Event Editor; laptop backup writer; live PBP and shot chart; MaxPreps CSV; printable personnel cards (GS% + badges). | *"Can't buy it"* → head coach buys one plan, generates a free revocable link for you. *"Paper's faster"* → paper gives a box hours later and a hand-tallied +/-; this is live, plus auto MaxPreps export. *"What if I mis-tag?"* → tap Undo, or fix it later in the Event Editor; score and +/- re-derive. *"Phone dies / WiFi drops"* → events queue and sync; a laptop can keep logging into the same game. |
| **Athletic Director** (tight dept budget) | Can't justify four-figure-per-sport spend; needs Title IX defensibility; must control multi-coach access; fears accidental deletes; dislikes multi-year contracts; needs adoption without IT/AV; history must survive turnover. | Flat $100/team or $150 boys+girls bundle, no per-camera/per-seat/lock-in; native boys+girls under one login; OIDC roles; delete-approval queue + audit log; admin moderation that preserves history; season archives; no hardware/offline PWA. | *"Single-founder product"* → competitors cost 15–75x more and need cameras/taggers; HoopTracks has roles, audit log, approval queue, and portable export — no lock-in. *"Title IX"* → the $150 bundle equips boys AND girls identically under one bill — the clean choice. *"Accidental deletes"* → non-admin deletes queue for your approval; every change is audited; departing coaches removed cleanly, history intact. *"No IT/AV"* → nothing to provision; a web app + add-to-home-screen PWA on coaches' phones. |
| **Dual-Staff Coach** (boys + girls, one school) | Prepping two seasons at once; tools price per team; juggling two logins/spreadsheets; doubled opponent scouting; privacy settings bleed between teams; can't scope assistant access per squad. | $150 bundle (2nd team heavily discounted); multi-team staffing under one login with gender radios; co-op coupling; reciprocal league pool feeds both schedules; per-team scoped notes + default-team; multiple labeled revocable links; War Room per squad. | *"Two teams adds up"* → $150 total, not $100 each; one login, one bill. *"Two teams = a mess"* → gender radios keep data split; notes scoped per team; default-team jumps you fast. *"Don't want to re-scout the league"* → one co-op toggle, both squads coupled, both scout the whole pool. *"Assistant access"* → issue separate labeled log-only links, each individually revocable. |
| **Club / AAU Coach** (adjacent buyer) | Box apps treat 12U as a stat dump; no scouting on unseen tournament opponents; parents want development shown; volunteer/low-paid; terrible tournament WiFi; constant roster churn. | Offline PWA (no WiFi, no install); tap shot charts + per-player charts; five-pillar 0-100 ratings + 2K badges; printable season cards; archetypes + similarity; quick-add mid-game; empirical-Bayes stabilization. | *"Built for HS"* → the engine works off whatever you track, and stabilization is built for short books; the development tools are exactly what club parents/recruiters want. *"$100 is a lot for a volunteer"* → flat, no hardware, cheaper than a tournament entry; free tier first. *"No WiFi / no setup"* → offline-first home turf; quick-add a player mid-game; no install. *"Roster churns"* → quick-add handles churn live; season archiving keeps a clean slate with full-depth archives. |

---

## 6. How to Market It

### Channels

| Channel | Tactic | Effort | Why |
|---|---|---|---|
| **X / hoops-coach community** | "Numbers-but-coachable" account; reply-guy into the hoops-Twitter graph; daily free artifact from public scores (power tables, luck takes); 3–4 app-screenshot tips/week; pinned 45-sec demo; DM engaged coaches a free-team offer. | High | Zero spend, where HS coaches already are, and your engine output *is* the content nobody else at $100 can post. |
| **r/BasketballCoach + r/Coaching** | Trust-first: 3 weeks of genuine "scout without Hudl money" answers, then a flagship AMA-style post with screenshots; free season to the first 25. | Medium | High-intent audience priced out of Hudl/Synergy — your exact wedge; the post stays searchable for years. |
| **State coaches associations** | Home state first: free season for board members + a free 20-min clinic breakout; bring printed scout sheets and cards as handouts; ask only for a newsletter mention. Repeat state-by-state. | High | One association blast reaches hundreds of trusting in-state coaches — the cheapest path to the density the co-op needs. |
| **Coaching clinics** | Skip paid booths; run a free chalk-talk or a vendor-hall table with a live tracker + printed sheets; email-capture raffle; be the "analytics guest" on virtual clinics. | Medium | Coaches buy from people they've watched present; a live tracker + printed sheet is a 30-second close. |
| **Hudl-adjacent (complement)** | "Keep your Hudl film, add the analytics layer." 2-min "HoopTracks + Hudl" video; answer "is Hudl Assist worth it" threads with the hardware-free alternative. | Medium | Coaches already have film; ride alongside it instead of asking them to switch. |
| **Flagship demo video** | One 3–5 min screen recording + three 30–45s cutdowns (offline log / tap-shot / one-click scout sheet); YouTube + landing embed; captioned for silent autoplay. | Medium | The differentiators only land when seen moving; one demo is reusable currency for every channel. |
| **Self-serve free-trial funnel** | Wire the existing `paid_until` trial into a no-card "30-day full season" button; OIDC sign-in → auto-grant → guided first game → day-21 "your season so far" email with their own data. | Medium | NOT built yet — payments are MANUAL today (admin sets `paid_until`; no Stripe). This funnel is the build; until then, comp/grant by hand. Conversion moment is showing a coach THEIR data, so push to first-game-tracked fast. |
| **Shareable player cards** | One-tap "Share card" with a "Made with HoopTracks" footer + URL; "recruit card" framing for seniors. | Low | The card already exists and is good; player/parent enthusiasm reaches coaches at other schools at near-zero cost. |
| **Guest-link Trojan horse** | Market the log-only link as "have a parent or JV coach log the game"; soft "want this for your own team?" prompt in guest mode. | Low | Already shipped; puts the product in adjacent coaches' hands (JV/feeder/AAU) for free. |
| **Local-cluster cold outreach** | Spreadsheet every HS in your metro; personalized cold email with a free power rating run on their league's public scores; free season if interested. | Medium | League analytics need zero tracking, so you can produce a real personalized artifact before sign-up — and seed co-op density. |

### Content Ideas

- "This 12-0 team is actually unlucky" — weekly Pythagorean/luck take naming a real local team.
- "Should your team shoot more 2s or 3s?" — breakeven explainer with the one-page output.
- "What Hudl Assist pays taggers for vs. what HoopTracks computes from a tap for $100."
- "I gave a parent a link and they tracked the whole game" — guest-link clip.
- Recruit-card reveal threads ("percentile ranks + shot chart + badges").
- "5 stats your box score is hiding" carousel (guarded FG%, RAPM, lineup +/-, creation mix, clutch WPA).
- "No camera, no laptop — a full scouting report from a phone."
- 2K-style badge reveals engineered for player/parent screenshots.
- "Scout sheet in 60 seconds" speed-run.
- Officials teaser: "Which ref calls the most fouls in our conference?"
- Co-op explainer framed as a movement: "Share your games, scout the league back."
- March season-recap auto-cards at the emotional peak.
- Off-season AAU angle: "Walk into tryouts with a data card."
- Pinned comparison table: HoopTracks vs. GameChanger vs. MaxPreps vs. CourtBook vs. Synergy/Hudl (price · hardware · real engine yes/no).

### Growth Loops

1. **Co-op density loop (core flywheel):** each coach who shares makes the pool more valuable for every other coach in the conference — concentrate one conference/state at a time until "every opponent is scoutable," then switching cost rockets.
2. **Player-card referral loop:** coach texts a card to parents/recruiters → footer + URL exposes the brand → a new coach signs up → makes more cards.
3. **Guest-link seeding loop:** paid coach hands a link to a parent/JV/AAU coach → that guest experiences the product → converts to their own team → hands out their own links.
4. **Association/clinic loop:** free board seasons + a clinic talk → coaches vouch → newsletter mention → new sign-ups deepen the same conference's co-op → stronger pitch to the next association.
5. **Content-from-data loop:** every tracked game and public score becomes shareable content → reach → sign-ups → more data → more content.
6. **Season-recap loop:** March "our season in numbers" cards posted at peak pride → exposure right as next-season planning starts.
7. **Free-tier loop:** free box scores + power rankings pull coaches in → they see their team ranked → curiosity → trial → first game tracked → their own shot chart → convert.

### Demo Script (3–5 min, ordered beats)

1. **0:00–0:20 — Hook/pain:** "Head coach, no analyst, no camera budget, Hudl wants four figures. Here's a full possession-level scouting operation on the phone in your pocket for $100 a year." Show the PWA icon on a home screen.
2. **0:20–1:00 — Log courtside:** Open the tracker, pick the on-court five, tap a shooter, tap *where* the shot went. Show the live score + sync dot, then flip to airplane mode and keep logging — "no WiFi at the gym? It queues and syncs, never loses a tap."
3. **1:00–1:40 — It's already a box score + shot chart:** Cut to the live box score and the shot map filling in (green makes / red misses). "No separate stat sheet, no camera — your taps are already a shot chart and a +/-."
4. **1:40–2:40 — The engine (the $100 differentiator):** Jump to the dashboard. Show three things fast — (1) opponent-adjusted power ratings, (2) a player card with RAPM + guarded FG% + 2K badges, (3) one lineup's observed net rating. "Synergy and Hudl Assist pay humans to tag this. We compute it from your taps. 15 to 75x cheaper, zero hardware."
5. **2:40–3:30 — The scout sheet (the close):** Open an opponent, click Print, show the one-pager — keys, hot zones, breakeven 2s-vs-3s, personnel cards with badges, blank half-courts. "Tape this to the locker-room whiteboard. One click."
6. **3:30–4:15 — Share + team:** Flash the printable recruit card ("text this to a parent or college coach"), the assistant-scorer guest link ("let a parent log — revoke anytime"), and the boys+girls one-login bundle. Co-op line: "Share your games, scout the league back."
7. **4:15–4:45 — Price + CTA:** "$100 a year, one team. $150 for boys and girls. Flat. No camera, no per-seat, no contract. Free box scores forever — start a free 30-day full season right now, no card." End on the URL.

### How to Present $100 / $150 Pricing

**Anchor against the ceiling, sell at the floor.** Lead every pitch with the competitive sandwich:

> "GameChanger and MaxPreps are free but stop at the box score. Synergy and Hudl Assist give you real analytics — but they cost four figures AND pay humans to tag your film. HoopTracks gives you the engine they charge for, computed from your phone, for $100."

- Make the number feel like a rounding error against what coaches assume analytics costs.
- Frame it as flat, honest, no-asterisk: **$100/year per team, $150/year boys+girls at one school** — no camera, no sensors, no per-seat, no per-game fees, no multi-year contract.
- Make the bundle obvious: **"$150 is $75 a team — a second program for half price, one login."** (Present it as a deliberate steal that earns loyalty now while you build density — not the long-term ceiling.)
- Always pair price with the unit it replaces: "less than one hour of a private analytics consultant," "a fraction of one Hudl Assist game-exchange package," "about $8 a month."
- **Never discount the headline number** — the flat price *is* the brand. Give value away instead: free box scores forever, a no-card 30-day full season, free founding-cohort seasons for testimonials.
- **Show price only after the coach has seen their own data.** A shot chart of their own team makes $100 feel trivial; leading with price makes it the whole conversation.

---

## 7. First 90 Days (Solo-Founder Launch Sequence)

1. **Days 1–7 — Lock assets, pick one cluster.** Choose ONE home state/conference to concentrate density. Record the flagship 3–5 min demo + 3 cutdowns; write the comparison/pricing pin; set up the X account and YouTube channel. Build the self-serve 30-day trial (Stripe checkout → webhook → `paid_until`) end-to-end so the funnel runs unattended — until that ships, trials are granted MANUALLY by the admin (no Stripe yet).
2. **Days 8–14 — Seed the founding cohort.** Personally onboard 5–10 friendly local coaches with FREE full seasons in exchange for a testimonial and demo-data permission. Goal: real tracked games in the DB so every future demo shows live, local data.
3. **Days 15–30 — Go public.** Post the demo across X, r/BasketballCoach (trust-first, after 2 weeks of genuine replies), and 2–3 Hudl/HS-hoops Facebook groups. Start the daily X cadence (one artifact/day from public scores). DM free seasons to engaged coaches. Begin the local cold-email run using League Analytics artifacts.
4. **Days 31–45 — Associations + cards.** Email the home-state association: free seasons for the board + offer a free clinic breakout, ask only for a newsletter mention. Line up 1–2 coach-podcast/webinar "analytics guest" spots. Ship the one-tap "Share card" footer so word-of-mouth starts compounding.
5. **Days 46–60 — Convert.** Day-21 trial-end emails go out to the founding cohort and public trialists, each showing THEIR data (shot chart + power rank + renewal link). Publish 2–3 testimonials/case studies. Push the $150 boys+girls bundle to every dual-program school in the cluster.
6. **Days 61–75 — Trigger the co-op flywheel.** With several tracked teams in the cluster, showcase the Coaches' Co-op — "every team in your conference is now scoutable; share back to see it." Use density as the closing argument on the remaining holdouts.
7. **Days 76–90 — Systematize + expand.** Bank a repeatable playbook (assets + email templates + clinic deck). Pick the SECOND state/conference and re-run the association + cold-cluster motion. Audit the funnel for the single biggest drop-off (sign-up? first game tracked? renewal?) and fix it. Lock in renewals from the founding cohort before their free year ends.

---

*HoopTracks — the analytics brain for your basketball program. No cameras. No sensors. No tagging fees. $100 a year.*
