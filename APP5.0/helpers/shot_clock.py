"""
shot_clock.py — where in the possession a team's offense actually happens.

`possession_secs` is non-NULL on every event row and is read in a dozen files,
always as a mean. A mean hides the only thing the field is good for. Bucketed
over the 2025-2026 production book (63 tracked games, 7,808 clean possessions):

    early (<7s)     n=1,978   PPP 0.741
    mid   (7-15s)   n=3,265   PPP 0.601
    late  (16-35s)  n=2,565   PPP 0.604

Getting into offense early is worth +0.138 points per possession, and NOTHING
after the first seven seconds differs at all — mid and late land within 0.003 of
each other. The whole effect lives in the early band.

It is not just fast breaks. Excluding every `play_type='transition'` row
(n=6,494) the early band still carries +0.104 over everything later:

    early n=1,297 PPP 0.709   mid n=2,655 PPP 0.604   late n=2,542 PPP 0.605

which is the coachable version of the read: hunt the first good look; after
seven seconds the possession is worth the same whenever you shoot it.

WHY THE CUTS ARE WHERE THEY ARE. 7s is the measured knee, not a convention —
it is where the PPP series stops changing. 15s splits what remains in half so
"mid" and "late" are reportable separately, which is how the read earns the
claim that they do not differ. Neither is tuned to make a verdict fire.

Pure data layer: no streamlit, no DB — callers hand in the events they already
fetched (prod is 1 vCPU and this read rides an existing pass).
"""
from __future__ import annotations

from collections import defaultdict


#: The measured knee. Below this a possession is worth ~0.14 PPP more; above it
#: the series is flat, which is why there is no "very late" band.
EARLY_MAX = 7

#: Splits everything after the knee into two reportable halves. Its only job is
#: to let the read SHOW that mid and late do not differ.
MID_MAX = 15

#: Above this a `possession_secs` value is a clock that was never reset rather
#: than a long possession — a 35-second shot clock cannot be beaten honestly.
SANE_MAX = 35

BUCKETS = ("early", "mid", "late")

LABELS = {"early": f"first {EARLY_MAX}s",
          "mid": f"{EARLY_MAX}-{MID_MAX}s",
          "late": f"{MID_MAX + 1}s+"}


def bucket(secs):
    """Which band a possession's elapsed clock falls in — None when unusable.

    0 and NULL both mean "no clock on this possession" (~16% of rows), and a
    value past SANE_MAX means the clock did not get reset. Neither is a short
    possession, so both leave the denominator rather than counting as one.
    """
    if secs is None:
        return None
    try:
        s = float(secs)
    except (TypeError, ValueError):
        return None
    if s <= 0 or s > SANE_MAX:
        return None
    if s < EARLY_MAX:
        return "early"
    return "mid" if s <= MID_MAX else "late"


def _blank():
    return {b: {"poss": 0, "pts": 0} for b in BUCKETS}


def _finish(raw):
    """Counts -> {bucket: {poss, pts, PPP, share}} plus a `poss` total."""
    total = sum(v["poss"] for v in raw.values())
    out = {}
    for b in BUCKETS:
        n, p = raw[b]["poss"], raw[b]["pts"]
        out[b] = {"poss": n, "pts": p,
                  "PPP": (p / n) if n else None,
                  "share": (n / total) if total else None}
    out["poss"] = total
    return out


def clock_profile(events, team_id=None, exclude_transition=False):
    """Possession value by shot-clock band.

    `team_id` scopes to that team's OWN offense; None pools the whole pass (the
    league baseline). `exclude_transition` drops `play_type='transition'` rows —
    the confound check, so a team that simply runs a lot does not read as a team
    that hunts early offense in the half court.

    Possessions are the app's locked rule (FGA + TOV), so this counts the same
    denominator every other PPP in the app does.
    """
    raw = _blank()
    for e in events or ():
        if e.get("event_type") not in ("shot", "turnover"):
            continue
        st = e.get("shooter_team_id")
        if st is None or (team_id is not None and st != team_id):
            continue
        if exclude_transition and e.get("play_type") == "transition":
            continue
        b = bucket(e.get("possession_secs"))
        if b is None:
            continue
        raw[b]["poss"] += 1
        if e.get("event_type") == "shot" and e.get("shot_result") == "make":
            raw[b]["pts"] += 3 if e.get("shot_type") == 3 else 2
    return _finish(raw)


def league_early_counts(events, min_poss=60):
    """{team_id: (early_poss, total_poss)} for every team in the pass.

    Counts, not shares, because the read that consumes them has to know how many
    possessions each share rests on — see `early_z`. Teams under `min_poss`
    clean possessions are dropped rather than shrunk: a share off 20 possessions
    is not a tempo, and it would distort the spread this feeds.
    """
    raw = defaultdict(_blank)
    for e in events or ():
        if e.get("event_type") not in ("shot", "turnover"):
            continue
        st = e.get("shooter_team_id")
        if st is None:
            continue
        b = bucket(e.get("possession_secs"))
        if b is None:
            continue
        raw[st][b]["poss"] += 1
    out = {}
    for tid, r in raw.items():
        tot = sum(v["poss"] for v in r.values())
        if tot >= min_poss:
            out[tid] = (r["early"]["poss"], tot)
    return out


def league_early_shares(events, min_poss=60):
    """{team_id: early share} — the plain rates, for display and for callers
    that only need the distribution's shape."""
    return {t: e / n for t, (e, n) in
            league_early_counts(events, min_poss=min_poss).items()}


def early_z(share, poss, counts):
    """How far a team's early share sits from the field, in units that account
    for how thin the team's own sample is.

    A plain (share - mean) / sd is the wrong test here and fails in the
    direction that matters. The observed spread between teams mixes real
    differences in tempo with the sampling noise of teams that have played twice
    — and the noisy ones sit furthest from the mean by construction. Measured on
    the 2025-2026 book, the plain z fired for four teams and every one of them
    had one or two tracked games, while Adair Girls (26 games, 1,706
    possessions) and Sequoyah Boys (15 games) never cleared it. That is a read
    that reports sample size and calls it style.

    So: split the observed variance into the part that is real and the part that
    is sampling, the standard random-effects decomposition —

        tau^2 = var(observed shares) - mean(se_i^2),   se_i^2 = p_i(1-p_i)/n_i
        z_i   = (p_i - mu) / sqrt(tau^2 + se_i^2)

    A team with a long book is judged against tau (the real between-team
    spread); a team with 95 possessions carries its own +/-3pp into the
    denominator and has to be genuinely extreme to clear. Returns None when the
    pool cannot support the estimate.
    """
    vals = [e / n for e, n in counts.values()]
    if len(vals) < 4 or not poss:
        return None
    mu = sum(vals) / len(vals)
    var_obs = sum((v - mu) ** 2 for v in vals) / len(vals)
    mean_se2 = sum((e / n) * (1 - e / n) / n
                   for e, n in counts.values()) / len(counts)
    tau2 = max(var_obs - mean_se2, 0.0)
    se2 = share * (1.0 - share) / poss
    denom = (tau2 + se2) ** 0.5
    if not denom:
        return None
    return (share - mu) / denom, mu
