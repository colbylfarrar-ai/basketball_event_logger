"""insights_severity.py — one calibrated ranking across three engine families.

WHY THIS EXISTS
---------------
Insights mines findings from three places that never agreed on a scale:

  * the PLAYER miner (`helpers/insights.py`) sorts by ``|z|``;
  * the TEAM miner (`helpers/team_insights.py`) sorts by the same field, except
    several generators do not produce a ``|z|`` at all — `_t_chemistry`
    hardcodes ``score: 1.4``, `_t_deserved` adds ``+0.5`` to jump the queue,
    `_t_keys` synthesises ``z = (hi_pct - lo_pct) / 0.15``;
  * the 13 PORTED engines (`helpers/dashboard/insights_deep.py`) are not scored
    at all — their order is a hand-authored tuple.

So "strongest first" was three different sentences and nothing could honestly
float to the top of the page. This module is the fourth, *additional* ordering:
it reads the three families, it does not rewrite them. Their own sections keep
their own internal order, and every regression test on the miners stays green.

THE LAW: RANK, NEVER HIDE
-------------------------
Severity ordering is a SORT. It is never a filter. If an engine fired a
finding, that finding renders — regardless of confidence, rank, sample, or
whether it has a points conversion. `rank()` returns EVERY finding it was
given, in order; a caller that slices the result is showing a spotlight, not
replacing the list. `tracker/test_insights_severity.py` asserts the count.

TWO BANDS, NEVER INTERLEAVED
----------------------------
    band 1 (has pts/g):  severity = |materiality| x reliability x confidence
    band 2 (no pts/g):   severity =                 reliability x confidence

Every tagged finding sorts above every untagged one. Two bands rather than one
blended score because a neutral stand-in for missing materiality would let an
untagged finding outrank a genuinely small tagged one — which reads as the app
inventing a number it does not have.

Within a band the score can tie (see `UNMEASURED_R`), so the sort finishes on
``|z|`` and then the finding key. That is a TIEBREAK for total, stable order —
it is not part of the score and never moves a finding across bands.

THE POINTS TABLE STARTS SMALL ON PURPOSE
----------------------------------------
`materiality` is points per game at stake. Its presence decides the band; its
magnitude decides the order inside band 1. **Never fabricate a conversion.** A
metric without a defensible derivation gets no tag and sorts into band 2. No
tag beats a wrong tag.

Derivations that ship today, each reading data the Insights page has already
paid for (prod is 1 vCPU — a derivation that costs a fresh event walk is not
worth the tag):

    Margin mix / Deserved   the four deserved terms are ALREADY points per
                            game, and they sum to the final margin exactly.
    GuardCliff              (open FG% - contested FG%) x contested attempts
                            per game x 2 — the points a shooter leaves on the
                            floor when the defense takes her space away.
    Impact                  WPA x the league's points-per-win, from
                            `hoopwar.wins_per_point` off the pool's own PPG.
    Ball security           (team TOV% - league TOV%) x possessions per game
                            x league PPP — the empty trips, priced.
    Takeaways               (team forced-TOV rate - league) x opponent
                            possessions per game x league PPP.
    Rebounding (team ORB%)  (team ORB% - league) x opponent DREB chances per
                            game x league PPP — the extra shots, priced.

Deliberately NOT tagged yet, and named so the gap is visible rather than
forgotten: possession-ledger sources, foul-state net, box-out payoff at the
PLAYER level, and kill-strings. Each has a defensible derivation in the design
but needs an engine output this page does not currently hold, and guessing one
would break the rule above. The table grows as derivations are proven.

Streamlit-free and side-effect-free, so it is unit-testable without a render.
"""
from __future__ import annotations

import math

import helpers.reliability as REL

#: Bands. Lower sorts first, and the two never interleave.
BAND_TAGGED = 1
BAND_UNTAGGED = 2

#: Reliability used for a metric the book has never measured. Set to the book's
#: own floor rather than to a neutral 1.0: an unmeasured read is SHOWN (the law
#: above) and ranked at the bottom of its band, never hidden and never
#: flattered. It is also a standing nudge — measuring a metric is the only way
#: to move it up the page.
UNMEASURED_R = REL.WEAK_SB

