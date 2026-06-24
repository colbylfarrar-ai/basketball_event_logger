"""
courtside.py — live, in-game decision tooling (Tier 1, ML_LAYER_ROADMAP).

The app's first piece of IN-GAME analytics: while a game is being tracked, surface
the three reads a coach makes on the bench in real time —

  • leverage_now  — Leverage Index: how much a basket would swing win probability
                    *right now* (the textbook "is this a season-defining possession"
                    meter). Same WP-swing math as the un-normalized li_at inside
                    wpa.game_wpa, reused live.
  • current_run   — is the OPPONENT on a run, and how much has it cost us in win
                    probability? The "consider a timeout" trigger, built on the same
                    possession-walk gameflow.scoring_runs uses.
  • late_game     — in the closing minutes, the win-prob of the canonical late-game
                    choices (foul up 3, foul-vs-guard, milk-vs-attack). Ships
                    LEAGUE-RATE-FIRST (opponent rates only when they're tracked &
                    dense), per the roadmap's honesty caveat.
  • comeback      — trailing-team feasibility gauge: points needed, possessions left
                    at the current pace, required PPP vs the season baseline.

Everything here is DETERMINISTIC (closed-form WP + a tiny scenario tree) so it is
exactly as data-safe as win_probability — no fitting, scales with games. Pure data
layer: reuses helpers.win_probability + helpers.gameflow + helpers.team_analytics;
no streamlit, no scipy. All `margin` args are from the SUBJECT team's perspective
(team − opponent) unless noted; pass the home margin for the home-perspective WP.
"""
from __future__ import annotations

import helpers.win_probability as WP
import helpers.team_analytics as TA


# Leverage tiers off the raw WP-swing of a 2-pt basket (probability units, 0–~0.2).
# A 2-pt swing late in a one-possession game moves WP ~0.10+; early or in a blowout
# it barely moves it. Thresholds are deliberately coarse (a bench glance, not a
# decimal). Tunable.
LEVERAGE_TIERS = (
    (0.10, "🔥 Season-defining"),
    (0.06, "High"),
    (0.03, "Moderate"),
    (0.0,  "Low"),
)

# League-average free-throw / three-point rates — the honest default when the
# opponent isn't tracked densely enough for their own rates (roadmap: league-rate
# first). HS ballpark; tunable / overridable per call.
LEAGUE_FT = 0.66
LEAGUE_3P = 0.31


def _tier(li):
    for thresh, label in LEVERAGE_TIERS:
        if li >= thresh:
            return label
    return "Low"


def leverage_now(margin, secs_left, total_secs=WP.GAME_SECONDS,
                 edge=0.0, sd_full=WP.SD_FULL, li_mean=None):
    """Leverage right now = |WP(margin+2) − WP(margin−2)| at `secs_left` (the
    un-normalized swing a single 2-pt basket would cause). `margin` is the subject
    team's lead (team − opp); `edge` is the pre-game spread in the same perspective.

    Returns {"li", "tier", "wp", "li_norm"}: `li` raw swing (prob units), `tier` a
    coarse label, `wp` the team's current win probability, and `li_norm` = li/li_mean
    when a game-average leverage `li_mean` is supplied (mirrors wpa's per-game-mean-
    1.0 normalization), else None."""
    hi = WP.win_prob(margin + 2, secs_left, total_secs, edge, sd_full)
    lo = WP.win_prob(margin - 2, secs_left, total_secs, edge, sd_full)
    li = abs(hi - lo)
    wp = WP.win_prob(margin, secs_left, total_secs, edge, sd_full)
    return {
        "li": round(li, 4),
        "tier": _tier(li),
        "wp": round(wp, 4),
        "li_norm": round(li / li_mean, 2) if li_mean else None,
    }


def _scoring_stream(events):
    """[(elapsed, team_id, pts)] for every made FG/FT, chronological. FTs resolve
    the scoring team via the player→team map (a made FT carries no shooter_team_id
    join the way a shot does). Mirrors gameflow.scoring_runs' stream."""
    import helpers.gameflow as GF
    ptmap = TA._player_team_map()
    out = []
    for e in sorted(events, key=GF.elapsed):
        team = pts = None
        if e["event_type"] == "shot" and e["shot_result"] == "make":
            team = e["shooter_team_id"]
            pts = 3 if e["shot_type"] == 3 else 2
        elif e["event_type"] == "free_throw" and e["shot_result"] == "make":
            team = ptmap.get(e["primary_player_id"])
            pts = 1
        if team is not None and pts:
            out.append((GF.elapsed(e), team, pts))
    return out


