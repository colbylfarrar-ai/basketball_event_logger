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

#: Ordered for display: worst-to-best is not the order a coach reads, distance is.
KINDS = ("rim", "floater", "mid", "corner3", "abovebreak3")

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


def _blank():
    return {"n": 0, "fgm": 0, "pts": 0.0}


def _finish(agg, located):
    """Turn raw {kind: {n,fgm,pts}} counters into the display dict.

    `share` is over LOCATED attempts only (unknown cannot be assigned a kind, so
    including it in the denominator would shrink every share by the coverage
    rate). Rates are None below MIN_KIND_RATE_ATT rather than being rounded into
    a number a caller might print.
    """
    out = {}
    for k in (*KINDS, UNKNOWN):
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
            "label": KIND_LABELS[k],
        }
    return out


def kind_table(shots):
    """{kind: {n, fgm, pts, share, fg, pps, rated, label}} over a shot list.

    `shots` is a located_shots()/mapped_shots() list. Adds a "_meta" key with
    the located / total counts so every caller can print its own coverage
    instead of guessing at it.
    """
    agg = defaultdict(_blank)
    located = 0
    for s in shots:
        k = classify_shot(s)
        a = agg[k]
        a["n"] += 1
        if k != UNKNOWN:
            located += 1
        if s.get("make"):
            a["fgm"] += 1
            a["pts"] += float(s.get("value") or 2)
    out = _finish(agg, located)
    total = sum(a["n"] for a in agg.values())
    out["_meta"] = {
        "total": total,
        "located": located,
        "located_share": (located / total) if total else None,
    }
    return out


def league_table(gender=None, game_ids=None, events=None, shots=None):
    """The league-wide kind table — the baseline every team read compares to.

    Pooled across every tracked game, which is the only level this book can fit
    a stable per-kind rate at.
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    return kind_table(shots)


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
               offense=True):
    """Kind table for one team's own shots (offense) or its opponents' (defense).

    The defensive view is what each team CONCEDES by kind, which is the read
    behind "our 2-3 gives up rim".
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    mine = [s for s in shots
            if (s.get("team_id") == team_id) == bool(offense)
            and s.get("team_id") is not None]
    return kind_table(mine)


def player_table(player_id, gender=None, game_ids=None, events=None, shots=None):
    """Kind table for one player's shots.

    SHARES here are trustworthy above MIN_PLAYER_SHARE_ATT. The per-kind `fg`
    and `pps` are gated by MIN_KIND_RATE_ATT and will almost always be None at
    player level in this book — that is correct, not a bug. See the docstring's
    reliability table: player floater FG% has r=.078 against itself.
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    return kind_table([s for s in shots if s.get("player_id") == player_id])


def diet(team_id=None, player_id=None, gender=None, game_ids=None, events=None,
         shots=None, offense=True):
    """A team's or player's kind SHARES against the league's, with the gate.

    Returns {"table", "league", "delta", "n_located", "gated", "min_att",
    "level"} where `delta` is share minus league share per kind (positive = takes
    more of that kind than the league). `gated` is True when the sample clears
    the split-half-derived minimum for its level; a caller must not render a
    share read when it is False.
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    lg = kind_table(shots)
    if player_id is not None:
        tbl = player_table(player_id, shots=shots)
        level, min_att = "player", MIN_PLAYER_SHARE_ATT
    else:
        tbl = team_table(team_id, shots=shots, offense=offense)
        level, min_att = "team", MIN_TEAM_SHARE_ATT
    n = tbl["_meta"]["located"]
    delta = {k: ((tbl[k]["share"] - lg[k]["share"])
                 if tbl[k]["share"] is not None and lg[k]["share"] is not None
                 else None)
             for k in KINDS}
    return {"table": tbl, "league": lg, "delta": delta, "n_located": n,
            "gated": n >= min_att, "min_att": min_att, "level": level}


def conversion_value(league):
    """League points-per-shot gap between a rim look and a floater.

    The unit behind the verdict: what one floater turned into a layup is worth,
    league-wide. Uses league rates rather than the team's own because per-team
    floater PPS only reaches SB .67 while the SHARE it multiplies reaches .74 —
    so the reliable half of the sentence carries the team-specific part and the
    league carries the rate.
    """
    r, f = league["rim"]["pps"], league["floater"]["pps"]
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
    if not n or lg["floater"]["share"] is None:
        return None
    raw = tbl["floater"]["share"]
    if raw is None:
        return None
    lgs = lg["floater"]["share"]
    shrunk = (raw * n + lgs * SHARE_K) / (n + SHARE_K)
    return {"share": raw, "share_shrunk": shrunk, "league_share": lgs,
            "n": n, "excess": (shrunk - lgs) * n}


def verdict(team_id=None, player_id=None, gender=None, game_ids=None,
            events=None, shots=None, games=None):
    """The coach sentence, or [] when the evidence does not support one.

    Shape: the points-on-the-table line first, the league-comparison diet line
    under it as evidence — verdict first, evidence beneath, per house style.
    Returns a list of dicts {"text", "tone", "n", "confidence"} so the caller
    renders rather than parses.

    Says nothing at all below the gate. That is the whole point of the gate.
    """
    if shots is None:
        shots = _shots(gender, game_ids, events)
    d = diet(team_id=team_id, player_id=player_id, shots=shots)
    if not d["gated"]:
        return []
    lg, tbl = d["league"], d["table"]
    gap = conversion_value(lg)
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

    lines = [{
        "text": (
            f"Every floater you turn into a layup is worth "
            f"{gap:+.2f} points. You take {tbl['floater']['n']} of them — "
            f"{ex['excess']:.0f} more than a league-average diet — which is "
            f"{pts:.0f} {'point' if round(pts) == 1 else 'points'} left on "
            f"the floor"
            + (f", about {per_game:.1f} a game." if per_game else ".")
        ),
        "tone": "bad", "n": n, "confidence": conf,
    }]

    fshare, lshare = ex["share"], ex["league_share"]
    fg = tbl["floater"]["fg"]
    ev = (f"{fshare * 100:.0f}% of your shots come from 4-10 feet"
          + (f", where you shoot {fg * 100:.0f}%" if fg is not None else "")
          + f". The league takes {lshare * 100:.0f}% there. "
            f"At the rim the league is at {lg['rim']['pps']:.2f} points a shot; "
            f"in that band it is {lg['floater']['pps']:.2f}.")
    lines.append({"text": ev, "tone": "info", "n": n, "confidence": conf})
    return lines