#: Game count at which `confidence` reaches 1.0. Mirrors `insights.FULL_BOOK`
#: on purpose so this ranking agrees with the gates the miners already apply.
FULL_BOOK = 20


def confidence(gp):
    """0.35-1.0 sample weight from a book's game count.

    Deliberately the same ladder as `insights.tier_factor` — if the miners
    consider a 7-game book worth 0.35 of a full one, this ranking has no
    business disagreeing.
    """
    return max(0.35, min(1.0, (gp or 0) / FULL_BOOK))


# ── the section each metric answers ──────────────────────────────────────────
# Insights is cut by the QUESTION a coach asks, not by the data category the
# number came from. This is the authored map from a generator's `metric` name
# to the section that holds its evidence.
S_IDENTITY = "identity"       # Who we are
S_WHY = "why"                 # Why we win / why we lose
S_HELPING = "helping"         # Who's helping
S_TOGETHER = "together"       # Who to play together
S_SCOUT = "scout"             # What they'll take away
S_RECEIPTS = "receipts"       # the appendix

SECTIONS = (S_IDENTITY, S_WHY, S_HELPING, S_TOGETHER, S_SCOUT, S_RECEIPTS)

SECTION_LABELS = {
    S_IDENTITY: "Who we are",
    S_WHY: "Why we win / why we lose",
    S_HELPING: "Who's helping",
    S_TOGETHER: "Who to play together",
    S_SCOUT: "What they'll take away",
    S_RECEIPTS: "Receipts",
}

#: metric -> section. Anything absent lands in Receipts, which is the honest
#: default: the appendix is where a read with no authored home belongs.
METRIC_SECTION = {
    # ── who we are ───────────────────────────────────────────────────────────
    "PlayStyle": S_IDENTITY, "Spacing": S_IDENTITY, "3PT diet": S_IDENTITY,
    "Scheme": S_IDENTITY, "Off engine": S_IDENTITY, "Def engine": S_IDENTITY,
    "Contest rate": S_IDENTITY, "Shots allowed": S_IDENTITY,
    "Vs scheme": S_IDENTITY,
    # ── why we win / why we lose ─────────────────────────────────────────────
    "Margin mix": S_WHY, "Deserved": S_WHY, "Quarters": S_WHY, "Runs": S_WHY,
    "Game script": S_WHY, "Close games": S_WHY, "Luck": S_WHY,
    "Volatility": S_WHY, "Momentum": S_WHY, "Rest": S_WHY,
    "Transition": S_WHY, "Transition D": S_WHY, "Keys": S_WHY,
    "Ball security": S_WHY, "Takeaways": S_WHY, "Garbage time": S_WHY,
    # ── who's helping ────────────────────────────────────────────────────────
    "POE": S_HELPING, "Selection": S_HELPING, "Usage": S_HELPING,
    "Playmaking": S_HELPING, "Rebounding": S_HELPING, "Impact": S_HELPING,
    "Consistency": S_HELPING, "Form": S_HELPING, "Foul rate": S_HELPING,
    "Fouls drawn": S_HELPING, "Clutch FT": S_HELPING, "Defense": S_HELPING,
    "Rim D": S_HELPING, "Perim D": S_HELPING, "Disruption": S_HELPING,
    "Stint length": S_HELPING, "Def load": S_HELPING, "Def area": S_HELPING,
    "Def role": S_HELPING, "Def scheme": S_HELPING,
    "Def footprint": S_HELPING, "On/off offense": S_HELPING,
    "On/off defense": S_HELPING, "Shot creation": S_HELPING,
    "Rim finish": S_HELPING, "3P%": S_HELPING, "Q4": S_HELPING,
    "TO type": S_HELPING, "PlayType": S_HELPING, "PnR role": S_HELPING,
    # ── who to play together ─────────────────────────────────────────────────
    "Lineups": S_TOGETHER, "Chemistry": S_TOGETHER, "Matchup": S_TOGETHER,
    # ── what they'll take away (the scout's report ON you) ───────────────────
    "Scoutability": S_SCOUT, "GuardCliff": S_SCOUT, "HandGap": S_SCOUT,
    "Situational": S_SCOUT, "Assignment": S_SCOUT,
}

