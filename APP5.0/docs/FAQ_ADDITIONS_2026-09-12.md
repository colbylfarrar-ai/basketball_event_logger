# FAQ — proposed additions and revisions, 2026-09-12

**The app cannot write these.** `pages/15_FAQ.py` renders the plain-text export
of your Google Doc (`helpers/faq.py`, `DOC_ID` 1yW__An6…), pulled on a 6h TTL and
cached in `app_settings`. The Doc is the source; `docs/faq_source.txt` is a
mirror. So everything below is paste-ready text for the Doc, not a code change.

Each item says which existing section it belongs under. **REVISE** items replace
text that is now wrong or out of date; **ADD** items are new.

Written in the Doc's voice: plain declarative sentences, no bold, either a
question as the heading or a `Topic - explanation` one-liner.

Two notes before you paste:

* The state of the Doc as of tonight is 38,197 characters and matches what
  production is serving exactly. `faq:fetched_at` on prod reads 2026-07-31,
  which is not a sync failure — `get_faq` only runs when somebody opens the FAQ
  page, and nobody has since then.
* Every number quoted below was measured tonight on the production snapshot
  (girls 2025-2026, 5,048 walk-forward games, deployed constants). They are in
  the overnight report too.

---

## 1 · REVISE — the uncertainty band, under "War Room And Simulations"

The Doc currently says:

> The honest uncertainty band on a single game is about 11 points. A projected
> four-point win is close to a coin flip, and the app would rather tell you that
> than sell you a lock.

11 was the constant in the code, not a measurement. The app now measures it, and
the real number is wider. Replace that paragraph with:

> The honest uncertainty band on a single game is about 13 points. That is not a
> guess — the app re-played every finished game in the book, predicting each one
> from the board as it stood the day before, and the typical miss on the final
> margin was 9.9 points with a spread of 12.6 around it on the girls' side and
> 13.4 on the boys'. A projected four-point win is close to a coin flip, and the
> app would rather tell you that than sell you a lock.

---

## 2 · ADD — under "War Room And Simulations"

> How accurate is the matchup predictor, really?
>
> Open the War Room, pick Matchup, and open "How accurate is this predictor?" at
> the bottom. It replays the season: every finished game is predicted again from
> the board solved over the games finished strictly before that day, so nothing
> from the game's own day is in the board it was predicted from. On the girls'
> 2025-2026 book that is 5,048 games. It picks the winner 85 percent of the
> time, misses the final margin by 9.9 points on average, and its stated win
> probabilities land within about three points of what actually happened in
> every band — when it says 85 percent it delivers 84, when it says 98 it
> delivers 97.
>
> The panel also shows the ten it got most wrong, which is the part worth
> reading. A model that is never badly wrong is usually a model that is not
> saying anything.

---

## 3 · ADD — under "War Room And Simulations"

> Can I see what the app would have said before the game?
>
> Yes, in two places. Rankings has a week picker that shows the board exactly as
> it stood on a past date, and the War Room's Matchup view has an "As of" picker
> that does the same thing for a projection — pick a date and the projected
> score, the win probability, the margin breakdown and the 20,000-game
> simulation are all solved over only the games that had been played by then.
>
> One caveat, and it is on the screen too. A board rebuilt for a past date uses
> today's model constants, not whatever was in use back then. So it tells you
> what the current model makes of that day, not what the screen actually showed
> you in January.
>
> The auto-scout tells and the game plan are hidden while a past date is
> selected. Those read the whole season's tracked data with no date filter, so
> leaving them up would describe games that had not been played yet.

---

## 4 · REVISE — under "Why Numbers Change"

The Doc already says the constants are re-checked by an automated backtest.
That test now has a screen. Add one sentence to the end of that paragraph:

> You can see that test yourself: War Room, Matchup, "How accurate is this
> predictor?". It reports the model's own error against the two constants it
> most depends on, so the claim is checkable rather than promised.

---

## 5 · ADD — new entries under "Accounts And Roles"

