# live.hooptracks.com — review, 2026-09-12

Read against the **running production site**, not the repo: every screenshot and
number below came from browsing `live.hooptracks.com` tonight and from its own
`/api/public/*` responses. Two defects found there are fixed in this run; one
finding is reported and left for you, because it is a product call.

## What it is, and how big

| | |
|---|---|
| `tracker/static/live_index.html` | 602 lines — landing: live games, latest finals, a date slate, and a team directory |
| `tracker/static/live.html` | 439 lines — one game: linescore, win probability, box score, shot chart, play-by-play, officiating |
| `tracker/static/live_team.html` | 211 lines — one team: record, rank, results + schedule |
| `helpers/public_feed.py` | 692 lines — the allowlist that shapes every public payload |
| **total** | **~1,950 lines, no build step, no framework** |

Five unauthenticated endpoints, all shaped exclusively by `public_feed`:
`/api/public/game/{token}`, `/api/public/team/{id}`, `/api/public/scoreboard`,
`/api/public/teams`, plus the QR.

**The allowlist discipline is the best thing in this code.** Names never cross
the fence — jersey numbers only, officials as R/U1/U2, no Power, no Rating, no
AdjNet, no tags. One module decides what is public and every route goes through
it. That is the right architecture for the thing with the largest blast radius
in the product, and it is worth keeping exactly as strict as it is.

---

# Verdict on "are we wearing too many hats?"

**Not in the code. In the claims.**

~1,950 lines with no framework and no build step is not an over-extension; the
whole live app is smaller than the Input Hub was this morning. It costs almost
nothing to carry.

The over-extension is that this site currently publishes **four different
products** to the public:

1. a **live game centre** (linescore, win probability, box, shot chart, PBP),
2. a **scoreboard / calendar** for every date and all 1,448 teams,
3. **team profile pages** (record, PPG, streak, form, schedule),
4. a **public ranking** of all 1,448 teams — a number, per team, by name.

Numbers 1–3 are facts a fan already believes you have: what the score was, who
played, when they play next. Number 4 is an **opinion with your name on it**, and
it is the only one that generates arguments, support load and reputational risk
— which is exactly what §3 below turns out to be about.

**Recommendation: keep 1, 2 and 3. Reconsider 4.** Not because ranking is wrong —
it is the engine's best work — but because a public ordinal over every team in
the state is a product with its own support burden, and it is the one thing here
that a one-person team cannot defend at 10 p.m. after a district game.

**The live game page is the funnel and it earns its place.** The QR at the gym
door → a parent watching a real win-probability curve and a real box score →
"who does this for you?" → the coach. That page is genuinely better than what
most high-school programs can show, and it renders well on a phone (checked at
375 px: the score, linescore, WP chart and a horizontally-scrollable box all
land). Do not trim it.

**The officiating table — RULED, 2026-09-12: it stays, and it stays for the
reason it was built.** I flagged it as the highest-risk block on the page and
argued officials were a customer segment being over-served. **Both halves of
that were wrong**, and the founder's correction is the design:

> Officials are **not** a customer segment currently. The officiating table is
> there **exclusively so assigners can check, in real time, whether a ref is
> being a hero**. Assigners have been asked and they like it. From a founder who
> refereed at the highest level of high-school basketball: you need thick skin,
> and you do not call 7 fouls on one team and fewer than 4 on the other. The
> table exists **by design, to show who is ruining a game.**