#: The Team Dashboard destination holding each metric's chart, as
#: `(view, path)` where `path` is None, one hop, or a tuple naming the nested
#: switcher too. `insights_tab` parks it and the page's `_sub_seg` switchers
#: consume one step each on the way down.
#:
#: This supersedes the view-only map that shipped before: a jump that landed on
#: Charts' first sub-tab when the evidence was on Trends was a jump a coach
#: stopped trusting after the second try. The ~30 player-side keys below never
#: rendered a button at all — `_evidence_jumps` had exactly one call site.
METRIC_EVIDENCE = {
    # ── player metrics ───────────────────────────────────────────────────────
    "POE": ("Charts", ("Offense", "Scoring")),
    "Selection": ("Charts", ("Offense", "Shooting")),
    "3P%": ("Charts", ("Offense", "Shooting")),
    "Rim finish": ("Charts", ("Offense", "Shooting")),
    "GuardCliff": ("Charts", ("Offense", "Shooting")),
    "HandGap": ("Charts", ("Offense", "Shooting")),
    "Shot creation": ("Charts", ("Offense", "Playmaking")),
    "Playmaking": ("Charts", ("Offense", "Playmaking")),
    "TO type": ("Charts", ("Offense", "Playmaking")),
    "Usage": ("Charts", ("Offense", "Scoring")),
    "Spacing": ("Charts", "Play Style"),
    "Q4": ("Charts", "Quarters"), "Situational": ("Charts", "Situational"),
    "Garbage time": ("Charts", "Situational"),
    "Form": ("Charts", "Trends"), "Consistency": ("Charts", "Trends"),
    "PlayType": ("Charts", "Play Style"), "PlayStyle": ("Charts", "Play Style"),
    "PnR role": ("Charts", "Play Style"),
    "Impact": ("Lab", "Impact Lab"), "On/off offense": ("Lab", "Impact Lab"),
    "On/off defense": ("Lab", "Impact Lab"), "Matchup": ("Lab", "Impact Lab"),
    "Def footprint": ("Lab", "Impact Lab"),
    "Stint length": ("Lab", "Impact Lab"),
    "Defense": ("Charts", ("Defense", "Team Defense")),
    "Rim D": ("Charts", ("Defense", "Team Defense")),
    "Perim D": ("Charts", ("Defense", "Team Defense")),
    "Disruption": ("Charts", ("Defense", "Team Defense")),
    "Def load": ("Charts", ("Defense", "Team Defense")),
    "Def area": ("Charts", ("Defense", "Team Defense")),
    "Def role": ("Charts", ("Defense", "Scheme")),
    "Def scheme": ("Charts", ("Defense", "Scheme")),
    "Assignment": ("Charts", ("Defense", "Scheme")),
    "Rebounding": ("Charts", ("Defense", "Glass")),
    "Fouls drawn": ("Roster", None), "Clutch FT": ("Roster", None),
    "Foul rate": ("Roster", None),
    # ── team metrics ─────────────────────────────────────────────────────────
    "Quarters": ("Charts", "Quarters"), "Transition": ("Charts", "Play Style"),
    "Transition D": ("Charts", ("Defense", "Team Defense")),
    "Runs": ("Charts", "Trends"),
    "Momentum": ("Charts", "Trends"), "Game script": ("Charts", "Trends"),
    "Front-runner": ("Charts", "Trends"),
    "Scheme": ("Charts", ("Defense", "Scheme")),
    "Vs scheme": ("Charts", ("Defense", "Scheme")),
    "Shots allowed": ("Charts", ("Defense", "Team Defense")),
    "Contest rate": ("Charts", ("Defense", "Team Defense")),
    "Forced TOs": ("Charts", ("Defense", "Team Defense")),
    "Takeaways": ("Charts", ("Defense", "Team Defense")),
    "Stops": ("Charts", ("Defense", "Stops")),
    "3PT diet": ("Charts", ("Offense", "Shooting")),
    "Lineups": ("Lab", "Impact Lab"), "Chemistry": ("Lab", "Impact Lab"),
    "Off engine": ("Charts", "Winning Formula"),
    "Def engine": ("Charts", "Winning Formula"),
    "Keys": ("Charts", "Winning Formula"),
    "Luck": ("Schedule", None), "Close games": ("Schedule", None),
    "Volatility": ("Schedule", None), "Rest": ("Schedule", None),
    "Deserved": ("Schedule", None), "Margin mix": ("Schedule", None),
    "Scoutability": ("Scout", None), "Ball security": ("Scout", None),
    "After push": ("Charts", "Situational"),
    "After cold": ("Charts", "Situational"),
    "After scramble": ("Charts", "Situational"),
}

