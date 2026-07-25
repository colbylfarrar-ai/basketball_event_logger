"""
shot_kinds.py — what KIND of shot it was (depth axis), not just where on the arc.

The app has always had two shot descriptors: `zone` (LC/LW/C/RW/RC — five angular
sectors fanning out from the hoop) and `shot_type` (2 or 3). Neither one carries
DEPTH, so nothing in the app could say the word "floater". This module adds that
axis. It is pure geometry over `shot_x`/`shot_y`, so it applies retroactively to
every shot ever tapped; no new tracking, no schema change.

WHY THIS EXISTS — THE ZONE-C PROBLEM
------------------------------------
Measured on the live book (3,798 located shots, 43 tracked games): zone C is more
than half of all located 2s and spans a median 3.9 ft with a p10 of 2.5 ft and a
p90 of 7.7 ft. That single bucket therefore blends 1.13-PPS rim shots with
0.58-PPS floaters — a ~0.55 PPS spread averaged into one number. The five zones
are an ANGLE system with no depth axis, so every shooting read keyed on zone has
been averaging across the sharpest efficiency cliff in the sport.

The cliff is at 4 feet and it is enormous. 2-ft bands, 2-point attempts only:

    0-2 ft   n=67    FG% 68.7   PPS 1.37
    2-4 ft   n=989   FG% 55.9   PPS 1.12
    4-6 ft   n=595   FG% 31.9   PPS 0.64   <-- cliff
    6-8 ft   n=220   FG% 26.4   PPS 0.53
    8-10 ft  n=143   FG% 20.3   PPS 0.41

Past 4 ft a 2 does not recover: the 4-10 ft "floater" band (0.58 PPS) shoots no
better than the midrange (0.55 PPS). The received wisdom that a floater beats a
15-footer is false in this data, and that band is a quarter of every shot taken.

THE TAXONOMY, AND WHY THESE BOUNDARIES
--------------------------------------
Tuned to this league's measured distribution, not copied from NBA convention.
RIM_FT and FLOATER_FT are where THIS data's cliffs actually sit, and both are
registered in model_constants so a recal can move them without a code change.

Measured league table (live book, 2026-07-25):

    kind           n     share    FG%     PPS
    rim         1056     27.8%   56.7%   1.134
    floater      958     25.2%   28.9%   0.578
    mid          429     11.3%   27.5%   0.550
    corner3      384     10.1%   31.5%   0.945
    abovebreak3  971     25.6%   28.4%   0.853
    unknown      221         -   37.6%   0.882

CORNER 3s USE court_geom, NOT A SECOND DEFINITION
-------------------------------------------------
`court_geom.is_corner_three` already exists and is derived from the real NFHS
arc (THREE_R 19.75, CORNER_X 19.0, and the corner/arc join CBREAK ~5.39 ft).
An earlier spec proposed a separate |x|>=20 & y<=14 box for this module; that
would have put two disagreeing definitions of "corner 3" in one codebase and
reclassified 101 of the 1,355 located 3s away from what the rest of the app
already renders. This module calls court_geom instead. Only the rim and floater
lines — which are genuinely new and genuinely tuned — are constants here.

The 2/3 split comes from the LOGGED `shot_type`, not from geometry, because the
tap is the coach's own call and the book is clean: measured on the live DB, zero
3s are logged inside the arc and zero 2s beyond 22.5 ft.

WHAT THIS MODULE WILL AND WILL NOT LET YOU SAY
----------------------------------------------
Split-half reliability, measured odd/even games on the live book and corrected
by Spearman-Brown (the house gate convention — a metric that does not correlate
with ITSELF cannot carry a verdict):

    unit    metric            r      SB     at
    player  floater share   .636    .778    >=10 located att/half
    player  rim share       .626    .770    >=20 att/half
    player  PPS             .317    .481    >=10 att/half  (and NEGATIVE at 40+)
    player  floater PPS     .078    .145    >=10 att/half
    team    floater share   .582    .736    >=40 att/half
    team    rim share       .640    .780    >=100 att/half
    team    PPS             .569    .725    >=40 att/half
    team    floater PPS     .501    .668    >=40 att/half

Read that table before adding any caller. SHARE is a count ratio and is the
robust half — a player's floater share genuinely predicts her own floater share.
RATES are the fragile half, and a player's floater FG% has essentially ZERO
split-half reliability (r=.078): it does not predict itself, at any threshold
this book can reach. So the spec's proposed scout line — "their #12 lives on the
floater, 34% on 61 attempts" — is half signal and half noise. "Lives on the
floater" is real. The 34% is a coin flip wearing a decimal point, and this module
will not hand a caller a per-player kind FG% dressed as a judgment.

Hence the gates below, and hence the shape of every return: shares and raw counts
always, rates only above their own gate, and the verdict speaking from shrunk
values so it fires no earlier than the evidence allows. Unit counts behind those
correlations are small (42 players, 9 teams), so treat the r's as order-of-
magnitude, which is exactly why the gates are set conservatively above them.

THE SECOND TAXONOMY — DEPTH BANDS (added 2026-07-26)
---------------------------------------------------
The 5 kinds split 3s by ANGLE (corner vs above-break) and 2s by depth. The
BANDS cut splits everything by depth: 0-4 ft, 4 ft-to-arc, a 3 at the arc, a 3
from 23+. Both now live here, and both render — the decision was to show the
two cuts side by side rather than replace one, because each carries information
the other cannot.

Re-measured on the live book (F / 2025-2026, 35 games, 3,246 shots) with 200
random half-splits rather than one odd/even split, because at 24-28 qualifying
players a single split's r has a sampling spread near +/-.2 — wider than the
differences this choice turned on. What that found:

    league table, the rendered pool
        rim04    836  27.4%  FG 54.3  PPS 1.086
        two419  1147  37.5%  FG 27.4  PPS 0.548
        arc3     692  22.6%  FG 27.6  PPS 0.828
        deep3    381  12.5%  FG 25.7  PPS 0.772

    player SHARE reliability (SB)   kind cut        band cut
        the problem band            .81 floater     .87 two419
        the midrange                .70 mid         (merged in)
        the deep look               .90 abovebreak3 .91 deep3

    player RATE reliability (SB, whole book — the conservative column)
        rim / rim04 FG%             .11   <- the largest sample, the worst r
        floater FG%                 .285
        two419 FG%                  .52   <- best available, still not a verdict
        above-break-3 FG%          -.25

1. MERGING HELPS SHARES. Folding floater+mid into one 4ft-to-arc band raises
   the share's reliability (.81/.70 -> .87) and follows the measurement that
   made the merge worth trying: the floater (0.569 PPS) and the midrange
   (0.503) are the same shot, and the app was splitting a distinction the
   league does not have.

2. MERGING DOES NOT RESCUE RATES, WHICH ANSWERS THE QUESTION THIS CUT WAS FOR.
   The open question was whether coarser cells would finally give enough n per
   player for RATES to clear. They roughly double the qualifying players (5-6
   -> 10-11) and lift the best band from SB .285 to .52 — real movement, and
   still short. Player rates stay withheld or hollow-dotted; see `rate_reads`.

3. THE MOST WANTED READ IS THE LEAST RELIABLE ONE. Rim FG% — "does she finish"
   — is measured from more attempts per player than any other cell in the book
   and predicts itself at SB .11. This is not a sample-size problem and more
   games will not fix it, which is why the refusal is wired to a measured
   reliability floor rather than to an attempt count.

Streamlit-free.
"""
from __future__ import annotations