So the asymmetry a parent can read off it is the *product*, not a side effect —
the whole point is that a lopsided split is visible to somebody who can act on
it. R / U1 / U2 anonymity is what keeps it a professional tool rather than a
pile-on. **Recorded as a decision, not an oversight** (THE BOOK §14's rule), so
no future sweep "fixes" it.

---

# 1 · FIXED — the front door was blank for eight months of the year

**What I saw.** `live.hooptracks.com`, tonight: a Scores/Teams toggle, a date
picker on 09/12/2026, and the sentence *"No games on this date."* Nothing else.

**Why.** The LATEST FINALS rail is gated on `g.date >= date('now','-3 day')`
(`public_feed.scoreboard`). A high-school season runs November to March, so from
March to November the rail is empty, the slate for any date is empty, and the
landing page has nothing on it. `/api/public/scoreboard?date=2026-09-12` returned
`live: 0, games: 0, recent: 0` — measured on production.

That is the public front door, blank, through the month you are training coaches
in.

**Fixed.** The three-day floor now applies only while there is something else on
the page. With no live game and an empty slate, the rail falls back to the last
twelve finals in the book however old they are. Same date now returns **12
recent finals**. In season nothing changes — a rail of three-month-old scores
next to tonight's slate would be noise, and the floor still suppresses it.

**Still worth considering (not done):** out of season, the Teams tab is the
better landing view — it is full of content year-round. Defaulting to it when
the scoreboard is empty is a five-line change in `live_index.html`, but it
changes which product a first-time visitor meets, so it is yours to call.

---

# 2 · FIXED — a team's public page read 0–0 the moment next season's schedule was entered

**What I saw.** `live.hooptracks.com/team/1` — Adair Girls, a 29-3 program —
showing **0–0**, with 23 games listed as "Upcoming" and no results at all.

**Why.** `public_feed.team_profile` resolved the season from the team's most
recent **dated** game:

```sql
SELECT season FROM games WHERE team1_id=? OR team2_id=?
ORDER BY date DESC, id DESC LIMIT 1
```

Adair's most recent dated row is 2027-02-16 — next season's schedule, already
entered. So the season resolved to one with zero finished games, the results
query found nothing, and the record, PPG, margin, streak and form all went to
zero. The function's own docstring promised the played season ("so a post-
rollover archive still shows the played season"); the `ORDER BY` just never
excluded the unplayed rows.

**This fires exactly when the most people are looking.** Coaches enter schedules
in the autumn. Every program that does so blanks its own public page — in
October.

**Fixed.** The season now resolves from the most recent **finished** game, with
the old behaviour kept as a fallback for a team that has genuinely never played.
The results query keeps that season's games **plus anything still upcoming**, so
the page shows both the record and the next fixture — scoping strictly to the
played season would have fixed the record and then hidden the schedule, which is
the other half of why a fan opens the page.

Verified on the production snapshot: Adair Girls now reads **29–3**, 58.2 PPG,
L1, #49 of 696, 32 finals and 23 upcoming games on one page.

---

# 3 · REPORTED, NOT FIXED — the public rank is computed over a pool the page does not show

**What I saw.** Teams → Boys, out of the box: `#1 MILLWOOD · #2 OWASSO · #5
BOOKER T WASHINGTON · #6 OKARCHE …`. **#3 and #4 are missing**, and a ranking
with holes in it reads as broken.

**What is actually there.** From `/api/public/teams` on production:

| rank | team | state | class | record |
|---|---|---|---|---|
| 1 | MILLWOOD Boys | OK | OK 3A | 27-2 |
| 2 | OWASSO Boys | OK | OK 6A | 24-6 |
| **3** | **Bryant (Bryant, Arkansas) Boys** | AR | — | **1-0** |
| **4** | **Link Academy EYBL Scholastic #2 Boys** | MO | — | **1-0** |
| 5 | BOOKER T WASHINGTON Boys | OK | OK 5A | 24-2 |

Two **one-game** out-of-state entries are ranked 3rd and 4th in the boys pool,
ahead of a 24-2 team. They are then hidden from the list, because the class
chips default to the eight OSSAA classes (`DEFAULT_CLASSES` in
`live_index.html`, a deliberate choice) and those two carry no class label. So
the pool that produces the NUMBER is 743 teams, and the list that shows the
number is Oklahoma only — 266 of 734 boys have no class label and are excluded.

Two separate problems, and they need different answers:

* **The rating.** A 1-0 team should not be third. This is THE BOOK §8.2 (the
  one-game leaderboards) and `thin-books-inflate-plain-z`, surfacing on the one
  page that is not gated behind a login.
* **The presentation.** Even with the rating fixed, a rank computed over one
  pool and displayed inside a filtered subset will keep producing gaps.

**Three ways out, and this is your call, not mine:**

1. **A games-played floor on the public rank.** Under N games (3? 5?), show the
   team without an ordinal — the directory already renders `–` for unranked
   teams, so the machinery exists. Smallest change, removes both symptoms.
2. **Rank within the displayed pool** — "#3 of 468 Oklahoma boys" — and say so.
   This is the house convention already (`pctile_bar` states its pool,
   `pctile-pool-convention`), just not applied here.
3. **Drop the league-wide ordinal from the public page** and keep only the class
   rank, which is the number a parent actually argues about anyway and the one
   the OSSAA ladder makes meaningful.

I did not pick one, because each changes what the public site *claims*, and that
is the "too many hats" question in §0 in its most concrete form.

---

# Smaller notes

* **Name truncation — APPROVED to fix.** "Claremore (Sequoya…" in the hero and
  the linescore at 375 px. `cards.team_short` only strips the " Girls"/" Boys"
  suffix, so it is not enough on its own and the live pages are plain JS that
  cannot import it — the short name has to travel in the `public_feed` payload.
* **A pregame fan page is thin — APPROVED to fill.** Badge, 0–0, "No stats yet",
  "Nothing logged yet". A fan who scans the QR before tip-off gets nothing to
  read. Both teams' records and ranks are already in `teams_directory`.
* **`tracker/demo_tracker.html`** (4.9 KB) is not routed by `api.py` and is not
  referenced anywhere I could find. Probably a leftover; worth confirming before
  it confuses someone.
* **The follow/star list works** and is stored per browser. Nothing public about
  it, no account needed — good call.

---

# Deploy note

Both fixes are in `helpers/public_feed.py`, which the **tracker service**
imports, not the Streamlit app. Restarting `app5-web` alone will not change
`live.hooptracks.com` — the tracker/uvicorn service needs the restart. No static
file changed, so the PWA cache does **not** need a bump this time.