#: Metrics a practice plan can actually move. AUTHORED, never inferred from a
#: finding's text, so Monday is auditable — and it defaults to False, so a
#: metric added tomorrow cannot silently appear on a coach's practice list.
#: This is a DISPLAY GROUPING inside Monday only. It removes nothing from any
#: other section and it is not a filter on the ranking.
REHEARSABLE = frozenset({
    "Ball security", "TO type", "GuardCliff", "HandGap", "Rebounding",
    "Clutch FT", "Foul rate", "Selection", "Scoutability", "Contest rate",
    "Spacing",
})

#: metric -> the reliability-book key that measured it. Absent means the book
#: has no measurement, and the finding takes `UNMEASURED_R`.
METRIC_RELIABILITY = {
    "GuardCliff": ("player", "band_fg"),
    "Selection": ("player", "band_share"),
    "Spacing": ("player", "band_share"),
    "PlayType": ("player", "playtype_share"),
    "PlayStyle": ("player", "playtype_share"),
    "PnR role": ("player", "playtype_ppp"),
    "Rim finish": ("player", "kind_fg"),
    "3P%": ("player", "band_fg"),
    "POE": ("player", "pps"),
    "Shot creation": ("player", "pps"),
    "Def load": ("defender", "load"),
    "Def area": ("defender", "area_share"),
    "Def role": ("defender", "family_share"),
    "Def scheme": ("defender", "scheme_share"),
    "Assignment": ("defender", "assignment_share"),
    "Def footprint": ("defender", "footprint"),
    "Defense": ("defender", "allowed_fg"),
    "Rim D": ("defender", "allowed_fg"),
    "Perim D": ("defender", "allowed_fg"),
    "Contest rate": ("team", "contest_share_allowed"),
    "Shots allowed": ("team", "band_share"),
    "3PT diet": ("team", "band_share"),
    "Scheme": ("team", "scheme_mix"),
    "Margin mix": ("game", "xmargin_vs_margin"),
    "Deserved": ("game", "xmargin_vs_margin"),
}

#: Which way a POSITIVE z reads for the coach: +1 good, -1 bad. A metric absent
#: here has no authored orientation and its findings carry `direction = 0`,
#: which renders neutral. Guessing the sign is how a page tells a coach she is
#: bad at something she is good at, so absence is the safe default.
METRIC_Z_ORIENT = {
    "POE": 1, "Selection": 1, "3P%": 1, "Rim finish": 1, "Shot creation": 1,
    "Impact": 1, "Consistency": 1, "Form": 1, "Playmaking": 1,
    "Rebounding": 1, "Clutch FT": 1, "Fouls drawn": 1, "Q4": 1,
    "Disruption": 1, "Defense": -1, "Rim D": -1, "Perim D": -1,
    "GuardCliff": -1, "HandGap": -1, "Foul rate": -1, "TO type": -1,
    "Ball security": -1, "Scoutability": -1, "Volatility": -1,
    "Takeaways": 1, "Contest rate": 1, "Close games": 1, "Momentum": 1,
    "Off engine": 1, "Def engine": 1, "Runs": 1, "Chemistry": 1,
    "Lineups": 1, "Transition": 1, "Transition D": -1, "Spacing": 1,
}


def reliability_of(metric):
    """The measured split-half r for a metric, or `UNMEASURED_R`.

    Negative measurements are clamped to 0.0 rather than passed through: a
    metric that predicts itself at r = -0.15 carries no information about the
    future, and a negative multiplier would flip the whole severity score's
    sign. It still renders (the law), it simply cannot rank.
    """
    key = METRIC_RELIABILITY.get(metric)
    r = REL.measured(*key) if key else None
    if r is None:
        return UNMEASURED_R
    return max(0.0, float(r))