from collections import defaultdict

import helpers.court_geom as CG
import helpers.stats as S


#: Rim line, feet from the hoop. The measured cliff: 2-4 ft shoots 55.9%, 4-6 ft
#: shoots 31.9%. Registered in model_constants so a recal can move it.
RIM_FT = 4.0

#: Outer edge of the floater / short-paint band. Past here a 2 is a midrange and
#: is no worse, so there is nothing left to separate.
FLOATER_FT = 10.0

#: The 3-point depth split. Measured on the live book, the 3s beyond 23 ft are
#: 0.772 PPS against 0.828 inside it — a real gap, and a smaller one than the
#: corner/above-break angular split (0.874 vs 0.784) it sits beside.
DEEP_FT = 23.0

#: Ordered for display: worst-to-best is not the order a coach reads, distance is.
KINDS = ("rim", "floater", "mid", "corner3", "abovebreak3")

#: The DEPTH taxonomy — four bands, split by distance and gated by the logged
#: shot_type so a 2 and a 3 at the same distance are never pooled. See
#: `classify_band` for why the 3-point bands carry no lower edge.
BANDS = ("rim04", "two419", "arc3", "deep3")

#: Shots with no coordinate. Never dropped, never folded into a real kind — they
#: are 5.5% of the book and pretending they are zero would bias every share.
UNKNOWN = "unknown"