> What can I edit, and what can't I?
>
> You can add. A new team, a new game, a new player, a new official — any coach
> can create those, because that is how a league gets entered and an opponent
> that does not exist yet has to come from somewhere.
>
> You can change your own. Your teams' rows, your teams' games, your teams'
> rosters.
>
> You cannot change somebody else's. Editing another program's team name, their
> roster or the score of a game your team did not play is refused with a
> sentence naming the row. If you paste in a batch and one row is out of scope,
> that row is refused and the rest still saves.
>
> Admins are league-wide, because somebody has to be able to clean up.

> Why does the Input Hub only show my team?
>
> Because those grids are editors, and you can only edit your own. There is a
> "Show the whole league" switch on each of them when you need to see another
> program — to pick an opponent, or to check a game you were not in. Other
> teams' rows are visible there but not editable.

---

## 6 · ADD — new section, or under "Troubleshooting"

> Where did the Roster & District page go?
>
> Into the Input Hub, on 2026-09-12. Three of its four tabs each edited a single
> column of a row the Input Hub was already editing — a player's position and
> status, a team's district, a game's type — so those are columns on the Input
> Hub's grids now. The team search box and the "apply this game type to
> everything shown" bulk control came with them.
>
> Its fourth tab, box score entry, did not fold in. It is a full box-score app
> with a MaxPreps import, and it is the other way a game gets its numbers, so it
> has its own page: Build, Box Score Entry, directly under the Game Tracker.
>
> The Input Hub's Team Schedule section went the same way. It was the same games
> in a one-team view, so it is now a point of view inside Games — League or One
> team — rather than a separate section that could disagree with the other one.

---

## 7 · ADD — under "Current Seasons" or "Past Seasons"

> Why does the app say the season hasn't started?
>
> Because it hasn't. A rollover opens the new season empty, and every read page
> with a season picker notices that and falls back to the last season that
> actually has finished games, with a line at the top telling you which season
> you are looking at. The pages without a picker either read every season at
> once, like the Hall of Fame, or run off the calendar, like Schedule. Nothing is lost and nothing is hidden — the season picker is right
> there. Entry pages behave the opposite way on purpose: a new game you add
> defaults to the current season, because that is the one you are about to play.

---

## 8 · ADD — under "Data Quality And Coverage"

> Do forfeits count?
>
> Not for anything that reads a margin. A 1-0 or 2-0 walkover is recorded, and
> it counts in your win-loss record because you won, but every rating,
> strength-of-schedule and prediction engine drops it. A two-point margin
> against a team you would have beaten by thirty is not information about
> either team, and a team whose only games are walkovers does not get a rating
> at all.

> Does the Neutral checkbox matter?
>
> More than it looks like it does. The projection adds a home-court bump to the
> home side of every game that is not flagged neutral, so a tournament or
> playoff game on a floor neither team owns gets a bump that nobody earned. On
> today's book the flag is set on almost no games, and the measured effect is
> visible: the model leans toward the home side by about 1.6 points in the
> regular season and about 2.7 in the playoffs, and the gap between those two
> numbers is the missing flag. If you are entering a neutral-site game, tick it.

---

## 9 · ADD — under "Troubleshooting"

> It says that matchup is already on the schedule.
>
> Two teams play each other once on a given day, so the app refuses a second row
> for the same matchup on the same date rather than creating a duplicate that
> would double-count in every rating. Edit the existing row instead. If the
> teams genuinely played twice — a tournament with a same-day rematch — put the
> second game on its real date.

> It says the score is owned by the Game Tracker.
>
> That game was tracked play-by-play, so its score is derived from the events
> and typing over it would make the score and the play-by-play disagree. Untrack
> it in the Game Tracker if you really need to score it by hand, or fix the
> mislogged event in the Event Editor, which is almost always the real answer.

---

## 10 · ADD — under "Troubleshooting"

> The FAQ says it's offline.
>
> That is the offline demo build. This page is the only one in the app that
> reaches the internet on a page load, so when the laptop has no connection it
> serves the copy it last synced and says so rather than spending fifteen
> seconds failing. Everything else in the app works from the local database and
> is unaffected.