# ══════════════════════════════════════════════════════════════════════════════
#  THE POINTS-PER-GAME TRANSLATOR
# ══════════════════════════════════════════════════════════════════════════════
# Every derivation below is a named function of (finding, ctx) returning points
# per game or None. `ctx` is a plain dict the caller assembles from output the
# page has ALREADY computed — no derivation is allowed to trigger a fresh event
# walk, because prod is 1 vCPU and this table runs on every render.

def _f(v):
    """float or None — the pools carry Decimals and strings in places."""
    try:
        if v is None:
            return None
        v = float(v)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def _lg_mean(ctx, key):
    """League mean of a `ts` pack column over every team with the column."""
    pack = (ctx or {}).get("ts_all") or {}
    vals = [_f((row or {}).get(key)) for row in pack.values()]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def _pts_margin_mix(fnd, ctx):
    """The deserved terms are already points per game, and they sum to the
    final margin exactly — the one conversion in the app that needs no
    conversion. The finding is about the term that swings hardest, so the
    materiality is that term's own season mean."""
    des = (ctx or {}).get("deserved") or {}
    ranked = des.get("ranked_terms") or []
    means = des.get("means") or {}
    if not ranked:
        return None
    return _f(means.get(ranked[0][0]))


def _pts_guard_cliff(fnd, ctx):
    """Points a shooter leaves on the floor when the defense takes her space.

    (open FG% - contested FG%) x her contested attempts per game x 2. That is
    the swing between her contested shots converting at her contested rate and
    at her open rate — a real, bounded quantity, not a forecast.
    """
    cl = ((ctx or {}).get("cliffs") or {}).get(fnd.get("pid"))
    gp = _f((ctx or {}).get("gp"))
    if not cl or not gp:
        return None
    cliff = _f(cl.get("cliff"))
    gn = _f(cl.get("gn"))
    if cliff is None or gn is None:
        return None
    return -(cliff / 100.0) * (gn / gp) * 2.0


def _pts_wpa(fnd, ctx):
    """Win probability added, priced in points via the league's own scoring.

    `hoopwar.wins_per_point` inverts the Pythagorean exponent at the pool's
    points per game, so this is the league's exchange rate, not a constant
    borrowed from the NBA.
    """
    imp = ((ctx or {}).get("wpa") or {}).get(fnd.get("pid")) or {}
    wpp = _f((ctx or {}).get("wins_per_point"))
    gp = _f(imp.get("games")) or _f((ctx or {}).get("gp"))
    tot = _f(imp.get("wpa"))
    if tot is None:
        off, dfn = _f(imp.get("off_wpa")), _f(imp.get("def_wpa"))
        tot = (off or 0.0) + (dfn or 0.0) if (off or dfn) else None
    if tot is None or not wpp or not gp:
        return None
    return (tot / wpp) / gp        # wins -> points -> points per game


def _pts_ball_security(fnd, ctx):
    """Empty trips, priced. (team TOV% - league TOV%) x poss/g x league PPP."""
    ts = (ctx or {}).get("ts") or {}
    tov, poss = _f(ts.get("TOVpct")), _f(ts.get("poss_pg"))
    lg_tov, lg_ppp = _lg_mean(ctx, "TOVpct"), _lg_mean(ctx, "PPP")
    if None in (tov, poss, lg_tov, lg_ppp):
        return None
    # TOVpct is a percentage in this pack (0-100), poss_pg a count per game
    return -((tov - lg_tov) / 100.0) * poss * lg_ppp


def _pts_takeaways(fnd, ctx):
    """The mirror: opponent trips this defense ends without a shot, priced."""
    ts = (ctx or {}).get("ts") or {}
    poss = _f(ts.get("poss_pg"))
    tov_forced = _f(ts.get("stl_r"))          # steals per 100 opp possessions
    lg_forced, lg_ppp = _lg_mean(ctx, "stl_r"), _lg_mean(ctx, "PPP")
    if None in (poss, tov_forced, lg_forced, lg_ppp):
        return None
    return ((tov_forced - lg_forced) / 100.0) * poss * lg_ppp