KIND_LABELS = {
    "rim": "Rim",
    "floater": "Floater / short paint",
    "mid": "Midrange",
    "corner3": "Corner 3",
    "abovebreak3": "Above-break 3",
    UNKNOWN: "Unlocated",
}

BAND_LABELS = {
    "rim04": "0-4 ft",
    "two419": "4 ft - arc",
    "arc3": "3 at the arc",
    "deep3": f"3 from {DEEP_FT:.0f}+ ft",
    UNKNOWN: "Unlocated",
}

#: A coach reads a distance, not a slug. Used in captions and verdicts.
BAND_PROSE = {
    "rim04": "inside 4 feet",
    "two419": "from 4 feet to the arc",
    "arc3": "from the arc",
    "deep3": f"from {DEEP_FT:.0f} feet and out",
}

# ── display gates, set by the split-half measurement in the docstring ─────────
#: Located attempts before a PLAYER's kind shares are shown as a read. The
#: measurement supports 20 (10/half, SB .78); rim share wants ~40 but shares
#: move together, so one gate covers the block and rim is captioned.
MIN_PLAYER_SHARE_ATT = 20

#: Located attempts before a TEAM's kind shares are shown. 80 = 40/half, SB .74.
MIN_TEAM_SHARE_ATT = 80

#: Attempts IN A KIND before that cell's FG%/PPS is shown at all. Team-level kind
#: PPS reaches SB .67 at 40/half; this is the per-cell equivalent and is
#: deliberately well above the point where the player-level rate collapsed.
MIN_KIND_RATE_ATT = 40

#: A per-player kind rate is never a judgment in this book (r=.078). Callers that
#: want one anyway get raw counts and must label them descriptive. This flag
#: exists so the refusal is greppable rather than a comment someone deletes.
PLAYER_KIND_RATES_ARE_NOISE = True

#: Shrink constant for the verdict's share estimate — pulls a team's floater
#: share toward the league share by volume, so a 30-shot sample cannot fire a
#: season-changing sentence on its own.
SHARE_K = 60

# ── materiality: a gate on SAMPLE is not a gate on SIZE ───────────────────────
# Measured on the live book, the sample gate alone let five teams fire the
# headline verdict, four of which read "1 more floater than a league-average
# diet — 1 point left on the floor, about 0.1 a game". True, well-sampled, and
# worthless: a team sitting ON the league average was being handed a
# season-changing sentence about nothing. Only Jay Girls (38 excess floaters,
# 4.2 points a game) had something a coach should act on.
#
# So the verdict must clear BOTH bars — enough evidence, and enough size.

#: Share points above the league diet before the excess is worth a sentence.
MIN_VERDICT_SHARE_DELTA = 0.05

#: And the cost has to be worth a coach's attention. A tenth of a point a game
#: is not, no matter how well measured.
MIN_VERDICT_PTS_PER_GAME = 1.0

#: When the caller has no game count, fall back to a season-total bar instead of
#: silently skipping the materiality check.
MIN_VERDICT_PTS_TOTAL = 10.0