def current_run(events, team_id, total_secs=None, edge=0.0, sd_full=WP.SD_FULL):
    """The ACTIVE trailing scoring run at the end of `events` (this game so far) and
    what it has cost `team_id` in win probability.

    Walks scoring events; the current run = the unbroken streak of points by ONE team
    ending at the last score. Returns None if there's no scoring yet, else
    {"team_id", "is_opponent", "points", "start", "end", "wp_then", "wp_now",
     "wp_cost"} where wp_* are `team_id`'s win probability at the run's start vs now
    and wp_cost = wp_then − wp_now (positive = the run has hurt us). `team_id` frames
    the margin; `edge` is the pre-game spread from team_id's perspective."""
    stream = _scoring_stream(events)
    if not stream:
        return None

    # subject-team margin trace, and the index where the trailing run began
    run_team = stream[-1][1]
    run_pts = 0
    start_i = len(stream)
    for i in range(len(stream) - 1, -1, -1):
        if stream[i][1] == run_team:
            run_pts += stream[i][2]
            start_i = i
        else:
            break

    if total_secs is None:
        total_secs = max((t for t, _, _ in stream), default=WP.GAME_SECONDS) or WP.GAME_SECONDS

    def margin_at(i):
        m = 0
        for t, team, pts in stream[: i + 1]:
            m += pts if team == team_id else -pts
        return m

    # margin/clock just BEFORE the run started vs at the latest score
    start_t = stream[start_i][0]
    end_t = stream[-1][0]
    m_then = margin_at(start_i - 1) if start_i > 0 else 0
    m_now = margin_at(len(stream) - 1)
    wp_then = WP.win_prob(m_then, max(total_secs - start_t, 0), total_secs, edge, sd_full)
    wp_now = WP.win_prob(m_now, max(total_secs - end_t, 0), total_secs, edge, sd_full)
    return {
        "team_id": run_team,
        "is_opponent": run_team != team_id,
        "points": run_pts,
        "start": start_t,
        "end": end_t,
        "wp_then": round(wp_then, 4),
        "wp_now": round(wp_now, 4),
        "wp_cost": round(wp_then - wp_now, 4),
    }


def run_alert(events, team_id, min_run=6, min_wp_cost=0.08, **kw):
    """Convenience wrapper: returns the current run dict WITH an `alert` flag set
    when the opponent's active run is both sizable (`min_run`+ pts) and has actually
    dented our win probability (`wp_cost` ≥ `min_wp_cost`) — the "call a timeout"
    trigger. Returns None when there's no scoring yet."""
    run = current_run(events, team_id, **kw)
    if run is None:
        return None
    run["alert"] = bool(
        run["is_opponent"] and run["points"] >= min_run and run["wp_cost"] >= min_wp_cost)
    return run


def comeback_gauge(margin, secs_left, sec_per_poss=15.0,
                   team_ppp=1.0, opp_ppp=1.0):
    """Trailing-team feasibility gauge. `margin` = subject team's lead (negative when
    trailing). Returns None when not trailing, else {"deficit","poss_left","your_poss",
    "req_ppp_margin","exp_ppp_margin","feasible","label"}.

    poss_left = total remaining possessions (both teams) at the current pace; your_poss
    ≈ half. To erase `deficit` you must out-score by deficit over your possessions →
    `req_ppp_margin` per your possession; `exp_ppp_margin` = team_ppp − opp_ppp is what
    the season says you net per trip. feasible when the required margin is within reach
    of the expected one (with a little slack)."""
    deficit = -margin
    if deficit <= 0:
        return None
    sec_per_poss = sec_per_poss if sec_per_poss and sec_per_poss > 0 else 15.0
    poss_left = max(secs_left, 0) / sec_per_poss
    your_poss = poss_left / 2.0
    req = (deficit / your_poss) if your_poss > 0 else float("inf")
    exp = team_ppp - opp_ppp
    # "reachable" = the required per-possession net is no worse than your expected net
    # plus a modest variance allowance that grows as the game shortens (fewer trips =
    # more swing). Coarse + honest, not a precise probability.
    slack = 0.35 + (0.5 / your_poss if your_poss > 0 else 1.0)
    feasible = req <= exp + slack
    if your_poss < 1:
        label = "Out of possessions"
    elif req <= exp:
        label = "Very live — on pace"
    elif feasible:
        label = "Live — need a small run"
    elif req <= exp + 2 * slack:
        label = "Long shot — need a big run"
    else:
        label = "Effectively out of reach"
    return {
        "deficit": deficit,
        "poss_left": round(poss_left, 1),
        "your_poss": round(your_poss, 1),
        "req_ppp_margin": round(req, 2),
        "exp_ppp_margin": round(exp, 2),
        "feasible": feasible,
        "label": label,
    }