def _pts_team_orb(fnd, ctx):
    """Extra shots off the offensive glass, priced at the league's PPP."""
    ts = (ctx or {}).get("ts") or {}
    orb, poss = _f(ts.get("ORBpct")), _f(ts.get("poss_pg"))
    lg_orb, lg_ppp = _lg_mean(ctx, "ORBpct"), _lg_mean(ctx, "PPP")
    if None in (orb, poss, lg_orb, lg_ppp):
        return None
    # a miss is the rebound chance; misses/g ~= poss/g x (1 - the pool's
    # scoring rate) is not held here, so use the pack's own oreb chances
    miss_pg = _f(ts.get("fga_pg"))
    if miss_pg is None:
        return None
    return ((orb - lg_orb) / 100.0) * miss_pg * lg_ppp


#: metric -> derivation. A metric absent here is UNTAGGED — band 2, no pts/g
#: chip, and that is a correct outcome, not a gap to paper over.
PTS_RULES = {
    "Margin mix": _pts_margin_mix,
    "Deserved": _pts_margin_mix,
    "GuardCliff": _pts_guard_cliff,
    "Impact": _pts_wpa,
    "Ball security": _pts_ball_security,
    "Takeaways": _pts_takeaways,
}

#: Team-level metrics whose derivation is the team ORB read. Kept separate from
#: PTS_RULES only because the player metric of the same name is a different
#: quantity and must NOT take this conversion.
TEAM_PTS_RULES = {
    "Rebounding": _pts_team_orb,
}


def materiality(fnd, ctx):
    """Points per game at stake for one finding, or None.

    Exception-isolated per finding: a bad derivation may not stop the rest of
    the list from ranking (§8 of the design). A raising rule yields None, which
    is band 2 — the same, honest place a metric with no rule at all lands.
    """
    rules = TEAM_PTS_RULES if fnd.get("family") == "team" else PTS_RULES
    fn = rules.get(fnd.get("metric")) or PTS_RULES.get(fnd.get("metric"))
    if fn is None:
        return None
    try:
        v = _f(fn(fnd, ctx))
    except Exception:
        return None
    if v is None or abs(v) < 0.05:
        # below a tenth of a point a game the tag is noise dressed as a number
        return None
    return v


def direction_of(fnd):
    """+1 good, -1 bad, 0 unknown. Sign only — never part of the ordering, and
    it never suppresses anything."""
    pts = fnd.get("pts")
    if pts is not None and abs(pts) >= 0.05:
        return 1 if pts > 0 else -1
    orient = METRIC_Z_ORIENT.get(fnd.get("metric"))
    z = _f(fnd.get("z"))
    if orient is None or z is None or abs(z) < 1e-9:
        return 0
    return 1 if (orient * z) > 0 else -1


# ══════════════════════════════════════════════════════════════════════════════
#  COLLECTION AND RANKING
# ══════════════════════════════════════════════════════════════════════════════

def _norm(raw, *, family, subject=None, pid=None, key=None):
    """One miner line -> the ranking's own record shape."""
    metric = str(raw.get("metric") or "Read")
    return {
        "key": key or f"{family}:{subject or ''}:{metric}:"
                      f"{str(raw.get('text'))[:24]}",
        "family": family,
        "subject": subject,
        "pid": pid,
        "metric": metric,
        "text": raw.get("text"),
        "n": raw.get("n"),
        "z": raw.get("z", raw.get("score")),
        "section": METRIC_SECTION.get(metric, S_RECEIPTS),
        "evidence": METRIC_EVIDENCE.get(metric),
        "rehearsable": metric in REHEARSABLE,
    }