def classify(x, y, shot_type):
    """The kind of shot at (x, y) logged as `shot_type` (2 or 3).

    Returns one of KINDS, or UNKNOWN when the shot carries no coordinate. The
    2/3 split is taken from the logged shot_type (the coach's tap); geometry
    only decides the depth band and the corner/above-break split.
    """
    if x is None or y is None:
        return UNKNOWN
    if shot_type == 3:
        return "corner3" if CG.is_corner_three(x, y) else "abovebreak3"
    d = CG.shot_distance(x, y)
    if d <= RIM_FT:
        return "rim"
    if d <= FLOATER_FT:
        return "floater"
    return "mid"


def classify_band(x, y, shot_type):
    """The DEPTH band of a shot — one of BANDS, or UNKNOWN.

    Four bands, gated by the logged shot_type so a 2 and a 3 at the same
    distance never share a cell:

        rim04    a 2 inside RIM_FT
        two419   a 2 beyond RIM_FT (out to the arc, by definition of a 2)
        arc3     a 3 inside DEEP_FT
        deep3    a 3 at DEEP_FT or beyond

    WHY THE 3-POINT BANDS HAVE NO LOWER EDGE. The cut was specified as
    0-4 / 4-19 / 19-23 / 23+, and the 19 cannot be taken literally. A corner 3
    sits 19.0-19.75 ft from the hoop — SHORTER than the arc's 19.75 ft top,
    because the corner is a straight segment closer to the rim than the arc's
    apex. A band floored at 19 (or at 19.75) would therefore contain few corner
    3s or none at all, and the corner is the most valuable 3 on the floor
    (0.874 PPS against 0.784 above the break). With shot_type as the gate the
    floor is redundant anyway: every logged 3 is behind the line by the coach's
    own tap, and the book is clean — zero 3s logged inside the arc. So the 3s
    split at DEEP_FT only.

    Symmetrically, `two419`'s upper edge is not 19 but "wherever the 2 ends",
    which is what a shot_type gate already means.
    """
    if x is None or y is None:
        return UNKNOWN
    d = CG.shot_distance(x, y)
    if shot_type == 3:
        return "deep3" if d >= DEEP_FT else "arc3"
    return "rim04" if d <= RIM_FT else "two419"


def classify_shot(shot):
    """classify() for a located_shots()/mapped_shots() dict.

    Note these feeds carry `value` (2/3) rather than the raw `shot_type`, and
    mapped_shots may carry a zone-centroid APPROXIMATION with approx=True — an
    approximated coordinate is a zone stand-in, not a location, so it classifies
    as UNKNOWN rather than inventing a depth this shot never had.
    """
    if shot.get("approx"):
        return UNKNOWN
    return classify(shot.get("x"), shot.get("y"), shot.get("value"))


def classify_band_shot(shot):
    """classify_band() for a located_shots()/mapped_shots() dict."""
    if shot.get("approx"):
        return UNKNOWN
    return classify_band(shot.get("x"), shot.get("y"), shot.get("value"))


# ── the two taxonomies, as data so one aggregation path serves both ───────────
#: name -> (ordered cells, labels, classifier, prose). Callers pass a taxonomy
#: name; nothing downstream branches on which one it got. Adding a third cut
#: means adding a row here, not forking kind_table.
TAXONOMIES = {
    "kind": (KINDS, KIND_LABELS, classify_shot, None),
    "band": (BANDS, BAND_LABELS, classify_band_shot, BAND_PROSE),
}

#: The taxonomy that owns DISPLAY and PLAYER-level reads. Depth beat angle on
#: every share-reliability comparison measured (player 4ft-to-arc share SB .87
#: against floater .81 / mid .70) and is the only cut under which any per-player
#: RATE clears the reliability floor at all. The 5 kinds keep the model — see
#: stats._sq_loc — and keep their place beside these on screen, because the
#: corner/above-break split is angular information the depth cut cannot carry.
DISPLAY_TAXONOMY = "band"