def foul_up_3(secs_left, total_secs=WP.GAME_SECONDS, edge=0.0, sd_full=WP.SD_FULL,
              opp_ft=LEAGUE_FT, opp_3p=LEAGUE_3P):
    """The single most second-guessed late call: leading by 3 on defense in the final
    seconds — foul (concede 2 from the line, deny the tying three) vs guard (risk the
    three)? Returns the win-prob of each choice for the LEADING team and the
    recommendation. League FT/3P rates by default; pass the opponent's tracked rates
    when dense.

    Model (subject = the team UP 3, with the ball-on-defense moment):
      • GUARD: opponent attempts a 3. Make (opp_3p) → tie → ~coinflip-ish in OT
        (WP at margin 0). Miss (1−opp_3p) → we win (clock ~expires).
      • FOUL (with enough time only): send to line up 3. Two makes → up 1, opp must
        foul/score again; one make + intentional miss rebound chaos; etc. Simplified
        to the dominant branch: they make 1, miss the 2nd intentionally and scramble —
        net they very rarely tie. We approximate FOUL win-prob as 1 − P(they tie),
        with P(tie) ≈ opp_ft·(1−opp_ft)·0.5 (make 1, miss 2nd, put-back/3 to tie) —
        small. The point isn't a perfect tree; it's that fouling collapses the tying-
        three branch."""
    sl = max(secs_left, 0)
    # GUARD: let them shoot a 3
    wp_make = WP.win_prob(0, WP._OT_SECONDS, total_secs, edge, sd_full)   # tie -> OT-ish
    wp_miss = 1.0                                                          # buzzer, we win
    guard_wp = opp_3p * wp_make + (1 - opp_3p) * wp_miss
    # FOUL: deny the three; rough P(they still tie)
    p_tie = max(0.0, opp_ft * (1 - opp_ft) * 0.5)
    foul_wp = 1.0 - p_tie
    # fouling needs a little time to be legal/clean; under ~2s it's a wash
    practical = sl >= 3
    rec = ("foul" if practical and foul_wp >= guard_wp else "guard")
    return {
        "guard_wp": round(guard_wp, 3),
        "foul_wp": round(foul_wp, 3),
        "recommend": rec,
        "note": ("Foul before the shot — concede 2, deny the tying three."
                 if rec == "foul" else
                 "Guard the line — don't risk a foul on a three; make them earn it."),
        "rates": {"opp_ft": opp_ft, "opp_3p": opp_3p, "league_default": opp_ft == LEAGUE_FT},
    }


def late_game(margin, secs_left, total_secs=WP.GAME_SECONDS, edge=0.0,
              sd_full=WP.SD_FULL, on_defense=None, **rate_kw):
    """Top-level late-game card. Returns the relevant decision read for the current
    `margin` (subject team) + `secs_left`. v1 covers the highest-value, cleanest
    cases; everything else returns generic protect/attack guidance + the comeback
    gauge. `on_defense` (bool) disambiguates the up-3 foul case when known."""
    out = {"wp": leverage_now(margin, secs_left, total_secs, edge, sd_full)}
    # leading by exactly 3, late, on defense -> the foul-up-3 decision
    if margin == 3 and secs_left <= 35 and (on_defense is None or on_defense):
        out["foul_up_3"] = foul_up_3(secs_left, total_secs, edge, sd_full, **{
            k: v for k, v in rate_kw.items() if k in ("opp_ft", "opp_3p")})
    if margin < 0:
        out["comeback"] = comeback_gauge(
            margin, secs_left,
            sec_per_poss=rate_kw.get("sec_per_poss", 15.0),
            team_ppp=rate_kw.get("team_ppp", 1.0),
            opp_ppp=rate_kw.get("opp_ppp", 1.0))
    return out