def collect(*, player_feed=None, names=None, team_lines=None, ported=None,
            ported_sections=None):
    """Normalise the three families into one list of finding records.

    `player_feed`   {pid: [line, ...]} from `insights.build_feed`
    `names`         {pid: display name}
    `team_lines`    [line, ...] from `team_insights.team_insight_feed`
    `ported`        {section_key: [(badge, n, html), ...]} from `_ported`
    `ported_sections`  {section_key: (short label, evidence view)} so a ported
                    line can name its own home without this module importing
                    the render layer.

    EVERY line handed in comes back out. That is the point.
    """
    out = []
    for pid, lines in (player_feed or {}).items():
        nm = (names or {}).get(pid) or f"#{pid}"
        for i, ln in enumerate(lines or []):
            out.append(_norm(ln, family="player", subject=nm, pid=pid,
                             key=f"p:{pid}:{i}:{ln.get('metric')}"))
    for i, ln in enumerate(team_lines or []):
        out.append(_norm(ln, family="team", subject="Team",
                         key=f"t:{i}:{ln.get('metric')}"))
    for skey, lines in (ported or {}).items():
        short, home = (ported_sections or {}).get(skey, (skey, None))
        for i, item in enumerate(lines or []):
            badge, n, txt = (list(item) + [None, None, None])[:3]
            metric = str(badge or short)
            out.append({
                "key": f"e:{skey}:{i}",
                "family": "engine",
                "subject": short,
                "pid": None,
                "metric": metric,
                "text": txt,
                "n": n,
                # the ported engines were never scored; they carry no z and
                # they are not given a fake one.
                "z": None,
                "section": METRIC_SECTION.get(metric, S_RECEIPTS),
                "evidence": (METRIC_EVIDENCE.get(metric)
                             or ((home, None) if home else None)),
                "rehearsable": metric in REHEARSABLE,
            })
    return out


def score(findings, ctx=None, *, gp=None):
    """Attach pts / r / confidence / severity / band / direction, in place-safe
    copies. Returns a new list, same length, same order."""
    ctx = dict(ctx or {})
    if gp is not None:
        ctx.setdefault("gp", gp)
    book_gp = ctx.get("gp") or 0
    out = []
    for f in findings:
        f = dict(f)
        try:
            f["pts"] = materiality(f, ctx)
        except Exception:
            f["pts"] = None
        f["r"] = reliability_of(f.get("metric"))
        # a player finding is only as confident as THAT player's book
        f["gp"] = f.get("gp") or ctx.get("player_gp", {}).get(f.get("pid")) \
            or book_gp
        f["confidence"] = confidence(f["gp"])
        f["direction"] = direction_of(f)
        if f["pts"] is not None:
            f["band"] = BAND_TAGGED
            f["severity"] = abs(f["pts"]) * f["r"] * f["confidence"]
        else:
            f["band"] = BAND_UNTAGGED
            f["severity"] = f["r"] * f["confidence"]
        out.append(f)
    return out


def rank(findings, ctx=None, *, gp=None):
    """The whole list, scored and ordered. NOTHING is dropped — a caller that
    wants a spotlight slices the result and says so on screen."""
    scored = score(findings, ctx, gp=gp)
    scored.sort(key=lambda f: (
        f["band"],                                  # bands never interleave
        -f["severity"],
        -abs(_f(f.get("z")) or 0.0),                # tiebreak, not the score
        str(f.get("key")),                          # total and stable
    ))
    return scored


def monday(ranked):
    """Findings that point the wrong way AND sit on an authored-rehearsable
    metric. A display grouping inside Monday only — §4.3. It removes nothing
    from any other section, and the full uncapped list still renders there."""
    return [f for f in ranked
            if f.get("rehearsable") and f.get("direction", 0) < 0]


def by_section(ranked):
    """{section: [finding, ...]} preserving the ranked order."""
    out = {s: [] for s in SECTIONS}
    for f in ranked:
        out.setdefault(f.get("section") or S_RECEIPTS, []).append(f)
    return out


def dest_label(view, sub=None):
    """'Charts → Offense → Shooting' from a (view, path) destination."""
    steps = ([] if sub is None else
             list(sub) if isinstance(sub, (tuple, list)) else [sub])
    return " → ".join([str(view)] + [str(s) for s in steps])


def pts_chip(pts):
    """`≈ +2.3 pts/g`, or an em dash when the metric has no derivation."""
    if pts is None:
        return "—"
    return f"≈ {pts:+.1f} pts/g"