def _blank():
    return {"n": 0, "fgm": 0, "pts": 0.0}


def _finish(agg, located, taxonomy="kind"):
    """Turn raw {cell: {n,fgm,pts}} counters into the display dict.

    `share` is over LOCATED attempts only (unknown cannot be assigned a cell, so
    including it in the denominator would shrink every share by the coverage
    rate). Rates are None below MIN_KIND_RATE_ATT rather than being rounded into
    a number a caller might print.
    """
    cells, labels, _, _ = TAXONOMIES[taxonomy]
    out = {}
    for k in (*cells, UNKNOWN):
        a = agg.get(k) or _blank()
        rated = a["n"] >= MIN_KIND_RATE_ATT
        out[k] = {
            "n": a["n"],
            "fgm": a["fgm"],
            "pts": a["pts"],
            "share": (a["n"] / located) if (located and k != UNKNOWN) else None,
            "fg": (a["fgm"] / a["n"]) if (rated and a["n"]) else None,
            "pps": (a["pts"] / a["n"]) if (rated and a["n"]) else None,
            "rated": rated,
            "label": labels[k],
        }
    return out


def kind_table(shots, taxonomy="kind"):
    """{cell: {n, fgm, pts, share, fg, pps, rated, label}} over a shot list.

    `shots` is a located_shots()/mapped_shots() list. `taxonomy` picks the cut —
    "kind" (the 5 angular/depth kinds) or "band" (the 4 depth bands); both are
    aggregated by this one path so they cannot drift. Adds a "_meta" key with
    the located / total counts so every caller can print its own coverage
    instead of guessing at it, plus the taxonomy name so a renderer handed a
    table can label it without being told twice.
    """
    _, _, classifier, _ = TAXONOMIES[taxonomy]
    agg = defaultdict(_blank)
    located = 0
    for s in shots:
        k = classifier(s)
        a = agg[k]
        a["n"] += 1
        if k != UNKNOWN:
            located += 1
        if s.get("make"):
            a["fgm"] += 1
            a["pts"] += float(s.get("value") or 2)
    out = _finish(agg, located, taxonomy)
    total = sum(a["n"] for a in agg.values())
    out["_meta"] = {
        "total": total,
        "located": located,
        "located_share": (located / total) if total else None,
        "taxonomy": taxonomy,
    }
    return out


def band_table(shots):
    """The depth-band table — kind_table over the 4-band taxonomy."""
    return kind_table(shots, taxonomy="band")


def both_tables(shots):
    """{"band": ..., "kind": ...} in ONE pass' worth of shot list.

    The display decision is to show both cuts rather than replace one with the
    other, so this exists to make "both" the cheap call and stop a renderer from
    fetching the shot feed twice on a 1 vCPU box.
    """
    return {"band": kind_table(shots, "band"), "kind": kind_table(shots, "kind")}


def league_table(gender=None, game_ids=None, events=None, shots=None,
                 taxonomy="kind"):
    """The league-wide table — the baseline every team read compares to.

    Pooled across every tracked game, which is the only level this book can fit
    a stable per-cell rate at.
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    return kind_table(shots, taxonomy)


def _shots(gender=None, game_ids=None, events=None):
    """Located + approximated shots for the tracked sample (one event pass).

    mapped_shots is used rather than located_shots so that unlocated legacy
    shots still appear in the coverage denominator as UNKNOWN; classify_shot
    sends the zone-centroid approximations there.
    """
    if events is None:
        import helpers.playtypes as PT
        gids = game_ids if game_ids is not None else PT._tracked_game_ids(gender)
        events = S.fetch_events(gids) if gids else []
    return S.mapped_shots(events=events)


def team_table(team_id, gender=None, game_ids=None, events=None, shots=None,
               offense=True, taxonomy="kind"):
    """Table for one team's own shots (offense) or its opponents' (defense).

    The defensive view is what each team CONCEDES by cell, which is the read
    behind "our 2-3 gives up rim".
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    mine = [s for s in shots
            if (s.get("team_id") == team_id) == bool(offense)
            and s.get("team_id") is not None]
    return kind_table(mine, taxonomy)


