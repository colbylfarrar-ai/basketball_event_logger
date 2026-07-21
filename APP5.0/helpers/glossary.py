"""
glossary.py — the app-wide "super stat glossary" (Synergy / Hudl style).

A single source of truth for every stat the app computes: abbreviation, full
name, category, formula, plain-English definition, how to read it, and whether
it is an invented / signature metric unique to this app.

`render_glossary()` is the reusable interactive component — a search box + a
category filter + expandable definition cards — embedded inside the analytics
pages (no standalone page). It is a UI helper (imports streamlit), the mirror of
the Streamlit-free engine, like box_score.py / ui.py.

Definitions are written to match THIS app's engine exactly, including the locked
calls (possession = FGA + TOV; PER = Game Score proxy; Shot Rating = difficulty;
ratings are pool-relative z-scores where 50 = league average).
"""
from __future__ import annotations

import streamlit as st

# Each entry: (ABBR, Full name, Category, Formula, Definition, How to read it, invented?)
# Formula "" means none / counting stat.
STAT_DEFS = [
    # ── Box score (counting) ──────────────────────────────────────────────────
    ("PTS",  "Points",            "Box Score", "2·2PM + 3·3PM + FTM",
     "Total points scored.", "Counting stat — more is better.", False),
    ("REB",  "Total Rebounds",    "Box Score", "OREB + DREB",
     "Offensive plus defensive rebounds secured.", "More is better.", False),
    ("OREB", "Offensive Rebounds","Box Score", "",
     "Rebounds grabbed on the offensive glass after a team's own miss.",
     "Fuels second-chance points.", False),
    ("DREB", "Defensive Rebounds","Box Score", "",
     "Rebounds grabbed off an opponent miss to end their possession.",
     "Ends defensive possessions.", False),
    ("AST",  "Assists",           "Box Score", "",
     "Passes that directly lead to a made field goal.", "More is better.", False),
    ("STL",  "Steals",            "Box Score", "",
     "Times the player takes the ball away from the offense.", "More is better.", False),
    ("BLK",  "Blocks",            "Box Score", "",
     "Opponent field-goal attempts the player blocks.", "More is better.", False),
    ("TOV",  "Turnovers",         "Box Score", "",
     "Possessions lost via bad pass, travel, offensive foul, etc.",
     "Fewer is better.", False),
    ("PF",   "Personal Fouls",    "Box Score", "",
     "Fouls a player commits (charged to the fouler, not the player fouled).",
     "Fewer is better — foul trouble limits minutes.", False),
    ("+/-",  "Plus / Minus",      "Box Score", "team pts − opp pts while on floor",
     "Team scoring margin while the player is on the court.",
     "Positive = team outscores opponents with them on.", False),
    ("MIN",  "Minutes Played",    "Box Score", "Σ possession_secs on floor ÷ 60",
     "Estimated minutes from the time elapsed on possessions the player was on "
     "the floor for. Slightly undercounts (≈16% of events carry 0 secs).",
     "Context for per-minute rates.", False),

    # ── Shooting ──────────────────────────────────────────────────────────────
    ("FG%",  "Field-Goal %",      "Shooting", "FGM / FGA",
     "Share of field-goal attempts made (2s + 3s).", "Higher is better.", False),
    ("2P%",  "Two-Point %",       "Shooting", "2PM / 2PA",
     "Accuracy on two-point attempts.", "Higher is better.", False),
    ("3P%",  "Three-Point %",     "Shooting", "3PM / 3PA",
     "Accuracy on three-point attempts.", "~33% breaks even with a 50% two.", False),
    ("FT%",  "Free-Throw %",      "Shooting", "FTM / FTA",
     "Accuracy at the line.", "Higher is better; ~70%+ is solid.", False),
    ("eFG%", "Effective FG%",     "Shooting", "(FGM + 0.5·3PM) / FGA",
     "Field-goal % that credits a made three for being worth 1.5× a two.",
     "The honest shooting-efficiency number. Higher is better.", False),
    ("TS%",  "True Shooting %",   "Shooting", "PTS / (2·(FGA + 0.44·FTA))",
     "Scoring efficiency across 2s, 3s AND free throws in one number.",
     "The single best shooting-efficiency stat. ~50%+ is strong at HS.", False),
    ("ScEff", "Scoring Efficiency", "Shooting", "(2·2PM + 3·3PM) / (2·2PA + 3·3PA)",
     "Field-goal points scored vs the MAX if every attempt had fallen at its shot "
     "value — a point-weighted make rate that rewards converting the harder, "
     "higher-value shots. Free throws excluded. NOT the same as SCE / "
     "Self-Creation %.",
     "Higher = you're capturing more of the points your shots could yield; "
     "100% would mean making everything.", True),
    ("AdjeFG%", "Adjusted eFG%",  "Shooting",
     "ridge fit of per-game eFG = league avg + offense effect + defense effect",
     "Opponent-adjusted shooting, KenPom-style: what a team would shoot against "
     "an AVERAGE defense (and, as Adj Opp eFG%, what an average offense would "
     "shoot against them). Corrects raw eFG% for the schedule faced — a team "
     "that shot 48% against elite defenses is better than one that shot 48% "
     "against sieves. Weighted by attempts and shrunk toward league average on "
     "thin samples. The efficiency numbers (ORtg/DRtg/PPP) get the same "
     "treatment in the tracked ratings.",
     "Compare to raw eFG%: adjusted above raw = tough schedule masked real "
     "shooting; below = the raw number was schedule-inflated.", False),
    ("3PAr", "Three-Point Rate",  "Shooting", "3PA / FGA",
     "Share of a player's shots that are threes.",
     "Shot-profile, not quality — how often they shoot from deep.", False),
    ("FTr",  "Free-Throw Rate",   "Shooting", "FTA / FGA",
     "How often a player gets to the line relative to shooting.",
     "Higher = draws contact / attacks the rim.", False),
    ("PPS",  "Points Per Shot",   "Shooting", "FG points / FGA",
     "Points produced per field-goal attempt (field goals only, no FTs).",
     "Higher is better; rewards efficient shot selection.", False),
    ("PPSA", "Pts Per Scoring Att","Shooting", "PTS / FGA",
     "All points (incl. FTs) divided by field-goal attempts.",
     "Higher is better; credits getting to the line.", False),
    ("Paint FG%", "Paint FG%",    "Shooting", "paint FGM / paint FGA",
     "Accuracy on shots from the painted area.",
     "Higher = strong finisher inside.", False),
    ("Paint PTS", "Paint Points", "Shooting", "2·paint FGM",
     "Points scored on shots in the paint.", "Inside scoring volume.", False),

    # ── Playmaking ──────────────────────────────────────────────────────────────
    ("AST/TO", "Assist-to-Turnover","Playmaking", "AST / TOV",
     "Assists for every turnover committed.",
     "Higher = takes care of the ball; >2.0 is excellent.", False),
    ("AST%",  "Assist %",         "Playmaking", "AST / team FGM while on floor",
     "Share of teammate field goals the player assisted while on the court.",
     "Higher = central creator.", False),
    ("TOV%",  "Turnover %",       "Playmaking", "TOV / (FGA + TOV)",
     "Share of a player's possessions that end in a turnover. Uses this app's "
     "locked possession rule (one shot OR one turnover).",
     "Lower is better.", False),
    ("USG%",  "Usage Rate",       "Playmaking", "player POSS / team POSS on floor",
     "Share of team possessions a player uses (shoots or turns over) while on "
     "the floor. Possessions = FGA + TOV.",
     "Higher = bigger offensive role / focal point.", False),
    ("SC",    "Shot Creation",    "Playmaking", "shots self-created + created for others",
     "Credit for generating shots — taking a self-created shot or passing/"
     "setting up a teammate's shot.", "Higher = engine of the offense.", False),
    ("PotAST", "Potential Assists", "Playmaking", "passes into a shot (make OR miss)",
     "Every pass that directly produced a shot attempt, whether it fell or not — "
     "the assists that COULD have been. AST only counts the makes, so a great "
     "passer whose teammates miss open looks reads unfairly low; PotAST measures "
     "the passing itself. The finished share (AST ÷ PotAST) shows how often "
     "teammates converted the looks they were given.",
     "High PotAST + low finished % = good passes, cold finishers — pair with "
     "the passer's look quality (xPPS created), not just AST.", True),
    ("ScrAST", "Screen Assists", "Playmaking", "credited screens on MADE field goals",
     "Screens that directly freed a made basket — the screener's version of an "
     "assist (a Second Spectrum staple, captured here through the shot's "
     "created-by credit). Shots from a screen-action set call (PnR / DHO / off "
     "screen) with no screener logged are counted separately as screen-created "
     "with the credit unassigned.",
     "The big who sets bone-rattling picks finally gets a number. Volume-"
     "dependent on tagging.", True),
    ("HAST",  "Hockey Assists",   "Playmaking", "the pass before the assist, made shots",
     "The secondary assist — the pass that fed the assister on a made basket "
     "(borrowed from hockey). It rewards the ball-mover who starts the advantage "
     "that someone else finishes with the assist. Not derivable from the shot "
     "alone (a pass isn't its own event), so it's an opt-in tap in the tracker; "
     "reads 0 until a coach starts capturing it.",
     "Surfaces the connector who swings the extra pass but rarely gets the "
     "assist. Volume-dependent on tagging.", True),
    ("SCE",   "Self-Creation %",  "Playmaking", "self-created shots / FGA",
     "Share of a player's own shots they created off the dribble (no pass into "
     "the shot).", "Higher = shot-maker who doesn't need setup.", False),

    # ── Rebounding rates ──────────────────────────────────────────────────────
    ("OREB%", "Off. Rebound %",   "Rebounding", "OREB / (OREB + opp DREB) on floor",
     "Share of available offensive rebounds the player grabbed while on court.",
     "Higher is better; inferred from lineup data.", False),
    ("DREB%", "Def. Rebound %",   "Rebounding", "DREB / (DREB + opp OREB) on floor",
     "Share of available defensive rebounds the player secured while on court.",
     "Higher is better.", False),
    ("TRB%",  "Total Rebound %",  "Rebounding", "REB / total available REB on floor",
     "Share of all available rebounds the player grabbed while on court.",
     "Higher is better.", False),

    # ── Defense ────────────────────────────────────────────────────────────────
    ("RimProt", "Rim Protection", "Defense",
     "league rim FG% − rim FG% allowed (contested 2s within 4 ft)",
     "How much a defender lowers opponents' finishing at the rim, in FG "
     "percentage points vs a league-average contest. Counts every tap-located "
     "shot inside 4 ft that the player contested OR blocked (the off-ball "
     "rim protector earns the block credit; a block is already a miss). "
     "Needs 8+ rim shots defended; feeds the DEFENSE rating.",
     "+5 = opponents finish 5 points worse than league average when this "
     "player meets them at the rim.", True),
    ("PerimD", "Perimeter Defense", "Defense",
     "league 3P% − 3P% allowed on contested threes",
     "The perimeter companion to Rim Protection: how much a defender lowers "
     "opponents' three-point shooting when contesting, in percentage points vs "
     "a league-average contest. Every contested 3-point attempt counts (no tap "
     "location needed). Needs 8+ threes defended; feeds the DEFENSE rating.",
     "+4 = shooters hit 4 points worse than league average against this "
     "player's closeouts.", True),
    ("STOCKS","Stocks",           "Defense", "STL + BLK",
     "Steals plus blocks — a single 'disruption' number.",
     "Higher = more defensive events.", False),
    ("CHG",  "Charges drawn",     "Defense", "fouls tagged Other / Other",
     "Charges this player took. A charge is logged by tagging the foul with "
     "Play type = Other AND Defense = Other — that pair is what marks it, and "
     "the player fouled is the defender who drew it. Drawing one is a defensive "
     "play, so it feeds the DEFENSE rating; the offensive player who committed "
     "it already takes the turnover and the personal foul, so no extra penalty "
     "is applied there. Players on teams that don't tag charges have no charge "
     "input at all rather than a zero, so a tagging gap never reads as bad "
     "defense.",
     "Higher = more charges taken.", False),
    ("DSHOT%","Defended FG%",      "Defense", "opp FG% when guarded by player",
     "Field-goal % opponents shoot when this player is the listed defender.",
     "Lower is better — tighter on-ball defense.", False),
    ("AdjDFG%","Adjusted Defended FG%", "Defense",
     "defended FG% rebased vs each shooter's expected make rate",
     "Answers 'was it the shooter or the defender?': every guarded shot is "
     "scored against that shooter's own season make rate for the shot value "
     "(shrunk toward league on thin samples), so holding an elite shooter to "
     "their norm no longer reads like bad defense. This is the contest leaf "
     "the DEFENSE rating uses.",
     "Lower is better — shooter quality removed.", True),
    ("DFGoe","Defended FG% over expected", "Defense",
     "(makes allowed − expected makes) / guarded shots",
     "The raw edge behind AdjDFG%: FG-percentage points allowed above what the "
     "guarded shooters normally make.",
     "Negative = holds shooters below their norm.", True),
    ("Guarded%","Contest Rate",    "Defense", "guarded opp shots / opp shots on floor",
     "Share of opponent shots that were contested while the player was on court.",
     "Higher = active contesting defense.", False),

    # ── Possession & pace ───────────────────────────────────────────────────────
    ("POSS",  "Possessions",      "Possession & Pace", "FGA + TOV",
     "This app's LOCKED possession rule: a possession is exactly one shot OR one "
     "turnover. Free throws and fouls never add a possession.",
     "The denominator for all per-possession and pace stats.", False),
    ("Pace",  "Pace",             "Possession & Pace", "possessions per game",
     "How many possessions a team plays per game.",
     "Higher = faster, run-and-gun; lower = grind-it-out.", False),
    ("PPP",   "Points Per Poss.", "Possession & Pace", "PTS / POSS",
     "Points scored per possession — the core efficiency unit.",
     "Higher on offense / lower allowed on defense is better.", False),
    ("Play Type", "Possession / Play Type", "Possession & Pace",
     "PPP per (tempo bucket) and per (shot-creation context), ranked vs league",
     "The Synergy-style view: points per possession grouped by HOW the shot was "
     "generated — tempo (transition ≤6s / early 7–14s / half-court 15s+, from the "
     "possession clock) and shot creation (self / off a pass / off a screen / "
     "both). Each gets a league percentile. Inferred from logged tempo + creation "
     "tags, NOT video-tagged play calls (no PnR/iso film here).",
     "Higher PPP + percentile = a more efficient way this team generates offense; "
     "on defense the rank is flipped so fewer points allowed ranks higher.", True),
    ("Defense", "Defensive Scheme", "Possession & Pace",
     "PPP per defensive scheme (man / zone / press / trap / junk), ranked vs league",
     "The defensive companion to Play Type: a one-tap, sticky tag for the scheme in "
     "effect (man, 2-3 / 1-3-1 zone, man / 2-2-1 / 1-3-1 press, traps, box-and-1, "
     "scramble…). Two reads off one tag — the schemes a team RUNS (PPP allowed) and "
     "how it ATTACKS each scheme it faces (PPP scored) — plus the play type × "
     "defense cross-tab ('their PnR vs a 2-3 zone'). A shot ends a possession, so "
     "PPP = points per shot; presses also report turnovers forced.",
     "On defense, fewer points allowed ranks higher; on offense, more points scored "
     "ranks higher. Empty until coaches tag the defense in the tracker.", True),
    ("ORtg",  "Offensive Rating", "Possession & Pace", "≈ 100 · PTS / POSS",
     "Points produced per 100 possessions. Possessions here = FGA + turnovers (no "
     "0.44·FTA free-throw-trip term), so these read a touch higher than box scores "
     "that use the full Dean Oliver formula — fine for in-app comparison. Individual "
     "ORtg uses on-court lineup fractions since the DB has no minutes.",
     "Higher is better. Directional on this small sample.", False),
    ("DRtg",  "Defensive Rating", "Possession & Pace", "≈ 100 · opp PTS / POSS",
     "Points allowed per 100 possessions.",
     "Lower is better.", False),
    ("NetRtg","Net Rating",       "Possession & Pace", "ORtg − DRtg",
     "Margin per 100 possessions — the bottom-line efficiency number.",
     "Positive and bigger is better.", False),

    # ── Advanced production ──────────────────────────────────────────────────────
    ("RTG",   "Game Rating (0-10)","Advanced",
     "6.0 + role-weighted (points-added vs expected), pool-calibrated, clamped 0–10",
     "The soccer-style per-game grade. Every action is scored as points added vs "
     "what was expected (a made contested shot is worth more than a made layup; a "
     "forced miss, steal, screen or board all count), reshaped by the player's "
     "fixed role so a glue guy isn't punished for low usage. 6.0 = an average game.",
     "7.5 good · 8.5 great · 9+ rare · <6 poor. Per-game only — season talent is "
     "OVERALL. 'Form' = the average of the last 5 game ratings.", True),
    ("GS",    "Game Score",       "Advanced",
     "PTS + 0.4·FGM − 0.7·FGA − 0.4·(FTA−FTM) + 0.7·OREB + 0.3·DREB + STL + "
     "0.7·AST + 0.7·BLK − 0.4·PF − TOV",
     "Hollinger's single-game value box-score summary.",
     "~10 is a solid game, 20+ is excellent.", False),
    ("PER",   "Player Efficiency","Advanced", "= Game Score (proxy)",
     "This app uses Game Score as the PER proxy — there is no league-wide pace/"
     "baseline in a single-program DB to compute true Hollinger PER.",
     "Read it like Game Score, not NBA PER (no 15.0 average).", False),
    ("EFF",   "Efficiency (NBA)", "Advanced",
     "(PTS+REB+AST+STL+BLK) − (missed FG + missed FT + TOV)",
     "The classic NBA 'efficiency' aggregate.",
     "Higher is better; rewards all-around box production.", False),
    ("FIC",   "Floor Impact Ctr.","Advanced",
     "PTS + OREB + 0.75·DREB + AST + STL + BLK − 0.75·FGA − 0.375·FTA − TOV − 0.5·PF",
     "RealGM's Floor Impact Counter — a fuller all-around impact number.",
     "Higher is better.", False),
    ("VPS",   "Value Point System","Advanced",
     "(PTS + REB + 2·(AST+STL+BLK)) / (FT miss + 2·(FG miss + PF + TOV))",
     "Hudl's production-to-mistakes ratio — positive box-score value over the cost "
     "of misses, fouls and turnovers (mistakes weighted ×2).",
     "Higher = more value per mistake; ~1.0 breaks even, 2+ is excellent.", False),
    ("PRF",   "Pts Responsible For","Advanced", "PTS + 2·AST2 + 3·AST3",
     "Points a player created — their own points plus the points their assists "
     "produced (split by 2-pt vs 3-pt assists).",
     "Higher = bigger share of offense generated.", False),
    ("per-32","Per-32 Minutes",   "Advanced", "stat · 32 / MIN",
     "A counting stat scaled to 32 minutes for fair comparison. HS games run "
     "≈32 min, so per-32 ≈ per-game here.",
     "Normalizes for playing time.", False),

    # ── Shot quality / Shot Lab ───────────────────────────────────────────────
    ("Shot Rating","Shot Rating", "Shot Quality", "100 · avg shot difficulty",
     "Difficulty (NOT efficiency) of the shots a player takes, 0–100. Anchors: "
     "50 = sample-average shot, 100 = contested self-created three. Difficulty = "
     "1 − sample make-rate for that shot's (zone, 2/3, creation, guarded) bucket.",
     "Higher = takes harder shots (degree of difficulty).", True),
    ("xFG%",  "Expected FG%",     "Shot Quality", "Σ bucket make-rate over shots taken",
     "The FG% an average shooter would post on this player's exact shot diet "
     "(by zone, 2/3, creation, contest).",
     "A 'shot quality' baseline to compare actual FG% against.", False),
    ("SMOE",  "Shot-Making Over Exp.","Shot Quality", "FG% − xFG%",
     "How much better (or worse) a player shoots than their shot difficulty "
     "predicts. The pure shot-making signal.",
     "Positive = makes tougher shots than expected.", True),
    ("xPPS",  "Expected Pts/Shot","Shot Quality", "expected points per shot from buckets",
     "Points-per-shot an average shooter would get on this player's shot diet.",
     "Compare to actual PPS to isolate finishing.", False),

    # ── 0–100 player ratings (pool-relative z-scores) ──────────────────────────
    ("OVERALL","Overall Rating",  "Ratings", "four categories + Game Score + EFF/g + FIC/g",
     "Master 0–100 player rating. Pool-relative z-score: 50 = league average, "
     "+10 per standard deviation, clamped 0–100.",
     "70+ elite, 62+ great, 54+ above average, ~50 average. Team Power uses the "
     "same ladder (Rankings tiers).", False),
    ("OFFENSE","Offense Rating",  "Ratings", "shooting + finishing + scoring volume (PPG + PRF/g)",
     "0–100 offensive rating from shooting, finishing AND scoring volume (z-scaled, "
     "50 = average) — volume is folded in so a low-usage efficient shooter doesn't "
     "rate the same as a high-volume scorer.", "Higher is better.", False),
    ("DEFENSE","Defense Rating",  "Ratings", "stocks · STL · BLK · contest %",
     "0–100 defensive rating from disruption and contesting inputs.",
     "Higher is better; thinner signal than offense in this data.", False),
    ("PLAYMAKING","Playmaking Rating","Ratings", "AST · SC · AST/TOV · TOV(inv)",
     "0–100 rating of shot creation and ball security.", "Higher is better.", False),
    ("REBOUNDING","Rebounding Rating","Ratings", "OREB/DREB/REB per-g + REB%",
     "0–100 rating of rebounding volume and rate.", "Higher is better.", False),
    ("PHYSICAL", "Physical Rating", "Ratings", "pool z of height + wingspan → 0-100",
     "The measurables, rated like any other category: height and wingspan "
     "(inches, from the roster) z-scored across the league pool, 50 = average. "
     "Weight is excluded (no 'more is better'). Feeds OVERALL at a deliberately "
     "small weight (0.25 — a nudge, not a pillar); players with no measurements "
     "recorded simply have no PHYSICAL rating and lose nothing.",
     "Length matters at the rim and on closeouts — but tape decides. Mostly a "
     "roster-context read.", True),
    ("2WAY",  "Two-Way Rating",   "Ratings", "mean(OFFENSE, DEFENSE)",
     "Balance of offensive and defensive value in one number.",
     "Higher = impacts both ends.", True),
    ("VERSATILITY","Versatility", "Ratings",
     "100 · Shannon entropy of normalized PTS/REB/AST/STL/BLK shares ÷ ln5",
     "How evenly a player fills the box score across the five core categories.",
     "100 = does everything; 0 = one-dimensional.", True),

    # ── Team & league ────────────────────────────────────────────────────────────
    ("Power", "Power Rating",     "Team & League", "z-scored blend → 0–100",
     "Opponent-adjusted overall team strength on a 0–100 scale (50 = league "
     "average). Built from results, margin and a class bridge.",
     "Higher is better; drives the rankings.", False),
    ("Four Factors","Dean Oliver's Four Factors","Team & League",
     "eFG% (40%) · TOV% (25%) · ORB% (20%) · FTr (15%)",
     "The four things that win games, weighted by importance. Defense = the "
     "opponent's four factors against you.",
     "Win the factors, win the game.", False),
    ("TO kind", "Turnover Kind", "Team & League",
     "one-tap tag on a turnover: bad pass / drive / held ball / shot clock / travel",
     "What KIND of giveaway it was — orthogonal to the Play type tag (which set "
     "the offense was running when it lost the ball). Optional; hidden in the "
     "phone tracker's quick mode.",
     "Bad-pass-heavy = pressure it; drive-heavy = build a wall.", True),
    ("4F-PPP", "Four-Factor Expected PPP", "Team & League",
     "(1−TOV%) · (2·eFG% + FTr) / (1 − (1−eFG%)·ORB%)",
     "Points per possession the four factors alone predict: turnovers score "
     "nothing, every shot carries the team's eFG% and FT rate, and offensive "
     "rebounds re-enter the shot chain (a geometric series of extra tries).",
     "Actual PPP above 4F-PPP = shot-making the factors can't see; below = "
     "leaving points on the floor.", True),
    ("Pythag","Pythagorean Wins", "Team & League", "PF^14 / (PF^14 + PA^14)",
     "Expected win % from points scored vs allowed (exponent 14).",
     "Compare to actual record to find lucky/unlucky teams.", False),
    ("Luck",  "Luck",             "Team & League", "actual wins − Pythagorean wins",
     "Wins above or below what scoring margins predict.",
     "Positive = winning more than the margins say (close-game luck).", True),
    ("SOS",   "Strength of Sched.","Team & League", "avg opponent power rating",
     "Average power rating of the opponents a team has faced.",
     "Higher = tougher schedule.", False),
    ("ClutchFT%", "Clutch Free-Throw %", "Shooting",
     "FT% when the moment's leverage ≥ 1.5× the game's average",
     "Free-throw accuracy in the moments that decide games — the same leverage "
     "bar Clutch WPA uses (how far a basket would swing win probability, vs the "
     "game's average moment), so 'clutch' means one thing app-wide. Late-and-"
     "close line trips qualify; garbage-time ones don't.",
     "Compare to season FT%: a big drop = the line gets heavy when it matters; "
     "small samples swing hard.", True),
    ("And-1", "And-One (3-Point Play)", "Shooting",
     "made FG followed by a LONE free throw by the same shooter",
     "Finishing through contact: a made basket plus the bonus free throw, "
     "linked automatically from the event stream (a single-FT trip right after "
     "a make; two-shot trips are fouled-on-the-miss, not and-1s). Counted as "
     "trips earned and conversions (the FT made).",
     "Earned and-1s = strength finishing; the conversion rate is the free "
     "point.", True),
    ("Rest", "Rest & Fatigue Splits", "Team & League",
     "record + MOV by days since the previous game; league margin by rest differential",
     "The schedule's dates as a signal: a team's record and margin-vs-usual on "
     "back-to-backs / 2 days / 3-4 days / 5+ days of rest, plus heavy weeks "
     "(3+ games in any 7 days). The MOV delta compares each bucket to the "
     "team's own season margin, so a bad team isn't called 'tired' for losing "
     "as usual. The league-wide fatigue edge is margin as a function of the "
     "REST DIFFERENTIAL (my rest − theirs) — the honest test of whether fresh "
     "legs matter in this league.",
     "A big negative MOV delta on short rest = schedule fatigue is real for "
     "this team; check the league edge before crediting excuses.", True),
    ("Volatility","Volatility",   "Team & League", "std-dev of game margin",
     "Game-to-game swing in scoring margin.",
     "Lower = steadier, more predictable team.", True),
    ("Dominance","Dominance",     "Team & League", "mean of scaled MOV, win%, blowout%",
     "How decisively a team wins, 0–100 (margin + win rate + blowout rate).",
     "Higher = wins big and often.", True),
    ("Consistency","Consistency", "Team & League", "scale100(−margin volatility)",
     "Game-to-game reliability, 0–100.", "Higher = fewer surprises.", True),
    ("Clutch","Clutch",           "Team & League", "scaled close-game win% & margin",
     "Performance in close games (≤5), 0–100. None when <2 close games.",
     "Higher = wins the tight ones.", True),
    ("Momentum","Momentum",       "Team & League", "scale100(last-5 MOV − season MOV)",
     "Whether a team is trending up or down vs its own baseline, 0–100.",
     "Higher = getting hotter.", True),
    ("Balance","Scoring Balance", "Team & League", "(eff. scorers−1)/(n−1)·100",
     "How evenly scoring is spread; effective scorers = 1/Σ(scoring shareᵢ²).",
     "Higher = balanced attack; low = one-man show.", True),

    # ── Officiating ──────────────────────────────────────────────────────────────
    ("FPG",   "Fouls Per Game",   "Officiating", "fouls called / games worked",
     "How many fouls an official calls per game.",
     "Higher = tighter whistle; context matters.", False),
    ("Call %","Call Share",       "Officiating", "ref's fouls / all fouls in their games",
     "Share of the whistle an official accounts for in their games.", "", False),
    ("H/A",   "Home/Away Lean",   "Officiating", "home fouls − away fouls",
     "Fouls called on the home team minus the away team (team 1 = home).",
     "Near 0 = even; large = a lean (small samples swing hard).", False),
    ("±FPG",  "FPG Consistency",  "Officiating", "std-dev of fouls/game",
     "Game-to-game swing in an official's foul count.",
     "Lower = a more predictable whistle.", False),
    ("WinProb", "Win Probability", "Advanced", "Φ(margin / (σ·√time_left))",
     "Live chance a team wins given the current margin and time left; the final "
     "margin is modeled as Normal around the current margin with variance that "
     "shrinks as the clock runs down (even-teams assumption).",
     "50% = coin flip; pushes toward 100/0 as a lead holds and time expires.", False),
    ("GEI", "Game Excitement Index", "Advanced", "Σ|ΔWin Probability|, length-adjusted",
     "Total win-probability movement across a game — how much the outcome was in "
     "doubt and how often it swung.",
     "Higher = more dramatic; a blowout ≈ 0, a back-and-forth thriller scores high.", True),
    ("Adj GEI", "Stakes-adjusted GEI", "Advanced", "GEI × (1 + stakes)",
     "GEI lifted by the stakes: the two teams' mean quality percentile plus an "
     "upset kicker when the worse-seeded team won — so a marquee thriller outranks "
     "an equally-frantic bottom-of-the-league game.",
     "A #1-vs-#2 nailbiter beats a low-vs-low one at a higher raw GEI; a live upset "
     "lands in between.", True),
    ("OffRating", "Officials Rating", "Advanced",
     "50 + 10·Σ(weightᵢ·zᵢ) over the ref pool",
     "The ref a coach wants, on a 0-100 index (50 = average): weighted, in order, "
     "by fewer fouls/game, higher-leverage games worked, higher scoring, higher "
     "pace, and clutch calls (Q4/OT within a possession or two).",
     "Higher = works the big games, lets them play, and still makes the gutsy late "
     "call. Needs 3+ games worked to rate.", True),
    ("Leverage", "Game leverage (officials)", "Advanced",
     "0.6·team-quality + 0.4·closeness",
     "How much a game is worth to work — the mean quality percentile of the two "
     "teams blended with how close the final was.",
     "~1 = a marquee, tight game; ~0 = a low-vs-low blowout.", True),
    ("sTS%", "Stabilized rate", "Advanced", "(value·n + k·league_mean) / (n + k)",
     "Any rate (FG%, 3P%, TS%, rating) regressed toward the league average by how "
     "little evidence backs it (empirical-Bayes); the prior strength k is fit from "
     "the data. Tames small-sample noise on a short book.",
     "Trust the stabilized value on low volume; it converges to the raw rate as "
     "attempts grow.", True),
    ("Archetype", "Play-Style Cluster", "Ratings", "k-means on z-scored stats",
     "A data-driven player group learned by clustering on standardized stats "
     "(including the OFFENSE/DEFENSE composites) and named from the cluster's "
     "signature — using the SAME vocabulary as the badge archetypes (Sharpshooter, "
     "Scorer, Floor General, Rebounder, Interior Anchor, Defensive Specialist, "
     "Glue Guy, Role Player), plus the two-way profiles (Two-Way Star, Offensive "
     "Engine, Defensive Anchor, Flamethrower) when a cluster splits on "
     "offense-vs-defense quality. Shown as the 'Cluster' chip on a player's "
     "header and on the Lab → Archetypes tab, where the two lenses can be read "
     "side by side: badges say what a player has EARNED, the cluster says how "
     "they PLAY.",
     "Same names, two lenses — when both agree the role is solid; a disagreement "
     "is the interesting scouting note. Distinct from the rule-based Scouting "
     "Role below.", True),
    ("Role", "Scouting Role", "Ratings", "rule-based thresholds on ratings + percentiles",
     "The plain-language role on a player's profile hero card (Two-Way Force, "
     "Scoring Machine, Floor General, Glass Cleaner, Defensive Anchor, 3-and-D "
     "Wing, Spot-Up Shooter, Interior Presence, Versatile Contributor, High-Impact "
     "Role Player, Developing Player). Assigned by the first matching rule on the "
     "player's OVERALL / OFFENSE / DEFENSE / PLAYMAKING / REBOUNDING ratings and "
     "stat percentiles — a scouting label, not a learned cluster.",
     "Reads how a coach would summarize the player; complements the statistical "
     "cluster rather than duplicating it.", True),
    ("MtchDiff", "Matchup Difficulty", "Defense", "attempt-weighted opponent OFFENSE faced",
     "How strong the scorers a defender was assigned to were, weighted by shots "
     "faced (reconstructed from who-guarded-whom on every contested shot).",
     "50 = average assignment; high = routinely guarded the other team's best.", True),
    ("Badge", "Skill Badge", "Ratings", "percentile tiers with volume gates",
     "A 2K-style strength tag (Deadeye, Pickpocket, Closer, …) earned by ranking "
     "in the league's top tiers on a stat, gated by minimum volume. "
     "Bronze/Silver/Gold = 60th/75th/90th percentile.",
     "A quick read of what a player is elite at; gates stop lucky small samples.", True),
    ("ProjM", "Projected Margin", "Team & League", "RatingA − RatingB (+ home court)",
     "Predicted point margin between two teams from the opponent-adjusted ratings, "
     "plus a class bridge and home-court edge; drives the matchup win probability.",
     "Positive favors team A; magnitude ≈ expected winning margin in points.", False),
    ("HoopWAR", "Wins Above Replacement", "Advanced",
     "(RAPM − replacement) × floor-time possessions × pts-to-wins",
     "One number for a player's total season value, in WINS — baseball's WAR "
     "brought to the court. Box-prior RAPM (points added per 100 possessions vs "
     "an average player) is paid out over the possessions actually played, "
     "measured against a REPLACEMENT-level player (−3 pts/100 — the bench kid "
     "who'd absorb the minutes), then converted to wins with the Pythagorean "
     "rate (≈14 points ≈ 1 win at HS scoring). Display-only: it is NOT part of "
     "the OVERALL rating.",
     "+1.0 = this player's floor time added about one win over a replacement. "
     "0 is replacement level, not average — an average starter earns positive "
     "WAR. Directional on a short book.", True),
    ("RAPM", "Regularized Adjusted +/-", "Advanced",
     "ridge regression over every possession",
     "Points a player adds per 100 possessions vs a league-average player, "
     "holding BOTH teammates and opponents constant — solved in one ridge "
     "regression across all possessions (the gold-standard impact metric). "
     "Field-goal possessions only; lambda shrinks thin samples to ~0.",
     "0 = average; a few points + is a real difference-maker. Directional on a "
     "small book.", True),
    ("ORAPM", "Offensive RAPM", "Advanced", "100 x offensive ridge coefficient",
     "The offensive half of RAPM — points added per 100 when the player's team "
     "has the ball.", "Higher = lifts the offense.", True),
    ("DRAPM", "Defensive RAPM", "Advanced", "-100 x defensive ridge coefficient",
     "The defensive half of RAPM — points prevented per 100 (sign flipped so "
     "positive = good).", "Higher = suppresses opponent scoring.", True),
    ("WPA", "Win Probability Added", "Advanced", "sum of win-prob change per basket",
     "How much each made basket changed the team's chance of winning, summed per "
     "player (assisted FGs split 70/30 with the passer). Credits the shots that "
     "actually mattered, not just the ones that counted.",
     "Higher = swung games toward your team.", True),
    ("Clutch WPA", "Clutch WPA", "Advanced", "WPA in high-leverage moments",
     "The share of a player's win-probability added that came in swingy, "
     "high-leverage situations (Leverage Index >= 1.5). A real 'hits the big "
     "shots' number.", "Higher = shows up when it matters most.", True),
    ("Leverage", "Leverage Index", "Advanced",
     "how much a basket would swing win prob, vs average",
     "How decisive the moment is — how far a single basket would move the win "
     "probability, normalized so the game's average moment = 1.0.",
     "High = crunch time; low = garbage time.", True),
    ("Unit Net", "Lineup Net Rating", "Possession & Pace",
     "ORtg - DRtg for a 5-man unit",
     "Points per 100 a specific five-player unit produced minus allowed while "
     "that exact five was on the floor (observed, not simulated).",
     "Positive = that combination outscores opponents.", False),
    ("Title Odds", "Championship Odds", "Team & League",
     "Monte Carlo single-elim simulations",
     "How often a team wins a simulated single-elimination bracket, rolling "
     "every game thousands of times from the power ratings.",
     "Higher = more likely to cut down the nets.", False),
    ("Exp. Wins", "Expected Wins", "Team & League",
     "mean wins over simulated seasons",
     "Average wins a team would post if its schedule were replayed thousands of "
     "times from current ratings. Compare to actual wins to see over/under-"
     "performance.", "Actual above expected = good fortune / clutch.", True),
    ("Poss WPA", "Possession WPA", "Advanced",
     "WP(margin+actual) - WP(margin+EP) per possession",
     "The possession-aware win-probability model: every shot AND turnover is "
     "scored against the average possession (expected points EP). Offense value "
     "goes to the shooter/passer (or the turnover committer); DEFENSE value to "
     "the stealer, defensive rebounder or blocker who ended it. Unlike scoring "
     "WPA it credits stops, steals and blocks, split into Off WPA + Def WPA.",
     "Positive = created value above an average possession on that end.", True),
    ("EP", "Expected Points / Possession", "Possession & Pace",
     "league points / league possessions",
     "Average points a possession is worth across the sample. The baseline the "
     "possession-WPA model scores each possession against.",
     "Beat it on offense / hold below it on defense to add win probability.", False),
    ("Pair Net", "Chemistry (Pair Net)", "Possession & Pace",
     "100 x (pts_for/off_poss - pts_against/def_poss), both on floor",
     "Teammate chemistry: the team's net points per 100 possessions while a "
     "specific PAIR of players are both on the floor. The pairwise companion to "
     "observed 5-man lineup ratings, drawn as a network of duos.",
     "Positive = the duo outscores opponents together; compare to each player's "
     "solo on-court net to spot pairings that lift or drag.", True),

    # ── platform concept (load-bearing everywhere) ───────────────────────────────
    ("Tracked", "Tracked vs box score", "Box Score", "",
     "Tracked = possession-level play-by-play (who shot, from where, who assisted "
     "or defended), captured by the phone tracker or the Game Tracker. Box score = "
     "final counting totals (PTS, REB, AST…) entered by hand. Tracked depth is a "
     "Paid feature; box scores are always free.",
     "Tracked unlocks shot charts, lineups, play types and on-ball defense; "
     "box-only coaches still get the full box + standings. Cross-season player "
     "development reads tracked games.", False),
]