def player_table(player_id, gender=None, game_ids=None, events=None, shots=None,
                 taxonomy="kind"):
    """Table for one player's shots.

    SHARES here are trustworthy above MIN_PLAYER_SHARE_ATT. The per-cell `fg`
    and `pps` are gated by MIN_KIND_RATE_ATT and will almost always be None at
    player level in this book — that is correct, not a bug. Even where a rate
    survives that attempt gate it may not survive RELIABILITY: see
    `rate_reads`, which is the gate a renderer should actually consult.
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    return kind_table([s for s in shots if s.get("player_id") == player_id],
                      taxonomy)


def rate_reads(table, unit="player"):
    """Per-cell display permission for the RATES in a table.

    Returns {cell: {"level", "sb", "show", "glyph", "caption"}}. Two independent
    bars, and a cell must clear both:

      1. ATTEMPTS — MIN_KIND_RATE_ATT, already applied by `_finish` (a rate is
         None below it). Precision.
      2. RELIABILITY — does this metric predict itself at this unit and cell?
         Stability. `helpers/reliability.py` holds the measured book.

    The second bar is the one that matters and the one that was missing. A
    player's rim FG% is estimated from more attempts than any other cell in the
    book and still predicts itself at SB .11, so it clears bar 1 and fails bar
    2. Attempts buy you precision about a quantity that is not stable; they
    cannot buy you stability.

    Cells above the floor but below `reliability.FAIR_SB` are SHOWN with a
    hollow dot and their r printed inline, not hidden — the standing rule here
    is density, and a number labelled with its own unreliability is more
    information than a blank cell. Cells below the floor are withheld with a
    reason, because a dot on noise still puts the noise on screen.
    """
    import helpers.reliability as REL
    taxonomy = table.get("_meta", {}).get("taxonomy", "kind")
    cells, _, _, _ = TAXONOMIES[taxonomy]
    out = {}
    for k in cells:
        sb = REL.measured(unit, "fg", k)
        lvl = REL.level(sb)
        cell = table.get(k) or {}
        out[k] = {
            "level": lvl,
            "sb": sb,
            "show": lvl != "withhold" and cell.get("fg") is not None,
            "glyph": REL.LEVEL_GLYPHS[lvl],
            "caption": REL.caption(sb, metric=f"{cell.get('label', k)} FG%"),
        }
    return out


def share_reads(table, unit="player"):
    """Per-cell display permission for the SHARES in a table.

    Shares are the robust half of this module — every cell, both units, both
    taxonomies measured SB .70 or better — so this rarely withholds. It exists
    so a renderer asks the same question of both halves of a table instead of
    dotting rates and leaving shares naked.
    """
    import helpers.reliability as REL
    taxonomy = table.get("_meta", {}).get("taxonomy", "kind")
    cells, _, _, _ = TAXONOMIES[taxonomy]
    out = {}
    for k in cells:
        sb = REL.measured(unit, "share", k)
        if sb is None:
            sb = REL.measured(unit, f"{'band' if taxonomy == 'band' else 'kind'}_share")
        lvl = REL.level(sb)
        out[k] = {"level": lvl, "sb": sb, "show": lvl != "withhold",
                  "glyph": REL.LEVEL_GLYPHS[lvl],
                  "caption": REL.caption(sb, metric="Share")}
    return out


def kind_by_tag(events, tag, team_id=None, offense=True, min_n=MIN_KIND_RATE_ATT,
                taxonomy="kind"):
    """Cross-tab of shot kind against an event tag — {tag_value: kind_table}.

    Works off raw EVENTS rather than a mapped-shots list because the tags this
    is for (`defense`, `play_type`) live on the event and are dropped by the
    shot feeds. `offense=False` reads the shots the team ALLOWED, whose
    `defense` tag is the scheme THIS team was running — which is the whole
    point of the defensive view.

    The rates inside each returned table are gated exactly as everywhere else,
    so a scheme with 30 tagged shots reports its shares and withholds its
    percentages. `min_n` drops tag values too thin to list at all; on the live
    book that removes the long tail of one-off scheme tags (matchup, diamond1,
    press_221 and friends all sit in single digits) rather than rendering a row
    per novelty.
    """
    buckets = defaultdict(list)
    for e in events:
        if e.get("event_type") != "shot":
            continue
        v = e.get(tag)
        if not v:
            continue
        st_ = e.get("shooter_team_id")
        if team_id is not None and (st_ == team_id) != bool(offense):
            continue
        buckets[v].append({
            "x": e.get("shot_x"), "y": e.get("shot_y"),
            "value": 3 if e.get("shot_type") == 3 else 2,
            "make": e.get("shot_result") == "make",
        })
    return {v: kind_table(sh, taxonomy) for v, sh in buckets.items()
            if len(sh) >= min_n}


def kind_by_shot_tag(shots, tag, min_n=MIN_KIND_RATE_ATT, taxonomy="kind"):
    """kind_by_tag over an already-built shot list — {tag_value: kind_table}.

    located_shots() carries `defense` and `play_type`, so a caller that already
    holds a scoped shot feed (the Defense tab does, cached) crosses it here
    instead of taking a second pass over the event stream. On a 1 vCPU box that
    difference is the whole reason this variant exists.
    """
    buckets = defaultdict(list)
    for s in shots:
        v = s.get(tag)
        if v:
            buckets[v].append(s)
    return {v: kind_table(sh, taxonomy) for v, sh in buckets.items()
            if len(sh) >= min_n}


def diet(team_id=None, player_id=None, gender=None, game_ids=None, events=None,
         shots=None, offense=True, taxonomy="kind"):
    """A team's or player's kind SHARES against the league's, with the gate.

    Returns {"table", "league", "delta", "n_located", "gated", "min_att",
    "level"} where `delta` is share minus league share per kind (positive = takes
    more of that kind than the league). `gated` is True when the sample clears
    the split-half-derived minimum for its level; a caller must not render a
    share read when it is False.
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    lg = kind_table(shots, taxonomy)
    if player_id is not None:
        tbl = player_table(player_id, shots=shots, taxonomy=taxonomy)
        level, min_att = "player", MIN_PLAYER_SHARE_ATT
    else:
        tbl = team_table(team_id, shots=shots, offense=offense,
                         taxonomy=taxonomy)
        level, min_att = "team", MIN_TEAM_SHARE_ATT
    n = tbl["_meta"]["located"]
    cells, _, _, _ = TAXONOMIES[taxonomy]
    delta = {k: ((tbl[k]["share"] - lg[k]["share"])
                 if tbl[k]["share"] is not None and lg[k]["share"] is not None
                 else None)
             for k in cells}
    return {"table": tbl, "league": lg, "delta": delta, "n_located": n,
            "gated": n >= min_att, "min_att": min_att, "level": level,
            "taxonomy": taxonomy}


#: The two cells the verdict compares, per taxonomy: the good look, and the one
#: a team takes too many of. Under the depth cut the problem band is wider
#: (every 2 outside 4 ft, 37.5% of the book at 0.548 PPS) and the gap it opens
#: against the rim is correspondingly larger — +0.538 against the 5-kind cut's
#: +0.517 — because the midrange the kind cut split off is no better than the
#: floater and merging them stopped pretending otherwise.
VERDICT_PAIR = {"kind": ("rim", "floater"), "band": ("rim04", "two419")}


def conversion_value(league, taxonomy="kind"):
    """League points-per-shot gap between a rim look and the problem band.

    The unit behind the verdict: what one bad-band shot turned into a layup is
    worth, league-wide. Uses league rates rather than the team's own because a
    team's own per-cell PPS only reaches SB .67 while the SHARE it multiplies
    reaches .88 — so the reliable half of the sentence carries the team-specific
    part and the league carries the rate.
    """
    good, bad = VERDICT_PAIR[taxonomy]
    r, f = league[good]["pps"], league[bad]["pps"]
    if r is None or f is None:
        return None
    return r - f


def excess_floaters(d, league=None):
    """How many more floaters this unit took than a league-average diet would.

    Measured against the LEAGUE share rather than against zero, because zero
    floaters is not an available option for any team and a sentence built on it
    would overstate by roughly a factor of four. The share used is shrunk toward
    the league by SHARE_K so a thin sample cannot manufacture a big excess.
    """
    lg = league or d["league"]
    tbl = d["table"]
    n = d["n_located"]
    _, bad = VERDICT_PAIR[d.get("taxonomy", "kind")]
    if not n or lg[bad]["share"] is None:
        return None
    raw = tbl[bad]["share"]
    if raw is None:
        return None
    lgs = lg[bad]["share"]
    shrunk = (raw * n + lgs * SHARE_K) / (n + SHARE_K)
    return {"share": raw, "share_shrunk": shrunk, "league_share": lgs,
            "n": n, "excess": (shrunk - lgs) * n}