CATEGORIES = ["Box Score", "Shooting", "Playmaking", "Rebounding", "Defense",
              "Possession & Pace", "Advanced", "Shot Quality", "Ratings",
              "Team & League", "Officiating"]


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _card_html(abbr, name, cat, formula, definition, good, invented):
    tag = ("<span class='gloss-cat' style='border-color:rgba(var(--accent-rgb),0.4)'>"
           "✦ SIGNATURE</span>" if invented
           else f"<span class='gloss-cat'>{_esc(cat)}</span>")
    formula_html = (f"<div class='gloss-formula'>{_esc(formula)}</div>"
                    if formula else "")
    good_html = (f"<div class='gloss-good'>{_esc(good)}</div>" if good else "")
    return (
        f"<div class='gloss-card'>{tag}"
        f"<span class='gloss-abbr'>{_esc(abbr)}</span> "
        f"<span class='gloss-full'>· {_esc(name)}</span>"
        f"<div class='gloss-def'>{_esc(definition)}</div>"
        f"{formula_html}{good_html}</div>"
    )


def render_glossary(key_prefix: str = "gloss", categories=None,
                    intro: str | None = None, columns: int = 2):
    """Interactive, searchable stat glossary embedded in a page.

    Parameters
    ----------
    key_prefix : unique prefix for widget keys (one page may host several).
    categories : optional list to restrict to a page's relevant categories.
                 None = all categories.
    intro      : optional caption shown above the controls.
    columns    : number of card columns (2 reads well on wide layout).
    """
    pool = STAT_DEFS
    if categories:
        catset = set(categories)
        pool = [d for d in STAT_DEFS if d[2] in catset]

    avail_cats = [c for c in CATEGORIES if any(d[2] == c for d in pool)]
    if any(d[6] for d in pool):
        avail_cats = avail_cats + ["✦ Signature (invented)"]

    if intro:
        st.caption(intro)

    c1, c2 = st.columns([2, 3])
    q = c1.text_input("Search stats", key=f"{key_prefix}_q",
                      placeholder="e.g. TS%, usage, rebound, clutch…").strip().lower()
    picked = c2.multiselect("Filter by category", avail_cats, default=[],
                            key=f"{key_prefix}_cats",
                            help="Leave empty to show every category.")

    def _match(d):
        abbr, name, cat, formula, definition, good, invented = d
        if picked:
            ok_cat = cat in picked or ("✦ Signature (invented)" in picked and invented)
            if not ok_cat:
                return False
        if q:
            hay = " ".join((abbr, name, cat, definition, good)).lower()
            if q not in hay:
                return False
        return True

    rows = [d for d in pool if _match(d)]
    st.caption(f"{len(rows)} of {len(pool)} stats"
               + (" · ✦ = invented / signature metric unique to this app"
                  if any(d[6] for d in pool) else ""))

    if not rows:
        st.info("No stats match that search. Try a different term or clear the filter.")
        return

    cols = st.columns(columns)
    for i, d in enumerate(rows):
        cols[i % columns].markdown(_card_html(*d), unsafe_allow_html=True)


@st.fragment
def glossary_tab(key_prefix: str):
    """The app's one standard glossary surface — identical on every page.

    Every analytics page's "Glossary" tab is just a call to this, so the
    glossary reads the same everywhere: the FULL searchable catalogue (no
    per-page category subset), one shared intro. The only per-page difference
    is `key_prefix`, which keeps the search/filter widget keys unique.

    ``@st.fragment``: the search box / category filter live INSIDE this
    function, so each keystroke reruns only the glossary — not the (often
    multi-thousand-line) host page. Everything rendered here stays within the
    fragment's own containers, per fragment rules.
    """
    st.subheader("Stat glossary")
    render_glossary(
        key_prefix, categories=None,
        intro="Every stat the app computes — search by name or filter by category. "
              "✦ = an invented / signature metric unique to this app.")