def verdict(team_id=None, player_id=None, gender=None, game_ids=None,
            events=None, shots=None, games=None, taxonomy=None):
    """The coach sentence, or [] when the evidence does not support one.

    Shape: the points-on-the-table line first, the league-comparison diet line
    under it as evidence — verdict first, evidence beneath, per house style.
    Returns a list of dicts {"text", "tone", "n", "confidence"} so the caller
    renders rather than parses.

    Says nothing at all below the gate. That is the whole point of the gate.
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    taxonomy = taxonomy or DISPLAY_TAXONOMY
    d = diet(team_id=team_id, player_id=player_id, shots=shots,
             taxonomy=taxonomy)
    if not d["gated"]:
        return []
    lg, tbl = d["league"], d["table"]
    good, bad = VERDICT_PAIR[taxonomy]
    gap = conversion_value(lg, taxonomy)
    ex = excess_floaters(d)
    if gap is None or ex is None or ex["excess"] <= 0:
        return []

    n = d["n_located"]
    pts = ex["excess"] * gap
    per_game = (pts / games) if games else None
    conf = "solid" if n >= d["min_att"] * 2 else "directional"

    # Materiality, not just sample — see MIN_VERDICT_* above.
    if (ex["share_shrunk"] - ex["league_share"]) < MIN_VERDICT_SHARE_DELTA:
        return []
    if per_game is not None:
        if per_game < MIN_VERDICT_PTS_PER_GAME:
            return []
    elif pts < MIN_VERDICT_PTS_TOTAL:
        return []

    # Each taxonomy gets its own noun: the kind cut has a word a coach already
    # uses ("floater"), the depth cut does not and must name the distance.
    subject, where = ((f"shot {BAND_PROSE[bad]}", BAND_PROSE[bad])
                      if taxonomy == "band" else ("floater", "from 4-10 feet"))
    lines = [{
        "text": (
            f"Every {subject} you turn into a layup is worth "
            f"{gap:+.2f} points. You take {tbl[bad]['n']} of them — "
            f"{ex['excess']:.0f} more than a league-average diet — which is "
            f"{pts:.0f} {'point' if round(pts) == 1 else 'points'} left on "
            f"the floor"
            + (f", about {per_game:.1f} a game." if per_game else ".")
        ),
        "tone": "bad", "n": n, "confidence": conf,
    }]

    fshare, lshare = ex["share"], ex["league_share"]
    fg = tbl[bad]["fg"]
    ev = (f"{fshare * 100:.0f}% of your shots come {where}"
          + (f", where you shoot {fg * 100:.0f}%" if fg is not None else "")
          + f". The league takes {lshare * 100:.0f}% there. "
            f"At the rim the league is at {lg[good]['pps']:.2f} points a shot; "
            f"in that band it is {lg[bad]['pps']:.2f}.")
    lines.append({"text": ev, "tone": "info", "n": n, "confidence": conf})
    return lines
